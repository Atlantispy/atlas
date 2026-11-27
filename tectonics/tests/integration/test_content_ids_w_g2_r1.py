"""Unit W g2 (issue 96, content identifiers), T-2: process identifiers equal under two code identities.
  python -B -I test_content_ids_w_g2_r1.py <package parent folder>"""
import math
import sys
import threading
import unittest
from unittest import mock

import numpy as np

if __name__ == '__main__':
    sys.path.insert(0, sys.argv.pop(1))
from atlas_tectonics.integration import reuse  # noqa: E402
from atlas_tectonics.integration.reuse import ExecutionContext  # noqa: E402
from atlas_tectonics.planet.mesh import ColumnGrid1D  # noqa: E402
from atlas_tectonics.materials.materials import MaterialCohort, MaterialState  # noqa: E402

A, B = 'a'*64, 'b'*64


def ctx(identity, backend='reference'):
    """A real ExecutionContext on a given identity (the adopted-worker route), no source capture."""
    c = object.__new__(ExecutionContext)
    c.backend, c._identity = backend, identity
    c._closed = c._close_verified = False
    c._close_lock = threading.RLock()
    return c


class ExtensionTests(unittest.TestCase):
    def motion(self, identity, backend='reference', velocity=.2):
        from atlas_tectonics.crust.extension import ListricGeometry, PreparedListricExtension
        return PreparedListricExtension(ColumnGrid1D(np.linspace(-16., 24., 81), frame_id='test-frame'),
            ListricGeometry(10., 3., math.atan(1.5), 0., 'test-geometry'), velocity_m_s=velocity,
            density_kg_m3=2., width_m=2., cohorts=(MaterialCohort('a', 'rock', 'source-a', -5.),
            MaterialCohort('b', 'rock', 'source-b', None)), fractions=(.25, .75), time_s=0.,
            epoch_id='test-epoch', datum_id='initial-flat-surface', source_id='test-extension',
            backend=backend, context=ctx(identity, backend))

    def test_plan_and_material_transition(self):
        with self.motion(A) as a, self.motion(B) as b, self.motion(A, velocity=.3) as c:
            self.assertEqual(a.plan_id, b.plan_id)
            self.assertNotEqual(a.plan_id, c.plan_id)
            sa, sb = a.advance(a.initial, time_s=1.), b.advance(b.initial, time_s=1.)
            # remapping._publish transition_id and MaterialState.state_id (E-6 helpers)
            self.assertNotEqual(sa.material.transition_record['execution'], sb.material.transition_record['execution'])
            self.assertEqual(sa.material.transition_id, sb.material.transition_id)
            self.assertEqual(sa.material.state_id, sb.material.state_id)
            self.assertNotEqual(sa.material.state_id, c.advance(c.initial, time_s=1.).material.state_id)

    def test_backend_is_in_the_plan(self):  # E-4
        try:
            import atlas_tectonics.planet._mesh_native  # noqa: F401
        except ImportError:
            self.skipTest('numba backend unavailable')
        with self.motion(A) as a, self.motion(A, 'numba') as n:
            self.assertNotEqual(a.plan_id, n.plan_id)

    def test_support_and_workflow(self):
        from atlas_tectonics import ExtensionSupportPolicy, FlexureParameters, PreparedExtensionWorkflow
        policy = ExtensionSupportPolicy(FlexureParameters('synthetic-elastic', 'workflow control',
            12., 1., 0., 4., 1.), 2., .5, .2, 1e-5, 'synthetic-support')
        out = {}
        for key, identity, velocity in (('a', A, .2), ('b', B, .2), ('c', A, .3)):
            with self.motion(identity, velocity=velocity) as m, \
                    PreparedExtensionWorkflow(m, policy, (0., 1.)) as w:
                r = w.run(through=1)
                out[key] = (w._support.plan_id, w.plan_id, r.checkpoint_id, r.support.result_id)
        self.assertEqual(out['a'], out['b'])
        for x, y in zip(out['a'], out['c']):
            self.assertNotEqual(x, y)


