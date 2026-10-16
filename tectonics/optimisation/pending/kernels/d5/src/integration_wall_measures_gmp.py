"""GMP-resident twins of integration_wall_measures._rotated_normal, _clip2 and _line.

Each of those functions calls its twin first and runs its own code when the twin returns DECLINED. A twin
declines unless the gmpy2 backend is selected, every reference object involved is still the one loaded
(the three functions, Q, integration_volume._work/_bits/select_budget, integration_volume_overlap._dot/
_cross: wrapped or replaced kernels keep the reference route, so instrumentation sees every call, including
_clip2's own inner call), and the arguments have exactly the types whose results it reproduces. Anything
else, including every error case, is the reference's.

What a twin reproduces: the same rationals, returned as NEW canonical Fractions of Python ints, or as the
reference's own input objects where the reference returns those (_clip2's `poly`, kept vertices and the
untouched `normal`); the same arena.work calls and integration_volume._work reservations (amount, category,
order), from the widths of the reference-typed objects; the same exceptions at the same step. Added only:
_rotated_normal's natives kept across Taylor steps are charged under NATIVE_RETAINED
(integration_exact_twin.Retained), so the twin can refuse earlier, never later.
"""
import sys
from fractions import Fraction as Q
from operator import is_

from . import integration_exact_twin as E
from . import integration_volume as V
from . import integration_volume_overlap as O

DECLINED = object()
_module = None
_loaded = ()


def attach(name):
    """Record the reference objects of the wall-measure module `name` (called once, at its import)."""
    global _module, _loaded
    _module = sys.modules[name]
    _loaded = _current()


def _current():
    W = _module
    return (W._rotated_normal, W._clip2, W._line, W.Q, V._work, V._bits, V.select_budget, O._dot, O._cross)


def _resident():
    return E.available() and _module is not None and all(map(is_, _current(), _loaded))


# ---------------------------------------------------------------- _clip2
def _clip2(poly, line):
    native, fraction = E.native, E.fraction
    if not poly:
        return ()
    a, b, c = native(line[0]), native(line[1]), native(line[2])
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
    # The reference's `p != out[j-1]` on equal rationals, decided on the natives in the same order.
    return tuple(p for k, p in enumerate(out) if kept[k] != kept[k-1])


def clip2(poly, line, arena):
    exact = E.exact
    if (type(line) is not tuple or len(line) != 3 or type(line[0]) is not Q or type(line[1]) is not Q
            or type(line[2]) is not Q or type(poly) is not tuple
            or not all(type(p) is tuple and len(p) == 2 and exact(p[0]) and exact(p[1]) for p in poly)
            or not _resident()):
        return DECLINED
    if arena is None:
        return _clip2(poly, line)
    width = sum(V._bits(v) for v in line)+sum(V._bits(q) for p in poly for q in p)
    with E.lease(width, 3+2*len(poly), arena.resource):
        return _clip2(poly, line)


# ---------------------------------------------------------------- _line
def line(face, normal, offset):
    triple = E.triple
    if (type(face) is not tuple or len(face) < 3 or not triple(normal) or not triple(face[0])
            or not triple(face[1]) or not triple(face[2]) or not E.exact(offset) or not _resident()):
        return DECLINED
    native, fraction = E.native, E.fraction
    n0, n1, n2 = native(normal[0]), native(normal[1]), native(normal[2])
    out = []
    for k in (1, 2, 0):
        e = face[k]
        out.append(n0*native(e[0])+n1*native(e[1])+n2*native(e[2]))
    return fraction(out[0]), fraction(out[1]), fraction(out[2]-native(offset))


# ---------------------------------------------------------------- _rotated_normal
def _cross(a, b):
    return a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]


def rotated_normal(normal, omega, t0, t1, level, arena):
    triple = E.triple
    if (type(t0) is not Q or type(t1) is not Q or type(level) is not int or level < -16 or arena is None
            or not triple(normal) or not triple(omega) or not _resident()):
        return DECLINED
    native, bits = E.native, E.bits
    w = (native(omega[0]), native(omega[1]), native(omega[2]))
    nv = (native(normal[0]), native(normal[1]), native(normal[2]))
    m0, m1 = native(t0), native(t1)
    middle, half = (m0+m1)/2, (m1-m0)/2
    derivative = _cross(w, nv)
    if not any(derivative):
        return normal, Q(0)
    norm_a = max(abs(w[1])+abs(w[2]), abs(w[0])+abs(w[2]), abs(w[0])+abs(w[1]))
    reference_norm_n = max(map(abs, normal))      # first of equals, int or Fraction as the reference's
    norm_n = native(reference_norm_n)
    x = abs(middle)*norm_a
    target = norm_n/E.mpq(2**(32+2*level))
    # Admission widths of the reference's step operands: omega and middle are the originals throughout;
    # term and major are the originals at step 0 and Fractions afterwards (whose widths the natives share).
    fixed_width = sum(V._bits(v) for v in omega)+bits(middle)
    term_width = sum(V._bits(v) for v in normal)
    major_width = V._bits(reference_norm_n)
    with E.Retained(arena.resource) as kept:
        (w0, w1, w2, middle, half, d0, d1, d2, x, target), held = kept.settle(
            (*w, middle, half, *derivative, x, target))
        w, derivative = (w0, w1, w2), (d0, d1, d2)
        (n0, n1, n2, norm_n), _ = kept.settle((*nv, norm_n), held)
        nv = (n0, n1, n2)
        total, term, major, order = list(nv), nv, norm_n, 0
        while True:
            next_major = major*x/(order+1)
            ratio = x/(order+2)
            if ratio < 1 and next_major/(1-ratio) <= target:
                tail = next_major/(1-ratio)
                break
            arena.work(64)
            with E.lease(term_width+fixed_width+major_width, 8, arena.resource):
                scale = middle/(order+1)
                term = tuple(scale*v for v in _cross(w, term))
                total = [a+b for a, b in zip(total, term, strict=True)]
                major = next_major
            settled, _ = kept.settle((*total, *term, major), held)
            total, term, major = list(settled[:3]), settled[3:6], settled[6]
            term_width = bits(term[0])+bits(term[1])+bits(term[2])
            major_width = bits(major)
            order += 1
    error = E.fraction(3*tail+half*sum(map(abs, derivative)))
    if order == 0:
        return tuple(list(normal)), error           # a NEW tuple of the original objects, as tuple(total)
    fraction = E.fraction
    return (fraction(total[0]), fraction(total[1]), fraction(total[2])), error
