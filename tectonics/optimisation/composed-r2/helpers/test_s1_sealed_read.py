"""S1 sealed-read speed: file identity per read batch, verified-manifest memo.

Synthetic data only (real native SQLite files under the tree's _t folder); no
timing assertions. tracemalloc is used for memory only.
"""
import gc
import os
import shutil
import sqlite3
import stat
import threading
import traceback
import tracemalloc
import unittest
from concurrent.futures import CancelledError
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import interval_store_set as ISS
import segment_store as S
import test_segment_store as fixture
from compact_contracts import ContractError
from interval_store_set import IntervalStoreSet, ReadOnlyNative

CHUNK = 65536


def _expected(source, start, stop):
    size = source.info.logical_bytes
    first, last = start // CHUNK, (stop - 1) // CHUNK
    data = b''.join(source.block(i, min(CHUNK, size - i * CHUNK)) for i in range(first, last + 1))
    return data[start - first * CHUNK:stop - first * CHUNK]


class _Counter:
    """Counts ReadOnlyNative._check_identity calls (each is one file_token)."""
    def __init__(self):
        self.calls = 0
        original = ReadOnlyNative._check_identity

        def check(reader):
            self.calls += 1
            return original(reader)
        self.check = check

    def patch(self):
        return patch.object(ReadOnlyNative, '_check_identity', self.check)


