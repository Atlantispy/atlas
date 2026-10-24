"""Live second-interval force factory for the actual reopened workflow.

Preparation for a joined control, not a continuation result. No fresh material,
volume map, spatial owner, thermal mesh, motion, source stage or heat is created.
The immutable source is consulted only for funding/source provenance and the
original authored force-owner names. All pressure/EOS fields come from the
current accepted native/exterior state and its carried physical partition.

SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from pathlib import Path
import json
import os

import numpy as np

import i04_fixtures as F
from i04_differential_modes import ORIGINAL_CONTROL
from atlas_tectonics import integration_differential_geometry as G
from atlas_tectonics import integration_differential_pressure as P
from atlas_tectonics import integration_differential_trace as T
from atlas_tectonics import integration_driving as D
from atlas_tectonics import integration_regional_driving as R
from atlas_tectonics import integration_volume as V
from atlas_tectonics import integration_wall_measures as W
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.integration_radial_pressure import RadialDatum
from atlas_tectonics.integration_regional_workflow import CollarWorkflow
from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D


def _current_trace(number, *args, **kwargs):
    """The refreshed current-state trace; a refusal keeps its bounded operands.

    Geometry attaches the support, query and unmet measure to the error. They
    are written only on failure and only where the focused artifact folder is
    declared, under a name of this stage, and never replace the refusal.
    """
    try:
        return T.PreparedDifferentialTrace(*args, **kwargs)
    except Exception as error:
        folder = os.environ.get('ATLAS_FOCUSED_ARTIFACT_DIR')
        for attribute, name in (('component_volume_failure', 'component-volume-failure'),
                                ('component_moment_failure', 'component-moment-failure'),
                                ('physical_measure_failure', 'physical-measure-failure')):
            diagnostic = getattr(error, attribute, None)
            if diagnostic is not None and folder:
                try:
                    with (Path(folder)/('continuation-%s-%02d.json' % (name, number))).open(
                            'x', encoding='utf-8', newline='\n') as stream:
                        json.dump(diagnostic, stream, sort_keys=True, indent=2, allow_nan=False)
                        stream.write('\n')
                except Exception as capture_error:
                    error.add_note('Trace failure capture (%s) failed: %s' % (name, capture_error))
        raise


def _retain_trace_inputs(number, partition, volume_map, arguments, budget, *, name='continuation-trace-inputs',
                         scope='inputs of a prepared current-state differential continuation trace'):
    """Inputs of a differential trace, kept for offline replay of EVERY contact query.

    Written only where the focused artifact folder is declared, before the
    trace is built, so that a refusal of any contact can be replayed without
    the workflow (tools/replay_trace_contacts.py). Encoded on the shared
    budget like the other captures. Diagnostic evidence from already issued
    records; never an issued record itself.
    """
    folder = os.environ.get('ATLAS_FOCUSED_ARTIFACT_DIR')
    if not folder:
        return
    from i04_differential_joined_control import _retain_failure
    size = len(partition._json)+sum(len(support._json) for support in partition.supports)+len(volume_map._record)+4096
    if number is None:
        number = 1+sum(1 for _ in Path(folder).glob(name+'-*.json.gz'))
    try:
        _retain_failure(Path(folder)/('%s-%02d.json.gz' % (name, number)), budget, size,
            category='test-'+name+'-encode', scope=scope,
            partition=partition.record, supports=lambda: [support.record() for support in partition.supports],
            volume_map=volume_map.record, arguments=arguments)
    except Exception as error:
        # Retention is diagnostic: a file already present, a budget refusal
        # of the encoding or a write error never decides the workflow's result.
        print('Trace inputs not retained (%s):' % name, type(error).__name__, error, flush=True)


def _retain_trace_failure(error, name):
    """The refused query of a trace, written beside the other captures where the folder is declared."""
    folder = os.environ.get('ATLAS_FOCUSED_ARTIFACT_DIR')
    diagnostic = getattr(error, 'component_moment_failure', None)
    if diagnostic is None or not folder:
        return
    try:
        number = 1+sum(1 for _ in Path(folder).glob(name+'-*.json'))
        with (Path(folder)/('%s-%02d.json' % (name, number))).open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(diagnostic, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write('\n')
    except Exception as capture_error:
        error.add_note('Trace failure capture (%s) failed: %s' % (name, capture_error))


def continuation_pressure_force(test, case, workflow, prepared_control, *, force_control=ORIGINAL_CONTROL):
    """Call prepared_control while the refreshed force/trace contexts are live.

    The callback receives driver, pressure, datum, current, partition,
    prior_interval, network, state, spatial_state, owner and provenance, and for
    a control that declares interval-predictor proposals their factory. It may
    propose/certify/publish the next interval, but this factory never does so.
    The actual current state arguments must replace the initial case['state']
    and owner.initial_state in the caller's next PreparedDifferentialIteration.
    """
    budget, native, collar, funding = (case[k] for k in ('budget', 'native', 'collar', 'funding'))
    if (type(workflow) is not CollarWorkflow or workflow._budget is not budget or
            workflow._collar is not collar or workflow._funding is not funding or
            not callable(prepared_control)):
        raise TectonicsError('actual reopened workflow, same source plans/budget and test consumer required')
    before = workflow.inspect()
    state, spatial_state = workflow.state, workflow.exterior_state
    current, partition, prior = (workflow.current_geometry, workflow.differential_partition,
                                 workflow.differential_interval)
    owner = workflow._exterior_owner
    if (type(current) is not G.CurrentGeometry or type(partition) is not G.DifferentialPartition or
            type(prior) is not G.DifferentialInterval or before['intervals'] < 1 or
            spatial_state is None or owner is None):
        raise TectonicsError('a genuinely accepted and reopened differential interval is required')
    # endpoint_network is issued GEOMETRY ONLY. No old SphereState/material
    # shadow is constructed around it, and no support is resampled from it.
    network = prior.endpoint_network
    geo, part, accepted = current.record(), partition.record(), prior.record()
    material_state = spatial_state.record()
    start = network.time_s
    duration = force_control.duration(case)  # Same frozen initial workload, not updated from solved rates/heat.
    end = start+duration
    if (Q(end)-Q(start) != Q(duration) or current._resource is not budget or
            partition._resource is not budget or prior._resource is not budget or
            geo['accepted_interval_id'] != prior.interval_id or
            geo['network_id'] != network.network_id or
            part['scope'] != 'physical-interval' or part['interval_id'] != prior.interval_id or
            part['endpoint_network_id'] != network.network_id or
            W._decode(geo['time_s']) != Q(start) or
            W._decode(accepted['end_time_s']) != Q(start) or
            W._decode(part['end_time_s']) != Q(start) or
            spatial_state.time_s != start or state.native_state.descriptor()['time_s'] != start or
            geo['accepted_support_id'] != material_state['support_id'] or
            geo['accepted_trajectory_id'] != material_state['trajectory_id']):
        raise TectonicsError('current force continuation has stale geometry, material, trajectory or clock')
    owner.validate_parent(spatial_state, state)
    test.assertEqual(workflow.inspect()['head'], before['head'])
    source_sphere, source_moving = case['source'][:2]
    source_boundary = force_control.boundary(source_sphere.network)
    boundary = force_control.boundary(network)
    plates = boundary.left_plate_id, boundary.right_plate_id
    if (boundary.boundary_id != source_boundary.boundary_id or
            plates != (source_boundary.left_plate_id, source_boundary.right_plate_id)):
        raise TectonicsError('the original authored verification force owners changed')
    datum = RadialDatum(10., 1., 1., 7., 1.1, 0.,
        'synthetic constant-magnitude radial gravity; zero outer load; fixed support sphere')
    with PreparedRegionalStokes3D(native.cells, native.lengths_m, native._cs.viscosity_pa_s,
            native._pattern, scales=native._ms, reference_viscosity_pa_s=native._cs.viscosity_pa_s,
            frame_id=native._frame, vertical_datum=native._datum, material_source=native.plan_id,
            method='direct', physical_mean_pressure_pa=None, budget=budget,
            **native._pressure_reference_args) as prototype:
        # This is the SAME externally authored pressure, not a hydrostatic
        # profile inferred from depleted/mixed reservoir stocks or locations.
        reservoir = P.prescribe_reservoir_pressure(funding, collar, prototype,
            pressure_at_origin_pa=Q(5), gradient_pa_m=(0, 0, 0), origin_world_m=(0, 0, 0),
            source='synthetic explicit5Pa finite-compartment boundary pressure', budget=budget)
        pressure = P.differential_pressure_forcing(source_sphere, network, current, funding,
            collar, state, spatial_state, prototype, datum, reservoir,
            source_moving=source_moving, supports=partition.supports, endpoint='end',
            exterior_parent_state_id=state.result_id, max_torque_width_n_m=Q(1, 4),
            max_operator_error=Q(1, 10**20), max_leaves=4096, budget=budget)
        report = pressure.descriptor()
        test.assertEqual(report['native_state_id'], state.native_state.result_id)
        test.assertEqual(report['spatial_state_id'], spatial_state.state_id)
        test.assertEqual(report['geometry_id'], current.geometry_id)
        test.assertEqual(report['network_id'], network.network_id)
        test.assertEqual(report['time_s'], start)
        for row in report['physical_densities']:
            temperature = W._decode(row['temperature_k'])
            expected = Q(case['material'].density_kg_m3)*(1-Q(case['material'].expansion_per_k)*
                (temperature-Q(case['material'].reference_temperature_k)))
            test.assertEqual(W._decode(row['density_kg_m3']), expected)
        # Only the material pressure is updated. These literal external torques,
        # drag coefficient/radius and reservoir pressure stay exactly authored.
        torques = force_control.torques(network)
        forcing = F.authored_forcing(network, torques, drag=.001)
        prepared = D.prepare(network, forcing)
        interval = network.step, network.step+1, start, end
        exterior = D.balance(network, forcing, prepared=prepared,
            parent_state_id=state.result_id, interval=interval)
        basis, global_basis = force_control.basis(network, plates)
        _retain_trace_inputs(before['intervals']+1, partition, case['volume_map'],
            dict(plate_ids=list(plates), endpoint='current', open_side='z0', max_moment_width=V._encoded(Q(1, 10**24)),
                 max_volume_width=V._encoded(Q(0)), max_leaves=64), budget)
        with _current_trace(before['intervals']+1, prototype, case['volume_map'], current,
                V.RadialLayer(10, 0, 3, budget=budget), network=network,
                plate_ids=plates, endpoint='current', open_side='z0',
                max_moment_width=Q(1, 10**24), max_volume_width=0, max_leaves=64,
                component_partition=partition, budget=budget) as trace, \
             T.DifferentialPlateBoundaryLift(network, prototype, case['volume_map'], trace,
                boundary.boundary_id, angular_rate_basis=basis,
                map_source='actual complete material component masks',
                constraint_source=force_control.constraint_source,
                max_l2_error_squared=10000, max_work_error=10000, budget=budget) as lift, \
             R.PreparedRegionalDriving(network, forcing, exterior, prepared, lift, budget=budget,
                differential_pressure=pressure, pressure_native=prototype,
                global_angular_rate_basis=global_basis,
                global_constraint_source=force_control.constraint_source) as driver:
            provenance = dict(scope='prepared current-state differential continuation, not an accepted next interval',
                workflow_id=workflow.workflow_id, accepted_head=before['head'],
                parent_state_id=state.result_id, native_state_id=state.native_state.result_id,
                spatial_state_id=spatial_state.state_id, prior_interval_id=prior.interval_id,
                partition_id=partition.partition_id, current_geometry_id=current.geometry_id,
                network_id=network.network_id, interval=list(interval),
                pressure_id=pressure.forcing_id, forcing_id=forcing.forcing_id,
                exterior_prepared_id=prepared.prepared_id,
                authored=dict(torque_n_m=torques, basal_drag_pa_s_m=.001,
                    basal_drag_radius_m=prepared.basal_drag_radius_m,
                    reservoir_pressure_pa=5., reservoir_gradient_pa_m=[0., 0., 0.],
                    extra_body_force_n_m3=0., extra_heat_source_w_m3=0., datum=datum.record(),
                    angular_subspace=force_control.constraint_source),
                updated=['native and positioned exterior component mass, enthalpy and EOS density',
                    'actual accepted boundary/ownership masks and current network drag geometry',
                    'pressure torque and source-bound physical Q2 trace'],
                constitutive='prototype supplies geometry/reference only; next actual mechanics refreshes retained T/history',
                source_role='immutable funding coverage/identity only; no initial field or finite-stock refill')
            test.assertEqual(workflow.inspect()['head'], before['head'])
            extra = {}
            if force_control.interval_predictor_proposals:
                from i04_differential_predictor import interval_predictor
                extra['predictor'] = interval_predictor(case, network=network, current=current,
                    prototype=prototype, forcing=forcing, exterior=exterior, prepared=prepared, pressure=pressure,
                    plates=plates, boundary=boundary, basis=basis, global_basis=global_basis,
                    force_control=force_control)
            return prepared_control(driver=driver, pressure=pressure, datum=datum,
                current=current, partition=partition, prior_interval=prior, network=network,
                state=state, spatial_state=spatial_state, owner=owner, provenance=provenance, **extra)
