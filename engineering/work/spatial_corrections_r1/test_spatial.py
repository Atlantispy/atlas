"""Small independent numerical and actual-pinned-source-invocation fixtures.
Run: python -m unittest work.spatial_corrections_r1.test_spatial -v
No production source import, map generation, saved map mutation or domain promotion.
"""
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from scipy import ndimage

from . import (Grid, SpatialError, categorical, cell_fractions, extensive,
               intensive, sample_cells, prepare_b1a3_fields, prepare_c1r7_fields,
               sample_political_evidence, require_native_contacts, verify_sources)
from .adapters import PINS, SourcePinError, _assignments, _source, _strict_shape


def brute_totals(a, source, target):
    # Independent physical rectangle intersection, not the sparse overlap builder.
    out = np.zeros(target.shape, float)
    for tr in range(target.shape[0]):
        for tc in range(target.shape[1]):
            tx = sorted([target.origin_x+tc*target.step_x,
                         target.origin_x+(tc+1)*target.step_x])
            ty = sorted([target.origin_y+tr*target.step_y,
                         target.origin_y+(tr+1)*target.step_y])
            for sr in range(source.shape[0]):
                for sc in range(source.shape[1]):
                    sx = sorted([source.origin_x+sc*source.step_x,
                                 source.origin_x+(sc+1)*source.step_x])
                    sy = sorted([source.origin_y+sr*source.step_y,
                                 source.origin_y+(sr+1)*source.step_y])
                    area = max(0, min(tx[1], sx[1])-max(tx[0], sx[0])) * max(
                        0, min(ty[1], sy[1])-max(ty[0], sy[0]))
                    out[tr, tc] += a[sr, sc]*area/abs(source.step_x*source.step_y)
    return out


def fixture(shape=(4, 5)):
    g = Grid(shape, 0, 0, 4, 4)
    x, y = g.centres()
    field = 2*x[None, :]+3*y[:, None]+7
    mask = np.indices(shape).sum(axis=0) % 2 == 0
    a2 = dict(predicted_conditioned_surface_m=field, sea_mask=mask,
              inward_mask=~mask, crown_mask=mask)
    r11 = dict(provisional_surface_m=field, competence_prior=field,
               erodibility_prior=field/100, fracture_prior=field/200,
               crown_support=field/300, derived_sea_mask=mask)
    r30 = dict(crown_divide_mask_public=mask, actual_outlet_route_mask_public=~mask)
    return g, a2, r11, r30


class GridTests(unittest.TestCase):
    def test_grid_validation(self):
        for shape in ((0, 1), (2.0, 2), (True, 2), (1,), [2, 2]):
            with self.subTest(shape=shape), self.assertRaises(SpatialError):
                Grid(shape, 0, 0, 1, 1)
        for args in ((0, 0, 0, 1, "km"), (0, 0, 1, np.inf, "km"),
                     (0, 0, 1, 1, "degrees")):
            with self.assertRaises(SpatialError):
                Grid((2, 2), *args)

    def test_centres_and_negative_orientation(self):
        g = Grid((2, 3), 10, 20, 2, -4)
        assert_array_equal(g.centres()[0], [11, 13, 15])
        assert_array_equal(g.centres()[1], [18, 14])
        self.assertEqual(g.bounds, (10, 12, 16, 20))
        self.assertEqual(g.area, 8)

    def test_derived_grid_overflow_collapse_and_boolean_rejected(self):
        for args in (((2, 2), 0, 0, 1e308, 1), ((2, 2), 0, 0, 1e200, 1e200),
                     ((2, 2), 1e20, 0, 1, 1), ((2, 2), 0, 0, 1e-200, 1e-200),
                     ((2, 2), True, 0, 1, 1), ((2, 2), 0, 0, True, 1)):
            with self.subTest(args=args), self.assertRaises(SpatialError):
                Grid(*args)

    def test_crop_origin_and_bounds(self):
        g = Grid((5, 6), 10, 30, 2, -4).crop(1, 4, 2, 5)
        self.assertEqual(g, Grid((3, 3), 14, 26, 2, -4))
        with self.assertRaises(SpatialError):
            g.crop(0, 8, 0, 1)

    def test_units_not_silently_mixed(self):
        a = Grid((2, 2), 0, 0, 1, 1, "km")
        b = Grid((2, 2), 0, 0, 1, 1, "m")
        for method in (intensive, extensive, categorical):
            with self.assertRaises(SpatialError):
                method(np.ones((2, 2), int), a, b)


