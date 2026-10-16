"""Independent check (review env: SymPy + mpmath) of the complementary-cut certificate.

Runs WITHOUT the Atlas runtime. For each proved query (support index, cell, other cell,
interface name) it re-derives from the stored support record:
  C1  two clip literals whose snapshot-rotated fan-edge records are equal up to the order
      of the two inner rays (plain dict comparison after swapping), on opposite sides;
  C2  one rotation axis for every rotation involved (SymPy exact cross products);
  C3  cut rays never parallel and the cut plane never normal to the axis (exact invariants);
  C4  an interface generator with a different rate and a nonzero transverse part.
Then an mpmath evaluation (60 digits) of the actual motion, built independently from the
stored semantics (prior rotations, then own rotation; snapshot normal = inner rays at the
snapshot instant, crossed, then rotated by the snapshot rate), checks:
  - the two literals' signed normals are exact negatives at sampled instants (relative
    residual), i.e. the face lies in one plane;
  - f(t) = m(t).g(t) equals C + A cos(Omega t + phi) with the invariant A, Omega (fit
    residual), A > 0 and Omega != 0, so f has finitely many zeros on [0, T];
  - the number of sign changes of f on a fine grid (finite, reported).
Usage: check_cpcut_sympy.py SUPPORTS.jsonl.gz REPLAY.jsonl [...]  (rows with the certificate rule)
"""
import gzip
import json
import sys

import mpmath as mp
import sympy as sp

mp.mp.dps = 60
RULE = 'exact-zero-area-from-complementary-moving-cuts'


def q(pair):
    return sp.Rational(int(pair[0], 16), int(pair[1], 16))


def vec(value):
    return sp.Matrix([q(p) for p in value])


def mvec(v):
    return mp.matrix([mp.mpf(int(x.p)) / int(x.q) for x in v])


