from __future__ import annotations

import threading
import unittest

import generation_runtime as runtime


class SchedulerTelemetryTests(unittest.TestCase):
    def test_real_overlap_is_recorded_and_results_stay_ordered(self):
        rendezvous = threading.Barrier(2)
        stats = runtime.RuntimeStats()
        caller = threading.get_ident()
        threads = set()
        lock = threading.Lock()

        def calculate(item):
            with lock:
                threads.add(threading.get_ident())
            rendezvous.wait(timeout=3)
            return item * item

        actual = list(runtime.bounded_map(calculate, range(6), workers=8,
            memory_budget_bytes=20, estimated_task_bytes=10,
            stats=stats, phase="fixture"))
        self.assertEqual(actual, [0, 1, 4, 9, 16, 25])
        self.assertEqual(len(threads), 2)
        self.assertNotIn(caller, threads)
        self.assertEqual(stats.counts["fixture.worker_limit"], 2)
        self.assertEqual(stats.counts["fixture.peak_active_workers"], 2)
        self.assertEqual(stats.counts["fixture.peak_inflight"], 2)
        self.assertEqual(stats.counts["fixture.admitted"], 6)
        self.assertEqual(stats.counts["fixture.completed"], 6)
        self.assertGreaterEqual(stats.seconds["fixture.worker_elapsed_sum"], 0)

    def test_serial_reference_stays_in_caller_and_one_slot_forces_it(self):
        for workers, budget in ((1, 80), (8, 10)):
            with self.subTest(workers=workers):
                caller = threading.get_ident()
                stats = runtime.RuntimeStats()
                actual = list(runtime.bounded_map(lambda item: (item, threading.get_ident()),
                    range(3), workers=workers, memory_budget_bytes=budget,
                    estimated_task_bytes=10, stats=stats, phase="serial"))
                self.assertEqual(actual, [(0, caller), (1, caller), (2, caller)])
                self.assertEqual(stats.counts["serial.peak_active_workers"], 1)
                self.assertEqual(stats.counts["serial.worker_limit"], 1)

    def test_worker_failure_is_counted_and_not_returned_as_success(self):
        stats = runtime.RuntimeStats()
        def calculate(_):
            raise RuntimeError("injected")
        with self.assertRaisesRegex(RuntimeError, "injected"):
            list(runtime.bounded_map(calculate, [1], stats=stats, phase="failure"))
        self.assertEqual(stats.counts["failure.failed"], 1)
        self.assertNotIn("failure.completed", stats.counts)

    def test_invalid_telemetry_is_rejected_before_input_loading(self):
        touched = []
        def inputs():
            touched.append(True)
            yield 1
        for options in ({"stats": {}}, {"phase": ""}):
            with self.subTest(options=options), self.assertRaises((ValueError, TypeError)):
                list(runtime.bounded_map(lambda item: item, inputs(), **options))
        self.assertEqual(touched, [])

    def test_maximum_is_not_a_sum_and_rejects_ambiguous_values(self):
        stats = runtime.RuntimeStats()
        for value in (2, 1, 4, 3):
            stats.maximum("high", value)
        self.assertEqual(stats.counts["high"], 4)
        for value in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                stats.maximum("high", value)


if __name__ == "__main__":
    unittest.main()
