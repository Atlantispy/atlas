"""Verification cannot turn skipped, forged, stale or unreviewed work into PASS."""
from copy import deepcopy
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from . import verify as v


class VerificationTests(unittest.TestCase):
    def record(self):
        ids = ['example.exact_a', 'example.exact_b']
        return {'status': 'PASS', 'tests': 2, 'test_ids': ids, 'started': ids[:], 'stopped': ids[:], 'passed': ids[:],
            'failures': 0, 'errors': 0, 'skips': 0, 'expected_failures': 0, 'unexpected_successes': 0}

    def verify_record(self, record):
        ids = self.record()['test_ids']
        with patch.multiple(v, RELEASE_READY=True, EXPECTED_COUNT=2, INVENTORY_SHA256=v.sha(v.encoded(ids))):
            v.validate_tests(record)

    def test_exact_success_record(self):
        self.verify_record(self.record())

    def test_unreviewed_gate_blocks_seal(self):
        with patch.object(v, 'RELEASE_READY', False):
            with self.assertRaisesRegex(ValueError, 'pending'):
                v.require_inventory(self.record()['test_ids'])

    def test_equal_count_different_tests_rejected(self):
        row = self.record(); row['test_ids'] = ['other.a', 'other.b']
        with self.assertRaisesRegex(ValueError, 'inventory'):
            self.verify_record(row)

    def test_omitted_started_test_rejected(self):
        row = self.record(); row['started'] = row['started'][:1]
        with self.assertRaisesRegex(ValueError, 'identities'):
            self.verify_record(row)

    def test_omitted_passed_test_rejected(self):
        row = self.record(); row['passed'] = row['passed'][:1]
        with self.assertRaisesRegex(ValueError, 'identities'):
            self.verify_record(row)

    def test_reordered_stopped_test_rejected(self):
        row = self.record(); row['stopped'] = row['stopped'][::-1]
        with self.assertRaisesRegex(ValueError, 'identities'):
            self.verify_record(row)

    def test_skip_is_not_completion(self):
        row = self.record(); row['skips'] = 1
        with self.assertRaisesRegex(ValueError, 'skipped'):
            self.verify_record(row)

    def test_expected_failure_is_not_completion(self):
        row = self.record(); row['expected_failures'] = 1
        with self.assertRaisesRegex(ValueError, 'expected-failure'):
            self.verify_record(row)

    def test_boolean_zero_is_not_count(self):
        row = self.record(); row['errors'] = False
        with self.assertRaises(ValueError):
            self.verify_record(row)

    def test_failure_status_rejected(self):
        row = self.record(); row['status'] = 'FAIL'
        with self.assertRaisesRegex(ValueError, 'successful'):
            self.verify_record(row)

    def test_running_count_rejected(self):
        row = self.record(); row['tests'] = 1
        with self.assertRaisesRegex(ValueError, 'complete'):
            self.verify_record(row)

    def test_retained_verifier_exact_source_not_canonical(self):
        original, path, digest = v.retained_verifier()
        self.assertEqual(original.RESULT_SCHEMA, 'diadem.seasonal-world-result.r10')
        self.assertEqual(v.sha(path.read_bytes()), digest)

    def test_actual_worker_mode_not_parent_claim(self):
        b = SimpleNamespace(identity={'example': 'source'}, source_sha256='a'*64)
        row = {'status': 'PASS', 'source_identity': b.identity, 'source_sha256': b.source_sha256, 'optimisation_flag': 0}
        v.validate_worker_header(row, b, 0)
        with self.assertRaisesRegex(ValueError, 'actual worker'):
            v.validate_worker_header(row, b, 2)

    def test_worker_source_hash_cannot_be_forged(self):
        b = SimpleNamespace(identity={'example': 'source'}, source_sha256='a'*64)
        row = {'status': 'PASS', 'source_identity': b.identity, 'source_sha256': 'b'*64, 'optimisation_flag': 0}
        with self.assertRaisesRegex(ValueError, 'source'):
            v.validate_worker_header(row, b, 0)

    def test_empty_actual_execution_map_rejected(self):
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            v.require_executed_sources({}, {'a': 'x'}, ['a'], str)

    def test_omitted_required_execution_rejected(self):
        with self.assertRaisesRegex(ValueError, 'required'):
            v.require_executed_sources({'b': 'y'}, {'a': 'x', 'b': 'y'}, ['a'], str)

    def test_extra_unbound_execution_rejected(self):
        with self.assertRaisesRegex(ValueError, 'binding'):
            v.require_executed_sources({'a': 'x', 'b': 'y'}, {'a': 'x'}, ['a'], str)

    def test_exact_actual_execution_accepted(self):
        v.require_executed_sources({'a': 'x'}, {'a': 'x'}, ['a'], str)


class WorkflowStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from . import binding
        cls.bundle = binding.load()
        cls.codec = cls.bundle.parent.graph.load('work.generator_upgrade_r10.payloads')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        unit = self.codec.pack({'schema': 'explicit-test-artifact', 'example': [1,2,3]})
        self.key = unit['sha256']
        self.product = {'schema': 'explicit-storage-test-not-science', 'graph_artifact': {'example': 'graph'},
            'graph_checkpoint': {'example': 'checkpoint'}, 'graph_recipe': {'example': 'recipe'},
            'packed_artifacts': {self.key: unit}}
        self.record = v.persist_workflow(self.bundle, Path(self.temp.name)/'separate', self.product)

    def test_separate_bounded_artifacts_round_trip(self):
        self.assertEqual(v.read_workflow(self.bundle, self.record), self.product)
        self.assertEqual(len(self.record['files']), 5)

    def test_file_byte_change_rejected(self):
        path = Path(self.record['path'])/'graph.json'
        path.write_bytes(self.bundle.storage.encoded({'example': 'changed'}))  # Deliberately corrupt only this temporary test fixture.
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            v.read_workflow(self.bundle, self.record)

    def test_extra_unit_rejected(self):
        path = Path(self.record['path'])/'artifacts'/('e'*64+'.json')
        self.bundle.storage.write_json(path, {})
        with self.assertRaisesRegex(ValueError, 'inventory'):
            v.read_workflow(self.bundle, self.record)

    def test_rehashed_omission_cannot_hide_disk_artifact(self):
        del self.record['files']['artifacts/'+self.key+'.json']
        self.record['content_sha256'] = v.sha(v.encoded(self.record['files']))
        with self.assertRaisesRegex(ValueError, 'inventory'):
            v.read_workflow(self.bundle, self.record)

    def test_manifest_traversal_rejected(self):
        self.record['files']['../outside.json'] = 'e'*64
        with self.assertRaisesRegex(ValueError, 'file names'):
            v.read_workflow(self.bundle, self.record)

    def test_forged_content_address_rejected_even_if_file_rehashed(self):
        name = 'artifacts/'+self.key+'.json'; path = Path(self.record['path'])/name
        value = self.bundle.storage.read_json(path); value['sha256'] = 'e'*64
        path.write_bytes(self.bundle.storage.encoded(value))  # Deliberately rehash a forged temporary test fixture.
        self.record['files'][name] = v.sha(path.read_bytes())
        self.record['content_sha256'] = v.sha(v.encoded(self.record['files']))
        with self.assertRaisesRegex(ValueError, 'content address'):
            v.read_workflow(self.bundle, self.record)


class ConsequenceStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from . import binding
        cls.bundle = binding.load()
        cls.codec = cls.bundle.parent.graph.load('work.generator_upgrade_r10.payloads')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.unit = self.codec.pack({'scenario_id': 'explicit-storage-fixture', 'example': [1,2,3]})
        self.result = {'schema': 'diadem.seasonal-consequences-result.r11',
            'source_sha256': self.bundle.source_sha256, 'recipe_sha256': 'b'*64,
            'state': {'completed_scenarios': 1, 'parent_result_sha256': 'c'*64,
                'results': {'explicit-storage-fixture': self.unit}},
            'biological_owner_inputs': None}
        self.units = {}; self.values = {}; self.expected = {}
        for name in v.PARTITIONED_NAMES:
            value = self.bundle.checkpoint(self.result) if 'checkpoint' in name else self.result
            self.expected[name] = deepcopy(value)
            self.units.update(v.persist_consequence(self.bundle, self.root, name, value))
            self.values[name] = self.bundle.storage.read_json(self.root/name)

    def read(self):
        return v.read_consequences(self.bundle, self.root, self.values, self.units)

    def test_shared_units_restore_every_result_and_checkpoint(self):
        self.assertEqual(self.read(), self.expected)
        self.assertEqual(len(self.units), 1)
        self.assertEqual(len(list((self.root/'consequence-units').iterdir())), 1)

    def test_saved_unit_byte_corruption_rejected(self):
        path = self.root/'consequence-units'/(self.unit['sha256']+'.json')
        path.write_bytes(b'{}')  # Corrupt only this temporary fixture.
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            self.read()

    def test_rehashed_unit_corruption_cannot_hide_record_change(self):
        key = self.unit['sha256']; path = self.root/'consequence-units'/(key+'.json')
        raw = self.bundle.storage.encoded(self.codec.pack({'different': 'scientific record'}))
        path.write_bytes(raw)  # Deliberately forge this temporary fixture and its file hash.
        self.units[key] = v.sha(raw)
        with self.assertRaises(ValueError):
            self.read()

    def test_missing_required_partition_manifest_rejected(self):
        self.values.pop('restart-result.json')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            self.read()

    def test_extra_disk_unit_rejected(self):
        self.bundle.storage.write_json(self.root/'consequence-units'/('e'*64+'.json'), {})
        with self.assertRaisesRegex(ValueError, 'inventory'):
            self.read()

    def test_rehashed_orphan_unit_rejected(self):
        extra = self.codec.pack({'explicit': 'unreferenced'}); key = extra['sha256']
        path = self.root/'consequence-units'/(key+'.json'); self.bundle.storage.write_json(path, extra)
        self.units[key] = v.sha(path.read_bytes())
        with self.assertRaisesRegex(ValueError, 'orphan'):
            self.read()

    def test_traversing_content_address_rejected(self):
        self.units['../outside'] = 'e'*64
        with self.assertRaisesRegex(ValueError, 'checksum inventory'):
            self.read()

    def test_existing_changed_shared_unit_not_overwritten(self):
        path = self.root/'consequence-units'/(self.unit['sha256']+'.json')
        path.write_bytes(b'{}')  # Corrupt only this temporary fixture.
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            v.persist_consequence(self.bundle, self.root, 'full-result.json', self.result)
        self.assertEqual(path.read_bytes(), b'{}')

    def test_unlisted_partition_destination_rejected(self):
        with self.assertRaisesRegex(ValueError, 'filename'):
            v.persist_consequence(self.bundle, self.root, '../outside.json', self.result)


if __name__ == '__main__':
    unittest.main()
