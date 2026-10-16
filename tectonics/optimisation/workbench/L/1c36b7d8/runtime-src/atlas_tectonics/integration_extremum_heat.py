"""Cell-centred extremum-preserving heat on a source-issued metric complex.

One temperature per material cell. Each shared face carries ONE transfer

    F = t (T_K - T_L) + N(G_K, G_L),

where ``t`` carries the magnitude of the conormal ``k A`` along the line to the
harmonic averaging point (for equal conductivities ``t = k |A| / |x_L - x_K|``),
and ``G_K``, ``G_L`` are the two cells' own estimates of what remains. Each
estimate is a combination of temperature differences with certified NONNEGATIVE
weights; ``N`` keeps their harmonic mean when they agree in direction and
nothing otherwise.
Seen from either owner the transfer is therefore a nonnegative combination of
``T_owner - T_other``: with zero boundary power no cell can leave the range of
the backward-Euler loads and prescribed face temperatures.

Method: Lipnikov, Svyatskiy and Vassilevski (2012), equations 2.2-2.11 (one-sided
positive decompositions, harmonic averaging points, two-sided weights); Droniou
(2014), section 6.2 and remark 6.2 (equal two-point parts keep the flux
continuous). Amanzi's ``PDE_DiffusionNLFV``/``nlfv.cc`` were read as software
precedent; its decomposition tolerance and absolute values of negative weights
are NOT used. Differences from those sources are stated in the method document.
The steady schemes above are used here inside one backward-Euler step with the
current capacities, and solved in 80-digit decimal arithmetic.
SPDX-License-Identifier: AGPL-3.0-only
"""
from collections import OrderedDict
from contextlib import contextmanager
from decimal import Decimal as D, ROUND_HALF_EVEN, localcontext
import hashlib
from itertools import combinations
import math
from pathlib import Path
import sys
from time import perf_counter

import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from scipy.sparse.linalg import splu

from ._validation import TectonicsError
from .integration_regional_inventory import _width
from .regional_heat3d import _cancel
from .resources import WorkBudget
from . import integration_mimetic_newton as N

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SCHEME = 'extremum-multipoint'
_PRECISION = 80
_GATE = D('1e-11')                 # the existing relative heat gate
# A stored combination must reproduce its vector to twenty digits fewer than
# the working precision. This bounds the consistency defect; it is not a heat gate.
_DEFECT = D(10)**(20-_PRECISION)
_PICARD_START = 2                  # bounded steps before the first Newton trial
_LIMIT = 64                        # bounded steps in all; an unfinished state is refused
_BASIS, _RESTARTS = 40, 2          # bounded inner Krylov work per Newton trial
_SUPPORT = 1e-11                   # float selection only; every weight is re-derived in Decimal
_LP_CACHE_BYTES = 1024**2           # optional, retained only during one prepare call


def assert_current():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
        raise TectonicsError('extremum heat source changed during solve')
    return _LOADED


def _dec(q):
    """An exact rational rounded to the working precision.

    Geometry rationals carry thousands of digits. One integer division with
    sixteen guard digits replaces two very long integer-to-Decimal conversions;
    its truncation is 1e-16 of the rounding unit of the returned value.
    """
    n, d = q.numerator, q.denominator
    if not n:
        return D(0)
    digits = _PRECISION+16-int((abs(n).bit_length()-d.bit_length())*0.30103)
    scaled = abs(n)*10**digits//d if digits >= 0 else abs(n)//(d*10**-digits)
    return D(-scaled if n < 0 else scaled).scaleb(-digits)


def _same(vector):
    """Scale-free key that only recognises one candidate vector reached twice.

    Components are compared relative to the largest one and the size to twelve
    significant digits, so nothing depends on the unit of length: distinct
    planes a picometre apart stay distinct. Used to avoid duplicate candidates,
    never to decide a weight.
    """
    values = [float(c) for c in vector]
    scale = max(map(abs, values))
    if not scale:
        return (0., 0., 0., 0.)
    return (*(round(v/scale, 12) for v in values), float('%.11e' % scale))


def _limited(gk, gl):
    """Harmonic mean of two agreeing one-sided remainders; zero when they disagree.

    ``gk`` is K's estimate of the K->L remainder and ``gl`` is L's estimate of
    the L->K remainder, so agreement means opposite signs. The value tends to
    zero with either argument: no regularising constant is needed or used.
    """
    if (gk > 0 and gl < 0) or (gk < 0 and gl > 0):
        return 2*gk*abs(gl)/(abs(gk)+abs(gl))
    return D(0)


def _least(columns, target):
    """Decimal least squares for at most four columns (normal equations)."""
    n = len(columns)
    m = [[sum((a*b for a, b in zip(columns[i], columns[j])), D(0)) for j in range(n)]+
         [sum((a*b for a, b in zip(columns[i], target)), D(0))] for i in range(n)]
    for k in range(n):
        pivot = max(range(k, n), key=lambda i: abs(m[i][k]))
        if not m[pivot][k]:
            return None
        m[k], m[pivot] = m[pivot], m[k]
        for i in range(k+1, n):
            if m[i][k]:
                f = m[i][k]/m[k][k]
                m[i] = [a-f*b for a, b in zip(m[i], m[k])]
    answer = [D(0)]*n
    for k in range(n-1, -1, -1):
        answer[k] = (m[k][n]-sum((m[k][j]*answer[j] for j in range(k+1, n)), D(0)))/m[k][k]
    return answer


def _certify(target, vectors, support):
    """Positive Decimal weights on ``support`` reproducing ``target``, or None.

    The certificate is what is stored: every weight is positive and the
    recomputed combination differs from the target by at most ``_DEFECT`` of
    its largest component. A float selection is never trusted for a sign.
    """
    support = sorted(set(support))
    scale = max(map(abs, target))
    for _ in range(2):
        if not support:
            return None
        columns = [vectors[j] for j in support]
        weights = _least(columns, target)
        if weights is None:
            return None
        if all(w > 0 for w in weights):
            defect = max(abs(sum((w*c[i] for w, c in zip(weights, columns)), D(0))-target[i])
                         for i in range(len(target)))
            return tuple(zip(support, weights)) if defect <= _DEFECT*scale else None
        support = [j for j, w in zip(support, weights) if w > 0]
    return None


