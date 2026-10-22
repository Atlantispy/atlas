"""Only the new notification/guard boundary; no scientific runtime or live message."""
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OverrunGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load(HERE / 'overrun.py', 'overrun_guard_fixture')
        cls.dispatcher = load(HERE / 'run_plan17.py', 'overrun_dispatch_fixture')
        cls.owned = cls.dispatcher.load_supervisor()

    def test_pid_union_counts_notice_descendants_once_and_refuses_partial_sample(self):
        class Members(ctypes.Structure):
            _fields_ = [('assigned', ctypes.c_uint32), ('listed', ctypes.c_uint32),
                        ('ids', ctypes.c_size_t * 256)]

        class Kernel:
            incomplete = False

            def QueryInformationJobObject(self, handle, kind, pointer, size, returned):
                members = pointer._obj
                ids = [10, 11] if handle == 1 else [11, 12]
                members.assigned = len(ids) + int(self.incomplete)
                members.listed = len(ids)
                for index, pid in enumerate(ids):
                    members.ids[index] = pid
                return True

        kernel = Kernel()
        calls = []

        def process(pid):
            calls.append(pid)
            return SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=pid))

        fixture = SimpleNamespace(JobPids=Members, psutil=SimpleNamespace(
            Process=process, NoSuchProcess=ProcessLookupError,
            virtual_memory=lambda: SimpleNamespace(available=2 << 30)))
        event = self.module.GuardedEvent.__new__(self.module.GuardedEvent)
        event.proof = SimpleNamespace(k=kernel, job=1)
        event.notice = SimpleNamespace(k=kernel, job=2)
        event.owned = fixture
        self.assertEqual(event.sample(None), (sum({os.getpid(), 10, 11, 12}), 2 << 30))
        self.assertEqual(sorted(calls), sorted({os.getpid(), 10, 11, 12}))
        kernel.incomplete = True
        with self.assertRaisesRegex(ValueError, 'incomplete combined'):
            event.sample(None)

    def test_blocked_notice_launch_cannot_stall_pressure_guard_or_escape_cleanup(self):
        directory = HERE / 'blocked-notice-fixture-r1'
        directory.mkdir()
        entered, release = threading.Event(), threading.Event()

        class FakeJob:
            def __init__(self, notice=False):
                self.notice, self.active, self.terminated = notice, 0 if notice else 1, False
                self.identity = {'assigned_before_resume': True}

            def start(self, *args):
                entered.set()
                if not release.wait(3):
                    raise TimeoutError('fixture release did not arrive')
                self.active = 1  # Plant the cancellation/start race.

            def accounting(self):
                return {'active': self.active}

            def snapshot(self):
                return dict(job=self.accounting(), exit_code=143 if self.terminated else None)

            def terminate_owned(self):
                self.terminated, self.active = True, 0
                release.set()
                return 'retained-fixture-handle'

            def exit_code(self):
                return 143 if self.terminated else None

            def close(self):
                if self.active:
                    raise RuntimeError('active fixture closed')

        proof, notice = FakeJob(), FakeJob(True)
        event = self.module.GuardedEvent(proof, self.owned,
            dict(result_directory=str(directory), projected_minutes=32), {}, job_factory=lambda: notice)
        try:
            event.trigger()
            self.assertTrue(entered.wait(2))
            event.trigger()
            samples = []

            def pressure(unused):
                samples.append(time.monotonic())
                return ((13 << 30) if len(samples) == 2 else 100), 2 << 30

            result = self.owned.supervise(event, sample=pressure, sleep=event.sleep)
            self.assertEqual(len(samples), 2)
            self.assertEqual(result['finality'], 'COMPLETE')
            self.assertTrue(result['errors'])
            self.assertTrue(proof.terminated)
            self.assertTrue(notice.terminated)
            self.assertTrue(event.launch_done.is_set())
            self.assertEqual(event.snapshot()['job']['active'], 0)
            self.assertEqual(event.outcome()['delivery']['status'], 'failed_or_unconfirmed')
        finally:
            release.set()
            if event.thread is not None:
                event.thread.join(3)
            event.close()

    def test_native_worker_delivery_is_contained_guarded_and_kept_distinct_from_proof(self):
        directory = HERE / 'native-notice-fixture-r1'
        directory.mkdir()
        queue = directory / 'queue'
        owner = '11111111-1111-4111-8111-111111111111'
        coordinator = '22222222-2222-4222-8222-222222222222'
        queue.write_text("import sys\nprint('DISPOSABLE CLI', sys.argv[2], flush=True)\n"
                         "raise SystemExit(9 if sys.argv[2].startswith('2222') else 0)\n")
        config = dict(event_id='native-overrun-fixture', owner=owner, coordinator=coordinator,
            phase='controls-fixture', manifest_sha256='b' * 64,
            manifest_path=str(HERE / 'REQUEST-r4.json'), result_directory=str(directory),
            codex=sys.executable, cwd=str(directory), projected_minutes=.0001)
        env = self.dispatcher.clean_environment()
        proof = self.owned.backend()()
        event = self.module.GuardedEvent(proof, self.owned, config, env)
        observations = []
        try:
            with (directory / 'proof.stdout').open('xb') as stdout, (directory / 'proof.stderr').open('xb') as stderr:
                proof.start([sys.executable, '-B', '-I', '-c', 'import time; time.sleep(.6)'],
                            str(directory), env, stdout, stderr)

                def sample(group):
                    observations.append(time.monotonic())
                    return group.sample(group)

                result = self.owned.supervise(event, sample=sample, sleep=event.sleep)
            outcome = event.outcome()
            evidence = dict(proof=result, overrun=outcome, sample_count=len(observations),
                largest_sample_interval_seconds=max((b - a for a, b in zip(
                    observations, observations[1:], strict=False)), default=0),
                planted_failure='second fake CLI exits9; no live Codex queue or model message')
            (directory / 'fixture-result.json').write_text(json.dumps(evidence, indent=2))
            self.assertEqual(result['errors'], [])
            self.assertEqual(result['finality'], 'COMPLETE')
            self.assertEqual(result['exit_code'], 0)
            self.assertTrue(outcome['triggered'])
            self.assertTrue(outcome['ownership']['assigned_before_resume'])
            self.assertEqual(outcome['worker_finality']['active'], 0)
            self.assertEqual(outcome['delivery']['status'], 'failed_or_unconfirmed')
            notices = outcome['delivery']['notifications']
            self.assertEqual(notices[owner]['status'], 'queued')
            self.assertEqual(notices[coordinator]['status'], 'failed_or_unconfirmed')
            self.assertEqual(len(notices), 2)
            self.assertGreaterEqual(len(observations), 3)
        finally:
            event.close()
            proof.close()


if __name__ == '__main__':
    unittest.main()
