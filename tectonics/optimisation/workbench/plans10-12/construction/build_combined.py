"""Add the reviewed heat delta to the complete r13 composition, source only.

No Atlas import, workload, old receipt modification or interval-run permission.
Targets are permanent short paths; an existing target is never overwritten.
"""
import copy
from hashlib import sha256
import json
from pathlib import Path
import types

W = Path('C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace')
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
HERE = W / 'work/plans10-12-integration-r1'
BASE = T / 'ac/p11-out/composed-r13'
TARGET = T / 'ac/p1012-r1'
RUNTIME = T / 'ac/p1012-run-r1'
UTILITY = W / 'work/plan11/integration-r1/build_profile.py'
UTILITY_SHA = '171915e6871740755afdd54528b9a9fc2dfd236a0b60ae427175ab70d3f7492e'
BASE_PINS = {
    'composition': (BASE / 'composition.json', '052373386aec0eeb04f84d49c4468b616c34c52bbe0f7f37850593da94cc2ab5'),
    'reviewed_inputs': (W / 'work/plan11/integration-r1/e2/reviewed-inputs.json', '01fa58b03adabb1934da9956c2c736ac2ccf8a886e403f50a6efe313334bd108'),
    'profile': (T / 'ac/p11-runtime-r1/fresh-profile.json', 'd527f613ddc5425e40c0bbb9ca9ed2e3074528fcb5e19efe260c08f4109404ed'),
    'manifest': (T / 'ac/p11-runtime-r1/manifest.json', 'd79457d79534c9ba20c2ca31842b25fbde3bc8b122b6585b33498075ce0b8b2f'),
    'derivation': (T / 'ac/p11-runtime-r1/derivation.json', '9313c75d9f5a4cc8e2c665acf1712e3c497692a0db939f29bb0532af3dce0698'),
}
DELTA = W / 'work/plan12/review-integration-r1/integration-map.json'
DELTA_SHA = 'e26d7afd1d2672306bcbfaef540a8b2387af19eef6fdd2846e642679cb4626e1'
TEST = W / 'work/plan10/review-integration-r1/helpers/test_launch_fresh_interval.py'
TEST_SHA = '74e56e162d4936c98153cd4ea10156548600ee2c5eb6b5d332c2d6003bcfc33b'
BOOTSTRAP = W / 'work/plan11/native-entry-r1/bootstrap_native.py'
BOOTSTRAP_SHA = 'f5009a2d9907a4835197714a86587ea4390a7d75a7eb830ca62311c594cc71f5'


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


