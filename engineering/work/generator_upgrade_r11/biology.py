"""Source-aware R11 biology successor. No source discovery or invented calibration."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
import re

ENTRY = 'BIOLOGICAL_INPUT_CONTRACT_R1.json'
CATALOGUE = 'contract_review/FIELD_CONTRACT_PROPOSAL.json'
SCHEMA = 'contract_review/FIELD_RECORD_SCHEMA.json'
PLANTS = 'plants/PLANT_FACTS.json'
PRIMARY = 'primary_biology/PRIMARY_BIOLOGY_CONTRACT.json'
HS4 = 'hs4/HS4_HOST_FIELDS_R1.json'
PATHWAY = 'HS4_SKYREACH_LINKED_PATHWAY_R1'


def _json(value):
    """Strict JSON, not Python's non-finite JSON extension or arbitrary objects."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for v in value:
            _json(v)
        return
    if type(value) is dict and all(type(k) is str for k in value):
        for v in value.values():
            _json(v)
        return
    raise ValueError('not strict JSON')


def _hash(value):
    _json(value)
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _text(v, name):
    if type(v) is not str or not v.strip() or len(v) > 8192:
        raise ValueError(name + ': nonempty bounded text required')
    return v


def _number(v, name, *, nonnegative=True):
    if type(v) not in (str, int, float) or (type(v) is str and len(v) > 256):
        raise ValueError(name + ': finite number required')
    try:
        n = Fraction(v)
    except (ValueError, OverflowError, ZeroDivisionError):
        raise ValueError(name + ': finite number required') from None
    if max(n.numerator.bit_length(), n.denominator.bit_length()) > 8192:
        raise ValueError(name + ': numeric range too large')
    if nonnegative and n < 0:
        raise ValueError(name + ': negative value')
    return n


def _schema(value, schema, where='record'):
    """The delivered envelope's complete validation vocabulary, fail closed on drift.

    This small interpreter is deliberately not advertised as general JSON Schema.
    It implements every validation keyword used in the pinned owner envelope.
    """
    known = {'$schema', '$comment', 'title', 'type', 'additionalProperties', 'required',
        'properties', 'enum', 'const', 'minLength', 'maxLength', 'pattern', 'items',
        'minItems', 'maxItems', 'anyOf', 'allOf', 'if', 'then', 'not'}
    if set(schema) - known:
        raise ValueError('unsupported owner schema keyword')
    types = {'null': lambda x: x is None, 'object': lambda x: type(x) is dict,
        'array': lambda x: type(x) is list, 'string': lambda x: type(x) is str,
        'boolean': lambda x: type(x) is bool, 'integer': lambda x: type(x) is int,
        'number': lambda x: type(x) in (int, float)}
    if 'type' in schema:
        allowed = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if not all(t in types for t in allowed) or not any(types[t](value) for t in allowed):
            raise ValueError(where + ': schema type')
    # JSON booleans must not pass a numeric enum through Python's True == 1.
    equal = lambda a, b: type(a) is type(b) and a == b
    if 'enum' in schema and not any(equal(value, x) for x in schema['enum']):
        raise ValueError(where + ': schema enum')
    if 'const' in schema and not equal(value, schema['const']):
        raise ValueError(where + ': schema const')
    if isinstance(value, str):
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 8192):
            raise ValueError(where + ': schema text length')
        if 'pattern' in schema and re.search(schema['pattern'], value) is None:
            raise ValueError(where + ': schema pattern')
    if type(value) is dict:
        if set(schema.get('required', [])) - set(value):
            raise ValueError(where + ': missing required keys')
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False and set(value) - set(props):
            raise ValueError(where + ': unknown keys')
        for key in set(value) & set(props):
            _schema(value[key], props[key], where + '.' + key)
    if type(value) is list:
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 10000):
            raise ValueError(where + ': schema array length')
        if 'items' in schema:
            for item in value:
                _schema(item, schema['items'], where + '[]')
    def matches(s):
        try:
            _schema(value, s, where)
            return True
        except ValueError:
            return False
    if 'anyOf' in schema and not any(matches(s) for s in schema['anyOf']):
        raise ValueError(where + ': no schema alternative')
    for s in schema.get('allOf', []):
        _schema(value, s, where)
    if 'not' in schema and matches(schema['not']):
        raise ValueError(where + ': forbidden schema value')
    if 'if' in schema and matches(schema['if']) and 'then' in schema:
        _schema(value, schema['then'], where)


