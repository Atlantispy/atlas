"""Adversarial verifier checks; corrupt fixtures live only in temporary folders."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from . import verify as v


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.ids = ['independent.a', 'independent.b']
        self.digest = v.inventory_digest(self.ids)
        self.path = v.canonical(v.HERE / 'synthetic_expected.py')
        self.before = {'r3_sources': {self.path: 'a' * 64}, 'protected_sources': {},
                       'category_contracts': {}, 'physical_interfaces': {}, 'executed_dependency_sources': {},
                       'runtime': {'python': 'fixture'}}
        self.source_digest = 'b' * 64
        reference = {'physical_state': ['exact', 2]}
        r = {'status': 'PASS', 'tests': 2, 'failures': 0, 'errors': 0, 'skips': 0,
             'expected_failures': 0, 'unexpected_successes': 0, 'test_ids': self.ids,
             'started': self.ids, 'stopped': self.ids, 'passed': self.ids, 'inventory_sha256': self.digest,
             'source_identity': self.before, 'source_sha256': self.source_digest,
             'executed_source_hashes': {self.path: 'a' * 64}, 'runtime': self.before['runtime'],
             'actual_reference': reference, 'reference_sha256': v.sha(json.dumps(reference, sort_keys=True, separators=(',', ':')).encode()),
             'cli_readback': [{'stage': 'full', 'verified': True}]}
        self.records = [copy.deepcopy(r) | {'optimisation_flag': mode} for mode in (0, 2)]
        for record in self.records:
            mode = record['optimisation_flag']
            record['cli_readback'] = [{'stage': stage, 'run_id': 'fixture-' + str(mode) + '-' + stage,
                'path': str(v.TASK / 'outputs/generator-upgrade-r3' / ('fixture-' + str(mode) + '-' + stage)),
                'receipt_sha256': 'c' * 64, 'result_sha256': record['reference_sha256'],
                'checkpoint_sha256': 'd' * 64, 'source_sha256': self.source_digest, 'optimisation_flag': mode}
                for stage in ('stop', 'restart', 'full')]

    def validate(self):
        with patch.object(v, 'EXPECTED_TEST_COUNT', 2), patch.object(v, 'INVENTORY_SHA256', self.digest), \
                patch.object(v, 'required_worker_sources', return_value=(self.path,)):
            v.validate_workers(self.records, self.before, self.source_digest, check_cli_artifacts=False)

    def test_matching_complete_mode_pair_passes(self):
        self.validate()

    def test_exactly_two_modes_required(self):
        self.records = self.records[:1]
        with self.assertRaises(ValueError):
            self.validate()

    def test_two_optimised_runs_cannot_claim_normal_coverage(self):
        self.records[0]['optimisation_flag'] = 2
        with self.assertRaises(ValueError):
            self.validate()

    def test_boolean_mode_cannot_impersonate_integer_zero(self):
        self.records[0]['optimisation_flag'] = False
        with self.assertRaises(ValueError):
            self.validate()

    def test_inherited_optimisation_removed_without_mutating_parent_environment(self):
        with patch.dict(os.environ, {'PYTHONOPTIMIZE': '2', 'R3_TEST_SENTINEL': 'retained'}):
            environment = v.child_environment()
            self.assertNotIn('PYTHONOPTIMIZE', environment)
            self.assertEqual(environment['R3_TEST_SENTINEL'], 'retained')
            self.assertEqual(os.environ['PYTHONOPTIMIZE'], '2')
            self.assertEqual(environment['PYTHONDONTWRITEBYTECODE'], '1')

    def test_actual_child_modes_ignore_inherited_optimisation(self):
        with patch.dict(os.environ, {'PYTHONOPTIMIZE': '2'}):
            for flags, expected in (([], 0), (['-OO'], 2)):
                result = subprocess.run([sys.executable, '-B', *flags, '-c',
                    'import json,sys;print(json.dumps([sys.flags.optimize,sys.flags.dont_write_bytecode]))'],
                    capture_output=True, text=True, env=v.child_environment(), timeout=30, check=True)
                self.assertEqual(json.loads(result.stdout), [expected, 1])

    def test_matching_worker_drift_cannot_replace_parent_capture(self):
        for r in self.records:
            r['source_identity']['r3_sources'][self.path] = 'c' * 64
        with self.assertRaises(ValueError):
            self.validate()

    def test_worker_source_digest_must_match_parent(self):
        self.records[1]['source_sha256'] = 'c' * 64
        with self.assertRaises(ValueError):
            self.validate()

    def test_executed_bytes_must_match_captured_bytes(self):
        for r in self.records:
            r['executed_source_hashes'][self.path] = 'c' * 64
        with self.assertRaises(ValueError):
            self.validate()

    def test_uncaptured_executable_source_rejects_even_if_workers_agree(self):
        for r in self.records:
            r['executed_source_hashes'][v.canonical(v.HERE / 'unapproved.py')] = 'd' * 64
        with self.assertRaises(ValueError):
            self.validate()

    def test_missing_required_executed_source_cannot_pass(self):
        for r in self.records:
            r['executed_source_hashes'] = {}
        with self.assertRaises(ValueError):
            self.validate()

    def test_failed_test_cannot_hide_behind_success_status(self):
        self.records[0]['failures'] = 1
        with self.assertRaises(ValueError):
            self.validate()

    def test_skips_and_expected_failures_cannot_count_as_complete(self):
        for field in ('skips', 'expected_failures', 'unexpected_successes'):
            original = copy.deepcopy(self.records)
            self.records[0][field] = 1
            with self.assertRaises(ValueError):
                self.validate()
            self.records = original

    def test_count_boolean_cannot_impersonate_zero_failures(self):
        self.records[0]['errors'] = False
        with self.assertRaises(ValueError):
            self.validate()

    def test_success_count_is_not_an_execution_inventory(self):
        self.records[0]['passed'] = self.ids[:1]
        with self.assertRaises(ValueError):
            self.validate()

    def test_reordered_started_or_stopped_inventory_rejects(self):
        for field in ('started', 'stopped'):
            original = copy.deepcopy(self.records)
            self.records[0][field] = list(reversed(self.ids))
            with self.assertRaises(ValueError):
                self.validate()
            self.records = original

    def test_duplicate_or_substituted_test_identity_rejects(self):
        for ids in ([self.ids[0], self.ids[0]], [self.ids[0], 'substitute']):
            self.records[0]['test_ids'] = ids
            self.records[0]['inventory_sha256'] = v.inventory_digest(ids)
            with self.assertRaises(ValueError):
                self.validate()

    def test_pending_inventory_cannot_authorise_final_seal(self):
        with patch.object(v, 'EXPECTED_TEST_COUNT', None), patch.object(v, 'INVENTORY_SHA256', None):
            with self.assertRaisesRegex(ValueError, 'PENDING'):
                v.require_inventory(self.ids)
            with self.assertRaisesRegex(ValueError, 'PENDING'):
                v.final_verification('no-output-created')

    def test_reference_mode_disagreement_rejects(self):
        self.records[1]['actual_reference'] = {'different': 'physical state'}
        with self.assertRaises(ValueError):
            self.validate()

    def test_forged_reference_digest_rejects(self):
        for r in self.records:
            r['reference_sha256'] = 'f' * 64
        with self.assertRaises(ValueError):
            self.validate()

    def test_cli_evidence_is_required(self):
        self.records[0]['cli_readback'] = []
        with self.assertRaises(ValueError):
            self.validate()

    def test_missing_stop_or_restart_cannot_claim_public_cli_coverage(self):
        self.records[0]['cli_readback'] = self.records[0]['cli_readback'][1:]
        with self.assertRaises(ValueError):
            self.validate()

    def test_cli_mode_must_match_the_actual_worker_mode(self):
        self.records[0]['cli_readback'][0]['optimisation_flag'] = 2
        with self.assertRaises(ValueError):
            self.validate()

    def test_cli_restart_must_match_direct_reference_digest(self):
        self.records[0]['cli_readback'][1]['result_sha256'] = 'e' * 64
        with self.assertRaises(ValueError):
            self.validate()

    def test_cli_restart_checkpoint_must_match_full_checkpoint(self):
        self.records[0]['cli_readback'][1]['checkpoint_sha256'] = 'e' * 64
        with self.assertRaises(ValueError):
            self.validate()

    def test_cli_outputs_cannot_reuse_one_artifact_for_three_claims(self):
        for row in self.records[0]['cli_readback']:
            row['path'] = self.records[0]['cli_readback'][0]['path']
            row['run_id'] = self.records[0]['cli_readback'][0]['run_id']
        with self.assertRaises(ValueError):
            self.validate()

    def test_missing_actual_reference_is_not_component_only_success(self):
        for r in self.records:
            r['actual_reference'] = None
        with self.assertRaises(ValueError):
            self.validate()

    def test_live_executed_source_readback_rejects_changed_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.py'
            path.write_bytes(b'VALUE=1\n')
            digest = v.sha(path.read_bytes())
            identity = copy.deepcopy(self.before)
            identity['r3_sources'] = {str(path): digest}
            path.write_bytes(b'VALUE=2\n')
            with self.assertRaisesRegex(ValueError, 'changed after execution'):
                v.validate_executed({str(path): digest}, identity, check_current=True)

    def test_actual_timestamp_valid_stale_bytecode_cannot_replace_source(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(v.READS, {}, clear=True):
            path = Path(folder) / 'fixture.py'
            path.write_bytes(b'VALUE=99\n')
            old_stat = path.stat()
            py_compile.compile(str(path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
            path.write_bytes(b'VALUE=11\n')
            os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
            ordinary = importlib.util.spec_from_file_location('ordinary_stale_fixture', path)
            loaded = importlib.util.module_from_spec(ordinary)
            ordinary.loader.exec_module(loaded)
            self.assertEqual(loaded.VALUE, 99, 'fixture must prove timestamp-valid stale bytecode was usable')
            fresh = types.ModuleType('fresh_fixture')
            v.SourceLoader(path).exec_module(fresh)
            self.assertEqual(fresh.VALUE, 11)
            self.assertEqual(v.READS[str(path.resolve())], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_loader_rejects_changed_bytes_at_same_path(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(v.READS, {}, clear=True):
            path = Path(folder) / 'fixture.py'
            path.write_bytes(b'VALUE=1\n')
            v.SourceLoader(path).exec_module(types.ModuleType('first'))
            path.write_bytes(b'VALUE=2\n')
            with self.assertRaisesRegex(ValueError, 'changed between executions'):
                v.SourceLoader(path).exec_module(types.ModuleType('second'))

    def test_audit_captures_privately_compiled_and_executed_source(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'work' / 'private.py'
            path.parent.mkdir()
            path.write_bytes(b'VALUE=3\n')
            capture = v.ExecutionCapture(folder)
            raw = path.read_bytes()
            capture.observe('compile', (raw, str(path)))
            capture.observe('exec', (compile(raw, str(path), 'exec'),))
            self.assertEqual(capture.executed, {str(path.resolve()): v.sha(raw)})

    def test_audit_rejects_execution_without_fresh_compile_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'work' / 'private.py'
            capture = v.ExecutionCapture(folder)
            with self.assertRaisesRegex(ValueError, 'without freshly captured source'):
                capture.observe('exec', (compile(b'VALUE=3\n', str(path), 'exec'),))

    def test_audit_rejects_two_different_sources_at_one_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'work' / 'private.py'
            capture = v.ExecutionCapture(folder)
            capture.observe('compile', (b'VALUE=1\n', str(path)))
            with self.assertRaisesRegex(ValueError, 'different project bytes'):
                capture.observe('compile', (b'VALUE=2\n', str(path)))

    def test_audit_does_not_claim_third_party_runtime_as_project_execution(self):
        capture = v.ExecutionCapture(v.TASK)
        self.assertIsNone(capture.project_path(str(v.TASK / 'work/terrain_reconstruction_r1/runtime/numpy/__init__.py')))
        self.assertIsNone(capture.project_path('<string>'))

    def test_extra_test_file_cannot_be_omitted_from_discovery(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(v, 'HERE', Path(folder)):
            (Path(folder) / 'test_unregistered.py').write_bytes(b'# extra fixture\n')
            with self.assertRaisesRegex(ValueError, 'suite file inventory'):
                v.discover()

    def test_verifier_rejects_unsafe_run_id_before_any_write(self):
        for run_id in ('../escape', '/absolute', '', 'x' * 49, None):
            with self.assertRaises(ValueError):
                v.final_verification(run_id)


if __name__ == '__main__':
    unittest.main()
