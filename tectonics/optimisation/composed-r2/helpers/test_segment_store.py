"""Real-limit synthetic segment/store-set integration; no historical data."""
from concurrent.futures import CancelledError
import gc
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import weakref

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
RUNTIME = HERE.parents[1] / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(RUNTIME), str(HERE.parent)]

from atlas_tectonics.resources import WorkBudget
from compact_contracts import BindingIndexRef, ContractError, LogicalIdentity, SegmentRef, SnapshotLocator
from content_cache import ChargeSpec, OwnedStream, create_retained_scope
from interval_store_set import IntervalStoreSet
import segment_store as S

MEASUREMENTS = {}


class GeneratedSource:
    def __init__(self, scope, size, *, name='payload', changed_last=False, dtype='|u1'):
        self.scope, self.changed_last = scope, changed_last
        self.info = S.ArrayInfo(name, dtype, (size,), size)

    def block(self, index, size):
        # Distinct whole native chunks: tests do not replace a 600 MiB record
        # with one scalar or one repeated-content leaf.
        token = (index + (1000000 if self.changed_last else 0)).to_bytes(8, 'little')
        return (token * ((size + 7) // 8))[:size]

    def blocks(self, *, max_owned_bytes):
        def generate():
            for start in range(0, self.info.logical_bytes, max_owned_bytes):
                size = min(max_owned_bytes, self.info.logical_bytes - start)
                index = start // S.NATIVE_CHUNK_BYTES
                reservation = self.scope.reserve(ChargeSpec('generated-input', size))
                if self.changed_last and start + size != self.info.logical_bytes:
                    token = index.to_bytes(8, 'little')
                    value = (token * ((size + 7) // 8))[:size]
                else:
                    value = self.block(index, size)
                yield reservation.commit(value)
        return OwnedStream(generate(), scope=self.scope)


class SegmentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='step4-segment-', dir=TASK / '_t')
        self.path = Path(self.temp.name)
        self.assertTrue(self.path.resolve().is_relative_to((TASK / '_t').resolve()))
        self.budget = WorkBudget(512 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='segment-fixture')
        self.stores = IntervalStoreSet.create_migration(self.path / 'catalog.json', workflow_id='a' * 64,
                                                       scope=self.scope)
        self.candidate = self.stores.begin_interval(None, producer_identity='b' * 64, runtime_identity='c' * 64)
        self.backend = S.SegmentBackend()
        self.views = []

    def tearDown(self):
        for view in self.views:
            view.close()
        self.candidate.close()
        self.stores.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temp.cleanup()

    def publish(self, sources, *, name='logical', candidate=None, metadata=b'{}', cancel=None):
        identity = LogicalIdentity('fixture.record.v1', sha256(name.encode()).hexdigest(), 99)
        return self.backend.publish(candidate or self.candidate, record_schema=identity.record_schema,
            identity=identity, metadata=metadata, arrays=lambda: iter(sources), producer='b' * 64,
            representation_profile='fixture.columns.v1', scope=self.scope, cancel=cancel)

    def open(self, ref, resolver=None):
        view = self.backend.open(resolver or self.candidate, ref, scope=self.scope)
        self.views.append(view)
        return view

    def promote(self, ref):
        sealed = self.candidate.seal(ref)
        self.stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)

    def test_info_retains_escaped_view_without_reciprocal_cycle(self):
        ref = self.publish([GeneratedSource(self.scope, 64)])
        before = self.scope.stats().purpose_bytes.get('retained:segment-metadata', 0)
        view = self.backend.open(self.candidate, ref, scope=self.scope)
        reference = weakref.ref(view)
        first, second = view.info, view.info
        self.assertEqual(first.ref, second.ref)
        self.assertEqual(first.array_count, second.array_count)
        with first.array('payload') as left, second.array('payload') as right:
            self.assertEqual(left.value, right.value)
        del view
        self.assertIsNotNone(reference())
        self.assertGreater(self.scope.stats().purpose_bytes['retained:segment-metadata'], before)
        descriptor = first.array('payload')
        self.assertEqual(descriptor.value.shape, (64,))
        del first, second
        self.assertIsNone(reference())
        # The escaped bounded descriptor still funds its metadata dependency.
        self.assertGreater(self.scope.stats().purpose_bytes['retained:segment-metadata'], before)
        descriptor.close()
        self.assertEqual(self.scope.stats().purpose_bytes['retained:segment-metadata'], before)
        view = self.backend.open(self.candidate, ref, scope=self.scope)
        reference = weakref.ref(view)
        del view
        self.assertIsNone(reference())
        self.assertEqual(self.scope.stats().purpose_bytes['retained:segment-metadata'], before)

    def test_publish_range_verify_and_find_before_factory(self):
        source = GeneratedSource(self.scope, 3 * 65536 + 13)
        ref = self.publish([source])
        view = self.open(ref)
        with patch.object(self.candidate, 'resolve_chunk', wraps=self.candidate.resolve_chunk) as read:
            block = view.read('payload', 65530, 65549, max_owned_bytes=19)
            self.assertEqual(block.value, source.block(0, 65536)[65530:] + source.block(1, 65536)[:13])
            self.assertEqual(read.call_count, 2)
            with self.assertRaises(RuntimeError):
                view.close()
            block.close()
        with patch.object(self.candidate, 'resolve_chunk', side_effect=AssertionError('manifest verification decoded payload')):
            evidence = self.backend.verify(self.candidate, ref, scope=self.scope)
            self.assertTrue(evidence.manifests_verified)
            self.assertFalse(evidence.payloads_verified or evidence.full_file_sha256_verified or evidence.logical_body_verified)
        before = self.candidate.local_statistics()
        with patch.object(self.candidate, 'put_chunk', side_effect=AssertionError('repeat staged')):
            again = self.backend.publish(self.candidate, record_schema=ref.identity.record_schema, identity=ref.identity,
                metadata=b'{}', arrays=lambda: (_ for _ in ()).throw(AssertionError('repeat encoded')),
                producer='b' * 64, representation_profile='fixture.columns.v1', scope=self.scope)
        self.assertEqual(again, ref)
        self.assertEqual(before, self.candidate.local_statistics())

    def test_compound_read_checks_before_after_and_keeps_cancellation_and_pin(self):
        ref = self.publish([GeneratedSource(self.scope, 64)])
        self.promote(ref)
        view = self.open(ref, self.stores)
        original = self.stores.assert_cached_read_safe
        with patch.object(self.stores, 'assert_cached_read_safe', wraps=original) as check:
            with view.verified_read():
                for _ in range(20):
                    view.check_unchanged()
                with view.verified_read():
                    view.check_unchanged()
                with self.assertRaises(RuntimeError):
                    view.close()
            self.assertEqual(check.call_count, 2)
        changed = False
        def fresh(**kwargs):
            if changed:
                raise ContractError('compound source changed')
            original(**kwargs)
        with patch.object(self.stores, 'assert_cached_read_safe', side_effect=fresh):
            with self.assertRaisesRegex(ContractError, 'compound source changed'):
                with view.verified_read():
                    changed = True
        self.assertEqual(view._read_depth, 0)
        event = threading.Event()
        view.cancel = event
        with self.assertRaises(CancelledError):
            with view.verified_read():
                event.set()
                view.check_unchanged()
        self.assertEqual(view._read_depth, 0)
        event.clear()
        view.check_unchanged()

    def test_compound_read_serialises_other_thread_freshness(self):
        ref = self.publish([GeneratedSource(self.scope, 64)])
        self.promote(ref)
        view = self.open(ref, self.stores)
        started, finished = threading.Event(), threading.Event()
        def reader():
            started.set()
            view.check_unchanged()
            finished.set()
        with view.verified_read():
            thread = threading.Thread(target=reader)
            thread.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(finished.is_set())
        thread.join(2)
        self.assertTrue(finished.is_set())

    def test_ancestor_prefix_only_stages_changed_chunk_and_cold_read(self):
        first = self.publish([GeneratedSource(self.scope, 4 * 65536)], name='first')
        self.promote(first)
        parent = self.stores.head
        self.candidate = self.stores.begin_interval(parent, producer_identity='b' * 64, runtime_identity='c' * 64)
        source = GeneratedSource(self.scope, 4 * 65536, changed_last=True)
        second = self.publish([source], name='second')
        self.assertEqual(self.candidate.local_statistics()['local_chunks'], 1)
        self.promote(second)
        self.stores.close()
        self.stores = IntervalStoreSet.open_catalog(self.path / 'catalog.json', scope=self.scope)
        view = self.open(second, self.stores)
        got = view.read('payload', 3 * 65536, 4 * 65536, max_owned_bytes=65536)
        self.assertEqual(got.value, source.block(3, 65536))
        got.close()
        entry = self.stores.head
        self.assertEqual(entry.interval, 1)
        self.assertEqual(len(entry.references), 1)

    def test_empty_and_fragmented_array_inventory(self):
        sources = [GeneratedSource(self.scope, i % 3, name='array-%04d' % i) for i in range(270)]
        ref = self.publish(sources)
        self.assertEqual(ref.array_bindings.count, 270)
        view = self.open(ref)
        empty = view.read('array-0000', 0, 0, max_owned_bytes=0)
        self.assertEqual(empty.value, b'')
        empty.close()
        one = view.read('array-0269', 0, 2, max_owned_bytes=2)
        self.assertEqual(one.value, b'\0\0')
        one.close()
        ref2 = self.publish([], name='empty-record')
        self.assertEqual(ref2.logical_bytes, 0)
        self.open(ref2)

    def test_explicit_bounds_schema_and_source_order_refuse(self):
        ref = self.publish([GeneratedSource(self.scope, 65536)])
        view = self.open(ref)
        with self.assertRaises(ContractError):
            view.read('payload', 0, 5, max_owned_bytes=4)
        with self.assertRaises(ContractError):
            view.read('payload', True, 1, max_owned_bytes=1)
        with self.assertRaises(ContractError):
            self.publish([GeneratedSource(self.scope, 2, name='b'), GeneratedSource(self.scope, 2, name='a')], name='bad-order')
        with self.assertRaises(ContractError):
            self.publish([GeneratedSource(self.scope, 1)], metadata=b'{ "not":"canonical" }', name='bad-meta')
        with self.assertRaises(ContractError):
            self.publish([GeneratedSource(self.scope, 1)], name='logical', metadata=b'{"changed":true}')

    def test_streamed_results_keep_view_pin_after_generator_closes(self):
        view = self.open(self.publish([GeneratedSource(self.scope, 65536)]))
        stream = view.iter('payload', block_bytes=1024, max_owned_bytes=1024)
        block = next(stream)
        stream.close()
        self.assertEqual(len(block.value), 1024)
        with self.assertRaises(RuntimeError):
            view.close()
        block.close()
        view.close()

    def test_cancelled_publish_has_no_root(self):
        event = threading.Event()
        source = GeneratedSource(self.scope, 65536)
        def factory():
            yield source
            event.set()
            yield GeneratedSource(self.scope, 65536, name='z')
        identity = LogicalIdentity('fixture.record.v1', 'd' * 64, 1)
        with self.assertRaises(CancelledError):
            self.backend.publish(self.candidate, record_schema=identity.record_schema, identity=identity,
                metadata=b'{}', arrays=factory, producer='b' * 64,
                representation_profile='fixture.columns.v1', scope=self.scope, cancel=event)
        key = S.h(S.ROOT_SCHEMA, dict(identity=identity.to_wire(), producer='b' * 64,
                                     representation_profile='fixture.columns.v1'))
        self.assertIsNone(self.candidate.find_manifest(key))

    def test_tampered_index_is_refused_before_payload_read(self):
        ref = self.publish([GeneratedSource(self.scope, 65536 * 17)])
        original = self.candidate.resolve_manifest
        def tampered(locator, **kwargs):
            owned = original(locator, **kwargs)
            raw = json.loads(owned.value)
            page = raw['metadata']
            if page.get('schema') == S.PAGE_SCHEMA and page['kind'] == 'leaves':
                page['entries'][0]['content']['start'] = 1
                altered = S.canonical(raw)
                owned.close()
                return self.scope.reserve(ChargeSpec('tamper-fixture', len(altered))).commit(altered)
            return owned
        with patch.object(self.candidate, 'resolve_manifest', side_effect=tampered), \
             patch.object(self.candidate, 'resolve_chunk', side_effect=AssertionError('unexpected payload read')):
            with self.assertRaises(ContractError):
                self.backend.verify(self.candidate, ref, scope=self.scope)

    def test_authenticated_reordered_and_duplicate_ranges_refuse(self):
        original = self.publish([GeneratedSource(self.scope, 2 * 65536)])
        with self.candidate.resolve_manifest(original.array_bindings.root_key) as owned:
            leaves = json.loads(owned.value)['metadata']['entries']
        for mode in ('reordered', 'duplicate'):
            entries = json.loads(json.dumps(leaves))
            if mode == 'reordered':
                entries.reverse()
            else:
                entries[1] = json.loads(json.dumps(entries[0]))
            builder = S._IndexBuilder(self.candidate, self.scope, None)
            for i, entry in enumerate(entries):
                entry['content']['ordinal'] = i
                builder.add(entry)
            tree = builder.finish()
            identity = LogicalIdentity('fixture.record.v1', sha256(mode.encode()).hexdigest(), 99)
            preimage = dict(identity=identity.to_wire(), producer='b' * 64,
                            representation_profile='fixture.columns.v1')
            locator = SnapshotLocator(self.candidate.workflow_id, 0, S.h(S.ROOT_SCHEMA, preimage))
            ref = SegmentRef(S.SEGMENT_REF_SCHEMA, locator, identity, original.logical_bytes,
                BindingIndexRef(S.BINDING_INDEX_SCHEMA, SnapshotLocator.from_wire(tree['locator']),
                                tree['digest'], 1),
                S.h('atlas.segment-content.v1', dict(identity=identity.to_wire(), array_count=1,
                    logical_bytes=original.logical_bytes, tree_digest=tree['tree_digest'])))
            self.candidate.put_manifest(locator.snapshot_key, dict(schema=S.ROOT_SCHEMA, **preimage,
                metadata={}, reference=ref.to_wire(), index=tree))
            with patch.object(self.candidate, 'resolve_chunk', side_effect=AssertionError('payload touched')):
                with self.assertRaisesRegex(ContractError, 'gap or overlap'):
                    self.backend.verify(self.candidate, ref, scope=self.scope)

    def test_600_mib_record_at_real_native_limits(self):
        size = 600 << 20
        source = GeneratedSource(self.scope, size)
        ref = self.publish([source], name='600MiB')
        self.assertEqual(ref.logical_bytes, size)
        self.assertEqual(self.candidate.local_statistics()['local_chunks'], size // 65536)
        view = self.open(ref)
        block = view.read('payload', size - 17, size, max_owned_bytes=17)
        self.assertEqual(block.value, source.block(size // 65536 - 1, 65536)[-17:])
        block.close()
        self.assertLessEqual(self.budget.peak_reserved_bytes, 2 * (128 << 20) + 65536)
        MEASUREMENTS['segment_600_mib'] = {
            'logical_bytes': size, 'local_chunks': self.candidate.local_statistics()['local_chunks'],
            'peak_run_reserved_bytes': self.budget.peak_reserved_bytes,
            'peak_retained_bytes': self.scope.stats().peak_retained_bytes,
            'manifest_only_open': True, 'tail_read_bytes': 17}

    def test_codec_sealed_chain_fresh_process_roundtrip(self):
        from record_tables import RecordCodec
        payload = {'rows': [{'id': ('%064x' % i), 'q': {'n': '-0x2a', 'd': '0x100'},
                            'value': -0.0 if i == 0 else i, 'name': 'row '+str(i)}
                           for i in range(8)], 'text': 'unicode \U0001f9ed / '+('abc' * 24000)}
        for generation in range(2):
            payload['rows'][-1]['value'] = generation + 100
            expected = S.canonical(payload)
            packed = RecordCodec().pack_record(payload, record_schema='fixture.record.v1',
                scope=self.scope, check=lambda: None)
            with packed.metadata_bytes() as metadata:
                ref = self.backend.publish(self.candidate, record_schema=packed.identity().record_schema,
                    identity=packed.identity(), metadata=metadata.value, arrays=packed.array_sources,
                    producer='b' * 64, representation_profile='atlas.compact-record.v1', scope=self.scope)
            packed.close()
            self.promote(ref)
            if generation == 0:
                self.candidate = self.stores.begin_interval(self.stores.head,
                    producer_identity='b' * 64, runtime_identity='c' * 64)
        self.assertTrue(self.stores.head.references)
        self.stores.close()
        code = '''
import hashlib, json, sys, time
from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
from segment_store import SegmentBackend
from record_views import CompactRecord, _Segment
budget = WorkBudget(512 << 20)
scope = create_retained_scope(budget, process_epoch='fresh-codec-reader')
stores = IntervalStoreSet.open_catalog(sys.argv[1], scope=scope)
view = SegmentBackend().open(stores, stores.head.head, scope=scope)
started = time.perf_counter()
record = CompactRecord.from_segment(view)
reopen_seconds = time.perf_counter() - started
comparison = {}
baseline = None
for enabled in (False, True):
    scope.evict_unpinned(requested_bytes=64 << 20, category='pages')
    columns = _Segment(view, record._meta['arrays'], use_page_cache=enabled)
    calls = [0]
    original_read = view.read
    def counted(*args, **kwargs):
        calls[0] += 1
        return original_read(*args, **kwargs)
    view.read = counted
    tick = time.perf_counter()
    values = [columns.value('node.kind', 0) for _ in range(128)]
    elapsed = time.perf_counter() - tick
    view.read = original_read
    if baseline is None:
        baseline = values
    assert values == baseline
    comparison['enabled' if enabled else 'disabled'] = dict(seconds=elapsed, reads=calls[0])
assert comparison['disabled']['reads'] == 128 and comparison['enabled']['reads'] == 1
# _Segment has no close(): like CompactRecord.close(), which drops its own
# _Segment, the comparison reader's optional page-cursor registry is released
# when its last reference goes. Drop it before the scope must be empty.
cursors_before = budget.statistics()['categories'].get('retained:record-page-cursors', 0)
del columns
comparison['released_cursor_bytes'] = cursors_before - budget.statistics()['categories'].get(
    'retained:record-page-cursors', 0)
digest = hashlib.sha256()
length = 0
with record.iter_json(max_chunk_bytes=8192) as stream:
    for block in stream:
        with block:
            assert len(block.value) <= 8192
            digest.update(block.value)
            length += len(block.value)
identity = record.identity()
assert digest.hexdigest() == identity.sha256 and length == identity.canonical_bytes
record.close()
view.close()
stores.close()
scope.close()
assert budget.reserved_bytes == 0
print(json.dumps(dict(sha256=digest.hexdigest(), canonical_bytes=length,
                     reopen_seconds=reopen_seconds,
                     small_column_cache=comparison,
                     total_read_seconds=time.perf_counter()-started,
                     peak_run_reserved_bytes=budget.peak_reserved_bytes)))
'''
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(HERE), str(RUNTIME), str(HERE.parent))))
        child = subprocess.run([sys.executable, '-B', '-c', code, str(self.path / 'catalog.json')],
                               capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(child.returncode, 0, child.stderr)
        result = json.loads(child.stdout)
        self.assertEqual(result['sha256'], sha256(expected).hexdigest())
        self.assertEqual(result['canonical_bytes'], len(expected))
        MEASUREMENTS['codec_fresh_process'] = result


if __name__ == '__main__':
    unittest.main()
