"""Bounded additional arithmetic controls; no production imports or performance claim."""
if not __debug__:
    raise RuntimeError('Control validation requires assertions; do not use Python -O or -OO')

from pathlib import Path
from concurrent.futures import CancelledError
import ast
import hashlib
import json
import gmpy2 as G

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
MAP = ROOT / 'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
MAP_SHA = 'ce77c8f2922e0d8780e241ba9204e775388fa093935968eaee7c577606baaccc'
NAMES = {'Arithmetic', 'Unresolved', '_require_gmp', 'approximate_inverse', 'solve_enclosure', 'physical_bounds'}
FLAGS = ('inexact', 'underflow', 'overflow', 'invalid', 'divzero', 'erange')
SETTINGS = ('precision', 'real_prec', 'imag_prec', 'round', 'real_round', 'imag_round', 'emax', 'emin',
            'subnormalize', 'trap_underflow', 'trap_overflow', 'trap_inexact', 'trap_invalid',
            'trap_erange', 'trap_divzero', 'allow_complex', 'rational_division')


def source():
    raw = MAP.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MAP_SHA:
        raise ValueError('Changed selected map')
    entry = next(e for e in json.loads(raw)['entries']
                 if e['member'] == 'source/helpers/private_heat_certification_kernel_r1.py')
    data = (ROOT / entry['public_path']).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry['public_sha256']:
        raise ValueError('Changed selected certificate')
    return data.decode(), entry


def definitions(text, candidate=False):
    tree = ast.parse(text)
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in NAMES]
    assert {n.name for n in nodes} == NAMES
    code = '\n\n'.join(ast.get_source_segment(text, n) for n in nodes)
    if candidate:
        substitutions = {
            'rows[j] = [ar.near.div(v, pivot) for v in rows[j]]':
            'rows[j] = rows[j][:j] + [ar.near.div(v, pivot) for v in rows[j][j:]]',
            'rows[i] = [ar.near.sub(x, ar.near.mul(value, y))\n'
            '                           for x, y in zip(rows[i], rows[j], strict=True)]':
            'rows[i] = rows[i][:j] + [ar.near.sub(x, ar.near.mul(value, y))\n'
            '                           for x, y in zip(rows[i][j:], rows[j][j:], strict=True)]',
        }
        for old, new in substitutions.items():
            assert code.count(old) == 1
            code = code.replace(old, new)
    ns = {'G': G, 'CancelledError': CancelledError, '_h3_batch': lambda *a, **kw: None,
          '_h3_plain': lambda ar: False, '_h3_module': lambda: None}
    exec(compile(code, '<selected-extension-control>', 'exec'), ns)
    return ns


def signature(x):
    if type(x) is G.mpfr:
        return (G.to_binary(x).hex(), x.precision, x.rc, x.is_signed())
    if isinstance(x, (tuple, list)):
        return [signature(v) for v in x]
    if isinstance(x, dict):
        return {k: signature(v) for k, v in x.items()}
    return x


def flags(context):
    return {name: getattr(context, name) for name in FLAGS}


class CountedContext:
    def __init__(self, context):
        self.context = context
        self.counts = dict(add=0, sub=0, mul=0, div=0, abs=0)

    def __getattr__(self, name):
        value = getattr(self.context, name)
        if name not in self.counts:
            return value
        def call(*args):
            self.counts[name] += 1
            return value(*args)
        return call


def inverse(ns, values, precision, cancel_at=None):
    ar = ns['Arithmetic'](precision)
    a = [[ar.point(v) for v in row] for row in values]
    ar.near = CountedContext(ar.near)
    trace = []
    def check(phase):
        trace.append(phase)
        if len(trace) == cancel_at:
            raise CancelledError('bounded injected cancellation')
    ar.check = check
    try:
        answer = ('return', signature(ns['approximate_inverse'](a, ar)))
    except Exception as error:
        answer = ('raise', type(error).__name__, str(error))
    return {'answer': answer, 'flags': flags(ar.near), 'trace': trace}, ar.near.counts


