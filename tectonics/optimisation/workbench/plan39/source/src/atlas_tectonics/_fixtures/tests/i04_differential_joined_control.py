"""Actual force-to-material-to-heat publication seam, never synthetic issuance.

This helper consumes the live initial owner and physical driver from the
pressure control. It avoids reconstructing that expensive geometry merely to
exercise the next seam. Coarse endpoint geometry remains construction evidence;
its allowance never replaces the independently requested stream accuracy.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
from contextlib import ExitStack, contextmanager, nullcontext
from contextvars import ContextVar
from fractions import Fraction as Q
from pathlib import Path
import json
import os
import tempfile

import numpy as np

import i02_workflow_fixtures as F2
from i04_differential_modes import ORIGINAL_CONTROL
from test_i04_spatial_workflow import check_global_accounts, operations
from atlas_tectonics import integration_differential_geometry as G
from atlas_tectonics import integration_differential_mesh as H
from atlas_tectonics import integration_differential_trace as T
from atlas_tectonics import integration_parallel_selection as PS
from atlas_tectonics import integration_volume as V
from atlas_tectonics import integration_wall_measures as W
from atlas_tectonics.integration_differential_coupling import PreparedDifferentialIteration
from atlas_tectonics.integration_mimetic_heat import _q
from atlas_tectonics.integration_native_projection import project_native_faces, choose_native_directed_volumes
from atlas_tectonics.integration_regional_workflow import CollarWorkflow


_ALE_COMPUTE_CONTEXT = ContextVar('joined_ale_compute_context', default=None)


@contextmanager
def ale_compute_context(factory):
    """Explicit diagnostic scope around the original ALE call only.

    A benchmark may temporarily release its own observation tools while the
    ordinary issuer runs. The caller owns cancellation, resource observation,
    restoration and capture. No context is installed by default; nesting is
    refused. This test-only seam changes no physical argument or policy.
    """
    if not callable(factory) or _ALE_COMPUTE_CONTEXT.get() is not None:
        raise ValueError('One explicit non-nested ALE diagnostic context required')
    token = _ALE_COMPUTE_CONTEXT.set(factory)
    try:
        yield
    finally:
        _ALE_COMPUTE_CONTEXT.reset(token)


def _store(path):
    """Explicit joined-case storage, not the small I02 fixture's 16 MiB cap.

    The user's larger validation resource envelope admits a 256 MiB fully
    decoded snapshot and 1 GiB on disk. Existing chunk, staging, manifest and
    shared WorkBudget guards remain active; no scientific bound changes.
    """
    return F2.store(path, max_array_bytes=256 << 20, max_store_bytes=1 << 30)


def stream_allowance(partition, interval, native_cells, *, force_control=ORIGINAL_CONTROL):
    """Existing relative stream factor, declared before integrating streams.

    The explicit original control uses its full-shell meridian lune; the
    transform control uses relative tangential transport through its real
    Cartesian cut face. Divide either predeclared physical scale by an upper
    bound on ALL directed queries, never an observed error or coarse volume.
    """
    record = interval.record()
    if W._decode(record['radius_m']) != 10:
        raise ValueError('the analytical shell belongs to the original ten-metre fixture')
    rates = {p: tuple(map(W._decode, row)) for p, row in record['plate_angular_velocity_rad_s'].items()}
    groups, count = {}, 0
    for support in partition.supports:
        row = support.record()
        # Within one decoded support a name is one constraint record and its
        # identity is a function of that record alone, so each token is
        # derived once. The record is looked up at every use all the same,
        # so a use the lookup refuses is refused wherever it stands. Nothing
        # is kept from one support to the next.
        tokens = {}
        for part in row['components']:
            count += 1
            for name, _ in part['constraints']:
                constraint = row['constraints'][name]
                token = tokens.get(name)
                if token is None:
                    identity = G._interface_identity(constraint)
                    token = tokens[name] = (tuple(row['voxel_index']), row['source_chart_id'],
                                            identity[0] if identity is not None else name)
                groups[token] = groups.get(token, 0)+1
    queries = 2*(6*count+sum(n+n*(n-1)//2 for n in groups.values())+6*native_cells)
    dt = W._decode(record['end_time_s'])-W._decode(record['start_time_s'])
    sweep = force_control.stream_reference_volume(rates, dt)
    return sweep/Q(10**12*queries), queries


def created_tracer_bounds(transported, names):
    """Projection error and relative bound of each declared created tracer.

    The owner bounds a tracer its control declared as created by the source
    stage by the total mass: declared before any solve, and loose against
    the inventory actually transported. This is the relative contract of
    every other field, taken on one accepted transport record: 1e-10 of the
    sum of absolute exact input stocks of the field.
    """
    rows = {}
    for name in names:
        inventory = sum((abs(_q(v)) for v in transported['exact_input_stocks'][name]), Q(0))
        rows[name] = (_q(transported['field_errors'][name]['sum_absolute_local_and_binary_residual']),
                      inventory/Q(10**10))
    return rows


def _retain_failure(target, budget, size, *, category, **parts):
    """One failure-only compressed replay capture, encoded on the shared budget.

    A part is plain text or the record() of an issued object, called here so
    that the decoded tables, the JSON text and its ASCII copy exist only
    inside the reservation. ``size`` is the encoded length of those objects
    and the factor is that of the native-directed capture. The file is
    opened once the bytes are complete and removed if its write or its
    close fails, so no partial capture is left; an existing file is never
    replaced.
    """
    import gzip
    with budget.reserve(131072+12*size, category=category):
        capture = {name: part() if callable(part) else part for name, part in parts.items()}
        encoded = json.dumps(capture, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')
        raw = target.open('xb')
        try:
            # Leaving the file closes it even when its last buffered bytes
            # cannot be written, so it can be removed on every platform.
            with raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as packed:
                packed.write(encoded)
        except BaseException:
            raw.close(); target.unlink()
            raise


def _interface_parallel_policy(ale_parallel):
    """The enclosure's scheduling policy: the caller's, or the launch environment's.

    ATLAS_INTERFACE_PARALLEL is auto (also when absent), serial or off, and
    ATLAS_INTERFACE_PROFILE optionally names an observation store outside the
    source tree. They are read here, in the test helper, never in the
    package, and select execution only: no physical request changes.
    """
    if ale_parallel is not None:
        if type(ale_parallel) is not PS.InterfaceParallelPolicy:
            raise ValueError('ale_parallel must be an InterfaceParallelPolicy or None')
        return ale_parallel
    mode = os.environ.get('ATLAS_INTERFACE_PARALLEL', 'auto')
    if mode not in PS.MODES:
        raise ValueError('ATLAS_INTERFACE_PARALLEL must be auto, serial or off')
    return PS.InterfaceParallelPolicy(mode=mode, profile_path=os.environ.get('ATLAS_INTERFACE_PROFILE') or None)


def _report_interface_parallel(folder, number, previous, error=None):
    """Print, and save beside the other artifacts, what the enclosure's scheduler decided.

    Scheduling evidence only: it is not part of ``progress`` or ``result``. A
    report that cannot be printed or saved becomes a note, never a failure.
    """
    try:
        decision = PS.last_decision()
        if decision is None or previous is not None and decision['sequence'] == previous['sequence']:
            decision = dict(route='serial', reason='no decision recorded',
                            detail='the enclosure ended before its scheduling selection')
        print('ACTUAL_DIFFERENTIAL_PARALLEL', json.dumps(decision, sort_keys=True), flush=True)
        if folder:
            with (Path(folder)/('differential-parallel-%02d.json' % number)).open(
                    'x', encoding='utf-8', newline='\n') as stream:
                json.dump(decision, stream, sort_keys=True, indent=2, allow_nan=False)
                stream.write('\n')
    except Exception as report_error:
        note = 'Interface scheduling report failed: %s: %s' % (type(report_error).__name__, report_error)
        if error is not None:
            error.add_note(note)
        else:
            try:
                print(note, flush=True)
            except Exception:
                pass


def _advance_current_interval(test, case, workflow, *, current, parent, owner, driver,
                              pressure, datum, network, prior_interval=None, force_control=ORIGINAL_CONTROL,
                              predictor=None, orientation_max_leaves=64,
                              native_directed_max_leaves=None, native_mask_max_leaves=None,
                              ale_max_leaves=None, final_trace_max_leaves=64,
                              thermal_max_leaves=64, thermal_witness_refinements=8, ale_parallel=None):
    """One proposal/publication from the actual head; no initial-state fallback.

    The helper's local proposal, iteration and mesh leave scope before a second
    interval is prepared. Only accepted-state replay operands are returned.
    Optional resource keywords are prospective work ceilings, not changed
    physical accuracy, force controls, retry counts or publication authority.
    ``ale_parallel`` is the enclosure's InterfaceParallelPolicy; None takes it
    from the launch environment. It schedules exact interface queries only.
    """
    # Refused before any expensive work, like the ceilings below.
    ale_parallel = _interface_parallel_policy(ale_parallel)
    if native_directed_max_leaves is None:
        native_directed_max_leaves = force_control.native_directed_max_leaves
    if native_mask_max_leaves is None:
        native_mask_max_leaves = force_control.native_mask_max_leaves
    if ale_max_leaves is None:
        ale_max_leaves = force_control.ale_max_leaves
    for name, value in (('orientation_max_leaves', orientation_max_leaves),
                        ('native_directed_max_leaves', native_directed_max_leaves),
                        ('native_mask_max_leaves', native_mask_max_leaves),
                        ('ale_max_leaves', ale_max_leaves),
                        ('final_trace_max_leaves', final_trace_max_leaves),
                        ('thermal_max_leaves', thermal_max_leaves)):
        if type(value) is not int or value < 1:
            raise ValueError(name+' must be an explicit positive integer work ceiling')
    if type(thermal_witness_refinements) is not int or thermal_witness_refinements < 0:
        raise ValueError('thermal_witness_refinements must be an explicit nonnegative integer work ceiling')
    budget, collar, funding = case['budget'], case['collar'], case['funding']
    sphere = case['source'][0]
    state, spatial_state, before_head = workflow.state, workflow.exterior_state, workflow.inspect()
    start_temperature = case['native']._fields(state.native_state)[3]
    workload = force_control.workload(case)
    workload_account = None
    if workload is not None:
        capacities = np.sum(state.native_state.array('component_mass_kg'), axis=0)*case['material'].heat_capacity_j_kg_k
        minimum_capacity = min(Q(float(v)) for v in capacities.flat)
        test.assertGreaterEqual(minimum_capacity, workload.capacity_floor_j_k)
    test.assertEqual(state.result_id, before_head['state_id'])
    test.assertEqual(spatial_state.state_id, before_head['exterior_state_id'])
    test.assertEqual(pressure.descriptor()['native_state_id'], state.native_state.result_id)
    test.assertEqual(pressure.descriptor()['spatial_state_id'], spatial_state.state_id)
    with PreparedDifferentialIteration(sphere, network, current, parent, funding,
            collar, state, owner, spatial_state, driver, pressure, datum,
            supplies=case['supplies'], sinks=case['sinks'], prior_interval=prior_interval, max_attempts=4,
            max_orientation_leaves=orientation_max_leaves, max_partition_components=8192,
            heat_source='test:no extra heat; native mechanical source booked once', budget=budget) as iteration, \
            ExitStack() as predictors:
        try:
            proposal = iteration.propose()
            fixed_point = [proposal.force_exchange.array('omega_rad_s').tolist()]
            # Declared same-parent fixed-point proposals. Each next driver
            # freezes the PRECEDING proposal's time-integrated component masks;
            # the accepted-start pressure, force and subspace never change. A
            # bitwise repeated rate is already its own candidate geometry.
            for _ in range(force_control.interval_predictor_proposals):
                if predictor is None:
                    raise ValueError('this control declares interval-predictor proposals without their driver factory')
                candidate_width, _ = stream_allowance(proposal.partition, proposal.interval,
                    len(collar.cell_geometries()), force_control=force_control)
                proposal = iteration.propose(predictors.enter_context(
                    predictor(proposal.interval, proposal.partition, candidate_width)))
                fixed_point.append(proposal.force_exchange.array('omega_rad_s').tolist())
                if fixed_point[-1] == fixed_point[-2]:
                    break
        except Exception as error:
            diagnostic = getattr(error, 'differential_force_failure', None)
            folder = os.environ.get('ATLAS_FOCUSED_ARTIFACT_DIR')
            if diagnostic is not None and folder:
                record = diagnostic.record()
                name = 'differential-force-failure-%s-%02d.json' % (record['iteration_id'][:16], record['attempt'])
                with (Path(folder)/name).open('x', encoding='utf-8', newline='\n') as stream:
                    json.dump(record, stream, sort_keys=True, indent=2, allow_nan=False)
                    stream.write('\n')
            raise
        interval, partition = proposal.interval, proposal.partition
        source, measured = proposal.source_flow_stage, proposal.native_faces
        if workload is not None:
            audit = source.source_stage.source_audit
            test.assertEqual(audit.descriptor()['duration_s'], workload.duration_s)
            np.testing.assert_array_equal(audit.array('external_heat_source_w_m3'), 0.)
            np.testing.assert_array_equal(audit.array('material_heat_source_w_m3'), 0.)
            power = sum((Q(float(p))*Q(float(v)) for p, v in zip(
                audit.array('viscous_heat_source_w_m3').flat, audit.array('cell_volume_m3').flat)), Q(0))
            booked_cells = tuple(Q(float(a))-Q(float(b)) for a, b in zip(
                audit.array('enthalpy_after_sources_j').flat, audit.array('enthalpy_before_sources_j').flat))
            test.assertGreaterEqual(min(booked_cells), 0)
            booked = sum(booked_cells, Q(0))
            test.assertGreaterEqual(power, 0)
            test.assertLessEqual(power, workload.power_w)
            test.assertGreaterEqual(booked, 0)
            test.assertLessEqual(booked, workload.energy_per_interval_j)
            workload_account = dict(**workload.record(), actual_power_w=V._encoded(power),
                actual_booked_source_energy_j=V._encoded(booked),
                current_minimum_capacity_j_k=V._encoded(minimum_capacity),
                current_cell_capacities_j_k=[V._encoded(Q(float(v))) for v in capacities.flat])
        width, queries = stream_allowance(partition, interval, len(collar.cell_geometries()),
                                         force_control=force_control)
        projection = project_native_faces(measured, funding, budget=budget)
        native_leaf_limit = native_directed_max_leaves
        native_mask_leaf_limit = native_mask_max_leaves
        ale_leaf_limit = ale_max_leaves
        try:
            directed = choose_native_directed_volumes(measured, projection,
                max_width_m3=width, max_leaves=native_leaf_limit, budget=budget)
        except Exception as error:
            folder = os.environ.get('ATLAS_FOCUSED_ARTIFACT_DIR')
            if folder:
                # Capture the exact already-computed operands once, not a
                # replacement flow or a new scientific acceptance condition.
                with budget.reserve(131072+12*(len(measured._json)+len(projection._json)),
                                    category='test-native-directed-failure-encode'):
                    diagnostic = dict(native=measured.record(), projection=projection.record(),
                        max_width_m3=V._encoded(width), max_leaves=native_leaf_limit,
                        details=getattr(error, 'directed_details', None), error=str(error))
                    with (Path(folder)/('native-directed-failure-%02d.json' %
                            (before_head['intervals']+1))).open('x', encoding='utf-8', newline='\n') as stream:
                        json.dump(diagnostic, stream, sort_keys=True, indent=2, allow_nan=False)
                        stream.write('\n')
            raise
        finite = owner._finite.restore(spatial_state.record()['finite_stock_state'])
        radius = Q(sphere.network.sphere.radius_m)
        folder = os.environ.get('ATLAS_FOCUSED_ARTIFACT_DIR')
        # Save the small converged-force/source audit BEFORE the expensive ALE
        # operation. This is an unpublished same-parent proposal, not a saved
        # material step or a reusable checkpoint that bypasses source guards.
        progress = dict(stage='converged force and source; before ALE, unpublished',
            proposal=proposal.record(), pressure_forcing_id=pressure.forcing_id,
            actual_plate_rates_rad_s=proposal.force_exchange.array('omega_rad_s').tolist(),
            same_parent_proposal_rates_rad_s=fixed_point,
            conditional_workload=workload_account, stream_width_m3=V._encoded(width),
            native_directed_leaf_limit=native_leaf_limit,
            native_mask_leaf_limit=native_mask_leaf_limit,
            ale_leaf_limit=ale_leaf_limit,
            directed_query_upper_bound=queries, current_budget=budget.statistics())
        if folder:
            with (Path(folder)/('differential-proposal-%02d.json' % (before_head['intervals']+1))).open(
                    'x', encoding='utf-8', newline='\n') as stream:
                json.dump(progress, stream, sort_keys=True, indent=2, allow_nan=False)
                stream.write('\n')
        print('ACTUAL_DIFFERENTIAL_PROPOSAL', json.dumps(progress, sort_keys=True), flush=True)
        scheduled = PS.last_decision()
        try:
            compute_context = _ALE_COMPUTE_CONTEXT.get()
            with nullcontext() if compute_context is None else compute_context():
                bounds = G.enclose_differential_ale(partition, interval, funding, collar, source,
                    native_measures=measured, native_projection=projection, native_directed_volumes=directed,
                    finite_stock_state=finite, max_volume_error_m3=32*radius**3,
                    max_stream_error_m3=width, max_leaves=ale_leaf_limit,
                    max_native_mask_leaves=native_mask_leaf_limit, budget=budget, parallel=ale_parallel)
        except Exception as error:
            _report_interface_parallel(folder, before_head['intervals']+1, scheduled, error)
            # Geometry owns these bounded operands. Capture BOTH resource
            # failures and returned-but-unmet physical measures, including a
            # different later operation after the original failure is fixed.
            for attribute, name in (('component_volume_failure', 'component-volume-failure'),
                                    ('component_moment_failure', 'component-moment-failure'),
                                    ('physical_measure_failure', 'physical-measure-failure'),
                                    ('physical_stream_failure', 'physical-stream-failure')):
                diagnostic = getattr(error, attribute, None)
                if diagnostic is not None and folder:
                    with (Path(folder)/('%s-%02d.json' % (name, before_head['intervals']+1))).open(
                            'x', encoding='utf-8', newline='\n') as stream:
                        json.dump(diagnostic, stream, sort_keys=True, indent=2, allow_nan=False)
                        stream.write('\n')
            if folder:
                from i04_differential_fixture import capture_ale_replay
                try:
                    count, size = capture_ale_replay(Path(folder)/('ale-replay-inputs-%02d.jsonl.gz' %
                        (before_head['intervals']+1)), partition=partition, interval=interval,
                        native=measured, projection=projection, directed=directed,
                        width=32*radius**3, stream_width=width, max_leaves=ale_leaf_limit,
                        max_native_mask_leaves=native_mask_leaf_limit, budget=budget)
                    print('ALE replay retained:', count, 'records;', size, 'uncompressed bytes', flush=True)
                except Exception as capture_error:
                    error.add_note('Complete ALE replay capture failed: '+str(capture_error))
            raise
        _report_interface_parallel(folder, before_head['intervals']+1, scheduled)
        original_trace = driver._lift._trace
        try:
            with T.PreparedDifferentialTrace(original_trace._native, case['volume_map'], interval,
                    V.RadialLayer(10, 0, 3, budget=budget), network=network, plate_ids=original_trace._plate_ids,
                    endpoint=None, open_side='z0', max_moment_width=Q(1, 10**24),
                    max_volume_width=width, max_leaves=final_trace_max_leaves,
                    component_partition=partition, budget=budget) as final_trace:
                solution = iteration.certify(proposal, final_trace, bounds,
                    max_l2_error_squared=10000, max_work_error=10000)
        except Exception as error:
            # Failure-only replay operands of the final-rate trace and of the
            # exact carried-volume closure: an unmet plate or component moment
            # query, or the complete infeasible graph (compressed). Nothing is
            # repaired or admitted from them; they avoid repeating the native
            # mechanics and the enclosure to examine the refusal.
            if folder:
                import gzip
                number = before_head['intervals']+1
                for attribute, name in (('physical_measure_failure', 'final-trace-measure-failure'),
                                        ('component_moment_failure', 'final-trace-component-moment-failure'),
                                        ('circulation_failure', 'circulation-failure')):
                    diagnostic = getattr(error, attribute, None)
                    if diagnostic is None:
                        continue
                    target = Path(folder)/('%s-%02d.json.gz' % (name, number))
                    with target.open('xb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as packed:
                        packed.write(json.dumps(diagnostic, sort_keys=True, separators=(',', ':'),
                                                allow_nan=False).encode('ascii'))
                    print('Final trace/closure replay retained:', target.name, flush=True)
            raise
        # The exact closure names the components that carry material: those
        # are the thermal cells, as the heat solve requires.
        try:
            mesh = H.build_differential_mesh(funding, bounds, partition.supports, endpoint='end',
                max_geometry_volume_error_m3=32*radius**3, max_leaves=thermal_max_leaves,
                max_witness_refinements=thermal_witness_refinements,
                closed_graph=solution.graph, budget=budget)
        except Exception as error:
            # Failure-only replay operands of the end thermal mesh: the exact
            # closure whose booked volumes name the thermal cells. Nothing is
            # repaired or admitted from them. A capture that fails is a note
            # on this refusal, never its replacement.
            if folder:
                try:
                    target = Path(folder)/('thermal-mesh-failure-%02d.json.gz' % (before_head['intervals']+1))
                    _retain_failure(target, budget, len(solution.graph._json),
                        category='test-thermal-mesh-failure-encode',
                        error=str(error), closed_graph=solution.graph.record)
                    print('Thermal mesh replay retained:', target.name, flush=True)
                except Exception as capture_error:
                    error.add_note('Thermal mesh replay capture failed: %s: %s' %
                                   (type(capture_error).__name__, capture_error))
            raise
        boundary = {name: ('power', 0.) for name in mesh.record()['required_thermal_boundary_faces']}
        # This owner funds finite stocks, so the caller declares the finite
        # exchanges explicitly: exactly the selection of the exact closure it
        # hands over, which may be empty. Nothing is added or left out here.
        exchanges = list(solution.graph.record().get('finite_exchanges', []))
        arguments = dict(differential_interval=interval, differential_partition=partition,
            differential_solution=solution, heat_boundary=boundary, finite_exchanges=exchanges)
        with test.assertRaises(CancelledError):
            workflow.advance_spatial(source, bounds, mesh, cancel=lambda: True, **arguments)
        test.assertEqual(workflow.inspect(), before_head)
        try:
            accepted = workflow.advance_spatial(source, bounds, mesh, **arguments)
        except Exception as error:
            # Failure-only replay operands of the joint transport and heat:
            # the closed graph, the thermal mesh and, when it can be repeated,
            # the transport result. Nothing is repaired or admitted from them.
            # The refusal text is taken before the transport is repeated, and
            # the repeat runs before the encoding is reserved. A repeat that
            # refuses is recorded in the capture; a capture that fails is a
            # note on this refusal, never its replacement.
            if folder:
                try:
                    target = Path(folder)/('joint-advance-failure-%02d.json.gz' % (before_head['intervals']+1))
                    parts = dict(error=str(error), closed_graph=solution.graph.record, thermal_mesh=mesh.record)
                    size = len(solution.graph._json)+len(mesh._json)
                    try:
                        repeated = owner.transport(spatial_state, source, solution.graph,
                                                   finite_exchanges=exchanges).result
                        size += len(repeated._snapshot._metadata)
                        parts['transport'] = repeated.record
                    except Exception as repeat_error:
                        parts['transport_error'] = '%s: %s' % (type(repeat_error).__name__, repeat_error)
                    _retain_failure(target, budget, size, category='test-joint-advance-failure-encode', **parts)
                    print('Joint advance replay retained:', target.name, flush=True)
                except Exception as capture_error:
                    error.add_note('Joint advance replay capture failed: %s: %s' %
                                   (type(capture_error).__name__, capture_error))
            raise
        check_global_accounts(test, spatial_state, source, accepted)
        # The global accounts close with any booked projection error, and the
        # owner bounds a created tracer only by the total mass. Hold each one
        # the control declared to the inventory this advance transported.
        transported = accepted.exterior._transport.record()
        created = created_tracer_bounds(transported, case.get('created_tracers', ()))
        for name, (residual, bound) in created.items():
            test.assertLessEqual(residual, bound, '%s projection error %.3e exceeds 1e-10 of its transported input, %.3e' %
                                 (name, float(residual), float(bound)))
        test.assertEqual(workflow.inspect()['intervals'], before_head['intervals']+1)
        test.assertEqual(workflow.inspect()['time_s'], float(W._decode(interval.record()['end_time_s'])))
        test.assertIs(accepted.collar.transport_stage.spatial_result, accepted.exterior._transport)
        test.assertIs(accepted.collar.heat_stage.joined_result, accepted.exterior._heat)
        ids = (accepted.state.result_id, accepted.exterior.state.state_id,
               accepted.collar.source_stage.source_audit.result_id)
        restored = dict(ids=ids, head=workflow.inspect()['head'],
            record=accepted.exterior.state.record(), fields=accepted.exterior.state.arrays(),
            partition_id=partition.partition_id, interval_id=interval.interval_id,
            intervals=before_head['intervals']+1)
        result = dict(interval_id=interval.interval_id, solution_id=solution.solution_id,
            parent_state_id=state.result_id, parent_exterior_state_id=spatial_state.state_id,
            pressure_forcing_id=pressure.forcing_id,
            actual_plate_rates_rad_s=proposal.force_exchange.array('omega_rad_s').tolist(),
            same_parent_proposals=len(fixed_point),
            stream_width_m3=float(width), directed_query_upper_bound=queries,
            native_directed_leaf_limit=native_leaf_limit,
            native_mask_leaf_limit=native_mask_leaf_limit,
            accepted_native_state_id=ids[0], accepted_exterior_state_id=ids[1],
            source_audit_id=ids[2], peak_accounted_bytes=budget.peak_reserved_bytes,
            native_temperature_change_k=float(np.max(np.abs(
                case['native']._fields(accepted.state.native_state)[3]-start_temperature))),
            native_component_mass_change_kg=float(np.max(np.abs(
                accepted.state.native_state.array('component_mass_kg')-state.native_state.array('component_mass_kg')))),
            native_enthalpy_change_j=V._encoded(sum((Q(float(v)) for v in
                accepted.state.native_state.array('enthalpy_j').flat), Q(0))-
                sum((Q(float(v)) for v in state.native_state.array('enthalpy_j').flat), Q(0))),
            accepted_start_pressure_uses_native_state_id=pressure.descriptor()['native_state_id'],
            accepted_start_pressure_uses_spatial_state_id=pressure.descriptor()['spatial_state_id'],
            finite_exchanges=len(exchanges),
            # Measured against the declared bound of each field, in its units.
            transport_projection_error_and_bound={name: [float(_q(row['sum_absolute_local_and_binary_residual'])),
                                                         float(_q(row['allowed']))]
                for name, row in sorted(transported['field_errors'].items())},
            geometry_scope='coarse construction32R^3 only; not physical/thermal spatial accuracy acceptance',
            scope='one actual differential publication from accepted fields; coarse geometry, not resolution acceptance')
        if created:
            # Measured against 1e-10 of the inventory actually transported.
            result['created_tracer_projection_error_and_input_bound'] = {
                name: [float(residual), float(bound)] for name, (residual, bound) in sorted(created.items())}
        if workload_account is not None:
            result['force_control'] = force_control.family
            result['conditional_workload'] = workload_account
        if force_control.family == 'equatorial-transform':
            rates = dict(zip(network.plate_ids, proposal.force_exchange.array('omega_rad_s')))
            relative = rates['north']-rates['south']
            np.testing.assert_array_equal(relative[:2], 0.)
            test.assertNotEqual(float(relative[2]), 0.)
            # The native source audit is the actual same-solve heating, before
            # advection. The local second index crosses the real equator.
            viscous = source.source_stage.source_audit.array('viscous_heat_source_w_m3').reshape(collar.cells)
            side_power = [float(np.sum(viscous[:, j, :]))/8 for j in range(2)]
            for power in side_power:
                test.assertGreater(power, 0.)
            result['force_control'] = force_control.family
            result['relative_equatorial_slip_m_s_at_radius10'] = 10*abs(float(relative[2]))
            result['side_viscous_power_w'] = side_power
            result['stream_reference'] = 'relative tangential y-cut transport17/4*abs(deltaOmega)*dt; no normal equator sweep'
        folder = os.environ.get('ATLAS_FOCUSED_ARTIFACT_DIR')
        if folder:
            target = Path(folder)/('differential-interval-%02d.json' % restored['intervals'])
            with target.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
                stream.write('\n')
        print('ACTUAL_DIFFERENTIAL_JOINED', json.dumps(result, sort_keys=True), flush=True)
        return result, restored


def _check_reopened(test, workflow, expected):
    test.assertEqual(workflow.inspect()['head'], expected['head'])
    test.assertEqual(workflow.inspect()['intervals'], expected['intervals'])
    test.assertEqual(workflow.state.result_id, expected['ids'][0])
    test.assertEqual(workflow.exterior_state.state_id, expected['ids'][1])
    test.assertEqual(workflow.source_audit.result_id, expected['ids'][2])
    test.assertEqual(workflow.exterior_state.record(), expected['record'])
    for name, values in expected['fields'].items():
        np.testing.assert_array_equal(workflow.exterior_state.arrays()[name], values)
    test.assertEqual(workflow.differential_partition.partition_id, expected['partition_id'])
    test.assertEqual(workflow.differential_interval.interval_id, expected['interval_id'])


def check_joined_interval(test, case, current, parent, owner, driver, pressure, datum,
                          *, force_control=ORIGINAL_CONTROL, predictor=None):
    """Publish/reopen twice, refreshing physical force only from accepted fields.

    Must run inside the first actual driver/trace/native contexts. No separate
    geometry campaign, heat replay, or fresh owner admission is performed.
    """
    from i04_differential_continuation_control import continuation_pressure_force
    budget, collar, funding = case['budget'], case['collar'], case['funding']
    force_control.validate_case(case)
    original_temperature = case['native']._fields(case['state'].native_state)[3].copy()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)/'actual-differential.sqlite'
        with _store(path) as store, CollarWorkflow.create(store, collar, case['owner'], funding,
                budget=budget, exterior_owner=owner, differential_partition=parent,
                current_geometry=current) as workflow:
            identity = workflow.workflow_id
            test.assertEqual(workflow.state.result_id, case['state'].result_id)
            first, restored = _advance_current_interval(test, case, workflow, current=current,
                parent=parent, owner=owner, driver=driver, pressure=pressure, datum=datum,
                network=case['source'][0].network, force_control=force_control, predictor=predictor)
        with _store(path) as store:
            counters = operations(collar)
            with CollarWorkflow.open(store, identity, collar, case['owner'], funding, budget=budget) as reopened:
                test.assertEqual(operations(collar), counters)
                _check_reopened(test, reopened, restored)
                # Release large first replay operands before the next pressure,
                # trace and geometry are prepared on the SAME shared budget.
                del restored
                current_temperature = case['native']._fields(reopened.state.native_state)[3]
                temperature_change = float(np.max(np.abs(current_temperature-original_temperature)))
                test.assertGreater(temperature_change, 0.)

                def continue_actual(**prepared):
                    test.assertEqual(prepared['state'].result_id, first['accepted_native_state_id'])
                    test.assertEqual(prepared['spatial_state'].state_id, first['accepted_exterior_state_id'])
                    test.assertNotEqual(prepared['pressure'].forcing_id, first['pressure_forcing_id'])
                    next_pressure = prepared['pressure'].descriptor()
                    test.assertEqual(next_pressure['native_state_id'], prepared['state'].native_state.result_id)
                    test.assertEqual(next_pressure['spatial_state_id'], prepared['spatial_state'].state_id)
                    result, replay = _advance_current_interval(test, case, reopened,
                        current=prepared['current'], parent=prepared['partition'], owner=prepared['owner'],
                        driver=prepared['driver'], pressure=prepared['pressure'], datum=prepared['datum'],
                        network=prepared['network'], prior_interval=prepared['prior_interval'],
                        force_control=force_control, predictor=prepared.get('predictor'))
                    result['current_temperature_change_k'] = temperature_change
                    result['current_force_provenance'] = prepared['provenance']
                    return result, replay

                second, restored = continuation_pressure_force(test, case, reopened, continue_actual,
                                                               force_control=force_control)
        with _store(path) as store:
            counters = operations(collar)
            with CollarWorkflow.open(store, identity, collar, case['owner'], funding, budget=budget) as reopened:
                test.assertEqual(operations(collar), counters)
                _check_reopened(test, reopened, restored)
                test.assertEqual(reopened.inspect()['intervals'], 2)
        report = dict(first=first, second=second, accepted_exterior_state_id=second['accepted_exterior_state_id'],
            scope='two actual differential publications with refreshed carried material forcing and two fresh-store opens')
        folder = os.environ.get('ATLAS_FOCUSED_ARTIFACT_DIR')
        if folder:
            with (Path(folder)/'differential-continuation.json').open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
                stream.write('\n')
        print('ACTUAL_DIFFERENTIAL_CONTINUATION', json.dumps(report, sort_keys=True), flush=True)
        return report
