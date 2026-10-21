"""Strict current-generation W4 comparison using the retained physical proof.

The r13 physical bijections, binary64 arrays, exact accounts and ledger equations
are unchanged. Its historical source fence is replaced with the exact requested
production inventories. Named identities require captured, verified preimages;
every resource observation and every other metadata field remains exact.
"""
import ast
from pathlib import Path

import w4_common as C


OUTPUT_PROJECTION_OLD = 'private_heat_native_projection_r4.py'
OUTPUT_PROJECTION_NEW = 'private_heat_native_projection_r5.py'
OUTPUT_NUMERICS_NEW = 'private_heat_projection_numerics_r4.py'
OUTPUT_PROJECTION_PINS = {
    OUTPUT_PROJECTION_OLD: '2c66898aea90f1613ef40b2ac570dda25f26d9f258a9fdf02efa71297479189f',
    OUTPUT_PROJECTION_NEW: '7fb40186f8b2e58426f269bef8fc034e42954d937b5a09331f903c50ce550616',
    OUTPUT_NUMERICS_NEW: '5cfd192b89444b599a9625a6fccb5a83a890b23be26ec2904038743d91c99eb1',
}


def _projection_codec_equivalence(old_raw, new_raw):
    """Allow only the reviewed numerical import/call; prove all codec code exact."""
    old_tree, new_tree = ast.parse(old_raw), ast.parse(new_raw)
    added = ast.parse('import private_heat_projection_numerics_r4 as NUMERICS').body[0]
    imports = [node for node in new_tree.body
        if ast.dump(node, include_attributes=False) == ast.dump(added, include_attributes=False)]
    C.require(len(imports) == 1, 'Exact reviewed projection numerical import required')
    new_tree.body.remove(imports[0])
    projects = [node for node in new_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'project']
    C.require(len(projects) == 1, 'Unique reviewed projection entry required')
    calls = [node for node in ast.walk(projects[0]) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == 'calculate'
        and isinstance(node.func.value, ast.Name) and node.func.value.id == 'NUMERICS']
    C.require(len(calls) == 1, 'Exact reviewed projection numerical call required')
    calls[0].func.value = ast.Name(id='R', ctx=ast.Load())
    C.require(ast.dump(new_tree, include_attributes=False) == ast.dump(old_tree, include_attributes=False),
        'Projection changes codec, metadata, geometry, owners or other unreviewed code')


def _output_policy_sources(V, bundle, inventory):
    """Translate N4 authority only for the actual source-bound N5/Q selection."""
    helpers = inventory['composition']['helpers']
    root = inventory['root'] / 'helpers'
    captured = {str(Path(path).resolve()): pin for path, pin in bundle['caller']['private_sources'].items()}
    loaded = bundle.get('plan14_preimages', {}).get('loaded', {})
    loaded_sources = loaded.get('sources', {})
    new_path = str((root / OUTPUT_PROJECTION_NEW).resolve())
    new_module = Path(OUTPUT_PROJECTION_NEW).stem
    if new_path not in captured and new_module not in loaded_sources:
        # The original captured-N4 route and its retained source/equation
        # checks are unchanged; filesystem presence of N5 grants nothing.
        return {name: helpers[name] for name in V.OUTPUT_POLICY_SOURCE_PINS}
    C.require(V.OUTPUT_POLICY_SOURCE_PINS.get(OUTPUT_PROJECTION_OLD)
        == OUTPUT_PROJECTION_PINS[OUTPUT_PROJECTION_OLD], 'Retained projection formula authority differs')
    C.require(str((root / OUTPUT_PROJECTION_OLD).resolve()) not in captured,
        'Ambiguous old/new captured projection authority')
    for name, pin in OUTPUT_PROJECTION_PINS.items():
        C.require(helpers.get(name) == pin and inventory['files'].get(str((root / name).resolve())) == pin,
            'Reviewed projection authority is outside exact selected sources: ' + name)
    for name in (OUTPUT_PROJECTION_NEW, OUTPUT_NUMERICS_NEW):
        path, pin = str((root / name).resolve()), OUTPUT_PROJECTION_PINS[name]
        C.require(captured.get(path) == pin
            and loaded_sources.get(Path(name).stem) == dict(path=path, sha256=pin),
            'Projection formula authority is not actually captured and loaded: ' + name)
    functions = loaded.get('functions', {})
    C.require(all(name in functions for name in (new_module + '._encode', new_module + '.project',
        Path(OUTPUT_NUMERICS_NEW).stem + '.calculate')), 'Loaded projection codec/numerical functions are missing')
    # Exact full sources plus this whole-module structural proof establish
    # unchanged metadata, _encode, return geometry and owner lifetimes.
    raw = {name: C.pinned((root / name).resolve(), pin) for name, pin in OUTPUT_PROJECTION_PINS.items()}
    _projection_codec_equivalence(raw[OUTPUT_PROJECTION_OLD], raw[OUTPUT_PROJECTION_NEW])
    result = {name: pin for name, pin in V.OUTPUT_POLICY_SOURCE_PINS.items() if name != OUTPUT_PROJECTION_OLD}
    for name, pin in result.items():
        path = str((root / name).resolve())
        C.require(helpers.get(name) == pin and inventory['files'].get(path) == pin
            and captured.get(path) == pin, 'Retained output formula authority differs: ' + name)
        C.pinned(path, pin)
    result[OUTPUT_PROJECTION_NEW] = OUTPUT_PROJECTION_PINS[OUTPUT_PROJECTION_NEW]
    return result