def _ranked_supports(unit, goal, cost, limit=64):
    """Float enumeration of every single, pair and triple; cheapest feasible first."""
    m = unit.shape[1]
    found = []
    for size in (1, 2, 3):
        if m < size:
            break
        index = np.asarray(list(combinations(range(m), size)), dtype=np.intp)
        columns = unit[:, index]                                # 3 x count x size
        gram = np.einsum('ics,ict->cst', columns, columns)
        rhs = np.einsum('ics,i->cs', columns, goal)
        good = np.abs(np.linalg.det(gram)) > 1e-18
        if not good.any():
            continue
        weights = np.linalg.solve(gram[good], rhs[good][..., None])[..., 0]
        chosen = index[good]
        residual = np.linalg.norm(np.einsum('ics,cs->ci', columns[:, good], weights)-goal, axis=1)
        feasible = (residual <= 1e-9) & np.all(weights > _SUPPORT, axis=1)
        values = np.einsum('cs,cs->c', weights[feasible], cost[chosen[feasible]])
        found.extend((float(value), tuple(int(j) for j in row)) for row, value in zip(chosen[feasible], values))
    found.sort()
    return [row for _, row in found[:limit]]


def _lp_support(cost, unit, goal, limit):
    """The only LP result consumed by decomposition; failed selections are not reusable."""
    answer = linprog(cost, A_eq=unit, b_eq=goal, bounds=(0, None), method='highs-ds',
                     A_ub=limit, b_ub=None if limit is None else [1.])
    if answer.status == 0:
        weights = answer.x
        return tuple(j for j in range(len(cost)) if weights[j] > _SUPPORT*weights.max())
    return None


class _LPSupportCache:
    """Exact LP inputs to immutable support, with no geometry or Decimal-weight reuse.

    The caller reserves twice ``capacity``: one half bounds retained entries,
    the other bounds a transient key/support and mapping growth. Oversized
    problems go directly to the original selector without building a key.
    """
    def __init__(self, capacity):
        self.capacity = capacity
        self.entries = OrderedDict()
        self.retained_bytes = 0

    @staticmethod
    def _width(value):
        return sys.getsizeof(value)+(sum(_LPSupportCache._width(v) for v in value)
                                     if isinstance(value, tuple) else 0)

    def __call__(self, cost, unit, goal, limit):
        arrays = (cost, unit, goal, limit)
        # Includes byte payloads, dtype/shape/stride tuples, Python integer
        # supports (at most one per column), containers and insertion slack.
        scratch = (4096+64*cost.size+
                   sum(a.nbytes+512*(a.ndim+1) for a in arrays if a is not None))
        if scratch > self.capacity:
            return _lp_support(cost, unit, goal, limit)
        key = (tuple(None if a is None else (a.dtype.str, a.shape, a.strides, a.tobytes()) for a in arrays),
               (0, None), 'highs-ds', None if limit is None else (1.,))
        if key in self.entries:
            support, _ = self.entries[key]
            self.entries.move_to_end(key)
            return support
        support = _lp_support(cost, unit, goal, limit)
        if support is not None:
            # The fixed allowance covers the mapping slot, stored value tuple
            # and allocator/container overhead in addition to all key objects.
            size = self._width(key)+self._width(support)+512
            if size+4096 <= self.capacity:
                while self.entries and self.retained_bytes+size+4096 > self.capacity:
                    _, (_, previous) = self.entries.popitem(last=False)
                    self.retained_bytes -= previous
                self.entries[key] = (support, size)
                self.retained_bytes += size
        return support

    def clear(self):
        self.entries.clear()
        self.retained_bytes = 0


@contextmanager
def _lp_support_reuse(budget):
    """Optional admission never introduces a new memory refusal."""
    with budget.try_reserve(2*_LP_CACHE_BYTES, category='extremum-heat-lp-cache') as admitted:
        if not admitted:
            yield _lp_support
            return
        cache = _LPSupportCache(_LP_CACHE_BYTES)
        try:
            yield cache
        finally:
            cache.clear()


def _decompose(target, vectors, costs, bounded=None, *, lp_support=None):
    """Certified nonnegative weights with the smallest declared linear cost.

    ``costs[j]`` is the cost of a unit weight on ``vectors[j]``. A binary64
    linear programme only SELECTS a support; :func:`_certify` then derives the
    stored Decimal weights and refuses anything negative or inexact. When the
    programme fails or its support does not certify, every single, pair and
    triple is ranked in binary64 and certified in that order. ``bounded`` marks
    candidates whose weights together may not exceed one (face temperatures).
    Returns ``((index, weight), ...)`` or None when no certified combination
    exists; a refusal is never replaced by an uncertified answer.
    """
    m = len(vectors)
    if not m or not any(target):
        return None
    matrix = np.asarray([[float(c) for c in v] for v in vectors]).T
    goal = np.asarray([float(c) for c in target])
    length, size = np.linalg.norm(matrix, axis=0), float(np.linalg.norm(goal))
    if not size or not np.all(length > 0) or not np.isfinite(matrix).all():
        return None
    unit, goal = matrix/length, goal/size
    cost = np.asarray(costs, dtype=float)/length
    # Selection only. Costs are divided by their own typical size, so the
    # programme's fixed tolerances see the same numbers whatever the unit of
    # length; a candidate a million times dearer than the typical one is never
    # preferred, and the cap keeps the programme well scaled without removing it.
    typical = max(float(np.median(np.abs(cost))), 1e-300)
    cost = np.minimum(cost, 1e6*typical)/typical
    limit = None if bounded is None else (np.asarray(bounded, dtype=float)*size/length)[None, :]

    def admitted(found):
        """Bounded weights may fill, but never exceed, the whole unit."""
        if found is None or bounded is None:
            return found
        return found if sum((w for j, w in found if bounded[j]), D(0)) <= 1 else None

    def certified(support):
        if bounded is not None and len(support) == 4:
            # The unit bound is active: solve with it as a fourth equation, then
            # make the last bounded weight the exact complement of the others.
            scale = max(map(abs, target))
            wide = [(*vectors[j], scale if bounded[j] else D(0)) for j in range(m)]
            found = _certify((*target, scale), wide, support)
            if found is None:
                return None
            last = max(j for j, _ in found if bounded[j])
            rest = sum((w for j, w in found if bounded[j] and j != last), D(0))
            if rest >= 1:
                return None
            found = tuple((j, 1-rest if j == last else w) for j, w in found)
            defect = max(abs(sum((w*vectors[j][i] for j, w in found), D(0))-target[i]) for i in range(3))
            return found if defect <= _DEFECT*scale else None
        return admitted(_certify(target, vectors, support)) if len(support) <= 3 else None

    try:
        support = (_lp_support if lp_support is None else lp_support)(cost, unit, goal, limit)
    except ValueError:
        support = None
    if support is not None:
        found = certified(support)
        if found is not None:
            return found
    for support in _ranked_supports(unit, goal, cost):
        found = certified(support)
        if found is not None:
            return found
    return None


