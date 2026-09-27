"""Bounded phase-selective delivery regressions. SPDX-License-Identifier: AGPL-3.0-only"""
from concurrent.futures import CancelledError
import importlib.util
import json
import math
from pathlib import Path
import sys
import threading
import unittest

PATH = Path(__file__).resolve().parents[1]/"tools/check_i01_delivery.py"
SPEC = importlib.util.spec_from_file_location("i01_delivery_control", PATH)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


class DeliveryTests(unittest.TestCase):
    def law(self, *, tref=300., latent=400000.):
        return m.MagmaticThermodynamics(("a",), [1000.], [latent],
            melting_temperature_k=1500., reference_temperature_k=tref,
            source_id="unit", provenance="analytical test")

    def split(self, alpha=.5, *, law=None, h=1280000000., mass=1000., **kwargs):
        return m.extract_liquid([[mass]], [h], law or self.law(),
                               fraction_of_available_liquid=alpha, **kwargs)

    def target(self):
        return m.EmplacementTarget(("cell",), [10.], [2800.], [1.],
            geometry_source="fixture", frame_id="f", datum_id="d", epoch_id="e")

    def place(self, split, **kwargs):
        return m.place_liquid(split, self.target(), source_id="source",
            transfer_id="one-transfer", liquid_density_kg_m3=2700.,
            mode="underplating", **kwargs)

    def test_phase_specific_not_bulk_enthalpy(self):
        result = self.split()
        self.assertAlmostEqual(result.liquid.mass_kg[0], 100.)
        self.assertAlmostEqual(result.liquid.enthalpy_j[0], 160000000.)
        self.assertAlmostEqual(result.remaining.enthalpy_j[0], 1120000000.)
        self.assertAlmostEqual(result.remaining.liquid_fraction[0], 1/9)
        self.assertEqual(result.remaining.temperature_k, (1500.,))
        self.assertEqual(result.liquid.phase, ("liquid",))
        self.assertNotEqual(result.liquid.enthalpy_j[0], 1280000000.*.1)

    def test_no_extraction_and_dry_and_empty(self):
        for mass, h, alpha in [(1000., 1280000000., 0.),
                               (1000., 1100000000., 1.), (0., 0., 1.)]:
            split = self.split(alpha, mass=mass, h=h)
            self.assertEqual(split.liquid.mass_kg[0], 0.)
            self.assertEqual(split.liquid.enthalpy_j[0], 0.)
            self.assertEqual(split.remaining.enthalpy_j[0], h)
            with self.assertRaisesRegex(ValueError, "no liquid delivery"):
                self.place(split)

    def test_all_available_not_all_source(self):
        result = self.split(1.)
        self.assertAlmostEqual(result.liquid.mass_kg[0], 200.)
        self.assertAlmostEqual(result.remaining.mass_kg[0], 800.)
        self.assertEqual(result.remaining.phase, ("solid",))

    def test_superheated_exhaustion(self):
        result = self.split(1., h=1700000000.)
        self.assertEqual(result.liquid.temperature_k, (1600.,))
        self.assertEqual(result.remaining.phase, ("empty",))
        self.assertEqual(result.remaining.enthalpy_j[0], 0.)
        self.assertEqual(result.remaining.temperature_k, (None,))

    def test_invalid_fraction_phase_and_source(self):
        for alpha in (-.01, 1.001, math.nan, math.inf, True, "0.5"):
            with self.assertRaises(ValueError):
                self.split(alpha)
        with self.assertRaisesRegex(ValueError, "zero-latent"):
            self.split(law=self.law(latent=0.))
        with self.assertRaises(ValueError):
            self.split(mass=-1.)
        with self.assertRaises(ValueError):
            m.extract_liquid([[1.], [1.]], [1280000., 1280000.], self.law(),
                             fraction_of_available_liquid=.5)

    def test_step_partition_and_component_conservation(self):
        law = m.MagmaticThermodynamics(("a", "b"), [1000., 1500.], [400000., 600000.],
            melting_temperature_k=1500., reference_temperature_k=300.,
            source_id="two", provenance="synthetic")
        mass = m.np.array([[6000., 4000.]])
        h = m._enthalpy(mass[0], 1500., .2, law)
        first = m.extract_liquid(mass, [h], law, fraction_of_available_liquid=.5)
        second = m.extract_liquid(first.remaining.component_mass_kg,
            first.remaining.enthalpy_j, law, fraction_of_available_liquid=1.)
        whole = m.extract_liquid(mass, [h], law, fraction_of_available_liquid=1.)
        m.np.testing.assert_allclose(first.liquid.component_mass_kg+second.liquid.component_mass_kg,
                                    whole.liquid.component_mass_kg, rtol=1e-12, atol=0)
        m.np.testing.assert_allclose(second.remaining.component_mass_kg+whole.liquid.component_mass_kg,
                                    mass, rtol=1e-12, atol=0)
        self.assertAlmostEqual((first.liquid.enthalpy_j[0]+second.liquid.enthalpy_j[0])
                               /whole.liquid.enthalpy_j[0], 1., places=12)

    def test_signed_datum_does_not_change_split(self):
        negative = self.split(law=self.law(tref=2000.), h=-420000000.)
        positive = self.split()
        self.assertEqual(negative.liquid.mass_kg[0], positive.liquid.mass_kg[0])
        self.assertEqual(negative.liquid.enthalpy_j[0], -10000000.)
        self.assertEqual(negative.remaining.temperature_k, positive.remaining.temperature_k)

    def test_immutable_inputs_and_outputs(self):
        mass, h = m.np.array([[1000.]]), m.np.array([1280000000.])
        result = m.extract_liquid(mass, h, self.law(), fraction_of_available_liquid=.5)
        self.assertEqual(mass[0, 0], 1000.)
        self.assertEqual(h[0], 1280000000.)
        with self.assertRaises(ValueError):
            result.remaining.component_mass_kg[0, 0] = 0.

    def test_cancel_and_budget_refuse_without_effect(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(CancelledError):
            self.split(cancel=event)
        budget = m.WorkBudget(16)
        with self.assertRaises(ValueError):
            self.split(budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_unrepresentable_debit_refused(self):
        with self.assertRaisesRegex(ValueError, "resolution"):
            self.split(1e-30)

    def test_native_placement_replay_and_heat_ownership(self):
        split = self.split()
        placed = self.place(split)
        self.assertAlmostEqual(placed.geometry[0, 0], 100/(2800*10))
        self.assertEqual(placed.descriptor()["heat_source_j"], 0.)
        self.assertEqual(placed.incoming[0, 1], split.liquid.enthalpy_j[0])
        m.accounting_entries((placed,))
        with self.assertRaises(ValueError):
            m.accounting_entries((placed, placed))
        phase = m.invert_enthalpy(placed.incoming_component_mass_kg,
                                  placed.incoming[:, 1], self.law())
        self.assertEqual(phase.phase, ("liquid",))

    def test_connected_case_and_declared_policy(self):
        spec = json.loads((m.ROOT/"cases/i01_delivery_v1.json").read_text())
        self.assertEqual(spec["policy"], m.POLICY)
        result = m.controls(spec)
        self.assertTrue(result["passed"])
        self.assertEqual(result["connected_w08"]["delivered_mass_kg"], 1000.)
        self.assertAlmostEqual(result["connected_w08"]["released_heat_j"], 1080000000.)


if __name__ == "__main__":
    unittest.main()
