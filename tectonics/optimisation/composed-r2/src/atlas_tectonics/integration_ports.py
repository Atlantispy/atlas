"""The I04/I05 port record: P1 columns and P5 plate motion as owned, immutable values (I04 Part A).

The record is tectonics/docs/I04_I05_PORTS.md. Every port value carries one header (parent state, interval, common
endpoint, I03 network and support identities, datum, model/parameter identity, frame, owner, producer); a missing
required value refuses and is never read as zero. P1 carries an explicit unknown mask per point; P5 has none, because
every plate of its balance has a value. Ports carry values, not transfers: every debit and credit still goes through
the I02 ledger once. P2 and P3 are I05's (integration_properties); P4 is reserved; P6 and P7 (I04.3, the D2 belt's
increment and dissipation) and P9 (I04.4, the boundary reaction for I07/I09) are coded here and issued by
integration_feedback; P8 is not issued (no admitted open-base strip).

P1 support is the plate-boundary trace: one point at the midpoint of every boundary edge, on each side. The GPE
torque on a rigid plate is a boundary integral (integration_driving), so these are the only columns it needs.

SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
import hashlib
import math
from numbers import Real

import numpy as np

from . import integration_sphere as S
from . import integration_state as _state
from ._validation import TectonicsError
from .materials import _json


SCHEMA = 'atlas.i04-port.v1'
TRACE_SUPPORT = 'atlas.i04-trace-support.v1'
MATERIAL_TRACE_SUPPORT = 'atlas.i05-material-trace-support.v1'
PLATE_SUPPORT = 'atlas.i04-plate-support.v1'
# Water depths are admitted only from a labelled test input ('test:' prefix) or a declared D5 producer. No D5
# producer exists yet (I08), so the producer list is empty.
TEST_PREFIX = 'test:'
D5_PRODUCERS = ()
PORTS = ('P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8', 'P9')
PIECE_SUPPORT = 'atlas.i05-piece-support.v1'      # P6 and P7: the endpoint state's (face, cohort) pieces
REACTION = 'atlas.i04-boundary-reaction.v1'      # P9, on the P1 trace support
HEAT_NOT_CONVERTED = 'atlas.i04-dissipation-not-heated.v1'   # IN-05 v1: P7 reported, not booked as heat
REPRESENTATIONS = ('fv-cell-mean',)  # P1 amendment of 4 October 2026: a face of bitwise-equal layer structure
MAX_LAYERS = 32          # the retained I01 GPE column bound (cases/i01_gpe_v1.json max_layers)
MAX_POINTS = 1 << 20

MISSING_VALUE = 'missing value'
STALE_IDENTITY = 'stale identity'
INCOMPATIBLE_SUPPORT = 'incompatible support'
UNIT_MISMATCH = 'unit mismatch'
UNRESOLVED_COLUMN = 'unresolved column'
UNSUPPORTED = 'unsupported'
CODES = (MISSING_VALUE, STALE_IDENTITY, INCOMPATIBLE_SUPPORT, UNIT_MISMATCH, UNRESOLVED_COLUMN, UNSUPPORTED)

LEFT, RIGHT = 'left', 'right'
COLUMN_UNITS = dict(thickness_m='m', reference_density_kg_m3='kg/m3', alpha_per_k='1/K',
                    bottom_temperature_k='K', top_temperature_k='K', water_depth_m='m')
MOTION_UNITS = dict(omega_rad_s='rad/s')


class PortRefused(TectonicsError):
    """A port value that cannot be issued or consumed; ``code`` is one of CODES.

    ``detail`` carries the underlying I01 REFUSED_* code or kernel message when a port refusal wraps one.
    """

    def __init__(self, message, code, detail=None):
        if code not in CODES:
            raise ValueError('unknown port refusal code')
        super().__init__(message)
        self.code = code
        self.detail = detail


def _name(value, label):
    """A nonblank name of at most 256 characters, refused as a port value (missing value) otherwise."""
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise PortRefused(label+' must be nonblank text of at most 256 characters', MISSING_VALUE, detail=label)
    return value


def plate_support_id(network_id, plate_ids):
    """P5 support: the network's plates, in order, as a versioned record bound to network_id."""
    _sha(network_id, 'network')
    return _digest(dict(schema=PLATE_SUPPORT, network_id=network_id, plate_ids=list(plate_ids)))


