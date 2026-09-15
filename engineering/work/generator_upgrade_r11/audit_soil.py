"""Independent saved material/water continuation audit; never advances a solver.

This checks the bounded reference's held mineral/retention law and actual
organic dry-origin change. It does not certify empirical chemistry, frozen
Richards, deformation energy, or a recomputed climatic/material history.
"""
from fractions import Fraction as F
import math
from . import snapshot, soil_feedback


def require(condition, message):
    if not condition:
        raise ValueError(message)


def quantity(value):
    require(type(value) in (int, float, str, F), 'finite non-boolean quantity required')
    answer = F(value)
    require(max(answer.numerator.bit_length(), answer.denominator.bit_length()) <= 8192,
            'bounded represented quantity required')
    return answer


def close(actual, expected, *scales):
    """Roundoff only, not a relaxed physical or integration tolerance."""
    actual, expected = quantity(actual), quantity(expected)
    scale = max([abs(float(actual)), abs(float(expected)), 1e-300, *[abs(float(x)) for x in scales]])
    require(abs(actual-expected) <= F(64*math.ulp(scale)), 'native represented roundoff differs')


def _native(bundle):
    return bundle.parent.parent.parent.parent.parent.solver


def _organic(ecosystem):
    inputs = ecosystem['inputs']; first = inputs['initial_state']; previous = first
    cf = quantity(inputs['organic_law']['carbon_fraction_dry_matter'])
    require(0 < cf <= 1, 'explicit organic dry carbon fraction required')
    def stock(state):
        organic = state['organic_state']; total = F()
        for key in ('fast_carbon_kg_m2', 'slow_carbon_kg_m2'):
            pair = organic[key]
            require(type(pair) is list and len(pair) == 2 and all(type(x) is int for x in pair)
                    and pair[1] > 0, 'native organic stock codec differs')
            value = quantity(F(*pair)); require(value >= 0, 'negative organic stock'); total += value
        return total
    rows, sources = ecosystem['events'], inputs['events']; elapsed = F(); delta = F()
    require(len(rows) == len(sources) == ecosystem['completed_events'] and bool(rows),
            'complete actual organic event inventory required')
    layer = first['organic_state']['layer_id']; support = first['organic_state']['support_id']
    for row, source in zip(rows, sources):
        dt = quantity(source['organic_forcing']['duration_seconds'])
        require(dt > 0 and row['status'] == 'MODELLED' and row['event_id'] == source['event_id']
                and row['layer_id'] == layer and row['support_id'] == support
                and row['initial_state'] == previous and quantity(row['start_seconds_in_year']) == elapsed
                and quantity(row['duration_seconds']) == dt, 'actual organic source/clock/endpoints differ')
        end = row['end_state']; o0, o1 = stock(previous), stock(end)
        require(end['organic_state']['layer_id'] == layer and end['organic_state']['support_id'] == support,
                'organic endpoint support changed')
        live0, live1 = quantity(previous['live_carbon_kg_m2']), quantity(end['live_carbon_kg_m2'])
        growth, potential = quantity(row['net_production_kg_c_m2']), quantity(row['potential_net_production_kg_c_m2'])
        litter, harvest = quantity(row['litter_carbon_kg_m2']), quantity(row['harvested_carbon_kg_m2'])
        incoming = dt*sum((quantity(source['organic_forcing'][k]) for k in
            ('fast_litter_carbon_kg_m2_s', 'slow_litter_carbon_kg_m2_s')), F())
        carbon = row['organic_producer']['carbon']; export = quantity(carbon['exported_atmospheric_carbon_kg_m2'])
        require(0 <= growth <= potential and 0 <= litter <= live0 and export >= 0
                and harvest == (live0-litter+growth)*quantity(source['harvest_fraction'])
                and live1 == live0-litter+growth-harvest
                and quantity(carbon['initial_kg_m2']) == o0 and quantity(carbon['input_kg_m2']) == incoming
                and quantity(carbon['final_kg_m2'])+export == o0+incoming
                and o1 == quantity(carbon['final_kg_m2'])+litter,
                'actual organic production/harvest endpoints differ')
        expected = dict(initial=live0+o0, final=live1+o1, net_atmospheric_input=growth,
            external_litter_input=incoming, heterotrophic_export=export, harvest_export=harvest, numerical_residual=F())
        require(set(row['budgets_kg_m2']['C']) == set(expected)
                and all(quantity(row['budgets_kg_m2']['C'][k]) == v for k, v in expected.items())
                and live0+o0+growth+incoming == live1+o1+export+harvest,
                'actual organic carbon account differs')
        change = quantity(row['soil_material_change']['organic_dry_mass_change_kg_m2'])
        require(change == (o1-o0)/cf and quantity(row['soil_material_change']['mineral_mass_change_kg_m2']) == 0,
                'organic/mineral change account differs')
        delta += change; previous = end; elapsed += dt
    require(previous == ecosystem['final_state'] and delta == (stock(previous)-stock(first))/cf,
            'accepted final organic stock differs')
    return layer, stock(first)/cf, stock(previous)/cf


