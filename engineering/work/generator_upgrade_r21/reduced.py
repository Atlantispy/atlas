"""Finite shared irrigation for the separate REDUCED_ROOT_ZONE_REFERENCE.

The declared ideal connector has no rate cap/refill or hydraulic simulation.
All contemporaneous requests are rationed before a single source debit. Its
explicit efficiency partitions that debit into certified net root-zone arrival
and a finite, unclassified loss which can never be reused in this reference.
This is not the R13 physical soil path and does not authenticate owner geography.
"""
from copy import deepcopy
from fractions import Fraction as F

from . import crops, irrigation, provenance as p
from .quantities import exact, ident, plain, q


ENGINE = 'REDUCED_ROOT_ZONE_REFERENCE'
CONNECTION = 'DECLARED_INSTANTANEOUS_ROOT_ZONE_REFERENCE_NO_REFILL'
WATER_FIELDS = {'source_id', 'initial_stock_m3', 'evidence', 'source_status', 'connection_law'}


def run(plans, water):
    """Execute fixed whole-plot plans against one exact finite source stock.

    Plot geometry/permission is admitted upstream. Sorting makes the receipt
    canonical, not priority-ordered; irrigation.ration handles simultaneous use.
    No aggregate annual area allocation, refill or implicit return-flow credit.
    """
    if type(plans) is not list or not 1 <= len(plans) <= 32:
        raise ValueError('1..32 explicit fixed whole-plot plans required')
    if len(p.encoded({'plans': plans, 'water': water})) > 8*1024*1024:
        raise ValueError('bounded reduced crop/water input required')
    copied = [crops._plan(plan) for plan in plans]
    copied.sort(key=lambda plan: (plan['support_id'], plan['plan_id']))
    water = deepcopy(water)
    exact(water, WATER_FIELDS, 'finite reduced irrigation source')
    for field in ('source_id', 'evidence', 'source_status', 'connection_law'):
        ident(water[field], field)
    if water['connection_law'] != CONNECTION:
        raise ValueError('explicit no-refill instantaneous reduced connection law required')
    if water['source_status'] not in crops.STATUSES:
        raise ValueError('explicit water source status required')
    supports = [plan['support_id'] for plan in copied]
    if len(set(supports)) != len(supports) or len({plan['plan_id'] for plan in copied}) != len(copied):
        raise ValueError('one unique pre-planted plan per distinct physical plot required')
    clock = (F(copied[0]['season_start_seconds']), F(copied[0]['day_duration_seconds']), len(copied[0]['daily_forcing']))
    if any((F(plan['season_start_seconds']), F(plan['day_duration_seconds']), len(plan['daily_forcing'])) != clock for plan in copied):
        raise ValueError('all contemporaneous plans must have the same complete daily clock')
    if any(plan['delivery_boundary'] != 'ROOT_ZONE_NET' for plan in copied):
        raise ValueError('reduced ideal connection requires ROOT_ZONE_NET plans')
    unknown = crops._unknowns({'plans': copied, 'water': water})
    if unknown:
        initial = None if water['initial_stock_m3'] is None else str(q(water['initial_stock_m3']))
        return {'engine': ENGINE, 'status': 'UNKNOWN', 'crops': [], 'reasons': unknown,
                'physical_hydraulics_executed': False,
                'water': {'days': [], 'initial_stock_m3': initial, 'remaining_stock_m3': initial,
                          'total_withdrawal_m3': '0', 'total_net_m3': '0', 'loss_m3': '0', 'residual_m3': '0',
                          'execution': 'NOT_STARTED_UNRESOLVED_INPUTS'}}
    execution = p.identity()
    identity = p.sha({'engine': ENGINE, 'plans': copied, 'water': water})
    initial = remaining = q(water['initial_stock_m3'], 'finite initial source stock')
    demands = {plan['support_id']: crops._demands(plan) for plan in copied}
    by_plot = {plan['support_id']: [] for plan in copied}
    plan_by_plot = {plan['support_id']: plan for plan in copied}
    days, total_net, total_loss, withdrawal = [], q(0), q(0), q(0)
    for day_index in range(clock[2]):
        at = q(clock[0]+day_index*clock[1], 'daily source withdrawal time')
        requests = []
        for plan in copied:
            plot = plan['support_id']
            requests.append({'request_id': 'request-'+p.sha({'input': identity, 'plot': plot, 'day': day_index}),
                'plot_id': plot, 'source_id': water['source_id'],
                'connection_id': 'connection-'+p.sha({'source': water['source_id'], 'sink': plan['irrigation_sink_id']}),
                'requested_m3': demands[plot][day_index]['gross_delivery_m3']})
        opening = remaining
        ration = irrigation.ration(str(opening), requests)
        debit = q(ration['ledger']['allocated_m3'])
        remaining = q(opening-debit, 'remaining finite source stock')
        if remaining != q(ration['ledger']['remaining_stock_m3']):
            raise ArithmeticError('source debit differs from common simultaneous ration')
        # Commit ONE debit, then subdivide that already-debited volume into
        # terminal receipts. Source and net arrival must not both be debited.
        debit_record = {'input_sha256': identity, 'execution_binding_sha256': p.sha(execution),
            'source_id': water['source_id'], 'day_index': day_index, 'at_seconds': str(at),
            'opening_stock_m3': str(opening), 'withdrawal_m3': str(debit),
            'remaining_stock_m3': str(remaining), 'ration': ration, 'connection_law': CONNECTION}
        debit_sha = p.sha(debit_record)
        receipts, day_net, day_loss, terminal_total = [], q(0), q(0), q(0)
        for allocation in ration['allocations']:
            plan = plan_by_plot[allocation['plot_id']]
            gross = q(allocation['allocated_m3'])
            efficiency = q(plan['application_efficiency'], positive=True)
            net, loss = q(gross*efficiency), q(gross*(1-efficiency))
            day_net, day_loss = q(day_net+net), q(day_loss+loss)
            terminal_total = q(terminal_total+gross)
            if not gross:
                continue
            delivery_id = 'delivery-'+p.sha({'debit': debit_sha, 'request_id': allocation['request_id']})
            row = {'allocation_id': allocation['request_id'], 'delivery_id': delivery_id,
                'kind': 'ROUTED_WITHDRAWAL_DELIVERY', 'status': 'MODELLED',
                'source_id': water['source_id'], 'source_input_sha256': debit_sha,
                'source_debit_sha256': debit_sha, 'support_id': plan['support_id'],
                'receiving_sink_id': plan['irrigation_sink_id'], 'day_index': day_index,
                'available_after_seconds': str(at), 'delivered_volume_m3': str(gross),
                'application_efficiency': plan['application_efficiency'],
                'application_evidence': plan['application_evidence'], 'delivery_boundary': 'ROOT_ZONE_NET',
                'evidence_id': water['evidence'], 'source_status': water['source_status'],
                'connection_law': CONNECTION, 'physical_hydraulics_executed': False,
                'record_kind_scope': 'native delivery-compatible receipt of executed declared ideal connector, not native routed hydraulics',
                'net_root_zone_m3': str(net), 'loss_m3': str(loss),
                'loss_destination': 'UNCLASSIFIED_NONREUSABLE_REFERENCE_LOSS'}
            receipts.append(row); by_plot[plan['support_id']].append(row)
        if terminal_total != debit or day_net+day_loss != debit or opening != remaining+debit:
            raise ArithmeticError('exact daily finite-stock/delivery/loss account failed')
        days.append({'day_index': day_index, 'at_seconds': str(at), 'source_debit': debit_record,
            'source_debit_sha256': debit_sha, 'deliveries': receipts,
            'net_root_zone_m3': str(day_net), 'loss_m3': str(day_loss), 'residual_m3': '0'})
        withdrawal, total_net, total_loss = q(withdrawal+debit), q(total_net+day_net), q(total_loss+day_loss)
    results = [crops.realise(plan, by_plot[plan['support_id']]) for plan in copied]
    observed_net = q(sum((F(result['irrigation_rationing_totals']['actual_net_root_zone_m3']) for result in results), F(0)))
    observed_gross = q(sum((F(result['irrigation_rationing_totals']['actual_gross_delivery_m3']) for result in results), F(0)))
    if observed_net != total_net or observed_gross != withdrawal or initial != remaining+total_net+total_loss:
        raise ArithmeticError('source debit and actual crop-bound irrigation differ')
    statuses = [result['status'] for result in results]
    status = 'UNKNOWN' if 'UNKNOWN' in statuses else 'OUTSIDE_REGIME' if 'OUTSIDE_REGIME' in statuses else 'MODELLED'
    result = plain({'engine': ENGINE, 'status': status, 'source_status': 'WORKING NON-CANON',
        'input_sha256': identity, 'execution_binding_sha256': p.sha(execution), 'crops': results,
        'physical_hydraulics_executed': False, 'planted_area_m2': sum((F(plan['area_m2']) for plan in copied), F(0)),
        'water': {'days': days, 'source_id': water['source_id'], 'initial_stock_m3': initial,
            'remaining_stock_m3': remaining, 'total_withdrawal_m3': withdrawal,
            'total_net_m3': total_net, 'loss_m3': total_loss,
            'residual_m3': initial-remaining-withdrawal,
            'delivery_residual_m3': withdrawal-total_net-total_loss,
            'connection_law': CONNECTION, 'loss_destination': 'UNCLASSIFIED_NONREUSABLE_REFERENCE_LOSS'},
        'scope': 'Resources fixed-area ideal shared-stock reference; separate from R13; no native hydraulics, refill, reuse, rights or geographical clearance claim'})
    p.verify(execution)
    return result