def _digest(record, arrays=()):
    digest = hashlib.sha256(_json(record))
    for name, array in arrays:
        digest.update(b'\0'+_json([name, array.dtype.str, list(array.shape)]))
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def _sha(value, label):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise PortRefused(label+' must be a sha256 identity', STALE_IDENTITY, detail=label)
    return value


def _seconds(value, label):
    """Finite seconds: a Python or NumPy real scalar (not bool), stored as float."""
    try:
        valid = not isinstance(value, bool) and isinstance(value, Real) and math.isfinite(float(value))
    except (TypeError, OverflowError):
        valid = False
    if not valid:
        raise PortRefused(label+' must be finite seconds', MISSING_VALUE, detail=label)
    return float(value)


@dataclass(frozen=True, slots=True)
class Header:
    """The common header of every port value. ``endpoint_s`` is the one time both sides evaluate at.

    network_id is the I03 network; support_id the digest of the versioned support record on it; datum_id the
    shared datum's digest, or None for a value whose producer used no datum (P1 requires one); parameter_id the
    producer's model/parameter identity; frame_id the network's frame (the axes every vector is expressed in).
    P4 is reserved and refuses.
    """
    port: str
    parent_state_id: str
    interval: tuple
    endpoint_s: float
    network_id: str
    support_id: str
    datum_id: str
    parameter_id: str
    frame_id: str
    owner: str
    producer: str

    def __post_init__(self):
        if self.port not in PORTS:
            raise PortRefused('unknown port', UNSUPPORTED)
        if self.port == 'P4':
            raise PortRefused('P4 (belt and basal state) is reserved in this record', UNSUPPORTED)
        _sha(self.parent_state_id, 'parent_state_id')
        _sha(self.network_id, 'network_id')
        _sha(self.support_id, 'support_id')
        if self.datum_id is not None:
            _sha(self.datum_id, 'datum_id')
        _sha(self.parameter_id, 'parameter_id')
        _name(self.frame_id, 'frame')
        _name(self.owner, 'port owner')
        _name(self.producer, 'port producer')
        if (type(self.interval) is not tuple or len(self.interval) != 4
                or any(type(v) is not int or isinstance(v, bool) for v in self.interval[:2])):
            raise PortRefused('interval is (start_step, end_step, start_s, end_s)', MISSING_VALUE, detail='interval')
        start, end = self.interval[:2]
        start_s, end_s = (_seconds(v, 'interval') for v in self.interval[2:])
        if not (0 <= start <= end <= _state.MAX_STEPS and start_s <= end_s):
            raise PortRefused('interval out of order or beyond the step ceiling', MISSING_VALUE, detail='interval')
        endpoint = _seconds(self.endpoint_s, 'endpoint_s')
        if not start_s <= endpoint <= end_s:
            raise PortRefused('the common endpoint lies outside its interval', MISSING_VALUE, detail='endpoint_s')
        object.__setattr__(self, 'interval', (start, end, start_s, end_s))
        object.__setattr__(self, 'endpoint_s', endpoint)

    def record(self):
        return dict(schema=SCHEMA, port=self.port, parent_state_id=self.parent_state_id,
                    interval=list(self.interval), endpoint_s=self.endpoint_s, network_id=self.network_id,
                    support_id=self.support_id, datum_id=self.datum_id, parameter_id=self.parameter_id,
                    frame_id=self.frame_id, owner=self.owner, producer=self.producer)


def _frozen(array, dtype):
    raw = np.ascontiguousarray(array, dtype=dtype)
    return np.frombuffer(raw.tobytes(), dtype=dtype).reshape(raw.shape)


