"""Bounded assembled W04 acceptance; synthetic SI cases, not terrain calibration.

Six explicit alternatives share the SAME evolved W03 inputs. This does not
require finite-resolution equality between discrete-periodic and continuum
methods, or pretend distinct physical boundaries describe the same problem.
"""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (FlexureBoundary1D, PreparedW04Support, RegionalGrid1D,
    RigidityProfile1D, VariableFlexureAccuracy, W03ExecutionContext)
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.reuse import CachePolicy
from atlas_tectonics.storage import ArrayStore
from atlas_tectonics.w03_workflow import (advance_w03_columns, save_w03_columns,
    load_w03_columns)
from test_w03_workflow import initialise, workflow_fixture
from test_w04_workflow import surface
from test_w04_regional_workflow import CONTINUOUS, ELASTIC, exterior
from test_w01_regional_forcing import store_limits


SOURCE='synthetic assembled W04 acceptance; not calibrated geology'
ACCURACY=VariableFlexureAccuracy(SOURCE,1e-3,1e-10,1e-10,1e-10)
MODES=('periodic','continuous','mixed-physical')
# The 1e6/2e6 s pilot correctly exceeded the uniform mixed-end 1% strain
# limit (1.201%). Use a shorter thermal interval, not a weakened validity gate.
INTERVAL_S=1e5


def pore_cells(state):
    return np.sum(state.compaction.grain_volume_m3*state.compaction.void_ratio,axis=0)


def thermal_pressure(reference,before,after):
    # Independent integration of W03 depth-cell temperature means, rather than
    # W04's direct mean-deficit-change implementation.
    material=reference.binding.buoyancy_material
    return float((before-after)@np.diff(reference.binding.depth_edges_m))*\
        material.density_kg_m3*material.expansion_per_k*ELASTIC.gravity_m_s2


def options(state,mode,variable,*,thickness_multiplier=1.):
    if mode=='periodic':
        policy=replace(CONTINUOUS,boundary='periodic-repetition',region_boundary=None)
    elif mode=='mixed-physical':
        policy=replace(CONTINUOUS,boundary='physical-edges',
            region_boundary=FlexureBoundary1D('free','clamped',SOURCE))
    else:
        policy=CONTINUOUS
    extra={}
    if variable:
        g=state.material.grid;left,right=(2,1) if mode=='continuous' else (0,0)
        n=g.cells+left+right
        grid=RegionalGrid1D(n,n*g.spacing_m,g.origin_m-left*g.spacing_m)
        te=np.linspace(1.,1.5,n)*thickness_multiplier
        ids=state.source_workflow.initial_samples.descriptor()
        material=lambda t:(ELASTIC.young_modulus_pa,float(t),ELASTIC.poisson_ratio)
        p=RigidityProfile1D(grid,np.full(n,ELASTIC.young_modulus_pa),te,
            np.full(n,ELASTIC.poisson_ratio),source_id=SOURCE,
            frame_id=ids['frame_id'],datum_id=state.binding.depth_reference_id,
            epoch_id=state.binding.epoch_id,
            far_left=material(te[0]) if left else None,
            far_right=material(te[-1]) if right else None)
        extra=dict(rigidity=p,accuracy=ACCURACY)
    return policy,extra


