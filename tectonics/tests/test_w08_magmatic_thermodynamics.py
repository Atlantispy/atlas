"""Focused independent controls for the W08 C06/A05 candidate."""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError
import threading
import unittest
from unittest.mock import patch

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.magmatic_thermodynamics import (MagmaticThermodynamics, invert_enthalpy,
    melt_source_fraction, reheat, thermodynamics_work_bytes)


def parameters(cp=(10.0,), latent=(100.0,), tref=300.0):
    return MagmaticThermodynamics(tuple("component-" + str(i) for i in range(len(cp))),
        cp, latent, melting_temperature_k=350.0, reference_temperature_k=tref,
        source_id="synthetic-C06-A05", provenance="W08 frozen synthetic analytic control")


class MagmaticThermodynamicsTests(unittest.TestCase):
    def test_identity_binds_exact_properties_order_and_provenance(self):
        p = parameters()
        self.assertEqual(p.thermodynamics_id, parameters().thermodynamics_id)
        self.assertEqual(len(p.thermodynamics_id), 64)
        for changed in (parameters(cp=(11.0,)), parameters(tref=299.0),
                        parameters(latent=(101.0,))):
            self.assertNotEqual(p.thermodynamics_id, changed.thermodynamics_id)
        base = dict(component_ids=("a", "b"), cp_j_kg_k=[10.0, 20.0],
                    latent_heat_j_kg=[100.0, 200.0], melting_temperature_k=350.0,
                    reference_temperature_k=300.0, source_id="x", provenance="p")
        original = MagmaticThermodynamics(**base)
        for delta in (dict(component_ids=("b", "a")), dict(melting_temperature_k=351.0),
                      dict(source_id="y"), dict(provenance="q")):
            self.assertNotEqual(original.thermodynamics_id,
                MagmaticThermodynamics(**(base | delta)).thermodynamics_id)
        state = invert_enthalpy([[2.0]], [0.0], p)
        heated = reheat([[2.0]], [0.0], [100.0], p).state
        conversion = melt_source_fraction([[2.0]], [0.0], 0.5, 600.0, p,
                                           liquid_temperature_k=350.0)
        for result in (state, heated, conversion.remaining, conversion.melted):
            self.assertEqual(result.thermodynamics_id, p.thermodynamics_id)
            self.assertEqual(result.enthalpy_source_id, p.thermodynamics_id)
            self.assertNotEqual(result.enthalpy_source_id, p.source_id)
        with self.assertRaises(FrozenInstanceError):
            p.thermodynamics_id = "changed"

    def test_dimension_and_independent_128_mib_work_bounds(self):
        with self.assertRaisesRegex(TectonicsError, "64 components"):
            parameters(cp=(10.0,) * 65, latent=(100.0,) * 65)
        p = parameters()
        large_parent = WorkBudget(1024 * 1024 * 1024)
        with self.assertRaisesRegex(TectonicsError, "64"):
            invert_enthalpy([[2.0]] * 65, [0.0] * 65, p, budget=large_parent)
        for shape in ((65, 1), (1, 65)):
            with self.assertRaisesRegex(TectonicsError, "64"):
                thermodynamics_work_bytes(*shape)
        # Current dimensions need far less space. Inject a future enlarged work
        # estimate to verify the independent child cap, without allocating it.
        with patch("atlas_tectonics.magmatic_thermodynamics.thermodynamics_work_bytes",
                   return_value=128 * 1024 * 1024 + 1):
            with self.assertRaises(MemoryLimitError):
                invert_enthalpy([[2.0]], [0.0], p, budget=large_parent)
        self.assertEqual(large_parent.reserved_bytes, 0)
        self.assertEqual(large_parent.peak_reserved_bytes, 0)

    def test_a05_unequal_heat_capacity_mixing(self):
        # 2*10*(400-300)+3*20*(300-300)=2000 J; Cp=80 J/K.
        p = parameters((10.0, 20.0), (0.0, 0.0))
        state = invert_enthalpy([[2.0, 3.0]], [2000.0], p)
        self.assertEqual(state.temperature_k, (325.0,))
        self.assertEqual(state.liquid_fraction, (None,))
        self.assertEqual(state.phase, ("single_phase",))
        self.assertEqual(state.mass_kg[0], 5.0)

    def test_a05_full_crystallisation_releases_2200_j(self):
        p = parameters()
        hot = invert_enthalpy([[2.0]], [2200.0], p)
        self.assertEqual(hot.temperature_k, (400.0,))
        cooled = reheat(hot.component_mass_kg, hot.enthalpy_j, [-2200.0], p)
        self.assertEqual(cooled.state.temperature_k, (300.0,))
        self.assertEqual(cooled.state.phase, ("solid",))
        self.assertEqual(cooled.applied_heat_j[0], -2200.0)
        np.testing.assert_array_equal(cooled.state.component_mass_kg, [[2.0]])

    def test_all_phase_branches_and_endpoints(self):
        state = invert_enthalpy([[2.0]] * 5, [0.0, 1000.0, 1100.0, 1200.0, 2200.0],
                                parameters())
        self.assertEqual(state.temperature_k, (300.0, 350.0, 350.0, 350.0, 400.0))
        self.assertEqual(state.liquid_fraction, (0.0, 0.0, 0.5, 1.0, 1.0))
        self.assertEqual(state.phase, ("solid", "solid", "two_phase", "liquid", "liquid"))

    def test_weighted_multicomponent_plateau(self):
        # Cp=80 J/K, L=800 J, Hsolidus=4000 J. All components share f=0.25.
        state = invert_enthalpy([[2.0, 3.0]], [4200.0],
                                parameters((10.0, 20.0), (100.0, 200.0)))
        self.assertEqual(state.temperature_k, (350.0,))
        self.assertEqual(state.liquid_fraction, (0.25,))

    def test_analytic_round_trip(self):
        p = parameters((10.0, 20.0), (100.0, 200.0))
        temperatures = [290.0, 350.0, 350.0, 350.0, 450.0]
        fractions = [0.0, 0.0, 0.3, 1.0, 1.0]
        energies = [80.0 * (t - 300.0) + 800.0 * f
                    for t, f in zip(temperatures, fractions)]
        state = invert_enthalpy([[2.0, 3.0]] * 5, energies, p)
        np.testing.assert_allclose(state.temperature_k, temperatures, rtol=0, atol=1e-12)
        np.testing.assert_allclose(state.liquid_fraction, fractions, rtol=0, atol=1e-14)

    def test_reference_origin_invariance_and_negative_enthalpy(self):
        masses = [[2.0], [2.0], [2.0]]
        a = invert_enthalpy(masses, [0.0, 1100.0, 2200.0], parameters(tref=300.0))
        b = invert_enthalpy(masses, [-2000.0, -900.0, 200.0], parameters(tref=400.0))
        self.assertEqual(a.temperature_k, b.temperature_k)
        self.assertEqual(a.liquid_fraction, b.liquid_fraction)
        self.assertEqual(a.phase, b.phase)

    def test_empty_semantics_are_exact(self):
        p = parameters()
        empty = invert_enthalpy([[0.0], [2.0]], [0.0, 0.0], p)
        self.assertEqual(empty.temperature_k, (None, 300.0))
        self.assertEqual(empty.liquid_fraction, (None, 0.0))
        self.assertEqual(empty.phase, ("empty", "solid"))
        with self.assertRaisesRegex(TectonicsError, "exactly zero"):
            invert_enthalpy([[0.0]], [np.nextafter(0.0, 1.0)], p)
        with self.assertRaisesRegex(TectonicsError, "exactly zero"):
            reheat([[0.0]], [0.0], [1.0], p)

    def test_input_detachment_and_result_descriptor_immutability(self):
        cp, latent, mass, energy = [10.0], [100.0], np.array([[2.0]]), np.array([1100.0])
        p = parameters(cp, latent)
        state = invert_enthalpy(mass, energy, p)
        cp[0], latent[0], mass[0, 0], energy[0] = 999.0, 999.0, 999.0, 999.0
        self.assertEqual(p.cp_j_kg_k[0], 10.0)
        self.assertEqual(state.temperature_k, (350.0,))
        self.assertEqual(state.component_mass_kg[0, 0], 2.0)
        for value in (p.cp_j_kg_k, p.latent_heat_j_kg, state.component_mass_kg,
                      state.enthalpy_j, state.mass_kg):
            with self.assertRaises(ValueError):
                value.setflags(write=True)
        descriptor = state.component_mass_kg
        descriptor.shape = (1,)
        self.assertEqual(state.component_mass_kg.shape, (1, 1))
        with self.assertRaises(FrozenInstanceError):
            state.phase = ("liquid",)

    def test_invalid_properties(self):
        for cp, latent, tref in (([0.0], [100.0], 300.0), ([True], [100.0], 300.0),
                                 ([np.inf], [100.0], 300.0), ([10.0], [-1.0], 300.0),
                                 ([10.0], [np.nan], 300.0), ([10.0], [100.0], -1.0)):
            with self.subTest(cp=cp, latent=latent, tref=tref), self.assertRaises(TectonicsError):
                parameters(cp, latent, tref)
        with self.assertRaises(TectonicsError):
            MagmaticThermodynamics(("x",), [10.0], [100.0], melting_temperature_k=0.0,
                reference_temperature_k=300.0, source_id="x", provenance="x")

    def test_invalid_shapes_values_and_temperature(self):
        p = parameters()
        for mass, energy in (([[-1.0]], [0.0]), ([[np.nan]], [0.0]),
                             ([[2.0]], [np.inf]), ([[True]], [0.0]),
                             ([[2.0, 1.0]], [0.0]), ([[2.0]], [[0.0]]),
                             ([[2.0]], [-6000.0]), ([[2.0]], [-6001.0]),
                             (np.ma.array([[2.0]], mask=False), [0.0])):
            with self.subTest(mass=mass, energy=energy), self.assertRaises(TectonicsError):
                invert_enthalpy(mass, energy, p)

    def test_overflow_and_unresolved_plateau_refuse(self):
        for mass, energy, p in (([[1e308]], [0.0], parameters()),
                               ([[1e-300]], [0.0], parameters((1e-300,), (100.0,))),
                               ([[1.0]], [500.0], parameters((10.0,), (1e-300,)))):
            with self.subTest(mass=mass), self.assertRaises(TectonicsError):
                invert_enthalpy(mass, energy, p)

    def test_heat_partition_equivalence(self):
        p = parameters()
        once = reheat([[2.0]], [0.0], [2200.0], p)
        first = reheat([[2.0]], [0.0], [1100.0], p)
        second = reheat(first.state.component_mass_kg, first.state.enthalpy_j, [1100.0], p)
        self.assertEqual(once.state.temperature_k, second.state.temperature_k)
        np.testing.assert_array_equal(once.state.enthalpy_j, second.state.enthalpy_j)
        self.assertEqual(first.state.liquid_fraction, (0.5,))

    def test_paid_finite_conversion_and_unused_heat(self):
        result = melt_source_fraction([[2.0]], [0.0], 0.5, 700.0, parameters(),
                                      liquid_temperature_k=350.0)
        self.assertEqual(result.heat_used_j, 600.0)
        self.assertEqual(result.heat_remaining_j, 100.0)
        self.assertEqual(result.remaining.mass_kg[0], 1.0)
        self.assertEqual(result.melted.mass_kg[0], 1.0)
        self.assertEqual(result.remaining.phase, ("solid",))
        self.assertEqual(result.melted.phase, ("liquid",))
        self.assertEqual(result.remaining.enthalpy_j[0] + result.melted.enthalpy_j[0], 600.0)
        np.testing.assert_array_equal(result.remaining.component_mass_kg
                                      + result.melted.component_mass_kg, [[2.0]])

    def test_full_conversion_and_no_second_melting(self):
        p = parameters()
        result = melt_source_fraction([[2.0]], [0.0], 1.0, 2200.0, p,
                                      liquid_temperature_k=400.0)
        self.assertEqual(result.remaining.phase, ("empty",))
        self.assertEqual(result.remaining.temperature_k, (None,))
        self.assertEqual(result.melted.temperature_k, (400.0,))
        with self.assertRaisesRegex(TectonicsError, "unambiguously solid"):
            melt_source_fraction(result.melted.component_mass_kg, result.melted.enthalpy_j,
                1.0, 2200.0, p, liquid_temperature_k=400.0)
        # Bulk extraction carries the already-paid enthalpy; inversion has no new cost.
        transferred = invert_enthalpy(result.melted.component_mass_kg,
                                       result.melted.enthalpy_j, p)
        self.assertEqual(transferred.enthalpy_j[0], 2200.0)

    def test_unpaid_and_unsupported_conversion_refuse(self):
        p = parameters()
        for fraction, heat, temperature in ((1.0, 2199.0, 400.0), (1.0, 0.0, 350.0),
                                            (1.1, 1e4, 400.0), (0.0, 1e4, 400.0),
                                            (1.0, 1e4, 300.0), (1.0, -1.0, 400.0)):
            with self.subTest(fraction=fraction, heat=heat), self.assertRaises(TectonicsError):
                melt_source_fraction([[2.0]], [0.0], fraction, heat, p,
                                      liquid_temperature_k=temperature)
        for energy, p in ((1100.0, parameters()), (0.0, parameters(latent=(0.0,)))):
            with self.assertRaisesRegex(TectonicsError, "unambiguously solid"):
                melt_source_fraction([[2.0]], [energy], 1.0, 1e4, p,
                                      liquid_temperature_k=400.0)

    def test_conversion_reference_origin_and_congruent_components(self):
        p = parameters((10.0, 20.0), (100.0, 200.0), tref=400.0)
        result = melt_source_fraction([[2.0, 3.0]], [-8000.0], 0.5, 4400.0, p,
                                      liquid_temperature_k=400.0)
        np.testing.assert_array_equal(result.melted.component_mass_kg, [[1.0, 1.5]])
        self.assertEqual(result.heat_used_j, 4400.0)
        self.assertEqual(result.melted.enthalpy_j[0], 400.0)
        self.assertEqual(result.remaining.temperature_k, (300.0,))
        self.assertEqual(result.melted.temperature_k, (400.0,))

    def test_budget_refusal_and_release(self):
        p = parameters()
        tiny = WorkBudget(1)
        for action in (lambda: invert_enthalpy([[2.0]], [0.0], p, budget=tiny),
                       lambda: reheat([[2.0]], [0.0], [100.0], p, budget=tiny),
                       lambda: melt_source_fraction([[2.0]], [0.0], 1.0, 2200.0, p,
                           liquid_temperature_k=400.0, budget=tiny)):
            with self.assertRaises(MemoryLimitError):
                action()
            self.assertEqual(tiny.reserved_bytes, 0)
        adequate = WorkBudget(thermodynamics_work_bytes(1, 1))
        invert_enthalpy([[2.0]], [0.0], p, budget=adequate)
        self.assertEqual(adequate.reserved_bytes, 0)
        self.assertEqual(adequate.peak_reserved_bytes, adequate.max_bytes)

    def test_cancellation_and_mid_operation_cleanup(self):
        p = parameters()
        event = threading.Event(); event.set()
        with self.assertRaises(CancelledError):
            invert_enthalpy([[2.0]], [0.0], p, cancel=event)
        class CancelAfterThreeChecks:
            calls = 0
            def is_set(self):
                self.calls += 1
                return self.calls >= 3
        budget = WorkBudget(1 << 20)
        with self.assertRaises(CancelledError):
            invert_enthalpy([[2.0], [2.0], [2.0]], [0.0, 0.0, 0.0], p,
                            cancel=CancelAfterThreeChecks(), budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == "__main__":
    unittest.main()
