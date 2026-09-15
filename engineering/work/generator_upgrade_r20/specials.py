"""Whole-unit special semantics; no geography, rights or distance inference.

Owner-contract adoption and external source readback belong to the caller. The
profile is compiled from its supplied bound matrix, never from invented names.
Distance intervals are frozen Water boundary measurements, not centroids. These
helpers do not certify an actual map, physical graph coverage or legal grants.
"""
from copy import deepcopy
from fractions import Fraction
import math

from . import inputs, provenance as p

SCHEMA = 'diadem.political-special-semantics.r20'
PHASE_ROLES = {'FORMATION': frozenset({'FORMATION_AUTHORITY'}),
               'HIERARCHY': frozenset({'FORMATION_AUTHORITY'}),
               'ASSIGNMENT': frozenset({'FORMATION_AUTHORITY', 'STAGE2_CONTEXT'}),
               'ISLAND': frozenset({'WATER_BOUNDARY_DISTANCE'})}


def _id(value):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError('bounded explicit identity required')
    return value


def _ids(values, *, empty=False):
    if type(values) is not list or len(values) > 8192 or (not values and not empty):
        raise ValueError('bounded explicit identity list required')
    result = [_id(value) for value in values]
    if len(set(result)) != len(result):
        raise ValueError('duplicate identity')
    return result


def _owner(value):
    if _id(value) in inputs.UNRESOLVED:
        raise ValueError('unresolved owner is not a jurisdiction or a lock')
    return value


def _number(value):
    if (type(value) not in (int, float, str) or
            (type(value) is str and len(value) > 4096) or
            (type(value) is float and not math.isfinite(value))):
        raise ValueError('finite bounded exact or represented number required')
    result = Fraction(value)
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > 8192:
        raise ValueError('number exceeds bounded exact arithmetic')
    return result


def _members(members):
    if type(members) is not dict or not 1 <= len(members) <= 8192:
        raise ValueError('explicit bounded whole-unit membership required')
    result = {_id(key): set(_ids(value)) for key, value in members.items()}
    if sum(map(len, result.values())) > 65536:
        raise ValueError('membership envelope exceeded')
    return result


def whole_unit_locks(members, atom_locks):
    """Lift compatible atom locks; conflicting locks never split their unit."""
    groups = _members(members)
    union = set().union(*groups.values())
    if sum(map(len, groups.values())) != len(union):
        raise ValueError('frozen units must not overlap')
    if type(atom_locks) is not dict or not set(atom_locks) <= union:
        raise ValueError('locks must refer to supplied atoms')
    for value in atom_locks.values():
        _owner(value)
    locks, conflicts = {}, {}
    for unit, atoms in sorted(groups.items()):
        owners = sorted({atom_locks[a] for a in atoms if a in atom_locks})
        if len(owners) == 1:
            locks[unit] = owners[0]
        elif owners:
            conflicts[unit] = owners
    return {'status': 'INFEASIBLE_NO_SPLIT' if conflicts else 'PASS',
            'locks': locks, 'conflicts': conflicts, 'membership_sha256': p.sha(members),
            'unit_mutations': 0}


def surface_accounting(units):
    """Each horizontal unit contributes once, irrespective of vertical relations."""
    if type(units) is not list or not 1 <= len(units) <= 8192:
        raise ValueError('explicit bounded surface units required')
    seen, by_owner, by_unit = set(), {}, {}
    for row in units:
        if type(row) is not dict or not {'id', 'area', 'owner'} <= set(row):
            raise ValueError('surface identity, area and nominal owner required')
        ident, owner = _id(row['id']), _owner(row['owner'])
        if ident in seen:
            raise ValueError('surface unit counted more than once')
        area = _number(row['area'])
        if area <= 0:
            raise ValueError('surface units require positive area; arena is separate')
        if 'layers' in row:
            _ids(row['layers'])
        if 'service_sponsor' in row:
            _id(row['service_sponsor'])
        seen.add(ident); by_unit[ident] = str(area)
        by_owner[owner] = by_owner.get(owner, Fraction(0)) + area
    return {'status': 'PASS', 'surface_area': str(sum(by_owner.values(), Fraction(0))),
            'area_by_unit': dict(sorted(by_unit.items())),
            'area_by_owner': {key: str(value) for key, value in sorted(by_owner.items())},
            'units': deepcopy(units), 'sponsorship_transfers_sovereignty': False}


