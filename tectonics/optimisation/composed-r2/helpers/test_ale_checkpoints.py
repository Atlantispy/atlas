"""Check the new explicit parameter reaches only endpoint queries, unchanged maths."""
import ast
from pathlib import Path
import unittest

from patch_ale_checkpoints import candidate_source


BASE = Path(__file__).resolve().parent.parent/'runtime-integration-r1/runtime-src/atlas_tectonics'


class ALECheckpointWiringTests(unittest.TestCase):
    def test_only_optional_plumbing_changes(self):
        old = ast.parse((BASE/'integration_differential_ale.py').read_text(encoding='utf8'))
        new = ast.parse(candidate_source(BASE))
        changed_functions, changed_calls = [], []
        for node in ast.walk(new):
            if isinstance(node, ast.FunctionDef):
                for at, argument in enumerate(node.args.kwonlyargs):
                    if argument.arg == '_endpoint_checkpoints':
                        self.assertIsInstance(node.args.kw_defaults[at], ast.Constant)
                        self.assertIsNone(node.args.kw_defaults[at].value)
                        changed_functions.append(node.name)
                        del node.args.kwonlyargs[at]
                        del node.args.kw_defaults[at]
                        break
            if isinstance(node, ast.Call):
                for at, keyword in enumerate(node.keywords):
                    if keyword.arg in ('_checkpoint', '_endpoint_checkpoints'):
                        self.assertIsInstance(keyword.value, ast.Name)
                        self.assertEqual(keyword.value.id, '_endpoint_checkpoints')
                        changed_calls.append(ast.unparse(node.func))
                        del node.keywords[at]
                        break
        self.assertEqual(sorted(changed_functions), ['_enclose', 'enclose_differential_ale'])
        self.assertEqual(sorted(changed_calls), ['E.measure_endpoint', '_enclose'])
        self.assertEqual(ast.dump(old), ast.dump(new))

    def test_no_default_store_or_new_lifetime(self):
        text = candidate_source(BASE)
        self.assertNotIn('EndpointCheckpoints(', text)
        self.assertNotIn('_endpoint_checkpoints.close()', text)
        compile(text, 'private-checkpoint-ALE', 'exec')


if __name__ == '__main__':
    unittest.main()
