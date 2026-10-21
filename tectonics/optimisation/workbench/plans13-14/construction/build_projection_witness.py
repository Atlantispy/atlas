"""Construct two new projection-witness candidates, source and metadata only.

No Atlas/runtime import, scientific run, test, queue operation, selected-build
change, historical receipt edit, hold release or publication. Both complete
generation plans are checked before the first new-only write. Partial outputs
are retained on failure and never overwritten by a retry.
"""
import copy
from hashlib import sha256
import json
import os
from pathlib import Path
import types

W = Path('C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace')
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
HERE = W / 'work/plan13/resource-witness-r1'
SELF = HERE / 'build_projection_witness.py'
DELTA_ROOT = W / 'work/plan14/resource-witness-r1'
DELTA = DELTA_ROOT / 'integration-map.json'
DELTA_SHA = 'f0f506d5fbdfa8ed0ea8bba9f1042dbc21db1e34b92a06a6030a88a46c0ac639'
UTILITY = W / 'work/plan11/integration-r1/build_profile.py'
UTILITY_SHA = '171915e6871740755afdd54528b9a9fc2dfd236a0b60ae427175ab70d3f7492e'
RESULT = HERE / 'construction-result.json'
SOURCE_REVIEW = HERE / 'source-review-r1.json'
SOURCE_REVIEW_SHA = '8f8b9a7604665475e261113a390bae5f43d3ddcc67392b7da8fbaa355a753be1'
ISSUER = 'helpers/private_heat_native_issuer_r13.py'
ADDED = frozenset(('helpers/private_heat_native_projection_r5.py',
                   'helpers/private_heat_projection_numerics_r4.py'))
CONSUMERS = frozenset((
    'helpers/private_heat_checkpoint_consumer_r10.py',
    'helpers/private_heat_joined_consumer_r6.py',
    'helpers/private_heat_restored_binding_r10.py',
    'helpers/private_heat_restored_binding_ram_context_r1.py',
    'helpers/private_heat_restored_binding_ram_recovery_r1.py',
    'src/atlas_tectonics/integration_private_heat_cold.py',
))
CHANGED = ADDED | CONSUMERS | {ISSUER}
OFF = dict(H3=False, H5a=False, D5=False, P4=False)
SPECS = (
    dict(label='base', parent=T / 'ac/p1012-r1', runtime=T / 'ac/p1012-run-r1',
         target=T / 'ac/p1012w-r1', target_runtime=T / 'ac/p1012w-run-r1',
         composition_sha='cb71df92d0ab2f3ab175c43a669d5b8ffc1d4d350cbdc49b68fd6f2cabfb74d5',
         profile_sha='5d1912888fff8271c8241ec6b10b961e9bb2acb7f6189b9d423b90f8235b0ad1',
         manifest_sha='4bab57bae18fc4f4e75f6b0d2ec1d03cdf6be4bae23c780f538ab8a159443304',
         derivation_sha='5cd8710ac26001fd5ca9eebc7fe98370e27ce1f0d5f0e081bf5e3b15fb3ef2f3',
         reviewed=W / 'work/plans10-12-integration-r1/reviewed-inputs.json',
         reviewed_sha='98d792324467a1492aff062f720b6d74e75c543057fbd5c2d437229d56cfea62',
         helpers=390, preserved=622),
    dict(label='joint', parent=T / 'ac/p13c14-r1', runtime=T / 'ac/p13c14-run-r1',
         target=T / 'ac/p13c14w-r1', target_runtime=T / 'ac/p13c14w-run-r1',
         composition_sha='646916ba3264257e5d67ae95b1fd66f9d300c92fa614e93f32035d7bb0ebaf70',
         profile_sha='fd862fba1b3ad4ac8d891965fffeef7b27519fdcfa74a3e2e6671135be3e2e7e',
         manifest_sha='2f9154408679a9d6d831246a8be5864104a0e6accff975dc1480c28219c9b7c3',
         derivation_sha='c333a6442c402f72322bb2969b81cce6ca853b4aeb241fc3b8fab1a827d9ba1e',
         reviewed=W / 'work/plan13/c14-r1/reviewed-inputs.json',
         reviewed_sha='ea594c18e26bf28224989ab048572980f5159e0b76a22e51101d5494a5ab6182',
         helpers=393, preserved=625),
)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def ref(path, pin):
    return dict(path=str(path), sha256=pin)


