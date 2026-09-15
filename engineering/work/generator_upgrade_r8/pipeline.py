"""Actual formed soil -> declared seasonal climate/water -> potential vegetation."""
from fractions import Fraction as F
import math
from . import binding, seasonal, vegetation, biomes

FIELDS = ('schema', 'source_status', 'source_sha256', 'evidence', 'soil_recipe', 'seasonal',
          'pfts', 'families', 'family_demand_multipliers', 'cell_context', 'classification_controls',
          'edges', 'actual_vegetation_overlays', 'limits')


def constraints(spec):
    raw = seasonal.fields(spec, ('pft_id', 'base_temperature_c', 'dry_stress_fraction', 'limits',
                                'external_requirements', 'evidence', 'source_status'), 'PFT constraints')
    return vegetation.PFTConstraints(**{**raw, 'limits': tuple(vegetation.Limit(**v) for v in raw['limits']),
                                       'external_requirements': tuple(raw['external_requirements'])})


def parse(bundle, recipe):
    recipe = bundle.storage.decoded(bundle.storage.encoded(recipe))
    seasonal.fields(recipe, FIELDS, 'R8 recipe')
    if recipe['schema'] != binding.RECIPE_SCHEMA or recipe['source_sha256'] != bundle.source_sha256 or recipe['source_status'] != 'WORKING NON-CANON':
        raise ValueError('this exact source-bound R8 candidate recipe required')
    seasonal.evidence(recipe['evidence']); seasonal.evidence(recipe['limits'])
    seasonal.configuration(recipe['seasonal'])
    if type(recipe['pfts']) is not dict or not 1 <= len(recipe['pfts']) <= 64:
        raise ValueError('bounded explicit PFT inventory required')
    for ident, row in recipe['pfts'].items():
        seasonal.fields(row, ('guild', 'evidence', 'rooting', 'active_above_temperature_c',
                              'reference_transpiration_fraction', 'constraints', 'chemical_regime'), 'PFT definition')
        seasonal.evidence(ident); seasonal.evidence(row['evidence'])
        if row['guild'] not in biomes.GUILDS or constraints(row['constraints']).pft_id != ident:
            raise ValueError('PFT/guild identity differs')
        seasonal.number(row['active_above_temperature_c'], 'phenology threshold', signed=True, maximum=100)
        seasonal.number(row['reference_transpiration_fraction'], 'demand hypothesis', positive=True, maximum=10)
    if type(recipe['families']) is not list or len(recipe['families']) != 3:
        raise ValueError('three explicit coequal classifier families required')
    family_ids = {row['family_id'] for row in recipe['families']}
    if len(family_ids) != 3 or type(recipe['family_demand_multipliers']) is not dict or set(recipe['family_demand_multipliers']) != family_ids:
        raise ValueError('family and counterfactual demand bindings differ')
    for value in recipe['family_demand_multipliers'].values():
        seasonal.number(value, 'family demand multiplier', positive=True, maximum=10)
    ids = {row['cell_id'] for row in recipe['seasonal']['transect']}
    if type(recipe['cell_context']) is not dict or set(recipe['cell_context']) != ids:
        raise ValueError('complete independent cell domain/context required')
    for row in recipe['cell_context'].values():
        seasonal.fields(row, ('domain', 'external_gates'), 'cell context')
        if type(row['external_gates']) is not dict or 'chemical_regime' in row['external_gates']:
            raise ValueError('chemical gate must be computed from actual soil chemistry')
    if type(recipe['edges']) is not list or len(recipe['edges']) > 1000:
        raise ValueError('bounded explicit adjacency required')
    pairs = set()
    for edge in recipe['edges']:
        seasonal.fields(edge, ('a', 'b', 'length_m', 'evidence'), 'adjacency')
        seasonal.evidence(edge['a']); seasonal.evidence(edge['b']); seasonal.evidence(edge['evidence'])
        seasonal.number(edge['length_m'], 'adjacency length', positive=True)
        pair = tuple(sorted((edge['a'], edge['b'])))
        if edge['a'] not in ids or edge['b'] not in ids or edge['a'] == edge['b'] or pair in pairs:
            raise ValueError('unknown, self or duplicate adjacency')
        pairs.add(pair)
    if type(recipe['actual_vegetation_overlays']) is not list or len(recipe['actual_vegetation_overlays']) > 1000:
        raise ValueError('bounded separate actual-vegetation overlays required')
    overlay_ids = set()
    for overlay in recipe['actual_vegetation_overlays']:
        seasonal.fields(overlay, ('overlay_id', 'cell_ids', 'label', 'evidence', 'source_status'), 'actual vegetation overlay')
        for field in ('overlay_id', 'label', 'evidence'):
            seasonal.evidence(overlay[field])
        if overlay['overlay_id'] in overlay_ids or type(overlay['cell_ids']) is not list or not overlay['cell_ids'] or any(type(v) is not str for v in overlay['cell_ids']) or len(set(overlay['cell_ids'])) != len(overlay['cell_ids']) or not set(overlay['cell_ids']) <= ids or overlay['source_status'] not in biomes.KNOWN | biomes.UNRESOLVED:
            raise ValueError('invalid separate vegetation overlay')
        overlay_ids.add(overlay['overlay_id'])
    return recipe


