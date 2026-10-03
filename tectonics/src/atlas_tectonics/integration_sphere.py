"""I03.1 one shared spherical network beside the I02 accepted state, with separate material accounts. WORKING NON-CANON.

A network is one closed, immutable, versioned partition of the sphere at one accepted time: uniquely owned sampling
faces, one record per shared plate boundary with its left and right plates, the junctions where records end, one
total finite rotation per plate, each boundary's origin and the lineage of retired identities. Geometry, coverage and
topology are those of the existing W01 closed atlas (spherical_atlas): shared vertex identities, opposite edge uses,
once-around vertex links, the Euler characteristic and an independently summed area. Nothing is snapped, welded,
repaired or renormalised here either.

Physical interfaces are separate from the sampling mesh. A boundary record follows only edges between two plates and
is stored once; an edge between two faces of one plate is a seam of the mesh and belongs to no record. Plate (and
block) ownership is separate from material identity: material is held as pieces, one per (face, cohort), with
separate extensive accounts for occupied area, reference mass and phase volume per declared phase and signed enthalpy
in a declared basis. A cohort carries its identity, origin, formation interval and an opaque history reference; it
is never averaged. Accounts a state does not carry are unknown, not zero. Every piece's area is measured on the
network's own faces, so the pieces of a face must occupy it within the existing relative tolerance.

Exact rational accounts keep the declared totals, what each named exterior has supplied and the rounding of the
stored binary64 stocks, as the I02 exchange accounts do, so the closure identity holds exactly for every account.
Vertices are kept in reference frames (schema v2). Every vertex has a home, a plate or a ridge record, and a unit
direction in that home's reference frame; the home's frame rotation places it in the sphere's axes, once. A ridge
record's frame is its own carrier, composed interval by interval, so a ridge vertex moves by its rule without being
rounded again each interval. A plate whose faces use a vertex kept elsewhere keeps its own copy of it, in its own
frame. Every face is measured from its own plate's coordinates, so a face that rides with its plate keeps exactly
the same numbers and the same area.

This module issues, describes and restores states; moving geometry and transfers are integration_transfer, and the
accepted commit that carries a state is integration_ledger. Each quantity is declared once in the I02 catalogue
(integration_state.CATALOGUE) under the owner named here.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import json
import math
from types import MappingProxyType

import numpy as np

from . import integration_state as _state
from ._validation import TectonicsError, input_shape, read_array, scalar
from .coordinates import SphericalFrame
from .geometry import _check_cancel, _limits
from .integration_ledger import EXACT_LIMIT, ROLES, TOKEN, LedgerError, _exact, _exact_text
from .kinematics import Rotation, _restore_rotation
from .materials import _json, _name, _sha
from .resources import MemoryLimitError, select_budget
from .spherical_atlas import (SphericalAtlas, SphericalPatch, _AREA_TOLERANCE_SR, _capture_directions, _cycle,
                              build_spherical_atlas)
from .spherical_geometry import SphericalChart, _ring_area


SCHEMA = 'atlas.i03-sphere-state.v2'
NETWORK_SCHEMA = 'atlas.i03-sphere-network.v2'
MATERIAL_SCHEMA = 'atlas.i03-sphere-material.v2'
OWNER = 'I03 spherical network'
RIDGE, TRENCH, TRANSFORM = 'ridge', 'trench', 'transform'
KINDS = (RIDGE, TRANSFORM, TRENCH)
INITIAL, EVENT = 'prescribed-initial-condition', 'event'
SIDES = ('left', 'right')
# Existing tolerances, reused unchanged: the W01/W02 relative tolerance (cases/w01_spherical_atlas.json,
# w01_geometry.json, w01_boundaries.json, w02_completion.json) and the W01 64-epsilon attachment/ambiguity band.
RELATIVE_TOLERANCE = 1e-12
ATTACHMENT_BAND_RAD = 64*float(np.finfo(float).eps)
AREA_CLOSURE_SR = _AREA_TOLERANCE_SR    # the atlas's own absolute area closure (2e-11 sr)
CHART_MIN_COSINE = 1e-3                 # SphericalChart's own default conditioning limit
MAX_STEPS = _state.MAX_STEPS            # the cumulative accepted-step ceiling of the I02 clock
MAX_RECORD = _state.MAX_METADATA
AREA, MASS, VOLUME, ENTHALPY = 'area_m2', 'mass_kg', 'volume_m3', 'enthalpy_j'
# Catalogue names of the quantities this module owns (declared once in integration_state.CATALOGUE).
QUANTITIES = ('sphere.vertex_direction', 'sphere.face_plate', 'sphere.face_area_m2', 'sphere.boundaries',
              'sphere.junctions', 'sphere.plate_rotation', 'sphere.lineage', 'sphere.cohorts',
              'sphere.piece_area_m2', 'sphere.reference_mass_kg', 'sphere.phase_volume_m3', 'sphere.enthalpy_j',
              'sphere.exterior_accounts')
# Quantities that can be read as one array of a state.
FIELDS = ('sphere.vertex_direction', 'sphere.face_area_m2', 'sphere.piece_area_m2', 'sphere.reference_mass_kg',
          'sphere.phase_volume_m3', 'sphere.enthalpy_j')
NETWORK_ARRAYS = ('vertex_ids', 'vertex_home', 'vertex_reference', 'view_vertex', 'view_plate', 'view_reference',
                  'faces', 'boundaries')
MATERIAL_ARRAYS = ('cohorts', 'piece_face', 'piece_cohort', 'piece_stock', 'face_occupancy_allowance')


class SphereError(TectonicsError):
    """An invalid network, material or state declaration, or a refused restoration; nothing was issued."""


def _canonical(value, label):
    try:
        data = _json(value)
    except TectonicsError as exc:
        raise SphereError(label+': finite JSON data required') from exc
    if len(data) > MAX_RECORD:
        raise SphereError(label+': record exceeds the bounded envelope')
    return data


def _identity(record, arrays):
    """SHA-256 of canonical metadata, then each named array's descriptor and exact bytes (as integration_state)."""
    digest = hashlib.sha256(record)
    for name, array in arrays:
        digest.update(b'\0'+_json([name, array.dtype.str, list(array.shape)]))
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def _frozen(array, dtype):
    raw = np.ascontiguousarray(array, dtype=dtype)
    return np.frombuffer(raw.tobytes(), dtype=dtype).reshape(raw.shape)


def _pack(records):
    """Records as canonical JSON lines in one immutable byte array: stored in chunks, never in a manifest."""
    text = b'\n'.join(_json(record) for record in records)
    return np.frombuffer(text, dtype=np.uint8)


def _unpack(array, label):
    raw = np.asarray(array)
    if raw.dtype != np.uint8 or raw.ndim != 1:
        raise SphereError(label+': a stored record list is one array of bytes')
    data = raw.tobytes()
    if not data:
        return []
    try:
        return [json.loads(line) for line in data.split(b'\n')]
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise SphereError(label+': stored records are not JSON lines') from exc


def _names(values, label):
    if type(values) is not tuple:
        raise SphereError(label+': an explicit tuple of names is required')
    for value in values:
        _name(value, label)
    return values


def _sorted_unique(values, label):
    if tuple(sorted(set(values))) != values:
        raise SphereError(label+' must be unique and lexically sorted')
    return values


# ----------------------------------------------------------------------------- declared records

@dataclass(frozen=True, slots=True)
class Face:
    """One sampling face: a numerical cell of the mesh, owned by exactly one plate (and block).

    The outer ring is counter-clockwise seen from outside, holes clockwise; every edge is the minor great-circle arc
    between two registered vertices. A face is not a material: its material pieces are recorded separately.
    """
    face_id: str
    plate_id: str
    vertex_ids: tuple
    holes: tuple = ()
    block_id: str | None = None

    def __post_init__(self):
        _name(self.face_id, 'face ID')
        _name(self.plate_id, 'plate ID')
        if self.block_id is not None:
            _name(self.block_id, 'block ID')
        if type(self.vertex_ids) is not tuple or type(self.holes) is not tuple:
            raise SphereError('face rings are explicit tuples of vertex IDs')
        # The atlas's own canonical form: a ring starts at its smallest vertex ID, holes are sorted and a block
        # that is the plate itself is no block. Where a ring starts is never part of a declaration.
        object.__setattr__(self, 'vertex_ids', _cycle(self.vertex_ids))
        object.__setattr__(self, 'holes', tuple(sorted(_cycle(hole) for hole in self.holes)))
        if self.block_id == self.plate_id:
            object.__setattr__(self, 'block_id', None)


@dataclass(frozen=True, slots=True)
class Plate:
    """One plate identity and its total finite rotation since the network's reference time.

    The rotation maps the plate's configuration at ``reference_time_s`` of the network to its configuration at the
    network time, in the sphere's axes. Parents record lineage only; a plate ID is never a material ID.
    """
    plate_id: str
    rotation: Rotation
    parent_plate_ids: tuple = ()

    def __post_init__(self):
        _name(self.plate_id, 'plate ID')
        if type(self.rotation) is not Rotation:
            raise SphereError('a plate carries one finite Rotation')
        parents = _names(self.parent_plate_ids, 'parent plate')
        if len(set(parents)) != len(parents) or self.plate_id in parents:
            raise SphereError('parent plates are distinct and a plate cannot parent itself')
        object.__setattr__(self, 'parent_plate_ids', tuple(sorted(parents)))         # a set, not an order


@dataclass(frozen=True, slots=True)
class Origin:
    """Where a boundary came from: a prescribed initial condition (naming its declaring source) or a named event."""
    kind: str
    reference: str

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in (INITIAL, EVENT):
            raise SphereError('a boundary origin is a prescribed initial condition or a named creation event')
        _name(self.reference, 'origin reference')


@dataclass(frozen=True, slots=True)
class Boundary:
    """One shared boundary record, stored once: an oriented vertex chain with its left and right plates.

    Walking the chain from its first vertex, ``left_plate_id`` lies on the left. A closed chain names each vertex
    once. The kind declares the rule the boundary moves by (atlas.boundary-migration.v1): a ridge its accretion
    fraction f in n.J = n.((1-f) v_L + f v_R), a trench its subducting side. A transform may declare the side whose
    plate carries its trace (``carrier_side``, I03a-2 D6); without it a transform moves only when its two plates
    share one rotation, as in I03a.
    """
    boundary_id: str
    kind: str
    left_plate_id: str
    right_plate_id: str
    vertex_ids: tuple
    origin: Origin
    closed: bool = False
    subducting_side: str | None = None
    accretion_fraction: float | None = None
    carrier_side: str | None = None

    def __post_init__(self):
        _name(self.boundary_id, 'boundary ID')
        _name(self.left_plate_id, 'left plate')
        _name(self.right_plate_id, 'right plate')
        if type(self.kind) is not str or self.kind not in KINDS:
            raise SphereError('unsupported boundary kind: a ridge, trench or transform is declared')
        if type(self.origin) is not Origin:
            raise SphereError('every boundary declares its Origin')
        if type(self.closed) is not bool:
            raise SphereError('closed is a bool')
        chain = _names(self.vertex_ids, 'boundary vertex')
        if len(set(chain)) != len(chain) or len(chain) < (3 if self.closed else 2):
            raise SphereError('a boundary chain names each of its vertices once')
        if self.closed:                         # a loop: where it starts is not part of the declaration
            first = chain.index(min(chain))
            object.__setattr__(self, 'vertex_ids', chain[first:]+chain[:first])
        if self.left_plate_id == self.right_plate_id:
            raise SphereError('a boundary separates no two plates: its left and right plates are the same')
        fraction = self.accretion_fraction
        if self.kind == RIDGE:
            if fraction is None or isinstance(fraction, bool) or not 0 <= scalar(fraction, 'accretion fraction') <= 1:
                raise SphereError('a ridge declares its accretion fraction f in [0, 1]; none is assumed')
            object.__setattr__(self, 'accretion_fraction', float(fraction)+0.)     # minus zero is zero
        elif fraction is not None:
            raise SphereError('only a ridge declares an accretion fraction')
        if self.kind == TRENCH:
            if type(self.subducting_side) is not str or self.subducting_side not in SIDES:
                raise SphereError('a trench declares its subducting side (left or right); none is inferred')
        elif self.subducting_side is not None:
            raise SphereError('only a trench declares a subducting side')
        if self.carrier_side is not None and (self.kind != TRANSFORM or type(self.carrier_side) is not str
                                              or self.carrier_side not in SIDES):
            raise SphereError('only a transform declares the side whose plate carries its trace (left or right)')


