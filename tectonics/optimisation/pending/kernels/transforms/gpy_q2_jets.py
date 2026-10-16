"""G-PY (WP24): moving-face Decimal-80 jet products with per-coefficient interval classes.

Source transform of atlas_tectonics/integration_moving_face_moments.py (the composed
candidate final-f2's file, reviewed input below). Pure Python, no new file, no new software.
_Jets.mul (plain _Jets, after the unchanged zero and integer-convolution routes) and
_Jets.div (plain _Jets) over plain integration_q2_directed._Intervals run the SAME Decimal
operations in the same order as the code they precede: for each product the point pair
(lo/hi multiply of the first endpoints), else the four-corner builtin-min/max rule when any
endpoint is zero (all four products, replacement only on a strict comparison, so the first
of equal zeros is kept), else the sign-class corners of _Intervals.mul (two candidates each
for mixed x mixed), then lo.add/hi.add from the jet's own zero start; mul skips the same
non-live coefficients as the fused route, div skips none. What changes: each coefficient's
point flag, zero test and sign class are computed once per jet instead of once per product,
and _Intervals.mul/add are inlined. Any coefficient that is not a 2-tuple of finite Decimals,
any other length, a subclass or instance-level methods on the interval object send the call
to the unchanged original route. Decimal context flags on lo/hi may be set in a different
order before an exception; no heat or geometry code reads them.
r2 (16 Oct, refuter DEFECT 1 + zero-identity RISK): jets that are not exactly tuples go to the
original route before any len() (r1 raised its own TypeError text for generators, iterators and
None); a mul coefficient with no live product is the jet's own zero object, as in the original
(r1 built an equal new tuple, which pickles differently).
r3 (16 Oct, delta refuter DEFECT A, contract only): the jet's zero must itself pass the coefficient
test (exactly a tuple of two finite Decimals) before it is compared with (0, 0); r2 compared first, so a
tuple-subclass zero with its own __ne__/__iter__ or an (sNaN, sNaN) zero took the classed route.
Record identity: numbers and their Decimal representations identical; the file digest
changes (D-b).
"""
from hashlib import sha256

INPUT_SHA256 = {
    'c5f2a1230f9e13633ad92f9a251ee01e08bac0b2905d9fed90c042402adb8075':
        'integration_moving_face_moments.py of the composed candidate final-f2 (T/gg/final-f2)',
}
MARK = '# G-PY: jet products by per-coefficient interval classes'