def island_owner(distances, eligible, *, near_tie_u, shoreline_binding):
    """A winner must beat every eligible rival throughout both error intervals."""
    allowed = _ids(eligible)
    for owner in allowed:
        _owner(owner)
    required = {'mainland_generation', 'shoreline_generation', 'distance_source_sha256',
                'context', 'source_status', 'distance_unit', 'source_role'}
    if type(shoreline_binding) is not dict or set(shoreline_binding) != required:
        raise ValueError('complete independently supplied frozen shoreline binding required')
    inputs.context(shoreline_binding['context'])
    for key in ('mainland_generation', 'shoreline_generation', 'source_status'):
        if _id(shoreline_binding[key]) in inputs.UNRESOLVED | inputs.REJECTED_ROLES:
            raise ValueError('unresolved shoreline binding')
    digest = shoreline_binding['distance_source_sha256']
    if (type(digest) is not str or len(digest) != 64 or
            any(c not in '0123456789abcdef' for c in digest)):
        raise ValueError('bound distance source hash required')
    if (shoreline_binding['distance_unit'] != 'm' or
            shoreline_binding['source_role'] != 'WATER_BOUNDARY_DISTANCE'):
        raise ValueError('Water boundary-distance metre intervals required')
    tolerance = _number(near_tie_u)
    if tolerance < 0 or type(distances) is not dict or len(distances) > 8192:
        raise ValueError('nonnegative predeclared uncertainty and bounded distances required')
    intervals = {}
    for owner, pair in distances.items():
        _id(owner)
        if type(pair) is not list or len(pair) != 2:
            raise ValueError('explicit lower/upper distance interval required')
        low, high = map(_number, pair)
        if not 0 <= low <= high:
            raise ValueError('ordered nonnegative distance bounds required')
        intervals[owner] = low, high
    missing = sorted(set(allowed) - set(intervals))
    winners = [] if missing else [owner for owner in allowed if all(
        intervals[owner][1] + tolerance < intervals[other][0]
        for other in allowed if other != owner)]
    owner = winners[0] if len(winners) == 1 else None
    return {'status': 'ASSIGNED' if owner else 'UNKNOWN', 'owner': owner,
            'eligible': sorted(allowed), 'missing_distances': missing,
            'intervals_m': {key: list(map(str, pair)) for key, pair in sorted(intervals.items())},
            'near_tie_m': str(tolerance), 'binding': deepcopy(shoreline_binding),
            'input_sha256': p.sha({'distances': distances, 'eligible': sorted(allowed),
                                   'near_tie_u': near_tie_u, 'binding': shoreline_binding}),
            'relationship': 'DETACHED_DEPENDENCY_NOT_MAINLAND_CONNECTIVITY'}


def reachability(physical, permission):
    """False is a supplied physical finding, never inferred from a missing edge."""
    if physical is not None and type(physical) is not bool:
        raise ValueError('physical feasibility must be true, false or unknown')
    if permission not in ('ALLOWED', 'DENIED', 'PROHIBITED', 'CONDITIONAL', 'UNKNOWN', 'CONFLICT'):
        raise ValueError('explicit legal permission required')
    status = ('NOT_PHYSICALLY_FEASIBLE' if physical is False else
              'NOT_PERMITTED' if permission in ('DENIED', 'PROHIBITED') else
              'CONFLICT' if permission == 'CONFLICT' else
              'PERMITTED' if physical is True and permission == 'ALLOWED' else 'UNKNOWN')
    return {'status': status, 'physical': physical, 'permission': permission,
            'sovereignty_transfer': False}


def hydraulic_path(edges, source, target, *, coverage_complete, reject_open=True):
    """Undirected open hydraulic continuity; a locked/dry transfer is a break.

Incomplete coverage can establish a found bypass, but cannot certify its absence.
The caller supplies the prohibited endpoint pair; names never drive this helper.
"""
    _id(source); _id(target)
    if (type(edges) is not list or len(edges) > 65536 or
            type(coverage_complete) is not bool or type(reject_open) is not bool):
        raise ValueError('bounded explicit hydraulic graph and coverage required')
    graph, seen = {}, set()
    for row in edges:
        if type(row) is not list or len(row) != 3 or type(row[2]) is not bool:
            raise ValueError('hydraulic edge requires two nodes and explicit open flag')
        left, right = _id(row[0]), _id(row[1])
        pair = tuple(sorted((left, right)))
        if left == right or pair in seen:
            raise ValueError('distinct unique hydraulic compartment edge required')
        seen.add(pair)
        graph.setdefault(left, set()); graph.setdefault(right, set())
        if row[2]:
            graph[left].add(right); graph[right].add(left)
    if source not in graph or target not in graph:
        raise ValueError('hydraulic endpoints must be explicit graph nodes')
    reached, pending = {source}, [source]
    while pending:
        for neighbour in graph[pending.pop()] - reached:
            reached.add(neighbour); pending.append(neighbour)
    found = target in reached
    status = 'FAIL' if found and reject_open else 'PASS' if found or coverage_complete else 'UNKNOWN'
    return {'status': status, 'all_open_path': True if found else False if coverage_complete else None,
            'coverage_complete': coverage_complete, 'prohibited_pair': [source, target],
            'hydraulic_reachable_nodes': sorted(reached), 'represented_surface_area': '0'}


def arena(geometry_type, owner, represented_area):
    valid = geometry_type == 'POINT' and owner is None and _number(represented_area) == 0
    return {'status': 'PASS' if valid else 'FAIL', 'geometry_type': geometry_type,
            'owner': owner, 'represented_area': str(_number(represented_area)),
            'physical_size_assertion': False}