def output_component_replay(V, verifier_ref):
    """Retain the complete original output formula body and selected-root seam."""
    raw = C.pinned(Path(verifier_ref['path']), verifier_ref['sha256'])
    tree = ast.parse(raw)
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
        and node.name == '_output_component_evidence']
    C.require(len(nodes) == 1, 'Unique retained output formula entry required')
    source = ast.get_source_segment(raw.decode('utf8'), nodes[0])
    old = '(TASK_ROOT / "hs" / layout / "helpers" / name).resolve()'
    C.require(source.count(old) == 1, 'Retained output formula authority seam differs')
    source = source.replace(old, '(actual_root / "helpers" / name).resolve()')
    code = compile(source, str(verifier_ref['path']) + ':selected-authority-only', 'exec')

    def replay(bundle, inventory):
        namespace = dict(vars(V), actual_root=inventory['root'],
            OUTPUT_POLICY_SOURCE_PINS=_output_policy_sources(V, bundle, inventory))
        exec(code, namespace)
        return namespace['_output_component_evidence'](bundle)

    return replay


def _bound_json(directory, name, pin):
    raw = C.pinned((directory / name).resolve(), pin)
    return raw, C.parse(raw)


def funding_witness(witness):
    origin = witness['origin_signature']
    preimage = witness['funding_snapshot_preimage']
    C.require(witness.get('funding_snapshot_identity_recomputed') is True
        and C.sha(C.canonical(preimage)) == origin['funding_id']
        and C.canonical(witness['funding_record'])
            == C.canonical(dict(funding_id=origin['funding_id'], **preimage['metadata'])),
        'Actual funding descriptor/snapshot identity preimage differs')


