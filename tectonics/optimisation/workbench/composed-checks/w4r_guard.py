"""W4: the CR real-job guard suite and the two successor drills on the COMPOSED guard bytes.

W1-G ran the CR suite (CR/guard/test_continuation_job_guard.py, 15 tests, with
synthetic_workload.py) and its two real drills on resource_guard_patch.successor_files
written into a scratch folder. Here the three guard-set files are copied from
composed-r1/helpers instead (each hash checked against the composed manifest and the
pins), so the bytes that run are exactly the composed ones. The test bodies are
W1-G's own (test_resource_guard_patch.SuccessorRealJob), inherited unchanged; only
the folder setup differs, plus one byte-equality test and a recording copy of the
CR-suite runner. Scratch lives under the short W4 root; nothing under R is written
except the NEW --output file.

    python -B w4r_guard.py --output <new.json>
"""
import sys
sys.dont_write_bytecode = True

import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

import w4r_common as W

sys.path.append(str(W.R))          # W1-G's test module and its transform (read as test-side references)
import resource_guard_patch as P   # noqa: E402
import test_resource_guard_patch as RGP   # noqa: E402

RGP_SHA256 = 'd769a8d0355bb45b09fe453c5c54e55cf97027d3314e8c7583bdee1f6429063d'
EVIDENCE = {}


def admission_guard_pin():
    """historical_admission.GUARD_PIN as shipped in composed helpers, read without importing it."""
    tree = ast.parse((W.HELPERS/'historical_admission.py').read_text(encoding='utf8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and [ast.unparse(t) for t in node.targets] == ['GUARD_PIN']:
            return ast.literal_eval(node.value)
    raise W.W4Refused('GUARD_PIN not found in composed historical_admission')


class ComposedGuardJob(RGP.SuccessorRealJob):
    @classmethod
    def setUpClass(cls):
        manifest = W.manifest()
        relative = '/'.join(W.HELPERS.relative_to(W.T).parts)
        cls.temp = tempfile.TemporaryDirectory(prefix='rg-', dir=W.SCRATCH)
        cls.folder = Path(cls.temp.name)
        cls.pins = {}
        for name in (P.GUARD_NAME, P.JOB_NAME, P.DIAGNOSTICS_NAME):
            raw = (W.HELPERS/name).read_bytes()
            digest = sha256(raw).hexdigest()
            assert manifest['files'][relative+'/'+name] == digest, name
            (cls.folder/name).write_bytes(raw)
            cls.pins[name] = digest
        assert cls.pins == {P.GUARD_NAME: P.SUCCESSOR_PIN, P.JOB_NAME: P.JOB_PIN,
                            P.DIAGNOSTICS_NAME: P.DIAGNOSTICS_PIN}, cls.pins
        assert P.SUCCESSOR_PIN == admission_guard_pin() == manifest['successor_guard_sha256'] == W.SUCCESSOR_GUARD_SHA256
        for name, pin in RGP.CR_SUITE.items():
            shutil.copy2(RGP.CR_GUARD/name, cls.folder/name)
            assert sha256((cls.folder/name).read_bytes()).hexdigest() == pin
        (cls.folder/'resource_workload.py').write_text(RGP.RESOURCE_WORKLOAD, encoding='utf8')
        EVIDENCE['folder_pins'] = dict(cls.pins, **{n: p for n, p in RGP.CR_SUITE.items()})

    def test_composed_guard_set_is_the_successor_transform_output(self):
        # The composed bytes are exactly W1-G's successor_files of the H guard/job and O diagnostics.
        expected = P.successor_files(*RGP.original_inputs())
        self.assertEqual({k: sha256(v).hexdigest() for k, v in expected.items()}, self.pins)
        for name, raw in expected.items():
            self.assertEqual((W.HELPERS/name).read_bytes(), raw, name)

    def test_cr_real_job_guard_suite_on_successor_bytes(self):
        # W1-G's assertions, with the CR suite's own output kept for the receipt.
        self.assertEqual(self.pins[P.GUARD_NAME], P.SUCCESSOR_PIN)
        begun = time.perf_counter()
        result = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-v', 'test_continuation_job_guard'],
            cwd=self.folder, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW)
        EVIDENCE['cr_suite'] = dict(returncode=result.returncode, seconds=time.perf_counter()-begun,
            summary=[line for line in result.stderr.splitlines() if line.startswith(('Ran ', 'OK', 'FAILED'))],
            tests=[line for line in result.stderr.splitlines() if line.endswith(' ... ok')],
            stderr_tail=result.stderr[-1500:])
        self.assertEqual(result.returncode, 0, result.stderr[-6000:])
        self.assertIn('Ran 15 tests', result.stderr)
        self.assertTrue(result.stderr.rstrip().endswith('OK'), result.stderr[-2000:])

    def run_fixture(self, kind):
        receipt, record = super().run_fixture(kind)
        EVIDENCE['drill_'+kind] = dict(status=receipt['status'], reason=receipt.get('reason'),
            limits=receipt['limits'], cleanup=receipt['cleanup'], workload_status=record['status'],
            resource_summary_error=receipt.get('resource_summary_error'),
            summary_phases=sorted(receipt.get('resource_summary', {}).get('phases', {})))
        return receipt, record


def main(argv):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args(argv)
    output = Path(options.output).resolve()
    W.require(not output.exists(), 'output exists; refusing to overwrite '+str(output))
    W.require(W.file_sha(Path(RGP.__file__)) == RGP_SHA256, 'W1-G guard test bytes differ from the pinned copy')
    begun = time.perf_counter()
    before = W.verify_composed()
    ram = W.ram_gate()
    W.SCRATCH.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ComposedGuardJob))
    seconds = time.perf_counter()-started
    after = W.verify_composed()
    leftovers = sorted(p.name for p in W.SCRATCH.glob('rg-*'))
    passed = (result.wasSuccessful() and not result.skipped and before['tree_digest'] == after['tree_digest']
              and not leftovers)
    record = dict(schema='private.w4-guard-composed.v1', passed=passed, tests=result.testsRun,
        failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
        seconds=seconds, wall_seconds=time.perf_counter()-begun,
        test_names=list(unittest.defaultTestLoader.getTestCaseNames(ComposedGuardJob)),
        failure_text=[t for _, t in result.failures+result.errors][:4],
        evidence=EVIDENCE, guard_test_module=dict(path=RGP.__file__, sha256=RGP_SHA256),
        resource_guard_patch_sha256=W.file_sha(Path(P.__file__)),
        pins=dict(successor=P.SUCCESSOR_PIN, job=P.JOB_PIN, diagnostics=P.DIAGNOSTICS_PIN,
                  admission_guard_pin=admission_guard_pin(), input_guard=P.GUARD_PIN),
        wrapper_sha256=W.file_sha(Path(__file__)), common_sha256=W.file_sha(W.HERE/'w4r_common.py'),
        scratch_leftovers=leftovers, composed_before=before, composed_after=after, ram_gate=ram,
        python=sys.version, executable=sys.executable, tmp=os.environ.get('TMP'))
    digest = W.write_exclusive(output, record)
    print('W4_GUARD '+json.dumps(dict(passed=passed, tests=result.testsRun, failures=len(result.failures),
          errors=len(result.errors), skipped=len(result.skipped), seconds=round(seconds, 3),
          cr_suite=EVIDENCE.get('cr_suite', {}).get('summary'), output=str(output), sha256=digest)), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
