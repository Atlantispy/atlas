"""Seasonal finite human stocks and source-bound R2 transport; no population dynamics.

The window boundary is part of the physical scenario: opening goods can travel,
all service is due at the end, and end-boundary harvest/water becomes next-window
stock. No daily availability, fleet schedule, hazard probability or diet is inferred.
"""
from __future__ import annotations

import copy
from fractions import Fraction as F
import hashlib
import json
import math

SCHEMA = 'diadem.seasonal-human.r11'
STATUS = 'WORKING NON-CANON'
HAZARD_UNITS = {'FLOOD_DEPTH': 'm', 'SNOW_WATER_EQUIVALENT': 'm',
                'WIND_SPEED': 'm/s', 'FACTOR_OF_SAFETY': '1', 'SUSCEPTIBILITY': '1'}


class HumanError(ValueError):
    pass


class MissingEvidence(HumanError):
    pass


def _id(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise HumanError(name + ': bounded nonblank identity/evidence required')
    return value


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise HumanError('explicit lowercase source SHA256 required')
    return value


def _q(value, name, *, positive=False, fraction=False, signed=False):
    if value is None:
        raise MissingEvidence(name)
    if isinstance(value, bool) or not isinstance(value, (str, int, float, F)):
        raise HumanError(name + ': explicit number or rational string required')
    try:
        result = F(value)
        view = float(result)
    except (ValueError, OverflowError, ZeroDivisionError) as exc:
        raise HumanError(name + ': finite rational required') from exc
    if not math.isfinite(view) or (result and view == 0):
        raise HumanError(name + ': outside finite represented range')
    if (not signed and result < 0) or (positive and result <= 0) or (fraction and not 0 <= result <= 1):
        raise HumanError(name + ': physical range violated')
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > 8192:
        raise HumanError(name + ': rational accounting envelope exceeded')
    return result


def _plain(value):
    if isinstance(value, F):
        return str(value)
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise HumanError('JSON object keys must be text')
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise HumanError('strict finite JSON input required')


def digest(value):
    return hashlib.sha256(json.dumps(_plain(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _rows(values, key, name, maximum=128):
    if not isinstance(values, list) or len(values) > maximum:
        raise HumanError(name + ': bounded list required')
    result = {}
    for row in values:
        if not isinstance(row, dict):
            raise HumanError(name + ': object record required')
        ident = _id(row.get(key), key)
        if ident in result:
            raise HumanError(name + ': duplicate ' + ident)
        result[ident] = row
    return result


def _keys(value, keys, name):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise HumanError(name + ': exact supported identities required')


def _source(row):
    evidence = row.get('evidence_id')
    if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 8192:
        raise HumanError('complete bounded evidence text/ID required')
    status = row.get('source_status')
    if status not in {'CANON', STATUS, 'SYNTHETIC TEST', 'UNKNOWN', 'CONFLICT', 'INCOMPLETE'}:
        raise HumanError('explicit preserved source_status required')
    if status in {'UNKNOWN', 'CONFLICT', 'INCOMPLETE'}:
        raise MissingEvidence('unresolved source status: ' + status)


def harvest_from_ecosystem(record, *, harvest_id, settlement_id, commodity_id,
                           support_id, area_m2, conversion, available_at_seconds):
    """Convert ACTUAL harvested biomass C, never PFT suitability/activity, to food.

    `record` is a narrowed producer-bound record with event_id/support_id,
    harvested_carbon_kg_m2, source_input_sha256, source_use_id, evidence_id,
    source_status and status='MODELLED'. Root selects the actual producer row.
    All three mass conversion coefficients and applicability evidence are required.
    """
    row = copy.deepcopy(record)
    _source(row)
    if row.get('status') != 'MODELLED':
        raise MissingEvidence('actual modelled harvested-carbon result required')
    if row.get('support_id') != support_id:
        raise HumanError('harvest support mismatch')
    source_after = _q(row.get('available_after_seconds'), 'actual harvest source availability')
    if _q(available_at_seconds, 'harvest available time') < source_after:
        raise HumanError('food harvest cannot predate its actual producer')
    _source(conversion)
    if conversion.get('mass_basis') != 'EDIBLE_DRY_FOOD_KG':
        raise HumanError('explicit edible dry food mass basis required')
    carbon = _q(row.get('harvested_carbon_kg_m2'), 'harvested carbon') * _q(area_m2, 'harvest area', positive=True)
    cf = _q(conversion.get('carbon_fraction_dry_matter'), 'dry-carbon fraction', positive=True, fraction=True)
    edible = _q(conversion.get('edible_fraction'), 'edible fraction', fraction=True)
    loss = _q(conversion.get('processing_loss_fraction'), 'processing loss', fraction=True)
    _id(conversion.get('food_quality_evidence'), 'food-quality/applicability evidence')
    dry = carbon / cf
    candidate = dry * edible
    quantity = candidate * (1 - loss)
    result = {'harvest_id': _id(harvest_id, 'harvest_id'), 'settlement_id': settlement_id,
              'commodity_id': commodity_id, 'support_id': support_id, 'quantity_kg': str(quantity),
              'mass_basis': conversion['mass_basis'], 'available_at_seconds': str(_q(available_at_seconds, 'harvest time')),
              'available_after_seconds': str(source_after),
              'source_event_id': _id(row.get('event_id'), 'source event'),
              'source_input_sha256': _sha(row.get('source_input_sha256')),
              'source_use_id': _id(row.get('source_use_id'), 'atomic source-use ID'),
              'source_status': STATUS, 'evidence_id': conversion['evidence_id'],
              'conversion': _plain({'producer': row, 'coefficients': conversion, 'harvested_carbon_kg': carbon,
                  'harvested_dry_biomass_kg': dry, 'nonfood_dry_biomass_kg': dry-candidate,
                  'processing_loss_kg': candidate-quantity, 'edible_food_kg': quantity,
                  'dry_mass_residual_kg': dry-(dry-candidate)-(candidate-quantity)-quantity,
                  'nutrients': 'NOT inferred into edible fraction; producer harvest nutrient ledger remains separate'})}
    return result


def harvest_from_ecosystem_result(result, *, event_id, settlement_id, commodity_id,
                                  support_id, area_m2, conversion,
                                  source_binding_sha256, geometry_sha256, scenario_id):
    """Select an actual ecosystem event, preserving its law and closing-time stock.

    The source-use identity is derived from the producer input/support/event,
    independent of selected food conversion, so alternate conversions cannot
    create another copy of the same biological harvest in this chain.
    """
    if (result.get('schema') != 'diadem.seasonal-ecosystem.r11'
            or result.get('source_binding_sha256') != _sha(source_binding_sha256)
            or result.get('geometry_sha256') != _sha(geometry_sha256)
            or result.get('scenario_id') != _id(scenario_id, 'ecosystem scenario')):
        raise HumanError('actual ecosystem schema/source/geometry/scenario mismatch')
    if result.get('inputs_sha256') != digest(result.get('inputs')):
        raise HumanError('ecosystem source-input digest mismatch')
    rows = _rows(result.get('events'), 'event_id', 'actual ecosystem events', 4096)
    if event_id not in rows or rows[event_id].get('status') != 'MODELLED':
        raise MissingEvidence('requested ecosystem harvest event not modelled')
    row = rows[event_id]
    source_events = _rows(result['inputs'].get('events'), 'event_id', 'ecosystem input events', 4096)
    previous = result['inputs'].get('initial_state'); elapsed = F(0)
    def organic_carbon(state):
        organic = state['organic_state']
        def quantity(v):
            return F(*v) if isinstance(v,list) and len(v)==2 else F(v)
        return quantity(organic['fast_carbon_kg_m2'])+quantity(organic['slow_carbon_kg_m2'])
    for key, accepted in rows.items():
        if key not in source_events or accepted.get('status') != 'MODELLED':
            raise HumanError('unbound ecosystem accepted event')
        original = source_events[key]
        if (accepted.get('initial_state') != previous or accepted.get('support_id') != original.get('support_id')
                or accepted.get('layer_id') != original.get('layer_id') or accepted.get('month_id') != original.get('month_id')
                or list(rows).index(key) >= len(source_events) or list(source_events)[list(rows).index(key)] != key):
            raise HumanError('ecosystem initial state, physical support or event sequence differs')
        dt = _q(original['organic_forcing']['duration_seconds'], 'producer event duration', positive=True)
        if F(accepted['duration_seconds']) != dt or F(accepted['start_seconds_in_year']) != elapsed:
            raise HumanError('ecosystem output chronology differs from actual inputs')
        initial_live = _q(previous['live_carbon_kg_m2'], 'opening live C')
        growth = _q(accepted.get('net_production_kg_c_m2'), 'actual net C production')
        potential = _q(accepted.get('potential_net_production_kg_c_m2'), 'potential production')
        litter = _q(accepted.get('litter_carbon_kg_m2'), 'actual litter export')
        harvest = _q(accepted.get('harvested_carbon_kg_m2'), 'actual harvest export')
        fraction = _q(original.get('harvest_fraction'), 'input harvest fraction', fraction=True)
        pre_harvest = initial_live-litter+growth
        end_live = _q(accepted['end_state']['live_carbon_kg_m2'], 'closing live C')
        if litter > initial_live or growth > potential or harvest != pre_harvest*fraction or end_live != pre_harvest-harvest:
            raise HumanError('ecosystem actual plant stock and supplied harvest-fraction ledger differs')
        budget = accepted['budgets_kg_m2']['C']; forcing = original['organic_forcing']
        incoming = dt*(F(forcing['fast_litter_carbon_kg_m2_s'])+F(forcing['slow_litter_carbon_kg_m2_s']))
        opening = initial_live+organic_carbon(previous); closing = end_live+organic_carbon(accepted['end_state'])
        export = _q(accepted['organic_producer']['carbon']['exported_atmospheric_carbon_kg_m2'], 'actual carbon export')
        expected = {'initial':opening, 'final':closing, 'net_atmospheric_input':growth,
            'external_litter_input':incoming, 'heterotrophic_export':export, 'harvest_export':harvest, 'numerical_residual':F(0)}
        if set(budget) != set(expected) or any(F(budget[k]) != v for k,v in expected.items()) or opening+growth+incoming != closing+export+harvest:
            raise HumanError('ecosystem carbon stock/source budget differs')
        previous = accepted['end_state']; elapsed += dt
        if key == event_id:
            break
    if row.get('support_id') != support_id:
        raise HumanError('ecosystem harvest physical support mismatch')
    actual_cf = _q(result['inputs']['plant_law'].get('carbon_fraction_dry_matter'), 'producer dry-carbon fraction', positive=True, fraction=True)
    if _q(conversion.get('carbon_fraction_dry_matter'), 'food conversion dry-carbon fraction', positive=True, fraction=True) != actual_cf:
        raise HumanError('food conversion must retain actual producer dry-carbon mass basis')
    carbon = _q(row.get('harvested_carbon_kg_m2'), 'actual harvested carbon')
    if _q(row.get('harvested_dry_matter_kg_m2'), 'actual harvested dry matter') != carbon/actual_cf:
        raise HumanError('ecosystem carbon/dry harvest ledger mismatch')
    at = _q(row.get('start_seconds_in_year'), 'ecosystem event start')+_q(row.get('duration_seconds'), 'ecosystem duration', positive=True)
    sid = digest({'inputs': result['inputs_sha256'], 'event_id': event_id, 'support_id': support_id,
                  'layer_id': row.get('layer_id'), 'kind': 'WHOLE_EVENT_HARVEST'})
    record = {'status': 'MODELLED', 'event_id': event_id, 'support_id': support_id,
        'harvested_carbon_kg_m2': str(carbon), 'source_input_sha256': digest(result), 'source_use_id': sid,
        'available_after_seconds': str(at),
        'evidence_id': result['inputs']['plant_law'].get('evidence'), 'source_status': result['inputs']['plant_law'].get('source_status')}
    harvest = harvest_from_ecosystem(record, harvest_id='ecosystem-'+sid, settlement_id=settlement_id,
        commodity_id=commodity_id, support_id=support_id, area_m2=area_m2, conversion=conversion, available_at_seconds=at)
    harvest['conversion']['ecosystem_event'] = copy.deepcopy(row)
    harvest['conversion']['ecosystem_source_binding_sha256'] = source_binding_sha256
    harvest['conversion']['geometry_sha256'] = geometry_sha256
    harvest['source_interval'] = {'event_id': event_id,
        'start_seconds': row['start_seconds_in_year'], 'end_seconds': str(at),
        'binding': 'actual ecosystem input/state/clock prefix checked before conversion'}
    return harvest


def harvest_from_crop(agroclimate, *, root_zone, daily_forcing, crop_parameters,
                      area_m2, conversion, harvest_id, settlement_id, commodity_id,
                      support_id, event_id, source_use_id, available_at_seconds):
    """Execute the exact injected R1 DAILY crop producer, with no monthly downsplit.

    potential/yield mass basis must explicitly be DRY_HARVEST_KG. Irrigation must
    already be separately debited at the physical water source by the caller.
    """
    parameters = copy.deepcopy(crop_parameters)
    if parameters.pop('yield_mass_basis', None) != 'DRY_HARVEST_KG':
        raise HumanError('declared dry crop harvest basis required')
    irrigation = parameters.pop('irrigation_deliveries', None)
    deliveries = _rows(irrigation, 'allocation_id', 'actual irrigation deliveries', 4096)
    day_seconds = _q(parameters.pop('day_duration_seconds', None), 'explicit crop-day seconds', positive=True)
    crop_start = _q(parameters.pop('season_start_seconds', None), 'crop season start')
    area = _q(area_m2, 'crop area', positive=True)
    applied = [F(0)]*len(daily_forcing)
    irrigation_rows = []; delivery_ids = set()
    for row in deliveries.values():
        _source(row)
        delivery_id = _id(row.get('delivery_id'), 'actual irrigation delivery ID')
        if delivery_id in delivery_ids:
            raise HumanError('irrigation terminal delivery reused under another allocation')
        delivery_ids.add(delivery_id)
        if row.get('kind') != 'ROUTED_WITHDRAWAL_DELIVERY' or row.get('status') != 'MODELLED':
            raise HumanError('irrigation needs actual debited terminal water, not runoff')
        if row.get('support_id') != support_id or row.get('receiving_sink_id') != parameters.get('irrigation_sink_id'):
            raise HumanError('irrigation physical support/sink mismatch')
        _sha(row.get('source_input_sha256'))
        day = row.get('day_index')
        if type(day) is not int or not 0 <= day < len(daily_forcing):
            raise HumanError('explicit irrigation day index required')
        at = crop_start+day_seconds*day
        if _q(row.get('available_after_seconds'), 'source water release time') > at:
            raise HumanError('irrigation used before routed delivery')
        volume = _q(row.get('delivered_volume_m3'), 'actual irrigation delivered volume')
        efficiency = _q(row.get('application_efficiency'), 'irrigation application efficiency', fraction=True)
        _id(row.get('application_evidence'), 'application efficiency evidence')
        net = volume*efficiency; applied[day] += net
        irrigation_rows.append(_plain({'allocation_id': row['allocation_id'], 'delivery_id': delivery_id, 'gross_delivery_m3': volume,
            'net_root_zone_m3': net, 'application_loss_m3': volume-net, 'day_index': day, 'source': row}))
    parameters.pop('irrigation_sink_id', None)
    for day, forcing in enumerate(daily_forcing):
        net = _q(forcing.get('net_irrigation_mm'), 'daily net irrigation')*area/1000
        if applied[day] != net:
            raise HumanError('irrigation source debit and exact daily net-root-zone volume do not match')
    if _q(available_at_seconds, 'crop harvest availability') < crop_start+day_seconds*len(daily_forcing):
        raise HumanError('crop harvest predates the actual explicit daily season')
    result = agroclimate.crop_season(agroclimate.RootZone(**root_zone),
        [agroclimate.DayForcing(**d) for d in daily_forcing], **parameters)
    if result['status'] != 'MODELLED':
        return {'status': result['status'], 'harvest': None, 'crop': result}
    _source(conversion)
    cf = _q(conversion.get('carbon_fraction_dry_matter'), 'explicit crop dry-carbon conversion', positive=True, fraction=True)
    # Multiplication/division by the same exact supplied factor cancels. It lets
    # the common checked material conversion expose a dry-mass ledger without
    # claiming that the crop producer modelled carbon chemistry.
    narrowed = {'status': 'MODELLED', 'event_id': event_id, 'support_id': support_id,
        'harvested_carbon_kg_m2': str(F(result['yield_kg_m2']) * cf),
        'source_input_sha256': digest({'root_zone': root_zone, 'daily_forcing': daily_forcing,
            'crop_parameters': crop_parameters, 'result': result}),
        'source_use_id': source_use_id, 'evidence_id': parameters['evidence'],
        'available_after_seconds': str(crop_start+day_seconds*len(daily_forcing)),
        'source_status': result['source_status']}
    harvest = harvest_from_ecosystem(narrowed, harvest_id=harvest_id, settlement_id=settlement_id,
        commodity_id=commodity_id, support_id=support_id, area_m2=area_m2,
        conversion=conversion, available_at_seconds=available_at_seconds)
    harvest['conversion']['producer_kind'] = 'ACTUAL_R1_DAILY_CROP; carbon here is only an exact cancelling conversion intermediary'
    harvest['conversion']['irrigation_debits'] = irrigation_rows
    harvest['conversion']['irrigation_allocation_ids'] = sorted(deliveries)
    harvest['conversion']['irrigation_delivery_ids'] = sorted(delivery_ids)
    harvest['conversion']['season_start_seconds'] = str(crop_start)
    harvest['conversion']['day_duration_seconds'] = str(day_seconds)
    return {'status': 'MODELLED', 'harvest': harvest, 'crop': result}


def water_delivery(record, *, settlement_id, receiving_sink_id, available_at_seconds):
    """Narrow an already-debited routed terminal delivery, not runoff/discharge."""
    _source(record)
    if record.get('status') != 'MODELLED' or record.get('kind') != 'ROUTED_WITHDRAWAL_DELIVERY':
        raise MissingEvidence('actual routed withdrawal delivery required')
    if record.get('receiving_sink_id') != receiving_sink_id:
        raise HumanError('routed water receiving sink mismatch')
    available = _q(available_at_seconds, 'available time')
    source_after = _q(record.get('available_after_seconds'), 'actual source delivery time')
    if available < source_after:
        raise HumanError('routed water cannot be available before its actual source delivery')
    return {'allocation_id': _id(record.get('allocation_id'), 'allocation_id'),
        'delivery_id': _id(record.get('delivery_id'), 'delivery_id'),
        'receiving_sink_id': receiving_sink_id, 'settlement_id': settlement_id,
        'delivered_volume_m3': str(_q(record.get('delivered_volume_m3'), 'delivered volume')),
        'source_event_id': _id(record.get('event_id'), 'event_id'),
        'source_input_sha256': _sha(record.get('source_input_sha256')),
        'available_at_seconds': str(available), 'available_after_seconds': str(source_after),
        'evidence_id': record['evidence_id'], 'source_status': record['source_status']}


def water_deliveries_from_result(result, *, event_id, settlement_by_sink,
                                 source_binding_sha256, scenario_id):
    """Consume only selected actual ALLOCATION terminals from the finite network.

    Unselected allocations, spill and evaporation are not settlement supply.
    Wrapper delivery IDs are explicitly derived content identities, not invented
    physical observations. Actual input/allocation/event identities remain intact.
    """
    if (result.get('schema') != 'diadem.thermal-water-result.r11'
            or result.get('source_binding_sha256') != _sha(source_binding_sha256)
            or result.get('scenario_id') != _id(scenario_id, 'water scenario')):
        raise HumanError('actual routed water schema/source/scenario mismatch')
    if result.get('inputs_sha256') != digest(result.get('inputs')):
        raise HumanError('actual routed water input digest mismatch')
    if not isinstance(settlement_by_sink, dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in settlement_by_sink.items()):
        raise HumanError('explicit terminal sink to settlement map required')
    rows = _rows(result.get('events'), 'event_id', 'actual routed water events', 4096)
    if event_id not in rows or rows[event_id].get('status') != 'MODELLED':
        raise MissingEvidence('actual routed water event not modelled')
    source = rows[event_id]; outputs = []
    inputs = result['inputs']; input_events = _rows(inputs.get('events'), 'event_id', 'water input events', 4096)
    if event_id not in input_events:
        raise HumanError('water output event is absent from source input')
    expected_start = F(inputs['initial']['elapsed_seconds'])
    for key, source_event in input_events.items():
        if key == event_id:
            break
        expected_start += F(source_event['duration_seconds'])
    expected_end = expected_start+F(input_events[event_id]['duration_seconds'])
    if F(source['start_seconds']) != expected_start or F(source['end_seconds']) != expected_end:
        raise HumanError('water event clock differs from source input sequence')
    deliveries = _rows(source.get('deliveries'), 'allocation_id', 'actual terminal deliveries', 4096)
    withdrawals = _rows(input_events[event_id]['withdrawals'], 'allocation_id', 'input water withdrawals', 4096)
    node_exports = {node: F(0) for node in source['nodes']}
    for row in deliveries.values():
        node = row.get('node_id')
        if node not in node_exports or node not in inputs['network']['nodes']:
            raise HumanError('terminal delivery source node mismatch')
        rho = _q(inputs['network']['nodes'][node]['liquid_density_kg_m3'], 'source water density', positive=True)
        mass = _q(row.get('delivered_mass_kg'), 'terminal delivered mass')
        volume = _q(row.get('delivered_volume_m3'), 'terminal delivered volume')
        if mass != volume*rho or F(row['available_after_seconds']) != expected_end:
            raise HumanError('terminal mass/volume or actual availability differs')
        if row.get('kind') != 'SPILL':
            original = withdrawals.get(row['allocation_id'])
            if (original is None or any(row.get(k) != original.get(k) for k in ('node_id','sink_id','kind'))
                    or F(row['requested_volume_m3']) != F(original['volume_m3'])
                    or volume+F(row['unmet_volume_m3']) != F(original['volume_m3'])):
                raise HumanError('terminal allocation differs from source withdrawal request')
        node_exports[node] += mass
    if any(node_exports[k] != F(v['ledger']['external_out_kg']) for k,v in source['nodes'].items()):
        raise HumanError('terminal delivery totals differ from actual source node export ledger')
    for row in deliveries.values():
        if row.get('kind') != 'ALLOCATION' or row.get('sink_id') not in settlement_by_sink:
            continue
        if row.get('event_id') != event_id or row.get('source_input_sha256') != result['inputs_sha256'] or row.get('source_binding_sha256') != source_binding_sha256:
            raise HumanError('water allocation parent identity mismatch')
        if row.get('availability_support') != 'INTERVAL_END_DELIVERY_NOT_WITHIN_INTERVAL_RESERVOIR_STOCK':
            raise HumanError('actual terminal delivery timing support differs')
        record = {'kind': 'ROUTED_WITHDRAWAL_DELIVERY', 'status': 'MODELLED',
            'allocation_id': row['allocation_id'], 'delivery_id': 'bound-delivery-'+digest(row),
            'receiving_sink_id': row['sink_id'], 'delivered_volume_m3': row['delivered_volume_m3'],
            'event_id': event_id, 'source_input_sha256': row['source_input_sha256'],
            'available_after_seconds': row['available_after_seconds'], 'evidence_id': row['evidence'],
            'source_status': result['inputs']['network']['source_status']}
        output = water_delivery(record, settlement_id=settlement_by_sink[row['sink_id']],
            receiving_sink_id=row['sink_id'], available_at_seconds=row['available_after_seconds'])
        output['actual_routed_delivery'] = copy.deepcopy(row)
        output['wrapper_id_semantics'] = 'content-derived delivery binding; original allocation_id retained'
        outputs.append(output)
    return outputs


def hazard_response(rule, observations, *, event_id):
    """Explicit monotone service response, not event probability or expected loss."""
    _id(rule.get('evidence_id'), 'response evidence')
    mid = _id(rule.get('metric_id'), 'metric_id')
    obs = observations.get(mid)
    if obs is None:
        raise MissingEvidence('hazard observation: ' + mid)
    _source(obs)
    if (obs.get('event_id') != event_id or obs.get('support_id') != rule.get('support_id')
            or obs.get('unit') != rule.get('unit') or HAZARD_UNITS.get(obs.get('kind')) != obs.get('unit')):
        raise HumanError('hazard event/support/dimension mismatch')
    _sha(obs.get('source_input_sha256'))
    if obs.get('temporal_support') not in {'INTERVAL_HELD', 'INTERVAL_MAXIMUM', 'INTERVAL_MINIMUM'}:
        raise HumanError('instantaneous hazard cannot silently represent the window')
    if rule.get('whole_window_scenario') is not True:
        raise HumanError('whole-window response hypothesis must be explicit')
    value = _q(obs.get('value'), 'hazard value')
    full = _q(rule.get('full_service_at'), 'full-service threshold')
    zero = _q(rule.get('zero_service_at'), 'zero-service threshold')
    if full == zero:
        raise HumanError('distinct service-response endpoints required')
    fraction = min(F(1), max(F(0), (zero-value)/(zero-full)))
    return _plain({'metric_id': mid, 'observation': obs, 'rule': rule,
                   'service_fraction': fraction, 'meaning': 'DECLARED_SERVICE_RESPONSE_NOT_PROBABILITY'})


def capacity_representation(exact_capacity_kg, law):
    """Explicit inner approximation solely at the retained R2 rational boundary.

    The physical capacity is never overwritten. The retained optimum/certificate
    belongs to the represented smaller feasible set, not the original optimum.
    """
    value = _q(exact_capacity_kg, 'exact physical capacity')
    in_envelope = lambda q: q.numerator.bit_length() <= 256 and q.denominator.bit_length() <= 128
    quantum = max_loss = None
    if law is not None:
        _keys(law, ('method','quantum_kg','max_absolute_loss_kg','evidence_id','source_status'), 'capacity representation law')
        _source(law)
        if law['method'] != 'EXACT_OR_DYADIC_INNER':
            raise HumanError('explicit supported capacity representation method required')
        quantum = _q(law['quantum_kg'], 'capacity quantum', positive=True)
        max_loss = _q(law['max_absolute_loss_kg'], 'capacity reduction allowance')
        if (quantum.numerator & (quantum.numerator-1) or quantum.denominator & (quantum.denominator-1)
                or not in_envelope(quantum)):
            raise HumanError('capacity quantum must be a supported exact power of two')
    represented = value
    if not in_envelope(value) and law is not None:
        represented = (value//quantum)*quantum
        if value > 0 and represented == 0:
            raise HumanError('positive capacity cannot disappear below the declared quantum')
        if value-represented > max_loss:
            raise HumanError('capacity representation exceeds declared absolute reduction allowance')
        if not in_envelope(represented):
            raise HumanError('represented capacity remains outside retained R2 rational envelope')
    # With no explicit law the exact value reaches R2 and its original strict
    # boundary rejects it. No default rounding or exception-driven repinning.
    return _plain({'exact_capacity_kg':value,'represented_capacity_kg':represented,
        'reduction_kg':value-represented,'relative_reduction':F(0) if value==0 else (value-represented)/value,
        'method':'EXACT' if value==represented else 'EXPLICIT_DYADIC_INNER',
        'declared_law':law,'feasible_for_original_capacity':True,
        'original_capacity_optimum_certified':value==represented,
        'certificate_scope':'R2 certified represented inner network only; no original-network objective-gap bound inferred'})


def _transport(module, network, settlements, commodities, food, demands, event, duration, scenario):
    nodes = [module.Node(**r) for r in network['nodes']]
    stocks = [module.Stock(s+'::'+c, row['node_id'], c, food[s][c], event['event_id'], row['evidence_id'])
              for s, row in settlements.items() for c in commodities]
    typed_demands = []
    for d in demands.values():
        _source(d)
        if d.get('settlement_id') not in settlements or d.get('commodity_id') not in commodities:
            raise HumanError('food demand endpoint/commodity unknown')
        typed_demands.append(module.Demand(d['demand_id'], settlements[d['settlement_id']]['node_id'],
            d['commodity_id'], _q(d.get('required_kg'), 'food demand'),
            _q(d.get('weight_per_kg'), 'explicit food objective weight', positive=True),
            event['event_id'], d['evidence_id']))
    # A uniform route-dispatch interval H=T-L leaves enough time for every
    # simple route. Bounding each group's SUM of route-entry rates by its rate
    # is sufficient even when differently delayed route legs overlap.
    travel_bound = sum((_q(link['travel_time_s'], 'travel/handling duration', positive=True)
                        for link in network['links'] if link['available'] is True), F(0))
    if travel_bound > duration:
        raise HumanError('OUTSIDE_REGIME: conservative all-simple-path travel bound exceeds window')
    dispatch_horizon = duration-travel_bound
    groups, response_rows = [], []
    for group in network['capacity_groups']:
        rate = _q(group.get('capacity_rate_kg_s'), 'shared throughput rate')
        rules = group.get('hazard_rules')
        if not isinstance(rules, list):
            raise HumanError('explicit group hazard rule list required; [] means no selected restriction')
        responses = [hazard_response(r, event['hazard_observations'], event_id=event['event_id']) for r in rules]
        factor = min([F(1)] + [F(r['service_fraction']) for r in responses])
        represented = capacity_representation(rate*dispatch_horizon*factor, network.get('capacity_representation'))
        groups.append(module.CapacityGroup(group['group_id'], F(represented['represented_capacity_kg']), event['event_id'], group['evidence_id']))
        response_rows.append(_plain({'group_id': group['group_id'], 'base_capacity_kg': rate*dispatch_horizon,
            'capacity_kg': rate*dispatch_horizon*factor, 'service_fraction': factor, 'responses': responses,
            'uniform_dispatch_horizon_seconds': dispatch_horizon, 'capacity_rate_kg_s': rate,
            'numerical_representation':represented}))
    links = []
    for link in network['links']:
        row = copy.deepcopy(link)
        time = _q(row['travel_time_s'], 'travel/handling duration', positive=True)
        if row['available'] is None:
            raise MissingEvidence('link availability')
        row['travel_time_s'] = time
        row['period_id'] = event['event_id']
        typed_rules = []
        for rule in row['rules']:
            rule = copy.deepcopy(rule)
            rule['loss_fraction'] = None if rule['loss_fraction'] is None else _q(rule['loss_fraction'], 'transport loss', fraction=True)
            rule['capacity_uses'] = tuple(module.CapacityUse(u['group_id'],
                _q(u['load_kg_per_kg_entering'], 'capacity loading', positive=True), u['evidence_id']) for u in rule['capacity_uses'])
            typed_rules.append(module.CommodityRule(**rule))
        row['rules'] = tuple(typed_rules)
        links.append(module.Link(**row))
    result = module.solve_multicommodity(nodes, [module.Commodity(**c) for c in commodities.values()], stocks,
        typed_demands, links, groups, period=module.Period(event['event_id'], duration),
        objective=module.Objective(module.OBJECTIVE, scenario, network['objective_evidence_id']),
        network_complete=network['network_complete'], evidence_id=network['evidence_id'])
    result['seasonal_capacity_representation'] = {
        'original_capacity_optimum_certified': all(r['numerical_representation']['original_capacity_optimum_certified'] for r in response_rows),
        'certificate_scope':'unchanged R2 certificate applies to the supplied represented capacities; original physical capacities and exact reductions are retained separately'}
    return result, response_rows, str(travel_bound)


def _event(module, state, event, clock, settlements, commodities, network, scenario):
    """Transactional window: caller commits only on fully known successful solve."""
    ident = clock['event_id']; start = F(clock['start_seconds']); duration = F(clock['duration_seconds']); end = start+duration
    if event.get('event_id') != ident:
        raise HumanError('event/calendar mismatch')
    if not isinstance(event.get('hazard_observations'), dict):
        raise HumanError('explicit hazard observation object required')
    for key in ('water_loss_fraction', 'food_loss_fraction', 'protected_food_reserve_kg'):
        _keys(event.get(key), settlements, key)
    water = {s: F(v) for s, v in state['water_m3'].items()}
    food = {s: {c: F(v) for c, v in values.items()} for s, values in state['food_kg'].items()}
    opening_water = copy.deepcopy(water); opening_food = copy.deepcopy(food)
    water_in = {s: [F(0), F(0)] for s in settlements}
    food_in = {s: {c: [F(0), F(0)] for c in commodities} for s in settlements}
    seen_water = set(state['used_water_allocation_ids']); seen_delivery = set(state['used_water_delivery_ids'])
    seen_harvest = set(state['used_harvest_ids']); seen_source = set(state['used_harvest_source_ids'])
    for row in _rows(event.get('water_deliveries'), 'allocation_id', 'water deliveries').values():
        _source(row); s = row.get('settlement_id')
        if s not in settlements or row.get('receiving_sink_id') != settlements[s]['receiving_sink_id']:
            raise HumanError('water allocation destination mismatch')
        aid = row['allocation_id']; did = _id(row.get('delivery_id'), 'delivery ID')
        if aid in seen_water or did in seen_delivery:
            raise HumanError('water source allocation/delivery reused')
        if row.get('source_event_id') != ident:
            raise HumanError('water source event mismatch')
        _sha(row.get('source_input_sha256'))
        at = _q(row.get('available_at_seconds'), 'water availability time')
        if at < _q(row.get('available_after_seconds'), 'actual routed source availability'):
            raise HumanError('water used before actual routed source delivery')
        if at not in (start, end):
            raise HumanError('water delivery must be explicitly at opening or closing boundary')
        water_in[s][int(at == end)] += _q(row.get('delivered_volume_m3'), 'water delivered')
        seen_water.add(aid); seen_delivery.add(did)
    for row in _rows(event.get('harvests'), 'harvest_id', 'harvests').values():
        _source(row); s = row.get('settlement_id'); c = row.get('commodity_id')
        if (s not in settlements or c not in commodities or row.get('support_id') != settlements[s]['support_id']
                or row.get('mass_basis') != commodities[c]['mass_basis']):
            raise HumanError('harvest support/commodity/mass basis mismatch')
        hid = row['harvest_id']; sid = _id(row.get('source_use_id'), 'atomic harvest source-use ID')
        if hid in seen_harvest or sid in seen_source:
            raise HumanError('harvest source reused, including alternate conversion/commodity')
        source_event = _id(row.get('source_event_id'), 'harvest source event')
        _sha(row.get('source_input_sha256'))
        at = _q(row.get('available_at_seconds'), 'harvest time')
        if source_event != ident:
            interval = row.get('source_interval')
            if (not isinstance(interval, dict) or interval.get('event_id') != source_event
                    or _q(interval.get('end_seconds'), 'source harvest interval end') != at
                    or _q(interval.get('start_seconds'), 'source harvest interval start') > at):
                raise HumanError('distinct source/consumer event IDs need an explicit actual interval-end join')
            _id(interval.get('binding'), 'actual interval binding')
        if 'available_after_seconds' in row and at < _q(row['available_after_seconds'], 'producer harvest time'):
            raise HumanError('food used before actual producer harvest')
        if at not in (start, end):
            raise HumanError('harvest must explicitly occur at opening or closing boundary')
        food_in[s][c][int(at == end)] += _q(row.get('quantity_kg'), 'actual edible harvest')
        seen_harvest.add(hid); seen_source.add(sid)
        irrigation_ids = row.get('conversion', {}).get('irrigation_allocation_ids', [])
        if not isinstance(irrigation_ids, list) or len(irrigation_ids) != len(set(irrigation_ids)):
            raise HumanError('unique crop irrigation source allocations required')
        for aid in irrigation_ids:
            _id(aid, 'crop irrigation allocation')
            if aid in seen_water:
                raise HumanError('crop irrigation allocation also used as settlement water or another crop')
            seen_water.add(aid)
        irrigation_delivery_ids = row.get('conversion', {}).get('irrigation_delivery_ids', [])
        if not isinstance(irrigation_delivery_ids,list) or len(irrigation_delivery_ids)!=len(set(irrigation_delivery_ids)) or len(irrigation_ids)!=len(irrigation_delivery_ids):
            raise HumanError('one unique irrigation delivery binding per allocation required')
        for did in irrigation_delivery_ids:
            _id(did, 'irrigation delivery binding')
            if did in seen_delivery:
                raise HumanError('crop terminal delivery reused as water or another crop')
            seen_delivery.add(did)
    water_pre, food_pre, water_losses, food_losses = {}, {}, {}, {}
    for s, row in settlements.items():
        cap = _q(row.get('water_capacity_m3'), 'reservoir capacity')
        raw = water[s]+water_in[s][0]; water_pre[s] = max(F(0), raw-cap)
        water[s] = min(raw, cap)
        water_losses[s] = water[s]*_q(event['water_loss_fraction'][s], 'reservoir opening attrition', fraction=True)
        water[s] -= water_losses[s]
        _keys(event['food_loss_fraction'][s], commodities, 'food attrition coverage')
        food_pre[s] = {}; food_losses[s] = {}
        for c in commodities:
            cap = _q(row['food_capacity_kg'][c], 'commodity storage capacity')
            raw = food[s][c]+food_in[s][c][0]; food_pre[s][c] = max(F(0), raw-cap)
            food[s][c] = min(raw, cap)
            food_losses[s][c] = food[s][c]*_q(event['food_loss_fraction'][s][c], 'food opening attrition', fraction=True)
            food[s][c] -= food_losses[s][c]
    water_demands = _rows(event.get('water_demands'), 'demand_id', 'water demands')
    order = event.get('water_demand_order')
    if not isinstance(order, list) or len(order) != len(set(order)) or set(order) != set(water_demands):
        raise HumanError('explicit water demand priority must list each demand exactly once')
    served_water = {s: F(0) for s in settlements}; water_services = []
    for did in order:
        row = water_demands[did]; _source(row); s = row.get('settlement_id')
        if s not in settlements:
            raise HumanError('water demand unknown settlement')
        required = _q(row.get('required_m3'), 'required service water')
        served = min(required, water[s]); water[s] -= served; served_water[s] += served
        water_services.append(_plain({'demand_id': did, 'settlement_id': s, 'required_m3': required,
            'delivered_m3': served, 'shortage_m3': required-served,
            'status': 'NO_DEMAND' if required == 0 else 'FULFILLED' if served == required else 'SHORTAGE'}))
    demands = _rows(event.get('food_demands'), 'demand_id', 'food demands', 64)
    food_order = event.get('food_demand_order')
    if not isinstance(food_order, list) or len(food_order) != len(set(food_order)) or set(food_order) != set(demands):
        raise HumanError('explicit local food priority must list each demand exactly once')
    local = {}; local_used = {s: {c: F(0) for c in commodities} for s in settlements}
    remaining = copy.deepcopy(demands)
    for did in food_order:
        d = demands[did]; _source(d); s = d.get('settlement_id'); c = d.get('commodity_id')
        if s not in settlements or c not in commodities:
            raise HumanError('unknown food demand endpoint/commodity')
        need = _q(d.get('required_kg'), 'food demand')
        _q(d.get('weight_per_kg'), 'explicit food objective weight', positive=True)
        take = min(need, food[s][c]); food[s][c] -= take; local[did] = take
        local_used[s][c] += take; remaining[did]['required_kg'] = str(need-take)
    reserves = {}; reserve_rows = []
    for s in settlements:
        _keys(event['protected_food_reserve_kg'][s], commodities, 'protected reserve commodity coverage')
        reserves[s] = {}
        for c in commodities:
            required = _q(event['protected_food_reserve_kg'][s][c], 'protected reserve')
            held = min(required, food[s][c]); reserves[s][c] = held; food[s][c] -= held
            reserve_rows.append(_plain({'settlement_id': s, 'commodity_id': c, 'required_kg': required,
                                       'held_kg': held, 'shortage_kg': required-held}))
    transport, responses, travel = _transport(module, network, settlements, commodities, food, remaining, event, duration, scenario)
    if not transport['solved']:
        if transport['status'] == 'MISSING_EVIDENCE':
            raise MissingEvidence('transport: ' + ', '.join(transport['missing_evidence']))
        raise HumanError('transport ' + transport['status'] + ': ' + str(transport.get('reason')))
    dispatched = {s: {c: F(0) for c in commodities} for s in settlements}
    for row in transport['stocks']:
        s, c = row['stock_id'].split('::')
        dispatched[s][c] = F(row['used_kg']['exact'])+local_used[s][c]
        food[s][c] = F(row['unused_kg']['exact'])+reserves[s][c]
    consumed = copy.deepcopy(local_used); food_services = []
    for row in transport['demands']:
        original = demands[row['demand_id']]
        delivered = F(row['delivered_kg']['exact']); required = F(original['required_kg']); local_delivery = local[row['demand_id']]
        consumed[original['settlement_id']][original['commodity_id']] += delivered
        food_services.append(_plain({'demand_id': row['demand_id'], 'settlement_id': original['settlement_id'],
            'commodity_id': original['commodity_id'], 'required_kg': required, 'local_delivery_kg': local_delivery,
            'transported_delivery_kg': delivered, 'delivered_kg': local_delivery+delivered,
            'shortage_kg': required-local_delivery-delivered,
            'status': 'NO_DEMAND' if required == 0 else 'FULFILLED' if local_delivery+delivered == required else row['status']}))
    water_ledgers, food_ledgers = [], []
    for s, row in settlements.items():
        raw = water[s]+water_in[s][1]; cap = F(row['water_capacity_m3']); spill = max(F(0), raw-cap)
        water[s] = min(raw, cap)
        residual = opening_water[s]+sum(water_in[s])-water_pre[s]-spill-water_losses[s]-served_water[s]-water[s]
        if residual:
            raise ArithmeticError('water stock conservation failed')
        water_ledgers.append(_plain({'settlement_id': s, 'opening_m3': opening_water[s],
            'opening_delivery_m3': water_in[s][0], 'closing_delivery_m3': water_in[s][1],
            'opening_spill_m3': water_pre[s], 'closing_spill_m3': spill, 'loss_m3': water_losses[s],
            'consumed_service_m3': served_water[s], 'closing_m3': water[s], 'residual_m3': residual}))
        for c in commodities:
            raw = food[s][c]+food_in[s][c][1]; cap = F(row['food_capacity_kg'][c]); discard = max(F(0), raw-cap)
            food[s][c] = min(raw, cap)
            residual = opening_food[s][c]+sum(food_in[s][c])-food_pre[s][c]-discard-food_losses[s][c]-dispatched[s][c]-food[s][c]
            if residual:
                raise ArithmeticError('food source stock conservation failed')
            food_ledgers.append(_plain({'settlement_id': s, 'commodity_id': c, 'opening_kg': opening_food[s][c],
                'opening_harvest_kg': food_in[s][c][0], 'closing_harvest_kg': food_in[s][c][1],
                'opening_storage_discard_kg': food_pre[s][c], 'closing_storage_discard_kg': discard,
                'storage_loss_kg': food_losses[s][c], 'used_at_source_kg': dispatched[s][c],
                'consumed_at_destination_kg': consumed[s][c], 'closing_kg': food[s][c], 'source_stock_residual_kg': residual}))
    exposure = []
    for s, row in settlements.items():
        for rule in row['exposure_rules']:
            try:
                response = hazard_response(rule, event['hazard_observations'], event_id=ident)
                exposed = row['population'] if F(response['service_fraction']) < 1 else 0
                exposure.append({'settlement_id': s, 'status': 'MODELLED_EXPOSURE', 'exposed_fixed_population': exposed,
                    'response': response, 'probability': None, 'expected_casualties': None})
            except MissingEvidence as exc:
                exposure.append({'settlement_id': s, 'status': 'UNKNOWN', 'reason': str(exc),
                    'exposed_fixed_population': None, 'probability': None, 'expected_casualties': None})
    following = _plain({'water_m3': water, 'food_kg': food, 'elapsed_seconds': end,
        'used_water_allocation_ids': sorted(seen_water), 'used_water_delivery_ids': sorted(seen_delivery),
        'used_harvest_ids': sorted(seen_harvest), 'used_harvest_source_ids': sorted(seen_source)})
    totals = []
    for c in commodities:
        opening = sum((opening_food[s][c] for s in settlements), F(0))
        harvest = sum((sum(food_in[s][c]) for s in settlements), F(0))
        closing = sum((food[s][c] for s in settlements), F(0))
        service = sum((consumed[s][c] for s in settlements), F(0))
        transport_loss = next(F(r['loss_kg']['exact']) for r in transport['commodity_totals'] if r['commodity_id'] == c)
        losses = sum((F(r['storage_loss_kg'])+F(r['opening_storage_discard_kg'])+F(r['closing_storage_discard_kg'])
                      for r in food_ledgers if r['commodity_id'] == c), F(0))
        residual = opening+harvest-closing-service-transport_loss-losses
        if residual:
            raise ArithmeticError('whole-network food ledger failed')
        totals.append(_plain({'commodity_id': c, 'opening_kg': opening, 'harvest_kg': harvest, 'closing_kg': closing,
            'consumed_service_kg': service, 'transport_loss_kg': transport_loss, 'storage_loss_and_discard_kg': losses, 'residual_kg': residual}))
    output = {'event_id': ident, 'status': 'MODELLED', 'start_seconds': str(start), 'duration_seconds': str(duration),
        'end_seconds': str(end), 'input_sha256': digest(event), 'water': water_ledgers,
        'water_service': water_services, 'food': food_ledgers, 'food_service': food_services,
        'protected_reserves': reserve_rows, 'food_totals': totals, 'transport': transport,
        'capacity_responses': responses, 'hazard_exposure': exposure,
        'conservative_route_travel_bound_seconds': travel,
        'service_timing': 'ALL demand due at END; only OPENING stock can travel; closing source inputs carried forward',
        'dispatch_horizon_seconds': str(duration-F(travel)),
        'temporal_limit': 'Constructive uniform divisible dispatch over T-L; constant whole-window capacity, deterministic link time, no fleet granularity or queues'}
    return following, output


def run_year(transport_module, *, calendar, initial_state, events, settlements, commodities, network,
             policy, source_binding_sha256, scenario_id, stop_after=None, resume=None):
    """Execute ordered windows; restart replays/validates the exact accepted prefix.

    Missing physical inputs stop this coupled stock chain and mark its suffix
    UNKNOWN, not zero. Malformed contracts raise. No partial event is committed.
    """
    source_binding_sha256 = _sha(source_binding_sha256); _id(scenario_id, 'scenario_id')
    payload = _plain(dict(calendar=calendar, initial_state=initial_state, events=events,
        settlements=settlements, commodities=commodities, network=network, policy=policy,
        source_binding_sha256=source_binding_sha256, scenario_id=scenario_id))
    input_hash = digest(payload)
    payload = copy.deepcopy(payload)
    calendar = payload['calendar']; events = payload['events']; network = payload['network']; policy = payload['policy']
    ss = _rows(payload['settlements'], 'settlement_id', 'settlements', 32)
    cs = _rows(payload['commodities'], 'commodity_id', 'commodities', 8)
    clocks = _rows(calendar, 'event_id', 'calendar', 366)
    if not ss or not cs or not clocks:
        raise HumanError('nonempty settlement/commodity/calendar required')
    if policy != {'allocation': 'MAX_WEIGHTED_DELIVERED_KG', 'hazard_combination': 'MIN_LIMITING',
                  'service_timing': 'END_WINDOW', 'storage_loss_timing': 'OPENING_BOUNDARY',
                  'population': 'FIXED', 'borders': 'FIXED'}:
        raise HumanError('explicit supported engineering policy required; no implicit fairness')
    node_ids = _rows(network.get('nodes'), 'node_id', 'network nodes', 32)
    for s, row in ss.items():
        if '::' in s or any('::' in c for c in cs):
            raise HumanError('reserved stock identity separator')
        _source(row)
        for key in ('support_id', 'border_id', 'receiving_sink_id'):
            _id(row.get(key), key)
        if row.get('node_id') not in node_ids:
            raise HumanError('settlement transport node missing')
        if type(row.get('population')) is not int or row['population'] < 0:
            raise HumanError('fixed nonnegative integer population required; no rate inferred')
        _keys(row.get('food_capacity_kg'), cs, 'food capacities')
        if not isinstance(row.get('exposure_rules'), list):
            raise HumanError('explicit exposure rules required')
    if len({s['node_id'] for s in ss.values()}) != len(ss):
        raise HumanError('this bounded adapter requires distinct settlement transport nodes')
    for c in cs.values():
        if c.get('unit') != 'kg' or c.get('mass_basis') != 'EDIBLE_DRY_FOOD_KG':
            raise HumanError('explicit edible dry-food kg commodity basis required')
    ordered_events = _rows(events, 'event_id', 'events', 366)
    if list(ordered_events) != list(clocks):
        raise HumanError('exact ordered calendar/event identity coverage required')
    clock_time = F(0)
    for row in calendar:
        _id(row.get('evidence_id'), 'calendar evidence')
        if _q(row.get('start_seconds'), 'start') != clock_time:
            raise HumanError('contiguous exact zero-based calendar required')
        clock_time += _q(row.get('duration_seconds'), 'duration', positive=True)
    initial = payload['initial_state']
    _keys(initial, ('water_m3', 'food_kg'), 'initial state')
    _keys(initial['water_m3'], ss, 'initial reservoir coverage'); _keys(initial['food_kg'], ss, 'initial food coverage')
    state = {'water_m3': {}, 'food_kg': {}, 'elapsed_seconds': '0', 'used_water_allocation_ids': [],
             'used_water_delivery_ids': [], 'used_harvest_ids': [], 'used_harvest_source_ids': []}
    try:
        for s, row in ss.items():
            water = _q(initial['water_m3'][s], 'initial water')
            if water > _q(row.get('water_capacity_m3'), 'water capacity'):
                raise HumanError('initial reservoir exceeds capacity')
            state['water_m3'][s] = str(water); state['food_kg'][s] = {}
            _keys(initial['food_kg'][s], cs, 'initial commodity stocks')
            for c in cs:
                mass = _q(initial['food_kg'][s][c], 'initial food')
                if mass > _q(row['food_capacity_kg'][c], 'food capacity'):
                    raise HumanError('initial food exceeds capacity')
                state['food_kg'][s][c] = str(mass)
    except MissingEvidence as exc:
        return {'schema': SCHEMA, 'status': 'UNKNOWN', 'source_status': STATUS, 'input_sha256': input_hash,
            'source_binding_sha256': source_binding_sha256, 'scenario_id': scenario_id,
            'state': None, 'accepted_events': 0, 'events': [{'event_id': r['event_id'], 'status': 'UNKNOWN', 'reason': str(exc)} for r in calendar],
            'checkpoint': None, 'fixed_settlements': list(ss.values())}
    if stop_after is not None and (type(stop_after) is not int or not 0 <= stop_after <= len(calendar)):
        raise HumanError('bounded stop_after event count required')
    limit = len(calendar) if stop_after is None else stop_after
    resume_count = 0
    if resume is not None:
        if not isinstance(resume, dict) or set(resume) != {'schema', 'input_sha256', 'source_binding_sha256', 'scenario_id', 'accepted_events', 'state', 'prefix_sha256'}:
            raise HumanError('exact human checkpoint schema required')
        if (resume['schema'] != 'diadem.seasonal-human-checkpoint.r11' or resume['input_sha256'] != input_hash
                or resume['source_binding_sha256'] != source_binding_sha256 or resume['scenario_id'] != scenario_id):
            raise HumanError('checkpoint input/source/scenario mismatch')
        resume_count = resume['accepted_events']
        if type(resume_count) is not int or not 0 <= resume_count <= limit:
            raise HumanError('checkpoint outside requested prefix')
        if resume_count == 0 and (resume['state'] != state or resume['prefix_sha256'] != digest([])):
            raise HumanError('initial checkpoint differs')
    outputs = []; status = 'COMPLETE' if limit == len(calendar) else 'PARTIAL'
    for index, clock in enumerate(calendar[:limit]):
        try:
            following, output = _event(transport_module, state, ordered_events[clock['event_id']], clock, ss, cs, network, scenario_id)
        except MissingEvidence as exc:
            status = 'UNKNOWN'
            outputs.extend({'event_id': c['event_id'], 'status': 'UNKNOWN', 'reason': str(exc) if j == index else 'causal stock predecessor unknown'}
                           for j, c in enumerate(calendar[index:], index))
            break
        except transport_module.TransportError as exc:
            status = 'OUTSIDE_REGIME'
            outputs.extend({'event_id': c['event_id'], 'status': status, 'reason': str(exc) if j == index else 'causal stock predecessor unsupported'}
                           for j, c in enumerate(calendar[index:], index))
            break
        state = following; outputs.append(output)
        if index+1 == resume_count and (resume['state'] != state or resume['prefix_sha256'] != digest(outputs)):
            raise HumanError('checkpoint replay state/prefix mismatch')
    accepted = sum(row['status'] == 'MODELLED' for row in outputs)
    if accepted < resume_count:
        raise HumanError('checkpoint prefix cannot be reproduced')
    checkpoint = {'schema': 'diadem.seasonal-human-checkpoint.r11', 'input_sha256': input_hash,
        'source_binding_sha256': source_binding_sha256, 'scenario_id': scenario_id, 'accepted_events': accepted,
        'state': copy.deepcopy(state), 'prefix_sha256': digest(outputs[:accepted])}
    return {'schema': SCHEMA, 'source_status': STATUS, 'status': status, 'input_sha256': input_hash,
        'source_binding_sha256': source_binding_sha256, 'scenario_id': scenario_id, 'state': state,
        'events': outputs, 'accepted_events': accepted, 'checkpoint': checkpoint,
        'fixed_settlements': list(ss.values()), 'policy': policy,
        'objective_scope': 'R2 weighted objective applies only AFTER explicit local-priority service and protected reserves; not global annual optimisation',
        'scope': 'Finite stocks, end-window service and aggregate shared transport constraints; not daily security, demographics, prices or hazard probabilities',
        'source_inputs': payload}


def reference_inputs(*, calendar=None, source_binding_sha256='0'*64, scenario_id='SYNTHETIC_HUMAN_REFERENCE', commodity_id='synthetic-food'):
    """Explicit, labelled two-node engineering fixture; NOT Diadem coefficients."""
    e = 'SYNTHETIC TEST: finite-stock analytical reference, not adopted geography'
    if calendar is None:
        calendar = [{'event_id': 'window-1', 'start_seconds': '0', 'duration_seconds': '10', 'evidence_id': e},
                    {'event_id': 'window-2', 'start_seconds': '10', 'duration_seconds': '10', 'evidence_id': e}]
    settlements = [{'settlement_id': s, 'node_id': s, 'support_id': s, 'border_id': 'fixed-border-'+s,
        'receiving_sink_id': 'water-sink-'+s, 'population': 10, 'water_capacity_m3': '20',
        'food_capacity_kg': {'grain': '100'}, 'exposure_rules': [], 'evidence_id': e,
        'source_status': 'SYNTHETIC TEST'} for s in ('upper', 'lower')]
    rule = {'commodity_id': 'grain', 'allowed': True, 'loss_fraction': '1/10',
        'capacity_uses': [{'group_id': 'shared-road', 'load_kg_per_kg_entering': '1', 'evidence_id': e}], 'evidence_id': e}
    network = {'nodes': [{'node_id': s, 'mode': 'LAND', 'evidence_id': e} for s in ('upper', 'lower')],
        'links': [{'link_id': a+'-to-'+b, 'from_node': a, 'to_node': b, 'kind': 'TRAVEL', 'travel_time_s': '1',
                   'available': True, 'rules': [copy.deepcopy(rule)], 'evidence_id': e} for a, b in [('upper','lower'), ('lower','upper')]],
        'capacity_groups': [{'group_id': 'shared-road', 'capacity_rate_kg_s': '1', 'hazard_rules': [], 'evidence_id': e}],
        'network_complete': True, 'evidence_id': e, 'objective_evidence_id': e,
        'capacity_representation': {'method':'EXACT_OR_DYADIC_INNER','quantum_kg':'1/1099511627776',
            'max_absolute_loss_kg':'1/1099511627776','source_status':'SYNTHETIC TEST',
            'evidence_id':'Explicit numerical inner-capacity control, not altered weather/physical capacity; floor only when retained R2 input representation requires it'}}
    events = []
    for clock in calendar:
        eid = clock['event_id']
        events.append({'event_id': eid, 'water_deliveries': [], 'harvests': [], 'hazard_observations': {},
            'water_loss_fraction': {'upper': '0', 'lower': '0'},
            'food_loss_fraction': {'upper': {'grain': '0'}, 'lower': {'grain': '0'}},
            'protected_food_reserve_kg': {'upper': {'grain': '0'}, 'lower': {'grain': '0'}},
            'water_demands': [{'demand_id': eid+'-water-'+s, 'settlement_id': s, 'required_m3': '4',
                'evidence_id': e, 'source_status': 'SYNTHETIC TEST'} for s in ('upper','lower')],
            'water_demand_order': [eid+'-water-'+s for s in ('upper','lower')],
            'food_demands': [{'demand_id': eid+'-food-lower', 'settlement_id': 'lower', 'commodity_id': 'grain',
                'required_kg': '12', 'weight_per_kg': '1', 'evidence_id': e, 'source_status': 'SYNTHETIC TEST'}],
            'food_demand_order': [eid+'-food-lower']})
    result = {'calendar': copy.deepcopy(calendar), 'initial_state': {'water_m3': {'upper': '6', 'lower': '2'},
        'food_kg': {'upper': {'grain': '30'}, 'lower': {'grain': '0'}}}, 'events': events,
        'settlements': settlements, 'commodities': [{'commodity_id': 'grain', 'mass_basis': 'EDIBLE_DRY_FOOD_KG', 'unit': 'kg', 'evidence_id': e}],
        'network': network, 'policy': {'allocation': 'MAX_WEIGHTED_DELIVERED_KG', 'hazard_combination': 'MIN_LIMITING',
            'service_timing': 'END_WINDOW', 'storage_loss_timing': 'OPENING_BOUNDARY', 'population': 'FIXED', 'borders': 'FIXED'},
        'source_binding_sha256': source_binding_sha256, 'scenario_id': scenario_id}
    _id(commodity_id, 'synthetic commodity identity')
    # Internal template uses grain only as an arbitrary test key; the public
    # reference does not turn temperate forest biomass into a cereal crop.
    def rename(value):
        if isinstance(value, dict):
            return {(commodity_id if k == 'grain' else k): rename(v) for k,v in value.items()}
        if isinstance(value, list):
            return [rename(v) for v in value]
        return commodity_id if value == 'grain' else value
    return rename(result)
