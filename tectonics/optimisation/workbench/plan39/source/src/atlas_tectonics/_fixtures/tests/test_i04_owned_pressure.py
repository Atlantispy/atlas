"""Owned wall integrals and pressure-reference virtual work, independently checked."""
from fractions import Fraction as Q
from dataclasses import replace
import gc
import math
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

from atlas_tectonics import integration_pressure_coupling as C
from atlas_tectonics import integration_volume as V
from atlas_tectonics import integration_regional_driving as R
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.regional_execution3d import SIDES
import i03_fixtures as F
from test_i04_pressure_partition import prepare
from test_i04_regional_driving import mapping


def primitive3(y, x):
    r = math.hypot(x, y)
    return y*r*(2*y*y+5*x*x)/8+3*x**4*math.asinh(y/x)/8


def primitive_log(y, x):
    return y*math.log(x*x+y*y)-2*y+2*x*math.atan(y/x)


def xr(x0, x1, y0, y1):
    return ((primitive3(y1, x1)-primitive3(y0, x1))-
            (primitive3(y1, x0)-primitive3(y0, x0)))/3


def x_inverse_r2(x0, x1, y0, y1):
    return ((primitive_log(y1, x1)-primitive_log(y0, x1))-
            (primitive_log(y1, x0)-primitive_log(y0, x0)))/2


def box(budget, low=(2, 1, -1), high=(3, 2, 1)):
    return V.CartesianCell(low, high, (0, 0, 0), ((1, 0, 0), (0, 1, 0), (0, 0, 1)), budget=budget)


def profiles():
    # Two layers, with the lower density2 layer below the anomaly support.
    # Surface r=4, p=1. Upper rho=1, lower r=1..1.5 rho=2.
    return (((Q(3, 2), Q(4), Q(1), Q(1)),
             (Q(1), Q(3, 2), Q(2), Q(7, 2))),)*2


