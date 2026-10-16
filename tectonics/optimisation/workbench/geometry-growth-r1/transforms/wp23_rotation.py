"""WP23 (interface stall): exact reuse + gmpy2 arithmetic for _rotation_boxes / _bernstein_range.

Source transform of atlas_tectonics/integration_differential_geometry.py for the
Step 10 (WP9) composition. Target: the measured IV2 moving-interface stall, where
_rotation_boxes (with _bernstein_range inside it) is about 64% of interface CPU.

1. Exact reuse. _rotation_boxes is a pure function of (vector box, omega, a, b,
   level). Results are kept per query on the caller's arena (bounded: 4096 entries,
   each charged with arena.keep). On a hit, the original arena.work charges are
   replayed in their original order and sizes, so work_units, predicate-budget
   admission and refusals are identical; the transient arithmetic-workspace
   reservation (V._work) is not taken because no arithmetic is done.
2. Same arithmetic in gmpy2 mpq. The power-series terms, interval cross products
   and the Bernstein conversion run on exact mpq values; results are converted to
   canonical Fractions at the boundary, so every returned value is identical. The
   V._work reservations keep their exact sizes (bit lengths are equal). Without
   gmpy2 the original Fraction code runs unchanged.
Records are byte-identical on saved IV1/IV2 queries (see the hand-off evidence).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    'fc9dd85e002fe54db6e409ebe89083996f62611c40d958a5a1e60184f3424253': 'RC1 composed-r1 runtime-src',
}

OLD_DEF = 'def _rotation_boxes(vector, omega, a, b, level, arena):\n'
NEW_DEF = 'def _rotation_boxes_fraction(vector, omega, a, b, level, arena):\n'
OLD_BERN = 'def _bernstein_range(coefficients, a, b):\n'
NEW_BERN = 'def _bernstein_range_fraction(coefficients, a, b):\n'
ANCHOR_AFTER = 'def _ray_component_boxes(ray, a, b, level, arena):\n'

HELPER = '''
try:
    import gmpy2 as _wp23_gmp
    _wp23_mpq = _wp23_gmp.mpq
except ImportError:          # the original Fraction route remains complete
    _wp23_gmp = _wp23_mpq = None
_WP23_MEMO_LIMIT = 4096


def _wp23_bits(value):
    return max(1, int(value.numerator).bit_length()+int(value.denominator).bit_length())


def _wp23_work(values, budget):
    """The exact V._work reservation size and category, for mpq operands."""
    bits = sum(_wp23_bits(v) for v in values)
    return V.select_budget(budget).reserve(65536+128*bits+256*len(values), category='i03-physical-volume')


def _wp23_fraction(value):
    return Q(int(value.numerator), int(value.denominator))


def _wp23_product(first, second):
    values = (first[0]*second[0], first[0]*second[1], first[1]*second[0], first[1]*second[1])
    return min(values), max(values)


def _wp23_cross(a, b):
    out = []
    for j in range(3):
        left = _wp23_product(a[(j+1) % 3], b[(j+2) % 3])
        right = _wp23_product(a[(j+2) % 3], b[(j+1) % 3])
        out.append((left[0]-right[1], left[1]-right[0]))
    return tuple(out)


def _wp23_bernstein(coefficients, a, b):
    """_bernstein_range_fraction's exact arithmetic on mpq values (mpq in, mpq out)."""
    mpq = _wp23_mpq
    degree = len(coefficients)-1
    if a == b:
        low = high = mpq(0)
        for k in range(degree+1):
            factor = mpq(math.comb(k, 0))*a**k
            p = _wp23_product(coefficients[k], (factor, factor))
            low += p[0]; high += p[1]
        return low, high
    width = b-a
    power = []
    for j in range(degree+1):
        low = high = mpq(0)
        for k in range(j, degree+1):
            factor = mpq(math.comb(k, j))*a**(k-j)*width**j
            p = _wp23_product(coefficients[k], (factor, factor))
            low += p[0]; high += p[1]
        power.append((low, high))
    lows, highs = [], []
    for j in range(degree+1):
        low = high = mpq(0)
        for k in range(j+1):
            factor = mpq(math.comb(j, k), math.comb(degree, k))
            p = _wp23_product(power[k], (factor, factor))
            low += p[0]; high += p[1]
        lows.append(low); highs.append(high)
    return min(lows), max(highs)


def _bernstein_range(coefficients, a, b):
    """Enclose a power polynomial on [a,b] (WP23: exact mpq route, identical values)."""
    if (_wp23_mpq is None or type(a) is not Q or type(b) is not Q or type(coefficients) is not tuple
            or not coefficients or not all(type(pair) is tuple and len(pair) == 2 and
                                           all(type(q) is Q for q in pair) for pair in coefficients)):
        return _bernstein_range_fraction(coefficients, a, b)
    mpq = _wp23_mpq
    low, high = _wp23_bernstein(tuple((mpq(lo), mpq(hi)) for lo, hi in coefficients), mpq(a), mpq(b))
    return _wp23_fraction(low), _wp23_fraction(high)