class IntensiveTests(unittest.TestCase):
    def test_affine_linear_independent_oracle(self):
        source = Grid((4, 5), 10, -6, 4, 3)
        x, y = source.centres()
        a = 2*x[None, :]-3*y[:, None]+17
        target = Grid((12, 20), 10, -6, 1, 1)
        out = intensive(a, source, target)
        tx, ty = target.centres()
        expected = 2*np.clip(tx, 12, 28)[None, :]-3*np.clip(ty, -4.5, 4.5)[:, None]+17
        assert_allclose(out.values, expected, rtol=0, atol=2e-14)
        self.assertTrue(out.valid.all())

    def test_legacy_zoom_regression_has_known_error(self):
        source = Grid((2, 8), 0, 0, 4, 4)
        target = Grid((16, 64), 0, 0, .5, .5)
        a = np.tile(np.arange(8, dtype=float)*4+2, (2, 1))
        correct = intensive(a, source, target).values[5]
        old = ndimage.zoom(a, 8, order=1, mode="nearest")[5]
        expected = np.clip(np.arange(64)*.5+.25, 2, 30)
        assert_allclose(correct, expected, atol=0, rtol=0)
        self.assertAlmostEqual(np.max(np.abs(old-expected)), 1.5277777777777786)

    def test_linear_and_cubic_constant_and_identity(self):
        g = Grid((4, 5), 0, 0, 4, 4)
        fine = Grid((16, 20), 0, 0, 1, 1)
        for order in (1, 3):
            with self.subTest(order=order):
                assert_allclose(intensive(np.full(g.shape, 9.5), g, fine, order=order).values,
                                9.5, rtol=0, atol=1e-13)
                a = np.arange(20).reshape(g.shape)
                assert_allclose(intensive(a, g, g, order=order).values, a, atol=1e-13)

    def test_orientation_reversal(self):
        s = Grid((2, 3), 0, 8, 4, -4)
        t = Grid((2, 3), 12, 0, -4, 4)
        a = np.arange(6).reshape(2, 3)
        assert_array_equal(intensive(a, s, t).values, a[::-1, ::-1])

    def test_shift_outside_is_missing_not_clamped(self):
        s = Grid((2, 2), 0, 0, 4, 4)
        t = Grid((2, 3), -4, 0, 4, 4)
        r = intensive(np.ones((2, 2)), s, t)
        self.assertTrue(np.isnan(r.values[:, 0]).all())
        self.assertFalse(r.valid[:, 0].any())
        assert_array_equal(r.values[:, 1:], 1)

    def test_missing_stencil_not_renormalised(self):
        s = Grid((2, 2), 0, 0, 4, 4)
        a = np.array([[0., np.nan], [4., 6.]])
        m = np.array([[True, False], [True, True]])
        t = Grid((1, 1), 2, 2, 4, 4)
        r = intensive(a, s, t, valid=m)
        self.assertFalse(r.valid.item())
        self.assertTrue(np.isnan(r.values.item()))
        self.assertAlmostEqual(r.support_fraction.item(), .75)
        with self.assertRaises(SpatialError):
            intensive(a, s, t, valid=m, order=3)

    def test_zero_weight_missing_neighbour_keeps_known_cell(self):
        s = Grid((2, 2), 0, 0, 4, 4)
        a = np.array([[0., np.nan], [4., 6.]])
        r = intensive(a, s, s, valid=np.isfinite(a))
        self.assertTrue(r.valid[0, 0])
        self.assertEqual(r.values[0, 0], 0)
        self.assertFalse(r.valid[0, 1])

    def test_tiny_positive_unknown_interpolation_is_still_unknown(self):
        s = Grid((2, 2), 0, 0, 1, 1)
        t = Grid((1, 1), 1e-14, 0, 1, 1)
        a = np.array([[2., np.nan], [2., np.nan]])
        r = intensive(a, s, t, valid=np.isfinite(a))
        self.assertFalse(r.valid.item())
        self.assertTrue(np.isnan(r.values.item()))
        with self.assertRaises(SpatialError):
            intensive(np.ones((2, 2)), s, s, order=True)

    def test_multiband_and_input_preservation(self):
        s = Grid((2, 2), 0, 0, 4, 4)
        a = np.arange(8., dtype=float).reshape(2, 2, 2)
        before = a.copy()
        r = intensive(a, s, Grid((4, 4), 0, 0, 2, 2))
        assert_array_equal(a, before)
        self.assertEqual(r.values.shape, (2, 4, 4))

    def test_shape_dtype_mask_and_nonfinite_errors(self):
        s = Grid((2, 2), 0, 0, 4, 4)
        for a, kw in ((np.ones((3, 3)), {}), (np.full((2, 2), np.nan), {}),
                      (np.ones((2, 2)), {"valid": np.ones((2, 2), int)}),
                      (np.ones((2, 2)), {"valid": np.ones((3, 3), bool)}),
                      (np.ones((2, 2)), {"order": 0})):
            with self.assertRaises(SpatialError):
                intensive(a, s, s, **kw)