@dataclass(frozen=True, slots=True)
class Junction:
    """A vertex where boundary records end: its incident record ends and plates in counter-clockwise order.

    Both cycles are read counter-clockwise seen from outside the sphere, starting at the smallest record end;
    ``plate_ids[0]`` is the plate just counter-clockwise of that first record.
    """
    junction_id: str
    vertex_id: str
    boundary_ends: tuple
    plate_ids: tuple


@dataclass(frozen=True, slots=True)
class Lineage:
    """Parent and root network identities, applied event identities in order, and retired identities.

    A retired face, boundary or plate identity stays reserved: no later record may reuse it.
    """
    parent_network_id: str | None = None
    root_network_id: str | None = None
    events: tuple = ()
    retired_face_ids: tuple = ()
    retired_boundary_ids: tuple = ()
    retired_plate_ids: tuple = ()

    def __post_init__(self):
        if (self.parent_network_id is None) != (self.root_network_id is None):
            raise SphereError('parent and root network identities are recorded together')
        if self.parent_network_id is not None:
            _sha(self.parent_network_id, 'parent network')
            _sha(self.root_network_id, 'root network')
        events = _names(self.events, 'event identity')
        if len(set(events)) != len(events):
            raise SphereError('an event identity is applied once')
        for name in ('retired_face_ids', 'retired_boundary_ids', 'retired_plate_ids'):
            _sorted_unique(_names(getattr(self, name), 'retired identity'), 'retired identities')


@dataclass(frozen=True, slots=True)
class Cohort:
    """One material cohort: a stable identity, origin and formation interval, never a face or plate ID.

    ``formation_start_s``/``formation_end_s`` are epoch seconds bracketing its formation (equal for a dated origin,
    an interval for material born over an accepted step); both None is explicitly unknown, never a zero age.
    ``history_id`` is an opaque reference to content another stage owns (I05); it is carried, not interpreted.
    """
    cohort_id: str
    material_id: str
    origin_id: str
    formation_start_s: float | None
    formation_end_s: float | None
    history_id: str | None = None

    def __post_init__(self):
        for label in ('cohort_id', 'material_id', 'origin_id'):
            _name(getattr(self, label), label.replace('_', ' '))
        if self.history_id is not None:
            _name(self.history_id, 'history reference')
        start, end = self.formation_start_s, self.formation_end_s
        if (start is None) != (end is None):
            raise SphereError('a formation interval is known at both ends or declared unknown at both')
        if start is not None:
            start, end = scalar(start, 'formation start'), scalar(end, 'formation end')
            if start > end:
                raise SphereError('a formation interval cannot end before it starts')
            object.__setattr__(self, 'formation_start_s', start+0.)                # minus zero is zero
            object.__setattr__(self, 'formation_end_s', end+0.)


@dataclass(frozen=True, slots=True)
class Piece:
    """The material of one cohort in one face: occupied area and its extensive accounts, in phase order."""
    face_id: str
    cohort_id: str
    area_m2: float
    mass_kg: tuple = ()
    volume_m3: tuple = ()
    enthalpy_j: float | None = None


def _plate_record(plate):
    return dict(plate_id=plate.plate_id, parent_plate_ids=list(plate.parent_plate_ids),
                rotation=list(plate.rotation.quaternion))


def _boundary_record(boundary):
    return dict(boundary_id=boundary.boundary_id, kind=boundary.kind, left_plate_id=boundary.left_plate_id,
                right_plate_id=boundary.right_plate_id, vertex_ids=list(boundary.vertex_ids),
                origin=dict(kind=boundary.origin.kind, reference=boundary.origin.reference), closed=boundary.closed,
                subducting_side=boundary.subducting_side, accretion_fraction=boundary.accretion_fraction,
                carrier_side=boundary.carrier_side)


def _face_record(face):
    return dict(face_id=face.face_id, plate_id=face.plate_id, block_id=face.block_id,
                vertex_ids=list(face.vertex_ids), holes=[list(hole) for hole in face.holes])


def _cohort_record(cohort):
    return dict(cohort_id=cohort.cohort_id, material_id=cohort.material_id, origin_id=cohort.origin_id,
                formation_start_s=cohort.formation_start_s, formation_end_s=cohort.formation_end_s,
                history_id=cohort.history_id)


def _junction_record(junction):
    return dict(junction_id=junction.junction_id, vertex_id=junction.vertex_id,
                boundary_ends=[list(end) for end in junction.boundary_ends], plate_ids=list(junction.plate_ids))


def _lineage_record(lineage):
    return dict(parent_network_id=lineage.parent_network_id, root_network_id=lineage.root_network_id,
                events=list(lineage.events), retired_face_ids=list(lineage.retired_face_ids),
                retired_boundary_ids=list(lineage.retired_boundary_ids),
                retired_plate_ids=list(lineage.retired_plate_ids))


# ----------------------------------------------------------------------------- the network

@dataclass(frozen=True, init=False, eq=False, slots=True)
class SphereNetwork(_state._Immutable):
    """One closed spherical network at one accepted time; compare networks by ``network_id``.

    Issued by build_network(), rotate_frame(), restore_network() and, for successors, integration_transfer. The W01
    atlas holds the geometry and its validated topology; faces keep their atlas order (sorted by ID). Charts are
    derived from the vertex positions and are not part of the physical state.
    """
    sphere: SphericalFrame
    atlas: SphericalAtlas
    epoch_id: str
    time_s: float
    step: int
    reference_time_s: float
    plates: tuple
    boundaries: tuple
    junctions: tuple
    lineage: Lineage
    network_id: str
    _faces: tuple = field(repr=False)
    _areas: np.ndarray = field(repr=False)
    _owners: tuple = field(repr=False)
    _layout: object = field(repr=False)
    _local: tuple = field(repr=False)
    _record: bytes = field(repr=False)
    _packed: tuple = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('SphereNetwork is issued by build_network(), restore_network() or an accepted motion step')

    @property
    def frames(self):
        """Each plate's frame rotation: it places the plate's reference frame in the sphere's axes."""
        return dict(self._layout.frames)

    @property
    def ridge_frames(self):
        """Each ridge record's frame rotation: its carriers since the declaration, composed."""
        return dict(self._layout.ridges)

    def vertex_home(self, vertex_id):
        """The plate in whose reference frame the vertex is kept, or ('ridge', boundary ID) for a ridge record's."""
        names = self.vertex_ids
        if type(vertex_id) is not str or vertex_id not in names:
            raise SphereError('unknown vertex')
        return self._layout.home[names.index(vertex_id)]

    def face_coordinates(self, index):
        """The rings of one face (outer ring, then holes) as unit directions in its own plate's reference frame."""
        return _rings_of(self, index)

    @property
    def face_ids(self):
        return tuple(face.face_id for face in self._faces)

    @property
    def faces(self):
        return self._faces

    @property
    def vertex_ids(self):
        return self.atlas.vertex_ids

    @property
    def plate_ids(self):
        return tuple(plate.plate_id for plate in self.plates)

    @property
    def vertex_direction(self):
        """Unit directions of the shared vertices in the sphere's axes, in ``vertex_ids`` order."""
        return self.atlas.vertex_directions.view()

    @property
    def face_area_m2(self):
        """Measured area of every face on the sphere, in ``face_ids`` order."""
        return self._areas.view()

    @property
    def area_m2(self):
        """The summed area of all faces: 4 pi R^2 within the atlas's own closure check."""
        return (self.atlas.statistics['area_steradians']*self.sphere.radius_m)*self.sphere.radius_m

    @property
    def statistics(self):
        return self.atlas.statistics

    def face(self, face_id):
        return self._faces[self._index(face_id)]

    def _index(self, face_id):
        ids = self.face_ids
        if type(face_id) is not str or face_id not in ids:
            raise SphereError('unknown face')
        return ids.index(face_id)

    def face_plate(self, face_id):
        return self.face(face_id).plate_id

    def face_block(self, face_id):
        return self.atlas.patches[self._index(face_id)].region_id

    def plate(self, plate_id):
        for plate in self.plates:
            if type(plate_id) is str and plate.plate_id == plate_id:
                return plate
        raise SphereError('unknown plate')

    def boundary(self, boundary_id):
        for boundary in self.boundaries:
            if type(boundary_id) is str and boundary.boundary_id == boundary_id:
                return boundary
        raise SphereError('unknown boundary')

    def plate_area_m2(self):
        """Area owned by each plate: its faces' measured areas, summed."""
        return {plate: math.fsum(float(area) for face, area in zip(self._faces, self._areas)
                                 if face.plate_id == plate) for plate in self.plate_ids}

    def adjacency(self):
        """Sorted pairs of plates that share a boundary of positive length."""
        return self.atlas.adjacency(by_plate=True)

    def boundary_edges(self):
        """Atlas edge index -> the one boundary record that owns it, for every edge between two plates."""
        return dict(self._owners)

    def descriptor(self):
        return dict(json.loads(self._record), network_id=self.network_id)

    def arrays(self):
        """The stored arrays, each a fresh read-only view: reshaping one never reaches the issued network."""
        return {'sphere.'+name: array.view() for name, array in self._packed}

    @property
    def nbytes(self):
        return sum(array.nbytes for _, array in self._packed)+len(self._record)


def _chart(sphere, points, face_id):
    """The face's own conditioned gnomonic chart: centred on its vertices' mean direction; topology only.

    The mean is an exactly rounded sum, so it does not depend on where a ring starts or on the order of its holes:
    a restored face receives the chart it was built with.
    """
    centre = np.array([math.fsum(points[:, axis]) for axis in range(3)])
    norm = float(np.linalg.norm(centre))
    if not math.isfinite(norm) or norm <= 0:
        raise SphereError('face %r has no mean direction: it does not fit an open hemisphere; split it' % face_id)
    centre = centre/norm
    if np.any(points @ centre < CHART_MIN_COSINE):
        raise SphereError('face %r does not fit a conditioned open-hemisphere chart; split it into smaller faces'
                          % face_id)
    return SphericalChart(sphere, tuple(float(x) for x in centre), CHART_MIN_COSINE)


def _captured(vertices, restored):
    if not isinstance(vertices, Mapping) or len(vertices) < 4:
        raise SphereError('a shared vertex registry of at least four directions is required')
    for name in vertices:
        _name(name, 'vertex ID')
    names = tuple(sorted(vertices))
    rows = []
    for name in names:
        if input_shape(vertices[name], 'vertex direction') != (3,):
            raise SphereError('one direction of three components per vertex is required')
        rows.append(read_array(vertices[name], 'vertex direction'))
    points = np.asarray(rows, dtype=np.float64)
    if restored:
        _unit_rows(points, 'stored vertices')
        return names, points
    return names, _capture_directions(points)+0.                           # minus zero is zero


def _unit_rows(points, label):
    if points.size and np.any(np.abs(np.linalg.norm(points, axis=1)-1) > 16*np.finfo(float).eps):
        raise SphereError(label+' are not unit directions')


IDENTITY = _restore_rotation((1., 0., 0., 0.))


def _placed(rotation, points):
    """``points`` rotated, one elementwise product and sum per component: the same bits for one or many rows."""
    m = rotation.matrix
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    out = np.empty_like(p)
    for row in range(3):
        out[:, row] = m[row, 0]*p[:, 0]+m[row, 1]*p[:, 1]+m[row, 2]*p[:, 2]
    return out


@dataclass(frozen=True, slots=True)
class _Layout:
    """Where the vertices of a network are kept (schema v2).

    Every vertex has a home and a unit direction in that home's reference frame. A home is a plate ID or
    (RIDGE, boundary ID) for a ridge record. ``frames`` and ``ridges`` hold the rotations that place each home's
    reference frame in the sphere's axes; a vertex's direction there is its home's frame rotation applied once to its
    reference direction, however many intervals have passed. ``views`` holds, for every plate whose faces use a
    vertex kept elsewhere, that plate's own copy of it in its own reference frame. A face is measured from its own
    plate's coordinates only.
    """
    names: tuple             # vertex IDs, sorted
    home: tuple              # the home of each vertex: a plate ID or (RIDGE, boundary ID)
    reference: np.ndarray    # (V, 3) unit directions in the homes' reference frames
    views: tuple             # ((vertex ID, plate ID), (x, y, z)) sorted: the copies other plates keep
    frames: tuple            # (plate ID, Rotation) sorted: reference frame -> sphere axes
    ridges: tuple            # (boundary ID, Rotation) sorted, one per ridge record: its carriers composed
    poles: tuple = None      # ((boundary ID, 'start', 'end' or 'trace'), (x, y, z)) sorted: one per record end at a
    #                          junction, and one per straight transform that declares its carrier (its trace's circle)


