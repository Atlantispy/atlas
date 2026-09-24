"""Analytical motion diagnostics only: no generated world or native campaign."""
import json
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(os.environ.get('ATLAS_TECTONICS_ROOT', Path(__file__).resolve().parents[1]))
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT/'tools')]
import assess_new_world_motion as assessment
import new_world_motion as motion
from new_world_contract import ContractError


class ArcAtlas:
    """Small supplied equatorial arcs, not a generated or accepted world."""
    def __init__(self, intervals, radius=1.):
        self.sphere = SimpleNamespace(radius_m=radius, frame_id='analytical-frame')
        self.atlas_id, self.geometry_id = 'analytical-atlas', 'analytical-geometry'
        self.plate_ids = ('left', 'right')
        self.vertex_directions = np.array([[math.cos(s), math.sin(s), 0.]
                                          for interval in intervals for s in interval])
        self.edge_vertices = np.arange(2*len(intervals)).reshape((-1, 2))
        self.interplate_edges = tuple(range(len(intervals)))

    def edge(self, index):
        return SimpleNamespace(left_plate_id='left', right_plate_id='right')


def fixture(intervals=((0., math.pi/2),), delta=(0., 1., 0.), cuts=None, common=(0., 0., 0.)):
    atlas = ArcAtlas(intervals)
    angular = {'left': list(common), 'right': (np.asarray(common)+delta).tolist()}
    segments = []
    for index in atlas.interplate_edges:
        a, b = atlas.vertex_directions[atlas.edge_vertices[index]]
        u, left, angle = motion._arc(a, b)
        A, B = float(np.asarray(delta) @ u), -float(np.asarray(delta) @ a)
        breaks = [0.] + motion._opening_breaks(A, B, angle) + [angle]
        if cuts is not None:
            breaks = sorted(set(breaks+[fraction*angle for fraction in cuts]))
        for lo, hi in zip(breaks, breaks[1:]):
            opening = A*math.cos(.5*(lo+hi))+B*math.sin(.5*(lo+hi))
            regime = ('stationary' if not np.any(delta) else 'normal-motion-unresolved') if A == B == 0. else (
                'incipient-extension' if opening > 0 else 'incipient-shortening')
            segments.append(dict(edge_index=index, start_fraction=lo/angle, end_fraction=hi/angle,
                left_plate='left', right_plate='right', regime=regime))
    record = dict(schema=motion.METHOD, status='WORKING NON-CANON', atlas_id=atlas.atlas_id,
                  geometry_id=atlas.geometry_id, frame_id=atlas.sphere.frame_id,
                  angular_velocities_rad_s=angular, segments=segments)
    return atlas, motion.WorldMotion(motion._encode(record))


