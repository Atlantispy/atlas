"""Physical plate/box lift and one actual global/regional linear solve.

Acceptance predeclared in I04_REGIONAL_DRIVING.md; no global evolution claim.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
import json
import unittest

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from threadpoolctl import threadpool_limits

import i03_fixtures as F
import i04_fixtures as X
from atlas_tectonics import integration_bridges as B, integration_driving as D
from atlas_tectonics import integration_regional_driving as R
from atlas_tectonics import integration_material as M, integration_sphere as S
from atlas_tectonics import integration_regional_evolution as O, integration_volume as V
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.regional_execution import RegionalMechanicsScales, RegionalMechanicalSnapshot
from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


def prepare(network, budget, eta=1.):
    pattern = {s: ('velocity',)*3 if s[0] == 'x' else ('traction',)*3 for s in SIDES}
    return PreparedRegionalStokes3D((2, 2, 2), (1., 1., 1.), eta, pattern,
        scales=RegionalMechanicsScales(1., 1.), reference_viscosity_pa_s=1.,
        frame_id='test:coupled-box', vertical_datum='explicit embedded box',
        material_source='test:fixed-or-thermal-source', method='direct', budget=budget)


def mapping(network, native):
    faces = tuple('s%02d-b%02d' % (s, b) for s in (0, 5) for b in (1, 2))
    footprint = B.Footprint('test:coupled-box', faces, 0., 0., 0., 0., 3., '3d')
    frame, _, rings, _, _ = B._charted(network, footprint)
    origin = (-.5, -.5, -2.)
    points = frame.positions_to_cartesian(native.coordinates('velocity')+origin)
    # This fixture assigns the actual containing source face; the API repeats
    # the exact point test and never infers an owner from a mean column.
    cells = {face: R.U.cells_of_rings(ring) for face, ring in rings.items()}
    mask = native.velocity_mask()
    owners = tuple(next(f for f in faces if R._contains(cells[f], p)) if np.any(m) else None
                   for p, m in zip(points, mask))
    # x=0/1 walls straddle meridian 0 (B|C). Common local-y rotation and each
    # plate's independent local-x/local-z rotations have zero net wall flux.
    # Independent local-y normal motion would violate volume compatibility.
    N = np.zeros((6, 5))
    N[:3, 0] = N[3:, 0] = frame.basis[:, 1]
    N[:3, 1], N[:3, 2] = frame.basis[:, 0], frame.basis[:, 2]
    N[3:, 3], N[3:, 4] = frame.basis[:, 0], frame.basis[:, 2]
    return footprint, dict(origin_local_m=origin, node_face_ids=owners, angular_rate_basis=N,
        map_source='test:exact affine embedded box, not a spherical material transfer',
        constraint_source='test:equal normal-driving rotation on B and C'), frame


class RegionalDrivingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = threadpool_limits(limits=1)
        cls.threads.__enter__()
        cls.budget = WorkBudget(256*1024*1024)
        cls.network = F.three_plates(sphere=F.sphere(radius=10.), time_s=0.)
        cls.native = prepare(cls.network, cls.budget)
        cls.footprint, cls.map_args, cls.frame = mapping(cls.network, cls.native)
        cls.lift = R.PlateBoundaryLift(cls.network, cls.native, cls.footprint, 'boundary-m00',
                                      **cls.map_args, budget=cls.budget)
        # C|A coupling is outside the replaced B|C boundary, making Schur
        # elimination nontrivial. No regional material/basal heat is added.
        cls.forcing = X.authored_forcing(cls.network,
            {'A': (1., -.4, .2), 'B': (.8, 1.1, .5), 'C': (-.3, -.6, -.2)}, drag=.001,
            interface={'boundary-m02': .03})
        cls.prepared = D.prepare(cls.network, cls.forcing)
        cls.exterior = D.balance(cls.network, cls.forcing, prepared=cls.prepared,
                                parent_state_id='0'*64, interval=(0, 1, 0., 1.))
        cls.driver = R.PreparedRegionalDriving(cls.network, cls.forcing, cls.exterior,
                                               cls.prepared, cls.lift, budget=cls.budget)
        cls.result = cls.driver.solve(cls.native, parent_state_id='test:native-parent', time_s=0.,
            epoch_id=cls.network.epoch_id, force_source='test:zero-body-force', boundary_source='test:physical-walls')

    @classmethod
    def tearDownClass(cls):
        cls.driver.close()
        cls.lift.close()
        cls.native.close()
        cls.threads.__exit__(None, None, None)

    def test_actual_volume_map_and_lift_share_geometry_and_parent(self):
        # Fresh authored spherical source. These dimensioned synthetic values
        # test a shared embedding, not a planetary thermal or density default.
        volume = float(V.RadialLayer(self.network.sphere.radius_m, 0., 3.,
                                    budget=self.budget).volume_per_area_m)
        material = F.material(self.network, phases=('crust',), basis=None,
                              mass_per_area_kg_m2={'crust': volume}, thickness_m={'crust': volume})
        sphere = S.initial_sphere(self.network, material)
        layer = M.Sublayer('test:embedded-rock', 'crust', 3., 1., 0., 1., 1., 0., 2., 2.)
        records = tuple(M.CohortRecord(c.cohort_id, 'test:physical-profile', 'test:thermal',
            (layer,), 2., 2., None, (0.,), M.BondRecord(c.cohort_id, False, 'UNKNOWN'),
            volume_convention=V.PHYSICAL_RADIAL_SHELL, reference_radius_m=self.network.sphere.radius_m)
            for c in material.cohorts)
        moving = M.declare_moving(sphere, records, enthalpy_reference_k=1., budget=self.budget)
        centres = np.stack(np.meshgrid((.25, .75), (.25, .75), (.25, .75), indexing='ij'), axis=-1).reshape(-1, 3)
        points = self.frame.positions_to_cartesian(centres+self.map_args['origin_local_m'], budget=self.budget)
        patches = sphere.material.support.patches
        sources = tuple((next(p.patch_id for p in patches if p.face_id in self.footprint.face_ids
                              and R._contains(p.cells, point)), 0) for point in points)
        volume_map = O.RegionalVolumeMap(sphere, moving, self.footprint, cells=(2, 2, 2),
            lengths_m=(1., 1., 1.), origin_local_m=self.map_args['origin_local_m'],
            cell_sources=sources, map_source='test:physical-lift-volume', budget=self.budget)
        with R.PlateBoundaryLift(self.network, self.native, self.footprint, 'boundary-m00',
                **self.map_args, budget=self.budget, volume_map=volume_map) as lift:
            binding = lift.descriptor()['physical_volume_binding']
            self.assertEqual(binding['volume_map_id'], volume_map.volume_map_id)
            self.assertEqual(binding['physical_points_sha256'], self.lift.descriptor()['physical_points_sha256'])
            exterior = D.balance(self.network, self.forcing, prepared=self.prepared,
                                 parent_state_id=sphere.state_id, interval=(0, 1, 0., 1.))
            with R.PreparedRegionalDriving(self.network, self.forcing, exterior, self.prepared,
                                          lift, budget=self.budget) as driver:
                self.assertEqual(driver._lift.descriptor()['physical_volume_binding'], binding)
            with self.assertRaisesRegex(TectonicsError, 'different parent states'):
                R.PreparedRegionalDriving(self.network, self.forcing, self.exterior, self.prepared,
                                          lift, budget=self.budget)
        args = dict(self.map_args, origin_local_m=(0., -.5, -2.))
        with self.assertRaisesRegex(TectonicsError, 'different source geometry'):
            R.PlateBoundaryLift(self.network, self.native, self.footprint, 'boundary-m00',
                                **args, budget=self.budget, volume_map=volume_map)

    def test_physical_point_depth_velocity_and_independent_virtual_work(self):
        result, lift = self.result, self.lift
        omega = result.exchange.array('omega_rad_s')
        actual = result.mechanical.array('velocity_m_s')
        mask = self.native.velocity_mask()
        owners = self.map_args['node_face_ids']
        expected = np.zeros_like(actual)
        for i, face in enumerate(owners):
            if face is not None:
                rate = omega[self.network.plate_ids.index(self.network.face_plate(face))]
                expected[i] = np.cross(rate, lift._points[i])@self.frame.basis
        assert_allclose(actual[mask], expected[mask], rtol=R.ALGEBRA, atol=R.ALGEBRA*np.max(np.abs(expected)))
        # Actual node radius varies through the depth; replacing r by R*r/|r|
        # changes the boundary velocity and is not an allowed shortcut.
        top, bottom = np.max(np.linalg.norm(lift._points, axis=1)), np.min(np.linalg.norm(lift._points, axis=1))
        self.assertGreater(top-bottom, .9)
        q = np.array([.1, -.2, .3, -.4, .5])
        force = np.arange(actual.size, dtype=float).reshape(actual.shape)/actual.size
        velocity = np.einsum('k,kij->ij', q, lift._modes)
        local_force = np.einsum('aij,ij->a', lift._full, force)
        self.assertLessEqual(R._relative(np.sum(force*velocity)-(lift._basis@q)@local_force,
                                        np.sum(np.abs(force*velocity))), R.ALGEBRA)
        meta = result.exchange.descriptor()
        self.assertLessEqual(meta['algebra_relative_residual'], R.ALGEBRA)
        self.assertLessEqual(meta['virtual_work_relative_residual'], R.WORK)
        self.assertLessEqual(abs(meta['constraint_work_w']), R.ALGEBRA*abs(meta['external_driving_work_w']))
        self.assertTrue(meta['constrained'])

    def test_against_uncondensed_full_global_system(self):
        # Independent native Dirichlet mode solves assemble the regional
        # bilinear form; solve the full global constrained system, not its Schur
        # complement. This check is small and does not repeat a refinement run.
        modes = self.driver.coupling()['boundary_modes_m']
        K = np.empty((len(modes), len(modes)))
        for j, mode in enumerate(modes):
            solved = self.native.solve(0., mode, {s: 0. for s in SIDES},
                parent_state_id='test:independent-mode', epoch_id=self.network.epoch_id, time_s=0.,
                force_source='test:zero-body', boundary_source='test:unit-physical-mode')
            K[:, j] = np.einsum('kij,ij->k', modes, solved.array('velocity_constraint_reaction_n'))
        a, other = self.driver._a, self.driver._other
        P = np.zeros((len(self.driver._b), len(modes)+len(other)))
        P[np.ix_(a, np.arange(len(modes)))] = self.lift._basis
        P[np.ix_(other, np.arange(len(modes), P.shape[1]))] = np.eye(len(other))
        matrix = P.T@self.prepared.matrix@P
        matrix[:len(modes), :len(modes)] += K
        expected = P@np.linalg.solve(matrix, P.T@self.driver._b)
        actual = self.result.exchange.array('omega_rad_s').ravel()
        self.assertLessEqual(R._relative(actual-expected, expected), R.ALGEBRA)
        self.assertGreater(np.max(np.abs(actual-self.exterior.omega_rad_s.ravel())), 1e-8)
        self.assertGreater(np.max(np.abs(self.driver._other_response)), 0.)

    def test_reconstruction_reuses_actual_snapshot_and_changed_viscosity(self):
        count = self.native.statistics()['solves']
        restored = RegionalMechanicalSnapshot(json.loads(json.dumps(self.result.mechanical.descriptor())),
            {k: self.result.mechanical.array(k) for k in self.result.mechanical.array_names})
        replay = self.driver.reconstruct(restored, parent_state_id='test:native-parent', time_s=0.)
        self.assertEqual(replay.exchange.result_id, self.result.exchange.result_id)
        self.assertEqual(self.native.statistics()['solves'], count)
        with self.native.with_viscosity(2., material_source='test:fixed-or-thermal-source') as changed:
            new = self.driver.solve(changed, parent_state_id='test:native-next', time_s=1.,
                epoch_id=self.network.epoch_id, force_source='test:zero-body', boundary_source='test:physical-walls')
        self.assertNotEqual(new.mechanical.descriptor()['plan_id'], restored.descriptor()['plan_id'])
        self.assertGreater(np.max(np.abs(new.exchange.array('omega_rad_s')-
                                        replay.exchange.array('omega_rad_s'))), 1e-8)
        self.assertEqual(self.forcing.forcing_id, self.exterior.forcing_id)
        before = self.driver.coupling()['boundary_modes_m']
        modified = self.driver.coupling()
        modified['boundary_modes_m'][:] = 7.
        assert_array_equal(before, self.driver.coupling()['boundary_modes_m'])
        with self.assertRaises(ValueError):
            replay.exchange.array('omega_rad_s')[0, 0] = 0.
        with self.assertRaisesRegex(TectonicsError, 'immutable'):
            self.lift.plate_ids = ('C', 'B')
        with self.assertRaisesRegex(TectonicsError, 'immutable'):
            self.driver.driving_id = 'changed'

    def test_refusals_preserve_geometry_flux_ownership_and_binding(self):
        common = dict(self.map_args)
        for changes, phrase in ((dict(angular_rate_basis=np.eye(6), constraint_source=None), 'volume flux'),
                                (dict(angular_rate_basis=np.zeros((6, 1))), 'nullspace'),
                                (dict(origin_local_m=(-.5, -.5, -5.)), 'depth')):
            with self.assertRaisesRegex(TectonicsError, phrase):
                R.PlateBoundaryLift(self.network, self.native, self.footprint, 'boundary-m00',
                                    **dict(common, **changes), budget=self.budget)
        bad = list(common['node_face_ids'])
        i = next(j for j, f in enumerate(bad) if f is not None)
        bad[i] = 's03-b01'
        with self.assertRaisesRegex(TectonicsError, 'outside'):
            R.PlateBoundaryLift(self.network, self.native, self.footprint, 'boundary-m00',
                **dict(common, node_face_ids=tuple(bad)), budget=self.budget)
        with self.assertRaisesRegex(TectonicsError, 'frame'):
            R.PlateBoundaryLift(self.network, self.native, replace(self.footprint, region_id='wrong'),
                'boundary-m00', **common, budget=self.budget)
        duplicate = replace(self.forcing, interface_k_pa_s=(('boundary-m00', .1),))
        op = D.prepare(self.network, duplicate)
        balance = D.balance(self.network, duplicate, prepared=op,
                            parent_state_id='0'*64, interval=(0, 1, 0., 1.))
        with self.assertRaisesRegex(TectonicsError, 'another resistance'):
            R.PreparedRegionalDriving(self.network, duplicate, balance, op, self.lift, budget=self.budget)
        with self.assertRaisesRegex(TectonicsError, 'stale'):
            self.driver.reconstruct(self.result.mechanical, parent_state_id='wrong', time_s=0.)
        with self.assertRaisesRegex(TectonicsError, 'endpoint'):
            self.driver.reconstruct(self.result.mechanical, parent_state_id='test:native-parent', time_s=2.)
        tamper = self.result.mechanical.descriptor()
        tamper['request']['coupling']['modes_sha256'] = '0'*64
        corrupted = RegionalMechanicalSnapshot(tamper,
            {k: self.result.mechanical.array(k) for k in self.result.mechanical.array_names})
        with self.assertRaisesRegex(TectonicsError, 'stale'):
            self.driver.reconstruct(corrupted, parent_state_id='test:native-parent', time_s=0.)
        # Admission refuses before new retained matrix/mode copies when the
        # shared budget is fully reserved; no alternate budget is accepted.
        with self.budget.reserve(self.budget.available_bytes, category='test-full-budget'):
            with self.assertRaises(MemoryLimitError):
                R.PreparedRegionalDriving(self.network, self.forcing, self.exterior,
                    self.prepared, self.lift, budget=self.budget)


if __name__ == '__main__':
    unittest.main()