def _homes(names, faces, boundaries):
    """The home of each vertex of a declaration.

    A vertex inside one plate is that plate's. A boundary vertex is kept with the carrier of its record: the
    overriding plate of a trench, the declared carrier of a transform (else its left plate), and the ridge record
    itself for a ridge, whose frame moves by the ridge's own rule. Where several records meet, a trench's carrier is
    preferred, then a transform's, then a ridge; among equals the smallest record ID.
    """
    around = {name: set() for name in names}
    for face in faces:
        for ring in (face.vertex_ids, *face.holes):
            for name in ring:
                if name in around:
                    around[name].add(face.plate_id)
    carried = {}
    for boundary in boundaries:                                  # sorted by boundary ID
        if boundary.kind == TRENCH:
            rank = 0
            plate = boundary.right_plate_id if boundary.subducting_side == 'left' else boundary.left_plate_id
        elif boundary.kind == RIDGE:
            rank, plate = 2, (RIDGE, boundary.boundary_id)
        else:                                                    # a transform: its declared carrier, else left
            rank = 1
            plate = boundary.right_plate_id if boundary.carrier_side == 'right' else boundary.left_plate_id
        for name in boundary.vertex_ids:
            if name in around and (name not in carried or rank < carried[name][0]):
                carried[name] = (rank, plate)
    fallback = min((face.plate_id for face in faces), default='')
    return tuple(carried[name][1] if name in carried else min(around[name], default=fallback) for name in names)


def _used(faces):
    """The (vertex ID, plate ID) pairs of every ring vertex of every face."""
    return {(name, face.plate_id) for face in faces for ring in (face.vertex_ids, *face.holes) for name in ring}


def _ridge_ids(boundaries):
    return tuple(sorted(boundary.boundary_id for boundary in boundaries if boundary.kind == RIDGE))


def _carrier(boundary):
    """The home whose frame carries a record's trace: a trench's overriding plate, a transform's declared carrier
    (else its left plate), a ridge's own frame."""
    if boundary.kind == TRENCH:
        return boundary.right_plate_id if boundary.subducting_side == 'left' else boundary.left_plate_id
    if boundary.kind == RIDGE:
        return (RIDGE, boundary.boundary_id)
    return boundary.right_plate_id if boundary.carrier_side == 'right' else boundary.left_plate_id


def _stable_pole(a, b):
    """The unit pole of the great circle through two directions, formed stably: normalise((a + b) x (b - a))."""
    pole = np.cross(a+b, b-a)
    return pole/np.linalg.norm(pole)


def _trace_pole(trace):
    """The pole of a trace that is one great circle, or None where it bends.

    Formed stably from its first vertex and the vertex farthest from it within 120 degrees (so never from a short or a
    near-antipodal pair); the trace is one circle when every vertex lies within the existing 64 eps band of it.
    """
    chords = np.linalg.norm(trace-trace[0], axis=1)
    usable = np.where(chords <= math.sqrt(3.), chords, -1.)
    far = int(np.argmax(usable))
    if usable[far] <= ATTACHMENT_BAND_RAD:
        return None
    pole = _stable_pole(trace[0], trace[far])
    return pole if float(np.max(np.abs(trace @ pole))) <= ATTACHMENT_BAND_RAD else None


def _trace_keys(boundaries):
    """The records that may store a trace pole: transforms that declare the plate carrying their trace."""
    return {(boundary.boundary_id, 'trace') for boundary in boundaries
            if boundary.kind == TRANSFORM and boundary.carrier_side is not None}


def _end_poles(names, points, boundaries, junctions):
    """The pole of every record end at a junction, at declaration (I03a-2 M6 and C3, approved 3 October 2026).

    Each end gets the pole of its end segment's great circle, formed stably, never from a short pair later. Two
    records ending at one junction form one through-going line when they have the same carrier and their junction
    and two neighbours lie on one circle within the existing 64 eps band. Its pole uses the best-conditioned pair
    of those three directions, so antipodal neighbours do not make it undefined: both ends get that circle's pole,
    so that the line is one constraint. Two such records with different carriers keep their own end
    poles: I03a admits such a declaration, and its junction moves while every record carries it to one point; it is
    refused only if it would advance (integration_transfer._advanced_junction, C3). The grouping is decided here once;
    a line is rigid in its carrier's frame, so it is never tested again. Every frame is the sphere's axes at a
    declaration.
    """
    lookup = {name: i for i, name in enumerate(names)}
    record = {boundary.boundary_id: boundary for boundary in boundaries}
    poles = {}
    # A transform that declares its carrier keeps its trace's circle, formed here once, so that C6 is judged against
    # the declared trace however far the far plate has slid (I03a-2 C6, cumulative; round 1, F3).
    for key in sorted(_trace_keys(boundaries)):
        pole = _trace_pole(points[[lookup[name] for name in record[key[0]].vertex_ids]])
        if pole is not None:
            poles[key] = pole
    for junction in junctions:
        here = points[lookup[junction.vertex_id]]
        ends = []
        for boundary_id, role in junction.boundary_ends:
            chain = record[boundary_id].vertex_ids
            beside = points[lookup[chain[1] if role == 'start' else chain[-2]]]
            ends.append(((boundary_id, role), beside))
            poles[boundary_id, role] = _stable_pole(here, beside)
        for i, (first, near) in enumerate(ends):
            for second, far in ends[i+1:]:
                if _carrier(record[first[0]]) == _carrier(record[second[0]]):
                    # Maximise sin(angle), the pole's conditioning, without an extra acceptance threshold. The
                    # junction's own end segments are valid minor arcs even when its neighbours are antipodal.
                    a, b, remaining = max(((near, far, here), (here, near, far), (here, far, near)),
                                          key=lambda triple: float(np.linalg.norm(
                                              np.cross(triple[0]+triple[1], triple[1]-triple[0]))))
                    line = _stable_pole(a, b)
                    if abs(float(line @ remaining)) <= ATTACHMENT_BAND_RAD:
                        poles[first] = poles[second] = line
    return tuple(sorted((key, tuple(float(x) for x in value)) for key, value in poles.items()))


def _declared_layout(names, points, faces, plates, boundaries):
    """The layout of a declaration: every reference frame is the sphere's axes at the declared time."""
    home = _homes(names, faces, boundaries)
    owner = dict(zip(names, home))
    row = {name: points[i] for i, name in enumerate(names)}
    views = tuple(sorted(((name, plate), tuple(float(x) for x in row[name])) for name, plate in _used(faces)
                         if name in owner and owner[name] != plate))
    return _Layout(names, home, points, views, tuple((plate.plate_id, IDENTITY) for plate in plates),
                   tuple((boundary_id, IDENTITY) for boundary_id in _ridge_ids(boundaries)), None)


def _checked_layout(layout, faces, plates, boundaries):
    """A layout whose homes, frames and copies are exactly those its faces, plates and ridge records need."""
    if type(layout) is not _Layout:
        raise SphereError('a vertex layout is required')
    names, declared = layout.names, tuple(plate.plate_id for plate in plates)
    ridges = _ridge_ids(boundaries)
    homes = set(declared) | {(RIDGE, boundary_id) for boundary_id in ridges}
    reference = np.asarray(layout.reference, dtype=np.float64)
    if (len(names) < 4 or tuple(sorted(set(names))) != tuple(names) or reference.shape != (len(names), 3)
            or len(layout.home) != len(names) or any(home not in homes for home in layout.home)):
        raise SphereError('the vertex layout does not match its vertex registry, plates and ridge records')
    for name in names:
        _name(name, 'vertex ID')
    # Every vertex is kept by the carrier its records and faces give it, so one network has one layout.
    canonical = _homes(names, faces, boundaries)
    for name, home, carrier in zip(names, layout.home, canonical):
        if home != carrier:
            raise SphereError('vertex %r is kept by %r, not by its carrier %r' % (name, home, carrier))
    _unit_rows(reference, 'vertex reference directions')
    if tuple(plate for plate, _ in layout.frames) != declared or any(
            type(rotation) is not Rotation for _, rotation in layout.frames):
        raise SphereError('every plate has exactly one frame rotation')
    if tuple(boundary_id for boundary_id, _ in layout.ridges) != ridges or any(
            type(rotation) is not Rotation for _, rotation in layout.ridges):
        raise SphereError('every ridge record has exactly one frame rotation')
    owner = dict(zip(names, layout.home))
    needed = sorted((name, plate) for name, plate in _used(faces) if name in owner and owner[name] != plate)
    if [key for key, _ in layout.views] != needed:
        raise SphereError("a plate's copies of vertices kept elsewhere are exactly those its faces use")
    copies = np.asarray([value for _, value in layout.views], dtype=np.float64).reshape(-1, 3)
    _unit_rows(copies, "a plate's copies of vertices kept elsewhere")
    checked = _Layout(names, tuple(layout.home), _frozen(reference, np.float64),
                      tuple((key, tuple(float(x) for x in value)) for (key, _), value in zip(layout.views, copies)),
                      tuple(layout.frames), tuple(layout.ridges), layout.poles)
    _copies_placed(checked)
    return checked


COPY_ROUNDING = 4*float(np.finfo(float).eps)


def _copies_placed(layout):
    """Refuse a plate's copy of a vertex kept elsewhere that lies off the vertex's placement (I03a-2 C10, form a).

    Approved by the coordinator on 3 October 2026. A copy is re-placed whenever it would drift from its vertex by more
    than the existing 64 eps band, so on issue and on restore |F_p copy - F_home reference| is at most the band plus
    4 eps: the rounding of two placements and one pull-back. This is an exact relation between stored values, not an
    authentication: a store rewritten consistently in other ways stays inside the trusted-local-store boundary.
    """
    if not layout.views:
        return
    where = _directions(layout)
    index = {name: i for i, name in enumerate(layout.names)}
    frames = dict(layout.frames)
    for (name, plate), value in layout.views:
        drift = float(np.linalg.norm(_placed(frames[plate], np.asarray(value))[0]-where[index[name]]))
        if not drift <= ATTACHMENT_BAND_RAD+COPY_ROUNDING:
            raise SphereError("plate %r's copy of vertex %r lies %.3e from the vertex's placement, more than the 64 eps "
                              "band plus 4 eps of rounding (C10); refused" % (plate, name, drift))


def _home_index(layout):
    """The stored index of each home: plates in order, then ridge records in order."""
    keys = tuple(plate for plate, _ in layout.frames)+tuple((RIDGE, b) for b, _ in layout.ridges)
    return {key: i for i, key in enumerate(keys)}


def _home_rows(layout, home):
    return np.fromiter((value == home for value in layout.home), dtype=bool, count=len(layout.home))


def _directions(layout):
    """Every vertex in the sphere's axes: its home's frame rotation applied once to its reference."""
    out = np.empty_like(layout.reference)
    for home, rotation in (*layout.frames, *(((RIDGE, b), rotation) for b, rotation in layout.ridges)):
        rows = _home_rows(layout, home)
        if np.any(rows):
            out[rows] = _placed(rotation, layout.reference[rows])
    return out


def _local(layout, plates):
    """Per plate, every vertex its faces can use, in that plate's reference frame; NaN where it has no copy."""
    index = {name: i for i, name in enumerate(layout.names)}
    tables = []
    for plate in plates:
        table = np.full_like(layout.reference, np.nan)
        rows = _home_rows(layout, plate.plate_id)
        table[rows] = layout.reference[rows]
        tables.append(table)
    order = {plate.plate_id: i for i, plate in enumerate(plates)}
    for (name, plate), value in layout.views:
        tables[order[plate]][index[name]] = value
    return tuple(_frozen(table, np.float64) for table in tables)


def _rings_of(network, index, lookup=None, order=None):
    """The rings of face ``index`` as unit directions in its own plate's reference frame."""
    face = network._faces[index]
    if lookup is None:
        lookup = {name: i for i, name in enumerate(network._layout.names)}
    plate = network.plate_ids.index(face.plate_id) if order is None else order[face.plate_id]
    table = network._local[plate]
    return [table[[lookup[name] for name in ring]] for ring in (face.vertex_ids, *face.holes)]


def _mean_direction(points):
    centre = np.array([math.fsum(points[:, axis]) for axis in range(3)])
    norm = float(np.linalg.norm(centre))
    if not math.isfinite(norm) or norm <= 0:
        raise SphereError('a ring has no mean direction')
    return centre/norm


def _measure(rings):
    """Area in steradians of one face from its rings (outer, then holes): the W01 signed fan about the outer mean."""
    anchor = _mean_direction(rings[0])
    area = _ring_area(np.vstack([rings[0], rings[0][:1]]), anchor)
    return area-math.fsum(_ring_area(np.vstack([hole, hole[:1]]), anchor) for hole in rings[1:])


EPSILON = float(np.finfo(float).eps)
QUARTER_TURN_COSINE = math.cos(math.pi/4)


