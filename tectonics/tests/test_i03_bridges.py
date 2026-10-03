"""I03.3 spatial bridges between the shared spherical network and a regional domain. WORKING NON-CANON.

Every value comes from cases/i03_controls_v3.json. The ProjectionTests use the R3-5 criteria of the I03b bounds
proposal, approved by the coordinator on 3 October 2026.
SPDX-License-Identifier: AGPL-3.0-only
"""
import dataclasses
from fractions import Fraction
import json
import math
from pathlib import Path
import tempfile
import time
import unittest
import warnings

import numpy as np

import i03_fixtures as F
from atlas_tectonics import integration_bridges as B, integration_sphere as S, integration_transfer as T

CASE3 = json.loads((F.CASES/'i03_controls_v3.json').read_text(encoding='utf-8'))
MYR = F.MYR_S
ANGULAR = F.tolerance('angular_absolute_rad')


def control(name):
    return CASE3['controls'][name]


def footprint(rule, representation='3d', azimuth_deg=None, region='region', faces=None, tolerance=None):
    lon, lat = rule['centre_lon_lat_deg']
    top, bottom = control('bridge_identity')['depth_m']
    return B.Footprint(region, tuple(faces or rule['footprint_faces']), math.radians(lon), math.radians(lat),
                       math.radians(rule.get('azimuth_deg', 0.) if azimuth_deg is None else azimuth_deg), top, bottom,
                       representation, tolerance)


def unchanged(extract):
    return B.RegionalResult(extract.extract_id, extract.footprint.representation, dict(extract.pieces))


def cohort_totals(state, faces):
    """{cohort: exact total of each column} over ``faces``."""
    material, out = state.material, {}
    for row in range(len(material.piece_face)):
        if state.network.face_ids[int(material.piece_face[row])] in faces:
            name = material.cohorts[int(material.piece_cohort[row])].cohort_id
            values = out.setdefault(name, [Fraction(0)]*len(material.columns))
            for k, value in enumerate(material.stock[row]):
                values[k] += Fraction(float(value))
    return out


def outside_bytes(state, faces):
    material = state.material
    keep = [row for row in range(len(material.piece_face))
            if state.network.face_ids[int(material.piece_face[row])] not in faces]
    return material.stock[keep].tobytes(), material.piece_face[keep].tobytes(), material.piece_cohort[keep].tobytes()


class IdentityTests(unittest.TestCase):
    def test_extract_then_return_unchanged_is_the_identity(self):
        rule = control('bridge_identity')
        state = F.crust(F.three_plates())
        extract = B.extract(state, footprint(rule))
        self.assertIs(B.returned(state, [(extract, unchanged(extract))]), state)
        self.assertEqual(extract.parent_state_id, state.state_id)
        self.assertEqual(set(extract.unknown), {'forces_n', 'work_j'})
        self.assertIsNone(extract.face_point_velocity_m_s)                   # no motion given: unknown, not zero
        self.assertIsNone(extract.angular_velocity_rad_s)
        for name in rule['footprint_faces']:
            index = state.network.face_ids.index(name)
            self.assertEqual(extract.area_m2[name], float(state.network.face_area_m2[index]))


class RedistributionTests(unittest.TestCase):
    def test_a_regional_redistribution_conserves_every_account_and_leaves_the_exterior(self):
        rule = control('bridge_redistribution')
        state = F.crust(F.three_plates())
        extract = B.extract(state, footprint(rule))
        first, second = rule['footprint_faces']
        (a, row_a), = extract.pieces[first]
        (b, row_b), = extract.pieces[second]
        half = lambda row: tuple(value/2 for value in row)
        pieces = {first: ((a, half(row_a)), (b, half(row_b))), second: ((a, half(row_a)), (b, half(row_b)))}
        after = B.returned(state, [(extract, B.RegionalResult(extract.extract_id, '3d', pieces))])
        self.assertIsNot(after, state)
        self.assertEqual(after.parent_state_id, state.state_id)
        self.assertEqual(after.network.network_id, state.network.network_id)
        for column in state.material.columns:
            self.assertEqual(after.material.exact_total(column), state.material.exact_total(column))
        self.assertEqual(after.material.supplied(), state.material.supplied())
        self.assertTrue(after.material.closure()['identity_exact'])
        self.assertEqual(outside_bytes(after, (first, second)), outside_bytes(state, (first, second)))
        self.assertEqual(sorted(after.material.face_cohorts(first)), sorted((a, b)))
        self.assertEqual(cohort_totals(after, (first, second)), cohort_totals(state, (first, second)))   # B1
        S.verified(after)


