"""Actual routed native supports over generic partition refs; no solve/migration."""
from copy import deepcopy
import gc
import gzip
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_partition_routing_runtime as F

setUpModule = F.setUpModule
tearDownModule = F.tearDownModule


class PartitionV2Consumers(unittest.TestCase):
    def prepared(self):
        from content_cache import create_retained_scope
        import partition_tables as P
        budget = F.T.WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='wp4-consumers')
        body, supports = F.T.tiny_partition(budget)
        operands = F.source_operands(body, budget)
        view = P.pack_partition_v2(body, iter(supports),
            expected_partition_id=F.D._record_hash(body), scope=scope)
        return budget, scope, body, supports, operands, view

    def test_trace_stream_preserves_body_and_support_bytes_without_export(self):
        from record_views import RecordRef
        budget, scope, body, supports, operands, view = self.prepared()
        native = F.D.DifferentialPartition.from_compact(view, *operands, budget=budget)
        volume_map = SimpleNamespace(_record=b'{"cells":[1]}', record=lambda: {'cells': [1]})
        arguments = {'fixture': 'v2 trace stream'}
        with tempfile.TemporaryDirectory(prefix='wp4-trace-', dir=F.HERE.parents[4]/'_t') as directory:
            with patch.dict(os.environ, {'ATLAS_FOCUSED_ARTIFACT_DIR': directory}), \
                    patch.object(RecordRef, 'export', side_effect=AssertionError('trace export')):
                F.RP.retain_compact_trace(1, native, volume_map, arguments, budget,
                                         name='v2', scope='synthetic')
            raw = gzip.decompress((Path(directory)/'v2-01.json.gz').read_bytes())
        expected = dict(arguments=arguments, partition=body, scope='synthetic',
                        supports=supports, volume_map=volume_map.record())
        self.assertEqual(raw, json.dumps(expected, sort_keys=True, separators=(',', ':')).encode())
        del native, operands
        gc.collect(); view.close(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_routing_projection_transport_constraint_and_prepaid_diagnostic(self):
        from record_views import RecordRef
        budget, scope, body, supports, operands, view = self.prepared()
        native = F.D.DifferentialPartition.from_compact(view, *operands, budget=budget)
        legacy = F.D.DifferentialPartition.restore(dict(body, supports=supports,
            partition_id=view.partition_id), *operands, budget=budget)
        unbound = native.supports[0]
        unbound._compact_ref._partition = None
        with self.assertRaisesRegex(ValueError, 'inventory or budget differs'):
            F.RP.retain_support(unbound)
        del unbound
        expected = {}
        with F.RV.RoutingArena(budget) as arena:
            rows = F.RV.SupportRoutingRows(legacy.supports, budget, arena)
            for support in legacy.supports:
                expected[support.support_id] = deepcopy(rows.project(support))
        del rows, support, arena
        with F.RV.RoutingArena(budget) as arena:
            rows = F.RV.SupportRoutingRows(native.supports, budget, arena)
            for support in native.supports:
                projected = rows.project(support)
                old = expected[support.support_id]
                self.assertEqual({k: v for k, v in projected.items() if k != 'constraints'},
                                 {k: v for k, v in old.items() if k != 'constraints'})
                for name, ref in projected['constraints'].items():
                    self.assertIs(type(ref), RecordRef)
                    with F.RP.owned_constraint(ref) as held:
                        self.assertEqual(held.value, old['constraints'][name])
                handle = rows._handles[support.support_id]
                inputs = F.RP.InputMap(128 << 20, 1 << 30)
                inputs.add(support.support_id, handle)
                self.assertEqual(inputs[support.support_id], support._json)
                restored, held = F.RP.as_native_with_record(handle)
                self.assertEqual(restored._json, support._json)
                del restored, held, inputs
            del support, projected, ref, handle
            with budget.reserve(budget.available_bytes, category='test-filled-ledger'):
                with patch.object(F.RES, '_admit_budgets', side_effect=AssertionError('late admission')):
                    first = rows[view.support_id(0)]
                    self.assertEqual(dict(first), supports[0])
            del first
        del rows, arena, native, legacy, operands
        gc.collect(); view.close(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_persisted_diagnostic_refusal_preserves_primary_failure(self):
        from interval_store_set import IntervalStoreSet
        from partition_store import open_partition_v2, publish_partition_v2
        budget, scope, body, supports, operands, built = self.prepared()
        with tempfile.TemporaryDirectory(prefix='wp4-diagnostic-', dir=F.HERE.parents[4]/'_t') as directory:
            stores = IntervalStoreSet.create_migration(str(Path(directory)/'catalog.json'),
                workflow_id='a'*64, scope=scope)
            candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
            ref = publish_partition_v2(candidate, built, producer='d'*64)
            built.close()
            stores.promote(candidate.seal(ref), expected_catalog_digest=None)
            # A sealed synthetic segment exercises the actual persisted
            # reader; it carries no scientific acceptance claim.
            view = open_partition_v2(stores, ref, scope=scope)
            native = F.D.DifferentialPartition.from_compact(view, *operands, budget=budget)
            with F.RV.RoutingArena(budget) as arena:
                rows = F.RV.SupportRoutingRows(native.supports, budget, arena)
                for support in native.supports:
                    rows.project(support)
                del support
                measure = dict(kind='component-angular-face', support_id=view.support_id(0),
                    met=False, logical_cell_id='component', leaves=1)
                with patch.object(F.RES, '_admit_budgets', side_effect=AssertionError('late admission')):
                    error = F.ALE._unmet_measure_error(measure, rows, budget)
                self.assertIs(type(error), F.D.V.VolumeError)
                self.assertIn('declared width/leaf bound', str(error))
                capture = error.diagnostic_capture_failure
                self.assertFalse(capture['complete'])
                self.assertEqual(capture['exception_type'], 'RuntimeError')
                self.assertIn('pending WP16 compact replay adapter', str(capture))
                del error, capture
            del rows, arena, native, operands
            gc.collect(); view.close()
            candidate.close(); stores.close()
        gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
