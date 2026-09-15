"""Physical formation -> immutable cut -> political assignment -> typed joins."""
from collections import defaultdict
from copy import deepcopy
from . import assignment, geometry, hierarchy, inputs, joins, owner, profile, specials, provenance as p
from .cache import StageCache

TERMS = ('physical_compatibility_u', 'settlement_service_u', 'permitted_access_u')


def edge_key(left, right):
    return p.encoded(sorted((left, right))).decode('utf-8')


def _source(record, role, execution):
    if type(record) is not dict or set(record) != {'path', 'sha256', 'role', 'status'}:
        raise ValueError('complete source-bound reference record required')
    expected = execution['sources'].get(record['path'])
    if expected != record['sha256'] or record['role'] != role or record['status'] != 'SYNTHETIC TEST':
        raise ValueError('reference source is not independently execution-bound for this stage')
    node = {'id': 'reference', 'parents': [], **record}
    return inputs.lineage([node], ['reference'],
        {record['path']: {'sha256': expected, 'role': role, 'status': 'SYNTHETIC TEST'}}, {role})


def _integer(value):
    if type(value) is not int or not 0 <= value <= 1000000:
        raise ValueError('INPUT_INCOMPLETE: explicit bounded integer compatibility required')
    return value


def _stage(name, invocation, binding, producer, validator, enabled, root, reporting):
    cache = StageCache(name, binding, root) if enabled else None
    if cache:
        result, hit = cache.reuse(invocation, producer, validator)
    else:
        result = producer(); validator(deepcopy(result)); hit = False
    reporting.append({'stage': name, 'hit': hit, 'stats': cache.stats if cache else {},
                      'warnings': cache.warnings if cache else []})
    return result


def _problem(prepared, frozen, political, limits):
    mapping = frozen['atom_to_assignment_unit']
    if set(political['atom_evidence']) != set(mapping) or set(political['atom_eligible']) != set(mapping):
        raise ValueError('complete explicit Stage2 evidence and eligibility coverage required')
    owners = political['owners']
    if (type(owners) is not list or not owners or any(type(v) is not str or not v for v in owners)
            or len(set(owners)) != len(owners)):
        raise ValueError('explicit active-owner set required')
    if set(political['surface_relations']) != set(owners):
        raise ValueError('exact surface-to-Haus relationship coverage required')
    for who in owners:
        joins._hierarchy({'barony_id': 'CHECK', 'county_id': 'CHECK', 'duchy_id': 'CHECK',
                          'surface_fill': who, 'haus': political['surface_relations'][who]})
    expected_edges = {edge_key(row['left'], row['right']) for row in prepared['edges']}
    if set(political['frontier_support_u']) != expected_edges:
        raise ValueError('exact physical frontier evidence coverage required')
    members, scores, eligible = defaultdict(list), {}, {}
    for atom, unit in mapping.items():
        members[unit].append(atom)
    locks = specials.whole_unit_locks(dict(members), political['atom_locks'])
    if locks['status'] != 'PASS':
        raise ValueError('INFEASIBLE_NO_SPLIT: conflicting atom locks in one frozen district')
    for unit, atoms in members.items():
        scores[unit] = {who: 0 for who in owners}
        allowed = set(owners)
        for atom in atoms:
            row = political['atom_evidence'][atom]
            if set(row) != set(owners):
                raise ValueError('complete frozen evidence by active owner required')
            candidates = political['atom_eligible'][atom]
            if type(candidates) is not list or len(set(candidates)) != len(candidates) or not set(candidates) <= set(owners):
                raise ValueError('explicit unique eligible owners required')
            allowed &= set(candidates)
            for who in owners:
                if type(row[who]) is not dict or set(row[who]) != set(TERMS):
                    raise ValueError('separate physical, settlement-service and permitted-access terms required')
                scores[unit][who] += sum(_integer(row[who][term]) for term in TERMS)
        locked = locks['locks'].get(unit)
        if locked is not None:
            allowed &= {locked}
        eligible[unit] = sorted(allowed)
    supports = {}
    for edge in prepared['edges']:
        key = edge_key(edge['left'], edge['right'])
        if key not in political['frontier_support_u']:
            raise ValueError('INPUT_INCOMPLETE: missing frozen frontier support')
        value = _integer(political['frontier_support_u'][key])
        left, right = sorted((mapping[edge['left']], mapping[edge['right']]))
        if left != right:
            supports[left, right] = supports.get((left, right), 0)+value
    edges = [{'left': row['left'], 'right': row['right'], 'length_m': row['length_m'],
              'boundary_score': supports[row['left'], row['right']]}
             for row in frozen['assignment_prepared']['edges']]
    return {'unit_ids': sorted(members), 'owners': owners, 'eligible': eligible, 'scores': scores,
        'edges': edges, 'required_owners': owners, 'connected_owners': owners,
        'required_adjacency': political['required_adjacency'],
        'prohibited_adjacency': political['prohibited_adjacency'],
        'required_presence': political['required_presence'], 'limits': limits}


