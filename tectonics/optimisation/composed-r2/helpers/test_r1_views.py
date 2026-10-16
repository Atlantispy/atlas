"""R1 record_views: the column renderer, column views and single-walk page fill change nothing.

Every comparison is against r1aref_record_views (the unmodified live origin,
12a468fe...), each module on its own records built from the same payload:
- canonical streams: identical block sequences (bytes AND block boundaries)
  for several chunk bounds, on memory and sealed segment backings;
- exports: identical values (types, key order, float signs) for the root and
  every node, small and large routes, ordinary and composite references;
- structural stats: equal to the origin's _decoded_stats, and the export
  charge (booking) equal to R1a's formula over them;
- accept/refuse: from_payload on hundreds of seeded single-column mutations
  (digest and metadata recomputed, so the structural/identity checks are what
  decides) gives the same outcome and message in both modules; the large
  route's key-inventory and cap refusals are the same;
- sealed reads: freshness and cancellation refusals unchanged.
Temporary files under R1V_TMP (default R/L/r1view from this file's location).
"""
import gc
import json
import math
import os
import random
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import CancelledError
from functools import partial
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'))
TMP = Path(os.environ.get('R1V_TMP', str(HERE.parent/'L'/'r1view')))
TMP.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TMP)

import r1aref_record_views as REF
import record_tables as T
import record_views as V
from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
from segment_store import SegmentBackend

T.SPILL_DIRECTORY = str(TMP)
BIG = 64 << 20


def same(a, b):
    """Exact value equality: types, key order and float signs."""
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    if type(a) is list:
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    if type(a) is float:
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    return a == b


def blocks(ref_or_record, size):
    out = []
    with ref_or_record.iter_json(max_chunk_bytes=size) as stream:
        for block in stream:
            with block:
                out.append(bytes(block.value))
    return out


def rational(rnd):
    num = rnd.getrandbits(rnd.choice((8, 60, 112, 300)))
    return [('-' if rnd.random() < 0.3 else '')+hex(num), hex(1 << rnd.randrange(1, 90))]


def scalar(rnd):
    pick = rnd.randrange(14)
    if pick == 0:
        return None
    if pick == 1:
        return rnd.random() < 0.5
    if pick == 2:
        return rnd.randrange(-300, 300)
    if pick == 3:
        return rnd.choice((-1, 1))*rnd.getrandbits(rnd.choice((40, 64, 65, 200, 900)))
    if pick == 4:
        return rnd.choice((0.0, -0.0, 5e-324, 1.7976931348623157e308, 0.1, -2.5e-300, 1e16, 123.456))
    if pick == 5:
        return rnd.uniform(-1e6, 1e6)
    if pick == 6:
        return ''.join(rnd.choice('abcXYZ019 _-') for _ in range(rnd.randrange(0, 40)))
    if pick == 7:
        return ''.join(chr(rnd.choice((0x22, 0x5c, 0x2f, 0x0a, 0x01, 0xe9, 0x4e2d, 0x1f600, 0xd800, 0x41)))
                       for _ in range(rnd.randrange(1, 12)))
    if pick == 8:
        return ('-' if rnd.random() < 0.4 else '')+hex(rnd.getrandbits(rnd.choice((4, 8, 64, 130, 513))))
    if pick == 9:
        return '0x1'+'0'*rnd.randrange(16, 300)
    if pick == 10:
        return sha256(str(rnd.random()).encode()).hexdigest()
    if pick == 11:
        return '0x0'
    if pick == 12:
        return rational(rnd)
    return 'k'+str(rnd.randrange(10))