class FullVectorTests(unittest.TestCase):
    def test_full_velocity_vectors_whatever_the_orientation(self):
        rule, ident = control('bridge_full_vector'), control('bridge_identity')
        state = F.crust(F.three_plates())
        motion = F.one_plate_motion(rule['turn_deg'])
        duration = rule['duration_myr']*MYR
        seen = None
        for azimuth in rule['azimuths_deg']:
            with self.subTest(azimuth=azimuth):
                extract = B.extract(state, footprint(ident, azimuth_deg=azimuth), motion, duration)
                vectors = {name: np.array(v) for name, v in extract.face_point_velocity_m_s.items()}
                if seen is None:
                    seen = {name: v.tobytes() for name, v in vectors.items()}
                self.assertEqual({name: v.tobytes() for name, v in vectors.items()}, seen)
                basis = np.frombuffer(extract.frame._basis).reshape(3, 3)
                omega = np.asarray(T._vector(dict(motion.rotations)['A']))/duration
                self.assertEqual(np.array(extract.angular_velocity_rad_s['A']).tobytes(), omega.tobytes())
                for name, vector in vectors.items():
                    local = np.array(extract.face_point_velocity_local_m_s[name])
                    speed = float(np.linalg.norm(vector))
                    self.assertGreater(speed, 0.)
                    self.assertLessEqual(float(np.linalg.norm(basis @ local-vector)), ANGULAR*speed)
                    # The point is the face's declared reference point: the normalised mean of its vertex directions.
                    point = np.array(extract.face_point[name])
                    index = state.network.face_ids.index(name)
                    ring = state.network.vertex_direction[[state.network.vertex_ids.index(v)
                                                           for v in state.network.faces[index].vertex_ids]]
                    mean = ring.sum(axis=0)
                    self.assertLessEqual(float(np.linalg.norm(point-mean/np.linalg.norm(mean))), ANGULAR)
                    radius = state.network.sphere.radius_m
                    self.assertLessEqual(float(np.linalg.norm(vector-np.cross(omega, point*radius))), ANGULAR*speed)
                    self.assertLessEqual(abs(float(local[2])), ANGULAR*speed)     # no radial motion in a rotation
                for (vertex, plate), vector in extract.vertex_velocity_m_s.items():
                    self.assertEqual(plate, 'A')
                    self.assertEqual(len(vector), 3)


class RefusalTests(unittest.TestCase):
    def setUp(self):
        self.rule = control('bridge_identity')
        self.state = F.crust(F.three_plates())

    def test_two_regions_owning_one_face_are_refused(self):
        one = B.extract(self.state, footprint(self.rule, region='east'))
        two = B.extract(self.state, footprint(self.rule, region='west', faces=(self.rule['footprint_faces'][0], 's03-b00')))
        with self.assertRaises(B.BridgeRefused) as caught:
            B.returned(self.state, [(one, unchanged(one)), (two, unchanged(two))])
        self.assertEqual(caught.exception.code, B.UNRESOLVED_OVERLAP)

    def test_a_result_for_a_state_that_has_moved_on_is_refused(self):
        extract = B.extract(self.state, footprint(self.rule))
        later = T.advance(self.state, F.one_plate_motion(.5), end_time_s=MYR).state
        with self.assertRaises(B.BridgeRefused) as caught:
            B.returned(later, [(extract, unchanged(extract))])
        self.assertEqual(caught.exception.code, B.STALE_GEOMETRY)

    def test_a_result_of_another_representation_is_refused(self):
        extract = B.extract(self.state, footprint(self.rule))
        with self.assertRaises(B.BridgeRefused) as caught:
            B.returned(self.state, [(extract, B.RegionalResult(extract.extract_id, 'map', dict(extract.pieces)))])
        self.assertEqual(caught.exception.code, B.OMITTED_DIMENSION)

    def test_a_result_that_does_not_conserve_is_refused(self):
        extract = B.extract(self.state, footprint(self.rule))
        name = self.rule['footprint_faces'][0]
        (cohort, row), = extract.pieces[name]
        pieces = dict(extract.pieces)
        pieces[name] = ((cohort, (row[0], row[1]*(1+1e-9))+tuple(row[2:])),)
        with self.assertRaises(B.BridgeRefused) as caught:
            B.returned(self.state, [(extract, B.RegionalResult(extract.extract_id, '3d', pieces))])
        self.assertEqual(caught.exception.code, B.INCOMPATIBLE_SUPPORT)
        self.assertIn('does not return its', str(caught.exception))         # the account check, before the cohort one

    def test_a_footprint_of_unknown_faces_is_refused(self):
        with self.assertRaises(B.BridgeRefused) as caught:
            B.extract(self.state, footprint(self.rule, faces=('no-such-face',)))
        self.assertEqual(caught.exception.code, B.INCOMPATIBLE_SUPPORT)


