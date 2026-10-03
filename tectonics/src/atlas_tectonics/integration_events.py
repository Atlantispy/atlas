"""I03.4: joint geometry commits of supplied topology events (atlas.topology-transactions.v1). WORKING NON-CANON.

Supplied, supported proposals only, in prescribed_history_v1: a plate split, a plate merge, and a ridge jump as
prescribed history (a split of the plate the ridge jumps into, then a merge across the old ridge, in one joint
proposal). They travel inside the integration_transfer.Motion of the interval they end, and are applied to the
interval's endpoint, after its motion and any mesh change. So the I02 clock and ledger commit them with that
interval's steps, in one transaction, or not at all; restoring a commit applies them again.

Each event declares its time. It takes effect only at the end of the interval that ends at that time: the I02
clock's schedule places interval ends, a supplied event is located exactly there (atlas.event-transaction.v1's
bracketing has nothing left to find), and nothing is applied in the middle of an interval. An event whose time falls
inside an interval needs that interval divided at it, at a whole step of the clock's schedule.

Ownership changes only by whole faces, so every ownership intersection is exact: a supplied split follows existing
edges, and a split through faces needs a mesh change in the same interval first. Material is not moved: a face keeps
its pieces, and only the plate that owns it changes. Fresh identities are required, and retired ones stay reserved.

Refused, each with its own cause:
- a standalone retirement: v1's trench consumption cannot bring a plate's area to zero, because an exhausted cell
  is refused;
- junction reorganisation, generated separation, subduction initiation and rift migration: no admitted law;
- a merge of plates that do not move together over its interval;
- a split whose new boundary ends inside a plate;
- two events of one interval whose footprints share a plate, including a plate one of them creates (they are one
  joint proposal);
- two events of one interval that cut the same record: the pieces would be named after whichever cut ran first.

An event carries no finite-stock demand of its own. The interval's transfer step aggregates every finite stock it
draws, so a joint demand beyond a stock refuses the whole interval, events included.

A face an event carries into another plate's frame, or whose vertices change home, is measured again there (D7'',
approved 3 October 2026 with conditions; see _reexpressed). Its measure may change by rounding only: within
C7(R) + C7(R') + 4 eps P, times R^2, the C7 terms zero above the C7 range. Its occupancy allowance then takes the exact
change. Beyond that bound the event is refused, because the change is a displacement, not rounding.

Events with disjoint footprints are applied in canonical event-identity order, and the result is checked against the
reverse order. The lineage records the interval's event identities once, in canonical order (a ridge jump's own
identity, then its split's and its merge's), whatever order they were applied in.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math

import numpy as np

from . import integration_sphere as _sphere
from ._validation import TectonicsError, scalar

SCHEMA = 'atlas.i03-topology-event.v1'
BASIS = 'prescribed_history_v1'
REEXPRESSION_ROUNDING = 4*float(np.finfo(float).eps)    # C10's rounding of placement and pull-back, per vertex (D7'')


class EventRefused(TectonicsError):
    """A topology event that this version does not commit; the message names the cause."""


def _token(value, label):
    if type(value) is not str or not value or len(value) > 256 or not value.isascii() or '|' in value:
        raise EventRefused('%s is a non-empty ASCII string of at most 256 characters without "|"' % label)
    return value


def _time(value):
    try:
        return scalar(value, 'an event time')+0.
    except TectonicsError as exc:
        raise EventRefused('an event declares its time, a finite number of epoch seconds') from exc


def _faces(values, label):
    if type(values) not in (tuple, list) or not values or any(type(name) is not str for name in values):
        raise EventRefused('%s names at least one face, by its identity' % label)
    names = tuple(sorted(values))
    if len(set(names)) != len(names):
        raise EventRefused('%s names each face once' % label)
    return names


@dataclass(frozen=True)
class Split:
    """Plate ``plate_id`` divided into two fresh plates along a new boundary record that follows existing edges.

    ``parts`` is ((new plate, its faces), (new plate, its faces)): together exactly the plate's faces at ``time_s``.
    ``boundary`` is the new record between the two new plates (a fresh identity; its origin is this event).
    """
    event_id: str
    plate_id: str
    parts: tuple
    boundary: _sphere.Boundary
    time_s: float
    basis: str = BASIS

    def __post_init__(self):
        _token(self.event_id, 'an event identity')
        _token(self.plate_id, 'a plate identity')
        if (type(self.parts) not in (tuple, list) or len(self.parts) != 2
                or any(type(part) not in (tuple, list) or len(part) != 2 for part in self.parts)):
            raise EventRefused('a split names exactly two new plates, each with its faces')
        parts = tuple((_token(name, 'a new plate identity'), _faces(faces, 'a new plate'))
                      for name, faces in self.parts)
        if parts[0][0] == parts[1][0] or set(parts[0][1]) & set(parts[1][1]):
            raise EventRefused('the two new plates of a split are distinct and own distinct faces')
        object.__setattr__(self, 'parts', tuple(sorted(parts)))
        if type(self.boundary) is not _sphere.Boundary:
            raise EventRefused('a split declares its new boundary record')
        _token(self.boundary.boundary_id, 'a new boundary identity')       # '|' is reserved for cut records
        if {self.boundary.left_plate_id, self.boundary.right_plate_id} != {parts[0][0], parts[1][0]}:
            raise EventRefused('the new boundary separates the two new plates')
        if self.boundary.origin != _sphere.Origin(_sphere.EVENT, self.event_id):
            raise EventRefused("the new boundary's origin is this event")
        object.__setattr__(self, 'time_s', _time(self.time_s))
        _basis(self.basis)

    def footprint(self):
        """The plates the event touches: the one it divides and the two it creates."""
        return {self.plate_id} | {name for name, _ in self.parts}

    def record(self):
        return dict(schema=SCHEMA, type='split', event_id=self.event_id, plate_id=self.plate_id, basis=self.basis,
                    time_s=self.time_s, parts=[[name, list(faces)] for name, faces in self.parts],
                    boundary=_boundary_record(self.boundary))


@dataclass(frozen=True)
class Merge:
    """Plates ``plates`` joined into the fresh plate ``new_plate_id``; every record between them retires (a suture)."""
    event_id: str
    plates: tuple
    new_plate_id: str
    time_s: float
    basis: str = BASIS

    def __post_init__(self):
        _token(self.event_id, 'an event identity')
        if type(self.plates) not in (tuple, list) or len(self.plates) != 2 or self.plates[0] == self.plates[1]:
            raise EventRefused('a merge joins exactly two distinct plates')
        object.__setattr__(self, 'plates', tuple(sorted(_token(name, 'a plate identity') for name in self.plates)))
        _token(self.new_plate_id, 'a new plate identity')
        object.__setattr__(self, 'time_s', _time(self.time_s))
        _basis(self.basis)

    def footprint(self):
        """The plates the event touches: the two it joins and the one it creates."""
        return set(self.plates) | {self.new_plate_id}

    def record(self):
        return dict(schema=SCHEMA, type='merge', event_id=self.event_id, plates=list(self.plates),
                    new_plate_id=self.new_plate_id, time_s=self.time_s, basis=self.basis)


@dataclass(frozen=True)
class RidgeJump:
    """A prescribed ridge jump: ``split`` divides the plate the ridge jumps into along the new ridge, and ``merge``
    joins the slice it leaves behind to the plate across the old ridge, which retires (I01 D6 §9: a split plus a
    retirement, never inferred from labels). One joint proposal, applied as one."""
    event_id: str
    split: Split
    merge: Merge
    basis: str = BASIS

    def __post_init__(self):
        _token(self.event_id, 'an event identity')
        if type(self.split) is not Split or type(self.merge) is not Merge:
            raise EventRefused('a ridge jump is a Split and a Merge')
        if self.split.boundary.kind != _sphere.RIDGE:
            raise EventRefused('a ridge jump creates a ridge')
        new = {name for name, _ in self.split.parts}
        if len(new & set(self.merge.plates)) != 1 or self.split.plate_id in self.merge.plates:
            raise EventRefused('a ridge jump merges one slice of the split plate with the plate across the old ridge')
        if len({self.event_id, self.split.event_id, self.merge.event_id}) != 3:
            raise EventRefused('a ridge jump and its two components have distinct event identities')
        if self.split.time_s != self.merge.time_s:
            raise EventRefused('the split and the merge of a ridge jump take effect at one time')
        _basis(self.basis)

    @property
    def time_s(self):
        return self.split.time_s

    def footprint(self):
        return self.split.footprint() | self.merge.footprint()

    def record(self):
        return dict(schema=SCHEMA, type='ridge_jump', event_id=self.event_id, basis=self.basis,
                    split=self.split.record(), merge=self.merge.record())


@dataclass(frozen=True)
class Retire:
    """A plate retirement on its own: refused when applied, with its cause (see the module docstring)."""
    event_id: str
    plate_id: str
    time_s: float
    basis: str = BASIS

    def __post_init__(self):
        _token(self.event_id, 'an event identity')
        _token(self.plate_id, 'a plate identity')
        object.__setattr__(self, 'time_s', _time(self.time_s))
        _basis(self.basis)

    def footprint(self):
        return {self.plate_id}

    def record(self):
        return dict(schema=SCHEMA, type='retire', event_id=self.event_id, plate_id=self.plate_id, time_s=self.time_s,
                    basis=self.basis)


EVENT_TYPES = (Split, Merge, RidgeJump, Retire)


def _basis(value):
    if value != BASIS:
        raise EventRefused('only supplied prescribed-history proposals are supported (basis %r); a generated event '
                           'needs an admitted law' % BASIS)


def _boundary_record(boundary):
    return dict(boundary_id=boundary.boundary_id, kind=boundary.kind, left_plate_id=boundary.left_plate_id,
                right_plate_id=boundary.right_plate_id, vertex_ids=list(boundary.vertex_ids),
                origin=[boundary.origin.kind, boundary.origin.reference], closed=boundary.closed,
                subducting_side=boundary.subducting_side, accretion_fraction=boundary.accretion_fraction,
                carrier_side=boundary.carrier_side)


def _boundary_from(row):
    return _sphere.Boundary(row['boundary_id'], row['kind'], row['left_plate_id'], row['right_plate_id'],
                            tuple(row['vertex_ids']), _sphere.Origin(*row['origin']), row['closed'],
                            row['subducting_side'], row['accretion_fraction'], row['carrier_side'])


def from_record(row):
    """An event proposal rebuilt from its stored record; it must reproduce the record exactly."""
    try:
        kind = row['type']
        if row['schema'] != SCHEMA:
            raise EventRefused('the stored event is not of this schema')
        if kind == 'split':
            event = Split(row['event_id'], row['plate_id'], tuple((name, tuple(faces)) for name, faces in row['parts']),
                          _boundary_from(row['boundary']), row['time_s'], row['basis'])
        elif kind == 'merge':
            event = Merge(row['event_id'], tuple(row['plates']), row['new_plate_id'], row['time_s'], row['basis'])
        elif kind == 'ridge_jump':
            event = RidgeJump(row['event_id'], from_record(row['split']), from_record(row['merge']), row['basis'])
        elif kind == 'retire':
            event = Retire(row['event_id'], row['plate_id'], row['time_s'], row['basis'])
        else:
            raise EventRefused('unknown stored event type')
    except (KeyError, TypeError, ValueError) as exc:
        raise EventRefused('the stored event record is incomplete') from exc
    if json.dumps(event.record(), sort_keys=True) != json.dumps(row, sort_keys=True):
        raise EventRefused('the stored event does not reproduce its record')
    return event


def checked(events):
    """The events of one Motion, typed, with distinct identities, in canonical order."""
    if type(events) not in (tuple, list):
        raise EventRefused('events are a sequence of event proposals')
    if any(type(event) not in EVENT_TYPES for event in events):
        raise EventRefused('events are Split, Merge, RidgeJump or Retire proposals')
    ids = [name for event in events for name in _identities(event)]
    if len(set(ids)) != len(ids):
        raise EventRefused('each event identity once, components included')
    return tuple(sorted(events, key=lambda event: event.event_id))


def _identities(event):
    """The identities an event adds to the lineage: its own, then its components'."""
    if type(event) is RidgeJump:
        return event.event_id, event.split.event_id, event.merge.event_id
    return (event.event_id,)


