"""Bounded source-bound successor fixtures. No selected source is modified.

Default correctness only. Benchmark execution requires separate queue authority.
"""
from __future__ import annotations

import sys
if not __debug__:
    raise RuntimeError('Correctness validation requires assertions; -O/-OO refused')

import argparse
import ast
from concurrent.futures import CancelledError
from contextlib import ExitStack
from dataclasses import dataclass
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import gc
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import types
import weakref

import gmpy2 as G

HERE = Path(__file__).resolve().parent
_location_parser = argparse.ArgumentParser(add_help=False)
_location_parser.add_argument('--repo', type=Path, required=True)
_location_args, _ = _location_parser.parse_known_args()
REPO = _location_args.repo.resolve()
HEAT = REPO / 'tectonics/optimisation/workbench/plan40/heat'
MAP = REPO / 'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
MAP_SHA = '1d1e2c79fe7825e276e2a33f2d5c18fe3157da8ef4b41ab0c3c347bca9295fcf'
FLAGS = ('inexact', 'underflow', 'overflow', 'invalid', 'divzero', 'erange')
SETTINGS = ('precision', 'real_prec', 'imag_prec', 'round', 'real_round', 'imag_round', 'emax', 'emin', 'subnormalize', 'trap_underflow', 'trap_overflow', 'trap_inexact', 'trap_invalid', 'trap_erange', 'trap_divzero', 'allow_complex', 'rational_division')
SOURCES = {}
raw = MAP.read_bytes()
if hashlib.sha256(raw).hexdigest() != MAP_SHA:
    raise ValueError('Selected source map changed')
ENTRIES = json.loads(raw)['entries']


def source(name):
    matches = [e for e in ENTRIES if Path(e['member']).name == name]
    if len(matches) != 1:
        raise ValueError(('Ambiguous source', name, len(matches)))
    e = matches[0]
    data = (REPO / e['public_path']).read_bytes()
    if hashlib.sha256(data).hexdigest() != e['public_sha256']:
        raise ValueError('Selected source changed: ' + name)
    SOURCES[name] = e
    return data.decode('utf-8')


