"""Write the records-check overlay manifest for one fold run (v25; R2 decisions 3-5).

    python -B mk_manifest.py B_LAYOUT A_OBS B_OBS OUT_JSON

The fold's own MANIFEST-h.json in B_LAYOUT is never edited. The overlay names it and pins its sha256; records.py loads
both. Everything the overlay declares is a literal in this file (bookings, external ID patterns, records rules, replay
sites, the token rule); this script only checks the literals against the two records and refuses when they do not fit:

  bookings  every declared path is an int >= 0 in both records, and every int under projection_resource_policy is
            declared;
  external  every 64-hex leaf of both records matches exactly one declared pattern, and every pattern is used in both;
  self_ids  [] (no record leaf is the digest of its own record: every hex leaf is a journalled ID, checked here);
  rules     every declared rule site occurs in A's journal.

Rules are written in A's site space (bare helper module names); records.py qualifies them for B. Roots come from the
arguments only.
"""
import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

HEX = re.compile(r'^(sha256:)?([0-9a-f]{64})$')
SCHEMA = 'rm.fold.records-overlay.r1'
SOURCES = ('caller_snapshot', 'private_sources')
POLICY = 'projection_resource_policy'

TRANSPORT = 'atlas_tectonics.integration_spatial_transport:PreparedSpatialTransport.__init__.<locals>.<lambda>'
REGIONAL = 'atlas_tectonics.regional_execution:_hash'
ISSUER = 'private_heat_issuer_resources_r1:stream_hash'
FINISH = 'record_tables:_Builder.finish_record'
ISSUE = 'private_heat_finish_issue_owned_r4:_issue'
SNAPSHOT = 'atlas_tectonics.regional_execution:RegionalMechanicalSnapshot.__init__'
CONSUMER_CELLS = [['metadata', 'cell_ids'], ['cell_ids']]
PER_CELL_EXACT = ['exact_cell_storage_residual_j', 'exact_corrected_enthalpy_j', 'exact_retained_solver_residual_j',
                  'exact_stock_projection_residual_j']

# ---------------------------------------------------------------- bookings (decision 5/6: compared exactly, A == B)
_N = [POLICY, 'numerical']
_O = [POLICY, 'output_components']
BOOKINGS = (
    [dict(path=_N + ['actual_retained_rational_bytes'], kind='bytes'),
     dict(path=_N + ['released_last_use_scratch_bytes'], kind='bytes'),
     dict(path=_N + ['retained_reserved_bytes'], kind='bytes'),
     dict(path=_N + ['equality_evidence', 'required_part_bits'], kind='bits'),
     dict(path=_N + ['equality_evidence', 'unused_cross_product_bits'], kind='bits'),
     dict(path=_N + ['scalar_peak_bits'], kind='bits'),
     dict(path=_N + ['operations'], kind='count'),
     dict(path=_N + ['scalar_slots'], kind='count'),
     dict(path=_O + ['actual_output_conversion_work'], kind='count'),
     dict(path=_O + ['output_hex_strings_and_pairs'], kind='count'),
     dict(path=_O + ['output_stream_codec'], kind='count')]
    + [dict(path=_N + ['equality_evidence', 'part_bits', k], kind='bits') for k in range(4)])
for _b in BOOKINGS:
    _b['rule'] = 'equal'

# ---------------------------------------------------------------- external IDs ('*' = any list index or dict key)
_SIG = ['funding_id', 'graph_id', 'native_source_inventory_id', 'owner_definition_id', 'owner_id', 'parent_state_id',
        'source_inventory_id', 'source_stage_id', 'state_id', 'thermal_mesh_id', 'transport_id']
