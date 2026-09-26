"""New W12 integration seams only; native scientific suites are not replayed."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from pathlib import Path
import copy
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'examples'), str(ROOT/'tools')]
from atlas_tectonics.assembly import PreparedColumnAssembly, read_product
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.w03_workflow import advance_w03_columns
from atlas_tectonics.w04_workflow import PreparedW04Support, W04SurfaceInputs
from w12_column_case import make_column_case
from w12_graph import run_graph


def context(case):
    p = case['provenance']
    return dict(world_id='synthetic', snapshot_id='w12', calendar_id=p['epoch']['id'],
        spatial_frame_id=p['frame']['id'], vertical_reference=p['frame']['depth_reference_id'], scenario_id='control')


def owner(path, budget):
    return ArrayStore(path, limits=StoreLimits(4096,8<<20,32<<20, max_manifest_bytes=1<<20,
        sqlite_cache_bytes=65536, verified_cache_entries=32), budget=budget)


def prepare(case, store, budget, **overrides):
    options = dict(store=store, context=context(case), source_id='w12-test',
        reservoir_weights=np.full(8,.125), external_pressure_pa=np.zeros(8), budget=budget)
    options.update(overrides)
    return PreparedColumnAssembly(case['initial'],case['initial_surface'],case['support_policy'],case['schedule'],**options)


class W12AssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = make_column_case(cells=8)

    def test_direct_clean_incremental_recovery_graph_and_full_fields(self):
        case = self.case
        state = case['initial']
        with PreparedW04Support(state,case['initial_surface'],case['support_policy']) as support:
            for step in case['schedule']:
                state = advance_w03_columns(state,**step)
            surface = W04SurfaceInputs(state,case['initial_surface'].cell_ids,
                np.full(8,state.reservoir_fluid_m3/8),np.zeros(8),source_id='w12-test')
            reference = support.solve(state,surface)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            b = WorkBudget(128<<20)
            with owner(tmp/'clean.db',b) as store, prepare(case,store,b) as plan:
                clean = plan.run()
                arrays = plan.read_fields(clean)
                np.testing.assert_array_equal(arrays['support.values'], reference.values)
                np.testing.assert_array_equal(arrays['cohort_thickness_m'],state.material.thickness_m)
                self.assertEqual(clean['native_state_id'],state.state_id)
                self.assertEqual(plan.statistics(),dict(computed_outputs=3,restored_outputs=0))
            self.assertEqual(b.reserved_bytes,0)
            with owner(tmp/'restart.db',b) as store, prepare(case,store,b) as plan:
                plan.run(1)
                self.assertEqual(plan.statistics()['computed_outputs'],2)
            with owner(tmp/'restart.db',b) as store, prepare(case,store,b) as plan:
                recovered = plan.run()
                self.assertEqual(recovered,clean)
                self.assertEqual(plan.statistics(),dict(computed_outputs=1,restored_outputs=2))
                for name,a in plan.read_fields(recovered).items():
                    np.testing.assert_array_equal(a,arrays[name])
                first = run_graph(plan,graph_cache_root=tmp/'graph')
                before = plan.statistics()
                second = run_graph(plan,graph_cache_root=tmp/'graph')
                self.assertEqual(first['product'],second['product'])
                self.assertEqual(first['inspection'],second['inspection'])
                self.assertEqual(plan.statistics(),before)
                self.assertEqual(plan.statistics()['computed_outputs'],1)
            self.assertEqual(b.reserved_bytes,0)

    def test_context_schedule_and_mutation_refusals(self):
        case = self.case
        with tempfile.TemporaryDirectory() as tmp:
            b = WorkBudget(128<<20)
            with owner(Path(tmp)/'s.db',b) as store:
                bad = context(case); bad['spatial_frame_id'] = 'other-frame'
                with self.assertRaises(TectonicsError):prepare(case,store,b,context=bad)
                with self.assertRaises(TectonicsError):prepare(case,store,b,reservoir_weights=np.ones(4))
                with prepare(case,store,b) as plan:
                    with self.assertRaises(TectonicsError):plan.run(True)
                    original = plan.context; original['world_id']='mutated'
                    self.assertNotEqual(original,plan.context)
                    with self.assertRaises(AttributeError):plan.plan_id='other'
                    product = plan.run(0)
                    changed = copy.deepcopy(product); changed['context']['scenario_id']='other'
                    with self.assertRaises(TectonicsError):plan.verify_product(changed)
                    changed = copy.deepcopy(product); changed['time_s']=1.
                    with self.assertRaises(TectonicsError):plan.verify_product(changed)
            self.assertEqual(b.reserved_bytes,0)

    def test_cancel_before_commit_and_missing_native_dependency_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = WorkBudget(128<<20)
            with owner(Path(tmp)/'s.db',b) as store, prepare(self.case,store,b) as plan:
                cancelled = threading.Event(); cancelled.set()
                with self.assertRaises(CancelledError):plan.run(cancel=cancelled)
                self.assertFalse(store.contains(plan._key(0)))
                product = plan.run(0)
                store._db.execute('DELETE FROM snapshots WHERE id=?',(product['native_state_id'],))
                store._db.commit()
                with self.assertRaises(TectonicsError):plan.verify_product(product)
            self.assertEqual(b.reserved_bytes,0)

    def test_initial_surface_policy_mismatch_refuses_before_support_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = WorkBudget(128<<20)
            with owner(Path(tmp)/'s.db',b) as store:
                baseline = b.reserved_bytes
                weights = np.full(8,.125); weights[:2] += (.001,-.001)
                with patch('atlas_tectonics.assembly.PreparedW04Support') as support:
                    for options, message in ((dict(external_pressure_pa=np.full(8,1e-3)), 'external pressure'),
                                             (dict(reservoir_weights=weights), 'reservoir allocation')):
                        with self.subTest(policy=message), self.assertRaisesRegex(TectonicsError,message):
                            prepare(self.case,store,b,**options)
                        self.assertEqual(b.reserved_bytes,baseline)
                    support.assert_not_called()
            self.assertEqual(b.reserved_bytes,0)

    def test_initial_surface_uses_exact_policy_values_and_preserves_supplied_identity(self):
        initial = self.case['initial']
        weights = np.arange(1.,9.)/36.
        pressure = np.full(8,1e-3)
        allocation = weights*initial.reservoir_fluid_m3
        authored = allocation.copy(); authored[0] = np.nextafter(authored[0],np.inf)
        supplied = W04SurfaceInputs(initial,self.case['initial_surface'].cell_ids,
            authored,pressure,source_id='independent-initial-surface')
        case = dict(self.case,initial_surface=supplied)
        with tempfile.TemporaryDirectory() as tmp:
            b = WorkBudget(128<<20)
            with owner(Path(tmp)/'s.db',b) as store, prepare(case,store,b,
                    reservoir_weights=weights,external_pressure_pa=pressure) as plan:
                self.assertEqual(plan.initial_surface.source_id,supplied.source_id)
                self.assertEqual(plan.initial_surface.state_id,supplied.state_id)
                np.testing.assert_array_equal(plan.initial_surface.reservoir_volume_m3,allocation)
                self.assertEqual(plan._surface(initial,None).reservoir_volume_m3.tobytes(),allocation.tobytes())
                product = plan.run(0)
                self.assertEqual(product['definition']['supplied_initial_surface_id'],supplied.input_id)
                self.assertEqual(product['definition']['initial_surface_id'],plan.initial_surface.input_id)
                fields = plan.read_fields(product)
                self.assertEqual(fields['reservoir_volume_m3'].tobytes(),allocation.tobytes())
                np.testing.assert_array_equal(fields['support.values'],np.zeros((8,8)))
            self.assertEqual(b.reserved_bytes,0)

    def test_close_from_foreign_thread_refuses_without_releasing_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = WorkBudget(128<<20)
            with owner(Path(tmp)/'s.db',b) as store:
                baseline = b.reserved_bytes
                with prepare(self.case,store,b) as plan:
                    retained = b.reserved_bytes
                    with ThreadPoolExecutor(max_workers=1) as worker:
                        with self.assertRaisesRegex(TectonicsError,'owning thread'):
                            worker.submit(plan.close).result()
                    self.assertEqual(b.reserved_bytes,retained)
                    plan.verify()
                    self.assertFalse(plan._support._closed)
                self.assertEqual(b.reserved_bytes,baseline)
                plan.close()
            self.assertEqual(b.reserved_bytes,0)

    def test_low_budget_and_closed_owner_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = WorkBudget(128<<20)
            with owner(Path(tmp)/'s.db',b) as store:
                with b.reserve((128<<20)-b.reserved_bytes-(1<<20)):
                    with self.assertRaises(MemoryLimitError):prepare(self.case,store,b)
                plan=prepare(self.case,store,b); plan.close()
                with self.assertRaises(TectonicsError):plan.run()
            self.assertEqual(b.reserved_bytes,0)


if __name__ == '__main__':
    unittest.main()
