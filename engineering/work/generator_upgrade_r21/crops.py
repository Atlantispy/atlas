"""Whole-plot DAILY crop sequences using unchanged captured R1/R11 producers.

This wrapper adds clocks, finite delivered irrigation and continuous depletion;
it does not add crop coefficients, weather disaggregation or a new soil law.
Preview quantities are forecasts, never actual delivered-water/food inventory.
The caller authenticates water-source debits and applicability on this support.
"""
from copy import deepcopy
from fractions import Fraction as F
import json
import math

from . import _native_crop as agro, _native_human as human


SCHEMA = 'diadem.whole-plot-crop-sequence.r21'
REGIME = 'FIXED_ROOT_UNFROZEN_NONSALINE_WELL_DRAINED'
PLAN_FIELDS = {'plan_id', 'support_id', 'irrigation_sink_id', 'settlement_id',
    'area_m2', 'season_start_seconds', 'day_duration_seconds', 'root_zone',
    'initial_depletion_mm', 'application_efficiency', 'application_evidence',
    'daily_forcing', 'segments', 'evidence', 'source_status', 'regime', 'delivery_boundary'}
ROOT_FIELDS = set(agro.RootZone.__dataclass_fields__)
DAY_FIELDS = set(agro.DayForcing.__dataclass_fields__)
CROP_FIELDS = {'potential_yield_kg_m2', 'yield_response_factor',
               'minimum_valid_et_ratio', 'evidence', 'source_status'}
CONVERSION_FIELDS = {'mass_basis', 'carbon_fraction_dry_matter', 'edible_fraction',
    'processing_loss_fraction', 'food_quality_evidence', 'evidence_id',
    'source_status', 'edible_energy_kcal_kg'}
SEGMENT_FIELDS = {'segment_id', 'kind', 'start_day', 'stop_day', 'evidence', 'source_status'}
STATUSES = {'CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST', 'UNKNOWN', 'CONFLICT', 'INCOMPLETE'}
UNRESOLVED = {'UNKNOWN', 'CONFLICT', 'INCOMPLETE'}
FALLOW_MODELS = {'PRESCRIBED_COVER_SINGLE_COEFFICIENT', 'ZERO_ET_REFERENCE'}
MAX_BYTES = 8*1024*1024


def _keys(row, fields, name):
    if type(row) is not dict or set(row) != fields:
        raise ValueError(name+': exact fields required')


def _text(value, name):
    return human._id(value, name)


def _source(row, name):
    _text(row['evidence'], name+' evidence')
    if type(row['source_status']) is not str or row['source_status'] not in STATUSES:
        raise ValueError(name+': explicit source status required')


def _q(value, name, **kwargs):
    return human._q(value, name, **kwargs)


def _input_copy(value):
    # JSON-only input bounds also prevent a large unbounded copy before checks.
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError('bounded finite JSON crop inputs required') from error
    if len(raw.encode()) > MAX_BYTES:
        raise ValueError('crop input exceeds existing 8 MiB envelope')
    return json.loads(raw)


