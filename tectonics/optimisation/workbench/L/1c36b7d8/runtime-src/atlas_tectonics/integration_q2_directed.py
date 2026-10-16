"""Certified one-dimensional integration after analytic quadratic sign split.

Taylor's theorem encloses each outer-coordinate integral. Every coefficient
operation is an outward-rounded Decimal interval; a root is used only when its
entire interval fixes its branch relative to 0 and 1. Unresolved root events use
the exact two-dimensional Bernstein enclosure, never a guessed root/sign.
SPDX-License-Identifier: AGPL-3.0-only
"""
from decimal import Context, Decimal as D, ROUND_FLOOR, ROUND_CEILING
from contextlib import ExitStack
from fractions import Fraction as Q
import heapq
import hashlib
from math import comb, isqrt
from pathlib import Path

from . import integration_volume as V
from . import integration_volume_bounds as B
from .regional_heat3d import _cancel
from .resources import WorkBudget, _GrowingLease

# A fixed even order, independent of the caller's outcome. Root events are
# isolated first; the high order controls smooth intervals without spending
# the finite geometric leaf allocation on a low-order quadrature remainder.
ORDER = 32
_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def source_digest():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
        raise V.VolumeError('Q2 directed quadrature source changed after loading')
    return _LOADED


class _Branch(Exception):
    pass


class _Intervals:
    def __init__(self):
        self.lo = Context(prec=80, rounding=ROUND_FLOOR)
        self.hi = Context(prec=80, rounding=ROUND_CEILING)

    def point(self, q):
        q = Q(q)
        return (self.lo.divide(D(q.numerator), D(q.denominator)),
                self.hi.divide(D(q.numerator), D(q.denominator)))

    def add(self, a, b):
        return self.lo.add(a[0], b[0]), self.hi.add(a[1], b[1])

    def neg(self, a):
        return a[1].copy_negate(), a[0].copy_negate()

    def sub(self, a, b):
        return self.add(a, self.neg(b))

    def mul(self, a, b):
        # Multiplication is monotone in each argument while its sign is fixed.
        # Select the SAME exact extrema as the four-corner rule, then round
        # those products outward. Mixed/mixed intervals need two candidates
        # per bound, not all four. This changes neither precision nor bounds.
        if a[0] == a[1] and b[0] == b[1]:
            return self.lo.multiply(a[0], b[0]), self.hi.multiply(a[0], b[0])
        # Preserve the old first-corner convention for signed-zero ties.
        if any(x.is_zero() for x in (*a, *b)):
            return (min(self.lo.multiply(x, y) for x in a for y in b),
                    max(self.hi.multiply(x, y) for x in a for y in b))
        if a[0] > 0:
            if b[0] > 0:
                low, high = (a[0], b[0]), (a[1], b[1])
            elif b[1] < 0:
                low, high = (a[1], b[0]), (a[0], b[1])
            else:
                low, high = (a[1], b[0]), (a[1], b[1])
        elif a[1] < 0:
            if b[0] > 0:
                low, high = (a[0], b[1]), (a[1], b[0])
            elif b[1] < 0:
                low, high = (a[1], b[1]), (a[0], b[0])
            else:
                low, high = (a[0], b[1]), (a[0], b[0])
        elif b[0] > 0:
            low, high = (a[0], b[1]), (a[1], b[1])
        elif b[1] < 0:
            low, high = (a[1], b[0]), (a[0], b[0])
        else:
            return (min(self.lo.multiply(a[0], b[1]), self.lo.multiply(a[1], b[0])),
                    max(self.hi.multiply(a[0], b[0]), self.hi.multiply(a[1], b[1])))
        return self.lo.multiply(*low), self.hi.multiply(*high)

    def div(self, a, b):
        if b[0] <= 0 <= b[1]:
            raise _Branch()
        return (min(self.lo.divide(x, y) for x in a for y in b),
                max(self.hi.divide(x, y) for x in a for y in b))

    def sqrt(self, a):
        if a[0] <= 0:
            raise _Branch()
        # Decimal.sqrt is correctly nearest-rounded regardless of context's
        # rounding attribute; one adjacent Decimal on each side encloses it.
        return self.lo.next_minus(self.lo.sqrt(a[0])), self.hi.next_plus(self.hi.sqrt(a[1]))


