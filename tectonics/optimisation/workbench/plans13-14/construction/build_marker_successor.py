"""Source-only JOINT successor containing only the supplied FD marker binding.

No runtime/scientific imports, tests, queue command, enabled-build change,
historical receipt edit or hold release. All bytes/metadata are prepared and
checked before new-only output writes. Existing/partial outputs are refused.
"""
import ast
import copy
from hashlib import sha256
import json
from pathlib import Path
import types

W = Path('C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace')
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
HERE = W / 'work/plan13/marker-integration-r1'
OWNED = HERE / 'joint'
SELF = HERE / 'build_marker_successor.py'
RESULT = OWNED / 'construction-result.json'
UTILITY = W / 'work/plan11/integration-r1/build_profile.py'
UTILITY_SHA = '171915e6871740755afdd54528b9a9fc2dfd236a0b60ae427175ab70d3f7492e'
MACHINERY = W / 'work/plan13/resource-witness-r1/build_projection_witness.py'
MACHINERY_SHA = '33ab20c9d16b442ac0c61e6038559152c3988868f7a1f851bb8cab024480025b'
DELTA = W / 'work/plan14/marker-projection-r1/integration-map.json'
DELTA_SHA = '58439e28d9db7ba31f512bef8e634d400dac86304528ec1dd9a85239184358fa'
SOURCE_REVIEW = HERE / 'source-review-r1.json'
SOURCE_REVIEW_SHA = '4d31ea527b72c827fb9dab1d17f89c004f396a88371bbf02296108891ed2fb23'
PARENT = T / 'ac/p13c14w-r1'
PARENT_RUNTIME = T / 'ac/p13c14w-run-r1'
TARGET = T / 'ac/p13c14m-r1'
RUNTIME = T / 'ac/p13c14m-run-r1'
PINS = dict(
    composition='4cbd4f78b1689b4bb8fc0f139b456ba47597bd6221bb8ca50e5eac3fd054b890',
    profile='6f07f61ff328a12ca42d34ea2dd719336f589f7ba46843e3d517c106e5ce88c8',
    manifest='569ec5da851ebc9bc97a68e13e1d7717cc106118409b27a59f8945a513221d7f',
    derivation='f900551620c26422757960bcf1a05291d93b990292fd436f69ac4829ab182960',
    reviewed='ba3278693a566cc2255bdfaf3e22b1dc0d79e7b8958ffc612993221607816026',
)
PARENT_REVIEWED = W / 'work/plan13/resource-witness-r1/joint/reviewed-inputs.json'
FD = 'fresh_interval_driver.py'
FD_MEMBER = 'helpers/' + FD
FD_BEFORE = '709f65d3d44662f04a8283ccd0265a9f0575f688ec6e96f3019fcd80328f9943'
FD_AFTER = 'c6df7b959ec9309d7b7ab12f2e763c5e111138fbb2cf2d736b4c616d24132895'
FD_SOURCE = W / 'work/plan14/marker-projection-r1/candidate/helpers/fresh_interval_driver.py'
OFF = dict(H3=False, H5a=False, D5=False, P4=False)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def without_projection_function(raw):
    """Compare all bytes outside the single explicitly selected function."""
    text = raw.decode('utf8')
    functions = [node for node in ast.parse(text).body
                 if isinstance(node, ast.FunctionDef) and node.name == '_projection_stages']
    require(len(functions) == 1, 'exact one top-level _projection_stages required')
    node = functions[0]
    lines = raw.splitlines(keepends=True)
    return b''.join(lines[:node.lineno-1]) + b'# EXACT_SELECTED_FUNCTION\n' + b''.join(lines[node.end_lineno:])


