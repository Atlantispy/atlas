"""Raw-bit controls and refusal boundaries for the bounded optimisation batch.

Scalar references retain the preceding arithmetic and reduction order. These
controls complement the existing physical/geometry tests, not their tolerances.
"""
from dataclasses import replace
import math
import unittest
from unittest import mock

import numpy as np
from scipy.special import erf, erfc
import shapely
from shapely.geometry import Polygon

from atlas_tectonics import geometry as planar
from atlas_tectonics import spherical_atlas as atlas
from atlas_tectonics import spherical_geometry as spherical
from atlas_tectonics import plate_cooling as cooling
from atlas_tectonics.materials import _positive_total
from atlas_tectonics.plate_integrals import _deficit
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from test_w01_spherical_atlas import SPHERE, octants


class BitwiseKernelTests(unittest.TestCase):
    def assertBits(self, actual, expected):
        actual, expected = np.asarray(actual), np.asarray(expected)
        self.assertEqual(actual.shape, expected.shape)
        self.assertEqual(actual.dtype, expected.dtype)
        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_erfc_shared_edges_wide_narrow_and_mixed(self):
        # Both sides of the Gauss threshold, a tail beyond the primitive clamp,
        # and the (phase edge, image, sample) layout used by spreading integrals.
        for column in ([0., .02, 1., 29., 30.], [0., .001, .002, .003, .004],
                       [0., .001, .011, .5, 30.]):
            edges = np.broadcast_to(np.array(column)[:, None, None], (5, 5, 7)).copy()
            expected = np.stack([cooling._erfc_mean(a, b, erfc)
                                 for a, b in zip(edges[:-1], edges[1:])])
            self.assertBits(cooling._erfc_edge_means(edges, erfc), expected)

    def test_batched_cell_mean_keeps_original_image_order(self):
        lo = np.array([0., .01, .4, .8])
        hi = np.array([.003, .09, .7, 1.])
        age = np.array([1e-12, .001, .0625, .01])
        scale = 2*np.sqrt(age)
        mean = cooling._erfc_mean
        expected = (1-mean(lo/scale, hi/scale, erfc)
                    + mean((2-hi)/scale, (2-lo)/scale, erfc)
                    - mean((2+lo)/scale, (2+hi)/scale, erfc)
                    + mean((4-hi)/scale, (4-lo)/scale, erfc)
                    - mean((4+lo)/scale, (4+hi)/scale, erfc))
        self.assertBits(cooling._fraction(lo, age, hi, erf, erfc), expected)

    def test_column_deficit_keeps_original_alternating_reduction(self):
        age = np.array([1e-300, 1e-12, .001, .0625])
        scale = 2*np.sqrt(age)
        expected = np.zeros_like(scale)
        for image in range(5):
            expected += (-1)**image*cooling._erfc_mean(image/scale, (image+1)/scale, erfc)
        self.assertBits(_deficit(age, erfc), expected)

    def test_cross_chart_basis_and_half_edge_angles_keep_scalar_bits(self):
        rng = np.random.default_rng(819)
        a = rng.normal(size=(64, 3)); b = rng.normal(size=(64, 3))
        a[0] = (1., -0., 0.); b[0] = (0., 1., -0.)
        for first, last in zip(a, b):
            self.assertBits(spherical._cross3(first, last), np.cross(first, last))
            centre = spherical._directions(first)
            axis = np.eye(3)[int(np.argmin(np.abs(centre)))]
            east = np.cross(axis, centre); east /= np.linalg.norm(east)
            north = np.cross(centre, east)
            self.assertEqual(spherical._chart_basis(centre), np.array([east, north, centre]).tobytes())
        expected = np.array([2*np.arctan2(np.linalg.norm(x-y, axis=-1),
                                         np.linalg.norm(x+y, axis=-1)) for x, y in zip(a, b)])
        self.assertBits(atlas._angle(a, b), expected)

    def test_batched_ring_crosses_keep_each_dot_and_fsum(self):
        unit = spherical._directions(np.array([[1., .2, .1], [1., .8, .1],
                                              [1., .7, .6], [1., .1, .5], [1., .2, .1]]))
        for anchor in (unit[0], spherical._directions(np.array([1., -.1, -.2]))):
            pieces = []
            for a, b in zip(unit[:-1], unit[1:]):
                numerator = float(np.dot(anchor, np.cross(a-anchor, b-anchor)))
                denominator = 1+float(np.dot(anchor, a))+float(np.dot(a, b))+float(np.dot(b, anchor))
                pieces.append(2*math.atan2(numerator, denominator))
            self.assertEqual(spherical._ring_area(unit, anchor).hex(), abs(math.fsum(pieces)).hex())

    def test_exact_positive_sum_does_not_change_caller_writeability(self):
        values = np.array([1., 2.**-54, 2.**-54, 2.**-53, 0., 1e-300])
        before = values.tobytes()
        self.assertEqual(_positive_total(values).hex(), math.fsum(values).hex())
        self.assertTrue(values.flags.writeable)
        self.assertEqual(values.tobytes(), before)
        readonly = values.view(); readonly.flags.writeable = False
        self.assertEqual(_positive_total(readonly).hex(), math.fsum(values).hex())
        self.assertFalse(readonly.flags.writeable)


