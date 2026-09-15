"""Replaceable geographical placement and fixed-population service connections.

Weights/caps are supplied working hypotheses, never inferred from population
totals or biology. Exact capped apportionment preserves people and reports any
unplaced balance. It does not create settlements, route capacity or resources.
"""
from copy import deepcopy
from fractions import Fraction as F

from work.generator_upgrade_r21 import _native_human as human
from work.generator_upgrade_r21.quantities import q, ident, plain
from . import provenance as p, _native_transport
from .cache import StageCache

SCHEMA = 'diadem.geography-population-connection.r22'
KNOWN = {'CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST', 'Provisional', 'Review-only'}
UNRESOLVED = {'UNKNOWN', 'CONFLICT', 'INCOMPLETE'}


def _source(row):
    ident(row.get('evidence_id'), 'evidence')
    if row.get('source_status') not in KNOWN | UNRESOLVED:
        raise ValueError('preserved explicit source status required')
    return row['source_status'] not in UNRESOLVED


def _integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError('nonnegative integer '+name+' required')
    return value


def _geography(value):
    if type(value) is not dict or type(value.get('context')) is not dict:
        raise ValueError('bound working geography view required')
    for key in ('world_id', 'snapshot_id', 'spatial_frame_id', 'vertical_reference'):
        ident(value['context'].get(key), key)
    for key in ('state_sha256', 'seed_scientific_sha256'):
        human._sha(value.get(key))
    if value.get('role') not in ('PRE_TERRAIN_FINITE_GEOLOGICAL_BODY_AND_INITIAL_SURFACE',
                                 'EVOLVED_FINITE_GROUND_CHILD', 'SYNTHETIC TEST',
                                 'EVOLVED_WORKING_TERRAIN_CHILD', 'SELECTED_WORKING_INITIAL_TERRAIN_SEED'):
        raise ValueError('explicit working seed/child role required; no legacy repin')
    if value.get('source_status') not in KNOWN:
        raise ValueError('numeric working geography required')
    if type(value.get('supports')) is not dict or not value['supports']:
        raise ValueError('explicit geographic supports required')
    return p.sha(value)


def _allocate(total, candidates):
    """Capped proportional quotas, then largest remainder; no per-person loop."""
    active = {r['settlement_id']: r for r in candidates
              if r['eligible'] and q(r['weight']) and r['max_population']}
    target = min(total, sum(r['max_population'] for r in active.values()))
    remaining, quota = F(target), {}
    while active:
        denominator = sum((q(r['weight']) for r in active.values()), F())
        proposed = {key: remaining*q(row['weight'])/denominator for key, row in active.items()}
        capped = [key for key, value in proposed.items() if value > active[key]['max_population']]
        if not capped:
            quota.update(proposed)
            break
        for key in capped:
            quota[key] = F(active[key]['max_population'])
            remaining -= quota[key]
            del active[key]
    counts = {r['settlement_id']: int(quota.get(r['settlement_id'], 0)) for r in candidates}
    extra = target-sum(counts.values())
    order = sorted(quota, key=lambda key: (-(quota[key]-counts[key]), key))
    for key in order[:extra]:
        counts[key] += 1
    if sum(counts.values()) != target or any(counts[r['settlement_id']] > r['max_population'] for r in candidates):
        raise ValueError('exact population apportionment failed')
    return counts, total-target, {key: str(value) for key, value in quota.items()}


