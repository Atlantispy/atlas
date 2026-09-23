"""Actual W03 integration, provenance and recovery for fixed variable rigidity."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (RigidityProfile1D,VariableFlexureAccuracy,FlexureBoundary1D,
    PreparedW04Support,project_w04_support,RegionalGrid1D)
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.reuse import CachePolicy
from atlas_tectonics.storage import ArrayStore
from atlas_tectonics.w03_workflow import save_w03_columns,load_w03_columns
from test_w03_workflow import initialise,workflow_fixture
from test_w04_workflow import surface
from test_w04_regional_workflow import CONTINUOUS,exterior,ELASTIC
from test_w01_regional_forcing import store_limits


SOURCE='synthetic variable-support integration, not geological calibration'
ACCURACY=VariableFlexureAccuracy(SOURCE,1e-3,1e-10,1e-10,1e-10)


def profile(state,*,halo=0,frame=None,te=None,far=True,source=SOURCE):
    grid=state.material.grid;n=grid.cells+2*halo
    full=RegionalGrid1D(n,n*grid.spacing_m,grid.origin_m-halo*grid.spacing_m)
    ids=state.source_workflow.initial_samples.descriptor()
    material=(ELASTIC.young_modulus_pa,1.,ELASTIC.poisson_ratio)
    return RigidityProfile1D(full,np.full(n,ELASTIC.young_modulus_pa),
        np.linspace(1.,1.5,n) if te is None else te,np.full(n,ELASTIC.poisson_ratio),
        source_id=source,frame_id=ids['frame_id'] if frame is None else frame,
        datum_id=state.binding.depth_reference_id,epoch_id=state.binding.epoch_id,
        far_left=material if far else None,far_right=material if far else None)


class W04VariableWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref=initialise(workflow_fixture(cells=8,length_m=8.))
        cls.zero=surface(cls.ref);cls.e0=exterior(cls.ref)
        cls.profile=profile(cls.ref)

    def test_connected_uniform_load_with_variable_stiffness_and_total_reference(self):
        applied=surface(self.ref,pressure=np.full(8,100.))
        outside=exterior(self.ref,far=(100.,100.))
        with PreparedW04Support(self.ref,self.zero,CONTINUOUS,exterior=self.e0,
                rigidity=self.profile,accuracy=ACCURACY) as plan:
            result=plan.solve(self.ref,applied,exterior=outside)
            again=plan.solve(self.ref,applied,exterior=outside)
        assert_allclose(result.values[:,5],100/33000.,rtol=3e-13,atol=1e-14)
        assert_array_equal(result.values,again.values)
        self.assertEqual(result.result_id,again.result_id)
        data=result.descriptor()['region']
        self.assertEqual(data['profile_id'],self.profile.profile_id)
        self.assertGreaterEqual(data['subdivisions'],2)
        self.assertEqual(data['rigidity_time_dependence'],'fixed reference profile; time-varying rigidity unsupported')
        assert_array_equal(result.values[:,:3],np.zeros((8,3)))

    def test_halo_profile_cache_source_change_and_exact_restore(self):
        old=exterior(self.ref,[0.],[0.]);now=exterior(self.ref,[200.],[50.])
        p=profile(self.ref,halo=1)
        with tempfile.TemporaryDirectory() as directory:
            with ArrayStore(Path(directory)/'variable.db',store_limits()) as store:
                with PreparedW04Support(self.ref,self.zero,CONTINUOUS,exterior=old,
                        rigidity=p,accuracy=ACCURACY) as plan:
                    kwargs=dict(exterior=now,store=store,cache_policy=CachePolicy(mode='always'))
                    a=plan.solve(self.ref,self.zero,**kwargs)
                    b=plan.solve(self.ref,self.zero,**kwargs)
                    self.assertGreaterEqual(plan._controller.statistics()['hits'],2)
                    self.assertEqual(a.result_id,b.result_id)
                    save_w03_columns(self.ref,store)
                    restored=load_w03_columns(store,self.ref.state_id)
                    c=plan.solve(restored,surface(restored),exterior=exterior(restored,[200.],[50.]))
                    self.assertEqual(c.result_id,a.result_id)
        one=project_w04_support(self.ref,self.ref,self.zero,self.zero,CONTINUOUS,
            reference_exterior=old,current_exterior=now,rigidity=p,accuracy=ACCURACY)
        self.assertEqual(one.result_id,a.result_id)
        self.assertGreater(np.max(np.abs(a.values[:,5])),0.)
        self.assertNotEqual(p.profile_id,profile(self.ref,halo=1,source='different source').profile_id)

    def test_periodic_and_physical_edges_connect_without_invented_exterior(self):
        p=profile(self.ref,far=False)
        applied=surface(self.ref,pressure=np.full(8,100.))
        for mode in ('periodic','free','clamped'):
            policy=(replace(CONTINUOUS,boundary='periodic-repetition',region_boundary=None) if mode=='periodic'
                    else replace(CONTINUOUS,boundary='physical-edges',region_boundary=FlexureBoundary1D(mode,mode,SOURCE)))
            with PreparedW04Support(self.ref,self.zero,policy,rigidity=p,accuracy=ACCURACY) as plan:
                result=plan.solve(self.ref,applied)
            if mode=='clamped':
                ends=np.array(result.descriptor()['region']['output_edge_response'])
                assert_allclose(ends[:,:2],0.,atol=1e-13)
            else:
                assert_allclose(result.values[:,5],100/33000.,rtol=3e-13,atol=1e-14)

    def test_source_profile_shape_frame_and_uncertainty_refuse(self):
        for p in (profile(self.ref,frame='wrong-frame'),profile(self.ref,halo=1)):
            with self.assertRaisesRegex(TectonicsError,'actual source'):
                PreparedW04Support(self.ref,self.zero,CONTINUOUS,exterior=self.e0,rigidity=p,accuracy=ACCURACY)
        with self.assertRaises(TectonicsError):
            PreparedW04Support(self.ref,self.zero,CONTINUOUS,exterior=self.e0,rigidity=self.profile)
        with PreparedW04Support(self.ref,self.zero,CONTINUOUS,exterior=self.e0,
                rigidity=self.profile,accuracy=ACCURACY) as plan:
            with self.assertRaisesRegex(TectonicsError,'exterior uncertainty'):
                plan.solve(self.ref,self.zero,exterior=exterior(self.ref,bounds=(1.,0.)))

    def test_factors_are_reused_and_budget_is_released(self):
        budget=WorkBudget(32<<20)
        applied=surface(self.ref,pressure=np.linspace(0.,100.,8))
        plan=PreparedW04Support(self.ref,self.zero,CONTINUOUS,exterior=self.e0,
            rigidity=self.profile,accuracy=ACCURACY,budget=budget)
        plan.solve(self.ref,applied,exterior=self.e0)
        retained=budget.reserved_bytes
        self.assertGreater(plan.operator.setup_bytes,0)
        plan.solve(self.ref,applied,exterior=self.e0)
        self.assertEqual(retained,budget.reserved_bytes)
        plan.close();self.assertEqual(budget.reserved_bytes,0)
        with self.assertRaises(TectonicsError): plan.solve(self.ref,applied,exterior=self.e0)


if __name__=='__main__': unittest.main()