def _package(package):
    _json(package)
    for key in ('manifest_sha256', 'entry_sha256'):
        if re.fullmatch('[0-9a-f]{64}', package[key]) is None:
            raise ValueError('invalid delivery hash')
    d = package['documents']
    entry, cat, schema = d[ENTRY], d[CATALOGUE], d[SCHEMA]
    if package['source_bindings'][ENTRY]['sha256'] != package['entry_sha256']:
        raise ValueError('entry binding mismatch')
    if entry['schema'] != 'diadem.r11.biological-input-contract.v1':
        raise ValueError('unsupported delivery')
    ids = [r['organism_id'] for r in entry['identity_records']]
    if len(ids) != 36 or len(set(ids)) != 36 or set(ids) != set(cat['identities']):
        raise ValueError('exact 36-identity join differs')
    if set(ids) != set(schema['properties']['organism_id']['enum']):
        raise ValueError('record schema identity join differs')
    if set(ids) != set(d['contract_review/roster_readback.json']):
        raise ValueError('retained roster identity join differs')
    if len(cat['field_catalog']) != 35 or set(cat['field_catalog']) != set(schema['properties']['field_id']['enum']):
        raise ValueError('35-field catalogue differs from schema')
    for row in entry['identity_records']:
        if row['kind'] != cat['identities'][row['organism_id']]['kind']:
            raise ValueError('organism kind mismatch')
    return d, entry, cat, schema


def _registry(package):
    d = package['documents']
    refs = {}
    for s in d['plants/SOURCE_INDEX.json']['plant_sources']:
        refs[s['source_id']] = {'path': s['path'], 'sha256': s['sha256'],
            'raw_source_status': json.dumps({'document_header_status': s['document_header_status'],
                'embedded_reconciliation_labels': s['embedded_reconciliation_labels'],
                'status_guard': s['status_guard']}, ensure_ascii=False, sort_keys=True),
            'locator_convention': s['paragraph_convention']}
    for key, s in d['primary_biology/SOURCES.json']['sources'].items():
        refs[key] = {'path': s.get('source_path', s.get('path')),
            'sha256': s.get('source_sha256', s.get('sha256')),
            'raw_source_status': s.get('authority_role', s.get('raw_status', 'SOURCE REGISTRY; status not supplied')),
            'locator_convention': s.get('locator_definition', s.get('locator', 'Original registry locator'))}
    return refs


def _source(refs, key, paragraphs, status=None):
    s = refs[key]
    if not paragraphs or any(type(p) is not int or p < 1 for p in paragraphs):
        raise ValueError('source paragraph list invalid')
    return {'path': s['path'], 'sha256': s['sha256'],
        'locator': ','.join('P' + str(p) for p in paragraphs) + '; ' + s['locator_convention'],
        'raw_source_status': status or s['raw_source_status']}


def _bound_ref(package, path, locator, status='WORKING NON-CANON'):
    return dict(package['source_bindings'][path], locator=locator, raw_source_status=status)


