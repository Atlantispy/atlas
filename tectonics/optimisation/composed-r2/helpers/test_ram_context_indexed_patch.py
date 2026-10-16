"""Indexed cold heat binding route on tiny real fixtures; never owner acceptance.

The frozen I/ram cold binding context (cd729dc2) gets an explicit indexed route
from ram_context_indexed_patch, applied by the successor heat bundle before pin
reconciliation. These tests import the COMPOSED bytes the bundle emits under a
temporary composed layout, build REAL IndexedSpatialSnapshot values through
spatial_indexed_patch.retained_snapshot (owning _RecordBytes metadata) and REAL
compact ExteriorMesh views, and drive the composed route helpers, the original
statements they replace and the transformed cold-reader seam with the real
resources r4 decoder. The genuine owner-call cold reopen (owner, collar states,
heat CAS) remains the W4 composed check and is not claimed here.
"""
import ast
from concurrent.futures import CancelledError
from contextlib import contextmanager
import dataclasses
import gc
from hashlib import sha256
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

import ram_context_indexed_patch as RX
import partition_workflow_transform as PWT
import test_private_heat_bundle_extended as BUNDLE

HERE = BUNDLE.HERE
T, H, BASE = BUNDLE.T, BUNDLE.H, BUNDLE.BASE
SPECIAL = frozenset(('cells', 'faces', 'support_tables', 'grid_lines', 'thermal_shared_lines',
                     'required_thermal_boundary_faces'))
_temporary = None
_path = None


def setUpModule():
    global _temporary, _path, HELPERS, RAM, REPORT, CTX, REC, R4, X, HEAT, N, S, E, M, FIXTURE
    global WorkBudget, MemoryLimitError, RegionalMechanicalSnapshot, SpatialExteriorState, CompactMesh, W
    if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
        raise RuntimeError('fresh source-selected test process required')
    HELPERS, RAM, REPORT = BUNDLE.successor()
    _temporary = tempfile.TemporaryDirectory(prefix='rc-', dir=T)
    root, helpers, ram = BUNDLE.write_layout(_temporary.name, HELPERS, RAM)
    _path = list(sys.path)
    sys.path[:0] = [str(root), str(helpers), str(ram), str(H/'source/tectonics/tests')]
    CTX = importlib.import_module('private_heat_restored_binding_ram_context_r1')
    REC = importlib.import_module('private_heat_restored_binding_ram_recovery_r1')
    assert Path(CTX.__file__).resolve().parent == ram.resolve() and REC._context is CTX._context
    R4, X, HEAT = CTX.R, CTX._INDEXED_SPATIAL, CTX._INDEXED_HEAT
    N, S = importlib.import_module('native_transfer'), importlib.import_module('spatial_transfer')
    E = importlib.import_module('atlas_tectonics.integration_exterior_mesh')
    M = importlib.import_module('atlas_tectonics.integration_mimetic_heat')
    resources = importlib.import_module('atlas_tectonics.resources')
    WorkBudget, MemoryLimitError = resources.WorkBudget, resources.MemoryLimitError
    RegionalMechanicalSnapshot = importlib.import_module('atlas_tectonics.regional_execution').RegionalMechanicalSnapshot
    SpatialExteriorState = importlib.import_module('atlas_tectonics.integration_spatial_owner').SpatialExteriorState
    CompactMesh = importlib.import_module('mesh_tables').CompactMesh
    W = importlib.import_module('workflow_transfer')
    FIXTURE = importlib.import_module('test_private_heat_mesh_patch')
    FIXTURE.E = E
    FIXTURE.T.E = E


def tearDownModule():
    if _path is not None:
        sys.path[:] = _path
    if _temporary is not None:
        _temporary.cleanup()


def category(budget, name):
    return budget.statistics()['categories'].get(name, 0)


def required_variant(record):
    """The same record with an explicit required boundary list (one-owner faces)."""
    faces = [row['face_id'] for row in record['faces'] if len(row['owners']) == 1][:2]
    assert len(faces) == 2
    return dict(record, required_thermal_boundary_faces=faces)


