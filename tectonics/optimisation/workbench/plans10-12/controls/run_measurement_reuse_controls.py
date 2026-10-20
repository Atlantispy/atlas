"""Ten synthetic Plan10 controls against the explicitly pinned final composition.

Uses the retained checked-source helper loader, without its whole-composition
inventory scan. No Atlas import or production store is permitted or needed.
"""
import argparse
from hashlib import sha256
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


HERE = Path(__file__).resolve().parent
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
ROOT = T / 'ac/p1012-r1'
BOOTSTRAP = HERE.parents[1] / 'plan11/native-entry-r1/bootstrap_native.py'
BOOTSTRAP_SHA = 'f5009a2d9907a4835197714a86587ea4390a7d75a7eb830ca62311c594cc71f5'
TEST_NAME = 'test_launch_fresh_interval'
TEST_SHA = '74e56e162d4936c98153cd4ea10156548600ee2c5eb6b5d332c2d6003bcfc33b'
METHODS = (
    'test_the_seed_is_the_adopted_root_receipt_and_the_store_pin_it_recorded',
    'test_anything_but_a_cleanly_adopted_root_stage_refuses',
    'test_changed_records_or_an_unnamed_store_refuse',
    'test_reuse_is_an_interval_stage_flag_only',
    'test_a_seeded_stage_passes_the_pins_and_reports_the_reuse',
    'test_a_runner_record_without_reuse_for_these_pins_stops_before_the_reader',
    'test_the_milestone_names_only_matching_pins',
    'test_valid_measured_misses_are_reported_and_continue_to_the_reader',
    'test_inconsistent_reuse_stops_before_reader_or_smoke_success',
    'test_the_milestone_refuses_malformed_or_inconsistent_counts_and_bytes',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def bootstrap():
    raw = BOOTSTRAP.read_bytes()
    require(sha256(raw).hexdigest() == BOOTSTRAP_SHA, 'retained loader source changed')
    spec = importlib.util.spec_from_file_location('_plan10_control_loader', BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(BOOTSTRAP), 'exec', dont_inherit=True), module.__dict__)
    module.checked_raw(BOOTSTRAP, BOOTSTRAP_SHA)
    module.validate_runtime()
    return module


class NoAtlas(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'atlas_tectonics' or fullname.startswith('atlas_tectonics.'):
            raise ImportError('actual Atlas imports forbidden in Plan10 synthetic controls')
        return None


def run(pin):
    loader = bootstrap()
    composition = ROOT / 'composition.json'
    require(loader.ordinary(composition).stat().st_size <= loader.MAX_COMPOSITION_BYTES,
            'composition exceeds bounded JSON size')
    raw = loader.checked_raw(composition, pin)
    row = json.loads(raw, object_pairs_hook=loader._pairs, parse_constant=loader._invalid_number)
    require(type(row) is dict and Path(row.get('root', '')) == ROOT,
            'composition must identify the final p1012-r1 root')
    require(type(row.get('helpers')) is dict and row['helpers'].get(TEST_NAME + '.py') == TEST_SHA,
            'final composition must include the corrected Plan10 test helper')
    helpers = {}
    for name, digest in row['helpers'].items():
        relative = loader._relative_name(name)
        require(loader.full_sha(digest), 'invalid declared helper pin: ' + name)
        if len(relative.parts) == 1 and relative.suffix == '.py':
            require(relative.stem.isidentifier(), 'invalid declared helper module: ' + name)
            helpers[relative.stem] = (ROOT / 'helpers' / name, digest)
    require('launch_fresh_interval' in helpers, 'final launcher declaration is missing')
    require(not any(name in sys.modules for name in helpers), 'preloaded same-name helper refused')
    require(not any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.') for name in sys.modules),
            'preloaded Atlas module refused')
    finder = loader.HelperFinder(SimpleNamespace(helpers=helpers))
    guard = NoAtlas()
    path_before, meta_before = list(sys.path), list(sys.meta_path)
    sys.meta_path[:0] = [guard, finder]
    result = None
    try:
        tests = __import__(TEST_NAME)
        cls = tests.MeasurementReuseTests
        require(set(unittest.defaultTestLoader.getTestCaseNames(cls)) == set(METHODS),
                'the ten selected MeasurementReuseTests changed')
        # The original fixture uses HERE as its workspace. Use bounded copies of
        # its nine pinned orchestration files so no final source directory gets
        # transient fixture outputs. Executed helpers remain the actual final files.
        with tempfile.TemporaryDirectory(prefix='p10-controls-', dir=HERE) as directory:
            fixture = Path(directory)
            for filename in tests.L.PINNED:
                source, source_pin = helpers[Path(filename).stem]
                require(source.name == filename, 'fixture helper name differs')
                with (fixture / filename).open('xb') as stream:
                    stream.write(loader.checked_raw(source, source_pin))
            tests.HERE = fixture
            result = unittest.TextTestRunner(verbosity=2).run(
                unittest.TestSuite(cls(name) for name in METHODS))
    finally:
        try:
            require(not any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.')
                            for name in sys.modules), 'actual Atlas import appeared')
            require(sys.meta_path == [guard, finder, *meta_before], 'synthetic import guard changed')
            finder.verify_loaded()
            loader.checked_raw(composition, pin)
            loader.checked_raw(BOOTSTRAP, BOOTSTRAP_SHA)
        finally:
            sys.path[:] = path_before
            sys.meta_path[:] = meta_before
            for name in finder.loaded:
                sys.modules.pop(name, None)
    passed = (result.wasSuccessful() and result.testsRun == len(METHODS) and not result.skipped
              and not result.expectedFailures and not result.unexpectedSuccesses)
    print(json.dumps({'passed': passed, 'selected_controls': len(METHODS), 'tests_run': result.testsRun,
                      'failures': len(result.failures), 'errors': len(result.errors),
                      'composition_sha256': pin, 'test_sha256': TEST_SHA,
                      'loader_sha256': BOOTSTRAP_SHA, 'actual_atlas_imports': False,
                      'synthetic_only': True, 'scientific_acceptance': False,
                      'loaded_helper_sha256': {name: value[2] for name, value in sorted(finder.loaded.items())}}),
          flush=True)
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--composition-sha256', required=True)
    args = parser.parse_args()
    return run(args.composition_sha256)


if __name__ == '__main__':
    raise SystemExit(main())
