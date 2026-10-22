"""Plan/apply one prepared selected-heat-driver successor; no import construction.

Plan writes predicted bytes and a complete pin map only under r23/plan-r1.
Apply requires that exact plan SHA and rederives every byte before creating
fresh permanent roots. Neither mode imports scientific sources, qualifies a
runtime, enables H3/defaults, runs a workload or changes queue/hold state.
Every invocation still requires its own externally source-bound authority.
"""
import argparse
import ast
import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = Path('C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace')
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
BASE = T / 'ac/p15c-r3'
OLD_RUNTIME = T / 'ac/p15-run-r3'
TARGET = T / 'ac/p15c-r4'
RUNTIME = T / 'ac/p15-run-r4'
OWNED = HERE / 'integration'
PLAN_ROOT = HERE / 'plan-r1'
PLAN = PLAN_ROOT / 'PLAN.json'
UTILITY = W / 'work/plan11/integration-r1/build_profile.py'
UTILITY_PIN = '171915e6871740755afdd54528b9a9fc2dfd236a0b60ae427175ab70d3f7492e'
PARENT_CONSTRUCTOR = W / 'work/plan15/r17/construct_successor.py'
PARENT_CONSTRUCTOR_PIN = '164bd54ee3fda4928b69aea06fcad5334decd6b78bf96ae1b914cfe5d85f660d'
BASE_PIN = 'f3b2f61da50dcb4e14ce0ec099cebd127a46df8b7a4a9c4c1dd4cf41d19dce4b'
PROFILE_PIN = '9d769e0355b66093b3112a684173603079b147a9f25ff0173a67dbe727f767aa'
MANIFEST_PIN = '3f8d8c5ccb3a438cb4bf472af224daa46dacf8c234d6758887176305abe29685'
DERIVATION_PIN = '3739815813afec814af8022d8e2703a6cc266c8a2c6921da962419acf62ca192'
MEMBER = 'helpers/fresh_interval_driver.py'
BEFORE = '68cf55cd270bae7d09d59bd4b5a7d47f2e75f45a390e88d47a29b68b8a266baf'
AFTER = '9103629802281dd55d4f0d1541eaaf9fa369e841fdc0fef0b87db0ce19b39640'
DELTA = HERE / 'DRIVER-DELTA.json'
CANDIDATE = HERE / 'fresh_interval_driver.py'
PARENT_RECEIPT = W / 'work/plan15/r17/integration/BUILD-RESULT.json'
PARENT_RECEIPT_PIN = '5380e52fb5c8b5903012de7604a8b342c191d173037fdc2498b6e0aa5aabb373'
DECISION = HERE / 'SOURCE-DECISION.md'
SELECTION_EVIDENCE = {
    'owned': dict(path=(W / 'work/plan15/r22/sweep-owned-r1/result.json').as_posix(),
                  sha256='8fb63d9b99fb6630b59ac8e199703855f3ad89ae9d888279d6bc7f3c0174979e'),
    'report': dict(path=(W / 'work/plan15/r22/MEASURED-RESULT.md').as_posix(),
                   sha256='25bb7dafa9bd1b1461094aed87f6872ec15c443a055684ecc327d4dec6e2f81e'),
    'extract': dict(path=(W / 'work/plan15/r22/ACTUAL-EVIDENCE.json').as_posix(),
                    sha256='2bb7fb78341090cffddd5c43146334813bf3aa35c10eefb91db1cf574146aa7d'),
}
PRESERVED_HELPERS = {
    'helpers/private_heat_functionals_parallel_r1.py':
        '711928938eeb3dd032721f8c7159cdb91bddab9eb29fc8924cf72e6064bc8f60',
    'helpers/private_heat_compiled_dot_r1.py':
        'e0be3a309c8ab9ccee3c1a36525f72da27e816b1ce984651dbd85a3c072a14aa',
    'helpers/private_heat_certification_kernel_r1.py':
        '4099a297a8423a6213761ab4f305d442dda647ec6c7a46ee4d4734d253041f71',
}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(raw):
    return sha256(raw).hexdigest()


def rel(path):
    return path.relative_to(T).as_posix()


