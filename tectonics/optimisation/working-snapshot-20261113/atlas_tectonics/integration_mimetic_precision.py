"""Precision successor for the unchanged HMM bilinear form.

Decimal80 retains the affine cancellations of exact positive thin cells. The
rounded sparse factor is only a preconditioner: its derived assembly-error
diagonal is NEVER added to the solved heat equation or reported face flux.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import ExitStack
from decimal import Decimal as D, ROUND_HALF_EVEN, localcontext
from fractions import Fraction as Q
import hashlib
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu

from ._validation import TectonicsError
from .integration_regional_inventory import _width
from .regional_heat3d import _cancel
from .regional_multigrid3d import _native_factor_bytes
from .resources import MemoryLimitError, WorkBudget
from . import integration_mimetic_newton as N
from . import _mimetic_newton_factor as J

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_PRECISION = 80
_GATE = D('1e-11')
# The preconditioned iteration gives way to a factorisation in rounded
# Decimal80 arithmetic when its best residual has not halved in this many
# iterations; the rounding of that factor is removed by at most this many
# refinements.
_STAGNATION = 32
_DIRECT_REFINEMENTS = 4
_NONLINEAR_LIMIT = 128


def solve_monotone(geometry, conductivity, old, capacity, dt, source, boundary,
                   reference, initial, *, budget, cancel=None, method='scheme2'):
    """Experimental nonlinear HMM solve; never accept an unfinished iterate.

    This is a different consistent discretisation, not more precision applied
    to the original form. Its active correction can lower spatial order. The
    caller must explicitly record this route; existing admissible HMM solves
    are left alone. Scheme 2 supports zero power only; the KSS adaptations
    additionally support positive prescribed temperatures. Nonzero prescribed
    power remains outside every nonlinear fallback.
    """
    if method not in ('scheme2', 'kss', 'bounded-kss'):
        raise TectonicsError('unknown nonlinear HMM method')
    if method != 'scheme2':
        from . import integration_mimetic_limiter as L
    if any(not (kind == 'power' and value == 0 or
                method != 'scheme2' and kind == 'temperature' and value > 0)
           for kind, value in boundary.values()):
        raise TectonicsError('nonlinear HMM repair requires insulated (zero power) or method-supported positive fixed temperature')
    if np.any(np.asarray(old)+float(dt)*np.broadcast_to(source, np.shape(old)) <= 0):
        raise TectonicsError('nonlinear HMM repair requires positive backward-Euler heat load')
    if (type(budget) is not WorkBudget or geometry._budget is not budget or
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED):
        raise TectonicsError('changed precision source or mismatched HMM resource')
    size = len(geometry._cells)+len(geometry._incidence)
    incidences = sum(len(row[2]) for row in geometry._cells)
    entries = sum((len(row[2])+1)**2 for row in geometry._cells)
    # Retain the immutable Decimal geometry and uncorrected blocks only for
    # this call. Admission precedes their first construction; the unchanged
    # per-iteration allowance conservatively still covers transient work.
    base_bytes = 1024**2+4*_width(geometry._cells)+1024*incidences+320*entries+8192*size
    started = perf_counter()
    with budget.reserve(32768*size+1024**2, category='mimetic-nonlinear-work'), \
            budget.reserve(base_bytes, category='mimetic-nonlinear-base'), ExitStack() as retained, \
            localcontext() as context:
        if method != 'scheme2':
            retained.enter_context(budget.reserve(L.workspace_bytes(geometry), category='mimetic-limiter-base'))
        context.prec = _PRECISION
        context.rounding = ROUND_HALF_EVEN
        base = {}
        iterate = list(map(D, initial))
        history = []
        residuals = []
        iteration_history = []
        for iteration in range(_NONLINEAR_LIMIT):
            _cancel(cancel)
            result = _solve_with_base(geometry, conductivity, old, capacity, dt, source, boundary,
                           reference, budget=budget, cancel=cancel, correction_at=iterate,
                           correction_history=history, base=base, initial_low_order=(iteration == 0), method=method)
            evidence = result['evidence']
            nonlinear = evidence['nonlinear']
            iteration_history.append(dict(nonlinear))
            residuals.append(nonlinear['residual_absolute_decimal'])
            following = list(map(D, evidence['solution_offset_decimal']))
            if nonlinear['converged']:
                ref = D(evidence['reference_decimal'])
                if any(value+ref <= 0 for value in following):
                    raise TectonicsError('converged nonlinear HMM has a nonpositive cell or face temperature')
                if method == 'bounded-kss':
                    lower, upper = base['limiter_bounds']
                    if any(not lower <= value <= upper for value in following):
                        raise TectonicsError('converged bounded-KSS state violates its discrete backward-Euler temperature bounds')
                    nonlinear['discrete_bounds_satisfied'] = True
                evidence['nonlinear'].update(method=('Le Potier--Mahamane 2012 Scheme 2; nu=1' if method == 'scheme2'
                    else 'Kuzmin--Shashkov--Svyatskiy 2009 Eq59/61/63; HMM '+method+' adaptation'),
                    iterations=iteration+1, limit=_NONLINEAR_LIMIT,
                    residual_history_decimal=residuals, elapsed_seconds=perf_counter()-started,
                    iteration_history=iteration_history,
                    iteration_method='positive graph initial guess; safeguarded Newton-GMRES and residual mixing',
                    activation='original HMM returned a nonpositive cell or face temperature',
                    scope='explicit final positivity and unchanged residual gates; zero power or supported fixed temperature',
                    accuracy=('consistent nonlinear correction; no second-order claim while active' if method == 'scheme2'
                        else 'gradient-recovered symmetric flux limiter; active accuracy requires mesh-family controls'),
                    base_reuse='immutable Decimal geometry and base blocks retained for this solve only',
                    base_admitted_bytes=base_bytes)
                return result
            history.append((following, list(map(D, result['nonlinear_residual_decimal']))))
            history = history[-6:]
            iterate = list(map(D, result['next_nonlinear_offset_decimal']))
    raise TectonicsError('nonlinear HMM did not converge within its bounded iteration limit; '
                         'last absolute residual '+residuals[-1])


def _mix(history):
    """Small residual-mixing least-squares solve with no state clipping."""
    if len(history) == 1:
        return history[-1][0]
    zero, one = D(0), D(1)
    last = history[-1][1]
    differences = [[a-b for a, b in zip(row[1], last)] for row in history[:-1]]
    dot = lambda a, b: sum((x*y for x, y in zip(a, b)), zero)
    matrix = [[dot(a, b) for b in differences]+[-dot(a, last)] for a in differences]
    n = len(matrix)
    for k in range(n):
        at = max(range(k, n), key=lambda i: abs(matrix[i][k]))
        if not matrix[at][k]:
            return history[-1][0]
        matrix[k], matrix[at] = matrix[at], matrix[k]
        pivot = matrix[k][k]
        matrix[k] = [x/pivot for x in matrix[k]]
        for i in range(n):
            if i != k:
                weight = matrix[i][k]
                matrix[i] = [a-weight*b for a, b in zip(matrix[i], matrix[k])]
    weights = [row[-1] for row in matrix]
    weights.append(one-sum(weights, zero))
    # Large extrapolations are unnecessary for bounded acceleration. Falling
    # back to Picard changes only work, not the accepted nonlinear solution.
    if any(not x.is_finite() for x in weights) or sum(map(abs, weights)) > D(10):
        return history[-1][0]
    return [sum((w*row[0][i] for w, row in zip(weights, history)), zero)
            for i in range(len(last))]


def _face_preconditioner(kn, nv, gamma, offsets, mv):
    """Evaluate each coefficient of the symmetric HMM form once.

    The two expanded expressions are equal in exact arithmetic, but swapped
    subtraction/contraction orders can round differently even at Decimal80.
    This is assembly of a known symmetric form, not averaging an asymmetric
    equation. The matrix-free heat action below remains independent.
    """
    zero = D(0)
    dot = lambda a, b: sum((x*y for x, y in zip(a, b)), zero)
    m = len(gamma)
    block = [[zero]*m for _ in range(m)]
    for i in range(m):
        for j in range(i, m):
            value = (dot(kn[i], nv[j])+(gamma[i] if i == j else zero)
                -gamma[i]*dot(offsets[i], nv[j])-gamma[j]*dot(offsets[j], nv[i])
                +dot(nv[i], mv[j]))
            block[i][j] = block[j][i] = value
    return block


def _cell_block(offsets, nv, kn, gamma):
    """Return one cell's symmetric block: its own row, then one per face.

    The preconditioner and the direct factor both take their coefficients
    from this single evaluation order, so they assemble the same form.
    """
    zero = D(0)
    moment = [[sum((gam*x[a]*x[b] for gam, x in zip(gamma, offsets)), zero)
               for b in range(3)] for a in range(3)]
    mv = [[sum((moment[a][b]*v[b] for b in range(3)), zero) for a in range(3)] for v in nv]
    # The exact HMM face block, evaluated at the same precision as action.
    block_faces = _face_preconditioner(kn, nv, gamma, offsets, mv)
    edge = [-sum(row, zero) for row in block_faces]
    block = [[-sum(edge, zero), *edge]]
    block += [[edge[i], *row] for i, row in enumerate(block_faces)]
    return block


def _symmetric_triangle(rows, columns, values, size):
    """Sum each global upper-triangle location once, then copy off-diagonals."""
    upper = sparse.coo_matrix((values, (rows, columns)), shape=(size, size)).tocsr()
    return upper+sparse.triu(upper, k=1, format='csr').T


def _factor_fill(above):
    """Count the strictly lower entries of the L D L^T of a symmetric pattern.

    ``above[k]`` lists the rows i < k that hold a coefficient (i, k), with the
    unknowns numbered in elimination order. This is the symbolic elimination:
    the elimination tree first, then each factor row as the tree branches
    from its coefficients up to its own column. It needs three integer lists
    of the pattern's order and creates no factor entry, so the fill is known
    before the memory it needs is reserved.
    """
    size = len(above)
    parent, ancestor = [size]*size, [size]*size
    for k, rows in enumerate(above):
        for i in rows:
            # Follow the compressed path to the root of the subtree; that
            # root becomes a child of column k.
            while i < k:
                following = ancestor[i]
                ancestor[i] = k
                if following == size:
                    parent[i] = k
                i = following
    fill, reached = 0, list(range(size))
    for k, rows in enumerate(above):
        for i in rows:
            while reached[i] != k:
                reached[i] = k
                fill += 1
                i = parent[i]
    return fill


def _local_faces(values, entry):
    """Original HMM face action, without any nonlinear correction."""
    zero = D(0)
    dot = lambda a, b: sum((x*y for x, y in zip(a, b)), zero)
    ci, indexes, _, _, offsets, nv, kn, gamma = entry
    differences = [values[j]-values[ci] for j in indexes]
    gradient = [sum((v[a]*d for v, d in zip(nv, differences)), zero) for a in range(3)]
    residual = [gam*(d-dot(x, gradient)) for gam, d, x in zip(gamma, differences, offsets)]
    moment = [sum((x[a]*r for x, r in zip(offsets, residual)), zero) for a in range(3)]
    return [dot(k, gradient)+r-dot(v, moment) for k, r, v in zip(kn, residual, nv)]


def _correction(local, values, fixed):
    """Le Potier--Mahamane (2012), Scheme 2, nu=1.

    Repeated face--face edges keep their cell multiplicity in BOTH the
    denominator and the local correction. Only differences enter this scheme,
    so the temperature-reference shift is immaterial. Fixed rows are not PDE
    equations and have zero ratio. This is not a universal boundary DMP claim.
    """
    zero = D(0)
    force, denominator = [zero]*len(values), [zero]*len(values)
    for entry in local:
        ci, indexes = entry[:2]
        flux = _local_faces(values, entry)
        force[ci] -= sum(flux, zero)
        for j, f in zip(indexes, flux):
            force[j] += f
        ids = [ci, *indexes]
        for i, a in enumerate(ids):
            for b in ids[i+1:]:
                difference = abs(values[a]-values[b])
                denominator[a] += difference
                denominator[b] += difference
    ratio = [abs(f)/d if d and i not in fixed else zero
             for i, (f, d) in enumerate(zip(force, denominator))]
    return [[(i, j, ratio[a]+ratio[b])
             for i, a in enumerate([entry[0], *entry[1]])
             for j, b in enumerate([entry[0], *entry[1]]) if i < j]
            for entry in local]


def _corrected_faces(values, entry, edges):
    flux = _local_faces(values, entry)
    if edges:
        ids = [entry[0], *entry[1]]
        for i, j, weight in edges:
            amount = weight*(values[ids[i]]-values[ids[j]])
            if i:
                flux[i-1] += amount
            flux[j-1] -= amount
    return flux


def _corrected_block(entry, edges, base=None):
    block = (_cell_block(entry[4], entry[5], entry[6], entry[7]) if base is None else
             [list(row) for row in base])
    for i, j, weight in edges:
        block[i][i] += weight; block[j][j] += weight
        block[i][j] -= weight; block[j][i] -= weight
    return block


def solve(geometry, conductivity, old, capacity, dt, source, boundary, reference,
          *, budget, cancel=None, correction_at=None, correction_history=()):
    """Return the actual same-form solve and once-evaluated outward face heat.

    The caller owns its existing native operation/lease and final float-output,
    paired-flux, temperature and energy gates. This helper additionally checks
    a recomputed Decimal residual against a physical-stock-scaled absolute
    target. Failure is visible; there is no altered-operator fallback.

    When the best residual of the preconditioned iteration has not halved in
    ``_STAGNATION`` iterations, the same form is factored and solved directly.
    That factor is computed in rounded 80-digit Decimal arithmetic, not
    exactly, and is refined on the matrix-free residual at most
    ``_DIRECT_REFINEMENTS`` times. The rule looks only at the residual, so a
    solve that converges slowly, and that the iteration alone would complete,
    can take the factor instead: its result meets the same two residual gates
    and its evidence carries ``direct_factor``. When the budget does not admit
    the factor, the iteration continues unaltered to its limit of twice the
    unknowns, and the solve is refused only if that also fails. The plan
    descriptor's ``linear_method`` does not mention the factor: the evidence
    of each advance, not the plan, names it.
    """
    return _solve_with_base(geometry, conductivity, old, capacity, dt, source, boundary,
                           reference, budget=budget, cancel=cancel, correction_at=correction_at,
                           correction_history=correction_history, base=None)


def _solve_with_base(geometry, conductivity, old, capacity, dt, source, boundary, reference,
                     *, budget, cancel, correction_at, correction_history, base, initial_low_order=False,
                     method='scheme2'):
    """Internal iteration entry; only solve_monotone owns a retained base."""
    if (type(budget) is not WorkBudget or geometry._budget is not budget or
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED):
        raise TectonicsError('changed precision source or mismatched HMM resource')
    nc, nf = len(geometry._cells), len(geometry._incidence)
    n = nc+nf
    incidences = sum(len(row[2]) for row in geometry._cells)
    entries = sum((len(row[2])+1)**2 for row in geometry._cells)
    metric_width = _width(geometry._cells)
    # Decimal80 payloads, pointer/tuple/vector workspace, exact input conversion,
    # simultaneous local block/COO construction, and returned encoded offsets.
    work_bytes = 2*1024**2+4*metric_width+1024*incidences+320*entries+8192*n
    if correction_at is not None:
        work_bytes += 1024*entries+4096*n
    with budget.reserve(work_bytes, category='mimetic-decimal-work'), ExitStack() as stack, localcontext() as context:
        context.prec = _PRECISION
        context.rounding = ROUND_HALF_EVEN
        return _solve(geometry, conductivity, old, capacity, dt, source, boundary,
                      reference, budget=budget, stack=stack, cancel=cancel,
                      work_bytes=work_bytes, correction_at=correction_at,
                      correction_history=correction_history, base=base, initial_low_order=initial_low_order, method=method)


def _solve(geometry, conductivity, old_input, capacity_input, dt_input, source_input,
           boundary, reference_input, *, budget, stack, cancel, work_bytes, correction_at=None,
           correction_history=(), base=None, initial_low_order=False, method='scheme2'):
    begin = perf_counter()
    zero, one = D(0), D(1)
    decimal = lambda x: D.from_float(float(x))
    exact = lambda q: D(q.numerator)/D(q.denominator)
    dot = lambda a, b: sum((x*y for x, y in zip(a, b)), zero)
    norm = lambda x: max(map(abs, x), default=zero)
    nc, nf = len(geometry._cells), len(geometry._incidence)
    size = nc+nf
    dt, reference = decimal(dt_input), decimal(reference_input)
    old, capacity = list(map(decimal, old_input)), list(map(decimal, capacity_input))
    source = [decimal(x) for x in np.broadcast_to(source_input, (nc,))]
    conductivity = [decimal(x) for x in np.broadcast_to(conductivity, (nc,))]
    if (len(old) != nc or len(capacity) != nc or dt <= 0 or
            any(not x.is_finite() for x in old+capacity+source+conductivity+[dt, reference]) or
            any(x <= 0 for x in old+capacity+conductivity)):
        raise TectonicsError('finite positive precision HMM inputs required')
    initial = [e-c*reference for e, c in zip(old, capacity)]
    rr, cc, vv = [], [], []
    row_abs, row_count = [zero]*size, [0]*size
    if base:
        _cancel(cancel)
        if base['geometry'] is not geometry or base['conductivity'] != tuple(conductivity):
            raise TectonicsError('nonlinear HMM geometry or conductivity changed during base reuse')
        local, base_blocks = base['local'], base['blocks']
    else:
        local, base_blocks = [], None
        for ci, (vq, _, faces, signs, xq, nq, distanceq) in enumerate(geometry._cells):
            _cancel(cancel)
            volume, k = exact(vq), conductivity[ci]
            normals = [tuple(map(exact, v)) for v in nq]
            offsets = [tuple(map(exact, x)) for x in xq]
            nv = [tuple(exact(a/vq) for a in v) for v in nq]
            kn = [tuple(k*a for a in v) for v in normals]
            gamma = [k*exact(sum(a*a for a in v)/d) for v, d in zip(nq, distanceq)]
            indexes = [nc+j for j in faces]
            local.append((ci, indexes, signs, normals, offsets, nv, kn, gamma))
        if base is not None:
            local = tuple((entry[0], *(tuple(values) for values in entry[1:])) for entry in local)
            base_blocks = []
            for entry in local:
                _cancel(cancel)
                block = _cell_block(entry[4], entry[5], entry[6], entry[7])
                base_blocks.append(tuple(map(tuple, block)))
            base_blocks = tuple(base_blocks)
            base.update(geometry=geometry, conductivity=tuple(conductivity),
                        local=local, blocks=base_blocks)
    correction_fixed = {nc+geometry._face_ids.index(name) for name, (kind, _) in boundary.items()
                        if kind == 'temperature'}
    limiter = None
    if correction_at is not None and method != 'scheme2':
        from . import integration_mimetic_limiter as L
        limiter_identity = L.assert_current()
        if base is None or base_blocks is None:
            raise TectonicsError('KSS correction requires its admitted call-local base')
        limits = None
        if method == 'bounded-kss':
            loads = [(e+dt*s)/c for e, s, c in zip(old, source, capacity)]
            loads += [decimal(value) for kind, value in boundary.values() if kind == 'temperature']
            if min(loads) <= 0:
                raise TectonicsError('positive exact backward-Euler temperature bounds required')
            limits = (min(loads)-reference, max(loads)-reference)
        if 'limiter' not in base:
            base['limiter'] = L.prepare(geometry, local, base_blocks, correction_fixed, cancel=cancel, bounds=limits)
            base['limiter_fixed'] = frozenset(correction_fixed)
            base['limiter_bounds'] = limits
        if base['limiter_fixed'] != correction_fixed or base['limiter_bounds'] != limits:
            raise TectonicsError('KSS fixed rows changed during prepared reuse')
        limiter = base['limiter']
    def correction(values):
        return (_correction(local, values, correction_fixed) if limiter is None else
                limiter.corrections(values))
    if correction_at is None:
        corrections = [[] for _ in local]
    else:
        correction_at = list(map(D, correction_at))
        if len(correction_at) != size or any(not x.is_finite() for x in correction_at):
            raise TectonicsError('finite complete nonlinear HMM iterate required')
        if initial_low_order:
            # A positive graph solve supplies only the starting iterate. Its
            # extra diffusion is NOT part of the accepted nonlinear equation:
            # below, acceptance and returned flux are recomputed using the
            # nonlinear operator, with unchanged final residual gates.
            corrections = []
            for at, entry in enumerate(local):
                block = (base_blocks[at] if base_blocks is not None else
                         _cell_block(entry[4], entry[5], entry[6], entry[7]))
                corrections.append([(i, j, max(zero, block[i][j]))
                    for i in range(len(block)) for j in range(i+1, len(block))])
        else:
            corrections = correction(correction_at)
    for at, (entry, edges) in enumerate(zip(local, corrections)):
        ci, indexes = entry[:2]
        block = _corrected_block(entry, edges, None if base_blocks is None else base_blocks[at])
        ids = [ci, *indexes]
        for i, gi in enumerate(ids):
            for j in range(i, len(ids)):
                gj = ids[j]
                value = dt*block[i][j]
                rr.append(min(gi, gj)); cc.append(max(gi, gj)); vv.append(float(value))
                row_abs[gi] += abs(value); row_count[gi] += 1
                if gi != gj:
                    row_abs[gj] += abs(value); row_count[gj] += 1
    for i, cap in enumerate(capacity):
        rr.append(i); cc.append(i); vv.append(float(cap))
        row_abs[i] += abs(cap); row_count[i] += 1

    calls = 0
    def action(values):
        nonlocal calls
        _cancel(cancel)
        calls += 1
        result = [zero]*size
        for entry, edges in zip(local, corrections):
            ci, indexes = entry[:2]
            flux = _corrected_faces(values, entry, edges)
            result[ci] = capacity[ci]*values[ci]-dt*sum(flux, zero)
            for j, f in zip(indexes, flux):
                result[j] += dt*f
        return result

    rhs = [e+dt*s for e, s in zip(initial, source)]+[zero]*nf
    face_ids = {name: i for i, name in enumerate(geometry._face_ids)}
    fixed = {}
    for name, (kind, value) in boundary.items():
        fi = face_ids.get(name)
        if fi is None or len(geometry._incidence[fi]) != 1:
            raise TectonicsError('precision HMM boundary must be an actual exposed face')
        value = decimal(value)
        if not value.is_finite():
            raise TectonicsError('nonfinite precision HMM boundary')
        if kind == 'temperature' and value > 0:
            fixed[nc+fi] = value-reference
        elif kind == 'power':
            rhs[nc+fi] -= dt*value
        else:
            raise TectonicsError('typed positive temperature or outward power required')
    free = [j for j in range(size) if j not in fixed]
    fixed_u = [fixed.get(j, zero) for j in range(size)]
    afixed = action(fixed_u)
    reduced_rhs = [rhs[j]-afixed[j] for j in free]
    rhs_max = norm(reduced_rhs)
    absolute_target = min(_GATE*rhs_max, _GATE*min(old)/len(free)) if rhs_max else _GATE*min(old)/len(free)
    approximate = _symmetric_triangle(rr, cc, vv, size)
    del rr, cc, vv, block
    asymmetry = approximate-approximate.T
    if asymmetry.nnz and np.any(asymmetry.data != 0):
        raise TectonicsError('precision preconditioner lost symmetric assembly')
    unit = D(2)**-53
    shifts = [D(count+1)*unit/(one-D(count+1)*unit)*a for a, count in zip(row_abs, row_count)]
    old_diag = approximate.diagonal()
    approximate.setdiag(np.nextafter(old_diag+np.asarray(list(map(float, shifts))), np.inf))
    reduced = approximate[free][:, free].tocsc()
    del approximate, row_abs, row_count, asymmetry
    scales = np.sqrt(reduced.diagonal())
    if not np.isfinite(scales).all() or np.any(scales <= 0):
        raise TectonicsError('unrepresentable precision preconditioner scaling')
    # Reuse the existing native-LU allocation model: initial fill30 input,
    # growth24 bytes/realised entry, and1024 bytes/unknown. This is explicit
    # accounted admission, not an allocator/RSS cap; realised fill is checked.
    fill_envelope = min(len(free)*(len(free)+1), 30*reduced.nnz)
    factor_allowance = 1024**2+_native_factor_bytes(len(free), reduced.nnz, fill_envelope)
    stack.enter_context(budget.reserve(factor_allowance, category='mimetic-decimal-factor'))
    scaling = sparse.diags(1/scales, format='csc')
    normalised = (scaling@reduced@scaling).tocsc()
    _cancel(cancel)
    try:
        factor = splu(normalised, permc_spec='MMD_AT_PLUS_A', diag_pivot_thresh=0.,
                      options=dict(SymmetricMode=True))
    except RuntimeError as exc:
        raise TectonicsError('precision HMM preconditioner factor failed') from exc
    factor_nnz = factor.L.nnz+factor.U.nnz
    realised = 1024**2+_native_factor_bytes(len(free), reduced.nnz, factor_nnz)
    if realised > factor_allowance:
        raise MemoryLimitError('precision HMM realised factor fill exceeds admitted envelope')
    if np.any(factor.U.diagonal() <= 0):
        raise TectonicsError('precision HMM preconditioner has nonpositive pivots')
    decimal_scales = list(map(decimal, scales))
    def precondition(values):
        _cancel(cancel)
        weighted = [a/b for a, b in zip(values, decimal_scales)]
        magnitude = norm(weighted)
        if not magnitude:
            return [zero]*len(values)
        answer = factor.solve(np.asarray([float(a/magnitude) for a in weighted]))
        if not np.isfinite(answer).all():
            raise TectonicsError('nonfinite precision HMM preconditioner action')
        return [decimal(a)*magnitude/b for a, b in zip(answer, decimal_scales)]
    def reduced_action(values):
        expanded = [zero]*size
        for j, value in zip(free, values):
            expanded[j] = value
        full = action(expanded)
        return [full[j] for j in free]
    def direct_form():
        """Assemble the same form in the rounded factor's order and count its fill.

        The first reservation is sized from the cell blocks before a
        coefficient exists, the second from the counted fill before a fill
        entry exists. A refusal of either returns both to the budget.
        """
        pairs = sum((len(entry[1])+1)*(len(entry[1])+2)//2 for entry in local)
        # 512 bytes per Decimal80 coefficient and its dictionary slot; 1024
        # bytes per unknown for its position, pivot, column and pattern row.
        coefficient_bytes = 1024**2+1024*len(free)+512*pairs
        with ExitStack() as held:
            held.enter_context(budget.reserve(coefficient_bytes, category='mimetic-decimal-direct'))
            position = {j: int(factor.perm_c[k]) for k, j in enumerate(free)}
            diagonal, columns = [zero]*len(free), [{} for _ in free]
            for at, (entry, edges) in enumerate(zip(local, corrections)):
                _cancel(cancel)
                ci, indexes = entry[:2]
                block = _corrected_block(entry, edges, None if base_blocks is None else base_blocks[at])
                ids = [position.get(j) for j in (ci, *indexes)]
                for i, a in enumerate(ids):
                    for j in range(i, len(ids)):
                        b = ids[j]
                        if a is None or b is None:
                            continue
                        value = dt*block[i][j]
                        if a == b:
                            diagonal[a] += value
                        else:
                            low, high = min(a, b), max(a, b)
                            columns[low][high] = columns[low].get(high, zero)+value
            for ci, cap in enumerate(capacity):
                diagonal[position[ci]] += cap
            # A coefficient that is exactly zero couples nothing. The rounded
            # factor chose its order without it; kept, it would fill.
            above = [[] for _ in free]
            for low, column in enumerate(columns):
                for high in [i for i, value in column.items() if not value]:
                    del column[high]
                for high in column:
                    above[high].append(low)
            fill = _factor_fill(above)
            del above
            # 512 bytes per stored factor entry; 1024 bytes per unknown for
            # the column being scaled and the substitution vectors.
            factor_bytes = 1024*len(free)+512*fill
            held.enter_context(budget.reserve(factor_bytes, category='mimetic-decimal-direct'))
            stack.enter_context(held.pop_all())
        return position, diagonal, columns, fill, coefficient_bytes+factor_bytes
    guess = [e/c-reference for e, c in zip(old, capacity)]
    guess += [sum((guess[ci] for ci, _ in owners), zero)/len(owners) for owners in geometry._incidence]
    if correction_at is not None:
        guess = correction_at
    x = [guess[j] for j in free]
    ax = reduced_action(x)
    r = [b-a for b, a in zip(reduced_rhs, ax)]
    z = precondition(r)
    direction, rz = z[:], dot(r, z)
    prepared = perf_counter()
    iterations, converged = 0, False
    limit = 2*size
    best, improved = norm(r), 0
    form, give_way = None, True
    while iterations < limit:
        if 2*norm(r) <= best:
            best, improved = norm(r), iterations
        if norm(r) <= absolute_target:
            ax = reduced_action(x)
            true_r = [b-a for b, a in zip(reduced_rhs, ax)]
            if norm(true_r) <= absolute_target:
                r, converged = true_r, True
                break
            r = true_r
            z = precondition(r)
            direction, rz = z[:], dot(r, z)
        # The newest residual has been judged for halving and convergence
        # above, so a solve that converges on its last permitted iteration
        # leaves there and never here.
        if give_way and (iterations-improved >= _STAGNATION or
                         (correction_at is not None and iterations == 0)):
            try:
                form = direct_form()
                break
            except MemoryLimitError:
                # The budget does not admit the factor. The iteration carries
                # on unaltered to its own limit, as it does without this rule.
                give_way = False
        ad = reduced_action(direction)
        denominator = dot(direction, ad)
        if denominator <= 0 or not denominator.is_finite():
            raise TectonicsError('precision HMM nonpositive PCG curvature')
        alpha = rz/denominator
        x = [a+alpha*b for a, b in zip(x, direction)]
        r = [a-alpha*b for a, b in zip(r, ad)]
        z = precondition(r)
        next_rz = dot(r, z)
        beta = next_rz/rz
        direction = [a+beta*b for a, b in zip(z, direction)]
        rz = next_rz
        iterations += 1
    direct = None
    if not converged:
        # The rounded factor carries an assembly-error diagonal. A cell whose
        # capacity is below it, yet thermally almost isolated, is a nearly
        # singular mode that the preconditioned iteration cannot resolve: its
        # residual stops improving far above a target scaled by the smallest
        # cell. The SAME symmetric form, its coefficients evaluated as for the
        # preconditioner, is then factored as L D L^T in 80-digit Decimal
        # arithmetic (every operation rounds: the factor is not exact), in the
        # fill order of the rounded factor, and solved directly. At most
        # _DIRECT_REFINEMENTS refinements on the matrix-free residual remove
        # the Decimal factor's own rounding. The equation and both residual
        # gates are unchanged.
        if form is None:
            # The iteration ended at its limit: without the factor nothing
            # is left, so a refused reservation is the refusal.
            form = direct_form()
        position, diagonal, columns, fill, direct_bytes = form
        # Entries are counted as the elimination creates them, so the factor
        # is refused at the first one beyond the count it was admitted for.
        stored = sum(map(len, columns))
        for k, column in enumerate(columns):
            _cancel(cancel)
            pivot = diagonal[k]
            if pivot <= 0 or not pivot.is_finite():
                raise TectonicsError('precision HMM Decimal80 direct factor lost positive definiteness '
                                     '(rounded pivot <= 0 or not finite)')
            rows = sorted(column)
            scaled = {i: column[i]/pivot for i in rows}
            for at, j in enumerate(rows):
                weight = column[j]
                diagonal[j] -= scaled[j]*weight
                target = columns[j]
                stored -= len(target)
                for i in rows[at+1:]:
                    target[i] = target.get(i, zero)-scaled[i]*weight
                stored += len(target)
                if stored > fill:
                    raise MemoryLimitError('precision HMM realised direct factor fill exceeds admitted count')
            columns[k] = scaled
        direct_nnz = sum(map(len, columns))
        order = [position[j] for j in free]
        def direct_solve(values):
            y = [zero]*len(free)
            for value, k in zip(values, order):
                y[k] = value
            for k, column in enumerate(columns):
                if y[k]:
                    for i, weight in column.items():
                        y[i] -= weight*y[k]
            y = [a/d for a, d in zip(y, diagonal)]
            for k in range(len(columns)-1, -1, -1):
                y[k] -= sum((weight*y[i] for i, weight in columns[k].items()), zero)
            return [y[k] for k in order]
        x = direct_solve(reduced_rhs)
        refinements = 0
        while True:
            _cancel(cancel)
            ax = reduced_action(x)
            r = [b-a for b, a in zip(reduced_rhs, ax)]
            if norm(r) <= absolute_target or refinements == _DIRECT_REFINEMENTS:
                break
            x = [a+b for a, b in zip(x, direct_solve(r))]
            refinements += 1
        converged = norm(r) <= absolute_target
        direct = dict(method='Decimal80 (rounded) LDL^T of the same symmetric form, coefficients evaluated as for '
                             'the preconditioner, in the rounded factor order; refinement on the matrix-free residual',
                      iterations_before=iterations, lower_factor_nnz=direct_nnz, refinements=refinements,
                      admitted_bytes=direct_bytes)
    ax = reduced_action(x)
    absolute = norm([a-b for a, b in zip(ax, reduced_rhs)])
    scale = max(rhs_max, norm(ax))
    relative = absolute/scale if scale else zero
    if not converged or relative > _GATE or absolute > absolute_target:
        raise TectonicsError('precision HMM did not meet original relative and stock-scaled absolute residual gates')
    solution = fixed_u[:]
    for j, value in zip(free, x):
        solution[j] = value
    nonlinear = None
    if correction_at is not None:
        # Recompute from the returned state, not the frozen input iterate.
        # The next action and reported flux belong to this ACTUAL nonlinear
        # state. No iterate-change tolerance can replace this residual check.
        corrections = correction(solution)
        true_action = action(solution)
        true_residual = [true_action[j]-rhs[j] if j not in fixed else zero for j in range(size)]
        true_absolute = norm(true_residual)
        true_fixed = action(fixed_u)
        true_scale = max(norm([rhs[j]-true_fixed[j] for j in free]),
                         norm([true_action[j]-true_fixed[j] for j in free]))
        true_relative = true_absolute/true_scale if true_scale else zero
        nonlinear = dict(residual_absolute_decimal=str(true_absolute),
            residual_relative_decimal=str(true_relative),
            positive_graph_initial_guess=initial_low_order,
            converged=bool(true_absolute <= absolute_target and true_relative <= _GATE))
        if limiter is not None:
            nonlinear['limiter_source_sha256'] = limiter_identity
            nonlinear['limiter_gamma_evaluation'] = dict(limiter.gamma_statistics)
            geometry_bounds = [g for edge in limiter.graph for g in (edge.gamma_i, edge.gamma_j) if g is not None]
            nonlinear['limiter_edges'] = len(limiter.graph)
            nonlinear['zero_geometry_bounds'] = sum(g == 0 for g in geometry_bounds)
            nonlinear['geometry_bound_min_decimal'] = str(min(geometry_bounds, default=zero))
            nonlinear['a_priori_temperature_bounds_decimal'] = (
                list(map(str, (value+reference for value in limits))) if limits is not None else None)
        next_iterate = solution
        if not nonlinear['converged']:
            # Newton changes only the iteration, not the selected equation.
            # Its inexact inner target is never used for heat acceptance.
            # Compare every proposal against the better of the input and the
            # frozen-coefficient solve, so an unsuccessful Picard update does
            # not silently increase the merit function.
            actual_corrections = corrections
            corrections = correction(correction_at)
            input_action = action(correction_at)
            input_residual = [input_action[j]-rhs[j] if j not in fixed else zero for j in range(size)]
            if not initial_low_order and dot(input_residual, input_residual) < dot(true_residual, true_residual):
                next_iterate, best_residual = correction_at, input_residual
            else:
                best_residual = true_residual
            best_merit = dot(best_residual, best_residual)
            corrections = actual_corrections
            try:
                with budget.reserve(N.workspace_bytes(size), category='mimetic-newton-direction'):
                    helper_identity = N.assert_current()
                    derivative = (N.prepare_scheme2_derivative(local, next_iterate,
                        correction_fixed, local_faces=_local_faces, cancel=cancel) if limiter is None else
                        limiter.derivative(next_iterate))
                    def jacobian(values):
                        expanded = [zero]*size
                        for j, value in zip(free, values):
                            expanded[j] = value
                        diffusion = derivative(expanded)
                        if limiter is not None:
                            for entry in local:
                                flux = _local_faces(expanded, entry)
                                diffusion[entry[0]] -= sum(flux, zero)
                                for j, value in zip(entry[1], flux):
                                    diffusion[j] += value
                        return [(capacity[j]*expanded[j] if j < nc else zero)+dt*diffusion[j]
                                for j in free]
                    # A vanishing inexact-Newton forcing term avoids a fixed
                    # ten-percent linear-convergence tail near the much
                    # stricter physical acceptance target. This controls work
                    # only; every proposed state is tested on the true action.
                    forcing = min(D('.1'), (norm(best_residual)/max(rhs_max, norm(best_residual))).sqrt())
                    def newton_direction(selected):
                        fallback = direct_solve if direct is not None else precondition
                        load = [-best_residual[j] for j in free]
                        if limiter is None or limiter.bounds is None:
                            return N.gmres(jacobian, fallback, load, cancel=cancel,
                                           max_restarts=1, relative_target=forcing)
                        def sources():
                            N.assert_current(); L.assert_current()
                        return J.solve_direction(local, base_blocks, capacity, dt, free, size,
                            selected.active_coefficients, action=jacobian, rhs=load,
                            relative_target=forcing, budget=budget, fallback=fallback,
                            source_check=sources, cancel=cancel, permutation=factor.perm_c,
                            symbolic_fill=_factor_fill)
                    direction = newton_direction(derivative)
                    nonlinear['newton'] = {k: v for k, v in direction.items() if k != 'solution'}
                    nonlinear['newton']['source_sha256'] = helper_identity
                    origin = next_iterate
                    def propose(values, record):
                        """One direction, bounded search, true-action merit only."""
                        nonlocal corrections, next_iterate, best_merit
                        expanded = [zero]*size
                        for j, value in zip(free, values):
                            expanded[j] = value
                        adjacent = None
                        def check(step):
                            nonlocal corrections, next_iterate, best_merit
                            _cancel(cancel)
                            trial = [a+step*b for a, b in zip(origin, expanded)]
                            corrections = correction(trial)
                            trial_action = action(trial)
                            residual = [trial_action[j]-rhs[j] if j not in fixed else zero
                                        for j in range(size)]
                            merit = dot(residual, residual)
                            if merit < best_merit:
                                next_iterate, best_merit = trial, merit
                                record.update(accepted_step_decimal=str(step),
                                              proposal_residual_decimal=str(norm(residual)))
                                return True
                            return False
                        for power in range(24):
                            if check(D(2)**-power):
                                return True, adjacent, expanded
                            if power == 0 and limiter is not None and limiter.bounds is not None:
                                base_direction = [(capacity[j]*expanded[j] if j < nc else zero)
                                                  for j in range(size)]
                                for entry in local:
                                    flux = _local_faces(expanded, entry)
                                    base_direction[entry[0]] -= dt*sum(flux, zero)
                                    for j, value in zip(entry[1], flux):
                                        base_direction[j] += dt*value
                                search = L.event_line_search(limiter, origin, expanded,
                                    best_residual, base_direction, dt, budget=budget,
                                    fixed=fixed, cancel=cancel)
                                record['event_line_search'] = {
                                    k: str(v) if isinstance(v, D) else v for k, v in search.items()}
                                adjacent = search['adjacent_step_ratio']
                                if search['step'] and check(search['step']):
                                    return True, adjacent, expanded
                        return False, adjacent, expanded
                    accepted, adjacent, expanded = propose(direction['solution'], nonlinear['newton'])
                    if adjacent is not None and (not accepted or (
                            best_merit > D(direction['target_norm_decimal'])**2 and
                            limiter.matches_derivative(next_iterate, derivative.active_coefficients))):
                        # ONE alternative Jacobian from the exact next affine
                        # region. Solve the SAME origin residual; the region
                        # point is never accepted as a heat state. Reuse the
                        # existing factor and workspace, and never recurse.
                        # A partial update within the SAME selected affine
                        # branch can repeat the same stalled Newton line.
                        # Compare an adjacent proposal even after tiny gains,
                        # unless the primary meets the existing inner target
                        # or changes the actual rounded-state selection.
                        # The latter gives the next iteration a new J.
                        # Shared best_merit preserves a better primary; this
                        # work policy changes no physical acceptance gate.
                        del direction, derivative
                        derivative = limiter.derivative(origin, line_direction=expanded,
                                                        line_step=Q(*adjacent), budget=budget)
                        direction = newton_direction(derivative)
                        alternative = {k: v for k, v in direction.items() if k != 'solution'}
                        alternative.update(source_sha256=helper_identity, region_step_ratio=adjacent,
                            origin='unchanged primary Newton origin; no uphill state accepted', maximum_attempts=1)
                        nonlinear['newton']['adjacent_branch'] = alternative
                        propose(direction['solution'], alternative)
                    N.assert_current()
                    del derivative, jacobian, direction, propose, newton_direction
            except MemoryLimitError:
                nonlinear['newton'] = dict(admitted=False)
            corrections = actual_corrections
            proposal = _mix([*correction_history[-5:], (solution, true_residual)])
            # Nonlinear residual mixing, not mixing unweighted Kelvin defects
            # dominated by nearly massless face modes. Backtracking is on the
            # actual equation residual and accepts only strict improvement.
            # No positivity clipping; final physical gates remain unchanged.
            for divisor in (1, 2, 4, 8):
                trial = [a+(b-a)/D(divisor) for a, b in zip(solution, proposal)]
                corrections = correction(trial)
                trial_action = action(trial)
                trial_residual = [trial_action[j]-rhs[j] for j in free]
                trial_norm = norm(trial_residual)
                trial_merit = dot(trial_residual, trial_residual)
                if trial_merit < best_merit:
                    next_iterate = trial
                    best_merit = trial_merit
                    nonlinear['mixing_residual_decimal'] = str(trial_norm)
                    break
            corrections = actual_corrections
    enthalpy = [c*(u+reference) for c, u in zip(capacity, solution)]
    raw = [[] for _ in range(nf)]
    exact_raw = [[] for _ in range(nf)]
    for entry, edges in zip(local, corrections):
        flux = _corrected_faces(solution, entry, edges)
        for j, sign, f in zip(entry[1], entry[2], flux):
            amount = -dt*f
            raw[j-nc].append((entry[0], sign, float(amount)))
            exact_raw[j-nc].append((entry[0], sign, str(amount)))
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
        raise TectonicsError('precision HMM source changed during solve')
    if limiter is not None:
        L.assert_current()
    _cancel(cancel)
    return dict(solution=np.asarray(list(map(float, solution))),
        absolute_temperature=np.asarray([float(u+reference) for u in solution]),
        **({} if nonlinear is None else dict(
            nonlinear_residual_decimal=list(map(str, true_residual)),
            next_nonlinear_offset_decimal=list(map(str, next_iterate)))),
        enthalpy=np.asarray(list(map(float, enthalpy))), raw=raw,
        iterations=iterations, linear_relative=float(relative),
        rhs_norm=float(dot(reduced_rhs, reduced_rhs).sqrt()), rhs_max=float(scale),
        statistics=dict(preparation_seconds=prepared-begin, solve_seconds=perf_counter()-prepared),
        evidence=dict(schema='atlas.mimetic-decimal80.v1', source_sha256=_LOADED,
            precision=_PRECISION, rounding='ROUND_HALF_EVEN; exact binary input conversion',
            equation=('unchanged HMM matrix-free factor action' if correction_at is None else
                      'HMM with conservative '+method+' nonlinear correction; recomputed-state flux')+
                     '; paired flux evaluated before float projection',
            **({} if nonlinear is None else dict(nonlinear=nonlinear)),
            solution_offset_decimal=list(map(str, solution)), raw_outward_energy_decimal=exact_raw,
            reference_decimal=str(reference), residual_absolute_decimal=str(absolute),
            residual_relative_decimal=str(relative), absolute_target_decimal=str(absolute_target),
            internal_target='min(original relative target, ALGEBRA*minimum positive old cell enthalpy/free unknowns)',
            preconditioner='same-form paired Decimal coefficients; one global triangle mirrored after duplicate sum; assembly gamma_n row-error diagonal, not a PDE change',
            preconditioner_shift_max_decimal=str(max(shifts)),
            preconditioner_nnz=int(reduced.nnz), factor_nnz=int(factor_nnz),
            factor_admitted_bytes=factor_allowance, factor_realised_accounted_bytes=realised,
            work_admitted_bytes=work_bytes, matvecs=calls, max_iterations=limit,
            # Present only when the direct factorisation was used.
            **({} if direct is None else dict(direct_factor=direct))))
