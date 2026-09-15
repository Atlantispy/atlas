"""Independent saved-product accounts, chronology and source joins (no solver)."""
from fractions import Fraction as F
from dataclasses import replace
from . import snapshot


def require(condition, message):
    if not condition:
        raise ValueError(message)


def balanced(row, incoming, outgoing, residual):
    require(sum((F(row[k]) for k in incoming), F()) ==
            sum((F(row[k]) for k in outgoing), F())+F(row[residual]), 'independent material/energy balance differs')


def water(product):
    require(product['status'] == 'MODELLED' and product['completed_events'] == len(product['events']) == 12,
            'complete twelve-window routed water required')
    require(snapshot.sha(product['inputs']) == product['inputs_sha256'], 'water input digest differs')
    nodes = product['inputs']['network']['nodes']; initial = product['inputs']['initial']
    require(len(product['inputs']['events']) == 12, 'water input event inventory differs')
    require(set(initial['nodes']) == set(nodes), 'water initial supports differ')
    previous = None; clock = F(initial['elapsed_seconds']); ice = steps = 0
    for event, source in zip(product['events'], product['inputs']['events']):
        dt = F(source['duration_seconds'])
        require(event['event_id'] == source['event_id'] and F(event['start_seconds']) == clock
                and F(event['duration_seconds']) == dt and F(event['end_seconds']) == clock+dt, 'water chronology differs')
        require(set(event['nodes']) == set(nodes), 'water supports omitted')
        for key, row in event['nodes'].items():
            b = row['ledger']
            for label, sample in (('initial', 'start'), ('final', 'end')):
                require(F(b[label+'_water_kg']) == F(row[sample]['water_mass_kg'])
                        and F(b[label+'_energy_j']) == F(row[sample]['energy_j']), 'water balance ledger endpoint differs from actual stock')
            if previous is None:
                require(all(F(row['start'][k]) == F(initial['nodes'][key][k]) for k in ('water_mass_kg','energy_j')),
                        'water initial input stock differs')
            require(F(b['external_in_kg']) == sum((F(r['volume_m3'])*F(nodes[key]['liquid_density_kg_m3'])
                for r in source['inflows'] if r['node_id'] == key), F()), 'water external input ledger differs from supplied forcing')
            balanced(b, ('initial_water_kg', 'external_in_kg', 'internal_in_kg'),
                ('final_water_kg', 'external_out_kg', 'internal_out_kg'), 'water_residual_kg')
            balanced(b, ('initial_energy_j', 'external_advected_in_j', 'internal_advected_in_j', 'boundary_heat_j', 'internal_heat_j'),
                ('final_energy_j', 'external_advected_out_j', 'internal_advected_out_j', 'latent_export_j'), 'energy_residual_j')
            require(F(b['water_residual_kg']) == F(b['energy_residual_j']) == 0, 'water/heat ledger residual not zero')
            if previous is not None:
                require(row['start'] == previous[key]['end'], 'water store reset between windows')
            for sample in (row['start'], row['end']):
                require(F(sample['water_mass_kg']) == F(sample['liquid_water_kg'])+F(sample['ice_water_kg']), 'phase masses differ')
                require(min(F(sample['liquid_water_kg']), F(sample['ice_water_kg'])) >= 0, 'negative phase stock')
                node = nodes[key]; liquid = F(sample['liquid_water_kg'])/F(node['liquid_density_kg_m3'])
                ice_volume = F(sample['ice_water_kg'])/F(node['ice_density_kg_m3'])
                law = node['thermal']; mass = F(sample['water_mass_kg']); energy = F(sample['energy_j'])
                cd, cw, ci, latent, tf = (F(law[k]) for k in ('solid_heat_capacity_j_k','liquid_heat_capacity_j_kg_k',
                    'ice_heat_capacity_j_kg_k','latent_heat_j_kg','freezing_temperature_k'))
                if energy < 0:
                    temperature, mobile = tf+energy/(cd+mass*ci), F()
                elif energy > mass*latent:
                    temperature, mobile = tf+(energy-mass*latent)/(cd+mass*cw), mass
                else:
                    temperature, mobile = tf, energy/latent
                require(F(sample['liquid_water_kg']) == mobile and F(sample['ice_water_kg']) == mass-mobile
                        and F(sample['temperature_k_exact']) == temperature and temperature > 0,
                        'independent water enthalpy/phase equation differs')
                require(F(sample['occupied_volume_m3']) == liquid+ice_volume
                        and liquid+ice_volume <= F(node['capacity_m3'])
                        and F(sample['stage_m']) == F(node['datum_m'])+F(sample['water_mass_kg'])/(F(node['liquid_density_kg_m3'])*F(node['storage_area_m2'])),
                        'occupied volume or water-equivalent hydraulic head differs')
            ice += F(row['end']['ice_water_kg']) > 0
        for a, b in (('internal_in_kg', 'internal_out_kg'), ('internal_advected_in_j', 'internal_advected_out_j')):
            require(sum((F(r['ledger'][a]) for r in event['nodes'].values()), F()) ==
                    sum((F(r['ledger'][b]) for r in event['nodes'].values()), F()), 'internal transfers not equal-opposite')
        require(sum((F(r['ledger']['internal_heat_j']) for r in event['nodes'].values()), F()) == 0, 'internal heat creates energy')
        elapsed = F()
        for step in event['accepted_steps']:
            step_dt = F(step['dt_seconds_exact']); require(step_dt > 0, 'nonpositive routing step')
            elapsed += step_dt; require(F(step['end_seconds_exact']) == elapsed, 'internal routing clock differs')
        require(elapsed == dt, 'routing steps do not cover event')
        delivery_ids = set(); requests = {r['allocation_id']: r for r in source['withdrawals']}
        exports = {k: {'mass': F(), 'advected': F(), 'latent': F()} for k in nodes}
        for delivery in event['deliveries']:
            ident = delivery['allocation_id']; key = delivery['node_id']
            require(ident not in delivery_ids and key in nodes, 'duplicate/unknown water delivery')
            delivery_ids.add(ident)
            require(delivery['source_input_sha256'] == product['inputs_sha256']
                    and delivery['source_binding_sha256'] == product['source_binding_sha256']
                    and delivery['event_id'] == event['event_id'], 'water delivery source identity differs')
            require(F(delivery['available_after_seconds']) == clock+dt, 'delivery available before interval end')
            require(F(delivery['delivered_volume_m3'])+F(delivery['unmet_volume_m3']) == F(delivery['requested_volume_m3']), 'delivered and unmet request differ')
            require(F(delivery['delivered_mass_kg']) == F(delivery['delivered_volume_m3'])*F(nodes[key]['liquid_density_kg_m3']), 'delivered volume/mass differs')
            if delivery['kind'] == 'SPILL':
                require(ident == 'spill/'+event['event_id']+'/'+key and delivery['sink_id'] == nodes[key]['spill_sink_id'], 'spill source identity differs')
            else:
                require(ident in requests and all(delivery[k] == requests[ident][k] for k in ('node_id','kind','sink_id'))
                        and F(delivery['requested_volume_m3']) == F(requests[ident]['volume_m3']), 'actual withdrawal request differs')
            exports[key]['mass'] += F(delivery['delivered_mass_kg'])
            exports[key]['advected'] += F(delivery['advected_energy_j'])
            exports[key]['latent'] += F(delivery['latent_energy_j'])
        require(set(requests) <= delivery_ids, 'withdrawal delivery omitted')
        for key, row in event['nodes'].items():
            require(exports[key] == {'mass': F(row['ledger']['external_out_kg']), 'advected': F(row['ledger']['external_advected_out_j']),
                'latent': F(row['ledger']['latent_export_j'])}, 'water terminal exports differ from node ledger')
        steps += len(event['accepted_steps']); clock += dt; previous = event['nodes']
    require(F(product['final_state']['elapsed_seconds']) == clock, 'water final time differs')
    require(product['final_state']['network_sha256'] == snapshot.sha(product['inputs']['network'])
            and product['final_state']['consumed_event_ids'] == initial['consumed_event_ids']+[e['event_id'] for e in product['inputs']['events']],
            'water final input support/consumed sequence differs')
    require(product['final_state']['nodes'] == {k: {f: row['end'][f] for f in ('water_mass_kg','energy_j')} for k,row in previous.items()},
            'water final state differs from last endpoint')
    return {'windows': 12, 'node_windows': 12*len(nodes), 'accepted_steps': steps, 'ice_bearing_node_endpoints': ice,
        'mass_and_energy_accounts': 'EXACT_REPRESENTED', 'elapsed_seconds': str(clock)}


