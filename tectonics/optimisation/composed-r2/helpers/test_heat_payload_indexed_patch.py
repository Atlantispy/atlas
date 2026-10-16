"""Owned active-row/source controls; full F13 parity belongs to root's test.

Use the same authenticated temporary runtime setup, but do not run a heat
solve or read any historical store. Geometry is an explicit synthetic two-cell
native exact fixture. Errors and separately held tracebacks are deliberate.
"""
import ast
from concurrent.futures import CancelledError
import gc
from hashlib import sha256
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import heat_payload_indexed_patch as P
import test_private_heat_indexed_runtime as FIXTURE


def setUpModule():
    FIXTURE.setUpModule()


def tearDownModule():
    FIXTURE.tearDownModule()


def build():
    budget = FIXTURE.WorkBudget(64 << 20)
    record = FIXTURE.FIXTURE.two_cell_record(budget)
    view = FIXTURE.FIXTURE.T.compact_fixture(record, budget)
    geometry = FIXTURE.M.MimeticGeometry.from_compact(view, budget=budget)
    return budget, record, view, geometry


def expected_payload(record):
    return dict(cells=[{key: row[key] for key in P.CELL_FIELDS} for row in record['cells']],
                faces=[{key: row[key] for key in P.FACE_FIELDS} for row in record['faces']])


def category(budget, name):
    return budget.statistics()['categories'].get(name, 0)


class SourceControls(unittest.TestCase):
    def test_strict_inputs_and_legacy_ast_numerics_unchanged(self):
        class StripIndexed(ast.NodeTransformer):
            def visit_Import(self, node):
                if any(alias.name == 'heat_payload_indexed_patch' for alias in node.names):
                    return None
                return node

            def visit_If(self, node):
                if (isinstance(node.test, ast.Call) and isinstance(node.test.func, ast.Attribute)
                        and isinstance(node.test.func.value, ast.Name)
                        and node.test.func.value.id == 'INDEXED_PAYLOAD'):
                    return [self.visit(child) for child in node.orelse]
                if (isinstance(node.test, ast.BoolOp) and isinstance(node.test.op, ast.And)
                        and ast.unparse(node.test.values[0]) == 'not INDEXED_PAYLOAD.is_indexed(geometry)'):
                    node.test = node.test.values[1]
                return self.generic_visit(node)

        for name, transform in P.TRANSFORMS.items():
            source = (FIXTURE.H/name).read_bytes().decode()
            transformed = transform(source)
            compile(transformed, name, 'exec')
            with self.assertRaises(ValueError):
                transform(source+'\n')
            with self.assertRaises(ValueError):
                transform(transformed)
            original, actual = ast.parse(source), ast.parse(transformed)
            if name.endswith('parallel_r1.py'):
                # Only reviewed source-membership predicates change. All
                # message layouts, arithmetic, worker logic and guards stay.
                old = {n.name: n for n in original.body if isinstance(n, ast.FunctionDef)}
                actual.body = [n for n in actual.body if not (isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == '_INDEXED_RUNTIME_HELPERS' for t in n.targets))]
                actual.body = [old[n.name] if isinstance(n, ast.FunctionDef)
                    and n.name in ('_ours', '_unlike') else n for n in actual.body]
            else:
                actual = StripIndexed().visit(actual)
            self.assertEqual(ast.dump(original), ast.dump(actual), name)

    def test_worker_finite_inventory_exact_file_binding_and_plain_serializer(self):
        worker = importlib.import_module('private_heat_functionals_parallel_r1')
        self.assertEqual(worker._INDEXED_RUNTIME_HELPERS, frozenset(P.WORKER_RUNTIME_HELPERS))
        for name in P.WORKER_RUNTIME_HELPERS:
            self.assertTrue(worker._ours(name))
            self.assertFalse(worker._ours(name+'_unreviewed'))
        self.assertFalse(worker._ours('test_heat_payload_indexed_patch'))
        files = worker._files()
        for name in ('heat_payload_indexed_patch', 'mesh_tables', 'native_transfer', 'spatial_transfer'):
            module = importlib.import_module(name)
            path = Path(module.__file__).resolve()
            self.assertEqual(files[str(path)], sha256(path.read_bytes()).hexdigest())
        with tempfile.TemporaryDirectory(prefix='heat-worker-source-', dir=FIXTURE.T) as directory:
            root = Path(directory)
            candidate, clone = root/'candidate', root/'clone'
            candidate.mkdir(); clone.mkdir()
            source = candidate/'mesh_tables.py'
            source.write_bytes(b'# explicitly synthetic worker source identity fixture\n')
            digest = sha256(source.read_bytes()).hexdigest()
            self.assertEqual(worker._unlike({str(source): digest}, {}, candidate, clone), [])
            self.assertEqual(worker._unlike({str(source): '0'*64}, {}, candidate, clone), ['mesh_tables.py'])
            foreign = root/'mesh_tables.py'
            foreign.write_bytes(source.read_bytes())
            self.assertEqual(worker._unlike({str(foreign): digest}, {}, candidate, clone), ['mesh_tables.py'])
        row = dict(vertices_m=[['fixture']], centroid_m=['same'], area_vector_m2=['same'],
                   physical_support={'must_not_serialize': True}, annotation='must_not_serialize')
        self.assertEqual(worker._moment_part(row), {key: row[key] for key in worker.MOMENT_FIELDS})
        self.assertEqual(set(worker._moment_part(row)), {'vertices_m', 'centroid_m', 'area_vector_m2'})


