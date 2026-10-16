"""I04.1 the declared starting family (atlas.i04-starting-family.v1). WORKING NON-CANON.

ToolParity: the reproductions are bitwise the New World tools (stream_seed, the label draw, the thermal tables).
RequestValidation and NamedRefusals: refusals that need no generated world. EdgePointBounds: the ruling-B2 edge-point
bounds (slerp and the bisector-pole rotation) checked in exact rational arithmetic. AreaMoment: the closed-form first
area moment against analytic shapes, at the existing algebra_relative gate. MinoritySites: the exact n_a rule (review
family-05). Containment: the float prefilter decides nothing (review family-06).
PredeclaredControls: the approved criteria C-7, C-8 (amended bound, ruling B2) and C-9 (ruling B3), on the development
worlds and on the declared review family-04 worlds (N = 4 with long rotation-built edges, N = 52, f > 0.5), and the
non-numerical expectations (reproducibility, stream independence, the seed-41 repeat, land unknown, the opt-in wide
range, refusals, F6' sites, kinds and slabs, derived suture sites, column and slab bounds, P1 family columns under a
Datum). Select a class with -k ClassName.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import new_world_contract as contract
import new_world_structure as structure
import new_world_thermal as thermal

from atlas_tectonics import integration_driving as D
from atlas_tectonics import integration_family as F
from atlas_tectonics import integration_ports as P
from atlas_tectonics import integration_sphere as S
from atlas_tectonics import integration_transfer as T
from atlas_tectonics.coordinates import SphericalFrame
from atlas_tectonics.parameters import PlateCoolingParameters, ThermalParameters
from atlas_tectonics.plate_cooling import finite_plate_temperature
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.spherical_geometry import SphericalChart


CASE = json.loads((Path(__file__).resolve().parents[1]/'cases'/'i04_controls_v1.json').read_text(encoding='utf-8'))
FAMILY = CASE['family']
RADIUS_M = CASE['sphere']['radius_m']
EPOCH = 'i04-family-test-epoch'
EPS = float(np.finfo(float).eps)
STREAMS = ('plate_layout', 'plate_sizes', 'continental_structure', 'crustal_structure', 'thermal_structure',
           'plate_motion', 'setting.radius_m')
SEEDS = ('0'*32, 'f'*32, '0123456789abcdef0123456789abcdef', '%032x' % 41)


def _same(a, b):
    """Bitwise equality of two float sequences (also distinguishes -0.0 and NaN payloads)."""
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return a.shape == b.shape and a.tobytes() == b.tobytes()


def _tool_columns(seed, name):
    """Edges and ages exactly as tools/new_world_structure.py derives them for one column name."""
    crust_seed = contract.stream_seed(seed, 'crustal_structure')
    thermal_seed = contract.stream_seed(seed, 'thermal_structure')
    value = lambda label: structure._draw(crust_seed, name+'/'+label)
    crust = 30000 + 15000*value('thickness')
    litho = 110000 + 40000*value('lithosphere')
    upper = crust*(.45+.15*value('upper-fraction'))
    continental = [0.]
    for thickness in (upper, crust-upper, litho-crust):
        continental.append(continental[-1]+thickness)
    ocean_crust, ocean_litho = 6200+1800*value('thickness'), 125000.
    oceanic = [0.]
    for thickness in (.25*ocean_crust, .75*ocean_crust, ocean_litho-ocean_crust):
        oceanic.append(oceanic[-1]+thickness)
    age = (10+110*structure._draw(thermal_seed, name+'/cooling-age'))*structure.MYR
    return continental, oceanic, age


class ToolParity(unittest.TestCase):
    """C-10: bitwise equality with the New World tools (imported from the tests only)."""

    def test_stream_seed_known_answer_and_tool(self):
        message = b'atlas.new-world.stream.v1\0' + bytes(16) + b'\0plate_layout'
        self.assertEqual(F.stream_seed('0'*32, 'plate_layout'), hashlib.sha256(message).hexdigest()[:32])
        for seed in SEEDS:
            for name in STREAMS:
                self.assertEqual(F.stream_seed(seed, name), contract.stream_seed(seed, name))
        for seed, name in (('0'*32, '../file'), ('0'*32, 'Plate'), ('0'*31, 'plate_layout'),
                           ('A'*32, 'plate_layout'), (0, 'plate_layout')):
            with self.subTest(seed=seed, name=name), self.assertRaises(F.FamilyRefused) as caught:
                F.stream_seed(seed, name)
            self.assertEqual(caught.exception.code, F.INVALID_REQUEST)

    def test_label_draw_matches_structure_draw(self):
        labels = ('area/0', 'shape/2', 'rotation/1', 'background/thickness', 'major-00/weight', 'ocean/plate-03/thermal-age',
                  'site/7/63/azimuth', 'slab/b012/length', 'x'*200)
        for seed in SEEDS:
            for name in ('continental_structure', 'crustal_structure', 'thermal_structure', 'plate_layout'):
                stream = contract.stream_seed(seed, name)
                for label in labels:
                    ours, theirs = F.unit(stream, label), structure._draw(stream, label)
                    self.assertEqual(ours.hex(), theirs.hex())

    def test_continental_profile_bitwise(self):
        cases = [((0.0, 10000.0, 40000.0, 120000.0), (3.0, 2.5, 3.3), (1.5e-6, 0.5e-6, 0.0)),
                 ((0.0, 100000.0), (3.0,), (1.0e-6,))]
        for seed in SEEDS:
            for name in ('background', 'province-0', 'major-03'):
                cases.append((tuple(_tool_columns(seed, name)[0]), (2.5, 2.5, 3.3), (1e-6, .25e-6, .02e-6)))
        keys = ('upward_interface_heat_flux_w_m2', 'integrated_heating_w_m2', 'computed_base_temperature_residual_k')
        for boundaries, k, heat in cases:
            with self.subTest(boundaries=boundaries):
                ours, theirs = F.continental_profile(boundaries, k, heat), thermal.continental_profile(boundaries, k,
                                                                                                        heat)
                self.assertTrue(_same(ours.depths_m, theirs.depths_m))
                self.assertTrue(_same(ours.temperatures_k, theirs.temperatures_k))
                self.assertEqual(ours.max_error_bound_k.hex(), theirs.max_error_bound_k.hex())
                for key in keys:
                    self.assertTrue(_same(ours.descriptor()[key], theirs.descriptor()[key]))
        for bad in (((1.0, 2.0), (3.0,), (1e-6,)), ((0.0, 2.0), (0.0,), (1e-6,)), ((0.0, 1.0, 1.0), (3., 3.), (0., 0.))):
            with self.assertRaises(ValueError):
                thermal.continental_profile(*bad)
            with self.assertRaises(F.FamilyRefused):
                F.continental_profile(*bad)

    def test_continental_sublayers_keep_the_tool_interfaces(self):
        for seed in SEEDS:
            edges = _tool_columns(seed, 'background')[0]
            table, depths, temperatures = F.continental_sublayers(edges)
            tool = thermal.continental_profile(tuple(edges), (2.5, 2.5, 3.3), (1e-6, .25e-6, .02e-6))
            self.assertTrue(_same(table.temperatures_k, tool.temperatures_k))
            self.assertEqual(len(depths), 3*F.SUBLAYERS+1)
            for layer, boundary in enumerate(edges):
                row = layer*F.SUBLAYERS
                self.assertEqual(depths[row].hex(), float(boundary).hex())
                knot = tool.depths_m.index(boundary)
                self.assertEqual(float(temperatures[row]).hex(), tool.temperatures_k[knot].hex())

    def test_ocean_profile_bitwise(self):
        cases = [(thermal.OCEAN_MIN_AGE_S, 125000.0), (thermal.OCEAN_MAX_AGE_S, 125000.0), (37.3*thermal.SECONDS_PER_MA,
                                                                                             125000.0)]
        for seed in SEEDS:
            _, oceanic, age = _tool_columns(seed, 'background')
            cases.append((age, oceanic[-1]))
        for age, thickness in cases:
            with self.subTest(age=age, thickness=thickness):
                ours = F.ocean_profile(age, thickness_m=thickness)
                theirs = thermal.ocean_profile(age, thickness_m=thickness)
                self.assertTrue(_same(ours.depths_m, theirs.depths_m))
                self.assertTrue(_same(ours.temperatures_k, theirs.temperatures_k))
                self.assertEqual(ours.max_error_bound_k.hex(), theirs.max_error_bound_k.hex())
        for age in (thermal.OCEAN_MIN_AGE_S*0.999, thermal.OCEAN_MAX_AGE_S*1.001):
            with self.assertRaises(ValueError):
                thermal.ocean_profile(age)
            with self.assertRaises(F.FamilyRefused):
                F.ocean_profile(age)


def _request(**changes):
    values = dict(seed='%032x' % 1, radius_m=RADIUS_M, plate_count=12, continental_fraction=.35, epoch_id=EPOCH,
                  time_s=0., support_level=1)
    values.update(changes)
    return F.FamilyRequest(**values)


class RequestValidation(unittest.TestCase):
    def test_bad_requests_refused(self):
        for field, values in (('seed', ('A'*32, '0'*31, 41, None)), ('radius_m', (True, math.nan, 1e6, 2e8, '6e6')),
                              ('plate_count', (1, 53, 12.0, True)), ('continental_fraction', (-.1, 1.1, math.nan,
                                                                                               True)),
                              ('epoch_id', ('', '   ', 3)), ('time_s', (math.inf, 2e18)),
                              ('support_level', (-1, 4, 1.0)), ('range', ('Wide', 'extreme', None))):
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(F.FamilyRefused) as caught:
                    _request(**{field: value})
                self.assertEqual(caught.exception.code, F.INVALID_REQUEST)
        with self.assertRaises(F.FamilyRefused) as caught:
            F.starting_family(dict(seed='0'*32))
        self.assertEqual(caught.exception.code, F.INVALID_REQUEST)

    def test_numpy_scalars_accepted_as_numbers(self):
        plain = _request()
        numpy = _request(radius_m=np.float64(RADIUS_M), plate_count=np.int64(12), continental_fraction=np.float64(.35),
                         time_s=np.float32(0.), support_level=np.int32(1))
        self.assertEqual(plain.record(), numpy.record())
        self.assertEqual({type(v) for v in numpy.record().values()} - {str}, {int, float})
        for field, value in (('plate_count', np.float64(12.)), ('support_level', np.bool_(True)),
                             ('continental_fraction', np.float64(np.nan))):
            with self.assertRaises(F.FamilyRefused):
                _request(**{field: value})

    def test_default_range_is_the_safe_one(self):
        self.assertEqual(_request().range, 'default')
        self.assertEqual(_request().record()['range'], 'default')
        self.assertEqual(_request(range='wide').record()['range'], 'wide')


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v/np.linalg.norm(v)


class NamedRefusals(unittest.TestCase):
    """Ruling C2 refusals that need no generated world."""

    def test_three_or_fewer_sites_refused_by_name(self):
        for count in (2, 3):
            with self.assertRaises(F.FamilyRefused) as caught:
                F.starting_family(_request(plate_count=count))
            self.assertEqual(caught.exception.code, F.LAYOUT_REFUSED)
            self.assertIn('N_UNSUPPORTED', str(caught.exception))

    def test_cocircular_and_bit_equal_vertices_refused_by_name(self):
        angles = np.arange(6)*(2*math.pi/6)
        great_circle = np.column_stack((np.cos(angles), np.sin(angles), np.zeros(6)))
        with self.assertRaises(F.FamilyRefused) as caught:
            F._voronoi(great_circle)
        self.assertIn('COCIRCULAR_SITES', str(caught.exception))
        cube = np.array([_unit((x, y, z)) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)])
        with self.assertRaises(F.FamilyRefused) as caught:
            F._voronoi(cube)
        self.assertEqual(caught.exception.code, F.LAYOUT_REFUSED)
        self.assertIn('DEGENERATE_VORONOI_VERTEX', str(caught.exception))


def _exact_plane_distance(point, a, b):
    """|p.(a x b)| / (|a x b| |p|) with the numerator and a x b exact (the slerp_offplane.py measure)."""
    A, B, X = ([Fraction(float(v)) for v in row] for row in (a, b, point))
    n = [A[1]*B[2]-A[2]*B[1], A[2]*B[0]-A[0]*B[2], A[0]*B[1]-A[1]*B[0]]
    dot = abs(sum(x*m for x, m in zip(X, n)))
    return float(dot)/math.sqrt(float(sum(m*m for m in n)))/math.sqrt(float(sum(x*x for x in X)))


def _synthetic_edge(rng, degrees, offset_eps=(0, 0)):
    """Two Voronoi vertices of a chosen separation and two sites mirrored across their great circle.

    ``offset_eps`` pushes each vertex off that circle by a multiple of eps, so the rotation's d_a and d_b terms are
    exercised; the sites' bisector plane is the circle's plane.
    """
    a = _unit(rng.normal(size=3))
    q = _unit(np.cross(a, rng.normal(size=3)))
    theta = math.radians(degrees)
    b = _unit(math.cos(theta)*a+math.sin(theta)*q)
    n = _unit(np.cross(a, b) if degrees < 179 else np.cross(a, q))
    a, b = _unit(a+offset_eps[0]*EPS*n), _unit(b+offset_eps[1]*EPS*n)
    middle = _unit(a+b) if degrees < 179 else q
    first = _unit(math.cos(.3)*middle+math.sin(.3)*n)
    sites = np.array([first, first-2*float(first @ n)*n])          # mirror images: bisector normal n
    vertices = np.array([a, b])
    return F._edge(sites, vertices, 0, 1, 0, 1), vertices


class EdgePointBounds(unittest.TestCase):
    """Ruling B2: every edge point within its declared bound, in exact rational arithmetic (as slerp_offplane.py)."""

    def test_slerp_points_within_bound_and_reversal_symmetric(self):
        rng = np.random.default_rng(20261003)
        degrees = [0.001, 0.1, 1., 10., 45., 60., 90., 110., 119.9, 119.999]+list(rng.uniform(0.01, 120., 40))
        for deg in degrees:
            edge, vertices = _synthetic_edge(rng, deg)
            self.assertEqual(edge['construction'], 'slerp')
            a, b = vertices[edge['start']], vertices[edge['end']]
            theta = edge['theta']
            self.assertEqual(edge['bound'], 0.5*EPS*(2+1/math.cos(theta/2)))
            reverse = dict(edge, start=edge['end'], end=edge['start'])
            for level in range(1, 6):
                for k in range(1, 2**level):
                    t = Fraction(k, 2**level)
                    point = F._arc(edge, vertices, t)
                    self.assertLessEqual(_exact_plane_distance(point, a, b), edge['bound'])
                    self.assertTrue(_same(point, F._arc(reverse, vertices, 1-t)))
            self.assertTrue(_same(F._arc(edge, vertices, Fraction(0)), a))
            self.assertTrue(_same(F._arc(edge, vertices, Fraction(1)), b))

    def test_rotation_points_within_derived_bound(self):
        rng = np.random.default_rng(1003)
        degrees = [120.5, 130., 150., 170., 175., 179., 179.9, 179.99, 179.999]+list(rng.uniform(120.1, 179.99, 30))
        worst = 0.
        for deg in degrees:
            for offsets in ((0, 0), (5, -3), (-20, 12), (40, 40)):
                edge, vertices = _synthetic_edge(rng, deg, offsets)
                self.assertEqual(edge['construction'], 'rotation')
                start = vertices[edge['start']]
                pole = edge['pole']
                own = F.off_plane(start, pole)
                self.assertEqual(edge['bound'], max(own+F.ROTATION_ROUNDING,
                                                    F.off_plane(vertices[edge['end']], pole)))
                self.assertLessEqual(edge['bound'], F.POINT_BAND_RAD)
                for level in range(1, 6):
                    for k in range(1, 2**level):
                        distance = F.off_plane(F._arc(edge, vertices, Fraction(k, 2**level)), pole)
                        self.assertLessEqual(distance, own+F.ROTATION_ROUNDING)
                        worst = max(worst, (distance-own)/EPS)
        print('\nrotation edges: largest interior excess over d_a %.3f eps (declared 4 eps)' % worst, file=sys.stderr)

    def test_point_bound_beyond_the_band_refused_by_name(self):
        rng = np.random.default_rng(7)
        with self.assertRaises(F.FamilyRefused) as caught:
            _synthetic_edge(rng, 150., (70, 0))
        self.assertIn('EDGE_POINT_BOUND', str(caught.exception))


class AreaMoment(unittest.TestCase):
    """int_Omega n dA in closed form, against analytic shapes (existing algebra_relative gate, no new number)."""

    def check(self, ring, expected):
        got = F.area_moment(np.array(ring, dtype=np.float64))
        scale = float(np.linalg.norm(expected))
        self.assertLessEqual(float(np.max(np.abs(got-np.asarray(expected)))), T.ALGEBRA_RELATIVE*scale)
        flipped = F.area_moment(np.array(ring[::-1], dtype=np.float64))
        self.assertLessEqual(float(np.max(np.abs(flipped+np.asarray(expected)))), T.ALGEBRA_RELATIVE*scale)

    def test_octant_hemisphere_and_split_lune(self):
        self.check([(1, 0, 0), (0, 1, 0), (0, 0, 1)], (math.pi/4,)*3)
        self.check([(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0)], (0., 0., math.pi))
        self.check([(0, 0, -1), (0, 1, 0), (0, 0, 1), (1, 0, 0)], (math.pi/2, math.pi/2, 0.))


class MinoritySites(unittest.TestCase):
    """Review family-05: n_a = floor(N s + 1/2) exactly on the Fraction of the binary64 f, rounding half up."""

    def test_ties_round_half_up_and_the_swap_is_symmetric(self):
        self.assertEqual(F.minority_sites(4, .375), 2)            # N s = 1.5 exactly: half up
        self.assertEqual(F.minority_sites(4, .625), 2)            # the same tie under the swap
        self.assertEqual(F.minority_sites(12, .125), 2)
        self.assertEqual(F.minority_sites(12, .875), 2)
        self.assertEqual(F.minority_sites(4, .5), 2)              # f = 0.5: the oceanic-background branch, 2.5 -> 2
        # The exact rational of the binary64 0.35 is just below 0.35, so 10 s + 1/2 is just below 4.
        self.assertEqual(Fraction(.35) < Fraction(35, 100), True)
        self.assertEqual(F.minority_sites(10, .35), 3)
        for count in range(4, 53):
            for k in range(65):
                f = k/64                                          # dyadic: 1 - f is exact in binary64
                self.assertEqual(F.minority_sites(count, f), F.minority_sites(count, 1-f), (count, f))

    def test_clamp_and_pure_worlds(self):
        self.assertEqual(F.minority_sites(12, 0.), 0)
        self.assertEqual(F.minority_sites(12, 1.), 0)
        self.assertEqual(F.minority_sites(12, 1e-6), 1)
        self.assertEqual(F.minority_sites(12, 1-1e-6), 1)
        self.assertEqual(F.minority_sites(4, .5), 2)
        for count in range(4, 53):
            for f in (1e-9, .1, .35, .5, .65, .9, 1-1e-9):
                share = Fraction(f) if f <= .5 else 1-Fraction(f)
                expected = min(max(math.floor(count*share+Fraction(1, 2)), 1), count-1)
                self.assertEqual(F.minority_sites(count, f), expected)


class Containment(unittest.TestCase):
    """Review family-06: the PREFILTER_MARGIN float prefilter decides nothing; the exact integer signs decide."""

    def test_prefilter_decides_nothing(self):
        chart = SphericalChart(SphericalFrame(RADIUS_M, 'containment-test'), tuple(_unit((.3, -.2, .9))))
        xy = F._planar(.3, [.7, .2, .9, .4], [.1, 1.2, 2.3, 3.4], 2.5, .7)
        outline = F._Outline(chart.centre, chart._unproject(.25*xy))
        rng = np.random.default_rng(6)
        v = outline.outline
        w = np.roll(v, -1, axis=0)
        near = []
        for scale in (0., 1e-15, 1e-13, 1e-9):
            normal = _unit_rows(np.cross(v, w))
            for sign in (1., -1.):
                near.append(_unit_rows(_unit_rows(v+w)+sign*scale*normal))
        near.append(v)
        near.append(_unit_rows(rng.normal(size=(200, 3))*.3+np.asarray(chart.centre)))
        points = np.vstack(near)
        filtered = outline.contains(points)
        with mock.patch.object(F, 'PREFILTER_MARGIN', 4.):        # every fan triangle passes: pure exact decisions
            exact = outline.contains(points)
        self.assertTrue(np.array_equal(filtered, exact))
        self.assertTrue(np.all(outline.contains(v)))              # outline vertices: on the closed polygon


# ----------------------------------------------------------------------------- the approved controls

# Declared before running (review family-04). N = 4 worlds, among which rotation-built edges over 160 degrees are
# expected (about half of random N = 4 site sets have one; ruling B2), an N = 52 pair and f > 0.5 swap worlds. C-7,
# C-8 and C-9 run on every world in these lists; at least one N = 4 world must have a rotation edge over 160 degrees,
# or this list itself is inadequate (a failure, not a reason to search further).
LONG_EDGE_WORLDS = tuple((seed, 4, f, rng) for rng in ('default', 'wide') for f in (.02, .35) for seed in range(1, 9))
SIZE_WORLDS = ((1, 52, .35, 'default'), (2, 52, .35, 'wide'), (3, 30, .6, 'default'), (4, 12, .65, 'default'),
               (5, 12, .65, 'wide'))
SWAP_FRACTION = .65

_BUILT = {}


def _family(seed, count, fraction, level, rng='default'):
    """One family (or its refusal), memoised for the run."""
    key = (seed, count, fraction, level, rng)
    if key not in _BUILT:
        try:
            _BUILT[key] = F.starting_family(F.FamilyRequest('%032x' % seed if type(seed) is int else seed, RADIUS_M,
                                                            count, fraction, EPOCH, 0., level, rng))
        except F.FamilyRefused as exc:
            _BUILT[key] = exc
    return _BUILT[key]


def _development():
    for rng in FAMILY['ranges']:
        for seed in FAMILY['development_seeds']:
            yield seed, rng


def _faces_by_plate(network):
    shapes = T._Shapes(network)
    out = {plate: [] for plate in network.plate_ids}
    for index, (face, area) in enumerate(zip(network.faces, network.face_area_m2)):
        out[face.plate_id].append((shapes.rings(index), float(area)))
    return out


def _unit_rows(v):
    v = np.asarray(v, dtype=np.float64)
    return v/np.linalg.norm(v, axis=-1, keepdims=True)


def _c7_m2(rings, area, radius):
    """The range-limited C7 of one face in m2 (ruling B2.4): E, min(E, 2e-12 mu) or 0; undefined fails closed."""
    ceiling = T._c7_range_limit(rings, area)
    if ceiling == 0.:
        return 0.
    bound = S._measure_bound(rings)
    if bound is None:
        return math.nan
    return min((bound*radius)*radius, ceiling)


class PredeclaredControls(unittest.TestCase):
    """The approved criteria and expectations (decisions proposal section 6 with rulings B, C, F6', P6)."""

    levels = tuple(FAMILY['resolution_levels'])

    def pair(self, seed, rng, count=None, fraction=None):
        count = FAMILY['development_plate_count'] if count is None else count
        fraction = FAMILY['development_continental_fraction'] if fraction is None else fraction
        first, second = (_family(seed, count, fraction, level, rng) for level in self.levels)
        if isinstance(first, F.FamilyRefused) or isinstance(second, F.FamilyRefused):
            self.assertTrue(isinstance(first, F.FamilyRefused) and isinstance(second, F.FamilyRefused))
            self.assertEqual((first.code, str(first)), (second.code, str(second)))
            return None
        return first, second

    def check_c7(self, pair):
        one, two = (family.geometry for family in pair)
        self.assertEqual(one.geometry_id, two.geometry_id)
        self.assertEqual(json.dumps(one.record(), sort_keys=True), json.dumps(two.record(), sort_keys=True))
        arrays = dict(two.arrays())
        for name, array in one.arrays():
            self.assertEqual((array.dtype, array.shape), (arrays[name].dtype, arrays[name].shape))
            self.assertEqual(array.tobytes(), arrays[name].tobytes(), name)
        self.assertEqual(sorted(pair[0].columns), sorted(pair[1].columns))
        for column_id, column in pair[0].columns.items():
            other = pair[1].columns[column_id]
            self.assertEqual(column.record(), other.record())
            for key in ('depths_m', 'temperatures_k', 'density_kg_m3', 'alpha_per_k'):
                self.assertEqual(getattr(column, key).tobytes(), getattr(other, key).tobytes())

    def check_c8(self, pair):
        """C-8 on one pair of levels; returns the largest gap/bound."""
        radius = pair[0].network.sphere.radius_m
        terms = pair[0].geometry.boundary_terms_m2()
        faces = [_faces_by_plate(family.network) for family in pair]
        reports = [family.report() for family in pair]
        worst = 0.
        for plate in pair[0].network.plate_ids:
            bound = math.fsum([_c7_m2(rings, area, radius)+S.RELATIVE_TOLERANCE*area
                               for level in faces for rings, area in level[plate]]+[terms[plate]])
            self.assertFalse(math.isnan(bound), 'C7 undefined in the thin range for plate %s' % plate)
            for key in ('plate_area_m2', 'plate_continental_area_m2'):
                gap = abs(reports[0][key][plate]-reports[1][key][plate])
                self.assertLessEqual(gap, bound, '%s %s' % (plate, key))
                worst = max(worst, gap/bound)
        return worst

    def check_c9(self, family, count, fraction):
        """C-9 on one family; returns (error, bound)."""
        report = family.report()
        self.assertEqual(len(family.network.plate_ids), count)
        self.assertEqual(len(family.geometry.sites), count)
        self.assertEqual(report['plate_count'], count)
        radius = family.network.sphere.radius_m
        occupancy = math.fsum(S.RELATIVE_TOLERANCE*float(mu) for mu in family.network.face_area_m2)
        allowed = 2e-11+occupancy/(4*math.pi*radius*radius)
        error = abs(report['realised_continental_fraction']-fraction)
        self.assertLessEqual(error, allowed)
        return error, allowed

    def test_c7_declared_geometry_bitwise_across_levels(self):
        for seed, rng in _development():
            with self.subTest(seed=seed, range=rng):
                pair = self.pair(seed, rng)
                if pair is not None:
                    self.check_c7(pair)

    def test_c8_plate_areas_across_levels(self):
        for seed, rng in _development():
            with self.subTest(seed=seed, range=rng):
                pair = self.pair(seed, rng)
                if pair is not None:
                    print('\nC-8 seed %d %s: largest |A(L1)-A(L2)|/bound %.3e' % (seed, rng, self.check_c8(pair)),
                          file=sys.stderr)

    def test_c9_exact_initial_controls(self):
        count, fraction = FAMILY['development_plate_count'], FAMILY['development_continental_fraction']
        worst = (0., 0.)
        for seed, rng in _development():
            for level in self.levels:
                with self.subTest(seed=seed, range=rng, level=level):
                    family = _family(seed, count, fraction, level, rng)
                    if not isinstance(family, F.FamilyRefused):
                        worst = max(worst, self.check_c9(family, count, fraction))
        print('\nC-9: largest |f_realised - f| %.3e (its bound %.3e)' % worst, file=sys.stderr)

    def test_c9_under_the_swap(self):
        """Review family-04: C-9 for f > 0.5, where f_realised = 1 - minority area / 4 pi R^2 (ruling B3)."""
        count, worst, built = FAMILY['development_plate_count'], (0., 0.), 0
        for seed, rng in _development():
            for level in self.levels:
                with self.subTest(seed=seed, range=rng, level=level):
                    family = _family(seed, count, SWAP_FRACTION, level, rng)
                    if isinstance(family, F.FamilyRefused):
                        continue
                    self.assertEqual(family.geometry.minority_type, F.OCEANIC)
                    worst = max(worst, self.check_c9(family, count, SWAP_FRACTION))
                    built += 1
        self.assertGreater(built, 0)
        print('\nC-9 at f = %.2f: largest |f_realised - f| %.3e (its bound %.3e), %d worlds' % (
            SWAP_FRACTION, *worst, built), file=sys.stderr)

    def test_c7_c8_c9_on_declared_review_worlds(self):
        """Review family-04: N = 4 worlds with rotation-built edges over 160 deg, N = 52 and f > 0.5 worlds."""
        long_edges, worst_c8, worst_c9, lines = 0, 0., (0., 0.), []
        for seed, count, fraction, rng in LONG_EDGE_WORLDS+SIZE_WORLDS:
            with self.subTest(seed=seed, count=count, fraction=fraction, range=rng):
                pair = self.pair(seed, rng, count, fraction)
                if pair is None:
                    lines.append('seed %d N %d f %.2f %s: REFUSED %s' % (
                        seed, count, fraction, rng, _family(seed, count, fraction, self.levels[0], rng)))
                    continue
                g = pair[0].geometry
                rotation = [math.degrees(float(a)) for a, c in zip(g.edge_angles_rad, g.edge_constructions)
                            if c == 'rotation']
                long_edges += count == 4 and any(a > 160 for a in rotation)
                self.check_c7(pair)
                ratio = self.check_c8(pair)
                worst_c8 = max(worst_c8, ratio)
                for family in pair:
                    worst_c9 = max(worst_c9, self.check_c9(family, count, fraction))
                lines.append('seed %d N %d f %.2f %s: rotation edges %d (longest %.1f deg); C-8 ratio %.3e' % (
                    seed, count, fraction, rng, len(rotation), max(rotation, default=0.), ratio))
        print('\n'+'\n'.join(lines)+'\nreview worlds: N = 4 worlds with a rotation edge over 160 deg: %d; largest '
              'C-8 ratio %.3e; largest C-9 error %.3e (bound %.3e)' % (long_edges, worst_c8, *worst_c9),
              file=sys.stderr)
        self.assertGreater(long_edges, 0)

    def test_refusal_rates_and_kind_shares_reported(self):
        count, fraction = FAMILY['development_plate_count'], FAMILY['development_continental_fraction']
        lines = []
        for seed, rng in _development():
            family = _family(seed, count, fraction, FAMILY['development_support_level'], rng)
            if isinstance(family, F.FamilyRefused):
                lines.append('seed %d %-7s REFUSED %s: %s' % (seed, rng, family.code, family))
                continue
            report = family.report()
            shares, edges, sites = report['kind_shares'], report['edges'], report['site_counts']
            flag = ''
            if rng == 'default' and (not shares[S.TRENCH]['count'] or not shares[S.RIDGE]['count']):
                flag = '  <-- DEFAULT WORLD WITH ZERO %s' % ('TRENCHES' if not shares[S.TRENCH]['count'] else 'RIDGES')
            lines.append('seed %d %-7s trench %d ridge %d transform %d (length shares %.2f/%.2f/%.2f); sites anchored '
                         '%d, minority-drawn %d, free %d; rotation edges %d; shortest edge %.1f km; edges below '
                         'k H_max %d; anchor notes %d%s' % (
                             seed, rng, *(shares[k]['count'] for k in (S.TRENCH, S.RIDGE, S.TRANSFORM)),
                             *(shares[k]['length_share'] for k in (S.TRENCH, S.RIDGE, S.TRANSFORM)),
                             sites['anchored'], sites['minority_drawn'], sites['free'], edges['rotation'],
                             edges['shortest_m']/1e3, edges['shorter_than_column_scale'], len(report['anchor_notes']),
                             flag))
            self.assertAlmostEqual(math.fsum(shares[k]['count_share'] for k in shares), 1., places=12)
        print('\n'+'\n'.join(lines), file=sys.stderr)

    def test_reproducible_identity(self):
        request = _request()
        self.assertEqual(F.starting_family(request).family_id, F.starting_family(request).family_id)

    def test_geology_independent_of_plate_count_and_level(self):
        base = _family(1, 12, .35, 1)
        for other in (_family(1, 8, .35, 1), _family(1, 12, .35, 2), _family(1, 30, .35, 1)):
            self.assertEqual([p.record() for p in base.geometry.provinces], [p.record() for p in other.geometry.provinces])
            for p, q in zip(base.geometry.provinces, other.geometry.provinces):
                for key in ('centre', 'outline', 'moment_sr', 'centroid'):
                    self.assertEqual(getattr(p, key).tobytes(), getattr(q, key).tobytes())
            self.assertEqual([s.record() for s in base.geometry.sutures], [s.record() for s in other.geometry.sutures])
            for s, t in zip(base.geometry.sutures, other.geometry.sutures):
                self.assertEqual((s.start.tobytes(), s.end.tobytes(), s.sites.tobytes()),
                                 (t.start.tobytes(), t.end.tobytes(), t.sites.tobytes()))
            for column_id, column in base.columns.items():
                if column_id.startswith('continental:'):
                    self.assertEqual(column.record(), other.columns[column_id].record())
                    self.assertEqual(column.temperatures_k.tobytes(), other.columns[column_id].temperatures_k.tobytes())

    def test_seed41_repeat_changes_the_layout(self):
        record = FAMILY['seed41']
        first, second = (_family(record['seed'], record['plate_count'], f, record['support_level'])
                         for f in record['continental_fraction'])
        self.assertFalse(isinstance(first, F.FamilyRefused) or isinstance(second, F.FamilyRefused))
        self.assertNotEqual(first.geometry.sites.tobytes(), second.geometry.sites.tobytes())
        moved = float(np.max(F._angle(first.geometry.sites, second.geometry.sites)))
        print('\nseed-41 repeat: max site displacement %.6f rad (%.1f km)' % (moved, moved*RADIUS_M/1e3),
              file=sys.stderr)

    def test_continent_is_not_land(self):
        family = _family(1, 12, .35, 1)
        report = family.report()
        self.assertEqual(report['land'], 'UNKNOWN')
        self.assertFalse(any('land' in key for key in report if key != 'land'))
        self.assertGreater(report['unknown_formation_age_share'], 0.)
        self.assertEqual(report['assumed_thermal_history_share'], 1.)
        for cohort in family.material.cohorts:
            self.assertEqual(cohort.formation_start_s is None, cohort.cohort_id.startswith('oceanic:'))

    def test_wide_range_recorded_and_never_default(self):
        default, wide = _family(1, 12, .35, 1), _family(1, 12, .35, 1, 'wide')
        self.assertFalse(isinstance(wide, F.FamilyRefused), str(wide))
        self.assertNotEqual(default.family_id, wide.family_id)
        self.assertEqual((default.report()['range'], wide.report()['range']), ('default', 'wide'))
        self.assertEqual((default.geometry.floor_k, wide.geometry.floor_k), (1., .5))
        self.assertTrue(all('#wide:' in c.origin_id for c in wide.material.cohorts))
        self.assertFalse(any('wide' in c.origin_id for c in default.material.cohorts))
        self.assertTrue(all(p.geotherm_note == F.THIN_GEOTHERM for p in wide.geometry.provinces))
        self.assertTrue(all(p.geotherm_note is None for p in default.geometry.provinces))

    def test_refusals(self):
        below = _family(1, 12, 1e-6, 1)
        self.assertIsInstance(below, F.FamilyRefused)
        self.assertEqual(below.code, F.STRUCTURE_REFUSED)
        between = 1e-4                       # between the k = 0.5 and k = 1 floors at the control radius
        self.assertIsInstance(_family(1, 12, between, 1), F.FamilyRefused)
        admitted = _family(1, 12, between, 1, 'wide')
        self.assertNotIsInstance(admitted, F.FamilyRefused, str(admitted))
        floor = math.pi*(.5*F.H_MAX_M/RADIUS_M)**2
        self.assertTrue(all(p.target_area_sr >= floor for p in admitted.geometry.provinces))
        with mock.patch.object(F, 'MAX_ATTEMPTS', 0):
            for fraction, code in ((.35, F.STRUCTURE_REFUSED), (0., F.LAYOUT_REFUSED)):
                with self.assertRaises(F.FamilyRefused) as caught:
                    F.starting_family(_request(continental_fraction=fraction))
                self.assertEqual(caught.exception.code, code)

    def test_f6_prime_sites_kinds_slabs_and_densities(self):
        count, fraction = 12, .35
        target = min(max(math.floor(count*Fraction(fraction)+Fraction(1, 2)), 1), count-1)   # F6', exact
        for seed, rng in _development():
            family = _family(seed, count, fraction, 1, rng)
            if isinstance(family, F.FamilyRefused):
                continue
            g = family.geometry
            origins = [origin.split(':') for origin in g.site_origins]
            kinds_of = [parts[0] for parts in origins]
            self.assertEqual(sum(kind in ('anchor', 'minority-drawn') for kind in kinds_of), target)
            self.assertEqual(kinds_of.count('free'), count-target)
            self.assertEqual(kinds_of[:target], sorted(kinds_of[:target]))      # anchors before minority-drawn
            self.assertEqual(g.counts['minority_sites'], target)
            for kind, site, crust in zip(kinds_of, g.sites, g.site_types):
                self.assertEqual(crust, F.CONTINENTAL if kind != 'free' else F.OCEANIC)
                if kind != 'anchor':
                    self.assertEqual(g.province_at(site) is not None, kind == 'minority-drawn')
            mirrored = {}
            for index, parts in enumerate(origins):
                if parts[0] == 'anchor' and len(parts) == 4:
                    mirrored.setdefault(tuple(parts[1:3]), []).append(index)
            pairs = {tuple(sorted(group)) for group in mirrored.values()}
            self.assertTrue(all(len(pair) == 2 for pair in pairs))
            report = family.report()
            self.assertEqual(report['site_counts']['anchored']+report['site_counts']['minority_drawn'], target)
            slabs = {slab.boundary_id: slab for slab in g.slabs}
            for e, (kind, side) in enumerate(zip(g.edge_kinds, g.edge_subducting)):
                cells = tuple(int(c) for c in g.edge_cells[e])
                left, right = (g.site_types[c] for c in cells)
                expected = S.TRANSFORM if cells in pairs else S.RIDGE if left == right else S.TRENCH
                self.assertEqual(kind, expected)
                self.assertEqual(g.boundary_ids[e] in slabs, kind == S.TRENCH)
                if kind == S.TRENCH:
                    subducting = g.plate_ids[int(g.edge_cells[e][0 if side == 'left' else 1])]
                    self.assertEqual(g.site_types[g.plate_ids.index(subducting)], F.OCEANIC)
                    slab = slabs[g.boundary_ids[e]]
                    column = family.columns['oceanic:'+subducting]
                    self.assertEqual(slab.subducting_plate_id, subducting)
                    self.assertEqual(slab.section_anomaly_kg_m, slab.length_m*column.mantle_deficit_kg_m2())
                    self.assertGreater(slab.deficit_kg_m2, 0.)
                    lo, hi = F.RANGES[rng]['slab_length_m']
                    self.assertTrue(lo <= slab.length_m < hi)
            for column in family.columns.values():
                lid = [i for i, (_, phase, _) in enumerate(column.layers) if phase == 'mantle-lid'][0]
                rows = column.density_kg_m3[lid*F.SUBLAYERS:(lid+1)*F.SUBLAYERS]
                self.assertTrue(np.all(rows == F.MANTLE_REFERENCE_KG_M3))

    def test_suture_span_and_derived_mirrored_sites(self):
        """Ruling family-01: span in [K/4, 3K/4] (declared); the pair is the larger part's centroid and its mirror."""
        lo, hi = F.SUTURE_SPAN_VERTICES
        self.assertEqual((lo, hi), (F.OUTLINE_VERTICES//4, 3*F.OUTLINE_VERTICES//4))
        seen = paired = 0
        for seed, rng in _development():
            family = _family(seed, 12, .35, 1, rng)
            if isinstance(family, F.FamilyRefused):
                continue
            g = family.geometry
            self.assertEqual(g.record()['suture_span_vertices'], [lo, hi])
            self.assertEqual(family.report()['declared']['suture_span_vertices'], [lo, hi])
            provinces = {p.name: (p, outline) for p, outline in zip(g.provinces, g._outlines)}
            for suture in g.sutures:
                seen += 1
                first, second = suture.vertices
                self.assertTrue(lo <= (second-first) % F.OUTLINE_VERTICES <= hi)
                province, outline = provinces[suture.province]
                pole = S._stable_pole(np.asarray(suture.start), np.asarray(suture.end))
                parts = [F._part(outline, sign*pole) for sign in (1., -1.)]
                whole_area = F._anchored_area(province.outline, province.centre)
                whole_moment = F.area_moment(province.outline)
                self.assertLessEqual(abs(parts[0][0]+parts[1][0]-whole_area), T.ALGEBRA_RELATIVE*whole_area)
                self.assertLessEqual(float(np.linalg.norm(parts[0][1]+parts[1][1]-whole_moment)),
                                     T.ALGEBRA_RELATIVE*float(np.linalg.norm(whole_moment)))
                larger = max(parts, key=lambda part: part[0])
                self.assertEqual(suture.part_areas_sr, (larger[0], min(part[0] for part in parts)))
                site, mirror = suture.sites
                self.assertTrue(_same(site, larger[1]/np.linalg.norm(larger[1])))
                self.assertTrue(_same(mirror, site-2*float(F._dot3(site, pole))*pole))     # mirrored
                indices = [i for i, o in enumerate(g.site_origins) if o.split(':')[2:3] == [suture.suture_id]]
                if indices:
                    paired += 1
                    self.assertEqual(len(indices), 2)
                    self.assertTrue(_same(g.sites[indices[0]], site) and _same(g.sites[indices[1]], mirror))
                    edge = [e for e, cells in enumerate(g.edge_cells)
                            if tuple(int(c) for c in cells) == tuple(indices)]
                    for e in edge:
                        self.assertEqual(g.edge_kinds[e], S.TRANSFORM)
        print('\nsutures: %d in the development worlds, %d used as mirrored site pairs' % (seen, paired),
              file=sys.stderr)
        self.assertGreater(seen, 0)

    def test_column_and_slab_bounds(self):
        """Review family-03: derived column bound and S quadrature offset against the continuous profile."""
        nodes, weights = np.polynomial.legendre.leggauss(24)
        worst_t = worst_s = 0.
        for seed, rng in _development():
            family = _family(seed, 12, .35, 1, rng)
            if isinstance(family, F.FamilyRefused):
                continue
            for column in family.columns.values():
                record = column.record()
                self.assertEqual(record['column_bound_k'], column.interpolation_bound_k())
                self.assertIn('table only', record['table_bound'])
                self.assertIn('table only', record['thermal_model']['bound_scope'])
            for slab in family.geometry.slabs:
                column = family.columns[slab.column_id]
                record = slab.record()
                self.assertIn('trapezoid', record['quadrature'])
                depths, temps = column.depths_m, column.temperatures_k
                parameters = PlateCoolingParameters(thermal=ThermalParameters(
                    'test', 'test', F.SURFACE_K, F.BASE_K, 1e-6), thickness_m=float(depths[-1]),
                    conductivity_w_m_k=3.3)
                lid = [phase for _, phase, _ in column.layers].index('mantle-lid')
                exact, worst_column = [], 0.
                for row in range(lid*F.SUBLAYERS, (lid+1)*F.SUBLAYERS):
                    top, bottom = float(depths[row]), float(depths[row+1])
                    z = (top+bottom)/2+(bottom-top)/2*nodes
                    t = np.asarray(finite_plate_temperature(z, column.thermal_age_s, parameters))
                    exact.append(float(column.density_kg_m3[row])*float(column.alpha_per_k[row])*(bottom-top)/2*
                                 math.fsum(weights*(F.BASE_K-t)))
                    linear = np.interp(z, [top, bottom], [float(temps[row]), float(temps[row+1])])
                    worst_column = max(worst_column, float(np.max(np.abs(linear-t))))
                self.assertLessEqual(worst_column, column.interpolation_bound_k())
                offset = abs(slab.section_anomaly_kg_m-slab.length_m*math.fsum(exact))
                self.assertLessEqual(offset, slab.quadrature_bound_kg_m)
                worst_t = max(worst_t, worst_column)
                if slab.section_anomaly_kg_m:
                    worst_s = max(worst_s, offset/slab.section_anomaly_kg_m)
        print('\ncolumns: largest |linear sublayer - finite plate| %.2f K in the mantle lid; slabs: largest '
              'measured |S - continuous S|/S %.4f' % (worst_t, worst_s), file=sys.stderr)

    def test_budget_refused_by_name(self):
        """Review family-02: an admitted request beyond the work budget refuses by name, never MemoryLimitError."""
        for request, budget in ((_request(), WorkBudget(1 << 20)), (_request(plate_count=30, support_level=3), None)):
            with self.assertRaises(F.FamilyRefused) as caught:
                F.starting_family(request, budget=budget)
            self.assertEqual(caught.exception.code, F.LAYOUT_REFUSED)
            self.assertIn('BUDGET_EXCEEDED', str(caught.exception))

    def test_minority_drawn_sites_fill_unfilled_slots(self):
        """F6-prime addendum: when anchors cannot fill n_a, the rest are drawn inside minority crust, not anchors."""
        exercised = 0
        for seed in (1, 2, 3):
            for count, fraction in ((52, .35), (30, .6)):
                family = _family(seed, count, fraction, 0)
                if isinstance(family, F.FamilyRefused):
                    continue
                g = family.geometry
                target = min(max(math.floor(count*min(fraction, 1-fraction)+.5), 1), count-1)
                kinds_of = [origin.split(':')[0] for origin in g.site_origins]
                minority = F.CONTINENTAL if fraction <= .5 else F.OCEANIC
                background = F.OCEANIC if fraction <= .5 else F.CONTINENTAL
                self.assertEqual(sum(k in ('anchor', 'minority-drawn') for k in kinds_of), target)
                self.assertEqual(kinds_of.count('free'), count-target)
                drawn = kinds_of.count('minority-drawn')
                exercised += drawn > 0
                for kind, site, crust in zip(kinds_of, g.sites, g.site_types):
                    self.assertEqual(crust, background if kind == 'free' else minority)
                    if kind != 'anchor':
                        self.assertEqual(g.province_at(site) is not None, kind == 'minority-drawn')
                report = family.report()['site_counts']
                self.assertEqual((report['anchored'], report['minority_drawn'], report['free']),
                                 (kinds_of.count('anchor'), drawn, count-target))
                if drawn:
                    # Anchors are the largest provinces first, fragments included (ruling F6-prime: "as before,
                    # largest provinces first"): a site is drawn only once every province has anchored.
                    anchored = {origin.split(':')[1] for origin in g.site_origins if origin.startswith('anchor:')}
                    # A province may anchor nothing only when its centroid failed the separation rule (recorded).
                    skipped = {note.split(' ')[0] for note in g.anchor_notes if 'within 2 k H_max' in note}
                    self.assertEqual(anchored | skipped, {p.name for p in g.provinces}, (seed, count, fraction))
                    self.assertFalse(anchored & skipped)
        self.assertGreater(exercised, 0)

    def test_datum_gate_is_exact_on_both_fields(self):
        """Round-2 ruling: v1 families exist only on the 3300 kg/m3 / 293.15 K datum; a twin datum with another T_ref
        that happens to derive the same mantle-lid density is refused too."""
        family = _family(1, 12, .35, 1)
        support = P.trace_support(family.network)
        target = F.mantle_reference_density(F.MANTLE_DATUM_KG_M3, F.DATUM_REFERENCE_K)
        t_ref, rho = 273.15, None
        guess = target*(1-F.ALPHA_PER_K*(F.BASE_K-t_ref))
        candidate = guess
        for _ in range(64):
            if F.mantle_reference_density(candidate, t_ref) == target:
                rho = candidate
                break
            candidate = np.nextafter(candidate, np.inf if F.mantle_reference_density(candidate, t_ref) < target
                                     else -np.inf)
        self.assertIsNotNone(rho, 'no exact twin datum found near the guess')
        base = CASE['gpe_hemispheres']['datum']
        # The twin; then each field alone off the v1 datum, the other exact. A T_ref one ulp above 293.15 with the
        # density exactly 3300 derives the same mantle-lid density, so only the T_ref comparison refuses it.
        t_near = float(np.nextafter(F.DATUM_REFERENCE_K, np.inf))
        self.assertEqual(F.mantle_reference_density(F.MANTLE_DATUM_KG_M3, t_near), target)
        for fields in (dict(mantle_density_kg_m3=float(rho), reference_temperature_k=t_ref),
                       dict(mantle_density_kg_m3=F.MANTLE_DATUM_KG_M3, reference_temperature_k=t_near),
                       dict(mantle_density_kg_m3=float(np.nextafter(F.MANTLE_DATUM_KG_M3, np.inf)),
                            reference_temperature_k=F.DATUM_REFERENCE_K)):
            datum = D.Datum(**dict(base, **fields))
            header = P.Header('P1', family.state.state_id, (0, 0, 0., 0.), 0., family.network.network_id,
                              support.support_id, D.datum_id(datum), family.family_id, family.network.sphere.frame_id,
                              'test', F.SCHEMA)
            with self.assertRaises(P.PortRefused, msg=str(fields)) as caught:
                F.family_columns(family, support, header, datum)
            self.assertEqual((caught.exception.code, caught.exception.detail), (P.STALE_IDENTITY, 'datum_id'), fields)

    def test_mirrored_sites_take_their_province_type(self):
        """Round-2 ruling, option 1: a mirrored pair's plates take the province's crust type, even where the mirror
        lands in ocean."""
        landed = 0
        for seed, rng in _development():
            family = _family(seed, 12, .35, 1, rng)
            if isinstance(family, F.FamilyRefused):
                continue
            g = family.geometry
            for origin, site, crust in zip(g.site_origins, g.sites, g.site_types):
                if origin.startswith('anchor:') and origin.endswith(':mirror'):
                    self.assertEqual(crust, F.CONTINENTAL, origin)
                    if g.crust_at(site) != F.CONTINENTAL:
                        landed += 1
        self.assertGreater(landed, 0, 'no mirror landed in ocean on the development worlds')

    def test_p1_family_columns(self):
        family = _family(1, 12, .35, 1)
        support = P.trace_support(family.network)
        state = family.state
        datum = D.Datum(**CASE['gpe_hemispheres']['datum'])

        def header(**changes):
            values = dict(port='P1', parent_state_id=state.state_id, interval=(0, 0, state.time_s, state.time_s),
                          endpoint_s=state.time_s, network_id=support.network_id, support_id=support.support_id,
                          datum_id=D.datum_id(datum), parameter_id=family.family_id,
                          frame_id=family.network.sphere.frame_id, owner='I05 (Part A: family columns)',
                          producer=F.SCHEMA)
            values.update(changes)
            return P.Header(**values)
        columns = F.family_columns(family, support, header(), datum)
        self.assertEqual(columns.points, 2*support.edges)
        self.assertFalse(np.any(columns.unknown))
        for point in range(columns.points):
            edge, side = divmod(point, 2)
            expected = family.column_at(support.midpoint[edge], support.plates[edge][side])
            self.assertEqual(columns.sources[point], expected.column_id)
            layers = columns.layers(point)
            self.assertEqual(len(layers[0]), 3*F.SUBLAYERS)
            for got, want in zip(layers, expected.bottom_to_top()):
                self.assertEqual(got.tobytes(), np.ascontiguousarray(want, dtype=np.float64).tobytes())
            self.assertEqual((float(layers[3][0]), float(layers[4][-1])), (F.BASE_K, F.SURFACE_K))
            # No density jump at the base of the lithosphere under this datum (ruling P6): the lid's reference
            # density is the one this datum derives.
            self.assertEqual(float(layers[1][0]), F.mantle_reference_density(datum.mantle_density_kg_m3,
                                                                              datum.reference_temperature_k))
        # A datum that differs only where the columns do not depend on it (pressure, gravity) is accepted.
        other = D.Datum(**dict(CASE['gpe_hemispheres']['datum'], pressure_pa=6.5e9, gravity_m_s2=9.8))
        F.family_columns(family, support, header(datum_id=D.datum_id(other)), other)
        refusals = (
            (dict(parent_state_id='0'*64), datum, P.STALE_IDENTITY, 'parent_state_id'),
            (dict(parameter_id='0'*64), datum, P.STALE_IDENTITY, 'parameter_id'),
            (dict(network_id='0'*64), datum, P.STALE_IDENTITY, 'network_id'),
            (dict(support_id='0'*64), datum, P.INCOMPATIBLE_SUPPORT, 'support_id'),
            (dict(frame_id='another-frame'), datum, P.STALE_IDENTITY, 'frame_id'),
            (dict(datum_id='0'*64), datum, P.STALE_IDENTITY, 'datum_id'),
            (dict(interval=(0, 1, state.time_s, state.time_s+1.), endpoint_s=state.time_s+1.), datum, P.UNSUPPORTED,
             D.EVALUATION),
            # Part A: endpoint at the START of the interval (ruling P4 / D-P3), never its end.
            (dict(interval=(0, 1, state.time_s-1e13, state.time_s), endpoint_s=state.time_s), datum, P.UNSUPPORTED,
             D.EVALUATION))
        for changes, used, code, detail in refusals:
            with self.subTest(changes=changes), self.assertRaises(P.PortRefused) as caught:
                F.family_columns(family, support, header(**changes), used)
            self.assertEqual((caught.exception.code, caught.exception.detail), (code, detail))
        # Mismatched datums (review ports-03): another mantle fill or reference temperature, even when the header
        # names that datum, would put a density jump at the base of the lithosphere: refused, never rebuilt.
        for change in (dict(mantle_density_kg_m3=3200.), dict(mantle_density_kg_m3=3190.),
                       dict(reference_temperature_k=273.15)):
            mismatched = D.Datum(**dict(CASE['gpe_hemispheres']['datum'], **change))
            for named in (mismatched, datum):
                with self.subTest(change=change, named=named is datum), \
                        self.assertRaises(P.PortRefused) as caught:
                    F.family_columns(family, support, header(datum_id=D.datum_id(named)), mismatched)
                self.assertEqual((caught.exception.code, caught.exception.detail), (P.STALE_IDENTITY, 'datum_id'))
        with self.assertRaises(P.PortRefused) as caught:
            F.family_columns(family, support, header(), D.datum_id(datum))
        self.assertEqual((caught.exception.code, caught.exception.detail), (P.MISSING_VALUE, 'datum'))


if __name__ == '__main__':
    unittest.main()
