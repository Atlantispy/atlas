"""Tiny actual native metrics, explicitly synthetic owner operands; no solve."""
import ast
from copy import deepcopy
import gc
import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import numpy as np
import exterior_mesh_patch as EP
import mimetic_patch as MP
import private_heat_mesh_patch as P
import test_exterior_mesh_patch as T


HERE = Path(__file__).resolve().parent
INTEGRATION = HERE.parents[1]/'runtime-integration-r1'
BASE = INTEGRATION/'runtime-src'/'atlas_tectonics'
HEAT = HERE.parents[3]/'heat-repair-20261007'
_temporary = None
_old_path = None


def setUpModule():
    global _temporary, _old_path, E, M, WorkBudget
    if any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.') for name in sys.modules):
        raise RuntimeError('fresh process required; no live runtime patching')
    _temporary = tempfile.TemporaryDirectory(prefix='hp-', dir=HERE)
    package = Path(_temporary.name)/'atlas_tectonics'
    shutil.copytree(BASE, package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, transform in (('integration_exterior_mesh.py', EP.transform),
                            ('integration_mimetic_heat.py', MP.mimetic_source)):
        target = package/name
        target.write_text(transform(target.read_text(encoding='utf8')), encoding='utf8')
    _old_path = list(sys.path)
    sys.path[:0] = [str(Path(_temporary.name)), str(INTEGRATION/'ram'),
                   str(INTEGRATION/'helpers'), str(HEAT)]
    E = importlib.import_module('atlas_tectonics.integration_exterior_mesh')
    M = importlib.import_module('atlas_tectonics.integration_mimetic_heat')
    WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
    T.E = E  # Fixture helper, not runtime or identity mutation.


def tearDownModule():
    if _old_path is not None:
        sys.path[:] = _old_path
    if _temporary is not None:
        assert Path(_temporary.name).resolve().parent == HERE
        _temporary.cleanup()


def two_cell_record(budget):
    from atlas_tectonics import integration_volume_bounds as B
    boxes = [E.V.CartesianCell((i, 0, 0), (i+1, 1, 1), budget=budget) for i in range(2)]
    entries, voxels = [], {}
    for logical, box in zip(('c'*64, 'd'*64), boxes, strict=True):
        voxels[box.cell_id] = box.record()
        entries.append((logical, B._box(box), dict(kind='collar',
            logical_cell_id=logical, physical_cell_id=box.cell_id,
            physical_support=dict(voxel_id=box.cell_id))))
    with B._Arena(budget) as arena:
        cells, faces = E._assemble(entries, arena)
    record = T.empty_legacy_record()
    record.update(cells=cells, faces=faces, support_tables=dict(voxels=voxels), time_s=['0x1', '0x1'])
    record['booked_cell_rule'] = dict(closed_graph_id='9'*64)
    return record


def operands(record, budget):
    logical = [row['logical_cell_id'] for row in record['cells']]
    graph = dict(start_time_s=['0x0', '0x1'], end_time_s=record['time_s'],
        source_flow_stage_id='5'*64, funding_id=record['funding_id'], source=record['source'],
        end_support_id=record['support_id'], grid_id=record['grid_id'],
        trajectory_id=record['trajectory_id'],
        cells=[dict(cell_id=key, end_volume_m3=['0x1', '0x1']) for key in logical])
    transported = dict(source_stage_id='5'*64, state_id='6'*64,
        cell_ids=list(reversed(logical)), exact_stocks={
            'enthalpy_j': [['0x65', '0x3'], ['0xc9', '0x7']],
            'component_mass_kg:0': [['0x1', '0x3'], ['0x2', '0x7']],
            'component_mass_kg:1': [['0x8', '0x7'], ['0x3', '0x5']]})
    return graph, transported, dict(graph_id='9'*64, funding_id=record['funding_id'],
        source_stage_id='5'*64, parent_state_id='6'*64, duration_s=1.0,
        component_count=2, heat_capacity_j_kg_k=1234.5, conductivity_w_m_k=1.7,
        boundary=None, budget=budget)


class IndexedHeatTests(unittest.TestCase):
    def test_exact_additive_issuer_source_and_ordinary_ast(self):
        source = (HEAT/'private_heat_native_issuer_r12.py').read_text(encoding='utf8')
        patched = P.issuer_source(source)
        original, successor = ast.parse(source), ast.parse(patched)
        self.assertEqual(ast.dump(original, include_attributes=False),
                         ast.dump(ast.Module(body=successor.body[:-1], type_ignores=[]), include_attributes=False))
        self.assertEqual(successor.body[-1].name, 'prepare_indexed_mesh_inputs')
        compile(patched, '<additive-preparation-only>', 'exec')
        for invalid in (source+'\n', patched):
            with self.assertRaises(P.IndexedHeatRefused):
                P.issuer_source(invalid)

    def test_actual_metric_and_binary_inputs_equal_original_operations_without_exports(self):
        from atlas_tectonics.integration_regional_inventory import _project
        budget = WorkBudget(64 << 20)
        record = two_cell_record(budget)
        view = T.compact_fixture(record, budget)
        mesh = E.ExteriorMesh.from_compact(view, budget=budget)
        graph, transported, options = operands(record, budget)
        face = next(row['face_id'] for row in record['faces'] if len(row['owners']) == 1)
        options['boundary'] = {face: ('temperature', 300)}
        old_geometry = M.MimeticGeometry(record, budget=budget)
        def no_export(frame, event, arg):
            if event == 'call' and frame.f_code.co_name in ('record', 'legacy_record', 'iter_legacy_json'):
                filename = Path(frame.f_code.co_filename).name
                if filename in ('mesh_tables.py', 'integration_exterior_mesh.py', 'integration_mimetic_heat.py'):
                    raise AssertionError('normal preparation attempted full geometry export')
        sys.setprofile(no_export)
        try:
            prepared = P.prepare_indexed_inputs(mesh, graph, transported, **options)
        finally:
            sys.setprofile(None)
        self.assertIs(type(prepared.geometry), M.MimeticGeometry)
        self.assertIsNone(prepared.geometry._encoded)
        for field in ('_cells', '_incidence', '_face_ids', 'geometry_id'):
            self.assertEqual(getattr(old_geometry, field), getattr(prepared.geometry, field))
        columns = {key: i for i, key in enumerate(transported['cell_ids'])}
        old, capacity = [], []
        for row in record['cells']:
            at = columns[row['logical_cell_id']]
            old.append(_project(M._q(transported['exact_stocks']['enthalpy_j'][at])))
            mass = np.asarray([_project(M._q(transported['exact_stocks']['component_mass_kg:'+str(i)][at]))
                               for i in range(2)])
            capacity.append(float(np.sum(mass)*options['heat_capacity_j_kg_k']))
        for key, expected in (('enthalpy_j', np.asarray(old)), ('capacity_j_k', np.asarray(capacity)),
                              ('source_w', np.zeros(2))):
            actual = prepared.array(key)
            self.assertEqual(actual.dtype, expected.dtype)
            self.assertEqual(actual.shape, expected.shape)
            self.assertEqual(actual.tobytes(), expected.tobytes())
            self.assertFalse(actual.flags.writeable)
            with self.assertRaises(ValueError):
                actual.setflags(write=True)
        descriptor = prepared.descriptor()
        self.assertEqual(descriptor.value['cell_ids'], [row['cell_id'] for row in record['cells']])
        self.assertEqual(descriptor.value['boundary'], {face: ['temperature', 300.0]})
        self.assertFalse(descriptor.value['owner_origin_validated'])
        self.assertFalse(prepared.may_advance)
        support = prepared.physical_support(0)
        self.assertEqual(support.value, E.resolve_physical_support(record, record['cells'][0]))
        retained = len(prepared._metadata)+sum(len(raw) for _, raw in prepared._fields)+4096
        self.assertEqual(budget.statistics()['categories']['indexed-heat-inputs-retained'], retained)
        self.assertEqual(budget.statistics()['categories'].get('indexed-heat-preparation', 0), 0)
        escaped = prepared.array('capacity_j_k')
        del actual, prepared, old_geometry, mesh, view, descriptor, support
        gc.collect()
        self.assertEqual(budget.reserved_bytes, retained)
        self.assertEqual(escaped.tobytes(), np.asarray(capacity).tobytes())
        del escaped
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        print(json.dumps(dict(case='indexed-heat-two-cell-equivalence', array_bytes=48,
                              exact_retained_bytes=retained, released_scratch=True)))

    def test_endpoint_coverage_order_and_material_refusals(self):
        budget = WorkBudget(64 << 20)
        record = two_cell_record(budget)
        view = T.compact_fixture(record, budget)
        mesh = E.ExteriorMesh.from_compact(view, budget=budget)
        original_g, original_t, original_options = operands(record, budget)
        cases = [
            ('interval', 'g', 'start_time_s', ['0x1', '0x1']),
            ('source', 'g', 'source_flow_stage_id', '0'*64),
            ('transport source', 't', 'source_stage_id', '0'*64),
            ('parent', 't', 'state_id', '0'*64),
            ('funding', 'g', 'funding_id', '0'*64),
            ('support', 'g', 'end_support_id', '0'*64),
            ('grid', 'g', 'grid_id', '0'*64),
            ('trajectory', 'g', 'trajectory_id', '0'*64),
            ('source extra', 'g', 'source', {}),
            ('coverage', 'g', 'cells', []),
            ('duplicates', 't', 'cell_ids', ['c'*64, 'c'*64]),
            ('booked graph', 'o', 'graph_id', '0'*64),
            ('actual funding', 'o', 'funding_id', '0'*64),
            ('duration', 'o', 'duration_s', float('inf')),
            ('conductivity', 'o', 'conductivity_w_m_k', 0),
            ('capacity', 'o', 'heat_capacity_j_kg_k', 0),
            ('components', 'o', 'component_count', True),
        ]
        baseline = budget.reserved_bytes
        for label, target, key, value in cases:
            g, t, options = deepcopy(original_g), deepcopy(original_t), dict(original_options)
            {'g': g, 't': t, 'o': options}[target][key] = value
            with self.subTest(label=label), self.assertRaises(P.IndexedHeatRefused):
                P.prepare_indexed_inputs(mesh, g, t, **options)
            gc.collect()
            self.assertEqual(budget.reserved_bytes, baseline)
        foreign = WorkBudget(64 << 20)
        with self.assertRaises(P.IndexedHeatRefused):
            P.prepare_indexed_inputs(mesh, original_g, original_t, **dict(original_options, budget=foreign))
        del mesh, view
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(foreign.reserved_bytes, 0)

    def test_required_boundary_and_boundary_topology_gates(self):
        budget = WorkBudget(64 << 20)
        record = two_cell_record(budget)
        face = next(row['face_id'] for row in record['faces'] if len(row['owners']) == 1)
        inside = next(row['face_id'] for row in record['faces'] if len(row['owners']) == 2)
        record['required_thermal_boundary_faces'] = [face]
        view = T.compact_fixture(record, budget)
        mesh = E.ExteriorMesh.from_compact(view, budget=budget)
        g, t, options = operands(record, budget)
        baseline = budget.reserved_bytes
        for boundary in (None, {face: ('temperature', 0)}, {face: ('power', float('nan'))},
                         {face: ('wrong', 1)}, {face: [1]},
                         {face: ('power', 0), '0'*64: ('power', 0)},
                         {face: ('power', 0), inside: ('power', 0)}):
            with self.subTest(boundary=boundary), self.assertRaises(P.IndexedHeatRefused):
                P.prepare_indexed_inputs(mesh, g, t, **dict(options, boundary=boundary))
            gc.collect()
            self.assertEqual(budget.reserved_bytes, baseline)
        result = P.prepare_indexed_inputs(mesh, g, t, **dict(options, boundary={face: ('power', 0)}))
        self.assertEqual(result.geometry.geometry_id, E._hash(record))
        del result, mesh, view
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_failure_traceback_cancellation_and_budget_lifetime(self):
        from atlas_tectonics.resources import MemoryLimitError
        budget = WorkBudget(64 << 20)
        record = two_cell_record(budget)
        view = T.compact_fixture(record, budget)
        mesh = E.ExteriorMesh.from_compact(view, budget=budget)
        g, t, options = operands(record, budget)
        baseline = budget.reserved_bytes
        held = None
        try:
            P.prepare_indexed_inputs(mesh, g, t, **dict(options, boundary={'0'*64: ('power', 0)}))
        except P.IndexedHeatRefused as error:
            held = error.__traceback__
        self.assertIsNotNone(held)
        self.assertGreater(budget.statistics()['categories'].get('indexed-heat-preparation', 0), 0)
        held = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        class Stop(Exception):
            pass
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if budget.statistics()['categories'].get('indexed-heat-preparation', 0):
                raise Stop('focused cancellation')
        with self.assertRaises(Stop):
            P.prepare_indexed_inputs(mesh, g, t, **options, cancel=cancel)
        self.assertGreater(calls, 1)
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        with budget.reserve(budget.available_bytes-32, category='fixture-budget-pressure'):
            with self.assertRaises(MemoryLimitError):
                P.prepare_indexed_inputs(mesh, g, t, **options)
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        del mesh, view
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
