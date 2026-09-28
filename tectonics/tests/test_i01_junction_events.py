"""Independent affine contact/guard controls; no generated reorganisation."""
import dataclasses
from fractions import Fraction
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
from check_i01_junction_events import PreparedContact, fixture, MODEL


class JunctionContacts(unittest.TestCase):
    def path(self, **kw):
        return PreparedContact(**fixture(**kw))

    def test_double_root_without_sign_change(self):
        p = self.path()
        for lo, hi in ((0, 8), (0, 4), (3, 5)):
            self.assertEqual(p.query(lo, hi).offset_s, Fraction(4))
        self.assertEqual((12-3*0)**2, (12-3*8)**2)
        self.assertIsNone(p.query(0, 3).offset_s)
        self.assertIsNone(p.query(5, 8).offset_s)

    def test_both_components_must_meet(self):
        p = self.path(x_right=(12, 8), v_left=(1, 2), v_right=(-2, 0))
        self.assertEqual(p.query(0, 8).offset_s, 4)
        for tiny in (1e-6, 5e-324):
            self.assertIsNone(self.path(x_right=(12, tiny)).query(0, 8).offset_s)
        self.assertIsNone(self.path(x_right=(12, 9), v_left=(1, 2)).query(0, 8).offset_s)

    def test_nonbinary_time_has_exact_ratio(self):
        p = self.path(x_right=(1, 0))
        self.assertEqual(p.query(0, 1).offset_s, Fraction(1, 3))
        self.assertEqual(p.query(0, 1).record()["offset_s_exact"], {"numerator": "1", "denominator": "3"})
        self.assertEqual(p.query(Fraction(1, 3), 1).status, "CONTACT_AT_WINDOW_START")
        self.assertEqual(p.query(0, Fraction(1, 3)).offset_s, Fraction(1, 3))

    def test_exact_event_order_not_rounded(self):
        a = self.path(x_right=(1, 0)).query(0, 1).offset_s
        b = self.path(x_right=(1.0000000000000002, 0)).query(0, 1).offset_s
        self.assertLess(a, b)

    def test_transformations_and_swapped_endpoints(self):
        a = self.path().query(0, 8)
        self.assertEqual(a, self.path(x_left=(100, 200), x_right=(112, 200), v_left=(21, -7), v_right=(18, -7)).query(0, 8))
        self.assertEqual(a, self.path(x_left=(12, 0), x_right=(0, 0), v_left=(-2, 0), v_right=(1, 0)).query(0, 8))
        self.assertEqual(a, self.path(x_right=(0, 12), v_left=(0, 1), v_right=(0, -2)).query(0, 8))

    def test_stationary_and_initial_contacts(self):
        self.assertEqual(self.path(v_right=(1, 0)).query(0, 8).status, "NO_CONTACT_ON_DECLARED_PATH")
        self.assertEqual(self.path(x_right=(0, 0)).query(0, 8).status, "CONTACT_AT_WINDOW_START")
        self.assertEqual(self.path(x_right=(0, 0), v_right=(1, 0)).query(0, 8).status, "COINCIDENT_INTERVAL_NOT_ISOLATED_EVENT")
        self.assertEqual(self.path(v_right=(2, 0)).query(0, 8).status, "NO_CONTACT_ON_DECLARED_PATH")

    def test_validity_and_model_guards(self):
        p = self.path()
        for window in ((-1, 1), (0, 9), (2, 2), (4, 3), (0, float('inf')), (False, 1)):
            with self.assertRaises(ValueError):
                p.query(*window)
        for kw in ({"model": "spherical"}, {"model": "accelerating"}, {"validity_s": 0}, {"parent_id": ""}, {"edge_id": "\n"}):
            with self.assertRaises(ValueError):
                self.path(**kw)

    def test_invalid_numbers_and_shapes(self):
        for x in ((float('nan'), 0), (float('inf'), 0), (True, 0), ('1', 0), (1<<1025, 0), (Fraction(1, 1<<16385), 0), (0,), (0, 0, 0)):
            with self.assertRaises(ValueError):
                self.path(x_left=x)

    def test_no_float_overflow_or_underflow_classification(self):
        p = self.path(x_left=(-1e308, 0), x_right=(1e308, 0), v_left=(1e308, 0), v_right=(-1e308, 0))
        self.assertEqual(p.query(0, 8).offset_s, 1)
        tiny = 5e-324
        p = self.path(x_left=(0, 0), x_right=(tiny, tiny), v_left=(tiny, tiny), v_right=(0, 0))
        self.assertEqual(p.query(0, 8).offset_s, 1)

    def test_immutable_copy_and_parent_identity(self):
        x = [12, 0]
        p = self.path(x_right=x)
        x[0] = 20
        self.assertEqual(p.query(0, 8).offset_s, 4)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.root_s = Fraction(1)
        rec = p.query(0, 8).record()
        self.assertEqual(rec['parent_id'], 'manufactured-parent')
        self.assertEqual(rec['trajectory_model'], MODEL)
        self.assertFalse(rec['topology_change_authorised'])


if __name__ == '__main__':
    unittest.main()