class HardeningTests(unittest.TestCase):
    # The I03.3 verifier's findings F2-F7 (3 October 2026), each a refusal that must hold.
    def setUp(self):
        self.rule = control('bridge_identity')
        self.state = F.crust(F.three_plates())

    def test_an_extract_is_issued_only_and_read_only(self):
        extract = B.extract(self.state, footprint(self.rule))
        with self.assertRaises(TypeError):
            dataclasses.replace(extract, parent_state_id='0'*64)
        with self.assertRaises(TypeError):
            B.RegionalExtract('x'*64, self.state.state_id)
        with self.assertRaises(AttributeError):
            extract.parent_state_id = '0'*64
        with self.assertRaises(TypeError):
            extract.pieces['s03-b01'] = ()
        with self.assertRaises(TypeError):
            extract.projection['omitted'] = []

    def test_an_altered_extract_is_refused_on_return(self):
        extract = B.extract(self.state, footprint(self.rule))
        later = T.advance(self.state, F.one_plate_motion(.5), end_time_s=MYR).state
        object.__setattr__(extract, 'parent_state_id', later.state_id)      # past the read-only guard
        object.__setattr__(extract, 'material_id', later.material.material_id)
        with self.assertRaises(B.BridgeRefused) as caught:
            B.returned(later, [(extract, unchanged(extract))])
        self.assertEqual(caught.exception.code, B.STALE_GEOMETRY)
        # Altered only in what its identity binds beyond the state: the interval it was read for.
        moving = B.extract(self.state, footprint(self.rule), F.one_plate_motion(.5), MYR)
        object.__setattr__(moving, 'duration_s', 2*MYR)
        with self.assertRaises(B.BridgeRefused) as caught:
            B.returned(self.state, [(moving, unchanged(moving))])
        self.assertEqual(caught.exception.code, B.STALE_GEOMETRY)

    def test_velocities_must_be_finite(self):
        motion = F.one_plate_motion(.5)
        for duration in (5e-324, float('inf')):
            with self.subTest(duration=duration), self.assertRaises(B.BridgeRefused):
                B.extract(self.state, footprint(self.rule), motion, duration)
        with warnings.catch_warnings():                 # the refusal holds whatever the process's warning policy
            warnings.simplefilter('error', RuntimeWarning)
            with self.assertRaises(B.BridgeRefused):
                B.extract(self.state, footprint(self.rule), motion, 5e-324)

    def test_a_motion_for_another_interval_is_refused(self):
        with self.assertRaises(B.BridgeRefused) as caught:
            B.extract(self.state, footprint(self.rule), F.one_plate_motion(.5, step=7), MYR)
        self.assertEqual(caught.exception.code, B.STALE_GEOMETRY)

    def test_negative_or_unsupported_amounts_are_incompatible_support(self):
        extract = B.extract(self.state, footprint(self.rule))
        name = self.rule['footprint_faces'][0]
        (cohort, row), = extract.pieces[name]
        columns = extract.columns
        mass = next(k for k, c in enumerate(columns) if c.startswith('mass_kg:'))
        area = columns.index('area_m2')
        other = [c.cohort_id for c in self.state.material.cohorts if c.cohort_id != cohort][0]
        # Half the area each: one piece holds twice the mass and the other a negative mass, so every total is kept.
        doubled = tuple(2*v if k == mass else v/2 for k, v in enumerate(row))
        negative = tuple(-v if k == mass else v/2 for k, v in enumerate(row))
        half = tuple(v/2 if k == mass else v for k, v in enumerate(row))
        massless_area = tuple(v/2 if k == mass else 0. for k, v in enumerate(row))
        for rows in (((cohort, doubled), (other, negative)), ((cohort, half), (other, massless_area))):
            pieces = dict(extract.pieces)
            pieces[name] = rows
            with self.subTest(rows=rows), self.assertRaises(B.BridgeRefused) as caught:
                B.returned(self.state, [(extract, B.RegionalResult(extract.extract_id, '3d', pieces))])
            self.assertEqual(caught.exception.code, B.INCOMPATIBLE_SUPPORT)
        # The cohort's amounts kept over the footprint, but its second face given a negative mass, or its mass without
        # area: only the sign checks see these (round 1).
        second = self.rule['footprint_faces'][1]
        (_, row2), = extract.pieces[second]
        k = row[mass]/4
        cases = {'a negative mass': ({name: ((cohort, tuple(v+row2[i]+k if i == mass else v for i, v in enumerate(row))),),
                                      second: ((cohort, tuple(-k if i == mass else v for i, v in enumerate(row2))),)}),
                 'material without area': ({name: ((cohort, tuple(v+row2[i] if i == area else v
                                                                   for i, v in enumerate(row))),),
                                            second: ((cohort, tuple(0. if i == area else v
                                                                    for i, v in enumerate(row2))),)})}
        for text, rows in cases.items():
            with self.subTest(case=text), self.assertRaises(B.BridgeRefused) as caught:
                B.returned(self.state, [(extract, B.RegionalResult(extract.extract_id, '3d', rows))])
            self.assertEqual(caught.exception.code, B.INCOMPATIBLE_SUPPORT)
            self.assertIn(text, str(caught.exception))

    def test_malformed_inputs_are_refused_not_raised(self):
        extract = B.extract(self.state, footprint(self.rule))
        name = self.rule['footprint_faces'][0]
        (cohort, row), = extract.pieces[name]
        bad = (dict(extract.pieces, **{name: ((['a list'], row),)}), {**dict(extract.pieces), 7: ()})
        for pieces in bad:
            with self.subTest(pieces=list(pieces)), self.assertRaises(B.BridgeRefused):
                B.returned(self.state, [(extract, B.RegionalResult(extract.extract_id, '3d', pieces))])
        lon, lat = self.rule['centre_lon_lat_deg']
        for azimuth, tolerance, representation in ((float('nan'), None, '3d'), (0., True, 'map')):
            with self.subTest(azimuth=azimuth), self.assertRaises(B.BridgeRefused):
                B.Footprint('r', tuple(self.rule['footprint_faces']), math.radians(lon), math.radians(lat),
                            azimuth, 0., 1., representation, tolerance)
        with self.assertRaises(B.BridgeRefused):
            B.extract(self.state, footprint(self.rule), F.one_plate_motion(.5), True)

    def test_a_return_cannot_relabel_material_into_another_cohort(self):
        # B1 (coordinator, round 1): every cohort keeps its exact amounts over the footprint; a cohort change would
        # need a named, booked transformation, which is not built.
        state = T.advance(self.state, F.one_plate_motion(.5), end_time_s=MYR).state
        name = 's03-b01'
        extract = B.extract(state, footprint(self.rule, faces=(name,)))
        (cohort, row), = extract.pieces[name]
        born = [c.cohort_id for c in state.material.cohorts if c.formation_start_s is not None][0]
        for target in (born, 'inherited-B'):
            with self.subTest(target=target), self.assertRaises(B.BridgeRefused) as caught:
                B.returned(state, [(extract, B.RegionalResult(extract.extract_id, '3d', {name: ((target, row),)}))])
            self.assertEqual(caught.exception.code, B.INCOMPATIBLE_SUPPORT)
            self.assertIn('cohort', str(caught.exception))

    def test_one_region_is_returned_once(self):
        one = B.extract(self.state, footprint(self.rule, faces=('s03-b01',)))
        two = B.extract(self.state, footprint(self.rule, faces=('s03-b02',)))
        with self.assertRaises(B.BridgeRefused) as caught:
            B.returned(self.state, [(one, unchanged(one)), (two, unchanged(two))])
        self.assertEqual(caught.exception.code, B.UNRESOLVED_OVERLAP)


