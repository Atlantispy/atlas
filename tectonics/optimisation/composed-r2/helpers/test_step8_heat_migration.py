"""Synthetic private admission exercises conversion, not historical authority."""
from copy import deepcopy
import gc
from hashlib import sha256
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE/'compact-geometry-r1'),
               str(HERE.parent/'runtime-integration-r1/runtime-src'), str(HERE)]

import numpy as np
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.storage import ArrayStore, Compression
from compact_contracts import ContractError
from compact_restart_store import CompactRestartStore
from heat_ledger_tables import CompactHeatSnapshot
from interval_store_set import LIMITS
from record_tables import canonical
import historical_admission as H
import historical_compact_heat as MIGRATE
import private_heat_snapshot_store_r4 as S
import test_private_heat_snapshot_store_r4 as FIXTURE
import workflow_transfer as W


class HistoricalHeatMigration(unittest.TestCase):
    def setUp(self):
        FIXTURE.HeatStoreTests.setUp(self)
        self.store = CompactRestartStore(self.candidate, scope=self.scope)
        self.original_path = self.path/'original.sqlite'
        self.receipts = {}
        self.expected_fields = {}
        manifests = {}
        with ArrayStore(self.original_path, LIMITS, Compression(codec='raw'), budget=self.budget) as original:
            for index in range(2):
                data = dict(self.data, historical_interval=index)
                arrays = dict(self.arrays, interval=np.array([index], dtype=np.float64))
                legacy = RegionalMechanicalSnapshot(data, arrays)
                snapshot = CompactHeatSnapshot.from_components(data, arrays, scope=self.scope)
                meta = dict(schema=S.LEGACY_SCHEMA, **S._logical(snapshot, self.bindings))
                invocation = sha256(canonical(meta)).hexdigest()
                self.receipts[invocation] = dict(invocation=invocation, metadata=meta)
                fields = {'metadata_utf8': np.frombuffer(legacy._metadata, dtype=np.uint8)}
                fields.update({row['array']: arrays[row['name']] for row in meta['fields']})
                original.put(invocation, fields, meta, budget=self.budget)
                manifests[invocation] = original._manifest(invocation)
                self.expected_fields[invocation] = {name: value.tobytes() for name, value in arrays.items()}
                snapshot.close()
        self.original_hash = sha256(self.original_path.read_bytes()).hexdigest()
        self.original = H.open_successor_readonly(self.original_path, expected_sha256=self.original_hash,
            limits=LIMITS, compression=Compression(codec='raw'), budget=self.budget)
        capsule = dict(source=dict(head_key='9'*64), snapshot_manifests=manifests)
        self.admission = object.__new__(W.HistoricalEndpointAdmission)
        object.__setattr__(self.admission, '_record', W.canonical(capsule))
        object.__setattr__(self.admission, '_binding', W.canonical(dict(capsule_sha256=W.digest(capsule))))
        object.__setattr__(self.admission, '_source_audit', None)
        self.producer = {'role': 'synthetic authenticated-heat test'}

    def tearDown(self):
        self.original.close()
        self.assertEqual(sha256(self.original_path.read_bytes()).hexdigest(), self.original_hash)
        self.store.close()
        self.admission = None
        gc.collect()
        FIXTURE.HeatStoreTests.tearDown(self)

    def migrate(self, check=lambda: None):
        return MIGRATE.migrate_heat_history(self.original, self.store, self.admission,
            source_producer=self.producer, budget=self.budget, check=check)

    def seal(self, row):
        self.store.seal_and_promote(W.digest(row['binding']))
        self.assertTrue(self.store.readonly)

    def test_all_original_receipts_exact_and_readonly_replay_does_not_read_legacy(self):
        with patch.object(ArrayStore, 'get', side_effect=AssertionError('whole original get')):
            row = self.migrate()
        self.assertEqual(set(row['receipts']), set(self.receipts))
        for invocation, legacy in self.receipts.items():
            compact = row['receipts'][invocation]
            self.assertTrue(all(compact['metadata'][name] == legacy['metadata'][name] for name in S.LOGICAL_KEYS))
        self.seal(row)
        token = self.store.change_token()
        with (patch.object(H, 'read_selected_arrays', side_effect=AssertionError('legacy reread')),
              patch.object(CompactHeatSnapshot, 'from_components', side_effect=AssertionError('reconversion'))):
            self.assertEqual(self.migrate(), row)
        self.assertEqual(self.store.change_token(), token)
        for invocation, legacy in self.receipts.items():
            for receipt in (legacy, row['receipts'][invocation]):
                with S.open(self.store, receipt, expected_result_id=legacy['metadata']['result_id'],
                            bindings=self.bindings, scope=self.scope) as owned:
                    actual = owned.value
                    for name, raw in self.expected_fields[invocation].items():
                        self.assertEqual(actual.array(name).tobytes(), raw)
                    actual.close()
                del actual

    def test_incomplete_or_corrupt_saved_mapping_refuses(self):
        row = self.migrate()
        self.seal(row)
        key = W.digest(row['binding'])
        first = next(iter(self.receipts))
        def corrupt_record(value):
            receipt = value['receipts'][first]
            receipt['metadata']['ledger']['merkle_root'] = '0'*64
            receipt['invocation'] = sha256(canonical(receipt['metadata'])).hexdigest()
        cases = (
            lambda value: value['receipts'].pop(first),
            lambda value: value.update(source_manifest_sha256='0'*64),
            lambda value: value['binding'].update(head_key='0'*64),
            corrupt_record)
        metadata = self.store.metadata
        for mutate in cases:
            bad = deepcopy(row)
            mutate(bad)
            with self.subTest(mutation=mutate), patch.object(self.store, 'metadata',
                    side_effect=lambda invocation: bad if invocation == key else metadata(invocation)), \
                    patch.object(H, 'read_selected_arrays', side_effect=AssertionError('legacy fallback')):
                with self.assertRaises((H.HistoricalAdmissionRefused, ContractError)):
                    self.migrate()
        self.assertEqual(self.store.metadata(key), row)

    def test_readonly_missing_inventory_refuses_without_legacy_read(self):
        self.store.put('7'*64, {'empty': np.empty(0, dtype=np.uint8)}, {'synthetic': True})
        self.store.seal_and_promote('7'*64)
        with patch.object(H, 'read_selected_arrays', side_effect=AssertionError('legacy fallback')):
            with self.assertRaisesRegex(H.HistoricalAdmissionRefused, 'missing compact heat migration'):
                self.migrate()

    def test_cancelled_conversion_publishes_no_inventory(self):
        def cancel():
            raise InterruptedError('synthetic cancellation')
        with self.assertRaisesRegex(InterruptedError, 'synthetic cancellation'):
            self.migrate(cancel)
        self.assertEqual(list(self.store.snapshot_keys()), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