def _measure_bound(rings):
    """An upper bound in steradians on the rounding of _measure(rings) (I03a-2 C7, approved 3 October 2026).

    e = 9 eps sum_j |v_j - c| |v_j+1 - c| + max(14 eps, 4.4 eps + 5 alpha) sum_j |T_j|, with c the outer ring's
    mean direction (the anchor _measure uses), alpha the largest departure from one of a vertex's or the anchor's
    norm, and T_j the fan triangles of every ring. Each fan triangle is 2 atan2(N, D) with |dN| <= 3.8 eps
    |v_j - c| |v_j+1 - c| (the permanent bound) and dA/dN <= 2/D <= 2; the relative term of each triangle collects D,
    atan2 (one ulp, a platform assumption tested in test_i03_thin_faces) and non-unit vertices, (4.5/D + 2.5) eps +
    5 alpha with D >= 1 + sqrt 2, so it scales with that triangle's own area, never with the face's net area (a hole's
    triangles subtract from the area but add to the rounding). It holds only while every vertex is within 45 degrees
    of the anchor; otherwise None, and a closure keeps the existing relative criterion alone.
    """
    anchor = _mean_direction(rings[0])
    total, spread, alpha = 0., 0., abs(float(np.linalg.norm(anchor))-1)
    for ring in rings:
        ring = np.asarray(ring, dtype=np.float64)
        if np.any(ring @ anchor < QUARTER_TURN_COSINE):
            return None
        alpha = max(alpha, float(np.max(np.abs(np.linalg.norm(ring, axis=1)-1))))
        reach = np.linalg.norm(ring-anchor, axis=1)
        total += math.fsum(reach*np.roll(reach, -1))
        after = np.roll(ring, -1, axis=0)
        numerator = np.cross(ring-anchor, after-anchor) @ anchor
        denominator = 1+ring @ anchor+np.sum(ring*after, axis=1)+after @ anchor
        spread += math.fsum(np.abs(2*np.arctan2(numerator, denominator)))
    return 9*EPSILON*total+max(14*EPSILON, 4.4*EPSILON+5*alpha)*spread


def _acyclic(plates, retired):
    known = {plate.plate_id for plate in plates} | set(retired)
    pending = {plate.plate_id: set(plate.parent_plate_ids) for plate in plates}
    for parents in pending.values():
        if not parents <= known:
            raise SphereError('unknown parent plate')
    done = set(retired)
    while pending:
        ready = [name for name, parents in pending.items() if parents <= done]
        if not ready:
            raise SphereError('cyclic plate lineage')
        for name in ready:
            done.add(name)
            del pending[name]


def _collapsed(values):
    """A cyclic sequence without consecutive repeats."""
    out = []
    for value in values:
        if not out or out[-1] != value:
            out.append(value)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return tuple(out)


def _owned(atlas, boundaries, plates):
    """(edge -> its one boundary record, vertex -> record uses, plates around each vertex) of the declared records.

    Every edge between two plates lies on exactly one record whose sides match the faces beside it, and a record
    follows no seam inside a plate.
    """
    lookup = {name: i for i, name in enumerate(atlas.vertex_ids)}
    edges = {(int(a), int(b)): i for i, (a, b) in enumerate(atlas.edge_vertices)}
    sides, patches = atlas.side_patches, atlas.patches
    around = [set() for _ in atlas.vertex_ids]
    for patch in patches:
        for ring in patch.rings:
            for name in ring:
                around[lookup[name]].add(patch.plate_id)
    declared = {plate.plate_id for plate in plates}
    owners, uses = {}, {}
    for boundary in boundaries:
        if not {boundary.left_plate_id, boundary.right_plate_id} <= declared:
            raise SphereError('boundary %r names an undeclared plate' % boundary.boundary_id)
        chain = boundary.vertex_ids
        if not set(chain) <= set(lookup):
            raise SphereError('boundary %r names an unregistered vertex' % boundary.boundary_id)
        steps = list(zip(chain, chain[1:]))+([(chain[-1], chain[0])] if boundary.closed else [])
        for a, b in steps:
            i, j = lookup[a], lookup[b]
            edge = edges.get((min(i, j), max(i, j)))
            if edge is None:
                raise SphereError('boundary %r follows no shared edge between %r and %r'
                                  % (boundary.boundary_id, a, b))
            left, right = (int(x) for x in sides[edge])
            if i > j:
                left, right = right, left
            beside = (patches[left].plate_id, patches[right].plate_id)
            if beside[0] == beside[1]:
                raise SphereError('boundary %r separates no two plates between %r and %r: that edge is a seam '
                                  'inside plate %r' % (boundary.boundary_id, a, b, beside[0]))
            if beside != (boundary.left_plate_id, boundary.right_plate_id):
                raise SphereError('boundary %r: its left and right plates do not match the faces beside it '
                                  'between %r and %r' % (boundary.boundary_id, a, b))
            if edge in owners:
                raise SphereError('an edge lies on more than one boundary record (%r and %r)'
                                  % (owners[edge], boundary.boundary_id))
            owners[edge] = boundary.boundary_id
        last = len(chain)-1
        for k, name in enumerate(chain):
            role = 'interior' if boundary.closed or 0 < k < last else ('start' if k == 0 else 'end')
            uses.setdefault(name, []).append((boundary.boundary_id, role))
    for edge in atlas.interplate_edges:
        if edge not in owners:
            left, right = (patches[int(x)].plate_id for x in sides[edge])
            raise SphereError('an edge between plates %r and %r has no boundary record' % (left, right))
    return owners, uses, around


def _joined(atlas, boundaries, plates, limits=None, budget=None, cancel=None):
    """Check the boundary records against the atlas and derive the junctions.

    Beyond _owned's checks, no chain runs through a vertex where another record ends or a third plate touches. The
    junction pass works within the caller's limits and budget.
    """
    owners, uses, around = _owned(atlas, boundaries, plates)
    lookup = {name: i for i, name in enumerate(atlas.vertex_ids)}
    junctions = []
    block_plate = {patch.region_id: patch.plate_id for patch in atlas.patches}
    for name in sorted(uses):
        entries = uses[name]
        roles = {role for _, role in entries}
        index = lookup[name]
        if 'interior' in roles:
            if len(entries) != 1 or len(around[index]) != 2:
                raise SphereError('a boundary chain runs through the junction at vertex %r; end the record there'
                                  % name)
            continue
        ends = dict(entries)
        if len(ends) != len(entries):
            raise SphereError('boundary records at vertex %r are ambiguous' % name)
        ring = atlas.junction(index, limits=limits, budget=budget, cancel=cancel)
        rays = [(owners[edge], ends[owners[edge]]) if edge in owners else None for edge in ring.edge_indices]
        if sorted(ray for ray in rays if ray is not None) != sorted(entries):
            raise SphereError('boundary record ends at vertex %r do not match the edges that meet there' % name)
        # The cycle starts at the smallest record end, so it does not depend on the frame's axes.
        first = rays.index(min(ray for ray in rays if ray is not None))
        turn = lambda values: tuple(values[first:])+tuple(values[:first])
        junctions.append(Junction('junction:'+name, name, tuple(ray for ray in turn(rays) if ray is not None),
                                  _collapsed(block_plate[block] for block in turn(ring.sector_region_ids))))
    return tuple(sorted(owners.items())), tuple(junctions)


def _network(sphere, vertices, faces, plates, boundaries, epoch_id, time_s, step, reference_time_s, lineage, limits,
             budget, cancel, restored):
    _check_cancel(cancel)
    if type(sphere) is not SphericalFrame:
        raise SphereError('an explicit SphericalFrame is required')
    for values, kind, label, empty in ((faces, Face, 'Face', False), (plates, Plate, 'Plate', False),
                                       (boundaries, Boundary, 'Boundary', True)):
        if type(values) not in (tuple, list) or any(type(v) is not kind for v in values) or not (values or empty):
            raise SphereError('an explicit sequence of %s records is required' % label)
    _name(epoch_id, 'epoch_id')
    now = scalar(time_s, 'network time')+0.                                   # minus zero is zero
    if type(step) is not int or not 0 <= step <= MAX_STEPS:
        raise SphereError('the accepted step index is an integer in 0..%d' % MAX_STEPS)
    reference = now if reference_time_s is None else scalar(reference_time_s, 'rotation reference time')+0.
    if reference > now:
        raise SphereError('plate rotations are measured from a reference time not after the network time')
    lineage = Lineage() if lineage is None else lineage
    if type(lineage) is not Lineage:
        raise SphereError('a typed Lineage is required')
    limits, policy = _limits(limits), select_budget(budget)
    count = sum(len(face.vertex_ids)+sum(len(hole) for hole in face.holes) for face in faces)
    registered = len(vertices.names) if type(vertices) is _Layout else len(
        vertices if isinstance(vertices, Mapping) else ())
    with policy.reserve(2048*count+(1024+24*len(plates))*registered+65536, category='i03-network-build'):
        faces = tuple(sorted(faces, key=lambda face: face.face_id))
        plates = tuple(sorted(plates, key=lambda plate: plate.plate_id))
        boundaries = tuple(sorted(boundaries, key=lambda boundary: boundary.boundary_id))
        for values, attribute, label in ((faces, 'face_id', 'face'), (plates, 'plate_id', 'plate'),
                                         (boundaries, 'boundary_id', 'boundary')):
            ids = [getattr(value, attribute) for value in values]
            if len(set(ids)) != len(ids):
                raise SphereError('duplicate %s ID' % label)
        for ids, retired, label in (((f.face_id for f in faces), lineage.retired_face_ids, 'face'),
                                    ((p.plate_id for p in plates), lineage.retired_plate_ids, 'plate'),
                                    ((b.boundary_id for b in boundaries), lineage.retired_boundary_ids, 'boundary')):
            if set(ids) & set(retired):
                raise SphereError('a retired %s identity stays reserved and cannot be reused' % label)
        declared = {plate.plate_id for plate in plates}
        owning = {face.plate_id for face in faces}
        if not owning <= declared:
            raise SphereError('a face names an undeclared plate: %r' % min(owning-declared))
        if declared-owning:
            raise SphereError('plate %r owns no face; retire it explicitly' % min(declared-owning))
        _acyclic(plates, lineage.retired_plate_ids)
        if type(vertices) is _Layout:
            layout = _checked_layout(vertices, faces, plates, boundaries)
        else:
            names, points = _captured(vertices, restored)
            layout = _checked_layout(_declared_layout(names, points, faces, plates, boundaries), faces, plates,
                                     boundaries)
        names, points = layout.names, _directions(layout)
        lookup = {name: i for i, name in enumerate(names)}
        patches = []
        for face in faces:
            _check_cancel(cancel)
            rings = (face.vertex_ids, *face.holes)
            if any(type(ring) is not tuple or not set(ring) <= set(lookup) for ring in rings):
                raise SphereError('face %r names an unregistered vertex' % face.face_id)
            chart = _chart(sphere, points[[lookup[name] for ring in rings for name in ring]], face.face_id)
            patches.append(SphericalPatch(face.face_id, face.plate_id if face.block_id is None else face.block_id,
                                          face.plate_id, face.vertex_ids, chart, face.holes))
        # The directions are already captured once; a second normalisation would drift them (as in stitching).
        atlas = build_spherical_atlas(sphere, dict(zip(names, points)), tuple(patches), limits=limits, budget=policy,
                                      cancel=cancel, _restored=True)
        owners, junctions = _joined(atlas, boundaries, plates, limits, policy, cancel)
        ends = sorted(end for junction in junctions for end in junction.boundary_ends)
        if layout.poles is None:                       # a declaration: the poles are formed here, once
            layout = _Layout(layout.names, layout.home, layout.reference, layout.views, layout.frames, layout.ridges,
                             _end_poles(names, points, boundaries, junctions))
        poles = np.asarray([value for _, value in layout.poles], dtype=np.float64).reshape(-1, 3)
        if ([key for key, _ in layout.poles if key[1] != 'trace'] != ends
                or not {key for key, _ in layout.poles if key[1] == 'trace'} <= _trace_keys(boundaries)):
            raise SphereError('the stored record-end poles are not those of the junctions and carried transforms')
        _unit_rows(poles, 'record-end poles')
        # Faces are recorded with the atlas's canonical ring starts, so a ring's starting vertex never matters.
        faces = tuple(Face(patch.patch_id, patch.plate_id, patch.vertex_ids, patch.holes,
                           None if patch.region_id == patch.plate_id else patch.region_id)
                      for patch in atlas.patches)
        # Every face is measured in its own plate's reference frame, from coordinates that do not change while it
        # rides: the atlas, built in the sphere's axes, validates coverage and topology only.
        local = _local(layout, plates)
        order = {plate.plate_id: i for i, plate in enumerate(plates)}
        homes = _home_index(layout)
        radius, measured = sphere.radius_m, []
        for face in faces:
            rings = [local[order[face.plate_id]][[lookup[name] for name in ring]]
                     for ring in (face.vertex_ids, *face.holes)]
            measured.append((_measure(rings)*radius)*radius)
        areas = _frozen(np.asarray(measured, dtype=np.float64), np.float64)
        if not np.all(np.isfinite(areas) & (areas > 0)):
            raise SphereError('a face area is outside the positive binary64 range')
        packed = (('vertex_ids', _pack(names)),
                  ('vertex_home', _frozen(np.asarray([homes[home] for home in layout.home], dtype=np.int64),
                                          np.int64)),
                  ('vertex_reference', layout.reference),
                  ('view_vertex', _frozen(np.asarray([lookup[key[0]] for key, _ in layout.views], dtype=np.int64),
                                          np.int64)),
                  ('view_plate', _frozen(np.asarray([order[key[1]] for key, _ in layout.views], dtype=np.int64),
                                         np.int64)),
                  ('view_reference', _frozen(np.asarray([value for _, value in layout.views],
                                                        dtype=np.float64).reshape(-1, 3), np.float64)),
                  ('faces', _pack([_face_record(face) for face in faces])),
                  ('boundaries', _pack([_boundary_record(boundary) for boundary in boundaries])))
        record = _canonical(dict(
            schema=NETWORK_SCHEMA, sphere=sphere.descriptor(), epoch_id=epoch_id,
            time_unit='SI seconds forward from the named epoch', time_s=now, step=step, reference_time_s=reference,
            geometry_id=atlas.geometry_id, atlas_id=atlas.atlas_id,
            counts=dict(vertices=len(names), faces=len(faces), edges=atlas.edge_count, boundaries=len(boundaries),
                        junctions=len(junctions), plates=len(plates)),
            plates=[_plate_record(plate) for plate in plates],
            frames=[list(rotation.quaternion) for _, rotation in layout.frames],
            ridge_frames=[list(rotation.quaternion) for _, rotation in layout.ridges],
            end_poles=[[boundary_id, role, list(pole)] for (boundary_id, role), pole in layout.poles],
            junctions=[_junction_record(junction) for junction in junctions],
            lineage=_lineage_record(lineage),
            arrays=[dict(name=name, dtype=array.dtype.str, shape=list(array.shape)) for name, array in packed]),
            'network record')
        _check_cancel(cancel)
        return _state._issue(SphereNetwork, sphere=sphere, atlas=atlas, epoch_id=epoch_id, time_s=now, step=step,
                             reference_time_s=reference, plates=plates, boundaries=boundaries, junctions=junctions,
                             lineage=lineage, network_id=_identity(record, packed), _faces=faces, _areas=areas,
                             _owners=owners, _layout=layout, _local=local, _record=record, _packed=packed)