# ----------------------------------------------------------------------------- applying events

def applied(network, material, events, stage, budget=None, cancel=None):
    """(network, material, records) after the ``events`` of one interval, at its endpoint.

    ``network`` is the interval's endpoint: each event's time must be its time, the end of the interval.
    ``stage`` maps each plate of ``network`` to its stage rotation over the interval. Footprints must be disjoint:
    events that share a plate are one joint proposal. They are applied in canonical event-identity order; with more
    than one, the reverse order must give the identical network and material.
    """
    events = checked(events)
    for event in events:
        if event.time_s != network.time_s:
            raise EventRefused('event %r is declared at %r s, but this interval ends at %r s: an event takes effect '
                               'only at the end of the interval that ends at its time; divide the interval there, at '
                               'a whole step of the clock' % (event.event_id, event.time_s, network.time_s))
    ids = tuple(name for event in events for name in _identities(event))
    for name in ids:
        if name in network.lineage.events:
            raise EventRefused('event %r was already applied to this network: replay is refused' % name)
    ids = network.lineage.events+ids
    seen, cut = {}, {}
    for event in events:
        for plate in event.footprint():
            if plate in seen:
                raise EventRefused('events %r and %r both touch plate %r: a shared footprint is one joint proposal, '
                                   'never two events' % (seen[plate], event.event_id, plate))
            seen[plate] = event.event_id
        for record in _cuts(network, event):
            if record in cut:
                raise EventRefused('events %r and %r both cut record %r: the pieces of a record cut twice in one '
                                   'interval would be named after whichever cut ran first, so the second cut belongs '
                                   'to a later interval' % (cut[record], event.event_id, record))
            cut[record] = event.event_id
    forward = _in_order(network, material, events, stage, budget, cancel, ids)
    if len(events) > 1:
        backward = _in_order(network, material, events[::-1], stage, budget, cancel, ids)
        if (backward[0].network_id, backward[1].material_id) != (forward[0].network_id, forward[1].material_id):
            raise EventRefused('the events of this interval give different networks in the two orders: their '
                               'footprints are not independent')
    return forward[0], forward[1], tuple(event.record() for event in events)


