"""Matched-scale boundary diagnostics: analytical cases, PB2002 conventions, one small saved world.
SPDX-License-Identifier: AGPL-3.0-only
"""
import contextlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src')]
import assess_boundary_kinematics as kin

EARTH = 6371000.
DATA = ROOT/'reference_data/pb2002'


def lonlat(lon, lat):
    lon, lat = math.radians(lon), math.radians(lat)
    return [math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)]


def line(coordinates, left='north', right='south', closed=False):
    return kin.BoundaryLine(left, right, np.asarray([lonlat(*c) for c in coordinates]), closed)


def measure(lines, delta, spacings, threshold=70.):
    angular = {'north': [0., 0., 0.], 'south': list(delta)}
    return kin.measure(lines, angular, EARTH, kin.protocol(spacings, threshold))[0]


class GeometryTests(unittest.TestCase):
    def test_equal_chords_keep_ends_and_straight_lines_do_not_bend(self):
        source = line([(lon, 0.) for lon in (0., 3., 10., 22., 35., 51., 60.)])
        ring = kin._resample(source.points, 6, False)
        arcs = kin._arc(ring[:-1], ring[1:])
        np.testing.assert_allclose(arcs, math.radians(10.), rtol=0, atol=1e-13)
        self.assertTrue(np.array_equal(ring[0], source.points[0]))
        self.assertTrue(np.array_equal(ring[-1], source.points[-1]))
        self.assertLess(kin._bends(ring, False).max(), 1e-9)

    def test_right_angle_corner_is_ninety_degrees_in_either_direction(self):
        path = [(0., 0.), (15., 0.), (30., 0.), (30., 15.), (30., 30.)]
        for coordinates in (path, path[::-1]):
            ring = kin._resample(line(coordinates).points, 2, False)
            np.testing.assert_allclose(kin._bends(ring, False), [90.], atol=1e-9)

    def test_closed_ring_bends_at_every_vertex_including_closure(self):
        coordinates = [(lon, 60.) for lon in range(0, 360, 30)] + [(0., 60.)]
        ring = line(coordinates, closed=True)
        report = measure([ring], (0., 0., 1e-15), (1000e3,))
        native = report['native']
        self.assertEqual(native['chords'], 12)
        self.assertEqual(native['bend_deg']['count'], 12)
        # A regular spherical 12-gon turns by the same exterior angle everywhere.
        self.assertAlmostEqual(native['bend_deg']['quantiles'][0], native['bend_deg']['quantiles'][-1], places=9)


