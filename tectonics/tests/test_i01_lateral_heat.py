"""Focused checks of the conditional thermal-model omission criterion.

SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest

PATH = Path(__file__).resolve().parents[1]/"tools/check_i01_lateral_heat.py"
SPEC = importlib.util.spec_from_file_location("i01_lateral_heat_control", PATH)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def contact(i=0, j=1, **changes):
    out = dict(left=i, right=j, conductivity_w_m_k=3, area_m2=1, distance_m=1000)
    out.update(changes)
    return out


def window(duration=1000000, bounds=None, kind="declared_whole_window"):
    return dict(duration_s=duration, envelope=dict(kind=kind,
                difference_bounds_k=[100] if bounds is None else bounds,
                basis="authored whole-window analytical bound"))


class LateralHeatTests(unittest.TestCase):
    def setUp(self):
        self.net = m.Network([2000000, 5000000], [contact()], assumptions=dict(m.ASSUMPTIONS))

    def test_case_controls(self):
        spec = json.loads((PATH.parents[1]/"cases/i01_lateral_heat_v1.json").read_text())
        out = m.controls(spec)
        self.assertTrue(out["passed"], out)
        self.assertEqual(out["permissive"]["error_bound_exact_k"], "3/20")

    def test_exact_threshold_and_outward_display(self):
        out = m.admission(self.net, [window()], temperature_allowance_k=Q(3, 20))
        self.assertTrue(out["conditional_temperature_admissible"])
        self.assertGreaterEqual(Q(out["error_bound_k"]), Q(3, 20))
        self.assertFalse(m.admission(self.net, [window()], temperature_allowance_k=Q(3, 20)-Q(1, 10**20))["conditional_temperature_admissible"])

    def test_unequal_capacity_analytical_temperature_and_heat(self):
        ci, cj, g, delta, t = 2., 5., 3., 100., .25
        net = m.Network([ci, cj], [contact(conductivity_w_m_k=g, distance_m=1)], assumptions=m.ASSUMPTIONS)
        f = -math.expm1(-g*(1/ci+1/cj)*t)
        changes = [-delta*cj/(ci+cj)*f, delta*ci/(ci+cj)*f]
        self.assertAlmostEqual(ci*changes[0]+cj*changes[1], 0.)
        bound = net.residual_bound([delta])*Q(t)
        self.assertLessEqual(max(map(abs, changes)), float(bound))

    def test_uniform_and_empty_contacts(self):
        self.assertEqual(self.net.residual_bound([0]), 0)
        net = m.Network([1, 3, 9], [], assumptions=m.ASSUMPTIONS)
        out = m.admission(net, [window(bounds=[])], temperature_allowance_k=0)
        self.assertTrue(out["conditional_temperature_admissible"])

    def test_time_gradient_conductivity_and_length_scaling(self):
        baseline = self.net.residual_bound([100])
        self.assertEqual(self.net.residual_bound([200]), 2*baseline)
        for field, value, factor in [("conductivity_w_m_k", 6, 2), ("distance_m", 2000, Q(1, 2))]:
            net = m.Network([2000000, 5000000], [contact(**{field: value})], assumptions=m.ASSUMPTIONS)
            self.assertEqual(net.residual_bound([100]), factor*baseline)
        doubled = m.admission(self.net, [window(duration=2000000)], temperature_allowance_k=1)
        self.assertEqual(Q(doubled["error_bound_exact_k"]), 2*Q(3, 20))

    def test_cumulative_budget_and_restart_carry(self):
        whole = m.admission(self.net, [window(), window()], temperature_allowance_k=Q(1, 5))
        restart = m.admission(self.net, [window()], temperature_allowance_k=Q(1, 5), initial_error_bound_k=Q(3, 20))
        self.assertEqual(whole["error_bound_exact_k"], restart["error_bound_exact_k"])
        self.assertFalse(whole["conditional_temperature_admissible"])

    def test_pulse_endpoints_are_not_a_window_envelope(self):
        # Reduced contrast 100 sin^2(pi t/T) vanishes at both endpoints.
        for kind in ("samples_only", "unknown"):
            out = m.admission(self.net, [window(bounds=[0], kind=kind)], temperature_allowance_k=1000)
            self.assertEqual(out["status"], "REFUSED_UNCERTIFIED_ENVELOPE")
        bad = window()
        bad["envelope"] = None
        self.assertFalse(m.admission(self.net, [bad], temperature_allowance_k=1000)["conditional_temperature_admissible"])

    def test_invalid_contacts(self):
        for key in ("conductivity_w_m_k", "distance_m", "area_m2"):
            for value in (-1, 0, math.nan, math.inf, True):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    m.Network([1, 2], [contact(**{key: value})], assumptions=m.ASSUMPTIONS)
        for edges in ([contact(), contact()], [contact(), contact(i=1, j=0)], [contact(i=1, j=1)], [contact(j=2)], [contact(i=True)]):
            with self.subTest(edges=edges), self.assertRaises(ValueError):
                m.Network([1, 2], edges, assumptions=m.ASSUMPTIONS)

    def test_invalid_capacity_and_window(self):
        for values in ([], [0], [-1], [math.nan], [True]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                m.Network(values, [], assumptions=m.ASSUMPTIONS)
        for bad in (window(duration=0), window(bounds=[]), window(bounds=[-1]), window(bounds=[math.nan])):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m.admission(self.net, [bad], temperature_allowance_k=1)
        with self.assertRaises(ValueError):
            m.admission(self.net, [], temperature_allowance_k=1)

    def test_unsupported_coupling_and_geometry(self):
        for key in m.ASSUMPTIONS:
            assumptions = dict(m.ASSUMPTIONS, **{key: "unknown_or_coupled"})
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.Network([1], [], assumptions=assumptions)

    def test_input_immutability_and_precision_guard(self):
        capacities, contacts, assumptions = [2, 5], [contact()], dict(m.ASSUMPTIONS)
        net = m.Network(capacities, contacts, assumptions=assumptions)
        original = net.residual_bound([100])
        capacities[0], contacts[0]["area_m2"], assumptions["feedback"] = 1, 99, "changed"
        self.assertEqual(net.residual_bound([100]), original)
        with self.assertRaises((AttributeError, TypeError)):
            net.capacities = (1,)
        with self.assertRaises(ValueError):
            m.rational(Q(1, 2**4096), "too precise")

    def test_three_cell_independent_matrix_oracle(self):
        # A tiny oracle only. Runtime admission neither imports SciPy nor allocates a matrix.
        import numpy as np
        from scipy.linalg import expm
        capacities = np.array([2., 5., 7.])
        edges = [contact(0, 1, conductivity_w_m_k=3, distance_m=1),
                 contact(1, 2, conductivity_w_m_k=4, distance_m=1)]
        net = m.Network(capacities.tolist(), edges, assumptions=m.ASSUMPTIONS)
        initial = np.array([400., 500., 350.])
        operator = np.zeros((3, 3))
        for i, j, conductance in net.contacts:
            g = float(conductance)
            operator[i, j] += g/capacities[i]
            operator[i, i] -= g/capacities[i]
            operator[j, i] += g/capacities[j]
            operator[j, j] -= g/capacities[j]
        t = .1
        actual = expm(t*operator)@initial
        out = m.admission(net, [window(duration=t, bounds=[100, 150])], temperature_allowance_k=100)
        self.assertLessEqual(float(np.max(np.abs(actual-initial))), out["error_bound_k"])
        self.assertAlmostEqual(float(capacities@(actual-initial)), 0., places=10)
        self.assertFalse(out["coupled_neck_certified"])
        self.assertFalse(out["continuum_error_certified"])


if __name__ == "__main__":
    unittest.main()
