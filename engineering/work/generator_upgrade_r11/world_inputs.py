"""Bounded owner-declared frames and transitive political source-use firewall.

Pure functions accept the root's verified geography package. They neither read
large arrays nor adopt a new world, datum, political generation or canon.
"""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
import math
import re

PHYSICAL_SHA = 'ef68eab6691b02d4ab5283fd32c1d260b7b974fe7acecab3c841787a88c53659'
POLITICAL_SHA = 'a315571de86e604ebce30cca78305a1c1021348a3d3c2f917b7f9e584d022871'
INDEX_SHA = 'd6fcb2735606c126deaffbc45ca5655f68f97ae10eb5dcd74a062f0e816d4389'
AUTHORITY_ID = '3608e686-b659-4234-a4f4-f15df8c110dc'
TERRAIN_ROOT = 'ddda02e987371329f6ea99cad792f9b59744e7b276954f158a16a38007dcb25b'
Z_REFERENCE = 'D31_STILLKLINGE_G0_RETAINED_Z'
COMPOSITE = 'PHYS-R11-RETAINED-COMPOSITE-G0'
C1C = 'C1C_NATIVE_1KM'
HISTORY_A = 'HISTORY_A_NATIVE_NODES'
C1R_AUTHORITY = 'PHYS-R11-C1R-A0-AUTHORITY'
C1R_SOLVER = 'PHYS-R11-C1R-A0-SOLVER'

# Exact source hashes from the Political owner's separately read evidence.
# Matching content remains legacy when renamed or presented under another role.
LEGACY_HASHES = frozenset({
    '075930ef63a3ce2f3c8c6d14674b1dace1f8653ff213c82cd472fe9afe4898ba',
    '180267c6fa902ca8b4dd6516494dd181b1406cd917b76577a5f83a4cbf37e2af',
    'fce774e18ae4ceb6a065c9425b1612dc79bd16b8af260e02f82db474cf1c13e8',
    '6a993b8d6670c1ab044854f94dbaa169daefbb7b6870b63655dd75c264637731',
    '1986ff3bba8d87ab1c89eb1491fca7b941c8ef4eae8a6e2e1d07d4647c34d808',
    'cb6600aa64d321e6240900e0622407b99a9bb81914f75de75cd44579e4958cb9',
    '4eeaf719affb1b8ecb6a9a6a7b3c2f1c00690aaeba9a446310c7db34a406c497',
})
# These pins establish owner-declared nonpolitical source families, not actual
# payload verification or cross-frame compatibility. Unknown leaves fail closed.
PHYSICAL_HASHES = frozenset({
    '4455a544011dddb13b1666a9fd4a51135593b7d2eab2949a591c0816893d12ab',
    '62e338648b347df59dfce5867115af1d08372d980675d0e608a8345ff7bb0587',
    '48dbe15ca9a9aa1ede603aba1c6a77f4f81d71bcc1b72eedadcae716f76274f7',
    '45ca6ee2873a4bce15d841044e31c354dcad518098d6c4a8616834b7832ed1aa',
    '30438078b25aa6c5e7fd10af6f28145de9b61e84a0ea4a9e6c76a6add06ae483',
    '7f8f083ebdc6159d372cf9414e82b3c834ea7a7aa7a143dca94beac2b6139932',
    '6478aa45c06dd025e29aa77ff3a844795acbf47a69681f9f1bac5c2402ecb7d9',
})
LEGACY_ROLES = frozenset({'LEGACY_STAGE6C_V11', 'PRIOR_POLITICAL_CANDIDATE',
    'GUARDED_DIAGONAL_PILOT', 'INHERITED_STAGE3_POLITICAL_MASK',
    'INHERITED_STAGE4_HOST_JURISDICTION', 'INHERITED_STAGE5B_POLITICAL_FILTER',
    'POLITICAL_ANCHOR', 'POLITICAL_LABEL', 'REJECTED_CONTROL_DO_NOT_SEED'})
ROLE_ALLOWLIST = LEGACY_ROLES | {'OWNER_NEUTRAL_PHYSICAL', 'OWNER_NEUTRAL_DERIVED',
    'SPECIES_IDENTITY', 'RESOURCE_OWNERSHIP', 'POLITICAL_TARGET_COUNT_AREA', 'UNKNOWN'}