def _preimages(V, bundle, native, inventory):
    root = bundle['root']
    caller, meta = bundle['caller'], bundle['meta']
    bindings = native['preimage_bindings']
    C.require(bindings['private_callback_count'] == 2 and len(bindings['private_results']) == 2,
              'Both actual private numerical results are required')
    C.require(bindings.get('observer_stop_completed') is True
              and bindings.get('monitoring_slot_released') is True and bindings.get('synthetic') is False,
              'Additional preimage observer did not complete its real-call cleanup')
    operations = bindings['observer_operations']
    C.require(not operations['secondary_failures'] and len(operations['operations']) == 2
              and all(row['phase'] == 'private-result-preimage' and row['failed'] is False
                      and row['deferred_to_callback_finally'] is True for row in operations['operations']),
              'Additional preimage callback operation failed or is incomplete')
    releases = bindings['private_callback_releases']
    C.require(len(releases) == 2, 'Both additional callback release records are required')
    for release in releases:
        C.require(release['released'] is True and release['callback_finalised'] is True
                  and release['retained_funding'] is False and release['explicit_release_required'] is False
                  and release['native_owners_retained'] == 0
                  and release['observer_reserved_bytes'] == release['observer_before_bytes'],
                  'Additional preimage callback retained native owners or funding')
    loaded_raw, loaded = _bound_json(root, 'loaded-preimage.json', bindings['loaded_sha256'])
    C.require(C.sha(loaded_raw) == caller['loaded_dependencies']['identity'] == meta['loaded_dependencies']['identity']
              and loaded['schema'] == 'atlas.private.loaded-dependencies.r1'
              and loaded['marshal_protocol'] == 2 and loaded['source_matches_loaded_not_asserted'] is True,
              'Loaded dependency identity preimage differs')
    C.require(meta['loaded_dependencies'] == caller['loaded_dependencies'] == dict(schema='atlas.private.loaded-dependencies.r1',
              identity=C.sha(loaded_raw), source_and_loaded_semantics_bound=True,
              source_matches_loaded_not_asserted=True), 'Loaded implementation descriptor differs')
    C.require(loaded['sources'] and loaded['functions'], 'Empty loaded implementation preimage')
    for row in loaded['sources'].values():
        path = str(Path(row['path']).resolve())
        C.require(inventory['files'].get(path) == row['sha256'], 'Loaded module is outside actual selected source')
    execution_raw, execution = _bound_json(root, 'execution-preimage.json', bindings['execution_sha256'])
    C.require(C.sha(execution_raw) == caller['execution']['execution_identity']
              and execution['schema'] == 'atlas.kernel-execution.v4' and execution['code_marshal_format'] == 2
              and execution['backend'] == 'scipy' and execution['sources'] and execution['loaded_code'],
              'Execution identity preimage differs')
    # Native source inventory keys are package-relative, rather than arbitrary
    # pathname/digest-shaped leaves. Every captured entry must be in the frozen
    # actual native composition with its exact bytes.
    native_sources = inventory['composition']['outputs']
    expected_execution_sources = {}
    for member, pin in native_sources.items():
        if member.startswith('atlas_tectonics/') and member.endswith('.py'):
            name = member[len('atlas_tectonics/'):]
            source = inventory['root'] / 'src' / member
            # reuse._source_bytes returns canonical bounded digest-record
            # bytes, and ExecutionContext hashes those records, not raw files.
            expected_execution_sources[name] = C.sha(C.canonical(dict(bytes=source.stat().st_size, sha256=pin)))
    C.require(execution['sources'] == expected_execution_sources,
              'Complete execution source inventory preimage differs from actual selected package')
    witness_raw, witness = _bound_json(root, 'origin-witness.json', bindings['origin_witness_sha256'])
    C.require(witness['schema'] == 'atlas.private.plan14.native-origin-witness.r1'
              and witness.get('synthetic') is False
              and witness['call_metadata_sha256'] == C.sha(C.canonical(caller))
              and witness['call_id'] == meta['call_id']
              and witness['native_verify_call_completed'] is True and witness['owner_verify_completed'] is True
              and witness['origin_signature_recomputed_and_equal'] is True
              and witness['origin_signature'] == caller['native_origin_signature']
              and witness['mesh_header'] == bundle['header'], 'Native origin witness differs')
    for key in ('issuer_source', 'forward_source'):
        ref = witness[key]
        member = ('private_heat_native_issuer_r13.py' if key == 'issuer_source' else
                  'private_heat_forward_kernel_r13.py')
        expected_path = (inventory['root'] / 'helpers' / member).resolve()
        C.require(Path(ref['path']).resolve() == expected_path
                  and inventory['files'].get(str(expected_path)) == ref['sha256'],
                  'Native origin witness selects another implementation')
    origin = witness['origin_signature']
    funding_witness(witness)
    C.require(C.sha(C.canonical(witness['owner_definition'])) == origin['owner_definition_id']
              == origin['owner_id'], 'Native owner definition identity does not replay')
    for key, value in witness['snapshot_verification'].items():
        target = 'state_id' if key == 'transported_state_id' else key
        C.require(origin.get(target) == value, 'Native snapshot verification witness differs: ' + key)
    private = []
    for index, ref in enumerate(bindings['private_results']):
        C.require(ref['file'] == 'private-' + str(index) + '.json', 'Private preimage filename/order differs')
        raw, record = _bound_json(root, ref['file'], ref['sha256'])
        value = dict(record)
        result_id = value.pop('result_id')
        C.require(C.sha(C.canonical(value)) == result_id == meta['private_result_id'],
                  'Private numerical result identity preimage differs')
        C.require(record['sources'], 'Private result omits bound sources')
        for name, pin in record['sources'].items():
            C.require((inventory['files'] | inventory['data']).get(str(Path(name).resolve())) == pin,
                      'Private result source differs from actual composition')
        private.append(record)
    C.require(bindings['private_results'][0]['sha256'] == bindings['private_results'][1]['sha256']
              and C.canonical(private[0]) == C.canonical(private[1]),
              'Same-call private numerical sealed output differs before packaging')
    bundle['plan14_preimages'] = dict(loaded=loaded, execution=execution, origin=witness, private=private[0],
        bindings=bindings, loaded_sha256=C.sha(loaded_raw), execution_sha256=C.sha(execution_raw),
        origin_sha256=C.sha(witness_raw))


