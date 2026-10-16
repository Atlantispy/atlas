"""Tiny real-store controls; no historical DB, checkpoint or simulation."""
from concurrent.futures import CancelledError
from copy import deepcopy
from fractions import Fraction as Q
import gc
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[1]/'runtime-integration-r1'
HEAT = HERE.parents[3]/'heat-repair-20261007'
sys.path[:0] = [str(RUNTIME/'runtime-src'), str(RUNTIME/'ram'),
               str(RUNTIME/'helpers'), str(HEAT)]

import numpy as np
from atlas_tectonics import integration_volume_bounds as B
from atlas_tectonics import integration_exterior_mesh as E
from atlas_tectonics import integration_volume as V
from atlas_tectonics.integration_mimetic_heat import _enc
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits, StoreError, _json
import mesh_tables as T
from compact_store import CompactMeshStore, CompactStoreRefused, SUPPORT_ARRAY, descriptor_digest


def limits():
    return StoreLimits(chunk_bytes=256, max_array_bytes=2 << 20,
        max_store_bytes=16 << 20, max_manifest_bytes=256 << 10,
        sqlite_cache_bytes=65536, codec_workspace_bytes=65536)


def fixture(budget):
    box = V.CartesianCell((0, 0, 0), (Q(1, 2**100), 1, 1), budget=budget)
    ident = sha256(b'compact storage fixture').hexdigest()
    with B._Arena(budget) as arena:
        cells, faces = E._assemble([(ident, B._box(box), dict(kind='collar', index=[0, 0, 0],
            physical_support=dict(voxel_id=box.cell_id)))], arena)
    return dict(schema=T.LEGACY, method=T.METHOD, funding_id='a'*64,
        source={'test': 'actual exact planar assembler; storage verification only'},
        support_id='b'*64, trajectory_id=T.digest([]), trajectory_segments=[], endpoint='end',
        time_s=_enc(1), grid_id='c'*64,
        grid_lines=[[_enc(0), _enc(Q(1, 2**100))], [_enc(0), _enc(1)], [_enc(0), _enc(1)]],
        cells=cells, faces=faces, support_tables={'voxels': {box.cell_id: box.record()}})


def observed(view):
    header = view.header()
    cells, faces = [], []
    for index in range(view.cell_count):
        owned = view.cell(index)
        cells.append(T.digest(owned.value))
    for index in range(view.face_count):
        owned = view.face(index)
        faces.append(T.digest(owned.value))
    return dict(geometry_id=view.geometry_id, header_sha256=T.digest(header.value),
                cell_hashes=cells, face_hashes=faces, supports=list(view.support_bindings()))


def child(path, key, geometry):
    budget = WorkBudget(128 << 20)
    with ArrayStore(path, limits(), budget=budget) as store:
        adapter = CompactMeshStore(store, budget=budget)
        before = store.change_token()
        with patch.object(T.CompactMesh, 'legacy_record', side_effect=AssertionError('whole record forbidden')):
            view = adapter.open(key, expected_geometry_id=geometry)
            result = observed(view)
            assert store.change_token() == before
            del view
    gc.collect()
    assert budget.reserved_bytes == 0, budget.statistics()
    print(json.dumps(dict(result=result, reserved_after_close=0), sort_keys=True))


def caught(action, kind):
    try:
        action()
    except kind as failure:
        return failure
    raise AssertionError('expected actual failure')


class CompactStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='.compact-store-', dir=HERE.parents[4])
        self.path = Path(self.temporary.name)/'fixture.sqlite'
        self.budget = WorkBudget(128 << 20)
        self.store = ArrayStore(self.path, limits(), budget=self.budget)
        self.adapter = CompactMeshStore(self.store, budget=self.budget)
        self.record = fixture(self.budget)
        self.geometry = T.digest(self.record)
        self.metadata, self.arrays = T.pack_mesh(self.record,
            support_writer=self.adapter.support_writer, budget=self.budget)

    def tearDown(self):
        self.arrays = self.metadata = None
        self.store.close()
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temporary.cleanup()

    def publish(self, **kwargs):
        return self.adapter.publish(self.metadata, self.arrays,
            expected_geometry_id=self.geometry, **kwargs)

    def test_independent_process_exact_reopen_no_legacy_expansion(self):
        key = self.publish(source_producer={'execution_identity': 'd'*64, 'execution_mode': 'strict'})
        with patch.object(T.CompactMesh, 'legacy_record', side_effect=AssertionError('whole record forbidden')):
            view = self.adapter.open(key, expected_geometry_id=self.geometry)
            expected = observed(view)
            self.assertEqual(expected['cell_hashes'], [T.digest(row) for row in self.record['cells']])
            self.assertEqual(expected['face_hashes'], [T.digest(row) for row in self.record['faces']])
            del view
        self.store.close()
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
            '--child', str(self.path), key, self.geometry], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['result'], json.loads(json.dumps(expected)))
        self.assertEqual(data['reserved_after_close'], 0)
        self.store = ArrayStore(self.path, limits(), budget=self.budget)

    def test_second_snapshot_exact_chunks_reused_original_preserved(self):
        first = self.publish(source_producer={'producer': 'original'})
        previous = self.store.metadata(first)
        before = self.store.statistics()
        second = self.publish(source_producer={'producer': 'successor'}, parent_snapshot=first)
        after = self.store.statistics()
        self.assertNotEqual(first, second)
        self.assertEqual(before['unique_chunks'], after['unique_chunks'])
        self.assertEqual(before['encoded_payload_bytes'], after['encoded_payload_bytes'])
        self.assertEqual(after['snapshots'], before['snapshots']+1)
        self.assertEqual(self.store.metadata(first), previous)
        self.assertEqual(self.publish(source_producer={'producer': 'original'}), first)

    def test_interruption_after_staging_rolls_back_root_and_new_chunks(self):
        before = self.store.statistics()
        def interrupted():
            raise CancelledError('interrupt at final atomic publication')
        with self.assertRaisesRegex(CancelledError, 'final atomic'):
            self.publish(publication_check=interrupted)
        after = self.store.statistics()
        for field in ('snapshots', 'unique_chunks', 'encoded_payload_bytes'):
            self.assertEqual(before[field], after[field])
        self.assertEqual(before['snapshots'], 1)  # Only the separately staged support.

    def test_early_and_late_cancel_leave_no_root(self):
        cancel = threading.Event()
        cancel.set()
        before = self.store.statistics()['snapshots']
        with self.assertRaises(CancelledError):
            self.publish(cancel=cancel)
        cancel.clear()
        with self.assertRaises(CancelledError):
            self.publish(cancel=cancel, publication_check=cancel.set)
        self.assertEqual(self.store.statistics()['snapshots'], before)

    def test_support_binding_refuses_wrong_hash_length_and_corruption(self):
        support = next(iter(self.record['support_tables']['voxels'].values()))
        raw = T.canonical(support)
        content = sha256(raw).hexdigest()
        with self.assertRaises(CompactStoreRefused):
            self.adapter.support_writer('f'*64, raw)
        with self.assertRaises(CompactStoreRefused):
            self.adapter.support_reader(content, len(raw)+1)
        key = self.publish()
        with self.store._read_scope():
            manifest = self.store._manifest(key)
        self.assertEqual(manifest['arrays'][SUPPORT_ARRAY]['shape'], [len(raw)])
        chunk = manifest['arrays'][SUPPORT_ARRAY]['chunks'][0]
        self.store._db.execute('UPDATE chunks SET payload=? WHERE id=?', (b'corrupt', chunk))
        with self.assertRaises(StoreError):
            self.adapter.open(key, expected_geometry_id=self.geometry)

    def test_many_supports_pack_into_one_root_array_within_manifest_limit(self):
        """Caps fix: the r9 head mesh has about 2,024 supports, one root array each.

        One array per support puts the root, its link and every workflow alias
        set over the 1 MiB manifest limit. Here 1,100 supports would need 256 B of
        manifest projection each, over this store's 256 KiB, before any chunk.
        The root holds the codec columns plus ONE packed array; every blob reads
        back exactly, from only the chunks covering its bytes.
        """
        record = deepcopy(self.record)
        table = {sha256(str(i).encode()).hexdigest(): {'fixture': i, 'pad': 'p'*(i % 300)} for i in range(1100)}
        record['support_tables']['differential_supports'] = table
        self.assertGreater(256*len(table), self.store.limits.max_manifest_bytes)
        geometry = T.digest(record)
        metadata, arrays = T.pack_mesh(record, support_writer=self.adapter.support_writer, budget=self.budget)
        key = self.adapter.publish(metadata, arrays, expected_geometry_id=geometry)
        with self.store._read_scope():
            manifest = self.store._manifest(key)
        self.assertEqual(set(manifest['arrays']), {'mesh:'+n for n in metadata['arrays']} | {SUPPORT_ARRAY})
        self.assertEqual({n: descriptor_digest(row) for n, row in manifest['arrays'].items()},
                         {n: self.store.reference(key, n).descriptor_sha256 for n in manifest['arrays']})
        blobs = {}
        for value in [*table.values(), *record['support_tables']['voxels'].values()]:
            raw = T.canonical(value)
            blobs[sha256(raw).hexdigest()] = raw
        offsets, position = {}, 0
        for content in sorted(blobs):
            offsets[content] = position
            position += len(blobs[content])
        self.assertEqual(self.store.metadata(key)['supports'], {c: len(b) for c, b in blobs.items()})
        self.assertEqual(manifest['arrays'][SUPPORT_ARRAY]['shape'], [position])
        width = self.store.limits.chunk_bytes
        view = self.adapter.open(key, expected_geometry_id=geometry)
        real, reads = self.store._chunk, []
        def counted(*args, **kwargs):
            reads.append(args[0])
            return real(*args, **kwargs)
        with patch.object(self.store, '_chunk', side_effect=counted), \
                patch.object(self.store, 'get', side_effect=AssertionError('full snapshot load forbidden')):
            for ident, value in table.items():
                content = sha256(T.canonical(value)).hexdigest()
                start, end = offsets[content], offsets[content]+len(blobs[content])
                before = len(reads)
                owned = view.support('differential_supports', ident)
                self.assertEqual(owned.value, value)
                self.assertEqual(len(reads)-before, (end-1)//width-start//width+1)
                del owned
        self.assertTrue(any(offsets[c] % width and offsets[c]//width != (offsets[c]+len(b)-1)//width
                            for c, b in blobs.items()))  # some blobs straddle chunk boundaries
        del view

    def test_root_packed_support_layout_tamper_refused(self):
        key = self.publish()
        with self.store._read_scope():
            manifest = self.store._manifest(key)
        content, size = next(iter(manifest['metadata']['supports'].items()))
        references = {name: self.store.reference(key, name) for name in manifest['arrays']}
        missing = {n: r for n, r in references.items() if n != SUPPORT_ARRAY}
        per_support = dict(missing, **{'support:'+content: self.store.reference(key, SUPPORT_ARRAY)})
        cases = (('shorter packed array', dict(references, **{SUPPORT_ARRAY: np.zeros(size-1, dtype=np.uint8)}), None),
                 ('missing packed array', missing, None),
                 ('extra per-support array', dict(per_support, **{SUPPORT_ARRAY: references[SUPPORT_ARRAY]}), None),
                 ('v1 per-support root', per_support, 'atlas.compact-mesh-store.v1'))
        for label, arrays, schema in cases:
            with self.subTest(label):
                record = dict(manifest['metadata'], source_producer={'forged': label})
                if schema is not None:
                    record['schema'] = schema
                forged = sha256(_json(record)).hexdigest()
                self.store.put(forged, arrays, record, budget=self.budget)
                with self.assertRaisesRegex(CompactStoreRefused,
                        'packed support descriptor|array inventory|invalid compact mesh root'):
                    self.adapter.open(forged, expected_geometry_id=self.geometry)

    def test_root_tamper_and_expected_geometry_refused(self):
        key = self.publish()
        with self.assertRaisesRegex(CompactStoreRefused, 'expected geometry'):
            self.adapter.open(key, expected_geometry_id='f'*64)
        with self.store._read_scope():
            manifest = self.store._manifest(key)
        manifest['metadata']['source_producer'] = {'invented': 'new producer'}
        raw = _json(manifest)
        self.store._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?',
                              (raw, sha256(raw).hexdigest(), key))
        with self.assertRaises(CompactStoreRefused):
            self.adapter.open(key, expected_geometry_id=self.geometry)

    def test_budget_refusal_leaves_no_root_or_retained_lease(self):
        before = self.store.statistics()['snapshots']
        used = self.budget.reserved_bytes
        with self.budget.reserve(self.budget.max_bytes-used-1024, category='fixture-pressure'):
            with self.assertRaises(MemoryLimitError):
                self.publish()
        self.assertEqual(self.budget.reserved_bytes, used)
        self.assertEqual(self.store.statistics()['snapshots'], before)

    def test_open_never_gets_complete_support_collection(self):
        key = self.publish()
        with patch.object(self.store, 'get', side_effect=AssertionError('full snapshot load forbidden')):
            view = self.adapter.open(key, expected_geometry_id=self.geometry)
            self.assertEqual(view.geometry_id, self.geometry)
            for ident, expected in self.record['support_tables']['voxels'].items():
                owned = view.support('voxels', ident)
                self.assertEqual(owned.value, expected)
                del owned
            del view

    def test_publication_uses_validated_owned_arrays_not_mutable_caller_aliases(self):
        metadata = deepcopy(self.metadata)
        arrays = {name: value.copy() for name, value in self.arrays.items()}
        original = self.store.put
        def mutate_then_put(*args, **kwargs):
            arrays['c.id'][0, 0] = 999999
            metadata['header']['source'] = {'mutated': True}
            return original(*args, **kwargs)
        with patch.object(self.store, 'put', side_effect=mutate_then_put):
            key = self.adapter.publish(metadata, arrays, expected_geometry_id=self.geometry)
        view = self.adapter.open(key, expected_geometry_id=self.geometry)
        row = view.cell(0)
        self.assertEqual(row.value, self.record['cells'][0])
        del row, view

    def test_support_failure_retains_buffer_charge_with_external_traceback(self):
        support = next(iter(self.record['support_tables']['voxels'].values()))
        raw = T.canonical(support)
        content = sha256(raw).hexdigest()
        key = self.adapter.support_writer(content, raw)
        before = self.budget.reserved_bytes
        failure = caught(lambda: self.adapter._read_bytes(key, 'bytes', len(raw), 'f'*64),
                         CompactStoreRefused)
        self.assertIn('content hash', str(failure))
        held_traceback = failure.__traceback__
        failure.__traceback__ = None
        del failure
        gc.collect()
        charge = self.budget.statistics()['categories']['compact-support-read']
        self.assertGreaterEqual(charge, 2*len(raw)+65536+8*self.store.limits.max_manifest_bytes)
        self.assertGreater(self.budget.reserved_bytes, before)
        del held_traceback
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)

    def test_open_refusal_retains_loaded_arrays_and_manifest_with_external_traceback(self):
        original = self.publish()
        with self.store._read_scope():
            manifest = self.store._manifest(original)
        record = deepcopy(manifest['metadata'])
        record['codec_metadata']['arrays']['c.id']['sha256'] = 'f'*64
        corrupt_key = sha256(_json(record)).hexdigest()
        references = {name: self.store.reference(original, name) for name in manifest['arrays']}
        self.store.put(corrupt_key, references, record, budget=self.budget)
        before = self.budget.reserved_bytes
        failure = caught(lambda: self.adapter.open(corrupt_key, expected_geometry_id=self.geometry),
                         T.MeshTablesRefused)
        self.assertIn('array byte identity', str(failure))
        held_traceback = failure.__traceback__
        failure.__traceback__ = None
        del failure
        gc.collect()
        categories = self.budget.statistics()['categories']
        total = sum(value.nbytes for value in self.arrays.values())
        self.assertGreaterEqual(categories['compact-store-open-arrays'], 2*total+65536)
        self.assertGreaterEqual(categories['compact-store-open-metadata'], 8*self.store.limits.max_manifest_bytes)
        del held_traceback
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)

    def test_publish_failure_retains_metadata_with_external_traceback(self):
        before = self.budget.reserved_bytes
        def refuse():
            raise CancelledError('held publication failure')
        failure = caught(lambda: self.publish(publication_check=refuse), CancelledError)
        held_traceback = failure.__traceback__
        failure.__traceback__ = None
        del failure
        gc.collect()
        self.assertGreaterEqual(self.budget.statistics()['categories']['compact-store-publication-metadata'],
                                8*self.store.limits.max_manifest_bytes)
        self.assertGreater(self.budget.reserved_bytes, before)
        del held_traceback
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--child':
        child(*sys.argv[2:])
    else:
        unittest.main(verbosity=2)
