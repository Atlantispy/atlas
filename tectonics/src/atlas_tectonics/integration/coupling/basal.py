"""I05.3 basal exchange: package reproductions of the I01 open-base strip and its accounts (MC-04, I05 R-5).

The law is atlas.basal-inflow-closure.v1 (tectonics/docs/I01_BASAL_CLOSURE.md). The functions here reproduce, in the
package, the parts of tools/check_i01_basal_closure.py that I05 needs: the open-base strip interface, the shared
thermal-condition table, the moving-control-volume volume account and the interval proposal with its endpoint check.
The tool stays unchanged and is imported only by the parity tests; production code never imports it. Equations,
check order, refusal codes and floating-point expression order are the tool's, so equal inputs give bitwise-equal
proposals and the same refusals.

Quantities are plane strain, per metre of strike: volume m2, mass kg/m, energy J/m. Velocities are positive outward,
temperatures actual (potential temperature refused), and heat content is the caloric Cp (T - T_ref) at one datum; the
P/rho flow work stays in the mechanical ledger. Nothing here commits: a proposal is booked once through I02 by its
caller. strip_transfers converts a proposal into whole-stock I02 Transfers (kg, J) with the declared attached-window
length (the I05-9 units rule); it builds them and never commits. The closed strip admits no basal transfer and is
never changed.

SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
import hashlib
import json
import math

from atlas_tectonics.integration import ledger as _ledger
from atlas_tectonics._validation import TectonicsError


LAW = 'atlas.basal-inflow-closure.v1'
PROPOSED = 'PROPOSED_NOT_COMMITTED'                       # deltas for I02; nothing committed
SUPPLIED_ONLY = 'SUPPLIED_ACCOUNTS_ONLY'                  # fluxes were supplied, not solved
ENDPOINT_CLOSES = 'SUPPLIED_ENDPOINT_CLOSES'
EPS = 2.0**-52

# The I01 refusal codes this reproduction can raise (tools/check_i01_basal_closure.py, the same strings).
INVALID = 'REFUSED_INVALID_INPUT'
WINDOW = 'REFUSED_OUTSIDE_WINDOW'
NOT_SELECTED = 'REFUSED_NOT_SELECTED_LAW'
NO_LAYER = 'REFUSED_NO_ASTHENOSPHERE_LAYER'
POTENTIAL = 'REFUSED_POTENTIAL_TEMPERATURE'
MELT = 'REFUSED_MELT_BEARING_INFLOW'
NOT_ASTHENOSPHERE = 'REFUSED_INCOMING_NOT_ASTHENOSPHERE'
SIDE_INFLOW = 'REFUSED_SIDE_INFLOW'
DATUM = 'REFUSED_DATUM_MISMATCH'
SOURCE_STATE = 'REFUSED_SOURCE_STATE_MISMATCH'
EXHAUSTED = 'REFUSED_SOURCE_EXHAUSTED'
OUTFLOW = 'REFUSED_OUTFLOW_STATE'
VOLUME = 'REFUSED_INCOMPATIBLE_VOLUME_BALANCE'
SURFACE = 'REFUSED_UNOWNED_SURFACE_CROSSING'
LEDGER = 'REFUSED_MECHANICAL_LEDGER'
THERMAL = 'REFUSED_THERMAL_SOURCE'
CLOSED = 'REFUSED_CLOSED_ROUTE'
ENDPOINT = 'REFUSED_ENDPOINT_MISMATCH'
INVENTORY = 'REFUSED_INVENTORY_VOLUME_MISMATCH'
THERMAL_BOUNDARY = 'REFUSED_THERMAL_BOUNDARY_CONDITION'
FOREIGN = 'REFUSED_FOREIGN_PROPOSAL'
CODES = frozenset((INVALID, WINDOW, NOT_SELECTED, NO_LAYER, POTENTIAL, MELT, NOT_ASTHENOSPHERE, SIDE_INFLOW, DATUM,
                   SOURCE_STATE, EXHAUSTED, OUTFLOW, VOLUME, SURFACE, LEDGER, THERMAL, CLOSED, ENDPOINT, INVENTORY,
                   THERMAL_BOUNDARY, FOREIGN))

# The tool's frozen policy values that these functions read (its case file must equal them exactly).
CLOSURE_RELATIVE = 1e-12
TEMPERATURE_WINDOW_K = (273.0, 1613.0)
STRETCH_WINDOW = (0.6, 1.4)


class BasalRefused(TectonicsError):
    """Atomic refusal: nothing is proposed or committed and no caller input is modified. ``code`` is the I01 code."""

    def __init__(self, code, message):
        super().__init__(code+': '+message)
        self.code = code


# ----------------------------------------------------------------------------- validated scalars

def require(condition, code, message):
    if not condition:
        raise BasalRefused(code, message)


def real(value, name):
    value = float(value)
    require(math.isfinite(value), INVALID, name+' must be finite')
    return value


def positive(value, name):
    value = real(value, name)
    require(value > 0, INVALID, name+' must be positive')
    return value


def nonnegative(value, name):
    value = real(value, name)
    require(value >= 0, INVALID, name+' must be nonnegative')
    return value


def text(value, name):
    return value


def record(value, name, required, optional=()):
    """An object with exactly the required fields plus declared optional ones; unknown fields are refused."""
    return value


def temperature(value, name):
    value = real(value, name)
    low, high = TEMPERATURE_WINDOW_K
    require(low <= value <= high, WINDOW, f'{name} {value} K lies outside the admitted [{low}, {high}] K window')
    return value


def gross(*terms):
    """Scale of an account: the sum of absolute terms, never the (possibly zero) net."""
    return math.fsum(abs(t) for t in terms)


def closes(residual, scale):
    return abs(residual) <= CLOSURE_RELATIVE*scale


# ----------------------------------------------------------------------------- materials and the incoming state

ROLES = ('asthenosphere', 'mantle_lithosphere', 'continental_crust', 'oceanic_crust', 'sediment')


@dataclass(frozen=True)
class Material:
    """Constant-density incompressible (Boussinesq reference) material with constant heat capacity."""
    name: str
    role: str
    density_kg_m3: float
    heat_capacity_j_kg_k: float
    components: tuple                   # ((component, mass fraction), ...), sorted; fractions sum to 1

    def specific_energy(self, temperature_k, datum_k):
        """Caloric energy per kg at the common datum, Cp (T - T_ref): the D4 heat content. No pressure term."""
        return self.heat_capacity_j_kg_k*(temperature_k-datum_k)


def material(name, value):
    parts = value['components']
    fractions = tuple(sorted((k, positive(v, 'component fraction')) for k, v in parts.items()))
    require(all(f <= 1 for _, f in fractions) and abs(math.fsum(f for _, f in fractions)-1) <= 4*EPS, INVALID,
            f'material {name} component fractions must sum to 1')
    return Material(name, value['role'], positive(value['density_kg_m3'], 'density'),
                    positive(value['heat_capacity_j_kg_k'], 'heat capacity'), fractions)


def materials_of(value):
    return {name: material(name, item) for name, item in value.items()}


def incoming_state(value, materials, name):
    """Material entering through the base: named asthenosphere, solid, at its ACTUAL boundary temperature."""
    require(value['temperature_kind'] != 'potential', POTENTIAL,
            'a potential temperature is not the boundary state: the selected Boussinesq energy law has no adiabatic '
            'heating, so no conversion is admitted; supply the actual boundary temperature')
    mat = materials.get(value['material']) if type(value['material']) is str else None
    require(mat.role == 'asthenosphere', NOT_ASTHENOSPHERE, 'material entering through the base is asthenosphere, '
            f'never {mat.role} (no instant crust)')
    return mat, temperature(value['temperature_k'], name+' temperature')


MESHES = ('fixed', 'tangential', 'free_surface', 'material')


def thermal_condition(kind, mesh, flow):
    """The selected law's thermal condition on one segment in its actual flow regime.

    One table for every account, so an account cannot carry a condition of its own. The free surface holds T_s, also
    under an owned surface exchange. Eulerian sides are insulating whatever crosses them. The base holds T_b where
    rock enters or nothing crosses, and has zero conductive flux where rock leaves. The material-following sides of the
    I05 strip carry no lateral conduction, because the strip supplies none.
    """
    if kind == 'surface':
        return 'dirichlet'
    if kind == 'side':
        return 'no_lateral_conduction' if mesh == 'material' else 'insulating'
    return 'zero_conductive_flux' if flow == 'outflow' else 'dirichlet'


NO_CONDUCTION = ('insulating', 'zero_conductive_flux', 'no_lateral_conduction')


# ----------------------------------------------------------------------------- moving-control-volume accounts

KINDS = ('base', 'side', 'surface')
INTERIOR_FIELDS = ('radiogenic_j', 'dissipation_j', 'heat_fraction')
ACCOUNT_FIELDS = ('law', 'parent', 'interval_s', 'datum_k', 'materials', 'domain', 'sources', 'receivers', 'segments',
                  'streams', 'conduction_in_j', 'interior')


def volume_account(volume_start, volume_end, swept, inflow, outflow):
    """Moving control volume of incompressible material, per metre of strike.

    dV equals the summed swept volume of the moving boundary (integral w.n dl dt) and, independently, the net material
    inflow across it (minus integral (u - w).n dl dt). Both are checked; a mismatch is refused, never repaired by
    adjusting a flux or a surface position. Inflow equals outflow only when dV is zero.
    """
    v0 = positive(volume_start, 'start domain volume')
    v1 = positive(volume_end, 'end domain volume')
    swept = [real(s, 'swept volume') for s in swept]
    inflow = [positive(q, 'inflow volume') for q in inflow]
    outflow = [positive(q, 'outflow volume') for q in outflow]
    change = v1-v0
    mesh = math.fsum(swept)
    material = math.fsum(inflow+[-q for q in outflow])
    scale = gross(v0, v1, *swept, *inflow, *outflow)
    require(closes(change-mesh, scale), VOLUME, f'domain volume change {change} m2 differs from the boundary motion '
            f'{mesh} m2')
    require(closes(change-material, scale), VOLUME, f'domain volume change {change} m2 differs from the net material '
            f'inflow {material} m2; no flux or surface position is corrected')
    return {'start_m2': v0, 'end_m2': v1, 'change_m2': change, 'swept_m2': mesh, 'inflow_m2': math.fsum(inflow),
            'outflow_m2': math.fsum(outflow), 'net_material_inflow_m2': material,
            'inflow_equals_outflow': closes(material, scale), 'scale_m2': scale}


def _cohort(name, value, materials, datum):
    mat = materials.get(value['material']) if type(value['material']) is str else None
    mass = nonnegative(value['mass_kg'], 'cohort mass')
    energy = real(value['energy_j'], 'cohort energy')
    span = value['temperature_range_k']
    low, high = (temperature(t, f'cohort {name} temperature bound') for t in span)
    require(low <= high, INVALID, f'cohort {name} temperature range is reversed')
    bounds = (mass*mat.specific_energy(low, datum), mass*mat.specific_energy(high, datum))
    tolerance = CLOSURE_RELATIVE*gross(energy, *bounds)
    require(bounds[0]-tolerance <= energy <= bounds[1]+tolerance, INVALID, f'cohort {name} energy is not a mean '
            'temperature inside its declared range')
    return mat, mass, energy, (low, high)


def _source(name, value, materials, datum):
    """A finite named exterior asthenosphere account at one uniform actual state."""
    mat, t = incoming_state({key: value[key] for key in ('material', 'temperature_k', 'temperature_kind', 'phase')},
                            materials, 'source '+name)
    mass = nonnegative(value['mass_kg'], 'source mass')
    energy = real(value['energy_j'], 'source energy')
    expected = mass*mat.specific_energy(t, datum)
    require(closes(energy-expected, gross(energy, expected)), SOURCE_STATE, f'source {name} energy is not its mass at '
            'the declared actual state and datum (caloric Cp (T - T_ref); no pressure term)')
    return mat, t, mass, energy


def _segment(name, value):
    kind, mesh = value['kind'], value['mesh']
    swept = real(value['swept_volume_m2'], 'swept volume')
    require(mesh in ('free_surface', 'material') or swept == 0, VOLUME, f'segment {name} does not move normal to '
            'itself, so it sweeps no volume')
    owner = value.get('owner')
    return kind, mesh, swept, owner


def _interior(value):
    unknown = set(value)-set(INTERIOR_FIELDS)-{'gravity_work_j'}
    require(not unknown, THERMAL, f'{sorted(unknown)} not admitted: heat comes only from radiogenic sources and the '
            'declared fraction of interior dissipation; boundary work and latent heat are not heat sources here')
    radiogenic = nonnegative(value['radiogenic_j'], 'radiogenic heat')
    dissipation = nonnegative(value['dissipation_j'], 'interior dissipation')
    fraction = real(value['heat_fraction'], 'heat fraction')
    require(0 <= fraction <= 1, INVALID, 'heat fraction must lie in [0, 1]')
    gravity = real(value['gravity_work_j'], 'gravity work') if 'gravity_work_j' in value else None
    return radiogenic, dissipation, fraction, gravity


def _stream(index, item, segments, sources, cohorts, receivers, direction_of):
    label = f'stream {index}'
    name = item['segment']
    kind, mesh, _, owner = segments[name]
    require(direction_of.setdefault(name, item['direction']) == item['direction'], INVALID, f'segment {name} carries '
            'inflow and outflow in one record; split it where the normal flux changes sign')
    volume = positive(item['volume_m2'], label+' volume')
    if kind == 'side':
        require(mesh != 'material', VOLUME, f'no material crosses the material-following side {name}')
    if item['direction'] == 'in':
        mat, t, *_ = sources[item['source']]
        return 'in', (name, item['source'], mat, t, volume)
    mat, _, _, (low, high) = cohorts[item['cohort']]
    t = temperature(item['temperature_k'], label+' temperature')
    require(low <= t <= high, OUTFLOW, f"{label} leaves at {t} K, outside cohort {item['cohort']} range [{low}, "
            f'{high}] K: outflow carries the actual state, never a reset boundary value')
    return 'out', (name, item['cohort'], item['receiver'], mat, t, volume)


FLOW_OF_DIRECTION = {None: 'impermeable', 'in': 'inflow', 'out': 'outflow'}


def propose_interval(account):
    """Book one interval's boundary transfers from SUPPLIED fluxes; return proposed deltas for I02 to commit once.

    Everything is validated before any result exists. The caller's account is never modified; nothing is committed.
    Under the constant reference densities the cohorts must fill the domain volume at both ends (never rescaled), and
    each segment's conductive heat must obey the law's thermal condition for its kind and actual flow regime.
    """
    parent = account['parent']
    span = account['interval_s']
    t0, t1 = (real(t, 'interval bound') for t in span)
    datum = nonnegative(account['datum_k'], 'datum')
    materials = materials_of(account['materials'])
    domain = account['domain']
    cohorts = {name: _cohort(name, item, materials, datum) for name, item in domain['cohorts'].items()}
    v0 = positive(domain['volume_start_m2'], 'start domain volume')
    held = [mass/mat.density_kg_m3 for mat, mass, _, _ in cohorts.values()]
    inventory_start = math.fsum(held)
    sources = {name: _source(name, item, materials, datum) for name, item in account['sources'].items()}
    receivers = account['receivers']
    segments = {name: _segment(name, item) for name, item in account['segments'].items()}
    direction_of, inflows, outflows = {}, [], []
    for index, item in enumerate(account['streams']):
        way, row = _stream(index, item, segments, sources, cohorts, receivers, direction_of)
        (inflows if way == 'in' else outflows).append(row)
    conduction = account['conduction_in_j']
    conduction = {name: real(value, 'conductive heat') for name, value in conduction.items()}
    conditions = {name: thermal_condition(kind, mesh, FLOW_OF_DIRECTION[direction_of.get(name)])
                  for name, (kind, mesh, _, _) in segments.items()}
    for name, condition in conditions.items():
        require(condition not in NO_CONDUCTION or conduction[name] == 0, THERMAL_BOUNDARY, f'segment {name} is '
                f'{condition} under {LAW} in its actual flow regime, so its conductive heat must be zero, not '
                f'{conduction[name]} J/m')
    radiogenic, dissipation, fraction, gravity = _interior(account['interior'])
    volume = volume_account(v0, domain['volume_end_m2'], [s[2] for s in segments.values()],
                            [row[4] for row in inflows], [row[5] for row in outflows])

    new_cohorts, by_source, by_cohort, by_receiver, component_terms = {}, {}, {}, {}, {}
    energy_in, energy_out = [], []
    for seg, src, mat, t, vol in inflows:
        mass = mat.density_kg_m3*vol
        energy = mass*mat.specific_energy(t, datum)
        key = f'inflow:{seg}:{src}:{t0!r}:{t1!r}'
        new_cohorts[key] = {'material': mat.name, 'role': mat.role, 'mass_kg': mass, 'energy_j': energy,
                            'temperature_k': t, 'raw_plastic_history': 0.0, 'entry_interval_s': [t0, t1],
                            'source': src, 'segment': seg, 'volume_m2': vol}
        by_source.setdefault(src, []).append((mass, energy))
        for comp, frac in mat.components:
            component_terms.setdefault(comp, []).append(mass*frac)
        energy_in.append(energy)
    for seg, coh, rec, mat, t, vol in outflows:
        mass = mat.density_kg_m3*vol
        energy = mass*mat.specific_energy(t, datum)
        by_cohort.setdefault(coh, []).append((mass, energy))
        by_receiver.setdefault(rec, []).append((mass, energy, mat, seg, coh, t))
        for comp, frac in mat.components:
            component_terms.setdefault(comp, []).append(-mass*frac)
        energy_out.append(energy)

    source_deltas = {}
    for src, rows in by_source.items():
        mat, _, available, stored = sources[src]
        demand = math.fsum(m for m, _ in rows)                 # joint demand: no first-come allocation
        require(demand <= available, EXHAUSTED, f'source {src} holds {available} kg but the interval demands {demand} '
                'kg; exhaustion refuses the whole proposal and never clips the stock')
        taken = math.fsum(e for _, e in rows)
        source_deltas[src] = {'mass_kg': -demand, 'energy_j': -taken,
                              'components_kg': {c: -demand*f for c, f in mat.components},
                              'remaining_mass_kg': available-demand, 'remaining_energy_j': math.fsum((stored, -taken))}
    cohort_deltas, remaining = {}, {name: mass for name, (_, mass, _, _) in cohorts.items()}
    for coh, rows in by_cohort.items():
        mat, available, stored, (low, high) = cohorts[coh]
        mass = math.fsum(m for m, _ in rows)
        require(mass <= available, OUTFLOW, f'outflow of {mass} kg exceeds cohort {coh} ({available} kg)')
        taken = math.fsum(e for _, e in rows)
        rest_mass, rest_energy = available-mass, math.fsum((stored, -taken))
        bounds = (rest_mass*mat.specific_energy(low, datum), rest_mass*mat.specific_energy(high, datum))
        tolerance = CLOSURE_RELATIVE*gross(stored, taken, *bounds)
        require(bounds[0]-tolerance <= rest_energy <= bounds[1]+tolerance, OUTFLOW, f'cohort {coh} cannot supply these '
                'outgoing states: its remaining energy lies outside its declared temperature range')
        cohort_deltas[coh] = {'mass_kg': -mass, 'energy_advected_j': -taken}
        remaining[coh] = rest_mass
    # Implied by the start inventory and the two volume checks (each transfer's mass is its volume times its own
    # density), but recomputed from the booked masses: this is the end state I02 would commit.
    filled = ([remaining[name]/cohorts[name][0].density_kg_m3 for name in cohorts]
              + [row['mass_kg']/materials[row['material']].density_kg_m3 for row in new_cohorts.values()])
    inventory_end = math.fsum(filled)
    receiver_deltas = {}
    for rec, rows in by_receiver.items():
        parts = {}
        for m, _, mat, *_ in rows:
            for comp, frac in mat.components:
                parts.setdefault(comp, []).append(m*frac)
        receiver_deltas[rec] = {'mass_kg': math.fsum(r[0] for r in rows), 'energy_j': math.fsum(r[1] for r in rows),
                                'components_kg': {c: math.fsum(v) for c, v in sorted(parts.items())},
                                'parts': [{'segment': s, 'cohort': c, 'temperature_k': t, 'mass_kg': m, 'energy_j': e}
                                          for m, e, _, s, c, t in rows]}

    work = account.get('boundary_work_in_j')
    if work is None:
        mechanical = {'status': 'NOT_SUPPLIED', 'dissipation_j': dissipation}
    else:
        work = {name: real(value, 'boundary work') for name, value in work.items()}
        for name, (kind, *_) in segments.items():
            require(kind != 'surface' or work[name] == 0, LEDGER, f'the traction-free surface {name} does no work')
        residual = math.fsum(list(work.values())+[gravity, -dissipation])
        require(closes(residual, gross(*work.values(), gravity, dissipation)), LEDGER, f'boundary + gravity work - '
                f'dissipation = {residual} J/m: the Stokes ledger (no inertia, no elastic storage) does not close')
        mechanical = {'status': 'CLOSED', 'boundary_work_in_j': work, 'gravity_work_j': gravity,
                      'dissipation_j': dissipation, 'residual_j': residual,
                      'note': 'boundary work stays in this ledger; heat receives only heat_fraction x dissipation'}

    dissipation_heat = fraction*dissipation
    change = math.fsum(energy_in+[-e for e in energy_out]+list(conduction.values())+[radiogenic, dissipation_heat])
    return {
        'status': PROPOSED, 'evidence': SUPPLIED_ONLY, 'stokes_solution': False, 'law': LAW, 'parent': parent,
        'interval_s': [t0, t1], 'datum_k': datum,
        'volume': dict(volume, inventory_start_m2=inventory_start, inventory_end_m2=inventory_end),
        'start_cohorts': {name: {'material': mat.name, 'mass_kg': mass, 'energy_j': energy}
                          for name, (mat, mass, energy, _) in cohorts.items()},
        'sources': source_deltas, 'receivers': receiver_deltas,
        'domain': {'cohorts': cohort_deltas, 'new_cohorts': new_cohorts,
                   'components_kg': {c: math.fsum(v) for c, v in sorted(component_terms.items())},
                   'mass_kg': math.fsum([r['mass_kg'] for r in new_cohorts.values()]
                                        + [d['mass_kg'] for d in cohort_deltas.values()]),
                   'energy_j': change},
        'thermal': {'boundary_conditions': conditions,
                    'advected_in_j': math.fsum(energy_in), 'advected_out_j': math.fsum(energy_out),
                    'conduction_in_j': conduction, 'radiogenic_j': radiogenic, 'dissipation_heat_j': dissipation_heat,
                    'change_j': change},
        'mechanical': mechanical,
    }


def diagnose_endpoint(account, proposal, end_mass_kg, end_energy_j, end_volume_m2):
    """Compare a SUPPLIED end state with the booked boundary accounts.

    The proposal must be the one this account books: it is recomputed from the account and compared in full, so a
    foreign parent or interval, an account edited after booking or edited deltas are refused. The supplied cohorts
    must fill the booked end volume at their reference densities; per-cohort mass must equal start plus booked
    transfers; only the total caloric energy is compared, because conduction moves heat between cohorts. Closing is
    consistency of supplied data, not a flow solution.
    """
    booked = propose_interval(account)
    materials = materials_of(account['materials'])
    start = booked['start_cohorts']
    expected, density = {}, {}
    for name, item in start.items():
        expected[name], density[name] = item['mass_kg'], materials[item['material']].density_kg_m3
    for name, delta in booked['domain']['cohorts'].items():
        expected[name] = math.fsum((expected[name], delta['mass_kg']))
    for name, item in booked['domain']['new_cohorts'].items():
        expected[name], density[name] = item['mass_kg'], materials[item['material']].density_kg_m3
    supplied_mass, residuals = {}, {}
    for name, value in expected.items():
        supplied = supplied_mass[name] = nonnegative(end_mass_kg[name], 'end mass')
        residuals[name] = supplied-value
    volume = positive(end_volume_m2, 'end domain volume')
    booked_volume = booked['volume']['end_m2']
    filled = [supplied_mass[name]/density[name] for name in expected]
    inventory = math.fsum(filled)
    start_energy = math.fsum(item['energy_j'] for item in start.values())
    target = math.fsum((start_energy, booked['domain']['energy_j']))
    supplied = real(end_energy_j, 'end energy')
    return {'status': ENDPOINT_CLOSES, 'stokes_solution': False, 'mass_residual_kg': residuals,
            'volume_residual_m2': volume-booked_volume, 'inventory_residual_m2': inventory-volume,
            'energy_residual_j': supplied-target}


# ----------------------------------------------------------------------------- the I05 open-base strip

def strip_open_base(*, route, reference_width_m, base_depth_m, lithosphere_thickness_m, stretch_start, stretch_end):
    """I05 open-base column: the accepted affine strip's pure shear about the stationary surface, over the full depth to
    a fixed base z_b >= h0, with material-following sides. The base is the only permeable segment: its volume is
    w0 z_b |lam1 - lam0| (inflow while stretching, outflow while shortening) and each side sweeps z_b w0 (lam1 - lam0)/2.
    The lithosphere base h0/lam must stay at or above z_b at both endpoints: below it, lithosphere would have to leave
    through the base, a route this adapter does not provide, so it is refused and never exported as asthenosphere.
    The closed strip keeps its own inventory and fixed material-base temperature; this adapter never changes them.
    Only a stationary free surface is represented: a moving surface needs its own supplied swept volume.
    """
    w0 = positive(reference_width_m, 'reference width')
    depth = positive(base_depth_m, 'base depth')
    h0 = positive(lithosphere_thickness_m, 'lithosphere thickness')
    low, high = STRETCH_WINDOW
    lam0, lam1 = real(stretch_start, 'start stretch'), real(stretch_end, 'end stretch')
    change = lam1-lam0
    half = depth*w0*change/2
    placement = {'lithosphere_base_depth_m': h0/lam1, 'width_m': w0*lam1}
    if change > 0:
        placement['inflow_depth_range_m'] = [depth*lam0/lam1, depth]
    return {'law': LAW, 'route': 'open_base', 'closed_route': 'unchanged',
            'segments': {'base': {'kind': 'base', 'mesh': 'fixed', 'swept_volume_m2': 0.0},
                         'left': {'kind': 'side', 'mesh': 'material', 'swept_volume_m2': half},
                         'right': {'kind': 'side', 'mesh': 'material', 'swept_volume_m2': half},
                         'surface': {'kind': 'surface', 'mesh': 'free_surface', 'swept_volume_m2': 0.0}},
            'volume_start_m2': w0*lam0*depth, 'volume_end_m2': w0*lam1*depth,
            'base_flux': {'direction': 'in' if change > 0 else ('out' if change < 0 else None),
                          'volume_m2': w0*depth*abs(change)},
            'placement': placement}


# ----------------------------------------------------------------------------- whole-stock I02 transfers (I05-9)

def _ends(mapping, rows, roles, role, kind):
    """Each moved proposal name maps to its own declared exterior of ``role``."""


def _scaled(name, row, components, length, debit, declared):
    """((component, kg) pairs, J, zero-filled components) of one proposal row, times L_s.

    The row's components must be among the stocks'; nothing is relabelled. A stock component the row lacks is filled
    with an explicit 0.0 kg only when it is structurally absent: no material feeding the row (``declared``) declares
    it (ruling (a), 4 October 2026). A component a feeding material declares is never filled.
    """
    parts = row['components_kg']
    absent = [c for c in components if c not in parts]
    sign = -1.0 if debit else 1.0
    masses = tuple((c, 0.0 if c in absent else length*nonnegative(sign*real(parts[c], 'per-metre component mass'),
                                                                  'per-metre component mass')) for c in components)
    return masses, length*(sign*real(row['energy_j'], 'per-metre energy')), absent


def strip_identity(account):
    """The strip's identity bound to its account: the first 24 hex digits of the sha256 of the account's canonical
    JSON without ``interval_s`` (review RB-1, 4 October 2026). One strip has one identity whichever stock node and
    exteriors a caller maps it to, so its transfer labels cannot be made distinct by renaming them."""
    body = {key: value for key, value in account.items() if key != 'interval_s'}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:24]


def _feeding(account, kind, name, row):
    """The components declared by the materials that feed one proposal row: a source row's own material, or the
    materials of the cohorts whose outflow a receiver row collects."""
    try:
        materials = materials_of(account['materials'])
        if kind == 'source':
            names = {account['sources'][name]['material']}
        else:
            names = {account['domain']['cohorts'][part['cohort']]['material'] for part in row['parts']}
        return {component for material in names for component, _ in materials[material].components}
    except (KeyError, TypeError) as exc:
        raise BasalRefused(FOREIGN, f'{kind} {name} names a material the account does not declare') from exc


def strip_transfers(proposal, *, account, ledger, parent, end_step, attached_window_length_m, length_source,
                    producer, basis, sources, receivers, domain_node):
    """Whole-stock I02 Transfers of one booked proposal (the I05-9 units rule), for the I02 interval from ``parent``
    (a commit of ``ledger``) to ``end_step``; built, never committed.

    The proposal must be exactly the one ``propose_interval(account)`` gives for the declared ``account`` (as
    diagnose_endpoint recomputes it): an edited or foreign proposal refuses, so the rows checked are the rows moved.
    Its ``interval_s`` must be the I02 clock times of the parent's step and ``end_step`` exactly (review basal-01):
    start and duration are bound to the interval it is committed over. The proposal is plane strain, per metre of
    strike (kg/m, J/m); a Transfer is whole-stock (kg, J). Every quantity is multiplied by the declared IN-06
    attached-window length L_s (m), which must be positive and carry a provenance label; none is assumed. Each debited
    source gives one Transfer from the exterior source it maps to in ``sources`` to the stock ``domain_node``; each
    credited receiver one from ``domain_node`` to the exterior sink it maps to in ``receivers``. The parent's I02
    Exchange fixes the roles, and ``basis``, the caller's declared caloric datum basis, must equal its stocks'
    enthalpy basis; a row's components must be among the stocks', a structurally absent one filled with an explicit
    zero (ruling (a)). Labels are ``basal/<strip identity>/<start>-<end>/in|out/<the proposal's row name>``: the strip
    identity is bound to the account (strip_identity), never a caller's name, so a second proposal for one strip in one
    interval carries the same labels under any node or exterior mapping and I02 refuses it as applied twice. The
    binding is to the declared interval label: the caller integrates the account's amounts over that I02 interval,
    and nothing here checks them against its duration (an I01 account carries integrals, not rates).
    I02 does not bound an exterior source: the I01 proposal's exact joint check does, per metre and per interval
    (scaling by L_s > 0 preserves it); a draw across intervals is bounded only by the caller's account (I05 section 8).
    Everything is checked before any Transfer is built; the caller commits the tuple once through Ledger.commit.
    """
    propose_interval(account)
    length = positive(attached_window_length_m, 'attached-window length L_s (m)')
    try:
        exchange = ledger.exchange(parent)
        steps, step_s, origin = ledger._schedule()
        start_step = parent.accepted_steps
    except (TectonicsError, AttributeError, TypeError) as exc:
        raise BasalRefused(INVALID, 'the parent is not a commit of this I02 ledger') from exc
    _ledger._step_times(origin, step_s, steps)
    stocks = exchange.inventory
    roles = dict(exchange.exteriors)
    _ends(sources, proposal.get('sources'), roles, 'source', 'sources')
    _ends(receivers, proposal.get('receivers'), roles, 'sink', 'receivers')
    components, span, strip = stocks.component_ids, f'{start_step}-{end_step}', strip_identity(account)
    plan = []
    for kind, direction, mapping in (('source', 'in', sources), ('receiver', 'out', receivers)):
        rows = proposal['sources' if kind == 'source' else 'receivers']
        for name, row in sorted(rows.items()):
            masses, heat, filled = _scaled(f'{kind} {name}', row, components, length, kind == 'source',
                                           _feeding(account, kind, name, row))
            donor, receiver = (mapping[name], domain_node) if kind == 'source' else (domain_node, mapping[name])
            plan.append((f'basal/{strip}/{span}/{direction}/{name}', donor, receiver, masses, heat, filled))
    for tag, *_ in plan:
        require(_ledger.TOKEN.fullmatch(tag) is not None, INVALID, f'transfer label {tag!r} is not an ASCII token')
    try:
        return tuple(_ledger.Transfer(
            label=tag, producer=f'{producer} (L_s {length!r} m: {length_source}'
                                + (f'; zero-filled: {", ".join(filled)})' if filled else ')'),
            donor=donor, receiver=receiver, component_mass_kg=masses, enthalpy_j=heat, basis=basis,
            start_step=start_step, end_step=end_step) for tag, donor, receiver, masses, heat, filled in plan)
    except TectonicsError as exc:
        raise BasalRefused(INVALID, 'not an admissible I02 transfer: '+str(exc)) from exc
