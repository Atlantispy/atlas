"""Source-bound extension controls. No timing, JIT, workers or production edits."""
if not __debug__:
    raise RuntimeError('Optimised execution is unsupported: control assertions are required')

import ast
from concurrent.futures import CancelledError
from decimal import Decimal as D, localcontext, ROUND_HALF_EVEN
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import gmpy2 as G

ROOT = Path(__file__).resolve().parents[5]
selection = ROOT / 'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
assert sha256(selection.read_bytes()).hexdigest() == 'ce77c8f2922e0d8780e241ba9204e775388fa093935968eaee7c577606baaccc'
entries = json.loads(selection.read_text(encoding='utf-8'))['entries']
sources = {}
def tree(name):
    e = next(e for e in entries if e['member'] == 'source/helpers/' + name)
    p = ROOT / e['public_path']
    assert sha256(p.read_bytes()).hexdigest() == e['public_sha256']
    sources[e['public_path']] = e['public_sha256']
    return ast.parse(p.read_text(encoding='utf-8'))

finish_tree = tree('private_heat_finish_arithmetic_r1.py')
finish_ns = dict(Q=Fraction, exact_library=lambda: G, CancelledError=CancelledError)
nodes = [n for n in finish_tree.body if isinstance(n, ast.FunctionDef) and n.name in ('rational', 'paired_global_balance')]
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<selected-finish-functions>', 'exec'), finish_ns)
A = SimpleNamespace(paired_global_balance=finish_ns['paired_global_balance'])
low_tree = tree('private_heat_low_solver_kernel_r5.py')
low_ns = {}
node = next(n for n in low_tree.body if isinstance(n, ast.FunctionDef) and n.name == '_residual')
exec(compile(ast.Module(body=[node], type_ignores=[]), '<selected-low-residual>', 'exec'), low_ns)
solve = next(n for n in low_tree.body if isinstance(n, ast.FunctionDef) and n.name == '_solve')
def assigned(node):
    return node.targets[0].id if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) else None
start = next(i for i, node in enumerate(solve.body) if assigned(node) == 'public_balance')
end = next(i for i, node in enumerate(solve.body) if assigned(node) == 'relative')
body = solve.body[start:end+1]
reference_code = compile(ast.Module(body=body, type_ignores=[]), '<selected-low-public-audit>', 'exec')
candidate_text = ast.unparse(ast.Module(body=body, type_ignores=[]))
candidate_text = 'public_exact = list(map(Q, public_energy))\n' + candidate_text.replace('list(map(Q, public_energy))', 'public_exact').replace('map(Q, public_energy)', 'public_exact')
candidate_code = compile(candidate_text, '<candidate-low-public-audit>', 'exec')
low_results = []
for public in ([0.0, -0.0, 1.25, -2.5], [1e-300, 1e300, 0.1]):
    outputs = []
    for code in (reference_code, candidate_code):
        calls, checks = [0], [0]
        def Q(value):
            calls[0] += 1
            return Fraction(value)
        def cancel():
            checks[0] += 1
            return False
        ns = dict(Q=Q, A=A, _residual=low_ns['_residual'], public_energy=list(public),
                  faces=[(0, 1, Fraction(1, 7)), (len(public)-1, None, Fraction(-2, 3))],
                  load=[Fraction(v)-Fraction(1, 9) for v in public], delta=Fraction(1, 2),
                  src=[Fraction(1, 3)]*len(public), e0=[Fraction(v) for v in public], cancel=cancel)
        exec(code, ns)
        outputs.append((tuple(ns['public_balance']), ns['global_balance'], ns['scale'], ns['relative'], calls[0], checks[0]))
    assert outputs[0][:4] == outputs[1][:4] and outputs[0][5] == outputs[1][5]
    # Two extra Q calls convert outward and final total; only public float
    # conversions change, from three complete vectors to one.
    assert outputs[0][4]-outputs[1][4] == 2*len(public)
    low_results.append(dict(cells=len(public), reference_Q_calls=outputs[0][4], candidate_Q_calls=outputs[1][4], cancel_calls=outputs[0][5]))

