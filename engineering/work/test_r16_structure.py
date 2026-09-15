"""Two small owner-contract geometry checks; no terrain/region execution."""
from fractions import Fraction as F
import math
import unittest

from work.generator_upgrade_r16.structure import FiniteMap


def fixture():
    return FiniteMap(F(9, 10), (1016000, 808000), 0, 1200, 32000, F(1, 100))


class FiniteMapTests(unittest.TestCase):
    def test_forward_inverse_analytic_jacobian_identity_and_invalid_values(self):
        model = fixture(); point = (F(12345, 7), F(-4321, 3), F(2345, 9))
        self.assertEqual(model.inverse(*model.forward(*point)), point)
        jac = model.jacobian(F(80000, 9), 0)
        a, b, c = jac
        determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
        self.assertEqual(determinant, 1)
        self.assertEqual(c[1], F(1, 100))
        self.assertAlmostEqual(float(c[0]), -.9*1200*math.tau/32000, places=14)
        identity = FiniteMap(1, (0, 0), 0, 0, 1, 0)
        self.assertEqual(identity.forward(*point), point)
        self.assertEqual(identity.inverse(*point), point)
        self.assertEqual(identity.jacobian(point[0], point[1]), ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
        for ratio in (0, -1, float('nan'), float('inf')):
            with self.subTest(ratio=ratio), self.assertRaises(ValueError):
                FiniteMap(ratio, (0, 0), 0, 1, 1, 0)
        for operation in (lambda: model.forward(float('inf'), 0, 0),
                          lambda: model.inverse(0, float('nan'), 0),
                          lambda: model.jacobian(0, float('inf')),
                          lambda: FiniteMap(1, (0, 0), 0, 1, 0, 0)):
            with self.assertRaises(ValueError):
                operation()

    def test_exact_owner_anchors_contact_volume_and_exhaustion(self):
        model = fixture(); contacts = [-5000, -1000, 0, 1000, 1300]; area = F(10000)
        cases = [(0, 1200, F(-39200, 9), F(1000), [F(40000, 9), F(8200, 9), F(), F()], 1),
                 (8000, 0, F(-50000, 9), F(1000), [F(40000, 9), F(10000, 9), F(1000), F()], 2),
                 (16000, -1200, F(-60800, 9), F(2200, 9), [F(40000, 9), F(10000, 9), F(10000, 9), F(1000, 3)], 3)]
        for u, offset, base, top, thicknesses, exposed in cases:
            row = model.column(1016000+u, 808000, contacts, 1000, area)
            self.assertEqual(F(row['displacement_m']), offset)
            self.assertEqual(F(row['final_base_m']), base); self.assertEqual(F(row['final_top_m']), top)
            self.assertEqual(list(map(F, row['retained_thicknesses_m'])), thicknesses)
            self.assertEqual(row['exposed_index'], exposed)
            self.assertEqual(row['trigonometric_evaluation'], 'EXACT_RATIONAL_QUARTER_WAVE')
            self.assertEqual(F(row['reference_preimage_area_m2']), area/F(9, 10))
            self.assertEqual(row['reference_bulk_volumes_m3'], row['current_bulk_volumes_m3'])
            for original, retained, exported in zip(row['current_bulk_volumes_m3'], row['retained_bulk_volumes_m3'], row['exported_bulk_volumes_m3']):
                self.assertEqual(F(original), F(retained)+F(exported))
        row = model.column(1016000, 808000, contacts, -500, area)
        self.assertEqual(list(map(F, row['retained_thicknesses_m'])), [F(34700, 9), F(), F(), F()])
        exact_contact = model.column(1016000, 808000, contacts, F(800, 9), area)
        self.assertEqual(exact_contact['exposed_index'], 0)
        empty = model.column(1016000, 808000, contacts, F(-39200, 9), area)
        self.assertTrue(empty['exhausted']); self.assertIsNone(empty['exposed_index'])
        self.assertEqual(empty['retained_thicknesses_m'], ['0']*4)
        near = model.column(F(1024000)+F(1, 2**80), 808000, contacts, 1000, area)
        self.assertEqual(near['trigonometric_evaluation'], 'BINARY64_TRIG_REPRESENTED_AS_FRACTION')
        for invalid_contacts, cap in ((contacts, -5000), (contacts, float('nan')), ([0, 0, 1], 1)):
            with self.assertRaises(ValueError):
                model.column(1016000, 808000, invalid_contacts, cap, area)


if __name__ == '__main__':
    unittest.main()