EXTERNAL = (
    [['call_id'], ['geometry_id'], ['plan_id'], ['private_result_id'], ['state_id'], ['loaded_dependencies', 'identity'],
     ['cell_ids', '*'], ['face_ids', '*'],
     ['caller_snapshot', 'cell_ids', '*'], ['caller_snapshot', 'execution', 'execution_identity'],
     ['caller_snapshot', 'geometry_id'], ['caller_snapshot', 'graph_id'],
     ['caller_snapshot', 'loaded_dependencies', 'identity'], ['caller_snapshot', 'owner_definition_id'],
     ['caller_snapshot', 'owner_id'], ['caller_snapshot', 'plan_id'], ['caller_snapshot', 'private_sources', '*'],
     ['caller_snapshot', 'source_stage_id'], ['caller_snapshot', 'state_id'], ['caller_snapshot', 'thermal_mesh_id']]
    + [['caller_snapshot', 'native_origin_signature', k] for k in _SIG])

# ---------------------------------------------------------------- records rules (decisions 3-5), A site space
SORT = [
    # site, path, key: the list is kept in ID order (a field of each item, or the hex items themselves when null)
    ('atlas_tectonics.integration_exterior_mesh:ExteriorMesh.geometry_id', ['cells'], 'cell_id'),
    ('atlas_tectonics.integration_exterior_mesh:ExteriorMesh.geometry_id', ['faces'], 'face_id'),
    ('atlas_tectonics.integration_regional_evolution:_hash', ['reservation', 'patch_ids'], None),
    ('atlas_tectonics.integration_regional_evolution:_hash', ['metadata', 'reservation', 'patch_ids'], None),
    (TRANSPORT, ['cells'], 'cell_id'),
    (TRANSPORT, ['inactive_zero_measure_cells'], 'cell_id'),
    (TRANSPORT, ['original_face_intervals'], 'face_id'),
    (TRANSPORT, ['selected_face_representatives'], 'face_id'),
    (TRANSPORT, ['transfers'], 'face_id'),
    (REGIONAL, ['metadata', 'cell_ids'], None),
    (REGIONAL, ['metadata', 'caller_snapshot', 'cell_ids'], None),
    (REGIONAL, ['metadata', 'face_ids'], None),
    (REGIONAL, ['metadata', 'cells'], 'cell_id'),
    (REGIONAL, ['metadata', 'thermal_mesh', 'cells'], 'cell_id'),
    (REGIONAL, ['metadata', 'thermal_mesh', 'faces'], 'face_id'),
    ('live_spatial_patch:record_access', ['cells'], 'cell_id'),
    ('live_spatial_patch:record_access', ['face_intervals'], 'face_id'),
    ('mesh_tables:pack_mesh', ['cells'], 'cell_id'),
    ('mesh_tables:pack_mesh', ['faces'], 'face_id'),
    (ISSUE, ['face_ids'], None),
    (ISSUER, ['metadata', 'cell_ids'], None),
    (ISSUER, ['metadata', 'face_ids'], None),
    (FINISH, ['cell_ids'], None),
    (FINISH, ['caller_snapshot', 'cell_ids'], None),
    (FINISH, ['face_ids'], None),
]
ITEMS = [
    # per-item lists that follow a sort list of the same entry
    (REGIONAL, ['metadata', 'cell_ids'], [['metadata', g, '*'] for g in (
        'binary_stock_projection_accounts', 'exact_input_stocks', 'exact_projection_accounts', 'exact_stocks')]
     + [['metadata', k] for k in PER_CELL_EXACT]),
    (REGIONAL, ['metadata', 'face_ids'], [['metadata', 'exact_paired_face_energy_j']]),
    (ISSUER, ['metadata', 'cell_ids'], [['arrays', '*']] + [['metadata', k] for k in PER_CELL_EXACT]),
    (ISSUER, ['metadata', 'face_ids'], [['metadata', 'exact_paired_face_energy_j']]),
    (FINISH, ['cell_ids'], [[k] for k in PER_CELL_EXACT]),
    (FINISH, ['face_ids'], [['exact_paired_face_energy_j']]),
]


