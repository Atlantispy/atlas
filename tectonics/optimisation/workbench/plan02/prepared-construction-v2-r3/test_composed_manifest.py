"""Frozen composed manifest and review records; source-only (no store or solve).

The allow-list manifest, its data-only references, the successor guard and
cold-binding pins, the restart profile and the runtime-compatibility policy
are checked against the bytes on disk. A fresh -I child runs the composed
runner's RestartProfile.read and RestartSources(profile).verify(), and the
composed runtime_compatibility.check_policy on the actual inventories.
"""
import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import assemble_resumable as A

TARGET = A.HERE/'composed-r1'
REVIEW = TARGET/'review'

CHILD = r'''
import importlib.util, json, sys
from pathlib import Path
runner, profile_path, profile_sha = sys.argv[1:4]
def bootstrap_runner(runner, profile_path, profile_sha):
    """Authenticate the selected profile/root and all three bootstrap modules before any executes."""
    from hashlib import sha256
    import importlib.util
    import json
    from pathlib import Path
    import re
    import stat
    import sys

    def require(condition, message):
        if not condition:
            raise ValueError('prepared child bootstrap refused: '+message)

    def ordinary(path, *, directory=False):
        path = Path(path).absolute()
        for part in (path, *path.parents):
            info = part.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                    'linked/reparsed source root')
        require(path.is_dir() if directory else path.is_file(), 'ordinary selected path required')
        require(str(path) == str(path.resolve()), 'canonical selected path required')
        return path

    def pinned(path, expected):
        require(type(expected) is str and re.fullmatch('[0-9a-f]{64}', expected), 'exact source pin required')
        path = ordinary(path)
        with path.open('rb') as stream:
            raw = stream.read((8 << 20)+1)
        require(len(raw) <= (8 << 20) and sha256(raw).hexdigest() == expected, 'selected bytes differ: '+str(path))
        return raw

    profile_path = ordinary(profile_path)
    profile = json.loads(pinned(profile_path, profile_sha))
    require(profile.get('schema') == 'atlas.prepared-restart-launch.v2', 'prepared profile required')
    workspace = ordinary(profile['workspace'], directory=True)
    target = ordinary(profile_path.parent.parent, directory=True)
    require(profile_path.parent.name == 'review' and profile_path.name == 'restart-profile-s2-r1.json' and
            target.is_relative_to(workspace), 'target-owned profile required')
    relative = target.relative_to(workspace).as_posix()
    binding = profile['source_manifest']
    require(binding['path'] == relative+'/manifest.json', 'profile names another manifest root')
    manifest = json.loads(pinned(target/'manifest.json', binding['sha256']))
    require(manifest.get('schema') == 'atlas.private.resumable-runtime-source.v2' and
            manifest.get('prepared_route') == 'legacy-prepared-construct_successor', 'selected prepared manifest required')
    helpers = ordinary(target/'helpers', directory=True)
    runner = ordinary(runner)
    require(runner == helpers/'run_prepared_restart.py' and
            manifest['restart_runner'] == relative+'/helpers/run_prepared_restart.py' and
            profile['native_root'] == manifest['layout']['native_root'] == relative+'/runtime-src' and
            profile['import_roots'] == manifest['layout']['import_roots'] and
            profile['import_roots'][0] == relative+'/helpers', 'selected runner/helper root differs')
    names = ('start_gate', 'route2_gate', 'run_prepared_restart')
    require(not any(name in sys.modules for name in names), 'bootstrap module already loaded')
    # Capture and pin ALL source bytes before dependent imports. Execute the
    # authenticated snapshots in order; do not add an unverified search root.
    blobs = {}
    for name in names:
        key = relative+'/helpers/'+name+'.py'
        require(key in manifest['files'], 'bootstrap module is not manifested: '+name)
        blobs[name] = pinned(helpers/(name+'.py'), manifest['files'][key])
    for name in names:
        path = helpers/(name+'.py')
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        exec(compile(blobs[name], str(path), 'exec', dont_inherit=True), module.__dict__)
        require(Path(module.__file__) == path, 'bootstrap module replaced its source identity')
    return sys.modules['run_prepared_restart']

RUN = bootstrap_runner(runner, profile_path, profile_sha)
profile = RUN.RestartProfile.read(Path(profile_path), profile_sha)
sources = RUN.RestartSources(profile)
proof = sources.verify()
row = profile.record()
helpers = Path(runner).resolve().parent
sys.path[:0] = [str(helpers)]
import runtime_compatibility as RC
policy = RUN.pinned_json(sources.path(row['compatibility_policy']['path']), row['compatibility_policy']['sha256'])
historical = RC.source_inventory(sources.path(row['historical_source_root'], directory=True))
current = RC.source_inventory(sources.native_root)
RC.check_policy(policy, historical=historical, current=current)
loaded = {name: Path(sys.modules[name].__file__).resolve().parent == helpers
          for name in ('runtime_compatibility', 'native_transfer', 'workflow_transfer')}
print(json.dumps(dict(proof=proof, policy_checked=True, loaded_from_helpers=loaded,
    output=str(RUN.canonical_absolute(row['output_directory'], 'restart output directory')),
    historical_paths=[e for e in sys.path if RUN.historical_import_path(sources.workspace, e)],
    delta=sorted(n for n in set(historical) | set(current) if historical.get(n) != current.get(n))), sort_keys=True))
'''


