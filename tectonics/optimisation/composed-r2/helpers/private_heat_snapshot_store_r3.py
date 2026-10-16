"""Private lossless snapshot persistence using the EXISTING native ArrayStore.

Large exact ledgers are byte payloads, not oversized manifest metadata. No
storage schema, codec limit or native heat admission changes. Restored snapshots
are detached data: the caller must validate origin, physics and continuation.
This adapter never constructs a ComposedHeatResult or changes its fixture flag.
JSON views follow resources r4: the codec is booked while an identity is hashed,
and a restore releases its metadata decode once the snapshot object exists.

r3 is r2 with one addition. A restore reserves six times the snapshot's bytes
for the store's arrays, the copy read from them, the decode and the constructor,
and r2 kept that for as long as the restored snapshot was held. Once the
snapshot object exists it owns exactly its encoded metadata and its field
bytes, each one block; this frame's references to everything else are dropped
and the reservation falls to those blocks. Nothing is reserved less before or
while the restore runs, and no byte of a snapshot differs.
"""
from hashlib import sha256
import json
import math

import numpy as np
import private_heat_issuer_resources_r4 as R
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.storage import ArrayStore

SCHEMA = 'atlas.private.exact-snapshot-array-store.r1'


def _bindings(value):
    if (type(value) is not dict or not value or len(value) > 32
            or any(type(k) is not str or not k or len(k) > 128
                   or type(v) is not str or len(v) != 64
                   or any(c not in '0123456789abcdef' for c in v) for k, v in value.items())):
        raise ValueError('Explicit small source/call/plan SHA256 bindings required')
    return dict(value)


def _identity(snapshot, budget, cancel):
    with R.decoded(snapshot._metadata, budget=budget, cancel=cancel) as owner, \
            R.codec(owner, budget=budget, cancel=cancel):
        return R.stream_hash(dict(metadata=owner.value, arrays={
            name: dict(shape=shape, sha256=sha256(raw).hexdigest())
            for name, shape, raw in snapshot._fields}), cancel)


def _manifest(value, maximum):
    """Bound the small manifest before copying; payload size lives elsewhere."""
    keys = {'schema', 'result_id', 'bindings', 'metadata_bytes', 'metadata_sha256',
            'fields', 'logical_bytes', 'detached_only', 'native_admission'}
    if type(value) is not dict or set(value) != keys:
        raise ValueError('Exact snapshot manifest keys required')
    _bindings(value['bindings'])
    _bindings({key: value[key] for key in ('result_id', 'metadata_sha256')})
    for key in ('metadata_bytes', 'logical_bytes'):
        if type(value[key]) is not int or not 0 < value[key] <= maximum:
            raise ValueError('Snapshot size exceeds explicitly configured bound')
    fields = value['fields']
    if type(fields) is not list or not 1 <= len(fields) <= 128:
        raise ValueError('One to128 snapshot fields required')
    total = value['metadata_bytes']
    names, arrays = set(), set()
    for row in fields:
        if type(row) is not dict or set(row) != {'name', 'shape', 'array', 'sha256'}:
            raise ValueError('Exact field manifest required')
        if (type(row['name']) is not str or not row['name'] or len(row['name']) > 512
                or type(row['array']) is not str or not row['array'].startswith('field_')
                or len(row['array']) > 32 or row['name'] in names or row['array'] in arrays):
            raise ValueError('Bounded unique field names required')
        shape = row['shape']
        if (type(shape) is not list or len(shape) > 16
                or any(type(n) is not int or not 0 <= n <= maximum for n in shape)):
            raise ValueError('Bounded exact field shape required')
        total += 8*math.prod(shape)
        if total > maximum:
            raise ValueError('Snapshot fields exceed configured size')
        _bindings({'field': row['sha256']})
        names.add(row['name'])
        arrays.add(row['array'])
    if total != value['logical_bytes']:
        raise ValueError('Logical byte count does not match complete manifest')
    if (value['schema'] != SCHEMA or value['detached_only'] is not True
            or value['native_admission'] is not False):
        raise ValueError('Detached private snapshot schema required')


class _Cancellation:
    def __init__(self, callback):
        self.callback = callback

    def is_set(self):
        return self.callback is not None and self.callback()


def save(store, snapshot, *, bindings, budget, cancel=None):
    """Store existing immutable bytes; return the caller-retained manifest.

    Source arrays and snapshot bytes remain caller-owned for this operation.
    A repeated save is idempotent under the existing store's exact identity.
    """
    R.check(cancel)
    if type(store) is not ArrayStore or type(snapshot) is not RegionalMechanicalSnapshot:
        raise TypeError('Existing ArrayStore and immutable regional snapshot required')
    bindings = _bindings(bindings)
    with R.workspace(budget, 65536+8192*len(snapshot._fields), cancel=cancel):
        if _identity(snapshot, budget, cancel) != snapshot.result_id:
            raise ValueError('Original immutable snapshot identity differs')
        fields, arrays = [], {'metadata_utf8': np.frombuffer(snapshot._metadata, dtype=np.uint8)}
        for i, (name, shape, raw) in enumerate(snapshot._fields):
            key = 'field_'+str(i)
            if len(raw) != 8*math.prod(shape):
                raise ValueError('Snapshot field is not native binary64')
            fields.append(dict(name=name, shape=list(shape), array=key, sha256=sha256(raw).hexdigest()))
            arrays[key] = np.frombuffer(raw, dtype=np.float64).reshape(shape)
        metadata = dict(schema=SCHEMA, result_id=snapshot.result_id, bindings=bindings,
            metadata_bytes=len(snapshot._metadata), metadata_sha256=sha256(snapshot._metadata).hexdigest(),
            fields=fields, logical_bytes=snapshot.nbytes,
            detached_only=True, native_admission=False)
        _manifest(metadata, store.limits.max_array_bytes)
        key = R.stream_hash(metadata, cancel)
        def still_bound():
            R.check(cancel)
            if _identity(snapshot, budget, cancel) != metadata['result_id']:
                raise ValueError('Snapshot changed during persistence')
        store.put(key, arrays, metadata, publication_check=still_bound,
                  cancel=_Cancellation(cancel), budget=budget)
        still_bound()
        return dict(invocation=key, metadata=metadata)


