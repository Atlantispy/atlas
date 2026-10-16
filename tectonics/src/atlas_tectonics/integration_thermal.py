"""I05.2 heat on the moving I03 support, and the lateral-heat rule (I05 R-1 to R-3).

This module starts with the package reproduction of the MC-06 conditional omission bound
(tools/check_i01_lateral_heat.py, tectonics/docs/I01_LATERAL_HEAT.md), used only by a caller that declares the
omission of lateral conduction over windows of fixed contact geometry. The tool stays unchanged and is imported only
by the parity tests; production code never imports it. Arithmetic is exact (fractions.Fraction) with no tolerance.

SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
from fractions import Fraction
import math

import numpy as np

from . import _integration_heat as _heat
from . import integration_sphere as _sphere
from ._validation import TectonicsError


class LateralRefused(TectonicsError):
    """A lateral-heat declaration or certificate that is not admitted; nothing is changed."""


# ----------------------------------------------------------------------------- MC-06 omission bound (reproduction)

LATERAL_POLICY = {'max_cells': 256, 'max_contacts': 1024, 'max_windows': 64, 'input_bits': 4096}
LATERAL_ASSUMPTIONS = {
    'geometry': 'fixed_orthogonal_control_volumes',
    'thermal_properties': 'prescribed_temperature_independent',
    'forcing': 'identical_prescribed_sources_and_vertical_boundaries',
    'lateral_boundaries': 'closed',
    'vertical_operator': 'nonnegative_offdiagonals_nonpositive_row_sums',
    'feedback': 'none',
    'claim': 'semidiscrete_temperature_only',
}


def _rational(value, name, *, positive=False):
    if type(value) not in (int, float, Fraction):
        raise LateralRefused(name+': finite real number required')
    if type(value) is float and not math.isfinite(value):
        raise LateralRefused(name+': finite real number required')
    out = Fraction(value)
    if out < 0 or (positive and out == 0):
        raise LateralRefused(name+': outside nonnegative/positive support')
    if max(abs(out.numerator).bit_length(), out.denominator.bit_length()) > LATERAL_POLICY['input_bits']:
        raise LateralRefused(name+': input precision budget exceeded')
    return out


def _upper_float(value):
    try:
        out = float(value)
    except OverflowError as exc:
        raise LateralRefused('display bound is not representable') from exc
    if not math.isfinite(out):
        raise LateralRefused('display bound is not representable')
    if Fraction(out) < value:
        out = math.nextafter(out, math.inf)
    if not math.isfinite(out):
        raise LateralRefused('display bound is not representable')
    return out


@dataclass(frozen=True, init=False)
class LateralNetwork:
    """Immutable capacities (J/K) and paired contacts G = k A/d (W/K); construction does not prove geometry."""
    capacities: tuple
    contacts: tuple

    def __init__(self, capacities_j_k, contacts, *, assumptions):
        if type(assumptions) is not dict or assumptions != LATERAL_ASSUMPTIONS:
            raise LateralRefused('unsupported geometry, forcing, operator or coupled-feedback claim')
        if type(capacities_j_k) is not list or not 1 <= len(capacities_j_k) <= LATERAL_POLICY['max_cells']:
            raise LateralRefused('a bounded nonempty capacity list is required')
        capacities = tuple(_rational(c, 'heat capacity', positive=True) for c in capacities_j_k)
        if type(contacts) is not list or len(contacts) > LATERAL_POLICY['max_contacts']:
            raise LateralRefused('bounded contact list required')
        pairs, prepared = set(), []
        keys = {'left', 'right', 'conductivity_w_m_k', 'area_m2', 'distance_m'}
        for item in contacts:
            if type(item) is not dict or set(item) != keys:
                raise LateralRefused('contact fields must declare exactly endpoints, k, area and distance')
            i, j = item['left'], item['right']
            if any(type(v) is not int or not 0 <= v < len(capacities) for v in (i, j)) or i == j:
                raise LateralRefused('distinct valid integer contact endpoints required')
            pair = tuple(sorted((i, j)))
            if pair in pairs:
                raise LateralRefused('duplicate or reversed duplicate contact')
            pairs.add(pair)
            k = _rational(item['conductivity_w_m_k'], 'conductivity', positive=True)
            area = _rational(item['area_m2'], 'area', positive=True)
            distance = _rational(item['distance_m'], 'distance', positive=True)
            prepared.append((i, j, k*area/distance))
        object.__setattr__(self, 'capacities', capacities)
        object.__setattr__(self, 'contacts', tuple(prepared))

    def residual_bound(self, differences_k):
        """max_i sum_j G_ij Delta_ij/C_i, in K/s."""
        if type(differences_k) is not list or len(differences_k) != len(self.contacts):
            raise LateralRefused('one whole-window difference bound per declared contact required')
        heat = [Fraction(0) for _ in self.capacities]
        for (i, j, conductance), difference in zip(self.contacts, differences_k):
            flow = conductance*_rational(difference, 'temperature difference bound')
            heat[i] += flow
            heat[j] += flow
        return max(q/c for q, c in zip(heat, self.capacities))


def lateral_admission(network, windows, *, temperature_allowance_k, initial_error_bound_k=0):
    """Conditional whole-window omission bound, never inferred from endpoint or interior samples.

    Each envelope constrains the exact column-only thermal trajectory. The initial error carries the previous
    window's bound; it is not reset by a new call. A sample-only or unknown envelope returns the refused status.
    """
    if type(network) is not LateralNetwork:
        raise LateralRefused('a prepared LateralNetwork is required')
    allowance = _rational(temperature_allowance_k, 'temperature allowance')
    error = _rational(initial_error_bound_k, 'initial error bound')
    if type(windows) is not list or not 1 <= len(windows) <= LATERAL_POLICY['max_windows']:
        raise LateralRefused('a bounded nonempty window list is required')
    result = dict(conditional_temperature_admissible=False, coupled_neck_certified=False,
                  physical_separation_authorised=False, continuum_error_certified=False,
                  status='REFUSED_UNCERTIFIED_ENVELOPE')
    duration, increments = Fraction(0), []
    for window in windows:
        if type(window) is not dict or set(window) != {'duration_s', 'envelope'}:
            raise LateralRefused('each window requires duration_s and envelope only')
        dt = _rational(window['duration_s'], 'duration', positive=True)
        envelope = window['envelope']
        if type(envelope) is not dict or envelope.get('kind') != 'declared_whole_window':
            return result
        if set(envelope) != {'kind', 'difference_bounds_k', 'basis'}:
            raise LateralRefused('whole-window envelope requires bounds and their declared basis')
        if type(envelope['basis']) is not str or not envelope['basis'].strip():
            raise LateralRefused('a nonempty envelope basis is required')
        increment = dt*network.residual_bound(envelope['difference_bounds_k'])
        error += increment
        duration += dt
        increments.append(str(increment))
    passed = error <= allowance
    result.update(status='PASS_CONDITIONAL_THERMAL_BOUND' if passed else 'REFUSED_TEMPERATURE_BUDGET',
                  conditional_temperature_admissible=passed,
                  error_bound_k=_upper_float(error), error_bound_exact_k=str(error),
                  temperature_allowance_exact_k=str(allowance), duration_exact_s=str(duration),
                  window_increments_exact_k=increments, windows=len(windows),
                  cells=len(network.capacities), contacts=len(network.contacts))
    return result


# ----------------------------------------------------------------------------- heat on the moving support (I05.2)

ALGEBRA_RELATIVE = 1e-11            # existing I01 control-policy tolerance (cases/i01_closures_v1.json)
STABILITY = 0.9                     # W07's explicit limit (regional_transport._limit), accepted to (1 + 8 eps)
EPS = 2.**-52
UNRESOLVED_CONTACT = 'unresolved contact'
NONORTHOGONAL = 'nonorthogonal contact'
INCOMPATIBLE = 'incompatible support'
MISSING = 'missing record'
BOUND_ROUNDING = 128                # W07's source-free maximum-principle check: 128 eps of the extreme magnitude


class ThermalRefused(TectonicsError):
    """A heat step that is refused whole; ``code`` names the reason and nothing is changed."""

    def __init__(self, message, code, detail=None):
        super().__init__('%s (%s)' % (message, code))
        self.code = code
        self.detail = detail


def column_of(record, piece, phases):
    """(thicknesses m, capacities J/K) of one piece's sublayers, top down: the declared sublayers scaled by the
    piece's phase volume over area (uniform within a phase), capacities rho cp t A. ``phases`` is the I03 material's
    phase order."""
    volume = dict(zip(phases, piece.volume_m3))
    thickness, capacity = [], []
    for sublayer in record.sublayers:
        ratio = volume[sublayer.phase]/piece.area_m2/record.phase_thickness(sublayer.phase)
        t = sublayer.thickness_m*ratio
        thickness.append(t)
        capacity.append(sublayer.reference_density_kg_m3*sublayer.heat_capacity_j_kg_k*t*piece.area_m2)
    return thickness, capacity


def temperatures(record, piece, heat, reference, phases):
    """Sublayer temperatures from heat through the inverse caloric form; heat is J, the piece's whole sublayer."""
    thickness, _ = column_of(record, piece, phases)
    return [s.temperature(q/(s.reference_density_kg_m3*t*piece.area_m2), reference)
            for s, t, q in zip(record.sublayers, thickness, heat)]


