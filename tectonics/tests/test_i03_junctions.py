"""I03a-2 Part 2: junction advance (approved 3 October 2026: D1-D5, C1, C3-C5, C8-C9, M1, M6). WORKING NON-CANON.

Every value comes from cases/i03_controls_v2.json. Two worlds: the hemispheres world, whose T-junctions persist under
three different poles because every record carries them to one point (I03a's rule; under three poles it relies on
M1, without which I03a refuses the first interval), and a plate that turns between
fixed neighbours on a transform, whose ridge-ended junction migrates along the transform line until a boundary
segment would shorten to zero.
"""
import json
import math
import unittest

import numpy as np

import i03_fixtures as F
from atlas_tectonics import integration_sphere as S, integration_transfer as T
from atlas_tectonics.kinematics import Rotation

CASE2 = json.loads((F.CASES/'i03_controls_v2.json').read_text(encoding='utf-8'))
CASE4 = json.loads((F.CASES/'i03_controls_v4.json').read_text(encoding='utf-8'))
MYR = F.MYR_S
RELATIVE = F.tolerance('relative')
ANGULAR = F.tolerance('angular_absolute_rad')
AREA_SR = F.tolerance('area_closure_absolute_sr')


def control(name):
    return CASE2['controls'][name]


def hemispheres(tilt=None, fraction=.5):
    rule = control('hemispheres')
    lons, lats = rule['longitudes_deg'], rule['latitudes_deg']
    equator, half, count = lats.index(0), len(lons)//2, len(lons)
    vertices, rings = F.sector_mesh(lons, lats, tilt=tilt)

    def owner(name):
        south = name.endswith('south') or ('-b' in name and int(name[-2:]) < equator)
        return 'O' if not south else ('S1' if F.sector_of(name) < half else 'S2')
    faces = tuple(S.Face(name, owner(name), ring) for name, ring in rings.items())
    boundaries = (
        S.Boundary('trench-s1', S.TRENCH, 'O', 'S1', tuple(F.vertex(i, equator) for i in range(half+1)), F.origin(),
                   subducting_side='right'),
        S.Boundary('trench-s2', S.TRENCH, 'O', 'S2', tuple(F.vertex(i % count, equator) for i in range(half, count+1)),
                   F.origin(), subducting_side='right'),
        S.Boundary('ridge', S.RIDGE, 'S1', 'S2', tuple(F.vertex(0, j) for j in range(equator, -1, -1))+('S',)
                   + tuple(F.vertex(half, j) for j in range(equator+1)), F.origin(), accretion_fraction=fraction))
    plates = tuple(S.Plate(name, F.IDENTITY) for name in ('O', 'S1', 'S2'))
    return S.build_network(sphere=F.sphere(), vertices=vertices, faces=faces, plates=plates, boundaries=boundaries,
                           epoch_id=F.EPOCH, time_s=F.START)


def about(axis, degrees, tilt=None):
    axis = np.asarray(axis, dtype=float)
    if tilt is not None:
        axis = tilt.apply(axis)
    return Rotation.from_axis_angle(tuple(axis), math.radians(degrees))


def persisting_motion(rule, step, tilt=None):
    # The axis through both junctions where they are at the start of this interval: O has carried them by step*gamma.
    turn = about((0, 0, 1), rule['gamma_deg'], tilt)
    through = about((0, 0, 1), step*rule['gamma_deg']).apply(np.array((1., 0., 0.)))
    rotations = {'O': turn, 'S1': about(through, rule['alpha_deg'], tilt).then(turn),
                 'S2': about(through, -rule['alpha_deg'], tilt).then(turn)}
    return T.Motion(step, step+1, rotations, supplies=F.both_sides('ridge'),
                    sinks=(F.sink('trench-s1'), F.sink('trench-s2')))


def junction_positions(state, plate, tilt=None):
    """Each junction's longitude (degrees east) and height above the equator plane, in ``plate``'s frame."""
    network = state.network
    frame = network.frames[plate]
    out = {}
    for junction in network.junctions:
        local = frame.inverse().apply(np.asarray(network.vertex_direction[network.vertex_ids.index(junction.vertex_id)]))
        if tilt is not None:
            local = tilt.inverse().apply(local)
        out[junction.vertex_id] = (math.degrees(math.atan2(local[1], local[0])) % 360., float(local[2]))
    return out


def check_state(test, state):
    network, material = state.network, state.material
    test.assertTrue(material.closure()['identity_exact'])
    test.assertLessEqual(abs(network.statistics['area_residual_sr']), AREA_SR)
    for index, area in enumerate(network.face_area_m2):
        held = math.fsum(material.stock[material.piece_face == index, 0])
        test.assertLessEqual(abs(held-area), max(RELATIVE*area, float(material.occupancy_allowance_m2[index])))


class PersistingJunctionTests(unittest.TestCase):
    def test_t_junctions_between_three_poles_persist(self):
        rule = control('persisting_t_junction')
        for tilt in (None, F.TILT):
            with self.subTest(tilted=tilt is not None):
                state = F.crust(hemispheres(tilt))
                start = junction_positions(state, 'O', tilt)
                for k in range(rule['intervals']):
                    state = T.advance(state, persisting_motion(rule, k, tilt), end_time_s=(k+1)*MYR).state
                    check_state(self, state)
                    for name, (longitude, height) in junction_positions(state, 'O', tilt).items():
                        if name in start and abs(start[name][1]) < 1e-12:            # the two T-junctions
                            self.assertLess(abs((longitude-start[name][0]+180.) % 360.-180.), 1e-9)
                            self.assertLess(abs(height), 1e-12)
                if tilt is None:
                    plain = state.material.totals()
                else:
                    for name, value in state.material.totals().items():
                        self.assertLessEqual(abs(value-plain[name]), RELATIVE*max(abs(plain[name]), 1.), name)


