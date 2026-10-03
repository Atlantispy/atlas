"""I03.2 moving the spherical network over one accepted interval and transferring its material. WORKING NON-CANON.

``advance`` takes an accepted network state (integration_sphere) and one prescribed Motion for the interval of whole
global steps it declares: one finite stage rotation per plate, a declared supply for every opening ridge side and a
declared destination for every consuming trench. It returns the successor state with the transfer record that
produced it. Mode prescribed_history_v1 only: nothing here chooses a rotation, a boundary or an event.

Geometry. Every sampling face rides rigidly with its plate. A shared boundary moves by its own declared rule
(atlas.boundary-migration.v1) with constant angular velocities over the interval: a ridge by the rotation whose
rotation vector is (1-f) r_L + f r_R, a trench with its overriding plate; a boundary whose two plates share one
rotation is locked for the interval. At an opening ridge each plate keeps its own copy of the old ridge vertices and
the strip between that old edge and the new ridge becomes new faces, born in this interval and never merged into
older ones, so birth times follow trajectories. At a trench the subducting plate's boundary faces end at the trench:
the part of each that has passed it is consumed. A junction must be moved to one point by every record that ends
there. Otherwise it would migrate along its boundaries, which this version does not implement, or would have to
reorganise, which needs an admitted law; either way the step is refused. A sliding
transform and a negative half-rate or consumption are refused too. Where a plate's own position of a boundary vertex
coincides with the boundary's within the existing 64-epsilon attachment band, that corner neither opens nor is
consumed. The successor is validated again as a closed atlas: no gap is patched and nothing is snapped, welded or
renormalised.

Transfers. Overlap rows relate parent faces, moved rigidly with their plates, to endpoint faces. A face that only
rode with its plate maps to itself and is never touched: its pieces keep their exact bytes. Rows are measured by
exact polygon intersection of minor-arc faces in one conditioned gnomonic chart and summed on the sphere, and each
donor's rows must close on its measured area within the existing relative tolerance. No row is discarded, however
small. Extensive accounts move by overlap fractions of the donor's own summed rows: every row but the largest
receives the correctly rounded binary64 value of its exact share and the largest the exact remainder, so a donor is
debited once and completely and every exact account stays a bounded binary fraction. Cohorts move intact with their
formation intervals and history references, and nothing is averaged. New area comes only from a ridge record's own
area account; its material comes from the declared source. Each changed stored value is rounded once into binary64
and the difference is kept in the exact rounding account, as the I02 exchange does. A source or destination
that is a finite W08 stock of the I02 exchange is debited or credited through one I02 Transfer per supply or
destination, committed in the same transaction; exhaustion is refused there.

A mesh change (Motion.mesh) replaces the sampling faces after the motion by the same kind of overlap rows; it cannot
move a physical interface and never resets an age. ``proposed`` and ``restored`` are the two calls the ledger makes:
one computes a commit's step, the other rebuilds a stored step, recomputing the moved geometry and applying the
recorded rows to the parent's stored material again; every identity must reproduce.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import math

import numpy as np
import shapely
from shapely.errors import GEOSException
from shapely.geometry import Polygon

from . import integration_sphere as _sphere
from . import integration_state as _state
from . import integration_junction_paths as _paths
from .integration_junction_paths import JunctionPath
from ._validation import TectonicsError, input_shape, read_array, scalar
from .geometry import _check_cancel, _limits
from .integration_ledger import EXACT_LIMIT, ExchangeRefused, LedgerError, Transfer, _exact_text
from .integration_sphere import (ATTACHMENT_BAND_RAD, RELATIVE_TOLERANCE, RIDGE, SIDES, TRANSFORM, TRENCH, Boundary,
                                 Cohort, Face, Lineage,
                                 Plate)
from .kinematics import Rotation, _restore_rotation
from .materials import _json, _name, _sha
from .resources import select_budget
from .spherical_atlas import _capture_directions
from .spherical_geometry import SphericalChart, _ring_area


SCHEMA = 'atlas.i03-sphere-step.v3'
MAP_SCHEMA = 'atlas.i03-overlap-map.v3'
MOTION_SCHEMA = 'atlas.i03-sphere-motion.v1'
PRODUCER = 'atlas.i03.sphere-transfer.v1'
MODE = 'prescribed_history_v1'
# Existing junction-closure tolerance (cases/i01_transitions_v1.json, control_policy.algebra_relative).
ALGEBRA_RELATIVE = _paths.ALGEBRA_RELATIVE
LOCKED = 'locked'
ROW_ARRAYS = ('donor', 'receiver', 'party', 'area_m2')
MAX_ROWS = 1 << 20


# Refusal codes of the transport port (docs/I03_SPHERICAL_NETWORK.md, "Transport port").
UNRESOLVED_OVERLAP = 'unresolved overlap'
INCOMPATIBLE_SUPPORT = 'incompatible support'
STALE_GEOMETRY = 'stale geometry identity'
TRANSFORM_NOT_SLIP_PARALLEL = 'transform not slip-parallel'           # I03a-2 C6, approved 3 October 2026


class TransferRefused(ExchangeRefused):
    """A motion, supply, destination or mesh the network refuses; nothing was published.

    ``code`` is the transport port's refusal code when the refusal is one of its three, otherwise None.
    """

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def _canonical(value, label):
    try:
        data = _json(value)
    except TectonicsError as exc:
        raise TransferRefused(label+': finite JSON data required') from exc
    if len(data) > _sphere.MAX_RECORD:
        raise TransferRefused(label+': record exceeds the bounded envelope')
    return data


# ----------------------------------------------------------------------------- the declared proposal

def _per_phase(value, label):
    pairs = list(value.items()) if isinstance(value, Mapping) else value
    if type(pairs) not in (tuple, list):
        raise LedgerError(label+': one (phase, value) pair per phase is required')
    out = []
    for pair in pairs:
        if type(pair) not in (tuple, list) or len(pair) != 2:
            raise LedgerError(label+': (phase, value) pairs are required')
        out.append((_name(pair[0], 'phase'), scalar(pair[1], label, nonnegative=True)))
    out.sort()
    if len({phase for phase, _ in out}) != len(out):
        raise LedgerError(label+': each phase once')
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Supply:
    """The declared supply of one side of one ridge over one interval.

    ``source`` names where the new material comes from: a declared exterior source of the network or, with
    ``stock=True``, a finite W08 stock node of the I02 exchange. Each unit of born area receives the declared
    reference mass and phase thickness per phase and, when the network carries enthalpy, the declared signed
    enthalpy in its basis. The new cohort takes ``material_id``, ``origin_id`` and ``history_id``; its formation
    interval is the accepted interval itself. Nothing here is a rate or melting law: the values are supplied.
    """
    boundary_id: str
    side: str
    source: str
    material_id: str
    origin_id: str
    mass_per_area_kg_m2: object = ()
    thickness_m: object = ()
    enthalpy_per_area_j_m2: float | None = None
    history_id: str | None = None
    stock: bool = False

    def __post_init__(self):
        for label in ('boundary_id', 'source', 'material_id', 'origin_id'):
            _name(getattr(self, label), 'supply '+label.replace('_', ' '))
        if self.side not in SIDES:
            raise LedgerError('a supply names the left or right side of its ridge')
        if self.history_id is not None:
            _name(self.history_id, 'supply history reference')
        if type(self.stock) is not bool:
            raise LedgerError('stock is a bool')
        object.__setattr__(self, 'mass_per_area_kg_m2', _per_phase(self.mass_per_area_kg_m2,
                                                                   'reference mass per area'))
        object.__setattr__(self, 'thickness_m', _per_phase(self.thickness_m, 'phase thickness'))
        if self.enthalpy_per_area_j_m2 is not None:
            object.__setattr__(self, 'enthalpy_per_area_j_m2', scalar(self.enthalpy_per_area_j_m2,
                                                                      'enthalpy per area'))

    def record(self):
        return dict(boundary_id=self.boundary_id, side=self.side, source=self.source, stock=self.stock,
                    material_id=self.material_id, origin_id=self.origin_id, history_id=self.history_id,
                    mass_per_area_kg_m2=[list(pair) for pair in self.mass_per_area_kg_m2],
                    thickness_m=[list(pair) for pair in self.thickness_m],
                    enthalpy_per_area_j_m2=self.enthalpy_per_area_j_m2)


@dataclass(frozen=True, slots=True)
class Sink:
    """The declared destinations of what one trench consumes over one interval.

    ``destinations`` are (name, fraction) or (name, fraction, stock) entries: a declared exterior sink of the
    network or, with stock True, a finite W08 stock node of the I02 exchange. Fractions are exact binary fractions
    that sum to one; the partition is supplied, not inferred. The consumed area itself leaves through the trench
    record's own area account.
    """
    boundary_id: str
    destinations: tuple

    def __post_init__(self):
        _name(self.boundary_id, 'sink boundary')
        if type(self.destinations) not in (tuple, list) or not self.destinations:
            raise LedgerError('a sink names at least one destination')
        out = []
        for entry in self.destinations:
            if type(entry) not in (tuple, list) or len(entry) not in (2, 3):
                raise LedgerError('a destination is (name, fraction) or (name, fraction, stock)')
            name, fraction = _name(entry[0], 'destination'), scalar(entry[1], 'destination fraction', positive=True)
            stock = entry[2] if len(entry) == 3 else False
            if type(stock) is not bool:
                raise LedgerError('stock is a bool')
            out.append((name, fraction, stock))
        if len({(name, stock) for name, _, stock in out}) != len(out):
            raise LedgerError('each destination once')
        if sum((Fraction(fraction) for _, fraction, _ in out), Fraction(0)) != 1:
            raise LedgerError('destination fractions must sum to exactly one')
        object.__setattr__(self, 'destinations', tuple(sorted(out)))

    def record(self):
        return dict(boundary_id=self.boundary_id, destinations=[list(entry) for entry in self.destinations])


@dataclass(frozen=True, slots=True)
class Mesh:
    """A replacement sampling mesh for the endpoint: its complete face set and any added seam vertices.

    Faces name vertices of the moved network or of ``vertices`` (ID -> direction). A mesh change regroups the
    numerical cells of each plate; it cannot move, subdivide or remove a boundary record's chain.
    """
    faces: tuple
    vertices: object = ()
    mesh_id: str = field(init=False)

    def __post_init__(self):
        if type(self.faces) not in (tuple, list) or not self.faces or any(type(f) is not Face for f in self.faces):
            raise LedgerError('a mesh is a nonempty sequence of Face records')
        if isinstance(self.vertices, Mapping):
            pairs = list(self.vertices.items())
        elif type(self.vertices) in (tuple, list):
            pairs = list(self.vertices)
        else:
            raise LedgerError('added mesh vertices are a mapping or a sequence of (ID, direction) pairs')
        added = []
        for pair in pairs:
            if type(pair) not in (tuple, list) or len(pair) != 2:
                raise LedgerError('added mesh vertices are (ID, direction) pairs')
            name = _name(pair[0], 'vertex ID')
            if input_shape(pair[1], 'mesh vertex direction') != (3,):
                raise LedgerError('one direction of three components per added vertex is required')
            # Captured as a network captures its registry, so a direction names the same vertex however it is
            # scaled; a Face's rings are already canonical. The identity then describes the mesh, not its spelling.
            direction = _capture_directions(read_array(pair[1], 'mesh vertex direction').reshape(1, 3))[0]
            if not np.all(np.isfinite(direction)):
                raise LedgerError('an added mesh vertex needs a direction')
            added.append((name, tuple(float(x) for x in direction)))
        added.sort()
        if len({name for name, _ in added}) != len(added):
            raise LedgerError('each added vertex once')
        object.__setattr__(self, 'faces', tuple(sorted(self.faces, key=lambda face: face.face_id)))
        object.__setattr__(self, 'vertices', tuple(added))
        record = dict(faces=[_sphere._face_record(face) for face in self.faces],
                      vertices=[[name, list(value)] for name, value in self.vertices])
        object.__setattr__(self, 'mesh_id', hashlib.sha256(_json(record)).hexdigest())


@dataclass(frozen=True, slots=True)
class _StoredMesh:
    """The identity of a mesh whose result is a stored endpoint network: only restoration uses it."""
    mesh_id: str


@dataclass(frozen=True, slots=True)
class Motion:
    """One prescribed motion of the whole network over the interval (start_step, end_step] of the global schedule.

    ``rotations`` gives every plate its finite stage rotation over the interval, in the sphere's axes (a mapping or
    (plate, Rotation) pairs); a plate that does not move is given the identity explicitly, because absent motion is
    unknown, never zero. ``supplies`` and ``sinks`` declare the source of every opening ridge side and the
    destination of every consuming trench. ``mesh`` optionally replaces the sampling faces after the motion.
    ``events`` holds the supplied topology events committed at the end of the interval, after the motion and any mesh
    change (I03.4, integration_events). ``regional_returns`` holds regional returns (integration_bridges.carried), applied at
    the end of the interval after any mesh change and before the events. The proposal is committed only by the commit
    spanning exactly its interval, on the accepted state at ``start_step``.
    """
    start_step: int
    end_step: int
    rotations: object
    supplies: tuple = ()
    sinks: tuple = ()
    mesh: Mesh | None = None
    events: tuple = ()
    regional_returns: tuple = ()
    junction_paths: tuple = ()
    motion_id: str = field(init=False)

    def __post_init__(self):
        steps = (self.start_step, self.end_step)
        if (any(type(step) is not int for step in steps)
                or not 0 <= self.start_step < self.end_step <= _sphere.MAX_STEPS):
            raise LedgerError('a motion declares its interval as whole global steps start_step < end_step')
        pairs = list(self.rotations.items()) if isinstance(self.rotations, Mapping) else self.rotations
        if type(pairs) not in (tuple, list) or not pairs:
            raise LedgerError('a motion gives every plate its stage rotation')
        turned = []
        for pair in pairs:
            if type(pair) not in (tuple, list) or len(pair) != 2 or type(pair[1]) is not Rotation:
                raise LedgerError('stage rotations are (plate, Rotation) pairs')
            turned.append((_name(pair[0], 'plate ID'), pair[1]))
        turned.sort(key=lambda pair: pair[0])
        if len({plate for plate, _ in turned}) != len(turned):
            raise LedgerError('each plate once')
        for values, kind, label in ((self.supplies, Supply, 'Supply'), (self.sinks, Sink, 'Sink')):
            if type(values) not in (tuple, list) or any(type(v) is not kind for v in values):
                raise LedgerError('a sequence of %s records is required' % label)
        supplies = tuple(sorted(self.supplies, key=lambda s: (s.boundary_id, s.side)))
        sinks = tuple(sorted(self.sinks, key=lambda s: s.boundary_id))
        if (len({(s.boundary_id, s.side) for s in supplies}) != len(supplies)
                or len({s.boundary_id for s in sinks}) != len(sinks)):
            raise LedgerError('one supply per ridge side and one sink per trench')
        if self.mesh is not None and type(self.mesh) not in (Mesh, _StoredMesh):
            raise LedgerError('a typed Mesh is required')
        if self.events:
            from . import integration_events as _events
            try:
                object.__setattr__(self, 'events', _events.checked(self.events))
            except _events.EventRefused as exc:
                raise LedgerError(str(exc)) from exc
        elif type(self.events) not in (tuple, list):
            raise LedgerError('events are a sequence of event proposals')
        else:
            object.__setattr__(self, 'events', ())
        if type(self.regional_returns) not in (tuple, list):
            raise LedgerError('regional returns are a sequence of carried returns')
        if self.regional_returns:
            from . import integration_bridges as _bridges
            if any(type(item) is not _bridges.RegionalReturn for item in self.regional_returns):
                raise LedgerError('regional returns are carried returns (integration_bridges.carried)')
            regions = [item.footprint.region_id for item in self.regional_returns]
            if len(set(regions)) != len(regions):
                raise LedgerError('each region is returned once in an interval')
            object.__setattr__(self, 'regional_returns',
                               tuple(sorted(self.regional_returns, key=lambda item: item.footprint.region_id)))
        else:
            object.__setattr__(self, 'regional_returns', ())
        object.__setattr__(self, 'rotations', tuple(turned))
        object.__setattr__(self, 'supplies', supplies)
        object.__setattr__(self, 'sinks', sinks)
        if type(self.junction_paths) not in (tuple, list) or any(type(p) is not JunctionPath for p in self.junction_paths):
            raise LedgerError('junction paths are typed JunctionPath records')
        paths = tuple(sorted(self.junction_paths, key=lambda p: p.junction_id))
        if len({p.junction_id for p in paths}) != len(paths) or len({p.reference_plate_id for p in paths}) > 1:
            raise LedgerError('junction paths are unique and share one common reference plate')
        object.__setattr__(self, 'junction_paths', paths)
        object.__setattr__(self, 'motion_id', hashlib.sha256(_json(self._declared())).hexdigest())

    def _declared(self):
        declared = dict(schema=MOTION_SCHEMA, mode=MODE, start_step=self.start_step, end_step=self.end_step,
                        rotations=[[plate, list(rotation.quaternion)] for plate, rotation in self.rotations],
                        supplies=[supply.record() for supply in self.supplies],
                        sinks=[sink.record() for sink in self.sinks],
                        mesh_id=None if self.mesh is None else self.mesh.mesh_id)
        if self.events:                    # recorded only when present, so a motion without events keeps its identity
            declared['events'] = [event.record() for event in self.events]
        if self.regional_returns:          # likewise
            declared['regional_returns'] = [item.record() for item in self.regional_returns]
        if self.junction_paths:
            declared['path_interpolation'] = _paths.CONVENTION
            declared['junction_paths'] = [path.record() for path in self.junction_paths]
        return declared

    def record(self):
        """The declared motion as stored with a commit; a mesh is named by its identity only."""
        return dict(self._declared(), motion_id=self.motion_id)


def _motion(record):
    """A Motion rebuilt from its stored record; a mesh is represented by its identity alone."""
    try:
        if record['schema'] != MOTION_SCHEMA or record['mode'] != MODE:
            raise LedgerError('the stored motion is not of this schema')
        supplies = tuple(Supply(boundary_id=row['boundary_id'], side=row['side'], source=row['source'],
                                material_id=row['material_id'], origin_id=row['origin_id'],
                                mass_per_area_kg_m2=tuple(tuple(pair) for pair in row['mass_per_area_kg_m2']),
                                thickness_m=tuple(tuple(pair) for pair in row['thickness_m']),
                                enthalpy_per_area_j_m2=row['enthalpy_per_area_j_m2'], history_id=row['history_id'],
                                stock=row['stock']) for row in record['supplies'])
        sinks = tuple(Sink(row['boundary_id'], tuple(tuple(entry) for entry in row['destinations']))
                      for row in record['sinks'])
        mesh = None if record['mesh_id'] is None else _StoredMesh(_sha(record['mesh_id'], 'mesh identity'))
        events, returns = (), ()
        if 'events' in record:
            from . import integration_events as _events
            events = tuple(_events.from_record(row) for row in record['events'])
        if 'regional_returns' in record:
            from . import integration_bridges as _bridges
            returns = tuple(_bridges.RegionalReturn.from_record(row) for row in record['regional_returns'])
        motion = Motion(record['start_step'], record['end_step'],
                        tuple((plate, _restore_rotation(tuple(q))) for plate, q in record['rotations']), supplies,
                        sinks, mesh, events, returns,
                        tuple(JunctionPath.from_record(row) for row in record.get('junction_paths', ())))
    except (KeyError, TypeError, ValueError, TectonicsError) as exc:
        raise LedgerError('the stored motion record is incomplete') from exc
    if _json(motion.record()) != _json(dict(record)):
        raise LedgerError('the stored motion does not reproduce its record and identity')
    return motion


# ----------------------------------------------------------------------------- rotations

IDENTITY = _restore_rotation((1., 0., 0., 0.))


def _signed(rotation):
    """The stored unit quaternion with its first nonzero component positive: q and -q are one rotation."""
    q = rotation.quaternion
    for value in q:
        if value > 0:
            return q
        if value < 0:
            return tuple(-x for x in q)
    return q


def _vector(rotation):
    """The rotation vector (axis times angle, radians) through the shorter angle."""
    w, x, y, z = rotation.quaternion
    if w < 0:
        w, x, y, z = -w, -x, -y, -z
    norm = math.hypot(x, y, z)
    if norm == 0:
        return (0., 0., 0.)
    scale = 2*math.atan2(norm, w)/norm
    return (x*scale, y*scale, z*scale)


def _blend(left, right, fraction):
    """The ridge rotation of atlas.boundary-migration.v1 over one interval (I03a-2 M1, approved 3 October 2026).

    A point of the ridge moves with velocity (1-f) v_L + f v_R. Relative to its left plate the ridge then moves at
    the fraction f of the right plate's relative velocity; with that relative angular velocity constant over the
    interval, the ridge's finite rotation is C = R_L exp(f log(R_L^-1 R_R)). C is exactly covariant: a common
    rotation Q applied to both plates gives Q C. It differs from I03a's rotation vector (1-f) r_L + f r_R only at
    third order, by f(1-f)/12 (r_L - r_R) x (r_L x r_R), and not at all when the two plates turn about one axis.
    """
    relative = right.then(left.inverse())                         # R_L^-1 R_R
    vector = _vector(relative)
    angle = math.hypot(*vector)
    if angle == 0:
        return left
    return Rotation.from_axis_angle(tuple(x/angle for x in vector), fraction*angle).then(left)


def _turned(rotation, points):
    """``points`` rotated, one elementwise product and sum per component: the same bits for one or many rows."""
    return _sphere._placed(rotation, points)


def _angle(a, b):
    """Angle between two directions, stable for small and near-antipodal separations."""
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return 2*np.arctan2(np.linalg.norm(a-b, axis=-1), np.linalg.norm(a+b, axis=-1))


def _turns_left(points):
    """True when a ring of three or four directions is a convex polygon with its interior on the left.

    Each corner's orientation is the sign of a . ((b - a) x (c - a)), which equals a . (b x c) but is formed from
    differences of the ring's own corners, so it stays reliable for a ring far smaller than the sphere.
    """
    count = len(points)
    for k in range(count):
        a, b, c = points[k], points[(k+1) % count], points[(k+2) % count]
        if not float(np.dot(a, np.cross(b-a, c-a))) > 0:
            return False
    return True


def _without_repeats(ids):
    """A ring of vertex IDs without consecutive (cyclic) repeats."""
    out = []
    for name in ids:
        if not out or out[-1] != name:
            out.append(name)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return tuple(out)


# ----------------------------------------------------------------------------- moved geometry

@dataclass(frozen=True, slots=True)
class _Moved:
    """The endpoint declaration of one motion and what the transfer rows need from the way it was built."""
    layout: object           # the endpoint's vertex layout (integration_sphere._Layout)
    faces: tuple
    plates: tuple
    boundaries: tuple
    lineage: Lineage
    status: tuple            # (boundary_id, status, quaternion) per record
    junctions: tuple         # (junction_id, spread_rad, relative_motion_rad, closure_residual)
    attachment_rad: float
    strips: tuple            # (face_id, boundary_id, side) of every face born in the interval
    deformed: tuple          # (face_id, plate_id) of every face that ends at a moved trench or slides along a transform
    slid: tuple              # the face IDs among them that only slide along a transform (nothing consumed)
    reshaped: tuple          # the face IDs among them of a line's carrier that only gain a sliding junction
    swept: tuple             # (boundary_id, plate_id, ring in that plate's reference frame) per consumed segment
    transient: tuple = ()    # (junction, ridge, side, trench, plate, ring): material born and consumed in this interval


def _moved(network, motion, cancel, limits=None, budget=None):
    """Move every vertex by its rule and declare the endpoint faces and vertex layout; no measure is taken here.

    Every decision is taken over this interval alone, from the start positions in the sphere's axes. Its result is
    kept in reference frames (integration_sphere._Layout). Each ridge record's frame is composed with the ridge's own
    rotation, so a ridge vertex keeps its reference direction and is placed once from it. A vertex kept by a plate is
    re-placed in that plate's frame only when it moves relative to the plate, and a plate's copy of a vertex kept
    elsewhere only when it would lie more than the band from the vertex's own placement (C10, form a, approved 3
    October 2026); it is then re-placed there. A vertex that rides keeps its exact numbers, however many intervals pass.
    """
    stage = dict(motion.rotations)
    if set(stage) != set(network.plate_ids):
        raise TransferRefused('a motion gives exactly the plates of the network their stage rotations: absent motion '
                              'is unknown, never zero')
    layout = network._layout
    path_rotations, path_targets, path_traces, path_poles, path_residuals = {}, {}, {}, {}, {}
    if motion.junction_paths:
        limits = _limits(limits)
        ends = {j.junction_id: len(j.boundary_ends) for j in network.junctions}
        maximum = sum((p.max_segments+1)*ends.get(p.junction_id, 0) for p in motion.junction_paths)
        if maximum+len(network.vertex_ids) > limits.max_vertices:
            raise TransferRefused('the declared junction sample ceilings exceed the geometry vertex limit')
        path_rotations, path_targets, path_traces, path_poles, path_residuals = _paths.prepare(
            network, motion, cancel, TransferRefused)
    names, points = network.vertex_ids, network.vertex_direction
    lookup = {name: i for i, name in enumerate(names)}
    order = {plate: i for i, plate in enumerate(network.plate_ids)}
    home = dict(zip(names, layout.home))
    frames = tuple((plate, rotation.then(stage[plate])) for plate, rotation in layout.frames)
    back = {plate: rotation.inverse() for plate, rotation in frames}
    # A plate's image of a vertex is its own corner, its own copy moved with it: so motion inside the band cannot
    # accumulate unseen between a plate's copy and the vertex, however many intervals it lasts.
    frame_of = dict(layout.frames)
    carried = {plate: _turned(stage[plate], _sphere._placed(frame_of[plate], network._local[order[plate]]))
               for plate in stage}
    status, rule = [], {}
    for boundary in network.boundaries:
        left, right = stage[boundary.left_plate_id], stage[boundary.right_plate_id]
        if _signed(left) == _signed(right):
            kind, rotation = LOCKED, left
        elif boundary.kind == RIDGE:
            fraction = boundary.accretion_fraction
            # The endpoint fractions carry the ridge exactly with that plate, including its floating-point frame.
            kind, rotation = RIDGE, left if fraction == 0. else right if fraction == 1. else _blend(left, right, fraction)
        elif boundary.kind == TRENCH:
            kind, rotation = TRENCH, right if boundary.subducting_side == 'left' else left
        elif boundary.carrier_side is not None:
            kind, rotation = TRANSFORM, right if boundary.carrier_side == 'right' else left
        else:
            raise TransferRefused('transform %r: its two plates move differently and it declares no carrier_side; '
                                  'sliding along a transform is not supported in this version without a declared '
                                  'carrier_side, the plate that carries its trace; it is admitted only with one '
                                  'shared rotation' % boundary.boundary_id)
        if path_rotations:
            rotation = path_rotations[boundary.boundary_id]
        rule[boundary.boundary_id] = (kind, rotation)
        status.append((boundary.boundary_id, kind, tuple(rotation.quaternion)))
    _slip_parallel(network, rule, dict(frames), lookup)
    ridges = tuple((boundary_id, rotation.then(rule[boundary_id][1])) for boundary_id, rotation in layout.ridges)
    ridge_frame = {(RIDGE, boundary_id): rotation for boundary_id, rotation in ridges}
    uses = {}
    for boundary in network.boundaries:
        for name in boundary.vertex_ids:
            uses.setdefault(name, []).append(boundary)
    around = {name: set() for name in uses}
    for face in network.faces:
        for ring in (face.vertex_ids, *face.holes):
            for name in ring:
                if name in around:
                    around[name].add(face.plate_id)
    at_junction = {junction.vertex_id: junction for junction in network.junctions}
    frames_old = dict(layout.frames, **{}) | {(RIDGE, b): r for b, r in layout.ridges}
    frames_new = dict(frames) | ridge_frame
    seam_targets = _trench_material_seams(network, rule, carried, lookup, uses, cancel)
    target, attached = {}, set()
    copies, corner, junctions, worst, pulled, sunk = {}, {}, [], 0., set(), set()
    advance, slides, placed_at, shared = {}, {}, {}, {}
    transient, trench_corners = [], []
    carrier_reshapes = set()

    def placement(name, index):
        """Where the vertex's home places it at the end of the interval (its home's decision is already taken)."""
        keeper = home[name]
        if name in path_targets:
            return target[name]
        if keeper in ridge_frame:
            return _sphere._placed(ridge_frame[keeper], layout.reference[index])[0]
        local = (network._local[order[keeper]][index] if (name, keeper) in attached
                 else _turned(back[keeper], target[name])[0])
        return _sphere._placed(frames_new[keeper], local)[0]
    used = set(names)
    for name in sorted(uses):
        _check_cancel(cancel)
        index = lookup[name]
        records = sorted(uses[name], key=lambda boundary: boundary.boundary_id)
        proposals = [_turned(rule[boundary.boundary_id][1], points[index])[0] for boundary in records]
        # Decisions and every plate's copy use the moved start position; a ridge record's own vertex is then placed
        # by its record's frame from its unchanged reference direction (integration_sphere._directions).
        target[name] = seam_targets[name][0] if name in seam_targets else proposals[0]
        spread = max((float(_angle(p, target[name])) for p in proposals[1:]), default=0.)
        owners = sorted(around[name])
        own = {plate: carried[plate][index] for plate in owners}
        scale = max((float(_angle(own[a], own[b])) for i, a in enumerate(owners) for b in owners[i+1:]), default=0.)
        residual = spread/scale if scale > ATTACHMENT_BAND_RAD else 0.
        if name in path_targets:
            target[name], residual = path_targets[name], path_residuals[name]
        elif spread > ATTACHMENT_BAND_RAD or residual > ALGEBRA_RELATIVE:
            if name not in at_junction:
                raise TransferRefused('the boundary records that use vertex %r move it to different points (%.3e rad '
                                      'apart); refused' % (name, spread))
            # The junction advances along its lines (Part 2); the plate that carries the through line goes first.
            target[name], residual, carrier, members, crossed = _advanced_junction(
                network, at_junction[name], points[index], rule, stage, frames_old, frames_new, points, lookup,
                seam_targets)
            advance[name] = (carrier, members, crossed)
            owners = sorted(owners, key=lambda plate: plate != carrier)
        if name in at_junction:
            junctions.append((at_junction[name].junction_id, spread, scale, residual))
        # The line's carrier decides first, then the vertex's home; every other plate's copy is then measured against
        # the vertex's own placement, exactly as integration_sphere._copies_placed measures it on issue and restore.
        first = advance[name][0] if name in advance else home[name]
        owners = sorted(owners, key=lambda plate: (plate != first, plate != home[name]))
        for plate in owners:
            mine = [boundary for boundary in records if plate in (boundary.left_plate_id, boundary.right_plate_id)]
            if plate == home[name] or plate == first:
                away = float(_angle(own[plate], target[name]))
            else:
                if name not in placed_at:
                    placed_at[name] = placement(name, index)
                mine_now = _sphere._placed(frames_new[plate], network._local[order[plate]][index])[0]
                away = float(np.linalg.norm(mine_now-placed_at[name]))
            if name in seam_targets and plate == seam_targets[name][1]:
                # Only a subdivision of this carrier's same straight edge moves. Its polygon and material do not.
                continue
            if name in advance and plate == advance[name][0]:
                # The plate that carries the through line: its faces ride, and it keeps its old corner where it
                # was, a vertex of the record behind; the junction slides along its edge to the new point.
                if away <= ATTACHMENT_BAND_RAD:
                    worst = max(worst, away)
                    attached.add((name, plate))
                    continue
                carrier_faces = [face for face in network.faces if face.plate_id == plate
                                 and any(name in ring for ring in (face.vertex_ids, *face.holes))]
                if (len(carrier_faces) == 1 and not advance[name][2]
                        and all(rule[boundary_id][0] == TRENCH for boundary_id, _ in advance[name][1])):
                    # Inside one carrier face this is only a subdivision of its straight through edge. Moving
                    # it creates no material seam; preserving a second old copy could reverse their order when
                    # an adjacent material seam also slides. The same face retains its geometry and inventory.
                    # This is only the consuming through-trench case. A transform's far plate can need the old
                    # corner for an opening strip, and D1-b crossings must still transfer passed sample vertices.
                    carrier_reshapes.add(carrier_faces[0].face_id)
                    continue
                copy = '%s|%s|%d' % (name, plate, motion.end_step)
                if copy in used or len(copy) > 256:
                    raise TransferRefused('the derived vertex identity %r is already in use or too long' % copy)
                used.add(copy)
                copies[copy] = (plate, network._local[order[plate]][index])
                corner[name, plate] = copy
                slides[name] = (copy, plate)
                continue
            sinking = any(rule[b.boundary_id][0] == TRENCH and plate == (
                b.left_plate_id if b.subducting_side == 'left' else b.right_plate_id) for b in mine)
            # The far plate of a sliding transform: its corner on the trace goes with the trace, and its cells beside
            # the trace are sheared and remapped among themselves (C6 has checked that the slip is along the trace).
            sliding = any(rule[b.boundary_id][0] == TRANSFORM and plate == (
                b.left_plate_id if b.carrier_side == 'right' else b.right_plate_id) for b in mine)
            if (sliding and not sinking and away > ATTACHMENT_BAND_RAD
                    and any(rule[b.boundary_id][0] == RIDGE for b in mine)):
                # Its old corner, between its new strip and its old crust, would have to slide along the line with
                # it as a vertex of the line: option D1-c, deferred by the coordinator (3 October 2026). This holds
                # whether or not the junction advances: pulled to it, the corner would leave its opening unbooked.
                raise TransferRefused('plate %r opens a ridge at junction %r while it slides along the line there: its '
                                      'old corner would have to slide along the line as a vertex of it (option D1-c, '
                                      'deferred); refused' % (plate, name))
            if (sinking and away > ATTACHMENT_BAND_RAD
                    and any(rule[b.boundary_id][0] == RIDGE for b in mine)):
                ridges_here = [b for b in mine if rule[b.boundary_id][0] == RIDGE]
                trenches_here = [b for b in mine if rule[b.boundary_id][0] == TRENCH and plate == (
                    b.left_plate_id if b.subducting_side == 'left' else b.right_plate_id)]
                if len(ridges_here) != 1 or len(trenches_here) != 1 or name not in at_junction:
                    raise TransferRefused('D5 needs one ridge ending on one overriding trench trace per plate')
                ridge, trench = ridges_here[0], trenches_here[0]
                zero_fraction = 0. if plate == ridge.left_plate_id else 1.
                generated_end = any(vertex == name and boundary_id == ridge.boundary_id
                                    for vertex, boundary_id, _ in path_traces)
                if ridge.accretion_fraction == zero_fraction and not generated_end:
                    # This side has no ridge opening. Its old face simply ends at the advancing trench/ridge
                    # intersection; a zero-area transient triangle is neither a birth nor a separate vertex.
                    # A supplied curved end has its own finite strip and retains the geometric D5 construction.
                    pulled.add((name, plate))
                    sunk.add((name, plate))
                    continue
                ends = dict(at_junction[name].boundary_ends)
                rr, tr = ends[ridge.boundary_id], ends[trench.boundary_id]
                rn = ridge.vertex_ids[1] if rr == 'start' else ridge.vertex_ids[-2]
                tn = trench.vertex_ids[1] if tr == 'start' else trench.vertex_ids[-2]
                # D1-b is not constructed at a D5 junction: the triangle below is built on the original trench end
                # segment, and its born strip takes no retained sample. Name that limit rather than let the
                # construction refuse with a misleading geometric cause.
                crossed_here = advance[name][2] if name in advance else {}
                if tn in crossed_here.get(trench.boundary_id, ()):
                    raise TransferRefused('D1-b at a D5 transient junction is not constructed: junction %r passes '
                                          'declared vertex %r of trench %r, which ends the trench segment of the D5 '
                                          'triangle of plate %r; refused' % (name, tn, trench.boundary_id, plate))
                old, neighbour = own[plate], carried[plate][lookup[rn]]
                trench_neighbour = (seam_targets[tn][0] if tn in seam_targets else
                                    _turned(rule[trench.boundary_id][1], points[lookup[tn]])[0])
                old_pole, trench_pole = _pole(old, neighbour), _pole(target[name], trench_neighbour)
                crossing = np.cross(old_pole, trench_pole)
                sine = float(np.linalg.norm(crossing))
                if sine < SHALLOWEST_SINE:
                    raise TransferRefused('D5 old ridge and advanced trench intersect below sin 1/16; refused')
                crossing /= sine
                if float(crossing @ target[name]) < 0:
                    crossing = -crossing
                def interior(point, first, last):
                    normal = _pole(first, last)
                    return (float(_angle(point, first)) > ATTACHMENT_BAND_RAD
                            and float(_angle(point, last)) > ATTACHMENT_BAND_RAD
                            and float(np.cross(first, point) @ normal) > 0
                            and float(np.cross(point, last) @ normal) > 0)
                for record_id, passed in sorted(crossed_here.items()):
                    for vertex in passed:
                        at = (seam_targets[vertex][0] if vertex in seam_targets else
                              _turned(rule[record_id][1], points[lookup[vertex]])[0])
                        if float(_angle(at, target[name])) <= ATTACHMENT_BAND_RAD:
                            continue                     # an exact landing removes the vertex; nothing is subdivided
                        if float(_angle(at, crossing)) <= ATTACHMENT_BAND_RAD or interior(at, crossing, target[name]):
                            raise TransferRefused(
                                'D1-b at a D5 transient junction is not constructed: junction %r passes declared '
                                'vertex %r, which lies between the D5 intersection X of plate %r and the new '
                                'junction; refused' % (name, vertex, plate))
                if not interior(crossing, old, neighbour) or not interior(crossing, target[name], trench_neighbour):
                    beyond = ''
                    if (interior(crossing, old, neighbour) and tn not in at_junction
                            and interior(trench_neighbour, target[name], crossing)):
                        beyond = (': X lies beyond declared vertex %r of trench %r, and D5 needs X on the trench '
                                  'segment next to the junction' % (tn, trench.boundary_id))
                    raise TransferRefused('D5 intersection X is not inside both the old ridge end segment and the '
                                          'advanced trench end segment%s; refused' % beyond)
                side = 'left' if plate == ridge.left_plate_id else 'right'
                directed = old_pole if rr == 'start' else -old_pole
                if (1 if side == 'left' else -1)*float(directed @ target[name]) >= 0:
                    raise TransferRefused('D5 triangle is not on the opening side of the old ridge; refused')
                copy = '%s|%s|%d' % (name, plate, motion.end_step)
                if copy in used or len(copy) > 256:
                    raise TransferRefused('the derived D5 vertex identity is reserved or too long')
                used.add(copy)
                keeper = _sphere._carrier(trench)
                copies[copy] = (keeper, _turned(back[keeper], crossing)[0])
                corner[name, plate] = copy
                pulled.add((name, plate))
                sunk.add((name, plate))
                ring = _turned(back[plate], np.asarray([old, crossing, target[name]]))
                if not _turns_left(ring):
                    ring = ring[::-1].copy()
                if not _turns_left(ring):
                    raise TransferRefused('D5 triangle has no positive oriented area; refused')
                transient.append((at_junction[name].junction_id, ridge.boundary_id, side, trench.boundary_id,
                                  plate, ring))
                trench_corners.append((trench.boundary_id, tr, copy, name, tn, keeper))
                continue
            if sinking or sliding:
                if away > ATTACHMENT_BAND_RAD:
                    pulled.add((name, plate))
                    if sinking:
                        sunk.add((name, plate))
                else:
                    worst = max(worst, away)
                    attached.add((name, plate))
            elif away <= ATTACHMENT_BAND_RAD:
                worst = max(worst, away)
                attached.add((name, plate))
            elif mine and all(rule[b.boundary_id][0] in (RIDGE, LOCKED) for b in mine) and any(
                    rule[b.boundary_id][0] == RIDGE for b in mine) and name in slides and float(
                    _angle(own[plate], own[slides[name][1]])) <= ATTACHMENT_BAND_RAD:
                corner[name, plate] = slides[name][0]       # the same old corner as the line's carrier keeps
                # Its view of that corner is its own corner, unchanged: its faces that only ride keep their bits
                # in any frame (C10 bounds it against the carrier's copy).
                shared[slides[name][0], plate] = network._local[order[plate]][index]
            elif mine and all(rule[b.boundary_id][0] in (RIDGE, LOCKED) for b in mine) and any(
                    rule[b.boundary_id][0] == RIDGE for b in mine):
                copy = '%s|%s|%d' % (name, plate, motion.end_step)
                if copy in used or len(copy) > 256:
                    raise TransferRefused('the derived vertex identity %r is already in use or too long' % copy)
                used.add(copy)
                # The plate keeps its own copy of the vertex where it was, with exactly its old coordinates.
                copies[copy] = (plate, network._local[order[plate]][index])
                corner[name, plate] = copy
            else:
                raise TransferRefused('plate %r separates from vertex %r where no opening ridge of its own allows it'
                                      % (plate, name))

    # Moving material seams may not collide with a neighbouring seam, physical end or fixed carrier subdivision.
    # Check their endpoint ordering before any ring is issued; a genuine crossing needs a different topology.
    for boundary in network.boundaries:
        chain = boundary.vertex_ids
        edges = list(zip(chain, chain[1:]))+([(chain[-1], chain[0])] if boundary.closed else [])
        for a, b in edges:
            if a not in seam_targets and b not in seam_targets:
                continue
            original = _turned(rule[boundary.boundary_id][1], points[[lookup[a], lookup[b]]])
            if (float(_angle(target[a], target[b])) <= ATTACHMENT_BAND_RAD or
                    float(np.cross(target[a], target[b]) @ np.cross(original[0], original[1])) <= 0):
                raise TransferRefused('a moving trench material seam would collide with or pass its neighbour; refused')

    def coords(plate, name):
        """Where ``name`` is at the end of the interval, in ``plate``'s reference frame."""
        if name in copies:
            keeper, local = copies[name]
            if keeper == plate:
                return local
            if (name, plate) in shared:
                return shared[name, plate]
            return _turned(back[plate], _turned(frames_new[keeper], local)[0])[0]
        if name not in target or (name, plate) in attached:
            return network._local[order[plate]][lookup[name]]                      # rides or stays attached
        if name in placed_at and plate != home[name]:
            return _turned(back[plate], placed_at[name])[0]                         # re-placed at the vertex (C10)
        return _turned(back[plate], target[name])[0]

    # A generated trace is part of the shared ridge record, not an interpolation-only display. Its carrier-local
    # samples use one identity on both strip sides. The stored junction endpoint keeps its analytic tangent.
    generated = {}
    for (name, boundary_id, role), points_on_trace in sorted(path_traces.items()):
        keeper = (RIDGE, boundary_id)
        ids = []
        for k, point in enumerate(points_on_trace[:-1]):
            copy = '%s|trace|%s|%d|%d' % (name, boundary_id, motion.end_step, k)
            if copy in used or len(copy) > 256:
                raise TransferRefused('the derived generated-trace identity is reserved or too long')
            used.add(copy)
            copies[copy] = (keeper, _turned(frames_new[keeper].inverse(), point)[0])
            ids.append(copy)
        generated[name, boundary_id] = tuple(ids)+(name,)

    # D1-b: a degree-two chain vertex is sampling, not a junction. Once passed it belongs to the record behind
    # the moving junction. Its carrier keeps it fixed; the face ahead on the other side no longer uses it.
    removed, coincident = {}, set()
    record = {boundary.boundary_id: boundary for boundary in network.boundaries}
    for name, (carrier, _, crossings) in advance.items():
        for boundary_id, passed in crossings.items():
            boundary = record[boundary_id]
            other = boundary.left_plate_id if boundary.right_plate_id == carrier else boundary.right_plate_id
            removed.setdefault(other, set()).update(passed)
            for vertex in passed:
                if float(_angle(target[name], target[vertex])) <= ATTACHMENT_BAND_RAD:
                    coincident.add(vertex)
    faces, deformed, slid, reshaped = [], [], [], []
    for face in network.faces:
        rings = (face.vertex_ids, *face.holes)
        if not any(name in uses for ring in rings for name in ring):
            faces.append(face)                                          # rides with its plate: the same record
            continue
        turned = [tuple(corner.get((name, face.plate_id), name) for name in ring
                        if name not in removed.get(face.plate_id, ()) and name not in coincident) for ring in rings]
        faces.append(Face(face.face_id, face.plate_id, turned[0], tuple(turned[1:]), face.block_id))
        if (face.face_id in carrier_reshapes or any(name in seam_targets and face.plate_id == seam_targets[name][1]
                                                   for ring in rings for name in ring)):
            deformed.append((face.face_id, face.plate_id))
            reshaped.append(face.face_id)
        if any((name, face.plate_id) in pulled for ring in rings for name in ring):
            deformed.append((face.face_id, face.plate_id))
            if not any((name, face.plate_id) in sunk for ring in rings for name in ring):
                slid.append(face.face_id)
    # A sliding junction: the line's carrier keeps its old corner in the record behind, and the junction is inserted
    # into the carrier's face ahead; a face of another plate along the record behind gains the old corner as well.
    record = {boundary.boundary_id: boundary for boundary in network.boundaries}
    chains = {}
    for (name, boundary_id, role), _ in sorted(path_traces.items()):
        chain = chains.get(boundary_id, record[boundary_id].vertex_ids)
        trace = generated[name, boundary_id]
        chains[boundary_id] = trace[::-1]+chain[1:] if role == 'start' else chain[:-1]+trace
    # Both ends of a record use the same advanced subdivision. In particular, an exact landing can remove a
    # sample that used to be the other junction's neighbour before that second junction is processed.
    passed_on = {}
    for _, _, crossings in advance.values():
        for boundary_id, passed in crossings.items():
            passed_on.setdefault(boundary_id, set()).update(passed)
    for boundary_id, passed in passed_on.items():
        chains[boundary_id] = tuple(vertex for vertex in chains.get(boundary_id, record[boundary_id].vertex_ids)
                                    if vertex not in passed)
    for boundary_id, _, _, name, neighbour, _ in trench_corners:
        if neighbour in passed_on.get(boundary_id, ()):
            # The junction's own passes are refused above; this is a pass by the record's other junction.
            raise TransferRefused('D1-b at a D5 transient junction is not constructed: declared vertex %r of trench '
                                  '%r, which ends the trench segment of the D5 triangle at junction %r, is passed by '
                                  'another junction in this interval; refused' % (neighbour, boundary_id, name))
    traversed_edges = {}
    for name, (copy, carrier) in sorted(slides.items()):
        moved_to, start = target[name], carried[carrier][lookup[name]]
        ahead, behind = [], []
        for boundary_id, role in advance[name][1]:
            chain = record[boundary_id].vertex_ids
            beside = chain[1] if role == 'start' else chain[-2]
            later = _turned(rule[boundary_id][1], points[lookup[beside]])[0]
            (ahead if float((later-start) @ (moved_to-start)) > 0 else behind).append((boundary_id, role, beside))
        if len(ahead) != 1 or len(behind) != 1:
            raise TransferRefused('junction %r does not slide along one line from one record into the other; refused'
                                  % name)
        (ahead_id, ahead_role, front), (behind_id, behind_role, back_vertex) = ahead[0], behind[0]
        passed = advance[name][2].get(ahead_id, ())
        chain = chains.get(ahead_id, record[ahead_id].vertex_ids)
        front = chain[1] if ahead_role == 'start' else chain[-2]
        chain = chains.get(behind_id, record[behind_id].vertex_ids)
        back_vertex = chain[1] if behind_role == 'start' else chain[-2]
        retained = tuple(vertex for vertex in passed if vertex not in coincident)
        if retained:
            traversed_edges[copy, name] = retained
        anchor = retained[-1] if retained else copy
        front = corner.get((front, carrier), front)        # a junction ahead that also slid is the carrier's copy
        hits = [k for k, face in enumerate(faces) if face.plate_id == carrier
                and _adjacent(face.vertex_ids, anchor, front) is not None]
        if len(hits) != 1:
            raise TransferRefused('junction %r has no single face of %r to slide into; refused' % (name, carrier))
        face = faces[hits[0]]
        faces[hits[0]] = Face(face.face_id, face.plate_id, _between(face.vertex_ids, anchor, front, name), face.holes,
                              face.block_id)
        deformed.append((face.face_id, carrier))
        reshaped.append(face.face_id)
        for k, face in enumerate(faces):
            behind_here = corner.get((back_vertex, face.plate_id), back_vertex)
            if face.plate_id != carrier and _adjacent(face.vertex_ids, name, behind_here) is not None:
                faces[k] = Face(face.face_id, face.plate_id,
                                _between_many(face.vertex_ids, behind_here, name, (copy, *retained)),
                                face.holes, face.block_id)
        chain = chains.get(behind_id, record[behind_id].vertex_ids)
        extension = (copy, *retained)
        chains[behind_id] = (chain[:-1]+extension+(name,)) if behind_role == 'end' else (
            (name,)+extension[::-1]+chain[1:])
    # The surviving old material ends at X; the new ridge strip fills X--J'. The overriding face uses the same
    # trench vertex. The original swept quadrilateral already includes the transient triangle exactly once.
    for boundary_id, role, copy, name, neighbour, keeper in trench_corners:
        chain = chains.get(boundary_id, record[boundary_id].vertex_ids)
        adjacent = chain[1] if role == 'start' else chain[-2]
        # A sliding junction may have inserted the carrier's old corner first. Locate X on that updated chain.
        point = _turned(frames_new[keeper], copies[copy][1])[0]
        pairs = list(zip(chain, chain[1:]))
        found = None
        for a, b in pairs:
            pa, pb = _turned(frames_new[keeper], coords(keeper, a))[0], _turned(frames_new[keeper], coords(keeper, b))[0]
            normal = _pole(pa, pb)
            if (float(np.cross(pa, point) @ normal) > 0 and float(np.cross(point, pb) @ normal) > 0):
                found = (a, b)
                break
        if found is None:
            raise TransferRefused('D5 intersection X has no segment on its advanced trench record; refused')
        a, b = found
        at = chain.index(a)
        chains[boundary_id] = chain[:at+1]+(copy,)+chain[at+1:]
        hits = [k for k, face in enumerate(faces) if face.plate_id == keeper
                and _adjacent(face.vertex_ids, a, b) is not None]
        if len(hits) != 1:
            raise TransferRefused('D5 intersection X has no unique overriding face; refused')
        face = faces[hits[0]]
        faces[hits[0]] = Face(face.face_id, keeper, _between(face.vertex_ids, a, b, copy), face.holes, face.block_id)
        if (face.face_id, keeper) not in deformed:
            deformed.append((face.face_id, keeper))
            reshaped.append(face.face_id)
        # The carrier may retain its old sampling corner between X and the old trench neighbour. The surviving
        # subducting face must use that same subdivision; omitting it leaves an unpaired carrier seam.
        chain = chains[boundary_id]
        first, last = chain.index(copy), chain.index(neighbour)
        between = chain[first+1:last] if first < last else chain[last+1:first][::-1]
        for k, face in enumerate(faces):
            if face.plate_id != keeper and _adjacent(face.vertex_ids, copy, neighbour) is not None and between:
                faces[k] = Face(face.face_id, face.plate_id,
                                _between_many(face.vertex_ids, copy, neighbour, between), face.holes, face.block_id)
    taken = {face.face_id for face in faces} | set(network.lineage.retired_face_ids)
    strips, swept = [], []
    for boundary in network.boundaries:
        kind, _ = rule[boundary.boundary_id]
        if kind in (LOCKED, TRANSFORM):                   # nothing is born or consumed along a transform
            continue
        chain = boundary.vertex_ids
        if kind == TRENCH and boundary.boundary_id in passed_on:
            # A passed degree-two point only subdivided this straight trace. Its individual old/new quad reverses
            # when the junction goes beyond it; coalesce those segments and sweep their original outer ends.
            # This retains the old footprint and its consuming plate while the endpoint subdivision changes owner.
            chain = tuple(vertex for vertex in chain if vertex not in passed_on[boundary.boundary_id])
        steps = list(zip(chain, chain[1:]))+([(chain[-1], chain[0])] if boundary.closed else [])
        for k, (a, b) in enumerate(steps):
            if kind == RIDGE:
                for side, plate in zip(SIDES, (boundary.left_plate_id, boundary.right_plate_id)):
                    mine = (corner.get((a, plate), a), corner.get((b, plate), b))
                    edge = generated.get((a, boundary.boundary_id), (a,))[::-1]+generated.get(
                        (b, boundary.boundary_id), (b,))
                    ids = (mine[1], mine[0])+edge if side == 'left' else edge[::-1]+mine
                    ids = _without_repeats(ids)
                    if len(ids) < 3:
                        continue
                    ring_points = [coords(plate, name) for name in ids]
                    curved = (a, boundary.boundary_id) in generated or (b, boundary.boundary_id) in generated
                    positive = _positive_simple_ring(network.sphere, ring_points) if curved else _turns_left(ring_points)
                    if not positive:
                        raise TransferRefused(
                            'ridge %r closes on its %s side between %r and %r: a negative half-rate creates no '
                            'material and consumes none; refused' % (boundary.boundary_id, side, a, b))
                    # The line carrier's face retains every sample crossed between its old corner and this
                    # junction. Its neighbouring born strip must use exactly that same edge subdivision. Test
                    # the opening above on the original corners: a collinear subdivision has no turn of its own.
                    for (copy, junction), passed in traversed_edges.items():
                        if _adjacent(ids, copy, junction) is not None:
                            ids = _between_many(ids, copy, junction, passed)
                    face_id = '%s|%s|%d|%04d' % (boundary.boundary_id, side, motion.end_step, k)
                    if face_id in taken or len(face_id) > 256:
                        raise TransferRefused('the derived face identity %r is reserved or too long' % face_id)
                    taken.add(face_id)
                    faces.append(Face(face_id, plate, ids))
                    strips.append((face_id, boundary.boundary_id, side))
            else:
                side = boundary.subducting_side
                plate = boundary.left_plate_id if side == 'left' else boundary.right_plate_id
                local = network._local[order[plate]]
                old = (local[lookup[a]], local[lookup[b]])
                new = (coords(plate, a), coords(plate, b))
                ring = [old[0], old[1], new[1], new[0]] if side == 'left' else [old[1], old[0], new[0], new[1]]
                kept = [ring[0]]
                for point in ring[1:]:
                    if float(_angle(point, kept[-1])) > ATTACHMENT_BAND_RAD:
                        kept.append(point)
                if len(kept) > 1 and float(_angle(kept[0], kept[-1])) <= ATTACHMENT_BAND_RAD:
                    kept.pop()
                if len(kept) < 3:
                    continue
                if not _turns_left(kept):
                    raise TransferRefused(
                        'trench %r opens between %r and %r: the subducting plate does not move into it there '
                        '(consumption must be positive); refused' % (boundary.boundary_id, a, b))
                swept.append((boundary.boundary_id, plate, np.array(kept)))
    if trench_corners:
        # D5 currently constructs the shared overriding-side subdivision without a general seam reorganisation.
        # Name that construction limit here, before the atlas validator can misdiagnose its gap as exhausted cells.
        ends = {vertex for _, _, copy, name, _, _ in trench_corners for vertex in (copy, name)}
        edges = {(a, b) for face in faces for ring in (face.vertex_ids, *face.holes)
                 for a, b in zip(ring, ring[1:]+ring[:1])}
        gaps = sorted((a, b) for a, b in edges if (a in ends or b in ends) and (b, a) not in edges)
        if gaps:
            raise TransferRefused('D5 overriding-side subdivision leaves an unpaired edge %r to %r: this interval '
                                  'needs a seam reorganisation beyond the constructed junction geometry; refused'
                                  % gaps[0])
    plates = tuple(Plate(plate.plate_id, plate.rotation.then(stage[plate.plate_id]), plate.parent_plate_ids)
                   for plate in network.plates)
    old = network.lineage
    lineage = Lineage(network.network_id, old.root_network_id or network.network_id, old.events,
                      old.retired_face_ids, old.retired_boundary_ids, old.retired_plate_ids)
    # The endpoint layout: copies are new vertices of the plate that keeps them; a ridge record's vertex keeps its
    # reference direction; a vertex that moved relative to its home plate is placed again there; every plate's copy of
    # a vertex kept elsewhere is its own.
    homes = {name: keeper for name, keeper in home.items() if name not in coincident}
    for copy, (plate, _) in copies.items():
        homes[copy] = plate
    endpoint_names = tuple(sorted(homes))
    reference = np.asarray([copies[name][1] if name in copies else
                            _turned(frames_new[homes[name]].inverse(), target[name])[0] if name in path_targets else
                            layout.reference[lookup[name]] if homes[name] in ridge_frame else coords(homes[name], name)
                            for name in endpoint_names], dtype=np.float64)
    views = tuple(sorted(((name, plate), tuple(float(x) for x in coords(plate, name)))
                         for name, plate in _sphere._used(faces) if homes[name] != plate))
    layout = _sphere._Layout(endpoint_names, tuple(homes[name] for name in endpoint_names), reference, views,
                             frames, ridges, tuple(sorted((dict(layout.poles) | path_poles).items())))
    boundaries = tuple(Boundary(b.boundary_id, b.kind, b.left_plate_id, b.right_plate_id, chains[b.boundary_id],
                                b.origin, b.closed, b.subducting_side, b.accretion_fraction, b.carrier_side)
                       if b.boundary_id in chains else b for b in network.boundaries)
    return _Moved(layout, tuple(faces), plates, boundaries, lineage, tuple(status), tuple(junctions), worst,
                  tuple(strips), tuple(deformed), tuple(slid), tuple(reshaped), tuple(swept), tuple(transient))