def _source_check(request, inventories, provenance, caller, historical_label, index, run_root=None):
    del historical_label, run_root
    arm, inventory = request['arms'][index], inventories[index]
    C.require(provenance['arm_index'] == index and provenance['layout_name'] == arm['label'],
              'Actual pair label/provenance differs')
    C.require(provenance['layout_control_sha256'] == arm['control']['sha256']
              and provenance['step7_control_sha256'] == request['primary']['control']['sha256']
              and provenance['issuer_sha256'] == inventory['composition']['helpers']['private_heat_native_issuer_r13.py'],
              'Actual control/issuer source binding differs')
    sources = caller['private_sources']
    C.require(sources == provenance['private_sources'] and sources, 'Complete actual private source map required')
    for name, pin in sources.items():
        C.require((inventory['files'] | inventory['data']).get(str(Path(name).resolve())) == pin,
                  'Private source escaped exact selected profile: ' + name)
    required = ['private_heat_native_issuer_r13.py', 'mesh_tables.py', 'exterior_mesh_patch.py',
                'heat_ledger_tables.py', 'content_cache.py', 'private_heat_indexed_runtime.py',
                'private_heat_physical_order_r1.py', 'private_heat_forward_kernel_r13.py']
    required += (['private_heat_finish_kernel_r10.py', 'private_heat_closed_owned_r4.py'] if index == 0 else
                 ['private_heat_finish_kernel_r11.py', 'private_heat_closed_owned_r5.py'])
    for name in required:
        path = str(inventory['root'] / 'helpers' / name)
        C.require(sources.get(path) == inventory['files'].get(path) and sources.get(path) is not None,
                  'Required actual loaded source is missing: ' + name)
    return dict(schema='atlas.private.plan14.selected-source-binding.r1', label=arm['label'],
                composition_sha256=arm['composition']['sha256'], profile_sha256=arm['profile']['sha256'],
                h5a_enabled=False, actual_sources=sources)


def _source_correspondence(bundles, inventories):
    rows = []
    maps = []
    for bundle, inventory in zip(bundles, inventories, strict=True):
        mapping = {}
        for name, pin in bundle['caller']['private_sources'].items():
            path = Path(name).resolve()
            if path.is_relative_to(inventory['root']):
                key = path.relative_to(inventory['root']).as_posix()
                key = key.replace('private_heat_finish_kernel_r11.py', 'private_heat_finish_kernel_r10.py')
                key = key.replace('private_heat_closed_owned_r5.py', 'private_heat_closed_owned_r4.py')
            else:
                key = 'external/' + path.relative_to(inventory['workspace']).as_posix()
            C.require(key not in mapping, 'Ambiguous bound source correspondence')
            mapping[key] = dict(path=name, sha256=pin)
        maps.append(mapping)
    for key in sorted(set(maps[0]) | set(maps[1])):
        rows.append(dict(relative_path=key, base=maps[0].get(key), joint=maps[1].get(key),
                         disposition='EXACT_ACTUAL_SOURCE_MAP_AND_APPROVED_R4_R5_R10_R11_CORRESPONDENCE'))
    return rows