class _Jets:
    def __init__(self):
        self.I = _Intervals()
        self.zero = self.I.point(0)

    def constant(self, q):
        return [self.I.point(q)]+[self.zero]*ORDER

    def variable(self, bounds):
        return [(self.I.point(bounds[0])[0], self.I.point(bounds[1])[1]), self.I.point(1)]+[self.zero]*(ORDER-1)

    def add(self, a, b):
        return [self.I.add(x, y) for x, y in zip(a, b)]

    def neg(self, a):
        return [self.I.neg(x) for x in a]

    def sub(self, a, b):
        return self.add(a, self.neg(b))

    def mul(self, a, b):
        result = []
        for k in range(ORDER+1):
            value = self.zero
            for i in range(k+1):
                value = self.I.add(value, self.I.mul(a[i], b[k-i]))
            result.append(value)
        return result

    def div(self, a, b):
        result = []
        for k in range(ORDER+1):
            value = a[k]
            for i in range(1, k+1):
                value = self.I.sub(value, self.I.mul(b[i], result[k-i]))
            result.append(self.I.div(value, b[0]))
        return result

    def sqrt(self, a):
        result = [self.I.sqrt(a[0])]
        denominator = self.I.mul(self.I.point(2), result[0])
        for k in range(1, ORDER+1):
            value = a[k]
            for i in range(1, k):
                value = self.I.sub(value, self.I.mul(result[i], result[k-i]))
            result.append(self.I.div(value, denominator))
        return result


def _outer_jet(p, bounds, J):
    """Exact Bernstein derivative ranges avoid interval dependency in D=B²-4AC."""
    def enclosure(values):
        degree = len(values)-1
        power = [sum((values[i]*comb(i, k)*bounds[0]**(i-k)*(bounds[1]-bounds[0])**k
                     for i in range(k, degree+1)), Q(0)) for k in range(degree+1)]
        bernstein = [sum((power[i]*Q(comb(k, i), comb(degree, i))
                         for i in range(k+1)), Q(0)) for k in range(degree+1)]
        return J.I.point(min(bernstein))[0], J.I.point(max(bernstein))[1]
    return [enclosure([v*comb(i, k) for i, v in enumerate(p) if i >= k])
            if k < len(p) else J.zero for k in range(ORDER+1)]


