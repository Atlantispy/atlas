"""Bounded private diagnostic sparse Gaussian elimination with partial pivoting.

Same supplied Decimal system, higher arithmetic precision, no regularisation,
dropping, tolerance pivot or physical change. Structural RCM ordering is optional.
MPFR factor precision is explicit; the caller independently checks the original
unscaled residual. This is not yet native WorkBudget admission.
"""
from concurrent.futures import CancelledError
from decimal import Decimal
from time import perf_counter

import gmpy2 as G


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Private MPFR factorisation cancelled')


def _mp(value):
    if type(value) is Decimal:
        a, b = value.as_integer_ratio()
        return G.mpfr(G.mpq(a, b))
    return G.mpfr(value)


def factor(rows, *, precision=512, cancel=None, observe=None):
    """Return factors plus pivot sequence. All entries are retained, including fill."""
    if type(precision) is not int or precision < 320:
        raise ValueError('Explicit factor precision of at least320 bits required')
    n = len(rows)
    if not n or n > 1024:
        raise ValueError('This bounded private diagnostic admits1..1024 rows')
    began = perf_counter()
    with G.context(precision=precision):
        a = []
        for row in rows:
            _check(cancel)
            built = {}
            for j, value in row:
                if type(j) is not int or not 0 <= j < n or j in built:
                    raise ValueError('Unique in-range columns required')
                v = _mp(value)
                if not G.is_finite(v):
                    raise ValueError('Finite coefficients required')
                if v:
                    built[j] = v
            a.append(built)
        pivots = []
        peak_nnz = sum(map(len, a))
        for k in range(n):
            _check(cancel)
            pivot = max(range(k, n), key=lambda i: abs(a[i].get(k, 0)))
            if not a[pivot].get(k, 0):
                raise ValueError('Exactly zero represented MPFR pivot; no regularisation permitted')
            pivots.append(pivot)
            if pivot != k:
                a[k], a[pivot] = a[pivot], a[k]
            diagonal = a[k][k]
            upper = [(j, v) for j, v in a[k].items() if j > k]
            for i in range(k+1, n):
                if k not in a[i]:
                    continue
                _check(cancel)
                multiplier = a[i][k]/diagonal
                a[i][k] = multiplier
                for j, value in upper:
                    updated = a[i].get(j, 0)-multiplier*value
                    if updated:
                        a[i][j] = updated
                    else:
                        a[i].pop(j, None)  # Only exact represented zero, never tiny-drop.
            if k % 16 == 0 or k == n-1:
                nnz = sum(map(len, a))
                peak_nnz = max(peak_nnz, nnz)
                if observe is not None:
                    observe(dict(pivot=k, rows=n, factor_nnz=nnz, seconds=perf_counter()-began))
        return dict(rows=a, pivots=pivots, precision=precision,
                    peak_factor_nnz=peak_nnz, seconds=perf_counter()-began)


def solve(factors, rhs, *, cancel=None):
    a, pivots = factors['rows'], factors['pivots']
    if len(rhs) != len(a):
        raise ValueError('Original RHS coverage required')
    with G.context(precision=factors['precision']):
        b = list(map(_mp, rhs))
        for k, pivot in enumerate(pivots):
            if k != pivot:
                b[k], b[pivot] = b[pivot], b[k]
        for i, row in enumerate(a):
            _check(cancel)
            b[i] -= sum((v*b[j] for j, v in row.items() if j < i), G.mpfr(0))
        for i in range(len(a)-1, -1, -1):
            _check(cancel)
            b[i] = (b[i]-sum((v*b[j] for j, v in a[i].items() if j > i), G.mpfr(0)))/a[i][i]
        return b