def _positive_simple_ring(sphere, points):
    """A generated curved strip may be nonconvex; require a simple positively oriented conditioned polygon."""
    points = np.asarray(points)
    centre = np.sum(points, axis=0)
    centre /= np.linalg.norm(centre)
    chart = SphericalChart(sphere, tuple(centre), _sphere.CHART_MIN_COSINE)
    polygon = Polygon(chart._project(points))
    return polygon.is_valid and not polygon.is_empty and polygon.exterior.is_ccw


def _pole(a, b):
    """The unit pole of the great circle through two directions, formed stably: normalise((a + b) x (b - a))."""
    pole = np.cross(a+b, b-a)
    return pole/np.linalg.norm(pole)


def _line_pole(trace):
    """The pole of a trace that is one great circle, or None where it bends (integration_sphere._trace_pole)."""
    return _sphere._trace_pole(trace)


def _trench_material_seams(network, rule, carried, lookup, uses, cancel):
    """Advect a two-face subducting seam's end on one straight carrier edge.

    A D5 intersection is not a permanent carrier sampling point: two subducting faces meet along an interior
    material edge there. Carry that edge rigidly with its plate, then intersect it with the advanced trench.
    The one carrier face only changes its same-edge subdivision. No face is merged, removed or reassigned, and
    the ordinary overlap rows retain each cohort. Carrier seams, physical junctions, bent traces, disappearing
    edges and an endpoint crossing another seam remain outside this construction.
    """
    incident = {name: [] for name in uses}
    for face in network.faces:
        for ring in (face.vertex_ids, *face.holes):
            for k, name in enumerate(ring):
                if name in incident:
                    incident[name].append((face, ring[k-1], ring[(k+1) % len(ring)]))
    result = {}
    for name, records in sorted(uses.items()):
        _check_cancel(cancel)
        if len(records) != 1 or rule[records[0].boundary_id][0] != TRENCH:
            continue
        boundary = records[0]
        chain = boundary.vertex_ids
        k = chain.index(name)
        if not boundary.closed and k in (0, len(chain)-1):
            continue
        carrier = _sphere._carrier(boundary)
        far = boundary.left_plate_id if boundary.subducting_side == 'left' else boundary.right_plate_id
        near = [row for row in incident[name] if row[0].plate_id == carrier]
        away = [row for row in incident[name] if row[0].plate_id == far]
        if len(near) != 1 or len(away) != 2 or len(incident[name]) != 3:
            continue
        common = set(away[0][1:]) & set(away[1][1:])
        if len(common) != 1 or next(iter(common)) in uses:
            continue
        neighbour = next(iter(common))
        rotation = rule[boundary.boundary_id][1]
        before, after = chain[k-1], chain[(k+1) % len(chain)]
        line = _turned(rotation, network.vertex_direction[[lookup[before], lookup[name], lookup[after]]])
        normal = _line_pole(line)
        if normal is None:
            raise TransferRefused('a moving trench material seam is not on one straight carrier edge')
        a, b = carried[far][lookup[name]], carried[far][lookup[neighbour]]
        edge = _pole(a, b)
        crossing = np.cross(edge, normal)
        sine = float(np.linalg.norm(crossing))
        if sine < SHALLOWEST_SINE:
            raise TransferRefused('a moving trench material seam intersects below sin 1/16; refused')
        crossing /= sine
        if float(crossing @ line[1]) < 0:
            crossing = -crossing
        if (float(np.cross(a, crossing) @ edge) <= 0 or float(np.cross(crossing, b) @ edge) <= 0
                or float(_angle(crossing, a)) <= ATTACHMENT_BAND_RAD
                or float(_angle(crossing, b)) <= ATTACHMENT_BAND_RAD):
            raise TransferRefused('a moving trench material seam has no interior carried-edge intersection; refused')
        result[name] = (crossing, carrier)
    return result


