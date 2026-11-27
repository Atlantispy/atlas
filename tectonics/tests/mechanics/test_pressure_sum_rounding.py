"""The add-site roundings of the pressure jets skip a pair already on the dyadic grid; the result must be the
same two fractions as the full rounding, endpoint by endpoint, type included."""
from fractions import Fraction as Q
import unittest

from atlas_tectonics.integration.coupling import pressure_coupling as PC
from atlas_tectonics.mechanics import pressure_midpoint_values as PM

BITS = (8, 16, 96, 128)


class _Owner:
    """Stands in for the midpoint scratch owner: a Value is just its pair."""

    def make(self, cls, pair, constant, expression=None):
        return pair


def corpus(bits):
    d = 1 << bits
    return (
        (Q(-5, d), Q(3, 1 << (bits // 2))),          # on the grid
        (Q(1, 12), Q(1, d - 1)),                     # off the grid, shorter denominators
        (Q(1, d + 1), Q(1, 1 << (bits + 3))),        # off the grid, longer denominators
        (Q(7, d), Q(9, d)),                          # d == 2**bits
        (Q(1, 2 * d), Q(3, 2 * d)),                  # d == 2**(bits+1)
        (Q(1, 3), Q(2, 3)),                          # d == 3
        (Q(-7, 3), Q(-1, 2 * d)),                    # negatives
        (Q(0), Q(0)),                                # zero
        (0, 5), (-3, 2),                             # int endpoints
        (Q(1, 2), Q(1, 2 * d)),                      # only the lower endpoint on the grid
        (Q(1, 2), Q(1, 3)),                          # only the lower endpoint on the grid, d == 3 above
        (Q(4), Q(9)),                                # Q with denominator 1
    )


def exact(pairs):
    return tuple((type(q), q.numerator, q.denominator) for pair in pairs for q in pair)


class SumRoundingTest(unittest.TestCase):
    def test_coupling_sum_equals_full_rounding(self):
        for bits in BITS:
            token = PC._JET_PRECISION.set(bits)
            try:
                jet = corpus(bits)
                for pair in jet:
                    with self.subTest(bits=bits, pair=pair):
                        self.assertEqual(exact(PC._jet_outward_sum((pair,))), exact(PC._jet_outward((pair,))))
                self.assertEqual(exact(PC._jet_outward_sum(jet)), exact(PC._jet_outward(jet)))
            finally:
                PC._JET_PRECISION.reset(token)

    def test_midpoint_sum_equals_full_rounding(self):
        owner = PM._OWNER.set(_Owner())
        try:
            for bits in BITS:
                token = PM._JET_PRECISION.set(bits)
                try:
                    for pair in corpus(bits):
                        with self.subTest(bits=bits, pair=pair):
                            self.assertEqual(exact((PM._rounded_sum(pair),)), exact((PM._rounded(pair),)))
                finally:
                    PM._JET_PRECISION.reset(token)
        finally:
            PM._OWNER.reset(owner)


if __name__ == '__main__':
    unittest.main()
