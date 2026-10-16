"""Narrow binding/seam checks; not a migrated workflow acceptance test."""
import ast
from pathlib import Path
import types
import unittest

import geometry_transfer as X


BASE = Path(__file__).resolve().parent.parent/'runtime-integration-r1/runtime-src/atlas_tectonics'


class GeometryTransferSeamTests(unittest.TestCase):
    def test_default_equal_binding_and_arbitrary_token_refusal(self):
        collar = types.SimpleNamespace(plan_id='current')
        self.assertTrue(X.collar_binding_matches({'collar_plan_id': 'current'}, None, collar, None, None))
        for token in (None, object(), {'current': 'historical'}):
            self.assertFalse(X.collar_binding_matches({'collar_plan_id': 'historical'}, None, collar, None, token))
        with self.assertRaises(TypeError):
            X.ParentGeometryTransfer()

    def test_exact_source_change_set(self):
        old = ast.parse((BASE/'integration_differential_geometry.py').read_text(encoding='utf8'))
        patched = X.candidate_source(BASE)
        compile(patched, 'geometry-parent-transfer', 'exec')
        new = ast.parse(patched)
        helper = new.body.pop()
        self.assertIsInstance(helper, ast.FunctionDef)
        self.assertEqual(helper.name, '_transferred_collar_binding')
        names, calls = [], []
        for node in ast.walk(new):
            if isinstance(node, ast.FunctionDef):
                for at, argument in enumerate(node.args.kwonlyargs):
                    if argument.arg == '_runtime_transfer':
                        self.assertIsNone(node.args.kw_defaults[at].value)
                        del node.args.kwonlyargs[at]
                        del node.args.kw_defaults[at]
                        names.append(node.name)
                        break
            if isinstance(node, ast.BoolOp):
                for at, value in enumerate(node.values):
                    if (isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not)
                            and isinstance(value.operand, ast.Call)
                            and ast.unparse(value.operand.func) == '_transferred_collar_binding'):
                        call = value.operand
                        which = call.args[0].id
                        calls.append(which)
                        self.assertEqual([ast.unparse(x) for x in call.args[1:]],
                            ['funding', 'collar', 'budget', '_runtime_transfer'])
                        expression = ("body.get('collar_plan_id') != collar.plan_id" if which == 'body'
                                      else "old['collar_plan_id'] != collar.plan_id")
                        node.values[at] = ast.parse(expression, mode='eval').body
        self.assertEqual(sorted(names), ['prepare_interval_partition', 'restore'])
        self.assertEqual(sorted(calls), ['body', 'old'])
        self.assertEqual(ast.dump(old), ast.dump(new))


if __name__ == '__main__':
    unittest.main()