def _symbolic(pattern, order):
    """Entries of the eliminated factors for the widest pattern, before any value exists."""
    rows = [set(row) for row in pattern]
    columns = [set() for _ in rows]
    for i, row in enumerate(rows):
        for j in row:
            columns[j].add(i)
    entries = 0
    for k in order:
        row = rows[k]
        entries += len(row)+len(columns[k])
        for j in row:
            columns[j].discard(k)
        for i in columns[k]:
            target = rows[i]
            target.discard(k)
            for j in row:
                if j != i and j not in target:
                    target.add(j)
                    columns[j].add(i)
        columns[k] = ()
    return entries


def _eliminate(off, sums, order, cancel=None):
    """Subtraction-free elimination of a row-dominant M-matrix in binary64.

    Row ``i`` is ``(sums[i] + sum(off[i].values())) x_i - sum(off[i][j] x_j)``
    with nonnegative ``off`` and ``sums``. A pivot is always formed as a SUM of
    the current off-diagonal magnitudes and the carried row sum, never as a
    difference (Grassmann, Taksar and Heyman 1985; Alfa, Xue and Ye 2002), so
    a capacity far below the rounding of its exchange coefficients is kept to
    relative accuracy. The factors are returned as exact Decimal images.
    """
    n = len(off)
    rows, v = [dict(r) for r in off], [float(s) for s in sums]
    columns = [set() for _ in range(n)]
    for i, row in enumerate(rows):
        for j in row:
            columns[j].add(i)
    upper, diagonal, lower = [None]*n, [0.]*n, []
    for at, k in enumerate(order):
        if not at % 64:
            _cancel(cancel)
        row = rows[k]
        d = v[k]
        for value in row.values():
            d += value
        if not d > 0 or not math.isfinite(d):
            raise TectonicsError('extremum heat system has a cell with no capacity and no exchange')
        diagonal[k], upper[k] = d, row
        for j in row:
            columns[j].discard(k)
        for i in columns[k]:
            target = rows[i]
            factor = target.pop(k)/d
            lower.append((i, k, factor))
            for j, value in row.items():
                if j != i:
                    if j in target:
                        target[j] += factor*value
                    else:
                        target[j] = factor*value
                        columns[j].add(i)
            v[i] += factor*v[k]
        columns[k] = ()
    entries = len(lower)+sum(map(len, upper))
    return (tuple((i, k, D(f)) for i, k, f in lower),
            tuple(tuple((j, D(value)) for j, value in row.items()) for row in upper),
            tuple(map(D, diagonal)), entries)


def _substitute(factor, rhs, order):
    """Apply the eliminated system in the caller's Decimal context."""
    lower, upper, diagonal, _ = factor
    b = list(rhs)
    for i, k, f in lower:
        if b[k]:
            b[i] += f*b[k]
    x = [D(0)]*len(b)
    for k in reversed(order):
        total = b[k]
        for j, value in upper[k]:
            total += value*x[j]
        x[k] = total/diagonal[k]
    return x


class _Prepared:
    """Geometry-only stencils for one conductivity field and one set of fixed faces."""
    __slots__ = ('nc', 'nf', 'fixed', 'interior', 'dirichlet', 'neumann', 'traces', 'order',
                 'statistics', 'conductivity', 'fill', 'bytes', 'seconds', 'geometry_id')


def workspace_bytes(geometry):
    """Conservative admission for stencil construction and the retained stencils.

    Decimal vectors for every signed incidence, one cell's two-ring candidate
    table at a time, and at most eight retained weights per one-sided transfer
    or face temperature. Accounting, not a resident-set cap.
    """
    incidences = sum(len(row[2]) for row in geometry._cells)
    n = len(geometry._cells)+len(geometry._incidence)
    return 2*1024**2+4*_width(geometry._cells)+6144*incidences+8192*n


def prepare(geometry, conductivity, fixed, *, budget, cancel=None):
    """Certified one-sided decompositions and face-centroid interpolations.

    Candidates of a cell: its face neighbours (through the harmonic averaging
    point; the neighbour's centre when conductivities are equal), prescribed
    face temperatures at face centroids, and planes of prescribed power, whose
    outward normal has a known directional derivative. The same three kinds of
    information held by its face neighbours are also candidates, but only along
    chains of equal conductivity: no stencil reaches across a conductivity jump
    except through that interface's own harmonic point.
    """
    if (type(budget) is not WorkBudget or geometry._budget is not budget or
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED):
        raise TectonicsError('changed extremum heat source or mismatched resource')
    with localcontext() as context, _lp_support_reuse(budget) as lp_support:
        context.prec, context.rounding = _PRECISION, ROUND_HALF_EVEN
        return _prepare(geometry, conductivity, fixed, cancel, lp_support)


