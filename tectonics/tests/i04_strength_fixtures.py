"""Shared I04b control inputs (I04.3 D2 belts, I04.4 feedback): authored test inputs, labelled; no calibration.

The values are those fixed in tectonics/cases/i04_controls_v1.json ``part_b`` before the controls ran. The belt column
is the I01 weakening case's layered lithosphere (cases/i01_weakening_v1.json: wet quartzite and wet anorthite crust over
dry olivine, 100 km, ASPECT-form weakening over kappa in [1, 3] to factors 0.25), carried as one I03 phase 'crust' whose
areal mass is the column's own; the oracle's single-layer column is that case's upper crust alone. The belt width 100 km
is the I01 motion-coupling control's authored width; the D2 length 5 km is the contract's. The worlds are I03's sector
meshes: twin hemispheres with an equatorial transform carried by the south plate (no junctions), with latitude rows at
the belt's half-width so that the faces resolve the belt, and the I03 lune world (ridge and trench).
SPDX-License-Identifier: AGPL-3.0-only
"""
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i03_fixtures as F                                    # noqa: E402
import i04_fixtures as F4                                   # noqa: E402
import i05_fixtures as X                                    # noqa: E402

from atlas_tectonics import integration_driving as D      # noqa: E402
from atlas_tectonics import integration_feedback as B     # noqa: E402
from atlas_tectonics import integration_material as M     # noqa: E402
from atlas_tectonics import integration_sphere as S       # noqa: E402
from atlas_tectonics import integration_strength as G     # noqa: E402

CASES = Path(__file__).resolve().parents[1]/'cases'
CASE = json.loads((CASES/'i04_controls_v1.json').read_text(encoding='utf-8'))['part_b']
WEAKENING = json.loads((CASES/'i01_weakening_v1.json').read_text(encoding='utf-8'))
SOURCE = 'test: tectonics/tests/i04_strength_fixtures.py (I01 weakening case layers; authored, not calibration)'
LAYERS = WEAKENING['layers']
SPLIT = (2, 2, 1, 5)                  # 10 km sublayers of the four case layers, top down
ALPHA, CONDUCTIVITY, HEAT_CAPACITY = 3e-5, 2.5, 1000.
T_REF = 273.15
INPUTS = CASE['inputs']
WIDTH_M, ELL_M, ORDER = INPUTS['belt_width_m'], INPUTS['d2_length_m'], INPUTS['gauss_order_per_layer']
DRAG, TORQUE, KAPPA0 = INPUTS['basal_drag_pa_s_m'], INPUTS['authored_torque_n_m'], INPUTS['inherited_kappa']
INTERVAL_MYR = INPUTS['interval_myr']
RADIUS_M = F.RADIUS_M
MYR = F.MYR_S
SINGLE_T = 453.


def sublayers(*, warmer_k=0., single=False):
    """The layered column top down (each case layer split into SPLIT sublayers, linear in temperature within the
    layer), or the oracle's single upper-crust sublayer at SINGLE_T. ``warmer_k`` raises every temperature."""
    if single:
        layer = LAYERS[0]
        return (M.Sublayer(layer['name'], 'crust', layer['thickness_m'], layer['density_kg_m3'], ALPHA, CONDUCTIVITY,
                           HEAT_CAPACITY, 0., SINGLE_T+warmer_k, SINGLE_T+warmer_k, creep_law_id='test:'+layer['name'],
                           pore_pressure_pa=0.),)
    out = []
    for layer, parts in zip(LAYERS, SPLIT):
        top, bottom = layer['temperature_k']
        h = layer['thickness_m']/parts
        for i in range(parts):
            t0, t1 = top+(bottom-top)*i/parts+warmer_k, top+(bottom-top)*(i+1)/parts+warmer_k
            out.append(M.Sublayer(layer['name'], 'crust', h, layer['density_kg_m3'], ALPHA, CONDUCTIVITY,
                                  HEAT_CAPACITY, 0., t0, t1, creep_law_id='test:'+layer['name'],
                                  pore_pressure_pa=0.))
    return tuple(out)


def thickness(single=False):
    return math.fsum(s.thickness_m for s in sublayers(single=single))


def mass(single=False):
    return math.fsum(s.reference_density_kg_m3*s.thickness_m for s in sublayers(single=single))


THICKNESS_M, MASS_PER_AREA = thickness(), mass()


