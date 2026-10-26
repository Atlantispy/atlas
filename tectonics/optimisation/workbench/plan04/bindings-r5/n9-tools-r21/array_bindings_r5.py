"""Additive N9 r5 observation and array proof; no runtime/store imports or run authority.

Call only after the comparator's independent prove_stage/load_dump checks.
`C` is the calling comparator module (no imports of a particular predecessor).
Bindings prove bytes within an arm. Layouts separately establish cross-arm row
correspondence; equal payload hashes cannot supply that correspondence.
"""
from hashlib import sha256
from pathlib import Path

SCHEMA = 'atlas.private.iv1-arm-dump.r5-draft'
HEAD_KEYS = frozenset(('key', 'kind', 'sequence', 'root_metadata'))
AUDIT_KEYS = frozenset(('pinned_modules_checked', 'exempt', 'pinned_source_imports',
                        'data_only_exclusion', 'first_resolution', 'source_bytes_loader'))
INTERPRETER_KEYS = frozenset(('interpreter_seed', 'instrumentation_at_start', 'launch_environment'))
HOOK_KEYS = frozenset(('trace', 'profile', 'monitoring_tools', 'tracemalloc'))
LAUNCH_ENV_KEYS = frozenset(('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                             'PYTHONDONTWRITEBYTECODE', 'PYTHONHASHSEED'))
NETWORK_NAMES = ('vertex_ids', 'vertex_home', 'vertex_reference', 'view_vertex',
                 'view_plate', 'view_reference', 'faces', 'boundaries')
TRANSPORT_PREFIX = 'spatial-audit:spatial-transport:'
# Compact root routes (producer constants: compact_contracts, partition_v2, compact_store, mesh_tables,
# partition_workflow_patch.HEADER_KEYS, spatial_records_patch.STATE_NAMES on the selected base).
SEGMENT_REF_SCHEMA = 'atlas.segment-ref.v1'
PARTITION_DESCRIPTOR = 'atlas.differential-partition-descriptor.v1'
PARTITION_ROUTE = 'compact-partition-v2'
PARTITION_HEADER_KEYS = ('partition_id', 'scope', 'funding_id', 'collar_plan_id', 'grid_id',
                         'start_time_s', 'end_time_s', 'current_geometry_id', 'interval_id', 'parent_partition_id')
MESH_V3_SCHEMA = 'atlas.compact-mesh-store.v3'
MESH_RECORD_SCHEMA = 'atlas.source-bound-exterior-thermal-mesh.v1'
STATE_HEADER_NAMES = ('schema', 'state_id', 'owner_id', 'funding_id', 'time_s', 'intervals',
                      'parent_state_id', 'collar_state_id', 'support_id', 'trajectory_id',
                      'grid_id', 'thermal_mesh_id')
# Root-route condition (b): the closed decoder module set an r5 dump names (dump_arm_r5.DECODER_MODULES), with each
# module's workspace path. Each digest must be the arm's own pinned manifest source and its present bytes.
DECODER_PATHS = {name: 'helpers/%s.py' % name for name in (
    'compact_contracts', 'compact_restart_store', 'compact_store', 'content_cache', 'interval_catalog',
    'interval_store_set', 'mesh_tables', 'native_transfer', 'partition_native_patch', 'partition_store',
    'partition_tables', 'partition_v2', 'partition_workflow_patch', 'record_tables', 'record_views',
    'segment_store', 'spatial_indexed_patch', 'spatial_record_recipes', 'spatial_records_patch',
    'spatial_workflow_patch', 'support_source')}
DECODER_PATHS.update({'atlas_tectonics.'+name: 'src/atlas_tectonics/%s.py' % name for name in (
    'integration_spatial_transport', 'resources', 'storage')})


def validate_dump_evidence(C, dump, arm, proof, observer_pin):
    """Supplement load_dump with the r5 closed observation checks, without trusting a new hash.

    Legacy r3/r4 remains readable, but bind_all explicitly reports its absent r5
    observation coverage. This function returns no authority or acceptance flag.
    """
    if dump['schema'] != SCHEMA:
        return
    p = C.prove
    p(set(dump['head']) == HEAD_KEYS, 'r5 head fields are not closed')
    p(type(dump['pid']) is int and dump['pid'] > 0, 'r5 observer PID must be positive')
    for name in ('producer_receipt', 'reader_receipt'):
        p(dump['pid'] != proof['files'][name].get('pid'),
          'r5 observer shares the '+name+' process')
    observer = dump['observer']
    p(C.file_sha(observer['path']) == observer_pin, 'r5 observer source bytes differ from independent pin')
    audit = dump['loaded_audit']
    p(type(audit) is dict and set(audit) == AUDIT_KEYS,
      'r5 observer audit fields are not closed')
    p(all(type(audit[k]) is int and audit[k] >= 0
          for k in ('pinned_modules_checked', 'pinned_source_imports')),
      'r5 observer module counts are not nonnegative integers')
    interp = dump['interpreter']
    p(type(interp) is dict and set(interp) == INTERPRETER_KEYS,
      'r5 interpreter gate fields are not closed')
    hooks, launch = interp['instrumentation_at_start'], interp['launch_environment']
    p(type(hooks) is dict and set(hooks) == HOOK_KEYS and
      all(hooks[k] is False for k in ('trace', 'profile', 'tracemalloc')) and
      hooks['monitoring_tools'] == {}, 'r5 instrumentation observation is not exactly clean')
    p(type(launch) is dict and set(launch) == LAUNCH_ENV_KEYS and
      all(v is None or type(v) is str for v in launch.values()),
      'r5 launch environment fields are not closed')
    for key in ('environment', 'environment_after'):
        env = dump[key]
        p(all(type(env[k]) is str and env[k] for k in
              ('executable', 'executable_sha256', 'version', 'implementation', 'cache_tag',
               'prefix', 'base_prefix', 'platform', 'byteorder', 'cwd')),
          'r5 environment text observation malformed')
        p(type(env['version_info']) is list and len(env['version_info']) == 3 and
          all(type(n) is int and n >= 0 for n in env['version_info']),
          'r5 interpreter version_info malformed')
        p(type(env['path_at_start']) is list and
          all(type(n) is str for n in env['path_at_start']), 'r5 sys.path observation malformed')
        p(type(env['flags']) is dict and
          all(type(k) is str and type(v) in (bool, int) for k, v in env['flags'].items()),
          'r5 interpreter flags malformed')
        p(all(type(k) is str and type(v) is str for k, v in env['python_environment'].items()),
          'r5 Python environment value malformed')
        p(all(type(v) is str for v in env['argv']), 'r5 invocation has non-text arguments')
        p(C.file_sha(env['executable']) == env['executable_sha256'],
          'r5 interpreter executable bytes differ')
        for name in ('PYTHONHASHSEED', 'PYTHONDONTWRITEBYTECODE'):
            p(launch[name] == env['python_environment'].get(name),
              'r5 interpreter gate and environment disagree on '+name)
    p(dump['environment'] == dump['environment_after'],
      'r5 complete interpreter/environment observation changed during extraction')
    before, after = dump['store_token_before'], dump['store_token_after']
    p(type(before) is list and len(before) == 3 and before == after and
      type(before[0]) is str and C.HEX64.fullmatch(before[0]) and
      type(before[1]) is list and len(before[1]) == 7 and
      all(type(v) is int and v >= 0 for v in before[1]) and before[2] is None,
      'r5 adopted read-only store token is not the exact catalogue/file/no-candidate shape')
    for name, ref in dump['bindings'].items():
        p(type(ref['nbytes']) is int and ref['nbytes'] > 0,
          'r5 binding byte length malformed: '+name)
        if name == 'catalog':
            # This is a historical observation bound to adopted.catalog_sha256
            # by load_dump. The live catalogue legitimately advances after i0.
            continue
        raw = C.bounded_bytes(Path(ref['path']), 'r5 bound '+name)
        p(len(raw) == ref['nbytes'] and sha256(raw).hexdigest() == ref['sha256'],
          'r5 bound file length or content differs: '+name)
    # Validate the observer invocation against all independently supplied arm inputs.
    argv = dump['environment']['argv']
    expected = {'--profile': str(arm['profile']), '--profile-sha256': arm['sha256'],
                '--interval': str(dump['interval']),
                '--out': str(arm['dumps']/('i%d' % dump['interval'])),
                '--observer-path': observer['path'], '--observer-sha256': observer_pin}
    p(len(argv) == 1+2*len(expected), 'r5 observer invocation has missing or extra arguments')
    args = {}
    for i in range(1, len(argv), 2):
        p(argv[i] in expected and argv[i] not in args, 'r5 observer option unknown or repeated')
        args[argv[i]] = argv[i+1]
    cwd = Path(dump['environment']['cwd'])
    for key, value in expected.items():
        p(C.same_path(cwd/args[key], value) if key in
          ('--profile', '--out', '--observer-path') else args[key] == value,
          'r5 observer invocation differs from proved inputs: '+key)
    check_decoders(C, dump, arm)


def check_decoders(C, dump, arm):
    """Root-route condition (b): the dump names exactly the closed decoder set, each the arm's own pinned
    manifest source.

    The import fence already refused any unpinned workspace module during the dump; this binds the named
    list to the profile's manifest pin and to the bytes now on disk, so a changed decoder refuses here.
    """
    p = C.prove
    found = dump.get('decoders')
    p(type(found) is dict and set(found) == set(DECODER_PATHS),
      'r5 decoder list is not the closed decoder module set')
    workspace, pin = Path(arm['row']['workspace']), arm['row']['source_manifest']
    manifest, digest, _ = C.pinned(workspace/pin['path'], 'r5 decoder source manifest')
    p(digest == pin['sha256'], 'r5 decoder source manifest differs from the profile pin')
    files = manifest.get('files')
    p(type(files) is dict, 'r5 source manifest has no importable source pins')
    for name, entry in sorted(found.items()):
        p(type(entry) is dict and set(entry) == {'path', 'sha256'} and entry['path'] == DECODER_PATHS[name] and
          type(entry['sha256']) is str and C.HEX64.fullmatch(entry['sha256']) and
          files.get(entry['path']) == entry['sha256'] and C.file_sha(workspace/entry['path']) == entry['sha256'],
          "r5 decoder is not the arm's pinned manifest source: "+name)


def root_metadata(C, dump, proofs):
    """Authenticate retained r5 metadata to the root reader-checked producer identity."""
    root = proofs['root']['files']['runner_record'].get('root')
    if type(root) is not dict or root.get('kind') not in C.ROOT_KINDS:
        return None, None, 'root runner record publishes no root kind'
    metadata = dump.get('head', {}).get('root_metadata') if dump.get('schema') == SCHEMA else None
    if metadata is None:
        return C.root_metadata(proofs, 'root: ')
    C.prove(type(metadata) is dict and type(root.get('root_metadata_sha256')) is str and
            sha256(C.producer_json(metadata)).hexdigest() == root['root_metadata_sha256'] and
            metadata.get('key') == root.get('root_key') and metadata.get('kind') == root['kind'] and
            metadata.get('sequence') == 0, 'r5 root metadata is not the reader-proved published root')
    if 'interval' in proofs:
        C.prove(metadata == proofs['interval']['files']['producer_receipt']['completed_endpoint'].get(
            'root_metadata'), 'r5 root metadata differs from reader-checked completed endpoint')
    if dump['interval'] == 0:
        C.prove(dump['head']['key'] == root['root_key'], 'r5 root head key differs from published root')
    return root['kind'], metadata, None


def root_partition_v2(C, dump, header, folder):
    """Bind the dumped root v2 descriptor to the reader-proved root header (None), or say why it is REVIEW.

    Reader side of dump_arm_r5.compact_partition: the entry must carry exactly the header's reference
    and its logical identity, the bytes must be unchanged, and the header must be the one
    partition_workflow_patch.compact_header derives from that descriptor (present HEADER_KEYS only).
    """
    wire = header['compact_partition']
    identity = wire.get('identity')
    C.prove(header.get('record_blobs') == {} and 'partition_id' in header and
            set(header) <= set(PARTITION_HEADER_KEYS) | {'record_blobs', 'compact_partition'},
            'v2 root partition header is not closed')
    C.prove(type(identity) is dict and identity.get('record_schema') == PARTITION_DESCRIPTOR and
            type(identity.get('sha256')) is str and C.HEX64.fullmatch(identity['sha256']) and
            type(identity.get('canonical_bytes')) is int and identity['canonical_bytes'] > 0,
            'v2 root partition reference identity malformed')
    entry = dump.get('partition')
    if type(entry) is not dict or entry.get('dumped') is not True:
        return 'root v2 partition descriptor not dumped: its header stays unbound'
    C.prove(entry.get('route') == PARTITION_ROUTE and entry.get('reference') == wire and
            entry.get('sha256') == identity['sha256'] and entry.get('nbytes') == identity['canonical_bytes'],
            'dumped root partition differs from the reader-proved header reference')
    if entry['nbytes'] > C.MAX_PROOF_BYTES:
        return 'root v2 partition descriptor exceeds the reader-side recomputation limit'
    raw = C.bounded_bytes(folder/'records'/'partition.json', 'root partition descriptor')
    C.prove(len(raw) == entry['nbytes'] and sha256(raw).hexdigest() == entry['sha256'],
            'root partition descriptor changed since the dump')
    descriptor = C.strict_json(raw, 'root partition descriptor')
    C.prove(type(descriptor) is dict and C.producer_json(descriptor) == raw,
            'root partition descriptor is not canonical producer JSON')
    expected = {'partition_id': descriptor.get('partition_id')}
    expected.update((k, descriptor[k]) for k in PARTITION_HEADER_KEYS[1:] if k in descriptor)
    expected.update(record_blobs={}, compact_partition=wire)
    C.prove(expected == header, 'root partition header differs from its dumped descriptor')
    return None


def compare_root_partitions(dumps):
    """r3: the arms' dumped root v2 descriptors. Identical bytes add nothing; any other outcome is REVIEW.

    Each arm's descriptor is first bound to its own header (root_partition_v2). No field contract covers a
    cross-arm descriptor difference, so it is never a PASS allowance.
    """
    entries = {arm: d.get('partition') for arm, d in dumps.items()}
    dumped = sorted(arm for arm, e in entries.items() if type(e) is dict and e.get('dumped') is True)
    if not dumped:
        return []
    if len(dumped) != len(entries):
        return ['root partition: only %s dumped a v2 descriptor (the route differs between arms)' % ', '.join(dumped)]
    if len({(e['sha256'], e['nbytes']) for e in entries.values()}) == 1:
        return []
    return ['root v2 partition descriptors differ between arms: no field contract covers them']


def decoder_summary(dumps):
    """The comparator record's named decoders per arm and interval, the modules whose digests differ, and the
    helpers/*.py decoders among those. The replay precondition holds every helpers module byte-identical in
    both arms, so the comparator reports a differing helper decoder as REVIEW; an atlas_tectonics decoder
    may legitimately differ by the width transform and stays record-only."""
    named = {arm: {'i%d' % i: d['decoders'] for i, d in sorted(per.items()) if 'decoders' in d}
             for arm, per in dumps.items()}
    differ = set()
    for interval in set().union(*(set(v) for v in named.values())):
        rows = [v.get(interval) for v in named.values()]
        if all(type(r) is dict for r in rows):
            differ.update(n for n in set().union(*rows) if len({str(r.get(n)) for r in rows}) > 1)
    helpers = sorted(n for n in differ if DECODER_PATHS.get(n, '').startswith('helpers/'))
    return {'arms': named, 'differ_across_arms': sorted(differ), 'helpers_differ_across_arms': helpers}


def root_mesh_v3(C, dump, exterior, folder):
    """The root v3 mesh reference, the state's thermal_mesh_id and the dumped mesh are one identity."""
    reference = exterior['compact_mesh']
    segment = reference.get('segment')
    identity = segment.get('identity') if type(segment) is dict else None
    C.prove(set(reference) == {'schema', 'segment', 'geometry_id', 'source_producer'} and
            type(segment) is dict and segment.get('schema') == SEGMENT_REF_SCHEMA and type(identity) is dict and
            identity.get('record_schema') == MESH_RECORD_SCHEMA, 'v3 root mesh reference is not closed')
    mesh = dump['records'].get('mesh')
    C.prove(type(mesh) is dict and type(identity.get('sha256')) is str and
            identity['sha256'] == reference['geometry_id'] == exterior.get('thermal_mesh_id') == mesh['sha256'] and
            identity.get('canonical_bytes') == mesh['nbytes'],
            'v3 root mesh reference, geometry_id, thermal_mesh_id and dumped mesh differ')
    state = C.dumped_record(dump, folder, 'state')
    C.prove(type(state) is dict and all(exterior.get(k) == state.get(k) for k in STATE_HEADER_NAMES) and
            set(exterior) == set(STATE_HEADER_NAMES) | {'record_blobs', 'compact_mesh'},
            'root state header differs from the dumped state record')
    blob = (exterior.get('record_blobs') or {}).get('state')
    C.prove(set(exterior['record_blobs']) == {'state'} and type(blob) is dict and
            {'sha256': blob.get('sha256'), 'nbytes': blob.get('bytes')} == dump['records'].get('state'),
            'root state header record blob is not the dumped state record')


def mesh_join(C, exterior):
    """r3: compact root state records carry their v3 thermal mesh join (the dump refuses them otherwise)."""
    blobs = exterior.get('record_blobs')
    C.prove(type(blobs) is dict and all(type(b) is dict for b in blobs.values()),
            'root exterior record blobs malformed')
    compact = sorted(name for name, blob in blobs.items() if 'compact' in blob)
    C.prove(not compact or (len(compact) == len(blobs) and type(exterior.get('compact_mesh')) is dict),
            'compact root state records without their v3 thermal mesh join')


def bind_root(C, dump, proofs, folder, descriptors):
    """Native-root families; migrated roots remain an explicit unsupported route."""
    rows = {r['name']: r for r in dump['arrays']}
    exterior = {n: r for n, r in rows.items() if n.startswith(C.EXTERIOR_PREFIX)}
    status, issues = {}, []
    rest = {n: r for n, r in rows.items() if n not in exterior}
    entry = dump.get('partition')
    dumped = type(entry) is dict and entry.get('dumped') is True
    bound_partition = False
    kind, metadata, why = root_metadata(C, dump, proofs)
    if kind != 'root' or metadata is None:
        C.prove(not dumped, 'dumped root partition on a root route with no v2 header to bind it')
        reason = why or 'migrated-root route has no implemented independent family binding'
        issues.append(reason)
        status.update((n, ('unbound', reason)) for n in rows)
        if exterior:
            bound = C.exterior_binding(dump, folder, exterior)
            status.update((n, ('bound', 'state_id') if bound == 'bound' else ('unbound', bound))
                          for n in exterior)
        return status, issues
    if 'exterior_state' in metadata:
        C.prove(type(metadata['exterior_state']) is dict, 'root exterior state metadata malformed')
        mesh_join(C, metadata['exterior_state'])
        bound = C.exterior_binding(dump, folder, exterior)
        if bound != 'bound':
            issues.append('exterior route: '+str(bound))
        else:
            state = C.dumped_record(dump, folder, 'state')
            C.prove(metadata['exterior_state'].get('state_id') == state.get('state_id'),
                    'root exterior metadata differs from reader-proved state_id')
        status.update((n, ('bound', 'state_id') if bound == 'bound' else ('unbound', bound))
                      for n in exterior)
    else:
        C.prove(not exterior, 'root exterior-fv arrays without exterior_state metadata')
    C.prove(not any(n.startswith(C.SUCCESSOR_PREFIXES) for n in rest),
            'successor-only families at a proved root head')
    heat = {n[len(C.HEAT_PREFIX):]: r for n, r in rest.items() if n.startswith(C.HEAT_PREFIX)}
    collar = {n: r for n, r in rest.items() if not n.startswith(C.ROOT_PREFIXES)}
    state = metadata.get('state')
    C.prove(type(state) is dict and state.get('schema') == C.COLLAR_STATE_SCHEMA and
            type(state.get('fields')) is dict and type(metadata.get('native_state_id')) is str and
            (type(state['exterior_heat']) is dict if 'exterior_heat' in state else not heat),
            'root collar/exterior-heat metadata malformed')
    identity = {'fields_id': C.snapshot_id(state['fields'], collar, folder, 'root collar'),
                'native_state_id': metadata['native_state_id']}
    if 'exterior_heat' in state:
        identity['exterior_heat_id'] = C.snapshot_id(state['exterior_heat'], heat, folder, 'root exterior heat')
    C.prove(sha256(C.producer_json(identity)).hexdigest() == state.get('result_id'),
            'root collar/exterior-heat payload contradicts reader-proved result_id')
    status.update((n, ('bound', 'collar result_id')) for n in collar)
    status.update((C.HEAT_PREFIX+n, ('bound', 'collar result_id')) for n in heat)
    partition = metadata.get('differential_partition')
    refs = partition.get('record_blobs') if type(partition) is dict else {}
    C.prove(type(refs) is dict, 'root differential partition refs malformed')
    blobs = {n: r for n, r in rest.items() if n.startswith(C.PARTITION_RECORD)}
    C.prove(all(type(v) is dict and set(v) == {'array', 'bytes', 'sha256'} and
                type(v['array']) is str and type(v['bytes']) is int and v['bytes'] > 0 and
                type(v['sha256']) is str and C.HEX64.fullmatch(v['sha256']) for v in refs.values()),
            'root differential partition ref fields malformed')
    expected = {ref['array']: ref for ref in refs.values()}
    C.prove(set(blobs) == set(expected) and len(expected) == len(refs),
            'root partition-record arrays differ from independently bound refs')
    for name, row in blobs.items():
        ref = expected[name]
        C.prove(C.np.dtype(row['dtype']) == C.np.dtype('u1') and row['shape'] == [ref['bytes']] and
                row['sha256'] == ref['sha256'], 'root partition-record payload differs from bound ref')
        status[name] = ('bound', 'partition record ref')
    for prefix, references, where in (
            (C.PARTITION_ALIAS, [metadata.get('compact_partition'),
              partition.get('compact_partition') if type(partition) is dict else None], 'partition-dag'),
            (C.MESH_ALIAS, [(metadata.get('exterior_state') or {}).get('compact_mesh')], 'spatial-mesh')):
        aliases = {n: r for n, r in rest.items() if n.startswith(prefix)}
        references = [r for r in references if r is not None]
        if not references:
            C.prove(not aliases, 'root aliases without independently bound '+where+' reference')
            continue
        C.prove(len(references) == 1, 'root has ambiguous compact '+where+' references')
        schema = references[0].get('schema') if type(references[0]) is dict else None
        if where == 'partition-dag' and schema == SEGMENT_REF_SCHEMA:
            # Root-route condition (c): a v2 partition has no alias arrays; its dumped descriptor binds the header.
            C.prove(not aliases and not blobs and type(partition) is dict and
                    references[0] is partition.get('compact_partition'),
                    'v2 root partition with alias arrays, record blobs or a top-level reference')
            why = root_partition_v2(C, dump, partition, folder)
            bound_partition = True
            if why:
                issues.append(why)
            continue
        if where == 'spatial-mesh' and schema == MESH_V3_SCHEMA:
            # r3: a v3 thermal mesh has no alias arrays; its segment identity is the dumped mesh.
            C.prove(not aliases, 'v3 root mesh with spatial-mesh alias arrays')
            root_mesh_v3(C, dump, metadata['exterior_state'], folder)
            continue
        bindings = C.alias_names(references[0], prefix, aliases, 'root '+where)
        status.update(C.alias_targets(bindings, prefix, None if descriptors is None else
                                     {n: d for n, d in descriptors.items() if n.startswith(prefix)}))
    C.prove(not any(n.startswith(C.RECORD_ARRAY) for n in rows), 'spatial-record array in root dump')
    C.prove(bound_partition or not dumped, 'dumped root partition has no v2 header reference to bind it')
    C.prove(set(status) == set(rows), 'root array family coverage is incomplete')
    return status, issues


def validate_composite_coverage(C, dump, folder):
    """Check absence as well as presence: deleting a whole composite family cannot bypass binding."""
    cert = C.dumped_record(dump, folder, 'certification')
    C.prove(type(cert) is dict and type(cert.get('force')) is dict and
            type(cert.get('solution')) is dict, 'i1 certification force link missing')
    force = {r['name'][len(C.FORCE_PREFIX):]: r for r in dump['arrays']
             if r['name'].startswith(C.FORCE_PREFIX)}
    C.prove(C.snapshot_id(cert['force'], force, folder, 'i1 force') ==
            cert['solution'].get('force_exchange_id'), 'i1 force family missing or contradicts certification')
    differential = C.dumped_record(dump, folder, 'differential')
    descriptor = differential.get('endpoint_network') if type(differential) is dict else None
    C.prove(type(descriptor) is dict and type(descriptor.get('arrays')) is list and
            all(type(r) is dict for r in descriptor['arrays']) and
            tuple(r.get('name') for r in descriptor['arrays']) == NETWORK_NAMES,
            'i1 endpoint network lacks exact eight producer arrays in producer order')
    expected = {C.NETWORK_PREFIX+C.NETWORK_ARRAY+n for n in NETWORK_NAMES}
    actual = {r['name'] for r in dump['arrays'] if r['name'].startswith(C.NETWORK_PREFIX)}
    C.prove(actual == expected, 'i1 network family missing or has extra arrays')


def _network_domain(C, dump, folder):
    """Read structural identifiers, never derive correspondence from changed numeric values."""
    rows = {r['name'][len(C.NETWORK_PREFIX+C.NETWORK_ARRAY):]: r for r in dump['arrays']
            if r['name'].startswith(C.NETWORK_PREFIX+C.NETWORK_ARRAY)}
    descriptor = C.dumped_record(dump, folder, 'differential')['endpoint_network']
    row = rows['vertex_ids']
    C.prove(C.np.dtype(row['dtype']) == C.np.dtype('u1') and len(row['shape']) == 1,
            'network vertex IDs are not the producer JSON-lines byte array')
    raw = C.bounded_bytes(folder/'arrays'/row['file'], 'network vertex IDs')
    vertices = [C.strict_json(line, 'network vertex ID') for line in raw.split(b'\n')] if raw else []
    C.prove(all(type(v) is str and v for v in vertices) and len(set(vertices)) == len(vertices),
            'network vertex IDs are missing, malformed or repeated')
    plates = descriptor.get('plates')
    C.prove(type(plates) is list and all(type(p) is dict and type(p.get('plate_id')) is str and
            p['plate_id'] for p in plates), 'network plate order missing')
    plate_ids = [p['plate_id'] for p in plates]
    C.prove(len(set(plate_ids)) == len(plate_ids), 'network plate IDs repeat')
    indexes = {}
    for name, bound in (('view_vertex', len(vertices)), ('view_plate', len(plate_ids))):
        r = rows[name]
        C.prove(r['dtype'] == '<i8' and len(r['shape']) == 1, 'network view indices malformed')
        values = C.np.fromfile(folder/'arrays'/r['file'], dtype='<i8')
        C.prove(bool(C.np.all((values >= 0) & (values < bound))), 'network view index outside own ID table')
        indexes[name] = values.tolist()
    C.prove(len(indexes['view_vertex']) == len(indexes['view_plate']), 'network view ID columns differ')
    views = [[vertices[v], plate_ids[p]] for v, p in
             zip(indexes['view_vertex'], indexes['view_plate'], strict=True)]
    C.prove(len({tuple(v) for v in views}) == len(views), 'network view identifiers repeat')
    home = rows['vertex_home']
    C.prove(home['dtype'] == '<i8' and home['shape'] == [len(vertices)],
            'network home-frame indices do not index vertices')
    homes = C.np.fromfile(folder/'arrays'/home['file'], dtype='<i8').tolist()
    # _home_index is plate frames then ridge frames. Keep the bound frames and
    # boundary order as part of the domain: equal vertex names alone do not
    # establish equality of coordinates represented in different home frames.
    return {'vertices': vertices, 'plates': plate_ids, 'views': views, 'homes': homes,
            'sphere': descriptor.get('sphere'), 'epoch_id': descriptor.get('epoch_id'),
            'reference_time_s': descriptor.get('reference_time_s'),
            'frames': descriptor.get('frames'), 'ridge_frames': descriptor.get('ridge_frames'),
            'faces_sha256': rows['faces']['sha256'], 'boundaries_sha256': rows['boundaries']['sha256']}


def layouts(C, dump, proofs, folder):
    """Row identity per emitted array; no identity is inferred from numeric contents."""
    result = {}
    state_ids = None
    transport_ids = None
    _, metadata, _ = root_metadata(C, dump, proofs)
    collar_state = metadata.get('state', {}) if type(metadata) is dict else {}
    interval_endpoint = (proofs['interval']['files']['producer_receipt']['completed_endpoint']
                         if dump['interval'] == 1 else {})
    network_domain = None
    for row in dump['arrays']:
        name = row['name']
        if name.startswith(C.EXTERIOR_PREFIX):
            if state_ids is None:
                state_ids = C.state_cell_ids(dump, folder)
            ids, kind = state_ids, 'state-cell'
        elif name.startswith(TRANSPORT_PREFIX):
            suffix = name[len(TRANSPORT_PREFIX):]
            C.prove(suffix.startswith(('stock:', 'density:')) and suffix.partition(':')[2],
                    'unknown transport field layout: '+name)
            if transport_ids is None:
                record = C.dumped_record(dump, folder, 'transport')
                C.prove(type(record) is dict and record.get('schema') == 'atlas.spatial-implicit-transport.v1',
                        'transport record schema cannot establish its cell order')
                transport_ids = record.get('cell_ids')
            ids, kind = transport_ids, 'transport-cell'
        else:
            domain = None
            if name.startswith(C.NETWORK_PREFIX):
                if network_domain is None:
                    network_domain = _network_domain(C, dump, folder)
                domain = ['network-structure', network_domain, name]
            elif name.startswith(C.FORCE_PREFIX):
                cert = C.dumped_record(dump, folder, 'certification')
                domain = ['force-snapshot', cert['solution']['force_exchange_id'], name]
            elif name.startswith('spatial-audit:joined-heat:') and 'exchange' in dump['records']:
                exchange = C.dumped_record(dump, folder, 'exchange')
                heat = exchange.get('joined_heat') if type(exchange) is dict else None
                if type(heat) is dict and all(type(heat.get(k)) is str and heat[k]
                                             for k in ('plan_id', 'geometry_id')):
                    domain = ['joined-heat-plan-geometry', heat['plan_id'], heat['geometry_id'], name]
            elif name.startswith(C.HEAT_PREFIX):
                heat = collar_state.get('exterior_heat', {})
                if type(heat) is dict and type(heat.get('plan_id')) is str and heat['plan_id']:
                    domain = ['exterior-heat-plan', heat['plan_id'], name]
            elif name.startswith('source-audit:'):
                native = collar_state.get('native', {})
                if type(native) is dict and type(native.get('plan_id')) is str and native['plan_id']:
                    domain = ['native-source-grid', native['plan_id'], name]
                elif type(interval_endpoint.get('source_audit_id')) is str:
                    domain = ['source-audit-snapshot', interval_endpoint['source_audit_id'], name]
            elif name.startswith(C.PARTITION_RECORD):
                domain = ['canonical-record-bytes', name]
            elif name.startswith((C.PARTITION_ALIAS, C.MESH_ALIAS)) and type(metadata) is dict:
                reference = (metadata.get('compact_partition') or
                             (metadata.get('differential_partition') or {}).get('compact_partition')
                             if name.startswith(C.PARTITION_ALIAS) else
                             (metadata.get('exterior_state') or {}).get('compact_mesh'))
                if type(reference) is dict:
                    domain = ['compact-reference', sha256(C.producer_json(reference)).hexdigest(), name]
            elif not name.startswith(C.ROOT_PREFIXES+C.SUCCESSOR_PREFIXES):
                fields = collar_state.get('fields', {})
                if type(fields) is dict and type(fields.get('plan_id')) is str and fields['plan_id']:
                    domain = ['collar-plan-grid', fields['plan_id'], name]
            result[name] = ({'kind': 'fixed-domain', 'identity': domain, 'axis': None} if domain is not None
                            else {'kind': 'positional-unproved', 'identity': None, 'axis': None})
            continue
        if ids is None:
            result[name] = {'kind': 'positional-unproved', 'identity': None, 'axis': None}
            continue
        C.prove(type(ids) is list and all(type(k) is str and k for k in ids) and
                len(set(ids)) == len(ids), kind+' IDs are malformed or repeated')
        C.prove(row['shape'] == [len(ids)], kind+' array does not have its exact source-proved vector shape')
        result[name] = {'kind': kind, 'identity': list(ids), 'axis': 0}
    return result


def bind_all(C, dump, proofs, folder):
    """Return (name -> (bound/unbound, route), REVIEW reasons, name -> layout).

    `proofs` is one arm's independently re-derived {'root': proof[, 'interval': proof]}.
    The caller must include every returned review, and evaluate layouts before
    allowing byte-identical payloads to imply comparison equality.
    """
    reviews = []
    interval = dump['interval']
    if dump['schema'] != SCHEMA:
        reviews.append('legacy dump lacks the complete r5 observation contract')
    if interval == 0:
        descriptors = None if dump['schema'] == C.DUMP_SCHEMA else {
            r['name']: r['descriptor_sha256'] for r in dump['arrays']}
        statuses, issues = bind_root(C, dump, proofs, folder, descriptors)
        reviews.extend(issues)
    else:
        root_metadata(C, dump, proofs)
        validate_composite_coverage(C, dump, folder)
        statuses = C.bind_arrays(dump, proofs['interval'], interval, folder)
        # No compact successor aliases are emitted by the specified producer.
        # Other storage routes need independent evidence and are not inferred.
        for name in statuses:
            if name.startswith((C.PARTITION_ALIAS, C.MESH_ALIAS, C.PARTITION_RECORD,
                                'certification-record:', 'differential-record:')):
                statuses[name] = ('unbound', 'no independent successor-head binding for this storage route')
    C.prove(set(statuses) == {r['name'] for r in dump['arrays']}, 'array family coverage is incomplete')
    layout = layouts(C, dump, proofs, folder)
    unproved = sorted(name for name, value in layout.items() if value['kind'] == 'positional-unproved')
    if unproved:
        reviews.append('array row correspondence not independently established: '+', '.join(unproved))
    return statuses, reviews, layout
