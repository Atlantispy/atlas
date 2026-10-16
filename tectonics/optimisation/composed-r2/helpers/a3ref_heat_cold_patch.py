"""Explicit bounded heat-ledger and completed-checkpoint access.

This module is shared by the r10 build transforms. It never turns a compact
ledger into JSON. A row carries its export owner through arithmetic, including
failed frames; successful readers release the index and their bounded fields.
"""
from contextlib import ExitStack, contextmanager, nullcontext
from hashlib import sha256
from types import SimpleNamespace

from compact_contracts import ContractError
from record_views import RecordRef
import spatial_validation_patch as V

ROW_BYTES = 4 << 20
_ARRAYS = frozenset(('cell_ids', 'face_ids', 'exact_corrected_enthalpy_j',
    'exact_paired_face_energy_j', 'exact_retained_solver_residual_j',
    'exact_stock_projection_residual_j', 'exact_cell_storage_residual_j'))


class _LedgerValue:
    """Keep an exact native pair alive and paid until its decoder releases it."""
    def __init__(self, owned):
        self.owner = owned

    @property
    def value(self):
        return self.owner.value


class _LedgerArray:
    def __init__(self, ref, stack, resources, cancel):
        self.ref, self.stack, self.resources, self.cancel = ref, stack, resources, cancel

    def __len__(self):
        return self.ref.size

    def __getitem__(self, index):
        self.resources.check(self.cancel)
        if type(index) is not int or not 0 <= index < len(self):
            raise IndexError(index)
        with self.ref.at(index) as row:
            owned = (row.scalar(max_owned_bytes=ROW_BYTES) if row.kind == 'scalar' else
                     row.export(max_logical_bytes=ROW_BYTES, max_owned_bytes=ROW_BYTES))
            return _LedgerValue(owned)

    def __iter__(self):
        for at in range(len(self)):
            yield self[at]

    def __eq__(self, other):
        if isinstance(other, _LedgerArray):
            return self.ref.identity().sha256 == other.ref.identity().sha256
        if type(other) not in (list, tuple) or len(other) != len(self):
            return False
        return all(left.value == right for left, right in zip(self, other, strict=True))


class _LedgerObject:
    def __init__(self, ref, stack, resources, cancel):
        self.ref, self.stack, self.resources, self.cancel = ref, stack, resources, cancel
        self.cache = {}

    def __getitem__(self, key):
        self.resources.check(self.cancel)
        if key in self.cache:
            return self.cache[key]
        child = self.ref.field(key)
        self.stack.callback(child.close)
        if child.kind == 'object':
            value = _LedgerObject(child, self.stack, self.resources, self.cancel)
        elif key in _ARRAYS and child.kind == 'array':
            value = _LedgerArray(child, self.stack, self.resources, self.cancel)
        else:
            owned = (child.scalar(max_owned_bytes=ROW_BYTES) if child.kind == 'scalar'
                     else child.export(max_logical_bytes=ROW_BYTES, max_owned_bytes=ROW_BYTES))
            self.stack.enter_context(owned)
            value = owned.value
        self.cache[key] = value
        return value

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __iter__(self):
        with self.ref.keys(max_owned_bytes=ROW_BYTES) as keys:
            yield from keys.value

    def __eq__(self, other):
        if isinstance(other, _LedgerObject):
            return self.ref.identity().sha256 == other.ref.identity().sha256
        if type(other) is not dict:
            return False
        with self.resources.codec_for_value(other, budget=self.ref.scope.run_budget, cancel=self.cancel):
            return self.ref.identity().sha256 == self.resources.stream_hash(other, self.cancel)


@contextmanager
def ledger_access(snapshot, budget, cancel, resources):
    """Yield a .value accessor; native snapshots retain the exact r4 branch."""
    from heat_ledger_tables import CompactHeatSnapshot
    resources.check(cancel)
    if type(snapshot) is not CompactHeatSnapshot:
        with resources.decoded(snapshot._metadata, budget=budget, cancel=cancel) as view:
            yield view
        return
    if snapshot.scope.run_budget is not budget:
        raise ContractError('compact heat ledger has another resource owner')
    stack = ExitStack()
    ref = snapshot.ledger
    stack.callback(ref.close)
    view = SimpleNamespace(value=_LedgerObject(ref, stack, resources, cancel))
    try:
        yield view
    except BaseException:
        # Tracebacks retain the accessor and its export owners until discarded.
        raise
    else:
        view.value.cache.clear()
        stack.close()


def ledger_arithmetic(resources):
    """Only unwrap the owned row; every numerical operation stays inherited."""
    class Arithmetic(resources._ProjectionArithmetic):
        def decode(self, value):
            if type(value) is _LedgerValue:
                return super().decode(value.value)
            return super().decode(value)
    return Arithmetic


def ledger_codec(view, budget, cancel, resources):
    return (nullcontext() if isinstance(view.value, _LedgerObject)
            else resources.codec(view, budget=budget, cancel=cancel))


