"""Declared representative year on actual formed terrain; no invented history."""
from dataclasses import asdict, is_dataclass
from fractions import Fraction as F
import hashlib
import json
import math

MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def plain(value):
    if isinstance(value, F):
        return str(value)
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, dict):
        converted = {}
        for key, item in value.items():
            if type(key) not in (str, int):
                raise ValueError('only explicit string or integer class-code keys supported')
            key = str(key)
            if key in converted:
                raise ValueError('class-code key collision during JSON conversion')
            converted[key] = plain(item)
        return converted
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def fields(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(name + ': exact fields required')
    return value


def number(value, name, *, positive=False, signed=False, maximum=1e12):
    if type(value) not in (int, float, F):
        raise ValueError(name + ': finite explicit number required')
    if abs(value) > maximum or (not signed and value < 0) or (positive and value <= 0):
        raise ValueError(name + ': outside physical range')
    if not math.isfinite(value):
        raise ValueError(name + ': finite explicit number required')
    if value and float(value) == 0:
        raise ValueError(name + ': positive magnitude cannot underflow')
    return float(value)


def evidence(value):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError('bounded explicit evidence required')
    return value


def configuration(config):
    fields(config, ('calendar', 'transect', 'months', 'phase', 'phase_controls',
                    'demand_constants', 'snow_max_cycles', 'snow_atol_m',
                    'temperature_distribution_evidence', 'evidence'), 'seasonal hypothesis')
    evidence(config['evidence']); evidence(config['temperature_distribution_evidence'])
    calendar = fields(config['calendar'], ('calendar_id', 'month_days', 'day_seconds', 'evidence'), 'calendar')
    if calendar['calendar_id'] != 'JAN_DEC_365_FEB28' or type(calendar['month_days']) is not list or calendar['month_days'] != list(MONTH_DAYS) or any(type(v) is not int for v in calendar['month_days']):
        raise ValueError('explicit Jan-Dec 365-day month order required')
    number(calendar['day_seconds'], 'day unit', positive=True, maximum=1e7); evidence(calendar['evidence'])
    if type(config['months']) is not list or len(config['months']) != 12:
        raise ValueError('complete twelve-month hypothesis required')
    if type(config['snow_max_cycles']) is not int or not 1 <= config['snow_max_cycles'] <= 100:
        raise ValueError('bounded snow-cycle budget required')
    number(config['snow_atol_m'], 'snow periodic tolerance', positive=True, maximum=0.001)
    transect = config['transect']
    if type(transect) is not list or not 1 <= len(transect) <= 32:
        raise ValueError('bounded actual transect required')
    for row in transect:
        fields(row, ('cell_id', 'length_m', 'width_m', 'evidence'), 'transect cell')
        evidence(row['cell_id']); evidence(row['evidence'])
        number(row['length_m'], 'length', positive=True); number(row['width_m'], 'width', positive=True)
    ids = {row['cell_id'] for row in transect}
    if len(ids) != len(transect):
        raise ValueError('unique physical cells required')
    for month, row in enumerate(config['months'], 1):
        fields(row, ('month_id', 'regimes', 'evidence'), 'month')
        if type(row['month_id']) is not int or row['month_id'] != month:
            raise ValueError('months may not repeat or be omitted')
        evidence(row['evidence'])
        if row['regimes'] is None:
            continue  # Explicitly unknown month, never a zero-precipitation month.
        if type(row['regimes']) is not list or not 1 <= len(row['regimes']) <= 8:
            raise ValueError('bounded explicit monthly circulation mixture required')
        weights = F(); names = set()
        for regime in row['regimes']:
            fields(regime, ('regime_id', 'weight', 'atmosphere', 'climate_controls', 'surfaces', 'evidence'), 'regime')
            evidence(regime['regime_id']); evidence(regime['evidence'])
            if regime['regime_id'] in names:
                raise ValueError('duplicate regime identity')
            names.add(regime['regime_id'])
            number(regime['weight'], 'circulation fraction', positive=True, maximum=1)
            weights += F(regime['weight'])
            if type(regime['surfaces']) is not dict or set(regime['surfaces']) != ids:
                raise ValueError('every actual cell needs explicit demand surface')
        if weights != 1:
            raise ValueError('represented monthly mixture weights must sum exactly to one')
    return config


def rooted_capacity(bundle, cell, spec, *, support_id):
    """VG available interval on actual rooting-accessible formed layers.

    Bounds are supplied plant/matric-head hypotheses, not intrinsic FC/PWP.
    Roots cannot be placed in rock or silently equated with the mineral solum.
    """
    fields(spec, ('maximum_root_depth_m', 'upper_head_m', 'lower_head_m', 'allowed_phases', 'evidence'), 'rooting hypothesis')
    evidence(spec['evidence']); evidence(support_id)
    depth = number(spec['maximum_root_depth_m'], 'root depth', positive=True, maximum=100)
    upper = number(spec['upper_head_m'], 'upper retention head', signed=True, maximum=1e6)
    lower = number(spec['lower_head_m'], 'lower retention head', signed=True, maximum=1e6)
    if not lower < upper < 0:
        raise ValueError('ordered unsaturated matric-head endpoints required')
    phases = spec['allowed_phases']
    if type(phases) is not list or not phases or len(set(phases)) != len(phases) or not set(phases) <= {'organic_mantle', 'mobile_sediment', 'immobile_regolith'}:
        raise ValueError('explicit nonrock accessible phases required')
    water = cell['formed_soil_water']
    if water['status'] != 'MODELLED_NEW_GEOMETRY_WATER_PROBE':
        return {'status': 'UNKNOWN', 'capacity_m': None, 'rooted_depth_m': None, 'support_id': support_id,
                'evidence': spec['evidence'], 'reason': 'new geometry lacks bound hydraulic material properties'}
    geometry = cell['geometry']
    if water['geometry_sha256'] != digest(geometry):
        raise ValueError('stale formed-water geometry')
    laws = water['column']['layers']
    if [v['layer_id'] for v in laws] != [v['layer_id'] for v in geometry]:
        raise ValueError('hydraulic and geometric layer identities differ')
    solver = bundle.parent.parent.solver
    remaining = F(depth); total = F(); rooted = F(); rows = []
    for g, law in zip(geometry, laws):
        if not remaining or g['phase'] not in phases:
            break  # Roots cannot tunnel through an excluded layer unnoticed.
        dz = min(remaining, F(g['thickness_m']))
        if float(F(g['thickness_m'])) != law['thickness_m'] or float(F(g['porosity'])) != law['theta_s']:
            raise ValueError('hydraulic dimensions differ from formed material')
        model = solver.HydraulicLayer(**law)
        theta_high = solver.hydraulic_properties(model, upper)[0]
        theta_low = solver.hydraulic_properties(model, lower)[0]
        if not theta_low <= theta_high <= law['theta_s']:
            raise ArithmeticError('retention order violated')
        contribution = (F(theta_high) - F(theta_low)) * dz
        rows.append({'layer_id': g['layer_id'], 'rooted_thickness_m': str(dz),
                     'theta_upper': theta_high, 'theta_lower': theta_low, 'available_water_m': str(contribution)})
        total += contribution; rooted += dz; remaining -= dz
    return {'status': 'MODELLED', 'capacity_m': number(total, 'rooted available capacity'), 'capacity_exact_m': str(total),
            'rooted_depth_m': number(rooted, 'accessible root depth'), 'rooted_depth_exact_m': str(rooted), 'layers': rows,
            'geometry_sha256': digest(geometry), 'hydraulic_material_sha256': digest(water['column']),
            'support_id': support_id, 'evidence': spec['evidence'], 'rooting_hypothesis': spec,
            'scope': 'available water between supplied heads; not total porewater, field capacity observation or groundwater state'}


def snow_cycle(hm, scenario, monthly, config, cell_id, binding_sha):
    """Periodic seasonal snow from both finite bounding starts, never growing ice."""
    day = F(config['calendar']['day_seconds'])
    annual_snow = sum((F(v['snowfall_m_s']) * F(v['duration_seconds']) for v in monthly), F())
    annual_capacity = sum((F(scenario.degree_day_factor_mm_c_day) * F(hm.positive_temperature(v['temperature_c'], scenario.temperature_sigma_c)) / 1000 / day * F(v['duration_seconds']) for v in monthly), F())
    if annual_capacity <= annual_snow:
        return {'status': 'UNKNOWN', 'reason': 'no unique finite periodic SWE: annual accumulation or neutral ice stock',
                'annual_snowfall_m': str(annual_snow), 'annual_melt_capacity_m': str(annual_capacity), 'events': None}
    def advance(start):
        state = hm.initial_snow(cell_id, scenario, start, binding_sha256=binding_sha, elapsed_seconds=0, evidence=config['evidence'])
        rows = []
        for month in monthly:
            result = hm.snow_step(state, scenario, temperature_c=month['temperature_c'],
                precipitation_m_s=F(month['precipitation_m_s']), snowfall_m_s=F(month['snowfall_m_s']),
                start_seconds=state.elapsed_seconds, duration_seconds=F(month['duration_seconds']), day_seconds=day,
                interval_id='month-' + str(month['month_id']), input_sha256=digest(month), binding_sha256=binding_sha,
                evidence=config['evidence'], source_status='WORKING NON-CANON',
                temperature_distribution_evidence=config['temperature_distribution_evidence'])
            state = result['state']; rows.append(result)
        return state.swe_m, rows
    lower, upper = F(), annual_snow
    for iteration in range(1, config['snow_max_cycles'] + 1):
        low_end, low_rows = advance(lower); high_end, high_rows = advance(upper)
        tolerance = config['snow_atol_m']
        errors = [abs(float(low_end - lower)), abs(float(high_end - upper)), abs(float(high_end - low_end))]
        errors += [abs(float(a['ledger']['liquid_to_soil_m'] - b['ledger']['liquid_to_soil_m'])) for a, b in zip(low_rows, high_rows)]
        if max(errors) <= tolerance:
            events = []; months = []
            for month, result in zip(monthly, low_rows):
                ledger = result['ledger']; duration = F(month['duration_seconds'])
                depletion = result['depletion_after_seconds']
                if depletion is not None:
                    first_rate = F(month['precipitation_m_s']) - F(month['snowfall_m_s']) + ledger['potential_melt_m'] / duration
                    parts = ((depletion, first_rate), (duration - depletion, F(month['precipitation_m_s'])))
                else:
                    parts = ((duration, ledger['liquid_to_soil_m'] / duration),)
                if sum((dt * rate for dt, rate in parts), F()) != ledger['liquid_to_soil_m']:
                    raise ArithmeticError('melt timing ledger mismatch')
                for index, (dt, rate) in enumerate(parts):
                    represented_rate = number(rate, 'represented snow-liquid rate')
                    events.append({'event_id': 'month-' + str(month['month_id']) + '-part-' + str(index),
                                   'month_id': month['month_id'], 'duration_seconds': str(dt),
                                   'temperature_c': month['temperature_c'], 'liquid_input_m_s': represented_rate,
                                   'liquid_conversion_error_m': str((F(represented_rate) - rate) * dt),
                                   'potential_evaporation_m_s': month['potential_evaporation_m_s']})
                months.append({**month, 'snow': plain(result)})
            residual = sum((v['ledger']['precipitation_m'] - v['ledger']['liquid_to_soil_m'] for v in low_rows), F()) + lower - low_end
            if residual:
                raise ArithmeticError('annual snow water ledger')
            return {'status': 'MODELLED_PERIODIC_SNOW', 'iterations': iteration,
                    'initial_swe_m': str(lower), 'final_swe_m': str(low_end),
                    'periodic_error_m': max(errors), 'annual_water_residual_m': str(residual),
                    'annual_snowfall_m': str(annual_snow), 'annual_melt_capacity_m': str(annual_capacity),
                    'events': events, 'months': months, 'scenario': plain(scenario),
                    'scope': 'periodic prescribed monthly forcing and Gaussian melt; not resolved snow cover, snow duration or glacier geometry'}
        lower, upper = low_end, high_end
    return {'status': 'UNKNOWN', 'reason': 'snow cycle brackets did not converge', 'events': None}


def build(bundle, soil_result, config):
    config = configuration(config); parent = bundle.parent.parent
    cm = parent.pipeline.climate; hm = parent.pipeline.hm
    if soil_result['source_sha256'] != bundle.parent.source_sha256 or soil_result['state']['completed_exposures'] < 1:
        raise ValueError('actual completed source-bound formed soil required')
    phase = hm.PhaseLaw(**config['phase']); constants = hm.DemandConstants(**config['demand_constants'])
    scenarios = {s.scenario_id: s for s in hm.snow_scenarios()}
    if set(soil_result['state']['members']) != set(scenarios):
        raise ValueError('complete unchanged coequal snow scenarios required')
    identity = digest({'soil_result_sha256': digest(soil_result), 'configuration': config})
    output = {}
    for member, cells in soil_result['state']['members'].items():
        if set(cells) != {v['cell_id'] for v in config['transect']}:
            raise ValueError('seasonal and actual formed-soil cells differ')
        terrain = []
        for row in config['transect']:
            cell = cells[row['cell_id']]
            original = soil_result['actual_exposure']['members'][member][row['cell_id']]
            if F(row['length_m']) * F(row['width_m']) != F(original['area_m2']):
                raise ValueError('seasonal transect and actual horizontal area differ')
            height = F(cell['formation_state']['base_elevation_m']) + sum((F(g['thickness_m']) for g in cell['geometry']), F())
            terrain.append(cm.Cell(**row, elevation_m=float(height)))
        monthly = {cell: [] for cell in cells}; atmosphere_records = []
        if any(row['regimes'] is None for row in config['months']):
            output[member] = {'formed_terrain': [plain(v) for v in terrain], 'atmosphere': [],
                'cells': {cell: {'status': 'UNKNOWN', 'reason': 'explicitly unknown representative month; no fabricated annual forcing',
                                 'events': None, 'months': None} for cell in cells}}
            continue
        for month in config['months']:
            duration = F(MONTH_DAYS[month['month_id'] - 1]) * F(config['calendar']['day_seconds'])
            regimes = []
            for regime in month['regimes']:
                air_mass = cm.AirMass(**regime['atmosphere'])
                if air_mass.water_density_kg_m3 != constants.water_density_kg_m3 or air_mass.epsilon != constants.molecular_mass_ratio:
                    raise ValueError('atmosphere and demand fluid constants differ')
                generated = cm.generate(tuple(terrain), air_mass, cm.Controls(**regime['climate_controls']))
                products = {}
                for cell_id, air in generated['cells'].items():
                    demand = hm.penman_monteith(air, hm.DemandSurface(**regime['surfaces'][cell_id]), constants,
                        evidence=regime['evidence'], source_status='WORKING NON-CANON')
                    wet_bulb = None
                    if phase.temperature_basis == 'SUPPLIED_WET_BULB':
                        wet = hm.psychrometric_wet_bulb(air['temperature_c'], air['vapour_pressure_pa'], demand['psychrometric_constant_pa_k'],
                                                      saturation_liquid=cm.saturation_liquid, **config['phase_controls'])
                        if wet['status'] != 'MODELLED':
                            raise ValueError('seasonal phase outside declared regime: ' + wet['status'])
                        wet_bulb = wet['wet_bulb_c']
                    elif config['phase_controls'] is not None:
                        raise ValueError('unused wet-bulb controls are not an implicit phase model')
                    partition = hm.partition_precipitation(air['precipitation_m_s'], air['temperature_c'], phase,
                        wet_bulb_c=wet_bulb, evidence=regime['evidence'], source_status='WORKING NON-CANON')
                    products[cell_id] = {'air': air, 'demand': demand, 'phase': plain(partition)}
                regimes.append({'regime_id': regime['regime_id'], 'weight': regime['weight'], 'generated': generated, 'products': products})
            atmosphere_records.append({'month_id': month['month_id'], 'regimes': regimes})
            for cell_id in cells:
                def weighted(section, field):
                    return sum((F(r['weight']) * F(r['products'][cell_id][section][field]) for r in regimes), F())
                monthly[cell_id].append({'month_id': month['month_id'], 'duration_seconds': str(duration),
                    'temperature_c': float(weighted('air', 'temperature_c')),
                    'precipitation_m_s': str(weighted('air', 'precipitation_m_s')),
                    'snowfall_m_s': str(weighted('phase', 'snowfall_m_s')),
                    'potential_evaporation_m_s': float(weighted('demand', 'potential_evaporation_m_s')),
                    'potential_condensation_m_s': float(weighted('demand', 'potential_condensation_m_s')),
                    'evidence': month['evidence']})
        output[member] = {'formed_terrain': [plain(v) for v in terrain], 'atmosphere': atmosphere_records,
                          'cells': {cell: snow_cycle(hm, scenarios[member], months, config, cell, identity) for cell, months in monthly.items()}}
    return {'schema': 'diadem.seasonal-vegetation-forcing.r8', 'status': 'DECLARED_REPRESENTATIVE_YEAR',
            'source_status': 'WORKING NON-CANON', 'soil_result_sha256': digest(soil_result),
            'configuration_sha256': digest(config), 'binding_sha256': identity, 'calendar': config['calendar'],
            'members': output, 'scope': 'new explicit 12-month scenario on actual formed elevations; not annualisation of the 240-second parent, adopted climate or a unique history'}