class KinematicsTests(unittest.TestCase):
    def test_opening_shear_and_oblique_cases(self):
        equator = [line([(lon, 0.) for lon in range(0, 61, 5)])]
        w = 1e-15
        opening = measure(equator, (0., w, 0.), (1000e3,))
        for profile in [opening['native']] + opening['scales']:
            self.assertEqual(profile['length_share']['opening'], 1.)
            self.assertLess(profile['obliquity_deg']['quantiles'][-1], 1e-9)
            self.assertEqual(profile['sign_changes'], dict(normal_component=0, dominated_class=0))
        shear = measure(equator, (0., 0., w), (1000e3,))
        for profile in [shear['native']] + shear['scales']:
            self.assertEqual(profile['length_share']['shear_dominated'], 1.)
            self.assertGreater(profile['obliquity_deg']['quantiles'][0], 90.-1e-9)
            self.assertEqual(profile['sign_changes'], dict(normal_component=0, dominated_class=0))
        # One chord centred on longitude 0: normal and along-chord speeds are equal.
        short = [line([(-1., 0.), (1., 0.)])]
        oblique = measure(short, (0., w, w), (2*math.radians(1.)*EARTH,))
        self.assertAlmostEqual(oblique['scales'][0]['obliquity_deg']['quantiles'][3], 45., places=9)
        self.assertEqual(oblique['scales'][0]['length_share']['opening'], 1.)

    def test_sign_change_across_the_relative_pole_is_counted_once(self):
        crossing = [line([(lon, 0.) for lon in range(60, 121, 5)])]
        report = measure(crossing, (0., 1e-15, 0.), (1000e3,))
        for profile in [report['native']] + report['scales']:
            self.assertEqual(profile['sign_changes'], dict(normal_component=1, dominated_class=1))
        self.assertAlmostEqual(report['native']['length_share']['opening'], .5, places=12)
        # Seven chords: the middle one is centred on the relative pole, where plates do not move.
        shares = report['scales'][0]['length_share']
        for name, value in (('opening', 3/7), ('shortening', 3/7), ('stationary', 1/7)):
            self.assertAlmostEqual(shares[name], value, places=12)

    def test_identical_rotations_are_stationary(self):
        report = measure([line([(lon, 0.) for lon in range(0, 31, 5)])], (0., 0., 0.), (1000e3,))
        for profile in [report['native']] + report['scales']:
            self.assertEqual(profile['length_share']['stationary'], 1.)
            self.assertEqual(profile['obliquity_deg'], dict(count=0))
            self.assertEqual(profile['sign_changes'], dict(normal_component=0, dominated_class=0))

    def test_zigzag_flips_at_native_resolution_but_not_at_its_own_wavelength(self):
        coordinates = [(float(k), .5 if k % 2 else 0.) for k in range(41)]
        zigzag = [line(coordinates)]
        length = float(np.sum(kin._arc(zigzag[0].points[:-1], zigzag[0].points[1:])))
        wavelength = length/20*EARTH
        report = measure(zigzag, (0., 0., 1e-15), (wavelength,))
        native, matched = report['native'], report['scales'][0]
        self.assertEqual(native['sign_changes'], dict(normal_component=39, dominated_class=39))
        self.assertGreater(native['bend_deg']['quantiles'][0], 50.)
        self.assertEqual(matched['chords'], 20)
        self.assertEqual(matched['sign_changes'], dict(normal_component=0, dominated_class=0))
        self.assertEqual(matched['length_share']['shear_dominated'], 1.)
        self.assertLess(matched['bend_deg']['quantiles'][-1], 1e-6)

    def test_reversing_a_line_changes_nothing(self):
        coordinates = [(float(k), .5 if k % 3 else -.2) for k in range(31)]
        forward = measure([line(coordinates)], (1e-15, 2e-15, 1e-15), (100e3, 250e3))
        backward = measure([line(coordinates[::-1], left='south', right='north')],
                           (1e-15, 2e-15, 1e-15), (100e3, 250e3))
        for a, b in zip([forward['native']] + forward['scales'], [backward['native']] + backward['scales']):
            self.assertEqual(a['sign_changes'], b['sign_changes'])
            for key, value in a['length_share'].items():
                self.assertAlmostEqual(value, b['length_share'][key], places=12)
            np.testing.assert_allclose(a['bend_deg']['quantiles'], b['bend_deg']['quantiles'], atol=1e-9)
            np.testing.assert_allclose(a['obliquity_deg']['quantiles'], b['obliquity_deg']['quantiles'], atol=1e-9)

    def test_short_lines_are_unresolved_not_invented(self):
        report = measure([line([(0., 0.), (1., 0.)])], (0., 1e-15, 0.), (1000e3,))
        scale = report['scales'][0]
        self.assertEqual(scale['lines'], dict(resolved=0, unresolved=1))
        self.assertIsNone(scale['sign_changes_per_1000_km']['dominated_class'])
        self.assertEqual(scale['bend_deg'], dict(count=0))
        self.assertEqual(scale['signed_motion_samples'], [dict(
            line_index=0, left_plate='north', right_plate='south', closed=False,
            status='UNRESOLVED_AT_SPACING')])

    def test_signed_components_survive_roundoff_and_shear_classification(self):
        boundary = line([(-.1, 0.), (.1, 0.)])
        delta = (0., -1e-28, -1e-15)
        report = measure([boundary], delta, (20e3,))
        middle, left, tangent, arcs = kin._chords(boundary.points, False)
        normal, _, speed = kin.chord_motion(middle, left, tangent, delta, EARTH)
        _, signs = kin.signed_motion(normal, speed, arcs, np.linalg.norm(delta), EARTH)
        self.assertEqual(signs.tolist(), [0.])
        for profile in [report['native']] + report['scales']:
            self.assertEqual(profile['length_share']['shear_dominated'], 1.)
            self.assertEqual(profile['sign_changes']['normal_component'], 0)
            samples = profile['signed_motion_samples']
            self.assertEqual(len(samples), 1)
            sample = samples[0]
            self.assertEqual((sample['line_index'], sample['left_plate'], sample['right_plate']),
                             (0, 'north', 'south'))
            self.assertFalse(sample['closed'])
            self.assertEqual(sample['status'], 'RESOLVED')
            self.assertLess(sample['normal_cm_year'][0], 0.)
            self.assertLess(sample['along_cm_year'][0], 0.)
            np.testing.assert_allclose(sample['normal_cm_year'], [delta[1]*EARTH*kin.CM_PER_YEAR], rtol=1e-14, atol=0.)
            np.testing.assert_allclose(sample['along_cm_year'], [delta[2]*EARTH*kin.CM_PER_YEAR], rtol=1e-14, atol=0.)
            np.testing.assert_allclose(sample['represented_path_edges_km'],
                                       [0., math.radians(.2)*EARTH/1000.], rtol=1e-14, atol=0.)