class ShorteningTests(unittest.TestCase):
    def plan(self, identity, rho=2850.):
        from atlas_tectonics.crust.shortening import PreparedShortening, ShorteningInterval
        grid = ColumnGrid1D(np.linspace(0., 1000., 9), frame_id='synthetic-cartesian')
        material = MaterialState(grid, (MaterialCohort('a', 'upper-crust', 'initial-A', -10.),
            MaterialCohort('b', 'lower-crust', 'initial-B', None)),
            np.array([np.full(8, 10000.), np.full(8, 20000.)]), time_s=0., epoch_id='synthetic-seconds')
        return PreparedShortening(material, (ShorteningInterval(1., math.log(.8), 0., 0., 'test-rate'),),
            density_kg_m3=[2700., rho], width_m=1000., datum_id='initial-datum', source_id='test-source',
            context=ctx(identity))

    def test_plan_and_states(self):
        with self.plan(A) as a, self.plan(B) as b, self.plan(A, 2900.) as c:
            self.assertEqual(a.plan_id, b.plan_id)
            self.assertNotEqual(a.plan_id, c.plan_id)
            self.assertEqual(a.evaluate(1.).material.state_id, b.evaluate(1.).material.state_id)

    def test_support_plan_and_result(self):
        from atlas_tectonics.planet.parameters import FlexureParameters
        from atlas_tectonics.crust.shortening_support import PreparedShorteningSupport, ShorteningSupportPolicy
        policy = ShorteningSupportPolicy(FlexureParameters('synthetic-elastic', 'control', 12., 1., 0., 4., 1.),
                                         4., 2., .8, .8, 'synthetic-support')
        out = {}
        from atlas_tectonics.crust.shortening import PreparedShortening, ShorteningInterval
        for key, identity, rho in (('a', A, 3.), ('b', B, 3.), ('c', A, 3.5)):
            material = MaterialState(ColumnGrid1D([0., 1., 2., 3., 4.], frame_id='section'),
                (MaterialCohort('a', 'rock-a', 'source-a', -2.), MaterialCohort('b', 'rock-b', 'source-b', -1.)),
                np.array([[.2]*4, [.3]*4]), time_s=0., epoch_id='epoch')
            grid = ColumnGrid1D(np.linspace(-2., 6., 17), frame_id='section')
            with PreparedShortening(material, (ShorteningInterval(1., math.log(.5), 0., 0., 'history'),),
                    density_kg_m3=[2., rho], width_m=2., datum_id='fixed-base', source_id='shortening',
                    context=ctx(identity)) as m, PreparedShorteningSupport(m, grid, policy,
                    support_height_m=np.full(grid.cells, 2.), replacement_density_kg_m3=np.zeros(grid.cells),
                    geometry_source='synthetic-support-geometry') as s:
                out[key] = (s.plan_id, s.solve(m.evaluate(1.)).result_id)
        self.assertEqual(out['a'], out['b'])
        self.assertNotEqual(out['a'][0], out['c'][0])
        self.assertNotEqual(out['a'][1], out['c'][1])


class SpreadingAndMagmaTests(unittest.TestCase):
    def test_ridge_spreading_plan(self):
        from atlas_tectonics.spreading.spreading import PreparedRidgeSpreading, RidgeMotion, SpreadingPhase
        year = 31557600.

        def plan(identity, crust=7000.):
            grid = ColumnGrid1D(np.linspace(-5e5, 5e5, 17), frame_id='w06-synthetic-planar-section')
            motion = RidgeMotion(0., -.02/year, .02/year, 0., 'left-plate', 'right-plate', 'ridge', 'onset',
                                 'w06-prescribed-motion')
            phases = (SpreadingPhase('crust', 'crust-feed', crust, 2900., 2e13),
                      SpreadingPhase('mantle', 'mantle-feed', 93000., 3300., 3e14))
            return PreparedRidgeSpreading(grid, motion, phases, time_s=0., epoch_id='epoch', width_m=1.,
                                          source_id='case', context=ctx(identity))
        with plan(A) as a, plan(B) as b, plan(A, 8000.) as c:
            self.assertEqual(a.plan_id, b.plan_id)
            self.assertNotEqual(a.plan_id, c.plan_id)

    def test_magmatic_transfer_plan(self):
        from atlas_tectonics.thermal.magmatic_transfer import MagmaticInventory, PreparedMagmaticTransfer

        def plan(identity, outflow=1.):
            inv = MagmaticInventory(('export', 'reservoir', 'source'), ('export', 'reservoir', 'source-melt'),
                ('initial', 'recharge'), [[0, 0], [2, 0], [0, 10]], [0, 0, 100], source_id='A05-initial',
                enthalpy_source='synthetic-specific-J-per-kg')
            q = np.zeros((3, 3)); q[2, 1] = 1.; q[1, 0] = outflow
            return PreparedMagmaticTransfer(inv, q, source_id='frozen-A04-A05', context=ctx(identity, 'scipy'))
        a, b, c = plan(A), plan(B), plan(A, 2.)
        self.assertEqual(a.plan_id, b.plan_id)
        self.assertNotEqual(a.plan_id, c.plan_id)