def build_network(sphere, vertices, faces, plates, boundaries, *, epoch_id, time_s, step=0, reference_time_s=None,
                  lineage=None, limits=None, budget=None, cancel=None):
    """Validate and issue one closed spherical network at ``time_s`` of the named epoch.

    ``vertices`` maps shared vertex IDs to directions in the sphere's axes; ``faces`` are the sampling faces with
    their owning plates; ``plates`` carry each plate's total finite rotation since ``reference_time_s`` (the network
    time when omitted); ``boundaries`` hold one record per interface between two plates. Coverage, pairing of every
    edge, vertex links, the Euler characteristic and the summed area are checked by the W01 atlas; this function
    adds unique ownership by declared plates, exactly one boundary record per edge between two plates with matching
    sides, junctions only where records end, acyclic plate lineage and reserved retired identities. Nothing is
    repaired: a gap, overlap, T-junction, unpaired seam or pinch is refused.
    """
    return _network(sphere, vertices, faces, plates, boundaries, epoch_id, time_s, step, reference_time_s, lineage,
                    limits, budget, cancel, False)


def rotate_frame(network, rotation, frame_id, *, limits=None, budget=None, cancel=None):
    """The same network expressed in rotated axes named ``frame_id``: a change of coordinates, not a motion.

    Every direction is rotated and every plate rotation R becomes Q R Q^-1 (the same angle about the rotated axis).
    Identities, sides, junctions and lineage are carried unchanged; lineage identities still name the records of the
    original frame.
    """
    if type(network) is not SphereNetwork or type(rotation) is not Rotation:
        raise SphereError('a SphereNetwork and a Rotation are required')
    if _name(frame_id, 'frame_id') == network.sphere.frame_id:
        raise SphereError('a rotated frame needs its own frame identity')
    sphere = SphericalFrame(network.sphere.radius_m, frame_id)
    moved = rotation.apply(network.vertex_direction, budget=budget)
    plates = []
    for plate in network.plates:
        w, *axis = plate.rotation.quaternion
        turned = rotation.apply(np.asarray(axis, dtype=np.float64), budget=budget)
        plates.append(Plate(plate.plate_id, Rotation((w, *(float(x) for x in turned))), plate.parent_plate_ids))
    return _network(sphere, dict(zip(network.vertex_ids, moved)), network.faces, tuple(plates), network.boundaries,
                    network.epoch_id, network.time_s, network.step, network.reference_time_s, network.lineage,
                    limits, budget, cancel, False)


_NETWORK_KEYS = frozenset(('schema', 'sphere', 'epoch_id', 'time_unit', 'time_s', 'step', 'reference_time_s',
                           'geometry_id', 'atlas_id', 'counts', 'plates', 'frames', 'ridge_frames', 'junctions',
                           'lineage', 'arrays', 'network_id', 'end_poles'))


def restore_network(record, arrays, *, limits=None, budget=None, cancel=None):
    """Rebuild a stored network through build_network's own checks; its record and identity must reproduce.

    ``arrays`` holds the stored 'sphere.*' network arrays. Nothing is trusted from the record alone: coverage,
    topology, sides and junctions are derived again from the stored vertices, faces and boundary records.
    """
    if not isinstance(record, Mapping) or set(record) != _NETWORK_KEYS or record['schema'] != NETWORK_SCHEMA:
        raise SphereError('the stored network record is not of this schema')
    if not isinstance(arrays, Mapping):
        raise SphereError('stored network arrays are required')
    try:
        reference = _stored(arrays, 'vertex_reference', np.float64, 2)
        home = _stored(arrays, 'vertex_home', np.int64, 1)
        view_vertex, view_plate = _stored(arrays, 'view_vertex', np.int64, 1), _stored(arrays, 'view_plate', np.int64, 1)
        view_reference = _stored(arrays, 'view_reference', np.float64, 2)
        names = _unpack(arrays['sphere.vertex_ids'], 'vertex identities')
        if (reference.shape[1:] != (3,) or len(names) != len(reference) or len(home) != len(names)
                or any(type(name) is not str for name in names) or len(set(names)) != len(names)
                or view_reference.shape != (len(view_vertex), 3) or len(view_plate) != len(view_vertex)):
            raise SphereError('stored vertices do not match their identities')
        frame = record['sphere']
        sphere = SphericalFrame(frame['radius_m'], frame['frame_id'])
        if sphere.descriptor() != frame:
            raise SphereError('the stored sphere is not a spherical frame of this schema')
        faces = tuple(Face(row['face_id'], row['plate_id'], tuple(row['vertex_ids']),
                           tuple(tuple(hole) for hole in row['holes']), row['block_id'])
                      for row in _unpack(arrays['sphere.faces'], 'faces'))
        boundaries = tuple(Boundary(row['boundary_id'], row['kind'], row['left_plate_id'], row['right_plate_id'],
                                    tuple(row['vertex_ids']), Origin(row['origin']['kind'],
                                                                     row['origin']['reference']),
                                    row['closed'], row['subducting_side'], row['accretion_fraction'],
                                    row['carrier_side'])
                           for row in _unpack(arrays['sphere.boundaries'], 'boundaries'))
        plates = tuple(Plate(row['plate_id'], _restore_rotation(tuple(row['rotation'])),
                             tuple(row['parent_plate_ids'])) for row in record['plates'])
        line = record['lineage']
        lineage = Lineage(line['parent_network_id'], line['root_network_id'], tuple(line['events']),
                          tuple(line['retired_face_ids']), tuple(line['retired_boundary_ids']),
                          tuple(line['retired_plate_ids']))
        ids = tuple(plate.plate_id for plate in sorted(plates, key=lambda plate: plate.plate_id))
        ridges = _ridge_ids(boundaries)
        keys = ids+tuple((RIDGE, boundary_id) for boundary_id in ridges)
        frames, ridge_frames = record['frames'], record['ridge_frames']
        if (type(frames) is not list or len(frames) != len(ids) or type(ridge_frames) is not list
                or len(ridge_frames) != len(ridges) or np.any((home < 0) | (home >= len(keys)))
                or np.any((view_plate < 0) | (view_plate >= len(ids)))
                or np.any((view_vertex < 0) | (view_vertex >= len(names)))):
            raise SphereError('stored vertex homes, copies and frames do not match the plates and ridge records')
        layout = _Layout(tuple(names), tuple(keys[int(i)] for i in home), reference,
                         tuple(((names[int(v)], ids[int(q)]), tuple(float(x) for x in row))
                               for v, q, row in zip(view_vertex, view_plate, view_reference)),
                         tuple((plate, _restore_rotation(tuple(q))) for plate, q in zip(ids, frames)),
                         tuple((boundary_id, _restore_rotation(tuple(q)))
                               for boundary_id, q in zip(ridges, ridge_frames)),
                         tuple(((boundary_id, role), tuple(float(x) for x in pole))
                               for boundary_id, role, pole in record['end_poles']))
        network = _network(sphere, layout, faces, plates, boundaries, record['epoch_id'],
                           record['time_s'], record['step'], record['reference_time_s'], lineage, limits, budget,
                           cancel, True)
    except (TectonicsError, MemoryLimitError):                  # a refusal keeps its own cause
        raise
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise SphereError('the stored network is incomplete') from exc
    if network.network_id != record['network_id'] or _json(network.descriptor()) != _json(dict(record)):
        raise SphereError('the stored network does not reproduce its record and identity: edited or foreign')
    _as_issued(network._packed, arrays)
    return network


# ----------------------------------------------------------------------------- material accounts

def _columns(phases, basis):
    return ((AREA,)+tuple(MASS+':'+phase for phase in phases)+tuple(VOLUME+':'+phase for phase in phases)
            + ((ENTHALPY,) if basis is not None else ()))


def _exteriors(value, cohorts):
    """Declared (name, role) exteriors: ASCII tokens that differ, even ignoring case, from every cohort identity."""
    if type(value) not in (tuple, list):
        raise SphereError('exteriors: a sequence of (name, role) pairs is required')
    out = []
    for pair in value:
        if type(pair) not in (tuple, list) or len(pair) != 2:
            raise SphereError('exteriors: (name, role) pairs are required')
        name, role = pair
        if type(name) is not str or TOKEN.fullmatch(name) is None:
            raise SphereError('an exterior name is an ASCII token of letters, digits and ._:/@+- (compared exactly)')
        if type(role) is not str or role not in ROLES:
            raise SphereError('an exterior is a named source or sink')
        out.append((name, role))
    names = [name.casefold() for name, _ in out]
    if len(set(names)) != len(names) or len(out) > 64:
        raise SphereError('at most 64 distinctly named exteriors')
    if set(names) & {cohort.cohort_id.casefold() for cohort in cohorts}:
        raise SphereError('an exterior name reuses a material cohort identity')
    return tuple(sorted(out))