def build_rules():
    rules = []
    for site, path, key in SORT:
        rules.append(dict(rule='sort', site=site, path=path, key=key))
    for site, by, paths in ITEMS:
        rules += [dict(rule='items', site=site, path=p, by=by) for p in paths]
    rules += [dict(rule='items', site=ISSUE, path=[k], by='consumers', consumer_paths=CONSUMER_CELLS) for k in (
        'capacity', 'corrected_energy_exact', 'enthalpy_j', 'exact_cell_residual', 'old_energy',
        'public_cell_residual', 'source_energy', 'stock_projection_residual', 'temperature_k')]
    rules.append(dict(rule='face_rows', site=ISSUE, path=['physical_faces'], cells='consumers',
                      consumer_paths=CONSUMER_CELLS, rows_by=['face_ids'],
                      why='[cell, neighbour or null, [num, den]] rows; a pair is stored lower cell index first, so a '
                          'renumbering that swaps the pair negates the oriented value'))
    rules.append(dict(rule='ordered_by', site=REGIONAL, path=['metadata', 'exact_face_transfers', '*'],
                      ref_site=TRANSPORT, ref_path=['transfers'], ref_key='face_id',
                      why='per-transfer values in the referenced transport\'s transfers order'))
    rules.append(dict(rule='cell_words', site=SNAPSHOT, width=8, consumer_paths=[['metadata', 'cell_ids']],
                      why='per-cell float64 words in the order of the consuming snapshot record\'s cell_ids'))
    for i, r in enumerate(rules):
        r['id'] = '%s-%02d' % (r['rule'], i)
    return rules


REPLAY: list[dict[str, Any]] = [
    dict(kind='mesh', module='mesh_tables', quals=['pack_mesh', 'pack_mesh.<locals>.support'],
         input_site='mesh_tables:pack_mesh', roles=True,
         why='pack_mesh re-encodes the translated mesh into binary arrays; their digests are tied by running the '
             'folded producer on A\'s input and on B\'s, and paired by array name'),
    dict(kind='record', module='record_tables',
         quals=['_Builder._token_raw', '_Builder._integer_row', '_Builder.finish_record', '_Builder._metadata'],
         input_site='record_tables:_Builder.finish_record', roles=False,
         internal=['_Builder._metadata'],
         why='RecordCodec.pack_record re-encodes the translated record into columns; the column digests are tied by '
             'running the folded producer on both inputs; none is consumed outside the record. _Builder._metadata '
             'hashes the column metadata with A\'s token hashes in it, so those entries stay unmapped; the producer '
             'consumes them and nothing outside it does'),
]
TOKEN = dict(site='record_tables:_Builder._token_raw', module_file='atlas_tectonics/_private/record_tables.py',
             name='EXACT_KEY_BYTES',
             why='_Builder._token_raw hashes a token only when its encoding is longer than EXACT_KEY_BYTES. A\'s tokens '
                 'here are absolute helper paths (longer than the bound), so A journals their hash; the folded tokens '
                 'are package keys within the bound, which B keys exactly and never hashes. The token bytes reach '
                 'the record columns either way, and the replay ties every column.')
IDENTITY = dict(key='atlas_tectonics/_identity.py', f4_schema='atlas.kernel-execution.v4')
B_WHY = ('parallel_r1._files() hashes every loaded module _ours() accepts: names in _INDEXED_RUNTIME_HELPERS, '
         'private_heat_*, or atlas_tectonics.*. A loads this helper by its bare name, which is in neither list, so A '
         'leaves it out; the fold loads it as atlas_tectonics._private.*, so B hashes it. B\'s worker file table is '
         'the stricter by this file; nothing journalled consumes the digest.')
B_ONLY = [dict(site='private_heat_functionals_parallel_r1:_digest', key='atlas_tectonics/_private/' + name, why=B_WHY)
          for name in ('compact_restart_patch.py', 'publish_mesh_patch.py')]


def leaves(v, path=()):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from leaves(x, path + (k,))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from leaves(x, path + (i,))
    else:
        yield path, v


def matches(pattern, path):
    return len(pattern) == len(path) and all(p == '*' or p == q for p, q in zip(pattern, path, strict=True))