def one_sided_point(ar, q, unresolved):
    # Only the exact GMP rational / matched factory contexts are proposed.
    options = dict(precision=ar.down.precision, trap_underflow=True, trap_overflow=True,
                   trap_invalid=True, trap_divzero=True, trap_erange=True)
    expected = (G.context(**options, round=G.RoundDown), G.context(**options, round=G.RoundUp))
    context_match = all(tuple(getattr(c, s) for s in SETTINGS) == tuple(getattr(e, s) for s in SETTINGS)
                        for c, e in zip((ar.down, ar.up), expected, strict=True))
    if type(q) is not G.mpq or not context_match:
        return ar.point(q), 2
    ar.check('directed-input')
    with ar.down:
        lo = G.mpfr(q)
    if lo.rc == 0 and G.is_finite(lo):
        return (lo, lo), 1
    with ar.up:
        hi = G.mpfr(q)
    if not G.is_finite(lo) or not G.is_finite(hi):
        raise unresolved('Nonfinite interval input')
    return (lo, hi), 2


def point_run(ns, q, precision, candidate, cancel=False, altered=None):
    ar = ns['Arithmetic'](precision)
    if altered == 'precision':
        ar.up.precision = 8
    elif altered == 'range':
        ar.up.emax = 8
    trace = []
    def check(phase):
        trace.append(phase)
        if cancel:
            raise CancelledError('bounded point cancellation')
    ar.check = check
    try:
        value, calls = one_sided_point(ar, q, ns['Unresolved']) if candidate else (ar.point(q), 2)
        answer = ('return', signature(value))
    except Exception as error:
        answer, calls = ('raise', type(error).__name__, str(error)), None
    return {'answer': answer, 'down_flags': flags(ar.down), 'up_flags': flags(ar.up), 'trace': trace}, calls


def physical_run(ns, rows, precision, reuse, stale=False):
    n, m = len(rows[0]), len(rows)
    rhs = [G.mpq(i+1, 7) for i in range(n)]
    initial = []
    ar_type = ns['Arithmetic']
    original = ar_type.point
    def capture(self, q):
        value = original(self, q)
        initial.append(value)
        return value
    ar_type.point = capture
    try:
        dual, ar, proof = ns['solve_enclosure'](rows, rhs, precision=precision)
    finally:
        ar_type.point = original
    snapshot = tuple(tuple(row) for row in rows)
    physical_rows = [list(row) for row in rows]
    if stale:
        physical_rows[0][0] += G.mpq(1, 9)
    eligible = reuse and tuple(tuple(row) for row in physical_rows) == snapshot
    cached = iter(initial[:m*n])
    remaining = m*n
    trace, conversions = [], []
    def check(phase):
        trace.append(phase)
    def point(q):
        nonlocal remaining
        if eligible and remaining:
            remaining -= 1
            ar.check('directed-input')
            return next(cached)
        conversions.append(1)
        return original(ar, q)
    ar.check, ar.point = check, point
    keys = [('cell', i) for i in range(m)]
    answer = ns['physical_bounds'](physical_rows, dual, keys, keys[:2], G.mpq(1, 7),
                                   [G.mpq(1) for _ in keys], ar)
    return {'bounds': signature(answer), 'proof': signature(proof), 'trace': trace,
            'flags': [flags(c) for c in (ar.down, ar.up, ar.near)]}, len(conversions), eligible