def hierarchy_cut(members, selected, atoms):
    groups, selection, universe = _members(members), _ids(selected), set(_ids(atoms))
    if not set(selection) <= set(groups) or not set().union(*groups.values()) <= universe:
        raise ValueError('cut references unknown units or atoms')
    counts = {atom: 0 for atom in universe}
    for unit in selection:
        for atom in groups[unit]:
            counts[atom] += 1
    gaps = sorted(atom for atom, count in counts.items() if count == 0)
    overlaps = sorted(atom for atom, count in counts.items() if count > 1)
    return {'status': 'FAIL' if gaps or overlaps else 'PASS', 'selected': sorted(selection),
            'gaps': gaps, 'overlaps': overlaps, 'atoms': sorted(universe),
            'membership_sha256': p.sha(members)}


def phase_role(phase, role):
    _id(phase); _id(role)
    return {'status': 'ALLOW' if role in PHASE_ROLES.get(phase, ()) and
            role not in inputs.REJECTED_ROLES else 'REJECT', 'phase': phase, 'role': role}


def profile(matrix, *, source):
    """Project the independently bound actual owner rows; this is not map adoption."""
    if type(source) is not dict or not {'path', 'sha256', 'status'} <= set(source):
        raise ValueError('verified owner-matrix source receipt required')
    _id(source['path']); _id(source['status'])
    digest = source['sha256']
    if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('exact owner-matrix source hash required')
    model, rows = matrix['surface_model'], matrix['haus_records']
    if (type(rows) is not list or len(rows) != 20 or model['primary_haus_records'] != 20 or
            model['mainland_surface_fill_classes'] != 20 or model['ordinary_named_haus_surface_classes'] != 18):
        raise ValueError('actual profile requires 20 Primary records and 18 ordinary/2 special fills')
    shared, neutral = _id(model['shared_great_forest_surface_class']), _id(model['neutral_gate_surface_class'])
    if shared == neutral:
        raise ValueError('shared and neutral surface classes must differ')
    records, fills, seen, ordinary, layered = [], {}, set(), [], []
    keys = ('haus_id', 'display_name', 'surface_role', 'surface_fill_id')
    for row in rows:
        record = {key: _id(row[key]) for key in keys}
        ident, fill = record['haus_id'], record['surface_fill_id']
        if ident in seen:
            raise ValueError('duplicate Primary identity')
        seen.add(ident); records.append(record)
        if record['surface_role'] == 'ordinary_named_surface_jurisdiction':
            if fill in fills or fill in (shared, neutral):
                raise ValueError('ordinary surface class must be independent')
            ordinary.append(fill)
        elif record['surface_role'] == 'vertical_layer_in_shared_great_forest_surface' and fill == shared:
            layered.append(ident)
        else:
            raise ValueError('unrecognised explicitly supplied Primary surface relationship')
        fills.setdefault(fill, []).append(ident)
    if len(ordinary) != 18 or len(layered) != 2 or len(fills) != 19:
        raise ValueError('actual Primary/surface relationship inventory mismatch')
    fills[neutral] = []
    sea = _ids(matrix['sea_frontage']['required_haus_ids'])
    prohibited = _ids(matrix['sea_frontage']['prohibited_haus_ids'])
    if len(sea) != 4 or set(sea) & set(prohibited) or set(sea) | set(prohibited) != seen:
        raise ValueError('explicit four-owner Sea whitelist and complete exclusions required')
    if set(matrix['sea_frontage']['prohibited_special_ids']) != {shared, neutral}:
        raise ValueError('special surfaces cannot silently acquire Sea frontage')
    islands = matrix['special_systems']['natural_islands']
    island_ids = _ids([row['island_id'] for row in islands['registry']])
    if type(islands['count']) is not int or islands['count'] != 14 or len(island_ids) != islands['count']:
        raise ValueError('explicit fourteen-island identity inventory required')
    return {'schema': SCHEMA, 'status': matrix['status'], 'source': deepcopy(source),
            'primary_records': sorted(records, key=lambda row: row['haus_id']),
            'surface_fills': [{'id': key, 'primary_haus_ids': sorted(value),
                               'kind': 'SHARED' if key == shared else 'NEUTRAL' if key == neutral else 'ORDINARY'}
                              for key, value in sorted(fills.items())],
            'ordinary_fill_ids': sorted(ordinary), 'shared_fill_id': shared, 'neutral_fill_id': neutral,
            'sea_owner_ids': sorted(sea), 'sea_prohibited_haus_ids': sorted(prohibited),
            'natural_island_count_required': islands['count'], 'natural_island_ids': sorted(island_ids),
            'island_inventory_scope': 'RETAINED IDENTITIES ONLY; NO GEOMETRY OR OWNERSHIP ADOPTION',
            'islands_separate_from_mainland': True,
            'actual_geometry_accepted': False, 'matrix_content_sha256': p.sha(matrix)}