def _in_order(network, material, events, stage, budget, cancel, ids):
    """The events applied one after another; every network on the way records the interval's identities ``ids``."""
    for event in events:
        network, material = _one(network, material, event, stage, budget, cancel, ids)
    return network, material


def _one(network, material, event, stage, budget, cancel, ids):
    if type(event) is Retire:
        raise EventRefused('plate %r cannot retire on its own: a plate retires when its area reaches zero through '
                           'bracketed consumption, which this version cannot reach (an exhausted boundary cell is '
                           'refused); its identity is retired by a split, merge or ridge jump' % event.plate_id)
    if type(event) is Split:
        return _split(network, material, event, budget, cancel, ids)
    if type(event) is Merge:
        return _merge(network, material, event, stage, budget, cancel, ids)
    network, material = _split(network, material, event.split, budget, cancel, ids)
    ridges = [b for b in network.boundaries if {b.left_plate_id, b.right_plate_id} == set(event.merge.plates)]
    if not ridges or any(b.kind != _sphere.RIDGE for b in ridges):
        raise EventRefused('a ridge jump retires the old ridge between %r and %r; no ridge separates them'
                           % event.merge.plates)
    # The slice moved with the split plate over the interval and is captured at its end: no common motion is due.
    # The grown plate continues the plate across the old ridge, its frame and its total rotation.
    across = [plate for plate in event.merge.plates if plate not in {name for name, _ in event.split.parts}][0]
    return _merge(network, material, event.merge, stage, budget, cancel, ids, captured=True, keeper=across)