class OwnedPayloadControls(unittest.TestCase):
    def test_typed_rows_minimal_values_no_support_decode_and_lifetime(self):
        import mesh_tables as C
        budget, record, view, geometry = build()
        adapter = P.IndexedMetricPayload(geometry, budget=budget)
        with patch.object(C.CompactMesh, 'cell', side_effect=AssertionError('whole cell row')), \
                patch.object(C.CompactMesh, 'face', side_effect=AssertionError('whole face row')), \
                patch.object(C.CompactMesh, '_support_blob', side_effect=AssertionError('support blob')):
            cell, face = adapter.cell(0), adapter.face(0)
            self.assertIs(type(cell), C.OwnedRow)
            self.assertEqual(cell.value, expected_payload(record)['cells'][0])
            self.assertEqual(face.value, expected_payload(record)['faces'][0])
            self.assertEqual(set(cell.value), P.CELL_FIELDS)
            self.assertEqual(set(face.value), P.FACE_FIELDS)
        with self.assertRaises(AttributeError):
            adapter.view = None
        for bad in (-1, True, 0.0, len(record['faces'])):
            with self.assertRaises(C.MeshTablesRefused):
                adapter.face(bad)
        with self.assertRaises(TypeError):
            P.IndexedMetricPayload(geometry, budget=FIXTURE.WorkBudget(1 << 20))
        del adapter, view, geometry, cell
        gc.collect()
        self.assertGreater(budget.reserved_bytes, 0)
        self.assertEqual(face.value, expected_payload(record)['faces'][0])
        del face
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_materialised_rows_fully_counted_and_life_transfer(self):
        import mesh_tables as C
        COUNT = importlib.import_module('private_heat_counted_blocks_r2')
        LIFE = importlib.import_module('private_heat_stage_lifetime_r3')
        from atlas_tectonics.exact_arithmetic import library
        budget, record, view, geometry = build()
        baseline = budget.reserved_bytes
        with patch.object(C.CompactMesh, 'cell', side_effect=AssertionError('whole cell row')), \
                patch.object(C.CompactMesh, 'face', side_effect=AssertionError('whole face row')), \
                patch.object(C.CompactMesh, '_support_blob', side_effect=AssertionError('support blob')):
            owner = P.materialise(geometry, budget=budget)
        self.assertEqual(owner.value, expected_payload(record))
        G = library()
        counted = COUNT.supported(G)
        exact = P._plain_bytes(owner.value, COUNT, G, counted, None if counted else COUNT.padding(), None)
        self.assertEqual(category(budget, 'heat-indexed-metric-payload'), 65536+exact)
        self.assertEqual(budget.reserved_bytes-baseline, 65536+exact)
        print('METRIC_ONLY_RETAINED', dict(graph_bytes=exact, metadata_bytes=65536,
              cells=len(record['cells']), faces=len(record['faces'])), flush=True)
        adopted = LIFE.compact(owner, budget=budget, cancelled=None)
        with self.assertRaises(RuntimeError):
            owner.value
        self.assertEqual(category(budget, 'heat-indexed-metric-payload'), 0)
        self.assertEqual(adopted.value, expected_payload(record))
        self.assertGreater(budget.reserved_bytes, baseline)
        adopted.close()
        del owner, adopted, view, geometry
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_cancelled_decoded_row_and_separate_traceback_retain_leases(self):
        budget, record, view, geometry = build()
        baseline = budget.reserved_bytes
        codec_baseline = category(budget, 'compact-mesh-owned')
        def cancel():
            return category(budget, 'compact-mesh-owned') > codec_baseline
        held = None
        try:
            P.materialise(geometry, budget=budget, cancel=cancel)
        except CancelledError as error:
            held = error
        self.assertIsNotNone(held)
        self.assertGreater(category(budget, 'heat-indexed-metric-payload'), 0)
        self.assertGreater(category(budget, 'compact-mesh-owned'), codec_baseline)
        trace = held.__traceback__
        has_row = False
        cursor = trace
        while cursor is not None:
            if cursor.tb_frame.f_code.co_name == 'cell':
                self.assertEqual(cursor.tb_frame.f_locals['row'], expected_payload(record)['cells'][0])
                has_row = True
            cursor = cursor.tb_next
        self.assertTrue(has_row)
        held = None
        gc.collect()
        self.assertGreater(budget.reserved_bytes, baseline)
        trace = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        del geometry, view
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_resource_refusal_after_table_allocation_retains_error_frame(self):
        from atlas_tectonics.resources import MemoryLimitError
        budget, record, view, geometry = build()
        baseline = budget.reserved_bytes
        initial = 65536+32*(len(record['cells'])+len(record['faces']))
        held = None
        with budget.reserve(budget.available_bytes-(initial+4096), category='explicit-fixture-pressure'):
            try:
                P.materialise(geometry, budget=budget)
            except MemoryLimitError as error:
                held = error
            self.assertIsNotNone(held)
            self.assertGreater(category(budget, 'heat-indexed-metric-payload'), 0)
        self.assertGreater(budget.reserved_bytes, baseline)
        held = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        del geometry, view
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
