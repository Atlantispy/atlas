"""K5 diagnostic ranges and exact-fallback reuse. WORKING NON-CANON.

History parameters are declared in i03_controls_v4.json/sweep_repair. The synthetic
polygon coordinates reuse test_i03_transfer's exact-clipping fixtures. These check
identity with the retained exact algorithm, not independent physical acceptance.
SPDX-License-Identifier: AGPL-3.0-only
"""
import json
import math
import unittest
from unittest import mock

import numpy as np

import i03_fixtures as F
from atlas_tectonics import integration_sphere as S, integration_transfer as T
from atlas_tectonics.resources import MemoryLimitError, WorkBudget

CONTROL = json.loads((F.CASES/'i03_controls_v4.json').read_text(encoding='utf-8'))['controls']['sweep_repair']


def ring(points):
    result = np.asarray([(x, y, 1.) for x, y in points], dtype=float)
    return result/np.linalg.norm(result, axis=1)[:, None]


def polygon_pairs():
    """Existing exact clipping's convex/concave/hole cases and exact collinear corners."""
    outer = ring(((-.4, -.4), (.4, -.4), (.4, .4), (-.4, .4)))
    hole = ring(((-.1, -.1), (.1, -.1), (.1, .1), (-.1, .1)))
    right = ring(((0., -.5), (.5, -.5), (.5, .5), (0., .5)))
    concave = ring(((-.4, -.4), (.4, -.4), (.4, 0.), (0., 0.), (0., .4), (-.4, .4)))
    subdivided = ring(((-.4, -.4), (0., -.4), (.4, -.4), (.4, 0.), (.4, .4), (0., .4), (-.4, .4), (-.4, 0.)))
    return ([outer], [outer, right]), ([outer, hole], [outer, right]), ([concave], [outer, right]), ([subdivided], [outer, right])


class SweepRepairTests(unittest.TestCase):
    def test_public_diagnostic_applies_all_three_approved_ranges(self):
        original = T._consumption_accuracy
        seen_ranges = set()
        for turn in CONTROL['turn_deg']:
            captured = []

            def capture(network, material, moved, rows, supplies):
                captured.extend(moved.swept)
                return original(network, material, moved, rows, supplies)

            state = F.crust(F.three_plates())
            with mock.patch.object(T, '_consumption_accuracy', capture):
                step = T.advance(state, F.one_plate_motion(turn), end_time_s=F.MYR_S)
            by_boundary = {}
            for boundary, _, points in captured:
                area = T._exact_ring_sr(points)
                perimeter = math.fsum(float(T._angle(a, b))
                                      for a, b in zip(points, np.roll(points, -1, axis=0)))
                ratio = area/perimeter
                raw = S._measure_bound([points])
                self.assertIsNotNone(raw)
                if ratio < T.THIN_FACE_RATIO:
                    value, band = raw, 'thin'
                elif ratio < 2*T.THIN_FACE_RATIO:
                    value, band = min(raw, 2*T.RELATIVE_TOLERANCE*area), 'transition'
                else:
                    value, band = 0., 'ordinary'
                seen_ranges.add(band)
                by_boundary.setdefault(boundary, []).append(value)
            diagnostic = step.summary()['consumption_accuracy']
            for boundary, values in by_boundary.items():
                expected = math.fsum(values)*state.network.sphere.radius_m**2
                self.assertEqual(diagnostic[boundary]['sweep_c7_m2'], expected, (turn, boundary))
            self.assertTrue(step.state.material.closure()['identity_exact'])
        self.assertEqual(seen_ranges, {'thin', 'transition', 'ordinary'})

    def test_retained_decomposition_is_bit_identical_for_rings_holes_and_frames(self):
        sphere = F.three_plates().sphere
        for index, (first, sweeps) in enumerate(polygon_pairs()):
            for tilted in (False, True):
                for reverse in (False, True):
                    with self.subTest(polygon=index, tilted=tilted, reverse=reverse):
                        donor = [r[::-1].copy() if reverse else r for r in first]
                        cutters = list(sweeps)
                        if tilted:
                            donor = [F.TILT.apply(r) for r in donor]
                            cutters = [F.TILT.apply(r) for r in cutters]
                        reference = math.fsum(T._exact_overlap_sr(donor, [r], sphere) for r in cutters)
                        self.assertEqual(T._exact_sweep_sr(donor, cutters, sphere).hex(), reference.hex())

    def test_reuse_preserves_peak_budget_and_releases_success_and_refusal(self):
        sphere = F.three_plates().sphere
        first, sweeps = polygon_pairs()[1]
        # The baseline pair formula, independently retained here to catch admission changes.
        def workspace(second):
            points = [point for rings in (first, [second]) for r in rings for point in r]
            exponent = max(float(x).as_integer_ratio()[1].bit_length() for point in points for x in point)
            return 65536+len(points)*(4096+128*exponent)

        maximum = max(workspace(r) for r in sweeps)
        old, new = WorkBudget(maximum), WorkBudget(maximum)
        reference = math.fsum(T._exact_overlap_sr(first, [r], sphere, budget=old) for r in sweeps)
        self.assertEqual(T._exact_sweep_sr(first, sweeps, sphere, budget=new), reference)
        self.assertEqual(new.peak_reserved_bytes, old.peak_reserved_bytes)
        self.assertEqual(new.reserved_bytes, 0)
        refused = WorkBudget(maximum-1)
        with mock.patch.object(T, '_exact_triangles', wraps=T._exact_triangles) as triangles:
            with self.assertRaises(MemoryLimitError):
                T._exact_sweep_sr(first, sweeps, sphere, budget=refused)
            triangles.assert_not_called()
        self.assertEqual(refused.reserved_bytes, 0)
        interrupted = WorkBudget(maximum)
        with mock.patch.object(T, '_exact_overlap_unreserved', side_effect=RuntimeError('test interruption')):
            with self.assertRaisesRegex(RuntimeError, 'test interruption'):
                T._exact_sweep_sr(first, sweeps, sphere, budget=interrupted)
        self.assertEqual(interrupted.reserved_bytes, 0)

    def test_disjoint_caps_skip_but_touching_polygons_keep_exact_check(self):
        sphere = F.three_plates().sphere
        first, _ = polygon_pairs()[0]
        opposite = -first[0]
        with mock.patch.object(T, '_exact_overlap_unreserved', wraps=T._exact_overlap_unreserved) as exact:
            self.assertEqual(T._exact_sweep_sr(first, [opposite], sphere), 0.)
            exact.assert_not_called()
        with mock.patch.object(T, '_exact_overlap_unreserved', wraps=T._exact_overlap_unreserved) as exact:
            expected = T._exact_ring_sr(first[0])
            self.assertEqual(T._exact_sweep_sr(first, [first[0]], sphere), expected)
            self.assertEqual(exact.call_count, 1)


if __name__ == '__main__':
    unittest.main()
