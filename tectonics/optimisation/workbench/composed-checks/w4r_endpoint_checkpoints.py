"""W4: the W2-K endpoint-checkpoint suite on the COMPOSED native inventory.

The 24-test W2-K module (R/endpoint-checkpoints/test_endpoint_checkpoints_w2k.py,
pinned bytes) is executed unchanged except for three asserted, exactly-once
substitutions: its candidate is a byte-identical copy of composed-r1/runtime-src
(the suite temporarily rewrites a package source, so it never runs on the frozen
tree itself), its import roots are the composed ones (helpers, ram,
H/source/tectonics/tests; no I helpers, no H root), and its temporary stores live
under the short W4 scratch root. Its one candidate-specific test (I runtime-src
plus seam) is replaced by an integrity test against the composed manifest; the
other 23 run as written. Nothing writes test-results-w2k.json; the result goes to
a NEW file named by --output.

    python -B w4r_endpoint_checkpoints.py --output <new.json>     (parent)
    python -B w4r_endpoint_checkpoints.py <mode> <directory>      (the suite's own fresh-process child)
"""
import sys
sys.dont_write_bytecode = True

from hashlib import sha256
import json
from pathlib import Path
import shutil
import time
import types

import w4r_common as W


SOURCE = W.E/'test_endpoint_checkpoints_w2k.py'
SOURCE_SHA256 = '3aac645528c5ef974e53d225abc2620c33edfbdb4ad7b533c1dc326328c33450'
W2K_RESULTS = W.E/'test-results-w2k.json'
W2K_RESULTS_SHA256 = '5cf0f943bf8e06b6e41c9c543c30ec5c5420f3a15ce44a5e1fcbabe2416e382d'
WORK = W.SCRATCH/'ep'
CANDIDATE = WORK/'c'          # copy of composed-r1/runtime-src
TMPROOT = WORK/'q'
REPLACED = 'test_w2k_candidate_is_frozen_runtime_plus_seam_with_current_companion'
SUBSTITUTIONS = (
    ("CANDIDATE = HERE / 'candidate-w2k'   # prepare_candidate_w2k.py; never candidate-src\n",
     "CANDIDATE = W4_CANDIDATE\n"),
    ("sys.path[:0] = [str(CANDIDATE), str(O/'runtime-integration-r1/helpers'),\n"
     "               str(O/'runtime-integration-r1/ram'), str(H)]\n",
     "sys.path[:0] = [str(CANDIDATE)]+[str(root) for root in W4_IMPORT_ROOTS]\n"),
    (r"        temporary_root = '\\\\?\\'+str(HERE) if os.name == 'nt' else str(HERE)" "\n",
     r"        temporary_root = '\\\\?\\'+str(W4_TMPROOT) if os.name == 'nt' else str(W4_TMPROOT)" "\n"),
)


def load():
    raw = SOURCE.read_bytes()
    W.require(sha256(raw).hexdigest() == SOURCE_SHA256, 'W2-K suite bytes differ from the pinned copy')
    text = raw.decode('utf8')
    for old, new in SUBSTITUTIONS:
        W.require(text.count(old) == 1, 'substitution anchor not found exactly once: '+old[:60])
        text = text.replace(old, new)
    module = types.ModuleType('w4r_endpoint_checkpoints_w2k')
    module.__file__ = str(Path(__file__).resolve())   # the suite's own child re-enters this wrapper
    module.__dict__.update(W4_CANDIDATE=CANDIDATE, W4_IMPORT_ROOTS=W.IMPORT_ROOTS, W4_TMPROOT=TMPROOT)
    sys.modules[module.__name__] = module
    exec(compile(text, str(SOURCE), 'exec'), module.__dict__)
    return module


def composed_suite(module):
    G = module.G

    def test_w4_candidate_is_the_composed_native_inventory(self):
        manifest = W.manifest()
        package = Path(G.__file__).resolve().parent
        self.assertEqual(package, (CANDIDATE/'atlas_tectonics').resolve())
        actual = W.native_hashes(package)
        self.assertEqual(actual, manifest['source_hashes'])
        self.assertEqual(W.native_hashes(W.NATIVE/'atlas_tectonics'), manifest['source_hashes'])
        self.assertEqual(len(actual), 236)
        companion = W.file_sha(W.E/'integration_endpoint_checkpoints.py')
        self.assertEqual(actual['atlas_tectonics/integration_endpoint_checkpoints.py'], companion)
        self.assertEqual(companion, W.COMPANION_SHA256)
        self.assertNotEqual(companion, module.PREDECESSOR_COMPANION)
        stages = manifest['stage_digests']
        for name, step in (('integration_component_volume_batch.py', 'patch_endpoint_seam.candidate_sources'),
                           ('integration_differential_geometry.py', 'geometry_transfer.transform(compact=True)')):
            self.assertEqual(actual['atlas_tectonics/'+name], stages['atlas_tectonics/'+name+'@'+step], name)
        w2k = W.native_hashes(W.E/'candidate-w2k'/'atlas_tectonics')
        module.EVIDENCE['candidate'] = dict(files=len(actual), companion_sha256=companion,
            inventory_sha256=sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest(),
            native_source_digest=sha256(W.canonical(actual)).hexdigest(),
            source_bytes=sum(p.stat().st_size for p in package.rglob('*.py')),
            w2k_candidate_files=len(w2k),
            w2k_candidate_bytes=sum(p.stat().st_size for p in (W.E/'candidate-w2k'/'atlas_tectonics').rglob('*.py')),
            differs_from_w2k_candidate=sorted(k for k in actual if w2k.get(k) != actual[k]),
            absent_from_w2k_candidate=sorted(set(actual)-set(w2k)))

    attributes = {REPLACED: None,     # its I-runtime-plus-seam premise does not describe the composed tree
                  'test_w4_candidate_is_the_composed_native_inventory': test_w4_candidate_is_the_composed_native_inventory}
    return type('ComposedEndpointChecks', (module.EndpointChecks,), attributes)


