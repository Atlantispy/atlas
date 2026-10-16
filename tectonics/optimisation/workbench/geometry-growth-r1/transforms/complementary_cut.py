"""Interface stall: exact zero area where a face is clipped by COMPLEMENTARY copies of one moving cut.

Source transform of atlas_tectonics/integration_differential_geometry.py (Step 10 / WP9
composition; this chat's file). Target, measured on the exact IV2 rebuild: paired moving
interfaces whose two components carry the same snapshot-rotated fan-edge cut on opposite
sides (e.g. "birth-outside-owner:vertex:m02-p03>vertex:m03-p03" on one cell and the same
record with its two rays swapped on the other, both sign +1). Their common face lies in that
plane, so its area is zero, but RC1's opposite-cut proof needs exact rigid plane paths
(these snapshots of deforming edges have irrational prior rotations) and declines. The
Taylor route then branches on every time leaf (a vertex exactly on the plane is clipped by
its reversed copy: value +-1e-78) and the geometric kernel alone converges as 1/n leaves:
such queries never finish (about 1e10 leaves to the IV2 stream width).

Proof (all conditions decided exactly on stored rationals; anything else declines):
 C1  Two clip literals (n1,s1), (n2,s2), s in {-1,+1}, whose records are both
     snapshot-rotated moving-ray-edge records that are EQUAL apart from the order of the
     two inner rays (all other fields compared exactly), with s1*o1 = -s2*o2, where o is
     +1 for the canonical ray order and -1 for the reversed one. The edge normal is
     r1 x r2 in stored order and the snapshot rotation is the same, so the two signed
     normals are exact negatives at every instant: the clipped face lies in the plane
     P(t) = {x : m(t).x = 0}, m(t) = R(t) (r1(s) x r2(s)), s the snapshot instant.
 C2  Every rotation vector involved (the interface's two ray rates and prior rotations,
     the cut's snapshot rate, its inner rays' rates and prior rotations) is exactly
     parallel to one nonzero rational axis k. All rotations then commute and preserve
     each vector's k-component and squared norm.
 C3  m(t) != 0 and m(t) is not parallel to k, for all t: with a_i = d_i.k for the cut's
     authored inner ray directions d_i, a1^2 |d2|^2 != a2^2 |d1|^2 (so the rays are not
     parallel at any instant), and (a1, a2) != (0, 0) (so the plane is not normal to k).
 C4  One interface generator g (authored direction d, rate w) has w != the cut's snapshot
     rate (both parallel to k, so their difference along k is nonzero) and d x k != 0.
 Then f(t) = m(t).g(t) = C + A cos(Omega t + phi) with A = |m_perp||d_perp| > 0 and
 Omega != 0 (rotation invariance of the dot product about k), which has finitely many
 zeros on [0, T]. Except at those instants g(t) is not in P(t), so the interface plane
 (which contains g(t)) is not P(t) and the face meets P(t) in at most a line. A face of
 zero area except at finitely many instants contributes exactly zero to the time
 integral of any bounded integrand over it: both inward and outward volumes are exactly
 [0, 0]. These records carry no moments or witnesses besides those bounds.

Gate (record identity): the check runs only when a query's Taylor attempt asks for its
65th geometric-kernel evaluation. Queries that finish with at most 64 evaluations run
exactly as before (byte-identical records). The check runs under a mandatory reservation
(same size rule and category as the exclusion module's path leases, so the outcome never
depends on free headroom) and charges no work units unless it proves; a declined check
lets the query continue unchanged. A proved query is issued like RC1's other exact
zero-area exclusions (bounds [0,0], leaves 1, met, rule, zero_area_certificate with
source_sha256 and open_interval); its work units include the 64 evaluations already done
plus the proof's charge, taken after the aborted attempt's frames are released.
source_sha256 is the sha256 of the inserted helper text plus the call site that builds the
proved record (constant _CP_SOURCE_SHA256); parallel adoption (companion transform
complementary_cut_adopt.py) accepts a worker's record only if it equals the PARENT's
loaded constant (the dispatcher's full-source binding pins parent and worker files).
r2 (16 Oct 2026): adoption, source identity, reservation and charge placement after the
cold review. r3: the reservation is mandatory (r2's optional one let headroom choose the
record) and the digest covers the call site, after the r2 check. r1 proof unchanged.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    'fc9dd85e002fe54db6e409ebe89083996f62611c40d958a5a1e60184f3424253': 'RC1 composed-r1 runtime-src',
}

ANCHOR_DEF = 'def enclose_component_interface(support, logical_cell_id, constraint_name, *,\n'

HELPER = '''
# Interface stall (complementary moving cuts): see the transform's documentation.
_CP_GATE_CALLS = 64


class _ComplementaryCut(Exception):
    """Internal: a gated Taylor attempt found an exact complementary-cut certificate."""

    def __init__(self, certificate):
        super().__init__('complementary moving cuts: exact zero area')
        self.certificate = certificate


def _cp_identity(constraint):
    """(identity, orientation) of a snapshot-rotated fan edge, or None.

    Equal identities: the same record apart from the order of the two inner rays.
    """
    if type(constraint) is not dict or constraint.get('kind') != 'snapshot-rotated':
        return None
    inner = constraint.get('constraint')
    if type(inner) is not dict or inner.get('kind') != 'moving-ray-edge':
        return None
    rays = inner.get('rays')
    if type(rays) is not list or len(rays) != 2:
        return None
    forward, reverse = _encoded(rays), _encoded([rays[1], rays[0]])
    if forward == reverse:
        return None
    rest = _encoded(dict((k, v) for k, v in constraint.items() if k != 'constraint'))
    inner_rest = _encoded(dict((k, v) for k, v in inner.items() if k != 'rays'))
    return (rest, inner_rest, min(forward, reverse)), (1 if forward < reverse else -1)


def _cp_ray(ray):
    return (_load_vec(ray['direction']), _load_vec(ray['angular_velocity_rad_s']),
            tuple(w for w, _ in _history(ray.get('prior_rotations', ()))))


def _cp_dot(a, b):
    return sum(x*y for x, y in zip(a, b, strict=True))


def _cp_prove(interface, cut, duration):
    """Conditions C2-C4 of the transform's proof, exactly; a certificate dict or None."""
    plane = _load_vec(cut['angular_velocity_rad_s'])
    inner = tuple(_cp_ray(ray) for ray in cut['constraint']['rays'])
    rays = tuple(_cp_ray(ray) for ray in interface['rays'])
    vectors = (plane, *(v for d, w, prior in inner+rays for v in (w, *prior)))
    axis = next((v for v in vectors if any(v)), None)
    if axis is None or any(any(O._cross(axis, v)) for v in vectors):
        return None
    (d1, _, _), (d2, _, _) = inner
    a1, a2 = _cp_dot(d1, axis), _cp_dot(d2, axis)
    left, right = a1*a1*_cp_dot(d2, d2), a2*a2*_cp_dot(d1, d1)
    if left == right or not (a1 or a2):
        return None
    for index, (d, w, _) in enumerate(rays):
        transverse = O._cross(d, axis)
        if w == plane or not any(transverse):
            continue
        return dict(method='exact-complementary-moving-cuts-coaxial-transverse-generator',
            source_sha256=_CP_SOURCE_SHA256,
            open_interval='0 <= t <= duration; the finitely many instants where the generator meets '
                          'the cut plane have zero time measure',
            axis=_store_vec(axis), cut_snapshot_rate_rad_s=_store_vec(plane),
            cut_ray_axis_components=[_qtext(a1), _qtext(a2)],
            cut_ray_parallel_test=[_qtext(left), _qtext(right)],
            interface_generator=index, generator_rate_rad_s=_store_vec(w),
            generator_cross_axis=_store_vec(transverse), duration_s=_qtext(duration),
            gate_kernel_evaluations=_CP_GATE_CALLS,
            area_rule='complementary signed copies of one moving plane hold the face in that plane; '
                      'a coaxial generator with a different rate and a nonzero transverse part leaves it '
                      'except at finitely many instants, so the face is at most a line almost everywhere')
    return None


