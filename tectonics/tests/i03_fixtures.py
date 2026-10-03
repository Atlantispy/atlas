"""Shared fixtures of the I03 checks: small closed spherical networks declared through the package API.

Every control value is read from cases/i03_controls_v1.json: the radius, the meshes, the worlds, the declared areal
material values, the rotations and intervals of each control, its tolerances (all existing ones) and its resource
caps. A "sector world" divides the sphere by meridians of one axis into pole-to-pole sectors, each cut into latitude
bands with a triangle at either pole. Sectors are grouped into plates; every meridian between two plates is one
shared boundary record running from the south pole to the north pole, so both poles are junctions. The axis can be
tilted: the same world is then expressed in rotated coordinates, with no vertex on the frame's own pole or seam.
These are bounded controls built from declared values, not generated worlds.
SPDX-License-Identifier: AGPL-3.0-only
"""
import json
import math
from pathlib import Path

import numpy as np

from atlas_tectonics import integration_sphere as S
from atlas_tectonics.coordinates import SphericalFrame
from atlas_tectonics.kinematics import Rotation
from atlas_tectonics.resources import WorkBudget

CASES = Path(__file__).resolve().parents[1]/'cases'
CASE = json.loads((CASES/'i03_controls_v1.json').read_text(encoding='utf-8'))
D3 = json.loads((CASES/'i01_closures_v1.json').read_text(encoding='utf-8'))['control_parameters']['D3']

RADIUS_M = CASE['sphere']['radius_m']
FRAME, EPOCH, START = CASE['sphere']['frame_id'], CASE['sphere']['epoch_id'], CASE['sphere']['start_time_s']
SOURCE = 'tectonics/tests/i03_fixtures.py'
IDENTITY = Rotation((1., 0., 0., 0.))
MYR_S = CASE['units']['myr_s']
SPHERE_M2 = 4*math.pi*RADIUS_M*RADIUS_M


def control(name):
    """The declared parameters of one control."""
    return CASE['controls'][name]


def tolerance(name):
    """An existing tolerance by the name the case gives it."""
    return CASE['tolerances'][name]['value']


def rotation(record):
    """The Rotation of an axis-angle record of the case."""
    return Rotation.from_axis_angle(tuple(record['axis']), record['angle_rad'])


def budget():
    """A fresh work budget at the cap the case declares for network and step controls."""
    return WorkBudget(CASE['resources']['work_budget_bytes'])


TILT = rotation(CASE['tilt'])


def mesh(name):
    """(longitudes, latitudes) of a declared sector mesh."""
    record = CASE['meshes'][name]
    return tuple(record['longitudes_deg']), tuple(record['latitudes_deg'])


def moved_latitudes(name='sector6'):
    """The mesh's latitudes with the identity control's one latitude moved: another, equally valid geometry."""
    change = control('identity')['moved_latitude_deg']
    return tuple(change['to'] if value == change['from'] else value for value in mesh(name)[1])


def lune(degrees):
    """Area between two meridians ``degrees`` apart: A = 2 R^2 delta_longitude (the D3 control's own formula)."""
    return 2*RADIUS_M*RADIUS_M*math.radians(degrees)