def source_module(path, raw, name):
    """Only exact pinned stdlib-only construction modules are executed here."""
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def prepare(U, B, self_pin):
    inputs = U.Inputs()
    for path, pin in ((SELF, self_pin), (UTILITY, UTILITY_SHA), (MACHINERY, MACHINERY_SHA)):
        B.read(inputs, path, pin)
    delta = B.doc(inputs, DELTA, DELTA_SHA)
    review = B.doc(inputs, SOURCE_REVIEW, SOURCE_REVIEW_SHA)
    require(review['schema'] == 'atlas.private.plan13.marker-boundary-review.r1' and
            review['status'] == 'PASS_SOURCE_AND_EVIDENCE_REUSE_BOUNDARY_ONLY' and
            review['delta']['path'] == str(DELTA) and review['delta']['sha256'] == DELTA_SHA and
            review['candidate'] == B.ref(FD_SOURCE, FD_AFTER), 'exact root source/evidence review required')
    require(delta['schema'] == 'atlas.private.plan14.marker-projection-delta.r1' and
            delta['status'] == 'SOURCE_PREPARED_NOT_EXECUTED' and
            delta['parent_composition'] == B.ref(PARENT / 'composition.json', PINS['composition']) and
            delta['parent_profile'] == B.ref(PARENT_RUNTIME / 'fresh-profile.json', PINS['profile']) and
            set(delta['replacements']) == {FD}, 'exact JOINT one-driver marker delta required')
    row = delta['replacements'][FD]
    require(row['parent'] == B.ref(PARENT / FD_MEMBER, FD_BEFORE) and
            row['candidate'] == B.ref(FD_SOURCE, FD_AFTER) and
            row['changed_function'] == '_projection_stages' and row['all_other_bytes_exact'] is True,
            'exact source-selection row required')
    base, prior, native, helpers = U.composition(inputs, B.scoped(PARENT), PINS['composition'],
                                                B.scoped(PARENT_REVIEWED), PINS['reviewed'])
    require((len(native), len(helpers)) == (239, 395) and helpers[FD] == FD_BEFORE,
            'exact JOINT parent inventory/driver required')
    baseline = {area + '/' + name: B.read(inputs, PARENT / area / name, pin)
                for area, rows in (('src', native), ('helpers', helpers)) for name, pin in rows.items()}
    replacement = B.read(inputs, FD_SOURCE, FD_AFTER)
    compile(replacement, str(FD_SOURCE), 'exec')  # Syntax only; never imported/executed.
    require(without_projection_function(baseline[FD_MEMBER]) == without_projection_function(replacement),
            'bytes outside _projection_stages changed')
    payload = dict(baseline, **{FD_MEMBER: replacement})
    require(set(payload) == set(baseline) and
            {name for name in payload if payload[name] != baseline[name]} == {FD_MEMBER},
            'undeclared source addition/omission/change')
    unchanged = {name: digest(value) for name, value in baseline.items() if name != FD_MEMBER}
    require(len(unchanged) == 633, 'exact unchanged source coverage required')
    protected = {}
    for key in ('projection', 'numerics'):
        identity = delta['loaded_heat_sources'][key]
        member = 'helpers/' + identity['name']
        require(member in unchanged and unchanged[member] == identity['sha256'],
                'selected numerical/projection bytes differ')
        protected[member] = identity['sha256']
    for name in (
        'private_heat_forward_kernel_r13.py', 'private_heat_native_issuer_r13.py',
        'private_heat_certification_kernel_r1.py', 'private_heat_certification_resources_r1.py',
        'private_heat_compiled_dot_r1.py', 'private_heat_closed_owned_r5.py', 'private_heat_finish_kernel_r11.py',
        'prepared_interval_driver.py', 'private_heat_physical_order_r1.py',
        'private_heat_checkpoint_consumer_r9.py', 'private_heat_restored_binding_r9.py',
        'private_heat_native_issuer_r12.py', 'private_heat_issuer_resources_r3.py',
        'private_heat_issuer_resources_r4.py', 'private_heat_native_projection_r4.py',
        'private_heat_bundle.py', 'historical_compact_heat.py', 'runtime_compatibility.py',
    ):
        member = 'helpers/' + name
        require(member in unchanged, 'protected inherited member absent: ' + member)
        protected[member] = unchanged[member]

    old = B.doc(inputs, PARENT_RUNTIME / 'manifest.json', PINS['manifest'])
    profile = B.doc(inputs, PARENT_RUNTIME / 'fresh-profile.json', PINS['profile'])
    derived = B.doc(inputs, PARENT_RUNTIME / 'derivation.json', PINS['derivation'])
    require(derived['status'] == 'PREPARED_SOURCE_ONLY' and all(
        derived[key + '_sha256'] == PINS[key] for key in ('composition', 'manifest', 'profile')),
        'exact parent derivation required')
    require(set(old) == {'files', 'source_hashes', 'data_only', 'completed_query_store', 'composition'} and
            old['source_hashes'] == {name: pin for name, pin in native.items() if name.endswith('.py')},
            'parent manifest schema/native sources differ')
    roots = [B.rel(PARENT / 'helpers'), 'fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests']
    require(old['composition'] == dict(root=B.rel(PARENT), composition_json=B.rel(PARENT / 'composition.json'),
        composition_sha256=PINS['composition'], frozen=False, import_root_order=roots) and
        old['completed_query_store'] == 'files', 'parent manifest composition differs')
    require(profile['schema'] == 'atlas.fresh-interval-profile.v1' and profile['workspace'] == str(T) and
        profile['native_root'] == B.rel(PARENT / 'src') and profile['import_roots'] == roots and
        len(profile['modules']) == 20 and profile['source_manifest'] ==
        dict(path=B.rel(PARENT_RUNTIME / 'manifest.json'), sha256=PINS['manifest']) and
        profile['advance_driver'] == dict(module='fresh_interval_driver', path=B.rel(PARENT / FD_MEMBER), sha256=FD_BEFORE),
        'parent profile/advance-driver differs')
    owned_code = {B.rel(PARENT / name): digest(value) for name, value in baseline.items() if name.endswith('.py')}
    owned_data = {B.rel(PARENT / name): digest(value) for name, value in baseline.items() if not name.endswith('.py')}
    owned_data[B.rel(PARENT / 'composition.json')] = PINS['composition']
    ext_code = {name: pin for name, pin in old['files'].items() if name not in owned_code}
    ext_data = {name: pin for name, pin in old['data_only'].items() if name not in owned_data}
    require(old['files'] == {**ext_code, **owned_code} and old['data_only'] == {**ext_data, **owned_data}
            and (len(ext_code), len(ext_data)) == (14, 104), 'full external parent closure differs')
    for name, pin in {**old['files'], **old['data_only']}.items():
        source = B.scoped(T / name)
        member = U.member(T, name)
        require(member == source, 'external source path identity differs')
        inputs.verify(member, pin)
    boot_source = Path(derived['bootstrap']['path'])
    boot = B.read(inputs, boot_source, derived['bootstrap']['sha256'])
    before = ('REAL_ROOT = T / "%s"' % B.rel(PARENT)).encode()
    after = ('REAL_ROOT = T / "%s"' % B.rel(TARGET)).encode()
    require(boot.count(before) == 1 and boot.count(b'REAL_COUNTS = (239, 395)') == 1,
            'exact inherited native bootstrap required')
    boot = boot.replace(before, after)
    compile(boot, str(OWNED / 'bootstrap_native.py'), 'exec')

    new_helpers = dict(helpers, **{FD: FD_AFTER})
    require(native == base['outputs'] and len(new_helpers) == 395, 'native/helper inventory changed unexpectedly')
    change = {FD_MEMBER: dict(before=FD_BEFORE, after=FD_AFTER, source=str(FD_SOURCE),
                             operation='exact-_projection_stages-only-source-replacement')}
    selected = dict(delta=B.ref(DELTA, DELTA_SHA), source_review=B.ref(SOURCE_REVIEW, SOURCE_REVIEW_SHA),
        parent=B.ref(PARENT / 'composition.json', PINS['composition']),
        changes=change, preserved_file_count=633, protected_identities=protected,
        status='CANDIDATE_NOT_ENABLED', enabled=False, disabled=OFF,
        proof_boundary=review['reuse_boundary'])
    reviewed = copy.deepcopy(prior)
    reviewed.update(target=TARGET.name, target_root=str(TARGET), outputs=native,
                    staged=dict(base['staged'], projection_marker_binding=selected))
    reviewed['helpers'][FD] = B.ref(FD_SOURCE, FD_AFTER)
    reviewed['stages'].append(dict(module=FD, stage='projection-marker:N5-exact-call-binding',
        input_sha256=FD_BEFORE, output_sha256=FD_AFTER,
        note='Only supplied _projection_stages replacement; numerical and other source bytes unchanged'))
    for name, pin in inputs.pins.items():
        require(name not in reviewed['files'] or reviewed['files'][name] == pin, 'conflicting reviewed source identity')
        reviewed['files'][name] = pin
    reviewed_path = OWNED / 'reviewed-inputs.json'
    reviewed_raw = U.canonical(reviewed)
    composition = copy.deepcopy(base)
    composition.update(root=str(TARGET), outputs=native, helpers=new_helpers,
        staged=reviewed['staged'], stages=reviewed['stages'], reviewed_inputs=str(reviewed_path),
        reviewed_inputs_sha256=digest(reviewed_raw))
    composition_raw = U.canonical(composition)
    files = {**ext_code, **{B.rel(TARGET / name): digest(value) for name, value in payload.items() if name.endswith('.py')}}
    data = {**ext_data, **{B.rel(TARGET / name): digest(value) for name, value in payload.items() if not name.endswith('.py')},
            B.rel(TARGET / 'composition.json'): digest(composition_raw)}
    require(len(files) == len(old['files']) and len(data) == len(old['data_only']) and not set(files) & set(data),
            'new manifest inventory changed unexpectedly')
    translate = lambda name: B.translated(name, PARENT, TARGET)
    import_roots = [translate(name) for name in profile['import_roots']]
    manifest = dict(old, files=files, data_only=data, source_hashes=old['source_hashes'],
        composition=dict(root=B.rel(TARGET), composition_json=B.rel(TARGET / 'composition.json'),
                         composition_sha256=digest(composition_raw), frozen=False, import_root_order=import_roots))
    manifest_raw = U.canonical(manifest)
    successor = copy.deepcopy(profile)
    successor.update(native_root=B.rel(TARGET / 'src'), import_roots=import_roots,
        modules={name: translate(value) for name, value in profile['modules'].items()},
        advance_driver=dict(module='fresh_interval_driver', path=B.rel(TARGET / FD_MEMBER), sha256=FD_AFTER),
        source_manifest=dict(path=B.rel(RUNTIME / 'manifest.json'), sha256=digest(manifest_raw)),
        output_directory=str(RUNTIME / 'attempt-r1'), store_directory=str(RUNTIME / 'store-r1'),
        completed_query_directory=B.rel(RUNTIME / 'queries-r1'))
    for name in (*successor['modules'].values(), successor['advance_driver']['path']):
        require(name in files, 'successor profile module escaped exact manifest')
    require(files[successor['advance_driver']['path']] == FD_AFTER and
            successor['completed_query_limits'] == profile['completed_query_limits'], 'driver/query identity differs')
    profile_raw = U.canonical(successor)
    logical = dict(before=sum(map(len, baseline.values())), after=sum(map(len, payload.values())),
                   scope='Logical src/helpers bytes only; no runtime/physical-disk claim')
    logical['change'] = logical['after'] - logical['before']
    record = dict(schema='atlas.private.projection-marker-candidate-derivation.r1', status='PREPARED_SOURCE_ONLY',
        candidate_status='CANDIDATE_NOT_ENABLED', parent=B.ref(PARENT / 'composition.json', PINS['composition']),
        composition_sha256=digest(composition_raw), manifest_sha256=digest(manifest_raw), profile_sha256=digest(profile_raw),
        reviewed_inputs=B.ref(reviewed_path, digest(reviewed_raw)), delta=B.ref(DELTA, DELTA_SHA), changes=change,
        source_review=B.ref(SOURCE_REVIEW, SOURCE_REVIEW_SHA),
        native_outputs=239, helper_outputs=395, added_files=0, replaced_files=1, preserved_source_files=633,
        protected_identities=protected, source_inputs=dict(inputs.pins), source_logical_bytes=logical,
        bootstrap=B.ref(OWNED / 'bootstrap_native.py', digest(boot)), enabled=False, disabled=OFF,
        historical_receipts_changed=False, interval_authority=False, holds_released=False, scientific_acceptance=False,
        root_eligibility='NEW_PROFILE_REQUIRES_NEW_ELIGIBLE_ROOT')
    outputs = {TARGET / name: value for name, value in payload.items()}
    outputs.update({reviewed_path: reviewed_raw, TARGET / 'composition.json': composition_raw,
        RUNTIME / 'manifest.json': manifest_raw, RUNTIME / 'fresh-profile.json': profile_raw,
        RUNTIME / 'derivation.json': U.canonical(record), OWNED / 'bootstrap_native.py': boot})
    summary = dict(parent=record['parent'], composition=B.ref(TARGET / 'composition.json', digest(composition_raw)),
        profile=B.ref(RUNTIME / 'fresh-profile.json', digest(profile_raw)),
        manifest=B.ref(RUNTIME / 'manifest.json', digest(manifest_raw)),
        derivation=B.ref(RUNTIME / 'derivation.json', digest(U.canonical(record))),
        reviewed_inputs=record['reviewed_inputs'], bootstrap=record['bootstrap'],
        native_files=239, helper_files=395, added_files=0, replaced_files=1, preserved_files=633,
        changes=change, protected_identities=protected, source_logical_bytes=logical)
    return dict(inputs=inputs, outputs=outputs, summary=summary, composition_pin=digest(composition_raw),
                reviewed_path=reviewed_path, reviewed_pin=digest(reviewed_raw))


