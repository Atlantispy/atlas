"""Bounded cost-policy checks; artificial clocks never claim measured speedup."""
from collections import deque
from copy import deepcopy
import multiprocessing
import os
import unittest

from work.generator_upgrade_r25.adaptive import AdaptiveBackend
from work.generator_upgrade_r24.parallel import PoolBackend

_BARRIER = None


def job(ident, value=7, **extra):
    return {'stage_id': ident, 'producer_id': 'synthetic', 'context': {},
            'inputs': {'value': value, **extra}, 'incoming': {}}


def record(item):
    return {'product': {'value': item['inputs']['value']}, 'artifacts': {}, 'diagnostics': {}}


def initialise(barrier):
    global _BARRIER
    _BARRIER = barrier


def process_worker(item):
    _BARRIER.wait(timeout=10)
    return record(item)


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class FakePool:
    def __init__(self, capacity=2, *, failure=None):
        self.capacity, self.failure = capacity, failure
        self.entered, self.closed = 0, 0
        self.submitted, self.pending = [], deque()
        self.observed_pids = (7001, 7002)
        self.timings = {'synthetic': True}

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
            raise ValueError('synthetic pool worker failure')
        if self.failure == 'inventory':
            return {'unexpected': record(job('unexpected'))}
        item = self.pending.popleft()
        return {item['stage_id']: record(item)}

    def close(self):
        self.closed += 1
        self.pending.clear()