def angle(a, b):
    """Angle between directions (rows), stable for small separations."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return 2*np.arctan2(np.linalg.norm(a-b, axis=-1), np.linalg.norm(a+b, axis=-1))


def rotation_angle(first, second):
    """The angle of the rotation that takes ``first`` to ``second`` (q and -q are one rotation)."""
    p, q = np.asarray(first.quaternion), np.asarray(second.quaternion)
    if float(p @ q) < 0:
        q = -q
    return 4*math.atan2(float(np.linalg.norm(p-q)), float(np.linalg.norm(p+q)))


def sphere(frame=FRAME, radius=RADIUS_M):
    return SphericalFrame(radius, frame)


def direction(longitude_deg, latitude_deg):
    lon, lat = math.radians(longitude_deg), math.radians(latitude_deg)
    return (math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat))


def meridian(i):
    return 'm%02d' % i


def vertex(i, j):
    return '%s-p%02d' % (meridian(i), j)


def sector_mesh(longitudes_deg, latitudes_deg, *, tilt=None, zigzag_deg=0.):
    """(vertices, rings): pole-to-pole sectors between consecutive meridians, bands between the latitudes.

    ``zigzag_deg`` shifts every meridian's vertices east and west alternately from one latitude row to the next, so
    that each boundary segment is oblique to a rotation about the axis.
    """
    count, bands = len(longitudes_deg), len(latitudes_deg)
    vertices = {'N': (0., 0., 1.), 'S': (0., 0., -1.)}
    for i, lon in enumerate(longitudes_deg):
        for j, lat in enumerate(latitudes_deg):
            vertices[vertex(i, j)] = direction(lon+zigzag_deg*(-1)**j, lat)
    if tilt is not None:
        vertices = {name: tuple(float(x) for x in tilt.apply(np.asarray(value))) for name, value in vertices.items()}
    rings = {}
    for i in range(count):
        k = (i+1) % count
        rings['s%02d-south' % i] = ('S', vertex(k, 0), vertex(i, 0))
        for j in range(bands-1):
            rings['s%02d-b%02d' % (i, j)] = (vertex(i, j), vertex(k, j), vertex(k, j+1), vertex(i, j+1))
        rings['s%02d-north' % i] = (vertex(i, bands-1), vertex(k, bands-1), 'N')
    return vertices, rings


def sector_of(face_id):
    return int(face_id[1:3])


def chain(i, bands):
    """The meridian's vertex chain from the south pole to the north pole."""
    return ('S', *(vertex(i, j) for j in range(bands)), 'N')


def origin(reference=SOURCE):
    return S.Origin(S.INITIAL, reference)


_STATIC = CASE['worlds']['static']


def sector_world(longitudes_deg=None, latitudes_deg=None, *, plates=tuple(_STATIC['plates']), kinds=None,
                 rotations=None, tilt=None, frame=FRAME, time_s=START, step=0, epoch=EPOCH, limits=None,
                 zigzag_deg=0., **changes):
    """A declared sector network: ``plates[i]`` owns the sector east of meridian i.

    The default is the case's 'static' world. ``kinds`` maps a meridian index to the keyword fields of its boundary
    record (kind and its declared rule); meridians between two plates that are not named are declared as ridges
    with the case's accretion fraction.
    """
    default = mesh(_STATIC['mesh'])
    longitudes_deg = default[0] if longitudes_deg is None else longitudes_deg
    latitudes_deg = default[1] if latitudes_deg is None else latitudes_deg
    count, bands = len(longitudes_deg), len(latitudes_deg)
    vertices, rings = sector_mesh(longitudes_deg, latitudes_deg, tilt=tilt, zigzag_deg=zigzag_deg)
    faces = tuple(S.Face(name, plates[sector_of(name)], ring) for name, ring in rings.items())
    rotations = {} if rotations is None else rotations
    records = tuple(S.Plate(name, rotations.get(name, IDENTITY)) for name in sorted(set(plates)))
    kinds = {} if kinds is None else kinds
    boundaries = []
    for i in range(count):
        west, east = plates[(i-1) % count], plates[i]
        if west == east:
            continue
        fields = dict(kinds.get(i, dict(kind=S.RIDGE, accretion_fraction=_STATIC['accretion_fraction'])))
        boundaries.append(S.Boundary('boundary-%s' % meridian(i), fields.pop('kind'), west, east,
                                     chain(i, bands), origin(), **fields))
    values = dict(sphere=sphere(frame), vertices=vertices, faces=faces, plates=records,
                  boundaries=tuple(boundaries), epoch_id=epoch, time_s=time_s, step=step, limits=limits)
    values.update(changes)
    return S.build_network(**values)