HELPER = MARK + ''' (T/ck/transforms/gpy_q2_jets.py).
from decimal import Decimal as _GPY_DECIMAL

_GPY_ZERO = (_GPY_DECIMAL(0), _GPY_DECIMAL(0))
# (low corner, high corner) of _Intervals.mul per sign-class pair; mixed x mixed is separate.
_GPY_CORNERS = {(1, 1): ((0, 0), (1, 1)), (1, 2): ((1, 0), (0, 1)), (1, 3): ((1, 0), (1, 1)),
                (2, 1): ((0, 1), (1, 0)), (2, 2): ((1, 1), (0, 0)), (2, 3): ((0, 1), (0, 0)),
                (3, 1): ((0, 1), (1, 1)), (3, 2): ((1, 0), (0, 0))}


def _gpy_plain(J):
    """A plain _Jets over a plain Decimal _Intervals whose zero is a plain tuple of two finite Decimals equal to 0."""
    I = J.I
    zero = J.zero
    return (type(J) is _Jets and type(I) is _Intervals
            and not any(name in I.__dict__ for name in ('mul', 'add', 'sub', 'div', 'neg'))
            and _gpy_class(zero) is not None and zero == _GPY_ZERO)


def _gpy_class(x):
    """(live, point, class) as _Intervals.mul tests them; class 0 = a zero endpoint, 1 > 0, 2 < 0, 3 mixed."""
    if type(x) is not tuple or len(x) != 2 or type(x[0]) is not _GPY_DECIMAL or type(x[1]) is not _GPY_DECIMAL:
        return None
    x0, x1 = x
    if not (x0.is_finite() and x1.is_finite()):
        return None
    if x0.is_zero() or x1.is_zero():
        cls = 0
    elif x0 > 0:
        cls = 1
    elif x1 < 0:
        cls = 2
    else:
        cls = 3
    return (x != _GPY_ZERO, x0 == x1, cls)


def _gpy_product(lm, hm, x, kx, y, ky):
    """_Intervals.mul(x, y) from the classes of x and y."""
    if kx[1] and ky[1]:
        return lm(x[0], y[0]), hm(x[0], y[0])
    cx, cy = kx[2], ky[2]
    if cx == 0 or cy == 0:
        x0, x1 = x
        y0, y1 = y
        p0 = lm(x0, y0)
        t = lm(x0, y1)
        if t < p0:
            p0 = t
        t = lm(x1, y0)
        if t < p0:
            p0 = t
        t = lm(x1, y1)
        if t < p0:
            p0 = t
        p1 = hm(x0, y0)
        t = hm(x0, y1)
        if t > p1:
            p1 = t
        t = hm(x1, y0)
        if t > p1:
            p1 = t
        t = hm(x1, y1)
        if t > p1:
            p1 = t
        return p0, p1
    if cx == 3 and cy == 3:
        return min(lm(x[0], y[1]), lm(x[1], y[0])), max(hm(x[0], y[0]), hm(x[1], y[1]))
    (li, lj), (hi, hj) = _GPY_CORNERS[cx, cy]
    return lm(x[li], y[lj]), hm(x[hi], y[hj])


def _gpy_mul(J, a, b):
    """J.mul(a, b) for a plain J after its zero/convolution routes, or None for the original."""
    if type(a) is not tuple or type(b) is not tuple or len(a) != ORDER+1 or len(b) != ORDER+1:
        return None
    ka = [_gpy_class(x) for x in a]
    kb = [_gpy_class(y) for y in b]
    if None in ka or None in kb:
        return None
    lm, hm, la, ha = J.I.lo.multiply, J.I.hi.multiply, J.I.lo.add, J.I.hi.add
    zero = J.zero
    z0, z1 = zero
    result = []
    for k in range(ORDER+1):
        v0, v1, live = z0, z1, False
        for i in range(k+1):
            kx, ky = ka[i], kb[k-i]
            if kx[0] and ky[0]:
                p0, p1 = _gpy_product(lm, hm, a[i], kx, b[k-i], ky)
                v0 = la(v0, p0)
                v1 = ha(v1, p1)
                live = True
        result.append((v0, v1) if live else zero)
    return tuple(result)


def _gpy_div(J, a, b):
    """J.div(a, b) for a plain J, or None for the original."""
    if type(a) is not tuple or type(b) is not tuple or len(a) != ORDER+1 or len(b) != ORDER+1:
        return None
    kb = [_gpy_class(y) for y in b]
    if None in kb:
        return None
    I = J.I
    lm, hm, la, ha = I.lo.multiply, I.hi.multiply, I.lo.add, I.hi.add
    z0, z1 = J.zero
    result, kr = [], []
    for k in range(ORDER+1):
        t0, t1 = z0, z1
        for i in range(1, k+1):
            p0, p1 = _gpy_product(lm, hm, b[i], kb[i], result[k-i], kr[k-i])
            t0 = la(t0, p0)
            t1 = ha(t1, p1)
        value = I.div(I.sub(a[k], (t0, t1)), b[0])
        known = _gpy_class(value)
        if known is None:
            return None
        result.append(value)
        kr.append(known)
    return tuple(result)


class _Jets:
'''

REPLACEMENTS = (
    ('''\
        # Same products, same order, same zero start as the line above; each
        # coefficient is compared with zero once instead of once per k.
''', '''\
        if _gpy_plain(self):
            classed = _gpy_mul(self, a, b)
            if classed is not None:
                return classed
        # Same products, same order, same zero start as the line above; each
        # coefficient is compared with zero once instead of once per k.
'''),
    ('''\
    def div(self, a, b):
        result = []
        for k in range(ORDER+1):
            tail = self._sum(self.I.mul(b[i], result[k-i]) for i in range(1, k+1))
''', '''\
    def div(self, a, b):
        if _gpy_plain(self):
            classed = _gpy_div(self, a, b)
            if classed is not None:
                return classed
        result = []
        for k in range(ORDER+1):
            tail = self._sum(self.I.mul(b[i], result[k-i]) for i in range(1, k+1))
'''),
)


def transform(source, *, allow_unreviewed_input=False):
    if MARK in source:
        raise ValueError('G-PY transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in INPUT_SHA256:
        raise ValueError('moving-face input is not the reviewed final-f2 file')
    anchor = '\nclass _Jets:\n'
    if (source.count(anchor) != 1
            or 'from .integration_q2_directed import _Intervals, _Branch\n' not in source
            or '\nORDER = 12\n' not in source):
        raise ValueError('G-PY expects one _Jets class, the q2 _Intervals import and ORDER 12')
    for old, _ in REPLACEMENTS:
        if source.count(old) != 1:
            raise ValueError('G-PY anchor must occur exactly once: %r' % old.splitlines()[0])
    source = source.replace(anchor, '\n' + HELPER)
    for old, new in REPLACEMENTS:
        source = source.replace(old, new)
    return source


if __name__ == '__main__':
    import sys
    from pathlib import Path
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    if dst.exists():
        raise SystemExit('%s exists' % dst)
    before = src.read_bytes()
    after = transform(before.decode('utf8')).encode('utf8')
    dst.write_bytes(after)
    print(src.name, sha256(before).hexdigest(), '->', sha256(after).hexdigest())