def fuzz(rnd, depth=0, pool=None, budget=None):
    """Seeded JSON value; ``budget`` ([bytes left]) bounds its canonical size, DAG reuse included."""
    pool = [] if pool is None else pool
    budget = [60000] if budget is None else budget
    r = rnd.random()
    if depth and pool and r < 0.08:
        value, size = rnd.choice(pool)   # repeated subtree (hash-consed DAG)
        if size <= budget[0]:
            budget[0] -= size
            return value
    if budget[0] <= 0 or depth > 7 or (depth and r < 0.45):
        value = scalar(rnd)
        budget[0] -= len(T.canonical(value))
        return value
    width = rnd.randrange(8, 40) if not depth else rnd.randrange(0, 9)
    if r < 0.6:
        value = [fuzz(rnd, depth+1, pool, budget) for _ in range(width)]
    else:
        keys = {''.join(rnd.choice('abcé中\U0001f600"\\\n_0') for _ in range(rnd.randrange(0, 6)))
                for _ in range(width)}
        value = {key: fuzz(rnd, depth+1, pool, budget) for key in sorted(keys)}
    if rnd.random() < 0.3:
        pool.append((value, len(T.canonical(value))))
    return value


def shapes():
    escaped = ''.join(chr(c) for c in range(32))+'"\\/'
    rnd = random.Random(1)
    cells = [{'cell_id': sha256(f'c{i}'.encode()).hexdigest(),
              'exact': {f'f{j}': rational(rnd) for j in range(44)},
              'source_key': 'src-é'+str(i % 5), 'volume_m3': [hex(i+3), '0x7']} for i in range(30)]
    force = {'rows': {f'row{o:04d}': {
        'a': [[hex(rnd.getrandbits(48)), hex(rnd.getrandbits(44) | 1)] for _ in range(12)],
        'n': [rnd.getrandbits(14) for _ in range(9)], 'm': [[rnd.getrandbits(10)] for _ in range(6)],
        'k': f'label-{o}', 'f': False, 'z': None} for o in range(60)}, 'time_s': 0.0}
    return [
        ('carried-cells', {'cells': cells}),
        ('certification-force', force),
        ('rational-wide-small', ['0x'+'f'*16000, '0x'+'1'+'0'*15000]),
        ('nested-arrays-depth-128', json.loads('['*128+']'*128)),
        ('nested-objects-depth-128', json.loads('{"a":'*127+'{}'+'}'*127)),
        ('escaped-keys', {f'{escaped[i % len(escaped)]}{i}': i for i in range(800)}),
        ('large-ints', [(-1)**i*int('9'*4000) for i in range(7)]),
        ('floats-special', [-0.0, 5e-324, 1.7976931348623157e308, 0.1]*300),
        ('empty-everything', [[], {}, '', 0, [[]], [{}], {'': {}}]*200),
        ('content-ids', [sha256(str(i).encode()).hexdigest() for i in range(300)]),
        ('dag-repeated-subtree', [{'x': [1, 2, 3], 'y': '0x7'}]*900),
        ('large-route-text', {'blob': 'z'*40000, 'small': {'a': [1, 2]}, 'tail': ['0x5', None]}),
        ('scalar-text', 'only a string'),
        ('scalar-hex', '-0xabc'),
        ('scalar-int', -12345678901234567890),
        ('scalar-float', -0.0),
    ]+[(f'fuzz-{i}', bounded_fuzz(100+i)) for i in range(40)]


def bounded_fuzz(seed):
    return fuzz(random.Random(seed))


class _Pair:
    """The same payload as an R1 record (scope) and as an origin record (its own ref_scope).

    One retained scope holds one 'pages' cache configuration (its verifier),
    so the origin module's sealed records live in their own scope, reading
    the same sealed file through their own store set.
    """
    def __init__(self, scope, ref_scope, value, backing, stores=None, origin_sealed=True):
        packed = T.RecordCodec().pack_record(value, record_schema='test.r1v.v1', scope=scope, check=lambda: None)
        self.keep, self.old_sealed = [], None
        with packed.storage_payload() as held:
            raw, arrays = held.value
            self.old = REF.CompactRecord.from_payload(raw, dict(arrays), scope=ref_scope, check=lambda: None)
            if backing == 'memory':
                self.new = V.CompactRecord.from_payload(raw, dict(arrays), scope=scope, check=lambda: None)
        if backing != 'memory':
            # The R1 sealed record is compared with the origin's record of the
            # same column bytes (its per-value sealed reads are too slow to
            # repeat per node); the origin's own sealed record is opened too
            # (full validation) and its root stream compared.
            segment, store_set, catalog = stores.publish(packed, scope)
            self.new = V.CompactRecord.from_segment(segment)
            self.keep = [segment, store_set]
            if origin_sealed:
                ref_stores = IntervalStoreSet.open_catalog(catalog, scope=ref_scope)
                ref_segment = SegmentBackend().open(ref_stores, segment.info.ref, scope=ref_scope)
                self.old_sealed = REF.CompactRecord.from_segment(ref_segment)
                self.keep = [segment, ref_segment, store_set, ref_stores]
        packed.close()

    def close(self):
        self.new.close()
        self.old.close()
        if self.old_sealed is not None:
            self.old_sealed.close()
        for item in self.keep:
            item.close()


