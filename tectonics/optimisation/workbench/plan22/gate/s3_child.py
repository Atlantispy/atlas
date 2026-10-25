"""Child of gate_s3l3.py: run one S3/L3 focused suite on an S3-layout fixture, as specified by a JSON spec.

PYTHONHASHSEED=0 python -B s3_child.py SPEC.json      (never -I: the suites import the runtime)

The spec names the fixture helpers and runtime-src folders, the pinned files (path -> sha256, all checked before any
import), the mode and the output path (must not exist). Modes:
  lazy        test_s3_lazy_rows: all 20 must pass
  consumers   test_d1b_carried_start + test_spatial_compact_cells through the reviewer's loader seams: all 17 must pass
  carry       test_s3_l3_fallback: both stored-segment fallback cases must pass
  own         test_l3_carried_pages: all must pass (the spec's expected_runs: 22 for port-r3), with record_views
              loaded from the fixture
  negative    test_s3_lazy_rows on a fixture without the S3 runtime change: all 20 must run, and at least one but not
              all must fail or error (a fixture that cannot run is not a detection)
Every mode also requires that no module was loaded from outside the fixture and the interpreter.
Adapted from Plan 21's unit_n12f_r2.py 4cdee5e9 (fixture paths and pins now come from the spec); the consumers
loader seams are its copy of review-r1/focused_adapter.py 1bd1d64d, verbatim.
"""
import ast
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import sys
import unittest

EXPECTED_RUNS = {'lazy': 20, 'consumers': 17, 'own': 22, 'carry': 2, 'negative': 20}  # a spec's expected_runs overrides


