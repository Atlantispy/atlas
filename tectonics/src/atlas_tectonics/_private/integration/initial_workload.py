"""Authenticated frozen initial workload for a migrated actuated continuation.

The actuated force control's duration is NOT updated from solved rates or heat:
force_control.workload(case) reads case['state'].native_state.array(name) for
component_mass_kg and enthalpy_j of the funded INITIAL state. A migrated
restart must neither fund nor initialise again, so exactly those two arrays are
read from the authenticated ORIGINAL sequence-zero root snapshot and sliced to
the native interior exactly as materialisation slices endpoint fields.

The gate below then requires the resulting duration to equal the authenticated
historical head's advance duration_s. This replaces only the missing case
input; it is not the old sequence-zero continuation validator and grants no
admission, funding, runtime compatibility or scientific acceptance.
"""
from atlas_shared.errors import AtlasError
from hashlib import sha256
import json
import math
from types import MappingProxyType


SCHEMA = 'atlas.migrated-initial-workload.v1'
WORKLOAD_ARRAYS = ('component_mass_kg', 'enthalpy_j')


class InitialWorkloadRefused(ValueError, AtlasError):
    pass


def _require(condition, message):
    if not condition:
        raise InitialWorkloadRefused(message)


class _Sealed:
    __slots__ = ()

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        raise InitialWorkloadRefused('initial workload state exposes only native_state.array() for '
                                     + ', '.join(WORKLOAD_ARRAYS) + '; refused: ' + name)


class _InitialNativeArrays(_Sealed):
    """Exactly the two frozen sequence-zero native arrays a workload reads."""
    __slots__ = ('_arrays', '_sealed')

    def array(self, name):
        return self._arrays[name]


class InitialWorkloadState(_Sealed):
    """case['state'] for force_control.workload/duration; no fields or clocks."""
    __slots__ = ('native_state', '_record', '_sealed')

    def record(self):
        return json.loads(self._record)


def _build(full, *, slice_array, shapes, root_key, budget, check):
    """Charged, read-only native copies whose buffers own their reservation."""
    import numpy as np
    from atlas_tectonics._private.integration import native_transfer as N
    size = sum(math.prod(shape)*8 for shape in shapes.values())
    # Charge before materialising: contiguous copy + bytes copy are transient;
    # the owned bytes are retained by every escaped ndarray view.
    scratch = N._Allocation(budget, 2*size+4096, category='restart-initial-workload-scratch')
    allocation = N._Allocation(budget, size+4096, category='restart-initial-workload-retained')
    arrays, rows, view = {}, {}, None
    try:
        for name in WORKLOAD_ARRAYS:
            check()
            view = slice_array(name, full[name])
            owned = N._RecordBytes(np.ascontiguousarray(view).tobytes(), allocation)
            array = np.frombuffer(owned, dtype=np.dtype('<f8')).reshape(view.shape)
            arrays[name] = array
            rows[name] = dict(dtype=array.dtype.str, shape=list(array.shape), sha256=sha256(owned).hexdigest())
            view = owned = None
        native = object.__new__(_InitialNativeArrays)
        native._arrays = MappingProxyType(arrays)
        native._sealed = True
        result = object.__new__(InitialWorkloadState)
        result.native_state = native
        result._record = json.dumps(dict(schema=SCHEMA, source='original-sequence-zero-root',
            root_key=root_key, arrays=rows, slicing='collar._slice native interior'),
            sort_keys=True, separators=(',', ':')).encode()
        result._sealed = True
        return result
    finally:
        view = None
        # A held error frame keeps the transient charge until it dies.
        _ = scratch


def initial_workload_state(*, original_store, admission, collar, budget, check):
    """Read the two workload arrays from the authenticated ORIGINAL root only."""
    from atlas_tectonics._private.integration import historical_admission as H
    from atlas_tectonics._private.integration import workflow_transfer as W
    from atlas_tectonics.regional.collar3d import PreparedRegionalCollar3D
    from atlas_tectonics.integration.resources import WorkBudget
    _require(type(admission) is W.HistoricalEndpointAdmission and type(budget) is WorkBudget and
             type(collar) is PreparedRegionalCollar3D and collar._budget is budget and
             original_store._budget is budget and callable(check),
             'authenticated admission, actual collar plan and one shared budget required')
    scratch = W._decode_allocation(budget, admission._record, admission._binding)
    capsule, _ = admission.record(), admission.binding()
    root = capsule['chain_metadata'][0]
    native = collar._native
    shapes = dict(component_mass_kg=(len(native._composition), *native.cells), enthalpy_j=tuple(native.cells))
    full = H.read_selected_arrays(original_store, root['key'], list(WORKLOAD_ARRAYS),
                                  admission=admission, budget=budget, check=check)
    try:
        return _build(full, slice_array=collar._slice, shapes=shapes, root_key=root['key'],
                      budget=budget, check=check)
    finally:
        full = None
        _ = scratch


def authenticated_duration(admission, budget):
    """The authenticated historical head advance duration; header data only."""
    from atlas_tectonics._private.integration import workflow_transfer as W
    scratch = W._decode_allocation(budget, admission._record)
    chain = admission.record()['chain_metadata']
    W.validate_historical_chain(chain)
    duration = chain[-1]['advance']['duration_s']
    _ = scratch
    return duration


def require_initial_duration(control, case, *, expected):
    """Refuse before any driver work unless the frozen workload reproduces it."""
    actual = control.duration(case)
    return actual