def rel(path):
    return path.relative_to(T).as_posix()


def scoped(path):
    """Every explicit source stays in the two named roots, never T/bridge."""
    require(path.is_absolute() and path == path.resolve(), 'canonical absolute scoped path required: ' + str(path))
    require(path.is_relative_to(W) or path.is_relative_to(T), 'source outside named scoped roots: ' + str(path))
    require(not path.is_relative_to(T / 'bridge'), 'T/bridge is excluded')
    return path


def new_path(U, path):
    scoped(path)
    require(not os.path.lexists(path), 'preserve existing output, including partial/link: ' + str(path))
    ancestor = path.parent
    while not os.path.lexists(ancestor):
        ancestor = ancestor.parent
    U.ordinary(ancestor, directory=True)


def read(inputs, path, pin):
    return inputs.raw(scoped(path), pin)


def doc(inputs, path, pin):
    scoped(path)
    return inputs.doc(path, pin)


def translated(name, parent, target):
    old = rel(parent)
    return rel(target) + name[len(old):] if name == old or name.startswith(old + '/') else name


def prepare(U, spec, self_pin):
    inputs = U.Inputs()
    read(inputs, SELF, self_pin)
    read(inputs, UTILITY, UTILITY_SHA)
    delta = doc(inputs, DELTA, DELTA_SHA)
    review = doc(inputs, SOURCE_REVIEW, SOURCE_REVIEW_SHA)
    require(review['schema'] == 'atlas.private.plan13.projection-witness-source-review.r1' and
            review['status'] == 'PASS_SOURCE_ONLY' and review['delta'] == ref(DELTA, DELTA_SHA),
            'existing exact source-only review binding differs')
    require(delta['schema'] == 'atlas.private.plan14.projection-witness-delta.r1' and
            delta['status'] == 'CANDIDATE_NOT_INTEGRATED' and delta['holds_unchanged'] is True,
            'exact reviewed projection witness map required')
    require(len(delta['generations']) == 2 and {r['label'] for r in delta['generations']} == {'base', 'joint'},
            'exact two generation rows required')
    selected = next(row for row in delta['generations'] if row['label'] == spec['label'])
    parent, target = spec['parent'], spec['target']
    runtime, output_runtime = spec['runtime'], spec['target_runtime']
    require(selected['parent'] == ref(parent / 'composition.json', spec['composition_sha']) and
            selected['copied_from_actual_selected_generation'] is True and
            selected['h3_enabled'] is False and selected['h5a_enabled'] is False and
            selected['preserved_files'] == spec['preserved'], 'selected parent/authority/count differs')
    require(set(selected['files']) == CHANGED and len(selected['files']) == 9 and
            set(selected['source_pin_only_consumers']) == CONSUMERS,
            'exact nine source rows and six current consumers required')
    base, prior, native, helpers = U.composition(inputs, scoped(parent), spec['composition_sha'],
                                                scoped(spec['reviewed']), spec['reviewed_sha'])
    require((len(native), len(helpers)) == (239, spec['helpers']), 'exact parent inventory counts required')
    baseline = {area + '/' + name: read(inputs, parent / area / name, pin)
                for area, rows in (('src', native), ('helpers', helpers)) for name, pin in rows.items()}
    replacements = {}
    for name, row in selected['files'].items():
        # Names are the exact frozen nine-row set, not caller-supplied paths.
        before = digest(baseline[name]) if name in baseline else None
        require(row['base_sha256'] == before and ((before is None) == (name in ADDED)),
                'delta predecessor/addition differs: ' + name)
        source = DELTA_ROOT / (spec['label'] + '-delta') / name
        require(row['candidate'] == str(source), 'candidate escaped exact selected delta root: ' + name)
        value = read(inputs, source, row['output_sha256'])
        require(digest(value) != before, 'declared delta row did not change: ' + name)
        compile(value, str(source), 'exec')  # Syntax only: no execution/import.
        replacements[name] = value
    payload = {**baseline, **replacements}
    additions = set(payload) - set(baseline)
    changed_existing = {name for name in baseline if payload[name] != baseline[name]}
    unchanged = set(baseline) - changed_existing
    require(additions == ADDED and changed_existing == (CHANGED - ADDED) and
            len(unchanged) == spec['preserved'] and len(payload) == len(baseline) + 2,
            'explicit nine-row change or preservation coverage differs')
    protected = dict(selected['preserved_historical_files'])
    for name, pin in protected.items():
        require(name in baseline and digest(baseline[name]) == pin and payload[name] == baseline[name],
                'historical identity changed: ' + name)
    # These are affected integration boundaries, not permission to rewrite them.
    for member in ('private_heat_forward_kernel_r13.py', 'private_heat_physical_order_r1.py',
            'fresh_interval_driver.py', 'prepared_interval_driver.py',
            'private_heat_certification_kernel_r1.py', 'private_heat_certification_resources_r1.py',
            'private_heat_compiled_dot_r1.py', 'private_heat_closed_owned_r5.py', 'private_heat_finish_kernel_r11.py'):
        name = 'helpers/' + member
        if name in baseline:
            require(payload[name] == baseline[name], 'H3/S1/order/marker bytes changed: ' + name)
            protected[name] = digest(baseline[name])

    profile = doc(inputs, runtime / 'fresh-profile.json', spec['profile_sha'])
    old = doc(inputs, runtime / 'manifest.json', spec['manifest_sha'])
    derived = doc(inputs, runtime / 'derivation.json', spec['derivation_sha'])
    require(derived['status'] == 'PREPARED_SOURCE_ONLY' and all(
        derived[key + '_sha256'] == spec[key + '_sha'] for key in ('composition', 'profile', 'manifest')),
        'exact parent derivation binding required')
    require(set(old) == {'files', 'source_hashes', 'data_only', 'completed_query_store', 'composition'} and
            old['source_hashes'] == {name: pin for name, pin in native.items() if name.endswith('.py')},
            'parent native manifest schema or source hashes differ')
    roots = [rel(parent / 'helpers'), 'fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests']
    require(old['composition'] == dict(root=rel(parent), composition_json=rel(parent / 'composition.json'),
        composition_sha256=spec['composition_sha'], frozen=False, import_root_order=roots) and
        old['completed_query_store'] == 'files', 'parent manifest composition binding differs')
    require(profile['schema'] == 'atlas.fresh-interval-profile.v1' and profile['workspace'] == str(T) and
        profile['native_root'] == rel(parent / 'src') and profile['import_roots'] == roots and
        len(profile['modules']) == 20 and profile['source_manifest'] ==
        dict(path=rel(runtime / 'manifest.json'), sha256=spec['manifest_sha']), 'parent profile binding differs')
    owned_code = {rel(parent / name): digest(value) for name, value in baseline.items() if name.endswith('.py')}
    owned_data = {rel(parent / name): digest(value) for name, value in baseline.items() if not name.endswith('.py')}
    owned_data[rel(parent / 'composition.json')] = spec['composition_sha']
    ext_code = {name: pin for name, pin in old['files'].items() if name not in owned_code}
    ext_data = {name: pin for name, pin in old['data_only'].items() if name not in owned_data}
    require(old['files'] == {**ext_code, **owned_code} and old['data_only'] == {**ext_data, **owned_data}
            and (len(ext_code), len(ext_data)) == (14, 104), 'parent external closure differs')
    for name, pin in {**old['files'], **old['data_only']}.items():
        source = scoped(T / name)
        member = U.member(T, name)
        require(source == member, 'manifest path identity differs')
        inputs.verify(member, pin)

    new_native = {name[4:]: digest(value) for name, value in payload.items() if name.startswith('src/')}
    new_helpers = {name[8:]: digest(value) for name, value in payload.items() if name.startswith('helpers/')}
    require((len(new_native), len(new_helpers)) == (239, spec['helpers'] + 2), 'new source inventory differs')
    changes = {name: dict(before=selected['files'][name]['base_sha256'], after=digest(value),
                         source=selected['files'][name]['candidate'], operation=selected['files'][name]['operation'])
               for name, value in replacements.items()}
    owned = HERE / spec['label']
    reviewed_path = owned / 'reviewed-inputs.json'
    # Read the bootstrap input before sealing reviewed-inputs, so its exact
    # source belongs to both the reviewed closure and the derivation record.
    boot_source = Path(derived['bootstrap']['path'])
    boot = read(inputs, boot_source, derived['bootstrap']['sha256'])
    for before, after in ((('REAL_ROOT = T / "%s"' % rel(parent)).encode(),
                          ('REAL_ROOT = T / "%s"' % rel(target)).encode()),
                         (('REAL_COUNTS = (239, %d)' % spec['helpers']).encode(),
                          ('REAL_COUNTS = (239, %d)' % (spec['helpers'] + 2)).encode())):
        require(boot.count(before) == 1, 'native bootstrap translation anchor differs')
        boot = boot.replace(before, after)
    compile(boot, str(owned / 'bootstrap_native.py'), 'exec')
    selection = dict(delta=ref(DELTA, DELTA_SHA), source_review=ref(SOURCE_REVIEW, SOURCE_REVIEW_SHA),
        parent=selected['parent'], changes=changes,
        preserved_file_count=len(unchanged), protected_identities=protected,
        status='CANDIDATE_NOT_ENABLED', enabled=False, disabled=OFF)
    reviewed = copy.deepcopy(prior)
    reviewed.update(target=target.name, target_root=str(target), outputs=new_native,
                    staged=dict(base['staged'], projection_peak_witness=selection))
    for name in replacements:
        if name.startswith('helpers/'):
            reviewed['helpers'][name[8:]] = ref(Path(selected['files'][name]['candidate']), digest(replacements[name]))
    reviewed['stages'].append(dict(module='private_heat_native_issuer_r13.py',
        stage='projection-peak-witness:r13-selects-N5', input_sha256=changes[ISSUER]['before'],
        output_sha256=changes[ISSUER]['after'],
        note='Exact supplied nine-file source delta; historical resource/projection helpers preserved'))
    for name, pin in inputs.pins.items():
        require(name not in reviewed['files'] or reviewed['files'][name] == pin, 'conflicting reviewed input: ' + name)
        reviewed['files'][name] = pin
    reviewed_raw = U.canonical(reviewed)
    composition = copy.deepcopy(base)
    composition.update(root=str(target), outputs=new_native, helpers=new_helpers,
        staged=reviewed['staged'], stages=reviewed['stages'], reviewed_inputs=str(reviewed_path),
        reviewed_inputs_sha256=digest(reviewed_raw))
    composition_raw = U.canonical(composition)
    files = {**ext_code, **{rel(target / name): digest(value) for name, value in payload.items() if name.endswith('.py')}}
    data = {**ext_data, **{rel(target / name): digest(value) for name, value in payload.items() if not name.endswith('.py')},
            rel(target / 'composition.json'): digest(composition_raw)}
    require(len(files) == len(old['files']) + 2 and len(data) == len(old['data_only']) and not set(files) & set(data),
            'new code/data closure differs')
    import_roots = [translated(name, parent, target) for name in profile['import_roots']]
    manifest = dict(old, files=files, data_only=data,
        source_hashes={name: pin for name, pin in new_native.items() if name.endswith('.py')},
        composition=dict(root=rel(target), composition_json=rel(target / 'composition.json'),
                         composition_sha256=digest(composition_raw), frozen=False, import_root_order=import_roots))
    manifest_raw = U.canonical(manifest)
    successor = copy.deepcopy(profile)
    successor.update(native_root=rel(target / 'src'), import_roots=import_roots,
        modules={name: translated(value, parent, target) for name, value in profile['modules'].items()},
        advance_driver={**profile['advance_driver'], 'path': translated(profile['advance_driver']['path'], parent, target)},
        source_manifest=dict(path=rel(output_runtime / 'manifest.json'), sha256=digest(manifest_raw)),
        output_directory=str(output_runtime / 'attempt-r1'), store_directory=str(output_runtime / 'store-r1'),
        completed_query_directory=rel(output_runtime / 'queries-r1'))
    for name in (*successor['modules'].values(), successor['advance_driver']['path']):
        require(name in files, 'new profile module is outside exact source manifest')
    require(files[successor['advance_driver']['path']] == successor['advance_driver']['sha256'] and
            successor['completed_query_limits'] == profile['completed_query_limits'],
            'unchanged driver/query contract differs')
    profile_raw = U.canonical(successor)

    logical = dict(before=sum(map(len, baseline.values())), after=sum(map(len, payload.values())),
                   scope='Logical src/helpers bytes only; not physical allocation/runtime storage')
    logical['change'] = logical['after'] - logical['before']
    record = dict(schema='atlas.private.projection-witness-candidate-derivation.r1', status='PREPARED_SOURCE_ONLY',
        candidate_status='CANDIDATE_NOT_ENABLED', generation=spec['label'], parent=selected['parent'],
        composition_sha256=digest(composition_raw), profile_sha256=digest(profile_raw), manifest_sha256=digest(manifest_raw),
        reviewed_inputs=ref(reviewed_path, digest(reviewed_raw)), delta=ref(DELTA, DELTA_SHA),
        source_review=ref(SOURCE_REVIEW, SOURCE_REVIEW_SHA),
        changes=changes, native_outputs=len(new_native), helper_outputs=len(new_helpers),
        added_files=2, replaced_files=7, preserved_source_files=len(unchanged), protected_identities=protected,
        source_logical_bytes=logical, source_inputs=dict(inputs.pins),
        bootstrap=ref(owned / 'bootstrap_native.py', digest(boot)), enabled=False, disabled=OFF,
        root_eligibility='NEW_PROFILE_REQUIRES_NEW_ELIGIBLE_ROOT',
        historical_receipts_changed=False, interval_authority=False, holds_released=False, scientific_acceptance=False)
    # Include the bootstrap source in the complete source record. It is not a
    # numerical output and changes no src/helpers file count.
    record['source_inputs'] = dict(inputs.pins)
    derivation_raw = U.canonical(record)
    outputs = {target / name: value for name, value in payload.items()}
    outputs.update({reviewed_path: reviewed_raw, target / 'composition.json': composition_raw,
        output_runtime / 'manifest.json': manifest_raw, output_runtime / 'fresh-profile.json': profile_raw,
        output_runtime / 'derivation.json': derivation_raw, owned / 'bootstrap_native.py': boot})
    report = dict(generation=spec['label'], status='PREPARED_SOURCE_ONLY', candidate_status='CANDIDATE_NOT_ENABLED',
        parent=selected['parent'], composition=ref(target / 'composition.json', digest(composition_raw)),
        profile=ref(output_runtime / 'fresh-profile.json', digest(profile_raw)),
        manifest=ref(output_runtime / 'manifest.json', digest(manifest_raw)),
        derivation=ref(output_runtime / 'derivation.json', digest(derivation_raw)),
        reviewed_inputs=ref(reviewed_path, digest(reviewed_raw)), bootstrap=record['bootstrap'],
        native_files=len(new_native), helper_files=len(new_helpers), explicit_delta_files=9,
        added_files=2, replaced_files=7, preserved_files=len(unchanged),
        protected_identities=protected, source_logical_bytes=logical, enabled=False, disabled=OFF)
    return dict(inputs=inputs, outputs=outputs, report=report, reviewed=reviewed_path,
                target=target, composition_pin=digest(composition_raw), reviewed_pin=digest(reviewed_raw))


