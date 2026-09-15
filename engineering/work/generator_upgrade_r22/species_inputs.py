"""Actual approved R22 source quantities with narrowly typed numerical uses.

Source intervals stay intervals and historical scenario columns stay unselected.
An executable unit conversion does not select a biological law or geography.
"""
from copy import deepcopy
from fractions import Fraction as F
from functools import lru_cache
import json
from pathlib import Path

from .species import _checked, _q, _text, digest

PATH = Path(r'C:\Users\LOCAL_USER\Documents\The Diadem - Local Workspace\02_Working_Files\Species_Coordination\Generator_R22_Inputs_2026-09-14\SPECIES_NUMERICAL_REGISTER_R1.json')
SHA256 = 'decfab605c33371eb7aebe617af21483a2fc29b1ed8d13196cedeca20a3e3f1a'
SCHEMA = 'diadem.species.numerical-register.v1'
HISTORICAL = 'HISTORICAL_UNSELECTED_SCENARIO'
UNITS = {
    'km/source hour': ('m/s', 'hour', F(1000), -1),
    'kg food/adult/source day': ('kg source food/adult/s', 'day', F(1), -1),
    'small clutch/sole Kronweberin/source week': ('small clutch/sole Kronweberin/s', 'week', F(1), -1),
    'viable eggs/legacy model year': ('viable eggs/s', 'legacy_model_year', F(1), -1),
    'source years': ('s', 'year', F(1), 1),
    'source days': ('s', 'day', F(1), 1),
    'tonnes usable grain/hectare annually harvested stand': ('kg usable grain/m2 annually harvested stand', None, F(1,10), 0),
}
SPEEDS = {
    'HS6:maintained_gardenway_speed:1': 'MAINTAINED_HUMID_GARDENWAY',
    'HS6:prepared_downhill_ramp_speed:2': 'PREPARED_MOIST_DOWNHILL_RAMP',
    'HS9:short_aerial_speed:6': 'BRIEF_AERIAL_STAGE_WITH_RESTING_POINTS',
}


@lru_cache(maxsize=1)
def _expected_register_digest():
    # Immutable expected identity comes only from the exact approved bytes;
    # no caller-supplied document or cached mutable dictionary can set it.
    return digest(json.loads(_checked(PATH, SHA256)))


def _bound_register(register):
    if digest(register) != _expected_register_digest():
        raise ValueError('species register quantities or effective overrides changed')


def _number(value):
    # Author-written JSON decimal values keep their decimal meaning here.
    return _q(str(value) if type(value) is float else value)


def _positive(value):
    result = _number(value)
    if result <= 0: raise ValueError('positive declared quantity required')
    return result


def _calendar(value):
    if type(value) is not dict or type(value.get('source_time_seconds')) is not dict:
        raise ValueError('explicit source-to-model calendar binding required')
    _text(value.get('calendar_id'), 'calendar identity'); _text(value.get('evidence'), 'calendar evidence')
    for key, seconds in value['source_time_seconds'].items():
        _text(key, 'source time name'); _positive(seconds)
    return value['source_time_seconds']


def load():
    document = json.loads(_checked(PATH, SHA256))
    if document.get('schema') != SCHEMA: raise ValueError('exact delivered species register required')
    quantities = document['quantities']; taxa = document['taxa']
    if (len(quantities) != 200 or len(taxa) != 36 or sum(t['kind']=='PLANT' for t in taxa) != 17
            or len({q['id'] for q in quantities}) != 200
            or sum(q['classification']==HISTORICAL for q in quantities) != 73):
        raise ValueError('bounded owner register identity/coverage changed')
    ids = {t['organism_id'] for t in taxa}
    if len(ids) != 36 or any(q['organism_id'] not in ids for q in quantities):
        raise ValueError('species identity join differs')
    for row in quantities:
        if any(ref['id'] not in document['source_registry'] for ref in row['source_refs']):
            raise ValueError('quantity source binding missing')
    return document


def effective_taxon(register, organism_id):
    _bound_register(register)
    row = next((t for t in register['taxa'] if t['organism_id']==organism_id), None)
    if row is None: raise ValueError('unknown registered organism')
    overrides = [deepcopy(r) for r in register['effective_overrides'] if r['organism_id']==organism_id]
    pending = deepcopy(row.get('specific_remaining_biology', []))
    # This exact unresolved predecessor field is explicitly superseded. Other
    # timing, incubation and mortality gaps remain; original facts are retained.
    if organism_id == 'HS5': pending = [x for x in pending if x != 'Queen clutch frequency']
    return {'organism_id': organism_id, 'original_taxon': deepcopy(row),
        'controlling_overrides': overrides, 'effective_remaining_biology': pending,
        'remaining_operational_fields': deepcopy(row['remaining_operational_fields']),
        'precedence': 'APPLY_CONTROLLING_OVERRIDES_BEFORE_ORIGINAL_FACTS', 'register_sha256': SHA256}