class Results(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def addSuccess(self, test):
        self.outcomes[test.id()] = 'ok'
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.outcomes[test.id()] = 'failure'
        super().addFailure(test, err)

    def addError(self, test, err):
        self.outcomes[test.id()] = 'error'
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.outcomes[test.id()] = 'skip'
        super().addSkip(test, reason)


def test_count(path):
    tree = ast.parse(path.read_text(encoding='utf8'))
    return sum(isinstance(item, ast.FunctionDef) and item.name.startswith('test_')
               for node in tree.body if isinstance(node, ast.ClassDef) for item in node.body)


def loaded_outside(fixture_root):
    roots = [fixture_root.resolve(), Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    found = []
    for module in list(sys.modules.values()):
        path = getattr(module, '__file__', None)
        if not path or getattr(module, '__name__', None) == '__main__':
            continue
        path = Path(path).resolve()
        if not any(root in path.parents for root in roots):
            found.append(str(path))
    return sorted(found)


def main():
    spec = json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
    mode, output = spec['mode'], Path(spec['output'])
    if mode not in EXPECTED_RUNS:
        raise SystemExit('unknown mode ' + mode)
    if output.exists():
        raise SystemExit('output exists: ' + str(output))
    if os.environ.get('PYTHONHASHSEED') != '0' or sys.flags.hash_randomization or not sys.dont_write_bytecode \
            or sys.flags.isolated or sys.flags.optimize:
        raise SystemExit('refusing: run with PYTHONHASHSEED=0, -B, without -I or -O')
    helpers, native, root = Path(spec['helpers']), Path(spec['native']), Path(spec['fixture_root'])
    owner = native / 'atlas_tectonics/integration_spatial_owner.py'
    legacy = Path(spec['legacy_owner'])
    sources = {}
    for path, expected in spec['pins'].items():
        actual = sha256(Path(path).read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f'pin differs: {path} {actual} != {expected}')
        sources[path] = actual
    sys.path[:0] = [str(helpers), str(native), str(helpers.parent)]
    loader = unittest.TestLoader()
    loaded, extra = {}, {}
    try:
        lazy = importlib.import_module('test_s3_lazy_rows')
        loaded['test_s3_lazy_rows'] = str(lazy.__file__)
    except Exception as error:  # recorded; the negative mode still requires all 20 to run
        if mode != 'negative':
            raise
        lazy, extra['import_error'] = None, type(error).__name__ + ': ' + str(error)[:200]
    if mode in ('lazy', 'negative'):
        suite = unittest.TestSuite() if lazy is None else loader.loadTestsFromModule(lazy)
    elif mode == 'own':
        own = importlib.import_module('test_l3_carried_pages')
        if Path(str(own.__file__)).resolve() != (helpers / 'test_l3_carried_pages.py').resolve() \
                or Path(str(own.M.__file__)).resolve() != (helpers / 'record_views.py').resolve():
            raise SystemExit('the L3 suite or its reader was not loaded from the fixture')
        loaded['test_l3_carried_pages'] = str(own.__file__)
        extra['defined_tests'] = test_count(helpers / 'test_l3_carried_pages.py')
        suite = loader.loadTestsFromModule(own)
    elif mode == 'carry':
        carry = importlib.import_module('test_s3_l3_fallback')
        for module, name in ((carry, 'test_s3_l3_fallback.py'),
                             (carry.RV, 'record_views.py'),
                             (carry.V, 'spatial_validation_patch.py')):
            if Path(str(module.__file__)).resolve() != (helpers / name).resolve():
                raise SystemExit('the carry case or its runtime was not loaded from the fixture')
        loaded['test_s3_l3_fallback'] = str(carry.__file__)
        extra['defined_tests'] = test_count(helpers / 'test_s3_l3_fallback.py')
        extra['carry_evidence'] = carry.EVIDENCE
        suite = loader.loadTestsFromModule(carry)
    else:
        compact = importlib.import_module('test_spatial_compact_cells')
        d1b = importlib.import_module('test_d1b_carried_start')
        if Path(compact.O.__file__).resolve() != owner.resolve() \
                or Path(compact.V.__file__).resolve() != (helpers / 'spatial_validation_patch.py').resolve():
            raise SystemExit('the consumers did not load the fixture owner and patch')
        for module in (compact, d1b, lazy):
            if module is None or Path(str(module.__file__)).resolve() != (helpers / (module.__name__ + '.py')).resolve():
                raise SystemExit('a consumer suite was not loaded from the fixture')
        # From here to the suite: review-r1/focused_adapter.py's loader seams, verbatim.
        reference = legacy.read_text(encoding='utf8')
        # Preserve the original transform identity check for the legacy reference.
        indexed = compact.X.transform(compact.S.spatial_owner_source(reference))
        assert sha256(indexed.encode()).hexdigest() == compact.E.INDEXED_OWNER_SHA

        def selected_methods():
            methods = {name: getattr(compact.O.PreparedSpatialOwner, name)
                       for name in ('_issue', '_bound', 'restore')}
            methods['_carried_start_cells'] = compact.O._carried_start_cells
            for method in methods.values():
                assert Path(method.__code__.co_filename).resolve() == owner.resolve()
            return methods

        def native_reference():
            return d1b._compiled(reference, dict(compact.O.__dict__), '<pinned-legacy-native>')

        def before_reference():
            held = compact.V._function(compact.E.holder_source(indexed),
                                       '_carried_start_cells', d1b.BEFORE_D1B)
            return d1b._compiled(held, {**compact.O.__dict__, '_SV': compact.V},
                                 '<pinned-legacy-before-d1b>')

        # Only test loader seams change; assertions, fixtures and test bodies remain intact.
        compact.native_methods = selected_methods
        d1b.native_methods = selected_methods
        d1b.native_function = native_reference
        d1b.before_d1b_function = before_reference
        suite = unittest.TestSuite(loader.loadTestsFromModule(module) for module in (d1b, compact))
        extra['reference_indexed_sha256'] = sha256(indexed.encode()).hexdigest()
    if 'record_views' in sys.modules:
        loaded['record_views'] = str(sys.modules['record_views'].__file__)
    with open(os.devnull, 'w') as sink:
        result = unittest.TextTestRunner(stream=sink, verbosity=2, resultclass=Results).run(suite)
    outcomes = getattr(result, 'outcomes', {})
    failed = sum(v in ('failure', 'error') for v in outcomes.values())
    runs = spec.get('expected_runs', EXPECTED_RUNS[mode])
    if mode == 'negative':
        expected = result.testsRun == runs and len(outcomes) == runs and 0 < failed < runs
    else:
        expected = result.wasSuccessful() and result.testsRun == runs and len(outcomes) == runs
        if mode in ('own', 'carry'):
            expected = expected and extra['defined_tests'] == runs
    foreign = loaded_outside(root)
    expected = expected and not foreign
    record = dict(mode=mode, python=sys.executable, child_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                  sources=sources, loaded=loaded, foreign_modules=foreign, testsRun=result.testsRun,
                  failed_or_error=failed, successful=result.wasSuccessful(), expected_outcome=expected,
                  outcomes=outcomes, **extra)
    with output.open('x', encoding='utf8') as stream:
        json.dump(record, stream, indent=1)
    print(json.dumps({key: record[key] for key in ('mode', 'testsRun', 'failed_or_error', 'expected_outcome')}))
    return 0 if expected else 1


if __name__ == '__main__':
    raise SystemExit(main())
