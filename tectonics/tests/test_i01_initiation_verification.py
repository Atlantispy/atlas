"""Independent analytical controls for the bounded initiation verification path."""
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_initiation_verification as v


class InitiationVerificationTests(unittest.TestCase):
    def test_couette_traction_and_boundary_work(self):
        p = v.Channel(2., np.full(16, 3.), top_mode="traction")
        r = p.solve(0., top_value=6.)
        assert_allclose(r["velocity_m_s"], 2*p.x, rtol=1e-12, atol=1e-14)
        self.assertAlmostEqual(r["boundary_power_w_m2"], 24., places=10)
        self.assertAlmostEqual(r["dissipation_w_m2"], 24., places=10)
        self.assertEqual(r["body_power_w_m2"], 0.)

    def test_release_and_clamp_are_different_problems(self):
        free = v.Channel(2., np.full(16, 3.), top_mode="traction").solve(6., top_value=0.)
        clamp = v.Channel(2., np.full(16, 3.), top_mode="velocity").solve(6., top_value=0.)
        self.assertAlmostEqual(free["velocity_m_s"][-1], 4.)
        self.assertEqual(clamp["velocity_m_s"][-1], 0.)
        self.assertAlmostEqual(clamp["reactions_pa"][-1], -6.)
        self.assertAlmostEqual(clamp["velocity_m_s"][8], 1.)

    def test_nonzero_clamp_and_signed_force_balance(self):
        p = v.Channel(2., np.full(12, 3.), top_mode="velocity")
        r = p.solve(-6., top_value=1.)
        expected = -p.x*(2-p.x)+p.x/2
        assert_allclose(r["velocity_m_s"], expected, atol=2e-13)
        self.assertAlmostEqual(sum(r["reactions_pa"]), 12.)
        self.assertAlmostEqual(r["balance_w_m2"], 0., places=11)
        self.assertGreaterEqual(r["dissipation_w_m2"], 0.)

    def test_layered_viscosity_traction_exact(self):
        eta = np.array([2., 2., 8., 8.])
        p = v.Channel(4., eta, top_mode="traction")
        eta[:] = 99.
        result = p.solve(0., top_value=4.)
        assert_allclose(result["velocity_m_s"], [0., 2., 4., 4.5, 5.], atol=2e-13)
        assert_allclose(result["stress_pa"], 4., atol=2e-13)

    def test_prepared_operator_not_changed_by_solves(self):
        p = v.Channel(2., [3., 4., 5.], top_mode="traction")
        before = p.ab.copy()
        a = p.solve(6., top_value=0.)
        p.solve(0., top_value=3.)
        b = p.solve(6., top_value=0.)
        assert_array_equal(p.ab, before)
        assert_array_equal(a["velocity_m_s"], b["velocity_m_s"])

    def test_invalid_inputs(self):
        for eta in ([True, False], [1., 0.], [1., np.nan], [1.], [[1., 2.]]):
            with self.subTest(eta=eta), self.assertRaises(ValueError):
                v.Channel(1., eta, top_mode="traction")
        with self.assertRaises(ValueError):
            v.Channel(0., [1., 1.], top_mode="traction")
        with self.assertRaises(ValueError):
            v.Channel(1., [1., 1.], top_mode="unspecified")
        p = v.Channel(1., [1., 1.], top_mode="traction")
        for value in (True, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                p.solve(value, top_value=0.)

    def test_complete_control_set_and_scope(self):
        result = v.controls()
        self.assertTrue(result["passed"], result)
        self.assertGreater(len(result["checks"]), 12)
        self.assertIn("no slab", result["scope"])

    def test_cli_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"evidence.json"
            path.write_text("original", encoding="utf-8")
            with patch.object(sys, "argv", ["verify", "--output", str(path)]), self.assertRaises(FileExistsError):
                v.main()
            self.assertEqual(path.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
