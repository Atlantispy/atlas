"""Staged general polygon heat functionals, with no control/probe imports.

Numerically unchanged extraction of N4. Same full physical polygons, exact20
integrated actions, exact complete nearest shell, rank-driven shell expansion,
base jump, intervals, exact fallback and power convention. Uniform k only.
The caller must still supply full geometry validation and prospective resource
admission; this standalone staged numerical core is NOT a native heat plan.
"""
from concurrent.futures import CancelledError
from fractions import Fraction as Q
from heapq import nsmallest
from math import inf, isfinite, nextafter
import math
from operator import index
import sys
from time import perf_counter

from atlas_tectonics._private import private_heat_certification_kernel_r1 as K

G = K.G
EXPONENTS = [(a, b, d-a-b) for d in range(4) for a in range(d+1) for b in range(d-a+1)]


def mq(value):
    K._require_gmp()
    return G.mpq(value.numerator, value.denominator)


def decode(pair):
    return Q(int(pair[0], 16), int(pair[1], 16))


def vector(raw):
    return tuple(map(decode, raw))


def dot(a, b):
    return sum(x*y for x, y in zip(a, b, strict=True))


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b, strict=True))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def face_second_moment(face):
    """Return area-average (x-centroid)(x-centroid)^T; reject missing geometry.

    The declared centroid and normal are independently checked against polygon
    integrals. Either ring orientation is accepted. Convex half-plane checks
    reject self-crossing/nonconvex rings; no simplification or vertex snapping.
    """
    points = [vector(p) for p in face['vertices_m']]
    centre, normal = vector(face['centroid_m']), vector(face['area_vector_m2'])
    shifted = [sub(p, centre) for p in points]
    fan = [(shifted[0], a, b) for a, b in zip(shifted[1:-1], shifted[2:], strict=True)]
    area_vectors = [tuple(v/2 for v in cross(sub(b, a), sub(c, a))) for a, b, c in fan]
    area = tuple(sum(v[j] for v in area_vectors) for j in range(3))
    if area == normal:
        orientation = 1
    elif area == tuple(-v for v in normal):
        orientation = -1
    else:
        raise ValueError('Polygon area does not match declared face area')
    for a, b in zip(shifted, shifted[1:]+shifted[:1], strict=True):
        if any(orientation*dot(cross(sub(b, a), sub(p, a)), normal) < 0 for p in shifted):
            raise ValueError('Convex non-crossing face ring required')
    weights = [orientation*dot(a, normal)/dot(normal, normal) for a in area_vectors]
    # Triangle barycentric integrals: E[lambda_i^2]=1/6 and
    # E[lambda_i lambda_j]=1/12. Stable exact shifted coordinates avoid large
    # origin cancellation even for a nanometre face far from the origin.
    return [[sum(w*(sum(v[i]*v[j] for v in tri)+sum(v[i] for v in tri)*sum(v[j] for v in tri))/12
                 for w, tri in zip(weights, fan, strict=True)) for j in range(3)] for i in range(3)]


def point_basis(point, centre, scale):
    coordinate = [(a-b)/scale for a, b in zip(point, centre, strict=True)]
    return [math.prod(v**power for v, power in zip(coordinate, exponent, strict=True))
            for exponent in EXPONENTS]


def integrated_flux_basis(face_point, normal, moment, centre, scale, conductivity):
    """Oriented -integral(k grad p dot n) for all cubic monomials.

    Face derivative degree is <=2; shift its exact centred second moment to
    the reconstruction origin. No derivative-at-centroid approximation occurs.
    """
    mean = [(a-b)/scale for a, b in zip(face_point, centre, strict=True)]

    def average(exponent):
        indices = [i for i, power in enumerate(exponent) for _ in range(power)]
        if not indices:
            return G.mpq(1)
        if len(indices) == 1:
            return mean[indices[0]]
        if len(indices) == 2:
            i, j = indices
            return mean[i]*mean[j]+mq(moment[i][j])/scale**2
        raise ValueError('Only cubic temperature functionals are supported')

    return [-conductivity*sum(normal[j]*power*average(tuple(p-int(i == j)
                for i, p in enumerate(exponent)))/scale
                for j, power in enumerate(exponent) if power)
            for exponent in EXPONENTS]