def _place(invocation):
    population, candidates, geography, policy = (invocation[k] for k in ('population', 'candidates', 'geography', 'policy'))
    gh = _geography(geography)
    if policy.get('allocation') != 'CAPPED_WEIGHTED_LARGEST_REMAINDER' or policy.get('tie_break') != 'SETTLEMENT_ID_ASCENDING':
        raise ValueError('explicit supported apportionment/tie policy required')
    policy_known, population_known = _source(policy), _source(population)
    known = policy_known and population_known
    for key in ('population_id', 'counting_unit', 'scope_id'):
        ident(population.get(key), key)
    if population.get('geography_sha256') != gh:
        raise ValueError('population application is bound to different geography')
    count = population.get('count')
    if count is not None:
        _integer(count, 'population')
    if type(candidates) is not list or len(candidates) > 4096:
        raise ValueError('bounded candidate list required')
    seen = set()
    for row in candidates:
        sid = ident(row.get('settlement_id'))
        if sid in seen: raise ValueError('duplicate settlement candidate')
        seen.add(sid)
        if row.get('support_id') not in geography['supports'] or row.get('geography_sha256') != gh:
            raise ValueError('candidate support/geography differs; explicit replacement join required')
        row_known = _source(row)
        if row.get('eligible') is not None and type(row['eligible']) is not bool:
            raise ValueError('explicit eligibility boolean or UNKNOWN required')
        if row.get('weight') is not None: q(row['weight'], 'placement weight')
        if row.get('max_population') is not None: _integer(row['max_population'], 'site cap')
        known = known and row_known and all(row.get(k) is not None for k in ('eligible', 'weight', 'max_population'))
    result = {'schema': SCHEMA, 'status': 'UNKNOWN', 'source_status': 'WORKING NON-CANON',
        'input_sha256': p.sha(invocation), 'geography_sha256': gh, 'context': deepcopy(geography['context']),
        'population_id': population['population_id'], 'counting_unit': population['counting_unit'],
        'scope_id': population['scope_id'], 'total': count, 'placed': 0, 'unplaced': count,
        'settlements': [], 'inputs': deepcopy(invocation), 'physical_acceptance': False}
    if not known or count is None:
        return {**result, 'reason': 'unresolved total, placement rule or candidate; no unknown-as-zero allocation'}
    counts, unplaced, quotas = _allocate(count, candidates)
    rows = [{**deepcopy(row), 'population': counts[row['settlement_id']]} for row in candidates]
    return {**result, 'status': 'PARTIAL' if unplaced else 'MODELLED', 'reason': None,
        'placed': count-unplaced, 'unplaced': unplaced, 'settlements': rows,
        'exact_continuous_quotas': quotas, 'population_residual': 0,
        'scope': 'SUPPLIED_WORKING_SITE_WEIGHTS_AND_CAPS; NOT_CARRYING_CAPACITY_OR_CANON_SITING'}


def place(population, candidates, *, geography, policy, cache=True, cache_root=None):
    invocation = deepcopy(dict(population=population, candidates=candidates, geography=geography, policy=policy))
    def validate(value):
        if value != _place(invocation): raise ValueError('cached placement differs from exact supplied allocation')
    if not cache: return _place(invocation)
    store = StageCache('population-placement', {'contract': SCHEMA}, cache_root)
    value, _ = store.reuse(invocation, lambda: _place(invocation), validate)
    return value


