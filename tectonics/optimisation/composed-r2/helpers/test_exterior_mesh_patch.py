"""Tiny actual native wrapper controls, not a physical mesh acceptance."""
import ast
from copy import deepcopy
from fractions import Fraction
import gc
import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import exterior_mesh_patch as P


HERE = Path(__file__).resolve().parent
INTEGRATION = HERE.parents[1]/'runtime-integration-r1'
BASE = INTEGRATION/'runtime-src'/'atlas_tectonics'
_temporary = None
_old_path = None


def setUpModule():
    global _temporary, _old_path, E, WorkBudget
    if any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.') for name in sys.modules):
        raise RuntimeError('fresh process required; no live runtime patching')
    _temporary = tempfile.TemporaryDirectory(prefix='em-', dir=HERE)
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    target = package/'integration_exterior_mesh.py'
    target.write_text(P.transform(target.read_bytes().decode('utf8')), encoding='utf8')
    _old_path = list(sys.path)
    sys.path[:0] = [str(Path(_temporary.name)), str(INTEGRATION/'ram'), str(INTEGRATION/'helpers'),
                   str(HERE.parents[3]/'heat-repair-20261007')]
    E = importlib.import_module('atlas_tectonics.integration_exterior_mesh')
    WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget


def tearDownModule():
    if _old_path is not None:
        sys.path[:] = _old_path
    if _temporary is not None:
        assert Path(_temporary.name).resolve().parent == HERE
        _temporary.cleanup()


def empty_legacy_record():
    return dict(schema='atlas.source-bound-exterior-thermal-mesh.v1', method=E.METHOD,
        funding_id='f'*64, source={'fixture': 'explicitly synthetic archive'}, support_id='a'*64,
        trajectory_id=E._hash([]), trajectory_segments=[], time_s=['0x0', '0x1'],
        grid_id='b'*64, grid_lines=[[['0x0', '0x1'], ['0x1', '0x1']]]*3,
        endpoint='end', cells=[], faces=[], support_tables={})


def tiny_record(budget, *, differential=False):
    """Actual exact cube metric producer, synthetic archive/support authority."""
    from atlas_tectonics import integration_volume_bounds as B
    box = E.V.CartesianCell((0, 0, 0), (1, 1, 1), budget=budget)
    logical = 'c'*64
    info = dict(kind='collar', logical_cell_id=logical, physical_cell_id=box.cell_id,
                physical_support=dict(voxel_id=box.cell_id))
    tables = dict(voxels={box.cell_id: box.record()})
    if differential:
        support = dict(schema='fixture.synthetic-differential-support',
                       components=[dict(logical_cell_id=logical, fixture='exact archived component')])
        support_id = E._hash(support)
        tables = dict(differential_supports={support_id: support})
        info.update(kind='exterior', physical_support=dict(differential_support_id=support_id,
                                                          logical_cell_id=logical))
    with B._Arena(budget) as arena:
        cells, faces = E._assemble([(logical, B._box(box), info)], arena)
    result = empty_legacy_record()
    result.update(cells=cells, faces=faces, support_tables=tables)
    return result


def compact_fixture(record, budget):
    import mesh_tables as C
    blobs = {}
    metadata, arrays = C.pack_mesh(record, support_writer=blobs.__setitem__, budget=budget)
    def reader(identity, expected_nbytes):
        raw = blobs[identity]
        if len(raw) != expected_nbytes:
            raise AssertionError('fixture reader length mismatch')
        return raw
    view = C.CompactMesh(metadata, arrays, support_reader=reader,
                         expected_geometry_id=E._hash(record), budget=budget)
    return view