def _primitive_jets(polynomial, bounds, J):
    coeff = [[polynomial.get((i, j), Q(0)) for j in range(3)] for i in range(3)]
    if any(coeff[0]) and not any(sum(row) for row in zip(*coeff)):
        # An exact endpoint root has no uncertain branch. Reflection x -> 1-x
        # converts it to the explicit C=0 formula below with unit Jacobian.
        reflected = {(i,j):v for i,row in ((1,[-b-2*a for b,a in zip(coeff[1],coeff[2])]),(2,coeff[2]))
                     for j,v in enumerate(row) if v}
        return _primitive_jets(reflected,bounds,J)
    C, B, A = [_outer_jet(p, bounds, J) for p in coeff]
    zero, one = J.constant(0), J.constant(1)
    total = J.add(J.add(C, J.div(B, J.constant(2))), J.div(A, J.constant(3)))
    def primitive(r):
        return J.mul(r, J.add(C, J.mul(r, J.add(J.div(B, J.constant(2)),
                                                J.div(J.mul(A, r), J.constant(3))))))
    def clamp(r):
        if r[0][1] <= 0:
            return zero
        if r[0][0] >= 1:
            return one
        if r[0][0] >= 0 and r[0][1] <= 1:
            return r
        raise _Branch()
    if not any(i == 2 for i, _ in polynomial):
        if not any(i == 1 for i, _ in polynomial):
            if C[0][0] >= 0:
                return zero
            if C[0][1] <= 0:
                return J.neg(total)
            raise _Branch()
        if B[0][0] > 0:
            return J.neg(primitive(clamp(J.div(J.neg(C), B))))
        if B[0][1] < 0:
            return J.sub(primitive(clamp(J.div(J.neg(C), B))), total)
        raise _Branch()
    if A[0][0] <= 0 <= A[0][1]:
        raise _Branch()
    if A[0][1] < 0:
        return J.sub(_primitive_jets({k:-v for k,v in polynomial.items()}, bounds, J), total)
    if not any(i == 0 for i, _ in polynomial):
        at_one = _outer_jet([a+b for a,b in zip(coeff[2],coeff[1])], bounds, J)
        if B[0][0] >= 0:
            return zero
        if at_one[0][1] <= 0:
            return J.neg(total)
        if B[0][1] < 0 and at_one[0][0] > 0:
            return J.div(J.neg(J.mul(J.mul(B,B),B)), J.mul(J.constant(6),J.mul(A,A)))
        raise _Branch()
    dc = [Q(0)]*5
    for i in range(3):
        for j in range(3):
            dc[i+j] += coeff[1][i]*coeff[1][j]-4*coeff[2][i]*coeff[0][j]
    discriminant = _outer_jet(dc, bounds, J)
    if discriminant[0][1] <= 0:
        return zero
    square = _square_root_polynomial(dc)
    if square is None:
        root = J.sqrt(discriminant)
    else:
        root = _outer_jet(square,bounds,J)
        if root[0][0] >= 0:
            pass
        elif root[0][1] <= 0:
            root = J.neg(root)
        else:
            raise _Branch()
    denominator = J.mul(J.constant(2), A)
    def left_root():
        if B[0][1] < 0:
            return J.div(J.mul(J.constant(2), C), J.add(J.neg(B), root))
        return J.div(J.sub(J.neg(B), root), denominator)
    def right_root():
        if B[0][0] > 0:
            return J.div(J.mul(J.constant(2), C), J.sub(J.neg(B), root))
        return J.div(J.add(J.neg(B), root), denominator)
    at_one = _outer_jet([sum(v) for v in zip(*coeff)], bounds, J)
    if C[0][1] < 0:
        left = zero
        if at_one[0][1] < 0:
            right = one
        elif at_one[0][0] > 0:
            right = right_root()
        else:
            raise _Branch()
    elif C[0][0] > 0:
        if at_one[0][1] < 0:
            left = left_root(); right = one
        elif at_one[0][0] > 0:
            vertex_numerator = J.neg(B)[0]
            vertex_below_one = _outer_jet([2*a+b for a,b in zip(coeff[2],coeff[1])], bounds, J)[0]
            if vertex_numerator[1] <= 0 or vertex_below_one[1] <= 0:
                return zero
            if vertex_numerator[0] <= 0 or vertex_below_one[0] <= 0:
                raise _Branch()
            # Both roots are interior. This identity avoids subtraction of two
            # nearly equal cubic primitives near a double root.
            return J.div(J.mul(discriminant, root), J.mul(J.constant(6), J.mul(A, A)))
        else:
            raise _Branch()
    else:
        raise _Branch()
    between = J.sub(primitive(right), primitive(left))
    return J.neg(between)


def _trim(p):
    while p and p[-1] == 0:
        p.pop()
    return p


def _square_root_polynomial(values):
    """Recognise an EXACT rational polynomial square, never a near-square."""
    p=_trim(list(values))
    if not p or (len(p)-1)%2 or p[-1]<0:
        return None
    a,b=isqrt(p[-1].numerator),isqrt(p[-1].denominator)
    if a*a!=p[-1].numerator or b*b!=p[-1].denominator:
        return None
    m=(len(p)-1)//2;r=[Q(0)]*(m+1);r[m]=Q(a,b)
    for k in range(m-1,-1,-1):
        known=sum((r[i]*r[m+k-i] for i in range(k+1,m+1) if 0<=m+k-i<=m),Q(0))
        r[k]=(p[m+k]-known)/(2*r[m])
    squared=[sum((r[i]*r[k-i] for i in range(m+1) if 0<=k-i<=m),Q(0)) for k in range(2*m+1)]
    return r if squared==p else None