PRIVATE_SCHEMA = 'atlas.private.standalone-corrected-integrated-heat-result.r1'
PRIVATE_CELL_FIELDS = ('capacity', 'corrected_energy_exact', 'enthalpy_j',
    'exact_cell_residual', 'old_energy', 'public_cell_residual',
    'stock_projection_residual', 'temperature_k')
PRIVATE_FLOAT_FIELDS = frozenset(('enthalpy_j', 'temperature_k'))


def _private_pair(value):
    """Accept the sealed producer's canonical decimal pair, without rounding."""
    def integer(text, *, positive=False):
        if type(text) is not str or not text:
            return False
        digits = text[1:] if text.startswith('-') else text
        if not digits or any(char not in '0123456789' for char in digits):
            return False
        if digits == '0':
            return text == '0' and not positive
        return digits[0] != '0' and (not positive or not text.startswith('-'))

    C.require(type(value) is list and len(value) == 2
        and integer(value[0]) and integer(value[1], positive=True),
        'Private exact value is not a canonical decimal numerator/denominator pair')


def _private_sign(value, sign):
    _private_pair(value)
    C.require(type(sign) is int and sign in (-1, 1), 'Private face sign must be exactly +/-1')
    numerator, denominator = value
    if sign == -1 and numerator != '0':
        numerator = numerator[1:] if numerator.startswith('-') else '-' + numerator
    return [numerator, denominator]