def dyadic_frame(centre, sample_points):
    """Choose a simple basis only; do not round physical points or moments.

    For an invertible cubic basis transform B, M'=MB, G'=B^TGB and
    t'=B^Tt. All compatible dual solutions yield the same minimum-norm
    observation weights M dual, including rank-deficient systems.
    """
    origin = tuple(G.mpq(float(value)) for value in centre)
    extent = max(abs(a-b) for point in sample_points
                 for a, b in zip(point, origin, strict=True))
    exponent = extent.numerator.bit_length()-extent.denominator.bit_length()
    scale = G.mpq(2)**exponent
    if scale < extent:
        scale *= 2
    return origin, scale






def _parts(value):
    """Exact represented rational; nonfinite input is invalid, not a stencil."""
    if isinstance(value, float):
        return value.as_integer_ratio()
    try:
        numerator, denominator = index(value.numerator), index(value.denominator)
    except (AttributeError, TypeError, ValueError, OverflowError) as error:
        raise TypeError('Coordinates must expose exact integer numerator/denominator') from error
    return numerator, denominator


def _float_le_rational(value, numerator, denominator):
    n, d = value.as_integer_ratio()
    return n*denominator <= numerator*d


def _rational_le_float(numerator, denominator, value):
    n, d = value.as_integer_ratio()
    return numerator*d <= n*denominator


def _enclosure(value):
    """Validate adjacent-float enclosure exactly; conversion quality is not trusted."""
    numerator, denominator = _parts(value)
    try:
        rounded = float(value)
    except (OverflowError, ValueError):
        return (-inf, inf), True
    if not isfinite(rounded):
        return (-inf, inf), True
    lower, upper = nextafter(rounded, -inf), nextafter(rounded, inf)
    if ((isfinite(lower) and not _float_le_rational(lower, numerator, denominator)) or
            (isfinite(upper) and not _rational_le_float(numerator, denominator, upper))):
        return (-inf, inf), True
    return (lower, upper), not (isfinite(lower) and isfinite(upper))


def _down_nonnegative(value):
    # On binary64 Python, one predecessor encloses the exact +, -, or * result.
    # Overflow/other uncertainty contributes zero, never a spurious rejection.
    return max(0., nextafter(value, -inf)) if isfinite(value) else 0.


def _distance_lower(point, centre):
    """Lower bound on squared Euclidean distance between enclosing boxes."""
    total = 0.
    for (lo, hi), (clo, chi) in zip(point, centre, strict=True):
        if not all(map(isfinite, (lo, hi, clo, chi))):
            continue
        if hi < clo:
            gap = _down_nonnegative(clo-hi)
        elif chi < lo:
            gap = _down_nonnegative(lo-chi)
        else:
            continue
        term = _down_nonnegative(gap*gap)
        # A sum overflow must not replace earlier certified contributions with
        # infinity. Keeping the old finite lower bound remains conservative.
        candidate = total+term
        if isfinite(candidate):
            total = _down_nonnegative(candidate)
    return total


def _upper_cutoff(value):
    numerator, denominator = _parts(value)
    try:
        upper = nextafter(float(value), inf)
    except (OverflowError, ValueError):
        return inf
    if not isfinite(upper) or not _rational_le_float(numerator, denominator, upper):
        return inf
    return upper


def _exact_distance(point, centre):
    return sum((Q(*_parts(a))-Q(*_parts(b)))**2 for a, b in zip(point, centre, strict=True))


def screen_inputs(observations, cancelled=None):
    """The centre-independent inputs of ScreenedSupport, built once per observation pool: points,
    coordinate enclosures and their uncertain count."""
    points = tuple((key, tuple(point)) for key, point in observations)
    intervals, uncertain = [], 0
    for _, point in points:
        if cancelled is not None and cancelled():
            raise CancelledError('Exact nearest-shell screen cancelled')
        row = []
        for value in point:
            bounds, flag = _enclosure(value)
            row.append(bounds)
            uncertain += flag
        intervals.append(tuple(row))
    return points, tuple(intervals), uncertain


