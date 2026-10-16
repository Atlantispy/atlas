"""The funding seam on the work-ceiling continuation derivative; text only.

The historical helper and control are read, never executed: only the helper's
pure _EDITS/_replace_exact definitions are evaluated to derive the text.
"""
import ast
from hashlib import sha256
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
HISTORICAL = HERE.parents[2]/'heat-repair-20261007'
sys.path[:0] = [str(HERE), str(HERE/'compact-geometry-r1')]

import funding_transfer as X
import partition_routing_transform as RT


def texts():
    helper = (HISTORICAL/'private_heat_original_continuation_r1.py').read_text(encoding='utf8')
    control = (HISTORICAL/'source'/'tectonics'/'tests'/'i04_differential_continuation_control.py').read_text(encoding='utf8')
    namespace = {}
    keep = [n for n in ast.parse(helper).body if (isinstance(n, ast.Assign) and any(
        getattr(t, 'id', None) == '_EDITS' for t in n.targets)) or (isinstance(n, ast.FunctionDef) and n.name == '_replace_exact')]
    exec(compile(ast.Module(keep, []), 'helper-edits', 'exec'), namespace)
    return control, namespace['_replace_exact'](control, namespace['_EDITS'])


def without_funding(source):
    """Remove the binding creation and the forwarded keyword; return (tree, calls)."""
    tree, calls = ast.parse(source), []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'continuation_pressure_force':
            node.body = [s for s in node.body if not (isinstance(s, ast.ImportFrom) and s.module == 'funding_transfer')
                         and ast.unparse(s) != '_funding_transfer = for_workflow(workflow)']
        if isinstance(node, ast.Call):
            for keyword in list(node.keywords):
                if keyword.arg == '_runtime_funding_transfer':
                    if ast.unparse(keyword.value) != '_funding_transfer':
                        raise AssertionError('forwarded value differs')
                    calls.append(ast.unparse(node.func))
                    node.keywords.remove(keyword)
    return tree, sorted(calls)


class AfterLimits(unittest.TestCase):
    def test_seam_composes_after_the_limit_and_compact_edits_only(self):
        control, derived = texts()
        self.assertEqual(sha256(derived.encode()).hexdigest(), RT.DERIVED_CONTROL_SHA256)
        for label, base in (('limits', derived), ('limits+compact', RT.continuation_control_source(derived))):
            with self.subTest(label=label):
                result = X.continuation_control_source_after_limits(base)
                compile(result, label, 'exec')
                tree, calls = without_funding(result)
                self.assertEqual(calls, ['P.differential_pressure_forcing', 'P.prescribe_reservoir_pressure'])
                self.assertEqual(ast.dump(tree), ast.dump(ast.parse(base)))
                self.assertEqual(result.count('    _funding_transfer = for_workflow(workflow)\n'
                                              '    datum = RadialDatum(10., 1., 1., 7., 1.1, 0.,\n'), 1)
                self.assertIn('max_leaves=pressure_max_leaves, budget=budget,\n'
                              '            _runtime_funding_transfer=_funding_transfer)', result)
                with self.assertRaises(X.FundingTransferRefused):
                    X.continuation_control_source_after_limits(result)
        # Applied first, the funding seam changes the pinned compact input: refused.
        with self.assertRaises(RT.CompactRoutingRefused):
            RT.continuation_control_source(X.continuation_control_source_after_limits(derived))

    def test_unlimited_source_stays_with_the_original_seam(self):
        control, derived = texts()
        for source in (control, b'not text', derived.replace('max_leaves=pressure_max_leaves, budget=budget)', '')):
            with self.subTest(source=type(source).__name__), self.assertRaises(X.FundingTransferRefused):
                X.continuation_control_source_after_limits(source)
        # The existing function is unchanged: it still takes the literal-limit
        # source and still refuses the work-ceiling derivative.
        tree, calls = without_funding(X.continuation_control_source(control))
        self.assertEqual(ast.dump(tree), ast.dump(ast.parse(control)))
        self.assertEqual(len(calls), 2)
        with self.assertRaises(X.FundingTransferRefused):
            X.continuation_control_source(derived)


if __name__ == '__main__':
    unittest.main(verbosity=2)