def _fresh(network, plates=(), boundaries=()):
    lineage = network.lineage
    for name in plates:
        if name in network.plate_ids or name in lineage.retired_plate_ids:
            raise EventRefused('plate identity %r is in use or retired: a new plate takes a fresh identity' % name)
    taken = {b.boundary_id for b in network.boundaries} | set(lineage.retired_boundary_ids)
    for name in boundaries:
        if name in taken:
            raise EventRefused('boundary identity %r is in use or retired: a new record takes a fresh identity'
                               % name)


def _edge_faces(network, plate):
    """{frozenset(edge): face ID} for the faces of ``plate``."""
    out = {}
    for face in network.faces:
        if face.plate_id != plate:
            continue
        for ring in (face.vertex_ids, *face.holes):
            for a, b in zip(ring, ring[1:]+ring[:1]):
                out[frozenset((a, b))] = face.face_id
    return out


def _split(network, material, event, budget, cancel, ids):
    plate = event.plate_id
    if plate not in network.plate_ids:
        raise EventRefused('plate %r is not a plate of this network' % plate)
    (first, first_faces), (second, second_faces) = event.parts
    _fresh(network, (first, second), (event.boundary.boundary_id,))
    own = {face.face_id for face in network.faces if face.plate_id == plate}
    if set(first_faces) | set(second_faces) != own:
        raise EventRefused('the two parts of a split own exactly the faces of plate %r' % plate)
    new_plate = {name: first for name in first_faces} | {name: second for name in second_faces}
    on_border = {name for b in network.boundaries for name in b.vertex_ids}
    chain = event.boundary.vertex_ids
    if not event.boundary.closed and (chain[0] not in on_border or chain[-1] not in on_border):
        raise EventRefused('the new boundary of a split ends inside plate %r: it must join existing boundaries or '
                           'junctions' % plate)
    faces = tuple(_sphere.Face(f.face_id, new_plate.get(f.face_id, f.plate_id) if f.plate_id == plate else f.plate_id,
                               f.vertex_ids, f.holes, f.block_id) for f in network.faces)
    edges = _edge_faces(network, plate)
    boundaries, retired, derived = [], [], {}
    for b in network.boundaries:
        if plate not in (b.left_plate_id, b.right_plate_id):
            boundaries.append(b)
            continue
        steps = list(zip(b.vertex_ids, b.vertex_ids[1:]))+([(b.vertex_ids[-1], b.vertex_ids[0])] if b.closed else [])
        sides = [new_plate[edges[frozenset(step)]] for step in steps]
        if len(set(sides)) == 1:
            boundaries.append(_resided(b, plate, sides[0]))
            continue
        if b.closed:
            raise EventRefused('a split crossing the closed record %r needs it opened at a junction first'
                               % b.boundary_id)
        cuts = [k for k in range(1, len(sides)) if sides[k] != sides[k-1]]
        pieces, start = [], 0
        for cut in cuts+[len(sides)]:
            pieces.append((b.vertex_ids[start:cut+1], sides[start]))
            start = cut
        retired.append(b.boundary_id)
        for k, (part, side) in enumerate(pieces):
            name = '%s|%s|%d' % (b.boundary_id, event.event_id, k)
            _fresh(network, (), (name,))
            derived[name] = b.boundary_id
            boundaries.append(_resided(_sphere.Boundary(name, b.kind, b.left_plate_id, b.right_plate_id, part,
                                                        _sphere.Origin(_sphere.EVENT, event.event_id), False,
                                                        b.subducting_side, b.accretion_fraction, b.carrier_side),
                                       plate, side))
    boundaries.append(event.boundary)
    plates = tuple(p for p in network.plates if p.plate_id != plate)+tuple(
        _sphere.Plate(name, network.plate(plate).rotation, (plate,)) for name in (first, second))
    frames = dict(network.frames)
    for name in (first, second):
        frames[name] = frames[plate]
    source = {name: plate for name in (first, second)}
    lineage = _lineage(network, ids, retired, (plate,))
    return _rebuilt(network, material, faces, plates, tuple(boundaries), lineage, frames, source, derived, {},
                    budget, cancel)


