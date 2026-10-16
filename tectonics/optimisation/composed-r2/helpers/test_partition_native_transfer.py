"""Optional runtime geometry transfer in compact native partition admission.

Actual tiny native/collar/funding owners and the composed temporary package of
resumability-r1/test_geometry_transfer_compact (partition reader -> endpoint
seam -> geometry_transfer(compact=True)). Parent bodies are SYNTHETIC
native-schema fixtures, not historical-reader or scientific acceptance.
"""
from copy import deepcopy
import gc
from pathlib import Path
import sys
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # transfer modules and actual-owner fixtures

import geometry_transfer as G
import partition_native_patch as P
import test_geometry_transfer_compact as GC


# The selected header partition_native_patch leaves in prepare_interval_partition.
PREPARE_FIELDS = ('scope', 'network_id', 'endpoint_network_id', 'trajectory_id', 'funding_id', 'source',
                  'collar_plan_id', 'end_time_s', 'start_time_s', 'grid_lines')


def setUpModule():
    GC.install('pnt-')


def tearDownModule():
    GC.uninstall()


class NativeTransferAdmissionTests(GC.CompactParentFixture, unittest.TestCase):
    def test_current_collar_admission_never_consults_transfer(self):
        body = dict(deepcopy(self.body), collar_plan_id=self.collar.plan_id)
        view = GC.compact(body, self.supports, self.budget)
        consulted = AssertionError('current-plan parent consulted a geometry transfer')
        with mock.patch.object(G, 'collar_binding_matches_compact', side_effect=consulted), \
                mock.patch.object(G, 'collar_binding_matches', side_effect=consulted):
            for token in (None, object()):
                part = self.admit(view, token)
                self.assertIs(part.compact_view(), view)
                arguments, kind, message = self.prepare(part, token)
                self.assertIsNotNone(arguments, (kind, message))
                del part
        del view, token, arguments
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_historical_collar_requires_exact_compact_binding(self):
        view = GC.compact(self.body, self.supports, self.budget)
        self.assertNotEqual(self.body['collar_plan_id'], self.collar.plan_id)
        body_b, supports_b = GC.foreign_parent(self.body, self.supports)
        foreign = self.bind_dict(body_b, supports_b)
        for token in (None, object(), {self.body['collar_plan_id']: self.collar.plan_id}, foreign):
            with self.subTest(token=type(token).__name__):
                with self.assertRaises(GC.VolumeError):
                    self.admit(view, token)
        binding = self.bind(view)
        part = self.admit(view, binding)
        legacy = self.restore(binding)
        self.assertIs(type(part), GC.D.DifferentialPartition)
        self.assertIs(part.compact_view(), view)
        self.assertEqual(part.partition_id, view.partition_id)
        self.assertEqual(part.partition_id, legacy.partition_id)
        self.assertEqual(part.legacy_record().value, legacy.record())
        self.assertEqual(len(part.supports), len(legacy.supports))
        for compact, old in zip(part.supports, legacy.supports, strict=True):
            self.assertEqual(compact._json, old._json)
            self.assertEqual(compact.support_id, old.support_id)
            self.assertIs(compact._compact_ref._view, view)
        self.assertEqual(self.collar._native.statistics()['accepted_intervals'], 0)
        del view, foreign, token, binding, part, legacy, compact, old
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_prepare_interval_partition_compact_parent_with_transfer(self):
        view = GC.compact(self.body, self.supports, self.budget)
        binding = self.bind(view)
        part, legacy = self.admit(view, binding), self.restore(binding)
        # A2: the compact selected header is not the full parent body, so the
        # dict binding hash can never match it; the partition-aware seam can.
        header = P.partition_fields(part, PREPARE_FIELDS)
        self.assertEqual(sorted(header.value), sorted(PREPARE_FIELDS))
        operands = (self.funding, self.collar, self.budget, binding)
        self.assertFalse(GC.D._transferred_collar_binding(header.value, *operands))
        self.assertTrue(GC.D._transferred_partition_binding(part, header.value, *operands))
        full = P.partition_fields(legacy, PREPARE_FIELDS)
        self.assertTrue(GC.D._transferred_partition_binding(legacy, full.value, *operands))
        del header, full
        compact_result, legacy_result = self.prepare(part, binding), self.prepare(legacy, binding)
        self.assertIsNotNone(compact_result[0], compact_result[1:])
        self.assertEqual(compact_result, legacy_result)
        self.assertEqual(compact_result[0][3], view.partition_id)
        body_b, supports_b = GC.foreign_parent(self.body, self.supports)
        foreign_view = GC.compact(body_b, supports_b, self.budget)
        foreign = self.bind(foreign_view)
        for token in (None, object(), foreign, self.bind_dict(body_b, supports_b)):
            with self.subTest(token=type(token).__name__):
                for parent in (part, legacy):
                    arguments, kind, message = self.prepare(parent, token)
                    self.assertIsNone(arguments)
                    self.assertIs(kind, GC.VolumeError)
                    self.assertIn('does not continue its actual accepted geometry', message)
        del view, binding, part, legacy, foreign_view, foreign, token, parent, operands
        del compact_result, legacy_result
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)

    def test_held_admission_refusal_releases_without_new_reservation(self):
        view = GC.compact(self.body, self.supports, self.budget)
        body_b, supports_b = GC.foreign_parent(self.body, self.supports)
        foreign_view = GC.compact(body_b, supports_b, self.budget)
        foreign = self.bind(foreign_view)
        gc.collect()
        before = self.budget.reserved_bytes
        for token in (None, foreign):
            held = None
            try:
                self.admit(view, token)
            except GC.VolumeError as error:
                held = error
            with self.subTest(token=type(token).__name__):
                self.assertIsNotNone(held)
                gc.collect()
                # The held frame keeps its owned header row, never a wrapper lease.
                self.assertGreater(self.budget.reserved_bytes, before)
                categories = self.budget.statistics()['categories']
                self.assertEqual(categories.get('compact-partition-native-wrapper', 0), 0)
                held = None
                gc.collect()
                self.assertEqual(self.budget.reserved_bytes, before)
                self.assertEqual(self.budget.statistics()['categories'].get('geometry-transfer-match-scratch', 0), 0)
        del view, foreign_view, foreign, token
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)


if __name__ == '__main__':
    unittest.main(verbosity=2)