def _reference(invocation):
    population, assignments, crosswalk, geography = (invocation[k] for k in ('population', 'assignments', 'crosswalk', 'geography'))
    gh = _geography(geography)
    if population.get('geography_sha256') != gh:
        raise ValueError('reference population application geography differs')
    population_known = _source(population)
    total = _integer(population.get('count'), 'reference total')
    if population.get('counting_unit') != 'HUMAN_INDIVIDUAL':
        raise ValueError('explicit human identity reference required')
    if type(assignments) is not list or len(assignments) > 100000 or type(crosswalk) is not dict:
        raise ValueError('bounded source assignments and explicit identity crosswalk required')
    used, all_known, placed, sites, unplaced = set(), 0, 0, {}, []
    for row in assignments:
        identity = ident(row.get('pool_id'), 'disjoint source pool')
        if identity in used or row.get('count_basis') != 'DISJOINT_HUMAN_IDENTITIES':
            raise ValueError('one count per disjoint source pool, never summed hierarchy/visits')
        used.add(identity)
        row_known = _source(row)
        count = row.get('count')
        if count is None:
            unplaced.append({'pool_id': identity, 'count': None, 'reason': 'UNKNOWN reference count'})
            continue
        _integer(count, 'reference pool count')
        all_known += count
        link = crosswalk.get(identity)
        if not population_known or not row_known or link is None or link.get('usable') is not True:
            unplaced.append({'pool_id': identity, 'count': count, 'reason': 'missing/rejected working identity join'})
            continue
        if link.get('geography_sha256') != gh or link.get('support_id') not in geography['supports']:
            raise ValueError('reference crosswalk physical parent differs')
        if not _source(link):
            unplaced.append({'pool_id': identity, 'count': count, 'reason': 'UNKNOWN working identity join'})
            continue
        sid = ident(link.get('settlement_id'))
        if sid in sites and sites[sid]['support_id'] != link['support_id']:
            raise ValueError('one settlement cannot silently change support between pools')
        site = sites.setdefault(sid, {**deepcopy(link), 'population': 0, 'pool_ids': [], 'service_classes': {}})
        service_class = row.get('service_class', 'UNKNOWN')
        if service_class not in ('LIVING_HUMANS', 'INCORPORATED_NO_ROUTINE_FOOD', 'UNKNOWN'):
            raise ValueError('explicit source human service class required')
        site['population'] += count
        site['pool_ids'].append(identity)
        site['service_classes'][service_class] = site['service_classes'].get(service_class, 0)+count
        placed += count
    if all_known > total:
        raise ValueError('reference counts exceed total; overlay or duplicate identity must be resolved')
    return {'schema': SCHEMA+'.reference', 'status': 'MODELLED' if placed == total and not unplaced else 'PARTIAL',
        'source_status': 'WORKING NON-CANON', 'input_sha256': p.sha(invocation), 'inputs': deepcopy(invocation),
        'population_id': population['population_id'], 'counting_unit': 'HUMAN_INDIVIDUAL',
        'scope_id': population['scope_id'], 'total': total, 'placed': placed, 'unplaced': total-placed,
        'unresolved_reference_remainder': total-all_known, 'unplaced_source_rows': unplaced,
        'settlements': [sites[sid] for sid in sorted(sites)], 'geography_sha256': gh,
        'context': deepcopy(geography['context']), 'population_residual': 0, 'physical_acceptance': False,
        'scope': 'IDENTITY_PRESERVING_REFERENCE_JOIN; NO_REDISTRIBUTION_OR_COORDINATE_INFERENCE'}


def assign_reference(population, assignments, crosswalk, *, geography, cache=True, cache_root=None):
    """Keep source people in their existing identity pools; missing joins unplaced."""
    invocation = deepcopy(dict(population=population, assignments=assignments, crosswalk=crosswalk, geography=geography))
    if not cache: return _reference(invocation)
    store = StageCache('reference-population-join', {'contract': SCHEMA+'.reference'}, cache_root)
    def validate(value):
        if value != _reference(invocation): raise ValueError('cached reference join differs')
    value, _ = store.reuse(invocation, lambda: _reference(invocation), validate)
    return value


