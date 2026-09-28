"""Manufactured kinematics only; no physical reorganisation acceptance."""
import dataclasses
from fractions import Fraction
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
from check_i01_ridge_junction import PreparedCandidate, fixture
from check_i01_junction_events import PreparedContact, MODEL


class RidgeContinuationTests(unittest.TestCase):
    def test_independent_solution_and_contact_connection(self):
        # In the laboratory frame outgoing endpoints are (-1/2,0),(1/2,0).
        p = PreparedCandidate(**fixture())
        self.assertEqual(p.status, "LOCALLY_FEASIBLE_NOT_GENERATED")
        self.assertEqual(p.junction_a_relative, (Fraction(3, 2), 0))
        self.assertEqual(p.junction_b_relative, (Fraction(5, 2), 0))
        incoming = PreparedContact((0, 2), (0, -2), (0, -0.5), (0, 0.5),
            validity_s=8, parent_id="incoming", edge_id="AB", model=MODEL)
        self.assertEqual(incoming.query(0, 8).offset_s, 4)
        self.assertEqual(p.separation_squared(Fraction(1, 3)), Fraction(1, 9))
        self.assertFalse(p.record()["topology_change_authorised"])

    def test_each_new_endpoint_must_match_ridge(self):
        p = PreparedCandidate(**fixture(normals=[(1, 1), (1, -1), (-1, 1), (-1, -1), (1, -1)]))
        self.assertEqual(p.status, "INCOMPATIBLE_NEW_RIDGE_MOTION")
        self.assertEqual(p.normal_residuals, (Fraction(-1, 2), Fraction(1, 2)))
        with self.assertRaises(ValueError):
            p.separation_squared(1)

    def test_stationary_and_reversed_growth(self):
        for v, status in [([(-1, 0), (1, 0), (0, 1), (0, -1)], "NO_FIRST_ORDER_GROWTH"),
                          ([(-1, 0), (1, 0), (0, 2), (0, -2)], "REVERSED_ORIENTED_GROWTH")]:
            p = PreparedCandidate(**fixture(velocities=v))
            self.assertEqual(p.status, status)
            with self.assertRaises(ValueError):
                p.separation_squared(1)

    def test_common_frame_and_rotation(self):
        base = PreparedCandidate(**fixture())
        p = PreparedCandidate(**fixture(velocities=[(x+32, y-9) for x, y in fixture()["velocities"]]))
        self.assertEqual(p.junction_a_relative, base.junction_a_relative)
        self.assertEqual(p.relative_growth, base.relative_growth)
        p = PreparedCandidate(**fixture(velocities=[(-y, x) for x, y in fixture()["velocities"]],
                                        normals=[(-y, x) for x, y in fixture()["normals"]]))
        self.assertEqual(p.relative_growth, (0, 1))
        self.assertEqual(p.status, base.status)

    def test_normal_scale_and_velocity_scale(self):
        p = PreparedCandidate(**fixture(normals=[tuple(5*q for q in n) for n in fixture()["normals"]]))
        self.assertEqual(p.relative_growth, (1, 0))
        p = PreparedCandidate(**fixture(velocities=[tuple(Fraction(1, 7)*q for q in v) for v in fixture()["velocities"]]))
        self.assertEqual(p.separation_squared(7), 1)

    def test_exact_tiny_mismatch_not_hidden(self):
        p = PreparedCandidate(**fixture(normals=[(1, 1), (1, -1), (-1, 1), (-1, -1), (5e-324, -1)]))
        self.assertEqual(p.status, "INCOMPATIBLE_NEW_RIDGE_MOTION")

    def test_rank_deficiency_not_a_branch(self):
        with self.assertRaisesRegex(ValueError, "underdetermined"):
            PreparedCandidate(**fixture(normals=[(1, 0), (1, 0), (-1, 1), (-1, -1), (0, -1)]))

    def test_bad_domain(self):
        changes = [{"model": "trench"}, {"plate_ids": ["A", "A", "C", "D"]},
                   {"validity_s": 0}, {"validity_s": True}, {"parent_id": ""},
                   {"velocities": [(0, 0)]*4}, {"normals": [(0, 0)]*5},
                   {"velocities": [(float("nan"), 0)]*4},
                   {"velocities": [(1 << 20000, 0)]*4}]
        for change in changes:
            with self.subTest(change=list(change)), self.assertRaises(ValueError):
                PreparedCandidate(**fixture(**change))
        p = PreparedCandidate(**fixture())
        for t in [0, -1, 9, True, float("inf")]:
            with self.assertRaises(ValueError):
                p.separation_squared(t)

    def test_copied_immutable_and_no_permission(self):
        kw = fixture()
        p = PreparedCandidate(**kw)
        kw["velocities"][0] = (999, 999)
        kw["plate_ids"][0] = "different"
        self.assertEqual(p.plate_ids, ("A", "B", "C", "D"))
        self.assertEqual(p.separation_squared(2), 4)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.status = "accepted"
        self.assertFalse(p.record()["physical_birth_verified"])
        self.assertFalse(p.record()["global_geometry_verified"])


if __name__ == "__main__":
    unittest.main()