def _cuts(network, event):
    """The records a split (or a ridge jump's split) would cut on ``network``: those whose side changes along them."""
    split = event.split if type(event) is RidgeJump else event
    if type(split) is not Split or split.plate_id not in network.plate_ids:
        return set()
    new_plate = {name: part for part, faces in split.parts for name in faces}
    edges = _edge_faces(network, split.plate_id)
    out = set()
    for b in network.boundaries:
        if split.plate_id not in (b.left_plate_id, b.right_plate_id):
            continue
        steps = list(zip(b.vertex_ids, b.vertex_ids[1:]))+([(b.vertex_ids[-1], b.vertex_ids[0])] if b.closed else [])
        sides = {new_plate.get(edges.get(frozenset(step))) for step in steps}
        if len(sides) > 1:
            out.add(b.boundary_id)
    return out


def _resided(boundary, old, new):
    left = new if boundary.left_plate_id == old else boundary.left_plate_id
    right = new if boundary.right_plate_id == old else boundary.right_plate_id
    return _sphere.Boundary(boundary.boundary_id, boundary.kind, left, right, boundary.vertex_ids, boundary.origin,
                            boundary.closed, boundary.subducting_side, boundary.accretion_fraction,
                            boundary.carrier_side)


def _merge(network, material, event, stage, budget, cancel, ids, captured=False, keeper=None):
    """Two plates joined. The new plate continues ``keeper`` (its frame and total rotation): the plate across the old
    ridge for a ridge jump, otherwise the larger plate by its exact rational piece-area account, and on an exact tie the
    first in identity order (a declared convention, so on an exact tie it depends on the names)."""
    a, b = event.plates
    for plate in (a, b):
        if plate not in network.plate_ids:
            raise EventRefused('plate %r is not a plate of this network' % plate)
    _fresh(network, (event.new_plate_id,))
    from . import integration_transfer as _transfer
    if not captured and (a not in stage or b not in stage):
        raise EventRefused('plates %r and %r need their stage rotations over the interval of their merge' % (a, b))
    if not captured and _transfer._signed(stage[a]) != _transfer._signed(stage[b]):
        raise EventRefused('plates %r and %r do not move together over the interval of their merge: a merge needs '
                           'relative motion within tolerance (here, one stage rotation)' % (a, b))
    new = event.new_plate_id
    faces = tuple(_sphere.Face(f.face_id, new if f.plate_id in (a, b) else f.plate_id, f.vertex_ids, f.holes,
                               f.block_id) for f in network.faces)
    boundaries, retired = [], []
    for record in network.boundaries:
        sides = {record.left_plate_id, record.right_plate_id}
        if sides == {a, b}:
            retired.append(record.boundary_id)                  # the suture: its identity stays reserved
        elif sides & {a, b}:
            boundaries.append(_resided(_resided(record, a, new), b, new))
        else:
            boundaries.append(record)
    if not retired:
        raise EventRefused('plates %r and %r share no boundary record: they cannot merge' % (a, b))
    if keeper is None:
        area = _exact_areas(network, material)
        keeper = a if area[a] >= area[b] else b             # a precedes b in identity order
    other = b if keeper == a else a
    plates = tuple(p for p in network.plates if p.plate_id not in (a, b))+(
        _sphere.Plate(new, network.plate(keeper).rotation, (a, b)),)
    frames = dict(network.frames)
    frames[new] = frames[keeper]
    lineage = _lineage(network, ids, retired, (a, b))
    return _rebuilt(network, material, faces, plates, tuple(boundaries), lineage, frames, {new: keeper}, {},
                    {new: other}, budget, cancel)


