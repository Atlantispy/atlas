"""Bounded synchronous generated-world evolution jobs, not a W12 example alias.

SPDX-License-Identifier: AGPL-3.0-only
The original .atlas and prepared material-map inputs are immutable. Resume
reconstructs the closed-form owner from saved inputs; it never rerandomises or
resamples the project, and does not claim generic joined-workflow restart.
Cancellation is cooperative, without a hard latency guarantee. Trusted local
paths only; callers retain ownership of the single attached worker process.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import stat
import sys
import time
from types import CodeType, FunctionType

import tectonics_job as jobs
import new_world as paths
import new_world_project as projects
from new_world_contract import ContractError, canonical_bytes, parse_json

SCHEMA = 'atlas.new-world-evolution-job.v1'
REQUEST_SCHEMA = 'atlas.new-world-evolution-job-request.v1'
PREFIX_SCHEMA = 'atlas.new-world-evolution-prefix.v1'
OUTPUT_SCHEMA = 'atlas.new-world-evolution-output.v1'
PRODUCER = 'atlas-generated-material-map-evolution-v1'
MAX_RECORD = 2 << 20
MAX_RESULTS = 64 << 20
MAX_OUTPUTS = 256
MAX_SECONDS = 300.
MAX_ATTEMPTS = 1000
ACTIVE = {'preparing', 'running'}
STATES = ACTIVE | {'completed', 'partial', 'cancelled', 'failed', 'interrupted'}
MESSAGES = {
    'INVALID_REQUEST': 'Use a bounded generated-world request and declared elapsed-time schedule.',
    'INVALID_STATE': 'The saved job or one of its committed dependencies is inconsistent.',
    'SOURCE_MISMATCH': 'The original execution sources changed; no automatic rebind is allowed.',
    'REQUEST_CONFLICT': 'This job ID already belongs to different frozen inputs or options.',
    'INPUT_CHANGED': 'The frozen original world no longer matches its recorded bytes.',
    'INITIAL_INCOMPLETE': 'No complete prepared input was saved; this job cannot resume without resampling.',
    'RUN_BUSY': 'A worker is already using this job or jobs root.',
    'JOB_LIMIT': 'This root has reached its retained-job limit.',
    'ATTEMPT_LIMIT': 'This job has reached its continuation-attempt limit.',
    'OUTPUT_LIMIT': 'The requested output exceeds its finite storage envelope.',
    'TIME_LIMIT': 'The job reached its cooperative wall-time limit.',
    'CANCELLED': 'The job was cancelled at a cooperative checkpoint.',
    'MISSING_INPUT': 'A required local file or directory is missing.',
    'INVALID_PATH': 'Use regular local files and directories without linked paths.',
    'WORKER_FAILED': 'The worker failed; committed outputs and the original world were retained.',
    'EVOLUTION_REFUSED': 'The supplied world or regional evolution scenario is unsupported.',
    'NATIVE_INPUT_REFUSED': 'The saved world cannot supply the requested bounded native material inputs.',
}

_SELF = Path(__file__).resolve()
_RAW = _SELF.read_bytes()
if sys._getframe().f_code != compile(_RAW, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed generated-world job source differs')
_LOADED = {_SELF: hashlib.sha256(_RAW).hexdigest()}
del _RAW
_HELPERS = []
for _module in (jobs, jobs.reader, paths, projects):
    _path = Path(_module.__file__).resolve()
    _raw = _path.read_bytes()
    _LOADED[_path] = hashlib.sha256(_raw).hexdigest()
    _codes = {code.co_name: code for code in compile(_raw, _module.__file__, 'exec',
              dont_inherit=True).co_consts if isinstance(code, CodeType)}
    for _name, _fn in vars(_module).items():
        if isinstance(_fn, FunctionType) and _fn.__module__ == _module.__name__ and _name in _codes:
            _actual = getattr(_fn, '__wrapped__', _fn)
            if _actual.__code__ != _codes[_name]:
                raise ValueError('executed job helper differs from its source')
            _HELPERS.append((_module, _name, _fn, _actual.__code__))
del _raw, _codes, _actual, _fn, _name, _path, _module


def _fail(code):
    raise jobs.JobError(code, MESSAGES[code])


def _hex(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _backend():
    import new_world_evolution
    return new_world_evolution


def _load_project(path):
    return projects.load_project(path)


def _sources(backend):
    result = {}
    for path, expected in _LOADED.items():
        digest = hashlib.sha256(jobs.reader._path(path).read_bytes()).hexdigest()
        if digest != expected:
            _fail('SOURCE_MISMATCH')
        result[path.name] = digest
    for module, name, original, code in _HELPERS:
        actual = getattr(module, name, None)
        if actual is not original or getattr(actual, '__wrapped__', actual).__code__ is not code:
            _fail('SOURCE_MISMATCH')
    return dict(adapters=result, evolution=backend.source_binding())


def _encoded(value, maximum=MAX_RECORD):
    # Bound depth and node count before JSON encoding; no custom coercions.
    remaining = 150000
    def visit(item, depth=0):
        nonlocal remaining
        remaining -= 1
        if depth > 32 or remaining < 0:
            _fail('OUTPUT_LIMIT')
        if item is None or type(item) is bool:
            return
        if type(item) is str:
            if len(item) > maximum:
                _fail('OUTPUT_LIMIT')
        elif type(item) is int:
            if item.bit_length() > 256:
                _fail('INVALID_STATE')
        elif type(item) is float:
            if not math.isfinite(item):
                _fail('INVALID_STATE')
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    _fail('INVALID_STATE')
                visit(key, depth + 1); visit(child, depth + 1)
        else:
            _fail('INVALID_STATE')
    visit(value)
    body = bytearray()
    for part in json.JSONEncoder(sort_keys=True, separators=(',', ':'),
            ensure_ascii=True, allow_nan=False).iterencode(value):
        part = part.encode('ascii')
        if len(body) + len(part) > maximum:
            _fail('OUTPUT_LIMIT')
        body.extend(part)
    return bytes(body)


def _sha(body):
    return hashlib.sha256(body).hexdigest()


def _read(path, maximum):
    path, parents = paths._checked_path(os.fspath(path))
    with paths._Directory(path.parent, parents) as directory:
        info = directory.inspect(path.name)
        if paths._unsafe(info) or not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
            _fail('INVALID_PATH')
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(directory.open(path.name, flags), 'rb') as stream:
            before = os.fstat(stream.fileno())
            if paths._identity(before) != paths._identity(info):
                _fail('INVALID_PATH')
            body = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        if len(body) != info.st_size or (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            _fail('INPUT_CHANGED')
        paths._check_parents(parents)
    return body


def _json(path, maximum=65536):
    body = _read(path, maximum)
    value = json.loads(body.decode('utf-8'), object_pairs_hook=jobs.reader._pairs,
                       parse_constant=jobs.reader._constant)
    if _encoded(value, maximum) != body:
        _fail('INVALID_STATE')
    return value, body


def _publish(path, body):
    """Publish only complete immutable bytes, cleaning only our owned temporary."""
    path, parents = paths._checked_path(os.fspath(path))
    with paths._Directory(path.parent, parents) as directory:
        name = '.new-world-' + secrets.token_hex(16) + '.tmp'
        fd = directory.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0))
        identity = paths._identity(os.fstat(fd))
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(body); stream.flush(); os.fsync(stream.fileno())
            info = directory.inspect(name)
            if paths._unsafe(info) or paths._identity(info) != identity:
                _fail('INVALID_PATH')
            directory.publish(name, path.name)
        finally:
            directory.remove_owned(name, identity)


def _control(path, value):
    # Reuse the existing atomic, fsynced mutable-control publication mechanism.
    _encoded(value, 65536)
    jobs._atomic(path, value)


def _control_json(path):
    value = jobs.reader._read_json(path, 65536)
    _encoded(value, 65536)
    return value


def _schedule(values):
    if (type(values) is not list or not 1 <= len(values) <= MAX_OUTPUTS
            or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values)
            or values[0] != 0 or any(a >= b for a, b in zip(values, values[1:]))):
        _fail('INVALID_REQUEST')
    return list(values)


def _max_new(value):
    if value is not None and (type(value) is not int or not 1 <= value <= MAX_OUTPUTS):
        _fail('INVALID_REQUEST')
    return value


def _request(directory):
    value, body = _json(directory / 'request.json')
    if (type(value) is not dict or set(value) != {'schema', 'producer_id', 'job_id', 'input',
            'options', 'schedule_s', 'max_wall_seconds', 'sources'}
            or value['schema'] != REQUEST_SCHEMA or value['producer_id'] != PRODUCER
            or value['job_id'] != directory.name or type(value['options']) is not dict
            or type(value['sources']) is not dict):
        _fail('INVALID_STATE')
    _schedule(value['schedule_s'])
    source = value['input']
    if (type(source) is not dict or set(source) != {'sha256', 'size_bytes'}
            or not _hex(source['sha256']) or type(source['size_bytes']) is not int
            or not 0 < source['size_bytes'] <= projects.MAX_PROJECT):
        _fail('INVALID_STATE')
    wall = value['max_wall_seconds']
    if type(wall) not in (int, float) or not math.isfinite(wall) or not 0 < wall <= MAX_SECONDS:
        _fail('INVALID_STATE')
    return value, _sha(body)


def _state(directory):
    state = _control_json(directory / 'status.json')
    if (type(state) is not dict or state.get('schema') != SCHEMA
            or state.get('job_id') != directory.name or state.get('state') not in STATES
            or type(state.get('attempt')) is not int or not 1 <= state['attempt'] <= MAX_ATTEMPTS):
        _fail('INVALID_STATE')
    return state


def _prefix(directory, request, request_sha):
    prefix = _control_json(directory / 'prefix.json')
    if (type(prefix) is not dict or set(prefix) != {'schema', 'job_id', 'request_sha256',
            'initial_sha256', 'outputs'} or prefix['schema'] != PREFIX_SCHEMA
            or prefix['job_id'] != directory.name or prefix['request_sha256'] != request_sha
            or not _hex(prefix['initial_sha256']) or type(prefix['outputs']) is not list
            or len(prefix['outputs']) > len(request['schedule_s'])):
        _fail('INVALID_STATE')
    total = 0
    for index, entry in enumerate(prefix['outputs']):
        if (type(entry) is not dict or set(entry) != {'index', 'elapsed_s', 'file', 'sha256',
                'size_bytes', 'output_id'} or type(entry['index']) is not int or entry['index'] != index
                or entry['elapsed_s'] != request['schedule_s'][index]
                or entry['file'] != f'output-{index:04d}.json' or not _hex(entry['sha256'])
                or not _hex(entry['output_id']) or type(entry['size_bytes']) is not int
                or not 0 < entry['size_bytes'] <= MAX_RECORD):
            _fail('INVALID_STATE')
        output, body = _json(directory / entry['file'], MAX_RECORD)
        if (len(body) != entry['size_bytes'] or _sha(body) != entry['sha256']
                or type(output) is not dict or set(output) != {'schema', 'request_sha256',
                    'initial_sha256', 'index', 'elapsed_s', 'result'}
                or output['schema'] != OUTPUT_SCHEMA or output['request_sha256'] != request_sha
                or output['initial_sha256'] != prefix['initial_sha256'] or output['index'] != index
                or output['elapsed_s'] != entry['elapsed_s'] or type(output['result']) is not dict
                or output['result'].get('output_id') != entry['output_id']):
            _fail('INVALID_STATE')
        total += len(body)
        if total > MAX_RESULTS:
            _fail('OUTPUT_LIMIT')
    return prefix, total


class _Cancel:
    def __init__(self, directory, state, seconds):
        self.directory, self.state = directory, state
        self.end = time.perf_counter() + seconds
        self.next_check, self.requested, self.timed_out = 0., False, False

    def is_set(self):
        now = time.perf_counter()
        if now >= self.end:
            self.timed_out = True
            return True
        if not self.requested and now >= self.next_check:
            self.requested = jobs._cancelled(self.directory, self.state)
            self.next_check = now + .1
        return self.requested

    def check(self):
        if self.is_set():
            raise CancelledError()


def _public(directory, state, busy=False):
    result = dict(state)
    # Requested schedule, not an assertion that every time has a saved result.
    request, _ = _request(directory)
    result['requested_elapsed_s'] = request['schedule_s']
    if result['state'] in ACTIVE and not busy:
        result['state'] = 'interrupted'
    result.update(worker_active=busy,
        resume_semantics='saved initial material-map owner; not generic joined-workflow restart',
        cancellation='Cooperative native checkpoints; preparation and verification may finish first.')
    return dict(schema=SCHEMA, status='ok', job=result)


def _safe(exc):
    code = getattr(exc, 'code', None)
    if code not in MESSAGES:
        code = 'MISSING_INPUT' if isinstance(exc, FileNotFoundError) else 'WORKER_FAILED'
    return dict(code=code, message=MESSAGES[code])


def _execute(directory, request, request_sha, backend, *, fresh, max_new_outputs=None):
    previous = None if fresh else _state(directory)
    attempt = 1 if fresh else previous['attempt'] + 1
    if attempt > MAX_ATTEMPTS:
        _fail('ATTEMPT_LIMIT')
    timings = dict(prepare_s=0., physics_s=0., store_s=0., restore_s=0., elapsed_s=0.)
    state = dict(schema=SCHEMA, producer_id=PRODUCER, job_id=directory.name, state='preparing',
                 attempt=attempt, completed_outputs=0, total_outputs=len(request['schedule_s']),
                 computed_outputs=0, restored_outputs=0, timings=timings, error=None)
    _control(directory / 'status.json', state)
    started = time.perf_counter()
    cancel = _Cancel(directory, state, request['max_wall_seconds'])
    @contextmanager
    def timing(name):
        tick = time.perf_counter()
        try:
            yield
        finally:
            timings[name] += time.perf_counter() - tick
    try:
        cancel.check()
        with timing('restore_s'):
            body = _read(directory / 'input.atlas', projects.MAX_PROJECT)
            if len(body) != request['input']['size_bytes'] or _sha(body) != request['input']['sha256']:
                _fail('INPUT_CHANGED')
            if _sources(backend) != request['sources']:
                _fail('SOURCE_MISMATCH')
        if fresh:
            with timing('prepare_s'):
                initial = backend.prepare(_load_project(directory / 'input.atlas'),
                                          request['options'], cancel=cancel)
                initial_body = _encoded(initial)
            cancel.check()
            if _sources(backend) != request['sources']:
                _fail('SOURCE_MISMATCH')
            if (type(initial) is not dict or not _hex(initial.get('initial_id'))
                    or type(initial.get('max_elapsed_s')) not in (int, float)
                    or not math.isfinite(initial['max_elapsed_s']) or initial['max_elapsed_s'] <= 0
                    or request['schedule_s'][-1] > initial['max_elapsed_s']):
                _fail('INVALID_REQUEST')
            prefix = dict(schema=PREFIX_SCHEMA, job_id=directory.name, request_sha256=request_sha,
                          initial_sha256=_sha(initial_body), outputs=[])
            with timing('store_s'):
                _publish(directory / 'initial.json', initial_body)
                _control(directory / 'prefix.json', prefix)
            total = 0
        else:
            with timing('restore_s'):
                if not (directory / 'initial.json').exists() or not (directory / 'prefix.json').exists():
                    _fail('INITIAL_INCOMPLETE')
                initial, initial_body = _json(directory / 'initial.json', MAX_RECORD)
                prefix, total = _prefix(directory, request, request_sha)
                if (_sha(initial_body) != prefix['initial_sha256']
                        or request['schedule_s'][-1] > initial['max_elapsed_s']):
                    _fail('INVALID_STATE')
        state['restored_outputs'] = len(prefix['outputs'])
        state['completed_outputs'] = len(prefix['outputs'])
        # A complete cache hit verifies source/native inputs without rebuilding
        # geometry or an initial material map. Partial continuation owns physics.
        if len(prefix['outputs']) == len(request['schedule_s']):
            with timing('restore_s'):
                backend.check_initial(initial)
            owner = None
        else:
            with timing('restore_s'):
                owner = backend.PreparedEvolution(initial, cancel=cancel)
        @contextmanager
        def ownership():
            if owner is None:
                yield
            else:
                with owner:
                    yield
        with ownership():
            state['state'] = 'running'
            _control(directory / 'status.json', state)
            for index in range(len(prefix['outputs']), len(request['schedule_s'])):
                cancel.check()
                with timing('physics_s'):
                    result = owner.evaluate(request['schedule_s'][index])
                cancel.check()
                if type(result) is not dict or not _hex(result.get('output_id')):
                    _fail('INVALID_STATE')
                if _sources(backend) != request['sources']:
                    _fail('SOURCE_MISMATCH')
                record = dict(schema=OUTPUT_SCHEMA, request_sha256=request_sha,
                    initial_sha256=prefix['initial_sha256'], index=index,
                    elapsed_s=request['schedule_s'][index], result=result)
                with timing('store_s'):
                    encoded = _encoded(record)
                    if total + len(encoded) > MAX_RESULTS:
                        _fail('OUTPUT_LIMIT')
                    filename = f'output-{index:04d}.json'
                    try:
                        _publish(directory / filename, encoded)
                    except FileExistsError:
                        # A crash after output publication but before prefix commit
                        # may leave these exact bytes. Never overwrite or guess.
                        if _read(directory / filename, MAX_RECORD) != encoded:
                            _fail('INVALID_STATE')
                    prefix['outputs'].append(dict(index=index, elapsed_s=record['elapsed_s'],
                        file=filename, sha256=_sha(encoded), size_bytes=len(encoded),
                        output_id=result['output_id']))
                    _control(directory / 'prefix.json', prefix)
                    total += len(encoded)
                state['computed_outputs'] += 1
                state['completed_outputs'] += 1
                _control(directory / 'status.json', state)
                if max_new_outputs is not None and state['computed_outputs'] >= max_new_outputs:
                    break
            if _sources(backend) != request['sources']:
                _fail('SOURCE_MISMATCH')
        state['state'] = 'completed' if len(prefix['outputs']) == len(request['schedule_s']) else 'partial'
    except CancelledError:
        state['state'] = 'cancelled'
        code = 'TIME_LIMIT' if cancel.timed_out else 'CANCELLED'
        state['error'] = dict(code=code, message=MESSAGES[code])
    except BaseException as exc:
        state['state'] = 'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed'
        state['error'] = _safe(exc)
    timings['elapsed_s'] = time.perf_counter() - started
    _control(directory / 'status.json', state)
    return _public(directory, state)


def submit(root, job_id, source, *, options, schedule_s, max_wall_seconds=MAX_SECONDS,
           max_new_outputs=None):
    root, directory = jobs._paths(root, job_id, existing=False)
    max_new_outputs = _max_new(max_new_outputs)
    schedule_s = _schedule(schedule_s)
    if (type(options) is not dict or type(max_wall_seconds) not in (int, float)
            or not math.isfinite(max_wall_seconds) or not 0 < max_wall_seconds <= MAX_SECONDS):
        _fail('INVALID_REQUEST')
    # Strict small options, including duplicate-key rejection at the CLI boundary.
    options = parse_json(canonical_bytes(options))
    input_bytes = _read(source, projects.MAX_PROJECT)
    backend = _backend()
    request = dict(schema=REQUEST_SCHEMA, producer_id=PRODUCER, job_id=job_id,
        input=dict(sha256=_sha(input_bytes), size_bytes=len(input_bytes)), options=options,
        schedule_s=schedule_s, max_wall_seconds=max_wall_seconds, sources=_sources(backend))
    request_body = _encoded(request, 65536)
    with jobs._lock(root / 'active.lock'):
        if directory.exists():
            original, _ = _request(directory)
            if original != request:
                _fail('REQUEST_CONFLICT')
            return status(root, job_id)
        if sum(bool(jobs.JOB_ID.fullmatch(p.name)) for p in root.iterdir()) >= jobs.MAX_JOBS:
            _fail('JOB_LIMIT')
        directory.mkdir()
        with jobs._lock(directory / 'worker.lock'):
            _publish(directory / 'input.atlas', input_bytes)
            # The identity is checked against published copied bytes, never a path.
            if _read(directory / 'input.atlas', projects.MAX_PROJECT) != input_bytes:
                _fail('INPUT_CHANGED')
            _publish(directory / 'request.json', request_body)
            return _execute(directory, request, _sha(request_body), backend, fresh=True,
                            max_new_outputs=max_new_outputs)


def resume(root, job_id, *, max_new_outputs=None):
    max_new_outputs = _max_new(max_new_outputs)
    root, directory = jobs._paths(root, job_id)
    with jobs._lock(root / 'active.lock'), jobs._lock(directory / 'worker.lock'):
        request, request_sha = _request(directory)
        backend = _backend()
        if _sources(backend) != request['sources']:
            _fail('SOURCE_MISMATCH')
        return _execute(directory, request, request_sha, backend, fresh=False,
                        max_new_outputs=max_new_outputs)


def status(root, job_id):
    _, directory = jobs._paths(root, job_id)
    _request(directory)
    try:
        with jobs._lock(directory / 'worker.lock'):
            return _public(directory, _state(directory))
    except jobs.JobError as exc:
        if exc.code != 'RUN_BUSY':
            raise
    return _public(directory, _state(directory), busy=True)


def cancel(root, job_id):
    _, directory = jobs._paths(root, job_id)
    _request(directory)
    state = _state(directory)
    if jobs._busy(directory) and state['state'] in ACTIVE:
        jobs._atomic(jobs._cancel_path(directory, state), dict(job_id=job_id, attempt=state['attempt']))
    return status(root, job_id)


def read_output(root, job_id, index=-1):
    """Verify saved closure even on a cache hit; never call prepare/evaluate."""
    _, directory = jobs._paths(root, job_id)
    with jobs._lock(directory / 'worker.lock'):
        request, request_sha = _request(directory)
        backend = _backend()
        if _sources(backend) != request['sources']:
            _fail('SOURCE_MISMATCH')
        body = _read(directory / 'input.atlas', projects.MAX_PROJECT)
        if _sha(body) != request['input']['sha256'] or len(body) != request['input']['size_bytes']:
            _fail('INPUT_CHANGED')
        initial, body = _json(directory / 'initial.json', MAX_RECORD)
        prefix, _ = _prefix(directory, request, request_sha)
        if _sha(body) != prefix['initial_sha256']:
            _fail('INVALID_STATE')
        backend.check_initial(initial)
        if type(index) is not int or not prefix['outputs'] or not -len(prefix['outputs']) <= index < len(prefix['outputs']):
            _fail('INVALID_REQUEST')
        return _json(directory / prefix['outputs'][index]['file'], MAX_RECORD)[0]['result']


def response(argv, stdin):
    try:
        if not argv or argv[0] not in {'submit', 'resume', 'status', 'cancel', 'result'}:
            _fail('INVALID_REQUEST')
        action, flags = argv[0], argv[1:]
        if len(flags) % 2:
            _fail('INVALID_REQUEST')
        values = dict(zip(flags[::2], flags[1::2]))
        expected = {'--root', '--job-id'} | ({'--file'} if action == 'submit' else set())
        extra = {'--max-new-outputs'} if action in {'submit', 'resume'} and '--max-new-outputs' in values else set()
        if action == 'result' and '--index' in values:
            extra.add('--index')
        if len(values) != len(flags)//2 or set(values) != expected | extra:
            _fail('INVALID_REQUEST')
        max_new = _max_new(int(values['--max-new-outputs'])) if '--max-new-outputs' in values else None
        root, job_id = values['--root'], values['--job-id']
        if action == 'submit':
            body = parse_json(stdin.read(65537))
            if type(body) is not dict or set(body) != {'options', 'schedule_s', 'max_wall_seconds'}:
                _fail('INVALID_REQUEST')
            answer = submit(root, job_id, values['--file'], max_new_outputs=max_new, **body)
        elif action == 'resume':
            answer = resume(root, job_id, max_new_outputs=max_new)
        elif action == 'result':
            answer = dict(schema=SCHEMA, status='ok',
                          result=read_output(root, job_id, int(values.get('--index', '-1'))))
        else:
            answer = globals()[action](root, job_id)
        return answer, 0 if answer.get('job', {}).get('state') != 'failed' else 2
    except Exception as exc:
        return dict(schema=SCHEMA, status='error', error=_safe(exc)), 2


def main(argv=None):
    answer, code = response(sys.argv[1:] if argv is None else argv,
                            getattr(sys.stdin, 'buffer', sys.stdin))
    sys.stdout.buffer.write(_encoded(answer) + b'\n')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