def chemical_gate(cell, rule):
    seasonal.fields(rule, ('minimum_ph_water', 'maximum_ph_water', 'maximum_ec_ds_m', 'cec_method', 'evidence'), 'chemical regime')
    seasonal.evidence(rule['evidence']); seasonal.evidence(rule['cec_method'])
    low = seasonal.number(rule['minimum_ph_water'], 'minimum pH', maximum=14)
    high = seasonal.number(rule['maximum_ph_water'], 'maximum pH', maximum=14)
    ec = seasonal.number(rule['maximum_ec_ds_m'], 'conductivity tolerance', maximum=100)
    if low > high:
        raise ValueError('pH bounds reversed')
    fertility = cell['fertility']
    if fertility is None or fertility.get('status') != 'MODELLED_NATURAL_REFERENCE' or fertility.get('exchange') is None:
        return {'status': 'UNKNOWN', 'evidence': 'actual common soil chemical context unavailable; no fertility-index substitute'}
    chemistry = fertility['exchange']['chemistry']
    if chemistry['cec_method'] != rule['cec_method']:
        raise ValueError('chemical assay protocol mismatch')
    passed = low <= chemistry['ph_water'] <= high and chemistry['electrical_conductivity_ds_m'] <= ec
    return {'status': 'PASS' if passed else 'FAIL',
            'evidence': rule['evidence'] + '; actual common-profile chemistry ' + seasonal.digest(chemistry) + '; applicability only, NOT nutrient adequacy'}


def climate_metrics(cycle, cell):
    def record(value, unit, description):
        return {'value': value, 'unit': unit, 'source_status': 'UNKNOWN' if value is None else 'WORKING NON-CANON', 'evidence': description}
    if cycle['status'] != 'MODELLED_PERIODIC_SNOW':
        return {key: record(None, unit, cycle['reason']) for key, unit in
                (('warmest_month_temperature_c', 'degC'), ('coldest_month_temperature_c', 'degC'),
                 ('annual_precipitation_to_reference_pet_ratio', '1'), ('snow_persistence_fraction', '1'))}
    months = cycle['months']; duration = sum((F(v['duration_seconds']) for v in months), F())
    precipitation = sum((F(v['precipitation_m_s']) * F(v['duration_seconds']) for v in months), F())
    pet = sum((F(v['potential_evaporation_m_s']) * F(v['duration_seconds']) for v in months), F())
    snow_duration = F()
    for month in months:
        snow = month['snow']; ledger = snow['ledger']; dt = F(month['duration_seconds'])
        if snow['depletion_after_seconds'] is not None:
            snow_duration += F(snow['depletion_after_seconds'])
        elif F(ledger['initial_swe_m']) > 0 or F(ledger['final_swe_m']) > 0:
            snow_duration += dt
    binding_note = 'actual declared seasonal cycle ' + seasonal.digest(cycle)
    result = {
        'warmest_month_temperature_c': record(max(v['temperature_c'] for v in months), 'degC', binding_note + '; monthly mean, not heat extremes'),
        'coldest_month_temperature_c': record(min(v['temperature_c'] for v in months), 'degC', binding_note + '; monthly mean, not frost extremes'),
        'annual_precipitation_to_reference_pet_ratio': record(float(precipitation / pet) if pet else None, '1', binding_note + '; atmospheric reference demand, NOT PFT actual/potential ratio'),
        'snow_persistence_fraction': record(float(snow_duration / duration), '1', binding_note + '; time with positive representative SWE, NOT snow-covered area fraction'),
        'annual_precipitation_m': record(float(precipitation), 'm', binding_note),
        'annual_reference_pet_m': record(float(pet), 'm', binding_note),
        'mineral_solum_depth_m': record(float(F(cell['horizons']['mineral_pedogenic_solum_depth_m'])) if cell['horizons']['solum_status'] == 'MODELLED' else None, 'm', 'actual R7 operational mineral solum; not rooting depth'),
    }
    return result