def _private_correspondence(a, b, physical_mapping):
    """Compare every sealed value through the SAME authenticated physical map.

    Only the eight named cell vectors and face-indexed fields are reordered.
    No value is dropped, rounded or classified by digest shape. The unchanged
    sources/result_id exclusions have already been authenticated in _preimages.
    Every other field (including source_energy and unknown additions) is exact.
    """
    C.require(type(physical_mapping) is tuple and len(physical_mapping) == 3,
        'Authenticated physical cell/face/orientation maps are required')
    pi, sigma, orientation = physical_mapping
    C.require(all(type(row) in (list, tuple) for row in physical_mapping),
        'Physical maps must be complete explicit sequences')
    n, nf = len(a['keys']), len(a['incidence'])
    C.require(n > 0 and nf > 0 and len(b['keys']) == n and len(b['incidence']) == nf,
        'Private physical coverage differs between arms')
    for mapping, count, label in ((pi, n, 'cell'), (sigma, nf, 'face')):
        C.require(len(mapping) == count and all(type(index) is int for index in mapping)
            and set(mapping) == set(range(count)), 'Private ' + label + ' map is not a complete bijection')
    C.require(len(orientation) == nf and all(type(sign) is int and sign in (-1, 1) for sign in orientation),
        'Private face orientation coverage is incomplete or invalid')
    C.require(len(set(a['keys'])) == len(set(b['keys'])) == n
        and all(a['keys'][i] == b['keys'][j] for i, j in enumerate(pi)),
        'Private cell map differs from authenticated physical keys')
    values = [bundle['plan14_preimages']['private'] for bundle in (a, b)]
    for bundle, private in zip((a, b), values, strict=True):
        C.require(type(private) is dict and private.get('schema') == PRIVATE_SCHEMA,
            'Private numerical preimage schema differs')
        for name in PRIVATE_CELL_FIELDS:
            rows = private.get(name)
            C.require(type(rows) is list and len(rows) == n, 'Incomplete private cell field: ' + name)
            for value in rows:
                if name in PRIVATE_FLOAT_FIELDS:
                    C.require(type(value) is float, 'Private public array must retain float type: ' + name)
                    C.canonical(value)  # refuses non-finite JSON, preserves signed zero
                else:
                    _private_pair(value)
        ids, faces = private.get('face_ids'), private.get('physical_faces')
        C.require(type(ids) is list and len(ids) == nf
            and all(type(value) is str and value for value in ids) and len(set(ids)) == nf
            and C.canonical(ids) == C.canonical(bundle['meta']['face_ids']),
            'Private face IDs do not exactly cover authenticated metadata')
        C.require(type(faces) is list and len(faces) == nf, 'Incomplete private physical faces')
        for row, incidence in zip(faces, bundle['incidence'], strict=True):
            C.require(type(row) is list and len(row) == 3
                and type(incidence) in (list, tuple) and len(incidence) in (1, 2),
                'Private physical face/owner schema differs')
            for owner in incidence:
                C.require(type(owner) in (list, tuple) and len(owner) == 2
                    and type(owner[0]) is int and 0 <= owner[0] < n
                    and type(owner[1]) is int and owner[1] in (-1, 1),
                    'Invalid authenticated private face incidence')
            owners = [owner[0] for owner in incidence]
            C.require(len(set(owners)) == len(owners)
                and type(row[0]) is int and 0 <= row[0] < n
                and (row[1] is None or type(row[1]) is int and 0 <= row[1] < n)
                and row[:2] == [owners[0], owners[1] if len(owners) == 2 else None],
                'Private face owners do not match authenticated incidence')
            _private_pair(row[2])
    private_a, private_b = values
    differences = []
    for name in PRIVATE_CELL_FIELDS:
        for i, j in enumerate(pi):
            if C.canonical(private_a[name][i]) != C.canonical(private_b[name][j]):
                differences.append('/' + name + '/' + str(i))
    swaps = 0
    for i, j in enumerate(sigma):
        ia = {pi[owner]: sign for owner, sign in a['incidence'][i]}
        ib = {owner: sign * orientation[i] for owner, sign in b['incidence'][j]}
        C.require(ia == ib, 'Private face map/orientation differs from authenticated incidence')
        left, right = private_a['physical_faces'][i], private_b['physical_faces'][j]
        mapped = [pi[left[0]], None if left[1] is None else pi[left[1]]]
        if mapped != right[:2]:
            C.require(mapped[1] is not None and mapped[::-1] == right[:2],
                'Private mapped face owner coverage differs')
            swaps += 1
        # A saved amount is outward from its FIRST owner. Convert through the
        # native area orientation and both actual first-owner incidence signs.
        sign = a['incidence'][i][0][1] * orientation[i] * b['incidence'][j][0][1]
        if C.canonical(_private_sign(left[2], sign)) != C.canonical(right[2]):
            differences.append('/physical_faces/' + str(i))
        if C.canonical(private_a['face_ids'][i]) != C.canonical(private_b['face_ids'][j]):
            differences.append('/face_ids/' + str(i))
    handled = set(PRIVATE_CELL_FIELDS) | {'physical_faces', 'face_ids', 'sources', 'result_id'}
    remaining_a = {key: value for key, value in private_a.items() if key not in handled}
    remaining_b = {key: value for key, value in private_b.items() if key not in handled}
    if C.canonical(remaining_a) != C.canonical(remaining_b):
        for key in sorted(set(remaining_a) | set(remaining_b)):
            if (key not in remaining_a or key not in remaining_b
                    or C.canonical(remaining_a[key]) != C.canonical(remaining_b[key])):
                differences.append('/' + key)
    return dict(coverage='ALL_PRIVATE_FIELDS_EXCEPT_VERIFIED_SOURCES_AND_RESULT_ID',
        exact=not differences, differing_paths=differences,
        mapped_cell_fields=list(PRIVATE_CELL_FIELDS), cell_count=n, face_count=nf,
        face_owner_swaps=swaps, map_source='SAME_RETAINED_AUTHENTICATED_PHYSICAL_MAP',
        canonical_json_type_and_signed_zero_preserved=True)


