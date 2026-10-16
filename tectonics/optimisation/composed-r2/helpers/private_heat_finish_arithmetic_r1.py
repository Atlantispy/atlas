"""Standalone exact arithmetic needed ONLY by the private heat finisher.

Import is stdlib-only. Computation requests Atlas's ALREADY selected exact
library at method invocation; Python-backend imports work, while a calculation
requiring MPFR explicitly refuses. There is no silent backend switch.

This extraction preserves directed rounding, exact fallback bit ceiling,
correctly rounded Fraction-to-float conversion, 64 feasible scalar refinements
and the shared-face global identity. No solver, geometry, control driver,
native result origin or WorkBudget admission is imported or claimed.
"""
from collections.abc import Sequence
from concurrent.futures import CancelledError
from fractions import Fraction as Q
from hashlib import sha256
from pathlib import Path

_SOURCES = {str(Path(__file__).resolve()): sha256(Path(__file__).read_bytes()).hexdigest()}


class ExactBackendUnavailable(RuntimeError):
    pass


def exact_library():
    """Use the native selected backend, never import gmpy2 or select one here."""
    from atlas_tectonics.exact_arithmetic import library
    backend = library()
    if backend is None:
        raise ExactBackendUnavailable('This exact/MPFR finisher requires the selected native GMP backend; Python-backend import is supported but execution is not')
    return backend


def rational(value):
    G = exact_library()
    if isinstance(value, G.mpq):
        return value
    if isinstance(value, (tuple, list)):
        return G.mpq(G.mpz(value[0]), G.mpz(value[1]))
    value = Q(value)
    return G.mpq(value.numerator, value.denominator)

def public_float(value):
    # Match r2's Python Fraction -> float stock conversion explicitly.
    return float(Q(int(value.numerator), int(value.denominator)))

def feasible_scalar(predicate):
    G = exact_library()
    history = []

    def test(theta):
        passed = bool(predicate(theta))
        history.append(dict(theta=theta, passed=passed))
        return passed

    if test(G.mpq(1)):
        return G.mpq(1), dict(status='FULL_CANDIDATE_CERTIFIED', refinements=0,
                              evaluations=history, maximality_claimed=False)
    if not test(G.mpq(0)):
        raise ValueError('Refused: low endpoint fails exact or actual public certification')
    lower, upper = G.mpq(0), G.mpq(1)
    for _ in range(64):
        middle = (lower+upper)/2
        if test(middle):
            lower = middle
        else:
            upper = middle
    assert upper-lower == G.mpq(1, 2**64)
    assert predicate(lower)
    return lower, dict(status='FEASIBLE_COMMON_SCALAR_CERTIFIED', refinements=64,
        evaluations=history, final_upper=upper, maximality_claimed=False,
        invariant='Only a directly tested feasible state replaces the lower endpoint; no monotonicity premise.')

class UnresolvedQuadraticSign(ArithmeticError):
    """No sign is issued; never reinterpret this refusal as true or false."""
    def __init__(self, message, evidence):
        super().__init__(message)
        self.evidence = evidence

class Unresolved(ArithmeticError):
    """No finite directed enclosure issued."""


class SupplyGuardRefused(ValueError):
    def __init__(self, message, evidence):
        super().__init__(message)
        self.evidence = evidence