def continuation(bundle, actual_unit, formed, ecosystem, product):
    """Check one actual saved remap plus new accepted unfrozen water interval."""
    sw = _native(bundle); water = actual_unit['hydrology']; remap = product['rebind']; step = product['actual_water_step']
    scenario = '/'.join(actual_unit[k] for k in ('snow_id', 'hydraulic_hypothesis_id', 'cell_id'))
    require(product['schema'] == 'diadem.actual-soil-structure-continuation.r11'
            and product['status'] == 'MODELLED_STRUCTURE_AND_WATER_CONTINUATION'
            and product['source_binding_sha256'] == bundle.source_sha256 and product['scenario_id'] == scenario,
            'actual continuation source/scenario/status differs')
    require(product['actual_r10_unit_sha256'] == snapshot.sha(actual_unit)
            and product['formed_cell_sha256'] == snapshot.sha(formed) == actual_unit['formed_soil_sha256']
            and product['ecosystem_result_sha256'] == snapshot.sha(ecosystem), 'actual source product hash join differs')
    require(water['status'] == 'MODELLED_SEASONAL_HYDRAULICS' and water['completed_months'] == 12
            and water['inputs_sha256'] == snapshot.sha(water['inputs'])
            and actual_unit['carbon']['water_product_sha256'] == snapshot.sha(water), 'actual retained water join differs')
    require(ecosystem['status'] == 'MODELLED_SEASONAL_ECOSYSTEM'
            and ecosystem['inputs_sha256'] == snapshot.sha(ecosystem['inputs'])
            and ecosystem['source_binding_sha256'] == bundle.source_sha256 and ecosystem['scenario_id'] == scenario
            and ecosystem['geometry_sha256'] == snapshot.sha(formed['geometry'])
            and all(ecosystem['inputs'][k] == ecosystem[k] for k in ('source_binding_sha256', 'scenario_id', 'geometry_sha256')),
            'actual ecosystem geometry/source/scenario join differs')
    selected, old_organic, new_organic = _organic(ecosystem)
    inputs = remap['inputs']; old = soil_feedback.native_column(sw, water['column'])
    old_state = soil_feedback.native_state(sw, old, water['final_state'])
    new = soil_feedback.native_column(sw, remap['new_column'])
    initial = soil_feedback.native_state(sw, new, remap['new_state'])
    require(remap['schema'] == 'diadem.conservative-soil-water-rebind.r11'
            and remap['status'] == 'MODELLED_ONE_TO_ONE_WATER_REBIND'
            and remap['source_binding_sha256'] == inputs['source_binding_sha256'] == bundle.source_sha256
            and remap['inputs_sha256'] == snapshot.sha(inputs)
            and inputs['ecosystem_result_sha256'] == snapshot.sha(ecosystem)
            and inputs['old_column'] == water['column'] and inputs['old_state'] == water['final_state'],
            'actual rebind input/end-state join differs')
    require(remap['old_column_sha256'] == water['column_sha256'] == sw.column_digest(old)
            and remap['new_column_sha256'] == sw.column_digest(new)
            and new.column_id == old.column_id and new.root_boundary_index == old.root_boundary_index,
            'native old/new column support binding differs')
    ids = [x.layer_id for x in old.layers]
    require([x.layer_id for x in new.layers] == ids == [x['layer_id'] for x in formed['geometry']]
            == [x['layer_id'] for x in remap['layer_ledgers']]
            and set(inputs['material_layers']) == set(ids) == set(inputs['ice_water_m_by_layer']),
            'exact one-to-one material/geometry inventory differs')
    require(all(quantity(x) == 0 for x in inputs['ice_water_m_by_layer'].values()), 'frozen rebind is unsupported')
    controls = water['inputs']['controls']; tolerance = quantity(controls['total_mass_atol_m'])
    geometry_tolerance = quantity(inputs['geometry_atol_m'])
    require(quantity(inputs['water_atol_m']) == tolerance and 0 < geometry_tolerance <= F(1e-9),
            'declared reference remap tolerances differ')
    minerals = {x['layer_id']: x for x in formed['formation_state']['layers']}
    residuals = []; old_stocks = []; new_stocks = []; changed = 0; organic_densities = set()
    for index, (before, after, geometry, ledger) in enumerate(zip(old.layers, new.layers, formed['geometry'], remap['layer_ledgers'])):
        key = before.layer_id; material = inputs['material_layers'][key]
        require(float(quantity(geometry['thickness_m'])) == before.thickness_m
                and float(quantity(geometry['porosity'])) == before.theta_s, 'actual formed/native geometry differs')
        mm, om = quantity(geometry['mineral_mass_kg_m2']), quantity(geometry['organic_dry_mass_kg_m2'])
        require(mm >= 0 and om >= 0 and quantity(geometry['total_dry_mass_kg_m2']) == mm+om,
                'formed constituent dry mass account differs')
        expected = {}
        if mm:
            require(quantity(minerals[key]['mineral_mass_kg_m2']) == mm, 'actual mineral stock differs')
            expected[key+'/mineral'] = ('MINERAL', mm, mm, quantity(minerals[key]['grain_density_kg_m3']))
        if om or key == selected:
            require(key != selected or om == old_organic, 'initial selected organic stock differs from formed support')
            expected[key+'/organic'] = ('ORGANIC', om, new_organic if key == selected else om, None)
        constituents = material['constituents']
        require(len(constituents) == len(expected) and {c['constituent_id'] for c in constituents} == set(expected),
                'finite actual constituent inventory differs')
        v0 = F(); v1 = F(); changes = []
        for c in constituents:
            kind, m0, m1, density = expected[c['constituent_id']]; rho = quantity(c['grain_density_kg_m3'])
            require(rho > 0 and c['kind'] == kind and quantity(c['old_mass_kg_m2']) == m0
                    and quantity(c['new_mass_kg_m2']) == m1 and (density is None or density == rho),
                    'actual mineral/organic mass or grain density differs')
            if kind == 'ORGANIC': organic_densities.add(rho)
            v0 += m0/rho; v1 += m1/rho
            changes.append({'constituent_id': c['constituent_id'], 'dry_mass_change_kg_m2': str(m1-m0)})
        require(ledger['constituent_changes'] == changes, 'saved constituent change ledger differs')
        p = quantity(material['new_porosity']); require(0 < p < 1, 'finite material porosity required')
        depth = v1/(1-p)
        require(p == F(before.theta_s) == F(after.theta_s) and abs(v0/(1-p)-F(before.thickness_m)) <= geometry_tolerance
                and abs(F(after.thickness_m)-depth) <= geometry_tolerance and after.thickness_m == float(depth),
                'represented constituent-volume geometry differs')
        for field in ('theta_r', 'alpha_per_m', 'n', 'mualem_l', 'ksat_m_s', 'evidence', 'source_status'):
            require(getattr(after, field) == getattr(before, field) == material['hydraulic_law'][field],
                    'held explicit native retention/conductivity law changed')
        w0 = F(sw.hydraulic_properties(before, old_state.head_m[index])[0])*F(before.thickness_m)
        w1 = F(sw.hydraulic_properties(after, initial.head_m[index])[0])*F(after.thickness_m); residual = w1-w0
        require(quantity(ledger['old_water_m']) == w0 and quantity(ledger['new_water_m']) == w1
                and quantity(ledger['representation_residual_m']) == residual and abs(residual) <= tolerance
                and quantity(ledger['old_thickness_m']) == F(before.thickness_m)
                and quantity(ledger['new_thickness_m_exact']) == depth
                and quantity(ledger['new_thickness_m_represented']) == F(after.thickness_m)
                and ledger['new_head_m'] == initial.head_m[index], 'actual extensive water/remap account differs')
        target = w0/F(after.thickness_m)
        if initial.head_m[index] >= 0:
            require(after == before and v0 == v1 and initial.head_m[index] == old_state.head_m[index]
                    and target == F(after.theta_s)
                    and ledger['head_status'] == 'UNCHANGED_SATURATED_SUPPORT_PRIOR_HEAD_NUMERICAL_INITIAL_CONDITION_ONLY',
                    'changed saturated support cannot borrow pressure')
        else:
            require(F(after.theta_r) < target < F(after.theta_s)
                    and initial.head_m[index] == sw.head_from_theta(after, float(target))
                    and ledger['head_status'] == 'UNIQUE_UNSATURATED_STOCK_INVERSE', 'actual unique stock inverse differs')
        residuals.append(residual); old_stocks.append(w0); new_stocks.append(w1); changed += v0 != v1
    require(len(organic_densities) <= 1 and sum(residuals, F()) == quantity(remap['total_water_representation_residual_m'])
            and abs(sum(residuals, F())) <= tolerance, 'whole-profile remap account differs')
    clock = F(old_state.elapsed_seconds)
    require(F(initial.elapsed_seconds) == clock == quantity(remap['elapsed_seconds_before']) == quantity(remap['elapsed_seconds_after'])
            and quantity(remap['external_water_input_m']) == quantity(remap['external_water_output_m']) == 0
            and remap['forcing_events_consumed'] == [] and remap['next_actual_water_step_required'] is True
            and remap['current_pressure_status'] == 'UNVERIFIED_UNTIL_NEXT_ACTUAL_WATER_STEP'
            and remap['frozen_richards_implemented'] is False, 'remap invented forcing/time/current pressure')
    dt = quantity(product['duration_seconds']); require(dt > 0 and F(float(dt)) == dt, 'exact positive new interval required')
    require(step['schema'] == 'diadem.layered-richards.r6' and step['status'] == 'MODELLED'
            and step['numerical_implementation'] == 'R10_SATURATION_BRANCH_RESOLUTION'
            and step['model'] == '1D_MIXED_RICHARDS_VG_MUALEM_'+controls['integration_method']+'_STEP_DOUBLING'
            and step['column_sha256'] == sw.column_digest(new)
            and step['numerics']['controls'] == controls and step['physical_acceptance'] is False
            and step['lower_boundary']['kind'] == actual_unit['initial_condition']['boundary']['kind'] == 'no_flow'
            and step['lower_boundary']['head_m'] is None, 'actual new geometry solver/support/controls differ')
    forcing = step['forcing']; fluid = step['fluid']
    require(quantity(forcing['duration_seconds']) == dt and quantity(forcing['surface_input_m_s']) == 0
            and quantity(forcing['potential_et_m_s']) == 0 and forcing['uptake'] is None
            and fluid == {k: water['inputs'][k] for k in ('water_density_kg_m3', 'gravity_m_s2')},
            'declared new forcing or physical fluid changed')
    adapter = bundle.parent.graph.load('work.generator_upgrade_r10.richards_numerics').Adapter(sw)
    require(step['numerical_binding'] == adapter.numerical_binding(), 'actual retained numerical source binding differs')
    final = soil_feedback.native_state(sw, new, step['state'])
    require(F(final.elapsed_seconds) == clock+dt, 'new accepted solver clock differs')
    elapsed = F(); details = step['numerics']['accepted_steps_detail']
    require(type(step['numerics']['accepted_steps']) is int and step['numerics']['accepted_steps'] == len(details) > 0,
            'actual accepted step inventory differs')
    for row in details:
        d = quantity(row['dt_seconds_exact'])
        require(type(row['dt_seconds']) is float and d == F(row['dt_seconds']) and d > 0
                and 0 <= quantity(row['error_ratio']) <= 1, 'accepted solver duration/error differs')
        elapsed += d
        require(elapsed <= dt and quantity(row['end_seconds_exact']) == elapsed and row['end_seconds'] == float(elapsed),
                'exact internal continuation clock differs')
    require(elapsed == dt == quantity(step['numerics']['elapsed_seconds_exact'])
            == quantity(step['numerics']['forcing_duration_seconds_exact']), 'exact new forcing coverage differs')
    rows = step['layers']; ledger = step['ledger']; n = len(ids)
    require([x['layer_id'] for x in rows] == ids and len(ledger['face_downward_m']) == len(ledger['face_upward_m']) == n+1,
            'actual final layer/face inventory differs')
    down = [quantity(x) for x in ledger['face_downward_m']]; up = [quantity(x) for x in ledger['face_upward_m']]
    require(min(down+up) >= 0 and down[0] == down[-1] == up[-1] == 0, 'closed zero-input face flux differs')
    final_stocks = []; depth = 0.; ets = []
    for i, (layer, row, head) in enumerate(zip(new.layers, rows, final.head_m)):
        theta = sw.hydraulic_properties(layer, head)[0]; close(row['theta_m3_m3'], theta)
        require(row['head_m'] == head and row['top_depth_m'] == depth and row['centre_depth_m'] == depth+layer.thickness_m/2
                and row['bottom_depth_m'] == depth+layer.thickness_m, 'actual pressure/geometric support differs')
        represented = quantity(row['theta_m3_m3'])*F(layer.thickness_m)
        require(quantity(row['water_m3_m2_exact_represented']) == represented
                and row['water_m3_m2'] == float(represented), 'final extensive water representation differs')
        close(row['effective_saturation'], (row['theta_m3_m3']-layer.theta_r)/(layer.theta_s-layer.theta_r))
        close(row['pore_saturation'], row['theta_m3_m3']/layer.theta_s)
        pressure = fluid['water_density_kg_m3']*fluid['gravity_m_s2']*head
        require(row['signed_pore_pressure_pa'] == pressure and row['positive_pore_pressure_pa'] == max(0., pressure),
                'solver-produced pressure conversion differs')
        et = quantity(row['et_m']); require(et == 0, 'zero-demand continuation cannot transpire')
        residual = represented-new_stocks[i]-down[i]+up[i]+down[i+1]-up[i+1]+et
        require(abs(residual) <= tolerance, 'independent layer water balance exceeds original tolerance')
        close(row['water_residual_m'], residual, represented, new_stocks[i], *down, *up)
        final_stocks.append(represented); ets.append(et); depth += layer.thickness_m
    close(ledger['initial_storage_m'], sum(new_stocks, F()))
    close(ledger['final_storage_m'], sum(final_stocks, F()))
    require(all(quantity(ledger[k]) == 0 for k in ('surface_input_m', 'infiltration_m', 'rain_excess_runoff_m',
                'actual_et_m', 'potential_et_m', 'bottom_downward_m', 'bottom_upward_m'))
            and quantity(ledger['surface_exfiltration_m']) == quantity(ledger['surface_runoff_m']) == up[0]
            and quantity(ledger['root_zone_gross_downward_m']) == down[new.root_boundary_index]
            and quantity(ledger['root_zone_upward_capillary_m']) == up[new.root_boundary_index], 'actual gross flux/uptake account differs')
    balance = sum(new_stocks, F())-sum(final_stocks, F())-up[0]
    require(abs(balance) <= tolerance, 'independent total continuation water balance exceeds original tolerance')
    close(ledger['water_residual_m'], balance, *new_stocks, *final_stocks, *up)
    require(product['pressure_status'] == 'ACTUAL_NEW_GEOMETRY_SOLVER_PRODUCED'
            and product['thermal_regime'] == 'EXPLICIT_UNFROZEN_ISOTHERMAL_CONTINUATION_NOT_COUPLED_TO_HELD_WATER_THERMAL_DIAGNOSTIC'
            and all(product[k] is False for k in ('new_forcing_forecast', 'full_history_recomputed', 'frozen_richards_implemented')),
            'unsupported current-pressure/thermal/history claim')
    return {'layers': n, 'changed_organic_supports': changed, 'accepted_water_steps': len(details),
        'old_water_m': str(sum(old_stocks, F())), 'rebound_water_m': str(sum(new_stocks, F())),
        'water_remap_representation_residual_m': str(sum(residuals, F())),
        'independent_new_water_residual_m': str(balance), 'duration_seconds': str(dt),
        'new_elapsed_seconds': str(clock+dt), 'numerical_source_binding': step['numerical_binding'],
        'audit_scope': 'ACTUAL_MATERIAL_GEOMETRY_WATER_AND_PRESSURE_JOINS; NO_SOLVER_RERUN_OR_FROZEN_HISTORY_CLAIM'}


