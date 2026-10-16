"""W4: the compact spatial fixture and the partition fresh-process fixture on COMPOSED bytes.

W2 ran C/test_spatial_workflow_patch.py and C/test_partition_workflow_fresh_process.py
on trees the tests composed themselves from I runtime-src (a subset of the chains),
R/C helper copies, and I/helpers, I/ram and the H root for everything else. Here the
same child bodies (SW.child_main, PWF.child_main and SW's alias-funding test, all
unchanged) run in fresh processes whose import roots are exactly the composed ones:

    composed-r1/runtime-src, composed-r1/helpers, composed-r1/ram, H/source/tectonics/tests

plus a folder of byte-identical copies of the eight TEST-ONLY modules they need
(none is a runtime helper). The copies' own path-relative roots (I runtime-src,
I helpers, the H root) resolve to non-existent folders, which is asserted, so
nothing outside the composed roots can be imported; every child also audits its
loaded modules and fails on any file outside the composed roots, the interpreter
environment, the test copies and this harness. The frozen tree is only read; stores
live under the short W4 scratch root. Results go to a NEW --output file.

    python -B w4r_fixtures.py --output <new.json>
    python -B w4r_fixtures.py --child {alias|spatial|partition} {publish|reopen|alias} <directory>
"""
import sys
sys.dont_write_bytecode = True

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import unittest

import w4r_common as W


TEST_ONLY = {   # name -> (source folder, sha256): test fixtures/builders, never runtime helpers
    'test_workflow_fresh_process.py': (W.R, '430b4976d29f247127f07785dce3a29e4b76bd528c1a881f7f3cd54876351c12'),
    'test_spatial_transfer.py': (W.R, '78e4e1f8a5ed0519ba84d30a8b47b9d29c45526680c2fb6078fabbf820d41b9f'),
    'test_native_transfer.py': (W.R, 'fe7e6f6aee02c31f74d2fdc4e320aac462d9766b4156386f98378d9455cc80bc'),
    'test_geometry_transfer_integration.py': (W.R, '7cb2407e984d0607325da9308da0c3a162237e283aee9b71744bb0d11d3edb3c'),
    'test_mesh_tables.py': (W.C, '21aa8c78a553ff9942922bd363981cfa0223fc75a0d2d98594ef2ebd49671e08'),
    'test_partition_tables.py': (W.C, '44ade6bb63d785868d9c8a3ce43a15b9bab26f9e7bfbe3b2914560f8c376ca31'),
    'test_spatial_workflow_patch.py': (W.C, '47c72bf899e6ab05a4dbc1e65e6b045e515ef8255e5dd33c9a741eead38e8bf1'),
    'test_partition_workflow_fresh_process.py': (W.C, '23df298cf1258732d2cd2e3f4cf6206c9dc28c844d59807fcbb0724f72bd6bf8'),
}
# W2-B fixture identities (w2b receipt; wave-2 retest reproduced them).
W2_PARTITION_ID = 'bb2a2500515ae95d378042f4adad3ef47741fb34e31f9d67c17671a664a93496'
W2_DESCRIPTOR_STATS = {'sha256': '59547365b50985f0b2ef30f8ffeefad5fdfb6a761cf40b197f41b766e162a011', 'nbytes': 34384}
PHASES = {'publish': ['convert-historical-partition', 'publish-compact-partition'], 'reopen': []}
MARKS = ('COMPACT_WORKFLOW_RESULT ', 'COMPACT_PARTITION_RESULT ', 'W4_ALIAS_RESULT ', 'W4_IMPORT_AUDIT ')
EVIDENCE = {}


# ---------------------------------------------------------------- child

def child(kind, operation, directory):
    directory = Path(directory).resolve()
    copies = directory/'t'
    here = W.HERE.resolve()
    sys.path[:] = [p for p in sys.path if Path(p or '.').resolve() != here]
    sys.path[:0] = [str(W.NATIVE)]+[str(root) for root in W.IMPORT_ROOTS]+[str(copies)]
    # The copies' own relative roots (I runtime-src/helpers/ram, the H root) must not exist.
    absent = [directory/'src', directory/'helpers', directory/'runtime-integration-r1',
              copies.parents[1]/'runtime-integration-r1', copies.parents[2]/'heat-repair-20261007']
    W.require(not any(path.exists() for path in absent), 'a test-copy relative root exists')
    if kind == 'alias':
        import test_spatial_workflow_patch as SW
        # HERE is read only at import and for this test's temporary-store parent (parents[4]).
        SW.HERE = directory/'h1'/'h2'/'h3'/'h4'/'h5'
        test = SW.CompactWorkflowTests('test_changed_alias_held_traceback_and_escaped_read_are_funded')
        result = unittest.TextTestRunner(verbosity=2, stream=sys.stderr).run(test)
        print('W4_ALIAS_RESULT '+json.dumps(dict(pid=os.getpid(), tests=result.testsRun,
              failures=len(result.failures), errors=len(result.errors), ok=result.wasSuccessful())), flush=True)
    elif kind == 'spatial':
        import test_spatial_workflow_patch as SW
        SW.child_main(operation, directory)
    elif kind == 'partition':
        import test_partition_workflow_fresh_process as PWF
        PWF.child_main(operation, directory)
    else:
        raise W.W4Refused('unknown fixture kind '+kind)
    audit = W.import_audit(sys.modules, test_copies=(copies,))
    print('W4_IMPORT_AUDIT '+json.dumps(audit, sort_keys=True), flush=True)
    return 3 if audit['violations'] else 0