def record(cohort, *, kappa=0., warmer_k=0., single=False, broken=False):
    layers = sublayers(warmer_k=warmer_k, single=single)
    return M.CohortRecord(cohort, 'test:profile-'+cohort, SOURCE, layers, layers[0].top_temperature_k,
                          layers[-1].bottom_temperature_k, None, (float(kappa),)*len(layers),
                          M.BondRecord(cohort, bool(broken), 'INSIDE'))


def crust(network, *, single=False, **changes):
    values = dict(mass_per_area_kg_m2={'crust': mass(single)}, thickness_m={'crust': thickness(single)})
    values.update(changes)
    return X.crust(network, **values)


BIRTH_HISTORY = X.BIRTH_HISTORY


def supplies(boundary_id='boundary-m02'):
    """Ridge supplies of the layered column on both sides (I05 owns the heat, so no I03 enthalpy)."""
    return F.both_sides(boundary_id, enthalpy_per_area_j_m2=None, history_id=BIRTH_HISTORY,
                        mass_per_area_kg_m2={'crust': MASS_PER_AREA}, thickness_m={'crust': THICKNESS_M})


def birth_column():
    """New ridge material: the layered column with its declared profile (authored test input)."""
    layers = sublayers()
    return M.BirthColumn('test:birth-profile', SOURCE, layers, layers[0].top_temperature_k,
                         layers[-1].bottom_temperature_k)


def births():
    return ((BIRTH_HISTORY, birth_column()),)


def moving(state, *, kappa=KAPPA0, warmer_k=0., single=False, records=None, kappa_of=None):
    """The declared moving state: one record per cohort, raw kappa ``kappa`` (or ``kappa_of(cohort)``)."""
    records = records or tuple(record(c.cohort_id, kappa=kappa if kappa_of is None else kappa_of(c.cohort_id),
                                      warmer_k=warmer_k, single=single) for c in state.material.cohorts)
    return M.declare_moving(state, records, enthalpy_reference_k=T_REF)


def half_width_deg(width_m=WIDTH_M):
    return math.degrees(width_m/(2*RADIUS_M))


def twin_latitudes(rows=1, width_m=WIDTH_M, latitudes_deg=None):
    half = half_width_deg(width_m)
    inner = [half*k/rows for k in range(1, rows+1)]
    return sorted(set((latitudes_deg or [-60., -30., 30., 60.])+[0.]+inner+[-x for x in inner]))


def twin(longitudes_deg=None, latitudes_deg=None, *, rows=1, width_m=WIDTH_M, tilt=None, epoch=None, time_s=None):
    """Two hemispheres, north and south, joined by a closed equatorial transform carried by the south plate (right).

    The latitudes always include the equator and the belt's half-width on both sides; ``rows`` subdivides each side
    of the belt into equal latitude rows (refinement). Equator vertices lie exactly at z = 0 and longitudes are
    uniform."""
    lons = longitudes_deg or [float(30*i) for i in range(12)]
    lats = twin_latitudes(rows, width_m, latitudes_deg)
    equator, count = lats.index(0.), len(lons)
    vertices, rings = F.sector_mesh(lons, lats, tilt=tilt)

    def owner(name):
        south = name.endswith('south') or ('-b' in name and int(name.rsplit('-b', 1)[1]) < equator)
        return 'south' if south else 'north'
    faces = tuple(S.Face(name, owner(name), ring) for name, ring in rings.items())
    chain = tuple(F.vertex(i, equator) for i in range(count))
    boundaries = (S.Boundary('equator', S.TRANSFORM, 'north', 'south', chain, F.origin(), closed=True,
                             carrier_side='right'),)
    plates = tuple(S.Plate(name, F.IDENTITY) for name in ('north', 'south'))
    return S.build_network(sphere=F.sphere(), vertices=vertices, faces=faces, plates=plates, boundaries=boundaries,
                           epoch_id=F.EPOCH if epoch is None else epoch, time_s=F.START if time_s is None else time_s)


def one_sided(*, side='right', width_m=WIDTH_M, **changes):
    """The twin world for a belt wholly on one side: rows at w/2R and w/R on that side (the carrier's, right =
    south by default)."""
    full = math.degrees(width_m/RADIUS_M)
    extra = -full if side == 'right' else full
    return twin(latitudes_deg=[-60., -30., 30., 60., extra], width_m=width_m, **changes)