class Arithmetic:
    """Explicit contexts prevent dependence on or changes to global precision."""
    def __init__(self, precision, cancelled=None, evidence=None):
        G = exact_library()
        self.backend = G
        options = dict(precision=precision, trap_underflow=True, trap_overflow=True,
                       trap_invalid=True, trap_divzero=True, trap_erange=True)
        self.down = G.context(**options, round=G.RoundDown)
        self.up = G.context(**options, round=G.RoundUp)
        self.near = G.context(**options, round=G.RoundToNearest)
        self.cancelled, self.evidence = cancelled, evidence
        with self.near:
            self.zero, self.one = G.mpfr(0), G.mpfr(1)

    def check(self, phase):
        if self.evidence is not None:
            self.evidence['phase'] = phase
        if self.cancelled is not None and self.cancelled():
            raise CancelledError('Interval functional cancelled at '+phase)

    def point(self, q):
        G = self.backend
        self.check('directed-input')
        with self.down:
            lo = G.mpfr(q)
        with self.up:
            hi = G.mpfr(q)
        if not G.is_finite(lo) or not G.is_finite(hi):
            raise Unresolved('Nonfinite interval input')
        return lo, hi

    def add(self, a, b):
        self.check('interval-add')
        return self.down.add(a[0], b[0]), self.up.add(a[1], b[1])

    def mul(self, a, b):
        self.check('interval-product')
        return (min(self.down.mul(x, y) for x in a for y in b),
                max(self.up.mul(x, y) for x in a for y in b))


def _quadratic_q(value):
    G = exact_library()
    try:
        return G.mpq(value)
    except (ValueError, TypeError, OverflowError, ZeroDivisionError) as error:
        raise ValueError('Finite represented rational energies/capacities required') from error

def quadratic_nonincrease(old, new, capacity, *, precisions=(320, 640, 1280, 2560),
                          exact_fallback=True, exact_fallback_bit_limit=65536,
                          cancelled=None, evidence=None):
    """Return a certified boolean for sum(new^2-old^2)/(2*C)<=0, or refuse.

    All three arrays must have the same nonzero length; capacities are positive.
    Fallback bit caps are conservative prospective arithmetic-size checks, NOT
    a physical tolerance. They may refuse an algebraically reducible operation.
    This helper performs no native WorkBudget admission or runtime guarantee.
    """
    G = exact_library()

    def check():
        if cancelled is not None and cancelled():
            raise CancelledError('Quadratic sign certification cancelled')

    def verify_sources():
        for path, pin in _SOURCES.items():
            check()
            if sha256(Path(path).read_bytes()).hexdigest() != pin:
                raise ValueError('Quadratic sign helper source changed since import')

    check()
    verify_sources()
    arrays = old, new, capacity
    if (any(not isinstance(a, Sequence) or isinstance(a, (str, bytes)) for a in arrays)
            or not old or len(old) != len(new) or len(old) != len(capacity)):
        raise ValueError('Complete matching nonempty energy/capacity arrays required')
    if (not isinstance(precisions, (tuple, list)) or not precisions
            or any(type(p) is not int or p < 2 for p in precisions)
            or any(a >= b for a, b in zip(precisions[:-1], precisions[1:], strict=True))):
        raise ValueError('Explicit strictly increasing MPFR precisions >=2 required')
    if type(exact_fallback) is not bool or type(exact_fallback_bit_limit) is not int or exact_fallback_bit_limit < 1:
        raise ValueError('Explicit fallback policy and positive arithmetic bit limit required')
    audit = {} if evidence is None else evidence
    audit.update(schema='atlas.private-quadratic-sign.r1', sources=dict(_SOURCES),
        predicate='sum_i((new_i-old_i)*(new_i+old_i)/(2*C_i)) <= 0',
        physical_predicate_changed=False, native_workbudget_admitted=False,
        exact_fallback_bit_limit=exact_fallback_bit_limit, attempts=[], exact_fallback_executed=False)
    factors = []
    for before, after, cap in zip(old, new, capacity, strict=True):
        check()
        before, after, cap = _quadratic_q(before), _quadratic_q(after), _quadratic_q(cap)
        if cap <= 0:
            raise ValueError('Strictly positive exact represented capacities required')
        factors.append((after-before, after+before, G.mpq(1)/(2*cap)))

    def issue(route, bounds, precision, exact=None):
        check()
        verify_sources()
        audit.update(route=route, precision_bits=precision, bounds=bounds,
            nonincrease=(exact <= 0 if exact is not None else bounds[1] <= 0),
            exact_change=exact, exact_numeric_value_materialised=exact is not None,
            exact_zero_proved=bounds == (G.mpq(0), G.mpq(0)))
        return dict(audit)

    for precision in precisions:
        check()
        ar = Arithmetic(precision, cancelled=check)
        total = (ar.zero, ar.zero)
        for delta, sigma, factor in factors:
            ar.check('quadratic-interval-term')
            term = ar.mul(ar.mul(ar.point(delta), ar.point(sigma)), ar.point(factor))
            total = ar.add(total, term)
        bounds = tuple(map(G.mpq, total))
        audit['attempts'].append(dict(precision_bits=precision, bounds=bounds,
                                     status='SIGN_PROVED' if bounds[1] <= 0 or bounds[0] > 0 else 'ZERO_STRADDLING'))
        if bounds[1] <= 0:
            return issue('DIRECTED_INTERVAL_NONPOSITIVE', bounds, precision)
        if bounds[0] > 0:
            return issue('DIRECTED_INTERVAL_STRICT_POSITIVE', bounds, precision)
    if not exact_fallback:
        raise UnresolvedQuadraticSign('Quadratic interval contains zero; exact fallback disabled', dict(audit))
    audit['exact_fallback_executed'] = True
    limit = exact_fallback_bit_limit

    def bits(value):
        return abs(value.numerator).bit_length(), value.denominator.bit_length()

    def bounded_product(a, b):
        check()
        if not a or not b:
            return G.mpq(0)
        an, ad = bits(a)
        bn, bd = bits(b)
        if max(an+bn, ad+bd) > limit:
            raise UnresolvedQuadraticSign('Exact quadratic fallback product exceeds explicit bit bound', dict(audit))
        return a*b

    total = G.mpq(0)
    for delta, sigma, factor in factors:
        check()
        term = bounded_product(bounded_product(delta, sigma), factor)
        if not term:
            continue
        if not total or total == -term:
            total += term
            continue
        an, ad = bits(total)
        bn, bd = bits(term)
        if max(max(an+bd, bn+ad)+1, ad+bd) > limit:
            raise UnresolvedQuadraticSign('Exact quadratic fallback sum exceeds explicit bit bound', dict(audit))
        total += term
    return issue('EXACT_ZERO_STRADDLING_FALLBACK', (total, total), precisions[-1], exact=total)