def one_plate_world(fraction=.5):
    rule = control('one_plate_on_a_transform')
    lons, lats = rule['longitudes_deg'], rule['latitudes_deg']
    equator, count = lats.index(0), len(lons)
    first, last = rule['plate_sectors'][0], rule['plate_sectors'][-1]+1
    vertices, rings = F.sector_mesh(lons, lats)

    def owner(name):
        if name.endswith('south') or ('-b' in name and int(name[-2:]) < equator):
            return 'S'
        return 'P' if F.sector_of(name) in rule['plate_sectors'] else 'W'
    faces = tuple(S.Face(name, owner(name), ring) for name, ring in rings.items())
    bands = len(lats)
    boundaries = (
        S.Boundary('ridge', S.RIDGE, 'W', 'P', tuple(F.vertex(first, j) for j in range(equator, bands))+('N',),
                   F.origin(), accretion_fraction=fraction),
        S.Boundary('trench', S.TRENCH, 'W', 'P', ('N',)+tuple(F.vertex(last, j) for j in range(bands-1, equator-1, -1)),
                   F.origin(), subducting_side='right'),
        S.Boundary('equator-p', S.TRANSFORM, 'P', 'S', tuple(F.vertex(i, equator) for i in range(first, last+1)),
                   F.origin(), carrier_side='right'),
        S.Boundary('equator-w', S.TRANSFORM, 'W', 'S',
                   tuple(F.vertex(i % count, equator) for i in range(last, count+first+1)), F.origin(),
                   carrier_side='right'))
    plates = tuple(S.Plate(name, F.IDENTITY) for name in ('P', 'S', 'W'))
    return S.build_network(sphere=F.sphere(), vertices=vertices, faces=faces, plates=plates, boundaries=boundaries,
                           epoch_id=F.EPOCH, time_s=F.START)


def rotating_north(lons=None, sectors=None, moved=None, n2_carrier='right', epoch=F.EPOCH, start=F.START):
    rule = control('rotating_north')
    lons, lats = lons or rule['longitudes_deg'], rule['latitudes_deg']
    sectors = sectors or rule['plate_sectors']
    equator, count, bands = lats.index(0), len(lons), len(lats)
    first, last = sectors[0], sectors[-1]+1
    vertices, rings = F.sector_mesh(lons, lats)
    if moved is not None:
        vertices[moved['name']] = F.direction(*moved['to_lon_lat_deg'])

    def owner(name):
        if name.endswith('south') or ('-b' in name and int(name[-2:]) < equator):
            return 'S'
        return 'N1' if F.sector_of(name) in sectors else 'N2'
    faces = tuple(S.Face(name, owner(name), ring) for name, ring in rings.items())
    boundaries = (
        S.Boundary('seam-west', S.TRANSFORM, 'N2', 'N1', tuple(F.vertex(first, j) for j in range(equator, bands))+('N',),
                   F.origin()),
        S.Boundary('seam-east', S.TRANSFORM, 'N2', 'N1', ('N',)+tuple(F.vertex(last, j) for j in range(bands-1, equator-1, -1)),
                   F.origin()),
        S.Boundary('equator-n1', S.TRANSFORM, 'N1', 'S', tuple(F.vertex(i, equator) for i in range(first, last+1)),
                   F.origin(), carrier_side='right'),
        S.Boundary('equator-n2', S.TRANSFORM, 'N2', 'S',
                   tuple(F.vertex(i % count, equator) for i in range(last, count+first+1)), F.origin(),
                   carrier_side=n2_carrier))
    plates = tuple(S.Plate(name, F.IDENTITY) for name in ('N1', 'N2', 'S'))
    return S.build_network(sphere=F.sphere(), vertices=vertices, faces=faces, plates=plates, boundaries=boundaries,
                           epoch_id=epoch, time_s=start)


def north_motion(step):
    """rotating_north's motion for interval ``step``: N1 and N2 turn by omega, S is fixed."""
    turn = F.spin(control('rotating_north')['omega_deg'])
    return T.Motion(step, step+1, {'N1': turn, 'N2': turn, 'S': F.IDENTITY})