def _link(value):
    """The I02 exterior accounts that stand for the network in the finite-stock exchange, or None."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {'receives', 'returns'}:
        raise SphereError('a stock link names the I02 exteriors through which the network receives and returns')
    out = {}
    for key in ('receives', 'returns'):
        name = value[key]
        if name is not None and (type(name) is not str or TOKEN.fullmatch(name) is None):
            raise SphereError('a stock link names declared I02 exteriors by their ASCII tokens')
        out[key] = name
    if out['receives'] is None and out['returns'] is None:
        raise SphereError('a stock link names at least one I02 exterior')
    if out['receives'] is not None and out['receives'] == out['returns']:
        raise SphereError('receiving and returning use distinct I02 exteriors: a sink and a source')
    return out


def _zero(count):
    return (Fraction(0),)*count


def _exact_sum(column):
    return sum((Fraction(float(x)) for x in column), Fraction(0))


@dataclass(frozen=True, init=False, eq=False, slots=True)
class SphereMaterial(_state._Immutable):
    """The material pieces of one network and their exact accounts; compare by ``material_id``.

    ``stock`` holds one row per piece and one column per account in ``columns``: occupied area, then reference mass
    per phase, phase volume per phase and, when a basis is declared, signed enthalpy. Rows are sorted by (face,
    cohort). The exact rational accounts hold the declared totals, what each named party has supplied since the
    declaration (received amounts are negative) and the rounding of the stored values, so that
    sum(stock) = initial + sum(supplied) + rounding holds exactly for every column. Nothing in a material names a
    plate.
    """
    phases: tuple
    enthalpy_basis: str | None
    columns: tuple
    cohorts: tuple
    exteriors: tuple
    stock_link: object
    material_id: str
    _face_ids: tuple = field(repr=False)
    _face: np.ndarray = field(repr=False)
    _cohort: np.ndarray = field(repr=False)
    _stock: np.ndarray = field(repr=False)
    _initial: tuple = field(repr=False)
    _supplied: tuple = field(repr=False)
    _rounding: tuple = field(repr=False)
    _allowance: tuple = field(repr=False)
    _occupancy_allowance: np.ndarray = field(repr=False)
    _record: bytes = field(repr=False)
    _packed: tuple = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('SphereMaterial is issued by build_material(), areal_material() or an accepted motion step')

    @property
    def occupancy_allowance_m2(self):
        """Per face, the round-off its pieces may carry against its measured area beyond the relative tolerance.

        Zero for every face of a declaration. A face whose pieces were last tied to it through rows closed under the
        thin-face bound (C7) carries that bound forward, and the faces it is divided among carry their shares (D7).
        """
        return self._occupancy_allowance.view()

    @property
    def stock(self):
        return self._stock.view()

    @property
    def piece_face(self):
        """Index of each piece's face in the network's ``face_ids`` order."""
        return self._face.view()

    @property
    def piece_cohort(self):
        """Index of each piece's cohort in ``cohorts``."""
        return self._cohort.view()

    def cohort(self, cohort_id):
        for cohort in self.cohorts:
            if cohort.cohort_id == cohort_id:
                return cohort
        raise SphereError('unknown cohort')

    def pieces(self):
        """Every piece as a detached record, in (face, cohort) order."""
        k = len(self.phases)
        out = []
        for row in range(len(self._face)):
            values = self._stock[row]
            out.append(Piece(self._face_ids[int(self._face[row])], self.cohorts[int(self._cohort[row])].cohort_id,
                             float(values[0]), tuple(float(x) for x in values[1:1+k]),
                             tuple(float(x) for x in values[1+k:1+2*k]),
                             None if self.enthalpy_basis is None else float(values[-1])))
        return tuple(out)

    def face_cohorts(self, face_id):
        """The cohorts present in one face."""
        if face_id not in self._face_ids:
            raise SphereError('unknown face')
        rows = np.flatnonzero(self._face == self._face_ids.index(face_id))
        return tuple(self.cohorts[int(self._cohort[row])].cohort_id for row in rows)

    def totals(self):
        """Every carried account summed over all pieces (accurate binary64 sums of the stored values)."""
        return {name: math.fsum(self._stock[:, column]) for column, name in enumerate(self.columns)}

    def exact_total(self, column):
        """The exact sum of the stored values of one account."""
        if column not in self.columns:
            raise SphereError('this material does not carry that account')
        return _exact_sum(self._stock[:, self.columns.index(column)])

    def supplied(self):
        """Exact cumulative amounts each named party has supplied to the pieces since the declaration."""
        return {name: dict(zip(self.columns, values)) for name, values in self._supplied}

    def closure(self):
        """Exact closure: sum(stock) - initial - sum(supplied) per account, which is the rounding account.

        ``identity_exact`` is True when every residual equals the exact rounding account and that account lies
        within its exact allowance: nothing was created, lost or booked twice.
        """
        residual, exact = {}, True
        for column, name in enumerate(self.columns):
            value = (_exact_sum(self._stock[:, column])-self._initial[column]
                     - sum((values[column] for _, values in self._supplied), Fraction(0)))
            exact &= value == self._rounding[column] and abs(value) <= self._allowance[column]
            residual[name] = float(value)
        return dict(residual=residual, identity_exact=bool(exact))

    def ages_s(self, time_s):
        """(youngest, oldest) age of each cohort at ``time_s``; None where its formation is unknown."""
        now = scalar(time_s, 'time_s')
        out = {}
        for cohort in self.cohorts:
            if cohort.formation_start_s is None:
                out[cohort.cohort_id] = None
            else:
                out[cohort.cohort_id] = (scalar(now-cohort.formation_end_s, 'cohort age', nonnegative=True),
                                         scalar(now-cohort.formation_start_s, 'cohort age', nonnegative=True))
        return out

    def descriptor(self):
        return dict(json.loads(self._record), material_id=self.material_id)

    def arrays(self):
        """The stored arrays, each a fresh read-only view: reshaping one never reaches the issued material."""
        return {'sphere.'+name: array.view() for name, array in self._packed}

    @property
    def nbytes(self):
        return sum(array.nbytes for _, array in self._packed)+len(self._record)


def _occupancy(network, face, stock, checked=None, allowance=None):
    """Refuse unless the pieces of each checked face occupy its measured area within the existing tolerance.

    ``face`` and ``stock`` are the sorted piece arrays; ``checked`` names the face indices to check (None is every
    face). Each face's pieces are added with an exactly rounded sum, here and nowhere else. ``allowance`` (m2 per
    face, D7) is the round-off a face carries from rows closed under the thin-face bound; the existing relative
    tolerance applies wherever it is larger.
    """
    areas = network.face_area_m2
    wanted = None if checked is None else {int(index) for index in checked}
    starts = np.flatnonzero(np.r_[True, np.diff(face) != 0])
    for index, start, end in zip(face[starts], starts, np.r_[starts[1:], len(face)]):
        if wanted is not None and int(index) not in wanted:
            continue
        total = math.fsum(stock[start:end, 0])
        slack = 0. if allowance is None else float(allowance[index])
        if abs(total-areas[index]) > max(RELATIVE_TOLERANCE*areas[index], slack):
            raise SphereError('the pieces of face %r do not occupy its measured area (%r of %r m2)'
                              % (network.face_ids[int(index)], total, float(areas[index])))


def _account(value, label):
    """The stored text of one exact account, which must read back as the same value: what is issued restores."""
    try:
        text = _exact_text(value)
        if _exact(text, label) != value:
            raise LedgerError(label+' does not read back')
    except LedgerError as exc:
        raise SphereError('%s is outside the finite accounting range or its bounded exact representation: nothing '
                          'is issued (%s)' % (label, exc)) from exc
    return text


def _material(network, phases, basis, cohorts, exteriors, link, face, cohort, stock, initial, supplied, rounding,
              allowance, budget, checked=None, occupancy_allowance=None):
    """Issue a material over already-assembled arrays and exact accounts, checking every join.

    ``checked`` names the faces whose occupancy is measured against their pieces; None, every face, is what every
    issuing and restoring route passes, so a face that only rode is measured again after every interval. A face keeps
    its numbers while it rides (its vertices are kept in its plate's reference frame), so this costs no tolerance. An
    empty ``checked`` is used only where the caller has just measured every face against the same arrays
    (integration_transfer). All pieces together must still cover the sphere once. ``occupancy_allowance`` holds each
    face's allowance (D7); None is zero for every face, as for a declaration.
    """
    if type(network) is not SphereNetwork:
        raise SphereError('a SphereNetwork is required')
    phases = _sorted_unique(_names(phases, 'phase'), 'phases')
    if len(phases) > 64:
        raise SphereError('at most 64 phases')
    if basis is not None:
        _name(basis, 'enthalpy basis')
    if type(cohorts) is not tuple or not cohorts or any(type(c) is not Cohort for c in cohorts):
        raise SphereError('a nonempty tuple of Cohort records is required')
    _sorted_unique(tuple(c.cohort_id for c in cohorts), 'cohort identities')
    for record in cohorts:
        if record.formation_end_s is not None and record.formation_end_s > network.time_s:
            raise SphereError('cohort %r forms in the future of this state' % record.cohort_id)
    exteriors, link = _exteriors(exteriors, cohorts), _link(link)
    if link is not None and (not phases or basis is None):
        raise SphereError('a stock link needs declared phases and an enthalpy basis: finite stocks carry both')
    columns = _columns(phases, basis)
    count, width = len(face), len(columns)
    with select_budget(budget).reserve(64*count*(width+4)+65536, category='i03-material'):
        face, cohort = _frozen(face, np.int64), _frozen(cohort, np.int64)
        stock = _frozen(stock, np.float64)
        if face.shape != (count,) or cohort.shape != (count,) or stock.shape != (count, width) or not count:
            raise SphereError('one face, one cohort and one value per account are required for every piece')
        faces = len(network.face_ids)
        if face.min() < 0 or face.max() >= faces or cohort.min() < 0 or cohort.max() >= len(cohorts):
            raise SphereError('a piece names an unknown face or cohort')
        keys = face*len(cohorts)+cohort
        if np.any(np.diff(keys) <= 0):
            raise SphereError('pieces are unique and sorted by face, then cohort')
        if not np.isfinite(stock).all() or np.abs(stock).max() > EXACT_LIMIT:
            raise SphereError('piece accounts must be finite and within the finite accounting range')
        signed = width-1 if basis is not None else width
        if np.any(stock[:, :signed] < 0) or np.any(stock[:, 0] <= 0):
            raise SphereError('occupied area is positive and reference mass and phase volume are nonnegative')
        # One owner per point: the pieces of a face occupy exactly its measured area, within the existing tolerance.
        areas = network.face_area_m2
        occupied = np.zeros(faces)
        np.add.at(occupied, face, 1.)
        if np.any(occupied == 0):
            raise SphereError('face %r carries no material piece: absent material is declared, never assumed'
                              % network.face_ids[int(np.flatnonzero(occupied == 0)[0])])
        slack = _frozen(np.zeros(faces) if occupancy_allowance is None else occupancy_allowance, np.float64)
        if slack.shape != (faces,) or not np.isfinite(slack).all() or np.any(slack < 0):
            raise SphereError('one finite nonnegative occupancy allowance per face is required')
        _occupancy(network, face, stock, checked, slack)
        radius = network.sphere.radius_m
        covered = math.fsum(stock[:, 0])
        if abs(covered-network.area_m2) > (AREA_CLOSURE_SR*radius)*radius:
            raise SphereError('the pieces do not cover the sphere once: they occupy %r m2 of its %r m2'
                              % (covered, network.area_m2))
        if (len(initial) != width or len(rounding) != width or len(allowance) != width
                or any(len(values) != width for _, values in supplied)):
            raise SphereError('one exact account per carried column is required')
        supplied = tuple(sorted(supplied))
        if len({name for name, _ in supplied}) != len(supplied):
            raise SphereError('one exact account per named party')
        for column in range(width):
            total = _exact_sum(stock[:, column])
            booked = initial[column]+sum((values[column] for _, values in supplied), Fraction(0))+rounding[column]
            if total != booked or abs(rounding[column]) > allowance[column]:
                raise SphereError('the exact accounts do not close on the stored pieces: nothing is issued')
        exact = dict(initial=[_account(v, 'a declared total') for v in initial],
                     supplied={name: [_account(v, 'a supplied account') for v in values] for name, values in supplied},
                     rounding=[_account(v, 'a rounding account') for v in rounding],
                     allowance=[_account(v, 'a rounding allowance') for v in allowance])
        packed = (('cohorts', _pack([_cohort_record(record) for record in cohorts])), ('piece_face', face),
                  ('piece_cohort', cohort), ('piece_stock', stock), ('face_occupancy_allowance', slack))
        units = dict({AREA: 'm2', ENTHALPY: 'J'}, **{MASS+':'+p: 'kg' for p in phases},
                     **{VOLUME+':'+p: 'm3' for p in phases})
        record = _canonical(dict(
            schema=MATERIAL_SCHEMA, phases=list(phases), enthalpy_basis=basis,
            columns=[dict(name=name, units=units[name]) for name in columns],
            exteriors=[list(pair) for pair in exteriors], stock_link=link, exact=exact,
            counts=dict(pieces=count, cohorts=len(cohorts)),
            arrays=[dict(name=name, dtype=array.dtype.str, shape=list(array.shape)) for name, array in packed]),
            'material record')
        return _state._issue(SphereMaterial, phases=phases, enthalpy_basis=basis, columns=columns, cohorts=cohorts,
                             exteriors=exteriors, stock_link=None if link is None else MappingProxyType(dict(link)),
                             material_id=_identity(record, packed),
                             _face_ids=network.face_ids, _face=face, _cohort=cohort, _stock=stock,
                             _initial=tuple(initial), _supplied=supplied, _rounding=tuple(rounding),
                             _allowance=tuple(allowance), _occupancy_allowance=slack, _record=record,
                             _packed=packed)