def _slip_parallel(network, rule, frames, lookup):
    """Refuse a sliding transform whose far plate has not slid along its trace in total (I03a-2 C6).

    A transform's trace is rigid in its carrier's frame. C6 is judged on the far plate's total frame relative to the
    carrier's, F_carrier^-1 F_far after this interval, so that motion inside the band cannot add up over intervals
    (round 1 of the coordinator's verification, F3). Every trace vertex, in the carrier's frame and carried by that
    relative rotation, must lie within the existing 64 eps band of the trace's great circle stored at declaration
    (integration_sphere._end_poles): an exact slip about the circle's pole leaves only rounding, and any normal motion
    would open a gap or an overlap with no account. A frame change cancels in the relative rotation. A trace that is
    not one great circle admits no slip in total: each vertex so carried must stay within the band of where it is.
    """
    poles = dict(network._layout.poles)
    order = {plate: i for i, plate in enumerate(network.plate_ids)}
    for boundary in network.boundaries:
        kind, _ = rule[boundary.boundary_id]
        if kind != TRANSFORM:
            continue
        carrier = boundary.right_plate_id if boundary.carrier_side == 'right' else boundary.left_plate_id
        far = boundary.left_plate_id if boundary.carrier_side == 'right' else boundary.right_plate_id
        relative = frames[far].then(frames[carrier].inverse())
        trace = network._local[order[carrier]][[lookup[name] for name in boundary.vertex_ids]]
        images = _turned(relative, trace)
        pole = poles.get((boundary.boundary_id, 'trace'))
        if pole is not None:
            offsets = np.abs(images @ np.asarray(pole))
            what = "off the trace's great circle"
        else:
            offsets = np.linalg.norm(images-trace, axis=1)
            what = 'from where it was on a trace that is not one great circle'
        worst = int(np.argmax(offsets))
        if float(offsets[worst]) > ATTACHMENT_BAND_RAD:
            raise TransferRefused('transform %r is not slip-parallel at %r: its far plate has moved %.3e rad in total '
                                  '%s (more than the 64 eps band); a boundary with opening or closing must be declared '
                                  'a ridge or a trench' % (boundary.boundary_id, boundary.vertex_ids[worst],
                                                           float(offsets[worst]), what),
                                  TRANSFORM_NOT_SLIP_PARALLEL)


