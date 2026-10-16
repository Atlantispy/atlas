"""Actual native exact metrics and tiny heat solve with indexed inputs.

Uses the native exact planar assembler, not a production checkpoint. These
controls establish reader/solver equivalence, not physical mesh certification.
"""
from copy import deepcopy
from fractions import Fraction as Q
import gc
import hashlib
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import mimetic_patch as P
import mesh_tables as T
import exterior_mesh_patch as EP


HERE = Path(__file__).resolve().parent
INTEGRATION = HERE.parents[1]/'runtime-integration-r1'
BASE = INTEGRATION/'runtime-src'/'atlas_tectonics'
HEAT = HERE.parents[3]/'heat-repair-20261007'
TEMP_PARENT = HERE.parents[4]  # Short path: Windows Python extensions can still impose MAX_PATH.
_temporary = None


def setUpModule():
    global _temporary, B, E, V, M, WorkBudget, TectonicsError
    if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
        raise RuntimeError('clean process required; do not replace an executing runtime')
    _temporary = tempfile.TemporaryDirectory(prefix='mimetic-', dir=TEMP_PARENT)
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, transform in (('integration_mimetic_heat.py', P.mimetic_source),
                            ('integration_extremum_heat.py', P.extremum_source),
                            ('integration_exterior_mesh.py', EP.transform)):
        target = package/name
        target.write_text(transform(target.read_text(encoding='utf-8')), encoding='utf-8')
    sys.path[:0] = [str(Path(_temporary.name)), str(INTEGRATION/'ram'), str(INTEGRATION/'helpers'), str(HEAT)]
    B = importlib.import_module('atlas_tectonics.integration_volume_bounds')
    E = importlib.import_module('atlas_tectonics.integration_exterior_mesh')
    V = importlib.import_module('atlas_tectonics.integration_volume')
    M = importlib.import_module('atlas_tectonics.integration_mimetic_heat')
    WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
    TectonicsError = importlib.import_module('atlas_tectonics._validation').TectonicsError


def tearDownModule():
    if _temporary is not None:
        assert Path(_temporary.name).resolve().parent == TEMP_PARENT
        _temporary.cleanup()


def mesh_record(budget, epsilon=Q(1)):
    boxes = (V.CartesianCell((0, 0, 0), (epsilon, 1, 1), budget=budget),
             V.CartesianCell((epsilon, 0, 0), (epsilon+1, 1, 1), budget=budget))
    ids = [hashlib.sha256(('logical:'+str(i)).encode()).hexdigest() for i in range(2)]
    with B._Arena(budget) as arena:
        cells, faces = E._assemble([(ident, B._box(box), dict(kind='collar', index=[i, 0, 0],
            physical_support=dict(voxel_id=box.cell_id))) for i, (ident, box) in enumerate(zip(ids, boxes, strict=True))], arena)
    return dict(schema=T.LEGACY, method=T.METHOD, funding_id='a'*64, source={'test': 'actual planar assembler'},
        support_id='b'*64, trajectory_id=T.digest([]), trajectory_segments=[], endpoint='end',
        time_s=M._enc(1), grid_id='c'*64,
        grid_lines=[[M._enc(0), M._enc(epsilon), M._enc(epsilon+1)], [M._enc(0), M._enc(1)], [M._enc(0), M._enc(1)]],
        cells=cells, faces=faces, support_tables={'voxels': {b.cell_id: b.record() for b in boxes}})


def compact(record, budget):
    blobs = {}
    metadata, arrays = T.pack_mesh(record, support_writer=lambda h, raw: blobs.setdefault(h, raw), budget=budget)
    def reader(h, size):
        raw = blobs[h]
        if len(raw) != size:
            raise AssertionError('unexpected support size')
        return raw
    view = T.CompactMesh(metadata, arrays, support_reader=reader, expected_geometry_id=T.digest(record), budget=budget)
    return view