class OwnedPressure(unittest.TestCase):
    def test_analytic_two_layer_density_anomaly_and_old_wall_replacement(self):
        budget = WorkBudget(256 << 20)
        cell = box(budget)
        common = dict(gravity=1, support_radius=1, width=Q(1, 8), max_leaves=4096, budget=budget)
        delta, removed, _ = C.wall_integrals((1, 0, 0), (0, 1, 0), profiles(), (cell,), (Q(1),), cell, **common)
        self.assertEqual(delta, ((Q(0), Q(0)),)*3)
        # p=5-r in the owned rectangle: integrate p*(y,-x,0) exactly.
        expected_removed = (Q(15, 2)-xr(1, 2, 2, 3), -Q(25, 2)+xr(2, 3, 1, 2), 0.)
        for (lo, hi), value in zip(removed, expected_removed):
            self.assertLessEqual(float(lo)-2e-13, value)
            self.assertGreaterEqual(float(hi)+2e-13, value)
        delta, _, _ = C.wall_integrals((1, 0, 0), (0, 1, 0), profiles(), (cell,), (Q(11, 10),), cell, **common)
        expected = ((xr(1, 2, 2, 3)-x_inverse_r2(1, 2, 2, 3))/30,
                    -(xr(2, 3, 1, 2)-x_inverse_r2(2, 3, 1, 2))/30, 0.)
        for (lo, hi), value in zip(delta, expected):
            self.assertLessEqual(float(lo)-2e-13, value)
            self.assertGreaterEqual(float(hi)+2e-13, value)
        self.assertGreater(delta[0][0], 0)
        self.assertLess(delta[1][1], 0)
        with self.assertRaises(C.PressureCouplingRefused):
            C.wall_integrals((1, 0, 0), (0, 1, 0), profiles(), (cell,), (Q(11, 10),), cell,
                **dict(common, width=Q(0), max_leaves=2))

    def test_actual_contact_splitting_rotation_and_resource_bound(self):
        budget = WorkBudget(256 << 20)
        cell = box(budget)
        lower, upper = box(budget, (2, 1, -1), (3, 2, 0)), box(budget, (2, 1, 0), (3, 2, 1))
        polygon, side = C.wall_polygon(cell, (1, 0, 0), (0, 1, 0))
        self.assertEqual(set(polygon), {(Q(2), Q(1)), (Q(3), Q(1)), (Q(3), Q(2)), (Q(2), Q(2))})
        self.assertIsNone(side)
        self.assertEqual(C.wall_polygon(lower, (1, 0, 0), (0, 1, 0))[1], 1)
        self.assertEqual(C.wall_polygon(upper, (1, 0, 0), (0, 1, 0))[1], 0)
        args = dict(gravity=1, support_radius=1, width=Q(1, 4), max_leaves=2048, budget=budget)
        whole = C.wall_integrals((1, 0, 0), (0, 1, 0), profiles(), (cell,), (Q(11, 10),), cell, **args)
        split = C.wall_integrals((1, 0, 0), (0, 1, 0), profiles(), (lower, upper), (Q(11, 10),)*2, cell, **args)
        for total, divided in zip(whole[:2], split[:2]):
            for a, b in zip(total, divided):
                self.assertLessEqual(max(a[0], b[0]), min(a[1], b[1]))
        # Exact +90 degree z rotation from a rational quaternion.
        rotated = cell.rotated((1, 0, 0, 1), budget=budget)
        turned = C.wall_integrals((0, 1, 0), (-1, 0, 0), profiles(), (rotated,), (Q(11, 10),), rotated, **args)
        for base, result in zip(whole[:2], turned[:2]):
            expected = ((-base[1][1], -base[1][0]), base[0], base[2])
            self.assertEqual(result, expected)
        with self.assertRaises(MemoryLimitError):
            C.wall_integrals((1, 0, 0), (0, 1, 0), profiles(), (cell,), (Q(11, 10),), cell,
                            **dict(args, budget=WorkBudget(1024)))

    def test_reference_counterterm_preserves_full_pressure_force_solution(self):
        budget = WorkBudget(256 << 20)
        network = F.three_plates(sphere=F.sphere(radius=10.), time_s=0.)
        results = []
        with threadpool_limits(1):
            for reference in (None, 5., 11., 'variable'):
                if reference == 'variable':
                    from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D
                    from atlas_tectonics.regional_execution import RegionalMechanicsScales
                    xyz = np.indices((3, 3, 3)).reshape(3, -1).T/2
                    native_context = PreparedRegionalStokes3D((2, 2, 2), (1., 1., 1.), 1.,
                        {s: ('velocity',)*3 if s[0] == 'x' else ('traction',)*3 for s in SIDES},
                        scales=RegionalMechanicsScales(1., 1.), reference_viscosity_pa_s=1.,
                        frame_id='test:coupled-box', vertical_datum='explicit embedded box',
                        material_source='test:fixed-or-thermal-source', method='direct', budget=budget,
                        pressure_reference_pa=5.+2*xyz[:, 0]-xyz[:, 2],
                        pressure_reference_source='test:nonmatching spatial reference', pressure_load_partition='full')
                else:
                    native_context = prepare(budget, reference, partition='full')
                with native_context as native:
                    footprint, args, _ = mapping(network, native)
                    with R.PlateBoundaryLift(network, native, footprint, 'boundary-m00', **args, budget=budget) as lift:
                        reference_force = lift._basis.T@C.reference_torque(native, lift).ravel()
                        drive = np.asarray([.1, .2, -.1, .3, -.2])-reference_force
                        extra = {} if reference is None else dict(pressure_reference_id=lift._pressure_reference['reference_id'])
                        result = native.solve_force_coupled(0., 0., {s: 0. for s in SIDES}, lift._modes,
                            drive, np.eye(5), coupling_source='test:physical-exterior-minus-exact-reference',
                            parent_state_id='test:current-owned-state', time_s=0., epoch_id=network.epoch_id,
                            force_source='test:full-physical-zero-body', boundary_source='test:full-physical-zero-traction', **extra)
                        results.append(result)
            for result in results[1:]:
                np.testing.assert_allclose(result.array('generalized_rates_s_inv'),
                    results[0].array('generalized_rates_s_inv'), rtol=1e-11, atol=2e-13)
                pressure_scale = max(float(np.max(np.abs(result.array(k)))) for k in
                    ('physical_pressure_pa', 'relative_pressure_pa', 'pressure_reference_pa'))
                self.assertLessEqual(float(np.max(np.abs(result.array('physical_pressure_pa')-
                    results[0].array('physical_pressure_pa')))), 1e-11*pressure_scale)
                np.testing.assert_allclose(result.array('full_velocity_constraint_reaction_n'),
                    results[0].array('velocity_constraint_reaction_n'), rtol=1e-11, atol=2e-13)
        self.assertEqual(budget.reserved_bytes, 0)


