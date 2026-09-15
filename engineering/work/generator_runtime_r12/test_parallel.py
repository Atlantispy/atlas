"""Process/safety tests with explicit synthetic jobs, not scientific validation."""
import multiprocessing
import os
import unittest
from concurrent.futures.process import BrokenProcessPool
from unittest.mock import patch

from .parallel import PoolBackend


_PREFIX = "main"
_BARRIER = None
_CALLS = 0
_SHA = "a" * 64


def initialise(prefix="child", barrier=None):
    global _PREFIX, _BARRIER, _CALLS
    _PREFIX, _BARRIER, _CALLS = prefix, barrier, 0


def failing_initialise():
    raise ValueError("synthetic initializer failure")


def worker(job):
    global _CALLS
    _CALLS += 1
    action = job.get("action")
    if action == "fail":
        raise ValueError("synthetic worker failure")
    if action == "exit":
        os._exit(13)
    if action == "malformed":
        return job["value"]
    if action == "non-json-result":
        return {"product": {"bad": float("nan")}, "artifacts": {}, "diagnostics": {}}
    if action == "barrier":
        _BARRIER.wait(timeout=20)
    nested_rejected = None
    if action == "nested":
        try:
            PoolBackend(worker)
        except RuntimeError:
            nested_rejected = True
        else:
            nested_rejected = False
    return {"product": {"value": job.get("value"), "prefix": _PREFIX},
            "artifacts": {_SHA: {"value": job.get("value")}},
            "diagnostics": {"pid": os.getpid(), "calls": _CALLS,
                            "nested_rejected": nested_rejected}}


