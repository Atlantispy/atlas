import importlib.util
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("plan05_launcher_tested", HERE / "launch_plan05_r13.py")
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


@contextmanager
def fixture_dir():
    root = HERE / "launcher-test-artifacts"
    root.mkdir(exist_ok=True)
    # Retain native process receipts and failed fixtures rather than deleting them.
    yield tempfile.mkdtemp(prefix="case-", dir=root)


class FakeJob:
    def __init__(self, observations):
        self.observations = iter(observations)
        self.last = None
        self.killed = False
        self.pi = SimpleNamespace(process=True)

    def snapshot(self):
        if self.killed:
            return {"job": {"active": 0}, "exit_code": 91}
        self.last = next(self.observations, self.last)
        if isinstance(self.last, BaseException):
            raise self.last
        return self.last

    def terminate_owned(self):
        self.killed = True
        return "retained-job-handle"


def obs(active, code=None):
    return {"job": {"active": active}, "exit_code": code}


class LauncherTests(unittest.TestCase):
    def supervise(self, job, sample=None, seconds=5):
        ticks = iter(range(100))
        return L.supervise(job, seconds, sample=sample or (lambda _: (100, 8 * L.GIB)),
                           clock=lambda: next(ticks) / 10, sleep=lambda _: None)

    def test_nonzero_exit_never_passes(self):
        result = self.supervise(FakeJob([obs(0, 7)]))
        self.assertEqual(result["finality"], "COMPLETE")
        self.assertFalse(result["passed"])
        self.assertEqual(result["exit_code"], 7)

    def test_root_exit_waits_for_descendant(self):
        job = FakeJob([obs(2), obs(1, 0), obs(0, 0)])
        calls = []
        result = self.supervise(job, lambda _: (calls.append(1) or 100, 8 * L.GIB))
        self.assertEqual(len(calls), 2)
        self.assertTrue(result["passed"])

    def test_query_failure_remains_failure_after_cleanup(self):
        job = FakeJob([OSError("injected query failure")])
        result = self.supervise(job)
        self.assertTrue(job.killed)
        self.assertEqual(result["finality"], "COMPLETE")
        self.assertFalse(result["passed"])
        self.assertIn("injected query failure", result["errors"][0])

    def test_sampler_failure_does_not_mean_empty_membership(self):
        def broken(_):
            raise OSError("membership unavailable")
        job = FakeJob([obs(1)])
        result = self.supervise(job, broken)
        self.assertTrue(job.killed)
        self.assertFalse(result["passed"])

    def test_resource_guards_stop_owned_job(self):
        for sample in (lambda _: (L.RSS_GUARD + 1, 8 * L.GIB),
                       lambda _: (100, L.FREE_FLOOR - 1)):
            job = FakeJob([obs(1)])
            result = self.supervise(job, sample)
            self.assertTrue(job.killed)
            self.assertFalse(result["passed"])
            self.assertIn("resource guard", result["errors"][0])

    def test_cancellation_preserved(self):
        job = FakeJob([KeyboardInterrupt("cancel")])
        result = self.supervise(job)
        self.assertFalse(result["passed"])
        self.assertIn("KeyboardInterrupt", result["errors"][0])

    def test_deadline_stops_whole_job(self):
        job = FakeJob([obs(1)])
        result = self.supervise(job, seconds=0.05)
        self.assertFalse(result["passed"])
        self.assertTrue(job.killed)
        self.assertEqual(result["finality"], "COMPLETE")

    def test_exact_admission_formula_and_low_memory_refusal(self):
        manifest = {"capture_added_memory_mib": 24}
        prediction = 1.03 + 24 / 1024
        need = max(prediction * 1.2 + 2, round(prediction * 1.2 + 2, 1))
        env = {"RUNQ_TICKET_GIB": str(prediction), "RUNQ_MEM_NEED_GIB": str(round(need, 1))}
        gate = L.admission(manifest, 8 * L.GIB, env)
        self.assertEqual(gate["predicted_peak_gib"], prediction)
        self.assertEqual(gate["start_gate_gib"], need)
        with self.assertRaisesRegex(ValueError, "below capture"):
            L.admission(manifest, int(need * L.GIB) - 1, env)
        with self.assertRaisesRegex(ValueError, "booking below"):
            L.admission(manifest, 8 * L.GIB, dict(env, RUNQ_TICKET_GIB="1.03"))

    def test_actual_queue_decimal_booking_accepts_exact_sum_only(self):
        manifest = {"capture_added_memory_mib": 1024}
        # These are the exact strings emitted by runq for the q29 booking.
        env = {"RUNQ_TICKET_GIB": "2.03", "RUNQ_MEM_NEED_GIB": "4.4"}
        gate = L.admission(manifest, 8 * L.GIB, env)
        self.assertEqual(gate["predicted_peak_gib"], 2.03)
        self.assertEqual(gate["start_gate_gib"], 4.436)
        with self.assertRaisesRegex(ValueError, "booking below"):
            L.admission(manifest, 8 * L.GIB, dict(env, RUNQ_TICKET_GIB="2.0299999999999998"))
        with self.assertRaisesRegex(ValueError, "below capture"):
            L.admission(manifest, int(4.436 * L.GIB) - 1, env)

    def test_environment_and_nonoverwrite(self):
        env = L.child_env()
        self.assertEqual({k: v for k, v in env.items() if k.upper().startswith("PYTHON")},
                         {"PYTHONHASHSEED": "0"})
        self.assertEqual(env["ATLAS_HS_DIR"], str(L.T / "hs"))
        with fixture_dir() as tmp:
            target = Path(tmp) / "once.json"
            L.write_new(target, {"attempt": 1})
            with self.assertRaises(FileExistsError):
                L.write_new(target, {"attempt": 2})
            self.assertEqual(L.read_json(target), {"attempt": 1})

    def test_explicit_continuation_consumes_once_without_erasing_prior(self):
        with fixture_dir() as tmp, patch.object(L, "HERE", Path(tmp)):
            base = Path(tmp)
            old_out = base / "first"
            old_out.mkdir()
            L.write_new(old_out / "result.json", {"stages": [
                {"finality": "COMPLETE", "log_final": True}]})
            old_marker = base / "D02-ATTEMPT.json"
            L.write_new(old_marker, {"out": str(old_out)})
            original = old_marker.read_bytes()
            out = base / "second"
            authority = {"scope": ["lf3", "lh"], "maximum_attempts": 1,
                         "output": str(out), "user_instruction": "explicit fixture authority",
                         "thread_id": "fixture", "prior_attempts": [
                             {"marker": old_marker.name,
                              "marker_sha256": L.digest(old_marker),
                              "result_sha256": L.digest(old_out / "result.json")}]}
            manifest = {"continuation_authority": authority}
            with self.assertRaisesRegex(ValueError, "explicit continuation"):
                L.claim_capture({}, "old", out, {})
            with self.assertRaisesRegex(ValueError, "bind one pair"):
                L.claim_capture(manifest, "new", base / "other", {})
            marker = L.claim_capture(manifest, "new", out, {})
            self.assertEqual(marker.name, "D02-ATTEMPT-02.json")
            self.assertEqual(old_marker.read_bytes(), original)
            self.assertEqual(L.read_json(marker)["continuation_authority"], authority)
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                L.claim_capture(manifest, "new", out, {})

    def test_continuation_refuses_changed_or_unfinished_predecessor(self):
        for fault in ("marker", "result", "finality", "missing", "scope"):
            with self.subTest(fault=fault), fixture_dir() as tmp, patch.object(L, "HERE", Path(tmp)):
                base = Path(tmp)
                old_out = base / "first"
                old_out.mkdir()
                L.write_new(old_out / "result.json", {"stages": [{
                    "finality": "UNRESOLVED" if fault == "finality" else "COMPLETE",
                    "log_final": fault != "finality"}]})
                old_marker = base / "D02-ATTEMPT.json"
                L.write_new(old_marker, {"out": str(old_out)})
                out = base / "second"
                authority = {"scope": ["lf3"] if fault == "scope" else ["lf3", "lh"],
                             "maximum_attempts": 1, "output": str(out),
                             "user_instruction": "explicit fixture authority", "thread_id": "fixture",
                             "prior_attempts": [] if fault == "missing" else [{
                                 "marker": old_marker.name,
                                 "marker_sha256": "bad" if fault == "marker" else L.digest(old_marker),
                                 "result_sha256": "bad" if fault == "result" else
                                 L.digest(old_out / "result.json")}]}
                with self.assertRaises(ValueError):
                    L.claim_capture({"continuation_authority": authority}, "new", out, {})
                self.assertFalse((base / "D02-ATTEMPT-02.json").exists())

    def test_missing_writer_or_verifier_pin_refused(self):
        required = {"writer.py", "verifier.py", "backend.py"}
        for absent in ("writer.py", "verifier.py"):
            manifest = {"source_pins": {name: "a" * 64 for name in required - {absent}}}
            with self.assertRaisesRegex(ValueError, "Unbound selected"):
                L.require_pin_coverage(manifest, required)

    def test_dispatch_failure_keeps_primary_traceback(self):
        class BrokenStart:
            def __init__(self):
                self.identity = {}
                self.pi = SimpleNamespace(process=False)
            def start(self, *args):
                raise OSError("injected primary start failure")
            def terminate_owned(self):
                return "no-process-created"
            def snapshot(self):
                return obs(0, 91)
            def close(self):
                pass
        with fixture_dir() as tmp, patch.object(
                L, "load_module", return_value=SimpleNamespace(WindowsJob=BrokenStart)):
            result = L.execute_owned([str(L.P), "-B", "-c", "pass"], Path(tmp), "failure", 1)
        self.assertFalse(result["passed"])
        self.assertTrue(any("injected primary start failure" in text for text in result["errors"]))

    def test_real_job_membership_sampling_and_descendant_finality(self):
        # Changed sampler uses real QueryInformationJobObject class 3. The
        # unchanged process-ownership backend has retained r9 OS evidence.
        self.assertEqual(os.name, "nt")
        with fixture_dir() as tmp:
            out = Path(tmp)
            command = [str(L.P), "-B", "-c",
                       "import subprocess,sys,time; "
                       "subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(0.7)']); "
                       "time.sleep(0.2); sys.exit(7)"]
            result = L.execute_owned(command, out, "native", 5)
            self.assertEqual(result["exit_code"], 7)
            self.assertEqual(result["finality"], "COMPLETE")
            self.assertTrue(result["log_final"])
            self.assertFalse(result["passed"])
            self.assertGreater(result["peak_sampled_tree_rss_bytes"], 0)
            self.assertGreaterEqual(result["ownership"]["initial_accounting"]["active"], 1)
            self.assertGreaterEqual(result["last_observation"]["job"]["total"], 2)
            self.assertEqual(result["last_observation"]["job"]["active"], 0)

    def test_no_process_created_can_finish_without_invented_exit(self):
        class NeverStarted:
            pi = SimpleNamespace(process=False)

            def snapshot(self):
                return obs(0, None)
        result = L.supervise(NeverStarted(), 1)
        self.assertEqual(result["finality"], "COMPLETE")
        self.assertIsNone(result["exit_code"])
        self.assertFalse(result["passed"])

    def test_source_snapshot_retains_exact_failed_attempt_inputs(self):
        with fixture_dir() as tmp:
            base = Path(tmp)
            route, native, previous = base / "route", base / "native", base / "previous"
            files = (route / "writer.py",
                     route / "worker-flags-repair/worker_flags_repair.py",
                     route / "worker-flags-repair/test_worker_flags_repair.py",
                     native / "q/runq.py",
                     native / "hs/scripts/check_arms.py", previous / "owned_windows_job.py")
            for number, path in enumerate(files):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("source " + str(number)).encode())
            manifest = {"source_pins": {str(path): L.digest(path) for path in files}}
            out = base / "attempt"
            out.mkdir()
            with patch.multiple(L, HERE=route, T=native, PREVIOUS=previous):
                L.retain_selected_sources(manifest, out)
                index = L.read_json(out / "source-inputs/index.json")
                for path in files:
                    retained = out / "source-inputs" / index[str(path)]["file"]
                    self.assertEqual(L.digest(retained), manifest["source_pins"][str(path)])
                files[0].write_bytes(b"next revision")
                self.assertNotEqual(L.digest(files[0]), manifest["source_pins"][str(files[0])])
                stale_out = base / "stale-attempt"
                stale_out.mkdir()
                with self.assertRaisesRegex(ValueError, "Source changed before retention"):
                    L.retain_selected_sources(manifest, stale_out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