class W04CombinedAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref=initialise(workflow_fixture(cells=8,length_m=8.))
        with W03ExecutionContext() as context:
            cls.middle=advance_w03_columns(cls.ref,time_s=INTERVAL_S,
                top_effective_stress_pa=1e6,context=context)
            cls.later=advance_w03_columns(cls.middle,time_s=2*INTERVAL_S,
                top_effective_stress_pa=0.,context=context)
            temperature=[state.thermal_diagnostics(context=context)['temperature_k']
                         for state in (cls.ref,cls.middle,cls.later)]
        cls.states=(cls.ref,cls.middle,cls.later)
        cls.surfaces=[];cls.exteriors=[];cls.thermal=[];cls.redistribution=[]
        baseline=surface(cls.ref).reservoir_volume_m3
        for index,state in enumerate(cls.states):
            shift=index*.01*np.array([3.,-1.,2.,-2.,-3.,1.,4.,-4.])
            water=baseline+pore_cells(cls.ref)-pore_cells(state)+shift
            pressure=index*np.array([20.,-10.,15.,-5.,30.,0.,-20.,10.])
            cls.surfaces.append(surface(state,water,pressure))
            q=thermal_pressure(cls.ref,temperature[0],temperature[index])
            cls.exteriors.append(exterior(state,q+index*np.array([60.,30.]),
                q+index*np.array([-15.]),far=(q+5*index,q-10*index)))
            cls.thermal.append(q);cls.redistribution.append(shift)

    def exterior_kwargs(self,mode,index):
        return dict(exterior=self.exteriors[index]) if mode=='continuous' else {}

    def test_evolved_load_and_surface_accounts_across_all_six_support_routes(self):
        self.assertLess(float(np.sum(pore_cells(self.middle))),float(np.sum(pore_cells(self.ref))))
        self.assertGreater(float(np.sum(pore_cells(self.later))),float(np.sum(pore_cells(self.middle))))
        area=self.ref.compaction.area_m2
        original=[(s.state_id,s.material.thickness_m.copy(),s.compaction.void_ratio.copy()) for s in self.states]
        for mode in MODES:
            for variable in (False,True):
                with self.subTest(mode=mode,variable=variable):
                    policy,extra=options(self.ref,mode,variable)
                    with PreparedW04Support(self.ref,self.surfaces[0],policy,**extra,
                            **self.exterior_kwargs(mode,0)) as plan:
                        zero=plan.solve(self.ref,self.surfaces[0],**self.exterior_kwargs(mode,0))
                        assert_array_equal(zero.values,np.zeros((8,8)))
                        for index,state in enumerate(self.states[1:],1):
                            result=plan.solve(state,self.surfaces[index],**self.exterior_kwargs(mode,index))
                            expected_inventory=1000.*10.*self.redistribution[index]/area
                            assert_allclose(result.values[:,0],expected_inventory,rtol=0.,atol=2e-8)
                            assert_allclose(result.values[:,1],0.,rtol=0.,atol=1e-12)
                            assert_allclose(result.values[:,2],self.thermal[index],rtol=3e-12,atol=1e-6)
                            assert_array_equal(result.values[:,3],self.surfaces[index].external_downward_pressure_pa)
                            expected=expected_inventory+self.thermal[index]+result.values[:,3]
                            assert_allclose(result.downward_load_pa,expected,rtol=3e-12,atol=1e-6)
                            self.assertAlmostEqual(float(result.values[:,0]@area),0.,delta=1e-7)
                            self.assertAlmostEqual(float(np.sum(self.surfaces[index].reservoir_volume_m3)),
                                state.reservoir_fluid_m3,delta=1e-10)
                            assert_array_equal(state.compaction.grain_volume_m3,self.ref.compaction.grain_volume_m3)
                            bulk=np.sum(state.material.thickness_m-self.ref.material.thickness_m,axis=0)
                            assert_allclose(result.sediment_surface_change_m,bulk-result.values[:,5],rtol=0.,atol=2e-12)
                            assert_allclose(result.reservoir_surface_change_m,
                                self.redistribution[index]/area-result.values[:,5],rtol=0.,atol=2e-12)
                            self.assertEqual(result.descriptor()['thermal_owner'],'flexure')
                            self.assertFalse(result.descriptor()['feedback_applied'])
        for state,(identity,thickness,voids) in zip(self.states,original):
            self.assertEqual(state.state_id,identity)
            assert_array_equal(state.material.thickness_m,thickness)
            assert_array_equal(state.compaction.void_ratio,voids)

    def test_rebased_sequence_is_additive_without_accumulating_previous_totals(self):
        for mode in MODES:
            for variable in (False,True):
                with self.subTest(mode=mode,variable=variable):
                    policy,extra=options(self.ref,mode,variable)
                    with PreparedW04Support(self.ref,self.surfaces[0],policy,**extra,
                            **self.exterior_kwargs(mode,0)) as plan:
                        a=plan.solve(self.middle,self.surfaces[1],**self.exterior_kwargs(mode,1))
                        b=plan.solve(self.later,self.surfaces[2],**self.exterior_kwargs(mode,2))
                        repeat=plan.solve(self.middle,self.surfaces[1],**self.exterior_kwargs(mode,1))
                        self.assertEqual(a.result_id,repeat.result_id)
                    with PreparedW04Support(self.middle,self.surfaces[1],policy,**extra,
                            **self.exterior_kwargs(mode,1)) as plan:
                        interval=plan.solve(self.later,self.surfaces[2],**self.exterior_kwargs(mode,2))
                    assert_allclose(b.values[:,:5],a.values[:,:5]+interval.values[:,:5],rtol=3e-12,atol=1e-6)
                    # Adaptive meshes can differ between the three loads. A
                    # fixed metre tolerance is tested, not bitwise superposition.
                    assert_allclose(b.values[:,5:],a.values[:,5:]+interval.values[:,5:],rtol=0.,atol=1e-7)
                    self.assertEqual(interval.descriptor()['reference_state'],self.middle.state_id)

    def test_saved_evolved_state_continues_and_rebuilds_cached_projection_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            with ArrayStore(Path(directory)/'w04-accept.db',store_limits()) as store:
                for state in (self.ref,self.middle): save_w03_columns(state,store)
                restored_ref=load_w03_columns(store,self.ref.state_id)
                restored_middle=load_w03_columns(store,self.middle.state_id)
                restored_later=advance_w03_columns(restored_middle,time_s=2*INTERVAL_S,top_effective_stress_pa=0.)
                self.assertEqual(restored_later.state_id,self.later.state_id)
                for mode in MODES:
                    for variable in (False,True):
                        with self.subTest(mode=mode,variable=variable):
                            policy,extra=options(self.ref,mode,variable)
                            cache=dict(store=store,cache_policy=CachePolicy(mode='always'))
                            with PreparedW04Support(self.ref,self.surfaces[0],policy,**extra,
                                    **self.exterior_kwargs(mode,0)) as plan:
                                expected=plan.solve(self.later,self.surfaces[2],**cache,**self.exterior_kwargs(mode,2))
                                again=plan.solve(self.later,self.surfaces[2],**cache,**self.exterior_kwargs(mode,2))
                                self.assertEqual(again.result_id,expected.result_id)
                                self.assertGreaterEqual(plan._controller.statistics()['hits'],2)
                            old=surface(restored_ref,self.surfaces[0].reservoir_volume_m3,
                                self.surfaces[0].external_downward_pressure_pa)
                            now=surface(restored_later,self.surfaces[2].reservoir_volume_m3,
                                self.surfaces[2].external_downward_pressure_pa)
                            _,recreated=options(restored_ref,mode,variable)
                            with PreparedW04Support(restored_ref,old,policy,**recreated,
                                    **self.exterior_kwargs(mode,0)) as plan:
                                actual=plan.solve(restored_later,now,**cache,**self.exterior_kwargs(mode,2))
                                self.assertGreaterEqual(plan._controller.statistics()['hits'],2)
                            assert_array_equal(actual.values,expected.values)
                            self.assertEqual(actual.result_id,expected.result_id)

    def test_cached_variable_support_rechecks_local_thickness_and_mesh_margin_strain(self):
        policy,extra=options(self.ref,'continuous',True,thickness_multiplier=2.)
        budget=WorkBudget(32<<20)
        with tempfile.TemporaryDirectory() as directory:
            with ArrayStore(Path(directory)/'strain.db',store_limits()) as store:
                cache=dict(store=store,cache_policy=CachePolicy(mode='always'))
                with PreparedW04Support(self.ref,self.surfaces[0],policy,**extra,
                        exterior=self.exteriors[0],budget=budget) as plan:
                    result=plan.solve(self.middle,self.surfaces[1],exterior=self.exteriors[1],**cache)
                    old,now=self.exteriors[:2]
                    packed=np.r_[now.left_pressure_pa-old.left_pressure_pa,result.downward_load_pa,
                        now.right_pressure_pa-old.right_pressure_pa,
                        now.far_left_pa-old.far_left_pa,now.far_right_pa-old.far_right_pa]
                    response=plan.operator.solve(packed)[2:10]
                    local_te=extra['rigidity'].elastic_thickness_m[2:10]
                    strain=response[:,3,2]*local_te/2
                    guarded=float(np.max(strain+response[:,4,2]*local_te/2))
                    unguarded=float(np.max(strain))
                    wrong_te=float(np.max((response[:,3,2]+response[:,4,2])*policy.elastic.elastic_thickness_m/2))
                self.assertGreater(unguarded,wrong_te)
                self.assertGreater(guarded,unguarded)
                count=store.statistics()['snapshots']
                for threshold in ((guarded+wrong_te)/2,(guarded+unguarded)/2):
                    with PreparedW04Support(self.ref,self.surfaces[0],
                            replace(policy,max_bending_strain=threshold),**extra,
                            exterior=self.exteriors[0],budget=budget) as plan:
                        with self.assertRaisesRegex(TectonicsError,'validity envelope'):
                            plan.solve(self.middle,self.surfaces[1],exterior=self.exteriors[1],**cache)
                        self.assertGreaterEqual(plan._controller.statistics()['hits'],2)
                self.assertEqual(store.statistics()['snapshots'],count)
        self.assertEqual(budget.reserved_bytes,0)


if __name__=='__main__': unittest.main()
