"""Compile the bound actual Diadem profile against a supplied physical freeze.

This is a Stage2 restriction adapter, not a source of protected geometry or a
map-acceptance certificate. Atom masks must already be independently registered
and frozen. The caller supplies their independently trusted source binding.
No historical coordinates, scalar scores or unnamed territorial classes enter.
"""
from collections import defaultdict
from copy import deepcopy

from . import inputs, owner, specials, provenance as p

SCHEMA = 'diadem.actual-profile-restrictions.r20'
BINDING_FIELDS = {'context', 'frame', 'terrain_generation', 'water_generation', 'freeze_sha256'}
PACKET_FIELDS = {'binding', 'source_binding', 'geometry_status', 'sea_atoms', 'envelopes',
                 'forest_exclusion_atoms', 'neutral_flanks'}
ENVELOPES = {'forest', 'neutral', 'dunkelhauch'}


def inventory():
    """Read the current pinned owner contract and matrix, not a cached names list."""
    contract = owner.contract()
    matrix = owner.read_matrix()
    source = next(row for row in contract['sources'] if row['id'] == 'CM')
    record = {'path': str(owner.source_path(source, contract)), 'sha256': source['sha256'],
              'status': source['status']}
    value = specials.profile(matrix, source=record)
    if set(value['sea_owner_ids']) != set(contract['diadem_constraints']['sea_required']):
        raise ValueError('CONFLICT: owner contract and matrix Sea whitelist differ')
    return contract, value


def _resolved(value, label):
    if (type(value) is not str or not value.strip() or len(value) > 4096 or
            value in inputs.UNRESOLVED or value in inputs.REJECTED_ROLES):
        raise ValueError('INPUT_INCOMPLETE: resolved '+label+' required')
    return value


def _ids(value, universe, label, *, nonempty=False):
    if (type(value) is not list or len(value) > 8192 or (nonempty and not value) or
            any(type(item) is not str or item not in universe for item in value) or
            len(set(value)) != len(value)):
        raise ValueError('INPUT_INCOMPLETE: complete distinct '+label+' atom memberships required')
    return set(value)