class CoverageTests(unittest.TestCase):
    def test_political_half_cell_regression_and_boundary(self):
        g = Grid((2, 3), 0, 0, 4, 4)
        a = np.array([[10, 20, 30], [40, 50, 60]])
        r = sample_cells(a, g, [0, 2, 3, 3.999, 4, 11.999], [0]*6)
        assert_array_equal(r.values, [10, 10, 10, 10, 20, 30])
        self.assertNotEqual(a[0, int(np.rint(3/4))], r.values[2])
        for x in (-.0001, 12, np.nan, np.inf):
            with self.assertRaises(SpatialError):
                sample_cells(a, g, x, 0)

    def test_negative_stride_half_open_pixel_boundaries(self):
        g = Grid((2, 2), 8, 8, -4, -4)
        a = np.array([[1, 2], [3, 4]])
        assert_array_equal(sample_cells(a, g, [8, 4, .001], [8, 4, .001]).values, [1, 4, 4])
        with self.assertRaises(SpatialError):
            sample_cells(a, g, 0, 4)

    def test_multiband_point_broadcast(self):
        g = Grid((2, 2), 0, 0, 4, 4)
        a = np.arange(8).reshape(2, 2, 2)
        r = sample_cells(a, g, [1, 5], [[1], [5]])
        assert_array_equal(r.values, a)

    def test_categorical_exact_coverage_labels_preserved(self):
        s = Grid((2, 3), 0, 0, 4, 4)
        t = Grid((8, 12), 0, 0, 1, 1)
        a = np.array([[0, 7, 100], [3, 7, 9]], dtype=np.int64)
        r = categorical(a, s, t)
        assert_array_equal(r.values, a.repeat(4, 0).repeat(4, 1))
        self.assertTrue(r.valid.all())
        self.assertEqual(set(np.unique(r.values)), set(np.unique(a)))
        with self.assertRaises(SpatialError):
            categorical(a.astype(float), s, t)

    def test_categorical_mask_and_outside_preserved(self):
        s = Grid((2, 2), 0, 0, 4, 4)
        a = np.array([[0, 1], [2, 3]])
        m = np.array([[True, False], [True, True]])
        t = Grid((2, 3), -4, 0, 4, 4)
        r = categorical(a, s, t, valid=m)
        assert_array_equal(r.valid, [[False, True, False], [False, True, True]])
        self.assertEqual(r.values[0, 1], 0)  # valid zero is not missing