def quantity(register, quantity_id, *, target_unit=None, source_time_seconds=None):
    """Preserve typed values and source qualifiers; no default scalar selection."""
    _bound_register(register)
    row = next((r for r in register['quantities'] if r['id']==quantity_id), None)
    if row is None: raise ValueError('unknown exact quantity identity')
    refs = []
    for ref in row['source_refs']:
        bound = register['source_registry'][ref['id']]
        _checked(bound['path'], bound['sha256'])
        refs.append({**deepcopy(ref), **deepcopy(bound)})
    source = row['quantity']; raw = source.get('values', source.get('value'))
    values = raw if type(raw) is list else [raw]
    try: exact = tuple(_number(v) for v in values)
    except ValueError: exact = None
    unit = source.get('unit'); converted = exact
    if target_unit is not None and target_unit != unit:
        if unit not in UNITS or UNITS[unit][0] != target_unit:
            raise ValueError('no supported semantic/unit conversion; quantity meaning cannot change')
        output, period, scale, exponent = UNITS[unit]
        if period is not None:
            if source_time_seconds is None or period not in source_time_seconds:
                raise ValueError('missing explicit source '+period+' duration; no implicit Earth/legacy clock')
            scale *= _positive(source_time_seconds[period])**exponent
        if exact is None: raise ValueError('descriptive quantity cannot become numeric')
        converted = tuple(v*scale for v in exact); unit = output
    historical = row['classification']==HISTORICAL
    return {'quantity_id': quantity_id, 'organism_id': row['organism_id'], 'field': row['field'],
        'status': 'AVAILABLE_UNSELECTED' if historical else 'TYPED_SOURCE_QUANTITY' if exact is not None else 'DESCRIPTIVE_QUANTITY',
        'values_exact': None if converted is None else [str(v) for v in converted], 'unit': unit,
        'shape': 'JOINT_SOURCE_COLUMNS' if historical else 'LABELLED_SOURCE_SCENARIOS' if 'labels' in source else 'SOURCE_INTERVAL' if type(raw) is list else 'SOURCE_SCALAR',
        'labels': deepcopy(source.get('labels')), 'selected_value': None,
        'source_status': row['source_status'], 'classification': row['classification'],
        'source_refs': refs, 'applicability': row['applicability'], 'temporal_basis': row['temporal_basis'],
        'original_record': deepcopy(row), 'controlling_overrides': effective_taxon(register,row['organism_id'])['controlling_overrides'],
        'register_sha256': SHA256, 'source_time_seconds': deepcopy(source_time_seconds),
        'forbidden_inference': row.get('forbidden_inference')}


def _scalar(record):
    if record['status']=='AVAILABLE_UNSELECTED' or record['shape']!='SOURCE_SCALAR' or record['values_exact'] is None:
        raise ValueError('one applicable source scalar required; scenarios/ranges cannot be selected implicitly')
    return F(record['values_exact'][0])


def adult_food_demand(register, *, adult_entities, duration_seconds, calendar, application_evidence):
    """Ink Owl ordinary adult source-food mass interval, not edible dry matter."""
    clock = _calendar(calendar); _text(application_evidence, 'ordinary adult/cohort applicability evidence')
    record = quantity(register,'HS2:adult_food_demand:5',target_unit='kg source food/adult/s',source_time_seconds=clock)
    multiplier = _number(adult_entities)*_positive(duration_seconds)
    amounts = [str(F(v)*multiplier) for v in record['values_exact']]
    return {'schema': 'diadem.species-source-food-demand.r22', 'status': 'CONDITIONAL_SOURCE_INTERVAL',
        'organism_id':'HS2', 'life_stage':'ADULT', 'adult_entities':str(_number(adult_entities)),
        'duration_seconds':str(_positive(duration_seconds)), 'food_mass_kg_interval':amounts,
        'mass_basis':'SOURCE_FOOD_AS_STATED; MOISTURE_AND_EDIBLE_DRY_FRACTION_UNKNOWN',
        'activity':'ORDINARY_ACTIVITY', 'source_quantity':record, 'calendar':deepcopy(calendar),
        'application_evidence':application_evidence, 'selected_demand_kg':None,
        'limits':'Interval demand only; no population estimate, food supply, C/N/P composition or selected per-adult point rate.'}