def octahedron(*, plates=None, frame=FRAME, **changes):
    """Eight octants on six axis vertices: every vertex a junction of the four faces around it."""
    vertices = {'+x': (1., 0., 0.), '-x': (-1., 0., 0.), '+y': (0., 1., 0.), '-y': (0., -1., 0.),
                '+z': (0., 0., 1.), '-z': (0., 0., -1.)}
    rings = {'o+++': ('+x', '+y', '+z'), 'o-++': ('+y', '-x', '+z'), 'o--+': ('-x', '-y', '+z'),
             'o+-+': ('-y', '+x', '+z'), 'o++-': ('+y', '+x', '-z'), 'o-+-': ('-x', '+y', '-z'),
             'o---': ('-y', '-x', '-z'), 'o+--': ('+x', '-y', '-z')}
    owners = {name: 'north' if name.endswith('+') else 'south' for name in rings} if plates is None else plates
    faces = tuple(S.Face(name, owners[name], ring) for name, ring in rings.items())
    records = tuple(S.Plate(name, IDENTITY) for name in sorted(set(owners.values())))
    boundaries = ()
    if plates is None:
        # Going east along the equator the northern plate is on the left.
        boundaries = (S.Boundary('equator', S.TRANSFORM, 'north', 'south', ('+x', '+y', '-x', '-y'), origin(),
                                 closed=True),)
    values = dict(sphere=sphere(frame), vertices=vertices, faces=faces, plates=records, boundaries=boundaries,
                  epoch_id=EPOCH, time_s=START)
    values.update(changes)
    return S.build_network(**values)


_MATERIAL = CASE['materials']['static']
PHASES = tuple(_MATERIAL['phases'])
BASIS = _MATERIAL['enthalpy_basis']
MASS_PER_AREA = dict(_MATERIAL['mass_per_area_kg_m2'])          # kg/m2: declared reference columns, not Earth values
THICKNESS = dict(_MATERIAL['thickness_m'])                      # m
ENTHALPY_PER_AREA = _MATERIAL['enthalpy_per_area_j_m2']         # J/m2, signed in the declared basis


def cohort(name, *, material='declared-crust', origin_id=SOURCE+'#inherited', start=None, end=None, history=None):
    return S.Cohort(name, material, origin_id, start, end, history)


def material(network, *, cohort_of=None, cohorts=None, phases=PHASES, basis=BASIS, exteriors=(),
             mass_per_area_kg_m2=None, thickness_m=None, **changes):
    """One declared cohort per face, each stock its declared areal value times the face's measured area."""
    cohort_of = (lambda face_id: 'inherited-'+network.face_plate(face_id)) if cohort_of is None else cohort_of
    names = sorted({cohort_of(face_id) for face_id in network.face_ids})
    cohorts = tuple(cohort(name) for name in names) if cohorts is None else cohorts
    mass = {p: MASS_PER_AREA[p] for p in phases} if mass_per_area_kg_m2 is None else mass_per_area_kg_m2
    depth = {p: THICKNESS[p] for p in phases} if thickness_m is None else thickness_m
    values = dict(phases=phases, cohorts=cohorts, face_cohort={f: cohort_of(f) for f in network.face_ids},
                  mass_per_area_kg_m2=mass, thickness_m=depth,
                  enthalpy_per_area_j_m2=None if basis is None else ENTHALPY_PER_AREA, enthalpy_basis=basis,
                  exteriors=exteriors)
    values.update(changes)
    return S.areal_material(network, **values)


def state(network=None, **changes):
    network = sector_world() if network is None else network
    return S.initial_sphere(network, material(network, **changes))


# ----------------------------------------------------------------------------- moving worlds (I03.2)

from atlas_tectonics import integration_transfer as T

_MOVING = CASE['materials']['moving']
EXTERIORS = tuple(tuple(pair) for pair in _MOVING['exteriors'])
# The I01 D3 lune control's declared values (cases/i01_closures_v1.json control_parameters and its tool).
D3_THICKNESS = D3['thickness_m']
D3_MASS_PER_AREA = D3['density_kg_m3']*D3_THICKNESS             # kg/m2
D3_ENTHALPY_PER_AREA = D3_MASS_PER_AREA*_MOVING['birth_heat_j_per_kg']    # J/m2, declared cp*(Tbirth - Treference)
INHERITED_ENTHALPY_PER_AREA = D3_ENTHALPY_PER_AREA*_MOVING['inherited_enthalpy_fraction']