SHALLOWEST_SINE = 1/16          # I03a-2 C4: (2 eps + 2 eps)/sin psi within the 64 eps band (approved 3 October 2026)


def _velocity(rotation, here):
    """The instantaneous velocity at ``here`` of a plate turning by ``rotation`` over the interval (radians)."""
    return np.cross(np.asarray(_vector(rotation)), here)


def _adjacent(ring, a, b):
    """The index k such that ring[k], ring[k+1] (cyclically) are a, b in either order, or None."""
    for k in range(len(ring)):
        if {ring[k], ring[(k+1) % len(ring)]} == {a, b}:
            return k
    return None


def _between(ring, a, b, name):
    """``ring`` with ``name`` inserted between its consecutive vertices a and b."""
    k = _adjacent(ring, a, b)
    return ring[:k+1]+(name,)+ring[k+1:]


def _between_many(ring, a, b, names):
    """Insert names ordered from a toward b into their ring edge, preserving the ring's orientation."""
    k = _adjacent(ring, a, b)
    inserted = tuple(names) if ring[k] == a else tuple(reversed(names))
    return ring[:k+1]+inserted+ring[k+1:]


def _advanced_junction(network, junction, here, rule, stage, frames_old, frames_new, points, lookup, seam_targets=None):
    """Where a junction whose records move it to different points goes (I03a-2 Part 2, approved 3 October 2026).

    The records ending there are grouped into lines by the poles stored at declaration (M6, C3): records that share a
    carrier and a line give one constraint. Exactly two lines must meet there: three or more rigid lines cannot stay
    concurrent, so such a junction must reorganise, which needs an admitted law. The contract's closure residual
    r = ||A J - b|| / max |v_i - v_j| is checked at the start of the interval (C1, 1e-11), with rows the stored poles and
    each record's carrier velocity relative to one plate at the junction (the first by ID), so that a common rotation
    of every plate leaves it unchanged; for one line and one other record it is zero by structure. The junction goes
    to the intersection of the two advanced lines nearest the junction as the first line carries it, which must cross
    at sin psi >= 1/16 (C4), and no record's end segment may shorten to zero or reverse (C5). Returns (new position, residual, carrier of the through line,
    record ends on it).
    """
    name = junction.vertex_id
    record = {boundary.boundary_id: boundary for boundary in network.boundaries}
    poles = dict(network._layout.poles)
    lines = {}
    for end in junction.boundary_ends:
        lines.setdefault((_sphere._carrier(record[end[0]]), poles[end]), []).append(end)
    if len(lines) < 2:
        raise TransferRefused('the boundary records that end at vertex %r move it to different points along one line; '
                              'refused' % name)
    # C3: records on one great circle through the junction with different carriers would be one line carried by two
    # plates. A through-going line is carried by one plate, so such a junction cannot advance.
    ends = [(end, _sphere._placed(frames_old[_sphere._carrier(record[end[0]])], np.asarray(poles[end]))[0])
            for end in junction.boundary_ends]
    for i, (first, one_pole) in enumerate(ends):
        for second, two_pole in ends[i+1:]:
            if (_sphere._carrier(record[first[0]]) != _sphere._carrier(record[second[0]])
                    and float(np.linalg.norm(np.cross(one_pole, two_pole))) <= ATTACHMENT_BAND_RAD):
                raise TransferRefused('records %r and %r end at junction %r on one great circle with different '
                                      'carriers: a through-going line is carried by one plate (C3); refused'
                                      % (first[0], second[0], name))
    plates = sorted({plate for end in junction.boundary_ends
                     for plate in (record[end[0]].left_plate_id, record[end[0]].right_plate_id)})
    velocity = {plate: _velocity(stage[plate], here) for plate in plates}
    reference = velocity[plates[0]]          # relative velocities: a common rotation changes neither b nor the scale
    rows, values = [], []
    for (carrier, pole), members in lines.items():
        start = _sphere._placed(frames_old[carrier], np.asarray(pole))[0]
        for boundary_id, _ in members:
            boundary = record[boundary_id]
            if boundary.kind == RIDGE:
                f = boundary.accretion_fraction
                moving = (1-f)*velocity[boundary.left_plate_id]+f*velocity[boundary.right_plate_id]
            else:
                carrier_plate = _sphere._carrier(boundary)
                moving = velocity[carrier_plate]
            rows.append(start)
            values.append(float(start @ (moving-reference)))
    scale = max((float(np.linalg.norm(velocity[a]-velocity[b])) for i, a in enumerate(plates)
                 for b in plates[i+1:]), default=0.)
    first = np.cross(here, np.eye(3)[int(np.argmin(np.abs(here)))])
    first /= np.linalg.norm(first)
    second = np.cross(here, first)
    matrix = np.array([[row @ first, row @ second] for row in rows])
    solution = np.linalg.lstsq(matrix, np.array(values), rcond=None)[0]
    residual = float(np.linalg.norm(matrix @ solution-np.array(values)))/scale if scale > 0 else 0.
    if residual > ALGEBRA_RELATIVE:
        raise TransferRefused('the boundary records that end at vertex %r move it to different points: the closure '
                              'residual at the start of the interval is %.3e, above 1e-11, so the junction must '
                              'reorganise, which needs an admitted law; refused' % (name, residual))
    if len(lines) > 2:
        raise TransferRefused('the boundary records that end at vertex %r move it to different points: %d distinct '
                              'lines meet there, and rigid lines do not stay concurrent beyond this instant, so the '
                              'junction must reorganise, which needs an admitted law; refused' % (name, len(lines)))
    (one, one_members), (two, two_members) = lines.items()
    advanced = [_sphere._placed(frames_new[carrier], np.asarray(pole))[0] for carrier, pole in (one, two)]
    crossing = np.cross(advanced[0], advanced[1])
    sine = float(np.linalg.norm(crossing))
    if sine < SHALLOWEST_SINE:
        raise TransferRefused('the lines at junction %r cross at sin %.3e, below 1/16: the junction is '
                              'underdetermined at the existing 64 eps band; refused' % (name, sine))
    moved = crossing/sine
    if float(moved @ _turned(rule[one_members[0][0]][1], here)[0]) < 0:      # nearest the carried junction
        moved = -moved
    through = [(carrier, members) for (carrier, _), members in lines.items() if len(members) > 1]
    if len(through) != 1 or type(through[0][0]) is not str:
        raise TransferRefused('the records at junction %r lie on two lines of one record each (a corner): this version '
                              'advances such a junction only where they carry it to one point; refused' % name)
    through_ends, crossings = set(through[0][1]), {}
    for boundary_id, role in junction.boundary_ends:
        chain = record[boundary_id].vertex_ids
        rotation = rule[boundary_id][1]
        carried = _turned(rotation, here)[0]
        candidates = chain[1:] if role == 'start' else chain[-2::-1]
        passed = []
        for ahead in candidates:
            old_beside = _turned(rotation, points[lookup[ahead]])[0]
            beside = seam_targets[ahead][0] if seam_targets and ahead in seam_targets else old_beside
            if (float(_angle(beside, moved)) > ATTACHMENT_BAND_RAD
                    and float(np.cross(moved, beside) @ np.cross(carried, old_beside)) > 0):
                break
            if any(other.vertex_id == ahead for other in network.junctions):
                raise TransferRefused('a boundary segment of %r would shorten to zero at junction %r: the junction '
                                      'must reorganise, which needs an admitted law; refused' % (boundary_id, name))
            used = sum(1 for face in network.faces for ring in (face.vertex_ids, *face.holes) if ahead in ring)
            pole = _sphere._placed(frames_new[_sphere._carrier(record[boundary_id])],
                                   np.asarray(poles[boundary_id, role]))[0]
            if ((boundary_id, role) in through_ends and used == 2
                    and abs(float(pole @ beside)) <= ATTACHMENT_BAND_RAD):
                passed.append(ahead)
                continue
            option = ('a declared vertex outside the advanced through line' if used <= 2 else
                      'a seam vertex, where faces beside the line meet: passing it needs option D1-c (deferred)')
            raise TransferRefused('a boundary segment of %r would shorten to zero at junction %r, which would reach or '
                                  'pass %r, %s; refused' % (boundary_id, name, ahead, option))
        if passed:
            crossings[boundary_id] = tuple(passed)
    return moved, residual, through[0][0], tuple(through[0][1]), crossings



def _issued(network, moved, end_time_s, step, limits, budget, cancel):
    """The endpoint network of a moved declaration, validated as a closed atlas; a refusal names the cause."""
    try:
        return _sphere._network(network.sphere, moved.layout, moved.faces, moved.plates, moved.boundaries,
                                network.epoch_id, end_time_s, step, network.reference_time_s, moved.lineage, limits,
                                budget, cancel, False)
    except ExchangeRefused:
        raise
    except TectonicsError as exc:
        raise TransferRefused('the moved network is not a valid closed network (a boundary cell may be exhausted, '
                              'or the interval may be too long for the mesh): '+str(exc)) from exc


# ----------------------------------------------------------------------------- measures

class _Shapes:
    """Ring directions of a network's faces by face index, each in its own plate's reference frame."""
    __slots__ = ('network', 'lookup', 'order')

    def __init__(self, network):
        self.network = network
        self.lookup = {name: i for i, name in enumerate(network.vertex_ids)}
        self.order = {plate: i for i, plate in enumerate(network.plate_ids)}

    def rings(self, index):
        """The directions of one face's rings in its plate's reference frame: the same before and after a ride."""
        return _sphere._rings_of(self.network, index, self.lookup, self.order)


def _cap(rings):
    """A geodesically convex cap that contains a face: (centre, angular radius)."""
    outer = rings[0]
    centre = np.array([math.fsum(outer[:, axis]) for axis in range(3)])
    centre = centre/np.linalg.norm(centre)
    return centre, float(np.max(_angle(outer, centre)))


def _separated(first, second):
    """True when a great circle through an edge of one face has that face on one side and the other face beyond it.

    The outer ring of one face lies on the inner side of the edge's great circle (within the attachment band) and
    every vertex of the other's outer ring lies beyond that band on the outer side. Minor-arc polygons are inside
    the convex hull of their vertices, so such faces cannot overlap.
    """
    for ring, other in ((first[0], second[0]), (second[0], first[0])):
        for a, b in zip(ring, np.roll(ring, -1, axis=0)):
            normal = np.cross(a, b)
            margin = ATTACHMENT_BAND_RAD*float(np.linalg.norm(normal))
            if margin > 0 and np.all(ring @ normal >= -margin) and np.all(other @ normal < -margin):
                return True
    return False


def _overlap_sr(first, second, sphere, *, budget=None):
    """Area in steradians of the intersection of two minor-arc polygons, each a list of rings of directions.

    Both are projected into one gnomonic chart centred on their joint mean, where every minor arc is a straight
    segment, so the intersection is that of two planar polygons and vertices the two share project to the same
    coordinates. Each resulting ring is measured on the sphere from an anchor at its own mean, so a small overlap is
    measured at its own scale. Two faces that share no conditioned hemisphere need no chart when a great circle
    separates them; otherwise they are refused, never split silently.
    """
    joint = np.vstack([first[0], second[0]])
    centre = np.array([math.fsum(joint[:, axis]) for axis in range(3)])
    norm = float(np.linalg.norm(centre))
    if not norm > 0:
        if _separated(first, second):
            return 0.
        raise TransferRefused('two faces share no conditioned hemisphere: unresolved overlap', UNRESOLVED_OVERLAP)
    try:
        chart = SphericalChart(sphere, tuple(float(x) for x in centre/norm), _sphere.CHART_MIN_COSINE)
        shapes = [Polygon(chart._project(rings[0]), [chart._project(hole) for hole in rings[1:]])
                  for rings in (first, second)]
        if not all(shape.is_valid for shape in shapes):
            raise TransferRefused('a moved face is not a simple polygon in its chart: unresolved overlap',
                                      UNRESOLVED_OVERLAP)
        common = shapely.intersection(shapes[0], shapes[1], grid_size=0.)
    except ExchangeRefused:
        raise
    except TectonicsError as exc:
        if _separated(first, second):
            return 0.
        raise TransferRefused('two faces share no conditioned hemisphere: unresolved overlap',
                              UNRESOLVED_OVERLAP) from exc
    except (GEOSException, ValueError) as exc:
        raise TransferRefused('polygon intersection failed; no repair attempted: unresolved overlap',
                              UNRESOLVED_OVERLAP) from exc
    pieces, stack = [], [common]
    while stack:
        part = stack.pop()
        if part.is_empty:
            continue
        if part.geom_type == 'Polygon':
            for sign, coords in ((1., part.exterior.coords), *((-1., hole.coords) for hole in part.interiors)):
                ring = chart._unproject(np.asarray(coords))
                pieces.append(sign*_ring_area(ring, _cap([ring[:-1]])[0]))
        elif part.geom_type in ('MultiPolygon', 'GeometryCollection'):
            stack.extend(part.geoms)
    if not pieces:
        # GEOS can return the overlay of two overlapping polygons as points or lines only, when vertices of a shared
        # edge lie an ulp apart. Where the union shows an overlap beyond the relative tolerance of the larger face
        # (above the union's own rounding), that is not a zero overlap. Resolve the original spherical operands
        # with the bounded exact intersection; its conditioning and input refusals remain in force. A sliver at
        # rounding level stays a zero overlap.
        larger = max(shapes[0].area, shapes[1].area)
        implied = shapes[0].area+shapes[1].area-shapely.union(shapes[0], shapes[1], grid_size=0.).area
        if implied > RELATIVE_TOLERANCE*larger:
            return _exact_overlap_sr(first, second, sphere, budget=budget)
    area = math.fsum(pieces)
    return area if area > 0 else 0.


