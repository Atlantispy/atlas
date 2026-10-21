"""Prepare an immutable C14 candidate over accepted p1012; no Atlas imports.

H2 -> L1 -> H3 changes exactly three heat source files. A separately reviewed,
explicitly pinned additional delta can share this generation. This constructor
does not enable H3, launch a workload, change receipts or release any hold.
"""
import argparse
import ast
import copy
from hashlib import sha256
import json
from pathlib import Path
import re
import types

W = Path('C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace')
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
HERE = W / 'work/plan13/c14-r1'
BASE = T / 'ac/p1012-r1'
TARGET = T / 'ac/p13c14-r1'
RUNTIME = T / 'ac/p13c14-run-r1'
UTILITY = W / 'work/plan11/integration-r1/build_profile.py'
UTILITY_SHA = '171915e6871740755afdd54528b9a9fc2dfd236a0b60ae427175ab70d3f7492e'
BASE_PINS = {
    'composition': (BASE / 'composition.json', 'cb71df92d0ab2f3ab175c43a669d5b8ffc1d4d350cbdc49b68fd6f2cabfb74d5'),
    'reviewed_inputs': (W / 'work/plans10-12-integration-r1/reviewed-inputs.json', '98d792324467a1492aff062f720b6d74e75c543057fbd5c2d437229d56cfea62'),
    'profile': (T / 'ac/p1012-run-r1/fresh-profile.json', '5d1912888fff8271c8241ec6b10b961e9bb2acb7f6189b9d423b90f8235b0ad1'),
    'manifest': (T / 'ac/p1012-run-r1/manifest.json', '4bab57bae18fc4f4e75f6b0d2ec1d03cdf6be4bae23c780f538ab8a159443304'),
    'derivation': (T / 'ac/p1012-run-r1/derivation.json', '5cd8710ac26001fd5ca9eebc7fe98370e27ce1f0d5f0e081bf5e3b15fb3ef2f3'),
}
ACCEPTED = W / 'work/plans10-12-integration-r1/integration-result.json'
ACCEPTED_SHA = '6bb55360ee2904642af5daaaf9bb63e540aa6044242f16eae37d8731b6d7b725'
TRANSFORM = T / 'ck/transforms/h3_compiled_dot.py'
TRANSFORM_SHA = '9ce7ac9d96a5606118977ee2a835b460202210abea5175f6c9f7452e10d4c3aa'
COMPILED = T / 'ck/h3/private_heat_compiled_dot_r1.py'
COMPILED_SHA = 'e0be3a309c8ab9ccee3c1a36525f72da27e816b1ce984651dbd85a3c072a14aa'
KERNEL = 'private_heat_certification_kernel_r1.py'
RESOURCES = 'private_heat_certification_resources_r1.py'
HELPER = 'private_heat_compiled_dot_r1.py'
KERNEL_BEFORE = '3be44650802e629bedeaf20ce2b70cd88a14f12ee83571e8560e10a5b1157241'
KERNEL_AFTER = '4099a297a8423a6213761ab4f305d442dda647ec6c7a46ee4d4734d253041f71'
RESOURCES_H2 = '8b451aa8d4e44175ecf24508a88245b00778a40a693111d5bfed5d8860cf167e'
RESOURCES_L1 = 'fadac10d59e7a453b7940db1ba382b925e40ec6e894f62a56b1efe99c5a84591'
BOOTSTRAP = W / 'work/plans10-12-integration-r1/bootstrap_native.py'
BOOTSTRAP_SHA = '9df3df452bc39509ff7364ca0ef37ed8218228c5adca39b87a08869fc1b2c59c'
QUALIFIER = HERE / 'qualify_heat.py'
FIXTURE = W / 'work/plan05/integrated-r13/order-repair/test_physical_order_r1.py'
FIXTURE_SHA = 'c2dd52a4d962cd28f71f196932e1d3d08aa5026ee27eac3c029344831d2f6c6f'
CURRENT = (
    'private_heat_forward_kernel_r13.py', 'private_heat_native_issuer_r13.py',
    'private_heat_checkpoint_consumer_r10.py', 'private_heat_joined_consumer_r6.py',
    'private_heat_restored_binding_r10.py', 'private_heat_restored_binding_ram_context_r1.py',
    'private_heat_restored_binding_ram_recovery_r1.py',
)
HISTORICAL = (
    'private_heat_checkpoint_consumer_r9.py', 'private_heat_restored_binding_r9.py',
    'private_heat_native_issuer_r12.py', 'private_heat_bundle.py',
    'historical_compact_heat.py', 'runtime_compatibility.py',
    'private_heat_closed_owned_r4.py', 'private_heat_finish_kernel_r10.py',
)
NATIVE_COLD = 'atlas_tectonics/integration_private_heat_cold.py'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def rel(path):
    return path.relative_to(T).as_posix()


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)