class ExteriorMeshTests(unittest.TestCase):
    def test_compact_equality_hash_and_legacy_representation_domain(self):
        budget = WorkBudget(16 << 20)
        first = tiny_record(budget)
        second = dict(first, support_id='e'*64)
        a_view, b_view = compact_fixture(first, budget), compact_fixture(second, budget)
        a = E.ExteriorMesh.from_compact(a_view, budget=budget)
        same = E.ExteriorMesh.from_compact(a_view, budget=budget)
        b = E.ExteriorMesh.from_compact(b_view, budget=budget)
        old = E.ExteriorMesh.restore(first, geometry_id=E._hash(first), budget=budget)
        old_same = E.ExteriorMesh.restore(first, geometry_id=E._hash(first), budget=budget)
        self.assertEqual(a, same)
        self.assertEqual(hash(a), hash(same))
        self.assertNotEqual(a, b)
        self.assertEqual(len({a, same, b}), 2)
        self.assertEqual(old, old_same)
        self.assertEqual(hash(old), hash((old._json,)))
        self.assertEqual(hash(old), hash(old_same))
        self.assertEqual(a.geometry_id, old.geometry_id)
        self.assertNotEqual(a, old)  # Explicit representation, not science, equality.
        self.assertEqual(len({a, same, b, old, old_same}), 3)
        del a, same, b, old, old_same, a_view, b_view
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_ordinary_ast_and_strict_source_pin(self):
        source = (BASE/'integration_exterior_mesh.py').read_bytes().decode('utf8')
        original, transformed = ast.parse(source), ast.parse(P.transform(source))
        new_methods = {node.name for node in ast.parse('class C:\n'+P._INDEXED_METHODS).body[0].body}

        class StripAdditions(ast.NodeTransformer):
            def visit_ClassDef(self, node):
                if node.name == 'ExteriorMesh':
                    node.body = [item for item in node.body if not (
                        isinstance(item, ast.FunctionDef) and item.name in new_methods or
                        isinstance(item, ast.AnnAssign) and item.target.id == '_compact')]
                return self.generic_visit(node)

            def visit_FunctionDef(self, node):
                if node.name in ('geometry_id', 'record') and isinstance(node.body[0], ast.If):
                    node.body = node.body[1:]
                elif node.name == 'resolve_physical_support':
                    self.assertion = isinstance(node.body[1], ast.If)
                    if not self.assertion:
                        raise AssertionError('exact support dispatch expected after docstring')
                    node.body.pop(1)
                return self.generic_visit(node)

        stripped = StripAdditions().visit(transformed)
        self.assertEqual(ast.dump(original, include_attributes=False), ast.dump(stripped, include_attributes=False))
        for changed in (source+'\n', P.transform(source)):
            with self.assertRaises(P.CompactExteriorRefused):
                P.transform(changed)

    def test_actual_legacy_restore_and_record_unchanged(self):
        budget = WorkBudget(8 << 20)
        record = empty_legacy_record()
        identity = E._hash(record)
        mesh = E.ExteriorMesh.restore(record, geometry_id=identity, budget=budget)
        self.assertIs(type(mesh), E.ExteriorMesh)
        self.assertFalse(mesh.is_compact)
        self.assertEqual(mesh.geometry_id, identity)
        self.assertEqual(mesh.record(), record)
        self.assertEqual(mesh._json, json.dumps(record, sort_keys=True, separators=(',', ':')).encode())
        with self.assertRaises(E.V.VolumeError):
            E.ExteriorMesh.restore(record, geometry_id='0'*64, budget=budget)
        del mesh
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_actual_compact_native_type_identity_rows_metrics_and_owned_export(self):
        import mesh_tables as C
        budget = WorkBudget(16 << 20)
        record = tiny_record(budget)
        view = compact_fixture(record, budget)
        mesh = E.ExteriorMesh.from_compact(view, budget=budget)
        self.assertIs(type(mesh), E.ExteriorMesh)
        self.assertTrue(mesh.is_compact)
        self.assertIsNone(mesh._json)
        self.assertEqual(mesh.geometry_id, E._hash(record))
        self.assertEqual((mesh.cell_count, mesh.face_count), (1, 6))
        row, face = mesh.cell(0), mesh.face(0)
        self.assertIs(type(row), C.OwnedRow)
        self.assertEqual(row.value, record['cells'][0])
        self.assertEqual(face.value, record['faces'][0])
        metrics = mesh.cell_metrics(0)
        self.assertEqual(metrics.value['volume'], Fraction(1))
        self.assertEqual(metrics.value['centre'], (Fraction(1, 2),)*3)
        face_metrics = mesh.face_metrics(0)
        self.assertEqual(face_metrics.value['face_id'], record['faces'][0]['face_id'])
        with self.assertRaisesRegex(E.V.VolumeError, 'indexed access'):
            mesh.record()
        exported = mesh.legacy_record()
        self.assertIs(type(exported), C.OwnedRow)
        self.assertEqual(exported.value, record)
        self.assertEqual(b''.join(mesh.iter_legacy_json()), C.canonical(record))
        # No materialised mutable record is retained by native wrapper/codec.
        row.value['volume_m3'] = ['0x2', '0x1']
        self.assertEqual(mesh.cell(0).value, record['cells'][0])
        held = mesh.physical_support(0)
        self.assertEqual(held.value, E.resolve_physical_support(record, record['cells'][0]))
        self.assertIs(type(held), C.OwnedRow)
        self.assertEqual(E.resolve_physical_support(mesh, 0).value, held.value)
        del row, face, metrics, face_metrics, exported, mesh, view
        gc.collect()
        self.assertGreater(budget.reserved_bytes, 0)
        self.assertEqual(held.value['voxel'], next(iter(record['support_tables']['voxels'].values())))
        del held
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_differential_support_and_held_error_keep_exact_native_gate(self):
        budget = WorkBudget(16 << 20)
        record = tiny_record(budget, differential=True)
        view = compact_fixture(record, budget)
        mesh = E.ExteriorMesh.from_compact(view, budget=budget)
        support = mesh.physical_support(0)
        self.assertEqual(support.value, E.resolve_physical_support(record, record['cells'][0]))
        support.value['component']['fixture'] = 'changed borrowed row'
        self.assertNotEqual(mesh.physical_support(0).value, support.value)
        del support, mesh, view
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        bad = deepcopy(record)
        next(iter(bad['support_tables']['differential_supports'].values()))['components'][0]['logical_cell_id'] = 'd'*64
        view = compact_fixture(bad, budget)
        mesh = E.ExteriorMesh.from_compact(view, budget=budget)
        held = None
        try:
            mesh.physical_support(0)
        except E.V.VolumeError as error:
            held = error
        self.assertIsNotNone(held)
        del mesh, view
        gc.collect()
        self.assertGreater(budget.reserved_bytes, 0)
        held = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_shared_budget_native_header_and_index_refusals(self):
        import mesh_tables as C
        budget, foreign = WorkBudget(16 << 20), WorkBudget(16 << 20)
        record = tiny_record(budget)
        view = compact_fixture(record, budget)
        with self.assertRaisesRegex(P.CompactExteriorRefused, 'shared WorkBudget'):
            E.ExteriorMesh.from_compact(view, budget=foreign)
        with self.assertRaises(P.CompactExteriorRefused):
            E.ExteriorMesh.from_compact(record, budget=budget)
        mesh = E.ExteriorMesh.from_compact(view, budget=budget)
        for index in (-1, 1, True, 0.0):
            with self.assertRaises(C.MeshTablesRefused):
                mesh.cell(index)
        del mesh, view
        for name, value in (('endpoint', 'midpoint'), ('trajectory_id', '0'*64)):
            bad = dict(record, **{name: value})
            view = compact_fixture(bad, budget)
            with self.assertRaisesRegex(P.CompactExteriorRefused, 'trajectory'):
                E.ExteriorMesh.from_compact(view, budget=budget)
            del view
        missing = dict(record)
        del missing['funding_id']
        view = compact_fixture(missing, budget)
        with self.assertRaisesRegex(P.CompactExteriorRefused, 'header'):
            E.ExteriorMesh.from_compact(view, budget=budget)
        del view
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(foreign.reserved_bytes, 0)

    def test_immutable_owner_budget_refusal_and_header_failure_lifetime(self):
        from atlas_tectonics.resources import MemoryLimitError
        budget = WorkBudget(16 << 20)
        record = tiny_record(budget)
        view = compact_fixture(record, budget)
        mesh = E.ExteriorMesh.from_compact(view, budget=budget)
        with self.assertRaises(AttributeError):
            view.geometry_id = '0'*64
        with self.assertRaises(AttributeError):
            mesh._compact = None
        baseline = budget.reserved_bytes
        with budget.reserve(budget.available_bytes-32, category='fixture-budget-pressure'):
            with self.assertRaises(MemoryLimitError):
                E.ExteriorMesh.from_compact(view, budget=budget)
        self.assertEqual(budget.reserved_bytes, baseline)
        header = mesh.header()
        del mesh, view
        gc.collect()
        self.assertGreater(budget.reserved_bytes, 0)
        self.assertEqual(header.value['funding_id'], record['funding_id'])
        del header
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        bad = dict(record, trajectory_id='0'*64)
        view = compact_fixture(bad, budget)
        held = None
        try:
            E.ExteriorMesh.from_compact(view, budget=budget)
        except P.CompactExteriorRefused as error:
            held = error
        self.assertIsNotNone(held)
        del view
        gc.collect()
        self.assertGreater(budget.statistics()['categories'].get('compact-exterior-trajectory-check', 0), 0)
        held = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