def evaluate_cell(bundle, recipe, soil, seasonal_result, member, cell_id):
    cell = soil['state']['members'][member][cell_id]
    cycle = seasonal_result['members'][member]['cells'][cell_id]
    cal = recipe['seasonal']['calendar']; day = F(cal['day_seconds'])
    calendar = vegetation.Calendar(cal['calendar_id'], tuple(F(v) * day for v in cal['month_days']), day, cal['evidence'])
    support_id = seasonal.digest({'soil_cell': cell, 'member': member, 'cell_id': cell_id})
    capacities = {}; pft_results = {}
    for pft_id, spec in sorted(recipe['pfts'].items()):
        capacities[pft_id] = seasonal.rooted_capacity(bundle, cell, spec['rooting'], support_id=support_id)
    for family in sorted(recipe['families'], key=lambda v: v['family_id']):
        family_id = family['family_id']; pft_results[family_id] = {}
        for pft_id, spec in sorted(recipe['pfts'].items()):
            capacity = capacities[pft_id]
            water_capacity = vegetation.WaterCapacity(capacity['capacity_m'], capacity['rooted_depth_m'], support_id,
                capacity['evidence'], 'WORKING NON-CANON' if capacity['status'] == 'MODELLED' else 'UNKNOWN')
            events = []
            if cycle['status'] == 'MODELLED_PERIODIC_SNOW':
                for row in cycle['events']:
                    active = row['temperature_c'] > spec['active_above_temperature_c']
                    demand = row['potential_evaporation_m_s'] * spec['reference_transpiration_fraction'] * recipe['family_demand_multipliers'][family_id] if active else 0.
                    seasonal.number(demand, 'represented PFT demand')
                    if active and row['potential_evaporation_m_s'] > 0 and demand == 0:
                        raise ValueError('positive PFT demand underflowed')
                    events.append(vegetation.Event(row['event_id'], row['month_id'], F(row['duration_seconds']),
                        row['temperature_c'], row['liquid_input_m_s'], demand, active,
                        recipe['evidence'] + '; explicit PFT demand/phenology and actual snow-liquid forcing ' + seasonal.digest(cycle), 'WORKING NON-CANON'))
            else:
                events = [vegetation.Event('unknown-month-' + str(i), i, dt, None, None, None, None,
                          cycle['reason'], 'UNKNOWN') for i, dt in enumerate(calendar.month_durations_seconds, 1)]
            gates = dict(recipe['cell_context'][cell_id]['external_gates'])
            gates['chemical_regime'] = chemical_gate(cell, spec['chemical_regime'])
            result = vegetation.evaluate(water_capacity, calendar, tuple(events), constraints(spec['constraints']), gates)
            result['source_binding'] = {'soil_support_id': support_id, 'capacity_sha256': seasonal.digest(capacity),
                                       'seasonal_cycle_sha256': seasonal.digest(cycle), 'family_id': family_id,
                                       'demand_hypothesis': 'independent counterfactual PFT demand; experiments may NOT be summed as simultaneous water use'}
            pft_results[family_id][pft_id] = result
    metrics = climate_metrics(cycle, cell)
    guilds = {key: {'guild': row['guild'], 'evidence': row['evidence']} for key, row in recipe['pfts'].items()}
    classification = biomes.classify_cell(cell_id, recipe['cell_context'][cell_id]['domain'], recipe['families'],
        pft_results, metrics, guilds, controls=recipe['classification_controls'])
    original = soil['actual_exposure']['members'][member][cell_id]
    return {'cell_id': cell_id, 'area_m2': original['area_m2'], 'soil_support_id': support_id,
            'capacities': capacities, 'pft_results': pft_results, 'climate_metrics': metrics, 'classification': classification,
            'uncalculated': ['realised vegetation cover', 'competition and disturbance resolution', 'nutrient sufficiency and uptake',
                            'wetland hydroperiod', 'geographic species ranges'],
            'source_status': 'WORKING NON-CANON'}