RESTORED_OWNER = 65536


def _restored_bytes(snapshot):
    """What a restored snapshot occupies: its encoded metadata and its field bytes.

    Each is one immutable bytes object, a block of its own: the 33-byte
    object header and the data rounded up to 16, the heap's 16-byte header,
    and one eighth, which is the rule for a block above pymalloc's 512 bytes;
    a smaller field takes less. 512 bytes more for each field's name, shape
    and tuple. Returns None for anything that is not such a snapshot.
    """
    if (type(snapshot) is not RegionalMechanicalSnapshot or type(snapshot._metadata) is not bytes
            or type(snapshot._fields) is not tuple):
        return None
    total = RESTORED_OWNER
    for item in (snapshot._metadata, *snapshot._fields):
        raw = item if type(item) is bytes else item[2] if type(item) is tuple and len(item) == 3 else None
        if type(raw) is not bytes:
            return None
        block = ((len(raw)+33+15) & ~15)+16
        total += block+(block >> 3)+512
    return total


def restore(store, receipt, *, expected_result_id, bindings, budget, cancel=None):
    """Owned detached snapshot. Exact identity is not scientific acceptance."""
    R.check(cancel)
    if type(store) is not ArrayStore or type(receipt) is not dict or set(receipt) != {'invocation', 'metadata'}:
        raise TypeError('Existing ArrayStore and caller-retained manifest required')
    bindings = _bindings(bindings)
    _manifest(receipt['metadata'], store.limits.max_array_bytes)
    # Freeze caller metadata before any store reads. Never infer expected source
    # bindings from the stored object itself.
    with R.workspace(budget, 1 << 20, cancel=cancel):
        meta = json.loads(json.dumps(receipt['metadata'], allow_nan=False))
        key = receipt['invocation']
        if (meta.get('schema') != SCHEMA or meta.get('result_id') != expected_result_id
                or meta.get('bindings') != bindings or meta.get('detached_only') is not True
                or meta.get('native_admission') is not False or R.stream_hash(meta, cancel) != key):
            raise ValueError('Expected source/call/plan/result identity differs')
        if store.metadata(key) != meta:
            raise ValueError('Stored snapshot manifest differs from the bound one')
        count = meta['logical_bytes']
        if type(count) is not int or not 0 < count <= store.limits.max_array_bytes:
            raise ValueError('Snapshot is outside the explicitly admitted store size')
        # Detached get arrays, immutable reconstruction copies, constructor JSON
        # and hash encoding. Decode/view containers have a separate actual-byte
        # inventory after the authenticated byte array is available.
        work = R.workspace(budget, 65536+6*count+8192*len(meta['fields']),
                           cancel=cancel, category='private-snapshot-restore')
        work.__enter__()
        try:
            arrays = store.get(key, budget=budget)
            if arrays is None or set(arrays) != {'metadata_utf8', *(row['array'] for row in meta['fields'])}:
                raise ValueError('Complete persisted snapshot fields required')
            encoded = arrays.pop('metadata_utf8')
            if encoded.dtype != np.uint8 or encoded.shape != (meta['metadata_bytes'],):
                raise ValueError('Exact metadata byte array required')
            raw = encoded.tobytes()
            if sha256(raw).hexdigest() != meta['metadata_sha256']:
                raise ValueError('Persisted metadata bytes differ')
            fields = {}
            for row in meta['fields']:
                R.check(cancel)
                value = arrays[row['array']]
                if (value.dtype != np.float64 or list(value.shape) != row['shape']
                        or row['name'] in fields or sha256(memoryview(value).cast('B')).hexdigest() != row['sha256']):
                    raise ValueError('Exact unique binary64 field/shape/hash required')
                fields[row['name']] = value
            # The snapshot keeps its own encoded metadata, never this decode.
            with R.decoded(raw, budget=budget, cancel=cancel) as view:
                snapshot = RegionalMechanicalSnapshot(view.value, fields)
            if (snapshot.result_id != expected_result_id or snapshot._metadata != raw
                    or store.metadata(key) != meta):
                raise ValueError('Restored snapshot identity or metadata changed')
            R.check(cancel)
            # The snapshot has its own encoded metadata and field bytes. Drop this frame's
            # references to the store's arrays and the copy read from them, then hold what stays.
            held = _restored_bytes(snapshot)
            arrays = encoded = raw = fields = value = view = None
            if held is not None and held < work.lease.count:
                work.resize_before_allocation_or_after_drop(held)
            return R.P.OwnedSolve(snapshot, work)
        except BaseException:
            import sys
            work.__exit__(*sys.exc_info())
            raise
