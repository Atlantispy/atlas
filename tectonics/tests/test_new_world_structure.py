"""Focused native structure checks; no plate campaign or time evolution."""
import copy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

TECTONICS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TECTONICS/'tools'), str(TECTONICS/'src')]
from new_world_contract import new_request, resolve_request, ContractError
import new_world_structure as structure
from atlas_tectonics import PreparedPrecursor, InitialSamplingCell, SphericalChart, SphericalGeometry


def plan(seed=0, fraction=.3, support=192, plates=6, radius=6371000., memory=128 << 20):
    settings = {k: dict(mode='fixed', value=v) for k,v in
        dict(radius_m=radius, gravity_m_s2=9.81, plate_count=plates, continental_fraction=fraction).items()}
    return resolve_request(new_request(f'{seed:032x}', settings=settings, support_cells=support,
        resources=dict(max_wall_seconds=30., max_work_bytes=memory)))


class InitialStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = plan()
        cls.world = structure.generate_structure(cls.plan)
        c = cls.world.state.case
        cls.request = dict(frame_id=c.topology.frame_id, epoch_id=c.epoch_id, depth_reference_id=c.depth_reference_id)

    def test_exact_replay_and_resolution_plate_independence(self):
        for other in (plan(), plan(support=512, plates=12)):
            w = structure.generate_structure(other)
            self.assertEqual(w.structure_id, self.world.structure_id)
            self.assertEqual(w.state.state_id, self.world.state.state_id)
        changed = structure.generate_structure(plan(seed=1))
        self.assertNotEqual(changed.state.state_id, self.world.state.state_id)
        self.assertNotEqual(changed.report['feature_geometry_ids'], self.world.report['feature_geometry_ids'])

    def test_coverage_columns_ages_and_explicit_unknowns(self):
        w = self.world
        self.assertAlmostEqual(w.report['realised_continental_fraction'], .3, places=13)
        self.assertFalse(w.state.preflight(require_temperature=True, require_porosity=True))
        self.assertTrue(w.state.preflight(required_fields=('stress', 'damage')))
        case = w.state.case
        self.assertTrue(all(z.strength_factor is None for z in case.weak_zones))
        for c in case.columns:
            self.assertAlmostEqual(sum(l.bulk_thickness_m for l in c.layers), c.lithosphere_thickness_m, places=8)
            d = next(d for d in w.report['columns'] if d['column_id'] == c.column_id)
            if c.crust_type == 'continental':
                self.assertIsNone(d['cooling_age_s'])
                self.assertGreater(d['crust_formation_age_s'], 100*structure.MYR)
            else:
                self.assertEqual(d['crust_formation_age_s'], d['cooling_age_s'])
        # Inheritance is actually in continental crust, not a separately guessed map.
        traces = [g for g in case.geometries if g.geometry.kind == 'LineString']
        points = [g.geometry.chart.centre for g in traces]
        with PreparedPrecursor(w.state) as p:
            sampled = p.sample_points(points, 1., **self.request)
        self.assertTrue(sampled.array('temperature_known').all())
        self.assertTrue(all(c.formation_time_s is None for c in
            (x.cohort for x in case.cohorts if x.cohort.cohort_id.endswith('-mantle'))))

    def test_fraction_extremes_and_majority_continent(self):
        for f in (0., .5, .85, 1.):
            with self.subTest(f=f):
                w = structure.generate_structure(plan(fraction=f))
                self.assertAlmostEqual(w.report['realised_continental_fraction'], f, places=13)
                if f in (0., 1.):
                    self.assertEqual(len(w.state.case.provinces), 1)
                if f == 0.:
                    self.assertEqual(w.state.case.weak_zones, ())

    def test_mixed_spherical_inventory_adds_under_cell_refinement(self):
        w = self.world
        feature = next(g.geometry for g in w.state.case.geometries if g.geometry.kind == 'Polygon')
        chart = feature.chart
        # A rectangle through the feature edge, with both crust types. Child
        # boundaries are identical great circles in the same gnomonic chart.
        edge = float(feature._projected._geom.bounds[2])
        def rectangle(x0, x1):
            return SphericalGeometry.polygon(chart._unproject(np.array(
                [[x0,-.08],[x1,-.08],[x1,.08],[x0,.08]])), chart=chart)
        a, b, middle = edge*.5, edge*1.25, edge*.875
        coarse = InitialSamplingCell('coarse', rectangle(a,b), 0., 60000.)
        children = (InitialSamplingCell('left', rectangle(a,middle), 0., 60000.),
                    InitialSamplingCell('right', rectangle(middle,b), 0., 60000.))
        with PreparedPrecursor(w.state) as p:
            c = p.sample_cells((coarse,), **self.request)
            f = p.sample_cells(children, **self.request)
        for key in ('cell_volume_m3', 'phase_volume_m3'):
            self.assertAlmostEqual(math.fsum(c.array(key))/math.fsum(f.array(key)), 1., places=10)
        self.assertGreater(len(set(c.array('phase_cohort_code'))), 3)
        for code in set(c.array('phase_cohort_code')):
            cv = math.fsum(c.array('phase_volume_m3')[c.array('phase_cohort_code') == code])
            fv = math.fsum(f.array('phase_volume_m3')[f.array('phase_cohort_code') == code])
            self.assertLess(abs(cv-fv)/cv, 2e-11)
        # Whole-cell means, not point samples: weighted thermal content agrees.
        coarse_t = float(c.temperature()[0])*float(c.array('cell_volume_m3')[0])
        fine_t = float(np.dot(f.temperature(), f.array('cell_volume_m3')))
        self.assertLess(abs(coarse_t-fine_t)/abs(coarse_t), 2e-11)
        radius = w.state.case.topology.sphere.radius_m
        expected = coarse.footprint.area_steradians*(60000.*(radius*radius-radius*60000.+60000.**2/3))
        self.assertLess(abs(c.array('cell_volume_m3')[0]-expected)/expected, 2e-11)

    def test_poles_seam_order_and_frame(self):
        points = np.array([[0,0,1.],[0,0,-1.],[-1,1e-14,0.],[-1,-1e-14,0.]])
        with PreparedPrecursor(self.world.state) as p:
            a = p.sample_points(points, 5000., **self.request)
            b = p.sample_points(points[::-1], 5000., **self.request)
        np.testing.assert_array_equal(a.temperature(), b.temperature()[::-1])
        self.assertAlmostEqual(a.temperature()[2], a.temperature()[3], places=11)
        rotation = structure._rotation('a'*32)
        np.testing.assert_allclose(rotation.T@rotation, np.eye(3), atol=1e-15)
        self.assertAlmostEqual(np.linalg.det(rotation), 1., places=14)

    def test_refusal_and_native_binding(self):
        structure.check_structure(self.plan, self.world, current=True)
        with self.assertRaises(ContractError):
            structure.check_structure(plan(fraction=.4), self.world)
        for p in (plan(radius=1e6), plan(memory=1 << 20)):
            with self.assertRaises(ContractError):
                structure.generate_structure(p)
        with patch.object(structure, '_LOADED_HASH', '0'*64):
            with self.assertRaisesRegex(ContractError, 'changed'):
                structure.generate_structure(self.plan)


if __name__ == '__main__':
    unittest.main()
