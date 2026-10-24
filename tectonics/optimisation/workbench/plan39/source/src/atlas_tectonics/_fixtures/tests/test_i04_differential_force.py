"""Actual initial differential pressure/force checker for the shared spatial case.

Called by the owner of the real static spatial fixture; this module does not
repeat its complete geometry build. Before execution: torque width1/4 N m,
operator bound1e-20, at most4096 integral leaves; exact current face moments
at1e-24, existing trace limits1e4 and original native force/FV gates. These are
synthetic connection bounds, not spatial-convergence or planetary accuracy.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
import unittest

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


class ForceFailureDiagnostics(unittest.TestCase):
    def test_preflight_rejects_oversized_shapes_before_any_snapshot_copy(self):
        from types import SimpleNamespace
        from atlas_tectonics.integration_differential_coupling import _force_diagnostic_preflight
        driver = SimpleNamespace(_matrix=np.empty((9, 9)), _resistance=np.empty((2, 2)),
            _drive=np.empty(2), _lift=SimpleNamespace(_basis=np.empty((6, 2))),
            _global_basis=np.empty((9, 2)))
        self.assertGreater(_force_diagnostic_preflight(driver, 3, 3), 0)
        self.assertIsNone(_force_diagnostic_preflight(driver, 3, 257))
        driver._matrix = np.empty((100, 100))
        self.assertIsNone(_force_diagnostic_preflight(driver, 3, 3))

    def test_small_operands_are_retained_charged_and_oversized_diagnostics_are_omitted(self):
        import gc
        from atlas_tectonics.integration_differential_coupling import _force_failure_diagnostic
        from atlas_tectonics.resources import WorkBudget, MemoryLimitError
        budget = WorkBudget(1 << 20)
        matrix = np.asarray(((2., -1.), (-1., 3.)))
        receipt = _force_failure_diagnostic(dict(parent_state_id='a'*64, published=False),
                                            dict(matrix=matrix), budget)
        self.assertEqual(receipt.record()['arrays']['matrix'], matrix.tolist())
        self.assertFalse(receipt.record()['published'])
        self.assertGreater(budget.reserved_bytes, 0)
        matrix[:] = 0
        self.assertEqual(receipt.record()['arrays']['matrix'], [[2., -1.], [-1., 3.]])
        del receipt
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertIsNone(_force_failure_diagnostic({}, dict(large=np.empty(8193)), budget))
        with self.assertRaises(MemoryLimitError):
            _force_failure_diagnostic({}, dict(matrix=matrix), WorkBudget(1024))


class RadialFirstPressure(unittest.TestCase):
    def test_shared_radial_endpoint_identity_is_algebraic_not_interval_overlap(self):
        from atlas_tectonics import integration_pressure_coupling as C
        from atlas_tectonics import integration_volume_overlap as O
        a, b = (Q(1), Q(0), Q(0)), (Q(0), Q(1), Q(0))
        left, right = Q(1, 4), Q(1, 3)
        s, _ = C._radial_chart_jets(a, b, O._cross(a, b), left, right, 128)
        lo, hi, fixed, exists = C._radial_interval_jets(s,left,right,
            (Q(2),Q(1),Q(0)),(Q(3),Q(1),Q(0)),Q(1),Q(10))
        x, y, selected, present = C._radial_interval_jets(s,left,right,
            (Q(-10),Q(-5),Q(0)),(Q(21),Q(7),Q(0)),Q(1),Q(10))
        self.assertTrue(fixed and exists and selected and present)
        self.assertTrue(C._same_radial(lo,x))
        self.assertTrue(C._same_radial(hi,y))
        self.assertTrue(C._donor_radial_pressure(lo,hi,x,y)[1])
        zero, proved = C._positive_interval_primitive(lo,x,lambda r:C._jet_power(r,3))
        self.assertTrue(proved)
        self.assertEqual(zero,C._jet_constant(Q(0)))
        # A positive2^-200 difference is not identified with the same plane,
        # even though128-bit jet bounds may coincide/overlap.
        distinct, _, _, _ = C._radial_interval_jets(s,left,right,
            (Q(2)+Q(1,2**200),Q(1),Q(0)),(Q(3),Q(1),Q(0)),Q(1),Q(10))
        self.assertFalse(C._same_radial(lo,distinct))
        other, _ = C._radial_chart_jets(a,(Q(0),Q(2),Q(0)),O._cross(a,b),left,right,128)
        different_chart, _, _, _ = C._radial_interval_jets(other,left,right,
            (Q(2),Q(1),Q(0)),(Q(3),Q(1),Q(0)),Q(1),Q(10))
        self.assertFalse(C._same_radial(lo,different_chart))

    def test_exact_constant_jet_shortcuts(self):
        from atlas_tectonics import integration_pressure_coupling as C
        zero = C._jet_constant(Q(0))
        variable = ((Q(2), Q(3)), (Q(-1), Q(4)), (Q(5), Q(9)))
        self.assertEqual(C._jet_add(zero, variable), variable)
        self.assertEqual(C._jet_add(variable, zero), variable)
        self.assertEqual(C._jet_mul(zero, variable), zero)
        self.assertEqual(C._jet_mul(variable, C._jet_constant(Q(1))), variable)
        for a in (Q(0), Q(1), Q(-1), Q(7, 11), Q(1, 2**800)):
            aa = C._jet_constant(a)
            for b in (Q(0), Q(1), Q(-1), Q(13, 17)):
                bb = C._jet_constant(b)
                self.assertEqual(C._jet_add(aa, bb), C._jet_constant(a+b))
                self.assertEqual(C._jet_mul(aa, bb), C._jet_constant(a*b))
                self.assertEqual(C._jet_scale(aa, b), C._jet_constant(a*b))
            for n in (0, 1, 3, 4):
                self.assertEqual(C._jet_power(aa, n), C._jet_constant(a**n))
            if a:
                self.assertEqual(C._jet_reciprocal(aa), C._jet_constant(1/a))

    def test_receiver_donor_pressure_has_independent_annular_integral(self):
        """Reference rho1 plus donor delta-rho1 on2<=r<=3, g1.

        On the first-quadrant receiver1<=r<=3, reference pressure3-r has
        radial moment6. The donor adds integral_1^2 r^2 dr plus
        integral_2^3 r^2(3-r)dr=61/12. Thus total is133/12; splitting the
        actual donor at45degrees may not change this field or its integral.
        Width1/1000 and4096leaves are declared before either evaluation.
        """
        from atlas_tectonics import integration_pressure_coupling as C
        from atlas_tectonics.resources import WorkBudget
        budget = WorkBudget(64 << 20)
        a, b = (Q(1), Q(0), Q(0)), (Q(0), Q(1), Q(0))
        poly = ((Q(0), Q(0)), (Q(8), Q(0)), (Q(0), Q(8)))
        halves = (((Q(0), Q(0)), (Q(8), Q(0)), (Q(4), Q(4))),
                  ((Q(0), Q(0)), (Q(4), Q(4)), (Q(0), Q(8))))
        profiles = ((Q(1), Q(3), Q(1), Q(0), Q(1)),)
        for shapes, exact in (((), Q(6)), ((poly,), Q(133, 12)), (halves, Q(133, 12))):
            donors = tuple((shape, Q(2), Q(3), Q(1)) for shape in shapes)
            value, leaves = C._integrate_radial_pressure(poly, a, b, profiles, donors, Q(1), Q(3), Q(1),
                width=Q(1, 1000), max_leaves=4096, budget=budget)
            for pair, expected in zip(value, (-exact, exact, Q(0))):
                self.assertLessEqual(pair[0], expected)
                self.assertLessEqual(expected, pair[1])
                self.assertLessEqual(pair[1]-pair[0], Q(1, 1000))
            self.assertEqual(budget.reserved_bytes, 0)
            print('RADIAL_RECEIVER_DONOR', dict(donor_pieces=len(shapes), leaves=leaves,
                max_width=float(max(hi-lo for lo, hi in value))), flush=True)

    def test_annular_sector_analytic_and_planar_kernel_parity(self):
        """Exact radial primitive; unchanged1/4 N m family bound, no fit.

        The triangle contains the complete first-quadrant annulus1<=r<=2.
        Its vector integral is (-1,1,0)*[r^4/4-r]_1^2=(-11/4,11/4,0).
        A second polygon lies strictly inside the shell and is compared with
        the original two-dimensional Hessian enclosure, at width1/100.
        """
        from atlas_tectonics import integration_pressure_coupling as C
        from atlas_tectonics import integration_volume_overlap as O
        from atlas_tectonics.resources import WorkBudget, MemoryLimitError
        budget = WorkBudget(64 << 20)
        a, b = (Q(1), Q(0), Q(0)), (Q(0), Q(1), Q(0))
        poly = ((Q(0), Q(0)), (Q(4), Q(0)), (Q(0), Q(4)))
        bounded, leaves = C._integrate_radial_shell(poly, a, b, Q(1), Q(2), Q(1),
            width=Q(1, 1000), max_leaves=4096, budget=budget)
        for pair, exact in zip(bounded, (Q(-11, 4), Q(11, 4), Q(0))):
            self.assertLessEqual(pair[0], exact)
            self.assertLessEqual(exact, pair[1])
            self.assertLessEqual(pair[1]-pair[0], Q(1, 1000))
        self.assertEqual(bounded[2], (Q(0), Q(0)))
        rectangle = ((Q(2), Q(1)), (Q(3), Q(1)), (Q(3), Q(2)), (Q(2), Q(2)))
        normal = O._cross(a, b)
        oracle, _ = C._integrate(rectangle, a, b,
            lambda points, radial, moment: C._radial_linear_mean(points, radial, normal, rc=Q(1)),
            width=Q(1, 100), max_leaves=4096, budget=budget)
        value, _ = C._integrate_radial_shell(rectangle, a, b, Q(1), Q(4), Q(1),
            width=Q(1, 100), max_leaves=4096, budget=budget)
        for x, y in zip(oracle, value):
            self.assertLessEqual(max(x[0], y[0]), min(x[1], y[1]))
        self.assertEqual(budget.reserved_bytes, 0)
        with self.assertRaises(MemoryLimitError):
            C._integrate_radial_shell(poly, a, b, Q(1), Q(2), Q(1),
                width=Q(1, 1000), max_leaves=4096, budget=WorkBudget(1024))
        print('RADIAL_FIRST_SECTOR', dict(leaves=leaves,
            max_width=float(max(hi-lo for lo, hi in bounded)),
            peak_accounted_bytes=budget.peak_reserved_bytes), flush=True)


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
                    from i04_differential_predictor import interval_predictor
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


class DifferentialForce(unittest.TestCase):
    def test_current_component_partition_binds_the_accepted_end(self):
        """Pure binding oracle, not manufactured issued geometry authority."""
        from atlas_tectonics._validation import TectonicsError
        part = dict(scope='physical-interval', interval_id='interval', network_id='old',
            endpoint_network_id='current', start_time_s=['0', '1'], end_time_s=['1', '1'],
            end_support_id='end-support', trajectory_id='trajectory', trajectory={'segments': ['accepted']})
        current = dict(accepted_interval_id='interval', accepted_support_id='end-support',
            accepted_trajectory_id='trajectory', trajectory=part['trajectory'], time_s=['1', '1'])
        self.assertEqual(T._partition_endpoint(part, current, static=True, endpoint='current', network_id='current'), 'end')
        for key in ('accepted_interval_id', 'accepted_support_id', 'accepted_trajectory_id', 'trajectory', 'time_s'):
            with self.subTest(key=key), self.assertRaises(TectonicsError):
                T._partition_endpoint(part, dict(current, **{key: 'stale'}),
                                      static=True, endpoint='current', network_id='current')
        initial = dict(scope='initial-current', network_id='initial', current_geometry_id='initial-geometry',
                       start_time_s=['0', '1'], end_time_s=['0', '1'])
        pose = dict(geometry_id='initial-geometry', start_time_s=['0', '1'], end_time_s=['0', '1'])
        self.assertEqual(T._partition_endpoint(initial, pose, static=True, endpoint='current', network_id='initial'), 'start')
        interval = dict(interval_id='interval', parent_network_id='old', start_time_s=['0', '1'], end_time_s=['1', '1'])
        self.assertIsNone(T._partition_endpoint(part, interval, static=False, endpoint=None, network_id='old'))

    def test_iteration_rotation_keeps_actual_rates_and_typed_authority(self):
        """Algebra only: no projection of noncoaxial rates or fake issuance."""
        import i03_fixtures as F3
        from atlas_tectonics import integration_differential_coupling as C
        from atlas_tectonics._validation import TectonicsError
        network = F3.three_plates(sphere=F3.sphere(radius=10.))
        rates = np.asarray(((0., 0., 0.), (0., 0., -.125), (.25, -.5, .75)))
        motion = C._motion_from_rates(network, network.step+1, Q(1, 8), rates, (), ())
        rotations = dict(motion.rotations)
        np.testing.assert_array_equal(rotations[network.plate_ids[0]].matrix, np.eye(3))
        for plate, rate in zip(network.plate_ids[1:], rates[1:]):
            length = np.linalg.norm(rate); x, y, z = rate/length
            cross = np.asarray(((0., -z, y), (z, 0., -x), (-y, x, 0.)))
            angle = length/8
            expected = np.eye(3)+np.sin(angle)*cross+(1-np.cos(angle))*(cross@cross)
            np.testing.assert_allclose(rotations[plate].matrix, expected, atol=R.ALGEBRA, rtol=R.ALGEBRA)
        np.testing.assert_array_equal(rates, ((0., 0., 0.), (0., 0., -.125), (.25, -.5, .75)))
        with self.assertRaises(TectonicsError):
            C._motion_from_rates(network, network.step+1, 1., np.full((3, 3), np.nan), (), ())
        with self.assertRaises(TectonicsError):
            C._motion_from_rates(network, network.step+1, 1e308, np.full((3, 3), 2.), (), ())
        for issued in (C.DifferentialForceProposal, C.DifferentialIntervalSolution):
            with self.assertRaises(TypeError):
                issued()

    def test_affine_reservoir_chart_pressure_and_actual_external_work(self):
        """Exact affine pullback, physical pressure and nonzero pressure work.

        With uniform translation u=e_z and f=grad(p), D=0 and sigma=-pI.
        Full basal traction is -p*n; pressure is affine/Q1-exact. Constant and
        nonzero-gradient cases use no reference and a2Pa Q1 decomposition;
        physical p/u/work must agree at the existing1e-11 algebra bound.
        """
        from i04_differential_fixture import radial_differential_fixture
        with radial_differential_fixture() as case:
            native, budget, collar = case['native'], case['budget'], case['collar']
            chart = V.CartesianCell.from_record(case['funding'].descriptor()['cell_geometries'][0], budget=budget)
            anchor = (Q(1, 3), Q(-2, 5), Q(3, 7))
            previous = {}
            for gradient in ((Q(0),)*3, (Q(1, 10), Q(1, 7), Q(1, 11))):
                # Independent affine change of variables, before sample values.
                local_gradient = tuple(sum(gradient[i]*chart.basis[i][j] for i in range(3)) for j in range(3))
                constant = Q(5)+sum(gradient[i]*(chart.origin_m[i]-anchor[i]) for i in range(3))
                evaluate = lambda point: constant+sum(g*Q(float(x)) for g, x in zip(local_gradient, point))
                for reference in (None, 2.):
                    reference_args = {} if reference is None else dict(pressure_reference_pa=np.full(27, reference),
                        pressure_reference_source='synthetic decomposition only; full physical loads unchanged',
                        pressure_load_partition='full')
                    with PreparedRegionalStokes3D(native.cells, native.lengths_m, native._cs.viscosity_pa_s,
                            native._pattern, scales=native._ms, reference_viscosity_pa_s=native._cs.viscosity_pa_s,
                            frame_id=native._frame, vertical_datum=native._datum, material_source=native.plan_id,
                            method='direct', physical_mean_pressure_pa=None, budget=budget, **reference_args) as plan:
                        pressure = P.prescribe_reservoir_pressure(case['funding'], collar, plan,
                            pressure_at_origin_pa=Q(5), gradient_pa_m=gradient, origin_world_m=anchor,
                            source='synthetic affine reservoir load on the actual complete funded cut', budget=budget)
                        record = pressure.descriptor()
                        self.assertEqual(record['native_plan_id'], plan.plan_id)
                        exact = tuple(evaluate(point) for point in plan.coordinates('z0').reshape(-1, 3))
                        self.assertEqual(tuple(map(W._decode, record['exact_native_pressure_pa'])), exact)
                        residual = tuple(Q(float(q))-q for q in exact)
                        self.assertEqual(tuple(map(W._decode, record['native_pressure_projection_residual_pa'])), residual)
                        traction = pressure.array('reservoir_native_traction_pa')
                        np.testing.assert_array_equal(traction[..., :2], 0.)
                        np.testing.assert_array_equal(traction[..., 2].ravel(), [float(q) for q in exact])
                        if any(gradient):
                            self.assertTrue(any(residual))
                        else:
                            self.assertTrue(all(q == 0 for q in residual))
                        body = np.broadcast_to(np.asarray(list(map(float, local_gradient))),
                                               plan.coordinates('quadrature').shape)
                        velocity = np.zeros_like(plan.coordinates('velocity')); velocity[:, 2] = 1.
                        loads = {s: np.zeros_like(plan.coordinates(s)) for s in SIDES}; loads['z0'] = traction
                        result = plan.solve(body, velocity, loads,
                            parent_state_id=case['state'].native_state.result_id, epoch_id=case['source'][0].network.epoch_id,
                            time_s=0., force_source='exact affine-pressure gradient in the funded chart',
                            boundary_source=pressure.closure_id)
                        u = result.array('velocity_m_s')
                        np.testing.assert_allclose(u, velocity, rtol=R.ALGEBRA, atol=R.ALGEBRA)
                        expected = np.asarray([float(evaluate(point)) for point in plan.coordinates('pressure')])
                        np.testing.assert_allclose(result.array('physical_pressure_pa'), expected, rtol=R.ALGEBRA, atol=0.)
                        account = R._reservoir_pressure_work(plan, u, record, budget)
                        full = W._decode(account['full_native_reservoir_pressure_work_w'])
                        declared = W._decode(account['declared_pressure_work_on_represented_quadrature_w'])
                        difference = W._decode(account['pressure_projection_work_residual_w'])
                        allowance = W._decode(account['pressure_projection_work_abs_bound_w'])
                        self.assertEqual(full, declared+difference)
                        self.assertLessEqual(abs(difference), allowance)
                        self.assertGreater(full, 0)
                        if any(gradient):
                            self.assertGreater(allowance, 0)
                        else:
                            self.assertEqual((difference, allowance), (Q(0), Q(0)))
                        powers = result.descriptor()['power_w']
                        actual_native_work = powers['prescribed_traction_work']
                        if reference is not None:
                            actual_native_work += float(np.sum(u*result.array('reference_natural_boundary_force_n')))
                        self.assertLessEqual(abs(actual_native_work-float(full)), R.ALGEBRA*abs(float(full)))
                        self.assertLessEqual(result.descriptor()['work_relative_residual'], R.WORK)
                        self.assertLessEqual(powers['viscous_dissipation'], R.ALGEBRA**2*abs(float(full)))
                        if reference is None:
                            previous[gradient] = result, float(full)
                        else:
                            old, old_work = previous[gradient]
                            np.testing.assert_allclose(u, old.array('velocity_m_s'), rtol=R.ALGEBRA, atol=R.ALGEBRA)
                            np.testing.assert_allclose(result.array('physical_pressure_pa'), old.array('physical_pressure_pa'),
                                                       rtol=R.ALGEBRA, atol=0.)
                            self.assertLessEqual(abs(float(full)-old_work), R.ALGEBRA*abs(old_work))

    def test_actual_complete_component_projection_keeps_common_rigid_field(self):
        """Real contact rows; no curved volume, heat or force solve is repeated.

        The independent equal-rate field is globally affine and Q2-exact.
        Retain the preceding trace control's500*ALGEBRA^2 squared-error bound.
        """
        from i04_differential_fixture import radial_differential_fixture
        from i04_differential_spatial_fixture import initial_partition
        with radial_differential_fixture() as case:
            current, partition = initial_partition(case, max_components=4096)
            native, budget, sphere = case['native'], case['budget'], case['source'][0]
            boundary = next(b for b in sphere.network.boundaries
                            if {b.left_plate_id, b.right_plate_id} == {'A', 'B'})
            with PreparedRegionalStokes3D(native.cells, native.lengths_m, native._cs.viscosity_pa_s,
                    native._pattern, scales=native._ms, reference_viscosity_pa_s=native._cs.viscosity_pa_s,
                    frame_id=native._frame, vertical_datum=native._datum, material_source=native.plan_id,
                    method='direct', physical_mean_pressure_pa=None, budget=budget,
                    **native._pressure_reference_args) as prototype, \
                 T.PreparedDifferentialTrace(prototype, case['volume_map'], current,
                    V.RadialLayer(10, 0, 3, budget=budget), network=sphere.network,
                    plate_ids=(boundary.left_plate_id, boundary.right_plate_id), endpoint='current',
                    open_side='z0', max_moment_width=Q(1, 10**24), max_volume_width=0, max_leaves=64,
                    component_partition=partition, budget=budget) as trace:
                report = trace.error_and_work(np.asarray(((0., 0., 1.), (0., 0., 1.))),
                    np.zeros_like(prototype.coordinates('velocity')),
                    max_l2_error_squared=Q(500)*Q(R.ALGEBRA)**2, max_work_error=0)
                part = trace.descriptor()['component_partition']
                self.assertEqual(part['partition_id'], partition.partition_id)
                self.assertGreater(part['actual_constraint_count'], 20)
                self.assertEqual(len(report['boundary_cell_normal_integrals']), part['actual_constraint_count'])
                self.assertGreater(len(part['independent_constraint_rows']), 0)
                self.assertLessEqual(W._decode(report['l2_error_squared_bounds'][1]), Q(500)*Q(R.ALGEBRA)**2)
