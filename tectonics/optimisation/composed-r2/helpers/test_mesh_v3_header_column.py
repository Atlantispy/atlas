"""A2/H4: mesh v3 root with an IV1-sized header rational, at the real store limits.

The census head mesh header field geometry_volume_max_deviation_m3 is 307,067 B
(one rational pair). r2 moves the canonical header into an authenticated
'header.json' column only when the v3 root metadata would exceed 48 KiB; the
root mesh and every smaller header keep the exact v3 root. The frozen base
module (copied from the review base tree) is loaded under another name to show
byte-identical v3 roots, that r2 reads v3 roots, and that a v3-only reader
refuses the r2 schema. Synthetic provenance only; no historical store.
"""
from copy import deepcopy
import gc
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import tracemalloc
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'), str(HERE.parent), str(HERE)]

from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
import compact_store as NEW
import mesh_tables as M
from segment_store import SegmentBackend
import test_mesh_v3 as F

# Test-only byte copy of the pre-fix compact_store (sha256 bf8cf6a8...), used to prove unchanged output.
BASE_FILE = HERE/'a2ref_compact_store.py'
TMP = HERE.parents[4]/'_t'


def base_module():
    spec = importlib.util.spec_from_file_location('compact_store_base_a2', BASE_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pair_of_bits(num_bits, den_bits):
    return [hex((1 << (num_bits-1)) | 1), hex(1 << (den_bits-1))]


HEAD = pair_of_bits(614_116, 614_105)        # 307,067 B canonical field (census IV1 head)
ROOT = pair_of_bits(35_900, 35_890)          # 17,959 B (census IV0 root is 17,949 B)
FIVE = pair_of_bits(5*614_116, 5*614_105)    # 5x head


class HeaderColumnTests(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='a2-mesh-header')
        self.held = []

    def tearDown(self):
        gc.collect()
        for tmp, stores, candidate in reversed(self.held):
            candidate.close(); stores.close()
        gc.collect(); self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        for tmp, _, _ in self.held:
            tmp.cleanup()

    def mesh(self, value):
        """A fresh real store holding the test_mesh_v3 partition fixture."""
        tmp = tempfile.TemporaryDirectory(prefix='a2-mesh-header-', dir=str(TMP))
        stores = IntervalStoreSet.create_migration(Path(tmp.name)/'catalog.json', workflow_id='a'*64, scope=self.scope)
        candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
        self.held.append((tmp, stores, candidate))
        mesh, record, source, partition, _ = F.fixture(self.scope, candidate)
        changed = deepcopy(record)
        changed['support_tables']['differential_supports'] = record['support_tables']['differential_supports']
        changed['geometry_volume_max_deviation_m3'] = value
        blobs = {}
        metadata, arrays = M.pack_mesh(changed, support_writer=lambda h, raw: blobs.setdefault(h, raw),
                                       budget=self.budget)
        view = M.CompactMesh(metadata, arrays, support_reader=lambda h, n: blobs[h],
                             expected_geometry_id=metadata['geometry_id'], budget=self.budget)
        self.assertEqual(sha256(b''.join(view.iter_legacy_json())).hexdigest(), view.geometry_id)
        return view, source, partition, candidate

    def root(self, candidate, ref):
        segment = SegmentBackend().open(candidate, ref, scope=self.scope)
        try:
            with segment.metadata() as held:
                return bytes(held.value)
        finally:
            segment.close()

    def check_reopen(self, module, candidate, ref, view, source):
        opened = module.CompactMeshStoreV3(candidate, scope=self.scope, support_source=source).open(
            ref, expected_geometry_id=view.geometry_id)
        try:
            self.assertEqual(opened.identity(), ref.identity)
            self.assertEqual(opened.geometry_id, view.geometry_id)
            self.assertEqual(sha256(b''.join(opened.iter_legacy_json())).hexdigest(), view.geometry_id)
            got, expected = opened.header(), view.header()
            self.assertEqual(M.canonical(got.value), M.canonical(expected.value))
            del got, expected
        finally:
            opened.close()

    def test_small_and_root_size_headers_keep_exact_v3_root(self):
        base = base_module()
        for value in (['0x0', '0x1'], ROOT):
            roots = []
            for module in (base, NEW):
                view, source, partition, candidate = self.mesh(value)
                ref = module.CompactMeshStoreV3(candidate, scope=self.scope, support_source=source).publish(
                    view, producer='b'*64)
                roots.append((self.root(candidate, ref), ref.to_wire()))
                if module is NEW:
                    self.assertIn(b'"schema":"atlas.compact-mesh-store.v3"', roots[-1][0])
                    self.assertNotIn(NEW.HEADER_COLUMN.encode(), roots[-1][0])
                    # The frozen v3 reader reads the r2 writer's v3 root, and r2 reads it too.
                    self.check_reopen(base, candidate, ref, view, source)
                    self.check_reopen(NEW, candidate, ref, view, source)
                del view; source.close(); partition.close()
                gc.collect()
            self.assertEqual(roots[0], roots[1])

    def test_iv1_head_and_five_times_header_publish_and_reopen(self):
        base = base_module()
        for label, value in (('head', HEAD), ('five', FIVE)):
            view, source, partition, candidate = self.mesh(value)
            self.assertGreater(len(M.canonical(value)), 300_000)
            # The frozen v3 writer refuses this mesh (the reviewed H4 failure).
            with self.assertRaisesRegex(Exception, 'mesh v3 metadata exceeds bounded root'):
                base.CompactMeshStoreV3(candidate, scope=self.scope, support_source=source).publish(
                    view, producer='b'*64)
            gc.collect()
            ref = NEW.CompactMeshStoreV3(candidate, scope=self.scope, support_source=source).publish(
                view, producer='b'*64)
            root = self.root(candidate, ref)
            self.assertLessEqual(len(root), NEW.V3_INLINE_METADATA_BYTES)
            self.assertIn(NEW.V3_HEADER_SCHEMA.encode(), root)
            self.assertEqual(ref.identity.sha256, view.geometry_id)
            self.check_reopen(NEW, candidate, ref, view, source)
            # A v3-only reader refuses the r2 schema rather than misreading it.
            with self.assertRaisesRegex(Exception, 'unsupported mesh v3 root'):
                base.CompactMeshStoreV3(candidate, scope=self.scope, support_source=source).open(
                    ref, expected_geometry_id=view.geometry_id)
            gc.collect()
            opened = NEW.CompactMeshStoreV3(candidate, scope=self.scope, support_source=source).open(
                ref, expected_geometry_id=view.geometry_id)
            again = NEW.CompactMeshStoreV3(candidate, scope=self.scope, support_source=source).publish(
                opened, producer='b'*64)
            self.assertEqual(again.to_wire(), ref.to_wire())
            opened.close()
            print('A2 H4', label, 'header field bytes', len(M.canonical(value)), 'root bytes', len(root), flush=True)
            del view; source.close(); partition.close()
            gc.collect()

    def test_cancelled_header_column_publish_leaves_no_root(self):
        view, source, partition, candidate = self.mesh(HEAD)
        token = threading.Event()
        token.set()
        with self.assertRaises(Exception):
            NEW.CompactMeshStoreV3(candidate, scope=self.scope, support_source=source).publish(
                view, producer='b'*64, cancel=token)
        gc.collect()
        ref = NEW.CompactMeshStoreV3(candidate, scope=self.scope, support_source=source).publish(
            view, producer='b'*64)
        self.check_reopen(NEW, candidate, ref, view, source)
        del view; source.close(); partition.close()

    def test_header_decode_charge_covers_real_decode(self):
        for value in ({'g': HEAD}, {'a': [[]]*2000}, {'b': list(range(10**6, 10**6+5000))},
                      {'c': ['\u00e9x']*3000}, {'d': [{}]*2000}, {'e': [1.5]*3000}):
            raw = M.canonical(value)
            gc.collect()
            tracemalloc.start()
            decoded = json.loads(raw)
            real = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            del decoded
            charge = NEW._header_decode_charge(raw)
            self.assertLessEqual(real, charge, value.keys())
            if 'g' in value:
                self.assertLessEqual(charge, 1.3*real)
                print('A2 H4 header decode real', real, 'booked', charge, flush=True)
                # Publish encode and the open-time canonical check: one
                # canonical() call each, booked at twice the encoded length.
                decoded = json.loads(raw)
                gc.collect()
                tracemalloc.start()
                again = M.canonical(decoded)
                real = tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()
                self.assertEqual(again, raw)
                del again, decoded
                self.assertLessEqual(real, 2*len(raw)+65536)
                self.assertLessEqual(2*len(raw)+65536, 1.3*real+65536)
                print('A2 H4 header canonical encode real', real, 'booked', 2*len(raw)+65536, flush=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
