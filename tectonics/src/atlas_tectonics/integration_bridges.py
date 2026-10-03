"""I03.3: spatial bridges between the shared spherical network and a regional process domain. WORKING NON-CANON.

A bridge moves state between the shared spherical network (integration_sphere) and a regional process domain, in
both directions, without becoming a second owner of anything.

**Sphere to region.** extract() reads a declared regional footprint: a set of whole faces of the network, with a
centre and azimuth, a depth support and the regional model's representation. It issues a read-only RegionalExtract
and never changes the state. Material and heat travel as accounts: each face's stored pieces exactly, with its
spherical measured area (the support every account is measured on) and, beside it, its area in the local frame.
Columns travel whole: the depth support is the regional model's declared extent, and no law divides a column by
depth. Velocities are full 3-vectors in the sphere's axes and in the local east/north/up frame, with no component
dropped: each plate's mean angular velocity over the interval, from which the rigid velocity at any point follows,
and that velocity at every footprint vertex and at each face's reference point. Forces and work have no producer in
I03, so they travel as unknown, never as zero.

**Region to sphere.** returned() puts a regional result back, in memory. To commit it, carry it (carried()) in the
Motion of its interval: the extract must declare that motion and duration, and the step binds both before applying
it at the interval's end. The motion identity excludes its regional returns to avoid a circular binding. Each face
must keep its exact support in its plate's reference frame and its pieces over the interval. The I02 ledger commits
the return with the interval or not at all. It replaces the footprint faces' pieces, the declared
coarse contribution, on the same faces; every other piece keeps its bytes. Each account must be conserved exactly
over the footprint, against the totals read again from the state. Two regions owning one face, one region returned
twice, an extract that was not read from this state as recorded, and a result of another representation are refused.

**Projection (R3-5, approved by the coordinator on 3 October 2026).** The regional frame is
coordinates.LocalCartesianFrame at the footprint's centre: an exact rigid map of 3-D positions. What a lower-dimensional
model omits is reported. A 'map' model omits the vertical: its relative length and area error is 1 - cos(rho_max) and
the surface lies up to R(1 - cos(rho_max)) below its plane. A 'section' model omits the across-section direction and
is admitted only where every velocity's across-section component is within regional_forcing's 64 eps round-off of its
speed. Every footprint vertex must lie within the conditioned-chart limit (integration_sphere.CHART_MIN_COSINE) of the
centre. A 'map' model declares the distortion it accepts; there is no default. That distortion is the orthographic
foreshortening, 1 - cos(rho_max). The plan areas handed over are straight-chord polygons, whose departure from the
spherical areas depends on each face's shape: it is reported (max_area_distortion), not bounded by the declaration.
So is the share of a handed-over speed along the direction a representation omits (omitted_velocity_share).

**Mean angular velocity.** A stage rotation is a finite rotation; its mean angular velocity over the interval is its
principal rotation vector (angle at most pi) over the duration. A turn of more than pi in one interval cannot be told
from the shorter turn the other way: such an interval must be divided.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import json
import math
from types import MappingProxyType

import numpy as np

from . import integration_sphere as _sphere
from . import integration_state as _state
from . import integration_transfer as _transfer
from ._validation import TectonicsError, scalar
from .coordinates import LocalCartesianFrame

SCHEMA = 'atlas.i03-regional-bridge.v1'
REPRESENTATIONS = ('3d', 'map', 'section')
PROJECTION_INVALID = 'projection invalid'
OMITTED_DIMENSION = 'omitted dimension'
INCOMPATIBLE_SUPPORT = 'incompatible support'
UNRESOLVED_OVERLAP = _transfer.UNRESOLVED_OVERLAP
STALE_GEOMETRY = _transfer.STALE_GEOMETRY
SECTION_ROUNDOFF = 64*float(np.finfo(float).eps)     # regional_forcing._ROUNDOFF: arithmetic uncertainty only
VERTICAL = 'whole columns: the depth support is the regional model\'s declared extent; no law divides a column by depth'
FACE_POINT = 'the normalised mean of the face\'s vertex directions (not its area centroid)'


class BridgeRefused(_transfer.TransferRefused):
    """A bridge refusal; ``code`` names the port's refusal (projection, omitted dimension, overlap, support, stale), or
    is None for a malformed argument."""


def _token(value, label):
    if type(value) is not str or not value or len(value) > 256 or not value.isascii():
        raise BridgeRefused('%s is a non-empty ASCII string of at most 256 characters' % label)
    return value


def _scalar(value, label):
    try:
        return scalar(value, label)+0.
    except TectonicsError as exc:
        raise BridgeRefused(str(exc)) from exc


@dataclass(frozen=True)
class Footprint:
    """A declared regional footprint: whole faces, a frame centre and azimuth, a depth support and a representation.

    ``face_ids`` are faces of the network, sorted on construction. ``centre_lon_rad``/``centre_lat_rad`` place the
    local frame and ``azimuth_rad`` turns its x axis from east towards north. ``depth_top_m`` < ``depth_bottom_m``
    bound the depth the regional model represents (positive down); whole columns are carried. ``representation`` is
    '3d', 'map' (x, y) or 'section' (along the azimuth, and up); a 'map' model declares ``max_relative_distortion``.
    """
    region_id: str
    face_ids: tuple
    centre_lon_rad: float
    centre_lat_rad: float
    azimuth_rad: float
    depth_top_m: float
    depth_bottom_m: float
    representation: str
    max_relative_distortion: float | None = None

    def __post_init__(self):
        _token(self.region_id, 'a region identity')
        if type(self.face_ids) not in (tuple, list) or not self.face_ids:
            raise BridgeRefused('a footprint names at least one face')
        names = tuple(sorted(_token(name, 'a face identity') for name in self.face_ids))
        if len(set(names)) != len(names):
            raise BridgeRefused('a footprint names each face once')
        object.__setattr__(self, 'face_ids', names)
        for name in ('centre_lon_rad', 'centre_lat_rad', 'azimuth_rad', 'depth_top_m', 'depth_bottom_m'):
            object.__setattr__(self, name, _scalar(getattr(self, name), name))
        if not abs(self.centre_lat_rad) <= math.pi/2:
            raise BridgeRefused('the footprint centre latitude lies in [-pi/2, pi/2]')
        if not self.depth_top_m < self.depth_bottom_m:
            raise BridgeRefused('a depth support has its top above its bottom (positive down)')
        if type(self.representation) is not str or self.representation not in REPRESENTATIONS:
            raise BridgeRefused('a representation is one of %s' % ', '.join(REPRESENTATIONS), OMITTED_DIMENSION)
        if self.representation == 'map':
            if self.max_relative_distortion is None:
                raise BridgeRefused("a 'map' model declares the relative distortion it accepts; there is no default",
                                    PROJECTION_INVALID)
            value = _scalar(self.max_relative_distortion, 'max_relative_distortion')
            if not 0 <= value < 1:
                raise BridgeRefused('a declared distortion lies in [0, 1)', PROJECTION_INVALID)
            object.__setattr__(self, 'max_relative_distortion', value)
        elif self.max_relative_distortion is not None:
            raise BridgeRefused("only a 'map' model declares a distortion: '3d' omits nothing and 'section' is held "
                                "to round-off", PROJECTION_INVALID)

    def record(self):
        return dict(region_id=self.region_id, face_ids=list(self.face_ids), centre_lon_rad=self.centre_lon_rad,
                    centre_lat_rad=self.centre_lat_rad, azimuth_rad=self.azimuth_rad, depth_top_m=self.depth_top_m,
                    depth_bottom_m=self.depth_bottom_m, representation=self.representation,
                    max_relative_distortion=self.max_relative_distortion)


_FIELDS = ('extract_id', 'parent_state_id', 'network_id', 'material_id', 'footprint', 'columns', 'frame',
           'projection', 'pieces', 'area_m2', 'projected_area_m2', 'face_point', 'rings_local_m', 'ring_vertex_ids',
           'face_point_velocity_m_s', 'face_point_velocity_local_m_s', 'vertex_velocity_m_s',
           'vertex_velocity_local_m_s', 'angular_velocity_rad_s', 'angular_velocity_local_rad_s',
           'omitted_velocity_share', 'motion_id', 'duration_s', 'totals', 'unknown')


class RegionalExtract:
    """What a regional process receives; issued by extract() only, and read-only throughout.

    ``pieces`` maps each footprint face to its pieces: (cohort ID, stored row of the material's ``columns``). ``area_m2``
    is each face's spherical measured area, the support of every account; ``projected_area_m2`` its plan area in the
    local frame's x-y plane, the outer ring's straight-chord polygon less its holes' (None for a 'section', which has no
    plan view). ``rings_local_m`` holds each face's rings (outer, then holes) as positions (x, y, z) in metres in the
    local frame, z the height above its tangent plane, R(p.up) - R; ``ring_vertex_ids`` the matching vertex identities.
    ``face_point`` is each face's reference point (FACE_POINT), a unit vector in the sphere's axes. With a motion,
    ``angular_velocity_rad_s`` holds each footprint plate's mean angular velocity, ``face_point_velocity_m_s`` and
    ``vertex_velocity_m_s`` (keyed by (vertex, plate), holes' vertices included) the rigid velocity there, all full
    3-vectors in the sphere's axes, and the ``*_local_*`` fields the same in the local frame (x, y, up);
    ``omitted_velocity_share`` is the largest share of a handed-over speed along the direction the representation
    omits (up for a 'map', across for a 'section', 0 for '3d'). Without a motion these are None (unknown, not zero).
    ``forces_n`` and ``work_j`` are unknown: I03 has no producer for them (I07 owns them).
    """
    __slots__ = _FIELDS

    def __init__(self, *args, **kwargs):
        raise TypeError('a RegionalExtract is issued by extract() only')

    def __setattr__(self, name, value):
        raise AttributeError('a RegionalExtract is read-only')

    def __delattr__(self, name):
        raise AttributeError('a RegionalExtract is read-only')

    def record(self):
        return dict(schema=SCHEMA, extract_id=self.extract_id, parent_state_id=self.parent_state_id,
                    network_id=self.network_id, material_id=self.material_id, footprint=self.footprint.record(),
                    columns=list(self.columns), projection=_plain(self.projection), motion_id=self.motion_id,
                    duration_s=self.duration_s, vertical=VERTICAL, face_point=FACE_POINT,
                    omitted_velocity_share=self.omitted_velocity_share, unknown=list(self.unknown))


@dataclass(frozen=True)
class RegionalResult:
    """A regional process's result for one extract: the footprint faces' pieces, as the region leaves them.

    ``pieces`` maps every footprint face to its pieces, (cohort ID, row of the extract's ``columns``); cohorts must
    exist in the parent material. ``representation`` must be the extract's.
    """
    extract_id: str
    representation: str
    pieces: dict


def _frozen(value):
    """A read-only copy: mappings become mapping proxies and sequences tuples, all the way down."""
    if isinstance(value, (dict, MappingProxyType)):
        return MappingProxyType({key: _frozen(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_frozen(item) for item in value)
    return value


def _plain(value):
    """JSON-ready data from a read-only copy."""
    if isinstance(value, (dict, MappingProxyType)):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _identity(parent_state_id, footprint, projection, motion_id, duration_s):
    record = dict(parent_state_id=parent_state_id, footprint=footprint.record(), projection=_plain(projection),
                  motion_id=motion_id, duration_s=duration_s)
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def _forcing_id(motion):
    """Identity of the interval proposal before its results: only regional returns are excluded.

    Keeping the rotations, step interval, supplies, sinks, mesh and events binds the result to what its solver was
    given. Excluding returns avoids making an extract's identity depend on the result that answers it.
    """
    return motion.motion_id if not motion.regional_returns else replace(motion, regional_returns=()).motion_id


def _local(frame, points):
    """Directions turned into the local frame's (x, y, up) axes; radius one."""
    basis = np.frombuffer(frame._basis).reshape(3, 3)
    return np.asarray(points, dtype=np.float64) @ basis


def _planar_area(xy):
    x, y = xy[:, 0], xy[:, 1]
    return 0.5*abs(math.fsum(x*np.roll(y, -1))-math.fsum(np.roll(x, -1)*y))


def _charted(network, footprint):
    """(frame, projection, rings, ring vertex identities, plan areas) of ``footprint`` on ``network``.

    ``rings`` maps each face to its rings (outer, then holes) as unit directions in the sphere's axes, and the plan
    area is the outer ring's in the local x-y plane less its holes'. Refused as extract() documents.
    """
    index = {name: i for i, name in enumerate(network.face_ids)}
    missing = [name for name in footprint.face_ids if name not in index]
    if missing:
        raise BridgeRefused('the footprint names faces this network does not have: %s' % ', '.join(missing[:5]),
                            INCOMPATIBLE_SUPPORT)
    frame = LocalCartesianFrame(network.sphere, footprint.region_id, footprint.centre_lon_rad,
                                footprint.centre_lat_rad, 0., footprint.azimuth_rad)
    centre = np.frombuffer(frame._basis).reshape(3, 3)[:, 2]
    lookup = {name: i for i, name in enumerate(network.vertex_ids)}
    ids = {name: (network.faces[index[name]].vertex_ids,)+tuple(network.faces[index[name]].holes)
           for name in footprint.face_ids}
    rings = {name: tuple(np.asarray(network.vertex_direction[[lookup[v] for v in ring]], dtype=np.float64)
                         for ring in ids[name]) for name in footprint.face_ids}
    cosine = min(float(np.min(ring @ centre)) for face in rings.values() for ring in face)
    if not cosine >= _sphere.CHART_MIN_COSINE:
        raise BridgeRefused('a footprint vertex lies %.6f rad from the centre, beyond the conditioned-chart limit'
                            % math.acos(max(-1., min(1., cosine))), PROJECTION_INVALID)
    rho = math.acos(max(-1., min(1., cosine)))
    radius = network.sphere.radius_m
    distortion, drop = 1-cosine, radius*(1-cosine)
    omitted = {'3d': (), 'map': ('up',), 'section': ('across-section',)}[footprint.representation]
    if footprint.representation == 'map' and distortion > footprint.max_relative_distortion:
        raise BridgeRefused('the footprint reaches %.6f rad from its centre: a map omitting the vertical distorts '
                            'lengths and areas by %.3e, more than the declared %.3e' % (
                                rho, distortion, footprint.max_relative_distortion), PROJECTION_INVALID)
    plan = {name: _planar_area(_local(frame, rings[name][0])*radius)
            - math.fsum(_planar_area(_local(frame, hole)*radius) for hole in rings[name][1:])
            for name in footprint.face_ids}
    vertical = omitted == ('up',)
    # A map receives each face's plan area as the straight-chord polygon of its projected corners: its departure from
    # the spherical area depends on the face's shape, so it is reported, not bounded by the foreshortening alone.
    area_error = max(abs(1-plan[name]/float(network.face_area_m2[index[name]])) for name in footprint.face_ids)
    projection = _frozen(dict(frame=frame.descriptor(), representation=footprint.representation, omitted=omitted,
                              rho_max_rad=rho, relative_distortion=distortion if vertical else 0.,
                              surface_drop_m=drop if vertical else 0.,
                              drop_over_depth=drop/(footprint.depth_bottom_m-footprint.depth_top_m) if vertical
                              else 0., max_area_distortion=area_error if vertical else 0.))
    return frame, projection, rings, ids, plan


def _footprint_pieces(network, material, face_ids):
    index = {name: i for i, name in enumerate(network.face_ids)}
    face_rows = np.asarray(material.piece_face)
    return {name: tuple((material.cohorts[int(material.piece_cohort[row])].cohort_id,
                         tuple(float(x) for x in material.stock[row]))
                        for row in np.flatnonzero(face_rows == index[name])) for name in face_ids}


def extract(state, footprint, motion=None, duration_s=None):
    """Read ``footprint`` from ``state`` for a regional process (sphere to region); the state is not changed.

    ``motion`` (the integration_transfer.Motion of the interval the region will run, declared from this state's step)
    and ``duration_s`` give the plates' mean angular velocities; without them velocities are unknown. Refused with
    PROJECTION_INVALID when a footprint vertex lies beyond the conditioned-chart limit of the centre or a 'map' model's
    distortion exceeds its declared tolerance, with OMITTED_DIMENSION when a 'section' model would drop motion across
    the section, with STALE_GEOMETRY when the motion is declared for another step, and with INCOMPATIBLE_SUPPORT when
    the footprint is not a set of faces of this network or is not a Footprint. Non-finite velocities are refused,
    whatever the process's floating-point warning policy.
    """
    state = _sphere.verified(state)
    if type(footprint) is not Footprint:
        raise BridgeRefused('a Footprint record is required', INCOMPATIBLE_SUPPORT)
    network, material = state.network, state.material
    frame, projection, rings, ids, plan = _charted(network, footprint)
    radius = network.sphere.radius_m
    index = {name: i for i, name in enumerate(network.face_ids)}
    plate_of = {name: network.faces[index[name]].plate_id for name in footprint.face_ids}
    rates = None
    if motion is not None or duration_s is not None:
        if type(motion) is not _transfer.Motion or duration_s is None:
            raise BridgeRefused('velocities need the interval Motion and its duration together')
        _supported_velocity_history(motion)
        duration_s = _scalar(duration_s, 'duration_s')
        if not duration_s > 0:
            raise BridgeRefused('an interval duration is positive')
        if motion.start_step != network.step:
            raise BridgeRefused('a motion declared from step %d cannot drive the state at step %d'
                                % (motion.start_step, network.step), STALE_GEOMETRY)
        stage = dict(motion.rotations)
        if set(stage) != set(network.plate_ids):
            raise BridgeRefused('the motion gives every plate of the network its stage rotation')
        with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
            rates = {plate: np.asarray(_transfer._vector(stage[plate]), dtype=np.float64)/duration_s
                     for plate in sorted(set(plate_of.values()))}
    pieces = _footprint_pieces(network, material, footprint.face_ids)
    area, point, positions = {}, {}, {}
    known = rates is not None
    face_v, face_v_local, vertex_v, vertex_v_local = ({}, {}, {}, {}) if known else (None,)*4
    for name in footprint.face_ids:
        i = index[name]
        area[name] = float(network.face_area_m2[i])
        positions[name] = tuple(tuple((float(x), float(y), float(z)-radius) for x, y, z in _local(frame, ring)*radius)
                                for ring in rings[name])
        mean = _sphere._mean_direction(rings[name][0])
        point[name] = tuple(float(x) for x in mean)
        if known:
            rate = rates[plate_of[name]]
            with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
                v = np.cross(rate, mean*radius)
                face_v[name] = tuple(float(x) for x in v)
                face_v_local[name] = tuple(float(x) for x in _local(frame, v[None, :])[0])
                for ring_ids, ring in zip(ids[name], rings[name]):
                    for vertex_id, direction in zip(ring_ids, ring):
                        w = np.cross(rate, direction*radius)
                        vertex_v[vertex_id, plate_of[name]] = tuple(float(x) for x in w)
                        vertex_v_local[vertex_id, plate_of[name]] = tuple(float(x)
                                                                          for x in _local(frame, w[None, :])[0])
    if known:
        values = [*rates.values(), *face_v.values(), *vertex_v.values(), *face_v_local.values(),
                  *vertex_v_local.values()]
        if not all(np.all(np.isfinite(v)) for v in values):
            raise BridgeRefused('the velocities are not finite: the interval is too short for its rotation')
    if footprint.representation == 'section':
        if not known:
            raise BridgeRefused('a section omits the across-section direction, which is admitted only where the '
                                'motion is known to have no component across it; give the interval motion',
                                OMITTED_DIMENSION)
        for values in (*face_v_local.values(), *vertex_v_local.values()):
            speed = math.hypot(*values)
            if not abs(values[1]) <= SECTION_ROUNDOFF*speed:
                raise BridgeRefused('a section along the azimuth would drop a velocity component of %.3e m/s across '
                                    'it (speed %.3e m/s); only an invariant section may omit that direction'
                                    % (abs(values[1]), speed), OMITTED_DIMENSION)
    share = None
    if known:
        axis = {'3d': None, 'map': 2, 'section': 1}[footprint.representation]
        speeds = [(values, math.hypot(*values)) for values in (*face_v_local.values(), *vertex_v_local.values())]
        share = 0. if axis is None else max((abs(values[axis])/speed for values, speed in speeds if speed > 0),
                                            default=0.)
    angular = angular_local = None
    if known:
        angular = {plate: tuple(float(x) for x in rate) for plate, rate in rates.items()}
        angular_local = {plate: tuple(float(x) for x in _local(frame, rate[None, :])[0])
                         for plate, rate in rates.items()}
    motion_id = None if motion is None else _forcing_id(motion)
    totals = tuple(_exact_column(pieces, column) for column in range(len(material.columns)))
    return _state._issue(
        RegionalExtract, extract_id=_identity(state.state_id, footprint, projection, motion_id, duration_s),
        parent_state_id=state.state_id, network_id=network.network_id, material_id=material.material_id,
        footprint=footprint, columns=tuple(material.columns), frame=frame, projection=projection,
        pieces=_frozen(pieces), area_m2=_frozen(area), projected_area_m2=None if footprint.representation == 'section'
        else _frozen(plan), face_point=_frozen(point), rings_local_m=_frozen(positions), ring_vertex_ids=_frozen(ids),
        face_point_velocity_m_s=None if face_v is None else _frozen(face_v),
        face_point_velocity_local_m_s=None if face_v_local is None else _frozen(face_v_local),
        vertex_velocity_m_s=None if vertex_v is None else _frozen(vertex_v),
        vertex_velocity_local_m_s=None if vertex_v_local is None else _frozen(vertex_v_local),
        angular_velocity_rad_s=None if angular is None else _frozen(angular),
        angular_velocity_local_rad_s=None if angular_local is None else _frozen(angular_local),
        omitted_velocity_share=share, motion_id=motion_id, duration_s=duration_s, totals=totals,
        unknown=('forces_n', 'work_j'))


def _supported_velocity_history(motion):
    # The current regional port carries one constant angular rate per plate. The opt-in common-reference
    # history generally has time-varying spatial rates; log(endpoint rotation)/duration is not that history.
    if motion.junction_paths:
        raise BridgeRefused('the regional velocity port does not represent common-reference exponential histories; '
                            'a junction-path interval cannot be replaced by a constant endpoint rotation rate',
                            INCOMPATIBLE_SUPPORT)


def _exact_column(pieces, column):
    return sum((Fraction(values[column]) for rows in pieces.values() for _, values in rows), Fraction(0))


def returned(state, pairs, *, budget=None):
    """Put regional results back (region to sphere) in memory: a successor state of ``state``.

    ``pairs`` is a sequence of (RegionalExtract, RegionalResult). Each result replaces its footprint faces' pieces,
    the declared coarse contribution, on the same faces; every other piece keeps its bytes, and the network is
    unchanged. Each account is conserved exactly over each footprint, against the totals read again from ``state``, so
    the exact accounts do not change. Refused with UNRESOLVED_OVERLAP when two footprints share a face (two regions
    would own one material) or one region is returned twice, or when the returned pieces do not occupy their faces;
    STALE_GEOMETRY when an extract was not read from ``state`` as recorded; OMITTED_DIMENSION when a result's
    representation is not its extract's; and INCOMPATIBLE_SUPPORT when a result names other faces or unknown cohorts,
    gives rows of another shape, negative mass or volume, or material without area, or changes any cohort's exact
    amounts over its footprint. A result that leaves every piece as extracted returns the parent state itself.

    The successor is held in memory only. To commit a return to an I02 history, carry it (``carried``) in the Motion
    of the interval it belongs to; the step applies it at the interval's end.
    """
    state = _sphere.verified(state)
    if type(pairs) not in (tuple, list) or not pairs:
        raise BridgeRefused('returned() takes a non-empty sequence of (RegionalExtract, RegionalResult) pairs')
    network, material = state.network, state.material
    items = []
    for pair in pairs:
        if type(pair) not in (tuple, list) or len(pair) != 2 or type(pair[0]) is not RegionalExtract or type(
                pair[1]) is not RegionalResult:
            raise BridgeRefused('each pair is (RegionalExtract, RegionalResult)')
        extracted, result = pair
        footprint = extracted.footprint
        if (type(footprint) is not Footprint or extracted.parent_state_id != state.state_id
                or extracted.material_id != material.material_id or extracted.network_id != network.network_id
                or _identity(extracted.parent_state_id, footprint, extracted.projection, extracted.motion_id,
                             extracted.duration_s) != extracted.extract_id):
            raise BridgeRefused('the extract %r was not read from this state as recorded; a region returns to the '
                                'state it was given' % getattr(footprint, 'region_id', None), STALE_GEOMETRY)
        if _plain(_charted(network, footprint)[1]) != _plain(extracted.projection):
            raise BridgeRefused('the extract does not reproduce its projection on this state', STALE_GEOMETRY)
        if result.extract_id != extracted.extract_id:
            raise BridgeRefused('a result answers another extract', INCOMPATIBLE_SUPPORT)
        if result.representation != footprint.representation:
            raise BridgeRefused('a %r result cannot replace a %r contribution: their omitted dimensions differ'
                                % (result.representation, footprint.representation), OMITTED_DIMENSION)
        items.append((footprint, result.pieces))
    held = _held(network, material, items)
    after = _replaced(network, material, items, held, budget)
    if after.material_id == material.material_id:
        return state
    return _sphere._sphere(network, after, state.state_id, state.root_state_id, _state.COMPUTED)


def _held(network, material, items):
    """What each footprint holds on ``network``, after checking that footprints and regions do not overlap."""
    owner, regions, held = {}, set(), []
    for footprint, pieces in items:
        if footprint.region_id in regions:
            raise BridgeRefused('region %r is returned twice: its results would overlap' % footprint.region_id,
                                UNRESOLVED_OVERLAP)
        regions.add(footprint.region_id)
        for name in footprint.face_ids:
            if name in owner:
                raise BridgeRefused('regions %r and %r both own face %r: two regions cannot own one material'
                                    % (owner[name], footprint.region_id, name), UNRESOLVED_OVERLAP)
            owner[name] = footprint.region_id
        if (type(pieces) not in (dict, MappingProxyType) or not all(type(name) is str for name in pieces)
                or sorted(pieces) != list(footprint.face_ids)):
            raise BridgeRefused('a result gives pieces for exactly its footprint faces', INCOMPATIBLE_SUPPORT)
        missing = [name for name in footprint.face_ids if name not in network.face_ids]
        if missing:
            raise BridgeRefused('the footprint names faces the network does not have: %s' % ', '.join(missing[:5]),
                                STALE_GEOMETRY)
        held.append(_footprint_pieces(network, material, footprint.face_ids))
    return held


def _replaced(network, material, items, held, budget):
    """``material`` with each footprint's pieces replaced by its result's, every account and cohort conserved."""
    cohort_index = {cohort.cohort_id: i for i, cohort in enumerate(material.cohorts)}
    face_index = {name: i for i, name in enumerate(network.face_ids)}
    columns = tuple(material.columns)
    replaced = {}
    for (footprint, pieces), kept in zip(items, held):
        fault = _shaped(pieces, columns, cohort_index)
        if fault:
            raise BridgeRefused('region %r returns %s' % (footprint.region_id, fault), INCOMPATIBLE_SUPPORT)
        for column in range(len(columns)):
            if _exact_column(pieces, column) != _exact_column(kept, column):
                raise BridgeRefused('region %r does not return its %s exactly: a regional exchange with an exterior '
                                    'goes through a named exterior, not a return' % (
                                        footprint.region_id, columns[column]), INCOMPATIBLE_SUPPORT)
        _same_cohorts(footprint.region_id, pieces, kept, columns)
        for name, rows in pieces.items():
            replaced[face_index[name]] = rows
    keep = [row for row in range(len(material.piece_face)) if int(material.piece_face[row]) not in replaced]
    entries = [(int(material.piece_face[row]), int(material.piece_cohort[row]), np.asarray(material.stock[row]))
               for row in keep]
    for face, rows in replaced.items():
        for cohort_id, values in rows:
            if any(v != 0 for v in values):
                entries.append((face, cohort_index[cohort_id], np.asarray(values, dtype=np.float64)))
    entries.sort(key=lambda entry: (entry[0], entry[1]))
    face = np.array([entry[0] for entry in entries], dtype=np.int64)
    cohort = np.array([entry[1] for entry in entries], dtype=np.int64)
    stock = np.array([entry[2] for entry in entries], dtype=np.float64).reshape(-1, len(columns))
    try:
        return _sphere._material(network, material.phases, material.enthalpy_basis, material.cohorts,
                                 material.exteriors, material.stock_link, face, cohort, stock, material._initial,
                                 material._supplied, material._rounding, material._allowance, budget,
                                 occupancy_allowance=material._occupancy_allowance)
    except TectonicsError as exc:
        raise BridgeRefused('the returned pieces do not occupy their faces: %s' % exc, UNRESOLVED_OVERLAP) from exc


@dataclass(frozen=True)
class RegionalReturn:
    """A regional result carried in the Motion of its interval (B2, round 1), applied at the interval's end.

    It keeps what binds it to the extract it answers (``footprint``, ``extract_id``, ``motion_id``, ``duration_s``)
    and the result's ``pieces``. The motion identity excludes regional returns, preventing a circular binding; motion
    and duration are required for a committed return. Its record is stored with the Motion, so restoring the step
    applies it again. Built by ``carried(extract, result)``, or rebuilt from its record.
    """
    footprint: Footprint
    extract_id: str
    motion_id: str
    duration_s: float
    representation: str
    pieces: tuple

    def __post_init__(self):
        if type(self.footprint) is not Footprint:
            raise BridgeRefused('a carried return names its Footprint', INCOMPATIBLE_SUPPORT)
        if type(self.extract_id) is not str or len(self.extract_id) != 64:
            raise BridgeRefused('a carried return names the identity of the extract it answers', INCOMPATIBLE_SUPPORT)
        if type(self.motion_id) is not str or len(self.motion_id) != 64:
            raise BridgeRefused('a carried return requires an extract with the interval motion and duration',
                                STALE_GEOMETRY)
        duration = _scalar(self.duration_s, 'duration_s')
        if duration <= 0:
            raise BridgeRefused('a carried return requires a positive interval duration', STALE_GEOMETRY)
        object.__setattr__(self, 'duration_s', duration)
        if type(self.pieces) not in (tuple, list, dict, MappingProxyType):
            raise BridgeRefused('a carried return gives its pieces', INCOMPATIBLE_SUPPORT)
        rows = self.pieces.items() if isinstance(self.pieces, (dict, MappingProxyType)) else self.pieces
        try:
            pieces = tuple(sorted((name, tuple((cohort, tuple(float(v) for v in values)) for cohort, values in face))
                                  for name, face in rows))
        except (TypeError, ValueError) as exc:
            raise BridgeRefused('the pieces of a carried return are (face, ((cohort, row), ...))',
                                INCOMPATIBLE_SUPPORT) from exc
        object.__setattr__(self, 'pieces', pieces)

    def record(self):
        return dict(schema=SCHEMA, footprint=self.footprint.record(), extract_id=self.extract_id,
                    motion_id=self.motion_id, duration_s=self.duration_s, representation=self.representation,
                    pieces=[[name, [[cohort, list(values)] for cohort, values in face]] for name, face in self.pieces])

    @staticmethod
    def from_record(row):
        try:
            if row['schema'] != SCHEMA:
                raise BridgeRefused('the stored return is not of this schema', INCOMPATIBLE_SUPPORT)
            footprint = Footprint(**row['footprint'])
            carried = RegionalReturn(footprint, row['extract_id'], row['motion_id'], row['duration_s'],
                                     row['representation'], tuple((name, tuple((cohort, tuple(values))
                                                                                for cohort, values in face))
                                                                  for name, face in row['pieces']))
        except (KeyError, TypeError, ValueError) as exc:
            raise BridgeRefused('the stored return record is incomplete', INCOMPATIBLE_SUPPORT) from exc
        if json.dumps(carried.record(), sort_keys=True) != json.dumps(row, sort_keys=True):
            raise BridgeRefused('the stored return does not reproduce its record', INCOMPATIBLE_SUPPORT)
        return carried


def carried(extract, result):
    """Carry a result for an extract issued with its interval's explicit motion and duration.

    An extract without these remains available for read-only inspection and in-memory returned(), but cannot bind a
    committed return to its forcing. The Motion identity used here excludes regional returns themselves.
    """
    if type(extract) is not RegionalExtract or type(result) is not RegionalResult:
        raise BridgeRefused('carried() takes a RegionalExtract and its RegionalResult')
    if result.extract_id != extract.extract_id:
        raise BridgeRefused('a result answers another extract', INCOMPATIBLE_SUPPORT)
    if type(result.pieces) not in (dict, MappingProxyType):
        raise BridgeRefused('a result gives pieces for exactly its footprint faces', INCOMPATIBLE_SUPPORT)
    return RegionalReturn(extract.footprint, extract.extract_id, extract.motion_id, extract.duration_s,
                          result.representation, dict(result.pieces))


def _returned_at_end(parent, network, material, returns, motion, budget=None):
    """``material`` at the end of an interval with its carried ``returns`` applied (B2, round 1).

    ``parent`` is the interval's parent state; ``network`` and ``material`` its endpoint, after the motion and any mesh
    change. Each return must answer an extract read from ``parent``, using this interval's proposal (excluding its
    returns) and duration. Every footprint face must keep its plate-relative support and its pieces exactly: equal
    inventories alone do not prove that the interval carried a face whole. Ring cycles and hole ordering do not
    change support. Refused with STALE_GEOMETRY when any binding fails.
    """
    items, held = [], []
    if returns:
        _supported_velocity_history(motion)
    forcing_id = _forcing_id(motion)
    duration = network.time_s-parent.network.time_s
    for item in returns:
        footprint = item.footprint
        if item.motion_id != forcing_id or item.duration_s != duration:
            raise BridgeRefused('region %r answers a different interval motion or duration' % footprint.region_id,
                                STALE_GEOMETRY)
        # Records are reconstructible data, not authentication of a prior extract() call. Reapply every
        # representation's admission, including finite velocities and any omitted component, to the real forcing.
        checked = extract(parent, footprint, motion, duration)
        if checked.extract_id != item.extract_id:
            raise BridgeRefused('region %r was not read from the parent of this interval as recorded'
                                % footprint.region_id, STALE_GEOMETRY)
        if item.representation != footprint.representation:
            raise BridgeRefused('a %r result cannot replace a %r contribution: their omitted dimensions differ'
                                % (item.representation, footprint.representation), OMITTED_DIMENSION)
        items.append((footprint, dict(item.pieces)))
    at_end = _held(network, material, items)
    before_index = {name: i for i, name in enumerate(parent.network.face_ids)}
    after_index = {name: i for i, name in enumerate(network.face_ids)}
    for (footprint, _), now in zip(items, at_end):
        for name in footprint.face_ids:
            i, j = before_index[name], after_index[name]
            if (parent.network.faces[i].plate_id != network.faces[j].plate_id
                    or _support(parent.network.face_coordinates(i)) != _support(network.face_coordinates(j))):
                raise BridgeRefused('region %r: face %r changed its support over the interval; a return applies only '
                                    'to faces the interval carried whole' % (footprint.region_id, name), STALE_GEOMETRY)
        then = _footprint_pieces(parent.network, parent.material, footprint.face_ids)
        if now != then:
            changed = [name for name in footprint.face_ids if now[name] != then[name]]
            raise BridgeRefused('region %r: face %r changed over the interval, so its return no longer applies; a '
                                'return applies only to faces the interval carried whole' % (
                                    footprint.region_id, changed[0]), STALE_GEOMETRY)
        held.append(now)
    return _replaced(network, material, items, held, budget)


def _support(rings):
    """Exact oriented rings in plate coordinates, independent of ring start, vertex names and hole order."""
    def cycle(ring):
        points = tuple(tuple(float(value) for value in point) for point in ring)
        start = min(range(len(points)), key=points.__getitem__)
        return points[start:]+points[:start]
    return cycle(rings[0]), tuple(sorted(cycle(hole) for hole in rings[1:]))


def _cohort_totals(pieces, width):
    out = {}
    for rows in pieces.values():
        for cohort, values in rows:
            totals = out.setdefault(cohort, [Fraction(0)]*width)
            for k, value in enumerate(values):
                totals[k] += Fraction(value)
    return out


def _same_cohorts(region, pieces, held, columns):
    """Refuse a result that changes any cohort's exact amount of any column over its footprint (B1).

    Material may move between the footprint's faces, but no cohort's amounts may change. A regional process that turns
    one cohort into another would need a named, booked transformation with its own origin record, which is not built.
    """
    width = len(columns)
    given, kept = _cohort_totals(pieces, width), _cohort_totals(held, width)
    zero = [Fraction(0)]*width
    for cohort in sorted(set(given) | set(kept)):
        a, b = given.get(cohort, zero), kept.get(cohort, zero)
        for k in range(width):
            if a[k] != b[k]:
                raise BridgeRefused('region %r returns %s of %s for cohort %r, which held %s over the footprint: a '
                                    "regional process changes no cohort's amounts (a cohort change needs a named, "
                                    'booked transformation, which is not built)'
                                    % (region, float(a[k]), columns[k], cohort, float(b[k])), INCOMPATIBLE_SUPPORT)


def _shaped(pieces, columns, cohort_index):
    """None for well-formed result pieces, else what is wrong with them."""
    width = len(columns)
    signed = [k for k, column in enumerate(columns) if column.startswith(('mass_kg:', 'volume_m3:'))]
    area = columns.index('area_m2')
    for rows in pieces.values():
        if type(rows) not in (tuple, list):
            return 'a face whose pieces are not a sequence'
        seen = set()
        for row in rows:
            if (type(row) not in (tuple, list) or len(row) != 2 or type(row[0]) is not str
                    or type(row[1]) not in (tuple, list) or len(row[1]) != width
                    or not all(isinstance(v, float) and math.isfinite(v) for v in row[1])):
                return 'a piece that is not (cohort ID, %d finite floats)' % width
            if row[0] not in cohort_index or row[0] in seen:
                return 'an unknown cohort, or one cohort twice in a face'
            seen.add(row[0])
            values = row[1]
            if not any(v != 0 for v in values):
                continue
            if not values[area] > 0:
                return 'material without area'
            if any(values[k] < 0 for k in signed):
                return 'a negative mass or volume'
    return None
