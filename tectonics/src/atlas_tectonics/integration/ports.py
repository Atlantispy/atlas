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
import sys
from numbers import Real

import numpy as np

from atlas_tectonics.integration.geometry import sphere as S
from . import state as _state
from atlas_tectonics._validation import TectonicsError, _replay_fsum
from atlas_tectonics._validation import frozen_contiguous as _frozen
from atlas_tectonics.integration.resources import select_budget
from atlas_tectonics.integration.resources import check_event_or_callable
from atlas_tectonics.integration.resources import json_sha256
from atlas_tectonics.materials.materials import _json


SCHEMA = 'atlas.i04-port.v1'
TRACE_SUPPORT = 'atlas.i04-trace-support.v1'
MATERIAL_TRACE_SUPPORT = 'atlas.i05-material-trace-support.v1'
PLATE_SUPPORT = 'atlas.i04-plate-support.v1'
# Water depths are admitted only from a labelled test input ('test:' prefix) or a declared D5 producer. No D5
# producer exists yet (I08), so the producer list is empty.
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
    return json_sha256(dict(schema=PLATE_SUPPORT, network_id=network_id, plate_ids=list(plate_ids)), _json)


def _digest(record, arrays=()):
    digest = hashlib.sha256(_json(record))
    for name, array in arrays:
        digest.update(b'\0'+_json([name, array.dtype.str, list(array.shape)]))
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


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
    datum_id: str | None
    parameter_id: str
    frame_id: str
    owner: str
    producer: str

    def __post_init__(self):
        _name(self.frame_id, 'frame')
        _name(self.owner, 'port owner')
        _name(self.producer, 'port producer')
        start, end = self.interval[:2]
        start_s, end_s = (_seconds(v, 'interval') for v in self.interval[2:])
        endpoint = _seconds(self.endpoint_s, 'endpoint_s')
        object.__setattr__(self, 'interval', (start, end, start_s, end_s))
        object.__setattr__(self, 'endpoint_s', endpoint)

    def record(self):
        return dict(schema=SCHEMA, port=self.port, parent_state_id=self.parent_state_id,
                    interval=list(self.interval), endpoint_s=self.endpoint_s, network_id=self.network_id,
                    support_id=self.support_id, datum_id=self.datum_id, parameter_id=self.parameter_id,
                    frame_id=self.frame_id, owner=self.owner, producer=self.producer)


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
    return _state._issue(TraceSupport, network_id=network.network_id, support_id=S._identity(_json(record), arrays),
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
    from . import support as support_geometry

    base = trace_support(sphere.network)
    groups = support_geometry.material_trace_segments(sphere)
    starts, ends, rows, owners, keys, patches, original = [], [], [], [], [], [], []
    for edge, segments in enumerate(groups):
        for segment in segments:
            a, b = np.asarray(segment.start_direction, dtype=float), np.asarray(segment.end_direction, dtype=float)
            starts.append(a)
            ends.append(b)
            rows.append(int(base.edge_boundary[edge]))
            owners.append(base.plates[edge])
            keys.append((segment.left_piece, segment.right_piece))
            patches.append((segment.left_patch, segment.right_patch))
            original.append(edge)
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
    return _state._issue(TraceSupport, network_id=base.network_id, support_id=S._identity(_json(record), arrays),
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
    offsets = np.asarray(offsets)
    counts = np.diff(offsets)
    points = len(counts)
    unknown = np.zeros(points, bool) if unknown is None else np.asarray(unknown)
    values = []
    for name, value in (('thickness_m', thickness_m), ('reference_density_kg_m3', reference_density_kg_m3),
                        ('alpha_per_k', alpha_per_k), ('bottom_temperature_k', bottom_temperature_k),
                        ('top_temperature_k', top_temperature_k)):
        a = np.asarray(value)
        values.append((name, _frozen(a, float)))
    for source in sources:
        _name(source, 'column source')
    water = None
    if water_depth_m is not None:
        _name(water_source, 'water_source')
        w = np.asarray(water_depth_m)
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
        for entry in representation:
            if entry is not None:
                for name in entry[1]:
                    _name(name, 'contributing cohort')
        record['representation'] = [None if entry is None else [entry[0], list(entry[1])] for entry in representation]
    return _state._issue(Columns, header=header, water_depth_m=water, water_source=water_source, sources=sources,
                         port_id=S._identity(_json(record), arrays), representation=representation,
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
        return self.omega_rad_s[self.plate_ids.index(plate_id)].copy()


def _plate_motion(header, plate_ids, omega_rad_s, *, frame_id, balance_id, evaluation, coupling_residual=None):
    """Private: P5 is issued only through integration_driving.motion_port, from a Balance, or by the coupled issuer
    (integration_feedback), which records its fixed-point residual (absent from Part A records)."""
    omega = np.asarray(omega_rad_s)
    _name(frame_id, 'frame')
    _name(evaluation, 'evaluation')
    omega = _frozen(omega, float)
    record: dict[str, object] = dict(header=header.record(), units=MOTION_UNITS, plate_ids=list(plate_ids), frame_id=frame_id,
                  balance_id=balance_id, evaluation=evaluation)
    if coupling_residual is not None:
        coupling_residual = float(coupling_residual)
        record['coupling_residual'] = coupling_residual
    return _state._issue(PlateMotion, header=header, plate_ids=plate_ids, omega_rad_s=omega, frame_id=frame_id,
                         balance_id=balance_id, evaluation=evaluation, coupling_residual=coupling_residual,
                         port_id=S._identity(_json(record), (('omega_rad_s', omega),)))


# ---------------------------------------------------------------------------------------------------------------
# P6, P7 (I04.3) and P9 (I04.4). Rows run bottom to top within each piece, with offsets as P2.

INCREMENT_UNITS = dict(kappa_increment='1', bound='1')
DISSIPATION_UNITS = dict(creep_energy_j_m3='J/m3', plastic_energy_j_m3='J/m3')
REACTION_UNITS = dict(velocity_jump_m_s='m/s', traction_left_n_m='N/m', edge_length_m='m')


def _rows(header, port, pieces, offsets, arrays, label):
    offsets = np.asarray(offsets)
    out = [('offsets', _frozen(offsets, np.int64))]
    for name, value in arrays:
        value = np.asarray(value)
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
    record = dict(schema=SCHEMA, header=header.record(), units=INCREMENT_UNITS, pieces=[list(p) for p in pieces])
    return _state._issue(MechanicalIncrement, header=header, pieces=pieces, offsets=arrays[0][1],
                         kappa_increment=values, bound=ceiling, port_id=S._identity(_json(record), arrays))


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
    record = dict(schema=SCHEMA, header=header.record(), units=DISSIPATION_UNITS, pieces=[list(p) for p in pieces],
                  heat_rule=heat_rule)
    return _state._issue(Dissipation, header=header, pieces=pieces, offsets=arrays[0][1],
                         creep_energy_j_m3=arrays[1][1], plastic_energy_j_m3=arrays[2][1], heat_rule=heat_rule,
                         port_id=S._identity(_json(record), arrays))


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

    def torques(self, plate_ids, plates, radius_m, midpoints, *, budget=None, cancel=None):
        """Original rounded edge torques, accurately reduced on each output plate.

        Native binary64 rows use compact original-order incidences. Exceptional
        lanes retain ordered NumPy arithmetic; a widened row selects that original
        vector route for the entire call, without evaluating any product twice.
        """
        check_event_or_callable(cancel, 'constitutive work cancelled')
        owner = select_budget(budget)
        count = len(plate_ids)
        owned_count = 0
        for edge, owned in enumerate(self.owned):
            if edge % 1024 == 0:
                check_event_or_callable(cancel, 'constitutive work cancelled')
            owned_count += owned

        # CPython's general-key table bounds also cover its smaller string-key
        # layout: at most two tables during growth, plus every index integer.
        # Small headers, row views, cross temporaries, masks and the <=2120-bit
        # scalar replay are covered by the fixed work allowance, not by E*P.
        slots = 1 << max(3, (((3*count+1)//2)-1).bit_length())
        width = 1 if slots <= 128 else 2 if slots <= 32768 else 4 if slots <= 2**31 else 8
        pointer = np.dtype(np.intp).itemsize
        mapping = 2*(dict.__basicsize__+64+slots*width+3*pointer*(2*slots//3))
        mapping += count*sys.getsizeof(count)
        work = 32*owned_count+35*count+mapping+65536
        with owner.reserve(work, category='p9-torque-reduction'):
            order = {}
            for row, plate in enumerate(plate_ids):
                if row % 1024 == 0:
                    check_event_or_callable(cancel, 'constitutive work cancelled')
                order[plate] = row
            packet = np.empty((owned_count, 3), dtype=np.float64)
            successor = np.full(2*owned_count, -1, dtype=np.int32)
            ends = np.full((count, 2), -1, dtype=np.int32)
            exceptional = np.zeros((count, 3), dtype=bool)
            out = np.zeros((count, 3))

            def legacy(first, current):
                # Prefix products are already captured. Replay them, use the live
                # first nonpacket row, then evaluate the untouched suffix once.
                ordinal = 0
                for edge, owned in enumerate(self.owned):
                    if edge % 1024 == 0:
                        check_event_or_callable(cancel, 'constitutive work cancelled')
                    if not owned:
                        continue
                    if edge < first:
                        value = packet[ordinal]
                    elif edge == first:
                        value = current
                    else:
                        value = radius_m*self.edge_length_m[edge]*np.cross(
                            midpoints[edge], self.traction_left_n_m[edge])
                    out[order[plates[edge][0]]] += value
                    out[order[plates[edge][1]]] -= value
                    ordinal += 1
                check_event_or_callable(cancel, 'constitutive work cancelled')
                return out

            ordinal = 0
            has_exceptional = False
            for edge, owned in enumerate(self.owned):
                if edge % 1024 == 0:
                    check_event_or_callable(cancel, 'constitutive work cancelled')
                if not owned:
                    continue
                tau = radius_m*self.edge_length_m[edge]*np.cross(
                    midpoints[edge], self.traction_left_n_m[edge])
                if (type(tau) is not np.ndarray or tau.shape != (3,)
                        or tau.dtype != np.dtype(np.float64) or not tau.dtype.isnative):
                    return legacy(edge, tau)
                left, right = order[plates[edge][0]], order[plates[edge][1]]
                packet[ordinal] = tau
                nonfinite = ~np.isfinite(tau)
                if np.any(nonfinite):
                    exceptional[left] |= nonfinite
                    exceptional[right] |= nonfinite
                    has_exceptional = True
                for row, occurrence in ((left, 2*ordinal), (right, 2*ordinal+1)):
                    tail = int(ends[row, 1])
                    if tail < 0:
                        ends[row, 0] = occurrence
                    else:
                        successor[tail] = occurrence
                    ends[row, 1] = occurrence
                ordinal += 1

            def values(row, axis):
                occurrence = int(ends[row, 0])
                visits = 0
                while occurrence >= 0:
                    if visits % 1024 == 0:
                        check_event_or_callable(cancel, 'constitutive work cancelled')
                    value = float(packet[occurrence//2, axis])
                    yield -value if occurrence % 2 else value
                    occurrence = int(successor[occurrence])
                    visits += 1

            for row in range(count):
                if row % 1024 == 0:
                    check_event_or_callable(cancel, 'constitutive work cancelled')
                for axis in range(3):
                    if exceptional[row, axis]:
                        continue
                    try:
                        out[row, axis] = _replay_fsum(lambda: values(row, axis))
                    except OverflowError:
                        # Only a true final projection overflow remains after the
                        # shared finite-word prefix replay. Preserve the original
                        # NumPy disposition for this lane, not a new port refusal.
                        exceptional[row, axis] = True
                        has_exceptional = True
            if has_exceptional:
                ordinal = 0
                for edge, owned in enumerate(self.owned):
                    if edge % 1024 == 0:
                        check_event_or_callable(cancel, 'constitutive work cancelled')
                    if not owned:
                        continue
                    left, right = order[plates[edge][0]], order[plates[edge][1]]
                    tau = packet[ordinal]
                    np.add(out[left], tau, out=out[left], where=exceptional[left])
                    np.subtract(out[right], tau, out=out[right], where=exceptional[right])
                    ordinal += 1
            check_event_or_callable(cancel, 'constitutive work cancelled')
            return out


def _boundary_reaction(header, support, owned, velocity, traction, length):
    arrays = []
    for name, value, shape in (('velocity_jump_m_s', velocity, (support.edges, 3)),
                               ('traction_left_n_m', traction, (support.edges, 3)),
                               ('edge_length_m', length, (support.edges,))):
        value = np.asarray(value)
        arrays.append((name, _frozen(value, float)))
    record = dict(schema=REACTION, header=header.record(), units=REACTION_UNITS, owned=list(owned))
    return _state._issue(BoundaryReaction, header=header, owned=owned, velocity_jump_m_s=arrays[0][1],
                         traction_left_n_m=arrays[1][1], edge_length_m=arrays[2][1], port_id=S._identity(_json(record), arrays))
