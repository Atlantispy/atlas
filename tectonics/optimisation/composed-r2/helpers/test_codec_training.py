"""Owned training contract fixtures; real native roundtrip belongs to build owner."""
from concurrent.futures import CancelledError
from contextlib import contextmanager
import gc
from hashlib import sha256
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[1] / 'runtime-integration-r1/runtime-src'
sys.path.insert(0, str(RUNTIME))

from atlas_tectonics.resources import WorkBudget
import codec_training as T


@contextmanager
def fixture_lock(path, expected):
    if sha256(path.read_bytes()).hexdigest() != expected:
        raise T.TrainingRefused('trainer executable identity differs')
    yield


class FakeProcess:
    def __init__(self, code):
        self.code, self.closed = code, False

    def poll(self):
        return self.code

    def wait(self, seconds):
        return self.code is not None

    def close(self):
        self.closed = True


class FakeJob:
    def __init__(self, mode='ok', cancel=None):
        self.mode, self.cancel = mode, cancel
        self.closed = self.stopped = self.launched = False
        self.process = None

    def verify_limits(self):
        return dict(process_memory_limit_bytes=T.NATIVE_LIMIT if self.mode != 'weak-limit' else 0,
                    job_memory_limit_bytes=T.NATIVE_LIMIT, kill_on_close=True,
                    breakaway=False, suspended_launch_owned=True)

    def launch(self, command, env, cwd):
        self.launched = True
        source = Path(command[1]).read_bytes()
        magic, count, capacity, total = struct.unpack_from('<4sIII', source)
        assert magic == b'WPT1' and count == 16 and total == 16*1024
        assert len(source) == 16 + 4*count + total
        if self.mode == 'ok':
            Path(command[2]).write_bytes(b'\x37\xa4\x30\xec\x01\0\0\0' + b'x'*56)
        elif self.mode == 'oversized':
            Path(command[2]).write_bytes(b'x'*(capacity+1))
        elif self.mode == 'invalid':
            Path(command[2]).write_bytes(b'x'*64)
        elif self.mode == 'cancel':
            self.cancel.set()
        code = None if self.mode in ('timeout', 'cancel') else 7 if self.mode == 'crash' else 0
        self.process = FakeProcess(code)
        return self.process

    def metrics(self):
        return dict(peak_job_memory_used_bytes=12 << 20, peak_process_memory_used_bytes=11 << 20)

    def stop(self):
        self.stopped = True
        if self.process is not None:
            self.process.code = 2
        return {'remaining': [], 'action_errors': []}

    def close(self):
        self.closed = True


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.exe = self.root / 'trainer-fixture.exe'
        self.exe.write_bytes(b'not executable; injected test job only')
        self.budget = WorkBudget(256 << 20)
        self.samples = [bytes([index])*1024 for index in range(16)]

    def tearDown(self):
        gc.collect()
        self.temp.cleanup()

    def run_training(self, job, **kwargs):
        options = dict(expected_executable_sha256=sha256(self.exe.read_bytes()).hexdigest(),
            samples=self.samples, array_class='metadata', dtype='|u1', shuffle='none',
            source_identity='a'*64, budget=self.budget, work_root=self.root,
            _job_factory=lambda: job, _lock_factory=fixture_lock)
        options.update(kwargs)
        return T.train_dictionary(self.exe, **options)

    def test_success_returns_funded_owner_then_releases(self):
        job = FakeJob()
        result = self.run_training(job)
        self.assertEqual(result.metadata['sha256'], sha256(result.data).hexdigest())
        self.assertEqual(result.metadata['training_sample_sha256'], [sha256(x).hexdigest() for x in self.samples])
        self.assertEqual(result.metadata['metrics']['peak_job_memory_used_bytes'], 12 << 20)
        self.assertFalse(result.metadata['production_enabled'])
        self.assertTrue(job.closed and job.process.closed)
        self.assertFalse(job.stopped)
        self.assertGreater(self.budget.statistics()['reserved_bytes'], 0)
        self.assertLess(self.budget.statistics()['reserved_bytes'], 1 << 20)
        self.assertEqual([p.name for p in self.root.iterdir()], ['trainer-fixture.exe'])
        result.close()
        self.assertEqual(self.budget.statistics()['reserved_bytes'], 0)
        with self.assertRaises(T.TrainingRefused):
            _ = result.data

    def test_limits_verified_before_any_launch(self):
        job = FakeJob('weak-limit')
        with self.assertRaisesRegex(T.TrainingRefused, 'limits differ'):
            self.run_training(job)
        self.assertFalse(job.launched)
        self.assertTrue(job.closed)

    def test_failed_native_paths_kill_join_close_without_dictionary(self):
        for mode in ('missing', 'oversized', 'invalid', 'crash', 'timeout'):
            job = FakeJob(mode)
            with self.subTest(mode=mode), self.assertRaises(T.TrainingRefused):
                self.run_training(job, timeout_seconds=.005)
            self.assertTrue(job.closed and job.stopped and job.process.closed)
            self.assertEqual([p.name for p in self.root.iterdir()], ['trainer-fixture.exe'])
            gc.collect()

    def test_cancel_before_launch_and_during_wait(self):
        cancel = threading.Event()
        cancel.set()
        job = FakeJob()
        with self.assertRaises(CancelledError):
            self.run_training(job, cancel=cancel)
        self.assertFalse(job.launched)
        cancel.clear()
        job = FakeJob('cancel', cancel)
        with self.assertRaises(CancelledError):
            self.run_training(job, cancel=cancel)
        self.assertTrue(job.stopped and job.closed and job.process.closed)

    def test_corpus_and_capacity_bounds_refuse_before_launch(self):
        for kwargs in ({'samples': [b'a']*257}, {'samples': [b'a'*65537]},
                       {'samples': [b'a'*65536]*17}, {'capacity': 65537},
                       {'timeout_seconds': 31}, {'source_identity': 'not-a-sha'}):
            job = FakeJob()
            with self.subTest(kwargs=tuple(kwargs)), self.assertRaises(T.TrainingRefused):
                self.run_training(job, **kwargs)
            self.assertFalse(job.launched)

    def test_transform_is_bounded_and_hash_bound(self):
        job = FakeJob()
        with self.run_training(job, transform_for_training=lambda raw, dtype, shuffle: raw[::-1]) as result:
            self.assertEqual(result.metadata['transformed_sample_sha256'],
                             [sha256(x[::-1]).hexdigest() for x in self.samples])
        job = FakeJob()
        with self.assertRaisesRegex(T.TrainingRefused, 'transform exceeds'):
            self.run_training(job, transform_for_training=lambda *args: b'x'*65537)
        self.assertFalse(job.launched)

    def test_wrong_executable_hash_refuses_without_launch(self):
        job = FakeJob()
        with self.assertRaisesRegex(T.TrainingRefused, 'identity differs'):
            self.run_training(job, expected_executable_sha256='0'*64)
        self.assertFalse(job.launched)

    def test_separately_retained_failed_traceback_keeps_python_work_funded(self):
        traceback = None
        try:
            self.run_training(FakeJob('invalid'))
        except T.TrainingRefused as error:
            traceback = error.__traceback__
        self.assertIsNotNone(traceback)
        gc.collect()
        self.assertGreaterEqual(self.budget.statistics()['reserved_bytes'], T.NATIVE_LIMIT+T.PYTHON_ALLOWANCE)
        traceback = None
        gc.collect()
        self.assertEqual(self.budget.statistics()['reserved_bytes'], 0)


if __name__ == '__main__':
    unittest.main()
