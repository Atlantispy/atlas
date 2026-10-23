"""Bounded controls for the AST-only constructor; no Atlas imports or runs."""
import unittest
import os
from pathlib import Path

import propagate_bindings as P


class PinConstructionTests(unittest.TestCase):
    def setUp(self):
        self.dependency = 'private_heat_restored_binding_ram_context_r1.py'
        self.old = P.OLD[self.dependency]
        self.selected = {P.PREFIX + self.dependency: {'public_sha256': 'a' * 64}}
        self.rules = {'_BINDING_SHA': self.dependency}

    def rewrite(self, data):
        return P.rewrite(data, 'recovery.py', (), self.rules, self.selected)

    def test_only_declared_pin_changes(self):
        data = ("# " + self.old + "\r\n_BINDING_SHA = '" + self.old +
                "'\r\nOTHER = '" + self.old + "'\r\n").encode()
        expected = data.replace(("_BINDING_SHA = '" + self.old).encode(),
                                ("_BINDING_SHA = '" + 'a' * 64).encode())
        self.assertEqual(self.rewrite(data), expected)

    def test_missing_mutated_duplicate_and_nonliteral_refused(self):
        candidates = [b'OTHER = 1\n', b"_BINDING_SHA = 'wrong'\n",
                      ("_BINDING_SHA = '" + self.old + "'\n") .encode() * 2,
                      b'_BINDING_SHA = calculate()\n']
        for data in candidates:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.rewrite(data)

    def test_pin_dictionary_missing_member_refused(self):
        with self.assertRaises(ValueError):
            P.rewrite(b'_PINS = {}\n', 'joined.py', P.JOINED, {}, {})

    def test_generated_update_accepts_only_pin_changes(self):
        original = ("_BINDING_SHA = '" + self.old + "'\n").encode()
        generated = self.rewrite(original)
        P.validate_generated(original, generated, 'recovery.py', (), self.rules)
        for mutated in (generated + b'GUARD = False\n',
                        generated.replace(b'_BINDING_SHA', b'CHANGED'),
                        generated.replace(b'a' * 64, b'not-a-hash')):
            with self.subTest(mutated=mutated), self.assertRaises(ValueError):
                P.validate_generated(original, mutated, 'recovery.py', (), self.rules)


class FinalSelectedChainTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('P40_SELECTED_MAP'),
                         'Set P40_SELECTED_MAP to final repository-relative map')
    def test_actual_final_selected_receiving_chains(self):
        root = Path(__file__).resolve().parents[6]
        checked = P.validate_selection(root, os.environ['P40_SELECTED_MAP'])
        self.assertEqual(checked, [P.PREFIX + name for name, _, _ in P.RULES])


if __name__ == '__main__':
    unittest.main()
