"""Actual consumer orchestration, disposable host paths, mocked science only."""
import builtins
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
INTEGRATION = HERE.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FIXTURES = load("plan12_integration_fixtures", HERE / "test_proof_gate.py")
L = load("plan12_actual_launcher", INTEGRATION / "launch_plan05_r13.py")
W = load("plan12_actual_writer", INTEGRATION / "ab_heat_r13.py")


class ConsumerLauncherIntegration(unittest.TestCase):
    def setUp(self):
        # Compose the already-authored synthetic evidence fixture without
        # inheriting/rerunning its test methods.
        self.f = FIXTURES.ProofGateTests("test_valid_bound_proof_and_separate_decisions")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.child_calls = []
        self.fail_arm = None
        self.bad_workers = False
        self.bad_interpreter = False
        self.bad_checker = False
        self.missing_profile = False
        self.f.source_paths = []
        self.route = self.f.integration
        self.f.output = self.route / "consumer-output"
        consumer = self.route / "consumer-repair"
        consumer.mkdir(exist_ok=True)

        # Same gate/metrics and adapter logic, with TASK replaced by the
        # disposable host root. The writer is loaded for its pure predictor;
        # no producer/control code is imported and all child dispatch is mocked.
        gate = (HERE / "proof_gate.py").read_text(encoding="utf8")
        old = 'TASK = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")'
        self.assertEqual(gate.count(old), 1)
        gate = gate.replace(old, "TASK = Path(" + repr(str(self.f.task)) + ")", 1)
        self.put(consumer / "proof_gate.py", gate)
        metrics = (HERE / "metrics.py").read_text(encoding="utf8")
        self.assertEqual(metrics.count(old), 1)
        self.put(consumer / "metrics.py",
                 metrics.replace(old, "TASK = Path(" + repr(str(self.f.task)) + ")", 1))
        self.put(consumer / "launch_adapter.py", (HERE / "launch_adapter.py").read_text(encoding="utf8"))
        self.put(consumer / "worker_runtime.py", "# Synthetic; worker runtime tested separately.\n")
        self.put(self.route / "ab_heat_r13.py",
                 (INTEGRATION / "ab_heat_r13.py").read_text(encoding="utf8"))
        for name in ("launch_plan05_r13.py", "verify_d02_r13.py"):
            self.put(self.route / name, "# Synthetic selected route; dispatch is mocked.\n")
        for name in ("worker_flags_repair.py", "test_worker_flags_repair.py"):
            self.put(self.route / "worker-flags-repair" / name, "# Synthetic source.\n")
        self.previous = self.route.parent / "r9-launch-prep"
        self.put(self.previous / "owned_windows_job.py", "# Supervisor is already tested; process dispatch mocked.\n")
        self.put(self.f.task / ".r44-env/Scripts/python.exe", "Synthetic interpreter identity only.")
        self.put(self.f.task / "q/runq.py", "# No queue command is run.\n")
        self.checker = self.f.task / "hs/scripts/check_arms.py"
        self.put(self.checker, (L.T / "hs/scripts/check_arms.py").read_text(encoding="utf8"))
        self.put(self.f.task / "hs/workerprof/sitecustomize.py", "# Synthetic selected profile startup.\n")
        for layout in ("lw", "ld3", "le3", "lf3", "lh"):
            paths = []
            for directory in ("runtime-src", "helpers", "ram"):
                path = self.f.task / "hs" / layout / directory
                self.put(path / "synthetic_dependency.py", "# Fixture source, never imported.\n")
                paths.append(str(path))
            control = self.f.task / "hs" / layout / "control.json"
            self.f.write(control, dict(paths=paths))
            self.f.source_paths.append(control)
        history_paths = []
        for name in ("h12-r1", "h1c-r4a"):
            path = self.f.task / "hs/evidence" / name / "summary.json"
            self.f.write(path, dict(arms=[dict(
                arm=0, mode="proof", layout=str(self.f.task / "hs/lh"),
                used=[6, 6], status="PASS", exit_code=0, tree_peak_mib=1024)]))
            self.f.source_paths.append(path)
            history_paths.append(path)
        self.f.source_paths += self.f.overlays
        self.f.source_pins = {str(path): FIXTURES.G.digest(path) for path in self.f.source_paths}
        self.f.selection["source_pins"] = dict(self.f.source_pins)
        self.f.write(self.f.selection_path, self.f.selection)
        self.f.selection_sha = FIXTURES.G.digest(self.f.selection_path)
        self.f.write(self.f.proof / "attempt.json",
                     dict(mode="capture", manifest_sha256=self.f.selection_sha))
        for arm in ("arm_a", "arm_b"):
            evidence = self.f.report["metadata"]["evidence"]["order_repair"][arm]
            evidence["launch_manifest_sha256"] = self.f.selection_sha
            evidence["descriptor"]["manifest_sha256"] = self.f.selection_sha
        self.f.reseal()
        self.f.manifest["resource_admission"] = dict(
            baseline_observed_gib=1.03, added_memory_mib=1024,
            basis="Synthetic integration control of the recorded 1.03 + 1 GiB forecast.")
        self.f.manifest["prediction_history"] = [
            dict(path=str(path), sha256=FIXTURES.G.digest(path)) for path in history_paths]
        self.f.save_manifest()
        self.args = SimpleNamespace(manifest=self.f.manifest_path,
                                    manifest_sha256=self.f.sha, out=self.f.output)
        self.queue = dict(hold=None, tickets=[dict(
            id="q22", status="running", ticket_hold=None, quiet=True,
            exclusive=True, cores=7, runner_pid=9001)])
        self.write_queue()
        patches = (
            patch.object(L, "HERE", self.route),
            patch.object(L, "T", self.f.task),
            patch.object(L, "P", self.f.task / ".r44-env/Scripts/python.exe"),
            patch.object(L, "PREVIOUS", self.previous),
            patch.object(L.psutil, "Process", return_value=SimpleNamespace(
                parents=lambda: [SimpleNamespace(pid=9001)])),
            patch.object(L.psutil, "virtual_memory", return_value=SimpleNamespace(available=10 * L.GIB)),
            patch.object(L.psutil, "cpu_times", return_value=SimpleNamespace(
                idle=0, _asdict=lambda: dict(user=100, system=0, idle=0))),
            patch.dict(os.environ, {"RUNQ_TICKET_GIB": "2.03", "RUNQ_MEM_NEED_GIB": "4.4",
                                    "RUNQ_PRED_PEAK_GIB": "2.03"}, clear=False),
            patch.object(L, "execute_owned", side_effect=self.execute),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def put(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf8")
        self.f.source_paths.append(path.resolve())

    def write_queue(self):
        self.f.write(self.f.task / "q/queue.json", self.queue)

    def execute(self, argv, out, name, seconds, env=None):
        self.child_calls.append(dict(argv=argv, name=name, seconds=seconds, env=env))
        if name == "check-arms":
            # Exercise the actual existing checker in-process against saved
            # summary bytes. This is no scientific job and starts no process.
            if self.bad_checker:
                data = L.read_json(out / "summary.json")
                data["arms"][0]["used"] = [5, 6]
                (out / "summary.json").write_text(json.dumps(data), encoding="utf8")
            output = io.StringIO()
            with patch.object(sys, "argv", [str(x) for x in argv[4:]]), redirect_stdout(output):
                try:
                    runpy.run_path(str(self.checker), run_name="__main__")
                except SystemExit as error:
                    code = error.code
            (out / "check-arms.stdout.log").write_text(output.getvalue(), encoding="utf8")
        else:
            index = int(name.split("-")[1])
            code = 7 if index == self.fail_arm else 0
            if code == 0:
                self.f.write(out / (name + ".json"), dict(
                    status="PASS", legacy=dict(seconds=0.0025),
                    compact=dict(seconds=0.002, result_id="a" * 64),
                    arrays={key: "b" * 64 for key in FIXTURES.G.ARRAYS},
                    ab=dict(leaks=[], calls=[
                        dict(workers=5 if self.bad_workers else 6, fallback=None,
                             seconds=0.001, worker_compute_seconds=0.002,
                             worker_working_set_peak_max=128 * (1 << 20)),
                        dict(workers=6, fallback=None, seconds=0.001,
                             worker_compute_seconds=0.002,
                             worker_working_set_peak_max=128 * (1 << 20))],
                        parent_cpu_seconds=0.002, parent_peak_working_set=256 * (1 << 20),
                        exact_growth_sha256="c" * 64, gmp_resources_sha256="d" * 64,
                        interpreter=dict(hash_randomization=0,
                                         worker_probe_hash_randomization=1 if self.bad_interpreter else 0),
                        consumer_selection=dict(sha256=self.args.manifest_sha256))))
                if index == 10 and not self.missing_profile:
                    (out / "arm-10/worker-synthetic.prof").write_bytes(
                        b"Synthetic nonempty profile receipt; not profiling evidence.")
        stage = dict(passed=code == 0, exit_code=code, finality="COMPLETE", log_final=True,
                     errors=[], last_observation=dict(job=dict(active=0)), wall_seconds=0.01,
                     peak_sampled_tree_rss_bytes=1 << 20, free_low_bytes=8 * L.GIB)
        self.f.write(out / (name + ".process.json"), stage)
        return stage

    def run_consumer(self):
        with redirect_stdout(io.StringIO()):
            return L.run_consumer(self.args)

    def test_complete_schedule_uses_actual_checker_and_retains_selected_overlay(self):
        self.assertEqual(self.run_consumer(), 0)
        self.assertEqual([call["name"] for call in self.child_calls],
                         ["arm-" + str(index) for index in range(11)] + ["check-arms"])
        result = L.read_json(self.f.output / "result.json")
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["arms"]), 11)
        self.assertEqual(result["arms"][-1]["mode"], "prof")
        self.assertEqual(result["arms"][0]["legacy_s"], 0.0025)
        self.assertEqual(result["arms"][0]["worker_peak_mib"], 128)
        self.assertIsNone(result["arms"][0]["worker_processes"])
        self.assertEqual(result["arms"][0]["predicted_peak_gib"], 2.03)
        self.assertEqual(result["arms"][9]["predicted_peak_gib"], 1)
        self.assertIn("this run", result["arms"][9]["prediction_basis"])
        self.assertEqual(result["arms"][10]["predicted_peak_gib"], 2.03)
        self.assertIn("ARMS PASS", (self.f.output / "check-arms.stdout.log").read_text())
        retained = L.read_json(self.f.output / "source-inputs/index.json")
        self.assertTrue({str(path) for path in self.f.overlays} <= set(retained))
        for path in self.f.overlays:
            self.assertEqual(FIXTURES.G.digest(self.f.output / "source-inputs" / retained[str(path)]["file"]),
                             self.f.source_pins[str(path)])
        self.assertEqual(self.child_calls[10]["env"]["PYTHONPATH"], str(self.f.task / "hs/workerprof"))
        with self.assertRaises(ValueError):
            self.run_consumer()
        self.assertEqual(len(self.child_calls), 12)

    def test_failed_arm_stops_after_one_and_retains_final_records(self):
        self.fail_arm = 0
        self.assertEqual(self.run_consumer(), 1)
        self.assertEqual([call["name"] for call in self.child_calls], ["arm-0"])
        result = L.read_json(self.f.output / "result.json")
        self.assertFalse(result["passed"])
        self.assertEqual(result["stages"][0]["exit_code"], 7)
        self.assertTrue(result["stages"][0]["log_final"])
        self.assertIn("stopped", result["arms"][0])
        self.assertEqual(len(L.read_json(self.f.output / "summary.json")["arms"]), 1)

    def test_worker_route_failure_stops_before_next_arm(self):
        self.bad_workers = True
        self.assertEqual(self.run_consumer(), 1)
        self.assertEqual([call["name"] for call in self.child_calls], ["arm-0"])
        self.assertFalse(L.read_json(self.f.output / "result.json")["passed"])

    def test_invalid_saved_interpreter_receipt_stops_before_next_arm(self):
        self.bad_interpreter = True
        self.assertEqual(self.run_consumer(), 1)
        self.assertEqual([call["name"] for call in self.child_calls], ["arm-0"])
        self.assertFalse(L.read_json(self.f.output / "result.json")["passed"])

    def test_missing_profile_refuses_before_final_checker(self):
        self.missing_profile = True
        self.assertEqual(self.run_consumer(), 1)
        self.assertEqual(len(self.child_calls), 11)
        self.assertNotIn("check-arms", [call["name"] for call in self.child_calls])
        self.assertIn("no nonempty profile files",
                      L.read_json(self.f.output / "result.json")["errors"][0])

    def test_existing_checker_failure_propagates(self):
        self.bad_checker = True
        self.assertEqual(self.run_consumer(), 1)
        result = L.read_json(self.f.output / "result.json")
        self.assertEqual(result["stages"][-1]["exit_code"], 1)
        self.assertFalse(result["passed"])

    def test_held_or_unrelated_queue_runner_refuses_before_claim(self):
        for change in (dict(status="held", ticket_hold="still held"), dict(runner_pid=123)):
            with self.subTest(change=change):
                original = dict(self.queue["tickets"][0])
                self.queue["tickets"][0].update(change)
                self.write_queue()
                with self.assertRaises(ValueError):
                    self.run_consumer()
                self.assertFalse(self.f.output.exists())
                self.assertEqual(self.child_calls, [])
                self.queue["tickets"][0] = original

    def test_exact_source_and_resource_gates_precede_dispatch(self):
        original = self.f.manifest["source_pins"][str(self.route / "consumer-repair/proof_gate.py")]
        self.f.manifest["source_pins"][str(self.route / "consumer-repair/proof_gate.py")] = "0" * 64
        self.f.save_manifest()
        self.args.manifest_sha256 = self.f.sha
        with self.assertRaisesRegex(ValueError, "adapter/gate is not source-bound"):
            self.run_consumer()
        self.f.manifest["source_pins"][str(self.route / "consumer-repair/proof_gate.py")] = original
        self.f.save_manifest()
        self.args.manifest_sha256 = self.f.sha
        with patch.dict(os.environ, {"RUNQ_TICKET_GIB": "2.0299999999999999"}):
            with self.assertRaisesRegex(ValueError, "booking below dynamic prediction"):
                self.run_consumer()
        with patch.object(L.psutil, "virtual_memory", return_value=SimpleNamespace(available=int(4.43 * L.GIB))):
            with self.assertRaisesRegex(ValueError, "Free memory below"):
                self.run_consumer()
        self.assertFalse(self.f.output.exists())
        self.assertEqual(self.child_calls, [])

    def test_changed_pin_between_arms_retains_failure_without_second_dispatch(self):
        original_execute = self.execute

        def mutate_after_first(*args, **kwargs):
            stage = original_execute(*args, **kwargs)
            (self.route / "ab_heat_r13.py").write_text("changed after first arm", encoding="utf8")
            return stage

        with patch.object(L, "execute_owned", side_effect=mutate_after_first):
            self.assertEqual(self.run_consumer(), 1)
        self.assertEqual([call["name"] for call in self.child_calls], ["arm-0"])
        self.assertIn("Pinned bytes changed", L.read_json(self.f.output / "result.json")["errors"][0])

    def test_changed_metrics_or_history_refuses_before_claim(self):
        for path in (self.route / "consumer-repair/metrics.py",
                     self.f.task / "hs/evidence/h12-r1/summary.json"):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(original + b"\nchanged after selection\n")
                with self.assertRaisesRegex(ValueError, "Pinned bytes changed"):
                    self.run_consumer()
                self.assertFalse(self.f.output.exists())
                self.assertEqual(self.child_calls, [])
                path.write_bytes(original)

    def test_missing_acceptance_refused_before_any_producer_import(self):
        self.f.manifest.pop("correctness_acceptance")
        self.f.save_manifest()
        self.args.manifest_sha256 = self.f.sha
        original_import = builtins.__import__
        producer_imports = []

        def guarded_import(name, *args, **kwargs):
            if name.startswith("private_heat_") or name.startswith("atlas_tectonics"):
                producer_imports.append(name)
                raise AssertionError("Producer imported before authority")
            return original_import(name, *args, **kwargs)

        with patch.object(W, "HERE", self.route), patch.object(builtins, "__import__", side_effect=guarded_import):
            with self.assertRaises(ValueError):
                W.child("time", self.f.task / "hs/lf3", self.f.output, 3,
                        consumer_manifest=self.f.manifest_path, consumer_manifest_sha=self.f.sha)
        self.assertEqual(producer_imports, [])
        self.assertFalse(self.f.output.exists())


if __name__ == "__main__":
    unittest.main()
