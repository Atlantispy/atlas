"""Small actual ArrayStore persistence checks; no Atlas solve or old DB access."""
from concurrent.futures import CancelledError
from pathlib import Path
import sys
import tempfile
import threading
import unittest

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent / 'runtime-integration-r1'
HEAT = HERE.parents[2] / 'heat-repair-20261007'
sys.path[:0] = [str(RUNTIME / 'runtime-src'), str(RUNTIME / 'ram'),
               str(RUNTIME / 'helpers'), str(HEAT),
               str(HEAT / 'source' / 'tectonics' / 'tests')]

import numpy as np
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.storage import ArrayStore, StoreLimits, StoreError, _json
from integration_restart_catalog import RestartCatalog, RestartRefused


class RestartCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.execution = ExecutionContext()

    @classmethod
    def tearDownClass(cls):
        cls.execution.close()

    def setUp(self):
        # Keep SQLite paths short and inside the explicitly writable workspace;
        # Windows' redirected sandbox temp is not a reliable SQLite directory.
        self.directory = tempfile.TemporaryDirectory(prefix='.restart-fixture-',
                                                       dir=HERE.parents[3])
        self.path = Path(self.directory.name) / 'fixture.sqlite'
        self.budget = WorkBudget(64 * 1024**2)
        self.limits = StoreLimits(chunk_bytes=128, max_array_bytes=1024**2,
            max_store_bytes=8 * 1024**2, max_manifest_bytes=64 * 1024,
            verified_cache_entries=32, sqlite_cache_bytes=65536,
            codec_workspace_bytes=65536)
        self.store = ArrayStore(self.path, self.limits, budget=self.budget)
        self.catalog = RestartCatalog(self.store, self.execution, budget=self.budget)
        self.source = 'a' * 64
        self.contract = 'b' * 64
        self.arrays = {'enthalpy_j': np.arange(100, dtype=np.float64),
                       'strain_history': np.array([2., 3., 5.])}
        self.store.put(self.source, self.arrays,
                       {'schema': 'test.carried-state.v1', 'sequence': 1,
                        'producer': self.execution.provenance},
                       budget=self.budget)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def save(self, **changes):
        values = dict(scientific_contract_id=self.contract,
                      state_format='test.carried-state.v1', sequence=1,
                      time_s='1/4', stage='interval-published')
        values.update(changes)
        return self.catalog.publish(self.source, **values)

    def test_fresh_connection_streams_identical_arrays_without_copying_payload(self):
        before = self.store.statistics()['encoded_payload_bytes']
        key = self.save()
        # Only the one-byte marker is added; original physical chunks are reused.
        self.assertLess(self.store.statistics()['encoded_payload_bytes'] - before, 100)
        self.store.close()
        self.store = ArrayStore(self.path, self.limits, budget=self.budget)
        catalog = RestartCatalog(self.store, self.execution, budget=self.budget)
        with catalog.inspect(key, scientific_contract_id=self.contract) as view:
            self.assertFalse(view['may_advance'])
            self.assertEqual(view['status'], 'SAME_RUNTIME_STATE_VALIDATION_REQUIRED')
            self.assertEqual(view['record']['sequence'], 1)
            self.assertEqual(view['record']['time_s'], '1/4')
        for name, expected in self.arrays.items():
            pieces = [part for _, part in catalog.stream(key, name,
                                             scientific_contract_id=self.contract)]
            self.assertEqual(np.concatenate(pieces).tobytes(), expected.tobytes())

    def test_changed_science_and_parent_position_refuse(self):
        key = self.save()
        with self.assertRaises(RestartRefused):
            with self.catalog.inspect(key, scientific_contract_id='c' * 64):
                pass
        for changes in ({'scientific_contract_id': 'c' * 64}, {'sequence': 3},
                        {'sequence': 0}, {'state_format': 'different.v2'}):
            with self.assertRaises(RestartRefused):
                self.save(parent_reference=key, **changes)

    def test_different_producer_is_never_relabelled_or_admitted(self):
        original = self.execution.provenance
        old_producer = dict(original, execution_identity='c' * 64)
        self.source = 'd' * 64
        self.store.put(self.source, self.arrays,
            {'schema': 'test.carried-state.v1', 'producer': old_producer}, budget=self.budget)
        historical = self.save()
        with self.catalog.inspect(historical, scientific_contract_id=self.contract) as view:
            self.assertEqual(view['status'], 'COMPATIBILITY_VALIDATION_REQUIRED')
            self.assertFalse(view['may_advance'])
            self.assertEqual(view['record']['source_producer'], old_producer)
            self.assertEqual(view['record']['recorder'], original)
            self.assertEqual(view['reader'], original)

    def test_missing_legacy_producer_is_unknown_not_the_recorders_identity(self):
        self.source = 'd' * 64
        self.store.put(self.source, self.arrays,
                       {'schema': 'test.legacy-state.v1'}, budget=self.budget)
        key = self.save(state_format='test.legacy-state.v1')
        with self.catalog.inspect(key, scientific_contract_id=self.contract) as view:
            self.assertIsNone(view['record']['source_producer'])
            self.assertEqual(view['status'], 'HISTORICAL_PRODUCER_VALIDATION_REQUIRED')
            self.assertFalse(view['may_advance'])

    def test_cancelled_publish_creates_no_checkpoint(self):
        before = self.store.statistics()['snapshots']
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(CancelledError):
            self.save(cancel=cancel)
        self.assertEqual(self.store.statistics()['snapshots'], before)

    def test_source_or_marker_corruption_refuses(self):
        key = self.save()
        # Deliberately damage an existing scientific chunk: ordinary storage
        # validation, not a trusted outer metadata label, must detect it.
        manifest = self.catalog._manifest(self.source)
        chunk = manifest['arrays']['enthalpy_j']['chunks'][0]
        self.store._db.execute('UPDATE chunks SET payload=? WHERE id=?', (b'bad', chunk))
        with self.assertRaises(StoreError):
            list(self.catalog.stream(key, 'enthalpy_j', scientific_contract_id=self.contract))

    def test_reference_manifest_tamper_refuses(self):
        key = self.save()
        manifest = self.catalog._manifest(key)
        manifest['metadata']['stage'] = 'heat-complete'
        raw = _json(manifest)
        import hashlib
        self.store._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?',
                              (raw, hashlib.sha256(raw).hexdigest(), key))
        with self.assertRaises(RestartRefused):
            with self.catalog.inspect(key, scientific_contract_id=self.contract):
                pass

    def test_late_publication_failure_is_atomic(self):
        before = self.store.statistics()['snapshots']
        original = self.catalog._source

        def changed(_):
            raise RestartRefused('source changed before publication')

        self.catalog._source = changed
        try:
            with self.assertRaisesRegex(RestartRefused, 'source changed'):
                self.save()
        finally:
            self.catalog._source = original
        self.assertEqual(self.store.statistics()['snapshots'], before)

    def test_duplicate_publication_is_idempotent_and_unknown_stage_refuses(self):
        key = self.save()
        count = self.store.statistics()['snapshots']
        self.assertEqual(self.save(), key)
        self.assertEqual(self.store.statistics()['snapshots'], count)
        with self.assertRaises(RestartRefused):
            self.save(stage='unvalidated-accepted')
        with self.assertRaises(RestartRefused):
            self.catalog.publish(key, scientific_contract_id=self.contract,
                state_format='test.carried-state.v1', sequence=1,
                time_s='1/4', stage='interval-published')


if __name__ == '__main__':
    unittest.main()
