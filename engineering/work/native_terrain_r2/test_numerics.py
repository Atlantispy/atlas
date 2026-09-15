"""Focused exact allocation checks; no native terrain or model execution."""
from copy import deepcopy
from fractions import Fraction as F
import itertools
import unittest

from work.native_terrain_r2 import numerics as n


class QuantumTests(unittest.TestCase):
    def test_exact_units_mass_and_outward_errors(self):
        for value in (0, 1, 2**64, 2**256 - 1):
            self.assertEqual(n.units(n.mass(value)), value)
        self.assertEqual(n.ceil_error_units(F()), 0)
        self.assertEqual(n.ceil_error_units(n.Q / 7), 1)
        self.assertEqual(n.ceil_error_units(n.Q), 1)
        self.assertEqual(n.ceil_error_units(7 * n.Q / 3), 3)

    def test_quantum_limits_fail_closed(self):
        for invalid in (True, False, -1, 1.0, '1', F(1, 3), n.Q / 2, n.mass(2**256 - 1) + n.Q):
            with self.subTest(invalid=type(invalid).__name__), self.assertRaises(ValueError):
                n.units(invalid)
        for invalid in (True, -1, F(1), 2**256):
            with self.assertRaises(ValueError):
                n.mass(invalid)
        for invalid in (-n.Q, True, 1.0, F(1, 2**8192)):
            with self.assertRaises(ValueError):
                n.ceil_error_units(invalid)


class PositiveAllocationTests(unittest.TestCase):
    def check(self, total, desired):
        actual, bound = n.allocate_positive(total, desired)
        self.assertEqual(sum(actual.values()), total)
        self.assertEqual(set(actual), set(desired))
        self.assertTrue(all(value >= 1 for value in actual.values()))
        exact_error = sum((abs(n.mass(actual[key]) - value) for key, value in desired.items()), F())
        self.assertLessEqual(exact_error, n.mass(bound))
        self.assertEqual((actual, bound), n.allocate_positive(total, dict(reversed(list(desired.items())))))
        return actual, bound

    def test_migration_tiny_positive_identity_survives(self):
        tiny = F(1, 10**435)
        actual, bound = self.check(10, {'tiny': tiny, 'bulk': n.mass(10) - tiny})
        self.assertEqual(actual, {'bulk': 9, 'tiny': 1})
        self.assertEqual(bound, 2)
        self.assertEqual(float(tiny), 0.)  # Binary64 positivity would lose it.

    def test_positive_lower_bounds_and_remainder_ties(self):
        desired = {'a': n.mass(7) / 2, 'b': n.mass(7) / 2, 'c': n.mass(1) / 2, 'd': n.mass(1) / 2}
        actual, _ = self.check(8, desired)
        self.assertEqual(actual, {'a': 3, 'b': 3, 'c': 1, 'd': 1})
        actual, _ = self.check(7, {'a': n.mass(7) / 3, 'b': n.mass(7) / 3, 'c': n.mass(7) / 3})
        self.assertEqual(actual, {'a': 3, 'b': 2, 'c': 2})
        # Many required tiny slots force several removals from one large slot.
        small = n.Q / 100
        desired = {f'tiny-{i:02}': small for i in range(9)}
        desired['bulk'] = n.mass(10) - 9 * small
        self.assertEqual(self.check(10, desired)[0]['bulk'], 1)

    def test_empty_exact_and_exhausted_limits(self):
        self.assertEqual(n.allocate_positive(0, {}), ({}, 0))
        self.assertEqual(self.check(5, {'one': n.mass(5)}), ({'one': 5}, 0))
        with self.assertRaisesRegex(ValueError, 'fund'):
            n.allocate_positive(1, {'a': n.Q / 2, 'b': n.Q / 2})

    def test_invalid_inputs_do_not_mutate_slots(self):
        desired = {'a': n.Q, 'b': 2 * n.Q}
        before = deepcopy(desired)
        with self.assertRaisesRegex(ValueError, 'total'):
            n.allocate_positive(4, desired)
        self.assertEqual(desired, before)
        for bad in ({'a': F()}, {'a': -n.Q}, {'a': float(n.Q)}, {True: n.Q}, {'': n.Q}):
            with self.assertRaises(ValueError):
                n.allocate_positive(1, bad)
        with self.assertRaises(ValueError):
            n.allocate_positive(16386, {str(i): n.Q for i in range(16386)})