def utility():
    raw = UTILITY.read_bytes()
    require(digest(raw) == UTILITY_PIN, 'Qualified metadata utility changed')
    spec = importlib.util.spec_from_file_location('plan15_metadata', UTILITY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ordinary(HERE, directory=True)
    module.ordinary(T / 'ac', directory=True)
    return module


def fresh(U):
    for path in (TARGET, RUNTIME, OWNED):
        require(not U.exists(path), 'Preserve existing/partial target: ' + str(path))


def validate_delta(delta, inputs):
    """Bind the selected driver only; inherit earlier native-policy records intact."""
    false_fields = ('numerical_changes', 'global_worker_default_changes', 'worker_lifecycle_protocol_changes',
                    'ipc_transport_changes', 'execution_authority', 'default_changed',
                    'runtime_policy_adopted', 'programme_adopted', 'whole_interval_performance_claim')
    counts = dict(source_members=634, native_members=239, helper_members=395,
                  changed_members=1, preserved_members=633)
    fields = {'schema', 'status', 'parent_composition_sha256', 'parent_profile_sha256',
              'parent_manifest_sha256', 'parent_derivation_sha256', 'replacement',
              'coordinator_decision', 'selection_evidence', 'scope', 'H3',
              'selected_driver_workers', 'global_parallel_default_workers',
              'driver_worker_configuration_changes', 'prepared_artifact_selection',
              *false_fields, *counts}
    require(type(delta) is dict and set(delta) == fields, 'Different selected-driver delta schema fields')
    require(delta['schema'] == 'plan15.selected-driver-delta.r1'
            and delta['status'] == 'SOURCE_ONLY_NOT_QUALIFIED'
            and delta['parent_composition_sha256'] == BASE_PIN
            and delta['parent_profile_sha256'] == PROFILE_PIN
            and delta['parent_manifest_sha256'] == MANIFEST_PIN
            and delta['parent_derivation_sha256'] == DERIVATION_PIN
            and delta['replacement'] == dict(member=MEMBER, before=BEFORE, after=AFTER,
                                             source=CANDIDATE.as_posix()), 'Different prepared driver selection')
    require(all(type(delta[key]) is int and delta[key] == value for key, value in counts.items())
            and type(delta['scope']) is str and bool(delta['scope'].strip()), 'Different driver scope/counts')
    require(delta['H3'] == 'CANDIDATE_NOT_ENABLED'
            and type(delta['selected_driver_workers']) is int and delta['selected_driver_workers'] == 8
            and type(delta['global_parallel_default_workers']) is int and delta['global_parallel_default_workers'] == 6
            and delta['driver_worker_configuration_changes'] is True
            and delta['prepared_artifact_selection'] is True
            and all(delta[key] is False for key in false_fields), 'Prepared driver authority differs')
    ref = delta['coordinator_decision']
    require(type(ref) is dict and set(ref) == {'path', 'sha256'}
            and ref['path'] == DECISION.as_posix() and type(ref['sha256']) is str
            and len(ref['sha256']) == 64 and all(c in '0123456789abcdef' for c in ref['sha256']),
            'Different prepared driver decision reference')
    require(delta['selection_evidence'] == SELECTION_EVIDENCE, 'Different completed schedule evidence')
    refs = [(DECISION, ref['sha256']),
        *((Path(ref['path']), ref['sha256']) for ref in SELECTION_EVIDENCE.values())]
    for path, pin in refs:
        inputs.raw(path, pin)


def derive(U):
    """Reuse the qualified Plan15 constructor's inventories and transformations."""
    fresh(U)
    inputs = U.Inputs()
    inputs.raw(UTILITY, UTILITY_PIN)
    inputs.raw(PARENT_CONSTRUCTOR, PARENT_CONSTRUCTOR_PIN)
    inputs.raw(PARENT_RECEIPT, PARENT_RECEIPT_PIN)
    inputs.raw(Path(__file__).resolve(), digest(Path(__file__).read_bytes()))
    base = inputs.doc(BASE / 'composition.json', BASE_PIN)
    prior_path, prior_pin = Path(base['reviewed_inputs']), base['reviewed_inputs_sha256']
    base, prior, native, helpers = U.composition(inputs, BASE, BASE_PIN, prior_path, prior_pin)
    require((len(native), len(helpers)) == (239, 395), 'Exact 634-member parent required')
    baseline = {area + '/' + name: inputs.raw(BASE / area / name, pin)
                for area, rows in (('src', native), ('helpers', helpers)) for name, pin in rows.items()}
    require(len(baseline) == 634 and helpers[Path(MEMBER).name] == BEFORE, 'Parent driver/membership differs')
    require(all(digest(baseline[name]) == pin for name, pin in PRESERVED_HELPERS.items()),
            'Parent PAR/H3/certification source differs')
    delta_raw = DELTA.read_bytes()
    delta = inputs.doc(DELTA, digest(delta_raw))
    validate_delta(delta, inputs)
    candidate = inputs.raw(CANDIDATE, AFTER)
    ast.parse(candidate)
    payload = dict(baseline)
    payload[MEMBER] = candidate
    changed = {name for name in payload if payload[name] != baseline[name]}
    require(changed == {MEMBER} and all(payload[name] == baseline[name] for name in baseline if name != MEMBER),
            'Undeclared source change')
    require(all(digest(payload[name]) == pin for name, pin in PRESERVED_HELPERS.items()),
            'Successor PAR/H3/certification source differs')

    old = inputs.doc(OLD_RUNTIME / 'manifest.json', MANIFEST_PIN)
    profile = inputs.doc(OLD_RUNTIME / 'fresh-profile.json', PROFILE_PIN)
    derived = inputs.doc(OLD_RUNTIME / 'derivation.json', DERIVATION_PIN)
    require(derived['composition_sha256'] == BASE_PIN and derived['manifest_sha256'] == MANIFEST_PIN
            and derived['profile_sha256'] == PROFILE_PIN
            and derived['reviewed_inputs'] == dict(path=str(prior_path), sha256=prior_pin),
            'Parent derivation differs')
    require(set(old) == {'files', 'source_hashes', 'data_only', 'completed_query_store', 'composition'}
            and old['completed_query_store'] == base['completed_query_store'] == 'files', 'Parent manifest differs')
    roots = profile['import_roots']
    require(profile['workspace'] == str(T) and profile['native_root'] == rel(BASE / 'src')
            and roots[0] == rel(BASE / 'helpers') and len(roots) == 2
            and profile['schema'] == 'atlas.fresh-interval-profile.v1' and len(profile['modules']) == 21
            and profile['advance_driver'] == dict(module='fresh_interval_driver', path=rel(BASE / MEMBER), sha256=BEFORE)
            and profile['source_manifest'] == dict(path=rel(OLD_RUNTIME / 'manifest.json'), sha256=MANIFEST_PIN),
            'Parent actual profile differs')
    require(old['composition'] == dict(root=rel(BASE), composition_json=rel(BASE / 'composition.json'),
            composition_sha256=BASE_PIN, frozen=False, import_root_order=roots), 'Parent manifest roots differ')
    require(old['source_hashes'] == {name: pin for name, pin in native.items() if name.endswith('.py')},
            'Parent native source inventory differs')
    owned_code = {rel(BASE / name): digest(raw) for name, raw in baseline.items() if name.endswith('.py')}
    owned_data = {rel(BASE / name): digest(raw) for name, raw in baseline.items() if not name.endswith('.py')}
    owned_data[rel(BASE / 'composition.json')] = BASE_PIN
    external_code = {name: pin for name, pin in old['files'].items() if name not in owned_code}
    external_data = {name: pin for name, pin in old['data_only'].items() if name not in owned_data}
    require((len(external_code), len(external_data)) == (14, 104)
            and old['files'] == {**external_code, **owned_code}
            and old['data_only'] == {**external_data, **owned_data}
            and not set(old['files']) & set(old['data_only']), 'Parent actual profile closure differs')
    for name, pin in {**old['files'], **old['data_only']}.items():
        require('bridge' not in Path(name).parts, 'Excluded bridge path')
        inputs.verify(U.member(T, name), pin)
    require(all(name in old['files'] for name in (*profile['modules'].values(), profile['advance_driver']['path']))
            and old['files'][profile['advance_driver']['path']] == profile['advance_driver']['sha256'],
            'Parent profile helper binding incomplete')

    boot = inputs.raw(Path(derived['bootstrap']['path']), derived['bootstrap']['sha256'])
    old_root = ('REAL_ROOT = T / "' + rel(BASE) + '"').encode()
    require(boot.count(old_root) == 1, 'Unique inherited bootstrap root required')
    boot = boot.replace(old_root, ('REAL_ROOT = T / "' + rel(TARGET) + '"').encode())
    ast.parse(boot)
    new_helpers = {name: digest(payload['helpers/' + name]) for name in helpers}
    require('plan15_selected_driver' not in base['staged'], 'Preserve an existing selected-driver record')
    selected = dict(delta=dict(path=str(DELTA), sha256=digest(delta_raw)), **copy.deepcopy(delta))
    reviewed = copy.deepcopy(prior)
    reviewed.update(target=TARGET.name, target_root=str(TARGET), outputs=native,
        staged=dict(base['staged'], plan15_selected_driver=selected))
    reviewed['helpers'][Path(MEMBER).name] = dict(path=str(CANDIDATE), sha256=AFTER)
    reviewed['stages'].append(dict(module=Path(MEMBER).name, stage='plan15:prepared-selected-heat-driver',
        input_sha256=BEFORE, output_sha256=AFTER,
        note='Prepared driver selects8 heat workers and retains first-pass report; live programme/default not adopted'))
    for name, pin in inputs.pins.items():
        require(name not in reviewed['files'] or reviewed['files'][name] == pin, 'Historical input conflict')
        reviewed['files'][name] = pin
    reviewed_path = OWNED / 'reviewed-inputs.json'
    reviewed_raw = U.canonical(reviewed)
    composition = copy.deepcopy(base)
    composition.update(root=str(TARGET), helpers=new_helpers, staged=reviewed['staged'], stages=reviewed['stages'],
        reviewed_inputs=str(reviewed_path), reviewed_inputs_sha256=digest(reviewed_raw))
    composition_raw = U.canonical(composition)
    files = {**external_code, **{rel(TARGET / name): digest(raw) for name, raw in payload.items() if name.endswith('.py')}}
    data = {**external_data, **{rel(TARGET / name): digest(raw) for name, raw in payload.items() if not name.endswith('.py')},
            rel(TARGET / 'composition.json'): digest(composition_raw)}
    require(len(files) == len(old['files']) and len(data) == len(old['data_only'])
            and not set(files) & set(data), 'Successor closure membership changed')

    def translate(name):
        return rel(TARGET) + name[len(rel(BASE)):] if name.startswith(rel(BASE) + '/') else name

    new_roots = [translate(name) for name in roots]
    manifest = dict(old, files=files, data_only=data,
        composition=dict(root=rel(TARGET), composition_json=rel(TARGET / 'composition.json'),
            composition_sha256=digest(composition_raw), frozen=False, import_root_order=new_roots))
    manifest_raw = U.canonical(manifest)
    successor = copy.deepcopy(profile)
    successor.update(native_root=rel(TARGET / 'src'), import_roots=new_roots,
        modules={name: translate(value) for name, value in profile['modules'].items()},
        advance_driver=dict(profile['advance_driver'], path=translate(profile['advance_driver']['path']), sha256=AFTER),
        source_manifest=dict(path=rel(RUNTIME / 'manifest.json'), sha256=digest(manifest_raw)),
        output_directory=str(RUNTIME / 'attempt-r1'), store_directory=str(RUNTIME / 'store-r1'),
        completed_query_directory=rel(RUNTIME / 'queries-r1'))
    require(set(successor) == set(profile) and len(successor['modules']) == 21
            and all(path in files for path in (*successor['modules'].values(), successor['advance_driver']['path']))
            and files[successor['advance_driver']['path']] == successor['advance_driver']['sha256'],
            'Successor profile schema/helper binding differs')
    profile_raw = U.canonical(successor)
    record = dict(schema='atlas.private.plan15.selected-driver-integration.r1',
        status='PREPARED_SOURCE_NOT_QUALIFIED', parent_composition_sha256=BASE_PIN,
        parent_profile_sha256=PROFILE_PIN, parent_manifest_sha256=MANIFEST_PIN,
        parent_derivation_sha256=DERIVATION_PIN, composition_sha256=digest(composition_raw),
        manifest_sha256=digest(manifest_raw), profile_sha256=digest(profile_raw),
        reviewed_inputs=dict(path=str(reviewed_path), sha256=digest(reviewed_raw)),
        native_outputs=239, helper_outputs=395, changed_helpers=1, preserved_files=633,
        changes={MEMBER: dict(before=BEFORE, after=AFTER)}, source_inputs=dict(inputs.pins),
        bootstrap=dict(path=str(OWNED / 'bootstrap_native.py'), sha256=digest(boot)),
        inherited_staged=copy.deepcopy(base['staged']), default_enabled=False, H3='CANDIDATE_NOT_ENABLED',
        selected_driver=selected, selected_driver_workers=8, global_parallel_default_workers=6,
        driver_worker_configuration_changes=True, global_worker_default_changes=False,
        runtime_policy_adopted=False, programme_adopted=False, execution_authority=False,
        read_only_process_handle_changes=False, worker_lifecycle_protocol_changes=False,
        production_limits_changed=False, numerical_changes=False, historical_receipts_changed=False,
        interval_authority=False, holds_released=False, scientific_acceptance=False,
        whole_interval_performance_claim=False,
        source_logical_bytes=dict(before=sum(map(len, baseline.values())), after=sum(map(len, payload.values()))))
    outputs = {TARGET / name: raw for name, raw in payload.items()}
    outputs.update({reviewed_path: reviewed_raw, TARGET / 'composition.json': composition_raw,
        RUNTIME / 'manifest.json': manifest_raw, RUNTIME / 'fresh-profile.json': profile_raw,
        RUNTIME / 'derivation.json': U.canonical(record), OWNED / 'bootstrap_native.py': boot})
    result_path = OWNED / 'BUILD-RESULT.json'
    result = dict(record, emitted_files=len(outputs) + 1,
        constructor_sha256=digest(Path(__file__).read_bytes()), input_finality=True, output_finality=True)
    outputs[result_path] = U.canonical(result)
    require(len(outputs) == 641 and all(any(path.is_relative_to(root) for root in (TARGET, RUNTIME, OWNED))
            for path in outputs),
            'Unexpected output scope/count')
    inputs.recheck()
    return inputs, outputs, record, result_path


def output_rows(outputs):
    return {str(path): dict(stage='bytes/' + str(index).zfill(4) + '.bin', sha256=digest(raw), bytes=len(raw))
            for index, (path, raw) in enumerate(sorted(outputs.items(), key=lambda row: str(row[0])))}


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)


