"""Exact transport result identity without a second whole metadata JSON."""
from dataclasses import dataclass, field
from hashlib import sha256
from concurrent.futures import CancelledError

import numpy as np

from compact_contracts import ContractError
from content_cache import ChargeSpec
from record_tables import RecordCodec, canonical
from record_views import _ObjectRecordRef
import live_spatial_patch as LIVE


class _FieldBytes(bytes):
    """An escaped numpy base keeps its own allocation funded."""
    def __new__(cls, array, owner):
        value = super().__new__(cls, array)
        object.__setattr__(value, '_owner', owner.retain())
        return value

    def __setattr__(self, name, value):
        raise ContractError('immutable transport field ownership')


def _own_field(array, scope):
    if array.nbytes > 512 << 20:
        raise ContractError('transport field exceeds 512 MiB bound')
    with scope.reserve(ChargeSpec('transport-result-field',
            65536+array.nbytes+(array.nbytes >> 3)), required=True) as reservation:
        owner = reservation.commit(None)
        raw = _FieldBytes(array, owner)
        owner._retire()
        return raw


@dataclass(frozen=True)
class CompactTransportSnapshot:
    _record: object
    _fields_owner: object
    result_id: str
    # Process-local seal of the one complete identity computation in THIS process
    # (plan section 7): (identity, record identity, field bindings). Never
    # persisted or trusted across processes, excluded from equality, and never
    # copied by dataclasses.replace (init=False).
    _verified: object = field(default=None, init=False, compare=False, repr=False)

    @property
    def array_names(self):
        return tuple(name for name, _, _ in self._fields_owner.value)

    @property
    def nbytes(self):
        # Preserve the native logical-size meaning for bounded consumers.
        return self._record.identity().canonical_bytes + sum(
            len(raw) for _, _, raw in self._fields_owner.value)

    def array(self, name):
        for key, shape, raw in self._fields_owner.value:
            if key == name:
                return np.frombuffer(raw, dtype=np.float64).reshape(shape)
        raise ContractError('unknown compact transport array')

    def descriptor(self):
        raise ContractError('compact transport metadata requires an owned record view')


def make_snapshot(metadata, arrays, budget, ordinary, check=None):
    scope = LIVE.active_scope(budget)
    if scope is None:
        return ordinary(metadata, arrays)
    if type(metadata) is not dict or type(arrays) is not dict or any(
            type(value) is not np.ndarray or value.dtype != np.dtype('float64')
            for value in arrays.values()):
        raise ContractError('actual native transport metadata and float64 arrays required')
    # Step 8: the advance's own cancellation now reaches the metadata pack.
    record = RecordCodec().pack_record(metadata, record_schema='atlas.spatial-implicit-transport.v1',
                                       scope=scope, check=check or (lambda: None))
    size = 16384+sum(1024+32*value.ndim for value in arrays.values())
    with scope.reserve(ChargeSpec('transport-result-arrays', size), required=True) as reservation:
        fields = reservation.commit(tuple((name, tuple(value.shape), _own_field(value, scope))
                                          for name, value in sorted(arrays.items())))
    result = CompactTransportSnapshot(record, fields, '')
    object.__setattr__(result, 'result_id', identity(result, budget))
    return result


def identity(snapshot, budget, cancel=None):
    """Recompute native identity, including byte hashes; never trust cached ID.

    The field bytes are always rehashed. Only the record stream is skipped, and
    only when this process already computed the identity from the same record
    identity (verified when the record was packed here) and the same byte hashes:
    a process-local seal (plan section 7, audit X2). A fresh process recomputes.
    """
    if type(snapshot) is not CompactTransportSnapshot or snapshot._record.scope.run_budget is not budget:
        raise ContractError('actual compact transport snapshot and same budget required')
    snapshot._record._live()
    fields = snapshot._fields_owner.value
    def check():
        if cancel is not None and cancel():
            raise CancelledError('Private composed issuance cancelled')
        snapshot._record._live()
    check()
    with LIVE.workspace(budget, 65536+1024*(len(fields)+1)):
        bindings = {}
        for name, shape, raw in fields:
            check()
            raw._owner.value
            if raw._owner.scope is not snapshot._record.scope:
                raise ContractError('transport field has a foreign retained scope')
            digest = sha256()
            view = memoryview(raw)
            for at in range(0, len(raw), 65536):
                check()
                digest.update(view[at:at+65536])
            bindings[name] = dict(shape=shape, sha256=digest.hexdigest())
        encoded, record = canonical(bindings), snapshot._record.identity()
        sealed = snapshot._verified
        if sealed is not None and sealed[1] == record and sealed[2] == encoded:
            check()
            return sealed[0]
        digest = sha256(b'{"arrays":'+encoded+b',"metadata":')
        with snapshot._record.iter_json() as stream:
            for block in stream:
                with block:
                    check()
                    digest.update(block.value)
        digest.update(b'}')
        check()
        result = digest.hexdigest()
        object.__setattr__(snapshot, '_verified', (result, record, encoded))
        return result


def result_record(result):
    snapshot = result._snapshot
    if type(snapshot) is not CompactTransportSnapshot:
        return dict(result_id=result.result_id, **snapshot.descriptor())
    body = snapshot._record.root()
    header = RecordCodec().pack_record(dict(result_id=result.result_id),
        record_schema='atlas.transport-result-header.v1', scope=body.scope,
        check=snapshot._record._check)
    return _ObjectRecordRef(body, overlay=header.root())


def retain(result, size, budget, ordinary):
    if type(result._snapshot) is CompactTransportSnapshot:
        if result._snapshot._record.scope.run_budget is not budget:
            raise ContractError('transport result has a foreign run budget')
        # The compact record, frozen fields and their carriers already own
        # their charges; the historical JSON allowance must not be duplicated.
        return
    return ordinary(result, size, budget)
