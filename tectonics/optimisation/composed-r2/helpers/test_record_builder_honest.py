"""A1 builder repair evidence: honest booking, streaming spill, exactness edges.

Synthetic census-shaped UNIQUE inputs; tracemalloc measures memory only (nothing
is timed). Real <= booked <= 1.3 x real is asserted on the whole pack peak.
"""
import gc
from hashlib import sha256
import os
from pathlib import Path
import random
import sys
import tempfile
import tracemalloc
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'))

from atlas_tectonics.resources import MemoryLimitError, WorkBudget  # noqa: E402
from compact_contracts import ContractError  # noqa: E402
from content_cache import create_retained_scope  # noqa: E402
import record_tables as T  # noqa: E402
from record_views import CompactRecord  # noqa: E402


def hid(rng):
    return '%064x' % rng.getrandbits(256)


def census_graph(rng, cells):
    den = [hex(rng.getrandbits(300) | 1) for _ in range(300)]
    return {'cells': [{'cell_id': hid(rng), 'kind': 'kind-%d-%s' % (i, '%040x' % rng.getrandbits(160)),
                       'band': rng.randint(300, 10**6), 'voxel': [rng.randint(300, 10**6) for _ in range(3)],
                       'q': [hex(rng.getrandbits(rng.randint(48, 400)) | 1), rng.choice(den)],
                       'bounds': [[hex(rng.getrandbits(200) | 1), rng.choice(den)] for _ in range(2)],
                       'parent': None if i % 3 else hid(rng)} for i in range(cells)],
            'physical_measure_receipts': {hid(rng): None for _ in range(cells*4)}}


def streamed(record):
    parts = []
    with record.iter_json() as stream:
        for block in stream:
            with block:
                parts.append(block.value)
    return b''.join(parts)


class HonestBuilderTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(3 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='a1-builder-test')
        self.codec = T.RecordCodec()

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def pack(self, value, schema='test.a1.v1'):
        return self.codec.pack_record(value, record_schema=schema, scope=self.scope, check=lambda: None)

    def measured(self, value):
        """(booked run peak, traced peak) for one pack of a pre-built input."""
        budget = WorkBudget(2 << 30)
        scope = create_retained_scope(budget, process_epoch='a1-measure')
        base_reserved = budget.reserved_bytes
        gc.collect()
        tracemalloc.start()
        base = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
        record = self.codec.pack_record(value, record_schema='test.a1.v1', scope=scope, check=lambda: None)
        peak = tracemalloc.get_traced_memory()[1]-base
        tracemalloc.stop()
        booked = budget.peak_reserved_bytes-base_reserved
        identity = record.identity()
        record.close()
        del record
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)
        return booked, peak, identity

    def test_booked_within_honest_band_on_unique_census_shapes(self):
        rng = random.Random(20261015)
        cases = {'id_keys': {hid(rng): None for _ in range(12_000)},
                 'graph_rationals': census_graph(rng, 1500),
                 'transport_pairs': {'f%02d' % k: [[hex(rng.getrandbits(53) | 1), hex(1 << rng.randint(0, 60))]
                                                   for _ in range(2000)] for k in range(8)},
                 'wide_rationals': [[hex(rng.getrandbits(1_724_160) | 1), hex(rng.getrandbits(2_054_539) | 1)]
                                    for _ in range(8)]}
        for name, value in cases.items():
            with self.subTest(name):
                booked, peak, identity = self.measured(value)
                self.assertEqual(identity.sha256, sha256(T.canonical(value)).hexdigest())
                self.assertGreaterEqual(booked, peak, name)
                self.assertLessEqual(booked, 1.3*peak, name)

    def test_streamed_bodies_spill_and_files_close(self):
        rng = random.Random(4)
        value = {'bodies': [''.join(rng.choices('abcdef', k=12_000)) for _ in range(400)],
                 'magnitudes': [hex(rng.getrandbits(200_000) | 1) for _ in range(20)]}
        directory = tempfile.mkdtemp(dir=os.environ.get('TEMP'))
        old, T.SPILL_DIRECTORY = T.SPILL_DIRECTORY, directory
        try:
            builder = T._Builder(self.scope, lambda: None)
            root = builder.add(value)
            self.assertGreater(sum(s.flushed for s in builder._spills()), 5_000_000)
            # Resident state is the maps and one block per spill, not the 5.3 MB of bodies.
            self.assertLess(builder.work_budget.reserved_bytes, 2_000_000)
            record = builder.finish_record(root, 'test.a1.v1')
            builder.close()
            builder.release()
            self.assertEqual(os.listdir(directory), [])
            self.assertEqual(streamed(record), T.canonical(value))
            record.close()
        finally:
            T.SPILL_DIRECTORY = old
            os.rmdir(directory)

    def test_digest_hits_are_confirmed_against_spilled_bytes(self):
        long_a = 'q'*70_000
        long_b = 'q'*69_999+'r'
        big = (1 << 4000)+12345
        value = [long_a, long_b, long_a, {long_a[:100]: hex(big)}, hex(big), hex(-big), [hex(big), hex(big)],
                 'k'*49, 'k'*49]
        record = self.pack(value)
        self.assertEqual(streamed(record), T.canonical(value))
        with record.storage_payload() as held:
            metadata, arrays = held.value
            self.assertEqual(len(arrays['token.offset'])-1, 4)   # long_a, long_b, long_a[:100] key, k*49
            self.assertEqual(len(arrays['int.sign']), 2)          # big and -big
            restored = CompactRecord.from_payload(metadata, arrays, scope=self.scope, check=lambda: None)
            restored.close()
        record.close()

    def test_depth_128_round_trips_and_129_refuses_including_empty_leaf(self):
        for leaf in ([], {}, 1, ['0x1', '0x2']):
            for levels, ok in ((128, True), (129, False)):
                value = leaf
                for _ in range(levels-1 if isinstance(leaf, (list, dict)) else levels):
                    value = [value]
                with self.subTest(leaf=repr(leaf), levels=levels):
                    if ok:
                        record = self.pack(value)
                        with record.storage_payload() as held:
                            restored = CompactRecord.from_payload(*held.value, scope=self.scope,
                                                                  check=lambda: None)
                            self.assertEqual(streamed(restored), T.canonical(value))
                            restored.close()
                        record.close()
                    else:
                        with self.assertRaisesRegex(ContractError, 'nesting exceeds bound'):
                            self.pack(value)

    def test_surrogate_pairs_held_as_two_code_points_refuse_at_pack(self):
        pair = chr(0xD83D)+chr(0xDE00)
        for value in ({pair: 1, chr(0x1F600): 2}, {pair+'x': 1}, pair, ['a'+pair], 'x'*70_000+pair,
                      {'k'*70+pair: 1}):
            with self.subTest(value=ascii(value)[:40]):
                with self.assertRaisesRegex(ContractError, 'round-trip'):
                    self.pack(value)
        # Lone, reversed or separated surrogates round-trip through JSON and stay accepted.
        for value in (chr(0xD800), chr(0xDE00)+chr(0xD83D), chr(0xD83D)+'z'+chr(0xDE00), {chr(0xDFFF): 1},
                      chr(0x1F600)):
            record = self.pack(value)
            self.assertEqual(streamed(record), T.canonical(value))
            record.close()

    def test_hex_magnitude_gate_falls_back_to_text_like_legacy(self):
        exact = '0x'+'f'*2_097_152                 # exactly 1 MiB of magnitude
        over = '0x1'+'0'*2_097_152                 # 2,097,153 digits: one bit over
        for value, kind in ((exact, T.HEX), (over, T.TEXT), ('-'+over, T.TEXT)):
            record = self.pack([value])
            with record.storage_payload() as held:
                arrays = held.value[1]
                self.assertIn(kind, set(arrays['node.kind'].tolist()))
            self.assertEqual(record.identity().sha256, sha256(T.canonical([value])).hexdigest())
            record.close()

    def test_incremental_builder_refuses_unreachable_appends_and_reuses_large_nodes(self):
        builder = T.RecordBuilder(scope=self.scope)
        builder.append({'orphan': 'row'}, record_schema='test.row.v1')
        used = builder.append({'used': 1}, record_schema='test.row.v1')
        with self.assertRaisesRegex(ContractError, 'final root does not reach'):
            builder.finish(dict(rows=[used]), record_schema='test.root.v1')
        builder.close()
        # A large scalar no longer makes every later built-node reuse refuse.
        builder = T.RecordBuilder(scope=self.scope)
        wide = hex((1 << 8_388_000)+5)
        first = builder.append([wide, '0x3'], record_schema='test.row.v1')
        second = builder.append({'small': 1}, record_schema='test.row.v1')
        record = builder.finish({'a': first, 'b': second, 'c': [second, first]}, record_schema='test.root.v1')
        expected = T.canonical({'a': [wide, '0x3'], 'b': {'small': 1}, 'c': [{'small': 1}, [wide, '0x3']]})
        self.assertEqual(record.identity().sha256, sha256(expected).hexdigest())
        record.close()
        del first, second

    def test_cancel_and_failure_frame_keep_funding_until_released(self):
        from concurrent.futures import CancelledError
        baseline = self.budget.reserved_bytes
        calls = 0

        def check():
            nonlocal calls
            calls += 1
            if calls == 5000:
                raise CancelledError('held failure')
        rng = random.Random(8)
        retained = self.scope.stats().retained_bytes
        error = None
        try:
            self.codec.pack_record(census_graph(rng, 300), record_schema='test.v1', scope=self.scope, check=check)
        except CancelledError as caught:
            error = caught
        self.assertIsNotNone(error)
        self.assertEqual(self.scope.stats().retained_bytes, retained)   # no partial record
        held = self.budget.reserved_bytes
        self.assertGreater(held, baseline)
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, held)
        error.__traceback__ = None
        del error
        self.assertEqual(self.budget.reserved_bytes, baseline)

    def test_retained_scope_refusal_points_to_segment_publication(self):
        budget = WorkBudget(4 << 20)
        scope = create_retained_scope(budget, process_epoch='a1-small')
        value = [hex((1 << (8*(1 << 19)))-1-i) for i in range(10)]   # about 5.2 MB of magnitude columns
        with self.assertRaisesRegex(MemoryLimitError, 'segments'):
            self.codec.pack_record(value, record_schema='test.v1', scope=scope, check=lambda: None)
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
