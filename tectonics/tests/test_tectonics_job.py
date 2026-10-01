"""Managed job lifecycle with fake workers; no scientific imports or simulation.

SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import ExitStack, redirect_stdout
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


class StagedSubmissionTests(unittest.TestCase):
    """A new job becomes visible complete, and a poll landing at that moment cannot wedge its ID (review infra-code-2).
    Control files stay canonical and within their own read limit (infra-code-3)."""

    setUp, assert_job_error = ManagedJobTests.setUp, ManagedJobTests.assert_job_error
    complete, submit = ManagedJobTests.complete, ManagedJobTests.submit

    def racing(self, poll):
        """Replace jobs._lock so ``poll(path)`` first takes the job's worker lock the moment the submitter asks."""
        real, polled = jobs._lock, []

        def lock(path):
            if path.name == 'worker.lock' and not polled:
                polled.append(path)
                poll(path)
            return real(path)
        return patch.object(jobs, '_lock', side_effect=lock)

    def test_a_poll_at_publication_cannot_wedge_the_job_id(self):
        directory, seen, held, release = self.root / self.job_id, [], threading.Event(), threading.Event()

        def status_poll():
            # What `tectonics_job.py status` does for an inactive job, holding the lock a little longer.
            with jobs._lock(directory / 'worker.lock'):
                try:
                    seen.append(jobs._state(directory)['state'])
                except Exception as exc:
                    seen.append(type(exc).__name__)
                held.set()
                release.wait(5)

        def start(_path):
            poller = threading.Thread(target=status_poll, daemon=True)
            poller.start()
            self.addCleanup(poller.join, 5)
            self.addCleanup(release.set)             # runs first: never leave the lock held after a failure
            self.assertTrue(held.wait(5))
            threading.Timer(.2, release.set).start()

        with self.racing(start):
            first = jobs.run(self.root, self.job_id, executor=self.complete)['job']
        self.assertEqual(seen, ['preparing'])        # the poll found a complete job, never half of one
        self.assertEqual(first['state'], 'completed')
        self.assertEqual(jobs.run(self.root, self.job_id, executor=Mock())['job']['state'], 'completed')
        self.assertEqual(jobs.status(self.root, self.job_id)['job']['state'], 'completed')
        self.assertEqual(jobs.run(self.root, self.job_id, resume=True, executor=Mock())['job']['state'], 'completed')

    def test_a_lock_held_past_the_claim_refuses_busy_but_leaves_a_resumable_job(self):
        holder = ExitStack()
        self.addCleanup(holder.close)
        executor = Mock()
        with self.racing(lambda path: holder.enter_context(jobs._lock(path))), \
                patch.object(jobs.time, 'sleep') as sleep:
            self.assert_job_error('RUN_BUSY', jobs.run, self.root, self.job_id, executor=executor)
        executor.assert_not_called()
        holder.close()
        current = jobs.status(self.root, self.job_id)['job']
        # The refused submitter records the job as interrupted and never started (not a worker that exited).
        self.assertEqual((current['state'], current['phase'], current['attempt']), ('interrupted', 'submitted', 1))
        self.assertTrue(current['capabilities']['resume'])
        resumed = jobs.run(self.root, self.job_id, resume=True, executor=self.complete)['job']
        self.assertEqual((resumed['state'], resumed['attempt']), ('completed', 2))
        self.assertEqual(sleep.call_count, jobs.CLAIM_RETRIES - 1)

    def test_status_and_cancel_before_the_claim_see_a_submitted_job_and_the_cancel_is_kept(self):
        # Verifier finding: between publication and the worker's claim, polls saw 'interrupted' (resumable) and a
        # cancel found the lock free and was dropped. The job is reported as submitted and the request is kept.
        directory, seen, rename = self.root / self.job_id, [], jobs.os.rename

        def published(source, target, *args, **kwargs):
            rename(source, target, *args, **kwargs)
            if Path(target) == directory and not seen:
                seen.append(jobs.status(self.root, self.job_id)['job'])
                seen.append(jobs.cancel(self.root, self.job_id)['job'])

        def honours_cancel(run, *, cells, resume, cancelled, progress):
            run.mkdir(exist_ok=True)
            return dict(status='cancelled', completed_outputs=0) if cancelled() else self.complete(
                run, cells=cells, resume=resume, cancelled=cancelled, progress=progress)

        with patch.object(jobs.os, 'rename', side_effect=published):
            answer = jobs.run(self.root, self.job_id, executor=honours_cancel)['job']
        waiting, cancelling = seen
        self.assertEqual((waiting['state'], waiting['phase'], waiting['worker_active']), ('preparing', 'submitted', False))
        self.assertEqual(waiting['capabilities'], dict(cancel=True, resume=False, inspect=False))
        self.assertEqual((cancelling['state'], cancelling['cancellation_requested']), ('cancelling', True))
        self.assertEqual((answer['state'], answer['attempt'], answer['phase']), ('cancelled', 1, 'cancelled'))
        resumed = jobs.run(self.root, self.job_id, resume=True, executor=self.complete)['job']
        self.assertEqual((resumed['state'], resumed['attempt']), ('completed', 2))

    def test_abandoned_submitted_status_exposes_resume_without_rewriting_it(self):
        # Exact on-disk state after a hard exit between directory publication and worker claim.
        directory = self.root / self.job_id
        directory.mkdir()
        jobs._atomic(directory / 'request.json', dict(schema=jobs.REQUEST_SCHEMA, job_id=self.job_id,
            case_id=jobs.CASE, cells=5, sources=jobs._sources(), execution_id=jobs._runtime()))
        saved = dict(jobs._new_state(self.job_id, 1), phase=jobs.SUBMITTED)
        jobs._atomic(directory / 'status.json', saved)
        current = jobs.status(self.root, self.job_id)['job']
        self.assertEqual((current['state'], current['phase'], current['worker_active']),
                         ('interrupted', 'submitted', False))
        self.assertTrue(current['capabilities']['resume'])
        self.assertFalse(current['capabilities']['cancel'])
        self.assertEqual(jobs._state(directory), saved)
        resumed = jobs.run(self.root, self.job_id, resume=True, executor=self.complete)['job']
        self.assertEqual((resumed['state'], resumed['attempt']), ('completed', 2))

    def test_a_poll_that_locks_a_new_lock_file_before_its_byte_is_written_cannot_fail_submission(self):
        # Verifier finding: Windows byte locks are mandatory, so a poll locking a just-created, still empty
        # worker.lock made the creator's one-byte write raise a raw PermissionError out of run().
        real_open, fired, holder = Path.open, [], ExitStack()
        self.addCleanup(holder.close)

        def racing_open(path, mode='r', *args, **kwargs):
            stream = real_open(path, mode, *args, **kwargs)
            if mode == 'xb' and path.name.endswith('.lock') and path.name != 'active.lock' and not fired:
                fired.append(path)
                holder.enter_context(jobs._lock(path))      # a second handle locks byte 0 before the flush
            return stream

        lock = self.root / 'probe.lock'
        with patch.object(Path, 'open', racing_open):
            self.assert_job_error('RUN_BUSY', lambda: jobs._lock(lock).__enter__())
        holder.close()
        with jobs._lock(lock):
            self.assertLessEqual(lock.stat().st_size, 1)
        fired.clear()
        held, release = threading.Event(), threading.Event()

        def poll(path):
            with jobs._lock(path):
                held.set()
                release.wait(5)

        def threaded_open(path, mode='r', *args, **kwargs):
            stream = real_open(path, mode, *args, **kwargs)
            if mode == 'xb' and path.name == 'worker.lock' and not fired:
                fired.append(path)
                poller = threading.Thread(target=poll, args=(path,), daemon=True)
                poller.start()
                self.addCleanup(poller.join, 5)
                self.addCleanup(release.set)
                self.assertTrue(held.wait(5))
                threading.Timer(.1, release.set).start()
            return stream

        with patch.object(Path, 'open', threaded_open):
            answer = jobs.run(self.root, self.job_id, executor=self.complete)['job']
        self.assertEqual((answer['state'], answer['attempt']), ('completed', 1))
        self.assertEqual([path.name for path in fired], ['worker.lock'])

    def test_a_failure_while_staging_leaves_no_job_and_no_staging_folder(self):
        real_fsync, calls, executor = jobs.os.fsync, [], Mock()

        def fsync(descriptor):
            calls.append(descriptor)
            if len(calls) == 2:          # the second control file of the new job
                raise OSError(5, 'injected write failure')
            return real_fsync(descriptor)

        with patch.object(jobs.os, 'fsync', side_effect=fsync):
            with self.assertRaises(OSError):
                jobs.run(self.root, self.job_id, executor=executor)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['active.lock'])
        with patch.object(jobs.reader, 'WINDOWS', True), patch.object(jobs.time, 'sleep'), \
                patch.object(jobs.os, 'rename', side_effect=PermissionError(13, 'Access is denied')) as rename:
            with self.assertRaises(PermissionError):
                jobs.run(self.root, self.job_id, executor=executor)
        self.assertEqual(rename.call_count, jobs.reader.REPLACE_RETRIES)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['active.lock'])
        executor.assert_not_called()
        # A hard crash can leave a dot-named staging folder: never read, never counted, never deleted automatically.
        leftover = jobs._staging(self.root / self.job_id, '0' * jobs.STAGING_HEX)
        leftover.mkdir()
        (leftover / 'request.json').write_bytes(b'{}')
        with patch.object(jobs, 'MAX_JOBS', 1):
            self.submit()
        self.assertEqual((leftover / 'request.json').read_bytes(), b'{}')

    def test_control_files_are_compact_canonical_and_refused_before_exceeding_the_read_limit(self):
        path = self.root / 'status.json'
        jobs._atomic(path, {'b': [1.5, 'x', None], 'a': 'é'})
        self.assertEqual(path.read_bytes(), b'{"a":"\\u00e9","b":[1.5,"x",null]}\n')
        largest = {'x': 'y' * (65536 - len(b'{"x":""}\n'))}
        jobs._atomic(path, largest)
        self.assertEqual(path.stat().st_size, 65536)
        self.assertEqual(jobs._json(path), largest)
        with patch.object(Path, 'open', side_effect=AssertionError('no temporary may be created')):
            error = self.assert_job_error('OUTPUT_LIMIT', jobs._atomic, path, {'x': largest['x'] + 'y'})
        self.assertNotIn(str(self.root), str(error))
        self.assertEqual(jobs._json(path), largest)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['status.json'])



