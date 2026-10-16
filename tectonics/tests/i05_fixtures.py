"""Shared I05 control inputs: the I03 control worlds with I05 records (authored test inputs, labelled; no calibration).

The worlds are tests/i03_fixtures.py's. Their crust is the D3 control's (cases/i01_closures_v1.json: 2900 kg/m3,
7000 m), here without an I03 enthalpy basis, because I05 owns the heat of an attached moving state. The thermal
inputs are labelled authored values in the 'test:' namespace, as I04's water inputs are: four 1750 m sublayers,
k = 2.5 W/m/K, cp = 1000 J/kg/K, no radiogenic heat, a 273.15 K surface and a fixed 573.15 K base, and a linear
declared profile between them (the steady column).
SPDX-License-Identifier: AGPL-3.0-only
"""
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i03_fixtures as F                                    # noqa: E402

from atlas_tectonics import integration_material as M      # noqa: E402
from atlas_tectonics import integration_transfer as T      # noqa: E402

SOURCE = 'test: tectonics/tests/i05_fixtures.py authored thermal inputs'
T_REF = 273.15                                              # declared enthalpy reference (test input)
T_SURFACE, T_BASE = 273.15, 573.15
CONDUCTIVITY, HEAT_CAPACITY = 2.5, 1000.
LAYERS = 4
BIRTH_HISTORY = 'test:ridge-birth'
MYR = F.MYR_S


def sublayers(top=T_SURFACE, bottom=T_BASE, *, layers=LAYERS, cp=HEAT_CAPACITY, k=CONDUCTIVITY, radiogenic=0.,
              material='declared-crust'):
    """``layers`` equal sublayers of the D3 crust, linear from ``top`` to ``bottom``, top down."""
    h = F.D3_THICKNESS/layers
    edges = [top+(bottom-top)*i/layers for i in range(layers+1)]
    return tuple(M.Sublayer(material, 'crust', h, F.D3['density_kg_m3'], 3e-5, k, cp, radiogenic, edges[i],
                            edges[i+1], creep_law_id='test:creep', pore_pressure_pa=0.) for i in range(layers))


def record(cohort, *, top=T_SURFACE, bottom=T_BASE, base=T_BASE, kappa=None, bond=('INSIDE', False), **kwargs):
    layers = sublayers(top, bottom, **kwargs)
    return M.CohortRecord(cohort, 'test:profile-'+cohort, SOURCE, layers, T_SURFACE, base, None,
                          tuple(kappa or (0.,)*len(layers)), M.BondRecord(cohort, bond[1], bond[0]))


def birth_column(top=T_BASE, bottom=T_BASE, **kwargs):
    """A hot-born column at the fixed base temperature throughout (its declared birth state)."""
    return M.BirthColumn('test:birth-profile', SOURCE, sublayers(top, bottom, **kwargs), T_SURFACE, T_BASE)


def crust(network, **changes):
    """The I03 control crust without an I03 enthalpy basis (I05 owns the heat)."""
    values = dict(basis=None, enthalpy_per_area_j_m2=None)
    values.update(changes)
    return F.crust(network, **values)


def moving(state, records=None, **kwargs):
    records = records or tuple(record(c.cohort_id, **kwargs) for c in state.material.cohorts)
    return M.declare_moving(state, records, enthalpy_reference_k=T_REF)


def supplies(boundary_id='boundary-m02'):
    return F.both_sides(boundary_id, enthalpy_per_area_j_m2=None, history_id=BIRTH_HISTORY)


def motion(degrees=2., step=0, **changes):
    """Plate A turns between its fixed neighbours: a ridge behind (births) and a trench ahead (consumption)."""
    values = dict(supplies=supplies())
    values.update(changes)
    return F.one_plate_motion(degrees, step=step, **values)


def advance(step_count=0, **changes):
    return M.MovingAdvance(step_count, step_count+1, births=((BIRTH_HISTORY, birth_column()),), **changes)


def stepped(state, motion_):
    return T.advance(state, motion_, end_time_s=state.network.time_s+MYR)


def nodes(network, skip=()):
    """A declared node per face of a sector mesh: its sector's middle meridian at its band's middle latitude."""
    longitudes, latitudes = F.mesh(F.CASE['worlds']['static']['mesh'])
    bands = list(latitudes)
    out = []
    for face in network.face_ids:
        if face in skip:
            continue
        i = F.sector_of(face)
        lon = (longitudes[i]+(longitudes[(i+1) % len(longitudes)] or 360.))/2
        if face.endswith('south'):
            lat = (-90.+bands[0])/2
        elif face.endswith('north'):
            lat = (bands[-1]+90.)/2
        else:
            j = int(face[-2:])
            lat = (bands[j]+bands[j+1])/2
        out.append((face, F.direction(lon, lat)))
    return tuple(out)


def column_temperatures(moving_state, sphere, index):
    from atlas_tectonics import integration_thermal as H
    piece = sphere.material.pieces()[index]
    record = moving_state.cohort(piece.cohort_id)
    return H.temperatures(record, piece, moving_state.heat_j(index).tolist(), moving_state.enthalpy_reference_k,
                          sphere.material.phases)


