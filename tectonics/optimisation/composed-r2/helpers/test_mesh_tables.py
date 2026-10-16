"""Focused tiny real-geometry tests; no original database or scientific run."""
from copy import deepcopy
from fractions import Fraction as Q
import gc
from hashlib import sha256
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent.parent / 'runtime-integration-r1' / 'runtime-src'
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import mesh_tables as M
from atlas_tectonics import integration_exterior_mesh as E
from atlas_tectonics import integration_volume as V
from atlas_tectonics import integration_volume_bounds as B
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


def small_mesh_record(budget, *, wide=False):
    """Actual E._assemble two-box mesh, with the complete native restore header.

    This is synthetic fixture provenance, never an admitted physical endpoint.
    Optional translation exercises integer widths beyond signed/unsigned64.
    """
    start = Q((1 << 90)+1, (1 << 91)+3) if wide else Q(0)
    boxes = [V.CartesianCell((start+i, 0, 0), (start+i+1, 1, 1), budget=budget) for i in range(2)]
    keys = [sha256(('fixture-cell-'+str(i)).encode()).hexdigest() for i in range(2)]
    candidates = []
    for i, (box, key) in enumerate(zip(boxes, keys)):
        candidates.append((key, B._box(box), dict(kind='collar', index=[i, 0, 0],
            logical_cell_id=key, physical_cell_id=box.cell_id, physical_support={'voxel_id': box.cell_id},
            physical_volume_bounds_m3=[E._enc(1), E._enc(1)], geometry_volume_max_deviation_m3=E._enc(0))))
    with B._Arena(budget) as arena:
        cells, faces = E._assemble(candidates, arena)
    return dict(schema=M.LEGACY, method=E.METHOD, funding_id=sha256(b'fixture-funding').hexdigest(),
        source={'fixture_only': True}, support_id=sha256(b'fixture-support').hexdigest(),
        trajectory_id=M.digest([]), trajectory_segments=[], endpoint='end', time_s=E._enc(0),
        grid_id=sha256(b'fixture-grid').hexdigest(),
        grid_lines=[[E._enc(start+i) for i in range(3)], [E._enc(0), E._enc(1)], [E._enc(0), E._enc(1)]],
        cells=cells, faces=faces, support_tables={'voxels': {b.cell_id: b.record() for b in boxes}},
        geometry_volume_max_deviation_m3=E._enc(0), max_geometry_volume_error_m3=E._enc(0),
        scope='tiny real exact metrics; synthetic source provenance; not production acceptance')


def compact_fixture(record=None, budget=None):
    budget = WorkBudget(1 << 30) if budget is None else budget
    record = small_mesh_record(budget) if record is None else record
    blobs, reads = {}, []
    def write(ident, raw):
        if ident in blobs and blobs[ident] != raw:
            raise AssertionError('content collision')
        blobs[ident] = raw
    def read(ident, size):
        reads.append((ident, size))
        return blobs[ident]
    metadata, arrays = M.pack_mesh(record, support_writer=write, budget=budget)
    view = M.CompactMesh(metadata, arrays, support_reader=read,
                         expected_geometry_id=M.digest(record), budget=budget)
    return view, metadata, arrays, blobs, reads


def rehash(metadata, arrays, name):
    metadata['arrays'][name] = dict(dtype=arrays[name].dtype.str,
        shape=list(arrays[name].shape), sha256=sha256(arrays[name].tobytes()).hexdigest())


class MeshTablesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = small_mesh_record(WorkBudget(1 << 30))

    def test_actual_native_geometry_hash_and_roundtrip(self):
        from atlas_tectonics.integration_mimetic_heat import MimeticGeometry
        budget = WorkBudget(1 << 30)
        native = MimeticGeometry(self.record, budget=budget)
        view, metadata, arrays, blobs, _ = compact_fixture(self.record, budget)
        self.assertEqual(view.geometry_id, native.geometry_id)
        self.assertEqual(b''.join(view.iter_legacy_json()), M.canonical(self.record))
        self.assertEqual(view.legacy_record().value, self.record)
        self.assertEqual(metadata['schema'], M.SCHEMA)
        self.assertEqual((view.cell_count, view.face_count), (2, 11))
        self.assertIs(view.budget, budget)
        self.assertEqual(sorted(view.support_bindings()), sorted((k, len(v)) for k, v in blobs.items()))
        self.assertTrue(all(not a.flags.writeable for a in arrays.values()))

    def test_exact_large_integer_rational_pool(self):
        budget = WorkBudget(1 << 30)
        record = small_mesh_record(budget, wide=True)
        view, _, arrays, _, _ = compact_fixture(record, budget)
        self.assertGreater(max(int(b-a) for a, b in zip(arrays['int.offset'][:-1], arrays['int.offset'][1:])), 8)
        self.assertEqual(view.legacy_record().value, record)
        for i, cell in enumerate(record['cells']):
            owned = view.cell_metrics(i)
            self.assertEqual(owned.value['volume'], Q(int(cell['volume_m3'][0], 16), int(cell['volume_m3'][1], 16)))
            self.assertEqual(owned.value['centre'], tuple(Q(int(n, 16), int(d, 16)) for n, d in cell['centroid_m']))

    def test_indexed_rows_do_not_fetch_support_or_expand_whole_mesh(self):
        view, _, _, _, reads = compact_fixture(self.record)
        reads.clear()
        for i, expected in enumerate(self.record['cells']):
            self.assertEqual(view.cell(i).value, expected)
            self.assertNotIn('support_tables', view.cell(i).value)
        for i, expected in enumerate(self.record['faces']):
            self.assertEqual(view.face(i).value, expected)
            self.assertIsInstance(view.face_metrics(i).value['normal'][0], Q)
        self.assertEqual(reads, [])
        key = next(iter(self.record['support_tables']['voxels']))
        row = view.support('voxels', key)
        self.assertEqual(row.value, self.record['support_tables']['voxels'][key])
        self.assertEqual(len(reads), 1)
        row.value['frame_rule'] = 'caller edit'
        self.assertNotEqual(view.support('voxels', key).value['frame_rule'], 'caller edit')
        with self.assertRaises(M.MeshTablesRefused):
            view.support('voxels', '0'*64)

    def test_pool_sharing_and_csr_are_actual_numeric_arrays(self):
        view, _, arrays, _, _ = compact_fixture(self.record)
        self.assertEqual(arrays['c.id'][0, 0], arrays['c.id'][0, 1])
        self.assertEqual(len(set(map(bytes, arrays['id.bytes']))), len(arrays['id.bytes']))
        self.assertEqual(int(arrays['c.face_offset'][-1]), 12)
        self.assertEqual(sum(int(v) for v in arrays['c.q'][:, 0] == arrays['c.q'][0, 0]), 2)
        self.assertEqual(len(arrays['q.pair']), len({tuple(map(int, row)) for row in arrays['q.pair']}))
        self.assertLess(sum(a.nbytes for a in arrays.values()), len(M.canonical(self.record)))
        self.assertEqual(view.header().value['trajectory_id'], self.record['trajectory_id'])

    def test_optional_fields_roundtrip(self):
        record = deepcopy(self.record)
        cell = record['cells'][0]
        cell.update(volume_centroid_m=deepcopy(cell['centroid_m']), metric_point_kind='strict kernel point; not the volume centroid')
        face = record['faces'][0]
        face.update(cartesian_support=[dict(cell_id=face['owners'][0], physical_voxel_id=cell['physical_cell_id'],
            axis=2, end=0, local_coordinate_m=E._enc(0))], geometry_kind='cartesian',
            relative_advection='actual certified Cartesian face-time material measure',
            boundary_role='fixture', reservoir_cut=dict(cell_id=face['owners'][0], axis=2, end=0))
        record['required_thermal_boundary_faces'] = [face['face_id']]
        record['thermal_shared_lines'] = deepcopy(record['grid_lines'])
        view, *_ = compact_fixture(record)
        self.assertEqual(view.legacy_record().value, record)

    def test_unknown_scientific_fields_refused(self):
        for where in ('header', 'cell', 'face'):
            record = deepcopy(self.record)
            target = record if where == 'header' else record[where+'s'][0]
            target['unrecognised_science'] = 'must not disappear'
            with self.subTest(where=where), self.assertRaises(M.MeshTablesRefused):
                compact_fixture(record)

    def test_noncanonical_rational_and_id_refused(self):
        for value in (['0x2', '0x2'], ['0x1', '-0x1'], ['0X1', '0x1'], ['0x1', '0x0']):
            record = deepcopy(self.record)
            record['cells'][0]['volume_m3'] = value
            with self.subTest(value=value), self.assertRaises(M.MeshTablesRefused):
                compact_fixture(record)
        record = deepcopy(self.record)
        record['cells'][0]['logical_cell_id'] = 'friendly-name-not-an-authenticated-id'
        with self.assertRaises(M.MeshTablesRefused):
            compact_fixture(record)

    def test_byte_corruption_and_expected_identity_refused(self):
        _, metadata, arrays, blobs, _ = compact_fixture(self.record)
        arrays = {k: a.copy() for k, a in arrays.items()}
        arrays['c.sign'][0] *= -1
        with self.assertRaisesRegex(M.MeshTablesRefused, 'byte identity'):
            M.CompactMesh(metadata, arrays, support_reader=lambda h, n: blobs[h],
                          expected_geometry_id=M.digest(self.record), budget=WorkBudget(1 << 30))
        rehash(metadata, arrays, 'c.sign')
        with self.assertRaisesRegex(M.MeshTablesRefused, 'original geometry identity'):
            M.CompactMesh(metadata, arrays, support_reader=lambda h, n: blobs[h],
                          expected_geometry_id=M.digest(self.record), budget=WorkBudget(1 << 30))
        with self.assertRaisesRegex(M.MeshTablesRefused, 'expected geometry ID'):
            M.CompactMesh(metadata, arrays, support_reader=lambda h, n: blobs[h],
                          expected_geometry_id='0'*64, budget=WorkBudget(1 << 30))

    def test_malformed_offsets_masks_pool_indexes_refused(self):
        _, original, source, blobs, _ = compact_fixture(self.record)
        cases = [('c.face_offset', (1,), 1000000), ('c.id', (0, 0), M.NULL),
                 ('c.mask', (0,), 255), ('c.q', (0, 0), M.NULL),
                 ('f.cut', (0, 0), 0), ('f.owner', (0,), M.NULL),
                 ('int.sign', (0,), 7), ('q.pair', (0, 1), M.NULL)]
        for name, position, value in cases:
            metadata, arrays = deepcopy(original), {k: a.copy() for k, a in source.items()}
            arrays[name][position] = value
            rehash(metadata, arrays, name)
            with self.subTest(name=name), self.assertRaises(M.MeshTablesRefused):
                M.CompactMesh(metadata, arrays, support_reader=lambda h, n: blobs[h],
                              expected_geometry_id=M.digest(self.record), budget=WorkBudget(1 << 30))

    def test_changed_or_missing_support_refused_on_every_read(self):
        view, _, _, blobs, _ = compact_fixture(self.record)
        key = next(iter(self.record['support_tables']['voxels']))
        content = M.digest(self.record['support_tables']['voxels'][key])
        blobs[content] = blobs[content][:-1]+b' '
        with self.assertRaisesRegex(M.MeshTablesRefused, 'length/hash'):
            view.support('voxels', key)
        record = deepcopy(self.record)
        record['support_tables']['voxels'].pop(key)
        with self.assertRaisesRegex(M.MeshTablesRefused, 'absent'):
            compact_fixture(record)

    def test_immutable_source_arrays_and_view(self):
        view, _, arrays, _, _ = compact_fixture(self.record)
        with self.assertRaises(ValueError):
            arrays['c.id'].setflags(write=True)
        with self.assertRaises(AttributeError):
            view.geometry_id = '0'*64
        with self.assertRaises(TypeError):
            view._arrays['c.id'] = arrays['c.id'].copy()
        before = view.cell(0).value
        row = view.cell(0)
        row.value['volume_m3'][0] = '0x0'
        self.assertEqual(view.cell(0).value, before)

    def test_storage_payload_has_detached_metadata_and_owned_immutable_arrays(self):
        budget = WorkBudget(1 << 30)
        view, metadata, arrays, blobs, reads = compact_fixture(self.record, budget)
        payload = view.storage_payload()
        meta, stored = payload.value
        self.assertEqual(meta, metadata)
        meta['header']['source']['fixture_only'] = False
        self.assertTrue(view.header().value['source']['fixture_only'])
        self.assertTrue(all(not a.flags.writeable for a in stored.values()))
        escaped = stored['c.id']
        del view, metadata, arrays, blobs, reads, payload, meta, stored
        gc.collect()
        self.assertGreater(budget.reserved_bytes, 0)
        self.assertEqual(escaped.shape, (2, 3))
        del escaped
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_row_array_and_held_error_lifetimes(self):
        budget = WorkBudget(1 << 30)
        view, metadata, arrays, blobs, reads = compact_fixture(self.record, budget)
        baseline = budget.reserved_bytes
        row = view.cell(0)
        self.assertGreater(budget.reserved_bytes, baseline)
        del row
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        escaped = arrays['c.id'][:, 0]
        row = view.cell(0)
        del view, metadata, arrays, blobs, reads
        gc.collect()
        self.assertGreater(budget.reserved_bytes, 0)
        self.assertEqual(row.value['cell_id'], self.record['cells'][0]['cell_id'])
        del row, escaped
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        held = None
        try:
            view, *_ = compact_fixture(self.record, budget)
            with_row = view.cell(0)
            raise RuntimeError('held application error')
        except RuntimeError as error:
            held = error
        self.assertGreater(budget.reserved_bytes, 0)
        del view, with_row, held
        gc.collect()
        # Starred assignment owns the other fixture outputs until cleared.
        del _
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_cancel_never_returns_complete_mesh(self):
        blobs = {}
        def check():
            if blobs:
                raise InterruptedError('cancel after one durable support')
        budget = WorkBudget(1 << 30)
        with self.assertRaises(InterruptedError):
            M.pack_mesh(self.record, support_writer=lambda h, r: blobs.setdefault(h, r), budget=budget, check=check)
        self.assertGreater(len(blobs), 0)
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_escape_width_is_conservative(self):
        for text in ('plain ascii', '\x00'*17, 'a\nb\r\tc', '"\\', '\u007f', '\U0001f642'*7,
                     '\ud800', 'mixed\x00\U0001f642é'):
            value = {'source': [text, -123, 0.25]}
            self.assertGreaterEqual(M._width(value), len(M.canonical(value)))
        record = deepcopy(self.record)
        record['source']['escaped'] = 'x\x00\n\U0001f642'
        self.assertEqual(compact_fixture(record)[0].legacy_record().value, record)

    def test_structural_decode_charge_counts_only_real_syntax(self):
        empty_objects = [{} for _ in range(1000)]
        raw = M.canonical(empty_objects)
        self.assertGreater(M._decode_charge(raw), 64*len(raw))
        plain = M.canonical('x'*1000)
        quoted_syntax = M.canonical('{[,:}'*200)
        self.assertEqual(M._decode_charge(plain), M._decode_charge(quoted_syntax))

    def test_optional_import_tables_are_funded_before_pool_or_support_writes(self):
        header = {k: v for k, v in self.record.items() if k not in M.SPECIAL}
        width = sum(map(M._width, (header, self.record['cells'], self.record['faces'],
                                  self.record['grid_lines'])))
        supports = self.record['support_tables']
        largest = max(M._width(v) for table in supports.values() for v in table.values())
        support_count = sum(map(len, supports.values()))
        ordinary_charge = 12*width+4*largest+2048*support_count+65536
        for field, value in (
                ('thermal_shared_lines', deepcopy(self.record['grid_lines'])),
                ('required_thermal_boundary_faces', [self.record['faces'][0]['face_id']])):
            record = deepcopy(self.record)
            record[field] = value
            budget = WorkBudget(ordinary_charge)
            written = []
            with self.subTest(field=field), self.assertRaises(MemoryLimitError):
                M.pack_mesh(record, support_writer=lambda h, r, out=written: out.append(h), budget=budget)
            self.assertEqual(written, [])
            gc.collect()
            self.assertEqual(budget.reserved_bytes, 0)

    def test_support_inventory_scratch_is_funded_separately_from_largest_blob(self):
        header = {k: v for k, v in self.record.items() if k not in M.SPECIAL}
        width = sum(map(M._width, (header, self.record['cells'], self.record['faces'],
                                  self.record['grid_lines'])))
        largest = max(M._width(v) for table in self.record['support_tables'].values() for v in table.values())
        budget = WorkBudget(12*width+4*largest+65536)
        written = []
        with self.assertRaises(MemoryLimitError):
            M.pack_mesh(self.record, support_writer=lambda h, r: written.append(h), budget=budget)
        self.assertEqual(written, [])
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_face_refusal_does_not_retain_unfunded_index_list(self):
        budget = WorkBudget(1 << 30)
        view, metadata, arrays, blobs, reads = compact_fixture(self.record, budget)
        baseline = budget.reserved_bytes
        held = None
        with budget.reserve(budget.max_bytes-baseline-1024, category='fixture-pressure'):
            try:
                view.face(0)
            except MemoryLimitError as failure:
                held = failure.__traceback__
            self.assertIsNotNone(held)
            frame = held
            while frame is not None and frame.tb_frame.f_code.co_name != 'face':
                frame = frame.tb_next
            self.assertIsNotNone(frame)
            self.assertNotIsInstance(frame.tb_frame.f_locals['qindexes'], (list, tuple))
        del held, frame
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        del view, metadata, arrays, blobs, reads
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_streamed_grid_rational_charge_lives_until_yield_is_released(self):
        budget = WorkBudget(1 << 30)
        view, metadata, arrays, blobs, reads = compact_fixture(self.record, budget)
        baseline = budget.reserved_bytes
        stream = view.iter_legacy_json()
        for part in stream:
            if part == b'"grid_lines":':
                break
        before_value = budget.reserved_bytes
        self.assertEqual(next(stream), b'[')
        self.assertEqual(next(stream), b'[')
        self.assertEqual(next(stream), M.canonical(self.record['grid_lines'][0][0]))
        self.assertGreaterEqual(budget.reserved_bytes-before_value, 65536)
        stream.close()
        del stream, part
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        del view, metadata, arrays, blobs, reads
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_support_blob_export_keeps_one_owned_canonical_blob_alive(self):
        budget = WorkBudget(1 << 30)
        view, metadata, arrays, blobs, reads = compact_fixture(self.record, budget)
        baseline = budget.reserved_bytes
        stream = view.support_blobs()
        owned = next(stream)
        ident, raw = owned.value
        self.assertEqual(raw, blobs[ident])
        self.assertEqual(sha256(raw).hexdigest(), ident)
        stream.close()
        del stream
        gc.collect()
        self.assertGreater(budget.reserved_bytes, baseline)
        del owned, raw
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        self.assertEqual({row.value[0] for row in view.support_blobs()}, set(blobs))
        del view, metadata, arrays, blobs, reads
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