def _plan(value):
    plan = _input_copy(value)
    _keys(plan, PLAN_FIELDS, 'crop sequence')
    for key in ('plan_id', 'support_id', 'irrigation_sink_id', 'settlement_id',
                'application_evidence', 'regime', 'delivery_boundary'):
        _text(plan[key], key)
    _source(plan, 'crop sequence')
    _q(plan['area_m2'], 'whole-plot area', positive=True)
    _q(plan['season_start_seconds'], 'sequence start')
    _q(plan['day_duration_seconds'], 'explicit day seconds', positive=True)
    _q(plan['application_efficiency'], 'field application efficiency', positive=True, fraction=True)
    if plan['initial_depletion_mm'] is not None:
        agro.number(plan['initial_depletion_mm'], 'initial depletion')
    _keys(plan['root_zone'], ROOT_FIELDS, 'root zone')
    _source(plan['root_zone'], 'root zone')
    for key in ROOT_FIELDS-{'evidence', 'source_status'}:
        if plan['root_zone'][key] is not None:
            agro.number(plan['root_zone'][key], key, positive=key == 'rooting_depth_m')
    if (all(value is not None for value in plan['root_zone'].values())
            and plan['root_zone']['source_status'] not in UNRESOLVED):
        agro.RootZone(**plan['root_zone'])
    days = plan['daily_forcing']
    if type(days) is not list or not 1 <= len(days) <= 366:
        raise ValueError('1..366 supplied DAILY forcing rows required')
    for day in days:
        _keys(day, DAY_FIELDS, 'daily forcing')
        for key, number in day.items():
            if number is not None:
                agro.number(number, key)
        if all(number is not None for number in day.values()):
            agro.DayForcing(**day)
    segments = plan['segments']
    if type(segments) is not list or not 1 <= len(segments) <= len(days):
        raise ValueError('bounded complete crop/fallow segmentation required')
    previous, seen = 0, set()
    for segment in segments:
        if type(segment) is not dict or segment.get('kind') not in ('CROP', 'FALLOW'):
            raise ValueError('explicit CROP or FALLOW segment required')
        extra = {'crop_parameters', 'conversion', 'commodity_id'} if segment['kind'] == 'CROP' else {'evaporation_model'}
        _keys(segment, SEGMENT_FIELDS | extra, 'segment')
        ident = _text(segment['segment_id'], 'segment ID')
        if ident in seen:
            raise ValueError('duplicate crop/fallow segment ID')
        seen.add(ident)
        a, b = segment['start_day'], segment['stop_day']
        if type(a) is not int or type(b) is not int or a != previous or not a < b <= len(days):
            raise ValueError('segments must cover all supplied days once, contiguously')
        previous = b
        _source(segment, 'segment')
        if segment['kind'] == 'FALLOW':
            _text(segment['evaporation_model'], 'explicit fallow evaporation model')
            continue
        _text(segment['commodity_id'], 'crop commodity')
        parameters, conversion = segment['crop_parameters'], segment['conversion']
        _keys(parameters, CROP_FIELDS, 'crop parameters')
        _source(parameters, 'crop parameters')
        for key in ('potential_yield_kg_m2', 'yield_response_factor', 'minimum_valid_et_ratio'):
            if parameters[key] is not None:
                agro.number(parameters[key], key)
        if parameters['minimum_valid_et_ratio'] is not None and parameters['minimum_valid_et_ratio'] > 1:
            raise ValueError('crop ET applicability ratio exceeds one')
        _keys(conversion, CONVERSION_FIELDS, 'food conversion')
        if conversion['mass_basis'] != 'EDIBLE_DRY_FOOD_KG':
            raise ValueError('explicit edible dry food mass basis required')
        for key in ('food_quality_evidence', 'evidence_id'):
            _text(conversion[key], key)
        if type(conversion['source_status']) is not str or conversion['source_status'] not in STATUSES:
            raise ValueError('conversion source status required')
        for key in ('carbon_fraction_dry_matter', 'edible_fraction', 'processing_loss_fraction', 'edible_energy_kcal_kg'):
            if conversion[key] is not None:
                _q(conversion[key], key, positive=key == 'carbon_fraction_dry_matter',
                   fraction=key != 'edible_energy_kcal_kg')
    if previous != len(days):
        raise ValueError('crop/fallow segments leave an unmodelled water interval')
    return plan


def _unknowns(value, path='plan'):
    if value is None:
        return [path]
    if type(value) is dict:
        found = [path+'.source_status'] if value.get('source_status') in UNRESOLVED else []
        for key, item in value.items():
            found.extend(_unknowns(item, path+'.'+key))
        return found
    if type(value) is list:
        return [reason for index, item in enumerate(value) for reason in _unknowns(item, path+f'[{index}]')]
    return []


