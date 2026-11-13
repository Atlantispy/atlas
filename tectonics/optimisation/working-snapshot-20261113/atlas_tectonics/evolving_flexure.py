"""Prescribed evolving elastic support on W04's stationary 1D source support.

The caller supplies the absolute reference pressure and each state's elastic
properties. W04 still owns physical inventory/thermal/external load changes.
For changed rigidity the response is A(D_current)^-1 q_current minus
A(D_reference)^-1 q_reference, never A(D_current)^-1 delta_q. There is no
inferred stress-free datum, material law, feedback or viscoelastic evolution.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict, dataclass
import json
import threading

import numpy as np

from ._validation import TectonicsError, input_shape, snapshot, text
from .compaction_columns import _cancel, _divide
from .execution import _acquire_native_limit, _release_native_limit
from .resources import WorkBudget, select_budget
from .reuse import cached_variable_flexure
from .stokes_execution import _factored_scale
from .variable_flexure import RigidityProfile1D, VariableFlexureAccuracy, VariableRigidityFlexure
from .w03_workflow import W03ColumnState
from .w04_workflow import (PreparedW04Support, W04SupportPolicy, W04SupportResult,
                           _id, _json)


CAP = 128 << 20


@dataclass(frozen=True, slots=True, init=False)
class W04RigidityState:
    """An explicitly supplied elastic profile bound to one actual W03 instant."""
    state_id: str
    source_id: str
    input_id: str
    profile: RigidityProfile1D
    time_s: float

    def __init__(self, state, profile, *, source_id):
        if type(state) is not W03ColumnState or type(profile) is not RigidityProfile1D:
            raise TectonicsError('typed W03 state and supplied rigidity profile required')
        text(source_id, 'evolving rigidity source')
        if (profile.frame_id != state.source_workflow.initial_samples.descriptor()['frame_id'] or
                profile.datum_id != state.binding.depth_reference_id or
                profile.epoch_id != state.binding.epoch_id):
            raise TectonicsError('rigidity frame/datum/epoch must match the actual W03 state')
        record = dict(schema='atlas.w04-rigidity-state.v1', state=state.state_id,
            time_s=state.time_s, source=source_id, profile=profile.profile_id)
        for key, value in dict(state_id=state.state_id, time_s=state.time_s,
                profile=profile, source_id=source_id, input_id=_id(record)).items():
            object.__setattr__(self, key, value)


@dataclass(frozen=True, slots=True, init=False)
class W04AbsoluteReferenceLoad:
    """Total imposed reference pressure on W04 cells, positive downward.

    This supplied datum already includes ALL reference material, replacement,
    thermal and additional external contributions. It is not an extra pressure
    to add to W04's reference inventory. The supplying model owns its absolute
    load convention; W04 cannot deduce that convention from anomaly-only inputs.
    Exterior totals use the existing W04ExteriorLoads and are bound here too.
    """
    state_id: str
    surface_id: str
    exterior_id: str | None
    policy_id: str
    source_id: str
    input_id: str
    _payload: bytes
    _metadata: bytes

    def __init__(self, state, surface, policy, downward_pressure_pa, *, source_id,
                 exterior=None, budget=None, cancel=None):
        _cancel(cancel)
        if type(state) is not W03ColumnState or type(policy) is not W04SupportPolicy:
            raise TectonicsError('typed reference W03 state and W04 policy required')
        text(source_id, 'absolute reference load source')
        PreparedW04Support._check_surface(state, surface)
        if policy.boundary == 'continuous-plate':
            PreparedW04Support._check_exterior(state, exterior)
        elif exterior is not None:
            raise TectonicsError('absolute exterior loads require a continuous plate')
        n = state.material.grid.cells
        if input_shape(downward_pressure_pa) != (n,):
            raise TectonicsError('one supplied absolute pressure per actual W04 cell required')
        with select_budget(budget).reserve(32*n+8192, category='w04-absolute-datum'):
            pressure = snapshot(downward_pressure_pa, 'absolute reference pressure')
            if pressure.shape != (n,):
                raise TectonicsError('absolute pressure shape changed during capture')
            raw = pressure.tobytes()
            exterior_id = None if exterior is None else exterior.input_id
            policy_id = _id(asdict(policy))
            record = dict(schema='atlas.w04-absolute-reference.v1', state=state.state_id,
                surface=surface.input_id, exterior=exterior_id, policy=policy_id,
                source=source_id, grid=asdict(state.material.grid), cells=surface.cell_ids,
                frame=state.source_workflow.initial_samples.descriptor()['frame_id'],
                datum=state.binding.depth_reference_id, epoch=state.binding.epoch_id,
                time_s=state.time_s, pressure='total-imposed-positive-downward-Pa')
            for key, value in dict(state_id=state.state_id, surface_id=surface.input_id,
                    exterior_id=exterior_id, policy_id=policy_id, source_id=source_id,
                    _payload=raw, _metadata=_json(record), input_id=_id(record,raw)).items():
                object.__setattr__(self,key,value)
        _cancel(cancel)

    @property
    def downward_pressure_pa(self):
        return np.frombuffer(self._payload,dtype=np.float64)

    def descriptor(self):
        return json.loads(self._metadata)


@dataclass(frozen=True, slots=True, init=False)
class EvolvingW04SupportResult(W04SupportResult):
    """W04 change accounts plus the two absolute pressures and displacements."""
    _absolute: bytes

    @property
    def absolute_values(self):
        """Columns: reference/current pressure Pa, reference/current downward m."""
        return np.frombuffer(self._absolute,dtype=np.float64).reshape(-1,4)


class PreparedEvolvingW04Support:
    """Fixed reference plus at most one replaceable current elastic preparation.

    Geometry, foundation K, boundary and numerical policy stay fixed. Current
    profiles are supplied with exact state/time binding. Retained factors do not
    accumulate across property history. All work shares a 128 MiB child budget
    and the existing one-native-thread lease; accounted bytes are not an RSS cap.
    """
    def __setattr__(self, name, value):
        if getattr(self,'_sealed',False):
            raise AttributeError('evolving W04 definition is immutable')
        object.__setattr__(self,name,value)

    def __init__(self,reference,reference_surface,policy,*,reference_rigidity,
                 reference_absolute_load,accuracy,reference_exterior=None,
                 budget=None,cancel=None):
        self._stack = ExitStack()
        self._closed = False
        self._current_operator = None
        self._lock = threading.RLock()
        self._budget = WorkBudget(CAP, parent=select_budget(budget))
        try:
            if type(reference) is not W03ColumnState or type(policy) is not W04SupportPolicy:
                raise TectonicsError('typed reference W03 state and W04 policy required')
            PreparedW04Support._check_surface(reference,reference_surface)
            if policy.boundary == 'continuous-plate':
                PreparedW04Support._check_exterior(reference,reference_exterior)
            elif reference_exterior is not None:
                raise TectonicsError('absolute exterior loads require a continuous plate')
            self._check_rigidity(reference,reference_rigidity)
            datum = reference_absolute_load
            exterior_id = None if reference_exterior is None else reference_exterior.input_id
            if (type(datum) is not W04AbsoluteReferenceLoad or
                    datum.state_id != reference.state_id or datum.surface_id != reference_surface.input_id or
                    datum.exterior_id != exterior_id or datum.policy_id != _id(asdict(policy))):
                raise TectonicsError('absolute reference datum must match state, surface, exterior and policy')
            if type(accuracy) is not VariableFlexureAccuracy:
                raise TectonicsError('explicit variable-flexure accuracy required')
            _acquire_native_limit(1)
            self._stack.callback(_release_native_limit)
            base = self._stack.enter_context(PreparedW04Support(reference,reference_surface,policy,
                exterior=reference_exterior,rigidity=reference_rigidity.profile,
                accuracy=accuracy,budget=self._budget,cancel=cancel))
            self._base = base
            self.reference_rigidity = reference_rigidity
            self.reference_absolute_load = datum
            self._stack.enter_context(self._budget.reserve(
                256*base.operator.grid.cells+32768,category='evolving-flexure-retained'))
            packed = self._pack(datum.downward_pressure_pa,reference_exterior)
            response = self._response(base.operator,packed,None,None,cancel)
            self._check_validity(response,base.rigidity,'absolute reference')
            self._reference_response = response
            self._reference_packed = packed.tobytes()
            self.plan_id = _id(dict(schema='atlas.evolving-w04-plan.v1',w04=base.plan_id,
                absolute_reference=datum.input_id,reference_rigidity=reference_rigidity.input_id,
                limits=dict(work_bytes=CAP,native_threads=1,retained_operators=2)))
            self._base._live(cancel)
            self._sealed = True
        except BaseException:
            self._stack.close()
            raise

    @staticmethod
    def _check_rigidity(state,rigidity):
        if (type(rigidity) is not W04RigidityState or rigidity.state_id != state.state_id or
                rigidity.time_s != state.time_s):
            raise TectonicsError('supplied rigidity must belong to this exact W03 state/time')

    def _pack(self,interior,exterior):
        if exterior is None:
            return np.concatenate((interior,[0.,0.]))
        if exterior.omitted_left_bound_pa != 0 or exterior.omitted_right_bound_pa != 0:
            raise TectonicsError('evolving variable rigidity requires exact exterior loads; exterior uncertainty unsupported')
        return np.concatenate((exterior.left_pressure_pa,interior,exterior.right_pressure_pa,
                               [exterior.far_left_pa,exterior.far_right_pa]))

    def _response(self,operator,packed,store,cache_policy,cancel):
        return cached_variable_flexure(operator,packed,context=self._base._context.scipy,
            budget=self._budget,controller=self._base._controller,store=store,
            cache_policy=cache_policy,cancel=cancel)

    def _maxima(self,response,profile):
        # Include the complete represented support, including explicit halos.
        error = response[:,4,:3]
        return (float(np.max(response[:,3,0]+error[:,0])),
                float(np.max(response[:,3,1]+error[:,1])),
                float(np.max(response[:,3,3]+error[:,2]*profile.elastic_thickness_m/2)))

    def _valid(self,maxima):
        base = self._base
        return (maxima[0] <= base.reference.binding.cooling_model.thickness_m*
                    base.reference.binding.support_parameters.max_relative_deflection and
                maxima[1] <= base.policy.max_abs_slope and maxima[2] <= base.policy.max_bending_strain)

    def _check_validity(self,response,profile,label):
        maxima = self._maxima(response,profile)
        if not self._valid(maxima):
            raise TectonicsError(label+' exceeds W04 linear/fixed-plate validity envelope')
        return maxima

    def _operator(self,profile):
        base = self._base
        if profile.grid != base.operator.grid:
            raise TectonicsError('changed source/halo geometry requires a new evolving W04 plan')
        if profile.profile_id == base.rigidity.profile_id:
            # Drop a previously changing state when returning to the reference.
            if self._current_operator is not None:
                self._current_operator.close()
                object.__setattr__(self,'_current_operator',None)
            return base.operator
        old = self._current_operator
        if old is not None and old.profile.profile_id == profile.profile_id:
            return old
        # Release old factors BEFORE preparing their replacement: at most two
        # live operators even during replacement or a failed new preparation.
        if old is not None:
            old.close()
            object.__setattr__(self,'_current_operator',None)
        operator = VariableRigidityFlexure(profile,base.policy.elastic,
            base.operator.boundary,base.operator.accuracy,budget=self._budget)
        object.__setattr__(self,'_current_operator',operator)
        return operator

    def solve(self,current,surface,*,rigidity,exterior=None,store=None,cache_policy=None,cancel=None):
        with self._lock:
            if self._closed:
                raise TectonicsError('prepared evolving W04 support is closed')
            base = self._base
            base._check_current(current,surface,exterior,store,cancel)
            self._check_rigidity(current,rigidity)
            n = current.material.grid.cells
            count = base.operator.grid.cells
            with self._budget.reserve(1536*count+32*n*(len(base.phases)+1)+32768,
                                      category='evolving-flexure-projection'):
                loads,thermal,external,total = base._load_change(current,surface,store,cache_policy,cancel)
                with np.errstate(over='ignore',invalid='ignore'):
                    absolute = self.reference_absolute_load.downward_pressure_pa+total
                if not np.isfinite(absolute).all():
                    raise TectonicsError('nonfinite absolute current load')
                packed = self._pack(absolute,exterior)
                operator = self._operator(rigidity.profile)
                reference = self._reference_response
                same = operator is base.operator
                unchanged = same and packed.tobytes() == self._reference_packed
                now = reference if unchanged else self._response(operator,packed,store,cache_policy,cancel)
                now_max = self._check_validity(now,rigidity.profile,'absolute current')
                left = 0 if exterior is None else exterior.left_cells
                crop = slice(left,left+n)
                if same:
                    # Linearity is valid ONLY for the unchanged operator. Use
                    # the original compensated load delta, avoiding subtraction
                    # of two large, nearly identical absolute solutions.
                    if exterior is None:
                        delta = self._pack(total,None)
                    else:
                        old = base.reference_exterior
                        delta = np.concatenate((exterior.left_pressure_pa-old.left_pressure_pa,total,
                            exterior.right_pressure_pa-old.right_pressure_pa,
                            [exterior.far_left_pa-old.far_left_pa,exterior.far_right_pa-old.far_right_pa]))
                    if np.any(delta):
                        changed = self._response(operator,delta,store,cache_policy,cancel)
                        self._check_validity(changed,rigidity.profile,'reference change')
                        w = changed[crop,1,0]
                        error = changed[:,4,:3]
                    else:
                        w = np.zeros(n)
                        error = np.zeros((count,3))
                else:
                    w = now[crop,1,0]-reference[crop,1,0]
                    error = now[:,4,:3]+reference[:,4,:3]
                    # Distinct meshes have no shared subcell polynomial. The
                    # triangle bound preserves the existing change validity gate.
                    change_max = (float(np.max(now[:,3,0]+reference[:,3,0]+error[:,0])),
                        float(np.max(now[:,3,1]+reference[:,3,1]+error[:,1])),
                        float(np.max((now[:,3,2]+reference[:,3,2]+error[:,2])*
                                     rigidity.profile.elastic_thickness_m/2)))
                    if not self._valid(change_max):
                        raise TectonicsError('reference change bound exceeds W04 linear/fixed-plate validity envelope')
                bulk = np.sum(current.material.thickness_m,axis=0)-np.frombuffer(base._reference_bulk,dtype=np.float64)
                sediment = bulk-w
                water = sediment+_divide(surface.reservoir_volume_m3-base.reference_surface.reservoir_volume_m3,
                                         base.support.area_m2,'W04 water-level change')
                wet = (surface.reservoir_volume_m3>0)&(base.reference_surface.reservoir_volume_m3>0)
                values = np.column_stack((_factored_scale(loads[:,:2],(base.policy.elastic.gravity_m_s2,),(),
                    'W04 inventory pressures'),np.full(n,thermal),external,total,w,sediment,np.where(wet,water,0.)))
                absolute_values = np.column_stack((self.reference_absolute_load.downward_pressure_pa,
                    absolute,reference[crop,1,0],now[crop,1,0]))
                if not np.isfinite(values).all() or not np.isfinite(absolute_values).all():
                    raise TectonicsError('nonfinite evolving W04 projection')
                metadata = dict(schema='atlas.evolving-w04-result.v1',plan_id=self.plan_id,
                    reference_state=base.reference.state_id,current_state=current.state_id,
                    reference_surface=base.reference_surface.input_id,current_surface=surface.input_id,
                    reference_time_s=base.reference.time_s,time_s=current.time_s,
                    reference_rigidity=self.reference_rigidity.input_id,current_rigidity=rigidity.input_id,
                    reference_profile=base.rigidity.profile_id,current_profile=rigidity.profile.profile_id,
                    reference_operator=base.operator.operator_id,current_operator=operator.operator_id,
                    absolute_reference_load=self.reference_absolute_load.input_id,
                    reference_exterior=None if base.reference_exterior is None else base.reference_exterior.input_id,
                    current_exterior=None if exterior is None else exterior.input_id,
                    source_workflow=base.reference.source_workflow.workflow_id,
                    epoch_id=base.reference.binding.epoch_id,depth_reference_id=base.reference.binding.depth_reference_id,
                    execution_id=base._context.identity,thermal_owner='flexure',vertical_response_owner='W04',
                    w03_local_displacement='diagnostic-only-excluded',total_reference_result=True,
                    surface_change_semantics='total from fixed reference; apply once, never accumulate totals',
                    feedback_applied=False,policy=asdict(base.policy),
                    response='fixed-operator-load-delta' if same else 'current-absolute-minus-reference-absolute',
                    accuracy=asdict(operator.accuracy),absolute_current_maxima=list(now_max),
                    mesh_change_estimate=np.max(error,axis=0).tolist(),
                    reference_subdivisions=int(reference[0,4,3]),current_subdivisions=int(now[0,4,3]),
                    exterior_uncertainty='exact declared loads required',
                    validity='polynomial maxima plus mesh-change estimates; not a rigorous continuum error bound')
                base._live(cancel)
                payload,mask,absolute_raw = values.tobytes(),wet.tobytes(),absolute_values.tobytes()
                result = object.__new__(EvolvingW04SupportResult)
                for key,value in dict(_metadata=_json(metadata),_payload=payload,_wet=mask,
                        _absolute=absolute_raw,result_id=_id(metadata,payload+mask+absolute_raw)).items():
                    object.__setattr__(result,key,value)
                return result

    def close(self):
        with self._lock:
            if not self._closed:
                object.__setattr__(self,'_closed',True)
                try:
                    if self._current_operator is not None:
                        self._current_operator.close()
                        object.__setattr__(self,'_current_operator',None)
                finally:
                    try:
                        self._stack.close()
                    finally:
                        object.__setattr__(self,'_reference_response',None)
                        object.__setattr__(self,'_reference_packed',b'')

    def __enter__(self):
        try:
            if self._closed:
                raise TectonicsError('prepared evolving W04 support is closed')
            self._base._live(None)
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self,*args):
        self.close()


def project_evolving_w04_support(reference,current,reference_surface,current_surface,policy,*,
        reference_rigidity,current_rigidity,reference_absolute_load,accuracy,
        reference_exterior=None,current_exterior=None,budget=None,store=None,
        cache_policy=None,cancel=None):
    """One-shot equivalent; retain preparation for successive supplied states."""
    with PreparedEvolvingW04Support(reference,reference_surface,policy,
            reference_rigidity=reference_rigidity,reference_absolute_load=reference_absolute_load,
            accuracy=accuracy,reference_exterior=reference_exterior,budget=budget,cancel=cancel) as plan:
        return plan.solve(current,current_surface,rigidity=current_rigidity,
            exterior=current_exterior,store=store,cache_policy=cache_policy,cancel=cancel)