def _prepare(geometry, conductivity, fixed, cancel, lp_support):
    started = perf_counter()
    cells, incidence = geometry._cells, geometry._incidence
    nc, nf = len(cells), len(incidence)
    fixed = frozenset(fixed)
    zero, one, two = D(0), D(1), D(2)
    dec = _dec
    dot = lambda a, b: a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
    norm = lambda a: float(dot(a, a).sqrt())
    k = [D.from_float(float(x)) for x in np.broadcast_to(conductivity, (nc,))]
    if any(not x.is_finite() or x <= 0 for x in k):
        raise TectonicsError('positive finite cell conductivity required')
    centre = [tuple(map(dec, row[1])) for row in cells]
    local = []                                   # per cell: face -> (area vector, offset, D_K, A.A)
    for at, row in enumerate(cells):
        if not at % 32:
            _cancel(cancel)
        local.append({fi: (tuple(map(dec, vector)), tuple(map(dec, offset)), dec(distance),
                           dec(sum(c*c for c in vector)))
                      for fi, offset, vector, distance in zip(row[2], row[4], row[5], row[6])})
    other = lambda ci, fi: next(c for c, _ in incidence[fi] if c != ci)
    neighbours = [dict() for _ in cells]
    for fi, owners in enumerate(incidence):
        if len(owners) == 2:
            a, b = owners[0][0], owners[1][0]
            neighbours[a].setdefault(b, []).append(fi)
            neighbours[b].setdefault(a, []).append(fi)

    def harmonic(ci, fi):
        """Vector from the cell centre to the harmonic averaging point, and the neighbour's weight."""
        area, _, dk, aa = local[ci][fi]
        cj = other(ci, fi)
        dl = local[cj][fi][2]
        line = tuple(b-a for a, b in zip(centre[ci], centre[cj]))
        if k[ci] == k[cj]:
            weight = dk/(dk+dl)
            return tuple(weight*c for c in line), weight
        denominator = k[ci]*dl+k[cj]*dk
        weight = k[cj]*dk/denominator
        shift = (k[ci]-k[cj])*dk*dl/(aa*denominator)
        return tuple(weight*c+shift*a for c, a in zip(line, area)), weight

    def candidates(ci):
        """Rows (vector, kind, payload, length); kind 0 cells, 1 fixed face, 2 power plane."""
        rows, seen, keys = [], {ci}, set()
        def cell(cj):
            if cj not in seen:
                seen.add(cj)
                rows.append((tuple(b-a for a, b in zip(centre[ci], centre[cj])), 0, ((cj, one),)))
        def plane(area, aa, distance, fi):
            # The mirror image of the cell centre in the plane: its temperature
            # differs from the cell's by the prescribed normal derivative alone.
            if distance > 0:
                mirror = tuple(two*distance/aa*a for a in area)
                key = _same(mirror)
                if key not in keys:
                    keys.add(key)
                    rows.append((mirror, 2, (fi, two*distance/(k[ci]*aa))))
        for fi, (area, offset, dk, aa) in local[ci].items():
            if len(incidence[fi]) == 2:
                cj = other(ci, fi)
                if k[cj] == k[ci]:
                    cell(cj)
                else:
                    vector, weight = harmonic(ci, fi)
                    key = (cj, _same(vector))
                    if key not in keys:
                        keys.add(key)
                        rows.append((vector, 0, ((cj, weight),)))
            elif fi in fixed:
                rows.append((offset, 1, fi))
            else:
                plane(area, aa, dk, fi)
        own = len(rows)
        radius = max((norm(r[0]) for r in rows if r[1] != 2), default=0.)
        for cj in neighbours[ci]:
            if k[cj] != k[ci]:
                continue
            shift = tuple(b-a for a, b in zip(centre[ci], centre[cj]))
            for fi, (area, offset, dk, aa) in local[cj].items():
                if len(incidence[fi]) == 2:
                    ck = other(cj, fi)
                    if k[ck] == k[ci]:
                        cell(ck)
                    elif ck != ci:
                        # The neighbour's own harmonic point on its interface: a
                        # convex value of two cells, reached without crossing it.
                        vector, weight = harmonic(cj, fi)
                        vector = tuple(a+b for a, b in zip(shift, vector))
                        key = (cj, ck, _same(vector))
                        if key not in keys:
                            keys.add(key)
                            rows.append((vector, 0, ((cj, one-weight), (ck, weight))))
                elif fi in local[ci]:
                    continue
                elif fi in fixed:
                    rows.append((tuple(a+b for a, b in zip(shift, offset)), 1, fi))
                else:
                    plane(area, aa, dot(area, tuple(a+b for a, b in zip(shift, offset))), fi)
        return [(v, kind, payload, norm(v)) for v, kind, payload in rows], own, radius

    def terms(table, found):
        cell_terms, fixed_terms, plane_terms = {}, {}, {}
        for j, weight in found:
            _, kind, payload, _ = table[j]
            if kind == 0:
                for cj, share in payload:
                    cell_terms[cj] = cell_terms.get(cj, zero)+weight*share
            elif kind == 1:
                fixed_terms[payload] = fixed_terms.get(payload, zero)+weight
            else:
                plane_terms[payload[0]] = plane_terms.get(payload[0], zero)+weight*payload[1]
        return cell_terms, fixed_terms, plane_terms

    def trace(ci, fi, table):
        """Face-centroid temperature as a convex combination about cell ``ci``."""
        offset = local[ci][fi][1]
        reach = dot(offset, offset)
        vectors = [row[0] for row in table]
        # Interpolation remainder of each point about the face centroid, relative
        # to using the cell centre alone; a plane moves along its normal only.
        costs = [float(sum(((a-b)*(a-b) for a, b in zip(row[0], offset)), zero)-reach) if row[1] != 2
                 else row[3]*row[3] for row in table]
        found = _decompose(offset, vectors, costs, bounded=[row[1] != 2 for row in table], lp_support=lp_support)
        return None if found is None else (ci, terms(table, found))

    # The owner whose centre is nearer the face centroid interpolates it.
    preferred = [min(owners, key=lambda item: (dot(local[item[0]][fi][1], local[item[0]][fi][1]), item[0]))[0]
                 for fi, owners in enumerate(incidence)]
    sides = {}                                   # (cell, face) -> (own two-point weight, terms)
    traces = [None]*nf
    statistics = dict(one_sided=0, orthogonal=0, corrected_faces=0, wide_candidates=0,
                      largest_candidate_table=0, trace_second_owner=0, trace_cell_substitutes=0)
    for ci in range(nc):
        _cancel(cancel)
        table = radius = None
        cache = {}
        for fi, (area, offset, dk, aa) in local[ci].items():
            owners = incidence[fi]
            if len(owners) == 1 and fi not in fixed:
                continue
            vector, weight = harmonic(ci, fi) if len(owners) == 2 else (offset, one)
            # Two-point part: the whole conormal magnitude along the line to the
            # harmonic point, k|A|/|v|. Among the classical splittings it is the
            # largest that stays finite when that line is tangent to the face
            # (the over-relaxed k|A|/d_K does not); the minimum-correction
            # projection k d_K|A|/|v|^2 is smaller and under-conducts a limited face.
            alpha = k[ci]*(aa/dot(vector, vector)).sqrt()
            conormal = tuple(k[ci]*a for a in area)
            remainder = tuple(c-alpha*v for c, v in zip(conormal, vector))
            statistics['one_sided'] += 1
            if max(map(abs, remainder)) <= _DEFECT*max(map(abs, conormal)):
                statistics['orthogonal'] += 1
                sides[ci, fi] = (alpha*weight, ({}, {}, {}))
                continue
            if table is None:
                table, own, radius = candidates(ci)
                statistics['wide_candidates'] += len(table)-own
                statistics['largest_candidate_table'] = max(statistics['largest_candidate_table'], len(table))
            vectors = [row[0] for row in table]
            size = norm(remainder)
            key = tuple(round(float(c)/size, 11) for c in remainder)
            found = _certify(remainder, vectors, cache[key]) if key in cache else None
            if found is None and radius:
                # Remainder bound of each difference plus, for a point whose value is
                # an unknown, the size of its weight; the cell's own neighbourhood
                # radius makes the two commensurable. A baseline of that radius is
                # preferred; shorter and longer ones are dearer in proportion.
                costs = [length*length/radius+(0. if kind == 2 else radius) for _, kind, _, length in table]
                found = _decompose(remainder, vectors, costs, lp_support=lp_support)
            if found is None:
                raise TectonicsError('extremum heat has no certified nonnegative flux decomposition for face '+
                                     geometry._face_ids[fi]+' of cell '+geometry.record()['cells'][ci]['cell_id']+
                                     '; this geometry/conductivity/boundary combination is not supported')
            cache[key] = tuple(j for j, _ in found)
            sides[ci, fi] = (alpha*weight, terms(table, found))
        for fi in local[ci]:
            if fi not in fixed and preferred[fi] == ci:
                if table is None:
                    table, own, radius = candidates(ci)
                traces[fi] = trace(ci, fi, table)
    for fi, owners in enumerate(incidence):
        if fi in fixed or traces[fi] is not None:
            continue
        for ci, _ in owners:
            if ci != preferred[fi]:
                _cancel(cancel)
                traces[fi] = trace(ci, fi, candidates(ci)[0])
                statistics['trace_second_owner'] += 1
        if traces[fi] is None:
            # The centroid lies outside every admissible convex combination (for
            # example at the tip of a long thin cell). No bounded, linearly exact
            # value exists there: the entry is the nearer owner's CELL temperature
            # and the face is listed as such, never presented as a centroid value.
            traces[fi] = (preferred[fi], None)
            statistics['trace_cell_substitutes'] += 1
    freeze = lambda group: tuple(tuple(sorted(part.items())) for part in group)
    interior, dirichlet, neumann = [], [], []
    pattern = [set() for _ in range(nc)]
    for fi, owners in enumerate(incidence):
        ci = owners[0][0]
        if len(owners) == 2:
            cj = owners[1][0]
            (own_i, terms_i), (own_j, terms_j) = sides[ci, fi], sides[cj, fi]
            # Equal two-point parts keep the transfer continuous in the temperatures
            # (Droniou 2014, remark 6.2); any excess stays a nonnegative difference.
            shared = min(own_i, own_j)
            if own_i > shared:
                terms_i[0][cj] = terms_i[0].get(cj, zero)+own_i-shared
            if own_j > shared:
                terms_j[0][ci] = terms_j[0].get(ci, zero)+own_j-shared
            if any(terms_i) or any(terms_j):
                statistics['corrected_faces'] += 1
            interior.append((fi, ci, cj, shared, freeze(terms_i), freeze(terms_j)))
            pattern[ci].add(cj); pattern[cj].add(ci)
            for a, group in ((ci, terms_i), (cj, terms_j)):
                for b in group[0]:
                    pattern[a].add(b); pattern[b].add(a)
        elif fi in fixed:
            own_i, terms_i = sides[ci, fi]
            if any(terms_i):
                statistics['corrected_faces'] += 1
            dirichlet.append((fi, ci, own_i, freeze(terms_i)))
            for b in terms_i[0]:
                pattern[ci].add(b); pattern[b].add(ci)
        else:
            neumann.append((fi, ci))
    order = list(range(nc))
    entries = sum(map(len, pattern))
    if entries:
        rows = [i for i, row in enumerate(pattern) for _ in row]
        columns = [j for row in pattern for j in row]
        graph = (sparse.coo_matrix((np.ones(entries), (rows, columns)), shape=(nc, nc))+
                 1000.*sparse.identity(nc)).tocsc()
        # SuperLU's perm_c maps original columns to their new positions. The
        # elimination loops require the inverse: original column at position k.
        permutation = splu(graph, permc_spec='MMD_AT_PLUS_A', diag_pivot_thresh=0.).perm_c
        order = [int(i) for i in np.argsort(permutation)]
    result = _Prepared()
    result.nc, result.nf, result.fixed = nc, nf, fixed
    result.interior, result.dirichlet, result.neumann = tuple(interior), tuple(dirichlet), tuple(neumann)
    result.traces = tuple(None if t is None else (t[0], None if t[1] is None else freeze(t[1])) for t in traces)
    result.order, result.conductivity = tuple(order), tuple(k)
    result.geometry_id = geometry.geometry_id
    result.fill = _symbolic(pattern, order)
    # Every stored support, weight and ordering. A float programme selected the
    # supports, so the record names exactly which stencils produced a result.
    digest = hashlib.sha256(repr((result.interior, result.dirichlet, result.neumann, result.traces,
                                  result.order, result.conductivity)).encode()).hexdigest()
    statistics.update(interior_faces=len(interior), fixed_faces=len(dirichlet), power_faces=len(neumann),
                      pattern_entries=entries, factor_entry_bound=result.fill, stencil_sha256=digest)
    # Wall-clock time is kept beside, never inside, the record that is hashed.
    result.statistics, result.seconds = statistics, perf_counter()-started
    result.bytes = 65536+4096*(len(interior)+len(dirichlet)+nf)+256*entries
    return result