class MigratingJunctionTests(unittest.TestCase):
    def test_t_junctions_slide_along_their_line_until_a_segment_would_shorten_to_zero(self):
        rule = control('rotating_north')
        lons = rule['longitudes_deg']
        first, last = rule['plate_sectors'][0], rule['plate_sectors'][-1]+1
        west, east = F.vertex(first, 2), F.vertex(last, 2)
        state = F.crust(rotating_north())
        lifetime = math.ceil(rule['next_vertex_deg']/rule['omega_deg'])
        refused, accepted = None, 0
        for k in range(rule['intervals']):
            turn = F.spin(rule['omega_deg'])
            motion = T.Motion(k, k+1, {'N1': turn, 'N2': turn, 'S': F.IDENTITY})
            try:
                state = T.advance(state, motion, end_time_s=(k+1)*MYR).state
            except T.TransferRefused as exc:
                refused = (k+1, str(exc))
                break
            accepted += 1
            check_state(self, state)
            where = junction_positions(state, 'S')
            for name, start in ((west, lons[first]), (east, lons[last])):
                self.assertLess(abs(where[name][0]-(start+accepted*rule['omega_deg'])), 1e-9, (k, name, where))
                self.assertLess(abs(where[name][1]), 1e-12)
            chain = state.network.boundary('equator-n2').vertex_ids
            self.assertEqual(chain[-1], west)
            self.assertTrue(chain[-2].startswith(west+'|S|'))                # S keeps the old corner behind it
        self.assertIsNotNone(refused, 'the junction never reached the next vertex')
        self.assertIn(refused[0], (lifetime-1, lifetime), refused)
        self.assertIn('shorten to zero', refused[1])
        self.assertIn('D1-c', refused[1])                          # the vertex ahead is a seam vertex
        self.assertEqual(S.restore_sphere(state.descriptor(), state.arrays()).state_id, state.state_id)

    def test_two_junctions_slide_on_a_line_record_of_one_segment(self):
        rule = control('one_segment_line')
        lons = rule['longitudes_deg']
        first, last = rule['plate_sectors'][0], rule['plate_sectors'][-1]+1
        state = F.crust(rotating_north(lons=lons, sectors=rule['plate_sectors']))
        self.assertEqual(len(state.network.boundary('equator-n1').vertex_ids), 2)
        west, east = F.vertex(first, 2), F.vertex(last, 2)
        for k in range(rule['intervals']):
            turn = F.spin(rule['omega_deg'])
            state = T.advance(state, T.Motion(k, k+1, {'N1': turn, 'N2': turn, 'S': F.IDENTITY}),
                              end_time_s=(k+1)*MYR).state
            check_state(self, state)
            where = junction_positions(state, 'S')
            for name, start in ((west, lons[first]), (east, lons[last])):
                self.assertLess(abs(where[name][0]-(start+(k+1)*rule['omega_deg'])), 1e-9, (k, name, where))
                self.assertLess(abs(where[name][1]), 1e-12)

    def test_a_ridge_side_plate_sliding_along_the_line_is_refused(self):
        # P turns between fixed neighbours: on the ridge's moving side it slides along the transform line, so its old
        # corner would have to slide along the line as a vertex of it (option D1-c, deferred).
        rule = control('one_plate_on_a_transform')
        state = F.crust(one_plate_world())
        motion = T.Motion(0, 1, {'P': F.spin(rule['omega_deg']), 'S': F.IDENTITY, 'W': F.IDENTITY},
                          supplies=F.both_sides('ridge'), sinks=(F.sink('trench'),))
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, motion, end_time_s=MYR)
        self.assertIn('D1-c', str(caught.exception))

    def test_the_same_holds_where_every_record_carries_the_junction_to_one_point(self):
        rule = control('same_point_ridge_on_a_transform')
        for case in rule['cases']:
            with self.subTest(**case):
                state = F.crust(one_plate_world(case['accretion_fraction']))
                fraction = case['accretion_fraction']
                supplies = F.both_sides('ridge') if 0 < fraction < 1 else (F.supply('ridge', 'right'),)
                motion = T.Motion(0, 1, {'P': F.spin(case['p_deg']), 'S': F.spin(case['s_deg']), 'W': F.IDENTITY},
                                  supplies=supplies, sinks=(F.sink('trench'),))
                with self.assertRaises(T.TransferRefused) as caught:
                    T.advance(state, motion, end_time_s=MYR)
                self.assertIn('D1-c', str(caught.exception))