def _wp23_rotation_compute(vector, omega, a, b, level, arena, charges):
    """_rotation_boxes_fraction on mpq values; records each arena.work charge."""
    mpq = _wp23_mpq
    if a > b:
        raise V.VolumeError('rotation time bracket reversed')
    if not any(omega) or a == b == 0:
        return vector
    w = tuple(mpq(q) for q in omega)
    fixed = tuple((q, q) for q in w)
    box = tuple((mpq(lo), mpq(hi)) for lo, hi in vector)
    first = _wp23_cross(fixed, box)
    second = _wp23_cross(fixed, first)
    inactive = tuple(first[j][0] == first[j][1] == second[j][0] == second[j][1] == 0 for j in range(3))
    if all(inactive):
        return vector
    norm = max(max(abs(lo), abs(hi)) for lo, hi in box)
    matrix_norm = max(abs(w[1])+abs(w[2]), abs(w[0])+abs(w[2]), abs(w[0])+abs(w[1]))
    qa, qb = mpq(a), mpq(b)
    time = max(abs(qa), abs(qb))
    target = norm/mpq(2**(32+2*level))
    terms, term, major, order = [box], box, norm, 0
    while True:
        following = major*matrix_norm/(order+1)
        ratio = time*matrix_norm/(order+2)
        if ratio < 1 and following*time**(order+1)/(1-ratio) <= target:
            tail = following/(1-ratio)
            break
        charges.append(128+32*order)
        arena.work(128+32*order)
        values = (*w, qa, qb, major, *(q for pair in term for q in pair))
        with _wp23_work(values, arena.resource):
            term = tuple((lo/(order+1), hi/(order+1)) for lo, hi in _wp23_cross(fixed, term))
            terms.append(term)
            major = following
            order += 1
    charges.append(128*len(terms)**2)
    arena.work(128*len(terms)**2)
    zero = mpq(0)
    with _wp23_work((*w, qa, qb, tail, *(q for t in terms for pair in t for q in pair)), arena.resource):
        out = []
        for j in range(3):
            coefficients = tuple(t[j] for t in terms)+(((zero, zero) if inactive[j] else (-tail, tail)),)
            low, high = _wp23_bernstein(coefficients, qa, qb)
            out.append((_wp23_fraction(low), _wp23_fraction(high)))
        return tuple(out)


def _rotation_boxes(vector, omega, a, b, level, arena):
    """Componentwise enclosure of exp([omega]x t) applied to a vector box.

    WP23: identical results to _rotation_boxes_fraction (exact mpq arithmetic) and
    exact per-query reuse with the original work charges replayed on a hit.
    """
    # Fractions only: with ints the original arithmetic could return ints, and
    # downstream code distinguishes types. Anything else takes the original route.
    if (_wp23_mpq is None or type(level) is not int or type(a) is not Q or type(b) is not Q
            or type(vector) is not tuple or type(omega) is not tuple or len(vector) != 3 or len(omega) != 3
            or not all(type(q) is Q for q in omega)
            or not all(type(pair) is tuple and len(pair) == 2 and all(type(q) is Q for q in pair)
                       for pair in vector)):
        return _rotation_boxes_fraction(vector, omega, a, b, level, arena)
    memo = getattr(arena, '_wp23_rotation_memo', None)
    key = (tuple(vector), tuple(omega), a, b, level)
    if memo is not None:
        hit = memo.get(key)
        if hit is not None:
            result, charges = hit
            for count in charges:
                arena.work(count)
            return result
    charges = []
    result = _wp23_rotation_compute(vector, omega, a, b, level, arena, charges)
    if memo is None:
        try:
            memo = arena._wp23_rotation_memo = {}
        except AttributeError:
            return result
    if len(memo) < _WP23_MEMO_LIMIT:
        arena.keep((*(q for pair in vector for q in pair), *omega, a, b,
                    *(q for pair in result for q in pair)), objects=2)
        memo[key] = (result, tuple(charges))
    return result


'''


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('WP23 rotation anchor must occur exactly once: ' + old[:60])
    return source.replace(old, new)


def transform(source, *, allow_unreviewed_input=False):
    if '_wp23_rotation_compute' in source:
        raise ValueError('WP23 rotation transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('WP23 rotation input is not the reviewed geometry; pass allow_unreviewed_input and re-run parity')
    if '\nimport math\n' not in source:
        raise ValueError('geometry module must import math')
    source = _once(source, OLD_DEF, NEW_DEF)
    source = _once(source, OLD_BERN, NEW_BERN)
    source = _once(source, ANCHOR_AFTER, HELPER.lstrip('\n') + ANCHOR_AFTER)
    return source