def compile_restrictions(frozen, packet, *, expected_binding):
    """Return restrictions for intersection with existing Stage2 eligibility.

    ``expected_binding`` has context/frame/terrain_generation/water_generation/
    freeze_sha256 and source_binding. The packet repeats that binding, excluding
    source_binding, plus its explicit masks. Missing data returns INPUT_INCOMPLETE;
    stale/malformed/conflicting bindings raise. PASS means compilation only.

    ``sea_atoms`` means positive-length frontage on the independently identified
    Sea boundary, not point contact, a river or a host-port right. Allowed masks
    are complete sourced outer envelopes, not guessed buffers. Forest exclusion
    atoms restrict settlement use; they do not erase horizontal sovereignty.
"""
    contract, profile = inventory()
    result = {'schema': SCHEMA, 'status': 'INPUT_INCOMPLETE', 'restrictions': None,
              'profile': profile, 'actual_diadem_map_accepted': False,
              'scope': 'BOUND ACTUAL PROFILE; SUPPLIED FROZEN MEMBERSHIPS; NO GEOMETRY INFERENCE'}

    def incomplete(reason):
        return dict(result, reason=reason)

    if expected_binding is None or packet is None:
        return incomplete('explicit registered protected-envelope and shoreline inputs required')
    if type(expected_binding) is not dict or set(expected_binding) != BINDING_FIELDS | {'source_binding'}:
        raise ValueError('complete independently trusted profile binding required')
    binding = {key: deepcopy(expected_binding[key]) for key in BINDING_FIELDS}
    if any(binding[key] is None for key in BINDING_FIELDS):
        return incomplete('world/frame or physical freeze is unresolved')
    inputs.context(binding['context']); inputs.frame(binding['frame'])
    if (binding['context']['spatial_frame_id'] != binding['frame']['spatial_frame_id'] or
            binding['context']['vertical_reference'] != binding['frame']['vertical_reference']):
        raise ValueError('CONFLICT: profile registration frame differs from context')
    for key in ('terrain_generation', 'water_generation', 'freeze_sha256'):
        _resolved(binding[key], key)
    if (type(frozen) is not dict or frozen.get('status') != 'PASS' or
            frozen.get('assignment_allowed') is not True):
        return incomplete('resolved whole-unit formation freeze required before profile compilation')
    if p.sha(frozen) != binding['freeze_sha256']:
        raise ValueError('stale or modified hierarchy freeze cannot receive profile restrictions')
    if type(packet) is not dict or set(packet) != PACKET_FIELDS:
        return incomplete('complete explicit profile physical-input packet required')
    if packet['binding'] != binding:
        raise ValueError('profile world/frame/terrain/water/freeze binding differs')
    source = packet['source_binding']
    if (type(source) is not dict or set(source) != {'path', 'sha256', 'role', 'status'} or
            source != expected_binding['source_binding'] or source['role'] != 'STAGE2_CONTEXT'):
        raise ValueError('profile physical source differs from independent Stage2 source admission')
    _resolved(source['status'], 'physical source status')
    lineage = inputs.lineage([{'id': 'profile-physical', 'parents': [], **source}],
        ['profile-physical'], {source['path']: {key: source[key] for key in ('sha256', 'role', 'status')}},
        {'STAGE2_CONTEXT'})
    result.update(binding=binding, source_status=source['status'], source_lineage=lineage,
        physical_input_sha256=p.sha(packet),
        owner_sources={'contract_path': str(owner.ROOT/'OWNER_CONTRACT.json'),
                       'contract_sha256': owner.PINS['OWNER_CONTRACT.json'],
                       'matrix': deepcopy(profile['source'])})
    if packet['geometry_status'] != 'FROZEN_COMPLETE':
        return incomplete('protected geometry or Sea-boundary coverage is not explicitly complete')
    mapping = frozen.get('atom_to_assignment_unit')
    if type(mapping) is not dict or not 1 <= len(mapping) <= 8192:
        raise ValueError('complete bounded frozen atom membership required')
    members = defaultdict(set)
    for atom, unit in mapping.items():
        _resolved(atom, 'atom identity'); _resolved(unit, 'assignment-unit identity')
        members[unit].add(atom)
    supports = frozen['assignment_prepared']['supports']
    if (len(members) > 256 or type(supports) is not list or
            len(supports) != len(members) or {row['id'] for row in supports} != set(members)):
        raise ValueError('frozen assignment supports and atom membership differ')
    atoms = set(mapping)
    if any(packet[key] is None for key in ('sea_atoms', 'envelopes', 'forest_exclusion_atoms', 'neutral_flanks')):
        return incomplete('UNKNOWN physical memberships cannot become empty masks')
    sea = _ids(packet['sea_atoms'], atoms, 'Sea shoreline')
    if type(packet['envelopes']) is not dict or set(packet['envelopes']) != ENVELOPES:
        return incomplete('Forest, immediate neutral Gate and single-complex Dunkelhauch envelopes required')
    envelopes = {}
    for name, row in packet['envelopes'].items():
        if type(row) is not dict or set(row) != {'core_atoms', 'allowed_atoms', 'excluded_atoms'}:
            return incomplete('explicit '+name+' core/allowed/excluded masks required')
        if any(row[key] is None for key in row):
            return incomplete('unresolved '+name+' envelope membership')
        core = _ids(row['core_atoms'], atoms, name+' core', nonempty=True)
        allowed = _ids(row['allowed_atoms'], atoms, name+' allowed', nonempty=True)
        excluded = _ids(row['excluded_atoms'], atoms, name+' excluded')
        if not core <= allowed or excluded & allowed:
            raise ValueError('CONFLICT: '+name+' core/allowed/excluded masks disagree')
        envelopes[name] = {'core': core, 'allowed': allowed, 'excluded': excluded}
    cordon = _ids(packet['forest_exclusion_atoms'], atoms, 'complete Forest settlement-exclusion cordon', nonempty=True)
    flanks = packet['neutral_flanks']
    if type(flanks) is not dict or set(flanks) != {'west_northwest_atoms', 'east_southeast_atoms'}:
        return incomplete('explicit registered immediate neutral-Gate flank memberships required')
    flanks = {key: _ids(value, atoms, 'neutral '+key, nonempty=True) for key, value in flanks.items()}

    primary = {row['haus_id']: row for row in profile['primary_records']}

    def haus(label):
        ident = label if label in primary else 'haus_'+label.casefold().translate(
            str.maketrans({'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss'})).replace(' ', '_')
        if ident not in primary:
            raise ValueError('unresolved owner-contract label; no fuzzy owner matching: '+label)
        return ident

    def fill(label):
        return primary[haus(label)]['surface_fill_id']

    fills = sorted(row['id'] for row in profile['surface_fills'])
    special_fills = {'forest': profile['shared_fill_id'], 'neutral': profile['neutral_fill_id'],
                     'dunkelhauch': fill('Dunkelhauch')}
    eligible = {unit: set(fills) for unit in members}
    locks, conflicts = defaultdict(set), []
    for name, envelope in envelopes.items():
        target = special_fills[name]
        for unit, children in members.items():
            if not children <= envelope['allowed'] or children & envelope['excluded']:
                eligible[unit].discard(target)
            if children & envelope['core']:
                locks[unit].add(target)
    for key, label in (('west_northwest_atoms', 'Edelstein'), ('east_southeast_atoms', 'Glanzgrund')):
        for atom in flanks[key]:
            locks[mapping[atom]].add(fill(label))
    sea_fills = {fill(ident) for ident in profile['sea_owner_ids']}
    sea_units = sorted({mapping[atom] for atom in sea})
    for unit in sea_units:
        eligible[unit] &= sea_fills
    for unit, values in locks.items():
        eligible[unit] &= values if len(values) == 1 else set()
    for unit, values in eligible.items():
        if not values:
            conflicts.append(unit)

    constraints = contract['diadem_constraints']

    def pairs(name):
        result = set()
        for left, right in constraints[name]:
            pair = tuple(sorted((fill(left), fill(right))))
            if pair[0] == pair[1]:
                raise ValueError('typed shared relation cannot masquerade as two distinct surface fills')
            result.add(pair)
        return [list(pair) for pair in sorted(result)]

    restrictions = {'owners': fills, 'required_owners': fills, 'connected_owners': fills,
        'eligible': {unit: sorted(values) for unit, values in sorted(eligible.items())},
        'required_adjacency': pairs('direct_frontiers_required'),
        'prohibited_adjacency': pairs('direct_frontiers_excluded'),
        'required_any_adjacency': [{'owner': special_fills['dunkelhauch'],
            'other_owners': sorted(set(fills)-{special_fills['dunkelhauch'], fill('Frostglanz')})}],
        'required_presence': [{'owner': target, 'unit_ids': list(sea_units)} for target in sorted(sea_fills)],
        'surface_relations': {row['id']: list(row['primary_haus_ids']) for row in profile['surface_fills']}}
    semantics = {'protected_unit_locks': {key: sorted(values) for key, values in sorted(locks.items())},
        'sea_unit_ids': sea_units, 'sea_sovereignty_not_host_port_access': True,
        'forest_exclusion_atom_ids': sorted(cordon),
        'forest_exclusion_role': 'SETTLEMENT_EXCLUSION_ONLY_NOT_UNOWNED_SURFACE',
        'shared_forest': {'surface_fill': profile['shared_fill_id'], 'surface_count': 1,
            'primary_haus_ids': restrictions['surface_relations'][profile['shared_fill_id']],
            'vertical_layers': ['canopy', 'floor-root'], 'settlement_columns_must_not_overlap': True},
        'neutral': {'surface_fill': profile['neutral_fill_id'], 'primary_haus_ids': [],
            'scope': 'SUPPLIED_IMMEDIATE_SILL_GORGE_CUSTOMS_DEFENCE_ONLY',
            'sponsor_is_not_owner': True, 'additional_coalition_powers_inferred': False},
        'typed_contacts': [{'haus_ids': [haus(a), haus(b)], 'type': kind,
                            'substitutes_for_land_adjacency': False}
                           for a, b, kind in constraints['typed_contacts']],
        'soft_preferences': constraints['soft_preferences'],
        'soft_preferences_are_not_hard_exclusions_or_invented_scores': True,
        'separate_remaining_acceptance': ['settlement-column overlap/cordon enforcement',
            'typed subsurface/hydraulic/vertical contacts and access rights',
            'post-mainland-freeze island boundary-distance calculation',
            'replacement terrain and independent actual-map acceptance']}
    result.update(restrictions=restrictions, semantics=semantics, unit_mutations=0)
    if conflicts or not sea_units:
        result.update(status='INFEASIBLE_NO_SPLIT', reason='whole-unit protected locks/Sea eligibility conflict',
                      conflicting_units=sorted(conflicts))
    else:
        result.update(status='PASS', reason='actual owner-profile assignment restrictions compiled; no solve or map acceptance')
    result['compilation_sha256'] = p.sha(result)
    return result
