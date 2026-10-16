"""Builder deduplication tables (W2 Decision 1, R1 W2-1) and D1 count bounds (Decision 2).

Fingerprint tables must give byte-identical records to the wave-1 dictionary
builder (w2ref_record_tables.py, a test-only byte copy of it), never merge on a
hashed fingerprint alone (exact short-key slots are equality), keep the paid
confirmed-entry caches and the re-emission memo exact and booked, book resizes
honestly (old and new arrays alive together, measured with tracemalloc only)
and keep every bound refusing exactly one past it.
"""
import gc
import importlib.util
import random
import sys
import tracemalloc
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'))

import record_tables as T
from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import create_retained_scope


def _base_module():
    spec = importlib.util.spec_from_file_location('w2ref_record_tables', HERE/'w2ref_record_tables.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules['w2ref_record_tables'] = module
    spec.loader.exec_module(module)
    return module


B = _base_module()


def hid(rng):
    return f'{rng.getrandbits(256):064x}'


def mixed_value(rng):
    """Every deduplicated pool, with repeats, near-misses and long bodies."""
    long_a = ''.join(rng.choice('abcdef') for _ in range(70_000))
    long_b = long_a[:-1]+'z'
    big = (1 << 4000)+12345
    ids = [hid(rng) for _ in range(40)]
    den = [hex(rng.getrandbits(300) | 1) for _ in range(7)]
    rows = [{'id': ids[i % 40], 'q': [hex(rng.getrandbits(90) | 1), den[i % 7]], 'n': i % 50,
             'w': 10**30+i % 9, 'f': (i % 5)/7, f'k{i % 13}': [i % 4, 'x'*(i % 60)]}
            for i in range(300)]
    return {'rows': rows, 'long': [long_a, long_b, long_a, {long_a[:100]: hex(big)}],
            'big': [hex(big), hex(-big), hex(big), big, -big, 1 << 900, 1 << 900, -(1 << 900)],
            'same': [[1, 2], [1, 2], [2, 1], {'a': [1, 2]}, {'a': [1, 2]}, {'b': [1, 2]}],
            'keys': {'k'*49: 1, 'k'*48: 2, 'k'*70: 3}, 'ids': ids+ids[:5]}


def columns(arrays):
    return {name: (a.dtype.str, tuple(a.shape), a.tobytes()) for name, a in arrays.items()}


class DedupTableTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(3 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='w2-dedup-test')

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def finish(self, module, value):
        builder = module._Builder(self.scope, lambda: None)
        root = builder.add(value)
        tables = {}
        if module is T:
            tables = {name: (table.confirms, table.rejects, table.anomalies) for name, table in
                      (('token', builder.token_index), ('integer', builder.integer_index),
                       ('id', builder.id_index), ('shape', builder.shape_index), ('node', builder.node_index))}
        raw, arrays = builder.finish(root, 'test.w2.v1')
        result = raw, columns(arrays)
        builder.close()
        builder.release()
        return result, tables

    def test_byte_identical_to_dictionary_builder(self):
        value = mixed_value(random.Random(11))
        expected, _ = self.finish(B, value)
        got, tables = self.finish(T, value)
        self.assertEqual(got, expected)
        self.assertEqual(sum(t[2] for t in tables.values()), 0)

    def test_forced_fingerprint_collisions_never_merge(self):
        value = mixed_value(random.Random(12))
        expected, _ = self.finish(B, value)
        for name, forced in (('constant', lambda key: 0), ('two', lambda key: hash(key) & 1)):
            with self.subTest(name), patch.object(T, '_fingerprint', forced):
                got, tables = self.finish(T, value)
                self.assertEqual(got, expected)
                # Different content met equal fingerprints in every hashed table
                # and was kept apart by the spill confirmation.
                for table, (confirms, rejects, _) in tables.items():
                    self.assertGreater(rejects, 0, table)
                    self.assertGreater(confirms, rejects, table)
        record = T.RecordCodec().pack_record(value, record_schema='test.w2.v1', scope=self.scope,
                                             check=lambda: None)
        self.assertEqual(record.identity().sha256, sha256(T.canonical(value)).hexdigest())
        record.close()

    def test_resize_booking_covers_old_and_new_arrays(self):
        live_budget = WorkBudget(1 << 30)
        live = T._Live(live_budget)
        gc.collect()
        tracemalloc.start()
        base = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
        booked_base = live_budget.reserved_bytes
        # The builder's fixed 8 KiB reserve covers interpreter transients (ints,
        # frames, ledger bookkeeping); the table books its arrays on top of it.
        live.take(8192)
        table = T._Table(live)
        peaks = []
        for index in range(400_000):
            if table.count == table.limit:
                # The next insert resizes: compare the peak across exactly this step.
                tracemalloc.reset_peak()
                before = live_budget.peak_reserved_bytes
                table.insert(T._fingerprint(index.to_bytes(4, 'little')), index)
                traced = tracemalloc.get_traced_memory()[1]-base
                peaks.append((live_budget.peak_reserved_bytes-booked_base, traced, before))
                continue
            table.insert(T._fingerprint(index.to_bytes(4, 'little')), index)
        tracemalloc.stop()
        self.assertEqual(table.anomalies, 0)
        self.assertEqual(table.count, 400_000)
        for booked, traced, _ in peaks[-4:]:
            self.assertGreaterEqual(booked, traced)
            self.assertLessEqual(booked, 1.3*traced)
        # Every entry is found again; an absent key is not.
        for index in range(0, 400_000, 997):
            fp = T._fingerprint(index.to_bytes(4, 'little'))
            self.assertEqual(table.find(fp, lambda found, index=index: found == index), index)
        self.assertIsNone(table.find(T._fingerprint(b'absent!'), lambda found: False))
        table.clear()
        live.close()
        self.assertEqual(live_budget.reserved_bytes, 0)

    def test_short_keys_are_exact_slots(self):
        # Bit 63 marks an exact short key; length is part of the code, so b'' and
        # b'\x00' differ; hashed keys never set bit 63.
        codes = [T._fingerprint(key) for key in (b'', b'\x00', b'\x00\x00', b'\x01', b'\xff'*7)]
        self.assertTrue(all(code >> 63 for code in codes))
        self.assertEqual(len(set(codes)), len(codes))
        for key in (b'\x00'*8, b'x'*33, bytes(range(64))):
            self.assertFalse(T._fingerprint(key) >> 63)
        live_budget = WorkBudget(1 << 26)
        live = T._Live(live_budget)
        table = T._Table(live)
        for index in range(5000):
            table.insert(T._fingerprint(index.to_bytes(3, 'little')), index)

        def never(index):
            raise AssertionError('an exact short slot needs no confirmation')
        for index in range(0, 5000, 7):
            self.assertEqual(table.find(T._fingerprint(index.to_bytes(3, 'little')), never), index)
        self.assertIsNone(table.find(T._fingerprint((6000).to_bytes(3, 'little')), never))
        self.assertEqual(table.confirms, 0)
        table.clear()
        live.close()
        self.assertEqual(live_budget.reserved_bytes, 0)

    def test_forced_hashed_collisions_keep_exact_short_slots(self):
        value = mixed_value(random.Random(14))
        expected, _ = self.finish(B, value)
        with patch.object(T, '_hashed', lambda key: 0):
            got, tables = self.finish(T, value)
        self.assertEqual(got, expected)
        for table in ('integer', 'id', 'node'):
            _, rejects, _ = tables[table]
            self.assertGreater(rejects, 0, table)

    def test_cached_confirmations_equal_the_spilled_entries(self):
        # Every cached entry is the entry's own content as read back from its spill,
        # and the paid caches change no decision even when constantly cleared.
        rng = random.Random(15)
        value = mixed_value(rng)
        expected, _ = self.finish(B, value)
        builder = T._Builder(self.scope, lambda: None)
        builder.add(value)
        builder.add(value)
        checked, hits = 0, {}
        try:
            for name, seen, content in (('token', builder.token_seen, builder._token_content),
                                        ('integer', builder.integer_seen, builder._integer_content),
                                        ('id', builder.id_seen, builder._id_content),
                                        ('shape', builder.shape_seen, builder._shape_content),
                                        ('node', builder.node_seen, builder._node_content)):
                hits[name] = seen.hits
                for key, index in seen.map.d.items():
                    self.assertEqual(content(index), key)
                    checked += 1
        finally:
            builder.close()
            builder.release()
        # Short strings are served by the exact key cache first, so tokens may have no hits.
        self.assertTrue(all(hits[name] for name in ('integer', 'id', 'shape', 'node')), hits)
        self.assertGreater(checked, 100)
        with patch.object(T, 'CONFIRM_CACHE_ENTRIES', 2), patch.object(T, '_hashed', lambda key: hash(key) & 7):
            got, _ = self.finish(T, value)
        self.assertEqual(got, expected)

    def _sequence(self, module, values, root, memo=None):
        """RecordBuilder: append values, finish with root(handles); returns bytes or the refusal."""
        builder = module.RecordBuilder(scope=self.scope)
        try:
            handles = [builder.append(v, record_schema='test.w2.row.v1') for v in values]
            ids = [h.identity for h in handles]
            inner = builder._builder
            record = builder.finish(root(handles), record_schema='test.w2.root.v1')
            if memo is not None:
                memo.append(inner.memo_hits)
            result = ('ok', record._owner.value[0], columns(record._owner.value[1]), ids)
            record.close()
            return result
        except ContractError as exc:
            return ('refused', str(exc))
        finally:
            builder.close()

    def test_reemission_memo_is_exact_and_keeps_the_depth_bound(self):
        rng = random.Random(16)
        rows = [{'cell': hid(rng), 'q': [hex(rng.getrandbits(80) | 1), '0x3'], 'shared': {'a': [1, 2, [3, 'x'*40]]}}
                for _ in range(30)]
        memo = []
        expected = self._sequence(B, rows, lambda h: {'rows': h, 'again': h, 'nested': [[h[0], h]]})
        got = self._sequence(T, rows, lambda h: {'rows': h, 'again': h, 'nested': [[h[0], h]]}, memo)
        self.assertEqual(got, expected)
        self.assertGreater(memo[0], 30)
        # A subtree with nesting need 120 (lists around a 2-level object): two shallow
        # references fill the memo, then a reference at depth+need = 128 is admitted
        # and at 129 refused, exactly as the dictionary builder decides.
        tower = {'leaf': ['0x5', '0x7'], 'n': 1}
        for _ in range(118):
            tower = [tower]

        def root(deep):
            def make(handles):
                nested = handles[0]
                for _ in range(deep-1):
                    nested = [nested]
                return [handles[0], handles[0], nested]
            return make
        for deep, outcome in ((8, 'ok'), (9, 'refused')):
            with self.subTest(deep=deep):
                memo = []
                expected = self._sequence(B, [tower], root(deep))
                got = self._sequence(T, [tower], root(deep), memo if outcome == 'ok' else None)
                self.assertEqual(got[0], outcome)
                self.assertEqual(got, expected)
                if outcome == 'ok':
                    self.assertGreaterEqual(memo[0], 2)
        with patch.object(T, 'MEMO_BYTES', 300), patch.object(T, 'MEMO_NODE_BYTES', 120):
            got = self._sequence(T, rows, lambda h: {'rows': h, 'again': h, 'nested': [[h[0], h]]})
        self.assertEqual(got, self._sequence(B, rows, lambda h: {'rows': h, 'again': h, 'nested': [[h[0], h]]}))

    def test_caches_and_memo_are_booked(self):
        # tracemalloc only (nothing timed): the paid caches and the memo are inside
        # the builder's booking during appends and the re-emitting finish.
        rng = random.Random(17)
        den = [hex(rng.getrandbits(120) | 1) for _ in range(40)]
        rows = [{'id': hid(rng), 'kind': f'k{i % 9}', 'n': i % 300, 'w': 10**20+i % 77,
                 'q': [hex(rng.getrandbits(100) | 1), den[i % 40]],
                 'shared': [{'a': j, 'b': [j, j+1, 'x'*(j % 50)]} for j in range(i % 25)]}
                for i in range(1500)]
        gc.collect()
        tracemalloc.start()
        base = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
        builder = T.RecordBuilder(scope=self.scope)
        inner = builder._builder
        handles = [builder.append(row, record_schema='test.w2.row.v1') for row in rows]
        traced_add = tracemalloc.get_traced_memory()[1]-base
        booked_add = inner.work_budget.peak_reserved_bytes
        inner.digest, inner.length = sha256(), 0
        root = inner.add({'rows': handles, 'again': handles[::3]})
        # After the re-emitting add the memo, caches and tables are all still held.
        traced_finish = tracemalloc.get_traced_memory()[0]-base
        booked_finish = inner.work_budget.reserved_bytes
        tracemalloc.stop()
        hits = (inner.memo_hits, inner.node_seen.hits, inner.integer_seen.hits, inner.shape_seen.hits)
        anomalies = sum(m.anomalies for m in (inner.key_cache, inner.spelling, inner.node_seen.map,
                                               inner.integer_seen.map, inner.id_seen.map))
        self.assertGreater(root, 0)
        builder.close()
        del handles
        self.assertTrue(all(hits), hits)
        self.assertEqual(anomalies, 0)
        self.assertGreaterEqual(booked_add, traced_add)
        self.assertLessEqual(booked_add, 1.3*traced_add)
        self.assertGreaterEqual(booked_finish, traced_finish)

    def test_reemission_scalar_workspace_is_booked(self):
        # tracemalloc only: re-emitting appended nodes with the widest scalar bodies
        # (1 MiB hex magnitude, 2,000,000-zero dyadic hex, multi-chunk text and key,
        # 4,000-digit and dyadic integers) stays inside what the builder books while
        # it emits them.
        rng = random.Random(18)
        rows = [['0x'+'f'*2097152], ['-0x1'+'0'*2000000], ['y'*200000], {'k'*70000: 'v'},
                [int('7'*4000)], [-(1 << 13000)], [hex(rng.getrandbits(4000) | 1), '0x3'],
                {'a': [1.5, None, True, hid(rng)], 'b': 'short'}]
        builder = T.RecordBuilder(scope=self.scope)
        inner = builder._builder
        handles = [builder.append(row, record_schema='test.w2.row.v1') for row in rows]
        root = {'rows': handles, 'again': handles[::-1]}
        # Booked = outstanding takes (lease minus free slack already held).
        live = inner.live
        peak = [0]
        take = live.take

        def tracked(size):
            take(size)
            peak[0] = max(peak[0], live.lease.count-live.free)
        live.take = tracked
        gc.collect()
        booked_base = peak[0] = live.lease.count-live.free
        tracemalloc.start()
        base = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
        inner.digest, inner.length = sha256(), 0
        inner.add(root)
        traced = tracemalloc.get_traced_memory()[1]-base
        tracemalloc.stop()
        booked = peak[0]-booked_base
        expected = sha256(T.canonical({'rows': rows, 'again': rows[::-1]})).hexdigest()
        self.assertEqual(inner.digest.hexdigest(), expected)
        builder.close()
        self.assertGreaterEqual(booked, traced)
        self.assertLessEqual(booked, 1.3*traced)

    def test_resident_cost_per_unique_node(self):
        rng = random.Random(13)
        den = [hex(rng.getrandbits(300) | 1) for _ in range(500)]
        value = {'cells': [{'cell_id': hid(rng), 'kind': f'kind-{i}-{rng.getrandbits(160):040x}',
                            'n': rng.randint(300, 10**9), 'q': [hex(rng.getrandbits(200) | 1), rng.choice(den)],
                            'nbr': [hid(rng) for _ in range(3)]} for i in range(12_000)]}
        builder = T._Builder(self.scope, lambda: None)
        start = builder.work_budget.reserved_bytes
        builder.add(value)
        resident = builder.work_budget.reserved_bytes-start
        # Wave-1 dictionaries held about 137-160 B per unique node.
        self.assertLess(resident/builder.n, 60)
        builder.close()
        builder.release()


class CountBoundTests(unittest.TestCase):
    """D1: each count bound admits exactly the bound and refuses one more."""
    def setUp(self):
        self.budget = WorkBudget(3 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='w2-bounds-test')

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def pack(self, value):
        record = T.RecordCodec().pack_record(value, record_schema='test.w2.v1', scope=self.scope,
                                             check=lambda: None)
        self.assertEqual(record.identity().sha256, sha256(T.canonical(value)).hexdigest())
        record.close()

    def refuses(self, value, message):
        with self.assertRaisesRegex(ContractError, message):
            self.pack(value)
        gc.collect()

    def test_derived_bounds_are_the_published_literals(self):
        self.assertEqual((T.MAX_ITEMS, T.MAX_EDGES, T.MAX_ROW_WORK_BYTES, T.MAX_BUILD_BYTES),
                         (4_000_000, 16_000_000, 32 << 20, 256 << 20))

    def test_node_count_bound(self):
        with patch.object(T, 'MAX_ITEMS', 1000), patch.object(T, 'MAX_EDGES', 4000):
            self.pack(list(range(300, 300+999)))                  # 999 integers + the list = 1000 nodes
            self.refuses(list(range(300, 300+1000)), 'node count exceeds bound')

    def test_token_pool_bound(self):
        with patch.object(T, 'MAX_ITEMS', 1000), patch.object(T, 'MAX_EDGES', 4000):
            keys = [f'key-{i:04d}' for i in range(1001)]
            self.pack([dict.fromkeys(keys[:500]), dict.fromkeys(keys[500:1000])])   # 1000 tokens
            self.refuses([dict.fromkeys(keys[:500]), dict.fromkeys(keys[500:1001])], 'token pool exceeds')

    def test_container_count_bound(self):
        with patch.object(T, 'MAX_ITEMS', 1000), patch.object(T, 'MAX_EDGES', 4000):
            self.pack([None]*1000)
            self.refuses([None]*1001, 'container count exceeds bound')

    def test_edge_count_bound(self):
        with patch.object(T, 'MAX_ITEMS', 1000), patch.object(T, 'MAX_EDGES', 4000):
            self.pack([[0]*1000, [1]*1000, [2]*1000, [3]*996])      # 3,996 + 4 root edges = 4,000
            self.refuses([[0]*1000, [1]*1000, [2]*1000, [3]*997], 'edge count exceeds bound')

    def test_row_workspace_bound(self):
        # Wide enough that the object row, not the fixed finish workspace, is the largest row.
        count = 40_000
        keys = [f'r{i:06d}' for i in range(count)]
        need = 3*(T._ARRAY_OBJECT+4*count)+T._BYTES_OBJECT+4*count+512   # the object row workspace
        with patch.object(T, 'MAX_ROW_WORK_BYTES', need):
            self.pack(dict.fromkeys(keys, 0))
        with patch.object(T, 'MAX_ROW_WORK_BYTES', need-1):
            self.refuses(dict.fromkeys(keys, 0), 'row workspace exceeds')

    def test_array_of_max_items_fits_the_real_row_workspace(self):
        # The largest admissible array row (MAX_ITEMS children) needs the
        # container dedup key and its confirmation read inside one row bound.
        count = T.MAX_ITEMS
        self.assertLessEqual(2*(T._BYTES_OBJECT+5+4*count), T.MAX_ROW_WORK_BYTES)
        self.assertLessEqual(T._ARRAY_OBJECT+4*count+256, T.MAX_ROW_WORK_BYTES)


if __name__ == '__main__':
    unittest.main()
