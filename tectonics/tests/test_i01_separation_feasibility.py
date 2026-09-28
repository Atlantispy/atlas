"""Analytical or independent checks for the resolved separation feasibility seam."""
from dataclasses import replace
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.linalg import solve_banded

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_i01_separation_feasibility as m
from check_i01_separation_law import Prepared, State


class FeasibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = m.load_case()
        cls.law = m.SofteningLaw(**cls.spec["law"])
        cls.loading = m.Loading(**cls.spec["loading"])

    def band(self, n=32, contrast=0.1, **kwargs):
        return m.Band(self.law, self.loading, cells=n, ell_m=1, contrast=contrast,
                      length_provenance="explicit synthetic physical length", **kwargs)

    def test_filter_constant_mean_and_neumann_cosine(self):
        errors = []
        for n in (32, 64):
            band = self.band(n)
            np.testing.assert_allclose(band.filtered(np.ones(n)), 1, rtol=1e-13)
            raw = 1 + 0.25*np.cos(2*np.pi*band.x/8)
            expected = 1 + 0.25*np.cos(2*np.pi*band.x/8)/(1+(2*np.pi/8)**2)
            filtered = band.filtered(raw)
            self.assertAlmostEqual(float(np.mean(filtered)), float(np.mean(raw)), places=13)
            errors.append(float(np.max(abs(filtered-expected))))
        self.assertLess(errors[1], errors[0]/3.9)
        self.assertLess(errors[0], m.POLICY["filter_relative"])

    def test_uniform_band_matches_independent_exact_local_solution(self):
        # Spatial force-balance/RK4 code is compared with the retained phase-exact kernel.
        exact = Prepared(self.law, self.loading).advance(State(2, 0, history_support="INSIDE"), 20)
        actual = self.band(contrast=0).run(dt_s=0.0025, horizon_s=20, traction_pa=2, support="INSIDE")
        self.assertAlmostEqual(actual["traction_pa"], exact["state"].traction_pa, places=6)
        self.assertAlmostEqual(actual["raw_history_range"][0], exact["state"].history, places=6)
        completion = next(event["time_s"] for event in exact["events"] if event["event"] == "softening_complete")
        self.assertLessEqual(actual["bond_loss_bracket_s"][0], completion)
        self.assertGreaterEqual(actual["bond_loss_bracket_s"][1], completion)
        self.assertLess(m.relative(actual["breakdown_dissipation_j_m2"],
                                   self.law.fracture_energy_j_m2(10)), 1e-6)
        self.assertLess(actual["account_relative_error"], m.POLICY["account_relative"])
        self.assertNotIn("opening_bracket_m", actual)
        np.testing.assert_array_equal(actual["shear_displacement_bracket_m"],
            np.asarray(actual["bond_loss_bracket_s"])*self.loading.loading_rate_m_s)

    def test_filter_factor_reused_and_matches_original_solver(self):
        with patch.object(m, "cholesky_banded", wraps=m.cholesky_banded) as factor:
            band = self.band(64)
            for offset in (0., 0.3, 2.):
                raw = offset+np.linspace(0, 1, 64)**2
                before = raw.copy()
                np.testing.assert_allclose(band.filtered(raw),
                    solve_banded((1, 1), band.ab, raw), rtol=1e-13, atol=1e-14)
                np.testing.assert_array_equal(raw, before)
            self.assertEqual(factor.call_count, 1)
        for array in (band.ab, band._filter_factor):
            with self.assertRaises(ValueError):
                array.setflags(write=True)

    def test_force_balance_and_energy_identity_for_nonuniform_field(self):
        band = self.band()
        state = np.zeros(1+band.n+5)
        state[0] = 11
        state[1:1+band.n] = 0.2+0.1*np.cos(2*np.pi*band.x/8)
        rates = band.rates(state)
        slip_rate = band.h*sum(rates[1:1+band.n])
        self.assertAlmostEqual(rates[0], 2*(1-slip_rate), places=12)
        self.assertAlmostEqual(rates[-5], state[0]*rates[0]/2+sum(rates[-4:]), places=10)
        self.assertGreater(float(np.ptp(rates[1:1+band.n])), 0)

    def test_bond_history_is_irreversible_when_strength_recovers(self):
        original = m.BondHistory("rock-A", False, "INSIDE")
        broken = original.observe(self.law, 1, 300, 10, increment_support="INSIDE")
        recovered = broken.observe(self.law, 0, 300, 10, increment_support="INSIDE")
        self.assertEqual(recovered.bond, "BROKEN")
        self.assertEqual(original.bond, "BONDED")
        self.assertEqual(self.law.bond_state(0, 300, 10, history_support="INSIDE"), "BONDED")

    def test_unsupported_history_never_becomes_certified(self):
        for flag in ("UNKNOWN", "VIOLATED"):
            record = m.BondHistory("rock-A", False, flag)
            after = record.observe(self.law, 2, 300, 10, increment_support="INSIDE")
            self.assertEqual(after.bond, "UNRESOLVED")
            self.assertEqual(after.support, flag)

    def test_current_support_does_not_erase_or_authorise_old_break(self):
        broken = m.BondHistory("rock-A", True, "INSIDE")
        outside = broken.observe(self.law, 0, 500, 10, increment_support="INSIDE")
        self.assertEqual(outside.bond, "BROKEN")
        self.assertEqual(outside.support, "VIOLATED")

    def test_filter_contributors_need_support_too(self):
        record = m.BondHistory("rock-A", False, "INSIDE")
        result = record.observe(self.law, 2, 300, 10, increment_support="UNKNOWN")
        self.assertEqual(result.bond, "UNRESOLVED")

    def test_intact_residual_never_breaks(self):
        law = replace(self.law, residual_state="weakened_intact")
        result = m.BondHistory("rock-A", False, "INSIDE").observe(law, 20, 300, 10,
                                                                     increment_support="INSIDE")
        self.assertEqual(result.bond, "BONDED")

    def test_cohort_mixture_keeps_distinct_bonds(self):
        records = (m.BondHistory("A", False, "INSIDE"), m.BondHistory("B", True, "INSIDE"))
        self.assertEqual(m.preserve_bond_cohorts(records), records)
        with self.assertRaises(m.Refusal):
            m.preserve_bond_cohorts((records[0], records[0]))

    def test_inadequate_resolution_and_invalid_history_refused(self):
        with self.assertRaises(m.Refusal):
            self.band(n=16)
        with self.assertRaises(m.Refusal):
            self.band().filtered(np.zeros(10))
        with self.assertRaises(m.Refusal):
            self.band().run(dt_s=0.005, horizon_s=1, traction_pa=2, support="UNKNOWN")

    def test_budget_and_unsafe_explicit_step_refused(self):
        for dt, horizon in ((1, 20), (1e-9, 1)):
            with self.assertRaises(m.Refusal):
                self.band().run(dt_s=dt, horizon_s=horizon, traction_pa=2, support="INSIDE")

    def test_missing_provenance_and_nonfinite_input_refused(self):
        for changes in ({"ell_m": math.inf}, {"contrast": True}, {"length_provenance": ""}):
            values = dict(cells=32, ell_m=1, contrast=0.1, length_provenance="synthetic")
            values.update(changes)
            with self.assertRaises(m.Refusal):
                m.Band(self.law, self.loading, **values)

    def test_creep_arm_respects_its_extra_stability_rate(self):
        spec = self.spec["creep_control"]
        self.assertEqual(spec["viscosity_pa_s"], 1.0)
        self.assertEqual(spec["dt_factor"], 0.5)
        band = m.Band(self.law, replace(self.loading, creep_viscosity_pa_s=spec["viscosity_pa_s"]),
                      cells=64, ell_m=1, contrast=0.1, length_provenance="synthetic physical length")
        with self.assertRaises(m.Refusal):
            band.run(dt_s=0.005, horizon_s=0.1, traction_pa=2, support="INSIDE")
        result = band.run(dt_s=0.005*spec["dt_factor"], horizon_s=0.1, traction_pa=2, support="INSIDE")
        self.assertEqual(result["bonded_connectivity"], "CONNECTED")
        self.assertEqual(result["raw_history_range"], [0., 0.])
        self.assertLess(result["account_relative_error"], m.POLICY["account_relative"])

    def test_comparison_does_not_relax_bracket_or_energy_limits(self):
        a = {"bond_loss_bracket_s": [1, 2], "shear_displacement_bracket_m": [1, 2],
             "breakdown_dissipation_j_m2": 10}
        self.assertTrue(m.compare(a, a)["pass"])
        self.assertFalse(m.compare(a, dict(a, bond_loss_bracket_s=[2.1, 3]))["pass"])
        self.assertFalse(m.compare(a, dict(a, breakdown_dissipation_j_m2=12))["pass"])

    def test_policy_and_status_remain_bounded(self):
        self.assertEqual(self.spec["policy"], m.POLICY)
        self.assertFalse(self.spec["scientific_acceptance"])
        self.assertFalse(self.spec["event_authorised"])
        self.assertEqual(m.POLICY["refinement_relative"], 0.03)

    def test_existing_output_refuses_before_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"existing.json"
            output.write_text("original evidence\n", encoding="utf-8")
            with patch.object(m, "campaign") as campaign:
                with self.assertRaises(FileExistsError):
                    m.main(["--output", str(output)])
                campaign.assert_not_called()
            self.assertEqual(output.read_text(encoding="utf-8"), "original evidence\n")

    def test_failed_campaign_leaves_visible_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"failed.json"
            with patch.object(m, "campaign", side_effect=m.Refusal("REFUSED_TEST", "actual failure")):
                with self.assertRaises(m.Refusal):
                    m.main(["--output", str(output)])
            failure = m.json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(failure["result"], "FAILED_CAMPAIGN")
            self.assertIn("actual failure", failure["error"])
            self.assertFalse(failure["scientific_acceptance"])
            self.assertEqual(set(failure["source_sha256"]), set(m.FILES))
            self.assertGreaterEqual(failure["elapsed_seconds_after_imports"], 0)
            self.assertIn("python", failure["runtime"])


if __name__ == "__main__":
    unittest.main()