def piece(start, end, coordinates, left, right):
    return (start, end, np.asarray([lonlat(*c) for c in coordinates]), left, right)


def ring_pieces(names, coordinates, left='A', right='B'):
    """Consecutive two-point pieces; names[i] labels coordinates[i]."""
    return [piece(names[i], names[i+1], coordinates[i:i+2], left, right) for i in range(len(names)-1)]


class ChainTests(unittest.TestCase):
    def test_island_loops_are_closed_whether_one_piece_or_many(self):
        corners = [(0., 0.), (4., 0.), (4., 4.), (0., 4.), (0., 0.)]
        many = kin._chain(ring_pieces(['p', 'q', 'r', 's', 'p'], corners))
        single = kin._chain([piece('p', 'p', corners, 'A', 'B')])
        for lines in (many, single):
            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].closed)
            self.assertEqual(len(lines[0].points), 5)

    def test_leaving_and_reentering_one_junction_stays_open(self):
        names = ['J', 'a', 'b', 'c', 'd', 'e', 'J']
        coordinates = [(0., 0.), (4., 4.), (8., 4.), (12., 0.), (8., -4.), (4., -4.), (0., 0.)]
        pieces = ring_pieces(names, coordinates) + [
            piece('J', 'x', [(0., 0.), (-4., 4.)], 'C', 'A'), piece('J', 'y', [(0., 0.), (-4., -4.)], 'B', 'C')]
        lines = kin._chain(pieces)
        loop = [l for l in lines if {l.left, l.right} == {'A', 'B'}]
        self.assertEqual(len(loop), 1)
        self.assertFalse(loop[0].closed)
        self.assertTrue(np.array_equal(loop[0].points[0], loop[0].points[-1]))
        self.assertEqual(sum(len(l.points)-1 for l in lines), len(pieces))

    def test_figure_eight_pinch_gives_two_open_lines_and_no_piece_is_lost(self):
        left = ring_pieces(['P', 'a', 'b', 'P'], [(0., 0.), (-4., 3.), (-4., -3.), (0., 0.)])
        right = ring_pieces(['P', 'c', 'd', 'P'], [(0., 0.), (4., 3.), (4., -3.), (0., 0.)])
        lines = kin._chain(left + right)
        self.assertEqual(len(lines), 2)
        self.assertFalse(any(l.closed for l in lines))
        self.assertEqual(sum(len(l.points)-1 for l in lines), 6)

    def test_contradictory_sides_along_one_line_are_refused(self):
        pieces = [piece('a', 'b', [(0., 0.), (5., 0.)], 'A', 'B'), piece('b', 'c', [(5., 0.), (10., 0.)], 'B', 'A')]
        with self.assertRaises(kin.BoundaryAssessmentError):
            kin._chain(pieces)

    def test_out_and_back_line_at_a_junction_is_unresolved_not_nan(self):
        step = math.degrees(75e3/EARTH)
        pieces = [piece('J', 'J', [(0., 0.), (step, 0.), (0., 0.)], 'A', 'B'),
                  piece('J', 'x', [(0., 0.), (0., 5.)], 'B', 'C'), piece('J', 'y', [(0., 0.), (-5., 0.)], 'C', 'A')]
        lines = kin._chain(pieces)
        angular = {'A': [0., 0., 0.], 'B': [0., 1e-15, 0.], 'C': [1e-15, 0., 0.]}
        report, _ = kin.measure(lines, angular, EARTH, kin.protocol((250e3,)))
        json.dumps(report, allow_nan=False)
        self.assertEqual(report['scales'][0]['lines']['unresolved'], 1)


