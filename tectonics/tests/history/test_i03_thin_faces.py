"""I03a-2: the thin-face round-off bound (C7) and the occupancy allowance it leaves on a face (D7). WORKING NON-CANON.

Approved by the coordinator on 3 October 2026 with four conditions; the first two are tested here. The measured area
of a ring is checked against the same formula evaluated exactly, on the same binary64 numbers, to 90 decimal digits:
a measured error above the derived bound e(ring) fails, and the bound is never adjusted. math.atan2's accuracy of one
unit in the last place, which the derivation assumes, is checked against an exact arctangent.
"""
from decimal import Decimal, localcontext
from fractions import Fraction
import json
import math
import random
import unittest

import numpy as np

import tests.fixtures.i03_fixtures as F
from atlas_tectonics.integration.geometry import sphere as S
from atlas_tectonics.integration import transfer as T

CASE2 = json.loads((F.CASES/'i03_controls_v2.json').read_text(encoding='utf-8'))
MYR = F.MYR_S


def control(name):
    return CASE2['controls'][name]


DIGITS = control('thin_face_bound')['reference_digits']
RELATIVE = F.tolerance('relative')


def _decimal(value):
    """A binary64 value (or an exact Fraction) as a Decimal at the working precision."""
    value = Fraction(value)
    return Decimal(value.numerator)/Decimal(value.denominator)


def _atan(t):
    """arctan(t) of a Decimal, to the working precision: halve the argument, then sum the Taylor series."""
    halvings = 0
    while abs(t) > Decimal('0.01'):
        t = t/(1+(1+t*t).sqrt())
        halvings += 1
    term, total, k, power = t, t, 1, t
    eps = Decimal(10)**(-(DIGITS+5))
    while abs(term) > eps:
        power *= -t*t
        k += 2
        term = power/k
        total += term
    return total*(2**halvings)


