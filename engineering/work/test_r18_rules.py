"""Two focused synthetic exact-rule checks; no owner data or model execution."""
from fractions import Fraction as F
import unittest

from work.generator_upgrade_r18 import rules


def constant(value):
    return {'operation': 'constant', 'value': value}


def product(coefficient, field):
    return {'operation': 'product', 'coefficient_m': coefficient, 'field': field}


class RuleTests(unittest.TestCase):
    def test_r17_constant_product_maximum_exact_formula_parity(self):
        samples = {'carbonate_a': .375, 'carbonate_b': .8, 'volcanic': .125}
        expressions = [constant(10000), product(2000, 'volcanic'),
            {'operation': 'maximum', 'terms': [
                {'coefficient_m': 2000, 'field': 'carbonate_a'},
                {'coefficient_m': 1000, 'field': 'carbonate_b'}]}]
        expected = [F(10000), F(2000)*F(samples['volcanic']),
                    max(F(2000)*F(samples['carbonate_a']), F(1000)*F(samples['carbonate_b']))]
        for expression, value in zip(expressions, expected):
            self.assertEqual(rules.evaluate(expression, samples), value)
            self.assertIsInstance(rules.evaluate(expression, samples), F)
        self.assertEqual(rules.referenced_fields(expressions[0]), set())
        self.assertEqual(rules.referenced_fields(expressions[1]), {'volcanic'})
        self.assertEqual(rules.referenced_fields(expressions[2]), {'carbonate_a', 'carbonate_b'})
        self.assertEqual(rules.evaluate(product(0, 'volcanic'), samples), 0)
        with self.assertRaisesRegex(ValueError, 'missing formula field'):
            rules.evaluate(product(0, 'absent'), samples)

    def test_nested_exact_math_references_and_bounded_rejections(self):
        expression = {'operation': 'quotient', 'terms': [
            {'operation': 'difference', 'terms': [
                {'operation': 'sum', 'terms': [constant('1/3'), product(2, 'a')]},
                {'operation': 'minimum', 'terms': [product(1, 'b'), constant('1/7')]}]},
            {'operation': 'product', 'terms': [constant(3), product(1, 'c')]}]}
        samples = {'a': '1/2', 'b': '1/5', 'c': '2/3'}
        self.assertEqual(rules.evaluate(expression, samples), F(25, 42))
        self.assertEqual(rules.referenced_fields(expression), {'a', 'b', 'c'})
        invalid = [constant(True), constant(float('nan')), constant(float('inf')),
            constant(1 << 8192), {'operation': '__import__', 'value': 'os'},
            {'operation': 'constant', 'value': 1, 'extra': 2},
            {'operation': 'sum', 'terms': []},
            {'operation': 'sum', 'terms': [constant(1)]*65},
            {'operation': 'difference', 'terms': [constant(1)]},
            {'operation': 'quotient', 'terms': [constant(1), constant(0)]},
            {'operation': 'product', 'coefficient_m': True, 'field': 'a'},
            {'operation': 'maximum', 'terms': [{'coefficient_m': 1, 'field': 'a', 'extra': 2}]},
            product(1, 'UNKNOWN')]
        deep = constant(1)
        for _ in range(16):
            deep = {'operation': 'sum', 'terms': [deep]}
        invalid.append(deep)
        invalid.append({'operation': 'sum', 'terms': [
            {'operation': 'sum', 'terms': [constant(1)]*64}]*4})
        huge = F((1 << 8191)+1, (1 << 8190)+1)
        invalid.append({'operation': 'product', 'terms': [constant(huge), constant(huge)]})
        for item in invalid:
            with self.subTest(expression=item.get('operation')), self.assertRaises(ValueError):
                rules.evaluate(item, samples)
            with self.subTest(references=item.get('operation')), self.assertRaises(ValueError):
                rules.referenced_fields(item)
        for value in (None, True, float('inf'), float('nan')):
            with self.subTest(sample=value), self.assertRaises(ValueError):
                rules.evaluate(product(1, 'bad'), {'bad': value})
        with self.assertRaisesRegex(ValueError, 'missing formula field'):
            rules.evaluate(expression, {})
        with self.assertRaisesRegex(ValueError, 'sample mapping'):
            rules.evaluate(constant(1), None)


if __name__ == '__main__':
    unittest.main()
