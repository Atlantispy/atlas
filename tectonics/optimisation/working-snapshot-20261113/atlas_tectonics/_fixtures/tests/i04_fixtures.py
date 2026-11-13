"""Shared I04 Part A control inputs: every value comes from cases/i04_controls_v1.json (authored, not calibration)."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np

import i03_fixtures as F
from atlas_tectonics import integration_driving as D
from atlas_tectonics import integration_ports as P
from atlas_tectonics import integration_sphere as S
from atlas_tectonics.coordinates import SphericalFrame
from atlas_tectonics.kinematics import Rotation


CASES = Path(__file__).resolve().parents[1]/'cases'
CASE = json.loads((CASES/'i04_controls_v1.json').read_text(encoding='utf-8'))
POLICY = CASE['policy']
SOURCE = 'tectonics/tests/i04_fixtures.py'
GPE = CASE['gpe_hemispheres']
D1 = CASE['d1_closures']
RADIUS_M = CASE['sphere']['radius_m']
IDENTITY = Rotation((1., 0., 0., 0.))


def datum():
    return D.Datum(**GPE['datum'])


def hemispheres(edges, *, latitudes_deg=None, kind=S.TRANSFORM, radius=RADIUS_M):
    """North and south plates sharing one closed equator record of ``edges`` equal edges (north on its left)."""
    latitudes = GPE['latitudes_deg'] if latitudes_deg is None else latitudes_deg
    longitudes = [360.*i/edges for i in range(edges)]
    vertices, rings = F.sector_mesh(longitudes, latitudes)
    equator = latitudes.index(0)

    def owner(name):
        if name.endswith('south'):
            return 'south'
        if name.endswith('north'):
            return 'north'
        return 'north' if int(name[-2:]) >= equator else 'south'
    faces = tuple(S.Face(name, owner(name), ring) for name, ring in rings.items())
    plates = (S.Plate('north', IDENTITY), S.Plate('south', IDENTITY))
    chain = tuple(F.vertex(i, equator) for i in range(edges))
    fields = dict(accretion_fraction=.5) if kind == S.RIDGE else {}
    boundary = S.Boundary('equator', kind, 'north', 'south', chain, S.Origin(S.INITIAL, SOURCE), closed=True,
                          **fields)
    return S.build_network(SphericalFrame(radius, CASE['sphere']['frame_id']), vertices, faces, plates,
                           (boundary,), epoch_id=CASE['sphere']['epoch_id'], time_s=0.)


def octahedron(**changes):
    return F.octahedron(**changes)


def state(network):
    return S.initial_sphere(network, F.material(network))


CONTROL_ID = hashlib.sha256((CASES/'i04_controls_v1.json').read_bytes()).hexdigest()


def header(port, network, support, *, state_id=None, time_s=0.):
    parent = state(network).state_id if state_id is None else state_id
    return P.Header(port, parent, (0, 0, time_s, time_s), time_s, network.network_id, support.support_id,
                    D.datum_id(datum()), CONTROL_ID, network.sphere.frame_id, 'I05 (authored control input)', SOURCE)


def single_layer_columns(network, support, thickness_of, *, density=None, alpha=None, temperature=None,
                         water_depth_m=None, water_source=None, state_id=None):
    """P1: one layer per trace point; thickness_of(direction, side) gives metres (sides 0 left, 1 right)."""
    density = GPE['crust_density_kg_m3'] if density is None else density
    alpha = GPE['alpha_per_k'] if alpha is None else alpha
    temperature = GPE['temperature_k'] if temperature is None else temperature
    directions = support.directions()
    h = np.array([thickness_of(directions[i], i % 2) for i in range(len(directions))], dtype=float)
    n = len(h)
    return P.columns_port(header('P1', network, support, state_id=state_id), np.arange(n+1), h,
                          np.full(n, float(density)), np.full(n, float(alpha)), np.full(n, float(temperature)),
                          np.full(n, float(temperature)), sources=tuple('authored-crust' for _ in range(n)),
                          water_depth_m=water_depth_m, water_source=water_source)


def degree_one(direction, side):
    """The I01 GPE control field: h^2 = h0^2 + A n_x (continuous across every boundary)."""
    return math.sqrt(GPE['mean_crust_m']**2+GPE['thickness_squared_amplitude_m2']*float(direction[0]))


def gpe_forcing(network, drag=None, **changes):
    drag = GPE['drag_pa_s_m'] if drag is None else drag
    values = dict(basal_drag_pa_s_m={p: float(drag) for p in network.plate_ids}, gamma=float(GPE['reduction']),
                  provenance='cases/i04_controls_v1.json gpe_hemispheres (authored I01 control inputs)',
                  omitted=('slab_pull', 'mantle_traction', 'authored_torque', 'interface'),
                  frame_id=network.sphere.frame_id)
    values.update(changes)
    return D.Forcing(**values)


def authored_forcing(network, torques, *, drag=None, interface=None, **changes):
    drag = D1['basal_drag_pa_s_m'] if drag is None else drag
    omitted = ['gpe', 'slab_pull', 'mantle_traction'] + ([] if interface else ['interface'])
    values = dict(basal_drag_pa_s_m={p: float(drag) for p in network.plate_ids}, authored_torque_n_m=torques,
                  provenance='cases/i04_controls_v1.json d1_closures (authored known forcing)',
                  interface_k_pa_s=interface or (), omitted=tuple(omitted), frame_id=network.sphere.frame_id)
    values.update(changes)
    return D.Forcing(**values)


def rodrigues(axis, angle):
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    k = np.array([[0., -axis[2], axis[1]], [axis[2], 0., -axis[0]], [-axis[1], axis[0], 0.]])
    return np.eye(3)+math.sin(angle)*k+(1-math.cos(angle))*(k @ k)


def frame_rotation():
    record = CASE['frame_rotation']
    axis = np.asarray(record['axis'], dtype=float)
    axis /= np.linalg.norm(axis)
    return rodrigues(axis, record['angle_rad']), Rotation.from_axis_angle(tuple(axis), record['angle_rad'])
