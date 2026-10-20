"""Affected caller controls: actual LF capture/map code, synthetic files, no scientific child.

The dump orchestration control invokes _dump against explicit storage/runtime
stubs. It validates the observer's extraction mechanism, never independent
scientific proof, admission, source readiness or a real selected composition.
"""
import ast
import copy
from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SELECTED = HERE/'selected-r1'
LM_PATH = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/'
              'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/'
              'resumability-r1/composed-r2/helpers/launch_monitored_interval.py')


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else canonical(value))
    return digest(path)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def lf_module():
    """Same inert import boundary as reviewed LF controls, preserving actual function bodies."""
    path = SELECTED/'launch_fresh_interval.py'
    tree = ast.parse(path.read_bytes(), filename=str(path))
    excluded = {'launch_monitored_interval', 'reopen_fresh_restart', 'run_fresh_interval',
                'run_prepared_restart', 'start_gate'}
    tree.body = [n for n in tree.body if not (isinstance(n, ast.Import) and
                                           any(a.name in excluded for a in n.names))]
    module = ModuleType('caller_lf')
    module.__file__ = str(path)
    module.__dict__.update({n: SimpleNamespace() for n in ('LM', 'RF', 'RUN', 'SG')})
    module.F = SimpleNamespace(MODES=('root', 'interval'))
    exec(compile(tree, str(path), 'exec'), module.__dict__)
    # Use the actual exclusive writer AST. No runtime import or subprocess.
    lm = ast.parse(LM_PATH.read_bytes(), filename=str(LM_PATH))
    node, = [n for n in lm.body if isinstance(n, ast.FunctionDef) and n.name == '_write_exclusive']
    namespace = {'json': json, 'os': os, 'sha256': sha256}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(LM_PATH), 'exec'), namespace)
    module.LM = SimpleNamespace(__file__=str(LM_PATH), _SELF_SHA=digest(LM_PATH), file_hash=digest,
                               _write_exclusive=namespace['_write_exclusive'])
    return module