def _integers(points):
    """Rows of binary64 directions as exact integers, all scaled by one power of two."""
    ratios = [[float(x).as_integer_ratio() for x in row] for row in points]
    scale = max(d for row in ratios for _, d in row)
    return [tuple(n*(scale//d) for n, d in row) for row in ratios]


def _dot(a, b):
    return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _sign(value):
    return (value > 0)-(value < 0)


def _primitive(point):
    """One exact homogeneous direction, with its irrelevant positive integer scale removed."""
    divisor = math.gcd(*point)
    if not divisor:
        raise TransferRefused('an exact overlap has an undefined direction', UNRESOLVED_OVERLAP)
    return tuple(value//divisor for value in point)


def _exact_triangle_sr(a, b, c):
    """Signed spherical triangle area without cancelling unit-scale binary64 products.

    The determinant and dot products are exact integers. Only square roots and the denominator use Decimal;
    80 significant decimal digits leave over 60 guard digits beyond binary64. atan2 retains C7's existing one-ulp
    platform assumption. Its two arguments share one scale before their final correctly rounded float conversion.
    """
    numerator = _dot(a, _cross(b, c))
    if not numerator:
        return 0.
    with localcontext() as context:
        context.prec = 80
        na, nb, nc = (Decimal(_dot(v, v)).sqrt() for v in (a, b, c))
        denominator = na*nb*nc+Decimal(_dot(a, b))*nc+Decimal(_dot(b, c))*na+Decimal(_dot(c, a))*nb
        numerator = Decimal(numerator)
        scale = max(abs(numerator), abs(denominator))
        return 2*math.atan2(float(numerator/scale), float(denominator/scale))


def _exact_ring_sr(ring):
    """Measure the directions actually stored, retaining exact predicates through the triangle determinant."""
    vertices = [_primitive(v) for v in _integers(ring)]
    return abs(math.fsum(_exact_triangle_sr(vertices[0], vertices[i], vertices[i+1])
                         for i in range(1, len(vertices)-1)))


def _exact_triangles(ring, centre):
    """Ear decomposition in an open hemisphere, using exact central-projection signs; no new vertices."""
    vertices = [_primitive(v) for v in _integers(ring)]
    # Every ring passed here already has simple-polygon validation. Remove only exact repeated/collinear corners.
    while len(vertices) > 2:
        remove = next((i for i, b in enumerate(vertices)
                       if _dot(vertices[i-1], _cross(b, vertices[(i+1) % len(vertices)])) == 0), None)
        if remove is None:
            break
        vertices.pop(remove)
    if len(vertices) < 3:
        return []
    axis = min(range(3), key=lambda k: abs(centre[k]))
    up = _cross(centre, tuple(int(k == axis) for k in range(3)))
    right = _cross(up, centre)
    projected = [(Fraction(_dot(right, v), _dot(centre, v)), Fraction(_dot(up, v), _dot(centre, v)))
                 for v in vertices]
    orientation = sum((a[0]*b[1]-a[1]*b[0] for a, b in zip(projected, projected[1:]+projected[:1])), Fraction(0))
    if orientation < 0:
        vertices.reverse()
    triangles = []
    while len(vertices) > 3:
        for i, b in enumerate(vertices):
            a, c = vertices[i-1], vertices[(i+1) % len(vertices)]
            if _dot(a, _cross(b, c)) <= 0:
                continue
            normals = (_cross(a, b), _cross(b, c), _cross(c, a))
            if any(all(_dot(n, p) >= 0 for n in normals) for p in vertices if p not in (a, b, c)):
                continue
            triangles.append((a, b, c))
            vertices.pop(i)
            break
        else:
            raise TransferRefused('the exact overlap cannot decompose its ring', UNRESOLVED_OVERLAP)
    triangles.append(tuple(vertices))
    return triangles


def _exact_clipped_triangle(first, second):
    """Sutherland-Hodgman intersection as integer homogeneous directions, with every side decision exact."""
    polygon = list(first)
    for a, b in zip(second, second[1:]+second[:1]):
        normal, out = _cross(a, b), []
        for p, q in zip(polygon, polygon[1:]+polygon[:1]):
            dp, dq = _dot(normal, p), _dot(normal, q)
            if dp >= 0:
                out.append(p)
            if dp*dq < 0:
                direction = tuple((y*dp-x*dq)*_sign(dp-dq) for x, y in zip(p, q))
                out.append(_primitive(direction))
        polygon = list(dict.fromkeys(out))
        if len(polygon) < 3:
            return 0.
    return math.fsum(_exact_triangle_sr(polygon[0], polygon[i], polygon[i+1])
                     for i in range(1, len(polygon)-1))


def _exact_overlap_workspace(first, second):
    """The unchanged conservative pair workspace, including integer exponent growth."""
    points = [point for rings in (first, second) for ring in rings for point in ring]
    exponent = max(float(x).as_integer_ratio()[1].bit_length() for point in points for x in point)
    # Ear decomposition stores O(vertices) directions/triangles and clips one triangle pair at a time. A clipped
    # corner is the cross of two original edge normals (four input factors); intermediate arithmetic is bounded
    # conservatively here, including Python objects. Extreme binary64 exponents consume the caller's same budget.
    return 65536+len(points)*(4096+128*exponent)


def _exact_overlap_sr(first, second, sphere, *, budget=None):
    """Reserve the bounded integer/ear-clipping workspace before constructing it."""
    workspace = _exact_overlap_workspace(first, second)
    with select_budget(budget).reserve(workspace, category='i03-exact-overlap'):
        return _exact_overlap_unreserved(first, second, sphere)


def _exact_overlap_unreserved(first, second, sphere, *, first_triangles=None):
    """M3 targeted fallback: exact intersection of the input directions, including concave rings and holes.

    Rings are decomposed into triangles using exact signs in a conditioned central projection. Triangle clipping
    keeps exact homogeneous integer directions, and the spherical measure is evaluated before rounding vertices.
    Inclusion-exclusion subtracts either polygon's holes and restores intersections of two holes.
    """
    joint = np.vstack([first[0], second[0]])
    centre = _sphere._mean_direction(joint)
    if np.any(joint @ centre < _sphere.CHART_MIN_COSINE):
        if _separated(first, second):
            return 0.
        raise TransferRefused('two faces share no conditioned hemisphere: unresolved overlap', UNRESOLVED_OVERLAP)
    c = _integers([centre])[0]
    triangles = [first_triangles if first_triangles is not None else
                 [(1 if index == 0 else -1, _exact_triangles(ring, c)) for index, ring in enumerate(first)],
                 [(1 if index == 0 else -1, _exact_triangles(ring, c)) for index, ring in enumerate(second)]]
    return max(0., math.fsum(sa*sb*_exact_clipped_triangle(a, b)
                            for sa, ta in triangles[0] for sb, tb in triangles[1] for a in ta for b in tb))


def _exact_sweep_sr(first, sweeps, sphere, *, budget=None, sweep_caps=None):
    """Exact swept area with conservative cap rejection and one retained donor decomposition.

    A strictly hemispheric cap contains the minor arcs and their polygon interior. Disjoint caps therefore
    cannot contribute. The existing attachment band widens the reach test only to retain rounding-near pairs;
    an unconditioned cap never rejects a pair. Every retained pair still passes the original joint-chart gate.
    Ear order uses only exact signs of the input directions, so every valid central projection gives the same
    triangles. Retain only this donor's triangles; reserve the largest unchanged pair envelope for their lifetime.
    """
    centre, radius = _cap(first)
    candidates = []
    if sweep_caps is None:
        sweep_caps = (_cap([ring]) for ring in sweeps)
    for ring, (middle, reach) in zip(sweeps, sweep_caps, strict=True):
        if (max(radius, reach)+ATTACHMENT_BAND_RAD < math.pi/2
                and float(_angle(centre, middle)) > radius+reach+2*ATTACHMENT_BAND_RAD):
            continue
        candidates.append(ring)
    if not candidates:
        return 0.
    workspace = max(_exact_overlap_workspace(first, [ring]) for ring in candidates)
    with select_budget(budget).reserve(workspace, category='i03-exact-overlap'):
        own = _sphere._mean_direction(first[0])
        triangles = None
        if np.all(first[0] @ own >= _sphere.CHART_MIN_COSINE):
            c = _integers([own])[0]
            triangles = [(1 if index == 0 else -1, _exact_triangles(ring, c))
                         for index, ring in enumerate(first)]
        return math.fsum(_exact_overlap_unreserved(first, [ring], sphere, first_triangles=triangles)
                         for ring in candidates)


def _within(inner, outer, centre):
    """True when the closed polygon ``inner`` lies in the closed polygon ``outer``, decided exactly; None if undecided.

    Each is the outer ring of a face (directions) and ``outer`` has no hole. The test is carried out in the central
    projection about ``centre``, where every minor arc is a straight segment, with every predicate an exact sign of
    an integer expression in the binary64 inputs: nothing is rounded. It is undecided (None) unless every vertex is
    strictly in the hemisphere of ``centre``. ``inner`` lies in ``outer`` when no edge of one properly crosses an edge
    of the other and every piece of each edge of ``inner``, cut at the vertices of ``outer`` on it, lies in the
    closed polygon ``outer`` (Sunday's winding-number test, with the boundary decided first); a polygon without holes
    then contains everything the closed curve bounds.
    """
    points = _integers(list(inner)+list(outer)+[centre])
    inner, outer, c = points[:len(inner)], points[len(inner):-1], points[-1]
    if any(_dot(c, v) <= 0 for v in inner+outer):
        return None
    # Projected coordinates are y(v) = up.v/c.v and x(v) = (up x c).v/c.v; with that x axis the planar orientation of
    # three projected points has the sign of det[a, b, p], since det[up x c, up, c] = |up x c|^2 > 0.
    axis = min(range(3), key=lambda k: abs(c[k]))
    up = _cross(c, tuple(int(k == axis) for k in range(3)))

    def left(a, b, p):
        return _sign(_dot(a, _cross(b, p)))

    def above(a, p):                                               # sign of y(a) - y(p), both projected
        return _sign(_dot(up, a)*_dot(c, p)-_dot(up, p)*_dot(c, a))

    def between(p, a, b):                                          # p on the arc a-b, given det[a, b, p] = 0
        n = _cross(a, b)
        return _dot(_cross(a, p), n) >= 0 and _dot(_cross(p, b), n) >= 0

    def where(p):                                                  # 1 inside, 0 on the boundary, -1 outside
        winding = 0
        for a, b in zip(outer, outer[1:]+outer[:1]):
            if _dot(a, _cross(b, p)) == 0 and between(p, a, b):
                return 0
            if above(a, p) <= 0:
                if above(b, p) > 0 and left(a, b, p) > 0:
                    winding += 1
            elif above(b, p) <= 0 and left(a, b, p) < 0:
                winding -= 1
        return 1 if winding else -1

    edges = list(zip(outer, outer[1:]+outer[:1]))
    for a, b in zip(inner, inner[1:]+inner[:1]):
        stops, n = [a, b], _cross(a, b)
        for p, q in edges:
            o1, o2 = _sign(_dot(n, p)), _sign(_dot(n, q))
            if o1*o2 < 0 and _sign(_dot(_cross(p, q), a))*_sign(_dot(_cross(p, q), b)) < 0:
                return False                                       # a proper crossing
            stops.extend(r for r, o in ((p, o1), (q, o2)) if o == 0 and between(r, a, b))
        # Order the stops along the arc from a to b; between neighbours the edge meets no vertex of ``outer`` and
        # crosses none of its edges, so it is wholly inside, outside or on the boundary: its middle decides.
        ordered = sorted(set(stops), key=lambda r: Fraction(_dot(_cross(a, r), n),
                                                            _dot(_cross(a, r), n)+_dot(_cross(r, b), n)))
        for p, q in zip(ordered, ordered[1:]):
            if where(tuple(x+y for x, y in zip(p, q))) < 0:
                return False
    return True


def _nested(first, second):
    """(face ``first`` lies within face ``second``, ``second`` lies within ``first``), each decided exactly.

    Both are lists of rings in one plate's reference frame. Containment is decided exactly (_within) and tried only
    where every vertex of the inner face is within the outer face's bounding cap, widened by the existing attachment
    band so that rounding of the angles cannot rule out a true containment; the cap decides nothing. An undecided
    containment counts as none, and the pair is then clipped like any other.
    """
    found = []
    for inner, outer in ((first, second), (second, first)):
        centre, radius = _cap(outer)
        found.append(len(outer) == 1 and bool(np.all(_angle(inner[0], centre) <= radius+ATTACHMENT_BAND_RAD))
                     and _within(inner[0], outer[0], centre) is True)
    return tuple(found)


def _metres(steradians, sphere):
    return (steradians*sphere.radius_m)*sphere.radius_m


def _ring_m2(ring, sphere):
    """Area in m2 of one convex ring of directions."""
    return _metres(_exact_ring_sr(ring), sphere)


@dataclass(frozen=True, slots=True)
class _Rows:
    """Sparse overlap rows: donor and receiver face indices (-1 for a named party) and measured areas in m2."""
    donor: tuple
    receiver: tuple
    party: tuple
    area_m2: tuple
    parties: tuple
    transient: tuple = ()

    def arrays(self, prefix):
        arrays = {prefix+'donor': np.asarray(self.donor, dtype=np.int64),
                prefix+'receiver': np.asarray(self.receiver, dtype=np.int64),
                prefix+'party': np.asarray(self.party, dtype=np.int64),
                prefix+'area_m2': np.asarray(self.area_m2, dtype=np.float64)}
        if self.transient:
            for k, name, dtype in ((0, 'transient_birth_party', np.int64), (1, 'transient_sink_party', np.int64),
                                    (2, 'transient_area_m2', np.float64)):
                arrays[prefix+name] = np.asarray([row[k] for row in self.transient], dtype=dtype)
        return arrays


def _motion_rows(network, endpoint, moved, cancel, budget=None):
    """Measure the rows of one motion: births, consumption and the subducting faces' own overlaps.

    A face that only rode with its plate has no row: it maps to itself. Each subducting face that ends at a moved
    trench is intersected with the endpoint faces of its own plate and with the segments the trench swept, all in
    that plate's reference frame, where its interior vertices have not moved at all.
    """
    sphere = network.sphere
    old = {name: i for i, name in enumerate(network.face_ids)}
    new = {name: i for i, name in enumerate(endpoint.face_ids)}
    before, after = _Shapes(network), _Shapes(endpoint)
    parties, donor, receiver, party, area = {}, [], [], [], []
    areas = endpoint.face_area_m2
    for face_id, boundary_id, side in moved.strips:
        donor.append(-1)
        receiver.append(new[face_id])
        party.append(parties.setdefault('ridge|%s|%s' % (boundary_id, side), len(parties)))
        area.append(float(areas[new[face_id]]))
    by_plate = {}
    for face_id, plate in moved.deformed:
        by_plate.setdefault(plate, []).append(face_id)
    for plate, ids in sorted(by_plate.items()):
        children = {face_id: after.rings(new[face_id]) for face_id in ids}
        caps = {face_id: _cap(rings) for face_id, rings in children.items()}
        quads = [(boundary_id, ring, _cap([ring])) for boundary_id, owner, ring in moved.swept if owner == plate]
        for face_id in ids:
            _check_cancel(cancel)
            rings = before.rings(old[face_id])
            centre, radius = _cap(rings)
            for other in ids:
                if float(_angle(centre, caps[other][0])) > radius+caps[other][1]:
                    continue
                value = _metres(_overlap_sr(rings, children[other], sphere, budget=budget), sphere)
                if value > 0:
                    donor.append(old[face_id])
                    receiver.append(new[other])
                    party.append(-1)
                    area.append(value)
            lost = {}
            for boundary_id, ring, (middle, reach) in quads:
                if float(_angle(centre, middle)) > radius+reach:
                    continue
                value = _metres(_overlap_sr(rings, [ring], sphere, budget=budget), sphere)
                if value > 0:
                    lost.setdefault(boundary_id, []).append(value)
            for boundary_id, values in sorted(lost.items()):
                donor.append(old[face_id])
                receiver.append(-1)
                party.append(parties.setdefault('trench|'+boundary_id, len(parties)))
                area.append(math.fsum(values))
            if len(area) > MAX_ROWS:
                raise TransferRefused('the overlap map exceeds its row limit; move a shorter interval')
    transient_measures = _transient_measures(moved, sphere)
    transient = tuple((parties.setdefault(birth, len(parties)), parties.setdefault(sink, len(parties)), value)
                      for (birth, sink), value in sorted(transient_measures.items()))
    # Only a sweep whose ordinary projected intersections miss the original swept-relative criterion needs M3.
    # Ordinary receiver overlaps retain their existing fast path; no acceptance threshold changes with precision.
    for boundary_id in sorted({boundary for boundary, _, _ in moved.swept}):
        label = 'trench|'+boundary_id
        quads = [(plate, ring) for boundary, plate, ring in moved.swept if boundary == boundary_id]
        swept = math.fsum(_ring_m2(ring, sphere) for _, ring in quads)
        booked = math.fsum(value for p, value in zip(party, area) if p >= 0 and tuple(parties)[p] == label)
        booked += math.fsum(value for (_, sink), value in transient_measures.items() if sink == label)
        if abs(booked-swept) <= RELATIVE_TOLERANCE*swept:
            continue
        retained = [i for i, p in enumerate(party) if p < 0 or tuple(parties)[p] != label]
        donor, receiver, party, area = ([values[i] for i in retained] for values in (donor, receiver, party, area))
        party_index = parties.setdefault(label, len(parties))
        for plate, ids in sorted(by_plate.items()):
            sweeps = [ring for owner, ring in quads if owner == plate]
            if not sweeps:
                continue
            sweep_caps = [_cap([ring]) for ring in sweeps]
            for face_id in ids:
                _check_cancel(cancel)
                rings = before.rings(old[face_id])
                value = _metres(_exact_sweep_sr(rings, sweeps, sphere, budget=budget,
                                                 sweep_caps=sweep_caps), sphere)
                if value > 0:
                    donor.append(old[face_id])
                    receiver.append(-1)
                    party.append(party_index)
                    area.append(value)
                    if len(area)+len(transient) > MAX_ROWS:
                        raise TransferRefused('the overlap map exceeds its row limit; move a shorter interval')
    return _Rows(tuple(donor), tuple(receiver), tuple(party), tuple(area), tuple(parties), transient)


def _transient_measures(moved, sphere):
    """Exact measured temporary surface grouped by its ridge-side birth and consuming trench."""
    grouped = {}
    for junction, ridge, side, trench, plate, ring in getattr(moved, 'transient', ()):
        if side not in SIDES:
            raise TransferRefused('a transient birth has no declared ridge side')
        grouped.setdefault(('ridge|'+ridge+'|'+side, 'trench|'+trench), []).append(_ring_m2(ring, sphere))
    return {key: math.fsum(values) for key, values in grouped.items()}


def _consumption_accuracy(network, material, moved, rows, supplies):
    """Public step diagnostic: actual sweep C7 bounds, propagated to amounts by donor areal density.

    These are cross-representation round-off diagnostics, never an allowance for rows missing their sweep. The
    latter still close at rho*swept. Undefined C7 is reported as unknown (None), not a zero error. Existing S1's
    approved fresh-control rule compares totals within rho*abs(total) plus the larger cumulative bound.
    """
    scale, width = network.sphere.radius_m**2, len(material.columns)
    by_trench = {}
    for boundary, _, ring in moved.swept:
        by_trench.setdefault(boundary, []).append(ring)
    row_totals = {}
    for source, area in zip(rows.donor, rows.area_m2):
        if source >= 0:
            row_totals.setdefault(source, []).append(area)
    held = {source: [] for source in row_totals}
    for source, stock in zip(material.piece_face, material.stock):
        if source in held:
            held[source].append(stock)
    amounts = {}
    for source in row_totals:
        total = math.fsum(row_totals[source])
        amounts[source] = [math.fsum(abs(float(stock[k])) for stock in held[source])/total for k in range(width)]
    result = {}
    for boundary, rings in sorted(by_trench.items()):
        measured = math.fsum(_ring_m2(ring, network.sphere) for ring in rings)
        terms = []
        for ring in rings:
            area_sr = _exact_ring_sr(ring)
            ceiling = _c7_range_limit([ring], area_sr, area_sr=area_sr)
            value = _sphere._measure_bound([ring])
            terms.append(0. if ceiling == 0. else None if value is None else min(value, ceiling))
        bound = None if any(value is None for value in terms) else math.fsum(terms)*scale
        donors = {source for source, target, party in zip(rows.donor, rows.receiver, rows.party)
                  if source >= 0 and target < 0 and rows.parties[party] == 'trench|'+boundary}
        density = [max((amounts[source][k] for source in donors), default=0.) for k in range(width)]
        for birth, sink, _ in rows.transient:
            if rows.parties[sink] != 'trench|'+boundary:
                continue
            ridge, side = rows.parties[birth][len('ridge|'):].rsplit('|', 1)
            supply = supplies[ridge, side]
            values = [1.]+[v for _, v in supply.mass_per_area_kg_m2]+[v for _, v in supply.thickness_m]
            if material.enthalpy_basis is not None:
                values.append(supply.enthalpy_per_area_j_m2)
            density = [max(a, abs(b)) for a, b in zip(density, values)]
        result[boundary] = dict(swept_area_m2=measured, sweep_c7_m2=bound,
                               account_roundoff={column: None if bound is None else bound*density[k]
                                                 for k, column in enumerate(material.columns)})
    return result


def _closed(total, expected, label, bound=0.):
    """Refuse unless rows close on their face within the existing tolerance or, where it is larger, the face's
    thin-face bound (C7): the largest rounding the measurement of these operands could have made."""
    if not abs(total-expected) <= max(RELATIVE_TOLERANCE*expected, bound):
        raise TransferRefused('%s: its overlap rows sum to %r m2 but its measured area is %r m2 (unresolved '
                              'overlap)' % (label, total, expected), UNRESOLVED_OVERLAP)


def _well_formed(rows, donors, receivers):
    if (len({len(rows.donor), len(rows.receiver), len(rows.party), len(rows.area_m2)}) != 1
            or len(rows.area_m2) > MAX_ROWS or any(not (math.isfinite(a) and a > 0) for a in rows.area_m2)
            or any(not -1 <= d < donors for d in rows.donor) or any(not -1 <= r < receivers for r in rows.receiver)
            or any(not -1 <= p < len(rows.parties) for p in rows.party)
            or len(set(zip(rows.donor, rows.receiver, rows.party))) != len(rows.area_m2)):
        raise TransferRefused('the overlap rows are not well formed')
    if (len(rows.transient)+len(rows.area_m2) > MAX_ROWS
            or any(len(row) != 3 or type(row[0]) is not int or type(row[1]) is not int
                   or not 0 <= row[0] < len(rows.parties) or not 0 <= row[1] < len(rows.parties)
                   or not (math.isfinite(row[2]) and row[2] > 0) for row in rows.transient)
            or len({row[:2] for row in rows.transient}) != len(rows.transient)):
        raise TransferRefused('the transient source-to-sink rows are not well formed')


def _audited(network, endpoint, moved, rows):
    """Check motion rows against the geometry they claim to measure, whether just measured or read from a store.

    Births go exactly into the faces born in the interval, with exactly their measured areas; every other row leaves
    a subducting face that ends at a moved trench, for another such face of its plate or for a trench that consumes
    its plate. Every donor's rows close on its measured area, every receiving face is filled, and each trench
    consumes exactly what it swept, within the original relative tolerance of the swept area. A targeted exact
    clipping/measure fallback resolves the cancellation of tiny sweeps; the boundary cells never set the tolerance.
    """
    _well_formed(rows, len(network.face_ids), len(endpoint.face_ids))
    sphere = network.sphere
    old = {name: i for i, name in enumerate(network.face_ids)}
    new = {name: i for i, name in enumerate(endpoint.face_ids)}
    born = {new[face_id]: 'ridge|%s|%s' % (boundary_id, side) for face_id, boundary_id, side in moved.strips}
    plate_of = {old[face_id]: plate for face_id, plate in moved.deformed}
    target_plate = {new[face_id]: plate for face_id, plate in moved.deformed}
    eats = {}
    for boundary_id, plate, ring in moved.swept:
        name = 'trench|'+boundary_id
        eats.setdefault(name, (plate, []))[1].append(_ring_m2(ring, sphere))
    before, after, reach = _Shapes(network), _Shapes(endpoint), {}

    def cap(index, parent):
        """The bounding cap of a parent face or of an endpoint face, in their plate's reference frame."""
        if (index, parent) not in reach:
            reach[index, parent] = _cap(before.rings(index) if parent else after.rings(index))
        return reach[index, parent]

    given, received, consumed, seen = {}, {}, {}, set()
    actual_transient = {(rows.parties[b], rows.parties[s]): value for b, s, value in rows.transient}
    if actual_transient != _transient_measures(moved, sphere):
        raise TransferRefused('the transient source-to-sink rows do not match their swept birth polygons')
    for (_, sink), value in actual_transient.items():
        if sink not in eats:
            raise TransferRefused('a transient row names a trench with no swept region')
        consumed.setdefault(sink, []).append(value)
    for source, target, party, area in zip(rows.donor, rows.receiver, rows.party, rows.area_m2):
        name = None if party < 0 else rows.parties[party]
        if source < 0:
            if born.get(target) != name or target in seen or area != float(endpoint.face_area_m2[target]):
                raise TransferRefused('a birth row does not match a face born in this interval and its measured '
                                      'area')
            seen.add(target)
            continue
        if source not in plate_of:
            raise TransferRefused('an overlap row leaves a face that only rode with its plate')
        given.setdefault(source, []).append(area)
        if target < 0:
            if name not in eats or eats[name][0] != plate_of[source]:
                raise TransferRefused('a consumption row names a trench that does not consume that plate')
            consumed.setdefault(name, []).append(area)
        elif name is not None or target_plate.get(target) != plate_of[source]:
            raise TransferRefused('an overlap row joins faces of different plates or a face that did not change')
        else:
            (here, reach_here), (there, reach_there) = cap(source, True), cap(target, False)
            if float(_angle(here, there)) > reach_here+reach_there:
                raise TransferRefused('an overlap row joins two faces that cannot overlap: unresolved overlap',
                                      UNRESOLVED_OVERLAP)
            received.setdefault(target, []).append(area)
    if seen != set(born):
        raise TransferRefused('a face born in this interval has no birth row')
    for source in plate_of:
        _closed(math.fsum(given.get(source, [0.])), float(network.face_area_m2[source]),
                'face %r' % network.face_ids[source])
    for target in target_plate:
        _closed(math.fsum(received.get(target, [0.])), float(endpoint.face_area_m2[target]),
                'endpoint face %r' % endpoint.face_ids[target])
    for name, (_, swept) in eats.items():
        total, taken = math.fsum(swept), math.fsum(consumed.get(name, [0.]))
        if not abs(taken-total) <= RELATIVE_TOLERANCE*total:
            raise TransferRefused('%s sweeps %r m2 but its subducting plate holds only %r m2 there: the finite stock '
                                  'of its boundary cells is exhausted; refused, never clipped'
                                  % (name.replace('|', ' '), total, taken))


def _same_face(first, i, second, j):
    """True when two networks hold the same face: the same plate and rings at the same directions."""
    a, b = first.network.atlas.patches[i], second.network.atlas.patches[j]
    if a.rings != b.rings or a.plate_id != b.plate_id:
        return False
    return all(np.array_equal(x, y) for x, y in zip(first.rings(i), second.rings(j)))


def _changed(parent, endpoint):
    """(parent shapes, endpoint shapes, changed parent face indices, changed endpoint face indices)."""
    before, after = _Shapes(parent), _Shapes(endpoint)
    new = {name: i for i, name in enumerate(endpoint.face_ids)}
    same = {i for i, name in enumerate(parent.face_ids) if name in new and _same_face(before, i, after, new[name])}
    kept = {new[parent.face_ids[i]] for i in same}
    return (before, after, [i for i in range(len(parent.face_ids)) if i not in same],
            [j for j in range(len(endpoint.face_ids)) if j not in kept])


def _mesh_rows(parent, endpoint, cancel, *, budget=None):
    """Measure the rows of a mesh change: every changed parent face against the new faces of its plate.

    Where one face lies wholly within the other, decided exactly (_nested), the row is the inner face's own measured
    area and nothing is clipped: the inner face has no other row. A renamed face, and a thin face merged into or split
    from a compact one, therefore close. A closure whose outer face is itself thin still carries that face's evaluation
    error: it is held to the relative tolerance, or, when every row is a whole face, to the C7 bound
    (_whole_face_bounds). Every other pair is clipped (_overlap_sr).
    """
    sphere = parent.sphere
    before, after, donors, receivers = _changed(parent, endpoint)
    rings = {j: after.rings(j) for j in receivers}
    caps = {j: _cap(value) for j, value in rings.items()}
    pairs, mine = [], {}
    for i in donors:
        mine[i] = before.rings(i)
        centre, radius = _cap(mine[i])
        plate = parent.atlas.patches[i].plate_id
        pairs.extend((i, j) for j in receivers if endpoint.atlas.patches[j].plate_id == plate
                     and float(_angle(centre, caps[j][0])) <= radius+caps[j][1])
    rows, whole = {}, set()
    for i, j in pairs:
        if (i, None) in whole or (None, j) in whole:
            continue
        _check_cancel(cancel)
        inside, around = _nested(mine[i], rings[j])
        if inside or around:
            rows[i, j] = float(parent.face_area_m2[i] if inside else endpoint.face_area_m2[j])
            whole.update(((i, None),) if inside else ())
            whole.update(((None, j),) if around else ())
    for i, j in pairs:
        if (i, j) in rows or (i, None) in whole or (None, j) in whole:
            continue
        _check_cancel(cancel)
        value = _metres(_overlap_sr(mine[i], rings[j], sphere, budget=budget), sphere)
        if value > 0:
            rows[i, j] = value
        if len(rows) > MAX_ROWS:
            raise TransferRefused('the overlap map exceeds its row limit; change the mesh in smaller parts')
    keys = sorted(rows)
    return _Rows(tuple(i for i, _ in keys), tuple(j for _, j in keys), (-1,)*len(keys),
                 tuple(rows[key] for key in keys), ())


# I03a-2 C7 (approved 3 October 2026): the derived bound replaces the relative criterion only for faces too thin to meet
# it, area over perimeter below R3-1's 1.1e-4 rad; up to twice that ratio (the range the approval flags) it may admit
# up to twice rho mu, and above it the existing criterion alone applies, with no bound and no allowance (D7').
THIN_FACE_RATIO = 1.1e-4


def _c7_range_limit(rings, area, *, area_sr=None):
    """Approved C7 range ceiling, in the units of ``area``; no new criterion."""
    perimeter = math.fsum(float(_angle(a, b)) for ring in rings for a, b in zip(ring, np.roll(ring, -1, axis=0)))
    measured = abs(_sphere._measure(rings)) if area_sr is None else area_sr
    ratio = measured/perimeter if perimeter else 0.
    return math.inf if ratio < THIN_FACE_RATIO else 2*RELATIVE_TOLERANCE*area if ratio < 2*THIN_FACE_RATIO else 0.


def _whole_face_bounds(parent, endpoint, before, after, triples):
    """(donor bounds, receiver bounds, receiver ceilings) in m2 of the thin-face criterion C7 (whole-face rows only).


    A whole-face row is one whose faces nest, decided exactly (_nested), and whose area is the inner face's own
    measured area. A closure of face F made only of such rows compares measured faces with measured faces, so its
    discrepancy is at most E = e(F) + sum_k e(inner face of row k), each e the derived rounding bound of _measure
    (integration_sphere._measure_bound). E is used only within the approved range: in full where F's area over
    perimeter is below THIN_FACE_RATIO, up to 2 rho mu(F) below twice that ratio, and not at all above it. Any closure
    with a clipped row, or a face outside the bound's derivation, keeps the existing relative criterion alone (bound
    0). A receiver's ceiling is the same range limit, which caps its occupancy allowance (D7'). Everything here is
    recomputed from the faces' rings and the rows, the same way when a step is measured and when it is restored.
    """
    scale = parent.sphere.radius_m*parent.sphere.radius_m
    cache = {}

    def bound(key):
        if key not in cache:
            rings = before.rings(key[1]) if key[0] == 'parent' else after.rings(key[1])
            value = _sphere._measure_bound(rings)
            cache[key] = None if value is None else value*scale
        return cache[key]

    inner, given, received = [], {}, {}
    for k, (source, target, area) in enumerate(triples):
        inside, around = _nested(before.rings(source), after.rings(target))
        if inside and area == float(parent.face_area_m2[source]):
            inner.append(('parent', source))
        elif around and area == float(endpoint.face_area_m2[target]):
            inner.append(('endpoint', target))
        else:
            inner.append(None)
        given.setdefault(source, []).append(k)
        received.setdefault(target, []).append(k)

    def cap(own):
        rings = before.rings(own[1]) if own[0] == 'parent' else after.rings(own[1])
        area = float((parent if own[0] == 'parent' else endpoint).face_area_m2[own[1]])
        return _c7_range_limit(rings, area)

    def closure(own, members):
        if any(inner[k] is None for k in members):
            return 0.
        parts = [bound(own)]+[bound(inner[k]) for k in members]
        return 0. if any(part is None for part in parts) else min(math.fsum(parts), cap(own))
    return ({source: closure(('parent', source), members) for source, members in given.items()},
            {target: closure(('endpoint', target), members) for target, members in received.items()},
            {target: cap(('endpoint', target)) for target in received})


def _audited_mesh(parent, endpoint, rows, ceilings=False):
    """Check mesh rows: the same physical network on other faces, and rows that close on both meshes.

    Returns the thin-face bounds of the closures (donor, receiver; _whole_face_bounds) and, with ``ceilings``, the
    receivers' ceilings too, from which the transfer sets each receiving face's occupancy allowance (D7').
    """
    if rows.transient:
        raise TransferRefused('a mesh change cannot create or consume transient surface')
    if ((endpoint.sphere, endpoint.epoch_id, endpoint.time_s, endpoint.step, endpoint.reference_time_s,
         endpoint.plates, endpoint.boundaries, endpoint.lineage)
            != (parent.sphere, parent.epoch_id, parent.time_s, parent.step, parent.reference_time_s, parent.plates,
                parent.boundaries, parent.lineage)):
        raise TransferRefused('a mesh change keeps the plates, boundary records, time and lineage of its network')
    _well_formed(rows, len(parent.face_ids), len(endpoint.face_ids))
    before, after, donors, receivers = _changed(parent, endpoint)
    given, received, reach = {i: [] for i in donors}, {j: [] for j in receivers}, {}
    for source, target, party, area in zip(rows.donor, rows.receiver, rows.party, rows.area_m2):
        if (party != -1 or source not in given or target not in received
                or parent.atlas.patches[source].plate_id != endpoint.atlas.patches[target].plate_id):
            raise TransferRefused('a mesh row joins faces of different plates, an unchanged face or an exterior')
        for key, shapes in ((source, before), (~target, after)):
            if key not in reach:
                reach[key] = _cap(shapes.rings(key if shapes is before else target))
        (here, reach_here), (there, reach_there) = reach[source], reach[~target]
        if float(_angle(here, there)) > reach_here+reach_there:
            raise TransferRefused('a mesh row joins two faces that cannot overlap: unresolved overlap',
                                  UNRESOLVED_OVERLAP)
        given[source].append(area)
        received[target].append(area)
    donor_bound, receiver_bound, ceiling = _whole_face_bounds(parent, endpoint, before, after,
                                                              list(zip(rows.donor, rows.receiver, rows.area_m2)))
    for source, values in given.items():
        _closed(math.fsum(values), float(parent.face_area_m2[source]), 'face %r' % parent.face_ids[source],
                donor_bound.get(source, 0.))
    for target, values in received.items():
        _closed(math.fsum(values), float(endpoint.face_area_m2[target]),
                'endpoint face %r' % endpoint.face_ids[target], receiver_bound.get(target, 0.))
    return (donor_bound, receiver_bound, ceiling) if ceilings else (donor_bound, receiver_bound)


def _meshed(network, mesh, limits, budget, cancel):
    """The network with its sampling faces replaced; plates, boundary records and time are unchanged.

    An added vertex lies inside one plate and is kept in that plate's reference frame. A face may use another plate's
    vertex only where its plate already keeps a copy of it, so a mesh cannot reach across a boundary.
    """
    if type(mesh) is not Mesh:
        raise TransferRefused('a stored mesh identity cannot be applied; its endpoint is read from its store')
    layout = network._layout
    known = dict(zip(layout.names, layout.home))
    for name, _ in mesh.vertices:
        if name in known:
            raise TransferRefused('an added mesh vertex reuses the identity %r' % name)
    added = dict(mesh.vertices)
    used = {name for face in mesh.faces for ring in (face.vertex_ids, *face.holes) for name in ring}
    if not used <= set(known) | set(added):
        raise TransferRefused('a mesh face names an unknown vertex')
    unused = [name for name, _ in mesh.vertices if name not in used]
    if unused:
        raise TransferRefused('no face uses the added mesh vertex %r: a mesh declares only the vertices it uses'
                              % min(unused))
    if {face.face_id for face in mesh.faces} & set(network.lineage.retired_face_ids):
        raise TransferRefused('a mesh face reuses a retired identity')
    plates_of = {}
    for name, plate in _sphere._used(mesh.faces):
        plates_of.setdefault(name, set()).add(plate)
    frames = dict(layout.frames)
    homes, reference = {}, {}
    index = {name: i for i, name in enumerate(layout.names)}
    for name in sorted(used):
        if name in added:
            if len(plates_of[name]) != 1:
                raise TransferRefused('the added mesh vertex %r lies on a plate boundary: a mesh cannot subdivide a '
                                      'boundary record' % name)
            (plate,) = plates_of[name]
            homes[name] = plate
            reference[name] = _turned(frames[plate].inverse(), np.asarray(added[name], dtype=np.float64))[0]
        else:
            homes[name] = known[name]
            reference[name] = layout.reference[index[name]]
    views = dict(layout.views)
    missing = sorted(pair for pair in _sphere._used(mesh.faces) if homes[pair[0]] != pair[1] and pair not in views)
    if missing:
        raise TransferRefused('a mesh face of plate %r uses vertex %r, which that plate does not keep: a mesh cannot '
                              'move or subdivide a physical interface' % (missing[0][1], missing[0][0]))
    names = tuple(sorted(used))
    endpoint = _sphere._Layout(names, tuple(homes[name] for name in names),
                               np.asarray([reference[name] for name in names], dtype=np.float64),
                               tuple(sorted((pair, views[pair]) for pair in _sphere._used(mesh.faces)
                                            if homes[pair[0]] != pair[1])),
                               layout.frames, layout.ridges, layout.poles)
    try:
        return _sphere._network(network.sphere, endpoint, mesh.faces, network.plates, network.boundaries,
                                network.epoch_id, network.time_s, network.step, network.reference_time_s,
                                network.lineage, limits, budget, cancel, False)
    except ExchangeRefused:
        raise
    except TectonicsError as exc:
        raise TransferRefused('the new mesh is not a valid closed network with the same physical interfaces: '
                              + str(exc)) from exc


# ----------------------------------------------------------------------------- exact transfer of the accounts

def _fractions(values):
    return [Fraction(float(x)) for x in values]


def _split(value, areas, total, largest):
    """Divide one exact value among rows in proportion to their measured areas, exactly and in binary.

    Every row but the largest receives the correctly rounded binary64 value of its exact share value*area/total; the
    largest receives the exact remainder. The parts therefore sum to ``value`` exactly, each is a binary fraction
    (so the exact accounts stay bounded), and none differs from its exact share by more than the rounding of the
    others. A single row receives the value itself.
    """
    parts = [None if k == largest else Fraction(float(value*area/total)) for k, area in enumerate(areas)]
    parts[largest] = value-sum((part for part in parts if part is not None), Fraction(0))
    return parts


def _largest(areas):
    return max(range(len(areas)), key=lambda k: (areas[k], -k))


def _birth_totals(material, supply, area):
    """What a supply delivers for ``area`` (exact, m2) of new surface: one correctly rounded total per account."""
    phases = material.phases
    if tuple(p for p, _ in supply.mass_per_area_kg_m2) != phases or tuple(p for p, _ in supply.thickness_m) != phases:
        raise TransferRefused('the supply of ridge %r declares other phases than the network carries (incompatible '
                              'support)' % supply.boundary_id, INCOMPATIBLE_SUPPORT)
    if (supply.enthalpy_per_area_j_m2 is None) != (material.enthalpy_basis is None):
        raise TransferRefused('the supply of ridge %r gives signed enthalpy exactly when the network carries it '
                              '(incompatible support)' % supply.boundary_id, INCOMPATIBLE_SUPPORT)
    per_area = ([value for _, value in supply.mass_per_area_kg_m2]+[value for _, value in supply.thickness_m]
                + ([] if material.enthalpy_basis is None else [supply.enthalpy_per_area_j_m2]))
    totals = []
    for value in per_area:
        total = Fraction(value)*area
        if abs(total) > EXACT_LIMIT:
            raise TransferRefused('a supplied account would leave the finite accounting range')
        totals.append(float(total))
    return totals


def _transferred(network, material, endpoint, rows, supplies, sinks, interval, stored_births=None, *, budget=None,
                 bounds=None):
    """Apply overlap rows to the parent's material in exact arithmetic.

    Returns (endpoint material, I02 stock transfers, birth records, return records). Pieces of faces that are no
    row's donor are carried with their exact stored values. Every other piece is divided among its face's rows in
    proportion to their measured areas (_split), so each donor is debited once and completely and every part is an
    exact binary fraction. A birth row creates a piece of the interval's new cohort with exactly its measured area
    and its part of the supply's total. A paired transient birth/consumption row shares that same allocation, books
    both source and trench legs, and leaves no endpoint piece. Its cohort and exact amounts remain in the birth
    record, including the formation interval, and both finite-stock legs share the interval's atomic commit.
    Changed values are rounded once; each difference enters the exact rounding
    account within its exact allowance. ``bounds`` holds the thin-face bounds of the rows' closures and the
    receivers' ceilings (_whole_face_bounds), from which each endpoint face's occupancy allowance follows (rule D7',
    the proposal's addendum after the coordinator withdrew the cumulative D7 on 3 October 2026). Exactly,
    d(X) = c'_X + sum_r w_r (c_s + d(s)) for pieces moved by whole-face rows; the part one step introduces is bounded
    by that step's own measures, E_X + sum_s w_s E_s, and the inherited part has no bound in current measures, so it
    is not carried:
    - a rename (X's only row comes from a donor with only that row, equal to both measured areas bit for bit) leaves
      d unchanged, and X keeps its donor's allowance;
    - any other receiver of mesh rows gets min(E_X + sum_s w_s E_s, its ceiling), never added to an earlier allowance;
    - a face that only rides keeps its allowance; a face given pieces by clipped rows (motion) gets none.
    """
    width, count = len(material.columns), len(material.phases)
    exteriors, link = dict(material.exteriors), material.stock_link
    old_ids, new_index = network.face_ids, {name: i for i, name in enumerate(endpoint.face_ids)}
    start_s, end_s, start_step, end_step = interval
    donors, born = {}, {}
    for row, source in enumerate(rows.donor):
        if source >= 0:
            donors.setdefault(source, []).append(row)
        else:
            born.setdefault(rows.parties[rows.party[row]], []).append(
                (rows.receiver[row], None, Fraction(rows.area_m2[row])))
    for birth_party, sink_party, area in rows.transient:
        # A measured junction triangle is supplied and consumed within the interval. It has a source and a sink,
        # but no endpoint face. Its two legs share one exact area and one allocation of the ridge-side supply.
        trench = rows.parties[sink_party]
        born.setdefault(rows.parties[birth_party], []).append((None, trench[len('trench|'):], Fraction(area)))
    supplied = {name: list(values) for name, values in material._supplied}
    rounding, allowance = list(material._rounding), list(material._allowance)

    def book(name, column, amount):
        supplied.setdefault(name, [Fraction(0)]*width)[column] += amount

    cohort_ids = [cohort.cohort_id for cohort in material.cohorts]
    cohorts = {cohort.cohort_id: cohort for cohort in material.cohorts}
    kept, exact, legs, eaten = {}, {}, {}, set()

    def consume(moved, boundary_id):
        """Book an exact piece through its trench, including a piece born earlier in this same interval."""
        eaten.add(boundary_id)
        if boundary_id not in sinks:
            raise TransferRefused('trench %r consumes material but no destination is declared for it' % boundary_id)
        book('trench|'+boundary_id, 0, -moved[0])
        for destination, fraction, stocked in sinks[boundary_id].destinations:
            part = Fraction(fraction)
            if stocked:
                if link is None or link['returns'] is None:
                    raise TransferRefused('destination %r is a finite stock, but the network declares no stock '
                                          'link to return through' % destination)
                leg = legs.setdefault((boundary_id, destination), [Fraction(0)]*width)
                for column in range(1, width):
                    leg[column] += moved[column]*part
            else:
                if exteriors.get(destination) != 'sink':
                    raise TransferRefused('destination %r is not a declared exterior sink of the network' % destination)
                for column in range(1, width):
                    book(destination, column, -moved[column]*part)

    face, cohort, stock = material._face, material._cohort, material._stock
    for piece in range(len(face)):
        source, name = int(face[piece]), cohort_ids[int(cohort[piece])]
        if source not in donors:
            if old_ids[source] not in new_index:
                raise TransferRefused('face %r disappears without any overlap row: unresolved overlap'
                                      % old_ids[source], UNRESOLVED_OVERLAP)
            kept[new_index[old_ids[source]], name] = stock[piece]
            continue
        areas = [Fraction(rows.area_m2[row]) for row in donors[source]]
        total, largest = sum(areas, Fraction(0)), _largest(areas)
        parts = [_split(value, areas, total, largest) for value in _fractions(stock[piece])]
        for k, row in enumerate(donors[source]):
            moved = [column[k] for column in parts]
            target = rows.receiver[row]
            if target >= 0:
                slot = exact.setdefault((target, name), [Fraction(0)]*width)
                for column in range(width):
                    slot[column] += moved[column]
                continue
            trench = rows.parties[rows.party[row]]
            boundary_id = trench[len('trench|'):]
            consume(moved, boundary_id)
    # Births: one new cohort per ridge side and interval, shared by every face born on that side.
    records = []
    for name in sorted(born):
        side = name.rsplit('|', 1)[1]
        boundary_id = name[len('ridge|'):-len('|'+side)]
        supply = supplies.get((boundary_id, side))
        if supply is None:
            raise TransferRefused('ridge %r opens on its %s side but no supply is declared for it: new material '
                                  'needs an actual source' % (boundary_id, side))
        if supply.stock:
            if link is None or link['receives'] is None:
                raise TransferRefused('supply %r is a finite stock, but the network declares no stock link to '
                                      'receive through' % supply.source)
        elif exteriors.get(supply.source) != 'source':
            raise TransferRefused('supply %r is not a declared exterior source of the network' % supply.source)
        area = sum((value for _, _, value in born[name]), Fraction(0))
        totals = _birth_totals(material, supply, area)
        if stored_births is not None and stored_births.get(name) != totals:
            raise TransferRefused('a stored supply total is not its declared areal value times the born area')
        cohort_id = '%s|%s|%d-%d' % (boundary_id, side, start_step, end_step)
        if cohort_id in cohorts or len(cohort_id) > 256:
            raise TransferRefused('the derived cohort identity %r is already in use or too long' % cohort_id)
        cohorts[cohort_id] = Cohort(cohort_id, supply.material_id, supply.origin_id, start_s, end_s,
                                    supply.history_id)
        source_name = 'stock|'+supply.source if supply.stock else supply.source
        book(name, 0, area)                                           # new area comes from the ridge record
        for column, total in enumerate(totals, start=1):
            book(source_name, column, Fraction(total))
        areas = [value for _, _, value in born[name]]
        parts = [_split(Fraction(total), areas, area, _largest(areas)) for total in totals]
        transient_records = []
        for k, (target, trench, _) in enumerate(born[name]):
            moved = [areas[k]]+[column[k] for column in parts]
            if trench is None:
                exact[target, cohort_id] = moved
            else:
                consume(moved, trench)
                transient_records.append(dict(boundary_id=trench, area_m2=_exact_text(areas[k]),
                                              amounts=[_exact_text(value) for value in moved]))
        record = dict(party=name, boundary_id=boundary_id, side=side, cohort_id=cohort_id,
                      source=supply.source, stock=supply.stock, area_m2=_exact_text(area), totals=totals, label=None)
        if transient_records:
            record['transient_consumption'] = transient_records
        records.append(record)
    if set(sinks)-eaten:
        raise TransferRefused('a destination is declared for %r, which consumes nothing in this interval'
                              % min(set(sinks)-eaten))
    opened = {(record['boundary_id'], record['side']) for record in records}
    if set(supplies)-opened:
        unused = min(set(supplies)-opened)
        raise TransferRefused('a supply is declared for the %s side of %r, which opens nothing in this interval'
                              % (unused[1], unused[0]))
    # Finite stocks: one I02 Transfer per supply and per (trench, destination), committed with this step.
    transfers, returned = [], []

    def transfer(kind, key, donor, receiver, masses, heat):
        label = 'i03.'+hashlib.sha256(_json([PRODUCER, kind, list(key), start_step, end_step])).hexdigest()[:40]
        try:
            return Transfer(label=label, producer=PRODUCER, donor=donor, receiver=receiver,
                            component_mass_kg=tuple(zip(material.phases, masses)), enthalpy_j=heat,
                            basis=material.enthalpy_basis, start_step=start_step, end_step=end_step)
        except TectonicsError as exc:
            raise TransferRefused('a finite-stock transfer of the network is not admissible: '+str(exc)) from exc

    for record in records:
        if record['stock']:
            totals = record['totals']
            transfers.append(transfer('birth', (record['boundary_id'], record['side']), record['source'],
                                      link['receives'], totals[:count], totals[-1]))
            record['label'] = transfers[-1].label
    for (boundary_id, destination), leg in sorted(legs.items()):
        name, sent = 'stock|'+destination, [0.]*width
        for column in range(1, width):
            if count < column <= 2*count:                             # phase volume has no W08 account
                book(name, column, -leg[column])
                continue
            sent[column] = float(leg[column])
            book(name, column, -Fraction(sent[column]))
            if Fraction(sent[column]) != leg[column]:
                rounding[column] += Fraction(sent[column])-leg[column]
                allowance[column] += Fraction(math.ulp(sent[column]))/2
        transfers.append(transfer('consumption', (boundary_id, destination), link['returns'], destination,
                                  sent[1:1+count], sent[-1]))
        returned.append(dict(boundary_id=boundary_id, destination=destination, label=transfers[-1].label,
                             totals=sent[1:1+count]+[sent[-1]]))
    # Assemble the endpoint pieces: untouched rows keep their bytes, changed rows are rounded once.
    ordered = tuple(sorted(cohorts))
    position = {name: i for i, name in enumerate(ordered)}
    keys = sorted(set(kept) | set(exact), key=lambda key: (key[0], position[key[1]]))
    out, chosen = np.empty((len(keys), width), dtype=np.float64), []
    for index, key in enumerate(keys):
        if key not in exact:
            out[index] = kept[key]
            chosen.append(index)
            continue
        values = list(exact[key])
        if key in kept:
            values = [a+b for a, b in zip(values, _fractions(kept[key]))]
        if values[0] == 0:
            if any(value != 0 for value in values):
                raise TransferRefused('a piece without area would keep material: unresolved overlap',
                                      UNRESOLVED_OVERLAP)
            continue
        for column, value in enumerate(values):
            if abs(value) > EXACT_LIMIT:
                raise TransferRefused('a piece account would leave the finite accounting range')
            stored = float(value)
            out[index, column] = stored
            if Fraction(stored) != value:
                rounding[column] += Fraction(stored)-value
                allowance[column] += Fraction(math.ulp(stored))/2
        chosen.append(index)
    face = np.array([keys[i][0] for i in chosen], dtype=np.int64)
    donor_bound, receiver_bound, ceiling = ({}, {}, {}) if bounds is None else bounds
    previous, slack = material._occupancy_allowance, np.zeros(len(endpoint.face_ids))
    into = {}
    for row, target in enumerate(rows.receiver):
        if target >= 0:
            into.setdefault(target, []).append(row)
    renamed = {}
    for target, members in into.items():
        if len(members) == 1:
            row = members[0]
            source = rows.donor[row]
            if (source >= 0 and donors.get(source) == [row] and rows.area_m2[row] == float(network.face_area_m2[source])
                    == float(endpoint.face_area_m2[target])):
                renamed[target] = source
    for source, name in enumerate(old_ids):
        if source in donors:
            share = donor_bound.get(source, 0.)
            total = math.fsum(rows.area_m2[row] for row in donors[source])
            for row in donors[source]:
                target = rows.receiver[row]
                if share and target >= 0 and target not in renamed:
                    slack[target] += rows.area_m2[row]/total*share
        elif name in new_index:
            slack[new_index[name]] += float(previous[source])
    for target, value in receiver_bound.items():
        if target not in renamed:
            slack[target] += value
    for target, source in renamed.items():
        slack[target] = float(previous[source])
    for target, value in ceiling.items():
        if target not in renamed:
            slack[target] = min(slack[target], value)
    try:
        # Every face, including those that only rode, is measured against its pieces after every interval. Rows that
        # each close within the tolerance can still deliver pieces that miss a face's measured area by more than it,
        # when a face is too thin for its area to be defined that well: the overlap is unresolved.
        _sphere._occupancy(endpoint, face, out[chosen], None, slack)
    except TectonicsError as exc:
        raise TransferRefused('the transferred pieces do not fill an endpoint face: %s: unresolved overlap' % exc,
                              UNRESOLVED_OVERLAP) from exc
    try:
        result = _sphere._material(
            endpoint, material.phases, material.enthalpy_basis, tuple(cohorts[name] for name in ordered),
            material.exteriors, link, face,
            np.array([position[keys[i][1]] for i in chosen], dtype=np.int64), out[chosen], material._initial,
            tuple((name, tuple(values)) for name, values in supplied.items()), tuple(rounding), tuple(allowance),
            budget, (), slack)                                      # every face was measured just above
    except ExchangeRefused:
        raise
    except TectonicsError as exc:
        raise TransferRefused('the transferred material cannot be issued on the endpoint faces: '+str(exc)) from exc
    return result, tuple(transfers), records, returned


# ----------------------------------------------------------------------------- the step

@dataclass(frozen=True, init=False, eq=False, slots=True)
class OverlapMap(_state._Immutable):
    """The measured overlap rows of one step, bound to the geometries they were measured between.

    A prepared map replaces the measurement of another call only while the parent, moved and endpoint geometry
    identities and the motion all match; anything else is a stale map and is refused.
    """
    parent_geometry_id: str
    moved_geometry_id: str
    endpoint_geometry_id: str
    motion_id: str
    map_id: str
    _motion: _Rows = field(repr=False)
    _mesh: object = field(repr=False)
    _added: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('OverlapMap is issued by advance() only')

    @property
    def rows(self):
        """Motion rows as (donor face index, receiver face index, party name or None, area in m2)."""
        rows = self._motion
        return tuple((d, r, None if p < 0 else rows.parties[p], a)
                     for d, r, p, a in zip(rows.donor, rows.receiver, rows.party, rows.area_m2))

    @property
    def mesh_rows(self):
        """Mesh-change rows as (donor face index, receiver face index, area in m2); empty without a mesh change."""
        rows = self._mesh
        return () if rows is None else tuple(zip(rows.donor, rows.receiver, rows.area_m2))

    def arrays(self):
        out = self._motion.arrays('sphere.map_')
        if self._mesh is not None:
            out.update(self._mesh.arrays('sphere.remap_'))
            out['sphere.remap_vertex_direction'] = self._added
        return out


def _added_directions(motion):
    """The declared directions of a mesh's added vertices, in ID order: what restoration rebuilds the mesh from."""
    rows = [value for _, value in motion.mesh.vertices] if type(motion.mesh) is Mesh else []
    return _sphere._frozen(np.asarray(rows, dtype=np.float64).reshape(-1, 3), np.float64)


def _map(parent, moved, endpoint, motion, rows, mesh_rows):
    record = dict(schema=MAP_SCHEMA, parent_geometry_id=parent.atlas.geometry_id,
                  moved_geometry_id=moved.atlas.geometry_id, endpoint_geometry_id=endpoint.atlas.geometry_id,
                  motion_id=motion.motion_id, parties=list(rows.parties))
    added = None if mesh_rows is None else _added_directions(motion)
    item = _state._issue(OverlapMap, parent_geometry_id=record['parent_geometry_id'],
                         moved_geometry_id=record['moved_geometry_id'],
                         endpoint_geometry_id=record['endpoint_geometry_id'], motion_id=motion.motion_id, map_id='',
                         _motion=rows, _mesh=mesh_rows, _added=added)
    digest = hashlib.sha256(_json(record))
    for name, array in sorted(item.arrays().items()):
        digest.update(b'\0'+_json([name, array.dtype.str, list(array.shape)]))
        digest.update(array.tobytes())
    object.__setattr__(item, 'map_id', digest.hexdigest())
    return item


@dataclass(frozen=True, init=False, eq=False, slots=True)
class Step(_state._Immutable):
    """One computed step: the successor state, the overlap map that produced it and its finite-stock transfers.

    ``state`` is the accepted successor (issued as computed). ``stock_transfers`` are the I02 Transfer proposals
    that debit or credit finite stocks for this step; the ledger commits them in the same transaction.
    """
    parent_state_id: str
    state: object
    motion: Motion
    map: OverlapMap
    stock_transfers: tuple
    _record: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('Step is issued by advance() only')

    def record(self):
        """The step record a commit stores: the motion, what it did and the successor state's descriptor."""
        return dict(json.loads(self._record), state=self.state.descriptor())

    def summary(self):
        """The step record without the successor's descriptor."""
        return json.loads(self._record)

    def arrays(self):
        """Every array a commit stores for this step: the successor state and the overlap rows."""
        return dict(self.state.arrays(), **self.map.arrays())


def _before_events(moved, faces, mesh_rows):
    """The stored endpoint faces with the plates they had before the interval's events (I03.4).

    Events change only which plate owns a face, and keep every face and its order; a mesh never changes a face's
    plate. So a face the mesh made takes its donors' plate in the moved network, and a face it kept keeps its plate
    there.
    """
    plate = {face.face_id: face.plate_id for face in moved.faces}
    donors = {}
    for i, j in zip(mesh_rows.donor, mesh_rows.receiver):
        if i >= 0 and j >= 0:
            donors.setdefault(int(j), set()).add(moved.faces[int(i)].plate_id)
    out = []
    for j, face in enumerate(faces):
        owners = donors.get(j) or ({plate[face.face_id]} if face.face_id in plate else set())
        if len(owners) != 1:
            raise TransferRefused('the stored endpoint mesh does not trace each face to one plate before its events')
        out.append(Face(face.face_id, owners.pop(), face.vertex_ids, face.holes, face.block_id))
    return tuple(out)


def _stepped(state, motion, end_time_s, prepared, limits, budget, cancel, stored=None):
    """Compute one step from a verified parent state, or re-apply the ``stored`` rows of one read from a store."""
    network, material = state.network, state.material
    if motion.start_step != network.step:
        raise TransferRefused('a motion declared from global step %d cannot be applied to the state at step %d'
                              % (motion.start_step, network.step))
    end = scalar(end_time_s, 'interval end time')
    if not end > network.time_s:
        raise TransferRefused('the interval must end after the accepted time of its parent state')
    limits = _limits(limits)
    declared = {boundary.boundary_id: boundary for boundary in network.boundaries}
    for supply in motion.supplies:
        if supply.boundary_id not in declared or declared[supply.boundary_id].kind != RIDGE:
            raise TransferRefused('a supply names %r, which is not a ridge of this network' % supply.boundary_id)
    for sink in motion.sinks:
        if sink.boundary_id not in declared or declared[sink.boundary_id].kind != TRENCH:
            raise TransferRefused('a sink names %r, which is not a trench of this network' % sink.boundary_id)
    geometry = _moved(network, motion, cancel, limits, budget)
    moved = _issued(network, geometry, end, motion.end_step, limits, budget, cancel)
    births = None
    if stored is not None:
        rows, mesh_rows, births = stored['rows'], stored['mesh_rows'], stored['births']
        endpoint = moved
        if motion.mesh is not None:
            # The mesh is rebuilt from the stored faces and the stored declared directions of its added vertices,
            # must reproduce the identity its motion records, and is applied again.
            known = set(moved.vertex_ids)
            added = [name for name in stored['vertex_ids'] if name not in known]
            directions = stored['added']
            if directions.shape != (len(added), 3):
                raise TransferRefused('the stored added mesh vertices do not match the stored endpoint')
            faces = stored['faces']
            if motion.events:
                faces = _before_events(moved, faces, stored['mesh_rows'])
            mesh = Mesh(faces, tuple(zip(added, directions)))
            if mesh.mesh_id != motion.mesh.mesh_id:
                raise TransferRefused('the stored endpoint mesh is not the mesh its motion declares')
            motion = replace(motion, mesh=mesh)
            endpoint = _meshed(moved, mesh, limits, budget, cancel)
    else:
        endpoint = moved if motion.mesh is None else _meshed(moved, motion.mesh, limits, budget, cancel)
        if prepared is not None:
            if type(prepared) is not OverlapMap or (
                    (prepared.parent_geometry_id, prepared.moved_geometry_id, prepared.endpoint_geometry_id,
                     prepared.motion_id) != (network.atlas.geometry_id, moved.atlas.geometry_id,
                                             endpoint.atlas.geometry_id, motion.motion_id)):
                raise TransferRefused('stale geometry identity: a prepared overlap map is reused only while the '
                                      'parent, moved and endpoint geometries and the motion all match',
                                      STALE_GEOMETRY)
            rows, mesh_rows = prepared._motion, prepared._mesh
        else:
            rows = _motion_rows(network, moved, geometry, cancel, budget)
            mesh_rows = None if motion.mesh is None else _mesh_rows(moved, endpoint, cancel, budget=budget)
    _audited(network, moved, geometry, rows)
    if (mesh_rows is None) != (motion.mesh is None):
        raise TransferRefused('mesh rows are carried exactly when the motion declares a mesh change')
    interval = (network.time_s, end, motion.start_step, motion.end_step)
    supplies = {(supply.boundary_id, supply.side): supply for supply in motion.supplies}
    sinks = {sink.boundary_id: sink for sink in motion.sinks}
    result, transfers, born, returned = _transferred(network, material, moved, rows, supplies, sinks, interval,
                                                     births, budget=budget)
    if mesh_rows is not None:
        bounds = _audited_mesh(moved, endpoint, mesh_rows, ceilings=True)
        result, _, _, _ = _transferred(moved, result, endpoint, mesh_rows, {}, {}, interval, budget=budget,
                                       bounds=bounds)
    mapped, events = endpoint, ()
    if motion.regional_returns:
        # Round 1 (B2): regional returns of this interval, at its end, on faces it carried whole (integration_bridges).
        from . import integration_bridges as _bridges
        result = _bridges._returned_at_end(state, endpoint, result, motion.regional_returns, motion, budget)
    if motion.events:
        # I03.4: supplied topology events, at the end of the interval, on its endpoint (integration_events).
        from . import integration_events as _events
        try:
            endpoint, result, events = _events.applied(endpoint, result, motion.events, dict(motion.rotations),
                                                       budget, cancel)
        except _events.EventRefused as exc:
            raise TransferRefused('a topology event of this interval is refused: '+str(exc)) from exc
    try:
        successor = _sphere._sphere(endpoint, result, state.state_id, state.root_state_id, _state.COMPUTED)
    except TectonicsError as exc:
        raise TransferRefused('the transferred material does not occupy the endpoint network: '+str(exc)) from exc
    overlap = _map(network, moved, mapped, motion, rows, mesh_rows)
    closure = result.closure()
    record = dict(
        schema=SCHEMA, mode=MODE, producer=PRODUCER, parent_state_id=state.state_id, state_id=successor.state_id,
        interval=dict(start_s=network.time_s, end_s=end, start_step=motion.start_step, end_step=motion.end_step),
        motion=motion.record(), motion_id=motion.motion_id,
        boundaries=[dict(boundary_id=b, status=kind, rotation=list(q)) for b, kind, q in geometry.status],
        junctions=[dict(junction_id=j, spread_rad=s, relative_motion_rad=m, closure_residual=r)
                   for j, s, m, r in geometry.junctions],
        attachment_rad=geometry.attachment_rad,
        map=dict(schema=MAP_SCHEMA, map_id=overlap.map_id, parent_geometry_id=overlap.parent_geometry_id,
                 moved_geometry_id=overlap.moved_geometry_id, endpoint_geometry_id=overlap.endpoint_geometry_id,
                 parties=list(rows.parties), rows=len(rows.area_m2),
                 mesh_rows=None if mesh_rows is None else len(mesh_rows.area_m2),
                 born_faces=len(geometry.strips),
                 consumed_faces=len(geometry.deformed)-len(geometry.slid)-len(geometry.reshaped),
                 slid_faces=len(geometry.slid), reshaped_faces=len(geometry.reshaped),
                 carried_faces=len(network.face_ids)-len(geometry.deformed)),
        births=born, returns=returned, stock_transfers=[t.label for t in transfers],
        closure=dict(identity_exact=closure['identity_exact'], residual=closure['residual']),
        consumption_accuracy=_consumption_accuracy(network, material, geometry, rows, supplies))
    if events:                              # recorded only when present: steps without events keep their records
        record['events'] = list(events)
    if motion.regional_returns:
        record['regional_returns'] = [item.extract_id for item in motion.regional_returns]
    record = _canonical(record, 'step record')
    return _state._issue(Step, parent_state_id=state.state_id, state=successor, motion=motion, map=overlap,
                         stock_transfers=transfers, _record=record)


def advance(state, motion, *, end_time_s, prepared=None, limits=None, budget=None, cancel=None):
    """Move the network of ``state`` by ``motion`` to ``end_time_s`` and transfer its material; returns a Step.

    ``state`` is an accepted SphereState at global step ``motion.start_step``. Nothing is published here and the
    parent is never changed: a refusal (TransferRefused) leaves no partial result. ``prepared`` is the OverlapMap of
    an identical earlier call; it is reused only while every geometry identity and the motion match.
    """
    if type(motion) is not Motion:
        raise TransferRefused('a typed Motion is required')
    try:
        state = _sphere.verified(state)
    except ExchangeRefused:
        raise
    except TectonicsError as exc:
        raise TransferRefused(str(exc)) from exc
    with select_budget(budget).reserve(_step_workspace(state.network, motion), category='i03-sphere-step'):
        return _stepped(state, motion, end_time_s, prepared, limits, budget, cancel)


def _step_workspace(network, motion):
    """Hold generated trace arrays, IDs and plate views through geometry, rows and material assembly/replay."""
    ends = {j.junction_id: len(j.boundary_ends) for j in network.junctions}
    count = sum((p.max_segments+1)*ends.get(p.junction_id, 0) for p in motion.junction_paths)
    return 8192*len(network.face_ids)+65536+(2048+24*len(network.plate_ids))*count


# ----------------------------------------------------------------------------- ledger hooks

def proposed(ledger, parent, parent_meta, interval, transfers, budget=None, cancel=None):
    """What Ledger.commit calls when a network is attached: (I02 transfers including stock legs, the Step).

    Exactly one Motion must be among ``transfers`` and must declare exactly the commit's interval; the parent's
    network state is the ledger's own restored one. A transfer of another producer may not use the network's linked
    exchange exteriors or its producer name: only a committed step moves material between stocks and the network.
    ``cancel`` is the commit's own cancellation: the step polls it, so a cancelled commit stops before any write.
    """
    motions = [item for item in transfers if type(item) is Motion]
    others = tuple(item for item in transfers if type(item) is not Motion)
    if len(motions) != 1:
        raise TransferRefused('a spherical network is attached to this history: each commit carries exactly one '
                              'Motion for its interval; absent motion is unknown, never assumed')
    motion = motions[0]
    if (motion.start_step, motion.end_step) != (interval[2], interval[3]):
        raise TransferRefused('a motion declared for the interval (%d, %d] cannot be committed over (%d, %d]'
                              % (motion.start_step, motion.end_step, interval[2], interval[3]))
    state = ledger._restored_sphere(parent, parent_meta)
    link = state.material.stock_link or {}
    reserved = {name for name in link.values() if name is not None}
    for item in others:
        if type(item) is Transfer and (item.producer == PRODUCER or {item.donor, item.receiver} & reserved):
            raise TransferRefused("only the network's own committed step moves material through its linked "
                                  'exchange exteriors')
    step = advance(state, motion, end_time_s=interval[1], budget=budget, cancel=cancel)
    return others+step.stock_transfers, step


def _state_record(record):
    """The state descriptor inside a commit's stored 'sphere' record (a root stores the descriptor itself)."""
    if not isinstance(record, Mapping):
        raise LedgerError('the stored spherical record is missing')
    return record if record.get('schema') == _sphere.SCHEMA else record.get('state')


def linked(record, parent_record, interval):
    """Structural check of a successor's stored 'sphere' record against its parent's, from metadata only."""
    try:
        parent = _state_record(parent_record)
        state = record['state']
        return (record['schema'] == SCHEMA and record['parent_state_id'] == parent['state_id']
                and record['state_id'] == state['state_id']
                and state['lineage']['parent_state_id'] == parent['state_id']
                and record['interval'] == interval and record['motion']['motion_id'] == record['motion_id']
                and (record['motion']['start_step'], record['motion']['end_step'])
                == (interval['start_step'], interval['end_step'])
                and state['clock']['time_s'] == interval['end_s'] and state['clock']['step'] == interval['end_step'])
    except (KeyError, TypeError):
        return False


def content(metadata):
    """(producer of the network's own stock transfers, [its motion identity]) of a stored commit, for comparison."""
    record = metadata.get('sphere') if isinstance(metadata, Mapping) else None
    if not isinstance(record, Mapping) or record.get('schema') != SCHEMA:
        return None, []
    return PRODUCER, [('motion', record.get('motion_id'))]


def _stored_rows(arrays, prefix, parties):
    columns = [np.asarray(arrays[prefix+name]) for name in ROW_ARRAYS]
    if (any(column.dtype != np.int64 for column in columns[:3]) or columns[3].dtype != np.float64
            or len({column.shape for column in columns}) != 1 or columns[0].ndim != 1):
        raise LedgerError('the stored overlap rows are not well formed')
    names = [prefix+name for name in ('transient_birth_party', 'transient_sink_party', 'transient_area_m2')]
    transient = ()
    if any(name in arrays for name in names):
        if not all(name in arrays for name in names):
            raise LedgerError('the stored transient rows are incomplete')
        extra = [np.asarray(arrays[name]) for name in names]
        if (any(column.dtype != np.int64 for column in extra[:2]) or extra[2].dtype != np.float64
                or len({column.shape for column in extra}) != 1 or extra[0].ndim != 1):
            raise LedgerError('the stored transient rows are not well formed')
        transient = tuple((int(b), int(s), float(a)) for b, s, a in zip(*extra))
    return _Rows(tuple(int(x) for x in columns[0]), tuple(int(x) for x in columns[1]),
                 tuple(int(x) for x in columns[2]), tuple(float(x) for x in columns[3]), tuple(parties), transient)


def restored(parent, metadata, arrays, *, budget=None):
    """Rebuild the network state of a stored commit; ``parent`` is its parent's state or (metadata, arrays).

    The parent's stored state is rebuilt through its constructors. The recorded motion is applied to it again, which
    reproduces the moved geometry exactly; the stored overlap rows must describe and close on that geometry and are
    applied to the parent's material again in exact arithmetic. The stored record, every stored array and every
    identity must equal the recomputed ones, and the commit's finite-stock transfers must be exactly this step's.
    No intersection is measured again.
    """
    record = metadata['sphere']
    if type(parent) is tuple:
        parent = _sphere.restore_sphere(_state_record(parent[0]['sphere']), parent[1], budget=budget)
    if not isinstance(record, Mapping) or record.get('schema') != SCHEMA:
        schema = record.get('schema') if isinstance(record, Mapping) else None
        raise LedgerError('unsupported spherical step schema %r; this runtime requires %r; '
                          'no implicit history migration' % (schema, SCHEMA))
    motion = _motion(record['motion'])
    if motion.motion_id != record['motion_id']:
        raise LedgerError('the stored motion does not reproduce its identity')
    described, mesh_rows, faces, names, added = record['map'], None, None, None, None
    if motion.mesh is not None:
        mesh_rows = _stored_rows(arrays, 'sphere.remap_', ())
        try:
            faces = tuple(Face(row['face_id'], row['plate_id'], tuple(row['vertex_ids']),
                               tuple(tuple(hole) for hole in row['holes']), row['block_id'])
                          for row in _sphere._unpack(arrays['sphere.faces'], 'faces'))
            names = _sphere._unpack(arrays['sphere.vertex_ids'], 'vertex identities')
            added = np.asarray(arrays['sphere.remap_vertex_direction'])
        except (KeyError, TypeError, ValueError, TectonicsError) as exc:
            raise LedgerError('the stored mesh change is incomplete') from exc
        if added.dtype != np.float64 or added.ndim != 2 or any(type(name) is not str for name in names):
            raise LedgerError('the stored mesh change is not well formed')
    stored = dict(rows=_stored_rows(arrays, 'sphere.map_', described['parties']), mesh_rows=mesh_rows,
                  faces=faces, vertex_ids=names, added=added,
                  births={row['party']: row['totals'] for row in record['births']})
    try:
        with select_budget(budget).reserve(_step_workspace(parent.network, motion), category='i03-sphere-step'):
            step = _stepped(parent, motion, record['interval']['end_s'], None, None, budget, None, stored)
    except ExchangeRefused as exc:
        raise LedgerError('the stored step no longer applies to its parent: '+str(exc)) from exc
    if _json(step.record()) != _json(dict(record)):
        raise LedgerError('the stored step record is not reproduced by its parent, motion and rows: edited or '
                          'foreign')
    expected = step.arrays()
    kept = {name: np.asarray(array) for name, array in arrays.items() if name.startswith('sphere.')}
    if set(kept) != set(expected) or any(
            kept[name].dtype != array.dtype or kept[name].shape != array.shape
            or kept[name].tobytes() != np.ascontiguousarray(array).tobytes() for name, array in expected.items()):
        raise LedgerError('the stored network arrays are not those of the recorded step: edited or foreign')
    labels = sorted(t['label'] for t in metadata['transfers'] if t['producer'] == PRODUCER)
    if labels != sorted(t.label for t in step.stock_transfers):
        raise LedgerError("the commit's finite-stock transfers are not exactly those of its network step")
    reserved = {name for name in (parent.material.stock_link or {}).values() if name is not None}
    if any(t['producer'] != PRODUCER and {t['donor'], t['receiver']} & reserved for t in metadata['transfers']):
        raise LedgerError("a stored transfer of another producer uses the network's linked exchange exteriors")
    by_label = {t['label']: t for t in metadata['transfers']}
    for transfer in step.stock_transfers:
        kept_transfer = by_label[transfer.label]
        if ((kept_transfer['donor'], kept_transfer['receiver'], kept_transfer['enthalpy_j'], kept_transfer['basis'])
                != (transfer.donor, transfer.receiver, transfer.enthalpy_j, transfer.basis)
                or sorted(kept_transfer['component_mass_kg'].items())
                != sorted(dict(transfer.component_mass_kg).items())):
            raise LedgerError("a stored finite-stock transfer differs from the network step's")
    return _sphere._sphere(step.state.network, step.state.material, parent.state_id, parent.root_state_id,
                           _state.RESTORED)