def _divide(p, divisor):
    r = _trim(list(p)); quotient = [Q(0)]*max(1, len(r)-len(divisor)+1)
    while len(r) >= len(divisor):
        value, shift = r[-1]/divisor[-1], len(r)-len(divisor)
        quotient[shift] = value
        for i, v in enumerate(divisor):
            r[i+shift] -= value*v
        _trim(r)
    return _trim(quotient), r


def _negative_primitive(polynomial, bounds, J):
    coeff = [_trim([polynomial.get((i,j), Q(0)) for j in range(3)]) for i in range(3)]
    factor = _common_factor(coeff)
    if len(factor) > 1:
        f = _outer_jet(factor, bounds, J)
        if f[0][0] >= 0 or f[0][1] <= 0:
            if f[0][1] <= 0:
                factor = [-v for v in factor]; f = J.neg(f)
            normalised = {(i,j):v for i in range(3)
                for j,v in enumerate(_divide(coeff[i],factor)[0]) if v}
            return J.mul(f, _primitive_jets(normalised, bounds, J))
    return _primitive_jets(polynomial, bounds, J)


def _common_factor(polynomials):
    nonzero = [p for p in polynomials if p]
    if not nonzero:
        return []
    a = nonzero[0]
    for b in nonzero[1:]:
        while b:
            _, remainder = _divide(a, b)
            a, b = b, remainder
    return [v/a[-1] for v in a]


def _parabola_upper(polynomial, bounds, J):
    """Integral bound through a double-root event, without dividing by sqrt(D).

    For A>0 the negative integral over the whole real line is D_+**(3/2)
    /(6*A**2). Restricting x to [0,1] can only reduce it. This remains valid
    on leaves containing D=0, where analytic derivatives are singular.
    """
    coeff = [[polynomial.get((i, j), Q(0)) for j in range(3)] for i in range(3)]
    a = _outer_jet(coeff[2], bounds, J)[0]
    if a[0] <= 0:
        return None
    dc = [Q(0)]*5
    for i in range(3):
        for j in range(3):
            dc[i+j] += coeff[1][i]*coeff[1][j]-4*coeff[2][i]*coeff[0][j]
    d = _outer_jet(dc, bounds, J)[0][1]
    if d <= 0:
        return Q(0)
    upper_root = J.I.hi.next_plus(J.I.hi.sqrt(d))
    numerator = J.I.hi.multiply(d, upper_root)
    denominator = J.I.lo.multiply(D(6), J.I.lo.multiply(a[0], a[0]))
    return Q(J.I.hi.divide(numerator, denominator))*(bounds[1]-bounds[0])


class _Q2Capacity:
    """Reusable high-water capacity for live records, not processed leaves.

    Preserve the former 8192-byte record allowance and add 64 times the
    actual retained rational payload bytes. The fixed Taylor workspace in
    negative_bounds remains separate. Eight staging slots are admitted
    before creating a popped record's trial/child records; current operand
    and accumulator widths enlarge that staging allowance. These are
    conservative admission estimates, not an operating-system RSS limit.
    """
    def __init__(self, budget):
        self.budget, self.stack = budget, ExitStack()
        self.lease = (_GrowingLease(budget) if type(budget) is WorkBudget and
                      'reserve' not in budget.__dict__ else None)
        self.live_bytes = self.capacity_bytes = 0
        self.staging_bytes = 8*8192

    def __enter__(self):
        self.stack.__enter__()
        if self.lease is not None:
            self.stack.enter_context(self.lease)
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    @staticmethod
    def _payload(value):
        if isinstance(value, (tuple, list)):
            return sum(_Q2Capacity._payload(v) for v in value)
        return (V._bits(value)+7)//8

    def _ensure(self, needed):
        if needed > self.capacity_bytes:
            extra = needed-self.capacity_bytes
            if self.lease is None:
                self.stack.enter_context(self.budget.reserve(extra, category='native-Q2-directed-frontier'))
            else:
                self.lease.add(extra, category='native-Q2-directed-frontier')
            self.capacity_bytes = needed

    def prepare(self, values=(), *, slots=8):
        # Admit staging before arithmetic/child construction. Never refund
        # an earlier maximum while this operation may reuse its capacity.
        staging = max(self.staging_bytes, 8192*slots+64*self._payload(values))
        self._ensure(self.live_bytes+staging)
        self.staging_bytes = staging

    def append(self, sequence, value, *, heap=False):
        size = 8192+64*self._payload(value)
        self._ensure(self.live_bytes+size+self.staging_bytes)
        self.live_bytes += size
        if heap:
            heapq.heappush(sequence, value)
        else:
            sequence.append(value)

    def pop(self, sequence, *, heap=False):
        value = heapq.heappop(sequence) if heap else sequence.pop()
        self.live_bytes -= 8192+64*self._payload(value)
        return value

    def clear(self, sequence):
        while sequence:
            self.pop(sequence)