class TransportationTests(unittest.TestCase):
    def check(self, rows, cols):
        original = deepcopy((rows, cols))
        matrix, bound = n.transportation_matrix(rows, cols)
        self.assertEqual((rows, cols), original)
        total = sum(rows.values())
        for row in rows:
            self.assertEqual(sum(matrix[row].values()), rows[row])
        for col in cols:
            self.assertEqual(sum(matrix[row][col] for row in rows), cols[col])
        error = F()
        for row, col in itertools.product(rows, cols):
            ideal = F(rows[row] * cols[col], total) if total else F()
            self.assertIn(matrix[row][col], {ideal.numerator // ideal.denominator,
                          -(-ideal.numerator // ideal.denominator)})
            self.assertLess(abs(matrix[row][col] - ideal), 1)
            if rows[row] == 0 or cols[col] == 0:
                self.assertEqual(matrix[row][col], 0)
            error += abs(matrix[row][col] - ideal)
        self.assertGreaterEqual(bound, error)
        self.assertEqual(bound, -(-error.numerator // error.denominator))
        self.assertEqual((matrix, bound), n.transportation_matrix(
            dict(reversed(list(rows.items()))), dict(reversed(list(cols.items())))))
        return matrix, bound

    def test_both_margins_floor_ceiling_and_permutation(self):
        self.check({'a': 8, 'b': 5, 'c': 3}, {'kept': 7, 'left': 6, 'export': 3})
        self.check({'a': 1, 'b': 1, 'c': 1}, {'x': 1, 'y': 1, 'z': 1})
        self.check({'a': 0, 'b': 11}, {'zero': 0, 'kept': 8, 'out': 3})

    def test_small_margin_matrix_family(self):
        # Exact mathematical margin family; no random seed or model fixture.
        for rows in itertools.product(range(4), repeat=3):
            total = sum(rows)
            for first in range(total + 1):
                self.check(dict(zip(('a', 'b', 'c'), rows)), {'x': first, 'y': total-first})

    def test_zero_and_full_exhaustion(self):
        self.assertEqual(n.transportation_matrix({}, {}), ({}, 0))
        self.assertEqual(self.check({'a': 0}, {'out': 0}), ({'a': {'out': 0}}, 0))
        result, _ = self.check({'a': 3, 'b': 7}, {'kept': 0, 'export': 10})
        self.assertEqual(result, {'a': {'export': 3, 'kept': 0}, 'b': {'export': 7, 'kept': 0}})

    def test_repeated_retained_export_splits_keep_bounded_exact_origins(self):
        initial = {'a': 2**190 + 17, 'b': 2**189 + 31, 'c': 2**188 + 7}
        retained, exported = dict(initial), {key: 0 for key in initial}
        accumulated_error = 0
        for _ in range(200):
            total = sum(retained.values())
            outgoing = total // 17
            matrix, bound = n.transportation_matrix(retained, {'kept': total-outgoing, 'export': outgoing})
            for origin in initial:
                retained[origin] = matrix[origin]['kept']
                exported[origin] += matrix[origin]['export']
                self.assertEqual(retained[origin] + exported[origin], initial[origin])
                self.assertLessEqual(max(retained[origin].bit_length(), exported[origin].bit_length()), n.MAX_UNIT_BITS)
                self.assertLessEqual(n.mass(retained[origin]).denominator.bit_length(), 65)
            accumulated_error += bound
        self.assertIs(type(accumulated_error), int)
        self.assertGreater(accumulated_error, 0)

    def test_malformed_margins_reject_without_mutation(self):
        rows, cols = {'a': 2}, {'x': 3}
        before = deepcopy((rows, cols))
        with self.assertRaisesRegex(ValueError, 'totals'):
            n.transportation_matrix(rows, cols)
        self.assertEqual((rows, cols), before)
        for bad in ({'a': True}, {'a': -1}, {'a': F(1)}, {'a': 2**256}, {'': 1}):
            with self.assertRaises(ValueError):
                n.transportation_matrix(bad, {'x': 1})
        with self.assertRaises(ValueError):
            n.transportation_matrix({'a': 2**255, 'b': 2**255}, {'x': 0})
        with self.assertRaises(ValueError):
            n.transportation_matrix({str(i): 0 for i in range(1025)}, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