class ScreenedSupport:
    """Exact initial complete shell plus lazy full exact rank-expansion fallback.

    `shell` has precisely the full oracle's first complete minimum-th shell.
    Every row is (Fraction squared distance, original key, original point tuple).
    Equal distances order by the exact point, then by position (geometry, never a label).
    `full_ranking()` must be requested before the first rank-driven expansion;
    it includes every original observation and retains original stable tie order.
    Diagnostics count the actual distance evaluations, including reused seeds.
    """
    def __init__(self, observations, centre, minimum, cancelled, inputs=None):
        self._points = inputs[0] if inputs is not None else tuple((key, tuple(point)) for key, point in observations)
        self._centre = tuple(centre)
        self._cancelled = cancelled
        self._distances = {}
        self._full = None
        self.diagnostics = dict(observations=len(self._points), minimum=minimum,
            float_interval_candidates=0, uncertain_coordinate_enclosures=0,
            exact_distance_evaluations=0, full_ranking_requested=False,
            discard_rule='certified squared-distance lower bound strictly exceeds outward exact-candidate cutoff',
            rank_expansion_rule='full_ranking() before adding any observation',
            changed_physics=False, scientific_acceptance=False)
        self._check()
        centre_intervals = []
        for value in self._centre:
            bounds, uncertain = _enclosure(value)
            centre_intervals.append(bounds)
            self.diagnostics['uncertain_coordinate_enclosures'] += uncertain
        binary64 = sys.float_info.radix == 2 and sys.float_info.mant_dig == 53
        lower = []
        if inputs is not None:
            self.diagnostics['uncertain_coordinate_enclosures'] += inputs[2]
            for intervals in inputs[1]:
                self._check()
                lower.append(_distance_lower(intervals, centre_intervals) if binary64 else 0.)
        else:
            for _, point in self._points:
                self._check()
                intervals = []
                for value in point:
                    bounds, uncertain = _enclosure(value)
                    intervals.append(bounds)
                    self.diagnostics['uncertain_coordinate_enclosures'] += uncertain
                lower.append(_distance_lower(intervals, centre_intervals) if binary64 else 0.)
        wanted = min(minimum, len(self._points))
        seeds = nsmallest(wanted, range(len(lower)), key=lambda i: (lower[i], i))
        cutoff = max(self._distance(i) for i in seeds)
        outward_cutoff = _upper_cutoff(cutoff) if binary64 else inf
        retained = [i for i, bound in enumerate(lower) if not bound > outward_cutoff]
        ordered = self._ordered(retained)
        shell_cutoff = ordered[wanted-1][0]
        self.shell = tuple(row for row in ordered if row[0] <= shell_cutoff)
        self.diagnostics.update(float_interval_candidates=len(retained),
            certified_discards=len(self._points)-len(retained), seed_exact_distances=len(seeds),
            initial_shell_samples=len(self.shell), upper_cutoff_finite=isfinite(outward_cutoff),
            binary64_screen_enabled=binary64, initial_complete_exact_ranking=len(retained) == len(self._points))
        if len(retained) == len(self._points):
            self._full = ordered

    def _check(self):
        if self._cancelled is not None and self._cancelled():
            raise CancelledError('Exact nearest-shell screen cancelled')

    def _distance(self, index):
        if index not in self._distances:
            self._check()
            self._distances[index] = _exact_distance(self._points[index][1], self._centre)
            self.diagnostics['exact_distance_evaluations'] += 1
        return self._distances[index]

    def _ordered(self, indices):
        # Ties order by the point, x then y then z, each an exact Fraction (floats and encoded rationals
        # decoded by _parts, so every coordinate compares exactly); equal points fall to their position.
        ordered = sorted(indices, key=self._distance)
        start = 0
        while start < len(ordered):
            end, distance = start + 1, self._distances[ordered[start]]
            while end < len(ordered) and self._distances[ordered[end]] == distance:
                end += 1
            if end - start > 1:         # only a tied run decodes its points: (point, position), as one key would
                ordered[start:end] = sorted(ordered[start:end], key=lambda i: (
                    tuple(Q(*_parts(a)) for a in self._points[i][1]), i))
            start = end
        return tuple((self._distances[i], *self._points[i]) for i in ordered)

    def full_ranking(self):
        self._check()
        self.diagnostics['full_ranking_requested'] = True
        if self._full is None:
            self._full = self._ordered(range(len(self._points)))
        return self._full


def nearest_complete_shell(observations, centre, *, minimum=40, cancelled=None, inputs=None):
    """Return ScreenedSupport; use .shell first, .full_ranking() on rank expansion."""
    return ScreenedSupport(observations, centre, minimum, cancelled, inputs)


