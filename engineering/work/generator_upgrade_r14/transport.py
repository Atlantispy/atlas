"""Preserved finite-material routing with conservative R13 water/heat ports.

The surface store is the R3 lagged transit compartment: no reinfiltration,
pond pressure or new heat exchange. All moved sediment must be thawed. Terrain
time records the operator dose; this split does not advance the soil clock.
"""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
import math

from . import provenance, remap, terrain as successor_terrain


def _q(value, name, *, signed=False, positive=False):
    if type(value) not in (int, float, str, F):
        raise ValueError(name + ': finite number or bounded rational required')
    if isinstance(value, str) and len(value) > 5000:
        raise ValueError(name + ': rational representation exceeds budget')
    try:
        result = F(value)
    except (ValueError, ZeroDivisionError, OverflowError) as error:
        raise ValueError(name + ': invalid rational') from error
    if (max(result.numerator.bit_length(), result.denominator.bit_length()) > 8192
            or (not signed and result < 0) or (positive and result <= 0)):
        raise ValueError(name + ': physical/arithmetic bound exceeded')
    return result


def _plain(value):
    if isinstance(value, F):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_plain(x) for x in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _routes(flow, reconciliation):
    return _plain({**{key: flow[key] for key in
                   ('rows', 'receivers', 'slopes', 'external_exports_m3')},
                   'native_geometry_reconciliation': reconciliation})


def _landscape(tt, cells, stocks, elapsed_years, *, reconciliation=None):
    columns = []
    for key in sorted(cells):
        cell = cells[key]
        area = _q(cell['area_m2'], 'cell area', positive=True)
        layers = []
        for row in reversed(stocks[key]):
            material, layer = row['material'], row['layer']
            mass = _q(material['dry_mass_kg_m2'], 'dry material mass', positive=True)
            density = _q(material['grain_density_kg_m3'], 'grain density', positive=True)
            depth = _q(layer['thickness_m'], 'authoritative soil thickness', positive=True)
            soil_phi = _q(layer['theta_s'], 'soil porosity')
            solid = mass/density
            residual = remap._roundoff(solid, depth*(1-soil_phi), 'native/soil solid geometry')
            # M, rho and the actual R13 binary64 depth are authoritative here.
            # Reconcile ONLY the terrain-side porosity, within the pre-existing
            # representation gate. Independent binary64 phi divisors otherwise
            # multiply when exact native depths are summed across layers.
            native_phi = _q(1-solid/depth, 'reconciled native porosity', signed=True)
            if not 0 < native_phi < 1:
                raise ValueError('reconciled native porosity outside (0,1); no clipping')
            native = tt.Layer(material['material_id'], mass*area, density,
                              native_phi, material['phase'], material['evidence'])
            if native.bulk_volume_m3/area != depth:
                raise ArithmeticError('reconciled native depth differs from authoritative soil depth')
            layers.append(native)
            if reconciliation is not None:
                reconciliation.append({'cell_id': key, 'layer_id': layer['layer_id'],
                    'soil_porosity': layer['theta_s'], 'native_porosity': str(native_phi),
                    'native_minus_soil_porosity': str(native_phi-soil_phi),
                    'solid_volume_residual_m': str(residual), 'native_depth_residual_m': '0',
                    'policy': 'TERRAIN_ONLY_64_ULP_SOLID_VOLUME_RECONCILIATION; exact dry mass/density and represented R13 depth preserved; hydraulic porosity unchanged'})
        columns.append((key, tt.Column(area,
            _q(cell['base_elevation_m'], 'base elevation', signed=True), tuple(layers),
            cell['model']['source_status'])))
    return tt.LandscapeState(tuple(columns), elapsed_years)


def _target(source, physical, area, water, enthalpy, capacity, head_guess, *, layer_id=None):
    layer = deepcopy(source['layer'])
    if layer_id is not None:
        layer['layer_id'] = layer_id
        layer['theta_s'] = float(physical.porosity)  # Supplied NEW deposit packing.
    # Retained layers keep their hydraulic law: terrain-only reconciliation
    # must not become a silently revised retention/saturation porosity.
    material = dict(source['material'], material_id=physical.material_id,
                    phase=physical.phase, grain_density_kg_m3=str(physical.grain_density_kg_m3),
                    dry_mass_kg_m2=str(physical.mass_kg/area), evidence=physical.evidence)
    return {'layer': layer, 'material': material, 'water_m': str(water/area),
            'enthalpy_j_m2': str(enthalpy/area),
            'dry_heat_capacity_j_m2_k': str(capacity/area), 'head_guess_m': head_guess}