def axis(tilt=None):
    """The world axis of a sector world: the frame's z axis, or its image under the tilt."""
    return (0., 0., 1.) if tilt is None else tuple(float(x) for x in tilt.apply(np.array((0., 0., 1.))))


def spin(angle_deg, tilt=None):
    """A finite rotation about the world axis, eastward for a positive angle."""
    return Rotation.from_axis_angle(axis(tilt), math.radians(angle_deg))


def _kinds(world):
    return {int(index): dict(fields) for index, fields in CASE['worlds'][world]['kinds'].items()}


def lune_world(*, tilt=None, **changes):
    """The case's 'lune' world: plates east and west, a ridge on meridian 0 and a trench on the far meridian.

    The trench record runs south to north with east on its left; west is the declared subducting side.
    """
    world = CASE['worlds']['lune']
    longitudes, latitudes = mesh(world['mesh'])
    values = dict(longitudes_deg=longitudes, latitudes_deg=latitudes, plates=tuple(world['plates']), tilt=tilt,
                  kinds=_kinds('lune'))
    values.update(changes)
    return sector_world(**values)


def three_plates(*, tilt=None, kinds=None, **changes):
    """The case's 'three_plates' world: C from 0 to 120 degrees, A from 120 to 240, B from 240 to 360.

    Meridian 2 is the ridge C|A, meridian 4 the trench A|B with A subducting, meridian 0 the boundary B|C.
    """
    world = CASE['worlds']['three_plates']
    declared = _kinds('three_plates')
    declared.update(kinds or {})
    longitudes, latitudes = mesh(world['mesh'])
    values = dict(longitudes_deg=longitudes, latitudes_deg=latitudes, plates=tuple(world['plates']),
                  kinds=declared, tilt=tilt)
    values.update(changes)
    return sector_world(**values)


def crust(network, **changes):
    """One inherited cohort per plate with the D3 control's declared areal values in one phase."""
    values = dict(phases=tuple(_MOVING['phases']), mass_per_area_kg_m2={'crust': D3_MASS_PER_AREA},
                  thickness_m={'crust': D3_THICKNESS}, enthalpy_per_area_j_m2=INHERITED_ENTHALPY_PER_AREA,
                  exteriors=EXTERIORS)
    values.update(changes)
    return S.initial_sphere(network, material(network, **values))


def supply(boundary_id, side, **changes):
    values = dict(boundary_id=boundary_id, side=side, source='mantle-source', material_id='declared-new-crust',
                  origin_id=SOURCE+'#ridge-supply', mass_per_area_kg_m2={'crust': D3_MASS_PER_AREA},
                  thickness_m={'crust': D3_THICKNESS}, enthalpy_per_area_j_m2=D3_ENTHALPY_PER_AREA)
    values.update(changes)
    return T.Supply(**values)


def both_sides(boundary_id, **changes):
    return (supply(boundary_id, 'left', **changes), supply(boundary_id, 'right', **changes))


def sink(boundary_id, destinations=(('slab', 1.),)):
    return T.Sink(boundary_id, destinations)


def one_plate_motion(degrees, step=0, tilt=None, plate='A', ridge='boundary-m02', trench='boundary-m04', **changes):
    """In the 'three_plates' world: ``plate`` turns between its fixed neighbours, a ridge behind and a trench ahead."""
    values = dict(start_step=step, end_step=step+1,
                  rotations={name: spin(degrees, tilt) if name == plate else IDENTITY for name in 'ABC'},
                  supplies=both_sides(ridge), sinks=(sink(trench),))
    values.update(changes)
    return T.Motion(**values)


def longitude_deg(directions, tilt=None):
    """Longitudes of directions about the world axis, in degrees in [0, 360)."""
    points = np.asarray(directions, dtype=float).reshape(-1, 3)
    if tilt is not None:
        points = tilt.inverse().apply(points)
    return np.degrees(np.arctan2(points[:, 1], points[:, 0])) % 360.
