"""Opening-stock local food accounts over explicit contiguous demand windows.

Only actual crop harvest events enter supply. A harvest arriving within a window
is closing carry, not food available at its opening. Source-attributed settlement
IDs are accounting sinks, NOT evidence of freight. Free and reserved carry have
no implicit spoilage, shipping or reserve release; physical storage suitability
is not certified by this bookkeeping model. Past shortages are never backfilled.
"""
from fractions import Fraction as F
import json

from . import _native_food as native, _native_human as human
from .quantities import q, exact, ident, plain

SCHEMA = 'diadem.temporal-local-food-accounts.r21'
MAX_HARVESTS, MAX_WINDOWS, MAX_ROWS, MAX_BYTES = 4096, 366, 65536, 8*1024*1024


def _copy(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError('finite JSON food input required') from exc
    if len(raw.encode()) > MAX_BYTES:
        raise ValueError('food input exceeds 8 MiB envelope')
    return json.loads(raw)


def _rows(value, label, maximum=4096):
    if type(value) is not list or len(value) > maximum:
        raise ValueError('bounded explicit '+label+' list required')
    return value


def _nullable(value):
    return None if value is None else q(value)


def _bundles(rows):
    result = []
    for row in _rows(rows, 'food bundles', 64):
        exact(row, native.FoodBundle.__dataclass_fields__, 'food bundle')
        components = []
        for item in _rows(row['components'], 'bundle components', 64):
            exact(item, native.FoodComponent.__dataclass_fields__, 'food component')
            components.append(native.FoodComponent(item['commodity_id'], _nullable(item['energy_share']),
                _nullable(item['edible_energy_kcal_kg']), item['composition_evidence']))
        result.append(native.FoodBundle(row['bundle_id'], tuple(components),
            _nullable(row['energy_kcal_person_day']), row['diet_evidence'], row['source_status']))
    if len({row.bundle_id for row in result}) != len(result):
        raise ValueError('duplicate food bundle identity')
    return tuple(result)


def _harvests(rows, densities):
    rows = _rows(rows, 'actual crop harvests', MAX_HARVESTS)
    if type(densities) is not dict or set(densities) != {row.get('harvest_id') for row in rows if type(row) is dict}:
        raise ValueError('exact kcal/kg composition for every harvest required')
    seen, source_uses, signatures, composition, result = set(), set(), set(), {}, []
    for row in rows:
        if type(row) is not dict:
            raise ValueError('actual native crop harvest object required')
        human._source(row)
        if row['source_status'] != human.STATUS or row.get('preview_only') or row.get('hypothetical'):
            raise ValueError('unchanged actual native harvest status required, not a promoted/preview stock')
        for key in ('harvest_id', 'settlement_id', 'commodity_id', 'support_id', 'source_event_id', 'source_use_id'):
            human._id(row.get(key), key)
        digest = human._sha(row.get('source_input_sha256'))
        identity, use = row['harvest_id'], row['source_use_id']
        signature = (digest, row['source_event_id'], row['support_id'])
        if identity in seen or use in source_uses or signature in signatures:
            raise ValueError('harvest/source use already imported, including renamed producer events')
        seen.add(identity); source_uses.add(use); signatures.add(signature)
        if row.get('mass_basis') != 'EDIBLE_DRY_FOOD_KG':
            raise ValueError('native edible dry food mass basis required')
        available = q(row.get('available_at_seconds'), 'harvest availability')
        after = q(row.get('available_after_seconds'), 'producer closing time')
        if available < after:
            raise ValueError('harvest cannot predate producer availability')
        conversion = row.get('conversion')
        if (type(conversion) is not dict or conversion.get('producer_kind') not in (
                'ACTUAL_R1_DAILY_CROP; carbon here is only an exact cancelling conversion intermediary',
                'ACTUAL_R13_COUPLED_SOIL_CROP_YIELD')):
            raise ValueError('actual native crop conversion required, not a forecast')
        producer, coefficients = conversion.get('producer'), conversion.get('coefficients')
        if type(producer) is not dict or type(coefficients) is not dict:
            raise ValueError('complete actual crop/conversion provenance required')
        human._source(producer); human._source(coefficients)
        if conversion['producer_kind'] == 'ACTUAL_R13_COUPLED_SOIL_CROP_YIELD':
            physical = producer.get('crop_receipt')
            if (type(physical) is not dict or physical.get('schema') != 'diadem.coupled-soil-crop-yield.r21'
                    or physical.get('status') != 'MODELLED' or physical.get('crop_id') != row['source_event_id']
                    or type(physical.get('et_compatibility')) is not dict):
                raise ValueError('actual supported R13 crop-yield receipt required')
            human._sha(physical.get('soil_input_sha256'))
            if not 0 <= q(physical.get('actual_to_potential_et_ratio')) <= 1:
                raise ValueError('physical crop actual/potential ratio outside its declared range')
            if q(producer.get('harvested_carbon_kg_m2')) != q(physical.get('yield_kg_m2'))*q(coefficients.get('carbon_fraction_dry_matter')):
                raise ValueError('physical crop harvest differs from its actual source yield')
        if (producer.get('status') != 'MODELLED' or producer.get('source_input_sha256') != digest
                or producer.get('source_use_id') != use or producer.get('event_id') != row['source_event_id']
                or producer.get('support_id') != row['support_id']
                or q(producer.get('available_after_seconds')) != after
                or coefficients.get('mass_basis') != row['mass_basis']):
            raise ValueError('native harvest differs from its explicit producer binding')
        dry, nonfood, loss, edible, carbon = (q(conversion.get(key), key) for key in (
            'harvested_dry_biomass_kg', 'nonfood_dry_biomass_kg', 'processing_loss_kg',
            'edible_food_kg', 'harvested_carbon_kg'))
        cf = q(coefficients.get('carbon_fraction_dry_matter'), positive=True)
        fraction = q(coefficients.get('edible_fraction'))
        loss_fraction = q(coefficients.get('processing_loss_fraction'))
        if cf > 1 or fraction > 1 or loss_fraction > 1:
            raise ValueError('food conversion fractions exceed one')
        quantity = q(row.get('quantity_kg'), 'actual available edible kg')
        if (dry != nonfood+loss+edible or dry*cf != carbon or nonfood != dry*(1-fraction)
                or loss != dry*fraction*loss_fraction or quantity != edible
                or q(conversion.get('dry_mass_residual_kg')) != 0):
            raise ValueError('actual native dry/edible harvest mass partition does not close exactly')
        density = q(densities[identity], 'edible energy kcal/kg', positive=True)
        commodity = row['commodity_id']
        if commodity in composition and composition[commodity] != density:
            raise ValueError('one commodity cannot have conflicting harvest energy densities')
        composition[commodity] = density
        if 'edible_energy_kcal' in row and q(row['edible_energy_kcal']) != quantity*density:
            raise ValueError('explicit kcal/kg density differs from actual harvest energy')
        result.append({'harvest': row, 'quantity': quantity, 'density': density, 'available': available,
            'event_key': 'native-crop-event:'+human.digest(list(signature))})
    return sorted(result, key=lambda row: (row['available'], row['harvest']['harvest_id']))


def account(harvests, *, energy_by_harvest, windows, bundles, calendar, evidence, source_status):
    """Use unchanged R2 native accounts with cumulative exact per-lot debits.

Bundles, obligations and policies are full JSON-shaped native dataclass fields.
Calendar is {days_per_year, day_duration_seconds, evidence}; each window is
{id,start_seconds,end_seconds,obligations,policies}. Atomic obligation/claim IDs
are globally unique window-specific slices. Each harvest/source event is admitted
once, including across commodities or renamed stock IDs. No external inventory
or annual-harvest conversion is inferred. All output quantities are exact strings.
"""
    data = _copy({'harvests': harvests, 'energy': energy_by_harvest, 'windows': windows,
                  'bundles': bundles, 'calendar': calendar, 'evidence': evidence, 'source_status': source_status})
    ident(data['evidence'], 'food-account scenario evidence')
    if source_status not in ('WORKING NON-CANON', 'SYNTHETIC TEST'):
        raise ValueError('explicit working/synthetic food-account scenario required')
    exact(data['calendar'], {'days_per_year', 'day_duration_seconds', 'evidence'}, 'calendar')
    year_days = q(data['calendar']['days_per_year'], positive=True)
    day_seconds = q(data['calendar']['day_duration_seconds'], positive=True)
    year_seconds = q(year_days*day_seconds, 'declared year seconds', positive=True)
    ident(data['calendar']['evidence'], 'calendar evidence')
    foods = _bundles(data['bundles'])
    events = _harvests(data['harvests'], data['energy'])
    composition = {event['harvest']['commodity_id']: event['density'] for event in events}
    for bundle in foods:
        for component in bundle.components:
            density = component.edible_energy_kcal_kg
            if density is not None:
                if component.commodity_id in composition and composition[component.commodity_id] != density:
                    raise ValueError('bundle composition differs from explicit actual harvest kcal/kg')
                composition[component.commodity_id] = density
    source_keys = [key for event in events for key in (event['harvest']['source_use_id'], event['event_key'])]
    if len(set(source_keys)) != len(source_keys):
        raise ValueError('duplicate original/derived physical source-use identity')
    parsed, window_ids, obligation_ids, claims, before, total_rows = [], set(), set(), set(), None, 0
    for window in _rows(data['windows'], 'demand windows', MAX_WINDOWS):
        exact(window, {'id', 'start_seconds', 'end_seconds', 'obligations', 'policies'}, 'food window')
        identity = ident(window['id'], 'window ID')
        start, end = q(window['start_seconds']), q(window['end_seconds'])
        if identity in window_ids or end <= start or (before is not None and start != before):
            raise ValueError('unique contiguous increasing half-open demand windows required')
        window_ids.add(identity); before = end
        obligations, policies = [], []
        for row in _rows(window['obligations'], 'obligations'):
            exact(row, native.Obligation.__dataclass_fields__, 'obligation')
            _rows(row['component_claim_ids'], 'claim identities')
            obligation = native.Obligation(row['obligation_id'], row['node_id'], row['bundle_id'],
                row['kind'], row['recurrence'], row['amount_unit'], _nullable(row['amount']),
                tuple(row['component_claim_ids']), row['evidence'], row['source_status'])
            if obligation.obligation_id in obligation_ids or claims & set(obligation.component_claim_ids):
                raise ValueError('obligation/atomic claim already used in another demand window')
            obligation_ids.add(obligation.obligation_id); claims.update(obligation.component_claim_ids)
            obligations.append(obligation)
        for row in _rows(window['policies'], 'local policies'):
            exact(row, native.LocalPolicy.__dataclass_fields__, 'local policy')
            _rows(row['protected_order'], 'protected kinds'); _rows(row['obligation_order'], 'obligation priority')
            policy = native.LocalPolicy(row['node_id'], tuple(row['protected_order']), tuple(row['obligation_order']),
                                       row['block_export_on_shortfall'], row['evidence'])
            policies.append(policy)
        # This local-only stage cannot fulfil unprotected residual commitments.
        # Native accounts retain them as exact unmet demands, not hidden exports.
        parsed.append((window, start, end, tuple(obligations), tuple(policies)))
        total_rows += len(obligations)+len(policies)
    if not parsed or total_rows > MAX_ROWS:
        raise ValueError('bounded nonempty temporal food account required')
    period_status = ('SYNTHETIC TEST' if source_status == 'SYNTHETIC TEST' and all(
        event['harvest']['source_status'] == 'SYNTHETIC TEST' for event in events) else 'WORKING NON-CANON')
    admitted, cursor, debits, debit_receipts, consumed, reserved = {}, 0, [], [], {}, {}
    receipts, ledger_rows = [], 0

    def admit(at):
        nonlocal cursor
        added = []
        while cursor < len(events) and events[cursor]['available'] <= at:
            event = events[cursor]; cursor += 1
            hid = event['harvest']['harvest_id']
            if hid in admitted:
                raise ValueError('physical harvest reimported across demand windows')
            admitted[hid] = event; consumed[hid] = F(0); reserved[hid] = F(0); added.append(hid)
        return added

    def stock_ledger():
        rows = []
        for hid, event in sorted(admitted.items()):
            free = q(event['quantity']-consumed[hid]-reserved[hid], 'remaining freely available stock')
            rows.append({'harvest_id': hid, 'source_use_id': event['harvest']['source_use_id'],
                'producer_event_key': event['event_key'], 'settlement_id': event['harvest']['settlement_id'],
                'commodity_id': event['harvest']['commodity_id'], 'available_at_seconds': event['available'],
                'initial_edible_kg': event['quantity'], 'consumed_kg': consumed[hid],
                'reserved_carry_kg': reserved[hid], 'free_carry_kg': free, 'residual_kg': F(0)})
        return rows

    base = {'schema': SCHEMA, 'source_status': period_status, 'input_source_status': source_status,
        'input_sha256': human.digest(data), 'evidence': evidence, 'calendar': data['calendar'],
        'local_attribution_not_freight': True, 'transport_solved': False, 'physical_storage_accepted': False,
        'shortages_retroactively_fulfilled': False, 'reserve_release_or_spoilage_inferred': False,
        'supply_inferred_from_demand': False}
    for window, start, end, obligations, policies in parsed:
        opening_arrivals = admit(start)
        period = native.Period(window['id'], q((end-start)/year_seconds), year_days,
                               data['calendar']['evidence'], period_status)
        stocks = []
        for hid, event in sorted(admitted.items()):
            row = event['harvest']; conversion = row['conversion']
            stocks.append(native.FoodStock(hid, row['settlement_id'], row['commodity_id'], window['id'],
                event['quantity'], event['density'], 'harvest', row['source_input_sha256'],
                (row['source_use_id'], event['event_key']),
                ('actual crop support '+row['support_id'], 'native crop/conversion '+human.digest(conversion),
                 'native irrigation/depletion evidence '+human.digest(conversion.get('irrigation_debits', []))),
                row['evidence_id'], row['source_status']))
        ledger_rows += len(stocks)+len(debits)+len(obligations)
        if ledger_rows > MAX_ROWS:
            raise ValueError('temporal native-account row envelope exceeded')
        accounts = native.prepare_accounts(tuple(stocks), obligations, foods, period, policies,
                                          prior_debits=tuple(debits), source_ledger_complete=True)
        if accounts['status'] != 'ACCOUNTED':
            return plain({**base, 'status': 'UNKNOWN', 'completed_windows': receipts,
                'unresolved_window_id': window['id'], 'unresolved': accounts['unresolved'],
                'final_stock_ledger': None, 'scope': 'accepted prefix only; unresolved demand is not zero'})
        by_obligation = {row.obligation_id: row for row in obligations}
        new_debits = []
        for use in accounts['local_uses']:
            hid = use['stock_id']; obligation = by_obligation[use['obligation_id']]
            amount = q(use['quantity_kg'])
            disposition = use['disposition']
            target = reserved if disposition == 'reserved_stock' else consumed
            target[hid] = q(target[hid]+amount, 'cumulative food disposition')
            debit_id = 'r21-food-use:'+human.digest({'window': window['id'], 'use': use})
            # Native atomic debit IDs name disjoint ACTUAL lot-use slices. The
            # original input claim IDs remain attached, and cannot recur later.
            slice_ids = ('r21-food-lot-slice:'+human.digest({'use_id': debit_id,
                'original_claims': obligation.component_claim_ids}),)
            if claims & set(slice_ids):
                raise ValueError('supplied claim collides with a derived physical lot-use slice')
            debit = native.StockDebit(debit_id, hid, amount, obligation.kind, slice_ids, evidence)
            debits.append(debit)
            receipt = {'use_id': debit_id, 'harvest_id': hid, 'window_id': window['id'],
                'obligation_id': obligation.obligation_id, 'commodity_id': use['commodity_id'],
                'quantity_kg': amount, 'kind': obligation.kind, 'disposition': disposition,
                'component_claim_ids': list(slice_ids),
                'original_obligation_component_claim_ids': list(obligation.component_claim_ids),
                'slice_meaning': 'DISJOINT_ACTUAL_PHYSICAL_LOT_USE; NOT_AN_EXTRA_DEMAND_OR_HARVEST'}
            debit_receipts.append(receipt); new_debits.append(receipt)
        for row in accounts['stock_ledger']:
            hid = row['stock_id']; event = admitted[hid]
            free = event['quantity']-consumed[hid]-reserved[hid]
            if free < 0 or row['held_kg']+row['exportable_kg'] != free:
                raise ArithmeticError('native accounts differ from cumulative exact edible-stock carry')
        closing_arrivals = admit(end)
        receipts.append({'window_id': window['id'], 'start_seconds': start, 'end_seconds': end,
            'opening_arrivals': opening_arrivals, 'opening_harvest_ids': [stock.stock_id for stock in stocks],
            'closing_arrivals': closing_arrivals, 'native_accounts': native.exact_json(accounts),
            'new_debits': new_debits, 'shortages': accounts['remaining_demands'],
            'exportable_offers': [{'harvest_id': row['stock_id'], 'commodity_id': row['commodity_id'],
                'settlement_id': row['node_id'], 'quantity_kg': row['exportable_kg'],
                'dispatched_kg': F(0)} for row in accounts['stock_ledger']],
            'closing_stock_ledger': stock_ledger()})
    final = stock_ledger()
    total_initial = q(sum((row['initial_edible_kg'] for row in final), F(0)))
    totals = {key: q(sum((row[key] for row in final), F(0))) for key in
              ('consumed_kg', 'reserved_carry_kg', 'free_carry_kg')}
    if total_initial != sum(totals.values(), F(0)):
        raise ArithmeticError('temporal food stock conservation failed')
    return plain({**base, 'status': 'ACCOUNTED', 'windows': receipts, 'final_stock_ledger': final,
        'debit_ledger': debit_receipts, 'used_harvest_ids': sorted(admitted),
        'used_source_use_ids': sorted(event['harvest']['source_use_id'] for event in admitted.values()),
        'used_obligation_ids': sorted(obligation_ids), 'used_input_claim_ids': sorted(claims),
        'pending_harvest_ids': [event['harvest']['harvest_id'] for event in events[cursor:]],
        'totals': {'initial_admitted_edible_kg': total_initial, **totals, 'residual_kg': F(0)},
        'scope': 'exact local opening-stock allocation and unshipped carry; no retroactive demand, storage physics or freight claim'})
