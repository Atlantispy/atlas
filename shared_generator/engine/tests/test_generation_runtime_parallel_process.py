from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import generation_runtime as runtime


def _spawn_probe(job):
    directory, value = job
    root = Path(directory)
    (root / f"{os.getpid()}.ready").touch()
    deadline = time.monotonic() + 10
    while len(list(root.glob("*.ready"))) < 2:
        if time.monotonic() >= deadline:
            raise RuntimeError("two independent worker processes did not rendezvous")
        time.sleep(0.01)
    time.sleep(0.02)
    return value * value, os.getpid(), multiprocessing.get_start_method()


class SpawnBackendTests(unittest.TestCase):
    def test_spawned_workers_are_distinct_ordered_and_measured(self):
        with tempfile.TemporaryDirectory() as directory:
            stats = runtime.RuntimeStats()
            result = list(runtime.bounded_map(_spawn_probe,
                [(directory, value) for value in range(4)], workers=2,
                backend="process", memory_budget_bytes=256 * 1024**2,
                estimated_task_bytes=16 * 1024**2, stats=stats, phase="spawn"))
        self.assertEqual([row[0] for row in result], [0, 1, 4, 9])
        self.assertEqual(len({row[1] for row in result}), 2)
        self.assertNotIn(os.getpid(), {row[1] for row in result})
        self.assertEqual({row[2] for row in result}, {"spawn"})
        self.assertEqual(stats.counts["spawn.peak_active_workers"], 2)
        self.assertEqual(stats.counts["spawn.observed_processes"], 2)
        self.assertEqual(stats.counts["spawn.completed"], 4)
        self.assertEqual(stats.counts["spawn.process_worker_limit"], 2)
        self.assertGreater(stats.seconds["spawn.worker_elapsed_sum"], 0)
        self.assertGreaterEqual(stats.seconds["spawn.worker_cpu_sum"], 0)

    def test_insufficient_process_reservation_uses_direct_reference(self):
        for workers, budget in ((1, 1024), (8, 128), (8, 16)):
            with self.subTest(workers=workers, budget=budget), mock.patch.object(runtime, "ProcessPoolExecutor") as pool:
                stats = runtime.RuntimeStats()
                self.assertEqual(list(runtime.bounded_map(lambda value: value + 1, [1, 2],
                    workers=workers, backend="process", memory_budget_bytes=budget * 1024**2,
                    estimated_task_bytes=16 * 1024**2, stats=stats)), [2, 3])
                pool.assert_not_called()
                self.assertEqual(stats.counts["compute.worker_limit"], 1)
                self.assertEqual(stats.counts["compute.worker_overhead_bytes"], 0)

    def test_invalid_backend_options_are_rejected_before_loading(self):
        for options in ({"backend": "unsafe"}, {"worker_overhead_bytes": -1},
                        {"worker_overhead_bytes": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                list(runtime.bounded_map(abs, [-1], **options))

    def test_interval_peak_distinguishes_overlap_from_adjacent_work(self):
        self.assertEqual(runtime._interval_peak([(0, 1), (1, 2)]), 1)
        self.assertEqual(runtime._interval_peak([(0, 2), (1, 3), (1.5, 2.5)]), 3)
        self.assertEqual(runtime._interval_peak([(1, 1)]), 0)

    @unittest.skipUnless(os.name == "nt", "Windows process-pool hard limit")
    def test_windows_capacity_is_capped_before_pool_construction(self):
        with mock.patch.object(runtime, "ProcessPoolExecutor") as pool:
            self.assertEqual(list(runtime.bounded_map(abs, [], workers=100,
                backend="process", estimated_task_bytes=1,
                memory_budget_bytes=1000, worker_overhead_bytes=0)), [])
            self.assertEqual(pool.call_args.kwargs["max_workers"], 61)
            pool.return_value.shutdown.assert_called_once_with(wait=True, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
