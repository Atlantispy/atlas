import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import provenance as p
from .storage import encoded, sha


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.r3 = self.root / 'r3'
        self.r4 = self.root / 'r4'
        self.r3.mkdir()
        self.r4.mkdir()
        self.write(self.r4 / 'candidate.py', b'value = 1\n')
        self.owners = {'owner': 'SYNTHETIC TEST'}
        self.identity = {
            'r3_sources': self.map(self.r3 / 'retained.py'),
            'protected_sources': self.map(self.root / 'prior.py'),
            'executed_dependency_sources': self.map(self.root / 'foundation.py'),
            'category_contracts': self.map(self.root / 'category.json'),
            'physical_interfaces': self.map(self.root / 'interface.md'),
            'owner_bindings': self.owners,
            'runtime': {'python': 'fixture'},
            'predecessors': [],
        }
        for index in range(3):
            path = self.root / ('prior_seal_' + str(index) + '.json')
            raw = b'{}'
            self.write(path, raw)
            self.identity['predecessors'].append({'path': str(path), 'sha256': sha(raw),
                                                  'source_files': 1, 'tests_rerun': False})
        self.seal = self.root / 'VERIFICATION.json'
        self.record = {'status': 'BOUNDED_CONNECTED_REFERENCE_VERIFIED',
                       'source_identity': self.identity, 'source_snapshot': self.identity['r3_sources'],
                       'production_installed': False, 'canon_changed': False,
                       'new_world_generated': False, 'whole_generator_upgraded': False,
                       'prior_tests_rerun_or_recounted': False}
        self.climate = {}
        self.climate.update(self.map(self.root / 'climate_owner.md'))
        self.climate.update(self.map(self.root / 'climate_bindings.md'))
        source = self.root / 'candidate_source.dat'
        source_raw = b'bounded synthetic monthly data'
        self.write(source, source_raw)
        self.manifest = {'schema': 'diadem.r4.climate-source-bindings',
                         'status': 'EXPLICIT_REVIEW_AND_RETAINED_FIXED_FORCING_BINDINGS_NOT_CANON',
                         'reviewed_sources': {'example': {'path': str(source), 'sha256': sha(source_raw),
                                                          'review_scope': 'SYNTHETIC TEST'}},
                         'retained_bridge': {name: {'path': str(source), 'sha256': sha(source_raw),
                                                   'role': 'SYNTHETIC TEST'}
                                             for name in ('monthly', 'geometry', 'manifest', 'parameter_card', 'G_launcher', 'G_gate')}}
        self.write_manifest()
        self.patches = []
        for key, value in {'R3_ROOT': self.r3, 'HERE': self.r4, 'R3_SEAL': self.seal,
                           'EXPECTED_R3_COUNT': 1, 'EXPECTED_PROTECTED_COUNT': 1,
                           'EXPECTED_DEPENDENCY_COUNT': 1, 'EXPECTED_CATEGORY_COUNT': 1,
                           'CLIMATE_BINDINGS': self.climate}.items():
            self.patch(key, value)
        self.patch('_owner_bindings', lambda: copy.deepcopy(self.owners))
        self.patch('_hydromet_bindings', lambda: dict(self.climate))
        self.reseal()

    def patch(self, key, value):
        patcher = patch.object(p, key, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, path, raw):
        path.write_bytes(raw)

    def map(self, path):
        raw = ('fixture ' + path.name + '\n').encode()
        self.write(path, raw)
        return {str(path): sha(raw)}

    def reseal(self):
        self.record['source_sha256'] = sha(encoded(self.identity))
        raw = encoded(self.record)
        self.write(self.seal, raw)
        self.patch('R3_SEAL_SHA256', sha(raw))
        self.patch('R3_IDENTITY_SHA256', self.record['source_sha256'])

    def write_manifest(self):
        self.write(self.r4 / 'CLIMATE_SOURCE_BINDINGS.json', encoded(self.manifest))

    def test_live_seal_maps_and_separate_counts_preserved(self):
        result = p.retained_identity()
        self.assertEqual(result, self.identity)
        self.assertEqual(len(result['r3_sources']), 1)
        self.assertEqual(len(result['protected_sources']), 1)

    def test_full_source_identity_roundtrip_verifies_live_bytes(self):
        identity, digest = p.source_identity()
        self.assertEqual(sha(encoded(identity)), digest)
        self.assertEqual(p.verify_identity(identity), digest)
        self.assertFalse(identity['r3_preservation']['prior_tests_rerun_or_recounted'])
        self.assertEqual(identity['climate_owner_bindings'], self.climate)

    def test_corrupt_retained_seal_rejected_without_repin(self):
        self.write(self.seal, b'{}')
        with self.assertRaisesRegex(ValueError, 'no silent repin'):
            p.retained_identity()

    def test_corrupt_embedded_identity_digest_rejected(self):
        self.record['source_identity']['runtime']['python'] = 'changed'
        raw = encoded(self.record)
        self.write(self.seal, raw)
        self.patch('R3_SEAL_SHA256', sha(raw))
        with self.assertRaisesRegex(ValueError, 'identity digest'):
            p.retained_identity()

    def test_source_snapshot_must_match_sealed_r3_map(self):
        self.record['source_snapshot'] = {}
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'schema'):
            p.retained_identity()

    def test_unknown_identity_field_rejected(self):
        self.identity['hidden_default'] = True
        self.reseal()
        with self.assertRaises(ValueError):
            p.retained_identity()

    def test_changed_r3_source_rejected(self):
        self.write(next(iter(map(Path, self.identity['r3_sources']))), b'changed')
        with self.assertRaisesRegex(ValueError, 'no silent repin'):
            p.retained_identity()

    def test_extra_r3_source_rejected_even_if_existing_files_match(self):
        self.write(self.r3 / 'hidden.py', b'pass\n')
        with self.assertRaisesRegex(ValueError, 'exact directory inventory'):
            p.retained_identity()

    def test_removed_r3_source_rejected(self):
        next(iter(map(Path, self.identity['r3_sources']))).unlink()
        with self.assertRaises(ValueError):
            p.retained_identity()

    def test_changed_previous_source_rejected(self):
        self.write(next(iter(map(Path, self.identity['protected_sources']))), b'changed')
        with self.assertRaisesRegex(ValueError, 'no silent repin'):
            p.retained_identity()

    def test_changed_foundation_dependency_rejected(self):
        self.write(next(iter(map(Path, self.identity['executed_dependency_sources']))), b'changed')
        with self.assertRaisesRegex(ValueError, 'no silent repin'):
            p.retained_identity()

    def test_changed_category_contract_rejected(self):
        self.write(next(iter(map(Path, self.identity['category_contracts']))), b'changed')
        with self.assertRaisesRegex(ValueError, 'no silent repin'):
            p.retained_identity()

    def test_changed_physical_interface_rejected(self):
        self.write(next(iter(map(Path, self.identity['physical_interfaces']))), b'changed')
        with self.assertRaisesRegex(ValueError, 'no silent repin'):
            p.retained_identity()

    def test_changed_owner_bindings_rejected(self):
        self.patch('_owner_bindings', lambda: {'owner': 'unapproved successor'})
        with self.assertRaisesRegex(ValueError, 'owner bindings differ'):
            p.retained_identity()

    def test_changed_climate_decision_rejected(self):
        self.write(next(iter(map(Path, self.climate))), b'changed')
        with self.assertRaisesRegex(ValueError, 'no silent repin'):
            p.source_identity()

    def test_changed_previous_seal_rejected(self):
        self.write(Path(self.identity['predecessors'][0]['path']), b'{"changed":true}')
        with self.assertRaisesRegex(ValueError, 'no silent repin'):
            p.retained_identity()

    def test_predecessor_count_or_extra_fields_rejected(self):
        self.identity['predecessors'][0]['hidden'] = True
        self.reseal()
        with self.assertRaises(ValueError):
            p.retained_identity()

    def test_retained_source_count_cannot_be_reduced(self):
        self.patch('EXPECTED_PROTECTED_COUNT', 2)
        with self.assertRaisesRegex(ValueError, 'count'):
            p.retained_identity()

    def test_retained_status_cannot_be_promoted(self):
        self.record['production_installed'] = True
        self.reseal()
        with self.assertRaisesRegex(ValueError, 'status boundary'):
            p.retained_identity()

    def test_retained_tests_cannot_be_recounted_as_new(self):
        self.identity['predecessors'][0]['tests_rerun'] = True
        self.reseal()
        with self.assertRaises(ValueError):
            p.retained_identity()

    def test_current_source_mutation_detected_before_after(self):
        identity, _ = p.source_identity()
        self.write(self.r4 / 'candidate.py', b'value = 2\n')
        with self.assertRaisesRegex(ValueError, 'changed during operation'):
            p.verify_identity(identity)

    def test_current_source_addition_detected_before_after(self):
        identity, _ = p.source_identity()
        self.write(self.r4 / 'new_design.md', b'new')
        with self.assertRaises(ValueError):
            p.verify_identity(identity)

    def test_capture_ignores_bytecode_without_treating_it_as_source(self):
        before = p.capture_sources()
        cache = self.r4 / '__pycache__'
        cache.mkdir()
        self.write(cache / 'candidate.pyc', b'untrusted pyc')
        self.assertEqual(p.capture_sources(), before)

    def test_source_file_count_and_bytes_are_bounded(self):
        with patch.object(p, 'MAX_SOURCE_FILES', 0):
            with self.assertRaises(ValueError):
                p.capture_sources()
        with patch.object(p, 'MAX_SOURCE_BYTES', 1):
            with self.assertRaises(ValueError):
                p.capture_sources()
        with patch.object(p, 'MAX_CAPTURE_BYTES', 1):
            with self.assertRaises(ValueError):
                p.capture_sources()

    def test_source_map_requires_absolute_paths_and_exact_hashes(self):
        for mapping in ({'relative.py': 'a' * 64}, {str(self.r4 / 'candidate.py'): 'bad'}, {}, []):
            with self.assertRaises(ValueError):
                p.verify_map(mapping)

    def test_duplicate_seal_json_rejected_even_with_matching_byte_hash(self):
        raw = b'{"source_sha256":1,"source_sha256":2}'
        self.write(self.seal, raw)
        self.patch('R3_SEAL_SHA256', sha(raw))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            p.retained_identity()

    def test_empty_source_directory_rejected(self):
        empty = self.root / 'empty'
        empty.mkdir()
        with self.assertRaisesRegex(ValueError, 'empty'):
            p.capture_sources(empty)

    def test_verify_requires_complete_identity(self):
        for value in (None, 'a' * 64, [], {}):
            with self.assertRaises(ValueError):
                p.verify_identity(value)

    def test_actual_explicit_climate_manifest_hashes_bound(self):
        result = p.climate_source_bindings()
        self.assertEqual(result['record'], self.manifest)
        self.assertEqual(len(result['sources']), 1)

    def test_climate_manifest_unknown_or_missing_roles_rejected(self):
        del self.manifest['retained_bridge']['G_gate']
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'inventory'):
            p.climate_source_bindings()

    def test_climate_manifest_status_cannot_be_promoted(self):
        self.manifest['status'] = 'CANON'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'schema/status'):
            p.climate_source_bindings()

    def test_climate_manifest_extra_record_fields_rejected(self):
        self.manifest['reviewed_sources']['example']['approved'] = True
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'record differs'):
            p.climate_source_bindings()

    def test_climate_source_hash_conflicts_rejected(self):
        self.manifest['retained_bridge']['monthly']['sha256'] = 'a' * 64
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            p.climate_source_bindings()

    def test_changed_climate_data_rejected(self):
        path = Path(self.manifest['retained_bridge']['monthly']['path'])
        self.write(path, b'changed')
        with self.assertRaisesRegex(ValueError, 'no silent repin'):
            p.climate_source_bindings()

    def test_climate_data_resource_limits_rejected(self):
        with patch.object(p, 'MAX_EXTERNAL_SOURCE_BYTES', 1):
            with self.assertRaises(ValueError):
                p.climate_source_bindings()
        with patch.object(p, 'MAX_EXTERNAL_TOTAL_BYTES', 1):
            with self.assertRaises(ValueError):
                p.climate_source_bindings()

    def test_climate_binding_digest_part_of_complete_identity(self):
        before, _ = p.source_identity()
        self.manifest['reviewed_sources']['example']['review_scope'] = 'revised scope'
        self.write_manifest()
        with self.assertRaises(ValueError):
            p.verify_identity(before)


class LivePreservationTests(unittest.TestCase):
    def test_actual_sealed_r3_and_predecessor_source_bytes_remain_intact(self):
        identity = p.retained_identity()
        self.assertEqual(len(identity['r3_sources']), 25)
        self.assertEqual(len(identity['protected_sources']), 161)
        self.assertEqual(len(identity['executed_dependency_sources']), 2)
        self.assertEqual(len(identity['category_contracts']), 4)
        self.assertEqual(p.verify_map(p.CLIMATE_BINDINGS), p.CLIMATE_BINDINGS)
        self.assertEqual(len(p._hydromet_bindings()), 5)


if __name__ == '__main__':
    unittest.main()