# ---------------------------------------------------------------- parent

def stage(name):
    directory = W.SCRATCH/name
    W.require(not directory.exists(), 'stale W4 fixture scratch exists: '+str(directory))
    (directory/'t').mkdir(parents=True)
    for module, (folder, pin) in TEST_ONLY.items():
        shutil.copy2(folder/module, directory/'t'/module)
        W.require(W.file_sha(directory/'t'/module) == W.file_sha(folder/module) == pin, 'test-only module differs: '+module)
    return directory


def launch(kind, operation, directory, timeout):
    gate = W.ram_gate()
    scratch = str(W.SCRATCH)
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--child', kind, operation, str(directory)]
    begun = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                               env=dict(os.environ, TMP=scratch, TEMP=scratch), stdin=subprocess.DEVNULL)
    seconds = time.perf_counter()-begun
    rows = {}
    for line in completed.stdout.splitlines():
        for mark in MARKS:
            if line.startswith(mark):
                rows.setdefault(mark.strip(), []).append(json.loads(line[len(mark):]))
    return dict(command=command[1:], returncode=completed.returncode, seconds=seconds, rows=rows, ram_gate=gate,
                stdout_tail=completed.stdout[-3000:], stderr_tail=completed.stderr[-12000:])


def digest(value):
    return sha256(W.canonical(value)).hexdigest()


class ComposedFixtures(unittest.TestCase):
    def check_child(self, run, mark, *, natives=236):
        # natives: modules expected from composed-r1/runtime-src; an ExecutionContext imports all 236,
        # the in-process alias test creates none and imports only what it uses.
        self.assertEqual(run['returncode'], 0, run['stdout_tail']+run['stderr_tail'])
        self.assertEqual(len(run['rows'].get(mark, [])), 1, run['stdout_tail'])
        audit = run['rows']['W4_IMPORT_AUDIT'][0]
        self.assertEqual(audit['violations'], [])
        self.assertGreaterEqual(audit['counts'].get('composed-native', 0), natives)
        self.assertGreater(audit['counts'].get('composed-helper', 0), 0)
        return run['rows'][mark][0], audit

    def test_1_spatial_alias_held_traceback_and_escaped_read_funded(self):
        directory = stage('sa')
        run = launch('alias', 'alias', directory, 180)
        row, audit = self.check_child(run, 'W4_ALIAS_RESULT', natives=1)
        self.assertEqual((row['tests'], row['failures'], row['errors'], row['ok']), (1, 0, 0, True))
        EVIDENCE['spatial_alias'] = dict(seconds=run['seconds'], row=row, import_counts=audit['counts'],
            h_tests=audit['h_tests'], helpers_loaded=audit['helpers_loaded'], ram_gate=run['ram_gate'],
            command=run['command'])
        self.assertEqual(sorted(p.name for p in directory.iterdir()), ['t'])
        shutil.rmtree(directory)

    def test_2_spatial_publish_then_independent_reopen_on_composed_bytes(self):
        directory = stage('sw')
        reports, runs = [], []
        for operation in ('publish', 'reopen'):
            run = launch('spatial', operation, directory, 180)
            row, audit = self.check_child(run, 'COMPACT_WORKFLOW_RESULT')
            reports.append(row)
            runs.append(dict(operation=operation, seconds=run['seconds'], pid=row['pid'], import_counts=audit['counts'],
                             h_tests=audit['h_tests'], test_copies=audit['test_copies'],
                             helpers_loaded=audit['helpers_loaded'], ram_gate=run['ram_gate'], command=run['command']))
        self.assertNotEqual(reports[0]['pid'], reports[1]['pid'])
        self.assertEqual([r['reserved_after_close'] for r in reports], [0, 0])
        self.assertEqual(reports[0]['result'], reports[1]['result'])
        result = reports[0]['result']
        EVIDENCE['spatial_two_process'] = dict(processes=2, runs=runs, sequence=result['root']['sequence'],
            result_sha256=digest(result), root_key=result['root']['key'], workflow_id=result['root']['workflow_id'],
            execution=result['execution'], execution_identity_equals_w3=result['execution']['execution_identity'] == W.EXECUTION_IDENTITY,
            compact_mesh_reference=result['root']['exterior_state'].get('compact_mesh', {}).get('snapshot_key'),
            has_compact_partition=('compact_partition' in result['root']), reserved_after_close=[0, 0])
        self.assertEqual(result['root']['sequence'], 3)
        shutil.rmtree(directory)

    def test_3_partition_publish_then_cold_readonly_reopen_on_composed_bytes(self):
        directory = stage('pw')
        reports, runs = [], []
        for operation in ('publish', 'reopen'):
            run = launch('partition', operation, directory, 300)
            row, audit = self.check_child(run, 'COMPACT_PARTITION_RESULT')
            reports.append(row)
            runs.append(dict(operation=operation, seconds=run['seconds'], pid=row['pid'], phases=row['phases'],
                             import_counts=audit['counts'], h_tests=audit['h_tests'],
                             helpers_loaded=audit['helpers_loaded'], ram_gate=run['ram_gate'], command=run['command']))
        self.assertNotEqual(reports[0]['pid'], reports[1]['pid'])
        self.assertEqual([r['phases'] for r in reports], [PHASES['publish'], PHASES['reopen']])
        self.assertEqual([r['reserved_after_close'] for r in reports], [0, 0])
        self.assertEqual(reports[0]['result'], reports[1]['result'])
        first = reports[0]['result']
        self.assertEqual(first['root']['compact_partition']['partition_id'], first['partition_id'])
        EVIDENCE['partition_two_process'] = dict(processes=2, runs=runs, partition_id=first['partition_id'],
            descriptor_stats=first['descriptor_stats'], result_sha256=digest(first),
            root_key=first['root']['key'], workflow_id=first['root']['workflow_id'], execution=first['execution'],
            execution_identity_equals_w3=first['execution']['execution_identity'] == W.EXECUTION_IDENTITY,
            support_ids=len(first['support_ids']), root_aliases=len(first['root_aliases']),
            partition_id_equals_w2=first['partition_id'] == W2_PARTITION_ID,
            descriptor_stats_equal_w2=first['descriptor_stats'] == W2_DESCRIPTOR_STATS, reserved_after_close=[0, 0])
        # Same synthetic parent through the composed converter: W2-B's exact identities.
        self.assertEqual(first['partition_id'], W2_PARTITION_ID)
        self.assertEqual(first['descriptor_stats'], W2_DESCRIPTOR_STATS)
        shutil.rmtree(directory)


