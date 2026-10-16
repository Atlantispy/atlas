"""Real bounded segment integration and hostile descriptor/ownership fixtures."""
from copy import deepcopy
from dataclasses import replace
import gc
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'))

from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError, LogicalIdentity
from content_cache import ChargeSpec, create_retained_scope
from interval_store_set import IntervalStoreSet
from segment_store import SegmentBackend
import record_tables as T
from record_views import CompactRecord, _Segment, _column_key, _verify_column_page
from test_record_tables import streamed


class RecordViewsTests(unittest.TestCase):
    def test_closed_record_drops_actual_arrays_and_failed_close_keeps_them(self):
        budget = WorkBudget(16 << 20)
        scope = create_retained_scope(budget, process_epoch='closed-record-backing')
        packed = T.RecordCodec().pack_record({'rows': list(range(100))},
            record_schema='test.v1', scope=scope, check=lambda: None)
        array_ref = weakref.ref(packed._columns.arrays['node.kind'])
        root = packed.root()
        before = budget.reserved_bytes
        with self.assertRaises(RuntimeError):
            packed.close()
        self.assertIsNotNone(array_ref())
        self.assertIsNotNone(packed._meta)
        self.assertEqual(budget.reserved_bytes, before)
        root.close()
        with self.assertRaises(RuntimeError):
            root.scalar(max_owned_bytes=16384)
        packed.close()
        # Keep the closed public record alive: its Python reachability must not
        # keep a second uncharged reference to the actual immutable array.
        closed_records = [packed]
        gc.collect()
        self.assertIsNone(array_ref())
        self.assertIsNone(closed_records[0]._columns)
        self.assertIsNone(closed_records[0]._meta)
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_paid_column_cache_parity_eviction_mutation_and_pressure(self):
        import numpy as np
        budget = WorkBudget(4 << 20)
        scope = create_retained_scope(budget, process_epoch='column-cache-test')
        values = np.arange(8192, dtype='<u8')
        descriptor = dict(dtype='<u8', shape=[8192], sha256=sha256(values.tobytes()).hexdigest())
        class Source:
            cancel = None
            def __init__(self):
                self.scope, self.reads, self.changed = scope, [], False
                self.info = SimpleNamespace(ref=SimpleNamespace(to_wire=lambda: {'fixture': 'column-cache'}))
            def cache_identity(self):
                return b'i'*32
            def check_unchanged(self):
                if self.changed:
                    raise ContractError('immutable file changed')
            def read(self, name, start, stop, *, max_owned_bytes):
                self.check_unchanged()
                self.reads.append((start, stop))
                with scope.reserve(ChargeSpec('fixture-column', 8*(stop-start))) as reservation:
                    return reservation.commit(values[start:stop].tobytes())
        source = Source()
        off = _Segment(source, {'data': descriptor}, use_page_cache=False)
        at = perf_counter(); expected = [off.value('data', i) for i in range(128)]
        off_seconds, off_reads = perf_counter()-at, len(source.reads)
        source.reads.clear()
        on = _Segment(source, {'data': descriptor})
        at = perf_counter(); observed = [on.value('data', i) for i in range(128)]
        on_seconds, on_reads = perf_counter()-at, len(source.reads)
        self.assertEqual(observed, expected)
        self.assertEqual((off_reads, on_reads), (128, 1))
        self.assertGreater(scope.stats().category_bytes['pages'], 65536)
        self.assertEqual(_Segment(source, {'data': descriptor}).cache, on.cache)
        source.changed = True
        with self.assertRaisesRegex(ContractError, 'immutable file'):
            on.value('data', 0)
        source.changed = False
        self.assertGreater(scope.evict_unpinned(requested_bytes=65536, category='pages'), 0)
        source.reads.clear()
        # Leave room for a paid 8-byte read, but not the optional whole column.
        room = budget.available_bytes
        filler = budget.reserve(room-32768)
        filler.__enter__()
        self.assertEqual(on.value('data', 7), 7)
        self.assertEqual(source.reads, [(7, 8)])
        filler.__exit__(None, None, None)
        # A changed body must fail its authenticated digest; only admission
        # shortage is eligible for fallback, never this integrity failure.
        values[0] = 99
        with self.assertRaisesRegex(ContractError, 'verification|verify|binding'):
            on.value('data', 0)
        print(json.dumps(dict(column_cache_fixture='owned in-memory source; not disk timing',
            off_reads=off_reads, on_reads=on_reads, off_seconds=off_seconds, on_seconds=on_seconds), sort_keys=True))
        del on, off
        gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_long_decoded_keys_keep_their_workspace_until_last_reference(self):
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='record-key-lifetime')
        keys = [prefix+'x'*32768 for prefix in ('a', 'b', 'c', 'd', 'e')]
        packed = T.RecordCodec().pack_record(dict.fromkeys(keys, 1), record_schema='test.v1',
                                             scope=scope, check=lambda: None)
        original_scratch, original_token = T.Scratch, CompactRecord._token
        latest, released_live_keys = [], []
        class TrackedText(str):
            pass
        class CheckedScratch(original_scratch):
            def __init__(self, owner_budget, count):
                super().__init__(owner_budget, count)
                self.key_refs = []
                latest[:] = [self]
            def __del__(self):
                if any(ref() is not None for ref in getattr(self, 'key_refs', ())):
                    released_live_keys.append(True)
                super().__del__()
        def token(view, index):
            text = TrackedText(original_token(view, index))
            latest[-1].key_refs.append(weakref.ref(text))
            return text
        with packed.storage_payload() as held:
            with patch.object(T, 'Scratch', CheckedScratch), patch.object(CompactRecord, '_token', token):
                restored = CompactRecord.from_payload(*held.value, scope=scope, check=lambda: None)
                root = restored.root()
                for name in (keys[0], keys[-1]):
                    child = root.field(name)
                    child.close()
                root.close(); restored.close()
                latest.clear()
                gc.collect()
        self.assertFalse(released_live_keys, 'decoded key survived its workspace reservation')
        packed.close(); gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_cached_raw_slices_are_paid_fresh_and_fall_back_under_pressure(self):
        budget = WorkBudget(4 << 20)
        scope = create_retained_scope(budget, process_epoch='raw-column-cache')
        raw = b'0123456789abcdef'*4096
        descriptor = dict(dtype='|u1', shape=[len(raw)], sha256=sha256(raw).hexdigest())
        class Source:
            cancel = None
            def __init__(self):
                self.scope, self.reads, self.changed = scope, [], False
                self.info = SimpleNamespace(ref=SimpleNamespace(to_wire=lambda: {'fixture': 'raw-cache'}))
            def cache_identity(self):
                return b'r'*32
            def check_unchanged(self):
                if self.changed:
                    raise ContractError('immutable raw source changed')
            def read(self, name, start, stop, *, max_owned_bytes):
                self.check_unchanged()
                self.reads.append((start, stop))
                with scope.reserve(ChargeSpec('raw-source', stop-start)) as reservation:
                    return reservation.commit(raw[start:stop])
        source = Source()
        columns = _Segment(source, {'token.bytes': descriptor})
        for i in range(16):
            with columns.raw('token.bytes', i, i+17) as held:
                self.assertEqual(held.value, raw[i:i+17])
        self.assertEqual(source.reads, [(0, len(raw))])
        escaped = columns.raw('token.bytes', 9, 30)
        self.assertGreater(scope.evict_unpinned(requested_bytes=len(raw), category='pages'), 0)
        self.assertEqual(escaped.value, raw[9:30])
        escaped.close()
        source.reads.clear()
        filler = budget.reserve(budget.available_bytes-12000)
        filler.__enter__()
        with columns.raw('token.bytes', 7, 10) as held:
            self.assertEqual(held.value, raw[7:10])
        self.assertEqual(source.reads, [(7, 10)])
        filler.__exit__(None, None, None)
        source.changed = True
        with self.assertRaisesRegex(ContractError, 'immutable raw'):
            columns.raw('token.bytes', 0, 1)
        del columns
        gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_large_column_native_chunk_pages_are_authenticated_and_bounded(self):
        from test_segment_store import GeneratedSource
        budget = WorkBudget(64 << 20)
        scope = create_retained_scope(budget, process_epoch='native-chunk-pages')
        with tempfile.TemporaryDirectory(prefix='wp3-chunk-pages-') as directory:
            stores = IntervalStoreSet.create_migration(Path(directory)/'catalog.json',
                workflow_id='a'*64, scope=scope)
            candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
            source = GeneratedSource(scope, 3*T.CHUNK+13)
            expected = b''.join(source.block(i, min(T.CHUNK, source.info.logical_bytes-i*T.CHUNK))
                                for i in range(4))
            identity = LogicalIdentity('test.chunk-pages.v1', sha256(expected).hexdigest(), len(expected))
            ref = SegmentBackend().publish(candidate, record_schema=identity.record_schema,
                identity=identity, metadata=b'{}', arrays=lambda: iter([source]),
                producer='b'*64, representation_profile='test.pages.v1', scope=scope)
            sealed = candidate.seal(ref)
            stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
            segment = SegmentBackend().open(stores, ref, scope=scope)
            descriptor = dict(dtype='|u1', shape=[len(expected)], sha256=identity.sha256)
            columns = _Segment(segment, {'payload': descriptor})
            with patch.object(segment, 'read', wraps=segment.read) as reads, \
                    patch.object(columns, '_bound_chunk', wraps=columns._bound_chunk) as fills, \
                    patch.object(segment, '_entries', wraps=segment._entries) as walks, \
                    patch.object(columns.cache, 'get', wraps=columns.cache.get) as cache_get:
                with columns.read_batch():
                    for i in range(20):
                        self.assertEqual(columns.value('payload', i), expected[i])
                        with columns.raw('payload', T.CHUNK-3, T.CHUNK+5) as held:
                            self.assertEqual(held.value, expected[T.CHUNK-3:T.CHUNK+5])
                # R1: each page miss is one authenticated walk (the binding
                # cursor) plus one verified read of the bound chunk; the second
                # walk through SegmentView.read is gone.
                self.assertEqual(reads.call_count, 0)
                self.assertEqual(fills.call_count, 2)
                self.assertEqual(walks.call_count, 2)
                self.assertEqual(cache_get.call_count, 2)
                self.assertIsNone(columns._batch_pages)
                self.assertTrue(all(call.args[3] <= T.CHUNK for call in fills.call_args_list))
            self.assertLess(scope.stats().category_bytes['pages'], 256 << 10)
            held, _, _ = columns._cached_native_owner('payload', 0, descriptor, __import__('numpy').dtype('|u1'))
            with held:
                page = held.value
                key = _column_key(scope.process_epoch, page.binding, page.expected_sha256, page.expected_bytes)
                self.assertTrue(_verify_column_page(key, page))
                self.assertFalse(_verify_column_page(key, replace(page, raw=b'x'+page.raw[1:])))
                self.assertFalse(_verify_column_page(key, replace(page, descriptor=b'{}')))
                self.assertFalse(_verify_column_page(key, replace(page, binding=page.binding+b'x')))
            scope.evict_unpinned(requested_bytes=1 << 20, category='pages')
            failure = registry = None
            try:
                with columns.read_batch():
                    columns.value('payload', 0)
                    registry = columns._batch_pages
                    raise RuntimeError('retained read failure')
            except RuntimeError as error:
                failure = error
            self.assertIsNone(columns._batch_pages)
            self.assertTrue(registry.value, 'failed frame lost its paid page borrows')
            self.assertEqual(next(iter(registry.value.values())).value.raw, expected[:T.CHUNK])
            del registry, failure
            gc.collect()
            original_reserve = scope.reserve
            def optional_pressure(spec, **kwargs):
                if kwargs.get('required') is False:
                    return None
                return original_reserve(spec, **kwargs)
            with columns.read_batch():
                columns.value('payload', 0)
                with patch.object(scope, 'reserve', side_effect=optional_pressure):
                    self.assertEqual(columns.value('payload', T.CHUNK+11), expected[T.CHUNK+11])
                    self.assertIsNone(columns._batch_pages, 'pressure fallback must release optional pins')
                    with columns.raw('payload', T.CHUNK-1, T.CHUNK+1) as held:
                        self.assertEqual(held.value, expected[T.CHUNK-1:T.CHUNK+1])
            for index in (-1, True, len(expected)):
                with self.assertRaisesRegex(ContractError, 'index outside'):
                    columns.value('payload', index)
            with patch.object(stores, 'assert_cached_read_safe', side_effect=ContractError('changed chunk file')):
                with self.assertRaisesRegex(ContractError, 'changed chunk file'):
                    columns.value('payload', 0)
            del columns, fills, walks    # the wrapping mocks hold bound methods of the views
            segment.close(); candidate.close(); stores.close()
        gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_real_native_segment_publish_and_bounded_reopen(self):
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='record-segment-test')
        with tempfile.TemporaryDirectory(prefix='wp2-segment-') as directory:
            stores = IntervalStoreSet.create_migration(str(Path(directory)/'catalog.json'),
                workflow_id='1'*64, scope=scope)
            candidate = stores.begin_interval(None, producer_identity='2'*64, runtime_identity='3'*64)
            value = {'cells': [{'id': sha256(str(i).encode()).hexdigest(), 'q': [hex(i), '0x8000000000000000000000'],
                               'unicode': 'é\ud800\U0001f600', 'signed_zero': -0.0} for i in range(8)]}
            packed = T.RecordCodec().pack_record(value, record_schema='test.persisted.v1', scope=scope, check=lambda: None)
            backend = SegmentBackend()
            with packed.metadata_bytes() as held:
                reference = backend.publish(candidate, record_schema='test.persisted.v1', identity=packed.identity(),
                    metadata=held.value, arrays=packed.array_sources, producer='2'*64,
                    representation_profile=T.SCHEMA, scope=scope)
            segment = backend.open(candidate, reference, scope=scope)
            requested = []
            read = segment.read
            def measured(name, start, stop, *, max_owned_bytes):
                requested.append((name, start, stop, max_owned_bytes))
                return read(name, start, stop, max_owned_bytes=max_owned_bytes)
            segment.read = measured
            restored = CompactRecord.from_segment(segment)
            self.assertEqual(streamed(restored), T.canonical(value))
            self.assertTrue(requested)
            self.assertTrue(all(stop-start <= 65536 for _, start, stop, _ in requested))
            with self.assertRaises(RuntimeError):
                segment.close()
            root = restored.root(); cells = root.field('cells'); cell = cells.at(7); q = cell.field('q'); num = q.at(0)
            with num.scalar(max_owned_bytes=16384) as held:
                self.assertEqual(held.value, '0x7')
            num.close(); q.close(); cell.close(); cells.close(); root.close()
            restored.close(); segment.close(); packed.close(); candidate.close(); stores.close()
            del restored, segment, packed, candidate, stores
        gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_child_length_charge_dtype_and_binary_mode_tampering(self):
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='record-tamper-test')
        packed = T.RecordCodec().pack_record({'text': 'x'*128, 'q': ['0x2', '0x1000000000000000000']},
            record_schema='test.v1', scope=scope, check=lambda: None)
        with packed.storage_payload() as held:
            metadata, arrays = held.value
            parsed = json.loads(metadata)
            cases = [('node.length', lambda a: a.__setitem__(0, 1)),
                     ('node.charge', lambda a: a.__setitem__(0, 0)),
                     ('int.mode', lambda a: a.__setitem__(-1, 3))]
            for name, mutate in cases:
                altered = dict(arrays); altered[name] = arrays[name].copy(); mutate(altered[name])
                header = deepcopy(parsed)
                header['arrays'][name]['sha256'] = sha256(altered[name].tobytes()).hexdigest()
                with self.assertRaises(ContractError):
                    CompactRecord.from_payload(T.canonical(header), altered, scope=scope, check=lambda: None)
            altered = dict(arrays); altered['node.payload'] = arrays['node.payload'].astype('<u8')
            header = deepcopy(parsed)
            header['arrays']['node.payload']['dtype'] = '<u8'
            header['arrays']['node.payload']['sha256'] = sha256(altered['node.payload'].tobytes()).hexdigest()
            with self.assertRaisesRegex(ContractError, 'narrowest'):
                CompactRecord.from_payload(T.canonical(header), altered, scope=scope, check=lambda: None)
        packed.close(); gc.collect(); scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
