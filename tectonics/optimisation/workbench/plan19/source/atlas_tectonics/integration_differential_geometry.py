"""Certified differential rigid-plate ownership and physical wall measures.

This is geometry, not an I03 material advance.  Actual material moves with its
own plate; ridge, overriding and transform-carrier boundaries have separate
trajectories.  Named vertices and an orientation-certified spherical fan give
the instantaneous ownership partition.  A material patch is clipped by that
partition, never replaced by the moving sampling face's average inventory.

The first supported family has exactly coaxial angular velocities (arbitrary
axis, including tilted axes), rigid boundary paths, and no topology events.
The restriction preserves the existing I03 finite ridge rule exactly in the
mathematical rotation group.  Noncommuting paths are not silently averaged.
All curved/time measurement error is enclosed and caller-budgeted.  No stock,
constitutive field, source reservoir or native velocity is changed here.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
from fractions import Fraction as Q
import hashlib
import heapq
import json
import math
import weakref
import live_spatial_patch as LIVE_SPATIAL
import live_finite_patch as LIVE_FINITE
from itertools import product
from contextlib import ExitStack, nullcontext

import numpy as np

from . import integration_sphere as S
from . import integration_transfer as T
from . import integration_volume as V
from . import integration_volume_overlap as O
from . import integration_volume_bounds as B
from . import integration_sphere_quadrature as SQ
from .integration_cone_intervals import _cone_cross_bounds, _cone_dot_bounds
from . import integration_wall_measures as W
from .geometry import _limits
from .resources import WorkBudget, MemoryLimitError


SCHEMA = 'atlas.differential-physical-geometry.v1'
MEASURE_SCHEMA = 'atlas.differential-physical-wall.v1'


def _encoded(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _restore_scratch(*records):
    """Peak codec work, not another reservation of caller-owned parsed graphs.

    Restore hashes/encodes one body or support at a time. Four times its input
    width covers the canonical ASCII string/bytes, encoder pieces and sorting
    work (including JSON escaping); descriptors' other parsed supports remain
    the caller's live input, not eight new object graphs created here.
    """
    from .integration_regional_inventory import _width
    return 65536+4*max((_width(r) for r in records), default=0)


def _record_hash(record):
    """Canonical identity without retaining a second full encoded record."""
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), allow_nan=False)
    for chunk in encoder.iterencode(record):
        digest.update(chunk.encode())
    return digest.hexdigest()


def _vec(value):
    if type(value) not in (tuple, list) or len(value) != 3:
        raise V.VolumeError('an explicit finite three-vector is required')
    return tuple(W._q(v) for v in value)


def _store_vec(value):
    return [V._encoded(v) for v in value]


def _load_vec(value):
    return tuple(W._decode(v) for v in value)


def _scale_ray(value):
    value = _vec(value)
    scale = max(map(abs, value))
    if not scale:
        raise V.VolumeError('zero spherical ray')
    return tuple(v/scale for v in value)


def _issue(cls, record, budget, endpoint=None):
    encoded = _encoded(record)
    # The issued object retains ONE immutable byte buffer, not four decoded
    # copies. Codec/input work belongs to the issuing operation; fixed capacity
    # covers the small handle, byte header, finalizer and reservation metadata.
    lease = budget.reserve(8192+len(encoded), category='differential-geometry-retained')
    lease.__enter__()
    try:
        result = object.__new__(cls)
        object.__setattr__(result, '_json', encoded)
        object.__setattr__(result, '_resource', budget)
        if cls is DifferentialInterval:
            object.__setattr__(result, '_endpoint', endpoint)
        weakref.finalize(result, lease.__exit__, None, None, None)
        return result
    except BaseException:
        lease.__exit__(None, None, None)
        raise


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class DifferentialInterval:
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)
    _endpoint: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('DifferentialInterval is issued by prepare_differential_interval')

    @property
    def interval_id(self):
        return hashlib.sha256(self._json).hexdigest()

    @property
    def endpoint_network(self):
        """Validated I03 GEOMETRY ONLY; no stale source material accompanies it."""
        return self._endpoint

    def record(self):
        return json.loads(self._json)

    def descriptor(self):
        return dict(interval_id=self.interval_id, **self.record())

    @classmethod
    def restore(cls, record, endpoint_network, *, budget):
        """Restore trusted source-bound CAS evidence, without advancing motion.

        The endpoint is separately restored by S.restore_network, including its
        original arrays/topology checks. This is not an authoring/certification
        route for arbitrary JSON: the workflow's immutable CAS/source binding
        authenticates the retained interval and endpoint bytes.
        """
        if type(record) is not dict or type(endpoint_network) is not S.SphereNetwork or type(budget) is not WorkBudget:
            raise V.VolumeError('retained interval, restored typed endpoint and caller budget required')
        with budget.reserve(_restore_scratch(record), category='differential-interval-restore'):
            identity = record.get('interval_id')
            body = {k: v for k, v in record.items() if k != 'interval_id'}
            if (body.get('schema') != SCHEMA or body.get('method') != 'coaxial-physical-ownership-fan-v1' or
                    body.get('geometry_only') is not True or type(identity) is not str or
                    _record_hash(body) != identity):
                raise V.VolumeError('stored differential geometry identity/method differs')
            segments = body.get('trajectory', {}).get('segments')
            if (type(segments) is not list or not segments or W._hash(segments) != body.get('trajectory_id') or
                    W._hash(segments[:-1]) != body.get('prior_trajectory_id') or
                    body.get('endpoint_network_id') != endpoint_network.network_id or
                    W._decode(body['end_time_s']) != Q(endpoint_network.time_s) or
                    W._decode(body['radius_m']) != Q(endpoint_network.sphere.radius_m)):
                raise V.VolumeError('stored differential endpoint or trajectory prefix differs')
            epoch = segments[0]['parent_network_id']
            if (body.get('start_support_id') != W._hash(dict(epoch_network_id=epoch, segments=segments[:-1])) or
                    body.get('end_support_id') != W._hash(dict(epoch_network_id=epoch, segments=segments))):
                raise V.VolumeError('stored physical support identity differs')
            return _issue(cls, body, budget, endpoint_network)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class DifferentialMeasure:
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('DifferentialMeasure is issued by a differential physical query')

    @property
    def measure_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return json.loads(self._json)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class DifferentialBoundaryPose:
    """One actual rigid boundary pose, not an averaged global material pose."""
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('boundary poses are issued by posed_boundary')

    @property
    def pose_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return json.loads(self._json)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class DifferentialSupport:
    """Issued convex angular components, not unlocated or surrogate stock."""
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)
    _compact_ref: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('DifferentialSupport is issued by partition_physical_support')

    @property
    def support_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return json.loads(self._json)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class CurrentGeometry:
    """One instantaneous owned geometry; declares NO material velocity."""
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('CurrentGeometry is issued by prepare_current_geometry')

    @property
    def geometry_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return json.loads(self._json)

    def descriptor(self):
        return dict(geometry_id=self.geometry_id, **self.record())

    @classmethod
    def restore(cls, record, *, budget):
        """Restore immutable CAS geometry, not arbitrary new physical authoring."""
        if type(record) is not dict or type(budget) is not WorkBudget:
            raise V.VolumeError('complete retained current geometry and caller budget required')
        with budget.reserve(_restore_scratch(record), category='differential-current-restore'):
            body = {k: v for k, v in record.items() if k != 'geometry_id'}
            if (body.get('schema') != 'atlas.differential-current-geometry.v1' or
                    _record_hash(body) != record.get('geometry_id') or
                    body.get('start_time_s') != body.get('time_s') or body.get('end_time_s') != body.get('time_s') or
                    W._decode(body['duration_s']) != 0 or
                    any(any(_load_vec(r['angular_velocity_rad_s'])) for r in body['rays'].values())):
                raise V.VolumeError('retained current geometry identity or instantaneous semantics differ')
            return _issue(cls, body, budget)


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class DifferentialPartition:
    """Complete source-owned spatial partition and its exact native contacts.

    Individual DifferentialSupports do not assert coverage. This issuer binds
    their disjoint source charts, complete owner/layer coverage and the aligned
    Cartesian subdivision. No stock or constitutive field is reconstructed.
    """
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)
    _supports: tuple = field(repr=False, compare=False)
    _compact: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('DifferentialPartition is issued by prepare_differential_partition')

    @property
    def partition_id(self):
        compact = getattr(self, '_compact', None)
        return compact.partition_id if compact is not None else hashlib.sha256(self._json).hexdigest()

    @property
    def supports(self):
        return self._supports

    def record(self):
        if getattr(self, '_compact', None) is not None:
            raise V.VolumeError('compact partition requires indexed access or owned legacy_record export')
        return json.loads(self._json)

    def compact_view(self):
        from partition_native_patch import compact_view
        return compact_view(self)

    def legacy_record(self):
        from partition_native_patch import partition_fields
        compact = self.compact_view()
        return partition_fields(self, ()) if compact is None else compact.legacy_record()

    @classmethod
    def from_compact(cls, view, funding, collar, geometry, *, budget, _runtime_transfer=None):
        from partition_native_patch import admit_partition
        return admit_partition(cls, view, funding, collar, geometry, budget=budget, _runtime_transfer=_runtime_transfer)

    def descriptor(self):
        return dict(partition_id=self.partition_id, **self.record(),
                    supports=[s.record() for s in self.supports])

    @classmethod
    def restore(cls, record, funding, collar, geometry, *, budget, _runtime_transfer=None):
        """Restore source-bound CAS evidence; no geometry is re-integrated."""
        if type(record) is not dict or type(budget) is not WorkBudget:
            raise V.VolumeError('complete retained partition record and caller budget required')
        # The shallow header and support tuple contain references only. The
        # caller retains ownership/accounting of its decoded descriptor. Each
        # canonical support is issued sequentially and charged by _issue.
        raw_supports = record.get('supports')
        if type(raw_supports) is not list:
            raise V.VolumeError('retained partition support inventory required')
        with budget.reserve(128+64*len(record)+16*len(raw_supports),
                            category='differential-partition-restore-containers'):
            identity = record.get('partition_id')
            body = {k: v for k, v in record.items() if k not in ('partition_id', 'supports')}
            with budget.reserve(_restore_scratch(body, *raw_supports), category='differential-partition-restore-codec'):
                if (body.get('schema') != 'atlas.differential-partition.v1' or
                        _record_hash(body) != identity or
                        [_record_hash(r) for r in raw_supports] != body.get('support_ids') or
                        body.get('funding_id') != funding.funding_id or not _transferred_collar_binding(body, funding, collar, budget, _runtime_transfer) or
                        body.get('source') != funding.descriptor()['source'] or
                        any(b is not budget for b in (funding._resource, collar._budget, geometry._resource))):
                    raise V.VolumeError('retained partition source, geometry inventory or identity differs')
                if body['scope'] == 'initial-current':
                    valid = type(geometry) is CurrentGeometry and body['current_geometry_id'] == geometry.geometry_id
                else:
                    valid = type(geometry) is DifferentialInterval and body['interval_id'] == geometry.interval_id
                if not valid:
                    raise V.VolumeError('retained partition belongs to a different actual geometry')
                supports = tuple(_issue(DifferentialSupport, r, budget) for r in raw_supports)
                result = _issue(cls, body, budget)
                object.__setattr__(result, '_supports', supports)
                return result


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class DifferentialInitialBounds:
    """Measured initial material geometry, before any future force or motion."""
    _json: bytes = field(repr=False)
    _resource: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('DifferentialInitialBounds is issued by enclose_initial_partition')

    @property
    def bounds_id(self):
        return hashlib.sha256(self._json).hexdigest()

    def record(self):
        return json.loads(self._json)


def prepare_current_geometry(network, *, budget):
    """Initial/current geometry for the force lift before angular velocity exists.

    No future Motion, future clock or guessed zero physical rate is created.
    Zero in a ray's evaluator denotes fixed evaluation of THIS pose only.
    """
    if type(network) is not S.SphereNetwork or not isinstance(budget, WorkBudget):
        raise V.VolumeError('issued current network and shared explicit budget required')
    points = {name: _scale_ray(tuple(float(q) for q in point))
              for name, point in zip(network.vertex_ids, network.vertex_direction)}
    rays = {'vertex:'+name: (point, (Q(0),)*3) for name, point in points.items()}
    fans = []
    with B._Arena(budget) as arena:
        for face in network.faces:
            if face.holes:
                raise V.VolumeError('current ownership with holes needs a conforming decomposition')
            ring = tuple(points[name] for name in face.vertex_ids)
            centre_id = 'face-centre:'+face.face_id
            rays[centre_id] = _scale_ray(tuple(sum(p[j] for p in ring) for j in range(3))), (Q(0),)*3
            for a, b in zip(face.vertex_ids, face.vertex_ids[1:]+face.vertex_ids[:1]):
                triangle = (centre_id, 'vertex:'+a, 'vertex:'+b)
                if not _orientation(triangle, rays, Q(0), Q(0), 0, arena):
                    raise V.VolumeError('current face needs a non-star-shaped exact ownership decomposition')
                fans.append(dict(face_id=face.face_id, plate_id=face.plate_id, ray_ids=triangle))
        record = dict(schema='atlas.differential-current-geometry.v1', network_id=network.network_id,
            sphere=network.sphere.descriptor(), time_s=_qtext(Q(network.time_s)),
            start_time_s=_qtext(Q(network.time_s)), end_time_s=_qtext(Q(network.time_s)),
            duration_s=_qtext(Q(0)), radius_m=_qtext(Q(network.sphere.radius_m)),
            plate_ids=list(network.plate_ids), rays={key: dict(direction=_store_vec(p),
                angular_velocity_rad_s=_store_vec(w)) for key, (p, w) in sorted(rays.items())},
            ownership_fans=fans, authority='instantaneous geometry only; no physical velocity or future interval')
    return _issue(CurrentGeometry, record, budget)


def current_geometry_from_interval(interval, *, budget):
    """Actual accepted endpoint with retained ray history and NO future rate.

    Sampling the rounded endpoint network anew would change the physical
    support. Instead, append the accepted current ray step to its exact symbolic
    prefix. A zero evaluator rate freezes that endpoint only; it is expressly
    not a declaration of future material velocity.
    """
    if type(interval) is not DifferentialInterval or interval._resource is not budget:
        raise V.VolumeError('actual accepted differential interval on the same budget required')
    row = interval.record()
    duration = W._decode(row['duration_s'])
    rays = {}
    for key, ray in row['rays'].items():
        history = _history(ray.get('prior_rotations', ()))+((_load_vec(ray['angular_velocity_rad_s']), duration),)
        rays[key] = dict(direction=ray['direction'], angular_velocity_rad_s=_store_vec((Q(0),)*3),
                         prior_rotations=_history_record(history))
    boundaries = []
    for boundary in row['boundary_paths']:
        history = _history(boundary.get('prior_rotations', ()))+(
            (_load_vec(boundary['angular_velocity_rad_s']), duration),)
        boundaries.append(dict(boundary, prior_rotations=_history_record(history),
                               angular_velocity_rad_s=_store_vec((Q(0),)*3)))
    result = dict(schema='atlas.differential-current-geometry.v1', network_id=row['endpoint_network_id'],
        sphere=interval.endpoint_network.sphere.descriptor(), time_s=row['end_time_s'],
        start_time_s=row['end_time_s'], end_time_s=row['end_time_s'], duration_s=_qtext(Q(0)),
        radius_m=row['radius_m'], plate_ids=list(row['plate_angular_velocity_rad_s']), rays=rays,
        ownership_fans=row['ownership_fans'], accepted_interval_id=interval.interval_id,
        accepted_support_id=row['end_support_id'], accepted_trajectory_id=row['trajectory_id'],
        trajectory=row['trajectory'], boundary_paths=boundaries,
        authority='accepted physical ray prefix only; no future material velocity or resampling')
    return _issue(CurrentGeometry, result, budget)


def _product(first, second):
    values = tuple(a*b for a in first for b in second)
    return min(values), max(values)


def _sum(values):
    values = tuple(values)
    return sum(v[0] for v in values), sum(v[1] for v in values)


def _minus(first, second):
    return first[0]-second[1], first[1]-second[0]


def _cross_bounds(a, b):
    return tuple(_minus(_product(a[(j+1) % 3], b[(j+2) % 3]),
                        _product(a[(j+2) % 3], b[(j+1) % 3])) for j in range(3))


def _dot_bounds(a, b):
    return _sum(_product(x, y) for x, y in zip(a, b))


def _history(value):
    return tuple((_load_vec(row['angular_velocity_rad_s']), W._decode(row['duration_s'])) for row in value)


def _history_record(value):
    return [dict(angular_velocity_rad_s=_store_vec(w), duration_s=_qtext(dt)) for w, dt in value]


def _ray_parts(value):
    return value[0], value[1], value[2] if len(value) > 2 else ()


class _ComponentRayCache:
    """Bounded exact-input poses retained only by one component-query arena."""
    MAX_ENTRIES = 256
    MAX_BYTES = 2 << 20

    def __init__(self, arena):
        self.owner, self.values, self.retained_bytes = arena, {}, 2048
        # Fixed 64-bit metadata inside the existing 2048-byte allowance.
        # No operands/proof graph; levels >= 64 always recompute.
        self.declined_cone_levels = 0
        # Two bits only, within existing 2048-byte query metadata.
        self.impossible_pair_families = 0
        # At most129 bits, inside the original2048-byte metadata.
        self.split_axis_bits = 0
        self.stack = ExitStack()
        arena.stack.callback(self.close)
        self.stack.enter_context(arena.resource.reserve(2048, category='component-ray-cache'))

    def close(self):
        # Drop cached objects before returning their retained-capacity leases.
        self.values.clear()
        self.declined_cone_levels = 0
        # Two bits only, within existing 2048-byte query metadata.
        self.impossible_pair_families = 0
        # At most129 bits, inside the original2048-byte metadata.
        self.split_axis_bits = 0
        self.owner = None
        self.stack.close()

    def key(self, ray, omega, a, b, level, arena, prior):
        if self.owner is not arena:
            raise V.VolumeError('ray-pose cache belongs to another or closed query arena')
        return (tuple(ray), tuple(omega), a, b, level,
                tuple((tuple(w), duration) for w, duration in prior))

    def retain(self, key, answer):
        if len(self.values) >= self.MAX_ENTRIES:
            return
        ray, omega, a, b, level, prior = key
        point, error, boxes = answer
        values = (*ray, *omega, a, b, level,
                  *(v for w, duration in prior for v in (*w, duration)),
                  *point, error, *(v for pair in boxes for v in pair))
        size = (1024+128*len(values)+128*(12+3*len(prior))+
                4*sum((V._bits(v)+7)//8 for v in values))
        if size > self.MAX_BYTES-self.retained_bytes:
            return
        self.stack.enter_context(self.owner.resource.reserve(size, category='component-ray-cache'))
        self.values[key] = answer
        self.retained_bytes += size


def _ray_box(ray, omega, a, b, level, arena, prior=()):
    cache = getattr(arena, '_component_ray_cache', None)
    if cache is not None:
        key = cache.key(ray, omega, a, b, level, arena, prior)
        if key in cache.values:
            return cache.values[key]
    point, error = W._pose_vector(ray, omega, a, b, level, arena, prior)
    answer = point, error, tuple((v-error, v+error) for v in point)
    if cache is not None:
        cache.retain(key, answer)
    return answer


def _orientation(triangle, rays, a, b, level, arena):
    items = tuple(_ray_parts(rays[key]) for key in triangle)
    # A shared rigid rotation preserves the determinant and hemisphere exactly.
    if all((w, prior) == (items[0][1], items[0][2]) for _, w, prior in items):
        boxes = tuple(tuple((q, q) for q in ray) for ray, _, _ in items)
    else:
        boxes = tuple(_ray_box(ray, w, a, b, level, arena, prior)[2] for ray, w, prior in items)
    determinant = _dot_bounds(boxes[0], _cross_bounds(boxes[1], boxes[2]))[0]
    centre = tuple(_sum(box[j] for box in boxes) for j in range(3))
    hemisphere = min(_dot_bounds(box, centre)[0] for box in boxes)
    arena.work(256)
    return determinant > 0 and hemisphere > 0


def _pose_binding(rotation, omega, duration, arena):
    """Outward bound between true exponential and the stored I03 operator.

    This is tested against the existing I03 attachment band, not a new fitted
    tolerance.  It is retained separately from physical swept-volume bounds.
    """
    stored = rotation.apply(np.eye(3))
    error = Q(0)
    for j in range(3):
        axis = tuple(Q(k == j) for k in range(3))
        point, tail = W._pose_vector(axis, omega, duration, duration, 24, arena)
        error = max(error, sum(abs(q-Q(float(v))) for q, v in zip(point, stored[j]))+tail)
    if error > Q(S.ATTACHMENT_BAND_RAD):
        raise V.VolumeError('actual angular velocity does not represent the I03 endpoint within its unchanged attachment band')
    return error


def prepare_differential_interval(parent_network, motion, *, end_time_s,
                                  angular_velocity_by_plate_rad_s, max_leaves,
                                  budget, limits=None, prior_interval=None):
    """Issue the geometry-only coaxial successor and all-time ownership proof.

    `max_leaves` limits the common time partition used to prove positive fan
    orientation.  Exhaustion refuses; no event, gap, overlap or tiny face is
    discarded.  The original I03 endpoint validation is also required.
    """
    if type(parent_network) is not S.SphereNetwork or type(motion) is not T.Motion:
        raise V.VolumeError('issued parent network and typed Motion required')
    if not isinstance(budget, WorkBudget):
        raise V.VolumeError('the shared explicit WorkBudget is required')
    if type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('positive finite orientation subdivision limit required')
    if motion.start_step != parent_network.step:
        raise V.VolumeError('differential interval must start at the actual network step')
    if any((motion.mesh, motion.events, motion.regional_returns, motion.junction_paths, motion.history_splits)):
        raise V.VolumeError('this differential interval requires fixed topology and rigid boundary paths')
    start, end = W._q(parent_network.time_s), W._q(end_time_s)
    if end <= start or Q(float(end)) != end:
        raise V.VolumeError('the I03 endpoint needs an exactly represented forward binary64 time')
    duration = end-start
    if type(angular_velocity_by_plate_rad_s) is not dict or set(angular_velocity_by_plate_rad_s) != set(parent_network.plate_ids):
        raise V.VolumeError('actual angular velocity of every plate must be supplied explicitly')
    omegas = {p: _vec(angular_velocity_by_plate_rad_s[p]) for p in parent_network.plate_ids}
    if any(any(O._cross(a, b)) for a in omegas.values() for b in omegas.values()):
        raise V.VolumeError('noncommuting differential paths require the composed I03 ridge trajectory, never a mean rotation')
    prior_record = None
    if prior_interval is not None:
        if type(prior_interval) is not DifferentialInterval or prior_interval._resource is not budget:
            raise V.VolumeError('prior interval must be issued on the same budget')
        prior_record = prior_interval.record()
        if (prior_record['endpoint_network_id'] != parent_network.network_id or
                W._decode(prior_record['end_time_s']) != start):
            raise V.VolumeError('prior physical trajectory is not the actual current geometry parent')
        prior_vectors = [_load_vec(row['angular_velocity_rad_s']) for row in prior_record['rays'].values()]
        if any(any(O._cross(a, b)) for a in omegas.values() for b in prior_vectors):
            raise V.VolumeError('this chained differential family requires the same actual common axis, not a changed-pole approximation')
    limits = _limits(limits)
    moved = T._moved(parent_network, motion, None, limits, budget)
    endpoint = T._issued(parent_network, moved, float(end), motion.end_step, limits, budget, None)
    points = {name: _scale_ray(tuple(float(v) for v in point))
              for name, point in zip(parent_network.vertex_ids, parent_network.vertex_direction)}
    boundary_rows, boundary_omega, uses = [], {}, {}
    supplies = {(s.boundary_id, s.side): s.record() for s in motion.supplies}
    sinks = {s.boundary_id: s.record() for s in motion.sinks}
    stage = dict(motion.rotations)
    status = {name: (kind, q) for name, kind, q in moved.status}
    with B._Arena(budget) as arena:
        bindings = {p: _pose_binding(stage[p], omega, duration, arena) for p, omega in omegas.items()}
        for boundary in parent_network.boundaries:
            left, right = omegas[boundary.left_plate_id], omegas[boundary.right_plate_id]
            if boundary.kind == S.RIDGE:
                f = Q(boundary.accretion_fraction)
                w = tuple((1-f)*a+f*b for a, b in zip(left, right))
                rule = 'coaxial-existing-I03-relative-exponential-ridge'
            elif boundary.kind == S.TRENCH:
                w = right if boundary.subducting_side == 'left' else left
                rule = 'overriding-plate'
            elif left == right:
                w, rule = left, 'shared-plate-rotation'
            elif boundary.carrier_side is not None:
                w = left if boundary.carrier_side == 'left' else right
                rule = 'declared-transform-carrier'
            else:
                raise V.VolumeError('differential transform needs its original explicit carrier side')
            # `_moved` already validates the original C6 transform rule.
            from .kinematics import _restore_rotation
            binding = _pose_binding(_restore_rotation(status[boundary.boundary_id][1]), w, duration, arena)
            boundary_omega[boundary.boundary_id] = w
            for name in boundary.vertex_ids:
                uses.setdefault(name, []).append(w)
            boundary_rows.append(dict(boundary_id=boundary.boundary_id, kind=boundary.kind,
                left_plate_id=boundary.left_plate_id, right_plate_id=boundary.right_plate_id,
                subducting_side=boundary.subducting_side, carrier_side=boundary.carrier_side,
                vertex_ids=list(boundary.vertex_ids), closed=boundary.closed,
                angular_velocity_rad_s=_store_vec(w), rule=rule,
                endpoint_operator_error_bound=_qtext(binding),
                supplies={side: supplies[(boundary.boundary_id, side)] for side in S.SIDES
                          if (boundary.boundary_id, side) in supplies},
                sink=sinks.get(boundary.boundary_id)))
        owners = {}
        for face in parent_network.faces:
            for name in face.vertex_ids:
                owners.setdefault(name, set()).add(face.plate_id)
        rays = {}
        for name, point in points.items():
            candidates = uses.get(name, [omegas[next(iter(owners[name]))]])
            if all(w == candidates[0] for w in candidates):
                w = candidates[0]
            elif all(not any(O._cross(w, point)) for w in candidates):
                w = (Q(0),)*3   # exact stationary common-axis point, not a snapped junction
            else:
                raise V.VolumeError('junction needs a non-rigid intersection trajectory; endpoint agreement alone is not a path')
            rays['vertex:'+name] = point, w
        fans = []
        for face in parent_network.faces:
            if face.holes:
                raise V.VolumeError('differential ownership with holes needs an explicit conforming decomposition')
            ring = tuple(points[name] for name in face.vertex_ids)
            centre = _scale_ray(tuple(sum(p[j] for p in ring) for j in range(3)))
            centre_id = 'face-centre:'+face.face_id
            rays[centre_id] = centre, omegas[face.plate_id]
            for a, b in zip(face.vertex_ids, face.vertex_ids[1:]+face.vertex_ids[:1]):
                triangle = (centre_id, 'vertex:'+a, 'vertex:'+b)
                if not _orientation(triangle, rays, Q(0), Q(0), 24, arena):
                    raise V.VolumeError('original face needs a non-star-shaped exact ownership decomposition')
                fans.append(dict(face_id=face.face_id, plate_id=face.plate_id, ray_ids=triangle))
        if prior_record is not None:
            # Retain the physical fan, not the endpoint's newly sampled face
            # geometry. Its symbolic ray trajectories grow by one shared step.
            old_boundaries = {r['boundary_id']: r for r in prior_record['boundary_paths']}
            current_boundaries = {r['boundary_id']: r for r in boundary_rows}
            if set(old_boundaries) != set(current_boundaries):
                raise V.VolumeError('physical boundary topology changed outside this interval family')
            previous_duration = W._decode(prior_record['duration_s'])
            old_uses = {}
            for key, old in old_boundaries.items():
                current = current_boundaries[key]
                if any(old[k] != current[k] for k in ('kind', 'left_plate_id', 'right_plate_id', 'closed')):
                    raise V.VolumeError('physical boundary ownership changed outside this interval family')
                current['sampling_vertex_ids'] = current['vertex_ids']
                current['vertex_ids'] = old['vertex_ids']
                history = _history(old.get('prior_rotations', ()))+((_load_vec(old['angular_velocity_rad_s']), previous_duration),)
                current['prior_rotations'] = _history_record(history)
                for name in old['vertex_ids']:
                    old_uses.setdefault('vertex:'+name, []).append(boundary_omega[key])
            owner_of = {}
            for fan in prior_record['ownership_fans']:
                for name in fan['ray_ids']:
                    owner_of.setdefault(name, fan['plate_id'])
            rays = {}
            for name, old in prior_record['rays'].items():
                point = _load_vec(old['direction'])
                history = _history(old.get('prior_rotations', ()))+((_load_vec(old['angular_velocity_rad_s']), previous_duration),)
                candidates = old_uses.get(name, [omegas[owner_of[name]]])
                if all(w == candidates[0] for w in candidates):
                    w = candidates[0]
                elif all(not any(O._cross(w, point)) for w in (*candidates, *(w for w, _ in history))):
                    w = (Q(0),)*3
                else:
                    raise V.VolumeError('continued junction needs its actual non-rigid path, not endpoint retimestamping')
                rays[name] = point, w, history
            fans = prior_record['ownership_fans']
        todo, proved, leaves = [(Q(0), duration, 0)], [], 1
        while todo:
            a, b, level = todo.pop()
            if all(_orientation(fan['ray_ids'], rays, a, b, level, arena) for fan in fans):
                proved.append((a, b))
                continue
            if leaves >= max_leaves:
                raise V.VolumeError('all-time differential ownership orientation was not certified within the declared work bound')
            middle = (a+b)/2
            todo.extend(((a, middle, level+1), (middle, b, level+1)))
            leaves += 1
        record = dict(schema=SCHEMA, method='coaxial-physical-ownership-fan-v1',
            parent_network_id=parent_network.network_id, endpoint_network_id=endpoint.network_id,
            motion_id=motion.motion_id, motion=motion.record(), geometry_only=True,
            start_time_s=_qtext(start), end_time_s=_qtext(end), duration_s=_qtext(duration),
            radius_m=_qtext(Q(parent_network.sphere.radius_m)),
            plate_angular_velocity_rad_s={p: _store_vec(w) for p, w in omegas.items()},
            plate_endpoint_operator_error_bounds={p: _qtext(e) for p, e in bindings.items()},
            endpoint_binding_limit_rad=S.ATTACHMENT_BAND_RAD,
            boundary_paths=boundary_rows,
            rays={key: dict(direction=_store_vec(_ray_parts(value)[0]), angular_velocity_rad_s=_store_vec(_ray_parts(value)[1]),
                           prior_rotations=_history_record(_ray_parts(value)[2]))
                  for key, value in sorted(rays.items())}, ownership_fans=fans,
            certified_time_partition_s=[[_qtext(a), _qtext(b)] for a, b in sorted(proved)],
            orientation_max_leaves=max_leaves, orientation_work_units=arena.work_units,
            material_account_authority='none: current carried fields and finite reservoirs belong to the material owner')
        previous_segments = [] if prior_record is None else prior_record['trajectory']['segments']
        segment = dict(start_time_s=record['start_time_s'], end_time_s=record['end_time_s'],
            parent_network_id=record['parent_network_id'], endpoint_network_id=record['endpoint_network_id'],
            motion_id=motion.motion_id, plate_angular_velocity_rad_s=record['plate_angular_velocity_rad_s'],
            boundary_angular_velocity_rad_s={row['boundary_id']: row['angular_velocity_rad_s'] for row in boundary_rows})
        record['trajectory'] = dict(segments=previous_segments+[segment])
        record['trajectory_id'] = W._hash(record['trajectory']['segments'])
        record['prior_trajectory_id'] = W._hash(previous_segments)
        epoch = record['parent_network_id'] if prior_record is None else prior_record['trajectory']['segments'][0]['parent_network_id']
        record['start_support_id'] = W._hash(dict(epoch_network_id=epoch, segments=previous_segments))
        record['end_support_id'] = W._hash(dict(epoch_network_id=epoch, segments=record['trajectory']['segments']))
    return _issue(DifferentialInterval, record, budget, endpoint)


def _qtext(value):
    return V._encoded(value)


def posed_boundary(interval, boundary_id, *, endpoint, max_operator_error, budget):
    """Rational orthogonal representative of the actual accumulated boundary.

    Taylor quaternion remainders and orthogonal normalisation use the existing
    proved operator bound. The requested dimensionless error is explicit; no
    geometric/force acceptance constant is introduced here. Original radial
    side rays plus this ONE rigid pose support the established wall-strip
    enclosure, including a continued interval's complete prior trajectory.
    """
    from . import integration_exterior_mesh as E
    if type(interval) not in (DifferentialInterval, CurrentGeometry) or interval._resource is not budget:
        raise V.VolumeError('issued differential interval/current geometry on the same budget required')
    if endpoint not in ('start', 'end'):
        raise V.VolumeError('boundary pose endpoint must be explicit')
    goal = W._q(max_operator_error)
    if goal <= 0:
        raise V.VolumeError('positive explicit dimensionless operator error required')
    r = interval.record()
    static = type(interval) is CurrentGeometry
    boundary = next((b for b in r.get('boundary_paths', ()) if b['boundary_id'] == boundary_id), None)
    if boundary is None:
        raise V.VolumeError('actual interval boundary identity required')
    history = list(_history(boundary.get('prior_rotations', ())))
    if endpoint == 'end' and not static:
        history.append((_load_vec(boundary['angular_velocity_rad_s']), W._decode(r['duration_s'])))
    steps = [dict(angular_velocity_rad_s=_store_vec(w), start_time_s=_qtext(Q(0)), end_time_s=_qtext(dt))
             for w, dt in history if dt and any(w)]
    with B._Arena(budget) as arena:
        quaternion, error = E._representative_pose(steps, goal, arena)
        basis = V.CartesianCell((0, 0, 0), (1, 1, 1), budget=budget).rotated(quaternion, budget=budget).basis
        chain = boundary['vertex_ids']
        if boundary['closed']:
            chain = chain+[chain[0]]
        original = {name: r['rays']['vertex:'+name]['direction'] for name in chain}
        result = dict(schema='atlas.differential-boundary-pose.v1',
            interval_id=r.get('accepted_interval_id') if static else interval.interval_id,
            boundary_id=boundary_id, boundary_kind=boundary['kind'], endpoint=endpoint,
            time_s=r[endpoint+'_time_s'], radius_m=r['radius_m'],
            left_plate_id=boundary['left_plate_id'], right_plate_id=boundary['right_plate_id'],
            subducting_side=boundary['subducting_side'], carrier_side=boundary['carrier_side'],
            trajectory_id=r['accepted_trajectory_id'] if static else r['trajectory_id' if endpoint == 'end' else 'prior_trajectory_id'],
            support_id=r['accepted_support_id'] if static else r[endpoint+'_support_id'], original_rays=original,
            segments=[dict(vertex_ids=[a, b], original_rays=[original[a], original[b]]) for a, b in zip(chain, chain[1:])],
            boundary_rotations=steps, representative_quaternion=_store_vec(quaternion[1:]),
            representative_quaternion_scalar=_qtext(quaternion[0]),
            rotation_matrix=[_store_vec(row) for row in basis],
            pose_operator_error_bound=_qtext(error), requested_operator_error=_qtext(goal),
            rule='actual boundary history only; source material uses its own plate trajectory', work_units=arena.work_units)
        # Keep the familiar complete quaternion key used by existing geometry
        # consumers; no rounded ENU frame or nonorthogonal matrix is introduced.
        result['representative_quaternion'] = list(map(_qtext, quaternion))
        result.pop('representative_quaternion_scalar')
        if static:
            result['current_geometry_id'] = interval.geometry_id
            result['network_id'] = r['network_id']
    return _issue(DifferentialBoundaryPose, result, budget)


def _multiply(first, second):
    out = {}
    for (i, j), a in first.items():
        for (k, l), b in second.items():
            key = i+k, j+l
            out[key] = out.get(key, Q(0))+a*b
    return out


def _polynomials(declarations):
    out = []
    for terms in declarations:
        if type(terms) not in (tuple, list):
            raise V.VolumeError('moment polynomial is an explicit sequence of (u_power,v_power,coefficient)')
        polynomial = {}
        for term in terms:
            if type(term) not in (tuple, list) or len(term) != 3:
                raise V.VolumeError('invalid moment polynomial term')
            i, j, value = term
            if type(i) is not int or type(j) is not int or not 0 <= i <= 4 or not 0 <= j <= 4:
                raise V.VolumeError('moment exponents must be integers in 0..4 per face coordinate')
            polynomial[i, j] = polynomial.get((i, j), Q(0))+W._q(value)
        out.append({key: value for key, value in polynomial.items() if value})
    return tuple(out)


def _polynomial_integral(poly, polynomial, arena):
    """Exact monomial integration; s^i t^j on a unit triangle is i!j!/(i+j+2)!."""
    if not poly or not polynomial:
        return Q(0)
    total, a = Q(0), poly[0]
    for b, c in zip(poly[1:-1], poly[2:]):
        determinant = (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        if determinant < 0:
            raise V.VolumeError('moment polygon orientation changed')
        up = {(0, 0): a[0], (1, 0): b[0]-a[0], (0, 1): c[0]-a[0]}
        vp = {(0, 0): a[1], (1, 0): b[1]-a[1], (0, 1): c[1]-a[1]}
        powers_u, powers_v = [{(0, 0): Q(1)}], [{(0, 0): Q(1)}]
        for _ in range(4):
            powers_u.append(_multiply(powers_u[-1], up))
            powers_v.append(_multiply(powers_v[-1], vp))
        for (i, j), coefficient in polynomial.items():
            terms = _multiply(powers_u[i], powers_v[j])
            total += determinant*coefficient*sum(value*Q(math.factorial(k)*math.factorial(l), math.factorial(k+l+2))
                                               for (k, l), value in terms.items())
            arena.work(16+16*len(terms))
    return total


def _power_bounds(pair, exponent):
    if not exponent:
        return Q(1), Q(1)
    a, b = pair
    values = (a**exponent, b**exponent)
    return (Q(0) if exponent % 2 == 0 and a <= 0 <= b else min(values), max(values))


def _polynomial_range(polynomial, bounds):
    terms = []
    for (i, j), value in polynomial.items():
        pair = _product(_power_bounds(bounds[0], i), _power_bounds(bounds[1], j))
        terms.append(tuple(value*q for q in pair) if value >= 0 else tuple(value*q for q in reversed(pair)))
    return _sum(terms)


def _bernstein_hull(polynomial, bounds):
    """Exact tensor Bernstein coefficient range of a polynomial on a rectangle.

    A polynomial lies in the convex hull of its Bernstein coefficients, so
    their extremes enclose its range. Unlike the termwise sum above, the hull
    keeps the cancellation between monomials: beside a zero curve of a native
    normal trace the termwise range has the size of one coefficient times the
    rectangle, while the hull has the size of the trace itself.
    """
    (a, b), (c, d) = bounds
    degree = (max((i for i, _ in polynomial), default=0), max((j for _, j in polynomial), default=0))
    unit = {}
    for (i, j), value in polynomial.items():
        for k in range(i+1):
            for l in range(j+1):
                unit[k, l] = unit.get((k, l), Q(0))+value*math.comb(i, k)*a**(i-k)*(b-a)**k*math.comb(j, l)*c**(j-l)*(d-c)**l
    coefficients = [sum((value*Q(math.comb(k, i), math.comb(degree[0], i))*Q(math.comb(l, j), math.comb(degree[1], j))
                         for (i, j), value in unit.items() if i <= k and j <= l), Q(0))
                    for k in range(degree[0]+1) for l in range(degree[1]+1)]
    return min(coefficients), max(coefficients)


def _unpack(interval, plate_id, budget, *, _record=None):
    if type(interval) not in (DifferentialInterval, CurrentGeometry) or interval._resource is not budget:
        raise V.VolumeError('issued differential interval and the same WorkBudget required')
    # The assembly already owns this decoded record. Borrowing it avoids only
    # another JSON parse; all plate/ray/history decoders below still run, and
    # the issued-object and shared-budget checks above are never bypassed.
    record = interval.record() if _record is None else _record
    plates = record.get('plate_angular_velocity_rad_s', record.get('plate_ids', ()))
    if plate_id not in plates:
        raise V.VolumeError('unknown source plate')
    omega = (_load_vec(record['plate_angular_velocity_rad_s'][plate_id]) if type(interval) is DifferentialInterval
             else (Q(0),)*3)
    rays = {key: (_load_vec(row['direction']), _load_vec(row['angular_velocity_rad_s']), _history(row.get('prior_rotations', ())))
            for key, row in record['rays'].items()}
    fans = tuple(tuple(row['ray_ids']) for row in record['ownership_fans'] if row['plate_id'] == plate_id)
    return record, omega, rays, fans


def _fan_planes(fan, rays, a, b, level, arena):
    posed = tuple(_ray_box(rays[key][0], rays[key][1], a, b, level, arena, _ray_parts(rays[key])[2])[:2] for key in fan)
    result = []
    for (p, ep), (q, eq) in zip(posed, posed[1:]+posed[:1]):
        normal = O._cross(p, q)
        # Euclidean errors bounded with exact L1 upper bounds on the operands.
        error = ep*sum(map(abs, q))+eq*sum(map(abs, p))+ep*eq
        result.append((normal, error))
    return tuple(result)


def _fixed_hemisphere(fans, rays):
    """Prove an issued owner's fan union is one invariant hemisphere.

    Exact reverse-edge cancellation leaves ONE directed great-circle cycle.
    Every nonboundary ray is strictly inside the same half sphere; each
    boundary edge has the same orientation. Current and retained rotations
    are about that plane's normal, so the boundary plane is fixed throughout.
    The issued positive, nonoverlapping fan partition supplies the interior
    coverage theorem; this helper does not admit caller-authored polygons.
    Only integration cuts are cancelled. No material component is combined.
    """
    edges = {}
    vertices = set()
    for fan in fans:
        vertices.update(fan)
        for first, second in zip(fan, fan[1:]+fan[:1]):
            reverse = (second, first)
            if edges.get(reverse, 0):
                edges[reverse] -= 1
                if not edges[reverse]:
                    del edges[reverse]
            else:
                edges[first, second] = edges.get((first, second), 0)+1
    if len(edges) < 3 or any(count != 1 for count in edges.values()):
        return None
    following = {}
    for first, second in edges:
        if first in following:
            return None
        following[first] = second
    if set(following) != set(following.values()):
        return None
    first = min(following)
    cursor, visited = first, set()
    while cursor not in visited:
        visited.add(cursor)
        cursor = following[cursor]
    if cursor != first or visited != set(following):
        return None
    normal = O._cross(rays[first][0], rays[following[first]][0])
    if not any(normal):
        return None
    normal = _scale_ray(normal)
    for start, end in edges:
        cross = O._cross(rays[start][0], rays[end][0])
        if any(O._cross(normal, cross)) or O._dot(normal, cross) <= 0:
            return None
    for key in vertices:
        point, omega, prior = _ray_parts(rays[key])
        distance = O._dot(normal, point)
        if (key in visited and distance != 0) or (key not in visited and distance <= 0):
            return None
        if any(O._cross(normal, omega)) or any(any(O._cross(normal, w)) for w, _ in prior):
            return None
    return normal


def _source_planes(cones, omega, a, b, level, arena, prior=()):
    if cones is None:
        return ((),)
    return tuple(tuple(W._pose_vector(n, omega, a, b, level, arena, prior=prior) for n in V._cone_normals(cone))
                 for cone in cones)


def _bernstein_range_fraction(coefficients, a, b):
    """Enclose a power polynomial on [a,b], retaining exact endpoint zeros."""
    if (type(a) is Q and type(b) is Q and a == b
            and type(coefficients) is tuple and bool(coefficients)
            and all(type(pair) is tuple and len(pair) == 2
                    and all(type(q) is Q for q in pair) for pair in coefficients)):
        # Higher transformed powers are exact zero; every Bernstein interval
        # is power[0]. Retain its original expression, including 0**0 = 1.
        degree = len(coefficients)-1
        return _sum(_product(coefficients[k], (factor, factor))
            for k in range(degree+1)
            for factor in (Q(math.comb(k, 0))*a**k*(b-a)**0,))
    degree = len(coefficients)-1
    power = tuple(_sum(_product(coefficients[k], (factor, factor))
        for k in range(j, degree+1)
        for factor in (Q(math.comb(k, j))*a**(k-j)*(b-a)**j,)) for j in range(degree+1))
    bernstein = tuple(_sum(_product(power[k], (factor, factor)) for k in range(j+1)
        for factor in (Q(math.comb(j, k), math.comb(degree, k)),)) for j in range(degree+1))
    return min(lo for lo, _ in bernstein), max(hi for _, hi in bernstein)


def _rotation_boxes_fraction(vector, omega, a, b, level, arena):
    """Componentwise enclosure of exp([omega]x t) applied to a vector box.

    The exact matrix series has a factored t^(N+1) tail. Bounding its POWER
    coefficient and then converting to Bernstein form preserves endpoint
    zeros/signs; adding a uniform error ball would lose those correlations.
    The infinity-norm tail is the same geometric majorant used by _ray_box.
    Cayley-Hamilton A^3=-|omega|^2 A proves a component with both first and
    second derivatives identically zero has no higher-order tail.
    """
    if a > b:
        raise V.VolumeError('rotation time bracket reversed')
    if not any(omega) or a == b == 0:
        return vector
    fixed = tuple((q, q) for q in omega)
    first = _cross_bounds(fixed, vector)
    second = _cross_bounds(fixed, first)
    inactive = tuple(first[j] == second[j] == (Q(0), Q(0)) for j in range(3))
    if all(inactive):
        return vector
    norm = max(max(map(abs, pair)) for pair in vector)
    matrix_norm = max(abs(omega[1])+abs(omega[2]), abs(omega[0])+abs(omega[2]),
                      abs(omega[0])+abs(omega[1]))
    time = max(abs(a), abs(b))
    target = norm/Q(2**(32+2*level))
    terms, term, major, order = [vector], vector, norm, 0
    while True:
        following = major*matrix_norm/(order+1)
        ratio = time*matrix_norm/(order+2)
        if ratio < 1 and following*time**(order+1)/(1-ratio) <= target:
            tail = following/(1-ratio)
            break
        arena.work(128+32*order)
        values = (*omega, a, b, major, *(q for pair in term for q in pair))
        with V._work(values, arena.resource):
            term = tuple((lo/(order+1), hi/(order+1)) for lo, hi in _cross_bounds(fixed, term))
            terms.append(term)
            major = following
            order += 1
    arena.work(128*len(terms)**2)
    with V._work((*omega, a, b, tail, *(q for term in terms for pair in term for q in pair)), arena.resource):
        return tuple(_bernstein_range(tuple(term[j] for term in terms)+
            (((Q(0), Q(0)) if inactive[j] else (-tail, tail)),), a, b) for j in range(3))


try:
    import gmpy2 as _wp23_gmp
    _wp23_mpq = _wp23_gmp.mpq
except ImportError:          # the original Fraction route remains complete
    _wp23_gmp = _wp23_mpq = None
_WP23_MEMO_LIMIT = 4096


def _wp23_bits(value):
    return max(1, int(value.numerator).bit_length()+int(value.denominator).bit_length())


def _wp23_work(values, budget):
    """The exact V._work reservation size and category, for mpq operands."""
    bits = sum(_wp23_bits(v) for v in values)
    return V.select_budget(budget).reserve(65536+128*bits+256*len(values), category='i03-physical-volume')


def _wp23_fraction(value):
    return Q(int(value.numerator), int(value.denominator))


def _wp23_product(first, second):
    values = (first[0]*second[0], first[0]*second[1], first[1]*second[0], first[1]*second[1])
    return min(values), max(values)


def _wp23_cross(a, b):
    out = []
    for j in range(3):
        left = _wp23_product(a[(j+1) % 3], b[(j+2) % 3])
        right = _wp23_product(a[(j+2) % 3], b[(j+1) % 3])
        out.append((left[0]-right[1], left[1]-right[0]))
    return tuple(out)


def _wp23_bernstein(coefficients, a, b):
    """_bernstein_range_fraction's exact arithmetic on mpq values (mpq in, mpq out)."""
    mpq = _wp23_mpq
    degree = len(coefficients)-1
    if a == b:
        low = high = mpq(0)
        for k in range(degree+1):
            factor = mpq(math.comb(k, 0))*a**k
            p = _wp23_product(coefficients[k], (factor, factor))
            low += p[0]; high += p[1]
        return low, high
    width = b-a
    power = []
    for j in range(degree+1):
        low = high = mpq(0)
        for k in range(j, degree+1):
            factor = mpq(math.comb(k, j))*a**(k-j)*width**j
            p = _wp23_product(coefficients[k], (factor, factor))
            low += p[0]; high += p[1]
        power.append((low, high))
    lows, highs = [], []
    for j in range(degree+1):
        low = high = mpq(0)
        for k in range(j+1):
            factor = mpq(math.comb(j, k), math.comb(degree, k))
            p = _wp23_product(power[k], (factor, factor))
            low += p[0]; high += p[1]
        lows.append(low); highs.append(high)
    return min(lows), max(highs)