def solve(geometry, conductivity, old, capacity, dt, source, boundary, reference, *,
          budget, cancel=None, prepared=None):
    """One backward-Euler step; never returns an unfinished or out-of-range state.

    ``boundary`` maps exposed face names to ``('temperature', K)`` or
    ``('power', outward watts)``; unnamed exposed faces are insulated. The
    caller owns the native lease, the float-output pairing and the energy gate.
    The iteration is accepted only when the recomputed conservative residual
    meets the existing relative gate and stock-scaled absolute target, and,
    whenever every boundary power is zero, every cell lies within the range of
    the loads ``(E + dt q)/C`` and prescribed temperatures (to within the
    temperature equivalent of that admitted residual).
    """
    if (type(budget) is not WorkBudget or geometry._budget is not budget or
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED):
        raise TectonicsError('changed extremum heat source or mismatched resource')
    nc, nf = len(geometry._cells), len(geometry._incidence)
    names = {name: i for i, name in enumerate(geometry._face_ids)}
    kinds = {}
    for name, entry in boundary.items():
        fi = names.get(name)
        if fi is None or len(geometry._incidence[fi]) != 1:
            raise TectonicsError('thermal boundary must name an actual one-owner face')
        if type(entry) not in (tuple, list) or len(entry) != 2:
            raise TectonicsError('typed thermal boundary pair required')
        if entry[0] not in ('temperature', 'power'):
            raise TectonicsError('thermal boundary must declare temperature or outward power')
        kinds[fi] = entry
    fixed = frozenset(fi for fi, (kind, _) in kinds.items() if kind == 'temperature')
    begin = perf_counter()
    with localcontext() as context:
        context.prec, context.rounding = _PRECISION, ROUND_HALF_EVEN
        if prepared is None:
            with budget.reserve(workspace_bytes(geometry), category='extremum-heat-stencil'):
                prepared = prepare(geometry, conductivity, fixed, budget=budget, cancel=cancel)
        if (type(prepared) is not _Prepared or prepared.geometry_id != geometry.geometry_id or
                prepared.nc != nc or prepared.nf != nf or prepared.fixed != fixed or
                prepared.conductivity != tuple(D.from_float(float(x)) for x in np.broadcast_to(conductivity, (nc,)))):
            raise TectonicsError('prepared extremum stencils belong to another geometry, conductivity or boundary type')
        # Krylov bases, Decimal factors (768 bytes an entry) and state vectors.
        work = 2*1024**2+N.workspace_bytes(nc, _BASIS)+768*prepared.fill+16384*nc+4096*nf
        with budget.reserve(work, category='extremum-heat-work'):
            return _solve(geometry, prepared, old, capacity, dt, source, kinds, reference,
                          cancel=cancel, begin=begin, work=work)