def routes(cells, connectors, *, seconds_per_year, duration_s=1):
    """Validate current soil/material support and expose zero-volume topology."""
    if type(cells) is not dict or not 1 <= len(cells) <= 32:
        raise ValueError('one to 32 explicit transport cells required')
    calendar = _q(seconds_per_year, 'seconds per model year', positive=True)
    duration = _q(duration_s, 'routing duration', positive=True)
    bundle, tt = provenance.backend()
    stocks = {k: remap.layer_stocks(c['model'], c['soil'], c['materials']) for k, c in cells.items()}
    clocks = {_q(c['soil']['elapsed_seconds'], 'soil clock') for c in cells.values()}
    if len(clocks) != 1:
        raise ValueError('routing cell clocks differ')
    reconciliation = []
    state = _landscape(tt, cells, stocks, next(iter(clocks))/calendar, reconciliation=reconciliation)
    edges = tuple(tt.Connector(**dict(row)) for row in connectors)
    result = tt.route_water(state, {k: F() for k in cells}, edges, duration_years=duration/calendar)
    provenance.verify_backend()
    return _routes(result, reconciliation)


def step(cells, connectors, erosion_laws, sediment_laws, deposition_templates, *,
         duration_s, seconds_per_year, controls, soil_controls, evidence):
    """One uncommitted split trial; the owner supplies whole-step refinement.

    Dataclass inputs are plain field dictionaries, including nested
    PhysicalProperty dictionaries inside each ErosionLaw. Extensive outputs and
    ledgers preserve represented rationals as strings. No input is mutated.
    """
    if type(cells) is not dict or not 1 <= len(cells) <= 32:
        raise ValueError('one to 32 explicit transport cells required')
    if type(evidence) is not str or not evidence.strip() or len(evidence) > 4096:
        raise ValueError('explicit bounded transport evidence required')
    duration = _q(duration_s, 'transport duration', positive=True)
    calendar = _q(seconds_per_year, 'seconds per model year', positive=True)
    bundle, tt = provenance.backend()
    stocks, releases, release_heat, retained_water, retained_heat = {}, {}, {}, {}, {}
    constants = next(iter(cells.values()))['model']['constants']
    elapsed = None
    initial_water = initial_energy = initial_capacity = F()
    for key in sorted(cells):
        cell = cells[key]
        if cell['model']['constants'] != constants:
            raise ValueError('transport requires one common fluid/enthalpy datum')
        clock = _q(cell['soil']['elapsed_seconds'], 'soil clock')
        if elapsed is not None and clock != elapsed:
            raise ValueError('transport cell clocks differ')
        elapsed = clock
        rows = remap.layer_stocks(cell['model'], cell['soil'], cell['materials'])
        stocks[key] = rows
        area = _q(cell['area_m2'], 'cell area', positive=True)
        water = _q(cell['surface_water_m3'], 'surface transit water')
        energy = _q(cell['surface_enthalpy_j'], 'surface transit enthalpy', signed=True)
        if not water and energy:
            raise ValueError('empty surface transit store cannot contain enthalpy')
        residence = _q(cell['surface_residence_seconds'], 'surface residence time', positive=True)
        fraction = F(-math.expm1(-float(duration/residence)))
        if fraction <= 0:
            raise ValueError('positive transit release underflows representation')
        releases[key], release_heat[key] = water*fraction, energy*fraction
        retained_water[key], retained_heat[key] = water-releases[key], energy-release_heat[key]
        initial_water += water + area*sum((_q(r['water_m'], 'layer water') for r in rows), F())
        initial_energy += energy + area*sum((_q(r['enthalpy_j_m2'], 'layer enthalpy', signed=True) for r in rows), F())
        initial_capacity += area*sum((_q(r['dry_heat_capacity_j_m2_k'], 'dry heat capacity') for r in rows), F())
    initial_reconciliation = []
    state = _landscape(tt, cells, stocks, elapsed/calendar, reconciliation=initial_reconciliation)
    edges = tuple(tt.Connector(**dict(row)) for row in connectors)
    laws = tuple(tt.ErosionLaw(row['material_id'], row['phase'],
        tt.PhysicalProperty(**row['k_per_year']), tt.PhysicalProperty(**row['reference_runoff_m_year']))
        for row in erosion_laws)
    settling = tuple(tt.SedimentLaw(**dict(row)) for row in sediment_laws)
    if type(deposition_templates) is not dict:
        raise ValueError('explicit material deposition templates required')
    for law in settling:
        if law.material_id not in deposition_templates:
            raise ValueError('missing deposition template: ' + law.material_id)
        if _q(deposition_templates[law.material_id]['theta_s'], 'deposition porosity') != law.deposited_porosity:
            raise ValueError('deposition template and sediment porosity differ')
    flow = tt.route_water(state, releases, edges, duration_years=duration/calendar)
    terrain = successor_terrain.trial(state, releases, edges, laws, settling,
        duration_years=duration/calendar, controls=tt.TrialControls(**controls), evidence_id=evidence)
    carried = {}
    for event in terrain.erosion_events:
        key, native_index = event['source_cell'], event['source_layer_index']
        index = len(stocks[key])-1-native_index
        if cells[key]['soil']['ice_water'][index] != 0:
            raise ValueError('unsupported frozen-sediment law: nonzero eroded ice in ' + key)
        row = stocks[key][index]
        multiplier = event['eroded_mass_kg']/event['source_initial_mass_kg']*_q(cells[key]['area_m2'], 'area')
        carried[key, native_index] = {
            'water': _q(row['water_m'], 'eroded water')*multiplier,
            'energy': _q(row['enthalpy_j_m2'], 'eroded enthalpy', signed=True)*multiplier,
            'capacity': _q(row['dry_heat_capacity_j_m2_k'], 'eroded dry capacity')*multiplier,
            'head': row['head_guess_m']}
    targets = {}
    for key, column in terrain.erosion_state.columns:
        area = _q(cells[key]['area_m2'], 'area')
        rows = []
        for native_index, physical in enumerate(column.layers):
            original = state.column_map[key].layers[native_index]
            source = stocks[key][len(stocks[key])-1-native_index]
            multiplier = physical.mass_kg/original.mass_kg*area
            rows.append(_target(source, physical, area,
                _q(source['water_m'], 'retained water')*multiplier,
                _q(source['enthalpy_j_m2'], 'retained enthalpy', signed=True)*multiplier,
                _q(source['dry_heat_capacity_j_m2_k'], 'retained dry capacity')*multiplier,
                source['head_guess_m']))
        targets[key] = rows  # Retained native bottom-to-top until every deposit is appended.
    deposit_records = []
    for event in terrain.deposit_events:
        key, physical = event['destination_cell'], event['layer']
        area = _q(cells[key]['area_m2'], 'area')
        water = energy = capacity = guess = F()
        for source in event['sources']:
            packet = carried[source['source_cell'], source['source_layer_index']]
            fraction = source['fraction_of_eroded_mass']
            water += packet['water']*fraction
            energy += packet['energy']*fraction
            capacity += packet['capacity']*fraction
            guess += F(packet['head'])*source['mass_kg']/event['mass_kg']
        identity = hashlib.sha256(json.dumps(_plain([str(elapsed), str(duration), key,
            event['material_id'], event['destination_layer_index'], event['sources']]),
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        template = {'layer': deposition_templates[event['material_id']], 'material': {}}
        saturated = water/area == F(float(physical.bulk_volume_m3/area))*physical.porosity
        # At exactly saturated packing the stock does not determine pressure.
        # Zero is an admissible NUMERICAL seed, not clipped/certified pressure.
        seed = max(0., float(guess)) if saturated else float(guess)
        targets[key].append(_target(template, physical, area, water, energy, capacity,
                                   seed, layer_id='transport-'+identity))
        deposit_records.append({'cell_id': key, 'layer_id': 'transport-'+identity,
                                'water_m3': water, 'enthalpy_j': energy, 'dry_heat_capacity_j_k': capacity,
                                'head_guess_m': seed, 'pressure_certified': False,
                                'head_guess_meaning': 'NONLINEAR_INITIAL_GUESS: max(0, source-mass-weighted head) at saturated packing; otherwise source-mass-weighted head. Subsequent R13 flow solve required.'})
    exported_water = exported_energy = exported_capacity = F()
    wet_exports = []
    for event in terrain.exports:
        packet = carried[event['source_cell'], event['source_layer_index']]
        fraction = event['fraction_of_eroded_mass']
        water, energy, capacity = (packet[k]*fraction for k in ('water', 'energy', 'capacity'))
        exported_water += water; exported_energy += energy; exported_capacity += capacity
        wet_exports.append(dict(event, water_m3=water, enthalpy_j=energy, dry_heat_capacity_j_k=capacity))
    # Transit heat follows the same actual downhill water route, without a
    # second release or exchange with recipient soil/sediment.
    through_heat, heat_exports = dict(release_heat), {}
    for key in flow['order']:
        if key not in flow['selected']:
            continue
        receiver = flow['receivers'][key]
        if receiver is None:
            heat_exports[flow['selected'][key][1].connector_id] = through_heat[key]
        else:
            through_heat[receiver] += through_heat[key]
    runoff_water = sum(releases.values(), F())
    runoff_energy = sum(heat_exports.values(), F())
    if runoff_energy != sum(release_heat.values(), F()):
        raise ArithmeticError('exact routed transit enthalpy failed')
    wanted_water = wanted_energy = wanted_capacity = F()
    for key, rows in targets.items():
        area = _q(cells[key]['area_m2'], 'area')
        wanted_water += retained_water[key]+area*sum((F(r['water_m']) for r in rows), F())
        wanted_energy += retained_heat[key]+area*sum((F(r['enthalpy_j_m2']) for r in rows), F())
        wanted_capacity += area*sum((F(r['dry_heat_capacity_j_m2_k']) for r in rows), F())
    if (initial_water != wanted_water+runoff_water+exported_water
            or initial_energy != wanted_energy+runoff_energy+exported_energy
            or initial_capacity != wanted_capacity+exported_capacity):
        raise ArithmeticError('exact material-carried water/enthalpy/capacity split failed')
    output, actual_stocks, remapping = deepcopy(cells), {}, {}
    actual_water = actual_energy = F()
    for key, rows in targets.items():
        if not rows:
            raise ValueError('exhausted hydraulic column needs an explicit exterior-bedrock model')
        if terrain.state.column_map[key].layers == state.column_map[key].layers:
            rebuilt = {k: deepcopy(cells[key][k]) for k in ('model', 'soil', 'materials')}
            rebuilt['ledger'] = {'status': 'UNCHANGED_GEOMETRY_IDENTITY'}
        else:
            rebuilt = remap.rebuild(cells[key]['model'], list(reversed(rows)), soil_controls,
                                    elapsed_seconds=cells[key]['soil']['elapsed_seconds'])
        output[key].update({k: rebuilt[k] for k in ('model', 'soil', 'materials')})
        output[key]['surface_water_m3'], output[key]['surface_enthalpy_j'] = str(retained_water[key]), str(retained_heat[key])
        remapping[key] = rebuilt['ledger']
        actual_stocks[key] = remap.layer_stocks(rebuilt['model'], rebuilt['soil'], rebuilt['materials'])
        area = _q(cells[key]['area_m2'], 'area')
        actual_water += retained_water[key]+area*sum((F(r['water_m']) for r in actual_stocks[key]), F())
        actual_energy += retained_heat[key]+area*sum((F(r['enthalpy_j_m2']) for r in actual_stocks[key]), F())
    water_residual = initial_water-actual_water-runoff_water-exported_water
    energy_residual = initial_energy-actual_energy-runoff_energy-exported_energy
    total_area = sum((_q(c['area_m2'], 'area') for c in cells.values()), F())
    if (abs(water_residual) > F(soil_controls['water_atol_m'])*total_area
            or abs(energy_residual) > F(soil_controls['energy_atol_j_m2'])*total_area):
        raise ValueError('transport remap exceeds declared water/enthalpy conservation tolerance')
    final_reconciliation = []
    final_landscape = _landscape(tt, output, actual_stocks, elapsed/calendar, reconciliation=final_reconciliation)
    # Zero-volume diagnostic refresh, NOT rerouting historical accepted water.
    after = tt.route_water(final_landscape, {k: F() for k in cells}, edges, duration_years=duration/calendar)
    provenance.verify_backend()
    ledger = {'schema': 'diadem.seasonal-ground-transport.r14', 'evidence': evidence,
        'duration_s': duration, 'soil_clock_advanced': False,
        'initial_water_m3': initial_water, 'final_water_m3': actual_water,
        'runoff_export_m3': runoff_water, 'sediment_water_export_m3': exported_water,
        'water_residual_m3': water_residual, 'initial_enthalpy_j': initial_energy,
        'final_enthalpy_j': actual_energy, 'runoff_export_enthalpy_j': runoff_energy,
        'sediment_enthalpy_export_j': exported_energy, 'enthalpy_residual_j': energy_residual,
        'initial_dry_heat_capacity_j_k': initial_capacity, 'target_final_dry_heat_capacity_j_k': wanted_capacity,
        'exported_dry_heat_capacity_j_k': exported_capacity,
        'exact_target_water_residual_m3': '0', 'exact_target_enthalpy_residual_j': '0',
        'exact_dry_heat_capacity_residual_j_k': '0', 'terrain': terrain.receipt,
        'erosion_local_mass_representation_error_bound_kg': terrain.receipt['actual_R14_erosion_receipt']['local_mass_representation_error_bound_kg'],
        'material_export_kg': {r['material_id']: r['exported_mass_kg'] for r in terrain.receipt['material_balances']},
        'wet_exports': wet_exports, 'deposits': deposit_records, 'remap_residuals': remapping,
        'runoff_enthalpy_by_outlet_j': heat_exports,
        'scope': 'Thawed finite sediment, imposed dilute steady settling; lagged transit runoff/heat without reinfiltration. Remapped saturated pressure is an unvalidated numerical seed until subsequent R13 flow. No ice transport, pond hydraulics or empirical calibration.'}
    return {'cells': output, 'ledger': _plain(ledger), 'routes_before': _routes(flow, initial_reconciliation),
            'routes_after': _routes(after, final_reconciliation)}