def run_policy_check(profile_path, *, timeout=600):
    profile_path = Path(profile_path)
    raw = profile_path.read_bytes()
    row = json.loads(raw)
    runner = (A.WORKSPACE/row['advance_driver']['path']).parent/'run_prepared_restart.py'
    environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    with tempfile.TemporaryDirectory(prefix='w3-policy-') as cwd:
        done = subprocess.run([sys.executable, '-B', '-I', '-c', CHILD, str(runner), str(profile_path),
                               sha256(raw).hexdigest()], capture_output=True, text=True, cwd=cwd,
                              env=environment, timeout=timeout)
    if done.returncode != 0:
        raise AssertionError('policy child failed: '+done.stderr[-6000:])
    return json.loads(done.stdout.strip().splitlines()[-1])


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def literal(raw, name):
    return A.literal(raw.decode('utf8') if type(raw) is bytes else raw, name)


def check_records(test, target, *, evidence_root=A.EVIDENCE_ROOT):
    """Everything below runs against an actual written target (frozen or dry)."""
    target = Path(target).resolve()
    relative = A.workspace_relative(target)
    manifest = json.loads((target/'manifest.json').read_bytes())
    files, data = manifest['files'], manifest['data_only']
    prior = json.loads((A.BASE/'manifest.json').read_bytes())
    # Allow-list: no inheritance of the predecessor files map.
    test.assertFalse(set(files) & set(data))
    inherited = set(files) & set(prior['files'])
    test.assertEqual({n for n in inherited if not n.startswith(A.HISTORICAL_TESTS_RELATIVE+'/')},
                     {A.HISTORICAL_RELATIVE+'/'+n for n in A.HISTORICAL_VALIDATORS})
    for name in files:
        test.assertFalse(name.startswith(A.workspace_relative(A.BASE)+'/'), name)
        test.assertNotIn('/native-composed-', name)
        test.assertTrue(name.startswith(relative+'/') or name.startswith(A.HISTORICAL_TESTS_RELATIVE+'/') or
                        Path(name).name in A.HISTORICAL_VALIDATORS, name)
    for name, pin in {**files, **data}.items():
        test.assertEqual(digest(A.WORKSPACE/name), pin, name)
    helpers = {p.name for p in (target/'helpers').glob('*.py')}
    ram = {p.name for p in (target/'ram').glob('*.py')}
    tests_dir = {p.name for p in A.HISTORICAL_TESTS.glob('*.py')}
    test.assertFalse(helpers & ram or helpers & tests_dir or ram & tests_dir)
    test.assertFalse(set(A.HISTORICAL_VALIDATORS) & helpers, 'M13: validators are executed from H only')
    test.assertEqual({n for n in files if n.startswith(relative+'/helpers/')},
                     {relative+'/helpers/'+n for n in helpers})
    # Native inventory: native-root-relative keys, complete, each pinned in files.
    inventory = A.native_inventory(target/'runtime-src')
    test.assertEqual(inventory, manifest['source_hashes'])
    test.assertEqual(sha256(A.canonical(inventory)).hexdigest(), manifest['native_source_digest'])
    for name, pin in inventory.items():
        test.assertEqual(files[relative+'/runtime-src/'+name], pin)
    test.assertEqual(manifest['stage_digests'], json.loads((A.HERE/'reviewed-inputs.json').read_bytes())['stage_digests'])
    # Preserved references: all 8 exactly bound; imported ones in files, the rest data-only.
    refs = manifest['heat_composition']['preserved_accounting_references']
    test.assertEqual(len(refs), 8)
    for name, pin in refs.items():
        test.assertEqual(files[name] if name in A.IMPORTED_REFERENCES else data[name], pin)
    # Successor guard: one directory, every pin equal.
    guard = target/'helpers'/'private_heat_continuation_guard_r3.py'
    admission = (target/'helpers'/'historical_admission.py').read_bytes()
    patch = (A.HERE/'resource_guard_patch.py').read_bytes()
    test.assertEqual({digest(guard), manifest['successor_guard_sha256'], literal(admission, 'GUARD_PIN'),
                      literal(patch, 'SUCCESSOR_PIN')},
                     {'9a2d7e8bcafe725ea861ebd455014fd50e25d152cb38cc709c3dba3347c42772'})
    test.assertEqual(digest(target/'helpers'/'windows_workload_job.py'), literal(admission, 'JOB_PIN'))
    test.assertEqual(digest(target/'helpers'/'private_heat_resource_diagnostics_r1.py'),
                     literal(admission, 'DIAGNOSTICS_PIN'))
    # Cold binding reconciled end to end.
    recovery = target/'ram'/'private_heat_restored_binding_ram_recovery_r1.py'
    context = target/'ram'/'private_heat_restored_binding_ram_context_r1.py'
    cold = (target/'runtime-src/atlas_tectonics/integration_private_heat_cold.py').read_text(encoding='utf8')
    test.assertEqual(cold.count("_BINDING_SHA = '"+digest(recovery)+"'\n"), 1)
    test.assertEqual(literal(recovery.read_bytes(), '_BINDING_SHA'), digest(context))
    pins = literal(context.read_bytes(), '_PINS')
    test.assertEqual(pins, {name: digest(target/'helpers'/name) for name in pins})
    # runtime.py: WORKSPACE resolves to T, and no H root is selected (M13).
    runtime = (target/'runtime.py').read_bytes()
    test.assertEqual(target.parents[4], A.WORKSPACE)
    test.assertIn(A.RUNTIME_WORKSPACE[1], runtime)
    test.assertIn(A.RUNTIME_ROOTS[1], runtime)
    test.assertNotIn(b'str(HEAT),', runtime)
    # Composed runner and reader pass the guard phase; the forced check stays unwrapped.
    for name in ('run_prepared_restart.py', 'reopen_prepared_restart.py'):
        tree = ast.parse((target/'helpers'/name).read_bytes())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, 'attr', None) == 'materialise']
        test.assertEqual(len(calls), 1, name)
        keywords = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
        test.assertEqual((keywords['phase'], keywords['check'], keywords['working_store']),
                         ('guard.phase', 'check', 'store'), name)
    # Required modules: exactly the composed runner's REQUIRED_MODULES, all pinned.
    required = literal((target/'helpers'/'run_prepared_restart.py').read_bytes(), 'REQUIRED_MODULES')
    test.assertEqual(set(manifest['required_modules']), set(required))
    for name, path in manifest['required_modules'].items():
        test.assertIn(path, files, name)
        test.assertEqual(Path(path).stem, name)
    # Profile (F section 3).
    profile = json.loads((target/'review'/A.PROFILE_NAME).read_bytes())
    test.assertEqual(profile['modules'], manifest['required_modules'])
    test.assertEqual(profile['import_roots'], [relative+'/helpers', relative+'/ram', A.HISTORICAL_TESTS_RELATIVE])
    test.assertEqual(profile['native_root'], relative+'/runtime-src')
    test.assertEqual(profile['source_manifest'], dict(path=relative+'/manifest.json', sha256=digest(target/'manifest.json')))
    test.assertEqual(profile['advance_driver'], dict(module='prepared_interval_driver',
                     path=relative+'/helpers/prepared_interval_driver.py',
                     sha256=digest(target/'helpers'/'prepared_interval_driver.py')))
    test.assertEqual(profile['preparation']['path'], A.PREPARATION)
    test.assertEqual(profile['compatibility_policy'], dict(path=relative+'/review/runtime-compatibility-policy.json',
                     sha256=digest(target/'review'/'runtime-compatibility-policy.json')))
    test.assertEqual(profile['historical_source_root'], A.HISTORICAL_NATIVE_RELATIVE)
    test.assertEqual(profile['evidence_root'], evidence_root)
    receipt = json.loads((A.HISTORICAL/A.HISTORICAL_RECEIPT[0]).read_bytes())['completed_endpoint']
    test.assertEqual((profile['store_limits'], profile['compression']),
                     (receipt['store_limits'], receipt['store_compression']))
    test.assertEqual(profile['completed_query_limits'], A.QUERY_LIMITS)
    output = Path(profile['output_directory'])
    test.assertEqual(str(output.resolve()), profile['output_directory'])
    queries = (A.WORKSPACE/profile['completed_query_directory']).resolve()
    test.assertFalse(queries.is_relative_to(output))
    test.assertNotIn(profile['source_manifest']['path'], files)
    # Policy (F section 3): historical identities and the exact actual delta.
    policy = json.loads((target/'review'/'runtime-compatibility-policy.json').read_bytes())
    test.assertEqual((policy['historical']['native_source_digest'], policy['historical']['source_manifest_sha256'],
                      policy['historical']['execution_identity']), (A.HISTORICAL_NATIVE_DIGEST,
                      A.HISTORICAL_SOURCE_MANIFEST[1], A.HISTORICAL_EXECUTION))
    review = json.loads((target/'review'/'helper-review.json').read_bytes())
    test.assertEqual(policy['current']['execution_identity'],
                     review['execution_identity_measurement']['execution_provenance']['execution_identity'])
    test.assertEqual(policy['current']['source_manifest_sha256'], profile['source_manifest']['sha256'])
    historical = A.native_inventory(A.WORKSPACE/A.HISTORICAL_NATIVE_RELATIVE)
    delta = {n for n in set(historical) | set(inventory) if historical.get(n) != inventory.get(n)}
    test.assertEqual(set(policy['reviewed_changes']), delta)
    for name, row in policy['reviewed_changes'].items():
        test.assertEqual((row['before'], row['after']), (historical.get(name), inventory.get(name)))
        test.assertTrue(row['reason'].strip() and row['evidence'] and set(row['evidence']) <= set(policy['evidence']))
    root = (A.WORKSPACE/evidence_root).resolve()
    for name, pin in policy['evidence'].items():
        test.assertEqual(digest(root/name), pin, name)
    test.assertEqual(digest(root/policy['current']['source_manifest_path']), profile['source_manifest']['sha256'])
    test.assertEqual(digest(root/policy['historical']['source_manifest_path']), A.HISTORICAL_SOURCE_MANIFEST[1])
    # Helper review covers every composed helper, ram module and runtime.py.
    test.assertEqual(set(review['entries']), {n[len(relative)+1:] for n in files if n.startswith(relative+'/') and
                                              not n.startswith(relative+'/runtime-src/')})
    for row in review['entries'].values():
        test.assertEqual(len(row['reviewed_by']), 2)
    return manifest, profile, policy


def check_child(test, result, profile_path):
    row = json.loads(Path(profile_path).read_bytes())
    test.assertTrue(result['policy_checked'])
    test.assertEqual(result['proof']['source_manifest_sha256'], row['source_manifest']['sha256'])
    test.assertEqual(result['loaded_from_helpers'], {'runtime_compatibility': True, 'native_transfer': True,
                                                     'workflow_transfer': True})
    test.assertEqual(result['output'], row['output_directory'])
    test.assertEqual(result['historical_paths'], [])


class ComposedManifest(unittest.TestCase):
    def setUp(self):
        if not (REVIEW/A.PROFILE_NAME).is_file():
            self.skipTest('composed-r1 review records not written yet')

    def test_allow_list_references_bindings_profile_and_policy(self):
        check_records(self, TARGET)

    def test_profile_reads_sources_verify_and_policy_checks_in_fresh_process(self):
        profile = REVIEW/A.PROFILE_NAME
        check_child(self, run_policy_check(profile), profile)


if __name__ == '__main__':
    unittest.main(verbosity=2)
