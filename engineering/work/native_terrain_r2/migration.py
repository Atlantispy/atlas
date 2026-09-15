"""Pinned R1 continuation to bounded R2 atoms; explicit numerical approximation.

The immutable predecessor owns the accepted prefix. Migration conserves every
original origin's total, and cannot remove a positive retained/exported incidence.
It does not assert equivalence to the predecessor's future arithmetic trajectory.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path

from work.native_terrain_r1 import evolve as old, materials as m
from . import numerics as n, provenance as p


def minimum_mass_per_bulk(executor, palette):
    """Conservative exact kg/m3 for old, domain-deposited and receiver stocks."""
    if type(palette) is not dict or not palette:
        raise ValueError('explicit nonempty original palette required')
    packing = executor.packing
    if type(packing) is not dict or not set(packing) <= set(palette):
        raise ValueError('receiving packing differs from original palette')
    if type(executor.sediment_laws) not in (tuple, list):
        raise ValueError('explicit channel sediment laws required')
    channel_packing = {}
    for law in executor.sediment_laws:
        mid = law.material_id
        if mid not in palette or mid in channel_packing:
            raise ValueError('channel sediment law material identity differs from original palette')
        channel_packing[mid] = F(law.deposited_porosity)
    values = []
    for mid, descriptor in palette.items():
        density = m.q(F(descriptor['grain_density_kg_m3']), 'declared density', positive=True)
        porosities = [F(descriptor['porosity'])]
        if mid in packing:
            porosities.append(F(packing[mid]))
        if mid in channel_packing:
            porosities.append(channel_packing[mid])
        if executor.receiver is not None:
            porosities.append(F(executor.receiver.deposit_porosity))
        for porosity in porosities:
            m.q(porosity, 'declared receiving porosity')
            if porosity >= 1:
                raise ValueError('declared receiving porosity must be below one')
            values.append(density * (1 - porosity))
    return min(values)


def _read_predecessor(reference):
    required = {'checkpoint_path', 'checkpoint_sha256', 'body_sha256', 'history_count'}
    if type(reference) is not dict or set(reference) != required:
        raise ValueError('complete explicit pinned predecessor reference required')
    if (type(reference['checkpoint_path']) is not str
            or not Path(reference['checkpoint_path']).is_absolute()):
        raise ValueError('absolute predecessor checkpoint path required')
    if (type(reference['history_count']) is not int
            or not 0 <= reference['history_count'] <= old.MAX_HISTORY):
        raise ValueError('predecessor accepted history count differs')
    for key in ('checkpoint_sha256', 'body_sha256'):
        digest = reference[key]
        if (type(digest) is not str or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('explicit predecessor SHA256 required')
    path = Path(reference['checkpoint_path'])
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference['checkpoint_sha256']:
        raise ValueError('predecessor checkpoint bytes changed')
    control = json.loads(raw)
    if type(control) is not dict:
        raise ValueError('explicit predecessor checkpoint object required')
    stored_envelope = control.get('envelope', control)
    if (type(stored_envelope) is not dict
            or stored_envelope.get('body_sha256') != reference['body_sha256']):
        raise ValueError('predecessor checkpoint body pin differs')
    if (stored_envelope.get('schema') != old.SCHEMA
            or type(stored_envelope.get('body')) is not dict):
        raise ValueError('preserved R1 predecessor envelope required')
    if 'storage_schema' not in control:
        if set(control) & {'history_refs', 'history_count'}:
            raise ValueError('ambiguous predecessor checkpoint history metadata')
        history = stored_envelope['body'].get('history')
        if type(history) is not list or len(history) != reference['history_count']:
            raise ValueError('predecessor accepted history count differs')
        if p.sha(stored_envelope['body']) != reference['body_sha256']:
            raise ValueError('plain predecessor checkpoint body hash differs')
    else:
        if control['storage_schema'] != 'diadem.native-case-checkpoint-history-files.r1':
            raise ValueError('unsupported predecessor checkpoint control schema')
        refs = control.get('history_refs')
        if (type(refs) is not list or control.get('history_count') != reference['history_count']
                or len(refs) != reference['history_count']):
            raise ValueError('predecessor checkpoint history reference count differs')
        if 'history' in stored_envelope['body']:
            raise ValueError('referenced predecessor control must not embed history')
        # The existing codec verifies these immutable payloads before this call;
        # retain its complete raw control pin without replaying/loading the prefix.
        for sequence, ref in enumerate(refs, 1):
            digest = ref.get('sha256', '') if type(ref) is dict else ''
            if (type(ref) is not dict or set(ref) != {'sequence', 'path', 'sha256', 'size_bytes'}
                    or type(ref['sequence']) is not int or ref['sequence'] != sequence
                    or type(digest) is not str or len(digest) != 64
                    or any(c not in '0123456789abcdef' for c in digest)
                    or ref['path'] != f'history/{sequence:06d}-{digest}.json'
                    or type(ref['size_bytes']) is not int or ref['size_bytes'] <= 0):
                raise ValueError('predecessor immutable history reference differs')
    return stored_envelope, raw


def read_predecessor_control(reference):
    """Authenticate the pinned R1 control without reading immutable history files.

    Compact controls retain their history-free body. Full legacy controls retain
    embedded history. The initial migration requires the existing codec's verified
    full envelope; successor validation only needs this pinned control view.
    """
    return _read_predecessor(reference)[0]


def _predecessor(envelope, reference):
    stored, raw = _read_predecessor(reference)
    if (reference['body_sha256'] != envelope['body_sha256']
            or p.sha(envelope['body']) != reference['body_sha256']):
        raise ValueError('predecessor body hash differs')
    if reference['history_count'] != len(envelope['body']['history']):
        raise ValueError('predecessor accepted history count differs')
    expected = envelope if 'history' in stored['body'] else dict(envelope,
        body={key: value for key, value in envelope['body'].items() if key != 'history'})
    if stored != expected:
        raise ValueError('predecessor checkpoint differs from supplied envelope')
    return raw


def _stocks(body, state):
    phases = {}
    values = []
    for _, column in state.columns:
        for layer in column.layers:
            row = phases.setdefault(layer.phase, {'mass_kg': F(), 'bulk_m3': F()})
            row['mass_kg'] += layer.mass_kg
            row['bulk_m3'] += layer.bulk_volume_m3
            values.append(layer.mass_kg)
    incidence = 0
    for rows in body['lineage'].values():
        for row in rows:
            incidence += len(row)
            values.extend(F(value) for value in row.values())
    exports = [F(value) for value in body['exported_origin_mass_kg'].values()]
    values.extend(exports)
    return p.plain({'cells': len(state.columns),
        'layers': sum(len(column.layers) for _, column in state.columns),
        'origins': len(body['origins']), 'retained_origin_incidences': incidence,
        'positive_exported_origin_incidences': sum(value > 0 for value in exports),
        'zero_exported_origin_incidences': sum(value == 0 for value in exports),
        'retained_by_phase': phases, 'exported_mass_kg': sum(exports, F()),
        'maximum_mass_numerator_bits': max((v.numerator.bit_length() for v in values), default=0),
        'maximum_mass_denominator_bits': max((v.denominator.bit_length() for v in values), default=0)})


def migrate(old_envelope, executor, *, predecessor_ref):
    """Return a new sealed envelope and receipt, writing no predecessor or output."""
    # Authenticate the exact prefix once. No replay of accepted physical steps.
    before = old.validate(old_envelope)
    raw = _predecessor(old_envelope, predecessor_ref)
    initial_binding = p.identity()
    policy = p.policy()
    state = old._native(before)
    prefix_ids = [row['operation_id'] for row in before['history']]
    if (len(prefix_ids) > old.MAX_HISTORY or len(set(prefix_ids)) != len(prefix_ids)
            or any(type(value) is not str or not value or len(value) > 1024 for value in prefix_ids)):
        raise ValueError('bounded unique original prefix operation IDs required')
    if len(before['origins']) > policy['maximum_origins']:
        raise ValueError('migration maximum original origins exceeded')
    minimum = minimum_mass_per_bulk(executor, before['palette'])
    slots = {origin: {} for origin in before['origins']}
    locations = {}
    for cell, rows in before['lineage'].items():
        for index, row in enumerate(rows):
            key = json.dumps(['retained', cell, index], separators=(',', ':'))
            locations[key] = (cell, index)
            for origin, value in row.items():
                slots[origin][key] = F(value)
    for origin, value in before['exported_origin_mass_kg'].items():
        if F(value):
            slots[origin]['exported'] = F(value)
    # The reference replaces the immutable accepted prefix; do not duplicate
    # potentially large predecessor history in RAM only to discard it later.
    following = deepcopy({key: value for key, value in before.items()
                          if key not in {'history', 'state', 'parent'}})
    error_units = 0
    maximum_slots = 0
    for origin in sorted(slots):
        desired = slots[origin]
        total = n.units(F(before['origins'][origin]['mass_kg']))
        maximum_slots = max(maximum_slots, len(desired))
        if len(desired) > policy['maximum_positive_migration_slots_per_origin']:
            raise ValueError('migration maximum positive slots per origin exceeded')
        if total < len(desired):
            raise ValueError('insufficient original origin quanta for positive incidences')
        allocated, bound = n.allocate_positive(total, desired)
        if set(allocated) != set(desired) or sum(allocated.values()) != total:
            raise ArithmeticError('migration origin allocation did not close')
        measured = 0
        for key, ticks in allocated.items():
            if ticks <= 0:
                raise ArithmeticError('migration lost a positive predecessor incidence')
            value = n.mass(ticks)
            measured += n.ceil_error_units(abs(value - desired[key]))
            if key == 'exported':
                following['exported_origin_mass_kg'][origin] = str(value)
            else:
                cell, index = locations[key]
                following['lineage'][cell][index][origin] = str(value)
        if measured > bound:
            raise ArithmeticError('migration allocation error bound was rounded inward')
        error_units += bound
    error_kg = n.mass(error_units)
    error_bulk = error_kg / minimum
    if error_bulk > F(policy['migration_bulk_l1_allocation_bound_m3']):
        raise ValueError('predeclared migration bulk L1 allocation error cap exceeded')
    if error_bulk > F(policy['new_cumulative_bulk_l1_allocation_bound_m3']):
        raise ValueError('predeclared total numerical allocation error cap exceeded')
    columns = []
    maximum_surface_change = F()
    for cell, column in state.columns:
        layers = []
        for index, layer in enumerate(column.layers):
            amount = sum((F(v) for v in following['lineage'][cell][index].values()), F())
            n.units(amount)
            if amount <= 0:
                raise ArithmeticError('migration erased a predecessor layer')
            if layer.phase != 'mobile_sediment' and amount != layer.mass_kg:
                raise ValueError('migration would change frozen weathered or rock stock')
            layers.append(replace(layer, mass_kg=amount))
        successor = replace(column, layers=tuple(layers))
        maximum_surface_change = max(maximum_surface_change, abs(successor.surface_m - column.surface_m))
        columns.append((cell, successor))
    new_state = replace(state, columns=tuple(columns))
    following['state'] = new_state.as_dict()
    old._lineage_check(following, new_state)
    if executor.receiver is None:
        if before['receiver'] is not None:
            raise ValueError('predecessor finite receiver must remain explicitly bound')
    else:
        solid = sum((F(value) / F(before['palette'][before['origins'][origin]['material_id']]
                     ['grain_density_kg_m3'])
                     for origin, value in following['exported_origin_mass_kg'].items()), F())
        following['receiver'] = p.plain(executor.receiver.account(
            F(before['surface_water_exported_m3']), solid))
    receipt = p.plain({'schema': 'diadem.native-numerical-migration.r2',
        'source_status': 'WORKING NON-CANON', 'predecessor': deepcopy(predecessor_ref),
        'successor_initial_state_sha256': p.sha(following['state']),
        'initial_elapsed_years': str(state.elapsed_years),
        'prior_surface_water_exported_m3': before['surface_water_exported_m3'],
        'prior_cumulative_allocation_error_m3': before['cumulative_allocation_error_m3'],
        'prefix_operation_ids': prefix_ids,
        'original_origin_inventory_sha256': p.sha(before['origins']),
        'palette_sha256': p.sha(before['palette']), 'clock_sha256': p.sha(before['clock']),
        'source_sha256': p.sha(before['source']),
        'method': policy['migration'], 'mass_quantum_kg': n.Q,
        'numeric_l1_units': error_units, 'mass_l1_error_bound_kg': error_kg,
        'bulk_l1_error_bound_m3': error_bulk, 'minimum_mass_per_bulk_m3': minimum,
        'migration_bulk_l1_cap_m3': policy['migration_bulk_l1_allocation_bound_m3'],
        'maximum_surface_change_m': maximum_surface_change,
        'maximum_positive_slots_per_origin': maximum_slots,
        'before': _stocks(before, state), 'after': _stocks(following, new_state),
        'exact_original_origin_totals_preserved': True, 'positive_incidences_lost': 0,
        'layers_lost': 0, 'frozen_weathered_rock_layers_unchanged': True,
        'predecessor_bytes_unchanged': True,
        'historical_hillslope_allocation_error_m3': before['cumulative_allocation_error_m3'],
        'numerical_approximation': True, 'predecessor_trajectory_equivalence_claimed': False,
        'error_scope': policy['error_scope']})
    following.update(history=[], initial_elapsed_years=str(state.elapsed_years),
        initial_state_sha256=p.sha(following['state']),
        continuation_base={'surface_water_exported_m3': before['surface_water_exported_m3'],
            'cumulative_allocation_error_m3': before['cumulative_allocation_error_m3'],
            'numeric_l1_units': error_units}, numeric_l1_units=error_units,
        minimum_mass_per_bulk_m3=str(minimum), numeric_policy=policy,
        parent={'kind': 'VERIFIED_R1_NUMERICAL_MIGRATION',
                'predecessor': deepcopy(predecessor_ref), 'migration': receipt})
    if _predecessor(old_envelope, predecessor_ref) != raw:
        raise ValueError('predecessor changed during migration')
    p.verify(initial_binding)
    from . import evolve
    result = evolve._seal(following, initial_binding)
    evolve.validate(result)
    return result, receipt