def main(argv):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args(argv)
    output = Path(options.output).resolve()
    W.require(not output.exists(), 'output exists; refusing to overwrite '+str(output))
    begun = time.perf_counter()
    before = W.verify_composed()
    sources = {name: W.file_sha(folder/name) for name, (folder, _) in TEST_ONLY.items()}
    W.require(sources == {name: pin for name, (_, pin) in TEST_ONLY.items()}, 'test-only module bytes changed')
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ComposedFixtures))
    seconds = time.perf_counter()-started
    after = W.verify_composed()
    leftovers = sorted(p.name for p in W.SCRATCH.iterdir() if p.name in ('sa', 'sw', 'pw'))
    passed = result.wasSuccessful() and before['tree_digest'] == after['tree_digest'] and not leftovers
    record = dict(schema='private.w4-fixtures-composed.v1', passed=passed, tests=result.testsRun,
        failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        seconds=seconds, wall_seconds=time.perf_counter()-begun,
        test_names=list(unittest.defaultTestLoader.getTestCaseNames(ComposedFixtures)),
        failure_text=[t[-6000:] for _, t in result.failures+result.errors][:4], evidence=EVIDENCE,
        test_only_modules=sources, import_roots=[str(W.NATIVE)]+[str(r) for r in W.IMPORT_ROOTS],
        w2_reference=dict(partition_id=W2_PARTITION_ID, descriptor_stats=W2_DESCRIPTOR_STATS),
        wrapper_sha256=W.file_sha(Path(__file__)), common_sha256=W.file_sha(W.HERE/'w4r_common.py'),
        scratch_leftovers=leftovers, composed_before=before, composed_after=after,
        python=sys.version, executable=sys.executable)
    digest_ = W.write_exclusive(output, record)
    print('W4_FIXTURES '+json.dumps(dict(passed=passed, tests=result.testsRun, failures=len(result.failures),
          errors=len(result.errors), seconds=round(seconds, 3), output=str(output), sha256=digest_)), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--child':
        raise SystemExit(child(sys.argv[2], sys.argv[3], sys.argv[4]))
    raise SystemExit(main(sys.argv[1:]))