def side_declaration(side='right', **changes):
    base = declaration(**changes)
    belts = tuple((name, G.Belt(b.width_m, b.length_m, b.healing_law_id, b.width_source, b.length_source, side))
                  for name, b in base.belts)
    return G.Declaration(belts, base.materials, base.creep_laws, base.order, base.provenance)


def row_cohorts(rows, width_m=WIDTH_M):
    """(cohort_of(face), kappa_of(cohort)) for a smooth inherited weakness kappa0(y) = KAPPA0 + exp(-(y/20 km)^2),
    taken per belt row at the row's centre distance y from the boundary (a physical profile, the same on every
    mesh); faces outside the belt rows carry the background KAPPA0 + exp(-(y/20 km)^2) at their own row too."""
    lats = twin_latitudes(rows, width_m)
    equator = lats.index(0.)
    centre = {}
    for j in range(len(lats)-1):
        mid = math.radians((lats[j]+lats[j+1])/2)*RADIUS_M
        centre['row%+03d' % (j-equator if j >= equator else j-equator)] = mid

    def cohort_of(face_id):
        if face_id.endswith('south') or face_id.endswith('north'):
            return 'cap-'+face_id[-5:]
        j = int(face_id.rsplit('-b', 1)[1])
        return 'row%+03d' % (j-equator)

    def kappa_of(cohort):
        if cohort.startswith('cap-'):
            return KAPPA0
        return KAPPA0+math.exp(-(centre[cohort]/2e4)**2)
    return cohort_of, kappa_of


def materials(*, scale_cohesion=1.):
    return tuple((layer['name'], G.BeltMaterial(layer['cohesion_pa']*scale_cohesion, layer['friction_rad'],
                                                 layer['plastic_viscosity_pa_s'], layer['grain_m'],
                                                 tuple(WEAKENING['weakening']['interval_engineering']),
                                                 WEAKENING['weakening']['cohesion_factor'],
                                                 WEAKENING['weakening']['friction_factor'], G.YIELD_CONVENTION,
                                                 SOURCE))
                 for layer in LAYERS)


def creep_laws():
    return tuple(('test:'+layer['name'], G.CreepLaw(tuple(dict(c) for c in layer['creep']), SOURCE))
                 for layer in LAYERS)


def declaration(*, boundaries=('equator',), width_m=WIDTH_M, ell_m=ELL_M, order=ORDER, scale_cohesion=1.):
    belts = tuple((name, G.Belt(width_m, ell_m, G.HEALING_NONE, SOURCE, SOURCE)) for name in boundaries)
    return G.Declaration(belts, materials(scale_cohesion=scale_cohesion), creep_laws(), order, SOURCE)


def forcing(torque_n_m=TORQUE, *, plate='north', belts=('equator',), frame=F.FRAME, drag=DRAG,
            plates=('north', 'south'), axis=(0., 0., 1.), omitted=('gpe', 'slab_pull', 'mantle_traction'), **changes):
    """Authored torque on one plate (about the world axis unless ``axis``), basal drag on every plate, the belts;
    the omitted terms declared omitted."""
    torque = tuple(float(torque_n_m)*a for a in axis)
    authored = ((plate, torque),) if torque_n_m else ()
    if not authored:
        omitted = tuple(omitted)+('authored_torque',)
    return D.Forcing(tuple((p, drag) for p in plates), SOURCE, authored_torque_n_m=authored, omitted=tuple(omitted),
                     frame_id=frame, belts=belts, **changes)


def inputs(torque_n_m=TORQUE, **changes):
    values = dict(declaration=changes.pop('declaration', declaration()),
                  forcing=changes.pop('forcing', forcing(torque_n_m)), datum=F4.datum())
    values.update(changes)
    return B.Inputs(**values)


def interval(state, years_myr=INTERVAL_MYR):
    step, time = state.network.step, state.network.time_s
    return (step, step+1, time, time+years_myr*MYR)


def twin_case(*, rows=1, kappa=KAPPA0, warmer_k=0., single=False, tilt=None, kappa_profile=False):
    """(state, moving) of the twin world with the belt column."""
    network = twin(rows=rows, tilt=tilt)
    if kappa_profile:
        cohort_of, kappa_of = row_cohorts(rows)
        state = crust(network, single=single, cohort_of=cohort_of)
        return state, moving(state, warmer_k=warmer_k, single=single, kappa_of=kappa_of)
    state = crust(network, single=single)
    return state, moving(state, kappa=kappa, warmer_k=warmer_k, single=single)