def validate_records(package, records):
    """Validate owner envelope AND field type/unit/applicability/source semantics.

    Passing does not approve a source claim or compile an arbitrary structured law.
    Numeric selection requires a bound decision and complete native context.
    """
    d, entry, cat, schema = _package(package)
    _json(records)
    if type(records) is not list or len(records) > 10000:
        raise ValueError('bounded records list required')
    registry = _registry(package)
    allowed = {}
    for x in registry.values():
        if x['path'] and x['sha256']:
            allowed.setdefault((x['path'].replace('\\', '/'), x['sha256']), set()).add(x['raw_source_status'])
    for x in package['source_bindings'].values():
        allowed.setdefault((x['path'].replace('\\', '/'), x['sha256']), set()).add('WORKING NON-CANON')
    # Approved scope labels belong to the actual asserted row, not the whole file.
    def row_statuses(value):
        if type(value) is dict:
            if value.get('source_id') in registry and type(value.get('status')) is str:
                s = registry[value['source_id']]
                allowed[(s['path'].replace('\\', '/'), s['sha256'])].add(value['status'])
            for v in value.values():
                row_statuses(v)
        elif type(value) is list:
            for v in value:
                row_statuses(v)
    row_statuses(d[PRIMARY])
    seen = set()
    for r in records:
        _schema(r, schema)
        if r['record_id'] in seen:
            raise ValueError('duplicate biological record ID')
        seen.add(r['record_id'])
        field, context = r['field_id'], r['context']
        kind = cat['identities'][r['organism_id']]['kind']
        if field.startswith('plant.') and kind != 'PLANT':
            raise ValueError('plant field on non-plant')
        if field.startswith('animal.') and kind != 'ANIMAL':
            raise ValueError('animal field on non-animal')
        if field == 'special.event_register' and r['organism_id'] != 'HS14':
            raise ValueError('event register applies only to HS14')
        if field in ('special.wild_count', 'special.organism_footprint_mass') and r['organism_id'] != 'HS19':
            raise ValueError('special organism applies only to HS19')
        for s in r['source_refs'] + ([r['use_decision_ref']] if r['use_decision_ref'] else []):
            key = (s['path'].replace('\\', '/'), s['sha256'])
            if key not in allowed:
                raise ValueError('unbound biological source reference')
            if 'SYNTHETIC TEST' in s['raw_source_status']:
                raise ValueError('synthetic test is not biology for a real roster identity')
            if s['raw_source_status'] not in allowed[key]:
                raise ValueError('raw source status differs from the delivered source/claim labels')
        if r['kernel_status'] == 'CANON' and r not in entry['compiler_ready_numeric_field_records']:
            raise ValueError('source facts cannot silently promote kernel status to CANON')
        if context['native_measure_unit'] not in (None, 'm', 'm2', 'm3'):
            raise ValueError('unsupported native measure; no implicit area projection')
        if context['duration_s'] is not None and _number(context['duration_s'], 'duration') <= 0:
            raise ValueError('positive duration required')
        if r['value'] is None:
            continue
        vtype = cat['field_catalog'][field]['value_type']
        if vtype == 'structured' and type(r['value']) not in (dict, list):
            raise ValueError('structured field requires structured value')
        if vtype == 'text' and r['value'] not in ('NONMOVING', 'SEASONAL_MOVEMENT', 'UNKNOWN'):
            raise ValueError('unsupported movement mode')
        if vtype == 'quantity':
            n = _number(r['value'], field, nonnegative=field not in ('occupancy.logit_intercept', 'occupancy.logit_slope'))
            unit = _text(r['unit'], 'quantity unit')
            fraction_fields = {'habitat.suitability_minimum', 'habitat.habitat_fraction',
                'occupancy.conditional_occupied_fraction', 'density.occupied_fraction'}
            if field in fraction_fields and (n > 1 or unit != '1'):
                raise ValueError('fraction outside [0,1] or wrong unit')
            fixed = {'occupancy.logit_intercept': '1', 'occupancy.logit_slope': '1 per unit habitat_support',
                'stock.allocation_weight': '1 relative weight', 'special.wild_count': 'wild organism identities'}
            if field in fixed and unit != fixed[field]:
                raise ValueError('field unit differs')
            if field == 'stock.occupied_measure' and unit != context['native_measure_unit']:
                raise ValueError('occupied measure has wrong native dimension')
            if field == 'density.value' and (not context['counting_unit'] or not context['native_measure_unit'] or
                    unit != context['counting_unit'] + '/' + context['native_measure_unit']):
                raise ValueError('density must use exact counting unit/native measure')
            if field == 'special.wild_count' and n != 0:
                raise ValueError('HS19 absent-wild branch contradicts nonzero wild count')
            if field == 'movement.budget' and unit not in ('s', 'm') and not unit.startswith('RESISTANCE:'):
                raise ValueError('movement budget unit unspecified')
            if field in ('stock.total_expected_entities', 'stock.capacity_expected_entities',
                    'movement.requested_entities', 'movement.receiving_capacity', 'movement.edge_capacity'):
                if not context['counting_unit'] or unit != context['counting_unit']:
                    raise ValueError('entity count requires matching declared unit')
            if field in ('plant.growth_or_productivity', 'plant.turnover_or_litter_flux'):
                if not context['native_measure_unit'] or unit != 'kg dry matter/' + context['native_measure_unit'] + '/s':
                    raise ValueError('plant flux requires explicit dry-mass/native-measure/second unit')
            if field == 'recruitment.rate' and (not context['counting_unit'] or unit != context['counting_unit'] + '/s'):
                raise ValueError('recruitment rate requires counted entities per second')
            if field == 'movement.cost_per_m' and unit not in ('s/m', 'm/m') and not (unit.startswith('RESISTANCE:') and unit.endswith('/m')):
                raise ValueError('movement cost unit unspecified')
        if r['model_use'] == 'SELECTED_FOR_R11':
            if r not in entry['compiler_ready_numeric_field_records']:
                raise ValueError('numerical selection is not present in the verified owner delivery')
            needed = ('life_stage', 'cohort_id', 'scope_id', 'support_id', 'snapshot_id',
                'physical_scenario_id', 'time_basis', 'calendar_id', 'phase_id',
                'within_period_aggregation', 'joint_scenario_id', 'natural_or_managed')
            for key in needed:
                _text(context[key], 'selected context ' + key)
            if cat['identities'][r['organism_id']]['applicability'] != 'SPATIAL' and field.startswith(('density.', 'occupancy.')):
                raise ValueError('special identity cannot use habitat density/occupancy')
            # Envelope validation is not a generic structured-law compiler.
            if vtype == 'structured':
                raise ValueError('structured biology is constraint-only until an explicit law compiler exists')
    return {'status': 'VALIDATED_NOT_CALIBRATION', 'records': len(records), 'catalogue_fields': 35}