def get(v, path):
    for k in path:
        if isinstance(v, dict) and k in v:
            v = v[k]
        elif isinstance(v, list) and type(k) is int and 0 <= k < len(v):
            v = v[k]
        else:
            return None
    return v


def check_record(name, rec, problems):
    used = [0] * len(EXTERNAL)
    for path, v in leaves(rec):
        if isinstance(v, str) and HEX.match(v):
            hits = [i for i, p in enumerate(EXTERNAL) if matches(p, path)]
            if len(hits) != 1:
                problems.append('%s: hex leaf %r matches %d patterns' % (name, list(path)[:6], len(hits)))
            for i in hits:
                used[i] += 1
        if type(v) is int and path[:1] == (POLICY,):
            if not any(list(path) == b['path'] for b in BOOKINGS):
                problems.append('%s: undeclared booking %r' % (name, list(path)))
    problems += ['%s: external pattern unused %r' % (name, EXTERNAL[i]) for i, n in enumerate(used) if not n]
    for b in BOOKINGS:
        x = get(rec, b['path'])
        if type(x) is not int or x < 0:
            problems.append('%s: booking %r is %r' % (name, b['path'], x))
    if not isinstance(get(rec, list(SOURCES)), dict):
        problems.append('%s: no %s' % (name, '.'.join(SOURCES)))
    return used


def main(b_layout, a_obs, b_obs, out):
    base = b_layout/'MANIFEST-h.json'
    base_raw = base.read_bytes()
    problems = []
    used = {}
    for name, obs in (('A', a_obs), ('B', b_obs)):
        used[name] = check_record(name, json.loads((obs/'metadata.json').read_bytes()), problems)
    a_sites = set()
    for e in json.loads((a_obs/'journal.json').read_bytes())['entries']:
        a_sites.update(e[4])
    rules = build_rules()
    for r in rules:
        for s in [r['site']] + ([r['ref_site']] if 'ref_site' in r else []):
            if s not in a_sites:
                problems.append('rule %s: site %s not in A journal' % (r['id'], s))
    for r in REPLAY:
        for q in r['quals']:
            if r['module'] + ':' + q not in a_sites:
                problems.append('replay %s: site %s:%s not in A journal' % (r['kind'], r['module'], q))
        if not set(r.get('internal', [])) <= set(r['quals']):
            problems.append('replay %s: internal qual outside its quals' % r['kind'])
    if TOKEN['site'] not in a_sites:
        problems.append('token site not in A journal')
    parent = Path(json.loads((b_layout/'arm.json').read_bytes())['package_parent'])
    for b in B_ONLY:
        if b['site'] not in a_sites or not (parent/b['key']).is_file():
            problems.append('b_only %s: site not in A journal or no folded file' % b['key'])
    if problems:
        print(json.dumps(dict(status='FAIL', problems=problems[:40])))
        return 1
    overlay = dict(
        schema=SCHEMA, base_manifest=base.name, base_sha256=sha256(base_raw).hexdigest(),
        bookings=BOOKINGS, self_ids=[],
        self_ids_note='no record leaf is its own record digest: every 64-hex leaf of both records is a journalled ID',
        external=[dict(path=p, preimage='journal') for p in EXTERNAL],
        private_sources_path=list(SOURCES), identity=IDENTITY, b_only=B_ONLY,
        records_rules=dict(rules=rules, replay=REPLAY, token=TOKEN, max_rounds=50))
    out.write_text(json.dumps(overlay, indent=1, sort_keys=True) + '\n', encoding='utf8', newline='\n')
    print(json.dumps(dict(status='PASS', out=out.name, sha256=sha256(out.read_bytes()).hexdigest(),
                          bookings=len(BOOKINGS), external=len(EXTERNAL), rules=len(rules), replay=len(REPLAY),
                          leaves_a=sum(used['A']), leaves_b=sum(used['B']))))
    return 0


if __name__ == '__main__':
    sys.exit(main(*map(Path, sys.argv[1:5])))
