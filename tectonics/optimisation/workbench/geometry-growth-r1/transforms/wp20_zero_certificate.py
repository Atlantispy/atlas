"""WP20: exact zero-volume certificates for undecided endpoint queries (the IV2 stall).

Source transform of atlas_tectonics/integration_differential_geometry.py, for the
Step 10 (WP9) composition. Independent of the partition/routing transforms: it
touches only _component_volume_bounds_decoded and adds private helpers. Reviewed
input: the RC1 geometry (KNOWN_INPUT_SHA256). On any other input the anchors are
still checked exactly, but the composer must re-run the parity harness on the
composed output before relying on it.

Where it acts. Inside the unchanged subdivision loop, once per query, when the
16th leaf is reached and the query is still undecided: positive_witness, no
relative-error target, aggregate lower bound zero, positive upper bound, no
positive witness (settling zero against positive volume: the measured IV2 stall).
Only there, two exact certificates are tried. Proved: the exact enclosure [0, 0]
ends the query, met. Not proved: the numbers and the met/unmet outcome are
unchanged and subdivision continues exactly as before; the attempt's charged work
does add to that query's work_units (a record identity change only). Queries that
settle before their 16th leaf are untouched (byte-identical records, no added
work). A query is never forced. Search size is capped (16 literals per pool);
larger pools decline. A resource or arithmetic refusal inside an attempt keeps
the original exception and gains a note naming the query.

Certificate 1 (Gordan's alternative, co-rotating). Literals whose planes follow the SAME
exact rigid path (theta, omega) (RC1 _rigid_plane_path; coaxial by construction)
are R(t)*n_i for one proper rotation R(t) at every time t, homogeneous, with
rational n_i. If 0 = sum lambda_i s_i n_i with lambda >= 0, sum lambda = 1, then
every true point x has s_i (R n_i).x = 0 for each lambda_i > 0: the component
lies in a plane, zero 3-D volume at every time. Fixed planes (zero path) join a
group only when R fixes them (normal parallel to the axis), or form their own
group (R = identity). Unused literals only shrink the region. Exact rationals
(Caratheodory: at most four normals), admitted and charged on the query arena.

Certificate 2 (pole contact). Literals whose plane contains the common rotation
axis A for all time (an edge with a ray exactly parallel to A, or a rotated normal
exactly perpendicular to A; every rotation vector parallel to A) have true normals
perpendicular to A. Three of them whose 2-D barycentric determinants det(A,v,w),
det(A,w,u), det(A,u,v) are certified strictly of one sign over the original pose
error boxes at the endpoint time surround the axis: the component lies on the
axis line, zero 3-D volume.

Records: no new field. A proved query issues the same schema as any exact-zero
result; only leaves/work_units can differ from the unpatched route. Interval-1
records are untouched; this is a reviewed identity successor for new intervals.
Independent review (16 Oct, one adversarial reviewer): soundness survives; its
three gaps (unproved-query work, search size, unchecked input) are addressed here.
"""
from hashlib import sha256

# The reviewed input: RC1 composed geometry (frozen). Anchors are checked on any input.
KNOWN_INPUT_SHA256 = {
    'fc9dd85e002fe54db6e409ebe89083996f62611c40d958a5a1e60184f3424253': 'RC1 composed-r1 runtime-src',
}