def _demands(plan):
    area = _q(plan['area_m2'], 'area', positive=True)
    efficiency = _q(plan['application_efficiency'], 'efficiency', positive=True, fraction=True)
    start, duration = F(plan['season_start_seconds']), F(plan['day_duration_seconds'])
    rows = []
    for index, day in enumerate(plan['daily_forcing']):
        net = _q(_q(day['net_irrigation_mm'], 'daily net irrigation')*area/1000, 'daily root-zone volume')
        gross = _q(net/efficiency, 'daily inlet irrigation')
        rows.append({'day_index': index, 'available_at_seconds': str(_q(start+index*duration, 'daily start')),
                     'gross_delivery_m3': str(gross), 'net_root_zone_m3': str(net),
                     'application_loss_m3': str(gross-net)})
    return rows


def _deliveries(plan, values, demands, *, allow_shortfall=False):
    values = _input_copy(values)
    keyed = human._rows(values, 'allocation_id', 'actual irrigation deliveries', 4096)
    seen, gross, applied = set(), [F(0)]*len(demands), [F(0)]*len(demands)
    by_day = [[] for _ in demands]
    expected_efficiency = _q(plan['application_efficiency'], 'efficiency', positive=True, fraction=True)
    for row in keyed.values():
        human._source(row)
        ident = _text(row.get('delivery_id'), 'actual irrigation delivery ID')
        if ident in seen:
            raise ValueError('terminal irrigation delivery reused under another allocation')
        seen.add(ident)
        if (row.get('kind') != 'ROUTED_WITHDRAWAL_DELIVERY' or row.get('status') != 'MODELLED'
                or row.get('hypothetical') or row.get('preview_only')):
            raise ValueError('actual predebited terminal irrigation required, not a preview/request')
        if row.get('support_id') != plan['support_id'] or row.get('receiving_sink_id') != plan['irrigation_sink_id']:
            raise ValueError('irrigation physical support/sink mismatch')
        if row.get('delivery_boundary') != 'ROOT_ZONE_NET':
            raise ValueError('reduced crop producer requires declared ROOT_ZONE_NET delivery, not surface application')
        human._sha(row.get('source_input_sha256'))
        day = row.get('day_index')
        if type(day) is not int or not 0 <= day < len(demands):
            raise ValueError('actual irrigation needs global zero-based day_index')
        if _q(row.get('available_after_seconds'), 'delivery time') > F(demands[day]['available_at_seconds']):
            raise ValueError('irrigation cannot be used before its terminal delivery')
        volume = _q(row.get('delivered_volume_m3'), 'actual field-inlet delivery')
        efficiency = _q(row.get('application_efficiency'), 'actual application efficiency', fraction=True)
        if efficiency != expected_efficiency or row.get('application_evidence') != plan['application_evidence']:
            raise ValueError('irrigation application law differs from the explicit plan')
        gross[day] = _q(gross[day]+volume, 'summed actual daily gross irrigation')
        applied[day] = _q(applied[day]+volume*efficiency, 'summed actual daily root-zone irrigation')
        by_day[day].append(row)
    for day, demand in enumerate(demands):
        if allow_shortfall:
            if gross[day] > F(demand['gross_delivery_m3']) or applied[day] > F(demand['net_root_zone_m3']):
                raise ValueError('actual irrigation exceeds the fixed planted plan request')
        elif gross[day] != F(demand['gross_delivery_m3']) or applied[day] != F(demand['net_root_zone_m3']):
            raise ValueError('actual daily gross/net irrigation differs from planned delivered schedule')
    return values, by_day


