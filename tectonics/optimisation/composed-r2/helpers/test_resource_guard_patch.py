"""Successor guard: exact policy equality, pinned bytes and bounded real job drills.

The real drills launch only tiny fixtures under the successor guard in a short
scratch copy; no scientific import, checkpoint access or simulation occurs.
"""
import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import resource_guard_patch as P

HERE = Path(__file__).resolve().parent
H = HERE.parents[2]/'heat-repair-20261007'
CR_GUARD = HERE.parents[1]/'guard'
DIAGNOSTICS = HERE.parent/'monitored-continuation-r1'/P.DIAGNOSTICS_NAME
CR_SUITE = {'test_continuation_job_guard.py': '3954669a475669c6705988b79a441328e6be0421b72b509914bb62a6f024fc05',
            'synthetic_workload.py': 'b48a6302194693e8ee183848b78bd6bb9ce5ac462c8221b6a8a96afefa680ab5'}
LIMITS = dict(rss_bytes=12 << 30, free_floor_bytes=1 << 30)

# Exactly the diagnostic nodes; anything else differing from the original fails.
REMOVED = (
    'import private_heat_resource_diagnostics_r1 as RESOURCE_DIAGNOSTICS',
    "if 'resource_summary' in receipt:\n    self.record['resource_summary'] = receipt['resource_summary']",
    "if 'resource_summary_error' in receipt:\n"
    "    self.record['resource_summary_error'] = receipt['resource_summary_error']",
    'resource_summary = RESOURCE_DIAGNOSTICS.ResourceSummary()',
    "sample = RESOURCE_DIAGNOSTICS.sample_job(job, None if parent is None else parent.pid, "
    "receipt.get('launch_cohort'))",
    "if resource_summary is not None:\n    try:\n"
    "        resource_summary.observe(sample, str(receipt['phase']), tick - started)\n"
    '        resource_snapshot = resource_summary.snapshot()\n'
    '        json.dumps(resource_snapshot, allow_nan=False)\n'
    "        receipt['resource_summary'] = resource_snapshot\n"
    '    except Exception as diagnostic_error:\n'
    '        resource_summary = None\n'
    "        receipt['resource_summary_error'] = repr(diagnostic_error)[:1024]")


def original_inputs():
    return ((H/P.GUARD_NAME).read_bytes(), (H/P.JOB_NAME).read_bytes(), DIAGNOSTICS.read_bytes())


def compose_successor(directory):
    """Write the successor guard set (bytes from successor_files) into one folder."""
    files = P.successor_files(*original_inputs())
    for name, raw in files.items():
        (Path(directory)/name).write_bytes(raw)
    return {name: sha256(raw).hexdigest() for name, raw in files.items()}


class WithoutDiagnostics(ast.NodeTransformer):
    def __init__(self):
        self.removed = []

    def visit_Import(self, node):
        if [(n.name, n.asname) for n in node.names] == [('private_heat_resource_diagnostics_r1', 'RESOURCE_DIAGNOSTICS')]:
            self.removed.append(ast.unparse(node))
            return None
        return node

    def visit_Assign(self, node):
        if [ast.unparse(t) for t in node.targets] == ['resource_summary']:
            self.removed.append(ast.unparse(node))
            return None
        if isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == 'RESOURCE_DIAGNOSTICS.sample_job':
            self.removed.append(ast.unparse(node))
            node.value = ast.parse('job.sample(None if parent is None else parent.pid)', mode='eval').body
        return self.generic_visit(node)

    def visit_If(self, node):
        if ast.unparse(node.test) in ('resource_summary is not None', "'resource_summary' in receipt",
                                      "'resource_summary_error' in receipt"):
            self.removed.append(ast.unparse(node))
            return None
        return self.generic_visit(node)


