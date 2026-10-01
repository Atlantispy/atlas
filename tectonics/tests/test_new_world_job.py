"""Isolated lifecycle tests: no physical fixtures, random generation or UI."""
from concurrent.futures import CancelledError
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import new_world_job as job


def identity(record):
    return hashlib.sha256(job._encoded(record)).hexdigest()


class FakeBackend:
    def __init__(self):
        self.version = 'original'
        self.preparations = self.owners = self.closed = 0
        self.checked = 0
        self.evaluated = []
        self.on_evaluate = None
        self.refuse_owner = False
        backend = self
        class PreparedEvolution:
            def __init__(self, initial, *, cancel=None):
                backend.owners += 1
                backend.check_initial(initial)
                self.initial, self.cancel = initial, cancel
            def __enter__(self):
                return self
            def __exit__(self, *_):
                backend.closed += 1
            def evaluate(self, elapsed_s):
                if self.cancel is not None and self.cancel.is_set():
                    raise CancelledError()
                backend.evaluated.append(elapsed_s)
                if backend.on_evaluate is not None:
                    backend.on_evaluate(elapsed_s)
                result = dict(initial_id=self.initial['initial_id'], elapsed_s=elapsed_s,
                              values=[value + elapsed_s for value in self.initial['sampled']])
                return dict(result, output_id=identity(result))
        self.PreparedEvolution = PreparedEvolution

    def source_binding(self):
        return dict(schema='fake-source', version=self.version)

    def check_initial(self, initial):
        self.checked += 1
        if self.refuse_owner:
            raise ValueError('missing native dependency at PRIVATE_PATH')
        record = {k:v for k,v in initial.items() if k != 'initial_id'}
        if initial.get('initial_id') != identity(record) or initial['source_binding'] != self.source_binding():
            raise ValueError('invalid saved initial')
        return initial

    def prepare(self, saved, options, *, cancel=None):
        self.preparations += 1
        initial = dict(schema='fake-initial', max_elapsed_s=10., source_binding=self.source_binding(),
                       sampled=[1.,2.,3.], input_sha256=hashlib.sha256(saved).hexdigest(), options=options)
        return dict(initial, initial_id=identity(initial))


class NewWorldJobTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'original.atlas'
        self.source.write_bytes(b'original immutable atlas fixture bytes')
        self.jobs_root = self.root / 'jobs'
        self.jobs_root.mkdir()
        self.ident = '4' * 32
        self.directory = self.jobs_root / self.ident
        self.backend = FakeBackend()
        self.enterContext(mock.patch.object(job, '_backend', return_value=self.backend))
        self.load = self.enterContext(mock.patch.object(job, '_load_project', side_effect=lambda p: Path(p).read_bytes()))

    def submit(self, **changes):
        options = dict(options={'cells_across':6}, schedule_s=[0.,1.,2.], max_wall_seconds=300.)
        options.update(changes)
        return job.submit(self.jobs_root, self.ident, self.source, **options)

    def control(self, name):
        return json.loads((self.directory / name).read_bytes())

    def test_fresh_frozen_input_exact_outputs_and_read_without_producers(self):
        answer = self.submit()['job']
        self.assertEqual(answer['state'], 'completed')
        self.assertEqual((answer['computed_outputs'], answer['restored_outputs']), (3,0))
        self.assertEqual(self.backend.evaluated, [0.,1.,2.])
        self.assertEqual(self.backend.preparations, 1)
        self.assertEqual(self.load.call_args.args[0], self.directory / 'input.atlas')
        self.assertEqual((self.directory / 'input.atlas').read_bytes(), self.source.read_bytes())
        self.assertEqual(set(answer['timings']), {'prepare_s','physics_s','store_s','restore_s','elapsed_s'})
        self.assertTrue(all(value >= 0 for value in answer['timings'].values()))
        prefix = self.control('prefix.json')
        self.assertEqual(len(prefix['outputs']), 3)
        for entry in prefix['outputs']:
            body = (self.directory / entry['file']).read_bytes()
            self.assertEqual(hashlib.sha256(body).hexdigest(), entry['sha256'])
            self.assertEqual(len(body), entry['size_bytes'])
        before = self.backend.checked
        with mock.patch.object(self.backend, 'prepare', side_effect=AssertionError('no sampling')), \
             mock.patch.object(self.backend, 'PreparedEvolution', side_effect=AssertionError('no geometry rebuild')), \
             mock.patch.object(self.backend.PreparedEvolution, 'evaluate', side_effect=AssertionError('no physics')):
            saved = job.read_output(self.jobs_root, self.ident)
        self.assertEqual(saved['values'], [3.,4.,5.])
        self.assertEqual(self.backend.checked, before + 1)
        self.assertEqual(self.backend.closed, self.backend.owners)

    def test_cli_selected_time_and_requested_schedule_without_new_physics(self):
        answer = self.submit()['job']
        self.assertEqual(answer['requested_elapsed_s'], [0.,1.,2.])
        before = list(self.backend.evaluated)
        for index in (0,1,2):
            response, code = job.response(['result','--root',str(self.jobs_root),
                '--job-id',self.ident,'--index',str(index)], io.BytesIO())
            self.assertEqual(code,0)
            self.assertEqual(response['result']['elapsed_s'],float(index))
        self.assertEqual(self.backend.evaluated,before)

    def test_cancelled_prefix_resume_only_computes_missing_and_matches_clean(self):
        def stop(elapsed):
            if elapsed == 1.:
                raise CancelledError()
        self.backend.on_evaluate = stop
        first = self.submit()['job']
        self.assertEqual(first['state'], 'cancelled')
        self.assertEqual(first['completed_outputs'], 1)
        retained = (self.directory / 'output-0000.json').read_bytes()
        self.assertFalse((self.directory / 'output-0001.json').exists())
        initial = (self.directory / 'initial.json').read_bytes()
        self.backend.on_evaluate = None
        self.backend.evaluated.clear()
        with mock.patch.object(self.backend, 'prepare', side_effect=AssertionError('no resampling')):
            second = job.resume(self.jobs_root, self.ident)['job']
        self.assertEqual(second['state'], 'completed')
        self.assertEqual((second['computed_outputs'],second['restored_outputs']), (2,1))
        self.assertEqual(self.backend.evaluated, [1.,2.])
        self.assertEqual((self.directory / 'output-0000.json').read_bytes(), retained)
        self.assertEqual((self.directory / 'initial.json').read_bytes(), initial)
        resumed = job.read_output(self.jobs_root, self.ident)
        self.ident = '5' * 32
        self.submit()
        self.assertEqual(job.read_output(self.jobs_root, self.ident), resumed)

    def test_completed_resume_validates_native_closure_without_any_evaluation(self):
        self.submit()
        self.backend.evaluated.clear()
        with mock.patch.object(self.backend, 'prepare', side_effect=AssertionError('no resampling')), \
             mock.patch.object(self.backend, 'PreparedEvolution', side_effect=AssertionError('no geometry rebuild')):
            again = job.resume(self.jobs_root, self.ident)['job']
        self.assertEqual((again['computed_outputs'],again['restored_outputs']), (0,3))
        self.assertEqual(self.backend.evaluated, [])
        self.backend.refuse_owner = True
        refused = job.resume(self.jobs_root, self.ident)['job']
        self.assertEqual(refused['state'], 'failed')
        self.assertEqual(self.backend.evaluated, [])

    def test_bounded_partial_checkpoint_resumes_without_resampling(self):
        first = self.submit(max_new_outputs=1)['job']
        self.assertEqual(first['state'], 'partial')
        self.assertEqual(first['completed_outputs'], 1)
        request = (self.directory / 'request.json').read_bytes()
        self.backend.evaluated.clear()
        with mock.patch.object(self.backend, 'prepare', side_effect=AssertionError('no resampling')):
            second = job.resume(self.jobs_root, self.ident, max_new_outputs=1)['job']
        self.assertEqual(second['state'], 'partial')
        self.assertEqual((second['computed_outputs'],second['restored_outputs']), (1,1))
        self.assertEqual(self.backend.evaluated, [1.])
        self.assertEqual((self.directory / 'request.json').read_bytes(), request)
        final = job.resume(self.jobs_root, self.ident)['job']
        self.assertEqual(final['state'], 'completed')
        self.assertEqual((final['computed_outputs'],final['restored_outputs']), (1,2))

    def test_cancel_file_stops_actual_cooperative_token_without_publishing_output(self):
        def request_cancel(elapsed):
            if elapsed == 1.:
                job.cancel(self.jobs_root, self.ident)
        self.backend.on_evaluate = request_cancel
        ticks = [0.]
        def clock():
            ticks[0] += .11
            return ticks[0]
        with mock.patch.object(job, 'time', SimpleNamespace(perf_counter=clock)):
            result = self.submit()['job']
        self.assertEqual(result['state'], 'cancelled')
        self.assertEqual(result['error']['code'], 'CANCELLED')
        self.assertEqual(result['completed_outputs'], 1)
        self.assertTrue((self.directory / 'cancel-0001.json').exists())
        self.assertFalse((self.directory / 'output-0001.json').exists())

    def test_backend_refusal_codes_are_meaningful_and_path_free(self):
        for code in ('EVOLUTION_REFUSED', 'NATIVE_INPUT_REFUSED', 'SOURCE_MISMATCH'):
            with self.subTest(code=code):
                answer = job._safe(job.ContractError(code, 'PRIVATE_PATH'))
                self.assertEqual(answer['code'], code)
                self.assertNotIn('PRIVATE_PATH', answer['message'])

    def test_idempotent_submit_conflicting_options_schedule_or_input_never_overwrites(self):
        self.submit()
        original = (self.directory / 'request.json').read_bytes()
        self.submit()
        self.assertEqual(self.backend.preparations, 1)
        for change in (dict(options={'cells_across':7}), dict(schedule_s=[0.,2.,3.]),
                       dict(max_wall_seconds=100.)):
            with self.subTest(change=change), self.assertRaises(job.jobs.JobError):
                self.submit(**change)
        self.source.write_bytes(b'changed source')
        with self.assertRaises(job.jobs.JobError):
            self.submit()
        self.assertEqual((self.directory / 'request.json').read_bytes(), original)
        self.assertEqual((self.directory / 'input.atlas').read_bytes(), b'original immutable atlas fixture bytes')

    def test_resume_source_input_and_output_corruption_refuse(self):
        self.submit()
        state = (self.directory / 'status.json').read_bytes()
        self.backend.version = 'changed'
        with self.assertRaises(job.jobs.JobError) as raised:
            job.resume(self.jobs_root, self.ident)
        self.assertEqual(raised.exception.code, 'SOURCE_MISMATCH')
        self.assertEqual((self.directory / 'status.json').read_bytes(), state)
        self.backend.version = 'original'
        source = self.directory / 'input.atlas'
        original = source.read_bytes()
        source.write_bytes(b'altered frozen input')
        result = job.resume(self.jobs_root, self.ident)['job']
        self.assertEqual(result['error']['code'], 'INPUT_CHANGED')
        source.write_bytes(original)
        output = self.directory / 'output-0001.json'
        output.write_bytes(b'{"partial":')
        self.assertEqual(job.resume(self.jobs_root, self.ident)['job']['state'], 'failed')
        self.assertEqual(output.read_bytes(), b'{"partial":')
        self.assertEqual(self.backend.preparations, 1)

    def test_failed_or_oversized_output_never_commits_partial_record(self):
        def fail(elapsed):
            if elapsed == 1.:
                raise OSError('PRIVATE_PATH')
        self.backend.on_evaluate = fail
        result = self.submit()['job']
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['completed_outputs'], 1)
        self.assertNotIn('PRIVATE_PATH', json.dumps(result))
        self.assertFalse((self.directory / 'output-0001.json').exists())
        self.backend.on_evaluate = None
        with mock.patch.object(self.backend.PreparedEvolution, 'evaluate',
                return_value={'output_id':'a'*64,'payload':'x' * job.MAX_RECORD}):
            result = job.resume(self.jobs_root, self.ident)['job']
        self.assertEqual(result['error']['code'], 'OUTPUT_LIMIT')
        self.assertEqual(len(self.control('prefix.json')['outputs']), 1)
        self.assertFalse((self.directory / 'output-0001.json').exists())

    def test_process_locks_and_per_attempt_cancellation_are_reused(self):
        self.submit()
        with job.jobs._lock(self.jobs_root / 'active.lock'):
            with self.assertRaises(job.jobs.JobError):
                job.resume(self.jobs_root, self.ident)
        state = self.control('status.json')
        state['state'] = 'running'
        job._control(self.directory / 'status.json', state)
        with job.jobs._lock(self.directory / 'worker.lock'):
            answer = job.cancel(self.jobs_root, self.ident)
            self.assertTrue(answer['job']['worker_active'])
            self.assertTrue((self.directory / 'cancel-0001.json').exists())
        self.assertEqual(job.status(self.jobs_root, self.ident)['job']['state'], 'interrupted')
        answer = job.resume(self.jobs_root, self.ident)['job']
        self.assertEqual(answer['attempt'], 2)
        self.assertEqual(answer['state'], 'completed')

    def test_preparation_cancellation_and_deadline_do_not_resample_on_resume(self):
        with mock.patch.object(self.backend, 'prepare', side_effect=CancelledError()):
            result = self.submit()['job']
        self.assertEqual(result['state'], 'cancelled')
        self.assertFalse((self.directory / 'initial.json').exists())
        with mock.patch.object(self.backend, 'prepare', side_effect=AssertionError('no resampling')):
            result = job.resume(self.jobs_root, self.ident)['job']
        self.assertEqual(result['error']['code'], 'INITIAL_INCOMPLETE')
        self.ident = '6' * 32
        counter = [0.]
        def clock():
            counter[0] += 1.
            return counter[0]
        with mock.patch.object(job, 'time', SimpleNamespace(perf_counter=clock)):
            result = self.submit(max_wall_seconds=.5)['job']
        self.assertEqual(result['error']['code'], 'TIME_LIMIT')
        self.assertEqual(result['computed_outputs'], 0)

    def test_invalid_schedule_request_paths_and_cli_errors_are_bounded(self):
        for schedule in ([1.,2.], [0.,0.], [0.,float('nan')], [0.,True], [], [0.] * 257):
            with self.subTest(schedule=schedule), self.assertRaises(job.jobs.JobError):
                self.submit(schedule_s=schedule)
        self.assertFalse(self.directory.exists())
        for body in (b'{', b'{"options":{},"options":{}}', b' '*65537):
            record, code = job.response(['submit','--root',str(self.jobs_root),'--job-id',self.ident,
                                        '--file',str(self.source)], io.BytesIO(body))
            self.assertEqual(code, 2)
            self.assertNotIn(str(self.root), json.dumps(record))
        with self.assertRaises((ValueError,OSError)):
            job.submit(self.jobs_root, self.ident, '../unsafe.atlas', options={}, schedule_s=[0.])
        self.assertEqual(self.backend.preparations, 0)
        result = self.submit(schedule_s=[0.,11.])['job']
        self.assertEqual(result['state'], 'failed')
        self.assertFalse((self.directory / 'initial.json').exists())


