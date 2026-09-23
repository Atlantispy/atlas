"""Focused source-bound finite-region assembly controls."""
from concurrent.futures import CancelledError
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (FlexureParameters, FlexureBoundary1D, W04ExteriorLoads,
    W04SupportPolicy, PreparedW04Support, project_w04_support)
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.reuse import CachePolicy
from atlas_tectonics.storage import ArrayStore
from atlas_tectonics.w03_workflow import advance_w03_columns, save_w03_columns, load_w03_columns
from test_w03_workflow import initialise, workflow_fixture
from test_w04_workflow import surface
from test_w01_regional_forcing import store_limits


SOURCE = 'synthetic finite-region integration control'
ELASTIC = FlexureParameters('regional-control', SOURCE, 1584000., 1., 0., 3300., 10.)  # alpha=2m
CONTINUOUS = W04SupportPolicy(SOURCE, 'continuous-plate', 'flexure', 0., 100., .1, .01,
    ELASTIC, FlexureBoundary1D('continuous', 'continuous', SOURCE), 0.)


def exterior(state, left=(), right=(), far=(0.,0.), bounds=(0.,0.), source=SOURCE):
    return W04ExteriorLoads(state,left,right,far_left_pa=far[0],far_right_pa=far[1],
        omitted_left_bound_pa=bounds[0],omitted_right_bound_pa=bounds[1],source_id=source)