class ProjectionTests(unittest.TestCase):
    # R3-5 (bounds proposal of 3 October 2026, approved the same day).
    def setUp(self):
        self.rule, self.state = control('bridge_projection'), F.crust(F.three_plates())
        self.ident = control('bridge_identity')

    def test_a_map_is_admitted_only_within_its_declared_distortion(self):
        with self.assertRaises(B.BridgeRefused) as caught:
            B.extract(self.state, footprint(self.ident, 'map', tolerance=self.rule['map_tolerance_small']))
        self.assertEqual(caught.exception.code, B.PROJECTION_INVALID)
        with self.assertRaises(B.BridgeRefused) as caught:
            B.extract(self.state, footprint(self.ident, 'map', tolerance=self.rule['map_tolerance_large']))
        self.assertEqual(caught.exception.code, B.PROJECTION_INVALID)
        extract = B.extract(self.state, footprint(self.ident, 'map', tolerance=self.rule['map_tolerance_admitting']))
        rho = extract.projection['rho_max_rad']
        self.assertEqual(tuple(extract.projection['omitted']), ('up',))
        self.assertAlmostEqual(extract.projection['relative_distortion'], 1-math.cos(rho), delta=1e-15)
        self.assertLessEqual(extract.projection['relative_distortion'], self.rule['map_tolerance_admitting'])
        self.assertIsNone(B.extract(self.state, footprint(self.ident, 'section', faces=('s03-b01',)),
                                    F.one_plate_motion(.5), MYR).projected_area_m2)

    def test_a_footprint_beyond_the_conditioned_chart_is_refused(self):
        faces = ('s03-b01', 's00-b01')                                      # 150 degrees apart in longitude
        with self.assertRaises(B.BridgeRefused) as caught:
            B.extract(self.state, footprint(self.ident, faces=faces))
        self.assertEqual(caught.exception.code, B.PROJECTION_INVALID)

    def test_a_section_drops_no_motion(self):
        motion, duration = F.one_plate_motion(.5), MYR
        # Plate A turns about the world axis: at the equator its motion runs east, along an azimuth of 0.
        along = B.extract(self.state, footprint(self.ident, 'section', azimuth_deg=0., faces=('s03-b01',)), motion,
                          duration)
        self.assertEqual(tuple(along.projection['omitted']), ('across-section',))
        with self.assertRaises(B.BridgeRefused) as caught:
            B.extract(self.state, footprint(self.ident, 'section', azimuth_deg=90., faces=('s03-b01',)), motion,
                      duration)
        self.assertEqual(caught.exception.code, B.OMITTED_DIMENSION)


