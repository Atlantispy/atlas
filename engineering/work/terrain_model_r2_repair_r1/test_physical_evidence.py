"""Numerical/closure tests; generated test curves are never observations."""
from copy import deepcopy
import hashlib
import math
import unittest
from unittest.mock import patch

import physical_evidence as evidence


def numerical_rows(slope=-2., intercept=math.log(.001)):
    return [{"sample": "NUMERICAL_TEST_" + str(i), "depth_m": i * .1,
        "rate_m_per_year": math.exp(intercept + slope * i * .1),
        "reported_error_m_per_year": .1 * math.exp(intercept + slope * i * .1)}
        for i in range(4)]


class PhysicalEvidenceTests(unittest.TestCase):
    def test_frozen_transcription_split_and_units(self):
        identity = evidence.freeze_identity()
        self.assertEqual(identity["data_sha256"], "30c13c9e8ef68cf3a0eeb437189e34e612b6de24abab66bc97e3a2a1022d7eb3")
        self.assertEqual(identity["protocol_sha256"], "06fc95600bb52ba2ac7dc6229ca1eaccef6addb38d9c1711c76b144c8028de9d")
        data = evidence.observations()
        self.assertEqual(len(data["calibration"]), 10)
        self.assertEqual(len(data["holdout"]), 8)
        self.assertTrue(set(r["sample"] for r in data["calibration"]).isdisjoint(r["sample"] for r in data["holdout"]))
        first = data["calibration"][0]
        self.assertEqual(first["sample"], "SG-103")
        self.assertEqual(first["depth_m"], .23)
        self.assertAlmostEqual(first["rate_m_per_year"], 78e-6, places=18)
        self.assertAlmostEqual(first["reported_error_m_per_year"], 17e-6, places=18)
        data["calibration"][0]["depth_m"] = 999
        self.assertEqual(evidence.observations()["calibration"][0]["depth_m"], .23)

    def test_frozen_protocol_or_data_mutation_fails(self):
        with patch.dict(evidence.PROTOCOL, {"cm_to_m": .1}):
            with self.assertRaises(evidence.EvidenceError):
                evidence.run_evidence()
        with patch.object(evidence, "HOLDOUT_RAW", evidence.HOLDOUT_RAW[:-1]):
            with self.assertRaises(evidence.EvidenceError):
                evidence.observations()

    def test_source_bytes_exact_pin_required(self):
        for payload in (b"", b"%PDF-truncated", "not bytes"):
            with self.assertRaises(evidence.EvidenceError):
                evidence.verify_primary_source(payload)
        payload = b"%PDF-" + b"x" * (evidence.SOURCE_BYTES - 5)
        with self.assertRaisesRegex(evidence.EvidenceError, "SHA"):
            evidence.verify_primary_source(payload)
        # Isolated mechanics check; not represented as authentication of the PDF.
        with patch.object(evidence, "SOURCE_SHA256", hashlib.sha256(payload).hexdigest()):
            self.assertEqual(evidence.verify_primary_source(payload)["bytes"], len(payload))

    def test_numerical_exponential_fit_recovers_known_parameters(self):
        rows = numerical_rows()
        before = deepcopy(rows)
        model = evidence.fit_calibration(rows)
        self.assertAlmostEqual(model["bare_rate_m_per_year"], .001, places=16)
        self.assertAlmostEqual(model["decay_per_m"], 2., places=13)
        self.assertAlmostEqual(model["cover_scale_m"], .5, places=13)
        self.assertFalse(model["constant_boundary_fit"])
        self.assertEqual(rows, before)

    def test_weights_match_independent_equal_relative_error_regression(self):
        rows = numerical_rows()
        rows[1]["rate_m_per_year"] *= 1.2
        for row in rows:
            row["reported_error_m_per_year"] = row["rate_m_per_year"] / 10.
        xs = [r["depth_m"] for r in rows]
        ys = [math.log(r["rate_m_per_year"]) for r in rows]
        mx, my = sum(xs) / 4., sum(ys) / 4.
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        model = evidence.fit_calibration(rows)
        self.assertAlmostEqual(model["decay_per_m"], -slope, places=13)
        self.assertAlmostEqual(model["bare_rate_m_per_year"], math.exp(my - slope * mx), places=16)

    def test_nondecaying_data_use_declared_constant_boundary(self):
        rows = numerical_rows(slope=2.)
        model = evidence.fit_calibration(rows)
        self.assertEqual(model["decay_per_m"], 0.)
        self.assertIsNone(model["cover_scale_m"])
        self.assertTrue(model["constant_boundary_fit"])
        geometric = math.exp(sum(math.log(r["rate_m_per_year"]) for r in rows) / len(rows))
        self.assertAlmostEqual(evidence.predict(model, 100.), geometric, places=16)

    def test_fit_has_no_holdout_or_observation_loader_access(self):
        rows = numerical_rows()
        baseline = evidence.fit_calibration(rows)
        with patch.object(evidence, "observations", side_effect=AssertionError("holdout access")), \
             patch.object(evidence, "HOLDOUT_RAW", (("poison",),)):
            self.assertEqual(evidence.fit_calibration(rows), baseline)

    def test_bad_numeric_inputs_and_duplicate_ids_reject(self):
        for value in (True, -1., math.nan, math.inf, 10 ** 1000, "1"):
            for field in ("depth_m", "rate_m_per_year", "reported_error_m_per_year"):
                rows = numerical_rows()
                rows[1][field] = value
                with self.subTest(value=str(value)[:12], field=field), self.assertRaises(evidence.EvidenceError):
                    evidence.fit_calibration(rows)
        for field in ("rate_m_per_year", "reported_error_m_per_year"):
            rows = numerical_rows()
            rows[0][field] = 0.
            with self.assertRaises(evidence.EvidenceError):
                evidence.fit_calibration(rows)
        rows = numerical_rows()
        rows[1]["sample"] = rows[0]["sample"]
        with self.assertRaises(evidence.EvidenceError):
            evidence.fit_calibration(rows)

    def test_count_and_unresolved_depth_reject(self):
        for rows in ([], numerical_rows()[:2], numerical_rows() * 65):
            with self.assertRaises(evidence.EvidenceError):
                evidence.fit_calibration(rows)
        rows = numerical_rows()
        for row in rows:
            row["depth_m"] = 1.
        with self.assertRaises(evidence.EvidenceError):
            evidence.fit_calibration(rows)

    def test_extreme_finite_fit_inputs_fail_controlled(self):
        rows = numerical_rows()
        for i, row in enumerate(rows):
            row["depth_m"] = 1e308 / (i + 1)
        with self.assertRaises(evidence.EvidenceError):
            evidence.fit_calibration(rows)
        rows = numerical_rows()
        rows[0]["reported_error_m_per_year"] = 1e-320
        with self.assertRaises(evidence.EvidenceError):
            evidence.fit_calibration(rows)

    def test_zero_depth_and_prediction_underflow(self):
        model = evidence.fit_calibration(numerical_rows())
        self.assertEqual(evidence.predict(model, 0), model["bare_rate_m_per_year"])
        with self.assertRaises(evidence.EvidenceError):
            evidence.predict(model, 1e308)

    def test_positive_decay_with_unrepresentable_cover_scale_rejects(self):
        rows = [{"sample": str(i), "depth_m": float(i), "rate_m_per_year": rate,
                 "reported_error_m_per_year": error}
                for i, (rate, error) in enumerate(((1., 1.), (1., 1.), (math.exp(-1), 1e155)))]
        with self.assertRaisesRegex(evidence.EvidenceError, "cover scale"):
            evidence.fit_calibration(rows)

    def test_metrics_and_extrapolation_are_reported_without_filtering(self):
        model = evidence.fit_calibration(numerical_rows())
        rows = numerical_rows()
        rows[0]["depth_m"] = 1.
        result = evidence.evaluate(model, rows)
        self.assertEqual(len(result["observations"]), 4)
        self.assertEqual(result["metrics"]["outside_depth_support_count"], 1)
        residuals = [r["residual_m_per_year"] for r in result["observations"]]
        self.assertAlmostEqual(result["metrics"]["rmse_m_per_year"], math.sqrt(sum(r * r for r in residuals) / 4.), places=16)
        self.assertAlmostEqual(result["metrics"]["bias_m_per_year"], sum(residuals) / 4., places=16)

    def test_complete_evidence_scopes_and_material_bridge(self):
        result = evidence.run_evidence()
        self.assertEqual(result, evidence.run_evidence())
        self.assertEqual(result["calibration"]["metrics"]["count"], 10)
        self.assertEqual(result["holdout"]["metrics"]["count"], 8)
        for flag in ("physical_validation_passed", "full_landform_family_implemented",
                     "diadem_coefficients_changed", "production_authorised",
                     "independent_external_study_holdout", "observations_are_synthetic"):
            self.assertIs(result[flag], False)
        bridge = result["material_operator_initial_rate_bridge"]
        self.assertLessEqual(bridge["maximum_absolute_rate_difference_m_per_year"], 1e-18)
        self.assertFalse(bridge["observed_density_or_mass_yield_validation"])
        self.assertEqual(bridge["duration_years"], 0.)


if __name__ == "__main__":
    unittest.main()
