"""Explicit frame and transitive source-use gates for replacement districts."""
from pathlib import Path
import hashlib
from . import provenance as p

FRAME_FIELDS = {'world_id', 'snapshot_id', 'calendar_id', 'spatial_frame_id',
                'vertical_reference', 'scenario_id'}
UNRESOLVED = frozenset({'UNKNOWN', 'CONFLICT', 'INCOMPLETE', 'NOT_ASSERTED', 'PENDING'})
REJECTED_HASHES = frozenset({
    '075930ef63a3ce2f3c8c6d14674b1dace1f8653ff213c82cd472fe9afe4898ba',
    '180267c6fa902ca8b4dd6516494dd181b1406cd917b76577a5f83a4cbf37e2af',
    'fce774e18ae4ceb6a065c9425b1612dc79bd16b8af260e02f82db474cf1c13e8',
    '6a993b8d6670c1ab044854f94dbaa169daefbb7b6870b63655dd75c264637731',
    '1986ff3bba8d87ab1c89eb1491fca7b941c8ef4eae8a6e2e1d07d4647c34d808',
    'cb6600aa64d321e6240900e0622407b99a9bb81914f75de75cd44579e4958cb9',
})
REJECTED_ROLES = frozenset({'REJECTED_CONTROL_DO_NOT_SEED', 'PRIOR_POLITICAL_CANDIDATE',
    'LEGACY_STAGE6C_V11', 'GUARDED_DIAGONAL_PILOT', 'INHERITED_STAGE3_POLITICAL_MASK',
    'INHERITED_STAGE4_HOST_JURISDICTION', 'INHERITED_STAGE5B_POLITICAL_FILTER'})


def context(value):
    if type(value) is not dict or set(value) != FRAME_FIELDS or any(
            type(item) is not str or not item.strip() or len(item) > 4096 or item in UNRESOLVED for item in value.values()):
        raise ValueError('complete fixed-date common snapshot context required')
    return value


def frame(value):
    if type(value) is not dict or set(value) != {'spatial_frame_id', 'horizontal_unit',
            'x_direction', 'y_direction', 'vertical_reference', 'evidence'}:
        raise ValueError('explicit projected spatial frame required')
    if value['horizontal_unit'] != 'm' or value['x_direction'] != 'east' or value['y_direction'] not in ('north', 'south'):
        raise ValueError('already registered metre frame required; no implicit transform')
    if any(type(item) is not str or not item.strip() or item in UNRESOLVED for item in value.values()):
        raise ValueError('frame identity and evidence cannot be unknown')
    return value


def source(path, expected):
    """Check a bounded declared small packet, not a path/mtime-only cache key."""
    raw = p.checked(Path(path), expected)
    return {'path': str(Path(path)), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def lineage(nodes, selected, trusted_leaves, allowed_roles):
    """Validate all declared ancestors, including rejected derived descendants.

    trusted_leaves is supplied by the hash-bound owner/input contract, not by
    relabelling arbitrary caller data. Every leaf's current bytes are checked.
    This verifies declared provenance, not concealed or fabricated lineage.
    """
    if type(nodes) is not list or not 1 <= len(nodes) <= 10000:
        raise ValueError('bounded nonempty declared source graph required')
    if (type(selected) is not list or not selected or len(set(selected)) != len(selected)
            or any(type(item) is not str for item in selected)):
        raise ValueError('explicit unique selected source IDs required')
    graph, states = {}, {}
    for row in nodes:
        if type(row) is not dict or set(row) != {'id', 'role', 'sha256', 'parents', 'path', 'status'}:
            raise ValueError('exact source-lineage node required')
        ident = row['id']
        if type(ident) is not str or not ident or ident in graph:
            raise ValueError('unique lineage identity required')
        if type(row['role']) is not str or type(row['status']) is not str or not row['status']:
            raise ValueError('explicit source role/status required')
        digest = row['sha256']
        if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('exact lowercase source hash required')
        parents = row['parents']
        if type(parents) is not list or any(type(v) is not str for v in parents) or len(set(parents)) != len(parents):
            raise ValueError('unique explicit lineage parents required')
        if parents:
            if row['path'] is not None:
                raise ValueError('derived node must declare its parents, not impersonate a source leaf')
        else:
            expected = trusted_leaves.get(row['path']) if type(row['path']) is str else None
            if (type(expected) is not dict or expected != {
                    'sha256': digest, 'role': row['role'], 'status': row['status']}):
                raise ValueError('UNKNOWN: source leaf is not independently bound')
            source(row['path'], digest)
        graph[ident] = row
    if any(ident not in graph for ident in selected) or any(
            parent not in graph for row in nodes for parent in row['parents']):
        raise ValueError('UNKNOWN: missing lineage node')

    def visit(ident, active):
        if ident in active or len(active) >= 256:
            raise ValueError('cyclic or overdeep source graph')
        if ident in states:
            return states[ident]
        row = graph[ident]
        bad = (row['sha256'] in REJECTED_HASHES or row['role'] in REJECTED_ROLES
               or row['status'] in REJECTED_ROLES)
        unknown = row['role'] not in allowed_roles or row['status'] in UNRESOLVED
        ancestors = {ident}
        for parent in row['parents']:
            earlier, forbidden, uncertain = visit(parent, active | {ident})
            ancestors |= earlier; bad |= forbidden; unknown |= uncertain
        states[ident] = ancestors, bad, unknown
        return states[ident]

    for ident in graph:
        visit(ident, set())
    ancestry = set()
    for ident in selected:
        ancestors, bad, unknown = states[ident]
        if bad:
            raise ValueError('REJECTED_CONTROL_DO_NOT_SEED: prohibited source ancestry')
        if unknown:
            raise ValueError('UNKNOWN: source role is not admitted for this stage')
        ancestry |= ancestors
    return {'status': 'NO_REJECTED_ANCESTRY_IN_DECLARED_GRAPH', 'nodes': sorted(ancestry),
            'sha256': p.sha({'nodes': nodes, 'selected': selected, 'allowed_roles': sorted(allowed_roles)}),
            'source_status': {ident: graph[ident]['status'] for ident in sorted(ancestry)}}
