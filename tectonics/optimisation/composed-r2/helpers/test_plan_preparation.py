"""No real saved checkpoint and no interval solve; actual small plan preparation."""
import ast
import gc
from pathlib import Path
import unittest

import plan_preparation as P
SOURCE = Path(__file__).resolve().parents[3]/'heat-repair-20261007/source/tectonics/tests/i04_differential_fixture.py'


class SourceTests(unittest.TestCase):
    def test_exact_preparation_prefix_and_no_fresh_funding(self):
        original = ast.parse(SOURCE.read_text(encoding='utf8'))
        changed = ast.parse(P.transformed_source(SOURCE.read_bytes()))
        old_function = next(node for node in original.body if isinstance(node, ast.FunctionDef)
                            and node.name == 'radial_differential_fixture')
        new_function = next(node for node in changed.body if isinstance(node, ast.FunctionDef)
                            and node.name == 'prepare_saved_plans')
        old_with, new_with = old_function.body[-1], new_function.body[-1]
        self.assertEqual(ast.dump(ast.Module(body=old_function.body[:-1], type_ignores=[])),
                         ast.dump(ast.Module(body=new_function.body[:-1], type_ignores=[])))
        self.assertEqual(ast.dump(old_with.items[0]), ast.dump(new_with.items[0]))
        # All native/component/owner/collar preparation before the innermost
        # admission boundary is identical, not reconstructed from prose.
        self.assertEqual(ast.dump(ast.Module(body=old_with.body[:-1], type_ignores=[])),
                         ast.dump(ast.Module(body=new_with.body[:-1], type_ignores=[])))
        old_inner, new_inner = old_with.body[-1], new_with.body[-1]
        self.assertEqual([ast.dump(x) for x in old_inner.items], [ast.dump(x) for x in new_inner.items])
        names = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                 for node in ast.walk(new_function) if isinstance(node, ast.Call)
                 and isinstance(node.func, (ast.Name, ast.Attribute))}
        self.assertFalse({'fund', 'carve_basal_inventory', 'initial_state_from_funding',
                          'finite_birth_stocks', 'finite_export_stocks'} & names)

    def test_changed_source_refused(self):
        with self.assertRaises(ValueError):
            P.transformed_source(SOURCE.read_bytes()+b'\n')


class ActualPlansTest(unittest.TestCase):
    def test_no_state_no_debit_and_zero_cleanup(self):
        import test_native_transfer as T
        T.setUpModule()
        try:
            from atlas_tectonics.resources import WorkBudget
            import native_transfer as N
            budget = WorkBudget(256 << 20)
            prepare = P.load_preparation(SOURCE)
            with prepare(budget=budget, pressure_space='q1-p0', material_quadrature=True) as case:
                self.assertTrue({'native', 'collar', 'registry', 'source', 'volume_map'} <= set(case))
                self.assertFalse({'funding', 'initial_funding', 'state', 'finite_rows'} & set(case))
                self.assertEqual(case['native'].statistics()['accepted_intervals'], 0)
                self.assertEqual(case['native'].statistics()['mechanical_preparations'], 0)
                graph = N.current_plan_graph(case['native'], case['collar'])
                self.assertEqual(graph['native']['plan_id'], case['native'].plan_id)
            del case, graph, prepare
            gc.collect()
            self.assertEqual(budget.reserved_bytes, 0)
        finally:
            T.tearDownModule()


if __name__ == '__main__':
    unittest.main()