def ecosystem(product):
    require(product['status'] == 'MODELLED_SEASONAL_ECOSYSTEM' and product['completed_months'] == 12,
            'complete seasonal ecosystem required')
    require(snapshot.sha(product['inputs']) == product['inputs_sha256'], 'ecosystem inputs differ')
    previous = product['inputs']['initial_state']; clock = F(); summed = {}
    require(len(product['events']) == len(product['inputs']['events']) == product['completed_events']
            and set(product['annual_budgets_kg_m2']) == {'C','N','P','K'}, 'ecosystem event/element inventory differs')
    def quantity(value):
        return F(*value) if isinstance(value,list) and len(value) == 2 else F(value)
    def totals(state):
        organic = state['organic_state']
        return {'C': F(state['live_carbon_kg_m2'])+quantity(organic['fast_carbon_kg_m2'])+quantity(organic['slow_carbon_kg_m2']),
            **{n: sum((F(dict(state[k])[n]) for k in ('live_nutrients_kg_m2','reserve_nutrients_kg_m2','labile_nutrients_kg_m2')), F()) for n in ('N','P','K')}}
    for event, source in zip(product['events'], product['inputs']['events']):
        dt = F(source['organic_forcing']['duration_seconds'])
        require(F(event['start_seconds_in_year']) == clock and F(event['duration_seconds']) == dt
                and all(event[k] == source[k] for k in ('event_id','month_id','layer_id','support_id','water_state_id','thermal_state_id')), 'ecosystem event chronology/support differs')
        require(event['initial_state'] == previous, 'ecosystem stocks reset between events')
        require(F(event['end_state']['elapsed_seconds']) == F(previous['elapsed_seconds'])+dt, 'ecosystem native state clock differs')
        start_totals = totals(previous); end_totals = totals(event['end_state'])
        require(set(event['budgets_kg_m2']) == {'C','N','P','K'}, 'ecosystem event/element inventory differs')
        for element, row in event['budgets_kg_m2'].items():
            require(F(row['initial']) == start_totals[element] and F(row['final']) == end_totals[element], 'ecosystem balance ledger endpoint differs from actual stock')
            if element == 'C':
                balanced(row, ('initial', 'net_atmospheric_input', 'external_litter_input'),
                    ('final', 'heterotrophic_export', 'harvest_export'), 'numerical_residual')
                require(F(row['numerical_residual']) == 0, 'represented carbon residual is nonzero')
            else:
                balanced(row, ('initial', 'external_input'), ('final', 'water_export', 'harvest_export'), 'numerical_residual')
            require(min(F(row[k]) for k in row if k != 'numerical_residual') >= 0, 'negative physical elemental amount')
            if element not in summed:
                summed[element] = {k: F(v) for k, v in row.items()}
            else:
                require(summed[element]['final'] == F(row['initial']), 'elemental stock continuation differs')
                summed[element]['final'] = F(row['final'])
                for k in row:
                    if k not in ('initial', 'final'):
                        summed[element][k] += F(row[k])
        previous = event['end_state']; clock += F(event['duration_seconds'])
    require(previous == product['final_state'], 'ecosystem final stock differs')
    require(summed == {e: {k: F(v) for k, v in b.items()} for e, b in product['annual_budgets_kg_m2'].items()},
            'annual ecosystem aggregation differs')
    return {'events': len(product['events']), 'months': 12, 'elements': ['C', 'N', 'P', 'K'], 'elapsed_seconds': str(clock)}