class FrameAndCompositionTests(unittest.TestCase):
    @staticmethod
    def history(state, rotations, steps):
        """Run ``steps`` intervals; rotations(k) gives each interval's stage rotations. Returns (states, refusal)."""
        out = []
        for k in range(steps):
            try:
                state = T.advance(state, T.Motion(k, k+1, rotations(k)), end_time_s=(k+1)*MYR).state
            except T.TransferRefused as exc:
                return out, str(exc)
            out.append(state)
        return out, None

    def test_a_common_frame_rotation_changes_nothing_accepted(self):
        rule, frame = control('rotating_north'), control('junction_frames_and_composition')
        q = Rotation.from_axis_angle(tuple(frame['frame_rotation']['axis']),
                                     math.radians(frame['frame_rotation']['angle_deg']))
        turn = F.spin(rule['omega_deg'])
        plain = lambda k: {'N1': turn, 'N2': turn, 'S': F.IDENTITY}

        def seen(k):                                  # G_k R_k G_(k-1)^-1 with G_0 = I and G_k = Q
            before = F.IDENTITY if k == 0 else q.inverse()
            return {p: before.then(r).then(q) for p, r in plain(k).items()}
        start = F.crust(rotating_north())
        one, refused_one = self.history(start, plain, frame['intervals'])
        two, refused_two = self.history(start, seen, frame['intervals'])
        self.assertEqual(len(one), len(two))
        self.assertEqual(refused_one is None, refused_two is None)
        for a, b in zip(one, two):
            for junction in a.network.junctions:
                here = a.network.vertex_direction[a.network.vertex_ids.index(junction.vertex_id)]
                there = b.network.vertex_direction[b.network.vertex_ids.index(junction.vertex_id)]
                self.assertLessEqual(float(F.angle(q.apply(here), there)), ANGULAR)
            for plate, area in a.network.plate_area_m2().items():
                self.assertLessEqual(abs(b.network.plate_area_m2()[plate]-area), RELATIVE*area)
            for name, value in a.material.totals().items():
                self.assertLessEqual(abs(b.material.totals()[name]-value), RELATIVE*max(abs(value), 1.), name)

    def test_slow_motion_and_large_frame_rotations_are_accepted_alike(self):
        # C1's residual is formed from velocities relative to one plate at the junction, and the advanced junction is
        # chosen nearest its carried position: neither may depend on the frame (Part 2 verifier, 3 October 2026).
        rule = control('junction_frames_slow_and_large')
        for case in rule['cases']:
            with self.subTest(**case):
                q = Rotation.from_axis_angle(tuple(rule['frame_axis']), math.radians(case['frame_angle_deg']))
                turn = F.spin(case['omega_deg'])
                plain = lambda k: {'N1': turn, 'N2': turn, 'S': F.IDENTITY}

                def seen(k):
                    before = F.IDENTITY if k == 0 else q.inverse()
                    return {p: before.then(r).then(q) for p, r in plain(k).items()}
                start = F.crust(rotating_north())
                one, refused_one = self.history(start, plain, rule['intervals'])
                two, refused_two = self.history(start, seen, rule['intervals'])
                self.assertIsNone(refused_one)
                self.assertIsNone(refused_two)
                for a, b in zip(one, two):
                    for junction in a.network.junctions:
                        here = a.network.vertex_direction[a.network.vertex_ids.index(junction.vertex_id)]
                        there = b.network.vertex_direction[b.network.vertex_ids.index(junction.vertex_id)]
                        self.assertLessEqual(float(F.angle(q.apply(here), there)), ANGULAR)

    def test_tilted_axes_give_the_same_history(self):
        rule, frame = control('rotating_north'), control('junction_frames_and_composition')
        turn, tilted = F.spin(rule['omega_deg']), F.spin(rule['omega_deg'], F.TILT)
        plain, _ = self.history(F.crust(rotating_north()), lambda k: {'N1': turn, 'N2': turn, 'S': F.IDENTITY},
                                frame['intervals'])
        world = rotating_north_tilted()
        other, _ = self.history(F.crust(world), lambda k: {'N1': tilted, 'N2': tilted, 'S': F.IDENTITY},
                                frame['intervals'])
        self.assertEqual(len(plain), len(other))
        for a, b in zip(plain, other):
            for name, value in a.material.totals().items():
                self.assertLessEqual(abs(b.material.totals()[name]-value), RELATIVE*max(abs(value), 1.), name)

    def test_the_junction_does_not_depend_on_subdivision(self):
        # C8 (approved; derived for a plate-carried third trace): each evaluation of J carries at most 4 eps / sin psi.
        rule = control('junction_subdivision')
        start = F.crust(rotating_north())
        whole = T.advance(start, T.Motion(0, 1, {'N1': F.spin(rule['total_deg']), 'N2': F.spin(rule['total_deg']),
                                                 'S': F.IDENTITY}), end_time_s=MYR).state
        bound = 8*float(np.finfo(float).eps)
        for n in rule['subdivisions']:
            with self.subTest(n=n):
                part = F.spin(rule['total_deg']/n)
                state = start
                for k in range(n):
                    state = T.advance(state, T.Motion(k, k+1, {'N1': part, 'N2': part, 'S': F.IDENTITY}),
                                      end_time_s=(k+1)*MYR/n).state
                for junction in whole.network.junctions:
                    a = whole.network.vertex_direction[whole.network.vertex_ids.index(junction.vertex_id)]
                    b = state.network.vertex_direction[state.network.vertex_ids.index(junction.vertex_id)]
                    self.assertLessEqual(float(F.angle(a, b)), bound, (n, junction.vertex_id))

    def test_one_interval_against_two_halves(self):
        rule = control('rotating_north')
        state = F.crust(rotating_north())
        whole = T.advance(state, T.Motion(0, 1, {'N1': F.spin(2*rule['omega_deg']), 'N2': F.spin(2*rule['omega_deg']),
                                                 'S': F.IDENTITY}), end_time_s=MYR).state
        half = F.spin(rule['omega_deg'])
        first = T.advance(state, T.Motion(0, 1, {'N1': half, 'N2': half, 'S': F.IDENTITY}), end_time_s=MYR).state
        second = T.advance(first, T.Motion(1, 2, {'N1': half, 'N2': half, 'S': F.IDENTITY}), end_time_s=2*MYR).state
        bound = 8*float(np.finfo(float).eps)                      # 8 eps / sin psi, sin psi = 1 here (C9)
        for junction in whole.network.junctions:
            a = whole.network.vertex_direction[whole.network.vertex_ids.index(junction.vertex_id)]
            b = second.network.vertex_direction[second.network.vertex_ids.index(junction.vertex_id)]
            self.assertLessEqual(float(F.angle(a, b)), bound)
        for plate, area in whole.network.plate_area_m2().items():
            self.assertLessEqual(abs(second.network.plate_area_m2()[plate]-area), RELATIVE*area)


def rotating_north_tilted():
    """rotating_north with every declared direction turned by the case's tilt."""
    original = F.sector_mesh
    try:
        F.sector_mesh = lambda lons, lats, **kw: original(lons, lats, tilt=F.TILT)
        return rotating_north()
    finally:
        F.sector_mesh = original


CONTINUE = """
import json, sys
import numpy as np
sys.path.insert(0, sys.argv[3])
import i03_fixtures as F
import test_i03_junctions as J
from atlas_tectonics import integration_sphere as S, integration_transfer as T
folder, steps = sys.argv[1], int(sys.argv[2])
record = json.loads(open(folder+'/state.json', encoding='utf-8').read())
with np.load(folder+'/arrays.npz', allow_pickle=False) as stored:
    arrays = {name: stored[name] for name in stored.files}
state = S.restore_sphere(record, arrays)
rule = J.control('rotating_north')
for k in range(state.step, state.step+steps):
    turn = F.spin(rule['omega_deg'])
    state = T.advance(state, T.Motion(k, k+1, {'N1': turn, 'N2': turn, 'S': F.IDENTITY}),
                      end_time_s=(k+1)*F.MYR_S).state
print(state.state_id)
"""


class DeclarationTests(unittest.TestCase):
    def test_a_line_of_two_carriers_does_not_advance(self):
        # C3 (approved): two records ending at a junction on one great circle form one line, which one plate carries.
        # I03a admits such a declaration and moves its junction while every record carries it to one point, so the
        # refusal comes when the junction would advance.
        state = F.crust(rotating_north(n2_carrier='left'))
        turn = F.spin(control('rotating_north')['omega_deg'])
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, T.Motion(0, 1, {'N1': turn, 'N2': turn, 'S': F.IDENTITY}), end_time_s=MYR)
        self.assertIn('carried by one plate', str(caught.exception))

    def test_the_line_carrier_s_face_ahead_is_reshaped_not_slid(self):
        state = F.crust(rotating_north())
        turn = F.spin(control('rotating_north')['omega_deg'])
        motion = T.Motion(0, 1, {'N1': turn, 'N2': turn, 'S': F.IDENTITY})
        geometry = T._moved(state.network, motion, None)
        plate = {face.face_id: face.plate_id for face in state.network.faces}
        self.assertTrue(geometry.slid)
        self.assertTrue(all(plate[face_id] in ('N1', 'N2') for face_id in geometry.slid))
        self.assertEqual(sorted(plate[face_id] for face_id in geometry.reshaped), ['S', 'S'])
        summary = T.advance(state, motion, end_time_s=MYR).summary()['map']
        self.assertEqual((summary['reshaped_faces'], summary['consumed_faces']), (2, 0))