def _metadata(V, a, b, inventories, component_replay, physical_mapping):
    handled = set(V.CELL_ACCOUNTS) | set(V.SCALARS) | {V.FACE_ACCOUNT, 'cell_ids', 'face_ids'}
    left, right = dict(V._leaves(a['meta'])), dict(V._leaves(b['meta']))
    differences, invariant = [], []
    loaded_paths = {('loaded_dependencies', 'identity'), ('caller_snapshot', 'loaded_dependencies', 'identity'),
                    ('caller_snapshot', 'execution', 'execution_identity')}
    identity_top = {'call_id', 'geometry_id', 'plan_id', 'private_result_id', 'state_id'}
    identity_call = V.PROVENANCE_CALL
    for path in sorted(set(left) | set(right), key=str):
        if path[0] in handled or path[:2] == ('caller_snapshot', 'cell_ids'):
            continue
        if path in left and path in right and C.canonical(left[path]) == C.canonical(right[path]):
            continue
        entry = dict(path='/' + '/'.join(map(str, path)), base=left.get(path), joint=right.get(path))
        source = path[:2] == ('caller_snapshot', 'private_sources')
        identity = (path in loaded_paths or len(path) == 1 and path[0] in identity_top
                    or len(path) == 2 and path[0] == 'caller_snapshot' and path[1] in identity_call
                    or len(path) == 3 and path[:2] == ('caller_snapshot', 'native_origin_signature')
                    and path[2] in V.ORIGIN_IDENTITIES)
        identity_values = (left.get(path), right.get(path))
        exact_identity_tokens = all(type(value) is str and len(value) == 64
            and all(c in '0123456789abcdef' for c in value) for value in identity_values)
        if source or identity and exact_identity_tokens:
            entry['disposition'] = ('EXACT_SELECTED_SOURCE_CORRESPONDENCE' if source else
                                    'EXACT_CAPTURED_AND_NATIVE_VERIFIED_IDENTITY_PREIMAGE')
            differences.append(entry)
        else:
            entry['disposition'] = 'UNAPPROVED_FIELD_DIFFERENCE'
            invariant.append(entry)
    # S1 diagnostics/closed-stage budgets are not sealed output metadata.
    # H3 adds no resource-field exemption. All resource differences above fail.
    private = _private_correspondence(a, b, physical_mapping)
    if not private['exact']:
        invariant.append(dict(path='/private_numerical_preimage', disposition='PRIVATE_SEALED_VALUES_DIFFER'))
    execution_a, execution_b = (bundle['plan14_preimages']['execution'] for bundle in (a, b))
    for key in ('schema', 'code_marshal_format', 'source_inventory_schema', 'backend', 'runtime'):
        if C.canonical(execution_a[key]) != C.canonical(execution_b[key]):
            invariant.append(dict(path='/execution_preimage/' + key,
                                  disposition='UNAPPROVED_EXECUTION_ENVIRONMENT_DIFFERENCE'))
    for key in sorted(V.HEADER_IDENTITIES):
        if a['header'].get(key) != b['header'].get(key):
            values = (a['header'].get(key), b['header'].get(key))
            entry = dict(path='/mesh_header/' + key, base=values[0], joint=values[1])
            if all(type(value) is str and len(value) == 64
                   and all(c in '0123456789abcdef' for c in value) for value in values):
                # Only these specifically named scalar identity fields are
                # translated, after complete per-arm native origin/header
                # verification. A compound source/booked-cell subtree never
                # inherits an exemption for its numerical or policy leaves.
                entry['disposition'] = 'NAMED_SCALAR_HEADER_IDENTITY_BOUND_BY_NATIVE_WITNESS_AND_PHYSICAL_MAP'
                differences.append(entry)
            else:
                entry['disposition'] = 'UNAPPROVED_COMPOUND_OR_NONIDENTITY_HEADER_DIFFERENCE'
                invariant.append(entry)
    output = [component_replay(bundle, inventory) for bundle, inventory in zip((a, b), inventories, strict=True)]
    failures = [dict(arm=index, **row) for index, evidence in enumerate(output) for row in evidence['failures']]
    unresolved = [dict(arm=index, **row) for index, evidence in enumerate(output) for row in evidence['unresolved']]
    return dict(coverage='ALL_LEAVES_PLUS_COMPLETE_PRIVATE_PREIMAGES', provenance_differences=differences,
                resource_differences=[], invariant_differences=invariant, header_provenance_differences=[],
                proof_failures=failures, unresolved_required_evidence=unresolved,
                source_correspondence=_source_correspondence((a, b), inventories), output_components=output,
                private_correspondence=private,
                disposition='Approved exact source/identity translations only; all other fields exact')


