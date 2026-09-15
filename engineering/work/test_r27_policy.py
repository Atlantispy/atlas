"""Fast forecast-policy checks; synthetic clocks do not measure speedups."""
from collections import deque
from copy import deepcopy
import unittest

from work.generator_upgrade_r27.policy import ForecastBackend


def job(ident, value=7):
    return {'stage_id': ident, 'producer_id': 'synthetic', 'context': {},
            'inputs': {'value': value}, 'incoming': {}}


def record(item):
    return {'product': {'value': item['inputs']['value']}, 'artifacts': {}, 'diagnostics': {}}


class FakePool:
    def __init__(self, capacity=2, failure=None):
        self.capacity, self.failure = capacity, failure
        self.entered, self.closed = 0, 0
        self.pending, self.submitted = deque(), []
        self.observed_pids, self.timings = (), {'synthetic': True}

    def __enter__(self):
        self.entered += 1
        if self.failure == 'enter':
            raise ValueError('synthetic pool entry failure')
        return self

    def submit(self, jobs):
        self.submitted.extend(item['stage_id'] for item in jobs)
        self.pending.extend(deepcopy(jobs))
        if self.failure == 'submit':
            raise ValueError('synthetic pool submit failure')

    def receive(self):
        if self.failure == 'receive':
            raise ValueError('synthetic worker failure')
        if self.failure == 'inventory':
            return {'unexpected': record(job('unexpected'))}
        item = self.pending.popleft()
        return {item['stage_id']: record(item)}

    def close(self):
        self.closed += 1
        self.pending.clear()


class ForecastTests(unittest.TestCase):
    def build(self, expected=None, *, capacity=2, failure=None, threshold=120):
        calls, pool = [], FakePool(capacity, failure)

        def local(item):
            calls.append(item['stage_id'])
            return record(item)

        backend = ForecastBackend(local, pool, expected_seconds=expected,
                                  parallel_threshold_s=threshold, clock=lambda: 0.0)
        return backend, pool, calls

    def test_first_two_different_jobs_promote_without_local_work(self):
        backend, pool, calls = self.build(120.01)
        original = job('a')
        backend.submit([original, job('b', 99)])
        original['inputs']['value'] = -1
        self.assertEqual(pool.entered, 0)  # Queueing cannot launch work.
        self.assertEqual(calls, [])
        self.assertEqual(backend.receive(), {'a': record(job('a'))})
        self.assertEqual(backend.receive(), {'b': record(job('b', 99))})
        self.assertEqual(pool.entered, 1)
        self.assertEqual(pool.submitted, ['a', 'b'])
        self.assertEqual(calls, [])
        self.assertTrue(backend.promoted)
        self.assertEqual(backend.effective_workers, 2)
        self.assertEqual(backend.selection['sample_runs_required'], 0)
        self.assertFalse(backend.selection['estimate_is_measured'])
        self.assertNotIn('predicted_saving_s', backend.selection)
        backend.close()

    def test_threshold_short_and_unknown_are_serial_without_learning(self):
        for expected in (None, 0, 1, 119.99, 120):
            with self.subTest(expected=expected):
                backend, pool, calls = self.build(expected)
                values = [job(str(i)) for i in range(6)]
                self.assertEqual(backend.execute(values),
                                 {item['stage_id']: record(item) for item in values})
                self.assertEqual(calls, [str(i) for i in range(6)])
                self.assertEqual(pool.entered, 0)
                self.assertFalse(backend.promoted)
                self.assertEqual(backend.effective_workers, 1)
                self.assertFalse(backend.selection['observed_timings_used_for_selection'])
                backend.close()

    def test_capacity_one_and_single_ready_job_never_promote(self):
        for capacity in (1, 2):
            backend, pool, calls = self.build(3600, capacity=capacity)
            backend.submit([job('a')])
            self.assertEqual(backend.receive(), {'a': record(job('a'))})
            self.assertEqual(calls, ['a'])
            self.assertEqual(pool.entered, 0)
            expected_reason = ('CANDIDATE_CAPACITY_ONE' if capacity == 1
                               else 'FEWER_THAN_TWO_READY_JOBS')
            self.assertEqual(backend.selection['reason'], expected_reason)
            backend.close()

    def test_empty_cached_run_never_starts_pool(self):
        backend, pool, calls = self.build(3600)
        self.assertEqual(backend.execute([]), {})
        self.assertEqual(backend.selection['reason'], 'NO_UNCACHED_READY_JOBS')
        backend.close()
        self.assertEqual(pool.entered, 0)
        self.assertEqual(calls, [])

    def test_failures_close_without_local_replay(self):
        for failure in ('enter', 'submit', 'receive', 'inventory'):
            with self.subTest(failure=failure):
                backend, pool, calls = self.build(121, failure=failure)
                backend.submit([job('a'), job('b')])
                with self.assertRaises(ValueError):
                    backend.receive()
                self.assertEqual(calls, [])
                self.assertGreater(pool.closed, 0)
                with self.assertRaises(RuntimeError):
                    backend.receive()

    def test_wave_order_capacity_and_custom_threshold(self):
        backend, pool, calls = self.build(10.01, threshold=10)
        values = [job(ident, index) for index, ident in enumerate(('z', 'y', 'x', 'w', 'v'))]
        result = backend.execute(values)
        self.assertEqual(list(result), ['z', 'y', 'x', 'w', 'v'])
        self.assertEqual(result, {item['stage_id']: record(item) for item in values})
        self.assertEqual(pool.submitted, ['z', 'y', 'x', 'w', 'v'])
        self.assertEqual(calls, [])
        self.assertEqual(pool.entered, 1)
        self.assertEqual(backend.timings['peak_pending'], 2)
        self.assertEqual(backend.selection['parallel_threshold_s'], 10)
        backend.close()

    def test_invalid_estimates_and_malformed_jobs_do_not_execute(self):
        for invalid in (-1, True, '120', float('nan'), float('inf'), 10 ** 400):
            with self.subTest(expected=repr(invalid)):
                with self.assertRaises(ValueError):
                    self.build(invalid)
        for invalid in (None, 0, -1, True, '120', float('nan'), float('inf'), 10 ** 400):
            with self.subTest(threshold=repr(invalid)):
                with self.assertRaises(ValueError):
                    self.build(121, threshold=invalid)
        backend, pool, calls = self.build(121)
        malformed = job('bad', float('nan'))
        with self.assertRaises(ValueError):
            backend.execute([job('good'), malformed])
        self.assertEqual(calls, [])
        self.assertEqual(pool.entered, 0)
        self.assertGreater(pool.closed, 0)


if __name__ == '__main__':
    unittest.main()