def _bernstein_range(coefficients, a, b):
    """Enclose a power polynomial on [a,b] (WP23: exact mpq route, identical values)."""
    if (_wp23_mpq is None or type(a) is not Q or type(b) is not Q or type(coefficients) is not tuple
            or not coefficients or not all(type(pair) is tuple and len(pair) == 2 and
                                           all(type(q) is Q for q in pair) for pair in coefficients)):
        return _bernstein_range_fraction(coefficients, a, b)
    mpq = _wp23_mpq
    low, high = _wp23_bernstein(tuple((mpq(lo), mpq(hi)) for lo, hi in coefficients), mpq(a), mpq(b))
    return _wp23_fraction(low), _wp23_fraction(high)


def _wp23_rotation_compute(vector, omega, a, b, level, arena, charges):
    """_rotation_boxes_fraction on mpq values; records each arena.work charge."""
    mpq = _wp23_mpq
    if a > b:
        raise V.VolumeError('rotation time bracket reversed')
    if not any(omega) or a == b == 0:
        return vector
    w = tuple(mpq(q) for q in omega)
    fixed = tuple((q, q) for q in w)
    box = tuple((mpq(lo), mpq(hi)) for lo, hi in vector)
    first = _wp23_cross(fixed, box)
    second = _wp23_cross(fixed, first)
    inactive = tuple(first[j][0] == first[j][1] == second[j][0] == second[j][1] == 0 for j in range(3))
    if all(inactive):
        return vector
    norm = max(max(abs(lo), abs(hi)) for lo, hi in box)
    matrix_norm = max(abs(w[1])+abs(w[2]), abs(w[0])+abs(w[2]), abs(w[0])+abs(w[1]))
    qa, qb = mpq(a), mpq(b)
    time = max(abs(qa), abs(qb))
    target = norm/mpq(2**(32+2*level))
    terms, term, major, order = [box], box, norm, 0
    while True:
        following = major*matrix_norm/(order+1)
        ratio = time*matrix_norm/(order+2)
        if ratio < 1 and following*time**(order+1)/(1-ratio) <= target:
            tail = following/(1-ratio)
            break
        charges.append(128+32*order)
        arena.work(128+32*order)
        values = (*w, qa, qb, major, *(q for pair in term for q in pair))
        with _wp23_work(values, arena.resource):
            term = tuple((lo/(order+1), hi/(order+1)) for lo, hi in _wp23_cross(fixed, term))
            terms.append(term)
            major = following
            order += 1
    charges.append(128*len(terms)**2)
    arena.work(128*len(terms)**2)
    zero = mpq(0)
    with _wp23_work((*w, qa, qb, tail, *(q for t in terms for pair in t for q in pair)), arena.resource):
        out = []
        for j in range(3):
            coefficients = tuple(t[j] for t in terms)+(((zero, zero) if inactive[j] else (-tail, tail)),)
            low, high = _wp23_bernstein(coefficients, qa, qb)
            out.append((_wp23_fraction(low), _wp23_fraction(high)))
        return tuple(out)


def _rotation_boxes(vector, omega, a, b, level, arena):
    """Componentwise enclosure of exp([omega]x t) applied to a vector box.

    WP23: identical results to _rotation_boxes_fraction (exact mpq arithmetic) and
    exact per-query reuse with the original work charges replayed on a hit.
    """
    # Fractions only: with ints the original arithmetic could return ints, and
    # downstream code distinguishes types. Anything else takes the original route.
    if (_wp23_mpq is None or type(level) is not int or type(a) is not Q or type(b) is not Q
            or type(vector) is not tuple or type(omega) is not tuple or len(vector) != 3 or len(omega) != 3
            or not all(type(q) is Q for q in omega)
            or not all(type(pair) is tuple and len(pair) == 2 and all(type(q) is Q for q in pair)
                       for pair in vector)):
        return _rotation_boxes_fraction(vector, omega, a, b, level, arena)
    memo = getattr(arena, '_wp23_rotation_memo', None)
    key = (tuple(vector), tuple(omega), a, b, level)
    if memo is not None:
        hit = memo.get(key)
        if hit is not None:
            result, charges = hit
            for count in charges:
                arena.work(count)
            return result
    charges = []
    result = _wp23_rotation_compute(vector, omega, a, b, level, arena, charges)
    if memo is None:
        try:
            memo = arena._wp23_rotation_memo = {}
        except AttributeError:
            return result
    if len(memo) < _WP23_MEMO_LIMIT:
        arena.keep((*(q for pair in vector for q in pair), *omega, a, b,
                    *(q for pair in result for q in pair)), objects=2)
        memo[key] = (result, tuple(charges))
    return result


def _ray_component_boxes(ray, a, b, level, arena):
    vector = tuple((q, q) for q in _load_vec(ray['direction']))
    for omega, duration in _history(ray.get('prior_rotations', ())):
        vector = _rotation_boxes(vector, omega, duration, duration, level, arena)
    return _rotation_boxes(vector, _load_vec(ray['angular_velocity_rad_s']), a, b, level, arena)


def _constraint_boxes(constraint, a, b, level, arena):
    kind = constraint['kind']
    if kind == 'snapshot-rotated':
        time = W._decode(constraint['snapshot_offset_s'])
        normal, offset = _constraint_boxes(constraint['constraint'], time, time, level, arena)
        return _rotation_boxes(normal, _load_vec(constraint['angular_velocity_rad_s']), a, b, level, arena), offset
    if kind == 'rotated-normal':
        normal = tuple((q, q) for q in _load_vec(constraint['normal']))
        return _rotation_boxes(normal, _load_vec(constraint['angular_velocity_rad_s']), a, b, level, arena), Q(0)
    if kind == 'moving-ray-edge':
        first, second = (_ray_component_boxes(ray, a, b, level, arena) for ray in constraint['rays'])
        return _cross_bounds(first, second), Q(0)
    if kind == 'fixed-plane':
        return tuple((q, q) for q in _load_vec(constraint['normal'])), W._decode(constraint['offset'])
    raise V.VolumeError('unknown physical constraint kind')


def _boxed_constraint_line(face, bounds, box, offset, sign, inner):
    """Affine lower/upper bound using the rectangle's actual coordinate signs."""
    vertices = tuple(W._point(face, p) for p in W._rectangle(bounds))
    normal, uncertainty = [], Q(0)
    for j, pair in enumerate(box):
        lo, hi = pair if sign > 0 else (-pair[1], -pair[0])
        minimum, maximum = min(p[j] for p in vertices), max(p[j] for p in vertices)
        if minimum >= 0:
            normal.append(lo if inner else hi)
        elif maximum <= 0:
            normal.append(hi if inner else lo)
        else:
            normal.append((lo+hi)/2)
            uncertainty += (hi-lo)*max(-minimum, maximum)/2
    return W._line(face, tuple(normal), sign*offset+(uncertainty if inner else -uncertainty))


def _wall_leaf(layer, face, bounds, omega, rays, fans, cones, polynomials, a, b, level, arena,
               *, integration_weight=None, source_prior=(), fixed_hemisphere=None, pose=None):
    original = W._rectangle(bounds)
    maximum_radius = sum(max(abs(W._point(face, p)[j]) for p in original) for j in range(3))
    owned = (((fixed_hemisphere, Q(0)),),) if fixed_hemisphere is not None else tuple(
        _fan_planes(fan, rays, a, b, level, arena) for fan in fans)
    source = _source_planes(cones, omega, a, b, level, arena, source_prior)
    if pose is not None:
        pose[0] = any(error for planes in (*owned, *source) for _, error in planes)
    shapes = []
    for inner in (True, False):
        polygons = []
        for owner in owned:
            for material in source:
                poly = original
                for normal, error in (*owner, *material):
                    poly = W._clip2(poly, W._line(face, normal, (1 if inner else -1)*error*maximum_radius), arena)
                    if not poly:
                        break
                for line in W._radial_planes(face, bounds, layer, inner):
                    poly = W._clip2(poly, line, arena)
                if poly:
                    polygons.append(poly)
        shapes.append(polygons)
    duration = b-a if integration_weight is None else integration_weight
    linear = tuple(O._dot(face[3], O._cross(omega, direction)) for direction in (face[1], face[2], face[0]))
    result = []
    for sign in (-1, 1):
        velocity = tuple(sign*v for v in linear)
        whole = W._integral(W._clip2(original, velocity, arena), velocity, arena)
        pair = tuple(min(whole, sum(W._integral(W._clip2(poly, velocity, arena), velocity, arena) for poly in polygons))*duration
                     for polygons in shapes)
        result.append(pair)
    inner_area = sum(W._integral(poly, (0, 0, 1), arena) for poly in shapes[0])
    outer_area = min(W._integral(original, (0, 0, 1), arena),
                     sum(W._integral(poly, (0, 0, 1), arena) for poly in shapes[1]))
    if outer_area < inner_area:
        raise V.VolumeError('differential ownership enclosure lost its disjoint physical partition')
    for polynomial in polynomials:
        exact_inner = sum(_polynomial_integral(poly, polynomial, arena) for poly in shapes[0])
        low, high = _polynomial_range(polynomial, bounds)
        result.append(((exact_inner+min(Q(0), low)*(outer_area-inner_area))*duration,
                       (exact_inner+max(Q(0), high)*(outer_area-inner_area))*duration))
    arena.work(128+64*len(owned)*len(source))
    return tuple(result)


def _refine(leaf, bounds, duration, widths, max_leaves, arena, *, spatial_only=False):
    quantums = tuple(W._quantum(width, max_leaves) for width in widths)
    def evaluate(box, a, b, level):
        pairs = leaf(box, a, b, level)
        if any(lo > hi for lo, hi in pairs):
            raise V.VolumeError('physical differential integral has reversed enclosure')
        return tuple(W._outward(pair, quantum) for pair, quantum in zip(pairs, quantums))
    first = evaluate(bounds, Q(0), duration, 0)
    sums, queue, serial, leaves = [list(pair) for pair in first], [], 0, 1
    def push(box, a, b, level, values):
        nonlocal serial
        uncertainty = max((hi-lo)/(width if width else 1) for (lo, hi), width in zip(values, widths))
        if uncertainty:
            serial += 1
            heapq.heappush(queue, (-uncertainty, serial, box, a, b, level, values))
            arena.keep((a, b, *(q for pair in values for q in pair)), 1)
    push(bounds, Q(0), duration, 0, first)
    while queue and any(hi-lo > width for (lo, hi), width in zip(sums, widths)) and leaves < max_leaves:
        _, _, box, a, b, level, old = heapq.heappop(queue)
        dimension = 1+level % 2 if spatial_only else level % 3
        if dimension == 0:
            middle = (a+b)/2
            children = ((box, a, middle), (box, middle, b))
        else:
            k = dimension-1
            middle = sum(box[k])/2
            lower, upper = list(box), list(box)
            lower[k], upper[k] = (box[k][0], middle), (middle, box[k][1])
            children = ((tuple(lower), a, b), (tuple(upper), a, b))
        values = []
        for child, ca, cb in children:
            current = evaluate(child, ca, cb, level+1)
            values.append(current)
            push(child, ca, cb, level+1, current)
        for i in range(len(widths)):
            for j in range(2):
                sums[i][j] += sum(v[i][j] for v in values)-old[i][j]
        leaves += 1
    return tuple(tuple(pair) for pair in sums), leaves, all(hi-lo <= width for (lo, hi), width in zip(sums, widths))


STATIC_POSE_LEVELS = (32, 64)


def _finer_static_pose(first, leaf, bounds, weight, widths, max_leaves, arena):
    """Finer pose of the SAME undivided face, for a query at one instant.

    At one instant nothing moves across the face. Where the planes of a posed
    owner or component come from a rotation, they are known as rational
    enclosures whose width at pose level L is 2^-(32+2L) of the vector. The
    ordinary refinement raises L by one for every halving of the face, so
    the declared leaves buy a few more bits of pose and cannot bring a
    carried rotation to a width such as 1e-24. The pose itself can: the
    undivided face is evaluated again at the levels above. Each evaluation
    encloses the same integral, so the enclosures are intersected, and two
    that do not meet are refused.

    The caller offers this only for a root whose own evaluation formed an
    inexact pose enclosure; ``first`` is that evaluation. A root that meets
    its widths is left to the refinement, which returns it unchanged, and so
    is a root no level brings inside them (a wall also cut by the shell).
    A successful finer-pose result counts each further level as one leaf.
    If the attempt declines, ordinary refinement keeps its terminal-leaf
    ceiling; the extra evaluations remain charged in the arena and record.
    The leaf ceiling is not a cumulative evaluation limit. Returns
    (values, leaves, level) when every width is met, otherwise None.
    """
    quantums = tuple(W._quantum(width, max_leaves) for width in widths)
    def rounded(pairs):
        if any(lo > hi for lo, hi in pairs):
            raise V.VolumeError('physical differential integral has reversed enclosure')
        return tuple(W._outward(pair, quantum) for pair, quantum in zip(pairs, quantums))
    def unmet(values):
        return any(hi-lo > width for (lo, hi), width in zip(values, widths))
    values = rounded(first)
    if not unmet(values):
        return None
    # An entry whose declared width is zero and whose root is inexact is not
    # offered a finer pose: the refinement runs as before and issues the
    # record it always issued, work count included. (A finer level could make
    # such an entry exact only where a plane that just cuts the face at the
    # root clears it at the finer level; the saving is forgone there, never
    # the result.)
    if any(width == 0 and lo != hi for (lo, hi), width in zip(values, widths)):
        return None
    for leaves, level in enumerate(STATIC_POSE_LEVELS, 2):
        if leaves > max_leaves:
            break
        finer = rounded(leaf(bounds, Q(0), weight, level))
        values = tuple((max(a[0], b[0]), min(a[1], b[1])) for a, b in zip(values, finer))
        if any(lo > hi for lo, hi in values):
            raise V.VolumeError('enclosures of one static face at two pose precisions contradict')
        arena.keep(tuple(q for pair in values for q in pair), 1)
        if not unmet(values):
            return values, leaves, level
    return None


def _moving_fan_integrals(ray_records, layer, face, omega, rays, fans, polynomials, widths, duration,
                          max_leaves, arena, whole):
    """Certified interval integrals of an owner's fan partition on one face.

    The owner's region is the issued positive, nonoverlapping fan partition;
    the geometric leaf already sums its fans. Each fan cone cuts the fixed
    face in one convex polygon whose edges may move, so its flux and
    polynomial moments have the fixed-topology interval-Taylor integral
    already used for component masks. Every fan uses the same face chart and
    the same complete interval.
    Fans whose geometric root enclosure is exact contribute exactly. A root
    is inexact for one of three reasons: an edge of the fan moves across the
    face, the pose of an edge ray is known only as an enclosure (a carried
    rotation history, even when every rate is zero), or the shell cuts the
    wall. The ``n`` fans without an exact root are integrated and each
    receives width/n, so the summed width meets the ORIGINAL query width; a
    fan is never given the whole allowance. The sum and ``whole``, the
    geometric enclosure of the complete partition (which caps the owned area
    and flux by the face), enclose the same quantity: the result is their
    intersection, and disjoint enclosures refuse.
    The leaf ceiling is shared: one root plus every additional time split,
    and a total above it after any fan declines.
    Returns (values, leaves, integrated fan count), or None when a fan has
    no certified Taylor integral, its allocation is not met or the ceiling
    is passed; the caller then runs the original geometric refinement with
    the same widths and ceiling. The work of a declined attempt stays in the
    arena and in the record.
    """
    from . import integration_moving_face_moments as TM
    start = (face[4], Q(0), duration, 0)
    exact, inexact = [Q(0)]*len(widths), []
    for fan in fans:
        leaf = lambda box, a, b, level, fan=fan: _wall_leaf(
            layer, face, box, omega, rays, (fan,), None, polynomials, a, b, level, arena)
        first = leaf(*start)
        if any(lo != hi for lo, hi in first):
            inexact.append((fan, leaf, first))
        else:
            exact = [total+pair[0] for total, pair in zip(exact, first)]
    if not inexact:
        return None
    arena.keep(tuple(exact), len(inexact))
    share = tuple(width/len(inexact) for width in widths)
    totals, leaves = [(q, q) for q in exact], 1
    for fan, leaf, first in inexact:
        constraints, literals = {}, []
        for one, two in zip(fan, fan[1:]+fan[:1]):
            name = 'owner-fan-edge:'+one+'>'+two
            constraints[name] = dict(kind='moving-ray-edge', rays=[ray_records[one], ray_records[two]])
            literals.append((name, 1))
        # The fan's root enclosure was just evaluated; do not charge it twice.
        fallback = lambda box, a, b, level, leaf=leaf, first=first: (
            first if (box, a, b, level) == start else leaf(box, a, b, level))
        result = TM.integrate(dict(constraints=constraints), dict(constraints=literals), layer, face, omega,
            polynomials, share, duration, fallback=fallback, max_leaves=max_leaves-leaves+1, arena=arena)
        if result is None or not result[2]:
            return None
        totals = [(a[0]+b[0], a[1]+b[1]) for a, b in zip(totals, result[0])]
        leaves += result[1]-1
        # Checked after every fan, the last included: the next fan is offered
        # at least its own root, and no accepted total passes the ceiling.
        if leaves > max_leaves:
            return None
    # Two certified enclosures of one quantity must meet; their intersection
    # is at least as narrow as the allocated sum.
    totals = tuple((max(lo, outer[0]), min(hi, outer[1])) for (lo, hi), outer in zip(totals, whole))
    if any(lo > hi for lo, hi in totals):
        raise V.VolumeError('integrated ownership fans contradict their complete partition enclosure')
    return totals, leaves, len(inexact)


def _query_inputs(layer, cell, max_width_m3, max_leaves, moment_polynomials, max_moment_widths):
    if type(layer) is not V.RadialLayer or type(cell) is not V.CartesianCell:
        raise V.VolumeError('actual typed physical layer and Cartesian cell required')
    width = W._q(max_width_m3)
    polynomials = _polynomials(moment_polynomials)
    moment_widths = tuple(W._q(q) for q in max_moment_widths)
    if len(moment_widths) != len(polynomials) or any(q < 0 for q in moment_widths) or width < 0:
        raise V.VolumeError('each dimensional moment requires its own explicit nonnegative width')
    if type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('positive finite query subdivision limit required')
    return polynomials, (width, width, *moment_widths)


