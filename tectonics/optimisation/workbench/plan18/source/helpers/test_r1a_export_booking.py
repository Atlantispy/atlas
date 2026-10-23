"""R1a: small-row exports book the structural bound (record_views._export_ref).

Before: rows up to 32 KiB booked 65536+192 x canonical width (about 50x the
real decoded carried parent cells). After: every row books the structural
_decoded_stats bound that rows over 32 KiB already use, computed exactly from
the validated columns (_node_stats), admitted before decode; the C JSON decode
of small rows is kept, over one exact-width buffer.

Checks: booked >= what the export owns (its live memory with a native row's
shallow dict copy held, after a collection, less the state still traced once
the export is closed and collected) and booked + held scratch >= the traced
peak during the export, for adversarial shapes in memory, on a sealed segment
and on an unsealed candidate segment; values, key order, canonical bytes and
identities equal the unmodified reference copy r1aref_record_views; admission
before decode; held-failure funding; the carried parent cells loop; timing.
Failure path (same generation): a stop raised inside nested record decoding
propagates as itself (RecordRef.__exit__ retires instead of closing) and
every reservation returns once its traceback is released.
Tables go to R1A_OUT (default: the temporary folder). tracemalloc is used for
memory only, never while timing.
"""
import gc
import json
import math
import os
import random
import sys
import tempfile
import time
import traceback
import tracemalloc
import unittest
from concurrent.futures import CancelledError
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'))
# Temporary files go to a per-process folder under the system temporary directory unless R1A_TMP names one.
# Nothing may be written inside this composition (HERE.parent): such a folder is refused before it exists.
TMP = Path(os.environ.get('R1A_TMP') or Path(tempfile.gettempdir())/('r1a-%d' % os.getpid()))
OUT = Path(os.environ.get('R1A_OUT', str(TMP)))
for _folder in (TMP, OUT):
    if _folder.resolve().is_relative_to(HERE.parent.resolve()):
        raise RuntimeError('%s is inside the composition %s; set R1A_TMP and R1A_OUT outside it'
                           % (_folder, HERE.parent))
TMP.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TMP)

import r1aref_record_views as REF
import record_tables as T
import record_views as V
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from compact_contracts import ContractError
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
from segment_store import SegmentBackend

T.SPILL_DIRECTORY = str(TMP)
# The unmodified exit (close on every path), kept as the failure-path mutant.
ORIGIN_EXIT = REF.RecordRef.__exit__
# The reference copy dispatches on its own class objects; point them at the
# live classes so REF._export_ref runs the unmodified route on the same refs.
REF.RecordRef, REF.LogicalRecord, REF.LogicalExchange = V.RecordRef, V.LogicalRecord, V.LogicalExchange

OWNED = 64 << 20
SCRATCH = 65536+256*256+T.MAX_DEPTH*1024
FIELDS = tuple(f'{base}_{unit}' for base in ('enthalpy', 'mass', 'volume', 'momentum_x', 'momentum_y',
               'momentum_z', 'entropy', 'salt', 'water', 'carbon', 'iron') for unit in ('j', 'kg', 'm3', 'n'))


def carried_row(i, neighbours=0):
    """Synthetic parent cell of the IV1 state shape: an ID plus 44 exact rationals."""
    rnd = random.Random(i)
    exact = {}
    for name in FIELDS:
        sign = '-' if rnd.random() < 0.3 else ''
        exact[name] = [sign+'0x'+format(rnd.getrandbits(112) | (1 << 111), 'x'),
                       '0x'+format(1 << rnd.randrange(40, 60), 'x')]
    row = {'cell_id': sha256(f'cell-{i}'.encode()).hexdigest(), 'exact': exact,
           'parent_cell_id': sha256(f'parent-{i}'.encode()).hexdigest(),
           'source_key': 'src-é'+str(i % 5), 'volume_m3': ['0x'+format(i+3, 'x'), '0x7']}
    if neighbours:
        row['neighbours'] = [sha256(f'n-{i}-{k}'.encode()).hexdigest() for k in range(neighbours)]
    return row


