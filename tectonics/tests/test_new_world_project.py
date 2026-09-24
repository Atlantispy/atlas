"""Lossless local project persistence; one small real candidate, no seed search."""
import copy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from numpy.testing import assert_array_equal

TECTONICS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TECTONICS / 'tools'))
sys.path.insert(0, str(TECTONICS / 'src'))

import new_world_contract as contract
import new_world_layout as layout
import new_world_project as project
import new_world_structure as structure_api
import new_world_motion as motion_api
import atlas_tectonics.planetary_generation as planetary
import atlas_tectonics.plate_layout as native_layout


def small_plan():
    settings = dict(
        radius_m=dict(mode='fixed', value=6371000.),
        gravity_m_s2=dict(mode='fixed', value=9.81),
        plate_count=dict(mode='fixed', value=6),
        continental_fraction=dict(mode='fixed', value=.3),
    )
    return contract.resolve_request(contract.new_request(
        f'{41:032x}', settings=settings, support_cells=192,
        resources=dict(max_work_bytes=128 << 20, max_wall_seconds=30.)))


class NewWorldProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = small_plan()
        cls.candidate = layout.generate_layout_candidate(cls.plan)
        if cls.candidate.atlas is None:
            raise AssertionError('The fixed N6/support192/seed41 candidate refused: '
                                 + repr(cls.candidate.report['rejection']))
        cls.structure = structure_api.generate_structure(cls.plan)
        cls.motion = motion_api.generate_motion(cls.plan, cls.candidate, cls.structure)
        changed_request = copy.deepcopy(cls.plan['request'])
        changed_request['settings']['continental_fraction']['value'] = .4
        cls.foreign_plan = contract.resolve_request(changed_request)
        cls.foreign_structure = structure_api.generate_structure(cls.foreign_plan)
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / 'original.atlas'
            cls.manifest = project.save_project(original, cls.plan, cls.candidate,
                                                title='Fixture world')
            cls.saved_bytes = original.read_bytes()
            structured = Path(tmp) / 'structured.atlas'
            cls.structured_manifest = project.save_project(
                structured, cls.plan, cls.candidate, title='Structured fixture', structure=cls.structure)
            cls.structured_bytes = structured.read_bytes()
            moving = Path(tmp) / 'motion.atlas'
            cls.motion_manifest = project.save_project(
                moving, cls.plan, cls.candidate, title='Motion fixture',
                structure=cls.structure, motion=cls.motion)
            cls.motion_bytes = moving.read_bytes()
        # The original package and its directory are gone. Every later reopen
        # must be self-contained, not tied to a surviving original filesystem path.

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'world.atlas'
        self.path.write_bytes(self.saved_bytes)

    def assert_same_atlas(self, actual):
        expected = self.candidate.atlas
        self.assertEqual(actual.atlas_id, expected.atlas_id)
        self.assertEqual(actual.geometry_id, expected.geometry_id)
        self.assertEqual(actual.descriptor(), expected.descriptor())
        for name in ('vertex_directions', 'edge_vertices', 'side_patches', 'patch_areas_sr'):
            before, after = getattr(expected, name), getattr(actual, name)
            self.assertEqual(before.dtype, after.dtype)
            self.assertEqual(before.shape, after.shape)
            assert_array_equal(after, before)
            self.assertEqual(after.tobytes(), before.tobytes())

    def assert_load_refuses_unchanged(self, path):
        before = path.read_bytes()
        inventory = set(self.root.iterdir())
        with self.assertRaises((ValueError, OSError, zipfile.BadZipFile)):
            project.load_project(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(set(self.root.iterdir()), inventory)

    def rewrite_archive(self, destination, *, change_store=False, extra=False):
        with zipfile.ZipFile(self.path, 'r') as source:
            members = {item.filename: source.read(item) for item in source.infolist()}
        if change_store:
            payload = bytearray(members['arrays.sqlite'])
            self.assertGreater(len(payload), 128)
            payload[len(payload) // 2] ^= 1
            members['arrays.sqlite'] = bytes(payload)
        if extra:
            members['unexpected.txt'] = b'not part of an Atlas project'
        # A fresh ZIP computes valid per-member CRCs, so changed database bytes
        # must be refused by the project's own integrity binding.
        with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_STORED) as output:
            for name, value in members.items():
                output.writestr(name, value)

    def test_archive_inventory_manifest_and_store_digest(self):
        with zipfile.ZipFile(self.path, 'r') as archive:
            members = archive.infolist()
            self.assertEqual(len(members), 2)
            self.assertEqual({item.filename for item in members}, {'project.json', 'arrays.sqlite'})
            self.assertTrue(all(item.compress_type == zipfile.ZIP_STORED for item in members))
            manifest = json.loads(archive.read('project.json'))
            store_bytes = archive.read('arrays.sqlite')
        self.assertEqual(manifest, self.manifest)
        self.assertEqual(manifest['schema'], 'atlas.new-world-project.v1')
        self.assertEqual(manifest['title'], 'Fixture world')
        self.assertEqual(manifest['plan'], self.plan)
        self.assertEqual(manifest['report'], self.candidate.report)
        self.assertEqual(manifest['atlas_id'], self.candidate.atlas.atlas_id)
        self.assertEqual(manifest['geometry_id'], self.candidate.atlas.geometry_id)
        self.assertEqual(manifest['store_sha256'], hashlib.sha256(store_bytes).hexdigest())
        self.assertRegex(manifest['project_id'], r'^[0-9a-f]{64}$')
        self.assertLessEqual(len(store_bytes), 64 << 20)

    def test_exact_roundtrip_preserves_plan_seed_ids_and_native_arrays(self):
        restored = project.load_project(self.path)
        self.assertEqual(restored.manifest, self.manifest)
        self.assertEqual(restored.manifest['plan'], self.plan)
        self.assertEqual(restored.manifest['plan']['request']['seed'], f'{41:032x}')
        self.assertIsNone(restored.structure)
        self.assertIsNone(restored.motion)
        self.assert_same_atlas(restored.atlas)
        self.assertEqual(self.path.read_bytes(), self.saved_bytes)
        with self.assertRaises(ValueError):
            restored.atlas.vertex_directions.setflags(write=True)

    def test_moved_file_reopens_without_any_layout_or_partition_generation(self):
        destination = self.root / 'moved'
        destination.mkdir()
        moved = destination / 'renamed.atlas'
        self.path.rename(moved)
        self.assertFalse(self.path.exists())
        failure = AssertionError('Reopening must not regenerate the saved world.')
        with mock.patch.object(layout, 'generate_layout_candidate', side_effect=failure), \
             mock.patch.object(structure_api, 'generate_structure', side_effect=failure), \
             mock.patch.object(motion_api, 'generate_motion', side_effect=failure), \
             mock.patch.object(planetary, 'generate_planetary_partition', side_effect=failure), \
             mock.patch.object(native_layout, 'generate_plate_layout', side_effect=failure), \
             mock.patch.object(project, 'generate_layout_candidate', side_effect=failure, create=True):
            restored = project.load_project(moved)
        self.assertEqual(restored.manifest, self.manifest)
        self.assert_same_atlas(restored.atlas)
        self.assertEqual(moved.read_bytes(), self.saved_bytes)

    def test_v2_structure_roundtrip_and_native_identity_without_regeneration(self):
        path = self.root / 'structured.atlas'
        path.write_bytes(self.structured_bytes)
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read('project.json'))
            self.assertEqual(set(archive.namelist()), {'project.json', 'arrays.sqlite'})
            self.assertLessEqual(len(archive.read('project.json')), project.MAX_JSON)
            self.assertLessEqual(len(archive.read('arrays.sqlite')), project.MAX_STORE)
        self.assertEqual(manifest['schema'], 'atlas.new-world-project.v2')
        self.assertEqual(set(manifest), set(self.manifest) | {'structure_id'})
        self.assertEqual(manifest, self.structured_manifest)
        failure = AssertionError('Reopen must restore native structure, never regenerate.')
        with mock.patch.object(structure_api, 'generate_structure', side_effect=failure), \
             mock.patch.object(motion_api, 'generate_motion', side_effect=failure), \
             mock.patch.object(layout, 'generate_layout_candidate', side_effect=failure):
            restored = project.load_project(path)
        self.assertEqual(restored.manifest, manifest)
        self.assertIsNone(restored.motion)
        self.assert_same_atlas(restored.atlas)
        self.assertEqual(restored.structure.report, self.structure.report)
        self.assertEqual(structure_api.structure_view(restored.structure),
                         structure_api.structure_view(self.structure))
        # Re-encoding the restored native record verifies its complete identified
        # contents, including fields omitted from the small interactive view.
        Store, limits, _, _ = project._native()
        with Store(self.root / 'identity-check.sqlite', limits) as store:
            identity = structure_api.save_structure(restored.structure, store)
        self.assertEqual(identity, manifest['structure_id'])
        self.assertEqual(path.read_bytes(), self.structured_bytes)

    def test_structure_from_another_plan_refuses_without_publication(self):
        target = self.root / 'mismatched-structure.atlas'
        with self.assertRaises(contract.ContractError):
            project.save_project(target, self.plan, self.candidate, structure=self.foreign_structure)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_v2_overwrite_and_missing_structure_identity_refuse(self):
        with self.assertRaises((ValueError, OSError)):
            project.save_project(self.path, self.plan, self.candidate, structure=self.structure)
        self.assertEqual(self.path.read_bytes(), self.saved_bytes)
        path = self.root / 'missing-structure.atlas'
        with zipfile.ZipFile(io.BytesIO(self.structured_bytes)) as archive:
            manifest = json.loads(archive.read('project.json'))
            database = archive.read('arrays.sqlite')
        manifest['structure_id'] = '0' * 64
        manifest['project_id'] = hashlib.sha256(contract.canonical_bytes(
            {key: value for key, value in manifest.items() if key != 'project_id'})).hexdigest()
        with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('project.json', contract.canonical_bytes(manifest))
            archive.writestr('arrays.sqlite', database)
        self.assert_load_refuses_unchanged(path)

    def test_v3_exact_motion_roundtrip_never_calls_any_producer(self):
        path = self.root / 'motion.atlas'
        path.write_bytes(self.motion_bytes)
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read('project.json'))
            self.assertEqual(set(archive.namelist()), {'project.json', 'arrays.sqlite'})
            self.assertLessEqual(len(archive.read('project.json')), project.MAX_JSON)
            self.assertLessEqual(len(archive.read('arrays.sqlite')), project.MAX_STORE)
        self.assertEqual(manifest['schema'], 'atlas.new-world-project.v3')
        self.assertEqual(set(manifest), set(self.structured_manifest) | {'motion_id'})
        self.assertEqual(manifest, self.motion_manifest)
        self.assertEqual(set(manifest['report']), {'schema', 'report_id', 'size_bytes'})
        self.assertEqual(manifest['report']['schema'], project.REPORT_SCHEMA)
        self.assertEqual(manifest['report']['report_id'],
                         hashlib.sha256(project._report_bytes(self.candidate.report)).hexdigest())
        failure = AssertionError('Opening v3 must restore saved fields without generating.')
        with mock.patch.object(motion_api, 'generate_motion', side_effect=failure), \
             mock.patch.object(structure_api, 'generate_structure', side_effect=failure), \
             mock.patch.object(layout, 'generate_layout_candidate', side_effect=failure):
            restored = project.load_project(path)
        self.assertEqual(restored.manifest, manifest)
        self.assert_same_atlas(restored.atlas)
        self.assertEqual(restored.structure.report, self.structure.report)
        self.assertEqual(restored.motion.motion_id, self.motion.motion_id)
        self.assertEqual(restored.motion.descriptor(), self.motion.descriptor())
        self.assertEqual(motion_api.motion_view(restored.motion), motion_api.motion_view(self.motion))
        Store, limits, _, _ = project._native()
        with Store(self.root / 'motion-identity.sqlite', limits) as store:
            self.assertEqual(motion_api.save_motion(restored.motion, store), manifest['motion_id'])
        self.assertEqual(path.read_bytes(), self.motion_bytes)

    def test_v3_original_inline_report_remains_readable_without_rebinding(self):
        with zipfile.ZipFile(io.BytesIO(self.motion_bytes)) as archive:
            manifest = json.loads(archive.read('project.json'))
            database = archive.read('arrays.sqlite')
        manifest['report'] = self.candidate.report
        manifest['project_id'] = project._digest(
            {key: value for key, value in manifest.items() if key != 'project_id'})
        path = self.root / 'original-inline.atlas'
        with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('project.json', contract.canonical_bytes(manifest))
            archive.writestr('arrays.sqlite', database)
        failure = AssertionError('An original inline v3 archive must never regenerate.')
        with mock.patch.object(motion_api, 'generate_motion', side_effect=failure), \
             mock.patch.object(structure_api, 'generate_structure', side_effect=failure), \
             mock.patch.object(layout, 'generate_layout_candidate', side_effect=failure):
            restored = project.load_project(path)
        self.assertEqual(restored.manifest, manifest)
        self.assertEqual(restored.motion.descriptor(), self.motion.descriptor())

    def test_v3_report_receipt_bound_and_dependency_integrity_refuse(self):
        report = copy.deepcopy(self.candidate.report)
        report['oversized'] = 'x' * project.MAX_REPORT
        target = self.root / 'oversized-report.atlas'
        with mock.patch.object(project, '_native') as native, self.assertRaises(contract.ContractError):
            project.save_project(target, self.plan, replace(self.candidate, report=report),
                                 structure=self.structure, motion=self.motion)
        native.assert_not_called()
        self.assertFalse(target.exists())
        with zipfile.ZipFile(io.BytesIO(self.motion_bytes)) as archive:
            original = json.loads(archive.read('project.json'))
            database = archive.read('arrays.sqlite')
        for key, value in (('size_bytes', project.MAX_REPORT + 1), ('report_id', '0' * 64)):
            manifest = copy.deepcopy(original)
            manifest['report'][key] = value
            manifest['project_id'] = project._digest(
                {name: item for name, item in manifest.items() if name != 'project_id'})
            path = self.root / (key + '.atlas')
            with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_STORED) as archive:
                archive.writestr('project.json', contract.canonical_bytes(manifest))
                archive.writestr('arrays.sqlite', database)
            with self.subTest(key=key):
                self.assert_load_refuses_unchanged(path)
        self.assertEqual(self.path.read_bytes(), self.saved_bytes)

    def test_v3_materialised_report_must_match_original_plan(self):
        with zipfile.ZipFile(io.BytesIO(self.motion_bytes)) as archive:
            manifest = json.loads(archive.read('project.json'))
            database = self.root / 'changed-report.sqlite'
            database.write_bytes(archive.read('arrays.sqlite'))
        report = copy.deepcopy(self.candidate.report)
        report['plan_id'] = '0' * 64
        Store, limits, _, _ = project._native()
        with Store(database, limits) as store:
            manifest['report'] = project._save_report(project._report_bytes(report), store)
        manifest['store_sha256'] = project._file_digest(database)
        manifest['project_id'] = project._digest(
            {key: value for key, value in manifest.items() if key != 'project_id'})
        path = self.root / 'mismatched-report.atlas'
        with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('project.json', contract.canonical_bytes(manifest))
            archive.write(database, 'arrays.sqlite')
        with self.assertRaises(contract.ContractError):
            project.load_project(path)
        self.assertEqual(self.path.read_bytes(), self.saved_bytes)

    def test_motion_requires_structure_and_matching_upstreams(self):
        target = self.root / 'invalid-motion.atlas'
        with self.assertRaises(contract.ContractError):
            project.save_project(target, self.plan, self.candidate, motion=self.motion)
        self.assertFalse(target.exists())
        foreign_candidate = layout.generate_layout_candidate(self.foreign_plan)
        self.assertIsNotNone(foreign_candidate.atlas, foreign_candidate.report)
        foreign_motion = motion_api.generate_motion(self.foreign_plan, foreign_candidate, self.foreign_structure)
        with self.assertRaises(contract.ContractError):
            project.save_project(target, self.plan, self.candidate,
                                 structure=self.structure, motion=foreign_motion)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_v3_missing_motion_dependency_refuses_and_keeps_original_bytes(self):
        path = self.root / 'missing-motion.atlas'
        with zipfile.ZipFile(io.BytesIO(self.motion_bytes)) as archive:
            manifest = json.loads(archive.read('project.json'))
            database = archive.read('arrays.sqlite')
        manifest['motion_id'] = '0' * 64
        manifest['project_id'] = hashlib.sha256(contract.canonical_bytes(
            {key: value for key, value in manifest.items() if key != 'project_id'})).hexdigest()
        with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('project.json', contract.canonical_bytes(manifest))
            archive.writestr('arrays.sqlite', database)
        self.assert_load_refuses_unchanged(path)
        self.assertEqual(self.path.read_bytes(), self.saved_bytes)

    def test_existing_destination_is_never_overwritten(self):
        with self.assertRaises((ValueError, OSError)):
            project.save_project(self.path, self.plan, self.candidate, title='Replacement refused')
        self.assertEqual(self.path.read_bytes(), self.saved_bytes)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_rejected_or_mismatched_candidate_never_publishes_a_project(self):
        rejected_report = copy.deepcopy(self.candidate.report)
        rejected_report.update(status='REJECTED', atlas_id=None, geometry_id=None,
                               rejection=dict(code='GEOMETRY_REFUSED', message='Synthetic refusal'))
        rejected = replace(self.candidate, atlas=None, report=rejected_report)
        mismatched_report = copy.deepcopy(self.candidate.report)
        mismatched_report['plan_id'] = '0' * 64
        mismatched = replace(self.candidate, report=mismatched_report)
        request = copy.deepcopy(self.plan['request'])
        request['settings']['gravity_m_s2']['value'] = 8.
        changed_plan = contract.resolve_request(request)
        for index, (prepared, candidate) in enumerate((
            (self.plan, rejected), (self.plan, mismatched), (changed_plan, self.candidate),
        )):
            target = self.root / f'refused-{index}.atlas'
            with self.subTest(index=index), self.assertRaises((ValueError, OSError)):
                project.save_project(target, prepared, candidate)
            self.assertFalse(target.exists())
            self.assertEqual(self.path.read_bytes(), self.saved_bytes)
            self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_changed_database_bytes_refuse_despite_valid_zip_crc(self):
        corrupted = self.root / 'changed-store.atlas'
        self.rewrite_archive(corrupted, change_store=True)
        self.assert_load_refuses_unchanged(corrupted)
        self.assertEqual(self.path.read_bytes(), self.saved_bytes)

    def test_unexpected_zip_member_refuses_without_extraction(self):
        extra = self.root / 'unexpected-member.atlas'
        self.rewrite_archive(extra, extra=True)
        self.assert_load_refuses_unchanged(extra)
        self.assertFalse((self.root / 'unexpected.txt').exists())
        self.assertEqual(self.path.read_bytes(), self.saved_bytes)

    def test_old_configuration_is_inspectable_without_rebinding(self):
        changed = contract.ContractError('SOURCE_MISMATCH', 'Synthetic source change')
        with mock.patch.object(project, 'validate_plan', side_effect=changed):
            restored = project.load_project(self.path)
        self.assertFalse(restored.configuration_compatible)
        self.assertEqual(restored.manifest['plan'], self.plan)
        self.assert_same_atlas(restored.atlas)

    def test_failed_publication_leaves_no_partial_project(self):
        target = self.root / 'unpublished.atlas'
        with mock.patch.object(project._Directory, 'publish', side_effect=OSError('Synthetic failure')):
            with self.assertRaises(OSError):
                project.save_project(target, self.plan, self.candidate)
        self.assertEqual(list(self.root.iterdir()), [self.path])
        self.assertEqual(self.path.read_bytes(), self.saved_bytes)


