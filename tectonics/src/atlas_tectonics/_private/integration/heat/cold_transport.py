"""Candidate retained compact transport for the independent cold reader.

Not wired to a selected package or authorised for a diagnostic run.
"""
from contextlib import ExitStack, contextmanager
import sys

import numpy as np

from atlas_tectonics._private.codecs.compact_contracts import ContractError
from atlas_tectonics._private.codecs.content_cache import ChargeSpec
from atlas_tectonics._private.integration.live_transport_result import (
    CompactTransportSnapshot, _FieldBytes, identity,
)
from atlas_tectonics._private.codecs.heat_ledger_tables import own_field
from atlas_tectonics._private.codecs.record_tables import Scratch
from atlas_tectonics._private.integration.geometry import spatial_validation_patch as spatial


class _MutableField(bytearray):
    """Mutable backing whose aliases retain the real scope allocation."""
    def __init__(self, size, owner):
        object.__setattr__(self, '_owner', owner.retain())
        super().__init__(size)

    def __setattr__(self, name, value):
        raise ContractError('immutable mutable-field ownership')

    def __delattr__(self, name):
        raise ContractError('immutable mutable-field ownership')


def mutable_float64(count, scope):
    """Reserve before creating a one-dimensional float64 staging buffer."""
    if type(count) is not int or count < 0 or count > (512 << 20)//8:
        raise ContractError('bounded nonnegative float64 count required')
    size = 8*count
    with scope.reserve(ChargeSpec('cold-projection-builder', 65536+size+(size >> 3)), required=True) as reserved:
        owner = reserved.commit(None)
        try:
            raw = _MutableField(size, owner)
        finally:
            owner._retire()
    return np.frombuffer(raw, dtype=np.float64)


def freeze_float64(array, scope):
    """Freeze C-order field bytes under an independent escaped-base owner."""
    raw = own_field(memoryview(array).cast('B') if array.size else b'', scope=scope)
    return np.frombuffer(raw, dtype=np.float64)


def compact_inputs(ar, transport, mesh, component_count, cp, scope):
    """Candidate bounded projection with separately owned output backings."""
    keys = transport['cell_ids']
    with transport.ref.field('cell_ids') as key_ref:
        key_width = key_ref._logical_length()
        count = key_ref.size
    # The selected CPython dict uses power-of-two tables at <=2/3 load.
    # Two copies of an upper-bounded table coexist during growth. Account
    # separately for retained decoded IDs, index integers, one scalar export
    # and the at-most-one exact-pair export used by the loop.
    slots = 8
    while 2*slots//3 < count:
        slots *= 2
    index_bytes = (65536 + 64*slots + 4*key_width +
                   count*(512 + sys.getsizeof(max(count-1, 0))) + (4 << 20))
    budget = scope.run_budget
    scratch = Scratch(budget, index_bytes)
    positions = {}
    key = None
    try:
        for at, key in enumerate(keys):
            positions[key] = at
        fields = transport['exact_stocks']
        field_stack = ExitStack()
        if isinstance(fields, spatial._Lazy):
            # Keep projection-created component-name cache entries scoped to
            # this operation, rather than on the longer-lived transport view.
            fields = spatial._Lazy(fields.ref, field_stack)
        components = range(component_count)
        name_bytes = 4096 + len(components)*(256 + 4*len(str(max(component_count-1, 0))))
        names = Scratch(budget, name_bytes)
        try:
            thermal = mesh['cells']
            output_count = len(thermal)
            enthalpy = mutable_float64(output_count, scope)
            capacity = mutable_float64(output_count, scope)
            source = mutable_float64(output_count, scope)
            for output_at, row in enumerate(thermal):
                ar.check()
                try:
                    at = positions[row['logical_cell_id']]
                except KeyError as error:
                    # The actual indexed row owns the decoded ID. Retain it
                    # through the guarded reader's exception handling; keep the
                    # original KeyError and argument unchanged.
                    error._cold_owned_row = row
                    raise
                enthalpy[output_at] = ar.public(ar.decode(fields['enthalpy_j'][at]))
                mass = 0
                for i in components:
                    mass = ar.op('add', mass, ar.decode(fields[f'component_mass_kg:{i}'][at]))
                capacity[output_at] = float(ar.public(mass)*cp)
                del mass
            result = dict(input_enthalpy_j=freeze_float64(enthalpy, scope),
                          input_capacity_j_k=freeze_float64(capacity, scope),
                          input_source_w=freeze_float64(source, scope))
            # On failure, a decoder traceback can still borrow a child. Keep
            # this accessor and its paid owners in the failing frame instead
            # of masking that failure by closing a live borrow.
            if isinstance(fields, spatial._Lazy) and fields.stack is field_stack:
                fields.cache.clear()
            field_stack.close()
            return result
        except BaseException as error:
            error._cold_component_workspace = names
            raise
    except BaseException as error:
        error._cold_index_workspace = scratch
        raise
    finally:
        positions.clear()
        key = keys = None


@contextmanager
def cold_transport(record, arrays, budget, *, expected_id, check):
    """Borrow a same-scope projection and freeze all arrays before exposing it."""
    scope = record.scope
    check()
    with ExitStack() as stack:
        projection = record.without(('result_id',))
        stack.callback(projection.close)
        with record.field('result_id') as result_ref:
            with result_ref.scalar(max_owned_bytes=1 << 20) as result:
                if result.value != expected_id:
                    raise ContractError('embedded transport identity differs')
        # The sort, growing tuple inventory and names coexist with the field
        # owners. Account for them before constructing any of those objects.
        stack.enter_context(budget.reserve(
            65536 + 2048*len(arrays) + 32*sum(len(k) for k in arrays),
            category='private-cold-transport-array-index'))
        owned = []
        try:
            for name, array in sorted(arrays.items()):
                check()
                # Charge both the C-order temporary and the immutable copy
                # before either exists. Escaped numpy bases retain the owner.
                charge = 65536 + 2 * array.nbytes + (array.nbytes >> 3)
                with scope.reserve(ChargeSpec('cold-transport-field', charge), required=True) as reserved:
                    owner = reserved.commit(None)
                    try:
                        raw = _FieldBytes(array.tobytes(order='C'), owner)
                    finally:
                        owner._retire()
                owned.append((name, tuple(array.shape), raw))
            size = 16384 + sum(1024 + 32 * len(shape) for _, shape, _ in owned)
            with scope.reserve(ChargeSpec('cold-transport-arrays', size), required=True) as reserved:
                fields = reserved.commit(tuple(owned))
            stack.callback(fields.close)
            snapshot = CompactTransportSnapshot(projection, fields, expected_id)
            from atlas_tectonics._private.codecs.compact_contracts import proving
            if proving():    # proof mode only; LTR.identity itself is never gated (F-3)
                identity(snapshot, budget, cancel=lambda: (check(), False)[1])
            yield snapshot
        finally:
            owned.clear()
