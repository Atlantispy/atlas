"""Owner-neutral whole-child hierarchy, frozen before political evidence."""
from collections import defaultdict
from copy import deepcopy
from . import geometry, partition, provenance as p
from .cache import StageCache

ALIASES = ('manor_or_barony_analogue', 'county_analogue', 'duchy_or_march_analogue')


def _cost(value):
    if type(value) is not int or not 0 <= value <= 1000000:
        raise ValueError('explicit bounded nonnegative integer evidence quanta required')
    return value


def project(prepared, membership, level):
    """Add level-specific boundary contributions; never multiply on subdivision."""
    fields = {'id', 'alias', 'edge_costs', 'must_join', 'must_cut'}
    if type(level) is not dict or set(level) != fields:
        raise ValueError('exact owner-neutral hierarchy level required')
    edge_by_pair = {tuple(sorted((edge['left'], edge['right']))): edge for edge in prepared['edges']}
    costs = defaultdict(lambda: [0, 0])
    for row in level['edge_costs']:
        if type(row) is not dict or set(row) != {'left', 'right', 'separation_u', 'continuity_u'}:
            raise ValueError('exact physical edge contribution required')
        pair = tuple(sorted((row['left'], row['right'])))
        if pair not in edge_by_pair:
            raise ValueError('physical evidence must lie on an actual positive boundary')
        costs[pair][0] += _cost(row['separation_u'])
        costs[pair][1] += _cost(row['continuity_u'])
    if set(costs) != set(edge_by_pair):
        raise ValueError('INPUT_INCOMPLETE: every physical edge needs explicit level evidence')
    projected, fixed = {}, 0
    for (left, right), edge in edge_by_pair.items():
        a, b = sorted((membership[left], membership[right]))
        separation, continuity = costs[(left, right)]
        if a == b:
            fixed += separation
            continue
        pair = (a, b)
        if pair not in projected:
            projected[pair] = {'left': a, 'right': b, 'length_m': 0., 'separation_u': 0, 'continuity_u': 0}
        projected[pair]['length_m'] += edge['length_m']
        projected[pair]['separation_u'] += separation
        projected[pair]['continuity_u'] += continuity
    constraints = {}
    for kind in ('must_join', 'must_cut'):
        translated = set()
        for pair in level[kind]:
            if (type(pair) is not list or len(pair) != 2 or pair[0] == pair[1]
                    or any(ident not in membership for ident in pair)):
                raise ValueError('hard physical pair must reference distinct current atoms')
            a, b = sorted(membership[ident] for ident in pair)
            if a == b:
                if kind == 'must_cut':
                    raise ValueError('CONFLICT: higher-level cut would split a frozen child')
            else:
                translated.add((a, b))
        constraints[kind] = [list(pair) for pair in sorted(translated)]
    return {'unit_ids': sorted(set(membership.values())), 'edges': [projected[k] for k in sorted(projected)],
            **constraints}, fixed


def scoped_facts(levels, hard_facts):
    """Require explicit level scope; no persistent constraint may disappear."""
    if type(hard_facts) is not list:
        raise ValueError('explicit hard physical facts with active_levels required')
    ids = [row['id'] for row in levels]
    if any(type(ident) is not str or not ident for ident in ids) or len(set(ids)) != len(ids):
        raise ValueError('unique declared hierarchy level identities required')
    expected = {ident: {'must_join': set(), 'must_cut': set()} for ident in ids}
    seen = set()
    for fact in hard_facts:
        if type(fact) is not dict or set(fact) != {'id', 'kind', 'atoms', 'active_levels'}:
            raise ValueError('exact hard physical fact required')
        ident, kind, pair, active = (fact[key] for key in ('id', 'kind', 'atoms', 'active_levels'))
        if type(ident) is not str or not ident or ident in seen or kind not in ('must_join', 'must_cut'):
            raise ValueError('unique typed hard physical fact required')
        seen.add(ident)
        if (type(pair) is not list or len(pair) != 2 or any(type(v) is not str or not v for v in pair)
                or pair[0] == pair[1] or type(active) is not list or not active
                or any(type(v) is not str for v in active) or len(set(active)) != len(active)
                or not set(active) <= set(ids)):
            raise ValueError('distinct atoms and explicit known active_levels required')
        for level in active:
            expected[level][kind].add(tuple(sorted(pair)))
    for level in levels:
        for kind in ('must_join', 'must_cut'):
            actual = level[kind]
            if type(actual) is not list or any(type(pair) is not list or len(pair) != 2
                    or any(type(v) is not str for v in pair) for pair in actual):
                raise ValueError('exact scoped hard pairs required')
            if {tuple(sorted(pair)) for pair in actual} != expected[level['id']][kind]:
                raise ValueError('CONFLICT: level constraints differ from declared active_levels')