def _events(polynomial, target, bound, arena, cancel=None, *, capacity):
    """Exact Sturm isolation of every possible quadratic branch event.

    Each root interval is widened by its own proved isolation width. Their
    total worst-case integral uncertainty is <=3/8 of the caller's target.
    Isolation predicates charge finite work; this is not an extra leaf limit.
    """
    C, Bp, A = [[polynomial.get((i, j), Q(0)) for j in range(3)] for i in range(3)]
    Dp = [Q(0)]*5
    for i in range(3):
        for j in range(3):
            Dp[i+j] += Bp[i]*Bp[j]-4*A[i]*C[j]
    polys = [_trim(p) for p in (A, Bp, C, [sum(v) for v in zip(A, Bp, C)], Dp)]
    degree = sum(max(0, len(p)-1) for p in polys)
    delta = target/(8*bound*(degree+2))
    capacity.prepare((tuple(polynomial.values()), target, bound, delta))
    brackets = []
    def evaluate(p, x):
        y = Q(0)
        for v in reversed(p):
            y = y*x+v
        return y
    for p in polys:
        if len(p) <= 1:
            continue
        chain = [p, [i*p[i] for i in range(1, len(p))]]
        while chain[-1]:
            r, divisor = list(chain[-2]), chain[-1]
            while len(r) >= len(divisor):
                q, shift = r[-1]/divisor[-1], len(r)-len(divisor)
                for i, v in enumerate(divisor):
                    r[i+shift] -= q*v
                _trim(r)
            if not r:
                break
            # Positive normalisation preserves Sturm signs and avoids needless
            # coefficient growth in subsequent exact Horner predicates.
            scale = abs(r[-1]); chain.append([-v/scale for v in r])
        arena.keep(tuple(v for row in chain for v in row), len(chain))
        def variation(x):
            _cancel(cancel)
            arena.work(sum(len(row) for row in chain))
            signs = [1 if v > 0 else -1 for row in chain if (v := evaluate(row, x))]
            return sum(a != b for a, b in zip(signs, signs[1:]))
        if evaluate(p, Q(0)) == 0:
            capacity.append(brackets, (Q(0), min(Q(1), delta)))
        stack = []
        capacity.append(stack, (Q(0), Q(1), variation(Q(0)), variation(Q(1))))
        while stack:
            capacity.prepare(stack[-1])
            a, b, va, vb = capacity.pop(stack)
            if va == vb:
                continue
            if b-a <= delta:
                capacity.append(brackets, (max(Q(0), a-delta), min(Q(1), b+delta)))
                continue
            mid = (a+b)/2; vm = variation(mid)
            capacity.append(stack, (a, mid, va, vm))
            capacity.append(stack, (mid, b, vm, vb))
    merged = []
    for a, b in sorted(brackets):
        capacity.prepare((a, b))
        if merged and a <= merged[-1][1]:
            old = capacity.pop(merged)
            capacity.append(merged, (old[0], max(b, old[1])))
        else:
            capacity.append(merged, (a, b))
    capacity.prepare(merged, slots=max(8, 2*len(merged)+2))
    cuts = sorted({Q(0), Q(1), *(q for pair in merged for q in pair)})
    capacity.prepare(cuts, slots=max(8, len(cuts)+2))
    parts = []
    for pair in zip(cuts, cuts[1:]):
        capacity.append(parts, pair)
    capacity.clear(brackets)
    capacity.clear(merged)
    return parts


