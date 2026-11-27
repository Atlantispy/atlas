"""R2 ownership, explicit bounds, cancellation, source invalidation and storage.

No external acquisition or broad benchmark. Temporary stores use the existing
lossless transaction/dedup implementation; old evidence is never re-bound.
"""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import replace, FrozenInstanceError
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import numpy as np

from atlas_tectonics import (
    PreparedPrecursor, PrecursorSamplingLimits, InitialSamples,
    save_precursor_state, load_precursor_state, save_initial_samples, load_initial_samples,
    TectonicsError, GeologyError, InputOrigin, CoolingHistory,
    ThermalInitialProfile,
    SphericalFrame, SphericalChart, SphericalGeometry,
)
from atlas_tectonics.crust.precursor import _precursor_snapshot, restore_precursor_state
from atlas_tectonics.integration.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.codecs.storage import ArrayStore, StoreLimits
from tests.fixtures.precursor_fixtures import state,case,mixed_case,rectangle,cell,REQUEST,SOURCE
from tests.crust.test_precursor_sampling import prior_state
import tests.integration.test_precursor_contracts as contracts


class CountedCancellation:
    def __init__(self,after): self.after=after; self.count=0
    def is_set(self):
        self.count+=1
        return self.count>=self.after


class ExecutionContracts(unittest.TestCase):
    def test_plan_reservations_held_until_close(self):
        b=WorkBudget(32<<20)
        p=PreparedPrecursor(state(mixed_case()),budget=b)
        held=b.reserved_bytes
        self.assertGreater(held,0)
        p.sample_points([[1,5]],5.,**REQUEST)
        self.assertEqual(b.reserved_bytes,held)
        p.close(); self.assertEqual(b.reserved_bytes,0)
        p.close()

    def test_plan_setup_refusal_no_partial_reservation(self):
        b=WorkBudget(100)
        with self.assertRaises(MemoryLimitError): PreparedPrecursor(state(),budget=b)
        self.assertEqual(b.reserved_bytes,0)

    def test_work_refusal_retains_plan_and_releases_scratch(self):
        b=WorkBudget(7<<20)
        with PreparedPrecursor(state(),budget=b) as p:
            held=b.reserved_bytes
            with self.assertRaises(MemoryLimitError): p.sample_points(np.ones((50000,2)),1.,**REQUEST)
            self.assertEqual(b.reserved_bytes,held)
            p.sample_points([[1,1]],1.,**REQUEST)
        self.assertEqual(b.reserved_bytes,0)

    def test_cancelled_mid_query_releases_scratch_without_publication(self):
        b=WorkBudget(32<<20)
        with PreparedPrecursor(state(mixed_case()),budget=b) as p:
            held=b.reserved_bytes
            cells=tuple(cell('c'+str(i),rectangle(i,i+1)) for i in range(10))
            with self.assertRaises(CancelledError): p.sample_cells(cells,cancel=CountedCancellation(8),**REQUEST)
            self.assertEqual(b.reserved_bytes,held)
            p.sample_cells((cell(),),**REQUEST)
        self.assertEqual(b.reserved_bytes,0)

    def test_same_plan_parallel_readers_have_identical_owned_results(self):
        with PreparedPrecursor(state(mixed_case())) as p:
            def sample(_): return p.sample_points([[1,5],[8,5]],5.,**REQUEST)
            with ThreadPoolExecutor(max_workers=2) as pool: values=list(pool.map(sample,range(4)))
        self.assertEqual(len({v.sample_id for v in values}),1)
        view=values[0].array('points'); view.shape=(4,)
        self.assertEqual(values[0].array('points').shape,(2,2))
        self.assertEqual(values[1].array('points').shape,(2,2))
        with self.assertRaises(ValueError): view.setflags(write=True)

    def test_mutating_caller_array_after_sampling_does_not_change_result(self):
        points=np.array([[1.,5.],[8.,5.]]);depths=np.array([1.,5.])
        with PreparedPrecursor(state(mixed_case())) as p: r=p.sample_points(points,depths,**REQUEST)
        points[:]=99;depths[:]=99
        np.testing.assert_array_equal(r.array('points'),[[1.,5.],[8.,5.]])
        np.testing.assert_array_equal(r.array('depths_m'),[1.,5.])
        d=r.descriptor();d['frame_id']='changed'
        self.assertEqual(r.descriptor()['frame_id'],REQUEST['frame_id'])


    def test_source_invalidation_is_not_bypassed_and_close_still_releases(self):
        b=WorkBudget(32<<20);p=PreparedPrecursor(state(),budget=b)
        with p:
            p.sample_points([[1,5]],5.,**REQUEST)
        self.assertEqual(b.reserved_bytes,0)

    def test_input_and_numerical_policy_invalidate_plan_identity(self):
        with PreparedPrecursor(state()) as a, PreparedPrecursor(state(case(time_s=1.))) as b, \
             PreparedPrecursor(state(),limits=PrecursorSamplingLimits(batch_points=64)) as c:
            self.assertEqual(len({a.identity,b.identity,c.identity}),3)

    def test_explicit_point_cell_and_sparse_work_limits(self):
        with PreparedPrecursor(state(mixed_case()),limits=PrecursorSamplingLimits(max_points=1,max_cells=1,max_rows=1)) as p:
            with self.assertRaises(GeologyError): p.sample_points([[1,5],[8,5]],1.,**REQUEST)
            with self.assertRaises(GeologyError): p.sample_points([[1,5]],1.,**REQUEST)
            with self.assertRaises(GeologyError): p.sample_cells((cell('a',rectangle(0,5)),cell('b',rectangle(5,10))),**REQUEST)
            with self.assertRaises(GeologyError): p.sample_cells((cell(),),**REQUEST)

    def test_quadrature_failure_does_not_downgrade_to_midpoint(self):
        t=ThermalInitialProfile('initial','fixture','half_space',temperatures_k=(300.,1000.),diffusivity_m2_s=1e-6,cooling_start_time_s=-4e6)
        with PreparedPrecursor(state(case(thermal_profiles=(t,)))) as p:
            with mock.patch('scipy.integrate.quad',return_value=(600.,1.)):
                with self.assertRaisesRegex(GeologyError,'quadrature error'): p.sample_cells((cell(),),**REQUEST)


class PersistenceContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'precursor.db'
        self.limits=StoreLimits(4096,8<<20,32<<20,8192)
        self.store=ArrayStore(self.path,self.limits)
    def tearDown(self): self.store.close();self.tmp.cleanup()

    def test_definition_roundtrip_includes_plate_independent_geometry(self):
        s=state(mixed_case());save_precursor_state(s,self.store)
        restored=load_precursor_state(self.store,s.state_id)
        self.assertEqual(restored.state_id,s.state_id)
        self.assertEqual(restored.case.topology.domain_id,s.case.topology.domain_id)
        self.assertEqual(restored.case.topology.plate_ids,())
        self.assertEqual(restored.cooling_history,s.cooling_history)

    def test_full_sphere_definition_roundtrip(self):
        s=state(case(SphericalFrame(1000.,'world')));save_precursor_state(s,self.store)
        r=load_precursor_state(self.store,s.state_id)
        self.assertEqual(r.state_id,s.state_id)
        self.assertTrue(r.case.topology.full_sphere)

    def test_bounded_spherical_definition_roundtrip(self):
        ch=SphericalChart(SphericalFrame(1000.,'world'),(1,0,0))
        g=SphericalGeometry.polygon([(1,-.2,-.2),(1,.2,-.2),(1,.2,.2),(1,-.2,.2)],chart=ch)
        s=state(case(g));save_precursor_state(s,self.store)
        r=load_precursor_state(self.store,s.state_id)
        self.assertEqual(r.case.topology.domain.geometry_id,g.geometry_id)

    def test_point_results_restore_without_resampling(self):
        with PreparedPrecursor(prior_state()) as p: sample=p.sample_points([[1,5],[8,5]],1.,**REQUEST)
        save_initial_samples(sample,self.store)
        with mock.patch('atlas_tectonics.crust.precursor.SeededSpatialPrior.evaluate',side_effect=AssertionError('must not regenerate')):
            r=load_initial_samples(self.store,sample.sample_id)
        self.assertEqual(r.sample_id,sample.sample_id)
        np.testing.assert_array_equal(r.temperature(),sample.temperature())
        self.assertEqual(r.state.fields[0].prior.prior_id,sample.state.fields[0].prior.prior_id)

    def test_cell_snapshot_contains_actual_support_not_just_hash(self):
        with PreparedPrecursor(state(mixed_case())) as p: sample=p.sample_cells((cell(),),**REQUEST)
        save_initial_samples(sample,self.store);r=load_initial_samples(self.store,sample.sample_id)
        self.assertEqual(r.sample_id,sample.sample_id)
        support=next(iter(r.descriptor()['supports'].values()))
        self.assertEqual(r.array(support['array']).tobytes(),rectangle().wkb)
        for name in sample._buffers: np.testing.assert_array_equal(sample.array(name),r.array(name))

    def test_source_material_library_is_self_contained(self):
        helper=contracts.SourcedMaterialContracts();helper.setUpClass();s=helper.make_sourced()
        save_precursor_state(s,self.store)
        with mock.patch('atlas_tectonics.materials.material_library.earth_material_library',side_effect=AssertionError('no external lookup')):
            r=load_precursor_state(self.store,s.state_id)
        self.assertEqual(r.library.library_id,s.library.library_id)
        self.assertEqual(r.library._payload,s.library._payload)

    def test_cold_process_restoration(self):
        with PreparedPrecursor(state(mixed_case())) as p: sample=p.sample_cells((cell(),),**REQUEST)
        save_initial_samples(sample,self.store)
        script='''import sys
sys.path.insert(0,sys.argv[1])
from atlas_tectonics import load_initial_samples
from atlas_tectonics.codecs.storage import ArrayStore,StoreLimits
with ArrayStore(sys.argv[2],StoreLimits(4096,8<<20,32<<20,8192)) as store:
    s=load_initial_samples(store,sys.argv[3])
    assert s.sample_id==sys.argv[3]
    assert s.temperature()[0]==380.
    assert s.state.case.topology.plate_ids==()
    print(s.sample_id)
'''
        result=subprocess.run([sys.executable,'-I','-B','-c',script,str(Path(__file__).resolve().parents[2]/'src'),str(self.path),sample.sample_id],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),sample.sample_id)

    def test_dedup_reuses_unchanged_case_and_library_bytes(self):
        a=state();b=state(cooling_history=(CoolingHistory('initial','fixture',-11.),))
        save_precursor_state(a,self.store);save_precursor_state(b,self.store)
        am=self.store._manifest(a.state_id)['arrays'];bm=self.store._manifest(b.state_id)['arrays']
        for key in am:
            if key.startswith('case__'): self.assertEqual(am[key]['chunks'],bm[key]['chunks'])
        self.assertEqual(self.store.statistics()['snapshots'],2)

    def test_missing_snapshot_returns_none_never_generates(self):
        self.assertIsNone(load_precursor_state(self.store,'0'*64))
        self.assertIsNone(load_initial_samples(self.store,'0'*64))


    def test_missing_extra_and_changed_dependencies_refused(self):
        s=state()
        for which in ('extra','changed'):
            meta,arrays=_precursor_snapshot(s);arrays=dict(arrays)
            if which=='extra': arrays['unexpected']=np.ones(2)
            else: arrays['precursor_definition']=np.frombuffer(b'{}',dtype='u1')
            with self.subTest(which=which),self.assertRaises(TectonicsError): restore_precursor_state(meta,arrays,s.state_id)

    def test_cancelled_save_does_not_publish_partial_snapshot(self):
        s=state();e=threading.Event();e.set()
        with self.assertRaises(CancelledError): save_precursor_state(s,self.store,cancel=e)
        self.assertEqual(self.store.statistics()['snapshots'],0)

    def test_restore_budget_refusal_does_not_change_store(self):
        s=state();save_precursor_state(s,self.store)
        with self.assertRaises(MemoryLimitError): load_precursor_state(self.store,s.state_id,budget=WorkBudget(1))
        self.assertEqual(load_precursor_state(self.store,s.state_id).state_id,s.state_id)