class ReplaceRetryTests(unittest.TestCase):
    """Windows refuses a replacement while another process holds the destination open, and an open while a
    replacement is in progress; both are transient, so the job files retry briefly. POSIX behaviour is unchanged."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='atlas-job-retry-')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name).resolve() / 'status.json'
        jobs._atomic(self.path, {'state': 'running', 'n': 0})

    def flaky(self, real, failures):
        calls = []

        def call(*args, **kwargs):
            calls.append(1)
            if len(calls) <= failures:
                raise PermissionError(13, 'Access is denied')
            return real(*args, **kwargs)
        return call, calls

    def test_a_transient_denial_is_retried_on_windows_only(self):
        replace, calls = self.flaky(jobs.os.replace, 3)
        with patch.object(jobs.reader, 'WINDOWS', True), patch.object(jobs.os, 'replace', replace), \
                patch.object(jobs.time, 'sleep'):
            jobs._atomic(self.path, {'state': 'running', 'n': 1})
        self.assertEqual((len(calls), jobs._json(self.path)['n']), (4, 1))
        replace, calls = self.flaky(jobs.os.replace, 1)
        with patch.object(jobs.reader, 'WINDOWS', False), patch.object(jobs.os, 'replace', replace):
            with self.assertRaises(PermissionError):
                jobs._atomic(self.path, {'state': 'running', 'n': 2})
        self.assertEqual((len(calls), jobs._json(self.path)['n']), (1, 1))
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ['status.json'])   # no temporary left
        opened, calls = self.flaky(Path.open, 2)
        with patch.object(jobs.reader, 'WINDOWS', True), patch.object(Path, 'open', opened), \
                patch.object(jobs.reader.time, 'sleep'):
            self.assertEqual(jobs._json(self.path)['n'], 1)
        self.assertEqual(len(calls), 3)
        opened, calls = self.flaky(Path.open, 1)
        with patch.object(jobs.reader, 'WINDOWS', False), patch.object(Path, 'open', opened):
            with self.assertRaises(PermissionError):
                jobs._json(self.path)

    def test_a_persistent_denial_still_raises_after_the_bounded_wait(self):
        replace, calls = self.flaky(jobs.os.replace, 10**6)
        with patch.object(jobs.reader, 'WINDOWS', True), patch.object(jobs.os, 'replace', replace), \
                patch.object(jobs.time, 'sleep'):
            with self.assertRaises(PermissionError):
                jobs._atomic(self.path, {'state': 'running', 'n': 3})
        self.assertEqual(len(calls), jobs.reader.REPLACE_RETRIES)

    @unittest.skipUnless(sys.platform == 'win32', 'the sharing violation is a Windows behaviour')
    def test_a_reader_holding_the_status_file_no_longer_fails_the_writer(self):
        held, released = threading.Event(), threading.Event()

        def reader():
            with self.path.open('rb'):
                held.set()
                released.wait(.2)
        thread = threading.Thread(target=reader)
        thread.start()
        held.wait(5)
        threading.Timer(.1, released.set).start()
        jobs._atomic(self.path, {'state': 'running', 'n': 4})          # waits for the reader instead of failing
        thread.join(5)
        self.assertEqual(jobs._json(self.path)['n'], 4)


if __name__ == '__main__':
    unittest.main()