HELPER = '''
def _wp20_zero_in_hull(vectors, arena):
    """Exact positive weights over <=4 rational 3-vectors summing to zero, or None."""
    from itertools import combinations
    vs = [v for v in vectors if any(v)]
    with V._work(tuple(q for v in vs for q in v), arena.resource):
        for k in range(2, min(4, len(vs))+1):
            for subset in combinations(range(len(vs)), k):
                arena.work(64*k)
                pts = [vs[i] for i in subset]
                eqs = [[p[j] for p in pts] for j in range(3)]+[[Q(1)]*k]
                rhs = [Q(0), Q(0), Q(0), Q(1)]
                for rows in combinations(range(4), k):
                    if 3 not in rows:
                        continue
                    m = [list(eqs[r])+[rhs[r]] for r in rows]
                    singular = False
                    for c in range(k):
                        p = next((r for r in range(c, k) if m[r][c] != 0), None)
                        if p is None:
                            singular = True
                            break
                        m[c], m[p] = m[p], m[c]
                        for r in range(k):
                            if r != c and m[r][c] != 0:
                                f = m[r][c]/m[c][c]
                                m[r] = [a-f*b for a, b in zip(m[r], m[c])]
                    if singular:
                        continue
                    w = [m[r][k]/m[r][r] for r in range(k)]
                    if any(x < 0 for x in w):
                        continue
                    if all(sum(e*x for e, x in zip(eqs[r], w)) == rhs[r] for r in range(4)):
                        return [subset[i] for i in range(k)], w
    return None


def _wp20_corotating_zero(literals, constraints, arena):
    """WP20 exact Gordan certificate: co-rotating homogeneous literals with no interior.

    See the transform module docstring for the proof. Returns a certificate
    dict (never recorded in the measure) or None. Declines all other shapes.
    """
    groups, fixed = {}, []
    for name, sign in literals:
        if sign not in (-1, 1):
            continue
        path = _rigid_plane_path(constraints[name])
        if path is None:
            continue
        normal, theta, omega = path
        oriented = tuple(sign*q for q in normal)
        if not any(theta) and not any(omega):
            fixed.append((name, sign, oriented))
        else:
            groups.setdefault((theta, omega), []).append((name, sign, oriented))
    pools = []
    for (theta, omega), members in groups.items():
        axis = omega if any(omega) else theta
        if any(any(O._cross(axis, v)) for v in (theta, omega) if any(v)):
            continue
        pools.append(members+[m for m in fixed if not any(O._cross(axis, m[2]))])
    if len(fixed) >= 2:
        pools.append(fixed)
    for pool in pools:
        if not 2 <= len(pool) <= 16:
            continue  # bounded search: a larger pool declines (never forced)
        hit = _wp20_zero_in_hull([m[2] for m in pool], arena)
        if hit is not None:
            indices, weights = hit
            return dict(kind='exact-gordan-corotating-zero-volume',
                        literals=[[pool[i][0], pool[i][1]] for i in indices], weights=weights)
    return None


def _wp20_rotations(constraint):
    """(axis-containing structure, every rotation vector) of one literal, or None.

    Structure 'ray': an edge with one ray exactly parallel to every rotation, so
    the plane always contains that axis. 'normal': a rotated normal exactly
    perpendicular to its rotation. Snapshots add their own rotation vector.
    """
    rotations, inner = [], constraint
    while inner['kind'] == 'snapshot-rotated':
        rotations.append(_load_vec(inner['angular_velocity_rad_s']))
        inner = inner['constraint']
    if inner['kind'] == 'moving-ray-edge':
        directions = []
        for ray in inner['rays']:
            directions.append(_load_vec(ray['direction']))
            rotations.append(_load_vec(ray['angular_velocity_rad_s']))
            rotations.extend(w for w, _ in _history(ray.get('prior_rotations', ())))
        return 'ray', directions, rotations
    if inner['kind'] == 'rotated-normal':
        rotations.append(_load_vec(inner['angular_velocity_rad_s']))
        return 'normal', [_load_vec(inner['normal'])], rotations
    return None


def _wp20_axial_meridian_zero(literals, constraints, time, arena):
    """WP20 exact pole-contact certificate: planes containing the rotation axis.

    Every rotation is about one axis A (exactly parallel vectors). A literal whose
    plane contains A at all times (an edge with a ray parallel to A, or a rotated
    normal perpendicular to A) has a true normal perpendicular to A. If, at this
    endpoint time, three such oriented normals have 2-D barycentric determinants
    det(A,v,w), det(A,w,u), det(A,u,v) certified strictly of one sign over the
    original pose error boxes, 0 is strictly inside their convex hull in the plane
    perpendicular to A. Then only points on the axis line satisfy all three, so
    the component has zero 3-D volume (no face-area or flux claim).
    """
    meridian, axis = [], None
    for name, sign in literals:
        if sign not in (-1, 1):
            continue
        shape = _wp20_rotations(constraints[name])
        if shape is None:
            continue
        kind, vectors, rotations = shape
        moving = [w for w in rotations if any(w)]
        if not moving:
            continue
        if axis is None:
            axis = moving[0]
        if any(any(O._cross(axis, w)) for w in moving):
            return None
        if kind == 'ray' and not any(not any(O._cross(axis, d)) for d in vectors):
            continue
        if kind == 'normal' and O._dot(axis, vectors[0]) != 0:
            continue
        meridian.append((name, sign))
    if axis is None or not 3 <= len(meridian) <= 16:
        return None
    axis_box = tuple((q, q) for q in axis)
    for level in (0, 24):
        boxes = []
        for name, sign in meridian:
            normal, error, offset = _constraint_pose(constraints[name], time, time, level, arena)
            if offset:
                continue
            boxes.append((name, sign, tuple(tuple(sorted((sign*q-error, sign*q+error))) for q in normal)))
        from itertools import combinations
        for (n1, s1, u), (n2, s2, v), (n3, s3, w) in combinations(boxes, 3):
            arena.work(512)
            with V._work(tuple(q for box in (u, v, w) for pair in box for q in pair)+axis, arena.resource):
                dets = (_dot_bounds(axis_box, _cross_bounds(v, w)), _dot_bounds(axis_box, _cross_bounds(w, u)),
                        _dot_bounds(axis_box, _cross_bounds(u, v)))
            if all(d[0] > 0 for d in dets) or all(d[1] < 0 for d in dets):
                return dict(kind='exact-axial-meridian-zero-volume', literals=[[n1, s1], [n2, s2], [n3, s3]],
                            level=level, determinant_bounds=dets)
    return None


'''

