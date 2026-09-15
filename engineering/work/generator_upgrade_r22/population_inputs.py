"""Exact owner-selected population records, not redistribution or new siting.

The large historical database is retained as a query contract. Its known Haus
balances remain unplaced aggregates until source-pool/site rows are explicitly
recovered and crosswalked; null source counts are never treated as zero.
"""
from copy import deepcopy
import json
from pathlib import Path

from .species import _checked, digest

ROOT = Path(r'C:\Users\LOCAL_USER\Documents\The Diadem - Local Workspace\02_Working_Files\Geography\R22_Population_Inputs_2026-09-14')
PINS = {
    'HUMAN_INPUTS.json': '82fc5fd7c2709fadc0f95248e56bf02bfca959cf1ce6929d60463c3f500f7470',
    'human_allocation_review.json': 'dc56057094f05516683279cf14214269910a2cda349068d7a9b823d80d75b68e',
    'human_allocation_sources.json': 'ce7788e37b7c32734a00e53ef402edf3ec423178fe0bed3a5ae84ead65b1f36a',
}
SCHEMA = 'diadem.population-reference-assignments.r22'


def application(reference, geography_sha256, *, haus=None, crosswalk=None):
    """Prepare an exact whole-reference or Haus input for assign_reference."""
    if reference.get('schema') != SCHEMA: raise ValueError('source-qualified population reference required')
    rows = [deepcopy(r) for r in reference['assignments'] if haus is None or r['haus']==haus]
    if not rows: raise ValueError('known Haus reference required')
    mapping = deepcopy(crosswalk or {})
    by_id = {r['pool_id']: r for r in rows}
    if set(mapping)-set(by_id): raise ValueError('crosswalk contains another population scope')
    if any(not by_id[k]['can_crosswalk_whole_scope'] for k in mapping):
        raise ValueError('unresolved aggregate/membership source cannot acquire a site through generic crosswalk')
    return {'population': {'population_id': 'R22-HUMANS:'+(haus or 'WHOLE_REFERENCE'),
            'scope_id': haus or 'WHOLE_WORKING_REFERENCE', 'count': sum(r['count'] for r in rows),
            'counting_unit': 'HUMAN_INDIVIDUAL', 'geography_sha256': geography_sha256,
            'evidence_id': 'GEO-R22-POPULATION-INPUTS-2026-09-14',
            'source_status': 'WORKING NON-CANON', 'raw_source_status': reference['source_status'],
            'source_binding_sha256': reference['source_binding_sha256']},
        'assignments': rows, 'crosswalk': mapping}


def _integer(value):
    if type(value) is not int or value < 0: raise ValueError('nonnegative exact human count required')
    return value


def load():
    """Read the three delivered contracts and six exact identity/count sources."""
    documents = {name: json.loads(_checked(ROOT/name, sha)) for name, sha in PINS.items()}
    human, review, manifest = (documents[k] for k in PINS)
    if (human.get('schema') != 'diadem.r22.human-population-inputs.v1'
            or review.get('schema') != 'diadem.r22.human-allocation-source-review.v1'
            or manifest.get('schema') != 'diadem.r22.human-allocation-source-register.v1'):
        raise ValueError('exact owner population delivery required')
    sources = {r['id']: r for r in manifest['sources']}
    wanted = {row['source'] for row in review['allocation_sources'][:5]} | {'marienhain_primary_ids'}
    supplied = {}
    bindings = {str(ROOT/name): sha for name, sha in PINS.items()}
    for key in sorted(wanted):
        ref = sources[key]
        supplied[key] = json.loads(_checked(ref['path'], ref['sha256']))
        bindings[ref['path']] = ref['sha256']
    return build(human, review, supplied, source_bindings=bindings)