class S1SealedReadTests(unittest.TestCase):
    setUp = fixture.SegmentStoreTests.setUp
    tearDown = fixture.SegmentStoreTests.tearDown
    publish = fixture.SegmentStoreTests.publish
    open = fixture.SegmentStoreTests.open
    promote = fixture.SegmentStoreTests.promote

    def sealed(self, size=40 * CHUNK + 11):
        # 41 leaves: three leaf pages and one branch page below the root.
        source = fixture.GeneratedSource(self.scope, size)
        ref = self.publish([source])
        self.promote(ref)
        view = self.open(ref, self.stores)
        return view, source, self.stores._handles[0].value

    def restore_read_only(self, path):
        os.chmod(path, stat.S_IREAD)

    def test_read_is_exact_and_checks_identity_once_before_and_after(self):
        view, source, _ = self.sealed()
        start, stop = 17 * CHUNK + 5, 33 * CHUNK + 9   # spans two leaf pages, 17 chunks
        counter = _Counter()
        with counter.patch(), view.read('payload', start, stop, max_owned_bytes=stop - start) as owned:
            self.assertEqual(owned.value, _expected(source, start, stop))
        # Before S1: two checks per page load and two per chunk (>= 40 here).
        self.assertEqual(counter.calls, 2)
        counter = _Counter()
        with counter.patch(), view.verified_read():
            for at in range(0, 40 * CHUNK, 5 * CHUNK + 3):
                with view.read('payload', at, at + 7, max_owned_bytes=7) as owned:
                    self.assertEqual(owned.value, _expected(source, at, at + 7))
        self.assertEqual(counter.calls, 2)   # one batch: before and after only
        blocks = []
        with view.scan(max_owned_bytes=CHUNK) as stream:
            for block in stream:
                with block:
                    blocks.append(block.value.data)
        self.assertEqual(b''.join(blocks), _expected(source, 0, source.info.logical_bytes))

    def test_unbatched_resolver_calls_keep_their_own_before_after_checks(self):
        view, _, _ = self.sealed()
        counter = _Counter()
        with counter.patch(), self.stores.resolve_manifest(0, view.ref.root_key) as body:
            self.assertTrue(body.value)
        self.assertEqual(counter.calls, 2)
        self.assertFalse(self.stores._batched())

    def test_attribute_change_mid_batch_refuses_at_batch_end_and_invalidates_memo(self):
        view, source, handle = self.sealed()
        path = handle.path
        with view.read('payload', 0, 9, max_owned_bytes=9):
            pass
        self.assertGreater(len(handle._memo), 0)
        self.assertGreater(self.scope.stats().purpose_bytes['retained:interval-manifest-memo'], 0)
        escaped = []
        try:
            with self.assertRaisesRegex(ContractError, 'identity changed'), view.verified_read():
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)   # sealed file changes mid-batch
                inner = view.read('payload', 30 * CHUNK, 30 * CHUNK + 9, max_owned_bytes=9)
                escaped.append(inner.value == _expected(source, 30 * CHUNK, 30 * CHUNK + 9))
                inner.close()
            # The read inside the batch ran (no per-call check) but nothing
            # outside the batch saw success: the batch end refused.
            self.assertEqual(escaped, [True])
            self.assertEqual(view._read_depth, 0)
            self.assertFalse(self.stores._batched())
            self.assertEqual(len(handle._memo), 0)
            self.assertGreaterEqual(handle.memo_invalidations, 1)
            self.assertEqual(self.scope.stats().purpose_bytes.get('retained:interval-manifest-memo', 0), 0)
            with self.assertRaisesRegex(ContractError, 'identity changed'):
                view.read('payload', 0, 9, max_owned_bytes=9)
        finally:
            self.restore_read_only(path)

    def test_modified_file_mid_read_refuses_and_memo_never_serves_it(self):
        view, _, handle = self.sealed()
        path = handle.path
        with view.read('payload', 0, 9, max_owned_bytes=9):
            pass
        original = self.stores.resolve_chunk
        calls = [0]

        def rewrite_after_first_chunk(*args, **kwargs):
            result = original(*args, **kwargs)
            calls[0] += 1
            if calls[0] == 1:
                # Another writer changes the sealed file between two chunk reads.
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                db = sqlite3.connect(path)
                db.execute('CREATE TABLE intruder (value INTEGER)')
                db.commit()
                db.close()
                os.chmod(path, stat.S_IREAD)
            return result
        with patch.object(self.stores, 'resolve_chunk', side_effect=rewrite_after_first_chunk), \
                self.assertRaisesRegex(ContractError, 'identity changed'):
            view.read('payload', 2 * CHUNK, 5 * CHUNK, max_owned_bytes=3 * CHUNK)
        self.assertEqual(calls[0], 3)   # the read itself completed inside the batch
        self.assertEqual(len(handle._memo), 0)
        with patch.object(ISS.native.ArrayStore, '_manifest', side_effect=AssertionError('reread')), \
                self.assertRaisesRegex(ContractError, 'identity changed'):
            view.read('payload', 0, 9, max_owned_bytes=9)
        # A fresh store set refuses the changed file outright.
        view.close()
        self.views.remove(view)
        self.candidate.close()
        self.stores.close()
        with self.assertRaisesRegex(ContractError, 'schema'):
            IntervalStoreSet.open_catalog(self.path / 'catalog.json', scope=self.scope)

    def test_sidecar_appearing_mid_read_refuses_then_clears(self):
        view, source, handle = self.sealed()
        sidecar = Path(str(handle.path) + '-journal')
        original = self.stores.resolve_chunk

        def sidecar_after_first(*args, **kwargs):
            result = original(*args, **kwargs)
            if not sidecar.exists():
                # Empty, so SQLite itself does not treat it as a hot journal;
                # the refusal below is the batch's closing identity check.
                sidecar.write_bytes(b'')
            return result
        try:
            with patch.object(self.stores, 'resolve_chunk', side_effect=sidecar_after_first), \
                    self.assertRaisesRegex(ContractError, 'sidecar'):
                view.read('payload', 0, 3 * CHUNK, max_owned_bytes=3 * CHUNK)
        finally:
            sidecar.unlink()
        with view.read('payload', 0, 3 * CHUNK, max_owned_bytes=3 * CHUNK) as owned:
            self.assertEqual(owned.value, _expected(source, 0, 3 * CHUNK))

    def test_replacement_by_identical_bytes_is_refused(self):
        view, _, handle = self.sealed()
        path = handle.path
        with view.read('payload', 0, 9, max_owned_bytes=9):
            pass
        copy = path.with_name('replacement.bin')
        shutil.copyfile(path, copy)
        os.chmod(copy, stat.S_IREAD)
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            try:
                os.replace(copy, path)
            except OSError as exc:
                os.chmod(path, stat.S_IREAD)
                self.skipTest(f'OS refuses replacing an open SQLite file here: {exc!r}')
            with self.assertRaisesRegex(ContractError, 'identity changed'), view.verified_read():
                view.read('payload', 0, 9, max_owned_bytes=9).close()
            self.assertEqual(len(handle._memo), 0)
        finally:
            if copy.exists():
                os.chmod(copy, stat.S_IWRITE | stat.S_IREAD)
                copy.unlink()

    def test_memo_serves_verified_bodies_bound_to_token(self):
        view, source, handle = self.sealed()
        start, stop = 20 * CHUNK, 20 * CHUNK + 50
        with view.read('payload', start, stop, max_owned_bytes=50) as owned:
            self.assertEqual(owned.value, _expected(source, start, stop))
        hits = handle.memo_hits
        with patch.object(ISS.native.ArrayStore, '_manifest', side_effect=AssertionError('memo should serve')), \
                view.read('payload', start, stop, max_owned_bytes=50) as owned:
            self.assertEqual(owned.value, _expected(source, start, stop))
        self.assertGreater(handle.memo_hits, hits)
        for key, body in handle._memo.items():
            row = handle._db.execute('SELECT body FROM snapshots WHERE id=?', (key,)).fetchone()
            self.assertEqual(row[0], body)
        # Funding covers the held bodies, within one slab.
        booked = self.scope.stats().purpose_bytes['retained:interval-manifest-memo']
        self.assertGreaterEqual(handle._memo_funded, handle._memo_used)
        self.assertLess(handle._memo_funded - handle._memo_used, ISS.MEMO_SLAB_BYTES)
        self.assertEqual(booked, len(handle._memo_slabs) * (ISS.MEMO_SLAB_BYTES + 4096))

    def test_memo_ceiling_and_pressure(self):
        _, _, handle = self.sealed()
        handle._release_memo()
        body = b'x' * 200_000
        for i in range(40):
            handle._memo_put(sha256(str(i).encode()).hexdigest(), bytes(body))
        self.assertLessEqual(handle._memo_used, ISS.MANIFEST_MEMO_BYTES)
        self.assertLessEqual(handle._memo_funded, ISS.MANIFEST_MEMO_BYTES + ISS.MEMO_SLAB_BYTES)
        handle._memo_put('f' * 64, b'y' * (ISS.MANIFEST_MEMO_BYTES + 1))
        self.assertNotIn('f' * 64, handle._memo)
        original = self.scope.reserve

        def declined(spec, **kwargs):
            if spec.purpose == 'interval-manifest-memo':
                return None
            return original(spec, **kwargs)
        # A declined slab after LRU eviction leaves at most one unused slab funded.
        with patch.object(self.scope, 'reserve', side_effect=declined):
            handle._memo_put('d' * 64, b'w' * (2 << 20))
        self.assertNotIn('d' * 64, handle._memo)
        self.assertGreaterEqual(handle._memo_funded, handle._memo_used)
        self.assertLess(handle._memo_funded - handle._memo_used, ISS.MEMO_SLAB_BYTES)
        handle._release_memo()
        with patch.object(self.scope, 'reserve', side_effect=declined):
            handle._memo_put('e' * 64, b'z' * 1000)
        self.assertEqual(len(handle._memo), 0)
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:interval-manifest-memo', 0), 0)

    def test_memo_booking_covers_measured_memory(self):
        """tracemalloc (memory only): real <= booked <= 1.3 x real."""
        _, _, handle = self.sealed()
        handle._release_memo()
        for size, count in ((4_500, 300), (600, 400), (60_000, 40)):
            gc.collect()
            booked_before = self.scope.stats().purpose_bytes.get('retained:interval-manifest-memo', 0)
            tracemalloc.start()
            try:
                base = tracemalloc.get_traced_memory()[0]
                for i in range(count):
                    key = sha256(f'{size}:{i}'.encode()).hexdigest()
                    handle._memo_put(key, os.urandom(size))
                real = tracemalloc.get_traced_memory()[0] - base
            finally:
                tracemalloc.stop()
            booked = self.scope.stats().purpose_bytes['retained:interval-manifest-memo'] - booked_before
            self.assertLessEqual(real, booked, (size, count, real, booked))
            if real >= 1 << 20:
                self.assertLessEqual(booked, 1.3 * real, (size, count, real, booked))
            fixture.MEASUREMENTS[f's1_memo_{size}'] = {'entries': count, 'real': real, 'booked': booked}
            handle._release_memo()
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:interval-manifest-memo', 0), 0)

    def test_open_seal_inventory_checks_identity_once_after_scan(self):
        small, _, _ = self.sealed(size=3 * CHUNK)
        small.close()
        self.views.remove(small)
        self.stores.close()
        counter = _Counter()
        with counter.patch():
            stores = IntervalStoreSet.open_catalog(self.path / 'catalog.json', scope=self.scope)
        stores.close()
        # constructor (1) + seal manifest before/after (2) + one after the
        # whole inventory scan (1); independent of the number of manifests.
        self.assertEqual(counter.calls, 4)

    def test_other_threads_are_not_covered_by_this_threads_batch(self):
        view, _, _ = self.sealed()
        seen = []

        def other():
            seen.append(self.stores._batched())
            counter = _Counter()
            with counter.patch(), self.stores.resolve_manifest(0, view.ref.root_key):
                pass
            seen.append(counter.calls)
        with self.stores.read_batch():
            self.assertTrue(self.stores._batched())
            thread = threading.Thread(target=other)
            thread.start()
            thread.join(10)
        self.assertEqual(seen, [False, 2])
        self.assertFalse(self.stores._batched())

    def test_failed_body_and_cancellation_keep_semantics(self):
        view, _, _ = self.sealed()
        with self.assertRaisesRegex(ValueError, 'body failed'), self.stores.read_batch(), \
                self.stores.read_batch():
            raise ValueError('body failed')
        self.assertFalse(self.stores._batched())
        event = threading.Event()
        view.cancel = event
        with self.assertRaises((CancelledError, InterruptedError)), view.verified_read():
            event.set()
            view.read('payload', 0, 9, max_owned_bytes=9)
        self.assertEqual(view._read_depth, 0)
        self.assertFalse(self.stores._batched())
        event.clear()
        with view.read('payload', 0, 9, max_owned_bytes=9):
            pass

    def test_failed_closing_check_withholds_read_and_keeps_failed_frame_paid(self):
        view, _, _ = self.sealed()
        original = self.stores.assert_cached_read_safe
        calls = [0]

        def closing_fails(**kwargs):
            calls[0] += 1
            if calls[0] == 2:
                raise ContractError('changed after read')
            original(**kwargs)
        failure = None
        with patch.object(self.stores, 'assert_cached_read_safe', side_effect=closing_fails):
            try:
                view.read('payload', 0, 2 * CHUNK, max_owned_bytes=2 * CHUNK)
            except ContractError as exc:
                failure = exc
        self.assertIsNotNone(failure)
        self.assertGreater(self.scope.stats().purpose_bytes.get('retained:segment-read', 0), 0)
        traceback.clear_frames(failure.__traceback__)
        failure.__traceback__ = None
        del failure
        gc.collect()
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:segment-read', 0), 0)


