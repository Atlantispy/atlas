"""Exact same-point/same-square reuse inside one AST-extracted chart call.

No production imports, stage, workers, timing, invariant hoisting or integration.
"""
import argparse
import ast
from collections import Counter
import copy
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HELPER_PIN = 'bcabef407a99aae01af82f9ec7d50d7d9378b1bce76a7885db89f4f0bcfbfa5a'


class PointMemo:
    def __init__(self):
        self.rows = {'radius2': [], '_sqrt': []}
        self.calls, self.misses = Counter(), Counter()

    def get(self, name, args, original):
        self.calls[name] += 1
        eligible = all(type(v) in (int, Fraction) for v in args)
        if eligible:
            for previous, value in self.rows[name]:
                if all(type(a) is type(b) and a == b for a, b in zip(previous, args, strict=True)):
                    return value
        value = original()  # Original exception propagates; failing value is not cached.
        self.misses[name] += 1
        if eligible:
            self.rows[name].append((args, value))
            assert len(self.rows[name]) <= (3 if name == 'radius2' else 2)
        return value


class Reuse(ast.NodeTransformer):
    def __init__(self):
        self.hits = Counter()

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in ('radius2', '_sqrt'):
            self.hits[node.func.id] += 1
            return ast.Call(func=ast.Attribute(value=ast.Name(id='_memo', ctx=ast.Load()), attr='get', ctx=ast.Load()),
                            args=[ast.Constant(node.func.id), ast.Tuple(elts=copy.deepcopy(node.args), ctx=ast.Load()),
                                  ast.Lambda(args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
                                             body=copy.deepcopy(node))], keywords=[])
        return self.generic_visit(node)


class Undo(ast.NodeTransformer):
    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == '_memo':
            return copy.deepcopy(node.args[2].body)
        return self.generic_visit(node)


def transform(original, name):
    visitor = Reuse()
    result = visitor.visit(copy.deepcopy(original))
    assert visitor.hits == {'radius2': 3, '_sqrt': 2}
    assert ast.dump(Undo().visit(copy.deepcopy(result)), include_attributes=False) == ast.dump(original, include_attributes=False)
    result.name = name
    result.body.insert(1, ast.parse('_memo = _new_point_memo()').body[0])
    return ast.fix_missing_locations(result)


def outcome(fn, encode, args):
    try:
        return ('value', encode(fn(*args)))
    except (ValueError, ZeroDivisionError, TypeError) as error:
        return ('error', type(error).__name__, str(error))


