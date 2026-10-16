"""Item 14 page-layer fix: byte-identical opens, fewer page reads, bounded booked memos.

Runs from the compact folder of a mirror whose record_views.py is the item-14
candidate, with item14_origin_record_views.py (the live origin, sha-pinned
below) beside this file. The origin is loaded under its own module name so
both versions open the same records in the same process.
"""
from collections import OrderedDict
from contextlib import ExitStack, contextmanager
import gc
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile
import tracemalloc
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'))
TMP = HERE.parents[4]/'_t'

import numpy as np
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from compact_contracts import ContractError
import content_cache
from content_cache import CACHE_CONTROL_BYTES, OWNER_BYTES, VerifiedCacheKey, create_retained_scope
from interval_store_set import IntervalStoreSet
from segment_store import SegmentBackend
import record_tables as T
import record_views as M
from test_record_tables import streamed

ORIGIN_SHA256 = 'e0a2a8453f494e50cacded7de06e275b1e36f526c220df611bbedb69248e0f9b'
_ORIGIN = HERE/'item14_origin_record_views.py'
if sha256(_ORIGIN.read_bytes()).hexdigest() != ORIGIN_SHA256:
    raise RuntimeError('item14 origin copy differs from the pinned live record_views')
_SPEC = importlib.util.spec_from_file_location('item14_origin_record_views', _ORIGIN)
O = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = O
_SPEC.loader.exec_module(O)

SCHEMA = 'test.item14.v1'
# The memo's designed bounds, pinned here rather than read from the module
# under test: rows (one per pinnable page plus one per column), bytes booked
# per row, and the widest binding kept (the verifier's descriptor bound).
ROWS, ROW_BYTES, BINDING_MAX = 128+len(M._NAMES), 4096, 1024
# The memo's backing; its retained charge adds the ownership carrier.
MEMO_BACKING = ROWS*ROW_BYTES+4096
MEMO_CHARGE = MEMO_BACKING+OWNER_BYTES


def page_misses(scope):
    return scope.stats().misses.get('pages', 0)


def make_value(count=6000, seed=14):
    """HEX strings of 1..48 magnitude bytes (both high-byte classes), plus every scalar kind."""
    rng = random.Random(seed)
    hexes = []
    for i in range(count):
        width = rng.randint(1, 48)
        text = hex(rng.getrandbits(8*width) or 1)
        hexes.append('-'+text if i % 7 == 0 else text)
    hexes += ['0x1ff', '0xfff0', '0x0', '-0x1', '0x1'+'0'*20, '0xf', '0x10']
    return {'h': hexes, 'i': [(1 << 200) | 12345, 1 << 70, -(1 << 90), 0, 255],
            'q': [['0x2', '0x3'], ['0x7', '0x10']], 't': 'text é', 'f': {'x': 1.5, 'y': -0.0}}


def payload(value, scope):
    packed = T.RecordCodec().pack_record(value, record_schema=SCHEMA, scope=scope, check=lambda: None)
    try:
        with packed.storage_payload() as held:
            metadata, arrays = held.value
            return bytes(metadata), {name: np.array(array, copy=True) for name, array in arrays.items()}
    finally:
        packed.close()


def int_facts(arrays):
    """binary: integers whose high byte both scans read; hex_binary: HEX nodes over them."""
    modes, offsets = arrays['int.mode'].tolist(), arrays['int.offset'].tolist()
    data = arrays['int.bytes']
    binary = [not modes[p] and offsets[p+1] > offsets[p] for p in range(len(modes))]
    hexes = [p for kind, p in zip(arrays['node.kind'].tolist(), arrays['node.payload'].tolist(), strict=True)
             if kind == T.HEX]
    return SimpleNamespace(binary=sum(binary), hex_binary=sum(binary[p] for p in hexes),
                           hex_low=sum(1 for p in hexes if binary[p] and data[offsets[p+1]-1] < 16),
                           hex_high=sum(1 for p in hexes if binary[p] and data[offsets[p+1]-1] >= 16))


def tampered(metadata, arrays, name, mutate):
    altered = dict(arrays)
    altered[name] = arrays[name].copy()
    mutate(altered[name])
    header = json.loads(metadata)
    header['arrays'][name]['sha256'] = sha256(altered[name].tobytes()).hexdigest()
    return T.canonical(header), altered


