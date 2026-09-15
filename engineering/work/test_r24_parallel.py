"""Real spawn-pool checks on an integer DAG with explicit scheduler delays.

The delays represent scheduler work only; they are not scientific calculations
or whole-generator performance estimates. Run with python -m work.test_r24_parallel.
"""
from copy import deepcopy
import json
import os
from time import perf_counter, sleep
from types import SimpleNamespace
import unittest

from work.generator_runtime_r12.test_executor import fixture, s
from work.generator_upgrade_r24 import executor
from work.generator_upgrade_r24.parallel import PoolBackend

_TEMPLATE, _REGISTRY, _CALLS = fixture()
_PRODUCER = _REGISTRY['sum']['run']
MEASUREMENTS = {}


def timed_producer(context, inputs, incoming):
    sleep(inputs.get('scheduler_delay_s', 0))
    if inputs.get('fail'):
        raise ValueError('controlled spawned worker failure')
    return _PRODUCER(context, inputs, incoming)


def worker(job):
    started = perf_counter()
    result = timed_producer(job['context'], job['inputs'], job['incoming'])
    if job['inputs'].get('malformed'):
        return {'product': result, 'artifacts': []}
    return {'product': result, 'artifacts': {},
            'diagnostics': {'started_s': started, 'finished_s': perf_counter(),
                            'pid': os.getpid()}}


def _job(ident, **options):
    return {'stage_id': ident, 'producer_id': 'sum',
            'context': deepcopy(_TEMPLATE['context']),
            'inputs': {'tag': ident, 'base': 1, **options}, 'incoming': {}}


class RealPoolTests(unittest.TestCase):
    def test_serial_wave_ready_exact_results_and_dependency_overlap(self):
        recipe, registry, _ = fixture()
        for stage, delay in zip(recipe['stages'], (0.15, 0.8, 0.65, 0.1)):
            stage['inputs']['scheduler_delay_s'] = delay
        expected = s.run(recipe, registry)  # Untimed original integer producer.
        registry['sum']['run'] = timed_producer
        timings, pids = {}, {}
        for mode in ('serial', 'wave', 'ready'):
            events = {}

            def restore(ident, record):
                events[ident] = record['diagnostics']

            started = perf_counter()
            if mode == 'serial':
                result = executor.run(s, recipe, registry)
            else:
                with PoolBackend(worker, workers=2, cpu_count=2) as pool:
                    backend = SimpleNamespace(execute=pool.execute) if mode == 'wave' else pool
                    result = executor.run(s, recipe, registry, backend=backend, on_restore=restore)
                self.assertEqual(pool.capacity, 2)
                self.assertEqual(len(pool.observed_pids), 2)
                self.assertNotIn(os.getpid(), pool.observed_pids)
                self.assertEqual(pool.timings['peak_in_flight'], 2)
                self.assertEqual(len(pool.timings['jobs']), 4)
                pids[mode] = list(pool.observed_pids)
            timings[mode] = perf_counter() - started
            self.assertEqual(result, expected)
            self.assertEqual(s.encoded(result), s.encoded(expected))
            if mode == 'ready':
                self.assertLess(events['c']['started_s'], events['b']['finished_s'])
                self.assertGreaterEqual(events['c']['started_s'], events['a']['finished_s'])
                self.assertGreaterEqual(events['d']['started_s'], events['b']['finished_s'])
                self.assertGreaterEqual(events['d']['started_s'], events['c']['finished_s'])
            elif mode == 'wave':
                self.assertGreaterEqual(events['c']['started_s'], events['b']['finished_s'])
        MEASUREMENTS.update(scope='SYNTHETIC SCHEDULER TEST; integer DAG; includes spawn and shutdown',
            imposed_delay_seconds={'a':0.15, 'b':0.8, 'c':0.65, 'd':0.1},
            elapsed_seconds=timings, worker_pids=pids, exact_scientific_result=True,
            ready_saved_vs_wave_seconds=timings['wave']-timings['ready'],
            ready_saved_vs_wave_percent=(timings['wave']-timings['ready'])/timings['wave']*100,
            ready_saved_vs_serial_seconds=timings['serial']-timings['ready'],
            ready_saved_vs_serial_percent=(timings['serial']-timings['ready'])/timings['serial']*100)

    def test_capacity_duplicate_failure_and_exclusive_lock(self):
        with PoolBackend(worker, workers=2, cpu_count=2) as pool:
            self.assertTrue(pool._lock.acquire(blocking=False))
            try:
                with self.assertRaisesRegex(RuntimeError, 'exclusively'):
                    pool.submit([_job('a')])
            finally:
                pool._lock.release()
            self.assertEqual(pool._state, 'OPEN')
            with self.assertRaisesRegex(ValueError, 'capacity'):
                pool.submit([_job('a'), _job('b'), _job('c')])
            self.assertIsNone(pool._executor)
            self.assertEqual(pool._state, 'FAILED')
        with PoolBackend(worker, workers=1, cpu_count=1) as pool:
            pool.submit([_job('once')])
            self.assertEqual(set(pool.receive()), {'once'})
            with self.assertRaisesRegex(ValueError, 'unique'):
                pool.submit([_job('once')])
            self.assertIsNone(pool._executor)
            self.assertEqual(pool._pending, {})

    def test_real_worker_failure_and_malformed_record_close_pool(self):
        for options in ({'fail':True}, {'malformed':True}):
            with self.subTest(options=options):
                with PoolBackend(worker, workers=1, cpu_count=1) as pool:
                    pool.submit([_job('bad', **options)])
                    with self.assertRaises(ValueError):
                        pool.receive()
                    self.assertIsNone(pool._executor)
                    self.assertEqual(pool._state, 'FAILED')
                    self.assertEqual(pool._pending, {})
                    with self.assertRaises(RuntimeError):
                        pool.submit([_job('must_not_run')])


if __name__ == '__main__':
    started = perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RealPoolTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(json.dumps({'tests_run':result.testsRun, 'passed':result.wasSuccessful(),
                      'total_elapsed_seconds':perf_counter()-started, **MEASUREMENTS}))
    raise SystemExit(0 if result.wasSuccessful() else 1)