class _Stores:
    def __init__(self, directory):
        self.directory, self.count = Path(directory), 0

    def publish(self, packed, scope, cancel=None):
        self.count += 1
        folder = self.directory/f'p{self.count}'
        folder.mkdir()
        catalog = folder/'catalog.json'
        stores = IntervalStoreSet.create_migration(str(catalog), workflow_id='1'*64, scope=scope)
        candidate = stores.begin_interval(None, producer_identity='2'*64, runtime_identity='3'*64)
        backend = SegmentBackend()
        with packed.metadata_bytes() as held:
            reference = backend.publish(candidate, record_schema='test.r1v.v1', identity=packed.identity(),
                metadata=held.value, arrays=packed.array_sources, producer='2'*64,
                representation_profile=T.SCHEMA, scope=scope)
        stores.promote(candidate.seal(reference), expected_catalog_digest=stores.catalog_digest)
        candidate.close()
        return backend.open(stores, reference, scope=scope, cancel=cancel), stores, catalog


def cancel_on_third(calls, cancel, real):
    """check_unchanged stand-in: the third call sets the view's cancel event, then checks."""
    calls[0] += 1
    if calls[0] == 3:
        cancel.set()
    return real()


def outcome(fn):
    try:
        result = fn()
    except Exception as error:  # noqa: BLE001 - the outcome is compared
        return ('refused', type(error).__name__, str(error))
    return ('accepted', result)


