"""Bounded sealed admission scan; synthetic data only, no timing benchmark."""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import threading
import traceback
import unittest
from unittest.mock import patch

import test_segment_store as fixture
from compact_contracts import ContractError, RETAINED_BYTES
from content_cache import ChargeSpec
import segment_store as S


MEASUREMENTS = {}


class Step7BSegmentTests(unittest.TestCase):
    # Reuse the established owner/interval fixture without inheriting its
    # unrelated large-record and codec timing tests into this focused suite.
    setUp = fixture.SegmentStoreTests.setUp
    tearDown = fixture.SegmentStoreTests.tearDown
    publish = fixture.SegmentStoreTests.publish
    open = fixture.SegmentStoreTests.open
    promote = fixture.SegmentStoreTests.promote

    def sealed(self, sources, *, name='logical'):
        ref = self.publish(sources, name=name)
        self.promote(ref)
        return self.open(ref, self.stores)

    def test_one_index_walk_exact_native_payloads_descriptors_and_empty_arrays(self):
        sizes = {'a-empty': 0, 'b-small': 5, 'c-payload': 17 * 65536 + 11}
        sources = {name: fixture.GeneratedSource(self.scope, size, name=name)
                   for name, size in sizes.items()}
        view = self.sealed(list(sources.values()))
        counts = dict.fromkeys(sources, 0)
        stops = dict.fromkeys(sources, 0)
        with patch.object(S, '_metadata', wraps=S._metadata) as metadata, \
             patch.object(self.stores, 'resolve_chunk', wraps=self.stores.resolve_chunk) as chunks, \
             patch.object(self.stores, 'assert_cached_read_safe',
                          wraps=self.stores.assert_cached_read_safe) as fresh:
            with view.scan(max_owned_bytes=65536) as stream:
                for block in stream:
                    with block:
                        value = block.value
                        source = sources[value.info.name]
                        self.assertEqual(value.info, source.info)
                        self.assertEqual(value.start, stops[value.info.name])
                        self.assertEqual(value.stop - value.start, len(value.data))
                        self.assertLessEqual(len(value.data), 65536)
                        expected = source.block(value.start // 65536, len(value.data))
                        self.assertEqual(value.data, expected)
                        counts[value.info.name] += 1
                        stops[value.info.name] = value.stop
            self.assertEqual(metadata.call_count, 3)  # two leaves, one branch
            self.assertEqual(chunks.call_count, 19)
            self.assertEqual(fresh.call_count, 2 * (sum(counts.values()) + 1))
            MEASUREMENTS['single_index_scan'] = dict(
                logical_bytes=sum(sizes.values()), blocks=sum(counts.values()),
                metadata_reads=metadata.call_count, chunk_reads=chunks.call_count,
                freshness_checks=fresh.call_count)
        self.assertEqual(counts, {'a-empty': 1, 'b-small': 1, 'c-payload': 18})
        self.assertEqual(stops, sizes)
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:segment-scan-block', 0), 0)
        self.assertLessEqual(self.scope.stats().peak_retained_bytes, RETAINED_BYTES)

    def test_escaped_block_funds_immutable_descriptor_and_payload_after_stream_close(self):
        view = self.sealed([fixture.GeneratedSource(self.scope, 65537)])
        metadata_before = self.scope.stats().purpose_bytes['retained:segment-metadata']
        stream = view.scan(max_owned_bytes=65536)
        block = next(stream)
        stream.close()
        with self.assertRaises(FrozenInstanceError):
            block.value.info.name = 'changed'
        with self.assertRaises(FrozenInstanceError):
            block.value.start = 1
        self.assertEqual(block.value.data, bytes(65536))
        self.assertEqual(self.scope.stats().purpose_bytes['retained:segment-metadata'], metadata_before)
        self.assertGreater(self.scope.stats().purpose_bytes['retained:segment-scan-block'], 65536)
        with self.assertRaises(RuntimeError):
            view.close()
        block.close()
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:segment-scan-block', 0), 0)
        view.close()

    def test_candidate_and_small_allowance_refuse_without_payload_reads(self):
        ref = self.publish([fixture.GeneratedSource(self.scope, 8)])
        candidate_view = self.open(ref)
        with self.assertRaisesRegex(ContractError, 'candidate'):
            candidate_view.scan(max_owned_bytes=65536)
        self.promote(ref)
        view = self.open(ref, self.stores)
        with patch.object(self.stores, 'resolve_chunk', side_effect=AssertionError('payload touched')):
            with self.assertRaisesRegex(ContractError, 'allowance'):
                view.scan(max_owned_bytes=65535)
            with self.assertRaises(ContractError):
                view.scan(max_owned_bytes=True)

    def test_cancelled_next_and_changed_source_between_yields_refuse(self):
        view = self.sealed([fixture.GeneratedSource(self.scope, 65537)])
        event = threading.Event()
        view.cancel = event
        stream = view.scan(max_owned_bytes=65536)
        next(stream).close()
        event.set()
        with self.assertRaises(CancelledError):
            next(stream)
        event.clear()
        stream.close()
        del stream

        stream = view.scan(max_owned_bytes=65536)
        next(stream).close()
        sidecar = Path(str(self.path / self.stores.head.filename) + '-journal')
        sidecar.write_bytes(b'synthetic change between yielded blocks')
        try:
            with patch.object(self.stores, 'resolve_chunk', side_effect=AssertionError('payload touched')):
                with self.assertRaisesRegex(ContractError, 'sidecar'):
                    next(stream)
        finally:
            sidecar.unlink()
            stream.close()

    def test_post_read_failure_withholds_block_and_keeps_failed_frame_paid(self):
        view = self.sealed([fixture.GeneratedSource(self.scope, 64)])
        original = self.stores.assert_cached_read_safe
        calls = 0

        def freshness(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ContractError('changed after scan payload read')
            original(**kwargs)

        failure = None
        stream = view.scan(max_owned_bytes=65536)
        with patch.object(self.stores, 'assert_cached_read_safe', side_effect=freshness):
            try:
                next(stream)
            except ContractError as exc:
                failure = exc
            else:
                self.fail('block escaped its final freshness check')
        self.assertIsNotNone(failure)
        self.assertIn('changed after', str(failure))
        self.assertGreater(self.scope.stats().purpose_bytes['retained:segment-scan-block'], 0)
        self.assertEqual(view._read_depth, 0)
        stream.close()
        self.assertGreater(self.scope.stats().purpose_bytes['retained:segment-scan-block'], 0)
        # Explicitly release the held diagnostic, rather than invoking GC to
        # hide a producer ownership leak in this focused check.
        traceback.clear_frames(failure.__traceback__)
        failure.__traceback__ = None
        del failure, stream
        self.assertEqual(self.scope.stats().purpose_bytes.get('retained:segment-scan-block', 0), 0)

    def test_scan_authenticates_metadata_before_any_payload(self):
        view = self.sealed([fixture.GeneratedSource(self.scope, 64)])
        original = self.stores.resolve_manifest

        def tampered(*args, **kwargs):
            owned = original(*args, **kwargs)
            native = json.loads(owned.value)
            page = native['metadata']
            if page.get('schema') == S.PAGE_SCHEMA:
                page['entries'][0]['content']['start'] = 1
                altered = S.canonical(native)
                owned.close()
                return self.scope.reserve(ChargeSpec('scan-tamper-fixture', len(altered))).commit(altered)
            return owned

        with patch.object(self.stores, 'resolve_manifest', side_effect=tampered), \
             patch.object(self.stores, 'resolve_chunk', side_effect=AssertionError('payload touched')):
            with self.assertRaisesRegex(ContractError, 'digest mismatch'):
                next(view.scan(max_owned_bytes=65536))

    def test_empty_segment_and_scan_under_shared_retained_pressure(self):
        empty = self.sealed([])
        with patch.object(self.stores, 'resolve_chunk', side_effect=AssertionError('payload touched')):
            with empty.scan(max_owned_bytes=65536) as stream:
                self.assertEqual(list(stream), [])
        self.candidate = self.stores.begin_interval(self.stores.head,
            producer_identity='b' * 64, runtime_identity='c' * 64)
        view = self.sealed([fixture.GeneratedSource(self.scope, 2 * 65536)], name='pressure')
        remaining = RETAINED_BYTES - self.scope.stats().retained_bytes - (2 << 20)
        with self.scope.reserve(ChargeSpec('scan-pressure-fixture', remaining - 4096)) as reserve:
            pressure = reserve.commit(None)
        with pressure:
            with view.scan(max_owned_bytes=65536) as stream:
                for block in stream:
                    block.close()
            self.assertLessEqual(self.scope.stats().peak_retained_bytes, RETAINED_BYTES)
            MEASUREMENTS['retained_pressure'] = dict(
                peak_retained_bytes=self.scope.stats().peak_retained_bytes,
                ceiling_bytes=RETAINED_BYTES)


if __name__ == '__main__':
    unittest.main()
