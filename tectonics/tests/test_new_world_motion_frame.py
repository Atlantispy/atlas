"""Frame-neutral prior regression: small algebra and one native initial world."""
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src')]
import new_world_motion as motion
from new_world_arcs import crust_intervals
from new_world_contract import ContractError
from new_world_layout import generate_layout_candidate
from new_world_structure import generate_structure
from test_new_world_structure import plan


class PriorMetricTests(unittest.TestCase):
    def test_precision_matches_eliminated_common_residual(self):
        w = np.array([.12, .33, .55])
        e = np.array([[2., 3., -1.], [-3., .4, 2.], [5., -2., 4.]])
        K = motion._prior_precision(w)
        centred = e - np.average(e, axis=0, weights=w)
        self.assertAlmostEqual(float(e.ravel() @ K @ e.ravel()),
                               float(np.sum(w[:, None]*centred**2)), places=13)
        shift = np.array([7., -3., 2.])
        np.testing.assert_allclose(K @ np.tile(shift, 3), 0., atol=1e-15)
        self.assertEqual(np.count_nonzero(np.linalg.eigvalsh(K) > 1e-12), 6)

    def test_common_residual_elimination_matches_full_augmented_solve(self):
        w = np.array([.2, .3, .5])
        prior = np.array([[1., -2., 0.], [3., 1., -1.], [-2., .5, 4.]])
        # Independent explicit least squares with three common-residual unknowns.
        # Anchor plate 0; a fixed relative-speed penalty joins plates 1 and 2.
        E = np.eye(9)[:, 3:]
        common = np.tile(np.eye(3), (3, 1))
        D = np.hstack((np.zeros((3, 3)), -np.eye(3), np.eye(3)))
        W = np.diag(np.sqrt(np.repeat(w, 3)))
        A = np.vstack((np.hstack((W @ E, -W @ common)),
                       np.hstack((D @ E, np.zeros((3, 3))))))
        b = np.r_[W @ prior.ravel(), np.zeros(3)]
        explicit = np.linalg.lstsq(A, b, rcond=None)[0][:6]
        K = motion._prior_precision(w)
        reduced = np.linalg.solve(E.T @ (K+D.T@D) @ E, E.T @ K @ prior.ravel())
        np.testing.assert_allclose(reduced, explicit, rtol=2e-13, atol=2e-13)


class InitialMotionFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = plan(seed=41)
        cls.candidate = generate_layout_candidate(cls.plan)
        cls.atlas = cls.candidate.atlas
        cls.structure = generate_structure(cls.plan)
        cls.intervals = crust_intervals(cls.atlas, cls.structure)
        cls.types = {c.column_id: c.crust_type for c in cls.structure.state.case.columns}

    def solve(self, **kwargs):
        from atlas_tectonics.stokes_execution import _native_lease
        with _native_lease():
            return motion._reconcile(self.atlas, self.intervals, self.types,
                                     self.plan['streams']['plate_motion'], **kwargs)

    def test_all_generation_anchors_preserve_relative_motion(self):
        ref = self.solve()
        for anchor in self.atlas.plate_ids:
            with self.subTest(anchor=anchor):
                result = self.solve(anchor=anchor)
                np.testing.assert_allclose(result[2]-result[2][0], ref[2]-ref[2][0],
                                           rtol=2e-11, atol=2e-27)
                np.testing.assert_array_equal(result[2][result[0].index(anchor)], np.zeros(3))
                self.assertAlmostEqual(result[5]['relative_prior_adjustment'],
                                       ref[5]['relative_prior_adjustment'], places=12)
                self.assertAlmostEqual(result[5]['achieved_boundary_rms_cm_year'],
                                       ref[5]['target_boundary_rms_cm_year'], places=12)

    def test_no_continental_affinity_also_preserves_anchor_invariance(self):
        a = self.solve(affinity=0., anchor=self.atlas.plate_ids[0])
        b = self.solve(affinity=0., anchor=self.atlas.plate_ids[-1])
        np.testing.assert_allclose(a[2]-a[2][0], b[2]-b[2][0], rtol=2e-11, atol=2e-27)

    def test_invalid_anchor_refuses(self):
        with self.assertRaises(ContractError):
            self.solve(anchor='not-a-plate')


if __name__ == '__main__':
    unittest.main()