class SubmissionLimitTests(unittest.TestCase):
    """Staged submission, the Windows path budget and the prefix's own read limit (review infra-code-2/3/4)."""

    setUp, submit, control = NewWorldJobTests.setUp, NewWorldJobTests.submit, NewWorldJobTests.control
    MYR = 3.15576e13

    def test_a_transient_loader_failure_can_resume_before_preparation_started(self):
        self.load.side_effect = PermissionError('temporary input refusal')
        answer = self.submit()['job']
        self.assertEqual((answer['state'], answer['phase']), ('failed', 'submitted'))
        self.assertEqual(self.backend.preparations, 0)
        self.load.side_effect = lambda path: Path(path).read_bytes()
        resumed = job.resume(self.jobs_root, self.ident)['job']
        self.assertEqual((resumed['state'], resumed['attempt']), ('completed', 2))
        self.assertEqual(self.backend.preparations, 1)

    def test_hard_exit_after_claim_before_prepare_leaves_a_recoverable_first_attempt(self):
        # No exception cleanup: the child exits after its worker claim, while loading the frozen project.
        script = (
            "import os, sys; from pathlib import Path; "
            "sys.path.insert(0, sys.argv[1]); from test_new_world_job import FakeBackend, job; "
            "job._backend = FakeBackend; job._load_project = lambda path: os._exit(91); "
            "job.submit(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]), "
            "options={'cells_across':6}, schedule_s=[0.,1.,2.])"
        )
        child = subprocess.run([sys.executable, '-B', '-c', script, str(Path(__file__).parent),
                                str(self.jobs_root), self.ident, str(self.source)],
                               capture_output=True, text=True, timeout=30)
        self.assertEqual(child.returncode, 91, child.stderr)
        saved = self.control('status.json')
        self.assertEqual((saved['state'], saved['phase']), ('preparing', 'submitted'))
        self.assertFalse((self.directory / 'initial.json').exists())
        current = job.status(self.jobs_root, self.ident)['job']
        self.assertEqual((current['state'], current['worker_active']), ('interrupted', False))
        self.assertEqual(self.control('status.json'), saved)   # inspection does not rewrite the recovery marker
        resumed = job.resume(self.jobs_root, self.ident)['job']
        self.assertEqual((resumed['state'], resumed['attempt']), ('completed', 2))
        self.assertEqual(self.backend.preparations, 1)

    def test_preparation_boundary_is_durable_and_never_resamples_after_failure(self):
        def interrupted(*args, **kwargs):
            self.assertNotIn('phase', self.control('status.json'))
            raise KeyboardInterrupt()
        with mock.patch.object(self.backend, 'prepare', side_effect=interrupted) as prepare:
            answer = self.submit()['job']
            self.assertEqual(answer['state'], 'interrupted')
            self.assertNotIn('phase', answer)
            resumed = job.resume(self.jobs_root, self.ident)['job']
            self.assertEqual(resumed['error']['code'], 'INITIAL_INCOMPLETE')
            self.assertEqual(prepare.call_count, 1)

    def test_extreme_integer_schedule_and_wall_limit_refuse_before_publication(self):
        for changed in ({'schedule_s': [0, 10 ** 400]}, {'max_wall_seconds': 10 ** 400}):
            with self.subTest(changed=next(iter(changed))):
                with self.assertRaises(job.jobs.JobError) as raised:
                    self.submit(**changed)
                self.assertEqual(raised.exception.code, 'INVALID_REQUEST')
                body = dict(options={}, schedule_s=[0., 1.], max_wall_seconds=300.)
                body.update(changed)
                answer, code = job.response(['submit', '--root', str(self.jobs_root), '--job-id', self.ident,
                                            '--file', str(self.source)], io.BytesIO(json.dumps(body).encode()))
                self.assertEqual((code, answer['error']['code']), (2, 'INVALID_REQUEST'))
        self.assertEqual(list(self.jobs_root.iterdir()), [])
        self.assertEqual(self.backend.preparations, 0)

    def root_of(self, length):
        """A new jobs root whose absolute path is exactly ``length`` characters."""
        root = self.root / (str(length) + 'q' * (length - len(str(self.root)) - 1 - len(str(length))))
        self.assertEqual(len(str(root)), length)
        root.mkdir()
        return root

    def test_every_output_of_a_full_long_float_schedule_stays_readable_and_resumable(self):
        def prepare(saved, options, *, cancel=None):
            # Myr-scale horizon and outputs of tens of kilobytes, so each size_bytes has five digits.
            initial = dict(schema='fake-initial', max_elapsed_s=1e16, source_binding=self.backend.source_binding(),
                           sampled=[1.] * 600, input_sha256=hashlib.sha256(saved).hexdigest(), options=options)
            return dict(initial, initial_id=identity(initial))
        schedule = [0.] + [index * self.MYR / 7 for index in range(1, job.MAX_OUTPUTS)]
        with mock.patch.object(self.backend, 'prepare', side_effect=prepare):
            answer = self.submit(schedule_s=schedule)['job']
        self.assertEqual((answer['state'], answer['completed_outputs']), ('completed', 256))
        body = (self.directory / 'prefix.json').read_bytes()
        self.assertLessEqual(len(body), 65536)
        self.assertEqual(body, job._encoded(json.loads(body), 65535) + b'\n')
        resumed = job.resume(self.jobs_root, self.ident)['job']
        self.assertEqual((resumed['state'], resumed['restored_outputs'], resumed['computed_outputs']),
                         ('completed', 256, 0))
        self.assertEqual(job.read_output(self.jobs_root, self.ident, 0)['elapsed_s'], 0.)
        self.assertEqual(job.read_output(self.jobs_root, self.ident)['elapsed_s'], schedule[-1])

    def test_a_schedule_whose_complete_prefix_cannot_fit_is_refused_at_submit(self):
        schedule = [0] + [10 ** 70 + index for index in range(1, job.MAX_OUTPUTS)]
        with self.assertRaises(job.jobs.JobError) as raised:
            self.submit(schedule_s=schedule)
        self.assertEqual(raised.exception.code, 'OUTPUT_LIMIT')
        self.assertEqual(list(self.jobs_root.iterdir()), [])
        self.assertEqual(self.backend.preparations, 0)

    def test_a_failure_while_staging_leaves_no_job_and_the_id_stays_usable(self):
        read = job._read
        def copied(path, maximum):
            body = read(path, maximum)
            return b'changed while copying' if Path(path).name == 'input.atlas' else body
        with mock.patch.object(job, '_read', side_effect=copied):
            with self.assertRaises(job.jobs.JobError) as raised:
                self.submit()
        self.assertEqual(raised.exception.code, 'INPUT_CHANGED')
        self.assertEqual(sorted(path.name for path in self.jobs_root.iterdir()), ['active.lock'])
        self.assertEqual(self.backend.preparations, 0)
        self.assertEqual(self.submit()['job']['state'], 'completed')
        self.assertEqual(job.status(self.jobs_root, self.ident)['job']['state'], 'completed')

    def test_a_poll_at_publication_cannot_wedge_a_new_world_job(self):
        # A result/status poll takes worker.lock the moment the job directory appears, however it appears.
        seen, held, release = [], threading.Event(), threading.Event()
        def poll():
            with job.jobs._lock(self.directory / 'worker.lock'):
                try:
                    seen.append(job._request(self.directory)[0]['job_id'] == self.ident)
                except Exception as exc:
                    seen.append(type(exc).__name__)
                held.set()
                release.wait(5)
        def appeared(path):
            if Path(path) == self.directory and not held.is_set():
                poller = threading.Thread(target=poll, daemon=True)
                poller.start()
                self.addCleanup(poller.join, 5)
                self.addCleanup(release.set)         # runs first: never leave the lock held after a failure
                self.assertTrue(held.wait(5))
                threading.Timer(.2, release.set).start()
        mkdir, rename = Path.mkdir, os.rename
        def made(path, *args, **kwargs):
            mkdir(path, *args, **kwargs)
            appeared(path)
        def renamed(source, target, *args, **kwargs):
            rename(source, target, *args, **kwargs)
            appeared(target)
        with mock.patch.object(Path, 'mkdir', made), mock.patch.object(os, 'rename', renamed):
            answer = self.submit()['job']
        self.assertEqual(seen, [True])
        self.assertEqual(answer['state'], 'completed')
        self.assertEqual(job.status(self.jobs_root, self.ident)['job']['state'], 'completed')

    def test_a_cancel_before_the_worker_starts_leaves_a_job_that_resume_starts(self):
        # Verifier findings: a cancel landing between publication and the worker's claim either vanished (lock free)
        # or, when a poll held the lock, stopped the job before preparation and left an ID that could never resume.
        for held_by_poll in (False, True):
            with self.subTest(held_by_poll=held_by_poll):
                self.ident = ('8' if held_by_poll else '7') * 32
                self.directory, seen, rename = self.jobs_root / self.ident, [], os.rename
                before = self.backend.preparations
                def published(source, target, *args, **kwargs):
                    rename(source, target, *args, **kwargs)
                    if Path(target) != self.directory or seen:
                        return
                    seen.append(job.status(self.jobs_root, self.ident)['job'])
                    with contextlib.ExitStack() as poll:
                        if held_by_poll:
                            poll.enter_context(job.jobs._lock(self.directory / 'worker.lock'))
                        seen.append(job.cancel(self.jobs_root, self.ident)['job'])
                with mock.patch.object(os, 'rename', published):
                    answer = self.submit()['job']
                waiting, cancelled = seen
                self.assertEqual((waiting['state'], waiting['phase'], waiting['worker_active']),
                                 ('preparing', 'submitted', False))
                self.assertEqual(cancelled['state'], 'preparing')
                self.assertTrue((self.directory / 'cancel-0001.json').is_file())
                self.assertEqual((answer['state'], answer['error']['code'], answer['phase']),
                                 ('cancelled', 'CANCELLED', 'submitted'))
                self.assertEqual(self.backend.preparations, before)
                self.assertFalse((self.directory / 'initial.json').exists())
                resumed = job.resume(self.jobs_root, self.ident)['job']
                self.assertEqual((resumed['state'], resumed['attempt'], resumed['computed_outputs']), ('completed', 2, 3))
                self.assertNotIn('phase', resumed)
                self.assertEqual(self.backend.preparations, before + 1)

    def test_a_lock_held_past_the_claim_leaves_a_new_world_job_that_resume_starts(self):
        # Verifier finding: the new-world counterpart of the W12 test. A refused first claim left 'interrupted' with
        # nothing prepared, and every resume refused INITIAL_INCOMPLETE.
        holder, rename = contextlib.ExitStack(), os.rename
        self.addCleanup(holder.close)
        def published(source, target, *args, **kwargs):
            rename(source, target, *args, **kwargs)
            if Path(target) == self.directory:
                holder.enter_context(job.jobs._lock(self.directory / 'worker.lock'))
        with mock.patch.object(os, 'rename', published), mock.patch.object(job.jobs.time, 'sleep') as sleep:
            with self.assertRaises(job.jobs.JobError) as raised:
                self.submit()
        self.assertEqual(raised.exception.code, 'RUN_BUSY')
        self.assertEqual(sleep.call_count, job.jobs.CLAIM_RETRIES - 1)
        holder.close()
        self.assertEqual(self.backend.preparations, 0)
        current = job.status(self.jobs_root, self.ident)['job']
        self.assertEqual((current['state'], current['phase'], current['attempt']), ('interrupted', 'submitted', 1))
        self.assertEqual(self.submit()['job']['state'], 'interrupted')      # the same submission, not a second one
        resumed = job.resume(self.jobs_root, self.ident)['job']
        self.assertEqual((resumed['state'], resumed['attempt'], resumed['computed_outputs']), ('completed', 2, 3))
        self.assertEqual(self.backend.preparations, 1)
        self.assertEqual(job.read_output(self.jobs_root, self.ident)['elapsed_s'], 2.)

    def test_path_budget_counts_the_longest_cancellation_temporary(self):
        # '.cancel-1000.json-<32 hex>' is 50 characters; with the separator it sets the 259-unit maximum.
        for extra, refused in ((0, False), (1, True)):
            with self.subTest(refused=refused):
                directory = self.jobs_root / ('d' * (259 - len(str(self.jobs_root)) - 1 - 33 - 51 + extra)) / self.ident
                self.assertEqual(len(str(directory)) + 51, 259 + extra)
                with mock.patch.object(job.os, 'name', 'nt'):
                    if refused:
                        with self.assertRaises(job.jobs.JobError) as raised:
                            job._path_budget(directory)
                        self.assertEqual(raised.exception.code, 'INVALID_PATH')
                    else:
                        job._path_budget(directory)

    @unittest.skipUnless(os.name == 'nt', 'the path budget applies to ordinary Windows paths')
    def test_a_windows_root_too_long_for_job_files_is_refused_before_anything_exists(self):
        root = self.root_of(195)
        for attempt in (1, 2):
            with self.subTest(attempt=attempt):
                with self.assertRaises(job.jobs.JobError) as raised:
                    job.submit(root, self.ident, self.source, options={}, schedule_s=[0., 1.], max_wall_seconds=300.)
                self.assertEqual(raised.exception.code, 'INVALID_PATH')
        self.assertEqual(list(root.iterdir()), [])
        self.assertEqual(self.backend.preparations, 0)

    @unittest.skipUnless(os.name == 'nt', 'the path budget applies to ordinary Windows paths')
    def test_cancel_works_under_every_admitted_windows_root_length(self):
        ticks = [0.]
        def clock():
            ticks[0] += .11
            return ticks[0]
        for length in (175, 176, 177, 178):
            with self.subTest(length=length):
                root, requested = self.root_of(length), []
                def request_cancel(elapsed, root=root, requested=requested):
                    if elapsed == 1.:
                        try:
                            requested.append(job.cancel(root, self.ident)['job']['worker_active'])
                        except Exception as exc:
                            requested.append(job._safe(exc)['code'])
                self.backend.on_evaluate = request_cancel
                with mock.patch.object(job, 'time', SimpleNamespace(perf_counter=clock)):
                    try:
                        result = job.submit(root, self.ident, self.source, options={}, schedule_s=[0., 1., 2.],
                                            max_wall_seconds=300.)['job']
                    except job.jobs.JobError as exc:
                        # 1 + 32 + 1 + 50 characters below the root: 176 is the first refused length.
                        self.assertEqual((exc.code, length >= 176), ('INVALID_PATH', True))
                        self.assertEqual(list(root.iterdir()), [])
                        continue
                self.assertLess(length, 176)
                self.assertEqual(requested, [True])
                self.assertEqual((result['state'], result['error']['code']), ('cancelled', 'CANCELLED'))
                self.assertTrue((root / self.ident / 'cancel-0001.json').is_file())


if __name__ == '__main__':
    unittest.main()