def _values(value, count, label, *, nonnegative=True):
    if type(value) not in (tuple, list) or len(value) != count:
        raise SphereError(label+': one value per declared phase, in phase order, is required')
    return [scalar(x, label, nonnegative=nonnegative) for x in value]


def build_material(network, *, phases, cohorts, pieces, enthalpy_basis=None, exteriors=(), stock_link=None,
                   budget=None):
    """Declare the material of a network: its phases, cohorts and one Piece per occupied (face, cohort).

    Every face must be fully occupied: its pieces' areas sum to its measured area within the existing relative
    tolerance. Signed enthalpy is carried only with a declared basis; without one it is unknown, and a piece that
    supplies one anyway is refused. ``exteriors`` are named sources and sinks of later transfers; ``stock_link``
    names the I02 exterior accounts through which finite stocks supply and receive material.
    """
    if type(network) is not SphereNetwork:
        raise SphereError('a SphereNetwork is required')
    if type(pieces) not in (tuple, list) or not pieces or any(type(p) is not Piece for p in pieces):
        raise SphereError('a nonempty sequence of Piece records is required')
    if type(cohorts) is not tuple or any(type(c) is not Cohort for c in cohorts):
        raise SphereError('a tuple of Cohort records is required')
    phases = _sorted_unique(_names(phases, 'phase'), 'phases')
    faces = {name: i for i, name in enumerate(network.face_ids)}
    known = {record.cohort_id: i for i, record in enumerate(cohorts)}
    rows, seen = [], set()
    for piece in pieces:
        if (type(piece.face_id) is not str or type(piece.cohort_id) is not str or piece.face_id not in faces
                or piece.cohort_id not in known):
            raise SphereError('a piece names an unknown face or cohort')
        key = (faces[piece.face_id], known[piece.cohort_id])
        if key in seen:
            raise SphereError('one piece per face and cohort: a duplicate is not summed')
        seen.add(key)
        values = [scalar(piece.area_m2, 'piece area', positive=True)]
        values += _values(piece.mass_kg, len(phases), 'reference mass')
        values += _values(piece.volume_m3, len(phases), 'phase volume')
        if (piece.enthalpy_j is None) != (enthalpy_basis is None):
            raise SphereError('signed enthalpy is carried exactly when its basis is declared: unknown is not zero')
        if enthalpy_basis is not None:
            values.append(scalar(piece.enthalpy_j, 'piece enthalpy'))
        rows.append((key, values))
    rows.sort(key=lambda row: row[0])
    stock = np.array([values for _, values in rows], dtype=np.float64).reshape(len(rows), -1)
    width = stock.shape[1]
    initial = tuple(_exact_sum(stock[:, column]) for column in range(width))
    return _material(network, phases, enthalpy_basis, cohorts, exteriors, stock_link,
                     np.array([key[0] for key, _ in rows], dtype=np.int64),
                     np.array([key[1] for key, _ in rows], dtype=np.int64), stock, initial, (), _zero(width),
                     _zero(width), budget)


def areal_material(network, *, phases, cohorts, face_cohort, mass_per_area_kg_m2, thickness_m,
                   enthalpy_per_area_j_m2=None, enthalpy_basis=None, exteriors=(), stock_link=None, budget=None):
    """One cohort per face, each stock its declared areal value times the face's own measured area.

    ``face_cohort`` maps every face to its cohort; ``mass_per_area_kg_m2`` and ``thickness_m`` map every phase to
    its reference mass and phase volume per unit area. Areas come from the network's faces, never from another
    grid's measure.
    """
    if type(network) is not SphereNetwork:
        raise SphereError('a SphereNetwork is required')
    phases = _sorted_unique(_names(phases, 'phase'), 'phases')
    for mapping, label in ((face_cohort, 'face cohorts'), (mass_per_area_kg_m2, 'reference mass per area'),
                           (thickness_m, 'phase thickness')):
        if not isinstance(mapping, Mapping):
            raise SphereError(label+': an explicit mapping is required')
    if set(face_cohort) != set(network.face_ids) or any(type(name) is not str for name in face_cohort.values()):
        raise SphereError('every face names its cohort: absent material is declared, never assumed')
    if set(mass_per_area_kg_m2) != set(phases) or set(thickness_m) != set(phases):
        raise SphereError('reference mass per area and thickness are declared for exactly the phases')
    if (enthalpy_per_area_j_m2 is None) != (enthalpy_basis is None):
        raise SphereError('signed enthalpy is carried exactly when its basis is declared: unknown is not zero')
    mass = [scalar(mass_per_area_kg_m2[p], 'reference mass per area', nonnegative=True) for p in phases]
    depth = [scalar(thickness_m[p], 'phase thickness', nonnegative=True) for p in phases]
    heat = None if enthalpy_basis is None else scalar(enthalpy_per_area_j_m2, 'enthalpy per area')
    pieces = []
    for face_id, area in zip(network.face_ids, network.face_area_m2):
        area = float(area)
        pieces.append(Piece(face_id, face_cohort[face_id], area, tuple(m*area for m in mass),
                            tuple(h*area for h in depth), None if heat is None else heat*area))
    return build_material(network, phases=phases, cohorts=cohorts, pieces=tuple(pieces),
                          enthalpy_basis=enthalpy_basis, exteriors=exteriors, stock_link=stock_link, budget=budget)


_MATERIAL_KEYS = frozenset(('schema', 'phases', 'enthalpy_basis', 'columns', 'exteriors', 'stock_link', 'exact',
                            'counts', 'arrays', 'material_id'))


def _stored(arrays, name, dtype, rank):
    """One stored array exactly as it was written: this dtype and rank, never cast to them."""
    array = np.asarray(arrays['sphere.'+name])
    if array.dtype != np.dtype(dtype) or array.ndim != rank:
        raise SphereError('the stored %s array is not the %s array it was written as: edited or foreign'
                          % (name, np.dtype(dtype).str))
    return array


def _as_issued(packed, arrays):
    """Refuse unless every stored array has exactly the type, shape and bytes of the rebuilt one."""
    for name, array in packed:
        kept = np.asarray(arrays['sphere.'+name])
        if kept.dtype != array.dtype or kept.shape != array.shape or kept.tobytes() != array.tobytes():
            raise SphereError('the stored %s array is not the one this state was issued with: edited or foreign'
                              % name)


def restore_material(network, record, arrays, *, budget=None):
    """Rebuild a stored material on its restored network; its record, arrays and identity must reproduce.

    Every face is measured against its pieces, for a declared and a computed state alike (see _material).
    """
    if not isinstance(record, Mapping) or set(record) != _MATERIAL_KEYS or record['schema'] != MATERIAL_SCHEMA:
        raise SphereError('the stored material record is not of this schema')
    if not isinstance(arrays, Mapping):
        raise SphereError('stored material arrays are required')
    try:
        cohorts = tuple(Cohort(row['cohort_id'], row['material_id'], row['origin_id'], row['formation_start_s'],
                               row['formation_end_s'], row['history_id'])
                        for row in _unpack(arrays['sphere.cohorts'], 'cohorts'))
        exact = record['exact']
        material = _material(
            network, tuple(record['phases']), record['enthalpy_basis'], cohorts,
            tuple(tuple(pair) for pair in record['exteriors']), record['stock_link'],
            _stored(arrays, 'piece_face', np.int64, 1), _stored(arrays, 'piece_cohort', np.int64, 1),
            _stored(arrays, 'piece_stock', np.float64, 2),
            tuple(_exact(v, 'initial account') for v in exact['initial']),
            tuple((name, tuple(_exact(v, 'supplied account') for v in values))
                  for name, values in exact['supplied'].items()),
            tuple(_exact(v, 'rounding account') for v in exact['rounding']),
            tuple(_exact(v, 'rounding allowance') for v in exact['allowance']), budget, None,
            _stored(arrays, 'face_occupancy_allowance', np.float64, 1))
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise SphereError('the stored material is incomplete') from exc
    except TectonicsError as exc:
        if isinstance(exc, SphereError):
            raise
        raise SphereError('the stored material is not valid: '+str(exc)) from exc
    if material.material_id != record['material_id'] or _json(material.descriptor()) != _json(dict(record)):
        raise SphereError('the stored material does not reproduce its record and identity: edited or foreign')
    _as_issued(material._packed, arrays)
    return material


# ----------------------------------------------------------------------------- the accepted sphere state

def _mass_known(state):
    return bool(state.material.phases)


_PRESENCE = {'sphere.reference_mass_kg': _mass_known, 'sphere.phase_volume_m3': _mass_known,
             'sphere.enthalpy_j': lambda state: state.material.enthalpy_basis is not None}


@dataclass(frozen=True, init=False, eq=False, slots=True)
class SphereState(_state._Immutable):
    """One network with its material at one accepted time; compare states by ``state_id``.

    Issued by initial_sphere() (a declared root), by an accepted motion step (a computed successor naming its parent
    and root) and by restore_sphere() (read back from a store). ``issued_by`` records which; it is provenance, never
    identity. The state is carried beside the I02 column envelope in an accepted ledger commit.
    """
    network: SphereNetwork
    material: SphereMaterial
    parent_state_id: str | None
    initial_state_id: str | None
    state_id: str
    _record: bytes = field(repr=False)
    _issuer: str = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('SphereState is issued by initial_sphere(), restore_sphere() or an accepted motion step')

    @property
    def issued_by(self):
        return self._issuer

    @property
    def root_state_id(self):
        return self.state_id if self.parent_state_id is None else self.initial_state_id

    @property
    def time_s(self):
        return self.network.time_s

    @property
    def step(self):
        return self.network.step

    def identities(self):
        return dict(state_id=self.state_id, root_state_id=self.root_state_id,
                    parent_state_id=self.parent_state_id, network_id=self.network.network_id,
                    geometry_id=self.network.atlas.geometry_id, material_id=self.material.material_id,
                    catalogue_id=_state.CATALOGUE_ID)

    def declaration(self):
        """Every network quantity of the I02 catalogue with its units, support, owner and presence here."""
        out = []
        for name in QUANTITIES:
            entry = _state._INDEX[name]
            known = _PRESENCE[name](self) if name in _PRESENCE else True
            out.append(dict(zip(_state.CATALOGUE_FIELDS, entry), known=known))
        return out

    def unknown(self):
        return [entry for entry in self.declaration() if not entry['known']]

    def fields(self):
        """Names of the quantities this state can return as one array."""
        return [name for name in FIELDS if name not in _PRESENCE or _PRESENCE[name](self)]

    def field(self, name):
        """One quantity as a read-only array with its units, support, owner, accepted time and identity."""
        if type(name) is not str or name not in self.fields():
            raise SphereError('unknown field; fields() lists the fields of a state')
        material, count = self.material, len(self.material.phases)
        values = {'sphere.vertex_direction': lambda: self.network.vertex_direction,
                  'sphere.face_area_m2': lambda: self.network.face_area_m2,
                  'sphere.piece_area_m2': lambda: material.stock[:, 0],
                  'sphere.reference_mass_kg': lambda: material.stock[:, 1:1+count],
                  'sphere.phase_volume_m3': lambda: material.stock[:, 1+count:1+2*count],
                  'sphere.enthalpy_j': lambda: material.stock[:, -1]}[name]()
        values = _frozen(values, values.dtype)
        _, units, support, owner, _, _, meaning = _state._INDEX[name]
        return dict(name=name, units=units, support=support, owner=owner, meaning=meaning, values=values,
                    dtype=values.dtype.str, shape=list(values.shape), state_id=self.state_id,
                    time_s=self.network.time_s, step=self.network.step)

    def descriptor(self):
        return dict(json.loads(self._record), state_id=self.state_id, network=self.network.descriptor(),
                    material=self.material.descriptor())

    def arrays(self):
        """Every stored array of the state, named as a ledger commit stores it."""
        return dict(self.network.arrays(), **self.material.arrays())

    @property
    def nbytes(self):
        return self.network.nbytes+self.material.nbytes+len(self._record)


