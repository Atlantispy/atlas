"""Compact-cell state identity and actual native issue/restore method controls.

The mesh uses the existing exact two-box fixture; owner provenance is synthetic.
No solver, historical database, source funding or migrated-owner acceptance runs.
"""
import ast
from copy import deepcopy
from dataclasses import replace
import gc
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
R = HERE.parent
I = R.parent/'runtime-integration-r1'/'runtime-src'
sys.path.insert(0, str(I))
sys.path.insert(0, str(R))

import numpy as np
from atlas_tectonics import integration_spatial_owner as O
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope
from compact_contracts import ContractError
import exchange_record_patch as E
import record_tables as RT
from record_views import RecordRef
import spatial_indexed_patch as X
import spatial_transfer as S
import spatial_validation_patch as V
from test_mesh_tables import small_mesh_record, compact_fixture


def native_methods():
    source = (I/'atlas_tectonics'/'integration_spatial_owner.py').read_text(encoding='utf8')
    indexed = X.transform(S.spatial_owner_source(source))
    if sha256(indexed.encode()).hexdigest() != E.INDEXED_OWNER_SHA:
        raise AssertionError('helper-only change altered indexed source transform')
    changed = V.owner_source(E.holder_source(indexed))
    tree = ast.parse(changed)
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PreparedSpatialOwner')
    wanted = ('_issue', '_bound', 'restore')
    methods = [n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    methods += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_carried_start_cells']
    env = dict(O.__dict__, _SV=V)
    exec(compile(ast.Module(body=methods, type_ignores=[]), '<actual-owner-methods>', 'exec'), env)
    return {name: env[name] for name in (*wanted, '_carried_start_cells')}


class SpatialCompactCellsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.methods = native_methods()

    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='wp5-compact-state-cells')
        self.mesh_record = small_mesh_record(self.budget)
        for row in self.mesh_record['cells']:
            row['kind'] = 'exterior'
        self.mesh = compact_fixture(self.mesh_record, self.budget)[0]
        self.owner = object.__new__(O.PreparedSpatialOwner)
        self.owner._budget = self.budget
        self.owner._record_scope = self.scope
        self.owner.owner_id = 'a'*64
        self.owner._funding = SimpleNamespace(funding_id=self.mesh_record['funding_id'])
        self.owner._definition = dict(grid_id=self.mesh_record['grid_id'])
        self.owner._names = ('mass_kg', 'enthalpy_j')
        self.owner._nonnegative = ('mass_kg',)
        self.owner._finite = self.owner._measure_policy = None
        self.owner._verify = lambda: None
        for name, method in self.methods.items():
            if name != '_carried_start_cells':
                setattr(self.owner, name, MethodType(method, self.owner))
        self.cells = [dict(cell_id=row['logical_cell_id'], source_key=['synthetic', i],
            volume_m3=O._enc(1), exact=dict(mass_kg=O._enc(i+1), enthalpy_j=O._enc(3*(i+1))))
            for i, row in enumerate(self.mesh_record['cells'])]
        self.body = dict(schema='atlas.spatial-exterior-state.v1', owner_id=self.owner.owner_id,
            funding_id=self.owner._funding.funding_id, time_s=0., intervals=1,
            parent_state_id='b'*64, collar_state_id='c'*64,
            support_id=self.mesh_record['support_id'], trajectory_id=self.mesh_record['trajectory_id'],
            trajectory=dict(segments=[]), grid_id=self.mesh_record['grid_id'],
            thermal_mesh_id=self.mesh.geometry_id, thermal_mesh=self.mesh, cells=self.cells,
            projection_accounts={name: O._enc(0) for name in self.owner._names})
        self.packed = RT.RecordCodec().pack_record(self.cells, record_schema='atlas.spatial-cells.v1',
                                                  scope=self.scope, check=lambda: None)
        self.reference = self.packed.root()
        self.compact_body = dict(self.body, cells=self.reference)
        self.mesh_reference = dict(schema=X.REFERENCE_SCHEMA, snapshot_key='d'*64,
            geometry_id=self.mesh.geometry_id, source_producer=dict(fixture='synthetic'),
            array_bindings={'mesh': 'e'*64})

    def tearDown(self):
        self.compact_body = None
        gc.collect()
        self.reference.close()
        self.packed.close()
        self.scope.close()
        self.owner = self.mesh = self.body = self.mesh_record = self.cells = None
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def test_native_issue_exact_identity_arrays_and_preserved_compact_cell_views(self):
        del self.owner._record_scope
        original = self.owner._issue(self.body)
        self.owner._record_scope = self.scope
        compact = self.owner._issue(self.compact_body)
        self.assertIs(type(compact), O.SpatialExteriorState)
        self.assertEqual(compact.state_id, original.state_id)
        native = RegionalMechanicalSnapshot(dict(self.body, thermal_mesh=self.mesh_record), compact.arrays())
        self.assertEqual(compact.state_id, native.result_id)
        self.assertNotIn('cells', json.loads(compact._snapshot._metadata))
        self.assertIsInstance(compact._snapshot._cells, RecordRef)
        self.assertEqual(X.snapshot_identity(compact._snapshot), original.state_id)
        for name, array in original.arrays().items():
            np.testing.assert_array_equal(array, compact.arrays()[name])
        logical = X.logical_record(compact)
        indexed = X.indexed_record(compact)
        self.assertIsInstance(logical['cells'], RecordRef)
        self.assertIsInstance(indexed.value['cells'], RecordRef)
        self.assertEqual(S._stream_stats(dict(logical, state_id=None))[0],
                         S._stream_stats(dict(self.compact_body, state_id=None))[0])
        self.assertEqual(self.owner._bound(compact)['owner_id'], self.owner.owner_id)
        del logical, indexed, compact, original, native, array

    def test_fresh_native_cells_are_packed_once_under_explicit_scope(self):
        with patch.object(RT.RecordCodec, 'pack_record', autospec=True,
                          side_effect=RT.RecordCodec.pack_record) as packed:
            state = self.owner._issue(self.body)
            self.assertEqual(packed.call_count, 1)
        self.assertIsInstance(state._snapshot._cells, RecordRef)
        self.assertNotIn('cells', json.loads(state._snapshot._metadata))
        del state
        del self.owner._record_scope
        legacy = self.owner._issue(self.body)
        self.assertIsNone(legacy._snapshot._cells)
        self.assertEqual(json.loads(legacy._snapshot._metadata)['cells'], self.cells)
        del legacy
        self.owner._record_scope = self.scope

    def test_native_restore_and_validate_only_keep_cells_compact(self):
        original = self.owner._issue(self.body)
        public = dict(self.compact_body, state_id=original.state_id)
        restored = self.owner.restore(public, original.arrays())
        self.assertIsInstance(restored._snapshot._cells, RecordRef)
        self.assertEqual(restored.state_id, original.state_id)
        checked = self.owner.restore(public, original.arrays(), _validate_only=True)
        self.assertEqual(checked['state_id'], original.state_id)
        from spatial_records_patch import _OwnedDict
        metadata = RT.RecordCodec().pack_record(X._small_body(self.compact_body),
            record_schema='test.state-metadata.v1', scope=self.scope, check=lambda: None)
        with metadata.root() as root:
            held = root.export(max_logical_bytes=4 << 20, max_owned_bytes=4 << 20)
        owned_public = _OwnedDict(dict(held.value, cells=self.reference, thermal_mesh=self.mesh,
                                      state_id=original.state_id), [held])
        owned_restore = self.owner.restore(owned_public, original.arrays())
        self.assertEqual(owned_restore.state_id, original.state_id)
        class UnknownDict(dict):
            pass
        with self.assertRaises(O.TectonicsError):
            self.owner.restore(UnknownDict(public), original.arrays())
        envelope = X.compact_record(restored, mesh_reference=self.mesh_reference)
        self.assertIsInstance(envelope.value['state']['cells'], RecordRef)
        again = X.restore_compact(self.owner, envelope.value, restored.arrays(), compact_mesh=self.mesh,
                                  expected_mesh_reference=self.mesh_reference)
        self.assertEqual(again.state_id, original.state_id)
        del checked, again, envelope, restored, public, original, owned_restore, owned_public
        held.close()
        metadata.close()

    def test_native_carried_rows_keep_original_and_differential_values_funded(self):
        carry = self.methods['_carried_start_cells']
        before = self.budget.reserved_bytes
        previous = carry(self.compact_body, {})
        self.assertEqual(dict(previous), {row['cell_id']: row for row in self.cells})
        self.assertGreater(self.budget.reserved_bytes, before)
        del previous
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)
        geometry = dict(physical_geometry_family='differential-plate-component-partition-v1',
            parent_partition_id=None,
            identity_start_cells=[dict(parent_cell_id=row['cell_id'], cell_id='child:'+str(i))
                                  for i, row in enumerate(self.cells)],
            cells=[dict(cell_id='child:'+str(i), kind='exterior', source_key=row['source_key'])
                   for i, row in enumerate(self.cells)])
        carried = carry(self.compact_body, geometry)
        self.assertEqual(carried, {'child:'+str(i): dict(row, cell_id='child:'+str(i))
                                   for i, row in enumerate(self.cells)})
        self.assertGreater(self.budget.reserved_bytes, before)
        del carried
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)

    def test_native_changed_id_arrays_and_positive_row_refuse(self):
        original = self.owner._issue(self.body)
        public = dict(self.compact_body, state_id=original.state_id)
        with self.assertRaises(O.TectonicsError):
            self.owner.restore(dict(public, state_id='0'*64), original.arrays())
        changed = {name: values.copy() for name, values in original.arrays().items()}
        changed['volume_m3'][0] += 1
        with self.assertRaises(O.TectonicsError):
            self.owner.restore(public, changed)
        rows = deepcopy(self.cells)
        rows[0]['volume_m3'] = O._enc(0)
        packed = RT.RecordCodec().pack_record(rows, record_schema='atlas.spatial-cells.v1',
                                              scope=self.scope, check=lambda: None)
        child = packed.root()
        with self.assertRaisesRegex(O.TectonicsError, 'positive-cell'):
            self.owner.restore(dict(public, cells=child), original.arrays())
        child.close()
        packed.close()
        del original, public

    def test_whole_cells_export_and_whole_mesh_materialisation_are_never_called(self):
        original_export = RecordRef.export
        def row_only(reference, **bounds):
            if reference.kind == 'array':
                raise AssertionError('whole cells export')
            self.assertLessEqual(bounds['max_owned_bytes'], X.CELL_ROW_BYTES)
            return original_export(reference, **bounds)
        with patch.object(RecordRef, 'export', row_only), patch.object(
                type(self.mesh), 'legacy_record', side_effect=AssertionError('whole mesh export')):
            state = self.owner._issue(self.compact_body)
            self.assertEqual(X.snapshot_identity(state._snapshot), state.state_id)
            record = X.logical_record(state)
            restored = self.owner.restore(dict(record), state.arrays())
            self.assertEqual(restored.state_id, state.state_id)
            del record, restored, state

    def test_snapshot_forgery_and_foreign_cell_owner_refuse(self):
        state = self.owner._issue(self.compact_body)
        with self.assertRaises(X.IndexedSpatialRefused):
            X.snapshot_identity(replace(state._snapshot, result_id='0'*64))
        with self.assertRaises(X.IndexedSpatialRefused):
            X.snapshot_identity(replace(state._snapshot, _cells=None))
        other_budget = WorkBudget(1 << 20)
        other_scope = create_retained_scope(other_budget, process_epoch='foreign-cells')
        packed = RT.RecordCodec().pack_record(self.cells, record_schema='atlas.spatial-cells.v1',
                                              scope=other_scope, check=lambda: None)
        child = packed.root()
        with self.assertRaises(X.IndexedSpatialRefused):
            self.owner._issue(dict(self.body, cells=child))
        child.close()
        packed.close()
        other_scope.close()
        self.assertEqual(other_budget.reserved_bytes, 0)
        del state

    def test_escaped_state_rows_and_arrays_remain_funded(self):
        before = self.budget.reserved_bytes
        state = self.owner._issue(self.compact_body)
        logical = X.logical_record(state)
        rows = X.iter_state_cells(logical['cells'], self.budget)
        row = next(rows)
        rows.close()
        array = state.arrays()['mass_kg']
        del state, logical, rows
        gc.collect()
        self.assertGreater(self.budget.reserved_bytes, before)
        self.assertEqual(row['exact'], self.cells[0]['exact'])
        self.assertFalse(array.flags.writeable)
        del row, array
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)

    def test_oversized_row_refuses_without_exporting_cells(self):
        rows = deepcopy(self.cells)
        rows[0]['note'] = 'x'*(4 << 20)
        packed = RT.RecordCodec().pack_record(rows, record_schema='atlas.spatial-cells.v1',
                                              scope=self.scope, check=lambda: None)
        child = packed.root()
        with self.assertRaises(ContractError):
            list(X.iter_state_cells(child, self.budget))
        gc.collect()
        child.close()
        packed.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