def _heat_of(record, piece, temperature, reference, phases):
    thickness, _ = column_of(record, piece, phases)
    return [s.reference_density_kg_m3*t*piece.area_m2*s.caloric(T, reference)
            for s, t, T in zip(record.sublayers, thickness, temperature)]


def _prepared(record, thickness, dt, cache):
    """The exact modal conduction of one column (reused only while its support, properties and step match)."""
    key = (record.cohort_id, tuple(thickness), dt)
    if key not in cache:
        depth = np.cumsum(thickness)-np.asarray(thickness)/2
        props = [dict(name='%d:%s' % (i, s.material_id), conductivity_w_m_k=s.conductivity_w_m_k,
                      heat_capacity_j_kg_k=s.heat_capacity_j_kg_k, radiogenic_w_m3=s.radiogenic_w_m3)
                 for i, s in enumerate(record.sublayers)]
        bottom = ({'type': 'insulated'} if record.base_temperature_k is None
                  else {'type': 'temperature', 'value_k': record.base_temperature_k})
        boundaries = {'top': {'type': 'temperature', 'value_k': record.surface_temperature_k}, 'bottom': bottom}
        try:
            thermal = _heat.prepare_thermal(np.arange(len(thickness)), depth, np.asarray(thickness),
                                            [float(t) for t in thickness], props,
                                            [s.reference_density_kg_m3 for s in record.sublayers], boundaries)
            cache[key] = (thermal, _heat.prepare_propagator(thermal, dt))
        except (ValueError, RuntimeError) as exc:
            raise ThermalRefused('the column of %r is not admitted by the column heat solve: %s'
                                 % (record.cohort_id, exc), 'unsupported', record.cohort_id) from exc
    return cache[key]