def build():
    require(Path(__file__).resolve() == HERE / 'build_combined.py', 'owned builder path required')
    require(not TARGET.exists() and not RUNTIME.exists(), 'preserve existing composition/runtime')
    raw = UTILITY.read_bytes()
    require(digest(raw) == UTILITY_SHA, 'qualified metadata utility changed')
    U = types.ModuleType('_qualified_plan11_metadata_primitives')
    U.__file__ = str(UTILITY)
    exec(compile(raw, str(UTILITY), 'exec'), U.__dict__)
    inputs = U.Inputs()
    inputs.raw(UTILITY, UTILITY_SHA)
    inputs.raw(Path(__file__).resolve(), digest(Path(__file__).read_bytes()))
    base, prior, native, helpers = U.composition(inputs, BASE, BASE_PINS['composition'][1], *BASE_PINS['reviewed_inputs'])
    require((len(native), len(helpers)) == (239, 389), 'r13 baseline count differs')
    delta = inputs.doc(DELTA, DELTA_SHA)
    require(delta['base'] == dict(path=str(BASE / 'composition.json'), sha256=BASE_PINS['composition'][1]), 'heat base mismatch')
    require(delta['selected']['lane'] == 'lf3' and delta['selected']['h5a_enabled'] is False and len(delta['files']) == 17,
            'exact reviewed heat delta required')
    inputs.raw(Path(delta['selected']['path']), delta['selected']['sha256'])
    inputs.raw(DELTA.parent / 'build_heat_delta.py', delta['builder_sha256'])
    replacements = {}
    for name, row in delta['files'].items():
        require(name.startswith(('helpers/', 'src/')) and '..' not in Path(name).parts, 'invalid delta path')
        area, member = name.split('/', 1)
        old = (helpers if area == 'helpers' else native).get(member)
        require(old == row['base_sha256'], 'delta predecessor differs: ' + name)
        inputs.raw(Path(row['source']), row['source_sha256'])
        replacements[name] = inputs.raw(Path(row['candidate']), row['output_sha256'])
    test_name = 'helpers/test_launch_fresh_interval.py'
    require(helpers['test_launch_fresh_interval.py'] == 'a280803bf51ddcf1416e3582df24f2c1e313eee78a47eba78f94c9b5eb1566f8', 'test predecessor differs')
    replacements[test_name] = inputs.raw(TEST, TEST_SHA)
    for name, expected in delta['preserved_helpers'].items():
        require(helpers[name] == expected and 'helpers/' + name not in replacements, 'inherited boundary differs')

    payload = {area + '/' + name: inputs.raw(BASE / area / name, expected)
               for area, rows in (('src', native), ('helpers', helpers)) for name, expected in rows.items()}
    payload.update(replacements)
    new_native = {name[4:]: digest(value) for name, value in payload.items() if name.startswith('src/')}
    new_helpers = {name[8:]: digest(value) for name, value in payload.items() if name.startswith('helpers/')}
    require((len(new_native), len(new_helpers)) == (239, 390), 'successor inventory differs')
    changes = {name: dict(before=(native if name.startswith('src/') else helpers).get(name.split('/', 1)[1]),
                         after=digest(value)) for name, value in replacements.items()}
    require({k for k in payload if k not in replacements} ==
            {area + '/' + name for area, rows in (('src', native), ('helpers', helpers)) for name in rows} - set(replacements),
            'undeclared omission')

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
    old_owned_code = {rel(BASE / name): digest(value) for name, value in payload.items()
                      if name.endswith('.py') and name not in replacements}
    old_owned_code.update({rel(BASE / name): changes[name]['before'] for name in replacements
                           if name.endswith('.py') and changes[name]['before'] is not None})
    ext_code = {k: v for k, v in old['files'].items() if k not in old_owned_code}
    require(old['files'] == {**ext_code, **old_owned_code} and len(ext_code) == 14, 'inherited code closure differs')
    old_owned_data = {rel(BASE / area / name): value for area, rows in (('src', native), ('helpers', helpers))
                      for name, value in rows.items() if not name.endswith('.py')}
    old_owned_data[rel(BASE / 'composition.json')] = BASE_PINS['composition'][1]
    ext_data = {k: v for k, v in old['data_only'].items() if k not in old_owned_data}
    require(old['data_only'] == {**ext_data, **old_owned_data} and len(ext_data) == 104, 'inherited data closure differs')

    reviewed = copy.deepcopy(prior)
    selected = dict(heat_delta=dict(path=str(DELTA), sha256=DELTA_SHA), test_fix=dict(path=str(TEST), sha256=TEST_SHA),
                    changes=changes, inherited='All other r13 source bytes preserved', h5a_enabled=False)
    reviewed.update(target=TARGET.name, target_root=str(TARGET), outputs=new_native,
                    staged=dict(base['staged'], plans10_12_integration=selected))
    for name, row in delta['files'].items():
        if name.startswith('helpers/'):
            reviewed['helpers'][name[8:]] = dict(path=row['candidate'], sha256=row['output_sha256'])
    reviewed['helpers']['test_launch_fresh_interval.py'] = dict(path=str(TEST), sha256=TEST_SHA)
    current_native = 'src/atlas_tectonics/integration_private_heat_cold.py'
    reviewed['stages'].append(dict(module='integration_private_heat_cold.py', stage='plans10-12:current-heat-binding',
        input_sha256=changes[current_native]['before'], output_sha256=changes[current_native]['after'],
        note='Only current restored-r10 dependency hash changes; historical source inventories remain unchanged'))
    for name, value in inputs.pins.items():
        require(name not in reviewed['files'] or reviewed['files'][name] == value, 'conflicting reviewed input')
        reviewed['files'][name] = value
    reviewed_raw = U.canonical(reviewed)
    reviewed_path = HERE / 'reviewed-inputs.json'
    composed = copy.deepcopy(base)
    composed.update(root=str(TARGET), outputs=new_native, helpers=new_helpers, staged=reviewed['staged'],
                    stages=reviewed['stages'], reviewed_inputs=str(reviewed_path), reviewed_inputs_sha256=digest(reviewed_raw))
    composed_raw = U.canonical(composed)
    files = {**ext_code, **{rel(TARGET / name): digest(value) for name, value in payload.items() if name.endswith('.py')}}
    data = {**ext_data, **{rel(TARGET / name): digest(value) for name, value in payload.items() if not name.endswith('.py')},
            rel(TARGET / 'composition.json'): digest(composed_raw)}
    require(len(files) == len(old['files']) + 1 and len(data) == len(old['data_only']) and not set(files) & set(data),
            'successor code/data inventory differs')
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
    require(files[new_profile['advance_driver']['path']] == new_profile['advance_driver']['sha256'], 'driver hash mismatch')
    require(len(new_profile['modules']) == 20 and new_profile['completed_query_limits'] == profile['completed_query_limits'],
            'profile module/query policy changed')
    profile_raw = U.canonical(new_profile)
    boot = inputs.raw(BOOTSTRAP, BOOTSTRAP_SHA)
    for before, after in ((b'REAL_ROOT = T / "ac/p11-out/composed-r13"', b'REAL_ROOT = T / "ac/p1012-r1"'),
                          (b'REAL_COUNTS = (239, 389)', b'REAL_COUNTS = (239, 390)')):
        require(boot.count(before) == 1, 'bootstrap constant anchor differs')
        boot = boot.replace(before, after)
    inputs.recheck()
    record = dict(schema='atlas.private.plans10-12.integration.r1', status='PREPARED_SOURCE_ONLY',
        baseline={k: dict(path=str(p), sha256=s) for k, (p, s) in BASE_PINS.items()}, changes=changes,
        composition_sha256=digest(composed_raw), profile_sha256=digest(profile_raw), manifest_sha256=digest(manifest_raw),
        reviewed_inputs=dict(path=str(reviewed_path), sha256=digest(reviewed_raw)),
        bootstrap=dict(path=str(HERE / 'bootstrap_native.py'), sha256=digest(boot)),
        native_outputs=239, helper_outputs=390, external_code=14, external_data=104,
        source_inputs=inputs.pins, root_eligibility='NEW_PROFILE_REQUIRES_NEW_ELIGIBLE_ROOT',
        interval_authority=False, holds_released=False, scientific_acceptance=False,
        preserved='Earlier plans preserved byte-for-byte outside the explicit 18-file delta; disabled D5/P4/H5a remain disabled',
        scope='Selected lf3 heat plus current receipt consumers integrated with Plans01-11 and storage fixes; no Plan13/H3')
    for name, value in payload.items():
        write(TARGET / name, value)
    write(reviewed_path, reviewed_raw)
    write(TARGET / 'composition.json', composed_raw)
    write(RUNTIME / 'manifest.json', manifest_raw)
    write(RUNTIME / 'fresh-profile.json', profile_raw)
    write(RUNTIME / 'derivation.json', U.canonical(record))
    write(HERE / 'bootstrap_native.py', boot)
    inputs.recheck()
    U.composition(U.Inputs(), TARGET, digest(composed_raw), reviewed_path, digest(reviewed_raw))
    print(json.dumps(dict(status='PREPARED_SOURCE_ONLY', composition_sha256=digest(composed_raw),
        profile_sha256=digest(profile_raw), manifest_sha256=digest(manifest_raw), bootstrap_sha256=digest(boot),
        changed_files=len(replacements), unchanged_source_files=len(payload)-len(replacements),
        native_outputs=239, helper_outputs=390, held_interval_runs=True)))


if __name__ == '__main__':
    build()