def main():
    require(Path(__file__).resolve() == SELF, 'exact owned constructor path required')
    raw = UTILITY.read_bytes()
    require(digest(raw) == UTILITY_SHA, 'qualified metadata utility changed')
    U = source_module(UTILITY, raw, '_qualified_marker_metadata')
    initial = U.Inputs()
    raw = initial.raw(MACHINERY, MACHINERY_SHA)
    B = source_module(MACHINERY, raw, '_qualified_projection_source_primitives')
    B.scoped(UTILITY)
    B.scoped(MACHINERY)
    for path in (TARGET, RUNTIME, OWNED):
        B.new_path(U, path)
    plan = prepare(U, B, digest(SELF.read_bytes()))
    require(not set(map(str, plan['outputs'])) & set(plan['inputs'].pins), 'output overlaps frozen source')
    for path in (TARGET, RUNTIME, OWNED):
        B.new_path(U, path)
    plan['inputs'].recheck()
    report = dict(schema='atlas.private.one-parent-projection-marker-construction.r1', status='SOURCE_WRITE_STARTED',
        builder=B.ref(SELF, digest(SELF.read_bytes())), delta=B.ref(DELTA, DELTA_SHA),
        source_review=B.ref(SOURCE_REVIEW, SOURCE_REVIEW_SHA), generation=plan['summary'],
        source_inputs=dict(plan['inputs'].pins), source_finality=dict(before_write=True, after_write=False),
        verified_output_files=0, enabled=False, disabled=OFF, full_interval_run=False,
        historical_receipts_changed=False, science_imported=False, holds_released=False, scientific_acceptance=False)
    written, failure = [], None
    try:
        for path, value in plan['outputs'].items():
            B.write_new(U, path, value)
            written.append(str(path))
        U.composition(U.Inputs(), TARGET, plan['composition_pin'], plan['reviewed_path'], plan['reviewed_pin'])
        for path, value in plan['outputs'].items():
            require(U.ordinary(path).read_bytes() == value, 'emitted byte mismatch: ' + str(path))
        plan['inputs'].recheck()
        report.update(status='PREPARED_SOURCE_ONLY', verified_output_files=len(plan['outputs']))
        report['source_finality']['after_write'] = True
    except BaseException as error:
        failure = error
        report.update(status='FAILED_PARTIAL_OUTPUTS_RETAINED', failure=repr(error), written_files=written)
        try:
            plan['inputs'].recheck()
            report['source_finality']['after_write'] = True
        except Exception as source_error:
            report['source_finality']['failure'] = repr(source_error)
    B.write_new(U, RESULT, U.canonical(report))
    print(json.dumps(dict(status=report['status'], result=B.ref(RESULT, digest(U.canonical(report))),
                          generation=report['generation'], source_finality=report['source_finality'])))
    if failure is not None:
        raise failure


if __name__ == '__main__':
    main()
