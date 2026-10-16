"""Actual tiny migrated spatial owners; synthetic archive, no physical run."""
from copy import deepcopy
from dataclasses import replace
import gc
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import spatial_indexed_patch as X
import spatial_transfer as S
import test_spatial_transfer as T


def setUpModule():
    original = S.spatial_owner_source
    with patch.object(S, 'spatial_owner_source', side_effect=lambda text: X.transform(original(text))):
        T.setUpModule()


def tearDownModule():
    T.tearDownModule()


class IndexedSpatialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T.SpatialTransferTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        T.SpatialTransferTests.tearDownClass.__func__(cls)
        cls.collar = cls.native = None
        gc.collect()
        if cls.budget.reserved_bytes:
            raise AssertionError(cls.budget.statistics())

    def setUp(self):
        T.SpatialTransferTests.setUp(self)
        import mesh_tables as M
        from test_mesh_tables import small_mesh_record
        from compact_store import CompactMeshStore, descriptor_digest
        from atlas_tectonics.storage import ArrayStore, StoreLimits
        self.M = M
        saved = self.args['historical_spatial_record']
        mesh = small_mesh_record(self.budget)
        mesh.update(funding_id=saved['funding_id'], source=self.args['funding_record']['source'],
            grid_id=saved['grid_id'], support_id=saved['support_id'], time_s=T.enc(saved['time_s']),
            trajectory_id=saved['trajectory_id'], trajectory_segments=saved['trajectory']['segments'])
        for geometric, stock in zip(mesh['cells'], saved['cells'], strict=True):
            geometric['kind'] = 'exterior'
            stock['cell_id'] = geometric['logical_cell_id']
        saved['thermal_mesh'], saved['thermal_mesh_id'] = mesh, M.digest(mesh)
        saved['state_id'] = S._snapshot_id({k: v for k, v in saved.items() if k != 'state_id'},
                                          S._bindings(self.args['spatial_arrays']))
        self.saved = deepcopy(saved)
        self.temporary = tempfile.TemporaryDirectory(prefix='indexed-spatial-', dir=HERE)
        self.store = ArrayStore(Path(self.temporary.name)/'tiny.sqlite', StoreLimits(
            chunk_bytes=256, max_array_bytes=2 << 20, max_store_bytes=16 << 20,
            max_manifest_bytes=256 << 10, sqlite_cache_bytes=65536,
            codec_workspace_bytes=65536), budget=self.budget)
        adapter = CompactMeshStore(self.store, budget=self.budget)
        metadata, arrays = M.pack_mesh(mesh, support_writer=adapter.support_writer, budget=self.budget)
        self.key = adapter.publish(metadata, arrays, expected_geometry_id=saved['thermal_mesh_id'],
            source_producer={'fixture': 'synthetic tiny native spatial owner',
                             'runtime_source_sha256': sha256(Path(T.P.__file__).read_bytes()).hexdigest()})
        self.view = adapter.open(self.key, expected_geometry_id=saved['thermal_mesh_id'])
        manifest, record = adapter._root(self.key)
        self.reference = dict(schema=record['schema'], snapshot_key=self.key, geometry_id=self.view.geometry_id,
                              source_producer=record['source_producer'],
                              array_bindings={n: descriptor_digest(r) for n, r in manifest['arrays'].items()})
        self.args['historical_spatial_record'] = dict(saved, thermal_mesh=self.view)

    def tearDown(self):
        self.saved = self.view = self.reference = None
        self.store.close()
        self.store = None
        self.temporary.cleanup()
        T.SpatialTransferTests.tearDown(self)

    def adopt(self, **arguments):
        with T.P.PreparedSpatialOwner.from_migrated_checkpoint(**dict(self.args, **arguments)) as lease:
            return lease.adopt()

    def test_actual_owner_exact_logical_identity_fields_history_and_indexed_parent(self):
        with patch.object(self.M.CompactMesh, 'legacy_record', side_effect=AssertionError('full mesh forbidden')):
            current = self.adopt()
            original = self.adopt(historical_spatial_record=self.saved)
            self.assertIs(type(current.owner), T.P.PreparedSpatialOwner)
            self.assertIs(type(current.state), T.P.SpatialExteriorState)
            self.assertEqual(current.state.state_id, original.state.state_id)
            self.assertEqual(current.funding.funding_id, original.funding.funding_id)
            self.assertEqual(current.funding.descriptor(), self.args['funding_record'])
            with self.assertRaisesRegex(X.IndexedSpatialRefused, 'explicit indexed_record'):
                current.state.record()
            owned = current.state.indexed_record()
            record = owned.value
            self.assertIs(record['thermal_mesh'], self.view)
            self.assertEqual(record['finite_stock_state'], self.saved['finite_stock_state'])
            self.assertEqual(record['intervals'], 3)
            self.assertEqual(record['parent_state_id'], self.saved['state_id'])
            self.assertEqual(record['collar_state_id'], self.native_owned.state.result_id)
            for name, values in self.args['spatial_arrays'].items():
                np.testing.assert_array_equal(current.state.arrays()[name], values)
            self.assertEqual(X.snapshot_identity(current.state._snapshot), original.state.state_id)
            self.assertLess(len(current.state._snapshot._metadata), len(original.state._snapshot._metadata))
            self.assertNotIn('thermal_mesh', json.loads(current.state._snapshot._metadata))
            self.assertEqual(current.state.time_s, 12.5)
            current.owner.validate_parent(current.state, self.native_owned.state)
            S.validate_current_parent(current.owner, self.native_owned.state, current.state)
            self.assertEqual(self.native.statistics()['accepted_intervals'], 0)
            current.owner.close(); original.owner.close()
            del owned, record, current, original

    def test_compact_envelope_reopen_and_original_scientific_refusals(self):
        current = self.adopt()
        owned = current.state.compact_record(mesh_reference=self.reference)
        envelope = owned.value
        self.assertEqual(set(envelope), {'schema', 'state_id', 'state', 'mesh_reference', 'logical_metadata'})
        self.assertNotIn('thermal_mesh', envelope['state'])
        self.assertEqual(json.loads(S.N._json(envelope)), envelope)
        arrays = current.state.arrays()
        restored = current.owner.restore_compact(envelope, arrays, compact_mesh=self.view,
                                                expected_mesh_reference=self.reference)
        self.assertEqual(restored.state_id, current.state.state_id)
        del restored
        for field, value, message in (
                ('support_id', 'f'*64, 'geometry/time/trajectory'),
                ('trajectory_id', 'f'*64, 'geometry/time/trajectory'),
                ('funding_id', 'f'*64, 'source/owner/field'),
                ('grid_id', 'f'*64, 'source/owner/field')):
            changed = deepcopy(envelope)
            changed['state'][field] = value
            body = dict(changed['state'], thermal_mesh=self.view)
            changed['logical_metadata'] = S._stream_stats(body)[0]
            changed['state_id'] = S._snapshot_id(body, S._bindings(arrays))
            with self.subTest(field=field), self.assertRaisesRegex(T.TectonicsError, message):
                current.owner.restore_compact(changed, arrays, compact_mesh=self.view,
                                             expected_mesh_reference=self.reference)
        changed = deepcopy(envelope)
        changed['mesh_reference']['snapshot_key'] = 'f'*64
        with self.assertRaisesRegex(X.IndexedSpatialRefused, 'externally expected'):
            current.owner.restore_compact(changed, arrays, compact_mesh=self.view,
                                         expected_mesh_reference=self.reference)
        changed_arrays = {k: v.copy() for k, v in arrays.items()}
        changed_arrays['volume_m3'][0] += 1
        with self.assertRaisesRegex(T.TectonicsError, 'projected arrays'):
            current.owner.restore_compact(envelope, changed_arrays, compact_mesh=self.view,
                                         expected_mesh_reference=self.reference)
        current.owner.close()
        del current, owned, envelope, arrays, changed, body, changed_arrays

    def test_indexed_owned_records_and_arrays_survive_state_release(self):
        before = self.budget.reserved_bytes
        current = self.adopt()
        row = current.state.indexed_record()
        escaped = current.state.arrays()['enthalpy_j']
        current.owner.close()
        del current
        gc.collect()
        self.assertGreater(self.budget.reserved_bytes, before)
        self.assertEqual(row.value['intervals'], 3)
        self.assertFalse(escaped.flags.writeable)
        del row, escaped
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)

    def test_identity_refuses_changed_bytes_and_failed_restore_keeps_traceback_funded(self):
        current = self.adopt()
        snapshot = current.state._snapshot
        forged = replace(snapshot, result_id='f'*64)
        with self.assertRaisesRegex(X.IndexedSpatialRefused, 'complete snapshot identity'):
            X.snapshot_identity(forged)
        fields = list(snapshot._fields)
        name, shape, raw = fields[0]
        fields[0] = name, shape, bytes(raw)
        forged = replace(snapshot, _fields=tuple(fields))
        with self.assertRaisesRegex(X.IndexedSpatialRefused, 'ownership'):
            X.snapshot_identity(forged)
        wire = current.state.compact_record(mesh_reference=self.reference)
        changed = deepcopy(wire.value)
        changed['state']['cells'][0]['volume_m3'] = T.enc(0)
        body = dict(changed['state'], thermal_mesh=self.view)
        changed['logical_metadata'] = S._stream_stats(body)[0]
        changed['state_id'] = S._snapshot_id(body, S._bindings(current.state.arrays()))
        before = self.budget.reserved_bytes
        held = None
        try:
            current.owner.restore_compact(changed, current.state.arrays(), compact_mesh=self.view,
                                          expected_mesh_reference=self.reference)
        except T.TectonicsError as failure:
            self.assertIn('positive-cell layout', str(failure))
            held = failure.__traceback__
            failure.__traceback__ = None
        self.assertIsNotNone(held)
        gc.collect()
        self.assertGreater(self.budget.statistics()['categories']['indexed-spatial-restore'], 0)
        self.assertGreater(self.budget.reserved_bytes, before)
        del held
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)
        current.owner.close()
        del current, snapshot, forged, fields, raw, wire, changed, body

    def test_verified_identity_is_sealed_per_object_and_process(self):
        """Audit X2: one complete check per snapshot object in this process, then the binding only."""
        current = self.adopt()
        snapshot = current.state._snapshot
        object.__setattr__(snapshot, '_verified', None)    # start from an unsealed object
        identity = X.snapshot_identity(snapshot)
        self.assertEqual(identity, snapshot.result_id)
        self.assertEqual(snapshot._verified[0], identity)
        # Sealed: the complete logical stream is not repeated.
        with patch.object(X, 'iter_logical_json', side_effect=AssertionError('second full stream')):
            self.assertEqual(X.snapshot_identity(snapshot), identity)
            # The mesh's own liveness/freshness check still runs on every sealed call.
            with patch.object(self.M.CompactMesh, 'identity', side_effect=RuntimeError('mesh closed')), \
                    self.assertRaisesRegex(RuntimeError, 'mesh closed'):
                X.snapshot_identity(snapshot)
        # A copy never inherits the seal: dataclasses.replace starts it unsealed.
        copy = replace(snapshot)
        self.assertIsNone(copy._verified)
        with patch.object(X, 'iter_logical_json', side_effect=AssertionError('copy streamed')), \
                self.assertRaisesRegex(AssertionError, 'copy streamed'):
            X.snapshot_identity(copy)
        self.assertEqual(X.snapshot_identity(copy), identity)
        # A forged binding on the sealed object itself falls back to the full check.
        forged = replace(snapshot, result_id='f'*64)
        object.__setattr__(forged, '_verified', snapshot._verified)
        with self.assertRaisesRegex(X.IndexedSpatialRefused, 'complete snapshot identity'):
            X.snapshot_identity(forged)
        fields = list(snapshot._fields)
        name, shape, raw = fields[0]
        fields[0] = name, shape, bytes(raw)
        unowned = replace(snapshot, _fields=tuple(fields))
        object.__setattr__(unowned, '_verified', snapshot._verified)
        with self.assertRaisesRegex(X.IndexedSpatialRefused, 'ownership'):
            X.snapshot_identity(unowned)
        # Equality and hashing ignore the seal.
        self.assertEqual(copy, snapshot)
        current.owner.close()
        del current, snapshot, copy, forged, unowned, fields, raw

    def test_transform_is_single_application_and_legacy_identity_stays_explicit(self):
        source = (T.TN.BASE/'integration_spatial_owner.py').read_text(encoding='utf8')
        candidate = X.transform(S.spatial_owner_source(source))
        compile(candidate, '<indexed-spatial>', 'exec')
        with self.assertRaises(X.IndexedSpatialRefused):
            X.transform(candidate)
        sentinel = object()
        self.assertEqual(X.snapshot_identity(sentinel, legacy_identity=lambda value: 'legacy'), 'legacy')


if __name__ == '__main__':
    unittest.main(verbosity=2)