def _enclose_cartesian_face(interval, plate_id, layer, cell, axis, end, *,
                              source_key=None, source_cones=None, moment_polynomials=(),
                              max_moment_widths=(), max_width_m3, max_leaves, budget, endpoint=None,
                              moments_only=False):
    """Both signs and polynomial moments on an actual fixed Cartesian face.

    Polynomials use the returned physical local u,v coordinates, NOT normalised
    FE coordinates. Coefficients may incorporate the exact affine FE map. The
    returned `met` must be true before a consumer accepts the interval.
    """
    record, omega, rays, fans = _unpack(interval, plate_id, budget)
    polynomials, widths = _query_inputs(layer, cell, max_width_m3, max_leaves, moment_polynomials, max_moment_widths)
    if layer.radius_m != W._decode(record['radius_m']):
        raise V.VolumeError('physical layer and differential network reference radii differ')
    if type(axis) is not int or axis not in (0, 1, 2) or type(end) is not int or end not in (0, 1):
        raise V.VolumeError('Cartesian face axis/end must be explicit integer indices')
    cones = None if source_cones is None else tuple(V.convex_cone_union((cone,), budget=budget) for cone in source_cones)
    if cones == ():
        raise V.VolumeError('an inherited support cannot be empty or replaced by whole-plate ownership')
    face, duration = W._face(cell, axis, end), W._decode(record['duration_s'])
    history = record.get('trajectory', {}).get('segments', [])
    previous = history[:-1] if type(interval) is DifferentialInterval else history
    source_prior = tuple((_load_vec(s['plate_angular_velocity_rad_s'][plate_id]),
                         W._decode(s['end_time_s'])-W._decode(s['start_time_s'])) for s in previous)
    with B._Arena(budget) as arena:
        arena.work(128+64*len(fans))
        fixed_hemisphere = _fixed_hemisphere(fans, rays)
        if endpoint is None:
            leaf = lambda box, a, b, level: _wall_leaf(
                layer, face, box, omega, rays, fans, cones, polynomials, a, b, level, arena,
                source_prior=source_prior, fixed_hemisphere=fixed_hemisphere)
            weight = duration
        else:
            if endpoint not in ('start', 'end'):
                raise V.VolumeError('physical endpoint must be start or end')
            time, pose = Q(0) if endpoint == 'start' else duration, [False]
            leaf = lambda box, a, b, level: _wall_leaf(
                layer, face, box, omega, rays, fans, cones, polynomials, time, time, level, arena,
                integration_weight=Q(1), source_prior=source_prior, fixed_hemisphere=fixed_hemisphere, pose=pose)
            weight = Q(1)
        if moments_only:
            if endpoint is None or not polynomials:
                raise V.VolumeError('moments-only query requires an endpoint and explicit moments')
            full_leaf = leaf
            leaf = lambda box, a, b, level: full_leaf(box, a, b, level)[2:]
            widths = widths[2:]
        temporal = None
        if endpoint is None:
            # One root evaluation serves both routes. The fan route is tried
            # only for a root that misses a declared width, judged with the
            # outward rounding and comparison _refine applies to its root. An
            # exact root, and a root that is not exact but meets every width,
            # go to the original refinement alone: its record and its work.
            start, geometric = (face[4], Q(0), duration, 0), leaf
            whole = geometric(*start)
            leaf = lambda box, a, b, level: whole if (box, a, b, level) == start else geometric(box, a, b, level)
            rounded = (W._outward(pair, W._quantum(width, max_leaves)) for pair, width in zip(whole, widths))
            if (cones is None and fixed_hemisphere is None and any(lo != hi for lo, hi in whole) and
                    any(hi-lo > width for (lo, hi), width in zip(rounded, widths))):
                temporal = _moving_fan_integrals(record['rays'], layer, face, omega, rays, fans, polynomials,
                                                 widths, duration, max_leaves, arena, whole)
        reposed = None
        if endpoint is not None:
            # One root evaluation serves both routes, as above.
            start, single = (face[4], Q(0), weight, 0), leaf
            first = single(*start)
            leaf = lambda box, a, b, level: first if (box, a, b, level) == start else single(box, a, b, level)
            if pose[0]:
                reposed = _finer_static_pose(first, single, face[4], weight, widths, max_leaves, arena)
        if reposed is not None:
            values, leaves, met = reposed[0], reposed[1], True
        elif temporal is None:
            values, leaves, met = _refine(leaf, face[4], weight, widths, max_leaves, arena,
                                         spatial_only=endpoint is not None)
        else:
            values, leaves, met = temporal[0], temporal[1], True
        if moments_only:
            values = ((Q(0), Q(0)), (Q(0), Q(0)), *values)
        result = dict(schema=MEASURE_SCHEMA, kind='fixed-cartesian-wall',
            interval_id=interval.interval_id if type(interval) is DifferentialInterval else None,
            plate_id=plate_id, source_key=source_key, source_cones=None if cones is None else
            [[_store_vec(p) for p in cone] for cone in cones], physical_cell_id=cell.cell_id,
            radial_layer=layer.record(), axis=axis, end=end, start_time_s=record['start_time_s'],
            end_time_s=record['end_time_s'], face=dict(origin_m=_store_vec(face[0]),
                tangent_u=_store_vec(face[1]), tangent_v=_store_vec(face[2]), outward_normal=_store_vec(face[3]),
                coordinate_bounds_m=[[_qtext(a), _qtext(b)] for a, b in face[4]], area_jacobian=_qtext(Q(1))),
            inward_volume_bounds_m3=[_qtext(q) for q in values[0]],
            outward_volume_bounds_m3=[_qtext(q) for q in values[1]],
            moment_polynomials=[[[i, j, _qtext(q)] for (i, j), q in sorted(poly.items())] for poly in polynomials],
            moment_bounds=[[_qtext(q) for q in pair] for pair in values[2:]],
            max_widths=[_qtext(q) for q in widths], max_leaves=max_leaves, leaves=leaves,
            met=met, work_units=arena.work_units,
            ownership_measure=('exact-invariant-hemisphere-union' if fixed_hemisphere is not None
                               else 'issued-positive-fan-partition'),
            authority='physical geometry only; no native velocity projection or material stock transfer')
        if endpoint is not None:
            result['kind'] = 'instantaneous-cartesian-face'
            result['endpoint'] = endpoint
            result['evaluation_time_s'] = record[endpoint+'_time_s']
            result['inward_volume_rate_bounds_m3_s'] = result.pop('inward_volume_bounds_m3')
            result['outward_volume_rate_bounds_m3_s'] = result.pop('outward_volume_bounds_m3')
            result['moment_time_measure'] = 'spatial only; no time integration or division by an interval'
            if reposed is not None:
                result['static_pose'] = dict(level=reposed[2], levels=[0, *STATIC_POSE_LEVELS[:reposed[1]-1]],
                    rule='undivided face posed again at finer rational precision; enclosures intersected')
        else:
            result['moment_time_measure'] = 'integrated over the complete physical interval'
        if temporal is not None:
            from . import integration_moving_face_moments as TM
            result['temporal_integration'] = dict(method='issued-fan-partition-fixed-topology-interval-Taylor',
                order=TM.ORDER, decimal_precision=80, source_sha256=TM.source_digest(), integrated_fans=temporal[2],
                owner_fans=len(fans),
                width_allocation='each fan without an exact root enclosure receives the query width divided by '
                                 'the count of such fans; exact fans add no width',
                partition='issued positive nonoverlapping owner fans, one face chart and the complete interval; '
                          'sum checked inside the whole-partition geometric enclosure',
                unresolved='original geometric refinement, same widths and leaf ceiling')
        if moments_only:
            result.pop('inward_volume_rate_bounds_m3_s')
            result.pop('outward_volume_rate_bounds_m3_s')
            result['query'] = 'spatial moments only; no rate acceptance criterion requested'
    return _issue(DifferentialMeasure, result, budget)


def enclose_current_face(current, plate_id, layer, cell, axis, end, *, moment_polynomials=(),
                         max_moment_widths=(), max_leaves, budget):
    """Spatial moments before solving for rates; no physical flux is inferred."""
    if type(current) is not CurrentGeometry:
        raise V.VolumeError('issued instantaneous CurrentGeometry required')
    measured = _enclose_cartesian_face(current, plate_id, layer, cell, axis, end,
        moment_polynomials=moment_polynomials, max_moment_widths=max_moment_widths,
        max_width_m3=0, max_leaves=max_leaves, budget=budget, endpoint='start')
    record = measured.record()
    record.pop('interval_id')
    record.pop('endpoint')
    record.pop('inward_volume_rate_bounds_m3_s')
    record.pop('outward_volume_rate_bounds_m3_s')
    record.update(kind='current-owned-spatial-face', geometry_id=current.geometry_id,
                  network_id=current.record()['network_id'], physical_velocity='not supplied, not inferred')
    return _issue(DifferentialMeasure, record, budget)


def enclose_differential_wall(interval, plate_id, layer, cell, axis, end, *,
                              source_key=None, source_cones=None, moment_polynomials=(),
                              max_moment_widths=(), max_width_m3, max_leaves, budget):
    """Issued complete-interval sign-split physical flux and polynomial moments."""
    return _enclose_cartesian_face(interval, plate_id, layer, cell, axis, end,
        source_key=source_key, source_cones=source_cones, moment_polynomials=moment_polynomials,
        max_moment_widths=max_moment_widths, max_width_m3=max_width_m3, max_leaves=max_leaves, budget=budget)


def enclose_differential_face_at(interval, plate_id, layer, cell, axis, end, *, endpoint,
                                 source_key=None, source_cones=None, moment_polynomials=(),
                                 max_moment_widths=(), max_rate_width_m3_s=None, max_leaves, budget):
    """Issued endpoint-owned SPATIAL moments and instantaneous volume rates.

    This is not an interval average. The force lift may use it before the
    resulting actual angular velocity is bound to an interval trajectory.
    """
    return _enclose_cartesian_face(interval, plate_id, layer, cell, axis, end,
        source_key=source_key, source_cones=source_cones, moment_polynomials=moment_polynomials,
        max_moment_widths=max_moment_widths, max_width_m3=0 if max_rate_width_m3_s is None else max_rate_width_m3_s,
        max_leaves=max_leaves, budget=budget, endpoint=endpoint, moments_only=max_rate_width_m3_s is None)


def _quadratic_radial_planes(face, bounds, layer, inner, padding=Q(0)):
    """Shell bounds in a non-orthogonal radial-wall parameter rectangle.

    q(y)=|y|²=L(y)+|y-centre|². The latter convex quadratic has its maximum
    at a rectangle corner. Its exact minimum is checked at corners and at
    the constrained stationary point on every edge (and the origin).
    """
    vertices = tuple(W._point(face, p) for p in W._rectangle(bounds))
    centre = W._point(face, tuple((a+b)/2 for a, b in bounds))
    residual = max(O._dot(O._minus(p, centre), O._minus(p, centre)) for p in vertices)
    u, v = face[1:3]
    aa, ab, bb = O._dot(u, u), O._dot(u, v), O._dot(v, v)
    candidates = list(W._rectangle(bounds))
    for fixed in bounds[1]:
        candidates.append((max(bounds[0][0], min(bounds[0][1], -ab*fixed/aa)), fixed))
    for fixed in bounds[0]:
        candidates.append((fixed, max(bounds[1][0], min(bounds[1][1], -ab*fixed/bb))))
    if all(a <= 0 <= b for a, b in bounds):
        candidates.append((Q(0), Q(0)))
    minimum = min(O._dot(W._point(face, p), W._point(face, p)) for p in candidates)
    maximum = max(O._dot(p, p) for p in vertices)
    lo2, hi2 = layer.bottom_radius_m**2, layer.top_radius_m**2
    if minimum-padding >= hi2 or maximum+padding <= lo2:
        return ((Q(0), Q(0), Q(-1)),)
    if minimum-padding >= lo2 and maximum+padding <= hi2:
        return ()
    squared, gradient = O._dot(centre, centre), tuple(2*q for q in centre)
    pad = padding if inner else -padding
    return (W._line(face, gradient, lo2+squared-(0 if inner else residual)+pad),
            W._line(face, tuple(-q for q in gradient), -hi2-squared+(residual if inner else 0)+pad))


def _boundary_leaf(layer, face, bounds, voxel, boundary_omega, relative_omega,
                   cones, a, b, level, arena, boundary_prior=(), source_prior=()):
    original = W._rectangle(bounds)
    vertices = tuple(W._point(face, p) for p in original)
    absolute = sum(max(abs(p[j]) for p in vertices) for j in range(3))
    linear = tuple(O._dot(face[3], O._cross(relative_omega, p)) for p in (face[1], face[2], face[0]))
    # All fields are evaluated in the moving boundary frame. Coaxial rotations
    # commute, so the relative material rotation is exactly omega_p-omega_b.
    source = _source_planes(cones, relative_omega, a, b, level, arena, source_prior)
    fixed = []
    if voxel is not None:
        for plane in O._box_planes(voxel):
            normal, error = W._pose_vector(tuple(-q for q in plane[:3]), boundary_omega,
                                          a, b, level, arena, inverse=True, prior=boundary_prior)
            fixed.append((normal, error, -plane[3]))
    values = []
    for sign in (-1, 1):
        velocity = tuple(sign*q for q in linear)
        signed = W._clip2(original, velocity, arena)
        whole = W._integral(signed, velocity, arena)
        pair = []
        for inner in (True, False):
            total = Q(0)
            for material in source:
                poly = signed
                for normal, error in material:
                    poly = W._clip2(poly, W._line(face, normal, (1 if inner else -1)*error*absolute), arena)
                for normal, error, offset in fixed:
                    poly = W._clip2(poly, W._line(face, normal, offset+(1 if inner else -1)*error*absolute), arena)
                for plane in _quadratic_radial_planes(face, bounds, layer, inner):
                    poly = W._clip2(poly, plane, arena)
                total += W._integral(poly, velocity, arena)
            pair.append(min(whole, total)*(b-a))
        values.append(tuple(pair))
    arena.work(128+64*len(source)+64*len(fixed))
    return tuple(values)