def shapes():
    escaped = ''.join(chr(c) for c in range(32))+'"\\/'
    tiny = 'a'*32000+'\U0001f600'
    return [
        ('carried-cell-mean', carried_row(1)),
        ('carried-cell-max', carried_row(2, neighbours=255)),
        ('rational-wide-small', ['0x'+'f'*16000, '0x'+'1'+'0'*15000]),
        ('rational-1MiB-magnitude', ['0x'+'f'*(2 << 20), '0x1'+'0'*((2 << 20)-1)]),
        ('nested-arrays-depth-128', json.loads('['*128+']'*128)),
        ('nested-objects-depth-128', json.loads('{"a":'*127+'{}'+'}'*127)),
        ('escaped-controls-quotes', [escaped*170]),
        ('escaped-short-strings', [escaped[i % len(escaped)] for i in range(3600)]),
        ('escaped-keys', {f'{escaped[i % len(escaped)]}{i}': 0 for i in range(2000)}),
        ('non-bmp-escapes', ['\U0001f600'*2700]),
        ('ascii-plus-one-non-bmp', [tiny]),
        ('non-bmp-short-strings', ['\U0001f600', '\U00010000']*1000),
        ('lone-surrogates-bmp', ['\ud800é中ß'*1300]),
        ('many-tiny-keys', {f'k{i}': i % 7 for i in range(3200)}),
        ('many-tiny-keys-empty-arrays', {f'{i:x}': [] for i in range(3500)}),
        ('cjk-keys', {chr(0x4e00+i): None for i in range(2200)}),
        ('large-ints', [(-1)**i*int('9'*4000) for i in range(7)]),
        ('floats', [(-1)**i*1.2345678901234567e-300*(i+1) for i in range(1300)]),
        ('floats-special', [-0.0, 5e-324, 1.7976931348623157e308, 0.1]*800),
        ('empty-arrays', [[] for _ in range(10900)]),
        ('empty-objects', [{} for _ in range(10900)]),
        ('empty-strings', ['' for _ in range(10900)]),
        ('small-ints', [0]*16000),
        ('two-digit-ints', [10+(i % 80) for i in range(10900)]),
        ('bools-nulls', [True, False, None]*2000),
        ('content-ids', [sha256(str(i).encode()).hexdigest() for i in range(480)]),
        ('dag-repeated-subtree', [{'x': [1, 2, 3], 'y': '0x7'}]*1300),
        ('large-route-empty-arrays', [[] for _ in range(30000)]),
    ]


# Candidate reads are verified per column value, so the candidate table runs
# shapes in order of node count (cheapest first) within its time budget. The
# 1 MiB-magnitude row is memory only (over 1 MiB canonical).
CANDIDATE_ORDER = (
    'escaped-controls-quotes', 'non-bmp-escapes', 'ascii-plus-one-non-bmp', 'lone-surrogates-bmp',
    'rational-wide-small', 'large-ints', 'nested-arrays-depth-128', 'nested-objects-depth-128',
    'carried-cell-mean', 'carried-cell-max', 'content-ids', 'dag-repeated-subtree', 'floats', 'escaped-keys',
    'non-bmp-short-strings', 'cjk-keys', 'many-tiny-keys', 'floats-special', 'many-tiny-keys-empty-arrays',
    'escaped-short-strings', 'bools-nulls', 'empty-arrays', 'empty-objects', 'empty-strings', 'two-digit-ints',
    'small-ints', 'large-route-empty-arrays')


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


def streamed(record_or_ref):
    out = bytearray()
    with record_or_ref.iter_json() as stream:
        for block in stream:
            with block:
                out += block.value
    return bytes(out)


def export_new(ref):
    return V._export_ref(ref, max_logical_bytes=OWNED, max_owned_bytes=OWNED)


def export_old(ref):
    return REF._export_ref(ref, max_logical_bytes=OWNED, max_owned_bytes=OWNED)