def _edges(network):
    """{(face, face): ((a, b), ...)} for every pair of faces sharing at least one edge of positive length: every
    shared edge, each a to b along the first face's rings, in ring order."""
    owner = {}
    for face in network.faces:
        for ring in (face.vertex_ids,)+tuple(face.holes):
            for a, b in zip(ring, ring[1:]+ring[:1]):
                owner[(a, b)] = face.face_id
    shared = {}
    for (a, b), face in owner.items():
        other = owner.get((b, a))
        if other is not None and face < other:
            shared.setdefault((face, other), []).append((a, b))
    return {pair: tuple(edges) for pair, edges in shared.items()}


def _arc(va, vb):
    return math.atan2(np.linalg.norm(np.cross(va, vb)), float(np.dot(va, vb)))


def _inside_face(network, face_id, node):
    """True when the unit ``node`` lies inside the face (its outer ring, outside its holes): an even-odd test in the
    gnomonic projection about the face's mean direction, where the face's great-circle edges are straight."""
    face = next(f for f in network.faces if f.face_id == face_id)
    direction = dict(zip(network.vertex_ids, np.asarray(network.vertex_direction)))
    outer = np.asarray([direction[v] for v in face.vertex_ids])
    centre = np.array([math.fsum(outer[:, axis]) for axis in range(3)])
    centre /= np.linalg.norm(centre)
    if not float(np.dot(node, centre)) > 0:
        return False
    first = np.cross(centre, np.eye(3)[int(np.argmin(np.abs(centre)))])
    first /= np.linalg.norm(first)
    second = np.cross(centre, first)

    def plane(v):
        v = np.asarray(v)/float(np.dot(v, centre))
        return float(np.dot(v, first)), float(np.dot(v, second))

    def within(ring):
        x, y = plane(node)
        points = [plane(direction[v]) for v in ring]
        inside = False
        for (x1, y1), (x2, y2) in zip(points, points[1:]+points[:1]):
            if (y1 > y) != (y2 > y) and x < x1+(y-y1)*(x2-x1)/(y2-y1):
                inside = not inside
        return inside
    return within(face.vertex_ids) and not any(within(hole) for hole in face.holes)


