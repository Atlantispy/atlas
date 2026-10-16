"""Bounded source/real two-cell numerical controls; never owner acceptance."""
import ast
import gc
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

import exterior_mesh_patch as E_PATCH
import mimetic_patch as M_PATCH
import private_heat_bundle as B
import private_heat_indexed_runtime as P
import test_private_heat_mesh_patch as FIXTURE


HERE = Path(__file__).resolve().parent
R = HERE.parent
T = HERE.parents[4]
BASE = HERE.parents[1]/'runtime-integration-r1'
H = HERE.parents[3]/'heat-repair-20261007'
_temporary = None
_path = None


def authenticated_inputs():
    raw = (BASE/'manifest.json').read_bytes()
    if sha256(raw).hexdigest() != '597c00328bb8aede225a8a936dcea2edab42d3c894eb87caeb974fdfd576979d':
        raise ValueError('fixture predecessor manifest changed')
    manifest = json.loads(raw)
    values = {}
    for name, digest in manifest['files'].items():
        path = T/name
        if path.parent == H and path.name.startswith('private_heat_') and path.suffix == '.py':
            content = path.read_bytes()
            if sha256(content).hexdigest() != digest:
                raise ValueError('fixture dependency changed: '+name)
            values[path.name] = content
    return manifest, values


def setUpModule():
    global _temporary, _path, I, E, M, WorkBudget, source_report
    if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
        raise RuntimeError('fresh source-selected test process required')
    manifest, inputs = authenticated_inputs()
    heat, source_report = B.construct(inputs, reference_root=H, reference_pins=B.REFERENCE_PINS)
    _temporary = tempfile.TemporaryDirectory(prefix='indexed-heat-', dir=T)
    root = Path(_temporary.name)
    outputs = dict(heat)
    for name, digest in manifest['source_hashes'].items():
        raw = (BASE/'runtime-src'/name).read_bytes()
        if sha256(raw).hexdigest() != digest:
            raise ValueError('native fixture source changed')
        if name.endswith('/integration_exterior_mesh.py'):
            raw = E_PATCH.transform(raw.decode()).encode()
        elif name.endswith('/integration_mimetic_heat.py'):
            raw = M_PATCH.mimetic_source(raw.decode()).encode()
        outputs[name] = raw
    for name, raw in outputs.items():
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    _path = list(sys.path)
    sys.path[:0] = [str(root), str(HERE), str(R), str(BASE/'ram'), str(BASE/'helpers'), str(H),
                   str(H/'source/tectonics/tests')]
    I = importlib.import_module('private_heat_native_issuer_r12')
    E = importlib.import_module('atlas_tectonics.integration_exterior_mesh')
    M = importlib.import_module('atlas_tectonics.integration_mimetic_heat')
    WorkBudget = importlib.import_module('atlas_tectonics.resources').WorkBudget
    FIXTURE.E = E
    FIXTURE.T.E = E


def tearDownModule():
    if _path is not None:
        sys.path[:] = _path
    if _temporary is not None:
        _temporary.cleanup()


def synthetic_call(execution, geometry):
    cap = np.asarray([float(c[0])*3 for c in geometry._cells])
    arrays = dict(enthalpy_j=cap*300, capacity_j_k=cap, source_w=np.zeros(len(cap)))
    snapshot = I.RegionalMechanicalSnapshot(dict(schema='EXPLICIT_SYNTHETIC_COMPACT_FIXTURE'), arrays)
    target = '1e-24'
    plan = dict(schema='atlas.private.composed-heat-plan.r1', method_id=I.METHOD,
        geometry_id=geometry.geometry_id, conductivity_w_m_k=[1.]*len(cap),
        absolute_residual_target=I._enc(I.Fraction(target)),
        absolute_residual_target_decimal=target,
        original_target=dict(kind='decimal-string', value=target), boundary={})
    meta = dict(schema='atlas.private.composed-owner-call.r1', state_id=snapshot.result_id,
        duration_s=.125, cell_ids=list(P.ordered_cell_ids(geometry)),
        source_policy='EXPLICIT_SYNTHETIC_FIXTURE_NOT_OWNER_ACCEPTANCE')
    return I._make_call(meta, arrays, geometry, execution, plan, (snapshot,), fixture=True)