def compact(record, budget):
    view = FIXTURE.T.compact_fixture(record, budget)
    return view, E.ExteriorMesh.from_compact(view, budget=budget)


def indexed_state(view, budget, **small):
    """A real indexed endpoint, built exactly as spatial_indexed_patch.issue builds one."""
    body = dict(schema='fixture.indexed-spatial-state', time_s=1.0, intervals=2, parent_state_id='7'*64,
                thermal_mesh_id=view.geometry_id, thermal_mesh=view,
                cells=[dict(cell_id='c'*64, exact=dict(enthalpy_j=['0x12c', '0x1']))], **small)
    arrays = {'enthalpy_j': np.asarray([300., 310.]), 'volume_m3': np.asarray([1., 1.])}
    identity, stats = S._snapshot_id(body, S._bindings(arrays)), S._stream_stats(body)[0]
    allocation = N._Allocation(budget, 65536+4096+sum(a.nbytes for a in arrays.values()),
                               category='fixture-indexed-spatial-state')
    snapshot = X.retained_snapshot(body, arrays, identity, stats, allocation, budget)
    return state_of(snapshot, budget)


def state_of(snapshot, budget):
    state = object.__new__(SpatialExteriorState)
    object.__setattr__(state, '_snapshot', snapshot)
    object.__setattr__(state, '_budget', budget)
    return state


@contextmanager
def no_whole_export():
    with patch.object(CompactMesh, 'legacy_record', side_effect=AssertionError('expanded compact mesh')), \
            patch.object(CompactMesh, 'iter_legacy_json', side_effect=AssertionError('streamed whole mesh')):
        yield


def original_endpoint_gate():
    """The frozen endpoint condition, compiled from the composed ordinary branch."""
    tree = ast.parse(Path(CTX.__file__).read_text(encoding='utf8'))
    context = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_context')
    gate = next(n for n in ast.walk(context) if isinstance(n, ast.If) and RX._indexed_test(n.test)
                and 'Restored physical mesh' in ast.dump(n))
    expression = gate.orelse[0].test
    function = ast.Expression(ast.Lambda(ast.arguments(posonlyargs=[], args=[ast.arg(a) for a in (
        'mesh', 'thermal', 'current', 'owner', 'graph', 'exchange')], kwonlyargs=[], kw_defaults=[], defaults=[]),
        expression))
    return eval(compile(ast.fix_missing_locations(function), '<frozen-endpoint-gate>', 'eval'))