def _checked_nodes(network, conduction):
    """The declared unit nodes, each of a face of this network and inside that face; refused otherwise."""
    faces = set(network.face_ids)
    nodes = {}
    for face, declared in conduction.nodes:
        if face not in faces:
            raise ThermalRefused('a node is declared for %r, which is not a face of this network' % face,
                                 INCOMPATIBLE, face)
        node = np.asarray(declared, dtype=float)/np.linalg.norm(declared)
        if not _inside_face(network, face, node):
            raise ThermalRefused('the declared node of %r lies outside its face' % face, INCOMPATIBLE, face)
        nodes[face] = node
    return nodes


def _contacts(endpoint, records, conduction):
    """Admitted lateral contacts (R-2): every pair of faces sharing an edge must be admitted, or the step refuses.

    A contact needs a shared boundary (one or more edges, on one great circle), one cohort piece in each face,
    declared node directions inside their faces, orthogonal to the boundary within I03's attachment band, on opposite
    sides and crossing inside one of its edges, and identical sublayer depths. The conductance of sublayer l is
    G = A/(d_i/k_i + d_j/k_j) with A = R theta t_l over the whole shared boundary (theta the sum of its edges' arcs; the
    prism convention of I03's V = h A, the wedge factor 1 - z/R omitted, declared) and d = R asin|n.s|.
    """
    network, material = endpoint.network, endpoint.material
    radius = network.sphere.radius_m
    nodes = _checked_nodes(network, conduction)
    direction = dict(zip(network.vertex_ids, np.asarray(network.vertex_direction)))
    pieces = {}
    for index, piece in enumerate(material.pieces()):
        pieces.setdefault(piece.face_id, []).append((index, piece))
    out = []
    for (left, right), edges in sorted(_edges(network).items()):
        if len(pieces[left]) != 1 or len(pieces[right]) != 1:
            raise ThermalRefused('faces %r and %r share an edge but hold several cohort pieces: which one touches it '
                                 'is not represented' % (left, right), UNRESOLVED_CONTACT, (left, right))
        if left not in nodes or right not in nodes:
            raise ThermalRefused('faces %r and %r share an edge but declare no node' % (left, right),
                                 UNRESOLVED_CONTACT, (left, right))
        normals = []
        for a, b in edges:
            normal = np.cross(direction[a], direction[b])
            normals.append(normal/np.linalg.norm(normal))
        normal = normals[0]
        if any(np.linalg.norm(np.cross(n, normal)) > _sphere.ATTACHMENT_BAND_RAD or not float(np.dot(n, normal)) > 0
               for n in normals[1:]):
            raise ThermalRefused('the shared boundary of %r and %r is not one great-circle arc: one two-point flux '
                                 'cannot be orthogonal to it' % (left, right), NONORTHOGONAL, (left, right))
        si, sj = nodes[left], nodes[right]
        crossing = np.cross(si, sj)
        across = float(np.dot(normal, si))*float(np.dot(normal, sj))
        if abs(float(np.dot(normal, crossing))) > _sphere.ATTACHMENT_BAND_RAD or not across < 0:
            raise ThermalRefused('the nodes of %r and %r are not orthogonal across their shared boundary'
                                 % (left, right), NONORTHOGONAL, (left, right))
        line = np.cross(crossing/np.linalg.norm(crossing), normal)

        def on(a, b):
            va, vb = direction[a], direction[b]
            point = line if np.dot(line, va+vb) >= 0 else -line
            return np.dot(np.cross(va, point), normal) >= 0 and np.dot(np.cross(point, vb), normal) >= 0
        if not any(on(a, b) for a, b in edges):
            raise ThermalRefused('the node line of %r and %r crosses outside their shared boundary' % (left, right),
                                 NONORTHOGONAL, (left, right))
        (i, pi), (j, pj) = pieces[left][0], pieces[right][0]
        ri, rj = records[pi.cohort_id], records[pj.cohort_id]
        ti, _ = column_of(ri, pi, material.phases)
        tj, _ = column_of(rj, pj, material.phases)
        depths_i, depths_j = np.cumsum(ti), np.cumsum(tj)
        if len(ti) != len(tj) or np.any(np.abs(depths_i-depths_j) > _sphere.RELATIVE_TOLERANCE*np.maximum(
                depths_i, depths_j)):
            raise ThermalRefused('the columns of %r and %r have different sublayer depths: a two-point flux between '
                                 'them is not horizontal' % (left, right), NONORTHOGONAL, (left, right))
        theta = math.fsum(_arc(direction[a], direction[b]) for a, b in edges)
        di, dj = (radius*math.asin(min(1., abs(float(np.dot(normal, s))))) for s in (si, sj))
        conductances = [radius*theta*min(a_t, b_t)/(di/a.conductivity_w_m_k+dj/b.conductivity_w_m_k)
                        for a_t, b_t, a, b in zip(ti, tj, ri.sublayers, rj.sublayers)]
        out.append((i, j, conductances))
    return out


