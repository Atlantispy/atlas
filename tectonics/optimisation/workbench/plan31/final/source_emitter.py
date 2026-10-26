"""Plan31 final source emission and paired-profile assembly.

The final constructor authenticates its literal frozen selection and this module
before calling these functions. This module has no CLI or alternative selection
route. It preserves partial failures and never replaces a generation or fold.
"""
import ast
import copy
import hashlib
from pathlib import Path

HERE = T = TARGET = RUNTIME = OWNED = CONTRACT = PACKET = None
PLAN02_BINDING = None
STAGE = 'plan31:final-generation-n12f-r1'
CONTRACT_PIN = 'c59cb93b495aaac6e5d5c62850a6cfbe1cf8c0934c43b67219b250152563a7d9'
PACKET_PIN = '1f057e4a8a807872bd52cbbdfb402cfba05ad7e1b34ae8007300c897031d406d'


def configure(*, control_root, workspace, plan02_binding):
    """Bind one explicit caller-owned control set; no search, defaults or runtime activation."""
    global HERE, T, TARGET, RUNTIME, OWNED, CONTRACT, PACKET, PLAN02_BINDING
    require(HERE is None, 'construction context already bound')
    root, workspace = Path(control_root), Path(workspace)
    require(root.is_absolute() and workspace.is_absolute(), 'explicit absolute construction roots required')
    require(type(plan02_binding) is dict and set(plan02_binding) == {'path', 'sha256'}
            and Path(plan02_binding['path']).is_absolute() and plan02_binding['sha256'] ==
            '509936760484459ce1f41aca15965d33dab5e2be26a2eae18df63bf5c7d44f60',
            'explicit accepted Plan02 component binding required')
    HERE, T = root, workspace
    TARGET, RUNTIME, OWNED = T/'ac/n12f-r1', T/'ac/n12f-run-r1', HERE/'integration-n12f-r1'
    CONTRACT, PACKET = HERE/'n12f-producer-contract-r3.json', HERE.parent/'n9-receiving-r4-correction-r1/ACTUAL-CONSTRUCTION.json'
    PLAN02_BINDING = dict(plan02_binding)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def rel(path):
    return Path(path).relative_to(T).as_posix()


def reference(path, raw):
    return {'path': str(Path(path)), 'sha256': sha(raw)}


def refuse_metadata(value):
    if isinstance(value, dict):
        require('purpose' not in value, 'purpose presence refuses final admission')
        for key, child in value.items():
            require(not isinstance(key, str) or not key.casefold().startswith('plan31:rehearsal-'),
                    'rehearsal key refuses final admission')
            refuse_metadata(child)
    elif isinstance(value, list):
        for child in value:
            refuse_metadata(child)
    elif isinstance(value, str):
        require(not value.casefold().startswith('plan31:rehearsal-'), 'rehearsal value refuses final admission')


def source_path(C, root, name):
    path = C.prospective(root, name)
    require(len(str(path)) + 8 < 260, 'pre-write MAX_PATH allowance exceeded: ' + str(path))
    return path