class S1RefuterFreshnessTests(unittest.TestCase):
    """S1 refuter (16 Oct, fixes/refute-s1-9a/probe_keyerror*.py): the sealed file is
    rewritten in place mid-batch so that a page manifest not yet loaded is missing,
    with the optional manifest memo evicted (LRU ceiling or retained pressure).
    Before S1 every lookup checked the file identity before its KeyError; every
    outcome here must be that refusal (ContractError), never an 'absent' answer."""
    setUp = fixture.SegmentStoreTests.setUp
    tearDown = fixture.SegmentStoreTests.tearDown
    publish = fixture.SegmentStoreTests.publish
    open = fixture.SegmentStoreTests.open
    promote = fixture.SegmentStoreTests.promote
    sealed = S1SealedReadTests.sealed

    def rewrite_after_first_manifest(self, handle, *, after=1):
        """After the `after`-th resolved manifest, another writer deletes every
        other snapshot row of the sealed file in place (the refuter's scenario)."""
        original = self.stores.resolve_manifest
        calls = [0]

        def rewrite(requester, locator, *, cancel=None):
            calls[0] += 1   # counts attempted lookups, including a refused one
            result = original(requester, locator, cancel=cancel)
            if calls[0] == after:
                os.chmod(handle.path, stat.S_IWRITE | stat.S_IREAD)
                db = sqlite3.connect(handle.path)
                db.execute('DELETE FROM snapshots WHERE id != ?', (locator.snapshot_key,))
                db.commit()
                db.close()
                os.chmod(handle.path, stat.S_IREAD)
            return result
        return patch.object(self.stores, 'resolve_manifest', side_effect=rewrite), calls

    def assert_refused_like_origin(self, operation, view):
        handle = self.stores._handles[0].value
        handle._release_memo()   # the optional memo evicted these page bodies
        hook, calls = self.rewrite_after_first_manifest(handle)
        with hook, self.assertRaisesRegex(ContractError, 'identity changed'):
            operation()
        # Refused at a lookup after the rewrite, inside the batch (not by its opening check).
        self.assertGreaterEqual(calls[0], 2)
        self.assertFalse(self.stores._batched())
        self.assertEqual(view._read_depth, 0)
        with self.assertRaisesRegex(ContractError, 'identity changed'):
            view.read('payload', 0, 9, max_owned_bytes=9)

    def test_info_array_on_rewritten_file_refuses(self):
        view, _, _ = self.sealed()
        self.assert_refused_like_origin(lambda: view.info.array('payload').close(), view)

    def test_has_array_idiom_on_rewritten_file_refuses(self):
        view, _, _ = self.sealed()

        def has_array(name):
            # The ordinary 'absent' idiom: KeyError means the array is absent.
            try:
                view.info.array(name).close()
                return True
            except KeyError:
                return False
        # Unchanged file: a genuinely absent name is still a plain KeyError ('absent').
        self.assertTrue(has_array('payload'))
        self.assertFalse(has_array('absent-name'))
        self.assert_refused_like_origin(lambda: has_array('payload'), view)

    def test_read_on_rewritten_file_refuses(self):
        view, _, _ = self.sealed()
        self.assert_refused_like_origin(
            lambda: view.read('payload', 30 * CHUNK, 30 * CHUNK + 9, max_owned_bytes=9).close(), view)

    def test_view_open_validation_on_rewritten_file_refuses(self):
        view, _, handle = self.sealed()
        handle._release_memo()
        # Root metadata (call 1) is read before the validation batch; the file
        # is rewritten after the walk's first page (call 2, inside the batch),
        # so the next page of the validation walk is missing.
        hook, calls = self.rewrite_after_first_manifest(handle, after=2)
        with hook, self.assertRaisesRegex(ContractError, 'identity changed'):
            self.backend.open(self.stores, view.ref, scope=self.scope)
        self.assertGreaterEqual(calls[0], 3)
        self.assertFalse(self.stores._batched())

    def build_record(self):
        import record_tables as T
        from record_views import CompactRecord
        value = {'alpha': list(range(50)), 'beta': 'present', 'gamma': [hex(i) for i in range(20)],
                 'delta': {'x': 1.5, 'y': -0.0}}
        packed = T.RecordCodec().pack_record(value, record_schema='test.persisted.v1', scope=self.scope,
                                             check=lambda: None)
        with packed.metadata_bytes() as held:
            ref = self.backend.publish(self.candidate, record_schema='test.persisted.v1',
                                       identity=packed.identity(), metadata=held.value,
                                       arrays=packed.array_sources, producer='2' * 64,
                                       representation_profile=T.SCHEMA, scope=self.scope)
        packed.close()
        self.promote(ref)
        segment = self.open(ref, self.stores)
        record = CompactRecord.from_segment(segment, use_page_cache=False)
        return segment, record

    def assert_record_lookup_refuses(self, lookup):
        _, record = self.build_record()   # the segment view is closed by tearDown
        root = record.root()
        try:
            # Unchanged file: presence answers are exact, absence is still KeyError.
            self.assertIs(lookup(root, 'beta'), True)
            self.assertIs(lookup(root, 'zeta'), False)
            handle = self.stores._handles[0].value
            handle._release_memo()
            hook, calls = self.rewrite_after_first_manifest(handle)
            with hook, self.assertRaisesRegex(ContractError, 'identity changed'):
                lookup(root, 'beta')
            self.assertGreaterEqual(calls[0], 2)
            self.assertFalse(self.stores._batched())
            with self.assertRaisesRegex(ContractError, 'identity changed'):
                lookup(root, 'alpha')
        finally:
            root.close()
            record.close()

    def test_record_field_presence_on_rewritten_file_refuses(self):
        def present(root, name):
            # spatial_validation_patch._CompactMapping.__contains__ idiom.
            try:
                child = root.field(name)
            except KeyError:
                return False
            child.close()
            return True
        self.assert_record_lookup_refuses(present)

    def test_record_get_default_on_rewritten_file_refuses(self):
        marker = 'absent-default'

        def present(root, name):
            # record_views.get: a KeyError from field() becomes the default.
            result = root.get(name, marker, max_owned_bytes=1 << 20)
            try:
                return result.value != marker
            finally:
                result.close()
        self.assert_record_lookup_refuses(present)

    def test_seal_inventory_failure_gets_its_closing_identity_check(self):
        _, _, handle = self.sealed(size=3 * CHUNK)
        path = handle.path
        for changed in (False, True):
            with self.subTest(changed=changed):
                reader = ReadOnlyNative(path, scope=self.scope)
                original = reader.manifest

                def fail_in_scan(key, *, batched=False, memo=True, _original=original, _changed=changed):
                    if not batched:
                        return _original(key, batched=batched, memo=memo)
                    if _changed:
                        info = path.stat()
                        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000))
                    raise KeyError(key)   # a body failure that skipped the per-call check
                try:
                    with patch.object(reader, 'manifest', side_effect=fail_in_scan):
                        if changed:
                            with self.assertRaisesRegex(ContractError, 'identity changed') as caught:
                                ISS._seal_digest(reader, workflow_id='a' * 64, interval=0, parent_seal=None,
                                                 references=())
                            self.assertIs(type(caught.exception.__cause__), KeyError)
                        else:
                            with self.assertRaises(KeyError):
                                ISS._seal_digest(reader, workflow_id='a' * 64, interval=0, parent_seal=None,
                                                 references=())
                finally:
                    reader.close()

    def test_failed_batch_body_refuses_only_if_identity_changed(self):
        _, _, handle = self.sealed()
        with self.assertRaises(KeyError), self.stores.read_batch():
            raise KeyError('genuinely absent')      # unchanged file: original error
        self.assertFalse(self.stores._batched())
        path = handle.path
        try:
            with self.assertRaisesRegex(ContractError, 'identity changed') as caught, self.stores.read_batch():
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                raise KeyError('answered while the file changed')
            self.assertIs(type(caught.exception.__cause__), KeyError)
            self.assertFalse(self.stores._batched())
        finally:
            os.chmod(path, stat.S_IREAD)

    def test_verified_read_fallback_without_read_batch_checks_on_failure(self):
        view, _, handle = self.sealed()
        stores = self.stores

        class NoBatchResolver:
            """A sealed resolver without read_batch: verified_read's own fallback."""
            scope, workflow_id = stores.scope, stores.workflow_id
            head, catalog_digest = stores.head, stores.catalog_digest
            resolve_manifest, resolve_chunk = stores.resolve_manifest, stores.resolve_chunk
            assert_cached_read_safe = stores.assert_cached_read_safe
        plain = self.open(view.ref, NoBatchResolver())
        self.assertFalse(hasattr(plain.resolver, 'read_batch'))
        with self.assertRaises(KeyError), plain.verified_read():
            raise KeyError('genuinely absent')      # unchanged file: original error
        path = handle.path
        try:
            with self.assertRaisesRegex(ContractError, 'identity changed') as caught, plain.verified_read():
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                raise KeyError('answered while the file changed')
            self.assertIs(type(caught.exception.__cause__), KeyError)
            self.assertEqual(plain._read_depth, 0)
        finally:
            os.chmod(path, stat.S_IREAD)

    def test_nested_batch_suspended_past_its_outer_batch_refuses(self):
        # The refuter's probe_depth_generator.py as a test: a generator suspended
        # inside a NESTED batch and finished after the outer batch closed must
        # not leave the thread 'batched' (no per-call identity checks).
        view, _, handle = self.sealed(size=3 * CHUNK)
        stores = self.stores

        def leaky():
            with stores.read_batch():
                yield 1
                yield 2
        gen = leaky()
        with self.assertRaisesRegex(ContractError, 'still open when its outer batch ended'), stores.read_batch():
            next(gen)
        self.assertFalse(stores._batched())
        self.assertEqual(next(gen), 2)
        with self.assertRaisesRegex(ContractError, 'ended after its outer batch'):
            gen.close()
        self.assertFalse(stores._batched())
        # A stale nested batch finishing inside a LATER batch leaves that batch intact.
        later = leaky()
        with self.assertRaisesRegex(ContractError, 'still open'), stores.read_batch():
            next(later)
        with stores.read_batch():
            self.assertEqual(next(later), 2)
            with self.assertRaisesRegex(ContractError, 'ended after its outer batch'):
                later.close()
            self.assertTrue(stores._batched())
            self.assertEqual(stores._batch_state.depth, 1)
        self.assertFalse(stores._batched())
        # The file now changes; an unbatched resolver call refuses per call.
        path = handle.path
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        db = sqlite3.connect(path)
        db.execute('CREATE TABLE intruder (v INTEGER)')
        db.commit()
        db.close()
        os.chmod(path, stat.S_IREAD)
        with self.assertRaisesRegex(ContractError, 'identity changed'):
            stores.resolve_manifest(0, view.ref.root_key)