def four_north(tilt=None):
    """The carried_ridge world: four northern plates over S, a ridge carried by N2 ending on S's equator line."""
    rule = control('carried_ridge')
    lons, lats = rule['longitudes_deg'], control('rotating_north')['latitudes_deg']
    equator, bands, count = lats.index(0), len(lats), len(lons)
    vertices, rings = F.sector_mesh(lons, lats, tilt=tilt)
    ia, iw, ie, ib = (lons.index(rule[key]) for key in ('ridge_lon', 'trench_w_lon', 'trench_e_lon', 'ridge_b_lon'))

    def owner(name):
        if name.endswith('south') or ('-b' in name and int(name[-2:]) < equator):
            return 'S'
        sector = F.sector_of(name)
        return 'N2' if ia <= sector < iw else 'N1' if iw <= sector < ie else 'N3' if ie <= sector < ib else 'N4'
    faces = tuple(S.Face(name, owner(name), ring) for name, ring in rings.items())
    north = lambda i: tuple(F.vertex(i, j) for j in range(equator, bands))+('N',)
    line = lambda i0, i1: tuple(F.vertex(i % count, equator) for i in range(i0, i1+1))
    boundaries = (
        S.Boundary('ridge-a', S.RIDGE, 'N4', 'N2', north(ia), F.origin(), accretion_fraction=1.),
        S.Boundary('trench-w', S.TRENCH, 'N2', 'N1', north(iw), F.origin(), subducting_side='right'),
        S.Boundary('trench-e', S.TRENCH, 'N1', 'N3', north(ie), F.origin(), subducting_side='left'),
        S.Boundary('ridge-b', S.RIDGE, 'N3', 'N4', north(ib), F.origin(), accretion_fraction=0.),
        S.Boundary('eq-n2', S.TRANSFORM, 'N2', 'S', line(ia, iw), F.origin(), carrier_side='right'),
        S.Boundary('eq-n1', S.TRANSFORM, 'N1', 'S', line(iw, ie), F.origin(), carrier_side='right'),
        S.Boundary('eq-n3', S.TRANSFORM, 'N3', 'S', line(ie, ib), F.origin(), carrier_side='right'),
        S.Boundary('eq-n4', S.TRANSFORM, 'N4', 'S', line(ib, count+ia), F.origin(), carrier_side='right'))
    plates = tuple(S.Plate(name, F.IDENTITY) for name in ('N1', 'N2', 'N3', 'N4', 'S'))
    return S.build_network(sphere=F.sphere(), vertices=vertices, faces=faces, plates=plates, boundaries=boundaries,
                           epoch_id=F.EPOCH, time_s=F.START)


def run(state, rotations, steps, supplies=(), sinks=(), frames=None, start=0):
    """``steps`` intervals; rotations(k) gives interval k's stage rotations; frames (G_1..) applies D3."""
    out = []
    for k in range(start, start+steps):
        stage = rotations(k)
        if frames is not None:
            before = F.IDENTITY if k == 0 else frames[k-1].inverse()
            stage = {plate: before.then(r).then(frames[k]) for plate, r in stage.items()}
        try:
            state = T.advance(state, T.Motion(k, k+1, stage, supplies=supplies, sinks=sinks),
                              end_time_s=(k+1)*MYR).state
        except T.TransferRefused as exc:
            return out, (k+1, str(exc))
        out.append(state)
    return out, None


def d3_frames(rule):
    return [Rotation.from_axis_angle(tuple(f['axis']), math.radians(f['angle_deg'])) for f in rule['d3_frames']]


CARRIED_SUPPLIES, CARRIED_SINKS = (F.supply('ridge-a', 'left'),), (F.sink('trench-w'),)


def carried(w, tilt=None):
    return lambda k: {'N1': F.IDENTITY, 'N3': F.IDENTITY, 'N4': F.IDENTITY, 'S': F.IDENTITY, 'N2': F.spin(w, tilt)}