def _run(plan, deliveries, *, preview_only):
    plan = _plan(plan)
    result = {'schema': SCHEMA, 'mode': 'PREVIEW' if preview_only else 'EXECUTE',
        'quantity_role': 'HYPOTHETICAL_NOT_DELIVERED' if preview_only else 'ACTUAL_DELIVERY_BOUND',
        'plan_id': plan['plan_id'], 'plan_sha256': human.digest(plan),
        'delivery_boundary': plan['delivery_boundary'],
        'source_status': 'WORKING NON-CANON', 'input_source_status': plan['source_status'],
        'evidence': plan['evidence'], 'status': None, 'reasons': [],
        'daily_demands': [], 'segments': [], 'harvests': [], 'forecasts': [],
        'irrigation_allocation_ids': [], 'irrigation_delivery_ids': [],
        'irrigation_deliveries': [], 'final_depletion_mm': None,
        'total_edible_dry_kg': None, 'total_edible_energy_kcal': None,
        'scope': 'supplied DAILY fixed-root covered-crop water/Ky scenarios; no source-debit authentication, new soil law or automatic phenology'}
    unknown = _unknowns(plan)
    if unknown:
        return {**result, 'status': 'UNKNOWN', 'reasons': unknown}
    reasons = []
    if plan['regime'] != REGIME:
        reasons.append('unsupported crop/root-zone regime')
    if plan['delivery_boundary'] != 'ROOT_ZONE_NET':
        reasons.append('reduced R1 bucket requires ROOT_ZONE_NET; surface application needs an infiltration-owning soil model')
    for segment in plan['segments']:
        if segment['kind'] == 'FALLOW':
            mode = segment['evaporation_model']
            if mode not in FALLOW_MODELS:
                reasons.append(segment['segment_id']+': unsupported fallow evaporation law')
            elif mode == 'ZERO_ET_REFERENCE' and any(day['potential_crop_et_mm'] != 0 for day in
                    plan['daily_forcing'][segment['start_day']:segment['stop_day']]):
                reasons.append(segment['segment_id']+': ZERO_ET_REFERENCE has nonzero supplied ET')
    if reasons:
        return {**result, 'status': 'OUTSIDE_REGIME', 'reasons': reasons}
    root = agro.RootZone(**plan['root_zone'])
    agro.stress_coefficient(root, plan['initial_depletion_mm'])
    demands = _demands(plan)
    result['daily_demands'] = demands
    by_day = [[] for _ in demands]
    if not preview_only:
        actual, by_day = _deliveries(plan, deliveries, demands)
        result.update(irrigation_deliveries=actual,
            irrigation_allocation_ids=sorted(row['allocation_id'] for row in actual),
            irrigation_delivery_ids=sorted(row['delivery_id'] for row in actual))
    depletion = plan['initial_depletion_mm']
    start, day_seconds = F(plan['season_start_seconds']), F(plan['day_duration_seconds'])
    total_food, total_energy, statuses = F(0), F(0), []
    all_water_rows = []
    for segment in plan['segments']:
        a, b = segment['start_day'], segment['stop_day']
        daily = deepcopy(plan['daily_forcing'][a:b])
        record = {'segment_id': segment['segment_id'], 'kind': segment['kind'],
            'start_day': a, 'stop_day': b, 'initial_depletion_mm': depletion,
            'start_seconds': str(start+a*day_seconds), 'end_seconds': str(start+b*day_seconds)}
        if segment['kind'] == 'FALLOW':
            water = agro.water_balance(root, [agro.DayForcing(**day) for day in daily], initial_depletion_mm=depletion)
            record.update(status='MODELLED', water=water, evaporation_model=segment['evaporation_model'])
        else:
            parameters = dict(segment['crop_parameters'], initial_depletion_mm=depletion)
            conversion = deepcopy(segment['conversion'])
            energy_density = _q(conversion.pop('edible_energy_kcal_kg'), 'edible food energy')
            if preview_only:
                crop = agro.crop_season(root, [agro.DayForcing(**day) for day in daily], **parameters)
                harvest = None
            else:
                local_deliveries = []
                for global_day in range(a, b):
                    for row in by_day[global_day]:
                        local_deliveries.append(dict(row, day_index=global_day-a))
                parameters.update(yield_mass_basis='DRY_HARVEST_KG',
                    irrigation_deliveries=local_deliveries, day_duration_seconds=str(day_seconds),
                    season_start_seconds=str(start+a*day_seconds), irrigation_sink_id=plan['irrigation_sink_id'])
                ident = human.digest({'support': plan['support_id'], 'plan_id': plan['plan_id'],
                    'segment_id': segment['segment_id'], 'start': str(start+a*day_seconds), 'end': str(start+b*day_seconds)})
                native = human.harvest_from_crop(agro, root_zone=plan['root_zone'], daily_forcing=daily,
                    crop_parameters=parameters, area_m2=plan['area_m2'], conversion=conversion,
                    harvest_id='crop-'+ident, settlement_id=plan['settlement_id'], commodity_id=segment['commodity_id'],
                    support_id=plan['support_id'], event_id=segment['segment_id'], source_use_id='crop-use-'+ident,
                    available_at_seconds=str(start+b*day_seconds))
                crop, harvest = native['crop'], native.get('harvest')
            water = crop['water']
            record.update(status=crop['status'], crop=crop)
            if crop['status'] == 'MODELLED':
                food = _q(F(crop['yield_kg_m2'])*F(plan['area_m2'])*F(conversion['edible_fraction'])*
                    (1-F(conversion['processing_loss_fraction'])), 'edible dry food')
                energy = _q(food*energy_density, 'harvest energy')
                if harvest is not None:
                    if F(harvest['quantity_kg']) != food:
                        raise ArithmeticError('native edible dry conversion differs')
                    harvest.update(edible_energy_kcal=str(energy), segment_id=segment['segment_id'])
                    result['harvests'].append(harvest)
                else:
                    result['forecasts'].append({'segment_id': segment['segment_id'],
                        'quantity_role': 'HYPOTHETICAL_NOT_DELIVERED', 'edible_dry_kg': str(food),
                        'edible_energy_kcal': str(energy), 'available_after_seconds': str(start+b*day_seconds)})
                record.update(edible_dry_kg=str(food), edible_energy_kcal=str(energy))
                total_food = _q(total_food+food, 'sequence edible dry food')
                total_energy = _q(total_energy+energy, 'sequence edible energy')
        depletion = water['final_depletion_mm']
        record['final_depletion_mm'] = depletion
        all_water_rows.extend(dict(row, day=a+index+1) for index, row in enumerate(water['rows']))
        result['segments'].append(record); statuses.append(record['status'])
    status = 'UNKNOWN' if 'UNKNOWN' in statuses else 'OUTSIDE_REGIME' if 'OUTSIDE_REGIME' in statuses else 'MODELLED'
    taw = root.available_water_mm
    inflow = math.fsum(row['inflow_mm'] for row in all_water_rows)
    et = math.fsum(row['actual_et_mm'] for row in all_water_rows)
    drainage = math.fsum(row['deep_percolation_mm'] for row in all_water_rows)
    residual = math.fsum((taw-plan['initial_depletion_mm'], inflow, -et, -drainage, -(taw-depletion)))
    if not math.isfinite(residual) or abs(residual) > 32*len(all_water_rows)*math.ulp(max(taw, inflow, et, drainage)):
        raise ArithmeticError('whole-sequence native water ledger does not reconcile')
    result.update(status=status, final_depletion_mm=depletion,
        daily_water=all_water_rows, water_residual_mm=residual,
        known_harvest_subtotal_edible_dry_kg=str(total_food), known_harvest_subtotal_energy_kcal=str(total_energy),
        total_edible_dry_kg=str(total_food) if status == 'MODELLED' else None,
        total_edible_energy_kcal=str(total_energy) if status == 'MODELLED' else None,
        reasons=[row['segment_id']+': '+row['status'] for row in result['segments'] if row['status'] != 'MODELLED'])
    return result


