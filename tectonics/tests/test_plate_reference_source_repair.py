"""Regression tests for real-source preservation and complete offline delivery.

PB2002 is reference evidence, not perfect simulation topology. A deliberately
non-passing source-consistency report is an expected result of correctly detecting
its unresolved features; it must never be converted into geological acceptance.
All earlier tests, scientific thresholds and source pins remain unchanged.
"""
from dataclasses import FrozenInstanceError
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import CancelledError
from unittest import mock

import numpy as np
from numpy.testing import assert_array_equal

from atlas_tectonics.plate_reference_dataset import (
    ReferenceDataError, ReferenceCurve, PB2002_FILES, load_pb2002, lonlat_vectors,
    parse_dig, spherical_ring_measures, verify_source_bytes,
)
from atlas_tectonics.plate_reference_acceptance import (
    reference_dataset_report, reference_protocol, write_report_snapshot,
    read_report_snapshot,
)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'reference_data'/'pb2002'
DUPLICATED = 'AA\n0,0\n90,0\n90,0\n0,90\n0,0\n0,0\n*** end of line segment ***\n'
OPEN = 'AA\n0,0\n90,0\n0,90\n1,1\n*** end of line segment ***\n'


class SourceGeometryViews(unittest.TestCase):
    def test_strict_parser_still_rejects_duplicate_vertices(self):
        with self.assertRaises(ReferenceDataError):
            parse_dig(DUPLICATED, 'plate')

    def test_raw_repetitions_and_indices_are_retained(self):
        curve = parse_dig(DUPLICATED, 'plate', preserve_source_geometry=True)[0]
        assert_array_equal(curve.coordinates, [[0,0],[90,0],[90,0],[0,90],[0,0],[0,0]])
        self.assertEqual(curve.repeated_vertex_indices, (2,5))
        self.assertEqual(curve.count, 6)
        self.assertTrue(curve.explicitly_closed)

    def test_view_has_same_area_without_mutating_source(self):
        curve = parse_dig(DUPLICATED, 'plate', preserve_source_geometry=True)[0]
        before = curve.coordinates.tobytes()
        view = curve.measurement_coordinates()
        assert_array_equal(view, [[0,0],[90,0],[0,90],[0,0]])
        metrics = spherical_ring_measures(lonlat_vectors(view))
        self.assertAlmostEqual(metrics['area_steradians'], np.pi/2, places=13)
        self.assertEqual(curve.coordinates.tobytes(), before)

    def test_views_and_raw_storage_are_immutable(self):
        curve = parse_dig(DUPLICATED, 'plate', preserve_source_geometry=True)[0]
        for array in (curve.coordinates, curve.measurement_coordinates()):
            with self.assertRaises(ValueError):
                array.setflags(write=True)
        with self.assertRaises(FrozenInstanceError):
            curve.explicitly_closed = False

    def test_view_array_descriptor_does_not_mutate_future_views(self):
        curve = parse_dig(DUPLICATED, 'plate', preserve_source_geometry=True)[0]
        view = curve.measurement_coordinates(); view.shape = (8,)
        self.assertEqual(curve.measurement_coordinates().shape, (4,2))
        self.assertEqual(curve.coordinates.shape, (6,2))

    def test_nearby_but_unequal_vertices_are_not_snapped(self):
        text = DUPLICATED.replace('90,0\n90,0', '90,0\n90.0000000000001,0')
        with self.assertRaises(ReferenceDataError):
            parse_dig(text, 'plate', preserve_source_geometry=True)

    def test_antipodal_edges_still_refused(self):
        text = DUPLICATED.replace('90,0', '180,0')
        with self.assertRaises(ReferenceDataError):
            parse_dig(text, 'plate', preserve_source_geometry=True)

    def test_open_polygon_can_be_retained_but_not_measured(self):
        curve = parse_dig(OPEN, 'orogen', preserve_source_geometry=True)[0]
        self.assertFalse(curve.explicitly_closed)
        self.assertEqual(curve.coordinates[-1].tolist(), [1,1])
        with self.assertRaisesRegex(ReferenceDataError, 'no closure inferred'):
            curve.measurement_coordinates()

    def test_open_polygon_strict_default_unchanged(self):
        with self.assertRaises(ReferenceDataError):
            parse_dig(OPEN, 'orogen')

    def test_preservation_does_not_allow_malformed_syntax(self):
        with self.assertRaises(ReferenceDataError):
            parse_dig(DUPLICATED.replace('0,90', 'bad,record'), 'plate', preserve_source_geometry=True)
        with self.assertRaises(ReferenceDataError):
            parse_dig(DUPLICATED.split('***')[0], 'plate', preserve_source_geometry=True)

    def test_preservation_setting_requires_real_boolean(self):
        for value in (1, 'true', None):
            with self.assertRaises(ReferenceDataError):
                parse_dig(DUPLICATED, 'plate', preserve_source_geometry=value)

    def test_pickled_source_preserves_raw_geometry_and_view_policy(self):
        curve = parse_dig(OPEN, 'orogen', preserve_source_geometry=True)[0]
        restored = pickle.loads(pickle.dumps(curve))
        self.assertEqual(restored, curve)
        with self.assertRaises(ReferenceDataError):
            restored.measurement_coordinates()


class CompleteOfflineSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The complete distribution carries these exact attributed raw originals.
        # Missing files fail; there is no skip or automatic network acquisition.
        cls.dataset = load_pb2002(DATA)
        cls.report = reference_dataset_report(cls.dataset)

    def test_every_original_passes_unchanged_byte_identity(self):
        self.assertEqual(len(self.dataset.raw_sha256), 8)
        for name, _, count in PB2002_FILES:
            raw = (DATA/name).read_bytes()
            self.assertEqual(len(raw), count)
            self.assertEqual(verify_source_bytes(name, raw), dict(self.dataset.raw_sha256)[name])

    def test_all_original_record_counts_are_retained(self):
        d = self.dataset
        self.assertEqual(tuple(map(len, (d.plates,d.boundaries,d.orogens,d.poles,d.steps))), (52,229,13,52,5819))
        self.assertEqual(sum(p.count for p in d.plates), 12148)
        self.assertEqual(sum(b.count for b in d.boundaries), 6048)
        self.assertEqual(sum(len(p.repeated_vertex_indices) for p in d.plates), 452)

    def test_all_plates_and_steps_are_attempted(self):
        r = self.report
        self.assertTrue(r['full_dataset_tested'])
        self.assertTrue(r['reference_processing_completed'])
        self.assertEqual(r['measurement_coverage'], dict(plates_attempted=52, plates_measured=52,
            orogens_attempted=13, orogens_measured=12, boundary_segments_checked=229, motion_steps_checked=5819))

    def test_motion_and_source_order_checks_pass_without_relaxed_bounds(self):
        self.assertEqual(self.report['motion']['issues'], [])
        self.assertEqual(self.report['motion']['steps_checked'], 5819)
        self.assertEqual(self.report['source_step_alignment_issues'], [])

    def test_area_formula_agreement_does_not_erase_table_mismatch(self):
        for row in self.report['plates']:
            self.assertLessEqual(row['metrics']['area_formula_disagreement_sr'], row['area_formula_bound_sr'])
        row = next(r for r in self.report['plates'] if r['plate_id']=='ON')
        self.assertGreater(abs(row['area_difference_sr']), row['source_area_rounding_bound_sr'])
        self.assertIn('ON', [r['plate'] for r in self.report['numerical_issues']])

    def test_open_peru_outline_is_not_closed_or_omitted(self):
        row = next(r for r in self.report['orogens'] if r['name'].startswith('Peru '))
        self.assertEqual(row['status'], 'UNRESOLVED_SOURCE_GEOMETRY')
        self.assertIsNone(row['metrics'])
        source = next(c for c in self.dataset.orogens if c.name.startswith('Peru '))
        self.assertFalse(source.explicitly_closed)
        self.assertEqual(source.count, 49)

    def test_zero_length_repetitions_are_not_fake_boundary_edges(self):
        c = self.report['connectivity']
        self.assertEqual(c['exact_repeated_polygon_spans_excluded'], 452)
        self.assertTrue(all(r['edge'][0]!=r['edge'][1] for r in c['incidence_discrepancies']))

    def test_real_shared_edge_discrepancies_remain_visible(self):
        issues = self.report['connectivity']['incidence_discrepancies']
        self.assertEqual(len(issues), 5)
        self.assertEqual(sum(r['boundary_uses']==0 for r in issues), 3)
        self.assertEqual(sum(r['boundary_uses']==2 for r in issues), 2)
        self.assertTrue(all('polygon_owner_directions' in r for r in issues))

    def test_strict_gate_cannot_pass_when_source_issues_remain(self):
        self.assertEqual(self.report['status'], 'REFERENCE_DISCREPANCIES_REQUIRE_REVIEW')
        self.assertFalse(self.report['generated_planet_assessed'])
        self.assertFalse(self.report['geological_model_accepted'])

    def test_registered_protocol_and_evidence_split_unchanged(self):
        record = json.loads((ROOT/'cases/plate_reference_r1.json').read_text())
        self.assertEqual(reference_protocol(), record['protocol'])
        self.assertEqual(self.report['protocol'], record['protocol'])

    def test_altered_source_is_refused_before_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp)/'data'; shutil.copytree(DATA, copy)
            p = copy/'original/PB2002_plates.dig.txt'
            p.write_bytes(p.read_bytes().replace(b'AF',b'XX',1))
            with mock.patch('atlas_tectonics.plate_reference_dataset.parse_dig', side_effect=AssertionError('parsed bad bytes')):
                with self.assertRaises(ReferenceDataError):
                    load_pb2002(copy)

    def test_record_arrays_remain_unchanged_after_reporting(self):
        before = tuple(hashlib.sha256(c.coordinates.tobytes()).hexdigest()
                       for c in self.dataset.plates+self.dataset.orogens)
        reference_dataset_report(self.dataset, include_scales=False)
        after = tuple(hashlib.sha256(c.coordinates.tobytes()).hexdigest()
                      for c in self.dataset.plates+self.dataset.orogens)
        self.assertEqual(before, after)

    def test_report_budget_refusal_releases_reservation(self):
        budget = WorkBudget(1)
        with self.assertRaises(MemoryLimitError):
            reference_dataset_report(self.dataset, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_cancellation_does_not_become_unresolved_source_geometry(self):
        event = threading.Event(); event.set()
        with self.assertRaises(CancelledError):
            reference_dataset_report(self.dataset, cancel=event)

    def test_full_report_roundtrip_zstd_dedup_and_independent_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'report.db'; backup = Path(tmp)/'backup.db'
            with ArrayStore(path, StoreLimits(4096,1<<20,8<<20)) as store:
                key = write_report_snapshot(self.report, store)
                chunks = store.statistics()['unique_chunks']
                self.assertEqual(write_report_snapshot(self.report, store), key)
                self.assertEqual(store.statistics()['unique_chunks'], chunks)
                store.backup_to(backup)
            path.unlink()
            with ArrayStore(backup, StoreLimits(4096,1<<20,8<<20)) as store:
                self.assertEqual(read_report_snapshot(store,key), self.report)

    def test_cli_emits_complete_review_report_and_nonzero_gate(self):
        proc = subprocess.run([sys.executable,'-I','-B',str(ROOT/'tools/prepare_plate_reference.py'),
            '--verify-only','--data',str(DATA)], capture_output=True,text=True,timeout=45)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        record = json.loads(proc.stdout)
        self.assertEqual(record, self.report)
        self.assertNotIn('Traceback', proc.stderr)


class CheckoutPreflight(unittest.TestCase):
    def test_standalone_update_has_actionable_error_not_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = Path(tmp)/'tectonics/tools/prepare_plate_reference.py'
            tool.parent.mkdir(parents=True)
            shutil.copy2(ROOT/'tools/prepare_plate_reference.py', tool)
            proc = subprocess.run([sys.executable,'-I','-B',str(tool),'--verify-only'],
                capture_output=True,text=True,timeout=30)
            self.assertEqual(proc.returncode, 2)
            record = json.loads(proc.stderr)
            self.assertEqual(record['status'], 'BLOCKED_REFERENCE_ACCEPTANCE')
            self.assertIn('baseline',record['error'])
            self.assertNotIn('Traceback',proc.stderr)
            self.assertFalse(record['full_dataset_tested'])

    def test_local_bytecode_is_refused_before_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)/'tectonics'; shutil.copytree(ROOT/'tools',tree/'tools')
            package = tree/'src/atlas_tectonics'; package.mkdir(parents=True)
            for name in ('__init__.py','_validation.py','plate_reference_dataset.py',
                         'plate_reference_acceptance.py','geometry.py','resources.py'):
                (package/name).write_text('# source stub; must not be imported\n')
            (package/'stale.pyc').write_bytes(b'not trusted bytecode')
            proc = subprocess.run([sys.executable,'-I','-B',str(tree/'tools/prepare_plate_reference.py'),'--verify-only'],
                capture_output=True,text=True,timeout=30)
            self.assertEqual(proc.returncode, 2)
            self.assertIn('local bytecode',json.loads(proc.stderr)['error'])


if __name__=='__main__':
    unittest.main()
