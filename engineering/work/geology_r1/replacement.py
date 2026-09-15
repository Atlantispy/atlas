"""Exact finite bulk-volume replacement; no density, phase, K or height law.

Depth is measured down from the CURRENT column top. Only currently resident
eligible, nonprotected shares are replaced. Equal removed/introduced bulk volume
does not imply equal mass or solid volume; the caller accounts those separately
using the supplied prototype properties. No stock is extended below the base.
"""
import hashlib
import json

from work.generator_upgrade_r16 import columns


LAYER = {'compartment_id', 'thickness_m', 'weights'}
MAX_UNITS = 64


def _label(value):
    columns._text(value, 'replacement identity')
    if value in {'UNKNOWN', 'INCOMPLETE', 'CONFLICT'}:
        raise ValueError('resolved replacement identity required')
    return value


def _unit_set(value):
    if type(value) not in (list, tuple, set, frozenset) or len(value) > MAX_UNITS:
        raise ValueError('bounded explicit replacement unit identities required')
    result = set()
    for unit in value:
        _label(unit)
        if unit in result:
            raise ValueError('duplicate replacement unit identity')
        result.add(unit)
    return result


def _weights(values):
    if type(values) is not dict or len(values) > MAX_UNITS:
        raise ValueError('bounded explicit unit-weight mapping required')
    result = {}
    for unit, value in sorted(values.items()):
        _label(unit)
        weight = columns._q(value, 'replacement weight/support', nonnegative=True)
        if weight > 1:
            raise ValueError('replacement weight/support outside [0,1]')
        result[unit] = weight
    return result


def _segment_id(parent_id, thickness, begin, end):
    identity = [parent_id, str(thickness), str(begin), str(end)]
    raw = json.dumps(identity, separators=(',', ':'), ensure_ascii=True).encode()
    return 'R18_SEGMENT_'+hashlib.sha256(raw).hexdigest()


def _inventory(layers):
    answer = {}
    for layer in layers:
        thickness = columns._q(layer['thickness_m'], 'compartment thickness', positive=True)
        for unit, weight in layer['weights'].items():
            volume = columns._q(thickness*columns._q(weight, 'resident bulk weight'), 'resident bulk thickness')
            answer[unit] = columns._q(answer.get(unit, 0)+volume, 'total resident bulk thickness')
    return answer


def _add_inventory(layer, answer):
    """Accumulate already validated exact quantities in original layer order."""
    for unit, weight in layer['weights'].items():
        volume = columns._q(layer['thickness_m']*weight, 'resident bulk thickness')
        answer[unit] = columns._q(answer.get(unit, 0)+volume, 'total resident bulk thickness')


def _plain_layers(layers):
    return [{'compartment_id': row['compartment_id'], 'thickness_m': str(row['thickness_m']),
             'weights': {unit: str(weight) for unit, weight in row['weights'].items()}}
            for row in layers]


def _plain_transfers(transfers):
    return [{key: ({unit: str(value) for unit, value in values.items()} if type(values) is dict
                   else values if key in ('source_compartment_id', 'compartment_id') else str(values))
             for key, values in row.items()} for row in transfers]


def replace(layers, depth_m, replacements, *, eligible_units=None, protected_units=(), coverage=None):
    """Return ``(new_layers, transfers)`` without mutating supplied objects.

Layers are bottom-to-top dictionaries with exactly compartment_id, thickness_m
and weights; their weights sum exactly to one and thickness is positive.
Replacements are explicit supports in [0,1]. Default coverage is
1-product(1-b_i), allocated in b_i/sum(b_i) proportions. Explicit coverage in
[0,1] substitutes only that coverage, not the supplied relative proportions.
All-zero supports are a no-op unless positive explicit coverage is requested.

The output layer schema is unchanged and quantities are exact rational strings.
Each changed segment's transfer records removed_bulk_thickness_m and
introduced_bulk_thickness_m by unit, not mass. Split IDs are deterministic hashes
of the parent compartment and exact interval; unsplit IDs are retained. A same-
unit replacement still records both removal and introduction. Empty layers mean
explicit finite exhaustion, not an inferred unknown or infinite substrate.
"""
    answer, transfers = _replace(layers, depth_m, replacements,
        eligible_units=eligible_units, protected_units=protected_units, coverage=coverage)
    return _plain_layers(answer), _plain_transfers(transfers)