def component_payload(inputs, U, *, component_binding, parent_arm):
    """Receive the complete actual component output; reuse unchanged component verifiers."""
    report = inputs.doc(Path(component_binding['path']), component_binding['sha256'])
    require(report['schema'] == 'plan31.final-shared-components.r1'
            and report['status'] == 'ACTUAL_COMPONENT_COMPOSITION_NOT_FINAL_FREEZE'
            and report['arm'] == parent_arm and report['native_members'] == 287
            and report['helper_members'] == 417 and report['private_A1_selected'] is False
            and report['S1A_full_B_selected'] is True, 'actual selected component disposition differs')
    for path, pin in report['source_pins'].items():
        inputs.raw(Path(path), pin)
    packet = inputs.doc(PACKET, PACKET_PIN)
    parent = packet['arms'][parent_arm]
    ids = parent['identities']
    require(report['parent_composition_sha256'] == ids['composition_sha256'], 'component parent differs')
    base, reviewed, native, helpers = U.composition(inputs, Path(parent['target']), ids['composition_sha256'],
        Path(ids['reviewed_inputs']['path']), ids['reviewed_inputs']['sha256'])
    expected = {area+'/'+name: pin for area, rows in [('src', native), ('helpers', helpers)]
                for name, pin in rows.items()}
    require(len(expected) == 696, 'complete immutable corrected replay parent required')
    for name, row in report['changes'].items():
        require(expected.get(name) == row['before'], 'component predecessor differs: '+name)
        expected[name] = row['after']
    root = Path(report['source_root'])
    require(root.resolve() == (HERE.parent/'final-components-r1'/parent_arm).resolve(),
            'component source outside explicit owned route')
    require(set(U.inventory(root, inputs, expected)) == set(expected), 'complete actual component membership differs')
    inputs.inventories.append((root, set(expected)))
    payload = {name: inputs.raw(root/name, pin) for name, pin in expected.items()}
    require(len(payload) == 704, 'complete actual 287-native/417-helper component tree required')
    return parent, base, reviewed, payload, report