def build(human, review, supplied, *, source_bindings):
    """Compile preserved disjoint additions and base subtotals, without geography."""
    if human['allocation_policy'] != 'Reference identity-preserving replay plus exact source overrides only. No generic redistributive weights. Replacement locations require compatible owner-supplied parents/crosswalk.':
        raise ValueError('owner allocation policy changed')
    haus = {r['haus']: deepcopy(r) for r in human['haus_rows']}
    if len(haus) != 20 or len(haus) != len(human['haus_rows']): raise ValueError('exact unique twenty-Haus roster required')
    total = sum(_integer(r['working_human_total']) for r in haus.values())
    if total != human['totals']['humans'] or total != review['reference']['humans']:
        raise ValueError('owner total and Haus sum disagree')
    assignments, added, seen = [], {}, set()

    def add(pool_id, name, count, ids, kind, status, evidence, *, source=None, addition=True, crosswalk=False):
        _integer(count)
        if pool_id in seen or name not in haus: raise ValueError('unique known-Haus disjoint pool required')
        if type(ids) is not list or len(ids) != len(set(ids)): raise ValueError('distinct preserved source site IDs required')
        seen.add(pool_id)
        if addition: added[name] = added.get(name, 0)+count
        incorporated = name == 'Dunkelhauch'
        service_class = ('INCORPORATED_NO_ROUTINE_FOOD' if incorporated else
            'UNKNOWN' if kind == 'UNPLACED_BASE_HAUS_SUBTOTAL' else 'LIVING_HUMANS')
        assignments.append({'pool_id': pool_id, 'haus': name, 'count': count,
            'count_basis': 'DISJOINT_HUMAN_IDENTITIES', 'service_class': service_class,
            'counting_unit': 'INCORPORATED_HUMAN_IDENTITY' if incorporated else 'HUMAN_INDIVIDUAL',
            'source_site_ids': deepcopy(ids), 'residence_kind': kind,
            'routine_human_food_demand': False if incorporated else None if service_class == 'UNKNOWN' else True,
            'source_status': 'WORKING NON-CANON', 'raw_source_status': status,
            'evidence_id': evidence, 'source_record': deepcopy(source),
            'can_crosswalk_whole_scope': crosswalk, 'split_counts_selected': False,
            'placement_status': 'UNKNOWN', 'replacement_support_id': None,
            'overlap_policy': 'EXPLICIT_DISJOINT_OWNER_POOL; SOURCE_IDS_AND_RESIDENTS_PRESERVED'})

    allocation = {r['haus']: r for r in review['allocation_sources']}
    specialist_count = specialist_humans = 0
    for name in ('Glanzgrund', 'Edelstein', 'Feuerschuppe', 'Eisenweb', 'Zwielicht'):
        contract = allocation[name]; rows = supplied[contract['source']]['sites']
        value_path = contract['human_path'].removeprefix('sites[].').split('.')
        ids, subtotal = set(), 0
        for row in rows:
            sid = row['settlement_id']; value = row
            for key in value_path: value = value[key]
            count = _integer(value)
            if sid in ids: raise ValueError('duplicate specialist source identity within Haus')
            ids.add(sid); subtotal += count
            add('SPECIALIST:'+name+':'+sid, name, count, [sid], 'FIXED_RESIDENT_SCOPE',
                contract['status'], contract['source']+':'+sid, source=row, crosswalk=True)
        if len(ids) != contract['sites'] or subtotal != contract['additional_humans']:
            raise ValueError('exact specialist selected path/count changed: '+name)
        specialist_count += len(ids); specialist_humans += subtotal
    if (specialist_count, specialist_humans) != (77, 234076): raise ValueError('specialist coverage changed')

    contract = allocation['Marienhain']; capital = contract['capital']
    add('MARIENHAIN:PRIMARY_CAPITAL', 'Marienhain', capital['humans'], [capital['site_id']],
        'FIXED_RESIDENT_SCOPE', contract['status'], 'marienhain_approved:capital', source=contract, crosswalk=True)
    other = contract['other_primary_family']
    ids = [r['site_id'] for r in supplied[contract['identity_source']]['rows'] if r['site_id'] != capital['site_id']]
    if len(ids) != other['sites'] or len(ids) != len(set(ids)): raise ValueError('Marienhain primary-family identities changed')
    add('MARIENHAIN:OTHER_PRIMARY_AGGREGATE', 'Marienhain', other['aggregate_humans'], ids,
        'UNSPLIT_MULTI_SITE_ALLOWANCE', contract['status'], 'marienhain_approved:other_primary_family', source=contract)

    contract = allocation['Stillklinge']
    for scope in contract['scopes']:
        add(scope['scope_id'], 'Stillklinge', scope.get('humans', scope.get('humans_inclusive')), scope['site_ids'],
            'INCLUSIVE_RESIDENCE_SCOPE' if 'humans_inclusive' in scope else 'FIXED_RESIDENT_SCOPE',
            contract['status'], 'stillklinge_approved:'+scope['scope_id'], source=scope, crosswalk=True)

    contract = allocation['Duftfährte']
    for scope in contract['home_membership']:
        add('DUFTFAEHRTE:HOME:'+scope['pool'], 'Duftfährte', scope['humans'], [],
            'MOBILE_HOME_MEMBERSHIP_AGGREGATE', contract['status'], 'duftfaehrte_membership:'+scope['pool'], source=scope)

    if sum(added.values()) != human['totals']['additions']:
        raise ValueError('disjoint source addition total changed')
    for name, row in haus.items():
        expected_addition = allocation.get(name, {}).get('additional_humans', 0)
        if added.get(name, 0) != expected_addition: raise ValueError('Haus addition sum differs: '+name)
        base = row['working_human_total']-added.get(name, 0)
        if base < 0: raise ValueError('additions exceed whole-Haus total')
        add('BASE:'+name, name, base, [], 'INCORPORATED_IDENTITY_REFERENCE' if name == 'Dunkelhauch' else 'UNPLACED_BASE_HAUS_SUBTOTAL',
            row['population_status'], 'v4_database:'+human['query_contract']['run_id']+':'+name,
            source={'haus_record': row, 'source_pool_query': human['query_contract']}, addition=False)
    accounted = sum(r['count'] for r in assignments)
    if accounted != total or sum(r['count'] for r in assignments if r['service_class']=='INCORPORATED_NO_ROUTINE_FOOD') != 50:
        raise ValueError('exact people/ordinary-food distinction failed')
    return {'schema': SCHEMA, 'status': 'REFERENCE_IDENTITIES_RECOVERED_SPATIAL_JOINS_INCOMPLETE',
        'source_bindings': deepcopy(source_bindings), 'source_binding_sha256': digest(source_bindings),
        'haus_rows': list(haus.values()), 'assignments': assignments,
        'totals': deepcopy(human['totals']), 'accounted_human_identities': accounted,
        'count_excluding_incorporated_reference': total-50,
        'known_living_service_class_count': sum(r['count'] for r in assignments if r['service_class']=='LIVING_HUMANS'),
        'unresolved_service_class_count': sum(r['count'] for r in assignments if r['service_class']=='UNKNOWN'),
        'placed_human_identities': 0,
        'unplaced_human_identities': total, 'specialist_sites': specialist_count, 'specialist_humans': specialist_humans,
        'query_contract': deepcopy(human['query_contract']),
        'unresolved_base_query': {'status': 'INCOMPLETE', 'native_pool_and_site_rows_recovered': False,
            'null_estimate_rows': human['query_contract']['read_only_check']['null_estimate_rows'],
            'known_subtotal': human['totals']['base_humans'],
            'reason': 'Base Haus known subtotals retained; individual SQL pool/site identities and their NULL flags require exact source query before replacement-site use.'},
        'retained_constraints': deepcopy(review['retained_pool_constraints']),
        'allocation_constraints': deepcopy(review['allocation_sources']),
        'food_constraints': deepcopy(review['food_constraints']), 'holds': deepcopy(human['holds']),
        'missing_joins': deepcopy(review['r22_compatibility']['required_before_spatial_use']),
        'population_reconciliation': deepcopy(human['population_reconciliation']),
        'source_status': human['status'], 'fictional_census_date': human['fictional_census_date'],
        'limits': 'Identity/count recovery only; no generic allocation weights, ancestry, bond redistribution, terrain capacity, food yields or current spatial acceptance.'}
