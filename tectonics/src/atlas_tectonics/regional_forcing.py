"""W01 Stage 6: prescribed motion -> checked, frozen regional face forcing.

This is a kinematic adapter, not a force/stress or geological-evolution model.
Projections retain every owner and residual component. Only analytically
invariant section reductions may produce solver-ready N+1 face velocities.
The declared interval holds the start-epoch spatial field in section coordinates;
it does not integrate a rotating frame, move topology, or initialise material.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from dataclasses import dataclass, fields, asdict, field
import hashlib
import json
import math
import threading

import numpy as np
import shapely
from shapely.geometry import LineString

from ._validation import TectonicsError, scalar, read_array, input_shape
from .coordinates import SphericalFrame, _label
from .kinematics import _unit
from .geological_records import GeologySource
from .geometry import GeometryLimits, _limits, _json, _check_cancel
from .boundaries import BoundaryNetwork, save_boundary_network, load_boundary_network
from .spherical_atlas import SphericalAtlas, save_spherical_atlas, load_spherical_atlas
from .geometry_index import GeometryFeature, GeometryIndex
from .regional import RegionalGrid1D, TransportBoundary, _boundaries
from .resources import select_budget
from .reuse import ExecutionContext
from .timebase import advance_time

_SCHEMA = 'atlas.regional-motion-forcing.v1'
_METHOD = 'prescribed-invariant-section-frozen-interval-binary64-v2'
# Arithmetic uncertainty only, not a user-selectable physical flow tolerance.
_ROUNDOFF = 64 * np.finfo(np.float64).eps


class MotionReductionError(TectonicsError):
    """Unsupported, ambiguous, incomplete or unrepresented prescribed motion."""


def _vector(value, size, name):
    if type(value) is not tuple or len(value) != size:
        raise MotionReductionError(name + ': explicit immutable component tuple required')
    return tuple(scalar(x, name) for x in value)


def _source(value):
    if type(value) is not GeologySource:
        raise MotionReductionError('explicit GeologySource required; no inferred provenance')


def _units(length, velocity, angular):
    if (length, velocity, angular) != ('m', 'm/s', 'rad/s'):
        raise MotionReductionError('explicit SI units m, m/s and rad/s required; convert inputs first')


def _record(value):
    """Only authored constructor fields; derived transforms are rebuilt on restore."""
    return {f.name: (asdict(getattr(value, f.name)) if f.name in ('source', 'sphere')
                     else getattr(value, f.name)) for f in fields(value) if f.init}


def _digest(record):
    return hashlib.sha256(_json(record)).hexdigest()


def _array_digest(arrays, descriptor):
    h = hashlib.sha256(_json(descriptor))
    for name, a in sorted(arrays.items()):
        h.update(_json((name, a.dtype.str, a.shape))); h.update(a.tobytes())
    return h.hexdigest()


def _finite(a, name):
    if not np.isfinite(a).all():
        raise MotionReductionError(name + ' exceeds binary64 range')
    return a


def _dot(a, b):
    return math.fsum(float(x) * float(y) for x, y in zip(a, b))


def _orthogonal(a, b):
    # Rescale the potentially extremely small velocity before testing its
    # direction. There is no absolute m/s allowance that could erase tiny flow.
    s = float(np.max(np.abs(a)))
    if s == 0:
        return True
    aa = np.asarray(a) / s
    products = aa * b
    return abs(math.fsum(map(float, products))) <= _ROUNDOFF * math.fsum(map(float, np.abs(products)))


def _parallel(a, b):
    s = float(np.max(np.abs(a)))
    if s == 0:
        return True
    aa = np.asarray(a) / s
    lhs = aa[[1, 2, 0]] * b[[2, 0, 1]]
    rhs = aa[[2, 0, 1]] * b[[1, 2, 0]]
    return bool(np.all(np.abs(lhs-rhs) <= _ROUNDOFF * (np.abs(lhs)+np.abs(rhs))))


def _arc_seam_intervals(a, b, basis, angle):
    """Conservative angular hits of a finite seam on a minor section arc.

    This is geometry, not mesh sampling. Ambiguous nearly coincident planes
    refuse the whole section rather than treating an ill-conditioned miss as
    proof of absence. Exactly coplanar arcs use wrapped interval overlap.
    """
    radial, tangent, pole = basis
    # Match the retained atlas frame construction for short/near-antipodal arcs.
    normal = _unit(np.cross(a+b, b-a))
    crossing = np.cross(pole, normal)
    size = float(np.linalg.norm(crossing))
    if size == 0:
        first = math.atan2(_dot(a, tangent), _dot(a, radial))
        last = math.atan2(_dot(b, tangent), _dot(b, radial))
        delta = math.remainder(last-first, 2*math.pi)
        lo, hi = sorted((first, first+delta))
        return [(max(0., lo+k-_ROUNDOFF), min(angle, hi+k+_ROUNDOFF))
                for k in (-2*math.pi, 0., 2*math.pi)
                if hi+k+_ROUNDOFF >= 0 and lo+k-_ROUNDOFF <= angle]
    if size <= _ROUNDOFF:
        return [(0., angle)]
    edge_tangent = np.cross(normal, a)
    edge_angle = 2*math.atan2(float(np.linalg.norm(b-a)), float(np.linalg.norm(b+a)))
    # Normal intersection conditioning determines the outward error bound.
    pad = min(math.pi, 4*_ROUNDOFF/size)
    hits = []
    for point in (crossing/size, -crossing/size):
        at_edge = math.atan2(_dot(point, edge_tangent), _dot(point, a))
        at_section = math.atan2(_dot(point, tangent), _dot(point, radial))
        if -pad <= at_edge <= edge_angle+pad and -pad <= at_section <= angle+pad:
            hits.append((max(0., at_section-pad), min(angle, at_section+pad)))
    return hits


@dataclass(frozen=True, slots=True)
class PrescribedPlateMotion:
    """A grid-independent instantaneous affine rigid velocity in named axes.

    v(r) = translation + omega cross (r-pivot). On a plane only the up-axis
    angular component is supported; vertical translation is retained in diagnostics
    and is NOT automatically converted to thickness change. Spherical motion must
    be Euler rotation about the stated sphere centre, without translation.
    """
    plate_id: str
    frame_id: str
    epoch_id: str
    time_s: float
    mode: str
    translation_m_s: tuple[float, float, float]
    angular_velocity_rad_s: tuple[float, float, float]
    pivot_m: tuple[float, float, float]
    source: GeologySource
    length_unit: str
    velocity_unit: str
    angular_velocity_unit: str

    def __post_init__(self):
        for key in ('plate_id', 'frame_id', 'epoch_id'):
            _label(getattr(self, key), key)
        object.__setattr__(self, 'time_s', scalar(self.time_s, 'motion time_s'))
        for key in ('translation_m_s', 'angular_velocity_rad_s', 'pivot_m'):
            object.__setattr__(self, key, _vector(getattr(self, key), 3, key))
        _source(self.source); _units(self.length_unit, self.velocity_unit, self.angular_velocity_unit)
        if self.mode == 'planar-rigid':
            if self.angular_velocity_rad_s[:2] != (0., 0.):
                raise MotionReductionError('planar rotation supports only the declared up axis')
        elif self.mode == 'spherical-euler':
            if self.translation_m_s != (0., 0., 0.) or self.pivot_m != (0., 0., 0.):
                raise MotionReductionError('spherical motion requires planet-centred Euler rotation')
        else:
            raise MotionReductionError('unsupported prescribed motion mode')

    def descriptor(self):
        return _record(self)

    def __reduce__(self):
        return (type(self), tuple(getattr(self, f.name) for f in fields(self)))


@dataclass(frozen=True, slots=True)
class PlanarRegionalSection:
    """Straight, oriented column transect in planar x/y/up axes.

    Reference rates are in those same parent axes, about origin_m at time_s.
    Components relative to this moving frame subtract BOTH translation and
    angular velocity. The section definition is independent of grid resolution.
    """
    section_id: str
    frame_id: str
    epoch_id: str
    time_s: float
    origin_m: tuple[float, float, float]
    direction_xy: tuple[float, float]
    length_m: float
    frame_velocity_m_s: tuple[float, float, float]
    frame_angular_velocity_rad_s: tuple[float, float, float]
    source: GeologySource
    length_unit: str
    velocity_unit: str
    angular_velocity_unit: str

    def __post_init__(self):
        for key in ('section_id', 'frame_id', 'epoch_id'):
            _label(getattr(self, key), key)
        for key, n in (('origin_m', 3), ('direction_xy', 2), ('frame_velocity_m_s', 3),
                       ('frame_angular_velocity_rad_s', 3)):
            object.__setattr__(self, key, _vector(getattr(self, key), n, key))
        _unit(np.asarray(self.direction_xy))
        if self.frame_angular_velocity_rad_s[:2] != (0., 0.):
            raise MotionReductionError('planar frame tilting is unsupported')
        object.__setattr__(self, 'length_m', scalar(self.length_m, 'section length', positive=True))
        object.__setattr__(self, 'time_s', scalar(self.time_s, 'section time'))
        _source(self.source); _units(self.length_unit, self.velocity_unit, self.angular_velocity_unit)

    def descriptor(self):
        return dict(kind='planar', **_record(self))

    def __reduce__(self):
        return (type(self), tuple(getattr(self, f.name) for f in fields(self)))


@dataclass(frozen=True, slots=True)
class SphericalRegionalSection:
    """Oriented minor great-circle arc, distance measured as R*angle.

    start_direction and pole_direction define the arc and its positive tangent
    pole cross radial. Across-section is pole (left), vertical is radial-up.
    A moving reference rotates about the planet centre. No translating centre,
    small-circle metric, planar chord approximation or latitude snapping is used.
    """
    section_id: str
    sphere: SphericalFrame
    epoch_id: str
    time_s: float
    start_direction: tuple[float, float, float]
    pole_direction: tuple[float, float, float]
    length_m: float
    frame_angular_velocity_rad_s: tuple[float, float, float]
    source: GeologySource
    length_unit: str
    velocity_unit: str
    angular_velocity_unit: str

    def __post_init__(self):
        _label(self.section_id, 'section_id'); _label(self.epoch_id, 'epoch_id')
        if type(self.sphere) is not SphericalFrame:
            raise MotionReductionError('explicit SphericalFrame required')
        for key in ('start_direction', 'pole_direction', 'frame_angular_velocity_rad_s'):
            object.__setattr__(self, key, _vector(getattr(self, key), 3, key))
        start = _unit(np.asarray(self.start_direction)); pole = _unit(np.asarray(self.pole_direction))
        if not _orthogonal(start, pole):
            raise MotionReductionError('great-circle start must be perpendicular to its pole')
        object.__setattr__(self, 'length_m', scalar(self.length_m, 'arc length', positive=True))
        angle = self.length_m / self.sphere.radius_m
        if not 0 < angle < math.pi:
            raise MotionReductionError('only resolvable, strictly minor section arcs are supported')
        object.__setattr__(self, 'time_s', scalar(self.time_s, 'section time'))
        _source(self.source); _units(self.length_unit, self.velocity_unit, self.angular_velocity_unit)

    @property
    def frame_id(self):
        return self.sphere.frame_id

    def descriptor(self):
        return dict(kind='sphere', **_record(self))

    def __reduce__(self):
        return (type(self), tuple(getattr(self, f.name) for f in fields(self)))


@dataclass(frozen=True, slots=True)
class RegionalReduction:
    """A fixed supported physical reduction AND explicit time approximation.

    Frozen-at-start is the existing regional solver's constant-forcing interval,
    not exact finite rotation/plate-boundary evolution. It never excuses omitted
    transverse/vertical transport: analytical invariance is separately mandatory.
    """
    model: str
    temporal_rule: str
    source: GeologySource
    reference_width_m: float

    def __post_init__(self):
        if self.model not in ('planar-columns', 'great-circle-columns'):
            raise MotionReductionError('unsupported regional reduction')
        if self.temporal_rule != 'frozen-at-start':
            raise MotionReductionError('regional forcing must explicitly declare frozen-at-start; no interval integration')
        _source(self.source)
        object.__setattr__(self, 'reference_width_m', scalar(self.reference_width_m, 'reference transverse width', positive=True))

    def descriptor(self):
        return _record(self)


@dataclass(frozen=True, slots=True)
class RegionalMotionDefinition:
    """Prescribed velocities plus a static, validated ownership snapshot.

    Assigning the snapshot to the named epoch is explicit authored provenance,
    not a prediction that the topology remains a material partition as it moves.
    The caller must construct another definition at a forcing/topology change.
    """
    topology: BoundaryNetwork | SphericalAtlas
    motions: tuple[PrescribedPlateMotion, ...]
    epoch_id: str
    start_time_s: float
    duration_s: float
    time_unit: str
    source: GeologySource

    def __post_init__(self):
        if type(self.topology) not in (BoundaryNetwork, SphericalAtlas):
            raise MotionReductionError('validated BoundaryNetwork or SphericalAtlas required')
        if type(self.motions) is not tuple or not self.motions or any(type(m) is not PrescribedPlateMotion for m in self.motions):
            raise MotionReductionError('explicit immutable plate-motion tuple required')
        _label(self.epoch_id, 'epoch_id'); _source(self.source)
        if self.time_unit != 's':
            raise MotionReductionError('time interval must explicitly use forward SI seconds')
        object.__setattr__(self, 'start_time_s', scalar(self.start_time_s, 'interval start'))
        object.__setattr__(self, 'duration_s', scalar(self.duration_s, 'interval duration', positive=True))
        advance_time(self.start_time_s, self.duration_s)
        spherical = type(self.topology) is SphericalAtlas or self.topology.spherical
        frame_id = (self.topology.sphere.frame_id if type(self.topology) is SphericalAtlas else
                    self.topology.domain.chart.sphere.frame_id if spherical else self.topology.domain.frame_id)
        names = [m.plate_id for m in self.motions]
        if len(set(names)) != len(names) or set(names) != set(self.topology.plate_ids):
            raise MotionReductionError('one explicit motion per topology plate is required; no missing or duplicate owners')
        for m in self.motions:
            if (m.frame_id != frame_id or m.epoch_id != self.epoch_id or m.time_s != self.start_time_s
                    or m.mode != ('spherical-euler' if spherical else 'planar-rigid')):
                raise MotionReductionError('motion frame/epoch/time/space does not match topology prescription')
        object.__setattr__(self, 'motions', tuple(sorted(self.motions, key=lambda m: m.plate_id)))

    @property
    def topology_id(self):
        return self.topology.atlas_id if type(self.topology) is SphericalAtlas else self.topology.network_id

    def descriptor(self):
        return {'topology_kind': 'atlas' if type(self.topology) is SphericalAtlas else 'network',
                'topology_id': self.topology_id, 'motions': [m.descriptor() for m in self.motions],
                'epoch_id': self.epoch_id, 'start_time_s': self.start_time_s,
                'duration_s': self.duration_s, 'time_unit': self.time_unit, 'source': asdict(self.source)}

    @property
    def identity(self):
        return _digest(self.descriptor())

    def __reduce__(self):
        return (type(self), tuple(getattr(self, f.name) for f in fields(self)))


@dataclass(frozen=True, slots=True, init=False)
class SectionMotionSamples:
    """All owner rows and unmodified measured components; not solver-ready alone."""
    def __init__(self):
        raise MotionReductionError('create projected samples with PreparedRegionalForcing.project')

    _descriptor: bytes = field(repr=False)
    _offsets: bytes = field(repr=False)
    _positions: bytes = field(repr=False)
    _pairs: bytes = field(repr=False)
    _values: bytes = field(repr=False)
    _selected: bytes = field(repr=False)

    @property
    def offsets_m(self): return np.frombuffer(self._offsets, dtype='f8')
    @property
    def positions_m(self): return np.frombuffer(self._positions, dtype='f8').reshape(-1, 3)
    @property
    def owner_pairs(self): return np.frombuffer(self._pairs, dtype='i8').reshape(-1, 2)
    @property
    def values_m_s(self): return np.frombuffer(self._values, dtype='f8').reshape(-1, 9)
    @property
    def absolute_velocity_m_s(self): return self.values_m_s[:, :3]
    @property
    def reference_velocity_m_s(self): return self.values_m_s[:, 3:6]
    @property
    def components_m_s(self): return self.values_m_s[:, 6:9]
    @property
    def selected_rows(self): return np.frombuffer(self._selected, dtype='i8')
    @property
    def region_ids(self): return tuple(self.descriptor()['region_ids'])

    def descriptor(self): return json.loads(self._descriptor)

    def arrays(self):
        return {'offsets_m': self.offsets_m, 'positions_m': self.positions_m,
                'owner_pairs': self.owner_pairs, 'values_m_s': self.values_m_s,
                'selected_rows': self.selected_rows}

    @property
    def identity(self): return _array_digest(self.arrays(), self.descriptor())


def _samples(desc, offsets, positions, pairs, values, selected):
    out = object.__new__(SectionMotionSamples)
    for key, value in (('_descriptor', _json(desc)), ('_offsets', offsets.tobytes()),
                       ('_positions', positions.tobytes()), ('_pairs', pairs.tobytes()),
                       ('_values', values.tobytes()), ('_selected', selected.tobytes())):
        object.__setattr__(out, key, value)
    return out


@dataclass(frozen=True, slots=True, init=False)
class RegionalFaceForcing:
    """N+1 prescribed relative velocities; boundary material stays caller-supplied."""
    def __init__(self):
        raise MotionReductionError('create solver-ready forcing with PreparedRegionalForcing.faces')

    definition: RegionalMotionDefinition
    section: PlanarRegionalSection | SphericalRegionalSection
    reduction: RegionalReduction
    grid: RegionalGrid1D
    samples: SectionMotionSamples
    _velocity: bytes = field(repr=False)
    _descriptor: bytes = field(repr=False)
    forcing_id: str

    @property
    def face_velocity_m_s(self): return np.frombuffer(self._velocity, dtype='f8')
    @property
    def start_time_s(self): return self.definition.start_time_s
    @property
    def duration_s(self): return self.definition.duration_s

    def validate_boundaries(self, *, left: TransportBoundary, right: TransportBoundary):
        if type(left) is not TransportBoundary or type(right) is not TransportBoundary:
            raise MotionReductionError('explicit regional transport boundaries required')
        _boundaries(self.face_velocity_m_s, left, right)
        # No inferred reservoir values, nor automatic zeroing of external faces.

    def descriptor(self): return json.loads(self._descriptor)

    def arrays(self):
        return dict(self.samples.arrays(), face_velocity_m_s=self.face_velocity_m_s)


class PreparedRegionalForcing:
    """Caller-owned transforms and existing indexes; no per-grid motion redraw/cache.

    Queries hold their own scratch. Close refuses active readers; source and
    callable verification surrounds every query. Published arrays outlive their
    temporary reservations and are thereafter caller-owned, as in other adapters.
    """
    def __setattr__(self, name, value):
        if name in ('definition', 'section', 'reduction', 'limits', 'budget', 'identity',
                    '_spherical', '_basis', '_coefficients', '_checks', '_motion_data',
                    '_region_ids', '_region_plate', '_index', '_context', '_execution_id',
                    '_discontinuities', '_lock', '_stack') and hasattr(self, name):
            raise MotionReductionError('prepared scientific definitions are immutable')
        object.__setattr__(self, name, value)

    def __init__(self, definition, section, reduction, *, limits=None, budget=None, cancel=None):
        _check_cancel(cancel)
        if type(definition) is not RegionalMotionDefinition or type(section) not in (PlanarRegionalSection, SphericalRegionalSection) or type(reduction) is not RegionalReduction:
            raise MotionReductionError('explicit motion definition, section and reduction required')
        self.definition = definition; self.section = section; self.reduction = reduction
        self.limits = _limits(limits); self.budget = select_budget(budget)
        self._spherical = type(section) is SphericalRegionalSection
        topology = definition.topology
        spherical = type(topology) is SphericalAtlas or topology.spherical
        if spherical != self._spherical or reduction.model != ('great-circle-columns' if spherical else 'planar-columns'):
            raise MotionReductionError('section and supported reduction space disagree')
        sphere = topology.sphere if type(topology) is SphericalAtlas else topology.domain.chart.sphere if spherical else None
        frame = sphere.frame_id if spherical else topology.domain.frame_id
        if (section.frame_id != frame or section.epoch_id != definition.epoch_id or section.time_s != definition.start_time_s
                or (spherical and section.sphere != sphere)):
            raise MotionReductionError('section frame, sphere, epoch or time does not match the prescription')
        self._lock = threading.Lock(); self._active = 0; self._closed = False
        self._stack = ExitStack()
        try:
            retained = topology.retained_bytes_estimate + 512*topology.edge_count + 4096 * len(definition.motions) + 32768
            self._stack.enter_context(self.budget.reserve(retained, category='regional-forcing-plan'))
            self._context = self._stack.enter_context(ExecutionContext('reference'))
            self._execution_id = self._context.identity
            self._prepare_coefficients(cancel)
            self._check_coverage()
            self._prepare_discontinuities(cancel)
            if type(topology) is SphericalAtlas:
                self._index = self._stack.enter_context(topology.index(limits=self.limits, budget=self.budget))
                names = topology.region_ids
                mapping = {p.region_id: p.plate_id for p in topology.patches}
            else:
                self._index = self._stack.enter_context(GeometryIndex(
                    tuple(GeometryFeature(r.region_id, r.geometry) for r in topology.regions), limits=self.limits, budget=self.budget))
                names = self._index.feature_ids
                mapping = {r.region_id: r.plate_id for r in topology.regions}
            self._region_ids = tuple(names)
            pindex = {m.plate_id: i for i, m in enumerate(definition.motions)}
            self._region_plate = np.asarray([pindex[mapping[n]] for n in names], dtype='i8').tobytes()
            self.identity = _digest({'method': _METHOD, 'execution_id': self._execution_id,
                                     'definition': definition.descriptor(), 'section': section.descriptor(),
                                     'reduction': reduction.descriptor()})
            _check_cancel(cancel); self._context.verify()
        except BaseException:
            self._stack.close(); self._closed = True
            raise

    def _prepare_coefficients(self, cancel=None):
        section = self.section
        if self._spherical:
            radial = _unit(np.asarray(section.start_direction))
            pole = _unit(np.asarray(section.pole_direction))
            tangent = _unit(np.cross(pole, radial))
            self._basis = np.stack((radial, tangent, pole)).tobytes()
        else:
            direction = _unit(np.asarray(section.direction_xy))
            tangent = np.r_[direction, 0.]; pole = np.array((-direction[1], direction[0], 0.))
            self._basis = np.stack((tangent, pole, (0., 0., 1.))).tobytes()
        coefficients = []; checks = []
        for index, motion in enumerate(self.definition.motions):
            if index % 256 == 0: _check_cancel(cancel)
            omega = np.asarray(motion.angular_velocity_rad_s)
            frame_omega = np.asarray(section.frame_angular_velocity_rad_s)
            delta = _finite(omega-frame_omega, 'relative angular rate')
            if self._spherical:
                base = np.zeros(3)
                admissible = _parallel(delta, pole)
                reason = 'axial Euler flow has no meridional or radial transport' if admissible else 'relative Euler pole is not the section pole: unrepresented cross-section flow'
            else:
                shift = _finite(np.asarray(section.origin_m)-motion.pivot_m, 'pivot shift')
                cross = _finite(np.cross(omega, shift), 'pivot velocity')
                base = np.array([math.fsum((motion.translation_m_s[j], float(cross[j]), -section.frame_velocity_m_s[j])) for j in range(3)])
                _finite(base, 'relative translation')
                admissible = bool(np.all(delta == 0) and _orthogonal(base, pole) and base[2] == 0)
                reason = ('relative translation parallel to the entire section; no cross/vertical transport' if admissible else
                          'relative angular, transverse or vertical motion is unrepresented by planar columns')
            coefficients.append(np.r_[base, delta])
            checks.append({'plate_id': motion.plate_id, 'admissible': admissible, 'reason': reason,
                           'relative_base_m_s': base.tolist(), 'relative_angular_velocity_rad_s': delta.tolist()})
        self._motion_data = np.asarray([(*m.translation_m_s, *m.angular_velocity_rad_s, *m.pivot_m) for m in self.definition.motions], dtype='f8').tobytes()
        self._coefficients = np.asarray(coefficients, dtype='f8').tobytes()
        self._checks = _json(checks)

    def reduction_checks(self):
        return json.loads(self._checks)

    def _geometry(self, s):
        basis = np.frombuffer(self._basis, dtype='f8').reshape(3, 3)
        if self._spherical:
            angle = s / self.section.sphere.radius_m
            if np.any((s != 0) & (angle == 0)):
                raise MotionReductionError('nonzero arc distance underflows its angular representation')
            radial = np.cos(angle)[:, None] * basis[0] + np.sin(angle)[:, None] * basis[1]
            tangent = -np.sin(angle)[:, None] * basis[0] + np.cos(angle)[:, None] * basis[1]
            positions = radial * self.section.sphere.radius_m
            frames = np.stack((tangent, np.broadcast_to(basis[2], tangent.shape), radial), axis=1)
        else:
            positions = np.asarray(self.section.origin_m) + s[:, None] * basis[0]
            frames = np.broadcast_to(basis, (len(s), 3, 3))
        _finite(positions, 'section coordinates')
        start = (np.frombuffer(self._basis, dtype='f8').reshape(3, 3)[0] * self.section.sphere.radius_m if self._spherical else np.asarray(self.section.origin_m))
        if np.any((s != 0) & np.all(positions == start, axis=1)):
            raise MotionReductionError('nonzero section offset is lost at this coordinate origin')
        return positions, frames

    def _line(self, a, b):
        p, _ = self._geometry(np.array((a, b)))
        topology = self.definition.topology
        if self._spherical:
            xy = topology.domain.chart._project(p / self.section.sphere.radius_m)
        else:
            xy = p[:, :2]
        if np.array_equal(xy[0], xy[1]):
            raise MotionReductionError('section length is unresolvable at this coordinate origin')
        return LineString(xy)

    def _check_coverage(self):
        topology = self.definition.topology
        if type(topology) is BoundaryNetwork:
            line = self._line(0., self.section.length_m)
            domain = topology.domain._projected._geom if self._spherical else topology.domain._geom
            if not shapely.covers(domain, line):
                raise MotionReductionError('the entire section must be covered; holes/outside intervals cannot be skipped by face sampling')

    def _prepare_discontinuities(self, cancel):
        """Prepare full-section interface hits once, independently of any grid."""
        topology = self.definition.topology
        if topology.edge_count > self.limits.max_overlay_pairs:
            raise MotionReductionError('section interface work exceeds geometry limits')
        basis = np.frombuffer(self._basis, dtype='f8').reshape(3, 3)
        coeff = np.frombuffer(self._coefficients, dtype='f8').reshape(-1, 6)
        # Admissible velocities have a constant analytic along-section rate.
        # Non-admissible definitions remain diagnostic-only and faces refuses.
        if not all(c['admissible'] for c in self.reduction_checks()):
            self._discontinuities = b''
            return
        rates = {m.plate_id: _dot(c[3:], basis[2]) if self._spherical else _dot(c[:3], basis[0])
                 for m, c in zip(self.definition.motions, coeff)}
        hits = []
        is_atlas = type(topology) is SphericalAtlas
        line = None if is_atlas else self._line(0., self.section.length_m)
        sides = topology.side_patches if is_atlas else topology.side_regions
        owners = topology.patches if is_atlas else topology.regions
        for index, (left, right) in enumerate(sides):
            if index % 256 == 0: _check_cancel(cancel)
            if left < 0 or right < 0 or rates[owners[left].plate_id] == rates[owners[right].plate_id]:
                continue
            if is_atlas:
                a, b = topology.vertex_directions[topology.edge_vertices[index]]
                radius = self.section.sphere.radius_m
                hits.extend((lo*radius, hi*radius) for lo, hi in
                            _arc_seam_intervals(a, b, basis, self.section.length_m/radius))
            else:
                edge = LineString(topology.vertex_xy[topology.edge_vertices[index]])
                xy = shapely.get_coordinates(shapely.intersection(line, edge))
                if not len(xy): continue
                if self._spherical:
                    xyz = topology.domain.chart._unproject(xy)
                    offsets = np.arctan2(xyz @ basis[1], xyz @ basis[0])*self.section.sphere.radius_m
                else:
                    offsets = (xy-np.asarray(self.section.origin_m[:2])) @ basis[0, :2]
                hits.append((float(np.min(offsets)), float(np.max(offsets))))
        self._discontinuities = np.asarray(hits, dtype='f8').reshape(-1, 2).tobytes()

    @contextmanager
    def _query(self, cancel):
        _check_cancel(cancel)
        with self._lock:
            if self._closed:
                raise MotionReductionError('prepared motion adapter is closed')
            self._active += 1
        try:
            self._context.verify()
            yield
            _check_cancel(cancel); self._context.verify()
        except (FloatingPointError, OverflowError) as exc:
            raise MotionReductionError('kinematic evaluation is outside binary64 numerical range') from exc
        finally:
            with self._lock: self._active -= 1

    def project(self, offsets_m, *, frame_id, epoch_id, time_s, selections=None,
                backend='vectorised', cancel=None):
        """Project arbitrary ordered/repeated section coordinates, retaining all owners.

        A selection is a named region on a shared face, never a nearest/first plate.
        No selection gives -1 for multiple distinct plate owners. Same-plate patch
        seams have one unambiguous velocity but retain all their membership rows.
        """
        if backend not in ('vectorised', 'reference'):
            raise MotionReductionError('unsupported evaluation backend')
        if frame_id != self.section.frame_id or epoch_id != self.definition.epoch_id or scalar(time_s, 'query time') != self.definition.start_time_s:
            raise MotionReductionError('query frame/epoch/time mismatch')
        shape = input_shape(offsets_m, 'section offsets')
        if len(shape) != 1 or not 1 <= shape[0] <= self.limits.max_hits:
            raise MotionReductionError('bounded nonempty one-dimensional section offsets required')
        n = shape[0]
        if selections is not None and (type(selections) is not tuple or len(selections) != n or any(x is not None and (type(x) is not str or not x.strip()) for x in selections)):
            raise MotionReductionError('selections must be an immutable region-or-None tuple matching queries')
        maximum = min(n*len(self._region_ids), self.limits.max_hits)
        with self._query(cancel), self.budget.reserve(1024*maximum + 512*n + 16384, category='regional-forcing-query'):
            s = read_array(offsets_m, 'section offsets', ndim=1)
            if np.any(s < 0) or np.any(s > self.section.length_m):
                raise MotionReductionError('section extrapolation is refused')
            positions, frames = self._geometry(s)
            if type(self.definition.topology) is SphericalAtlas:
                hits = self._index.query(positions, by_plate=False, budget=self.budget, cancel=cancel)
                names = hits.owner_ids
            else:
                hits = self._index.query(positions if self._spherical else positions[:, :2], budget=self.budget, cancel=cancel)
                names = hits.feature_ids
            if tuple(names) != self._region_ids:
                raise MotionReductionError('ownership index does not match prepared mapping')
            pairs = hits.pairs
            counts = np.bincount(pairs[:, 0], minlength=n)
            if np.any(counts == 0):
                raise MotionReductionError('missing face ownership; no nearest or exterior plate is invented')
            region_plate = np.frombuffer(self._region_plate, dtype='i8')
            owners = region_plate[pairs[:, 1]]
            values = self._evaluate(positions, frames, pairs[:, 0], owners, backend, cancel)
            starts = np.r_[0, np.cumsum(counts)[:-1]].astype('i8')
            selected = starts.copy()
            # Existing indexes return stable query-major/owner-major rows.
            low = np.minimum.reduceat(owners, starts); high = np.maximum.reduceat(owners, starts)
            selected[low != high] = -1
            if selections is not None:
                lookup = {name: i for i, name in enumerate(names)}
                for i, name in enumerate(selections):
                    if name is None: continue
                    part = np.arange(starts[i], starts[i]+counts[i])
                    match = part[pairs[part, 1] == lookup.get(name, -1)]
                    if len(match) != 1:
                        raise MotionReductionError('selected region is not a verified owner at this query')
                    selected[i] = match[0]
            descriptor = {'schema': _SCHEMA, 'method': _METHOD, 'plan_id': self.identity,
                          'execution_id': self._execution_id, 'definition': self.definition.descriptor(),
                          'section': self.section.descriptor(), 'reduction': self.reduction.descriptor(),
                          'region_ids': self._region_ids,
                          'region_plate_ids': [self.definition.motions[int(i)].plate_id for i in region_plate],
                          'reduction_checks': self.reduction_checks(), 'backend': backend,
                          'selections': selections, 'component_order': ['along', 'cross-left', 'vertical-up'],
                          'arithmetic_direction_bound': _ROUNDOFF,
                          'ownership_rule': 'existing inclusive predicates; all reported owners retained; no snapping',
                          'solver_ready': False}
            return _samples(descriptor, s, positions, pairs, values, selected)

    def _evaluate(self, positions, frames, queries, owners, backend, cancel):
        """Shared query/index work; independent scalar or vector velocity evaluation."""
        coefficients = np.frombuffer(self._coefficients, dtype='f8').reshape(-1, 6)
        n = len(owners); result = np.empty((n, 9), dtype='f8')
        data = np.frombuffer(self._motion_data, dtype='f8').reshape(-1, 9)
        translations, omega, pivots = data[:, :3], data[:, 3:6], data[:, 6:9]
        fw = np.asarray(self.section.frame_angular_velocity_rad_s)
        origin = np.zeros(3) if self._spherical else np.asarray(self.section.origin_m)
        fv = np.zeros(3) if self._spherical else np.asarray(self.section.frame_velocity_m_s)
        with np.errstate(over='raise', invalid='raise'):
            if backend == 'reference':
                # Deliberately clear scalar formula, no per-row source captures or
                # repeated ownership searches inflating the comparison baseline.
                for i, (q, o) in enumerate(zip(queries, owners)):
                    if i % 256 == 0: _check_cancel(cancel)
                    p = positions[q]; d = p-origin; dp = p-pivots[o]
                    w = omega[o]; c = coefficients[o]; dw = c[3:]
                    absolute = [translations[o, 0]+w[1]*dp[2]-w[2]*dp[1],
                                translations[o, 1]+w[2]*dp[0]-w[0]*dp[2],
                                translations[o, 2]+w[0]*dp[1]-w[1]*dp[0]]
                    reference = [fv[0]+fw[1]*d[2]-fw[2]*d[1], fv[1]+fw[2]*d[0]-fw[0]*d[2], fv[2]+fw[0]*d[1]-fw[1]*d[0]]
                    relative = [c[0]+dw[1]*d[2]-dw[2]*d[1], c[1]+dw[2]*d[0]-dw[0]*d[2], c[2]+dw[0]*d[1]-dw[1]*d[0]]
                    result[i, :3] = absolute; result[i, 3:6] = reference
                    result[i, 6:] = [_dot(relative, basis) for basis in frames[q]]
            else:
                for start in range(0, n, self.limits.batch_points):
                    _check_cancel(cancel); stop = min(n, start+self.limits.batch_points)
                    ix = owners[start:stop]; iq = queries[start:stop]
                    p = positions[iq]; d = p-origin; c = coefficients[ix]
                    result[start:stop, :3] = translations[ix] + np.cross(omega[ix], p-pivots[ix])
                    result[start:stop, 3:6] = fv + np.cross(fw, d)
                    relative = c[:, :3] + np.cross(c[:, 3:], d)
                    result[start:stop, 6:] = np.sum(frames[iq] * relative[:, None, :], axis=2)
        return _finite(result, 'prescribed velocity')

    def faces(self, grid, *, frame_id, epoch_id, start_time_s, duration_s,
              selections=None, backend='vectorised', cancel=None):
        """Checked adapter to fixed-grid regional transport; no boundary zeroing.

        Interior two-sided discontinuities cannot be a single solver flux without
        a separate interface law. Endpoint one-sided selection is supported only
        when that region covers the adjacent full cell. Otherwise refine/crop or
        supply a supported interface model in later work, not an ignore flag.
        """
        if type(grid) is not RegionalGrid1D:
            raise MotionReductionError('explicit RegionalGrid1D required')
        if scalar(duration_s, 'duration', positive=True) != self.definition.duration_s:
            raise MotionReductionError('requested interval differs from the frozen prescription')
        if grid.cells+1 > self.limits.max_hits or grid.origin_m < 0 or grid.origin_m+grid.length_m > self.section.length_m:
            raise MotionReductionError('regional grid exceeds declared section support or work envelope')
        checks = self.reduction_checks()
        if not all(c['admissible'] for c in checks):
            raise MotionReductionError('; '.join(c['plate_id']+': '+c['reason'] for c in checks if not c['admissible']))
        with self._query(cancel), self.budget.reserve(256*(grid.cells+1)+16384, category='regional-forcing-faces'):
            seams = np.frombuffer(self._discontinuities, dtype='f8').reshape(-1, 2)
            if np.any((seams[:, 1] > grid.origin_m) & (seams[:, 0] < grid.origin_m+grid.length_m)):
                raise MotionReductionError('interior plate discontinuity needs an explicit supported interface law, even between grid faces')
            offsets = np.linspace(grid.origin_m, grid.origin_m+grid.length_m, grid.cells+1)
            if np.any(np.diff(offsets) <= 0):
                raise MotionReductionError('regional face spacing is unresolvable at this origin')
            samples = self.project(offsets, frame_id=frame_id, epoch_id=epoch_id, time_s=start_time_s,
                                   selections=selections, backend=backend, cancel=cancel)
            pairs = samples.owner_pairs; values = samples.components_m_s
            starts = np.r_[0, np.flatnonzero(pairs[1:, 0] != pairs[:-1, 0])+1]
            ends = np.r_[starts[1:], len(pairs)]
            if np.any(np.all(np.diff(samples.positions_m, axis=0) == 0, axis=1)):
                raise MotionReductionError('distinct grid faces collapse at the supplied coordinate origin')
            # Resolve only a common EXACT sided value, never average different
            # plate velocities. Vector reduction avoids a Python loop per face.
            same = np.minimum.reduceat(values[:, 0], starts) == np.maximum.reduceat(values[:, 0], starts)
            selected = samples.selected_rows
            rows = np.where(selected >= 0, selected, starts)
            for i in np.flatnonzero(~same):
                row = int(selected[i])
                if i not in (0, grid.cells) or row < 0:
                    raise MotionReductionError('two-sided discontinuous face velocity needs an explicit supported interface law')
                self._check_endpoint_side(grid, int(i), samples.region_ids[int(pairs[row, 1])])
            velocity = values[rows, 0].copy()
            desc = {'schema': _SCHEMA, 'method': _METHOD, 'solver_ready': True,
                    'grid': asdict(grid), 'samples': samples.descriptor(),
                    'scope': 'column inventory per reference section metric; no stress, force, uplift or material initialisation',
                    'inventory_convention': ('volume / (reference arc length * reference_width_m); not raw radial thickness'
                                             if self._spherical else 'column thickness per unit transverse measure'),
                    'temporal_contract': 'start-epoch spatial prescription held fixed for exactly the declared interval'}
            arrays = dict(samples.arrays(), face_velocity_m_s=velocity)
            out = object.__new__(RegionalFaceForcing)
            for key, value in (('definition', self.definition), ('section', self.section), ('reduction', self.reduction),
                               ('grid', grid), ('samples', samples), ('_velocity', velocity.tobytes()),
                               ('_descriptor', _json(desc)), ('forcing_id', _array_digest(arrays, desc))):
                object.__setattr__(out, key, value)
            return out

    def _check_endpoint_side(self, grid, face, region_id):
        topology = self.definition.topology
        if type(topology) is SphericalAtlas:
            # A named region may span differently charted patches. Avoid pretending
            # one patch proves the whole adjacent arc; global discontinuous one-sided
            # endpoint selection is a deliberately refused extension.
            raise MotionReductionError('discontinuous atlas endpoint selection requires a separately verified regional crop')
        region = next(r for r in topology.regions if r.region_id == region_id)
        a, b = ((grid.origin_m, grid.origin_m+grid.spacing_m) if face == 0 else
                (grid.origin_m+grid.length_m-grid.spacing_m, grid.origin_m+grid.length_m))
        shape = region.geometry._projected._geom if self._spherical else region.geometry._geom
        # Network spherical regions may have their own charts, so reproject the
        # two positions through that region, not the network's indexing chart.
        if self._spherical:
            p, _ = self._geometry(np.array((a, b)))
            line = LineString(region.geometry.chart._project(p / self.section.sphere.radius_m))
        else:
            line = self._line(a, b)
        if not shapely.covers(shape, line):
            raise MotionReductionError('selected endpoint owner does not cover the adjacent cell on the section side')

    def project_batches(self, batches, **kwargs):
        for offsets in batches:
            yield self.project(offsets, **kwargs)

    def close(self):
        with self._lock:
            if self._active:
                raise MotionReductionError('join active queries before closing the motion adapter')
            if self._closed: return
            self._closed = True
        self._stack.close()

    def __enter__(self):
        with self._query(None): pass
        return self

    def __exit__(self, *args): self.close()


def save_regional_forcing(result, store, *, budget=None, cancel=None):
    """Existing ArrayStore only; deduplicated topology plus atomic forcing snapshot."""
    from .storage import ArrayStore
    if type(result) is not RegionalFaceForcing or not isinstance(store, ArrayStore):
        raise MotionReductionError('typed forcing and ArrayStore required')
    _check_cancel(cancel)
    with ExecutionContext('reference') as context:
        if context.identity != result.samples.descriptor()['execution_id']:
            raise MotionReductionError('changed source/runtime cannot publish historical forcing')
        if _array_digest(result.arrays(), result.descriptor()) != result.forcing_id:
            raise MotionReductionError('forcing identity mismatch')
        saver = save_spherical_atlas if type(result.definition.topology) is SphericalAtlas else save_boundary_network
        saver(result.definition.topology, store, budget=budget, cancel=cancel)
        context.verify(); _check_cancel(cancel)
        return store.put(result.forcing_id, result.arrays(), result.descriptor(), budget=budget, cancel=cancel)


def _source_from_record(record):
    value = dict(record); value['references'] = tuple(value['references'])
    return GeologySource(**value)


def _restore_definition(meta, topology):
    record = dict(meta)
    record.pop('topology_id'); record.pop('topology_kind')
    motions = []
    for raw in record.pop('motions'):
        m = dict(raw); m['source'] = _source_from_record(m['source'])
        for name in ('translation_m_s', 'angular_velocity_rad_s', 'pivot_m'):
            m[name] = tuple(m[name])
        motions.append(PrescribedPlateMotion(**m))
    record['source'] = _source_from_record(record['source'])
    out = RegionalMotionDefinition(topology, tuple(motions), **record)
    if _json(out.descriptor()) != _json(meta):
        raise MotionReductionError('restored motion definition mismatch')
    return out


def _restore_section(meta):
    record = dict(meta); kind = record.pop('kind'); record['source'] = _source_from_record(record['source'])
    cls = PlanarRegionalSection if kind == 'planar' else SphericalRegionalSection if kind == 'sphere' else None
    if cls is None:
        raise MotionReductionError('unsupported saved section kind')
    if cls is SphericalRegionalSection:
        record['sphere'] = SphericalFrame(**record['sphere'])
    for name in ('origin_m', 'direction_xy', 'frame_velocity_m_s', 'frame_angular_velocity_rad_s', 'start_direction', 'pole_direction'):
        if name in record: record[name] = tuple(record[name])
    return cls(**record)


def load_regional_forcing(store, forcing_id, *, limits=None, budget=None, cancel=None):
    """Rebuild definition and evaluate saved grid; refuse changed source or payload.

    Re-evaluation is bounded kinematics, not a dynamics simulation. Geometry and
    arrays use the store's existing checks/dedup/cache. A version label alone is
    never accepted as the original source/runtime identity.
    """
    from .storage import ArrayStore
    if not isinstance(store, ArrayStore):
        raise MotionReductionError('ArrayStore required')
    if type(forcing_id) is not str or len(forcing_id) != 64 or any(c not in '0123456789abcdef' for c in forcing_id):
        raise MotionReductionError('forcing SHA-256 required')
    _check_cancel(cancel)
    meta = store.metadata(forcing_id)
    if meta is None: return None
    try:
        if meta['schema'] != _SCHEMA or meta['method'] != _METHOD or meta['solver_ready'] is not True:
            raise MotionReductionError('unsupported saved forcing schema')
        sample = meta['samples']; definition_record = sample['definition']
        with ExecutionContext('reference') as context:
            if context.identity != sample['execution_id']:
                raise MotionReductionError('source/runtime mismatch; no automatic forcing rebind')
            kind = definition_record['topology_kind']
            loader = load_spherical_atlas if kind == 'atlas' else load_boundary_network if kind == 'network' else None
            if loader is None: raise MotionReductionError('unsupported saved topology')
            topology = loader(store, definition_record['topology_id'], limits=limits, budget=budget, cancel=cancel)
            if topology is None: raise MotionReductionError('saved forcing lacks its ownership topology')
            definition = _restore_definition(definition_record, topology)
            section = _restore_section(sample['section'])
            r = dict(sample['reduction']); r['source'] = _source_from_record(r['source'])
            reduction = RegionalReduction(**r)
            grid = RegionalGrid1D(**meta['grid'])
            selections = sample['selections']
            with PreparedRegionalForcing(definition, section, reduction, limits=limits, budget=budget, cancel=cancel) as plan:
                result = plan.faces(grid, frame_id=section.frame_id, epoch_id=definition.epoch_id,
                                    start_time_s=definition.start_time_s, duration_s=definition.duration_s,
                                    selections=None if selections is None else tuple(selections), backend=sample['backend'], cancel=cancel)
            if result.forcing_id != forcing_id or result.descriptor() != meta:
                raise MotionReductionError('restored forcing policy/identity mismatch')
            arrays = store.get(forcing_id, budget=budget)
            expected = result.arrays()
            if arrays is None or set(arrays) != set(expected) or any(
                    arrays[k].dtype != expected[k].dtype or arrays[k].shape != expected[k].shape or arrays[k].tobytes() != expected[k].tobytes() for k in expected):
                raise MotionReductionError('stored forcing payload disagrees with reconstructed kinematics')
            context.verify(); _check_cancel(cancel)
            return result
    except (KeyError, TypeError, AttributeError) as exc:
        raise MotionReductionError('malformed forcing snapshot') from exc
