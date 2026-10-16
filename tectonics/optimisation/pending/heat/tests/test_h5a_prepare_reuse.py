"""Unit tests for H5a (transforms/h5a_prepare_reuse.py): functionals r5 -> r6, forward r13 -> r14.

Light: no heat call and no W4 case run. The inputs are lw's reviewed helpers (base layout).
1. TransformTests: anchors apply once, reviewed-input refusal, and only the intended definitions change:
   - functionals gains _shared_key, SharedPrepared and prepare_shared and changes _prepare and reconstruct;
   - forward changes only the import and _run;
   - no new upper-case module state (the loaded-identity guard captures it);
   - forward r14 makes ONE prepare_shared, passes it to both reconstruct calls, and closes it after the
     ladder loop, before the HIGH solve.
2. ReuseDecision: r6 loaded from text with a counting fake _prepare. Reuse happens only for the same payload
   object with the same boundary types/lengths/members and the same exact k. A copy, other sets, list vs set,
   a duplicate list, Fraction(1) vs 1 or mpq(1) vs 1 each prepare afresh. A closed SharedPrepared raises.
   prepared_shared=None prepares on every call.
3. EmptyMesh: the REAL _prepare on an empty payload. r5 and r6 (with and without sharing) give equal evidence
   apart from 'seconds'.
The real equivalence proof (W4 same-call control D-b, refinement rows and census equal apart from seconds)
is owed by the forward successor's run; see the transform's docstring.
"""
import ast
import json
import sys
import types
import unittest
from fractions import Fraction
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
LAYOUT = HS/'lw'
sys.path[:0] = json.loads((LAYOUT/'control.json').read_text(encoding='utf8'))['paths']
sys.path.insert(0, str(HS/'transforms'))
import h5a_prepare_reuse as H5A  # noqa: E402
import gmpy2 as G  # noqa: E402
from atlas_tectonics.resources import WorkBudget  # noqa: E402
import private_heat_gmp_resources_r1 as R  # noqa: E402
import private_heat_decimal_sparse_core_r1 as P  # noqa: E402

FUN5 = (LAYOUT/'helpers'/'private_heat_functionals_kernel_r5.py').read_bytes().decode('utf8')
FWD13 = (LAYOUT/'helpers'/'private_heat_forward_kernel_r13.py').read_bytes().decode('utf8')
FUN6 = H5A.functionals(FUN5)
FWD14 = H5A.forward(FWD13)
NEW_FUNCTIONALS = {'_shared_key', 'SharedPrepared', 'prepare_shared'}


def load(name, text):
    module = types.ModuleType(name)
    module.__file__ = str(LAYOUT/'helpers'/(name+'.py'))
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    return module


