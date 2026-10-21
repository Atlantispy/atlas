"""Focused actual-method tests; real GMP, isolated from Atlas dispatch/owners."""
import ast
import hashlib
import itertools
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import gmpy2

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'helpers/private_heat_issuer_resources_r3.py'
ORIGINAL = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/ac/p1012-r1/helpers/private_heat_issuer_resources_r3.py')
CAPTURE = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/ac/p14-w4-q51-r1')
PINS = ('be5116323e7532e6cfa0cafb4049868206d59e02828f288423243130abd180dd',
        '3005cde8ead2df1b60c50a42f8b0a197f7b6ac1f63b504b702f1b634524c97b6')


def actual_method(source=None):
    tree = ast.parse(SOURCE.read_bytes() if source is None else source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == '_ProjectionArithmetic')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'equal')
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_equality_rank']
    selected.append(method)
    namespace = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['equal']


class Fixture:
    def __init__(self):
        self.G = gmpy2
        self.peak_bits = 1
        self.operations = 0
        self.reservations = []

    def reserve(self, bits):
        self.reservations.append(bits)
        self.peak_bits = max(self.peak_bits, bits)

    def shape(self, value):
        return SimpleNamespace(numerator_bits=int(value.numerator).bit_length(),
                               denominator_bits=int(value.denominator).bit_length())


def witness(left, right):
    parts = tuple(int(part).bit_length() for value in (left, right)
                  for part in (value.numerator, value.denominator))
    return dict(part_bits=parts, required_part_bits=max(parts),
        unused_cross_product_bits=max(parts[0] + parts[3], parts[2] + parts[1]))


def run(values, method=None):
    ar = Fixture()
    equal = actual_method() if method is None else method
    for left, right in values:
        if not equal(ar, left, right):
            raise AssertionError('Actual canonical equality refused fixture operands')
    return ar


def capture(index):
    raw = (CAPTURE / ('arm-' + str(index)) / 'legacy_metadata.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != PINS[index]:
        raise AssertionError('Retained failed capture changed')
    metadata = json.loads(raw)
    def q(pair):
        return gmpy2.mpq(gmpy2.mpz(pair[0], 16), gmpy2.mpz(pair[1], 16))
    retained, projection, public = (metadata[name] for name in (
        'exact_retained_solver_residual_j', 'exact_stock_projection_residual_j',
        'exact_cell_storage_residual_j'))
    return [(q(a) + q(b), q(c)) for a, b, c in zip(retained, projection, public, strict=True)]


class WitnessTests(unittest.TestCase):
    def test_peak_is_an_actual_witness_and_independent_of_visit_order(self):
        values = [gmpy2.mpq(3, 5), gmpy2.mpq(2**180 + 3, 2**211 + 1),
                  gmpy2.mpq(2**77 + 1, 2**219 + 3)]
        expected = witness(values[2], values[2])
        for order in itertools.permutations(values):
            ar = run([(value, value) for value in order])
            self.assertEqual(ar.equality_evidence, expected)
            self.assertEqual(ar.operations, 3)
            self.assertGreaterEqual(ar.peak_bits, expected['required_part_bits'])

    def test_actual_failed_capture_orders_choose_the_same_real_peak(self):
        left, right = capture(0), capture(1)
        self.assertEqual(len(left), 236)
        self.assertEqual(len(right), 236)
        # Same physical operand multiset, independently of its stored order.
        self.assertEqual(sorted((str(a), str(b)) for a, b in left),
                         sorted((str(a), str(b)) for a, b in right))
        self.assertNotEqual(witness(*left[-1]), witness(*right[-1]))
        actual_left, actual_right = run(left), run(right)
        self.assertEqual(actual_left.equality_evidence, actual_right.equality_evidence)
        observed = [witness(a, b) for a, b in left]
        self.assertIn(actual_left.equality_evidence, observed)
        self.assertEqual(actual_left.equality_evidence['required_part_bits'],
                         max(item['required_part_bits'] for item in observed))

    def test_unequal_values_are_still_false(self):
        ar = Fixture()
        self.assertFalse(actual_method()(ar, gmpy2.mpq(1, 3), gmpy2.mpq(2, 3)))
        self.assertEqual(ar.operations, 1)
        self.assertTrue(ar.reservations)

    def test_foreign_numeric_types_still_refuse_before_work(self):
        ar = Fixture()
        with self.assertRaises(TypeError):
            actual_method()(ar, 0.5, gmpy2.mpq(1, 2))
        self.assertEqual(ar.operations, 0)
        self.assertEqual(ar.reservations, [])

    def test_numerical_reserve_getter_and_equality_tail_is_unchanged(self):
        raw = ORIGINAL.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
            '6517cc80b676a7a66a0ab573899d2e6e6beadf20af5fd7f9b6987962f35621cd')
        def equal(source):
            tree = ast.parse(source)
            cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == '_ProjectionArithmetic')
            return next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'equal')
        old, new = equal(raw), equal(SOURCE.read_bytes())
        self.assertEqual([ast.dump(node, include_attributes=False) for node in old.body[:3]],
                         [ast.dump(node, include_attributes=False) for node in new.body[:3]])
        self.assertEqual([ast.dump(node, include_attributes=False) for node in old.body[-5:]],
                         [ast.dump(node, include_attributes=False) for node in new.body[-5:]])

    def test_known_last_witness_mutant_is_detected_on_actual_capture(self):
        text = SOURCE.read_text(encoding='utf8')
        target = "if previous is None or _equality_rank(evidence) > _equality_rank(previous):"
        self.assertEqual(text.count(target), 1)
        mutant = actual_method(text.replace(target, 'if True:'))
        self.assertNotEqual(run(capture(0), mutant).equality_evidence,
                            run(capture(1), mutant).equality_evidence)

    def test_known_minimum_witness_mutant_fails_peak_requirement(self):
        text = SOURCE.read_text(encoding='utf8')
        target = '_equality_rank(evidence) > _equality_rank(previous)'
        self.assertEqual(text.count(target), 1)
        mutant = actual_method(text.replace(target, '_equality_rank(evidence) < _equality_rank(previous)'))
        observed = capture(0)
        self.assertLess(run(observed, mutant).equality_evidence['required_part_bits'],
                        max(witness(a, b)['required_part_bits'] for a, b in observed))


if __name__ == '__main__':
    unittest.main(verbosity=2)