def omission_cells(endpoint, records):
    """(capacities J/K, contacts) of the state's own lateral network, which an MC-06 omission certificate must cover.

    Cells are every piece's sublayers, in I03 piece order and top down (capacity rho cp t A). A contact is every pair
    of cells that can exchange heat laterally: of two pieces in faces sharing an edge, or of two pieces in one face
    (their side-by-side layout is not represented), whose sublayers overlap in depth by more than I03's relative
    tolerance. Contacts are (i, j) cell indices with i < j, sorted. Nothing here proves geometry or conductance.
    """
    material = endpoint.material
    pieces = material.pieces()
    offsets, capacities, depths = [0], [], []
    for piece in pieces:
        thickness, capacity = column_of(records[piece.cohort_id], piece, material.phases)
        capacities.extend(capacity)
        bottoms = np.cumsum(thickness)
        depths.append([(top, bottom) for top, bottom in zip(np.concatenate([[0.], bottoms[:-1]]), bottoms)])
        offsets.append(len(capacities))
    by_face = {}
    for index, piece in enumerate(pieces):
        by_face.setdefault(piece.face_id, []).append(index)
    pairs = set()
    for indices in by_face.values():
        pairs.update((p, q) for n, p in enumerate(indices) for q in indices[n+1:])
    for left, right in _edges(endpoint.network):
        pairs.update((p, q) for p in by_face.get(left, ()) for q in by_face.get(right, ()))
    contacts = set()
    for p, q in pairs:
        scale = _sphere.RELATIVE_TOLERANCE*max(depths[p][-1][1], depths[q][-1][1])
        for l, (top_p, bottom_p) in enumerate(depths[p]):
            for m, (top_q, bottom_q) in enumerate(depths[q]):
                if min(bottom_p, bottom_q)-max(top_p, top_q) > scale:
                    contacts.add(tuple(sorted((offsets[p]+l, offsets[q]+m))))
    return tuple(capacities), tuple(sorted(contacts))


def _fixed_geometry(parent, step):
    """True when the interval keeps every lateral contact: no rows, no mesh change, every plate turning alike."""
    rotations = {tuple(rotation.quaternion) for _, rotation in step.motion.rotations}
    return (not step.map.rows and not step.map.mesh_rows and len(rotations) == 1 and not step.motion.events
            and parent.network.face_ids == step.state.network.face_ids)