class ResourceGuardPatch(unittest.TestCase):
    def test_policy_ownership_and_cleanup_unchanged(self):
        before, _, _ = original_inputs()
        after = P.transform(before)
        a, b = ast.parse(before), ast.parse(after)
        stripper = WithoutDiagnostics()
        # The whole module, including exception/cleanup ordering and thresholds.
        self.assertEqual(ast.dump(a), ast.dump(stripper.visit(b)))
        self.assertEqual(tuple(stripper.removed), REMOVED)

    def test_limits_and_cleanup_definitions_identical_without_stripping(self):
        before, _, _ = original_inputs()
        a, b = ast.parse(before), ast.parse(P.transform(before))
        def definitions(tree):
            rows = {}
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.Assign, ast.ClassDef)) and not (
                        isinstance(node, ast.FunctionDef) and node.name == 'supervise'):
                    if isinstance(node, ast.ClassDef):
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef) and item.name != '_sync':
                                rows[node.name+'.'+item.name] = ast.dump(item)
                    else:
                        rows[ast.unparse(node.targets[0]) if isinstance(node, ast.Assign) else node.name] = ast.dump(node)
            return rows
        original, successor = definitions(a), definitions(b)
        self.assertEqual(original, successor)
        for name in ('RSS_LIMIT', 'FREE_FLOOR', '_limits', '_write', '_terminal_main',
                     'ContinuationGuard.check', 'ContinuationGuard.close', 'ContinuationGuard.__init__'):
            self.assertIn(name, successor)
        supervise = lambda tree: next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'supervise')
        self.assertEqual(ast.dump(supervise(a).args), ast.dump(supervise(b).args))
        # Every handler and the finally block of supervise() are byte-for-byte unchanged.
        trys = lambda tree: next(n for n in supervise(tree).body if isinstance(n, ast.Try))
        self.assertEqual([ast.dump(h) for h in trys(a).handlers], [ast.dump(h) for h in trys(b).handlers])
        self.assertEqual([ast.dump(s) for s in trys(a).finalbody], [ast.dump(s) for s in trys(b).finalbody])

    def test_successor_pin_and_refusals(self):
        before, job, diagnostics = original_inputs()
        after = P.transform(before)
        self.assertEqual(sha256(after).hexdigest(), P.SUCCESSOR_PIN)
        self.assertEqual(sha256(before).hexdigest(), P.GUARD_PIN)
        for changed in (before+b'\n', before.replace(b'\n', b'\r\n'), before.decode()):
            with self.assertRaisesRegex(ValueError, 'exact original'):
                P.transform(changed)
        with patch.object(P, 'SUCCESSOR_PIN', '0'*64), self.assertRaisesRegex(ValueError, 'reviewed successor'):
            P.transform(before)
        files = P.successor_files(before, job, diagnostics)
        self.assertEqual({k: sha256(v).hexdigest() for k, v in files.items()},
                         {P.GUARD_NAME: P.SUCCESSOR_PIN, P.JOB_NAME: P.JOB_PIN, P.DIAGNOSTICS_NAME: P.DIAGNOSTICS_PIN})
        for args in ((before, job+b'\n', diagnostics), (before, job, diagnostics+b'#'),
                     (before, job.decode(), diagnostics)):
            with self.assertRaisesRegex(ValueError, 'dependency'):
                P.successor_files(*args)
        with self.assertRaisesRegex(ValueError, 'exact original'):
            P.successor_files(after, job, diagnostics)


RESOURCE_WORKLOAD = '''"""Tiny successor-guard resource fixture. No scientific imports or checkpoint access."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import private_heat_continuation_guard_r3 as G


def main():
    kind, output = sys.argv[1], Path(sys.argv[2])
    record = dict(status='STARTED', pid=os.getpid(), phases=[], errors=[])
    with output.open('x', encoding='utf-8') as stream:
        json.dump(record, stream)
    save = lambda: G._write(output, record)
    guard = G.ContinuationGuard(output, record, save)
    guard.phase('a')
    child = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(2)'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)
    child.wait(timeout=20)
    if kind == 'invalid-phase':
        # The diagnostics refuse names over 256 characters; the guardian must not.
        guard.phase('p'*300)
        time.sleep(1.)
    guard.phase('b')
    time.sleep(.6)
    guard.close()
    record['status'] = 'PASS_SYNTHETIC_RESOURCES'
    save()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
'''


