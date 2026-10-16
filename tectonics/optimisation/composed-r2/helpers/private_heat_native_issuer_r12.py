"""PRIVATE genuine forward producer binding, not native heat dispatch.

Only actual owner-derived calls (or explicitly marked internal test fixtures)
can invoke the one fixed standalone producer. No saved result, numerical
callback or replay API is accepted. The immutable exact-transfer result binds
the real input snapshot, plan, source stage, geometry, duration and scipy
ExecutionContext. Fixture output never claims actual-owner origin.

Projection, call, codec and retained snapshot worksets are derived from actual
operands; the fixed forward producer separately owns its derived stages. These
are accounted policies, NOT allocator/RSS or native whole-method acceptance. Native dispatch, the heat hold and production acceptance
remain unchanged. This is a non-hostile Python trust boundary, like native
issuance; it is not a sandbox against object.__new__ or arbitrary Python.

Decoded JSON views follow resources r4: a derived decode inventory, the stream
codec booked only while a snapshot identity is hashed, and one complete decode
at a time while an owner call is bound. The fixed producer is F10, which is F9
with the same derived inventory for its startup decode. Physics, checks and
identities of the r8 binding are otherwise unchanged.

R10 is R9 with the fixed producer F11: F10 with the precision choice of its
selective refinement corrected, as that kernel describes. Nothing else differs.

R11 is R10 with the fixed producer F12: F11 on numerical modules that hold a
result that exists at what it occupies, as that kernel describes. Nothing else differs.

R12 is R11 with the fixed producer F13: F12 metered by the process meter where
that supports the runtime, as that kernel describes. Nothing else differs.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib
import json
import math
from pathlib import Path
from types import ModuleType, FunctionType
import sys
import weakref

import numpy as np
import private_heat_native_projection_r4 as N
import private_heat_indexed_runtime as INDEXED
import private_heat_mesh_patch as INDEXED_INPUTS
import mesh_tables as INDEXED_TABLES
import exterior_mesh_patch as INDEXED_EXTERIOR
import spatial_indexed_patch as INDEXED_SPATIAL
import native_transfer as INDEXED_NATIVE_TRANSFER
import spatial_transfer as INDEXED_SPATIAL_TRANSFER
import private_heat_issuer_resources_r4 as RESOURCES
import private_heat_forward_kernel_r13 as F
import private_heat_loaded_identity_r1 as LOADED_IDENTITY
import private_heat_certification_kernel_r1 as CERT
import private_heat_functionals_kernel_r1 as FUNCTIONS
from atlas_tectonics.integration_exterior_mesh import ExteriorMesh
from atlas_tectonics.integration_mimetic_heat import MimeticGeometry, _enc, _hash, _json, _q
from atlas_tectonics.integration_regional_inventory import _project, _width
from atlas_tectonics.integration_spatial_owner import PreparedSpatialOwner, SpatialOwnerTransport
from atlas_tectonics.integration_spatial_transport import _json_encoding_capacity, _workspace
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics import exact_arithmetic

HERE = Path(__file__).resolve().parent
_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
METHOD = 'private:uniform-k-composed-forward-contract.r12'
SCHEMA = 'atlas.private.composed-heat-advance.r12'
# Exactly the fields bind_owner_call and owner_projection_bytes read from the
# closed graph, the transported state and, after its metric exists, the mesh.
_GRAPH_FIELDS = {key: RESOURCES.ALL for key in (
    'start_time_s', 'end_time_s', 'source_flow_stage_id', 'funding_id', 'source',
    'end_support_id', 'grid_id', 'trajectory_id')}
_GRAPH_FIELDS['cells'] = RESOURCES.Rows(dict(cell_id=RESOURCES.ALL, end_volume_m3=RESOURCES.ALL))
_TRANSPORT_FIELDS = dict(source_stage_id=RESOURCES.ALL, state_id=RESOURCES.ALL,
                         cell_ids=RESOURCES.ALL, exact_stocks=RESOURCES.ALL)
_MESH_FIELDS = dict(cells=RESOURCES.Rows(dict(cell_id=RESOURCES.ALL)))


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Private composed issuance cancelled')


def _target_text(value, cancel=None):
    if type(value) is float:
        value = Decimal.from_float(value)
    F.INVENTORY._target_metadata(value, cancel)
    return str(value) if type(value) is Decimal else value


def _target_provenance(value):
    if type(value) is float:
        return dict(kind='represented-binary64', value=value.hex())
    if type(value) is Decimal:
        return dict(kind='Decimal', value=str(value))
    if type(value) is str:
        return dict(kind='decimal-string', value=value)
    raise ValueError('Original target must be float, Decimal or decimal string; no rational rounding')


def _validate_target_plan(plan):
    original = plan['original_target']
    if original['kind'] == 'represented-binary64':
        value = float.fromhex(original['value'])
    elif original['kind'] == 'Decimal':
        value = Decimal(original['value'])
    elif original['kind'] == 'decimal-string':
        value = original['value']
    else:
        raise ValueError('Unknown original target provenance')
    text = _target_text(value)
    if (text != plan['absolute_residual_target_decimal']
            or Fraction(text) != _q(plan['absolute_residual_target'])):
        raise ValueError('Original tagged target, decimal and exact target differ')


def _private_modules():
    """Only this fixed standalone dependency graph, not unrelated probes."""
    pending, modules = [sys.modules[__name__], N, F, CERT, FUNCTIONS, LOADED_IDENTITY,
                        INDEXED, INDEXED_INPUTS, INDEXED_TABLES, INDEXED_EXTERIOR, INDEXED_SPATIAL,
                        INDEXED_NATIVE_TRANSFER, INDEXED_SPATIAL_TRANSFER], {}
    # Load fixed late numerical/resource dependencies before identity capture.
    # Historical pinned kernels may be included conservatively; no unrelated probes.
    pending.extend(importlib.import_module(Path(path).stem) for path in F._SOURCES
                   if Path(path).parent == HERE and Path(path).stem.startswith('private_heat_'))
    pending.extend(importlib.import_module(name) for name in
                   ('private_heat_gmp_resources_r1', 'private_heat_sparse_resources_r1'))
    while pending:
        module = pending.pop()
        if module.__name__ in modules:
            continue
        modules[module.__name__] = module
        pending.extend(value for value in tuple(vars(module).values())
                       if type(value) is ModuleType and value.__name__.startswith('private_heat_')
                       and Path(value.__file__).resolve().parent == HERE)
    return tuple(modules.values())


def _sources():
    """Actual fixed dependencies; late resource imports also pinned now."""
    paths = {Path(module.__file__).resolve() for module in _private_modules()}
    paths.update(Path(path) for path in F._SOURCES)
    paths.update((HERE/'private_heat_gmp_resources_r1.py', HERE/'private_heat_sparse_resources_r1.py'))
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def _functions():
    for module in _private_modules():
        for name, value in tuple(vars(module).items()):
            if type(value) is FunctionType:
                yield module, name, value, value.__code__, repr(value.__defaults__), repr(value.__kwdefaults__)
            elif isinstance(value, type) and value.__module__.startswith('private_heat_'):
                for key, method in tuple(vars(value).items()):
                    if type(method) is FunctionType:
                        yield value, key, method, method.__code__, repr(method.__defaults__), repr(method.__kwdefaults__)


def _verify_implementation():
    _LOADED_IMPLEMENTATION.verify(m for m in _private_modules() if m is not sys.modules[__name__])
    for module, name, value in _IMPORTED_CLASSES:
        if getattr(module, name) is not value:
            raise ValueError('Fixed private producer class binding changed')
    for module, name, function, code, defaults, keywords in _IMPORTED_FUNCTIONS:
        if (getattr(module, name) is not function or function.__code__ is not code
                or repr(function.__defaults__) != defaults or repr(function.__kwdefaults__) != keywords):
            raise ValueError('Fixed private producer implementation changed; no callback replacement')


def _snapshot_identity(snapshot, budget, cancel=None):
    _check(cancel)
    if type(snapshot) is INDEXED_SPATIAL.IndexedSpatialSnapshot:
        if snapshot._budget is not budget:
            raise ValueError('indexed snapshot has a foreign resource owner')
        return INDEXED_SPATIAL.snapshot_identity(snapshot)
    return _legacy_snapshot_identity(snapshot, budget, cancel)


def _legacy_snapshot_identity(snapshot, budget, cancel=None):
    with RESOURCES.decoded(snapshot._metadata, budget=budget, cancel=cancel) as owner:
        with RESOURCES.workspace(budget, 65536+1024*(len(snapshot._fields)+1), cancel=cancel), \
                RESOURCES.codec(owner, budget=budget, cancel=cancel):
            return RESOURCES.stream_hash(dict(metadata=owner.value, arrays={
                name: dict(shape=shape, sha256=hashlib.sha256(raw).hexdigest())
                for name, shape, raw in snapshot._fields}), cancel)


def _origin_signature(owner, step, mesh):
    """Recompute native immutable identities; do not trust only cached IDs."""
    owner._verify()
    if (step._owner is not owner or step.source._owner is not owner._collar
            or step.result._budget is not owner._budget or step.graph._resource is not owner._budget
            or mesh._resource is not owner._budget):
        raise ValueError('Actual native owner origin has foreign source or resource owner')
    snapshots = (step.result._snapshot, step.parent._snapshot, step.source.inventory,
                 step.source.source_stage.inventory)
    if any(snapshot.result_id != _snapshot_identity(snapshot, owner._budget) for snapshot in snapshots):
        raise ValueError('Actual native owner origin snapshot changed')
    return dict(owner_id=owner.owner_id, owner_definition_id=_hash(owner._definition),
        funding_id=owner._funding.funding_id, component_count=owner._component_count,
        heat_capacity_j_kg_k=owner._collar._native._material.heat_capacity_j_kg_k,
        transport_id=step.result_id, state_id=step.result.result_id,
        parent_state_id=step.parent.state_id, source_stage_id=step.source.result_id,
        source_inventory_id=step.source.inventory.result_id,
        native_source_inventory_id=step.source.source_stage.inventory.result_id,
        graph_id=step.graph.geometry_id, thermal_mesh_id=mesh.geometry_id,
        duration_s=float(step.source.duration_s))


def _new_snapshot(metadata, arrays, budget, owner, attribute):
    """Admit immutable storage and native JSON/array copies BEFORE creation."""
    encoded, codec = _json_encoding_capacity(metadata, budget)
    payload = sum(value.nbytes for value in arrays.values())
    retained = 2048+encoded+payload+512*len(arrays)
    with _workspace(budget, codec+2*payload+65536, 'private-heat-snapshot-codec') as work:
        work.enter_context(budget.reserve(retained, category='private-heat-snapshot-retained'))
        snapshot = RegionalMechanicalSnapshot(metadata, arrays)
        if snapshot.nbytes > retained:
            raise ArithmeticError('Native snapshot exceeded admitted retained envelope')
        object.__setattr__(owner, attribute, snapshot)
        # ExitStack cannot detach one context. A separately reserved owner lease
        # below overlaps until the construction stack closes, never undercharges.
        owned = budget.reserve(retained, category='private-heat-snapshot-owned')
        owned.__enter__()
        try:
            weakref.finalize(owner, owned.__exit__, None, None, None)
        except BaseException:
            owned.__exit__(None, None, None)
            raise
    return snapshot


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class OwnerHeatCall:
    _snapshot: object = field(repr=False)
    _geometry: object = field(repr=False)
    _budget: object = field(repr=False)
    _execution: object = field(repr=False)
    _origin_objects: tuple = field(repr=False)
    _plan: bytes = field(repr=False)
    _bindings: tuple = field(repr=False)
    _fixture: bool

    def __init__(self, *args, **kwargs):
        raise TypeError('Call origins are derived from actual native owner objects')

    @property
    def call_id(self):
        return self._snapshot.result_id

    def descriptor(self):
        return self._snapshot.descriptor()


def _make_call(metadata, arrays, geometry, execution, plan, origins, *, fixture=False):
    """Internal construction; fixture origins are NEVER owner-admitted."""
    if type(geometry) is not MimeticGeometry or type(execution) is not ExecutionContext:
        raise TypeError('Issued metric and actual ExecutionContext required')
    if execution.backend != 'scipy':
        raise ValueError('The actual SuperLU runtime must be bound by a scipy context')
    if exact_arithmetic.library() is not N.A.A.exact_library():
        raise ValueError('The GMP library used by this private projection is not the selected bound native backend')
    execution.verify_boundary()
    budget = geometry._budget
    if type(budget) is not WorkBudget:
        raise TypeError('One native resource owner required')
    plan_bytes, plan_codec = _json_encoding_capacity(plan, budget)
    target_work = RESOURCES.target_bytes(plan['absolute_residual_target_decimal'], budget=budget)
    identity_work = 65536+512*len(_IMPORTED_FUNCTIONS)+1024*len(_IMPORTED_SOURCES)
    with _workspace(budget, plan_bytes+plan_codec+target_work+identity_work, 'private-heat-call-definition'):
        _verify_implementation()
        out = object.__new__(OwnerHeatCall)
        for key, value in dict(_geometry=geometry, _budget=budget, _execution=execution,
                               _origin_objects=tuple(origins), _fixture=fixture).items():
            object.__setattr__(out, key, value)
        _validate_target_plan(plan)
        encoded = _json(plan)
        bindings = dict(_IMPORTED_SOURCES)
        for path, digest in bindings.items():
            if RESOURCES.source_hash(path) != digest:
                raise ValueError('Private dependency changed after import; no source repin')
        object.__setattr__(out, '_plan', encoded)
        object.__setattr__(out, '_bindings', tuple(bindings.items()))
        owned = budget.reserve(2048+len(encoded)+_width(bindings), category='private-heat-call-definition-owned')
        owned.__enter__()
        try:
            weakref.finalize(out, owned.__exit__, None, None, None)
        except BaseException:
            owned.__exit__(None, None, None)
            raise
        meta = dict(metadata, plan_id=hashlib.sha256(encoded).hexdigest(),
                    geometry_id=geometry.geometry_id, execution=execution.provenance,
                    private_sources=bindings, loaded_dependencies=_LOADED_IMPLEMENTATION.descriptor(),
                    fixture_only=fixture)
        _new_snapshot(meta, arrays, budget, out, '_snapshot')
    return out


def bind_owner_call(owner, step, mesh, *, boundary, absolute_residual_target,
                    execution, cancel=None):
    """Forward owner seam; does not reconstruct, solve or issue a heat result.

    Mirrors current owner heat checks and its EXACT binary capacity operation
    order. Sources were already booked by transport: this owner route uses zero
    added power. A future general source route needs its own genuine producer.
    Caller-specified boundary/target are physical/solver inputs, not provenance.
    """
    _check(cancel)
    if (type(owner) is not PreparedSpatialOwner or type(step) is not SpatialOwnerTransport
            or step._owner is not owner or type(mesh) is not ExteriorMesh
            or mesh._resource is not owner._budget):
        raise TypeError('Actual shared-budget owner, transport stage and exterior mesh required')
    if type(execution) is not ExecutionContext or execution.backend != 'scipy':
        raise TypeError('Actual scipy ExecutionContext required')
    execution.verify_boundary()
    target_work = RESOURCES.target_bytes(absolute_residual_target, budget=owner._budget, cancel=cancel)
    with RESOURCES.workspace(owner._budget, target_work+65536+512*len(_IMPORTED_FUNCTIONS)+
            1024*len(_IMPORTED_SOURCES), cancel=cancel, category='private-heat-owner-call') as scope:
        origin = _origin_signature(owner, step, mesh)
        target_text = _target_text(absolute_residual_target, cancel)
        target = Fraction(target_text)
        if target <= 0 or not math.isfinite(float(target)):
            raise ValueError('Original positive finite residual target required')
        # One complete decode at a time. The graph and the transported state
        # are read through compact owned copies of exactly the fields used
        # below; the mesh decode lives only until its metric exists.
        with RESOURCES.decoded(step.graph._json, budget=owner._budget, cancel=cancel) as gv:
            g = scope.stack.enter_context(RESOURCES.extracted(gv, _GRAPH_FIELDS,
                budget=owner._budget, cancel=cancel)).value
        with RESOURCES.decoded(step.result._snapshot._metadata,
                               budget=owner._budget, cancel=cancel) as tv:
            t = scope.stack.enter_context(RESOURCES.extracted(tv, _TRANSPORT_FIELDS,
                budget=owner._budget, cancel=cancel)).value
        if mesh.is_compact:
            return _bind_indexed_owner_call(owner, step, mesh, g=g, t=t, origin=origin,
                target=target, target_text=target_text, absolute_residual_target=absolute_residual_target,
                boundary=boundary, execution=execution, cancel=cancel)
        mv = scope.stack.enter_context(RESOURCES.decoded(mesh._json, budget=owner._budget, cancel=cancel))
        m = mv.value
        projection_bytes = RESOURCES.owner_projection_bytes(m, g, t, owner._component_count,
                                                            budget=owner._budget, cancel=cancel)
        scope.stack.enter_context(RESOURCES.workspace(owner._budget, projection_bytes,
            cancel=cancel, category='private-heat-owner-input-projection'))
        duration = float(step.source.duration_s)
        if (not math.isfinite(duration) or duration <= 0
                or _q(g['end_time_s'])-_q(g['start_time_s']) != Fraction(duration)
                or g['source_flow_stage_id'] != step.source.result_id
                or t['source_stage_id'] != step.source.result_id or t['state_id'] != step.parent.state_id):
            raise ValueError('Actual source, transported state and physical interval differ')
        # Native issued mesh/graph records need not carry an extra `source`
        # field. Their actual funding, source-stage and immutable graph chain
        # above is mandatory. An optional additional source must match on both.
        if (m['funding_id'] != owner._funding.funding_id or m['funding_id'] != g['funding_id']
                or ('source' in m) != ('source' in g) or m.get('source') != g.get('source')
                or m['support_id'] != g['end_support_id']
                or m['grid_id'] != g['grid_id'] or m['trajectory_id'] != g['trajectory_id']
                or m['time_s'] != g['end_time_s']):
            raise ValueError('Thermal geometry is not this transported endpoint')
        if 'booked_cell_rule' in m and (type(m['booked_cell_rule']) is not dict
                or m['booked_cell_rule'].get('closed_graph_id') != step.graph.geometry_id):
            raise ValueError('Thermal cells were booked by a different graph')
        positive = {r['cell_id'] for r in g['cells'] if _q(r['end_volume_m3']) > 0}
        if {r['logical_cell_id'] for r in m['cells']} != positive:
            raise ValueError('Every positive transported cell must remain represented')
        boundary = {} if boundary is None else dict(boundary)
        if not set(m.get('required_thermal_boundary_faces', ())).issubset(boundary):
            raise ValueError('Required physical boundaries must be explicitly supplied')
        columns = {key: i for i, key in enumerate(t['cell_ids'])}
        if len(columns) != len(t['cell_ids']):
            raise ValueError('Transported cell order contains duplicates')
        cp = owner._collar._native._material.heat_capacity_j_kg_k
        old, capacity = [], []
        for row in m['cells']:
            at = columns[row['logical_cell_id']]
            old.append(_project(_q(t['exact_stocks']['enthalpy_j'][at])))
            mass = np.asarray([_project(_q(t['exact_stocks']['component_mass_kg:'+str(i)][at]))
                               for i in range(owner._component_count)])
            capacity.append(float(np.sum(mass)*cp))
        k = float(owner._definition['conductivity_w_m_k'])
        if not math.isfinite(k) or k <= 0:
            raise ValueError('Uniform positive owner conductivity required')
        geometry = MimeticGeometry(m, budget=owner._budget)
        ids = {name: i for i, name in enumerate(geometry._face_ids)}
        for fid, entry in boundary.items():
            if fid not in ids or len(geometry._incidence[ids[fid]]) != 1:
                raise ValueError('Boundary must name an actual one-owner face')
            if type(entry) not in (list, tuple) or len(entry) != 2:
                raise ValueError('Typed thermal boundary pair required')
            kind, value = entry
            value = float(value)
            if not math.isfinite(value) or kind not in ('temperature', 'power') or kind == 'temperature' and value <= 0:
                raise ValueError('Finite physical boundary declaration required')
            boundary[fid] = [kind, value]
        # Last use of the complete mesh decode. The metric owns its encoding
        # and exact metrics, and its retained lease charges its face names
        # again. Cell names continue as an owned compact copy.
        cells = scope.stack.enter_context(RESOURCES.extracted(mv, _MESH_FIELDS,
            budget=owner._budget, cancel=cancel)).value['cells']
        del m, row
        mv.close()
        plan = dict(schema='atlas.private.composed-heat-plan.r1', method_id=METHOD,
                    geometry_id=geometry.geometry_id, conductivity_w_m_k=[k]*len(old),
                    absolute_residual_target=_enc(target), absolute_residual_target_decimal=target_text,
                    original_target=_target_provenance(absolute_residual_target),
                    boundary=boundary,
                    endpoint_face_trace_status=N.A.TRACE_STATUS)
        meta = dict(schema='atlas.private.composed-owner-call.r1', owner_id=owner.owner_id,
                    owner_definition_id=_hash(owner._definition), heat_capacity_j_kg_k=cp,
                    state_id=step.result.result_id, source_stage_id=step.source.result_id,
                    graph_id=step.graph.geometry_id, thermal_mesh_id=mesh.geometry_id,
                    duration_s=float(step.source.duration_s), cell_ids=[r['cell_id'] for r in cells],
                    source_policy='already-booked-transport; zero added heat source',
                    native_origin_signature=origin)
        arrays = dict(enthalpy_j=np.asarray(old), capacity_j_k=np.asarray(capacity),
                      source_w=np.zeros(len(old)))
        out = _make_call(meta, arrays, geometry, execution, plan,
                         (owner, step, mesh, step.result._snapshot))
        _verify_call(out, cancel)
        return out



def _bind_indexed_owner_call(owner, step, mesh, *, g, t, origin, target,
        target_text, absolute_residual_target, boundary, execution, cancel):
    # Called only after bind_owner_call's actual type/origin/runtime gates and
    # its owned graph/transport extraction. This does not admit supplied data.
    prepared = INDEXED_INPUTS.prepare_indexed_inputs(mesh, g, t,
        graph_id=step.graph.geometry_id, funding_id=owner._funding.funding_id,
        source_stage_id=step.source.result_id, parent_state_id=step.parent.state_id,
        duration_s=step.source.duration_s, component_count=owner._component_count,
        heat_capacity_j_kg_k=owner._collar._native._material.heat_capacity_j_kg_k,
        conductivity_w_m_k=owner._definition['conductivity_w_m_k'],
        boundary=boundary, budget=owner._budget, cancel=cancel)
    descriptor = prepared.descriptor()
    data = descriptor.value
    # Preparation's scratch was released on return. Fund the new plan/list
    # containers separately before constructing them; this frame retains the
    # allocation if an escaping exception keeps any of those objects alive.
    assembly = INDEXED_INPUTS._Allocation(owner._budget,
        65536+256*len(data['cell_ids']), 'indexed-heat-owner-call-assembly')
    arrays = {name: prepared.array(name) for name in
              ('enthalpy_j', 'capacity_j_k', 'source_w')}
    plan = dict(schema='atlas.private.composed-heat-plan.r1', method_id=METHOD,
        geometry_id=prepared.geometry.geometry_id,
        conductivity_w_m_k=[data['conductivity_w_m_k']]*len(arrays['enthalpy_j']),
        absolute_residual_target=_enc(target), absolute_residual_target_decimal=target_text,
        original_target=_target_provenance(absolute_residual_target), boundary=data['boundary'],
        endpoint_face_trace_status=N.A.TRACE_STATUS)
    meta = dict(schema='atlas.private.composed-owner-call.r1', owner_id=owner.owner_id,
        owner_definition_id=_hash(owner._definition),
        heat_capacity_j_kg_k=data['heat_capacity_j_kg_k'],
        state_id=step.result.result_id, source_stage_id=step.source.result_id,
        graph_id=step.graph.geometry_id, thermal_mesh_id=mesh.geometry_id,
        duration_s=float(step.source.duration_s), cell_ids=data['cell_ids'],
        source_policy='already-booked-transport; zero added heat source',
        native_origin_signature=origin)
    out = _make_call(meta, arrays, prepared.geometry, execution, plan,
                     (owner, step, mesh, step.result._snapshot))
    _verify_call(out, cancel)
    del meta, plan, arrays, data, descriptor, prepared
    del assembly
    return out

def _verify_call_record(call, meta, cancel=None):
    _check(cancel)
    if type(call) is not OwnerHeatCall:
        raise TypeError('A forward-issued owner call is required')
    call._execution.verify_boundary()
    _verify_implementation()
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
        raise ValueError('Private issuer source changed after import')
    for path, digest in call._bindings:
        if RESOURCES.source_hash(path) != digest:
            raise ValueError('Bound private source changed')
    if (call.call_id != _snapshot_identity(call._snapshot, call._budget, cancel)
            or meta['geometry_id'] != INDEXED.metric_identity(call._geometry, cancel=cancel)
            or meta['plan_id'] != hashlib.sha256(call._plan).hexdigest()
            or meta['private_sources'] != dict(call._bindings)
            or meta['loaded_dependencies'] != _LOADED_IMPLEMENTATION.descriptor()
            or meta['fixture_only'] is not call._fixture
            or call._geometry._budget is not call._budget
            or meta['execution'] != call._execution.provenance):
        raise ValueError('Actual caller snapshot, metric, plan or runtime changed')
    if not call._fixture:
        owner, step, mesh, snapshot = call._origin_objects
        if (step._owner is not owner or step.result._snapshot is not snapshot
                or _snapshot_identity(snapshot, owner._budget) != meta['state_id']
                or step.source.result_id != meta['source_stage_id']
                or float(step.source.duration_s) != meta['duration_s']
                or step.graph.geometry_id != meta['graph_id'] or mesh.geometry_id != meta['thermal_mesh_id']
                or owner.owner_id != meta['owner_id'] or mesh._resource is not call._budget
                or _hash(owner._definition) != meta['owner_definition_id']
                or owner._collar._native._material.heat_capacity_j_kg_k != meta['heat_capacity_j_kg_k']):
            raise ValueError('Actual native owner origin changed')
    if 'native_origin_signature' in meta:
        owner, step, mesh, snapshot = call._origin_objects
        if (step.result._snapshot is not snapshot
                or _origin_signature(owner, step, mesh) != meta['native_origin_signature']):
            raise ValueError('Actual native owner origin changed')
    elif call._fixture:
        if (len(call._origin_objects) != 1 or
                _snapshot_identity(call._origin_objects[0], call._budget, cancel) != meta['state_id']):
            raise ValueError('Explicit fixture snapshot changed')
    return meta


def _verified_call(call, cancel=None):
    if type(call) is not OwnerHeatCall:
        raise TypeError('A forward-issued owner call is required')
    view = RESOURCES.decoded(call._snapshot._metadata, budget=call._budget, cancel=cancel)
    try:
        with RESOURCES.workspace(call._budget, 65536+512*len(_IMPORTED_FUNCTIONS)+
                1024*len(_IMPORTED_SOURCES), cancel=cancel, category='private-heat-identity-work'):
            _verify_call_record(call, view.value, cancel)
        return view
    except BaseException:
        view.__exit__(*sys.exc_info())
        raise


def _verify_call(call, cancel=None):
    with _verified_call(call, cancel):
        pass


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class ComposedHeatResult:
    _snapshot: object = field(repr=False)
    _budget: object = field(repr=False)
    _geometry: object = field(repr=False)
    _plan_definition: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('Composed results are issued only by a forward producer')

    @property
    def result_id(self):
        return self._snapshot.result_id

    @property
    def nbytes(self):
        return self._snapshot.nbytes

    @property
    def array_names(self):
        return self._snapshot.array_names

    def descriptor(self):
        return self._snapshot.descriptor()

    def plan_descriptor(self):
        if hashlib.sha256(self._plan_definition).hexdigest() != self.descriptor()['plan_id']:
            raise ValueError('Immutable issuing plan differs')
        return json.loads(self._plan_definition)

    def array(self, name):
        if name == 'face_temperature_k':
            raise N.A.EndpointTraceUnavailable(N.A.TRACE_STATUS)
        return self._snapshot.array(name)


def advance(call, *, cancel=None):
    """Fixed forward producer only; derived owned stages, no manual allowance."""
    with _verified_call(call, cancel) as metadata_owner:
        meta = metadata_owner.value
        with RESOURCES.decoded(call._plan, budget=call._budget, cancel=cancel) as plan_owner:
            plan = plan_owner.value
            n = len(call._geometry._cells)
            with RESOURCES.workspace(call._budget, 65536+1024*(8*n+32), cancel=cancel,
                                     category='private-heat-call-array-copies'):
                return _advance_verified(call, meta, plan, cancel)


def _advance_verified(call, meta, plan, cancel):
    values = {name: call._snapshot.array(name).tolist() for name in call._snapshot.array_names}
    conductivity = plan['conductivity_w_m_k']
    if (len(conductivity) != len(values['enthalpy_j']) or not conductivity
            or any(k != conductivity[0] for k in conductivity)):
        raise ValueError('Only the original uniform conductivity is supported')
    with F.advance(call._geometry, values['enthalpy_j'], values['capacity_j_k'],
            meta['duration_s'], values['source_w'], plan['boundary'],
            conductivity=conductivity[0],
            absolute_residual_target=plan['absolute_residual_target_decimal'],
            budget=call._budget, cancelled=cancel) as numerical_owner:
        produced, diagnostics = numerical_owner.value
        _verify_call(call, cancel)
        projection_owner = N.project(produced, call._geometry, cell_ids=meta['cell_ids'],
            enthalpy_j=values['enthalpy_j'], capacity_j_k=values['capacity_j_k'],
            source_w=values['source_w'], duration_s=meta['duration_s'], state_id=meta['state_id'],
            absolute_residual_target=_q(plan['absolute_residual_target']), budget=call._budget, cancel=cancel)
        with projection_owner:
            projected, private = projection_owner.value
            fixed, powers = {}, {}
            for f, linked in enumerate(call._geometry._incidence):
                if len(linked) != 1:
                    continue
                kind, value = plan['boundary'].get(call._geometry._face_ids[f], ('power', 0.))
                if kind == 'temperature':
                    fixed[str(f)] = N._q(value)
                else:
                    powers[str(f)] = N._q(meta['duration_s'])*N._q(value)
            actual_fixed = {str(f): v for f, v in projected['boundary_exact']['boundary_temperature'].items()}
            actual_power = {str(f): v for f, v in projected['boundary_exact']['prescribed_boundary_energy'].items()}
            if (actual_fixed != fixed or any(actual_power.get(f, 0) != value for f, value in powers.items())
                    or not set(actual_power).issubset(powers)):
                raise ValueError('Produced result did not use the original physical boundary declarations')
            record = projected['metadata']
            record.pop('unverified_advance_context')
            record.update(schema=SCHEMA, method_id=METHOD, private_correction_method_id=private['method_id'],
                plan_id=meta['plan_id'], state_id=meta['state_id'], duration_s=meta['duration_s'],
                call_id=call.call_id, caller_snapshot=meta,
                origin_binding_status=('TEST_FIXTURE_NOT_NATIVE_OWNER' if call._fixture
                                       else 'FORWARD_ACTUAL_OWNER_SNAPSHOT'),
                genuine_forward_origin=not call._fixture,
                fixed_forward_producer='private_heat_forward_kernel_r13.advance',
                native_issue_performed=False, native_resource_admitted=False,
                whole_method_memory_inventory_certified=False, native_heat_dispatch_enabled=False,
                private_loaded_source_identity_certified=True,
                loaded_dependencies=meta['loaded_dependencies'],
                loaded_instructions_match_disk_source_not_asserted=True,
                production_acceptance=False, endpoint_face_trace_status=N.A.TRACE_STATUS,
                source_policy=meta['source_policy'],
                resource_scope='Derived call, projection, snapshot/codec and fixed-forward policies; not allocator/RSS or native admission')
            result = object.__new__(ComposedHeatResult)
            object.__setattr__(result, '_budget', call._budget)
            object.__setattr__(result, '_geometry', call._geometry)
            object.__setattr__(result, '_plan_definition', call._plan)
            lease = call._budget.reserve(1024+len(call._plan), category='private-heat-result-plan')
            lease.__enter__()
            try:
                weakref.finalize(result, lease.__exit__, None, None, None)
            except BaseException:
                lease.__exit__(None, None, None)
                raise
            _new_snapshot(record, {key: np.asarray(value, dtype=np.float64)
                          for key, value in projected['arrays'].items()}, call._budget, result, '_snapshot')
            _verify_call(call, cancel)
            # All borrowed numerical records die before their owning workspace.
            del produced, diagnostics, projected, private, record, fixed, powers, actual_fixed, actual_power
    _verify_call(call, cancel)
    return result


def issue_saved(*args, **kwargs):
    raise ValueError('Saved low/high/private results have no native forward origin; replay issuance is forbidden')


# Capture already imported dependencies ONCE, before a caller can request an
# origin. Reading a changed file at bind time must not silently repin old code.
_LOADED_IMPLEMENTATION = LOADED_IDENTITY.LoadedIdentity(
    m for m in _private_modules() if m is not sys.modules[__name__])
_IMPORTED_SOURCES = tuple(_sources().items())
_IMPORTED_FUNCTIONS = tuple(_functions())
_IMPORTED_CLASSES = tuple((module, name, value) for module in _private_modules()
    for name, value in tuple(vars(module).items())
    if isinstance(value, type) and value.__module__.startswith('private_heat_'))