def holed_world():
    """An octahedron whose octant o+++ holds a triangular island, 'isle', in a hole (the coordinator's p5)."""
    unit = lambda v: tuple(float(x) for x in np.asarray(v, float)/np.linalg.norm(v))
    vertices = {'+x': (1., 0., 0.), '-x': (-1., 0., 0.), '+y': (0., 1., 0.), '-y': (0., -1., 0.), '+z': (0., 0., 1.),
                '-z': (0., 0., -1.)}
    centre = np.array((1., 1., 1.))/math.sqrt(3)
    u = np.cross(centre, (0., 0., 1.))
    u /= np.linalg.norm(u)
    w = np.cross(centre, u)
    for k, t in enumerate((0., 2*math.pi/3, 4*math.pi/3)):
        vertices['h%d' % k] = unit(centre+.35*(math.cos(t)*u+math.sin(t)*w))
    rings = {'o+++': ('+x', '+y', '+z'), 'o-++': ('+y', '-x', '+z'), 'o--+': ('-x', '-y', '+z'),
             'o+-+': ('-y', '+x', '+z'), 'o++-': ('+y', '+x', '-z'), 'o-+-': ('-x', '+y', '-z'),
             'o---': ('-y', '-x', '-z'), 'o+--': ('+x', '-y', '-z')}
    owner = lambda name: 'north' if name.endswith('+') else 'south'
    faces = [S.Face(name, owner(name), ring, (('h2', 'h1', 'h0'),) if name == 'o+++' else ())
             for name, ring in rings.items()]
    faces.append(S.Face('isle', 'north', ('h0', 'h1', 'h2')))
    network = S.build_network(F.sphere(), vertices, tuple(faces), (S.Plate('north', F.IDENTITY),
                                                                    S.Plate('south', F.IDENTITY)),
                              (S.Boundary('equator', S.TRANSFORM, 'north', 'south', ('+x', '+y', '-x', '-y'),
                                          F.origin(), closed=True),), epoch_id=F.EPOCH, time_s=F.START)
    return F.crust(network, cohort_of=lambda face: 'inherited', exteriors=()), centre


class ShapeTests(unittest.TestCase):
    # Round 1 (coordinator's minor items): plan areas without holes, positions, and what a map omits.
    def test_a_holed_face_hands_over_its_plan_area_without_its_hole(self):
        state, centre = holed_world()
        lon, lat = math.atan2(centre[1], centre[0]), math.asin(centre[2])
        both = B.extract(state, B.Footprint('r', ('isle', 'o+++'), lon, lat, 0., 0., 1e4, '3d'))
        outer = B.extract(state, B.Footprint('r', ('o+++',), lon, lat, 0., 0., 1e4, '3d'))
        isle = B.extract(state, B.Footprint('r', ('isle',), lon, lat, 0., 0., 1e4, '3d'))
        # The octant's plan area plus the island's is the plan area of the whole octant triangle, hole and all.
        rings = outer.rings_local_m['o+++']
        whole = B._planar_area(np.asarray(rings[0]))
        self.assertLessEqual(abs(outer.projected_area_m2['o+++']+isle.projected_area_m2['isle']-whole), 1e-9*whole)
        self.assertLess(sum(both.projected_area_m2.values()), sum(both.area_m2.values()))

    def test_positions_are_handed_over_in_the_local_frame(self):
        state = F.crust(F.three_plates())
        extract = B.extract(state, footprint(control('bridge_identity')))
        basis = np.frombuffer(extract.frame._basis).reshape(3, 3)
        radius = state.network.sphere.radius_m
        for name in extract.footprint.face_ids:
            k = state.network.face_ids.index(name)
            self.assertEqual(extract.ring_vertex_ids[name][0], state.network.faces[k].vertex_ids)
            for vertex, (x, y, z) in zip(extract.ring_vertex_ids[name][0], extract.rings_local_m[name][0]):
                direction = state.network.vertex_direction[state.network.vertex_ids.index(vertex)]
                self.assertLessEqual(float(np.linalg.norm(basis @ np.array((x, y, z+radius))-direction*radius)),
                                     ANGULAR*radius)
                self.assertLessEqual(z, 0.)                               # the surface lies below its tangent plane

    def test_a_map_reports_its_area_distortion_and_the_motion_it_omits(self):
        state = F.crust(F.three_plates())
        motion = F.one_plate_motion(.5)
        fp = B.Footprint('m', ('s03-north',), math.radians(210.), math.radians(75.), 0., 0., 35000., 'map', .053)
        extract = B.extract(state, fp, motion, MYR)
        name = 's03-north'
        self.assertAlmostEqual(extract.projection['max_area_distortion'],
                               abs(1-extract.projected_area_m2[name]/extract.area_m2[name]), delta=1e-15)
        local = list(extract.vertex_velocity_local_m_s.values())+list(extract.face_point_velocity_local_m_s.values())
        share = max(abs(v[2])/math.hypot(*v) for v in local if math.hypot(*v) > 0)
        self.assertEqual(extract.omitted_velocity_share, share)
        self.assertGreater(share, .1)
        still = B.extract(state, footprint(control('bridge_identity')), motion, MYR)
        self.assertEqual(still.omitted_velocity_share, 0.)                       # '3d' omits nothing
        self.assertIsNone(B.extract(state, footprint(control('bridge_identity'))).omitted_velocity_share)