def segment_travel_time(register, quantity_id, *, length_m, route_regime, calendar, application_evidence):
    """A caller-evidenced compatible segment; speed is never a movement budget."""
    if SPEEDS.get(quantity_id) != route_regime: raise ValueError('source-specific movement regime required')
    clock = _calendar(calendar); _text(application_evidence,'segment applicability evidence')
    record = quantity(register,quantity_id,target_unit='m/s',source_time_seconds=clock)
    length = _number(length_m); speeds = [F(v) for v in record['values_exact']]
    if any(v<=0 for v in speeds): raise ValueError('positive segment speed required')
    times = [length/v for v in speeds]
    return {'schema':'diadem.species-segment-time.r22','status':'CONDITIONAL_SOURCE_INTERVAL',
        'travel_time_seconds_interval':[str(min(times)),str(max(times))], 'source_speed_order_times':[str(v) for v in times],
        'length_m':str(length), 'route_regime':route_regime, 'source_quantity':record,
        'calendar':deepcopy(calendar),'application_evidence':application_evidence,
        'movement_budget':None, 'selected_edge_cost':None,
        'limits':'One compatible segment, excluding unprovided rests/delays; no daily range, dispersal kernel or stock movement inferred.'}


def ferrarachne_reference_cohort(register, *, laying_interval_seconds, calendar, application_evidence):
    """Existing sole-Queen average plus protected-nursery eventual cohort outcome.

    Event dates and the maturation-time distribution are not provided. Eventual
    functional adults are never inserted as same-interval successful recruits.
    """
    clock=_calendar(calendar); _text(application_evidence,'sole Queen/protected nursery applicability')
    frequency=quantity(register,'HS5:queen_mean_clutch_frequency:6',
        target_unit='small clutch/sole Kronweberin/s',source_time_seconds=clock)
    clutch=quantity(register,'HS5:reference_eggs_per_clutch:7')
    survival=quantity(register,'HS5:reference_egg_adult_survival:9')
    clutches=_scalar(frequency)*_positive(laying_interval_seconds)
    eggs=clutches*_scalar(clutch); eventual=eggs*_scalar(survival)
    return {'schema':'diadem.species-protected-nursery-cohort.r22','status':'EXISTING_WORKING_REFERENCE_COHORT',
        'organism_id':'HS5','sole_reproductive_queen_count':1,'mean_small_clutches':str(clutches),
        'viable_eggs':str(eggs),'eventual_functional_adults':str(eventual),
        'same_interval_successful_recruits':None,'selected_recruitment_rate_per_s':None,
        'maturation_schedule':'UNKNOWN; protected whole-juvenile-period survival, not immediate recruitment',
        'source_quantities':[frequency,clutch,survival],'calendar':deepcopy(calendar),
        'application_evidence':application_evidence,
        'limits':'Long-run mean and existing protected-nursery reference; no exact weekly events, new density, mortality law, current stock or annual calendar assumed.'}


def red_wheat_grain_account(register, *, scenario_label, annually_harvested_area_m2, application_evidence):
    """Use the exact selected existing grain-account scenario once per harvest year."""
    _text(application_evidence,'annual harvested-stand/account evidence')
    record=quantity(register,'bannerhaus_red_wheat_grass:usable_net_grain_yield:1',
        target_unit='kg usable grain/m2 annually harvested stand')
    if scenario_label not in record['labels']: raise ValueError('explicit existing grain-account scenario label required')
    index=record['labels'].index(scenario_label); yield_value=F(record['values_exact'][index])
    area=_number(annually_harvested_area_m2)
    return {'schema':'diadem.species-usable-grain-account.r22','status':'EXISTING_WORKING_REFERENCE_ACCOUNT',
        'scenario_label':scenario_label,'annually_harvested_area_m2':str(area),
        'usable_grain_kg':str(area*yield_value),'yield_kg_usable_grain_per_m2':str(yield_value),
        'source_quantity':record,'application_evidence':application_evidence,
        'potential_yield_kg_m2':None,'edible_dry_yield_kg_m2':None,'et_stress_applied':False,
        'limits':'One existing annual usable-grain account, not recovery footprint, crop water-response calibration, edible-dry harvest or twelve monthly crops.'}