class RamContextTransform(unittest.TestCase):
    def test_exact_input_pinned_output_and_ordinary_statements(self):
        frozen = (BASE/'ram'/RX.NAME).read_text(encoding='utf8')
        self.assertEqual(sha256(frozen.encode()).hexdigest(), RX.BASE_SHA256)
        out = RX.transform(frozen)
        self.assertEqual(sha256(out.encode()).hexdigest(), RX.OUTPUT_SHA256)
        self.assertEqual(REPORT['stage_digests'][RX.NAME+'@ram_context_indexed_patch'], RX.OUTPUT_SHA256)
        for old, new in RX.SEAMS:
            self.assertEqual(frozen.count(old), 1, old[:60])
            self.assertEqual(out.count(new), 1, new[:60])
        before, after = ast.parse(frozen), ast.parse(out)
        a, b = RX._functions(before), RX._functions(after)
        self.assertEqual((set(b)-set(a), {n for n in a if a[n] != b[n]}), (RX.ROUTE_NAMES, {'_context'}))
        self.assertEqual(ast.dump(RX.ordinary(ast.parse(out))), ast.dump(before))
        # The ordinary-branch check is not vacuous: one changed original statement is seen.
        old = 'sha256(geometry._encoded).hexdigest() != mesh.geometry_id'
        self.assertEqual(out.count(old), 1)
        mutated = out.replace(old, 'sha256(geometry._encoded).hexdigest() == mesh.geometry_id')
        self.assertNotEqual(ast.dump(RX.ordinary(ast.parse(mutated))), ast.dump(before))
        with self.assertRaises(RX.RamContextIndexedRefused):
            RX.ordinary(ast.parse(out.replace('    else:\n        thermal_view = work', '    if True:\n        thermal_view = work', 1)))
        for bad in (out, frozen+'\n', frozen.replace('\n', '\r\n'), None, frozen.encode()):
            with self.assertRaises(RX.RamContextIndexedRefused):
                RX.transform(bad)
        with self.assertRaises(RX.RamContextIndexedRefused):
            RX._once('x\n        def f():\n', '    def f():\n', 'y\n')
        # The composed module is this output with only its dependency pins reconciled.
        self.assertEqual(Path(CTX.__file__).read_bytes(), RAM[RX.NAME])
        module = ast.parse((HERE/'ram_context_indexed_patch.py').read_bytes().decode('utf8'))
        imported = {a.name for n in module.body if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module for n in module.body if isinstance(n, ast.ImportFrom)}
        self.assertEqual(imported, {'ast', 'hashlib'})
        probe = ('import sys; sys.path.insert(0, %r); import ram_context_indexed_patch; '
                 "bad = [n for n in sys.modules if n.split('.')[0] in ('atlas_tectonics', 'numpy')]; "
                 "assert not bad, bad; print('STDLIB_ONLY')") % str(HERE)
        completed = subprocess.run([sys.executable, '-B', '-I', '-c', probe], capture_output=True, text=True, timeout=60)
        self.assertEqual((completed.returncode, completed.stdout.strip()), (0, 'STDLIB_ONLY'), completed.stderr)