class _Stores:
    """In-memory, candidate-segment and sealed-segment backings of one value."""
    def __init__(self, scope, directory):
        self.scope, self.directory, self.count = scope, Path(directory), 0
        self.backend = SegmentBackend()

    def publish(self, packed, *, seal):
        self.count += 1
        folder = self.directory/f'p{self.count}'
        folder.mkdir()
        stores = IntervalStoreSet.create_migration(str(folder/'catalog.json'),
                                                   workflow_id='1'*64, scope=self.scope)
        candidate = stores.begin_interval(None, producer_identity='2'*64, runtime_identity='3'*64)
        with packed.metadata_bytes() as held:
            reference = self.backend.publish(candidate, record_schema='test.r1a.v1', identity=packed.identity(),
                metadata=held.value, arrays=packed.array_sources, producer='2'*64,
                representation_profile=T.SCHEMA, scope=self.scope)
        if seal:
            sealed = candidate.seal(reference)
            stores.promote(sealed, expected_catalog_digest=stores.catalog_digest)
            candidate.close()
            segment = self.backend.open(stores, reference, scope=self.scope)
            return V.CompactRecord.from_segment(segment), (segment, stores)
        segment = self.backend.open(candidate, reference, scope=self.scope)
        return V.CompactRecord.from_segment(segment), (segment, candidate, stores)


def purpose(scope, name='retained:record-export'):
    return scope.stats().purpose_bytes.get(name, 0)


def measure(scope, fn, ref):
    """Booked bytes against what the export owns (tracemalloc, memory only).

    peak: traced peak while the export runs (its decode workspace and result).
    owned: traced current with the export and a native row's shallow dict copy
    held, after gc.collect(), less the traced current once both are closed,
    deleted and collected (``residual``). Cyclic garbage the read path makes is
    collected in both terms (the export holds no reference to it), and state
    the reader keeps after the export is closed cancels; both are reported raw.
    The value comes from the warm-up export, allocated before tracing starts.
    """
    warm = fn(ref)
    value = warm.value
    warm.close()
    del warm
    gc.collect()
    before = purpose(scope)
    tracemalloc.start()
    try:
        held = fn(ref)
        raw, peak = tracemalloc.get_traced_memory()
        booked = purpose(scope)-before
        copy = dict(held.value) if type(held.value) is dict else None
        raw_with_copy = tracemalloc.get_traced_memory()[0]
        gc.collect()
        live = tracemalloc.get_traced_memory()[0]
        held.close()
        del held, copy
        gc.collect()
        residual = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    return {'booked': booked, 'peak': peak, 'retained_raw': raw, 'retained_raw_with_copy': raw_with_copy,
            'live_with_copy_gc': live, 'residual_after_close_gc': residual, 'owned': live-residual}, value


def measure_booked(scope, fn, ref):
    """Booked bytes and value only, untraced (the reference route on a candidate,
    where every traced export is several times slower)."""
    before = purpose(scope)
    held = fn(ref)
    booked = purpose(scope)-before
    value = held.value
    held.close()
    return {'booked': booked, 'peak': None, 'owned': None, 'residual_after_close_gc': None}, value


class ExportBookingTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='r1a-export-booking')

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def pack(self, value):
        return T.RecordCodec().pack_record(value, record_schema='test.r1a.v1', scope=self.scope, check=lambda: None)

    def test_shapes_memory_booked_at_or_above_real(self):
        self.shapes_table('memory')

    def test_shapes_candidate_segment_booked_at_or_above_real(self):
        # A candidate cannot serve the sealed page cache: every column value is
        # a verified segment read, so shapes run in order of node count until
        # R1A_CANDIDATE_BUDGET_S (default 45 s) is spent; the rest are listed
        # in the table as not run.
        self.shapes_table('candidate', CANDIDATE_ORDER, budget_s=float(os.environ.get('R1A_CANDIDATE_BUDGET_S', '45')))

    def test_shapes_sealed_segment_booked_at_or_above_real(self):
        self.shapes_table('sealed')

    def shapes_table(self, kind, names=None, budget_s=None):
        # R1A_PART=i/n runs every n-th shape from the i-th (one process each).
        # R1A_FROM=k starts at the k-th shape (candidate runs resumed process by process).
        part = os.environ.get('R1A_PART', '')
        index, count = map(int, part.split('/')) if part else (0, 1)
        first = int(os.environ.get('R1A_FROM', '0'))
        suffix = (f'-part{index}of{count}' if part else '')+(f'-from{first}' if first else '')
        values = dict(shapes())
        order = list(values if names is None else names)[index::count][first:]
        rows, failures, not_run, started = [], [], [], time.perf_counter()
        with tempfile.TemporaryDirectory(prefix='r1a-shapes-') as directory:
            stores = _Stores(self.scope, directory)
            for name in order:
                value = values[name]
                if budget_s is not None and time.perf_counter()-started > budget_s:
                    not_run.append(name)
                    continue
                shape_started = time.perf_counter()
                packed = self.pack(value)
                canonical = T.canonical(value)
                backings = []
                if kind == 'memory':
                    backings.append(('memory', packed, ()))
                elif len(canonical) <= 1 << 20:
                    record, keep = stores.publish(packed, seal=kind == 'sealed')
                    backings.append((kind, record, keep))
                for backing, record, keep in backings:
                    self.assertEqual(streamed(record), canonical)
                    with record.root() as ref:
                        length = ref._logical_length()
                        new, new_value = measure(self.scope, export_new, ref)
                        old, old_value = (measure_booked if kind == 'candidate' else measure)(
                            self.scope, export_old, ref)
                        with V.CompactRecord._read_batch(record):
                            stats = V._node_stats(record, ref.index, OWNED, {})
                            reference_stats = REF._decoded_stats(ref, OWNED, {})
                    self.assertEqual(stats, reference_stats, name)
                    self.assertTrue(same(new_value, old_value), name)
                    self.assertTrue(same(new_value, json.loads(canonical)), name)
                    self.assertEqual(T.canonical(new_value), canonical, name)
                    small = length <= 32768
                    # Small rows hold the preflight scratch through their decode
                    # (traversal stack, exact-width buffer and its str copy);
                    # the large route releases it before decode (unchanged).
                    decode_funding = new['booked']+(SCRATCH if small else 0)
                    decoded, scalar = stats
                    row = {'shape': name, 'backing': backing, 'route': 'small' if small else 'large',
                           'canonical_bytes': length, 'booked_old': old['booked'], 'booked_new': new['booked'],
                           'scratch_held_through_decode': SCRATCH if small else 0,
                           'real_peak_new': new['peak'],
                           'real_owned_new': new['owned'],
                           'booked_over_owned': round(new['booked']/max(new['owned'], 1), 3),
                           'decode_funding_over_peak': round(decode_funding/max(new['peak'], 1), 3),
                           'booked_over_peak_without_scratch': round(new['booked']/max(new['peak'], 1), 3),
                           'info_retained_raw_with_row_copy_new': new['retained_raw_with_copy'],
                           'info_raw_over_booked': round(new['retained_raw_with_copy']/max(new['booked'], 1), 3),
                           'info_live_with_row_copy_gc_new': new['live_with_copy_gc'],
                           'info_residual_after_close_gc_new': new['residual_after_close_gc'],
                           'info_residual_after_close_gc_old': old['residual_after_close_gc'],
                           'info_owned_old': old['owned'],
                           'real_peak_old_join_route': old['peak'],
                           'join_route_peak_over_new_booking':
                               None if old['peak'] is None else round(old['peak']/max(new['booked'], 1), 3),
                           'structural_decoded': decoded, 'largest_scalar': scalar,
                           'alt_retained_decoded_only': decoded+V.OWNER_BYTES,
                           'alt_retained_over_owned': round((decoded+V.OWNER_BYTES)/max(new['owned'], 1), 3),
                           'seconds': round(time.perf_counter()-shape_started, 1)}
                    rows.append(row)
                    print(json.dumps({k: row[k] for k in ('shape', 'backing', 'booked_new', 'real_owned_new',
                                                          'real_peak_new', 'booked_over_owned',
                                                          'decode_funding_over_peak',
                                                          'info_retained_raw_with_row_copy_new', 'seconds')}),
                          file=sys.stderr, flush=True)
                    if new['booked'] < new['owned'] or decode_funding < new['peak']:
                        failures.append(row)
                    if length > 32768:
                        self.assertEqual(new['booked'], old['booked'], name)
                    else:
                        self.assertLessEqual(new['booked'], old['booked'], name)
                    del new_value, old_value
                    if keep:
                        record.close()
                        for item in keep:
                            item.close()
                    del record, keep
                packed.close()
                del backings, packed
                gc.collect()
        (OUT/f'r1a-shapes-{kind}{suffix}.json').write_text(
            json.dumps({'scratch_bytes': SCRATCH, 'part': part or 'all', 'rows': rows,
                        'not_run_time_budget': not_run}, indent=1), encoding='utf8')
        self.assertEqual(failures, [])
        self.assertTrue(rows)

    def test_admission_before_decode_and_refusal_without_decode(self):
        packed = self.pack(carried_row(3))
        events = []
        real_parts, real_loads, real_renderer = V.CompactRecord._parts, V.json.loads, V.CompactRecord._renderer
        def parts(view, node, depth=0, memo=None):
            events.append(('parts', node))
            yield from real_parts(view, node, depth, memo)
        def renderer(view, access):
            # R1: the small route renders canonical bytes from the columns.
            emit = real_renderer(view, access)
            def traced(node, depth, out, limit):
                events.append(('render', node))
                return emit(node, depth, out, limit)
            return traced
        def loads(raw, *args, **kwargs):
            events.append(('loads', len(raw)))
            return real_loads(raw, *args, **kwargs)
        real_owned = V._owned
        def owned(scope, count, factory, purpose='record-output', dependencies=()):
            events.append(('reserve', purpose, count))
            return real_owned(scope, count, factory, purpose, dependencies)
        with packed.root() as ref, V.CompactRecord._read_batch(packed):
            decoded, scalar = V._node_stats(packed, ref.index, OWNED, {})
        charge = 65536+decoded+3*scalar+min(4*scalar, 4*T.CHUNK)
        with patch.object(V.CompactRecord, '_parts', parts), patch.object(V.json, 'loads', loads), \
                patch.object(V.CompactRecord, '_renderer', renderer), \
                patch.object(V, '_owned', owned), packed.root() as ref:
            before = self.scope.stats().retained_bytes
            with self.assertRaisesRegex(ContractError, 'owned export bound exceeded before allocation'):
                V._export_ref(ref, max_logical_bytes=OWNED, max_owned_bytes=charge+V.OWNER_BYTES-1)
            self.assertEqual(events, [])
            self.assertEqual(self.scope.stats().retained_bytes, before)
            with V._export_ref(ref, max_logical_bytes=OWNED, max_owned_bytes=charge+V.OWNER_BYTES) as held:
                self.assertTrue(same(held.value, json.loads(T.canonical(carried_row(3)))))
                self.assertEqual(events[0], ('reserve', 'record-export', charge))
                self.assertTrue(all(kind != 'reserve' for kind, *_ in events[1:]))
                self.assertTrue({'parts', 'render'} & {kind for kind, *_ in events[1:]})
                self.assertEqual(events[-1][0], 'loads')
        packed.close()

    def test_failed_export_keeps_its_charge_while_frames_are_held(self):
        packed = self.pack(carried_row(4))
        for module in (V, REF):
            def broken(raw, *args, **kwargs):
                raise ValueError('injected decode failure')
            base = purpose(self.scope)
            with packed.root() as ref, patch.object(module.json, 'loads', broken):
                try:
                    module._export_ref(ref, max_logical_bytes=OWNED, max_owned_bytes=OWNED)
                except ValueError as error:
                    held = error
                held_charge = purpose(self.scope)-base
                held_run = self.budget.reserved_bytes
                self.assertGreater(held_charge, 0, module.__name__)
                frames = held.__traceback__
                del held
                gc.collect()
                self.assertEqual(purpose(self.scope)-base, held_charge, module.__name__)
                del frames
                gc.collect()
                self.assertEqual(purpose(self.scope), base, module.__name__)
                self.assertLess(self.budget.reserved_bytes, held_run, module.__name__)
        packed.close()

    def carried(self, label, route, trace):
        """The live _carried_start_cells loop: every parent row decoded once, all held."""
        import spatial_validation_patch as SV
        count = 847
        cells = [carried_row(i, neighbours=255 if i % 100 == 0 else 0) for i in range(count)]
        lengths = [len(T.canonical(row)) for row in cells]
        report = {'arm': label, 'rows': count, 'canonical_mean': round(sum(lengths)/count, 1),
                  'canonical_max': max(lengths), 'retained_limit': self.scope.retained_budget.max_bytes}
        record = self.pack({'cells': cells})
        del cells
        gc.collect()
        with record.root() as root, root.field('cells') as cells_ref, patch.object(V, '_export_ref', route):
            base = self.scope.stats().retained_bytes
            previous, held = {}, 0
            if trace:
                tracemalloc.start()
            try:
                for value in SV.rows(cells_ref):
                    previous[value['cell_id']] = value
                    held += 1
                del value
                refused = None
            except MemoryLimitError as error:
                refused = str(error)
            real = tracemalloc.get_traced_memory()[0] if trace else None
            tracemalloc.stop()
            report.update(rows_held=held, refused=refused, booked_total=self.scope.stats().retained_bytes-base,
                          real_total_traced=real)
            previous.clear()
            gc.collect()
        record.close()
        if trace:
            report['booked_over_real'] = round(report['booked_total']/real, 3)
        report['fraction_of_cap'] = round(report['booked_total']/report['retained_limit'], 4)
        report['booked_per_row'] = round(report['booked_total']/max(held, 1))
        (OUT/f'r1a-carried-{label}.json').write_text(json.dumps(report, indent=1), encoding='utf8')
        return report

    def test_carried_parent_cells_fit_retained_scope(self):
        report = self.carried('new', V._export_ref, trace=True)
        self.assertIsNone(report['refused'])
        self.assertEqual(report['rows_held'], 847)
        self.assertGreaterEqual(report['booked_total'], report['real_total_traced'])

    def test_carried_parent_cells_reference_refuses(self):
        report = self.carried('old', REF._export_ref, trace=False)
        self.assertIsNotNone(report['refused'])
        self.assertLess(report['rows_held'], 847)

    def test_timing_many_small_rows(self):
        self.assertFalse(tracemalloc.is_tracing())
        rows = [carried_row(i) for i in range(int(os.environ.get('R1A_TIMING_ROWS', '200')))]
        timings = {}
        with tempfile.TemporaryDirectory(prefix='r1a-timing-') as directory:
            stores = _Stores(self.scope, directory)
            packed = self.pack({'cells': rows})
            record, keep = stores.publish(packed, seal=True)
            for backing, source in (('memory', packed), ('sealed', record)):
                with source.root() as root, root.field('cells') as cells:
                    refs = [cells.at(i) for i in range(len(rows))]
                    def run(fn, refs=refs):
                        start = time.perf_counter()
                        for ref in refs:
                            fn(ref).close()
                        return time.perf_counter()-start
                    def stats_new(refs=refs, source=source):
                        start = time.perf_counter()
                        for ref in refs:
                            with source._read_batch():
                                V._node_stats(source, ref.index, OWNED, {})
                        return time.perf_counter()-start
                    def stats_old(refs=refs, source=source):
                        start = time.perf_counter()
                        for ref in refs:
                            with source._read_batch():
                                REF._decoded_stats(ref, OWNED, {})
                        return time.perf_counter()-start
                    arms = {'export_old': lambda: run(export_old), 'export_new': lambda: run(export_new),
                            'stats_node': stats_new, 'stats_decoded': stats_old}
                    samples = {name: [] for name in arms}
                    for _ in range(3):
                        for name, arm in arms.items():
                            samples[name].append(arm())
                    timings[backing] = {name: {'rows': len(refs), 'min_s': round(min(v), 4),
                                               'median_s': round(sorted(v)[len(v)//2], 4),
                                               'per_row_us': round(1e6*sorted(v)[len(v)//2]/len(refs), 1)}
                                        for name, v in samples.items()}
                    for ref in refs:
                        ref.close()
            record.close()
            for item in keep:
                item.close()
            packed.close()
            del record, keep, packed
        (OUT/'r1a-timing.json').write_text(json.dumps(timings, indent=1), encoding='utf8')


class GuardAborted(CancelledError):
    """Stand-in with the guard's base class (private_heat_continuation_guard_r3.GuardAborted)."""


# Over the 32 KiB small-row route, so the export decodes through nested
# RecordRefs and owned key inventories (as the mesh supports do).
NESTED = {'outer': {'middle': {'inner': list(range(6)), 'tag': 'x'}, 'other': [1, 2, 3]},
          'side': {'deep': {'deeper': {'leaf': 'y'}}}, 'top': 7, 'blob': 'z'*40000}
STOPS = (('GuardAborted', lambda: GuardAborted('Independent guard: free-memory floor')),
         ('CancelledError', lambda: CancelledError('compact operation cancelled')),
         ('TimeoutError', lambda: TimeoutError('Independent guard: timeout')),
         ('ValueError', lambda: ValueError('plain failure inside nested decode')))


def exception_chain(error):
    out, seen = [], set()
    while error is not None and id(error) not in seen and len(out) < 64:
        seen.add(id(error))
        out.append(error)
        error = error.__cause__ if error.__cause__ is not None else error.__context__
    return out


class FailurePathTests(unittest.TestCase):
    """RecordRef.__exit__ on a failure path retires its owners instead of closing them."""
    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='r1a-failure-path')

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def stop_once(self, value, make, stop_at, composite=False):
        """Export with make() raised at the stop_at-th record check.

        Returns None when the stop never fired, else (masked, kinds, released
        without a collection): every traceback in the chain is cleared and
        dropped, then the root and record close (which refuses while borrows
        are held) and the budget must be back at its baseline.
        """
        baseline = self.budget.reserved_bytes
        calls, armed, injected = 0, False, []

        def check():
            nonlocal calls
            if armed:
                calls += 1
                if calls == stop_at:
                    injected.append(make())
                    raise injected[-1]

        record = T.RecordCodec().pack_record(value, record_schema='test.r1a.failure.v1', scope=self.scope,
                                            check=check)
        root = record.root()
        # R1: ordinary references decode from the columns without nested
        # wrappers; a composite whose 'outer' is a composite keeps the wrapper
        # route (owned key inventories and child RecordRefs).
        parts = None
        if composite:
            outer = root.field('outer')
            inner = outer.without(())
            parts = (V.LogicalExchange.from_records(root, outer=inner), inner, outer)
            del outer, inner
        armed, caught = True, None
        try:
            exported = (parts[0] if composite else root).export(max_logical_bytes=1 << 20,
                                                                 max_owned_bytes=16 << 20)
        except (CancelledError, TimeoutError, ValueError, RuntimeError) as error:
            caught = error
        else:
            self.assertTrue(same(exported.value, json.loads(T.canonical(value))))
            exported.close()
            for item in parts or ():
                item.close()
        armed = False
        del parts
        outcome = None
        if caught is not None:
            self.assertEqual(len(injected), 1)
            chain = exception_chain(caught)
            outcome = [caught is not injected[0], tuple(type(item).__name__ for item in chain)]
            self.assertIs(chain[-1], injected[0], outcome)
            for item in chain:
                traceback.clear_frames(item.__traceback__)
                item.__traceback__ = None
            del chain, item
        del caught
        injected.clear()
        root.close()
        record.close()
        del root, record
        if outcome is not None:
            outcome.append(self.budget.reserved_bytes == baseline)
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, baseline, stop_at)
        return outcome

    def every_stop(self, value, make, composite=False):
        results = []
        gc.disable()
        try:
            for stop_at in range(1, 5000):
                outcome = self.stop_once(value, make, stop_at, composite)
                if outcome is None:
                    break
                results.append(outcome)
        finally:
            gc.enable()
        self.assertLess(len(results), 4999)
        return results

    def test_stop_inside_nested_decode_propagates_and_releases(self):
        report = {}
        for value_name, value, composite in (('nested-large-route', NESTED, False),
                                             ('nested-composite-route', NESTED, True),
                                             ('carried-small-route', carried_row(5), False)):
            for kind, make in STOPS:
                results = self.every_stop(value, make, composite)
                self.assertGreater(len(results), 10, (value_name, kind))
                # Fixed: the injected stop itself propagates at every point, with
                # no close refusal in its chain, and everything is released
                # without a collection once its one traceback is cleared.
                self.assertEqual([r for r in results if r[0] or len(r[1]) != 1 or not r[2]], [], (value_name, kind))
                report[f'{value_name}/{kind}'] = {'stop_points': len(results), 'masked': 0,
                                                  'released_without_gc': len(results)}
            # Mutant: the unmodified exit (close on every path) masks the stop
            # where wrappers nest (the original finding), so this test sees it.
            # R1: ordinary references (large and small) no longer nest wrappers;
            # the composite route still does.
            with patch.object(V.RecordRef, '__exit__', ORIGIN_EXIT):
                results = self.every_stop(value, STOPS[0][1], composite)
            masked = sum(1 for r in results if r[0])
            report[f'{value_name}/mutant-origin-exit'] = {'stop_points': len(results), 'masked': masked}
            if composite:
                self.assertGreater(masked, 0)
                self.assertTrue(all(r[1][0] == 'RuntimeError' for r in results if r[0]))
            else:
                self.assertEqual(masked, 0)      # column decode, no nested wrappers
        (OUT/'r1a-failure-path.json').write_text(json.dumps(report, indent=1), encoding='utf8')

    def test_normal_path_exit_closes_as_before(self):
        for label, exit_method in (('new', V.RecordRef.__exit__), ('origin', ORIGIN_EXIT)):
            with patch.object(V.RecordRef, '__exit__', exit_method):
                record = T.RecordCodec().pack_record(NESTED, record_schema='test.r1a.failure.v1',
                                                    scope=self.scope, check=lambda: None)
                root = record.root()
                with root.field('outer') as child:
                    owner = child._owner
                    self.assertIsNotNone(owner._allocation, label)
                self.assertIsNone(owner._allocation, label)          # closed at exit
                self.assertIsNone(child._view, label)
                # A success exit with a live child borrow still refuses.
                with self.assertRaisesRegex(RuntimeError, 'live child borrows'), root.field('outer') as child:
                    kept = child.borrow()
                kept.close()
                child.close()
                # A failed body with a borrow held elsewhere: the new exit
                # keeps the body's error and closes when the borrow drops; the
                # unmodified exit replaced it with the close refusal.
                expected = (ValueError, 'body failure') if label == 'new' else (RuntimeError, 'live child borrows')
                with self.assertRaisesRegex(*expected), root.field('outer') as child:
                    kept = child.borrow()
                    raise ValueError('body failure')
                owner = child._owner
                self.assertIsNotNone(owner._allocation, label)
                kept.close()
                if label == 'new':
                    self.assertIsNone(owner._allocation)             # retired: closed with its last borrow
                else:
                    child.close()
                del owner, child, kept
                root.close()
                record.close()
                del root, record
                gc.collect()


if __name__ == '__main__':
    unittest.main()