def _complementary_cut_certificate(constraint, constraints, literals, duration):
    """Certificate for the face of ``constraint`` clipped by ``literals``, or None (no change)."""
    if (type(constraint) is not dict or constraint.get('kind') != 'moving-ray-edge'
            or len(constraint.get('rays', ())) != 2 or not duration > 0):
        return None
    seen = {}
    for name, s in literals:
        if s not in (-1, 1):
            continue
        item = constraints.get(name)
        found = _cp_identity(item)
        if found is None:
            continue
        identity, orientation = found
        for other_name, other_s, other_side in seen.get(identity, ()):
            if other_side == -s*orientation:
                proof = _cp_prove(constraint, item, duration)
                if proof is not None:
                    return dict(proof, constraint_names=[other_name, name], halfspace_signs=[other_s, s])
        seen.setdefault(identity, []).append((name, s, s*orientation))
    return None


def _cp_gate(fallback, constraint, constraints, literals, duration, arena):
    """The unchanged kernel; past its 64th evaluation, one exact certificate check.

    The check's encoded records and rationals sit under a MANDATORY reservation sized
    and categorised like the exclusion module's path leases, so its outcome never
    depends on free headroom: a shortfall is the same resource refusal the exclusion
    module can already raise in this query. It charges no work units unless it proves.
    """
    state = [0, False]

    def gated(t0, t1, level):
        state[0] += 1
        if state[0] > _CP_GATE_CALLS and not state[1]:
            state[1] = True
            from .integration_regional_inventory import _width
            size = 8192+32*_width((constraint, [constraints.get(name) for name, _ in literals]))
            with arena.resource.reserve(size, category='interface-exclusion-paths'):
                certificate = _complementary_cut_certificate(constraint, constraints, literals, duration)
            if certificate is not None:
                raise _ComplementaryCut(certificate)
        return fallback(t0, t1, level)
    return gated