class CarriedRidgeTests(unittest.TestCase):
    # F4 and F5 (round 1): a ridge carried by its moving plate ends on S's line; N4, locked to S, shares S's corner.
    def test_the_junctions_slide_until_one_reaches_the_next_junction(self):
        rule = control('carried_ridge')
        lons = rule['longitudes_deg']
        ridge, west = F.vertex(lons.index(rule['ridge_lon']), 2), F.vertex(lons.index(rule['trench_w_lon']), 2)
        states, refused = run(F.crust(four_north()), carried(rule['omega_deg']), rule['accepted_intervals']+1,
                              CARRIED_SUPPLIES, CARRIED_SINKS)
        self.assertEqual(len(states), rule['accepted_intervals'], refused)
        for k, state in enumerate(states):
            check_state(self, state)
            where = junction_positions(state, 'S')
            for name, start in ((ridge, rule['ridge_lon']), (west, rule['trench_w_lon'])):
                self.assertLess(abs(where[name][0]-(start+(k+1)*rule['omega_deg'])), 1e-9, (k, name))
                self.assertLess(abs(where[name][1]), 1e-12)
        self.assertEqual(refused[0], rule['accepted_intervals']+1)
        self.assertIn('shorten to zero', refused[1])
        self.assertIn('reorganise', refused[1])                 # the segment between two junctions collapses

    def test_narrow_strips_are_accepted_alike_in_every_frame(self):
        rule = control('carried_ridge')
        frames, step = d3_frames(rule), Rotation.from_axis_angle(tuple(rule['moving_carrier']['axis']),
                                                                 math.radians(rule['moving_carrier']['angle_deg']))

        def moving(w):
            def rotations(k):
                so_far = F.IDENTITY
                for _ in range(k):
                    so_far = so_far.then(step)
                slip = so_far.inverse().then(F.spin(w)).then(so_far)         # about S's current equator pole
                return {'N1': step, 'N3': step, 'N4': step, 'S': step, 'N2': slip.then(step)}
            return rotations
        start = F.crust(four_north())
        for w in rule['narrow_deg']:
            for label, rotations, applied in (('fixed', carried(w), None), ('D3', carried(w), frames),
                                              ('moving carrier', moving(w), None)):
                with self.subTest(w=w, history=label):
                    states, refused = run(start, rotations, rule['narrow_intervals'], CARRIED_SUPPLIES,
                                          CARRIED_SINKS, applied)
                    self.assertIsNone(refused)
                    for state in states:
                        check_state(self, state)

    def test_tilted_axes_and_halves(self):
        rule = control('carried_ridge')
        w = rule['omega_deg']
        plain, _ = run(F.crust(four_north()), carried(w), 2, CARRIED_SUPPLIES, CARRIED_SINKS)
        tilted, refused = run(F.crust(four_north(F.TILT)), carried(w, F.TILT), 2, CARRIED_SUPPLIES, CARRIED_SINKS)
        self.assertIsNone(refused)
        for a, b in zip(plain, tilted):
            for name, value in a.material.totals().items():
                self.assertLessEqual(abs(b.material.totals()[name]-value), RELATIVE*max(abs(value), 1.), name)
        whole, _ = run(F.crust(four_north()), carried(2*w), 1, CARRIED_SUPPLIES, CARRIED_SINKS)
        halves, refused = run(F.crust(four_north()), carried(w), 2, CARRIED_SUPPLIES, CARRIED_SINKS)
        self.assertIsNone(refused)
        bound = 8*float(np.finfo(float).eps)
        for junction in whole[0].network.junctions:
            a = whole[0].network.vertex_direction[whole[0].network.vertex_ids.index(junction.vertex_id)]
            b = halves[1].network.vertex_direction[halves[1].network.vertex_ids.index(junction.vertex_id)]
            self.assertLessEqual(float(F.angle(a, b)), bound, junction.vertex_id)


def sliding(rule, tilt=None):
    """hemispheres_slide's rotations: every record carries each junction to one point that slides along O's line."""
    def rotations(k):
        z = np.array((0., 0., 1.)) if tilt is None else tilt.apply(np.array((0., 0., 1.)))
        lon = math.radians(k*rule['delta_deg'])
        through = np.array((math.cos(lon), math.sin(lon), 0.))
        if tilt is not None:
            through = tilt.apply(through)
        spin = Rotation.from_axis_angle(tuple(z), math.radians(rule['delta_deg']))
        return {'O': Rotation.from_axis_angle(tuple(z), math.radians(rule['gamma_deg'])),
                'S1': Rotation.from_axis_angle(tuple(through), math.radians(rule['alpha_deg'])).then(spin),
                'S2': Rotation.from_axis_angle(tuple(through), math.radians(-rule['alpha_deg'])).then(spin)}
    return rotations


HEMISPHERE_SUPPLIES, HEMISPHERE_SINKS = F.both_sides('ridge'), (F.sink('trench-s1'), F.sink('trench-s2'))


class HemispheresSlideTests(unittest.TestCase):
    # F5 (round 1): T-junctions of a ridge on O's trench line slide along it under three poles.
    def test_the_junctions_slide_until_they_reach_the_next_vertex(self):
        rule = control('hemispheres_slide')
        rate = rule['delta_deg']-rule['gamma_deg']
        for tilt in (None, F.TILT):
            with self.subTest(tilted=tilt is not None):
                start = F.crust(hemispheres(tilt))
                origin = junction_positions(start, 'O', tilt)
                states, refused = run(start, sliding(rule, tilt), rule['accepted_intervals']+1, HEMISPHERE_SUPPLIES,
                                      HEMISPHERE_SINKS)
                self.assertEqual(len(states), rule['accepted_intervals'], refused)
                for k, state in enumerate(states):
                    check_state(self, state)
                    for name, (longitude, height) in junction_positions(state, 'O', tilt).items():
                        if abs(origin[name][1]) < 1e-12:                         # the two T-junctions
                            moved = (longitude-origin[name][0]-(k+1)*rate+180.) % 360.-180.
                            self.assertLess(abs(moved), 1e-9, (k, name))
                            self.assertLess(abs(height), 1e-12)
                self.assertEqual(refused[0], rule['accepted_intervals']+1)
                self.assertIn('shorten to zero', refused[1])

    def test_the_same_history_in_rotated_axes_and_in_halves(self):
        rule = control('hemispheres_slide')
        frames = d3_frames(rule)
        start = F.crust(hemispheres())
        plain, _ = run(start, sliding(rule), 3, HEMISPHERE_SUPPLIES, HEMISPHERE_SINKS)
        seen, refused = run(start, sliding(rule), 3, HEMISPHERE_SUPPLIES, HEMISPHERE_SINKS, frames)
        self.assertIsNone(refused)
        for k, (a, b) in enumerate(zip(plain, seen)):
            for junction in a.network.junctions:
                here = a.network.vertex_direction[a.network.vertex_ids.index(junction.vertex_id)]
                there = b.network.vertex_direction[b.network.vertex_ids.index(junction.vertex_id)]
                self.assertLessEqual(float(F.angle(frames[k].apply(here), there)), ANGULAR)
        # Two halves about the junction axis at the start of each half compose exactly to the whole motion.
        slow = rule['halves']
        half = {key: value/2 for key, value in slow.items()}
        whole, _ = run(start, sliding(slow), 1, HEMISPHERE_SUPPLIES, HEMISPHERE_SINKS)
        halves, refused = run(start, sliding(half), 2, HEMISPHERE_SUPPLIES, HEMISPHERE_SINKS)
        self.assertIsNone(refused)
        bound = 8*float(np.finfo(float).eps)/math.cos(math.radians(slow['alpha_deg']))      # 8 eps / sin psi (C9)
        for junction in whole[0].network.junctions:
            a = whole[0].network.vertex_direction[whole[0].network.vertex_ids.index(junction.vertex_id)]
            b = halves[1].network.vertex_direction[halves[1].network.vertex_ids.index(junction.vertex_id)]
            self.assertLessEqual(float(F.angle(a, b)), bound, junction.vertex_id)


