"""D5 prototype (r1): GMP-resident twins of wall_measures._rotated_normal, _clip2 and _line.

Prototype for measurement and proof only (T/ck/d5/DESIGN.md); not wired into any runtime. Import after the
runtime is installed (rc1_env.install); the twins take the reference modules W, V, O and exact_arithmetic X.
Every twin first checks the type guard of DESIGN sections 4-5; anything else runs the unchanged reference
function. Natives never leave a call; results are new Fractions (or the reference's own input objects where
the reference returns those).
"""
from contextlib import contextmanager
from fractions import Fraction as Q

from atlas_tectonics import exact_arithmetic as X
from atlas_tectonics import integration_volume as V
from atlas_tectonics import integration_wall_measures as W

CEILING_BITS = 1 << 27                         # integration_exact_gmp.CEILING_BITS (32-bit bit counts)
_library = X.library()
if _library is not None:
    mpq = _library.mpq
    _numer, _denom = _library.numer, _library.denom
_from_coprime = getattr(Q, '_from_coprime_ints', None)
REF_CLIP2, REF_ROTATED, REF_LINE = W._clip2, W._rotated_normal, W._line


def native(v):
    """int or Fraction (exact types only; the guards have checked) -> mpq."""
    if type(v) is Q:
        return mpq(v.numerator, v.denominator)
    return mpq(v)


def fraction(q):
    """A new canonical Fraction from a canonical mpq (positive denominator, coprime): no gcd."""
    if _from_coprime is not None:
        return _from_coprime(int(_numer(q)), int(_denom(q)))
    return Q(int(_numer(q)), int(_denom(q)))


def nbits(q):
    """V._bits of the Fraction a non-integer-typed reference value would be (equal for every Fraction)."""
    return max(1, _numer(q).bit_length()+_denom(q).bit_length())


@contextmanager
def lease(bits, count, budget, *, pairs=0):
    """V._work's reservation (amount, category, taken on entry) without its Fraction copy tuple, then
    integration_exact_gmp._work's ceiling check inside it."""
    with V.select_budget(budget).reserve(65536+128*bits+256*count+256*pairs, category='i03-physical-volume'):
        if bits > CEILING_BITS:
            raise V.VolumeError('exact operands exceed the GMP route ceiling of 2**27 bits in one step; '
                                'use ATLAS_EXACT_ARITHMETIC=python')
        yield


def _exact(v):
    return type(v) is int or type(v) is Q


def _triple(v):
    return type(v) is tuple and len(v) == 3 and _exact(v[0]) and _exact(v[1]) and _exact(v[2])


# ---------------------------------------------------------------- T2: _clip2
def _clip2_native(poly, line):
    if not poly:
        return ()
    a, b, c = (native(v) for v in line)
    points = [(native(p[0]), native(p[1])) for p in poly]
    signs = [a*x+b*y+c for x, y in points]
    if min(signs) >= 0:
        return poly
    if max(signs) <= 0:
        return ()
    out, kept = [], []
    n = len(poly)
    for i in range(n):
        j = i+1 if i+1 < n else 0
        sp, sq = signs[i], signs[j]
        if sp >= 0:
            out.append(poly[i])
            kept.append(points[i])
        if sp*sq < 0:
            f = sp/(sp-sq)
            (px, py), (qx, qy) = points[i], points[j]
            x, y = px+f*(qx-px), py+f*(qy-py)
            out.append((fraction(x), fraction(y)))
            kept.append((x, y))
    if len(out) < 3:
        return ()
    return tuple(p for k, p in enumerate(out) if kept[k] != kept[k-1])


def clip2(poly, line, arena=None):
    if (_library is None or type(line) is not tuple or len(line) != 3 or type(line[0]) is not Q
            or type(line[1]) is not Q or type(line[2]) is not Q or type(poly) is not tuple
            or not all(type(p) is tuple and len(p) == 2 and _exact(p[0]) and _exact(p[1]) for p in poly)):
        return REF_CLIP2(poly, line, arena)
    if arena is None:
        return _clip2_native(poly, line)
    bits = sum(V._bits(v) for v in line)+sum(V._bits(q) for p in poly for q in p)
    with lease(bits, 3+2*len(poly), arena.resource):
        return _clip2_native(poly, line)


# ---------------------------------------------------------------- _line
def line(face, normal, offset=0):
    if (_library is None or type(face) is not tuple or len(face) < 3 or not _triple(normal)
            or not _triple(face[0]) or not _triple(face[1]) or not _triple(face[2]) or not _exact(offset)):
        return REF_LINE(face, normal, offset)
    n0, n1, n2 = (native(v) for v in normal)
    out = []
    for k in (1, 2, 0):
        e = face[k]
        out.append(n0*native(e[0])+n1*native(e[1])+n2*native(e[2]))
    out[2] -= native(offset)
    return fraction(out[0]), fraction(out[1]), fraction(out[2])


# ---------------------------------------------------------------- T1: _rotated_normal
def _cross(a, b):
    return a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]


def rotated_normal(normal, omega, t0, t1, level, arena):
    if (_library is None or type(t0) is not Q or type(t1) is not Q or type(level) is not int or level < -16
            or arena is None
            or not _triple(normal) or not _triple(omega)):
        return REF_ROTATED(normal, omega, t0, t1, level, arena)
    w = tuple(native(v) for v in omega)
    nv = tuple(native(v) for v in normal)
    m0, m1 = native(t0), native(t1)
    middle, half = (m0+m1)/2, (m1-m0)/2
    derivative = _cross(w, nv)
    if not any(derivative):
        return normal, Q(0)
    norm_a = max(abs(w[1])+abs(w[2]), abs(w[0])+abs(w[2]), abs(w[0])+abs(w[1]))
    reference_norm_n = max(map(abs, normal))       # its type (int or Fraction) sets the step-0 admission width
    norm_n = native(reference_norm_n)
    x = abs(middle)*norm_a
    target = norm_n/mpq(2**(32+2*level))
    # Admission widths of the reference's operands: omega and middle are the originals throughout; term and
    # major are the originals at step 0 and Fractions afterwards (equal to the native widths).
    fixed_bits = sum(V._bits(v) for v in omega)+nbits(middle)
    term_bits = sum(V._bits(v) for v in normal)
    major_bits = V._bits(reference_norm_n)
    total, term, major, order = list(nv), nv, norm_n, 0
    while True:
        next_major = major*x/(order+1)
        ratio = x/(order+2)
        if ratio < 1 and next_major/(1-ratio) <= target:
            tail = next_major/(1-ratio)
            break
        arena.work(64)
        with lease(term_bits+fixed_bits+major_bits, 8, arena.resource):
            scale = middle/(order+1)
            term = tuple(scale*v for v in _cross(w, term))
            total = [a+b for a, b in zip(total, term, strict=True)]
            major = next_major
        term_bits = nbits(term[0])+nbits(term[1])+nbits(term[2])
        major_bits = nbits(major)
        order += 1
    error = 3*tail+half*sum(map(abs, derivative))
    if order == 0:
        return tuple(list(normal)), fraction(error)   # a NEW tuple of the same objects, as tuple(total)
    return tuple(fraction(t) for t in total), fraction(error)