def prepare():
    W.require(not WORK.exists(), 'stale W4 endpoint scratch exists: '+str(WORK))
    WORK.mkdir(parents=True)
    shutil.copytree(W.NATIVE, CANDIDATE, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    TMPROOT.mkdir()
    W.require(W.native_hashes(CANDIDATE/'atlas_tectonics') == W.manifest()['source_hashes'],
              'composed native copy differs from the manifest')
    W.require(sorted(p.name for p in CANDIDATE.iterdir()) == ['atlas_tectonics'], 'unexpected copy membership')


def compare_with_w2k(evidence):
    raw = W2K_RESULTS.read_bytes()
    W.require(sha256(raw).hexdigest() == W2K_RESULTS_SHA256, 'W2-K evidence file differs from the pinned bytes')
    base = json.loads(raw)['observations']
    same = {}
    tiny, prior = evidence.get('tiny_result', {}), base['tiny_result']
    for key in ('bytes', 'sha256', 'replay_geometry_calls', 'store_bytes', 'peak_logical_bytes'):
        same['tiny_result.'+key] = [tiny.get(key), prior[key], tiny.get(key) == prior[key]]
    same['process_stop'] = [evidence.get('process_stop'), base['process_stop'],
                            evidence.get('process_stop') == base['process_stop']]
    for key in sorted(k for k in base if k.startswith('w2k_')):
        same[key] = [evidence.get(key), base[key], evidence.get(key) == base[key]]
    return dict(w2k_results=str(W2K_RESULTS), w2k_results_sha256=sha256(raw).hexdigest(), fields=same,
                all_identical=all(row[2] for row in same.values()),
                profiled_hit_seconds=dict(composed=tiny.get('profiled_hit_seconds'), w2k=prior['profiled_hit_seconds']))


def main(argv):
    import argparse
    import unittest
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args(argv)
    output = Path(options.output).resolve()
    W.require(not output.exists(), 'output exists; refusing to overwrite '+str(output))
    begun = time.perf_counter()
    before = W.verify_composed()
    w2k_before = W.file_sha(W2K_RESULTS)
    ram = W.ram_gate()
    prepare()
    try:
        module = load()
        suite_class = composed_suite(module)
        started = time.perf_counter()
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(suite_class))
        seconds = time.perf_counter()-started
        audit = W.import_audit(sys.modules, native_copy=CANDIDATE)
        restored = W.native_hashes(CANDIDATE/'atlas_tectonics') == W.manifest()['source_hashes']
        names = unittest.defaultTestLoader.getTestCaseNames(suite_class)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    after = W.verify_composed()
    comparison = compare_with_w2k(module.EVIDENCE)
    # Byte identity with the W2-K observations is reported beside the verdict, not folded into it.
    passed = (result.wasSuccessful() and restored and not audit['violations']
              and before['tree_digest'] == after['tree_digest'] and W.file_sha(W2K_RESULTS) == w2k_before)
    record = dict(schema='private.w4-endpoint-checkpoints-composed.v1', passed=passed,
        tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        skipped=len(result.skipped), seconds=seconds, wall_seconds=time.perf_counter()-begun,
        test_names=list(names), replaced_test=REPLACED,
        failure_text=[t for _, t in result.failures+result.errors][:4],
        suite=dict(path=str(SOURCE), sha256=SOURCE_SHA256, substitutions=[old for old, _ in SUBSTITUTIONS]),
        wrapper_sha256=W.file_sha(Path(__file__)), common_sha256=W.file_sha(W.HERE/'w4r_common.py'),
        candidate_copy=str(CANDIDATE), copy_restored_after_mutation_tests=restored,
        observations=module.EVIDENCE, comparison_with_w2k=comparison, import_audit=audit,
        composed_before=before, composed_after=after, w2k_results_untouched=W.file_sha(W2K_RESULTS) == w2k_before,
        ram_gate=ram, python=sys.version, executable=sys.executable)
    digest = W.write_exclusive(output, record)
    print('W4_ENDPOINT_CHECKPOINTS '+json.dumps(dict(passed=passed, tests=result.testsRun,
          failures=len(result.failures), errors=len(result.errors), seconds=round(seconds, 3),
          identical_to_w2k=comparison['all_identical'], violations=len(audit['violations']),
          output=str(output), sha256=digest)), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    if len(sys.argv) == 3 and not sys.argv[1].startswith('--'):
        load().child(sys.argv[1], sys.argv[2])
    else:
        raise SystemExit(main(sys.argv[1:]))