class ClosingCheckWordingTests(unittest.TestCase):
    """R1-batch storage (S1 refuter divergence 3): the closing identity check of a failed
    batch body refuses in every case; an identity that cannot be read (an OSError from the
    stat) is worded as unverified, a changed one keeps its words, an unchanged file returns."""

    def test_stat_error_is_reported_as_unverified(self):
        body = KeyError('absent')

        def unreadable():
            raise PermissionError(13, 'denied')
        with self.assertRaisesRegex(
                ContractError, r'^could not verify immutable interval file identity \(PermissionError\)$') as caught:
            ISS._closing_check_after_failure(unreadable, body)
        self.assertIs(caught.exception.__cause__, body)

    def test_changed_identity_keeps_its_words_and_unchanged_returns(self):
        body = KeyError('absent')

        def changed():
            raise ContractError('immutable interval file identity changed')
        with self.assertRaisesRegex(ContractError, r'^immutable interval file identity changed$') as caught:
            ISS._closing_check_after_failure(changed, body)
        self.assertIs(caught.exception.__cause__, body)
        self.assertIsNone(ISS._closing_check_after_failure(lambda: None, body))


class DigestSpellingTests(unittest.TestCase):
    def test_compiled_digest_check_accepts_exactly_the_former_set(self):
        def former(value):
            return (type(value) is str and len(value) == 64 and
                    all(c in '0123456789abcdef' for c in value))
        good = sha256(b'x').hexdigest()
        cases = [good, good.upper(), good[:63], good + '0', good[:63] + '\n', good + '\n',
                 '٠' * 64, 'g' * 64, 'f' * 64, '0' * 64, ' ' + good[1:], good.encode(),
                 None, 7, '', good[:32] + 'A' + good[33:], good[:10] + '０' + good[11:]]
        cases += [bytes([b]).decode('latin-1') * 64 for b in range(256)]
        for value in cases:
            accepted = True
            try:
                S._digest(value)
            except ContractError:
                accepted = False
            self.assertEqual(accepted, former(value), repr(value))


def tearDownModule():
    if fixture.MEASUREMENTS:
        import json
        import sys
        print('S1 measurements:', json.dumps(fixture.MEASUREMENTS, sort_keys=True), file=sys.stderr)


if __name__ == '__main__':
    unittest.main()