def map_products(members, edges, complete):
    result = {}
    for member, cells in members.items():
        areas = {}; rows = []
        for cell_id, row in sorted(cells.items()):
            classification = row['classification']
            broad = None if classification['broad'] is None else classification['broad']['primary_code']
            form = None if classification['formation'] is None else classification['formation']['primary_code']
            key = 'UNKNOWN' if form is None else str(form)
            areas[key] = areas.get(key, F()) + F(row['area_m2'])
            rows.append({'cell_id': cell_id, 'area_m2': row['area_m2'], 'broad_code': broad, 'formation_code': form,
                         'status': classification['status'], 'uncertainty': classification['uncertainty']})
        eligible_edges = [v for v in edges if v['a'] in cells and v['b'] in cells]
        diagnostics = biomes.transition_diagnostics([row['classification'] for row in cells.values()], eligible_edges) if cells else None
        result[member] = {'cells': rows, 'class_area_m2': {key: str(v) for key, v in sorted(areas.items())},
                          'represented_area_m2': str(sum(areas.values(), F())), 'transitions': diagnostics,
                          'coverage': 'ALL_SUPPLIED_CELLS' if complete else 'PARTIAL_CHECKPOINT',
                          'spatial_support': 'actual source cell IDs/areas and declared adjacency; no invented geographic CRS or ecotone width'}
    return result


def run(bundle, recipe, *, stop_after=None, resume=None):
    recipe = parse(bundle, recipe)
    soil = bundle.parent.run(recipe['soil_recipe'])
    exposure = seasonal.build(bundle, soil, recipe['seasonal'])
    ordered = sorted((member, cell) for member, cells in soil['state']['members'].items() for cell in cells)
    until = len(ordered) if stop_after is None else stop_after
    if type(until) is not int or not 0 <= until <= len(ordered):
        raise ValueError('whole bounded cell-completion cursor required')
    recipe_sha = seasonal.digest(recipe)
    def simulate(count):
        members = {member: {} for member in soil['state']['members']}
        for member, cell_id in ordered[:count]:
            members[member][cell_id] = evaluate_cell(bundle, recipe, soil, exposure, member, cell_id)
        return seasonal.plain({'completed_cells': count, 'soil_result_sha256': seasonal.digest(soil),
                'seasonal_sha256': seasonal.digest(exposure), 'members': members})
    if resume is not None:
        seasonal.fields(resume, ('schema', 'recipe_sha256', 'source_sha256', 'state_sha256', 'state'), 'R8 checkpoint')
        state = resume['state']; seasonal.fields(state, ('completed_cells', 'soil_result_sha256', 'seasonal_sha256', 'members'), 'R8 saved state')
        if resume['schema'] != binding.CHECKPOINT_SCHEMA or resume['source_sha256'] != bundle.source_sha256 or resume['recipe_sha256'] != recipe_sha or resume['state_sha256'] != seasonal.digest(state):
            raise ValueError('checkpoint source/recipe/state binding differs')
        prior = state['completed_cells']
        if type(prior) is not int or not 0 <= prior <= until:
            raise ValueError('checkpoint cursor may not skip/reverse execution')
        if simulate(prior) != state:
            raise ValueError('saved state differs from actual bound soil/seasonal/PFT replay')
    state = simulate(until)
    output = {'schema': binding.RESULT_SCHEMA, 'status': 'BOUNDED_BIOMES_VEGETATION_REFERENCE',
        'source_status': 'WORKING NON-CANON', 'source_sha256': bundle.source_sha256, 'recipe_sha256': recipe_sha,
        'state': state, 'soil_result': soil, 'seasonal': exposure,
        'map_products': map_products(state['members'], recipe['edges'], until == len(ordered)),
        'legend': {'broad': biomes.BROAD_NAMES, 'formation': biomes.FORMATION_NAMES, 'compatibility': biomes.COMPATIBILITY},
        'actual_vegetation_overlays': recipe['actual_vegetation_overlays'],
        'actual_vegetation_used_as_classifier_input': False,
        'production_installed': False, 'canon_changed': False, 'optimisation_performed': False,
        'limits': recipe['limits']}
    return bundle.storage.decoded(bundle.storage.encoded(seasonal.plain(output)))