def _replace(layers, depth_m, replacements, *, eligible_units=None, protected_units=(), coverage=None):
    """Private exact state; validate fully even for empty/no-op replacements."""
    if type(layers) is not list or len(layers) > columns.MAX_LAYERS:
        raise ValueError('bounded bottom-to-top replacement layers required')
    depth = columns._q(depth_m, 'finite replacement depth', nonnegative=True)
    eligible = None if eligible_units is None else _unit_set(eligible_units)
    protected = _unit_set(protected_units)
    supplied = _weights(replacements)
    support_sum = columns._sum(supplied.values(), 'total competing support')
    if coverage is None:
        retained = columns._q(1, 'retained host fraction')
        for support in supplied.values():
            retained = columns._q(retained*columns._q(1-support, 'unoccupied replacement support'), 'retained host fraction')
        cover = columns._q(1-retained, 'competing replacement coverage')
    else:
        cover = columns._q(coverage, 'explicit replacement coverage', nonnegative=True)
        if cover > 1:
            raise ValueError('explicit replacement coverage outside [0,1]')
        if cover and not support_sum:
            raise ValueError('positive coverage requires positive replacement support')
    allocation = ({unit: columns._q(value/support_sum, 'conditional replacement allocation')
                   for unit, value in supplied.items() if value} if support_sum else {})
    original, identities, before = [], set(), {}
    for row in layers:
        if type(row) is not dict or set(row) != LAYER:
            raise ValueError('exact finite compartment fields required')
        identity = _label(row['compartment_id'])
        if identity in identities:
            raise ValueError('duplicate compartment identity')
        identities.add(identity)
        thickness = columns._q(row['thickness_m'], 'compartment thickness', positive=True)
        weights = _weights(row['weights'])
        if columns._sum(weights.values(), 'resident weight sum') != 1:
            raise ValueError('resident bulk weights must sum exactly to one')
        exact_row = {'compartment_id': identity, 'thickness_m': thickness, 'weights': weights}
        original.append(exact_row)
        _add_inventory(exact_row, before)
    total = columns._sum((row['thickness_m'] for row in original), 'finite column height')
    boundary = columns._q(total-min(depth, total), 'replacement boundary above base')
    answer, transfers = [], []
    bottom = columns._q(0, 'interval bottom')
    for row in original:
        thickness = row['thickness_m']
        top = columns._q(bottom+thickness, 'interval top')
        active_bottom = max(bottom, boundary)
        affected = columns._q(max(0, top-active_bottom), 'affected interval thickness')
        weights = row['weights']
        host = {unit: value for unit, value in weights.items()
                if unit not in protected and (eligible is None or unit in eligible)}
        host_sum = columns._sum(host.values(), 'current eligible host fraction')
        if not (affected and cover and host_sum):
            answer.append(row)
            bottom = top
            continue
        retained_height = columns._q(thickness-affected, 'unaffected lower thickness')
        new_id = row['compartment_id']
        if retained_height:
            lower_id = _segment_id(row['compartment_id'], thickness, 0, retained_height)
            new_id = _segment_id(row['compartment_id'], thickness, retained_height, thickness)
            answer.append({'compartment_id': lower_id, 'thickness_m': retained_height,
                           'weights': dict(row['weights'])})
        removed, introduced = {}, {}
        modified = dict(weights)
        for unit, weight in host.items():
            fraction = columns._q(weight*cover, 'removed resident fraction')
            if fraction:
                modified[unit] = columns._q(modified[unit]-fraction, 'remaining resident fraction')
                removed[unit] = columns._q(affected*fraction, 'removed bulk thickness')
        replaced_fraction = columns._q(host_sum*cover, 'total replaced bulk fraction')
        for unit, share in allocation.items():
            fraction = columns._q(replaced_fraction*share, 'introduced bulk fraction')
            modified[unit] = columns._q(modified.get(unit, 0)+fraction, 'new resident bulk fraction')
            introduced[unit] = columns._q(affected*fraction, 'introduced bulk thickness')
        modified = {unit: value for unit, value in sorted(modified.items()) if value}
        if len(modified) > MAX_UNITS:
            raise ValueError('replacement exceeds constituent count budget')
        if (columns._sum(modified.values(), 'new resident weight sum') != 1
                or columns._sum(removed.values(), 'removed bulk sum') != columns._sum(introduced.values(), 'introduced bulk sum')):
            raise ArithmeticError('exact segment bulk replacement closure failed')
        answer.append({'compartment_id': new_id, 'thickness_m': affected, 'weights': modified})
        transfers.append({'source_compartment_id': row['compartment_id'], 'compartment_id': new_id,
            'thickness_m': affected, 'depth_start_m': columns._q(total-top, 'segment start depth'),
            'depth_stop_m': columns._q(total-active_bottom, 'segment stop depth'),
            'coverage': cover, 'eligible_bulk_fraction': host_sum,
            'removed_bulk_thickness_m': removed, 'introduced_bulk_thickness_m': introduced})
        bottom = top
    if len(answer) > columns.MAX_LAYERS or len({row['compartment_id'] for row in answer}) != len(answer):
        raise ValueError('replacement split layer budget or unique identity violated')
    if columns._sum((row['thickness_m'] for row in answer), 'final column height') != total:
        raise ArithmeticError('replacement changed finite bulk height')
    after = {}
    for row in answer:
        _add_inventory(row, after)
    removed_totals, introduced_totals = {}, {}
    for transfer in transfers:
        for values, target in ((transfer['removed_bulk_thickness_m'], removed_totals),
                               (transfer['introduced_bulk_thickness_m'], introduced_totals)):
            for unit, value in values.items():
                target[unit] = columns._q(target.get(unit, 0)+value, 'total bulk transfer')
    for unit in set(before) | set(after) | set(removed_totals) | set(introduced_totals):
        expected = columns._q(before.get(unit, 0)-removed_totals.get(unit, 0), 'remaining unit bulk thickness')
        expected = columns._q(expected+introduced_totals.get(unit, 0), 'final unit bulk thickness')
        if expected != after.get(unit, 0):
            raise ArithmeticError('exact per-unit replacement bulk account failed')
    return answer, transfers