def rot(axis_vec, angle):
    """Rodrigues rotation matrix (mpmath) about a nonzero axis by angle (radians)."""
    k = axis_vec / mp.norm(axis_vec)
    K = mp.matrix([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return mp.eye(3) + mp.sin(angle) * K + (1 - mp.cos(angle)) * (K * K)


def rotate_by_vector(w, dt, v):
    """Rotate v by the rotation vector w*dt (angle |w| dt about w)."""
    if all(x == 0 for x in w):
        return v
    wm = mvec(w)
    return rot(wm, mp.norm(wm) * dt) * v


def ray_at(ray, t):
    v = mvec(vec(ray['direction']))
    for row in ray.get('prior_rotations', ()):
        v = rotate_by_vector(vec(row['angular_velocity_rad_s']), mp.mpf(int(q(row['duration_s']).p)) / int(q(row['duration_s']).q), v)
    return rotate_by_vector(vec(ray['angular_velocity_rad_s']), t, v)


def cross(a, b):
    return mp.matrix([a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]])


def snapshot_normal(record, t):
    off = q(record['snapshot_offset_s'])
    off = mp.mpf(int(off.p)) / int(off.q)
    r1, r2 = (ray_at(r, off) for r in record['constraint']['rays'])
    return rotate_by_vector(vec(record['angular_velocity_rad_s']), t, cross(r1, r2))


def swapped(record):
    inner = dict(record['constraint'])
    inner['rays'] = [inner['rays'][1], inner['rays'][0]]
    out = dict(record)
    out['constraint'] = inner
    return out


def edge_identity(item):
    """Unordered ray pair of a bare moving-ray-edge (as the geometry pairs interfaces)."""
    if item.get('kind') != 'moving-ray-edge':
        return None
    a, b = (json.dumps(r, sort_keys=True) for r in item['rays'])
    return min(a, b) + '|' + max(a, b)


def check(record, cell, other, name):
    parts = {p['logical_cell_id'][:16]: p for p in record['components']}
    constraints = record['constraints']
    interface = constraints[name]
    own = parts[cell]
    literals = [(n, s) for n, s in own['constraints'] if n != name]
    if other:
        ident = edge_identity(interface)
        for n, s in parts[other]['constraints']:
            if constraints[n] == interface or (ident is not None and edge_identity(constraints[n]) == ident):
                continue
            literals.append(('neighbour:' + n, s))
    def rec(n):
        return constraints[n[len('neighbour:'):]] if n.startswith('neighbour:') else constraints[n]
    pairs = []
    for i, (n1, s1) in enumerate(literals):
        r1 = rec(n1)
        if r1.get('kind') != 'snapshot-rotated' or r1['constraint'].get('kind') != 'moving-ray-edge':
            continue
        for n2, s2 in literals[i+1:]:
            r2 = rec(n2)
            if r2 == swapped(r1) and r2 != r1 and s1 == s2:
                pairs.append((n1, s1, n2, s2, r1, r2))
            elif r2 == r1 and s1 == -s2:
                pairs.append((n1, s1, n2, s2, r1, r2))
    out = dict(cell=cell, other=other, name=name, complementary_pairs=len(pairs))
    T = q(record['duration_s'])
    for n1, s1, n2, s2, r1, r2 in pairs:
        omega_c = vec(r1['angular_velocity_rad_s'])
        inner_rays = r1['constraint']['rays']
        vectors = [omega_c]
        for ray in list(inner_rays) + list(interface['rays']):
            vectors.append(vec(ray['angular_velocity_rad_s']))
            vectors += [vec(row['angular_velocity_rad_s']) for row in ray.get('prior_rotations', ())]
        axis = next((v for v in vectors if any(x != 0 for x in v)), None)
        coaxial = axis is not None and all(axis.cross(v) == sp.zeros(3, 1) for v in vectors)
        d1, d2 = (vec(r['direction']) for r in inner_rays)
        a1, a2 = d1.dot(axis), d2.dot(axis)
        not_parallel = a1**2 * d2.dot(d2) != a2**2 * d1.dot(d1)
        not_normal = a1 != 0 or a2 != 0
        generators = []
        for index, ray in enumerate(interface['rays']):
            w, d = vec(ray['angular_velocity_rad_s']), vec(ray['direction'])
            if w != omega_c and d.cross(axis) != sp.zeros(3, 1):
                generators.append(index)
        row = dict(pair=[n1, n2], signs=[s1, s2], coaxial=bool(coaxial), not_parallel=bool(not_parallel),
                   not_normal_to_axis=bool(not_normal), generators=generators)
        if not (coaxial and not_parallel and not_normal and generators):
            out.setdefault('declined', []).append(row)
            continue
        # mpmath: the motion itself.
        Tm = mp.mpf(int(T.p)) / int(T.q)
        ts = [Tm * k / 40 for k in range(41)]
        worst_negation = mp.mpf(0)
        for t in ts[::8]:
            n_a = snapshot_normal(r1, t) * s1
            n_b = snapshot_normal(r2, t) * s2
            worst_negation = max(worst_negation, mp.norm(n_a + n_b) / mp.norm(n_a))
        g = interface['rays'][generators[0]]
        f = [mp.fdot(snapshot_normal(r1, t), ray_at(g, t)) for t in ts]
        # Invariants: A = |m_perp| |d_perp|, Omega = (lambda_g - lambda_c) |k|.
        km = mvec(axis); kn = mp.norm(km); kh = km / kn
        m0 = snapshot_normal(r1, 0)
        m_perp = m0 - mp.fdot(m0, kh) * kh
        dg = ray_at(g, 0)
        d_perp = dg - mp.fdot(dg, kh) * kh
        A = mp.norm(m_perp) * mp.norm(d_perp)
        lam_g = mp.fdot(mvec(vec(g['angular_velocity_rad_s'])), km) / kn**2
        lam_c = mp.fdot(mvec(omega_c), km) / kn**2
        Omega = (lam_g - lam_c) * kn
        C = mp.fdot(m0, kh) * mp.fdot(dg, kh)
        # phi from t=0 and the derivative sign, then the residual of the closed form on the grid.
        c0 = (f[0] - C) / A
        c0 = max(min(c0, mp.mpf(1)), mp.mpf(-1))
        candidates = [mp.acos(c0), -mp.acos(c0)]
        residual = min(max(abs(f[i] - (C + A * mp.cos(Omega * ts[i] + phi))) for i in range(len(ts)))
                       for phi in candidates)
        changes = sum(1 for x, y in zip(f, f[1:]) if (x > 0) != (y > 0))
        row.update(A=mp.nstr(A, 8), Omega=mp.nstr(Omega, 8), C=mp.nstr(C, 8),
                   closed_form_residual=mp.nstr(residual, 5), scale=mp.nstr(max(abs(x) for x in f), 8),
                   signed_normals_negation_residual=mp.nstr(worst_negation, 5),
                   f_sign_changes_on_41_point_grid=changes, f_range=[mp.nstr(min(f), 6), mp.nstr(max(f), 6)])
        out.setdefault('proved', []).append(row)
    return out


def main():
    supports = sys.argv[1]
    wanted = {}
    for path in sys.argv[2:]:
        for line in open(path, encoding='utf8'):
            r = json.loads(line)
            if r.get('rule') == RULE:
                wanted.setdefault(r['support_index'], []).append((r['cell'], r.get('other'), r['constraint_name']))
    results = []
    with gzip.open(supports, 'rt', encoding='utf8') as f:
        f.readline()
        for index, line in enumerate(f):
            if index in wanted:
                record = json.loads(line)
                for cell, other, name in wanted[index]:
                    results.append(dict(support_index=index, **check(record, cell, other, name)))
    ok = all(r.get('proved') for r in results)
    print(json.dumps(dict(checked=len(results), all_proved=ok, results=results), indent=1))
    sys.exit(0 if ok and results else 1)


if __name__ == '__main__':
    main()