class EvolvedStateTests(unittest.TestCase):
    # Round 1 (coordinator's minor item): the bridge on a state that has moved, near a pole and in tilted axes.
    def test_extract_then_return_unchanged_is_the_identity_on_an_evolved_state(self):
        state = F.crust(F.three_plates())
        for k in range(2):
            state = T.advance(state, F.one_plate_motion(.5, step=k), end_time_s=(k+1)*MYR).state
        born = sorted(f.face_id for f in state.network.faces if f.face_id.startswith('boundary-m02|right|1|'))
        faces = tuple(born[1:3])+('s02-b01', 's02-b02')
        extract = B.extract(state, B.Footprint('r', faces, math.radians(121.), 0., 0., 0., 35000., '3d'))
        self.assertIs(B.returned(state, [(extract, unchanged(extract))]), state)
        self.assertGreater(len({cohort for rows in extract.pieces.values() for cohort, _ in rows}), 1)

    def test_full_vectors_near_the_pole_and_in_tilted_axes(self):
        for tilt, faces, centre in ((None, ('s03-north',), (210., 75.)), (F.TILT, ('s03-b01', 's03-b02'), None)):
            with self.subTest(tilted=tilt is not None):
                state = F.crust(F.three_plates(tilt=tilt))
                motion = F.one_plate_motion(.5, tilt=tilt)
                network = state.network
                if centre is None:
                    points = [S._mean_direction(network.face_coordinates(network.face_ids.index(f))[0]) for f in faces]
                    c = np.sum(points, axis=0)
                    c /= np.linalg.norm(c)
                    centre = (math.degrees(math.atan2(c[1], c[0])), math.degrees(math.asin(c[2])))
                for azimuth in (0., 77., 200.):
                    extract = B.extract(state, B.Footprint('r', faces, math.radians(centre[0]), math.radians(centre[1]),
                                                           math.radians(azimuth), 0., 35000., '3d'), motion, MYR)
                    omega = np.array(extract.angular_velocity_rad_s['A'])
                    basis = np.frombuffer(extract.frame._basis).reshape(3, 3)
                    for name in faces:
                        v = np.array(extract.face_point_velocity_m_s[name])
                        point = np.array(extract.face_point[name])*network.sphere.radius_m
                        speed = float(np.linalg.norm(v))
                        self.assertLessEqual(float(np.linalg.norm(v-np.cross(omega, point))), ANGULAR*speed)
                        local = np.array(extract.face_point_velocity_local_m_s[name])
                        self.assertLessEqual(float(np.linalg.norm(basis @ local-v)), ANGULAR*speed)


class ReturnRouteTests(unittest.TestCase):
    # B2 (coordinator, round 1): a regional return rides in the Motion of its interval and is applied at its end.
    def setUp(self):
        self.rule = control('bridge_return_commit')
        self.state = F.crust(F.three_plates())

    def carried(self, state, faces=None, relabel=False, rule=None, duration=MYR):
        motion = F.one_plate_motion(self.rule['turn_deg'], step=state.network.step)
        extract = B.extract(state, footprint(rule or self.rule, faces=faces), motion, duration)
        names = tuple(sorted(extract.pieces))
        if len(names) == 1:
            ((cohort, row),) = extract.pieces[names[0]]
            target = 'inherited-B' if relabel else cohort
            pieces = {names[0]: ((target, row),)}
        else:
            (a, row_a), = extract.pieces[names[0]]
            (b, row_b), = extract.pieces[names[1]]
            half = lambda row: tuple(v/2 for v in row)
            pieces = {name: ((a, half(row_a)), (b, half(row_b))) for name in names}
        return extract, B.carried(extract, B.RegionalResult(extract.extract_id, '3d', pieces))

    def test_a_return_commits_with_its_interval_and_restores(self):
        extract, carried = self.carried(self.state)
        step = T.advance(self.state, F.one_plate_motion(self.rule['turn_deg'], regional_returns=(carried,)),
                         end_time_s=MYR)
        after, faces = step.state, tuple(self.rule['footprint_faces'])
        for name in faces:
            self.assertEqual(sorted(after.material.face_cohorts(name)), ['inherited-A', 'inherited-C'])
        self.assertEqual(cohort_totals(after, faces), cohort_totals(self.state, faces))
        self.assertTrue(after.material.closure()['identity_exact'])
        self.assertEqual(step.record()['regional_returns'], [extract.extract_id])
        again = T.restored(self.state, {'sphere': step.record(), 'transfers': []}, step.arrays())
        self.assertEqual(again.state_id, after.state_id)
        plain = F.one_plate_motion(self.rule['turn_deg'])
        self.assertNotIn('regional_returns', plain._declared())
        self.assertNotIn('regional_returns', T.advance(self.state, plain, end_time_s=MYR).record())

    def refused(self, carried, code, state=None):
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state or self.state, F.one_plate_motion(self.rule['turn_deg'], regional_returns=(carried,)),
                      end_time_s=MYR)
        self.assertEqual(caught.exception.code, code, str(caught.exception))

    def test_a_return_for_a_face_the_interval_changed_is_refused(self):
        self.refused(self.carried(self.state, faces=('s03-b01',), rule=control('bridge_identity'))[1],
                     B.STALE_GEOMETRY)                                                       # cut at the trench

    def test_a_return_read_from_another_state_is_refused(self):
        later = T.advance(self.state, F.one_plate_motion(.5), end_time_s=MYR).state
        self.refused(self.carried(later)[1], B.STALE_GEOMETRY)

    def test_a_relabelled_return_is_refused_at_commit(self):
        self.refused(self.carried(self.state, faces=('s01-b01',), relabel=True)[1], B.INCOMPATIBLE_SUPPORT)

    def test_a_carried_return_round_trips_its_record(self):
        _, carried = self.carried(self.state)
        self.assertEqual(B.RegionalReturn.from_record(carried.record()), carried)