ANCHOR_DEF = 'def _component_volume_bounds_decoded(support, logical_cell_id, record, arena, *,\n'
ANCHOR_HOOK = '            _, _, parent, depth, lo, hi, mask = storage.pop(queue)\n'
# Once per query, when the 16th leaf is reached still undecided: queries that settle
# sooner are untouched (byte-identical records, no added work).
WP20_AFTER_LEAVES = 16
HOOK = ('            if leaves == %d and positive_witness and relative_error is None and not witness and not low and high:\n'
        '                try:\n'
        "                    proved = (_wp20_corotating_zero(component['constraints'], record['constraints'], arena) is not None or\n"
        "                              _wp20_axial_meridian_zero(component['constraints'], record['constraints'], time, arena) is not None)\n"
        '                except Exception as error:\n'
        "                    error.add_note('WP20 zero-certificate attempt: '+str(dict(logical_cell_id=logical_cell_id,\n"
        "                        endpoint=endpoint, support_id=support.support_id, leaves=leaves)))\n"
        '                    raise\n'
        '                if proved:\n'
        '                    # WP20: the true component has zero 3-D volume (exact proof);\n'
        '                    # its exact enclosure is [0, 0] and the query ends met.\n'
        '                    low = high = Q(0)\n'
        '                    break\n') % WP20_AFTER_LEAVES


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('WP20 transform anchor must occur exactly once: ' + old[:60])
    return source.replace(old, new)


def transform(source, *, allow_unreviewed_input=False):
    """Return the transformed geometry source; refuses if any anchor is absent or repeated.

    Only the reviewed RC1 input is accepted by default. A composer applying it to a
    different (already transformed) input passes allow_unreviewed_input=True and
    must then re-run the parity harness on its composed output.
    """
    if '_wp20_corotating_zero' in source:
        raise ValueError('WP20 transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('WP20 transform input is not the reviewed geometry; pass allow_unreviewed_input and re-run parity')
    source = _once(source, ANCHOR_DEF, HELPER.lstrip('\n') + ANCHOR_DEF)
    source = _once(source, ANCHOR_HOOK, HOOK + ANCHOR_HOOK)
    return source


def describe(source):
    digest = sha256(source.encode()).hexdigest()
    return dict(input_sha256=digest, known_input=KNOWN_INPUT_SHA256.get(digest),
                output_sha256=sha256(transform(source).encode()).hexdigest())
