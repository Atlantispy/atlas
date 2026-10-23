"""AST-only chart-local inverse reuse; preserves reciprocal constant branch."""
import argparse
import ast
import copy
from fractions import Fraction as Q
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HELPER_PIN = 'bcabef407a99aae01af82f9ec7d50d7d9378b1bce76a7885db89f4f0bcfbfa5a'


class Replace(ast.NodeTransformer):
    def __init__(self, before, after):
        self.before, self.after = ast.parse(before, mode='eval').body, ast.parse(after, mode='eval').body
        self.hits = 0

    def visit(self, node):
        if ast.dump(node, include_attributes=False) == ast.dump(self.before, include_attributes=False):
            self.hits += 1
            return copy.deepcopy(self.after)
        return super().visit(node)


def change(original, before, after):
    rewrite = Replace(before, after)
    candidate = rewrite.visit(copy.deepcopy(original))
    assert rewrite.hits == 1
    undo = Replace(after, before)
    restored = undo.visit(copy.deepcopy(candidate))
    assert undo.hits == 1 and ast.dump(restored, include_attributes=False) == ast.dump(original, include_attributes=False)
    return candidate


def main():
    if sys.flags.optimize:
        raise SystemExit('refused: assertions must remain enabled')
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert hashlib.sha256(args.helper.read_bytes()).hexdigest() == HELPER_PIN
    spec = importlib.util.spec_from_file_location('chart_inverse_support', args.helper)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.SOURCE, helper.VECTOR = args.repo/helper.SOURCE_REL, args.repo/helper.VECTOR_REL
    ns = helper.build()
    tree = ast.parse(helper.SOURCE.read_bytes())
    chart = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_radial_chart_jets')
    reciprocal = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_jet_reciprocal')
    changed_chart = change(chart, '_jet_reciprocal(s_jet)', '_chart_reciprocal(s_jet, inv_s)')
    changed_chart.name = '_inverse_reuse_chart'
    changed_reciprocal = change(reciprocal, '_divide(_ONE, a[0])', 'already_inverted')
    changed_reciprocal.name = '_chart_reciprocal'
    changed_reciprocal.args.args.append(ast.arg(arg='already_inverted'))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[changed_chart, changed_reciprocal], type_ignores=[])),
                 '<chart-inverse-reuse>', 'exec'), ns)
    divide = ns['_divide']
    calls = []
    def count(q, pair):
        calls.append((q, pair))
        return divide(q, pair)
    ns['_divide'] = count
    fixtures = [
        ('midpoint', (1, 0, 0), (0, 1, 0), Q(1, 2), Q(1, 2)),
        ('interval', (1, 0, 0), (0, 1, 0), Q(0), Q(1)),
        ('constant-exact', (1, 0, 0), (1, 0, 0), Q(0), Q(1)),
        ('stationary-irrational', (1, 1, 0), (1, 1, 0), Q(0), Q(1)),
        ('origin-refusal', (1, 0, 0), (-1, 0, 0), Q(0), Q(1))]
    records = []
    normal = tuple(map(Q, (0, 0, 1)))
    for label, av, bv, left, right in fixtures:
        for bits in (32, 96):
            ns['_JET_PRECISION'].set(bits)
            values = tuple(map(Q, av)), tuple(map(Q, bv)), normal, left, right, bits
            calls.clear()
            original = helper.outcome(ns['_radial_chart_jets'], *values)
            original_calls = list(calls)
            calls.clear()
            candidate = helper.outcome(ns['_inverse_reuse_chart'], *values)
            candidate_calls = list(calls)
            assert original == candidate
            assert original_calls[:len(candidate_calls)] == candidate_calls
            if label == 'origin-refusal':
                assert not original_calls and not candidate_calls
            elif label == 'constant-exact':
                assert len(original_calls) == len(candidate_calls) == 1
            else:
                assert len(original_calls) == 2 and original_calls[0] == original_calls[1] and len(candidate_calls) == 1
            records.append(dict(case=label, bits=bits, result=original[0], original_divides=len(original_calls),
                                candidate_divides=len(candidate_calls)))
    # Constant fast path ignores the supplied inverse entirely.
    constant = ns['_jet_constant'](Q(2))
    assert helper.encoded(ns['_chart_reciprocal'](constant, object())) == helper.encoded(ns['_jet_reciprocal'](constant))
    # Original first divide remains the failure boundary before reciprocal reuse.
    def refusal(*_):
        raise helper.Refused('injected initial inverse refusal')
    ns['_divide'] = refusal
    values = tuple(map(Q, (1, 0, 0))), tuple(map(Q, (0, 1, 0))), normal, Q(1, 2), Q(1, 2), 96
    assert helper.outcome(ns['_radial_chart_jets'], *values) == helper.outcome(ns['_inverse_reuse_chart'], *values)
    result = dict(status='PASS', scope='chart-local inverse AST feasibility only; no production, stage or timing',
                  adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), helper_sha256=HELPER_PIN,
                  source_sha256=helper.PIN, vector_sha256=helper.VPIN, records=records,
                  constant_fast_branch_ignores_supplied_inverse=True, initial_divide_refusal_preserved=True,
                  reversible_AST_expression_replacement=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