def top(text):
    out = {}
    for node in ast.parse(text).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            out[node.name] = ast.dump(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                for leaf in ast.walk(target):
                    if isinstance(leaf, ast.Name):
                        out['=' + leaf.id] = ast.dump(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out['import:' + ast.dump(node)] = ''
    return out


class TransformTests(unittest.TestCase):
    def test_anchor_and_refusals(self):
        compile(FUN6, 'f6.py', 'exec')
        compile(FWD14, 'w14.py', 'exec')
        for fn, text in ((H5A.functionals, FUN6), (H5A.forward, FWD14)):
            with self.assertRaises(ValueError):
                fn(text)                                    # not a reviewed input
            with self.assertRaises(ValueError):
                fn(text, allow_unreviewed_input=True)       # anchors are gone: never applied twice
        self.assertNotIn('\r', FUN6 + FWD14)

    def test_only_intended_definitions_change(self):
        a, b = top(FUN5), top(FUN6)
        self.assertEqual(set(b) - set(a), NEW_FUNCTIONALS)
        self.assertEqual(set(a) - set(b), set())
        self.assertEqual({k for k in a if a[k] != b[k]}, {'_prepare', 'reconstruct'})
        a, b = top(FWD13), top(FWD14)
        changed = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
        self.assertEqual({k for k in changed if not k.startswith('import:')}, {'_run'})
        self.assertEqual(sorted(k for k in changed if k.startswith('import:')),
                         sorted(k for k in changed if k.startswith('import:') and 'functionals_kernel_r' in k))
        self.assertEqual(len(changed), 3)                   # _run + the r5 import out + the r6 import in

    def test_no_new_upper_case_module_state(self):
        for old, new in ((FUN5, FUN6), (FWD13, FWD14)):
            added = {k[1:] for k in set(top(new)) - set(top(old)) if k.startswith('=')}
            self.assertEqual({n for n in added if n.upper() == n}, set())

    def test_forward_shares_once_and_closes_before_high(self):
        run = FWD14[FWD14.index('def _run('):FWD14.index('\ndef ', FWD14.index('def _run(')+1)]
        self.assertEqual(run.count('FUNCTIONS.prepare_shared('), 1)
        self.assertEqual(run.count('FUNCTIONS.reconstruct('), 2)
        self.assertEqual(run.count('prepared_shared=prepared_shared'), 2)
        made, first = run.index('FUNCTIONS.prepare_shared('), run.index('FUNCTIONS.reconstruct(')
        closed = run.index('prepared_shared.close()')
        self.assertLess(made, first)
        self.assertLess(run.index("raise ASSEMBLY.UnresolvedRounding('Aggregate rounding unresolved after unchanged"
                                  " finite precision ladder')\n            used"), closed)
        self.assertLess(closed, run.index("stage('solve-certified-high')"))
        self.assertIn('prepared_shared = retain(FUNCTIONS.prepare_shared(', run)
        self.assertNotIn('import private_heat_functionals_kernel_r5', FWD14)


class Fake:
    def __init__(self, module):
        self.calls, self.categories, self.module = 0, [], module
        module._prepared_bytes = lambda prepared, cancelled: None

    def __call__(self, payload, point, power, k, *, budget, cancelled, category='heat-functional-geometry'):
        self.calls += 1
        self.categories.append(category)
        work = R.OwnedWorkspace(budget, 4096, category=category, cancelled=cancelled)
        work.__enter__()
        return P.OwnedSolve(dict(points=[], geometry={}, face_data={}, face_ids=set(), dirichlet={},
                                 neumann=set(), conductivity=k), work)


def call(m, payload, point, power, k, budget, shared):
    owner = m.reconstruct(payload, boundary_point_faces=point, boundary_power_faces=power, budget=budget,
                          conductivity=k, selected_faces=(), prepared_shared=shared)
    try:
        rows, evidence = owner.value
        return rows, {key: value for key, value in evidence.items() if key != 'seconds'}
    finally:
        owner.close()


class ReuseDecision(unittest.TestCase):
    def setUp(self):
        self.m = load('private_heat_functionals_kernel_r6', FUN6)
        self.fake = self.m._prepare = Fake(self.m)
        self.budget = WorkBudget(1 << 34)
        self.payload = dict(cells=[], faces=[])
        self.point, self.power = {'a'}, {'b', 'c'}

    def test_same_call_reuses(self):
        shared = self.m.prepare_shared(self.payload, self.point, self.power, 1, budget=self.budget)
        self.assertEqual((self.fake.calls, self.fake.categories), (1, ['heat-functional-geometry-shared']))
        first = call(self.m, self.payload, self.point, self.power, 1, self.budget, shared)
        second = call(self.m, self.payload, set(self.point), set(self.power), 1, self.budget, shared)
        self.assertEqual((self.fake.calls, shared.uses), (1, 2))
        plain = call(self.m, self.payload, self.point, self.power, 1, self.budget, None)
        self.assertEqual((self.fake.calls, self.fake.categories[-1]), (2, 'heat-functional-geometry'))
        self.assertEqual(first, second)
        self.assertEqual(first, plain)
        shared.close()
        shared.close()                                      # idempotent, as on the forward's stack

    def test_mismatch_prepares_afresh(self):
        shared = self.m.prepare_shared(self.payload, self.point, self.power, 1, budget=self.budget)
        cases = [(dict(self.payload), self.point, self.power, 1),        # equal copy, other object
                 (self.payload, {'a', 'x'}, self.power, 1),
                 (self.payload, self.point, {'b'}, 1),
                 (self.payload, ['a'], self.power, 1),                   # list vs set
                 (self.payload, ['a', 'a'], self.power, 1),              # duplicate
                 (self.payload, self.point, self.power, Fraction(1)),
                 (self.payload, self.point, self.power, G.mpq(1)),
                 (self.payload, self.power, self.point, 1)]              # partitions swapped
        for n, (payload, point, power, k) in enumerate(cases):
            call(self.m, payload, point, power, k, self.budget, shared)
            self.assertEqual((self.fake.calls, shared.uses), (2+n, 0), n)
        shared.close()

    def test_closed_shared_raises(self):
        shared = self.m.prepare_shared(self.payload, self.point, self.power, 1, budget=self.budget)
        shared.close()
        with self.assertRaises(RuntimeError):
            call(self.m, self.payload, self.point, self.power, 1, self.budget, shared)
        with self.assertRaises(RuntimeError):
            shared.value

    def test_exit_with_error_passes_the_error_to_the_owner(self):
        shared = self.m.prepare_shared(self.payload, self.point, self.power, 1, budget=self.budget)
        seen = []
        owner = shared._owner
        owner.__exit__ = lambda *exc: seen.append(exc[0]) or False
        self.assertFalse(shared.__exit__(KeyError, KeyError('x'), None))
        self.assertEqual(seen, [KeyError])
        self.assertFalse(shared.__exit__(None, None, None))  # already released: no second exit
        owner._workspace.__exit__(None, None, None)

    def test_module_state_unchanged_by_calls(self):
        before = set(vars(self.m))
        shared = self.m.prepare_shared(self.payload, self.point, self.power, 1, budget=self.budget)
        call(self.m, self.payload, self.point, self.power, 1, self.budget, shared)
        shared.close()
        self.assertEqual(set(vars(self.m)), before)


class EmptyMesh(unittest.TestCase):
    def test_real_prepare_r5_equals_r6(self):
        old = load('private_heat_functionals_kernel_r5_h5a', FUN5)
        new = load('private_heat_functionals_kernel_r6_h5a', FUN6)
        budget = WorkBudget(1 << 34)
        payload = dict(cells=[], faces=[])
        reference = call(types.SimpleNamespace(reconstruct=lambda *a, prepared_shared, **k: old.reconstruct(*a, **k)),
                         payload, set(), set(), 1, budget, None)
        shared = new.prepare_shared(payload, set(), set(), 1, budget=budget)
        self.assertEqual(call(new, payload, set(), set(), 1, budget, shared), reference)
        self.assertEqual(call(new, payload, set(), set(), 1, budget, None), reference)
        self.assertEqual(shared.uses, 1)
        shared.close()


if __name__ == '__main__':
    unittest.main()
