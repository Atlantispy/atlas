"""Disposable offline fixtures only: no science, native imports, subprocesses or queue writes."""
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("plan12_report_under_test", HERE / "report_q22.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf8")


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="report-fixture-", dir=HERE)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "completed-consumer"
        self.run.mkdir()
        self.selection_path = self.root / "selection.json"
        histories = [dict(path=str(self.root / (name + ".json")), sha256="1" * 64)
                     for name in ("h12-r1", "h1c-r4a")]
        self.selection = dict(schema="plan12.successor-consumer-selection.r1", queue_ticket="q22",
                              historical_q10="FAIL", schedule=R.SCHEDULE, output=str(self.run),
                              prediction_history=histories,
                              source_pins={str((R.INTEGRATION / "ab_heat_r13.py").resolve()): "2" * 64})
        write(self.selection_path, self.selection)
        self.selection_sha = R.digest(self.selection_path)
        write(self.run / "attempt.json", dict(mode="consumer", manifest_sha256=self.selection_sha, queue_ticket="q22"))
        self.arms, self.stages = [], []
        bases = dict(lw=100.0, ld3=80.0, le3=64.0, lf3=70.0, lh=50.0)
        for index, spec in enumerate(R.SCHEDULE):
            wall = 999.0 if spec["mode"] == "prof" else bases[spec["layout"]] + (2 if index >= 5 else 0)
            native = dict(status="PASS", elapsed_seconds=wall * 0.9,
                          legacy=dict(seconds=wall * 0.25),
                          compact=dict(seconds=wall * 0.2, result_id="3" * 64),
                          arrays={name: "4" * 64 for name in R.ARRAYS},
                          ab=dict(mode=spec["mode"], layout=str(R.TASK / "hs" / spec["layout"]),
                                  workers_configured=6, leaks=[], control_wall_seconds=round(wall * 0.95, 3),
                                  parent_cpu_seconds=4.0, parent_peak_working_set=256 * (1 << 20),
                                  exact_growth_sha256="5" * 64, gmp_resources_sha256="6" * 64,
                                  interpreter=dict(hash_randomization=0, worker_probe_hash_randomization=0),
                                  consumer_selection=dict(path=str(self.selection_path), sha256=self.selection_sha,
                                                          historical_q10="FAIL"),
                                  calls=[dict(workers=6, fallback=None, seconds=wall * 0.1,
                                              worker_compute_seconds=5.0, worker_working_set_peak_max=64 * (1 << 20)),
                                         dict(workers=6, fallback=None, seconds=wall * 0.08,
                                              worker_compute_seconds=7.0, worker_working_set_peak_max=80 * (1 << 20))]))
            write(self.run / ("arm-" + str(index) + ".json"), native)
            argv = [str(R.TASK / ".r44-env/Scripts/python.exe"), "-B", "-s", "-P",
                    str(R.INTEGRATION / "ab_heat_r13.py"), "child", spec["mode"], native["ab"]["layout"],
                    str(self.run), str(index), "--consumer-selection", str(self.selection_path), self.selection_sha]
            stage = self.stage("arm-" + str(index), wall, argv)
            self.stages.append(stage)
            arm = dict(arm=index, mode=spec["mode"], label=spec["label"], layout=native["ab"]["layout"],
                       input=R.INPUT, status="PASS", exit_code=0, leaks=0, used=[6, 6], fallback=[None, None],
                       legacy_s=native["legacy"]["seconds"], compact_s=native["compact"]["seconds"],
                       recon_s=[call["seconds"] for call in native["ab"]["calls"]], worker_cpu_s=[5.0, 7.0],
                       parent_cpu_seconds=4.0, accounted_cpu_seconds=16.0, machine_busy_cpu_seconds=20.0,
                       other_load_cpus=4.0 / wall, other_load_basis="Qualified residual, not isolated external load.",
                       arm_wall_seconds=wall, tree_peak_mib=1024.0, available_low_mib=5120.0,
                       parent_peak_mib=256.0, worker_peak_mib=80.0,
                       worker_processes=None, worker_processes_basis="No distinct PIDs in retained receipt.",
                       arrays=native["arrays"], result_id="3" * 64,
                       exact_growth_sha256="5" * 64, gmp_resources_sha256="6" * 64,
                       predicted_peak_gib=1.1, prediction_basis="fallback RUNQ_PRED_PEAK_GIB",
                       prediction_history=histories, prediction_writer_sha256="2" * 64,
                       start_gate_gib=3.32, required_start_gate_bytes=3564822856,
                       free_gib_at_start=6.0, gate_waited_s=0.5, start_gate_passed=True)
            if spec["mode"] == "prof":
                profile = self.run / "arm-10/worker-100.prof"
                profile.parent.mkdir()
                profile.write_bytes(b"retained synthetic profile bytes")
                arm["profile_files"] = [dict(path=str(profile.relative_to(self.run)),
                                             bytes=profile.stat().st_size, sha256=R.digest(profile))]
            self.arms.append(arm)
        checker_text = "\n".join(str(index) + " " + spec["mode"] + " " + spec["label"] + " OK {}"
                                  for index, spec in enumerate(R.SCHEDULE)) + "\nARMS PASS\n"
        checker = self.stage("check-arms", 0.25,
                             [str(R.TASK / ".r44-env/Scripts/python.exe"), "-B", "-s", "-P",
                              str(R.TASK / "hs/scripts/check_arms.py"), str(self.run), "11"], checker_text)
        self.stages.append(checker)
        (self.run / "check-arms.txt").write_text(checker_text, encoding="utf8")
        self.save()

    def stage(self, name, wall, argv, stdout=""):
        for suffix, value in (("stdout", stdout), ("stderr", "")):
            (self.run / (name + "." + suffix + ".log")).write_text(value, encoding="utf8")
        result = dict(argv=argv, passed=True, finality="COMPLETE", exit_code=0, errors=[], log_final=True,
                      last_observation=dict(exit_code=0, job=dict(active=0)), wall_seconds=wall,
                      peak_sampled_tree_rss_bytes=1024 * (1 << 20), free_low_bytes=5 * (1 << 30),
                      log_sha256={suffix: R.digest(self.run / (name + "." + suffix + ".log"))
                                  for suffix in ("stdout", "stderr")})
        write(self.run / (name + ".process.json"), result)
        return result

    def save(self):
        write(self.run / "summary.json", dict(arms=self.arms))
        write(self.run / "result.json", dict(schema="plan12-consumer-route-result.r1", passed=True,
                                              historical_q10="FAIL", errors=[], arms=self.arms, stages=self.stages))

    def report(self, queue=None):
        return R.build_report(self.run, self.selection_path, self.selection_sha, queue)

    def test_pairs_percentage_profile_exclusion_and_negative_reductions(self):
        result = self.report()
        self.assertEqual(result["layout_pairs"]["lw"]["arm_indices"], [0, 9])
        self.assertEqual(result["layout_pairs"]["lh"]["arm_indices"], [4, 5])
        self.assertEqual(result["layout_pairs"]["lh"]["descriptive_means"]["arm_wall_seconds"], 51.0)
        self.assertEqual(result["profile"]["metrics"]["arm_wall_seconds"], 999.0)
        total = result["comparisons"][-1]["metrics"]["arm_wall_seconds"]
        self.assertEqual(total["old_observations"], [100.0, 102.0])
        self.assertEqual(total["new_observations"], [50.0, 52.0])
        self.assertAlmostEqual(total["percent_reduction"], 100 * 50 / 101)
        self.assertLess(result["comparisons"][2]["metrics"]["arm_wall_seconds"]["percent_reduction"], 0)
        self.assertIsNone(result["whole_interval"]["measured_percent_reduction"])
        self.assertIsNone(result["observations"][0]["summary"]["worker_processes"])

    def test_missing_extra_and_reordered_arms_refuse(self):
        original = deepcopy(self.arms)
        variants = [original[:-1], original + [original[-1]], [original[1], original[0], *original[2:]]]
        for variant in variants:
            with self.subTest(length=len(variant)):
                self.arms = deepcopy(variant)
                self.save()
                with self.assertRaises(ValueError):
                    self.report()

    def test_incomplete_summary_fields_refuse(self):
        original = deepcopy(self.arms[0])
        for key, value in (("status", "FAIL"), ("exit_code", 1), ("leaks", 1), ("stopped", "stopped"),
                           ("used", [6, 5]), ("used", [6.0, 6]), ("fallback", [None, "serial"])):
            with self.subTest(key=key, value=value):
                self.arms[0] = deepcopy(original)
                self.arms[0][key] = value
                self.save()
                with self.assertRaises(ValueError):
                    self.report()

    def test_extra_native_arm_json_record_refuses(self):
        write(self.run / "arm-11.json", R.read_json(self.run / "arm-10.json"))
        with self.assertRaisesRegex(ValueError, "extra native arm"):
            self.report()

    def test_seed_selection_and_native_worker_evidence_refuse(self):
        path = self.run / "arm-0.json"
        original = R.read_json(path)
        variants = []
        for key in ("hash_randomization", "worker_probe_hash_randomization"):
            value = deepcopy(original)
            value["ab"]["interpreter"][key] = 1
            variants.append(value)
        value = deepcopy(original)
        value["ab"]["consumer_selection"]["sha256"] = "f" * 64
        variants.append(value)
        value = deepcopy(original)
        value["ab"]["calls"][0]["workers"] = 5
        variants.append(value)
        for value in variants:
            write(path, value)
            with self.assertRaises(ValueError):
                self.report()

    def test_process_and_route_completion_refuse(self):
        path = self.run / "result.json"
        original = R.read_json(path)
        for change in ("passed", "errors", "finality", "active", "log_final", "stage_count"):
            value = deepcopy(original)
            if change == "passed":
                value["passed"] = False
            elif change == "errors":
                value["errors"] = ["failure"]
            elif change == "stage_count":
                value["stages"].pop()
            else:
                stage = value["stages"][-1]
                if change == "active":
                    stage["last_observation"]["job"]["active"] = 1
                else:
                    stage[change] = "UNRESOLVED" if change == "finality" else False
                write(self.run / "check-arms.process.json", stage)
            write(path, value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.report()

    def test_actual_child_command_schedule_binding_refuses(self):
        self.stages[0]["argv"][9] = "1"
        write(self.run / "arm-0.process.json", self.stages[0])
        self.save()
        with self.assertRaisesRegex(ValueError, "Child command"):
            self.report()

    def test_migrated_route_keeps_original_predictor_and_refuses_wrong_execution_writer(self):
        filenames = dict(launcher="launch_q22.py", writer="child_q22.py",
                         adapter="launch_adapter.py", gate="migration_gate.py")
        self.selection["execution_route"] = {
            key: dict(path=str((R.PLAN12 / filename).resolve()), sha256="7" * 64)
            for key, filename in filenames.items()}
        self.selection["source_pins"].update({reference["path"]: reference["sha256"]
                                               for reference in self.selection["execution_route"].values()})
        write(self.selection_path, self.selection)
        self.selection_sha = R.digest(self.selection_path)
        write(self.run / "attempt.json", dict(mode="consumer", manifest_sha256=self.selection_sha,
                                              queue_ticket="q22"))
        for index in range(11):
            stage = self.stages[index]
            stage["argv"][4] = str(R.PLAN12 / "child_q22.py")
            stage["argv"][-1] = self.selection_sha
            write(self.run / ("arm-" + str(index) + ".process.json"), stage)
            path = self.run / ("arm-" + str(index) + ".json")
            native = R.read_json(path)
            native["ab"]["consumer_selection"]["sha256"] = self.selection_sha
            write(path, native)
        self.save()
        result = self.report()
        self.assertEqual(result["execution_route"]["mode"], "MIGRATED_ADDITIVE_ROUTE")
        self.assertEqual(result["observations"][0]["summary"]["prediction_writer_sha256"], "2" * 64)
        self.stages[0]["argv"][4] = str(R.INTEGRATION / "ab_heat_r13.py")
        write(self.run / "arm-0.process.json", self.stages[0])
        self.save()
        with self.assertRaisesRegex(ValueError, "Child writer path differs"):
            self.report()

    def test_changed_final_log_and_metric_copy_refuse(self):
        log = self.run / "arm-0.stdout.log"
        log.write_bytes(b"changed after finality")
        with self.assertRaisesRegex(ValueError, "log bytes"):
            self.report()
        log.write_bytes(b"")
        self.arms[0]["legacy_s"] += 1
        self.save()
        with self.assertRaisesRegex(ValueError, "metric differs"):
            self.report()

    def test_rehashed_checker_failure_is_not_accepted(self):
        text = (self.run / "check-arms.txt").read_text(encoding="utf8").replace("ARMS PASS", "ARMS FAIL 1")
        for name in ("check-arms.txt", "check-arms.stdout.log"):
            (self.run / name).write_text(text, encoding="utf8")
        self.stages[-1]["log_sha256"]["stdout"] = R.digest(self.run / "check-arms.stdout.log")
        write(self.run / "check-arms.process.json", self.stages[-1])
        self.save()
        with self.assertRaisesRegex(ValueError, "Checker did not confirm"):
            self.report()

    def test_missing_or_unreported_profile_files_refuse(self):
        path = self.run / self.arms[10]["profile_files"][0]["path"]
        content = path.read_bytes()
        path.unlink()
        with self.assertRaises(OSError):
            self.report()
        path.write_bytes(content)
        (self.run / "arm-10/worker-extra.prof").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "Unreported profile"):
            self.report()

    def test_disk_scope_and_missing_queue_metrics_are_explicit(self):
        (self.root / "unrelated-large-file.bin").write_bytes(b"outside run")
        result = self.report()
        files = list(self.run.rglob("*"))
        self.assertEqual(result["disk"]["file_count"], sum(path.is_file() for path in files))
        self.assertEqual(result["disk"]["bytes"], sum(path.stat().st_size for path in files if path.is_file()))
        self.assertIsNone(result["disk"]["transient_peak_disk_bytes"])
        self.assertEqual(result["queue"]["status"], "UNAVAILABLE")
        self.assertIsNone(result["queue"]["isolated_queue_overhead_seconds"])

    def test_queue_elapsed_residual_and_binding_limits(self):
        path = self.root / "q22-record.json"
        row = dict(id="q22", status="done", exit=0, outputs=[str(self.run)],
                   started="2026-10-20T10:00:00+01:00", ended="2026-10-20T10:30:00+01:00")
        write(path, row)
        result = self.report(path)
        times = result["time_accounting"]
        expected = 1800 - sum(times[key] for key in ("ten_uninstrumented_supervised_arms_seconds",
            "separate_profile_supervised_arm_seconds", "checker_supervised_seconds", "per_arm_memory_gate_wait_seconds"))
        self.assertEqual(result["queue"]["admitted_payload_elapsed_seconds"], 1800)
        self.assertEqual(result["queue"]["admitted_payload_residual_seconds"], expected)
        self.assertIsNone(result["queue"]["pre_admission_queue_wait_seconds"])
        del row["ended"]
        write(path, row)
        self.assertEqual(self.report(path)["queue"]["status"], "UNAVAILABLE")
        row["outputs"] = [str(self.root / "another-run")]
        write(path, row)
        with self.assertRaisesRegex(ValueError, "does not bind"):
            self.report(path)

    def test_installed_queue_string_output_is_accepted_and_stale_string_refused(self):
        path = self.root / "q22-record.json"
        row = dict(id="q22", status="done", exit=0, outputs=str(self.run),
                   started="2026-10-20T10:00:00+01:00", ended="2026-10-20T10:30:00+01:00")
        write(path, row)
        result = self.report(path)
        self.assertEqual(result["queue"]["admitted_payload_elapsed_seconds"], 1800)
        self.assertEqual(result["current_launch_admission"]["status"], "NON_EXECUTABLE_MISSING_DECISIONS")
        row["outputs"] = str(self.root / "stale-output")
        write(path, row)
        with self.assertRaisesRegex(ValueError, "does not bind"):
            self.report(path)

    def test_cli_failure_has_no_partial_report_and_nonzero_exit(self):
        self.arms[0]["status"] = "FAIL"
        self.save()
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = R.main(["--run", str(self.run), "--selection", str(self.selection_path),
                           "--selection-sha256", self.selection_sha])
        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(json.loads(stderr.getvalue())["status"], "REFUSED")

    def test_duplicate_json_and_changed_selection_are_refused(self):
        self.selection_path.write_text('{"schema":"a","schema":"b"}', encoding="utf8")
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            self.report()
        self.selection_sha = R.digest(self.selection_path)
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            self.report()


if __name__ == "__main__":
    unittest.main()