_PLANT_FIELDS = {
    'habitat.requirements': 'habitat habitat_and_attachment habitat_context habitat_and_forms habitat_and_substrate habitat_and_history habitat_and_establishment environmental_preferences habitat_and_growth habitat_and_management habitat_and_salt',
    'habitat.dependencies_exclusions': 'uptake_and_substrate stress_and_harvest water_uptake food_web_and_litter proposed_fertilisation growth_and_harvest symbiosis exclusions_and_stress functional_weather_limits host_requirement water_and_drought nutrient_carbon_and_competition stress management_not_native_mask host_interaction universal_host_dependency root_and_nutrient_function snow_and_erosion_effects energy_and_nutrients predation_cost_and_state environmental_stress habitat_engineering limits_and_emergency_cost exclusions digestion_and_recycling cost_and_mortality',
    'plant.phenological_windows': 'phenology_and_litter release_phenology phenology cultivated_fruiting phenology_and_longevity growth_and_dormancy',
    'recruitment.requirements': 'reproduction establishment sexual_reproduction graft_establishment reproduction_and_dispersal proposed_reproduction_and_attachment establishment_and_spread growth_and_reproduction',
    'natural_history.observation': 'harvest_not_reproduction counting_unit_and_clone taxonomic_reconciliation counting_unit growth_habit clonal_counting perennial_counting_and_harvest body_and_counting limits_of_evidence counting_unit_and_growth petal_transport_not_seed_dispersal biological_unknowns movement_not_dispersal',
    'dispersal.response': 'dispersal',
}
_PLANT_MAP = {name: field for field, names in _PLANT_FIELDS.items() for name in names.split()}
_PRIMARY_MAP = {'cohort_reconciliation': 'natural_history.observation',
    'habitat_constraints': 'habitat.requirements', 'seasonal_residence': 'animal.seasonal_resource_refuge_response',
    'resource_and_refuge_requirements': 'animal.seasonal_resource_refuge_response',
    'recruitment': 'recruitment.requirements'}


def _record(schema, oid, rid, field, value, refs, evidence):
    return {'record_id': rid, 'organism_id': oid, 'field_id': field,
        'context': {key: None for key in schema['properties']['context']['required']},
        'assertion_state': 'SOURCED_VALUE', 'value': deepcopy(value), 'unit': None,
        'evidence': evidence, 'source_refs': refs,
        'uncertainty': 'Exact source scope/qualifiers retained; no quantitative law or calendar conversion inferred.',
        'model_use': 'CONSTRAINT_ONLY', 'use_decision_ref': None, 'kernel_status': None,
        'unresolved_owner': None, 'required_action': None}


