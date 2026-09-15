"""Adversarial engineering-intake tests; no scientific model is executed."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('terrain_intake_under_test', HERE / 'contract.py')
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
template_spec = importlib.util.spec_from_file_location('terrain_template_under_test', HERE / 'template.py')
template = importlib.util.module_from_spec(template_spec)
_old_contract = sys.modules.get('contract')
sys.modules['contract'] = contract
try:
    template_spec.loader.exec_module(template)
finally:
    if _old_contract is None: sys.modules.pop('contract', None)
    else: sys.modules['contract'] = _old_contract
intake_spec = importlib.util.spec_from_file_location('terrain_intake_cli_under_test', HERE / 'intake.py')
intake = importlib.util.module_from_spec(intake_spec)
_old = {key: sys.modules.get(key) for key in ('contract', 'template')}
sys.modules.update(contract=contract, template=template)
try:
    intake_spec.loader.exec_module(intake)
finally:
    for key, value in _old.items():
        if value is None: sys.modules.pop(key, None)
        else: sys.modules[key] = value


def bound_metadata_fixture():
    """Synthetic metadata ONLY; no invented real-world/Diadem acceptance band."""
    sources = [{'id': 'S' + str(i), 'path': f'synthetic-fixture-{i}.json',
                'sha256': hashlib.sha256(f'fixture-{i}'.encode()).hexdigest(), 'bytes': 9,
                'source_status': 'WORKING NON-CANON', 'owner': 'Engineering',
                'role': 'synthetic_engineering_test_fixture'} for i in range(3)]
    recipe = template.make_recipe(sources)
    recipe['snapshot_id'] = 'SYNTHETIC-METADATA-NOT-A-DIADEM-RUN'
    recipe['mode_status'] = 'SYNTHETIC_TEST_DECLARATION_ONLY'
    recipe['frame'].update(id='F0', crs='Diadem local test frame', origin='0,0',
                           x_direction='east', y_direction='south', horizontal_datum='test datum',
                           vertical_datum='test datum', validity='all fixture cells',
                           boundaries='closed test fixture', spacing_m=100., effective_support_m=100., source_ids=['S0'])
    for row in recipe['input_groups']:
        row.update(state='BOUND', source_ids=['S0'], reason='Synthetic metadata fixture only', binding='fixture binding')
    recipe['coverage'].update(state='BOUND', source_ids=['S0'], domain_inventory_source_ids=['S0'],
                              coverage_proof='Synthetic fixture coverage declaration, not geographic proof',
                              additional_family_inventory='COMPLETE_NONE', reason='Synthetic fixture only')
    for row in recipe['families']:
        row.update(state='BOUND', source_ids=['S0'], support='PLANNED_IMPLEMENTATION',
                   algorithm='synthetic test algorithm declaration, not an implemented model',
                   domain_binding='synthetic test domain', parameter_binding='synthetic parameters only',
                   reason='Synthetic schema fixture; no scientific implementation claim')
    recipe['constraint_inventory'].update(state='BOUND', source_ids=['S0'], reason='One synthetic reference control')
    recipe['constraints'] = [{'id': 'C0', 'geometry_binding': 'synthetic geometry', 'reason': 'reference only',
                              'source_status': 'WORKING NON-CANON', 'conflict_policy': 'report conflict',
                              'owner': 'Physical', 'source_ids': ['S0'], 'role': 'reference',
                              'interval': [0., 2.], 'units': 'm', 'derived_predecessor': True}]
    for i, row in enumerate(recipe['tests']):
        split = 'calibration' if i == 0 else 'holdout' if i == 1 else 'analytical'
        source = 'S1' if i == 0 else 'S2' if i == 1 else 'S0'
        row.update(state='BOUND', source_ids=[source], reason='Synthetic engineering fixture only',
                   regime='synthetic', parameters='synthetic fixed parameters', expected='fixture identity',
                   method='synthetic independent calculation', acceptance_layer='numerical')
        row['fixture'].update(source_ids=[source], split=split, shape=[4, 4], spacing_m=100., seed=0)
        row['tolerance'].update(metric='synthetic residual', units='m', atol=0., rtol=0.,
                                scale_definition='one synthetic grid', physical_band=[0., 1.],
                                justification='Exact synthetic mathematical fixture, not a physical acceptance band')
    recipe['coupling'].update(state='BOUND', source_ids=['S0'], reason='Synthetic interface declaration',
                              method='one_way_test', stopping_rule='single test evaluation', limits='synthetic fixture only',
                              influence_proof='synthetic bounded graph', c1_compatibility='original C1 remains untouched',
                              meltwater_producer='test producer, transferred once', mass_basis='reconstruction_geometric_change')
    recipe['downstream'].update(state='BOUND', source_ids=['S0'], reason='Synthetic dependency declaration',
                                influence_rule='bounded old/new synthetic graph reachability',
                                compatibility_rule='compare fresh synthetic dependent products; no adoption')
    return recipe


class IntakeEnvelopeTests(unittest.TestCase):
    def test_json_metadata_read_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'metadata.json'
            path.write_text('{"value": 123}', encoding='utf-8')
            self.assertEqual(contract.load_json(path, max_bytes=64), {'value': 123})
            with self.assertRaises(ValueError):
                contract.load_json(path, max_bytes=3)

    def assert_envelope(self, result):
        self.assertIsInstance(result, dict)
        self.assertEqual(result['gate_b'], 'INCOMPLETE')
        self.assertIs(result['production_ready'], False)
        self.assertIs(result['model_implemented'], False)
        self.assertIn(result['binding_validation'], ('PASS', 'INCOMPLETE', 'FAIL'))
        self.assertIsInstance(result['issues'], list)
        for issue in result['issues']:
            for key in ('path', 'code', 'owner', 'message'):
                self.assertIsInstance(issue[key], str)
                self.assertTrue(issue[key])

    def test_empty_recipe_is_incomplete_not_a_model(self):
        result = contract.validate_recipe({})
        self.assert_envelope(result)
        self.assertNotEqual(result['binding_validation'], 'PASS')
        self.assertTrue(result['issues'])

    def test_arbitrary_bypass_fields_cannot_authorise_any_gate(self):
        for bypass in ({'gate_b': 'PASS', 'production_ready': True, 'model_implemented': True},
                       {'force': True, 'skip_validation': True, 'allow_production': True},
                       {'gate_c': 'PASS', 'gate_d': 'PASS', 'adoption': 'APPROVED',
                        'owner_approval': True, 'receipt': {'status': 'PASS'}}):
            result = contract.validate_recipe(bypass)
            self.assert_envelope(result)
            self.assertNotEqual(result['binding_validation'], 'PASS')

    def test_validation_does_not_mutate_caller_recipe(self):
        recipe = {'gate_b': 'PASS', 'nested': {'unbound': [1, None, 'UNKNOWN']}}
        original = copy.deepcopy(recipe)
        contract.validate_recipe(recipe)
        self.assertEqual(recipe, original)

    def test_diagnostics_are_deterministic(self):
        recipe = {'production_ready': True, 'frame': {}, 'constraints': [], 'tests': []}
        first = contract.validate_recipe(recipe)
        second = contract.validate_recipe(copy.deepcopy(recipe))
        self.assertEqual(first, second)


class RecipeMutationTests(unittest.TestCase):
    assert_envelope = IntakeEnvelopeTests.assert_envelope
    def setUp(self):
        self.recipe = bound_metadata_fixture()

    def reject(self, recipe, code=None):
        result = contract.validate_recipe(recipe)
        self.assert_envelope(result)
        self.assertNotEqual(result['binding_validation'], 'PASS')
        if code is not None:
            self.assertIn(code, {issue['code'] for issue in result['issues']})
        return result

    def test_honest_unknown_starter_is_incomplete_not_invalid(self):
        result = contract.validate_recipe(template.make_recipe())
        self.assert_envelope(result)
        self.assertEqual(result['binding_validation'], 'INCOMPLETE')

    def test_complete_synthetic_metadata_is_not_gate_b_or_a_model(self):
        result = contract.validate_recipe(self.recipe)
        self.assert_envelope(result)
        self.assertEqual(result['binding_validation'], 'PASS', result['issues'])
        self.assertEqual(result['issues'], [])

    def test_completion_assertions_cannot_flip_gates_on_complete_metadata(self):
        self.recipe.update(gate_b='PASS', production_ready=True, model_implemented=True,
                           force=True, skip_validation=True, gate_c='PASS', gate_d='PASS',
                           owner_approval={'status': 'PASS', 'scientifically_accepted': True})
        self.assert_envelope(contract.validate_recipe(self.recipe))

    def test_missing_numerical_tolerances_are_not_accepted(self):
        for field in ('atol', 'rtol'):
            for omitted in (False, True):
                recipe = copy.deepcopy(self.recipe)
                if omitted: del recipe['tests'][0]['tolerance'][field]
                else: recipe['tests'][0]['tolerance'][field] = None
                with self.subTest(field=field, omitted=omitted): self.reject(recipe, 'UNBOUND_TOLERANCE')

    def test_nonfinite_boolean_negative_and_string_tolerances_rejected(self):
        for value in (float('nan'), float('inf'), -float('inf'), True, False, -1., '0.01', [], {}):
            recipe = copy.deepcopy(self.recipe); recipe['tests'][0]['tolerance']['atol'] = value
            with self.subTest(value=value): self.reject(recipe, 'INVALID_TOLERANCE')

    def test_duplicate_ids_in_every_inventory_rejected(self):
        for key in ('sources', 'input_groups', 'families', 'constraints', 'tests'):
            recipe = copy.deepcopy(self.recipe); recipe[key].append(copy.deepcopy(recipe[key][0]))
            with self.subTest(key=key): self.reject(recipe, 'DUPLICATE_ID')

    def test_missing_required_groups_families_and_test_rows(self):
        for key, code in (('input_groups', 'MISSING_GROUP'), ('families', 'MISSING_FAMILY'), ('tests', 'MISSING_TEST')):
            recipe = copy.deepcopy(self.recipe); recipe[key].pop()
            with self.subTest(key=key): self.reject(recipe, code)

    def test_incompatible_units_world_and_recipe_status_rejected(self):
        for path, value in ((('frame', 'horizontal_unit'), 'km'), (('frame', 'vertical_unit'), 'feet'),
                            (('world_id',), 'earth'), (('world_state',), 'temporal_simulation'),
                            (('source_status',), 'CANON')):
            recipe = copy.deepcopy(self.recipe)
            target = recipe
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path): self.reject(recipe)

    def test_incompatible_normalised_axes_rejected(self):
        self.recipe['frame']['y_direction'] = self.recipe['frame']['x_direction']
        self.reject(self.recipe)

    def test_hard_derived_controls_need_owner_review_not_ancestry(self):
        row = self.recipe['constraints'][0]; row.update(role='hard', derived_predecessor=True)
        self.reject(self.recipe, 'HARD_DERIVED_OWNER_REVIEW')
        row['owner_decision_source_ids'] = ['S0']
        row['asserted_owner_approval'] = {'status': 'PASS'}
        result = self.reject(self.recipe, 'HARD_DERIVED_OWNER_REVIEW')
        self.assert_envelope(result)

    def test_constraint_intervals_require_finite_ordered_nonboolean_numbers(self):
        for interval in (None, [], [1], [2, 1], [False, 1.], [0., float('inf')], ['0', '2']):
            recipe = copy.deepcopy(self.recipe); recipe['constraints'][0]['interval'] = interval
            with self.subTest(interval=interval): self.reject(recipe, 'CONSTRAINT_INTERVAL')

    def test_calibration_holdout_alias_overlap_rejected(self):
        self.recipe['sources'][2]['sha256'] = self.recipe['sources'][1]['sha256']
        self.reject(self.recipe, 'HOLDOUT_LEAKAGE')

    def test_active_unsupported_family_not_silently_admitted(self):
        self.recipe['families'][0]['support'] = 'UNSUPPORTED'
        self.reject(self.recipe, 'UNSUPPORTED_FAMILY')

    def test_inactive_family_requires_reason_and_source(self):
        self.recipe['families'][0].update(state='INACTIVE', reason=None, source_ids=[])
        self.reject(self.recipe)

    def test_additional_family_cannot_be_announced_without_inventory(self):
        self.recipe['coverage']['additional_family_inventory'] = 'COMPLETE_LISTED'
        self.reject(self.recipe, 'ADDITIONAL_FAMILY_LIST_EMPTY')

    def test_missing_coupling_or_development_envelope_rejected(self):
        for key in ('coupling', 'development_resources'):
            recipe = copy.deepcopy(self.recipe); del recipe[key]
            with self.subTest(key=key): self.reject(recipe)

    def test_missing_downstream_contract_rejected(self):
        self.recipe.pop('downstream', None)
        self.reject(self.recipe)

    def test_resource_limits_and_fixture_dimensions(self):
        for value in (0, -1, True, 1.5, float('inf')):
            recipe = copy.deepcopy(self.recipe); recipe['development_resources']['max_cells'] = value
            with self.subTest(value=value): self.reject(recipe)
        self.recipe['tests'][0]['fixture']['shape'] = [129, 129]
        self.reject(self.recipe, 'DEVELOPMENT_ENVELOPE')

    def test_malformed_enum_types_return_diagnostics_not_tracebacks(self):
        for path in (('mode',), ('families', 0, 'state'), ('families', 0, 'support'),
                     ('coverage', 'additional_family_inventory'), ('constraints', 0, 'role'),
                     ('tests', 0, 'fixture', 'split'), ('tests', 0, 'acceptance_layer')):
            for value in ([], {}, ['BOUND']):
                recipe = copy.deepcopy(self.recipe); target = recipe
                for key in path[:-1]: target = target[key]
                target[path[-1]] = value
                with self.subTest(path=path, value=value): self.reject(recipe)

    def test_malformed_top_level_containers_fail_closed(self):
        for key in ('frame', 'sources', 'input_groups', 'families', 'constraints', 'tests', 'coupling', 'coverage'):
            recipe = copy.deepcopy(self.recipe); recipe[key] = 'not-an-object-or-list'
            with self.subTest(key=key): self.reject(recipe)

    def test_huge_integer_tolerance_fails_closed(self):
        self.recipe['tests'][0]['tolerance']['atol'] = 10 ** 1000
        self.reject(self.recipe)

    def test_invalid_source_id_reference_hash_and_size(self):
        for mutate in (lambda r: r['sources'][0].update(sha256='X' * 64),
                       lambda r: r['sources'][0].update(bytes=True),
                       lambda r: r['families'][0].update(source_ids=['unknown-source'])):
            recipe = copy.deepcopy(self.recipe); mutate(recipe); self.reject(recipe)

    def test_malformed_owner_fields_have_valid_diagnostic_records(self):
        self.recipe['families'][0]['owner'] = ['not-an-owner-string']
        self.reject(self.recipe)

    def test_physical_band_must_be_frozen_and_not_boolean(self):
        for band in (None, [], [1., 0.], [False, 1.], [0., float('nan')]):
            recipe = copy.deepcopy(self.recipe)
            recipe['tests'][0]['acceptance_layer'] = 'physical'
            recipe['tests'][0]['tolerance']['physical_band'] = band
            with self.subTest(band=band): self.reject(recipe)

    def test_each_downstream_dependency_is_required(self):
        for item in self.recipe['downstream']['dependent_products']:
            recipe = copy.deepcopy(self.recipe); recipe['downstream']['dependent_products'].remove(item)
            with self.subTest(item=item): self.reject(recipe, 'DEPENDENCY_COVERAGE')


class PackageFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='terrain-contract-test-')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def check_bytes(self, content, expected=None):
        path = self.root / 'PACKAGE_MANIFEST.json'
        path.write_bytes(content)
        before = path.read_bytes()
        result = contract.verify_package(path, expected or hashlib.sha256(content).hexdigest())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(result['status'], 'FAIL')
        self.assertIsInstance(result['issues'], list)
        self.assertTrue(result['issues'])
        return result

    def test_manifest_pin_mismatch(self):
        self.check_bytes(b'{}', '0' * 64)

    def test_invalid_manifest_json(self):
        for content in (b'{', b'not JSON', b'[]', b'null'):
            with self.subTest(content=content): self.check_bytes(content)

    def test_empty_manifest_is_not_a_verified_package(self):
        self.check_bytes(b'{}')

    def test_duplicate_json_keys_fail_even_with_matching_whole_file_hash(self):
        self.check_bytes(b'{"files":[],"files":[]}')

    def test_nonfinite_json_fails_even_with_matching_whole_file_hash(self):
        for value in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(value=value):
                self.check_bytes(('{"value":' + value + '}').encode())

    def test_excessive_json_nesting_fails_closed(self):
        self.check_bytes(b'{"nested":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}')

    def test_missing_manifest_fails_closed(self):
        result = contract.verify_package(self.root / 'missing.json', '0' * 64)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['issues'])

    def package(self):
        files = []
        for name in ('first.md', 'second.md'):
            path = self.root / name; content = ('fixture-' + name).encode(); path.write_bytes(content)
            files.append({'path': str(path), 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
        manifest = {'schema': contract.PACKAGE_SCHEMA, 'source_status': 'WORKING NON-CANON',
                    'files': files, 'specialist_sources': []}
        return manifest

    def run_package(self, manifest):
        path = self.root / 'PACKAGE_MANIFEST.json'
        raw = json.dumps(manifest).encode(); path.write_bytes(raw)
        return contract.verify_package(path, hashlib.sha256(raw).hexdigest())

    def test_verified_tiny_package_means_integrity_not_permission(self):
        result = self.run_package(self.package())
        self.assertEqual(result['status'], 'PASS', result['issues'])
        self.assertIs(result['generation_authorised'], False)
        self.assertEqual(result['source_status'], 'WORKING NON-CANON')

    def test_member_content_or_size_mismatch_rejected(self):
        for field, value in (('sha256', '0' * 64), ('bytes', 999), ('bytes', True)):
            manifest = self.package(); manifest['files'][0][field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(self.run_package(manifest)['status'], 'FAIL')

    def test_duplicate_member_and_normalised_path_alias_rejected(self):
        manifest = self.package(); manifest['files'].append(copy.deepcopy(manifest['files'][0]))
        self.assertEqual(self.run_package(manifest)['status'], 'FAIL')
        alias = self.root / 'sub'; alias.mkdir()
        manifest['files'][-1]['path'] = str(alias / '..' / 'first.md')
        self.assertEqual(self.run_package(manifest)['status'], 'FAIL')

    def test_member_drift_while_remaining_package_is_read_rejected(self):
        manifest = self.package(); original = contract.file_pin; changed = False
        first = self.root / 'first.md'; second = self.root / 'second.md'
        def drift(path, **kwargs):
            nonlocal changed
            result = original(path, **kwargs)
            if Path(path) == second and not changed:
                first.write_bytes(b'changed-after-verification'); changed = True
            return result
        with patch.object(contract, 'file_pin', side_effect=drift):
            result = self.run_package(manifest)
        self.assertTrue(changed)
        self.assertEqual(result['status'], 'FAIL')


class IntakeOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='terrain-intake-output-test-')
        self.root = Path(self.temp.name)
        self.allowed = self.root / 'outputs' / 'terrain-model-r1'
        self.file_patch = patch.object(intake, '__file__', str(self.root / 'work' / 'terrain_model_r1' / 'intake.py'))
        self.file_patch.start()

    def tearDown(self):
        self.file_patch.stop()
        self.temp.cleanup()

    def test_new_child_writes_only_metadata_with_exact_product_receipts(self):
        output = self.allowed / 'test-01'
        recipe = template.make_recipe()
        report = {'model_implemented': False, 'production_ready': False, 'terrain_generated': False}
        intake.write_checkpoint(output, recipe, report)
        self.assertEqual({p.name for p in output.iterdir()}, {'RECIPE_UNBOUND.json', 'INTAKE_REPORT.json', 'INTAKE_RECEIPT.json'})
        receipt = json.loads((output / 'INTAKE_RECEIPT.json').read_text())
        self.assertIs(receipt['terrain_generated'], False)
        self.assertIs(receipt['authority_changed'], False)
        for item in receipt['products']:
            path = Path(item['path'])
            self.assertTrue(path.is_relative_to(output))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item['sha256'])
            self.assertEqual(path.stat().st_size, item['bytes'])

    def test_existing_output_is_never_overwritten(self):
        output = self.allowed / 'existing'; output.mkdir(parents=True)
        prior = output / 'RECIPE_UNBOUND.json'; prior.write_bytes(b'original evidence')
        with self.assertRaises(FileExistsError): intake.write_checkpoint(output, {}, {})
        self.assertEqual(prior.read_bytes(), b'original evidence')
        self.assertEqual(list(output.iterdir()), [prior])

    def test_outside_sibling_parent_and_root_paths_are_rejected(self):
        for output in (self.root / 'outside', self.allowed,
                       self.root / 'outputs' / 'terrain-model-r1-escape' / 'run',
                       self.allowed / '..' / 'escaped'):
            with self.subTest(output=output):
                with self.assertRaises(ValueError): intake.write_checkpoint(output, {}, {})
        self.assertFalse(self.allowed.exists())

    def test_linked_ancestor_rejected_without_writes(self):
        self.allowed.mkdir(parents=True)
        output = self.allowed / 'new'
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda path: path == self.allowed or original(path)):
            with self.assertRaises(ValueError): intake.write_checkpoint(output, {}, {})
        self.assertFalse(output.exists())

    def test_serialisation_failure_preserves_partial_no_success_receipt(self):
        output = self.allowed / 'failed'
        with self.assertRaises(ValueError): intake.write_checkpoint(output, {'invalid': float('nan')}, {})
        self.assertTrue(output.exists())
        self.assertFalse((output / 'INTAKE_RECEIPT.json').exists())
        with self.assertRaises(FileExistsError): intake.write_checkpoint(output, {}, {})

    def test_product_drift_before_receipt_is_detected(self):
        output = self.allowed / 'drifting'
        original = intake.file_pin
        def drift(path, **kwargs):
            result = original(path, **kwargs)
            if Path(path).name == 'INTAKE_REPORT.json':
                with (output / 'RECIPE_UNBOUND.json').open('ab') as stream:
                    stream.write(b'changed-after-initial-pin')
            return result
        with patch.object(intake, 'file_pin', side_effect=drift):
            with self.assertRaises(ValueError): intake.write_checkpoint(output, {}, {})

    def test_checkpoint_detects_changed_inspection_sources(self):
        package = {'status': 'PASS', 'verified': []}
        with patch.object(intake, 'collect', side_effect=[(package, [], []), (package, [{'changed': True}], [])]):
            with self.assertRaisesRegex(ValueError, 'changed'): intake.checkpoint(self.root)
        self.assertFalse(self.allowed.exists())

    def test_external_recipe_is_metadata_only_and_never_executes_its_sources(self):
        path = self.root / 'external.json'; path.write_text(json.dumps(bound_metadata_fixture()))
        package = {'status': 'PASS', 'verified': []}
        with patch.object(intake, 'collect', return_value=(package, [], [])) as collect:
            recipe, report = intake.checkpoint(self.root, path)
        self.assertEqual(collect.call_count, 2)
        self.assertEqual(report['recipe_source_verification'], 'NOT_VERIFIED_EXTERNAL_RECIPE_METADATA_ONLY')
        self.assertIs(report['terrain_generated'], False)
        self.assertIs(report['production_ready'], False)
        self.assertIs(report['model_implemented'], False)
        self.assertEqual(report['gates']['B'], 'INCOMPLETE')
        self.assertFalse(self.allowed.exists())


if __name__ == '__main__':
    unittest.main()
