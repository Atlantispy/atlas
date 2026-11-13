"""Experimental Decimal80 KSS2009 Eq59/61/63 adaptation for hybrid HMM.

The paper's finite-element gradient recovery is replaced by exact HMM cell
gradients and volume-weighted adjacent-cell face gradients. An insulated
exposed face uses the tangent projection of its own planar normal. This is
not validation for arbitrary cut cells or a claim of general accuracy/DMP.
Source: https://doi.org/10.1016/j.jcp.2009.01.031

The caller must reserve workspace_bytes(geometry) before prepare and retain
the reservation until the prepared helper and its derived actions are gone.
This is allocation accounting, not a hard RSS cap; caller-owned geometry,
Decimal base blocks, factors and the Newton Krylov basis are excluded.
Nonzero Neumann data are outside this helper's boundary model and must be
refused by its caller. Source, geometry and boundary identity remain owned by
that caller. No global result cache is constructed.
SPDX-License-Identifier: AGPL-3.0-only
"""
from collections import namedtuple
from concurrent.futures import CancelledError
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, localcontext, getcontext
from fractions import Fraction as Q
import hashlib
from pathlib import Path
from .resources import WorkBudget, MemoryLimitError
from . import _mimetic_enclosure as _gamma


_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
# The dependency supplies its own load-time source identity; the owner checks
# that same loaded identity before and after the full preparation/solve.
_GAMMA_LOADED = _gamma.assert_current()
_ZERO_VECTOR = (Q(0),)*3
_Edge = namedtuple('_Edge', 'i j d gamma_i gamma_j shares')


def assert_current():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
        raise ValueError('KSS limiter source changed during solve')
    if _gamma.assert_current() != _GAMMA_LOADED:
        raise ValueError('certified gamma dependency changed during solve')
    return _LOADED


def _cancel(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel()):
        raise CancelledError('KSS limiter work cancelled')


def _dot(a, b):
    return sum((x*y for x, y in zip(a, b)), Q(0))


def _vector(values, size):
    result = tuple(map(D, values))
    if len(result) != size or any(not value.is_finite() for value in result):
        raise ValueError('finite complete KSS state or direction required')
    return result


def _partition_nonnegative(target, weights, cancel=None):
    """Partition one Decimal80 coefficient without a rounded last remainder.

    All parts use the target's 80-digit quantum. Every partial sum then has
    at most 80 digits and is exact, including the final target-minus-used.
    An upward-rounded total and downward ratio/product put every provisional
    part below its exact proportional ideal, so the remainder is nonnegative.
    This changes local proportional allocation only by rounding; the exact
    global target, and thus its global correction/Jacobian, are unchanged.

    Unlike exact Fraction allocation, working precision/storage do not grow
    with the span between arbitrary Decimal exponents. A positive tiny part
    can round to zero. No returned state or global coefficient is clipped.
    """
    _cancel(cancel)
    if not target.is_finite() or target < 0 or not weights:
        raise ValueError('finite nonnegative target and nonempty weights required')
    with localcontext() as context:
        context.prec, context.rounding = 80, ROUND_HALF_EVEN
        if +target != target:
            raise ValueError('exactly representable Decimal80 partition target required')
        for value in weights:
            _cancel(cancel)
            if not value.is_finite() or value < 0:
                raise ValueError('finite nonnegative partition weights required')
        zero = D(0)
        if not target:
            return (zero,)*len(weights)
        if len(weights) == 1:
            if not weights[0]:
                raise ValueError('positive partition weight required for positive target')
            return (target,)
        context.rounding = ROUND_CEILING
        total = zero
        for value in weights:
            _cancel(cancel)
            total += value
        if not total:
            raise ValueError('positive partition weight required for positive target')
        # Etiny also covers representable subnormal targets. Constructing
        # the quantum from a tuple does not allocate an exponent-sized int.
        quantum = D((0, (1,), max(target.adjusted()-79, context.Etiny())))
        context.rounding = ROUND_FLOOR
        parts, used = [], zero
        for value in weights[:-1]:
            _cancel(cancel)
            part = ((value/total)*target).quantize(quantum)
            parts.append(part)
            used += part
        remainder = target-used
        if remainder < 0:
            raise ValueError('Decimal80 partition lost nonnegativity')
        parts.append(remainder)
        used += remainder
        if used != target:
            raise ValueError('Decimal80 partition lost its exact global coefficient')
        _cancel(cancel)
        return tuple(parts)


def _shape(value):
    """Unreduced rational bit bounds; zero is represented explicitly."""
    return (abs(value.numerator).bit_length(), value.denominator.bit_length())


def _shape_add(a, b):
    if not a[0]:
        return b
    if not b[0]:
        return a
    return max(a[0]+b[1], b[0]+a[1])+1, a[1]+b[1]


def _shape_mul(a, b):
    return (a[0]+b[0], a[1]+b[1]) if a[0] and b[0] else (0, 1)


def _shape_div(a, b):
    return (a[0]+b[1], a[1]+b[0]) if a[0] else (0, 1)