def build_overlay(package):
    """Consume a verified owner_inputs.species package; preserve every supplied fact."""
    d, entry, cat, schema = _package(package)
    refs = _registry(package)
    records, identities = [], []
    for join in entry['identity_records']:
        oid = join['organism_id']
        source = d[join['source_fact_artifact']]
        for part in join['json_pointer'].strip('/').split('/'):
            source = source[int(part)] if type(source) is list else source[part]
        if source.get('id', source.get('organism_id')) != join['source_id'] and source.get('organism_id') != oid:
            raise ValueError('source fact identity join mismatch')
        local = []
        if join['kind'] == 'PLANT':
            for i, fact in enumerate(source['facts']):
                if fact['field'] not in _PLANT_MAP:
                    raise ValueError('unmapped owner plant fact')
                sr = [_source(refs, join['source_id'], fact['p'])]
                sr += [_source(refs, s['source_id'], s['p']) for s in fact.get('other_refs', [])]
                r = _record(schema, oid, oid + ':fact:' + str(i), _PLANT_MAP[fact['field']], fact, sr, fact['value'])
                # Preserve the raw predecessor row; change only its effective issue status.
                if fact['field'] == 'universal_host_dependency':
                    r.update(assertion_state='UNKNOWN', value=None, kernel_status='UNKNOWN',
                        model_use='WITHHELD', unresolved_owner=d[HS4]['unresolved']['next_owner'],
                        required_action=d[HS4]['unresolved']['next_action'],
                        evidence='Owner resolved earlier CONFLICT wording to UNKNOWN scope/energy allocation; not host-free viability.')
                    r['source_refs'].append(_bound_ref(package, HS4, '/unresolved'))
                local.append(r)
            quantities = source['quantities']
            unknowns = source['unknowns']
        else:
            for key, field in _PRIMARY_MAP.items():
                fact = source[key]
                if join['kind'] == 'OTHER' and field.startswith('animal.'):
                    field = 'natural_history.observation'
                local.append(_record(schema, oid, oid + ':' + key, field, fact,
                    [_source(refs, fact['source_id'], fact['source_paragraphs'], fact['status'])], fact['statement']))
            quantities = source['quantitative_biology']
            unknowns = source['specific_unknown_fields']
        for i, fact in enumerate(quantities):
            sr = [_source(refs, fact.get('source_id', join['source_id']), fact.get('p', fact.get('source_paragraphs')), fact.get('status'))]
            sr += [_source(refs, s['source_id'], s['p']) for s in fact.get('other_refs', [])]
            local.append(_record(schema, oid, oid + ':quantity:' + str(i), 'natural_history.observation',
                fact, sr, 'Natural-history quantity only: ' + fact['field'] + '; preserve exact unit, comparator and process.'))
        records.extend(local)
        identities.append({'organism_id': oid, 'kind': join['kind'],
            'applicability': cat['identities'][oid]['applicability'],
            'record_ids': [r['record_id'] for r in local],
            'source_fact_record': deepcopy(source),
            'source_binding': _bound_ref(package, join['source_fact_artifact'], join['json_pointer']),
            'unresolved_inputs': deepcopy(unknowns),
            'quantitative_model_status': 'UNKNOWN',
            'population_reference': deepcopy(source.get('population_reference')),
            'population_reference_policy': 'Existing Population-owner records unchanged; this delivery supplies no replacement totals.'})
    # Source-established special zero is meaningful; it is not a missing-value default.
    wild = _record(schema, 'HS19', 'HS19:absent_wild', 'special.wild_count', 0,
        [_bound_ref(package, CATALOGUE, '/identities/HS19'), _source(refs, 'HS19_primary', [63, 68, 69, 70, 71])],
        'Exactly one continuous organism, no separate wild population; incorporated persons are not animal count.')
    wild['unit'] = 'wild organism identities'
    records.append(wild)
    for oid, fact_key in (('HS4', 'growth_and_dormancy'),
                         ('bannerhaus_cloud_kelp', 'habitat_and_attachment')):
        fact = next(r for r in records if r['organism_id'] == oid and r['value'] and
            type(r['value']) is dict and r['value'].get('field') == fact_key)
        movement = _record(schema, oid, oid + ':adult_movement', 'movement.mode', 'NONMOVING',
            deepcopy(fact['source_refs']), 'Explicit rooted attached adult; no bodily migration. Propagules and local growth separate.')
        movement['context']['life_stage'] = 'ADULT'
        records.append(movement)
    for identity in identities:
        identity['record_ids'] = [r['record_id'] for r in records if r['organism_id'] == identity['organism_id']]
    validation = validate_records(package, records)
    hs4 = deepcopy(d[HS4])
    hs4['effective_selection'] = None
    hs4['decision_binding'] = _bound_ref(package, HS4, '/conditional_model')
    output = {'schema': 'diadem.r11.source-aware-biology.v1', 'status': 'WORKING NON-CANON',
        'delivery_manifest_sha256': package['manifest_sha256'], 'delivery_entry_sha256': package['entry_sha256'],
        'input_content_sha256': _hash(package), 'identities': identities, 'field_records': records,
        'field_catalogue': deepcopy(cat['field_catalog']), 'minimum_profiles': deepcopy(cat['minimum_profiles']),
        'validation': validation, 'permitted_unselected_scenarios': deepcopy(entry['permitted_unselected_scenarios']),
        'hs4': hs4, 'special': {'HS14': {'branch': 'NONSPATIAL_EVENT', 'dated_register': None,
            'status': 'UNKNOWN', 'required': 'Dated current present non-Stagnated identity/event register; no density.'},
            'HS19': {'branch': 'ABSENT_WILD', 'wild_organism_count': 0, 'continuous_organism_count': 1,
                'incorporated_persons_are_organisms': False, 'geometry_and_mass': None,
                'source_record_id': 'HS19:absent_wild'}},
        'limits': ['Source facts are not selected numerical calibration or canon adoption.',
            'No new total, occurrence, density, growth, recruitment or movement is inferred.',
            'Native linear/area/volume supports stay separate; no automatic PFT or calendar mapping.']}
    output['overlay_sha256'] = _hash(output)
    return output