class EnvelopeTests(unittest.TestCase):
    def test_small_genuine_sign_changes_count_but_representation_noise_does_not(self):
        speed = np.ones(3)
        arcs = np.full(3, 100e3/EARTH)
        moving, signs = kin.signed_motion(np.array([-1e-6, 5e-13, -1e-6]), speed, arcs, 1./EARTH, EARTH)
        self.assertTrue(moving.all())
        self.assertEqual(kin._changes(signs.tolist(), False), 2)
        _, noise = kin.signed_motion(np.array([2e-11]), np.ones(1), np.array([50./EARTH]), 1./EARTH, EARTH)
        self.assertEqual(noise.tolist(), [0.])
        still, _ = kin.signed_motion(np.array([0.]), np.array([1e-3*kin._EPS]), np.ones(1), 1./EARTH, EARTH)
        self.assertEqual(still.tolist(), [False])

    def test_pure_sliding_on_a_tilted_great_circle_with_50_m_vertices_has_no_sign_changes(self):
        tilt = np.array([[1., 0., 0.], [0., math.cos(.5), -math.sin(.5)], [0., math.sin(.5), math.cos(.5)]])
        turn = np.array([[math.cos(.3), -math.sin(.3), 0.], [math.sin(.3), math.cos(.3), 0.], [0., 0., 1.]])
        rotation = turn @ tilt
        angles = np.arange(2001)*(50./EARTH)
        points = np.column_stack((np.cos(angles), np.sin(angles), np.zeros_like(angles))) @ rotation.T
        boundary = kin.BoundaryLine('north', 'south', points, False)
        report, _ = kin.measure([boundary], {'north': [0., 0., 0.], 'south': (rotation @ [0., 0., 1e-15]).tolist()},
                                EARTH, kin.protocol((25e3,)))
        for profile in [report['native']] + report['scales']:
            self.assertEqual(profile['sign_changes'], dict(normal_component=0, dominated_class=0))
            self.assertEqual(profile['length_share']['shear_dominated'], 1.)