class ConfigurationTests(unittest.TestCase):
    def test_worker_cpu_and_memory_bounds(self):
        for kwargs, expected in (({"workers": 3, "cpu_count": 9}, 3),
                                 ({"workers": 9, "cpu_count": 2}, 2),
                                 ({"workers": 9, "cpu_count": 9, "memory_budget_mb": 750}, 2),
                                 ({"workers": 9, "cpu_count": 9, "memory_budget_mb": 256}, 1)):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(PoolBackend(worker, **kwargs).effective_workers, expected)

    def test_invalid_integer_configuration(self):
        for name in ("workers", "cpu_count", "memory_budget_mb", "worker_memory_mb"):
            for value in (0, -1, True, False, 1.0, "2"):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        PoolBackend(worker, **{name: value})

    def test_insufficient_memory_fails(self):
        with self.assertRaisesRegex(ValueError, "one estimated worker"):
            PoolBackend(worker, memory_budget_mb=100, worker_memory_mb=101)

    def test_cpu_fallback(self):
        with patch("work.generator_runtime_r12.parallel.os.cpu_count", return_value=None):
            self.assertEqual(PoolBackend(worker).effective_workers, 1)

    def test_windows_limit(self):
        with patch("work.generator_runtime_r12.parallel.sys.platform", "win32"):
            self.assertEqual(PoolBackend(worker, workers=100, cpu_count=100,
                                         memory_budget_mb=100, worker_memory_mb=1).effective_workers, 61)

    def test_invalid_callables_and_initargs(self):
        for value in (None, 4, "worker"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                PoolBackend(value)
        with self.assertRaises(ValueError):
            PoolBackend(worker, initializer="not callable")
        with self.assertRaises(ValueError):
            PoolBackend(worker, initargs=[])
        with self.assertRaisesRegex(ValueError, "picklable"):
            PoolBackend(lambda job: job)

    def test_context_required_and_cannot_reenter(self):
        backend = PoolBackend(worker)
        with self.assertRaises(RuntimeError):
            backend.execute([])
        with backend:
            self.assertEqual(backend.execute([]), {})
            with self.assertRaises(RuntimeError):
                backend.__enter__()
        with self.assertRaises(RuntimeError):
            backend.execute([])
        with self.assertRaises(RuntimeError):
            backend.__enter__()
        backend.close()


class ProcessTests(unittest.TestCase):
    def test_one_worker_isolated_and_reused(self):
        with PoolBackend(worker, initializer=initialise, initargs=("initialised",), workers=1) as backend:
            first = backend.execute([{"stage_id": "a", "value": 9}])["a"]
            second = backend.execute([{"stage_id": "b", "value": 10}])["b"]
            self.assertEqual(first["product"], {"value": 9, "prefix": "initialised"})
            self.assertEqual(second["diagnostics"]["calls"], 2)
            self.assertEqual(first["diagnostics"]["pid"], second["diagnostics"]["pid"])
            self.assertNotEqual(first["diagnostics"]["pid"], os.getpid())
            self.assertEqual(_PREFIX, "main")
            self.assertEqual(len(backend.observed_pids), 1)
            self.assertEqual(len(backend.timings["executions"]), 2)
            self.assertTrue(all(item["status"] == "PASS" for item in backend.timings["executions"]))
            self.assertTrue(all(item["wall_s"] >= 0 for item in backend.timings["jobs"]))

    def test_two_processes_overlap_and_result_order_is_deterministic(self):
        barrier = multiprocessing.get_context("spawn").Barrier(2)
        jobs = [{"stage_id": name, "value": index, "action": "barrier"}
                for index, name in enumerate(("z", "a", "d", "b", "y", "c"))]
        with PoolBackend(worker, initializer=initialise, initargs=("two", barrier),
                         workers=2, cpu_count=2) as backend:
            result = backend.execute(jobs)
            self.assertEqual(list(result), [job["stage_id"] for job in jobs])
            self.assertEqual(len(backend.observed_pids), 2)
            self.assertNotIn(os.getpid(), backend.observed_pids)
            self.assertEqual(backend.timings["peak_in_flight"], 2)
            self.assertEqual([r["product"]["value"] for r in result.values()], list(range(6)))

    def test_nested_backend_rejected(self):
        with PoolBackend(worker, workers=1) as backend:
            result = backend.execute([{"stage_id": "nested", "action": "nested"}])
            self.assertTrue(result["nested"]["diagnostics"]["nested_rejected"])

    def test_caller_job_unchanged_and_extra_json_fields_allowed(self):
        job = {"stage_id": "test/1", "value": [None, True, 1.25, {"x": "test"}],
               "records": {_SHA: {"bytes": "BASE64"}}}
        with PoolBackend(worker, workers=1) as backend:
            result = backend.execute([job])
            result["test/1"]["product"]["value"].append("local result change")
        self.assertEqual(job["value"], [None, True, 1.25, {"x": "test"}])

    def test_timings_are_defensive_copies(self):
        with PoolBackend(worker, workers=1) as backend:
            backend.execute([{"stage_id": "a"}])
            timing = backend.timings
            timing["jobs"][0]["pid"] = -1
            timing["executions"].clear()
            self.assertNotEqual(backend.timings["jobs"][0]["pid"], -1)
            self.assertEqual(len(backend.timings["executions"]), 1)


class FailureTests(unittest.TestCase):
    def invalid_jobs(self, jobs):
        with PoolBackend(worker, workers=1) as backend:
            with self.assertRaises(ValueError):
                backend.execute(jobs)
            self.assertEqual(backend.observed_pids, ())
            self.assertEqual(backend.timings["peak_in_flight"], 0)
            with self.assertRaises(RuntimeError):
                backend.execute([])

    def test_malformed_jobs_fail_before_any_submission(self):
        for jobs in ((), {}, None, [1], [{}], [{"stage_id": ""}], [{"stage_id": " a"}],
                     [{"stage_id": True}], [{"stage_id": "x" * 257}],
                     [{"stage_id": "a"}, {"stage_id": "a"}]):
            with self.subTest(jobs=jobs):
                self.invalid_jobs(jobs)

    def test_non_json_jobs_fail_before_any_submission(self):
        for value in (float("nan"), float("inf"), b"bytes", (1, 2), {1: "non-string key"}):
            with self.subTest(value=value):
                self.invalid_jobs([{"stage_id": "a", "extra": value}])
        cyclic = []
        cyclic.append(cyclic)
        self.invalid_jobs([{"stage_id": "a", "extra": cyclic}])

    def test_worker_failure_closes_and_no_partial_result(self):
        with PoolBackend(worker, workers=1) as backend:
            with self.assertRaisesRegex(ValueError, "synthetic worker failure"):
                backend.execute([{"stage_id": "a"}, {"stage_id": "b", "action": "fail"},
                                 {"stage_id": "must_not_run"}])
            self.assertEqual([item["stage_id"] for item in backend.timings["jobs"]], ["a"])
            self.assertEqual(backend.timings["executions"][0]["status"], "FAILED")
            self.assertIsNone(backend._executor)
            with self.assertRaises(RuntimeError):
                backend.execute([])

    def test_initializer_failure_closes(self):
        with PoolBackend(worker, initializer=failing_initialise, workers=1) as backend:
            with self.assertRaises(BrokenProcessPool):
                backend.execute([{"stage_id": "a"}])
            self.assertIsNone(backend._executor)
            with self.assertRaises(RuntimeError):
                backend.execute([])

    def test_abrupt_worker_exit_closes(self):
        with PoolBackend(worker, workers=1) as backend:
            with self.assertRaises(BrokenProcessPool):
                backend.execute([{"stage_id": "a", "action": "exit"}])
            self.assertIsNone(backend._executor)
            with self.assertRaises(RuntimeError):
                backend.execute([])

    def test_malformed_worker_records_rejected(self):
        valid = {"product": {}, "artifacts": {}, "diagnostics": {}}
        records = [None, [], {}, {**valid, "extra": 1}, {**valid, "product": []},
                   {**valid, "artifacts": []}, {**valid, "diagnostics": []},
                   {**valid, "artifacts": {"not-sha": {}}},
                   {**valid, "artifacts": {"A" * 64: {}}},
                   {**valid, "artifacts": {_SHA: []}}]
        for value in records:
            with self.subTest(value=value):
                with PoolBackend(worker, workers=1) as backend:
                    with self.assertRaises(ValueError):
                        backend.execute([{"stage_id": "a", "action": "malformed", "value": value}])
                    with self.assertRaises(RuntimeError):
                        backend.execute([])

    def test_non_json_worker_result_rejected(self):
        with PoolBackend(worker, workers=1) as backend:
            with self.assertRaisesRegex(ValueError, "non-finite"):
                backend.execute([{"stage_id": "a", "action": "non-json-result"}])
            with self.assertRaises(RuntimeError):
                backend.execute([])

    def test_concurrent_execute_rejected(self):
        with PoolBackend(worker, workers=1) as backend:
            backend._lock.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "concurrent"):
                    backend.execute([])
            finally:
                backend._lock.release()
            self.assertEqual(backend.execute([]), {})


if __name__ == "__main__":
    unittest.main()