class ExactIncompatibility(ValueError):
    """Only the exact fallback has proved that the current span is insufficient."""


def functional_bounds(matrix, target, keys, base_keys, signed_tau, conversion, *,
                      gradient, observation, cancelled=None, evidence=None, before_exact=None):
    """Certify physical coefficient bounds or compute exact singleton fallback.

    An interval certificate proves Gram nonsingularity and the unique exact dual.
    Therefore M^T(M dual) = target exactly. Adding the exact base jump restores
    gradient, so all polynomial moment identities hold algebraically. This is
    not a claim that non-singleton interval endpoints themselves satisfy them.
    """
    K._require_gmp()
    audit = {} if evidence is None else evidence
    audit.update(exact_gram_constructed=False, exact_fallback=False, interval={})

    def check():
        if cancelled is not None and cancelled():
            raise CancelledError('Certified functional cancelled')

    check()
    _, _ = observation(base_keys[0]), observation(base_keys[1])
    try:
        result = K.certified_weights(matrix, target, keys, base_keys, signed_tau, conversion,
                                     cancelled=check, evidence=audit['interval'])
    except K.ExactIncompatibility as error:
        audit.update(route='exact-incompatible', rank=None,
                     exact_incompatibility='singleton-original-moment-constraint')
        raise ExactIncompatibility(str(error)) from error
    except K.Unresolved as error:
        audit['interval_refusal'] = dict(type=type(error).__name__, reason=str(error))
    else:
        proof = {key: [G.mpq(value).numerator.digits(16), G.mpq(value).denominator.digits(16)]
                 if isinstance(value, (G.mpfr, G.mpq)) else value
                 for key, value in result['proof'].items()}
        audit.update(route='interval', rank=len(target), interval_proof=proof,
                     interval_proof_scalar_encoding='exact signed-hex rational pairs; integer fields unchanged',
                     precision_bits=result['precision_bits'], moment_identity_kind='algebraic-nonsingular-Gram')
        return dict(ordered_keys=result['keys'], bounds=result['bounds']), audit

    # A literally zero observation column has an immediate exact dependency.
    # In the common Neumann-only case this removes the constant mode without
    # doing any integer elimination. Successful reduced inverse certification
    # proves that the remaining columns are independent. Failure falls through
    # to general exact reduction; a zero screen alone NEVER claims full rank.
    active = [j for j in range(len(target)) if any(row[j] for row in matrix)]
    missing = [j for j in range(len(target)) if j not in active]
    audit['literal_zero_columns'] = missing
    if any(target[j] for j in missing):
        audit.update(route='exact-incompatible', rank=None,
                     exact_incompatibility='literal-zero-column-nonzero-target')
        raise ExactIncompatibility('A zero original observation column has a nonzero target')
    if active and missing:
        audit['zero_column_interval'] = {}
        try:
            result = K.certified_weights([[row[j] for j in active] for row in matrix],
                [target[j] for j in active], keys, base_keys, signed_tau, conversion,
                cancelled=check, evidence=audit['zero_column_interval'])
        except K.Unresolved as error:
            audit['zero_column_interval_refusal'] = dict(type=type(error).__name__, reason=str(error))
        else:
            proof = {key: [G.mpq(value).numerator.digits(16), G.mpq(value).denominator.digits(16)]
                     if isinstance(value, (G.mpfr, G.mpq)) else value
                     for key, value in result['proof'].items()}
            audit.update(route='interval-reduced', rank=len(active),
                interval_proof=proof, independent_columns=active,
                interval_proof_scalar_encoding='exact signed-hex rational pairs; integer fields unchanged',
                precision_bits=result['precision_bits'],
                moment_identity_kind='literal-zero-original-columns-and-nonsingular-reduced-Gram')
            return dict(ordered_keys=result['keys'], bounds=result['bounds']), audit

    # Neumann-only observations cannot determine the constant polynomial mode.
    # Remove only EXACT proved column dependencies, never tolerance ranks or
    # samples. M=B*C and t=C^T*t[J] preserve the unique minimum-norm M*dual.
    audit['rank_reduction'] = {}
    reduced = K.reduce_observations(matrix, target, cancelled=check,
                                      evidence=audit['rank_reduction'])
    if not reduced['compatible']:
        audit.update(route='exact-incompatible', rank=reduced['rank'],
                     exact_incompatibility='original-rectangular-null-witness')
        raise ExactIncompatibility('Exact original observation dependency conflicts with target')
    if reduced['rank'] == 0:
        scaled = {key: G.mpq(0) for key in keys}
        scaled[base_keys[0]] = scaled.get(base_keys[0], G.mpq(0))+signed_tau
        scaled[base_keys[1]] = scaled.get(base_keys[1], G.mpq(0))-signed_tau
        factors = dict(zip(keys, conversion, strict=True))
        factors.update({key: factors.get(key, G.mpq(1)) for key in base_keys})
        physical = {key: value*factors[key] for key, value in scaled.items()}
        audit.update(route='exact-reduced-zero', rank=0, exact_moment_checks=len(target),
                     moment_identity_kind='exact-zero-correction-plus-verified-base-jump')
        return dict(ordered_keys=list(physical),
                    bounds={key: (value, value) for key, value in physical.items()}), audit
    if reduced['rank'] < len(target):
        audit['reduced_interval'] = {}
        try:
            result = K.certified_weights(reduced['matrix'], reduced['target'], keys,
                base_keys, signed_tau, conversion, cancelled=check,
                evidence=audit['reduced_interval'])
        except K.Unresolved as error:
            audit['reduced_interval_refusal'] = dict(type=type(error).__name__, reason=str(error))
        else:
            proof = {key: [G.mpq(value).numerator.digits(16), G.mpq(value).denominator.digits(16)]
                     if isinstance(value, (G.mpfr, G.mpq)) else value
                     for key, value in result['proof'].items()}
            audit.update(route='interval-reduced', rank=reduced['rank'],
                interval_proof=proof,
                interval_proof_scalar_encoding='exact signed-hex rational pairs; integer fields unchanged',
                precision_bits=result['precision_bits'],
                moment_identity_kind='exact-original-column-certificate-and-nonsingular-reduced-Gram')
            return dict(ordered_keys=result['keys'], bounds=result['bounds']), audit

    audit.update(exact_gram_constructed=True, exact_fallback=True, exact={})
    if before_exact is not None:
        before_exact(audit)
    size = len(target)
    gram = []
    for a in range(size):
        check()
        gram.append([sum((row[a]*row[b] for row in matrix), G.mpq(0)) for b in range(size)])
    try:
        dual = K.functional_solve(gram, target, cancelled=check, evidence=audit['exact'])
    except ValueError as error:
        if audit['exact'].get('status') == 'EXACT_INCOMPATIBLE':
            audit.update(route='exact-incompatible', rank=audit['exact']['rank'])
            raise ExactIncompatibility(str(error)) from error
        raise
    scaled = {}
    for key, values in zip(keys, matrix, strict=True):
        check()
        scaled[key] = sum((a*b for a, b in zip(values, dual, strict=True)), G.mpq(0))
    scaled[base_keys[0]] = scaled.get(base_keys[0], G.mpq(0))+signed_tau
    scaled[base_keys[1]] = scaled.get(base_keys[1], G.mpq(0))-signed_tau
    {key: observation(key) for key in scaled}
    for j in range(size):
        check()
    factors = dict(zip(keys, conversion, strict=True))
    factors.update({key: factors.get(key, G.mpq(1)) for key in base_keys})
    physical = {key: value*factors[key] for key, value in scaled.items()}
    audit.update(route='exact-fallback', rank=audit['exact']['rank'],
                 moment_identity_kind='materialised-exact-rational-checks',
                 exact_moment_checks=size)
    return dict(ordered_keys=list(physical), bounds={key: (value, value) for key, value in physical.items()}), audit