class PlanarTests(unittest.TestCase):
    def square(self, x=0.):
        from atlas_tectonics.planet.geometry import PlanarGeometry
        return PlanarGeometry.polygon([[x, 0.], [x+1., 0.], [x+1., 1.], [x, 1.]], frame_id='test-plane')

    def transform(self, identity, rho=2850.):
        from atlas_tectonics.plates import transform as T
        with mock.patch.object(T, 'ExecutionContext', lambda backend: ctx(identity, backend)):
            m = T.PreparedAffineMotion((self.square(),), (T.AffineMotionInterval(1., ((0., 2.), (0., 0.)),
                (0., 0.), (0., 0.), 'test-motion'),), parcel_ids=('p0',), time_s=0., source_id='analytic')
        p = T.PreparedPlanarMaterials(m, (MaterialCohort('a', 'upper', 'source-a', -10.),
            MaterialCohort('b', 'lower', 'source-b', None)), np.array([[10000.], [20000.]]),
            density_kg_m3=[2700., rho], epoch_id='test-epoch', datum_id='test-datum', source_id='inventory',
            context=ctx(identity, 'scipy'))
        return m, p

    def test_transform_plan_snapshot_projection(self):
        ids = {}
        for key, identity, rho in (('a', A, 2850.), ('b', B, 2850.), ('c', A, 2900.)):
            m, p = self.transform(identity, rho)
            with m, p:
                s = p.evaluate(1.)
                q = p.project(1., (self.square(-1.), self.square(1.)), target_ids=('t0', 't1'),
                              exterior_id='out', source_id='view')
                ids[key] = (m.plan_id, p.plan_id, s.state_id, q.projection_id)
        self.assertEqual(ids['a'], ids['b'])
        self.assertEqual(ids['a'][0], ids['c'][0])  # same motion
        for x, y in zip(ids['a'][1:], ids['c'][1:]):
            self.assertNotEqual(x, y)

    def test_fault_slip_and_network(self):
        from atlas_tectonics.plates import fault_slip as F, deformation_network as D
        from atlas_tectonics.planet.geometry import PlanarGeometry

        def slip(identity, source):
            parcels = tuple(PlanarGeometry.polygon(xy, frame_id='slip-frame') for xy in (
                [[-1000., -2000.], [0., -2000.], [0., 2000.], [-1000., 2000.]],
                [[0., -2000.], [1000., -2000.], [1000., 2000.], [0., 2000.]]))
            with mock.patch.object(F, 'ExecutionContext', lambda backend: ctx(identity, backend)):
                return F.PreparedFaultSlip(parcels, (F.SlipInterval(10., [0., -10.], [0., 20.], [0., 0.], 'slip'),),
                    parcel_ids=('west', 'east'), sides=(-1, 1), interface_point_m=[0., 0.],
                    interface_normal=[1., 0.], interface_id='fault', time_s=0., source_id=source)

        def net(identity, source):
            x = np.array([[-2., -1.], [2., -1.], [2., 1.], [-2., 1.], [0., 0.]])*1000
            t = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]])
            with mock.patch.object(D, 'ExecutionContext', lambda backend: ctx(identity, backend)):
                return D.PreparedDeformationNetwork(x, t, (D.NodalMotionInterval(10., np.zeros_like(x), 'still'),),
                    time_s=0., frame_id='synthetic-local-SI', source_id=source,
                    triangle_ids=tuple('triangle-'+str(i) for i in range(4)))

        for make in (slip, net):
            with self.subTest(make.__name__):
                with make(A, 's') as a, make(B, 's') as b, make(A, 's2') as c:
                    self.assertEqual(a.plan_id, b.plan_id)
                    self.assertNotEqual(a.plan_id, c.plan_id)
                    self.assertEqual(a.evaluate(5.).state_id, b.evaluate(5.).state_id)


class AtlasTests(unittest.TestCase):
    def test_partition_atlas_id_drops_generator_source(self):  # E-1; E-8 qhull stays
        from atlas_tectonics.planet.coordinates import SphericalFrame
        from atlas_tectonics.planet.planetary_generation import PlanetPartitionSettings, generate_planetary_partition
        sphere = SphericalFrame(6.371e6, 'test-sphere')

        def atlas(source, seed=7):
            with mock.patch.object(reuse, '_file_hash', lambda path: source):
                return generate_planetary_partition(sphere, PlanetPartitionSettings(8, seed))
        a, b = atlas(A), atlas(B)
        self.assertNotEqual(a.descriptor()['source_bindings'], b.descriptor()['source_bindings'])
        self.assertEqual(a.atlas_id, b.atlas_id)
        self.assertNotEqual(a.atlas_id, atlas(A, 8).atlas_id)

    def test_plate_layout_atlas_id_drops_execution(self):
        from atlas_tectonics.plates import layout as P
        from atlas_tectonics.planet.coordinates import SphericalFrame
        sphere = SphericalFrame(6.371e6, 'test-sphere')

        def atlas(identity, seed=3):
            return P._generate_plate_layout(sphere, P.PlateLayoutSettings(6, seed, support_cells=256),
                                            execution_id=identity)
        a = atlas(A)
        self.assertEqual(a.atlas_id, atlas(B).atlas_id)
        self.assertNotEqual(a.atlas_id, atlas(A, 4).atlas_id)


if __name__ == '__main__':
    unittest.main()