class W04RegionalWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = initialise(workflow_fixture(cells=8,length_m=8.))
        cls.s0 = surface(cls.ref)
        cls.e0 = exterior(cls.ref)
        cls.current = advance_w03_columns(cls.ref,time_s=1e6,top_effective_stress_pa=0.)

    def test_uniform_whole_line_load_and_total_reference_are_connected(self):
        applied = surface(self.ref,pressure=np.full(8,100.))
        e1 = exterior(self.ref,far=(100.,100.))
        with PreparedW04Support(self.ref,self.s0,CONTINUOUS,exterior=self.e0) as plan:
            result = plan.solve(self.ref,applied,exterior=e1)
            again = plan.solve(self.ref,applied,exterior=e1)
        assert_allclose(result.values[:,5],100./33000.,rtol=3e-14,atol=1e-16)
        assert_array_equal(result.values,again.values)
        self.assertEqual(result.result_id,again.result_id)
        assert_array_equal(result.values[:,:3],np.zeros((8,3)))
        self.assertEqual(result.descriptor()['current_exterior'],e1.input_id)
        assert_allclose(np.array(result.descriptor()['region']['output_edge_response'])[:,1:],0.,atol=2e-16)
        self.assertFalse(result.descriptor()['feedback_applied'])

    def test_explicit_halo_load_changes_crop_and_restores_cache_exactly(self):
        old = exterior(self.ref,[0.,0.],[0.])
        new = exterior(self.ref,[100.,200.],[50.])
        with tempfile.TemporaryDirectory() as directory:
            with ArrayStore(Path(directory)/'region.db',store_limits()) as store:
                with PreparedW04Support(self.ref,self.s0,CONTINUOUS,exterior=old) as plan:
                    kwargs = dict(exterior=new,store=store,cache_policy=CachePolicy(mode='always'))
                    first = plan.solve(self.ref,self.s0,**kwargs)
                    second = plan.solve(self.ref,self.s0,**kwargs)
                    self.assertGreaterEqual(plan._controller.statistics()['hits'],2)
                    assert_array_equal(first.values,second.values)
                    self.assertGreater(np.max(np.abs(first.values[:,5])),0.)
                    assert_array_equal(first.downward_load_pa,np.zeros(8))
                    save_w03_columns(self.ref,store)
                    restored = load_w03_columns(store,self.ref.state_id)
                    restored_inputs = exterior(restored,[100.,200.],[50.])
                    self.assertEqual(restored_inputs.input_id,new.input_id)
                    recovery = plan.solve(restored,self.s0,exterior=restored_inputs)
                    self.assertEqual(recovery.result_id,first.result_id)
        one = project_w04_support(self.ref,self.ref,self.s0,self.s0,CONTINUOUS,
            reference_exterior=old,current_exterior=new)
        self.assertEqual(one.result_id,first.result_id)
        # Nearest output centre x=.5; source strips are [-2,-1],[-1,0],[8,9].
        def primitive(x):
            return np.sign(x)*(1-np.exp(-abs(x)/2)*np.cos(abs(x)/2))/(2*33000.)
        expected = (100*(primitive(2.5)-primitive(1.5))+200*(primitive(1.5)-primitive(.5))
                    +50*(primitive(-7.5)-primitive(-8.5)))
        assert_allclose(first.values[0,5],expected,rtol=2e-13,atol=1e-16)

    def test_unknown_surroundings_gate_displacement_and_derivative_validity(self):
        uncertain = exterior(self.ref,bounds=(10.,10.))
        with PreparedW04Support(self.ref,self.s0,CONTINUOUS,exterior=self.e0) as plan:
            with self.assertRaisesRegex(TectonicsError,'exterior load'):
                plan.solve(self.ref,self.s0,exterior=uncertain)
        allowed = replace(CONTINUOUS,max_omitted_deflection_m=.1)
        with PreparedW04Support(self.ref,self.s0,allowed,exterior=self.e0) as plan:
            result = plan.solve(self.ref,self.s0,exterior=uncertain)
        bounds = result.descriptor()['region']['omitted_response_bounds']
        self.assertTrue(all(x>0 for x in bounds))
        for policy in (replace(allowed,max_abs_slope=bounds[1]/2),
                       replace(allowed,max_bending_strain=bounds[2]*ELASTIC.elastic_thickness_m/4)):
            with PreparedW04Support(self.ref,self.s0,policy,exterior=self.e0) as plan:
                with self.assertRaisesRegex(TectonicsError,'validity envelope'):
                    plan.solve(self.ref,self.s0,exterior=uncertain)

    def test_actual_physical_edges_not_periodic_or_implicit_exterior(self):
        applied = surface(self.ref,pressure=np.full(8,100.))
        for mode in ('free','clamped'):
            policy = replace(CONTINUOUS,boundary='physical-edges',
                region_boundary=FlexureBoundary1D(mode,mode,SOURCE))
            with PreparedW04Support(self.ref,self.s0,policy) as plan:
                result = plan.solve(self.ref,applied)
                with self.assertRaisesRegex(TectonicsError,'exterior'):
                    plan.solve(self.ref,applied,exterior=self.e0)
            ends = np.array(result.descriptor()['region']['output_edge_response'])
            if mode == 'free':
                assert_allclose(result.values[:,5],100./33000.,rtol=3e-13,atol=1e-16)
                assert_allclose(ends[:,2:],0.,atol=1e-15)
            else:
                assert_allclose(ends[:,:2],0.,atol=1e-15)
                self.assertGreater(result.values[4,5],0.)

    def test_exterior_geometry_state_and_source_are_not_guessed(self):
        with self.assertRaisesRegex(TectonicsError,'explicit exterior'):
            PreparedW04Support(self.ref,self.s0,CONTINUOUS)
        with PreparedW04Support(self.ref,self.s0,CONTINUOUS,exterior=self.e0) as plan:
            for bad in (None,exterior(self.current),exterior(self.ref,[0.])):
                with self.subTest(bad=bad),self.assertRaises(TectonicsError):
                    plan.solve(self.ref,self.s0,exterior=bad)
        a = exterior(self.ref,[1.],source='source A')
        b = exterior(self.ref,[1.],source='source B')
        self.assertNotEqual(a.input_id,b.input_id)
        with self.assertRaises(ValueError): a.left_pressure_pa.setflags(write=True)
        record = a.descriptor(); record['grid']['origin_m'] = 999
        self.assertEqual(a.descriptor()['grid']['origin_m'],self.ref.material.grid.origin_m)
        for values in (dict(bounds=(-1.,0.)),dict(far=(float('nan'),0.))):
            with self.assertRaises(TectonicsError): exterior(self.ref,**values)

    def test_thermal_exterior_is_explicit_and_budget_cancel_release(self):
        budget = WorkBudget(16<<20)
        now = surface(self.current)
        with PreparedW04Support(self.ref,self.s0,CONTINUOUS,exterior=self.e0,budget=budget) as plan:
            retained = budget.reserved_bytes
            local = plan.solve(self.current,now,exterior=exterior(self.current))
            thermal = float(local.values[0,2])
            whole = plan.solve(self.current,now,exterior=exterior(self.current,far=(thermal,thermal)))
            assert_allclose(whole.values[:,5],thermal/33000.,rtol=2e-12,atol=1e-12)
            self.assertGreater(np.max(np.abs(local.values[:,5]-whole.values[:,5])),1e-10)
            self.assertEqual(budget.reserved_bytes,retained)
            event = threading.Event();event.set()
            with self.assertRaises(CancelledError): plan.solve(self.current,now,exterior=exterior(self.current),cancel=event)
            self.assertEqual(budget.reserved_bytes,retained)
        self.assertEqual(budget.reserved_bytes,0)


if __name__ == '__main__':
    unittest.main()
