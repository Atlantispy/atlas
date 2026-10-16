"""Focused native-consumer controls; not a real saved-world acceptance run."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

import mimetic_patch as P


HERE = Path(__file__).resolve().parent
BASE = HERE.parent.parent/'runtime-integration-r1'/'runtime-src'/'atlas_tectonics'


class SourceTransform(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = (BASE/'integration_mimetic_heat.py').read_text(encoding='utf-8')
        cls.patched = P.mimetic_source(cls.original)

    def test_exact_validator_is_identical_except_indexed_row_access(self):
        self.assertEqual(P.validator_ast(self.original, compact=False),
                         P.validator_ast(self.patched, compact=True))

    def test_ordinary_constructor_and_metric_sizing_unchanged(self):
        def selected(source):
            tree = ast.parse(source)
            owner = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'MimeticGeometry')
            names = ('_metric_allocation_capacity', '_admitted_moment_fails', '_moment_fails')
            return [ast.dump(x, include_attributes=False) for x in tree.body
                    if isinstance(x, ast.FunctionDef) and x.name in names]+[
                        ast.dump(next(x for x in owner.body if isinstance(x, ast.FunctionDef) and
                                      x.name == '__init__'), include_attributes=False)]
        self.assertEqual(selected(self.original), selected(self.patched))

    def test_source_drift_and_double_application_refused(self):
        for source in (self.original+'\n', self.patched):
            with self.assertRaisesRegex(ValueError, 'differs from the reviewed base'):
                P.mimetic_source(source)

    def test_extremum_diagnostic_fetches_only_one_cell_id(self):
        original = (BASE/'integration_extremum_heat.py').read_text(encoding='utf-8')
        actual = P.extremum_source(original)
        self.assertEqual(actual.replace('geometry.cell_id(ci)', "geometry.record()['cells'][ci]['cell_id']"), original)
        with self.assertRaises(ValueError):
            P.extremum_source(actual)

    def test_indexed_constructor_has_no_json_export_or_whole_record_call(self):
        tree = ast.parse(self.patched)
        owner = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'MimeticGeometry')
        method = next(x for x in owner.body if isinstance(x, ast.FunctionDef) and x.name == 'from_compact')
        for node in ast.walk(method):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
                self.assertNotIn(name, ('legacy_record', 'record', '_stream_json', 'loads', 'dumps'))


if __name__ == '__main__':
    unittest.main()
