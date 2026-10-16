"""x-mesh-cert (F5): one stream per shared partition support in pack_mesh.

Before: every SharedSupportRecord was decoded three times (width, canonical
blob, geometry stream). Now ONE ref.iter_json stream per shared support feeds
the writer and the geometry hash, its SHA-256 and length checked against the
sealed partition identity; the largest-support width is that identity's exact
canonical length. Output must be byte-identical to W3's module (xmref_mesh_tables,
a byte copy of g3 mesh_tables 0a4319d6...) and to the all-static pack of the
same supports; tampering must refuse; booking must cover the traced peak.
tracemalloc measures memory only (no timing here).
"""
import gc
import json
import random
import sys
import tempfile
import tracemalloc
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
sys.path.insert(0, str(HERE))
from test_mesh_v3 import NativeSupport, fixture  # also sets the runtime path

# isort: split
import mesh_tables as M
import record_views as RV
import xmref_mesh_tables as REF
from atlas_tectonics.resources import WorkBudget
from compact_store import CompactMeshStoreV3
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
from partition_v2 import PartitionV2


def variant(module, record, source, view, kind):
    """Same logical mesh; differential supports as static rows or shared references."""
    tables = dict(record['support_tables'])
    rows = tables['differential_supports']
    ids = sorted(rows)
    if kind == 'static':
        shared = {}
    elif kind == 'source':
        shared = {i: module.SharedSupportRecord(source, i) for i in ids}
    else:  # mixed: even via the sealed PartitionV2, odd stay native static rows
        shared = {i: module.SharedSupportRecord(view, i) for i in ids[::2]}
    tables['differential_supports'] = {i: shared.get(i, rows[i]) for i in ids}
    return dict(record, support_tables=tables)


def token_term(record):
    """x-mesh-booking (A5): the transient token-copy term W3's booking omitted.

    pack_mesh now also books 2*max(L1, P)+256 for the widest scalar token and
    the widest pair of neighbouring scalar tokens (re-check defect 4);
    every other booking term is unchanged from W3's module.
    """
    top = [0, 0, 0]
    header = {k: v for k, v in record.items() if k not in M.SPECIAL}
    for value in [header, record['cells'], record['faces']]+[
            record[f] for f in ('grid_lines', 'thermal_shared_lines', 'required_thermal_boundary_faces') if f in record]:
        M._width(value, 0, top)
    return 2*max(top[0], top[2])+256


def packed(module, record, budget, *, defer=True):
    writes = []
    def writer(content, raw):
        writes.append((content, bytes(raw)))
    if defer:
        metadata, arrays, owner = module.pack_mesh(record, support_writer=writer, budget=budget, _defer_freeze=True)
        size = owner.size
        del owner
    else:
        metadata, arrays = module.pack_mesh(record, support_writer=writer, budget=budget)
        size = None
    columns = {k: (v.dtype.str, v.shape, v.tobytes()) for k, v in arrays.items()}
    return metadata, columns, writes, size, arrays


class SharedSupportPackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='xmc-mesh-', dir=TASK/'_t')
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='xmc-mesh-shared')
        self.stores = IntervalStoreSet.create_migration(Path(self.temp.name)/'catalog.json',
                                                        workflow_id='a'*64, scope=self.scope)
        self.candidate = self.stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        self.mesh, self.record, self.source, self.view, _ = fixture(self.scope, self.candidate, count=6,
                                                                    coverage_bytes=3000)

    def tearDown(self):
        del self.mesh, self.record
        gc.collect()
        self.source.close(); self.view.close()
        self.candidate.close(); self.stores.close(); gc.collect(); self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())
        self.temp.cleanup()

    def test_byte_identical_to_w3_and_to_static_pack(self):
        static = packed(M, variant(M, self.record, self.source, self.view, 'static'), self.budget)
        self.assertEqual(static[0]['geometry_id'], self.mesh.geometry_id)
        for kind in ('static', 'source', 'mixed'):
            with self.subTest(kind=kind):
                new = packed(M, variant(M, self.record, self.source, self.view, kind), self.budget)
                old = packed(REF, variant(REF, self.record, self.source, self.view, kind), self.budget)
                self.assertEqual(new[0], old[0])          # metadata incl. geometry_id and array hashes
                self.assertEqual(new[1], old[1])          # every s.*, c.*, f.* column, byte for byte
                self.assertEqual(new[2], old[2])          # writer calls: same order, content and bytes
                self.assertEqual(new[0], static[0])
                self.assertEqual(new[1], static[1])
                self.assertEqual(new[2], static[2])
                # Exact identity width books no more than W3's decoded upper width
                # (plus the x-mesh-booking token-copy term W3 omitted).
                self.assertLessEqual(new[3], old[3]+token_term(self.record))
                del new, old
                gc.collect()

    def test_segment_refs_identical_after_publication(self):
        refs = []
        for module, kind in ((REF, 'source'), (M, 'source'), (M, 'mixed'), (M, 'static')):
            metadata, _, writes, _, arrays = packed(module, variant(module, self.record, self.source, self.view, kind),
                                                    self.budget, defer=False)
            blobs = dict(writes)
            view = M.CompactMesh(metadata, arrays, support_reader=lambda h, n, blobs=blobs: blobs[h],
                                 expected_geometry_id=metadata['geometry_id'], budget=self.budget)
            del arrays
            ref = CompactMeshStoreV3(self.candidate, scope=self.scope,
                                     support_source=self.source).publish(view, producer='b'*64)
            refs.append(ref.to_wire())
            del view
            gc.collect()
        self.assertEqual(refs[1], refs[0])
        self.assertEqual(refs[2], refs[0])
        self.assertEqual(refs[3], refs[0])

    def test_one_stream_per_shared_support_and_no_decode(self):
        record = variant(M, self.record, self.source, self.view, 'source')
        count = len(record['support_tables']['differential_supports'])
        original = RV.RecordRef.iter_json
        streams = []
        def counted(ref, *args, **kwargs):
            streams.append(ref.index)
            return original(ref, *args, **kwargs)
        with patch.object(RV.RecordRef, 'iter_json', counted), \
                patch.object(RV, '_export_ref', side_effect=AssertionError('shared support decoded')), \
                patch.object(M.SharedSupportRecord, 'open', side_effect=AssertionError('shared support exported')):
            result = packed(M, record, self.budget)
        self.assertEqual(len(streams), count)
        self.assertEqual(result[0]['geometry_id'], self.mesh.geometry_id)

    def _refused(self, record, regex=None):
        gc.collect()
        before = self.budget.reserved_bytes
        writes = []
        with self.assertRaises(ValueError) as caught:
            M.pack_mesh(record, support_writer=lambda h, raw: writes.append(h), budget=self.budget)
        if regex is not None:
            self.assertRegex(str(caught.exception), regex)
        del caught
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)

    def test_tampered_identity_or_body_refused(self):
        original = PartitionV2.support_identity
        def forged_hash(view, support_id):
            found = original(view, support_id)
            flipped = ('0' if found.sha256[0] != '0' else '1')+found.sha256[1:]
            return replace(found, sha256=flipped)
        def forged_length(view, support_id):
            found = original(view, support_id)
            return replace(found, canonical_bytes=found.canonical_bytes+1)
        mixed = variant(M, self.record, self.source, self.view, 'mixed')
        for forged in (forged_hash, forged_length):
            with self.subTest(forged=forged.__name__), patch.object(PartitionV2, 'support_identity', forged):
                self._refused(mixed, 'fresh support differs from compact partition')
        # Body tamper below the authenticated identity: the support's own
        # coverage text changes by one byte inside the compact stream.
        parts = RV.CompactRecord._parts
        def tampered(record, node, depth=0, memo=None):
            for part in parts(record, node, depth, memo):
                yield part.replace(b'xxxx', b'xxxy', 1) if type(part) is bytes else part
        for kind in ('mixed', 'source'):
            with self.subTest(body=kind), patch.object(RV.CompactRecord, '_parts', tampered):
                self._refused(variant(M, self.record, self.source, self.view, kind),
                              'fresh support differs from compact partition|streamed support identity differs')

    def test_booking_covers_traced_peak(self):
        record = variant(M, self.record, self.source, self.view, 'source')
        gc.collect()
        base_booked = self.budget.reserved_bytes
        self.budget._peak = self.budget._used
        tracemalloc.start()
        base = tracemalloc.get_traced_memory()[0]
        try:
            metadata, arrays, owner = M.pack_mesh(record, support_writer=lambda h, raw: None, budget=self.budget,
                                                  _defer_freeze=True)
            real = tracemalloc.get_traced_memory()[1]-base
        finally:
            tracemalloc.stop()
        booked = self.budget.peak_reserved_bytes-base_booked
        self.assertLessEqual(real, booked)
        self.assertLessEqual(real, owner.size)
        del metadata, arrays, owner


class WidthFastPathTests(unittest.TestCase):
    def test_width_identical_to_w3_formula(self):
        rng = random.Random(11)
        alphabet = [chr(c) for c in range(128)]+['é', ' ', '\ud800', '\U0001f642']
        texts = ['', '"', '\\', '\x7f', '\x1f', ' ', '~', 'plain', '0x'+'f'*4000, '"\\'*50]
        texts += [''.join(rng.choice(alphabet) for _ in range(rng.randrange(0, 40))) for _ in range(3000)]
        texts += [''.join(chr(rng.randrange(32, 127)) for _ in range(rng.randrange(0, 80))) for _ in range(3000)]
        for text in texts:
            self.assertEqual(M._width(text), REF._width(text), repr(text))
            self.assertEqual(M._width({'k': [text, 1, 2.5, None, True]}), REF._width({'k': [text, 1, 2.5, None, True]}))
            if text.isascii() and text.isprintable():
                self.assertGreaterEqual(M._width(text), len(json.dumps(text)))
        record = json.loads(json.dumps({'cells': [[hex(rng.getrandbits(4000)), 'a"b\\c', '\x00']]*50}))
        self.assertEqual(M._width(record), REF._width(record))

    def test_static_differential_supports_unchanged_without_partition(self):
        from test_mesh_tables import small_mesh_record
        budget = WorkBudget(1 << 30)
        record = small_mesh_record(budget)
        row = {'kind': 'native', 'coverage': 'x'*100}
        record['support_tables']['differential_supports'] = {M.digest(row): NativeSupport(row)}
        new = packed(M, record, budget)
        old = packed(REF, record, budget)
        self.assertEqual(new[:3], old[:3])
        self.assertEqual(new[3], old[3]+token_term(record))
        self.assertEqual(new[0]['geometry_id'], sha256(b''.join(REF.iter_input_json(record))).hexdigest())
        del new, old
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