class MotionAssessmentTests(unittest.TestCase):
    def test_analytic_normal_shear_and_oblique_rms(self):
        scale = motion.YEAR*100.
        for delta, normal, shear, obliquity in (
            ((0., 1., 0.), 1/math.sqrt(2), 0., 0.),
            ((0., 0., 2.), 0., 2., 90.),
            ((0., 1., 2.), 1/math.sqrt(2), 2., math.degrees(math.atan2(2., math.sqrt(.5)))),
        ):
            with self.subTest(delta=delta):
                atlas, saved = fixture(delta=delta)
                report = assessment.assess_motion(atlas, saved)
                rms = report['boundary_rms_cm_year']
                self.assertAlmostEqual(rms['normal']/scale, normal, places=13)
                self.assertAlmostEqual(rms['shear']/scale, shear, places=13)
                self.assertAlmostEqual(rms['relative']/scale, math.hypot(normal, shear), places=13)
                self.assertAlmostEqual(report['obliquity']['mean_degrees'], obliquity, places=13)
                self.assertIn('MIDPOINT_APPROXIMATION', report['obliquity']['method'])

    def test_length_weighting_not_segment_count_weighting(self):
        # One extension segment covers 1 rad; one shortening covers .25 rad.
        atlas, saved = fixture(intervals=((0., 1.), (2., 2.25)))
        report = assessment.assess_motion(atlas, saved)
        self.assertEqual(report['segment_count'], 2)
        self.assertAlmostEqual(report['boundary_length_fractions']['extension'], .8, places=14)
        self.assertAlmostEqual(report['boundary_length_fractions']['shortening'], .2, places=14)
        self.assertAlmostEqual(report['boundary_length_m'], 1.25, places=14)
        oblique_atlas, oblique = fixture(intervals=((0., 1.), (2., 2.25)), delta=(0., 1., 2.))
        value = assessment.assess_motion(oblique_atlas, oblique)['obliquity']['mean_degrees']
        expected = (.8*math.degrees(math.atan2(2., abs(math.cos(.5))))
                    +.2*math.degrees(math.atan2(2., abs(math.cos(2.125)))))
        self.assertAlmostEqual(value, expected, places=13)

    def test_segment_and_native_edge_subdivision_preserve_exact_statistics(self):
        a, m = fixture(intervals=((0., 1.4),), delta=(.3, 1., 2.))
        baseline = assessment.assess_motion(a, m)
        for intervals, cuts in ((((0., 1.4),), (.05, .2, .55, .9)),
                                (((0., .3), (.3, 1.), (1., 1.4)), None)):
            other_a, other_m = fixture(intervals=intervals, delta=(.3, 1., 2.), cuts=cuts)
            report = assessment.assess_motion(other_a, other_m)
            for key in ('normal', 'shear', 'relative'):
                self.assertAlmostEqual(report['boundary_rms_cm_year'][key]/baseline['boundary_rms_cm_year'][key], 1., places=13)
            for key in ('extension', 'shortening', 'unresolved'):
                self.assertAlmostEqual(report['boundary_length_fractions'][key], baseline['boundary_length_fractions'][key], places=13)
        self.assertNotEqual(report['obliquity']['mean_degrees'], baseline['obliquity']['mean_degrees'])

    def test_common_rotation_preserves_relative_diagnostics(self):
        a, m = fixture(delta=(.25, 1., 2.))
        b, n = fixture(delta=(.25, 1., 2.), common=(16., -32., 8.))
        first, second = assessment.assess_motion(a, m), assessment.assess_motion(b, n)
        for key in ('boundary_rms_cm_year', 'boundary_length_fractions', 'obliquity'):
            self.assertEqual(first[key], second[key])

    def test_stationary_is_unresolved_and_excluded_from_obliquity(self):
        a, m = fixture(delta=(0., 0., 0.), cuts=(.1, .4))
        report = assessment.assess_motion(a, m)
        self.assertEqual(report['boundary_length_fractions'], dict(extension=0., shortening=0., unresolved=1.))
        self.assertEqual(report['boundary_rms_cm_year'], dict(normal=0., shear=0., relative=0.))
        self.assertIsNone(report['obliquity']['mean_degrees'])
        self.assertEqual(report['obliquity']['excluded_stationary_segment_count'], 3)
        self.assertEqual(report['obliquity']['excluded_stationary_length_m'], report['boundary_length_m'])
        json.dumps(report, allow_nan=False)

    def test_nonstationary_zero_speed_midpoint_is_separately_excluded(self):
        a, m = fixture(intervals=((-0.5, 0.5),), delta=(1., 0., 0.))
        record = m.descriptor()
        record['segments'] = [dict(edge_index=0, start_fraction=0., end_fraction=1.,
                                   left_plate='left', right_plate='right')]
        report = assessment.assess_motion(a, motion.WorldMotion(motion._encode(record)))
        self.assertGreater(report['boundary_rms_cm_year']['relative'], 0.)
        self.assertIsNone(report['obliquity']['mean_degrees'])
        self.assertEqual(report['obliquity']['excluded_stationary_segment_count'], 0)
        self.assertEqual(report['obliquity']['excluded_zero_speed_midpoint_count'], 1)

    def test_finite_inputs_and_coverage_refusals(self):
        a, m = fixture(cuts=(.3,))
        for change in ('gap', 'overlap', 'missing', 'rotation'):
            r = m.descriptor()
            if change == 'gap': r['segments'][1]['start_fraction'] += .01
            elif change == 'overlap': r['segments'][1]['start_fraction'] -= .01
            elif change == 'missing': r['segments'].pop()
            else: r['angular_velocities_rad_s']['right'] = [0., True, 0.]
            with self.subTest(change=change), self.assertRaises(ContractError):
                assessment.assess_motion(a, motion.WorldMotion(motion._encode(r)))
        a.sphere.radius_m = float('nan')
        with self.assertRaises(ContractError): assessment.assess_motion(a, m)

    def test_fractions_ignore_altered_saved_regime_and_opening_labels(self):
        a, m = fixture(delta=(2., 1., 3.))
        r = m.descriptor()
        for segment in r['segments']:
            segment['regime'] = 'stationary'
            segment['opening_midpoint_m_s'] = 12345.
            segment['tangential_m_s'] = -12345.
        report = assessment.assess_motion(a, motion.WorldMotion(motion._encode(r)))
        expected_extension = math.atan(.5)/(math.pi/2)
        self.assertAlmostEqual(report['boundary_length_fractions']['extension'], expected_extension, places=14)
        self.assertAlmostEqual(report['boundary_length_fractions']['shortening'], 1.-expected_extension, places=14)
        self.assertEqual(report['obliquity']['excluded_stationary_segment_count'], 0)

    def test_validation_delegation_and_nonmutation(self):
        a, m = fixture()
        before = m.payload
        vertices = a.vertex_directions.copy()
        with patch.object(assessment, 'check_motion') as check:
            report = assessment.assess_motion(a, m, plan={'plan_id': 'original'}, structure='original-state')
            check.assert_called_once_with({'plan_id': 'original'}, a, 'original-state', m)
        self.assertEqual(report['validation'], 'saved-motion-and-dependencies')
        self.assertEqual(m.payload, before)
        np.testing.assert_array_equal(vertices, a.vertex_directions)
        with self.assertRaises(ContractError): assessment.assess_motion(a, m, structure='alone')
        with patch.object(assessment, 'check_motion', side_effect=ContractError('MOTION_REFUSED', 'bad dependency')):
            with self.assertRaises(ContractError): assessment.assess_motion(a, m, plan={}, structure='state')


if __name__ == '__main__':
    unittest.main()