def negative_bounds(polynomial, *, target_width, max_leaves, budget, bernstein_range, cancel=None, _arena=None):
    """Return exact rational enclosure of integral max(-p,0) on the unit face."""
    source_digest(); _cancel(cancel)
    width = sum((q.numerator.bit_length()+q.denominator.bit_length()+7)//8
                for q in (*polynomial.values(), target_width))
    from contextlib import nullcontext
    if _arena is not None and _arena.resource is not budget:
        raise V.VolumeError('shared Q2 Taylor arena has another budget')
    with budget.reserve((2 << 20)+64*width, category='native-Q2-directed-Taylor'), \
            _Q2Capacity(budget) as capacity, \
            (B._Arena(budget) if _arena is None else nullcontext(_arena)) as arena:
        capacity.prepare(tuple(polynomial.values()))
        J = _Jets()
        coeff = [_trim([polynomial.get((i,j),Q(0)) for j in range(3)]) for i in range(3)]
        common = _common_factor(coeff[1:])
        remainder = _divide(coeff[0],common)[1] if len(common)>1 else []
        constant = remainder[0] if len(remainder)==1 else Q(0)
        if constant:
            base = dict(polynomial);base[(0,0)]=base.get((0,0),Q(0))-constant
            base = {key:v for key,v in base.items() if v}
            # The positive-part map is 1-Lipschitz. On rectangles whose old
            # and shifted signs agree, its correction is exactly -delta*area
            # or zero. Only the sign-uncertain area pays the Lipschitz bound.
            # These leaves and the base integral share ONE caller ceiling.
            def correction(bounds):
                _cancel(cancel)
                capacity.prepare((bounds, tuple(base.values())))
                arena.work(32+64*len(base))
                low, high = bernstein_range(base, bounds)
                area = (bounds[0][1]-bounds[0][0])*(bounds[1][1]-bounds[1][0])
                if low >= 0 and low+constant >= 0:
                    return Q(0),Q(0)
                if high <= 0 and high+constant <= 0:
                    return -constant*area,-constant*area
                return min(Q(0),-constant*area),max(Q(0),-constant*area)
            unit = ((Q(0),Q(1)),)*2
            cl,ch = correction(unit); cq=[]; count=1; serial=0
            capacity.append(cq, (cl-ch,0,unit,cl,ch))
            # At most half of the leaf allocation is spent on the inexpensive
            # correction proof; otherwise retain the full analytic algorithm.
            while ch-cl > target_width/2 and count < max_leaves//2 and cq:
                capacity.prepare((cq[0],cl,ch))
                _,_,bounds,a,b=capacity.pop(cq,heap=True); cl-=a;ch-=b
                candidates=[]
                for axis in range(2):
                    mid=sum(bounds[axis])/2; children=[]
                    for pair in ((bounds[axis][0],mid),(mid,bounds[axis][1])):
                        child=list(bounds);child[axis]=pair;child=tuple(child)
                        a,b=correction(child);children.append((child,a,b))
                    candidates.append((sum(b-a for _,a,b in children),
                                       -(bounds[axis][1]-bounds[axis][0]),axis,children))
                # Only the selected partition is retained; all trial exact
                # predicates are charged, and only its two leaves are used.
                for child,a,b in min(candidates)[3]:
                    cl+=a;ch+=b;serial+=1
                    if a<b: capacity.append(cq,(a-b,serial,child,a,b),heap=True)
                count+=1
                capacity.prepare((cl,ch,candidates))
            # Only the two correction totals continue into the recursive
            # base solve (or full analytic fallback), not the retired heap
            # or rejected trial partitions. The frame's admitted maximum
            # remains owned until return, including recursive overlap.
            capacity.clear(cq)
            candidates=children=[]
            capacity.prepare((cl,ch))
            if ch-cl < target_width and count < max_leaves:
                bl,bh,used=negative_bounds(base,target_width=target_width-(ch-cl),
                    max_leaves=max_leaves-count,budget=budget,bernstein_range=bernstein_range,cancel=cancel,
                    _arena=_arena)
                return bl+cl,bh+ch,used+count
        def leaf(bounds):
            _cancel(cancel)
            capacity.prepare((bounds, tuple(polynomial.values())))
            arena.work(4*(ORDER+1)**2)
            net = sum((v/Q(i+1)*(bounds[1]**(j+1)-bounds[0]**(j+1))/Q(j+1)
                       for (i, j), v in polynomial.items()), Q(0))
            lo, hi = bernstein_range(polynomial, ((Q(0), Q(1)), bounds))
            if lo >= 0:
                return Q(0), Q(0)
            if hi <= 0:
                return -net, -net
            area = bounds[1]-bounds[0]
            fallback = max(Q(0), -net), min(-lo*area, hi*area-net)
            upper = _parabola_upper(polynomial, bounds, J)
            if upper is None:
                upper = _parabola_upper({k:-v for k,v in polynomial.items()}, bounds, J)
                if upper is not None:
                    upper -= net
            if upper is not None:
                fallback = fallback[0], min(fallback[1], upper)
            try:
                derivatives = _negative_primitive(polynomial, bounds, J)
                centre = sum(bounds)/2
                coefficients = _negative_primitive(polynomial, (centre, centre), J)
                radius = area/2
                value = J.zero
                for k in range(0, ORDER, 2):
                    value = J.I.add(value, J.I.mul(coefficients[k], J.I.point(2*radius**(k+1)/Q(k+1))))
                value = J.I.add(value, J.I.mul(derivatives[ORDER],
                    J.I.point(2*radius**(ORDER+1)/Q(ORDER+1))))
                result = max(fallback[0], Q(value[0])), min(fallback[1], Q(value[1]))
                if result[0] > result[1]:
                    raise V.VolumeError('analytic Q2 integral contradicts exact Bernstein enclosure')
                return result
            except _Branch:
                return fallback
        fullrange = bernstein_range(polynomial, ((Q(0), Q(1)),)*2)
        bound = max(abs(q) for q in fullrange)
        parts = _events(polynomial, target_width, bound, arena, cancel, capacity=capacity)
        if len(parts) > max_leaves:
            raise V.VolumeError('Q2 directed-volume quadrature leaf ceiling reached at root events; no flux accepted')
        lo, hi, queue = Q(0), Q(0), []
        for serial, bounds in enumerate(parts):
            capacity.prepare((bounds,lo,hi))
            a, b = leaf(bounds); lo += a; hi += b
            capacity.prepare((lo,hi,a,b))
            if b > a:
                capacity.append(queue, (a-b, serial, bounds, a, b), heap=True)
        leaves, serial = len(parts), len(parts)
        while hi-lo > target_width:
            if leaves >= max_leaves or not queue:
                error = V.VolumeError('Q2 directed-volume quadrature leaf ceiling reached; no flux accepted')
                error.directed_details = dict(width=float(hi-lo), target=float(target_width),
                    worst=[dict(bounds=list(map(float, row[2])), width=float(row[4]-row[3]))
                           for row in sorted(queue)[:8]])
                raise error
            capacity.prepare((queue[0],lo,hi))
            _, _, bounds, old_lo, old_hi = capacity.pop(queue,heap=True)
            centre = sum(bounds)/2
            lo -= old_lo; hi -= old_hi
            for child in ((bounds[0], centre), (centre, bounds[1])):
                a, b = leaf(child); lo += a; hi += b; serial += 1
                capacity.prepare((lo,hi,a,b))
                if b > a:
                    capacity.append(queue, (a-b, serial, child, a, b), heap=True)
            leaves += 1
        source_digest(); _cancel(cancel)
        return lo, hi, leaves
