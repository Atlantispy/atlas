"""Real-limit compact heat publication, authenticated migration and reopen."""
from concurrent.futures import CancelledError
import gc
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
sys.path[:0] = [str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'), str(HERE.parent)]
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, Compression
from compact_contracts import ContractError, SegmentRef
from content_cache import create_retained_scope
from heat_ledger_tables import CompactHeatSnapshot
from interval_store_set import IntervalStoreSet, LIMITS
from record_tables import canonical
import private_heat_snapshot_store_r4 as S


class HeatStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='heat-r4-', dir=TASK/'_t')
        self.path = Path(self.temp.name)
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='heat-store')
        self.stores = IntervalStoreSet.create_migration(self.path/'catalog.json', workflow_id='a'*64, scope=self.scope)
        self.candidate = self.stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        self.data = {'cell_ids': ['d'*64], 'face_ids': ['e'*64], 'q': ['0x2', '0x4'], 'rows': [1, 2]}
        self.arrays = {'a': np.array([-0., 1.]), 'empty': np.empty(0)}
        self.snapshot = CompactHeatSnapshot.from_components(self.data, self.arrays, scope=self.scope)
        self.bindings = {'source': 'f'*64, 'call': '1'*64}

    def tearDown(self):
        self.snapshot.close()
        self.candidate.close()
        self.stores.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temp.cleanup()

    def save(self):
        return S.save(self.candidate, self.snapshot, bindings=self.bindings, scope=self.scope)

    def reopen(self, receipt, resolver=None):
        return S.open(resolver or self.candidate, receipt, expected_result_id=self.snapshot.result_id,
                      bindings=self.bindings, scope=self.scope)

    def test_roundtrip_idempotence_no_get_real_limits(self):
        with patch.object(ArrayStore, 'get', side_effect=AssertionError('whole store get')):
            receipt = self.save()
            before = self.candidate.local_statistics()
            self.assertEqual(receipt, self.save())
            self.assertEqual(before, self.candidate.local_statistics())
            with self.reopen(receipt) as result:
                restored = result.value
                self.assertEqual(restored.result_id, self.snapshot.result_id)
                self.assertEqual(restored.nbytes, self.snapshot.nbytes)
                self.assertEqual(restored.array('a').tobytes(), self.arrays['a'].tobytes())
                restored.close()
            del restored
        self.assertEqual(LIMITS.chunk_bytes, 65536)
        self.assertEqual(LIMITS.max_array_bytes, 512 << 20)
        self.assertEqual(LIMITS.max_store_bytes, 4 << 30)

    def test_receipt_mutation_and_external_binding_refused(self):
        receipt = self.save()
        bad = json.loads(json.dumps(receipt))
        bad['metadata']['metadata_bytes'] += 1
        with self.assertRaises(ContractError):
            self.reopen(bad)
        with self.assertRaisesRegex(ContractError, 'source/call'):
            S.open(self.candidate, receipt, expected_result_id=self.snapshot.result_id,
                   bindings={'source': '0'*64}, scope=self.scope)
        token = threading.Event()
        token.set()
        with self.assertRaises(CancelledError):
            S.open(self.candidate, receipt, expected_result_id=self.snapshot.result_id,
                   bindings=self.bindings, scope=self.scope, cancel=token)

    def test_historical_authenticated_lookup_and_sealed_reopen(self):
        legacy = RegionalMechanicalSnapshot(self.data, self.arrays)
        meta = dict(schema=S.LEGACY_SCHEMA, **S._logical(self.snapshot, self.bindings))
        receipt = dict(invocation=sha256(canonical(meta)).hexdigest(), metadata=meta)
        arrays = {'metadata_utf8': np.frombuffer(legacy._metadata, dtype=np.uint8)}
        arrays.update({row['array']: self.arrays[row['name']] for row in meta['fields']})
        with ArrayStore(self.path/'original.sqlite', LIMITS, Compression(codec='raw'), budget=self.budget) as store:
            store.put(receipt['invocation'], arrays, meta, budget=self.budget)
            original = (self.path/'original.sqlite').read_bytes()
            compact = S.register_legacy_lookup(self.candidate, store, receipt, self.snapshot,
                                               bindings=self.bindings, scope=self.scope)
            self.assertEqual((self.path/'original.sqlite').read_bytes(), original)
        sealed = self.candidate.seal(SegmentRef.from_wire(compact['metadata']['ledger']))
        self.stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
        for view in (receipt, compact):
            with self.reopen(view, resolver=self.stores) as result:
                self.assertEqual(result.value.result_id, legacy.result_id)
                result.value.close()

    def test_original_manifest_mismatch_refused(self):
        meta = dict(schema=S.LEGACY_SCHEMA, **S._logical(self.snapshot, self.bindings))
        receipt = dict(invocation=sha256(canonical(meta)).hexdigest(), metadata=meta)
        class Wrong:
            def metadata(self, key):
                return None
        with self.assertRaisesRegex(ContractError, 'original heat manifest'):
            S.register_legacy_lookup(self.candidate, Wrong(), receipt, self.snapshot,
                                     bindings=self.bindings, scope=self.scope)

    def test_historical_same_bytes_wrong_shape_refused(self):
        legacy = RegionalMechanicalSnapshot(self.data, self.arrays)
        meta = dict(schema=S.LEGACY_SCHEMA, **S._logical(self.snapshot, self.bindings))
        receipt = dict(invocation=sha256(canonical(meta)).hexdigest(), metadata=meta)
        arrays = {'metadata_utf8': np.frombuffer(legacy._metadata, dtype=np.uint8)}
        arrays.update({row['array']: self.arrays[row['name']] for row in meta['fields']})
        arrays['field_0'] = arrays['field_0'].reshape(2, 1)
        with ArrayStore(self.path/'wrong-shape.sqlite', LIMITS, Compression(codec='raw'), budget=self.budget) as store:
            store.put(receipt['invocation'], arrays, meta, budget=self.budget)
            with self.assertRaisesRegex(ContractError, 'shape/dtype'):
                S.register_legacy_lookup(self.candidate, store, receipt, self.snapshot,
                                         bindings=self.bindings, scope=self.scope)

    def test_foreign_producer_graft_and_oversized_envelope_refused(self):
        foreign = S.save(self.candidate, self.snapshot, bindings={'source': '0'*64}, scope=self.scope)
        foreign['metadata']['bindings'] = self.bindings
        foreign['invocation'] = sha256(canonical(foreign['metadata'])).hexdigest()
        with self.assertRaisesRegex(ContractError, 'producer'):
            self.reopen(foreign)
        bad = self.save()
        bad['metadata']['fields'] = [None]*10000
        with patch.object(S, 'canonical', side_effect=AssertionError('unbounded envelope encoded')):
            with self.assertRaisesRegex(ContractError, 'inventory'):
                self.reopen(bad)

    def test_mesh_id_columns_shared_ordered_and_reopened(self):
        from compact_store import CompactMeshStoreV3
        from test_mesh_v3 import fixture
        old, _, source, partition, _ = fixture(self.scope, self.candidate)
        adapter = CompactMeshStoreV3(self.candidate, scope=self.scope, support_source=source)
        mesh_ref = adapter.publish(old, producer='b'*64)
        mesh = adapter.open(mesh_ref, expected_geometry_id=old.geometry_id)
        data = dict(cell_ids=[mesh.cell_id(i) for i in range(mesh.cell_count)],
                    face_ids=[mesh.face_id(i) for i in range(mesh.face_count)],
                    caller_snapshot={'cell_ids': [mesh.cell_id(i) for i in range(mesh.cell_count)]},
                    exact=['0x2', '0x4'])
        snapshot = CompactHeatSnapshot.from_components(data, self.arrays, scope=self.scope, mesh=mesh)
        expected = RegionalMechanicalSnapshot(data, self.arrays)
        self.assertEqual(snapshot.result_id, expected.result_id)
        with snapshot.record.root() as compact:
            with self.assertRaises(KeyError):
                compact.field('cell_ids')
        with snapshot.field('cell_ids') as ids:
            self.assertEqual(ids.value, data['cell_ids'])
        with snapshot.ledger as ledger, ledger.field('cell_ids') as ids:
            actual = []
            with ids.iter_rows(max_rows=1, max_owned_bytes=32768) as rows:
                for group in rows:
                    with group:
                        for item in group.value:
                            with item, item.export(max_logical_bytes=128, max_owned_bytes=131072) as value:
                                actual.append(value.value)
            self.assertEqual(actual, data['cell_ids'])
            self.assertEqual(ids.identity().sha256, sha256(canonical(data['cell_ids'])).hexdigest())
            with self.assertRaises(ContractError):
                ids.export(max_logical_bytes=1, max_owned_bytes=131072)
        with self.assertRaises(RuntimeError):
            mesh.close()
        receipt = S.save(self.candidate, snapshot, bindings=self.bindings, scope=self.scope)
        self.assertEqual(receipt['metadata']['shared_mesh']['segment'], mesh_ref.to_wire())
        with S.open(self.candidate, receipt, expected_result_id=expected.result_id,
                    bindings=self.bindings, scope=self.scope, mesh=mesh) as owner:
            self.assertEqual(owner.value.result_id, expected.result_id)
            with owner.value.field('caller_snapshot') as caller:
                self.assertEqual(caller.value, data['caller_snapshot'])
            owner.value.close()
        with self.assertRaisesRegex(ContractError, 'shared mesh'):
            S.open(self.candidate, receipt, expected_result_id=expected.result_id,
                   bindings=self.bindings, scope=self.scope)
        bad = dict(data, cell_ids=list(reversed(data['cell_ids'])))
        if len(data['cell_ids']) > 1:
            with self.assertRaisesRegex(ContractError, 'order'):
                CompactHeatSnapshot.from_components(bad, self.arrays, scope=self.scope, mesh=mesh)
        snapshot.close(); mesh.close(); source.close(); partition.close()
        del old


if __name__ == '__main__':
    unittest.main()
