"""Managed job lifecycle with fake workers; no scientific imports or simulation.

SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import queue
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch


TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import tectonics_job as jobs


class ManagedJobTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='atlas-job-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job_id = 'a' * 32
        self.sources = patch.object(jobs, '_sources', return_value={'worker.py': 'b' * 64})
        self.runtime = patch.object(jobs, '_runtime', return_value='c' * 64)
        self.sources.start()
        self.runtime.start()
        self.addCleanup(self.sources.stop)
        self.addCleanup(self.runtime.stop)

    def assert_job_error(self, code, operation, *args, **kwargs):
        with self.assertRaises(jobs.JobError) as caught:
            operation(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_windows_cache_path_budget_refuses_before_native_work(self):
        with patch.object(jobs.os, 'name', 'nt'):
            jobs._path_budget(self.root / self.job_id)
            self.assert_job_error('INVALID_PATH', jobs._path_budget,
                                  self.root / ('nested' * 30) / self.job_id)

    def complete(self, directory, *, cells, resume, cancelled, progress):
        directory.mkdir(exist_ok=True)
        self.assertFalse(cancelled())
        for index in range(1, 4):
            report = 'run-%05d.json' % index
            (directory / report).write_text(json.dumps({'fixture': index}), encoding='utf-8')
            progress(dict(completed_outputs=index, report=report, product_id='product-%d' % index))
        return dict(status='completed', completed_outputs=3, report='run-00003.json',
                    product_id='product-3', statistics={'fixture_outputs': 3})

    def submit(self, **kwargs):
        answer = jobs.run(self.root, self.job_id, executor=self.complete, **kwargs)
        self.assertEqual(answer['job']['state'], 'completed', answer)
        return answer

    def cli(self, action, *, job_id=None, extra=()):
        output = io.StringIO()
        arguments = ['tectonics_job.py', action, '--root', str(self.root),
                     '--job-id', self.job_id if job_id is None else job_id, *extra]
        with patch.object(sys, 'argv', arguments), redirect_stdout(output):
            code = jobs.main()
        return code, json.loads(output.getvalue())

    def test_fresh_submission_is_idempotent_and_conflicting_inputs_refuse(self):
        executor = Mock(side_effect=self.complete)
        first = jobs.run(self.root, self.job_id, cells=5, executor=executor)
        directory = self.root / self.job_id
        request = (directory / 'request.json').read_bytes()
        second = jobs.run(self.root, self.job_id, cells=5, executor=executor)
        resumed = jobs.run(self.root, self.job_id, cells=5, resume=True, executor=executor)
        self.assertEqual(first, second)
        self.assertEqual(first, resumed)
        self.assertEqual(first['job']['state'], 'completed')
        self.assertEqual(first['job']['statistics'], {'fixture_outputs': 3})
        self.assertEqual(first['job']['capabilities'], dict(cancel=False, resume=False, inspect=True))
        executor.assert_called_once()
        self.assertEqual(executor.call_args.kwargs['cells'], 5)
        self.assertFalse(executor.call_args.kwargs['resume'])
        for resume in (False, True):
            self.assert_job_error('REQUEST_CONFLICT', jobs.run, self.root, self.job_id,
                                  cells=6, resume=resume, executor=executor)
        self.assertEqual(request, (directory / 'request.json').read_bytes())

    def test_active_root_and_job_locks_prevent_concurrent_work_and_inspection(self):
        def active(directory, **arguments):
            current = jobs.status(self.root, self.job_id)['job']
            self.assertTrue(current['worker_active'])
            self.assertEqual(current['state'], 'preparing')
            self.assertTrue(current['capabilities']['cancel'])
            self.assertFalse(current['capabilities']['resume'])
            duplicate = jobs.run(self.root, self.job_id, executor=Mock())
            self.assertTrue(duplicate['job']['worker_active'])
            self.assert_job_error('RUN_BUSY', jobs.run, self.root, 'd' * 32, executor=Mock())
            self.assertFalse((self.root / ('d' * 32)).exists())
            self.assert_job_error('RUN_BUSY', jobs.run, self.root, self.job_id, resume=True)
            self.assert_job_error('RUN_BUSY', jobs.result, self.root, self.job_id)
            return dict(status='cancelled', completed_outputs=0, report=None)

        answer = jobs.run(self.root, self.job_id, executor=active)
        self.assertEqual(answer['job']['state'], 'cancelled', answer)
        with jobs._lock(self.root / self.job_id / 'worker.lock'):
            self.assert_job_error('RUN_BUSY', jobs.run, self.root, self.job_id,
                                  resume=True, executor=Mock())
        self.assertFalse(jobs.status(self.root, self.job_id)['job']['worker_active'])

    def test_killed_process_releases_lock_and_stale_running_status_is_interrupted(self):
        self.submit()
        directory = self.root / self.job_id
        state = jobs._state(directory)
        state.update(state='running', phase='fixture')
        jobs._atomic(directory / 'status.json', state)
        script = (
            'import pathlib, sys\n'
            'sys.path.insert(0, sys.argv[1])\n'
            'import tectonics_job as jobs\n'
            'with jobs._lock(pathlib.Path(sys.argv[2])):\n'
            '    print("ready", flush=True)\n'
            '    sys.stdin.buffer.read(1)\n'
        )
        process = subprocess.Popen(
            [sys.executable, '-I', '-B', '-c', script, str(TOOLS), str(directory / 'worker.lock')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
        try:
            self.assertEqual(ready.get(timeout=10).strip(), 'ready')
            active = jobs.status(self.root, self.job_id)['job']
            self.assertEqual(active['state'], 'running')
            self.assertTrue(active['worker_active'])
            process.kill()
            process.communicate(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
        interrupted = jobs.status(self.root, self.job_id)['job']
        self.assertEqual(interrupted['state'], 'interrupted')
        self.assertEqual(interrupted['phase'], 'worker-exited')
        self.assertFalse(interrupted['worker_active'])
        self.assertTrue(interrupted['capabilities']['resume'])
        self.assertEqual(interrupted['report'], 'run-00003.json')
        self.assertEqual(jobs._state(directory)['state'], 'running')

    def test_cancellation_is_per_attempt_and_resume_keeps_saved_outputs(self):
        def first(directory, *, cells, resume, cancelled, progress):
            directory.mkdir()
            (directory / 'run-00001.json').write_bytes(b'{"retained":true}\n')
            progress(dict(completed_outputs=1, report='run-00001.json', product_id='first'))
            requested = jobs.cancel(self.root, self.job_id)['job']
            self.assertEqual(requested['state'], 'cancelling')
            self.assertTrue(requested['cancellation_requested'])
            self.assertTrue(cancelled())
            return dict(status='cancelled', completed_outputs=1, report=None, product_id=None)

        first_result = jobs.run(self.root, self.job_id, executor=first)['job']
        directory = self.root / self.job_id
        request = (directory / 'request.json').read_bytes()
        report = (directory / 'run/run-00001.json').read_bytes()
        self.assertEqual(first_result['state'], 'cancelled')
        self.assertEqual(first_result['report'], 'run-00001.json')
        self.assertEqual(first_result['product_id'], 'first')
        self.assertTrue(first_result['capabilities']['inspect'])

        def resumed(run_directory, *, cells, resume, cancelled, progress):
            self.assertTrue(resume)
            self.assertFalse(cancelled())
            progress(dict(phase='verifying', report=None, product_id=None))
            current = jobs.status(self.root, self.job_id)['job']
            self.assertEqual(current['attempt'], 2)
            self.assertEqual(current['completed_outputs'], 1)
            self.assertEqual(current['report'], 'run-00001.json')
            self.assertEqual(current['product_id'], 'first')
            (run_directory / 'run-00003.json').write_text('{}', encoding='utf-8')
            return dict(status='completed', completed_outputs=3, report='run-00003.json', product_id='last')

        final = jobs.run(self.root, self.job_id, resume=True, executor=resumed)['job']
        self.assertEqual(final['state'], 'completed')
        self.assertEqual(final['attempt'], 2)
        self.assertEqual(request, (directory / 'request.json').read_bytes())
        self.assertEqual(report, (directory / 'run/run-00001.json').read_bytes())
        self.assertTrue((directory / 'cancel-0001.json').is_file())
        self.assertFalse((directory / 'cancel-0002.json').exists())

    def test_deadline_cancels_and_repeated_native_polls_throttle_file_reads(self):
        clock = [100.0]
        with patch.object(jobs.time, 'perf_counter', side_effect=lambda: clock[0]), \
                patch.object(jobs, '_cancelled', wraps=jobs._cancelled) as check:
            def worker(directory, *, cells, resume, cancelled, progress):
                self.assertFalse(cancelled())
                self.assertFalse(cancelled())
                self.assertEqual(check.call_count, 1)
                clock[0] += .11
                self.assertFalse(cancelled())
                self.assertEqual(check.call_count, 2)
                clock[0] = 100.0 + jobs.MAX_SECONDS
                self.assertTrue(cancelled())
                self.assertEqual(check.call_count, 2)
                return dict(status='cancelled', completed_outputs=0, report=None)

            result = jobs.run(self.root, self.job_id, executor=worker)['job']
        self.assertEqual(result['state'], 'cancelled')
        self.assertEqual(result['phase'], 'time-limit')
        self.assertEqual(result['seconds'], jobs.MAX_SECONDS)

    def test_resume_refuses_source_or_runtime_drift_without_touching_saved_state(self):
        self.submit()
        directory = self.root / self.job_id
        before = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
        for target, value in (('_sources', {'changed.py': 'd' * 64}), ('_runtime', 'e' * 64)):
            with self.subTest(target=target), patch.object(jobs, target, return_value=value):
                executor = Mock()
                self.assert_job_error('SOURCE_MISMATCH', jobs.run, self.root, self.job_id,
                                      resume=True, executor=executor)
                executor.assert_not_called()
        after = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
        self.assertEqual(before, after)

    def test_missing_corrupt_and_invalid_saved_state_fail_closed(self):
        code, result = self.cli('status')
        self.assertEqual(code, 2)
        self.assertEqual(result['error']['code'], 'MISSING_INPUT')
        self.submit()
        directory = self.root / self.job_id
        for name, body, expected in (
                ('request.json', '{}', 'INVALID_STATE'),
                ('request.json', '{"schema":1,"schema":2}', 'INVALID_REPORT'),
                ('status.json', '{', 'WORKER_FAILED'),
                ('status.json', '{"seconds":NaN}', 'INVALID_REPORT'),
                ('status.json', '{}', 'INVALID_STATE')):
            with self.subTest(name=name, body=body):
                source = directory / name
                original = source.read_bytes()
                source.write_text(body, encoding='utf-8')
                try:
                    code, result = self.cli('status')
                    self.assertEqual(code, 2)
                    self.assertEqual(result['status'], 'error')
                    self.assertEqual(result['error']['code'], expected)
                    self.assertNotIn(str(self.root), json.dumps(result))
                finally:
                    source.write_bytes(original)

    def test_result_uses_only_saved_bounded_report_and_never_arbitrary_path(self):
        self.submit()
        directory = self.root / self.job_id
        with patch.object(jobs.reader, 'response', return_value={'status': 'ok', 'result': 'fixture'}) as read:
            self.assertEqual(jobs.result(self.root, self.job_id)['result'], 'fixture')
            read.assert_called_once_with(directory / 'run', 'run-00003.json')
            read.reset_mock()
            state = jobs._state(directory)
            state['report'] = '../private.json'
            jobs._atomic(directory / 'status.json', state)
            self.assert_job_error('INVALID_STATE', jobs.result, self.root, self.job_id)
            read.assert_not_called()
            state['report'] = None
            jobs._atomic(directory / 'status.json', state)
            self.assert_job_error('NO_RESULT', jobs.result, self.root, self.job_id)
            read.assert_not_called()

    def test_invalid_ids_and_cells_never_create_jobs_or_call_executor(self):
        executor = Mock()
        for job_id in ('../escape', 'A' * 32, 'a' * 31, 'a' * 33, 1, None):
            with self.subTest(job_id=job_id):
                self.assert_job_error('INVALID_REQUEST', jobs.run, self.root, job_id, executor=executor)
        for cells in (True, False, 4, 65, 8.0, '8'):
            with self.subTest(cells=cells):
                self.assert_job_error('INVALID_REQUEST', jobs.run, self.root, self.job_id,
                                      cells=cells, executor=executor)
        executor.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_symlink_and_reparse_metadata_refuse_before_job_creation(self):
        original_lstat = Path.lstat
        # Synthetic lstat metadata exercises both platform guards without
        # claiming real Windows symlink/junction creation privileges.
        for linked_mode, attributes in ((stat.S_IFLNK, 0), (None, 0x400)):
            with self.subTest(mode=linked_mode, attributes=attributes):
                def linked_lstat(path):
                    info = original_lstat(path)
                    if path == self.root:
                        return type('LinkedStat', (), {
                            'st_mode': info.st_mode if linked_mode is None else linked_mode,
                            'st_file_attributes': attributes})()
                    return info

                with patch.object(Path, 'lstat', linked_lstat):
                    with self.assertRaises(jobs.reader.ReadError) as caught:
                        jobs.run(self.root, self.job_id, executor=Mock())
                self.assertEqual(caught.exception.code, 'INVALID_PATH')
                self.assertEqual(list(self.root.iterdir()), [])

    def test_worker_exceptions_and_invalid_progress_keep_fixed_safe_errors(self):
        secret = str(self.root / 'private-source.json')
        for index, exception, expected_state, expected_code in (
                (1, RuntimeError(secret), 'failed', 'WORKER_FAILED'),
                (2, ImportError(secret), 'failed', 'DEPENDENCY_UNAVAILABLE'),
                (3, KeyboardInterrupt(secret), 'interrupted', 'WORKER_FAILED')):
            with self.subTest(exception=type(exception).__name__):
                result = jobs.run(self.root, '%032x' % index,
                                  executor=Mock(side_effect=exception))['job']
                self.assertEqual(result['state'], expected_state)
                self.assertEqual(result['error']['code'], expected_code)
                self.assertNotIn(secret, json.dumps(result))
                self.assertFalse(result['capabilities']['inspect'])
                self.assertTrue(result['capabilities']['resume'])
        for index, update in enumerate(([], {'completed_outputs': True}, {'report': '../private.json'}), 4):
            with self.subTest(update=update):
                def bad_progress(directory, *, cells, resume, cancelled, progress):
                    progress(dict(completed_outputs=1, report='run-00001.json', product_id='retained'))
                    progress(update)

                result = jobs.run(self.root, '%032x' % index, executor=bad_progress)['job']
                self.assertEqual(result['state'], 'failed')
                self.assertEqual(result['error']['code'], 'INVALID_STATE')
                self.assertEqual(result['report'], 'run-00001.json')
                self.assertEqual(result['completed_outputs'], 1)

    def test_cli_reports_fixed_validation_errors_and_no_paths(self):
        code, result = self.cli('status', job_id='../private')
        self.assertEqual(code, 2)
        self.assertEqual(result, dict(schema=jobs.SCHEMA, status='error', error=dict(
            code='INVALID_REQUEST', message='A lowercase 32-character hexadecimal job ID is required.')))
        code, result = self.cli('status', extra=('--cells', '8'))
        self.assertEqual(code, 2)
        self.assertEqual(result['error'], dict(code='INVALID_REQUEST',
            message='Cells are accepted only for a run or exact resume.'))
        code, result = self.cli('result')
        self.assertEqual(code, 2)
        self.assertEqual(result['error'], dict(code='MISSING_INPUT',
            message='A required local job file or directory is missing.'))
        self.assertNotIn(str(self.root), json.dumps(result))


if __name__ == '__main__':
    unittest.main()