@dataclass(frozen=True, init=False, eq=False, slots=True)
class TraceSupport(_state._Immutable):
    """P1 support on one network: every plate-boundary edge's endpoints and midpoint, in the sphere's axes.

    Edge e runs a -> b along its boundary record (closing edge included for a closed record); the left plate lies
    toward a x b (I03's convention). ``nu_left`` is the left plate's outward conormal, constant on the edge's great
    circle. Points are ordered edge-major, left then right, so point 2e+s belongs to edge e and side s. The
    support_id is the digest of this versioned record, bound to network_id.
    """
    network_id: str
    support_id: str
    radius_m: float
    boundary_ids: tuple
    edge_boundary: np.ndarray = field(repr=False)
    start: np.ndarray = field(repr=False)
    end: np.ndarray = field(repr=False)
    midpoint: np.ndarray = field(repr=False)
    nu_left: np.ndarray = field(repr=False)
    plates: tuple = field(repr=False)
    material_id: object = None
    piece_keys: object = field(default=None, repr=False)
    patch_ids: object = field(default=None, repr=False)
    original_edges: object = field(default=None, repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('TraceSupport is issued by trace_support()')

    @property
    def edges(self):
        return len(self.edge_boundary)

    def point_plate(self, point):
        edge, side = divmod(int(point), 2)
        return self.plates[edge][side]

    def directions(self):
        """Point directions in sphere axes: each edge midpoint twice (left, right)."""
        return np.repeat(self.midpoint, 2, axis=0)


def trace_support(network):
    """The P1 trace support of an issued network: no snapping, the stored shared vertex directions only."""
    if type(network) is not S.SphereNetwork:
        raise PortRefused('trace support needs an issued SphereNetwork', INCOMPATIBLE_SUPPORT)
    index = {vertex: i for i, vertex in enumerate(network.vertex_ids)}
    directions = np.asarray(network.vertex_direction, dtype=float)
    rows, starts, ends, owners = [], [], [], []
    for b, boundary in enumerate(network.boundaries):
        chain = list(boundary.vertex_ids)
        pairs = list(zip(chain, chain[1:]))+([(chain[-1], chain[0])] if boundary.closed else [])
        for first, second in pairs:
            rows.append(b)
            starts.append(directions[index[first]])
            ends.append(directions[index[second]])
            owners.append((boundary.left_plate_id, boundary.right_plate_id))
    if not rows or len(rows) > MAX_POINTS//2:
        raise PortRefused('a network needs between one and MAX_POINTS/2 boundary edges', INCOMPATIBLE_SUPPORT)
    a, b = np.array(starts), np.array(ends)
    total = a+b
    middle = total/np.linalg.norm(total, axis=1)[:, None]
    pole = np.cross(b, a)
    nu = pole/np.linalg.norm(pole, axis=1)[:, None]
    arrays = (('edge_boundary', _frozen(rows, np.int64)), ('start', _frozen(a, float)), ('end', _frozen(b, float)),
              ('midpoint', _frozen(middle, float)), ('nu_left', _frozen(nu, float)))
    ids = tuple(boundary.boundary_id for boundary in network.boundaries)
    record = dict(schema=TRACE_SUPPORT, network_id=network.network_id, radius_m=network.sphere.radius_m,
                  boundary_ids=list(ids), plates=[list(pair) for pair in owners],
                  point_order='edge-major; left then right', sides=[LEFT, RIGHT])
    return _state._issue(TraceSupport, network_id=network.network_id, support_id=_digest(record, arrays),
                         radius_m=float(network.sphere.radius_m), boundary_ids=ids, plates=tuple(owners),
                         material_id=None, piece_keys=None, patch_ids=None, original_edges=None,
                         **dict(arrays))


def material_trace_support(sphere):
    """Exact piecewise-material trace, split at contacts on either side of each edge.

    The spherical support producer owns geometric admission. This adapter binds
    its sided material/patch identities to the actual subarcs consumed by P1 and
    the analytic GPE boundary integral. It never reconstructs missing support from
    a cell average. The original edge map is retained for non-P1 consumers.
    """
    from . import integration_support as support_geometry

    base = trace_support(sphere.network)
    groups = support_geometry.material_trace_segments(sphere)
    if len(groups) != base.edges:
        raise PortRefused('material trace does not cover the network edges', INCOMPATIBLE_SUPPORT)
    starts, ends, rows, owners, keys, patches, original = [], [], [], [], [], [], []
    for edge, segments in enumerate(groups):
        if not segments:
            raise PortRefused('material trace has an uncovered edge', UNRESOLVED_COLUMN)
        previous = base.start[edge]
        for segment in segments:
            a, b = np.asarray(segment.start_direction, dtype=float), np.asarray(segment.end_direction, dtype=float)
            if (a.shape != (3,) or b.shape != (3,) or not np.isfinite(a).all() or not np.isfinite(b).all()
                    or not np.array_equal(a, previous) or np.array_equal(a, b)):
                raise PortRefused('material trace segments must form an unbroken ordered edge',
                                  INCOMPATIBLE_SUPPORT)
            starts.append(a)
            ends.append(b)
            rows.append(int(base.edge_boundary[edge]))
            owners.append(base.plates[edge])
            keys.append((segment.left_piece, segment.right_piece))
            patches.append((segment.left_patch, segment.right_patch))
            original.append(edge)
            previous = b
        if not np.array_equal(previous, base.end[edge]):
            raise PortRefused('material trace does not reach the original edge end', INCOMPATIBLE_SUPPORT)
    if len(rows) > MAX_POINTS//2:
        raise PortRefused('material trace exceeds MAX_POINTS/2 segments', INCOMPATIBLE_SUPPORT)
    a, b = np.asarray(starts), np.asarray(ends)
    total = a+b
    middle = total/np.linalg.norm(total, axis=1)[:, None]
    # Subarcs retain their parent's great-circle conormal, avoiding renormalising
    # a short cross product at a thin surviving material contact.
    normal = np.asarray([base.nu_left[e] for e in original])
    arrays = (('edge_boundary', _frozen(rows, np.int64)), ('start', _frozen(a, float)),
              ('end', _frozen(b, float)), ('midpoint', _frozen(middle, float)),
              ('nu_left', _frozen(normal, float)))
    record = dict(schema=MATERIAL_TRACE_SUPPORT, base_support_id=base.support_id,
                  material_id=sphere.material.material_id, original_edges=original,
                  piece_keys=keys, patch_ids=patches)
    return _state._issue(TraceSupport, network_id=base.network_id, support_id=_digest(record, arrays),
                         radius_m=base.radius_m, boundary_ids=base.boundary_ids, plates=tuple(owners),
                         material_id=sphere.material.material_id, piece_keys=tuple(keys),
                         patch_ids=tuple(patches), original_edges=tuple(original), **dict(arrays))


@dataclass(frozen=True, init=False, eq=False, slots=True)
class Columns(_state._Immutable):
    """P1: one bottom-to-top layered column per support point, with explicit unknowns.

    Layers of point i are rows offsets[i]:offsets[i+1] (the I01_GPE representation: thickness, reference density,
    expansivity, absolute bottom and top temperature). ``unknown[i]`` marks a point whose material the producer
    could not resolve; consumers refuse it. Water depth is present only from a 'test:'-labelled test input or a
    declared D5 producer (none exists yet).
    """
    header: Header
    offsets: np.ndarray = field(repr=False)
    thickness_m: np.ndarray = field(repr=False)
    reference_density_kg_m3: np.ndarray = field(repr=False)
    alpha_per_k: np.ndarray = field(repr=False)
    bottom_temperature_k: np.ndarray = field(repr=False)
    top_temperature_k: np.ndarray = field(repr=False)
    unknown: np.ndarray = field(repr=False)
    water_depth_m: object = field(repr=False)
    water_source: object
    sources: tuple
    port_id: str
    representation: object = None

    def __init__(self, *args, **kwargs):
        raise TypeError('Columns are issued by columns_port()')

    @property
    def points(self):
        return len(self.offsets)-1

    def layers(self, point):
        if type(point) is not int or not 0 <= point < self.points:
            raise PortRefused('no such support point', INCOMPATIBLE_SUPPORT)
        if self.unknown[point]:
            raise PortRefused('the column at point %d is unknown' % point, UNRESOLVED_COLUMN)
        lo, hi = int(self.offsets[point]), int(self.offsets[point+1])
        return tuple(array[lo:hi] for array in (self.thickness_m, self.reference_density_kg_m3, self.alpha_per_k,
                                                self.bottom_temperature_k, self.top_temperature_k))


def columns_port(header, offsets, thickness_m, reference_density_kg_m3, alpha_per_k, bottom_temperature_k,
                 top_temperature_k, *, unknown=None, sources, water_depth_m=None, water_source=None,
                 representation=None):
    """Issue one P1 value. Every known column needs 1..32 layers; values are copied and frozen.

    ``sources`` names, per point, the declared material or provenance (a nonblank name). Water depth requires a
    ``water_source`` that is a 'test:'-prefixed label (with a nonblank label after the prefix) or a declared D5
    producer (none exists yet); any other source is refused. ``representation`` (I05 amendment of 4 October 2026) is
    None, or per point None (one piece's own column) or (REPRESENTATIONS member, sorted contributing cohort names);
    when given it is recorded and bound into ``port_id``, and when absent the record is unchanged.
    """
    if type(header) is not Header or header.port != 'P1':
        raise PortRefused('a P1 header is required', UNSUPPORTED)
    if header.datum_id is None:
        raise PortRefused('P1 columns are always issued for a declared datum', MISSING_VALUE, detail='datum_id')
    offsets = np.asarray(offsets)
    if offsets.ndim != 1 or offsets.dtype.kind not in 'iu' or len(offsets) < 2 or offsets[0] != 0:
        raise PortRefused('offsets must be an integer prefix starting at zero', INCOMPATIBLE_SUPPORT)
    counts = np.diff(offsets)
    points = len(counts)
    unknown = np.zeros(points, bool) if unknown is None else np.asarray(unknown)
    if unknown.shape != (points,) or unknown.dtype != bool:
        raise PortRefused('unknown must be one boolean per point', INCOMPATIBLE_SUPPORT)
    if np.any(counts < 0) or np.any(counts[~unknown] < 1) or np.any(counts > MAX_LAYERS) or np.any(counts[unknown]):
        raise PortRefused('a known column needs 1..32 layers and an unknown one none', MISSING_VALUE,
                          detail='offsets')
    total = int(offsets[-1])
    values = []
    for name, value in (('thickness_m', thickness_m), ('reference_density_kg_m3', reference_density_kg_m3),
                        ('alpha_per_k', alpha_per_k), ('bottom_temperature_k', bottom_temperature_k),
                        ('top_temperature_k', top_temperature_k)):
        a = np.asarray(value)
        if a.shape != (total,) or a.dtype.kind not in 'fiu' or not np.all(np.isfinite(a)):
            raise PortRefused(name+': one finite value per layer required', MISSING_VALUE, detail=name)
        values.append((name, _frozen(a, float)))
    if type(sources) is not tuple or len(sources) != points:
        raise PortRefused('one source name per point is required', MISSING_VALUE, detail='sources')
    for source in sources:
        _name(source, 'column source')
    water = None
    if water_depth_m is not None:
        if water_source is None:
            raise PortRefused('water depths only from a labelled test input or a declared D5 producer', UNSUPPORTED,
                              detail='water_source')
        _name(water_source, 'water_source')
        labelled = water_source.startswith(TEST_PREFIX) and water_source[len(TEST_PREFIX):].strip()
        if not (labelled or water_source in D5_PRODUCERS):
            raise PortRefused('water depths only from a labelled test input or a declared D5 producer',
                              UNSUPPORTED, detail='water_source')
        w = np.asarray(water_depth_m)
        if w.shape != (points,) or w.dtype.kind not in 'fiu' or not np.all(np.isfinite(w)) or np.any(w < 0):
            raise PortRefused('water depth: one finite nonnegative value per point', MISSING_VALUE,
                              detail='water_depth_m')
        water = _frozen(w, float)
    elif water_source is not None:
        raise PortRefused('a water source without water depths', MISSING_VALUE, detail='water_depth_m')
    arrays = [('offsets', _frozen(offsets, np.int64))]+values+[('unknown', _frozen(unknown, bool))]
    if water is not None:
        arrays.append(('water_depth_m', water))
    record = dict(header=header.record(), units=COLUMN_UNITS, sources=list(sources), water_source=water_source)
    if type(representation) is tuple and all(entry is None for entry in representation):
        representation = None             # one value, one identity: no point is a cell mean (P1-NOTE-3)
    if representation is not None:
        if type(representation) is not tuple or len(representation) != points:
            raise PortRefused('one representation entry per point is required', MISSING_VALUE,
                              detail='representation')
        for entry in representation:
            if entry is not None and (type(entry) is not tuple or len(entry) != 2 or entry[0] not in REPRESENTATIONS
                                      or type(entry[1]) is not tuple or len(entry[1]) < 2
                                      or list(entry[1]) != sorted(set(entry[1]))):
                raise PortRefused('a representation entry is None or (representation, sorted cohort names)',
                                  UNSUPPORTED, detail='representation')
            if entry is not None:
                for name in entry[1]:
                    _name(name, 'contributing cohort')
        record['representation'] = [None if entry is None else [entry[0], list(entry[1])] for entry in representation]
    return _state._issue(Columns, header=header, water_depth_m=water, water_source=water_source, sources=sources,
                         port_id=_digest(record, arrays), representation=representation,
                         **{name: array for name, array in arrays if name != 'water_depth_m'})


@dataclass(frozen=True, init=False, eq=False, slots=True)
class PlateMotion(_state._Immutable):
    """P5: each plate's rigid angular velocity in the network's axes, from one D1 balance (integration_driving).

    Issued only by integration_driving.motion_port from a Balance. It holds rigid rotations only: deforming-region
    velocities have no field here, so they cannot be sent (structurally unsupported in Part A). ``evaluation``
    carries the D-P3 label of the explicit Part A evaluation.
    """
    header: Header
    plate_ids: tuple
    omega_rad_s: np.ndarray = field(repr=False)
    frame_id: str
    balance_id: str
    evaluation: str
    port_id: str
    coupling_residual: object = None

    def __init__(self, *args, **kwargs):
        raise TypeError('PlateMotion is issued by integration_driving.motion_port() or the coupled issuer')

    @property
    def duration_s(self):
        return self.header.interval[3]-self.header.interval[2]

    def omega(self, plate_id):
        if plate_id not in self.plate_ids:
            raise PortRefused('no motion for plate %r' % (plate_id,), MISSING_VALUE, detail='plate_ids')
        return self.omega_rad_s[self.plate_ids.index(plate_id)].copy()


def _plate_motion(header, plate_ids, omega_rad_s, *, frame_id, balance_id, evaluation, coupling_residual=None):
    """Private: P5 is issued only through integration_driving.motion_port, from a Balance, or by the coupled issuer
    (integration_feedback), which records its fixed-point residual (absent from Part A records)."""
    if type(header) is not Header or header.port != 'P5':
        raise PortRefused('a P5 header is required', UNSUPPORTED)
    if header.frame_id != frame_id:
        raise PortRefused('the P5 header and value frames differ', STALE_IDENTITY, detail='frame_id')
    if type(plate_ids) is not tuple or not plate_ids or len(set(plate_ids)) != len(plate_ids):
        raise PortRefused('unique plate IDs required', MISSING_VALUE, detail='plate_ids')
    omega = np.asarray(omega_rad_s)
    if omega.shape != (len(plate_ids), 3) or omega.dtype.kind != 'f' or not np.all(np.isfinite(omega)):
        raise PortRefused('one finite angular velocity per plate required', MISSING_VALUE, detail='omega_rad_s')
    _name(frame_id, 'frame')
    _name(evaluation, 'evaluation')
    _sha(balance_id, 'balance')
    omega = _frozen(omega, float)
    record = dict(header=header.record(), units=MOTION_UNITS, plate_ids=list(plate_ids), frame_id=frame_id,
                  balance_id=balance_id, evaluation=evaluation)
    if coupling_residual is not None:
        coupling_residual = float(coupling_residual)
        if not (math.isfinite(coupling_residual) and coupling_residual >= 0):
            raise PortRefused('the coupling residual is finite and nonnegative', MISSING_VALUE,
                              detail='coupling_residual')
        record['coupling_residual'] = coupling_residual
    return _state._issue(PlateMotion, header=header, plate_ids=plate_ids, omega_rad_s=omega, frame_id=frame_id,
                         balance_id=balance_id, evaluation=evaluation, coupling_residual=coupling_residual,
                         port_id=_digest(record, (('omega_rad_s', omega),)))


# ---------------------------------------------------------------------------------------------------------------
# P6, P7 (I04.3) and P9 (I04.4). Rows run bottom to top within each piece, with offsets as P2.

INCREMENT_UNITS = dict(kappa_increment='1', bound='1')
DISSIPATION_UNITS = dict(creep_energy_j_m3='J/m3', plastic_energy_j_m3='J/m3')
REACTION_UNITS = dict(velocity_jump_m_s='m/s', traction_left_n_m='N/m', edge_length_m='m')


def _rows(header, port, pieces, offsets, arrays, label):
    if type(header) is not Header or header.port != port:
        raise PortRefused('a %s header is required' % port, UNSUPPORTED)
    if type(pieces) is not tuple or any(type(p) is not tuple or len(p) != 2 for p in pieces):
        raise PortRefused('pieces are (face, cohort) pairs', MISSING_VALUE, detail='pieces')
    offsets = np.asarray(offsets)
    if (offsets.dtype.kind not in 'iu' or offsets.shape != (len(pieces)+1,) or offsets[0] != 0
            or np.any(np.diff(offsets) < 1)):
        raise PortRefused('offsets give each piece its rows', MISSING_VALUE, detail='offsets')
    out = [('offsets', _frozen(offsets, np.int64))]
    for name, value in arrays:
        value = np.asarray(value)
        if value.shape != (int(offsets[-1]),) or value.dtype.kind != 'f' or not np.all(np.isfinite(value)):
            raise PortRefused('%s: one finite value per piece row' % label, MISSING_VALUE, detail=name)
        out.append((name, _frozen(value, float)))
    return out


@dataclass(frozen=True, init=False, eq=False, slots=True)
class MechanicalIncrement(_state._Immutable):
    """P6: the raw-kappa increment of the interval per endpoint piece and sublayer (bottom to top), from the D2
    integration (D-P1), with its ceiling 2 dt e of the same finite-volume mean. Increments are never negative and
    never above the ceiling."""
    header: Header
    pieces: tuple
    offsets: np.ndarray = field(repr=False)
    kappa_increment: np.ndarray = field(repr=False)
    bound: np.ndarray = field(repr=False)
    port_id: str

    def __init__(self, *args, **kwargs):
        raise TypeError('MechanicalIncrement is issued by integration_feedback')

    def increments(self):
        """((face, cohort), values top down) pairs: the I05 MovingAdvance order (the cohort record's)."""
        out = []
        for i, piece in enumerate(self.pieces):
            values = self.kappa_increment[int(self.offsets[i]):int(self.offsets[i+1])][::-1]
            out.append((piece, tuple(float(v) for v in values)))
        return tuple(out)


def _mechanical_increment(header, pieces, offsets, kappa_increment, bound):
    arrays = _rows(header, 'P6', pieces, offsets, (('kappa_increment', kappa_increment), ('bound', bound)), 'P6')
    values, ceiling = arrays[1][1], arrays[2][1]
    if np.any(values < 0):
        raise PortRefused('a negative raw-history increment', UNSUPPORTED, detail='negative increment')
    if np.any(values > ceiling*(1+2e-11+4*2.**-52)):       # the column kernel's rate tolerance (2e-11)
        raise PortRefused('an increment above 2 integral e dt', UNSUPPORTED, detail='increment above 2∫e dt')
    record = dict(schema=SCHEMA, header=header.record(), units=INCREMENT_UNITS, pieces=[list(p) for p in pieces])
    return _state._issue(MechanicalIncrement, header=header, pieces=pieces, offsets=arrays[0][1],
                         kappa_increment=values, bound=ceiling, port_id=_digest(record, arrays))


@dataclass(frozen=True, init=False, eq=False, slots=True)
class Dissipation(_state._Immutable):
    """P7: the interval's creep and plastic energies per endpoint piece and sublayer (J/m3, the line-quadrature
    deposit of the belt cells), from the same integration as P6. The per-edge belt power is a D1/P9 diagnostic, not a
    P7 field. ``heat_rule`` names the IN-05 rule; in v1 it is HEAT_NOT_CONVERTED: dissipation is reported and enters
    the power account, but is not booked as heat."""
    header: Header
    pieces: tuple
    offsets: np.ndarray = field(repr=False)
    creep_energy_j_m3: np.ndarray = field(repr=False)
    plastic_energy_j_m3: np.ndarray = field(repr=False)
    heat_rule: str
    port_id: str

    def __init__(self, *args, **kwargs):
        raise TypeError('Dissipation is issued by integration_feedback')


def _dissipation(header, pieces, offsets, creep, plastic, heat_rule):
    arrays = _rows(header, 'P7', pieces, offsets, (('creep_energy_j_m3', creep),
                                                   ('plastic_energy_j_m3', plastic)), 'P7')
    if heat_rule != HEAT_NOT_CONVERTED:
        raise PortRefused('only the declared v1 rule %r is admitted' % HEAT_NOT_CONVERTED, UNSUPPORTED,
                          detail='heat_rule')
    if np.any(arrays[1][1] < 0) or np.any(arrays[2][1] < 0):
        raise PortRefused('dissipated energy is never negative', UNSUPPORTED, detail='energy')
    record = dict(schema=SCHEMA, header=header.record(), units=DISSIPATION_UNITS, pieces=[list(p) for p in pieces],
                  heat_rule=heat_rule)
    return _state._issue(Dissipation, header=header, pieces=pieces, offsets=arrays[0][1],
                         creep_energy_j_m3=arrays[1][1], plastic_energy_j_m3=arrays[2][1], heat_rule=heat_rule,
                         port_id=_digest(record, arrays))


@dataclass(frozen=True, init=False, eq=False, slots=True)
class BoundaryReaction(_state._Immutable):
    """P9 (atlas.i04-boundary-reaction.v1): the work-conjugate boundary reaction on the oriented P1 trace support.

    Per trace edge: the velocity jump v_R - v_L at the midpoint (m/s), the line traction on the left plate (N/m; the
    right plate takes the opposite) and the edge length (m); ``owned`` marks the edges whose reaction this value
    carries (the reduced belt's). The left torque is R sum m x f L, the power sum f.dv L: the same midpoint quadrature
    as the D1 belt term, so a regional replacement returning tractions here enters D1 as exactly these torques."""
    header: Header
    owned: tuple
    velocity_jump_m_s: np.ndarray = field(repr=False)
    traction_left_n_m: np.ndarray = field(repr=False)
    edge_length_m: np.ndarray = field(repr=False)
    port_id: str

    def __init__(self, *args, **kwargs):
        raise TypeError('BoundaryReaction is issued by integration_feedback')

    def power_w(self):
        """sum f.dv L over the owned edges: the belt's dissipation (no sign is imposed on regional reactions)."""
        mask = np.asarray(self.owned, dtype=bool)
        return math.fsum(float(x) for x in np.einsum('ij,ij->i', self.traction_left_n_m[mask],
                                                     self.velocity_jump_m_s[mask])*self.edge_length_m[mask])

    def torques(self, plate_ids, plates, radius_m, midpoints):
        """Per-plate torques of the owned edges by the D1 belt term's midpoint quadrature: R m x f L on the left
        plate, the opposite on the right (``plates`` are the trace support's (left, right) pairs)."""
        order = {p: i for i, p in enumerate(plate_ids)}
        out = np.zeros((len(plate_ids), 3))
        for e, owned in enumerate(self.owned):
            if not owned:
                continue
            tau = radius_m*self.edge_length_m[e]*np.cross(midpoints[e], self.traction_left_n_m[e])
            out[order[plates[e][0]]] += tau
            out[order[plates[e][1]]] -= tau
        return out


def _boundary_reaction(header, support, owned, velocity, traction, length):
    if type(header) is not Header or header.port != 'P9':
        raise PortRefused('a P9 header is required', UNSUPPORTED)
    if type(support) is not TraceSupport or header.support_id != support.support_id:
        raise PortRefused('P9 lies on the P1 trace support', INCOMPATIBLE_SUPPORT, detail='support_id')
    if type(owned) is not tuple or len(owned) != support.edges or any(type(o) is not bool for o in owned):
        raise PortRefused('one ownership flag per trace edge', MISSING_VALUE, detail='owned')
    arrays = []
    for name, value, shape in (('velocity_jump_m_s', velocity, (support.edges, 3)),
                               ('traction_left_n_m', traction, (support.edges, 3)),
                               ('edge_length_m', length, (support.edges,))):
        value = np.asarray(value)
        if value.shape != shape or value.dtype.kind != 'f' or not np.all(np.isfinite(value)):
            raise PortRefused('P9: finite values on every trace edge', MISSING_VALUE, detail=name)
        arrays.append((name, _frozen(value, float)))
    record = dict(schema=REACTION, header=header.record(), units=REACTION_UNITS, owned=list(owned))
    return _state._issue(BoundaryReaction, header=header, owned=owned, velocity_jump_m_s=arrays[0][1],
                         traction_left_n_m=arrays[1][1], edge_length_m=arrays[2][1], port_id=_digest(record, arrays))