class FundedPressure(unittest.TestCase):
    def test_current_owned_heat_radial_gravity_and_actual_force_consumer(self):
        """Fresh uniform source; one-sided actual heat; no moving-source claim.

        Predeclared dimensioned synthetic request: g=1, source1.1 W/m3 in
        left interior cells for .25 s, insulated full grid; torque enclosure
        width1/2 N m, at most4096 leaves/integral. This enclosure is reported,
        not an acceptance tolerance or fit to a desired force response.
        """
        import test_i04_regional_owner as O
        import test_integration_collar_geometry as G
        from atlas_tectonics import integration_material as M, integration_ports as P
        from atlas_tectonics import integration_radial_pressure as H, integration_radial_strength as S
        from atlas_tectonics import integration_driving as D, integration_bridges as B
        from atlas_tectonics.constitutive import BoussinesqMaterial, DiffusiveScales
        from atlas_tectonics.integration_strength import CreepLaw
        from atlas_tectonics.regional_execution import RegionalMechanicsScales
        from atlas_tectonics.regional_evolution3d import PreparedRegionalEvolution3D
        from atlas_tectonics.regional_collar3d import PreparedRegionalCollar3D, RigidCollarMotion
        from test_regional_collar3d import native_driving

        budget = WorkBudget(256 << 20)
        fixture = list(O.physical_source(budget))
        sphere, original = fixture[:2]
        records = tuple(replace(row, sublayers=(replace(row.sublayers[0], alpha_per_k=.1,
            top_temperature_k=1.5, bottom_temperature_k=1.5),)) for row in original.cohorts)
        moving = M.declare_moving(sphere, records, enthalpy_reference_k=1., budget=budget)
        fixture[1], fixture[-1] = moving, (-.5, 1., -2.)
        fixture = tuple(fixture)
        volume_map = O.physical_map(fixture, budget)
        law = CreepLaw((dict(a=.5, n=1., energy_j_mol=0., volume_m3_mol=0., grain_exponent=0.),), 'analytic-SI')
        plastic = S.RadialPlasticity3D(1., 0., None, 1., (0., 1.), 1., 1.,
            'plastic branch explicitly disabled; no calibration')
        source = S.radial_strength_source(moving, sphere, volume_map,
            materials={'synthetic': plastic}, creep_laws={'test:constant-creep': law},
            provenance='actual uniform shell, nonzero thermal expansion', budget=budget)
        material = BoussinesqMaterial('test:pressure', 'synthetic', 1.1, 1., .1, .1, 1., 0., 0., (1., 2.))
        pattern = {s: tuple('velocity' if s[0] == 'x' or j == 'xyz'.index(s[0]) else 'traction'
                           for j in range(3)) for s in SIDES}
        with threadpool_limits(1), PreparedRegionalEvolution3D((2, 2, 2), (1., 1., 1.), material,
                None, DiffusiveScales('test:scales', 1., 1., 1., 1., 1., 1.), RegionalMechanicsScales(1., 1.),
                pattern, composition_values=(0., 1.), frame_id=fixture[2].region_id,
                vertical_datum='actual mapped radial shell', include_viscous_heating=True,
                divergence_rtol=1e-10, max_velocity_correction_m_s=1e-8,
                max_relative_correction=1e-6, mechanics_method='direct', budget=budget,
                radial_constitutive=source, physical_mean_pressure_pa=1., pressure_reference_pa=np.ones(27),
                pressure_reference_source='explicit discrete constant; counterterm cancels independently',
                pressure_load_partition='full') as native, \
                O.physical_owner(native, fixture, volume_map, budget) as owner, \
                PreparedRegionalCollar3D(native, volume_map, ((1, 1),)*3, budget=budget) as collar:
            funding = G.fund(fixture, owner, collar, budget)
            state = collar.initial_state_from_funding(funding, owner)
            support = P.material_trace_support(sphere)
            datum = H.RadialDatum(10., 1., 1., 7., 1.1, .1,
                'synthetic .1 Pa surface load; constrained support sphere')
            header = P.Header('P1', sphere.state_id, (0, 1, 0., .25), 0., sphere.network.network_id,
                support.support_id, datum.datum_id, moving.moving_id, sphere.network.sphere.frame_id,
                'test:owned-pressure', 'test:actual source')
            port = H.radial_pressure_trace(moving, sphere, support, header, datum, budget=budget)
            gravity = C.radial_gravity_field(collar, datum, budget=budget)
            xyz = source.array('position_m')
            np.testing.assert_array_equal(gravity.array(), (-xyz/np.linalg.norm(xyz, axis=-1)[..., None])@collar._basis)
            self.assertGreater(np.ptp(gravity.array()[..., 0]), 0.)
            initial = C.owned_pressure_correction(sphere, moving, support, port, funding, collar, state,
                max_torque_width_n_m=Q(1, 2), max_leaves=4096, budget=budget)
            names = tuple(k[7:] for k in state.native_state.array_names if k.startswith('tracer:'))
            stocks = collar._transport.empty_boundary_stocks(2, names)
            heat = np.zeros((2, 2, 2)); heat[0] = 1.1
            advanced = collar.advance(state, .25,
                rigid_motion=RigidCollarMotion((0., 0., 0.), 'stationary during explicit heat-only control'),
                boundary_stocks=stocks, heat_boundaries={s: ('flux', 0.) for s in SIDES},
                **native_driving(heat=heat))
            current = C.owned_pressure_correction(sphere, moving, support, port, funding, collar, advanced.state,
                max_torque_width_n_m=Q(1, 2), max_leaves=4096, budget=budget)
            density = current.array('current_cell_density_kg_m3')
            mass = np.sum(advanced.state.fields.array('component_mass_kg'), axis=0)
            actual_t = advanced.state.fields.array('enthalpy_j')/mass
            np.testing.assert_array_equal(density, 1.1-1.1*.1*(actual_t-1.))
            self.assertLess(float(np.min(density)), float(np.min(initial.array('current_cell_density_kg_m3'))))
            self.assertFalse(np.array_equal(current.array('density_update_torque_n_m'),
                                           initial.array('density_update_torque_n_m')))
            self.assertEqual(current.descriptor()['native_state_id'], advanced.state.native_state.result_id)
            self.assertEqual(current.descriptor()['source']['moving_id'], moving.moving_id)
            # Actual current-density radial gravity enters a single mechanics
            # solve; no source-stage advection/projection is disguised as solved.
            frame, _, rings, _, _ = B._charted(sphere.network, fixture[2])
            operator = native._mechanical
            nodes = frame.positions_to_cartesian(operator.coordinates('velocity')+fixture[-1], budget=budget)
            cells = {f: R.U.cells_of_rings(r) for f, r in rings.items()}
            owners = tuple(next(f for f in fixture[2].face_ids if R._contains(cells[f], p))
                if np.any(m) else None for p, m in zip(nodes, operator.velocity_mask()))
            # Net x-wall flux is proportional to 8.5*domega_y-1.5*domega_z:
            # the actual physical mid-wall coordinates are y=1.5,z=8.5.
            # This analytic compatibility constraint is not a fitted nullspace.
            basis = np.zeros((6, 5)); basis[:3, :3] = basis[3:, :3] = frame.basis
            basis[:3, 3], basis[3:, 3] = frame.basis[:, 0], -frame.basis[:, 0]
            compatible = 1.5*frame.basis[:, 1]+8.5*frame.basis[:, 2]
            basis[:3, 4], basis[3:, 4] = compatible, -compatible
            boundary = next(b.boundary_id for b in sphere.network.boundaries
                if {b.left_plate_id, b.right_plate_id} == {'A', 'B'})
            forcing = D.Forcing({p: .001 for p in sphere.network.plate_ids},
                'actual radial pressure plus separately owned native volume forces',
                omitted=('gpe', 'slab_pull', 'mantle_traction', 'authored_torque', 'interface'),
                frame_id=sphere.network.sphere.frame_id, basal_drag_radius_m=7.,
                radial_pressure_rule='central-half-radial-pressure-trace-v1')
            prepared = D.prepare(sphere.network, forcing)
            exterior = D.balance(sphere.network, forcing, support=support, datum=datum, prepared=prepared,
                radial_pressure_port=port, interface_pressure_rule='central-half-radial-pressure-trace-v1')
            with R.PlateBoundaryLift(sphere.network, operator, fixture[2], boundary,
                    origin_local_m=fixture[-1], node_face_ids=owners, angular_rate_basis=basis,
                    map_source='same actual funded geometry', constraint_source='8.5*domega_y=1.5*domega_z from exact mean x-wall lever arms',
                    volume_map=volume_map, budget=budget) as lift:
                results = []
                for actual, correction in ((state, initial), (advanced.state, current)):
                    with R.PreparedRegionalDriving(sphere.network, forcing, exterior, prepared, lift,
                            pressure_correction=correction, pressure_native=operator, budget=budget) as driver:
                        local_t = actual.native_state.array('enthalpy_j')/np.sum(
                            actual.native_state.array('component_mass_kg'), axis=0)
                        body = (1.1-1.1*.1*(local_t.reshape(8, 1)-1.))[..., None]*gravity.array()
                        result = driver.solve(operator, parent_state_id=actual.native_state.result_id,
                            time_s=actual.native_state.descriptor()['time_s'], epoch_id=sphere.network.epoch_id,
                            force_source='actual current density times issued radial quadrature gravity',
                            boundary_source='full zero natural traction, explicit reference subtraction', body_force_n_m3=body)
                        results.append(result)
                        self.assertLessEqual(result.exchange.descriptor()['algebra_relative_residual'], R.ALGEBRA)
                        self.assertEqual(driver.reconstruct(result.mechanical,
                            parent_state_id=actual.native_state.result_id,
                            time_s=actual.native_state.descriptor()['time_s']).exchange.result_id, result.exchange.result_id)
                self.assertFalse(np.array_equal(results[0].exchange.array('omega_rad_s'), results[1].exchange.array('omega_rad_s')))
            del gravity, funding, initial, current, correction
            # A retained collar stage holds its bytes while its advance
            # result is alive; release the results before asking for zero.
            del advanced, results, result, driver, state, exterior, prepared
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