class JunctionHistoryBridgeTests(unittest.TestCase):
    def test_time_varying_history_is_not_silently_replaced_by_an_endpoint_rate(self):
        import test_i03_junction_paths as paths
        state, proposal = F.crust(paths.world()), paths.motion()
        name = 's03-b01'
        ring = state.network.face_coordinates(state.network.face_ids.index(name))[0]
        point = np.sum(ring, axis=0)
        point /= np.linalg.norm(point)
        fp = B.Footprint('r', (name,), math.atan2(point[1], point[0]), math.asin(point[2]),
                         0., 0., 35000., '3d')
        # Material-only reading remains valid. A velocity-bearing regional run needs the actual history.
        self.assertIsNone(B.extract(state, fp).angular_velocity_rad_s)
        with self.assertRaisesRegex(B.BridgeRefused, 'common-reference exponential histories') as caught:
            B.extract(state, fp, proposal, MYR)
        self.assertEqual(caught.exception.code, B.INCOMPATIBLE_SUPPORT)
        still = T.Motion(0, 1, {p: F.IDENTITY for p in state.network.plate_ids})
        extracted = B.extract(state, fp, still, MYR)
        record = B.carried(extracted, unchanged(extracted)).record()
        record['motion_id'] = proposal.motion_id
        record['extract_id'] = B._identity(state.state_id, fp, extracted.projection, proposal.motion_id, MYR)
        carrying = dataclasses.replace(proposal, regional_returns=(B.RegionalReturn.from_record(record),))
        with self.assertRaisesRegex(B.BridgeRefused, 'common-reference exponential histories') as caught:
            T.advance(state, carrying, end_time_s=MYR)
        self.assertEqual(caught.exception.code, B.INCOMPATIBLE_SUPPORT)