def _exact_areas(network, material):
    """{plate: the exact sum of its pieces' area accounts}, as rationals: no measure and no rounding decides."""
    from fractions import Fraction
    column = material.columns.index('area_m2')
    out = {plate: Fraction(0) for plate in network.plate_ids}
    for row in range(len(material.piece_face)):
        out[network.faces[int(material.piece_face[row])].plate_id] += Fraction(float(material.stock[row, column]))
    return out


def _lineage(network, ids, boundaries, plates):
    old = network.lineage
    return _sphere.Lineage(old.parent_network_id, old.root_network_id, tuple(ids),
                           old.retired_face_ids, tuple(sorted(old.retired_boundary_ids+tuple(boundaries))),
                           tuple(sorted(old.retired_plate_ids+tuple(plates))))


def _rebuilt(network, material, faces, plates, boundaries, lineage, frames, source, derived, joined, budget, cancel):
    """The network after an event and its material on it.

    Every vertex keeps the coordinates it had in the frame of the plate (``source`` maps a new plate to the old plate
    whose frame and coordinates it inherits) or ridge record (``derived`` maps a record split from an old one) that
    keeps it. A merged plate also takes the faces of a second plate (``joined`` maps it to that plate): their
    vertices are carried into its frame, except those it already has. Record-end poles are carried into their
    carrier's frame where the record end persists, and formed afresh where it is new, in the carrier's frame.
    """
    boundaries = tuple(sorted(boundaries, key=lambda record: record.boundary_id))   # homes break ties in this order
    layout = network._layout
    names = layout.names
    index = {name: i for i, name in enumerate(names)}
    order = {plate: i for i, plate in enumerate(network.plate_ids)}
    directions = _sphere._directions(layout)
    old_home = dict(zip(names, layout.home))
    old_frames = dict(network.frames)
    ridge_frames = dict(layout.ridges)

    def local(plate, name):
        old = source.get(plate, plate)
        value = network._local[order[old]][index[name]]
        if np.all(np.isfinite(value)):
            return value
        other = joined.get(plate)
        if other is None:
            raise EventRefused('vertex %r has no coordinates for plate %r' % (name, plate))
        carried = old_frames[other].then(frames[plate].inverse())
        return _sphere._placed(carried, network._local[order[other]][index[name]])[0]

    ridges = {}
    for b in boundaries:
        if b.kind == _sphere.RIDGE:
            origin = derived.get(b.boundary_id, b.boundary_id)
            ridges[b.boundary_id] = ridge_frames.get(origin, _sphere.IDENTITY)
    home = _sphere._homes(names, faces, boundaries)
    reference = np.empty_like(layout.reference)
    for k, name in enumerate(names):
        keeper = home[k]
        if type(keeper) is tuple:
            origin = derived.get(keeper[1], keeper[1])
            if old_home[name] == (_sphere.RIDGE, origin):
                reference[k] = layout.reference[k]
            else:
                reference[k] = _sphere._placed(ridges[keeper[1]].inverse(), directions[k])[0]
        else:
            reference[k] = local(keeper, name)
    used = _sphere._used(faces)
    owner = dict(zip(names, home))
    views = tuple(sorted(((name, plate), tuple(float(x) for x in local(plate, name))) for name, plate in used
                         if owner[name] != plate))
    plate_frames = tuple(sorted((p.plate_id, frames[p.plate_id]) for p in plates))
    ridge_rows = tuple(sorted(ridges.items()))
    draft = _sphere._Layout(names, home, reference, views, plate_frames, ridge_rows, None)
    sphere, args = network.sphere, (network.epoch_id, network.time_s, network.step, network.reference_time_s,
                                    lineage, None, budget, cancel)
    try:
        first = _sphere._network(sphere, draft, faces, plates, boundaries, *args[:4], args[4], args[5], args[6],
                                 args[7], False)
        poles = _poles(network, first, frames, ridges, derived)
        final = _sphere._network(sphere, _sphere._Layout(names, home, reference, views, plate_frames, ridge_rows,
                                                        poles), faces, plates, boundaries, *args[:4], args[4],
                                 args[5], args[6], args[7], False)
    except EventRefused:
        raise
    except TectonicsError as exc:
        raise EventRefused('the network after the event is not a valid closed network: %s' % exc) from exc
    if final.face_ids != network.face_ids:
        raise EventRefused('an event keeps every face, with its identity')
    allowance = _reexpressed(network, final, material.occupancy_allowance_m2)
    try:
        result = _sphere._material(final, material.phases, material.enthalpy_basis, material.cohorts,
                                   material.exteriors, material.stock_link, np.asarray(material.piece_face),
                                   np.asarray(material.piece_cohort), np.asarray(material.stock), material._initial,
                                   material._supplied, material._rounding, material._allowance, budget,
                                   occupancy_allowance=allowance)
    except TectonicsError as exc:
        again = [name for k, name in enumerate(final.face_ids)
                 if float(final.face_area_m2[k]) != float(network.face_area_m2[k])]
        if again:
            raise EventRefused('the material does not occupy the network after the event: %s. The event carries %d '
                               'face(s) into another frame, where each is measured again in the frame of its new '
                               "plate (first: %r); where C7 is undefined for such a face, D7'' admits no allowance "
                               'and the existing check alone decides' % (exc, len(again), again[0])) from exc
        raise EventRefused('the material does not occupy the network after the event: %s' % exc) from exc
    return final, result