def controls():
    text, entry = source()
    ref, cand = definitions(text), definitions(text, True)
    cases = []
    matrices = [
        [[G.mpq((i == j)) + G.mpq(1, i+j+2) for j in range(n)] for i in range(n)]
        for n in (2, 3, 6, 20)
    ]
    matrices += [[[G.mpq(0), G.mpq(-2), G.mpq(0)],
                  [G.mpq(0), G.mpq(0), G.mpq(3)],
                  [G.mpq(-1), G.mpq(0), G.mpq(0)]]]
    for precision in (8, 53, 80, 320):
        for number, matrix in enumerate(matrices):
            r, rc = inverse(ref, matrix, precision)
            c, cc = inverse(cand, matrix, precision)
            assert r == c, (precision, number)
            assert r['answer'][0] == 'return'
            n = len(matrix)
            assert rc['div']-cc['div'] == n*(n-1)//2
            assert rc['mul']-cc['mul'] == n*(n-1)*(n-1)//2
            assert rc['sub']-cc['sub'] == n*(n-1)*(n-1)//2
            cases.append({'precision': precision, 'dimension': n, 'matrix_kind': number,
                          'signature_flags_trace_equal': True, 'reference_ops': rc, 'candidate_ops': cc})
    refused = []
    for matrix, cancel in [([[G.mpq(0)]], None), (matrices[1], 1), (matrices[1], 2),
                           (matrices[1], 7), (matrices[2], 20)]:
        r, _ = inverse(ref, matrix, 53, cancel)
        c, _ = inverse(cand, matrix, 53, cancel)
        assert r == c and r['answer'][0] == 'raise'
        refused.append({'cancel_at': cancel, 'same_exception_flags_trace': True, 'exception': r['answer'][1]})
    point_cases = []
    rationals = [G.mpq(0), G.mpq(1), G.mpq(-1), G.mpq(3, 8), G.mpq(-11, 32),
                 G.mpq(1, 3), G.mpq(-2, 7), G.mpq(2)**1000, G.mpq(2)**-1000,
                 G.mpq(2**400+1, 2**401), G.mpq(-(2**800+3), 2**700)]
    for precision in (8, 53, 80, 320):
        for index, q in enumerate(rationals):
            r, _ = point_run(ref, q, precision, False)
            c, count = point_run(ref, q, precision, True)
            assert r == c, (precision, index)
            point_cases.append({'precision': precision, 'rational_case': index, 'signature_flags_trace_equal': True,
                                'reference_conversions': 2, 'candidate_conversions': count})
    r, _ = point_run(ref, G.mpq(1), 53, False, True)
    c, _ = point_run(ref, G.mpq(1), 53, True, True)
    assert r == c and r['answer'][0] == 'raise'
    fallbacks = []
    for q, altered in [(G.mpq(1, 3), 'precision'), (G.mpq(2)**20, 'range'), (-0.0, None)]:
        r, _ = point_run(ref, q, 53, False, altered=altered)
        c, count = point_run(ref, q, 53, True, altered=altered)
        assert r == c and (count == 2 or c['answer'][0] == 'raise')
        fallbacks.append({'altered_context': altered, 'same_reference_outcome': True})
    physical = []
    for n in (2, 3):
        rows = [[G.mpq(i == j) for j in range(n)] for i in range(n)]
        rows += [[G.mpq(i+j+1, 2**(i+j+2)) for j in range(n)] for i in range(3)]
        for precision in (53, 320):
            for stale in (False, True):
                r, rc, _ = physical_run(ref, rows, precision, False, stale)
                c, cc, eligible = physical_run(ref, rows, precision, True, stale)
                assert r == c and rc-cc == (n*len(rows) if eligible else 0)
                physical.append({'columns': n, 'rows': len(rows), 'precision': precision, 'changed_matrix': stale,
                                 'reference_point_calls': rc, 'candidate_point_calls': cc,
                                 'signature_flags_trace_equal': True, 'reuse_eligible': eligible})
    return {'status': 'PASS', 'source_map_sha256': MAP_SHA, 'selected_source': entry,
            'gmpy2': G.version(), 'mpfr': G.mpfr_version(), 'inverse_cases': cases,
            'inverse_refusal_cancellation': refused, 'point_cases': point_cases,
            'point_cancellation_equal': True,
            'point_fallbacks': fallbacks, 'physical_matrix_reuse': physical,
            'limits': 'Source-extracted arithmetic feasibility only; no production source edit, native/worker import, resource proof or timing'}


if __name__ == '__main__':
    result = controls()
    result['control_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (HERE / 'EXTENSION-CERTIFICATE-RESULTS.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps({'status': result['status'], 'inverse_cases': len(result['inverse_cases']),
                      'point_cases': len(result['point_cases']), 'refusal_cases': len(result['inverse_refusal_cancellation'])+1}))