def apply_profile(problem, compiled, surface_relations):
    """Intersect compiled real-profile rules; never replace caller exclusions."""
    if compiled['status'] != 'PASS':
        raise ValueError(compiled['status']+': '+compiled['reason'])
    rules = compiled['restrictions']
    if (set(problem['owners']) != set(rules['owners']) or surface_relations != rules['surface_relations']
            or set(problem['unit_ids']) != set(rules['eligible'])):
        raise ValueError('actual Diadem active fills, typed relationships or frozen units differ')
    result = deepcopy(problem)
    for unit in result['unit_ids']:
        result['eligible'][unit] = sorted(set(result['eligible'][unit]) & set(rules['eligible'][unit]))
    for key in ('required_owners', 'connected_owners'):
        result[key] = sorted(set(result[key]) | set(rules[key]))
    for key in ('required_adjacency', 'prohibited_adjacency'):
        result[key] = [list(pair) for pair in sorted({tuple(sorted(pair)) for pair in result[key]+rules[key]})]
    for key in ('required_presence', 'required_any_adjacency'):
        result[key] = list({p.sha(row): row for row in result.get(key, [])+rules[key]}.values())
    return result


def run(physical, political_loader, *, cache=True, cache_root=None):
    """Reference entrypoint; Stage2 inputs are loaded only after a complete freeze.

    physical is a separately source-bound, explicit-input owner-neutral packet.
    political_loader receives an isolated copy of the frozen formation, so its
    separately bound Stage2/profile packet can name the exact immutable cut.
    Neither can authorise an actual Diadem map or silently choose inputs.
    """
    controls = owner.binding(verify_sources=True)
    execution = p.identity()
    physical = deepcopy(physical)
    fields = {'schema', 'context', 'frame', 'terrain_generation', 'water_generation',
              'source_status', 'source_binding', 'feature_transform', 'uncertainty',
              'supports', 'domain', 'levels', 'hard_facts', 'limits'}
    if type(physical) is not dict or set(physical) != fields or physical['schema'] != 'diadem.political-physical-input.r20':
        raise ValueError('exact owner-neutral physical input packet required')
    inputs.context(physical['context']); inputs.frame(physical['frame'])
    if (physical['context']['spatial_frame_id'] != physical['frame']['spatial_frame_id'] or
            physical['context']['vertical_reference'] != physical['frame']['vertical_reference']):
        raise ValueError('physical context/frame differs')
    if physical['source_status'] != 'SYNTHETIC TEST':
        raise ValueError('actual map generation remains held for replacement terrain and acceptance')
    for field in ('terrain_generation', 'water_generation', 'feature_transform', 'uncertainty'):
        if type(physical[field]) is not str or not physical[field] or physical[field] in inputs.UNRESOLVED:
            raise ValueError('explicit physical generation/transform/uncertainty required')
    if physical['source_binding'].get('role') != 'FORMATION_AUTHORITY':
        raise ValueError('formation may not read Stage2 or rejected source roles')
    physical_lineage = _source(physical['source_binding'], 'FORMATION_AUTHORITY', execution)
    reporting = []
    binding = {'owner': controls, 'context': physical['context'], 'frame': physical['frame'],
               'physical_input_sha256': p.sha(physical)}
    prepared = _stage('geometry', {'supports': physical['supports'], 'domain': physical['domain']}, binding,
        lambda: geometry.prepare(physical['supports'], physical['domain']),
        lambda value: value == geometry.prepare(physical['supports'], physical['domain']) or (_ for _ in ()).throw(ValueError('cached topology differs')),
        cache, cache_root, reporting)
    formed = hierarchy.form(prepared, physical['levels'], binding=binding, limits=physical['limits'],
                            hard_facts=physical['hard_facts'], cache=cache, cache_root=cache_root)
    reporting.extend(formed['reporting'])
    if formed['scientific']['status'] != 'PASS':
        p.verify(execution)
        science = {'status': formed['scientific']['status'], 'formation': formed['scientific'],
            'context': physical['context'], 'frame': physical['frame'], 'owner_binding': controls,
            'political_input_read': False, 'source_status': 'SYNTHETIC TEST'}
        return {'scientific': science, 'scientific_sha256': p.sha(science),
                'execution': execution, 'reporting': reporting}
    frozen = deepcopy(formed['scientific']); freeze = formed['freeze_sha256']
    political = deepcopy(political_loader(deepcopy(frozen)))
    political_fields = {'context', 'terrain_generation', 'water_generation', 'source_binding', 'owners',
        'atom_evidence', 'atom_eligible', 'atom_locks', 'frontier_support_u', 'required_adjacency',
        'prohibited_adjacency', 'required_presence', 'surface_relations', 'sites', 'access'}
    if (type(political) is not dict or not political_fields <= set(political)
            or set(political)-political_fields-{'diadem_profile_input'}):
        raise ValueError('exact separately bound Stage2 input packet required')
    if (political['context'] != physical['context'] or political['terrain_generation'] != physical['terrain_generation']
            or political['water_generation'] != physical['water_generation']):
        raise ValueError('Stage2 world/date/frame or physical generations differ')
    if political['source_binding'].get('role') != 'STAGE2_CONTEXT':
        raise ValueError('admitted separate Stage2 evidence required')
    political_lineage = _source(political['source_binding'], 'STAGE2_CONTEXT', execution)
    if p.sha(frozen) != freeze:
        raise ValueError('formation changed after political evidence read')
    problem = _problem(prepared, frozen, political, physical['limits'])
    compiled = None
    if 'diadem_profile_input' in political:
        compiled = profile.compile_restrictions(frozen, political['diadem_profile_input'],
            expected_binding={'context': physical['context'], 'frame': physical['frame'],
                'terrain_generation': physical['terrain_generation'], 'water_generation': physical['water_generation'],
                'freeze_sha256': freeze, 'source_binding': political['source_binding']})
        problem = apply_profile(problem, compiled, political['surface_relations'])
    solver = {}

    def produce():
        value = assignment.solve(problem); solver.update(value['diagnostics'])
        if value['solution']['status'] == 'INCOMPLETE':
            raise RuntimeError('SEARCH_INCOMPLETE: '+value['solution']['reason'])
        return value['solution']

    def validate(value):
        if value['status'] not in ('MODELLED', 'POLYCENTRIC_UNRESOLVED', 'FAILED'):
            raise ValueError('complete assignment outcome required')
        if value['status'] == 'MODELLED':
            labels = value['assignment']
            if set(labels) != set(problem['unit_ids']):
                raise ValueError('assignment coverage differs')
            dissolved = geometry.dissolve(frozen['assignment_prepared'], labels)
            if dissolved['disconnected_groups']:
                raise ValueError('disconnected assigned mainland realm')

    assigned = _stage('assignment', {'freeze_sha256': freeze, 'problem': problem},
        dict(binding, political_input_sha256=p.sha(political)), produce, validate, cache, cache_root, reporting)
    reporting.append({'solver': solver})
    science = {'status': assigned['status'], 'context': physical['context'], 'frame': physical['frame'],
        'source_status': 'SYNTHETIC TEST', 'owner_binding': controls, 'formation': frozen,
        'physical_freeze_sha256': freeze, 'assignment': assigned,
        'source_lineage': {'formation': physical_lineage, 'assignment': political_lineage},
        'political_input_sha256': p.sha(political), 'actual_diadem_map_accepted': False}
    if compiled is not None:
        science['diadem_profile'] = compiled
    if assigned['status'] == 'MODELLED':
        labels = assigned['assignment']
        atom_hierarchy = {}
        for atom, ids in frozen['leaf_hierarchy'].items():
            fill = labels[frozen['atom_to_assignment_unit'][atom]]
            atom_hierarchy[atom] = {'barony_id': ids[0], 'county_id': ids[1], 'duchy_id': ids[2],
                                    'surface_fill': fill, 'haus': political['surface_relations'][fill]}
        science['hierarchy'] = atom_hierarchy
        science['borders'] = geometry.dissolve(frozen['assignment_prepared'], labels)
        generation = p.sha(science)
        join_binding = {'generation': generation, 'expected_generation': generation,
                        'context': physical['context'], 'expected_context': physical['context']}
        science['sites'] = joins.sites(political['sites'], prepared, atom_hierarchy, **join_binding)
        science['access'] = joins.access(political['access'], science['sites'], **join_binding)
        science['political_generation'] = generation
    p.verify(execution)
    return {'scientific': science, 'scientific_sha256': p.sha(science),
            'execution': execution, 'reporting': reporting}