def translated(name):
    prefix = rel(BASE)
    return rel(TARGET) + name[len(prefix):] if name == prefix or name.startswith(prefix + '/') else name


def literal_repin(raw, before, after):
    """Exactly one complete literal, leaving all surrounding source bytes intact."""
    require(re.fullmatch('[0-9a-f]{64}', before) and re.fullmatch('[0-9a-f]{64}', after), 'full pins required')
    text = raw.decode('utf8')
    constants = [n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Constant) and n.value == before]
    require(len(constants) == 1, 'source pin must have exactly one literal')
    pattern = re.compile(r"(['\"])" + re.escape(before) + r'\1')
    require(len(pattern.findall(text)) == 1, 'source pin spelling must occur exactly once')
    result = pattern.sub(lambda m: m[1] + after + m[1], text).encode('utf8')
    compile(result, '<explicit-C14-source-repin>', 'exec')
    return result


def c14_delta(inputs, helpers):
    """Use H3's exact transform, with only its approved resources-input repin."""
    require(helpers[KERNEL] == KERNEL_BEFORE and helpers[RESOURCES] == RESOURCES_L1,
            'accepted H2/L1 inputs required')
    require(HELPER not in helpers, 'H3 helper must be new')
    original = inputs.raw(TRANSFORM, TRANSFORM_SHA)
    adjusted = literal_repin(original, RESOURCES_H2, RESOURCES_L1)
    module = types.ModuleType('_reviewed_C14_source_transform')
    # Preserve the reviewed transform's original source-relative helper lookup.
    module.__file__ = str(TRANSFORM)
    exec(compile(adjusted, str(TRANSFORM) + ':C14-resources-input', 'exec'), module.__dict__)
    require(module.RESOURCES_INPUT_SHA256.keys() == {RESOURCES_L1} and
            module.COMPILED_SHA256 == COMPILED_SHA, 'unexpected transform derivation')
    helper = inputs.raw(COMPILED, COMPILED_SHA)
    kernel = inputs.raw(BASE / 'helpers' / KERNEL, KERNEL_BEFORE)
    resources = inputs.raw(BASE / 'helpers' / RESOURCES, RESOURCES_L1)
    after_kernel = module.transform(kernel.decode('utf8')).encode('utf8')
    require(digest(after_kernel) == KERNEL_AFTER, 'reviewed H3 kernel output differs')
    after_resources = module.repin(resources.decode('utf8'), KERNEL_BEFORE, KERNEL_AFTER).encode('utf8')
    require(after_resources == literal_repin(resources, KERNEL_BEFORE, KERNEL_AFTER),
            'C14 resources must change only the kernel literal')
    payload = {'helpers/' + KERNEL: after_kernel, 'helpers/' + RESOURCES: after_resources,
               'helpers/' + HELPER: helper}
    for name, value in payload.items():
        compile(value, str(TARGET / name), 'exec')
    return payload, dict(original_transform=dict(path=str(TRANSFORM), sha256=TRANSFORM_SHA),
        derived_transform_sha256=digest(adjusted), resources_input_repin=dict(before=RESOURCES_H2, after=RESOURCES_L1),
        kernel_input=KERNEL_BEFORE, kernel_output=KERNEL_AFTER, resources_input=RESOURCES_L1,
        resources_output=digest(after_resources), compiled_helper=dict(path=str(COMPILED), sha256=COMPILED_SHA))


def additional_delta(inputs, path, pin, native, helpers, c14):
    """Admit only explicit source rows over this exact predecessor, no overlaps."""
    if path is None:
        require(pin is None, 'additional delta pin without path')
        return {}, None
    require(pin is not None, 'explicit additional delta pin required')
    doc = inputs.doc(path, pin)
    require(doc.get('base') == dict(path=str(BASE / 'composition.json'), sha256=BASE_PINS['composition'][1]),
            'additional delta has another predecessor')
    require(type(doc.get('files')) is dict and doc['files'], 'nonempty explicit additional files required')
    payload = {}
    for name, row in doc['files'].items():
        require(type(name) is str and name.startswith(('helpers/', 'src/')) and name.endswith('.py') and
                '\\' not in name and ':' not in name and all(p not in ('', '.', '..') for p in name.split('/')),
                'additional delta must select canonical source members')
        require(name not in ('helpers/' + KERNEL, 'helpers/' + HELPER),
                'additional delta cannot replace reviewed H3 kernel/helper: ' + name)
        area, member = name.split('/', 1)
        # An overlap is an explicitly ordered successor over the C14 output,
        # never a blind merge of two deltas written against the old resources.
        previous = digest(c14[name]) if name in c14 else (helpers if area == 'helpers' else native).get(member)
        require(row['base_sha256'] == previous, 'additional predecessor differs: ' + name)
        candidate = Path(row['candidate'])
        value = inputs.raw(candidate, row['output_sha256'])
        require(digest(value) != previous, 'unchanged additional source row')
        compile(value, str(candidate), 'exec')
        payload[name] = value
    return payload, dict(path=str(path), sha256=pin, files=doc['files'])