def total_heat(moving_state):
    return math.fsum(math.fsum(moving_state.heat_j(i)) for i in range(len(moving_state.pieces)))


def frozen_bytes(moving_state):
    return {name: np.asarray(array).tobytes() for name, array in moving_state.arrays().items()}


# ----------------------------------------------------------------------------- the I02 moving control (I05-1)

def ledger_world():
    """The three-plate world at the I02 column's epoch and start, with plate A's crust heated."""
    import i02_workflow_fixtures as F2
    network = F.three_plates(epoch=F2.EPOCH, time_s=F2.START)
    state = crust(network)
    records = tuple(record(c.cohort_id, top=900. if c.cohort_id == 'inherited-A' else T_SURFACE,
                           bottom=1100. if c.cohort_id == 'inherited-A' else T_BASE)
                    for c in state.material.cohorts)
    return state, M.declare_moving(state, records, enthalpy_reference_k=T_REF)


def certificate(duration):
    """An authored MC-06 declaration over exactly one interval, two cells and one contact (test input): plain data
    for declaration checks only; it is not the network of any state, so an omission refuses it."""
    window = dict(duration_s=duration, envelope=dict(kind='declared_whole_window', difference_bounds_k=[100],
                                                     basis='test: authored whole-window bound'))
    return dict(capacities_j_k=[10**20, 10**20], contacts=[dict(left=0, right=1, conductivity_w_m_k=3, area_m2=1,
                                                                 distance_m=1000)],
                windows=[window], temperature_allowance_k=1)


def omission_certificate(sphere, moving_state, duration, *, allowance=1, bound=None):
    """An MC-06 omission declaration over exactly one interval: one whole window whose envelope bounds every contact
    of the state's own network (integration_thermal.omission_cells, in its order) by ``bound`` K.

    By default the bound is the range of the state's start temperatures and its cohorts' fixed surface and base
    temperatures. Without radiogenic heat (as in every fixture here) each column-only trajectory keeps its
    temperatures inside that range (the maximum principle of the vertical solve), so the range bounds every
    |T_i - T_j| over the whole window: a valid envelope, derived, not tuned. The cells and conductances are the
    state's own and are not declared."""
    from atlas_tectonics import integration_thermal as H
    records = {c.cohort_id: c for c in moving_state.cohorts}
    _, contacts = H.omission_cells(sphere, records)
    if bound is None:
        values = [t for i in range(len(sphere.material.pieces()))
                  for t in column_temperatures(moving_state, sphere, i)]
        values += [r.surface_temperature_k for r in records.values()]
        values += [r.base_temperature_k for r in records.values() if r.base_temperature_k is not None]
        bound = max(values)-min(values)
    window = dict(duration_s=duration, envelope=dict(kind='declared_whole_window',
                                                     difference_bounds_k=[bound]*len(contacts),
                                                     basis='test: range of the start and boundary temperatures'))
    return dict(windows=[window], temperature_allowance_k=allowance)


SPLIT_FACES = ('s01-b00', 's01-b01', 's01-b02', 's01-b03')


def ledger_plan(k, step_s, sphere, moving_state, degrees=0.4):
    """(Motion, MovingAdvance) of interval k of the moving control.

    Intervals 0 to 3 stand still and conduct on the undeformed three-plate mesh, whose contacts R-2 admits with the
    declared sector nodes: 0, 2 and 3 omit lateral heat under certificates on the state's own network (the carried
    bound chains 0 -> 2 -> 3, across the save after interval 3's parent), and 1 solves it. Interval 4 turns plate A
    between a ridge (births) and a trench (consumption) and splits inherited-C's pieces in sector 1; interval 5 merges
    two faces of C. Both are advection only, so they make the carried bound UNKNOWN and no omission follows them.
    ``sphere`` and ``moving_state`` are the interval's parent states, from which a mesh change lists every face and a
    certificate takes its cells."""
    network = sphere.network
    still = {p: F.IDENTITY for p in 'ABC'}
    if k == 4:
        from atlas_tectonics import integration_splits as P
        splits = (P.HistorySplit('inherited-C', (('test:history-c1', SPLIT_FACES),)),)
        motion_ = F.one_plate_motion(degrees, step=k, supplies=supplies(), history_splits=splits)
        return motion_, M.MovingAdvance(k, k+1, births=((BIRTH_HISTORY, birth_column()),))
    if k == 5:
        from test_i05_transport import merged_face
        faces = [f for f in network.faces if f.face_id not in ('s00-b01', 's00-b02')]+[merged_face()]
        return T.Motion(k, k+1, still, mesh=T.Mesh(tuple(faces))), M.MovingAdvance(k, k+1)
    if k == 1:
        conduction = M.Conduction('solve', nodes(network))
    else:
        conduction = M.Conduction('omit', nodes(network), certificate=omission_certificate(sphere, moving_state,
                                                                                            step_s))
    return T.Motion(k, k+1, still), M.MovingAdvance(k, k+1, conduction=conduction)
