"""Composed import fence in a FRESH process (no store, database, solve or launch).

The child selects the frozen composed tree only through the composed runner's
RestartSources and the restart profile: native root, composed helpers and ram,
and the historical tests directory. It imports every REQUIRED_MODULE, the
driver, the reader, every native module and ExecutionContext, then requires
check_imported()/check_paths() to be clean and every atlas_tectonics module to
come from the composed native root. Adverse cases are checked by module
identity only (nothing historical is executed): a historical package or H root
on sys.path, an H original of a composed helper, a data-only reference and a
native module outside the root must all refuse, and unpinned workspace imports
through the finder must refuse before execution.
"""
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
PROFILE = TARGET/'review'/A.PROFILE_NAME

CHILD = r'''
import importlib, importlib.util, json, sys, types
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
row, result = profile.record(), {}
result['proof'] = sources.verify()
manifest = json.loads(sources.manifest_path.read_bytes())
H = sources.workspace/RUN.HISTORICAL_RELATIVE
native = sources.native_root/'atlas_tectonics'
with sources.selected():
    result['sys_path_head'] = sys.path[:1+len(sources.import_roots)]
    bound = {name: sources.module(name) for name in RUN.REQUIRED_MODULES}
    driver = sources.module(row['advance_driver']['module'])
    for extra in ('reopen_prepared_restart', 'probe_execution_identity'):
        importlib.import_module(extra)
    names = []
    for path in sorted(native.rglob('*.py')):
        parts = path.relative_to(sources.native_root).with_suffix('').parts
        names.append('.'.join(parts[:-1] if parts[-1] == '__init__' else parts))
    failures = {}
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as error:
            failures[name] = type(error).__name__+': '+str(error)[:300]
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    require_strict_execution()
    with ExecutionContext('scipy') as execution:
        result['execution_provenance'] = dict(execution.provenance)
    result['native_import_failures'] = failures
    result['native_modules'] = len(names)
    imported = sources.check_imported()
    sources.check_paths()
    atlas = {n: m.__file__ for n, m in tuple(sys.modules.items())
             if n == 'atlas_tectonics' or n.startswith('atlas_tectonics.')}
    result['atlas_loaded'] = len(atlas)
    result['atlas_outside_root'] = sorted(n for n, f in atlas.items()
                                          if not Path(f).resolve().is_relative_to(native))
    helpers = (sources.native_root.parent/'helpers').resolve()
    result['required_module_files'] = {n: Path(m.__file__).resolve().relative_to(sources.workspace).as_posix()
                                       for n, m in bound.items()}
    result['driver_file'] = Path(driver.__file__).resolve().relative_to(sources.workspace).as_posix()
    result['imported_workspace_sources'] = len(imported)
    result['imported_outside_selected'] = sorted(n for n in imported if not any(
        (sources.workspace/n).resolve().is_relative_to(root) for root in (sources.native_root, *sources.import_roots)))
    adverse = {}
    def refused(label, action):
        try:
            action()
        except RUN.RestartRefused as error:
            adverse[label] = 'refused: '+str(error)[:160]
        else:
            adverse[label] = 'ACCEPTED'
    def fake(name, file, action):
        module = types.ModuleType(name)
        module.__file__ = str(file)
        sys.modules[name] = module
        try:
            refused(name, action)
        finally:
            del sys.modules[name]
    for label, entry in (('h_package_src_on_sys_path', H/'source'/'tectonics'/'src'), ('h_root_on_sys_path', H),
                         ('h_native_composed_on_sys_path', H/'native-composed-r7'/'tectonics'/'src')):
        sys.path.insert(0, str(entry))
        try:
            refused(label, sources.check_paths)
        finally:
            sys.path.remove(str(entry))
    fake('h_original_composed_helper', H/'private_heat_original_continuation_r1.py', sources.check_imported)
    data = sorted(n for n in manifest['data_only'] if n.endswith('.py'))
    fake('data_only_reference', sources.workspace/data[0], sources.check_imported)
    fake('atlas_tectonics.outside_native_root', H/'source/tectonics/src/atlas_tectonics/integration_exact_gmp.py',
         sources.check_imported)
    for label, name in (('unpinned_test_import_via_finder', 'i04_differential_predictor'),
                        ('data_only_import_via_finder', 'i04_differential_continuation_control')):
        refused(label, lambda name=name: importlib.import_module(name))
        sys.modules.pop(name, None)
    result['adverse'] = adverse
    result['final_imported'] = len(sources.check_imported())
result['proof_after'] = sources.verify()
print(json.dumps(result, sort_keys=True))
'''