def derive_sources(C, U, inputs, *, selection_binding, constructor_binding):
    """Build acyclic source metadata from an actual authenticated final selection."""
    contract = inputs.doc(CONTRACT, CONTRACT_PIN)
    inputs.raw(Path(constructor_binding['path']), constructor_binding['sha256'])
    require(Path(constructor_binding['path']).resolve() == Path(contract['constructor_path']).resolve(),
            'exact final constructor required')
    require(Path(selection_binding['path']).resolve() == Path(contract['selection_path']).resolve(),
            'exact literal-bound final selection required')
    selected = inputs.doc(Path(selection_binding['path']), selection_binding['sha256'])
    refuse_metadata(selected)
    for name, expected in contract['selection_admission']['required_values'].items():
        require(type(selected.get(name)) is type(expected) and selected[name] == expected,
                'exact final selection field required: '+name)
    contract_ref = reference(CONTRACT, inputs.raw(CONTRACT, CONTRACT_PIN))
    require(selected['producer_contract'] == contract_ref and selected['parent_arm'] in ('baseline', 'width'),
            'final producer contract/selected arm differs')
    authority = contract['destination_authority']
    inputs.doc(Path(authority['path']), authority['sha256'])
    parent, base, prior, payload, components = component_payload(inputs, U,
        component_binding=selected['component_composition'], parent_arm=selected['parent_arm'])
    require(Path(selected['base']).resolve() == Path(parent['target']).resolve()
            and selected['base_composition_sha256'] == parent['identities']['composition_sha256'],
            'actual final parent binding differs')
    require(type(selected['dispositions']) is dict and selected['dispositions']
            and all(type(v) is dict and type(v.get('reason')) is str and v['reason'].strip()
                    for v in selected['dispositions'].values()), 'explicit reasoned final dispositions required')
    require(selected['policy']['evidence_root'] == '.', 'explicit contained final evidence root required')
    replay_ref = selected['replay_disposition']
    inputs.raw(Path(replay_ref['path']), replay_ref['sha256'])
    original = dict(payload)
    for name, row in selected['additional_rows'].items():
        source_path(C, TARGET, name)
        require(name.startswith(('src/atlas_tectonics/', 'helpers/')) and set(row) ==
                {'path', 'sha256', 'before_sha256', 'kind', 'diff', 'review', 'reason'},
                'closed separately selected receiving delta required: '+name)
        require(type(row['reason']) is str and row['reason'].strip()
                and row['before_sha256'] == (sha(payload[name]) if name in payload else None),
                'selected receiving delta predecessor/reason differs: '+name)
        after = inputs.raw(Path(row['path']), row['sha256'])
        inputs.raw(Path(row['review']['path']), row['review']['sha256'])
        if row['kind'] == 'diff':
            diff = inputs.raw(Path(row['diff']['path']), row['diff']['sha256'])
            require(name in payload and C.apply_diff(payload[name], diff, name) == after,
                    'selected receiving delta does not derive: '+name)
        else:
            require(row['kind'] in ('replace', 'add') and row['diff'] is None
                    and (row['kind'] == 'add') == (name not in payload), 'selected receiving row kind differs')
        require(after != payload.get(name), 'unchanged receiving row declared changed')
        payload[name] = after
    native = {name[4:]: sha(raw) for name, raw in payload.items() if name.startswith('src/')}
    helpers = {name[8:]: sha(raw) for name, raw in payload.items() if name.startswith('helpers/')}
    require(len(native) == 287 and len(helpers) == selected['helper_members']
            and len(native)+len(helpers) == len(payload), 'exact final source coverage differs')
    for name, raw in payload.items():
        source_path(C, TARGET, name)
        if name.endswith('.py'):
            ast.parse(raw, filename=name)
    require(len({name.casefold() for name in payload}) == len(payload), 'case-insensitive source collision')
    ids = parent['identities']
    old = inputs.doc(Path(parent['runtime'])/'manifest.json', ids['manifest_sha256'])
    old_profile = inputs.doc(Path(parent['runtime'])/'fresh-profile.json', ids['profile_sha256'])
    old_prefix = rel(Path(parent['target']))+'/'
    external = {name: pin for name, pin in old['data_only'].items() if not name.startswith(old_prefix)}
    for name, pin in external.items():
        inputs.raw(U.member(T, name), pin)
    bootstrap = inputs.raw(Path(ids['bootstrap']['path']), ids['bootstrap']['sha256'])
    for before, after in [(f'REAL_ROOT = T / "{rel(Path(parent["target"]))}"', f'REAL_ROOT = T / "{rel(TARGET)}"'),
                          ('REAL_COUNTS = (287, 409)', f'REAL_COUNTS = (287, {len(helpers)})')]:
        require(bootstrap.count(before.encode()) == 1, 'unique actual bootstrap anchor required: '+before)
        bootstrap = bootstrap.replace(before.encode(), after.encode())
    ast.parse(bootstrap)
    evidence_names = list(selected['policy']['evidence_sources'])
    validate_destination_names(evidence_names)
    evidence_outputs = {}
    for name, binding in selected['policy']['evidence_sources'].items():
        destination = source_path(C, RUNTIME, 'evidence/'+name)
        evidence_outputs[destination] = inputs.raw(Path(binding['path']), binding['sha256'])
    stage = {'generation': 'n12f-r1', 'selection_path': selection_binding['path'],
             'selection_sha256': selection_binding['sha256'], 'producer_contract': contract_ref,
             'parent_composition_sha256': ids['composition_sha256'], 'parent_arm': selected['parent_arm'],
             'observer_reissue_required': True, 'fold_not_performed': True}
    reviewed = copy.deepcopy(prior)
    require(STAGE not in reviewed['staged'], 'final stage already exists')
    reviewed['staged'][STAGE] = stage
    reviewed.update(target=TARGET.name, target_root=str(TARGET), outputs=native)
    all_changes = {**components['changes'], **{name: {'before': sha(original[name]) if name in original else None,
                    'after': sha(payload[name])} for name in selected['additional_rows']}}
    for name, row in all_changes.items():
        if name.startswith('helpers/'):
            reviewed['helpers'][name[8:]] = {'path': str(Path(components['source_root'])/name), 'sha256': row['after']}
            if name in selected['additional_rows']:
                reviewed['helpers'][name[8:]]['path'] = selected['additional_rows'][name]['path']
        reviewed['stages'].append({'module': Path(name).name, 'stage': STAGE,
                                  'input_sha256': row['before'] or row['after'],
                                  'output_sha256': row['after'], 'note': 'Explicit selected final receiving source'})
    for path, pin in inputs.pins.items():
        require(path not in reviewed['files'] or reviewed['files'][path] == pin,
                'historical construction input conflict: '+path)
        reviewed['files'][path] = pin
    reviewed_path = OWNED/'reviewed-inputs.json'
    reviewed_raw = U.canonical(reviewed)
    composition = copy.deepcopy(base)
    composition.update(root=str(TARGET), outputs=native, helpers=helpers, staged=reviewed['staged'],
        stages=reviewed['stages'], reviewed_inputs=str(reviewed_path), reviewed_inputs_sha256=sha(reviewed_raw))
    composition_raw = U.canonical(composition)
    files = {rel(TARGET/name): sha(raw) for name, raw in payload.items() if name.endswith('.py')}
    data = {**external, **{rel(TARGET/name): sha(raw) for name, raw in payload.items() if not name.endswith('.py')},
            rel(TARGET/'composition.json'): sha(composition_raw)}
    def translate(name):
        require(name.startswith(old_prefix), 'untranslatable fixture binding')
        return rel(TARGET)+'/'+name[len(old_prefix):]
    fixture = old['fixture_source_map']
    manifest = dict(old, files=files, data_only=data,
        source_hashes={name: pin for name, pin in native.items() if name.endswith('.py')},
        fixture_source_map={'schema': fixture['schema'],
            'modules': {name: translate(path) for name, path in fixture['modules'].items()},
            'by_path': {name: translate(path) for name, path in fixture['by_path'].items()}},
        composition={'root': rel(TARGET), 'composition_json': rel(TARGET/'composition.json'),
                     'composition_sha256': sha(composition_raw), 'frozen': False,
                     'import_root_order': [rel(TARGET/'helpers')]})
    require(not files.keys() & data.keys() and manifest['completed_query_store'] == 'files',
            'complete disjoint final manifest with explicit files query-store required')
    for value in (composition, reviewed, manifest):
        refuse_metadata(value)
    outputs = {TARGET/name: raw for name, raw in payload.items()}
    outputs.update(evidence_outputs)
    outputs.update({reviewed_path: reviewed_raw, TARGET/'composition.json': composition_raw,
                    RUNTIME/'manifest.json': U.canonical(manifest), OWNED/'bootstrap_native.py': bootstrap})
    inputs.recheck()
    return {'selected': selected, 'selection': selection_binding, 'constructor': constructor_binding,
            'producer_contract': contract_ref, 'parent': parent, 'payload': payload,
            'old_profile': old_profile, 'composition': composition, 'manifest': manifest,
            'reviewed_inputs': reference(reviewed_path, reviewed_raw),
            'bootstrap': reference(OWNED/'bootstrap_native.py', bootstrap),
            'source_outputs': outputs, 'changes': all_changes}


