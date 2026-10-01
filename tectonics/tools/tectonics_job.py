"""Managed local W12 jobs. Trusted CLI paths only; no HTTP or detached process.

SPDX-License-Identifier: AGPL-3.0-only
Run/resume stay attached to their caller. OS locks end with the worker process;
immutable requests and native commits survive it. This is not a new scheduler.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager, suppress
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

import read_tectonics as reader

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'atlas.tectonics-job.v1'
REQUEST_SCHEMA = 'atlas.tectonics-job-request.v1'
CASE = 'w12-public-columns-v1'
MAX_JOBS = 32
MAX_SECONDS = 300.
MAX_CONTROL = 64 << 10          # every control file's read limit; writes must fit it, newline included
ACTIVE = {'preparing', 'running', 'finalising'}
TERMINAL = {'completed', 'cancelled', 'failed', 'interrupted'}
JOB_ID = re.compile(r'[0-9a-f]{32}\Z')
REPORT = re.compile(r'run-[0-9]{5}\.json\Z')
# A just-published job's worker lock can be held only by a status/cancel/result poll (active.lock excludes every
# other worker), for microseconds: its first claim waits up to about two seconds before RUN_BUSY.
CLAIM_RETRIES, CLAIM_WAIT_S = 100, .02
STAGING_HEX = 16                # random suffix of a dot-named staging folder (see _staging)
# Status phase of a published job that no worker has started: awaiting its submitter's claim while active, or never
# started once stopped. Polls report it as it is (never 'interrupted' while it waits) and cancel records a request.
SUBMITTED = 'submitted'


class JobError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _json(path):
    return reader._read_json(path, MAX_CONTROL)


def _encode(value):
    """Canonical compact control bytes (sorted keys, no spaces, finite, ASCII, one newline) within the read limit."""
    body = (json.dumps(value, allow_nan=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    if len(body) > MAX_CONTROL:
        raise JobError('OUTPUT_LIMIT', 'A job control record exceeds its 64 KiB control-file limit.')
    return body


def _atomic(path, value):
    body = _encode(value)       # refused before any temporary exists
    reader._path(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        reader._path(path, maximum=MAX_CONTROL)
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        with temporary.open('xb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(reader.REPLACE_RETRIES):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                # On Windows a status or cancel reader holding the destination open blocks the replacement for
                # microseconds; wait briefly. POSIX renames never fail this way; a persistent denial still raises.
                if not reader.WINDOWS or attempt == reader.REPLACE_RETRIES-1:
                    raise
                time.sleep(reader.REPLACE_WAIT_S)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _lock(path):
    """One-byte advisory process lock; never infer liveness from PID reuse."""
    reader._path(path.parent, directory=True)
    try:
        initial = path.open('xb')
    except FileExistsError:
        pass
    else:
        # Windows byte locks are mandatory: another caller may lock this new, still empty file before its byte is
        # flushed, refusing the write. The file exists either way and an empty lock file is accepted below.
        with suppress(PermissionError), initial:
            initial.write(b'0')
    reader._path(path, maximum=1)
    with path.open('r+b') as stream:
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise JobError('RUN_BUSY', 'A worker is already using this job or jobs directory.') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def _claim(directory, write, claimed, abandoned):
    """Claim a job this call has just published under active.lock (status phase SUBMITTED) and record the claim.

    The worker lock is retried briefly (CLAIM_RETRIES) because a poll may land right after publication; a lock still
    held after the wait refuses RUN_BUSY as before. ``write(path, record)`` then replaces the staged status with
    ``claimed``. Until that is recorded, any failure (that RUN_BUSY, an interruption, a failed write) records
    ``abandoned`` instead, as a best effort: the job reads as interrupted and never started, so resume starts it.
    """
    held = ExitStack()
    try:
        for attempt in range(CLAIM_RETRIES):
            try:
                held.enter_context(_lock(directory / 'worker.lock'))
                break
            except JobError as exc:
                if exc.code != 'RUN_BUSY' or attempt == CLAIM_RETRIES-1:
                    raise
                time.sleep(CLAIM_WAIT_S)
        write(directory / 'status.json', claimed)
    except BaseException:
        with held, suppress(Exception):
            write(directory / 'status.json', abandoned)
        raise
    with held:
        yield


def _busy(directory, name='worker.lock'):
    try:
        with _lock(directory / name):
            return False
    except JobError as exc:
        if exc.code == 'RUN_BUSY':
            return True
        raise


def _staging(directory, token):
    # Dot-named sibling '.<job ID>-<16 hex>': never matches JOB_ID, so it is never counted, listed or read as a job.
    # Its longest path (root + 64 characters) stays below the job directory's own longest control temporary.
    return directory.with_name('.' + directory.name + '-' + token)


def _stage(directory, files, check=None):
    """Publish a new job directory complete: write its files into a dot-named staging folder, then rename it.

    Call under the root's active.lock. A poll finds no job or one with every control file, never half of one.
    Before the rename, a failure removes only the files this call created (identity-checked, after their handles
    closed) and then its empty folder. A hard crash can leave that folder; nothing deletes it automatically.
    """
    staging = _staging(directory, uuid.uuid4().hex[:STAGING_HEX])
    staging.mkdir()
    folder, owned = os.lstat(staging), []
    try:
        for name, body in files:
            with (staging / name).open('xb') as stream:
                owned.append((staging / name, os.fstat(stream.fileno())))
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        if check is not None:
            check(staging)
        for attempt in range(reader.REPLACE_RETRIES):
            try:
                os.rename(staging, directory)
                break
            except PermissionError:
                # Windows refuses a directory rename while another process (an indexer or antivirus) has it open.
                if not reader.WINDOWS or attempt == reader.REPLACE_RETRIES-1:
                    raise
                time.sleep(reader.REPLACE_WAIT_S)
    except BaseException:
        for path, created in reversed(owned):
            with suppress(OSError):
                info = os.lstat(path)
                if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == (created.st_dev, created.st_ino):
                    os.unlink(path)
        with suppress(OSError):
            info = os.lstat(staging)
            if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (folder.st_dev, folder.st_ino):
                os.rmdir(staging)       # only when empty; anything this call did not create is left alone
        raise


def _new_state(job_id, attempt):
    return dict(schema=SCHEMA, job_id=job_id, state='preparing', phase='preparing', attempt=attempt,
                completed_outputs=0, total_outputs=3, report=None, product_id=None, seconds=0., error=None)


def _paths(root, job_id, *, existing=True):
    root = reader._path(root, directory=True)
    if type(job_id) is not str or not JOB_ID.fullmatch(job_id):
        raise JobError('INVALID_REQUEST', 'A lowercase 32-character hexadecimal job ID is required.')
    directory = root / job_id
    if existing:
        reader._path(directory, directory=True)
    elif directory.exists() or directory.is_symlink():
        reader._path(directory, directory=True)
    return root, directory


def _path_budget(directory):
    # R12 deliberately uses ordinary Windows paths and full content hashes.
    destination = directory / 'run' / 'g' / ('0' * 64) / ('0' * 64 + '.json')
    if os.name == 'nt' and len(str(destination).encode('utf-16-le')) // 2 >= 260:
        raise JobError('INVALID_PATH', 'The jobs directory is too long for the native cache; choose a shorter root.')


def _sources():
    paths = (Path(__file__), ROOT / 'tools/w12_job_worker.py',
             ROOT / 'tools/run_tectonics.py', ROOT / 'tools/w12_graph.py',
             ROOT / 'tools/read_tectonics.py', ROOT / 'examples/w12_column_case.py')
    return {path.resolve().relative_to(ROOT).as_posix():
            hashlib.sha256(reader._path(path).read_bytes()).hexdigest() for path in paths}


def _native_paths(directory):
    """Reject linked recovery content before native constructors can write."""
    if not directory.exists() and not directory.is_symlink():
        return
    reader._path(directory, directory=True)
    count = 0
    for parent, folders, files in os.walk(directory, followlinks=False):
        for name in folders + files:
            count += 1
            if count > 4096:
                raise JobError('INPUT_LIMIT', 'The job recovery tree exceeds its file-count limit.')
            path = Path(parent) / name
            reader._path(path, directory=name in folders,
                         maximum=None if name in folders else 32 << 20)


def _runtime():
    from atlas_tectonics.reuse import ExecutionContext
    with ExecutionContext() as execution:
        execution.verify()
        return execution.identity


def _request(directory):
    request = _json(directory / 'request.json')
    if (type(request) is not dict or set(request) != {
            'schema', 'job_id', 'case_id', 'cells', 'sources', 'execution_id'}
            or request['schema'] != REQUEST_SCHEMA or request['case_id'] != CASE
            or request['job_id'] != directory.name or type(request['cells']) is not int
            or not 5 <= request['cells'] <= 64 or type(request['sources']) is not dict
            or not re.fullmatch('[0-9a-f]{64}', str(request['execution_id']))):
        raise JobError('INVALID_STATE', 'The immutable job request is invalid.')
    return request


def _state(directory):
    value = _json(directory / 'status.json')
    if (type(value) is not dict or value.get('schema') != SCHEMA
            or value.get('job_id') != directory.name
            or value.get('state') not in ACTIVE | TERMINAL
            or type(value.get('attempt')) is not int or not 1 <= value['attempt'] <= 1000
            or type(value.get('completed_outputs')) is not int
            or not 0 <= value['completed_outputs'] <= 3
            or value.get('total_outputs') != 3
            or value.get('report') is not None and
               (type(value['report']) is not str or not REPORT.fullmatch(value['report']))):
        raise JobError('INVALID_STATE', 'The saved job status is invalid.')
    return value


def _cancel_path(directory, state):
    return directory / ('cancel-%04d.json' % state['attempt'])


def _cancelled(directory, state):
    path = _cancel_path(directory, state)
    if not path.exists() and not path.is_symlink():
        return False
    if _json(path) != {'job_id': directory.name, 'attempt': state['attempt']}:
        raise JobError('INVALID_STATE', 'The cancellation request is invalid.')
    return True


def _public(directory, state, *, busy):
    request = _request(directory)
    state = dict(state)
    # A live submitter holds active.lock even before claiming worker.lock. If both locks are free, a hard-killed
    # submitter cannot publish its terminal status: expose recovery without changing the saved never-started phase.
    waiting = (state['state'] in ACTIVE and state.get('phase') == SUBMITTED
               and (busy or _busy(directory.parent, 'active.lock')))
    if state['state'] in ACTIVE and not busy and not waiting:
        state['state'] = 'interrupted'
        if state.get('phase') != SUBMITTED:
            state['phase'] = 'worker-exited'
    requested = (busy or waiting) and _cancelled(directory, state)
    if requested and state['state'] in ACTIVE:
        state['state'] = 'cancelling'
    return dict(schema=SCHEMA, status='ok', job=dict(
        id=directory.name, case_id=CASE, cells=request['cells'],
        state=state['state'], phase=state.get('phase'), attempt=state['attempt'],
        completed_outputs=state['completed_outputs'], total_outputs=3,
        progress_basis='completed declared outputs, not elapsed-time percentage',
        report=state.get('report'), product_id=state.get('product_id'),
        seconds=state.get('seconds'), statistics=state.get('statistics'),
        error=state.get('error'), cancellation_requested=bool(requested),
        worker_active=busy,
        capabilities=dict(cancel=(busy or waiting) and state['state'] in ACTIVE | {'cancelling'},
            resume=not busy and state['state'] in {'cancelled', 'interrupted', 'failed'},
            inspect=not busy and state.get('report') is not None),
        resume_validation='Original inputs, source/runtime and native dependencies must verify.',
        cancellation='Cooperative native checkpoints; preparation or final verification may finish first.',
        max_seconds=MAX_SECONDS,
        source_status='WORKING NON-CANON'))


def status(root, job_id):
    _, directory = _paths(root, job_id)
    try:
        with _lock(directory / 'worker.lock'):
            return _public(directory, _state(directory), busy=False)
    except JobError as exc:
        if exc.code != 'RUN_BUSY':
            raise
    # Holding the lock for inactive snapshots prevents a new resume racing a
    # falsely recoverable status. A busy snapshot can be conservatively stale.
    return _public(directory, _state(directory), busy=True)


def cancel(root, job_id):
    _, directory = _paths(root, job_id)
    state = _state(directory)
    # A job awaiting its claim takes the request without probing its lock: its worker checks it before any work.
    if state['state'] in ACTIVE and (state.get('phase') == SUBMITTED or _busy(directory)):
        _atomic(_cancel_path(directory, state),
                {'job_id': job_id, 'attempt': state['attempt']})
    return status(root, job_id)


def result(root, job_id):
    _, directory = _paths(root, job_id)
    with _lock(directory / 'worker.lock'):
        state = _state(directory)
        _request(directory)
        if state['report'] is None:
            raise JobError('NO_RESULT', 'This job has no completed saved output to inspect.')
        return reader.response(directory / 'run', state['report'])


def _safe_error(exc):
    if isinstance(exc, JobError):
        return dict(code=exc.code, message=str(exc))
    if isinstance(exc, FileNotFoundError):
        return dict(code='MISSING_INPUT', message='A required local job file or directory is missing.')
    if isinstance(exc, reader.ReadError):
        return dict(code=exc.code, message='A job path or saved input failed validation.')
    if isinstance(exc, ImportError):
        return dict(code='DEPENDENCY_UNAVAILABLE', message='A required worker dependency is unavailable.')
    return dict(code='WORKER_FAILED', message='The job failed; its complete native checkpoints were retained. No result was invented.')


def run(root, job_id, *, cells=None, resume=False, executor=None):
    root, directory = _paths(root, job_id, existing=resume)
    _path_budget(directory)
    if cells is not None and (type(cells) is not int or not 5 <= cells <= 64):
        raise JobError('INVALID_REQUEST', 'Cells must be an integer between 5 and 64.')
    # A repeated run ID means the same submission, never a second simulation.
    if not resume and directory.exists():
        request = _request(directory)
        if request['cells'] != (8 if cells is None else cells):
            raise JobError('REQUEST_CONFLICT', 'That job ID already belongs to different inputs.')
        return status(root, job_id)
    with _lock(root / 'active.lock'):
        if not resume:
            if directory.exists():
                return run(root, job_id, cells=cells, executor=executor)
            if sum(bool(JOB_ID.fullmatch(path.name)) for path in root.iterdir()) >= MAX_JOBS:
                raise JobError('JOB_LIMIT', 'This jobs directory has reached its 32-job limit; retain or archive jobs before using a new directory.')
            request = dict(schema=REQUEST_SCHEMA, job_id=job_id, case_id=CASE,
                cells=8 if cells is None else cells, sources=_sources(), execution_id=_runtime())
            # The job becomes visible only with a valid request and status, so no poll can wedge its ID. Its status
            # says SUBMITTED until the claim below records the worker (or records it interrupted, never started).
            staged = dict(_new_state(job_id, 1), phase=SUBMITTED)
            _stage(directory, (('request.json', _encode(request)), ('status.json', _encode(staged))))
            previous = None
        else:
            request = _request(directory)
            if cells is not None and cells != request['cells']:
                raise JobError('REQUEST_CONFLICT', 'Resume cannot change the submitted inputs.')
            if request['sources'] != _sources() or request['execution_id'] != _runtime():
                raise JobError('SOURCE_MISMATCH', 'The original worker source or runtime changed; no automatic rebind is allowed.')
            previous = _state(directory)
            if previous['state'] == 'completed':
                return _public(directory, previous, busy=False)
        with (_lock(directory / 'worker.lock') if resume else
              _claim(directory, _atomic, _new_state(job_id, 1), dict(staged, state='interrupted'))):
            _native_paths(directory / 'run')
            attempt = 1 if previous is None else previous['attempt'] + 1
            if attempt > 1000:
                raise JobError('ATTEMPT_LIMIT', 'This job has reached its continuation-attempt limit.')
            state = _new_state(job_id, attempt)
            if previous is not None:        # a fresh job's claim has already recorded exactly this record
                for key in ('completed_outputs', 'report', 'product_id'):
                    state[key] = previous[key]
                _atomic(directory / 'status.json', state)
            started = time.perf_counter()
            last_cancel_check = -1.
            requested = False
            timed_out = False
            def cancelled():
                nonlocal last_cancel_check, requested, timed_out
                now = time.perf_counter()
                if now - started >= MAX_SECONDS:
                    timed_out = True
                    return True
                if not requested and now - last_cancel_check >= .1:
                    requested = _cancelled(directory, state)
                    last_cancel_check = now
                return requested
            def progress(update):
                if type(update) is not dict:
                    raise JobError('INVALID_STATE', 'The worker supplied invalid progress.')
                report = update.get('report') or state['report']
                count = update.get('completed_outputs', state['completed_outputs'])
                if (type(count) is not int or not 0 <= count <= 3
                        or report is not None and (type(report) is not str or not REPORT.fullmatch(report))):
                    raise JobError('INVALID_STATE', 'The worker supplied invalid output progress.')
                product_id = update.get('product_id') or state['product_id']
                if count < state['completed_outputs']:
                    count, report, product_id = (state['completed_outputs'],
                                                 state['report'], state['product_id'])
                state.update(state='running', phase=update.get('phase', 'running'),
                    completed_outputs=count, report=report,
                    product_id=product_id,
                    seconds=time.perf_counter() - started)
                _atomic(directory / 'status.json', state)
            try:
                if executor is None:
                    from w12_job_worker import execute
                    executor = execute
                output = executor(directory / 'run', cells=request['cells'],
                    resume=(directory / 'run').exists(),
                    cancelled=cancelled, progress=progress)
                if request['sources'] != _sources():
                    raise JobError('SOURCE_MISMATCH', 'Worker source changed during execution; no automatic rebind is allowed.')
                if output.get('status') not in {'completed', 'cancelled'}:
                    raise JobError('INVALID_STATE', 'The worker did not return a supported terminal state.')
                progress(output)
                state.update(state=output['status'], phase=output['status'],
                             statistics=output.get('statistics'))
                if timed_out and state['state'] == 'cancelled':
                    state['phase'] = 'time-limit'
            except BaseException as exc:
                state.update(state='interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed',
                             phase='stopped', error=_safe_error(exc))
            state['seconds'] = time.perf_counter() - started
            _atomic(directory / 'status.json', state)
            return _public(directory, state, busy=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'resume', 'status', 'cancel', 'result'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--cells', type=int)
    args = parser.parse_args()
    try:
        if args.action in {'run', 'resume'}:
            answer = run(args.root, args.job_id, cells=args.cells, resume=args.action == 'resume')
        else:
            if args.cells is not None:
                raise JobError('INVALID_REQUEST', 'Cells are accepted only for a run or exact resume.')
            answer = globals()[args.action](args.root, args.job_id)
    except Exception as exc:
        answer = dict(schema=SCHEMA, status='error', error=_safe_error(exc))
    print(json.dumps(answer, allow_nan=False, separators=(',', ':')))
    return 0 if answer['status'] == 'ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