class ProtocolAndInputTests(unittest.TestCase):
    def test_registered_scales_and_protocol_identity(self):
        from atlas_tectonics.plate_reference_acceptance import OBSERVATION_SCALES_M
        self.assertEqual(kin.DEFAULT_SPACINGS_M, OBSERVATION_SCALES_M)
        self.assertEqual(kin.protocol()['protocol_id'], kin.protocol()['protocol_id'])
        self.assertNotEqual(kin.protocol()['protocol_id'], kin.protocol(shear_obliquity_deg=60.)['protocol_id'])
        for spacings, threshold in (((), 70.), ((250e3, 100e3), 70.), ((100e3,), 90.), ((0.,), 70.)):
            with self.assertRaises(kin.BoundaryAssessmentError):
                kin.protocol(spacings, threshold)

    def test_invalid_numbers_and_tiny_spacings_are_controlled_refusals(self):
        for spacings, threshold in ((None, 70.), (('100000',), 70.), ((True,), 70.),
                                   ((100e3,), None), ((100e3,), True), ((10**1000,), 70.)):
            with self.subTest(spacings=spacings, threshold=threshold), self.assertRaises(kin.BoundaryAssessmentError):
                kin.protocol(spacings, threshold)
        with self.assertRaisesRegex(kin.BoundaryAssessmentError, 'too fine'):
            measure([line([(0., 0.), (1., 0.)])], (0., 1e-15, 0.), (1e-310,))

    def test_measure_refuses_protocol_fields_changed_without_a_new_identity(self):
        proto = kin.protocol()
        proto['spacings_m'] = [200e3]
        with self.assertRaisesRegex(kin.BoundaryAssessmentError, 'protocol'):
            kin.measure([line([(0., 0.), (1., 0.)])],
                        {'north': [0., 0., 0.], 'south': [0., 1e-15, 0.]}, EARTH, proto)

    def test_descriptive_cdf_gap_has_analytical_limits(self):
        self.assertEqual(kin._gap(np.array([0., 1.]), np.array([0., 1.])), 0.)
        self.assertEqual(kin._gap(np.array([0., 1.]), np.array([2., 3.])), 1.)
        self.assertEqual(kin._gap(np.array([0., 0., 1., 1.]), np.array([0., 1.])), 0.)

    def test_neutral_input_refusals(self):
        good = dict(schema=kin.INPUT_SCHEMA, radius_m=EARTH, angular_velocities_rad_s={'a': [0, 0, 0], 'b': [0, 0, 1e-15]},
                    boundaries=[dict(left='a', right='b', points=[lonlat(0, 0), lonlat(10, 0)])])
        kin.input_lines(good)
        for change in (dict(schema='other'), dict(extra=1), dict(radius_m=-1.),
                       dict(radius_m=True), dict(radius_m=10**1000),
                       dict(angular_velocities_rad_s={'a': [0, 0, 0], 'b': [10**1000, 0, 0]}),
                       dict(boundaries=[dict(left=['a'], right='b', points=[lonlat(0, 0), lonlat(1, 0)])]),
                       dict(boundaries=[dict(left='a', right='a', points=[lonlat(0, 0), lonlat(1, 0)])]),
                       dict(boundaries=[dict(left='a', right='c', points=[lonlat(0, 0), lonlat(1, 0)])]),
                       dict(boundaries=[dict(left='a', right='b', points=[[2., 0., 0.], lonlat(1, 0)])]),
                       dict(boundaries=[dict(left='a', right='b', points=[lonlat(0, 0), lonlat(0, 0)])])):
            with self.subTest(change=change), self.assertRaises(kin.BoundaryAssessmentError):
                kin.input_lines(dict(good, **change))
        with tempfile.TemporaryDirectory() as tmp:
            for text in ('{"schema": 1, "schema": 2}', '{"radius_m": NaN}', '\xff'):
                path = Path(tmp)/'bad.json'
                path.write_bytes(text.encode('latin-1'))
                with self.subTest(text=text), self.assertRaises(kin.BoundaryAssessmentError):
                    kin.input_source(path, kin.protocol())

    def test_input_byte_limit_applies_to_read_and_utf16_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'input.json'
            path.write_bytes(b' '*33)
            with mock.patch.object(kin, 'MAX_INPUT_BYTES', 32), \
                    mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('Unbounded read')), \
                    self.assertRaisesRegex(kin.BoundaryAssessmentError, 'bounded size'):
                kin._read_input(path)
            path.write_bytes('{"schema": "test"}'.encode('utf-16'))
            with self.assertRaisesRegex(kin.BoundaryAssessmentError, 'UTF-8'):
                kin._read_input(path)


