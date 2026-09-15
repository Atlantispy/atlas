"""Finite, delayed, downstream-only collection of actual soil export parcels.

No upstream connection, aquifer identity, ice, evaporation or thermal evolution
is inferred. Liquid heat is carried as an inventory, not reset to a temperature.
Capacity overflow is a well-mixed external export under this explicit hypothesis.
"""
from fractions import Fraction as F
from itertools import groupby
import re
from .quantities import q, exact, ident, plain


def route(parcels, *, receiver_id, capacity_m3, delay_seconds, horizon_seconds,
          overflow_destination, evidence, source_status):
    """Reconstruct an explicitly empty receiver from the complete parcel history.

    This is not an incremental import into an existing receiver. Simultaneous
    arrivals mix together before the capacity spill, independently of parcel IDs.
    """
    ident(receiver_id); ident(evidence); ident(overflow_destination)
    if overflow_destination == receiver_id:
        raise ValueError('overflow requires a separate explicit external destination')
    if source_status not in ('SYNTHETIC TEST', 'WORKING NON-CANON'):
        raise ValueError('declared working downstream collection scenario required')
    cap, delay, horizon = q(capacity_m3), q(delay_seconds, positive=True), q(horizon_seconds)
    if type(parcels) is not list or len(parcels) > 16384:
        raise ValueError('bounded actual export parcel list required')
    pending, seen = [], set()
    for row in parcels:
        exact(row, ('id', 'source_use_id', 'source_input_sha256', 'created_at_seconds',
                    'water_m3', 'enthalpy_j'), 'actual liquid export')
        for key in ('id', 'source_use_id', 'source_input_sha256'):
            ident(row[key])
        if re.fullmatch('[0-9a-f]{64}', row['source_input_sha256']) is None:
            raise ValueError('full exact source-input SHA256 required')
        if row['id'] in seen or row['source_use_id'] in seen:
            raise ValueError('actual soil export already collected')
        seen.update((row['id'], row['source_use_id']))
        amount, created = q(row['water_m3']), q(row['created_at_seconds'])
        if created > horizon:
            raise ValueError('future soil export is not present inventory')
        # Positive enthalpy uses the native water/ice reference; a negative
        # liquid parcel is outside this declared thawed collection regime.
        energy = q(row['enthalpy_j'])
        if not amount and energy:
            raise ValueError('liquid enthalpy without a water parcel')
        pending.append(dict(row, water_m3=amount, enthalpy_j=energy,
                            arrival_at_seconds=q(created+delay, 'return arrival clock')))
    pending.sort(key=lambda row: (row['arrival_at_seconds'], row['id']))
    volume = energy = overflow = overflow_heat = F(0)
    delivered, timeline = [], []
    for arrival, grouped in groupby(pending, key=lambda row: row['arrival_at_seconds']):
        rows = list(grouped)
        if arrival > horizon:
            continue
        for row in rows:
            volume = q(volume + row['water_m3'], 'receiver volume before spill')
            energy = q(energy + row['enthalpy_j'], 'receiver enthalpy before spill')
        spill = max(F(0), volume-cap)
        spill_heat = q(energy*spill/volume if volume else F(0), 'overflow enthalpy')
        volume = q(volume-spill); energy = q(energy-spill_heat)
        overflow = q(overflow+spill); overflow_heat = q(overflow_heat+spill_heat)
        delivered.extend(row['id'] for row in rows)
        timeline.append({'parcel_ids': [row['id'] for row in rows], 'at_seconds': arrival,
            'receiver_m3': volume, 'receiver_enthalpy_j': energy,
            'overflow_m3': spill, 'overflow_enthalpy_j': spill_heat})
    delivered_set = set(delivered)
    queue = [row for row in pending if row['id'] not in delivered_set]
    def total_of(rows, key):
        result = F(0)
        for row in rows:
            result = q(result+row[key], 'collection aggregate '+key)
        return result
    total, total_energy = total_of(pending, 'water_m3'), total_of(pending, 'enthalpy_j')
    queued, queued_heat = total_of(queue, 'water_m3'), total_of(queue, 'enthalpy_j')
    if total != volume+overflow+queued or total_energy != energy+overflow_heat+queued_heat:
        raise ArithmeticError('finite downstream water/enthalpy collection failed')
    return plain({'schema': 'diadem.soil-export-collection.r21', 'status': 'COLLECTED',
        'receiver_id': receiver_id, 'horizon_seconds': horizon, 'evidence': evidence,
        'overflow_destination': overflow_destination,
        'receiver_initial_m3': F(0), 'receiver_initial_enthalpy_j': F(0),
        'history_semantics': 'COMPLETE_ACCEPTED_PARCEL_HISTORY_NOT_INCREMENTAL_CREDIT',
        'source_status': source_status, 'received_input_m3': total,
        'receiver_m3': volume, 'receiver_enthalpy_j': energy, 'pending_returns': queue,
        'pending_m3': queued, 'pending_enthalpy_j': queued_heat,
        'overflow_m3': overflow, 'overflow_enthalpy_j': overflow_heat,
        'water_residual_m3': F(0), 'enthalpy_residual_j': F(0),
        'delivered_ids': delivered, 'timeline': timeline,
        'upstream_reuse_allowed': False, 'thermal_evolution_modelled': False,
        'assumption': 'EXPLICIT_DELAY_UNFROZEN_LIQUID_ADIABATIC_TRANSIT_FINITE_MIXED_RECEIVER'})
