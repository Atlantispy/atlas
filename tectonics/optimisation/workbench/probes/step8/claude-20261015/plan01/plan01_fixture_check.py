"""Plan 01 bounded fixture check for test_wp10_integration's scoped candidate setup.

Usage: python -B plan01_fixture_check.py <compact folder>           (runs every case in a child)
       python -B plan01_fixture_check.py <compact folder> <case>    (one case)
"""
import subprocess
import sys
import unittest.case
from pathlib import Path

NAMES = ('atlas_tectonics.storage', 'interval_store_set', 'segment_store')
ABSENT = object()
CASES = ('absent_normal', 'existing_normal', 'absent_failed', 'existing_failed', 'omitted_restore_detected')


def state():
    package = sys.modules.get('atlas_tectonics')
    return dict(path=list(sys.path), modules={n: sys.modules.get(n, ABSENT) for n in NAMES},
        package=package, parent=ABSENT if package is None else package.__dict__.get('storage', ABSENT))


def is_candidate(module):
    # Candidates are compiled under '<path>[wp10-candidate]'; their own functions carry it.
    return module is not ABSENT and any('[wp10-candidate]' in f.__code__.co_filename
        for f in vars(module).values() if hasattr(f, '__code__'))


def problems(before, after):
    out = []
    if after['path'] != before['path']:
        out.append('sys.path not restored')
    for name in NAMES:
        b, a = before['modules'][name], after['modules'][name]
        if is_candidate(a):
            out.append(f'{name} still a candidate')
        elif b is not ABSENT and a is not b:
            out.append(f'{name} not the original object')
        elif b is ABSENT and name != 'atlas_tectonics.storage' and a is not ABSENT:
            out.append(f'{name} present though absent before')
    package = after['package']
    if package is not None:
        parent = package.__dict__.get('storage', ABSENT)
        if is_candidate(parent):
            out.append('parent storage attribute still a candidate')
        elif parent is not after['modules']['atlas_tectonics.storage'] and parent is not ABSENT:
            out.append('parent storage attribute differs from sys.modules entry')
    return out


def run_case(compact, case):
    sys.path.insert(0, compact)
    if case.startswith('existing'):
        # Real (native) modules loaded first, as earlier suite modules do.
        here = Path(compact)
        sys.path[:0] = [str(here), str(here.parent / 'composed-r1' / 'runtime-src')]
        import atlas_tectonics.storage, interval_store_set, segment_store  # noqa: F401
    before = state()
    import test_wp10_integration as mod
    discovery = problems(before, state())
    if discovery or any(is_candidate(m) for m in state()['modules'].values()):
        return ['discovery mutated state: ' + '; '.join(discovery)]
    if case == 'omitted_restore_detected':
        mod._restore = lambda saved: None
    if case.endswith('failed'):
        real = mod._candidate_module

        def failing(name, path, code):
            if name == 'segment_store':
                raise RuntimeError('deliberate setup failure')
            return real(name, path, code)
        mod._candidate_module = failing
    failed = False
    try:
        mod.setUpModule()
        installed = state()
        if not (is_candidate(installed['modules']['segment_store'])
                and installed['modules']['segment_store'] is mod.segments):
            return ['candidates were not installed by setUpModule']
    except RuntimeError:
        failed = True
        if not is_candidate(state()['modules']['interval_store_set']):
            return ['failure injected before the interval candidate was installed']
    if failed != case.endswith('failed'):
        return [f'unexpected failure state {failed}']
    unittest.case.doModuleCleanups()
    found = problems(before, state())
    if case == 'omitted_restore_detected':
        return [] if found else ['omitted restoration was NOT detected']
    return found


if __name__ == '__main__':
    compact = sys.argv[1]
    if len(sys.argv) > 2:
        result = run_case(compact, sys.argv[2])
        print('PASS' if not result else 'FAIL ' + '; '.join(result))
        sys.exit(1 if result else 0)
    bad = 0
    for case in CASES:
        child = subprocess.run([sys.executable, '-B', __file__, compact, case],
            cwd=compact, capture_output=True, text=True)
        line = (child.stdout.strip().splitlines() or ['(no output)'])[-1]
        print(f'{case}: {line}' + ('' if child.returncode == 0 else ' | ' + child.stderr.strip()[-400:]))
        bad += child.returncode != 0
    print(f'fixture-check cases={len(CASES)} failed={bad}')
    sys.exit(1 if bad else 0)
