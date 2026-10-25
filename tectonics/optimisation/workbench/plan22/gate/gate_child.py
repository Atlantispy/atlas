"""Child of gate_s3l3.py: run one gate test file against a composed helpers folder, as suite_check.py runs a module.

    PYTHONHASHSEED=0 python -B -P gate_child.py HELPERS TMPDIR TEST_FILE EXPECTED_RUNS

The environment is suite_check.py's (W/work/plan20/integration-r1/postapply-r1/suite_check.py 03ea7acd): sys.path
starts with HELPERS, the composition's src and the inherited heat-repair test root; temporary folders that would land
in the composition go to TMPDIR; the composition is snapshotted before and after (`residue`). The only difference:
the test file lives outside HELPERS (the gate's own case), so the composed tree stays exactly the composed rows.
Refuses unless PYTHONHASHSEED=0 and -B (no -I/-E/-O). Also records where the storage modules were loaded from and
fails if any module came from outside the composition, the heat-repair test root, the interpreter or TEST_FILE.
Prints one JSON line; exit 0 only if every test ran and passed, the run count is EXPECTED_RUNS and nothing is foreign.
"""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

STORAGE = ('record_views', 'record_tables', 'content_cache', 'segment_store', 'interval_store_set', 'compact_store',
           'mesh_tables', 'compact_contracts')


def snapshot(root):
    return {path.relative_to(root).as_posix(): (path.is_dir(), None if path.is_dir() else path.stat().st_size,
                                                path.stat().st_mtime_ns) for path in root.rglob('*')}


def main():
    helpers, tmp, test_file = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    expected_runs = int(sys.argv[4])
    composition = helpers.parent
    if os.environ.get('PYTHONHASHSEED') != '0' or sys.flags.hash_randomization or not sys.dont_write_bytecode \
            or sys.flags.isolated or sys.flags.ignore_environment or sys.flags.optimize:
        raise SystemExit('refusing: run with PYTHONHASHSEED=0 and -B, without -I, -E or -O')
    if not tmp.is_dir() or any(tmp.iterdir()) or tmp == composition or composition in tmp.parents:
        raise SystemExit('TMPDIR must be an existing empty folder outside the composition')
    workspace = helpers.parents[2]
    heat = workspace / 'fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests'
    sys.path[:0] = [str(helpers), str(composition / 'src'), str(heat)]
    for key, folder in (('TMP', 'tmp'), ('TEMP', 'tmp'), ('R2T_TEMP', 'r2t'), ('R3T_TEMP', 'r3t')):
        (tmp / folder).mkdir(exist_ok=True)
        os.environ[key] = str(tmp / folder)
    tempfile.tempdir = str(tmp / 'tmp')
    os.chdir(tmp)

    redirected = []

    def outside(folder):
        if folder is None:
            return folder
        path = Path(folder).resolve()
        if path == composition or composition in path.parents:
            redirected.append(path.relative_to(composition).as_posix())
            return str(tmp / 'tmp')
        return folder

    class TemporaryDirectory(tempfile.TemporaryDirectory):
        def __init__(self, suffix=None, prefix=None, dir=None, **options):
            super().__init__(suffix, prefix, outside(dir), **options)

    real_mkdtemp = tempfile.mkdtemp
    tempfile.TemporaryDirectory = TemporaryDirectory
    tempfile.mkdtemp = lambda suffix=None, prefix=None, dir=None: real_mkdtemp(suffix, prefix, outside(dir))

    name = test_file.stem
    before = snapshot(composition)
    spec = importlib.util.spec_from_file_location(name, test_file)
    assert spec is not None and spec.loader is not None, test_file
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    with open(os.devnull, 'w') as sink:
        result = unittest.TextTestRunner(stream=sink).run(suite)
    after = snapshot(composition)
    residue = dict(added=sorted(set(after) - set(before)), removed=sorted(set(before) - set(after)),
                   changed=sorted(k for k in set(before) & set(after) if before[k] != after[k]))
    bad = {test.id().split('.', 1)[-1]: trace.strip().splitlines()[-1][:200]
           for test, trace in result.failures + result.errors}
    roots = [composition, heat.resolve(), Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    foreign, loaded = [], {}
    for key, value in list(sys.modules.items()):
        path = getattr(value, '__file__', None)
        if not path or key == '__main__':
            continue
        path = Path(path).resolve()
        if key in STORAGE:
            loaded[key] = path.as_posix()
        if path not in (test_file, Path(__file__).resolve()) and not any(root in path.parents for root in roots):
            foreign.append(path.as_posix())
    ok = (result.wasSuccessful() and result.testsRun == expected_runs and not foreign and not any(residue.values()))
    print(json.dumps(dict(test=name, test_sha256=sha256(test_file.read_bytes()).hexdigest(),
                          child_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), helpers=helpers.as_posix(),
                          run=result.testsRun, expected_runs=expected_runs, failures=len(result.failures),
                          errors=len(result.errors), skipped=len(result.skipped), bad=bad, redirected=len(redirected),
                          residue=residue, clean=not any(residue.values()), loaded=loaded,
                          foreign_modules=sorted(foreign), passed=ok), sort_keys=True))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