def _unit_interval(ray, bits):
    squared = O._dot(ray, ray)
    scale = 1 << bits
    integer = math.isqrt((squared.numerator << (2*bits))//squared.denominator)
    low = Q(integer, scale)
    high = low if low*low == squared else Q(integer+1, scale)
    if not low:
        raise V.VolumeError('unit-ray enclosure precision did not separate its positive norm')
    return tuple((q/high, q/low) if q >= 0 else (q/low, q/high) for q in ray)


def _whole_radial_segment(layer, a, b, normal_sign, relative, duration, width, max_leaves, arena):
    """Analytic full-wall flux with certified normalisation, not surface quadrature.

    For the oriented minor arc a_hat->b_hat and unit normal n,
    integral (omega×s).n dl = omega.(a_hat-b_hat).  The radial factor
    is integral r²dr. At most one zero of the affine flux splits its signs.
    """
    cross = O._cross(a, b)
    ca = normal_sign*O._dot(cross, O._cross(relative, a))
    cb = normal_sign*O._dot(cross, O._cross(relative, b))
    parts = [(a, b, ca if ca else cb)]
    if ca*cb < 0:
        split = tuple(abs(cb)*p+abs(ca)*q for p, q in zip(a, b))
        parts = [(a, split, ca), (split, b, cb)]
    factor = (layer.top_radius_m**3-layer.bottom_radius_m**3)*duration/3
    for level in range(max_leaves):
        values = [[Q(0), Q(0)], [Q(0), Q(0)]]
        for first, second, sign in parts:
            if not sign:
                continue
            aa, bb = _unit_interval(first, 32+2*level), _unit_interval(second, 32+2*level)
            terms = tuple(_product((normal_sign*w, normal_sign*w), _minus(x, y))
                          for w, x, y in zip(relative, aa, bb))
            lo, hi = (factor*q for q in _sum(terms))
            index, pair = (1, (max(Q(0), lo), max(Q(0), hi))) if sign > 0 else (0, (max(Q(0), -hi), max(Q(0), -lo)))
            for endpoint in range(2):
                values[index][endpoint] += pair[endpoint]
        arena.work(256+128*len(parts))
        if all(hi-lo <= width for lo, hi in values):
            return tuple(tuple(pair) for pair in values), level+1, True
    return tuple(tuple(pair) for pair in values), max_leaves, False


def enclose_boundary_exchange(interval, boundary_id, side, layer, *, physical_cell_id,
                               voxel=None, source_key=None, source_cones=None,
                               max_width_m3, max_leaves, budget):
    """Actual relative flux at a ridge/trench/transform radial side wall.

    Inward means birth/supply into that plate; outward means material leaving
    it. The latter must be debited from the CURRENT carried donor. This query
    neither evaluates a stale I03 density nor funds a reservoir. `voxel` clips
    to a real fixed physical control cell; without it the complete boundary
    side is measured. The logical cell ID and geometric box ID are distinct.
    """
    if type(interval) is not DifferentialInterval or interval._resource is not budget:
        raise V.VolumeError('issued differential interval and same WorkBudget required')
    record = interval.record()
    boundary = next((row for row in record['boundary_paths'] if row['boundary_id'] == boundary_id), None)
    if boundary is None or side not in S.SIDES:
        raise V.VolumeError('actual boundary ID and left/right side required')
    if type(physical_cell_id) is not str or not physical_cell_id:
        raise V.VolumeError('the receiving/donating physical logical cell ID is required')
    if type(layer) is not V.RadialLayer or layer.radius_m != W._decode(record['radius_m']):
        raise V.VolumeError('physical radial layer of this network required')
    if voxel is not None and type(voxel) is not V.CartesianCell:
        raise V.VolumeError('a fixed clipping voxel must be an actual CartesianCell')
    width = W._q(max_width_m3)
    if width < 0 or type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('nonnegative physical error and positive finite leaf limit required')
    plate_id = boundary[side+'_plate_id']
    omega = _load_vec(record['plate_angular_velocity_rad_s'][plate_id])
    carrier = _load_vec(boundary['angular_velocity_rad_s'])
    relative = tuple(p-c for p, c in zip(omega, carrier))
    boundary_prior = _history(boundary.get('prior_rotations', ()))
    previous = record['trajectory']['segments'][:-1]
    source_prior = tuple((tuple(p-b for p, b in zip(
        _load_vec(s['plate_angular_velocity_rad_s'][plate_id]),
        _load_vec(s['boundary_angular_velocity_rad_s'][boundary_id]))),
        W._decode(s['end_time_s'])-W._decode(s['start_time_s'])) for s in previous)
    cones = None if source_cones is None else tuple(V.convex_cone_union((cone,), budget=budget) for cone in source_cones)
    if cones == ():
        raise V.VolumeError('empty inherited source support cannot stand for the whole boundary')
    duration = W._decode(record['duration_s'])
    rays = {key: _load_vec(row['direction']) for key, row in record['rays'].items()}
    chain = boundary['vertex_ids']+[boundary['vertex_ids'][0]] if boundary['closed'] else boundary['vertex_ids']
    totals, segments, all_met = [[Q(0), Q(0)], [Q(0), Q(0)]], [], True
    with B._Arena(budget) as arena:
        for first, second in zip(chain, chain[1:]):
            a, b = rays['vertex:'+first], rays['vertex:'+second]
            cross = O._cross(a, b)
            denominator = max(map(abs, cross))
            if not denominator:
                raise V.VolumeError('radial boundary segment has zero or antipodal opening')
            # |u(a×b)|=|(u a+v b)×b| <= R|b|. L1/max-component
            # bounds give an outward finite rectangle without sqrt rounding.
            bounds = ((Q(0), layer.top_radius_m*sum(map(abs, b))/denominator),
                      (Q(0), layer.top_radius_m*sum(map(abs, a))/denominator))
            normal = tuple((-1 if side == 'left' else 1)*q for q in cross)
            face = ((Q(0),)*3, a, b, normal, bounds)
            per_segment_width = width/(len(chain)-1)
            if voxel is None and cones is None:
                values, leaves, met = _whole_radial_segment(layer, a, b, -1 if side == 'left' else 1,
                    relative, duration, per_segment_width, max_leaves, arena)
            else:
                values, leaves, met = _refine(lambda box, t0, t1, level: _boundary_leaf(
                    layer, face, box, voxel, carrier, relative, cones, t0, t1, level, arena,
                    boundary_prior, source_prior),
                    bounds, duration, (per_segment_width,)*2, max_leaves, arena)
            for sign in range(2):
                for endpoint in range(2):
                    totals[sign][endpoint] += values[sign][endpoint]
            all_met = all_met and met
            segments.append(dict(vertex_ids=[first, second], parameter_rays=[_store_vec(a), _store_vec(b)],
                parameter_bounds=[[_qtext(x), _qtext(y)] for x, y in bounds],
                vector_area=_store_vec(normal), leaves=leaves, met=met,
                inward_volume_bounds_m3=[_qtext(q) for q in values[0]],
                outward_volume_bounds_m3=[_qtext(q) for q in values[1]]))
        result = dict(schema=MEASURE_SCHEMA, kind='moving-radial-boundary-relative-flux',
            interval_id=interval.interval_id, boundary_id=boundary_id, boundary_kind=boundary['kind'],
            side=side, plate_id=plate_id, physical_cell_id=physical_cell_id,
            voxel_id=None if voxel is None else voxel.cell_id, source_key=source_key,
            source_cones=None if cones is None else [[_store_vec(p) for p in cone] for cone in cones],
            radial_layer=layer.record(), supply_definition=boundary['supplies'].get(side),
            sink_definition=boundary['sink'], start_time_s=record['start_time_s'], end_time_s=record['end_time_s'],
            inward_volume_bounds_m3=[_qtext(q) for q in totals[0]],
            outward_volume_bounds_m3=[_qtext(q) for q in totals[1]], segments=segments,
            max_width_m3=_qtext(width), max_leaves_per_segment=max_leaves, met=all_met,
            work_units=arena.work_units, relative_angular_velocity_rad_s=_store_vec(relative),
            authority='physical relative wall flux only; actual finite supply/debit/export remains with material owner')
    return _issue(DifferentialMeasure, result, budget)


def _constraint_pose(constraint, a, b, level, arena, *, _validate_only=False):
    """Enclose an oriented halfspace, permitting an exact positive rescaling.

    A homogeneous moving edge may have a constant oriented plane even when
    its cross-product magnitude varies. Its returned representative need not
    equal that cross product; all predicates use the same physical halfspace.

    Validation-only queries share every retained field read and scalar decoder.
    They omit arithmetic only for complete three-vector/two-ray inputs, whose
    decoded Fractions satisfy the pose operators' indexing/arithmetic contract.
    They return False for an unproven shape so the caller can pose the entire
    original constraint once, retaining its numerical refusals and work order.
    """
    if constraint['kind'] == 'snapshot-rotated':
        time = W._decode(constraint['snapshot_offset_s'])
        if _validate_only:
            nested = _constraint_pose(constraint['constraint'], time, time, level, arena,
                                      _validate_only=True)
            if not nested:
                return False
            omega = _load_vec(constraint['angular_velocity_rad_s'])
            return len(omega) == 3
        normal, old_error, offset = _constraint_pose(constraint['constraint'], time, time, level, arena)
        omega = _load_vec(constraint['angular_velocity_rad_s'])
        # exp(0*skew(omega)) is exactly the identity. Read/decode both the
        # complete nested constraint and this velocity before using it.
        # Restrict the shortcut to the original arithmetic's proven shape;
        # malformed or nonstandard inputs retain the numerical refusal path.
        if (type(a) is Q and type(b) is Q and a == b == 0
                and type(level) is int and level >= 0
                and type(normal) is tuple and len(normal) == len(omega) == 3
                and all(type(q) in (int, Q) for q in (*normal, *omega))):
            return normal, old_error, offset
        normal, error = W._pose_vector(normal, omega, a, b, level, arena)
        return normal, old_error+error, offset
    if constraint['kind'] == 'moving-ray-edge':
        values = []
        directions, rotations = [], []
        for ray in constraint['rays']:
            direction = _load_vec(ray['direction'])
            omega = _load_vec(ray['angular_velocity_rad_s'])
            prior = _history(ray.get('prior_rotations', ()))
            if _validate_only and (len(direction) != 3 or len(omega) != 3 or
                                   any(len(w) != 3 for w, _ in prior)):
                return False
            directions.append(direction)
            rotations.extend(w for w, _ in prior)
            rotations.append(omega)
            if not _validate_only:
                values.append(_ray_box(direction, omega, a, b, level, arena, prior)[:2])
        if _validate_only:
            return len(directions) == 2
        (p, ep), (q, eq) = values
        normal = O._cross(p, q)
        error = ep*sum(map(abs, q))+eq*sum(map(abs, p))+ep*eq
        axis = next((w for w in rotations if any(w)), None)
        if axis is not None:
            with V._work((*normal, error, *(x for v in (*directions, *rotations) for x in v)),
                         arena.resource):
                arena.work(64+32*len(rotations))
                if (all(not any(O._cross(axis, w)) for w in rotations) and
                        all(not O._dot(axis, direction) for direction in directions)):
                    # Every exact ray stays in axis-perp, so its cross product
                    # is axial. The existing enclosure certifies its sign for
                    # the WHOLE [a,b], including all actual prior rotations.
                    # Strict separation excludes zero/reversal; no epsilon.
                    centre = O._dot(axis, normal)
                    padding = error*sum(map(abs, axis))
                    if centre > padding:
                        return axis, Q(0), Q(0)
                    if centre < -padding:
                        return tuple(-x for x in axis), Q(0), Q(0)
        return normal, error, Q(0)
    if constraint['kind'] == 'rotated-normal':
        normal = _load_vec(constraint['normal'])
        omega = _load_vec(constraint['angular_velocity_rad_s'])
        if _validate_only:
            return len(normal) == len(omega) == 3
        normal, error = W._pose_vector(normal, omega, a, b, level, arena)
        return normal, error, Q(0)
    if constraint['kind'] == 'fixed-plane':
        normal, error, offset = _load_vec(constraint['normal']), Q(0), W._decode(constraint['offset'])
        if _validate_only:
            return len(normal) == 3
        return normal, error, offset
    raise V.VolumeError('unknown physical differential constraint')


def _voxel_absolute_scale(cell):
    """Same sum of coordinate extrema used by the existing pose padding."""
    total = 0
    for origin, row in zip(cell.origin_m, cell.basis, strict=True):
        lower = origin + sum(b * (lo if b >= 0 else hi)
                             for b, lo, hi in zip(row, cell.lower_m, cell.upper_m, strict=True))
        upper = origin + sum(b * (hi if b >= 0 else lo)
                             for b, lo, hi in zip(row, cell.lower_m, cell.upper_m, strict=True))
        total += max(abs(lower), abs(upper))
    return total


def _literal_plane(literal, posed, cell, inner, scale=None):
    name, sign = literal
    normal, error, offset = posed[name]
    pad = Q(0)
    if error:
        # The padding scale depends on the cell alone. A caller clipping many
        # literals of one cell passes a list to hold that exact value once.
        if scale:
            absolute = scale[0]
        else:
            absolute = _voxel_absolute_scale(cell)
            if scale is not None:
                scale.append(absolute)
        pad = (1 if inner else -1)*error*absolute
    # All support literals use sign*(normal.x-offset)>=0; B clips <=.
    return (*( -sign*q for q in normal), -sign*offset-pad)


def _rigid_plane_path(constraint):
    """Exact coaxial homogeneous-plane identity, never a fitted pose.

    Commuting rotations add their rotation vectors. An axial ray is fixed,
    so a pole-to-moving-ray edge follows the latter even when the two stored
    ray velocities differ. Noncommuting or genuinely deforming edges return
    None and retain their ordinary certified enclosure.
    """
    zero = (Q(0),)*3
    kind = constraint['kind']
    if kind == 'rotated-normal':
        result = (_load_vec(constraint['normal']), zero,
                  _load_vec(constraint['angular_velocity_rad_s']))
    elif kind == 'fixed-plane':
        if W._decode(constraint['offset']):
            return None
        result = (_load_vec(constraint['normal']), zero, zero)
    elif kind == 'snapshot-rotated':
        old = _rigid_plane_path(constraint['constraint'])
        if old is None:
            return None
        normal, theta, velocity = old
        offset = W._decode(constraint['snapshot_offset_s'])
        theta = tuple(a+offset*b for a, b in zip(theta, velocity))
        omega = _load_vec(constraint['angular_velocity_rad_s'])
        if any(O._cross(theta, omega)):
            return None
        result = normal, theta, omega
    elif kind == 'moving-ray-edge':
        rays = constraint['rays']
        directions = [_load_vec(ray['direction']) for ray in rays]
        paths = []
        vectors = []
        for ray in rays:
            history = _history(ray.get('prior_rotations', ()))
            omega = _load_vec(ray['angular_velocity_rad_s'])
            theta = tuple(sum((w[j]*dt for w, dt in history), Q(0)) for j in range(3))
            paths.append((theta, omega))
            vectors.extend(w for w, _ in history)
            vectors.append(omega)
        axis = next((v for v in vectors if any(v)), zero)
        if any(any(O._cross(axis, v)) for v in vectors):
            return None
        mobile = [i for i, d in enumerate(directions) if not any(axis) or any(O._cross(axis, d))]
        if len(mobile) == 2 and paths[0] != paths[1]:
            return None
        theta, omega = paths[mobile[0]] if mobile else (zero, zero)
        result = O._cross(*directions), theta, omega
    else:
        return None
    normal, theta, omega = result
    if not any(normal):
        return None
    if not any(O._cross(normal, theta)) and not any(O._cross(normal, omega)):
        theta = omega = zero
    return normal, theta, omega


def _plane_identity(constraint):
    path = _rigid_plane_path(constraint)
    if path is None:
        return None
    normal, theta, omega = path
    first = next(q for q in normal if q)
    return (tuple(q/first for q in normal), theta, omega), (1 if first > 0 else -1)


def _interface_identity(constraint):
    identity = _plane_identity(constraint)
    if identity is not None:
        return ('rigid', identity[0]), identity[1]
    if constraint['kind'] == 'moving-ray-edge':
        forward = _encoded(constraint['rays'])
        reverse = _encoded(list(reversed(constraint['rays'])))
        return ('deforming-ray-edge', min(forward, reverse)), (1 if forward <= reverse else -1)
    return None


def _material_plane(constraint, omega):
    """Does the plane move with the material, so that nothing crosses it?

    A carried chart is a snapshot of an accepted boundary advected rigidly
    with the material rate: a material surface by construction, whatever
    literal it was a snapshot of. A fan edge whose rays have different
    carriers has no symbolic rigid path, but its snapshot at one instant is
    a definite plane, and the path decides nothing about materiality.
    """
    if (constraint['kind'] == 'snapshot-rotated' and
            _load_vec(constraint['angular_velocity_rad_s']) == tuple(omega)):
        return True
    path = _rigid_plane_path(constraint)
    if path is None:
        return False
    normal, theta, velocity = path
    return velocity == omega or (not any(O._cross(normal, theta)) and
        not any(O._cross(normal, velocity)) and not any(O._cross(normal, omega)))


def _consistent_literals(literals, identities):
    """Remove exact duplicate inequalities; None proves zero 3-D measure."""
    seen, result = {}, []
    for name, sign in literals:
        identity = identities[name]
        if identity is None:
            result.append((name, sign))
            continue
        key, orientation = identity
        orientation *= sign
        if key in seen:
            if seen[key] != orientation:
                return None
            continue
        seen[key] = orientation
        result.append((name, sign))
    return tuple(result)


def _material_frame_constraint(constraint, omega):
    """Change a coaxial angular predicate's frame, not its physical support."""
    kind = constraint['kind']
    if kind in ('snapshot-rotated', 'rotated-normal'):
        velocity = _load_vec(constraint['angular_velocity_rad_s'])
        if any(O._cross(velocity, omega)):
            return None
        return dict(constraint, angular_velocity_rad_s=_store_vec(tuple(a-b for a, b in zip(velocity, omega))))
    if kind == 'moving-ray-edge':
        rays = []
        for ray in constraint['rays']:
            velocity = _load_vec(ray['angular_velocity_rad_s'])
            if any(O._cross(velocity, omega)):
                return None
            rays.append(dict(ray, angular_velocity_rad_s=_store_vec(tuple(a-b for a, b in zip(velocity, omega)))))
        return dict(constraint, rays=rays)
    return None


def _angular_possible(literals, constraints, omega, duration, arena, cache, owner_rays=()):
    """Prove zero angular measure in a material-corotating frame.

    Independent world-frame pose errors otherwise turn a shared moving vertex
    into many spurious possible overlaps. The frame change is exact for the
    declared coaxial paths. A homogeneous cone has positive volume somewhere
    iff it has positive volume inside the unit cube; no voxel is approximated
    by that cube. An unresolved/noncoaxial case is retained.
    """
    angular = []
    for name, sign in literals:
        original = constraints[name]
        if original['kind'] == 'fixed-plane':
            continue
        transformed = _material_frame_constraint(original, omega)
        if transformed is None:
            return True
        angular.append((transformed, sign))
    key = tuple((_encoded(value), sign) for value, sign in angular)
    entries, owner = cache if cache is not None else ({}, arena)
    if key in entries:
        return entries[key]
    if any(any(O._cross(_load_vec(ray['angular_velocity_rad_s']), omega)) for ray in owner_rays):
        return True
    with _PartitionScratch(owner) as scratch:
        posed = tuple((_constraint_pose(value, Q(0), duration, 0, scratch), sign) for value, sign in angular)
        # The owner triangle is the positive cone of its actual three rays.
        # A separating literal excludes that entire cone if all three exact
        # ray/plane dot products have nonpositive certified upper bounds.
        # This cheap proof precedes polyhedral clipping, retaining tangencies
        # as zero positive volume, never comparing with a numerical epsilon.
        generators = tuple(_ray_box(_load_vec(ray['direction']),
            tuple(a-b for a, b in zip(_load_vec(ray['angular_velocity_rad_s']), omega)),
            Q(0), duration, 0, scratch, _history(ray.get('prior_rotations', ())))[:2] for ray in owner_rays)
        separated = False
        for (normal, error, offset), sign in posed:
            if generators and not offset and all(sign*O._dot(normal, point)+
                error*sum(map(abs, point))+point_error*sum(map(abs, normal))+error*point_error <= 0
                for point, point_error in generators):
                separated = True
                break
        scratch.work(8*len(posed)*len(generators))
        cube = V.CartesianCell((-1, -1, -1), (1, 1, 1), budget=owner.resource)
        # One exact kernel from the box to the sign of the volume; only that
        # sign leaves (integration_volume_bounds._resident).
        K = B._resident()
        poly = () if separated else K._owned_box(cube, scratch)
        for (normal, error, offset), sign in posed:
            if not poly:
                break
            if offset:
                return True
            poly = K._clip(poly, K._plane((*(-sign*q for q in normal), 3*error)), scratch)
            if not poly:
                break
        result = bool(poly) and K._volume(poly, scratch) > 0
    if cache is not None:
        owner.stack.enter_context(owner.resource.reserve(128+sum(64+2*len(k) for k, _ in key),
                                                         category='differential-angular-proof-cache'))
        entries[key] = result
    return result


def _merged_start_fans(record, fans, rays, budget):
    """Lossless convex unions of conforming fans with a shared exact pose.

    Internal diagonals do not define physical birth. Cancel them only after
    the existing exact union proof certifies identical coverage, convexity and
    no hole. Different accumulated poses are never merged using rounded rays.
    """
    rings = [(tuple(fan), (i,)) for i, fan in enumerate(fans)]
    failed = set()
    with budget.reserve(65536+128*len(fans)**2, category='differential-start-fan-union'):
        while True:
            edges, pairs = {}, set()
            for i, (ring, _) in enumerate(rings):
                for a, b in zip(ring, ring[1:]+ring[:1]):
                    if (b, a) in edges:
                        pairs.add((edges[b, a], i))
                    edges[a, b] = i
            merged = False
            for i, j in sorted(pairs):
                left, li = rings[i]; right, ri = rings[j]
                identity = left, right
                if identity in failed:
                    continue
                names = set(left+right)
                histories = {_encoded(record['rays'][name].get('prior_rotations', [])) for name in names}
                if len(histories) != 1:
                    failed.add(identity); continue
                points = {name: _ray_parts(rays[name])[0] for name in names}
                try:
                    union = V.convex_cone_union((tuple(points[n] for n in left),
                                                tuple(points[n] for n in right)), budget=budget)
                except V.VolumeError:
                    failed.add(identity); continue
                lookup = {_scale_ray(p): name for name, p in points.items()}
                joined = tuple(lookup[_scale_ray(p)] for p in union)
                rings[i] = joined, tuple(sorted(li+ri))
                del rings[j]
                merged = True
                break
            if not merged:
                break
    return tuple(rings)


class _PartitionScratch(B._Arena):
    """Recyclable live clipping scratch; finite work stays on the parent."""
    def __init__(self, parent):
        super().__init__(parent.resource)
        self.parent = parent

    def work(self, count):
        self.parent.work(count)
        self.work_units += count


def partition_physical_support(interval, plate_id, layer, voxel, *, source_key,
                               kind='inherited', source_cones=None, exclusion_cells=(),
                               max_components, budget, _owner_face_ids=None, _source_chart=None,
                               _start_fans=None, _owner_fan_indices=None, _pose_cache=None,
                               _angular_cache=None, _interval_record=None, _owned_result=False):
    """Conforming convex angular pieces valid over the WHOLE interval.

    A birth domain is current ownership minus the actual advected start owner.
    The complement is the disjoint union of all OTHER start owners, transported
    by this target material rotation; the complete spherical fan partition
    proves that identity. Internal triangulation is never Boolean-subtracted.
    Paths identify all-time cells, including those with zero endpoint volume.
    Only a provably zero outer polyhedron is pruned. No positive sliver, thermal
    surrogate or endpoint sample decides physical support. The finite work
    ceiling is caller-supplied and does not authorise material culling.
    """
    record, omega, rays, fans = _unpack(interval, plate_id, budget, _record=_interval_record)
    if _owner_face_ids is not None:
        fans = tuple(tuple(row['ray_ids']) for row in record['ownership_fans']
            if row['plate_id'] == plate_id and row['face_id'] in _owner_face_ids)
    static = type(interval) is CurrentGeometry
    if static and kind == 'birth':
        raise V.VolumeError('instantaneous geometry cannot author future birth support')
    identity_id = interval.geometry_id if static else interval.interval_id
    if type(layer) is not V.RadialLayer or layer.radius_m != W._decode(record['radius_m']) or type(voxel) is not V.CartesianCell:
        raise V.VolumeError('physical radial layer and actual fixed voxel required')
    if kind not in ('inherited', 'birth', 'plate'):
        raise V.VolumeError('physical support kind must be inherited, birth or plate')
    if type(max_components) is not int or max_components < 1:
        raise V.VolumeError('explicit positive finite component work ceiling required')
    if kind == 'inherited' and not source_cones and _source_chart is None:
        raise V.VolumeError('inherited components need their actual source cone geometry')
    if kind != 'inherited' and source_cones is not None:
        raise V.VolumeError('birth/plate support must not masquerade as an old material patch')
    if type(exclusion_cells) not in (tuple, list) or any(type(c) is not V.CartesianCell for c in exclusion_cells):
        raise V.VolumeError('excluded native/reservoir supports must be actual CartesianCells')
    if _source_chart is not None and (kind != 'inherited' or source_cones is not None):
        raise V.VolumeError('carried source charts cannot be replaced by fresh cones or birth support')
    cones = (None,) if source_cones is None else tuple(V.convex_cone_union((cone,), budget=budget) for cone in source_cones)
    constraints, initial, subtract = {}, [], []
    def fan_names(fan, prefix, advected_start=False):
        names = []
        for first, second in zip(fan, fan[1:]+fan[:1]):
            name = prefix+':'+first+'>'+second
            if advected_start:
                if any(_ray_parts(rays[name])[2] for name in (first, second)):
                    constraint = dict(kind='snapshot-rotated', snapshot_offset_s=_qtext(Q(0)),
                        constraint=dict(kind='moving-ray-edge', rays=[record['rays'][first], record['rays'][second]]),
                        angular_velocity_rad_s=_store_vec(omega))
                else:
                    constraint = dict(kind='rotated-normal', normal=_store_vec(O._cross(rays[first][0], rays[second][0])),
                                      angular_velocity_rad_s=_store_vec(omega))
            else:
                constraint = dict(kind='moving-ray-edge', rays=[record['rays'][first], record['rays'][second]])
            constraints[name] = constraint
            names.append(name)
        return tuple(names)
    selected_fans = range(len(fans)) if _owner_fan_indices is None else _owner_fan_indices
    owned_groups = {i: fan_names(fans[i], 'owner') for i in selected_fans}
    start_groups, outside_groups = (), ()
    if kind == 'birth':
        other_fans = tuple(tuple(row['ray_ids']) for row in record['ownership_fans'] if row['plate_id'] != plate_id)
        start_groups = _merged_start_fans(record, other_fans, rays, budget) if _start_fans is None else _start_fans
        outside_groups = tuple(fan_names(fan, 'birth-outside-owner', True) for fan, _ in start_groups)
    for j, cone in enumerate(cones):
        names, carried = [], ()
        if _source_chart is not None:
            for name, value in _source_chart['constraints'].items():
                constraints['carried:'+name] = value
            carried = tuple(('carried:'+name, sign) for name, sign in _source_chart['literals'])
        if cone is not None:
            for k, normal in enumerate(V._cone_normals(cone)):
                name = 'source:%d:%d' % (j, k)
                constraints[name] = dict(kind='rotated-normal', normal=_store_vec(normal), angular_velocity_rad_s=_store_vec(omega))
                names.append(name)
        for i, owner in owned_groups.items():
            # If all three actual ray paths use this material velocity, this
            # whole current fan IS its advected start fan. Its birth difference
            # is identically empty, including any accumulated prior pose.
            if kind == 'birth' and all(_ray_parts(rays[name])[1] == omega for name in fans[i]):
                continue
            if kind == 'birth':
                for k, outside in enumerate(outside_groups):
                    initial.append((('owner-fan', i, 'advected-other-owner', k),
                                    tuple((name, 1) for name in (*owner, *outside))))
            else:
                initial.append((('owner-fan', i, 'source-cone', j),
                                (*carried, *((name, 1) for name in (*owner, *names)))))
    for i, cell in enumerate(exclusion_cells):
        group = []
        for j, plane in enumerate(O._box_planes(cell)):
            name = 'excluded:%s:%d' % (cell.cell_id, j)
            constraints[name] = dict(kind='fixed-plane', normal=_store_vec(tuple(-q for q in plane[:3])), offset=_qtext(-plane[3]))
            group.append(name)
        subtract.append(tuple(group))
    duration = W._decode(record['duration_s'])
    with B._Arena(budget) as arena:
        identities = {name: _plane_identity(value) for name, value in constraints.items()}
        arena.keep(tuple(q for item in identities.values() if item is not None
                         for vector in item[0] for q in vector), objects=2*len(identities))
        posed = {name: _cached_constraint_pose(value, duration, arena, _pose_cache) for name, value in constraints.items()}
        vertices = voxel._vertices()
        absolute = sum(max(abs(p[j]) for p in vertices) for j in range(3))
        outer_planes = {(name, sign): (*(-sign*q for q in normal), -sign*offset+error*absolute)
                        for name, (normal, error, offset) in posed.items() for sign in (-1, 1)}
        arena.work((16+8*len(vertices))*len(outer_planes))
        impossible = {literal for literal, plane in outer_planes.items()
                      if (any(plane[:3]) and min(O._dot(plane[:3], p)-plane[3] for p in vertices) >= 0)
                      or (not any(plane[:3]) and plane[3] < 0)}
        # The immutable box and exact halfspace broad phase are shared across
        # every candidate. This is only a proof of zero positive volume; no
        # small magnitude, endpoint sample or approximate hull is consulted.
        # One exact kernel holds every integration polyhedron of this
        # partition; none is returned, stored or encoded.
        K = B._resident()
        base_poly = K._owned_box(voxel, arena)
        parts = []
        for path, literals in initial:
            literals = _consistent_literals(literals, identities)
            if literals is None:
                continue
            if any(literal in impossible for literal in literals):
                continue
            if not _angular_possible(literals, constraints, omega, duration, arena, _angular_cache,
                                     tuple(record['rays'][name] for name in fans[path[1]])):
                continue
            live = ExitStack()
            try:
                with _PartitionScratch(arena) as scratch:
                    poly = base_poly
                    for literal in literals:
                        poly = K._clip(poly, K._plane(outer_planes[literal]), scratch)
                        if not poly:
                            break
                    if not poly or K._volume(poly, scratch) <= 0:
                        continue
                    live = scratch.stack.pop_all()
                local_parts = [(path, literals, poly)]
                poly = ()
                order = list(range(len(subtract)))
                for group_index in order:
                    group, after = subtract[group_index], []
                    with _PartitionScratch(arena) as scratch:
                        for local_path, local_literals, local_poly in local_parts:
                            inside, prefix = local_poly, []
                            for index, name in enumerate(group):
                                outside = K._clip(inside, K._plane(outer_planes[name, -1]), scratch)
                                if outside and K._volume(outside, scratch) > 0:
                                    after.append(((*local_path, 'outside', group_index, index),
                                                  (*local_literals, *prefix, (name, -1)), outside))
                                    if len(parts)+len(after) > max_components:
                                        raise V.VolumeError('physical Boolean partition exceeds the declared component work limit; nothing culled')
                                # Inner/outer strip uncertainty remains intact.
                                inside = K._clip(inside, K._plane(outer_planes[name, 1]), scratch)
                                prefix.append((name, 1))
                                if not inside:
                                    break
                        # Some clips return their unchanged input. Re-account
                        # the actual surviving output set, not just newly
                        # allocated intersections, before releasing old input.
                        values = tuple(v for _, _, p in after for point in K._points(p) for v in point)
                        size = 1024+128*len(values)+128*sum(sum(map(len, p)) for _, _, p in after)
                        size += 4*sum((K._bits(v)+7)//8 for v in values)
                        extra = K._retained_extra(p for _, _, p in after)
                        # One unit: a refused native surcharge releases the
                        # re-charge it accompanies before the error leaves.
                        with ExitStack() as pending:
                            pending.enter_context(budget.reserve(size, category='differential-partition-live'))
                            if extra:
                                pending.enter_context(budget.reserve(extra, category=B.NATIVE_RETAINED))
                            next_live = pending.pop_all()
                        del values
                    # Keep the current input while clipping. Only then release
                    # the preceding stage's discarded integration polyhedra.
                    local_parts = after
                    local_poly = inside = outside = ()
                    live.close(); live = next_live
                    if not local_parts:
                        break
                for local_path, local_literals, _ in local_parts:
                    arena.keep((), objects=len(local_path)+len(local_literals))
                    parts.append((local_path, local_literals, None))
                local_parts = after = ()
                _ = None
            except MemoryLimitError as exc:
                # No locals() snapshot: it would tie this frame, and the last
                # polyhedra with it, to the error until a cyclic collection.
                try:
                    reported = inside
                except NameError:
                    reported = poly
                points = K._points(reported)
                raise MemoryLimitError(str(exc)+'; differential partition '+str(dict(kind=kind,
                    plate=plate_id, voxel_id=voxel.cell_id, start_union_groups=len(start_groups),
                    work_units=arena.work_units, vertices=len(points),
                    coordinate_bits=sum(K._bits(v) for p in points for v in p),
                    live_reserved_bytes=budget.reserved_bytes))) from exc
            finally:
                live.close()
        components = []
        for path, literals, _ in parts:
            identity = dict(kind=kind, plate_id=plate_id, source_key=source_key,
                voxel_id=voxel.cell_id, layer_id=layer.layer_id, partition_path=path)
            # New birth lineage intentionally includes its actual birth interval.
            if kind == 'birth':
                identity['birth_interval_id'] = identity_id
            components.append(dict(logical_cell_id=hashlib.sha256(_encoded(identity)).hexdigest(),
                partition_path=path, owner_ray_ids=list(fans[path[1]]), constraints=literals))
        if not static:
            # Growth successor (a), new intervals only: store only the
            # constraints some component literal names (none other is read).
            _used = {name for part in components for name, _ in part['constraints']}
            constraints = {name: value for name, value in constraints.items() if name in _used}
            del _used
        result = dict(schema='atlas.differential-physical-support.v1', interval_id=None if static else identity_id,
            kind=kind, plate_id=plate_id, source_key=source_key, radial_layer=layer.record(), voxel=voxel.record(),
            exclusion_ids=[c.cell_id for c in exclusion_cells], exclusion_cells=[c.record() for c in exclusion_cells],
            material_angular_velocity_rad_s=_store_vec(omega), constraints=constraints, components=components,
            max_components=max_components, work_units=arena.work_units, start_time_s=record['start_time_s'],
            end_time_s=record['end_time_s'], duration_s=record['duration_s'],
            coverage='exact ordered Boolean partition; only zero all-time outer volumes pruned')
        if kind == 'birth':
            result['birth_start_union'] = dict(original_fans=sum(row['plate_id'] != plate_id for row in record['ownership_fans']),
                convex_groups=[dict(ray_ids=ring, original_fan_indices=members) for ring, members in start_groups],
                method='complement equals disjoint OTHER owners of complete start sphere; exact convex unions with shared retained pose only')
        if static:
            result.update(current_geometry_id=identity_id, network_id=record['network_id'],
                physical_velocity='not supplied, not inferred')
        if _owned_result:
            from live_partition_patch import owned_support
            return owned_support(result, budget)
    return _issue(DifferentialSupport, result, budget)


def _cached_constraint_pose(value, duration, arena, cache):
    if cache is None:
        return _constraint_pose(value, Q(0), duration, 0, arena)
    entries, owner = cache
    key = _encoded(value)
    if key not in entries:
        result = _constraint_pose(value, Q(0), duration, 0, owner)
        owner.keep((*result[0], result[1], result[2]), objects=1)
        owner.stack.enter_context(owner.resource.reserve(128+2*len(key), category='differential-shared-pose-key'))
        entries[key] = result
    return entries[key]


def partition_current_support(current, plate_id, layer, voxel, *, source_key,
                              source_cones, exclusion_cells=(), max_components, budget,
                              _owner_face_ids=None):
    """Actual instantaneous source chart; no future motion or birth assumed."""
    if type(current) is not CurrentGeometry:
        raise V.VolumeError('issued current geometry required, not an invented future interval')
    return partition_physical_support(current, plate_id, layer, voxel, source_key=source_key,
        source_cones=source_cones, exclusion_cells=exclusion_cells, max_components=max_components, budget=budget,
        _owner_face_ids=_owner_face_ids)


def _initial_partition_sources(funding, sphere, *, budget):
    """Prove exact initial owner coverage, not merely closed stock/area sums."""
    from . import integration_support as U
    from . import integration_collar_geometry as F
    if type(funding) is not F.FullCellFunding or funding._resource is not budget:
        raise V.VolumeError('actual funded source on the shared budget required')
    r = funding.descriptor()
    if r['source']['sphere_state_id'] != sphere.state_id:
        raise V.VolumeError('initial partition must bind the actual funded sphere')
    network = sphere.network
    plates = tuple(r.get('initial_source_plate_ids', network.plate_ids))
    # A partial owner domain needs real external boundary conditions. This
    # closed initial family never invents them or fills an omitted plate.
    if tuple(sorted(plates)) != tuple(network.plate_ids):
        raise V.VolumeError('closed differential partition requires the complete declared owner domain')
    if any(tuple(network.frames[p].quaternion) not in ((1., 0., 0., 0.), (-1., 0., 0., 0.)) for p in plates):
        raise V.VolumeError('initial material cone declaration needs the exact source frame; nonidentity frame not inferred')
    material = U.required(sphere.material)
    patches = {p.patch_id: p for p in material.patches}
    face_plate = {face.face_id: face.plate_id for face in network.faces}
    rows = {(row['patch_id'], row['sublayer']): row for row in r['exterior_remainder']}
    keys = tuple(tuple(k) for k in r['component_keys'])
    if len(set(keys)) != len(keys) or not set(keys).issubset(rows):
        raise V.VolumeError('funded source component keys are duplicated or have no actual remainder')
    selected = {key[0] for key in keys}
    if selected != set(patches):
        raise V.VolumeError('funded source omits actual owner patch components')
    with U.geometry_workspace(budget):
        shapes = T._Shapes(network)
        for face in network.faces:
            held = tuple(cell for p in material.patches if p.face_id == face.face_id for cell in p.cells)
            full = U.cells_of_rings(shapes.rings(network.face_ids.index(face.face_id)))
            if U.difference(full, held) or U.difference(held, full):
                raise V.VolumeError('funded material footprints do not exactly cover the declared owner face')
        spans, layers, sources = {}, {}, []
        for patch_id in sorted(selected):
            declared = sorted((k for k in keys if k[0] == patch_id), key=lambda k: k[1])
            physical = []
            for key in declared:
                g = rows[key]['radial_layer']
                layer = V.RadialLayer(*(W._decode(g[name]) for name in
                    ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
                if layer.radius_m != Q(network.sphere.radius_m):
                    raise V.VolumeError('source radial layer belongs to another sphere')
                physical.append((key, layer))
            physical.sort(key=lambda item: item[1].top_depth_m)
            if any(a.bottom_depth_m != b.top_depth_m for (_, a), (_, b) in zip(physical, physical[1:])):
                raise V.VolumeError('funded source radial intervals have a gap or overlap')
            spans[patch_id] = (physical[0][1].top_depth_m, physical[-1][1].bottom_depth_m)
            layers[patch_id] = physical
        if len(set(spans.values())) != 1:
            raise V.VolumeError('closed owner partition requires one explicitly common radial domain')
        cuts = sorted({depth for physical in layers.values() for _, g in physical
                       for depth in (g.top_depth_m, g.bottom_depth_m)})
        for patch_id, physical in sorted(layers.items()):
            patch = patches[patch_id]
            try:
                cones = (V.convex_cone_union(patch.cells, budget=budget),)
            except V.VolumeError:
                cones = patch.cells
            for key, layer in physical:
                for band, (a, b) in enumerate(zip(cuts, cuts[1:])):
                    if layer.top_depth_m <= a < b <= layer.bottom_depth_m:
                        g = V.RadialLayer(layer.radius_m, a, b, budget=budget)
                        for chart, cone in enumerate(cones):
                            row = dict(source_key=list(key), plate_id=face_plate[patch.face_id], source_face_id=patch.face_id,
                                radial_band=band, chart=chart, radial_layer=g.record(),
                                original_cone=[_store_vec(tuple(Q(q) for q in point)) for point in cone])
                            row['source_chart_id'] = W._hash(row)
                            sources.append(row)
    return r, sources


def prepare_differential_partition(funding, sphere, geometry, collar, *,
                                   grid_lines, max_components, budget, compact_scope=None):
    """Issue the complete INITIAL static partition and native contact mapping.

    Coverage follows exact source-face set difference, common radial interval,
    conforming owner fans and exact Cartesian adjacency. A face area sum is not
    used as a substitute for disjoint coverage. All-time continuation/births
    require the corresponding carried partition issuer, not this fresh route.
    """
    from .regional_collar3d import PreparedRegionalCollar3D
    if (type(geometry) is not CurrentGeometry or geometry._resource is not budget or
            type(collar) is not PreparedRegionalCollar3D or collar._budget is not budget):
        raise V.VolumeError('initial issued current geometry, actual collar and shared budget required')
    current = geometry.record()
    if current.get('accepted_interval_id') is not None or current['network_id'] != sphere.network.network_id:
        raise V.VolumeError('continued source fields require their accepted partition; fresh funding cannot reseed them')
    if type(max_components) is not int or max_components < 1:
        raise V.VolumeError('explicit finite component count required')
    original, regions = _initial_partition_sources(funding, sphere, budget=budget)
    if original['collar_plan_id'] != collar.plan_id or Q(original['time_s']) != W._decode(current['time_s']):
        raise V.VolumeError('initial collar, funding and actual geometry clocks differ')
    del current
    return _assemble_partition(funding, sphere, geometry, collar, original, regions,
        grid_lines=grid_lines, max_components=max_components, budget=budget, compact_scope=compact_scope)


def _assemble_partition(funding, sphere, geometry, collar, original, regions, *,
                        grid_lines, max_components, budget, parent_partition=None,
                        compact_scope=None, _final_fields=None):
    from live_partition_patch import resolve_scope, SupportBatch, finish
    compact_scope = resolve_scope(budget, compact_scope, parent_partition)
    current = geometry.record()
    static = type(geometry) is CurrentGeometry
    if type(grid_lines) is not tuple or len(grid_lines) != 3 or any(type(a) is not tuple or len(a) < 2 for a in grid_lines):
        raise V.VolumeError('three explicit Cartesian line tuples required')
    lines = tuple(tuple(map(W._q, axis)) for axis in grid_lines)
    if any(a >= b for line in lines for a, b in zip(line, line[1:])):
        raise V.VolumeError('partition Cartesian lines must increase strictly')
    native = collar.cell_geometries()
    base = native[0]
    origin, basis = base.origin_m, base.basis
    if any(c.origin_m != origin or c.basis != basis for c in native):
        raise V.VolumeError('partition needs the actual common native Cartesian chart')
    excluded = tuple(V.CartesianCell.from_record(row, budget=budget)
                     for row in original.get('excluded_static_cells', ()))
    for axis in range(3):
        values = {q for c in (*native, *excluded) for q in (c.lower_m[axis], c.upper_m[axis])}
        if not values.issubset(lines[axis]):
            raise V.VolumeError('partition grid omits an actual native or finite-compartment face')
    if any(c.origin_m != origin or c.basis != basis for c in excluded):
        raise V.VolumeError('fixed exclusions require the same exact partition chart')
    radius = Q(sphere.network.sphere.radius_m)
    translation = tuple(sum(basis[k][j]*origin[k] for k in range(3)) for j in range(3))
    if any(line[0] > -radius-t or line[-1] < radius-t for line, t in zip(lines, translation)):
        raise V.VolumeError('partition grid does not cover the complete funded radial domain')
    grid_id = W._hash(dict(lines=[list(map(_qtext, axis)) for axis in lines],
        origin=_store_vec(origin), basis=[_store_vec(row) for row in basis]))
    shape = tuple(len(axis)-1 for axis in lines)
    prepared_regions = []
    for region in regions:
        g = region['radial_layer']
        layer = V.RadialLayer(*(W._decode(g[k]) for k in ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
        cone = None if 'original_cone' not in region else tuple(_load_vec(p) for p in region['original_cone'])
        prepared_regions.append((region, layer, cone, None if cone is None else V._cone_normals(cone)))
    supports = [] if compact_scope is None else SupportBatch(compact_scope)
    from live_partition_patch import native_projection
    native_components = {}
    cells, by_voxel, native_voxels, excluded_voxels = {}, {}, {}, set()
    component_count = 0
    start_fans = {}
    for plate in sorted({r['plate_id'] for r in regions if r.get('kind') == 'birth'}):
        start_record, _, start_rays, _ = _unpack(geometry, plate, budget, _record=current)
        other_fans = tuple(tuple(row['ray_ids']) for row in start_record['ownership_fans'] if row['plate_id'] != plate)
        start_fans[plate] = _merged_start_fans(start_record, other_fans, start_rays, budget)
    # Count candidate storage/work before making the complete Cartesian grid.
    with budget.reserve(131072+math.prod(shape)*(256+64*len(regions)),
                        category='differential-partition-candidates'), B._Arena(budget) as arena:
        pose_cache = ({}, arena)
        angular_cache = ({}, arena)
        owner_planes = {}
        if not static:
            for plate in sorted({r['plate_id'] for r in regions}):
                _, _, _, fans = _unpack(geometry, plate, budget, _record=current)
                owner_planes[plate] = tuple(tuple(_cached_constraint_pose(dict(kind='moving-ray-edge',
                    rays=[current['rays'][a], current['rays'][b]]), W._decode(current['duration_s']), arena, pose_cache)
                    for a, b in zip(fan, fan[1:]+fan[:1])) for fan in fans)
        carried_planes = {}
        for region in regions:
            chart = region.get('source_constraint_chart')
            if chart is not None:
                carried_planes[region['source_chart_id']] = tuple((sign, *_cached_constraint_pose(
                    chart['constraints'][name], W._decode(current['duration_s']), arena, pose_cache))
                    for name, sign in chart['literals'])
        for at in product(*(range(n) for n in shape)):
            box = V.CartesianCell(tuple(lines[j][at[j]] for j in range(3)),
                tuple(lines[j][at[j]+1] for j in range(3)), origin, basis, budget=budget)
            cells[at] = box
            matches = [j for j, c in enumerate(native) if all(c.lower_m[k] <= box.lower_m[k] and
                       box.upper_m[k] <= c.upper_m[k] for k in range(3))]
            if matches:
                if len(matches) != 1:
                    raise V.VolumeError('native full cells overlap in partition')
                native_voxels[at] = matches[0]
                continue
            if any(all(c.lower_m[k] <= box.lower_m[k] and box.upper_m[k] <= c.upper_m[k] for k in range(3)) for c in excluded):
                excluded_voxels.add(at)
                continue
            radial_min, radial_max = box._radial_bounds()
            vertices = box._vertices()
            absolute = sum(max(abs(p[j]) for p in vertices) for j in range(3))
            arena.work((16+8*len(vertices))*sum(len(planes) for groups in owner_planes.values() for planes in groups))
            fan_candidates = {plate: tuple(i for i, planes in enumerate(groups) if not any(
                max(O._dot(normal, p)-offset for p in vertices)+error*absolute <= 0
                for normal, error, offset in planes)) for plate, groups in owner_planes.items()}
            for region, layer, cone, normals in prepared_regions:
                if radial_min >= layer.top_radius_m**2 or radial_max <= layer.bottom_radius_m**2:
                    continue
                # Convex linear predicates: an entire box outside one source
                # halfspace has exactly zero source volume. No angular sliver
                # or near-zero margin is removed by this broad phase.
                if static and normals is not None and any(max(O._dot(normal, p) for p in vertices) <= 0 for normal in normals):
                    continue
                if any(max(sign*(O._dot(normal, p)-offset) for p in vertices)+error*absolute <= 0
                       for sign, normal, error, offset in carried_planes.get(region['source_chart_id'], ())):
                    continue
                support = partition_physical_support(geometry, region['plate_id'], layer, box,
                    source_key=region['source_key'], source_cones=None if cone is None else (cone,),
                    kind=region.get('kind', 'inherited'), max_components=max_components, budget=budget,
                    _source_chart=region.get('source_constraint_chart'),
                    _start_fans=start_fans.get(region['plate_id']),
                    _owner_fan_indices=None if static else fan_candidates[region['plate_id']],
                    _pose_cache=pose_cache,
                    _angular_cache=angular_cache,
                    _interval_record=current,
                    _owner_face_ids=(region['source_face_id'],) if static else None,
                    _owned_result=True)
                row_owner = support
                row = support.value
                if not row['components']:
                    row = support = row_owner = None
                    continue
                row.update(grid_id=grid_id, voxel_index=list(at), radial_band=region['radial_band'],
                    chart=region['chart'], source_chart_id=region['source_chart_id'])
                if 'finite_stock_id' in region:
                    row.update(finite_stock_id=region['finite_stock_id'], stock_lineage=region['stock_lineage'],
                               birth_boundary_id=region['birth_boundary_id'], birth_side=region['birth_side'])
                for part in row['components']:
                    part['logical_cell_id'] = W._hash(dict(source_chart_id=region['source_chart_id'],
                        grid_id=grid_id, voxel_index=list(at), partition_path=part['partition_path']))
                    if not static:
                        parent_map = region.get('parent_cells', {})
                        old_key = ','.join(map(str, at))
                        parent_id = parent_map.get(old_key) if part['owner_ray_ids'] == region.get('parent_owner_ray_ids') else None
                        part['parent_cell_id'] = parent_id
                        part['start_identity'] = ('same physical component at accepted endpoint' if parent_id is not None else
                            'exact zero: distinct original ownership fans at the shared start' if region.get('kind') != 'birth' else
                            'exact zero: owner minus the identical start-owner union')
                support = (_issue(DifferentialSupport, row, budget) if compact_scope is None
                           else supports.issue(row))
                if compact_scope is None:
                    native_components[support.support_id] = native_projection(row, budget)
                supports.append(support)
                by_voxel.setdefault(at, []).append(support)
                component_count += len(row['components'])
                if component_count > max_components:
                    raise V.VolumeError('complete source partition exceeds explicit component count; nothing omitted')
                row = part = row_owner = None
        contacts = {}
        for at, flat in native_voxels.items():
            for axis, end in product(range(3), (0, 1)):
                neighbour = list(at); neighbour[axis] += 1 if end else -1; neighbour = tuple(neighbour)
                if neighbour in native_voxels:
                    continue
                box = native[flat]
                edge = (box.lower_m, box.upper_m)[end][axis]
                if (cells[at].lower_m, cells[at].upper_m)[end][axis] != edge:
                    raise V.VolumeError('unexpected native interior subdivision boundary')
                key = flat, axis, end
                group = contacts.setdefault(key, dict(native_index=flat, physical_cell_id=box.cell_id,
                    axis=axis, end=end, side='xyz'[axis]+str(end), contacts=[], excluded_subfaces=[]))
                if neighbour in excluded_voxels:
                    group['excluded_subfaces'].append(dict(voxel_index=list(neighbour),
                        axis=axis, end=1-end, physical_cell_id=cells[neighbour].cell_id))
                elif neighbour not in cells:
                    raise V.VolumeError('native face lies on unrepresented outer source domain')
                else:
                    for support in by_voxel.get(neighbour, ()):
                        for part in (native_components[support.support_id][0] if compact_scope is None
                                     else support.components):
                            group['contacts'].append(dict(support_id=support.support_id,
                                logical_cell_id=part['logical_cell_id'], voxel_index=list(neighbour), axis=axis, end=1-end))
        result = dict(schema='atlas.differential-partition.v1', scope='initial-current' if static else 'physical-interval',
            funding_id=funding.funding_id, source=original['source'], collar_plan_id=collar.plan_id,
            volume_map_id=original['volume_map_id'],
            current_geometry_id=geometry.geometry_id if static else None,
            network_id=current['network_id'] if static else current['parent_network_id'],
            start_time_s=current['start_time_s'], end_time_s=current['end_time_s'],
            component_keys=original['component_keys'], component_registry=original.get('component_registry'),
            grid_id=grid_id, grid_lines=[list(map(_qtext, line)) for line in lines],
            grid_origin_m=_store_vec(origin), grid_basis=[_store_vec(row) for row in basis],
            initial_source_plate_ids=list(sphere.network.plate_ids), source_regions=regions,
            excluded_static_cells=[c.record() for c in excluded],
            native_cells=[c.record() for c in native], support_ids=[s.support_id for s in supports],
            native_contacts=[contacts[k] for k in sorted(contacts)], max_components=max_components,
            coverage='exact source-face set differences; common radial domain; disjoint owner fans and aligned Cartesian subdivision',
            stocks='not allocated or reseeded by this geometric issuer')
        if not static:
            identities = [dict(parent_cell_id=p['parent_cell_id'], cell_id=p['logical_cell_id'])
                for support in supports
                for p in (native_components[support.support_id][0] if compact_scope is None else support.components)
                if p['parent_cell_id'] is not None]
            if len({r['parent_cell_id'] for r in identities}) != len(identities):
                raise V.VolumeError('a carried physical start cell has more than one identity child')
            result.update(interval_id=geometry.interval_id, parent_partition_id=parent_partition.partition_id,
                parent_network_id=current['parent_network_id'], endpoint_network_id=current['endpoint_network_id'],
                start_support_id=current['start_support_id'], end_support_id=current['end_support_id'],
                trajectory=current['trajectory'], trajectory_id=current['trajectory_id'],
                prior_trajectory_id=current['prior_trajectory_id'], identity_start_cells=identities,
                start_remap='exact accepted chart/fan/voxel identity; other siblings are geometric zero at the start')
        # The scientific work ends with the result dict on both branches.
        # Its candidate and arena charges stay booked until the block exits.
        del by_voxel, cells, native_voxels, excluded_voxels, prepared_regions
        del pose_cache, angular_cache, owner_planes, carried_planes, start_fans
        del current, native, excluded, contacts, native_components
        if _final_fields is not None:
            result.update(_final_fields)
        if compact_scope is None:
            issued = _issue(DifferentialPartition, result, budget)
            object.__setattr__(issued, '_supports', tuple(supports))
            return issued
        from live_partition_patch import owned_support
        holder = [owned_support(result, budget)]
        del result
    return finish(holder, supports, funding, collar, geometry, source=original['source'])


def _growth_chart_empty(region, old_time, grid, arena, budget):
    """Exact proof that a carried chart's cone has zero volume at the parent end instant.

    Returns the certificate name or None. See the growth_successor transform docstring.
    """
    chart = region.get('source_constraint_chart')
    if region.get('kind') != 'inherited' or chart is None:
        return None
    literals = tuple((name, sign) for name, sign in chart['literals'])
    wrapped = chart['constraints']
    rates = {_encoded(wrapped[name].get('angular_velocity_rad_s')) for name, _ in literals}
    if (not literals or len(rates) != 1 or
            any(wrapped[name].get('kind') != 'snapshot-rotated' or
                W._decode(wrapped[name]['snapshot_offset_s']) != old_time for name, _ in literals)):
        return None
    inner = {name: wrapped[name]['constraint'] for name, _ in literals}
    identities = {name: _plane_identity(wrapped[name]) for name, _ in literals}
    if _consistent_literals(literals, identities) is None:
        return 'C1-opposite-duplicate-rigid-plane'
    for level in (0, 24):
        if _common_ray_cone_zero_volume(literals, inner, old_time, old_time, level, arena) is not None:
            return 'C4-instant-common-ray-cone'
    g = region['radial_layer']
    layer = V.RadialLayer(*(W._decode(g[k]) for k in ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
    lower2, upper2 = layer.bottom_radius_m**2, layer.top_radius_m**2
    # Voxels holding parent pieces first: a positive chart fails fast there.
    first = set(region.get('parent_cells', {}))
    ordered = sorted(grid, key=lambda item: (','.join(map(str, item[0])) not in first, item[0]))
    for at, box in ordered:
        low, high = box._radial_bounds()
        if low >= upper2 or high <= lower2:
            continue
        zero = False
        for level in (0, 16, 32):
            detail = {}
            bounds, _, _, _ = _component_volume_certificate(layer, box, literals, inner, old_time, level,
                                                            arena, detail=detail)
            if bounds[1] == 0:
                zero = True
                break
            if not detail.get('angular_inner_empty'):
                break
        if not zero:
            return None
    return 'C5-every-voxel-instant-zero'


def _growth_drop_empty_charts(regions, step, old_time, grid_lines, collar, budget):
    """Growth successor (b): the carried regions minus charts proved empty (exact)."""
    if not regions:
        return regions
    base = collar.cell_geometries()[0]
    origin, basis = base.origin_m, base.basis
    lines = tuple(tuple(map(W._decode, axis)) for axis in grid_lines)
    radius = W._decode(step['radius_m'])
    translation = tuple(sum(basis[k][j]*origin[k] for k in range(3)) for j in range(3))
    if any(line[0] > -radius-t or line[-1] < radius-t for line, t in zip(lines, translation)):
        return regions   # coverage not proved here: drop nothing
    grid = [(at, V.CartesianCell(tuple(lines[j][at[j]] for j in range(3)),
                                 tuple(lines[j][at[j]+1] for j in range(3)), origin, basis, budget=budget))
            for at in product(*(range(len(a)-1) for a in lines))]
    kept = {}
    with B._Arena(budget) as arena:
        for key in sorted(regions):
            if _growth_chart_empty(regions[key], old_time, grid, arena, budget) is None:
                kept[key] = regions[key]
    return kept


def prepare_interval_partition(parent_partition, interval, funding, sphere, collar, *,
                               finite_stock_state, max_components, budget, _runtime_transfer=None, compact_scope=None):
    """Transport accepted clipped charts and retain exact start-field lineage.

    Each old chart/owner-fan intersection becomes a material chart BEFORE the
    fixed voxel and native/reservoir exclusions. At the next start its overlap
    with that same named fan is the old physical cell; other fan intersections
    are exactly zero by the previously proved disjoint fan partition. This is
    an identity transfer of actual fields, not an interpolated new temperature.
    New cross-fan and born components remain in the space-time partition even
    if both endpoint numerical volumes are zero. Repeated chart growth is
    admitted only within the caller's unchanged finite work/storage budget.
    """
    from . import integration_material as M
    from .integration_spatial_reservoir import FiniteStockState
    if (type(parent_partition) is not DifferentialPartition or type(interval) is not DifferentialInterval or
            parent_partition._resource is not budget or interval._resource is not budget or
            type(finite_stock_state) is not FiniteStockState or finite_stock_state._owner._budget is not budget):
        raise V.VolumeError('actual retained partition, physical interval and finite state on one budget required')
    if type(max_components) is not int or max_components < 1:
        raise V.VolumeError('explicit finite component limit required')
    from partition_native_patch import partition_fields, partition_rows, owned_support_record, _RetainedRows
    old_owner = partition_fields(parent_partition, ('scope', 'network_id', 'endpoint_network_id',
        'trajectory_id', 'funding_id', 'source', 'collar_plan_id', 'end_time_s', 'start_time_s', 'grid_lines'))
    old, step, original = old_owner.value, interval.record(), funding.descriptor()
    from live_partition_patch import resolve_scope, ChartLifetime, parent_rows
    compact_scope = resolve_scope(budget, compact_scope, parent_partition)
    retained_rows = ChartLifetime(parent_partition, compact_scope)
    static = old['scope'] == 'initial-current'
    previous_network = old['network_id'] if static else old['endpoint_network_id']
    previous_trajectory = W._hash([]) if static else old['trajectory_id']
    if (old['funding_id'] != funding.funding_id or old['source'] != original['source'] or
            not _transferred_partition_binding(parent_partition, old, funding, collar, budget, _runtime_transfer) or previous_network != step['parent_network_id'] or
            previous_trajectory != step['prior_trajectory_id'] or old['end_time_s'] != step['start_time_s']):
        raise V.VolumeError('differential material partition does not continue its actual accepted geometry')
    old_time = Q(0) if static else W._decode(old['end_time_s'])-W._decode(old['start_time_s'])
    regions = _carried_partition_regions(parent_partition, step, old_time,
                                          retained_rows, compact_scope)
    # Growth successor (b), new intervals only: a carried chart proved empty
    # at the parent end instant is empty for this whole interval; never seed it.
    regions = _growth_drop_empty_charts(regions, step, old_time, old['grid_lines'], collar, budget)
    # Actual finite birth declarations, not a fake old patch/source key. The
    # owner registry gives these their own component slots and physical fields.
    finite_record = finite_stock_state.record()
    stocks = finite_record['stocks']
    for boundary in step['boundary_paths']:
        if boundary['kind'] != S.RIDGE:
            continue
        for side, supply in boundary['supplies'].items():
            plate = boundary[side+'_plate_id']
            selected = [row for row in stocks if row['kind'] == 'source' and
                row['lineage'].get('kind') == 'declared-finite-shell-birth' and
                row['lineage'].get('supply') == supply and row['lineage'].get('plate_id') == plate]
            if not selected:
                raise V.VolumeError('ridge side lacks its actual retained finite birth declaration')
            for row in selected:
                lineage = row['lineage']
                context = lineage['source_context']
                if (context['sphere_state_id'] != original['source']['sphere_state_id'] or
                        context['network_id'] != original['source']['network_id'] or
                        context['boundary_id'] != boundary['boundary_id'] or context['plate_id'] != plate):
                    raise V.VolumeError('finite birth lineage belongs to another source or physical ridge side')
                column = M.BirthColumn.from_record(lineage['birth_column'])
                layers = M.layer_geometry(column, tuple(s.thickness_m for s in column.sublayers), budget=budget)
                layer = layers[lineage['sublayer']]
                matching = {owned.value['radial_band'] for owned in partition_rows(parent_partition,
                    'source_regions', fields=('radial_band', 'plate_id', 'radial_layer'))
                    if owned.value['plate_id'] == plate and owned.value['radial_layer'] == layer.record()}
                if len(matching) != 1:
                    raise V.VolumeError('birth radial interfaces need a shared explicit source-layer subdivision')
                key = W._hash(dict(birth_interval_id=interval.interval_id, stock_id=row['stock_id']))
                regions[key] = dict(source_chart_id=key, kind='birth',
                    source_key=[lineage['source_id'], lineage['sublayer']], plate_id=plate,
                    radial_band=next(iter(matching)), chart=key, radial_layer=layer.record(),
                    finite_stock_id=row['stock_id'], stock_lineage=lineage,
                    birth_boundary_id=boundary['boundary_id'], birth_side=side)
    if not regions or len(regions) > max_components:
        raise V.VolumeError('carried material chart inventory exceeds the declared finite component limit')
    grid_lines = tuple(tuple(map(W._decode, axis)) for axis in old['grid_lines'])
    final_fields = dict(finite_state_id=finite_stock_state.state_id, finite_owner_id=finite_stock_state._owner.owner_id,
        component_registry_id=finite_record['registry_id']
            if 'registry_id' in finite_record else finite_stock_state._owner.definition()['registry_id'])
    del step, stocks, finite_record, old, old_owner
    result = _assemble_partition(funding, sphere, interval, collar, original,
        [regions[k] for k in sorted(regions)], grid_lines=grid_lines,
        max_components=max_components, budget=budget, parent_partition=parent_partition,
        compact_scope=compact_scope, _final_fields=final_fields)
    return result


def enclose_initial_partition(partition, *, max_volume_error_m3, max_leaves, budget,
                              relative_error=None, measurement_store=None, measurement_context=None):
    """Certify actual initial CV measures, without inventing a future interval.

    The sum of requested per-component widths is no larger than the caller's
    predeclared total. Positive inner-subset witnesses and all zero/uncertain
    rows are retained; no thermal surrogate volume enters these intervals.
    An explicit relative_error additionally bounds each exterior component's
    initial quadrature dilution, using one retained query per component.
    Omission preserves the legacy absolute-only query and record.
    Explicit store/context reuse only complete source-bound local measurements;
    the complete partition and initial allocation are still checked normally.
    """
    if type(partition) is not DifferentialPartition or partition._resource is not budget:
        raise V.VolumeError('issued complete differential partition and shared budget required')
    p = partition.record()
    if p['scope'] != 'initial-current':
        raise V.VolumeError('initial measures cannot reseed an evolved material partition')
    width = W._q(max_volume_error_m3)
    if width <= 0 or type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('positive physical volume error and finite subdivision request required')
    if relative_error is not None and (type(relative_error) not in (int, Q) or not 0 <= relative_error < 1):
        raise V.VolumeError('explicit exact local relative error below one required')
    if (measurement_store is None) != (measurement_context is None) or (
            measurement_store is not None and relative_error is None):
        raise V.VolumeError('initial measurement reuse needs paired store/context and explicit relative accuracy')
    count = sum(len(s.record()['components']) for s in partition.supports)
    local_width = width/max(1, count)
    # initpar r1 (T/ck/transforms/initpar_r1.py): None unless a caller opened a pass.
    prefetch = None
    if relative_error is not None:
        from .integration_initial_parallel import active as _initial_parallel
        prefetch = _initial_parallel()
        if prefetch is not None:
            prefetch = prefetch.start(partition, budget=budget, relative_error=relative_error,
                                      max_width_m3=local_width, max_leaves=max_leaves)
    cells = []
    for index, row in enumerate(p['native_cells']):
        box = V.CartesianCell.from_record(row, budget=budget)
        cells.append(dict(cell_id=W._hash(dict(kind='collar', funding_id=p['funding_id'], cell_id=box.cell_id)),
            kind='collar', index=index, physical_cell_id=box.cell_id,
            volume_bounds_m3=[_qtext(box.volume_m3)]*2))
    for support in partition.supports:
        row = support.record()
        for component in row['components']:
            accuracy = None
            if relative_error is None:
                measured = component_volume_bounds(support, component['logical_cell_id'], endpoint='start',
                    max_width_m3=local_width, max_leaves=max_leaves, positive_witness=True, budget=budget).record()
                if not measured['met']:
                    raise V.VolumeError('initial physical component exceeds the declared measure/work request')
            else:
                from .integration_dual_geometry import measure_initial_component, cached_initial_component
                measure = measure_initial_component if measurement_store is None else cached_initial_component
                reuse = {} if measurement_store is None else dict(store=measurement_store, context=measurement_context)
                if prefetch is not None:
                    reuse['_volume'] = prefetch
                accuracy = measure(support, component['logical_cell_id'],
                    relative_error=relative_error, absolute_width_m3=local_width,
                    max_leaves_per_query=max_leaves, budget=budget, **reuse)
                measured = dict(max(accuracy['queries'], key=lambda q: W._decode(q['positive_witness_m3'])),
                    lower_m3=_qtext(accuracy['bounds'][0]), upper_m3=_qtext(accuracy['bounds'][1]))
            cells.append(dict(cell_id=component['logical_cell_id'], kind='exterior',
                source_key=row['source_key'], voxel_index=row['voxel_index'], radial_band=row['radial_band'],
                chart=row['chart'], source_chart_id=row['source_chart_id'], support_id=support.support_id,
                volume_bounds_m3=[measured['lower_m3'], measured['upper_m3']],
                positive_witness_m3=measured['positive_witness_m3']))
            if accuracy is not None:
                cells[-1]['initial_accuracy'] = dict(accuracy,
                    bounds=list(map(_qtext, accuracy['bounds'])),
                    relative_error_bound=_qtext(accuracy['relative_error_bound']),
                    requested_relative_error=_qtext(accuracy['requested_relative_error']),
                    absolute_width_m3=_qtext(accuracy['absolute_width_m3']))
            if 'positive_witness_point_m' in measured:
                cells[-1]['positive_witness_point_m'] = measured['positive_witness_point_m']
                cells[-1]['positive_witness_point_rule'] = measured['positive_witness_point_rule']
    if prefetch is not None:
        prefetch.finish()
    result = dict(schema='atlas.differential-initial-bounds.v1', scope='initial-current',
        partition_id=partition.partition_id, funding_id=p['funding_id'], collar_plan_id=p['collar_plan_id'],
        source=p['source'], current_geometry_id=p['current_geometry_id'], network_id=p['network_id'],
        support_id=W._hash(dict(epoch_network_id=p['network_id'], segments=[])),
        trajectory_id=W._hash([]), trajectory=dict(segments=[]), time_s=p['start_time_s'],
        grid_id=p['grid_id'], grid_lines=p['grid_lines'], grid_origin_m=p['grid_origin_m'], grid_basis=p['grid_basis'],
        support_ids=p['support_ids'], component_keys=p['component_keys'], component_registry=p['component_registry'],
        excluded_static_cells=p['excluded_static_cells'], cells=cells,
        max_volume_error_m3=_qtext(width), max_leaves=max_leaves,
        physical_volume_scope='exact source-owned cone/shell/Cartesian geometry; no future trajectory or stock allocation')
    if relative_error is not None:
        result['relative_error'] = _qtext(Q(relative_error))
    return _issue(DifferentialInitialBounds, result, budget)


def _support_pose_input(support, endpoint, budget, record=None):
    if type(support) is not DifferentialSupport or support._resource is not budget or endpoint not in ('start', 'end'):
        raise V.VolumeError('issued physical support, same budget and start/end endpoint required')
    record = support.record() if record is None else record
    time = Q(0) if endpoint == 'start' else W._decode(record['duration_s'])
    return record, time


def _posed_support_record(support, record, endpoint, posed):
    return dict(schema='atlas.differential-posed-support.v1', support_id=support.support_id,
        interval_id=record['interval_id'], endpoint=endpoint, time_s=record[endpoint+'_time_s'],
        plate_id=record['plate_id'], source_key=record['source_key'], kind=record['kind'],
        radial_layer=record['radial_layer'], voxel=record['voxel'], constraints=posed,
        components=record['components'], physical_constraint_record=record['constraints'])


def _validate_unposed_support(support, record, *, endpoint, budget):
    """Read all pose inputs when no numerical representative will be consumed."""
    record, time = _support_pose_input(support, endpoint, budget, record)
    with B._Arena(budget) as arena:
        for _, value in record['constraints'].items():
            if not _constraint_pose(value, time, time, 24, arena, _validate_only=True):
                _constraint_pose(value, time, time, 24, arena)
        # Keep the exact required metadata reads of the retained pose route.
        _posed_support_record(support, record, endpoint, {})


def posed_support(support, *, endpoint, budget):
    """Shared rational plane representatives plus rigorously bounded true errors.

    Thermal geometry may use the representative planes; physical volumes must
    use component_volume_bounds. The returned constraints remain shared rather
    than duplicated into every convex component.
    """
    record, time = _support_pose_input(support, endpoint, budget)
    with B._Arena(budget) as arena:
        posed = {}
        for name, value in record['constraints'].items():
            normal, error, offset = _constraint_pose(value, time, time, 24, arena)
            posed[name] = dict(normal=_store_vec(normal), error_euclidean=_qtext(error), offset=_qtext(offset))
        result = _posed_support_record(support, record, endpoint, posed)
    return _issue(DifferentialMeasure, result, budget)


def _mesh_pose_filter(record, booked):
    """Whether borrowed component literals permit a bounded scan without a name set.

    This is eligibility, not validation: unproven shapes take the complete pose
    path, preserving its failures before a consumer reads malformed literals.
    No name set or retained cache competes with mandatory arithmetic admission.
    At most 128 components and 128 carried literals bound each extra scan;
    larger inventories retain the original algorithm without a numerical limit.
    """
    if type(booked) is not dict or type(record.get('components')) is not list:
        return False
    if len(record['components']) > 128:
        return False
    count = 0
    for component in record['components']:
        if type(component) is not dict or type(component.get('logical_cell_id')) is not str:
            return False
        if not booked.get(component['logical_cell_id'], Q(0)):
            continue
        literals = component.get('constraints')
        if type(literals) is not list:
            return False
        for literal in literals:
            if type(literal) is not list or len(literal) != 2 or type(literal[0]) is not str:
                return False
            count += 1
            if count > 128:
                return False
    return True


def _mesh_posed_support(support, record, *, endpoint, booked, budget):
    """Private partial pose for the mesh's booked components, never public coverage.

    Every constraint is still visited in its original order. Unused constraints
    retain the shared decoder/shape validation and numerical fallback used by
    the all-unbooked mesh route. Only needed representatives are encoded. The
    original issue lease owns the resulting bytes, including the complete
    physical constraint record and metadata; no additional retained collection
    or optional reservation is introduced. The public posed_support is intact.
    """
    record, time = _support_pose_input(support, endpoint, budget, record)
    if not _mesh_pose_filter(record, booked):
        return posed_support(support, endpoint=endpoint, budget=budget)
    with B._Arena(budget) as arena:
        posed = {}
        for name, value in record['constraints'].items():
            needed = any(booked.get(component['logical_cell_id'], Q(0)) and
                         any(literal[0] == name for literal in component['constraints'])
                         for component in record['components'])
            if not needed:
                if not _constraint_pose(value, time, time, 24, arena, _validate_only=True):
                    _constraint_pose(value, time, time, 24, arena)
                continue
            normal, error, offset = _constraint_pose(value, time, time, 24, arena)
            posed[name] = dict(normal=_store_vec(normal), error_euclidean=_qtext(error), offset=_qtext(offset))
        result = _posed_support_record(support, record, endpoint, posed)
    return _issue(DifferentialMeasure, result, budget)


def _support_component(support, logical_cell_id, budget):
    if type(support) is not DifferentialSupport or support._resource is not budget:
        raise V.VolumeError('issued physical support and its shared WorkBudget required')
    record = support.record()
    component = next((row for row in record['components'] if row['logical_cell_id'] == logical_cell_id), None)
    if component is None:
        raise V.VolumeError('unknown physical support logical cell')
    layer = V.RadialLayer(*(W._decode(record['radial_layer'][key])
                           for key in ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
    cell = V.CartesianCell.from_record(record['voxel'], budget=budget)
    return record, component, layer, cell


def _wall_cone_zero_measure(record, component, face, duration, arena):
    """A complete positive ray cone meets this origin-plane face in one ray.

    All three literal-directed cyclic edges and a strictly positive whole-
    interval determinant establish the nonnegative generator cone. If all
    generator projections onto a face normal are nonpositive, with at least
    two strictly negative throughout, a point in the face can use at most
    one generator. Its section has zero 2-D area, irrespective of the shell.
    Two generators in the face are deliberately insufficient. Ordered ray
    history and current motion use the existing componentwise rotation bounds.
    """
    with V._work((duration, *face[0], *face[3]), arena.resource):
        if O._dot(face[0], face[3]) != 0:
            return None
    keys, ids, edges, adjacency = [], {}, {}, {}
    for name, sign in component['constraints']:
        paths = _constraint_edge_ray_paths(record['constraints'][name])
        if paths is None or len(paths) != 2 or sign not in (-1, 1):
            continue
        pair = []
        for path in paths:
            if path not in ids:
                ids[path] = len(keys)
                keys.append(path)
            pair.append(ids[path])
        i, j = pair if sign == 1 else pair[::-1]
        edges[i, j] = (name, sign)
        adjacency.setdefault(i, set()).add(j)
    if len(edges) < 3:
        return None
    operands = (duration, *face[3], *(q for direction, omega, prior in keys for q in
        (*direction, *omega, *(v for old, dt in prior for v in (*old, dt)))))
    with _PartitionScratch(arena) as scratch, V._work(operands, arena.resource):
        scratch.work(128+64*len(keys))
        boxes = {}
        def box(index):
            if index not in boxes:
                direction, omega, prior = keys[index]
                posed = tuple((q, q) for q in direction)
                for old, dt in prior:
                    posed = _rotation_boxes(posed, old, dt, dt, 0, scratch)
                posed = _rotation_boxes(posed, omega, Q(0), duration, 0, scratch)
                scratch.keep(tuple(q for pair in posed for q in pair), 4)
                boxes[index] = posed
            return boxes[index]
        normal = tuple((q, q) for q in face[3])
        for i in adjacency:
            for j in sorted(adjacency[i]):
                for k in sorted(adjacency.get(j, ())):
                    scratch.work(16)
                    if not (i < j and i < k and i in adjacency.get(k, ())):
                        continue
                    triangle = i, j, k
                    projected = tuple(_dot_bounds(normal, box(index)) for index in triangle)
                    negative = all(hi <= 0 for lo, hi in projected) and sum(hi < 0 for lo, hi in projected) >= 2
                    positive = all(lo >= 0 for lo, hi in projected) and sum(lo > 0 for lo, hi in projected) >= 2
                    scratch.work(128)
                    if not (negative or positive):
                        continue
                    determinant = _dot_bounds(box(i), _cross_bounds(box(j), box(k)))
                    scratch.work(256)
                    if determinant[0] <= 0:
                        continue
                    return dict(method='whole-interval-ray-cone-zero-area', pose_level=0,
                        triangle_literals=[list(edges[triangle[q], triangle[(q+1) % 3]]) for q in range(3)],
                        determinant_bounds=list(map(_qtext, determinant)),
                        face_normal=_store_vec(face[3]),
                        generator_projection_bounds=[list(map(_qtext, pair)) for pair in projected],
                        scope='fixed-face intersection lies in at most one ray throughout the complete time interval')
    return None


def _wall_outer_zero_measure(record, component, layer, face, duration, arena):
    """Certify zero area on the actual fixed face for the WHOLE interval.

    Each boxed angular line is an upper bound on its signed constraint at
    every point of this rectangle and every query time. The radial lines
    likewise contain the true shell intersection. Their convex polygon
    therefore contains every true face section up to zero-area boundaries;
    exact zero polygon area
    proves zero flux without inferring face area from a volume certificate.
    This is a sufficient screen only: uncertain positive area falls through.
    """
    values = (duration, layer.bottom_radius_m, layer.top_radius_m,
              *(q for vector in face[:4] for q in vector),
              *(q for pair in face[4] for q in pair))
    with _PartitionScratch(arena) as scratch, V._work(values, arena.resource):
        polygon = W._rectangle(face[4])
        radial = W._radial_planes(face, face[4], layer, False)
        scratch.work(128)
        for line in radial:
            polygon = W._clip2(polygon, line, scratch)
            scratch.keep(tuple(q for point in polygon for q in point), len(polygon))
        examined = 0
        for name, sign in component['constraints']:
            if not polygon:
                break
            box, offset = _constraint_boxes(record['constraints'][name], Q(0), duration, 0, scratch)
            with V._work((*values, offset, *(q for pair in box for q in pair)), arena.resource):
                line = _boxed_constraint_line(face, face[4], box, offset, sign, False)
                polygon = W._clip2(polygon, line, scratch)
                scratch.keep(tuple(q for point in polygon for q in point), len(polygon))
            examined += 1
            scratch.work(64)
        if W._integral(polygon, (Q(0), Q(0), Q(1)), scratch) != 0:
            return _wall_cone_zero_measure(record, component, face, duration, arena)
        return dict(method='whole-interval-outer-face-zero-area', pose_level=0,
                    angular_literals_examined=examined, radial_outer_halfplanes=len(radial),
                    scope='zero fixed-face area throughout the complete time interval')


def enclose_component_wall(support, logical_cell_id, axis, end, *, max_width_m3, max_leaves, budget,
                           moment_polynomials=(), max_moment_widths=(), endpoint=None,
                           normal_polynomial=None, moments_only=False, _funded=None, _screen_only=False):
    """True component-masked Cartesian flux and separately bounded moments.

    The chart is identical to the whole-owner face API. With ``endpoint`` the
    moments are SPATIAL and the velocity integral is a rate; otherwise all
    quantities are integrated over the complete actual interval. This is the
    mask needed for componentwise work-conjugate native trace constraints.
    With ``moments_only`` (endpoint queries) the query is judged on its
    moments alone, as the whole-owner face API does when no rate width is
    requested: the leaf still evaluates the rates, so the work and every
    other field are those of the full query, and the record carries no rate.
    """
    record, component, layer, cell = _support_component(support, logical_cell_id, budget)
    static = 'current_geometry_id' in record
    if _GEOMETRY_PROGRESS is not None:
        _GEOMETRY_PROGRESS.start('wall', support.support_id, logical_cell_id, (axis, end))
    if static and endpoint is None:
        raise V.VolumeError('instantaneous component requires spatial endpoint evaluation')
    normal = None if normal_polynomial is None else _polynomials((normal_polynomial,))[0]
    polynomials, widths = _query_inputs(layer, cell, max_width_m3, max_leaves, moment_polynomials, max_moment_widths)
    if type(axis) is not int or axis not in (0, 1, 2) or type(end) is not int or end not in (0, 1):
        raise V.VolumeError('explicit Cartesian face axis/end required')
    omega = _load_vec(record['material_angular_velocity_rad_s'])
    face, duration = W._face(cell, axis, end), W._decode(record['duration_s'])
    if endpoint not in (None, 'start', 'end'):
        raise V.VolumeError('component moment endpoint must be start or end')
    if moments_only and (endpoint is None or not polynomials or normal is not None):
        raise V.VolumeError('moments-only query requires an endpoint and explicit moments, and takes no normal')
    with B._Arena(budget) as arena:
        # A mask cannot change an identically zero physical normal field.
        # Prove this in the actual world-space face frame, before constructing
        # thousands of moving polygons for walls parallel to rigid motion.
        # Requested scalar moments still require their real masked geometry.
        with V._work((*omega, *(q for point in face[:4] for q in point)), budget):
            velocity = tuple(O._dot(face[3], O._cross(omega, p))
                             for p in (face[1], face[2], face[0]))
            zero_flux = not polynomials and not any(velocity if normal is None else normal.values())
        zero_wall = None
        if not zero_flux and endpoint is None and normal is None and not polynomials:
            # The full-time OUTER face contains every instantaneous material
            # face. Exact zero area of that superset proves zero flux without
            # constructing a time history of polygons. An undecided proof
            # leaves the existing numerical integrators and limits unchanged.
            zero_wall = _wall_outer_zero_measure(record, component, layer, face, duration, arena)
        eligible = endpoint is None and normal is None and not polynomials and not moments_only
        if _screen_only and (not eligible or not zero_flux and zero_wall is None):
            # A scheduling screen never substitutes an approximate answer or
            # enters an expensive integrator. Other query types stay serial.
            return None
        if eligible and not zero_flux and zero_wall is None and _funded is not None:
            # Original input checks and the exact zero proofs stay in parent
            # order. Only the unchanged unresolved body may come from a live,
            # source-bound worker funded by this same resource owner.
            request = dict(schema=MEASURE_SCHEMA, kind='component-fixed-voxel-face',
                support_id=support.support_id, interval_id=record['interval_id'],
                logical_cell_id=logical_cell_id, axis=axis, end=end,
                start_time_s=record['start_time_s'], end_time_s=record['end_time_s'],
                max_width_m3=_qtext(widths[0]), max_leaves=max_leaves)
            funded = _funded(request, budget)
            if funded is not None:
                from .integration_parallel_results import adopt
                return adopt(DifferentialMeasure, funded, budget)
        pose_cache, pose = None, [False]
        def leaf(bounds, a, b, level):
            weight = b-a
            if endpoint is not None:
                a = b = Q(0) if endpoint == 'start' else duration
                weight = Q(1)
            original = W._rectangle(bounds)
            posed = {name: (_constraint_boxes(record['constraints'][name], a, b, level, arena)
                           if pose_cache is None else pose_cache.boxes(record['constraints'][name], a, b, level, arena))
                      for name, _ in component['constraints']}
            if endpoint is not None:
                pose[0] = any(lo != hi for box, _ in posed.values() for lo, hi in box)
            shapes = []
            for inner in (True, False):
                poly = original
                for name, sign in component['constraints']:
                    normal_box, offset = posed[name]
                    line = _boxed_constraint_line(face, bounds, normal_box, offset, sign, inner)
                    poly = W._clip2(poly, line, arena)
                    if not poly:
                        break
                for line in W._radial_planes(face, bounds, layer, inner):
                    poly = W._clip2(poly, line, arena)
                shapes.append(poly)
            result = []
            for flow_sign in (-1, 1):
                if normal is None:
                    linear = tuple(flow_sign*q for q in velocity)
                    result.append(tuple(W._integral(W._clip2(poly, linear, arena), linear, arena)*weight for poly in shapes))
                else:
                    # A general native Q2 trace may change sign inside a leaf.
                    # The lower Jensen bound and interval upper bound enclose
                    # its actual positive part; subdivision resolves the zero
                    # curve without pretending the nine Gauss signs are exact.
                    polynomial = {key: flow_sign*q for key, q in normal.items()}
                    low, high = _polynomial_range(polynomial, bounds)
                    # Both are certified ranges of the same polynomial. The
                    # hull decides the sign beside the zero curve, where the
                    # termwise range cannot, and bounds the unresolved stream
                    # by the trace's own size there.
                    hull = _bernstein_hull(polynomial, bounds)
                    low, high = max(low, hull[0]), min(high, hull[1])
                    arena.work(32*len(polynomial))
                    if high <= 0:
                        pair = (Q(0), Q(0))
                    elif low >= 0:
                        pair = tuple(_polynomial_integral(poly, polynomial, arena) for poly in shapes)
                    else:
                        pair = (max(Q(0), _polynomial_integral(shapes[0], polynomial, arena)),
                                high*W._integral(shapes[1], (0, 0, 1), arena))
                    result.append(tuple(q*weight for q in pair))
            inner_area, outer_area = (W._integral(poly, (0, 0, 1), arena) for poly in shapes)
            if inner_area > outer_area:
                raise V.VolumeError('physical component enclosure lost containment')
            for polynomial in polynomials:
                known = _polynomial_integral(shapes[0], polynomial, arena)
                low, high = _polynomial_range(polynomial, bounds)
                unknown = outer_area-inner_area
                result.append(((known+min(Q(0), low)*unknown)*weight,
                               (known+max(Q(0), high)*unknown)*weight))
            arena.work(128+64*len(posed))
            return tuple(result)
        temporal, native_integral = None, None
        native_method, native_certificate, native_digest = None, None, None
        try:
            if not zero_flux and zero_wall is None and endpoint is None and normal is not None:
                from . import integration_masked_native as NM
                native_integral = NM.integrate(record, component, layer, face, normal, polynomials,
                    widths, duration, max_leaves=max_leaves, arena=arena)
                native_method = NM.METHOD
                if native_integral is None:
                    near_signed = NM.integrate_near_signed(record, component, layer, face, normal, polynomials,
                        widths, duration, fallback=leaf, max_leaves=max_leaves, arena=arena)
                    if near_signed is not None:
                        native_integral, native_certificate = near_signed[:3], near_signed[3]
                        native_method = NM.SIGNED_METHOD
                if native_integral is None:
                    complement = NM.integrate_signed_complement(record, component, layer, face, normal, polynomials,
                        widths, duration, fallback=leaf, max_leaves=max_leaves, arena=arena)
                    if complement is not None:
                        native_integral, native_certificate = complement[:3], complement[3]
                        native_method = NM.COMPLEMENT_METHOD
                if native_integral is None:
                    from . import integration_masked_partition as MP
                    pose_cache = MP._PoseCache(arena)
                    partitioned = MP.integrate(record, component, layer, face, normal, polynomials,
                        widths, duration, fallback=leaf, max_leaves=max_leaves, arena=arena,_pose_cache=pose_cache)
                    if partitioned is not None:
                        native_integral, native_certificate = partitioned[:3], partitioned[3]
                        native_method = MP.METHOD
                        native_digest = MP.source_digest()
            if not zero_flux and zero_wall is None and endpoint is None and normal is None:
                from . import integration_moving_face_moments as TM
                temporal = TM.integrate(record, component, layer, face, omega, polynomials,
                    widths, duration, fallback=leaf, max_leaves=max_leaves, arena=arena)
            reposed = None
            if zero_flux or zero_wall is not None:
                values, leaves, met = ((Q(0), Q(0)), (Q(0), Q(0))), 1, True
            elif native_integral is not None:
                values, leaves, met = native_integral
            elif temporal is None:
                root, judged = leaf, widths
                if endpoint is not None:
                    # One root evaluation serves the finer pose and the refinement.
                    # A moments-only query is judged on its moments alone; the
                    # leaf still evaluates the rates, so its work is unchanged.
                    start, first = (face[4], Q(0), Q(1), 0), leaf(face[4], Q(0), Q(1), 0)
                    cut = (lambda pairs: pairs[2:]) if moments_only else (lambda pairs: pairs)
                    judged, first = cut(widths), cut(first)
                    single = lambda box, a, b, level: cut(leaf(box, a, b, level))
                    root = lambda box, a, b, level: first if (box, a, b, level) == start else single(box, a, b, level)
                    if pose[0]:
                        reposed = _finer_static_pose(first, single, face[4], Q(1), judged, max_leaves, arena)
                if reposed is not None:
                    values, leaves, met = reposed[0], reposed[1], True
                else:
                    values, leaves, met = _refine(root, face[4], duration if endpoint is None else Q(1),
                                                  judged, max_leaves, arena, spatial_only=endpoint is not None)
                if moments_only:
                    values = ((Q(0), Q(0)), (Q(0), Q(0)), *values)
            else:
                values, leaves, met = temporal
        except Exception as error:
            query = dict(logical_cell_id=logical_cell_id, axis=axis, end=end, endpoint=endpoint,
                moment_polynomials=[[[i, j, _qtext(q)] for (i, j), q in sorted(p.items())] for p in polynomials],
                max_moment_widths=list(map(_qtext, widths[2:])),
                max_width_m3=_qtext(widths[0]), max_leaves=max_leaves, moments_only=moments_only)
            if normal is not None:
                query['normal_polynomial'] = [[i, j, _qtext(q)] for (i, j), q in sorted(normal.items())]
            error.component_moment_failure = _wall_failure_payload(record, query, budget, error,
                budget_scope='component arena still live; failed integration scratch has unwound')
            raise
        result = dict(schema=MEASURE_SCHEMA, kind='component-fixed-voxel-face', support_id=support.support_id,
            interval_id=record['interval_id'], logical_cell_id=logical_cell_id, axis=axis, end=end,
            physical_cell_id=cell.cell_id, start_time_s=record['start_time_s'], end_time_s=record['end_time_s'],
            inward_volume_bounds_m3=[_qtext(q) for q in values[0]], outward_volume_bounds_m3=[_qtext(q) for q in values[1]],
            face=dict(origin_m=_store_vec(face[0]), tangent_u=_store_vec(face[1]), tangent_v=_store_vec(face[2]),
                outward_normal=_store_vec(face[3]), coordinate_bounds_m=[list(map(_qtext, b)) for b in face[4]],
                area_jacobian=_qtext(Q(1))),
            moment_polynomials=[[[i, j, _qtext(q)] for (i, j), q in sorted(poly.items())] for poly in polynomials],
            moment_bounds=[list(map(_qtext, pair)) for pair in values[2:]], max_widths=list(map(_qtext, widths)),
            max_width_m3=_qtext(widths[0]), max_leaves=max_leaves, leaves=leaves, met=met, work_units=arena.work_units,
            moment_time_measure='integrated over the complete physical interval')
        if zero_flux:
            result['exact_zero_normal_flux'] = (
                'all three exact world-space rigid normal coefficients vanish' if normal is None else
                'every coefficient of the explicitly supplied normal polynomial vanishes')
        if zero_wall is not None:
            result['exact_zero_wall_measure'] = zero_wall
        if temporal is not None:
            result['temporal_integration'] = dict(method='fixed-topology-interval-Taylor',
                order=TM.ORDER, decimal_precision=80, source_sha256=TM.source_digest(),
                endpoint_topology='exact same-sign Taylor prefix plus enclosed remainder, or closed one-sign bound with strict monotonicity; departure sign only on a nondegenerate open interval',
                    edge_intersection='exact whole-jet-zero endpoint reused; exact homogeneous origin with strict opposite crossing signs; retained common edge with closed nonzero determinant, or exact half-angle/certified endpoint-series cancellation with closed nonzero reduced denominator; otherwise interpolation/fallback',
                    radial_zero_rule='actual homogeneous halfspace cone with certified nonzero whole-time determinant; fixed-plane section or actual rectangle-capped cone strictly inside inner sphere',
                unresolved_topology='original geometric enclosure, same leaf limit')
        if native_integral is not None:
            result['native_mask_integration'] = dict(method=native_method,
                source_sha256=native_digest if native_digest is not None else NM.source_digest())
            if native_certificate is not None:
                result['native_mask_integration']['signed_moment_certificate'] = native_certificate
        if normal is not None:
            result['normal_polynomial'] = [[i, j, _qtext(q)] for (i, j), q in sorted(normal.items())]
            result['normal_trace_authority'] = 'exact supplied polynomial; caller must bind to actual issued native flow'
        if endpoint is not None:
            result.update(kind='component-instantaneous-voxel-face', endpoint=endpoint,
                evaluation_time_s=record[endpoint+'_time_s'], moment_time_measure='spatial only; no interval division')
            result['inward_volume_rate_bounds_m3_s'] = result.pop('inward_volume_bounds_m3')
            result['outward_volume_rate_bounds_m3_s'] = result.pop('outward_volume_bounds_m3')
            if reposed is not None:
                result['static_pose'] = dict(level=reposed[2], levels=[0, *STATIC_POSE_LEVELS[:reposed[1]-1]],
                    rule='undivided face posed again at finer rational precision; enclosures intersected')
        if static:
            result.update(current_geometry_id=record['current_geometry_id'], network_id=record['network_id'])
            if normal is None:
                result.pop('inward_volume_rate_bounds_m3_s')
                result.pop('outward_volume_rate_bounds_m3_s')
                result['physical_velocity'] = 'not supplied, not inferred'
        elif moments_only:
            # A static support's record already carries no rate and says so;
            # it is issued exactly as before. An interval support's spatial
            # query records that no rate criterion was requested.
            result.pop('inward_volume_rate_bounds_m3_s')
            result.pop('outward_volume_rate_bounds_m3_s')
            result['query'] = 'spatial moments only; no rate acceptance criterion requested'
    if _GEOMETRY_PROGRESS is not None:
        _GEOMETRY_PROGRESS.end(result)
    return _issue(DifferentialMeasure, result, budget)


def _moving_interface_leaf(layer, voxel, first, second, outward_sign, omega, constraints,
                            literals, bounds, t0, t1, level, arena):
    posed_rays = tuple(_ray_box(_load_vec(ray['direction']), _load_vec(ray['angular_velocity_rad_s']),
                               t0, t1, level, arena, _history(ray.get('prior_rotations', ()))) for ray in (first, second))
    (a, ea, ia), (b, eb, ib) = posed_rays
    area_interval = _cross_bounds(ia, ib)
    relative = tuple(tuple(p-q for p, q in zip(omega, _load_vec(ray['angular_velocity_rad_s']))) for ray in (first, second))
    coefficients = []
    for w, box in zip(relative, (ia, ib)):
        velocity = _cross_bounds(tuple((q, q) for q in w), box)
        pair = _dot_bounds(velocity, area_interval)
        coefficients.append(tuple(outward_sign*q for q in pair) if outward_sign > 0 else tuple(outward_sign*q for q in reversed(pair)))
    face = ((Q(0),)*3, a, b, O._cross(a, b), bounds)
    original = W._rectangle(bounds)
    absolute = sum(max(abs(W._point(face, p)[j]) for p in original) for j in range(3))
    position_error = bounds[0][1]*ea+bounds[1][1]*eb
    radial_error = 2*absolute*position_error+position_error**2
    posed = {name: _constraint_pose(constraints[name], t0, t1, level, arena) for name, _ in literals}
    fixed = tuple((tuple(-q for q in p[:3]), -p[3]) for p in O._box_planes(voxel))
    result = []
    for flow_sign in (-1, 1):
        values = []
        for inner in (True, False):
            index = 0 if inner else 1
            pair = coefficients if flow_sign > 0 else tuple((-hi, -lo) for lo, hi in coefficients)
            linear = (pair[0][index], pair[1][index], Q(0))
            poly = W._clip2(original, linear, arena)
            for name, sign in literals:
                normal, error, offset = posed[name]
                total_error = error*absolute+position_error*sum(map(abs, normal))+error*position_error
                poly = W._clip2(poly, W._line(face, tuple(sign*q for q in normal),
                    sign*offset+(1 if inner else -1)*total_error), arena)
            for normal, offset in fixed:
                error = position_error*sum(map(abs, normal))
                poly = W._clip2(poly, W._line(face, normal, offset+(1 if inner else -1)*error), arena)
            for line in _quadratic_radial_planes(face, bounds, layer, inner, radial_error):
                poly = W._clip2(poly, line, arena)
            values.append(W._integral(poly, linear, arena)*(t1-t0))
        result.append(tuple(values))
    arena.work(256+64*len(posed))
    return tuple(result)


_CP_SOURCE_SHA256 = 'e18220a7fb672a6a3b8c4d6342b48fd960eadaeba8bce66ddfe0fe8e548f9a28'  # sha256 of the certificate helper below + its call site
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


def enclose_component_interface(support, logical_cell_id, constraint_name, *,
                                 other_support=None, other_logical_cell_id=None,
                                 max_width_m3, max_leaves, budget, _funded=None, _screen_only=False):
    """Relative material flux through an actual moving radial component face.

    The face may be an artificial fan separator: its speed is NOT assumed to
    equal material speed. If a neighbour is supplied, the face is clipped to
    both physical components and one paired geometric receipt is issued.
    Radial shell surfaces and rigid material-cone faces have exactly zero
    relative normal flux. Fixed excluded-box walls use their own FV coupling,
    not an invented rigid basal boundary condition.
    """
    record, component, layer, cell = _support_component(support, logical_cell_id, budget)
    _, widths = _query_inputs(layer, cell, max_width_m3, max_leaves, (), ())
    sign = next((s for name, s in component['constraints'] if name == constraint_name), None)
    if _GEOMETRY_PROGRESS is not None:
        _GEOMETRY_PROGRESS.start('interface', support.support_id, logical_cell_id, constraint_name,
                                 other=other_logical_cell_id)
    if sign is None:
        raise V.VolumeError('component does not use this interface')
    constraint = record['constraints'][constraint_name]
    omega = _load_vec(record['material_angular_velocity_rad_s'])
    duration = W._decode(record['duration_s'])
    constraints = dict(record['constraints'])
    literals = tuple((name, s) for name, s in component['constraints'] if name != constraint_name)
    other_id = None
    if other_support is not None:
        other, other_component, other_layer, other_cell = _support_component(other_support, other_logical_cell_id, budget)
        if (other['interval_id'] != record['interval_id'] or other['plate_id'] != record['plate_id'] or
                other_layer.layer_id != layer.layer_id or other_cell.cell_id != cell.cell_id):
            raise V.VolumeError('paired moving faces must share actual interval, plate, layer and voxel')
        other_id = other_support.support_id
        matched = False
        for name, s in other_component['constraints']:
            item = other['constraints'][name]
            # Same/reversed ray paths name the identical physical moving plane.
            left, right = _interface_identity(constraint), _interface_identity(item)
            equivalent = left is not None and right is not None and left[0] == right[0]
            same = item == constraint or equivalent and left[1] == right[1]
            reverse = equivalent and left[1] != right[1]
            if same or reverse:
                if s*(1 if same else -1) != -sign:
                    raise V.VolumeError('paired components do not use opposite sides of the physical plane')
                matched = True
                continue
            key = 'neighbour:'+name
            constraints[key] = item
            literals += ((key, s),)
        if not matched:
            raise V.VolumeError('paired components have no identical opposite physical interface')
    # A live parent-owned dispatch may supply the unchanged body's result only
    # HERE: every original prefix check and admission above has still happened
    # in serial order. Optional failure/absence runs the original body below.
    if _funded is not None:
        request = dict(schema=MEASURE_SCHEMA, kind='component-moving-radial-interface',
            support_id=support.support_id, interval_id=record['interval_id'],
            logical_cell_id=logical_cell_id, constraint_name=constraint_name,
            other_support_id=other_id, other_logical_cell_id=other_logical_cell_id,
            start_time_s=record['start_time_s'], end_time_s=record['end_time_s'],
            max_width_m3=_qtext(widths[0]), max_leaves=max_leaves)
        funded = _funded(request, budget)
        if funded is not None:
            from .integration_parallel_results import adopt
            return adopt(DifferentialMeasure, funded, budget)
    with B._Arena(budget) as arena:
        from . import integration_interface_exclusion as IE
        interface_moments = None
        material_plane = _material_plane(constraint, omega)
        rigid_fan = constraint['kind'] == 'moving-ray-edge' and all(
            _load_vec(ray['angular_velocity_rad_s']) == omega for ray in constraint['rays'])
        # The voxel clips this face as well; only its walls through the sphere
        # centre are homogeneous halfspaces of the same positive ray cone.
        walls = tuple(('fixed-voxel-wall:%d:%d' % (index//2, 1-index % 2), tuple(Q(-q) for q in plane[:3]))
                      for index, plane in enumerate(O._box_planes(cell)) if not plane[3])
        exclusion = None if material_plane or rigid_fan else IE.zero_area(
            constraint, constraints, literals, duration, arena, fixed=walls)
        if exclusion is None and not material_plane and not rigid_fan:
            exclusion = IE.radial_cap_zero_area(constraint, layer, cell, duration, arena)
        if exclusion is not None:
            values, leaves, met = ((Q(0), Q(0)), (Q(0), Q(0))), 1, True
            rule = ('exact-zero-area-from-actual-voxel-radial-cap'
                    if exclusion['method'] == 'exact-voxel-cap-inside-inner-radius' else
                    'exact-zero-area-from-actual-halfspace-pair' if 'constraint_names' in exclusion else
                    'exact-zero-area-from-actual-fixed-voxel-wall' if 'halfspace_kind' in exclusion else
                    'exact-zero-area-from-actual-moving-halfspace')
        elif material_plane:
            values, leaves, met = ((Q(0), Q(0)), (Q(0), Q(0))), 1, True
            rule = 'exact-zero-relative-flux-on-material-transported-plane'
        elif constraint['kind'] == 'moving-ray-edge':
            first, second = constraint['rays']
            if all(_load_vec(ray['angular_velocity_rad_s']) == omega for ray in (first, second)):
                values, leaves, met = ((Q(0), Q(0)), (Q(0), Q(0))), 1, True
                rule = 'exact-zero-relative-flux-on-rigid-material-fan-edge'
            else:
                if _screen_only:
                    # Optional scheduling probe: exact shortcuts above did
                    # not decide this contact. No approximation is returned.
                    return None
                (a, ea, _), (b, eb, _) = tuple(_ray_box(_load_vec(ray['direction']),
                    _load_vec(ray['angular_velocity_rad_s']), Q(0), duration, 0, arena,
                    _history(ray.get('prior_rotations', ()))) for ray in (first, second))
                normal = O._cross(a, b)
                error = ea*sum(map(abs, b))+eb*sum(map(abs, a))+ea*eb
                lower = max((abs(q)-error for q in normal), default=Q(0))
                if lower <= 0:
                    raise V.VolumeError('moving face needs a finer time bracket to certify a finite radial parameter chart')
                # Euclidean norm is preserved for each exact ray. Its L1 norm
                # is bounded by 3 times the original L1 norm, without sqrt.
                bounds = ((Q(0), 3*layer.top_radius_m*sum(map(abs, _load_vec(second['direction'])))/lower),
                          (Q(0), 3*layer.top_radius_m*sum(map(abs, _load_vec(first['direction'])))/lower))
                from . import integration_moving_interface_moments as IM
                physical_leaf = lambda box, t0, t1, level: _moving_interface_leaf(
                    layer, cell, first, second, -sign, omega, constraints, literals, box, t0, t1, level, arena)
                # The Taylor route encloses the SAME physical face. An
                # unresolved result does not replace the original adaptive
                # geometric integrator or borrow any of its width allowance.
                certificate = None
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
        else:
            raise V.VolumeError('fixed reservoir/native box interface needs its actual supplied FV flow, not rigid continuation')
        result = dict(schema=MEASURE_SCHEMA, kind='component-moving-radial-interface', support_id=support.support_id,
            interval_id=record['interval_id'], logical_cell_id=logical_cell_id, constraint_name=constraint_name,
            other_support_id=other_id, other_logical_cell_id=other_logical_cell_id,
            start_time_s=record['start_time_s'], end_time_s=record['end_time_s'],
            inward_volume_bounds_m3=[_qtext(q) for q in values[0]], outward_volume_bounds_m3=[_qtext(q) for q in values[1]],
            max_width_m3=_qtext(widths[0]), max_leaves=max_leaves, leaves=leaves, met=met,
            rule=rule, work_units=arena.work_units)
        if exclusion is not None:
            result['zero_area_certificate'] = exclusion
        if interface_moments is not None:
            result['moving_interface_moments'] = interface_moments
    if _GEOMETRY_PROGRESS is not None:
        _GEOMETRY_PROGRESS.end(result)
    return _issue(DifferentialMeasure, result, budget)


def _close_dual_differential_record(record, start_volumes_m3, material_quadrature_m3,
                                    stock_record, budget, geometry_volume_errors):
    """Select G0/G1/streams inside physical bounds independently of carried B.

    This private arithmetic seam issues nothing. Original endpoint and face
    bounds remain intact; only start geometry intersects retained true-minus-G
    errors. Finite geometric capacity constrains the same circulation.
    """
    from . import integration_dual_geometry as D
    physical = {r['cell_id'] for r in record['cells'] if r['kind'] != 'algebraic-port'}
    if any(r['kind'] == 'finite-inventory' for r in record['cells']):
        raise V.VolumeError('differential bounds must contain physical cells before inventory attachment')
    if type(material_quadrature_m3) is not dict or type(start_volumes_m3) is not dict:
        raise V.VolumeError('complete exact physical G and material B mappings required')
    if type(geometry_volume_errors) is not dict or set(geometry_volume_errors)-physical:
        raise V.VolumeError('carried geometric volume errors must name actual physical cells')
    for pair in geometry_volume_errors.values():
        if (type(pair) not in (tuple, list) or len(pair) != 2 or
                any(type(v) not in (int, Q) for v in pair)):
            raise V.VolumeError('geometric volume error must be an exact signed pair')
    exchanges = record.get('finite_exchange_intervals', [])
    if type(exchanges) is not list:
        raise V.VolumeError('complete certified finite exchange interval list required')
    required = {'stock_id', 'physical_cell_id', 'direction', 'face_id',
                'volume_bounds_m3', 'physical_certificate_id', 'stock_lineage'}
    for row in exchanges:
        if (type(row) is not dict or set(row) != required or
                type(row['physical_certificate_id']) is not str or not row['physical_certificate_id']):
            raise V.VolumeError('complete issued finite exchange geometry and lineage required')
    finite_measures = {}
    for row in stock_record['stocks']:
        if type(row.get('exact')) is not dict or 'material_quadrature_m3' not in row['exact']:
            raise V.VolumeError('dual finite inventory requires explicit carried material quadrature B')
        finite_measures[row['stock_id']] = dict(geometric_start_m3=W._decode(row['volume_m3']),
            material_quadrature_m3=W._decode(row['exact']['material_quadrature_m3']))
    preferred = dict(start_volumes_m3)
    preferred.update({'finite-stock:'+key: values['geometric_start_m3']
                      for key, values in finite_measures.items()})
    try:
        augmented, _ = D.physical_record(record, material_quadrature_m3, geometry_volume_errors,
            stock_record, geometric_starts=start_volumes_m3, finite_measures=finite_measures)
        closed = D.select_geometry(augmented, budget=budget, preferred_starts=preferred)
    except V.VolumeError:
        raise
    except ValueError as error:
        raise V.VolumeError(str(error)) from error
    originals = {r['cell_id']: r for r in record['cells']}
    errors = {}
    for row in closed['cells']+closed['inactive_zero_measure_cells']:
        key = row['cell_id']
        if key not in physical:
            continue
        selected = W._decode(row['start_volume_m3'])
        low, high = map(W._decode, row['start_volume_bounds_m3'])
        errors[key] = [low-selected, high-selected]
        row['admissible_start_volume_bounds_m3'] = row['start_volume_bounds_m3']
        row['start_volume_bounds_m3'] = originals[key]['start_volume_bounds_m3']
        row['true_start_volume_bounds_m3'] = originals[key]['start_volume_bounds_m3']
        row['true_end_volume_bounds_m3'] = originals[key]['end_volume_bounds_m3']
        row['carried_start_geometry_volume_m3'] = _qtext(Q(start_volumes_m3[key]))
        row['geometric_rebase_m3'] = _qtext(selected-Q(start_volumes_m3[key]))
        row['start_geometry_volume_error_m3'] = list(map(_qtext, errors[key]))
    ports = {r['cell_id']: r['collar_cell_id'] for r in record['cells'] if r['kind'] == 'algebraic-port'}
    for face in closed['selected_face_representatives']:
        if face.get('partition_total'):
            continue
        selected = W._decode(face['volume_m3'])
        low, high = (v-selected for v in map(W._decode, face['volume_bounds_m3']))
        donor, receiver = ports.get(face['donor'], face['donor']), ports.get(face['receiver'], face['receiver'])
        if donor in errors:
            errors[donor][0] -= high; errors[donor][1] -= low
        if receiver in errors:
            errors[receiver][0] += low; errors[receiver][1] += high
    for row in closed['cells']+closed['inactive_zero_measure_cells']:
        key = row['cell_id']
        if key not in errors:
            continue
        selected = W._decode(row['end_volume_m3'])
        low, high = map(W._decode, row['true_end_volume_bounds_m3'])
        low, high = max(low-selected, errors[key][0]), min(high-selected, errors[key][1])
        if low > high:
            raise V.VolumeError('strict stream error and endpoint physical volume certificates are inconsistent')
        row['geometry_volume_error_m3'] = list(map(_qtext, (low, high)))
    selected = {r['face_id']: r for r in closed['selected_face_representatives']}
    issued = []
    for row in exchanges:
        chosen = selected[row['face_id']]['volume_m3']
        if W._decode(chosen):
            issued.append({k: row[k] for k in ('stock_id', 'physical_cell_id', 'direction',
                                              'face_id', 'physical_certificate_id')} | {'volume_m3': chosen})
    finite_cells = [r for r in closed['cells']+closed['inactive_zero_measure_cells'] if r['kind'] == 'finite-inventory']
    closed['cells'] = [r for r in closed['cells'] if r['kind'] != 'finite-inventory']
    closed['inactive_zero_measure_cells'] = [r for r in closed['inactive_zero_measure_cells'] if r['kind'] != 'finite-inventory']
    closed['transfers'] = [r for r in closed['transfers'] if not r.get('finite_exchange')]
    closed.update(schema='atlas.source-bound-spatial-ale-graph.v1',
        finite_exchanges=issued, finite_exchange_intervals=exchanges,
        finite_state_id=stock_record['state_id'], finite_owner_id=stock_record['owner_id'],
        selected_finite_inventory_volumes=finite_cells,
        material_quadrature_m3={key: _qtext(Q(value)) for key, value in material_quadrature_m3.items()},
        geometry_error_method='true-minus-selected G; carried signed start error rebased to selected G0 plus original directed stream intervals, intersected with original endpoint geometry',
        physical_outer_boundary='open only at issued finite supply/export interfaces; exact GCL includes retained finite inventories',
        inventory_selection='finite geometric source caps and sink storage in the same exact circulation; carried material B is independent',
        selection='joint geometric G0/G1/face representatives in original physical bounds; minimum exact L1 rebase from carried G')
    return closed


def _close_differential_record(record, start_volumes_m3, stock_record, budget, geometry_volume_errors=None,
                                material_quadrature_m3=None):
    """Select physical and finite-inventory volumes in ONE circulation.

    This is the private arithmetic seam, not a geometry issuer. Source stock
    end volume is in [0, V_start]; sink end volume is in [V_start,
    V_start+sum(incoming upper bounds)]. Thus finite exhaustion constrains the
    same choice as every physical endpoint and face bound. No closed physical
    graph is produced first, and no subsequent source addition repairs it.
    An end enclosure containing zero is not evidence of disappearance. Never
    release booked material beyond its certified physical stream intervals.
    """
    if material_quadrature_m3 is not None:
        return _close_dual_differential_record(record, start_volumes_m3, material_quadrature_m3,
            stock_record, budget, geometry_volume_errors)
    from . import integration_spatial_ale as A
    rows = stock_record['stocks']
    stocks = {r['stock_id']: r for r in rows}
    if len(stocks) != len(rows):
        raise V.VolumeError('unique retained finite stock identities required')
    physical = {r['cell_id'] for r in record['cells'] if r['kind'] != 'algebraic-port'}
    if any(r['kind'] == 'finite-inventory' for r in record['cells']):
        raise V.VolumeError('differential bounds must contain physical cells before inventory attachment')
    augmented = LIVE_FINITE.clone_mutable(record, ('cells', 'face_intervals', 'finite_exchange_intervals'), budget=budget)
    exchanges = augmented.pop('finite_exchange_intervals', [])
    if not isinstance(exchanges, list):
        raise V.VolumeError('complete certified finite exchange interval list required')
    starts = dict(start_volumes_m3)
    geometric_starts = {}
    if geometry_volume_errors is not None:
        if type(geometry_volume_errors) is not dict or set(geometry_volume_errors)-physical:
            raise V.VolumeError('carried geometric volume errors must name actual physical cells')
        # A true volume is not a booked stock. Preserve its signed interval
        # relative to the chosen FV representative, rather than resampling it.
        widths = {key: Q(0) for key in physical}
        for face in record['face_intervals']:
            lo, hi = map(W._decode, face['volume_bounds_m3'])
            for key in (face['donor'], face['receiver']):
                if key in widths:
                    widths[key] += hi-lo
        for face in exchanges:
            lo, hi = map(W._decode, face['volume_bounds_m3'])
            widths[face['physical_cell_id']] += hi-lo
        for row in augmented['cells']:
            key = row['cell_id']
            if key not in physical:
                continue
            value = Q(starts.get(key, 0))
            raw = geometry_volume_errors.get(key)
            if raw is None:
                if value and row['kind'] != 'collar':
                    raise V.VolumeError('positive carried exterior volume lacks its retained geometric error')
                raw = (Q(0), Q(0))
            if type(raw) not in (tuple, list) or len(raw) != 2:
                raise V.VolumeError('geometric volume error must be an exact signed pair')
            low, high = map(W._q, raw)
            if low > high:
                raise V.VolumeError('geometric volume error is reversed')
            if row['kind'] == 'collar' and (low or high):
                raise V.VolumeError('exact full Cartesian native cells cannot carry a geometric volume error')
            true_start = tuple(map(W._decode, row['start_volume_bounds_m3']))
            low, high = max(low, true_start[0]-value), min(high, true_start[1]-value)
            if low > high:
                raise V.VolumeError('carried true-start geometry is inconsistent with the new physical certificate')
            geometric_starts[key] = (low, high)
            true_end = tuple(map(W._decode, row['end_volume_bounds_m3']))
            row['true_start_volume_bounds_m3'] = row['start_volume_bounds_m3']
            row['true_end_volume_bounds_m3'] = row['end_volume_bounds_m3']
            row['start_geometry_volume_error_m3'] = list(map(_qtext, (low, high)))
            row['start_volume_bounds_m3'] = [_qtext(value)]*2
            # For any selected face within [l,u], |Ftrue-Fchosen| <= u-l.
            # This is an outer feasibility range, not a wider physical bound.
            bound = widths[key]
            row['end_volume_bounds_m3'] = list(map(_qtext,
                (max(Q(0), true_end[0]-high-bound), max(Q(0), true_end[1]-low+bound))))
            if row['kind'] == 'collar':
                row['end_volume_bounds_m3'] = row['true_end_volume_bounds_m3']
    maxima, used, face_ids = {}, set(), {r['face_id'] for r in record['face_intervals']}
    for row in exchanges:
        required = {'stock_id', 'physical_cell_id', 'direction', 'face_id',
                    'volume_bounds_m3', 'physical_certificate_id', 'stock_lineage'}
        if type(row) is not dict or set(row) != required:
            raise V.VolumeError('complete issued finite exchange geometry and lineage required')
        stock = stocks.get(row['stock_id'])
        if (stock is None or stock['lineage'] != row['stock_lineage'] or
                row['physical_cell_id'] not in physical or row['face_id'] in face_ids or
                type(row['physical_certificate_id']) is not str or not row['physical_certificate_id']):
            raise V.VolumeError('finite exchange stock lineage, physical support or certificate differs')
        direction = row['direction']
        if direction not in ('supply', 'export') or stock['kind'] not in (
                'reservoir', 'source' if direction == 'supply' else 'sink'):
            raise V.VolumeError('finite source/export direction differs from its actual retained stock')
        lo, hi = map(W._decode, row['volume_bounds_m3'])
        if lo < 0 or hi < lo:
            raise V.VolumeError('finite exchange must retain nonnegative certified bounds')
        stock_id = row['stock_id']; node = 'finite-stock:'+stock_id
        if node in physical:
            raise V.VolumeError('finite inventory identity collides with physical geometry')
        used.add(stock_id); face_ids.add(row['face_id'])
        if direction == 'export':
            maxima[stock_id] = maxima.get(stock_id, Q(0))+hi
        a, b = (node, row['physical_cell_id']) if direction == 'supply' else (row['physical_cell_id'], node)
        augmented['face_intervals'].append(dict(face_id=row['face_id'], donor=a, receiver=b,
            volume_bounds_m3=row['volume_bounds_m3'], finite_exchange=True,
            physical_certificate_id=row['physical_certificate_id']))
    for stock_id in sorted(used):
        stock = stocks[stock_id]; value = W._decode(stock['volume_m3'])
        if value < 0:
            raise V.VolumeError('negative retained finite stock volume')
        node = 'finite-stock:'+stock_id
        starts[node] = value
        end = ((Q(0), value) if stock['kind'] == 'source' else
               (Q(0) if stock['kind'] == 'reservoir' else value, value+maxima.get(stock_id, Q(0))))
        augmented['cells'].append(dict(cell_id=node, kind='finite-inventory', stock_id=stock_id,
            start_volume_bounds_m3=[_qtext(value)]*2, end_volume_bounds_m3=list(map(_qtext, end))))
    # The circulation is a selection inside the certified family. The heat
    # solve gives a cell to every component with a booked end volume and
    # needs a certified positive subset of it, so a member is sought that
    # books no end volume into a component whose certified end volume has no
    # positive lower bound: first for every such component, then only for
    # those that also carry no start volume, then in the complete family.
    # A trial only removes members: a closure found in it belongs to the
    # original family, and every certificate below is the same.
    true_end = 'true_end_volume_bounds_m3' if geometry_volume_errors is not None else 'end_volume_bounds_m3'
    unwitnessed = [row['cell_id'] for row in augmented['cells'] if row['cell_id'] in physical and
                   not W._decode(row[true_end][0]) and not W._decode(row['end_volume_bounds_m3'][0]) and
                   W._decode(row['end_volume_bounds_m3'][1])]
    trials = (unwitnessed, [key for key in unwitnessed if not Q(starts.get(key, 0))])
    # A component asked to end empty must pass on its whole start volume and
    # whatever its faces are certified to bring in. Where the certified upper
    # ends of its outgoing faces cannot carry that, the trial has no member
    # and is not run: every trial that is run is one complete circulation.
    incoming, outgoing = {}, {}
    if unwitnessed:
        for face in augmented['face_intervals']:
            low, high = map(W._decode, face['volume_bounds_m3'])
            incoming[face['receiver']] = incoming.get(face['receiver'], Q(0))+low
            outgoing[face['donor']] = outgoing.get(face['donor'], Q(0))+high
    blocked = lambda key: Q(starts.get(key, 0))+incoming.get(key, Q(0)) > outgoing.get(key, Q(0))
    closed = member = None
    circulations = 0
    for number, empty in enumerate(trials):
        if not empty or number and empty == trials[0] or any(map(blocked, empty)):
            continue
        chosen = set(empty)
        trial = dict(augmented, cells=[dict(row, end_volume_bounds_m3=[row['end_volume_bounds_m3'][0]]*2)
                                       if row['cell_id'] in chosen else row for row in augmented['cells']])
        circulations += 1
        try:
            closed = A._close_record(trial, starts, budget)
        except A.GCLInfeasible:
            continue
        outer = {row['cell_id']: row['end_volume_bounds_m3'] for row in augmented['cells'] if row['cell_id'] in chosen}
        for row in closed['cells']+closed['inactive_zero_measure_cells']:
            if row['cell_id'] in outer:
                row['end_volume_bounds_m3'] = outer[row['cell_id']]
        member = ('every component without a certified positive end volume',
                  'every such component that carries no start volume')[number]
        break
    if closed is None:
        circulations += 1
        closed = A._close_record(augmented, starts, budget)
    if unwitnessed:
        # Present only when such components exist, so other graphs keep their identity.
        closed['booked_end_selection'] = dict(
            components_without_certified_positive_end_volume=len(unwitnessed),
            zero_end_volume_booked_in=member or 'none: the certified family has no such member',
            circulations=circulations,
            rule='a member of the same certified circulation family; no bound, stream or volume is changed')
    if geometry_volume_errors is not None:
        errors = {key: list(pair) for key, pair in geometric_starts.items()}
        ports = {r['cell_id']: r['collar_cell_id'] for r in augmented['cells'] if r['kind'] == 'algebraic-port'}
        for face in closed['selected_face_representatives']:
            if face.get('partition_total'):
                continue
            low, high = map(W._decode, face['volume_bounds_m3'])
            chosen = W._decode(face['volume_m3'])
            low, high = low-chosen, high-chosen
            # Algebraic ports carry no material. Resolve them to the same
            # physical native owner as the conservative transport does.
            donor, receiver = ports.get(face['donor'], face['donor']), ports.get(face['receiver'], face['receiver'])
            if donor in errors:
                errors[donor][0] -= high; errors[donor][1] -= low
            if receiver in errors:
                errors[receiver][0] += low; errors[receiver][1] += high
        for row in closed['cells']+closed['inactive_zero_measure_cells']:
            key = row['cell_id']
            if key not in errors:
                continue
            value = W._decode(row['end_volume_m3'])
            physical_end = tuple(map(W._decode, row['true_end_volume_bounds_m3']))
            low, high = max(errors[key][0], physical_end[0]-value), min(errors[key][1], physical_end[1]-value)
            if low > high:
                raise V.VolumeError('strict stream error and endpoint physical volume certificates are inconsistent')
            row['geometry_volume_error_m3'] = list(map(_qtext, (low, high)))
        closed['geometry_error_method'] = 'true-minus-booked volume; carried signed start error plus original directed stream intervals, intersected with true endpoint geometry'
    selected = {r['face_id']: r for r in closed['selected_face_representatives']}
    issued = []
    for row in exchanges:
        chosen = selected[row['face_id']]['volume_m3']
        if W._decode(chosen):
            issued.append({k: row[k] for k in ('stock_id', 'physical_cell_id', 'direction',
                                              'face_id', 'physical_certificate_id')} | {'volume_m3': chosen})
    finite_cells = [r for r in closed['cells']+closed['inactive_zero_measure_cells'] if r['kind'] == 'finite-inventory']
    closed['cells'] = [r for r in closed['cells'] if r['kind'] != 'finite-inventory']
    closed['inactive_zero_measure_cells'] = [r for r in closed['inactive_zero_measure_cells'] if r['kind'] != 'finite-inventory']
    closed['transfers'] = [r for r in closed['transfers'] if not r.get('finite_exchange')]
    closed.update(finite_exchanges=issued, finite_exchange_intervals=exchanges,
        finite_state_id=stock_record['state_id'], finite_owner_id=stock_record['owner_id'],
        selected_finite_inventory_volumes=finite_cells,
        physical_outer_boundary='open only at issued finite supply/export interfaces; exact GCL includes retained finite inventories',
        inventory_selection='finite source caps and sink storage included in the same exact bounded circulation')
    return closed


def _circulation_failure(bounds_id, record, stock_record, start_volumes_m3, geometry_volume_errors, error):
    """Failure-only replay operands of the private closure seam.

    They are the already issued inputs of ``_close_differential_record`` and
    the exact cut it reported. Nothing is repaired, widened or admitted from
    them; replaying them reproduces the same refusal without native mechanics.
    """
    return dict(schema='atlas.differential-circulation-failure.v1',
        scope='reproducer operands only, never an issued graph or acceptance',
        bounds_id=bounds_id, bounds=LIVE_SPATIAL.reference(record), finite_stock_state=stock_record,
        start_volumes_m3={key: _qtext(Q(value)) for key, value in start_volumes_m3.items()},
        geometry_volume_errors={key: list(map(_qtext, map(W._q, pair)))
                                for key, pair in geometry_volume_errors.items()},
        cut_cell_ids=list(error.cut_cell_ids), incoming_lower_m3=_qtext(error.incoming_lower_m3),
        outgoing_upper_m3=_qtext(error.outgoing_upper_m3), unsatisfied_m3=_qtext(error.unsatisfied_m3))


def close_differential_ale(bounds, start_volumes_m3, finite_stock_state, *, budget,
                           geometry_volume_errors=None, material_quadrature_m3=None):
    """Close an issued interval against actual carried geometry and inventory.

    Returned graph keeps the physical prefix only. Its immutable selected
    ``finite_exchanges`` is precisely what PreparedFiniteStocks.prepare must
    attach and verify; inventories have already constrained that selection.
    Explicit material_quadrature_m3 selects the dual route: start_volumes_m3
    is G, retained errors are true-minus-G and material quadrature B is an
    independent extensive field. Omission preserves the legacy route.
    """
    from . import integration_spatial_ale as A
    from .integration_spatial_reservoir import FiniteStockState
    if (type(bounds) is not A.SpatialALEBounds or type(budget) is not WorkBudget or
            bounds._resource is not budget or type(finite_stock_state) is not FiniteStockState or
            finite_stock_state._owner._budget is not budget):
        raise V.VolumeError('issued differential bounds and actual finite stock on one shared budget required')
    finite_stock_state._owner._verify()
    with LIVE_SPATIAL.record_access(bounds) as record:
        # The original schema and lineage gates below still precede closure.
        if record.get('physical_geometry_family') != 'differential-plate-component-partition-v1':
            raise V.VolumeError('differential finite closure cannot reinterpret a common-rigid graph')
        if record.get('component_registry_id') != finite_stock_state._owner.definition()['registry_id']:
            raise V.VolumeError('finite inventory and physical graph component registries differ')
        if record.get('finite_owner_id') != finite_stock_state._owner.owner_id:
            raise V.VolumeError('certified finite definitions differ from the actual stock owner')
        if 'finite_state_id' in record and record['finite_state_id'] != finite_stock_state.state_id:
            raise V.VolumeError('certified finite state differs from the actual retained stock state')
        if type(start_volumes_m3) is not dict:
            raise V.VolumeError('actual carried physical volumes are required')
        if type(geometry_volume_errors) is not dict:
            raise V.VolumeError('differential continuation requires actual retained signed geometric volume errors')
        with LIVE_SPATIAL.workspace(budget, 65536+4*LIVE_SPATIAL.holder_bytes(bounds)+4*len(finite_stock_state._encoded)):
            try:
                result = _close_differential_record(record, start_volumes_m3, finite_stock_state.record(), budget,
                    geometry_volume_errors=geometry_volume_errors, material_quadrature_m3=material_quadrature_m3)
            except A.GCLInfeasible as error:
                error.circulation_failure = _circulation_failure(bounds.bounds_id, record,
                    finite_stock_state.record(), start_volumes_m3, geometry_volume_errors, error)
                if material_quadrature_m3 is not None:
                    error.circulation_failure['material_quadrature_m3'] = {
                        key: _qtext(Q(value)) for key, value in material_quadrature_m3.items()}
                raise
            result['bounds_id'] = bounds.bounds_id
            issued_graph = A._issue(A.SpatialALEGraph, result, budget)
            del result
            return issued_graph


def enclose_differential_ale(*args, **kwargs):
    """Source-issued interval graph; implementation kept beside its FV seam."""
    from .integration_differential_ale import enclose_differential_ale as issue
    return issue(*args, **kwargs)


def _voxel_projection_maximum(cell, normal):
    """max normal.(origin + basis*q) over the same closed Cartesian box.

Linearity separates the three local coordinates. A zero coefficient can
choose either endpoint, including exact contact. All inputs and results
remain rational. This does not rely on approximate orthogonality.
"""
    local = tuple(sum(normal[i] * cell.basis[i][j] for i in range(3))
                  for j in range(3))
    return sum(normal[i] * cell.origin_m[i] for i in range(3)) + sum(
        local[j] * (cell.upper_m[j] if local[j] >= 0 else cell.lower_m[j])
        for j in range(3))


def _corotating_plane_pair_zero_volume(cell, literals, constraints, arena, *, _query=None):
    """Exact axial positive combination of two co-rotating halfspaces.

    _rigid_plane_path supplies only homogeneous planes with proved coaxial
    histories. Equal (theta, omega) means the SAME rotation acts on both
    original normals. If positive weights cancel their transverse parts,
    the remaining nonzero axial normal is fixed by that rotation. A voxel
    on its nonpositive side then intersects the two positive literals only
    in a plane. This certifies zero 3-D volume, not zero wall area or flux.
    """
    # Supplied only by one immutable decoded component query. The first
    # pass keeps original parsing, arithmetic admissions and proof order.
    if _query is not None:
        if (_query is not getattr(arena, '_component_ray_cache', None)
                or _query.owner is not arena):
            raise V.VolumeError('pair impossibility belongs to another or closed query arena')
        if _query.impossible_pair_families & 1:
            return None
    possible = False
    # Plain moving-edge pairs already have their dedicated proof below.
    # Avoid repeating path algebra for that common case.
    if all(constraints[name]['kind'] == 'moving-ray-edge' for name, _ in literals):
        if _query is not None:
            _query.impossible_pair_families |= 1
        return None
    entries = []
    for name, sign in literals:
        if sign not in (-1, 1):
            continue
        path = _rigid_plane_path(constraints[name])
        if path is not None:
            normal, theta, omega = path
            axis = next((v for v in (omega, theta) if any(v)), None)
            if axis is not None and not any(O._cross(theta, omega)):
                entries.append((name, sign, tuple(sign*q for q in normal), theta, omega, axis))
    for i, (name1, sign1, first, theta, omega, axis) in enumerate(entries):
        for name2, sign2, second, theta2, omega2, _ in entries[i+1:]:
            if (theta, omega) != (theta2, omega2):
                continue
            with V._work((*first, *second, *theta, *omega, *axis), arena.resource):
                arena.work(128)
                u, v = O._cross(axis, first), O._cross(axis, second)
                j = next((j for j in range(3) if u[j]*v[j] < 0), None)
                if j is None:
                    continue
                alpha, beta = abs(v[j]), abs(u[j])
                if any(alpha*x+beta*y for x, y in zip(u, v)):
                    continue
                inward = tuple(alpha*x+beta*y for x, y in zip(first, second))
                if not any(inward):
                    continue
                # Beyond this point a decline is not query-global.
                possible = True
                maximum = _voxel_projection_maximum(cell, inward)
                if maximum <= 0:
                    return dict(kind='exact-corotating-two-plane-zero-volume',
                        literals=[[name1, sign1], [name2, sign2]],
                        positive_weights=list(map(_qtext, (alpha, beta))),
                        inward_axis=_store_vec(inward), voxel_axis_maximum=_qtext(maximum))
    if _query is not None and not possible:
        # No pair reached cell projection.
        # Store no operands or certificate; exceptions never reach this write.
        _query.impossible_pair_families |= 1
    return None


def _coaxial_edge_pair_zero_volume(cell, literals, constraints, a, b, level, arena, *, _query=None):
    """Certify zero 3-D volume from two true owner halfspaces and the voxel.

    For a shared ray p perpendicular to a common rotation axis A,
      (A.q)(f cross p) + (A.f)(p cross q) = det(f,p,q) A.
    Exact coaxial histories preserve all axial projections. Literal signs
    and edge ordering determine the combination weights; only positive
    weights and a strictly certified determinant sign are admitted. This is
    a volume certificate, NOT zero face area/flux or a rigid-vector identity.
    """
    # Supplied only by one immutable decoded component query. The first
    # pass keeps original parsing, arithmetic admissions and proof order.
    if _query is not None:
        if (_query is not getattr(arena, '_component_ray_cache', None)
                or _query.owner is not arena):
            raise V.VolumeError('pair impossibility belongs to another or closed query arena')
        if _query.impossible_pair_families & 2:
            return None
    possible = False
    entries = []
    for name, sign in literals:
        constraint = constraints[name]
        if constraint['kind'] != 'moving-ray-edge' or sign not in (-1, 1):
            continue
        paths = tuple((_load_vec(ray['direction']), _load_vec(ray['angular_velocity_rad_s']),
                       _history(ray.get('prior_rotations', ()))) for ray in constraint['rays'])
        entries.append((name, sign, paths))
    for i, (name1, sign1, first) in enumerate(entries):
        for name2, sign2, second in entries[i+1:]:
            shared = [(j, k) for j in range(2) for k in range(2) if first[j] == second[k]]
            if len(shared) != 1:
                continue
            j, k = shared[0]
            f, p, q = first[1-j], first[j], second[1-k]
            rotations = tuple(w for _, omega, prior in (f, p, q)
                              for w in (*(v for v, _ in prior), omega))
            axis = next((w for w in rotations if any(w)), None)
            if axis is None:
                continue
            operands = (*axis, a, b, *(x for path in (f, p, q) for x in path[0]),
                        *(x for w in rotations for x in w))
            with V._work(operands, arena.resource):
                arena.work(64+32*len(rotations))
                if (any(any(O._cross(axis, w)) for w in rotations) or O._dot(axis, p[0])):
                    continue
                # raw first edge = o1*(f cross p), raw second = o2*(p cross q).
                o1, o2 = (1 if j == 1 else -1), (1 if k == 0 else -1)
                alpha = sign1*o1*O._dot(axis, q[0])
                beta = sign2*o2*O._dot(axis, f[0])
                if alpha < 0 and beta < 0:
                    axis, alpha, beta = tuple(-x for x in axis), -alpha, -beta
                if alpha <= 0 or beta <= 0:
                    continue
                # Beyond this point a decline is not query-global.
                possible = True
                boxes = tuple(_ray_box(direction, omega, a, b, level, arena, prior)[2]
                              for direction, omega, prior in (f, p, q))
                determinant = _dot_bounds(boxes[0], _cross_bounds(boxes[1], boxes[2]))
                if determinant[0] > 0:
                    inward = axis
                elif determinant[1] < 0:
                    inward = tuple(-x for x in axis)
                else:
                    continue
                # Flipping the combination axis does not change determinant.
                # Positive combination implies inward.x>=0. A voxel entirely
                # on its nonpositive side intersects only the boundary plane.
                maximum = _voxel_projection_maximum(cell, inward)
                if maximum <= 0:
                    return dict(kind='exact-coaxial-two-edge-zero-volume',
                        literals=[[name1, sign1], [name2, sign2]],
                        combination_axis=_store_vec(axis), positive_weights=list(map(_qtext, (alpha, beta))),
                        determinant_bounds=list(map(_qtext, determinant)), inward_axis=_store_vec(inward),
                        voxel_axis_maximum=_qtext(maximum))
    if _query is not None and not possible:
        # No pair reached precision-dependent ray poses.
        # Store no operands or certificate; exceptions never reach this write.
        _query.impossible_pair_families |= 2
    return None


def _constraint_edge_ray_paths(constraint):
    """Exact ray paths underlying a homogeneous edge, including snapshots."""
    if constraint['kind'] == 'moving-ray-edge':
        return tuple((_load_vec(ray['direction']), _load_vec(ray['angular_velocity_rad_s']),
                      _history(ray.get('prior_rotations', ()))) for ray in constraint['rays'])
    if constraint['kind'] == 'snapshot-rotated':
        paths = _constraint_edge_ray_paths(constraint['constraint'])
        if paths is not None:
            offset = W._decode(constraint['snapshot_offset_s'])
            omega = _load_vec(constraint['angular_velocity_rad_s'])
            # A proper rotation carries a cross product into the cross
            # product of its rotated rays. Preserve the full ordered path.
            return tuple((direction, omega, (*prior, (old_omega, offset)))
                         for direction, old_omega, prior in paths)
    return None


def _common_ray_cone_zero_volume(literals, constraints, a, b, level, arena, *, cell=None):
    """Prove zero 3-D contact using literal edges or two separated ray cones.

    All THREE literal-directed cyclic edges and a strictly positive
    determinant establish each nonnegative ray cone by Cramer's rule.
    First try an active edge halfspace sharing an exact ray with a cone.
    Matched edge generators have structurally zero normal projection; all
    other cone generators must have strictly negative certified projection.
    The active edge requires the opposite sign, confining their intersection
    to its plane. This includes shared-edge and shared-ray contacts.

    If no such literal edge certifies zero, retain the two-cone separator:
    For a shared exact path f, N(t)=axis cross f(t) is exactly perpendicular
    to f. Strict opposite signs on the other generators separate the cones;
    their intersection is at most the shared ray, hence has zero 3-D volume.
    Finally, coaxial rotations preserve every generator's projection on the
    rotation axis. Cones in opposite closed axial halfspaces intersect only
    in their separating plane, even without a shared ray path. Both complete
    cycles must still have strictly positive certified determinants.
    A supplied voxel may instead supply the opposing halfspace: every cone
    generator must have nonpositive projection onto a voxel supporting axis
    whose minimum over the voxel is nonnegative. No shared ray is required.
    This says nothing about wall area/flux or rigid-plane identity.
    """
    entries = []
    for name, sign in literals:
        paths = _constraint_edge_ray_paths(constraints[name])
        if paths is not None and len(paths) == 2 and sign in (-1, 1):
            entries.append((name, sign, paths))
    if len(entries) < (3 if cell is not None else 4):
        return None
    paths = tuple(path for _, _, pair in entries for path in pair)
    rotations = tuple(w for _, omega, prior in paths for w in (*(v for v, _ in prior), omega))
    axis = next((w for w in rotations if any(w)), None)
    if axis is None:
        return None
    operands = (a, b, *(cell._geometry() if cell is not None else ()), *(q for direction, omega, prior in paths for q in
        (*direction, *omega, *(x for w, dt in prior for x in (*w, dt)))))
    with V._work(operands, arena.resource):
        arena.work(128+64*len(paths))
        if any(any(O._cross(axis, w)) for w in rotations):
            return None
        # Only the exact coaxial premise permits ordered history to become
        # one phase vector. Equal keys now mean equal rays for every t.
        def canonical(path):
            direction, omega, prior = path
            theta = tuple(sum((w[j]*dt for w, dt in prior), Q(0)) for j in range(3))
            return direction, omega, theta
        keys, ids, edges, adjacency = [], {}, {}, {}
        for name, sign, pair in entries:
            ij = []
            for path in pair:
                key = canonical(path)
                if key not in ids:
                    ids[key] = len(keys)
                    keys.append(key)
                ij.append(ids[key])
            i, j = ij if sign == 1 else ij[::-1]
            edges[i, j] = (name, sign)
            adjacency.setdefault(i, set()).add(j)
        triangles = []
        for i in adjacency:
            for j in sorted(adjacency[i]):
                for k in sorted(adjacency.get(j, ())):
                    arena.work(16)
                    if i < j and i < k and i in adjacency.get(k, ()):
                        triangles.append((i, j, k))
        boxes = {}
        def box(i):
            if i not in boxes:
                direction, omega, theta = keys[i]
                prior = ((theta, Q(1)),) if any(theta) else ()
                boxes[i] = _ray_box(direction, omega, a, b, level, arena, prior)[2]
            return boxes[i]
        determinants = {}
        def determinant(t):
            if t not in determinants:
                # Preserve original ordered pose/cache/validation calls even
                # when their interval coordinates are not needed below.
                first, second, third = box(t[0]), box(t[1]), box(t[2])
                if (keys[t[0]][1] == keys[t[1]][1] == keys[t[2]][1] and
                        keys[t[0]][2] == keys[t[1]][2] == keys[t[2]][2]):
                    # All histories were proved coaxial before canonical keys.
                    # Equal omega and phase give the SAME proper rotation R(t).
                    # det(Ru,Rv,Rw)=det(R)*det(u,v,w)=det(u,v,w), for every t.
                    # This encloses TRUE rays, not the approximate posed vectors.
                    value = O._dot(keys[t[0]][0], O._cross(keys[t[1]][0], keys[t[2]][0]))
                    determinants[t] = (value, value)
                else:
                    determinants[t] = _cone_dot_bounds(first, _cone_cross_bounds(second, third))
                arena.work(256)
            return determinants[t]
        # An edge is an ACTUAL active positive halfspace, already oriented
        # by its literal sign. Exact path matching, never a fitted pose,
        # makes each shared generator dot product identically zero.
        for triangle in triangles:
            for edge, literal in edges.items():
                arena.work(32)
                shared = tuple(i for i in triangle if i in edge)
                if not shared or edge[0] == edge[1]:
                    continue
                orientation = determinant(triangle)
                if orientation[0] <= 0:
                    continue
                # A forward cycle edge's only unshared projection is the
                # same cyclic positive determinant. It cannot be negative.
                # Retain determinant/ray validation and the original 32-unit
                # edge admission; omit only its impossible separator work.
                if ((edge[0] == triangle[0] and edge[1] == triangle[1]) or
                        (edge[0] == triangle[1] and edge[1] == triangle[2]) or
                        (edge[0] == triangle[2] and edge[1] == triangle[0])):
                    continue
                normal = _cone_cross_bounds(box(edge[0]), box(edge[1]))
                dots = tuple((Q(0), Q(0)) if i in shared else _cone_dot_bounds(normal, box(i))
                             for i in triangle)
                arena.work(128*(3-len(shared)))
                if all(dots[j][1] < 0 for j, i in enumerate(triangle) if i not in shared):
                    # A positive triangle has three independent generators;
                    # at least one is not an edge generator. Its strict
                    # negative projection also proves the edge normal nonzero.
                    return dict(kind='exact-literal-edge-cone-zero-volume',
                        triangle_literals=[list(edges[triangle[i], triangle[(i+1) % 3]]) for i in range(3)],
                        separator_literal=list(literal),
                        structural_zero_generator_indices=[j for j, i in enumerate(triangle) if i in shared],
                        determinant_bounds=list(map(_qtext, orientation)),
                        separator_dot_bounds=[list(map(_qtext, row)) for row in dots])
        axis_box = tuple((q, q) for q in axis)
        for at, first in enumerate(triangles):
            for second in triangles[at+1:]:
                arena.work(32)
                shared = set(first).intersection(second)
                if len(shared) != 1:
                    continue
                common = next(iter(shared))
                # Coaxial paths preserve an axial ray: its meridian normal
                # is identically zero and cannot separate positive cones.
                if not any(O._cross(axis, keys[common][0])):
                    continue
                orientation = tuple(determinant(t) for t in (first, second))
                if any(bounds[0] <= 0 for bounds in orientation):
                    continue
                normal = _cone_cross_bounds(axis_box, box(common))
                dots = tuple(tuple(_cone_dot_bounds(normal, box(i)) for i in t if i != common)
                             for t in (first, second))
                sides = tuple(-1 if all(v[1] < 0 for v in row) else
                              1 if all(v[0] > 0 for v in row) else 0 for row in dots)
                arena.work(256)
                if sides[0]*sides[1] == -1:
                    return dict(kind='exact-common-ray-cone-zero-volume',
                        triangle_literals=[[list(edges[t[i], t[(i+1) % 3]]) for i in range(3)]
                                           for t in (first, second)],
                        rotation_axis=_store_vec(axis),
                        common_ray_direction=_store_vec(keys[common][0]),
                        common_ray_angular_velocity=_store_vec(keys[common][1]),
                        common_ray_prior_phase=_store_vec(keys[common][2]),
                        determinant_bounds=[list(map(_qtext, row)) for row in orientation],
                        separator_dot_bounds=[[list(map(_qtext, v)) for v in row] for row in dots])
        # Distinct histories can move along the same invariant plane without
        # sharing a ray PATH. No approximate equality of normals or endpoints
        # is needed: all ordered rotations were proved coaxial above, hence
        # axis.R(t).direction == axis.direction exactly. Cramer's rule turns
        # the three active oriented halfspaces into the nonnegative cone only
        # when its determinant stays strictly positive on this whole query.
        projections = tuple(O._dot(axis, direction) for direction, _, _ in keys)
        arena.work(32*len(keys))
        sides = tuple(1 if all(projections[i] >= 0 for i in t) and any(projections[i] > 0 for i in t)
                      else -1 if all(projections[i] <= 0 for i in t) and any(projections[i] < 0 for i in t)
                      else 0 for t in triangles)
        for at, first in enumerate(triangles):
            for bt in range(at+1, len(triangles)):
                if sides[at]*sides[bt] != -1:
                    continue
                second = triangles[bt]
                orientation = tuple(determinant(t) for t in (first, second))
                if any(bounds[0] <= 0 for bounds in orientation):
                    continue
                return dict(kind='exact-axial-cones-zero-volume',
                    triangle_literals=[[list(edges[t[i], t[(i+1) % 3]]) for i in range(3)]
                                       for t in (first, second)],
                    rotation_axis=_store_vec(axis),
                    determinant_bounds=[list(map(_qtext, row)) for row in orientation],
                    invariant_axis_projections=[list(map(_qtext, (projections[i] for i in t)))
                                                for t in (first, second)],
                    scope='zero volume only; no face-area, flux or material-debit claim')
        if cell is not None:
            # Columns of the exact orthogonal voxel basis give nonzero
            # candidate separating normals. Their planes pass through the
            # sphere origin; a cone is homogeneous, so an offset is not fitted.
            vertices = cell._vertices()
            for j in range(3):
                for sign in (-1, 1):
                    normal = tuple(sign*cell.basis[i][j] for i in range(3))
                    minimum = min(O._dot(normal, p) for p in vertices)
                    arena.work(128)
                    if minimum < 0:
                        continue
                    normal_box = tuple((q, q) for q in normal)
                    for triangle in triangles:
                        dots = tuple(_cone_dot_bounds(normal_box, box(i)) for i in triangle)
                        arena.work(128)
                        if not all(v[1] <= 0 for v in dots):
                            continue
                        orientation = determinant(triangle)
                        if orientation[0] <= 0:
                            continue
                        return dict(kind='exact-cone-voxel-zero-volume',
                            triangle_literals=[list(edges[triangle[i], triangle[(i+1) % 3]]) for i in range(3)],
                            separator_normal=_store_vec(normal), voxel_minimum=_qtext(minimum),
                            determinant_bounds=list(map(_qtext, orientation)),
                            separator_dot_bounds=[list(map(_qtext, pair)) for pair in dots],
                            scope='zero volume only; no face-area, flux or material-debit claim')
    return None


def _clipped_voxel_edge_zero_volume(cell, literals, constraints, time, level, arena):
    """Separate an active edge from a voxel clipped by an exact fixed plane.

    Every true point lies in that clipped convex polyhedron P. If a nonzero
    active edge normal has nonpositive projection on EVERY vertex of P,
    its positive halfspace intersects P only in its plane: zero 3-D volume.
    Interval projections must prove the sign, not merely approximate zero.
    All clip-intersection vertices count. This proves no face-area/flux claim.
    """
    fixed, moving = [], []
    for name, sign in literals:
        if sign not in (-1, 1):
            continue
        constraint = constraints[name]
        path = _rigid_plane_path(constraint)
        if path is not None and not any(path[1]) and not any(path[2]):
            fixed.append((name, sign, path[0], Q(0)))
        elif constraint['kind'] == 'fixed-plane':
            normal = _load_vec(constraint['normal'])
            if any(normal):
                fixed.append((name, sign, normal, W._decode(constraint['offset'])))
        paths = _constraint_edge_ray_paths(constraint)
        if paths is not None and len(paths) == 2:
            moving.append((name, sign, paths))
    if not fixed or not moving:
        return None
    # A bounded one-plane clip, only after the existing root enclosure failed
    # to decide contact. Its polygons live in scratch, not in the certificate.
    with _PartitionScratch(arena) as scratch:
        box = B._owned_box(cell, scratch)
        normals = {}
        for fixed_name, fixed_sign, normal, offset in fixed:
            with V._work((*normal, offset), arena.resource):
                plane = (*( -fixed_sign*q for q in normal), -fixed_sign*offset)
            clipped = B._clip(box, plane, scratch)
            if not clipped:
                return dict(kind='exact-fixed-plane-voxel-zero-volume',
                    literal=[fixed_name, fixed_sign])
            points = B._points(clipped)
            for name, sign, paths in moving:
                if name == fixed_name:
                    continue
                cache_key = name, sign
                if cache_key not in normals:
                    boxes = tuple(_ray_box(direction, omega, time, time, level, arena, prior)[2]
                                  for direction, omega, prior in paths)
                    with V._work(tuple(q for box in boxes for pair in box for q in pair), arena.resource):
                        raw = _cross_bounds(*boxes)
                        normals[cache_key] = tuple(tuple(sorted(sign*q for q in pair)) for pair in raw)
                        scratch.keep(tuple(q for pair in normals[cache_key] for q in pair), objects=8)
                        arena.work(256)
                bounds = normals[cache_key]
                # Without a strictly nonzero component the equality set might
                # be all of space, so decline rather than discard material.
                if not any(lo > 0 or hi < 0 for lo, hi in bounds):
                    continue
                with V._work((*(q for pair in bounds for q in pair),
                              *(q for point in points for q in point)), arena.resource):
                    maxima = tuple(_dot_bounds(bounds, tuple((q, q) for q in point))[1] for point in points)
                    arena.work(64*len(points))
                    maximum = max(maxima)
                if maximum <= 0:
                    return dict(kind='exact-clipped-voxel-edge-zero-volume',
                        fixed_literal=[fixed_name, fixed_sign], separator_literal=[name, sign],
                        separator_normal_bounds=[list(map(_qtext, pair)) for pair in bounds],
                        clipped_vertex_count=len(points), maximum_projection=_qtext(maximum),
                        scope='zero volume only; no face-area, flux or material-debit claim')
    return None


def _component_cube_from_poly(kernel, poly, layer, cell, literals, posed, mask, arena):
    """Keep the centre funded through BOTH the work and arithmetic admissions.

    The existing admitted barycentre helpers return Fractions but do not retain
    them. Use their identical arithmetic admissions and computation here, and
    keep that lease open until the cube either retains its result or declines.
    A failure transfers the already held lease, without a new reservation.
    """
    from .integration_spatial_transport import _preserve_workspace
    with ExitStack() as admitted:
        centre = vertices = None
        if kernel is B:
            vertices = kernel._points(poly)
            admitted.enter_context(kernel._arithmetic(
                (*(v for point in vertices for v in point), len(vertices)), arena.resource))
        else:
            admitted.enter_context(kernel._work(
                poly.bits+V._bits(len(poly.points)), 3*len(poly.points)+1, arena.resource))
        try:
            centre = kernel._barycentre(poly)
            return _component_interior_cube(layer, cell, literals, posed, mask, arena, centre)
        except BaseException as failure:
            _failure_owner = _preserve_workspace(failure, admitted)
            raise
        finally:
            # On a decline no centre escapes. On success the cube's own keep
            # has admitted it before this arithmetic lease can be released.
            centre = vertices = None


def _component_interior_cube(layer, cell, literals, posed, mask, arena, centre):
    """Positive rational cube inside the SAME padded halfspaces and true shell.

    The Cartesian frame is an exact isometry. In local coordinates centred at
    q, |u+d|^2-|u|^2 is bounded by 2*r*sum|u|+3*r^2 for |d_j|<=r.
    Choose r<=1 and half the strict radial margin divided by 2*sum|u|+3.
    For each padded halfspace use half its strict centre slack divided by the
    L1 norm of its local normal. Convexity includes the whole cube in the
    padded angular halfspaces. The uniform radial bound holds at EVERY point
    of the cube, establishing shell inclusion without assuming a convex shell.
    Its exact volume is 8*r^3 and its exact vertex barycentre is the centre.
    A failed strict test declines; neither contact nor a missed sliver is zero.
    """
    from .integration_spatial_transport import _preserve_workspace
    values = (*cell._geometry(), *centre, layer.bottom_radius_m, layer.top_radius_m,
              *(q for normal, error, offset in posed.values() for q in (*normal, error, offset)))
    arena.work(160+64*len(literals))
    with ExitStack() as admitted:
        admitted.enter_context(V._work(values, arena.resource))
        local = radial_local = normal = local_normal = None
        radius = margin = squared = absolute = slack = coefficient = volume = upper = None
        try:
            local = tuple(sum(cell.basis[i][j]*(centre[i]-cell.origin_m[i]) for i in range(3)) for j in range(3))
            radial_local = tuple(sum(cell.basis[i][j]*centre[i] for i in range(3)) for j in range(3))
            squared = sum(q*q for q in radial_local)
            margin = min(squared-layer.bottom_radius_m**2, layer.top_radius_m**2-squared)
            if margin <= 0:
                return None
            radius = min(Q(1), *(min(q-a, b-q) for a, q, b in zip(cell.lower_m, local, cell.upper_m)),
                         margin/(2*(2*sum(abs(q) for q in radial_local)+3)))
            if radius <= 0:
                return None
            # Identical whole-cell padding to the existing inner clip plane.
            # It remains valid throughout this cube because the cube is inside
            # the original cell. No normal/rotation uncertainty is discarded.
            absolute = _voxel_absolute_scale(cell)
            for index, (name, sign) in enumerate(literals):
                if mask & (1 << index):
                    continue
                normal, error, offset = posed[name]
                slack = sign*(sum(n*p for n, p in zip(normal, centre))-offset)-error*absolute
                if slack <= 0:
                    return None
                local_normal = tuple(sum(normal[i]*cell.basis[i][j] for i in range(3)) for j in range(3))
                coefficient = sum(abs(q) for q in local_normal)
                if coefficient:
                    radius = min(radius, slack/(2*coefficient))
            # An exact dyadic radius no larger than the proved radius avoids
            # cubing a product of unrelated clipping denominators. This only
            # shrinks the new inner subset; it has no minimum size or float.
            exponent = radius.numerator.bit_length()-radius.denominator.bit_length()
            dyadic = Q(1 << exponent) if exponent >= 0 else Q(1, 1 << -exponent)
            if dyadic > radius:
                dyadic /= 2
            volume = 8*dyadic**3
            upper = math.prod(b-a for a, b in zip(cell.lower_m, cell.upper_m))
            if not 0 < volume <= upper:
                raise V.VolumeError('invalid certified interior cube volume')
            # The clipping arena owns escaped values until the caller admits
            # its answer slots; no proof graph survives the scratch workspace.
            arena.keep((*centre, volume, upper), objects=3)
            return volume, centre
        except BaseException as failure:
            _failure_owner = _preserve_workspace(failure, admitted)
            raise
        finally:
            values = local = centre = radial_local = normal = local_normal = None
            radius = margin = squared = absolute = slack = coefficient = volume = upper = dyadic = None


def _component_volume_leaf(layer, cell, literals, constraints, time, level, arena, *, witness_point=False,
                           detail=None, _clip_arena=None, _posed=None, _mask=0, _radial=None, _cone_query=None, _loose_witness=False):
    clipping = arena if _clip_arena is None else _clip_arena
    if clipping.resource is not arena.resource:
        raise V.VolumeError('component clipping must share the query budget')
    minimum, maximum = cell._radial_bounds() if _radial is None else _radial
    lower2, upper2 = layer.bottom_radius_m**2, layer.top_radius_m**2
    if minimum >= upper2 or maximum <= lower2:
        return ((Q(0), Q(0)), None) if witness_point else (Q(0), Q(0))
    # One sufficient proof at the endpoint root only. It does not certify
    # wall area/flux, change material accounts, or recur on every child.
    if detail is not None and level == 0:
        from .integration_cone_zero import certificate
        if certificate(cell, literals, constraints, time, arena, detail=detail) is not None:
            return ((Q(0), Q(0)), None) if witness_point else (Q(0), Q(0))
    contained = _mask == (1 << len(literals))-1
    zero_certificate = None if contained else _corotating_plane_pair_zero_volume(cell, literals, constraints, arena, _query=_cone_query)
    if zero_certificate is not None:
        if detail is not None:
            detail['corotating_pair_zero_volume'] = zero_certificate
        return ((Q(0), Q(0)), None) if witness_point else (Q(0), Q(0))
    zero_certificate = None if contained else _coaxial_edge_pair_zero_volume(cell, literals, constraints, time, time, level, arena, _query=_cone_query)
    if zero_certificate is not None:
        if detail is not None:
            detail['coaxial_pair_zero_volume'] = zero_certificate
        return ((Q(0), Q(0)), None) if witness_point else (Q(0), Q(0))
    # This token is supplied only by one decoded component query, whose
    # ordered literals, constraints and exact endpoint time remain fixed.
    # Preserve the original proof position; each unseen precision recomputes.
    # Successful certificates are returned normally, never stored here.
    if _cone_query is not None and (
            _cone_query is not getattr(arena, '_component_ray_cache', None) or
            _cone_query.owner is not arena):
        raise V.VolumeError('cone decline belongs to another or closed query arena')
    cone_bit = 1 << level if _cone_query is not None and 0 <= level < 64 else 0
    zero_certificate = None
    if not contained and (not cone_bit or not (_cone_query.declined_cone_levels & cone_bit)):
        zero_certificate = _common_ray_cone_zero_volume(literals, constraints, time, time, level, arena)
        if zero_certificate is None and cone_bit:
            # Bounded integer bookkeeping only; no geometric arithmetic or
            # expandable level collection is performed by a reuse hit.
            _cone_query.declined_cone_levels |= cone_bit
    if zero_certificate is not None:
        if detail is not None:
            detail['common_ray_cone_zero_volume'] = zero_certificate
        return ((Q(0), Q(0)), None) if witness_point else (Q(0), Q(0))
    # Keep all existing successful proofs first. This root-only test can also
    # recognise a single rotating plane touching the voxel on an edge/point.
    # A decline changes neither the padded geometry nor subsequent refinement.
    if detail is not None and level == 0 and not contained:
        from .integration_cone_zero import plane_certificate
        if plane_certificate(cell, literals, constraints, time, arena, detail=detail) is not None:
            return ((Q(0), Q(0)), None) if witness_point else (Q(0), Q(0))
    posed = _posed if _posed is not None else {
        name: _constraint_pose(constraints[name], time, time, level, arena) for name, _ in literals}
    radial_partial = not (minimum >= lower2 and maximum <= upper2)
    if radial_partial:
        centre = tuple(cell.origin_m[i]+sum(cell.basis[i][j]*(cell.lower_m[j]+cell.upper_m[j])/2 for j in range(3)) for i in range(3))
        squared = O._dot(centre, centre)
        residual = sum(((b-a)/2)**2 for a, b in zip(cell.lower_m, cell.upper_m))
        gradient = tuple(2*q for q in centre)
    values = []
    point = None
    # One exact kernel from the box to both volumes. Planes enter once; the
    # two volumes and the witness point leave as Fractions; no polyhedron does.
    K = B._resident()
    box = K._owned_box(cell, clipping)
    # The mask already removes a literal from BOTH angular clip loops.
    # Issued child certificates pose/validate every active constraint before
    # reaching here; a newly contained inexact pose is now inactive. Preserve
    # the original no-mask selector for root/detail and ordinary direct calls.
    exact_angular = (all(not posed[name][1] for index, (name, _) in enumerate(literals)
                         if not _mask & (1 << index)) if _mask else
                     all(not error for _, error, _ in posed.values()))
    angular, scale = None, []
    angular_candidate = None
    angular_volume = False
    # Plan19 diagnostic successor: this is an already funded immutable
    # intermediate from the ORIGINAL inner clipping path. Keep every
    # original clip, volume, witness and zero-proof call before using it.
    bottom_surrogate_candidate = None
    repeat_volume = getattr(K, '_repeat_volume_exact', None)
    for inner in (True, False):
        if not inner and exact_angular:
            # Zero pose error makes the two angular halfspace lists identical.
            # _clip returns immutable tuples: retain this pre-radial polyhedron,
            # never the inner radial result, for the unchanged outer branch.
            poly = angular
        else:
            poly = box
            for index, literal in enumerate(literals):
                if _mask & (1 << index):
                    continue
                poly = K._clip(poly, K._plane(_literal_plane(literal, posed, cell, inner, scale)), clipping)
                if not poly:
                    break
            if exact_angular:
                angular = poly
        if inner and _loose_witness:
            angular_candidate = poly
        if inner and detail is not None:
            # The inner polyhedron of the literal (angular) planes alone,
            # before either radial plane. Only this part depends on the pose.
            # A cell that misses the shell returns above and reports nothing.
            detail['angular_inner_empty'] = not poly
        if radial_partial:
            for radial_index, plane in enumerate((
                    (*gradient, upper2+squared-(residual if inner else 0)),
                    (*(-q for q in gradient), -lower2-squared+(0 if inner else residual)))):
                poly = K._clip(poly, K._plane(plane), clipping)
                if inner and radial_index == 0 and minimum >= lower2:
                    # radial_partial plus the satisfied bottom boundary
                    # means an actual top crossing (early misses returned).
                    bottom_surrogate_candidate = poly
                elif inner and radial_index == 1 and poly is bottom_surrogate_candidate:
                    # The original bottom clip was an identity no-op.
                    # Its funded volume/witness below already use this
                    # exact object, so no strengthening is possible.
                    bottom_surrogate_candidate = None
        if not inner and angular_volume and poly is angular and repeat_volume is not None:
            # The same angular object is already retained by this leaf.
            # Its exact first result is already present in values.
            values.append(repeat_volume(poly, clipping, values[0]))
        else:
            values.append(K._volume_exact(poly, clipping))
        if inner:
            angular_volume = poly is angular
        if witness_point and inner and values[-1] > 0:
            # Positive convex inner volume guarantees this positive-weight
            # barycentre lies strictly inside its non-redundant faces. It is
            # inside TRUE radial/cone support, not only the thermal surrogate.
            point = K._barycentre_admitted(poly, clipping)
    if (detail is not None and level == 0 and not values[0] and values[1]
            and detail['angular_inner_empty']):
        certificate = _common_ray_cone_zero_volume(literals, constraints, time, time, level, arena, cell=cell)
        proof_key = 'common_ray_cone_zero_volume'
        if certificate is None:
            certificate = _clipped_voxel_edge_zero_volume(cell, literals, constraints, time, level, arena)
            proof_key = 'clipped_voxel_edge_zero_volume'
        if certificate is not None:
            detail[proof_key] = certificate
            return ((Q(0), Q(0)), None) if witness_point else (Q(0), Q(0))
    if (_loose_witness and witness_point and angular_candidate and
            not values[0] and values[1]):
        cube = _component_cube_from_poly(K, angular_candidate, layer, cell,
                                         literals, posed, _mask, clipping)
        if cube is not None:
            volume, point = cube
            if volume > values[1]:
                raise V.VolumeError('interior cube contradicts certified outer volume')
            # Preserve the original exact outer bound, strengthening only the
            # old zero lower bound with an independently certified inner cube.
            values[0] = volume
    if bottom_surrogate_candidate and values[1]:
        # The full original leaf, including late contact proofs and the
        # loose cube witness, has completed. This extra work is funded;
        # its refusal propagates and never falls back to an old result.
        clipping.work(16)
        stronger = K._volume_exact(bottom_surrogate_candidate, clipping)
        if not 0 <= stronger <= values[1]:
            raise V.VolumeError(
                'Plan19 bottom-surrogate successor contradicts outer bound')
        if stronger > values[0]:
            if witness_point:
                point = K._barycentre_admitted(bottom_surrogate_candidate, clipping)
            values[0] = stronger
    return (tuple(values), point) if witness_point else tuple(values)


def _padded_box_contained(cell, normal, error, offset, sign, arena):
    # For every x in the cell, |(n_true-n).x| <= error*sum_j max_cell|x_j|.
    # Max(-sign*n.x) <= -sign*offset-padding therefore proves the TRUE
    # halfspace contains the entire box. Every descendant is a subset of it;
    # the bit records this geometric fact, not equality of rounded poses.
    from .integration_spatial_transport import _preserve_workspace
    arena.work(128)
    with ExitStack() as admitted:
        n = local = absolute = maximum = threshold = None
        low = high = column = None
        admitted.enter_context(V._work((*normal, error, offset, *cell._geometry()), arena.resource))
        try:
            absolute = Q(0)
            for i in range(3):
                low = cell.origin_m[i]+sum(cell.basis[i][j]*(cell.lower_m[j] if cell.basis[i][j] >= 0 else cell.upper_m[j]) for j in range(3))
                high = cell.origin_m[i]+sum(cell.basis[i][j]*(cell.upper_m[j] if cell.basis[i][j] >= 0 else cell.lower_m[j]) for j in range(3))
                absolute += max(abs(low), abs(high))
            n = tuple(-sign*q for q in normal)
            local = tuple(sum(n[i]*cell.basis[i][j] for i in range(3)) for j in range(3))
            maximum = sum(n[i]*cell.origin_m[i] for i in range(3))+sum(
                local[j]*(cell.upper_m[j] if local[j] >= 0 else cell.lower_m[j]) for j in range(3))
            threshold = -sign*offset-error*absolute
            return maximum <= threshold
        except BaseException as failure:
            _failure_owner = _preserve_workspace(failure, admitted)
            raise
        finally:
            n = local = absolute = maximum = threshold = None
            low = high = column = cell = normal = None


def _component_volume_certificate(layer, cell, literals, constraints, time, level, arena, *,
                                  detail=None, _clip_arena=None, mask=0, _cone_query=None, _loose_witness=False):
    """Volume enclosure, explicit point, inherited mask and independent witness.

    Bits prove whole-box containment in the TRUE angular halfspace. Descendant
    boxes inherit them; inexact poses must include their full error pad. The root
    and pose-detail calls keep the old zero-first path. Only clean single-sphere
    children use quadrature; all other cases retain the original enclosure.
    """
    clipping = arena if _clip_arena is None else _clip_arena
    if clipping.resource is not arena.resource:
        raise V.VolumeError('component clipping must share the query budget')
    if detail is not None:
        bounds, point = _component_volume_leaf(layer, cell, literals, constraints, time, level,
            arena, witness_point=True, detail=detail, _clip_arena=clipping, _cone_query=_cone_query, _loose_witness=_loose_witness)
        return bounds, point, mask, bounds[0]
    radial_bounds = cell._radial_bounds()
    minimum, maximum = radial_bounds
    if minimum >= layer.top_radius_m**2 or maximum <= layer.bottom_radius_m**2:
        return (Q(0), Q(0)), None, mask, Q(0)
    zero_volume = False
    posed = {}
    for index, (name, sign) in enumerate(literals):
        if mask & (1 << index):
            continue
        normal, error, offset = _constraint_pose(constraints[name], time, time, level, arena)
        posed[name] = (normal, error, offset)
        if error:
            continue  # D1: item 15 off (no padded containment for inexact poses, as r7)
        clipping.work(64)
        with V._work((*normal, offset, *cell._geometry()), clipping.resource):
            # The literal means (-sign*n).x <= -sign*offset. Maximise this
            # linear functional over the Cartesian box in its exact frame.
            n = tuple(-sign*q for q in normal)
            local = tuple(sum(n[i]*cell.basis[i][j] for i in range(3)) for j in range(3))
            maximum = sum(n[i]*cell.origin_m[i] for i in range(3)) + sum(
                local[j]*(cell.upper_m[j] if local[j] >= 0 else cell.lower_m[j]) for j in range(3))
            if maximum <= -sign*offset:
                mask |= 1 << index
            elif not zero_volume and any(n):
                # Same exact functional; the least value on the box excludes
                # its positive-volume interior when it is >= the clip offset.
                # A zero normal could make equality all of space, so decline.
                # Admit the additional endpoint arithmetic before evaluating it.
                clipping.work(32)
                plane_minimum = sum(n[i]*cell.origin_m[i] for i in range(3)) + sum(
                    local[j]*(cell.lower_m[j] if local[j] >= 0 else cell.upper_m[j]) for j in range(3))
                zero_volume = plane_minimum >= -sign*offset
                del plane_minimum
    clipping.keep((mask,), objects=1)
    # Finish every active pose and containment admission before returning.
    # In particular, an earlier exclusion cannot conceal a malformed later
    # literal or its mandatory pose/containment resource refusal.
    if zero_volume:
        return (Q(0), Q(0)), None, mask, Q(0)
    if mask == (1 << len(literals))-1:
        answer = SQ.enclose(layer, cell, clipping)
        if answer is not None:
            bounds, witness, point, _ = answer
            if not witness and bounds[1]:
                # A positive integral bound is not an interior-point proof.
                # Try the old witness once; if still absent the driver must
                # keep subdividing or return an unmet result.
                old, point = _component_volume_leaf(layer, cell, literals, constraints, time, level,
                    arena, witness_point=True, _clip_arena=clipping, _posed=posed, _mask=mask, _radial=radial_bounds, _cone_query=_cone_query, _loose_witness=_loose_witness)
                witness = old[0]
            return bounds, point, mask, witness
    bounds, point = _component_volume_leaf(layer, cell, literals, constraints, time, level,
        arena, witness_point=True, _clip_arena=clipping, _posed=posed, _mask=mask, _radial=radial_bounds, _cone_query=_cone_query, _loose_witness=_loose_witness)
    return bounds, point, mask, bounds[0]


def _wall_failure_payload(support_record, query, budget, error, *, measure=None,
                          budget_scope='failed inner scratch has unwound'):
    """One failure-only wall replay contract for resource and precision refusals."""
    requests, arithmetic, tb = [], [], error.__traceback__
    while tb is not None:
        frame = tb.tb_frame
        if frame.f_code.co_name == '_admit_budgets':
            requests.append(dict(requested_bytes=frame.f_locals.get('count'),
                                 category=frame.f_locals.get('category')))
        if frame.f_code.co_name == '_work' and 'bits' in frame.f_locals:
            arithmetic.append(dict(input_bits=frame.f_locals['bits'], pairs=frame.f_locals.get('pairs')))
        tb = tb.tb_next
    return dict(support=support_record, query=query, measure=measure,
        exception_type=type(error).__name__, requested_reservations=requests,
        arithmetic_requests=arithmetic, budget_at_dispatch_unwind=budget.statistics(), budget_scope=budget_scope)


def _volume_outward(pair, quantum):
    """Pack outward, without erasing a positive volume's entire size scale.

    The absolute error allocation is a ceiling, not a minimum cell volume.
    If its grid would replace a sub-quantum upper bound by one whole quantum,
    keep 53 binary significant bits in that upper bound instead. The exponent
    is unbounded and all rounding is rational/outward: no positive volume is
    zeroed and no physical criterion changes. The lower bound and ordinary
    records retain their existing encoding. This only narrows an enclosure.
    """
    low, high = W._outward(pair, quantum)
    upper = pair[1]
    if quantum and 0 < upper < quantum:
        # _quantum(u, 2**50) <= u * 2**-52. Thus the extra upper
        # padding is < u * 2**-52, and below the absolute allocation.
        fine = W._quantum(upper, 1 << 50)
        high = W._outward((Q(0), upper), fine)[1]
    return low, high


class _ComponentVolumeStorage:
    """Reusable local slots plus exactly the currently queued leaf capacity.

    Four local slots cover root/parent/two children and their escaped answers;
    queued leaves have a separate charge. Replaced leaves never accumulate in
    the byte ledger. Predicate work remains cumulative on the original arena.
    """
    def __init__(self, arena):
        from .resources import _ResizableLease
        self.arena = arena
        self.local = {'cell': 0, 'answer': 0}
        self.queue = arena.stack.enter_context(_ResizableLease(
            arena.resource, category='component-volume-live-queue'))

    @staticmethod
    def size(values, objects):
        return 1024+128*len(values)+128*objects+4*sum((V._bits(v)+7)//8 for v in values)

    def workspace(self, kind, values, objects):
        capacity = 4*self.size(values, objects)
        if capacity > self.local[kind]:
            self.arena.stack.enter_context(self.arena.resource.reserve(
                capacity-self.local[kind], category='component-volume-live-workspace'))
            self.local[kind] = capacity

    def push(self, queue, item):
        priority, serial, cell, depth, low, high, mask = item
        size = self.size((*cell._geometry(), priority, serial, depth, low, high, mask), 16)
        self.queue.resize(self.queue.count+size)
        # serial is unique, so ordering never compares cells or this charge.
        # On an exceptional partial heap mutation keep the admitted capacity
        # until the operation/error owner dies, rather than assume rollback.
        heapq.heappush(queue, (*item, size))

    def pop(self, queue):
        *item, size = heapq.heappop(queue)
        # Popped cell/answer aliases now belong to the prepaid local slots.
        self.queue.resize(self.queue.count-size)
        return item


def component_volume_bounds(support, logical_cell_id, *, endpoint, max_width_m3,
                            max_leaves, positive_witness=False, budget, relative_error=None):
    """Physical volume of the SAME convex component used by graph and heat.

    Positive witnesses are exact inner subsets of true geometry, never the
    thermal facet's positive volume. Unmet error/work bounds remain explicit.
    Explicit relative accuracy shares the same subdivision queue and requires
    both width limits before stopping; it never raises the caller's leaf ceiling.
    """
    if type(support) is not DifferentialSupport or support._resource is not budget or endpoint not in ('start', 'end'):
        raise V.VolumeError('issued support, same budget and explicit endpoint required')
    from .integration_routing_views import RoutingArena, _decoded_json_capacity, _decode_workspace
    with RoutingArena(budget) as arena:
        # Encoded ownership is separate from this actual decoded query input.
        # Reserve it BEFORE decode, including the record() identity field.
        arena.stack.enter_context(budget.reserve(4096+_decoded_json_capacity(support._json),
                                               category='component-volume-decoded-input'))
        decoder = ExitStack()
        try:
            decoder.enter_context(budget.reserve(_decode_workspace(support._json),
                                                 category='component-volume-decoder'))
            record = support.record()
        except BaseException:
            arena.stack.callback(decoder.close)
            raise
        else:
            decoder.close()
        return _component_volume_bounds_decoded(support, logical_cell_id, record, arena,
            endpoint=endpoint, max_width_m3=max_width_m3, max_leaves=max_leaves,
            positive_witness=positive_witness, budget=budget, relative_error=relative_error)


def _component_longest_side(cell, arena, depth=None, _query=None):
    # Every depth-d descendant has the same local side lengths: all ancestors
    # at the same depth choose the same axis, then exactly halve it. Location
    # and refinement-queue order do not enter this effort-only rule.
    if _query is not None:
        if (_query is not getattr(arena, '_component_ray_cache', None) or
                _query.owner is not arena or type(depth) is not int or depth < 0):
            raise V.VolumeError('split schedule belongs to another or closed query arena')
        if _query.split_axis_bits >> 128:
            return depth % 3
        if depth < 64:
            code = (_query.split_axis_bits >> (2*depth)) & 3
            if code:
                return code-1
    from .integration_spatial_transport import _preserve_workspace
    arena.work(16)
    with ExitStack() as admitted:
        widths = None
        admitted.enter_context(V._work((*cell.lower_m, *cell.upper_m), arena.resource))
        try:
            widths = tuple(b-a for a, b in zip(cell.lower_m, cell.upper_m, strict=True))
            longest = max(range(3), key=widths.__getitem__)
            if depth is None:
                return longest
            cyclic = depth % 3
            axis = longest if widths[longest] >= 2*widths[cyclic] else cyclic
            if _query is not None:
                # If all root sides differ by less than one halving, the
                # cyclic axis can never be a full halving too small at any
                # descendant. Preserve that entire original schedule.
                if depth == 0 and widths[longest] < 2*min(widths):
                    _query.split_axis_bits = 1 << 128
                elif depth < 64:
                    _query.split_axis_bits |= (axis+1) << (2*depth)
            return axis
        except BaseException as error:
            _failure_owner = _preserve_workspace(error, admitted)
            raise
        finally:
            widths = cell = None


def _component_split_failure(record, logical_cell_id, endpoint, width,
        max_leaves, positive_witness, relative_error, parent, depth, offset,
        arena, storage, error):
    # The caller has discarded obsolete child/list local aliases. The two
    # original child-cell slots now fund this fixed-size metadata graph, not
    # another copy of the decoded support or any new rational/hex encoding.
    # The other two local slots still cover the root and selected parent.
    metadata_bytes = 8192
    available = storage.local['cell']//2
    if available < metadata_bytes:
        raise V.VolumeError('split replay metadata exceeds prepaid child slots')
    request = arithmetic = predicate = None
    if hasattr(error, 'requested_units'):
        predicate = dict(requested_units=error.requested_units,
                         category=error.category)
    tb = error.__traceback__
    while tb is not None:
        frame = tb.tb_frame
        name = frame.f_code.co_name
        if name == '_admit_budgets' and request is None:
            request = dict(requested_count=frame.f_locals.get('count'),
                           category=frame.f_locals.get('category'))
        elif name == '_work' and arithmetic is None and 'bits' in frame.f_locals:
            arithmetic = dict(input_bits=frame.f_locals['bits'],
                              pairs=frame.f_locals.get('pairs'))
        elif name == 'work' and predicate is None and frame.f_locals.get('self') is arena:
            predicate = dict(requested_units=frame.f_locals.get('count'),
                             category='curved-volume-work')
        tb = tb.tb_next
    frame = None
    return dict(schema='atlas.differential-component-split-failure.v1',
        failed_operation='component_split_axis_selection',
        recording_contract='borrowed exact Fraction geometry; encode only under a separately funded recorder',
        support=record,
        query=dict(logical_cell_id=logical_cell_id, endpoint=endpoint,
                   max_width_m3=width, max_leaves=max_leaves,
                   positive_witness=positive_witness, relative_error=relative_error),
        failed_split=dict(parent_cell=dict(lower_m=parent.lower_m, upper_m=parent.upper_m,
            origin_m=parent.origin_m, basis=parent.basis), depth=depth, pose_offset=offset),
        exception_type=type(error).__name__, requested_reservation=request,
        arithmetic_request=arithmetic, predicate_work_request=predicate,
        budget_at_split_unwind=dict(reserved_bytes=arena.resource.reserved_bytes,
            max_bytes=arena.resource.max_bytes, work_units=arena.work_units,
            max_predicate_work_units=arena.resource.max_predicate_work_units),
        funding=dict(category='component-volume-live-workspace',
                     reused_child_slot_bytes=available, metadata_limit_bytes=metadata_bytes),
        budget_scope='outer operation owner remains live; no child was attempted at this split')


def _encode_component_split_failure(payload, budget):
    # Explicit new recorder boundary. Historical component_volume_failure
    # reporters and their failed_leaf schema are untouched.
    from .integration_routing_views import _FailureOwner, _OwnedPayload
    if (type(payload) is not _OwnedPayload or
            payload.get('schema') != 'atlas.differential-component-split-failure.v1'):
        raise V.VolumeError('owned raw split diagnostic required')
    raw = payload['failed_split']['parent_cell']
    query = payload['query']
    values = (*raw['lower_m'], *raw['upper_m'], *raw['origin_m'],
              *(v for row in raw['basis'] for v in row), query['max_width_m3'])
    if query['relative_error'] is not None:
        values += (query['relative_error'],)
    stack = ExitStack()
    owner = _FailureOwner(stack)
    stack.enter_context(V._work(values, budget))
    # Encoded support is borrowed, not recopied. The encoded result therefore
    # also retains the source diagnostic's original input/parent owner.
    stack.callback(lambda _source=payload: None)
    legacy = all(v in (-1, 0, 1) for row in raw['basis'] for v in row)
    cell = dict(schema='atlas.exact-cartesian-cell.v1' if legacy else 'atlas.exact-cartesian-cell.v2',
        lower_m=list(map(_qtext, raw['lower_m'])), upper_m=list(map(_qtext, raw['upper_m'])),
        origin_m=list(map(_qtext, raw['origin_m'])),
        basis=[[(int(v) if legacy else _qtext(v)) for v in row] for row in raw['basis']],
        number_encoding='rational-hex-v1',
        frame_rule='basis columns are local axes in sphere-centred Cartesian XYZ')
    encoded_query = dict(query, max_width_m3=_qtext(query['max_width_m3']))
    if query['relative_error'] is None:
        del encoded_query['relative_error']
    else:
        encoded_query['relative_error'] = _qtext(Q(query['relative_error']))
    encoded = dict(payload, schema='atlas.differential-component-split-replay.v1',
        recording_contract='JSON-compatible exact parent descriptor; not a failed_leaf record',
        query=encoded_query, failed_split=dict(payload['failed_split'], parent_cell=cell))
    return _OwnedPayload(encoded, owner)


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


# Optional bounded progress recorder (runner option; None = off, no effect).
_GEOMETRY_PROGRESS = None


def _component_volume_bounds_decoded(support, logical_cell_id, record, arena, *,
        endpoint, max_width_m3, max_leaves, positive_witness, budget, relative_error, _funded=None, _checkpoint=None):
    component = next((c for c in record['components'] if c['logical_cell_id'] == logical_cell_id), None)
    if component is None:
        raise V.VolumeError('unknown physical support component')
    width = W._q(max_width_m3)
    if width < 0 or type(max_leaves) is not int or max_leaves < 1:
        raise V.VolumeError('explicit nonnegative volume error and positive leaf limit required')
    if _GEOMETRY_PROGRESS is not None:
        _GEOMETRY_PROGRESS.start('endpoint', support.support_id, logical_cell_id, endpoint,
                                 literals=len(component['constraints']))
    if relative_error is not None and (type(relative_error) not in (int, Q) or not 0 <= relative_error < 1):
        raise V.VolumeError('explicit exact local relative error below one required')
    layer_record = record['radial_layer']
    layer = V.RadialLayer(*(W._decode(layer_record[key]) for key in ('radius_m', 'top_depth_m', 'bottom_depth_m')), budget=budget)
    cell = V.CartesianCell.from_record(record['voxel'], budget=budget)
    time = Q(0) if endpoint == 'start' else W._decode(record['duration_s'])
    quantum = W._quantum(width, max_leaves)
    # Durable completed-query reuse has distinct provenance from a live worker.
    if _checkpoint is not None and positive_witness is True and relative_error is None:
        from .integration_endpoint_checkpoints import EndpointCheckpoints
        from .integration_component_volume_parallel import request_for
        if type(_checkpoint) is not EndpointCheckpoints:
            raise TypeError("native endpoint checkpoint owner required")
        request = request_for(support, logical_cell_id, endpoint,
                              record[endpoint+'_time_s'], width, max_leaves)
        resumed = _checkpoint.before(support, request, budget)
        if resumed is not None:
            return resumed
    # Optional endpoint adoption comes only after the unchanged mandatory
    # component/query/layer/cell/time/quantum prefix. Other modes stay serial.
    if _funded is not None and positive_witness is True and relative_error is None:
        from .integration_component_volume_parallel import request_for
        request = request_for(support, logical_cell_id, endpoint,
                              record[endpoint+'_time_s'], width, max_leaves)
        funded = _funded(request, budget)
        if funded is not None:
            from .integration_parallel_results import adopt
            return adopt(DifferentialMeasure, funded, budget)
    # The full root box plus outward packing must already fit the absolute
    # allowance. Relative targets and ordinary volume-only requests keep the
    # original algorithm. Each child is a subset; no accuracy target changes.
    loose_witness = (positive_witness and relative_error is None and
                     width >= 2*cell.volume_m3)
    def outward(pair):
        if relative_error is None:
            return _volume_outward(pair, quantum)
        # A loose absolute request must not impose a rounding floor on local
        # accuracy, particularly for tiny positive components. Both grids are
        # outward; the new grid is never coarser. Also support requests tighter
        # than 53 significant bits, including exact (zero-error) requests.
        fine = min(W._quantum(pair[1], 1 << 50),
                   W._quantum(relative_error*pair[1], max_leaves))
        return _volume_outward(pair, min(quantum, fine))
    def measure_leaf(current_cell, level, arena, detail=None, mask=0):
        # Materialise the small replay descriptor before the operation; do not
        # request another geometry workspace after its admission has failed.
        replay_cell = current_cell.record()
        try:
            storage.workspace('cell', (*current_cell._geometry(), level, 2*max_leaves), 12)
            with _PartitionScratch(arena) as scratch:
                answer = _component_volume_certificate(layer, current_cell, component['constraints'],
                    record['constraints'], time, level, arena, detail=detail,
                    _clip_arena=scratch, mask=mask, _cone_query=arena._component_ray_cache, _loose_witness=loose_witness)
                bounds, at, mask, witness_volume = answer
                packed = outward(bounds)
                # The leaf frame/polygons have returned. Admit every exact
                # escaped value BEFORE its clipping scratch is released.
                # Packed bounds/priority and tuple space cover the queue;
                # level and 2*max_leaves bound its depth/serial bit widths.
                storage.workspace('answer', (*bounds, *packed, packed[0]-packed[1], mask,
                                             witness_volume, *(at or ())), 8)
                return answer
        except Exception as error:
            # No result is issued. Retain bounded original operands so resource
            # failures can be replayed without rebuilding the accepted parent.
            requests, arithmetic, tb = [], [], error.__traceback__
            while tb is not None:
                frame = tb.tb_frame
                if frame.f_code.co_name == '_admit_budgets':
                    requests.append(dict(requested_bytes=frame.f_locals.get('count'),
                                         category=frame.f_locals.get('category')))
                if frame.f_code.co_name == '_work' and 'bits' in frame.f_locals:
                    arithmetic.append(dict(input_bits=frame.f_locals['bits'],
                                           pairs=frame.f_locals.get('pairs')))
                tb = tb.tb_next
            # The deepest frame leads back to this handler. Holding it made a
            # cycle that kept the failed leaf's polyhedra alive after the
            # error itself had been dropped, until a cyclic collection.
            frame = None
            error.component_volume_failure = dict(support=record,
                query=dict(logical_cell_id=logical_cell_id, endpoint=endpoint,
                    max_width_m3=_qtext(width), max_leaves=max_leaves, positive_witness=positive_witness),
                failed_leaf=dict(cell=replay_cell, level=level),
                exception_type=type(error).__name__, requested_reservations=requests,
                arithmetic_requests=arithmetic, budget_at_leaf_unwind=budget.statistics(),
                budget_scope='outer operation arena is still live; failed inner scratch has unwound')
            if relative_error is not None:
                error.component_volume_failure['query']['relative_error'] = _qtext(Q(relative_error))
            raise
    # Public wrapper owns decoded input, queue, output admission and failure
    # payload under ONE arena. Exiting this helper does not release it early.
    with nullcontext(arena):
        storage = _ComponentVolumeStorage(arena)
        arena._component_ray_cache = _ComponentRayCache(arena)
        aggregate_peak = 0
        def retain_aggregate(low, high, witness):
            nonlocal aggregate_peak
            # Only growth of these live scalar slots is retained; old
            # totals are replaced. This remains physical byte accounting.
            values = (low, high, witness)
            size = 1024+128*len(values)+4*sum((V._bits(v)+7)//8 for v in values)
            if size > aggregate_peak:
                delta = size-aggregate_peak
                if arena.lease is None:
                    arena.stack.enter_context(budget.reserve(delta, category='component-volume-aggregate'))
                else:
                    arena.lease.add(delta, category='component-volume-aggregate')
                aggregate_peak = size
        detail = {}
        exact, witness_at, mask, root_witness = measure_leaf(cell, 0, arena, detail)
        leaves, poses = 1, [0]
        if positive_witness and not exact[0] and exact[1]:
            # Neither empty nor given a positive inner subset: undecided by
            # the radial linearisation, which does not depend on the pose and
            # which halving resolves, or because the padded literal planes
            # alone leave no inner polyhedron (a gap, a contact or a sliver
            # narrower than their pose enclosure). Only the second is
            # escalated, and only while it lasts. A finer pose of the SAME
            # whole voxel proves a separated gap empty and can expose a sliver
            # when the inner radial slab is non-empty. Where the voxel
            # straddles the shell that slab is empty at every pose and the
            # sliver's positive subset is found by the halved children, which
            # inherit the finer pose level. All enclosures bound the one true
            # volume, so they are intersected. Each evaluation spends a leaf
            # of the ceiling.
            for finer in (16, 32):
                if leaves >= max_leaves or not exact[1] or exact[0] or not detail['angular_inner_empty']:
                    break
                again, at, mask, again_witness = measure_leaf(cell, finer, arena, detail, mask)
                leaves += 1; poses.append(finer)
                if again_witness > root_witness:
                    witness_at = at
                    root_witness = again_witness
                exact = (max(exact[0], again[0]), min(exact[1], again[1]))
                if exact[0] > exact[1]:
                    raise V.VolumeError('component volume enclosures at two pose precisions contradict')
        witness = root_witness if positive_witness else Q(0)
        low, high = outward(exact)
        retain_aggregate(low, high, witness)
        # The queue carries depth for pose precision; side lengths select the axis.
        # A leaf at depth d is posed at level d+offset.
        queue, serial, offset = [], 0, poses[-1]
        storage.push(queue, (low-high, 0, cell, 0, low, high, mask))
        while queue and (high-low > width or positive_witness and not witness and high > 0 or
                relative_error is not None and high > 0 and (not low or high-low > relative_error*low)) and leaves < max_leaves:
            if leaves == 16 and positive_witness and relative_error is None and not witness and not low and high:
                try:
                    proved = (_wp20_corotating_zero(component['constraints'], record['constraints'], arena) is not None or
                              _wp20_axial_meridian_zero(component['constraints'], record['constraints'], time, arena) is not None)
                except Exception as error:
                    error.add_note('WP20 zero-certificate attempt: '+str(dict(logical_cell_id=logical_cell_id,
                        endpoint=endpoint, support_id=support.support_id, leaves=leaves)))
                    raise
                if proved:
                    # WP20: the true component has zero 3-D volume (exact proof);
                    # its exact enclosure is [0, 0] and the query ends met.
                    low = high = Q(0)
                    break
            if _GEOMETRY_PROGRESS is not None:
                _GEOMETRY_PROGRESS.step(leaves, len(queue), low, high, witness, width, positive_witness)
            _, _, parent, depth, lo, hi, mask = storage.pop(queue)
            try:
                k = depth % 3  # D1: item 11 off (r7 cyclic axis)
            except Exception as error:
                # Retain the original owner even when only this traceback is
                # kept after RoutingArena has detached its exception owner.
                _split_failure_owner = getattr(arena, '_failure_owner', None)
                child = aa = bb = values = None
                try:
                    from .integration_routing_views import _OwnedPayload
                    payload = _component_split_failure(record,
                        logical_cell_id, endpoint, width, max_leaves, positive_witness,
                        relative_error, parent, depth, offset, arena, storage, error)
                    error.component_split_failure = _OwnedPayload(payload, _split_failure_owner)
                except BaseException:
                    # Optional diagnostic construction must never replace the
                    # original resource/arithmetic exception or its traceback.
                    pass
                raise
            middle = (parent.lower_m[k]+parent.upper_m[k])/2
            values = []
            for upper in (False, True):
                aa, bb = list(parent.lower_m), list(parent.upper_m)
                (aa if upper else bb)[k] = middle
                child = V.CartesianCell(tuple(aa), tuple(bb), parent.origin_m, parent.basis, budget=budget)
                exact, candidate_at, child_mask, candidate_witness = measure_leaf(child, depth+1+offset, arena, mask=mask)
                if positive_witness and candidate_witness > witness:
                    witness_at = candidate_at
                # Keep one explicit certificate, including parents whose
                # descendants replace them. Never add parent/child witnesses.
                witness = max(witness, candidate_witness) if positive_witness else witness
                a, b = outward(exact)
                serial += 1
                if a != b:
                    storage.push(queue, (a-b, serial, child, depth+1, a, b, child_mask))
                values.append((a, b))
            low += sum(v[0] for v in values)-lo
            high += sum(v[1] for v in values)-hi
            retain_aggregate(low, high, witness)
            leaves += 1
        low = max(low, witness)
        retain_aggregate(low, high, witness)
        result = dict(schema='atlas.differential-component-volume.v1', support_id=support.support_id,
            logical_cell_id=logical_cell_id, endpoint=endpoint, time_s=record[endpoint+'_time_s'],
            lower_m3=_qtext(low), upper_m3=_qtext(high), max_width_m3=_qtext(width),
            max_leaves=max_leaves, leaves=leaves,
            met=high-low <= width and (not positive_witness or high == 0 or witness > 0),
            positive_witness_m3=_qtext(witness), work_units=arena.work_units)
        if relative_error is not None:
            error = (high-low)/low if low else (Q(0) if not high else None)
            result.update(relative_error=_qtext(Q(relative_error)),
                relative_error_bound=None if error is None else _qtext(error),
                met=result['met'] and error is not None and error <= relative_error)
        if positive_witness and witness_at is not None:
            result.update(positive_witness_point_m=_store_vec(witness_at),
                positive_witness_point_rule='exact vertex barycentre of a positive-volume certified inner convex polyhedron')
        if len(poses) > 1:
            # Present only when used, so every other record keeps its bytes.
            result['whole_voxel_pose_levels'] = poses
        if _GEOMETRY_PROGRESS is not None:
            _GEOMETRY_PROGRESS.end(result)
    return _issue(DifferentialMeasure, result, budget)


def _transferred_collar_binding(body, funding, collar, budget, transfer):
    if body.get('collar_plan_id') == collar.plan_id:
        return True
    if transfer is None:
        return False
    from geometry_transfer import collar_binding_matches
    return collar_binding_matches(body, funding, collar, budget, transfer)


def _transferred_partition_binding(partition, header, funding, collar, budget, transfer):
    if header.get('collar_plan_id') == collar.plan_id:
        return True
    if transfer is None:
        return False
    if getattr(partition, '_compact', None) is None:
        from geometry_transfer import collar_binding_matches
        return collar_binding_matches(header, funding, collar, budget, transfer)
    from partition_native_patch import compact_view
    from geometry_transfer import collar_binding_matches_compact
    return collar_binding_matches_compact(compact_view(partition), funding, collar, budget, transfer)


def _carried_partition_regions(parent_partition, step, old_time, retained_rows, compact_scope):
    from live_partition_patch import parent_rows
    regions = {}
    for support_owner in parent_rows(parent_partition, compact_scope):
        retained_rows.keep(support_owner)
        r = support_owner.value
        omega = _load_vec(step['plate_angular_velocity_rad_s'][r['plate_id']])
        for component in r['components']:
            identity = dict(parent_partition_id=parent_partition.partition_id,
                parent_source_chart_id=r['source_chart_id'], parent_partition_path=component['partition_path'],
                plate_id=r['plate_id'], radial_layer=r['radial_layer'])
            key = W._hash(identity)
            if key not in regions:
                constraints, literals = {}, []
                for name, sign in component['constraints']:
                    # Fixed exclusions are spatial compartments, never material
                    # charts. The aligned-grid issuer removes whole voxels.
                    value = r['constraints'][name]
                    if value['kind'] == 'fixed-plane':
                        raise V.VolumeError('a fixed exclusion cannot be advected into carried material')
                    constraints[name] = dict(kind='snapshot-rotated', constraint=value,
                        snapshot_offset_s=_qtext(old_time), angular_velocity_rad_s=_store_vec(omega))
                    literals.append((name, sign))
                regions[key] = dict(source_chart_id=key, kind='inherited', source_key=r['source_key'],
                    plate_id=r['plate_id'], radial_band=r['radial_band'], chart=key,
                    radial_layer=r['radial_layer'], source_constraint_chart=dict(constraints=constraints, literals=literals),
                    parent_owner_ray_ids=component['owner_ray_ids'], parent_cells={}, parent_chart=identity)
                regions[key] = retained_rows.detach(regions[key])
            cells = regions[key]['parent_cells']
            at = ','.join(map(str, r['voxel_index']))
            if at in cells:
                raise V.VolumeError('one accepted physical parent appears in duplicate carried chart slots')
            cells[at] = component['logical_cell_id']
            retained_rows.cell()
    return regions