@unittest.skipUnless(os.name == 'nt', 'Windows job-object integration')
class SuccessorRealJob(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='rg-')
        cls.folder = Path(cls.temp.name)
        cls.pins = compose_successor(cls.folder)
        for name, pin in CR_SUITE.items():
            shutil.copy2(CR_GUARD/name, cls.folder/name)
            assert sha256((cls.folder/name).read_bytes()).hexdigest() == pin
        (cls.folder/'resource_workload.py').write_text(RESOURCE_WORKLOAD, encoding='utf8')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_fixture(self, kind):
        folder = tempfile.TemporaryDirectory(dir=self.folder)
        self.addCleanup(folder.cleanup)
        output = Path(folder.name)/'run.json'
        command = [sys.executable, '-B', str(self.folder/P.GUARD_NAME), '--launch', '--output', str(output),
                   '--', sys.executable, '-B', str(self.folder/'resource_workload.py'), kind, str(output)]
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        receipt = json.loads(output.with_suffix('.guard.json').read_bytes())
        record = json.loads(output.read_bytes())
        self.assertEqual(result.returncode, 0, result.stderr + repr(receipt))
        self.assertEqual((receipt['status'], receipt.get('reason')), ('STOPPED', None))
        self.assertEqual((receipt['workload_exit_confirmed'], receipt['workload_exit_code']), (True, 0))
        self.assertEqual(receipt['cleanup'], dict(remaining=[], action_errors=[]))
        self.assertEqual(receipt['limits'], LIMITS)
        self.assertEqual((receipt['sample_interval'], receipt['grace_seconds']), (.25, 5.))
        self.assertEqual(record['status'], 'PASS_SYNTHETIC_RESOURCES')
        self.assertEqual(sha256((self.folder/P.GUARD_NAME).read_bytes()).hexdigest(), P.SUCCESSOR_PIN)
        return receipt, record

    def test_cr_real_job_guard_suite_on_successor_bytes(self):
        self.assertEqual(self.pins[P.GUARD_NAME], P.SUCCESSOR_PIN)
        result = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-v', 'test_continuation_job_guard'],
            cwd=self.folder, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr[-6000:])
        self.assertIn('Ran 15 tests', result.stderr)
        self.assertTrue(result.stderr.rstrip().endswith('OK'), result.stderr[-2000:])

    def test_successor_guard_resource_summary_real(self):
        receipt, record = self.run_fixture('clean')
        self.assertNotIn('resource_summary_error', receipt)
        summary = receipt['resource_summary']
        self.assertEqual(summary['schema'], 'atlas.private.resource-summary.r1')
        self.assertTrue({'a', 'b'} <= set(summary['phases']))
        self.assertTrue(all(summary['phases'][name]['samples'] > 0 for name in ('a', 'b')))
        self.assertGreaterEqual(summary['phases']['a']['peaks']['worker_process_count'], 1)
        self.assertGreaterEqual(summary['peaks']['worker_process_count'], 1)
        self.assertGreaterEqual(summary['overlapping_identity_cpu_seconds'], 0)
        self.assertIsInstance(summary['phases']['a']['least_available_ram_bytes'], int)
        self.assertGreaterEqual(summary['peaks']['parent_os_peak_working_set_bytes'], summary['peaks']['parent_rss_bytes'])
        self.assertIn('process_tree_private_bytes', receipt['latest_sample'])
        # The driver's own receipt carries the guardian's detached summary copy.
        self.assertEqual(record['resource_summary']['schema'], 'atlas.private.resource-summary.r1')
        self.assertNotIn('resource_summary_error', record)

    def test_diagnostic_failure_does_not_abort(self):
        receipt, record = self.run_fixture('invalid-phase')
        self.assertIn('Short, nonempty phase name required', receipt['resource_summary_error'])
        self.assertLessEqual(len(receipt['resource_summary_error']), 1024)
        self.assertEqual(record['resource_summary_error'], receipt['resource_summary_error'])
        # Sampling and the unchanged RSS/free-floor triggers continued after the
        # diagnostic refusal (same tick, then the next phase); the summary did not.
        self.assertIn('p'*300, receipt['sampled_peak_by_phase'])
        self.assertIn('b', receipt['sampled_peak_by_phase'])
        self.assertIn('a', receipt['resource_summary']['phases'])
        self.assertNotIn('b', receipt['resource_summary']['phases'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