def apply_plan(U, inputs, outputs, record, result_path, plan_raw, plan_sha256):
    """Apply already rederived bytes only after every pre-write trust check."""
    rows = output_rows(outputs)
    checked = U.Inputs()
    existing = checked.raw(PLAN, plan_sha256)
    require(existing == plan_raw, 'Plan differs from exact rederived sources, bytes, paths or metadata')
    for path, raw in outputs.items():
        staged = U.member(PLAN_ROOT, rows[str(path)]['stage'])
        require(checked.raw(staged, rows[str(path)]['sha256']) == raw, 'Planned bytes differ')
    fresh(U)
    inputs.recheck()
    checked.recheck()
    for path, raw in outputs.items():
        if path != result_path:
            write_new(path, raw)
    inputs.recheck()
    checked.recheck()
    for path, raw in outputs.items():
        if path != result_path:
            require(U.ordinary(path).read_bytes() == raw, 'Emitted bytes differ: ' + str(path))
    U.composition(U.Inputs(), TARGET, record['composition_sha256'],
                  Path(record['reviewed_inputs']['path']), record['reviewed_inputs']['sha256'])
    write_new(result_path, outputs[result_path])  # finality receipt only after all preceding checks
    require(U.ordinary(result_path).read_bytes() == outputs[result_path], 'Finality receipt differs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('plan', 'apply'))
    parser.add_argument('--plan-sha256')
    args = parser.parse_args()
    require((args.mode == 'apply') == (args.plan_sha256 is not None), 'Only apply requires exact plan SHA')
    U = utility()
    inputs, outputs, record, result_path = derive(U)
    rows = output_rows(outputs)
    plan = dict(schema='plan15.selected-driver-successor-plan.r1', status='UNEXECUTED_SOURCE_PLAN',
        source_inputs=dict(inputs.pins), outputs=rows, target=str(TARGET), runtime=str(RUNTIME),
        owned=str(OWNED), identities={key: record[key] for key in
            ('composition_sha256', 'manifest_sha256', 'profile_sha256', 'reviewed_inputs', 'bootstrap')},
        source_members=634, native_members=239, helper_members=395, changed_members=1, preserved_members=633,
        selected_driver_workers=8, global_parallel_default_workers=6, prepared_artifact_selection=True,
        runtime_policy_adopted=False, programme_adopted=False, global_worker_default_changes=False,
        read_only_process_handle_changes=False, worker_lifecycle_protocol_changes=False,
        scientific_execution_authority=False, qualification=False, default_changed=False, H3='CANDIDATE_NOT_ENABLED')
    plan_raw = U.canonical(plan)
    if args.mode == 'plan':
        require(not U.exists(PLAN_ROOT), 'Preserve existing/partial source plan')
        for path, raw in outputs.items():
            write_new(PLAN_ROOT / rows[str(path)]['stage'], raw)
        inputs.recheck()
        write_new(PLAN, plan_raw)
        print(json.dumps(dict(status=plan['status'], plan=str(PLAN), sha256=digest(plan_raw), outputs=len(rows),
                              identities=plan['identities'])))
        return
    apply_plan(U, inputs, outputs, record, result_path, plan_raw, args.plan_sha256)
    print(json.dumps(dict(status=record['status'], applied_plan_sha256=args.plan_sha256,
                          build_result=str(result_path), source_qualified=False, outputs=len(rows))))


if __name__ == '__main__':
    main()