def verify_pair(request, request_pin, output, inventories):
    """Offline only: preserve the old numerical checks; replace named trust boundaries."""
    verifier_ref = request['primary']['verifier']
    V = C.load_source('_plan14_retained_numerical_verifier', verifier_ref['path'], verifier_ref['sha256'])
    V._source_check = lambda *args, **kwargs: _source_check(request, inventories, *args, **kwargs)
    original_load = V._load
    original_maps = V._maps
    authenticated_map = {}

    def maps(a, b):
        C.require(not authenticated_map, 'Private comparison requires one physical-map evaluation')
        result = original_maps(a, b)
        authenticated_map.update(a=a, b=b, mapping=tuple(tuple(row) for row in result))
        return result

    def metadata(a, b):
        C.require(authenticated_map.get('a') is a and authenticated_map.get('b') is b,
            'Private comparison is not bound to these authenticated physical bundles')
        return _metadata(V, a, b, inventories, replay, authenticated_map['mapping'])

    def load(directory, index):
        bundle = original_load(directory, index)
        native = V.read_json(Path(directory).parent / ('arm-' + str(index) + '.json'))
        arm = request['arms'][index]
        C.require(native.get('request_sha256') == request_pin and native.get('source_finality') is True
                  and native.get('profile_sha256') == arm['profile']['sha256']
                  and native.get('composition_sha256') == arm['composition']['sha256']
                  and native.get('qualification_fingerprint') == request['qualification_fingerprint']
                  and native.get('source_fixture_sha256') == request['primary']['fixture']['sha256']
                  and native.get('issuer_sha256') == inventories[index]['composition']['helpers']['private_heat_native_issuer_r13.py']
                  and native.get('numerical_kernel_sha256') == inventories[index]['composition']['helpers']['private_heat_forward_kernel_r13.py'],
                  'Native receipt is not bound to the exact requested source/input generation')
        calls = native['ab']['calls']
        C.require(len(calls) == 2 and all(row['workers'] == 6 and row['fallback'] is None for row in calls)
                  and not native['ab']['fallbacks'], 'Required six-worker same-call coverage missing')
        _preimages(V, bundle, native, inventories[index])
        return bundle

    replay = output_component_replay(V, verifier_ref)

    V._load = load
    V._maps = maps
    V._metadata = metadata
    report = V.verify_correspondence(output / 'arm-0', output / 'arm-1')
    if report.get('new_run_verdict') == 'METADATA_DISPOSITION_REQUIRED':
        metadata = report['metadata']
        # All retained differences have already passed the exact named
        # source/preimage checks above. Existing S1/C14 authority suffices;
        # there is no new per-leaf approval round or generic digest exception.
        C.require(not metadata['resource_differences'] and not metadata['invariant_differences']
                  and not metadata['proof_failures'] and not metadata['unresolved_required_evidence'],
                  'Unproved metadata difference cannot be translated')
        report.update(verdict='EXACT_COMPARISON_COMPLETE', new_run_verdict='EXACT_COMPARISON_COMPLETE',
                      exit_code=0, identity_translation_applied=True)
    report.update(schema='atlas.private.plan14.w4-verification.r1', request_sha256=request_pin,
                  scientific_acceptance=False, historical_q10='FAIL', h5a_enabled=False,
                  comparison_generation=[arm['composition'] for arm in request['arms']],
                  retained_numerical_verifier=verifier_ref,
                  adaptation='Exact selected-source/identity preimages; retained physical/array/account/ledger equations')
    report['passed'] = report.get('exit_code') == 0 and report.get('new_run_verdict') == 'EXACT_COMPARISON_COMPLETE'
    report['status'] = report.get('new_run_verdict', 'VERIFY_REFUSE')
    return report