def validate_destination_names(names):
    # Validate the raw list before WindowsPath dict keys can collapse aliases.
    require(all(type(name) is str and name for name in names), 'explicit destination names required')
    require(len({name.casefold() for name in names}) == len(names),
            'case-insensitive output destination collision')


def validate_source_outputs(C, U, inputs, bundle):
    """Authenticate complete planned output coverage before the first write."""
    outputs = bundle['source_outputs']
    require(type(outputs) is dict and all(isinstance(p, Path) and type(raw) is bytes
            for p, raw in outputs.items()), 'complete ordinary source output plan required')
    source_items = [(source_path(C, TARGET, name), raw) for name, raw in bundle['payload'].items()]
    metadata_paths = [TARGET/'composition.json', RUNTIME/'manifest.json',
                      Path(bundle['reviewed_inputs']['path']), Path(bundle['bootstrap']['path'])]
    require(metadata_paths[2:] == [OWNED/'reviewed-inputs.json', OWNED/'bootstrap_native.py'],
            'exact owned source metadata destinations required')
    evidence_items = [(source_path(C, RUNTIME, 'evidence/'+name), binding)
                      for name, binding in bundle['selected']['policy']['evidence_sources'].items()]
    expected_paths = [path for path, _ in source_items] + metadata_paths + [path for path, _ in evidence_items]
    validate_destination_names([str(path) for path in expected_paths])
    require(set(outputs) == set(expected_paths) and len(outputs) == len(expected_paths),
            'complete source/metadata output coverage differs')
    for path, raw in source_items:
        require(outputs[path] == raw, 'planned source bytes differ: '+str(path))
    require(outputs[TARGET/'composition.json'] == U.canonical(bundle['composition'])
            and outputs[RUNTIME/'manifest.json'] == U.canonical(bundle['manifest']),
            'planned composition/manifest bytes differ')
    for name in ('reviewed_inputs', 'bootstrap'):
        ref = bundle[name]
        require(sha(outputs[Path(ref['path'])]) == ref['sha256'], 'planned metadata binding differs: '+name)
    for path, binding in evidence_items:
        require(outputs[path] == inputs.raw(Path(binding['path']), binding['sha256']),
                'planned contained evidence differs')
    return outputs


