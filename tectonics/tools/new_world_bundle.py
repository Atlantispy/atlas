"""Portable initial world plus committed regional jobs, without changing producers.

SPDX-License-Identifier: AGPL-3.0-only
Trusted local CLI paths; archive contents are untrusted. No extractall, simulation,
source repinning, destination replacement, automatic resume or process-state copy.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
import zipfile

import new_world as paths
from new_world_contract import ContractError, parse_json
import new_world_project as projects
import new_world_job as job

SCHEMA = 'atlas.world-bundle.v1'
RESPONSE_SCHEMA = 'atlas.world-bundle-response.v1'
MAX_DATA = 256 << 20
MAX_MANIFEST = 2 << 20
MAX_ARCHIVE = MAX_DATA + (4 << 20)
MAX_MEMBERS = 2 + 32 * (4 + 256)
FIXED = ('request.json', 'initial.json', 'prefix.json', 'status.json')
_SELF = Path(__file__).resolve()
_SELF_HASH = hashlib.sha256(_SELF.read_bytes()).hexdigest()
MESSAGES = {
    'INVALID_BUNDLE': 'The combined project is damaged, inconsistent or unsupported.',
    'BUNDLE_LIMIT': 'The combined project exceeds its file, record or total size limit.',
    'BUNDLE_WORLD_MISMATCH': 'A saved run belongs to a different original world.',
    'UNSTABLE_JOB': 'Finish, pause or recover the active run before saving its checkpoint.',
    'INITIAL_INCOMPLETE': 'The run has no complete prepared checkpoint to save.',
    'FILE_EXISTS': 'The destination already exists; nothing was replaced.',
    'SOURCE_MISMATCH': 'The saved code or runtime does not match; no sources were rebound.',
    'RUN_BUSY': 'A selected run is busy; no run was cancelled or changed.',
    'INVALID_REQUEST': 'Use a supported bundle command and distinct saved run IDs.',
    'INVALID_PATH': 'Use an existing safe local parent and a new destination.',
    'UNSAFE_PATH': 'Linked or changed paths are not supported.',
    'INPUT_CHANGED': 'An input changed during the operation; it was not accepted.',
    'BUNDLE_FAILED': 'The local combined project operation failed; keep the current world.',
}


def _fail(code='INVALID_BUNDLE'):
    raise ContractError(code, MESSAGES[code])


def _guard():
    if hashlib.sha256(_SELF.read_bytes()).hexdigest() != _SELF_HASH:
        _fail('SOURCE_MISMATCH')


def _entry(name, body):
    return dict(file=name, size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest())


@contextmanager
def _open(raw_path, maximum):
    path, parents = paths._checked_path(os.fspath(raw_path))
    with paths._Directory(path.parent, parents) as directory:
        info = directory.inspect(path.name)
        if paths._unsafe(info) or not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
            _fail('INVALID_PATH')
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(directory.open(path.name, flags), 'rb') as source:
            opened = os.fstat(source.fileno())
            if paths._identity(opened) != paths._identity(info):
                _fail('INPUT_CHANGED')
            yield source
            after = os.fstat(source.fileno())
            current = directory.inspect(path.name)
            if (paths._unsafe(current) or paths._identity(current) != paths._identity(opened)
                    or (after.st_size, after.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns)):
                _fail('INPUT_CHANGED')
        paths._check_parents(parents)


def _transfer(source, target, maximum):
    """Bounded streaming, hashing the exact transferred bytes, never whole-history RAM."""
    hasher, total = hashlib.sha256(), 0
    while chunk := source.read(65536):
        total += len(chunk)
        if total > maximum:
            _fail('BUNDLE_LIMIT')
        hasher.update(chunk)
        if target is not None:
            target.write(chunk)
    return dict(size_bytes=total, sha256=hasher.hexdigest())


def _copy(source, destination, maximum):
    with _open(source, maximum) as handle, destination.open('xb') as target:
        return _transfer(handle, target, maximum)


def _publish_copy(source, destination, maximum):
    path, parents = paths._checked_path(os.fspath(destination))
    with paths._Directory(path.parent, parents) as directory:
        name = '.world-import-' + secrets.token_hex(16) + '.tmp'
        fd = directory.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0))
        identity = paths._identity(os.fstat(fd))
        try:
            with os.fdopen(fd, 'wb') as output, _open(source, maximum) as handle:
                _transfer(handle, output, maximum)
                output.flush(); os.fsync(output.fileno())
            if paths._identity(directory.inspect(name)) != identity:
                _fail('UNSAFE_PATH')
            directory.publish(name, path.name)
        finally:
            directory.remove_owned(name, identity)


def _job_ids(values):
    if (type(values) not in (list, tuple) or len(values) > job.jobs.MAX_JOBS
            or any(type(v) is not str or not job.jobs.JOB_ID.fullmatch(v) for v in values)
            or len(set(values)) != len(values)):
        _fail('INVALID_REQUEST')
    return sorted(values)


def _json(raw):
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=job.jobs.reader._pairs,
                       parse_constant=job.jobs.reader._constant)
    if job._encoded(value, MAX_MANIFEST) != raw:
        _fail()
    return value


def _validate_job(directory, world, world_entry, sources):
    """Lock-free validator for an owned snapshot; never prepare or evaluate."""
    request, request_sha = job._request(directory)
    if request['input'] != {k: world_entry[k] for k in ('size_bytes', 'sha256')}:
        _fail('BUNDLE_WORLD_MISMATCH')
    if request['sources'] != sources:
        _fail('SOURCE_MISMATCH')
    initial, initial_bytes = job._json(directory / 'initial.json', job.MAX_RECORD)
    prefix, _ = job._prefix(directory, request, request_sha)
    if (hashlib.sha256(initial_bytes).hexdigest() != prefix['initial_sha256']
            or request['schedule_s'][-1] > initial['max_elapsed_s']):
        _fail()
    for key in ('project_id', 'atlas_id', 'structure_id', 'motion_id'):
        if initial.get(key) != world.manifest.get(key) or initial.get(key) is None:
            _fail('BUNDLE_WORLD_MISMATCH')
    if initial.get('plan_id') != world.manifest['plan']['plan_id']:
        _fail('BUNDLE_WORLD_MISMATCH')
    backend = job._backend()
    backend.check_initial(initial)
    n = initial['native_input']
    for entry in prefix['outputs']:
        output, _ = job._json(directory / entry['file'], job.MAX_RECORD)
        result = output['result']
        scientific = {k:v for k,v in result.items() if k not in ('output_id', 'accounted_workspace_peak_bytes')}
        if (backend._digest(scientific) != result['output_id']
                or result.get('schema') != backend.OUTPUT_SCHEMA or result.get('method') != backend.METHOD
                or result.get('initial_id') != initial['initial_id']
                or result.get('project_id') != initial['project_id']
                or result.get('elapsed_s') != entry['elapsed_s']
                or result.get('time_s') != n['epoch_time_s'] + entry['elapsed_s']
                or any(result.get(k) != n[k] for k in ('frame_id','epoch_id','datum_id'))):
            _fail()
    state = job._state(directory)
    if state['state'] in job.ACTIVE:
        _fail('UNSTABLE_JOB')
    if (state.get('producer_id') != job.PRODUCER
            or type(state.get('completed_outputs')) is not int or type(state.get('total_outputs')) is not int
            or state.get('completed_outputs') != len(prefix['outputs'])
            or state.get('total_outputs') != len(request['schedule_s'])
            or (state['state'] == 'completed' and len(prefix['outputs']) != len(request['schedule_s']))):
        _fail()
    for key in ('computed_outputs', 'restored_outputs'):
        if type(state.get(key)) is not int or not 0 <= state[key] <= len(prefix['outputs']):
            _fail()
    if state['computed_outputs'] + state['restored_outputs'] != len(prefix['outputs']):
        _fail('UNSTABLE_JOB')
    if (type(state.get('timings')) is not dict or set(state['timings']) !=
            {'prepare_s','physics_s','store_s','restore_s','elapsed_s'}
            or any(type(v) not in (int,float) or not math.isfinite(v) or v < 0 for v in state['timings'].values())):
        _fail()
    error = state.get('error')
    if error is not None and (type(error) is not dict or set(error) != {'code','message'}
            or error['code'] not in job.MESSAGES or error['message'] != job.MESSAGES[error['code']]):
        _fail()
    return dict(job_id=directory.name, producer_id=job.PRODUCER, state=state['state'],
        attempt=state['attempt'], completed_outputs=len(prefix['outputs']), total_outputs=len(request['schedule_s']),
        requested_elapsed_s=request['schedule_s'], output_ids=[e['output_id'] for e in prefix['outputs']],
        continuation_compatible=True, attempts_remaining=job.MAX_ATTEMPTS-state['attempt'], error=error)


def _summary(manifest, world, states):
    return dict(kind='combined' if manifest else 'initial-only',
        bundle_id=None if manifest is None else manifest['bundle_id'],
        project_id=world.manifest['project_id'], title=world.manifest['title'],
        status='WORKING NON-CANON', jobs=states, generated_on_open=False,
        world_file='world.atlas', jobs_directory='jobs')


def _new_archive(raw_path, staged, manifest):
    path, parents = paths._checked_path(os.fspath(raw_path))
    with paths._Directory(path.parent, parents) as directory:
        name = '.world-bundle-' + secrets.token_hex(16) + '.tmp'
        fd = directory.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0))
        identity = paths._identity(os.fstat(fd))
        try:
            with os.fdopen(fd, 'w+b') as handle:
                with zipfile.ZipFile(handle, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
                    archive.writestr('bundle.json', job._encoded(manifest, MAX_MANIFEST))
                    for entry in [manifest['world']] + [e for j in manifest['jobs'] for e in j['files']]:
                        archive.write(staged / entry['file'], entry['file'])
                size = handle.tell()
                if size > MAX_ARCHIVE:
                    _fail('BUNDLE_LIMIT')
                handle.flush(); os.fsync(handle.fileno())
            _guard()
            if paths._identity(directory.inspect(name)) != identity:
                _fail('UNSAFE_PATH')
            try:
                directory.publish(name, path.name)
            except FileExistsError:
                _fail('FILE_EXISTS')
        finally:
            directory.remove_owned(name, identity)
    return size


def save_bundle(raw_path, world_path, *, jobs_root=None, job_ids=()):
    _guard()
    destination, _ = paths._checked_path(os.fspath(raw_path))
    if destination.exists() or destination.is_symlink():
        _fail('FILE_EXISTS')
    ids = _job_ids(job_ids)
    if ids and jobs_root is None:
        _fail('INVALID_REQUEST')
    with tempfile.TemporaryDirectory(prefix='atlas-bundle-') as tmp:
        staged = Path(tmp)
        world_entry = dict(file='world.atlas', **_copy(world_path, staged/'world.atlas', projects.MAX_PROJECT))
        world = projects.load_project(staged/'world.atlas')
        sources = job._sources(job._backend()) if ids else None
        records, states = [], []
        total = world_entry['size_bytes']
        for ident in ids:
            _, source = job.jobs._paths(jobs_root, ident)
            target = staged / 'jobs' / ident
            target.mkdir(parents=True)
            with job.jobs._lock(source/'worker.lock'):
                if not (source/'initial.json').exists() or not (source/'prefix.json').exists():
                    _fail('INITIAL_INCOMPLETE')
                prefix = job._control_json(source/'prefix.json')
                outputs = prefix.get('outputs')
                if type(outputs) is not list or len(outputs) > job.MAX_OUTPUTS:
                    _fail()
                names = [*FIXED, *(f'output-{i:04d}.json' for i in range(len(outputs)))]
                with _open(source/'input.atlas', projects.MAX_PROJECT) as handle:
                    if _transfer(handle, None, projects.MAX_PROJECT) != {k:world_entry[k] for k in ('size_bytes','sha256')}:
                        _fail('BUNDLE_WORLD_MISMATCH')
                entries = []
                for name in names:
                    info = _copy(source/name, target/name, job.MAX_RECORD if name == 'initial.json' or name.startswith('output-') else 65536)
                    total += info['size_bytes']
                    if total > MAX_DATA:
                        _fail('BUNDLE_LIMIT')
                    entries.append(dict(file=f'jobs/{ident}/{name}', **info))
                states.append(_validate_job(target, world, world_entry, sources))
            records.append(dict(job_id=ident, files=entries))
        if ids and job._sources(job._backend()) != sources:
            _fail('SOURCE_MISMATCH')
        manifest = dict(schema=SCHEMA, status='WORKING NON-CANON', project_id=world.manifest['project_id'],
                        world=world_entry, jobs=records)
        manifest['bundle_id'] = hashlib.sha256(job._encoded(manifest, MAX_MANIFEST)).hexdigest()
        size = _new_archive(raw_path, staged, manifest)
        return dict(_summary(manifest, world, states), archive_bytes=size,
            stored_world_copies=1, avoided_frozen_world_copies=len(ids))


def _manifest(archive):
    manifest = _json(archive.read('bundle.json'))
    if (type(manifest) is not dict or set(manifest) != {'schema','status','project_id','world','jobs','bundle_id'}
            or manifest['schema'] != SCHEMA or manifest['status'] != 'WORKING NON-CANON'
            or not job._hex(manifest['project_id']) or not job._hex(manifest['bundle_id'])
            or manifest['bundle_id'] != hashlib.sha256(job._encoded(
                {k:v for k,v in manifest.items() if k != 'bundle_id'}, MAX_MANIFEST)).hexdigest()
            or type(manifest['world']) is not dict or manifest['world'].get('file') != 'world.atlas'
            or type(manifest['jobs']) is not list):
        _fail()
    ids = _job_ids([j.get('job_id') if type(j) is dict else None for j in manifest['jobs']])
    if ids != [j['job_id'] for j in manifest['jobs']]:
        _fail()
    entries, total = [manifest['world']], 0
    for item in manifest['jobs']:
        if set(item) != {'job_id','files'} or type(item['files']) is not list or not 4 <= len(item['files']) <= 4+job.MAX_OUTPUTS:
            _fail()
        names = [*FIXED, *(f'output-{i:04d}.json' for i in range(len(item['files'])-4))]
        if [e.get('file') if type(e) is dict else None for e in item['files']] != [f"jobs/{item['job_id']}/{n}" for n in names]:
            _fail()
        entries.extend(item['files'])
    for entry in entries:
        if type(entry) is not dict or set(entry) != {'file','size_bytes','sha256'}:
            _fail()
        name = entry['file'].split('/')[-1]
        maximum = projects.MAX_PROJECT if entry['file'] == 'world.atlas' else (
            job.MAX_RECORD if name == 'initial.json' or name.startswith('output-') else 65536)
        if (not job._hex(entry['sha256']) or type(entry['size_bytes']) is not int
                or not 0 < entry['size_bytes'] <= maximum):
            _fail('BUNDLE_LIMIT')
        total += entry['size_bytes']
    if total > MAX_DATA or len(entries)+1 > MAX_MEMBERS:
        _fail('BUNDLE_LIMIT')
    return manifest, entries


def _read_into(raw_path, staged):
    _guard()
    with _open(raw_path, MAX_ARCHIVE) as handle:
        # Bound the central-directory allocation before ZipFile constructs its
        # per-member Python objects. CPython's own bounded EOCD reader supports
        # normal/ZIP64 records; the allowed entry/byte counts remain small here.
        end = zipfile._EndRecData(handle)
        if (end is None or end[zipfile._ECD_ENTRIES_TOTAL] > MAX_MEMBERS
                or end[zipfile._ECD_SIZE] > 4 << 20 or end[zipfile._ECD_DISK_NUMBER] != 0
                or end[zipfile._ECD_DISK_START] != 0):
            _fail('BUNDLE_LIMIT')
        handle.seek(0)
        with zipfile.ZipFile(handle) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or len(names) > MAX_MEMBERS:
                _fail()
            if set(names) == {'project.json','arrays.sqlite'}:
                manifest, entries = None, None
            else:
                if 'bundle.json' not in names:
                    _fail()
                for info in infos:
                    mode = stat.S_IFMT(info.external_attr >> 16)
                    if (info.compress_type != zipfile.ZIP_STORED or info.flag_bits & 1 or info.is_dir()
                            or mode not in (0,stat.S_IFREG) or info.file_size != info.compress_size
                            or not 0 < info.file_size <= (MAX_MANIFEST if info.filename == 'bundle.json' else projects.MAX_PROJECT)):
                        _fail()
                manifest, entries = _manifest(archive)
                if set(names) != {'bundle.json', *(e['file'] for e in entries)}:
                    _fail()
                for entry in entries:
                    info = archive.getinfo(entry['file'])
                    if info.file_size != entry['size_bytes']:
                        _fail()
                    target = staged/entry['file']
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open('xb') as output:
                        found = _transfer(source, output, entry['size_bytes'])
                    if found != {k:entry[k] for k in ('size_bytes','sha256')}:
                        _fail()
        if manifest is None:
            handle.seek(0)
            with (staged/'world.atlas').open('xb') as output:
                found = _transfer(handle, output, projects.MAX_PROJECT)
            world_entry = dict(file='world.atlas', **found)
        else:
            world_entry = manifest['world']
    world = projects.load_project(staged/'world.atlas')
    if manifest is not None and world.manifest['project_id'] != manifest['project_id']:
        _fail('BUNDLE_WORLD_MISMATCH')
    states = []
    if manifest is not None and manifest['jobs']:
        sources = job._sources(job._backend())
        for item in manifest['jobs']:
            directory = staged/'jobs'/item['job_id']
            states.append(_validate_job(directory, world, world_entry, sources))
            prefix = job._control_json(directory/'prefix.json')
            if len(item['files']) != 4 + len(prefix['outputs']):
                _fail()
        if job._sources(job._backend()) != sources:
            _fail('SOURCE_MISMATCH')
    _guard()
    return manifest, world, states


def inspect_bundle(raw_path):
    with tempfile.TemporaryDirectory(prefix='atlas-bundle-read-') as tmp:
        manifest, world, states = _read_into(raw_path, Path(tmp))
        return _summary(manifest, world, states)


def load_bundle(raw_path, new_directory):
    """Validate first; publish into an exclusively created managed directory.

    ready.json is last. Callers adopt the new world only after successful return.
    Failed publication removes only our unchanged owned files/empty directories;
    it never recursively deletes an arbitrary destination or changes old worlds.
    """
    target, parents = paths._checked_path(os.fspath(new_directory))
    if target.exists() or target.is_symlink():
        _fail('FILE_EXISTS')
    with tempfile.TemporaryDirectory(prefix='atlas-bundle-read-') as tmp:
        staged = Path(tmp)
        manifest, world, states = _read_into(raw_path, staged)
        answer = _summary(manifest, world, states)
        owned_files, owned_dirs = [], []
        def folder(path):
            path.mkdir()
            owned_dirs.append((path, paths._identity(path.lstat())))
        def publish(source, destination, limit):
            # Publication is exclusive and fsynced. A single source archive is
            # copied into each job's native frozen-input slot on restoration.
            _publish_copy(source, destination, limit)
            info = destination.lstat()
            owned_files.append((destination, (paths._identity(info), info.st_size, info.st_mtime_ns)))
        try:
            paths._check_parents(parents)
            folder(target)
            folder(target/'jobs')
            publish(staged/'world.atlas', target/'world.atlas', projects.MAX_PROJECT)
            if manifest:
                for item in manifest['jobs']:
                    destination = target/'jobs'/item['job_id']
                    folder(destination)
                    for entry in item['files']:
                        publish(staged/entry['file'], target/entry['file'], entry['size_bytes'])
                    publish(staged/'world.atlas', destination/'input.atlas', projects.MAX_PROJECT)
            _guard()
            job._publish(target/'ready.json', job._encoded(answer, MAX_MANIFEST))
        except BaseException:
            for path, expected in reversed(owned_files):
                try:
                    paths._check_parents(parents)
                    # Do not follow a replaced ancestor during rollback.
                    for folder_path, folder_identity in owned_dirs:
                        folder_info = folder_path.lstat()
                        if (paths._unsafe(folder_info) or not stat.S_ISDIR(folder_info.st_mode)
                                or paths._identity(folder_info) != folder_identity):
                            _fail('UNSAFE_PATH')
                    info = path.lstat()
                    if not paths._unsafe(info) and (paths._identity(info),info.st_size,info.st_mtime_ns) == expected:
                        path.unlink()
                except (OSError, ContractError):
                    pass
            for path, identity in reversed(owned_dirs):
                try:
                    paths._check_parents(parents)
                    # _checked_path rejects a substituted symlink/reparse parent.
                    paths._checked_path(os.fspath(path))
                    info = path.lstat()
                    if not paths._unsafe(info) and paths._identity(info) == identity:
                        path.rmdir()  # Refuses unexpected contents; never recursive.
                except (OSError, ContractError):
                    pass
            raise
    return answer


def response(argv, stdin):
    try:
        if not argv or len(argv[1:]) % 2:
            _fail('INVALID_REQUEST')
        action, flags = argv[0], argv[1:]
        values = dict(zip(flags[::2],flags[1::2]))
        if len(values)*2 != len(flags):
            _fail('INVALID_REQUEST')
        if action == 'save' and set(values) in ({'--file','--world'}, {'--file','--world','--root'}):
            body = parse_json(stdin.read(65537))
            if type(body) is not dict or set(body) != {'job_ids'}:
                _fail('INVALID_REQUEST')
            result = save_bundle(values['--file'], values['--world'], jobs_root=values.get('--root'), job_ids=body['job_ids'])
        elif action == 'load' and set(values) == {'--file','--directory'}:
            result = load_bundle(values['--file'], values['--directory'])
        elif action == 'inspect' and set(values) == {'--file'}:
            result = inspect_bundle(values['--file'])
        else:
            _fail('INVALID_REQUEST')
        return dict(schema=RESPONSE_SCHEMA, status='ok', data=result), 0
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code not in MESSAGES:
            code = 'FILE_EXISTS' if isinstance(exc, FileExistsError) else 'BUNDLE_FAILED'
        return dict(schema=RESPONSE_SCHEMA,status='error',error=dict(code=code,message=MESSAGES[code])), 2


def main(argv=None):
    answer, code = response(sys.argv[1:] if argv is None else argv, sys.stdin.buffer)
    print(json.dumps(answer, sort_keys=True, allow_nan=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
