"""Seeded, crust-conditioned INITIAL kinematics, not inferred plate dynamics.

SPDX-License-Identifier: AGPL-3.0-only
Forward-time rotations in a named plate-fixed frame. All deformation starts now;
no mature ridge, slab, polarity, mantle force, or finite-time stability is implied.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time

from new_world_contract import ContractError, validate_plan

METHOD = 'atlas.initial-motion.v1'
YEAR = 365.25*86400.
CONTINENTAL_AFFINITY = 4.  # Declared dimensionless scenario prior, NOT rheology.
MAX_RECORD = 8 << 20
_FILE = Path(__file__).resolve()
_LOADED_HASH = hashlib.sha256(_FILE.read_bytes()).hexdigest()
REFERENCES = (
    'https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities',
    'https://www.gplates.org/docs/pygplates/generated/pygplates.NetRotationModel',
    'https://www.nature.com/articles/224125a0',
    'https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2001gc000252',
)


def _fail(message):
    raise ContractError('MOTION_REFUSED', message)


def _encode(record):
    raw = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(raw) > MAX_RECORD:
        _fail('Initial-motion record exceeds its bounded envelope.')
    return raw


@dataclass(frozen=True, slots=True)
class WorldMotion:
    """Immutable canonical bytes; callers receive detached descriptors."""
    payload: bytes

    def __post_init__(self):
        if type(self.payload) is not bytes or not 0 < len(self.payload) <= MAX_RECORD:
            _fail('Invalid initial-motion payload.')
        try:
            record = json.loads(self.payload)
            if type(record) is not dict or record.get('schema') != METHOD or _encode(record) != self.payload:
                _fail('Non-canonical initial-motion payload.')
        except (ValueError, RecursionError, UnicodeError) as exc:
            _fail('Malformed initial-motion payload.')

    @property
    def motion_id(self):
        return hashlib.sha256(self.payload).hexdigest()

    def descriptor(self):
        return json.loads(self.payload)


def _source_binding():
    import new_world_arcs
    digest = hashlib.sha256(_FILE.read_bytes()).hexdigest()
    if digest != _LOADED_HASH:
        raise ContractError('SOURCE_MISMATCH', 'Initial-motion adapter changed while loaded.')
    try:
        arc_hash = new_world_arcs.source_hash()
    except ValueError as exc:
        raise ContractError('SOURCE_MISMATCH', 'Initial-motion arc adapter changed while loaded.') from exc
    return dict(motion_sha256=digest, arcs_sha256=arc_hash)


def _draw(seed, label):
    raw = hashlib.sha256(bytes.fromhex(seed)+b'\0'+label.encode('ascii')).digest()
    return (int.from_bytes(raw[:8], 'big') >> 11)*2.**-53


def _arc(a, b):
    import numpy as np
    left = np.cross(a, b)
    sine = float(np.linalg.norm(left))
    angle = math.atan2(sine, float(np.dot(a, b)))
    if sine < 1e-12 or not 0 < angle < math.pi-1e-10:
        _fail('Degenerate or unresolved antipodal interplate arc.')
    left /= sine
    return np.cross(left, a), left, angle


def _speed_gram(a, u, start, end):
    """Positive midpoint decomposition of integral I-r(s)r(s)^T."""
    import numpy as np
    basis, weights = _speed_parts(a,u,start,end)
    return sum(w*np.outer(v,v) for v,w in zip(basis,weights))


def _speed_parts(a, u, start, end):
    import numpy as np
    d = end-start
    mid = .5*(start+end)
    if d <= 0 or d > math.pi:
        _fail('Speed integration requires a positive minor-arc interval.')
    small = d**3/12*(1-d*d/20+d**4/840-d**6/60480) if d < .1 else .5*(d-math.sin(d))
    r = a*math.cos(mid)+u*math.sin(mid)
    tangent = -a*math.sin(mid)+u*math.cos(mid)
    return (r,tangent,np.cross(a,u)), (small,d-small,d)


def _speed_integral(delta, a, u, start, end):
    """Sum nonnegative projections, stable even on tiny crust intersections."""
    basis, weights = _speed_parts(a,u,start,end)
    return math.fsum(w*float(delta@v)**2 for v,w in zip(basis,weights))


def _opening_breaks(A, B, angle):
    """All interior zeros of A*cos(s)+B*sin(s), without a display threshold."""
    if A == B == 0.:
        return []
    root = math.atan2(-A, B)
    return sorted(x for k in range(-2, 3) if 0 < (x := root+k*math.pi) < angle)


def _opening_range(A, B, lo, hi):
    points = [lo, hi]
    root = math.atan2(B, A)
    points.extend(x for k in range(-2, 3) if lo < (x := root+k*math.pi) < hi)
    values = [A*math.cos(s)+B*math.sin(s) for s in points]
    return min(values), max(values)


def _opening_uncertainty(left_omega, right_omega, radius, angle):
    """Round-off allowance, not a physical speed/transform threshold.

    Covers subtraction, dot products and the conditioned arc frame. A normal
    component inside this envelope is explicitly unresolved, not pure sliding.
    """
    import numpy as np
    scale = np.linalg.norm(left_omega)+np.linalg.norm(right_omega)
    return 64*np.finfo(float).eps*radius*float(scale)/abs(math.sin(angle))


def _junction_system(atlas, edge_data, plates, free):
    """Eliminate each junction's two tangent velocities, retaining C*omega=0."""
    import numpy as np
    incident = {}
    for item in edge_data:
        for vertex in atlas.edge_vertices[item['index']]:
            incident.setdefault(int(vertex), []).append(item)
    rows, junctions = [], []
    for vertex, edges in sorted(incident.items()):
        owners = {p for e in edges for p in (e['left'], e['right'])}
        if len(owners) < 3:
            continue
        r = atlas.vertex_directions[vertex]
        axis = np.eye(3)[int(np.argmin(np.abs(r)))]
        t1 = np.cross(r, axis); t1 /= np.linalg.norm(t1)
        basis = np.column_stack((t1, np.cross(r, t1)))
        N = np.array([-e['normal_left'] @ basis for e in edges])
        B = np.zeros((len(edges), 3*len(plates)))
        for i, e in enumerate(edges):
            coeff = .5*np.cross(r, -e['normal_left'])
            for p in (e['left'], e['right']):
                j = plates.index(p); B[i, 3*j:3*j+3] += coeff
        U, singular, _ = np.linalg.svd(N, full_matrices=True)
        if len(singular) < 2 or singular[1] < 1e-10:
            _fail('Junction tangent geometry is unresolved.')
        rows.extend(U[:, 2:].T @ B[:, free])
        junctions.append((vertex, edges, basis, N, B[:, free]))
    C = np.asarray(rows).reshape((-1, len(free)))
    return C, junctions