class ConservativeTests(unittest.TestCase):
    def test_extensive_split_and_aggregate(self):
        s = Grid((2, 2), 0, 0, 4, 4)
        a = np.array([[16, 32], [48, 64]])
        t = Grid((4, 4), 0, 0, 2, 2)
        r = extensive(a, s, t)
        assert_array_equal(r.values, a.repeat(2, 0).repeat(2, 1)/4)
        self.assertEqual(r.values.sum(), a.sum())
        assert_array_equal(extensive(r.values, t, s).values, a)

    def test_independent_rectangle_oracle_noninteger_ratio_and_orientation(self):
        rng = np.random.default_rng(872)
        for sy in (-2., 2.):
            for sx in (-3., 3.):
                s = Grid((3, 2), 6 if sx < 0 else 0, 6 if sy < 0 else 0, sx, sy)
                a = rng.uniform(0, 20, s.shape)
                t = Grid((4, 5), 0, 0, 1.2, 1.5)
                r = extensive(a, s, t)
                assert_allclose(r.values, brute_totals(a, s, t), rtol=0, atol=2e-14)
                self.assertAlmostEqual(r.values.sum(), a.sum(), places=12)
                self.assertTrue(r.valid.all())

    def test_partial_domain_must_be_explicit(self):
        s = Grid((2, 2), 0, 0, 4, 4)
        t = Grid((1, 1), 2, 2, 4, 4)
        a = np.array([[16., 32.], [48., 64.]])
        with self.assertRaises(SpatialError):
            extensive(a, s, t)
        r = extensive(a, s, t, allow_partial_domain=True)
        assert_allclose(r.values, [[40]])
        self.assertNotEqual(r.values.sum(), a.sum())

    def test_missing_or_uncovered_area_is_not_zero(self):
        s = Grid((2, 2), 0, 0, 4, 4)
        t = Grid((1, 1), 0, 0, 8, 8)
        a = np.array([[0., np.nan], [32., 48.]])
        r = extensive(a, s, t, valid=np.isfinite(a))
        self.assertFalse(r.valid.item())
        self.assertTrue(np.isnan(r.values.item()))
        self.assertEqual(r.support_fraction.item(), .75)
        u = extensive(np.ones((2, 2)), s, Grid((1, 1), -4, 0, 8, 8), allow_partial_domain=True)
        self.assertEqual(u.support_fraction.item(), .5)
        self.assertTrue(np.isnan(u.values.item()))

    def test_fractional_class_coverage_not_interpolated_labels(self):
        s = Grid((2, 2), 0, 0, 4, 4)
        t = Grid((1, 1), 0, 0, 8, 8)
        a = np.array([[0, 7], [7, 100]])
        r = cell_fractions(a, s, t, [0, 7, 100])
        assert_array_equal(r.values[:, 0, 0], [.25, .5, .25])
        self.assertEqual(r.values.sum(), 1)
        for classes in ([], [7, 7]):
            with self.assertRaises(SpatialError):
                cell_fractions(a, s, t, classes)

    def test_tiny_unknown_overlap_and_uncovered_sliver_are_unknown(self):
        s = Grid((1, 2), 0, 0, 1, 1)
        t = Grid((1, 1), 0, 0, 1+1e-14, 1)
        a = np.array([[2., np.nan]])
        r = extensive(a, s, t, valid=np.isfinite(a), allow_partial_domain=True)
        self.assertFalse(r.valid.item())
        self.assertTrue(np.isnan(r.values.item()))
        outside = Grid((1, 1), -1e-14, 0, 1, 1)
        u = extensive(np.ones((1, 2)), s, outside, allow_partial_domain=True)
        self.assertFalse(u.valid.item())
        with self.assertRaises(SpatialError):
            extensive(np.ones((1, 2)), s, s, allow_partial_domain=1)

    def test_multiband_conservation(self):
        s = Grid((2, 3), 4, 3, 2, 3)
        t = Grid((3, 4), 4, 3, 1.5, 2)
        a = np.arange(12.).reshape(2, 2, 3)
        r = extensive(a, s, t)
        assert_allclose(r.values.sum(axis=(-2, -1)), a.sum(axis=(-2, -1)), atol=1e-13)