class AdaptiveTests(unittest.TestCase):
    def build(self, costs, *, pool=None, budget=1.5):
        clock, calls, remaining = Clock(), [], iter(costs)
        pool = FakePool() if pool is None else pool

        def local(item):
            calls.append(item['stage_id'])
            clock.value += next(remaining)
            return record(item)

        return AdaptiveBackend(local, pool, startup_budget_s=budget, clock=clock), pool, calls

    def sample_two(self, backend, value=7, prefix='s'):
        for index in range(2):
            backend.submit([job(prefix + str(index), value)])
            self.assertEqual(set(backend.receive()), {prefix + str(index)})

    def test_submit_only_queues_detaches_and_receive_runs_one_small_job(self):
        backend, pool, calls = self.build([0.01] * 4)
        first = job('a')
        backend.submit([first, job('b')])
        first['inputs']['value'] = 999
        self.assertEqual(calls, [])
        self.assertEqual(pool.entered, 0)
        self.assertEqual(backend.receive()['a']['product']['value'], 7)
        self.assertEqual(calls, ['a'])
        backend.submit([job('c')])
        self.assertEqual(set(backend.receive()), {'b'})
        backend.submit([job('d')])
        self.assertEqual(set(backend.receive()), {'c'})
        self.assertEqual(backend.selection['reason'], 'OBSERVED_SAVING_DOES_NOT_EXCEED_BUDGET')
        backend.receive()
        self.assertFalse(backend.promoted)
        self.assertEqual(backend.effective_workers, 1)
        self.assertEqual(backend.observed_pids, ())
        self.assertEqual(calls, ['a', 'b', 'c', 'd'])
        backend.close()

    def test_costly_exact_repeats_promote_once_and_never_replay_samples(self):
        backend, pool, calls = self.build([3.0, 2.0])
        self.sample_two(backend)
        backend.submit([job('c'), job('d')])
        self.assertEqual(pool.entered, 0)
        self.assertEqual(set(backend.receive()), {'c'})
        self.assertTrue(backend.promoted)
        self.assertEqual(pool.submitted, ['c', 'd'])
        self.assertEqual(calls, ['s0', 's1'])
        self.assertEqual(backend.selection['predicted_saving_s'], 2.0)
        backend.receive()
        backend.submit([job('e')])
        backend.receive()
        self.assertEqual(pool.entered, 1)
        self.assertEqual(pool.submitted, ['c', 'd', 'e'])
        self.assertEqual(backend.effective_workers, 2)
        backend.close()

    def test_changed_inputs_are_unknown_until_their_own_two_samples(self):
        backend, pool, calls = self.build([4.0, 3.0, 3.0, 3.0, 3.0])
        self.sample_two(backend)
        backend.submit([job('known'), job('different', value=8)])
        backend.receive()
        self.assertEqual(backend.selection['reason'], 'FEWER_THAN_TWO_COMPARABLE_SAMPLES')
        self.assertEqual(pool.entered, 0)
        backend.receive()
        backend.submit([job('second_different', value=8)])
        backend.receive()
        backend.submit([job('known_final'), job('different_final', value=8)])
        backend.receive()
        self.assertTrue(backend.promoted)  # Each distinct exact key has its own samples.
        self.assertEqual(calls, ['s0', 's1', 'known', 'different', 'second_different'])
        backend.close()

    def test_cheap_inner_return_single_slot_and_budget_prevent_promotion(self):
        for costs, capacity, budget in (([5.0, 0.01, 0.01, 0.01], 2, 1.5),
                                        ([5.0] * 4, 1, 0.0), ([5.0] * 4, 2, 10.0)):
            backend, pool, calls = self.build(costs, pool=FakePool(capacity), budget=budget)
            self.sample_two(backend)
            if capacity == 1:
                backend.submit([job('c')])
                backend.receive()
            else:
                backend.submit([job('c'), job('d')])
                backend.receive()
                backend.receive()
            self.assertFalse(backend.promoted)
            self.assertEqual(pool.entered, 0)
            backend.close()
        for invalid in (-1, True, float('nan'), float('inf'), '1'):
            with self.assertRaises(ValueError):
                AdaptiveBackend(record, FakePool(), startup_budget_s=invalid)
        for capacity in (0, True, 3):
            with self.assertRaises(ValueError):
                AdaptiveBackend(record, FakePool(capacity))

    def test_failures_close_without_replay_and_invalid_wave_prevents_work(self):
        for failure in ('enter', 'submit', 'receive', 'inventory'):
            backend, pool, calls = self.build([3.0, 3.0], pool=FakePool(failure=failure))
            self.sample_two(backend)
            backend.submit([job('c'), job('d')])
            with self.assertRaises(ValueError):
                backend.receive()
            self.assertEqual(calls, ['s0', 's1'])
            self.assertGreater(pool.closed, 0)
            with self.assertRaises(RuntimeError):
                backend.receive()
        backend, pool, calls = self.build([3.0])
        malformed = job('invalid')
        malformed['inputs']['value'] = float('nan')
        with self.assertRaises(ValueError):
            backend.execute([job('valid'), malformed])
        self.assertEqual(calls, [])
        self.assertEqual(pool.entered, 0)
        self.assertGreater(pool.closed, 0)
        backend, pool, calls = self.build([1.0])
        with self.assertRaises(ValueError):
            backend.submit([job('same'), job('same')])
        self.assertEqual(calls, [])

    def test_wave_input_order_bounded_profiles_and_selection_copies(self):
        backend, pool, calls = self.build([3.0, 3.0])
        result = backend.execute([job(ident) for ident in ('z', 'y', 'x', 'w', 'v')])
        self.assertEqual(list(result), ['z', 'y', 'x', 'w', 'v'])
        self.assertEqual(calls, ['z', 'y'])
        self.assertEqual(pool.submitted, ['x', 'w', 'v'])
        copy = backend.selection
        copy['local_executed_stage_ids'].clear()
        self.assertEqual(backend.selection['local_executed_stage_ids'], ['z', 'y'])
        backend.close()
        backend, pool, calls = self.build([0.0] * 130)
        for index in range(130):
            backend.submit([job(str(index), value=index)])
            backend.receive()
        self.assertEqual(backend.selection['profile_count'], 128)
        self.assertFalse(backend.promoted)
        backend.close()

    def test_real_process_promotion_returns_exact_records(self):
        barrier = multiprocessing.get_context('spawn').Barrier(2)
        pool = PoolBackend(process_worker, initializer=initialise, initargs=(barrier,),
                           workers=2, cpu_count=2)
        backend, _, calls = self.build([3.0, 3.0], pool=pool)
        try:
            self.sample_two(backend)
            backend.submit([job('c'), job('d')])
            result = {}
            while len(result) < 2:
                result.update(backend.receive())
            self.assertEqual(result, {'c': record(job('c')), 'd': record(job('d'))})
            self.assertTrue(backend.promoted)
            self.assertEqual(len(backend.observed_pids), 2)
            self.assertNotIn(os.getpid(), backend.observed_pids)
            self.assertEqual(calls, ['s0', 's1'])
        finally:
            backend.close()


if __name__ == '__main__':
    unittest.main()