def _prior_precision(plate_weights):
    """Eliminate a common Euler residual, not a physical net-rotation frame.

    min_c sum_i w_i |omega_i - prior_i - c|^2 has this precision.
    Its only nullspace is a common rotation; an anchor removes that gauge.
    """
    import numpy as np
    w = np.asarray(plate_weights, dtype=float)
    return np.kron(np.diag(w)-np.outer(w, w)/w.sum(), np.eye(3))


def _reconcile(atlas, intervals, crust_types, seed, *, affinity=CONTINENTAL_AFFINITY,
               anchor=None):
    """Small deterministic constrained quadratic solve; one native thread."""
    import numpy as np
    plates = list(atlas.plate_ids)
    areas = atlas.areas(by_plate=True)
    if anchor is None:
        anchor = min(plates, key=lambda p: (-areas[p], p))
    if anchor not in plates:
        _fail('The motion reference must be one of the represented plates.')
    fixed = plates.index(anchor)
    free = [i for i in range(3*len(plates)) if i//3 != fixed]
    prior = []
    for p in plates:
        z = 2*_draw(seed, p+'/z')-1
        phi = 2*math.pi*_draw(seed, p+'/azimuth')
        scale = .5+_draw(seed, p+'/magnitude')
        prior.append(scale*np.array([math.sqrt(1-z*z)*math.cos(phi), math.sqrt(1-z*z)*math.sin(phi), z]))
    prior = np.asarray(prior)
    edge_data, total_angle = [], 0.
    for index in atlas.interplate_edges:
        edge = atlas.edge(index)
        a, b = atlas.vertex_directions[atlas.edge_vertices[index]]
        u, left, angle = _arc(a, b)
        edge_data.append(dict(index=int(index), left=edge.left_plate_id, right=edge.right_plate_id,
                              a=a, u=u, normal_left=left, angle=angle))
        total_angle += angle
    if not edge_data:
        _fail('At least two interacting plates are required.')
    by_edge = {e['index']: e for e in edge_data}
    weights = np.asarray([areas[p]/sum(areas.values()) for p in plates])
    precision = _prior_precision(weights)
    H = precision.copy()
    for interval in intervals:
        # Ambiguous/touching province boundaries supply no invented material affinity.
        if (interval.end_fraction <= interval.start_fraction or len(interval.column_ids) != 1
                or crust_types[interval.column_ids[0]] != 'continental'):
            continue
        e = by_edge[interval.edge_index]
        G = affinity*_speed_gram(e['a'], e['u'], interval.start_fraction*e['angle'],
                                 interval.end_fraction*e['angle'])/total_angle
        li, ri = plates.index(e['left'])*3, plates.index(e['right'])*3
        H[li:li+3, li:li+3] += G; H[ri:ri+3, ri:ri+3] += G
        H[li:li+3, ri:ri+3] -= G; H[ri:ri+3, li:li+3] -= G
    C, junctions = _junction_system(atlas, edge_data, plates, free)
    if len(C):
        _, singular, Vt = np.linalg.svd(C, full_matrices=True)
        threshold = 1e-11*max(1., float(singular[0]))
        rank = int(np.count_nonzero(singular > threshold))
        # A nearly singular rank transition is refused rather than guessed.
        if any(threshold/100 < s < threshold*100 for s in singular):
            _fail('Junction constraint rank is numerically ambiguous.')
        Z = Vt[rank:].T
    else:
        rank, Z = 0, np.eye(len(free))
    if Z.shape[1] == 0:
        _fail('The selected junction law leaves no relative plate motion.')
    rhs = (precision @ prior.ravel())[free]
    h = H[np.ix_(free, free)]
    x = Z @ np.linalg.solve(Z.T @ h @ Z, Z.T @ rhs)
    omega = np.zeros(3*len(plates)); omega[free] = x
    omega = omega.reshape((-1, 3))
    # Report adjustment in the same frame-neutral metric as the fit, before
    # applying the independent physical-speed normalisation.
    centred_prior = prior-np.average(prior, axis=0, weights=weights)
    residual = omega-prior
    residual -= np.average(residual, axis=0, weights=weights)
    prior_norm2 = float(np.sum(weights[:, None]*centred_prior**2))
    adjustment = math.sqrt(float(np.sum(weights[:, None]*residual**2))/max(prior_norm2, 1e-60))
    integral = 0.
    for e in edge_data:
        delta = omega[plates.index(e['right'])]-omega[plates.index(e['left'])]
        integral += _speed_integral(delta,e['a'],e['u'],0.,e['angle'])
    rms = math.sqrt(integral/total_angle)
    if rms < 1e-10:
        _fail('Junction reconciliation collapsed the selected relative motion.')
    target_cm_year = 1.+7.*_draw(seed, 'boundary-rms-cm-year')
    unit_scale = target_cm_year*.01/YEAR/(atlas.sphere.radius_m*rms)
    omega *= unit_scale
    achieved_integral = math.fsum(_speed_integral(
        omega[plates.index(e['right'])]-omega[plates.index(e['left'])],
        e['a'],e['u'],0.,e['angle']) for e in edge_data)
    achieved = math.sqrt(achieved_integral/total_angle)*atlas.sphere.radius_m*YEAR*100
    junction_records = []
    max_residual = 0.
    for vertex, edges, basis, N, B in junctions:
        rhs = B @ omega.ravel()[free] * atlas.sphere.radius_m
        tangent, _, _, _ = np.linalg.lstsq(N, rhs, rcond=None)
        residual = float(np.max(np.abs(N@tangent-rhs)))
        max_residual = max(max_residual, residual)
        junction_records.append(dict(vertex_index=vertex, position=atlas.vertex_directions[vertex].tolist(),
            velocity_m_s=(basis@tangent).tolist(), residual_m_s=residual,
            edge_indices=[e['index'] for e in edges]))
    if max_residual > target_cm_year*.01/YEAR*1e-9:
        _fail('Initial junction-normal velocities are incompatible.')
    diagnostics = dict(constraint_rank=rank, relative_degrees_of_freedom=int(Z.shape[1]),
        continental_affinity=affinity, target_boundary_rms_cm_year=target_cm_year,
        achieved_boundary_rms_cm_year=achieved,
        prior_fit='area-weighted-common-rotation-eliminated.v1',
        relative_prior_adjustment=adjustment,
        relative_prior_adjustment_metric='area-weighted-centred-euler-residual',
        max_junction_residual_m_s=max_residual)
    return plates, anchor, omega, edge_data, junction_records, diagnostics


def _segments(atlas, structure, intervals, plates, omega, edge_data, check):
    import numpy as np
    by_edge = {e['index']: e for e in edge_data}
    columns = {c.column_id: c for c in structure.state.case.columns}
    segments, contacts = [], []
    continental_integral = continental_angle = 0.
    for interval in intervals:
        check()
        e = by_edge[interval.edge_index]
        lw, rw = omega[plates.index(e['left'])], omega[plates.index(e['right'])]
        delta = rw-lw
        A, B = atlas.sphere.radius_m*float(delta@e['u']), -atlas.sphere.radius_m*float(delta@e['a'])
        shear = atlas.sphere.radius_m*float(delta@e['normal_left'])
        uncertainty = _opening_uncertainty(lw, rw, atlas.sphere.radius_m, e['angle'])
        lo, hi = interval.start_fraction*e['angle'], interval.end_fraction*e['angle']
        if hi == lo:
            contacts.append(dict(edge_index=e['index'], fraction=interval.start_fraction,
                                 column_ids=list(interval.column_ids)))
            continue
        unresolved = math.hypot(A, B) <= uncertainty
        cuts = [lo]+([] if unresolved else [s for s in _opening_breaks(A, B, e['angle']) if lo < s < hi])+[hi]
        for s, t in zip(cuts, cuts[1:]):
            mid = .5*(s+t)
            opening = A*math.cos(mid)+B*math.sin(mid)
            regime = ('stationary' if np.array_equal(lw, rw) else 'normal-motion-unresolved') if unresolved else (
                'incipient-extension' if opening > 0 else 'incipient-shortening')
            low, high = _opening_range(A, B, s, t)
            position = e['a']*math.cos(mid)+e['u']*math.sin(mid)
            direction = np.cross(delta, position)*atlas.sphere.radius_m
            segments.append(dict(edge_index=e['index'], start_fraction=s/e['angle'], end_fraction=t/e['angle'],
                left_plate=e['left'], right_plate=e['right'], column_ids=list(interval.column_ids),
                crust_types=sorted({columns[c].crust_type for c in interval.column_ids}),
                regime=regime, opening_midpoint_m_s=opening, opening_range_m_s=[low, high],
                opening_roundoff_m_s=uncertainty,
                tangential_m_s=shear, position=position.tolist(), relative_velocity_m_s=direction.tolist(),
                polarity=None))
        if len(interval.column_ids) == 1 and columns[interval.column_ids[0]].crust_type == 'continental':
            continental_integral += _speed_integral(delta,e['a'],e['u'],lo,hi)
            continental_angle += hi-lo
    continental_rms = None if continental_angle == 0 else (
        atlas.sphere.radius_m*math.sqrt(continental_integral/continental_angle))
    return segments, contacts, continental_rms


def generate_motion(plan, candidate, structure, *, cancel=None):
    started = time.perf_counter()
    plan = validate_plan(plan)
    from new_world_project import _check_pair
    from new_world_structure import check_structure
    from new_world_arcs import crust_intervals
    from atlas_tectonics.plate_layout import evaluate_plate_kinematics
    from atlas_tectonics.resources import WorkBudget, MemoryLimitError
    from atlas_tectonics.reuse import ExecutionContext
    from atlas_tectonics.stokes_execution import _native_lease
    atlas = candidate.atlas
    if atlas is None:
        _fail('An admitted native layout candidate is required.')
    _check_pair(plan, candidate.report, atlas)
    check_structure(plan, structure, current=True)
    if (atlas.sphere.frame_id != structure.state.case.topology.frame_id
            or atlas.sphere.radius_m != structure.state.case.topology.sphere.radius_m):
        _fail('Motion and geological frame or radius disagree.')
    binding = _source_binding()
    budget = WorkBudget(plan['request']['resources']['max_work_bytes'])

    def check():
        if cancel is not None:
            from atlas_tectonics.geometry import _check_cancel
            _check_cancel(cancel)
        if time.perf_counter()-started >= plan['request']['resources']['max_wall_seconds']:
            raise ContractError('TIME_LIMIT', 'Initial-motion time budget expired.')

    # Bounded polynomial work, no dense spatial raster or pairwise plate samples.
    n, ne, nv = 3*len(atlas.plate_ids), len(atlas.interplate_edges), len(atlas.vertex_ids)
    workspace = (8 << 20)+8*(32*n*n+8*n*nv)+24576*ne
    try:
        with budget.reserve(workspace, category='initial-motion-adapter'), ExecutionContext() as context:
            check()
            try:
                intervals = crust_intervals(atlas, structure, budget=budget, cancel=cancel)
            except ContractError as exc:
                if exc.code == 'ARC_GEOMETRY_REFUSED':
                    _fail(str(exc))
                raise
            check()
            with _native_lease():
                plates, anchor, omega, edges, junctions, diagnostics = _reconcile(atlas, intervals,
                    {c.column_id:c.crust_type for c in structure.state.case.columns}, plan['streams']['plate_motion'])
            check()
            angular = {p:omega[i].tolist() for i,p in enumerate(plates)}
            native = evaluate_plate_kinematics(atlas, angular, budget=budget, cancel=cancel)
            segments, contacts, continental_rms = _segments(atlas, structure, intervals, plates, omega, edges, check)
            diagnostics['continental_boundary_rms_m_s'] = continental_rms
            diagnostics['own_area_rate_sr_s'] = native['own_area_rate_sr_s']
            if max(map(abs, native['own_area_rate_sr_s'].values()), default=0.) > 1e-9*max(
                    float(abs(x)) for x in omega.ravel()):
                _fail('Rigid plate area-flux closure failed.')
            diagnostics['accounted_workspace_peak_bytes'] = budget.peak_reserved_bytes
            case = structure.state.case
            record = dict(schema=METHOD, status='WORKING NON-CANON',
                scientific_status='INITIAL_KINEMATIC_CANDIDATE',
                plan_id=plan['plan_id'], atlas_id=atlas.atlas_id, geometry_id=atlas.geometry_id,
                structure_id=structure.structure_id, state_id=structure.state.state_id,
                frame_id=atlas.sphere.frame_id, epoch_id=case.epoch_id, time_s=case.time_s,
                binding=binding, execution_id=context.identity, seed=plan['streams']['plate_motion'],
                rotation_frame=dict(kind='anchored-plate', anchor_plate_id=anchor, positive_time='forward'),
                angular_velocities_rad_s=angular, segments=segments, crust_contacts=contacts,
                junctions=junctions, diagnostics=diagnostics,
                event=dict(kind='symmetric-incipient-reorganisation', onset_time_s=case.time_s,
                    elapsed_time_s=0., new_crust_volume_m3=0., polarity=None,
                    column_age_context=structure.report['columns']),
                inherited_zones=[dict(zone_id=z.zone_id, active=False, strength_factor=z.strength_factor,
                    reason=z.unknown_reason) for z in case.weak_zones],
                assumptions=[
                    'Largest plate is fixed; this is not a no-net-rotation frame.',
                    'Euler proposals fitted modulo a common rotation; the anchor only selects the display frame.',
                    'Continental-affinity prior and junction constraints reconcile relative Euler proposals.',
                    'Continental affinity is a dimensionless scenario preference, not calibrated rock strength.',
                    'Boundary normal motion is the half-sum of adjacent plate normal velocities.',
                    'Junction compatibility is instantaneous first order, not finite-time stability.',
                    'All deformation initiates now; inherited crust ages are unchanged.',
                    'Near-roundoff normal motion is unresolved, not a physical transform classification.',
                    'No slab, mature ridge, polarity, active inherited fault or geological acceptance inferred.'],
                references=list(REFERENCES))
            if _source_binding() != binding:
                raise ContractError('SOURCE_MISMATCH', 'Initial-motion dependencies changed.')
            context.verify(); check()
            result = WorldMotion(_encode(record))
            check_motion(plan, atlas, structure, result)
            return result
    except MemoryLimitError as exc:
        raise ContractError('MEMORY_LIMIT', 'Initial motion exceeds the requested work budget.') from exc


def check_motion(plan, atlas, structure, motion, *, current=False):
    """Validate saved dependency edges; restoration does not rerun a generator."""
    if type(motion) is not WorldMotion or structure is None:
        _fail('An initial motion and its geological state are required.')
    r = motion.descriptor()
    if (r.get('plan_id') != plan['plan_id'] or r.get('atlas_id') != atlas.atlas_id
            or r.get('geometry_id') != atlas.geometry_id or r.get('structure_id') != structure.structure_id
            or r.get('state_id') != structure.state.state_id or r.get('frame_id') != atlas.sphere.frame_id
            or r.get('epoch_id') != structure.state.case.epoch_id or r.get('time_s') != structure.state.case.time_s
            or r.get('status') != 'WORKING NON-CANON' or r.get('scientific_status') != 'INITIAL_KINEMATIC_CANDIDATE'
            or set(r.get('angular_velocities_rad_s', {})) != set(atlas.plate_ids)):
        _fail('Motion, layout, geology and configuration disagree.')
    _check_saved_records(atlas, structure, r)
    if current:
        from atlas_tectonics.reuse import ExecutionContext
        if r['binding'] != _source_binding():
            raise ContractError('SOURCE_MISMATCH', 'Initial-motion source changed; no silent rebind.')
        with ExecutionContext() as context:
            if r['execution_id'] != context.identity:
                raise ContractError('SOURCE_MISMATCH', 'Native initial-motion runtime/source changed.')
            context.verify()


def _check_saved_records(atlas, structure, record):
    """Cheap retained-record admission, not a repeated motion solve."""
    import numpy as np
    try:
        angular = record['angular_velocities_rad_s']
        for vector in angular.values():
            if type(vector) is not list or len(vector) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
                _fail('Saved plate rotations are invalid.')
        frame = record['rotation_frame']
        if (frame['kind'] != 'anchored-plate' or frame['positive_time'] != 'forward'
                or angular[frame['anchor_plate_id']] != [0.,0.,0.]):
            _fail('Saved rotation-frame contract is invalid.')
        event = record['event']
        if (event['kind'] != 'symmetric-incipient-reorganisation' or event['onset_time_s'] != record['time_s']
                or event['elapsed_time_s'] != 0. or event['new_crust_volume_m3'] != 0. or event['polarity'] is not None
                or event['column_age_context'] != structure.report['columns']):
            _fail('Saved motion must preserve the incipient event and original ages.')
        segments, edge_ids = record['segments'], set(atlas.interplate_edges)
        if type(segments) is not list or not 0 < len(segments) <= 256*len(edge_ids):
            _fail('Invalid saved boundary-motion count.')
        columns = {c.column_id for c in structure.state.case.columns}
        spans = {}
        for s in segments:
            index = s['edge_index']
            lo, hi = s['start_fraction'], s['end_fraction']
            if (type(index) is not int or index not in edge_ids or not 0 <= lo < hi <= 1
                    or not s['column_ids'] or not set(s['column_ids']) <= columns or s['polarity'] is not None):
                _fail('Saved boundary-motion interval is invalid.')
            edge = atlas.edge(index)
            if (s['left_plate'],s['right_plate']) != (edge.left_plate_id,edge.right_plate_id):
                _fail('Saved boundary owners disagree with the native atlas.')
            p = np.asarray(s['position'], dtype=float)
            v = np.asarray(s['relative_velocity_m_s'], dtype=float)
            if p.shape != (3,) or v.shape != (3,) or not np.isfinite(p).all() or not np.isfinite(v).all():
                _fail('Saved boundary vectors are invalid.')
            a,b = atlas.vertex_directions[atlas.edge_vertices[index]]
            u,left,angle = _arc(a,b)
            mid = .5*(lo+hi)*angle
            expected = a*math.cos(mid)+u*math.sin(mid)
            delta = np.subtract(angular[s['right_plate']], angular[s['left_plate']])
            if (not np.allclose(p,expected,rtol=0.,atol=2e-12)
                    or not np.allclose(v,np.cross(delta,expected)*atlas.sphere.radius_m,rtol=1e-11,atol=1e-24)):
                _fail('Saved boundary vectors disagree with the plate rotations.')
            spans.setdefault(index, []).append((lo,hi))
        if set(spans) != edge_ids:
            _fail('Saved motion omits native interplate edges.')
        for values in spans.values():
            values.sort()
            if (values[0][0] != 0. or values[-1][1] != 1.
                    or any(abs(a[1]-b[0]) > 2e-14 for a,b in zip(values,values[1:]))):
                _fail('Saved motion intervals leave gaps or overlaps.')
        if any(z['active'] for z in record['inherited_zones']):
            _fail('Unknown-strength inherited structures cannot be activated by this recipe.')
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        if isinstance(exc, ContractError):
            raise
        _fail('Saved initial-motion records are malformed.')


def save_motion(motion, store):
    import numpy as np
    store.put(motion.motion_id, {'record':np.frombuffer(motion.payload, dtype='u1')}, {'schema':METHOD})
    return motion.motion_id


def load_motion(store, motion_id):
    import numpy as np
    arrays, metadata = store.get(motion_id), store.metadata(motion_id)
    if (type(arrays) is not dict or set(arrays) != {'record'} or metadata != {'schema':METHOD}
            or arrays['record'].dtype != np.dtype('u1') or arrays['record'].ndim != 1
            or arrays['record'].nbytes > MAX_RECORD):
        _fail('Missing or invalid saved initial-motion record.')
    motion = WorldMotion(arrays['record'].tobytes())
    if motion.motion_id != motion_id:
        _fail('Saved initial-motion identity mismatch.')
    return motion


def motion_view(motion):
    r = motion.descriptor()
    return dict(schema='atlas.initial-motion-view.v1', motion_id=motion.motion_id,
        **{k:r[k] for k in ('status', 'scientific_status', 'frame_id', 'epoch_id', 'time_s', 'rotation_frame',
            'angular_velocities_rad_s', 'segments', 'crust_contacts', 'junctions', 'diagnostics', 'event',
            'inherited_zones', 'assumptions', 'references')})