class ProducerIntegrationTests(unittest.TestCase):
    def test_b1a3_actual_source_all_eleven_fields(self):
        g, a2, r11, r30 = fixture()
        before = [a.copy() for d in (a2, r11, r30) for a in d.values()]
        t = Grid((16, 20), 0, 0, 1, 1)
        p = prepare_b1a3_fields(a2, r11, r30, g, t)
        self.assertEqual(len(p.fields), 11)
        x = np.clip(np.arange(20)+.5, 2, 18)
        y = np.clip(np.arange(16)+.5, 2, 14)
        assert_allclose(p.fields["comp"], 2*x[None, :]+3*y[:, None]+7, atol=0)
        for out, data, key in (("sea", a2, "sea_mask"), ("divide", r30, "crown_divide_mask_public"),
                               ("outlet_route", r30, "actual_outlet_route_mask_public")):
            assert_array_equal(p.fields[out], data[key].repeat(4, 0).repeat(4, 1))
        self.assertEqual(p.receipt["sha256"], PINS["b1a3"]["sha256"])
        self.assertFalse(p.receipt["downstream_model_executed"])
        for a, old in zip((a for d in (a2, r11, r30) for a in d.values()), before):
            assert_array_equal(a, old)

    def test_b1a3_invalid_and_unknown_inputs_rejected(self):
        g, a2, r11, r30 = fixture()
        a2["sea_mask"] = a2["sea_mask"].astype(float)
        a2["sea_mask"][0, 0] = np.nan
        with self.assertRaises(SpatialError):
            prepare_b1a3_fields(a2, r11, r30, g, g)
        a2["sea_mask"][0, 0] = 2
        with self.assertRaises(SpatialError):
            prepare_b1a3_fields(a2, r11, r30, g, g)
        with self.assertRaises(SpatialError):
            _strict_shape(np.zeros((2, 2)), 3, 3)

    def test_b1a3_wrong_grid_rejected(self):
        g, a2, r11, r30 = fixture()
        for t in (Grid((4, 5), 1, 0, 4, 4), Grid((4, 5), 0, 0, 4, 3)):
            with self.assertRaises(SpatialError):
                prepare_b1a3_fields(a2, r11, r30, g, t)
        with self.assertRaises(SpatialError):
            prepare_b1a3_fields(a2, r11, r30, Grid(g.shape, 0, 0, 4000, 4000, "m"), g)

    def test_c1r7_actual_source_nonzero_crop_origin(self):
        g, _, r11, _ = fixture((56, 56))
        r11["derived_sea_mask"] = np.zeros(g.shape, bool)
        r11["derived_sea_mask"][54, 54] = True
        p = prepare_c1r7_fields(r11, g)
        self.assertEqual(p.grid, Grid((216, 216), 116, 116, .5, .5))
        self.assertEqual(p.fields["old"].sum(), 64)
        assert_array_equal(p.fields["x"][:3], [116.25, 116.75, 117.25])
        assert_array_equal(p.fields["y"][-3:], [222.75, 223.25, 223.75])
        # Affine oracle evaluated at declared centres, with nearest-centre edge support.
        x = np.clip(np.arange(216)*.5+116.25, 118, 222)
        y = x.copy()
        assert_allclose(p.fields["comp"], 2*x[None, :]+3*y[:, None]+7, atol=0)
        assert_array_equal(p.fields["old"][200:208, 200:208], True)
        self.assertIn("BLOCKED", p.receipt["physical_mouths"])

    def test_c1r7_empty_sea_rejected(self):
        g, _, r11, _ = fixture()
        r11["derived_sea_mask"][:] = False
        with self.assertRaisesRegex(SpatialError, "nonempty sea"):
            prepare_c1r7_fields(r11, g)

    def test_political_actual_source_scalar_and_banded_fields(self):
        g = Grid((2, 3), 0, 0, 4, 4)
        a = np.arange(6).reshape(2, 3)
        evidence = {name: a for name in ("access", "barrier", "shore", "elev", "relief", "grass")}
        evidence.update(hs=np.stack([a, a+10]), res=np.stack([a+20, a+30]))
        p = sample_political_evidence(evidence, [3, 4, 7.999, 8], [1]*4, g)
        assert_array_equal(p.fields["ua"], [0, 1, 1, 2])
        assert_array_equal(p.fields["uh"], [[0, 1, 1, 2], [10, 11, 11, 12]])
        assert_array_equal(p.fields["ures"], [[20, 21, 21, 22], [30, 31, 31, 32]])
        self.assertEqual(p.receipt["executed_assignments"], [[75, 76]])
        with self.assertRaises(SpatialError):
            sample_political_evidence(evidence, 12, 0, g)

    def test_native_contact_boundary_is_fail_closed(self):
        for representation in ("cartographic", "native", None):
            with self.assertRaisesRegex(SpatialError, "not implemented"):
                require_native_contacts(representation=representation)

    def test_actual_predecessor_pins_unchanged(self):
        before = verify_sources()
        g, a2, r11, r30 = fixture()
        prepare_b1a3_fields(a2, r11, r30, g, g)
        prepare_c1r7_fields(r11, g)
        self.assertEqual(verify_sources(), before)
        for key, pin in PINS.items():
            self.assertEqual(hashlib.sha256(pin["path"].read_bytes()).hexdigest(), pin["sha256"])

    def test_source_drift_rejected_without_mutating_source(self):
        original = Path.read_bytes
        def changed(path):
            raw = original(path)
            return raw+b"\n" if path == PINS["b1a3"]["path"] else raw
        with patch.object(Path, "read_bytes", changed), self.assertRaises(SourcePinError):
            _source("b1a3")

    def test_wrong_assignment_selection_rejected(self):
        raw, _ = _source("political")
        with self.assertRaises(SourcePinError):
            _assignments(raw, "political", [(75, 76)], ("wrong",))


if __name__ == "__main__":
    unittest.main()