'''

OLD_CALL = '''                attempt = IM.integrate(layer=layer, cell=cell, first=first, second=second,
                    outward_sign=-sign, omega=omega, constraints=constraints, literals=literals,
                    duration=duration, widths=widths, max_leaves=max_leaves,
                    fallback=lambda t0,t1,level: physical_leaf(bounds,t0,t1,level), arena=arena)
                if attempt[2]:
                    values, leaves, met = attempt
                else:
                    values, leaves, met = _refine(physical_leaf, bounds, duration, widths, max_leaves, arena)
                interface_moments = dict(source_sha256=IM.source_digest(), order=IM.ORDER,
                    method='moving-orthonormal-chart-annular-first-moments-certified-time-Taylor',
                    attempt_leaves=attempt[1], attempt_met=attempt[2],
                    unresolved='original physical geometric kernel and original limits')
                rule = 'material-velocity-minus-actual-two-ray-face-velocity'
'''
NEW_CALL = '''                certificate = None
                try:
                    attempt = IM.integrate(layer=layer, cell=cell, first=first, second=second,
                        outward_sign=-sign, omega=omega, constraints=constraints, literals=literals,
                        duration=duration, widths=widths, max_leaves=max_leaves,
                        fallback=_cp_gate(lambda t0,t1,level: physical_leaf(bounds,t0,t1,level),
                                          constraint, constraints, literals, duration, arena), arena=arena)
                except _ComplementaryCut as proved:
                    certificate = proved.certificate
                if certificate is not None:
                    # Charged after the except block, so the aborted attempt's frames are released.
                    exclusion = certificate
                    with V._work((duration, *(W._decode(q) for q in certificate['cut_ray_parallel_test'])),
                                 arena.resource):
                        arena.work(256)
                    values, leaves, met = ((Q(0), Q(0)), (Q(0), Q(0))), 1, True
                    rule = 'exact-zero-area-from-complementary-moving-cuts'
                else:
                    if attempt[2]:
                        values, leaves, met = attempt
                    else:
                        values, leaves, met = _refine(physical_leaf, bounds, duration, widths, max_leaves, arena)
                    interface_moments = dict(source_sha256=IM.source_digest(), order=IM.ORDER,
                        method='moving-orthonormal-chart-annular-first-moments-certified-time-Taylor',
                        attempt_leaves=attempt[1], attempt_met=attempt[2],
                        unresolved='original physical geometric kernel and original limits')
                    rule = 'material-velocity-minus-actual-two-ray-face-velocity'
'''


def _once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('complementary-cut anchor must occur exactly once: ' + old[:60])
    return source.replace(old, new)


def transform(source, *, allow_unreviewed_input=False):
    if '_complementary_cut_certificate' in source:
        raise ValueError('complementary-cut transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('complementary-cut input is not the reviewed geometry; pass allow_unreviewed_input and re-run parity')
    helper = HELPER.lstrip('\n')
    # The certificate's source identity: the helper text and the call site that builds
    # the proved record (the parent's loaded constant is what parallel adoption compares
    # a worker's record against; the dispatcher's full-source binding pins both files).
    digest = ("_CP_SOURCE_SHA256 = '%s'  # sha256 of the certificate helper below + its call site\n"
              % sha256((helper + NEW_CALL).encode()).hexdigest())
    source = _once(source, ANCHOR_DEF, digest + helper + ANCHOR_DEF)
    source = _once(source, OLD_CALL, NEW_CALL)
    return source