def _reexpression_bound(old_rings, new_rings, area_m2, radius):
    """The most an event can change a face's measure by re-expressing its rings, in m2 (D7''), or None.

    C7(R) + C7(R') + 4 eps P, times R^2: C7 bounds each measure's rounding, and re-placing every vertex by one composed
    rotation moves it by at most 4 eps (C10), which changes the exact area by at most P times that. Above the C7 range
    (area over perimeter above twice THIN_FACE_RATIO) the C7 terms are zero, as D7''s ceiling says, and 4 eps P alone
    remains. Within the range, None where C7 is undefined (a vertex beyond 45 degrees of its anchor).
    """
    from . import integration_transfer as _transfer
    perimeter = math.fsum(float(_transfer._angle(a, b)) for ring in new_rings
                          for a, b in zip(ring, np.roll(ring, -1, axis=0)))
    bound = REEXPRESSION_ROUNDING*perimeter
    if area_m2/radius**2/perimeter <= 2*_transfer.THIN_FACE_RATIO:
        old, new = _sphere._measure_bound(old_rings), _sphere._measure_bound(new_rings)
        if old is None or new is None:
            return None
        bound += old+new
    return bound*radius**2


def _reexpressed(network, final, allowance):
    """Each face's occupancy allowance after an event (D7'', approved 3 October 2026 with conditions).

    An event changes no face's geometry on the sphere, so a face whose measure changes was re-expressed in another
    frame or had vertices re-homed, and only those faces are touched. Its change delta = mu' - mu is exact (Sterbenz:
    the two measures lie within a factor 2). Within _reexpression_bound, its allowance becomes what the per-face check
    allowed it before, max(1e-12 mu, E), plus |delta|: the pieces were within that of mu, and mu' is exactly |delta|
    from mu, so the identity closes exactly. This is an exception to D7''s zero ceiling above the C7 range, because
    re-expression is a distinct rounding source. Beyond the bound the event is refused.
    """
    radius = network.sphere.radius_m
    out = np.array(allowance, dtype=np.float64, copy=True)
    for k, name in enumerate(final.face_ids):
        before, after = float(network.face_area_m2[k]), float(final.face_area_m2[k])
        if before == after:
            continue
        if not after/2 <= before <= 2*after:
            raise EventRefused('face %r would change its measure from %r to %r m2 when measured again after the event'
                               % (name, before, after))
        delta = abs(after-before)
        bound = _reexpression_bound(network.face_coordinates(k), final.face_coordinates(k), after, radius)
        if bound is None:
            continue
        if not delta <= bound:
            raise EventRefused("face %r is measured again %r m2 from its measure before the event, beyond its D7'' "
                               'bound of %r m2: a displacement, not rounding' % (name, delta, bound))
        out[k] = max(_sphere.RELATIVE_TOLERANCE*before, float(out[k]))+delta
    return out