def conducted(endpoint, records, heat, reference, parent, step, conduction, budget=None, carried=Fraction(0)):
    """(sublayer heat after conduction over the interval, report): per substep, in mode 'solve', an explicit
    (forward-Euler) lateral exchange over admitted contacts, then the exact modal vertical conduction of every piece;
    in mode 'omit', the vertical conduction only, with a passing MC-06 certificate on fixed contact geometry.

    An omission's MC-06 network is the state's own (_omission_network): its cells and the R-2 conductances of its
    admitted contacts, derived from the declared IN-05 k and the declared nodes, never supplied (ruling (c), 4 October
    2026). Its initial error bound is ``carried``, the moving state's carried bound; None (UNKNOWN, after an interval
    without conduction) refuses. The state's own temperatures at the start and at the end of the interval are samples
    of the column-only trajectory the envelopes bound: an envelope they contradict refuses (a sample cannot prove an
    envelope, but it can refute one).

    Each sub-operator keeps the discrete maximum principle (the exchange is a convex combination while
    dt (sum G)/C <= 0.9, W07's limit with G_bdy = 0 for the lateral operator, whose boundaries are closed; the vertical
    solve is exact), so their Lie composition does: without radiogenic heat no temperature may leave the range of the
    starting and fixed boundary values, checked as W07 checks it. Energy closes per piece to ALGEBRA_RELATIVE.
    """
    duration = endpoint.network.time_s-parent.network.time_s
    pieces = endpoint.material.pieces()
    phases = endpoint.material.phases
    contacts, certificate, omission = [], None, None
    if conduction.lateral == 'solve':
        contacts = _contacts(endpoint, records, conduction)
    else:
        if not _fixed_geometry(parent, step):
            raise ThermalRefused('omitting lateral conduction is admitted only over fixed contact geometry (MC-06)',
                                 'unsupported', 'omit')
        if carried is None:
            raise ThermalRefused('the carried lateral-omission bound is UNKNOWN after an interval without conduction: '
                                 'an omission cannot chain from it', 'unsupported', 'certificate')
        omission = _omission_network(endpoint, records, _contacts(endpoint, records, conduction))
    substeps = conduction.substeps
    dt = duration/substeps
    cache, columns = {}, []
    for index, piece in enumerate(pieces):
        record = records[piece.cohort_id]
        thickness, capacity = column_of(record, piece, phases)
        thermal, propagator = _prepared(record, thickness, dt, cache)
        columns.append((record, piece, thickness, capacity, thermal, propagator))
    lateral = [[0.]*len(column[2]) for column in columns]
    worst = 0.
    for i, j, conductances in contacts:
        for l, g in enumerate(conductances):
            lateral[i][l] += g
            lateral[j][l] += g
    for (_, _, _, capacity, _, _), loss in zip(columns, lateral):
        for c, g in zip(capacity, loss):
            worst = max(worst, dt*g/c)
    if worst > STABILITY*(1+8*EPS):
        raise ThermalRefused('the explicit lateral step is unstable: dt (sum G)/C = %r exceeds %r; declare more '
                             'substeps' % (worst, STABILITY), 'unsupported', 'stability')
    temperature = [temperatures(c[0], c[1], q, reference, phases) for c, q in zip(columns, heat)]
    if omission is not None:
        certificate = _certified(conduction.declared_certificate(), duration, omission,
                                 [t for column in temperature for t in column], carried)
    bounded = not any(s.radiogenic_w_m3 for c in columns for s in c[0].sublayers)
    if bounded:
        values = [t for column in temperature for t in column]+[c[0].surface_temperature_k for c in columns]+[
            c[0].base_temperature_k for c in columns if c[0].base_temperature_k is not None]
        low, high = min(values), max(values)
        tolerance = BOUND_ROUNDING*EPS*max(abs(low), abs(high))
    totals = [dict(top=0., base=0., radiogenic=0., lateral=0.) for _ in columns]
    for _ in range(substeps):
        flux = [[0.]*len(c[2]) for c in columns]                      # W into each sublayer
        for i, j, conductances in contacts:
            for l, g in enumerate(conductances):
                q = g*(temperature[j][l]-temperature[i][l])
                flux[i][l] += q
                flux[j][l] -= q
        for k, column in enumerate(columns):                           # the explicit lateral exchange
            temperature[k] = [t+dt*q/c for t, q, c in zip(temperature[k], flux[k], column[3])]
            totals[k]['lateral'] += math.fsum(flux[k])*dt
        for k, (record, piece, thickness, capacity, thermal, propagator) in enumerate(columns):
            area = piece.area_m2
            theta = np.asarray(temperature[k])-thermal.steady_k
            theta_new, integral = _heat.conduct(propagator, theta, np.zeros(len(thickness)))
            g_top, g_bottom = thermal.boundary_conductance
            top_out = area*g_top*(integral[0]+(thermal.steady_k[0]-record.surface_temperature_k)*dt)
            base_in = 0. if record.base_temperature_k is None else area*g_bottom*(
                (record.base_temperature_k-thermal.steady_k[-1])*dt-integral[-1])
            totals[k]['top'] += top_out
            totals[k]['base'] += base_in
            totals[k]['radiogenic'] += area*math.fsum(thermal.radiogenic)*dt
            temperature[k] = list(thermal.steady_k+theta_new)
        if bounded and any(not low-tolerance <= t <= high+tolerance for column in temperature for t in column):
            raise ThermalRefused('the source-free conduction step leaves the range of its starting and boundary '
                                 'temperatures (maximum principle)', 'unsupported', 'maximum principle')
    if omission is not None:                     # the column-only trajectory at the window end
        _refuted(conduction.declared_certificate()['windows'][-1], omission[1],
                 [t for column in temperature for t in column], 'end')
    out, residual = [], 0.
    for k, (record, piece, thickness, capacity, thermal, propagator) in enumerate(columns):
        new = _heat_of(record, piece, temperature[k], reference, phases)
        change = math.fsum(new)-math.fsum(heat[k])
        terms = totals[k]
        booked = -terms['top']+terms['base']+terms['radiogenic']+terms['lateral']
        scale = math.fsum(abs(v) for v in terms.values())+math.fsum(abs(a-b) for a, b in zip(new, heat[k]))
        if scale > 0:
            residual = max(residual, float(abs(change-booked)/scale))
        out.append(new)
    if residual > ALGEBRA_RELATIVE:
        raise ThermalRefused('the conduction step does not close its energy: relative residual %r' % residual,
                             'unsupported', 'energy closure')
    report = dict(mode=conduction.lateral, substeps=substeps, contacts=len(contacts),
                  scheme='Lie splitting: explicit lateral exchange, then exact vertical conduction (first order)',
                  stability=float(worst), closure_relative=residual, certificate=certificate,
                  surface_out_j=math.fsum(t['top'] for t in totals), base_in_j=math.fsum(t['base'] for t in totals),
                  radiogenic_j=math.fsum(t['radiogenic'] for t in totals),
                  lateral_net_j=math.fsum(t['lateral'] for t in totals),
                  wedge_omission=dict(convention='prism (V = h A): the omitted wedge factor is in the capacity and '
                                                 'thickness, about 2 z/R in volume at depth z; R cancels in G',
                                      max_thickness_over_radius=max(math.fsum(c[2]) for c in columns)
                                      / endpoint.network.sphere.radius_m))
    return out, report