class RadialGravityEvolution(unittest.TestCase):
    def test_actual_radial_gravity_enters_native_donor_stage(self):
        import test_i05_radial_strength as S
        from atlas_tectonics import integration_radial_pressure as H, integration_bridges as B
        from atlas_tectonics import integration_regional_evolution as O
        from atlas_tectonics.constitutive import BoussinesqMaterial, DiffusiveScales
        from atlas_tectonics.regional_execution import RegionalMechanicsScales
        from atlas_tectonics.regional_evolution3d import PreparedRegionalEvolution3D
        from atlas_tectonics.regional_collar3d import PreparedRegionalCollar3D

        budget = WorkBudget(256 << 20)
        sphere, moving, volume_map, seed, source, _, laws = S.fixture(budget, plastic=None, friction=0.)
        seed.close()
        request = volume_map.record()['request']
        rows = volume_map.record()['cell_sources']
        components = len({(row['patch_id'], row['sublayer']) for row in rows})
        with threadpool_limits(1), PreparedRegionalEvolution3D((2, 2, 2), (1., 1., 1.),
                BoussinesqMaterial('synthetic', 'same source material', 1., 1., 1., 0., 500., 0., 0., (400., 600.)),
                None, DiffusiveScales('synthetic', 1., 1., 1., 400., 200., 1.), RegionalMechanicsScales(1., 1.),
                {s: ('velocity',)*3 for s in SIDES}, composition_values=(0.,)*components,
                frame_id='test:coupled-box', vertical_datum='actual embedded shell', include_viscous_heating=True,
                divergence_rtol=1e-10, max_velocity_correction_m_s=1e-8, max_relative_correction=1e-6,
                mechanics_method='direct', budget=budget, radial_constitutive=source,
                physical_mean_pressure_pa=5.) as native, \
                O.PreparedRegionalOwner(native, sphere, moving, B.Footprint(**request['footprint']),
                    plate_ids=tuple(sorted({row['plate_id'] for row in rows})),
                    creep_match={'creep_law_id': 'creep', 'law': laws['creep'].record()},
                    map_source=request['map_source'], volume_map=volume_map, budget=budget) as owner, \
                PreparedRegionalCollar3D(native, volume_map, ((1, 1),)*3, budget=budget) as collar:
            datum = H.RadialDatum(10., 1., 500., 7., 1., .1, 'synthetic explicit surface load and support')
            gravity = C.radial_gravity_field(collar, datum, budget=budget)
            stage = native.source_stage(owner.initial_state.native_state, .001,
                velocity_m_s=0., dynamic_traction_pa={s: 0. for s in SIDES}, gravity_m_s2=gravity,
                additional_body_force_n_m3=0., driving_source='actual full radial gravity',
                heat_source_w_m3=0., heat_source='only actual same-solve viscous heat')
            self.assertEqual(stage.driving.descriptor()['radial_gravity']['field_id'], gravity.field_id)
            np.testing.assert_array_equal(stage.driving.array('gravity_m_s2'), gravity.array())
            self.assertIs(stage.mechanical_arguments()[2], gravity)
            self.assertLessEqual(stage.initial_mechanics.descriptor()['work_relative_residual'], R.WORK)
            np.testing.assert_array_equal(stage.initial_mechanics.array('velocity_m_s'), 0.)
            xyz = source.array('position_m')
            radius = np.linalg.norm(xyz, axis=-1)
            weights = native._mechanical._mesh.quadrature_weights
            mean_radius = np.sum(radius*weights)/np.prod(native.lengths_m)
            expected_pressure = 5.+mean_radius-radius
            np.testing.assert_allclose(stage.initial_mechanics.array('physical_pressure_q_pa'),
                expected_pressure, rtol=64*np.finfo(float).eps, atol=0.)
            np.testing.assert_allclose(stage.initial_mechanics.array('full_cauchy_stress_q_pa'),
                -expected_pressure[..., None, None]*np.eye(3), rtol=64*np.finfo(float).eps, atol=0.)
            self.assertEqual(stage.flow.descriptor()['correction_max_m_s'], 0.)
            self.assertTrue(np.any(stage.initial_mechanics.array('analytic_hydrostatic_velocity_constraint_reaction_n') != 0.))
            self.assertIn('analytic_hydrostatic_body_quadrature_difference_n', stage.initial_mechanics.array_names)
            del gravity, stage
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
