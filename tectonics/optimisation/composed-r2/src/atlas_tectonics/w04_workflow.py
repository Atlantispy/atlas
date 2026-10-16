"""W04.2/3/4: source-bound W03 loads -> prescribed linear support.

Closed pore/reservoir water has explicit spatial placement. Thermal buoyancy is
an effective fixed-plate diagnostic, not an extra rock inventory. W03's local
isostatic diagnostic is NOT applied. Outputs are totals from one reference,
never accumulated displacements or a feedback update to W03 material/heat.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict, dataclass
import hashlib
import json
import math

import numpy as np

from ._validation import TectonicsError, input_shape, snapshot, scalar, text
from .column_loads import LoadSupport, LoadPhase, ColumnLoadState, _add
from .compaction_columns import _cancel, _multiply, _divide
from .flexure import PeriodicFlexure
from .finite_flexure import FiniteRegionFlexure, FlexureBoundary1D
from .variable_flexure import RigidityProfile1D, VariableFlexureAccuracy, VariableRigidityFlexure
from .regional import RegionalGrid1D
from .parameters import FlexureParameters, PeriodicGrid1D
from .plate_integrals import plate_cooling_deficit_change
from .resources import select_budget
from .reuse import (ReuseController, cached_column_load_change, cached_flexure,
                    cached_finite_flexure, cached_variable_flexure)
from .storage import ArrayStore
from .stokes_execution import _factored_scale
from .w03_workflow import W03ColumnState, W03ExecutionContext


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _id(value, payload=b''):
    return hashlib.sha256(_json(value)+payload).hexdigest()


def _cell_ids(state):
    return tuple(c['cell_id'] for c in state.source_workflow.initial_samples.descriptor()['cells'])


@dataclass(frozen=True, slots=True, init=False)
class W04SurfaceInputs:
    """Prescribed reservoir location and ADDITIONAL total external pressure.

    Cell IDs must be the actual W01 sampled cells in order. No reservoir location
    is inferred from net pore outflow. External pressure is not inferred from W03
    effective stress and must exclude overburden already represented as material.
    Supply explicit zeros when there is no additional present external load.
    """
    source_id: str
    state_id: str
    reservoir_id: str
    cell_ids: tuple[str, ...]
    input_id: str
    _payload: bytes

    def __init__(self, state, cell_ids, reservoir_volume_m3, external_downward_pressure_pa,
                 *, source_id, budget=None, cancel=None):
        _cancel(cancel)
        if type(state) is not W03ColumnState:
            raise TectonicsError('source-bound W03ColumnState required')
        text(source_id, 'surface input source')
        if type(cell_ids) is not tuple or cell_ids != _cell_ids(state):
            raise TectonicsError('surface cell IDs/order must match actual W01 supports')
        n = len(cell_ids)
        if input_shape(reservoir_volume_m3) != (n,) or input_shape(external_downward_pressure_pa) != (n,):
            raise TectonicsError('one explicit reservoir volume and external pressure per cell required')
        with select_budget(budget).reserve(96*n+8192, category='w04-surface-inputs'):
            volume = snapshot(reservoir_volume_m3, 'reservoir allocation', nonnegative=True)
            pressure = snapshot(external_downward_pressure_pa, 'additional external pressure')
            if volume.shape != (n,) or pressure.shape != (n,):
                raise TectonicsError('surface input shape changed during capture')
            try:
                total = math.fsum(map(float,volume))
            except OverflowError as exc:
                raise TectonicsError('reservoir allocation exceeds finite range') from exc
            if not math.isclose(total,state.reservoir_fluid_m3,rel_tol=128*np.finfo(float).eps,abs_tol=0.):
                raise TectonicsError('spatial allocation must account for the complete finite W03 reservoir')
            raw = np.column_stack((volume,pressure)).tobytes()
            reservoir_id = state.compaction.conditions.reservoir_id
            record = dict(schema='atlas.w04-surface-inputs.v1', source=source_id,
                state=state.state_id, cells=cell_ids, reservoir=reservoir_id)
            for key,value in dict(source_id=source_id,state_id=state.state_id,
                    reservoir_id=reservoir_id,cell_ids=cell_ids,_payload=raw,input_id=_id(record,raw)).items():
                object.__setattr__(self,key,value)
            _cancel(cancel)

    @property
    def reservoir_volume_m3(self):
        return np.frombuffer(self._payload,dtype=np.float64).reshape(-1,2)[:,0]

    @property
    def external_downward_pressure_pa(self):
        return np.frombuffer(self._payload,dtype=np.float64).reshape(-1,2)[:,1]


@dataclass(frozen=True, slots=True, init=False)
class W04ExteriorLoads:
    """Total exterior pressure at one W03 time on adjacent equal-width cells.

