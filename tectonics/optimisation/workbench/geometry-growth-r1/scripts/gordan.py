"""WP20 candidate: exact Gordan certificate for co-rotating homogeneous literals.

Literals whose planes follow the SAME exact rigid path (theta, omega) are, at
every time t, R(t)*n_i for one proper rotation R(t) and rational original
normals n_i (homogeneous planes; offset zero). If 0 = sum lambda_i s_i n_i with
lambda >= 0 not all zero, then any x satisfying s_i (R n_i).x >= 0 for those
literals has every weighted term zero, so x lies in a plane: the intersection
has zero 3-D volume for ALL t (Gordan's alternative). Axial normals (fixed by
rotations about their own direction) join any group whose rotation axis they
are parallel to. Dropping the other literals only enlarges the region, so the
proof covers the whole component. Exact rationals only; no tolerance.
"""
from fractions import Fraction as Q
from itertools import combinations


def _solve(rows, rhs):
    n = len(rows)
    m = [list(r) + [b] for r, b in zip(rows, rhs)]
    for c in range(n):
        p = next((r for r in range(c, n) if m[r][c] != 0), None)
        if p is None:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[r][c] != 0:
                f = m[r][c] / m[c][c]
                m[r] = [a - f * b for a, b in zip(m[r], m[c])]
    return [m[r][n] / m[r][r] for r in range(n)]


def zero_in_hull(vectors, work=None):
    """Exact: positive weights over <=4 of the vectors summing to 0, else None (Caratheodory)."""
    vs = [tuple(v) for v in vectors if any(v)]
    # Normalise duplicates; a direction and its exact negative already decide it.
    for k in range(2, min(4, len(vs)) + 1):
        for subset in combinations(range(len(vs)), k):
            if work is not None:
                work(16 * k)
            pts = [vs[i] for i in subset]
            eqs = [[p[j] for p in pts] for j in range(3)] + [[Q(1)] * k]
            rhs = [Q(0), Q(0), Q(0), Q(1)]
            for rows in combinations(range(4), k):
                if 3 not in rows:
                    continue
                w = _solve([eqs[r] for r in rows], [rhs[r] for r in rows])
                if w is None or any(x < 0 for x in w):
                    continue
                if all(sum(e * x for e, x in zip(eqs[r], w)) == rhs[r] for r in range(4)):
                    return [subset[i] for i in range(k)], w
    return None


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def certificate(literals, constraints, rigid_plane_path, work=None):
    """Return a JSON-able certificate dict, or None. rigid_plane_path is RC1's _rigid_plane_path."""
    groups, axial = {}, []
    for name, sign in literals:
        if sign not in (-1, 1):
            continue
        path = rigid_plane_path(constraints[name])
        if path is None:
            continue
        normal, theta, omega = path
        oriented = tuple(sign * q for q in normal)
        if not any(theta) and not any(omega):
            axial.append((name, sign, oriented))
            continue
        groups.setdefault((theta, omega), []).append((name, sign, oriented))
    for (theta, omega), members in groups.items():
        axis = next(v for v in (omega, theta) if any(v))
        if any(any(_cross(axis, v)) for v in (theta, omega) if any(v)):
            continue  # not a single coaxial rotation; decline (never inferred)
        pool = members + [m for m in axial if not any(_cross(axis, m[2]))]
        if len(pool) < 2:
            continue
        hit = zero_in_hull([m[2] for m in pool], work)
        if hit is None:
            continue
        indices, weights = hit
        return dict(kind='exact-gordan-corotating-zero-volume',
                    literals=[[pool[i][0], pool[i][1]] for i in indices],
                    positive_weights=[str(w) for w in weights],
                    rotation=dict(theta=[str(q) for q in theta], omega=[str(q) for q in omega]),
                    scope='zero 3-D volume for every time; no face-area, flux or material claim')
    # Axial-only group (no rotation at all): the same argument with R = identity.
    if len(axial) >= 2:
        hit = zero_in_hull([m[2] for m in axial], work)
        if hit is not None:
            indices, weights = hit
            return dict(kind='exact-gordan-fixed-zero-volume',
                        literals=[[axial[i][0], axial[i][1]] for i in indices],
                        positive_weights=[str(w) for w in weights],
                        scope='zero 3-D volume for every time; no face-area, flux or material claim')
    return None