def write_new(U, path, raw):
    # Targets and metadata folders were checked absent before any write. Recheck
    # each existing ancestor immediately before exclusive file creation as well.
    scoped(path)
    ancestor = path.parent
    while not os.path.lexists(ancestor):
        ancestor = ancestor.parent
    U.ordinary(ancestor, directory=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    U.ordinary(path.parent, directory=True)
    with path.open('xb') as stream:
        stream.write(raw)


def main():
    require(Path(__file__).resolve() == SELF, 'exact owned source-constructor path required')
    utility_raw = scoped(UTILITY).read_bytes()
    require(digest(utility_raw) == UTILITY_SHA, 'qualified source-metadata utility changed')
    U = types.ModuleType('_qualified_projection_witness_metadata')
    U.__file__ = str(UTILITY)
    exec(compile(utility_raw, str(UTILITY), 'exec'), U.__dict__)
    self_pin = digest(SELF.read_bytes())
    for spec in SPECS:
        for path in (spec['target'], spec['target_runtime'], HERE / spec['label']):
            new_path(U, path)
    new_path(U, RESULT)
    plans = [prepare(U, spec, self_pin) for spec in SPECS]
    all_outputs = {}
    source_pins = {}
    for plan in plans:
        require(not set(all_outputs) & set(plan['outputs']), 'generation output collision')
        all_outputs.update(plan['outputs'])
        for name, pin in plan['inputs'].pins.items():
            require(name not in source_pins or source_pins[name] == pin, 'conflicting shared source identity')
            source_pins[name] = pin
    require(not set(map(str, all_outputs)) & set(source_pins), 'new output overlaps frozen input')
    for spec in SPECS:
        for path in (spec['target'], spec['target_runtime'], HERE / spec['label']):
            new_path(U, path)
    new_path(U, RESULT)
    for plan in plans:
        plan['inputs'].recheck()
    report = dict(schema='atlas.private.two-parent-projection-witness-construction.r1',
        status='SOURCE_WRITE_STARTED', builder=ref(SELF, self_pin), delta=ref(DELTA, DELTA_SHA),
        source_review=ref(SOURCE_REVIEW, SOURCE_REVIEW_SHA),
        generations=[plan['report'] for plan in plans], source_inputs=source_pins,
        source_finality=dict(before_write=True, after_write=False), verified_output_files=0,
        enabled=False, disabled=OFF, historical_receipts_changed=False, full_interval_run=False,
        science_imported=False, holds_released=False, scientific_acceptance=False)
    written = []
    failure = None
    try:
        for path, raw in all_outputs.items():
            write_new(U, path, raw)
            written.append(str(path))
        # Validate actual emitted descriptors, exact inventories and every
        # runtime/provenance file, using the same accepted metadata machinery.
        for plan in plans:
            U.composition(U.Inputs(), plan['target'], plan['composition_pin'], plan['reviewed'], plan['reviewed_pin'])
        for path, raw in all_outputs.items():
            require(U.ordinary(path).read_bytes() == raw, 'emitted bytes differ: ' + str(path))
        for plan in plans:
            plan['inputs'].recheck()
        report.update(status='PREPARED_SOURCE_ONLY', verified_output_files=len(all_outputs))
        report['source_finality']['after_write'] = True
    except BaseException as error:
        failure = error
        report.update(status='FAILED_PARTIAL_OUTPUTS_RETAINED', failure=repr(error), written_files=written)
        errors = []
        for plan in plans:
            try:
                plan['inputs'].recheck()
            except Exception as source_error:
                errors.append(repr(source_error))
        report['source_finality'].update(after_write=not errors, failures=errors)
    write_new(U, RESULT, U.canonical(report))
    print(json.dumps(dict(status=report['status'], result=ref(RESULT, digest(U.canonical(report))),
        generations=report['generations'], source_finality=report['source_finality'])))
    if failure is not None:
        raise failure


if __name__ == '__main__':
    main()