class _Counting:
    """Counts single-value reads of one column; byte-range reads keep the backing's route."""
    __slots__ = ('_counter', '_view')

    def __init__(self, view, counter):
        self._view, self._counter = view, counter

    def __getitem__(self, index):
        self._counter[0] += 1
        return self._view[index]


@contextmanager
def counting(module, counter, name='int.bytes'):
    original = module._Access.column

    def column(self, column_name):
        view = original(self, column_name)
        return _Counting(view, counter) if column_name == name else view
    with patch.object(module._Access, 'column', column):
        yield


@contextmanager
def tracked(module, made, calls):
    original = module.CompactRecord._validate_batch

    def validate_batch(self, *args, **kwargs):
        calls.append(kwargs.get('keep_highs') is not None)
        return original(self, *args, **kwargs)
    with ExitStack() as stack:
        stack.enter_context(patch.object(module.CompactRecord, '_validate_batch', validate_batch))
        if module is M:
            class Tracking(M._OptionalScratch):
                def __init__(self, budget, size, category='record-column-lookup'):
                    super().__init__(budget, size, category)
                    if category == 'record-validate-highs':
                        made.append((size, self.admitted, weakref.ref(self)))
            stack.enter_context(patch.object(M, '_OptionalScratch', Tracking))
        yield


@contextmanager
def sealed(test, value, epoch, *, quota=None, budget_bytes=1 << 30):
    """A promoted native segment of ``value`` in its own scope (one page-cache verifier per scope)."""
    with patch.dict(content_cache._QUOTAS, {} if quota is None else {'pages': quota}):
        budget = WorkBudget(budget_bytes)
        scope = create_retained_scope(budget, process_epoch=epoch)
        TMP.mkdir(exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix='i14-', dir=TMP))
        stores = candidate = None
        ok = False
        try:
            stores = IntervalStoreSet.create_migration(str(directory/'catalog.json'),
                workflow_id='1'*64, scope=scope)
            candidate = stores.begin_interval(None, producer_identity='2'*64, runtime_identity='3'*64)
            packed = T.RecordCodec().pack_record(value, record_schema=SCHEMA, scope=scope, check=lambda: None)
            backend = SegmentBackend()
            with packed.metadata_bytes() as held:
                ref = backend.publish(candidate, record_schema=SCHEMA, identity=packed.identity(),
                    metadata=held.value, arrays=packed.array_sources, producer='2'*64,
                    representation_profile=T.SCHEMA, scope=scope)
            with packed.storage_payload() as held:
                metadata, arrays = held.value
                metadata = bytes(metadata)
                arrays = {name: np.array(array, copy=True) for name, array in arrays.items()}
            packed.close()
            del packed, held
            promoted = candidate.seal(ref)
            stores.promote(promoted, expected_catalog_digest=promoted.expected_catalog_digest)
            del promoted
            yield SimpleNamespace(scope=scope, budget=budget, metadata=metadata, arrays=arrays,
                                  segment=lambda: backend.open(stores, ref, scope=scope))
            ok = True
        finally:
            gc.collect()
            try:
                if candidate is not None:
                    candidate.close()
                if stores is not None:
                    stores.close()
                gc.collect()
                scope.close()
            except Exception:
                if ok:
                    raise
            shutil.rmtree(directory, ignore_errors=True)
        test.assertEqual(budget.reserved_bytes, 0)


def open_sealed(fx, module):
    segment = fx.segment()
    return module.CompactRecord.from_segment(segment), segment


def close_sealed(record, segment):
    record.close()
    segment.close()


def report(**fields):
    print('ITEM14 '+json.dumps(fields, sort_keys=True), flush=True)


