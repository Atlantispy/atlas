"""Bounded Step 7B reuse: exact bytes, read boundaries and paid lifetimes."""
from concurrent.futures import CancelledError
from contextlib import contextmanager
import gc
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import weakref

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1] / 'runtime-integration-r1' / 'runtime-src'),
               str(HERE.parent)]

import numpy as np

from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError, LogicalIdentity
from content_cache import ChargeSpec, OwnedStream, create_retained_scope
from interval_store_set import IntervalStoreSet
import record_tables as T
import record_views as V
from segment_store import ArrayInfo, SegmentBackend
from test_record_tables import streamed


class _TypedSource:
    def __init__(self, scope, values):
        self.scope, self.raw = scope, values.tobytes()
        self.info = ArrayInfo('typed', values.dtype.str, values.shape, values.nbytes)

    def blocks(self, *, max_owned_bytes):
        def blocks():
            for at in range(0, len(self.raw), max_owned_bytes):
                raw = self.raw[at:at + max_owned_bytes]
                with self.scope.reserve(ChargeSpec('typed-test-source', len(raw))) as reserved:
                    yield reserved.commit(raw)
        return OwnedStream(blocks(), scope=self.scope)


class RecordReuseTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(128 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='step7b-record-reuse')

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def pack(self, value, *, check=lambda: None):
        return T.RecordCodec().pack_record(value, record_schema='test.step7b.v1',
                                           scope=self.scope, check=check)

    @contextmanager
    def sealed(self, record, *, use_page_cache=True):
        with tempfile.TemporaryDirectory(prefix='step7b-reuse-') as directory:
            stores = IntervalStoreSet.create_migration(Path(directory) / 'catalog.json',
                workflow_id='a' * 64, scope=self.scope)
            candidate = stores.begin_interval(None, producer_identity='b' * 64,
                                               runtime_identity='c' * 64)
            backend = SegmentBackend()
            with record.metadata_bytes() as metadata:
                reference = backend.publish(candidate, record_schema=record.identity().record_schema,
                    identity=record.identity(), metadata=metadata.value, arrays=record.array_sources,
                    producer='b' * 64, representation_profile=T.SCHEMA, scope=self.scope)
            sealed = candidate.seal(reference)
            stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
            segment = backend.open(stores, reference, scope=self.scope)
            restored = V.CompactRecord.from_segment(segment, use_page_cache=use_page_cache)
            try:
                yield restored, segment, stores
            finally:
                restored.close()
                del restored
                segment.close()
                candidate.close()
                stores.close()

    def test_repeated_subtree_keeps_exact_spellings_and_reopens(self):
        row = dict(integer=1, float=1.0, negative_zero=-0.0,
            bounds=[(1 << 64) - 1, -(1 << 65)], text='repeat-token-' * 32,
            spellings=['0x01', '+0x1', '0XFF', '-0x0', '001', '1e3', 'é\ud800\U0001f600'],
            rational=['0x2', '0x4'], dyadic=['-0x1', hex(1 << 81)], ident='d' * 64)
        value = {'rows': [row] * 160}
        expected = T.canonical(value)
        record = self.pack(value)
        with record.root() as root, root.field('rows') as rows, rows.at(0) as first:
            row_index = first.index
        # The repeated row is constructed once (R1: rendered from the columns
        # by _rendered, or streamed by _uncached_parts), then reused.
        with patch.object(record, '_uncached_parts', wraps=record._uncached_parts) as uncached, \
                patch.object(record, '_rendered', wraps=record._rendered) as rendered:
            self.assertEqual(streamed(record, 97), expected)
            self.assertEqual(sum(call.args[0] == row_index for call in
                                 uncached.call_args_list+rendered.call_args_list), 1)
        self.assertEqual(record.identity().sha256, sha256(expected).hexdigest())
        self.assertEqual(record.identity().canonical_bytes, len(expected))
        for enabled in (True, False):
            with self.subTest(use_page_cache=enabled), self.sealed(record, use_page_cache=enabled) as opened:
                restored, _, _ = opened
                self.assertEqual(streamed(restored, 97), expected)
                self.assertEqual(restored.identity(), record.identity())
        record.close()

    def test_unique_prefix_does_not_crowd_out_later_repeated_rows(self):
        row = {'repeated': 'late-' * 100, 'q': ['0x2', '0x4']}
        # R1: both arrays exceed one 64 KiB chunk, so their members (1,500 unique
        # strings, then the repeated row) are the memo's units on either route
        # (a parent within one chunk is rendered whole, without memo entries).
        value = {'a': [f'{i:08d}-' * 6 for i in range(1500)], 'z': [row] * 200}
        record = self.pack(value)
        with record.root() as root, root.field('z') as rows, rows.at(0) as first:
            index = first.index
        with patch.object(record, '_uncached_parts', wraps=record._uncached_parts) as uncached, \
                patch.object(record, '_rendered', wraps=record._rendered) as rendered:
            self.assertEqual(streamed(record, 65536), T.canonical(value))
            self.assertEqual(sum(call.args[0] == index for call in
                                 uncached.call_args_list+rendered.call_args_list), 1)
        record.close()

    def test_oversized_nodes_and_false_lengths_never_enter_memo(self):
        value = {'large': 'x' * (3 * T.CHUNK + 17),
                 'rows': [{'small': 'kept', 'q': ['0x2', '0x4']}] * 2048}
        record = self.pack(value)
        with record.root() as root, root.field('large') as large:
            oversized = {root.index, large.index}
        memo = V._CanonicalMemo(self.scope)
        self.assertIsNotNone(memo.owner)
        original = record._v

        def false_length(name, index):
            return 1 if name == 'node.length' and index in oversized else original(name, index)

        digest, total, largest = sha256(), 0, 0
        # Even an unvalidated length hint must not cause whole-node joining.
        with patch.object(record, '_v', side_effect=false_length):
            for part in record._parts(record._root, memo=memo):
                digest.update(part)
                total += len(part)
                largest = max(largest, len(part))
        self.assertEqual(digest.hexdigest(), record.identity().sha256)
        self.assertEqual(total, record.identity().canonical_bytes)
        self.assertLessEqual(largest, T.CHUNK)
        entries = memo.owner.value
        self.assertTrue(entries)
        self.assertTrue(oversized.isdisjoint(entries))
        self.assertLessEqual(len(entries), memo.MAX_ENTRIES)
        self.assertTrue(all(type(raw) is bytes and len(raw) <= T.CHUNK for raw in entries.values()))
        self.assertLessEqual(sum(len(raw) + 512 for raw in entries.values()) + 4096, memo.CAPACITY)
        del entries, memo
        record.close()

    def test_optional_memo_decline_preserves_required_stream(self):
        value = {'rows': [{'text': 'repeated', 'q': ['0x2', '0x4']}] * 32}
        record = self.pack(value)
        original = self.scope.reserve
        declined = []

        def optional_pressure(spec, **kwargs):
            if kwargs.get('required') is False:
                declined.append(spec.purpose)
                return None
            return original(spec, **kwargs)

        before = self.budget.reserved_bytes
        with patch.object(self.scope, 'reserve', side_effect=optional_pressure):
            self.assertEqual(streamed(record, 7), T.canonical(value))
        self.assertIn('record-canonical-reuse', declined)
        self.assertEqual(self.budget.reserved_bytes, before)
        record.close()

    def test_stream_rechecks_memory_cancellation_between_memo_slices(self):
        cancelled = False

        def check():
            if cancelled:
                raise CancelledError('next memo slice cancelled')

        record = self.pack({'text': 'x' * 1024}, check=check)
        stream = record.iter_json(max_chunk_bytes=7)
        with next(stream) as first:
            self.assertEqual(len(first.value), 7)
        cancelled = True
        with self.assertRaisesRegex(CancelledError, 'next memo slice'):
            next(stream)
        cancelled = False
        stream.close()
        del stream
        gc.collect()
        record.close()

    def test_sealed_stream_rechecks_mutation_and_cancellation_between_blocks(self):
        record = self.pack({'rows': [{'text': 'repeated'}] * 16})
        with self.sealed(record) as (restored, segment, stores):
            changed = False
            original = stores.assert_cached_read_safe

            def freshness(**kwargs):
                if changed:
                    raise ContractError('source changed between memo blocks')
                return original(**kwargs)

            with patch.object(stores, 'assert_cached_read_safe', side_effect=freshness):
                stream = restored.iter_json(max_chunk_bytes=7)
                with next(stream):
                    pass
                changed = True
                with self.assertRaisesRegex(ContractError, 'between memo blocks'):
                    next(stream)
                changed = False
                stream.close()
                del stream
                gc.collect()
            event = threading.Event()
            segment.cancel = event
            stream = restored.iter_json(max_chunk_bytes=7)
            with next(stream):
                pass
            event.set()
            with self.assertRaises(CancelledError):
                next(stream)
            event.clear()
            stream.close()
            del stream
            gc.collect()
        record.close()

    def test_escaped_block_and_failed_frame_keep_their_funding(self):
        cancelled = False

        def check():
            if cancelled:
                raise CancelledError('retain memo failure')

        record = self.pack({'rows': [{'text': 'kept'}] * 32}, check=check)
        before = self.budget.reserved_bytes
        original_memo = V._CanonicalMemo
        memo_refs = []

        def capture(scope):
            memo = original_memo(scope)
            memo_refs.append(weakref.ref(memo))
            return memo

        with patch.object(V, '_CanonicalMemo', side_effect=capture):
            stream = record.iter_json(max_chunk_bytes=7)
            escaped = next(stream)
            self.assertIsNotNone(memo_refs[-1]().owner)
            stream.close()
            del stream
            gc.collect()
            self.assertIsNone(memo_refs[-1]())
            self.assertGreater(self.budget.reserved_bytes, before)
            self.assertEqual(escaped.value, T.canonical({'rows': [{'text': 'kept'}] * 32})[:7])
            escaped.close()
            self.assertEqual(self.budget.reserved_bytes, before)

            stream = record.iter_json(max_chunk_bytes=7)
            with next(stream):
                pass
            cancelled = True
            failure = None
            try:
                next(stream)
            except CancelledError as error:
                failure = error
            self.assertIsNotNone(failure)
            stream.close()
            del stream
            gc.collect()
            self.assertIsNotNone(memo_refs[-1]())
            self.assertIsNotNone(memo_refs[-1]().owner.value)
            self.assertGreater(self.budget.reserved_bytes, before + original_memo.CAPACITY)
            failure.__traceback__ = None
            del failure
            gc.collect()
            self.assertIsNone(memo_refs[-1]())
            self.assertEqual(self.budget.reserved_bytes, before)
        cancelled = False
        record.close()

    def test_typed_pages_reuse_views_only_within_the_read_batch(self):
        for dtype in ('<u2', '<u4', '<u8', '<f8'):
            with self.subTest(dtype=dtype), tempfile.TemporaryDirectory(prefix='step7b-typed-') as directory:
                width = T.CHUNK // np.dtype(dtype).itemsize
                values = np.arange(width + 2, dtype=dtype)
                values[0] = -0.0 if dtype == '<f8' else np.iinfo(dtype).max
                stores = IntervalStoreSet.create_migration(Path(directory) / 'catalog.json',
                    workflow_id='a' * 64, scope=self.scope)
                candidate = stores.begin_interval(None, producer_identity='b' * 64,
                                                   runtime_identity='c' * 64)
                source = _TypedSource(self.scope, values)
                identity = LogicalIdentity('test.step7b.typed.v1', sha256(source.raw).hexdigest(), len(source.raw))
                backend = SegmentBackend()
                reference = backend.publish(candidate, record_schema=identity.record_schema, identity=identity,
                    metadata=b'{}', arrays=lambda: iter([source]), producer='b' * 64,
                    representation_profile='test.typed.v1', scope=self.scope)
                sealed = candidate.seal(reference)
                stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
                segment = backend.open(stores, reference, scope=self.scope)
                descriptor = dict(dtype=dtype, shape=[len(values)], sha256=identity.sha256)
                columns = V._Segment(segment, {'typed': descriptor})
                # Warm physical pages, then count only compound scalar dispatch.
                for index in (0, width):
                    columns.value('typed', index)
                original_frombuffer = np.frombuffer
                # R1: a pinned page's typed view is an exact memoryview cast
                # (V._BatchPage.view) where the host allows it, else frombuffer;
                # either way one view per pinned page per read batch.
                original_view, created = V._BatchPage.view, []

                def counting_view(page, code, created=created, original_view=original_view):
                    if page._view is None:
                        created.append(code)
                    return original_view(page, code)
                with patch.object(V.np, 'frombuffer', wraps=original_frombuffer) as decoded, \
                        patch.object(V._BatchPage, 'view', counting_view):
                    with columns.read_batch():
                        for index in (0, 1, width - 1, width, width + 1, 0):
                            actual = columns.value('typed', index)
                            self.assertEqual(actual, values[index].item())
                            if index == 0 and dtype == '<f8':
                                self.assertTrue(np.signbit(actual))
                    self.assertEqual(decoded.call_count+len(created), 2)
                    self.assertIsNone(columns._batch_pages)
                    with columns.read_batch():
                        self.assertEqual(columns.value('typed', 1), values[1].item())
                    self.assertEqual(decoded.call_count+len(created), 3)
                del columns
                segment.close()
                candidate.close()
                stores.close()


if __name__ == '__main__':
    unittest.main()