CERTIFICATE_FIELDS = {'windows', 'temperature_allowance_k'}


def _omission_network(endpoint, records, contacts):
    """(the MC-06 LateralNetwork of the state's own cells and admitted contacts, its contact cell pairs in order).

    Cells are omission_cells' (every piece sublayer, capacity rho cp t A). Each contact's conductance is the R-2 G of
    sublayer l between two admitted pieces, from the declared k and nodes (passed to MC-06 as k A/d with k = d = 1,
    so the exact rational is G itself). The admitted contacts must be exactly omission_cells' topology: no missing
    contact and none invented.
    """
    capacities, required = omission_cells(endpoint, records)
    offsets = [0]
    for piece in endpoint.material.pieces():
        offsets.append(offsets[-1]+len(records[piece.cohort_id].sublayers))
    derived = {}
    for i, j, conductances in contacts:
        for l, g in enumerate(conductances):
            derived[tuple(sorted((offsets[i]+l, offsets[j]+l)))] = g
    if set(derived) != set(required):
        missing = sorted(set(required)-set(derived))
        raise ThermalRefused('the admitted contacts are not the state\'s lateral contacts (%d missing): an omission '
                             'needs every contact' % len(missing), INCOMPATIBLE, 'certificate')
    order = tuple(required)
    try:
        network = LateralNetwork(list(capacities), [dict(left=a, right=b, conductivity_w_m_k=1, area_m2=derived[a, b],
                                                         distance_m=1) for a, b in order],
                                 assumptions=dict(LATERAL_ASSUMPTIONS))
    except LateralRefused as exc:
        raise ThermalRefused('the state\'s lateral network is not admitted by MC-06: '+str(exc), 'unsupported',
                             'certificate') from exc
    return network, order


def _refuted(window, order, cells, when):
    """Refuse a whole-window envelope that the state's own cell temperatures (a sample at the window's start or end)
    contradict: each contact's bound must be at least |T_i - T_j|, compared exactly."""
    try:
        bounds = window['envelope']['difference_bounds_k']
        if type(bounds) is not list or len(bounds) != len(order):
            return                                # MC-06 refuses a mis-sized envelope by itself
        for (a, b), bound in zip(order, bounds):
            if type(bound) in (int, float) and Fraction(bound) < abs(Fraction(cells[a])-Fraction(cells[b])):
                raise ThermalRefused('the declared envelope of contact (%d, %d), %r K, is refuted by the state\'s own '
                                     'temperatures at the window %s (difference %r K)'
                                     % (a, b, bound, when, abs(cells[a]-cells[b])), 'unsupported', 'certificate')
    except (KeyError, TypeError, IndexError):
        return                                    # malformed: _certified or MC-06 refuses it with its own code