LEGACY_USES = frozenset({'LEGACY_JOIN', 'LEGACY_REGRESSION', 'LEGACY_CONDITIONAL_ASSESSMENT', 'PROVENANCE'})
NEW_WORLD_USES = frozenset({'NEW_WORLD_PARENT', 'NEW_WORLD_SEED', 'NEW_WORLD_LABEL',
    'NEW_WORLD_TRAINING', 'NEW_WORLD_TRACING', 'NEW_WORLD_IMITATION', 'DISTRICT_FORMATION'})


class SourceUseError(ValueError):
    def __init__(self, status, message, lineage=None):
        super().__init__(message)
        self.status = status
        self.lineage = list(lineage or [])


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 8192:
        raise ValueError(name + ': bounded nonempty text required')
    return value


def _sha(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('invalid SHA256')
    return value


def _number(value):
    if type(value) not in (str, int, float) or (type(value) is str and len(value) > 256):
        raise ValueError('finite rational coordinate required')
    try:
        result = F(value)
    except (ValueError, OverflowError, ZeroDivisionError):
        raise ValueError('finite rational coordinate required') from None
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > 8192:
        raise ValueError('numeric range too large')
    return result


def _strict(value):
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for v in value:
            _strict(v)
        return
    if type(value) is dict and all(type(k) is str for k in value):
        for v in value.values():
            _strict(v)
        return
    raise ValueError('strict JSON required')


def _digest(value):
    _strict(value)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _package(package):
    _strict(package)
    pins = {p.replace('\\', '/'): _sha(h) for p, h in package['source_bindings'].items()}
    if not {PHYSICAL_SHA, POLITICAL_SHA, INDEX_SHA} <= set(pins.values()):
        raise ValueError('exact Physical/Political owner delta decisions not bound')
    delta = package['owner_deltas']
    if delta['schema'] != 'diadem.geo.r11-owner-deltas.v1' or delta['revision'] != 1:
        raise ValueError('owner delta identity differs')
    if delta['accepted_compatible_world_snapshot'] is not None:
        raise ValueError('this adapter does not adopt a new world snapshot')
    if not delta['requested_physical_and_political_returns_integrated']:
        raise ValueError('owner returns not integrated')
    actual_returns = {r['sha256'] for r in delta['source_returns']}
    if not {PHYSICAL_SHA, POLITICAL_SHA} <= actual_returns:
        raise ValueError('source decisions differ')
    for r in delta['source_returns']:
        if pins.get(r['path'].replace('\\', '/')) != r['sha256']:
            raise ValueError('decision path/hash binding differs')
    effective = package['effective_interpretation']
    if effective['physical']['selected_branch'] != COMPOSITE:
        raise ValueError('retained composite branch differs')
    if effective['physical']['original_reference_columns_automatically_rebound'] is not False:
        raise ValueError('old reference columns must not be silently rebound')
    if effective['political']['new_world_legacy_source_policy'] != 'REJECTED_CONTROL_DO_NOT_SEED':
        raise ValueError('political source-use firewall changed')
    return pins


def _decision_ref(package, sha):
    return {'path': next(p for p, h in package['source_bindings'].items() if h == sha),
        'sha256': sha, 'status': 'WORKING NON-CANON owner interpretation; UNKNOWN/INCOMPLETE retained'}


def declared_frames(package):
    """The owner-declared numerical frames; no array reads or joined-world claim."""
    _package(package)
    frames = {
        COMPOSITE: {'shape': [18600, 22000], 'corner_km': ['0', '0'], 'spacing_km': '1/10',
            'x_direction': 'EAST', 'y_direction': 'SOUTH', 'row_y_sign': 1, 'sampling': 'CELL_CENTRE',
            'source_status': 'ACTIVE_EDITABLE_WORKING_AUTHORITY', 'scope': 'Retained present-map numerical parent'},
        C1C: {'shape': [1650, 1950], 'corner_km': ['0', '1650'], 'spacing_km': '1',
            'x_direction': 'EAST', 'y_direction': 'NORTH', 'row_y_sign': -1, 'sampling': 'CELL_CENTRE',
            'source_status': 'ACCEPTED_REDUCED_CONSTRAINT_ATLAS', 'scope': 'Native 2-D/2.5-D non-kinematic constraints, not final outcrop'},
        HISTORY_A: {'shape': [1651, 1951], 'corner_km': ['0', '0'], 'spacing_km': '1',
            'x_direction': 'EAST', 'y_direction': 'SOUTH', 'row_y_sign': 1, 'sampling': 'NODE',
            'source_status': 'FIXED_SNAPSHOT_NO_EVOLUTION', 'scope': 'Structural blocks are not established plates; motion UNKNOWN'},
        C1R_AUTHORITY: {'shape': [665, 710], 'corner_km': ['-320', '-480'], 'spacing_km': '4',
            'x_direction': 'EAST', 'y_direction': 'SOUTH', 'row_y_sign': 1, 'sampling': 'PER_FIELD_REQUIRED',
            'source_status': 'WORKING NON-CANON', 'scope': 'A0 prior scenario; PENDING_INDEPENDENT_1R_ATLAS_AUDIT'},
        C1R_SOLVER: {'shape': [761, 806], 'corner_km': ['-512', '-672'], 'spacing_km': '4',
            'x_direction': 'EAST', 'y_direction': 'SOUTH', 'row_y_sign': 1, 'sampling': 'PER_FIELD_REQUIRED',
            'source_status': 'WORKING NON-CANON', 'scope': 'A0 solver prior with192 km padding; not C1R7'},
    }
    return {'schema': 'diadem.r11.owner-declared-world-frames.v1', 'status': 'WORKING NON-CANON',
        'world': 'Diadem', 'selected_terrain_branch': COMPOSITE, 'frames': frames,
        'terrain_identity': {'authority_id': AUTHORITY_ID, 'generation': 0, 'merkle_root': TERRAIN_ROOT},
        'composition': {'base': 'D3.1', 'replacement': 'APPROVED_AUTHORITATIVE_STILLKLINGE_REPLACEMENT',
            'rows_half_open': [2200, 6100], 'columns_half_open': [9100, 10650], 'resampling': False},
        'vertical': {'unit': 'm', 'positive': 'UP', 'reference_token': Z_REFERENCE,
            'offset_applied_m': '0', 'precise_datum_realisation': None, 'world_ocean_tie': None,
            'water_family_offsets': None},
        'raw_metadata': {'crs': None, 'band_units': None, 'nodata': None, 'zarr_fill_value': 0},
        'c1r_scenario': {'id': 'PHYS-R11-C1R-A0-PRIOR-SCENARIO', 'history': 'A0', 'source_master': 'A2',
            'scale_only_control': False, 'public_crop_in_authority': {'row': 120, 'column': 80, 'height': 465, 'width': 550},
            'public_extent_km': ['0', '2200', '0', '1860'], 'categorical': 'REVIEW_ONLY', 'three_dimensional': 'DEFERRED'},
        'accepted_cross_frame_join': None, 'world_date': None, 'geological_age': None, 'plate_motion_epoch': None,
        'geodetic_crs': None, 'boundary_conditions': None,
        'source_ref': _decision_ref(package, PHYSICAL_SHA),
        'limits': ['Computational edges are not physical boundaries or outlets.',
            'Raw fill zero does not establish valid terrain coverage.',
            '100 m sampling is not survey accuracy or observed10 m detail.',
            'Same numerical extent does not establish accepted geology/terrain compatibility.']}


def coordinates(package, frame_id, row, column, *, unit='m', field_sampling=None):
    """Exact native cell/node coordinates, with independently bound C1R sampling."""
    frames = declared_frames(package)['frames']
    if frame_id not in frames:
        raise ValueError('unknown or unselected frame')
    frame = frames[frame_id]
    if type(row) is not int or type(column) is not int or not (0 <= row < frame['shape'][0] and 0 <= column < frame['shape'][1]):
        raise ValueError('native index outside support')
    if unit not in ('m', 'km'):
        raise ValueError('explicit m or km coordinate unit required')
    sampling = frame['sampling']
    if sampling == 'PER_FIELD_REQUIRED':
        if field_sampling is None:
            return {'status': 'UNKNOWN', 'x': None, 'y': None, 'reason': 'C1R field sampling/payload binding required.'}
        if set(field_sampling) != {'field_id', 'sampling', 'source_path', 'source_sha256', 'shape', 'evidence'}:
            raise ValueError('explicit bound field sampling required')
        pins = _package(package)
        if pins.get(field_sampling['source_path'].replace('\\', '/')) != field_sampling['source_sha256']:
            raise ValueError('C1R field metadata/payload not bound')
        if field_sampling not in package.get('field_sampling_records', []):
            raise ValueError('field sampling is not an exact verified package record')
        _text(field_sampling['field_id'], 'field ID')
        _text(field_sampling['evidence'], 'field sampling evidence')
        sampling = field_sampling['sampling']
        if sampling not in ('CELL_CENTRE', 'NODE') or field_sampling['shape'] != frame['shape']:
            raise ValueError('field sampling/shape differs from declared native support')
    elif field_sampling is not None:
        raise ValueError('fixed owner sampling may not be overridden')
    offset = F(1, 2) if sampling == 'CELL_CENTRE' else F(0)
    scale = 1000 if unit == 'm' else 1
    dx = F(frame['spacing_km'])
    x = (F(frame['corner_km'][0]) + (column + offset) * dx) * scale
    y = (F(frame['corner_km'][1]) + frame['row_y_sign'] * (row + offset) * dx) * scale
    return {'status': 'DECLARED_NATIVE_COORDINATES', 'frame_id': frame_id, 'row': row, 'column': column,
        'x': str(x), 'y': str(y), 'unit': unit, 'sampling': sampling,
        'field_sampling': deepcopy(field_sampling), 'accepted_world_join': False}


def _point_bounds(frame, x, y):
    step = F(frame['spacing_km'])
    # Node grids contain N-1 intervals; cell grids contain N full cells.
    subtract = 1 if frame['sampling'] == 'NODE' else 0
    x0, y0 = map(F, frame['corner_km'])
    x1 = x0 + (frame['shape'][1] - subtract) * step
    y1 = y0 + frame['row_y_sign'] * (frame['shape'][0] - subtract) * step
    return x0 <= x <= x1 and min(y0, y1) <= y <= max(y0, y1)


def transform_point(package, source_frame, target_frame, x_km, y_km, *, transform=None):
    """Point transform only; never resample arrays or infer node/cell equivalence."""
    frames = declared_frames(package)['frames']
    if source_frame not in frames or target_frame not in frames:
        raise ValueError('unknown frame')
    x, y = _number(x_km), _number(y_km)
    if not _point_bounds(frames[source_frame], x, y):
        raise ValueError('source point outside evidenced support')
    if source_frame == target_frame:
        if transform is not None:
            raise ValueError('same-frame coordinates require no new transform')
        tx, ty, mode = x, y, 'SAME_NATIVE_FRAME'
    elif {source_frame, target_frame} == {C1C, HISTORY_A}:
        if transform is not None:
            raise ValueError('owner-bound reflection cannot be overridden')
        tx, ty, mode = x, 1650 - y, 'OWNER_BOUND_POINT_REFLECTION_NOT_SAMPLING_EQUIVALENCE'
    else:
        if transform is None:
            return {'status': 'UNKNOWN', 'x_km': None, 'y_km': None,
                'reason': 'No accepted/bound cross-frame transform; origin/extent similarity is insufficient.'}
        expected = {'source_frame', 'target_frame', 'matrix_km', 'source_path', 'source_sha256', 'evidence', 'status'}
        if set(transform) != expected or transform['source_frame'] != source_frame or transform['target_frame'] != target_frame:
            raise ValueError('transform frame binding differs')
        if _package(package).get(transform['source_path'].replace('\\', '/')) != transform['source_sha256']:
            raise ValueError('transform decision not source-bound')
        if transform not in package.get('coordinate_transforms', []):
            raise ValueError('transform is not an exact verified package record')
        if transform['status'] != 'WORKING NON-CANON':
            raise ValueError('no accepted world transform selected by owner return')
        _text(transform['evidence'], 'explicit transform interpretation')
        mat = transform['matrix_km']
        if type(mat) is not list or len(mat) != 2 or any(type(r) is not list or len(r) != 3 for r in mat):
            raise ValueError('two by three affine matrix required')
        a, c = [[_number(v) for v in r] for r in mat]
        if a[0] * c[1] - a[1] * c[0] == 0:
            raise ValueError('degenerate coordinate transform')
        tx, ty = a[0]*x + a[1]*y + a[2], c[0]*x + c[1]*y + c[2]
        mode = 'EXPLICIT_WORKING_POINT_TRANSFORM_NOT_ACCEPTED_JOIN'
    if not _point_bounds(frames[target_frame], tx, ty):
        raise ValueError('transform leaves evidenced target support; no extrapolation')
    return {'status': mode, 'source_frame': source_frame, 'target_frame': target_frame,
        'x_km': str(tx), 'y_km': str(ty), 'sampling_equivalent': source_frame == target_frame,
        'accepted_world_join': False, 'transform': deepcopy(transform)}


def elevation(package, value, *, coverage, authority_id, generation, merkle_root):
    """Retained z is metres, unchanged. Coverage is independent of storage fill."""
    declared_frames(package)
    if authority_id != AUTHORITY_ID or type(generation) is not int or generation != 0 or merkle_root != TERRAIN_ROOT:
        raise ValueError('terrain authority changed: compatible rebind required')
    if coverage not in ('PRESENT_VERIFIED', 'MISSING_SHARD', 'OUTSIDE_SUPPORT', 'UNKNOWN'):
        raise ValueError('explicit coverage state required')
    raw = None if value is None else str(_number(value))
    known = coverage == 'PRESENT_VERIFIED' and value is not None
    return {'status': 'KNOWN_RETAINED_SAMPLE' if known else 'UNKNOWN',
        'z_m': raw if known else None, 'raw_storage_value': raw, 'coverage': coverage,
        'reference_token': Z_REFERENCE, 'unit': 'm', 'positive': 'UP',
        'authority_id': authority_id, 'generation': generation, 'merkle_root': merkle_root,
        'precise_datum_realisation': None, 'water_family_offset_m': None}


def relative_height(a, b):
    """Same-parent differences only; not an implicit Water-family datum join."""
    for key in ('authority_id', 'generation', 'merkle_root', 'reference_token', 'unit', 'positive'):
        if a[key] != b[key]:
            raise ValueError('height families differ; explicit compatible vertical reference required')
    if a['reference_token'] != Z_REFERENCE or a['unit'] != 'm' or a['positive'] != 'UP':
        raise ValueError('unrecognised elevation interpretation')
    if a['authority_id'] != AUTHORITY_ID or type(a['generation']) is not int or a['generation'] != 0 or a['merkle_root'] != TERRAIN_ROOT:
        raise ValueError('unbound retained terrain identity')
    if a['status'] != 'KNOWN_RETAINED_SAMPLE' or b['status'] != 'KNOWN_RETAINED_SAMPLE':
        return {'status': 'UNKNOWN', 'difference_m': None}
    if a['coverage'] != 'PRESENT_VERIFIED' or b['coverage'] != 'PRESENT_VERIFIED':
        raise ValueError('known elevation cannot originate in missing coverage')
    return {'status': 'SAME_PARENT_RELATIVE_HEIGHT', 'difference_m': str(_number(a['z_m']) - _number(b['z_m'])),
        'reference_token': Z_REFERENCE}


def validate_source_use(package, nodes, requested_node_ids, *, purpose, legacy_label=None):
    """Enforce complete declared provenance DAG closure before any consumer runs.

    Rejected ancestry cannot be removed by extraction, aggregation, renaming,
    copying to a new hash or relabelling descendants as physical. Unknown source
    leaves remain UNKNOWN, not owner-neutral. This does not discover concealed
    undeclared reads: the workflow must supply its complete verified dependency DAG.
    """
    pins = _package(package)
    _strict(nodes)
    if purpose not in LEGACY_USES | NEW_WORLD_USES:
        raise ValueError('unrecognised source-use purpose')
    if type(nodes) is not list or not 1 <= len(nodes) <= 10000:
        raise ValueError('bounded source lineage required')
    if (type(requested_node_ids) is not list or not requested_node_ids or
            any(type(n) is not str or not n for n in requested_node_ids) or
            len(set(requested_node_ids)) != len(requested_node_ids)):
        raise ValueError('unique requested source node IDs required')
    graph = {}
    for n in nodes:
        keys = {'node_id', 'kind', 'sha256', 'source_path', 'role', 'parents', 'lineage_complete', 'evidence'}
        if set(n) != keys:
            raise ValueError('exact source-lineage schema required')
        nid = _text(n['node_id'], 'node ID')
        if nid in graph:
            raise ValueError('duplicate source-lineage node')
        _sha(n['sha256'])
        _text(n['evidence'], 'lineage evidence')
        if n['kind'] not in ('SOURCE', 'DERIVED') or n['role'] not in ROLE_ALLOWLIST:
            raise ValueError('unknown lineage kind/role')
        if type(n['parents']) is not list or any(type(v) is not str for v in n['parents']) or len(set(n['parents'])) != len(n['parents']):
            raise ValueError('unique parent IDs required')
        if n['lineage_complete'] is not True:
            raise SourceUseError('UNKNOWN', 'complete lineage not established', [nid])
        if n['kind'] == 'SOURCE':
            _text(n['source_path'], 'source path')
            if n['parents'] or pins.get(n['source_path'].replace('\\', '/')) != n['sha256']:
                raise SourceUseError('UNKNOWN', 'source leaf is not independently package-bound', [nid])
        elif n['source_path'] is not None or not n['parents']:
            raise ValueError('derived payload must name actual parents and not impersonate a source leaf')
        graph[nid] = n
    if any(nid not in graph for nid in requested_node_ids):
        raise ValueError('requested node missing from lineage')
    if any(p not in graph for n in nodes for p in n['parents']):
        raise SourceUseError('UNKNOWN', 'source lineage has missing parent')
    active, results = set(), {}
    def visit(nid):
        if nid in active:
            raise ValueError('source-lineage cycle')
        if nid in results:
            return results[nid]
        if len(active) >= 256:
            raise ValueError('source-lineage depth exceeds bounded256-node path')
        active.add(nid)
        n = graph[nid]
        ancestry, forbidden, uncertain = {nid}, set(), set()
        legacy = n['sha256'] in LEGACY_HASHES or n['role'] in LEGACY_ROLES
        if legacy:
            forbidden.add(nid)
        if n['role'] in ('SPECIES_IDENTITY', 'RESOURCE_OWNERSHIP', 'POLITICAL_TARGET_COUNT_AREA'):
            # These cannot force owner-neutral district formation either.
            forbidden.add(nid)
        if n['role'] == 'UNKNOWN':
            uncertain.add(nid)
        if n['kind'] == 'SOURCE' and not legacy and n['sha256'] not in PHYSICAL_HASHES:
            uncertain.add(nid)
        for parent in n['parents']:
            aa, ff, uu = visit(parent)
            ancestry |= aa; forbidden |= ff; uncertain |= uu
        active.remove(nid)
        results[nid] = ancestry, forbidden, uncertain
        return results[nid]
    # Check even unused declared nodes for cycles, not just a selected safe prefix.
    for nid in graph:
        visit(nid)
    selected, bad, unknown = set(), set(), set()
    for nid in requested_node_ids:
        aa, ff, uu = results[nid]
        selected |= aa; bad |= ff; unknown |= uu
    if purpose in NEW_WORLD_USES and bad:
        raise SourceUseError('REJECTED_CONTROL_DO_NOT_SEED',
            'Prior/inherited political or identity/ownership targets cannot feed a new-world consumer.', sorted(bad))
    if unknown:
        raise SourceUseError('UNKNOWN', 'Unclassified source ancestry cannot be assumed owner-neutral.', sorted(unknown))
    if purpose in LEGACY_USES:
        _text(legacy_label, 'explicit legacy snapshot/source-qualified label')
    elif legacy_label is not None:
        raise ValueError('legacy label cannot convert a new-world operation into regression')
    report = {'status': 'ALLOWED_LABELLED_LEGACY_USE' if purpose in LEGACY_USES else 'NO_REJECTED_ANCESTRY_IN_DECLARED_GRAPH',
        'purpose': purpose, 'requested_node_ids': list(requested_node_ids), 'lineage_node_ids': sorted(selected),
        'legacy_label': legacy_label, 'rejected_control_ancestry': sorted(bad),
        'source_ref': _decision_ref(package, POLITICAL_SHA),
        'political_generation_accepted': False, 'compatible_world_snapshot_accepted': False,
        'limits': 'Source-use permission only; not physical compatibility, payload correctness, production or political acceptance.'}
    report['lineage_sha256'] = _digest({'nodes': nodes, 'requested': requested_node_ids, 'purpose': purpose, 'legacy_label': legacy_label})
    return report