def main():
    if sys.flags.optimize:
        raise SystemExit('refused: assertions must remain enabled')
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert hashlib.sha256(args.helper.read_bytes()).hexdigest() == HELPER_PIN
    spec = importlib.util.spec_from_file_location('point_probe_support', args.helper)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.SOURCE, helper.VECTOR = args.repo/helper.SOURCE_REL, args.repo/helper.VECTOR_REL
    ns = helper.build()  # Extracts definitions only; does not run the helper's suite.
    original = next(n for n in ast.parse(helper.SOURCE.read_bytes()).body
                    if isinstance(n, ast.FunctionDef) and n.name == '_radial_chart_jets')
    candidate = transform(original, '_point_chart')
    # The unchanged radius-bound prefix is also needed by a derivative-free chart.
    prefix = copy.deepcopy(original)
    stop = next(i for i, n in enumerate(prefix.body) if isinstance(n, ast.Assign)
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 's')
    prefix.body = prefix.body[:stop+1] + [ast.Return(value=ast.Name(id='s', ctx=ast.Load()))]
    prefix.name = '_value_norm'
    prefix = ast.fix_missing_locations(prefix)
    value_candidate = transform(prefix, '_point_value_norm')
    pending = []
    def make_memo():
        memo = PointMemo()
        pending.append(memo)
        return memo
    ns['_new_point_memo'] = make_memo
    exec(compile(ast.fix_missing_locations(ast.Module(body=[candidate, prefix, value_candidate], type_ignores=[])),
                 '<chart-point-probe>', 'exec'), ns)
    comparisons, records = Counter(), []
    q = Fraction
    normal = tuple(map(q, (0, 0, 1)))
    fixtures = [
        ('midpoint', (1, 0, 0), (0, 1, 0), q(1, 2), q(1, 2)),
        ('closest-left', (1, 0, 0), (2, 1, 0), q(0), q(1)),
        ('closest-right', (2, 1, 0), (1, 0, 0), q(0), q(1)),
        ('interior', (1, 0, 0), (0, 1, 0), q(0), q(1)),
        ('stationary', (2, 1, 0), (2, 1, 0), q(0), q(1)),
        ('nondyadic-midpoint', (q(2, 3), q(5, 7), 1), (q(11, 13), q(-1, 5), 2), q(3, 11), q(3, 11)),
        ('wide-midpoint', (q(2**128+1, 7), 1, 0), (1, q(2**100+1, 9), 2), q(1, 3), q(1, 3)),
        ('origin-crossing', (1, 0, 0), (-1, 0, 0), q(0), q(1)),
        ('origin-point', (1, 0, 0), (-1, 0, 0), q(1, 2), q(1, 2)),
    ]
    for label, av, bv, left, right in fixtures:
        for bits in (32, 96):
            values = tuple(map(q, av)), tuple(map(q, bv)), normal, left, right, bits
            ns['_JET_PRECISION'].set(bits)
            for plain, changed, scope in (('_radial_chart_jets', '_point_chart', 'full_chart'),
                                          ('_value_norm', '_point_value_norm', 'value_norm_prefix')):
                expected = outcome(ns[plain], helper.encoded, values)
                actual = outcome(ns[changed], helper.encoded, values)
                assert actual == expected, (label, scope)
                assert len(pending) == 1
                memo = pending.pop()
                comparisons[scope+'_'+actual[0]] += 1
                if scope == 'full_chart':
                    records.append(dict(case=label, bits=bits, result=actual[0], calls=dict(memo.calls), misses=dict(memo.misses)))
                if left == right:
                    assert memo.misses['radius2'] == 1
                    assert memo.misses['_sqrt'] == (1 if actual[0] == 'value' else 0)
                if label.startswith('origin'):
                    assert memo.calls['_sqrt'] == 0
    # Actual helper failure remains at its first original call; no cache entry survives it.
    original_sqrt = ns['_sqrt']
    def refused_sqrt(*_):
        raise helper.Refused('injected first square-root refusal')
    ns['_sqrt'] = refused_sqrt
    values = tuple(map(q, (1, 0, 0))), tuple(map(q, (0, 1, 0))), normal, q(1, 2), q(1, 2), 96
    assert outcome(ns['_radial_chart_jets'], helper.encoded, values) == outcome(ns['_point_chart'], helper.encoded, values)
    memo = pending.pop()
    assert memo.calls['_sqrt'] == 1 and not memo.rows['_sqrt']
    ns['_sqrt'] = original_sqrt
    # A wrong cached square-root tuple must be caught by the complete output comparator.
    class Corrupt(PointMemo):
        def get(self, name, call_args, original_call):
            if name == '_sqrt' and self.rows[name]:
                lo, hi = self.rows[name][0][1]
                return lo, hi+1
            return super().get(name, call_args, original_call)
    ns['_new_point_memo'] = Corrupt
    assert outcome(ns['_radial_chart_jets'], helper.encoded, values) != outcome(ns['_point_chart'], helper.encoded, values)
    # Precision participates in reuse identity; changing it must compute afresh.
    memo = PointMemo()
    assert memo.get('_sqrt', (q(2), 32), lambda: (1, 2)) == (1, 2)
    assert memo.get('_sqrt', (q(2), 96), lambda: (3, 4)) == (3, 4)
    assert memo.misses['_sqrt'] == 2
    result = dict(status='PASS', scope='synthetic per-invocation reuse only; no stage, timing or funded-runtime acceptance',
                  adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), helper_sha256=HELPER_PIN,
                  source_sha256=helper.PIN, vector_sha256=helper.VPIN,
                  comparisons=dict(comparisons), records=records,
                  controls=['AST expression order restored exactly', 'full jets and exact radial expression compared',
                            'fresh cache each invocation', 'origin refusal before any sqrt', 'first sqrt failure not cached',
                            'wrong reused sqrt detected', 'precision included in reuse identity'],
                  actual_capture_replay='NOT RUN', repeated_existing_arithmetic_suite=False)
    args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('status', 'adapter_sha256', 'comparisons', 'controls')}))


if __name__ == '__main__':
    main()