def _poles(old, first, frames, ridges, derived):
    """Record-end poles of the new network, each in its record's carrier frame (M6).

    A record end that persists (same record identity and end) keeps its stored pole, carried into its carrier's new
    frame when the carrier changed frame. A new end, or a record split from an old one, gets a pole formed now from
    the end segment's directions, as at a declaration, then expressed in its carrier's frame.
    """
    kept = dict(old._layout.poles or ())
    record_old = {b.boundary_id: b for b in old.boundaries}
    record_new = {b.boundary_id: b for b in first.boundaries}
    formed = dict(_sphere._end_poles(first.vertex_ids, first.vertex_direction, first.boundaries, first.junctions))

    def frame_of(boundary, plates_frames):
        carrier = _sphere._carrier(boundary)
        return ridges.get(carrier[1], _sphere.IDENTITY) if type(carrier) is tuple else plates_frames[carrier]

    old_plate_frames = dict(old.frames)
    old_ridges = dict(old._layout.ridges)
    out = {}
    for key, pole in formed.items():
        boundary = record_new[key[0]]
        if key in kept and key[0] in record_old and record_old[key[0]].vertex_ids == boundary.vertex_ids:
            before = record_old[key[0]]
            carrier = _sphere._carrier(before)
            old_frame = old_ridges[carrier[1]] if type(carrier) is tuple else old_plate_frames[carrier]
            new_frame = frame_of(boundary, frames)
            if tuple(old_frame.quaternion) == tuple(new_frame.quaternion):
                out[key] = kept[key]
            else:
                turned = old_frame.then(new_frame.inverse())
                out[key] = tuple(float(x) for x in _sphere._placed(turned, np.asarray(kept[key]))[0])
        else:
            out[key] = tuple(float(x) for x in _sphere._placed(frame_of(boundary, frames).inverse(),
                                                                np.asarray(pole))[0])
    return tuple(sorted(out.items()))
