"""Portable native world projects; no simulation on reopening.

SPDX-License-Identifier: AGPL-3.0-only

The ZIP container is uncompressed: native ArrayStore already compresses arrays.
Only two fixed members are read; no archive paths are extracted. This is a
trusted-local-file adapter, not a hostile concurrent-filesystem sandbox.
Layout-only saves retain the original v1 manifest. A v2 manifest adds exactly
structure_id and stores the initial structure beside the atlas in arrays.sqlite.
Legacy v1 projects never acquire invented crust or thermal fields on reopening.
Version 3 adds motion_id only when native structure and motion are both present;
its complete layout report is a bounded, content-addressed native-store receipt.
Existing v3 inline reports remain readable. All versions retain the same bounded
archive/store format; no scientific report fields are truncated.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import stat
import sys
import tempfile
import zipfile

from new_world import _checked_path, _Directory, _identity, _unsafe, _check_parents
from new_world_contract import ContractError, canonical_bytes, parse_json, validate_plan

SCHEMA = 'atlas.new-world-project.v1'
STRUCTURE_SCHEMA = 'atlas.new-world-project.v2'
MOTION_SCHEMA = 'atlas.new-world-project.v3'
REPORT_SCHEMA = 'atlas.layout-candidate-report-reference.v1'
MAX_STORE = 64 << 20
MAX_JSON = 64 << 10
MAX_REPORT = 1 << 20
MAX_NATIVE_METADATA = 2 << 20
MAX_PROJECT = MAX_STORE + MAX_JSON + 4096


@dataclass(frozen=True, slots=True)
class SavedProject:
    manifest: dict
    atlas: object
    configuration_compatible: bool
    structure: object | None = None
    motion: object | None = None


def _fail(message):
    raise ContractError('INVALID_PROJECT', message)


def _digest(record):
    return hashlib.sha256(canonical_bytes(record)).hexdigest()


def _file_digest(path):
    with open(path, 'rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _native():
    # The existing configuration CLI remains stdlib-only.
    source = str(Path(__file__).resolve().parents[1] / 'src')
    if source not in sys.path:
        sys.path.insert(0, source)
    from atlas_tectonics import save_spherical_atlas, load_spherical_atlas
    from atlas_tectonics.storage import ArrayStore, StoreLimits
    # Native topology descriptors have a separate bounded metadata envelope;
    # this does not enlarge project.json or the total retained store.
    limits = StoreLimits(65536, 16 << 20, MAX_STORE, max_manifest_bytes=MAX_NATIVE_METADATA)
    return ArrayStore, limits, save_spherical_atlas, load_spherical_atlas


def _report_bytes(report):
    """Finite plain JSON with an independent receipt bound, not the S1 limit."""
    remaining = 100000

    def visit(value, depth):
        nonlocal remaining
        remaining -= 1
        if depth > 16 or remaining < 0:
            _fail('The layout report exceeds its bounded JSON structure.')
        if value is None or type(value) is bool:
            return
        if type(value) is str:
            if len(value) > MAX_REPORT:
                _fail('The layout report exceeds 1 MiB.')
        elif type(value) is int:
            if value.bit_length() > 256:
                _fail('The layout report contains an unsupported integer.')
        elif type(value) is float:
            if not math.isfinite(value):
                _fail('The layout report contains a non-finite number.')
        elif type(value) is dict:
            for key, child in value.items():
                if type(key) is not str:
                    _fail('The layout report requires string object keys.')
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(value) is list:
            for child in value:
                visit(child, depth + 1)
        else:
            _fail('The layout report requires plain JSON values.')

    visit(report, 0)
    body = bytearray()
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'),
                               ensure_ascii=True, allow_nan=False)
    for part in encoder.iterencode(report):
        chunk = part.encode('ascii')
        if len(body) + len(chunk) > MAX_REPORT:
            _fail('The layout report exceeds 1 MiB.')
        body.extend(chunk)
    return bytes(body)


def _save_report(body, store):
    import numpy as np
    reference = dict(schema=REPORT_SCHEMA, report_id=hashlib.sha256(body).hexdigest(),
                     size_bytes=len(body))
    store.put(reference['report_id'], {'receipt': np.frombuffer(body, dtype='u1')}, reference)
    return reference


def _load_report(reference, store):
    import numpy as np
    if (type(reference) is not dict or set(reference) != {'schema', 'report_id', 'size_bytes'}
            or reference['schema'] != REPORT_SCHEMA
            or type(reference['report_id']) is not str or len(reference['report_id']) != 64
            or any(c not in '0123456789abcdef' for c in reference['report_id'])
            or type(reference['size_bytes']) is not int
            or not 0 < reference['size_bytes'] <= MAX_REPORT
            or store.metadata(reference['report_id']) != reference):
        _fail('Invalid layout report receipt reference.')
    body = bytearray()
    # Stream bounded chunks rather than allocating an untrusted full snapshot.
    for offset, chunk in store.iter_chunks(reference['report_id'], 'receipt'):
        if (chunk.dtype != np.dtype('u1') or chunk.ndim != 1 or offset != len(body)
                or len(body) + chunk.nbytes > reference['size_bytes']):
            _fail('Invalid layout report receipt payload.')
        body.extend(chunk.tobytes())
    if (len(body) != reference['size_bytes']
            or hashlib.sha256(body).hexdigest() != reference['report_id']):
        _fail('Layout report receipt identity mismatch.')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail('Duplicate layout report JSON key.')
            result[key] = value
        return result

    try:
        report = json.loads(body.decode('utf-8'), object_pairs_hook=pairs,
                            parse_constant=lambda _: _fail('Non-finite layout report JSON.'))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError('INVALID_PROJECT', 'Invalid layout report JSON.') from exc
    if _report_bytes(report) != body:
        _fail('The layout report receipt is not canonical JSON.')
    return report


def _check_pair(plan, report, atlas):
    if (atlas is None or type(report) is not dict
            or report.get('schema') != 'atlas.layout-candidate-result.v1'
            or report.get('status') != 'CANDIDATE_NOT_GEOLOGICALLY_ACCEPTED'
            or report.get('rejection') is not None
            or report.get('plan_id') != plan['plan_id']
            or report.get('atlas_id') != atlas.atlas_id
            or report.get('geometry_id') != atlas.geometry_id):
        _fail('A successful candidate and its matching original plan are required.')
    spec = atlas.descriptor()['source_bindings'].get('new_world_layout')
    if (type(spec) is not dict or report.get('specification') != spec
            or spec.get('scientific_id') != plan['scientific_id']
            or spec.get('contract_binding') != plan['binding']
            or spec.get('geometry_seed') != plan['streams']['plate_layout']):
        _fail('The stored layout, report and configuration bindings disagree.')


def save_project(raw_path, plan, candidate, *, title='Untitled world', structure=None, motion=None):
    """Save existing geometry atomically without replacing another project."""
    plan = validate_plan(plan)
    if (type(title) is not str or not title.strip() or len(title) > 160
            or any(ord(char) < 32 for char in title)):
        _fail('Use a nonempty project title of at most 160 characters.')
    if motion is not None and structure is None:
        _fail('Initial motion requires its matching native structure.')
    report_body = _report_bytes(candidate.report) if motion is not None else canonical_bytes(candidate.report)
    report = json.loads(report_body)
    _check_pair(plan, report, candidate.atlas)
    if structure is not None:
        from new_world_structure import check_structure, save_structure
        check_structure(plan, structure, current=True)
    if motion is not None:
        from new_world_motion import check_motion, save_motion
        check_motion(plan, candidate.atlas, structure, motion, current=True)
    path, parents = _checked_path(os.fspath(raw_path))
    with _Directory(path.parent, parents) as directory:
        try:
            directory.inspect(path.name)
        except FileNotFoundError:
            pass
        else:
            raise ContractError('FILE_EXISTS', 'The destination already exists; nothing was replaced.')
        Store, limits, save, _ = _native()
        with tempfile.TemporaryDirectory(prefix='atlas-project-') as temporary:
            database = Path(temporary) / 'arrays.sqlite'
            with Store(database, limits) as store:
                save(candidate.atlas, store)
                structure_id = None if structure is None else save_structure(structure, store)
                motion_id = None if motion is None else save_motion(motion, store)
                if motion is not None:
                    report = _save_report(report_body, store)
            if database.stat().st_size > MAX_STORE:
                _fail('The project store exceeds 64 MiB.')
            schema = MOTION_SCHEMA if motion is not None else (SCHEMA if structure is None else STRUCTURE_SCHEMA)
            manifest = dict(schema=schema,
                title=title, status='WORKING NON-CANON',
                plan=plan, report=report, atlas_id=candidate.atlas.atlas_id,
                geometry_id=candidate.atlas.geometry_id, store_sha256=_file_digest(database))
            if structure is not None:
                if (type(structure_id) is not str or len(structure_id) != 64
                        or any(char not in '0123456789abcdef' for char in structure_id)):
                    _fail('The native structure did not return a valid identity.')
                manifest['structure_id'] = structure_id
            if motion is not None:
                if (type(motion_id) is not str or len(motion_id) != 64
                        or any(char not in '0123456789abcdef' for char in motion_id)):
                    _fail('The native motion did not return a valid identity.')
                manifest['motion_id'] = motion_id
            manifest['project_id'] = _digest(manifest)
            body = canonical_bytes(manifest)
            if len(body) > MAX_JSON:
                _fail('The project manifest exceeds 64 KiB.')
            name = '.atlas-project-' + secrets.token_hex(16) + '.tmp'
            fd = directory.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0))
            identity = _identity(os.fstat(fd))
            try:
                with os.fdopen(fd, 'w+b') as handle:
                    with zipfile.ZipFile(handle, 'w', compression=zipfile.ZIP_STORED) as archive:
                        archive.writestr('project.json', body)
                        archive.write(database, 'arrays.sqlite')
                    handle.flush()
                    os.fsync(handle.fileno())
                info = directory.inspect(name)
                if _unsafe(info) or _identity(info) != identity:
                    _fail('Temporary project ownership changed.')
                directory.publish(name, path.name)
            finally:
                directory.remove_owned(name, identity)
    return manifest


def _read_archive(handle, database):
    try:
        with zipfile.ZipFile(handle, 'r') as archive:
            entries = archive.infolist()
            if len(entries) != 2 or {e.filename for e in entries} != {'project.json', 'arrays.sqlite'}:
                _fail('A project must contain exactly project.json and arrays.sqlite.')
            for entry in entries:
                bound = MAX_JSON if entry.filename == 'project.json' else MAX_STORE
                if (entry.compress_type != zipfile.ZIP_STORED or entry.flag_bits & 1
                        or not 0 < entry.file_size <= bound
                        or entry.compress_size != entry.file_size):
                    _fail('Unsupported or oversized project member.')
            manifest = parse_json(archive.read('project.json'))
            with archive.open('arrays.sqlite') as source, database.open('xb') as target:
                shutil.copyfileobj(source, target, length=65536)
    except (zipfile.BadZipFile, EOFError) as exc:
        raise ContractError('INVALID_PROJECT', 'Damaged project container.') from exc
    keys = {'schema', 'title', 'status', 'plan', 'report', 'atlas_id',
            'geometry_id', 'store_sha256', 'project_id'}
    if type(manifest) is dict and manifest.get('schema') in (STRUCTURE_SCHEMA, MOTION_SCHEMA):
        keys.add('structure_id')
        identity = manifest.get('structure_id')
        if (type(identity) is not str or len(identity) != 64
                or any(char not in '0123456789abcdef' for char in identity)):
            _fail('The project structure identity is invalid.')
    if type(manifest) is dict and manifest.get('schema') == MOTION_SCHEMA:
        keys.add('motion_id')
        identity = manifest.get('motion_id')
        if (type(identity) is not str or len(identity) != 64
                or any(char not in '0123456789abcdef' for char in identity)):
            _fail('The project motion identity is invalid.')
    if (type(manifest) is not dict or set(manifest) != keys
            or manifest['schema'] not in (SCHEMA, STRUCTURE_SCHEMA, MOTION_SCHEMA)
            or manifest['status'] != 'WORKING NON-CANON'
            or manifest['project_id'] != _digest({k: v for k, v in manifest.items() if k != 'project_id'})
            or manifest['store_sha256'] != _file_digest(database)):
        _fail('Project version or integrity check failed.')
    plan = manifest['plan']
    if (type(plan) is not dict or plan.get('plan_id') !=
            _digest({k: v for k, v in plan.items() if k != 'plan_id'})):
        _fail('Saved plan integrity check failed.')
    compatible = True
    try:
        validate_plan(plan)
    except ContractError as exc:
        if exc.code != 'SOURCE_MISMATCH':
            raise
        # Preserve the old bindings for inspection; never silently rebind them.
        compatible = False
    return manifest, compatible


def load_project(raw_path):
    """Restore native geometry from a temporary store; never change the source file.

    configuration_compatible concerns the S1 configuration contract only. Neither
    it nor reopening a layout grants native simulation-restart capability.
    """
    path, parents = _checked_path(os.fspath(raw_path))
    with _Directory(path.parent, parents) as directory:
        info = directory.inspect(path.name)
        if _unsafe(info) or not stat.S_ISREG(info.st_mode):
            _fail('Use a regular local project file, not a link.')
        if not 0 < info.st_size <= MAX_PROJECT:
            _fail('The project exceeds its bounded storage envelope.')
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        flags |= getattr(os, 'O_NONBLOCK', 0)
        fd = directory.open(path.name, flags)
        with os.fdopen(fd, 'rb') as handle, tempfile.TemporaryDirectory(prefix='atlas-project-open-') as tmp:
            opened = os.fstat(handle.fileno())
            if _unsafe(opened) or not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(info):
                _fail('Project file changed while opening.')
            database = Path(tmp) / 'arrays.sqlite'
            manifest, compatible = _read_archive(handle, database)
            Store, limits, _, load = _native()
            with Store(database, limits) as store:
                atlas = load(store, manifest['atlas_id'])
                report = manifest['report']
                if (manifest['schema'] == MOTION_SCHEMA and type(report) is dict
                        and report.get('schema') == REPORT_SCHEMA):
                    report = _load_report(report, store)
                _check_pair(manifest['plan'], report, atlas)
                if atlas.geometry_id != manifest['geometry_id']:
                    _fail('Saved geometry identity disagrees with the manifest.')
                structure, motion = None, None
                if manifest['schema'] in (STRUCTURE_SCHEMA, MOTION_SCHEMA):
                    from new_world_structure import load_structure, check_structure
                    structure = load_structure(store, manifest['structure_id'])
                    check_structure(manifest['plan'], structure)
                if manifest['schema'] == MOTION_SCHEMA:
                    from new_world_motion import load_motion, check_motion
                    motion = load_motion(store, manifest['motion_id'])
                    check_motion(manifest['plan'], atlas, structure, motion)
            after = os.fstat(handle.fileno())
            if (after.st_size, after.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns):
                _fail('Project file changed during reopening.')
        _check_parents(parents)
    return SavedProject(manifest, atlas, compatible, structure, motion)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 3 or args[:2] != ['inspect', '--file']:
            raise ContractError('INVALID_ARGUMENTS', 'Use inspect --file PATH.')
        project = load_project(args[2])
        manifest = project.manifest
        result = dict(status='ok', title=manifest['title'], project_id=manifest['project_id'],
            seed=manifest['plan']['request']['seed'], atlas_id=project.atlas.atlas_id,
            plates=len(project.atlas.plate_ids), configuration_compatible=project.configuration_compatible,
            saved_layout=True, generated_on_open=False, native_restart=False)
    except Exception as exc:
        result = dict(status='error', code=getattr(exc, 'code', 'PROJECT_READ_FAILED'))
        print(canonical_bytes(result).decode())
        return 2
    print(canonical_bytes(result).decode())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
