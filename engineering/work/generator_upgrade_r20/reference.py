"""Declared twelve-atom numerical reference, not a Diadem district map.

Metre rectangles are exact topology. Edge values are ALREADY integrated integer
physical-evidence hypotheses (R20-W1), not rates per metre or measured slopes.
Ridge/reach continuity distinctions at three declared scales are separate input
arrays. Identity transform, one quantum quantisation, zero fixture uncertainty;
there are no inferred terrain coefficients, target unit counts or area penalties.
Real terrain-to-evidence calibration and uncertainty remain owner/data gates.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
from . import hierarchy, owner, provenance as p

LIMITS = {'max_cut_rounds': 128, 'node_limit': 100000, 'time_limit_s': 30.0}


def _source(role):
    return {'path': str(Path(__file__).resolve()), 'sha256': hashlib.sha256(p.checked(Path(__file__).resolve())).hexdigest(),
            'role': role, 'status': 'SYNTHETIC TEST'}


def physical():
    context = {'world_id': 'R20_NUMERICAL_REFERENCE', 'snapshot_id': 'FIXED_DATE_1',
        'calendar_id': 'REFERENCE', 'spatial_frame_id': 'R20_LOCAL_METRES',
        'vertical_reference': 'NOT_USED_2D', 'scenario_id': 'R20_W1_CONNECTED'}

    def rectangle(left, right):
        return {'type': 'Polygon', 'coordinates': [[[left, 0], [right, 0], [right, 1000], [left, 1000], [left, 0]]]}

    supports = [{'id': 'atom-'+str(i), 'geometry': rectangle(1000*i, 1000*(i+1))} for i in range(12)]
    levels = []
    for index, separators in enumerate(({1, 3, 5, 7, 9}, {3, 5, 7}, {3, 7})):
        levels.append({'id': 'L'+str(index+1), 'alias': hierarchy.ALIASES[index],
            'edge_costs': [{'left': 'atom-'+str(i), 'right': 'atom-'+str(i+1),
                'separation_u': 9 if i in separators else 0,
                'continuity_u': 0 if i in separators else 6} for i in range(11)],
            'must_join': [], 'must_cut': [['atom-3', 'atom-4']]})
    return {'schema': 'diadem.political-physical-input.r20', 'context': context,
        'frame': {'spatial_frame_id': context['spatial_frame_id'], 'horizontal_unit': 'm',
            'x_direction': 'east', 'y_direction': 'north', 'vertical_reference': 'NOT_USED_2D',
            'evidence': 'Explicit synthetic Cartesian support; no Diadem transform'},
        'terrain_generation': 'R20_HYPOTHETICAL_PHYSICAL_V1', 'water_generation': 'R20_HYPOTHETICAL_REACHES_V1',
        'source_status': 'SYNTHETIC TEST', 'source_binding': _source('FORMATION_AUTHORITY'),
        'feature_transform': 'IDENTITY_OF_EXPLICIT_INTEGRATED_INTEGER_EDGE_QUANTA_V1',
        'uncertainty': 'ZERO_FOR_THIS_NUMERICAL_ORACLE_ONLY; REAL_INPUTS_REQUIRE_DECLARED_UNCERTAINTY',
        'supports': supports, 'domain': rectangle(0, 12000), 'levels': levels,
        'hard_facts': [{'id': 'persistent-physical-barrier', 'kind': 'must_cut',
                        'atoms': ['atom-3', 'atom-4'], 'active_levels': ['L1', 'L2', 'L3']}],
        'limits': dict(LIMITS)}


def political(_frozen=None):
    """Called by the pipeline only after complete physical hierarchy freeze."""
    base = physical()
    case = next(row for row in owner.read_cases()['assignment_cases'] if row['id'] == 'A01-whole-unit-evidence')
    atoms = [row['id'] for row in base['supports']]
    evidence = {atom: {who: {key: 0 for key in ('physical_compatibility_u', 'settlement_service_u', 'permitted_access_u')}
                       for who in case['owners']} for atom in atoms}
    # A01 whole-upper-unit evidence is attached to one support in each upper
    # group, not repeated by area, grid count or number of child settlements.
    for atom, unit in [('atom-0', 'u'), ('atom-4', 'v'), ('atom-8', 'w')]:
        for who, score in case['scores'][unit].items():
            evidence[atom][who]['physical_compatibility_u'] = score
    return {'context': deepcopy(base['context']), 'terrain_generation': base['terrain_generation'],
        'water_generation': base['water_generation'], 'source_binding': _source('STAGE2_CONTEXT'),
        'owners': case['owners'], 'atom_evidence': evidence,
        'atom_eligible': {atom: list(case['owners']) for atom in atoms},
        'atom_locks': {'atom-0': 'A', 'atom-11': 'B'},
        'frontier_support_u': {p.encoded(sorted(('atom-'+str(i), 'atom-'+str(i+1)))).decode(): 1 for i in range(11)},
        'required_adjacency': [['A', 'B']], 'prohibited_adjacency': [], 'required_presence': [],
        'surface_relations': {'A': ['abstract-A'], 'B': ['abstract-B']},
        'sites': [{'id': 's1', 'xy_m': [500, 500], 'source_status': 'SYNTHETIC TEST'},
                  {'id': 's2', 'xy_m': [8500, 500], 'source_status': 'SYNTHETIC TEST'}],
        'access': [{'id': 'route', 'from_site': 's1', 'to_site': 's2', 'physical_travel_seconds': 7200,
            'permission': 'UNKNOWN', 'mode': 'walk', 'season': 'reference season',
            'evidence': 'Hypothetical physical route; no grant of permission', 'source_status': 'SYNTHETIC TEST'}]}
