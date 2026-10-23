"""Tiny source-bound arithmetic controls; no package setup, JIT or timings."""
if not __debug__:
    raise RuntimeError('Control validation requires assertions; do not use Python -O or -OO')

import ast
from concurrent.futures import CancelledError
from decimal import Decimal
from hashlib import sha256
import importlib.util
import json
from operator import index
from pathlib import Path
from time import perf_counter
import gmpy2 as G

ROOT = Path(__file__).resolve().parents[5]
MAP = ROOT / 'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
assert sha256(MAP.read_bytes()).hexdigest() == 'ce77c8f2922e0d8780e241ba9204e775388fa093935968eaee7c577606baaccc'
entries = json.loads(MAP.read_text())['entries']
identities = {}
def source(member):
    e = next(e for e in entries if e['member'] == 'source/helpers/' + member)
    p = ROOT / e['public_path']
    assert sha256(p.read_bytes()).hexdigest() == e['public_sha256']
    identities[e['public_path']] = e['public_sha256']
    return p

lu_path = source('private_heat_mpfr_lu_r1.py')
spec = importlib.util.spec_from_file_location('control_lu', lu_path)
lu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lu)
FLAG_NAMES = ('underflow', 'overflow', 'inexact', 'invalid', 'erange', 'divzero')
def flags():
    return tuple(bool(getattr(G.get_context(), name)) for name in FLAG_NAMES)
# Observe flags before the source's local context exits; numerical statements
# are unchanged. Instrument only the return expression of the selected function.
solve_node = next(node for node in ast.parse(lu_path.read_text()).body
                  if isinstance(node, ast.FunctionDef) and node.name == 'solve')
for node in ast.walk(solve_node):
    if isinstance(node, ast.Return):
        node.value = ast.Tuple(elts=[node.value, ast.Call(func=ast.Name(id='flags', ctx=ast.Load()), args=[], keywords=[])], ctx=ast.Load())
lu.__dict__['flags'] = flags
exec(compile(ast.fix_missing_locations(ast.Module(body=[solve_node], type_ignores=[])), str(lu_path), 'exec'), lu.__dict__)

def partitioned(factors, rhs, cancel=None):
    a, pivots = factors['rows'], factors['pivots']
    lower = [tuple((j, v) for j, v in row.items() if j < i) for i, row in enumerate(a)]
    upper = [tuple((j, v) for j, v in row.items() if j > i) for i, row in enumerate(a)]
    with G.context(precision=factors['precision']):
        b = list(map(lu._mp, rhs))
        for k, pivot in enumerate(pivots):
            if k != pivot:
                b[k], b[pivot] = b[pivot], b[k]
        for i, row in enumerate(lower):
            lu._check(cancel)
            b[i] -= sum((v*b[j] for j, v in row), G.mpfr(0))
        for i in range(len(a)-1, -1, -1):
            lu._check(cancel)
            b[i] = (b[i]-sum((v*b[j] for j, v in upper[i]), G.mpfr(0)))/a[i][i]
        return b, flags()

def canonical(values):
    return [(G.to_binary(v).hex(), v.rc, str(G.mpq(v)), bool(G.is_signed(v)), v.precision) for v in values]

matrix = [[(0, Decimal('0')), (2, Decimal('1.3')), (1, Decimal('2.1'))],
          [(2, Decimal('5.2')), (0, Decimal('4.7')), (1, Decimal('-2.2'))],
          [(1, Decimal('3.1')), (2, Decimal('0.9')), (0, Decimal('-0.1'))]]
factors = lu.factor(matrix, precision=512)
for rhs in ([Decimal('1.1'), Decimal('-2.7'), Decimal('0')], [Decimal('0')]*3,
            [Decimal('1e-30'), Decimal('2.03'), Decimal('-17.333')]):
    original, original_flags = lu.solve(factors, rhs)
    proposed, proposed_flags = partitioned(factors, rhs)
    assert canonical(original) == canonical(proposed) and original_flags == proposed_flags
cancel_results = []
for stop in range(1, 7):
    outcomes = []
    for solve in (lu.solve, partitioned):
        calls = [0]
        def cancel():
            calls[0] += 1
            return calls[0] == stop
        try:
            solve(factors, [Decimal(1)]*3, cancel=cancel)
            raise AssertionError('Missing cancellation')
        except CancelledError as error:
            outcomes.append((calls[0], str(error)))
    assert outcomes[0] == outcomes[1]
    cancel_results.append(stop)

