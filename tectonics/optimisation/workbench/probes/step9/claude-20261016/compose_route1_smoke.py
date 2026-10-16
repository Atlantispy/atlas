"""Interim TEST-ONLY route (1) composition for the smoke and the post-advance proof (coordinator, 16 Oct 2026).

Usage:
  python -B compose_route1_smoke.py compose TARGET    new TARGET: base I plus the LIVE transforms
  python -B compose_route1_smoke.py manifest TARGET   closed manifest and profile over TARGET's tree

compose: test_step8_runtime.compose_live_fixture writes TARGET/src (I's package with
the live cursor, spatial v1/v3, partition v1+v2, validation, restart-patch, owner,
mimetic and exterior-mesh transforms). Its own TARGET/helpers copies are left on
disk but are NOT import roots: the run imports live R, then live C, then
composed-r1/helpers and composed-r1/ram (the r9-era heat helpers exist only there;
H's root is fenced), then H's retained tests.

manifest: pins every .py of the native tree and the top level of each import root
(files, workspace-relative; source_hashes, native-root-relative), declares
completed_query_store "files" (WP17 is not enabled before Step 10), binds each
route (1) helper to its first resolution over the roots and writes
TARGET/manifest-<n>.json and TARGET/profile-<n>.json exclusively. Rerun it after
any live source changes; nothing in I, RC1, H or the live trees is written.
This is not the Step 10 composition and never a production profile.
"""
import json
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
WORKSPACE = R.parents[3]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'
K = R/'composed-r1'
H_TESTS = WORKSPACE/'fidelity-integration-20261005'/'heat-repair-20261007'/'source'/'tectonics'/'tests'
ROOTS = (R, C, K/'helpers', K/'ram', H_TESTS)


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def relative(path):
    return Path(path).resolve().relative_to(WORKSPACE).as_posix()


def compose(target):
    target.mkdir()
    sys.path[:0] = [str(C), str(I), str(R)]
    import test_step8_runtime as S8
    sources = S8.compose_live_fixture(target)
    (target/'composition.json').write_text(json.dumps({
        'schema': 'atlas.private.route1-smoke-composition.v1', 'base': relative(I),
        'recipe': 'test_step8_runtime.compose_live_fixture', 'recipe_sha256': digest(R/'test_step8_runtime.py'),
        'test_only': True, 'composed_sources': sources}, indent=1, sort_keys=True), encoding='utf8')
    print(json.dumps({'composed': str(target), 'native_files': sum(1 for _ in (target/'src').rglob('*.py'))}))


def first_resolution(name):
    for root in ROOTS:
        for candidate in (root/name/'__init__.py', root/(name+'.py')):
            if candidate.is_file():
                return candidate
    raise SystemExit('route (1) helper not found over the import roots: '+name)


def manifest(target):
    sys.path.insert(0, str(R))
    import run_fresh_interval as F
    native_root = target/'src'
    native = sorted((native_root/'atlas_tectonics').rglob('*.py'))
    files = {relative(path): digest(path) for path in native}
    for root in ROOTS:
        for path in sorted(root.glob('*.py')):
            files.setdefault(relative(path), digest(path))
    number = 1+sum(1 for _ in target.glob('manifest-*.json'))
    value = {'files': files, 'data_only': {}, F.QUERY_STORE_FLAG: 'files',
             'source_hashes': {path.relative_to(native_root).as_posix(): digest(path) for path in native},
             'composition': {'test_only': True, 'composition_record': relative(target/'composition.json'),
                             'composition_record_sha256': digest(target/'composition.json'),
                             'import_root_order': [relative(root) for root in ROOTS]}}
    manifest_path = target/f'manifest-{number}.json'
    with manifest_path.open('x', encoding='utf8') as stream:
        json.dump(value, stream, sort_keys=True, separators=(',', ':'))
    driver = R/'fresh_interval_driver.py'
    attempt = (target/f'attempt-{number}').resolve()
    attempt.mkdir()
    profile = {'schema': F.PROFILE_SCHEMA, 'workspace': str(WORKSPACE.resolve()),
               'source_manifest': {'path': relative(manifest_path), 'sha256': digest(manifest_path)},
               'native_root': relative(native_root), 'import_roots': [relative(root) for root in ROOTS],
               'modules': {name: relative(first_resolution(name)) for name in F.FRESH_MODULES},
               'advance_driver': {'module': F.DRIVER, 'path': relative(driver), 'sha256': digest(driver)},
               'output_directory': str(attempt), 'store_directory': str(attempt.parent/f'store-{number}'),
               'completed_query_directory': relative(target)+f'/queries-{number}',
               'completed_query_limits': {'max_entries': 2000000, 'max_store_bytes': 8 << 30}}
    profile_path = target/f'profile-{number}.json'
    with profile_path.open('x', encoding='utf8') as stream:
        json.dump(profile, stream, sort_keys=True, separators=(',', ':'))
    F.FreshProfile.read(profile_path, digest(profile_path))
    print(json.dumps({'manifest': str(manifest_path), 'files': len(files), 'profile': str(profile_path),
                      'profile_sha256': digest(profile_path)}))


def main():
    action, target = sys.argv[1], Path(sys.argv[2]).resolve()
    if action == 'compose':
        compose(target)
    elif action == 'manifest':
        manifest(target)
    else:
        raise SystemExit('compose or manifest')


if __name__ == '__main__':
    main()