class ReturnBindingTests(unittest.TestCase):
    # Review F1/F2: the result's forcing and support must match the interval that commits it.
    def setUp(self):
        self.state = F.crust(F.three_plates())
        self.rule = control('bridge_return_commit')

    def test_a_committed_return_requires_explicit_motion_and_duration(self):
        extract = B.extract(self.state, footprint(self.rule))
        self.assertIs(B.returned(self.state, [(extract, unchanged(extract))]), self.state)
        with self.assertRaises(B.BridgeRefused) as caught:
            B.carried(extract, unchanged(extract))
        self.assertEqual(caught.exception.code, B.STALE_GEOMETRY)

    def test_a_return_cannot_commit_under_a_different_rotation_or_duration(self):
        extract, carried = ReturnRouteTests.carried(self, self.state)
        for degrees, end in ((self.rule['turn_deg'], 2*MYR), (2*self.rule['turn_deg'], MYR)):
            with self.subTest(degrees=degrees, end=end), self.assertRaises(B.BridgeRefused) as caught:
                T.advance(self.state, F.one_plate_motion(degrees, regional_returns=(carried,)), end_time_s=end)
            self.assertEqual(caught.exception.code, B.STALE_GEOMETRY)
            self.assertIn('different interval motion or duration', str(caught.exception))

    def test_forcing_identity_excludes_the_results_that_answer_it(self):
        motion = F.one_plate_motion(self.rule['turn_deg'])
        extracted = B.extract(self.state, footprint(self.rule), motion, MYR)
        carried = B.carried(extracted, unchanged(extracted))
        carrying = dataclasses.replace(motion, regional_returns=(carried,))
        again = B.extract(self.state, footprint(self.rule), carrying, MYR)
        self.assertNotEqual(carrying.motion_id, motion.motion_id)
        self.assertEqual(again.motion_id, motion.motion_id)
        self.assertEqual(again.extract_id, extracted.extract_id)

    def test_a_section_result_cannot_bypass_the_actual_motion_omission_check(self):
        still = T.Motion(0, 1, {name: F.IDENTITY for name in self.state.network.plate_ids})
        fp = footprint(control('bridge_identity'), 'section', faces=('s03-b01',))
        extract = B.extract(self.state, fp, still, MYR)
        rotation = F.Rotation.from_axis_angle((1., 0., 0.), .1)
        actual = T.Motion(0, 1, {name: rotation for name in self.state.network.plate_ids})
        with self.assertRaises(B.BridgeRefused) as caught:
            B.extract(self.state, fp, actual, MYR)
        self.assertEqual(caught.exception.code, B.OMITTED_DIMENSION)
        carried = B.carried(extract, unchanged(extract))
        with self.assertRaises(B.BridgeRefused) as caught:
            T.advance(self.state, dataclasses.replace(actual, regional_returns=(carried,)), end_time_s=MYR)
        self.assertEqual(caught.exception.code, B.STALE_GEOMETRY)

    def test_a_reconstructed_section_record_cannot_claim_unsupported_forcing(self):
        still = T.Motion(0, 1, {name: F.IDENTITY for name in self.state.network.plate_ids})
        fp = footprint(control('bridge_identity'), 'section', faces=('s03-b01',))
        extracted = B.extract(self.state, fp, still, MYR)
        rotation = F.Rotation.from_axis_angle((1., 0., 0.), .1)
        actual = T.Motion(0, 1, {name: rotation for name in self.state.network.plate_ids})
        record = B.carried(extracted, unchanged(extracted)).record()
        record['motion_id'] = actual.motion_id
        record['extract_id'] = B._identity(self.state.state_id, fp, extracted.projection, actual.motion_id, MYR)
        carried = B.RegionalReturn.from_record(record)
        with self.assertRaises(B.BridgeRefused) as caught:
            T.advance(self.state, dataclasses.replace(actual, regional_returns=(carried,)), end_time_s=MYR)
        self.assertEqual(caught.exception.code, B.OMITTED_DIMENSION)

    def test_equal_stock_does_not_make_a_remeshed_face_the_same_support(self):
        state = F.crust(F.octahedron())
        fp = B.Footprint('r', ('o+++',), math.pi/4, math.asin(1/math.sqrt(3)), 0., 0., 35000., '3d')
        faces = {face.face_id: face for face in state.network.faces}
        first, second = faces['o+++'], faces['o-++']
        faces[first.face_id] = dataclasses.replace(first, vertex_ids=second.vertex_ids)
        faces[second.face_id] = dataclasses.replace(second, vertex_ids=first.vertex_ids)
        motion = T.Motion(0, 1, {plate: F.IDENTITY for plate in state.network.plate_ids},
                          mesh=T.Mesh(tuple(faces.values())))
        extract = B.extract(state, fp, motion, MYR)
        plain = T.advance(state, motion, end_time_s=MYR).state
        self.assertEqual(B._footprint_pieces(plain.network, plain.material, fp.face_ids), dict(extract.pieces))
        carried = B.carried(extract, unchanged(extract))
        with self.assertRaises(B.BridgeRefused) as caught:
            T.advance(state, dataclasses.replace(motion, regional_returns=(carried,)), end_time_s=MYR)
        self.assertEqual(caught.exception.code, B.STALE_GEOMETRY)
        self.assertIn('changed its support', str(caught.exception))

    def test_rigid_rides_and_cyclic_ring_order_keep_their_support_and_restore(self):
        fp = footprint(control('bridge_identity'), faces=('s03-b01',))
        rotation = F.Rotation.from_axis_angle((1., 0., 0.), .1)
        faces = tuple(dataclasses.replace(face, vertex_ids=face.vertex_ids[1:]+face.vertex_ids[:1])
                      if face.face_id == 's03-b01' else face for face in self.state.network.faces)
        for mesh in (None, T.Mesh(faces)):
            with self.subTest(mesh=mesh is not None):
                motion = T.Motion(0, 1, {name: rotation for name in self.state.network.plate_ids}, mesh=mesh)
                extract = B.extract(self.state, fp, motion, MYR)
                carried = B.carried(extract, unchanged(extract))
                step = T.advance(self.state, dataclasses.replace(motion, regional_returns=(carried,)), end_time_s=MYR)
                self.assertEqual(B._footprint_pieces(step.state.network, step.state.material, fp.face_ids),
                                 dict(extract.pieces))
                again = T.restored(self.state, {'sphere': step.record(), 'transfers': []}, step.arrays())
                self.assertEqual(again.state_id, step.state.state_id)


class ReturnLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import i02_workflow_fixtures as F2
        from threadpoolctl import threadpool_limits
        cls.F2 = F2
        with threadpool_limits(limits=1, user_api='blas'):
            cls.prepared = F2.preparation()

    def test_a_return_commits_through_the_clock_reopens_and_continues(self):
        from atlas_tectonics import integration_clock as K, integration_ledger as L
        F2, rule = self.F2, control('bridge_return_commit')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'ledger.sqlite'
            store = F2.store(path)
            try:
                world = F.three_plates(epoch=F2.EPOCH, time_s=F2.START)
                column = F2.root(F.control('clock_commit')['column_steps'], prepared=self.prepared)
                ledger, root = L.Ledger.create(store, column, sphere=F.crust(world))
                parent = ledger.sphere(root)
                clock = K.Clock(ledger)
                duration = clock.time_at(1)-parent.network.time_s
                carried = ReturnRouteTests.carried(type('R', (), {'rule': rule})(), parent, duration=duration)[1]
                deadline = lambda: time.perf_counter()+F.CASE['resources']['clock_deadline_s']
                first = clock.advance(steps=1, deadline=deadline(), transfers=(
                    F.one_plate_motion(rule['turn_deg'], regional_returns=(carried,)),))
                self.assertEqual(first.status, K.COMPLETED, first.reason)
                made = ledger.sphere(first.head)
            finally:
                store.close()
            store = F2.store(path)
            try:
                again = L.Ledger.open(store, ledger.ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
                self.assertEqual(again.verify_chain().key, first.head.key)
                self.assertEqual(again.sphere(first.head).state_id, made.state_id)
                later = K.Clock(again).advance(steps=1, deadline=deadline(), transfers=(
                    F.one_plate_motion(rule['turn_deg'], step=1),))
                self.assertEqual(later.status, K.COMPLETED, later.reason)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
