"""Actual harvest -> separate food accounts -> shared lossy commodity transport.

Supplied diets/priorities/networks are hypotheses, not adopted Diadem defaults.
The sequential crop allocation is not a joint production/distribution optimum.
"""
from fractions import Fraction as F
from decimal import Decimal
import json

from . import food_accounting as food
from . import multicommodity as transport


def demand_id(obligation_id, commodity_id):
    return json.dumps([obligation_id,commodity_id],separators=(',',':'),ensure_ascii=True)


def food_delivery_snapshot(food_budget, harvest_bindings, *, period, day_duration_seconds, day_duration_evidence, source_id,
        inventory_stocks, obligations, bundles, policies, prior_debits, source_ledger_complete,
        nodes, commodities, links, capacity_groups, objective, demand_weights,
        network_complete, evidence):
    """Bind exact edible kg and one explicit annual calendar at each boundary.

    Weights cover each (obligation_id, commodity_id), including zero remainder.
    Delivered reserves remain reserves, not recurring consumption. Previous stock
    debits remain charged and cannot reappear as exported harvest. No shipping
    schedule, multi-year inventory, diet sufficiency or observed harvest is claimed.
    """
    if type(day_duration_evidence) is not str or not day_duration_evidence.strip() or len(day_duration_evidence)>4096:
        raise ValueError('explicit calendar day-duration evidence required')
    if day_duration_seconds is not None:
        if type(day_duration_seconds) not in (int,float,F,Decimal):
            raise ValueError('explicit positive finite day duration required')
        try:day_duration_seconds=F(day_duration_seconds)
        except (ValueError,OverflowError) as exc:raise ValueError('nonfinite day duration') from exc
        if day_duration_seconds<=0 or max(day_duration_seconds.numerator.bit_length(),day_duration_seconds.denominator.bit_length())>128:
            raise ValueError('day duration outside supported bounds')
    imported=food.stocks_from_food_budget(food_budget,harvest_bindings,period,
        source_id=source_id,one_representative_harvest_in_period=True)
    base={'schema':'diadem.crop-account-delivery-snapshot.r2',
          'source_status':'WORKING NON-CANON','harvest_import':imported,
          'period_id':period.period_id,'day_duration_seconds':day_duration_seconds,
          'day_duration_evidence':day_duration_evidence,'accounts':None,'transport':None,
          'production_installed':False,'physical_acceptance':False,
          'joint_crop_transport_optimum':False,'population_capacity_claim':False}
    if imported['status']!='IMPORTED':
        return {**base,'status':'UNKNOWN','unresolved':imported['unresolved']}
    if not isinstance(inventory_stocks,(tuple,list)):
        raise ValueError('explicit additional physical inventory required')
    stocks=(*imported['stocks'],*inventory_stocks)
    accounts=food.prepare_accounts(stocks,obligations,bundles,period,policies,
        prior_debits=prior_debits,source_ledger_complete=source_ledger_complete)
    base['accounts']=accounts
    if accounts['status']!='ACCOUNTED':
        return {**base,'status':'UNKNOWN','unresolved':accounts['unresolved']}
    if day_duration_seconds is None:
        return {**base,'status':'UNKNOWN','unresolved':['calendar day duration']}
    commodity_ids={s.commodity_id for s in stocks}|{r['commodity_id'] for r in accounts['remaining_demands']}
    if (not isinstance(commodities,(tuple,list)) or any(type(c) is not transport.Commodity for c in commodities)
            or len({c.commodity_id for c in commodities})!=len(commodities)
            or {c.commodity_id for c in commodities}!=commodity_ids
            or any(c.mass_basis!='available_edible_kg' or c.unit!='kg' for c in commodities)):
        raise ValueError('transport must bind exactly the accounted edible-kg commodities')
    keys={(r['obligation_id'],r['commodity_id']) for r in accounts['remaining_demands']}
    if type(demand_weights) is not dict or set(demand_weights)!=keys:
        raise ValueError('explicit objective weight for every remaining commodity obligation required')
    composition={s.commodity_id:s.edible_energy_kcal_kg for s in stocks}
    composition.update({c.commodity_id:c.edible_energy_kcal_kg for b in bundles for c in b.components})
    seconds=period.duration_years*period.days_per_year*day_duration_seconds
    demands=[transport.Demand(demand_id(r['obligation_id'],r['commodity_id']),r['node_id'],r['commodity_id'],
        r['quantity_kg'],demand_weights[r['obligation_id'],r['commodity_id']],period.period_id,evidence)
        for r in accounts['remaining_demands']]
    exports=[transport.Stock(r['stock_id'],r['node_id'],r['commodity_id'],r['exportable_kg'],period.period_id,evidence)
        for r in accounts['stock_ledger']]
    result=transport.solve_multicommodity(nodes,commodities,exports,demands,links,capacity_groups,
        period=transport.Period(period.period_id,seconds),objective=objective,
        network_complete=network_complete,evidence_id=evidence)
    base['transport']=result
    if not result['solved']:
        return {**base,'status':result['status'],'closure':None}
    delivered={r['demand_id']:r for r in result['demands']}
    shipped={r['stock_id']:r for r in result['stocks']}
    closure=[]
    for row in accounts['stock_ledger']:
        exported=shipped[row['stock_id']]
        used=F(exported['used_kg']['exact']);unused=F(exported['unused_kg']['exact'])
        residual=row['initial_kg']-sum((row[k] for k in ('prior_debit_kg','consumed_kg','reserved_kg','held_kg')),F())-used-unused
        if residual or used+unused!=row['exportable_kg']:
            raise ArithmeticError('integrated source stock mass failed exact conservation')
        closure.append({**row,'dispatched_kg':used,'unshipped_export_stock_kg':unused,'integrated_residual_kg':residual})
    fulfilment=[]
    for row in accounts['remaining_demands']:
        route=delivered[demand_id(row['obligation_id'],row['commodity_id'])]
        received=F(route['delivered_kg']['exact'])
        local=sum((u['quantity_kg'] for u in accounts['local_uses']
            if u['obligation_id']==row['obligation_id'] and u['commodity_id']==row['commodity_id']),F())
        disposition=('reserved_stock' if row['kind']=='one_off_reserve' else
                     'consumption_allocation' if row['kind']=='recurring_consumption' else 'delivered_commitment')
        fulfilment.append({**row,'local_allocated_kg':local,'network_delivered_kg':received,
            'fulfilled_kg':local+received,'shortage_kg':F(route['shortage_kg']['exact']),
            'fulfilled_energy_kcal':(local+received)*composition[row['commodity_id']],
            'disposition':disposition,'physically_consumed_observation':False})
    return {**base,'status':'ACCOUNTED_AND_TRANSPORT_SOLVED','period_seconds':seconds,
            'closure':closure,'obligation_fulfilment':fulfilment,
            'scope':'one supplied annual fixed-snapshot hypothesis; exact represented mass, not scientific or site acceptance'}