def exact_ring_area(ring, anchor):
    """W01's signed fan (spherical_geometry._ring_area) evaluated exactly on the same binary64 numbers."""
    pts = [[Fraction(float(x)) for x in row] for row in np.vstack([ring, ring[:1]])]
    c = [Fraction(float(x)) for x in anchor]
    dot = lambda a, b: a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
    cross = lambda a, b: (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    with localcontext() as context:
        context.prec = DIGITS+10
        total = Decimal(0)
        for a, b in zip(pts[:-1], pts[1:]):
            da, db = [x-y for x, y in zip(a, c)], [x-y for x, y in zip(b, c)]
            numerator = dot(c, cross(da, db))
            denominator = 1+dot(c, a)+dot(a, b)+dot(b, c)
            assert denominator > 0
            total += 2*_atan(_decimal(numerator)/_decimal(denominator))
        return abs(total)


def true_area(rings):
    """The spherical area of the rings' directions normalised exactly (outer minus holes), each fanned from its first
    vertex with the exact arctangent: the area the binary64 rows stand for, not the formula on the same numbers."""
    def unit(v):
        v = [_decimal(float(x)) for x in v]
        norm = (v[0]*v[0]+v[1]*v[1]+v[2]*v[2]).sqrt()
        return [x/norm for x in v]
    dot = lambda a, b: a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
    cross = lambda a, b: (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    with localcontext() as context:
        context.prec = DIGITS+10
        areas = []
        for ring in rings:
            pts = [unit(v) for v in ring]
            total = Decimal(0)
            for b, c in zip(pts[1:-1], pts[2:]):
                a = pts[0]
                denominator = 1+dot(a, b)+dot(b, c)+dot(c, a)
                assert denominator > 0
                total += 2*_atan(dot(a, cross(b, c))/denominator)
            areas.append(abs(total))
        return areas[0]-sum(areas[1:], Decimal(0))


def regular(centre, turn, radius, count, phase, sign):
    """A regular ring of ``count`` vertices at angular ``radius`` about ``centre`` (counter-clockwise if sign > 0)."""
    c = np.array(F.direction(*centre))
    east = np.cross((0., 0., 1.), c)
    east /= np.linalg.norm(east)
    north = np.cross(c, east)
    east, north = math.cos(turn)*east+math.sin(turn)*north, -math.sin(turn)*east+math.cos(turn)*north
    out = []
    for j in range(count):
        a = phase+sign*2*math.pi*j/count
        v = math.cos(radius)*c+math.sin(radius)*(math.cos(a)*east+math.sin(a)*north)
        out.append(v/np.linalg.norm(v))
    return np.array(out)


def off_unit(ring, k):
    """``ring`` scaled by 1 + k eps, with |k| reduced in quarter steps until the stored-direction contract keeps it."""
    eps = float(np.finfo(float).eps)
    while True:
        scaled = ring*(1+k*eps)
        if np.array_equal(S._capture_directions(scaled), scaled):
            return scaled
        k -= math.copysign(.25, k)


def strip(width_m, length_m, per_side, angle):
    """A long thin quadrilateral-like ring (per_side vertices on each long side), turned by ``angle`` about z."""
    radius = F.RADIUS_M
    half_w, half_l = width_m/radius/2, length_m/radius/2
    xs = np.linspace(-half_l, half_l, per_side)
    corners = [(x, -half_w) for x in xs]+[(x, half_w) for x in xs[::-1]]
    ring = np.array([F.direction(math.degrees(x+angle), math.degrees(y)) for x, y in corners])
    return S._capture_directions(ring)+0.


def square(side_m, count, angle, lat_deg):
    radius = F.RADIUS_M
    half = side_m/radius/2
    corners = [(half*math.cos(2*math.pi*k/count+angle), half*math.sin(2*math.pi*k/count+angle)) for k in range(count)]
    ring = np.array([F.direction(30.+math.degrees(x), lat_deg+math.degrees(y)) for x, y in corners])
    return S._capture_directions(ring)+0.


class AreaBoundTests(unittest.TestCase):
    def test_the_measured_area_is_within_its_rounding_bound_of_the_exact_evaluation(self):
        rule = control('thin_face_bound')
        rings = []
        for width in rule['strip_widths_m']:
            for per_side in rule['strip_vertices_per_side']:
                for angle in (0.1, 1.3):
                    rings.append(('strip %g m, %d per side' % (width, per_side),
                                  strip(width, rule['strip_length_km']*1e3, per_side, angle)))
        for side in rule['compact_sides_m']:
            for count in rule['compact_vertices']:
                rings.append(('square %g m, %d vertices' % (side, count), square(side, count, 0.3, -12.)))
        worst = 0.
        for name, ring in rings:
            with self.subTest(ring=name):
                measured = S._measure([ring])
                bound = S._measure_bound([ring])
                self.assertIsNotNone(bound)
                error = abs(Decimal(repr(measured))-exact_ring_area(ring, S._mean_direction(ring)))
                self.assertLessEqual(error, _decimal(bound))
                worst = max(worst, float(error)/bound)
        self.assertLess(worst, 1.)

    def test_math_atan2_is_within_one_ulp_over_the_fan_range(self):
        # The platform assumption of C7's derivation, over the denominators the fan meets (every vertex within 45
        # degrees of the anchor gives D between 1 + sqrt(2) and 4) and numerators from 1e-300 to 1.
        rule = control('thin_face_bound')
        draw = random.Random(20261003)
        worst = 0.
        for _ in range(rule['atan2_samples']):
            x = draw.uniform(1+math.sqrt(2), 4.)
            y = math.copysign(10**draw.uniform(-300, 0), draw.random()-.5)
            value = math.atan2(y, x)
            with localcontext() as context:
                context.prec = DIGITS+10
                exact = _atan(_decimal(y)/_decimal(x))
            error = abs(Decimal(repr(value))-exact)/_decimal(math.ulp(value))
            worst = max(worst, float(error))
            self.assertLessEqual(error, 1, (x, y))
        self.assertLessEqual(worst, 1.)


def merged(network, first, second, name):
    faces = {f.face_id: f for f in network.faces}
    a, b = faces.pop(first), faces.pop(second)
    ra, rb = list(a.vertex_ids), list(b.vertex_ids)
    for i in range(len(ra)):
        u, v = ra[i], ra[(i+1) % len(ra)]
        if v in rb and rb[(rb.index(v)+1) % len(rb)] == u:
            break
    else:
        raise AssertionError('no shared edge')
    pa = [ra[(i+1+k) % len(ra)] for k in range(len(ra))]
    j = rb.index(u)
    pb = [rb[(j+k) % len(rb)] for k in range(len(rb))]
    faces[name] = S.Face(name, a.plate_id, tuple(pa+pb[1:-1]))
    return tuple(faces.values()), a, b


class TrueAreaTests(unittest.TestCase):
    def test_the_measured_area_is_within_its_bound_of_the_true_area_with_holes_and_non_unit_rows(self):
        rule = control('thin_face_true_area')
        radius = math.radians(rule['circumradius_deg'])
        for gap in rule['gaps']:
            for count in rule['vertex_counts']:
                for k in rule['norm_departures_eps']:
                    with self.subTest(gap=gap, count=count, k=k):
                        outer = regular(rule['centre_lon_lat_deg'], rule['turn_rad'], radius, count, rule['phase_rad'], 1)
                        hole = regular(rule['centre_lon_lat_deg'], rule['turn_rad'], (1-gap)*radius, count,
                                       rule['phase_rad'], -1)
                        rings = [off_unit(outer, k), off_unit(hole, -k)]
                        bound = S._measure_bound(rings)
                        self.assertIsNotNone(bound)
                        error = abs(Decimal(repr(S._measure(rings)))-true_area(rings))
                        self.assertLessEqual(error, _decimal(bound))


class ApprovedRangeTests(unittest.TestCase):
    def test_the_bound_exceeds_the_relative_criterion_only_in_the_approved_range(self):
        rule, merge = control('thin_face_range'), control('thin_merge')
        name = merge['first_strip']
        for rate in rule['rates_deg']:
            with self.subTest(rate=rate):
                state = F.crust(F.three_plates())
                for k in range(merge['rides']):
                    state = T.advance(state, F.one_plate_motion(rate, k), end_time_s=(k+1)*MYR).state
                network, step = state.network, state.network.step
                index = network.face_ids.index(name)
                rings = S._rings_of(network, index)
                ring = rings[0]
                ratio = S._measure(rings)/math.fsum(float(T._angle(a, b)) for a, b in zip(ring, np.roll(ring, -1, 0)))
                faces = tuple(S.Face('renamed', f.plate_id, f.vertex_ids, f.holes) if f.face_id == name else f
                              for f in network.faces)
                motion = T.Motion(step, step+1, {p: F.IDENTITY for p in 'ABC'}, mesh=T.Mesh(faces))
                result = T.advance(state, motion, end_time_s=(step+1)*MYR)
                moved = T._issued(network, T._moved(network, motion, None), (step+1)*MYR, motion.end_step,
                                  T._limits(None), None, None)
                donor, receiver = T._audited_mesh(moved, result.state.network, result.map._mesh)
                area = float(network.face_area_m2[index])
                limit = T.THIN_FACE_RATIO
                factor = math.inf if ratio < limit else (2. if ratio < 2*limit else 1.)
                for value in (*donor.values(), *receiver.values()):
                    self.assertLessEqual(value, factor*RELATIVE*area, (rate, ratio))


class BoundSizeTests(unittest.TestCase):
    def test_a_sliver_of_four_bounds_left_out_of_the_rows_is_refused_by_its_closure(self):
        # Whole-face closures may close within E; a sliver of 4 E that the rows leave out must be refused by the
        # closure itself, so that the size of E matters (round 1 of the coordinator's verification).
        rule, merge = control('thin_bound_size'), control('thin_merge')
        state = F.crust(F.three_plates())
        for k in range(merge['rides']):
            state = T.advance(state, F.one_plate_motion(merge['advance_deg'], k), end_time_s=(k+1)*MYR).state
        network, step = state.network, state.network.step
        faces, first, second = merged(network, merge['first_strip'], merge['second_strip'], 'merged')
        joined = [face for face in faces if face.face_id == 'merged'][0]
        neighbour = network.face(rule['neighbour'])
        lookup = {name: i for i, name in enumerate(network.vertex_ids)}
        a_id, b_id = rule['edge']
        local = network._local[network.plate_ids.index('A')]
        a, b = local[lookup[a_id]], local[lookup[b_id]]
        middle = (a+b)/np.linalg.norm(a+b)
        normal = np.cross(a, b)/np.linalg.norm(np.cross(a, b))           # into the neighbour (left of a -> b)
        scale = F.RADIUS_M*F.RADIUS_M
        e = lambda nw, name: S._measure_bound(nw.face_coordinates(nw.face_ids.index(name)))*scale
        plain = T._meshed(network, T.Mesh(faces), T._limits(None), None, None)
        bound = e(network, first.face_id)+e(network, second.face_id)+e(plain, 'merged')
        offset = 2*rule['sliver_bound_multiple']*bound/scale/float(F.angle(a, b))
        x = middle+offset*normal
        x = S._placed(dict(network._layout.frames)['A'], (x/np.linalg.norm(x))[None, :])[0]
        ring, other = list(joined.vertex_ids), list(neighbour.vertex_ids)
        ring.insert(ring.index(b_id)+1, 'X')
        other.insert(other.index(a_id)+1, 'X')
        mesh = T.Mesh(tuple(f for f in faces if f.face_id not in ('merged', neighbour.face_id))
                      + (S.Face('merged', 'A', tuple(ring)), S.Face('t-new', 'A', tuple(other))),
                      (('X', tuple(float(v) for v in x)),))
        motion = T.Motion(step, step+1, {p: F.IDENTITY for p in 'ABC'}, mesh=mesh)
        moved = T._issued(network, T._moved(network, motion, None), (step+1)*MYR, step+1, T._limits(None), None, None)
        endpoint = T._meshed(moved, mesh, T._limits(None), None, None)
        rows = T._mesh_rows(moved, endpoint, None)
        keep = [i for i, (d, r) in enumerate(zip(rows.donor, rows.receiver))
                if not (network.face_ids[d] == neighbour.face_id and endpoint.face_ids[r] == 'merged')]
        self.assertEqual(len(keep), len(rows.donor)-1)
        pick = lambda values: tuple(values[i] for i in keep)
        forged = T._map(network, moved, endpoint, motion, T._Rows((), (), (), (), ()),
                        T._Rows(pick(rows.donor), pick(rows.receiver), pick(rows.party), pick(rows.area_m2),
                                rows.parties))
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, motion, end_time_s=(step+1)*MYR, prepared=forged)
        self.assertIn('overlap rows sum to', str(caught.exception))


def renamed(state, face_id, new_id):
    """One still interval whose mesh change renames ``face_id``."""
    step = state.network.step
    faces = tuple(S.Face(new_id, f.plate_id, f.vertex_ids, f.holes, f.block_id) if f.face_id == face_id else f
                  for f in state.network.faces)
    return T.advance(state, T.Motion(step, step+1, {p: F.IDENTITY for p in 'ABC'}, mesh=T.Mesh(faces)),
                     end_time_s=(step+1)*MYR).state


class AllowanceTests(unittest.TestCase):
    # D7' (round 1): the allowance never grows where the discrepancy does not, and is never a sum of past bounds.
    def test_a_rename_adds_nothing(self):
        rule, merge = control('occupancy_allowance'), control('thin_merge')
        state = F.crust(F.three_plates())
        for k in range(merge['rides']):
            state = T.advance(state, F.one_plate_motion(merge['advance_deg'], k), end_time_s=(k+1)*MYR).state
        step = state.network.step
        faces, _, _ = merged(state.network, merge['first_strip'], merge['second_strip'], 'merged-0')
        state = T.advance(state, T.Motion(step, step+1, {p: F.IDENTITY for p in 'ABC'}, mesh=T.Mesh(faces)),
                          end_time_s=(step+1)*MYR).state
        allowance = float(state.material.occupancy_allowance_m2[state.network.face_ids.index('merged-0')])
        self.assertGreater(allowance, 0.)
        for k in range(rule['renames']):
            state = renamed(state, 'merged-%d' % k, 'merged-%d' % (k+1))
            index = state.network.face_ids.index('merged-%d' % (k+1))
            self.assertEqual(float(state.material.occupancy_allowance_m2[index]), allowance, k)

    def test_above_the_range_a_renamed_face_keeps_a_zero_allowance(self):
        rule = control('occupancy_allowance')['above_range']
        state = F.crust(F.three_plates())
        for k in range(rule['intervals']):
            state = T.advance(state, F.one_plate_motion(rule['rate_deg'], k), end_time_s=(k+1)*MYR).state
        state = renamed(state, rule['face'], 'renamed')
        index = state.network.face_ids.index('renamed')
        self.assertEqual(float(state.material.occupancy_allowance_m2[index]), 0.)

    def test_a_compact_face_merged_from_a_thin_strip_keeps_a_zero_allowance(self):
        # The merged face lies above the range, so its allowance is zero although its thin donor's closure carries a
        # bound (the ceiling of D7').
        merge = control('thin_merge')
        state = F.crust(F.three_plates())
        for k in range(merge['rides']):
            state = T.advance(state, F.one_plate_motion(merge['advance_deg'], k), end_time_s=(k+1)*MYR).state
        network, step = state.network, state.network.step
        strip = network.face(merge['first_strip'])
        cells = [f for f in network.faces if f.plate_id == strip.plate_id and '|' not in f.face_id
                 and len(set(f.vertex_ids) & set(strip.vertex_ids)) == 2]
        self.assertEqual(len(cells), 1, [f.face_id for f in cells])
        faces, _, _ = merged(network, strip.face_id, cells[0].face_id, 'compact')
        state = T.advance(state, T.Motion(step, step+1, {p: F.IDENTITY for p in 'ABC'}, mesh=T.Mesh(faces)),
                          end_time_s=(step+1)*MYR).state
        index = state.network.face_ids.index('compact')
        self.assertEqual(float(state.material.occupancy_allowance_m2[index]), 0.)


class ThinMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rule = cls.rule = control('thin_merge')
        state = F.crust(F.three_plates())
        for k in range(rule['rides']):
            state = T.advance(state, F.one_plate_motion(rule['advance_deg'], k), end_time_s=(k+1)*MYR).state
        cls.ridden = state

    def test_two_thin_strips_merge_ride_and_split_with_exact_accounts(self):
        state, step = self.ridden, self.ridden.step
        faces, first, second = merged(state.network, self.rule['first_strip'], self.rule['second_strip'], 'merged')
        still = T.Motion(step, step+1, {p: F.IDENTITY for p in 'ABC'}, mesh=T.Mesh(faces))
        merge = T.advance(state, still, end_time_s=(step+1)*MYR)
        after = merge.state
        self.assertTrue(after.material.closure()['identity_exact'])
        index = after.network.face_ids.index('merged')
        area = float(after.network.face_area_m2[index])
        held = math.fsum(after.material.stock[after.material.piece_face == index, 0])
        allowance = float(after.material.occupancy_allowance_m2[index])
        self.assertGreater(abs(held-area), 1e-12*area)                    # beyond the existing tolerance ...
        self.assertLessEqual(abs(held-area), allowance)                    # ... and within the bound C7 left on it
        # D7: A = E_receiver + sum over donors (A_s + E_s); each strip lies wholly in the merged face, so its donor
        # closure's bound is e(strip) twice, and the receiver's is e(merged) + e(strip 1) + e(strip 2).
        scale = F.RADIUS_M*F.RADIUS_M
        e = lambda network, face_id: S._measure_bound(network.face_coordinates(network.face_ids.index(face_id)))*scale
        strips = [e(state.network, first.face_id), e(state.network, second.face_id)]
        expected = e(after.network, 'merged')+sum(strips)+sum(2*value for value in strips)
        self.assertLessEqual(abs(allowance-expected), 1e-12*expected)
        rides = T.advance(after, T.Motion(step+1, step+2, {p: F.IDENTITY for p in 'ABC'}),
                          end_time_s=(step+2)*MYR).state                   # the every-interval check holds it there
        self.assertEqual(rides.material.occupancy_allowance_m2[index], allowance)
        apart = tuple(f for f in rides.network.faces if f.face_id != 'merged')+(first, second)
        split = T.advance(rides, T.Motion(step+2, step+3, {p: F.IDENTITY for p in 'ABC'}, mesh=T.Mesh(apart)),
                          end_time_s=(step+3)*MYR).state
        self.assertTrue(split.material.closure()['identity_exact'])
        self.assertEqual(S.restore_sphere(split.descriptor(), split.arrays()).state_id, split.state_id)
        # The same merge with one of its rows enlarged by four times the bound is refused.
        rows = merge.map._mesh
        enlarged = list(rows.area_m2)
        enlarged[0] += 4*allowance
        forged = T._map(state.network, state.network, after.network, still, T._Rows((), (), (), (), ()),
                        T._Rows(rows.donor, rows.receiver, rows.party, tuple(enlarged), rows.parties))
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, still, end_time_s=(step+1)*MYR, prepared=forged)
        self.assertIn('unresolved overlap', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