class Callers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.M = load('caller_map', SELECTED/'write_captures_map_r3.py')
        cls.C = cls.M.C
        cls.LF = lf_module()
        cls.D = load('caller_dump', SELECTED/'dump_arm_r5.py')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fixture-', dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def captured(self):
        attempt = self.root/'attempt'
        attempt.mkdir()
        profile = self.root/'profile.json'
        pin = write(profile, {'synthetic': True})
        guard, entry = self.root/'guard.py', self.root/'workload.py'
        write(guard, b'# synthetic source; never launched\n')
        write(entry, b'# synthetic source; never launched\n')
        for stage, interval in self.C.STAGES:
            stage_path = attempt/('stage-'+stage+'.json')
            stage_record = {'schema': self.C.STAGE_SCHEMA, 'stage': stage, 'interval': interval,
                            'profile': {'path': str(profile), 'sha256': pin}, 'steps': []}
            write(stage_path, stage_record)
            for step in ('runner', 'reader'):
                p = self.C.step_paths(attempt, stage, step)
                p['out'].mkdir()
                argv = [sys.executable, '-B', str(guard), '--launch', '--output', str(p['receipt']), '--',
                        sys.executable, '-B', str(entry)]
                launch = self.LF.step_launch(argv, {'PYTHONHASHSEED': '0'}, p,
                         binding={'arm': 'before', 'stage': stage, 'interval': interval,
                                  'step': step, 'attempt': str(attempt)},
                         profile=SimpleNamespace(path=profile, sha256=pin), stage_record=stage_path)
                launch_pin = self.LF.LM._write_exclusive(p['launch'], launch)
                write(p['receipt'], {'synthetic': True, 'status': 'STOPPED'})
                write(p['guard'], {'status': 'STOPPED', 'reason': None, 'nonce': 'synthetic-only',
                                  'workload_exit_confirmed': True, 'workload_exit_code': 0})
                write(p['tracking'], {'synthetic': True})
                write(p['control'], {'synthetic': True})
                write(p['log'], b'Synthetic file capture; no workload was run.\n')
                capture_pin = self.LF._capture(p, launch, launch_pin, outcome='NOT_RUNNING', code=0,
                                               observed='2026-10-20T00:00:00+00:00')
                stage_record['steps'].append({'name': step, 'launch_sha256': launch_pin,
                                             'capture': {'ok': True, 'sha256': capture_pin}})
                write(stage_path, stage_record)
        return attempt, pin

    def map_main(self, attempt, pin, output):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return self.M.main(['--arm', 'before', '--profile-sha256', pin, '--attempt', str(attempt),
                                '--output', str(output)])

    def test_actual_parent_capture_map_and_selected_comparator_consumer(self):
        attempt, pin = self.captured()
        output = self.root/'map.json'
        self.assertEqual(self.map_main(attempt, pin, output), 0)
        entries, why = self.C.load_captures({'name': 'before', 'attempt': attempt, 'sha256': pin},
                                           [str(output), digest(output)])
        self.assertIsNone(why)
        self.assertEqual(set(entries), {('root', 'runner'), ('root', 'reader'),
                                        ('interval', 'runner'), ('interval', 'reader')})
        for stage, step in entries:
            p = self.C.step_paths(attempt, stage, step)
            capture = json.loads(p['capture'].read_bytes())
            self.assertEqual(capture['writer']['pid'], os.getpid())
            self.assertEqual(capture['writer']['launcher']['sha256'], digest(SELECTED/'launch_fresh_interval.py'))
            self.assertEqual(capture['files']['receipt']['sha256'], digest(p['receipt']))
        self.assertEqual(self.map_main(attempt, pin, output), 1, 'exclusive map must not overwrite')

    def test_capture_map_rejects_changed_stage_digest_and_foreign_profile(self):
        attempt, pin = self.captured()
        self.assertEqual(self.map_main(attempt, '0'*64, self.root/'foreign.json'), 1)
        path = attempt/'stage-root.json'
        stage = json.loads(path.read_bytes())
        stage['steps'][0]['capture']['sha256'] = '0'*64
        write(path, stage)
        output = self.root/'broken.json'
        self.assertEqual(self.map_main(attempt, pin, output), 1)
        self.assertFalse(output.exists())

    def test_map_import_refuses_wrong_selected_comparator_before_execution(self):
        map_path = self.root/'write_captures_map_r3.py'
        map_path.write_bytes((SELECTED/'write_captures_map_r3.py').read_bytes())
        (self.root/'compare_arms_r21.py').write_text("raise AssertionError('must never execute')\n", encoding='utf8')
        with self.assertRaisesRegex(RuntimeError, 'selected comparator bytes differ'):
            load('caller_bad_map', map_path)

    def test_launcher_source_unchanged_and_dumper_guard_is_not_an_execution_positive(self):
        self.assertEqual(digest(SELECTED/'launch_fresh_interval.py'),
                         digest(HERE.parent/'lf-r2/launch_fresh_interval.py'))
        self.assertFalse(self.D.EXTRACTION_READY)
        with self.assertRaises(self.D.DumpRefused):
            self.D.dump(SimpleNamespace(), {})

    def root_dump_case(self):
        attempt, store_dir, output = self.root/'attempt', self.root/'store', self.root/'dump'
        attempt.mkdir()
        store_dir.mkdir()
        output.mkdir()
        native = self.root/'native'
        native.mkdir()
        row = {'workspace': str(self.root), 'native_root': 'native', 'import_roots': [],
               'store_directory': str(store_dir), 'output_directory': str(attempt)}
        profile = self.root/'profile.json'
        pin = write(profile, row)
        records = {'state': canonical({'synthetic': 'state'}), 'mesh': canonical({'synthetic': 'mesh'})}
        targets = {n: {'sha256': sha256(v).hexdigest(), 'nbytes': len(v)} for n, v in records.items()}
        root_metadata = {'key': 'root-key', 'kind': 'root', 'sequence': 0,
                         'exterior_state': {'record_blobs': {
                             n: {'array': 'spatial-record:'+n, 'sha256': t['sha256'], 'bytes': t['nbytes']}
                             for n, t in targets.items()}}}
        runner_path = store_dir/'runner-record-interval-0000.json'
        runner_pin = write(runner_path, {'workflow_id': 'workflow', 'root': {'root_key': 'root-key',
                                'root_metadata_sha256': sha256(canonical(root_metadata)).hexdigest()}})
        producer = {'mode': 'root', 'status': 'SEALED_ROOT_AWAITING_READER', 'errors': [],
                    'profile_sha256': pin, 'runner_record': {'path': str(runner_path), 'sha256': runner_pin}}
        producer_pin = write(attempt/'run-root/run.json', producer)
        reader_pin = write(attempt/'reader-root/reopen.json', {
            'mode': 'root', 'errors': [], 'review_only': False, 'profile_sha256': pin,
            'producer_receipt_sha256': producer_pin, 'root_record_identities': targets})
        entry = {'file_sha256': 'e'*64}
        verdict_pin = write(store_dir/'reader-verdict-interval-0000.json', {
            'status': 'PASS_ROOT_INDEPENDENT_REOPEN', 'interval': 0, 'entry': entry,
            'reopen_receipt_sha256': reader_pin, 'producer_receipt_sha256': producer_pin,
            'runner_record_sha256': runner_pin})
        catalog_pin = write(store_dir/'interval-catalog.json', {'synthetic': True})
        adopted_pin = write(store_dir/'adopted-interval-0000.json', {
            'status': 'ADOPTED_AFTER_INDEPENDENT_READER', 'interval': 0, 'entry': entry,
            'catalog_sha256': catalog_pin, 'catalog_digest': 'c'*64,
            'verdict_sha256': verdict_pin, 'runner_record_sha256': runner_pin})
        write(attempt/'stage-root.json', {'status': 'ADOPTED', 'steps': [
            {'name': 'runner', 'ok': True, 'receipt_sha256': producer_pin},
            {'name': 'reader', 'ok': True, 'receipt_sha256': reader_pin},
            {'name': 'finalise', 'ok': True, 'verdict_sha256': verdict_pin},
            {'name': 'adopt', 'ok': True, 'adopted_sha256': adopted_pin}]})
        source_proof = {'source_manifest_sha256': 'a'*64, 'native_source_digest': 'b'*64}
        scope = SimpleNamespace(closed=False)
        scope.close = lambda: setattr(scope, 'closed', True)

        class Sources:
            def __init__(self, profile):
                self.native_root, self.import_roots = native, []
            def check_paths(self):
                pass
            def verify(self):
                return copy.deepcopy(source_proof)

        class Store:
            readonly = True
            store_set = SimpleNamespace(head=SimpleNamespace(interval=0, file_sha256='e'*64),
                                        catalog_digest='c'*64)
            limits = SimpleNamespace(chunk_bytes=16)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def metadata(self, key):
                if key != 'root-key':
                    raise AssertionError(key)
                return root_metadata
            def change_token(self):
                return ('c'*64, (0, 1, 2, 3, 4, 5, 0), None)
            def _manifest(self, key):
                return {'arrays': {'synthetic': {'dtype': '|u1', 'shape': [3], 'chunks': []}}}
            def iter_chunks(self, key, name, budget):
                raw = records[name[len('spatial-record:'):]] if name.startswith('spatial-record:') else b'abc'
                yield 0, raw

        fake = {
            'run_fresh_interval': SimpleNamespace(
                FreshProfile=SimpleNamespace(read=lambda path, sha: SimpleNamespace(record=lambda: row)),
                FreshSources=Sources, CATALOG='interval-catalog.json',
                record_name=lambda kind, i: '%s-interval-%04d.json' % (kind, i),
                READER_PASS={'root': 'PASS_ROOT_INDEPENDENT_REOPEN'},
                SEALED_STATUS={'root': 'SEALED_ROOT_AWAITING_READER'}, _store_configuration=lambda store: None),
            'run_prepared_restart': SimpleNamespace(LOGICAL_BYTES=1, new_retained_scope=lambda budget: scope,
                                                    interpreter_gate=lambda: {'synthetic': True}),
            'compact_restart_store': SimpleNamespace(CompactRestartStore=SimpleNamespace(
                open_catalog=lambda path, scope: Store())),
            'spatial_indexed_patch': SimpleNamespace(), 'spatial_records_patch': SimpleNamespace(),
            'workflow_transfer': SimpleNamespace(workflow_key=lambda kind, key: 'root-key'),
            'atlas_tectonics.resources': SimpleNamespace(WorkBudget=lambda *args, **kw: object()),
            'compact_contracts': SimpleNamespace(SegmentRef=object),
            'compact_store': SimpleNamespace(CompactMeshStoreV3=object)}
        args = SimpleNamespace(profile=str(profile), profile_sha256=pin, interval=0, out=str(output))
        fence = SimpleNamespace(audit=lambda: {'synthetic': True})
        return args, fake, fence, scope, root_metadata, targets, output

    def test_actual_root_only_dump_body_retains_bound_metadata_and_streams_records(self):
        args, fake, fence, scope, root_metadata, targets, output = self.root_dump_case()
        record = {}
        with mock.patch.dict(sys.modules, fake):
            self.D._dump(args, record, fence)
        self.assertTrue(scope.closed)
        self.assertEqual(record['head']['root_metadata'], root_metadata)
        self.assertEqual(record['records'], targets)
        self.assertEqual((output/'arrays/0000.bin').read_bytes(), b'abc')
        self.assertEqual(record['store_token_before'], record['store_token_after'])
        self.assertEqual(record['source_proof'], record['source_proof_before'])
        self.assertFalse(self.D.EXTRACTION_READY)

    def test_actual_root_only_dump_body_refuses_changed_published_metadata(self):
        args, fake, fence, scope, root_metadata, _, _ = self.root_dump_case()
        root_metadata['unproved_change'] = True
        with mock.patch.dict(sys.modules, fake), self.assertRaisesRegex(self.D.DumpRefused,
                                                       'independently reader-checked published root'):
            self.D._dump(args, {}, fence)
        self.assertTrue(scope.closed)
        self.assertFalse(self.D.EXTRACTION_READY)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('new output stem required')
    stem = Path(sys.argv[1])
    if any(stem.with_suffix(suffix).exists() for suffix in ('.json', '.log')):
        raise SystemExit('preserve existing evidence')
    pins = json.loads((HERE/'SOURCE-PINS.json').read_bytes())['files']
    changed = lambda: [p for p, h in pins.items() if digest(p) != h]
    if changed():
        raise SystemExit('source pins changed before caller controls')
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(Callers))
    drift = changed()
    payload = {'schema': 'plan04-affected-callers-controls.v1',
               'status': 'PASS' if result.wasSuccessful() and not drift else 'FAIL',
               'tests': result.testsRun, 'changed_pins': drift,
               'failures': [(str(t), text) for t, text in result.failures],
               'errors': [(str(t), text) for t, text in result.errors],
               'source_pins': pins, 'scientific_run': False, 'real_arm': False,
               'selected_live_composition': False, 'readiness': False}
    stem.with_suffix('.log').write_text(log.getvalue(), encoding='utf8')
    payload['log_sha256'] = digest(stem.with_suffix('.log'))
    stem.with_suffix('.json').write_text(json.dumps(payload, indent=2)+'\n', encoding='utf8')
    print(log.getvalue())
    print(json.dumps({k: payload[k] for k in ('status', 'tests', 'changed_pins')}))
    return 0 if payload['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