def with_mid_vertex(lon):
    """rotating_north with a vertex 'mid' declared on equator-n1's first segment, used by its two faces only."""
    rule = control('rotating_north')
    lons, lats, sectors = rule['longitudes_deg'], rule['latitudes_deg'], rule['plate_sectors']
    equator, count, bands = lats.index(0), len(lons), len(lats)
    first, last = sectors[0], sectors[-1]+1
    vertices, rings = F.sector_mesh(lons, lats)
    a, b = F.vertex(first, equator), F.vertex(first+1, equator)
    longitudes = (lon,) if isinstance(lon, (int, float)) else tuple(lon)
    mids = tuple('mid' if i == 0 else 'mid%d' % i for i in range(len(longitudes)))
    for name, longitude in zip(mids, longitudes):
        vertices[name] = F.direction(longitude, 0.)

    def inserted(ring):
        for k in range(len(ring)):
            if {ring[k], ring[(k+1) % len(ring)]} == {a, b}:
                added = mids if ring[k] == a else mids[::-1]
                return tuple(ring[:k+1])+added+tuple(ring[k+1:])
        return tuple(ring)

    def owner(name):
        if name.endswith('south') or ('-b' in name and int(name[-2:]) < equator):
            return 'S'
        return 'N1' if F.sector_of(name) in sectors else 'N2'
    faces = tuple(S.Face(name, owner(name), inserted(ring)) for name, ring in rings.items())
    n1 = tuple(F.vertex(i, equator) for i in range(first, last+1))
    boundaries = (
        S.Boundary('seam-west', S.TRANSFORM, 'N2', 'N1', tuple(F.vertex(first, j) for j in range(equator, bands))+('N',),
                   F.origin()),
        S.Boundary('seam-east', S.TRANSFORM, 'N2', 'N1',
                   ('N',)+tuple(F.vertex(last, j) for j in range(bands-1, equator-1, -1)), F.origin()),
        S.Boundary('equator-n1', S.TRANSFORM, 'N1', 'S', (n1[0],)+mids+n1[1:], F.origin(), carrier_side='right'),
        S.Boundary('equator-n2', S.TRANSFORM, 'N2', 'S',
                   tuple(F.vertex(i % count, equator) for i in range(last, count+first+1)), F.origin(),
                   carrier_side='right'))
    plates = tuple(S.Plate(name, F.IDENTITY) for name in ('N1', 'N2', 'S'))
    return S.build_network(sphere=F.sphere(), vertices=vertices, faces=faces, plates=plates, boundaries=boundaries,
                           epoch_id=F.EPOCH, time_s=F.START)


class DeclaredVertexTests(unittest.TestCase):
    def test_antipodal_neighbours_still_declare_one_line_in_every_frame(self):
        # Each end segment is a valid quarter circle. The neighbouring vertices are antipodal, so they alone
        # cannot define the shared line. Exercise declaration and endpoint geometry; transferring these coarse
        # cells has the separate, documented conditioned-chart limit.
        source = rotating_north(lons=[0., 90., 180., 270.], sectors=[0])
        vertices = dict(zip(source.vertex_ids, source.vertex_direction.copy()))
        for i, direction in enumerate(((1., 0., 0.), (0., 1., 0.), (-1., 0., 0.), (0., -1., 0.))):
            vertices[F.vertex(i, 2)] = np.asarray(direction)
        for tilt in (F.IDENTITY, Rotation.from_axis_angle((1., 2., 3.), .37)):
            with self.subTest(tilt=tilt.quaternion), np.errstate(invalid='raise', divide='raise'):
                network = S.build_network(source.sphere, {name: tilt.apply(point) for name, point in vertices.items()},
                                          source.faces, source.plates, source.boundaries,
                                          epoch_id=source.epoch_id, time_s=source.time_s)
                poles = dict(network._layout.poles)
                self.assertEqual(poles['equator-n1', 'start'], poles['equator-n2', 'end'])
                self.assertEqual(poles['equator-n1', 'end'], poles['equator-n2', 'start'])
                turn = about((0., 0., 1.), 1., tilt)
                motion = T.Motion(0, 1, {'N1': turn, 'N2': turn, 'S': F.IDENTITY})
                moved = T._moved(network, motion, None)
                endpoint = T._issued(network, moved, MYR, 1, None, None, None)
                for name in (F.vertex(0, 2), F.vertex(1, 2)):
                    before = network.vertex_direction[network.vertex_ids.index(name)]
                    after = endpoint.vertex_direction[endpoint.vertex_ids.index(name)]
                    self.assertLessEqual(float(T._angle(after, turn.apply(before))), ANGULAR)

    def test_a_junction_passes_a_declared_vertex_without_changing_its_position(self):
        rule = CASE4['controls']['declared_vertex_ahead']
        turn = F.spin(control('rotating_north')['omega_deg'])
        for tilt in (F.IDENTITY, Rotation.from_axis_angle((1., 2., 3.), .37)):
            with self.subTest(tilt=tilt.quaternion):
                network = S.rotate_frame(with_mid_vertex(rule['mid_lon_deg']), tilt, 'declared-vertex-tilted')
                initial = network.vertex_direction[network.vertex_ids.index('mid')].copy()
                state = F.crust(network)
                rotation = tilt.inverse().then(turn).then(tilt)
                for k in range(rule['intervals']):
                    state = T.advance(state, T.Motion(k, k+1, {'N1': rotation, 'N2': rotation, 'S': F.IDENTITY}),
                                      end_time_s=(k+1)*MYR).state
                    check_state(self, state)
                self.assertNotIn('mid', state.network.boundary('equator-n1').vertex_ids)
                self.assertIn('mid', state.network.boundary('equator-n2').vertex_ids)
                after = state.network.vertex_direction[state.network.vertex_ids.index('mid')]
                np.testing.assert_array_equal(after, initial)
                self.assertEqual(S.restore_sphere(state.descriptor(), state.arrays()).state_id, state.state_id)

    def test_a_junction_can_land_on_or_pass_multiple_declared_vertices(self):
        rule = CASE4['controls']['declared_vertex_ahead']
        for longitudes, degrees in ((rule['exact_landing_longitudes_deg'], rule['exact_landing_turn_deg']),
                                    (rule['multiple_longitudes_deg'], rule['multiple_turn_deg'])):
            with self.subTest(longitudes=longitudes):
                state = F.crust(with_mid_vertex(longitudes))
                turn = F.spin(degrees)
                state = T.advance(state, T.Motion(0, 1, {'N1': turn, 'N2': turn, 'S': F.IDENTITY}),
                                  end_time_s=MYR).state
                check_state(self, state)
                self.assertFalse(any(name.startswith('mid') for name in
                                     state.network.boundary('equator-n1').vertex_ids))
                if len(longitudes) == 1:
                    self.assertNotIn('mid', state.network.vertex_ids)  # the junction is now the coincident sample
                else:
                    self.assertTrue({'mid', 'mid1', 'mid2'} <= set(state.network.boundary('equator-n2').vertex_ids))
                turn = F.spin(1.)
                state = T.advance(state, T.Motion(1, 2, {'N1': turn, 'N2': turn, 'S': F.IDENTITY}),
                                  end_time_s=2*MYR).state
                check_state(self, state)


