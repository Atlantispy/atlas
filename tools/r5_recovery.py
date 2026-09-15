#!/usr/bin/env python3
"""Offline, byte-preserving recovery bundles for explicitly selected Atlas R5 controls.

Standard library only; never imports Atlas, decodes frames, loads native libraries,
changes checkpoints, follows links, deletes stores or restores over live paths.
A verified bundle establishes byte integrity in an operator-declared scope, not
native runtime compatibility, dependency closure or scientific acceptance.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
from typing import Any, Callable, Iterator

PLAN_SCHEMA = 'atlas.r5-recovery-plan.v1'
BUNDLE_SCHEMA = 'atlas.r5-recovery-bundle.v1'
CONTROL_SCHEMA = 'diadem.native-shared-history-controls.r5'
STORE_SCHEMA = 'diadem.native-shared-history-store.r5'
REF_SCHEMA = 'diadem.shared-native-history-reference.r5'
RAW_SCHEMA = 'diadem.canonical-json-record.r1'
MAX_JSON = 64 * 1024 * 1024
MAX_CONTROL = 32 * 1024 * 1024
MAX_FILES = 200_000
BLOCK = 1024 * 1024
ROLES = {'source', 'runtime', 'inputs', 'provenance'}
HEX = re.compile(r'[0-9a-f]{64}\Z')
ALIAS = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')
RESERVED = {'con', 'prn', 'aux', 'nul', 'clock$', 'conin$', 'conout$',
            *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}
BOUNDARY = {
    'verification': 'byte-integrity-only',
    'dependency_scope': 'operator-declared-not-proven-complete',
    'native_runtime_verified': False,
    'checkpoint_bindings_changed': False,
    'scientific_acceptance': False,
}


class RecoveryError(ValueError):
    """Invalid, changed, unsafe or incomplete recovery input."""


def _keys(value: Any, keys: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise RecoveryError(f'{label}: unexpected or missing fields')
    return value


def _sha(value: Any) -> str:
    if type(value) is not str or not HEX.fullmatch(value):
        raise RecoveryError('expected a lowercase SHA256 digest')
    return value


def _integer(value: Any, lower: int, upper: int) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise RecoveryError('integer outside the explicit bound')
    return value


def encoded(value: Any) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise RecoveryError('invalid JSON value') from exc
    if len(raw) > MAX_JSON:
        raise RecoveryError('metadata exceeds byte limit')
    return raw


def decoded(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise RecoveryError('duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise RecoveryError('non-finite JSON number')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)
        encoded(value)  # Also rejects non-finite numbers produced by exponent overflow.
        return value
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise RecoveryError('invalid, ambiguous or over-deep JSON') from exc


def _relative(value: Any, *, allow_root: bool = False) -> str:
    if allow_root and value == '.':
        return value
    if type(value) is not str or not value or len(value) > 4096:
        raise RecoveryError('invalid relative path')
    parts = value.split('/')
    for part in parts:
        if (part in ('', '.', '..') or part[-1:] in (' ', '.')
                or any(ord(c) < 32 or c in '\\:<>"|?*' for c in part)
                or part.split('.')[0].casefold() in RESERVED):
            raise RecoveryError('unsafe or non-portable relative path')
    return value


def _safe(path: Path, *, exists: bool = True, directory: bool = False) -> Path:
    # Check lexical components before resolution; resolving first hides links.
    path = Path(path).absolute()
    if '..' in path.parts:
        raise RecoveryError('parent traversal refused')
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        if ':' in part or part.endswith((' ', '.')):
            raise RecoveryError('alternate stream or ambiguous path refused')
        cursor /= part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            if exists or cursor != path:
                raise RecoveryError('required path or parent is missing') from None
            return path
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RecoveryError('symlink or Windows reparse point refused')
        if cursor != path and not stat.S_ISDIR(info.st_mode):
            raise RecoveryError('parent is not a directory')
    if exists:
        info = path.lstat()
        wanted = stat.S_ISDIR if directory else stat.S_ISREG
        if not wanted(info.st_mode):
            raise RecoveryError('expected directory' if directory else 'expected regular file')
    return path


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def _reader(path: Path) -> Iterator[Any]:
    path = _safe(path)
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or _stamp(os.fstat(stream.fileno())) != _stamp(before):
            raise RecoveryError('source changed before reading')
        yield stream
        if _stamp(os.fstat(stream.fileno())) != _stamp(before) or _stamp(_safe(path).lstat()) != _stamp(before):
            raise RecoveryError('source changed during reading')


def _read(path: Path, limit: int = MAX_JSON) -> bytes:
    with _reader(path) as stream:
        if os.fstat(stream.fileno()).st_size > limit:
            raise RecoveryError('file exceeds byte limit')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise RecoveryError('file exceeds byte limit')
    return raw


def _hash(path: Path, destination: Path | None = None) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    # Destination is always an exclusive file in our new, private staging directory.
    output = None
    try:
        if destination is not None:
            output = destination.open('xb')
        with _reader(path) as stream:
            while chunk := stream.read(BLOCK):
                size += len(chunk)
                digest.update(chunk)
                if output is not None:
                    output.write(chunk)
        if output is not None:
            output.flush()
            os.fsync(output.fileno())
    finally:
        if output is not None:
            output.close()
    return digest.hexdigest(), size


def _pure(value: Any):
    if type(value) is not str:
        raise RecoveryError('root/store location must be a string')
    path = PureWindowsPath(value) if PureWindowsPath(value).is_absolute() else PurePosixPath(value)
    if not path.is_absolute() or '..' in path.parts:
        raise RecoveryError('explicit absolute location required')
    # Relative suffix restrictions also exclude device paths, ADS and ambiguities.
    if len(path.parts) > 1:
        _relative('/'.join(path.parts[1:]))
    if str(path).startswith(('\\\\?\\', '\\\\.\\')):
        raise RecoveryError('device namespace refused')
    return path


def _selector(value: Any, roots: dict) -> tuple[str, str]:
    _keys(value, {'root', 'path'}, 'selection')
    if type(value['root']) is not str or value['root'] not in roots:
        raise RecoveryError('unknown root alias')
    return value['root'], _relative(value['path'], allow_root=True)


def validate_plan(plan: Any, *, local: bool) -> dict:
    _keys(plan, {'schema', 'roots', 'controls', 'dependencies'}, 'plan')
    if plan['schema'] != PLAN_SCHEMA or type(plan['roots']) is not dict or not plan['roots']:
        raise RecoveryError('unsupported plan or empty roots')
    roots = plan['roots']
    pure = []
    for alias, location in roots.items():
        if type(alias) is not str or not ALIAS.fullmatch(alias) or alias in RESERVED:
            raise RecoveryError('invalid root alias')
        path = _pure(location)
        if any(type(path) is type(old) and (path == old or path in old.parents or old in path.parents) for old in pure):
            raise RecoveryError('root aliases must be disjoint, not overlapping')
        pure.append(path)
        if local:
            if not Path(location).is_absolute():
                raise RecoveryError('foreign-platform root; use the original environment, do not rebind')
            _safe(Path(location), directory=True)
    controls = plan['controls']
    if type(controls) is not list or not 1 <= len(controls) <= MAX_FILES:
        raise RecoveryError('explicit nonempty control list required')
    selected = [_selector(item, roots) for item in controls]
    if any(path == '.' for _, path in selected) or len(set(selected)) != len(selected):
        raise RecoveryError('duplicate or invalid control selection')
    deps = _keys(plan['dependencies'], ROLES, 'dependency coverage')
    for role, record in deps.items():
        _keys(record, {'paths', 'note'}, 'dependency declaration')
        if type(record['note']) is not str or not record['note'].strip():
            raise RecoveryError('each dependency role needs an operator explanation')
        if type(record['paths']) is not list or (not record['paths'] and role != 'inputs'):
            raise RecoveryError('source, runtime and provenance files must be explicitly selected')
        for item in record['paths']:
            _selector(item, roots)
    return plan


def _source(roots: dict, key: tuple[str, str]) -> Path:
    alias, relative = key
    return Path(roots[alias]) / relative


def _location(roots: dict, absolute: str) -> tuple[str, str]:
    target = _pure(absolute)
    for alias, root in roots.items():
        base = _pure(root)
        if type(base) is type(target) and (target == base or base in target.parents):
            return alias, _relative(target.relative_to(base).as_posix(), allow_root=True)
    raise RecoveryError('referenced dependency lies outside the explicitly allowed roots')


def _store(record: dict, key: tuple[str, str], roots: dict) -> tuple[str, str]:
    _keys(record, {'schema', 'path'}, 'history store')
    if record['schema'] != STORE_SCHEMA:
        raise RecoveryError('unsupported store schema')
    if record['path'] == 'store':
        return key[0], (PurePosixPath(key[1]).parent / 'store').as_posix()
    return _location(roots, record['path'])


def _control(raw: bytes, key: tuple[str, str], roots: dict,
             frame: Callable[[tuple[str, str], str, int], None]) -> dict:
    if len(raw) > MAX_CONTROL:
        raise RecoveryError('control exceeds byte limit')
    data = decoded(raw)
    _keys(data, {'storage_schema', 'execution_binding', 'wrapper', 'history_refs', 'history_store'}, 'control')
    if data['storage_schema'] != CONTROL_SCHEMA:
        raise RecoveryError('only explicit R5 controls are supported; no migration')
    wrapper = data['wrapper']
    if (type(data['execution_binding']) is not dict or type(wrapper) is not dict
            or type(wrapper.get('envelope')) is not dict
            or type(wrapper['envelope'].get('body')) is not dict
            or 'history' in wrapper['envelope']['body']):
        raise RecoveryError('invalid control wrapper or duplicate inline history')
    store = _store(data['history_store'], key, roots)
    refs = data['history_refs']
    if type(refs) is not list or len(refs) > 256:
        raise RecoveryError('R5 history exceeds retained 256-reference boundary')
    codec = None
    for sequence, ref in enumerate(refs, 1):
        _keys(ref, {'schema', 'sequence', 'path', 'raw_sha256', 'raw_size_bytes',
                    'frame_sha256', 'frame_size_bytes', 'storage_schema', 'storage_size_bytes', 'summary', 'codec'}, 'history reference')
        digest = _sha(ref['frame_sha256'])
        _sha(ref['raw_sha256'])
        if (ref['schema'] != REF_SCHEMA or type(ref['sequence']) is not int or ref['sequence'] != sequence
                or ref['path'] != f'objects/{digest}.zst' or ref['storage_schema'] != RAW_SCHEMA):
            raise RecoveryError('history sequence, schema or content-addressed path differs')
        size = _integer(ref['raw_size_bytes'], 1, 32 * 1024 * 1024)
        if type(ref['storage_size_bytes']) is not int or ref['storage_size_bytes'] != size:
            raise RecoveryError('logical and storage size differ')
        compressed = _integer(ref['frame_size_bytes'], 1, 64 * 1024 * 1024)
        if type(ref['codec']) is not dict or type(ref['summary']) is not dict or len(encoded(ref['summary'])) > 64 * 1024:
            raise RecoveryError('invalid codec or summary metadata')
        current_codec = encoded(ref['codec'])
        if codec is not None and current_codec != codec:
            raise RecoveryError('mixed codec identities in one history')
        codec = current_codec
        relative = (PurePosixPath(store[1]) / ref['path']).as_posix()
        frame((store[0], relative), digest, compressed)
    return {'root': key[0], 'path': key[1], 'store': {'root': store[0], 'path': store[1]},
            'history_references': len(refs),
            'execution_binding_sha256': hashlib.sha256(encoded(data['execution_binding'])).hexdigest()}


def _walk(path: Path) -> list[Path]:
    _safe(path, exists=False)
    info = path.lstat()
    if stat.S_ISREG(info.st_mode):
        return [_safe(path)]
    _safe(path, directory=True)
    result, pending, visited = [], [path], 0
    while pending:
        directory = _safe(pending.pop(), directory=True)
        children = []
        with os.scandir(directory) as entries:
            for entry in entries:
                visited += 1
                if visited > MAX_FILES:
                    raise RecoveryError('dependency tree exceeds file/directory bound')
                children.append(entry)
        for entry in sorted(children, key=lambda entry: entry.name):
            child = Path(entry.path)
            _safe(child, exists=False)
            info = child.lstat()
            if stat.S_ISDIR(info.st_mode):
                pending.append(child)
            elif stat.S_ISREG(info.st_mode):
                result.append(child)
            else:
                raise RecoveryError('non-regular dependency refused')
    if not result:
        raise RecoveryError('empty dependency directory does not establish coverage')
    return sorted(result)


def _no_writer_locks(plan: dict) -> None:
    for item in plan['controls']:
        path = _source(plan['roots'], _selector(item, plan['roots']))
        lock = path.with_name(path.name + '.lock')
        if os.path.lexists(lock):
            raise RecoveryError('R5 writer lock present; stop and investigate, never remove automatically')


def inventory(plan: dict) -> dict:
    validate_plan(plan, local=True)
    _no_writer_locks(plan)
    roots, files = plan['roots'], {}

    def add(key, role, expected_sha=None, expected_size=None):
        _relative(key[1])
        if key not in files:
            if len(files) >= MAX_FILES:
                raise RecoveryError('inventory exceeds file bound')
            digest, size = _hash(_source(roots, key))
            files[key] = {'root': key[0], 'path': key[1], 'sha256': digest, 'size_bytes': size, 'roles': []}
        entry = files[key]
        if expected_sha is not None and (entry['sha256'], entry['size_bytes']) != (expected_sha, expected_size):
            raise RecoveryError('referenced immutable frame hash/size differs')
        if role not in entry['roles']:
            entry['roles'].append(role)
            entry['roles'].sort()

    controls = []
    for item in plan['controls']:
        key = _selector(item, roots)
        raw = _read(_source(roots, key), MAX_CONTROL)
        add(key, 'control', hashlib.sha256(raw).hexdigest(), len(raw))
        record = _control(raw, key, roots, lambda k, h, n: add(k, 'frame', h, n))
        # Even an empty history depends on the declared store directory.
        _safe(_source(roots, (record['store']['root'], record['store']['path'])), directory=True)
        controls.append(record)
    for role, declaration in plan['dependencies'].items():
        for selected in declaration['paths']:
            alias, relative = _selector(selected, roots)
            for path in _walk(_source(roots, (alias, relative))):
                rel = path.relative_to(Path(roots[alias])).as_posix()
                add((alias, rel), role)
    result = {'schema': BUNDLE_SCHEMA, 'boundary': dict(BOUNDARY), 'plan': plan,
              'controls': controls, 'files': [files[key] for key in sorted(files)]}
    index = _file_index(result)
    for record in controls:
        raw = _read(_source(roots, (record['root'], record['path'])), MAX_CONTROL)
        if hashlib.sha256(raw).hexdigest() != index[(record['root'], record['path'])]['sha256']:
            raise RecoveryError('control changed during dependency inventory')
        record['dependency_pins'] = _dependency_pins(raw, roots, index)
    _no_writer_locks(plan)
    return result


def _file_index(manifest: Any) -> dict:
    _keys(manifest, {'schema', 'boundary', 'plan', 'controls', 'files'}, 'bundle manifest')
    if manifest['schema'] != BUNDLE_SCHEMA or manifest['boundary'] != BOUNDARY:
        raise RecoveryError('unsupported bundle schema or overstated validation boundary')
    plan = validate_plan(manifest['plan'], local=False)
    entries = manifest['files']
    if type(entries) is not list or not 1 <= len(entries) <= MAX_FILES:
        raise RecoveryError('invalid file inventory')
    result, portable = {}, set()
    for entry in entries:
        _keys(entry, {'root', 'path', 'sha256', 'size_bytes', 'roles'}, 'file entry')
        key = _selector({'root': entry['root'], 'path': entry['path']}, plan['roots'])
        _relative(key[1])
        _sha(entry['sha256'])
        _integer(entry['size_bytes'], 0, 2**63 - 1)
        roles = entry['roles']
        if (type(roles) is not list or not roles or any(type(role) is not str or role not in ROLES | {'control', 'frame'} for role in roles)
                or len(set(roles)) != len(roles)):
            raise RecoveryError('invalid file role')
        folded = (key[0], unicodedata.normalize('NFC', key[1]).casefold())
        if key in result or folded in portable:
            raise RecoveryError('duplicate or case/Unicode-ambiguous destination')
        result[key] = entry
        portable.add(folded)
    for alias, relative in portable:
        if any((alias, parent.as_posix()) in portable for parent in PurePosixPath(relative).parents if parent != PurePosixPath('.')):
            raise RecoveryError('file/directory prefix collision')
    for item in plan['controls']:
        key = _selector(item, plan['roots'])
        if key not in result or 'control' not in result[key]['roles']:
            raise RecoveryError('selected control missing from manifest')
    for role, declaration in plan['dependencies'].items():
        for selected in declaration['paths']:
            alias, relative = _selector(selected, plan['roots'])
            if not any(a == alias and (relative == '.' or p == relative or p.startswith(relative + '/')) and role in row['roles']
                       for (a, p), row in result.items()):
                raise RecoveryError('declared dependency has no inventoried file')
    return result



def _dependency_pins(raw: bytes, roots: dict, index: dict) -> dict:
    """Check recognised absolute source/library pins without reading new paths.

    Relative native source maps and other binding formats remain unresolved.
    This supplements byte recovery; it deliberately does not impersonate Atlas's
    source/runtime validators or rewrite an old path to a new source installation.
    """
    pending, checked, relative, visited = [decoded(raw)], set(), 0, 0
    while pending:
        node = pending.pop()
        visited += 1
        if visited > MAX_FILES:
            raise RecoveryError('binding metadata exceeds traversal bound')
        if type(node) is list:
            pending.extend(node)
            continue
        if type(node) is not dict:
            continue
        pins = []
        sources = node.get('sources')
        if type(sources) is dict:
            for location, expected in sources.items():
                if type(expected) is str and HEX.fullmatch(expected):
                    if PurePosixPath(location).is_absolute() or PureWindowsPath(location).is_absolute():
                        pins.append((location, expected))
                    else:
                        relative += 1
        if 'library_path' in node and 'library_sha256' in node:
            pins.append((node['library_path'], _sha(node['library_sha256'])))
        for location, expected in pins:
            key = _location(roots, location)
            entry = index.get(key)
            if entry is None:
                raise RecoveryError('a recognised bound source/library is not in the selected dependencies')
            if entry['sha256'] != expected:
                raise RecoveryError('a recognised source/library hash pin differs; never repin')
            checked.add((key, expected))
        pending.extend(node.values())
    return {'recognised_absolute_pins_verified': len(checked),
            'relative_source_pins_not_resolved': relative,
            'full_native_binding_validation_performed': False}


def _write(path: Path, raw: bytes) -> None:
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _disjoint(destination: Path, sources: list[Path]) -> None:
    for source in sources:
        if source == destination or source in destination.parents or destination in source.parents:
            raise RecoveryError('destination must be outside all source roots/bundles')


@contextmanager
def _publication(destination: Path, sources: list[Path]):
    destination = _safe(destination, exists=False)
    _disjoint(destination, sources)
    if os.path.lexists(destination):
        raise RecoveryError('destination already exists; overwrite is never permitted')
    lock = destination.with_name(destination.name + '.recovery-lock')
    token = os.urandom(32)
    _write(lock, token)  # Exclusive; a stale lock is not deleted by a later run.
    staging = None
    try:
        if os.path.lexists(destination):
            raise RecoveryError('destination appeared before staging')
        staging = Path(tempfile.mkdtemp(prefix='.' + destination.name + '.incomplete-', dir=destination.parent))
        yield staging
        _safe(destination, exists=False)
        if os.path.lexists(destination):
            raise RecoveryError('destination appeared before publication')
        # The lock serialises this tool's writers. Do not run against hostile or
        # concurrently modified directory trees; this is not an OS snapshot API.
        os.rename(staging, destination)
        staging = None
    finally:
        # Failed candidates deliberately remain visibly incomplete for inspection.
        # No source or partial recovery data is automatically deleted.
        if _read(lock, 32) != token:
            raise RecoveryError('publication lock changed; retained for investigation')
        lock.unlink()


def _blob(bundle: Path, digest: str) -> Path:
    return bundle / 'blobs' / _sha(digest)


def verify(bundle: Path, expected_manifest_sha256: str) -> dict:
    bundle = _safe(bundle, directory=True)
    expected = _sha(expected_manifest_sha256)
    raw = _read(bundle / 'MANIFEST.json')
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RecoveryError('manifest differs from separately retained SHA256')
    manifest = decoded(raw)
    index = _file_index(manifest)
    marker = decoded(_read(bundle / 'COMPLETE.json'))
    if marker != {'schema': BUNDLE_SCHEMA, 'manifest_sha256': expected}:
        raise RecoveryError('bundle is incomplete or completion marker differs')
    seen = {}
    for entry in index.values():
        digest, size = entry['sha256'], entry['size_bytes']
        if digest not in seen:
            seen[digest] = _hash(_blob(bundle, digest))
        if seen[digest] != (digest, size):
            raise RecoveryError('backup blob missing, corrupt or inconsistent in size')
    def frame(key, digest, size):
        item = index.get(key)
        if item is None or 'frame' not in item['roles'] or (item['sha256'], item['size_bytes']) != (digest, size):
            raise RecoveryError('control references a missing or mismatched stored frame')
    records = []
    for selected in manifest['plan']['controls']:
        key = _selector(selected, manifest['plan']['roots'])
        raw_control = _read(_blob(bundle, index[key]['sha256']), MAX_CONTROL)
        record = _control(raw_control, key, manifest['plan']['roots'], frame)
        record['dependency_pins'] = _dependency_pins(raw_control, manifest['plan']['roots'], index)
        records.append(record)
    if encoded(records) != encoded(manifest['controls']):
        raise RecoveryError('control inventory does not match the original control bytes')
    return manifest


def backup(plan: dict, destination: Path, *, quiescent: bool = False) -> dict:
    if not quiescent:
        raise RecoveryError('explicit --quiescent confirmation required after stopping writers')
    manifest = inventory(plan)
    raw = encoded(manifest)
    digest = hashlib.sha256(raw).hexdigest()
    sources = [Path(location).absolute() for location in plan['roots'].values()]
    unique = {entry['sha256']: entry for entry in manifest['files']}
    destination = _safe(destination, exists=False)
    required = sum(item['size_bytes'] for item in unique.values()) + len(raw) + BLOCK
    if shutil.disk_usage(destination.parent).free < required:
        raise RecoveryError('insufficient free space for the selected backup bytes')
    with _publication(destination, sources) as staging:
        (staging / 'blobs').mkdir()
        for item in unique.values():
            source = _source(plan['roots'], (item['root'], item['path']))
            if _hash(source, _blob(staging, item['sha256'])) != (item['sha256'], item['size_bytes']):
                raise RecoveryError('source changed while copying; candidate not published')
        _write(staging / 'MANIFEST.json', raw)
        _write(staging / 'COMPLETE.json', encoded({'schema': BUNDLE_SCHEMA, 'manifest_sha256': digest}))
        verify(staging, digest)
        # Re-enumeration detects selected-directory membership and control changes,
        # not only modified files. Writers must remain stopped until publication.
        if inventory(plan) != manifest:
            raise RecoveryError('selected sources changed during backup; candidate not published')
    return {'manifest_sha256': digest, 'files': len(manifest['files']), 'unique_blobs': len(unique),
            'unique_bytes': sum(item['size_bytes'] for item in unique.values()), 'boundary': dict(BOUNDARY)}


def restore(bundle: Path, destination: Path, expected_manifest_sha256: str) -> dict:
    manifest = verify(bundle, expected_manifest_sha256)
    bundle = _safe(bundle, directory=True)
    destination = _safe(destination, exists=False)
    sources = [bundle]
    # Same-platform original roots are also forbidden destinations. Foreign root
    # strings are audit metadata only and are never used as restoration targets.
    sources += [Path(root).absolute() for root in manifest['plan']['roots'].values() if Path(root).is_absolute()]
    required = sum(item['size_bytes'] for item in manifest['files']) + BLOCK
    if shutil.disk_usage(destination.parent).free < required:
        raise RecoveryError('insufficient free space for restored independent files')
    with _publication(destination, sources) as staging:
        for alias in manifest['plan']['roots']:
            (staging / alias).mkdir()
        for item in manifest['files']:
            target = staging / item['root'] / item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            if _hash(_blob(bundle, item['sha256']), target) != (item['sha256'], item['size_bytes']):
                raise RecoveryError('backup changed during restoration; candidate not published')
        # Preserve empty referenced stores too; never manufacture a missing frame.
        for item in manifest['controls']:
            (staging / item['store']['root'] / item['store']['path']).mkdir(parents=True, exist_ok=True)
        for item in manifest['files']:
            if _hash(staging / item['root'] / item['path']) != (item['sha256'], item['size_bytes']):
                raise RecoveryError('restored bytes differ')
        verify(bundle, expected_manifest_sha256)
        _write(staging / 'RESTORE_RECEIPT.json', encoded({
            'schema': 'atlas.r5-staged-restore.v1', 'manifest_sha256': expected_manifest_sha256,
            'files_verified': len(manifest['files']), 'original_locations': manifest['plan']['roots'],
            'boundary': dict(BOUNDARY), 'live_integration_performed': False}))
    return {'files_verified': len(manifest['files']), 'boundary': dict(BOUNDARY), 'live_integration_performed': False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('inventory', 'backup'):
        command = sub.add_parser(name)
        command.add_argument('--plan', required=True, type=Path)
        if name == 'backup':
            command.add_argument('--destination', required=True, type=Path)
            command.add_argument('--quiescent', action='store_true', help='Confirm all selected writers remain stopped')
    for name in ('verify', 'restore'):
        command = sub.add_parser(name)
        command.add_argument('--bundle', required=True, type=Path)
        command.add_argument('--expected-manifest-sha256', required=True)
        if name == 'restore':
            command.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command in ('inventory', 'backup'):
            plan = decoded(_read(args.plan))
            result = inventory(plan) if args.command == 'inventory' else backup(plan, args.destination, quiescent=args.quiescent)
        else:
            if args.command == 'restore':
                result = restore(args.bundle, args.destination, args.expected_manifest_sha256)
            else:
                manifest = verify(args.bundle, args.expected_manifest_sha256)
                result = {'files_verified': len(manifest['files']), 'boundary': manifest['boundary']}
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (RecoveryError, OSError) as exc:
        print(f'R5 recovery refused: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