def _sphere(network, material, parent, root, issuer, declared=False):
    if type(network) is not SphereNetwork or type(material) is not SphereMaterial:
        raise SphereError('a SphereNetwork and its SphereMaterial are required')
    if material._face_ids != network.face_ids:
        raise SphereError('the material was declared on other faces than this network')
    if declared:                         # a computed state's faces were all measured when its material was issued
        # A declaration has nothing moved yet: every frame is the sphere's axes and every copy is its vertex's own
        # direction, bit for bit, as _declared_layout makes them.
        layout = network._layout
        index = {name: i for i, name in enumerate(layout.names)}
        if (any(rotation.quaternion != IDENTITY.quaternion for _, rotation in (*layout.frames, *layout.ridges))
                or any(np.asarray(value, dtype=np.float64).tobytes() != layout.reference[index[name]].tobytes()
                       for (name, _), value in layout.views)):
            raise SphereError('a declared state needs a declaration: every frame at the sphere axes and every copy '
                              "equal to its vertex's own direction")
        if np.any(material._occupancy_allowance != 0):
            raise SphereError('a declared state carries no occupancy allowance: its pieces were declared on its faces')
        try:
            _occupancy(network, material._face, material._stock, None, material._occupancy_allowance)
        except SphereError as exc:
            raise SphereError('the material does not occupy the measured faces of this network: '+str(exc)) from exc
    if any(c.formation_end_s is not None and c.formation_end_s > network.time_s for c in material.cohorts):
        raise SphereError('a cohort forms in the future of this state')
    if (parent is None) != (root is None):
        raise SphereError('parent and root state identities are recorded together')
    record = _canonical(dict(
        schema=SCHEMA, unit_system=_state.UNIT_SYSTEM, catalogue_id=_state.CATALOGUE_ID,
        network_id=network.network_id, material_id=material.material_id,
        clock=dict(epoch_id=network.epoch_id, time_unit='SI seconds forward from the named epoch',
                   time_s=network.time_s, step=network.step),
        frame=dict(frame_id=network.sphere.frame_id, radius_m=network.sphere.radius_m),
        lineage=dict(parent_state_id=parent, initial_state_id=root)), 'sphere state')
    return _state._issue(SphereState, network=network, material=material, parent_state_id=parent,
                         initial_state_id=root, state_id=hashlib.sha256(record).hexdigest(), _record=record,
                         _issuer=issuer)


def initial_sphere(network, material):
    """The declared initial state of a network and its material: carried, not moved; nothing is born here."""
    return _sphere(network, material, None, None, _state.DECLARED, True)


def _same(value, array):
    return (type(value) is np.ndarray and value.dtype == array.dtype and value.shape == array.shape
            and value.tobytes() == array.tobytes())


def _network_joined(network):
    """True when every part of a network is the one its identity-bound record and arrays describe."""
    record, packed, atlas = json.loads(network._record), dict(network._packed), network.atlas
    layout = network._layout
    if (type(atlas) is not SphericalAtlas or type(network.sphere) is not SphericalFrame
            or type(layout) is not _Layout):
        return False
    radius = network.sphere.radius_m
    faces = tuple(Face(patch.patch_id, patch.plate_id, patch.vertex_ids, patch.holes,
                       None if patch.region_id == patch.plate_id else patch.region_id) for patch in atlas.patches)
    order = {plate.plate_id: i for i, plate in enumerate(network.plates)}
    lookup = {name: i for i, name in enumerate(layout.names)}
    local = _local(layout, network.plates)
    measured = np.asarray([(_measure([local[order[face.plate_id]][[lookup[name] for name in ring]]
                                      for ring in (face.vertex_ids, *face.holes)])*radius)*radius
                           for face in faces], dtype=np.float64)
    return (record['sphere'] == network.sphere.descriptor() and atlas.sphere == network.sphere
            and layout.names == tuple(atlas.vertex_ids)
            and _same(_frozen(_directions(layout), np.float64), _frozen(atlas.vertex_directions, np.float64))
            and record['frames'] == [list(rotation.quaternion) for _, rotation in layout.frames]
            and record['ridge_frames'] == [list(rotation.quaternion) for _, rotation in layout.ridges]
            and record['end_poles'] == [[boundary_id, role, list(pole)] for (boundary_id, role), pole in layout.poles]
            and tuple(plate for plate, _ in layout.frames) == tuple(order)
            and tuple(boundary_id for boundary_id, _ in layout.ridges) == _ridge_ids(network.boundaries)
            and _same(packed['vertex_home'], np.asarray([_home_index(layout)[home] for home in layout.home],
                                                        dtype=np.int64))
            and _same(packed['vertex_reference'], layout.reference)
            and _same(packed['view_vertex'], np.asarray([lookup[key[0]] for key, _ in layout.views], dtype=np.int64))
            and _same(packed['view_plate'], np.asarray([order[key[1]] for key, _ in layout.views], dtype=np.int64))
            and _same(packed['view_reference'], np.asarray([value for _, value in layout.views],
                                                           dtype=np.float64).reshape(-1, 3))
            and len(network._local) == len(local) and all(
                a.tobytes() == b.tobytes() for a, b in zip(network._local, local))
            and (record['epoch_id'], record['time_s'], record['step'], record['reference_time_s'])
            == (network.epoch_id, network.time_s, network.step, network.reference_time_s)
            and (record['geometry_id'], record['atlas_id']) == (atlas.geometry_id, atlas.atlas_id)
            and record['plates'] == [_plate_record(plate) for plate in network.plates]
            and record['junctions'] == [_junction_record(junction) for junction in network.junctions]
            and record['lineage'] == _lineage_record(network.lineage)
            and _unpack(packed['vertex_ids'], 'vertex identities') == list(atlas.vertex_ids)
            and network._faces == faces
            and _unpack(packed['faces'], 'faces') == [_face_record(face) for face in faces]
            and _unpack(packed['boundaries'], 'boundaries') == [_boundary_record(b) for b in network.boundaries]
            and _same(network._areas, measured)
            and network._owners == tuple(sorted(_owned(atlas, network.boundaries, network.plates)[0].items())))


def _material_joined(material):
    """True when every part of a material is the one its identity-bound record and arrays describe."""
    record, packed, link = json.loads(material._record), dict(material._packed), material.stock_link
    exact = dict(initial=[_exact_text(v) for v in material._initial],
                 supplied={name: [_exact_text(v) for v in values] for name, values in material._supplied},
                 rounding=[_exact_text(v) for v in material._rounding],
                 allowance=[_exact_text(v) for v in material._allowance])
    return (record['phases'] == list(material.phases) and record['enthalpy_basis'] == material.enthalpy_basis
            and material.columns == _columns(material.phases, material.enthalpy_basis)
            and [column['name'] for column in record['columns']] == list(material.columns)
            and record['exteriors'] == [list(pair) for pair in material.exteriors]
            and (link is None or type(link) is MappingProxyType)
            and record['stock_link'] == (None if link is None else dict(link))
            and _unpack(packed['cohorts'], 'cohorts') == [_cohort_record(cohort) for cohort in material.cohorts]
            and _same(material._face, packed['piece_face']) and _same(material._cohort, packed['piece_cohort'])
            and _same(material._stock, packed['piece_stock'])
            and _same(material._occupancy_allowance, packed['face_occupancy_allowance']) and record['exact'] == exact)


def verified(state):
    """``state`` if it is an issued SphereState whose records, arrays and parts still agree.

    Every identity is recomputed from its record and arrays, and every part a caller can read is compared with what
    those identity-bound records describe, so a look-alike, a swapped part or an edited record or array refuses. The
    pieces of every face must occupy its measured area within the relative tolerance or its occupancy allowance. As
    in integration_state, introspection that rewrites a whole state and all its identities consistently is not
    defended, and ``issued_by`` is provenance, not identity.
    """
    if type(state) is not SphereState:
        raise SphereError('a SphereState issued by initial_sphere(), restore_sphere() or a motion step is required')
    network, material = state.network, state.material
    if type(network) is not SphereNetwork or type(material) is not SphereMaterial:
        raise SphereError('state parts are not the issued network and material records')
    try:
        if (hashlib.sha256(state._record).hexdigest() != state.state_id
                or _identity(network._record, network._packed) != network.network_id
                or _identity(material._record, material._packed) != material.material_id):
            raise SphereError('a record or array no longer reproduces its identity: edited or forged state')
        record = json.loads(state._record)
        joined = ((record['network_id'], record['material_id']) == (network.network_id, material.material_id)
                  and record['lineage'] == dict(parent_state_id=state.parent_state_id,
                                                initial_state_id=state.initial_state_id)
                  and record['clock'] == dict(epoch_id=network.epoch_id, time_s=network.time_s, step=network.step,
                                              time_unit='SI seconds forward from the named epoch')
                  and record['frame'] == dict(frame_id=network.sphere.frame_id, radius_m=network.sphere.radius_m)
                  and material._face_ids == network.face_ids
                  and _network_joined(network) and _material_joined(material))
    except SphereError:
        raise
    except (TectonicsError, KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        raise SphereError('state parts disagree with their identity-bound records: edited or forged state') from exc
    if not joined:
        raise SphereError('state parts disagree with their identity-bound records: edited or forged state')
    _occupancy(network, material._face, material._stock, None, material._occupancy_allowance)
    return state


def bound(root, state, inventory, exteriors):
    """Check that ``state`` can stand beside the I02 column state ``root`` in its ledger; returns the state.

    The network shares the root's epoch and unit system and stands at the same accepted time and step. A stock link
    names declared exchange exteriors of the right roles, and then the pieces and the finite stocks describe the same
    components in the same enthalpy basis. ``inventory`` and ``exteriors`` are the root exchange's W08 stocks and
    declared (name, role) pairs, or None and () without finite stocks.
    """
    state = verified(state)
    network, material = state.network, state.material
    if (network.epoch_id, network.time_s, network.step) != (root.epoch_id, root.time_s, root.column.accepted_steps):
        raise SphereError('the network is not dated at the accepted epoch, time and step of the column state')
    if json.loads(state._record)['unit_system'] != root.unit_system:
        raise SphereError('the network is declared in another unit system')
    link = material.stock_link
    if link is not None:
        if inventory is None:
            raise SphereError('a stock link needs attached finite stocks; none are attached')
        roles = dict(exteriors)
        if link['receives'] is not None and roles.get(link['receives']) != 'sink':
            raise SphereError('the network receives from finite stocks through a declared exchange sink')
        if link['returns'] is not None and roles.get(link['returns']) != 'source':
            raise SphereError('the network returns to finite stocks through a declared exchange source')
        if tuple(inventory.component_ids) != material.phases:
            raise SphereError('the finite stocks and the network pieces carry different components')
        if inventory.enthalpy_source != material.enthalpy_basis:
            raise SphereError('the finite stocks and the network pieces use different enthalpy bases')
    return state


def summary(state):
    """Identities and sizes of a state for inspection."""
    return dict(state.identities(), time_s=state.network.time_s, step=state.network.step,
                faces=len(state.network.face_ids), pieces=len(state.material.piece_face))


_STATE_KEYS = frozenset(('schema', 'unit_system', 'catalogue_id', 'network_id', 'material_id', 'clock', 'frame',
                         'lineage', 'state_id', 'network', 'material'))


def restore_sphere(record, arrays, *, limits=None, budget=None, cancel=None, exclusive=False):
    """Rebuild a stored state through the validating constructors; every record and identity must reproduce.

    The network is validated again as a closed atlas, and the material's exact accounts must close on its stored
    pieces. The pieces of every face, of a declared or a computed state, must occupy its measured area. Every stored
    array must have exactly the type, shape and bytes of the rebuilt one: nothing is cast, rebound or repaired.
    ``exclusive`` also refuses any other stored 'sphere.*' array, as for a root snapshot, which holds no step.
    """
    names = {'sphere.'+name for name in NETWORK_ARRAYS+MATERIAL_ARRAYS}
    if not isinstance(record, Mapping) or set(record) != _STATE_KEYS or record['schema'] != SCHEMA:
        raise SphereError('the stored sphere state is not of this schema')
    if not isinstance(arrays, Mapping) or not names <= set(arrays):
        raise SphereError('the stored sphere state is missing arrays')
    if exclusive and {name for name in arrays if type(name) is str and name.startswith('sphere.')} != names:
        raise SphereError('the stored sphere state holds arrays that are not its own: edited or foreign')
    try:
        lineage = record['lineage']
        parent, root = lineage['parent_state_id'], lineage['initial_state_id']
        for value in (parent, root):
            if value is not None:
                _sha(value, 'lineage identity')
    except (KeyError, TypeError) as exc:
        raise SphereError('the stored sphere state is incomplete') from exc
    declared = parent is None
    network = restore_network(record['network'], arrays, limits=limits, budget=budget, cancel=cancel)
    material = restore_material(network, record['material'], arrays, budget=budget)
    state = _sphere(network, material, parent, root, _state.RESTORED, declared)
    if state.state_id != record['state_id'] or _json(state.descriptor()) != _json(dict(record)):
        raise SphereError('the stored sphere state does not reproduce its record and identity: edited or foreign')
    return state