class ShallowAndForgedTests(unittest.TestCase):
    def test_lines_crossing_too_shallowly_are_refused(self):
        rule = control('shallow_junction')
        world = rotating_north(lons=list(range(0, 360, 30)), sectors=[3, 4, 5], moved=rule['moved_vertex'])
        state = F.crust(world)
        turn = F.spin(rule['omega_deg'])
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, T.Motion(0, 1, {'N1': turn, 'N2': turn, 'S': F.IDENTITY}), end_time_s=MYR)
        self.assertIn('below 1/16', str(caught.exception))

    def test_a_forged_record_end_pole_is_refused(self):
        import dataclasses
        state = F.crust(rotating_north())
        layout = state.network._layout
        (key, pole), rest = layout.poles[0], layout.poles[1:]
        forged = ((key, tuple(-x for x in pole)),)+rest
        object.__setattr__(state.network, '_layout', dataclasses.replace(layout, poles=forged))
        with self.assertRaises(S.SphereError):
            S.verified(state)


class SaveReopenTests(unittest.TestCase):
    def test_save_reopen_and_continue_in_a_new_process_with_migrating_junctions(self):
        import os
        import subprocess
        import sys
        import tempfile
        rule = control('rotating_north')
        turn = F.spin(rule['omega_deg'])
        motion = lambda k: T.Motion(k, k+1, {'N1': turn, 'N2': turn, 'S': F.IDENTITY})
        state = F.crust(rotating_north())
        saved = None
        for k in range(4):
            state = T.advance(state, motion(k), end_time_s=(k+1)*MYR).state
            if k == 1:
                saved = state
        tests = os.path.dirname(os.path.abspath(__file__))
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, 'state.json'), 'w', encoding='utf-8') as handle:
                json.dump(saved.descriptor(), handle)
            np.savez(os.path.join(folder, 'arrays.npz'), **{k: np.asarray(v) for k, v in saved.arrays().items()})
            env = dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.join(os.path.dirname(tests), 'src'), tests]))
            done = subprocess.run([sys.executable, '-B', '-c', CONTINUE, folder, '2', tests], capture_output=True,
                                  text=True, env=env, timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.split()[-1], state.state_id)                # exactly the uninterrupted state


class RefusalTests(unittest.TestCase):
    def test_a_ridge_trench_slide_without_an_interior_d5_intersection_is_refused(self):
        rule = control('ridge_on_a_trench')
        state = F.crust(hemispheres(fraction=rule['accretion_fraction']))
        axis = F.direction(*rule['axis_lon_lat_deg'])
        motion = T.Motion(0, 1, {'O': F.IDENTITY, 'S1': about(axis, rule['alpha_deg']),
                                 'S2': about(axis, -rule['alpha_deg'])},
                          supplies=F.both_sides('ridge'), sinks=(F.sink('trench-s1'), F.sink('trench-s2')))
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, motion, end_time_s=MYR)
        self.assertIn('D5 intersection X is not inside both the old ridge end segment and the advanced trench end segment',
                      str(caught.exception))

    def test_three_distinct_lines_at_a_junction_are_refused(self):
        # The I03a tipped motion: the ridge, the trench and the boundary between B and C meet at the poles on three
        # different great circles, and three rigid lines cannot stay concurrent.
        state = F.crust(F.three_plates())
        rotation = Rotation.from_axis_angle((0.6, 0.0, 0.8), math.radians(2.))
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, F.one_plate_motion(0., rotations={'A': rotation, 'B': F.IDENTITY, 'C': F.IDENTITY}),
                      end_time_s=MYR)
        self.assertIn('move it to different points', str(caught.exception))
        self.assertIn('reorganise', str(caught.exception))
        self.assertIn('above 1e-11', str(caught.exception))                 # refused by the contract residual (C1)


if __name__ == '__main__':
    unittest.main()