def call_identity(origin, arrays, resources, cancel):
    """Stream the original call wrapper in the native canonical key order."""
    from record_tables import canonical
    descriptors = {name: dict(shape=list(value.shape),
        sha256=sha256(memoryview(value).cast('B')).hexdigest()) for name, value in arrays.items()}
    if not isinstance(origin, _LedgerObject):
        return resources.stream_hash(dict(metadata=origin, arrays=descriptors), cancel)
    # The wrapper descriptors are tiny but nevertheless paid before encoding.
    with resources.codec_for_value(descriptors, budget=origin.ref.scope.run_budget, cancel=cancel):
        digest = sha256(b'{"arrays":'+canonical(descriptors)+b',"metadata":')
        with origin.ref.iter_json() as stream:
            for block in stream:
                with block:
                    resources.check(cancel)
                    digest.update(block.value)
        digest.update(b'}')
        return digest.hexdigest()


@contextmanager
def state_view(snapshot, budget, cancel, resources):
    """Small indexed state header plus a borrowed compact cell row source."""
    from spatial_indexed_patch import IndexedSpatialSnapshot
    resources.check(cancel)
    if type(snapshot) is not IndexedSpatialSnapshot:
        with resources.decoded(snapshot._metadata, budget=budget, cancel=cancel) as view:
            yield view
        return
    if snapshot._budget is not budget:
        raise ContractError('indexed heat context has another resource owner')
    stack = ExitStack()
    try:
        # The paid plain copy respects resources r4's exact-bytes contract.
        stack.enter_context(budget.reserve(65536+len(snapshot._metadata),
                                          category='private-cold-indexed-metadata'))
        view = stack.enter_context(resources.decoded(bytes(snapshot._metadata), budget=budget, cancel=cancel))
        if snapshot._cells is not None:
            if 'cells' in view.value:
                raise ContractError('compact state contains duplicate cell representations')
            cells = snapshot._cells.borrow()
            stack.callback(cells.close)
            view.value['cells'] = V.rows(cells)
        yield view
    except BaseException:
        raise
    else:
        stack.close()


def snapshot_charge(record, arrays, ordinary):
    """Compact state data already owns its cells/mesh on the common scope."""
    import spatial_validation_patch as validation
    if type(record) is dict or not validation.is_state_record(record):
        return ordinary(record, arrays)
    # The native restored snapshot retains the same compact references; only
    # the existing numeric-array copy and small header need additional charge.
    from spatial_indexed_patch import retained_metadata_nbytes
    import numpy as np
    if any(type(v) is not np.ndarray or v.dtype != np.dtype('float64') for v in arrays.values()):
        raise ValueError('Native float64 snapshot fields required')
    return 65536+4*retained_metadata_nbytes(record)+4*sum(v.nbytes for v in arrays.values())+8192*len(arrays)


def native_plan(value, stack):
    ref = V._reference(value)
    if not isinstance(ref, RecordRef):
        return value
    return stack.enter_context(ref.export(max_logical_bytes=ROW_BYTES, max_owned_bytes=ROW_BYTES)).value


def owned_plan_bytes(plan, work, budget, cancel, resources, encode):
    # This bounded retained copy outlives the validation export which supplied
    # it. Keep its booking on the returned binding's existing workspace.
    work.stack.enter_context(budget.reserve(ROW_BYTES+65536, category='private-cold-retained-plan'))
    with resources.codec_for_value(plan, budget=budget, cancel=cancel):
        encoded = encode(plan)
    if len(encoded) > ROW_BYTES:
        raise ContractError('restored heat plan exceeds bounded retained representation')
    return encoded


class _CellLookup:
    """Paid ID-to-row index; endpoint row bodies remain in compact columns."""
    def __init__(self, rows):
        from content_cache import ChargeSpec
        self.ref = rows.ref
        count = self.ref.size
        with self.ref.scope.reserve(ChargeSpec('heat-endpoint-cell-index', 4096+2048*count)) as reservation:
            index = {}
            for at in range(count):
                with self.ref.at(at) as row, row.field('cell_id') as field, field.scalar(max_owned_bytes=65536) as cell:
                    key = cell.value
                    if type(key) is not str or len(key) > 256:
                        raise ContractError('bounded endpoint cell identity required')
                    # The new string is covered by the index's own reservation.
                    index[(' '+key)[1:]] = at
            self.owner = reservation.commit(index)

    def __getitem__(self, key):
        with self.ref.at(self.owner.value[key]) as row:
            owned = row.export(max_logical_bytes=ROW_BYTES, max_owned_bytes=ROW_BYTES)
            return V._OwnedRow(owned.value, owned)


def endpoint_cells(rows):
    return _CellLookup(rows) if isinstance(rows, V._Rows) else {row['cell_id']: row for row in rows}


def transform(source):
    """Cold bridge after W.private_heat_cold_source and PWT.cold_source."""
    if '\nimport heat_cold_patch as _HC' in source:
        raise ContractError('compact heat cold bridge already transformed')
    source = V._replace(source, 'import private_heat_restored_binding_ram_recovery_r1 as B',
                        'import private_heat_restored_binding_r10 as B')
    source = V._function(source, 'restore_checkpoint', (
        ('type(exchange) is not dict', 'not _SV.is_record(exchange)'),
    ), scope='with _SV.access(exchange) as exchange:')
    source = V._function(source, '_restore_parent', (
        ('_snapshot_charge(old, exterior_arrays)',
         '_HC.snapshot_charge(old, exterior_arrays, _snapshot_charge)'),
    ))
    # All earlier indexed-mesh and lineage checks remain in place.
    result = source.rstrip()+'\nimport heat_cold_patch as _HC\nimport spatial_validation_patch as _SV\n'
    compile(result, '<compact-heat-cold>', 'exec')
    return result