class R1ViewsTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(2 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='r1-views-test')
        self.ref_budget = WorkBudget(2 << 30)
        self.ref_scope = create_retained_scope(self.ref_budget, process_epoch='r1-views-reference')
        self.directory = tempfile.TemporaryDirectory(prefix='r1v-')
        self.stores = _Stores(self.directory.name)
        # The base generation is R1a: the origin copy with R1a's failure-path
        # exit (retire, not close), so a refusal is never masked by a close
        # refusal on the reference side either.
        self.exit_patch = patch.object(REF.RecordRef, '__exit__', V.RecordRef.__exit__)
        self.exit_patch.start()

    def tearDown(self):
        self.exit_patch.stop()
        gc.collect()
        self.scope.close()
        self.ref_scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.assertEqual(self.ref_budget.reserved_bytes, 0)
        self.directory.cleanup()

    def compare(self, name, pair, value, *, all_nodes, sample=40, sizes=(7, 64, 4096, T.CHUNK)):
        canonical = T.canonical(value)
        self.assertEqual(pair.new.identity(), pair.old.identity(), name)
        if pair.old_sealed is not None:
            self.assertEqual(pair.old_sealed.identity(), pair.old.identity(), name)
            self.assertEqual(blocks(pair.new, T.CHUNK), blocks(pair.old_sealed, T.CHUNK), name)
        for size in ((1,) if len(canonical) <= 20000 else ())+sizes:
            new, old = blocks(pair.new, size), blocks(pair.old, size)
            self.assertEqual(new, old, (name, size))
        self.assertEqual(b''.join(new), canonical, name)
        n = pair.new._n('node.kind')
        nodes = range(n) if all_nodes else sorted({0, n-1, pair.new._root,
                                                    *random.Random(n).sample(range(n), min(n, sample))})
        for node in nodes:
            with V.RecordRef(pair.new, node) as new_ref, REF.RecordRef(pair.old, node) as old_ref:
                with new_ref.export(max_logical_bytes=BIG, max_owned_bytes=BIG) as a, \
                        old_ref.export(max_logical_bytes=BIG, max_owned_bytes=BIG) as b:
                    self.assertTrue(same(a.value, b.value), (name, node))
                with V.CompactRecord._read_batch(pair.new), REF.CompactRecord._read_batch(pair.old):
                    stats = V._node_stats(pair.new, node, BIG, {})
                    self.assertEqual(stats, REF._decoded_stats(old_ref, BIG, {}), (name, node))
                    self.assertEqual(V._decoded_stats(new_ref, BIG, {}), stats, (name, node))
                # Booking: the export charge is R1a's formula over the (equal) stats.
                before = self.scope.stats().purpose_bytes.get('retained:record-export', 0)
                with new_ref.export(max_logical_bytes=BIG, max_owned_bytes=BIG):
                    booked = self.scope.stats().purpose_bytes.get('retained:record-export', 0)-before
                decoded, largest = stats
                self.assertEqual(booked, 65536+decoded+3*largest+min(4*largest, 4*T.CHUNK)+V.OWNER_BYTES,
                                 (name, node))
                if new_ref.kind != 'object':
                    continue
                for size in (5, T.CHUNK):
                    self.assertEqual(blocks(new_ref, size), blocks(old_ref, size), (name, node, size))

    def run_shapes(self, backing, names):
        # R1V_PART=i/n runs every n-th shape from the i-th (one process each).
        part = os.environ.get('R1V_PART', '')
        index, count = map(int, part.split('/')) if part else (0, 1)
        values = dict(shapes())
        # R1V_SHAPES=a,b,... restricts the run to the named shapes (resuming a split run).
        only = set(filter(None, os.environ.get('R1V_SHAPES', '').split(',')))
        ran = 0
        for name in [name for name in names if not only or name in only][index::count]:
            value = values[name]
            if backing != 'memory' and len(T.canonical(value)) > 1 << 20:
                continue
            started = time.perf_counter()
            # The origin's own sealed open (slow per-value validation) for the named shapes only.
            pair = _Pair(self.scope, self.ref_scope, value, backing, self.stores,
                         origin_sealed=not name.startswith('fuzz'))
            try:
                nodes = pair.new._n('node.kind')
                if backing == 'memory':
                    self.compare(name, pair, value, all_nodes=nodes <= 200)
                else:
                    # Each API call outside a read batch re-checks the sealed file
                    # identity on the live (pre-S1) storage: sample fewer nodes.
                    self.compare(name, pair, value, all_nodes=nodes <= 30,
                                 sample=4 if name.startswith('fuzz') else 12)
            finally:
                pair.close()
            gc.collect()
            ran += 1
            print(json.dumps({'shape': name, 'backing': backing, 'nodes': nodes, 'canonical_bytes':
                              len(T.canonical(value)), 'seconds': round(time.perf_counter()-started, 2)}),
                  file=sys.stderr, flush=True)
        self.assertGreater(ran, 0)

    def test_memory_shapes(self):
        self.run_shapes('memory', [name for name, _ in shapes() if not name.startswith('fuzz')])

    def test_memory_fuzz(self):
        self.run_shapes('memory', [name for name, _ in shapes() if name.startswith('fuzz')])

    def test_sealed_shapes(self):
        self.run_shapes('sealed', [name for name, _ in shapes() if not name.startswith('fuzz')])

    def test_sealed_fuzz(self):
        self.run_shapes('sealed', [name for name, _ in shapes() if name.startswith('fuzz')])

    def test_composites_and_api_reads(self):
        value = {'blob': 'q'*40000, 'outer': {'middle': {'inner': list(range(6)), 'tag': 'x'}, 'k': [1.5, -0.0]},
                 'rows': [{'a': i, 'b': hex(i*7919)} for i in range(50)], 'top': 7}
        headed = {**value, 'state_id': 'a'*64, 'result_id': 'b'*64}
        headed_bytes = T.canonical(headed)
        for backing in ('memory', 'sealed'):
            pair = _Pair(self.scope, self.ref_scope, value, backing, self.stores)
            try:
                for module, record in ((V, pair.new), (REF, pair.old)):
                    root = record.root()
                    outer = root.field('outer')
                    inner = outer.without(('k',))
                    composite = module.LogicalExchange.from_records(root, outer=inner)
                    with composite.export(max_logical_bytes=BIG, max_owned_bytes=BIG) as a:
                        got = (a.value, None, blocks(composite, 33), composite.composite_identity('c'*64))
                    if module is V:
                        # from_body packs its header record with the live codec, which only
                        # the live classes accept: checked against the legacy dictionary.
                        header = V.LogicalExchange.from_body(record, state_id='a'*64, result_id='b'*64)
                        with header.export(max_logical_bytes=BIG, max_owned_bytes=BIG) as b:
                            self.assertTrue(same(b.value, json.loads(headed_bytes)), backing)
                        self.assertEqual(blocks(header, T.CHUNK), [headed_bytes[i:i+T.CHUNK] for i in
                                                                   range(0, len(headed_bytes), T.CHUNK)])
                        identity = header.identity()
                        self.assertEqual((identity.sha256, identity.canonical_bytes),
                                         (sha256(headed_bytes).hexdigest(), len(headed_bytes)))
                        header.close()

                    def val(owned):
                        with owned as held:
                            return held.value
                    with root.field('rows') as rows, rows.iter_rows(max_rows=7, max_owned_bytes=1 << 20,
                                                                     fields=('b',)) as stream:
                        listed = []
                        for block in stream:
                            with block:
                                for row in block.value:
                                    listed.append(val(row.get('b')))
                                    row.close()
                    with root.field('outer') as o, o.field('middle') as m, m.field('inner') as i:
                        api = (val(root.keys()), val(m.get('tag')), i.size, val(root.get('top')),
                               val(root.get('missing', 3)), outer.kind, inner.size)
                    got += (listed, api)
                    if module is V:
                        new_got = got
                    else:
                        old_got = got
                    for item in (composite, inner, outer, root):
                        item.close()
                self.assertTrue(same(new_got[0], old_got[0]), backing)
                self.assertEqual(new_got[2:], old_got[2:], backing)
            finally:
                pair.close()
            gc.collect()

    def test_mutated_payloads_same_accept_or_refuse(self):
        rnd = random.Random(7)
        values = [v for name, v in shapes() if name in ('carried-cells', 'certification-force', 'escaped-keys',
                                                         'dag-repeated-subtree', 'large-ints', 'fuzz-3', 'fuzz-11',
                                                         'nested-objects-depth-128', 'floats-special')]
        tried, refused, messages = 0, 0, set()
        for value in values:
            packed = T.RecordCodec().pack_record(value, record_schema='test.r1v.v1', scope=self.scope,
                                                check=lambda: None)
            with packed.storage_payload() as held:
                raw, arrays = held.value
                meta = json.loads(raw)
                names = [name for name in sorted(arrays) if arrays[name].size]
                for _ in range(45):
                    name = rnd.choice(names)
                    changed = {k: np.array(a, copy=True) for k, a in arrays.items()}
                    column = changed[name]
                    index = rnd.randrange(column.size)
                    if column.dtype.kind == 'f':
                        column[index] = rnd.choice((float('inf'), -0.0, column[index]+1.0, 0.5))
                    else:
                        top = np.iinfo(column.dtype).max
                        column[index] = rnd.choice((0, 1, 2, top, (int(column[index])+1) % (top+1),
                                                    max(0, int(column[index])-1)))
                    meta2 = json.loads(raw)
                    meta2['arrays'][name]['sha256'] = sha256(memoryview(column).cast('B')).hexdigest()
                    raw2 = T.canonical(meta2)
                    results = []
                    for module in (V, REF):
                        def build(module=module, raw2=raw2, changed=changed):
                            record = module.CompactRecord.from_payload(raw2, changed, scope=self.scope,
                                                                       check=lambda: None)
                            identity = record.identity()
                            record.close()
                            return identity
                        results.append(outcome(build))
                    self.assertEqual(results[0], results[1], (name, index, results))
                    tried += 1
                    refused += results[0][0] == 'refused'
                    messages.add(results[0][2] if results[0][0] == 'refused' else 'accepted')
                    gc.collect()
                del meta
            packed.close()
        print(json.dumps({'mutations': tried, 'refused': refused, 'distinct_outcomes': sorted(messages)}),
              file=sys.stderr)
        self.assertGreater(refused, tried//3)

    def test_large_route_refusals_are_the_same(self):
        value = {'blob': 'z'*40000, 'wide': {f'key-{i:05d}': i for i in range(3000)}}
        pair = _Pair(self.scope, self.ref_scope, value, 'memory')
        try:
            results = []
            for module, record in ((V, pair.new), (REF, pair.old)):
                with record.root() as root:
                    # Key inventory bound of the large route (patched lower for the test).
                    with patch.object(T, 'MAX_ROW_WORK_BYTES', 200000):
                        a = outcome(lambda root=root: root.export(max_logical_bytes=BIG, max_owned_bytes=BIG).close())
                    b = outcome(lambda root=root: root.export(max_logical_bytes=BIG, max_owned_bytes=300000).close())
                    c = outcome(lambda root=root: root.export(max_logical_bytes=1000, max_owned_bytes=BIG).close())
                    results.append((a, b, c))
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0][0][2], 'object keys exceed owned byte bound')
            self.assertEqual(results[0][1][2], 'owned export bound exceeded before allocation')
            self.assertEqual(results[0][2][2], 'logical export bound exceeded')
        finally:
            pair.close()

    def test_sealed_freshness_and_cancellation_refusals(self):
        value = {'cells': [{'id': sha256(str(i).encode()).hexdigest(), 'q': [hex(i*31+1), '0x10']}
                           for i in range(400)], 'blob': 'w'*40000}
        for module, scope in ((V, self.scope), (REF, self.ref_scope)):
            packed = T.RecordCodec().pack_record(value, record_schema='test.r1v.v1', scope=scope,
                                                check=lambda: None)
            cancel = threading.Event()
            segment, stores, _ = self.stores.publish(packed, scope, cancel=cancel)
            packed.close()
            record = module.CompactRecord.from_segment(segment)
            with record.root() as root:
                with patch.object(stores, 'assert_cached_read_safe', side_effect=ContractError('changed file')):
                    with self.assertRaisesRegex(ContractError, 'changed file'):
                        blocks(root, T.CHUNK)
                    with self.assertRaisesRegex(ContractError, 'changed file'):
                        root.export(max_logical_bytes=BIG, max_owned_bytes=BIG)
                self.assertEqual(b''.join(blocks(root, T.CHUNK)), T.canonical(value))
                # A cancellation set during a read refuses the read (CancelledError).
                cancelling = partial(cancel_on_third, [0], cancel, segment.check_unchanged)
                with patch.object(segment, 'check_unchanged', side_effect=cancelling), \
                        self.assertRaises(CancelledError):
                    root.export(max_logical_bytes=BIG, max_owned_bytes=BIG)
                cancel.clear()
                with self.assertRaises(CancelledError):
                    cancel.set()
                    blocks(root, T.CHUNK)
                cancel.clear()
            gc.collect()
            record.close()
            segment.close()
            stores.close()
            gc.collect()

    def test_record_check_runs_once_per_rendered_node(self):
        """The renderer keeps _parts' record check before every child (guard stops still land)."""
        value = {'a': [1, 2, {'b': ['0x5', None, 2.5]}], 'c': 'x'}
        counts = []
        for module in (V, REF):
            calls = [0]
            def check(calls=calls):
                calls[0] += 1
            record = T.RecordCodec().pack_record(value, record_schema='test.r1v.v1', scope=self.scope, check=check)
            with record.storage_payload() as held:
                raw, arrays = held.value
                view = module.CompactRecord.from_payload(raw, dict(arrays), scope=self.scope, check=check)
            record.close()
            calls[0] = 0
            out = b''.join(view._parts(view._root, memo=module._CanonicalMemo(self.scope)))
            counts.append((calls[0], out))
            view.close()
        self.assertEqual(counts[0], counts[1])


if __name__ == '__main__':
    unittest.main()