# Capture the actual HIGH matrix-construction loop. Replace only literal
# Decimal(0) constructors, keeping every rounded multiply and addition.
high_tree = tree('private_heat_decimal_sparse_core_r2.py')
high_solve = next(n for n in high_tree.body if isinstance(n, ast.FunctionDef) and n.name == '_solve')
loop = next(n for n in high_solve.body if isinstance(n, ast.For) and ast.unparse(n.target) == '(i, row)')
reference_loop = compile(ast.Module(body=[loop], type_ignores=[]), '<selected-high-matrix-loop>', 'exec')
candidate_loop = compile(ast.unparse(loop).replace('D(0)', 'shared_zero'), '<candidate-shared-decimal-zero>', 'exec')
zero_results = []
for code in (reference_loop, candidate_loop):
    calls, checkpoints = [0], []
    def counted_D(value):
        calls[0] += 1
        return D(value)
    with localcontext() as context:
        context.prec, context.rounding = 80, ROUND_HALF_EVEN
        context.clear_flags()
        ns = dict(D=counted_D, delta=D('0.125'), c=[D(2), D(3), D(4)],
                  op=[{1:D('1e99'), 2:D('-1.125')}, {0:D('1e-400'),1:D('0')}, {2:D('7.25')}],
                  dm=[],data=[],indices=[],indptr=[0], cancel=None,
                  P=SimpleNamespace(_checkpoint=lambda c,o,p: checkpoints.append(p)))
        if code is candidate_loop:
            ns['shared_zero'] = counted_D(0)
        exec(code, ns)
        zero_results.append(([[[j, v.as_tuple()] for j,v in row] for row in ns['dm']], ns['data'], ns['indices'],ns['indptr'],
                             tuple(sorted(k.__name__ for k,v in context.flags.items() if v)), checkpoints, calls[0]))
assert zero_results[0][:6] == zero_results[1][:6]
assert (zero_results[0][6], zero_results[1][6]) == (9, 1)

# Observe the source-generated sign*value expression. Value is computed first
# under the same active context, then signed owner strings are built with no
# callback or context switch between those operations.
for name in ('private_heat_decimal_sparse_core_r1.py', 'private_heat_decimal_sparse_core_r2.py'):
    t = tree(name)
    assert any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mult) and isinstance(n.left, ast.Name)
               and n.left.id == 'sign' and isinstance(n.right, ast.Name) and n.right.id == 'value' for n in ast.walk(t))
sign_cases = 0
for emin, emax in ((-999999, 999999), (-4, 4)):
    for literal in ('0', '-0', '1.23456789', '-1.23456789', '1e-40', '-1e-40', '1e-200'):
        for sign in (-1, 1):
            records = []
            for candidate in (False, True):
                with localcontext() as context:
                    context.prec, context.rounding, context.Emin, context.Emax = 80, ROUND_HALF_EVEN, emin, emax
                    context.clear_flags()
                    value = D('1.125')*sum((D(literal),), D(0))
                    # Conservative fallback retains sign multiplication for
                    # nonfinite/subnormal values; shortcut normal/zero only.
                    if candidate and value.is_finite() and not value.is_subnormal():
                        output = value if sign == 1 else value.copy_negate()
                    else:
                        output = sign*value
                    records.append((output.as_tuple(), str(output), tuple(sorted(k.__name__ for k,v in context.flags.items() if v))))
            assert records[0] == records[1]
            sign_cases += 1

# Identity-guarded boundary cache keeps every original read and falls back
# on replacement. Strong raw-value references prohibit object-ID recycling.
assembly_tree = tree('private_heat_interval_assembly_kernel_r1.py')
assembly_ns = dict(Q=Fraction)
q_node = next(n for n in assembly_tree.body if isinstance(n, ast.FunctionDef) and n.name == '_q')
exec(compile(ast.Module(body=[q_node], type_ignores=[]), '<selected-assembly-q>', 'exec'), assembly_ns)
cache, actual_conversions = {}, [0]
def convert(key, raw):
    previous = cache.get(key)
    if previous is not None and previous[0] is raw and type(raw) in (float, int, Fraction, G.mpq):
        return previous[1]
    actual_conversions[0] += 1
    result = assembly_ns['_q'](raw, G)
    if type(raw) in (float, int, Fraction, G.mpq):
        cache[key] = (raw, result)
    return result
raw = float('0.1')
sequence = [('wall', raw)]*4 + [('wall', float('-0.0')), ('wall', float('0.2'))]
for key, raw_value in sequence:
    assert convert(key, raw_value) == assembly_ns['_q'](raw_value, G)
assert actual_conversions[0] == 3
print(json.dumps(dict(status='PASS', source_map_sha256=sha256(selection.read_bytes()).hexdigest(),
                     sources=sources, low_public_audit_cases=low_results, decimal_sign_cases=sign_cases,
                     matrix_zero_constructor_calls=[zero_results[0][6],zero_results[1][6]],
                     guarded_boundary_reference_conversions=len(sequence), guarded_boundary_candidate_conversions=actual_conversions[0],
                     no_runtime_admission_or_performance_claim=True), indent=2))