def form(prepared, levels, *, binding, limits, hard_facts=None, cache=True, cache_root=None):
    """Three structural levels; reuse each complete source-bound solved level."""
    if type(levels) is not list or len(levels) != 3 or [row['alias'] for row in levels] != list(ALIASES):
        raise ValueError('exact predeclared three-level structural hierarchy required')
    scoped_facts(levels, hard_facts)
    ids = [row['id'] for row in prepared['supports']]
    current = {ident: ident for ident in ids}
    lineage = {ident: [] for ident in ids}
    records, reporting = [], []
    for level in levels:
        problem, fixed_cost = project(prepared, current, level)
        problem['limits'] = deepcopy(limits)
        captured = {}

        def produce():
            solved = partition.solve(problem)
            captured.update(solved['diagnostics'])
            if solved['solution']['status'] == 'INCOMPLETE':
                raise RuntimeError('SEARCH_INCOMPLETE: '+str(solved['solution']))
            return solved['solution']

        def validate(value):
            if value.get('status') not in ('PASS', 'POLYCENTRIC_UNRESOLVED', 'FAILED'):
                raise ValueError('complete partition result or explicit diagnostic required')
            if value['status'] == 'PASS':
                members = value['memberships']
                if set(members) != set(problem['unit_ids']):
                    raise ValueError('cached level membership coverage differs')
                atom_groups = {atom: members[child] for atom, child in current.items()}
                dissolved = geometry.dissolve(prepared, atom_groups)
                if dissolved['disconnected_groups']:
                    raise ValueError('disconnected physical hierarchy block')

        invocation = {'prepared_sha256': p.sha(prepared), 'children': current,
                      'level': level, 'problem': problem}
        store = StageCache('formation-'+level['id'], binding, cache_root) if cache else None
        if store:
            solution, hit = store.reuse(invocation, produce, validate)
        else:
            solution = produce(); validate(solution); hit = False
        reporting.append({'level': level['id'], 'hit': hit, 'stats': store.stats if store else {},
                          'warnings': store.warnings if store else [], 'solver': captured})
        records.append({'id': level['id'], 'alias': level['alias'], 'solution': solution,
                        'fixed_child_cost_u': fixed_cost, 'problem_sha256': p.sha(problem)})
        if solution['status'] != 'PASS':
            return {'scientific': {'status': solution['status'], 'levels': records,
                    'assignment_allowed': False, 'complete_diagnostic_atom_ids': sorted(ids)},
                    'reporting': reporting}
        current = {atom: solution['memberships'][child] for atom, child in current.items()}
        for atom in ids:
            lineage[atom].append(current[atom])
    grouped = geometry.dissolve(prepared, current)
    upper = geometry.prepare([{'id': row['id'], 'geometry': row['geometry']}
                              for row in grouped['groups']], prepared['domain'])
    science = {'status': 'PASS', 'levels': records, 'assignment_allowed': True,
        'structural_status': 'STRUCTURAL_ANALOGY_ONLY_NOT_DIADEM_TITLE_CANON',
        'leaf_hierarchy': lineage, 'atom_to_assignment_unit': current,
        'assignment_prepared': upper, 'formation_input_sha256': p.sha(
            {'prepared': prepared, 'levels': levels, 'hard_facts': hard_facts, 'binding': binding, 'limits': limits})}
    return {'scientific': science, 'freeze_sha256': p.sha(science), 'reporting': reporting}