def _overlay(overlay):
    _json(overlay)
    body = {k: v for k, v in overlay.items() if k != 'overlay_sha256'}
    if _hash(body) != overlay['overlay_sha256']:
        raise ValueError('biology overlay mutated')
    return {r['organism_id']: r for r in overlay['identities']}


def hs4_host_access(overlay, *, selection=None, usable_connection=None,
                    sufficient_vascular_supply=None, evidence=None):
    """Three-valued AND on the explicitly activated host-fed prerequisite ONLY."""
    _overlay(overlay)
    for v in (usable_connection, sufficient_vascular_supply):
        if v is not None and type(v) is not bool:
            raise ValueError('host predicates must be true, false or null')
    if selection not in (None, PATHWAY):
        raise ValueError('unrecognised HS4 branch')
    if selection is None:
        if usable_connection is not None or sufficient_vascular_supply is not None:
            raise ValueError('host observation requires explicit pathway selection')
        result, state = None, 'PERMITTED_UNSELECTED'
    else:
        _text(evidence, 'evidenced or expressly declared pathway')
        result = False if False in (usable_connection, sufficient_vascular_supply) else (
            True if usable_connection is True and sufficient_vascular_supply is True else None)
        state = 'UNKNOWN' if result is None else 'HOST_ACCESS_PREREQUISITE_EVALUATED'
    return {'pathway_id': PATHWAY, 'selection': selection, 'status': state,
        'host_access_prerequisite': result, 'whole_organism_persistence': None,
        'whole_organism_recruitment': None, 'host_free_viability': None,
        'universal_host_necessity': None, 'evidence': evidence,
        'source_ref': deepcopy(overlay['hs4']['decision_binding']),
        'scope': 'Host-fed pathway only; no total-stock, density, death or production inference.'}


# Explicit source-by-source categorical joins, not text mining or numerical laws.
# (organism, fact-key, life-stage, natural/managed scope, required predicates, result)
_SEASON_RULES = (
    ('bannerhaus_aurblatt', 'phenology_and_litter', 'LEAVES', None, ('spring',), 'Spring leaf metallisation develops with sap flow.'),
    ('bannerhaus_aurblatt', 'phenology_and_litter', 'LEAVES', None, ('autumn',), 'Autumn leaf drying/fall; window and material flux UNKNOWN.'),
    ('bannerhaus_mistchimes_nebelglockchen', 'phenology', 'FLOWERING', None, ('fog_pattern_change',), 'Bloom cycles follow fog; direction, delay and rate UNKNOWN.'),
    ('bannerhaus_mistleholly_berries', 'cultivated_fruiting', 'MATURE_CROWN', 'MANAGED', ('mature_cultivated_crown',), 'Year-round overlapping flowering/ripening cohorts; not equal monthly yield.'),
    ('bannerhaus_periwinkle_vine', 'phenology_and_longevity', 'ADULT', None, ('winter',), 'No obligatory winter dormancy; growth remains conditional on temperature/moisture/light.'),
    ('bannerhaus_periwinkle_vine', 'water_and_drought', 'ADULT', None, ('drought',), 'Progressive stomatal closure and reduced growth/flowering; severity/rates UNKNOWN.'),
    ('bannerhaus_dandeblooms', 'release_phenology', 'MATURE_CLOCK', None, ('warm_midsummer_wind', 'mature_clock'), 'Source-favoured clonal release conditions; release rate and establishment UNKNOWN.'),
    ('HS4', 'growth_and_dormancy', 'NODES', None, ('wet_period',), 'Wet periods favour increased active node growth; whole-organism growth rate UNKNOWN.'),
    ('HS4', 'growth_and_dormancy', 'NODES', None, ('dry_period',), 'Node senescence/retraction/dormancy; not whole-organism death or universal winter dormancy.'),
    ('HS3', 'seasonal_residence', 'BREEDING_ADULT', None, ('warm_wet_period',), 'Breeding generally tracks local warm wet period; recruitment rate UNKNOWN.'),
    ('HS9', 'seasonal_residence', 'ADULT', None, ('winter',), 'Most winter adults cluster in warm corridors; no all-caste emissary cold tolerance.'),
    ('HS9', 'seasonal_residence', 'ADULT', None, ('low_stores',), 'Low stores induce torpor; no quantitative threshold/duration supplied.'),
    ('HS12', 'seasonal_residence', 'ADULT', None, ('hard_freeze',), 'Adults burrow below worst frost and reduce activity; prolonged cold still disadvantageous.'),
    ('HS12', 'seasonal_residence', 'BREEDING_ADULT', None, ('warm_rain',), 'Warm rains start breeding; successful recruitment and rate UNKNOWN.'),
    ('HS17', 'seasonal_residence', 'ADULT', 'NATURAL', ('winter', 'herd_uses_elevational_movement'), 'This explicitly identified elevational herd uses lower winter browse; no endpoint weights/budget inferred.'),
    ('HS17', 'seasonal_residence', 'ADULT', 'NATURAL', ('summer', 'herd_uses_elevational_movement'), 'This explicitly identified elevational herd uses summer slopes; no endpoint weights/budget inferred.'),
)