def _solve(geometry, prepared, old_input, capacity_input, dt_input, source_input, kinds, reference_input,
           *, cancel, begin, work):
    zero, two = D(0), D(2)
    decimal = lambda x: D.from_float(float(x))
    norm = lambda values: max(map(abs, values), default=zero)
    nc, nf, order = prepared.nc, prepared.nf, prepared.order
    dt, reference = decimal(dt_input), decimal(reference_input)
    old, capacity = list(map(decimal, old_input)), list(map(decimal, capacity_input))
    source = [decimal(x) for x in np.broadcast_to(source_input, (nc,))]
    if (len(old) != nc or len(capacity) != nc or dt <= 0 or
            any(not x.is_finite() for x in old+capacity+source+[dt, reference]) or
            any(x <= 0 for x in old+capacity)):
        raise TectonicsError('finite positive extremum heat inputs required')
    value = {}
    for fi, (kind, amount) in kinds.items():
        amount = decimal(amount)
        if not amount.is_finite():
            raise TectonicsError('nonfinite thermal boundary value')
        if kind == 'temperature' and amount <= 0:
            raise TectonicsError('absolute boundary temperature must be positive')
        value[fi] = amount
    power = lambda fi: value.get(fi, zero)
    insulated = all(not value[fi] for fi, (kind, _) in kinds.items() if kind == 'power')

    def close(group):
        """A one-sided remainder as cell weights, its fixed-face slope and its constant."""
        cell_terms, fixed_terms, plane_terms = group
        slope = sum((w for _, w in fixed_terms), zero)
        constant = (sum((w*power(fi) for fi, w in plane_terms), zero)-
                    sum((w*value[fi] for fi, w in fixed_terms), zero))
        return cell_terms, slope, constant
    faces = [(ci, cj, shared, close(a), close(b)) for _, ci, cj, shared, a, b in prepared.interior]
    fixed_faces = [(ci, own, value[fi], close(group)) for fi, ci, own, group in prepared.dirichlet]
    load = [e+dt*q for e, q in zip(old, source)]
    for fi, ci in prepared.neumann:
        load[ci] -= dt*power(fi)

    def remainder(u, ci, group):
        cell_terms, slope, constant = group
        own = u[ci]
        total = slope*own+constant
        for cj, weight in cell_terms:
            total += weight*(own-u[cj])
        return total

    def evaluate(u):
        """Remainder pairs, the ONE transfer of every face, and the conservative residual."""
        pairs, transfers, outward = [], [], []
        residual = [c*x-b for c, x, b in zip(capacity, u, load)]
        for ci, cj, shared, a, b in faces:
            gi, gj = remainder(u, ci, a), remainder(u, cj, b)
            flow = shared*(u[ci]-u[cj])+_limited(gi, gj)
            pairs.append((gi, gj)); transfers.append(flow)
            residual[ci] += dt*flow; residual[cj] -= dt*flow
        for ci, own, fixed_value, group in fixed_faces:
            flow = own*(u[ci]-fixed_value)+remainder(u, ci, group)
            outward.append(flow)
            residual[ci] += dt*flow
        return pairs, transfers, outward, residual

    def picard(pairs):
        """Row-dominant M-matrix of the frozen-weight forms, its row sums and right-hand side."""
        off = [dict() for _ in range(nc)]
        sums, rhs = list(capacity), list(load)
        def row(ci, factor, group):
            cell_terms, slope, constant = group
            target = off[ci]
            for cj, weight in cell_terms:
                target[cj] = target.get(cj, zero)+factor*weight
            sums[ci] += factor*slope
            rhs[ci] -= factor*constant
        for (ci, cj, shared, a, b), (gi, gj) in zip(faces, pairs):
            amount = dt*shared
            off[ci][cj] = off[ci].get(cj, zero)+amount
            off[cj][ci] = off[cj].get(ci, zero)+amount
            if (gi > 0 and gj < 0) or (gi < 0 and gj > 0):
                total = abs(gi)+abs(gj)
                row(ci, two*dt*abs(gj)/total, a)
                row(cj, two*dt*abs(gi)/total, b)
        for ci, own, fixed_value, group in fixed_faces:
            sums[ci] += dt*own
            rhs[ci] += dt*own*fixed_value
            row(ci, dt, group)
        return off, sums, rhs

    def jacobian(pairs):
        """Action of the derivative of the conservative residual at this state."""
        active = []
        for (ci, cj, shared, a, b), (gi, gj) in zip(faces, pairs):
            if (gi > 0 and gj < 0) or (gi < 0 and gj > 0):
                total = abs(gi)+abs(gj)
                mi, mj = abs(gj)/total, abs(gi)/total
                active.append((ci, cj, shared, two*mi*mi, a, two*mj*mj, b))
            else:
                active.append((ci, cj, shared, None, None, None, None))
        def linear(x, ci, group):
            cell_terms, slope, _ = group
            own = x[ci]
            total = slope*own
            for cj, weight in cell_terms:
                total += weight*(own-x[cj])
            return total
        def action(x):
            _cancel(cancel)
            result = [c*v for c, v in zip(capacity, x)]
            for ci, cj, shared, wi, a, wj, b in active:
                flow = shared*(x[ci]-x[cj])
                if wi is not None:
                    flow += wi*linear(x, ci, a)-wj*linear(x, cj, b)
                flow *= dt
                result[ci] += flow; result[cj] -= flow
            for ci, own, _, group in fixed_faces:
                result[ci] += dt*(own*x[ci]+linear(x, ci, group))
            return result
        return action

    offset_load = [b-c*reference for b, c in zip(load, capacity)]
    rhs_max = norm(offset_load)
    # The existing stock-scaled target counts the unknowns of the hybrid system:
    # cells and faces without a prescribed temperature. The same count is kept
    # here, so this method's absolute target is not looser for having fewer unknowns.
    free = nc+nf-len(prepared.fixed)
    target = min(_GATE*rhs_max, _GATE*min(old)/free) if rhs_max else _GATE*min(old)/free
    limits = None
    if insulated:
        loads = [b/c for b, c in zip(load, capacity)]+[value[fi] for fi in prepared.fixed]
        limits = (min(loads), max(loads))
        if limits[0] <= 0:
            raise TectonicsError('positive backward-Euler temperature bounds required')

    def judge(u, residual):
        absolute = norm(residual)
        scale = max(rhs_max, norm([r+b for r, b in zip(residual, offset_load)]))
        relative = absolute/scale if scale else zero
        # At the coldest cell every transfer is inward, so its temperature is at
        # least its load minus its own residual over its capacity; likewise above.
        slack = max((abs(r)/c for r, c in zip(residual, capacity)), default=zero)
        inside = min(u) > 0 and (limits is None or (min(u) >= limits[0]-slack and max(u) <= limits[1]+slack))
        return absolute, relative, slack, inside, absolute <= target and relative <= _GATE

    def forcing(absolute):
        return min(D('.1'), max(D(10)**(8-_PRECISION), (absolute/max(rhs_max, absolute)).sqrt()))

    u = [e/c for e, c in zip(old, capacity)]
    pairs, transfers, outward, residual = evaluate(u)
    absolute, relative, slack, inside, done = judge(u, residual)
    history, entries = [str(absolute)], 0
    counts = dict(picard=0, newton=0, newton_rejected=0, eliminations=0, krylov=0, refinements=0)
    # Intermediate iterates are never issued. How far an accepted one lay outside
    # the declared range, and how exactly each bounded step was solved, is recorded.
    outside = lambda state: zero if limits is None else max(limits[0]-min(state), max(state)-limits[1], zero)
    excursion, linear_defect = dict(bounded_steps=zero, newton_steps=zero), zero
    # The furthest outside the declared range that any ACCEPTABLE final state could
    # lie: the temperature equivalent of the residual target in the smallest cell.
    allowance = target/min(capacity)
    while not done:
        _cancel(cancel)
        if counts['picard']+counts['newton'] >= _LIMIT:
            raise TectonicsError('extremum heat did not converge within its bounded iteration limit; '
                                 'last absolute residual '+str(absolute))
        # A bounded step: the frozen-weight system is a row-dominant M-matrix, so
        # its solution cannot leave the range of its loads and fixed temperatures.
        # The iterate is that solution to within the recorded linear defect.
        off, sums, rhs = picard(pairs)
        factor = _eliminate([{j: float(v) for j, v in row.items()} for row in off],
                            list(map(float, sums)), order, cancel)
        entries = max(entries, factor[3])
        counts['eliminations'] += 1
        x = _substitute(factor, rhs, order)
        passes = 0
        while True:
            _cancel(cancel)
            defect = [b-s*x[i]-sum((v*(x[i]-x[j]) for j, v in off[i].items()), zero)
                      for i, (b, s) in enumerate(zip(rhs, sums))]
            if norm(defect) <= target/1000 or passes == 8:
                break
            x = [a+b for a, b in zip(x, _substitute(factor, defect, order))]
            passes += 1
            counts['refinements'] += 1
        linear_defect = max(linear_defect, norm(defect))
        u = x
        pairs, transfers, outward, residual = evaluate(u)
        absolute, relative, slack, inside, done = judge(u, residual)
        counts['picard'] += 1
        history.append(str(absolute))
        excursion['bounded_steps'] = max(excursion['bounded_steps'], outside(u))
        # Newton trials use these factors as their preconditioner. A trial is
        # kept only if its inner solve converged, every temperature stays
        # positive, the conservative residual at least halves and, where a range
        # is declared, no cell lies further outside it than an acceptable final
        # state could. A small residual alone does not show that: a cell of
        # negligible capacity can be far out of range and barely change it.
        # Otherwise the next bounded step follows.
        while not done and counts['picard'] >= _PICARD_START and counts['picard']+counts['newton'] < _LIMIT:
            _cancel(cancel)
            direction = N.gmres(jacobian(pairs), lambda y: _substitute(factor, y, order), [-r for r in residual],
                                cancel=cancel, max_basis=_BASIS, max_restarts=_RESTARTS,
                                relative_target=forcing(absolute))
            counts['krylov'] += direction['iterations']
            trial = [a+b for a, b in zip(u, direction['solution'])]
            found = evaluate(trial)
            verdict = judge(trial, found[3])
            if not (direction['converged'] and verdict[3] and outside(trial) <= allowance and
                    2*verdict[0] <= absolute):
                counts['newton_rejected'] += 1
                break
            u, (pairs, transfers, outward, residual) = trial, found
            absolute, relative, slack, inside, done = verdict
            counts['newton'] += 1
            history.append(str(absolute))
            excursion['newton_steps'] = max(excursion['newton_steps'], outside(u))
        del factor
    if not inside:
        raise TectonicsError('converged extremum heat state lies outside its positive backward-Euler temperature bounds')
    # Face-centroid temperatures: certified convex combinations about one owner.
    traces = [zero]*nf
    for fi, entry in enumerate(prepared.traces):
        if entry is None:
            traces[fi] = value[fi]
            continue
        ci, group = entry
        own = u[ci]
        if group is None:
            traces[fi] = own
            continue
        cell_terms, fixed_terms, plane_terms = group
        total = own
        for cj, weight in cell_terms:
            total += weight*(u[cj]-own)
        for fj, weight in fixed_terms:
            total += weight*(value[fj]-own)
        for fj, weight in plane_terms:
            total -= weight*power(fj)
        traces[fi] = total
    # With zero boundary power every face value is a convex combination of cell
    # and prescribed temperatures and shares their bounds. A declared power
    # shifts its own face value by the prescribed normal derivative; that value
    # is reported as computed and, like the hybrid-mimetic face value, is not a gate.
    if limits is not None and (min(traces) < limits[0]-slack or max(traces) > limits[1]+slack):
        raise TectonicsError('extremum heat face-centroid temperature lies outside its bounds')
    raw = [[] for _ in range(nf)]
    exact_raw = [[] for _ in range(nf)]
    def book(fi, ci, amount):
        for cell, sign in geometry._incidence[fi]:
            signed = amount if cell == ci else -amount
            raw[fi].append((cell, sign, float(signed)))
            exact_raw[fi].append((cell, sign, str(signed)))
    for (fi, ci, *_), flow in zip(prepared.interior, transfers):
        book(fi, ci, dt*flow)
    for (fi, ci, *_), flow in zip(prepared.dirichlet, outward):
        book(fi, ci, dt*flow)
    for fi, ci in prepared.neumann:
        book(fi, ci, dt*power(fi))
    agree = lambda gi, gj: (gi > 0 and gj < 0) or (gi < 0 and gj > 0)
    limited = sum(1 for gi, gj in pairs if (gi or gj) and not agree(gi, gj))
    active = sum(1 for gi, gj in pairs if agree(gi, gj))
    # The counts include remainders at rounding level where the temperature is
    # uniform. These shares weigh each face by the heat it moves instead.
    moved = sum(map(abs, transfers), zero)
    dropped = sum((abs(flow) for flow, (gi, gj) in zip(transfers, pairs) if (gi or gj) and not agree(gi, gj)), zero)
    kept = sum((abs(_limited(gi, gj)) for gi, gj in pairs), zero)
    shares = dict(limited_decimal=str(dropped/moved if moved else zero),
                  kept_correction_decimal=str(kept/moved if moved else zero),
                  meaning='of the summed absolute interior face transfers: the part on faces whose two remainders '
                          'disagree, which use the two-point part alone; and the summed absolute kept corrections')
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
        raise TectonicsError('extremum heat source changed during solve')
    N.assert_current()
    _cancel(cancel)
    solution = [x-reference for x in u]+[t-reference for t in traces]
    stencil = dict(prepared.statistics)
    return dict(solution=np.asarray(list(map(float, solution))),
        absolute_temperature=np.asarray(list(map(float, u+traces))),
        enthalpy=np.asarray([float(c*x) for c, x in zip(capacity, u)]), raw=raw,
        iterations=counts['picard']+counts['newton'], linear_relative=float(relative),
        rhs_norm=float(sum((b*b for b in offset_load), zero).sqrt()),
        rhs_max=float(max(rhs_max, norm([r+b for r, b in zip(residual, offset_load)]))),
        statistics=dict(seconds=perf_counter()-begin, stencil_seconds=prepared.seconds),
        evidence=dict(schema='atlas.extremum-heat-decimal80.v1', source_sha256=_LOADED, scheme=SCHEME,
            precision=_PRECISION, rounding='ROUND_HALF_EVEN; exact binary input conversion',
            equation='cell storage plus one shared transfer per face; two-point part plus harmonic-limited '
                     'two-sided remainder with certified nonnegative weights; recomputed-state transfer',
            time_method='backward Euler on current capacities',
            residual_absolute_decimal=str(absolute), residual_relative_decimal=str(relative),
            absolute_target_decimal=str(target),
            internal_target='min(original relative target, ALGEBRA*minimum positive old cell enthalpy/free unknowns '
                            'of the hybrid system: cells plus faces without a prescribed temperature)',
            temperature_bounds_decimal=None if limits is None else [str(limits[0]), str(limits[1])],
            bounds_rule=('range of (E + dt q)/C and prescribed face temperatures, to within max|residual|/C'
                         if limits is not None else 'not claimed: a boundary power is nonzero'),
            bounds_satisfied=bool(inside), bound_slack_kelvin_decimal=str(slack),
            nonlinear=dict(counts, limit=_LIMIT, residual_history_decimal=history, lower_factor_entries=entries,
                iteration='bounded frozen-weight M-matrix steps, then Newton trials kept only when the inner '
                          'solve converged, every temperature stays positive and no further outside a declared '
                          'range than the residual target allows, and the conservative residual at least halves',
                range_allowance_kelvin_decimal=None if limits is None else str(allowance),
                largest_range_excursion_kelvin_decimal=None if limits is None else
                    {key: str(value) for key, value in excursion.items()},
                bounded_step_linear_defect_decimal=str(linear_defect),
                elimination='subtraction-free binary64 factors applied and refined in Decimal'),
            corrected_faces=stencil['corrected_faces'], limited_faces=limited, active_faces=active,
            transfer_shares=shares, stencil=stencil, decomposition_defect_bound_decimal=str(_DEFECT),
            face_temperature='certified convex combination at the face centroid about one owner; prescribed '
                             'value on fixed-temperature faces; where no such combination exists the entry is '
                             'the nearer owner\'s cell temperature and the face index is listed below',
            face_temperature_cell_substitutes=[fi for fi, entry in enumerate(prepared.traces)
                                               if entry is not None and entry[1] is None],
            solution_offset_decimal=list(map(str, solution)), raw_outward_energy_decimal=exact_raw,
            reference_decimal=str(reference), work_admitted_bytes=work))