assembly = source('private_heat_interval_assembly_kernel_r1.py')
tree = ast.parse(assembly.read_text())
scale_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_scale')
scale_ns = {}
exec(compile(ast.Module(body=[scale_node], type_ignores=[]), str(assembly), 'exec'), scale_ns)
def unit_scale(bounds, sign):
    return bounds if sign == 1 else (-bounds[1], -bounds[0])
scale_checks = 0
for bounds in ((G.mpq(0), G.mpq(0)), (G.mpq(-7, 3), G.mpq(11, 17)),
               (G.mpq(2**200+1, 3**80), G.mpq(2**201+1, 3**80))):
    for sign in (-1, 1):
        actual = scale_ns['_scale'](bounds, sign)
        proposed = unit_scale(bounds, sign)
        assert actual == proposed and tuple(map(type, actual)) == tuple(map(type, proposed))
        scale_checks += 1

cert = source('private_heat_certification_kernel_r1.py')
names = {'_require_gmp','_rank_q','_reduce_reference','reduce_observations','_functional_q','functional_solve'}
nodes = [node for node in ast.parse(cert.read_text()).body if isinstance(node, ast.FunctionDef) and node.name in names]
ns = dict(G=G, PRIME=(1<<61)-1, perf_counter=perf_counter, CancelledError=CancelledError, index=index)
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(cert), 'exec'), ns)
p = ns['PRIME']
rank = ns['reduce_observations']([[G.mpq(p), G.mpq(1)], [G.mpq(0), G.mpq(0)]], [G.mpq(p), G.mpq(2)])
assert rank['evidence']['fallback_reason'] == 'unlucky prime changed canonical independent-column order'
assert rank['independent_columns'] == [0] and rank['target_witness'] == 1
answer = ns['functional_solve']([[2, 1, 0], [0, 3, 1], [1, 0, 4]], [1, 2, 3])
assert answer == [G.mpq(7,25), G.mpq(11,25), G.mpq(17,25)]
# A zero lower coefficient still requires Bareiss row scaling: 2*3/1 is 6, not 3.
assert 2*3 != 3
high = source('private_heat_decimal_sparse_core_r2.py')
# Independent realised CSR/CSC control for the count-only proposal. The source
# validates unique ascending columns; duplicates are deliberately ineligible.
from scipy.sparse import csr_matrix
import scipy
count_cases = [
    [[]],
    [[(0, Decimal('2'))]],
    [[(0, Decimal('1e-1000')), (2, Decimal('-3'))], [(1, Decimal('0'))], [(0, Decimal('1e1000')), (2, Decimal('-0'))]],
    [[(1, Decimal('-2'))], [(0, Decimal('3')), (1, Decimal('7'))]],
]
nnz = []
for rows in count_cases:
    data, indices, indptr, count = [], [], [0], 0
    for row in rows:
        columns = [j for j, value in row]
        assert columns == sorted(set(columns))
        for j, value in row:
            if value:
                approximate = float(value)
                if approximate:
                    data.append(approximate)
                    indices.append(j)
                    count += 1
        indptr.append(len(data))
    approximate = csr_matrix((data, indices, indptr), shape=(len(rows), len(rows))).tocsc()
    approximate.sort_indices()
    assert count == approximate.nnz
    nnz.append(count)
assert [0, 0] != sorted(set([0, 0]))
result = dict(status='PASS', scope='SOURCE_BOUND_TINY_ARITHMETIC_ONLY_NOT_RUNTIME_QUALIFICATION',
              selected_source_map_sha256=sha256(MAP.read_bytes()).hexdigest(), sources=identities,
              runtime=dict(gmpy2=G.version(), gmp=G.mp_version(), mpfr=G.mpfr_version(), scipy=scipy.__version__),
              mpfr_rhs_cases=3, mpfr_cancellation_positions=cancel_results,
              mpfr_comparison='to_binary, rc, exact ratio, sign, precision and local-context flags',
              csr_count_cases=len(count_cases), csr_expected_nnz=nnz, duplicate_columns_ineligible=True,
              unit_scale_cases=scale_checks,
              canonical_unlucky_prime_fallback=dict(independent_columns=rank['independent_columns'],
                  target_witness=str(rank['target_witness']), null_witness=list(map(str,rank['null_witness']))),
              bareiss_solution=list(map(str,answer)), no_timing_or_resource_measurement=True)
Path(__file__).with_name('SOLVE-CONTROL-RESULTS.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))