def _shape_bytes(value):
    # CPython 30-bit limbs: 48-byte Fraction, two 28-byte integer bases,
    # plus 32 bytes for allocation alignment/overhead. This overcounts zero
    # and shared small integers. This payload bound is not an RSS guarantee.
    return 136+4*((value[0]+29)//30+(value[1]+29)//30)


def _shape_dot(a, b):
    result = (0, 1)
    for x, y in zip(a, b):
        result = _shape_add(result, _shape_mul(x, y))
    return result


def workspace_breakdown(geometry):
    """Phase-aware admission for streamed exact recovery.

    Integer bounds follow unreduced rational +, *, /; gcd cancellation can
    only shrink the result. Coordinates/normals and cell rows are retained,
    but only one face row and its projected successor coexist. The largest
    accumulator/product gets a separate 16-object arithmetic scratch charge,
    all rational storage receives x4 allocator/intermediate headroom, and
    unchanged generous pair/node allowances cover graph/actions/containers.

    This is still accounted admission, not an operating-system memory cap.
    Caller geometry, Decimal base/factors/Krylov work remain separately owned.
    The shape preflight retains at most one sparse face row (integer metadata).
    """
    cells, incidence = geometry._cells, geometry._incidence
    size = len(cells)+len(incidence)
    pairs = sum((len(row[2])+1)*len(row[2])//2 for row in cells)
    support = sum(len(row[2]) for row in cells)
    face_support = sum(sum(len(cells[ci][2]) for ci, _ in owners) for owners in incidence)
    rational_retained = 0
    delta = [(0, 1)]*3
    cell_scratch = (0, 1)
    for volume, centre, _, _, offsets, normals, _ in cells:
        v = _shape(volume)
        for offset, normal in zip(offsets, normals):
            for axis, (c, x, n) in enumerate(zip(centre, offset, normal)):
                coordinate = _shape_add(_shape(c), _shape(x))
                normal_shape = _shape_mul(_shape(n), (1, 1))
                coefficient = _shape_div(_shape(n), v)
                rational_retained += sum(map(_shape_bytes, (coordinate, normal_shape, coefficient)))
                delta[axis] = (max(delta[axis][0], coordinate[0]),
                               max(delta[axis][1], coordinate[1]))
        # Constant-row checking is also a rational sum, even if it cancels.
        for axis in range(3):
            value = (0, 1)
            for normal in normals:
                value = _shape_add(value, _shape_div(_shape(normal[axis]), v))
            if _shape_bytes(value) > _shape_bytes(cell_scratch):
                cell_scratch = value
    delta = tuple(_shape_add(shape, shape) for shape in delta)
    max_face, max_scratch = 0, _shape_bytes(cell_scratch)
    # Cell-row mu bounds use a common worst coordinate delta. This avoids
    # building pair adjacency before its reservation has been admitted.
    for volume, _, _, _, _, normals, _ in cells:
        mu = (0, 1)
        for normal in normals:
            vector = tuple(_shape_div(_shape(q), _shape(volume)) for q in normal)
            term = _shape_dot(vector, delta)
            mu = _shape_add(mu, term)
            max_scratch = max(max_scratch, _shape_bytes(term), _shape_bytes(mu))
    for owners in incidence:
        denominator = (0, 1)
        for ci, _ in owners:
            denominator = _shape_add(denominator, _shape(cells[ci][0]))
        row = {}
        for ci, _ in owners:
            volume, _, faces, _, _, normals, _ = cells[ci]
            weight = _shape_div(_shape(volume), denominator)
            for fi, normal in zip(faces, normals):
                before = row.get(fi, ((0, 1),)*3)
                vector = tuple(_shape_div(_shape(q), _shape(volume)) for q in normal)
                row[fi] = tuple(_shape_add(a, _shape_mul(weight, b))
                                for a, b in zip(before, vector))
        old_bytes = sum(_shape_bytes(q) for vector in row.values() for q in vector)
        if len(owners) == 1:
            ci, sign = owners[0]
            # Exactly one cell contains this face. The normal-specific shape
            # is bounded by the componentwise maximum over its face normals.
            normals = cells[ci][5]
            normal = tuple((max(_shape(v[a])[0] for v in normals)+1,
                            max(_shape(v[a])[1] for v in normals)+1) for a in range(3))
            squared = _shape_dot(normal, normal)
            projected = {}
            for k, vector in row.items():
                dot = _shape_dot(vector, normal)
                projected[k] = tuple(_shape_add(a, _shape_div(_shape_mul(dot, b), squared))
                                     for a, b in zip(vector, normal))
                max_scratch = max(max_scratch, _shape_bytes(dot), _shape_bytes(squared),
                                  *(_shape_bytes(q) for q in projected[k]))
            row = projected
        new_bytes = sum(_shape_bytes(q) for vector in row.values() for q in vector)
        max_face = max(max_face, old_bytes+new_bytes)
        for axis in range(3):
            value = (0, 1)
            for vector in row.values():
                value = _shape_add(value, vector[axis])
            max_scratch = max(max_scratch, _shape_bytes(value))
        mu = (0, 1)
        for vector in row.values():
            term = _shape_dot(vector, delta)
            mu = _shape_add(mu, term)
            max_scratch = max(max_scratch, _shape_bytes(term), _shape_bytes(mu))
    rational = 4*(rational_retained+max_face+16*max_scratch)
    result = dict(rational_retained_bound=rational_retained,
                  two_face_rows_bound=max_face,
                  arithmetic_object_bound=max_scratch,
                  rational_with_headroom=rational,
                  graph_and_actions=4096*8*pairs,
                  node_containers=4096*16*size,
                  cell_support_containers=4096*support,
                  neighbour_containers=128*(face_support+2*pairs+size),
                  fixed_allowance=2*1024**2)
    result['total'] = sum(result[k] for k in (
        'rational_with_headroom', 'graph_and_actions', 'node_containers',
        'cell_support_containers', 'neighbour_containers', 'fixed_allowance'))
    return result


def workspace_bytes(geometry):
    return workspace_breakdown(geometry)['total']


def _recovery_cells(geometry, cancel, *, raw=False):
    """Retain exact cell rows or raw normal numerators with the same support."""
    cells, incidence = geometry._cells, geometry._incidence
    nc, nf = len(cells), len(incidence)
    coords = [tuple(row[1]) for row in cells]+[None]*nf
    operators = []
    face_normals = [None]*nf
    for ci, (volume, centre, faces, signs, offsets, normals, _) in enumerate(cells):
        _cancel(cancel)
        coeff = {}
        for fi, sign, offset, normal in zip(faces, signs, offsets, normals):
            at = nc+fi
            position = tuple(a+b for a, b in zip(centre, offset))
            global_normal = tuple(sign*a for a in normal)
            if coords[at] is not None and (coords[at] != position or face_normals[fi] != global_normal):
                raise ValueError('inconsistent exact KSS face geometry')
            coords[at], face_normals[fi] = position, global_normal
            coeff[at] = tuple(normal) if raw else tuple(a/volume for a in normal)
        operators.append(coeff)
    return coords, operators, face_normals


def _face_recovery(geometry, fi, fixed, cell_operators, face_normals):
    cells, incidence = geometry._cells, geometry._incidence
    nc = len(cells)
    owners = incidence[fi]
    if not owners:
        raise ValueError('unowned exact KSS face')
    denominator = sum((cells[ci][0] for ci, _ in owners), Q(0))
    coeff = {}
    for ci, _ in owners:
        weight = cells[ci][0]/denominator
        for k, vector in cell_operators[ci].items():
            before = coeff.get(k, _ZERO_VECTOR)
            coeff[k] = tuple(a+weight*b for a, b in zip(before, vector))
    if len(owners) == 1 and nc+fi not in fixed:
        normal = face_normals[fi]
        squared = _dot(normal, normal)
        coeff = {k: tuple(a-_dot(vector, normal)*b/squared for a, b in zip(vector, normal))
                 for k, vector in coeff.items()}
    return {k: vector for k, vector in coeff.items() if any(vector)}


def _raw_face_recovery(geometry, fi, fixed, cell_normals, face_normals):
    """Raw numerator row, positive common volume and optional tangent plane.

    The exact cancellation (V_i/sum(V))*N_i/V_i = N_i/sum(V) is performed
    before materialising any recovered coefficient. Tangent-null vectors
    are removed by their exact cross product, preserving old neighbour keys.
    """
    cells, incidence = geometry._cells, geometry._incidence
    nc = len(cells)
    owners = incidence[fi]
    if not owners:
        raise ValueError('unowned exact KSS face')
    denominator = sum((cells[ci][0] for ci, _ in owners), Q(0))
    if denominator <= 0:
        raise ValueError('positive exact KSS common volume required')
    coeff = {}
    for ci, _ in owners:
        for k, normal in cell_normals[ci].items():
            before = coeff.get(k, _ZERO_VECTOR)
            coeff[k] = tuple(a+b for a, b in zip(before, normal))
    tangent, squared = None, None
    if len(owners) == 1 and nc+fi not in fixed:
        tangent = face_normals[fi]
        squared = _dot(tangent, tangent)
        if not squared:
            raise ValueError('nonzero exact KSS face normal required')
        def survives(vector):
            return any((vector[1]*tangent[2]-vector[2]*tangent[1],
                        vector[2]*tangent[0]-vector[0]*tangent[2],
                        vector[0]*tangent[1]-vector[1]*tangent[0]))
        coeff = {k: vector for k, vector in coeff.items() if survives(vector)}
    else:
        coeff = {k: vector for k, vector in coeff.items() if any(vector)}
    return coeff, denominator, tangent, squared


def prepare(geometry, local, base_blocks, fixed, cancel=None, bounds=None):
    """Form the identical graph with streamed raw-normal recovery and exact mu."""
    assert_current()
    _cancel(cancel)
    nc, nf = len(geometry._cells), len(geometry._incidence)
    size, zero = nc+nf, D(0)
    fixed = frozenset(fixed)
    if bounds is not None:
        bounds = _vector(bounds, 2)
        if bounds[0] > bounds[1]:
            raise ValueError('ordered a priori heat bounds required')
    if any(type(i) is not int or not 0 <= i < size for i in fixed):
        raise ValueError('fixed KSS node outside geometry')
    if len(local) != nc or len(base_blocks) != nc:
        raise ValueError('complete KSS local block coverage required')
    # Partition the existing conservative arithmetic/fixed headroom between
    # one cached interval row and exact fallback temporaries. No extra lease,
    # cap change or omission from admission: an interval that cannot fit is
    # discarded and the original already-admitted exact formula is used.
    allocation = workspace_breakdown(geometry)
    interval_allowance = allocation['fixed_allowance']//2+32*allocation['arithmetic_object_bound']
    gamma_statistics = dict(calls=0, certified_96=0, certified_192=0,
                            certified_384=0, exact_fallbacks=0,
                            scratch_refusals=0, unaccelerated_pairs=0,
                            helper_source_sha256=_GAMMA_LOADED,
                            interval_allowance_bytes=interval_allowance)
    with localcontext() as context:
        context.prec, context.rounding = 80, ROUND_HALF_EVEN
        assembled, positive = {}, {}
        for at, (entry, block) in enumerate(zip(local, base_blocks)):
            _cancel(cancel)
            ci, indexes = entry[:2]
            if ci != at or tuple(indexes) != tuple(nc+j for j in geometry._cells[ci][2]):
                raise ValueError('KSS local entries do not match exact geometry')
            ids = (ci, *indexes)
            if len(block) != len(ids) or any(len(row) != len(ids) for row in block):
                raise ValueError('complete KSS local block required')
            for a, i in enumerate(ids):
                for b in range(a+1, len(ids)):
                    j, value = ids[b], D(block[a][b])
                    if not value.is_finite() or value != block[b][a]:
                        raise ValueError('finite symmetric KSS local block required')
                    key = (min(i, j), max(i, j))
                    assembled[key] = assembled.get(key, zero)+value
                    if value > 0:
                        positive.setdefault(key, []).append((at, a, b, value))
        # Reserve prior to this function using workspace_bytes. The adjacency
        # and directed bounds fit the unchanged 32768-byte/local-pair charge.
        edges = [(key, value) for key, value in sorted(assembled.items()) if value > 0]
        adjacency = [[] for _ in range(size)]
        edge_bounds = [[None, None] for _ in edges]
        for at, ((i, j), _) in enumerate(edges):
            adjacency[i].append((at, 0, j))
            adjacency[j].append((at, 1, i))
        coords, operators, face_normals = _recovery_cells(geometry, cancel, raw=True)
        neighbours = [None]*size
        checked_cell_rows = 0
        for a in range(size):
            _cancel(cancel)
            if a >= nc and coords[a] is None:
                raise ValueError('unowned exact KSS face')
            if a < nc:
                row, denominator = operators[a], geometry._cells[a][0]
                tangent, squared = None, None
            else:
                row, denominator, tangent, squared = _raw_face_recovery(
                    geometry, a-nc, fixed, operators, face_normals)
            if denominator <= 0:
                raise ValueError('positive exact KSS common volume required')
            if a < nc:
                # These are the actual dictionary rows used by recovery,
                # including any duplicate-key coalescing semantics. Check
                # every cell exactly once, even fixed or unconnected cells.
                if any(sum((v[axis] for v in row.values()), Q(0)) for axis in range(3)):
                    raise ValueError('KSS recovered gradient does not annihilate constants exactly')
                checked_cell_rows += 1
            elif checked_cell_rows != nc:
                raise ValueError('face recovery requires every exact cell closure first')
            # Face closure now follows from the checked source rows:
            # sum_k sum_owner N_owner,k = sum_owner 0. Dividing by the
            # positive common volume preserves zero. Deleting exact zeros
            # changes nothing; deleting tangent-parallel vectors changes
            # the raw sum only by a normal component, whose projection is
            # zero. _raw_face_recovery still checks nonzero normals and
            # exact tangent-null support. No unverified geometry is assumed.
            neighbours[a] = tuple(sorted(set(row)|{a}|{other for _, _, other in adjacency[a]}))
            if a not in fixed and adjacency[a]:
                interval = None
                try:
                    interval = _gamma.CertifiedGammaRow(row, denominator, node=a,
                        tangent=tangent, squared=squared,
                        admitted_bytes=interval_allowance, cancel=cancel)
                except MemoryLimitError:
                    gamma_statistics['scratch_refusals'] += 1
                for at, end, other in adjacency[a]:
                    _cancel(cancel)
                    delta = tuple(x-y for x, y in zip(coords[a], coords[other]))
                    if interval is not None:
                        try:
                            edge_bounds[at][end] = interval.gamma(delta)
                            continue
                        except MemoryLimitError:
                            # Release cached enclosures before the exact-only
                            # continuation when a delta's conversion cannot fit.
                            for key, value in interval.statistics.items():
                                gamma_statistics[key] += value
                            interval = None
                            gamma_statistics['scratch_refusals'] += 1
                    if tangent is not None:
                        scale = _dot(delta, tangent)/squared
                        delta = tuple(value-scale*normal for value, normal in zip(delta, tangent))
                    mu = sum((abs(_dot(vector, delta)) for k, vector in row.items() if k != a), Q(0))/denominator
                    edge_bounds[at][end] = D(2*mu.numerator)/D(mu.denominator)
                    gamma_statistics['unaccelerated_pairs'] += 1
                if interval is not None:
                    for key, value in interval.statistics.items():
                        gamma_statistics[key] += value
                    del interval
            del row
        del coords, operators, face_normals
        graph = []
        for at, ((i, j), d) in enumerate(edges):
            _cancel(cancel)
            occurrences = positive[i, j]
            weights = _partition_nonnegative(d, tuple(row[3] for row in occurrences), cancel)
            shares = tuple((cell, a, b, share) for (cell, a, b, _), share in zip(occurrences, weights))
            graph.append(_Edge(i, j, d, *edge_bounds[at], tuple(shares)))
        result = _Prepared(size, nc, tuple(neighbours), tuple(graph), cancel, bounds)
        result.gamma_statistics = gamma_statistics
        assert_current()
        _cancel(cancel)
        return result


class _Prepared:
    """Per-solve immutable-by-convention geometry/graph; no retained iterates."""
    __slots__ = ('size', 'local_count', 'neighbours', 'graph', 'cancel', 'bounds', 'gamma_statistics')

    def __init__(self, size, local_count, neighbours, graph, cancel, bounds):
        self.size, self.local_count = size, local_count
        self.neighbours, self.graph, self.cancel = neighbours, graph, cancel
        self.bounds = bounds
        self.gamma_statistics = None

    def _branches(self, state):
        return list(self._iter_branches(state))

    def _iter_branches(self, state):
        # Sorted neighbours and original-slope-first ties match probe_afc.
        state = _vector(state, self.size)
        mins = [min(row, key=state.__getitem__) for row in self.neighbours] if self.bounds is None else None
        maxs = [max(row, key=state.__getitem__) for row in self.neighbours] if self.bounds is None else None
        for edge in self.graph:
            _cancel(self.cancel)
            i, j = edge.i, edge.j
            delta = state[i]-state[j]
            sign = D(1) if delta >= 0 else D(-1)
            choices = [(sign*delta, 0, None, None)]
            if edge.gamma_i is not None:
                if self.bounds is None:
                    k = maxs[i] if sign > 0 else mins[i]
                    choices.append((sign*edge.gamma_i*(state[k]-state[i]), 1, k, edge.gamma_i))
                else:
                    room = sign*(self.bounds[1 if sign > 0 else 0]-state[i])
                    choices.append((edge.gamma_i*max(D(0), room), 1, None,
                                    edge.gamma_i if room > 0 else D(0)))
            if edge.gamma_j is not None:
                if self.bounds is None:
                    k = mins[j] if sign > 0 else maxs[j]
                    choices.append((sign*edge.gamma_j*(state[j]-state[k]), 2, k, edge.gamma_j))
                else:
                    room = sign*(state[j]-self.bounds[0 if sign > 0 else 1])
                    choices.append((edge.gamma_j*max(D(0), room), 2, None,
                                    edge.gamma_j if room > 0 else D(0)))
            if self.bounds is not None and not delta:
                # A zero allowance gives identically zero allowed slope in
                # an exterior neighbourhood. Retain that linear branch, not
                # a fictitious zero correction derivative at an equal pair.
                choices.sort(key=lambda row: (row[0], row[3] != 0))
            slope, branch, k, gamma = min(choices, key=lambda row: row[0])
            if slope < 0 or slope > abs(delta):
                raise ValueError('KSS selected slope violates its exact nonnegative bounds')
            yield delta, sign*slope, branch, k, gamma

    def matches_derivative(self, state, active):
        """Compare the actual rounded state's selection without a second table.

        This is Newton work eligibility only, never a physical acceptance
        check. Caller-owned active coefficients and Newton vector storage
        remain in their existing admitted lifetime.
        """
        assert_current(); _cancel(self.cancel)
        with localcontext() as context:
            context.prec, context.rounding = 80, ROUND_HALF_EVEN
            expected = iter(active)
            same = True
            for edge, (_, _, branch, k, gamma) in zip(self.graph, self._iter_branches(state)):
                if branch and next(expected, None) != (edge.i, edge.j, edge.d, branch, k, gamma):
                    same = False
                    break
            if same:
                same = next(expected, None) is None
        assert_current(); _cancel(self.cancel)
        return same

    def corrections(self, state):
        """Return local nonnegative frozen coefficients for P._corrected_faces."""
        assert_current()
        _cancel(self.cancel)
        with localcontext() as context:
            context.prec, context.rounding = 80, ROUND_HALF_EVEN
            output, zero = [[] for _ in range(self.local_count)], D(0)
            for edge, (delta, slope, _, _, _) in zip(self.graph, self._branches(state)):
                coefficient = edge.d*(delta-slope)/delta if delta else zero
                weights = _partition_nonnegative(coefficient, tuple(row[3] for row in edge.shares), self.cancel)
                for (at, a, b, _), weight in zip(edge.shares, weights):
                    output[at].append((a, b, weight))
        assert_current()
        _cancel(self.cancel)
        return output

    def derivative(self, state, *, line_direction=None, line_step=None, budget=None):
        """Prepare the selected correction-only Jacobian, excluding base K.

        Keep the active min/max branch fixed. At ties use the same deterministic
        branch as corrections; zero difference selects the original slope and
        hence zero correction derivative. This is a selected linearisation at
        kinks, not a claim of differentiability there. For one bounded
        alternative, line_direction/line_step select an exact rational point
        in the next affine region returned by event_line_search. That point
        selects a Jacobian only; it is never an accepted heat state.
        Adjacent-region construction requires its caller's shared budget;
        its exact rational workspace is released before returning the
        Decimal-only active coefficients charged by Newton's workspace.
        """
        assert_current()
        _cancel(self.cancel)
        with localcontext() as context:
            context.prec, context.rounding = 80, ROUND_HALF_EVEN
            if (line_direction is None) != (line_step is None):
                raise ValueError('complete adjacent-region direction and exact step required')
            if line_direction is None:
                branches = self._branches(state)
                active = tuple((edge.i, edge.j, edge.d, branch, k, gamma)
                               for edge, (_, _, branch, k, gamma) in zip(self.graph, branches) if branch)
            else:
                if self.bounds is None or not isinstance(line_step, Q) or not 0 < line_step < 1:
                    raise ValueError('fixed bounds and an interior exact line-region step required')
                if type(budget) is not WorkBudget:
                    raise ValueError('shared WorkBudget required for exact adjacent-region construction')
                state, direction = _vector(state, self.size), _vector(line_direction, self.size)
                admitted = _adjacent_workspace_bytes(state, direction, self.bounds, self.graph, line_step, self.cancel)
                def exact_coefficients():
                    # Keep rational objects local to this call so none is
                    # captured by the returned Decimal derivative action.
                    def points():
                        for value, step_direction in zip(state, direction):
                            _cancel(self.cancel)
                            yield Q(value)+line_step*Q(step_direction)
                    point = tuple(points())
                    bounds = tuple(map(Q, self.bounds))
                    def selected_branches():
                        for edge in self.graph:
                            _cancel(self.cancel)
                            yield _event_branch(edge, point, bounds)
                    return tuple((edge.i, edge.j, edge.d, branch, k, gamma)
                        for edge, (_, _, branch, k, gamma) in zip(self.graph, selected_branches()) if branch)
                with budget.reserve(admitted, category='mimetic-adjacent-rational'):
                    active = exact_coefficients()
                del exact_coefficients
        assert_current()

        def action(direction):
            assert_current()
            _cancel(self.cancel)
            with localcontext() as context:
                context.prec, context.rounding = 80, ROUND_HALF_EVEN
                direction = _vector(direction, self.size)
                result = [D(0)]*self.size
                for i, j, d, branch, k, gamma in active:
                    _cancel(self.cancel)
                    other = direction[k] if k is not None else D(0)
                    limited = gamma*((other-direction[i]) if branch == 1 else
                                     (direction[j]-other))
                    amount = d*((direction[i]-direction[j])-limited)
                    result[i] += amount
                    result[j] -= amount
            assert_current()
            _cancel(self.cancel)
            return result
        # Immutable tuple is the actual selected linearisation, including
        # exact adjacent-region choices; preconditioners must not reselect it.
        action.active_coefficients = active
        return action

_MAX_EVENTS_PER_EDGE = 9


def _adjacent_workspace_bytes(state, direction, bounds, graph, line_step, cancel=None):
    """Account exact point construction before creating any Fraction values.

    Decimal span includes exponent size, including very small input values.
    Four bits per decimal digit upper-bounds decimal integer conversion;
    adding the exact step numerator/denominator bit lengths covers products
    and cross-multiplied sums. Two rational-vector equivalents plus transient
    branch arithmetic are admitted. The surviving Decimal coefficient tuple
    is separately covered by the caller's existing Newton reservation.
    """
    span = 1
    def include(value):
        nonlocal span
        item = value.as_tuple()
        span = max(span, len(item.digits)+abs(item.exponent))
    for values in (state, direction, bounds):
        for value in values:
            _cancel(cancel)
            include(value)
    for edge in graph:
        _cancel(cancel)
        for value in (edge.gamma_i, edge.gamma_j):
            if value is not None:
                include(value)
    decimal_bits = 4*span+8
    step_bits = abs(line_step.numerator).bit_length()+line_step.denominator.bit_length()
    integer_bytes = (2*decimal_bits+step_bits+15)//8
    rational_bytes = 256+2*integer_bytes
    return 65536+len(state)*(2*rational_bytes+128)+64*rational_bytes


def _event_workspace_bytes(size, edges, decimal_span=160):
    """Admission estimate before Fraction vectors or event tables are built.

Span is digits+abs(exponent), not merely significant digits. At most nine
actual slope-change events occur per edge: each sign of delta has a zero
piece on either side of a lower envelope of at most three affine functions.
The allowance includes transient candidate roots and two sweep vectors.
Like the existing helpers this is conservative accounting, not an RSS cap
or a universal proof about arbitrary-rational numerator growth.
"""
    if any(type(v) is not int or v < 0 for v in (size, edges, decimal_span)):
        raise ValueError('nonnegative integer event-search workspace dimensions required')
    integer_bytes = (4*max(1, decimal_span)+7)//8
    return 2*1024**2+8192*size+edges*(8192+16*(512+8*integer_bytes))


def _event_branch(edge, u, bounds):
    """Exact bounded branch, shared by event values and adjacent Jacobians."""
    delta = u[edge.i]-u[edge.j]
    sign = 1 if delta >= 0 else -1
    choices = [(abs(delta), 0, None, None)]
    if edge.gamma_i is not None:
        room = sign*(bounds[1 if sign > 0 else 0]-u[edge.i])
        choices.append((Q(edge.gamma_i)*max(Q(0), room), 1, None, edge.gamma_i if room > 0 else D(0)))
    if edge.gamma_j is not None:
        room = sign*(u[edge.j]-bounds[0 if sign > 0 else 1])
        choices.append((Q(edge.gamma_j)*max(Q(0), room), 2, None, edge.gamma_j if room > 0 else D(0)))
    if not delta:
        choices.sort(key=lambda row: (row[0], row[3] != 0))
    slope, branch, k, gamma = min(choices, key=lambda row: row[0])
    return delta, sign*slope, branch, k, gamma


def _event_allowance(edge, u, bounds):
    return _event_branch(edge, u, bounds)[1]


def _single_edge_piece(edge, state, direction, bounds, delta, dd):
    """Prove one affine branch on the whole line, or defer to exact events.

    An affine inequality holds throughout [0,1] when it holds at both ends.
    Use untruncated headroom here: a nonnegative winning line can only be
    dominated by another allowance if its RAW headroom dominates at both
    ends. Comparing just max(0, headroom) at endpoints is not sufficient.
    All comparisons are rational, with no geometric tolerance or sampling.
    """
    zero, one = Q(0), Q(1)
    end = delta+dd
    if delta < 0 < end or end < 0 < delta:
        return None
    if not delta and not end:
        return [(zero, one, zero, zero)]
    sign = 1 if delta >= 0 and end >= 0 else -1
    lines = [(sign*delta, sign*dd)]
    for gamma, p, q in (
            (edge.gamma_i, sign*(bounds[1 if sign > 0 else 0]-state[edge.i]), -sign*direction[edge.i]),
            (edge.gamma_j, sign*(state[edge.j]-bounds[0 if sign > 0 else 1]), sign*direction[edge.j])):
        if gamma is None:
            continue
        if not gamma or p <= 0 and p+q <= 0:
            return [(zero, one, zero, zero)]
        g = Q(gamma)
        lines.append((g*p, g*q))
    for p, q in lines:
        if p >= 0 and p+q >= 0 and all(p <= a and p+q <= a+b for a,b in lines):
            return [(zero, one, sign*p, sign*q)]
    return None


def _edge_pieces(edge, state, direction, bounds, cancel=None):
    """Exact rational affine pieces of the signed allowed slope on [0,1]."""
    zero, one = Q(0), Q(1)
    i, j = edge.i, edge.j
    delta, dd = state[i]-state[j], direction[i]-direction[j]
    _cancel(cancel)
    single = _single_edge_piece(edge, state, direction, bounds, delta, dd)
    if single is not None:
        return single
    cuts = {zero, one}
    def root(p, q, lo=zero, hi=one):
        if q:
            value = -p/q
            if lo < value < hi:
                cuts.add(value)
    root(delta, dd)
    for k, gamma in ((i, edge.gamma_i), (j, edge.gamma_j)):
        if gamma is not None:
            for bound in bounds:
                root(state[k]-bound, direction[k])
    def choices(mid):
        sign = 1 if delta+mid*dd >= 0 else -1
        lines = [(sign*delta, sign*dd)]
        if edge.gamma_i is not None:
            p, q = sign*(bounds[1 if sign > 0 else 0]-state[i]), -sign*direction[i]
            gamma = Q(edge.gamma_i)
            lines.append((gamma*p, gamma*q) if p+mid*q > 0 else (zero, zero))
        if edge.gamma_j is not None:
            p, q = sign*(state[j]-bounds[0 if sign > 0 else 1]), sign*direction[j]
            gamma = Q(edge.gamma_j)
            lines.append((gamma*p, gamma*q) if p+mid*q > 0 else (zero, zero))
        return sign, lines
    outer = sorted(cuts)
    for lo, hi in zip(outer, outer[1:]):
        _cancel(cancel)
        _, lines = choices((lo+hi)/2)
        for at, (p, q) in enumerate(lines):
            for pp, qq in lines[at+1:]:
                root(p-pp, q-qq, lo, hi)
    cuts = sorted(cuts)
    pieces = []
    for lo, hi in zip(cuts, cuts[1:]):
        mid = (lo+hi)/2
        sign, lines = choices(mid)
        p, q = min(lines, key=lambda line: line[0]+mid*line[1])
        p, q = sign*p, sign*q
        if pieces and pieces[-1][2:] == (p, q):
            pieces[-1] = (pieces[-1][0], hi, p, q)
        else:
            pieces.append((lo, hi, p, q))
    if len(pieces)-1 > _MAX_EVENTS_PER_EDGE:
        raise ArithmeticError('fixed-bound edge exceeded admitted affine-piece count')
    if pieces[0][2] != _event_allowance(edge, state, bounds):
        raise ArithmeticError('edge line search lost continuity at its origin')
    for left, right in zip(pieces, pieces[1:]):
        alpha = right[0]
        if left[2]+alpha*left[3] != right[2]+alpha*right[3]:
            raise ArithmeticError('fixed-bound edge slope is not continuous at an exact event')
    return pieces


def event_line_search(limiter, state, direction, residual, base_direction, dt, *, budget, fixed=(), cancel=None):
    """Return a proposed Decimal step in [0,1], never an accepted heat state.

    ``limiter`` supplies size, graph and fixed bounds. Graph edge attributes
    are i,j,d,gamma_i,gamma_j; None gamma omits a fixed endpoint's allowance.
    Pass all Dirichlet indices in ``fixed`` (fixed endpoints seen on a positive
    edge are also inferred from None gamma). Their directions and residuals
    must be zero; their base-action and edge rows are excluded from merit.
    Pass one common WorkBudget. Reservation is held through all exact event
    and merit work. Caller must keep the returned proposal check separate
    from final heat acceptance; no tolerance is defined by this helper.
    """
    if type(budget) is not WorkBudget:
        raise ValueError('explicit shared WorkBudget required')
    if limiter.bounds is None:
        raise ValueError('event search supports fixed a-priori bounds only')
    _cancel(cancel)
    size, edge_count = limiter.size, len(limiter.graph)
    if any(len(v) != size for v in (state, direction, residual, base_direction)):
        raise ValueError('complete line-search state, direction and residual vectors required')
    values = (state, direction, residual, base_direction, limiter.bounds, (dt,))
    span = 1
    for rows in values:
        for value in rows:
            if not isinstance(value, D) or not value.is_finite():
                raise ValueError('finite Decimal line-search values required')
            item = value.as_tuple()
            span = max(span, len(item.digits)+abs(item.exponent))
    if dt <= 0 or limiter.bounds[0] > limiter.bounds[1]:
        raise ValueError('positive duration and ordered bounds required')
    fixed = set(fixed)
    if any(type(i) is not int or not 0 <= i < size for i in fixed):
        raise ValueError('fixed line-search index outside state')
    for edge in limiter.graph:
        if not (0 <= edge.i < size and 0 <= edge.j < size and edge.i != edge.j):
            raise ValueError('line-search edge index outside state')
        for coefficient in (edge.d, edge.gamma_i, edge.gamma_j):
            if coefficient is not None:
                if not isinstance(coefficient, D) or not coefficient.is_finite() or coefficient < 0:
                    raise ValueError('nonnegative finite Decimal edge coefficient required')
                item = coefficient.as_tuple()
                span = max(span, len(item.digits)+abs(item.exponent))
        for index, gamma in ((edge.i,edge.gamma_i),(edge.j,edge.gamma_j)):
            if gamma is None:
                fixed.add(index)
            elif index in fixed:
                raise ValueError('fixed endpoint retains a limiter allowance')
    if any(direction[i] or residual[i] for i in fixed):
        raise ValueError('fixed rows require zero direction and residual')
    admitted = _event_workspace_bytes(size, edge_count, span)
    output_precision = getcontext().prec
    with budget.reserve(admitted, category='mimetic-event-line-search'), localcontext() as context:
        # Twice the caller precision protects squared-merit updates; digit
        # growth from summing n rows gets an explicit additional allowance.
        context.prec = 2*output_precision+len(str(max(1, size, edge_count)))+4
        context.rounding = ROUND_HALF_EVEN
        zero, one = D(0), D(1)
        decimal = lambda q: D(q.numerator)/D(q.denominator)
        uq, pq = tuple(map(Q, state)), tuple(map(Q, direction))
        bounds, dtq = tuple(map(Q, limiter.bounds)), Q(dt)
        a, b = list(residual), [zero if i in fixed else value for i,value in enumerate(base_direction)]
        events = []
        for edge in limiter.graph:
            _cancel(cancel)
            pieces = _edge_pieces(edge, uq, pq, bounds, cancel)
            coefficient = dtq*Q(edge.d)
            derivative = coefficient*((pq[edge.i]-pq[edge.j])-pieces[0][3])
            change = decimal(derivative)
            if edge.i not in fixed: b[edge.i] += change
            if edge.j not in fixed: b[edge.j] -= change
            for left, right in zip(pieces, pieces[1:]):
                change = -coefficient*(right[3]-left[3])
                if change:
                    events.append((right[0], edge.i, edge.j, change))
        _cancel(cancel)
        events.sort(key=lambda event: event[0])
        # Reuse this one event ordering. A rejected direction may supply ONE
        # adjacent-region Jacobian, without another graph/event preparation.
        # Preserve its midpoint as an exact ratio: rounding a Kelvin probe
        # can collapse the very thin region that caused Newton to stall.
        adjacent_step, adjacent_interval = None, None
        if events:
            lower = events[0][0]
            upper = next((event[0] for event in events if event[0] > lower), Q(1))
            middle = (lower+upper)/2
            adjacent_step = (middle.numerator, middle.denominator)
            adjacent_interval = ((lower.numerator, lower.denominator), (upper.numerator, upper.denominator))
        aa = sum((v*v for v in a), zero)
        ab = sum((v*w for v,w in zip(a,b)), zero)
        bb = sum((v*v for v in b), zero)
        original_merit, best_merit, best_step = aa, aa, zero
        intervals, at, previous = 0, 0, Q(0)
        while True:
            _cancel(cancel)
            following = events[at][0] if at < len(events) else Q(1)
            lo, hi = decimal(previous), decimal(following)
            step = max(lo, min(hi, -ab/bb)) if bb else lo
            merit = aa+step*(2*ab+step*bb)
            if merit < best_merit:
                best_merit, best_step = merit, step
            intervals += 1
            if at == len(events):
                break
            # F(alpha)=a+alpha*b. Changing one edge's derivative affects only
            # rows i,j. a-=event*db preserves F continuously at that event.
            while at < len(events) and events[at][0] == following:
                _, i, j, rational_change = events[at]
                change = decimal(rational_change)
                for k, db in ((i,change),(j,-change)):
                    if k in fixed:
                        continue
                    old_a, old_b = a[k], b[k]
                    new_a, new_b = old_a-hi*db, old_b+db
                    aa += new_a*new_a-old_a*old_a
                    ab += new_a*new_b-old_a*old_b
                    bb += new_b*new_b-old_b*old_b
                    a[k], b[k] = new_a, new_b
                at += 1
            previous = following
        # Round the proposal to actual caller arithmetic, checking its direct
        # neighbours too. No empirical epsilon or acceptance tolerance enters.
        with localcontext() as output_context:
            output_context.prec = output_precision
            rounded = +best_step
            candidates = {zero, one, rounded, rounded.next_minus(), rounded.next_plus()}
        candidates = sorted(step for step in candidates if zero <= step <= one)
        initial_slopes = [_event_allowance(edge,uq,bounds) for edge in limiter.graph]
        best_step, checked_merit = zero, original_merit
        for step in candidates:
            _cancel(cancel)
            if not step:
                continue
            stepq = Q(step)
            trial = tuple(v+stepq*w for v,w in zip(uq,pq))
            f = [zero if i in fixed else v+step*w for i,(v,w) in enumerate(zip(residual,base_direction))]
            for edge, initial_slope in zip(limiter.graph,initial_slopes):
                _cancel(cancel)
                slope = _event_allowance(edge,trial,bounds)
                difference = stepq*(pq[edge.i]-pq[edge.j])-(slope-initial_slope)
                amount = decimal(dtq*Q(edge.d)*difference)
                if edge.i not in fixed: f[edge.i] += amount
                if edge.j not in fixed: f[edge.j] -= amount
            merit = sum((v*v for v in f),zero)
            if merit < checked_merit:
                checked_merit, best_step = merit, step
        return dict(step=best_step, max_step=one, events=len(events), intervals=intervals,
            adjacent_step_ratio=adjacent_step, adjacent_interval_ratios=adjacent_interval,
            original_merit_decimal=str(original_merit),
            proposed_surrogate_merit_decimal=str(checked_merit),
            sweep_merit_decimal=str(best_merit),
            event_identity='exact rational breakpoints of supplied finite Decimal coefficients',
            caller_precision=output_precision, search_precision=context.prec, admitted_bytes=admitted,
            requires_true_residual_check=True)