def launch_environment():
    environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    environment.update(A.LAUNCH_ENVIRONMENT)
    return environment


def run_fence(profile_path, *, timeout=900):
    """One fresh -I child against the composed tree the profile names; returns its JSON."""
    profile_path = Path(profile_path)
    raw = profile_path.read_bytes()
    row = json.loads(raw)
    runner = A.WORKSPACE/row['advance_driver']['path']
    runner = runner.parent/'run_prepared_restart.py'
    with tempfile.TemporaryDirectory(prefix='w3-fence-') as cwd:
        done = subprocess.run([sys.executable, '-B', '-I', '-c', CHILD, str(runner), str(profile_path),
                               sha256(raw).hexdigest()], capture_output=True, text=True, cwd=cwd,
                              env=launch_environment(), timeout=timeout)
    if done.returncode != 0:
        raise AssertionError('fence child failed: '+done.stderr[-6000:])
    return json.loads(done.stdout.strip().splitlines()[-1])


def check_fence(test, result, profile_path):
    row = json.loads(Path(profile_path).read_bytes())
    manifest = json.loads((A.WORKSPACE/row['source_manifest']['path']).read_bytes())
    test.assertEqual(result['proof'], result['proof_after'])
    test.assertEqual(result['proof']['source_manifest_sha256'], row['source_manifest']['sha256'])
    test.assertEqual(result['proof']['native_source_digest'], manifest['native_source_digest'])
    test.assertEqual(result['native_import_failures'], {})
    test.assertEqual(result['native_modules'], len(manifest['source_hashes']))
    test.assertEqual(result['atlas_outside_root'], [])
    test.assertGreaterEqual(result['atlas_loaded'], len(manifest['source_hashes']))
    test.assertEqual(result['required_module_files'], row['modules'])
    test.assertEqual(result['driver_file'], row['advance_driver']['path'])
    test.assertEqual(result['imported_outside_selected'], [])
    test.assertEqual(result['execution_provenance']['execution_mode'], 'strict')
    test.assertEqual([Path(p).resolve() for p in result['sys_path_head']],
                     [(A.WORKSPACE/p).resolve() for p in (row['native_root'], *row['import_roots'])])
    for label, outcome in result['adverse'].items():
        test.assertTrue(outcome.startswith('refused: '), label+' was '+outcome)
    test.assertEqual(set(result['adverse']), {
        'h_package_src_on_sys_path', 'h_root_on_sys_path', 'h_native_composed_on_sys_path',
        'h_original_composed_helper', 'data_only_reference', 'atlas_tectonics.outside_native_root',
        'unpinned_test_import_via_finder', 'data_only_import_via_finder'})


class ComposedImportFence(unittest.TestCase):
    def test_fresh_process_composed_selection_and_refusals(self):
        if not PROFILE.is_file():
            self.skipTest('composed-r1 review records not written yet')
        result = run_fence(PROFILE)
        check_fence(self, result, PROFILE)
        review = json.loads((TARGET/'review'/'helper-review.json').read_bytes())
        # The fence measures the same strict identity the policy reviewed.
        self.assertEqual(result['execution_provenance'],
                         review['execution_identity_measurement']['execution_provenance'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