def compare_seasons(overlay, *, organism_id, support, phases):
    """Join explicitly evidenced phase predicates to applicable owner fact constraints.

    Support/season labels come from the caller; no weather threshold is invented.
    False means rule not triggered, never unsuitable habitat or zero abundance.
    """
    ids = _overlay(overlay)
    if organism_id not in ids:
        raise ValueError('unknown biological identity')
    _json(support)
    required = {'support_id', 'native_measure_unit', 'native_measure', 'scope_id',
        'cohort_id', 'life_stage', 'natural_or_managed', 'physical_scenario_id', 'calendar_id', 'source_evidence'}
    if set(support) != required:
        raise ValueError('explicit native biological support required')
    for key in required - {'native_measure'}:
        _text(support[key], key)
    if support['native_measure_unit'] not in ('m', 'm2', 'm3'):
        raise ValueError('native support cannot be silently projected')
    if _number(support['native_measure'], 'native measure') <= 0:
        raise ValueError('positive native measure required')
    if support['natural_or_managed'] not in ('NATURAL', 'MANAGED'):
        raise ValueError('explicit natural/managed applicability required')
    if ids[organism_id]['applicability'] != 'SPATIAL':
        raise ValueError('special identity uses its event/one-organism branch, not seasonal spatial comparison')
    if type(phases) is not list or not 2 <= len(phases) <= 366:
        raise ValueError('two or more bounded phases required')
    rules = [r for r in _SEASON_RULES if r[0] == organism_id and r[2] == support['life_stage']
        and r[3] in (None, support['natural_or_managed'])]
    rows, seen = [], set()
    for phase in phases:
        if set(phase) != {'phase_id', 'start_seconds', 'duration_seconds', 'predicates', 'evidence'}:
            raise ValueError('phase fields differ')
        pid = _text(phase['phase_id'], 'phase_id')
        if pid in seen:
            raise ValueError('duplicate season phase')
        seen.add(pid)
        start = _number(phase['start_seconds'], 'phase start')
        duration = _number(phase['duration_seconds'], 'phase duration')
        if duration <= 0 or (rows and start < last_end):
            raise ValueError('positive nonoverlapping ordered phases required')
        last_end = start + duration
        _text(phase['evidence'], 'phase evidence')
        predicates = phase['predicates']
        if type(predicates) is not dict or any(type(v) is not bool and v is not None for v in predicates.values()):
            raise ValueError('evidenced categorical predicates must be true/false/null')
        for a, b in (('wet_period', 'dry_period'), ('winter', 'summer'), ('spring', 'autumn')):
            if predicates.get(a) is True and predicates.get(b) is True:
                raise ValueError('contradictory phase predicates')
        results = []
        for _, key, _, _, needed, response in rules:
            fact = next((r for r in overlay['field_records'] if r['organism_id'] == organism_id and type(r['value']) is dict and
                (r['value'].get('field') == key or r['record_id'] == organism_id + ':' + key)), None)
            if fact is None:
                raise ValueError('categorical rule has no matching delivered fact')
            vals = [predicates.get(k) for k in needed]
            applies = False if False in vals else (True if all(v is True for v in vals) else None)
            results.append({'source_record_id': fact['record_id'], 'required_predicates': list(needed),
                'triggered': applies, 'response': response if applies is True else None,
                'status': 'SOURCE_CONDITION_JOIN' if applies is True else ('NOT_TRIGGERED' if applies is False else 'UNKNOWN'),
                'source_refs': deepcopy(fact['source_refs'])})
        rows.append({'phase_id': pid, 'start_seconds': str(start), 'duration_seconds': str(duration),
            'predicate_evidence': phase['evidence'], 'predicates': deepcopy(predicates),
            'categorical_responses': results, 'quantitative_activity': None,
            'quantitative_abundance': None, 'quantitative_productivity': None})
    # Information becoming known is not evidence that the biology changed.
    columns = [[r['categorical_responses'][i]['triggered'] for r in rows] for i in range(len(rules))]
    definite_change = any(True in col and False in col for col in columns)
    has_unknown = any(v is None for col in columns for v in col)
    changed = True if definite_change else (None if not rules or has_unknown else False)
    return {'schema': 'diadem.r11.biological-season-comparison.v1', 'organism_id': organism_id,
        'support': deepcopy(support), 'phases': rows,
        'categorical_response_changed': changed,
        'applicable_rule_count': len(rules), 'source_fact_record': deepcopy(ids[organism_id]['source_fact_record']),
        'status': 'PARTIAL_SOURCE_CONSTRAINTS' if rules else 'SOURCE_FACTS_PRESENT_NO_EXECUTABLE_SEASONAL_RULE',
        'quantitative_status': 'UNKNOWN', 'input_sha256': _hash({'overlay': overlay['overlay_sha256'],
            'organism_id': organism_id, 'support': support, 'phases': phases}),
        'limits': 'Categorical joins only; no numerical thresholds, equal seasonal production, population change or range map inferred.'}