class IndexedRuntime(unittest.TestCase):
    def test_source_guards_and_finite_dependency_closure(self):
        self.assertFalse(source_report['checkpoint_admission'])
        self.assertFalse(source_report['numerical_algorithm_changed'])
        for name in ('_make_call', '_verify_implementation', '_verified_call', 'advance', '_advance_verified'):
            before = ast.parse((H/'private_heat_native_issuer_r12.py').read_bytes())
            after = ast.parse(Path(I.__file__).read_bytes())
            a = next(n for n in before.body if isinstance(n, ast.FunctionDef) and n.name == name)
            b = next(n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertEqual(ast.dump(a), ast.dump(b), name)
        self.assertEqual(I.CERT.__file__, str(Path(_temporary.name)/'private_heat_certification_kernel_r1.py'))
        for transform, name in ((P.issuer_source, 'private_heat_native_issuer_r12.py'),
                                (P.projection_source, 'private_heat_native_projection_r4.py')):
            with self.assertRaises(ValueError):
                transform((H/name).read_text()+'\n')
        CAS = importlib.import_module('private_heat_checkpoint_consumer_r9')
        CAS._verify(None)
        J = importlib.import_module('private_heat_joined_consumer_r6')
        J._verify(None)
        joined = importlib.import_module('private_heat_original_joined_r6')
        self.assertIn('endpoint_checkpoints', joined._advance_current_interval.__kwdefaults__)
        self.assertIn('forward-completed-query-owner', joined.derivation()['changes'])

    def test_reopen_compares_all_mesh_bytes_without_expansion(self):
        budget = WorkBudget(64 << 20)
        record = FIXTURE.two_cell_record(budget)
        left = FIXTURE.T.compact_fixture(record, budget)
        right = FIXTURE.T.compact_fixture(record, budget)
        actual = dict(state_id='synthetic', thermal_mesh=left)
        expected = dict(state_id='synthetic', thermal_mesh=right)
        state = SimpleNamespace(_snapshot=None, _budget=budget, record=lambda: actual)
        P.compare_spatial_records(self, state, expected)
        # Different chunk boundaries (ordinary dict vs compact stream) are
        # compared byte-for-byte as well; no hash equality substitutes for it.
        P.compare_spatial_records(self, state, dict(expected, thermal_mesh=record))
        changed = dict(record, extra_unrecognised_field='different')
        with self.assertRaises(AssertionError):
            P.compare_spatial_records(self, state, dict(expected, thermal_mesh=changed))
        del state, expected, actual, left, right
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_indexed_numerical_projection_exact_parity_no_whole_export(self):
        budget = WorkBudget(256 << 20)
        record = FIXTURE.two_cell_record(budget)
        view = FIXTURE.T.compact_fixture(record, budget)
        ordinary = M.MimeticGeometry(record, budget=budget)
        indexed = M.MimeticGeometry.from_compact(view, budget=budget)
        self.assertEqual(P.metric_identity(indexed), P.metric_identity(ordinary))
        with I.ExecutionContext('scipy') as execution:
            old_call = synthetic_call(execution, ordinary)
            new_call = synthetic_call(execution, indexed)
            expected = I.advance(old_call)
            # Profiling would alter ExecutionContext runtime eligibility. The
            # compact geometry has _encoded=None and record() refuses anyway;
            # both conditions make an accidental eager legacy path fail.
            self.assertIsNone(indexed._encoded)
            actual = I.advance(new_call)
            for name in expected.array_names:
                self.assertEqual(expected.array(name).tobytes(), actual.array(name).tobytes(), name)
            a, b = expected.descriptor(), actual.descriptor()
            for key in ('exact_corrected_enthalpy_j', 'exact_retained_solver_residual_j',
                        'exact_stock_projection_residual_j', 'exact_cell_storage_residual_j',
                        'exact_paired_face_energy_j', 'exact_source_energy_j',
                        'exact_outward_boundary_energy_j', 'geometry_id', 'cell_ids', 'face_ids'):
                self.assertEqual(a[key], b[key], key)
            self.assertFalse(b['genuine_forward_origin'])
            self.assertFalse(b['production_acceptance'])
            del old_call, new_call, expected, actual, a, b
        del indexed, ordinary, view
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_joined_rows_are_bounded_and_keep_ownership(self):
        budget = WorkBudget(64 << 20)
        record = FIXTURE.two_cell_record(budget)
        view = FIXTURE.T.compact_fixture(record, budget)
        mesh = E.ExteriorMesh.from_compact(view, budget=budget)
        rows = P.mesh_rows(mesh)
        self.assertEqual(len(rows['cells']), len(record['cells']))
        cell = next(iter(rows['cells']))
        self.assertEqual(cell['logical_cell_id'], record['cells'][0]['logical_cell_id'])
        self.assertIs(P.stored_mesh(mesh), view)
        del rows, mesh, view
        gc.collect()
        self.assertGreater(budget.reserved_bytes, 0)
        self.assertEqual(cell['logical_cell_id'], record['cells'][0]['logical_cell_id'])
        del cell
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