class IndexedMimetic(unittest.TestCase):
    def test_exact_metrics_and_operator_match_without_full_expansion(self):
        budget = WorkBudget(256 << 20)
        raw = mesh_record(budget)
        view = compact(raw, budget)
        resident = budget.reserved_bytes
        native_mesh = E.ExteriorMesh.from_compact(view, budget=budget)
        self.assertEqual(budget.reserved_bytes-resident, 1024)
        self.assertEqual(native_mesh.geometry_id, view.geometry_id)
        self.assertTrue(native_mesh.is_compact)
        self.assertEqual(native_mesh.cell_count, view.cell_count)
        baseline = M.MimeticGeometry(raw, budget=budget)
        with patch.object(T.CompactMesh, 'legacy_record', side_effect=AssertionError('whole mesh export forbidden')):
            actual = M.MimeticGeometry.from_compact(view, budget=budget)
            self.assertEqual(actual.geometry_id, baseline.geometry_id)
            self.assertEqual(actual._cells, baseline._cells)
            self.assertEqual(actual._incidence, baseline._incidence)
            self.assertEqual(actual._face_ids, baseline._face_ids)
            self.assertEqual(actual.cell_id(0), raw['cells'][0]['cell_id'])
            self.assertIsNone(actual._encoded)
            with M.PreparedMimeticHeat3D(baseline, 1., budget=budget) as old:
                with M.PreparedMimeticHeat3D(actual, 1., budget=budget) as new:
                    np.testing.assert_array_equal(old._matrix.toarray(), new._matrix.toarray())
                    before = old.advance([2., 4.], [1., 1.], .125, state_id='same declared input')
                    after = new.advance([2., 4.], [1., 1.], .125, state_id='same declared input')
                    self.assertEqual(before.descriptor(), after.descriptor())
                    for name in before.array_names:
                        np.testing.assert_array_equal(before.array(name), after.array(name))
        del before, after, old, new, actual, baseline, native_mesh, view
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_arbitrary_precision_thin_positive_cells_remain_exact(self):
        budget = WorkBudget(128 << 20)
        raw = mesh_record(budget, Q(1, 2**100))
        view = compact(raw, budget)
        expected = M.MimeticGeometry(raw, budget=budget)
        actual = M.MimeticGeometry.from_compact(view, budget=budget)
        self.assertEqual(actual._cells, expected._cells)
        self.assertEqual(actual._cells[0][0], Q(1, 2**100))
        del expected, actual, view
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_native_geometric_refusals_survive_valid_storage_encoding(self):
        budget = WorkBudget(128 << 20)
        source = mesh_record(budget)
        def volume(r):
            r['cells'][0]['volume_m3'] = M._enc(2)
        def closure(r):
            r['faces'][0]['area_vector_m2'][0] = M._enc(Q(7, 2))
        def outside_centre(r):
            r['cells'][0]['centroid_m'][0] = M._enc(-1)
        def zero_area(r):
            r['faces'][0]['area_vector_m2'] = [M._enc(0)]*3
        def duplicate_incidence(r):
            r['cells'][0]['faces'].append(r['cells'][0]['faces'][0])
        for mutate in (volume, closure, outside_centre, zero_area, duplicate_incidence):
            raw = deepcopy(source)
            mutate(raw)
            view = compact(raw, budget)
            with self.subTest(mutation=mutate.__name__):
                with self.assertRaises(TectonicsError) as before:
                    M.MimeticGeometry(raw, budget=budget)
                with self.assertRaises(TectonicsError) as after:
                    M.MimeticGeometry.from_compact(view, budget=budget)
                self.assertEqual(str(before.exception), str(after.exception))
            del view, before, after
            gc.collect()
            self.assertEqual(budget.reserved_bytes, 0)

    def test_budget_identity_and_explicit_owned_export(self):
        budget = WorkBudget(128 << 20)
        raw = mesh_record(budget)
        view = compact(raw, budget)
        with self.assertRaisesRegex(TectonicsError, 'different budget'):
            M.MimeticGeometry.from_compact(view, budget=WorkBudget(128 << 20))
        actual = M.MimeticGeometry.from_compact(view, budget=budget)
        with self.assertRaisesRegex(TectonicsError, 'explicit owned'):
            actual.record()
        owned = actual.legacy_record()
        self.assertEqual(owned.value, raw)
        del actual, view
        gc.collect()
        self.assertGreater(budget.reserved_bytes, 0)
        del owned
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_failed_validation_retains_charges_while_traceback_is_held(self):
        budget = WorkBudget(128 << 20)
        raw = mesh_record(budget)
        raw['cells'][0]['volume_m3'] = M._enc(2)
        view = compact(raw, budget)
        gc.collect()
        before = budget.reserved_bytes
        errors = []
        try:
            M.MimeticGeometry.from_compact(view, budget=budget)
        except TectonicsError as error:
            errors.append(error)
        else:
            self.fail('invalid exact volume was accepted')
        gc.collect()
        self.assertGreater(budget.reserved_bytes, before)
        errors.clear()
        gc.collect()
        self.assertEqual(budget.reserved_bytes, before)
        del view
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
