"""Actual R10 -> routed water / living soil -> finite human consequences.

Independent physical hypotheses remain separate. Whole-world coverage and soil
geometry/unsaturated frozen-water feedback are not inferred from this reference.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
from . import binding, snapshot

E = 'SYNTHETIC TEST: explicit seasonal engineering consequence; not adopted Diadem biology, terrain or policy.'


def parse(bundle, recipe):
    snapshot.exact(recipe, ('schema', 'source_sha256', 'source_status', 'evidence', 'parent_recipe',
        'parameters', 'reference_laws', 'scope'), 'seasonal-consequence recipe')
    if recipe['schema'] != binding.RECIPE_SCHEMA or recipe['source_sha256'] != bundle.source_sha256 or recipe['source_status'] != 'WORKING NON-CANON':
        raise ValueError('exact source-bound R11 recipe required')
    if recipe['reference_laws'] != 'R11_EXPLICIT_SYNTHETIC_NETWORK_PLANT_AND_HUMAN_CONSEQUENCES':
        raise ValueError('explicit supported reference laws required')
    snapshot.text(recipe['evidence']); snapshot.text(recipe['scope'])
    p = snapshot.exact(recipe['parameters'], ('routing_substeps_per_shortest_month',
        'network_conductance_multiplier', 'plant_absorbed_light_multiplier',
        'monthly_settlement_water_demand_m3', 'edible_fraction_of_test_harvest', 'food_processing_loss_fraction'), 'reference parameters')
    n = p['routing_substeps_per_shortest_month']
    if type(n) is not int or not 1 <= n <= 256:
        raise ValueError('explicit bounded routing resolution required')
    number = bundle.parent.graph.load('work.generator_upgrade_r10.climate').rational
    for key in p:
        if key == 'routing_substeps_per_shortest_month':
            continue
        value = number(p[key])
        if key in ('edible_fraction_of_test_harvest', 'food_processing_loss_fraction') and value > 1:
            raise ValueError('food fractions must not exceed unity')
    return recipe


def parent_units(bundle, recipe, parent):
    if (parent.get('schema') != 'diadem.seasonal-world-result.r10'
            or parent.get('source_sha256') != bundle.parent.source_sha256
            or parent.get('recipe_sha256') != snapshot.sha(recipe['parent_recipe'])
            or parent.get('status') != 'COMPLETE_BOUNDED_SEASONAL_EXECUTION'):
        raise ValueError('complete actual source-bound R10 input required')
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    groups = {}
    for key, packed in parent['state']['results'].items():
        unit = codec.unpack(packed)
        group = unit['snow_id']+'/'+unit['hydraulic_hypothesis_id']
        if key != group+'/'+unit['cell_id']:
            raise ValueError('actual parent scientific unit identity differs')
        if unit['hydrology']['status'] != 'MODELLED_SEASONAL_HYDRAULICS':
            raise ValueError('complete physical parent water required')
        bucket = groups.setdefault(group, {})
        if unit['cell_id'] in bucket:
            raise ValueError('duplicate actual physical support')
        bucket[unit['cell_id']] = unit
    expected = {(snow, h) for snow in parent['climate']['members'] for h in recipe['parent_recipe']['hydraulic_hypotheses']}
    if set(groups) != {a+'/'+b for a, b in expected}:
        raise ValueError('all coequal parent scenarios must remain present')
    expected_cells = set(recipe['parent_recipe']['parent_recipe']['parent_recipe']['cell_context'])
    if any(set(group) != expected_cells for group in groups.values()):
        raise ValueError('complete actual physical support set required')
    return groups


def water_inputs(bundle, recipe, group, climate_member=None):
    water = bundle.module('water')
    events = []; joins = []
    for month in range(1, 13):
        durations = {F(unit['hydrology']['months'][str(month)]['duration_seconds']) for unit in group.values()}
        if len(durations) != 1:
            raise ValueError('routed cells must share exact calendar windows')
        dt = durations.pop(); inputs = {}
        for cell, unit in sorted(group.items()):
            if unit['initial_condition']['boundary']['kind'] != 'no_flow':
                raise ValueError('reference must not ignore a changed physical groundwater boundary')
            m = unit['hydrology']['months'][str(month)]
            local = unit['downstream']['local_water_supply'][str(month)]
            area = F(unit['downstream']['represented_area_m2'])
            volume = F(m['ledger_m']['surface_runoff_m'])*area
            if F(local['local_surface_export_m3']['exact']) != volume:
                raise ValueError('once-only local area conversion differs')
            inputs[cell] = str(volume)
            joins.append({'event_id': 'month-'+str(month), 'cell_id': cell,
                'actual_parent_unit_sha256': snapshot.sha(unit), 'area_m2': str(area),
                'surface_export_m3': str(volume), 'source_month_sha256': snapshot.sha(m),
                'groundwater_recharge_from_internal_drainage_m3': '0',
                'reason': 'Actual R10 lower boundary is no-flow; gross internal drainage is not new groundwater supply.'})
        events.append({'event_id': 'month-'+str(month), 'duration_seconds': str(dt), 'inflows_m3': inputs})
    spec = water.reference_spec(events, {cell: '0' for cell in group})
    spec['controls']['max_dt_seconds'] = str(min(F(x['duration_seconds']) for x in events)/recipe['parameters']['routing_substeps_per_shortest_month'])
    for link in spec['network']['links']:
        link['conductance_m2_s'] = str(F(link['conductance_m2_s'])*F(recipe['parameters']['network_conductance_multiplier']))
    # Changing a declared law requires a freshly initialised source binding, not
    # reuse of the old network fingerprint.
    spec['initial'] = water.initial_state(spec['network'], spec['initial']['nodes'])
    for event in spec['events']:
        event['withdrawals'] = [{'allocation_id': event['event_id']+'/water-sink-'+cell,
            'node_id': 'lake', 'sink_id': 'water-sink-'+cell, 'volume_m3': '4',
            'kind': 'ALLOCATION', 'latent_heat_j_kg': '0', 'evidence': E} for cell in sorted(group)]
        if climate_member is not None:
            mid = int(event['event_id'].split('-')[-1])-1
            weights = {c: F(u['downstream']['represented_area_m2']) for c, u in group.items()}
            temperatures = {c: F(climate_member['cells'][c]['months'][mid]['air']['temperature_c']['exact'])+F(27315, 100) for c in group}
            mean = sum((weights[c]*temperatures[c] for c in group), F())/sum(weights.values(), F())
            for key, boundary in event['heat_boundaries'].items():
                if key == 'groundwater':
                    boundary['temperature_k'] = '280'
                    boundary['evidence'] = 'Explicit synthetic deep-ground heat bath 280 K; not inferred from air or geology.'
                else:
                    boundary['temperature_k'] = str(temperatures.get(key, mean))
                    boundary['evidence'] = 'Actual R10 monthly air under explicit lumped heat-exchange boundary hypothesis; lake/wetland uses area-weighted cell air, not observed water temperature.'
    return spec, joins


def ecosystem_products(bundle, recipe, group_id, group):
    ecosystem = bundle.module('ecosystem'); products = {}; joins = {}
    for cell, unit in sorted(group.items()):
        spec = ecosystem.reference_spec(bundle.organic, bundle.fertility, unit)
        joins[cell] = spec.pop('reference_join')
        multiplier = F(recipe['parameters']['plant_absorbed_light_multiplier'])
        spec['events'] = tuple(replace(e, absorbed_par_j_m2=e.absorbed_par_j_m2*multiplier) for e in spec['events'])
        result = ecosystem.run_year(bundle.organic, bundle.fertility, **spec,
            source_binding_sha256=bundle.source_sha256, scenario_id=group_id+'/'+cell,
            evidence=E, source_status='SYNTHETIC TEST')
        products[cell] = result
    return products, joins


def human_inputs(bundle, recipe, parent, group_id, group, routed, ecosystems):
    human = bundle.module('human'); calendar = []; clock = F()
    for row in routed['events']:
        dt = F(row['duration_seconds'])
        calendar.append({'event_id': row['event_id'], 'start_seconds': str(clock), 'duration_seconds': str(dt), 'evidence_id': E})
        clock += dt
    spec = human.reference_inputs(calendar=calendar, source_binding_sha256=bundle.source_sha256, scenario_id=group_id)
    # The fixture's stable commodity label is only synthetic edible dry biomass.
    # It does not make the retained temperate stand a grain-producing species.
    for item in spec['commodities']:
        item['evidence_id'] = 'SYNTHETIC TEST edible dry-biomass conversion; label is not a biological grain/yield claim.'
    for settlement in spec['settlements']:
        cell = settlement['settlement_id']
        rule = {'metric_id': 'held-wind-'+cell, 'support_id': cell, 'unit': 'm/s',
            'full_service_at': '5', 'zero_service_at': '15', 'whole_window_scenario': True,
            'evidence_id': 'SYNTHETIC TEST service curve for held monthly-mean wind; no gust, storm probability or daily reliability claim.'}
        settlement['exposure_rules'] = [rule]
        spec['network']['capacity_groups'][0]['hazard_rules'].append(deepcopy(rule))
        snow_rule = {'metric_id': 'held-opening-snow-'+cell, 'support_id': cell, 'unit': 'm',
            'full_service_at': '0', 'zero_service_at': '1/4', 'whole_window_scenario': True,
            'evidence_id': 'SYNTHETIC TEST service curve on explicitly held opening snow SWE; not a measured road clearance or month-long snow history.'}
        settlement['exposure_rules'].append(snow_rule)
        spec['network']['capacity_groups'][0]['hazard_rules'].append(deepcopy(snow_rule))
    conversion = {'carbon_fraction_dry_matter': '2/5', 'edible_fraction': recipe['parameters']['edible_fraction_of_test_harvest'],
        'processing_loss_fraction': recipe['parameters']['food_processing_loss_fraction'],
        'mass_basis': 'EDIBLE_DRY_FOOD_KG', 'food_quality_evidence': 'Synthetic conversion oracle only, not evidence of real plant edibility.',
        'evidence_id': E, 'source_status': 'SYNTHETIC TEST'}
    for event, window, wrow in zip(spec['events'], calendar, routed['events']):
        end = F(window['start_seconds'])+F(window['duration_seconds'])
        mid = int(event['event_id'].split('-')[-1])-1
        snow = next(iter(group.values()))['snow_id']
        for cell in group:
            actual = parent['climate']['members'][snow]['cells'][cell]['months'][mid]
            event['hazard_observations']['held-wind-'+cell] = {'event_id': event['event_id'], 'support_id': cell,
                'unit': 'm/s', 'kind': 'WIND_SPEED', 'value': actual['air']['mean_scalar_speed_10m_m_s']['exact'],
                'temporal_support': 'INTERVAL_HELD', 'source_input_sha256': snapshot.sha(actual),
                'evidence_id': 'Actual R10 mean wind, explicitly held for a synthetic monthly service scenario; not an interval maximum.',
                'source_status': 'WORKING NON-CANON'}
            event['hazard_observations']['held-opening-snow-'+cell] = {'event_id': event['event_id'], 'support_id': cell,
                'unit': 'm', 'kind': 'SNOW_WATER_EQUIVALENT', 'value': actual['initial_swe_m']['exact'],
                'temporal_support': 'INTERVAL_HELD', 'source_input_sha256': snapshot.sha(actual),
                'evidence_id': 'Actual R10 opening SWE, explicitly held for this synthetic monthly accessibility scenario; not actual whole-month snow.',
                'source_status': 'WORKING NON-CANON'}
        for demand in event['water_demands']:
            demand['required_m3'] = recipe['parameters']['monthly_settlement_water_demand_m3']
        event['water_deliveries'].extend(human.water_deliveries_from_result(routed,
            event_id=event['event_id'], settlement_by_sink={'water-sink-'+cell: cell for cell in group},
            source_binding_sha256=bundle.source_sha256, scenario_id=group_id))
        for cell, eco in ecosystems.items():
            for erow in eco['events']:
                if F(erow['start_seconds_in_year'])+F(erow['duration_seconds']) != end:
                    continue
                if F(erow['harvested_carbon_kg_m2']) == 0:
                    continue
                harvest = human.harvest_from_ecosystem_result(eco, event_id=erow['event_id'],
                    settlement_id=cell, commodity_id=spec['commodities'][0]['commodity_id'], support_id=erow['support_id'],
                    area_m2=group[cell]['downstream']['represented_area_m2'], conversion=conversion,
                    source_binding_sha256=bundle.source_sha256, geometry_sha256=eco['geometry_sha256'], scenario_id=group_id+'/'+cell)
                event['harvests'].append(harvest)
    return spec


def evaluate_group(bundle, recipe, parent, group_id, group):
    snow = next(iter(group.values()))['snow_id']
    water = bundle.module('water'); spec, water_joins = water_inputs(bundle, recipe, group, parent['climate']['members'][snow])
    routed = water.run(spec['network'], spec['initial'], spec['events'], controls=spec['controls'],
        source_binding_sha256=bundle.source_sha256, scenario_id=group_id)
    ecosystems, ecosystem_joins = ecosystem_products(bundle, recipe, group_id, group)
    if routed['status'] == 'MODELLED' and all(x['status'] == 'MODELLED_SEASONAL_ECOSYSTEM' for x in ecosystems.values()):
        human_spec = human_inputs(bundle, recipe, parent, group_id, group, routed, ecosystems)
        human = bundle.module('human').run_year(bundle.transport, **human_spec)
    else:
        human_spec = None
        human = {'status': 'UNKNOWN', 'reason': 'physical or biological predecessor unresolved; no zero substitute'}
    return {'scenario_id': group_id, 'parent_unit_sha256': {c: snapshot.sha(u) for c, u in sorted(group.items())},
        'water': routed, 'ecosystems': ecosystems, 'human': human, 'human_inputs': human_spec,
        'water_joins': water_joins, 'ecosystem_joins': ecosystem_joins,
        'status': 'MODELLED' if routed['status'] == 'MODELLED' and human['status'] == 'COMPLETE' and all(x['status'] == 'MODELLED_SEASONAL_ECOSYSTEM' for x in ecosystems.values()) else 'INCOMPLETE',
        'actual_biology_calibrated': False, 'physical_soil_geometry_feedback': 'INCOMPLETE',
        'fixed_snapshot_not_history': True}


def run_from_parent(bundle, recipe, parent, *, stop_after=None, resume=None):
    parse(bundle, recipe); groups = parent_units(bundle, recipe, parent)
    keys = sorted(groups); count = len(keys) if stop_after is None else stop_after
    if type(count) is not int or not 0 <= count <= len(keys):
        raise ValueError('bounded complete scenario cursor required')
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    parent_sha = snapshot.sha(parent); recipe_sha = snapshot.sha(recipe)
    def simulate(until):
        return {'completed_scenarios': until, 'parent_result_sha256': parent_sha,
            'results': {key: codec.pack(evaluate_group(bundle, recipe, parent, key, groups[key])) for key in keys[:until]}}
    if resume is not None:
        snapshot.exact(resume, ('schema', 'recipe_sha256', 'source_sha256', 'state_sha256', 'state'), 'R11 checkpoint')
        if (resume['schema'] != binding.CHECKPOINT_SCHEMA or resume['recipe_sha256'] != recipe_sha
                or resume['source_sha256'] != bundle.source_sha256 or resume['state_sha256'] != bundle.module('consequences').state_digest(resume['state'], codec)):
            raise ValueError('R11 checkpoint identity differs')
        cursor = resume['state'].get('completed_scenarios')
        if type(cursor) is not int or not 0 <= cursor <= count or resume['state'] != simulate(cursor):
            raise ValueError('R11 checkpoint differs from actual semantic replay')
    state = simulate(count)
    all_modelled = all(codec.unpack(v)['status'] == 'MODELLED' for v in state['results'].values())
    biology = bundle.module('biology').build_overlay(bundle.module('owner_inputs').species(bundle))
    geo = bundle.module('owner_inputs').geography(bundle)
    return {'schema': binding.RESULT_SCHEMA, 'source_sha256': bundle.source_sha256, 'source_status': 'WORKING NON-CANON',
        'recipe_sha256': recipe_sha, 'parent_result_sha256': parent_sha, 'state': state,
        'status': 'STOPPED_AT_SCENARIO_BOUNDARY' if count < len(keys) else 'COMPLETE_BOUNDED_CONSEQUENCES' if all_modelled else 'INCOMPLETE',
        'parent_retained_separately': True, 'hypotheses_are_coequal_not_additive': True,
        'biological_owner_inputs': codec.pack(biology),
        'biological_input_status': 'OWNER_FACTS_AND_SCOPED_DECISIONS_INTEGRATED; NO_NEW_SELECTED_NUMERICAL_COEFFICIENTS',
        'geo_input_contract': {'sha256': snapshot.sha(geo), 'source_bindings': geo['source_bindings'],
            'unresolved': geo['effective_unresolved'], 'original_unresolved': geo['contract']['unresolved'],
            'world_input_completeness': geo['contract']['world_input_completeness'],
            'requested_owner_returns_complete': geo['requested_owner_returns_complete'], 'effective_interpretation': geo['effective_interpretation']},
        'remaining_physical_feedback': ['general frozen unsaturated soil hydraulics', 'conservative changing soil geometry/water rebind'],
        'whole_generator_complete': False, 'production_installed': False, 'canon_changed': False, 'optimisation_performed': False,
        'limits': recipe['scope']}


def run(bundle, recipe, *, stop_after=None, resume=None):
    parse(bundle, recipe)
    parent = bundle.parent.run(recipe['parent_recipe'])
    return run_from_parent(bundle, recipe, parent, stop_after=stop_after, resume=resume)