def connect_human(placement, human_inputs, rates, *, geography_sha256, cache=True, cache_root=None):
    """Execute placed population -> supplied per-person demand -> finite network.

Input templates must leave their demand slots empty: no duplicate service or
silent overwrite. Stocks, delivered water, harvests and shared route capacities
are supplied unchanged. Unplaced people remain reported, never disappear.
"""
    if placement.get('schema') not in (SCHEMA, SCHEMA+'.reference') or placement.get('status') not in ('MODELLED', 'PARTIAL'):
        raise ValueError('modelled fixed-population placement required')
    verify_placement = _reference if placement['schema'] == SCHEMA+'.reference' else _place
    if placement != verify_placement(placement['inputs']):
        raise ValueError('placement source/account binding differs')
    if placement['counting_unit'] != 'HUMAN_INDIVIDUAL':
        raise ValueError('human consumer cannot reinterpret animal stock or active bonds')
    if geography_sha256 != placement['geography_sha256']:
        raise ValueError('network and placement geography differ; no silent rebind')
    known = _source(rates)
    if rates.get('unit_basis') != 'PER_HUMAN_INDIVIDUAL_PER_SECOND':
        raise ValueError('explicit rate units required; no assumed day/calendar')
    if not known or rates.get('water_m3') is None or any(v is None for v in rates.get('food_kg', {}).values()):
        return {'schema': SCHEMA+'.human', 'status': 'UNKNOWN', 'reason': 'unresolved supplied per-person service rates',
            'placement': deepcopy(placement), 'rates': deepcopy(rates)}
    payload = deepcopy(human_inputs)
    sites = {r['settlement_id']: r for r in placement['settlements']}
    templates = {r['settlement_id']: r for r in payload['settlements']}
    if len(templates) != len(payload['settlements']) or set(templates) != set(sites):
        raise ValueError('exact settlement/node coverage required')
    commodities = {r['commodity_id'] for r in payload['commodities']}
    if set(rates.get('food_kg', {})) != commodities or set(rates.get('food_weight_per_kg', {})) != commodities:
        raise ValueError('supplied per-person demand and priority per commodity required')
    if payload['scenario_id'] != placement['context'].get('scenario_id'):
        raise ValueError('human scenario differs from geographic application')
    for key, row in templates.items():
        if row['support_id'] != sites[key]['support_id']:
            raise ValueError('settlement accounting support differs from placement')
        row['population'] = sites[key]['population']
    clocks = {r['event_id']: r for r in payload['calendar']}
    for event in payload['events']:
        if any(event.get(k) != [] for k in ('water_demands', 'water_demand_order', 'food_demands', 'food_demand_order')):
            raise ValueError('empty explicit demand slots required; existing obligations are not overwritten')
        duration = q(clocks[event['event_id']]['duration_seconds'], positive=True)
        for sid in sorted(sites):
            persons = sites[sid]['population']
            if placement['schema'] == SCHEMA+'.reference':
                classes = sites[sid]['service_classes']
                if classes.get('UNKNOWN', 0):
                    raise ValueError('unknown residence/service identity cannot become ordinary food demand')
                persons = classes.get('LIVING_HUMANS', 0)
            water_id = event['event_id']+'-water-'+sid
            source = {'evidence_id': rates['evidence_id'],
                'source_status': rates['source_status'] if rates['source_status'] in {'CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST'} else 'WORKING NON-CANON',
                'source_status_original': rates['source_status']}
            event['water_demands'].append(dict(source, demand_id=water_id, settlement_id=sid,
                                               required_m3=str(persons*duration*q(rates['water_m3']))))
            event['water_demand_order'].append(water_id)
            for cid in sorted(commodities):
                did = event['event_id']+'-food-'+sid+'-'+cid
                event['food_demands'].append(dict(source, demand_id=did, settlement_id=sid, commodity_id=cid,
                    required_kg=str(persons*duration*q(rates['food_kg'][cid])),
                    weight_per_kg=str(q(rates['food_weight_per_kg'][cid], positive=True))))
                event['food_demand_order'].append(did)
    invocation = {'placement': placement, 'template': human_inputs, 'rates': rates, 'geography_sha256': geography_sha256}
    payload['source_binding_sha256'] = p.sha(invocation)
    def produce():
        result = human.run_year(_native_transport, **plain(payload))
        return {'schema': SCHEMA+'.human', 'status': result['status'], 'input_sha256': p.sha(invocation),
            'human': result, 'native_inputs': plain(payload), 'placement': deepcopy(placement),
            'unplaced_population': placement['unplaced'], 'rate_sources': deepcopy(rates),
            'geography_sha256': geography_sha256, 'whole_diadem_year_verified': False}
    def validate(value):
        if (value.get('input_sha256') != p.sha(invocation) or value.get('geography_sha256') != geography_sha256
                or value.get('native_inputs') != plain(payload)
                or value.get('human', {}).get('input_sha256') != human.digest(plain(payload))
                or value.get('status') != value.get('human', {}).get('status')):
            raise ValueError('cached human connection input differs')
    if not cache: return produce()
    store = StageCache('placed-human-service', {'contract': SCHEMA}, cache_root)
    result, _ = store.reuse(invocation, produce, validate)
    return result