class IndexedRoute(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(256 << 20)

    def tearDown(self):
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_spatial_snapshot_identity_and_owned_metadata_decode(self):
        budget = self.budget
        record = FIXTURE.two_cell_record(budget)
        view, _ = compact(record, budget)
        state = indexed_state(view, budget)
        other = indexed_state(view, budget, extra='other endpoint')
        snapshot = state._snapshot
        self.assertIs(type(snapshot._metadata), N._RecordBytes)
        # The frozen statements refuse every real indexed endpoint (defects 1-3).
        with self.assertRaises(TypeError):
            CTX._snapshot(snapshot, budget, None)
        with self.assertRaisesRegex(ValueError, 'Owned ensure_ascii JSON bytes required'):
            R4.decoded(snapshot._metadata, budget=budget)
        native = RegionalMechanicalSnapshot(dict(schema='fixture'), {'x': np.zeros(1)})
        self.assertTrue(CTX._indexed_spatial(snapshot, (other, state)))
        self.assertFalse(CTX._indexed_spatial(snapshot, (other,)))
        self.assertFalse(CTX._indexed_spatial(native, (state_of(native, budget),)))
        CTX._snapshot(native, budget, None)
        CTX._indexed_snapshot(snapshot, budget, None)
        foreign = WorkBudget(1 << 20)
        with self.assertRaisesRegex(ValueError, 'foreign resource owner'):
            CTX._indexed_snapshot(snapshot, foreign, None)
        with self.assertRaises(ValueError):
            CTX._indexed_snapshot(dataclasses.replace(snapshot, result_id='0'*64), budget, None)
        baseline = budget.reserved_bytes
        decoded = CTX._indexed_metadata_view(snapshot, budget, None)
        self.assertEqual(decoded.value, json.loads(bytes(snapshot._metadata)))
        self.assertNotIn('thermal_mesh', decoded.value)
        self.assertEqual(decoded.value['thermal_mesh_id'], view.geometry_id)
        # The copy was charged and released with it; only the r4 view remains.
        self.assertEqual(category(budget, 'private-cold-indexed-metadata'), 0)
        self.assertGreater(category(budget, 'private-heat-json-view'), 0)
        decoded.close()
        self.assertEqual(budget.reserved_bytes, baseline)
        with self.assertRaises(CancelledError):
            CTX._indexed_metadata_view(snapshot, budget, lambda: True)
        self.assertEqual(budget.reserved_bytes, baseline)
        # A refused decode is held with its traceback: the copy's charge stays.
        size = 65536+len(snapshot._metadata)
        held = None
        with budget.reserve(budget.available_bytes-size-1024, category='fixture-pressure'):
            try:
                CTX._indexed_metadata_view(snapshot, budget, None)
            except MemoryLimitError as error:
                held = error
        self.assertIsNotNone(held)
        self.assertEqual(category(budget, 'private-cold-indexed-metadata'), size)
        held = None
        gc.collect()
        self.assertEqual((category(budget, 'private-cold-indexed-metadata'), budget.reserved_bytes), (0, baseline))
        del state, other, snapshot, view, native, decoded

    def test_thermal_rows_match_legacy_record_without_expansion(self):
        budget = self.budget
        base = FIXTURE.two_cell_record(budget)
        for record in (base, required_variant(base)):
            view, mesh = compact(record, budget)
            with no_whole_export():
                thermal = CTX._IndexedThermal(mesh, budget)
                header = [k for k in record if k not in SPECIAL]
                self.assertTrue({'funding_id', 'grid_id', 'support_id', 'trajectory_id', 'time_s', 'source',
                                 'booked_cell_rule'} <= set(header))
                for key in header:
                    self.assertEqual(thermal[key], record[key], key)
                    self.assertEqual(thermal.get(key), record[key], key)
                    self.assertIn(key, thermal)
                self.assertNotIn('absent_field', thermal)
                self.assertEqual(thermal.get('absent_field', 'default'), 'default')
                with self.assertRaises(KeyError):
                    thermal['absent_field']
                key = 'required_thermal_boundary_faces'
                self.assertEqual(key in thermal, key in record)
                self.assertEqual(thermal.get(key, ()), record.get(key, ()))
                rows = list(thermal['cells'])
                self.assertEqual(len(rows), len(record['cells']))
                for row, expected in zip(rows, record['cells'], strict=True):
                    for field in expected:
                        self.assertEqual(row[field], expected[field], field)
                for whole in ('faces', 'support_tables', 'grid_lines'):
                    with self.assertRaises(TypeError):
                        thermal[whole]
                    with self.assertRaises(TypeError):
                        whole in thermal
            with self.assertRaises(TypeError):
                CTX._IndexedThermal(mesh, WorkBudget(64 << 20))
            legacy = E.ExteriorMesh.restore(record, geometry_id=E._hash(record), budget=budget)
            self.assertEqual(legacy.geometry_id, mesh.geometry_id)
            with self.assertRaises(TypeError):
                CTX._IndexedThermal(legacy, budget)
            del thermal, rows, row, view, mesh, legacy

    def test_endpoint_gates_match_the_original_on_legacy_rows(self):
        budget = self.budget
        record = required_variant(FIXTURE.two_cell_record(budget))
        view, mesh = compact(record, budget)
        legacy = E.ExteriorMesh.restore(record, geometry_id=E._hash(record), budget=budget)
        legacy_rows, rows = json.loads(legacy._json), CTX._IndexedThermal(mesh, budget)
        gate = original_endpoint_gate()
        owner = SimpleNamespace(_funding=SimpleNamespace(funding_id=record['funding_id']),
                                _definition=dict(grid_id=record['grid_id']))
        graph = dict(funding_id=record['funding_id'], grid_id=record['grid_id'], end_support_id=record['support_id'],
                     trajectory_id=record['trajectory_id'], end_time_s=record['time_s'], source=record['source'])
        exchange = dict(spatial_graph_id=record['booked_cell_rule']['closed_graph_id'])
        current = dict(thermal_mesh_id=mesh.geometry_id)
        cases = [('consistent', {}, False),
                 ('graph funding', dict(graph=dict(graph, funding_id='e'*64)), True),
                 ('owner funding', dict(owner=SimpleNamespace(_funding=SimpleNamespace(funding_id='e'*64),
                                                             _definition=owner._definition)), True),
                 ('owner grid', dict(owner=SimpleNamespace(_funding=owner._funding, _definition=dict(grid_id='e'*64))), True),
                 ('graph grid', dict(graph=dict(graph, grid_id='e'*64)), True),
                 ('support', dict(graph=dict(graph, end_support_id='e'*64)), True),
                 ('trajectory', dict(graph=dict(graph, trajectory_id='e'*64)), True),
                 ('time', dict(graph=dict(graph, end_time_s=['0x2', '0x1'])), True),
                 ('source value', dict(graph=dict(graph, source={'fixture': 'other'})), True),
                 ('source presence', dict(graph={k: v for k, v in graph.items() if k != 'source'}), True),
                 ('booked graph', dict(exchange=dict(spatial_graph_id='e'*64)), True),
                 ('mesh identity', dict(current=dict(thermal_mesh_id='e'*64)), True)]
        with no_whole_export():
            for label, change, expected in cases:
                arguments = dict(owner=owner, graph=graph, exchange=exchange, current=current)
                arguments.update(change)
                frozen = gate(legacy, legacy_rows, dict(arguments['current'], thermal_mesh=legacy_rows),
                              arguments['owner'], arguments['graph'], arguments['exchange'])
                indexed = CTX._indexed_endpoint_differs(mesh, rows, arguments['current'], arguments['owner'],
                                                        arguments['graph'], arguments['exchange'])
                self.assertEqual((bool(frozen), bool(indexed)), (expected, expected), label)
            # Indexed metadata may never also carry an expanded mesh copy.
            self.assertTrue(CTX._indexed_endpoint_differs(mesh, rows, dict(current, thermal_mesh=legacy_rows),
                                                          owner, graph, exchange))
        # The original statements cannot read the indexed metadata at all.
        with self.assertRaises(KeyError):
            gate(mesh, rows, current, owner, graph, exchange)
        del view, mesh, legacy, legacy_rows, rows

    def test_indexed_geometry_and_retained_metric_identity(self):
        budget = self.budget
        record = FIXTURE.two_cell_record(budget)
        view, mesh = compact(record, budget)
        geometry = CTX._indexed_geometry(mesh, None, budget, None)
        self.assertIs(type(geometry), M.MimeticGeometry)
        self.assertIs(geometry._indexed, view)
        self.assertEqual(geometry.geometry_id, mesh.geometry_id)
        # The frozen retained-metric rehash cannot run on an indexed metric (defect 6).
        self.assertIsNone(geometry._encoded)
        with self.assertRaises(TypeError):
            sha256(geometry._encoded)
        self.assertIs(CTX._indexed_geometry(mesh, geometry, budget, None), geometry)
        ordinary = M.MimeticGeometry(record, budget=budget)
        self.assertIs(CTX._indexed_geometry(mesh, ordinary, budget, None), ordinary)
        self.assertEqual((list(ordinary._face_ids), [list(i) for i in ordinary._incidence]),
                         (list(geometry._face_ids), [list(i) for i in geometry._incidence]))
        _, changed = compact(required_variant(record), budget)
        other = CTX._indexed_geometry(changed, None, budget, None)
        with self.assertRaisesRegex(ValueError, 'Retained restored metric differs'):
            CTX._indexed_geometry(mesh, other, budget, None)
        foreign = WorkBudget(64 << 20)
        elsewhere = M.MimeticGeometry.from_compact(FIXTURE.T.compact_fixture(record, foreign), budget=foreign)
        with self.assertRaisesRegex(ValueError, 'Retained restored metric differs'):
            CTX._indexed_geometry(mesh, elsewhere, budget, None)
        del geometry, ordinary, other, changed, elsewhere, view, mesh
        gc.collect()
        self.assertEqual(foreign.reserved_bytes, 0)


class ColdSeam(unittest.TestCase):
    """M14: the transformed cold reader's indexed thermal-mesh restore, real encoding."""
    def setUp(self):
        self.budget = WorkBudget(256 << 20)

    def tearDown(self):
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def seam(self):
        frozen = (BASE/'runtime-src/atlas_tectonics/integration_private_heat_cold.py').read_text(encoding='utf8')
        cold = PWT.cold_source(W.private_heat_cold_source(frozen))
        self.assertEqual(sha256(cold.encode()).hexdigest(), PWT.COLD_OUTPUT_SHA256)
        restore = next(f for f in ast.parse(cold).body if getattr(f, 'name', None) == 'restore_checkpoint')
        branch = next(n for n in ast.walk(restore) if isinstance(n, ast.If) and '_COMPACT_INDEXED' in ast.dump(n.test))
        text = textwrap.dedent(ast.get_source_segment(cold, branch, padded=True))
        # The real composed resources r4, RAM recovery (its ExteriorMesh) and codec.
        namespace = dict(R=R4, B=REC, _COMPACT_INDEXED=X)
        exec(compile('def seam(spatial_state, budget, cancel):\n'+textwrap.indent(text, '    ')+'\n    return mesh\n',
                     '<composed-cold-thermal-seam>', 'exec'), namespace)
        return namespace['seam']

    def test_indexed_thermal_mesh_with_real_encoding_and_decoder(self):
        budget, seam = self.budget, self.seam()
        record = FIXTURE.two_cell_record(budget)
        view, _ = compact(record, budget)
        state = indexed_state(view, budget)
        # What the superseded c1605caa branch did with the same bytes.
        with self.assertRaisesRegex(ValueError, 'Owned ensure_ascii JSON bytes required'):
            R4.decoded(state._snapshot._metadata, budget=budget)
        with no_whole_export():
            mesh = seam(state, budget, None)
        self.assertIs(type(mesh), E.ExteriorMesh)
        self.assertTrue(mesh.is_compact)
        self.assertIs(mesh._compact, view)
        self.assertEqual(mesh.geometry_id, E._hash(record))
        self.assertEqual(category(budget, 'private-cold-indexed-endpoint-metadata'), 0)
        # The ordinary branch is the unchanged legacy restore.
        native = RegionalMechanicalSnapshot(dict(thermal_mesh=record, thermal_mesh_id=E._hash(record)),
                                            {'x': np.zeros(1)})
        old = seam(state_of(native, budget), budget, None)
        self.assertEqual((old.is_compact, old.geometry_id), (False, mesh.geometry_id))
        del mesh, old, native, state, view

    def test_refusals_keep_the_copy_charge_while_held(self):
        budget, seam = self.budget, self.seam()
        record = FIXTURE.two_cell_record(budget)
        view, _ = compact(record, budget)
        foreign = WorkBudget(64 << 20)
        elsewhere = FIXTURE.T.compact_fixture(record, foreign)
        allocation = N._Allocation(budget, 65536, category='fixture-indexed-metadata')
        small = dict(time_s=1.0, thermal_mesh_id=view.geometry_id, support_id=record['support_id'])
        def snapshot(metadata, mesh_view=view):
            # Real class and real owning encoding; deliberately inconsistent bindings.
            return state_of(X.IndexedSpatialSnapshot(N._RecordBytes(N._json(metadata), allocation), (), 'a'*64,
                                                     mesh_view, ('b'*64, 1), 1.0, budget), budget)
        for state, message in ((snapshot(dict(small, thermal_mesh=record)), 'expanded thermal mesh'),
                               (snapshot(dict(small, thermal_mesh_id='f'*64)), 'committed geometry ID'),
                               (snapshot(small, elsewhere), 'sealed on the workflow budget')):
            held = None
            try:
                seam(state, budget, None)
            except ValueError as error:
                held = error
            self.assertIsNotNone(held)
            self.assertRegex(str(held), message)
            self.assertEqual(category(budget, 'private-cold-indexed-endpoint-metadata'),
                             65536+len(state._snapshot._metadata))
            held = None
            gc.collect()
            self.assertEqual(category(budget, 'private-cold-indexed-endpoint-metadata'), 0)
        # The fixture metadata allocation stays with the closure until return;
        # tearDown checks that the workflow budget then returns to zero.
        del state, elsewhere
        gc.collect()
        self.assertEqual(foreign.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
