"""Route (1) profile (and, if absent, manifest) over a FROZEN composition, checked by the runner itself.

Usage: python -B frozen_route1_profile.py FROZEN SMOKE_DIR

FROZEN holds src/ (the native package) and helpers/ (every helper flattened, including the
route (1) runner family, which runs from there). Import roots: [FROZEN/helpers, H tests]; no
live R or C. If FROZEN/manifest.json exists (the composer's) it is used as is; otherwise
SMOKE_DIR/manifest-N.json is written in the s1 builder's format (compose_route1_smoke.py): every
native .py plus the top-level .py of each import root, data_only {}, completed_query_store
"files", source_hashes, composition. SMOKE_DIR/profile-N.json binds each FRESH_MODULE to its
first resolution over the roots and the driver to FROZEN/helpers/fresh_interval_driver.py.

Checks, before printing the launch command: the runner family is present in FROZEN/helpers;
run_fresh_interval and run_prepared_restart are imported FROM FROZEN/helpers (as the launcher
started there will); FreshProfile.read and FreshSources.verify pass (own-file pins, native
inventory, helper bindings, driver); the launcher's PINNED files are in the manifest at that
folder. SMOKE_DIR is created if absent; nothing in FROZEN is written.
"""
import json
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
WORKSPACE = R.parents[3]
H_TESTS = WORKSPACE/'fidelity-integration-20261005'/'heat-repair-20261007'/'source'/'tectonics'/'tests'
FAMILY = ('launch_fresh_interval.py', 'launch_monitored_interval.py', 'run_fresh_interval.py',
          'run_prepared_restart.py', 'reopen_fresh_restart.py', 'reopen_prepared_restart.py',
          'fresh_interval_driver.py')


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def relative(path):
    return Path(path).resolve().relative_to(WORKSPACE).as_posix()


def published(frozen):
    """Root rule and integrity of a published composition (composition.json), when it has one.

    Coordinator rule (16 Oct 2026): a composition runs only from its permanent root, because
    heat result IDs bind absolute helper source paths. The root must equal composition.json's
    root and the reviewed inputs' target_root (normcase of the resolved path), the reviewed
    inputs must match their recorded SHA-256, and every helper and native file must equal the
    digest composition.json records for it, with nothing missing or extra.
    """
    import os
    record_path = frozen/'composition.json'
    if not record_path.is_file():
        return None
    record = json.loads(record_path.read_text(encoding='utf8'))
    same = lambda a, b: os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    inputs_path = WORKSPACE/record['reviewed_inputs']
    if digest(inputs_path) != record['reviewed_inputs_sha256']:
        raise SystemExit('reviewed inputs differ from their recorded SHA-256')
    inputs = json.loads(inputs_path.read_text(encoding='utf8'))
    if not (same(frozen, record['root']) and same(frozen, inputs['target_root'])):
        raise SystemExit('composition root rule refused: run only from '+record['root'])
    helpers = {path.name: digest(path) for path in (frozen/'helpers').glob('*.py')}
    native = {path.relative_to(frozen/'src').as_posix(): digest(path) for path in (frozen/'src').rglob('*.py')}
    if helpers != record['helpers'] or native != record['outputs']:
        raise SystemExit('published composition differs from composition.json')
    return {'composition_sha256': digest(record_path), 'reviewed_inputs_sha256': record['reviewed_inputs_sha256'],
            'root': record['root'], 'helpers': len(helpers), 'native': len(native)}


def main():
    frozen, smoke = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    native_root, helpers = frozen/'src', frozen/'helpers'
    roots = (helpers, H_TESTS)
    composition = published(frozen)
    missing = [name for name in FAMILY if not (helpers/name).is_file()]
    if missing:
        raise SystemExit('route (1) runner family missing from the frozen helpers: '+', '.join(missing))
    sys.path.insert(0, str(helpers))
    import run_fresh_interval as F
    import run_prepared_restart as RUN
    for module in (F, RUN):
        if Path(module.__file__).resolve().parent != helpers:
            raise SystemExit('runner module not imported from the frozen helpers: '+module.__name__)
    smoke.mkdir(parents=True, exist_ok=True)
    number = 1+sum(1 for _ in smoke.glob('profile-*.json'))
    manifest_path = frozen/'manifest.json'
    if not manifest_path.is_file():
        native = sorted((native_root/'atlas_tectonics').rglob('*.py'))
        files = {relative(path): digest(path) for path in native}
        for root in roots:
            for path in sorted(root.glob('*.py')):
                files.setdefault(relative(path), digest(path))
        value = {'files': files, 'data_only': {}, F.QUERY_STORE_FLAG: 'files',
                 'source_hashes': {path.relative_to(native_root).as_posix(): digest(path) for path in native},
                 'composition': {'frozen': relative(frozen), 'import_root_order': [relative(root) for root in roots],
                                 'published': composition}}
        manifest_path = smoke/f'manifest-{number}.json'
        with manifest_path.open('x', encoding='utf8') as stream:
            json.dump(value, stream, sort_keys=True, separators=(',', ':'))

    def first_resolution(name):
        for root in roots:
            for candidate in (root/name/'__init__.py', root/(name+'.py')):
                if candidate.is_file():
                    return candidate
        raise SystemExit('route (1) helper not found over the frozen roots: '+name)

    driver = helpers/'fresh_interval_driver.py'
    attempt = smoke/f'attempt-{number}'
    attempt.mkdir()
    profile = {'schema': F.PROFILE_SCHEMA, 'workspace': str(WORKSPACE.resolve()),
               'source_manifest': {'path': relative(manifest_path), 'sha256': digest(manifest_path)},
               'native_root': relative(native_root), 'import_roots': [relative(root) for root in roots],
               'modules': {name: relative(first_resolution(name)) for name in F.FRESH_MODULES},
               'advance_driver': {'module': F.DRIVER, 'path': relative(driver), 'sha256': digest(driver)},
               'output_directory': str(attempt), 'store_directory': str(smoke/f'store-{number}'),
               'completed_query_directory': relative(smoke)+f'/queries-{number}',
               'completed_query_limits': {'max_entries': 2000000, 'max_store_bytes': 8 << 30}}
    profile_path = smoke/f'profile-{number}.json'
    with profile_path.open('x', encoding='utf8') as stream:
        json.dump(profile, stream, sort_keys=True, separators=(',', ':'))
    read = F.FreshProfile.read(profile_path, digest(profile_path))
    verified = F.FreshSources(read).verify()
    pins = json.loads(manifest_path.read_text(encoding='utf8'))['files']
    unpinned = [name for name in ('run_fresh_interval.py', 'run_prepared_restart.py', 'reopen_fresh_restart.py',
                                  'reopen_prepared_restart.py')
                if pins.get(relative(helpers/name)) != digest(helpers/name)]
    if unpinned:
        raise SystemExit("the launcher's pinned runner files are not in the manifest: "+', '.join(unpinned))
    print(json.dumps({'manifest': str(manifest_path), 'profile': str(profile_path),
                      'profile_sha256': digest(profile_path), 'verified': verified, 'published': composition,
                      'launcher': str(helpers/'launch_fresh_interval.py')}))


if __name__ == '__main__':
    main()
