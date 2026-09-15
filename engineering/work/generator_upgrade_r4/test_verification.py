"""Adversarial verifier checks; corrupt fixtures live only in temporary folders."""
import copy
import ast
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
        self.before = {'r4_sources': {self.path: 'a' * 64}, 'protected_sources': {},
                       'category_contracts': {}, 'physical_interfaces': {}, 'executed_dependency_sources': {},
                       'r3_sources': {}, 'climate_owner_bindings': {}, 'climate_source_bindings': {'sources': {}},
                       'hydromet_source_bindings': {},
                       'runtime': {'python': 'fixture'}}
        self.source_digest = 'b' * 64
        scenarios = ('LOW_DDF3_SIGMA2', 'DIAGNOSTIC_DDF4_SIGMA4', 'HIGH_DDF5_SIGMA6')
        reference = {'schema': 'diadem.connected-climate-terrain-water-soil.r4',
                     'source_sha256': self.source_digest, 'production_installed': False, 'canon_changed': False,
                     'snow_family': 'THREE_COEQUAL_SENSITIVITIES_NO_PREFERRED_MEMBER',
                     'state': {'completed_events': 2, 'members': {name: {} for name in scenarios}},
                     'members': {name: {'final_terrain_climate_diagnostic': {'receipt': {
                         'status': 'BOUNDED_MECHANISTIC_REFERENCE', 'old_climate_parent_reused': False}}} for name in scenarios}}
        r = {'status': 'PASS', 'tests': 2, 'failures': 0, 'errors': 0, 'skips': 0,
             'expected_failures': 0, 'unexpected_successes': 0, 'test_ids': self.ids,
             'started': self.ids, 'stopped': self.ids, 'passed': self.ids, 'inventory_sha256': self.digest,
             'source_identity': self.before, 'source_sha256': self.source_digest,
             'executed_source_hashes': {self.path: 'a' * 64}, 'runtime': self.before['runtime'],
             'derived_executions': {},
             'test_duration_seconds': 1.0, 'duration_seconds': 2.0,
             'actual_reference': reference, 'reference_sha256': v.sha(json.dumps(reference, sort_keys=True, separators=(',', ':')).encode()),
             'cli_readback': [{'stage': 'full', 'verified': True}]}
        self.records = [copy.deepcopy(r) | {'optimisation_flag': mode} for mode in (0, 2)]
        for record in self.records:
            report = {'caps_seconds': [120, 60, 30], 'predeclared_ratio_band': [1.4, 3.0],
                      'first_order_criterion_met': {name: name in ('water_export_m3', 'swe_m', 'head_integral_m2')
                          for name in ('sediment_export_kg', 'terrain_change_m', 'water_export_m3', 'swe_m',
                                       'precipitation_m3', 'temperature_c', 'head_integral_m2')}}
            report['differences'] = {key: [0, 0] for key in report['first_order_criterion_met']}
            report['predeclared_floors'] = {key: 1e-9 for key in report['first_order_criterion_met']}
            bridge = {'status': 'ACTUAL_A_MONTHLY_SNOW_DEMAND_FIXED_FORCING_SENSITIVITY',
                      'new_terrain_compatible': False, 'pm_recomputed': False, 'realised_et_computed': False,
                      'members': {name: {'monthly': [{} for _ in range(12)]} for name in scenarios}}
            record.update(coupled_refinement_report=report, retained_bridge_result=bridge,
                          scientific_diagnostics_scope=v.DIAGNOSTICS_SCOPE)
            for key, hash_key in (('coupled_refinement_report', 'coupled_refinement_sha256'),
                                  ('retained_bridge_result', 'retained_bridge_sha256')):
                record[hash_key] = v.sha(json.dumps(record[key], sort_keys=True, separators=(',', ':')).encode())
            mode = record['optimisation_flag']
            record['cli_readback'] = [{'stage': stage, 'run_id': 'fixture-' + str(mode) + '-' + stage,
                'path': str(v.TASK / 'outputs/generator-upgrade-r4' / ('fixture-' + str(mode) + '-' + stage)),
                'receipt_sha256': 'c' * 64, 'result_sha256': record['reference_sha256'],
                'execution_receipt_path': str(v.TASK / 'outputs/generator-upgrade-r4' / ('fixture-' + str(mode) + '-' + stage + '.json')),
                'execution_receipt_sha256': 'e' * 64, 'executed_source_hashes': {self.path: 'a' * 64},
                'derived_executions': {},
                'checkpoint_sha256': 'd' * 64, 'source_sha256': self.source_digest, 'optimisation_flag': mode}
                for stage in ('stop', 'restart', 'full')]

    def validate(self):
        with patch.object(v, 'EXPECTED_TEST_COUNT', 2), patch.object(v, 'INVENTORY_SHA256', self.digest), \
                patch.object(v, 'required_worker_sources', return_value=(self.path,)), \
                patch.object(v, 'required_cli_sources', return_value=(self.path,)), \
                patch.object(v, 'required_derived_names', return_value=()):
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
        with patch.dict(os.environ, {'PYTHONOPTIMIZE': '2', 'R4_TEST_SENTINEL': 'retained'}):
            environment = v.child_environment()
            self.assertNotIn('PYTHONOPTIMIZE', environment)
            self.assertEqual(environment['R4_TEST_SENTINEL'], 'retained')
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
            r['source_identity']['r4_sources'][self.path] = 'c' * 64
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
            identity['r4_sources'] = {str(path): digest}
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

    def test_missing_coequal_snow_member_cannot_pass(self):
        for record in self.records:
            del record['actual_reference']['members']['HIGH_DDF5_SIGMA6']
        with self.assertRaisesRegex(ValueError, 'three-member'):
            self.validate()

    def test_fixed_forcing_cannot_replace_actual_new_producer_reference(self):
        for record in self.records:
            receipt = record['actual_reference']['members']['LOW_DDF3_SIGMA2']['final_terrain_climate_diagnostic']['receipt']
            receipt['old_climate_parent_reused'] = True
        with self.assertRaisesRegex(ValueError, 'impersonate'):
            self.validate()

    def test_reference_source_identity_cannot_differ_from_workers(self):
        for record in self.records:
            record['actual_reference']['source_sha256'] = 'e' * 64
        with self.assertRaises(ValueError):
            self.validate()

    def test_incomplete_zero_time_reference_is_not_accepted(self):
        for record in self.records:
            record['actual_reference']['state']['completed_events'] = 0
        with self.assertRaises(ValueError):
            self.validate()

    def test_invalid_or_mislabelled_duration_evidence_rejected(self):
        original = copy.deepcopy(self.records)
        for key, value in (('test_duration_seconds', None), ('duration_seconds', float('nan')),
                           ('duration_seconds', True), ('duration_seconds', .5)):
            self.records = copy.deepcopy(original)
            self.records[0][key] = value
            with self.assertRaises(ValueError):
                self.validate()

    def test_retained_r3_execution_map_is_not_omitted(self):
        other = v.canonical(v.TASK / 'work/generator_upgrade_r3/fixture.py')
        identity = copy.deepcopy(self.before)
        identity['r3_sources'][other] = 'd' * 64
        self.assertEqual(v.source_map(identity)[other], 'd' * 64)

    def test_conflicting_new_and_retained_source_identity_rejected(self):
        identity = copy.deepcopy(self.before)
        identity['r3_sources'][self.path] = 'd' * 64
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            v.source_map(identity)

    def test_explicit_reviewed_climate_sources_remain_distinct_bindings(self):
        other = v.canonical(v.TASK / 'work/retained_fixture.py')
        identity = copy.deepcopy(self.before)
        identity['climate_source_bindings']['sources'][other] = 'e' * 64
        self.assertEqual(v.source_map(identity)[other], 'e' * 64)

    def test_cli_execution_receipt_hash_required(self):
        del self.records[0]['cli_readback'][0]['execution_receipt_sha256']
        with self.assertRaises(ValueError):
            self.validate()

    def test_cli_actual_execution_must_match_parent_capture(self):
        self.records[0]['cli_readback'][0]['executed_source_hashes'][self.path] = 'f' * 64
        with self.assertRaises(ValueError):
            self.validate()

    def test_cli_component_only_execution_cannot_claim_complete_chain(self):
        self.records[0]['cli_readback'][0]['executed_source_hashes'] = {}
        with self.assertRaises(ValueError):
            self.validate()

    def test_upstream_project_execution_cannot_hide_as_third_party(self):
        capture = v.ExecutionCapture(v.TASK)
        path = v.RETAINED_WORK_ROOT / 'cryosphere/c1_r1/snow_model.py'
        self.assertEqual(capture.project_path(str(path)), str(path.resolve()))
        with self.assertRaisesRegex(ValueError, 'without freshly captured source'):
            capture.observe('exec', (types.SimpleNamespace(co_filename=str(path)),))

    def derived_fixture(self):
        name = '<environment-successor:work/cryosphere/c1_r1/snow_model.py>'
        proof = {'ast_sha256': 'f'*64, 'producer_path': str(v.derived_producer_path(name)),
                 'producer_sha256': 'c'*64, 'deriver_path': str(v.DERIVER_PATH), 'deriver_sha256': 'd'*64,
                 'meaning': 'source-derived bound functions; original full module not executed'}
        identity = copy.deepcopy(self.before)
        identity['climate_source_bindings']['sources'][proof['producer_path']] = proof['producer_sha256']
        identity['protected_sources'][proof['deriver_path']] = proof['deriver_sha256']
        return name, proof, identity

    def test_derived_AST_evidence_binds_both_source_and_transformation_code(self):
        name, proof, identity = self.derived_fixture()
        v.validate_derived({name: proof}, identity, require_names=(name,))

    def test_derived_AST_cannot_claim_original_full_module_execution(self):
        name, proof, identity = self.derived_fixture()
        proof['meaning'] = 'original whole module executed'
        with self.assertRaises(ValueError):
            v.validate_derived({name: proof}, identity)

    def test_derived_binder_pin_cannot_be_changed(self):
        name, proof, identity = self.derived_fixture()
        proof['deriver_sha256'] = 'e' * 64
        with self.assertRaisesRegex(ValueError, 'binder differs'):
            v.validate_derived({name: proof}, identity)

    def test_missing_actual_retained_bound_execution_rejected(self):
        name, _, identity = self.derived_fixture()
        with self.assertRaisesRegex(ValueError, 'execution missing'):
            v.validate_derived({}, identity, require_names=(name,))

    def test_derived_execution_without_fresh_AST_compile_rejected(self):
        name, _, _ = self.derived_fixture()
        capture = v.ExecutionCapture()
        with self.assertRaisesRegex(ValueError, 'without fresh AST'):
            capture.observe('exec', (types.SimpleNamespace(co_filename=name),))

    def test_derived_path_traversal_or_wrong_kind_rejected(self):
        for name in ('<environment-successor:../secret.py>', '<environment-successor:work/../secret.py>',
                     '<environment-successor:work/data.json>', '<environment-successor:other.py>'):
            with self.assertRaises(ValueError):
                v.derived_producer_path(name)

    def test_source_text_cannot_impersonate_known_AST_binding(self):
        name, _, _ = self.derived_fixture()
        capture = v.ExecutionCapture()
        with self.assertRaisesRegex(ValueError, 'AST-binding'):
            capture.observe('compile', (b'VALUE=1', name))

    def test_unattributed_AST_cannot_be_attached_to_later_derived_execution(self):
        name, _, _ = self.derived_fixture()
        capture = v.ExecutionCapture()
        capture.observe('compile', (ast.parse('value=1'), None))
        self.assertEqual(capture.derived_compiled, {})
        with self.assertRaisesRegex(ValueError, 'without fresh AST'):
            capture.observe('exec', (types.SimpleNamespace(co_filename=name),))

    def test_normal_optimised_derived_AST_disagreement_rejected(self):
        name, proof, identity = self.derived_fixture()
        self.before = identity
        for record in self.records:
            record['source_identity'] = copy.deepcopy(identity)
            record['derived_executions'] = {name: copy.deepcopy(proof)}
        self.records[1]['derived_executions'][name]['ast_sha256'] = 'e' * 64
        with self.assertRaisesRegex(ValueError, 'normal/-OO disagreement: derived_executions'):
            self.validate()

    def test_missing_actual_scientific_report_cannot_be_component_only_success(self):
        self.records[0]['coupled_refinement_report'] = None
        with self.assertRaisesRegex(ValueError, 'diagnostic product missing'):
            self.validate()

    def test_scientific_diagnostic_hash_detects_changed_evidence(self):
        self.records[0]['retained_bridge_result']['new_terrain_compatible'] = True
        with self.assertRaisesRegex(ValueError, 'product hash differs'):
            self.validate()

    def test_scientific_diagnostic_cannot_claim_all_fields_first_order(self):
        report = self.records[0]['coupled_refinement_report']
        report['first_order_criterion_met']['terrain_change_m'] = True
        self.records[0]['coupled_refinement_sha256'] = v.sha(json.dumps(report, sort_keys=True, separators=(',', ':')).encode())
        with self.assertRaisesRegex(ValueError, 'order limits'):
            self.validate()

    def test_resigned_retained_bridge_cannot_be_promoted_to_current_terrain(self):
        report = self.records[0]['retained_bridge_result']
        report['new_terrain_compatible'] = True
        self.records[0]['retained_bridge_sha256'] = v.sha(json.dumps(report, sort_keys=True, separators=(',', ':')).encode())
        with self.assertRaisesRegex(ValueError, 'fixed-forcing limits'):
            self.validate()

    def test_normal_optimised_scientific_diagnostic_disagreement_rejected(self):
        report = self.records[1]['coupled_refinement_report']
        report['differences']['water_export_m3'] = [3, 1]
        self.records[1]['coupled_refinement_sha256'] = v.sha(json.dumps(report, sort_keys=True, separators=(',', ':')).encode())
        with self.assertRaisesRegex(ValueError, 'scientific diagnostic disagreement'):
            self.validate()

    def test_fixture_token_scope_cannot_be_hidden(self):
        del self.records[0]['scientific_diagnostics_scope']
        with self.assertRaisesRegex(ValueError, 'fixture-token distinction'):
            self.validate()


if __name__ == '__main__':
    unittest.main()
