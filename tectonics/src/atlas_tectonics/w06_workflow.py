"""Atomic requested-output workflows for the supported W06 physical routes.

Each run owns one ocean or inherited-margin route, not a shared world reservoir.
ArrayStore provides lossless chunks and transactional publication. Restarts decode
only the newest requested output and never repeat a completed thermal solve.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import math
import numpy as np

from ._validation import TectonicsError, scalar, frozen
from .materials import _json, _name
from .constitutive import BoussinesqMaterial
from .thermal_support import ThermalSupportParameters
from .regional import _cancelled
from .resources import select_budget
from .storage import ArrayStore
from .spreading import _within_budget, MAX_SPREADING_INTERVALS
from .spreading_cooling import PreparedSpreadingCooling
from .spreading_history_cooling import PreparedHistoryCooling
from .spreading_checkpoint import pack_ocean, restore_ocean
from .margin_cooling import PreparedMarginCooling, MarginThermalResult, MarginSupportResult


@dataclass(frozen=True, slots=True)
class MarginWorkflowPolicy:
    materials: tuple[BoussinesqMaterial, ...]
    support: ThermalSupportParameters
    initial_depth_m: float
    area_m2: float
    water_stock_m3: float
    water_source_id: str
    source_id: str

    def __post_init__(self):
        if (type(self.materials) is not tuple or not self.materials or
                any(type(m) is not BoussinesqMaterial for m in self.materials) or
                len({m.name for m in self.materials}) != len(self.materials) or
                type(self.support) is not ThermalSupportParameters):
            raise TectonicsError('unique typed margin materials and support policy required')
        for key in ('initial_depth_m', 'area_m2'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, positive=True))
        object.__setattr__(self, 'water_stock_m3', scalar(self.water_stock_m3, 'water stock', nonnegative=True))
        _name(self.water_source_id, 'water source'); _name(self.source_id, 'margin workflow source')

    def arguments(self):
        return dict(materials={m.name: m for m in self.materials}, parameters=self.support,
                    initial_depth_m=self.initial_depth_m, area_m2=self.area_m2,
                    water_stock_m3=self.water_stock_m3, water_source_id=self.water_source_id)


@dataclass(frozen=True, slots=True)
class W06WorkflowCheckpoint:
    checkpoint_id: str
    output_index: int
    state: object


def _margin_pack(state):
    thermal = state.thermal
    arrays = dict(mean_temperature_k=thermal.mean_temperature_k,
                  temperature_change_k=thermal.temperature_change_k,
                  outward_heat_j_m2=thermal.outward_heat_j_m2)
    meta = dict(thermal_state_id=thermal.state_id, support_id=state.support_id,
                temperature_truncation_bound_k=thermal.temperature_truncation_bound_k,
                heat_truncation_bound_j_m2=thermal.heat_truncation_bound_j_m2)
    return arrays, meta


def _margin_restore(plan, policy, reference, time_s, arrays, meta):
    """Rebuild cheap support/accounts from authenticated thermal fields, no PDE."""
    if (type(meta) is not dict or set(meta) != {'thermal_state_id', 'support_id',
            'temperature_truncation_bound_k', 'heat_truncation_bound_j_m2'} or
            set(arrays) != {'mean_temperature_k', 'temperature_change_k', 'outward_heat_j_m2'}):
        raise TectonicsError('invalid inherited-margin checkpoint fields')
    initial = reference.thermal
    shapes = {'mean_temperature_k': initial.mean_temperature_k.shape,
              'temperature_change_k': initial.mean_temperature_k.shape, 'outward_heat_j_m2': (2,)}
    for key, shape in shapes.items():
        a = arrays[key]
        if a.dtype != np.dtype('float64') or a.shape != shape or not np.isfinite(a).all():
            raise TectonicsError('invalid inherited-margin checkpoint arrays')
    means, change, heat = (frozen(arrays[k]) for k in
                          ('mean_temperature_k', 'temperature_change_k', 'outward_heat_j_m2'))
    t_error = scalar(meta['temperature_truncation_bound_k'], 'temperature bound', nonnegative=True)
    h_error = scalar(meta['heat_truncation_bound_j_m2'], 'heat bound', nonnegative=True)
    # The full-profile maximum-principle and trajectory bounds were checked by
    # the original support producer at preparation, with this exact policy.
    tol = 64*np.finfo(float).eps*max(1., float(np.max(np.abs(plan._temperatures))))
    if (np.any(means < min(plan._temperatures)-tol-t_error) or
            np.any(means > max(plan._temperatures)+tol+t_error) or
            not np.allclose(means, initial.initial_reference_temperature_k+change, rtol=0., atol=tol)):
        raise TectonicsError('restored margin temperature/reference mismatch')
    depth = initial.depth_edges_m
    state_id = hashlib.sha256(_json(dict(plan=plan.plan_id, time_s=time_s, epoch=initial.epoch_id))+
        b''.join(a.tobytes() for a in (depth, means, initial.initial_reference_temperature_k, change, heat))).hexdigest()
    if state_id != meta['thermal_state_id']:
        raise TectonicsError('restored margin thermal identity mismatch')
    elapsed = time_s-initial.source_time_s
    if elapsed == 0. and (state_id != initial.state_id or t_error != 0. or h_error != 0.):
        raise TectonicsError('initial margin checkpoint differs from declared source')
    energy = plan.plate.volumetric_heat_capacity_j_m3_k*math.fsum(change*np.diff(depth))
    residual = math.fsum((energy, *heat))
    scale = max(abs(energy), math.fsum(abs(v) for v in heat))
    if abs(residual) > 1e-8*scale:
        raise TectonicsError('restored margin heat account does not close')
    thermal = MarginThermalResult(plan.initial_state.state_id, plan.plan_id, state_id,
        plan.execution_id, initial.epoch_id, initial.source_time_s, time_s, elapsed,
        depth, means, initial.initial_reference_temperature_k, change, heat, t_error, h_error,
        plan.source_column, plan.source_profile, plan.material_definitions, plan.cooling_history,
        plan.thinning_source_id, plan.geometry_reference_id, plan.initial_state)
    sheet = math.fsum(-float(delta)*layer.bulk_thickness_m*m.density_kg_m3*m.thermal_expansion_per_k
        for delta, layer, m in zip(change, plan.source_column.layers, plan.material_definitions))
    displacement = scalar(sheet/policy.support.restoring_density_contrast_kg_m3, 'margin displacement')
    current_depth = scalar(policy.initial_depth_m+displacement, 'margin water depth', positive=True)
    water = scalar(current_depth*policy.area_m2, 'margin water', nonnegative=True)
    if (water > policy.water_stock_m3 or
            abs(displacement)/plan.plate.thickness_m > policy.support.max_relative_deflection or
            not reference.trajectory_depth_bounds_m[0]-tol <= current_depth <= reference.trajectory_depth_bounds_m[1]+tol):
        raise TectonicsError('restored margin exceeds water/support envelope')
    support_id = hashlib.sha256(_json(dict(thermal=state_id, parameters=asdict(policy.support),
        materials={m.name: asdict(m) for m in policy.materials}, depth=policy.initial_depth_m,
        area=policy.area_m2, water_stock=policy.water_stock_m3, water_source=policy.water_source_id))).hexdigest()
    if support_id != meta['support_id']:
        raise TectonicsError('restored margin support identity mismatch')
    return MarginSupportResult(thermal, support_id, 'column-isostasy', scalar(sheet, 'thermal sheet'),
        scalar(sheet*policy.support.gravity_m_s2, 'thermal pressure'), displacement, policy.initial_depth_m,
        current_depth, policy.area_m2, reference.reference_water_m3,
        scalar(displacement*policy.area_m2, 'margin water change'), water, policy.water_stock_m3-water,
        policy.water_source_id, reference.reference_material_mass_kg, reference.trajectory_depth_bounds_m)


class PreparedW06Workflow:
    """Borrow one prepared physical route and store; retain only the latest output.

    Changing schedule, source, policy or runtime creates a different run identity.
    Independent runs are alternative scenarios, not permission to debit a shared
    real-world reservoir twice. Caller-retained outputs need their own allowance.
    """
    def __setattr__(self, name, value):
        if getattr(self, '_sealed', False):
            raise AttributeError('prepared W06 workflow is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, prepared, output_times_s, *, margin_policy=None, store=None, budget=None, cancel=None):
        _cancelled(cancel)
        if type(prepared) not in (PreparedSpreadingCooling, PreparedHistoryCooling, PreparedMarginCooling):
            raise TectonicsError('supported prepared W06 physical route required')
        self.is_margin = type(prepared) is PreparedMarginCooling
        if (self.is_margin and type(margin_policy) is not MarginWorkflowPolicy) or (
                not self.is_margin and margin_policy is not None):
            raise TectonicsError('margin policy must match the selected physical route')
        if type(output_times_s) not in (tuple, list) or not 1 <= len(output_times_s) <= MAX_SPREADING_INTERVALS:
            raise TectonicsError('one to 256 explicit requested W06 outputs required')
        times = tuple(scalar(t, 'output time') for t in output_times_s)
        origin = prepared.initial_state.case.time_s if self.is_margin else prepared.initial.time_s
        if times[0] < origin or any(b <= a for a, b in zip(times, times[1:])):
            raise TectonicsError('output times must increase strictly from the source time')
        previous = origin
        for end in times:
            if origin+(end-origin) != end or previous+(end-previous) != end:
                raise TectonicsError('output clock is not representable')
            previous = end
        if store is not None and not isinstance(store, ArrayStore):
            raise TectonicsError('ArrayStore required for W06 recovery')
        resource = prepared._budget if budget is None else select_budget(budget)
        _within_budget(resource, prepared._budget)
        if store is not None:
            _within_budget(resource, store._budget)
        self.prepared, self.margin_policy, self.store = prepared, margin_policy, store
        self.output_times_s, self._origin, self._budget = times, origin, resource
        self._closed, self._current, self._current_lease, self._reference = False, None, None, None
        reference_bytes = (512*len(prepared.source_column.layers)+8192*len(margin_policy.materials)
                           if self.is_margin else 0)
        self._lease = resource.reserve(65536+2048*len(times)+reference_bytes, category='w06-workflow-prepared')
        self._lease.__enter__()
        try:
            self._check(cancel)
            if self.is_margin:
                self._reference = prepared.support(time_s=origin, epoch_id=prepared.initial_state.case.epoch_id,
                    **margin_policy.arguments(), budget=resource, cancel=cancel)
            self.execution_id = prepared.execution_id if self.is_margin else prepared.spreading.execution_id
            descriptor = dict(method='atlas.w06-workflow.v1', route=type(prepared).__name__,
                prepared=prepared.plan_id, times_s=times, execution=self.execution_id,
                margin_policy=None if margin_policy is None else asdict(margin_policy))
            self.plan_id = hashlib.sha256(_json(descriptor)).hexdigest()
            self._sealed = True
        except BaseException:
            self._lease.__exit__(None, None, None)
            raise

    def _check(self, cancel=None):
        if self._closed:
            raise TectonicsError('W06 workflow is closed')
        _cancelled(cancel)
        if self.is_margin:
            self.prepared._check(self._budget, cancel)
        else:
            self.prepared._check(self.prepared.initial)
            self.prepared.spreading._context.verify()

    def _index(self, index):
        if type(index) is not int or not 0 <= index < len(self.output_times_s):
            raise TectonicsError('output index outside the declared W06 schedule')
        return index

    def _invocation(self, index):
        return dict(schema='atlas.w06-output.v1', workflow=self.plan_id,
                    output_index=self._index(index), time_s=self.output_times_s[index])

    def checkpoint_id(self, index):
        return hashlib.sha256(_json(self._invocation(index))).hexdigest()

    def _pack(self, checkpoint, cancel=None):
        arrays, payload = (_margin_pack(checkpoint.state) if self.is_margin else
                           pack_ocean(self.prepared, checkpoint.state, budget=self._budget, cancel=cancel))
        i = checkpoint.output_index
        header = dict(invocation=self._invocation(i), execution=self.execution_id,
                      parent_checkpoint_id=None if i == 0 else self.checkpoint_id(i-1), payload=payload)
        return arrays, dict(header, content_id=hashlib.sha256(_json(header)).hexdigest())

    def _header(self, index, meta):
        if type(meta) is not dict or set(meta) != {'invocation', 'execution', 'parent_checkpoint_id', 'payload', 'content_id'}:
            raise TectonicsError('invalid W06 checkpoint envelope')
        header = {k: v for k, v in meta.items() if k != 'content_id'}
        if (meta['invocation'] != self._invocation(index) or meta['execution'] != self.execution_id or
                meta['parent_checkpoint_id'] != (None if index == 0 else self.checkpoint_id(index-1)) or
                hashlib.sha256(_json(header)).hexdigest() != meta['content_id'] or type(meta['payload']) is not dict):
            raise TectonicsError('W06 checkpoint source/schedule/content mismatch')
        return meta['payload']

    def _scan(self, end, cancel):
        latest, found, parents, latest_parents, gap = -1, None, None, None, False
        if not self.is_margin:
            parents = (self.prepared.initial.motion.state_id, self.prepared.initial.state_id)
        for index in range(end+1):
            _cancelled(cancel)
            meta = self.store.metadata(self.checkpoint_id(index))
            if meta is None:
                gap = True
                continue
            if gap:
                raise TectonicsError('W06 requested-output history has a missing checkpoint')
            payload = self._header(index, meta)
            expected = (None, None) if self.output_times_s[index] == self._origin else parents
            if not self.is_margin:
                count = index+1-int(self.output_times_s[0] == self._origin)
                if (payload.get('intervals') != count or payload.get('time_s') != self.output_times_s[index] or
                        (payload.get('motion_parent_id'), payload.get('thermal_parent_id')) != expected):
                    raise TectonicsError('W06 checkpoint parent/count mismatch')
                parents = (payload.get('motion_state_id'), payload.get('thermal_state_id'))
                if any(type(x) is not str or len(x) != 64 for x in parents):
                    raise TectonicsError('invalid W06 parent identities')
            latest, found, latest_parents = index, meta, expected
        return latest, found, latest_parents

    def _restore(self, index, meta, parents, cancel):
        payload = self._header(index, meta)
        arrays = self.store.get(self.checkpoint_id(index), budget=self._budget)
        if arrays is None:
            raise TectonicsError('W06 checkpoint disappeared during read')
        time_s = self.output_times_s[index]
        # Store.get accounts its decoding buffers; retain admission for those
        # returned arrays plus immutable reconstruction copies until restored.
        with self._budget.reserve(4*sum(a.nbytes for a in arrays.values())+65536,
                                  category='w06-workflow-restore'):
            if self.is_margin:
                result = _margin_restore(self.prepared, self.margin_policy, self._reference, time_s, arrays, payload)
            else:
                count = index+1-int(self.output_times_s[0] == self._origin)
                result = restore_ocean(self.prepared, arrays, payload, time_s=time_s, intervals=count,
                    motion_parent_id=parents[0], thermal_parent_id=parents[1], budget=self._budget, cancel=cancel)
        self._check(cancel)
        return W06WorkflowCheckpoint(self.checkpoint_id(index), index, result)

    def load(self, index, *, cancel=None):
        """Return a verified output without changing the workflow's current state."""
        self._index(index); self._check(cancel)
        if self.store is None:
            return self._current if self._current is not None and self._current.output_index == index else None
        latest, meta, parents = self._scan(index, cancel)
        return None if latest != index else self._restore(index, meta, parents, cancel)

    @staticmethod
    def _bytes(state):
        if type(state) is MarginSupportResult:
            t = state.thermal
            return 16384+sum(a.nbytes for a in (t.depth_edges_m, t.mean_temperature_k,
                t.initial_reference_temperature_k, t.temperature_change_k, t.outward_heat_j_m2))
        return state.nbytes+16384

    def _adopt(self, candidate, lease):
        old = self._current_lease
        object.__setattr__(self, '_current', candidate)
        object.__setattr__(self, '_current_lease', lease)
        if old is not None:
            old.__exit__(None, None, None)

    def run(self, *, through=None, cancel=None):
        self._check(cancel)
        end = len(self.output_times_s)-1 if through is None else self._index(through)
        current = self._current
        if self.store is not None:
            latest, meta, parents = self._scan(end, cancel)
            current = None if latest < 0 else self._restore(latest, meta, parents, cancel)
            if current is not None:
                lease = self._budget.reserve(self._bytes(current.state), category='w06-workflow-retained')
                lease.__enter__()
                self._adopt(current, lease)
        elif current is not None and current.output_index > end:
            raise TectonicsError('earlier output not retained; use a store to recover it')
        start = 0 if current is None else current.output_index+1
        for index in range(start, end+1):
            self._check(cancel)
            if self.is_margin:
                result = self.prepared.support(time_s=self.output_times_s[index],
                    epoch_id=self.prepared.initial_state.case.epoch_id,
                    **self.margin_policy.arguments(), budget=self._budget, cancel=cancel)
            else:
                previous = self.prepared.initial if current is None else current.state
                result = self.prepared.advance(previous, time_s=self.output_times_s[index],
                                              budget=self._budget, cancel=cancel)
            candidate = W06WorkflowCheckpoint(self.checkpoint_id(index), index, result)
            lease = self._budget.reserve(self._bytes(result), category='w06-workflow-retained')
            lease.__enter__()
            try:
                if self.store is not None:
                    arrays, meta = self._pack(candidate, cancel)
                    self.store.put(candidate.checkpoint_id, arrays, meta, budget=self._budget,
                        cancel=cancel, publication_check=lambda: self._check(cancel))
                self._check(cancel)
            except BaseException:
                lease.__exit__(None, None, None)
                raise
            self._adopt(candidate, lease)
            current = candidate
        self._check(cancel)
        return current

    def close(self):
        if not self._closed:
            object.__setattr__(self, '_closed', True)
            object.__setattr__(self, '_current', None)
            if self._current_lease is not None:
                self._current_lease.__exit__(None, None, None)
                object.__setattr__(self, '_current_lease', None)
            self._lease.__exit__(None, None, None)

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, *args):
        self.close()