def declared_native_density(package, records, *, support, basis):
    """Dimension-preserving density arithmetic for separately selected field records.

    No supplied delivery record currently selects this numerical route. This is a
    successor adapter, not a selection of the historical owner parameter menu.
    """
    validate_records(package, records)
    needed = {'density.value'}
    if basis in ('PER_HABITAT_MEASURE', 'PER_OCCUPIED_MEASURE'):
        needed.add('habitat.habitat_fraction')
    if basis == 'PER_OCCUPIED_MEASURE':
        needed.add('density.occupied_fraction')
    if basis not in ('PER_WHOLE_CELL_MEASURE', 'PER_HABITAT_MEASURE', 'PER_OCCUPIED_MEASURE'):
        raise ValueError('explicit density denominator basis required')
    byfield = {r['field_id']: r for r in records}
    if len(byfield) != len(records) or set(byfield) != needed:
        raise ValueError('exact conditional minimum density profile required')
    if any(r['model_use'] != 'SELECTED_FOR_R11' or r['value'] is None for r in records):
        return {'status': 'UNKNOWN', 'expected_entities': None, 'reason': 'Complete selected joint density profile absent.'}
    first = records[0]
    if any(r['organism_id'] != first['organism_id'] or r['context'] != first['context'] for r in records):
        raise ValueError('density records must share exact joint cohort/support/season/scenario')
    if set(support) != {'support_id', 'native_measure_unit', 'native_measure', 'evidence'}:
        raise ValueError('explicit geometry support required')
    _text(support['evidence'], 'physical geometry evidence')
    if support['support_id'] != first['context']['support_id'] or support['native_measure_unit'] != first['context']['native_measure_unit']:
        raise ValueError('density and actual native geometry differ')
    measure = _number(support['native_measure'], 'native physical measure')
    amount = measure * _number(byfield['density.value']['value'], 'density')
    for field in needed - {'density.value'}:
        amount *= _number(byfield[field]['value'], field)
    return {'status': 'SELECTED_WORKING_ARITHMETIC_NOT_CALIBRATION', 'expected_entities': str(amount),
        'counting_unit': first['context']['counting_unit'], 'native_measure_unit': support['native_measure_unit'],
        'density_basis': basis, 'context': deepcopy(first['context']), 'record_ids': [r['record_id'] for r in records],
        'source_refs': [deepcopy(s) for r in records for s in r['source_refs']],
        'support': deepcopy(support)}