def build(additional_path=None, additional_pin=None):
    require(Path(__file__).resolve() == HERE / 'build_combined.py', 'owned constructor path required')
    require(not TARGET.exists() and not RUNTIME.exists(), 'preserve existing composition/runtime')
    for name in ('reviewed-inputs.json', 'integration-map.json', 'bootstrap_native.py'):
        require(not (HERE / name).exists(), 'preserve existing preparation: ' + name)
    raw = UTILITY.read_bytes()
    require(digest(raw) == UTILITY_SHA, 'qualified metadata utility changed')
    U = types.ModuleType('_qualified_metadata_primitives')
    U.__file__ = str(UTILITY)
    exec(compile(raw, str(UTILITY), 'exec'), U.__dict__)
    inputs = U.Inputs()
    inputs.raw(UTILITY, UTILITY_SHA)
    self_pin = digest(Path(__file__).read_bytes())
    inputs.raw(Path(__file__).resolve(), self_pin)
    accepted = inputs.doc(ACCEPTED, ACCEPTED_SHA)
    require(accepted['status'] == 'INTEGRATED_FOCUSED_CHECKS_PASS' and
            accepted['composition']['sha256'] == BASE_PINS['composition'][1], 'accepted predecessor required')
    base, prior, native, helpers = U.composition(inputs, BASE, BASE_PINS['composition'][1], *BASE_PINS['reviewed_inputs'])
    require((len(native), len(helpers)) == (239, 390), 'p1012 inventory differs')
    replacements, transform = c14_delta(inputs, helpers)
    c14 = dict(replacements)
    extra, extra_record = additional_delta(inputs, additional_path, additional_pin, native, helpers, c14)
    replacements.update(extra)
    baseline = {area + '/' + name: inputs.raw(BASE / area / name, expected)
                for area, rows in (('src', native), ('helpers', helpers)) for name, expected in rows.items()}
    payload = {**baseline, **replacements}
    changes = {name: dict(before=digest(baseline[name]) if name in baseline else None, after=digest(value))
               for name, value in replacements.items()}
    require(all(changes[name]['before'] != changes[name]['after'] for name in changes), 'unchanged delta row')
    require({name for name, value in payload.items() if name not in changes and value != baseline[name]} == set(),
            'undeclared source change')
    current = {'helpers/' + name: helpers[name] for name in CURRENT}
    current['src/' + NATIVE_COLD] = native[NATIVE_COLD]
    historical = {'helpers/' + name: helpers[name] for name in HISTORICAL}
    require(not set(historical) & set(replacements), 'historical reader sources must remain exact')
    require(not {'helpers/private_heat_native_issuer_r13.py',
                 'helpers/private_heat_physical_order_r1.py'} & set(replacements),
            'accepted issuer and physical order bytes must remain exact')
    # C14 alone changes no current reader source; a separately reviewed S1
    # cascade may explicitly change current readers in the additional delta.
    require(not set(current) & set(c14), 'C14 must not gratuitously repin current readers')
    new_native = {name[4:]: digest(value) for name, value in payload.items() if name.startswith('src/')}
    new_helpers = {name[8:]: digest(value) for name, value in payload.items() if name.startswith('helpers/')}

    old = inputs.doc(*BASE_PINS['manifest'])
    profile = inputs.doc(*BASE_PINS['profile'])
    derived = inputs.doc(*BASE_PINS['derivation'])
    require(derived['status'] == 'PREPARED_SOURCE_ONLY' and all(derived[k + '_sha256'] == BASE_PINS[k][1]
            for k in ('composition', 'profile', 'manifest')), 'predecessor runtime binding differs')
    require(old['source_hashes'] == {k: v for k, v in native.items() if k.endswith('.py')}, 'native manifest differs')
    require(profile['native_root'] == rel(BASE / 'src') and profile['source_manifest'] ==
            dict(path=rel(BASE_PINS['manifest'][0]), sha256=BASE_PINS['manifest'][1]), 'predecessor profile differs')
    for name, expected in {**old['files'], **old['data_only']}.items():
        inputs.verify(U.member(T, name), expected)
    old_code = {rel(BASE / name): digest(value) for name, value in baseline.items() if name.endswith('.py')}
    ext_code = {k: v for k, v in old['files'].items() if k not in old_code}
    require(old['files'] == {**ext_code, **old_code} and len(ext_code) == 14, 'inherited code closure differs')
    old_data = {rel(BASE / name): digest(value) for name, value in baseline.items() if not name.endswith('.py')}
    old_data[rel(BASE / 'composition.json')] = BASE_PINS['composition'][1]
    ext_data = {k: v for k, v in old['data_only'].items() if k not in old_data}
    require(old['data_only'] == {**ext_data, **old_data} and len(ext_data) == 104, 'inherited data closure differs')
    qualifier_pin = digest(QUALIFIER.read_bytes())
    inputs.raw(QUALIFIER, qualifier_pin)
    inputs.raw(FIXTURE, FIXTURE_SHA)

    delta = dict(schema='atlas.private.plan13-c14.source-delta.r1', status='CANDIDATE_NOT_ENABLED',
        base=dict(path=str(BASE / 'composition.json'), sha256=BASE_PINS['composition'][1]),
        transform=transform, composition_order=('additional-then-C14 (disjoint deltas)' if not set(c14) & set(extra)
            else 'C14-then-additional (explicit successor pin required for overlap)'),
        files={name: dict(base_sha256=row['before'], output_sha256=row['after'],
            candidate=str(TARGET / name), operation='C14-reviewed-transform' if name not in extra else 'additional-reviewed-source')
            for name, row in changes.items()}, additional=extra_record,
        affected_current_consumers={name: dict(before=pin, after=digest(payload[name]),
            source_changed=name in extra) for name, pin in current.items()}, preserved_historical_consumers=historical,
        physical_order_sha256=helpers['private_heat_physical_order_r1.py'],
        current_source_policy='C14 current consumer source pins unchanged; extra reviewed cascade explicit; loaded graph binds final bytes',
        numerical_contract='Exact directed numbers, zero signs, ternaries, bounds and public accounts preserved',
        enabled=False, H5a_enabled=False, historical_receipts_changed=False, holds_released=False)
    delta_raw = U.canonical(delta)
    delta_path = HERE / 'integration-map.json'
    reviewed = copy.deepcopy(prior)
    selected = dict(delta=dict(path=str(delta_path), sha256=digest(delta_raw)), changes=changes,
                    status='CANDIDATE_NOT_ENABLED', enabled=False, additional=extra_record,
                    inherited='All p1012 bytes outside the explicit delta preserved')
    reviewed.update(target=TARGET.name, target_root=str(TARGET), outputs=new_native,
                    staged=dict(base['staged'], plan13_c14_candidate=selected))
    for name, value in replacements.items():
        if name.startswith('helpers/'):
            reviewed['helpers'][name[8:]] = dict(path=str(TARGET / name), sha256=digest(value))
    reviewed['stages'].append(dict(module=RESOURCES, stage='plan13:C14-H2-L1-H3',
        input_sha256=RESOURCES_L1, output_sha256=transform['resources_output'],
        note='Candidate only; exact kernel-pin change; current loaded dependency identity derives anew'))
    for name, value in inputs.pins.items():
        require(name not in reviewed['files'] or reviewed['files'][name] == value, 'conflicting reviewed input')
        reviewed['files'][name] = value
    reviewed_path = HERE / 'reviewed-inputs.json'
    reviewed_raw = U.canonical(reviewed)
    composed = copy.deepcopy(base)
    composed.update(root=str(TARGET), outputs=new_native, helpers=new_helpers, staged=reviewed['staged'],
        stages=reviewed['stages'], reviewed_inputs=str(reviewed_path), reviewed_inputs_sha256=digest(reviewed_raw))
    composed_raw = U.canonical(composed)
    files = {**ext_code, **{rel(TARGET / name): digest(value) for name, value in payload.items() if name.endswith('.py')}}
    data = {**ext_data, **{rel(TARGET / name): digest(value) for name, value in payload.items() if not name.endswith('.py')},
            rel(TARGET / 'composition.json'): digest(composed_raw)}
    require(not set(files) & set(data), 'code/data inventory overlap')
    roots = [translated(p) for p in profile['import_roots']]
    manifest = dict(old, files=files, data_only=data,
        source_hashes={k: v for k, v in new_native.items() if k.endswith('.py')},
        composition=dict(root=rel(TARGET), composition_json=rel(TARGET / 'composition.json'),
                         composition_sha256=digest(composed_raw), frozen=False, import_root_order=roots))
    manifest_raw = U.canonical(manifest)
    new_profile = copy.deepcopy(profile)
    new_profile.update(native_root=rel(TARGET / 'src'), import_roots=roots,
        modules={k: translated(v) for k, v in profile['modules'].items()},
        advance_driver={**profile['advance_driver'], 'path': translated(profile['advance_driver']['path'])},
        source_manifest=dict(path=rel(RUNTIME / 'manifest.json'), sha256=digest(manifest_raw)),
        output_directory=str(RUNTIME / 'attempt-r1'), store_directory=str(RUNTIME / 'store-r1'),
        completed_query_directory=rel(RUNTIME / 'queries-r1'))
    for name in (*new_profile['modules'].values(), new_profile['advance_driver']['path']):
        require(name in files, 'profile module outside manifest')
    driver = new_profile['advance_driver']
    if files[driver['path']] != driver['sha256']:
        old_driver = profile['advance_driver']['path']
        prefix = rel(BASE) + '/'
        require(old_driver.startswith(prefix) and old_driver[len(prefix):] in extra,
                'driver changed without explicit additional reviewed source row')
        new_profile['advance_driver']['sha256'] = files[driver['path']]
    require(new_profile['completed_query_limits'] == profile['completed_query_limits'], 'query policy changed')
    profile_raw = U.canonical(new_profile)
    boot = inputs.raw(BOOTSTRAP, BOOTSTRAP_SHA)
    for before, after in ((b'REAL_ROOT = T / "ac/p1012-r1"', b'REAL_ROOT = T / "ac/p13c14-r1"'),
                          (b'REAL_COUNTS = (239, 390)', ('REAL_COUNTS = (%d, %d)' %
                          (len(new_native), len(new_helpers))).encode('ascii'))):
        require(boot.count(before) == 1, 'bootstrap constant anchor differs')
        boot = boot.replace(before, after)
    inputs.recheck()
    record = dict(schema='atlas.private.plan13-c14.candidate-derivation.r1', status='PREPARED_SOURCE_ONLY',
        candidate_status='CANDIDATE_NOT_ENABLED', baseline={k: dict(path=str(p), sha256=s) for k, (p, s) in BASE_PINS.items()},
        changes=changes, composition_sha256=digest(composed_raw), profile_sha256=digest(profile_raw),
        manifest_sha256=digest(manifest_raw), delta_sha256=digest(delta_raw),
        reviewed_inputs=dict(path=str(reviewed_path), sha256=digest(reviewed_raw)),
        bootstrap=dict(path=str(HERE / 'bootstrap_native.py'), sha256=digest(boot)),
        qualifier=dict(path=str(QUALIFIER), sha256=qualifier_pin), source_inputs=inputs.pins,
        native_outputs=len(new_native), helper_outputs=len(new_helpers),
        unchanged_source_files=len(payload)-len(replacements), root_eligibility='NEW_PROFILE_REQUIRES_NEW_ELIGIBLE_ROOT',
        H3_enabled=False, interval_authority=False, holds_released=False, scientific_acceptance=False,
        historical_receipts_changed=False, scope='C14 candidate plus explicit additional source delta; no selected-build change')
    for name, value in payload.items():
        write(TARGET / name, value)
    for path, value in ((delta_path, delta_raw), (reviewed_path, reviewed_raw),
            (TARGET / 'composition.json', composed_raw), (RUNTIME / 'manifest.json', manifest_raw),
            (RUNTIME / 'fresh-profile.json', profile_raw), (RUNTIME / 'derivation.json', U.canonical(record)),
            (HERE / 'bootstrap_native.py', boot)):
        write(path, value)
    inputs.recheck()
    U.composition(U.Inputs(), TARGET, digest(composed_raw), reviewed_path, digest(reviewed_raw))
    print(json.dumps(dict(status='CANDIDATE_NOT_ENABLED', composition_sha256=digest(composed_raw),
        profile_sha256=digest(profile_raw), manifest_sha256=digest(manifest_raw), delta_sha256=digest(delta_raw),
        derivation_sha256=digest(U.canonical(record)), changed_files=len(replacements),
        preserved_source_files=len(payload)-len(replacements), native_files=len(new_native), helper_files=len(new_helpers))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--additional-delta', type=Path)
    parser.add_argument('--additional-delta-sha256')
    args = parser.parse_args()
    build(args.additional_delta, args.additional_delta_sha256)
