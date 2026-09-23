"""Lossless, bounded W07 snapshot bundles for the checked ArrayStore.

SPDX-License-Identifier: AGPL-3.0-only

This codec preserves existing snapshot identities; it never repins sources or
evaluates mechanics/thermal/surface physics. The caller must authenticate the
workflow, execution, policy, expected snapshot set, parents and physical state.
Hashes detect corruption, not an attacker replacing both records and hashes.
Returned data are detached and immutable. Reservations cover codec working and
output buffers until return; callers must account for retained input/output data
and ArrayStore work separately. ``resources`` describes these byte allowances,
not measured RSS. No history or process-global payload cache is retained.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

import numpy as np

from ._validation import TectonicsError
from .constitutive import _cancel
from .regional_execution import RegionalMechanicalSnapshot
from .resources import WorkBudget, select_budget


_SCHEMA = 'atlas.w07-regional-checkpoint.v1'
_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,127}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_DTYPE = np.dtype('float64')
_MAX_SNAPSHOTS = 16
_MAX_FIELDS = 128
_MAX_TOTAL_FIELDS = 1024
_MAX_METADATA_BYTES = 512 * 1024
_MAX_SNAPSHOT_METADATA_BYTES = 128 * 1024
_MAX_ARRAY_BYTES = 128 * 1024 * 1024
_MAX_LOGICAL_BYTES = 128 * 1024 * 1024
_MAX_WORK_BYTES = 128 * 1024 * 1024
_META_KEYS = {'schema', 'version', 'snapshots', 'arrays', 'resources', 'content_id'}
_SNAPSHOT_KEYS = {'name', 'metadata', 'metadata_sha256', 'result_id', 'fields'}
_ARRAY_KEYS = {'name', 'dtype', 'shape', 'nbytes', 'sha256'}


def _fail(message):
    raise TectonicsError('regional checkpoint '+message)


def _keys(value, keys, label):
    if type(value) is not dict or set(value) != keys:
        _fail('invalid '+label+' keys')


def _name(value):
    if type(value) is not str or _NAME.fullmatch(value) is None:
        _fail('requires bounded field/snapshot names')
    return value


def _sha(value):
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail('requires lowercase SHA-256 identities')
    return value


def _shape(value):
    if (type(value) not in (tuple, list) or len(value) > 8
            or any(type(n) is not int or not 0 <= n <= 2_097_152 for n in value)):
        _fail('invalid or oversized array shape')
    size = math.prod(value) * _DTYPE.itemsize
    if size > _MAX_ARRAY_BYTES:
        _fail('array exceeds byte limit')
    return tuple(value), size


def _json(value):
    # Bound arbitrary caller metadata before json.dumps allocates its result.
    nodes, characters = 0, 0
    def visit(item, depth):
        nonlocal nodes, characters
        nodes += 1
        if nodes > 65536 or depth > 32:
            _fail('metadata exceeds node/depth limit')
        kind = type(item)
        if kind is str:
            characters += len(item)
            if len(item) > 65536 or characters > _MAX_METADATA_BYTES:
                _fail('metadata exceeds text limit')
        elif kind is dict:
            if len(item) > 65536:
                _fail('metadata exceeds object limit')
            for key, child in item.items():
                if type(key) is not str:
                    _fail('metadata keys must be strings')
                visit(key, depth+1); visit(child, depth+1)
        elif kind in (list, tuple):
            if len(item) > 65536:
                _fail('metadata exceeds list limit')
            for child in item:
                visit(child, depth+1)
        elif kind is float:
            if not math.isfinite(item):
                _fail('metadata must be finite JSON')
        elif kind is int:
            if item.bit_length() > 4096:
                _fail('metadata integer exceeds limit')
        elif item is not None and kind is not bool:
            _fail('metadata must be finite JSON')
    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError) as exc:
        raise TectonicsError('regional checkpoint metadata must be finite JSON') from exc
    if len(raw) > _MAX_METADATA_BYTES:
        _fail('metadata exceeds byte limit')
    return raw


def _parse(raw):
    def pairs(values):
        out = {}
        for key, value in values:
            if key in out:
                _fail('duplicate metadata key')
            out[key] = value
        return out
    try:
        result = json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda _: _fail('nonfinite metadata'))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise TectonicsError('invalid regional checkpoint metadata') from exc
    if type(result) is not dict or _json(result) != raw:
        _fail('snapshot metadata must be a canonical JSON object')
    return result


def _hash(raw, cancel=None):
    digest = hashlib.sha256()
    view = memoryview(raw).cast('B')
    for offset in range(0, len(view), 1024 * 1024):
        _cancel(cancel); digest.update(view[offset:offset+1024*1024])
    _cancel(cancel)
    return digest.hexdigest()


def _array_name(shape, digest):
    return 'field_'+_hash(_json({'dtype': _DTYPE.str, 'shape': shape, 'sha256': digest}))


def _resources(logical, stored, metadata, fields, snapshots):
    # JSON object/string/record allowances, including identity serialisation.
    work = 32*metadata + 8192*fields + 4096*snapshots + 65536
    return dict(logical_array_bytes=logical, stored_array_bytes=stored,
        snapshot_metadata_bytes=metadata, field_count=fields, snapshot_count=snapshots,
        pack_work_bytes=work+2*stored, restore_work_bytes=work+stored+2*logical,
        retained_snapshot_bytes=logical+metadata, retained_array_bytes=stored)


def _resource(budget):
    # A caller can narrow the established envelope, never widen this codec cap.
    return WorkBudget(_MAX_WORK_BYTES, parent=select_budget(budget))


def _source_rows(snapshots):
    if type(snapshots) is not dict or not 1 <= len(snapshots) <= _MAX_SNAPSHOTS:
        _fail('requires one to sixteen named snapshots')
    rows, logical, metadata_bytes, count = [], 0, 0, 0
    for name, snapshot in snapshots.items():
        _name(name)
        if type(snapshot) is not RegionalMechanicalSnapshot:
            _fail('requires typed regional mechanical snapshots')
        raw_meta, fields = snapshot._metadata, snapshot._fields
        if type(raw_meta) is not bytes or len(raw_meta) > _MAX_SNAPSHOT_METADATA_BYTES:
            _fail('snapshot metadata exceeds byte limit')
        if type(fields) is not tuple or not 1 <= len(fields) <= _MAX_FIELDS:
            _fail('snapshot field count exceeds limit')
        seen = set()
        for field in fields:
            if type(field) is not tuple or len(field) != 3:
                _fail('invalid immutable snapshot field')
            key, shape, raw = field
            _name(key)
            if key in seen:
                _fail('duplicate snapshot field')
            seen.add(key)
            _, size = _shape(shape)
            if type(raw) is not bytes or len(raw) != size:
                _fail('snapshot field shape/bytes mismatch')
            logical += size
        metadata_bytes += len(raw_meta); count += len(fields)
        if (logical > _MAX_LOGICAL_BYTES or metadata_bytes > _MAX_METADATA_BYTES
                or count > _MAX_TOTAL_FIELDS):
            _fail('snapshot bundle exceeds bounds')
        rows.append((name, snapshot, raw_meta, fields))
    return sorted(rows), logical, metadata_bytes, count


def pack_regional_snapshots(snapshots, *, budget=None, cancel=None):
    """Pack an exact named snapshot set, deduplicating before payload copies.

    The catalogue identity includes shape, native float64 dtype and raw C-order
    bytes. Scalars, zero-length arrays, signed zero and small fields are retained.
    No fields are inferred from physics or silently dropped as reconstructible.
    """
    _cancel(cancel)
    rows, logical, metadata_bytes, count = _source_rows(snapshots)
    resource = _resource(budget)
    overhead = _resources(logical, 0, metadata_bytes, count, len(rows))['pack_work_bytes']
    with resource.reserve(overhead, category='regional-checkpoint-metadata'):
        records, catalogue, unique = [], {}, {}
        for name, snapshot, raw_meta, fields in rows:
            _cancel(cancel)
            metadata = _parse(raw_meta)
            refs, identity = [], {}
            for key, shape, raw in sorted(fields):
                digest = _hash(raw, cancel)
                array_name = _array_name(shape, digest)
                identity[key] = {'shape': shape, 'sha256': digest}
                refs.append({'name': key, 'array': array_name})
                if array_name not in unique:
                    # Retain only an existing immutable source reference here.
                    unique[array_name] = raw
                    catalogue[array_name] = dict(name=array_name, dtype=_DTYPE.str,
                        shape=list(shape), nbytes=len(raw), sha256=digest)
            result_id = _hash(_json({'metadata': metadata, 'arrays': identity}))
            if result_id != _sha(snapshot.result_id):
                _fail('snapshot result identity mismatch')
            records.append(dict(name=name, metadata=metadata, metadata_sha256=_hash(raw_meta),
                result_id=result_id, fields=refs))
        stored = sum(len(raw) for raw in unique.values())
        costs = _resources(logical, stored, metadata_bytes, count, len(rows))
        header = dict(schema=_SCHEMA, version=1, snapshots=records,
            arrays=[catalogue[key] for key in sorted(catalogue)], resources=costs)
        metadata = dict(header, content_id=_hash(_json(header)))
        _json(metadata)
        with resource.reserve(2*stored, category='regional-checkpoint-pack'):
            arrays = {}
            for key in sorted(unique):
                _cancel(cancel)
                # Copy only unique arrays. bytes-backed buffers cannot be thawed.
                raw = memoryview(unique[key]).tobytes()
                value = np.frombuffer(raw, dtype=_DTYPE).reshape(catalogue[key]['shape'])
                if not np.isfinite(value).all():
                    _fail('nonfinite snapshot array')
                arrays[key] = value
            _cancel(cancel)
            return arrays, metadata


def restore_regional_snapshots(arrays, metadata, *, budget=None, cancel=None):
    """Validate the complete catalogue and restore detached original identities.

    ArrayStore owns stored-chunk authentication; this function checks schema,
    bindings, hashes, finite values, bounded names/shapes/dtypes and exact coverage.
    Mutable input arrays/metadata must remain unchanged until this call returns.
    Caller validation of expected workflow/source/parent/physical meaning remains
    mandatory even when a bundle is internally self-consistent.
    """
    _cancel(cancel)
    _keys(metadata, _META_KEYS, 'bundle')
    if metadata['schema'] != _SCHEMA or type(metadata['version']) is not int or metadata['version'] != 1:
        _fail('unsupported schema/version')
    records, catalogue = metadata['snapshots'], metadata['arrays']
    if type(records) is not list or not 1 <= len(records) <= _MAX_SNAPSHOTS:
        _fail('invalid snapshot catalogue count')
    if type(catalogue) is not list or not 1 <= len(catalogue) <= _MAX_TOTAL_FIELDS:
        _fail('invalid array catalogue count')
    if type(arrays) is not dict or len(arrays) != len(catalogue):
        _fail('missing/extra array payload')
    specs, stored = {}, 0
    for entry in catalogue:
        _keys(entry, _ARRAY_KEYS, 'array catalogue')
        key = _name(entry['name']); digest = _sha(entry['sha256'])
        shape, size = _shape(entry['shape'])
        if (entry['dtype'] != _DTYPE.str or type(entry['nbytes']) is not int
                or entry['nbytes'] != size or key != _array_name(shape, digest) or key in specs):
            _fail('invalid/duplicate array catalogue binding')
        value = arrays.get(key)
        if (type(value) is not np.ndarray or value.dtype != _DTYPE or value.shape != shape
                or value.nbytes != size or not value.flags.c_contiguous):
            _fail('array type/dtype/shape/layout mismatch')
        specs[key] = entry; stored += size
        if stored > _MAX_LOGICAL_BYTES:
            _fail('stored arrays exceed byte limit')
    if set(arrays) != set(specs):
        _fail('missing/extra array payload')
    logical, metadata_bytes, count = 0, 0, 0
    names, used, descriptions = set(), set(), []
    for record in records:
        _keys(record, _SNAPSHOT_KEYS, 'snapshot')
        name = _name(record['name'])
        if name in names:
            _fail('duplicate snapshot name')
        names.add(name)
        fields = record['fields']
        if type(fields) is not list or not 1 <= len(fields) <= _MAX_FIELDS:
            _fail('snapshot field count exceeds limit')
        seen, identity = set(), {}
        for field in fields:
            _keys(field, {'name', 'array'}, 'snapshot field')
            key, target = _name(field['name']), _name(field['array'])
            if key in seen or target not in specs:
                _fail('duplicate/missing snapshot field')
            seen.add(key); used.add(target)
            entry = specs[target]
            logical += entry['nbytes']; count += 1
            identity[key] = {'shape': entry['shape'], 'sha256': entry['sha256']}
        raw_meta = _json(record['metadata'])
        if (type(record['metadata']) is not dict or len(raw_meta) > _MAX_SNAPSHOT_METADATA_BYTES
                or _hash(raw_meta) != _sha(record['metadata_sha256'])
                or _hash(_json({'metadata': record['metadata'], 'arrays': identity})) != _sha(record['result_id'])):
            _fail('snapshot metadata/result identity mismatch')
        metadata_bytes += len(raw_meta)
        if logical > _MAX_LOGICAL_BYTES or count > _MAX_TOTAL_FIELDS or metadata_bytes > _MAX_METADATA_BYTES:
            _fail('snapshot bundle exceeds bounds')
        descriptions.append((record, raw_meta))
    if used != set(specs):
        _fail('unreferenced array catalogue entry')
    costs = _resources(logical, stored, metadata_bytes, count, len(records))
    if (_json(metadata['resources']) != _json(costs)
            or _hash(_json({key: value for key, value in metadata.items() if key != 'content_id'}))
            != _sha(metadata['content_id'])):
        _fail('bundle content/resource identity mismatch')
    _json(metadata)
    with _resource(budget).reserve(costs['restore_work_bytes'], category='regional-checkpoint-restore'):
        captured = {}
        for key, entry in specs.items():
            _cancel(cancel)
            raw = arrays[key].tobytes(order='C')
            if len(raw) != entry['nbytes'] or _hash(raw, cancel) != entry['sha256']:
                _fail('array content hash mismatch')
            value = np.frombuffer(raw, dtype=_DTYPE).reshape(entry['shape'])
            if not np.isfinite(value).all():
                _fail('nonfinite restored array')
            captured[key] = value
        restored = {}
        for record, raw_meta in descriptions:
            _cancel(cancel)
            fields = {entry['name']: captured[entry['array']] for entry in record['fields']}
            result = RegionalMechanicalSnapshot(_parse(raw_meta), fields)
            if result.result_id != record['result_id']:
                _fail('restored snapshot result identity mismatch')
            restored[record['name']] = result
        _cancel(cancel)
        return restored