class PB2002Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan, cls.dataset, cls.lines, cls.roles, cls.angular = kin.pb2002_lines(DATA)

    def test_chord_motion_reproduces_step_motion_for_every_step(self):
        from atlas_tectonics.plate_reference_dataset import lonlat_vectors, step_motion
        poles = {p.plate_id: p for p in self.dataset.poles}
        scale = 1000.*kin.YEAR_S
        for step in self.dataset.steps:
            expected = step_motion(step, poles)
            middle, left, tangent, _ = kin._chords(np.asarray(lonlat_vectors([step.start, step.end])), False)
            delta = np.subtract(self.angular[step.boundary[3:]], self.angular[step.boundary[:2]])
            normal, along, speed = kin.chord_motion(middle, left, tangent, delta, EARTH)
            self.assertAlmostEqual(normal[0]*scale, expected['opening_mm_a'], delta=1e-9)
            self.assertAlmostEqual(-along[0]*scale, expected['right_lateral_mm_a'], delta=1e-9)
            self.assertAlmostEqual(speed[0]*scale, expected['speed_mm_a'], delta=1e-9)

    def test_registered_splits_partition_the_whole_inventory(self):
        from atlas_tectonics.plate_reference_acceptance import WITHHELD_MORPHOLOGY_PLATES
        reserved = set(WITHHELD_MORPHOLOGY_PLATES)
        steps = sum(len(l.points)-1 for l in self.lines)
        self.assertEqual(steps, len(self.dataset.steps))
        for boundary in self.lines:
            self.assertEqual(self.roles[boundary] == 'withheld', bool({boundary.left, boundary.right} & reserved))
        length = sum(float(np.sum(kin._arc(l.points[:-1], l.points[1:]))) for l in self.lines)*EARTH/1000.
        self.assertAlmostEqual(length, sum(s.length_km for s in self.dataset.steps), delta=10.)

    def test_withheld_split_needs_a_named_run_and_is_labelled_validation(self):
        with self.assertRaises(kin.BoundaryAssessmentError):
            kin.assess(reference='withheld', pb2002_directory=DATA)
        proto = kin.protocol((500e3,))
        cached = mock.patch.object(kin, 'pb2002_lines', return_value=(
            self.plan, self.dataset, self.lines, self.roles, self.angular))
        with cached:
            development, _, _ = kin.pb2002_source(DATA, 'development', 'unit-development', proto)
        self.assertEqual(development['audit']['purpose'], 'calibration')
        self.assertEqual(development['identity']['split'], 'development')
        self.assertFalse(development['audit']['geological_model_accepted'])
        # Selection and audit only: no withheld statistic is computed by this test.
        from atlas_tectonics.plate_reference_acceptance import WITHHELD_MORPHOLOGY_PLATES
        seen = []
        def record(lines, *args):
            seen.extend(lines)
            return dict(boundary_lines=len(lines)), []
        with cached, mock.patch.object(kin, 'measure', side_effect=record):
            withheld, _, _ = kin.pb2002_source(DATA, 'withheld', 'unit-withheld-selection', proto)
        self.assertEqual(withheld['audit']['purpose'], 'validation')
        self.assertEqual(withheld['identity']['split'], 'withheld')
        self.assertTrue(seen)
        self.assertTrue(all({l.left, l.right} & set(WITHHELD_MORPHOLOGY_PLATES) for l in seen))