def thermal_reference(spec, product):
    """Audit fixed-initial-water heat receipts, not time-varying/frozen Richards.

    Reconstructs the supplied enthalpy/phase equation at every saved sample and
    checks exact booked net-boundary energy. It does not rerun conduction or
    reconstruct unsaved intermediate pair/boundary heat exchanges.
    """
    require(product['schema'] == 'diadem.held-soil-thermal-year.r11'
            and product['status'] == 'MODELLED_HOLD_INITIAL_WATER_DIAGNOSTIC', 'complete held-water thermal diagnostic required')
    source = product['source_binding_sha256']; snapshot.digest(source)
    require(product['inputs'] == {'spec': spec, 'source_binding_sha256': source, 'scenario_id': product['scenario_id']}
            and product['inputs_sha256'] == snapshot.sha(product['inputs']), 'thermal source/specification binding differs')
    require(product['water_support'] == 'HOLD_INITIAL_WATER_DIAGNOSTIC'
            and product['ecosystem_moisture_pairing'] == 'NOT_VALIDATED_WITH_TIME_VARYING_R10_WATER'
            and product['frozen_richards_implemented'] is False and product['geometry_feedback_applied'] is False,
            'held-water diagnostic promoted to coupled thermal/Richards')
    cells = spec['cells']; stocks = spec['initial_cells']; ids = set(cells)
    require(bool(ids) and ids == set(stocks), 'held thermal initial support inventory differs')
    initial_clock = quantity(spec['initial_elapsed_seconds']); clock = F(); count = 0; phase_samples = 0
    previous = {'schema': 'diadem.held-water-thermal-state.r11', 'cells_sha256': snapshot.sha(cells),
        'source_binding_sha256': source, 'elapsed_seconds': str(initial_clock), 'cells': stocks, 'consumed_event_ids': []}
    rows = product['events']; require(len(rows) == len(spec['events']) == product['completed_events'] > 0,
        'complete thermal event inventory differs')
    total_boundary = F()
    for row, event in zip(rows, spec['events']):
        dt = quantity(event['duration_seconds']); result = row['thermal_result']
        require(dt > 0 and row['status'] == result['status'] == 'MODELLED'
                and result['schema'] == 'diadem.held-water-thermal-result.r11'
                and row['event_id'] == event['event_id'] == result['event_id']
                and row['month_id'] == event['month_id'] and quantity(row['start_seconds_in_year']) == clock
                and quantity(event['start_seconds_in_year']) == clock and quantity(row['duration_seconds']) == dt
                and quantity(result['duration_seconds_exact']) == dt
                and row['actual_water_event_sha256'] == event['actual_water_event_sha256'], 'thermal event/source calendar differs')
        identity = {'cells': cells, 'initial': previous, 'links': spec['links'], 'boundaries': event['boundaries'],
            'event_id': event['event_id'], 'duration_seconds': event['duration_seconds'], **spec['controls']}
        require(result['source_binding_sha256'] == source and result['inputs_sha256'] == snapshot.sha(identity)
                and result['initial_state'] == previous, 'thermal accepted prefix/input binding differs')
        require(result['water_mass_changed'] is False and result['geometry_feedback'] == 'NOT_APPLIED'
                and result['hydraulic_feedback'] == 'NOT_FROZEN_RICHARDS', 'unsupported thermal mass/geometry feedback')
        elapsed = F(); last = None
        for step in result['accepted_steps']:
            d = quantity(step['duration_seconds_exact']); require(0 < d <= quantity(spec['controls']['max_dt_seconds']), 'invalid held-thermal step')
            elapsed += d
            require(elapsed <= dt and quantity(step['elapsed_seconds_exact']) == elapsed and set(step['end_layers']) == ids,
                    'thermal internal clock/layer support differs')
            for key, sample in step['end_layers'].items():
                cell = cells[key]; mass = quantity(stocks[key]['water_mass_kg']); energy = quantity(sample['energy_j'])
                cd, cw, ci, latent, tf = (quantity(cell[k]) for k in ('solid_heat_capacity_j_k',
                    'liquid_heat_capacity_j_kg_k', 'ice_heat_capacity_j_kg_k', 'latent_heat_j_kg', 'freezing_temperature_k'))
                require(min(cd, cw, ci, latent, tf) > 0 and mass >= 0, 'positive explicit thermal laws required')
                if energy < 0: temperature, liquid = tf+energy/(cd+mass*ci), F()
                elif energy > mass*latent: temperature, liquid = tf+(energy-mass*latent)/(cd+mass*cw), mass
                else: temperature, liquid = tf, energy/latent
                require(sample['cell_id'] == cell['cell_id'] == key and temperature > 0
                        and quantity(sample['water_mass_kg']) == mass and quantity(sample['liquid_water_kg']) == liquid
                        and quantity(sample['ice_water_kg']) == mass-liquid and quantity(sample['temperature_k_exact']) == temperature
                        and sample['temperature_k'] == float(temperature)
                        and sample['liquid_fraction'] == (float(liquid/mass) if mass else 0.)
                        and sample['phase_law'] == 'SUPPLIED_ISOTHERMAL_FREE_WATER_PHASE_CHANGE'
                        and sample['sample'] == 'INSTANTANEOUS_CELL_STATE', 'independent held-soil enthalpy/phase equation differs')
                phase_samples += 1
            last = step['end_layers']; count += 1
        require(last is not None and elapsed == dt, 'complete thermal interval coverage required')
        following = dict(previous, elapsed_seconds=str(initial_clock+clock+dt),
            cells={k: {f: last[k][f] for f in ('water_mass_kg', 'energy_j')} for k in ids},
            consumed_event_ids=previous['consumed_event_ids']+[event['event_id']])
        require(result['final_state'] == following and result['water_mass_kg'] == {k: stocks[k]['water_mass_kg'] for k in ids},
                'thermal final state differs from held mass/accepted phase')
        initial_energy = sum((quantity(s['energy_j']) for s in previous['cells'].values()), F())
        final_energy = sum((quantity(s['energy_j']) for s in following['cells'].values()), F())
        ledger = result['energy_ledger_j']; boundary = quantity(ledger['boundary_input'])
        require(quantity(ledger['initial']) == initial_energy and quantity(ledger['final']) == final_energy
                and initial_energy+boundary == final_energy and quantity(ledger['residual']) == 0,
                'independent held-soil energy/endpoint account differs')
        total_boundary += boundary; clock += dt; previous = following
    require(product['final_state'] == previous, 'whole thermal final state differs')
    cp = product['checkpoint']; state = {'completed_events': len(rows), 'continuing_state': previous, 'accepted_events': rows}
    require(cp['schema'] == 'diadem.held-soil-thermal-checkpoint.r11' and cp['source_binding_sha256'] == source
            and cp['inputs_sha256'] == product['inputs_sha256'] and cp['state'] == state
            and cp['state_sha256'] == snapshot.sha(state), 'thermal checkpoint saved prefix differs')
    return {'events': len(rows), 'layers': len(ids), 'accepted_heat_steps': count, 'phase_samples': phase_samples,
        'elapsed_seconds': str(clock), 'booked_boundary_energy_j': str(total_boundary), 'water_mass_changed': False,
        'audit_scope': 'EXACT_HELD_MASS_ENERGY_CLOCK_AND_PHASE; NOT_CONDUCTION_RERUN_OR_FROZEN_RICHARDS'}