def _certified(certificate, duration, omission, cells, carried):
    """Re-run the MC-06 admission the caller declares, on the state's own network and from the carried bound.

    The certificate declares only its window (exactly one per interval, ruling of 4 October 2026: a whole-window
    envelope, one bound per contact in the order of omission_cells) and its temperature allowance; the network is the
    state's own (_omission_network), never declared.
    The initial error bound is the moving state's carried bound (a declared one must equal it; it is never reset).
    The first window's envelope must not be refuted by the state's start temperatures ``cells``. Only a passing
    whole-window bound over exactly this interval admits the omission; the passing bound is carried on.
    """
    network, order = omission
    try:
        if not CERTIFICATE_FIELDS <= set(certificate) <= CERTIFICATE_FIELDS | {'initial_error_bound_k'}:
            raise ThermalRefused('an MC-06 certificate declares exactly its windows and temperature allowance (and '
                                 'optionally initial_error_bound_k); the cells and conductances are the state\'s own',
                                 MISSING, 'certificate')
        if type(certificate['windows']) is not list or len(certificate['windows']) != 1:
            raise ThermalRefused('an omission certificate has exactly one window per interval: the state samples '
                                 'only its start and end, so a middle window\'s envelope could never be refuted',
                                 'unsupported', 'certificate')
        windows = sum((Fraction(w['duration_s']) for w in certificate['windows']), Fraction(0))
        if windows != Fraction(duration):
            raise ThermalRefused('the MC-06 windows cover %r s, not the interval of %r s' % (float(windows), duration),
                                 'unsupported', 'certificate')
        initial = certificate.get('initial_error_bound_k', str(carried))
        if type(initial) not in (int, float, str) or Fraction(initial) != carried:
            raise ThermalRefused('the MC-06 initial error bound must be the carried bound %s K; it is never reset'
                                 % carried, INCOMPATIBLE, 'certificate')
        _refuted(certificate['windows'][0], order, cells, 'start')
        result = lateral_admission(network, [dict(w) for w in certificate['windows']],
                                   temperature_allowance_k=certificate['temperature_allowance_k'],
                                   initial_error_bound_k=carried)
    except LateralRefused as exc:
        raise ThermalRefused('the MC-06 certificate is not admitted: '+str(exc), 'unsupported', 'certificate') from exc
    except (KeyError, TypeError, ValueError, AttributeError, ZeroDivisionError, IndexError) as exc:
        if isinstance(exc, ThermalRefused):
            raise
        raise ThermalRefused('the MC-06 certificate is incomplete', MISSING, 'certificate') from exc
    if result['status'] != 'PASS_CONDITIONAL_THERMAL_BOUND':
        raise ThermalRefused('the MC-06 certificate does not pass (%s): lateral conduction cannot be omitted'
                             % result['status'], 'unsupported', 'certificate')
    return dict(status=result['status'], error_bound_exact_k=result['error_bound_exact_k'],
                initial_error_bound_exact_k=str(carried), increments_exact_k=result['window_increments_exact_k'],
                cells=len(network.capacities), contacts=len(order),
                conductances='derived: R-2 G from the declared k and nodes')


# ----------------------------------------------------------------------------- occupied-ocean means (W06 rule)

def occupied_mean(values_and_areas):
    """Area-weighted mean over occupied material only: None when nothing is occupied, never a zero temperature.

    ``values_and_areas`` holds (value, occupied area m2) per occupied piece; each value is that piece's own state
    (for example its own conducted column, at its own age), so the mean is the age-distribution integral, never the
    value at the mean age. Values and areas must be finite real numbers and areas nonnegative; a zero area is
    unoccupied. Anything else refuses; nothing is dropped silently.
    """
    rows = []
    for row in values_and_areas:
        value, area = row
        for number, name in ((value, 'value'), (area, 'occupied area')):
            if type(number) not in (int, float, np.float64) or not math.isfinite(number):
                raise ThermalRefused('an occupied-mean %s must be a finite real number' % name, MISSING, name)
        if area < 0:
            raise ThermalRefused('an occupied area is never negative', MISSING, 'occupied area')
        if area > 0:
            rows.append((float(value), float(area)))
    if not rows:
        return None
    total = math.fsum(a for _, a in rows)
    return math.fsum(v*a for v, a in rows)/total


def face_mean(moving, sphere, face_id, value, *, occupied):
    """The occupied-material mean of one face: each piece whose cohort record occupied admits contributes
    value(record, piece, heat) weighted by its own area; None when no such piece occupies the face (W06: masked
    entries are not temperatures; the mean is over occupied oceanic material, never the whole cell). ``moving`` must
    be the moving state of exactly ``sphere``, and ``face_id`` one of its faces."""
    from . import integration_material as _material
    _material.bound_moving(moving, sphere)
    if face_id not in sphere.network.face_ids:
        raise ThermalRefused('%r is not a face of this network' % (face_id,), MISSING, face_id)
    rows = []
    for index, piece in enumerate(sphere.material.pieces()):
        if piece.face_id == face_id:
            record = moving.cohort(piece.cohort_id)
            if occupied(record):
                rows.append((value(record, piece, moving.heat_j(index).tolist()), piece.area_m2))
    return occupied_mean(rows)


def mean_age_cooling(*args, **kwargs):
    """Cooling a mixture at its mean age is refused (W06; CM-02): every piece keeps its own history."""
    raise ThermalRefused('cooling a mixture of ages at its mean age is not admitted; average the pieces, each at its '
                         'own age', 'unsupported', 'mean-age cooling')
