"""Synthetic-only component fixtures at unchanged native store limits."""
from dataclasses import replace
import gc
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, Compression
from compact_contracts import (BINDING_INDEX_SCHEMA, SEGMENT_REF_SCHEMA,
                               BindingIndexRef, ContractError, LogicalIdentity,
                               SegmentRef, SnapshotLocator)
from content_cache import create_retained_scope
from interval_catalog import (Catalog, CatalogEntry, canonical, digest, publish_catalog,
                              publication_lock, read_catalog, relative_file, tagged)
from interval_store_set import (LIMITS, IntervalStoreSet, ReadOnlyNative, chunk_id,
                                seal_key)


WORKFLOW = 'a' * 64


def scope():
    return create_retained_scope(WorkBudget(512 << 20), process_epoch='interval-tests')


def add_interval(stores, raw_values, *, share=(), compression=None):
    candidate = stores.begin_interval(stores.head, producer_identity='b' * 64,
                                      runtime_identity='c' * 64)
    if compression is not None:
        candidate.compression = compression
    chunks = []
    for raw in (*share, *raw_values):
        desc = canonical({'dtype': '|u1', 'count': len(raw)})
        owner, key = candidate.put_chunk(desc, raw)
        chunks.append({'owner': owner, 'key': key, 'descriptor': desc.decode()})
    key = hashlib.sha256(f'root-{candidate.interval}'.encode()).hexdigest()
    locator = SnapshotLocator(WORKFLOW, candidate.interval, key)
    ref = SegmentRef(SEGMENT_REF_SCHEMA, locator,
                     LogicalIdentity('synthetic.component.v1', digest(canonical(chunks)), len(canonical(chunks))),
                     sum(len(raw) for raw in (*share, *raw_values)),
                     BindingIndexRef(BINDING_INDEX_SCHEMA, locator, 'd' * 64, len(chunks)),
                     'e' * 64)
    candidate.put_manifest(key, {'schema': 'atlas.segment-root.v1',
                                 'reference': ref.to_wire(), 'chunks': chunks})
    return candidate, ref, chunks


def finish(stores, candidate, ref):
    sealed = candidate.seal(ref)
    return stores.promote(sealed, expected_catalog_digest=stores.catalog_digest)


class IntervalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wp13-')
        self.root = Path(self.temp.name)
        self.sc = scope()
        self.scope_baseline = self.sc.stats().retained_bytes
        self.stores = IntervalStoreSet.create_migration(str(self.root / 'catalog.json'),
                                                       workflow_id=WORKFLOW, scope=self.sc)

    def tearDown(self):
        self.stores.close()
        gc.collect()
        self.sc.close()
        for path in self.root.rglob('*'):
            if path.is_file():
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        self.temp.cleanup()

    def root_interval(self):
        candidate, ref, chunks = add_interval(self.stores, [b'abc' * 50])
        entry = finish(self.stores, candidate, ref)
        return entry, ref, chunks

    def test_three_file_chain_shares_real_chunks_and_reopens_fresh(self):
        a, b, c = b'first' * 100, b'second' * 100, b'third' * 100
        for fresh, shared in (([a], ()), ([b], (a,)), ([c], (a, b))):
            candidate, ref, chunks = add_interval(self.stores, fresh, share=shared)
            self.assertEqual(candidate.local_statistics()['local_chunks'], 1)
            finish(self.stores, candidate, ref)
        self.assertEqual([row['owner'] for row in chunks], [0, 1, 2])
        self.assertEqual(self.stores.head.references,
                         tuple((i, self.stores._entries()[i].logical_seal) for i in (0, 1)))
        for i in range(3):
            self.assertTrue(self.stores.verify_file_sha256(i))
            db = sqlite3.connect(f'file:{self.root / f"interval-{i:04d}.sqlite"}?mode=ro', uri=True)
            self.assertEqual(db.execute('SELECT count(*) FROM chunks').fetchone()[0], 1)
            db.close()
        self.stores.close()
        self.stores = IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        self.assertEqual(self.stores.opened_intervals, [2])
        with self.stores.resolve_chunk(2, 0, chunks[0]['key'], chunks[0]['descriptor'].encode()) as found:
            self.assertEqual(found.value, a)
        self.assertEqual(self.stores.opened_intervals, [2, 0])
        self.stores.close()
        code = """
import json,sys
from test_interval_store_set import scope
from interval_store_set import IntervalStoreSet
s=scope(); stores=IntervalStoreSet.open_catalog(sys.argv[1],scope=s)
with stores.resolve_manifest(2,stores.head.head.root_key) as m: chunks=json.loads(m.value)['metadata']['chunks']
for row in chunks:
 with stores.resolve_chunk(2,row['owner'],row['key'],row['descriptor'].encode()) as owned:
  assert len(owned.value)>0
for i in range(3): assert stores.verify_file_sha256(i)
stores.close();s.close(); print('fresh-reader-pass')
"""
        result = subprocess.run([sys.executable, '-B', '-c', code, str(self.root / 'catalog.json')],
                                capture_output=True, text=True, env=os.environ.copy(), check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('fresh-reader-pass', result.stdout)

    def test_reader_never_invokes_native_writer_constructor(self):
        entry, ref, _ = self.root_interval()
        self.stores.close()
        before = (self.root / entry.filename).read_bytes()
        with patch.object(ArrayStore, '__init__', side_effect=AssertionError('writer constructor')):
            self.stores = IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
            with self.stores.resolve_manifest(0, ref.root_key):
                pass
            with self.assertRaises(sqlite3.OperationalError):
                self.stores._handle(0).value._db.execute('DELETE FROM snapshots')
            self.assertFalse(self.stores._handle(0).value._db.in_transaction)
        self.assertEqual(before, (self.root / entry.filename).read_bytes())
        self.assertFalse(any(self.root.glob('*-journal')))

    def test_seal_is_final_file_hash_and_no_later_writer(self):
        candidate, ref, _ = add_interval(self.stores, [b'x' * 1000])
        sealed = candidate.seal(ref)
        self.assertEqual(sealed.entry.file_sha256, digest(candidate.path.read_bytes()))
        with self.assertRaises(ContractError):
            candidate.put_chunk(canonical({'dtype': '|u1', 'count': 1}), b'y')
        self.stores.promote(sealed, expected_catalog_digest=None)
        self.assertEqual(sealed.entry.file_sha256, digest(candidate.path.read_bytes()))

    def test_native_single_file_arrays_still_compatible(self):
        path = self.root / 'ordinary.sqlite'
        a = np.arange(100, dtype='<i8')
        with ArrayStore(path, LIMITS, Compression(codec='raw'), budget=self.sc.run_budget) as store:
            key = 'f' * 64
            store.put(key, {'a': a}, {'schema': 'old-synthetic'})
            np.testing.assert_array_equal(store.get(key)['a'], a)
        os.chmod(path, stat.S_IREAD)
        reader = ReadOnlyNative(path, scope=self.sc)
        try:
            body = json.loads(reader.manifest(key))
            desc = canonical({'dtype': '<i8', 'count': len(a)})
            self.assertEqual(reader.chunk(body['arrays']['a']['chunks'][0], desc), a.tobytes())
        finally:
            reader.close()

    def test_manifest_only_open_does_not_decode_payload(self):
        self.root_interval()
        self.stores.close()
        with patch.object(ArrayStore, '_decode', side_effect=AssertionError('payload touched')):
            self.stores = IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
            with self.stores.resolve_manifest(0, self.stores.head.head.root_key):
                pass

    def test_unlisted_and_future_foreign_requests_refuse(self):
        self.root_interval()
        candidate, ref, _ = add_interval(self.stores, [b'new'])
        with self.assertRaises(ContractError):
            self.stores.resolve_manifest(1, ref.root_key)
        with self.assertRaises(ContractError):
            self.stores.resolve_manifest(0, ref.root_key)
        with self.assertRaises(ContractError):
            self.stores.resolve_manifest(0, SnapshotLocator('f' * 64, 0, ref.root_key.snapshot_key))
        candidate.close()

    def test_orphan_and_bootstrap_collisions_refuse(self):
        candidate, ref, _ = add_interval(self.stores, [b'x'])
        candidate.seal(ref)
        candidate.close()
        with self.assertRaises(FileExistsError):
            self.stores.begin_interval(None, producer_identity='b' * 64, runtime_identity='c' * 64)
        with self.assertRaises(ContractError):
            IntervalStoreSet.open_catalog(str(self.root / 'missing.json'), scope=self.sc)

    def test_catalog_cas_keeps_previous_head(self):
        self.root_interval()
        previous = (self.root / 'catalog.json').read_bytes()
        candidate, ref, _ = add_interval(self.stores, [b'x'])
        sealed = candidate.seal(ref)
        with self.assertRaises(ContractError):
            self.stores.promote(sealed, expected_catalog_digest='0' * 64)
        self.assertEqual(previous, (self.root / 'catalog.json').read_bytes())

    def test_handle_pin_and_scope_lifetime(self):
        entry, _, chunks = self.root_interval()
        row = chunks[0]
        value = self.stores.resolve_chunk(0, 0, row['key'], row['descriptor'].encode())
        before = self.sc.stats().retained_bytes
        retained = value.retain()
        self.assertGreater(self.sc.stats().retained_bytes, before)
        with self.assertRaises((ValueError, RuntimeError)):
            self.stores.close()
        with self.assertRaises((ValueError, RuntimeError)):
            value.close()
        retained.close()
        value.close()
        self.stores.close()
        self.assertEqual(self.sc.stats().retained_bytes, self.scope_baseline)

    def test_eight_handles_lru_and_all_pinned_refusal(self):
        for i in range(9):
            candidate, ref, _ = add_interval(self.stores, [bytes([i + 1]) * 20])
            finish(self.stores, candidate, ref)
        pins = [self.stores.borrow_handle(i) for i in range(8)]
        self.assertEqual(len(self.stores._handles), 8)
        with self.assertRaisesRegex(ContractError, 'pinned'):
            self.stores.borrow_handle(8)
        pins[0].close()
        last = self.stores.borrow_handle(8)
        self.assertNotIn(0, self.stores._handles)
        last.close()
        for pin in pins[1:]:
            pin.close()

    def test_cancellation_poison_prevents_later_seal(self):
        candidate, ref, _ = add_interval(self.stores, [b'x'])
        token = threading.Event()
        token.set()
        with self.assertRaises(InterruptedError):
            candidate.put_chunk(canonical({'dtype': '|u1', 'count': 1}), b'x', cancel=token)
        with self.assertRaises(ContractError):
            candidate.seal(ref)
        self.assertFalse((self.root / 'catalog.json').exists())

    def test_same_snapshot_conflict_and_reserved_seal_refuse(self):
        candidate, _, _ = add_interval(self.stores, [b'x'])
        key = '1' * 64
        candidate.put_manifest(key, {'schema': 'fixture.v1'})
        with self.assertRaises(ContractError):
            candidate.put_manifest(key, {'schema': 'fixture.v2'})
        with self.assertRaises(ContractError):
            candidate.put_manifest(seal_key(WORKFLOW, 0), {'schema': 'fixture.v1'})

    def test_final_physical_hash_is_separate_from_manifest_seal(self):
        self.root_interval()
        path = self.root / 'catalog.json'
        self.stores.close()
        catalog, _ = read_catalog(path)
        changed = Catalog(WORKFLOW, 1, (replace(catalog.entries[0], file_sha256='0' * 64),))
        path.write_bytes(changed.to_bytes())
        self.stores = IntervalStoreSet.open_catalog(str(path), scope=self.sc)
        with self.assertRaisesRegex(ContractError, 'physical'):
            self.stores.verify_file_sha256(0)

    def test_payload_tamper_detected_only_when_read_or_full_hash_requested(self):
        entry, _, chunks = self.root_interval()
        self.stores.close()
        path = self.root / entry.filename
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        db = sqlite3.connect(path)
        db.execute('UPDATE chunks SET payload=?', (b'corrupt',))
        db.commit()
        db.close()
        os.chmod(path, stat.S_IREAD)
        self.stores = IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        row = chunks[0]
        with self.assertRaises(ContractError):
            self.stores.resolve_chunk(0, 0, row['key'], row['descriptor'].encode())
        with self.assertRaises(ContractError):
            self.stores.verify_file_sha256(0)

    def test_manifest_seal_and_changed_identity_detected(self):
        entry, ref, _ = self.root_interval()
        self.stores.close()
        path = self.root / entry.filename
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        db = sqlite3.connect(path)
        body = db.execute('SELECT body FROM snapshots WHERE id=?', (ref.root_key.snapshot_key,)).fetchone()[0]
        value = json.loads(body)
        value['metadata']['new'] = 'tampered'
        altered = canonical(value)
        db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?', (altered, digest(altered), ref.root_key.snapshot_key))
        db.commit()
        db.close()
        os.chmod(path, stat.S_IREAD)
        with self.assertRaises(ContractError):
            IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)

    def test_missing_dependency_and_unsafe_paths_refuse(self):
        self.root_interval()
        candidate, ref, _ = add_interval(self.stores, [b'next'], share=(b'abc' * 50,))
        finish(self.stores, candidate, ref)
        self.stores.close()
        first = self.root / 'interval-0000.sqlite'
        first.rename(self.root / 'preserved-root.sqlite')
        with self.assertRaises(ContractError):
            IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        for name in ('../escape.sqlite', 'C:/escape.sqlite', 'x/y.sqlite', 'CON.sqlite', 'x.sqlite:ads'):
            with self.assertRaises(ContractError):
                relative_file(self.root, name)

    def test_real_process_crash_at_each_publication_boundary(self):
        self.root_interval()
        original = (self.root / 'catalog.json').read_bytes()
        self.stores.close()
        code = """
import os,sys
from test_interval_store_set import scope,add_interval,finish
from interval_store_set import IntervalStoreSet
s=scope(); stores=IntervalStoreSet.open_catalog(sys.argv[1],scope=s)
stores.crash_hook=lambda phase: os._exit(72) if phase==sys.argv[2] else None
candidate,ref,_=add_interval(stores,[b'crash-successor'])
finish(stores,candidate,ref)
"""
        import shutil
        for phase in ('candidate_quiesced', 'seal_written', 'file_sealed', 'catalog_flushed', 'catalog_replaced'):
            with self.subTest(phase=phase):
                dest = self.root / phase
                dest.mkdir()
                shutil.copy2(self.root / 'interval-0000.sqlite', dest / 'interval-0000.sqlite')
                (dest / 'catalog.json').write_bytes(original)
                result = subprocess.run([sys.executable, '-B', '-c', code, str(dest / 'catalog.json'), phase],
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 72, result.stderr)
                recovered = IntervalStoreSet.open_catalog(str(dest / 'catalog.json'), scope=self.sc)
                self.assertEqual(recovered.head.interval, 1 if phase == 'catalog_replaced' else 0)
                recovered.verify_file_sha256(recovered.head.interval)
                recovered.close()
                self.assertTrue((dest / 'interval-0001.sqlite').exists())
                if phase == 'catalog_flushed':
                    self.assertEqual(len(list(dest.glob('catalog.json.tmp-*'))), 1)
                if phase != 'catalog_replaced':
                    self.assertEqual((dest / 'catalog.json').read_bytes(), original)

    def test_separate_recompressed_archive_keeps_logical_ids_and_active_bytes(self):
        a, b, c = b'abcdef' * 5000, b'012345' * 5000, b'ghijkl' * 5000
        for fresh, shared in (([a], ()), ([b], (a,)), ([c], (a, b))):
            candidate, ref, _ = add_interval(self.stores, fresh, share=shared,
                                             compression=Compression(codec='raw', palette=False))
            finish(self.stores, candidate, ref)
        old_entries = self.stores._entries()
        before = {p.name: digest(p.read_bytes()) for p in self.root.glob('*.sqlite')}
        before['catalog.json'] = digest((self.root / 'catalog.json').read_bytes())
        archive_root = self.root / 'independent-archive'
        archive_root.mkdir()
        archive = IntervalStoreSet.create_migration(str(archive_root / 'catalog.json'),
                                                    workflow_id=WORKFLOW, scope=self.sc)
        try:
            for fresh, shared in (([a], ()), ([b], (a,)), ([c], (a, b))):
                candidate, ref, _ = add_interval(archive, fresh, share=shared,
                                                 compression=Compression(codec='zstd', palette=False))
                finish(archive, candidate, ref)
            for old, new in zip(old_entries, archive._entries(), strict=True):
                self.assertEqual(old.head.identity, new.head.identity)
                self.assertEqual(old.logical_seal, new.logical_seal)
                self.assertNotEqual(old.file_sha256, new.file_sha256)
                archive.verify_file_sha256(new.interval)
        finally:
            archive.close()
        reopened = IntervalStoreSet.open_catalog(str(archive_root / 'catalog.json'), scope=self.sc)
        try:
            for i in range(3):
                reopened.verify_file_sha256(i)
        finally:
            reopened.close()
        self.assertEqual(before, {name: digest((self.root / name).read_bytes()) for name in before})

    def test_unsealed_and_unknown_native_schema_refuse(self):
        entry, _, _ = self.root_interval()
        self.stores.close()
        path = self.root / entry.filename
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        db = sqlite3.connect(path)
        db.execute('DELETE FROM snapshots WHERE id=?', (seal_key(WORKFLOW, 0),))
        db.commit()
        db.close()
        os.chmod(path, stat.S_IREAD)
        with self.assertRaisesRegex(ContractError, 'unsealed'):
            IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        db = sqlite3.connect(path)
        db.execute('CREATE TABLE extra (value INTEGER)')
        db.commit()
        db.close()
        os.chmod(path, stat.S_IREAD)
        with self.assertRaisesRegex(ContractError, 'schema'):
            IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)

    def test_live_file_identity_change_refuses(self):
        entry, ref, _ = self.root_interval()
        self.stores._handle(0)
        path = self.root / entry.filename
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        with self.assertRaisesRegex(ContractError, 'identity changed'):
            self.stores.resolve_manifest(0, ref.root_key)
        self.stores.close()

    def test_hardlinks_refuse_when_platform_allows_creation(self):
        entry, _, _ = self.root_interval()
        self.stores.close()
        path = self.root / entry.filename
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        link = self.root / 'hardlink.sqlite'
        try:
            os.link(path, link)
        except PermissionError:
            self.skipTest('Windows sandbox refuses hardlink fixture creation')
        with self.assertRaisesRegex(ContractError, 'hard-linked'):
            IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        os.chmod(link, stat.S_IWRITE | stat.S_IREAD)
        link.unlink()

    def test_native_nonfinite_and_manifest_bounds(self):
        candidate, _, _ = add_interval(self.stores, [b'x'])
        with self.assertRaisesRegex(ContractError, 'nonfinite'):
            candidate.put_chunk(canonical({'dtype': '<f8', 'count': 1}), np.array([np.inf]).tobytes())
        with self.assertRaisesRegex(ContractError, '64 KiB'):
            candidate.put_manifest('1' * 64, {'huge': 'x' * 65536})

    def test_final_seal_metadata_bound_and_missing_binding_refuse(self):
        candidate, ref, _ = add_interval(self.stores, [b'x'])
        bad = replace(ref, array_bindings=replace(ref.array_bindings,
                                                 root_key=SnapshotLocator(WORKFLOW, 0, '7' * 64)))
        # The immutable root binds the valid reference, so a conflicting head refuses.
        with self.assertRaises(ContractError):
            candidate.seal(bad)
        missing = replace(bad, root_key=SnapshotLocator(WORKFLOW, 0, '8' * 64))
        candidate.put_manifest('8' * 64, {'schema': 'atlas.segment-root.v1',
                                        'reference': missing.to_wire()})
        with self.assertRaises(KeyError):
            candidate.seal(missing)
        gc.collect()
        with patch('interval_store_set._seal_metadata', return_value={'huge': 'x' * 65536}):
            with self.assertRaisesRegex(ContractError, 'seal metadata'):
                candidate.seal(ref)
        self.assertFalse((self.root / 'catalog.json').exists())

    def test_failed_decode_workspace_stays_charged_with_traceback(self):
        _, _, chunks = self.root_interval()
        row = chunks[0]
        self.stores._handle(0)
        before = self.sc.run_budget.statistics()['reserved_bytes']
        held_traceback = None
        with patch.object(ArrayStore, '_decode', side_effect=RuntimeError('injected decode failure')):
            try:
                self.stores.resolve_chunk(0, 0, row['key'], row['descriptor'].encode())
            except RuntimeError as error:
                held_traceback = error.__traceback__
        self.assertGreater(self.sc.run_budget.statistics()['reserved_bytes'], before)
        self.assertIsNotNone(held_traceback)
        del held_traceback
        gc.collect()
        self.assertEqual(self.sc.run_budget.statistics()['reserved_bytes'], before)

    def test_duplicate_chunk_search_authenticates_once_without_encoding(self):
        self.root_interval()
        candidate = self.stores.begin_interval(self.stores.head, producer_identity='b' * 64,
                                               runtime_identity='c' * 64)
        desc = canonical({'dtype': '|u1', 'count': 150})
        calls = []
        original = ReadOnlyNative.chunk
        def counted(reader, key, descriptor):
            calls.append(key)
            return original(reader, key, descriptor)
        with patch.object(ReadOnlyNative, 'chunk', counted):
            owner, _ = candidate.put_chunk(desc, b'abc' * 50)
        self.assertEqual(owner, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(candidate.local_statistics()['encodes'], 0)

    def test_each_read_checks_path_and_sidecars_exactly_twice(self):
        _, ref, chunks = self.root_interval()
        reader = self.stores._handle(0).value
        original = Path.lstat
        calls = []
        def counted(path):
            calls.append(path)
            return original(path)
        one_boundary = len(reader.path.parents) + 1 + 3
        with patch.object(Path, 'lstat', counted):
            with self.stores.resolve_manifest(0, ref.root_key):
                pass
        self.assertEqual(len(calls), 2 * one_boundary)
        calls.clear()
        row = chunks[0]
        with patch.object(Path, 'lstat', counted):
            with self.stores.resolve_chunk(0, 0, row['key'], row['descriptor'].encode()):
                pass
        self.assertEqual(len(calls), 2 * one_boundary)

    def test_sidecars_before_and_during_read_still_refuse(self):
        _, ref, chunks = self.root_interval()
        reader = self.stores._handle(0).value
        sidecar = Path(str(reader.path) + '-journal')
        sidecar.write_bytes(b'unaccepted sidecar')
        with self.assertRaisesRegex(ContractError, 'sidecar'):
            self.stores.resolve_manifest(0, ref.root_key)
        sidecar.unlink()
        original = ArrayStore._decode
        def add_sidecar(handle, codec, payload, dt, count):
            raw = original(handle, codec, payload, dt, count)
            sidecar.write_bytes(b'appeared during read')
            return raw
        row = chunks[0]
        with patch.object(ArrayStore, '_decode', add_sidecar):
            with self.assertRaisesRegex(ContractError, 'sidecar'):
                self.stores.resolve_chunk(0, 0, row['key'], row['descriptor'].encode())
        sidecar.unlink()

    def test_failed_catalog_open_keeps_decoded_owner_with_traceback(self):
        from interval_store_set import catalog_retained_charge
        entry, _, _ = self.root_interval()
        self.stores.close()
        # W1 L16: the retained owner is booked from the decoded catalog.
        CATALOG_CHARGE = catalog_retained_charge(read_catalog(self.root / 'catalog.json')[0])
        path = self.root / entry.filename
        path.rename(self.root / 'preserved.sqlite')
        before = self.sc.stats().retained_bytes
        held_traceback = None
        try:
            IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        except ContractError as error:
            held_traceback = error.__traceback__
        self.assertIsNotNone(held_traceback)
        gc.collect()
        self.assertGreaterEqual(self.sc.stats().retained_bytes, before + CATALOG_CHARGE)
        del held_traceback
        gc.collect()
        self.assertEqual(self.sc.stats().retained_bytes, before)

    def test_cached_read_safety_is_fresh_and_cancellable(self):
        entry, _, _ = self.root_interval()
        self.stores._handle(0)
        self.stores.assert_cached_read_safe()
        token = threading.Event()
        token.set()
        with self.assertRaises(InterruptedError):
            self.stores.assert_cached_read_safe(cancel=token)
        sidecar = Path(str(self.root / entry.filename) + '-wal')
        sidecar.write_bytes(b'new sidecar')
        with self.assertRaisesRegex(ContractError, 'sidecar'):
            self.stores.assert_cached_read_safe()
        sidecar.unlink()
        self.stores.assert_cached_read_safe()

    def test_evicted_source_file_stays_bound_for_cached_reads(self):
        for i in range(9):
            candidate, ref, _ = add_interval(self.stores, [bytes([i + 1]) * 20])
            finish(self.stores, candidate, ref)
        self.stores.close()
        self.stores = IntervalStoreSet.open_catalog(str(self.root / 'catalog.json'), scope=self.sc)
        for i in range(9):
            pin = self.stores.borrow_handle(i)
            pin.close()
        self.assertNotIn(0, self.stores._handles)
        self.assertIn(0, self.stores._verified_tokens)
        self.assertEqual(len(self.stores._handles), 8)
        self.stores.assert_cached_read_safe()
        self.assertEqual(len(self.stores._handles), 8)
        path = self.root / 'interval-0000.sqlite'
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        with path.open('ab') as out:
            out.write(b'changed after eviction')
        os.chmod(path, stat.S_IREAD)
        with self.assertRaisesRegex(ContractError, 'identity changed'):
            self.stores.assert_cached_read_safe()
        # A later open cannot silently replace the previously authenticated token.
        with self.assertRaisesRegex(ContractError, 'identity changed'):
            self.stores.borrow_handle(0)
        path.rename(self.root / 'changed-preserved.sqlite')
        with self.assertRaisesRegex(ContractError, 'missing'):
            self.stores.assert_cached_read_safe()
        self.stores.close()
        self.assertEqual(self.stores._verified_tokens, {})

    def test_closed_candidate_drops_prepaid_reference_set(self):
        self.root_interval()
        candidate, _, _ = add_interval(self.stores, [b'next'], share=(b'abc' * 50,))
        self.assertEqual(candidate._references, {0})
        candidate.close()
        self.assertEqual(candidate._references, set())


class CatalogTests(unittest.TestCase):
    def entry(self, i, previous=None, references=()):
        loc = SnapshotLocator(WORKFLOW, i, 'd' * 64)
        ref = SegmentRef(SEGMENT_REF_SCHEMA, loc, LogicalIdentity('fixture.v1', 'e' * 64, 0),
                         0, BindingIndexRef(BINDING_INDEX_SCHEMA, loc, 'f' * 64, 0), '0' * 64)
        return CatalogEntry(i, f'interval-{i:04d}.sqlite', '1' * 64,
                            hashlib.sha256(str(i).encode()).hexdigest(), i - 1 if i else None,
                            previous.logical_seal if previous else None, ref,
                            '2' * 64, '3' * 64, references)

    def test_unknown_duplicate_noncanonical_and_bad_closure(self):
        zero = self.entry(0)
        raw = Catalog(WORKFLOW, 1, (zero,)).to_bytes()
        for changed in (raw.replace(b'atlas.interval-catalog.v1', b'atlas.interval-catalog.v9'),
                        raw.replace(b'"generation":1', b'"generation":1,"generation":1'),
                        raw + b' '):
            with self.assertRaises(ContractError):
                Catalog.from_bytes(changed)
        one = self.entry(1, zero, ((0, zero.logical_seal),))
        two = self.entry(2, one, ((1, one.logical_seal),))
        with self.assertRaises(ContractError):
            Catalog(WORKFLOW, 3, (zero, one, two))
        with self.assertRaises(ContractError):
            replace(one, references=((1, one.logical_seal),))

    def test_catalog_growth_refuses_without_replacing_old(self):
        entries = []
        for i in range(1000):
            entries.append(self.entry(i, entries[-1] if entries else None))
        candidate = Catalog(WORKFLOW, len(entries), tuple(entries))
        with tempfile.TemporaryDirectory(prefix='wp13-catalog-') as tmp:
            path = Path(tmp) / 'catalog.json'
            old = Catalog(WORKFLOW, 1, (entries[0],)).to_bytes()
            path.write_bytes(old)
            with self.assertRaisesRegex(ContractError, '1 MiB'):
                publish_catalog(path, candidate, expected_digest=digest(old))
            self.assertEqual(path.read_bytes(), old)
            self.assertFalse(list(Path(tmp).glob('catalog.json.tmp-*')))

    def test_actual_catalog_lock_and_disk_compare_and_swap(self):
        zero = self.entry(0)
        first = Catalog(WORKFLOW, 1, (zero,))
        second = Catalog(WORKFLOW, 2, (zero, self.entry(1, zero)))
        with tempfile.TemporaryDirectory(prefix='wp13-cas-') as tmp:
            path = Path(tmp) / 'catalog.json'
            identity = publish_catalog(path, first, expected_digest=None)
            with publication_lock(path):
                with self.assertRaisesRegex(ContractError, 'lock'):
                    publish_catalog(path, second, expected_digest=identity)
            newer = publish_catalog(path, second, expected_digest=identity)
            self.assertEqual(read_catalog(path)[1], newer)
            with self.assertRaisesRegex(ContractError, 'compare-and-swap'):
                publish_catalog(path, first, expected_digest=identity)
            self.assertEqual(read_catalog(path)[0], second)


if __name__ == '__main__':
    unittest.main()