def reconstruct(payload, *, boundary_point_faces, boundary_power_faces,
                conductivity=1, cancelled=None, selected_faces=None, observe=None):
    """Same r1 outward-power contract; selected rows retain payload order.

    Duplicate and unknown selectors refuse. Default None means complete rows
    and complete polygon validation. Any explicit selection is labelled partial,
    even if a caller happens to enumerate every face.
    """
    K._require_gmp()
    began = perf_counter()

    def check():
        if cancelled is not None and cancelled():
            raise CancelledError('Certified polygon reconstruction cancelled')

    check()
    cells, faces = payload['cells'], payload['faces']
    ids = {cell['cell_id']: i for i, cell in enumerate(cells)}
    face_ids = {face['face_id'] for face in faces}
    partial = selected_faces is not None
    if partial:
        requested = tuple(selected_faces)
        selected = set(requested)
    else:
        selected = face_ids
    dirichlet, neumann = set(boundary_point_faces), set(boundary_power_faces)
    k = mq(conductivity)
    points = {}
    linked, owners_of = {}, {}
    for i, cell in enumerate(cells):
        check()
        points['cell', i] = tuple(mq(decode(x)) for x in cell['centroid_m'])
        for fid, sign in cell['faces']:
            linked[fid, i] = sign
            owners_of.setdefault(fid, set()).add(i)
    geometry, face_data = {}, {}
    for face in faces:
        check()
        fid = face['face_id']
        owners = sorted((ids[cid], linked[fid, ids[cid]]) for cid in face['owners'])
        centre = tuple(mq(decode(x)) for x in face['centroid_m'])
        normal = tuple(mq(decode(x)) for x in face['area_vector_m2'])
        geometry[fid] = dict(centre=centre, normal=normal, owners=owners)
        face_data[fid] = face
        if fid in dirichlet:
            points['wall', fid] = centre
        elif fid in neumann:
            points['power', fid] = centre
            i, sign = owners[0]
            normal_distance_area = sign*sum(a*(b-c) for a, b, c in
                                            zip(normal, centre, points['cell', i], strict=True))
            geometry[fid]['beta'] = normal_distance_area/(k*sum(a*a for a in normal))
    moments = {}

    def moment(fid):
        if fid not in moments:
            check()
            moments[fid] = face_second_moment(face_data[fid])
            check()
        return moments[fid]

    rows, census = [], []
    interval_faces = exact_faces = exact_attempts = 0
    size = len(EXPONENTS)
    for face in faces:
        if face['face_id'] not in selected:
            continue
        check()
        fid = face['face_id']
        data = geometry[fid]
        centre, normal, owners = data['centre'], data['normal'], data['owners']
        target_moment = moment(fid)
        if fid in neumann:
            key, value = ('power', fid), G.mpq(owners[0][1])
            rows.append(dict(face_id=fid, owners=owners, ordered_keys=[key], bounds={key: (value, value)}))
            census.append(dict(face_id=fid, prescribed_power_exact=True, samples=1,
                               moment_identity_kind='prescribed-exact-transfer'))
            if observe is not None:
                observe('certified-row', dict(row=rows[-1], diagnostics=census[-1]))
            continue
        support = nearest_complete_shell(points.items(), centre, minimum=2*size, cancelled=check)
        ranked = list(support.shell)
        count = len(ranked)
        # .shell omits the tail even when broadphase retained every point.
        # Always request the complete order before the first rank expansion.
        full_order = False
        basis_origin, scale = dyadic_frame(centre, [p for _, _, p in ranked])
        if observe is not None:
            observe('nearest-shell-screened', dict(face_id=fid, **support.diagnostics))

        def observation(key):
            check()
            if key[0] != 'power':
                return point_basis(points[key], basis_origin, scale)
            observed = geometry[key[1]]
            oriented = integrated_flux_basis(observed['centre'], observed['normal'], moment(key[1]),
                                             basis_origin, scale, k)
            return [observed['beta']*observed['owners'][0][1]*value for value in oriented]

        gradient = integrated_flux_basis(centre, normal, target_moment, basis_origin, scale, k)
        i, sign = owners[0]
        ki = ('cell', i)
        kj = ('cell', owners[1][0]) if len(owners) == 2 else ('wall', fid)
        denominator = sign*sum(a*(b-c) for a, b, c in zip(normal, points[kj], points[ki], strict=True))
        tau = k*sum(a*a for a in normal)/denominator
        pi, pj = point_basis(points[ki], basis_origin, scale), point_basis(points[kj], basis_origin, scale)
        target = [g-sign*tau*(a-b) for g, a, b in zip(gradient, pi, pj, strict=True)]
        matrix = [observation(key) for _, key, _ in ranked[:count]]
        expansions = 0
        attempts = []
        while True:
            check()
            keys = [key for _, key, _ in ranked[:count]]
            conversion = [geometry[key[1]]['beta'] if key[0] == 'power' else G.mpq(1) for key in keys]
            if observe is not None:
                observe('before-functional-certification', dict(face_id=fid, target=target,
                    stencil_keys=keys, expansion=expansions, basis_origin=basis_origin, basis_scale=scale,
                    observation_matrix=matrix, gradient=gradient, base_keys=(ki, kj),
                    base_signed_tau=sign*tau, observation_conversion=conversion,
                    exact_gram_constructed=False))
            audit = {}
            attempts.append(audit)
            try:
                result, audit = functional_bounds(matrix, target, keys, (ki, kj), sign*tau, conversion,
                    gradient=gradient, observation=observation, cancelled=check, evidence=audit,
                    before_exact=None if observe is None else lambda item: observe('before-exact-gram',
                        dict(face_id=fid, expansion=expansions, diagnostics=item)))
                break
            except ExactIncompatibility:
                if observe is not None:
                    observe('exact-functional-incompatible', dict(face_id=fid, expansion=expansions, diagnostics=audit))
                if not full_order:
                    ranked = list(support.full_ranking())
                    full_order = True
                    if observe is not None:
                        observe('rank-expansion-full-order', dict(face_id=fid, **support.diagnostics))
                cutoff, end = ranked[count][0], count+1
                while end < len(ranked) and ranked[end][0] == cutoff:
                    end += 1
                matrix.extend(observation(key) for _, key, _ in ranked[count:end])
                count, expansions = end, expansions+1
        exact_attempts += sum(bool(item['exact_fallback']) for item in attempts)
        interval_faces += audit['route'] in ('interval', 'interval-reduced')
        exact_faces += audit['route'] in ('exact-fallback', 'exact-reduced-zero')
        rows.append(dict(face_id=fid, owners=owners, **result))
        census.append(dict(face_id=fid, samples=count, rank=audit['rank'], expanded_shells=expansions,
            power_observations=sum(key[0] == 'power' for _, key, _ in ranked[:count]),
            support_screen=dict(support.diagnostics), functional_attempts=attempts,
            moment_identity_kind=audit['moment_identity_kind']))
        if observe is not None:
            observe('certified-row', dict(row=rows[-1], diagnostics=census[-1]))
            observe('post-certificate', dict(face_id=fid, expansion=expansions,
                all_twenty_moment_identities_certified=True,
                exact_rational_weights_materialised=audit['route'] in ('exact-fallback', 'exact-reduced-zero'),
                moment_identity_kind=audit['moment_identity_kind'], physical_bounds=result['bounds']))
    check()
    return rows, dict(seconds=perf_counter()-began, basis_dimension=size,
                      all_twenty_integrated_moment_identities_certified=True,
                      all_twenty_integrated_moment_checks_exact=interval_faces == 0, census=census,
                      interval_certified_faces=interval_faces, exact_fallback_faces=exact_faces,
                      exact_fallback_attempts=exact_attempts, coefficient_output='exact-rational-enclosures',
                      assembly_requirement='Enclose exact cross-face sums before Decimal80 rounding',
                      moment_certificate_note='Interval route is an algebraic identity, not materialised rational coefficient checks',
                      nearest_shell_rule='conservative interval screening, exact complete shell, full exact rank-expansion fallback',
                      power_input_convention='outward face-integrated watts',
                      power_scaling='normal_distance/(conductivity*face_area), exact area-vector ratio',
                      exterior_temperature_samples=len(dirichlet), prescribed_power_faces=len(neumann),
                      general_planar_convex_face_moments=True, stability_proven=False,
                      production_resource_accounting=False, partial_reconstruction=partial,
                      physical_functional_equations_and_precision_unchanged=True,
                      exact_cubic_basis_frame='nearby binary64 dyadic origin and power-of-two scale',
                      physical_geometry_rounded=False,
                      functional_cancellation_per_scalar=True,
                      reconstruction_scope='SELECTED_FACES_ONLY' if partial else 'ALL_PHYSICAL_FACES',
                      full_incidence_metadata_checked=True,
                      full_polygon_geometry_validated=not partial,
                      full_geometry_acceptance=False,
                      selected_face_ids=[row['face_id'] for row in rows],
                      total_physical_faces=len(faces), polygon_moments_computed=len(moments))