def human(product):
    require(product['status'] == 'COMPLETE' and len(product['events']) == 12, 'complete seasonal human reference required')
    inputs = product['source_inputs']
    require(snapshot.sha(inputs) == product['input_sha256'] and len(inputs['events']) == len(inputs['calendar']) == 12,
            'human source input/event inventory differs')
    require(product['fixed_settlements'] == inputs['settlements'] and product['policy'] == inputs['policy'], 'fixed human constraints differ')
    clock = F(); restrictions = 0
    prior_water = {k:F(v) for k,v in inputs['initial_state']['water_m3'].items()}
    prior_food = {(s,c):F(v) for s,row in inputs['initial_state']['food_kg'].items() for c,v in row.items()}
    for event, source, period in zip(product['events'], inputs['events'], inputs['calendar']):
        dt = F(event['duration_seconds'])
        require(event['event_id'] == source['event_id'] == period['event_id'] and snapshot.sha(source) == event['input_sha256']
                and dt == F(period['duration_seconds']) and F(event['start_seconds']) == F(period['start_seconds']) == clock
                and F(event['end_seconds']) == clock+dt, 'human clock or source event differs')
        require({row['settlement_id'] for row in event['water']} == set(prior_water)
                and len(event['water']) == len(prior_water), 'human water support inventory differs')
        require({(row['settlement_id'],row['commodity_id']) for row in event['food']} == set(prior_food)
                and len(event['food']) == len(prior_food), 'human food support inventory differs')
        for row in event['water']:
            balanced(row, ('opening_m3', 'opening_delivery_m3', 'closing_delivery_m3'),
                ('closing_m3', 'loss_m3', 'opening_spill_m3', 'closing_spill_m3', 'consumed_service_m3'), 'residual_m3')
            require(F(row['residual_m3']) == 0, 'settlement water residual differs')
            key = row['settlement_id']
            if key in prior_water:
                require(F(row['opening_m3']) == prior_water[key], 'settlement water annual reset')
            prior_water[key] = F(row['closing_m3'])
        for row in event['food']:
            balanced(row, ('opening_kg', 'opening_harvest_kg', 'closing_harvest_kg'),
                ('closing_kg', 'opening_storage_discard_kg', 'closing_storage_discard_kg', 'storage_loss_kg', 'used_at_source_kg'), 'source_stock_residual_kg')
            require(F(row['source_stock_residual_kg']) == 0, 'food source residual differs')
            key = (row['settlement_id'], row['commodity_id'])
            if key in prior_food:
                require(F(row['opening_kg']) == prior_food[key], 'food stock annual reset')
            prior_food[key] = F(row['closing_kg'])
        for row in event['food_totals']:
            balanced(row, ('opening_kg', 'harvest_kg'), ('closing_kg', 'consumed_service_kg', 'transport_loss_kg', 'storage_loss_and_discard_kg'), 'residual_kg')
            require(F(row['residual_kg']) == 0, 'network food residual differs')
        require(F(event['dispatch_horizon_seconds'])+F(event['conservative_route_travel_bound_seconds']) == dt,
                'feasible dispatch interval differs')
        for response in event['capacity_responses']:
            factor = F(response['service_fraction']); require(0 <= factor <= 1, 'invalid weather capacity fraction')
            require(F(response['base_capacity_kg'])*factor == F(response['capacity_kg']), 'weather capacity accounting differs')
            rep = response['numerical_representation']; exact = F(response['capacity_kg']); represented = F(rep['represented_capacity_kg'])
            require(F(rep['exact_capacity_kg']) == exact and 0 <= represented <= exact
                    and F(rep['reduction_kg']) == exact-represented
                    and F(rep['relative_reduction']) == (F() if exact == 0 else (exact-represented)/exact)
                    and rep['original_capacity_optimum_certified'] is (exact == represented), 'capacity representation accounting differs')
            envelope = exact.numerator.bit_length() <= 256 and exact.denominator.bit_length() <= 128
            if envelope:
                require(rep['method'] == 'EXACT' and represented == exact, 'representable physical capacity was changed')
            elif represented != exact:
                law = rep['declared_law']; quantum = F(law['quantum_kg'])
                require(law['method'] == 'EXACT_OR_DYADIC_INNER' and rep['method'] == 'EXPLICIT_DYADIC_INNER'
                        and represented == (exact//quantum)*quantum and represented > 0
                        and exact-represented <= F(law['max_absolute_loss_kg']), 'declared inner capacity law differs')
            solved = [r for r in event['transport']['capacity_groups'] if r['group_id'] == response['group_id']]
            require(len(solved) == 1 and F(solved[0]['capacity_kg']['exact']) == represented
                    and 0 <= F(solved[0]['used_kg']['exact']) <= represented
                    and F(solved[0]['used_kg']['exact'])+F(solved[0]['unused_kg']['exact']) == represented,
                    'solver capacity differs from represented physical input')
            restrictions += factor < 1
        require(event['transport']['seasonal_capacity_representation']['original_capacity_optimum_certified'] is
                all(r['numerical_representation']['original_capacity_optimum_certified'] for r in event['capacity_responses']),
                'inner-network optimum promoted to original physical optimum')
        for row in event['hazard_exposure']:
            require(row['probability'] is None and row['expected_casualties'] is None, 'exposure promoted to disaster prediction')
        clock += dt
    require(product['state']['water_m3'] == {k:str(v) for k,v in prior_water.items()}
            and {(s,c): F(v) for s,row in product['state']['food_kg'].items() for c,v in row.items()} == prior_food
            and F(product['state']['elapsed_seconds']) == clock, 'human final native stock/clock differs')
    return {'windows': 12, 'restricted_capacity_windows': restrictions, 'elapsed_seconds': str(clock)}


def group(bundle, recipe, parent, group_id, source_units, result):
    require(result['status'] == 'MODELLED' and result['scenario_id'] == group_id, 'complete own scenario required')
    require(result['parent_unit_sha256'] == {c: snapshot.sha(u) for c, u in sorted(source_units.items())}, 'actual source unit join differs')
    require(result['actual_biology_calibrated'] is False and result['fixed_snapshot_not_history'] is True, 'bounded applicability labels lost')
    routed = result['water']; eco = result['ecosystems']; h = result['human']
    for product in (routed, h, *eco.values()):
        require(product['source_binding_sha256'] == bundle.source_sha256, 'dependent source binding differs')
    water_checks = water(routed); eco_checks = {c: ecosystem(v) for c, v in eco.items()}; human_checks = human(h)
    require(set(eco) == set(source_units), 'ecological supports omitted')
    require(all(v['elapsed_seconds'] == water_checks['elapsed_seconds'] for v in eco_checks.values())
            and human_checks['elapsed_seconds'] == water_checks['elapsed_seconds'], 'downstream time support differs')
    producer = bundle.module('pipeline')
    spec, joins = producer.water_inputs(bundle, recipe, source_units, parent['climate']['members'][group_id.split('/')[0]])
    require(result['water_joins'] == joins and routed['inputs']['events'] == spec['events']
            and routed['inputs']['network'] == spec['network'] and routed['inputs']['initial'] == spec['initial']
            and routed['inputs']['controls'] == spec['controls'] and routed['scenario_id'] == group_id,
            'actual physical monthly water source join differs')
    ecosystem_module = bundle.module('ecosystem')
    for cell, unit in source_units.items():
        expected = ecosystem_module.reference_spec(bundle.organic, bundle.fertility, unit)
        join = expected.pop('reference_join')
        expected['initial_state'] = ecosystem_module.state_to_record(bundle.organic, expected['initial_state'])
        expected['events'] = tuple(replace(e, absorbed_par_j_m2=e.absorbed_par_j_m2*F(recipe['parameters']['plant_absorbed_light_multiplier'])) for e in expected['events'])
        expected.update(source_binding_sha256=bundle.source_sha256, scenario_id=group_id+'/'+cell,
            evidence=producer.E, source_status='SYNTHETIC TEST')
        require(ecosystem_module.plain(expected) == eco[cell]['inputs'] and result['ecosystem_joins'][cell] == join,
                'actual ecological source/law/event join differs')
    supplied = producer.human_inputs(bundle, recipe, parent, group_id, source_units, routed, eco)
    require(result['human_inputs'] == supplied and h['source_inputs'] == supplied, 'water/food/hazard full-producer consumer join differs')
    return {'water': water_checks, 'ecosystems': eco_checks, 'human': human_checks}


def result(bundle, recipe, parent, product):
    p = bundle.module('pipeline'); groups = p.parent_units(bundle, recipe, parent)
    require(product['schema'] == 'diadem.seasonal-consequences-result.r11'
            and product['source_sha256'] == bundle.source_sha256 and product['recipe_sha256'] == snapshot.sha(recipe)
            and product['parent_result_sha256'] == snapshot.sha(parent), 'actual full result identity differs')
    require(product['status'] == 'COMPLETE_BOUNDED_CONSEQUENCES' and product['state']['completed_scenarios'] == len(groups)
            and set(product['state']['results']) == set(groups), 'complete coequal scenario set required')
    for key in ('whole_generator_complete', 'production_installed', 'canon_changed', 'optimisation_performed'):
        require(product[key] is False, 'unsupported whole-generator/canon/production claim')
    codec = bundle.parent.graph.load('work.generator_upgrade_r10.payloads')
    biology = bundle.module('biology').build_overlay(bundle.module('owner_inputs').species(bundle))
    require(codec.unpack(product['biological_owner_inputs']) == biology, 'actual owner biology overlay differs')
    require(product['biological_input_status'] == 'OWNER_FACTS_AND_SCOPED_DECISIONS_INTEGRATED; NO_NEW_SELECTED_NUMERICAL_COEFFICIENTS',
            'source facts promoted to calibrated biology')
    geo = bundle.module('owner_inputs').geography(bundle)
    require(product['geo_input_contract']['sha256'] == snapshot.sha(geo)
            and product['geo_input_contract']['unresolved'] == geo['effective_unresolved']
            and product['geo_input_contract']['original_unresolved'] == geo['contract']['unresolved']
            and product['geo_input_contract']['requested_owner_returns_complete'] is True, 'GEO field-level input gates differ')
    return {key: group(bundle, recipe, parent, key, groups[key], codec.unpack(product['state']['results'][key])) for key in sorted(groups)}