def preview(plan):
    """Forecast the complete plan; does not create irrigation or harvest stock."""
    return _run(plan, None, preview_only=True)


def execute(plan, deliveries):
    """Use actual predebited field-inlet rows; source authentication is caller-owned."""
    return _run(plan, deliveries, preview_only=False)


def realise(plan, deliveries):
    """Keep pre-season planted geometry; recompute crops from rationed deliveries.

    The external Water ledger owns simultaneous rationing and source debits.
    ROOT_ZONE_NET explicitly certifies that inlet volume times the supplied
    efficiency reaches this reduced root-zone ledger; it is NOT an infiltration
    calculation. No missing delivery is fabricated, and no crop/area is removed.
    Nonrepresentable R1 depths fail closed, rather than silently rounding water.
    """
    requested = _plan(plan)
    lineage = {'requested_plan_sha256': human.digest(requested),
        'requested_daily_forcing': deepcopy(requested['daily_forcing']),
        'planted_area_m2': str(_q(requested['area_m2'], 'fixed planted area', positive=True)),
        'planted_segments': deepcopy(requested['segments']),
        'planting_policy': 'FIXED_PRESEASON; NO_DROUGHT_AREA_DELETION_OR_REOPTIMISATION'}
    if _unknowns(requested) or requested['delivery_boundary'] != 'ROOT_ZONE_NET':
        return {**_run(requested, deliveries, preview_only=False), **lineage,
                'mode': 'REALISE', 'actual_plan_sha256': None,
                'requested_daily_demands': [], 'actual_daily_demands': [],
                'actual_daily_forcing': None, 'irrigation_rationing': []}
    demands = _demands(requested)
    actual_rows, by_day = _deliveries(requested, deliveries, demands, allow_shortfall=True)
    actual_plan = deepcopy(requested)
    area = _q(requested['area_m2'], 'fixed planted area', positive=True)
    efficiency = _q(requested['application_efficiency'], 'application efficiency', positive=True, fraction=True)
    accounts = []
    for index, (demand, rows) in enumerate(zip(demands, by_day)):
        gross = _q(sum((F(row['delivered_volume_m3']) for row in rows), F(0)), 'actual daily inlet volume')
        net = _q(gross*efficiency, 'actual daily root-zone volume')
        exact_mm = _q(net*1000/area, 'actual daily irrigation depth')
        represented_mm = float(exact_mm)
        if F(represented_mm) != exact_mm:
            raise ValueError('actual ROOT_ZONE_NET depth is not exactly native-R1-representable; no silent irrigation rounding')
        actual_plan['daily_forcing'][index]['net_irrigation_mm'] = represented_mm
        requested_gross, requested_net = F(demand['gross_delivery_m3']), F(demand['net_root_zone_m3'])
        unmet_gross = _q(requested_gross-gross, 'unmet daily inlet demand')
        unmet_net = _q(requested_net-net, 'unmet daily root-zone demand')
        accounts.append({'day_index': index, 'available_at_seconds': demand['available_at_seconds'],
            'requested_gross_delivery_m3': str(requested_gross), 'actual_gross_delivery_m3': str(gross),
            'unmet_gross_delivery_m3': str(unmet_gross), 'requested_net_root_zone_m3': str(requested_net),
            'actual_net_root_zone_m3': str(net), 'unmet_net_root_zone_m3': str(unmet_net),
            'actual_application_loss_m3': str(gross-net), 'actual_net_irrigation_mm': str(exact_mm),
            'delivery_ids': sorted(row['delivery_id'] for row in rows),
            'allocation_ids': sorted(row['allocation_id'] for row in rows)})
    # This is the same strict execution gate as a fully supplied schedule, now
    # bound to its explicit ACTUAL forcing. Requested forcing remains separate.
    result = execute(actual_plan, actual_rows)
    fields = ('requested_gross_delivery_m3', 'actual_gross_delivery_m3', 'unmet_gross_delivery_m3',
              'requested_net_root_zone_m3', 'actual_net_root_zone_m3', 'unmet_net_root_zone_m3',
              'actual_application_loss_m3')
    totals = {field: str(_q(sum((F(row[field]) for row in accounts), F(0)), field)) for field in fields}
    return {**result, **lineage, 'mode': 'REALISE',
        'actual_plan_sha256': human.digest(actual_plan),
        'requested_daily_demands': demands, 'actual_daily_demands': _demands(actual_plan),
        'actual_daily_forcing': deepcopy(actual_plan['daily_forcing']),
        'irrigation_rationing': accounts, 'irrigation_rationing_totals': totals}
