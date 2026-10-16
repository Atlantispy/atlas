"""Same-parent force/physical-interval iteration, before material publication.

Pressure and constitutive inputs are the accepted START state. Only the owned
interface discretisation is iterated. A proposal is not an accepted interval:
the actual final-rate trace and exact finite-inventory GCL must both pass.
The resulting source stage is reusable after failed/cancelled publication;
the workflow's accepted-parent compare-and-swap, not a consumed token, prevents
double advancement. No iteration advects material or books heat into a head.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
from fractions import Fraction as Q
import hashlib
import json
import math
import weakref

import numpy as np

from . import integration_differential_geometry as G
from . import integration_differential_trace as T
from . import integration_regional_driving as D
from . import integration_sphere as S
from . import integration_volume as V
from . import integration_wall_measures as W
from ._validation import TectonicsError, frozen, input_shape
from .integration_collar_geometry import FullCellFunding
from .integration_differential_pressure import DifferentialPressureForcing
from .integration_native_faces import measure_native_faces
from .integration_pressure_coupling import radial_gravity_field
from .integration_radial_pressure import RadialDatum
from .integration_spatial_ale import SpatialALEBounds
from .integration_spatial_owner import PreparedSpatialOwner, SpatialExteriorState
from .integration_transfer import Motion
from .kinematics import Rotation
from .regional_collar3d import PreparedRegionalCollar3D, RegionalCollarState
from .regional_execution3d import SIDES, _digest_array, _cancel
from .resources import WorkBudget, MemoryLimitError


def _json(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _issue(cls, record, resource, **objects):
    encoded = _json(record)
    guard = resource.reserve(8192+4*len(encoded), category='differential-coupling-receipt')
    guard.__enter__()
    try:
        result = object.__new__(cls)
        for key, value in dict(_json=encoded, _resource=resource, **objects).items():
            object.__setattr__(result, key, value)
        weakref.finalize(result, guard.__exit__, None, None, None)
        return result
    except BaseException:
        guard.__exit__(None, None, None)
        raise


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class _ForceFailure:
    """Bounded diagnostic only: not a proposal, solution or published state."""
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)

    def record(self):
        return json.loads(self._json)


def _force_failure_diagnostic(metadata, arrays, budget):
    # Failed topology must not discard a costly solve's small force operands.
    # Never retain the full 3-D solution here. Oversized diagnostics are omitted,
    # not allowed to raise the physical workload's resource limit.
    count = sum(a.size for a in arrays.values())
    if count > 8192:
        return None
    with budget.reserve(65536+128*count, category='differential-force-diagnostic-scratch'):
        record = dict(schema='atlas.differential-force-failure.v1', **metadata,
            arrays={key: value.tolist() for key, value in arrays.items()},
            scope='failed geometry admission after an actual force solve; no material or heat publication')
        if len(_json(record)) > 262144:
            return None
        return _issue(_ForceFailure, record, budget)


def _force_diagnostic_preflight(driver, plate_count, boundary_count):
    """Inspect existing shapes only, before snapshot copies or metadata lists."""
    count = (driver._matrix.size+driver._lift._basis.size+driver._resistance.size+
             driver._drive.size+33*plate_count+2*driver._lift._basis.shape[1])
    if driver._global_basis is not None:
        count += driver._global_basis.size
    if count > 8192 or plate_count > 256 or boundary_count > 256:
        return None
    # Raw float copies, bounded names/error text and per-boundary dictionaries.
    # The inner packer separately charges its list/JSON scratch and retention.
    return 65536+32*count+2048*(plate_count+boundary_count)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class DifferentialForceProposal:
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)
    _owner: object = field(repr=False, compare=False)
    source_flow_stage: object
    native_faces: object
    force_exchange: object
    interval: object
    partition: object

    def __init__(self, *args, **kwargs):
        raise TypeError('force proposals are issued by PreparedDifferentialIteration.propose')

    @property
    def proposal_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return dict(proposal_id=self.proposal_id, **json.loads(self._json))


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class DifferentialIntervalSolution:
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)
    proposal: DifferentialForceProposal
    trace_audit: T.IntervalTraceAudit
    bounds: object
    graph: object

    def __init__(self, *args, **kwargs):
        raise TypeError('interval solutions require final trace and exact carried-stock closure')

    @property
    def solution_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return dict(solution_id=self.solution_id, **json.loads(self._json))

    def validate_source(self, source, interval, partition, bounds, *, spatial_state_id):
        p = self.proposal
        if (source is not p.source_flow_stage or interval is not p.interval or partition is not p.partition or
                bounds is not self.bounds or spatial_state_id != self.record()['spatial_state_id']):
            raise TectonicsError('certified interval is not this actual same-parent source, support and material')
        p.native_faces.validate_source(p.native_faces._collar, source)


def _driver_family(driver):
    """Fixed physical data; trace-dependent operators are intentionally absent."""
    d = driver.descriptor(); lift = d['lift']
    return {key: d[key] for key in ('network_id', 'parent_state_id', 'interval', 'forcing_id',
        'exterior_balance_id', 'exterior_prepared_id', 'material_source')} | dict(
        pressure_forcing_id=d.get('differential_pressure_partition', {}).get('forcing', {}).get('forcing_id'),
        boundary_id=lift['boundary_id'], angular_rate_basis=lift['angular_rate_basis'],
        constraint_source=lift['constraint_source'], exterior_subspace=d.get('exterior_angular_subspace'),
        native_geometry=lift['geometry'], physical_volume_binding=lift['physical_volume_binding']) | (
        {} if 'global_angular_subspace' not in d else dict(global_subspace=d['global_angular_subspace']))


def _motion_from_rates(network, end_step, duration, rates, supplies, sinks):
    """Finite rotations of the actual rates; never project onto a coaxial axis."""
    values = D._array(rates, (len(network.plate_ids), 3), 'actual solved angular rates')
    rotations = {}
    for plate, row in zip(network.plate_ids, values):
        speed = math.hypot(*map(float, row))
        angle = speed*float(duration)
        if not math.isfinite(angle):
            raise TectonicsError('actual finite angular displacement is not representable')
        rotations[plate] = (Rotation((1., 0., 0., 0.)) if speed == 0 else
                            Rotation.from_axis_angle(row, angle))
    return Motion(network.step, end_step, rotations, supplies=supplies, sinks=sinks)


class PreparedDifferentialIteration:
    """Bounded same-parent attempts using an actual typed plate driver each time.

    Start with the supplied current-geometry driver. A later driver must use
    the preceding proposal's time-integrated component trace, with the SAME
    accepted-start pressure/force/subspace. Geometry and material producers
    remain typed external stages, not callbacks. ``certify`` does not publish.
    """
    def __setattr__(self, key, value):
        if not key.startswith('_') and hasattr(self, key):
            raise TectonicsError('differential iteration definitions are immutable')
        object.__setattr__(self, key, value)

    def __init__(self, sphere, network, current_geometry, parent_partition, funding,
                 collar, state, spatial_owner, spatial_state, initial_driver, pressure, datum, *,
                 supplies, sinks, prior_interval=None, max_attempts, max_orientation_leaves,
                 max_partition_components, additional_body_force_n_m3=0., heat_source_w_m3=0.,
                 heat_source, budget):
        self._guard = None
        if (type(sphere) is not S.SphereState or type(network) is not S.SphereNetwork or
                type(current_geometry) is not G.CurrentGeometry or type(parent_partition) is not G.DifferentialPartition or
                type(funding) is not FullCellFunding or type(collar) is not PreparedRegionalCollar3D or
                type(state) is not RegionalCollarState or type(spatial_owner) is not PreparedSpatialOwner or
                type(spatial_state) is not SpatialExteriorState or type(initial_driver) is not D.PreparedRegionalDriving or
                type(pressure) is not DifferentialPressureForcing or type(datum) is not RadialDatum or
                type(budget) is not WorkBudget):
            raise TectonicsError('actual source, accepted material/geometry and typed physical driver required')
        if type(initial_driver._lift) is not T.DifferentialPlateBoundaryLift:
            raise TectonicsError('differential iteration requires the issued component trace, not a nodal-owner lift')
        if (any(value is not budget for value in (current_geometry._resource, parent_partition._resource,
                funding._resource, collar._budget, spatial_owner._budget, spatial_state._budget,
                initial_driver._budget, pressure._resource)) or spatial_owner._collar is not collar or
                spatial_owner._funding is not funding or collar.mechanics_scope != 'complete-grid'):
            raise TectonicsError('one actual complete-grid spatial owner and shared resource budget required')
        if any(type(v) is not int or v < 1 for v in (max_attempts, max_orientation_leaves, max_partition_components)):
            raise TectonicsError('explicit positive finite attempt and geometry work limits required')
        D._name(heat_source)
        spatial_owner.validate_parent(spatial_state, state)
        if spatial_owner._finite is None:
            raise TectonicsError('physical differential evolution requires its retained finite stocks')
        current, part, force, drive = current_geometry.record(), parent_partition.record(), pressure.descriptor(), initial_driver.descriptor()
        start_step, end_step, start, end = drive['interval']
        duration = Q(end)-Q(start)
        expected_current = (G.prepare_current_geometry(network, budget=budget) if prior_interval is None else
                            G.current_geometry_from_interval(prior_interval, budget=budget))
        trace = initial_driver._lift._trace if type(initial_driver._lift) is T.DifferentialPlateBoundaryLift else None
        if (current_geometry.geometry_id != expected_current.geometry_id or current['network_id'] != network.network_id or
                start_step != network.step or start != network.time_s or start != spatial_state.time_s or
                end <= start or Q(float(duration)) != duration or Q(float(start)+float(duration)) != Q(end) or
                part['end_time_s'] != current['time_s'] or part['funding_id'] != funding.funding_id or
                funding.descriptor()['source']['sphere_state_id'] != sphere.state_id or
                force['geometry_id'] != current_geometry.geometry_id or force['native_state_id'] != state.native_state.result_id or
                force['spatial_state_id'] != spatial_state.state_id or force['radial_datum'] != datum.record() or
                _driver_family(initial_driver)['pressure_forcing_id'] != pressure.forcing_id or trace is None or
                trace._endpoint != 'current' or trace.descriptor().get('component_partition', {}).get('partition_id') != parent_partition.partition_id):
            raise TectonicsError('initial driver does not bind this accepted clock, complete material and current pressure')
        sizes = (math.prod(collar._native.cells)*27*3, math.prod(collar._native.cells))
        self._guard = budget.reserve(131072+24*sum(sizes)+2048*max_attempts, category='differential-iteration-inputs')
        self._guard.__enter__()
        try:
            def fixed(value, shape, label):
                shape_in = input_shape(value, label)
                if shape_in not in ((), shape):
                    raise TectonicsError(label+' must be a scalar or the actual native field shape')
                a = np.asarray(value, dtype=float)
                if not np.isfinite(a).all():
                    raise TectonicsError(label+' must be finite')
                return frozen(np.full(shape, float(a)) if shape_in == () else a)
            self._body = fixed(additional_body_force_n_m3, (math.prod(collar._native.cells), 27, 3), 'fixed body force')
            self._heat = fixed(heat_source_w_m3, collar._native.cells, 'fixed extra heat source')
            # Validate finite declarations before the first mechanical solve.
            _motion_from_rates(network, end_step, duration, np.zeros((len(network.plate_ids), 3)), supplies, sinks)
            self._sphere, self._network, self._current, self._parent_partition = sphere, network, current_geometry, parent_partition
            self._funding, self._collar, self._state = funding, collar, state
            self._spatial_owner, self._spatial_state = spatial_owner, spatial_state
            self._initial_driver, self._pressure = initial_driver, pressure
            self._finite = spatial_owner._finite.restore(spatial_state.record()['finite_stock_state'])
            self._supplies, self._sinks = tuple(supplies), tuple(sinks)
            self._prior, self._duration, self._end_step = prior_interval, float(duration), end_step
            self._budget, self._attempts, self._last_interval_id, self._last_partition_id = budget, 0, None, None
            self._max_attempts, self._orientation_leaves = max_attempts, max_orientation_leaves
            self._max_components, self._heat_source = max_partition_components, heat_source
            self._gravity = radial_gravity_field(collar, datum, budget=budget)
            self._family = _driver_family(initial_driver)
            self._definition = dict(schema='atlas.differential-iteration.v1', family=self._family,
                collar_plan_id=collar.plan_id, parent_state_id=state.result_id, native_state_id=state.native_state.result_id,
                spatial_state_id=spatial_state.state_id, finite_state_id=self._finite.state_id,
                current_geometry_id=current_geometry.geometry_id, parent_partition_id=parent_partition.partition_id,
                pressure_forcing_id=pressure.forcing_id, gravity_field_id=self._gravity.field_id,
                body_sha256=_digest_array(self._body), heat_sha256=_digest_array(self._heat), heat_source=heat_source,
                duration_s=self._duration, max_attempts=max_attempts, max_orientation_leaves=max_orientation_leaves,
                max_partition_components=max_partition_components,
                supplies=[s.record() for s in self._supplies], sinks=[s.record() for s in self._sinks],
                time_rule='accepted-start physical pressure and constitutive state; frozen interval-mask fixed-point proposals',
                publication='none; only actual final trace plus exact carried-stock GCL may enter one workflow CAS')
            self.iteration_id = hashlib.sha256(_json(self._definition)).hexdigest()
        except BaseException:
            self.close()
            raise

    def descriptor(self):
        if self._guard is None:
            raise TectonicsError('differential iteration is closed')
        self._spatial_owner.validate_parent(self._spatial_state, self._state)
        return dict(iteration_id=self.iteration_id, **json.loads(_json(self._definition)))

    def propose(self, driver=None, *, cancel=None):
        self.descriptor(); _cancel(cancel)
        driver = self._initial_driver if driver is None else driver
        if type(driver) is not D.PreparedRegionalDriving or driver._budget is not self._budget or _driver_family(driver) != self._family:
            raise TectonicsError('each attempt must retain the exact accepted-start physical force and subspace')
        if self._attempts >= self._max_attempts:
            raise TectonicsError('declared same-parent differential iteration attempt limit reached')
        trace = driver._lift._trace
        if self._last_interval_id is not None:
            if (not trace._interval_predictor or trace._interval.interval_id != self._last_interval_id or
                    trace.descriptor().get('component_partition', {}).get('partition_id') != self._last_partition_id or
                    trace.descriptor()['interval_predictor']['force_geometry_id'] != self._current.geometry_id):
                raise TectonicsError('next attempt requires the preceding actual-rate interval predictor')
        elif (trace._endpoint != 'current' or trace._interval.geometry_id != self._current.geometry_id or
                trace.descriptor().get('component_partition', {}).get('partition_id') != self._parent_partition.partition_id):
            raise TectonicsError('first attempt requires the actual accepted current geometry')
        self._attempts += 1
        prototype = trace._native
        tractions = {side: np.zeros_like(prototype.coordinates(side)) for side in SIDES}
        side = self._pressure.descriptor()['reservoir_native_side']
        tractions[side] = self._pressure.array('reservoir_native_traction_pa')
        stage = self._collar.source_flow_stage(self._state, self._duration, velocity_m_s=0.,
            dynamic_traction_pa=tractions, gravity_m_s2=self._gravity,
            additional_body_force_n_m3=self._body, driving_source=driver.driving_id,
            heat_source_w_m3=self._heat, heat_source=self._heat_source, coupling=driver.coupling(), cancel=cancel)
        force = driver.reconstruct(stage.source_stage.initial_mechanics,
            parent_state_id=self._state.native_state.result_id, time_s=self._network.time_s).exchange
        faces = measure_native_faces(self._collar, stage, budget=self._budget)
        rates = force.array('omega_rad_s')
        motion = _motion_from_rates(self._network, self._end_step, self._duration, rates, self._supplies, self._sinks)
        try:
            interval = G.prepare_differential_interval(self._network, motion, end_time_s=self._network.time_s+self._duration,
                angular_velocity_by_plate_rad_s={p: tuple(map(float, row)) for p, row in zip(self._network.plate_ids, rates)},
                max_leaves=self._orientation_leaves, budget=self._budget, prior_interval=self._prior)
            partition = G.prepare_interval_partition(self._parent_partition, interval, self._funding, self._sphere,
                self._collar, finite_stock_state=self._finite, max_components=self._max_components, budget=self._budget)
        except TectonicsError as error:
            scratch = _force_diagnostic_preflight(driver, len(self._network.plate_ids), len(self._network.boundaries))
            try:
                diagnostic = None
                if scratch is not None:
                    with self._budget.reserve(scratch, category='differential-force-diagnostic-inputs'):
                        mechanical = stage.source_stage.initial_mechanics
                        arrays = dict(omega_rad_s=rates, exterior_resistance_j_s=driver._matrix,
                            full_driving_torque_n_m=driver._b, reduced_external_force_j=driver._drive,
                            reduced_external_resistance_j_s=driver._resistance,
                            pair_angular_basis=driver._lift._basis,
                            regional_resisting_torque_n_m=force.array('regional_resisting_torque_n_m'),
                            torque_equation_residual_n_m=force.array('torque_equation_residual_n_m'),
                            constraint_torque_n_m=force.array('constraint_torque_n_m'),
                            native_generalized_force_j=mechanical.array('generalized_regional_force_j'),
                            native_generalized_rates_s_inv=mechanical.array('generalized_rates_s_inv'))
                        if driver._global_basis is not None:
                            arrays['global_angular_rate_basis'] = driver._global_basis
                        for key in ('hydrostatic_wall_torque_n_m', 'native_owned_wall_torque_n_m',
                                    'reservoir_cut_torque_n_m', 'reservoir_imposed_cut_torque_n_m',
                                    'reservoir_removed_wall_torque_n_m', 'torque_error_bound_n_m'):
                            arrays[key] = self._pressure.array(key)
                        metadata = dict(iteration_id=self.iteration_id, attempt=self._attempts,
                            parent_state_id=self._state.result_id, spatial_state_id=self._spatial_state.state_id,
                            source_flow_stage_id=stage.result_id, source_audit_id=stage.source_stage.source_audit.result_id,
                            force_exchange_id=force.result_id, mechanical_result_id=mechanical.result_id,
                            driving_id=driver.driving_id, pressure_forcing_id=self._pressure.forcing_id,
                            native_measure_id=faces.measure_id, motion_id=motion.motion_id,
                            plate_ids=list(self._network.plate_ids), time_s=self._network.time_s, duration_s=self._duration,
                            boundaries=[dict(boundary_id=b.boundary_id, kind=b.kind, left=b.left_plate_id,
                                right=b.right_plate_id, subducting_side=b.subducting_side, carrier_side=b.carrier_side)
                                for b in self._network.boundaries], error_type=type(error).__name__, error=str(error)[:4096])
                        diagnostic = _force_failure_diagnostic(metadata, arrays, self._budget)
                        del arrays, metadata, mechanical
                if diagnostic is not None:
                    error.differential_force_failure = diagnostic
                else:
                    error.add_note('force diagnostic omitted: bounded diagnostic size exceeded')
            except MemoryLimitError:
                arrays = metadata = mechanical = None
                error.add_note('force diagnostic omitted: shared memory budget exhausted')
            raise
        self._last_interval_id = interval.interval_id
        self._last_partition_id = partition.partition_id
        record = dict(schema='atlas.differential-force-proposal.v1', iteration_id=self.iteration_id,
            attempt=self._attempts, parent_state_id=self._state.result_id, spatial_state_id=self._spatial_state.state_id,
            source_flow_stage_id=stage.result_id, source_audit_id=stage.source_stage.source_audit.result_id,
            force_exchange_id=force.result_id, native_measure_id=faces.measure_id,
            interval_id=interval.interval_id, partition_id=partition.partition_id, motion_id=motion.motion_id,
            interval_predictor_id=trace.descriptor().get('interval_id'),
            published=False, accepted_heat_state_advanced=False, donor_source_computed=True)
        return _issue(DifferentialForceProposal, record, self._budget, _owner=self,
            source_flow_stage=stage, native_faces=faces, force_exchange=force, interval=interval, partition=partition)

    def certify(self, proposal, final_trace, bounds, *, max_l2_error_squared, max_work_error, cancel=None):
        """Actual-rate field/error audit and one exact carried-volume closure.

        Failure leaves the parent and proposal unchanged. The caller may build
        a next interval predictor, or retry unchanged publication after success.
        There is no angular-rate convergence tolerance or automatic bound change.
        """
        self.descriptor(); _cancel(cancel)
        if (type(proposal) is not DifferentialForceProposal or proposal._owner is not self or
                type(final_trace) is not T.PreparedDifferentialTrace or final_trace._interval is not proposal.interval or
                type(bounds) is not SpatialALEBounds or bounds._resource is not self._budget):
            raise TectonicsError('actual proposal, final-rate physical trace and issued ALE bounds required')
        if final_trace.descriptor().get('component_partition', {}).get('partition_id') != proposal.partition.partition_id:
            raise TectonicsError('final trace must use the proposal\'s complete actual component partition')
        b, p = bounds.record(), proposal.record()
        expected = dict(physical_geometry_family='differential-plate-component-partition-v1',
            interval_id=proposal.interval.interval_id, partition_id=proposal.partition.partition_id,
            parent_partition_id=self._parent_partition.partition_id, funding_id=self._funding.funding_id,
            native_measure_id=proposal.native_faces.measure_id, source_flow_stage_id=proposal.source_flow_stage.result_id,
            flow_id=proposal.source_flow_stage.flow.flow_id)
        if any(b.get(k) != v for k, v in expected.items()):
            raise TectonicsError('physical material closure is not from this actual solved Q2 field and final interval')
        audit = T.audit_interval_solution(final_trace, proposal.native_faces, proposal.force_exchange,
            max_l2_error_squared=max_l2_error_squared, max_work_error=max_work_error, budget=self._budget)
        graph = self._spatial_owner.close_graph(self._spatial_state, proposal.source_flow_stage, bounds)
        _cancel(cancel)
        if graph.record().get('finite_state_id') != self._finite.state_id:
            raise TectonicsError('exact material closure used another finite inventory parent')
        record = dict(schema='atlas.differential-interval-solution.v1', iteration_id=self.iteration_id,
            proposal_id=proposal.proposal_id, parent_state_id=self._state.result_id,
            spatial_state_id=self._spatial_state.state_id, finite_state_id=self._finite.state_id,
            source_flow_stage_id=p['source_flow_stage_id'], source_audit_id=p['source_audit_id'],
            force_exchange_id=p['force_exchange_id'], native_measure_id=p['native_measure_id'],
            interval_id=p['interval_id'], partition_id=p['partition_id'],
            trace_audit_id=audit.audit_id, trace_audit=audit.record(), bounds_id=bounds.bounds_id,
            graph_id=graph.geometry_id, published=False,
            retry='same immutable source/audit and accepted parent; workflow CAS only, never a consumed heat token')
        return _issue(DifferentialIntervalSolution, record, self._budget, proposal=proposal,
                      trace_audit=audit, bounds=bounds, graph=graph)

    def close(self):
        if self._guard is not None:
            self._guard.__exit__(None, None, None)
            self._guard = None

    def __enter__(self):
        self.descriptor()
        return self

    def __exit__(self, *_):
        self.close()
