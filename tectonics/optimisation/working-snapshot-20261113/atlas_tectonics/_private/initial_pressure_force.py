from fractions import Fraction as Q

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

from atlas_tectonics.integration_pressure_coupling import radial_gravity_field

from atlas_tectonics.integration_radial_pressure import RadialDatum

from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES

def check_initial_pressure_force(test, case, current, partition, spatial_state, *, prepared_control=None,
                                 force_control=ORIGINAL_CONTROL, pressure_max_leaves=4096,
                                 initial_trace_max_leaves=64):
    """Use actual current material, not a forged port or a reconstructed mean.

    Returns the actual same-parent source/flow proposal and reconstructed force
    exchange. No accepted clock, finite stock or store is mutated here.
    An explicit test-only prepared_control may instead consume these live
    prepared objects for the joined acceptance harness. It replaces the
    preliminary source proposal, so that harness does not re-solve it first.
    Explicit leaf keywords change work ceilings only; physical/error limits
    and omitted-keyword behaviour remain the retained control's declarations.
    """
    for name, value in (('pressure_max_leaves', pressure_max_leaves),
                        ('initial_trace_max_leaves', initial_trace_max_leaves)):
        if type(value) is not int or value < 1:
            raise ValueError(name+' must be an explicit positive integer work ceiling')
    sphere, moving = case['source'][:2]
    budget, native, collar = case['budget'], case['native'], case['collar']
    state, funding = case['state'], case['funding']
    force_control.validate_case(case)
    test.assertIs(type(current), G.CurrentGeometry)
    test.assertEqual(partition.record()['current_geometry_id'], current.geometry_id)
    datum = RadialDatum(10., 1., 1., 7., 1.1, 0.,
        'synthetic constant-magnitude radial gravity; zero outer load; fixed support sphere')
    with PreparedRegionalStokes3D(native.cells, native.lengths_m, native._cs.viscosity_pa_s,
            native._pattern, scales=native._ms, reference_viscosity_pa_s=native._cs.viscosity_pa_s,
            frame_id=native._frame, vertical_datum=native._datum, material_source=native.plan_id,
            method='direct', physical_mean_pressure_pa=None, budget=budget,
            **native._pressure_reference_args) as prototype:
        reservoir = P.prescribe_reservoir_pressure(funding, collar, prototype,
            pressure_at_origin_pa=Q(5), gradient_pa_m=(0, 0, 0), origin_world_m=(0, 0, 0),
            source='synthetic explicit5Pa finite-compartment boundary pressure', budget=budget)
        force = P.differential_pressure_forcing(sphere, sphere.network, current, funding,
            collar, state, spatial_state, prototype, datum, reservoir, source_moving=moving,
            supports=partition.supports, exterior_parent_state_id=sphere.state_id,
            max_torque_width_n_m=Q(1, 4), max_operator_error=Q(1, 10**20),
            max_leaves=pressure_max_leaves, budget=budget)
        report = force.descriptor()
        test.assertEqual(report['native_state_id'], state.native_state.result_id)
        test.assertEqual(report['spatial_state_id'], spatial_state.state_id)
        # The physical current density values themselves must change with T;
        # new hashes alone are not a thermal-density observation.
        densities = report['physical_densities']
        actual_temperatures = {W._decode(row['temperature_k']) for row in densities}
        test.assertGreater(len(actual_temperatures), 1)
        material = case['material']
        for row in densities:
            temperature = W._decode(row['temperature_k'])
            expected = Q(material.density_kg_m3)*(1-Q(material.expansion_per_k)*
                (temperature-Q(material.reference_temperature_k)))
            test.assertEqual(W._decode(row['density_kg_m3']), expected)
        if force_control.coaxial:
            test.assertGreater(np.max(np.abs(force.array('hydrostatic_wall_torque_n_m'))), 0.)
        # Axisymmetric hemisphere densities need not exert any axial torque;
        # the transform is driven by the separately authored tangential loads.
        boundary = force_control.boundary(sphere.network)
        plates = boundary.left_plate_id, boundary.right_plate_id
        layer = V.RadialLayer(10, 0, 3, budget=budget)
        forcing = F.authored_forcing(sphere.network, force_control.torques(sphere.network), drag=.001)
        prepared = D.prepare(sphere.network, forcing)
        duration = force_control.duration(case)
        exterior = D.balance(sphere.network, forcing, prepared=prepared,
            parent_state_id=sphere.state_id, interval=(0, 1, 0., duration))
        basis, global_basis = force_control.basis(sphere.network, plates)
        with T.PreparedDifferentialTrace(prototype, case['volume_map'], current, layer,
                network=sphere.network, plate_ids=plates, endpoint='current', open_side='z0',
                max_moment_width=Q(1, 10**24), max_volume_width=0,
                max_leaves=initial_trace_max_leaves, budget=budget,
                component_partition=partition) as trace, \
             T.DifferentialPlateBoundaryLift(sphere.network, prototype, case['volume_map'], trace,
                boundary.boundary_id, angular_rate_basis=basis, map_source='actual complete material component masks',
                constraint_source=force_control.constraint_source,
                max_l2_error_squared=10000, max_work_error=10000, budget=budget) as lift, \
             R.PreparedRegionalDriving(sphere.network, forcing, exterior, prepared, lift, budget=budget,
                differential_pressure=force, pressure_native=prototype,
                global_angular_rate_basis=global_basis,
                global_constraint_source=force_control.constraint_source) as driver:
            tractions = {side: np.zeros_like(prototype.coordinates(side)) for side in SIDES}
            tractions['z0'] = force.array('reservoir_native_traction_pa')
            if prepared_control is not None:
                extra = {}
                if force_control.interval_predictor_proposals:
                    from atlas_tectonics._private.runtime_interval_predictor import interval_predictor
                    extra['predictor'] = interval_predictor(case, network=sphere.network, current=current,
                        prototype=prototype, forcing=forcing, exterior=exterior, prepared=prepared, pressure=force,
                        plates=plates, boundary=boundary, basis=basis, global_basis=global_basis,
                        force_control=force_control)
                return prepared_control(driver=driver, pressure=force, datum=datum, **extra)
            stage = collar.source_flow_stage(state, duration, velocity_m_s=0., dynamic_traction_pa=tractions,
                gravity_m_s2=radial_gravity_field(collar, datum, budget=budget), additional_body_force_n_m3=0.,
                driving_source=driver.driving_id, heat_source_w_m3=0., heat_source='no extra heat',
                coupling=driver.coupling())
            result = driver.reconstruct(stage.source_stage.initial_mechanics,
                parent_state_id=state.native_state.result_id, time_s=0.)
            rates = result.exchange.array('omega_rad_s')
            np.testing.assert_array_equal(rates[:, :2], 0.)
            checked = result.exchange.descriptor()
            test.assertLessEqual(checked['algebra_relative_residual'], R.ALGEBRA)
            test.assertLessEqual(checked['virtual_work_relative_residual'], R.WORK)
            test.assertEqual(checked['driving']['differential_pressure_partition']['forcing']['forcing_id'], force.forcing_id)
            work = checked['reservoir_pressure_work']
            test.assertEqual(W._decode(work['pressure_projection_work_residual_w']), 0)
            test.assertEqual(W._decode(work['pressure_projection_work_abs_bound_w']), 0)
            test.assertGreater(trace.descriptor()['component_partition']['actual_constraint_count'], 20)
            return dict(stage=stage, force=result.exchange, pressure=force, datum=datum)