Left halo runs far-to-near; right runs near-to-far. Beyond the halo, each
infinite half-line has an explicit constant pressure and a declared bound on
unknown departures. Includes any outside thermal/water/material load: no
automatic continuation or off-domain allocation of the closed W03 reservoir.
"""
    state_id: str
    input_id: str
    left_cells: int
    right_cells: int
    far_left_pa: float
    far_right_pa: float
    omitted_left_bound_pa: float
    omitted_right_bound_pa: float
    _left: bytes
    _right: bytes
    _metadata: bytes

    def __init__(self, state, left_pressure_pa, right_pressure_pa, *, far_left_pa,
                 far_right_pa, omitted_left_bound_pa, omitted_right_bound_pa,
                 source_id, budget=None, cancel=None):
        _cancel(cancel)
        if type(state) is not W03ColumnState:
            raise TectonicsError('source-bound W03 state required for exterior loads')
        text(source_id, 'exterior source')
        values = dict(far_left_pa=scalar(far_left_pa, 'left far pressure'),
            far_right_pa=scalar(far_right_pa, 'right far pressure'),
            omitted_left_bound_pa=scalar(omitted_left_bound_pa, 'left omitted bound', nonnegative=True),
            omitted_right_bound_pa=scalar(omitted_right_bound_pa, 'right omitted bound', nonnegative=True))
        shapes = []
        for value in (left_pressure_pa, right_pressure_pa):
            empty = type(value) in (tuple, list) and len(value) == 0
            shape = (0,) if empty else input_shape(value, 'exterior halo')
            if len(shape) != 1:
                raise TectonicsError('one-dimensional ordered exterior halo required')
            shapes.append(shape)
        with select_budget(budget).reserve(32*sum(s[0] for s in shapes)+8192):
            arrays = []
            for value,shape in zip((left_pressure_pa,right_pressure_pa),shapes):
                arr = b'' if shape[0] == 0 else snapshot(value, 'exterior pressure').tobytes()
                if len(arr) != 8*shape[0]:
                    raise TectonicsError('exterior halo changed shape during capture')
                arrays.append(arr)
            grid = state.material.grid
            record = dict(schema='atlas.w04-exterior.v1', source=source_id, state=state.state_id,
                grid=asdict(grid), frame=state.source_workflow.initial_samples.descriptor()['frame_id'],
                epoch=state.binding.epoch_id, datum=state.binding.depth_reference_id, time_s=state.time_s,
                left_cells=len(arrays[0])//8, right_cells=len(arrays[1])//8, **values)
            metadata = _json(record)
            digest = hashlib.sha256(metadata)
            for payload in arrays: digest.update(payload)
            for key, value in dict(state_id=state.state_id, input_id=digest.hexdigest(),
                    left_cells=record['left_cells'], right_cells=record['right_cells'],
                    _left=arrays[0], _right=arrays[1], _metadata=metadata, **values).items():
                object.__setattr__(self, key, value)
        _cancel(cancel)

    @property
    def left_pressure_pa(self):
        return np.frombuffer(self._left, dtype=np.float64)

    @property
    def right_pressure_pa(self):
        return np.frombuffer(self._right, dtype=np.float64)

    def descriptor(self):
        return json.loads(self._metadata)


@dataclass(frozen=True, slots=True)
class W04SupportPolicy:
    """Explicit bounded support assumptions; no guessed Earth material/limits."""
    source_id: str
    boundary: str
    thermal_owner: str
    void_density_kg_m3: float
    headroom_m: float
    max_abs_slope: float
    max_bending_strain: float
    elastic: FlexureParameters
    region_boundary: FlexureBoundary1D | None = None
    max_omitted_deflection_m: float = 0.

    def __post_init__(self):
        text(self.source_id,'support policy source')
        if self.boundary not in ('periodic-repetition', 'continuous-plate', 'physical-edges'):
            raise TectonicsError('explicit supported boundary assumption required')
        if self.boundary == 'periodic-repetition':
            if self.region_boundary is not None or self.max_omitted_deflection_m != 0:
                raise TectonicsError('periodic support cannot carry finite-region assumptions')
        elif (type(self.region_boundary) is not FlexureBoundary1D or
              self.region_boundary.continuous != (self.boundary == 'continuous-plate')):
            raise TectonicsError('region boundary must explicitly match continuous plate or physical ends')
        object.__setattr__(self, 'max_omitted_deflection_m', scalar(
            self.max_omitted_deflection_m, 'omitted displacement tolerance', nonnegative=True))
        if self.thermal_owner != 'flexure':
            raise TectonicsError('W04 needs exclusive flexure ownership of thermal support')
        if type(self.elastic) is not FlexureParameters:
            raise TectonicsError('explicit elastic parameters required')
        object.__setattr__(self,'void_density_kg_m3',scalar(self.void_density_kg_m3,'void density',nonnegative=True))
        for name in ('headroom_m','max_abs_slope','max_bending_strain'):
            value = scalar(getattr(self,name),name,positive=True)
            if name != 'headroom_m' and value >= 1:
                raise TectonicsError('small-slope/strain validity limits must be below one')
            object.__setattr__(self,name,value)


@dataclass(frozen=True, slots=True, init=False)
class W04SupportResult:
    """Immutable derived projection, not a displaced/reinvented material state.

    Packed columns: inventory Pa, void/replacement Pa, thermal Pa, external Pa,
    total Pa, downward deflection m, sediment-top change m, water-top change m.
    Positive surface changes are upward. Both surfaces share the source datum.
    Water-top is only defined where reservoir water exists at both instants.
    """
    result_id: str
    _metadata: bytes
    _payload: bytes
    _wet: bytes

    def descriptor(self):
        return json.loads(self._metadata)

    @property
    def values(self):
        return np.frombuffer(self._payload,dtype=np.float64).reshape(-1,8)

    @property
    def downward_load_pa(self):
        return self.values[:,4]

    @property
    def downward_displacement_from_reference_m(self):
        return self.values[:,5]

    @property
    def sediment_surface_change_m(self):
        return self.values[:,6]

    @property
    def reservoir_surface_known(self):
        return np.frombuffer(self._wet,dtype=np.bool_)

    @property
    def reservoir_surface_change_m(self):
        if not self.reservoir_surface_known.all():
            raise TectonicsError('water surface undefined for dry reference/current cells; inspect the known mask')
        return self.values[:,7]


class PreparedW04Support:
    """One immutable reference/operator and shared source-checked backends.

    Closing releases prepared-budget reservations, not caller-owned source states.
    A solve spans the complete support/load domain; no independent spatial tiles.
    """
    def __setattr__(self,name,value):
        if getattr(self,'_sealed',False):
            raise AttributeError('prepared W04 definition is immutable')
        object.__setattr__(self,name,value)

    def __init__(self,reference,reference_surface,policy,*,exterior=None,rigidity=None,accuracy=None,budget=None,cancel=None):
        _cancel(cancel)
        if type(reference) is not W03ColumnState or type(policy) is not W04SupportPolicy:
            raise TectonicsError('typed W03 reference and W04 policy required')
        self._check_surface(reference,reference_surface)
        workflow = reference.source_workflow
        if workflow.support.kind != 'planar-strip' or np.any(workflow.forcing.face_velocity_m_s != 0):
            raise TectonicsError('W04 bridge supports stationary planar W03 columns only')
        grid = reference.material.grid
        if policy.boundary == 'continuous-plate':
            self._check_exterior(reference, exterior)
            left, right = exterior.left_cells, exterior.right_cells
        else:
            if exterior is not None:
                raise TectonicsError('exterior loads require a continuous plate')
            left = right = 0
        model_grid = RegionalGrid1D(grid.cells+left+right,
            (grid.cells+left+right)*grid.spacing_m, grid.origin_m-left*grid.spacing_m)
        b = reference.binding
        if rigidity is None:
            if accuracy is not None:
                raise TectonicsError('variable accuracy requires a variable rigidity profile')
        elif (type(rigidity) is not RigidityProfile1D or type(accuracy) is not VariableFlexureAccuracy or
              rigidity.grid != model_grid or rigidity.frame_id != workflow.initial_samples.descriptor()['frame_id'] or
              rigidity.datum_id != b.depth_reference_id or rigidity.epoch_id != b.epoch_id):
            raise TectonicsError('variable rigidity must match actual source/halo grid, frame, datum and epoch with explicit accuracy')
        if (policy.elastic.gravity_m_s2 != b.support_parameters.gravity_m_s2 or
                policy.elastic.density_contrast_kg_m3 != b.support_parameters.compensation_density_kg_m3-policy.void_density_kg_m3):
            raise TectonicsError('gravity/restoring contrast must match source mantle minus explicit void, not implicit water infill')
        if policy.void_density_kg_m3 >= reference.compaction.conditions.pore_fluid_density_kg_m3:
            raise TectonicsError('closed finite-water bridge requires explicit lighter air/vacuum background')
        self._budget = select_budget(budget)
        self._stack = ExitStack(); self._closed = False
        try:
            self._stack.enter_context(self._budget.reserve(128*grid.cells*(len(reference.material.cohorts)+3)+32768,
                                                           category='w04-prepared-retained'))
            self._context = self._stack.enter_context(W03ExecutionContext())
            if self._context.identity != reference.execution_id:
                raise TectonicsError('W03 source/runtime changed; no automatic rebind')
            self.reference = reference; self.reference_surface = reference_surface; self.policy = policy
            self.reference_exterior = exterior
            self.rigidity=rigidity
            if rigidity is not None:
                boundary='periodic' if policy.boundary=='periodic-repetition' else policy.region_boundary
                self.operator=self._stack.enter_context(VariableRigidityFlexure(
                    rigidity,policy.elastic,boundary,accuracy,budget=self._budget))
            elif policy.boundary == 'periodic-repetition':
                self.operator = PeriodicFlexure(PeriodicGrid1D(grid.cells,grid.length_m),policy.elastic)
            else:
                self.operator = FiniteRegionFlexure(model_grid,policy.elastic,policy.region_boundary,budget=self._budget)
                self._stack.enter_context(self._budget.reserve(self.operator.setup_bytes,category='w04-finite-retained'))
            self._controller = ReuseController()
            initial = workflow.initial_samples.state
            metadata = workflow.initial_samples.descriptor()
            if (metadata['frame_id'] != initial.sampling_domain.frame_id or
                    metadata['depth_reference_id'] != b.depth_reference_id or
                    len(metadata['cells']) != grid.cells):
                raise TectonicsError('W01 sample geometry/frame/datum does not match W03 source')
            area = grid.spacing_m*reference.reference_width_m
            if np.any(reference.compaction.area_m2 != area):
                raise TectonicsError('W03 column areas differ from the support grid')
            geometry = dict(samples=workflow.initial_samples.sample_id,cells=metadata['cells'],
                frame=metadata['frame_id'],section=workflow.forcing.section.descriptor(),
                grid=asdict(grid),width_m=reference.reference_width_m,
                bottom_depth_m=workflow.support.bottom_depth_m,
                top_depth_m=workflow.support.top_depth_m-policy.headroom_m)
            self.support = LoadSupport(reference_surface.cell_ids,np.full(grid.cells,area),
                np.full(grid.cells,workflow.support.bottom_depth_m-workflow.support.top_depth_m+policy.headroom_m),
                geometry_source=_id(geometry),frame_id=metadata['frame_id'],datum_id=b.depth_reference_id,budget=self._budget)
            materials = {m.material_id:m for m in initial.case.materials}
            phases = []
            for cohort in reference.material.cohorts:
                m = materials[cohort.material_id]
                if m.density_kg_m3 is None:
                    raise TectonicsError('source material density is unknown')
                pore = cohort == reference.pore_fluid_cohort
                if pore and m.density_kg_m3 != reference.compaction.conditions.pore_fluid_density_kg_m3:
                    raise TectonicsError('source reservoir/pore density differs from W03')
                phases.append(LoadPhase('cohort:'+cohort.cohort_id,'pore-water' if pore else 'sediment-grain',
                    m.density_kg_m3,_id(dict(material=asdict(m),cohort=asdict(cohort)))))
            phases.append(LoadPhase('reservoir:'+reference_surface.reservoir_id,'water',
                reference.compaction.conditions.pore_fluid_density_kg_m3,_id(asdict(reference.compaction.conditions))))
            self.phases = tuple(phases)
            self._reference_load = self._load_snapshot(reference,reference_surface,cancel)
            self._reference_bulk = np.sum(reference.material.thickness_m,axis=0).tobytes()
            self.plan_id = _id(dict(schema='atlas.w04-projection.v1',reference=reference.state_id,
                surface=reference_surface.input_id,policy=asdict(policy),geometry=geometry,
                exterior=None if exterior is None else exterior.input_id,
                operator=self.operator.operator_id,execution=self._context.identity))
            self._context.verify(); _cancel(cancel)
            self._sealed = True
        except BaseException:
            self._stack.close()
            raise

    @staticmethod
    def _check_surface(state,surface):
        if (type(surface) is not W04SurfaceInputs or surface.state_id != state.state_id or
                surface.reservoir_id != state.compaction.conditions.reservoir_id):
            raise TectonicsError('surface inputs belong to another W03 state/reservoir')

    @staticmethod
    def _check_exterior(state, exterior):
        if type(exterior) is not W04ExteriorLoads or exterior.state_id != state.state_id:
            raise TectonicsError('explicit exterior loads must belong to this W03 state/time/frame')

    def _live(self,cancel):
        if self._closed:
            raise TectonicsError('prepared W04 support is closed')
        _cancel(cancel); self._context.verify()

    def _load_snapshot(self,state,surface,cancel):
        area = self.support.area_m2
        volumes = _multiply(state.material.thickness_m.T,area[:,None],'W04 source phase volumes')
        volumes = np.column_stack((volumes,surface.reservoir_volume_m3))
        return ColumnLoadState(self.support,self.phases,volumes,
            np.full(len(area),self.policy.void_density_kg_m3),
            source_id=_id(dict(w03=state.state_id,surface=surface.input_id)),
            epoch_id=_id(dict(epoch=state.material.epoch_id,time_s=state.time_s)),budget=self._budget,cancel=cancel)

    def _check_current(self,current,surface,exterior,store,cancel):
        """Shared fixed-support source validation for W04 response adapters."""
        self._live(cancel)
        if type(current) is not W03ColumnState:
            raise TectonicsError('typed current W03 state required')
        self._check_surface(current,surface)
        old_exterior = self.reference_exterior
        if self.policy.boundary == 'continuous-plate':
            self._check_exterior(current, exterior)
            if (exterior.left_cells, exterior.right_cells) != (old_exterior.left_cells, old_exterior.right_cells):
                raise TectonicsError('changed halo geometry needs new reference preparation')
        elif exterior is not None:
            raise TectonicsError('exterior loads require a continuous plate')
        ref = self.reference
        if (current.execution_id != ref.execution_id or current.binding != ref.binding or
                current.source_workflow.workflow_id != ref.source_workflow.workflow_id or
                current.material.grid != ref.material.grid or current.material.cohorts != ref.material.cohorts or
                current.compaction.conditions != ref.compaction.conditions or
                current.compaction.parcels != ref.compaction.parcels or
                current.pore_fluid_cohort != ref.pore_fluid_cohort or current.reference_width_m != ref.reference_width_m or
                current.total_fluid_m3 != ref.total_fluid_m3 or current.time_s < ref.time_s or
                surface.cell_ids != self.reference_surface.cell_ids):
            raise TectonicsError('current W03 source/history/geometry is incompatible with fixed reference')
        if store is not None and not isinstance(store,ArrayStore):
            raise TectonicsError('ArrayStore required')

    def _load_change(self,current,surface,store,cache_policy,cancel):
        """The existing physical accounts, after _check_current and admission."""
        n = current.material.grid.cells
        now = self._load_snapshot(current,surface,cancel)
        g = self.policy.elastic.gravity_m_s2
        kwargs = dict(store=store,budget=self._budget,controller=self._controller,cache_policy=cache_policy,cancel=cancel)
        loads = cached_column_load_change(self._reference_load,now,g,context=self._context.reference,**kwargs)
        b = current.binding
        ref = self.reference
        ages = [scalar(b.reference_age_s+(s.time_s-b.reference_time_s),'cooling age',nonnegative=True) for s in (ref,current)]
        if current.time_s != ref.time_s and ages[0] == ages[1]:
            raise TectonicsError('distinct W03 times collapse to one cooling age')
        mean = plate_cooling_deficit_change(ages[1],ages[0],b.cooling_model,budget=self._budget,cancel=cancel)
        m = b.buoyancy_material
        thermal = (0. if m.expansion_per_k == 0 else float(_factored_scale(mean,
            (m.density_kg_m3,m.expansion_per_k,b.cooling_model.thickness_m,g),(),'W04 thermal pressure')))
        external = surface.external_downward_pressure_pa-self.reference_surface.external_downward_pressure_pa
        total = loads[:,3].copy(); correction = np.zeros(n)
        _add(total,correction,np.full(n,thermal)); _add(total,correction,external)
        total += correction
        return loads,thermal,external,total

    def solve(self,current,surface,*,exterior=None,store=None,cache_policy=None,cancel=None):
        self._check_current(current,surface,exterior,store,cancel)
        ref = self.reference
        old_exterior = self.reference_exterior
        n = current.material.grid.cells
        with self._budget.reserve(256*n+32*n*(len(self.phases)+1)+32768,category='w04-projection'):
            loads,thermal,external,total = self._load_change(current,surface,store,cache_policy,cancel)
            g = self.policy.elastic.gravity_m_s2
            kwargs = dict(store=store,budget=self._budget,controller=self._controller,cache_policy=cache_policy,cancel=cancel)
            b = current.binding
            region = None
            if self.rigidity is not None:
                w,maxima,region=self._variable_response(total,exterior,kwargs)
            elif self.policy.boundary == 'periodic-repetition':
                w = cached_flexure(self.operator,total,context=self._context.reference,**kwargs)
                dx = self.operator.grid.spacing_m
                slope = _divide(np.roll(w,-1)-w,dx,'W04 periodic slope')
                curvature = _divide(np.roll(w,-1)-2*w+np.roll(w,1),dx,'W04 curvature numerator')
                strain = _multiply(_divide(curvature,dx,'W04 curvature'),self.policy.elastic.elastic_thickness_m/2,'W04 bending strain')
                maxima = (np.max(np.abs(w)), np.max(np.abs(slope)), np.max(np.abs(strain)))
            else:
                w, maxima, region = self._regional_response(total, exterior, kwargs)
            if (maxima[1] > self.policy.max_abs_slope or maxima[2] > self.policy.max_bending_strain or
                    maxima[0] > b.cooling_model.thickness_m*b.support_parameters.max_relative_deflection):
                raise TectonicsError('W04 displacement exceeds selected linear/fixed-plate validity envelope')
            bulk_delta = np.sum(current.material.thickness_m,axis=0)-np.frombuffer(self._reference_bulk,dtype=np.float64)
            sediment = bulk_delta-w
            water = sediment+_divide(surface.reservoir_volume_m3-self.reference_surface.reservoir_volume_m3,
                                     self.support.area_m2,'W04 water-level change')
            wet = (surface.reservoir_volume_m3 > 0) & (self.reference_surface.reservoir_volume_m3 > 0)
            values = np.column_stack((_factored_scale(loads[:,:2],(g,),(),'W04 inventory pressures'),
                np.full(n,thermal),external,total,w,sediment,np.where(wet,water,0.)))
            if not np.isfinite(values).all():
                raise TectonicsError('nonfinite W04 projection')
            metadata = dict(schema='atlas.w04-support-result.v1',plan_id=self.plan_id,
                reference_state=ref.state_id,current_state=current.state_id,
                reference_surface=self.reference_surface.input_id,current_surface=surface.input_id,
                source_workflow=ref.source_workflow.workflow_id,source_sample=ref.binding.sample_id,
                epoch_id=ref.binding.epoch_id,depth_reference_id=ref.binding.depth_reference_id,
                reference_time_s=ref.time_s,time_s=current.time_s,operator_id=self.operator.operator_id,
                execution_id=self._context.identity,thermal_owner='flexure',w03_local_displacement='diagnostic-only-excluded',
                total_reference_result=True,feedback_applied=False,policy=asdict(self.policy),
                region=region,reference_exterior=None if old_exterior is None else old_exterior.input_id,
                current_exterior=None if exterior is None else exterior.input_id)
            self._context.verify(); _cancel(cancel)
            payload,mask = values.tobytes(),wet.tobytes()
            result = object.__new__(W04SupportResult)
            for key,value in dict(_metadata=_json(metadata),_payload=payload,_wet=mask,
                                  result_id=_id(metadata,payload+mask)).items():
                object.__setattr__(result,key,value)
            return result

    def _regional_response(self, total, exterior, kwargs):
        old = self.reference_exterior
        left = 0 if old is None else old.left_cells
        bounds = (0., 0., 0.)
        with self._budget.reserve(128*self.operator.grid.cells+8192,category='w04-exterior-load'):
            if old is None:
                packed = np.concatenate((total,[0.,0.]))
            else:
                bounds = self.operator.omitted_response_bounds(
                    scalar(old.omitted_left_bound_pa+exterior.omitted_left_bound_pa,'left combined uncertainty',nonnegative=True),
                    scalar(old.omitted_right_bound_pa+exterior.omitted_right_bound_pa,'right combined uncertainty',nonnegative=True),
                    left*self.operator.grid.spacing_m,old.right_cells*self.operator.grid.spacing_m)
                if bounds[0] > self.policy.max_omitted_deflection_m:
                    raise TectonicsError('unrepresented exterior load exceeds selected region-error tolerance; supply wider/better inputs')
                packed = np.concatenate((exterior.left_pressure_pa-old.left_pressure_pa,total,
                    exterior.right_pressure_pa-old.right_pressure_pa,
                    [exterior.far_left_pa-old.far_left_pa,exterior.far_right_pa-old.far_right_pa]))
            response = cached_finite_flexure(self.operator,packed,context=self._context.reference,**kwargs)
            crop = response[2*left:2*(left+len(total))+1]
            maxima = [float(np.max(np.abs(crop[:,d])))+bounds[d] for d in range(3)]
            maxima[2] *= self.policy.elastic.elastic_thickness_m/2
            region = dict(boundary=asdict(self.policy.region_boundary),model_grid=asdict(self.operator.grid),
                flexural_length_m=self.operator.alpha_m,output_left_cell=left,output_cells=len(total),
                omitted_response_bounds=list(bounds),max_omitted_deflection_m=self.policy.max_omitted_deflection_m,
                representation='cell-constant pressure; point response at centres and faces',
                validity='sampled centres/faces plus exterior-uncertainty bound; not subcell extrema',
                output_edge_response=crop[[0,-1]].tolist())
            # Detach the requested interior before releasing the halo reservation.
            # A small view must not keep the full surrounding response alive.
            return snapshot(crop[1::2,0],'regional interior displacement'), maxima, region

    def _variable_response(self,total,exterior,kwargs):
        old=self.reference_exterior;left=0 if old is None else old.left_cells
        with self._budget.reserve(384*self.operator.grid.cells+8192,category='w04-variable-projection'):
            if old is None:
                packed=np.concatenate((total,[0.,0.]))
            else:
                # Uniform Green-tail bounds do not apply through variable D.
                # Fail closed, never silently erase source uncertainty or call a
                # discrete sensitivity bound a continuum error certificate.
                if any(x!=0 for x in (old.omitted_left_bound_pa,old.omitted_right_bound_pa,
                                      exterior.omitted_left_bound_pa,exterior.omitted_right_bound_pa)):
                    raise TectonicsError('variable rigidity currently requires exact declared exterior loads; nonzero exterior uncertainty is unsupported')
                packed=np.concatenate((exterior.left_pressure_pa-old.left_pressure_pa,total,
                    exterior.right_pressure_pa-old.right_pressure_pa,
                    [exterior.far_left_pa-old.far_left_pa,exterior.far_right_pa-old.far_right_pa]))
            response=cached_variable_flexure(self.operator,packed,context=self._context.scipy,**kwargs)
            crop=response[left:left+len(total)]
            error=crop[:,4,:3]
            maxima=(float(np.max(crop[:,3,0]+error[:,0])),
                    float(np.max(crop[:,3,1]+error[:,1])),
                    float(np.max(crop[:,3,3]+error[:,2]*self.rigidity.elastic_thickness_m[left:left+len(total)]/2)))
            region=dict(method='C1 Hermite variable-rigidity weak form',profile_id=self.rigidity.profile_id,
                boundary=self.operator.boundary if self.operator.boundary=='periodic' else asdict(self.operator.boundary),
                model_grid=asdict(self.operator.grid),output_left_cell=left,output_cells=len(total),
                subdivisions=int(response[0,4,3]),mesh_change_estimates=np.max(error,axis=0).tolist(),
                accuracy=asdict(self.operator.accuracy),exterior_uncertainty='exact declared loads required',
                validity='one-sided polynomial maxima plus mesh-change estimate; not rigorous continuum-error bound',
                third_derivative='diagnostic FE derivative; not controlled by the displacement/slope/curvature gate',
                output_edge_response=[crop[0,0].tolist(),crop[-1,2].tolist()],
                rigidity_time_dependence='fixed reference profile; time-varying rigidity unsupported')
            return snapshot(crop[:,1,0],'variable interior displacement'),maxima,region

    def close(self):
        if not self._closed:
            object.__setattr__(self,'_closed',True)
            self._stack.close()

    def __enter__(self):
        try:
            self._live(None)
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self,*args):
        self.close()


def project_w04_support(reference,current,reference_surface,current_surface,policy,*,
                        reference_exterior=None,current_exterior=None,rigidity=None,accuracy=None,
                        store=None,budget=None,cache_policy=None,cancel=None):
    """One-shot equivalent of PreparedW04Support; reuse preparation for sequences."""
    with PreparedW04Support(reference,reference_surface,policy,exterior=reference_exterior,
                            rigidity=rigidity,accuracy=accuracy,budget=budget,cancel=cancel) as prepared:
        return prepared.solve(current,current_surface,exterior=current_exterior,store=store,cache_policy=cache_policy,cancel=cancel)