class GeometryReuseGuards(unittest.TestCase):
    def assertSameAtlas(self, first, second):
        self.assertEqual(first.descriptor(), second.descriptor())
        for name in ('_points', '_edges', '_sides', '_areas', '_offsets', '_incidence', '_stats'):
            self.assertEqual(getattr(first, name), getattr(second, name))
        for a, b in zip(first.regions, second.regions):
            self.assertEqual(a.geometry.geometry_id, b.geometry.geometry_id)

    def test_same_faces_new_owners_keep_bytes_and_budget_statistics(self):
        vertices, patches = octants()
        support = atlas.build_spherical_atlas(SPHERE, vertices, patches)
        patches = tuple(replace(p, region_id=p.patch_id, plate_id='new-owner') for p in patches)
        ordinary_budget, reuse_budget = WorkBudget(1<<26), WorkBudget(1<<26)
        ordinary = atlas.build_spherical_atlas(SPHERE, vertices, patches, budget=ordinary_budget)
        with mock.patch.object(atlas, '_face_geometry', side_effect=AssertionError('unchanged face rebuilt')):
            reused = atlas.build_spherical_atlas(SPHERE, vertices, patches,
                                                 budget=reuse_budget, reuse_faces_from=support)
        self.assertSameAtlas(ordinary, reused)
        self.assertEqual(ordinary_budget.statistics(), reuse_budget.statistics())

    def test_equal_but_distinct_charts_rebuild(self):
        vertices, patches = octants()
        support = atlas.build_spherical_atlas(SPHERE, vertices, patches)
        changed = tuple(replace(p, chart=spherical.SphericalChart.from_descriptor(p.chart.descriptor()))
                        for p in patches)
        ordinary = atlas.build_spherical_atlas(SPHERE, vertices, changed)
        with mock.patch.object(atlas, '_face_geometry', wraps=atlas._face_geometry) as build:
            reused = atlas.build_spherical_atlas(SPHERE, vertices, changed, reuse_faces_from=support)
        self.assertEqual(build.call_count, len(patches))
        self.assertSameAtlas(ordinary, reused)

    def test_changed_directions_rebuild_and_reversed_ring_still_refuses(self):
        vertices, patches = octants()
        support = atlas.build_spherical_atlas(SPHERE, vertices, patches)
        moved = dict(vertices, px=(1., .001, 0.))
        ordinary = atlas.build_spherical_atlas(SPHERE, moved, patches)
        with mock.patch.object(atlas, '_face_geometry', wraps=atlas._face_geometry) as build:
            reused = atlas.build_spherical_atlas(SPHERE, moved, patches, reuse_faces_from=support)
        self.assertEqual(build.call_count, len(patches))
        self.assertSameAtlas(ordinary, reused)
        reversed_ring = replace(patches[0], vertex_ids=tuple(reversed(patches[0].vertex_ids)))
        with self.assertRaises(planar.GeometryError):
            atlas.build_spherical_atlas(SPHERE, vertices, (reversed_ring, *patches[1:]),
                                        reuse_faces_from=support)

    def test_reused_face_keeps_limits_and_build_reservations(self):
        vertices, patches = octants()
        support = atlas.build_spherical_atlas(SPHERE, vertices, patches)
        patch = support.patches[0]
        with self.assertRaisesRegex(planar.GeometryError, 'vertex limit'):
            atlas._reused_face(support, 0, patch, planar.GeometryLimits(max_vertices=3), WorkBudget(1<<20))
        budget = WorkBudget(16)
        with self.assertRaises(MemoryLimitError):
            atlas._reused_face(support, 0, patch, planar.GeometryLimits(), budget)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_validation_reuse_requires_same_shape_and_same_limits(self):
        shape = Polygon([(0., 0.), (1., 0.), (0., 1.)])
        limits = planar.GeometryLimits()
        planar._validate_shape(shape, limits)
        with mock.patch.object(planar, '_validate_shape', wraps=planar._validate_shape) as check:
            planar._validate_once(shape, limits, (shape, limits))
            self.assertEqual(check.call_count, 0)
            equivalent = shapely.from_wkb(shapely.to_wkb(shape))
            planar._validate_once(equivalent, limits, (shape, limits))
            self.assertEqual(check.call_count, 1)
        with self.assertRaisesRegex(planar.GeometryError, 'vertex limit'):
            planar._validate_once(shape, planar.GeometryLimits(max_vertices=3), (shape, limits))

    def test_post_construction_ring_validation_is_retained(self):
        # Input validation must not certify a different result from the geometry
        # constructor. GEOS validity alone accepts this repeated adjacent row.
        invalid = Polygon([(0., 0.), (1., 0.), (1., 0.), (0., 1.)])
        self.assertTrue(invalid.is_valid)
        with mock.patch.object(planar, 'Polygon', return_value=invalid):
            with self.assertRaisesRegex(planar.GeometryError, 'zero-length edge'):
                planar.PlanarGeometry.polygon([(0., 0.), (1., 0.), (0., 1.)], frame_id='test')

    def test_signed_zero_duplicates_and_large_ring_fallback(self):
        with self.assertRaisesRegex(planar.GeometryError, 'repeats a vertex'):
            planar._vertices([(0., -0.), (1., 0.), (-0., 0.), (0., 1.)], 2,
                             ring=True, limits=planar.GeometryLimits())
        angles = np.linspace(0., 2*math.pi, 4097, endpoint=False)
        ring = np.column_stack((np.cos(angles), np.sin(angles)))
        self.assertEqual(planar._vertices(ring, 2, ring=True,
                                         limits=planar.GeometryLimits()).tobytes(), ring.tobytes())
        repeated = np.vstack((ring, ring[1]))
        with self.assertRaisesRegex(planar.GeometryError, 'repeats a vertex'):
            planar._vertices(repeated, 2, ring=True, limits=planar.GeometryLimits())


if __name__ == '__main__':
    unittest.main()