class SavedWorldTests(unittest.TestCase):
    """One small generated world, saved and reopened like any user project."""
    @classmethod
    def setUpClass(cls):
        from test_new_world_structure import plan
        from new_world_layout import generate_layout_candidate
        from new_world_structure import generate_structure
        from new_world_motion import generate_motion
        from new_world_project import save_project
        cls.plan = plan(seed=41)
        cls.candidate = generate_layout_candidate(cls.plan)
        if cls.candidate.atlas is None:
            raise AssertionError('The fixed N6/support192/seed41 layout refused.')
        cls.structure = generate_structure(cls.plan)
        cls.motion = generate_motion(cls.plan, cls.candidate, cls.structure)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name)/'world.atlas'
        save_project(cls.path, cls.plan, cls.candidate, title='Boundary fixture',
                     structure=cls.structure, motion=cls.motion)
        cls.proto = kin.protocol()
        cls.source, _, cls.motion_id, (cls.lines, cls.angular, cls.radius) = kin.project_source(cls.path, cls.proto)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_lines_cover_each_interplate_edge_once_with_true_sides(self):
        atlas = self.candidate.atlas
        vertices, edges = atlas.vertex_directions, atlas.edge_vertices
        expected = math.fsum(float(kin._arc(*vertices[edges[i]])) for i in atlas.interplate_edges)
        actual = math.fsum(float(np.sum(kin._arc(l.points[:-1], l.points[1:]))) for l in self.lines)
        self.assertAlmostEqual(actual, expected, places=12)
        self.assertEqual(sum(len(l.points)-1 for l in self.lines), len(atlas.interplate_edges))
        probes, owners = [], []
        for boundary in self.lines:
            middle, left, _, _ = kin._chords(boundary.points, False)
            for side, owner in ((1e-4, boundary.left), (-1e-4, boundary.right)):
                probes.extend(kin._normalise(middle+side*left)); owners.extend([owner]*len(middle))
        with atlas.index() as index:
            hits = index.query(np.asarray(probes))
        found = {}
        for point, owner in hits.pairs:
            found.setdefault(int(point), set()).add(hits.owner_ids[int(owner)])
        self.assertEqual([found.get(i) for i in range(len(probes))], [{o} for o in owners])

    def test_normal_component_matches_saved_motion_segments(self):
        record = self.motion.descriptor()
        atlas = self.candidate.atlas
        for segment in record['segments']:
            a, b = atlas.vertex_directions[atlas.edge_vertices[segment['edge_index']]]
            left = kin._normalise(np.cross(a, b))
            position = np.asarray(segment['position'])
            tangent = np.cross(left, position)
            delta = np.subtract(self.angular[segment['right_plate']], self.angular[segment['left_plate']])
            normal, _, speed = kin.chord_motion(position, left, tangent, delta, self.radius)
            self.assertAlmostEqual(float(normal), segment['opening_midpoint_m_s'], delta=1e-12*max(float(speed), 1e-30))

    def test_neutral_export_round_trip_and_reports_carry_no_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'boundaries.json'
            path.write_text(json.dumps(kin.export_input(self.lines, self.angular, self.radius)),
                            encoding='utf-8', newline='\n')
            reopened, _, _ = kin.input_source(path, self.proto)
        for key in ('native', 'scales', 'boundary_lines', 'boundary_length_km'):
            self.assertEqual(reopened[key], self.source[key], key)
        first = kin.assess(projects=[self.path], reference='none')
        again = kin.assess(projects=[self.path], reference='none')
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(again, sort_keys=True))

        def strings(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield key
                    yield from strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)
            elif isinstance(value, str):
                yield value
        # Walk decoded strings: JSON would escape a Windows path's backslashes.
        folder = str(Path(self.tmp.name))
        self.assertFalse([s for s in strings(first) if folder in s or Path(folder).name in s])
        self.assertEqual(first['sources'][0]['identity']['motion_id'], self.motion.motion_id)
        self.assertEqual(first['runtime']['numpy_version'], np.__version__)
        self.assertEqual(first['runtime']['python_version'], sys.version.split()[0])
        scale = first['sources'][0]['scales']
        edge = first['sources'][0]['native']['edge_length_km']['quantiles'][3]*1000.
        self.assertEqual([s['finer_than_native_median_edge'] for s in scale],
                         [s['spacing_m'] < edge for s in scale])

    def test_cli_writes_a_new_lf_report_and_refuses_overwrite_or_unnamed_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp)/'report.json'
            self.assertEqual(kin.main(['--project', str(self.path), '--reference', 'none', '--report', str(report)]), 0)
            raw = report.read_bytes()
            self.assertNotIn(b'\r', raw)
            self.assertEqual(json.loads(raw)['sources'][0]['identity']['motion_id'], self.motion.motion_id)
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit):
                kin.main(['--project', str(self.path), '--reference', 'none', '--report', str(report)])
            self.assertIn('new file', errors.getvalue())
            self.assertEqual(report.read_bytes(), raw)
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                code = kin.main(['--project', str(self.path), '--reference', 'withheld',
                                 '--report', str(Path(tmp)/'other.json')])
            self.assertEqual(code, 2)
            self.assertIn('explicit named run', errors.getvalue())
            self.assertFalse((Path(tmp)/'other.json').exists())

    def test_cli_stdout_is_lf_and_expected_failures_are_refusals_not_tracebacks(self):
        stream = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
        with mock.patch('sys.stdout', stream):
            self.assertEqual(kin.main(['--project', str(self.path), '--reference', 'none']), 0)
        raw = stream.buffer.getvalue()
        self.assertNotIn(b'\r', raw)
        self.assertEqual(json.loads(raw)['sources'][0]['identity']['motion_id'], self.motion.motion_id)
        refuse = mock.patch.object(kin, 'pb2002_lines', side_effect=AssertionError('PB2002 must not load'))
        for arguments, fragment in (
                (['--project', str(Path(self.tmp.name)/'missing.atlas'), '--reference', 'none'], 'REFUSED'),
                (['--project', str(self.path), '--run-id', 'x'*300], 'run name')):
            errors = io.StringIO()
            with self.subTest(arguments=arguments[-1]), refuse, contextlib.redirect_stderr(errors):
                self.assertEqual(kin.main(arguments), 2)
                self.assertIn(fragment, errors.getvalue())
                self.assertNotIn('Traceback', errors.getvalue())


if __name__ == '__main__':
    unittest.main()
