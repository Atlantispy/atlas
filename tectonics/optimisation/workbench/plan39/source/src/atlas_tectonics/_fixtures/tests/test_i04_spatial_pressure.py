"""Predeclared moving physical-wall controls, not a heat-mesh accuracy claim.

The existing analytic two-layer wall uses width1/4 N m and at most4096 leaves.
An exactly rational 90-degree pose must rotate both physical integrals. Exact
EOS and Q2 closed-volume constraints have no fitted comparison allowance.
The optional real-endpoint helper consumes a preceding actual joined solve;
it must not regenerate geometry or pretend alpha-zero fields imply feedback.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from types import SimpleNamespace
import unittest

import numpy as np

from atlas_tectonics import integration_spatial_pressure as S
from atlas_tectonics import integration_pressure_coupling as C
from atlas_tectonics import integration_current_force_pose as F
from atlas_tectonics import integration_regional_driving as R
from atlas_tectonics import integration_volume as V
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.constitutive import BoussinesqMaterial
from test_i04_owned_pressure import box, profiles


class SpatialPressureKernel(unittest.TestCase):
    def test_differential_world_halfspace_matches_actual_clipped_box(self):
        """The same 1/4 N m control, independent exact Cartesian clipping.

        A posed CSG plane cuts the density support, not the mechanical box.
        Compare both the force and hydrostatic-ray integral with the actual
        smaller density voxel. The optional uncertainty must keep that answer.
        """
        budget = WorkBudget(256 << 20)
        cell = box(budget)
        clipped = box(budget, high=(Q(5, 2), 2, 1))
        identity = tuple(tuple(Q(int(i == j)) for j in range(3)) for i in range(3))
        pose = SimpleNamespace(rotation=lambda: identity, _error=Q(0))
        args = dict(gravity=1, support_radius=1, radius=4, width=Q(1, 4), max_leaves=4096, budget=budget)
        region = dict(cell=clipped, density=Q(11, 10), cone=(), radial=(Q(1), Q(4)), side=None)
        reference = S.moving_wall_integrals((1, 0, 0), (0, 1, 0), profiles(), (region,), cell, pose, **args)
        for error in (Q(0), Q(1, 10**24)):
            actual = dict(region, cell=cell, world_planes=((1, 0, 0, Q(5, 2), error),))
            measured = S.moving_wall_integrals((1, 0, 0), (0, 1, 0), profiles(), (actual,), cell, pose, **args)
            for expected, enclosed in zip(reference[:2], measured[:2]):
                for a, b in zip(expected, enclosed):
                    self.assertLessEqual(max(a[0], b[0]), min(a[1], b[1]))
        with self.assertRaises(C.PressureCouplingRefused):
            S.moving_wall_integrals((1, 0, 0), (0, 1, 0), profiles(),
                (dict(region, world_planes=((1, 0, 0, 0, -1),)),), cell, pose, **args)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_actual_wall_rotates_with_exact_pose_and_retains_enclosures(self):
        budget = WorkBudget(256 << 20)
        cell = box(budget)
        rotation = V.CartesianCell((0, 0, 0), (1, 1, 1), budget=budget).rotated((1, 0, 0, 1), budget=budget).basis
        identity = tuple(tuple(Q(int(i == j)) for j in range(3)) for i in range(3))
        args = dict(gravity=1, support_radius=1, radius=4, width=Q(1, 4), max_leaves=4096, budget=budget)
        outputs = []
        for matrix, current in ((identity, cell), (rotation, cell.rotated((1, 0, 0, 1), budget=budget))):
            pose = SimpleNamespace(rotation=lambda: matrix, _error=Q(0))
            region = dict(cell=current, density=Q(11, 10), cone=(), radial=(Q(1), Q(4)), side=None)
            outputs.append(S.moving_wall_integrals((1, 0, 0), (0, 1, 0), profiles(), (region,), current, pose, **args))
        for original, rotated in zip(outputs[0][:2], outputs[1][:2]):
            self.assertEqual(rotated, ((-original[1][1], -original[1][0]), original[0], original[2]))
        old = C.wall_integrals((1, 0, 0), (0, 1, 0), profiles(), (cell,), (Q(11, 10),), cell,
            **{k: v for k, v in args.items() if k != 'radius'})
        for first, second in zip(old[:2], outputs[0][:2]):
            for a, b in zip(first, second):
                self.assertLessEqual(max(a[0], b[0]), min(a[1], b[1]))
        # Nonzero proved pose error must enclose the same physical wall without
        # classifying all boundary-touching triangles as unknown material.
        near = SimpleNamespace(rotation=lambda: identity, _error=Q(1, 10**24))
        region0 = dict(cell=cell, density=Q(11, 10), cone=(), radial=(Q(1), Q(4)), side=None)
        uncertain = S.moving_wall_integrals((1, 0, 0), (0, 1, 0), profiles(), (region0,), cell, near, **args)
        for certain, enclosed in zip(outputs[0][:2], uncertain[:2]):
            for a, b in zip(certain, enclosed):
                self.assertLessEqual(max(a[0], b[0]), min(a[1], b[1]))
        with self.assertRaises(MemoryLimitError):
            S.moving_wall_integrals((1, 0, 0), (0, 1, 0), profiles(), (region,), current, pose,
                **dict(args, budget=WorkBudget(1024)))
        self.assertEqual(budget.reserved_bytes, 0)

    def test_current_exact_caloric_field_and_closed_volume_constraint(self):
        budget = WorkBudget(8 << 20)
        material = BoussinesqMaterial('synthetic', 'literal EOS control', 1.1, 2., .1, .001,
            500., 0., 0., (400., 600.))
        masses = (Q(1, 3), Q(2, 3))
        cold = S._density(material, Q(1000), masses, budget)
        hot = S._density(material, Q(1002), masses, budget)
        self.assertEqual(cold, (Q(1.1), Q(500)))
        self.assertEqual(hot, (Q(1.1)*(1-Q(.001)), Q(501)))
        self.assertLess(hot[0], cold[0])
        points = np.indices((5, 5, 5)).reshape(3, -1).T/4
        full = np.zeros((6, len(points), 3))
        full[0, :, 0] = points[:, 0]; full[1, :, 1] = points[:, 1]
        basis, record = R._closed_volume_basis(full, (2, 2, 2), (1., 1., 1.))
        decode = lambda v: Q(int(v[0], 16), int(v[1], 16))
        flux = list(map(decode, record['exact_flux']))
        self.assertEqual(flux, [1, 1, 0, 0, 0, 0])
        self.assertEqual(basis.shape, (6, 5))
        for column in zip(*record['exact_basis']):
            self.assertEqual(sum(f*decode(q) for f, q in zip(flux, column)), 0)
        self.assertEqual(budget.reserved_bytes, 0)


class DatumForceReconstruction(unittest.TestCase):
    def test_near_null_force_datum_shift_and_corruption(self):
        """Same r6 physical box; no spatial-history regeneration for algebra.

        Before the repair the mean5 case had3.14e-15 J regrouping error on
        2.75..87.14 J operands, misjudged against a2.41e-6 J result. Require
        unchanged original force/work gates after explicit arithmetic, zero
        datum compatibility, same actual rates under a10^6 Pa datum, and
        rejection of force corruption exceeding the proved arithmetic bound.
        """
        from threadpoolctl import threadpool_limits
        import i04_fixtures as X
        import test_i04_regional_owner as O
        from atlas_tectonics import integration_bridges as B, integration_driving as D
        from atlas_tectonics._validation import TectonicsError
        from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot, RegionalMechanicsScales
        from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES
        budget = WorkBudget(256 << 20)
        source = O.physical_source(budget)
        sphere, _, footprint = source[:3]
        pattern = {s: ('velocity',)*3 for s in SIDES}
        forcing = X.authored_forcing(sphere.network, {p: (0., 0., 0.) for p in sphere.network.plate_ids}, drag=.001)
        prepared = D.prepare(sphere.network, forcing)
        exterior = D.balance(sphere.network, forcing, prepared=prepared,
                             parent_state_id=sphere.state_id, interval=(0, 1, 0., 1.))
        outputs = []
        with threadpool_limits(1):
            for mean in (0., 5., 1e6):
                with PreparedRegionalStokes3D((2, 2, 2), (1., 1., 1.), 1., pattern,
                        scales=RegionalMechanicsScales(1., 1.), reference_viscosity_pa_s=1.,
                        frame_id=footprint.region_id, vertical_datum='test:physical box',
                        physical_mean_pressure_pa=mean, material_source='test:datum-source',
                        method='direct', budget=budget) as native:
                    frame, _, rings, _, _ = B._charted(sphere.network, footprint)
                    origin = (-.5, 1., -2.)
                    points = frame.positions_to_cartesian(native.coordinates('velocity')+origin, budget=budget)
                    cells = {name: R.U.cells_of_rings(ring) for name, ring in rings.items()}
                    owners = tuple(next(f for f in footprint.face_ids if R._contains(cells[f], p))
                        if np.any(mask) else None for p, mask in zip(points, native.velocity_mask()))
                    boundary = next(b.boundary_id for b in sphere.network.boundaries
                        if {b.left_plate_id, b.right_plate_id} == {'A', 'B'})
                    with R.PlateBoundaryLift(sphere.network, native, footprint, boundary,
                            origin_local_m=origin, node_face_ids=owners,
                            angular_rate_basis='closed-native-volume', map_source='r6 same physical box',
                            constraint_source='same closed Q2 flux constraint', budget=budget) as lift, \
                         R.PreparedRegionalDriving(sphere.network, forcing, exterior, prepared, lift, budget=budget) as driver:
                        xyz = frame.positions_to_cartesian(native.coordinates('quadrature')+origin, budget=budget)
                        body = (-1.1*xyz/np.linalg.norm(xyz, axis=-1)[..., None])@frame.basis
                        result = driver.solve(native, parent_state_id='test:current', time_s=0.,
                            epoch_id=sphere.network.epoch_id, force_source='same radial body',
                            boundary_source='same physical modes', body_force_n_m3=body)
                        outputs.append(result.mechanical.array('velocity_m_s'))
                        report = result.exchange.descriptor()
                        self.assertLessEqual(report['algebra_relative_residual'], R.ALGEBRA)
                        self.assertLessEqual(report['virtual_work_relative_residual'], R.WORK)
                        if mean == 0.:
                            self.assertNotIn('pressure_datum_account', report)
                        else:
                            account = report['pressure_datum_account']
                            self.assertLessEqual(account['force_contraction_absolute_residual_j'],
                                                 account['force_contraction_roundoff_bound_j'])
                            self.assertGreater(np.max(np.abs(result.exchange.array('pressure_datum_constraint_torque_n_m'))), 0.)
                            arrays = {k: result.mechanical.array(k).copy() for k in result.mechanical.array_names}
                            force = arrays['generalized_regional_force_j']
                            corruption = max(16*account['force_contraction_roundoff_bound_j'],
                                             16*R.ALGEBRA*float(np.max(np.abs(force))))
                            force[0] += corruption
                            changed = RegionalMechanicalSnapshot(result.mechanical.descriptor(), arrays)
                            with self.assertRaisesRegex(TectonicsError, 'virtual work'):
                                driver.reconstruct(changed, parent_state_id='test:current', time_s=0.)
        np.testing.assert_array_equal(outputs[0], outputs[1])
        np.testing.assert_array_equal(outputs[0], outputs[2])


def check_spatial_endpoint(case, first, wall):
    """One additional force solve from an already accepted spatial endpoint."""
    from atlas_tectonics import integration_ports as P, integration_radial_pressure as H
    from atlas_tectonics import integration_driving as D, integration_bridges as B
    from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D
    from atlas_tectonics.regional_execution import RegionalMechanicsScales
    source, funding, collar, budget = (case[k] for k in ('source', 'funding', 'collar', 'budget'))
    sphere, moving, footprint = source[:3]
    state, spatial = first.state, first.exterior.state
    support = P.material_trace_support(sphere)
    datum = H.RadialDatum(10., 1., 1., 7., 1.1, .1,
        'synthetic .1 Pa load on common physical sphere; fixed basal radial constraint')
    header = P.Header('P1', sphere.state_id, (0, 1, 0., 1/64), 0., sphere.network.network_id,
        support.support_id, datum.datum_id, moving.moving_id, sphere.network.sphere.frame_id,
        'test:current-spatial-pressure', 'actual bound original profile for subtraction only')
    port = H.radial_pressure_trace(moving, sphere, support, header, datum, budget=budget)
    pose = F.current_force_pose(sphere, funding, wall, max_operator_error=Q(1, 10**24), budget=budget)
    correction = S.spatial_pressure_correction(sphere, moving, support, port, funding, collar, state,
        spatial, pose, max_torque_width_n_m=Q(1, 2), max_leaves=4096, budget=budget)
    assert correction.descriptor()['spatial_state_id'] == spatial.state_id
    assert correction.descriptor()['native_state_id'] == state.native_state.result_id
    # This source is alpha=0. Its pressure density is independent of heat,
    # though the actual current heat fields remain identity-bound and consumed.
    np.testing.assert_array_equal(correction.array('spatial_cell_density_kg_m3'), 1.1)
    forcing = D.Forcing({p: .001 for p in sphere.network.plate_ids},
        'current owned pressure and explicit basal drag',
        omitted=('gpe', 'slab_pull', 'mantle_traction', 'authored_torque', 'interface'),
        frame_id=sphere.network.sphere.frame_id, basal_drag_radius_m=7.,
        radial_pressure_rule='central-half-radial-pressure-trace-v1')
    prepared = D.prepare(sphere.network, forcing)
    exterior = D.balance(sphere.network, forcing, support=support, datum=datum, prepared=prepared,
        radial_pressure_port=port, interface_pressure_rule='central-half-radial-pressure-trace-v1')
    background = F.rotated_background(pose, sphere.network, exterior, prepared,
        max_torque_error_n_m=Q(1, 1000), max_power_error_w=Q(1, 1000), angular_rate_l2_bound_s_inv=Q(100), budget=budget)
    pattern = collar._native._pattern
    # A declared absolute mean supplies the steady force-only pressure datum;
    # this does not alter or advance the already accepted native state.
    with PreparedRegionalStokes3D((2, 2, 2), (1., 1., 1.), 1., pattern,
            scales=RegionalMechanicsScales(1., 1.), reference_viscosity_pa_s=1.,
            frame_id=footprint.region_id, vertical_datum=collar._native._datum,
            physical_mean_pressure_pa=5., material_source=collar._native.plan_id,
            method='direct', budget=budget) as operator:
        frame, _, rings, _, _ = B._charted(sphere.network, footprint)
        points = frame.positions_to_cartesian(operator.coordinates('velocity')+source[-1], budget=budget)
        cells = {name: R.U.cells_of_rings(ring) for name, ring in rings.items()}
        owners = tuple(next(f for f in footprint.face_ids if pose.contains(cells[f], p))
            if np.any(mask) else None for p, mask in zip(points, operator.velocity_mask()))
        boundary = next(b.boundary_id for b in sphere.network.boundaries
            if {b.left_plate_id, b.right_plate_id} == {'A', 'B'})
        with R.PlateBoundaryLift(sphere.network, operator, footprint, boundary, origin_local_m=source[-1],
                node_face_ids=owners, angular_rate_basis='closed-native-volume', map_source='actual current physical pose',
                constraint_source='exact integral of current Q2 wall-normal velocity is zero',
                volume_map=collar._map, current_pose=pose, budget=budget) as lift, \
             R.PreparedRegionalDriving(sphere.network, forcing, exterior, prepared, lift,
                pressure_correction=correction, pressure_native=operator, current_background=background, budget=budget) as driver:
            xyz = collar._origin+operator.coordinates('quadrature')@collar._basis.T
            body = (-1.1*xyz/np.linalg.norm(xyz, axis=-1)[..., None])@collar._basis
            result = driver.solve(operator, parent_state_id=state.native_state.result_id, time_s=spatial.time_s,
                epoch_id=sphere.network.epoch_id, force_source='actual current alpha-zero radial density and gravity',
                boundary_source='actual current positioned plate modes', body_force_n_m3=body)
            assert result.exchange.descriptor()['algebra_relative_residual'] <= R.ALGEBRA
            assert driver.reconstruct(result.mechanical, parent_state_id=state.native_state.result_id,
                time_s=spatial.time_s).exchange.result_id == result.exchange.result_id
            assert driver.descriptor()['current_background']['pose']['pose_id'] == pose.pose_id
    return correction.correction_id, result.exchange.result_id


if __name__ == '__main__':
    unittest.main()
