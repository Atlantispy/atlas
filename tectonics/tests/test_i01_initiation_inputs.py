"""Synthetic comparator/admission checks, not a subduction experiment."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_i01_initiation_inputs as target


def fixture():
    spec = target.read_json(target.DEFAULT)
    protocol = spec["benchmark_protocol"]
    for name, row in protocol["inputs"].items():
        row.update(basis="SOURCE_EXPLICIT" if name in target.PUBLISHED else "ATLAS_CHOICE",
                   definition="Synthetic test definition, not physical calibration.",
                   source="synthetic://unit-test", locator=name, reviewed=True)
    protocol["reference_curve"] = dict(convergence_m=[0, 1, 2], force_N_per_m=[0, 2, 0],
        sign_convention=target.SIGN, uncertainty_N_per_m=[0, 0, 0],
        source="synthetic://triangle", locator="closed-form unit triangle",
        uncertainty_basis="Exact manufactured values; no digitisation.")
    protocol["comparison_policy"] = dict(interval_m=[0, 2], max_gap_m=1,
        force_allowance_N_per_m=0, work_allowance_J_per_m=0,
        basis="Exact manufactured identity, not a scientific acceptance tolerance.", reviewed=True)
    return spec


def candidate(plan, xs=None, ys=None):
    ref = plan["payload"]["specification"]["benchmark_protocol"]["reference_curve"]
    return dict(plan_sha256=plan["plan_sha256"], run_identity="synthetic-unit-test-only",
        curve=dict(convergence_m=deepcopy(ref["convergence_m"] if xs is None else xs),
                   force_N_per_m=deepcopy(ref["force_N_per_m"] if ys is None else ys),
                   sign_convention=target.SIGN))


class InitiationInputTests(unittest.TestCase):
    def test_actual_record_stays_incomplete_and_cannot_enable_physics(self):
        spec = target.read_json(target.DEFAULT)
        before = deepcopy(spec)
        result = target.inspect_inputs(spec)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(len(result["missing"]), 15)
        self.assertFalse(result["runnable_configuration"])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            target.prepare(spec)
        self.assertEqual(spec, before)

    def test_source_vs_choice_and_inferred_values(self):
        for basis, reviewed in [("INFERRED", True), ("SOURCE_EXPLICIT", False)]:
            spec = fixture()
            spec["benchmark_protocol"]["inputs"]["creep_laws"].update(basis=basis, reviewed=reviewed)
            self.assertIn("creep_laws", target.inspect_inputs(spec)["missing"])
        spec = fixture()
        p = spec["benchmark_protocol"]
        p["track"] = "PUBLISHED_REPRODUCTION"
        p["inputs"]["creep_laws"]["basis"] = "ATLAS_CHOICE"
        self.assertIn("creep_laws", target.inspect_inputs(spec)["missing"])
        p["inputs"]["creep_laws"]["basis"] = "SOURCE_DERIVED"
        for key in target.ATLAS:
            p["inputs"][key] = dict(basis="MISSING", definition=None, source=None, locator=None, reviewed=False)
        self.assertEqual(target.inspect_inputs(spec)["status"], "COMPLETE_FOR_REVIEW")
        target.prepare(spec)  # published comparison does not require an invented release test

    def test_recovered_source_facts_do_not_admit_incomplete_benchmark(self):
        spec = target.read_json(target.DEFAULT)
        published = spec["published_comparisons"]
        case = published["case23_table3"]
        self.assertEqual(dict(zip(case["age_order"], case["ages_Myr"])),
                         {"left_overriding": 10, "right_subducting": 40})
        parameters = published["source_parameters"]
        g, k = parameters["shear_modulus_Pa"], parameters["bulk_modulus_Pa"]
        self.assertEqual(parameters["derived"]["young_modulus_Pa"], 9*k*g/(3*k+g))
        self.assertEqual(parameters["derived"]["poisson_ratio"], (3*k-2*g)/(2*(3*k+g)))
        conflict = published["source_definition_gaps"]["basal_temperature"]
        self.assertEqual(conflict["status"], "CONFLICT")
        self.assertIsNone(conflict["adopted_basal_temperature_C"])
        readings = published["reported_graphical_readings"]
        self.assertEqual(readings["status"], "NOT_ADMITTED_INCOMPLETE_EXTRACTION_PROVENANCE")
        self.assertTrue(readings["extraction_provenance_missing"])
        count = 0
        for panel_name in ("figure8b_p17", "figure13a_p22"):
            panel = readings[panel_name]
            xs = panel["convergence_km"]
            self.assertTrue(all(a < b for a, b in zip(xs, xs[1:])))
            self.assertGreater(panel["reported_horizontal_halfwidth_km"], 0)
            for name, bands in panel.items():
                if name.endswith("_force_intervals"):
                    self.assertEqual(len(xs), len(bands))
                    self.assertTrue(all(lo <= hi for lo, hi in bands))
                    count += len(bands)
        self.assertEqual(count, 28)
        self.assertFalse(readings["reference_curve_populated"])
        self.assertIsNone(spec["benchmark_protocol"]["reference_curve"])
        self.assertIsNone(spec["benchmark_protocol"]["comparison_policy"])
        # Documentary observations cannot silently fill the runner's input groups.
        self.assertEqual(len(target.inspect_inputs(spec)["missing"]), 15)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            target.prepare(spec)

    def test_unknown_malformed_and_unsupported_records(self):
        variants = []
        spec = fixture(); spec["scientific_acceptance"] = True; variants.append(spec)
        spec = fixture(); spec["benchmark_protocol"]["inputs"].pop("elastic_constants"); variants.append(spec)
        spec = fixture(); spec["benchmark_protocol"]["inputs"]["creep_laws"]["source"] = ""; variants.append(spec)
        spec = fixture(); spec["benchmark_protocol"]["track"] = "unknown"; variants.append(spec)
        spec = fixture(); spec["benchmark_protocol"]["comparison_policy"]["reviewed"] = False; variants.append(spec)
        for spec in variants:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                target.prepare(spec)

    def test_independent_analytic_work_and_nonmatching_sampling(self):
        plan = target.prepare(fixture())
        out = target.compare(plan, candidate(plan, [0, .5, 1, 1.5, 2], [0, 1, 2, 1, 0]))
        self.assertEqual(out["status"], "PASS_DECLARED_CURVE_ONLY")
        self.assertEqual(out["reference_signed_work_J_per_m"], 2)
        self.assertEqual(out["candidate_signed_work_J_per_m"], 2)
        self.assertEqual(out["evaluated_knots"], 5)
        self.assertFalse(out["scientific_acceptance"])
        self.assertEqual(out["release_classification"], "NOT_ASSESSED")

    def test_candidate_peak_between_reference_knots_is_not_hidden(self):
        spec = fixture(); spec["benchmark_protocol"]["comparison_policy"]["work_allowance_J_per_m"] = 100
        plan = target.prepare(spec)
        out = target.compare(plan, candidate(plan, [0, .5, 1, 2], [0, 10, 2, 0]))
        self.assertEqual(out["status"], "FAIL")
        self.assertEqual(out["max_abs_force_error_N_per_m"], 9)

    def test_signed_work_cancellation_cannot_hide_force_error(self):
        plan = target.prepare(fixture())
        out = target.compare(plan, candidate(plan, [0, .5, 1, 1.5, 2], [0, 2, 2, 0, 0]))
        self.assertEqual(out["signed_work_error_J_per_m"], 0)
        self.assertEqual(out["status"], "FAIL")

    def test_force_and_work_allowances_are_independent(self):
        spec = fixture(); spec["benchmark_protocol"]["comparison_policy"]["force_allowance_N_per_m"] = 1
        plan = target.prepare(spec)
        out = target.compare(plan, candidate(plan, ys=[1, 3, 1]))
        self.assertEqual(out["status"], "FAIL")
        self.assertEqual(out["signed_work_error_J_per_m"], 2)
        spec["benchmark_protocol"]["comparison_policy"]["work_allowance_J_per_m"] = 2
        plan = target.prepare(spec)
        self.assertEqual(target.compare(plan, candidate(plan, ys=[1, 3, 1]))["status"], "PASS_DECLARED_CURVE_ONLY")

    def test_explicit_uncertainty_envelope_and_interior_interval(self):
        spec = fixture(); p = spec["benchmark_protocol"]
        p["reference_curve"]["uncertainty_N_per_m"] = [.5, .5, .5]
        p["comparison_policy"]["interval_m"] = [.5, 1.5]
        plan = target.prepare(spec)
        out = target.compare(plan, candidate(plan, ys=[.5, 2.5, .5]))
        self.assertEqual(out["status"], "PASS_DECLARED_CURVE_ONLY")
        self.assertEqual(out["work_uncertainty_J_per_m"], .5)
        self.assertEqual(out["reference_signed_work_J_per_m"], 1.5)

    def test_no_extrapolation_or_sparse_curve_and_units_fail_closed(self):
        plan = target.prepare(fixture())
        for xs, ys in [([.1, 1, 2], [0, 2, 0]), ([0, 1, 1.9], [0, 2, 0]),
                       ([0, 2], [0, 0]), ([0, 1, 1], [0, 2, 0]),
                       ([0, 2, 1], [0, 2, 0]), ([0, True, 2], [0, 2, 0]),
                       ([0, 1, 2], [0, float("nan"), 0]), ([0, 1, 2], [0, 10**400, 0])]:
            with self.subTest(xs=xs, ys=ys), self.assertRaises(ValueError):
                target.compare(plan, candidate(plan, xs, ys))
        c = candidate(plan); c["curve"]["force_N"] = c["curve"].pop("force_N_per_m")
        with self.assertRaises(ValueError): target.compare(plan, c)
        c = candidate(plan); c["curve"]["sign_convention"] = "compression_negative"
        with self.assertRaises(ValueError): target.compare(plan, c)

    def test_plan_detached_and_changed_plan_run_or_source_refused(self):
        spec = fixture(); plan = target.prepare(spec); c = candidate(plan)
        spec["benchmark_protocol"]["comparison_policy"]["force_allowance_N_per_m"] = 999
        self.assertEqual(target.compare(plan, c)["status"], "PASS_DECLARED_CURVE_ONLY")
        edited = deepcopy(plan)
        edited["payload"]["specification"]["benchmark_protocol"]["comparison_policy"]["force_allowance_N_per_m"] = 999
        with self.assertRaisesRegex(ValueError, "plan changed"): target.compare(edited, c)
        edited = target.prepare(spec)
        with self.assertRaisesRegex(ValueError, "different plan"): target.compare(edited, c)
        with patch.object(target, "bindings", return_value={}):
            with self.assertRaisesRegex(ValueError, "implementation/method changed"): target.compare(plan, c)

    def test_json_duplicate_nonfinite_size_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"record.json"
            for content in ['{"a":1,"a":2}', '{"a":NaN}', ' '* (target.MAX_BYTES+1)]:
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError): target.read_json(path)
            path.unlink()
            target.write_new(path, {"ok": True})
            with self.assertRaises(FileExistsError): target.write_new(path, {})
            self.assertEqual(target.read_json(path), {"ok": True})

    def test_cli_inspect_prepare_compare_and_no_partial_refusal_file(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            root = Path(directory); plan_path = root/"plan.json"
            self.assertEqual(target.main(["inspect"]), 2)
            self.assertEqual(target.main(["prepare", "--output", str(plan_path)]), 1)
            self.assertFalse(plan_path.exists())
            spec_path = root/"spec.json"; target.write_new(spec_path, fixture())
            self.assertEqual(target.main(["prepare", "--spec", str(spec_path), "--output", str(plan_path)]), 0)
            run_path = root/"run.json"; target.write_new(run_path, candidate(target.read_json(plan_path)))
            result_path = root/"result.json"
            command = ["compare", "--plan", str(plan_path), "--candidate", str(run_path), "--output", str(result_path)]
            self.assertEqual(target.main(command), 0)
            self.assertEqual(target.main(command), 1)
            self.assertEqual(target.read_json(result_path)["status"], "PASS_DECLARED_CURVE_ONLY")


if __name__ == "__main__":
    unittest.main()
