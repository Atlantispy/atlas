"""Isolated lifecycle tests: no physical fixtures, random generation or UI."""
from concurrent.futures import CancelledError
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
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


if __name__ == '__main__':
    unittest.main()
