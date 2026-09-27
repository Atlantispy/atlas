"""Independent phase/depletion checks. SPDX-License-Identifier: AGPL-3.0-only"""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError, replace
import importlib.util
import math
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1]/"tools/check_i01_phase_partition.py"
SPEC = importlib.util.spec_from_file_location("i01_partition", PATH)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


class PartitionTests(unittest.TestCase):
    def setUp(self):
        self.p = m.Partition(("a", "b"), (.5, 2.), 1e9, 1600., "analytical-control")

    def test_binary_independent_root_and_compositions(self):
        for a in (.35, .4, .41, .5, .6, .65):
            # Independently reduced binary root: f=3a-1 for K=(1/2,2).
            state = m.equilibrate(self.p, [a, 1-a])
            self.assertAlmostEqual(state.liquid_fraction, 3*a-1, places=11)
            f = state.liquid_fraction
            self.assertAlmostEqual(state.liquid_mass_kg[0]/f, 2/3, places=11)
            self.assertAlmostEqual(state.solid_mass_kg[0]/(1-f), 1/3, places=11)

    def test_depletion_does_not_recreate_extracted_liquid(self):
        before = m.equilibrate(self.p, [4000., 6000.])
        residue, taken = m.extract(before, .5)
        self.assertAlmostEqual(math.fsum(taken), 1000., places=7)
        self.assertAlmostEqual(math.fsum(residue.liquid_mass_kg), 1000., places=7)
        bulk = tuple(s+l for s, l in zip(residue.solid_mass_kg, residue.liquid_mass_kg))
        after = m.equilibrate(self.p, bulk)
        self.assertAlmostEqual(after.liquid_fraction, 1/9, places=11)
        for actual, expected in zip(after.liquid_mass_kg, residue.liquid_mass_kg):
            self.assertAlmostEqual(actual, expected, places=7)
        self.assertAlmostEqual(9000*.2-math.fsum(after.liquid_mass_kg), 800., places=7)

    def test_dry_liquid_empty_and_ambiguous(self):
        self.assertEqual(m.equilibrate(self.p, [1., 9.]).liquid_fraction, 0.)
        self.assertEqual(m.equilibrate(self.p, [9., 1.]).liquid_fraction, 1.)
        self.assertIsNone(m.equilibrate(self.p, [0., 0.]).liquid_fraction)
        for coefficients, masses in (((1., 1.), [1., 1.]), ((1., .5), [1., 0.])):
            with self.assertRaisesRegex(ValueError, "indeterminate"):
                m.equilibrate(replace(self.p, coefficients=coefficients), masses)

    def test_component_permutation_scale_and_no_mutation(self):
        mass = [4000., 6000.]
        a = m.equilibrate(self.p, mass)
        b = m.equilibrate(replace(self.p, component_ids=("b", "a"), coefficients=(2., .5)), mass[::-1])
        self.assertEqual(a.liquid_mass_kg, b.liquid_mass_kg[::-1])
        scaled = m.equilibrate(self.p, [x*1e8 for x in mass])
        self.assertAlmostEqual(a.liquid_fraction, scaled.liquid_fraction, places=14)
        self.assertEqual(mass, [4000., 6000.])
        with self.assertRaises(FrozenInstanceError):
            self.p.temperature_k = 1700.

    def test_repeated_fractional_extraction_and_endpoints(self):
        state = m.equilibrate(self.p, [4000., 6000.])
        half, a = m.extract(state, .5)
        quarter, b = m.extract(half, .5)
        once, c = m.extract(state, .75)
        for actual, expected in zip(quarter.liquid_mass_kg, once.liquid_mass_kg):
            self.assertLessEqual(abs(actual-expected), m.POLICY["fraction_tolerance"]*max(actual, expected))
        for x, y, z in zip(a, b, c):
            self.assertAlmostEqual(x+y, z, places=10)
        full, taken = m.extract(state, 1.)
        self.assertEqual(full.liquid_mass_kg, (0., 0.))
        self.assertEqual(full.solid_mass_kg, state.solid_mass_kg)
        unchanged, nothing = m.extract(state, 0.)
        self.assertEqual(unchanged.liquid_mass_kg, state.liquid_mass_kg)
        self.assertEqual(nothing, (0., 0.))

    def test_partition_relations_for_multicomponent_state(self):
        p = m.Partition(("a", "b", "c"), (.1, .8, 6.), 2e9, 1800., "synthetic")
        bulk = [200., 500., 300.]
        state = m.equilibrate(p, bulk)
        self.assertTrue(0 < state.liquid_fraction < 1)
        sm, lm = math.fsum(state.solid_mass_kg), math.fsum(state.liquid_mass_kg)
        for total, s, l, k in zip(bulk, state.solid_mass_kg, state.liquid_mass_kg, p.coefficients):
            self.assertAlmostEqual(s+l, total, places=11)
            self.assertAlmostEqual((s/sm)/(l/lm), k, places=10)

    def test_invalid_inputs_and_numerical_debits(self):
        for k in ((True, 2.), (0., 2.), (float("nan"), 2.), (1e13, 2.)):
            with self.assertRaises(ValueError):
                replace(self.p, coefficients=k)
        for mass in ([1.], [-1., 1.], [float("nan"), 1.], [True, 1.], ["1", 2.]):
            with self.assertRaises(ValueError):
                m.equilibrate(self.p, mass)
        for alpha in (True, -.1, 1.1, float("nan"), 1e-30):
            with self.assertRaises(ValueError):
                m.extract(m.equilibrate(self.p, [4000., 6000.]), alpha)

    def test_nearly_indistinguishable_mixed_phases_refused(self):
        with self.assertRaisesRegex(ValueError, "ill-conditioned"):
            m.equilibrate(replace(self.p, coefficients=(1-1e-7, 1+1e-7)), [1., 1.])

    def test_cancellation_deadline_and_budget(self):
        event = threading.Event(); event.set()
        with self.assertRaises(CancelledError):
            m.equilibrate(self.p, [4000., 6000.], cancel=event)
        with self.assertRaises(TimeoutError):
            m.equilibrate(self.p, [4000., 6000.], deadline=time.perf_counter()-1)
        with self.assertRaises(ValueError):
            m.equilibrate(self.p, [4000., 6000.], deadline=float("nan"))
        with patch.dict(m.POLICY, {"max_iterations": 1}):
            with self.assertRaisesRegex(ValueError, "budget"):
                m.equilibrate(self.p, [4100., 5900.])
        with self.assertRaises(CancelledError):
            m.extract(m.equilibrate(self.p, [4000., 6000.]), .5, cancel=event)


if __name__ == "__main__":
    unittest.main()