def paired_global_balance(final_energy, loaded_energy, physical_faces, *, cancel=None):
    """Return GMP-exact ``total`` and ``outward`` plus face counts.

    ``loaded_energy`` is old energy plus timestep-integrated source, BEFORE
    exterior debits. Each (i,j,q) uses q outward from i; j=None is exterior.
    Cancellation is checked per cell/face. Individual native exact operations
    remain noninterruptible, but cancelled interior denominators are not built.
    Inputs are read-only. No global residual array is materialised or summed.
    """
    G = exact_library()

    def check():
        if cancel is not None and cancel():
            raise CancelledError('Exact paired global balance cancelled')

    check()
    count = len(final_energy)
    if not count or len(loaded_energy) != count:
        raise ValueError('Complete matching final and source-loaded energy arrays required')
    total, outward = G.mpq(0), G.mpq(0)
    for energy, load in zip(final_energy, loaded_energy, strict=True):
        check()
        total += rational(energy)-rational(load)
    interior_count = boundary_count = 0
    for i, j, amount in physical_faces:
        check()
        if not isinstance(i, int) or not 0 <= i < count or j is not None and (
                not isinstance(j, int) or not 0 <= j < count or j == i):
            raise ValueError('Single shared physical face owners are invalid')
        # Validate exact/finiteness even for interior values; do not accumulate.
        amount = rational(amount)
        if j is None:
            outward += amount
            boundary_count += 1
        else:
            interior_count += 1
    check()
    return dict(total=total+outward, outward=outward, interior_faces=interior_count,
                boundary_faces=boundary_count)