class LargeReportProjectTests(unittest.TestCase):
    def test_native_1024_cell_report_roundtrip_preserves_complete_receipt(self):
        request = copy.deepcopy(small_plan()['request'])
        request['resolution']['support_cells'] = 1024
        request['settings']['plate_count']['value'] = 12
        request['resources'] = dict(max_work_bytes=256 << 20, max_wall_seconds=120.)
        plan = contract.resolve_request(request)
        structure = structure_api.generate_structure(plan)
        candidate = layout.generate_layout_candidate(plan)
        self.assertIsNotNone(candidate.atlas, candidate.report.get('rejection'))
        motion = motion_api.generate_motion(plan, candidate, structure)
        report_bytes = project._report_bytes(candidate.report)
        self.assertGreater(len(report_bytes), project.MAX_JSON)
        self.assertLessEqual(len(report_bytes), project.MAX_REPORT)
        metadata_bytes = len(json.dumps(candidate.atlas.descriptor(), sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode('utf-8'))
        self.assertGreater(metadata_bytes, 1 << 20)
        self.assertLessEqual(metadata_bytes, project.MAX_NATIVE_METADATA)
        self.assertEqual(project.MAX_NATIVE_METADATA, 2 << 20)
        self.assertEqual(project._native()[1].max_manifest_bytes, 2 << 20)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'large-report.atlas'
            manifest = project.save_project(path, plan, candidate, structure=structure, motion=motion)
            before = path.read_bytes()
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()), {'project.json', 'arrays.sqlite'})
                self.assertLessEqual(len(archive.read('project.json')), project.MAX_JSON)
                self.assertLessEqual(len(archive.read('arrays.sqlite')), project.MAX_STORE)
            failure = AssertionError('Reopening the actual larger receipt must never regenerate.')
            with mock.patch.object(layout, 'generate_layout_candidate', side_effect=failure), \
                 mock.patch.object(structure_api, 'generate_structure', side_effect=failure), \
                 mock.patch.object(motion_api, 'generate_motion', side_effect=failure), \
                 mock.patch.object(project, '_check_pair', wraps=project._check_pair) as check:
                restored = project.load_project(path)
            self.assertEqual(check.call_args.args[1], candidate.report)
            self.assertEqual(restored.manifest, manifest)
            self.assertEqual(manifest['report']['size_bytes'], len(report_bytes))
            self.assertEqual(manifest['report']['report_id'], hashlib.sha256(report_bytes).hexdigest())
            self.assertEqual(restored.atlas.descriptor(), candidate.atlas.descriptor())
            self.assertEqual(restored.atlas.vertex_directions.tobytes(),
                             candidate.atlas.vertex_directions.tobytes())
            self.assertEqual(restored.motion.descriptor(), motion.descriptor())
            self.assertEqual(restored.structure.report, structure.report)
            self.assertEqual(path.read_bytes(), before)
        print(f'1024-cell archive: native metadata {metadata_bytes} bytes; '
              f'complete layout report {len(report_bytes)} bytes; '
              f'project manifest {len(contract.canonical_bytes(manifest))} bytes.')


if __name__ == '__main__':
    unittest.main()