def write_sources(C, U, inputs, bundle):
    """Only the final constructor calls this after required implementation review."""
    roots = (TARGET, RUNTIME, OWNED)
    for root in roots:
        require(not U.exists(root), 'preserve existing/partial generation: '+str(root))
        U.ordinary(root.parent, directory=True)
    outputs = validate_source_outputs(C, U, inputs, bundle)
    for path in outputs:
        require(any(path.is_relative_to(root) for root in roots), 'output outside owned final roots')
        require(len(str(path)) + 8 < 260, 'pre-write MAX_PATH allowance exceeded')
        for source in inputs.pins:
            require(not Path(source).is_relative_to(path) and not path.is_relative_to(Path(source)),
                    'construction source/output overlap')
    inputs.recheck()
    for path, raw in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        U.ordinary(path.parent, directory=True)
        with path.open('xb') as stream:
            stream.write(raw)
    inputs.recheck()
    for path, raw in outputs.items():
        require(U.ordinary(path).read_bytes() == raw, 'emitted final source/metadata differs')
    U.composition(U.Inputs(), TARGET, sha(outputs[TARGET/'composition.json']),
                  Path(bundle['reviewed_inputs']['path']), bundle['reviewed_inputs']['sha256'])


def finish_profiles(U, S, inputs, bundle):
    """Measure actual emitted identity and connect both actual Plan02 profile consumers."""
    manifest_ref = {'path': rel(RUNTIME/'manifest.json'), 'sha256': sha(bundle['source_outputs'][RUNTIME/'manifest.json'])}
    _, native, native_digest = S.validate_source_closure(inputs, workspace=T, native_root=rel(TARGET/'src'),
        manifest_binding=manifest_ref, profile_paths=list(S.FINAL_PROFILE_PATHS.values()),
        expected_native_members=287, inventory=U.inventory)
    measurement, current, probe_process = S.capture_final_identity(inputs, workspace=T,
        manifest_binding=manifest_ref, source_hashes=native)
    require(current['native_source_digest'] == native_digest, 'actual final identity/source closure differs')
    historical, limits, compression = S.historical_policy_inputs(inputs, workspace=T)
    policy_selection = bundle['selected']['policy']
    evidence = {rel(RUNTIME/'evidence'/name): binding['sha256']
                for name, binding in policy_selection['evidence_sources'].items()}
    _, policy_raw = S.build_policy(inputs, workspace=T, evidence_root='.', historical=historical,
        current=current, reviewed_changes=policy_selection['reviewed_changes'], evidence=evidence)
    def emit(path, raw):
        require(not U.exists(path), 'preserve final metadata: '+str(path))
        U.ordinary(path.parent, directory=True)
        with path.open('xb') as stream:
            stream.write(raw)
        require(U.ordinary(path).read_bytes() == raw, 'emitted metadata differs')
        return reference(path, raw)
    emit(RUNTIME/'execution-identity.json', U.canonical(measurement))
    emit(OWNED/'identity-probe-process.json', U.canonical(probe_process))
    policy_ref = emit(RUNTIME/'runtime-policy.json', policy_raw)
    layout = S.profile_layout(inputs, workspace=T, payload=bundle['payload'],
        parent_fresh_binding={'path': str(Path(bundle['parent']['runtime'])/'fresh-profile.json'),
                              'sha256': bundle['parent']['identities']['profile_sha256']})
    component = S.authenticate_plan02(inputs, binding=PLAN02_BINDING)
    fresh, prepared = S.final_profile_documents(inputs, component, workspace=T, layout=layout,
        manifest_binding=manifest_ref, policy_binding={'path': rel(RUNTIME/'runtime-policy.json'), 'sha256': policy_ref['sha256']},
        policy_raw=policy_raw, store_limits=limits, compression=compression)
    refuse_metadata(fresh)
    refuse_metadata(prepared)
    fresh_ref = emit(RUNTIME/'fresh-profile.json', U.canonical(fresh))
    prepared_ref = emit(RUNTIME/'prepared-profile.json', U.canonical(prepared))
    inputs.recheck()
    record = {'schema': 'atlas.private.plan31.final-generation.r1', 'status': 'PREPARED_SOURCE_NOT_QUALIFIED',
        'generation': 'n12f-r1', 'stage': STAGE, 'pending': [], 'completed_query_store': 'files',
        'selection': bundle['selection'], 'producer_contract': bundle['producer_contract'],
        'composition_sha256': sha(bundle['source_outputs'][TARGET/'composition.json']),
        'manifest_sha256': manifest_ref['sha256'], 'profile_sha256': fresh_ref['sha256'],
        'prepared_profile': prepared_ref, 'reviewed_inputs': bundle['reviewed_inputs'], 'bootstrap': bundle['bootstrap'],
        'source_inputs': dict(inputs.pins), 'constructor_sha256': bundle['constructor']['sha256'],
        'native_outputs': 287, 'helper_outputs': len(bundle['composition']['helpers']),
        'fold_not_performed': True, 'observer_reissue_required': True, 'execution_authority': False,
        'interval_authority': False, 'holds_released': False, 'default_changed': False, 'scientific_acceptance': False}
    refuse_metadata(record)
    derivation_ref = emit(RUNTIME/'derivation.json', U.canonical(record))
    receipt = dict(record, derivation_sha256=derivation_ref['sha256'], input_finality=True, output_finality=True)
    receipt_ref = emit(OWNED/'BUILD-RESULT.json', U.canonical(receipt))
    manifest = bundle['manifest']
    config = S.paired_config(component, construction_receipt=receipt_ref, derivation=derivation_ref,
        composition=reference(TARGET/'composition.json', bundle['source_outputs'][TARGET/'composition.json']),
        fresh_profile=fresh_ref, prepared_profile=prepared_ref,
        fresh_runner={'path': str(TARGET/'helpers/run_fresh_interval.py'),
                      'sha256': manifest['files'][rel(TARGET/'helpers/run_fresh_interval.py')]},
        prepared_runner={'path': str(TARGET/'helpers/run_prepared_restart.py'),
                         'sha256': manifest['files'][rel(TARGET/'helpers/run_prepared_restart.py')]},
        compatibility_policy=policy_ref, prepared_record=prepared)
    config_ref = emit(OWNED/'prepared-construction.json', U.canonical(config))
    inputs.recheck()
    return {'receipt': receipt_ref, 'derivation': derivation_ref, 'fresh_profile': fresh_ref,
            'prepared_profile': prepared_ref, 'policy': policy_ref, 'config': config_ref,
            'execution_identity': current['execution_identity'], 'native_source_digest': native_digest,
            'scientific_acceptance': False, 'fold_not_performed': True}