def extract(text, names):
    nodes = [n for n in ast.parse(text).body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    if {n.name for n in nodes} != set(names):
        raise ValueError('Required definitions missing')
    return '\n\n'.join(ast.get_source_segment(text, n) for n in nodes)


def replace(code, old, new):
    if code.count(old) != 1:
        raise ValueError('Source transform not unique: ' + old[:80])
    return code.replace(old, new)


def sig(x):
    if type(x) is G.mpfr:
        return ('mpfr', G.to_binary(x).hex(), x.precision, x.rc, x.is_signed())
    if type(x) is G.mpq:
        return ('mpq', str(x))
    if type(x) is Decimal:
        return ('Decimal', str(x), tuple(x.as_tuple()))
    if isinstance(x, dict):
        return [(repr(k), sig(v)) for k, v in x.items()]
    if isinstance(x, (tuple, list)):
        return [sig(v) for v in x]
    return x


def flags(ar):
    return [[getattr(c, f) for f in FLAGS] for c in (ar.down, ar.up, ar.near)]


def settings(ar):
    return tuple(tuple(getattr(c, f) for f in SETTINGS) for c in (ar.down, ar.up, ar.near))


def expected(ar):
    p = ar.down.precision
    options = dict(precision=p, trap_underflow=True, trap_overflow=True, trap_invalid=True, trap_divzero=True, trap_erange=True)
    return settings(types.SimpleNamespace(**{k: G.context(**options, round=r) for k, r in (('down', G.RoundDown), ('up', G.RoundUp), ('near', G.RoundToNearest))}))


class SourceFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Only selected helper imports; every loaded byte is checked against the map."""
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('private_heat_', 'atlas_tectonics.')) and any(Path(e['member']).name == fullname.rsplit('.',1)[-1]+'.py' for e in ENTRIES):
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        basename = module.__name__.rsplit('.',1)[-1]+'.py'
        text = source(basename)
        module.__file__ = str(REPO / SOURCES[basename]['public_path'])
        exec(compile(text, module.__file__, 'exec'), module.__dict__)


def resources():
    # Actual source-defined WorkBudget and escaping-frame custody; no substitutes.
    pkg = types.ModuleType('atlas_tectonics')
    pkg.__path__ = []
    sys.modules['atlas_tectonics'] = pkg
    resource = types.ModuleType('atlas_tectonics.resources')
    sys.modules[resource.__name__] = resource
    exec(compile(source('resources.py'), '<selected-resources>', 'exec'), resource.__dict__)
    spatial = types.ModuleType('atlas_tectonics.integration_spatial_transport')
    spatial.weakref = weakref
    sys.modules[spatial.__name__] = spatial
    exec(extract(source('integration_spatial_transport.py'), {'_EscapingWorkspace', '_preserve_workspace'}), spatial.__dict__)
    sys.meta_path.insert(0, SourceFinder())
    import private_heat_gmp_resources_r1 as R
    import private_heat_certification_resources_r1 as inventory
    import private_heat_decimal_sparse_core_r1 as P
    import private_heat_rational_decimal_kernel_r1 as decimal_kernel
    import private_heat_low_ledger_inventory_r1 as L
    return R, inventory, P, decimal_kernel, L


R, INVENTORY, P, DECIMAL, L = resources()
WorkBudget = R.WorkBudget


class OptionalOwner:
    """Explicit conservative fixture inventory; failed admission uses reference.

    This accounts buffers/metadata; it is not an allocator/RSS bound.
    """
    def __init__(self, budget, count, category):
        self.live = False
        self.work = None
        try:
            self.work = R.OwnedWorkspace(budget, count, category=category)
            self.work.__enter__()
            self.live = True
        except sys.modules['atlas_tectonics.resources'].MemoryLimitError:
            self.work = None

    def close(self):
        if self.live:
            self.live = False
            self.work.__exit__(None, None, None)
            self.work = None

    def fail(self, error):
        """Escaping frames may still hold arrays; preserve their existing lease."""
        if self.live:
            spatial = sys.modules['atlas_tectonics.integration_spatial_transport']
            # The failed source frame retains this owner even if only its
            # traceback (not the exception object) survives.
            self.failure_owner = spatial._preserve_workspace(error, self.work.stack)
            self.work.finished = True
            self.work = None
            self.live = False


class PreparedRHS(OptionalOwner):
    def __init__(self, module, rows, down, up, budget):
        n, length = len(rows), len(rows[0]) if rows else 0
        # Endpoint references, address/class arrays, list/tuple generations; no output buffers.
        count = 65536 + 1024*(4*n*length+8*n+64)
        super().__init__(budget, count, 'C5-prepared-rhs')
        try:
            self.module, self.rows, self.keep = module, None, []
            self.lo = self.hi = self.cls = None
            self.contexts = (down, up)
            self.settings = tuple(module._settings(c) for c in self.contexts)
            if not self.live:
                return
            if not module.contexts_ok(down, up) or not n or not length:
                raise module.Unavailable('unreviewed prepared RHS')
            self.rows = tuple(tuple(row) for row in rows)
            self.lo, self.hi = module._addresses(self.rows, length, self.keep)
            saved = module.mpfr_flags_save()
            try:
                self.cls = module._compiled(module._classes, self.lo, self.hi)
            finally:
                module.mpfr_flags_restore(saved, module.FLAGS_ALL)
        except module.Unavailable:
            self.close()
            raise
        except BaseException as error:
            # Construction has not yet registered this handle with owned_solve.
            # Failed helper frames can still retain allocated buffers and rows.
            self.fail(error)
            self.close()
            raise

    def require(self, module, rows, down, up):
        if (not self.live or self.module is not module or self.rows is None
                or down is not self.contexts[0] or up is not self.contexts[1]
                or tuple(module._settings(c) for c in (down, up)) != self.settings
                or len(rows) != len(self.rows)
                or any(len(a) != len(b) or any(x is not y for x, y in zip(a, b, strict=True))
                       for a, b in zip(rows, self.rows, strict=True))):
            raise module.Unavailable('prepared RHS custody/context mismatch')

    def close(self):
        self.rows = self.lo = self.hi = self.cls = None
        self.keep = []
        super().close()


def native_module(zero_candidate=False):
    # Execute unchanged selected native module, including its reviewed-version/layout/self-test gates.
    module = types.ModuleType('plan40b_native_reference')
    text = source('private_heat_compiled_dot_r1.py')
    if zero_candidate:
        text = replace(text, "mpfr_mul = _bind('mpfr_mul', _I, [_P, _P, _P, _I])",
                       "mpfr_zero_p = _bind('mpfr_zero_p', _I, [_P])\n    mpfr_number_p = _bind('mpfr_number_p', _I, [_P])\n    mpfr_signbit = _bind('mpfr_signbit', _I, [_P])\n    mpfr_set_zero = _bind('mpfr_set_zero', None, [_P, _I])\n    mpfr_mul = _bind('mpfr_mul', _I, [_P, _P, _P, _I])")
        text = replace(text, 'def _product(tmp, ca, cb, a0, a1, b0, b1):\n    if ca == 0 or cb == 0:',
                       "def _product(tmp, ca, cb, a0, a1, b0, b1):\n    if (mpfr_number_p(a0) and mpfr_number_p(a1) and mpfr_number_p(b0) and mpfr_number_p(b1)\n            and ((mpfr_zero_p(a0) and mpfr_zero_p(a1)) or (mpfr_zero_p(b0) and mpfr_zero_p(b1)))):\n        sign = -1 if bool(mpfr_signbit(a0)) != bool(mpfr_signbit(b0)) else 1\n        mpfr_set_zero(tmp[0], sign)\n        mpfr_set_zero(tmp[4], sign)\n        return tmp[0], tmp[4]\n    if ca == 0 or cb == 0:")
    module.__file__ = str(REPO / SOURCES['private_heat_compiled_dot_r1.py']['public_path'])
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    module.executed_source_sha256 = hashlib.sha256(text.encode()).hexdigest()
    code = extract(text, {'pair_dots'})
    code = replace(code, 'def pair_dots(x_rows, y_rows, down, up, *, gram=False, check=None):',
                   'def prepared_pair_dots(x_rows, y_rows, down, up, *, gram=False, check=None, prepared=None):')
    code = replace(code, 'y_lo, y_hi = (x_lo, x_hi) if gram else _addresses(y_rows, length, keep)',
                   "if prepared is None:\n        y_lo, y_hi = (x_lo, x_hi) if gram else _addresses(y_rows, length, keep)\n    else:\n        if gram:\n            raise Unavailable('prepared RHS is not a Gram input')\n        prepared.require(_module_self, y_rows, down, up)\n        y_lo, y_hi = prepared.lo, prepared.hi")
    code = replace(code, 'y_cls = x_cls if gram else _compiled(_classes, y_lo, y_hi)',
                   'y_cls = prepared.cls if prepared is not None else (x_cls if gram else _compiled(_classes, y_lo, y_hi))')
    module._module_self = module
    exec(compile(code, '<C5-prepared-row-successor>', 'exec'), module.__dict__)
    module.candidate_source_sha256 = hashlib.sha256(code.encode()).hexdigest()
    return module


NATIVE = None
ZERO_NATIVE = None
NATIVE_ERROR = None


def kernel(candidate=None, native=False, budget=None, gram_owner=None, matrix_owner=None):
    text = source('private_heat_certification_kernel_r1.py')
    names = {'_require_gmp', 'Unresolved', 'Arithmetic', 'approximate_inverse', 'solve_enclosure', 'physical_bounds', '_h3_plain', '_h3_batch'}
    code = extract(text, names)
    if candidate == 'C15':
        code = replace(code, 'rows[j] = [ar.near.div(v, pivot) for v in rows[j]]',
                       'rows[j] = rows[j][:j] + [ar.near.div(v, pivot) for v in rows[j][j:]]')
        code = replace(code, 'rows[i] = [ar.near.sub(x, ar.near.mul(value, y))\n                           for x, y in zip(rows[i], rows[j], strict=True)]',
                       'rows[i] = rows[i][:j] + [ar.near.sub(x, ar.near.mul(value, y))\n                           for x, y in zip(rows[i][j:], rows[j][j:], strict=True)]')
    if candidate == 'C4':
        code = replace(code, 'xhat = []\n    for row in r:', 'xhat = []\n    midpoint_cache = {}\n    for row in r:')
        code = replace(code, 'for v, bound in zip(row, b, strict=True):\n            value = ar.near.add(value, ar.near.mul(v, ar.midpoint(bound)))',
                       'for j, (v, bound) in enumerate(zip(row, b, strict=True)):\n            if j not in midpoint_cache:\n                midpoint_cache[j] = ar.midpoint(bound)\n            value = ar.near.add(value, ar.near.mul(v, midpoint_cache[j]))')
        code = replace(code, 'dots = _h3_batch(ar, a, [[(x, x) for x in xhat]])', 'xhat_intervals = [(x, x) for x in xhat]\n    dots = _h3_batch(ar, a, [xhat_intervals])')
        code = replace(code, 'ar.dot(row, [(x, x) for x in xhat])', 'ar.dot(row, xhat_intervals)')
    if candidate == 'C11':
        old = "a = _h3_batch(ar, columns, columns, gram=True)\n    if a is None:\n        a = [[ar.dot(x, y) for y in columns] for x in columns]\n    else:\n        ar.check('interval-add')"
        code = replace(code, old, 'a = _gram_owner.compute(ar, columns, matrix, _h3_batch, _native_enabled)')
    if candidate == 'C16':
        code = replace(code, 'm = [[ar.point(q) for q in row] for row in matrix]',
                       'm = [[ar.point(q) for q in row] for row in matrix]\n    _matrix_owner.capture(ar, matrix, m)')
        code = replace(code, 'rows = [[ar.point(q) for q in row] for row in matrix]',
                       'rows = [_matrix_owner.row(ar, matrix, i, row) for i, row in enumerate(matrix)]')
        code = replace(code, 'result = {key: ar.dot([ar.point(q) for q in row], dual)\n                  for key, row in zip(keys, matrix, strict=True)}',
                       'result = {key: ar.dot(_matrix_owner.row(ar, matrix, i, row), dual)\n                  for i, (key, row) in enumerate(zip(keys, matrix, strict=True))}')
    ns = dict(G=G, CancelledError=CancelledError, _h3_module=lambda: (ZERO_NATIVE if candidate=='C3' else NATIVE) if native else None,
              _gram_owner=gram_owner, _native_enabled=native, _matrix_owner=matrix_owner)
    exec(compile(code, '<selected-source-successor-'+str(candidate)+'>', 'exec'), ns)
    ns['_variant_sha256'] = hashlib.sha256(code.encode()).hexdigest()
    ar_type = ns['Arithmetic']
    original_point, original_dot = ar_type.point, ar_type.dot
    if candidate == 'C17':
        def point(self, q):
            if type(self) is not ar_type or type(q) is not G.mpq or settings(self) != expected(self):
                return original_point(self, q)
            self.check('directed-input')
            with self.down:
                lo = G.mpfr(q)
            if lo.rc == 0 and G.is_finite(lo):
                return lo, lo
            with self.up:
                hi = G.mpfr(q)
            if not G.is_finite(lo) or not G.is_finite(hi):
                raise ns['Unresolved']('Nonfinite interval input')
            return lo, hi
        ar_type.point = point
    if candidate == 'C3':
        def dot(self, a, b):
            if (type(self) is not ar_type or any(k in self.__dict__ for k in ('mul', 'add'))
                    or settings(self) != expected(self)):
                return original_dot(self, a, b)
            lo = hi = self.zero
            for x, y in zip(a, b, strict=True):
                eligible = (type(x) is tuple and type(y) is tuple and len(x) == len(y) == 2
                            and all(type(v) is G.mpfr and G.is_finite(v) for v in (*x, *y))
                            and (all(G.is_zero(v) for v in x) or all(G.is_zero(v) for v in y)))
                if eligible:
                    self.check('interval-product')
                    product = G.mpfr('-0.0' if x[0].is_signed() != y[0].is_signed() else '0.0', self.down.precision)
                    lower = upper = product
                else:
                    lower, upper = self.mul(x, y)
                self.check('interval-add')
                lo, hi = self.down.add(lo, lower), self.up.add(hi, upper)
            return lo, hi
        ar_type.dot = dot
    if candidate == 'C5':
        ordinary = ns['_h3_batch']
        handles = []
        counts = {'created': 0, 'borrowed': 0, 'fallback': 0, 'closed': 0}
        def batch(ar, xs, ys, gram=False):
            # Defect is the only nx=1, ny=rank batch; rank>=2 fixtures.
            if not native or gram or len(xs) != 1 or len(ys) < 2 or not ns['_h3_plain'](ar):
                return ordinary(ar, xs, ys, gram)
            ar.check('interval-product')
            try:
                handle = next((h for identity, h in handles if identity is ys), None)
                if handle is None:
                    handle = PreparedRHS(NATIVE, ys, ar.down, ar.up, budget)
                    if not handle.live:
                        counts['fallback'] += 1
                        # Already performed the entry check; preserve ordinary native row call.
                        return NATIVE.pair_dots(xs, ys, ar.down, ar.up, check=lambda: ar.check('interval-product'))
                    handles.append((ys, handle))
                    counts['created'] += 1
                counts['borrowed'] += 1
                return NATIVE.prepared_pair_dots(xs, ys, ar.down, ar.up, prepared=handle, check=lambda: ar.check('interval-product'))
            except NATIVE.Unavailable:
                counts['fallback'] += 1
                return None
        ns['_h3_batch'] = batch
        solve = ns['solve_enclosure']
        def owned_solve(*args, **kwargs):
            try:
                answer = solve(*args, **kwargs)
            except BaseException as error:
                while handles:
                    _, h = handles.pop()
                    h.fail(error)
                    h.close()
                    counts['closed'] += 1
                raise
            else:
                while handles:
                    _, h = handles.pop()
                    h.close()
                    counts['closed'] += 1
                return answer
        ns['solve_enclosure'] = owned_solve
        ns['_handle_counts'] = counts
    if candidate == 'C4':
        solve = ns['solve_enclosure']
        reference_code = replace(extract(text, {'solve_enclosure'}), 'def solve_enclosure(', 'def reference_solve_enclosure(')
        exec(compile(reference_code, '<C4-unavailable-storage-reference>', 'exec'), ns)
        def funded_solve(matrix, rhs, **kwargs):
            extra = OptionalOwner(budget, 1024*(6*len(rhs)+64), 'C4-midpoint-and-residual-aliases')
            if not extra.live:
                return ns['reference_solve_enclosure'](matrix, rhs, **kwargs)
            try:
                answer = solve(matrix, rhs, **kwargs)
            except BaseException as error:
                extra.fail(error)
                raise
            else:
                extra.close()
                return answer
        ns['solve_enclosure'] = funded_solve
    return ns


class MatrixOwner:
    """Attempt-local aliases funded inside unchanged full interval inventory."""
    def __init__(self):
        self.live = True
        self.rows = self.original = self.ar = self.context = None
        self.hits = self.misses = 0

    def capture(self, ar, matrix, rows):
        # Immutable exact caller data only. No new scalar endpoints or copied matrix.
        if self.live and type(matrix) is tuple and all(type(r) is tuple and all(type(q) is G.mpq for q in r) for r in matrix):
            self.original, self.rows, self.ar, self.context = matrix, rows, ar, settings(ar)

    def row(self, ar, matrix, i, row):
        if self.live and self.ar is ar and self.original is matrix and settings(ar) == self.context:
            for _ in row:
                ar.check('directed-input')
            self.hits += len(row)
            return self.rows[i]
        self.misses += len(row)
        return [ar.point(q) for q in row]

    def close(self):
        self.rows = self.original = self.ar = self.context = None
        self.live = False


class GramOwner:
    """One nominated-precision completed Gram, optional charged custody.

    Native prefix continuation is deliberately unavailable: native uses complete
    source replay. The Python fold continues the exact stored rounded endpoints.
    """
    def __init__(self, budget, binding, precision):
        self.budget, self.binding, self.precision = budget, binding, precision
        self.owner = None
        self.saved = None
        self.live = True
        self.hits = self.fallbacks = self.replays = 0

    def compute(self, ar, columns, matrix, batch, native):
        n, m = len(columns), len(matrix)
        context = settings(ar)
        old = self.saved
        # Fund optional metadata before collecting it. Old and replacement coexist.
        successor = None
        if self.live and ar.down.precision == self.precision and type(matrix) is tuple:
            count = 65536 + 1024*(30*n*n+4*m*n+128) + 2*n*n*(256+8*((self.precision+63)//64+2))
            successor = OptionalOwner(self.budget, count, 'C11-completed-gram')
        records = []
        eligible = (self.live and not native and old is not None and ar.down.precision == self.precision
                    and context == old['context'] and self.binding == old['binding']
                    and type(matrix) is tuple and matrix[:old['m']] == old['matrix']
                    and m > old['m'] and n == old['n'])
        if not native and not eligible and (successor is None or not successor.live):
            self.fallbacks += 1
            return [[ar.dot(x,y) for y in columns] for x in columns]
        try:
            if native:
                self.replays += 1
                a = batch(ar, columns, columns, gram=True)
                if a is not None:
                    ar.check('interval-add')
                else:
                    a = [[ar.dot(x, y) for y in columns] for x in columns]
                # Native does not export per-check Python flags. Do not cache it.
                if successor is not None:
                    successor.close()
                    successor = None
            else:
                if eligible:
                    self.hits += 1
                else:
                    self.fallbacks += 1
                a = []
                for i, x in enumerate(columns):
                    row = []
                    for j, y in enumerate(columns):
                        first_true = [None]*18
                        checkpoint = 0
                        original_check = ar.check
                        def capture(phase):
                            nonlocal checkpoint
                            if successor is not None and successor.live:
                                flat = [v for fs in flags(ar) for v in fs]
                                for k,v in enumerate(flat):
                                    if v and first_true[k] is None:
                                        first_true[k] = checkpoint
                            checkpoint += 1
                            original_check(phase)
                        ar.check = capture
                        try:
                            if eligible:
                                value = old['a'][i][j]
                                history = old['records'][i*n+j]
                                for t in range(2*old['m']+1):
                                    for k, when in enumerate(history):
                                        if when is not None and when <= t:
                                            setattr((ar.down,ar.up,ar.near)[k//6],FLAGS[k%6],True)
                                    if t < 2*old['m']:
                                        ar.check('interval-product' if t%2==0 else 'interval-add')
                                for left,right in zip(x[old['m']:],y[old['m']:],strict=True):
                                    value=ar.add(value,ar.mul(left,right))
                            else:
                                value=ar.dot(x,y)
                            # State after the last add also matters at cancellation in next dot.
                            if successor is not None and successor.live:
                                for k,v in enumerate(v for fs in flags(ar) for v in fs):
                                    if v and first_true[k] is None:
                                        first_true[k]=checkpoint
                                records.append(first_true)
                        finally:
                            ar.check=original_check
                        row.append(value)
                    a.append(row)
            if successor is not None and successor.live:
                saved = dict(a=a,matrix=matrix,context=context,binding=self.binding,m=m,n=n,records=records)
                previous = self.owner
                self.saved,self.owner=saved,successor
                if previous is not None:
                    previous.close()
        except BaseException as error:
            if successor is not None:
                successor.fail(error)
            raise
        return a

    def close(self):
        self.saved = None
        if self.owner is not None:
            self.owner.close()
            self.owner = None
        self.live = False


def matrix(n, extra=2):
    return tuple(tuple(G.mpq(int(i == j)) for j in range(n)) for i in range(n)) + tuple(tuple(G.mpq((i+j)%3-1, 2**(i+j+3)) for j in range(n)) for i in range(extra))


def solve_case(ns, rows, rhs, precision=80, cancel_at=None, physical=False):
    ar_type = ns['Arithmetic']
    original_check, original_init, original_point = ar_type.check, ar_type.__init__, ar_type.point
    trace, created = [], []
    calls = {'point': 0}
    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self)
    def check(self, phase):
        trace.append(phase)
        if len(trace) == cancel_at:
            raise CancelledError('fixture cancellation at '+phase)
        return original_check(self, phase)
    def point(self, q):
        calls['point'] += 1
        return original_point(self, q)
    ar_type.__init__, ar_type.check, ar_type.point = init, check, point
    try:
        try:
            dual, ar, proof = ns['solve_enclosure'](rows, rhs, precision=precision)
            output = [dual, proof]
            if physical:
                keys = [('cell', i) for i in range(len(rows))]
                output.append(ns['physical_bounds'](rows, dual, keys, keys[:2], G.mpq(1, 8), [G.mpq(1)]*len(rows), ar))
            outcome = ('return', sig(output))
        except Exception as error:
            outcome = ('raise', type(error).__name__, str(error))
        gc.collect()
        return dict(outcome=outcome, trace=trace, flags=[flags(a) for a in created]), calls
    finally:
        ar_type.__init__, ar_type.check, ar_type.point = original_init, original_check, original_point


def compile_attempt(ns, owner=None):
    text = source('private_heat_certification_kernel_r3.py')
    code = extract(text, {'_round_bounds', '_export_plan', '_attempt'})
    if owner is not None:
        # Attempt drop positions precede BOTH refusal close and successful export shrink.
        code = replace(code, 'dual = ar = proof = bounds = rounded = result = export = None\n            work.__exit__',
                       'dual = ar = proof = bounds = rounded = result = export = None\n            _matrix_owner.close()\n            work.__exit__')
        code = replace(code, 'dual = ar = proof = bounds = rounded = None\n        retained',
                       'dual = ar = proof = bounds = rounded = None\n        _matrix_owner.close()\n        retained')
        code = replace(code, 'except BaseException:\n        work.__exit__',
                       'except BaseException:\n        _matrix_owner.close()\n        work.__exit__')
    env = dict(K=types.SimpleNamespace(**ns), INVENTORY=INVENTORY, P=P, DECIMAL=DECIMAL, L=L,
               G=G, Unresolved=ns['Unresolved'], localcontext=localcontext, ROUND_HALF_EVEN=ROUND_HALF_EVEN,
               sys=sys, _matrix_owner=owner)
    exec(compile(code, '<selected-r3-attempt-successor>', 'exec'), env)
    return env


def attempt(ns, rows, rhs, precision, owner=None, cancel_at=None, budget_bytes=256*1024*1024, physical=None, budget_override=None):
    env=compile_attempt(ns,owner)
    budget = budget_override if budget_override is not None else WorkBudget(budget_bytes)
    checks = 0
    def cancel():
        nonlocal checks
        checks += 1
        return checks == cancel_at
    keys = [('cell', i) for i in range(len(rows))]
    evidence, audit = [], {}
    held_error = None
    try:
        result, reason = env['_attempt'](rows, rhs, keys, keys[:2], G.mpq(0), [G.mpq(1)]*len(rows), {} if physical is None else physical,
            precision=precision, largest_owned_bytes=max(sys.getsizeof(v) for row in rows for v in row),
            budget=budget, cancelled=cancel, audit=audit, resource_evidence=evidence)
        if result is None:
            outcome = ('refused', reason)
            held = budget.reserved_bytes
        else:
            outcome = ('return', sig(result.value))
            held = budget.reserved_bytes
            result.close()
            try:
                result.value
                raise AssertionError('borrow after close accepted')
            except RuntimeError:
                pass
    except Exception as error:
        outcome = ('raise', type(error).__name__, str(error))
        held_error = error
        held = budget.reserved_bytes
    failure_held = held_error is not None and held > 0
    held_error = None
    gc.collect()
    return dict(outcome=outcome, checks=checks, resource_evidence=evidence, held_bytes=held,
                after_drop_bytes=budget.reserved_bytes, failure_frame_was_funded=failure_held,
                peak_accounted_bytes=budget.peak_reserved_bytes, owner_closed=None if owner is None else not owner.live,
                owner_hits=None if owner is None else owner.hits), budget


def reuse_evidence():
    out = []
    for script_name, result_name in (('examine_controls.py', 'CONTROL-RESULTS.json'), ('extension_certificate_controls.py', 'EXTENSION-CERTIFICATE-RESULTS.json')):
        script, result = HEAT/script_name, HEAT/result_name
        raw_result = result.read_bytes()
        data = json.loads(raw_result)
        if data['status'] != 'PASS' or data['source_map_sha256'] != MAP_SHA:
            raise ValueError('Retained controls not applicable')
        out.append(dict(script=script_name, script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(), result=result_name,
                        result_sha256=hashlib.sha256(raw_result).hexdigest(), status='REUSED_NOT_RERUN', scope=data.get('scope', data.get('limits'))))
    return out


def basic_integration(candidate):
    cases = []
    for native in (False, True):
        if native and NATIVE is None:
            continue
        for n, precision in ((2, 80), (4, 320)):
            rows = matrix(n)
            rhs = tuple(G.mpq(i+1, 8) for i in range(n))
            ref = kernel(native=native)
            budget = WorkBudget(16*1024*1024)
            cand = kernel(candidate, native=native, budget=budget)
            a, ac = solve_case(ref, rows, rhs, precision, physical=True)
            b, bc = solve_case(cand, rows, rhs, precision, physical=True)
            assert a == b and a['outcome'][0] == 'return', (candidate, native, n, 'success', a['outcome'], b['outcome'])
            for cancel_at in (1, max(2, len(a['trace'])//2), len(a['trace'])):
                ra, _ = solve_case(ref, rows, rhs, precision, cancel_at, physical=True)
                rb, _ = solve_case(cand, rows, rhs, precision, cancel_at, physical=True)
                assert ra == rb and ra['outcome'][0] == 'raise', (candidate, 'cancel', cancel_at)
            singular = tuple(tuple(G.mpq(0) for _ in range(n)) for _ in range(n))
            ra, _ = solve_case(ref, singular, rhs, precision)
            rb, _ = solve_case(cand, singular, rhs, precision)
            assert ra == rb and ra['outcome'][0] == 'raise'
            assert budget.reserved_bytes == 0
            cases.append(dict(native=native, rank=n, precision=precision, full_solve_physical_equal=True,
                              same_binary_flags_check_trace=True, cancellation_positions=[1, max(2,len(a['trace'])//2),len(a['trace'])],
                              singular_equal=True, reference_point_calls=ac['point'], candidate_point_calls=bc['point'],
                              variant_sha256=cand['_variant_sha256'], handle_counts=cand.get('_handle_counts'), peak_accounted_bytes=budget.peak_reserved_bytes))
    return cases


def native_handle_cases():
    if NATIVE is None:
        return {'status': 'BLOCKED_NATIVE', 'reason': NATIVE_ERROR}
    ns = kernel()
    ar = ns['Arithmetic'](80)
    rows = tuple(tuple(ar.point(q) for q in row) for row in matrix(3))
    xs = [rows[0]]
    budget = WorkBudget(16*1024*1024)
    h = PreparedRHS(NATIVE, rows, ar.down, ar.up, budget)
    assert h.live and budget.reserved_bytes > 0
    actual = NATIVE.prepared_pair_dots(xs, rows, ar.down, ar.up, prepared=h)
    assert sig(actual) == sig(NATIVE.pair_dots(xs, rows, ar.down, ar.up))
    # Caller container replacement cannot free endpoint refs retained by the immutable handle.
    mutable = [list(r) for r in rows]
    original = mutable[0][0]
    h2 = PreparedRHS(NATIVE, mutable, ar.down, ar.up, budget)
    mutable[0][0] = ar.point(G.mpq(77))
    gc.collect()
    assert h2.keep[0] is original
    declined = []
    for label, yy, down, up in [('replacement', mutable, ar.down, ar.up), ('context-identity', h2.rows, G.context(ar.down), ar.up)]:
        try:
            NATIVE.prepared_pair_dots(xs, yy, down, up, prepared=h2)
            raise AssertionError('Stale prepared handle accepted')
        except NATIVE.Unavailable:
            declined.append(label)
    ar.up.precision = 53
    try:
        NATIVE.prepared_pair_dots(xs, rows, ar.down, ar.up, prepared=h)
        raise AssertionError('Changed context accepted')
    except NATIVE.Unavailable:
        declined.append('context-settings')
    ar.up.precision = 80
    before_flags = NATIVE.mpfr_flags_save()
    bad = ((G.mpfr('inf'), G.mpfr('inf')),)*3
    zero = ((ar.zero, ar.zero),)*3
    hb = PreparedRHS(NATIVE, [bad], ar.down, ar.up, budget)
    try:
        NATIVE.prepared_pair_dots([zero], [bad], ar.down, ar.up, prepared=hb)
        raise AssertionError('Exceptional native flag accepted')
    except NATIVE.Unavailable:
        declined.append('exceptional-native-flags')
    assert NATIVE.mpfr_flags_save() == before_flags
    hb.close()
    # Force two native row blocks without large allocations.
    old_block = NATIVE.BLOCK_PRODUCTS
    NATIVE.BLOCK_PRODUCTS = 1
    try:
        try:
            NATIVE.prepared_pair_dots(list(rows), rows, ar.down, ar.up, prepared=h,
                                     check=lambda: (_ for _ in ()).throw(CancelledError('block cancellation')))
            raise AssertionError('block cancellation absent')
        except CancelledError:
            declined.append('block-cancellation')
    finally:
        NATIVE.BLOCK_PRODUCTS = old_block
    h2.close()
    h.close()
    try:
        NATIVE.prepared_pair_dots(xs, rows, ar.down, ar.up, prepared=h)
        raise AssertionError('closed prepared handle accepted')
    except NATIVE.Unavailable:
        declined.append('owner-closed')
    assert budget.reserved_bytes == 0
    small = WorkBudget(1)
    hf = PreparedRHS(NATIVE, rows, ar.down, ar.up, small)
    assert not hf.live and small.reserved_bytes == 0
    ref = kernel(native=True)
    cand = kernel('C5', native=True, budget=small)
    r, _ = solve_case(ref, matrix(3), [G.mpq(1),G.mpq(2),G.mpq(3)])
    c, _ = solve_case(cand, matrix(3), [G.mpq(1),G.mpq(2),G.mpq(3)])
    assert r == c and cand['_handle_counts']['fallback'] == 3
    return dict(status='PASS_NATIVE_PREPARED_ROW_FIXTURE', refusals=declined, optional_admission_reference_fallback=True,
                strong_endpoint_custody=True, native_global_flags_restored=True,
                no_live_charge_after_close=True, prepared_transform_sha256=NATIVE.candidate_source_sha256,
                peak_accounted_bytes=budget.peak_reserved_bytes)


def escaping_owner_case(candidate):
    budget=WorkBudget(16*1024*1024)
    ns=kernel(candidate,native=candidate=='C5',budget=budget)
    ar_type=ns['Arithmetic']
    check=ar_type.check
    def fail(self,phase):
        if phase=='interval-subtract':
            raise CancelledError('injected after optional retained allocation')
        return check(self,phase)
    ar_type.check=fail
    held_error=held_traceback=None
    try:
        ns['solve_enclosure'](matrix(3),[G.mpq(1),G.mpq(2),G.mpq(3)],precision=80)
        raise AssertionError('expected cancellation absent')
    except CancelledError as error:
        held_error=error
        held_traceback=error.__traceback__
    finally:
        ar_type.check=check
    held=budget.reserved_bytes
    assert held>0 and held_error is not None and held_traceback is not None, (candidate,'optional failed frame was uncharged')
    del held_error
    gc.collect()
    trace_only=budget.reserved_bytes
    assert trace_only>0
    del held_traceback
    gc.collect()
    assert budget.reserved_bytes==0
    return dict(exception_held_bytes=held,traceback_only_held_bytes=trace_only,after_drop_bytes=0,
                escaping_frame_custody='actual selected _preserve_workspace and WorkBudget')


def gram_cases():
    cases = []
    for change in ('append', 'prefix-change', 'prefix-reorder', 'basis-change', 'precision-change', 'closed', 'no-funding', 'native-replay', 'native-exception-replay'):
        budget = WorkBudget(1 if change == 'no-funding' else 16*1024*1024)
        owner = GramOwner(budget, ('basis-frame-scale-source-v1',), 80)
        cand = kernel('C11', native=False, gram_owner=owner)
        # Deliberately singular first attempt: completed Gram must survive, no exception frame retained.
        prefix = ((G.mpq(1),G.mpq(0)),)
        r, _ = solve_case(cand, prefix, (G.mpq(1),G.mpq(2)), 80)
        assert r['outcome'][0] == 'raise'
        assert owner.saved is not None or change == 'no-funding'
        held = budget.reserved_bytes
        rows = prefix + ((G.mpq(0),G.mpq(1)), (G.mpq(1,8),G.mpq(-1,4)))
        precision = 80
        native = False
        if change == 'prefix-change':
            rows = ((G.mpq(2),G.mpq(0)),)+rows[1:]
        elif change == 'prefix-reorder':
            rows = rows[::-1]
        elif change == 'basis-change':
            owner.binding = ('changed-basis',)
        elif change == 'precision-change':
            precision = 320
        elif change == 'closed':
            owner.close()
        elif change in ('native-replay','native-exception-replay'):
            if NATIVE is None:
                owner.close()
                cases.append(dict(case=change, status='BLOCKED_NATIVE', reason=NATIVE_ERROR))
                continue
            native = True
        cand = kernel('C11', native=native, gram_owner=owner)
        ref = kernel(native=native)
        original_pair = None
        if change=='native-exception-replay':
            original_pair=NATIVE.pair_dots
            def unavailable(*a,**kw):
                raise NATIVE.Unavailable('injected native failure requires full reference replay')
            NATIVE.pair_dots=unavailable
        try:
            a, _ = solve_case(ref, rows, (G.mpq(1),G.mpq(2)), precision, physical=True)
            b, _ = solve_case(cand, rows, (G.mpq(1),G.mpq(2)), precision, physical=True)
        finally:
            if original_pair is not None:
                NATIVE.pair_dots=original_pair
        assert a == b and a['outcome'][0] == 'return', (change, a, b)
        assert owner.hits == (1 if change == 'append' else 0)
        replacement_peak = budget.peak_reserved_bytes
        owner.close()
        assert budget.reserved_bytes == 0 and owner.saved is None
        cases.append(dict(case=change, status='PASS', full_solve_physical_signature_flags_trace_equal=True,
                          hit_count=owner.hits, full_native_replays=owner.replays, charged_after_failed_attempt=held,
                          replacement_overlap_peak_bytes=replacement_peak, charge_after_close=0))
    # Cancellation during replay leaves the previous completed cache intact and funded.
    budget = WorkBudget(16*1024*1024)
    owner = GramOwner(budget, ('cancellation',), 80)
    cand = kernel('C11', gram_owner=owner)
    prefix = matrix(2,0)
    solve_case(cand,prefix,(G.mpq(1),G.mpq(2)))
    old = owner.saved
    rows=matrix(2,1)
    ref=kernel()
    a,_=solve_case(ref,rows,(G.mpq(1),G.mpq(2)),80,9)
    b,_=solve_case(cand,rows,(G.mpq(1),G.mpq(2)),80,9)
    assert a==b and a['outcome'][0]=='raise' and owner.saved is old and budget.reserved_bytes>0
    owner.close()
    assert budget.reserved_bytes==0
    cases.append(dict(case='cancel-during-prefix-replay',status='PASS',same_failure_flags_trace=True,prior_completed_cache_funded=True))
    # Inexact prefix transitions must match even when cancellation interrupts a later dot.
    prefix=((G.mpq(1,3),G.mpq(2,7)),(G.mpq(2,5),G.mpq(-1,3)))
    rows=prefix+((G.mpq(1,9),G.mpq(3,11)),)
    for position in (10,14,18,24,30):
        budget=WorkBudget(16*1024*1024)
        owner=GramOwner(budget,('inexact-prefix',),80)
        cand=kernel('C11',gram_owner=owner)
        solve_case(cand,prefix,(G.mpq(1,13),G.mpq(2,17)))
        a,_=solve_case(kernel(),rows,(G.mpq(1,13),G.mpq(2,17)),80,position)
        b,_=solve_case(cand,rows,(G.mpq(1,13),G.mpq(2,17)),80,position)
        assert a==b and a['outcome'][0]=='raise',('inexact-prefix-cancel',position,a,b)
        owner.close()
        assert budget.reserved_bytes==0
        cases.append(dict(case='inexact-prefix-cancel',position=position,status='PASS',same_failure_flags_trace=True))
    # A replacement that cannot coexist with the previous cache is optional.
    initial_count=65536+1024*(30*4+4*2*2+128)+8*(256+8*((80+63)//64+2))
    budget=WorkBudget(initial_count+1024)
    owner=GramOwner(budget,('replacement-refusal',),80)
    cand=kernel('C11',gram_owner=owner)
    solve_case(cand,matrix(2,0),(G.mpq(1),G.mpq(2)))
    retained=owner.saved
    assert retained is not None
    a,_=solve_case(kernel(),matrix(2,1),(G.mpq(1),G.mpq(2)))
    b,_=solve_case(cand,matrix(2,1),(G.mpq(1),G.mpq(2)))
    assert a==b and owner.saved is retained and budget.reserved_bytes==initial_count
    owner.close()
    assert budget.reserved_bytes==0
    cases.append(dict(case='replacement-admission-refused',status='PASS',old_cache_still_funded=True,
                      no_new_numerical_refusal=True,baseline_candidate_equal=True))
    return cases


def attempt_cases():
    out=[]
    for native in (False,True):
        if native and NATIVE is None:
            continue
        for case in ('success','normal-refusal','cancellation','entry-refusal','mutable-fallback'):
            rows=matrix(2,0)
            rhs=(G.mpq(1,8),G.mpq(3,8))
            if case=='normal-refusal':
                rows=((G.mpq(0),G.mpq(0)),)*2
            if case=='mutable-fallback':
                rows=[list(r) for r in rows]
            cancel_at=8 if case=='cancellation' else None
            limit=1 if case=='entry-refusal' else 256*1024*1024
            ref=kernel(native=native)
            mo=MatrixOwner()
            cand=kernel('C16',native=native,matrix_owner=mo)
            a,_=attempt(ref,rows,rhs,320,cancel_at=cancel_at,budget_bytes=limit)
            b,_=attempt(cand,rows,rhs,320,owner=mo,cancel_at=cancel_at,budget_bytes=limit)
            assert a['outcome']==b['outcome'] and a['checks']==b['checks'],(case,native,a,b)
            assert a['resource_evidence']==b['resource_evidence']
            assert a['after_drop_bytes']==b['after_drop_bytes']==0,(case,a,b)
            if case!='entry-refusal':
                assert b['owner_closed'] and mo.rows is None
            else:
                mo.close() # attempt entry refused before any matrix allocation/capture
            if case=='success':
                assert a['outcome'][0]=='return' and mo.hits==4, (case,native,a,b)
            if case=='normal-refusal':
                assert a['outcome'][0]=='refused'
            out.append(dict(case=case,native=native,reference=a,candidate=b))
    return out


def additional_attempts(candidate):
    """Existing r3 admission/export owner receives each changed numerical consumer."""
    out=[]
    for native in (False,True):
        if native and NATIVE is None:
            continue
        rows=matrix(2,0)
        rhs=(G.mpq(1,8),G.mpq(3,8))
        ref=kernel(native=native)
        budget=WorkBudget(256*1024*1024)
        cand=kernel(candidate,native=native,budget=budget)
        a,_=attempt(ref,rows,rhs,320)
        b,_=attempt(cand,rows,rhs,320,budget_override=budget)
        assert a['outcome']==b['outcome'] and a['checks']==b['checks']
        assert a['resource_evidence']==b['resource_evidence']
        assert a['outcome'][0]=='return' and a['after_drop_bytes']==b['after_drop_bytes']==0
        out.append(dict(native=native,full_attempt_exact_export_equal=True,
                        reference_peak_accounted_bytes=a['peak_accounted_bytes'],candidate_peak_accounted_bytes=b['peak_accounted_bytes'],
                        unchanged_interval_export_reservations=True,actual_result_closed=True))
    if candidate=='C4':
        ref=kernel()
        small=WorkBudget(1)
        cand=kernel('C4',budget=small)
        a,_=solve_case(ref,matrix(3),tuple(G.mpq(i,8) for i in range(3)))
        b,_=solve_case(cand,matrix(3),tuple(G.mpq(i,8) for i in range(3)))
        assert a==b and small.reserved_bytes==0
        out.append(dict(optional_admission_reference_fallback=True))
    return out


def benchmark_factory(candidate, arm, scenario='ordinary', rank=4):
    """Return an entire changed component call, with optional setup/close INSIDE it.

    Module import/JIT is separately observed once. Test-only AST construction is
    outside timed calls. Inputs are fixed synthetic rank4/precision320 fixtures.
    """
    use_candidate=arm=='candidate'
    rows=matrix(rank,0)
    rhs=tuple(G.mpq(i+1,8) for i in range(rank))
    keys=[('cell',i) for i in range(len(rows))]
    budget=WorkBudget(256*1024*1024)
    native=candidate!='C11'
    matrix_owner=MatrixOwner() if candidate=='C16' and use_candidate else None
    gram_owner=GramOwner(budget,('benchmark-fixed-basis',),320) if candidate=='C11' and use_candidate else None
    ns=kernel(candidate if use_candidate else None,native=native,budget=budget,
              gram_owner=gram_owner,matrix_owner=matrix_owner)
    env=compile_attempt(ns,matrix_owner) if candidate in ('C11','C16') else None
    def operation():
        if candidate=='C16':
            if matrix_owner is not None:
                matrix_owner.__init__()
            owner,reason=env['_attempt'](rows,rhs,keys,keys[:2],G.mpq(0),[G.mpq(1)]*len(rows),{},precision=320,
                largest_owned_bytes=64,budget=budget,cancelled=None,audit={},resource_evidence=[])
            if owner is None:
                raise AssertionError(('Benchmark actual attempt refused',reason))
            answer=sig(owner.value)
            owner.close()
        elif candidate=='C11':
            prefix=rows[:-1]
            final=rows
            if scenario=='mismatch':
                final=rows[::-1]
            if gram_owner is not None:
                gram_owner.__init__(WorkBudget(1) if scenario=='no-funding' else budget,('benchmark-fixed-basis',),320)
            try:
                first,reason=env['_attempt'](prefix,rhs,keys[:-1],keys[:2],G.mpq(0),[G.mpq(1)]*len(prefix),{},precision=320,
                    largest_owned_bytes=64,budget=budget,cancelled=None,audit={},resource_evidence=[])
                if first is not None or reason is None:
                    raise AssertionError('Expected source r3 prefix refusal')
                owner,reason=env['_attempt'](final,rhs,keys,keys[:2],G.mpq(0),[G.mpq(1)]*len(final),{},precision=320,
                    largest_owned_bytes=64,budget=budget,cancelled=None,audit={},resource_evidence=[])
                if owner is None:
                    raise AssertionError(('Completed append attempt refused',reason))
                answer=sig(owner.value)
                owner.close()
            finally:
                if gram_owner is not None:
                    gram_owner.close()
        else:
            # Same conservative interval envelope plus explicit optional owner charge.
            plan=INVENTORY.interval_plan(len(rows),len(rhs),320,64,R)
            work=R.OwnedWorkspace(budget,plan.total,category='benchmark-full-interval')
            work.__enter__()
            try:
                dual,ar,proof=ns['solve_enclosure'](rows,rhs,precision=320)
                bounds=ns['physical_bounds'](rows,dual,keys,keys[:2],G.mpq(0),[G.mpq(1)]*len(rows),ar)
                answer=sig([dual,proof,bounds])
                dual=ar=proof=bounds=None
            except BaseException:
                work.__exit__(*sys.exc_info())
                raise
            else:
                work.__exit__(None,None,None)
        if budget.reserved_bytes:
            raise AssertionError('Benchmark retained charge after component close')
        return answer,budget.peak_reserved_bytes
    return operation


def benchmark(candidates):
    # Invocation belongs to an admitted queue command; this agent never invokes it.
    from time import perf_counter
    out={}
    for candidate in candidates:
        scenarios=('append','mismatch','no-funding') if candidate=='C11' else ('ordinary',)
        records=[]
        for rank,scenario in ((rank,scenario) for rank in (4,20) for scenario in scenarios):
            arms={name:benchmark_factory(candidate,name,scenario,rank) for name in ('baseline','candidate')}
            samples=[]
            complete_calls=4 if rank==4 else 1
            # Four counterbalanced pairs; bounded complete calls per arm/sample.
            for order in (('baseline','candidate'),('candidate','baseline'),('baseline','candidate'),('candidate','baseline')):
                for arm in order:
                    started=perf_counter()
                    values=[arms[arm]() for _ in range(complete_calls)]
                    seconds=perf_counter()-started
                    digests=[hashlib.sha256(json.dumps(v[0],sort_keys=True).encode()).hexdigest() for v in values]
                    if len(set(digests))!=1:
                        raise AssertionError('Nonrepeatable component output')
                    samples.append(dict(arm=arm,seconds=seconds,complete_calls=complete_calls,result_sha256=digests[0],
                                        peak_accounted_bytes=max(v[1] for v in values)))
            if len({s['result_sha256'] for s in samples})!=1:
                raise AssertionError('Benchmark baseline/candidate output differs')
            records.append(dict(scenario=scenario,samples=samples,rank=rank,precision=320,
                observations=rank,prefix_observations=rank-1 if candidate=='C11' else None,
                scope='full source-bound changed component including setup, guards, ownership and release; synthetic, not whole heat'))
        out[candidate]=dict(status='PASS',benchmarks=records)
    return out


def benchmark_smoke(candidate):
    records=[]
    scenarios=('append','mismatch','no-funding') if candidate=='C11' else ('ordinary',)
    for rank,scenario in ((rank,scenario) for rank in (4,20) for scenario in scenarios):
        a=benchmark_factory(candidate,'baseline',scenario,rank)()
        b=benchmark_factory(candidate,'candidate',scenario,rank)()
        if a[0]!=b[0]:
            raise AssertionError('Prepared benchmark component outcomes differ: '+candidate+'/'+scenario)
        records.append(dict(scenario=scenario,rank=rank,precision=320,baseline_candidate_equal=True,
                            result_sha256=hashlib.sha256(json.dumps(a[0],sort_keys=True).encode()).hexdigest(),
                            baseline_peak_accounted_bytes=a[1],candidate_peak_accounted_bytes=b[1]))
    return records


def aggregate_status(candidates, requested):
    """PASS requires complete exact requested coverage and every arm passing."""
    return 'PASS' if (bool(requested) and set(candidates) == set(requested)
                      and all(record.get('status') == 'PASS' for record in candidates.values())) else 'FAIL'


def main():
    global NATIVE,ZERO_NATIVE,NATIVE_ERROR
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--correctness',action='store_true')
    mode.add_argument('--benchmark',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--candidate',action='append',choices=['C3','C4','C5','C11','C15','C16','C17'])
    args=parser.parse_args()
    if args.output.exists():
        parser.error('--output must name a new path')
    # Set this process to one available CPU before JIT, with no persistent environment change.
    import psutil
    process=psutil.Process()
    process.cpu_affinity(process.cpu_affinity()[:1])
    result=dict(schema='plan40b.certificate-testing-r1',status='INCOMPLETE',source_map_sha256=MAP_SHA,
                mode='benchmark' if args.benchmark else 'correctness',retained_evidence=reuse_evidence(), candidates={},
                bounds=dict(one_core=True,projected_peak_rss_mib=700,projected_runtime_seconds=180),
                claims=dict(production_changed=False,scientific_run=False,performance_measured=False,whole_runtime_qualified=False))
    selected=args.candidate or ['C3','C4','C5','C11','C15','C16','C17']
    result['requested_candidates']=list(dict.fromkeys(selected))
    result['limitations']=[
        'Bounded source-bound fixtures only; no production or whole-runtime qualification.',
        'No scientific acceptance or whole-heat performance projection.',
        'C11 native prefix continuation is unsupported; the complete native reference route is retained.',
        'C16 and C17 savings overlap and must not be summed.',
    ]
    try:
        if args.benchmark:
            from time import perf_counter
            native_start=perf_counter()
        NATIVE=native_module()
        info=NATIVE.build_info()
        info.pop('load_seconds',None) # correctness-only, no timing claim
        info['mpfr_dll']=Path(info['mpfr_dll']).name
        result['native_build']=info
        if args.benchmark:
            result['native_reference_import_compile_selftest_seconds']=perf_counter()-native_start
        if 'C3' in selected:
            if args.benchmark:
                candidate_start=perf_counter()
            ZERO_NATIVE=native_module(True)
            result['C3_native_transform_sha256']=ZERO_NATIVE.executed_source_sha256
            if args.benchmark:
                result['C3_native_candidate_import_compile_selftest_seconds']=perf_counter()-candidate_start
    except Exception as error:
        NATIVE_ERROR=type(error).__name__+': '+str(error)
        result['native_blocker']=NATIVE_ERROR
    if args.benchmark:
        if NATIVE is None or ('C3' in selected and ZERO_NATIVE is None):
            result.update(reason=NATIVE_ERROR)
            result['candidates']={candidate:dict(status='BLOCKED',reason=NATIVE_ERROR) for candidate in selected}
        else:
            try:
                result['candidates']=benchmark(selected)
                result['claims']['performance_measured']=True
            except Exception as error:
                result.update(status='FAIL',error=type(error).__name__+': '+str(error))
        result['status']=aggregate_status(result['candidates'],selected)
        result['script_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        result['sources']=SOURCES
        result['workload_sha256']=hashlib.sha256(json.dumps({'ranks':[4,20],'precision':320,'calls_per_sample_by_rank':{'4':4,'20':1},'paired_orders':4,'source':result['script_sha256']},sort_keys=True).encode()).hexdigest()
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps({'status':result['status'],'candidates':list(result['candidates'])}))
        return 0 if result['status']=='PASS' else 1
    for candidate in ('C3','C4','C5','C15','C17'):
        if args.candidate and candidate not in args.candidate:
            continue
        try:
            cases=basic_integration(candidate)
            result['candidates'][candidate]=dict(status='PASS',scope='source-bound integration fixture',cases=cases,attempts=additional_attempts(candidate))
            if candidate in ('C4','C5'):
                result['candidates'][candidate]['escaping_optional_owner']=escaping_owner_case(candidate)
        except Exception as error:
            import traceback
            result['candidates'][candidate]=dict(status='FAIL',error=type(error).__name__+': '+str(error),traceback=traceback.format_exc())
    for candidate,fn in (('C5-handle',native_handle_cases),('C11',gram_cases),('C16',attempt_cases)):
        if args.candidate and candidate.split('-')[0] not in args.candidate:
            continue
        try:
            checks=fn()
            if candidate=='C5-handle':
                result['candidates']['C5']['native_handle']=checks
            else:
                result['candidates'][candidate]=dict(status='PASS',scope='source-bound lifetime fixture',cases=checks)
        except Exception as error:
            import traceback
            result['candidates'][candidate.split('-')[0]]=dict(status='FAIL',error=type(error).__name__+': '+str(error),traceback=traceback.format_exc())
    for candidate in selected:
        if result['candidates'].get(candidate,{}).get('status')=='PASS':
            try:
                result['candidates'][candidate]['benchmark_component_untimed_smoke']=benchmark_smoke(candidate)
            except Exception as error:
                import traceback
                result['candidates'][candidate].update(status='FAIL',benchmark_smoke_error=type(error).__name__+': '+str(error),traceback=traceback.format_exc())
    result['sources']=SOURCES
    result['script_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['environment']=dict(python=sys.version,gmpy2=G.version(),mpfr=G.mpfr_version())
    result['process_peak_wset_bytes']=getattr(process.memory_info(),'peak_wset',None)
    result['workload_sha256']=hashlib.sha256(json.dumps({'ranks':[2,4],'precisions':[80,320],'source':result['script_sha256']},sort_keys=True).encode()).hexdigest()
    result['status']=aggregate_status(result['candidates'],selected)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'status':result['status'],'native_available':NATIVE is not None,'candidates':{k:v['status'] for k,v in result['candidates'].items()}}))
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