class Item14PageLayerTests(unittest.TestCase):
    maxDiff = None

    def test_validate_reads_each_integer_high_byte_once(self):
        value = make_value()
        expected = T.canonical(value)
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='i14-counts')
        metadata, arrays = payload(value, scope)
        facts = int_facts(arrays)
        self.assertGreater(facts.hex_binary, 5000)
        self.assertGreater(facts.hex_low, 0)
        self.assertGreater(facts.hex_high, 0)
        counts = {}
        for label, module in (('origin', O), ('candidate', M)):
            counter = [0]
            with counting(module, counter):
                record = module.CompactRecord.from_payload(metadata, dict(arrays), scope=scope, check=lambda: None)
            counts[label] = counter[0]
            self.assertEqual(streamed(record), expected, label)
            record.close()
        # The origin reads each binary high byte in the integer scan and again
        # for each HEX node; the candidate reads it once.
        self.assertEqual(counts['origin'], facts.binary+facts.hex_binary)
        self.assertEqual(counts['candidate'], facts.binary)
        declined = []

        class Declining(M._OptionalScratch):
            def __init__(self, budget, size, category='record-column-lookup'):
                if category == 'record-validate-highs':
                    self._lease, self.admitted = None, False
                    declined.append(size)
                else:
                    super().__init__(budget, size, category)
        counter = [0]
        with counting(M, counter), patch.object(M, '_OptionalScratch', Declining):
            record = M.CompactRecord.from_payload(metadata, dict(arrays), scope=scope, check=lambda: None)
        self.assertEqual(declined, [4096+len(arrays['int.sign'])])
        self.assertEqual(counter[0], counts['origin'], 'a declined memo must read exactly as before')
        self.assertEqual(streamed(record), expected)
        record.close()
        report(check='high-byte-reads', origin=counts['origin'], candidate=counts['candidate'],
               declined=counter[0], hex_binary=facts.hex_binary, binary=facts.binary)
        del record
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_sealed_opens_are_byte_identical_with_no_more_page_misses(self):
        value = make_value()
        expected = T.canonical(value)
        result = {}
        for label, module in (('origin', O), ('candidate', M)):
            with sealed(self, value, 'i14-sealed-'+label) as fx:
                facts = int_facts(fx.arrays)
                self.assertGreater(len(fx.arrays['int.bytes']), 2*T.CHUNK)
                before = page_misses(fx.scope)
                record, segment = open_sealed(fx, module)
                misses = page_misses(fx.scope)-before
                self.assertEqual(streamed(record), expected, label)
                close_sealed(record, segment)
                # Reads are counted on a second open: the proxy moves byte-range
                # reads off the paged route, so it must not shape the misses.
                counter = [0]
                with counting(module, counter):
                    record, segment = open_sealed(fx, module)
                close_sealed(record, segment)
                del record, segment
                result[label] = dict(reads=counter[0], misses=misses)
        self.assertEqual(result['origin']['reads']-result['candidate']['reads'], facts.hex_binary)
        self.assertLessEqual(result['candidate']['misses'], result['origin']['misses'])
        report(check='sealed-default-quota', **{f'{k}_{f}': v[f] for k, v in result.items() for f in v})

    def test_thrashing_page_cache_misses_fewer_pages(self):
        # No batch registry and a page cache that holds about one int.bytes
        # page: every access asks the cache, as a registry past its 128 pins does.
        value = make_value(count=1500)
        expected = T.canonical(value)
        misses = {}
        for label, module in (('origin', O), ('candidate', M)):
            with sealed(self, value, 'i14-thrash-'+label, quota=CACHE_CONTROL_BYTES+48*1024) as fx:
                original = fx.scope.reserve

                def no_registry(spec, *, _reserve=original, **kwargs):
                    if spec.purpose == 'record-batch-page-borrows' and kwargs.get('required') is False:
                        return None
                    return _reserve(spec, **kwargs)
                before = page_misses(fx.scope)
                with patch.object(fx.scope, 'reserve', side_effect=no_registry):
                    record, segment = open_sealed(fx, module)
                misses[label] = page_misses(fx.scope)-before
                self.assertEqual(streamed(record), expected, label)
                close_sealed(record, segment)
                del record, segment, original, no_registry
        self.assertLess(misses['candidate'], misses['origin'])
        report(check='thrash-misses', **misses)

    def test_admitted_memo_that_starves_the_scan_reopens_without_it(self):
        value = make_value(count=600)
        expected = T.canonical(value)
        for route in ('payload', 'sealed'):
            for module in (O, M):
                made, calls = [], []
                with ExitStack() as stack:
                    if route == 'sealed':
                        fx = stack.enter_context(sealed(self, value, f'i14-retry-{module.__name__}'))
                        arrays = fx.arrays

                        def opened(fx=fx, module=module):
                            return open_sealed(fx, module)
                    else:
                        budget = WorkBudget(1 << 30)
                        scope = create_retained_scope(budget, process_epoch='i14-retry-payload')
                        metadata, arrays = payload(value, scope)

                        def opened(scope=scope, metadata=metadata, arrays=arrays, module=module):
                            return module.CompactRecord.from_payload(metadata, dict(arrays), scope=scope,
                                                                     check=lambda: None), None
                    n, ints = len(arrays['node.kind']), len(arrays['int.sign'])
                    need = 65536+256*n+65536*4+T.MAX_DEPTH*1024
                    with tracked(module, made, calls):
                        with patch.object(T, 'MAX_BUILD_BYTES', need+64):
                            record, segment = opened()
                        self.assertEqual(streamed(record), expected, (route, module.__name__))
                        record.close()
                        if segment is not None:
                            segment.close()
                        del record, segment
                        with patch.object(T, 'MAX_BUILD_BYTES', need-64):
                            if route == 'sealed':
                                segment = fx.segment()
                                with self.assertRaises(MemoryLimitError):
                                    module.CompactRecord.from_segment(segment)
                                gc.collect()
                                segment.close()
                                del segment
                            else:
                                with self.assertRaises(MemoryLimitError):
                                    opened()
                    gc.collect()
                    if module is M:
                        # Fits only without the memo: admitted, starved, then reopened without it.
                        self.assertEqual(calls, [True, False, True, False])
                        self.assertEqual([(size, admitted) for size, admitted, _ in made],
                                         [(4096+ints, True)]*2)
                        self.assertTrue(all(ref() is None for _, _, ref in made), 'memo lease outlived its scan')
                    else:
                        self.assertEqual(calls, [False, False])
                    if route == 'payload':
                        del opened
                        gc.collect()
                        scope.close()
                        self.assertEqual(budget.reserved_bytes, 0)
                    del made
        report(check='starved-memo-retry', routes=['payload', 'sealed'])

    def test_tampered_integers_are_refused_as_before(self):
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='i14-tamper')
        metadata, arrays = payload(make_value(count=400), scope)
        modes, offsets, data = arrays['int.mode'], arrays['int.offset'], arrays['int.bytes']
        hexes = [int(p) for kind, p in zip(arrays['node.kind'], arrays['node.payload'], strict=True) if kind == T.HEX]
        binary = [p for p in hexes if not modes[p] and offsets[p+1] > offsets[p]]
        high = next(p for p in binary if data[offsets[p+1]-1] >= 16)
        low = next(p for p in binary if data[offsets[p+1]-1] < 16)
        node = next(i for i, (kind, p) in enumerate(zip(arrays['node.kind'], arrays['node.payload'], strict=True))
                    if kind == T.HEX and int(p) == high)
        cases = [('zero-high', 'nonminimal binary integer', 'int.bytes',
                  lambda a: a.__setitem__(offsets[high+1]-1, 0)),
                 ('high-to-low', None, 'int.bytes', lambda a: a.__setitem__(offsets[high+1]-1, 0x0f)),
                 ('low-to-high', None, 'int.bytes', lambda a: a.__setitem__(offsets[low+1]-1, 0x10)),
                 ('length-up', None, 'node.length', lambda a: a.__setitem__(node, a[node]+1)),
                 ('length-down', None, 'node.length', lambda a: a.__setitem__(node, a[node]-1))]
        refusals = {}
        for label, message, name, mutate in cases:
            header, altered = tampered(metadata, arrays, name, mutate)
            seen = []
            for module in (O, M):
                with self.assertRaises(ContractError, msg=(label, module.__name__)) as caught:
                    module.CompactRecord.from_payload(header, dict(altered), scope=scope, check=lambda: None)
                seen.append(str(caught.exception))
                del caught
            # The same refusal as before, whichever check meets the change first.
            self.assertEqual(seen[1], seen[0], label)
            if message is not None:
                self.assertIn(message, seen[0], label)
            refusals[label] = seen[0]
            del altered
            gc.collect()
        report(check='tamper', **refusals)
        # At least one change must reach the HEX canonical-length check the memo now feeds.
        self.assertTrue(any('node canonical length differs' in v for v in refusals.values()), refusals)
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_memo_rows_are_the_origin_bindings_and_every_page_reads_exactly(self):
        value = make_value()
        with sealed(self, value, 'i14-rows') as fx:
            record, segment = open_sealed(fx, M)
            cols, epoch = record._columns, fx.scope.process_epoch
            for _ in range(2):
                for name, descriptor in cols.descriptors.items():
                    count = descriptor['shape'][0]
                    array = fx.arrays[name]
                    itemsize = array.dtype.itemsize
                    step = count if count*itemsize <= T.CHUNK else T.CHUNK//itemsize
                    for start in range(0, count, max(step, 1)):
                        stop = min(count, start+step)
                        with cols.raw(name, start, stop) as held:
                            self.assertEqual(bytes(held.value), array[start:stop].tobytes(), (name, start))
                        self.assertEqual(cols.value(name, start), array[start].item())
                        self.assertEqual(cols.value(name, stop-1), array[stop-1].item())
            rows = cols._page_keys.value
            self.assertTrue(any(start is None for _, start in rows))
            self.assertTrue(any(start is not None for _, start in rows))
            identity, wire = cols.file_identity.hex(), cols.segment.info.ref.to_wire()
            for (name, start), (entry, descriptor, facts, binding, key) in rows.items():
                self.assertIs(descriptor, cols.descriptors[name])
                dtype = np.dtype(descriptor['dtype'])
                if start is None:
                    self.assertIsNone(entry)
                    size = descriptor['shape'][0]*dtype.itemsize
                    # The origin's _cached_owner, verbatim.
                    origin_binding = T.canonical(dict(file_identity=identity,
                        segment=wire, name=name, dtype=dtype.str,
                        shape=descriptor['shape'], start=0, stop=descriptor['shape'][0]))
                    origin_key = O._column_key(epoch, origin_binding, descriptor['sha256'], size)
                else:
                    lo, hi, chunk_id, _, owner = entry
                    self.assertEqual(lo, start)
                    size = (hi-lo)*dtype.itemsize
                    # The origin's _cached_native_owner, verbatim.
                    origin_binding = T.canonical(dict(kind='native-chunk-v1', file_identity=identity,
                        segment=wire, name=name, dtype=dtype.str,
                        shape=descriptor['shape'], start=lo, stop=hi, owner=owner))
                    origin_key = O._column_key(epoch, origin_binding, chunk_id, size)
                self.assertEqual(binding, origin_binding, (name, start))
                self.assertEqual(key, origin_key, (name, start))
                self.assertEqual(facts, (dtype.str, size, epoch, descriptor['sha256'], tuple(descriptor['shape'])))
            report(check='memo-rows', rows=len(rows), native=sum(start is not None for _, start in rows))
            close_sealed(record, segment)
            del record, segment, cols, rows

    def test_page_key_memo_requires_identity_and_stays_bounded(self):
        value = make_value(count=400)
        expected = T.canonical(value)
        with sealed(self, value, 'i14-memo') as fx:
            record, segment = open_sealed(fx, M)
            cols, epoch = record._columns, fx.scope.process_epoch
            rows = cols._page_keys.value
            descriptor = cols.descriptors['int.bytes']
            dtype = np.dtype(descriptor['dtype'])
            made = []

            def make(width=64):
                def build(*args):
                    made.append(args)
                    binding = bytes([len(made) % 256])*width
                    return binding, VerifiedCacheKey('pages', epoch, sha256(binding).digest())
                return build

            def key(row, entry, *, descriptor=descriptor, dtype=dtype, size=10, width=64, _cols=cols, _make=make):
                return _cols._page_key(row, entry, descriptor, dtype, size, _make(width), row)
            entry = (0, 10, 'c'*64, b'{}', 'o'*64)
            row = ('synthetic', 0)
            steps = [((entry,), {}, 1, 'first build'),
                     ((entry,), {}, 0, 'identical entry and descriptor must reuse the row'),
                     # tuple(entry) would return entry itself; this is an equal, distinct object.
                     ((tuple(list(entry)),), {}, 1, 'an equal but different entry object must rebuild'),  # noqa: C414
                     ((entry,), {}, 1, 'the row now holds the other entry object'),
                     ((entry,), {}, 0, 'stored again'),
                     ((entry,), dict(descriptor=dict(descriptor)), 1, 'a different descriptor object must rebuild'),
                     ((entry,), {}, 1, 'back to the view descriptor'),
                     ((entry,), dict(dtype=np.dtype('<u8')), 1, 'a different dtype must rebuild'),
                     ((entry,), dict(dtype=np.dtype('<u8')), 0, 'stored again'),
                     ((entry,), dict(dtype=np.dtype('<u8'), size=11), 1, 'a different size must rebuild')]
            self.assertIsNot(steps[2][0][0], entry)
            for args, kwargs, built, why in steps:
                before = len(made)
                key(row, *args, **kwargs)
                self.assertEqual(len(made)-before, built, why)
            changing = dict(descriptor, shape=list(descriptor['shape']))
            for change, built, why in ((None, 1, 'first build'), (None, 0, 'same descriptor object reused'),
                                       (('shape', [descriptor['shape'][0]+1]), 1,
                                        'a changed shape in the same descriptor must rebuild'),
                                       (('sha256', '0'*64), 1, 'a changed digest in the same descriptor must rebuild'),
                                       (None, 0, 'stored again')):
                if change is not None:
                    changing[change[0]] = change[1]
                before = len(made)
                key(('synthetic', 1), entry, descriptor=changing)
                self.assertEqual(len(made)-before, built, why)
            for width, kept in ((BINDING_MAX, True), (BINDING_MAX+1, False)):
                before = len(made)
                key(('wide', width), entry, width=width)
                key(('wide', width), entry, width=width)
                self.assertEqual(len(made)-before, 1 if kept else 2, width)
                self.assertEqual(('wide', width) in rows, kept, width)
            for i in range(ROWS+5):
                key(('bulk', i), entry)
                if i == 10:
                    before = len(made)
                    key(('bulk', 0), entry)    # a hit moves the row to the newest end
                    self.assertEqual(len(made), before)
            # Recency: bulk 1..10, bulk 0, bulk 11..; the five oldest went.
            self.assertEqual(len(rows), ROWS)
            self.assertIn(('bulk', 0), rows)
            self.assertNotIn(('bulk', 1), rows)
            self.assertNotIn(('bulk', 5), rows)
            self.assertIn(('bulk', 6), rows)
            self.assertIn(('bulk', ROWS+4), rows)
            # Synthetic rows never stand in for real pages.
            self.assertEqual(streamed(record), expected)
            for name in ('int.bytes', 'node.kind', 'node.length'):
                itemsize = fx.arrays[name].dtype.itemsize
                stop = min(cols.descriptors[name]['shape'][0], T.CHUNK//itemsize)
                with cols.raw(name, 0, stop) as held:
                    self.assertEqual(bytes(held.value), fx.arrays[name][:stop].tobytes(), name)
            close_sealed(record, segment)
            del record, segment, cols, rows, make, key, held

    def test_memo_booking_covers_its_worst_case_and_is_released(self):
        value = make_value()
        with sealed(self, value, 'i14-booking') as fx:
            record, segment = open_sealed(fx, M)
            self.assertEqual((M._PAGE_KEY_ROWS, M._PAGE_KEY_ROW_BYTES, M._PAGE_KEY_BINDING_MAX),
                             (ROWS, ROW_BYTES, BINDING_MAX))
            booked = MEMO_BACKING
            stats = fx.scope.stats()
            self.assertEqual(stats.purpose_bytes['retained:record-page-keys'], MEMO_CHARGE)
            self.assertLessEqual(MEMO_CHARGE, stats.retained_bytes)
            self.assertLessEqual(stats.peak_retained_bytes, 256 << 20)
            cols, epoch = record._columns, fx.scope.process_epoch
            descriptor = cols.descriptors['int.bytes']
            dtype = np.dtype(descriptor['dtype'])
            owner = next(iter(cols._page_cursors.value.values()))[4]
            gc.collect()
            tracemalloc.start()
            try:
                before = tracemalloc.get_traced_memory()[0]
                # Every per-row object fresh at its bound: a 1,024 B typed
                # descriptor and a 1,024 B binding, as no real row exceeds.
                worst = OrderedDict()
                for i in range(ROWS):
                    start = (1 << 40)+i*T.CHUNK
                    entry = (start, start+T.CHUNK, '%064x' % (i+1), bytes([i % 256])*1024,
                             json.loads(json.dumps(owner)))
                    binding = bytes([(i+7) % 256])*BINDING_MAX
                    page_key = VerifiedCacheKey('pages', epoch, sha256(binding+bytes([i % 256])).digest())
                    facts = (dtype.str, T.CHUNK+i, epoch, descriptor['sha256'], tuple(descriptor['shape']))
                    worst[('int.bytes', start)] = (entry, descriptor, facts, binding, page_key)
                measured = tracemalloc.get_traced_memory()[0]-before
            finally:
                tracemalloc.stop()
            self.assertLessEqual(measured, booked)
            self.assertLessEqual(measured/ROWS, ROW_BYTES)
            report(check='memo-booking', booked=booked, charge=MEMO_CHARGE, worst_measured=measured,
                   per_row=round(measured/ROWS), owner_type=type(owner).__name__)
            del worst, entry, binding, page_key, facts
            close_sealed(record, segment)
            del record, segment, cols
            gc.collect()
            self.assertEqual(fx.scope.stats().purpose_bytes.get('retained:record-page-keys', 0), 0)

    def test_declined_memo_booking_keeps_every_access_unchanged(self):
        value = make_value(count=400)
        expected = T.canonical(value)
        with sealed(self, value, 'i14-declined-keys') as fx:
            original = fx.scope.reserve
            declined = []

            def decline(spec, *, _reserve=original, **kwargs):
                if spec.purpose == 'record-page-keys' and kwargs.get('required') is False:
                    declined.append(spec.total_bytes)
                    return None
                return _reserve(spec, **kwargs)
            with patch.object(fx.scope, 'reserve', side_effect=decline):
                record, segment = open_sealed(fx, M)
            self.assertEqual(declined, [MEMO_CHARGE])
            self.assertIsNone(record._columns._page_keys)
            self.assertEqual(streamed(record), expected)
            self.assertNotIn('retained:record-page-keys',
                             {k for k, v in fx.scope.stats().purpose_bytes.items() if v})
            close_sealed(record, segment)
            del record, segment, original, decline

    def test_verifier_digest_in_parts_agrees_with_the_origin(self):
        value = make_value()
        with sealed(self, value, 'i14-verifier') as fx:
            record, segment = open_sealed(fx, M)
            cols, epoch = record._columns, fx.scope.process_epoch
            descriptor = cols.descriptors['int.bytes']
            held, _, _ = cols._cached_native_owner('int.bytes', 0, descriptor, np.dtype(descriptor['dtype']))
            with held:
                page = held.value
                self.assertIs(type(page), M._NativeChunkPage)
                whole = sha256(b'atlas-typed-chunk-v1\0'+page.descriptor+b'\0'+page.raw).hexdigest()
                self.assertEqual(whole, page.expected_sha256)
                key = M._column_key(epoch, page.binding, page.expected_sha256, page.expected_bytes)
                self.assertEqual(key, O._column_key(epoch, page.binding, page.expected_sha256, page.expected_bytes))
                fields = dict(binding=page.binding, expected_sha256=page.expected_sha256,
                              expected_bytes=page.expected_bytes, raw=page.raw, descriptor=page.descriptor)
            del held, page
            cases = {'genuine': {}, 'raw': dict(raw=b'x'+fields['raw'][1:]),
                     'descriptor': dict(descriptor=b'{}'), 'binding': dict(binding=fields['binding']+b'x'),
                     'long-descriptor': dict(descriptor=b' '*1025), 'raw-type': dict(raw=bytearray(fields['raw'])),
                     'short': dict(raw=fields['raw'][:-1]), 'digest': dict(expected_sha256='0'*64)}
            for label, change in cases.items():
                values = dict(fields, **change)
                mine = M._verify_column_page(key, M._NativeChunkPage(**values))
                theirs = O._verify_column_page(key, O._NativeChunkPage(**values))
                self.assertIs(mine, theirs, label)
                self.assertIs(mine, label == 'genuine', label)
            small = cols.descriptors['node.kind']
            dtype = np.dtype(small['dtype'])
            held = cols._cached_owner('node.kind', small, dtype, small['shape'][0]*dtype.itemsize)
            with held:
                page = held.value
                self.assertIs(type(page), M._ColumnPage)
                fields = dict(binding=page.binding, expected_sha256=page.expected_sha256,
                              expected_bytes=page.expected_bytes, raw=page.raw)
            del held, page
            key = O._column_key(epoch, fields['binding'], fields['expected_sha256'], fields['expected_bytes'])
            for label, change in {'genuine': {}, 'raw': dict(raw=b'\xff'+fields['raw'][1:])}.items():
                values = dict(fields, **change)
                mine = M._verify_column_page(key, M._ColumnPage(**values))
                theirs = O._verify_column_page(key, O._ColumnPage(**values))
                self.assertIs(mine, theirs, label)
                self.assertIs(mine, label == 'genuine', label)
            close_sealed(record, segment)
            del record, segment, cols


if __name__ == '__main__':
    unittest.main()
