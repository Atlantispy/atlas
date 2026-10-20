"""Bounded synthetic controls for actual writer prediction and metric adaptation."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load("plan12_metrics_under_test", HERE / "metrics.py")
W = load("plan12_metrics_actual_writer", HERE.parent / "ab_heat_r13.py")


def native_receipt():
    return dict(status="PASS", legacy=dict(seconds=10.125),
                compact=dict(seconds=8.625, result_id="a" * 64),
                arrays={name: "b" * 64 for name in M.ARRAYS},
                ab=dict(leaks=[], parent_cpu_seconds=5.25, parent_peak_working_set=256 * M.MIB,
                        exact_growth_sha256="c" * 64, gmp_resources_sha256="d" * 64,
                        calls=[dict(workers=6, fallback=None, seconds=2.5,
                                    worker_compute_seconds=8.25,
                                    worker_working_set_peak_max=64 * M.MIB),
                               dict(workers=6, fallback=None, seconds=2.25,
                                    worker_compute_seconds=7.75,
                                    worker_working_set_peak_max=80 * M.MIB)]))


class ConsumerMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="metrics-fixture-", dir=HERE)
        self.addCleanup(self.temporary.cleanup)
        self.task = Path(self.temporary.name)
        self.layout = str(self.task / "hs/lh")
        self.arm = dict(arm=5, mode="time", layout=self.layout)
        self.selection = dict(source_pins={
            str(Path(W.__file__).resolve()): M.digest(W.__file__),
            str(Path(M.__file__).resolve()): M.digest(M.__file__)},
            prediction_history=[])
        for name in M.HISTORY_NAMES:
            path = self.task / "hs/evidence" / name / "summary.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(dict(arms=[self.history_arm(mode="proof")])), encoding="utf8")
            sha = M.digest(path)
            self.selection["prediction_history"].append(dict(path=str(path), sha256=sha))
            self.selection["source_pins"][str(path)] = sha
        for item in (patch.object(M, "TASK", self.task),
                     patch.dict(os.environ, dict(RUNQ_PRED_PEAK_GIB="2.03",
                                                RUNQ_TICKET_GIB="2.03",
                                                RUNQ_MEM_NEED_GIB="4.4"), clear=False)):
            item.start()
            self.addCleanup(item.stop)
        self.context = M.load_history(self.selection, W)

    def history_arm(self, **changes):
        value = dict(arm=4, mode="time", layout=self.layout, input=W.INPUT,
                     used=[6, 6], status="PASS", exit_code=0, tree_peak_mib=900,
                     parent_peak_mib=300, worker_peak_mib=120)
        value.update(changes)
        return value

    def predict(self, completed=(), **kwargs):
        return M.predict_arm(self.selection, W, self.arm, self.context, list(completed), **kwargs)

    def test_proof_history_is_not_a_time_measurement_and_gate_is_dynamic(self):
        value = self.predict()
        self.assertEqual(value["predicted_peak_gib"], 2.03)
        self.assertIn("fallback RUNQ_PRED_PEAK_GIB", value["prediction_basis"])
        self.assertAlmostEqual(value["start_gate_gib"], 4.436)
        self.assertEqual(value["prediction_history"], self.selection["prediction_history"])
        self.assertEqual(value["wait_policy"]["maximum_seconds"], 600)
        self.assertEqual(value["wait_policy"]["effective_maximum_seconds"], 120)

    def test_actual_predictor_uses_largest_same_route_parent_plus_six_workers(self):
        value = self.predict([self.history_arm(), self.history_arm(tree_peak_mib=1100)])
        self.assertEqual(value["predicted_peak_gib"], 1100 / 1024)
        self.assertIn("this run", value["prediction_basis"])
        self.assertEqual(self.predict([self.history_arm()])["predicted_peak_gib"], 1020 / 1024)

    def test_nonmatching_or_failed_history_cannot_lower_prediction(self):
        excluded = [self.history_arm(mode="prof"), self.history_arm(mode="proof"),
                    self.history_arm(layout="elsewhere"), self.history_arm(used=[5, 6]),
                    self.history_arm(input="different input"), self.history_arm(status="FAIL"),
                    self.history_arm(exit_code=1), self.history_arm(stopped="failed")]
        self.assertEqual(self.predict(excluded)["predicted_peak_gib"], 2.03)

    def test_prof_is_separate_and_invalid_environment_does_not_fall_through(self):
        self.arm["mode"] = "prof"
        self.assertEqual(self.predict([self.history_arm()])["predicted_peak_gib"], 2.03)
        for invalid in ("nan", "-1", "not-a-number"):
            with self.subTest(invalid=invalid), patch.dict(os.environ, {"RUNQ_PRED_PEAK_GIB": invalid}):
                with self.assertRaisesRegex(ValueError, "no positive finite peak"):
                    self.predict(cli_gib=1.1)

    def test_exact_booking_and_queue_gate_refuse_understatement(self):
        with patch.dict(os.environ, {"RUNQ_TICKET_GIB": "2.0299999999999999"}):
            with self.assertRaisesRegex(ValueError, "booking below"):
                self.predict()
        with patch.dict(os.environ, {"RUNQ_MEM_NEED_GIB": "4.39"}):
            with self.assertRaisesRegex(ValueError, "memory admission below"):
                self.predict()
        with self.assertRaisesRegex(ValueError, "booking below"):
            self.predict([self.history_arm(tree_peak_mib=2200)])

    def test_exact_history_paths_hashes_and_writer_pins_are_required(self):
        other = deepcopy(self.selection)
        other["prediction_history"] = other["prediction_history"][:1]
        with self.assertRaisesRegex(ValueError, "Exactly the two"):
            M.load_history(other, W)
        other = deepcopy(self.selection)
        other["prediction_history"].reverse()
        with self.assertRaisesRegex(ValueError, "exact r2"):
            M.load_history(other, W)
        other = deepcopy(self.selection)
        other["source_pins"][str(Path(W.__file__).resolve())] = "0" * 64
        with self.assertRaisesRegex(ValueError, "writer source"):
            M.load_history(other, W)
        Path(self.selection["prediction_history"][0]["path"]).write_text('{"arms":[]}', encoding="utf8")
        with self.assertRaisesRegex(ValueError, "history changed"):
            M.load_history(self.selection, W)

    def test_start_observation_preserves_real_wait_and_exact_free_boundary(self):
        prediction = self.predict()
        required = prediction["required_start_gate_bytes"]
        self.assertFalse(M.start_observation(prediction, available_bytes=required - 1,
                                            waited_seconds=120)["start_gate_passed"])
        self.assertTrue(M.start_observation(prediction, available_bytes=required,
                                           waited_seconds=15)["start_gate_passed"])
        late = M.start_observation(prediction, available_bytes=required - 1, waited_seconds=120.01)
        self.assertEqual(late["gate_waited_s"], 120.01)
        self.assertTrue(late["gate_wait_limit_reached"])
        self.assertFalse(late["start_gate_passed"])

    def test_metric_copy_preserves_precision_identity_and_measured_peak_scope(self):
        native = native_receipt()
        stage = dict(wall_seconds=25, peak_sampled_tree_rss_bytes=1024 * M.MIB,
                     free_low_bytes=5 * M.GIB)
        value = M.summary_metrics(native, stage, machine_busy_cpu_seconds=30.25)
        self.assertEqual(value["legacy_s"], 10.125)
        self.assertEqual(value["compact_s"], 8.625)
        self.assertEqual(value["worker_cpu_s"], [8.25, 7.75])
        self.assertEqual(value["other_load_cpus"], (30.25 - 21.25) / 25)
        self.assertEqual(value["parent_peak_mib"], 256)
        self.assertEqual(value["worker_peak_mib"], 80)
        self.assertEqual(value["arrays"], native["arrays"])
        self.assertEqual(value["exact_growth_sha256"], "c" * 64)
        self.assertIsNone(value["worker_processes"])
        native["arrays"]["enthalpy_j"] = "e" * 64
        self.assertEqual(value["arrays"]["enthalpy_j"], "b" * 64)

    def test_missing_observations_refuse_instead_of_inventing_load_or_memory(self):
        stage = dict(wall_seconds=25, peak_sampled_tree_rss_bytes=1024 * M.MIB,
                     free_low_bytes=5 * M.GIB)
        for missing in (None, float("nan"), -1, True):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                M.summary_metrics(native_receipt(), stage, machine_busy_cpu_seconds=missing)
        native = native_receipt()
        del native["ab"]["parent_peak_working_set"]
        with self.assertRaises(KeyError):
            M.summary_metrics(native, stage, machine_busy_cpu_seconds=30)


if __name__ == "__main__":
    unittest.main()
