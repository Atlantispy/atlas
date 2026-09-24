"""Independent W02 remap, moving-volume, ownership and history verification.

Synthetic regional 1D cases only. Conservation is not arbitrary reversibility
under coarsening; mesh motion is not automatically geological material motion.
"""
from concurrent.futures import CancelledError
from dataclasses import replace
from fractions import Fraction
import copy, json, math, pickle, tempfile, threading, unittest
from pathlib import Path
from unittest import mock
import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from atlas_tectonics import TectonicsError
from atlas_tectonics.regional import RegionalGrid1D
from atlas_tectonics.materials import (MaterialCohort,MaterialState,MaterialBoundary,MaterialEvent,
    apply_material_event,save_material_state,load_material_state,advect_materials)
from atlas_tectonics.mesh import ColumnGrid1D
from atlas_tectonics.remapping import (RemapPlan,remap_materials,advect_ale,ale_timestep_limit,
    to_column_state,_inventories,restore_ale_result,_GEOMETRY_RTOL)
from atlas_tectonics.topology import (PlateRecord,BlockRecord,BoundaryRecord,PlateTopology1D,
    TectonicState1D,split_block,merge_blocks,reassign_blocks,change_boundary,move_partition,
    advance_plate_state,regrid_plate_state,apply_plate_material_event,save_tectonic_state,load_tectonic_state)
from atlas_tectonics.markers import MaterialMarkers1D,move_material_markers
from atlas_tectonics.storage import ArrayStore,StoreLimits,StoreError
from atlas_tectonics.resources import WorkBudget,MemoryLimitError
from atlas_tectonics.reuse import cached_material_remap,cached_ale_transport,CachePolicy,ExecutionContext
from atlas_tectonics.execution import KernelExecutor,ExecutionPolicy

CLOSED=MaterialBoundary('closed')
COHORTS=(MaterialCohort('a','basalt','origin-a',0.),MaterialCohort('b','basalt','origin-b',None))
def grid(n=16):return ColumnGrid1D(np.linspace(0.,1.,n+1),frame_id='test-frame')
def state(n=16,values=None):
    return MaterialState(grid(n),COHORTS,np.vstack([np.ones(n),np.full(n,.5)]) if values is None else values,
                         time_s=1.,epoch_id='test-epoch')
def ext(a=1.,b=.5):return MaterialBoundary('open',{'a':a,'b':b},'outside')
def inv(s):return _inventories(s.thickness_m,s.grid,'reference')
def close(a,b):assert_allclose(a,b,rtol=1e-12,atol=1e-12)
def topology(cuts=(0.,.5,1.)):
    return PlateTopology1D(ColumnGrid1D(cuts,frame_id='test-frame'),(PlateRecord('p'),PlateRecord('q')),
        (BlockRecord('left','p'),BlockRecord('right','q')),(BoundaryRecord('middle','rift'),))
def world(n=16):return TectonicState1D(state(n),topology())
def limits():return StoreLimits(1024,8<<20,32<<20,decoded_cache_bytes=4096)

class MeshRemapTests(unittest.TestCase):
    def test_bad_geometry(self):
        for x in ([0],[0,0],[1,0],[0,np.inf],[0,np.nan],np.ma.array([0,1]),[1e20,math.nextafter(1e20,math.inf)]):
            with self.subTest(x=str(x)),self.assertRaises(TectonicsError):ColumnGrid1D(x,frame_id='test')
    def test_frame_and_geometry_identity(self):
        self.assertNotEqual(grid().grid_id,ColumnGrid1D(grid().edges_m,frame_id='other').grid_id)
        self.assertNotEqual(grid().grid_id,grid(17).grid_id)
    def test_mesh_immutable_restore(self):
        g=grid();r=pickle.loads(pickle.dumps(g));self.assertEqual(g,r)
        for x in (g,r,copy.deepcopy(g)):
            with self.assertRaises(ValueError):x.edges_m.setflags(write=True)
    def test_mesh_state_restore(self):
        s=state();r=pickle.loads(pickle.dumps(s));self.assertEqual(s.state_id,r.state_id)
        self.assertEqual(r.ages_s(),(1.,None))
        with self.assertRaises(ValueError):r.thickness_m.setflags(write=True)
    def test_uniform_bridge(self):
        old=MaterialState(RegionalGrid1D(7,10.,2.),COHORTS,np.ones((2,7)),time_s=1,epoch_id='e')
        r=to_column_state(old,frame_id='f');close(inv(r),[10,10]);self.assertEqual(r.parent_state_id,old.state_id)
    def test_fixed_api_refuses_nonuniform(self):
        with self.assertRaisesRegex(TectonicsError,'advect_ale'):advect_materials(state(),np.zeros(17),0,left=CLOSED,right=CLOSED)
    def test_identity_remap(self):
        s=state();self.assertIs(remap_materials(s,s.grid),s)
    def test_uniform_refine_coarsen(self):
        s=state();g=ColumnGrid1D(np.linspace(0,1,39)**1.3,frame_id='test-frame')
        f=remap_materials(s,g);r=remap_materials(f,grid(5))
        close(f.thickness_m,np.repeat([[1.],[.5]],38,axis=1));close(inv(r),inv(s))
    def test_affine_reconstruction_exact(self):
        g=ColumnGrid1D([0,.125,.25,.5,.75,1],frame_id='test-frame')
        s=MaterialState(g,(COHORTS[0],),(2+3*g.centres_m)[None,:],time_s=1,epoch_id='e')
        t=ColumnGrid1D([0,.0625,.1875,.375,.625,.875,1],frame_id='test-frame')
        r=remap_materials(s,t);close(r.thickness_m[0],2+3*t.centres_m);close(inv(s),inv(r))
    def test_affine_remap_is_independent_of_absolute_coordinate_origin(self):
        for origin in (0.,1e16,-1e16):
            g=ColumnGrid1D(origin+np.array([0.,6.,12.,18.]),frame_id='test-frame')
            t=ColumnGrid1D(origin+np.array([0.,4.,8.,12.,18.]),frame_id='test-frame')
            s=MaterialState(g,(COHORTS[0],),[[13.,19.,25.]],time_s=1,epoch_id='e')
            for backend in ('reference','numba'):
                with self.subTest(origin=origin,backend=backend):
                    r=remap_materials(s,t,backend=backend)
                    assert_array_equal(r.thickness_m,[[12.,16.,20.,25.]])
                    close(inv(s),inv(r))
    def test_constant_remap_fraction_reference(self):
        g=ColumnGrid1D([0,.25,.75,1],frame_id='test-frame')
        s=MaterialState(g,(COHORTS[0],),[[1,3,2]],time_s=1,epoch_id='e')
        r=remap_materials(s,ColumnGrid1D([0,.5,1],frame_id='test-frame'),scheme='constant')
        expected=[(Fraction(1,4)+3*Fraction(1,4))/Fraction(1,2),(3*Fraction(1,4)+2*Fraction(1,4))/Fraction(1,2)]
        assert_array_equal(r.thickness_m,[[float(x) for x in expected]])
    def test_affine_remap_across_binary_exponent_boundary(self):
        # Test endpoint and interior slopes using exact local cell averages,
        # not rounded absolute centres or a second implementation as the oracle.
        for local,target in (([0,3,8],[0,2,4,8]),
                             ([0,3,8,14,20],[0,2,4,8,12,16,20])):
            x=np.array(local,dtype=float);y=np.array(target,dtype=float)
            h=10+x[:-1]+.5*np.diff(x);expected=10+y[:-1]+.5*np.diff(y)
            g=ColumnGrid1D((2**53-6)+x,frame_id='test-frame')
            t=ColumnGrid1D((2**53-6)+y,frame_id='test-frame')
            s=MaterialState(g,(COHORTS[0],),h[None,:],time_s=1,epoch_id='e')
            for backend in ('reference','numba'):
                with self.subTest(cells=len(h),backend=backend):
                    r=remap_materials(s,t,backend=backend)
                    assert_array_equal(r.thickness_m[0],expected);close(inv(s),inv(r))
    def test_sharp_front_nonnegative_and_conserved(self):
        h=np.zeros((2,64));h[0,:23]=2;h[1,23:]=3;s=state(64,h)
        r=remap_materials(s,ColumnGrid1D(np.linspace(0,1,91)**1.1,frame_id='test-frame'))
        self.assertGreaterEqual(float(r.thickness_m.min()),0);close(inv(s),inv(r));self.assertEqual(r.cohorts,s.cohorts)
    def test_native_reference(self):
        rng=np.random.default_rng(312)
        for n in (1,2,7,31):
            s=state(n,rng.uniform(.1,4,(2,n)))
            for scheme in ('linear','constant'):
                close(remap_materials(s,grid(n*2+1),scheme=scheme).thickness_m,
                      remap_materials(s,grid(n*2+1),scheme=scheme,backend='reference').thickness_m)
    def test_coarsening_not_falsely_reversible(self):
        s=state(4,[[0,2,0,2],[1,0,1,0.]])
        r=remap_materials(remap_materials(s,grid(1)),s.grid)
        close(inv(s),inv(r));self.assertFalse(np.array_equal(s.thickness_m,r.thickness_m))
    def test_stale_plan_or_domain_refused(self):
        s=state();p=RemapPlan(s.grid,grid(8))
        with self.assertRaises(TectonicsError):remap_materials(s,grid(9),plan=p)
        for t in (ColumnGrid1D([0,2],frame_id='test-frame'),ColumnGrid1D([0,1],frame_id='other')):
            with self.assertRaises(TectonicsError):RemapPlan(s.grid,t)
    def test_sparse_plan_restore(self):
        p=RemapPlan(grid(128),grid(257));self.assertLessEqual(len(p.arrays()[1]),384);self.assertLess(p.nbytes,40*385)
        r=pickle.loads(pickle.dumps(p));self.assertEqual(r.plan_id,p.plan_id)
        for a in r.arrays():
            with self.assertRaises(ValueError):a.setflags(write=True)
    def test_memory_cancel(self):
        s=state();b=WorkBudget(16)
        with self.assertRaises(MemoryLimitError):remap_materials(s,grid(30),budget=b)
        self.assertEqual(b.reserved_bytes,0);e=threading.Event();e.set()
        with self.assertRaises(CancelledError):remap_materials(s,grid(30),cancel=e)
    def test_smooth_refinement(self):
        errors=[]
        for n in (32,64,128):
            x=np.linspace(0,1,n+1);h=2+(np.cos(2*np.pi*x[:-1])-np.cos(2*np.pi*x[1:]))/(2*np.pi*np.diff(x))
            s=state(n,np.vstack([h,h*.5]));y=np.linspace(0,1,2*n+2)
            r=remap_materials(s,ColumnGrid1D(y,frame_id='test-frame'))
            exact=2+(np.cos(2*np.pi*y[:-1])-np.cos(2*np.pi*y[1:]))/(2*np.pi*np.diff(y))
            errors.append(np.sum(abs(r.thickness_m[0]-exact)*np.diff(y)))
        self.assertGreater(errors[0]/errors[1],3);self.assertGreater(errors[1]/errors[2],3)
    def test_material_event_weighted_nonuniform(self):
        s=MaterialState(ColumnGrid1D([0,.1,.8,1],frame_id='test-frame'),COHORTS,np.ones((2,3)),time_s=1,epoch_id='e')
        e=MaterialEvent('remove',s.state_id,1,'remove',COHORTS[0],'mantle')
        r=apply_material_event(s,e,[.5,0,0]);self.assertAlmostEqual(r.transferred_volume_m2,.05);close(inv(r.state),[.95,1])

class MovingVolumeTests(unittest.TestCase):
    def test_geometry_tolerance_matches_existing_case(self):
        case=json.loads((Path(__file__).parents[1]/'cases'/'w02_completion.json').read_text())
        self.assertEqual(_GEOMETRY_RTOL,case['verification']['relative_tolerance'])
    def test_materially_rounded_mesh_motion_refused(self):
        g=ColumnGrid1D([1e16,1e16+8],frame_id='test-frame')
        s=MaterialState(g,(COHORTS[0],),[[1.]],time_s=1,epoch_id='e')
        for u,w,left,right in (([0.,0.],[0.,6.],CLOSED,MaterialBoundary('open',{'a':1.},'outside')),
                               ([6.,6.],[6.,6.],CLOSED,CLOSED)):
            # Expansion breaks GCL; rounded rigid translation breaks the path
            # even though its cell widths and material inventory are unchanged.
            for backend in ('reference','numba'):
                for scheme in ('upwind','muscl'):
                    with self.subTest(w=w,backend=backend,scheme=scheme):
                        with self.assertRaisesRegex(TectonicsError,'represented mesh motion'):
                            advect_ale(s,u,w,.5,left=left,right=right,scheme=scheme,backend=backend)
        assert_array_equal(s.thickness_m,[[1.]])
    def test_fine_mesh_small_motion_preserves_uniform_field(self):
        # The established 8192-cell workload must not be rejected merely because
        # displacement-relative rounding exceeds the inventory roundoff factor.
        s=state(8192);w=.02*np.sin(np.pi*s.grid.edges_m);w[-1]=0.
        r=advect_ale(s,np.zeros(8193),w,2/8192,left=CLOSED,right=CLOSED)
        close(r.state.thickness_m,s.thickness_m);close(inv(s),inv(r.state))
    def test_zero_and_exact_large_origin_motion(self):
        g=ColumnGrid1D([1e16,1e16+8],frame_id='test-frame')
        s=MaterialState(g,(COHORTS[0],),[[1.]],time_s=1,epoch_id='e')
        for dt in (0.,1.):
            r=advect_ale(s,[4.,4.],[4.,4.],dt,left=CLOSED,right=CLOSED)
            assert_array_equal(r.state.grid.edges_m,g.edges_m+4*dt)
            assert_array_equal(r.state.thickness_m,s.thickness_m)
    def test_restore_cannot_bypass_mesh_precision_guard(self):
        g=ColumnGrid1D([1e16,1e16+8],frame_id='test-frame')
        s=MaterialState(g,(COHORTS[0],),[[1.]],time_s=1,epoch_id='e')
        # Historical invalid one-cell result: Q=11, width=12, right influx=3.
        packed=np.array([[11/12,0.,-6.,8.,11.,3.,0.,0.,.375,0.,3.]])
        for backend in ('reference','numba'):
            with self.subTest(backend=backend),self.assertRaisesRegex(TectonicsError,'represented mesh motion'):
                restore_ale_result(s,np.zeros(2),np.array([0.,6.]),.5,CLOSED,
                    MaterialBoundary('open',{'a':1.},'outside'),'muscl',backend,packed)
    def test_ale_reconstruction_across_binary_exponent_boundary(self):
        results=[]
        for origin in (0.,float(2**53-6)):
            g=ColumnGrid1D(origin+np.array([0.,3.,8.,14.,20.]),frame_id='test-frame')
            s=MaterialState(g,(COHORTS[0],),[[11.5,15.5,21.,27.]],time_s=1,epoch_id='e')
            for backend in ('reference','numba'):
                r=advect_ale(s,[0.,.1,.1,.1,0.],np.zeros(5),.5,
                    left=CLOSED,right=CLOSED,backend=backend)
                results.append(r.state.thickness_m);close(inv(s),inv(r.state))
        for actual in results[1:]:close(actual,results[0])
    def test_increasing_clock_cannot_mislabel_ale_interval(self):
        g=ColumnGrid1D([0.,1.,2.],frame_id='test-frame')
        s=MaterialState(g,(COHORTS[0],),[[1.,0.]],time_s=1e16,epoch_id='e')
        for backend in ('reference','numba'):
            with self.subTest(backend=backend),self.assertRaisesRegex(TectonicsError,'represented clock interval'):
                advect_ale(s,[0.,.1,0.],[0.,0.,0.],3.,left=CLOSED,right=CLOSED,
                           scheme='upwind',backend=backend)
        assert_array_equal(s.thickness_m,[[1.,0.]])
    def test_ale_reconstruction_is_independent_of_absolute_coordinate_origin(self):
        results=[]
        for origin in (0.,1e16,-1e16):
            g=ColumnGrid1D(origin+np.array([0.,6.,12.,18.]),frame_id='test-frame')
            s=MaterialState(g,(COHORTS[0],),[[13.,19.,25.]],time_s=1,epoch_id='e')
            for backend in ('reference','numba'):
                with self.subTest(origin=origin,backend=backend):
                    r=advect_ale(s,[0.,.1,.1,0.],[0.,0.,0.,0.],.5,
                                 left=CLOSED,right=CLOSED,backend=backend)
                    results.append(r.state.thickness_m)
                    close(inv(s),inv(r.state))
        for result in results[1:]:close(result,results[0])
    def test_lagrangian_translation(self):
        s=state();u=np.full(17,.3);r=advect_ale(s,u,u,.25,left=CLOSED,right=CLOSED)
        close(r.state.grid.edges_m,s.grid.edges_m+.075);close(r.state.thickness_m,s.thickness_m);close(r.accounts[:,2:4],0)
    def test_lagrangian_extension(self):
        s=state();u=.2*s.grid.edges_m;r=advect_ale(s,u,u,.25,left=CLOSED,right=CLOSED)
        close(r.state.thickness_m,s.thickness_m/1.05);close(inv(r.state),inv(s))
    def test_lagrangian_compression(self):
        s=state();u=-.2*s.grid.edges_m;r=advect_ale(s,u,u,.25,left=CLOSED,right=CLOSED)
        close(r.state.thickness_m,s.thickness_m/.95);close(inv(r.state),inv(s))
    def test_uniform_mesh_expansion_GCL(self):
        s=state();r=advect_ale(s,np.zeros(17),.2*s.grid.edges_m,.05,left=CLOSED,right=ext())
        close(r.state.thickness_m,s.thickness_m);close(r.accounts[:,6],0);close(r.accounts[:,7],[.01,.005])
    def test_mesh_through_stationary_material(self):
        s=state();r=advect_ale(s,np.zeros(17),np.full(17,.1),.1,left=ext(),right=ext())
        close(r.state.thickness_m,s.thickness_m);close(r.accounts[:,6],[-.01,-.005]);close(r.accounts[:,7],[.01,.005])
    def test_closed_is_relative(self):
        with self.assertRaises(TectonicsError):advect_ale(state(),np.zeros(17),np.ones(17),.001,left=CLOSED,right=CLOSED)
    def test_relative_inflow_requires_composition(self):
        missing=MaterialBoundary('open',None,'outside')
        with self.assertRaises(TectonicsError):advect_ale(state(),np.zeros(17),np.ones(17),.01,left=missing,right=missing)
    def test_mesh_crossing_refused(self):
        s=state();w=-2*s.grid.edges_m
        with self.assertRaises(TectonicsError):advect_ale(s,w,w,1,left=CLOSED,right=CLOSED)
    def test_event_interval_guard(self):
        s=state();z=np.zeros(17)
        with self.assertRaises(TectonicsError):advect_ale(s,z,z,.5,left=CLOSED,right=CLOSED,event_times_s=(1.2,))
        r=advect_ale(s,z,z,.2,left=CLOSED,right=CLOSED,event_times_s=(1.2,));self.assertEqual(r.state.time_s,1.2)
    def test_timestep_advice(self):
        s=state();u=np.ones(17);w=-.1*s.grid.edges_m;dt=ale_timestep_limit(s,u,w,left=ext(),right=ext())
        r=advect_ale(s,u,w,dt,left=ext(),right=ext());self.assertLessEqual(float(r.accounts[:,5].max()),.5)
        with self.assertRaises(TectonicsError):advect_ale(s,u,w,2*dt,left=ext(),right=ext())
    def test_crossing_limit_even_no_relative_flow(self):
        s=state();w=-2*s.grid.edges_m;dt=ale_timestep_limit(s,w,w,left=CLOSED,right=CLOSED)
        self.assertLess(dt,.5);self.assertGreater(dt,0)
        self.assertIsNone(ale_timestep_limit(s,np.zeros(17),np.zeros(17),left=CLOSED,right=CLOSED))
    def test_native_reference_irregular(self):
        g=ColumnGrid1D(np.linspace(0,1,20)**1.1,frame_id='test-frame')
        s=MaterialState(g,COHORTS,np.vstack([2+np.sin(3*g.centres_m),np.ones(19)]),time_s=1,epoch_id='e')
        u=np.full(20,.1);w=.02*np.sin(np.pi*g.edges_m);w[-1]=0.
        for scheme in ('muscl','upwind'):
            a=advect_ale(s,u,w,.005,left=ext(2,1),right=ext(),scheme=scheme)
            b=advect_ale(s,u,w,.005,left=ext(2,1),right=ext(),scheme=scheme,backend='reference')
            close(a.state.thickness_m,b.state.thickness_m);close(a.accounts,b.accounts)
    def test_fraction_upwind_fixed_mesh(self):
        s=state(4,[[1,2,3,4],[2,4,6,8]])
        r=advect_ale(s,np.ones(5),np.zeros(5),.125,left=ext(0,0),right=ext(),scheme='upwind')
        assert_array_equal(r.state.thickness_m,[[.5,1.5,2.5,3.5],[1,3,5,7]]);close(r.accounts[:,3],[.5,1])
    def test_ages_not_reset(self):
        s=state();r=advect_ale(s,np.zeros(17),np.zeros(17),.25,left=CLOSED,right=CLOSED)
        self.assertEqual(r.state.ages_s(),(1.25,None));self.assertEqual(r.state.cohorts,s.cohorts)
    def test_sharp_front(self):
        h=np.zeros((2,64));h[0,20:30]=1;h[1,40:50]=2;s=state(64,h)
        r=advect_ale(s,np.full(65,.1),np.zeros(65),.02,left=ext(0,0),right=ext(0,0))
        self.assertGreaterEqual(float(r.state.thickness_m.min()),0);close(inv(s),inv(r.state))
    def test_uniform_extension_time_convergence(self):
        errors=[]
        for dt in (.04,.02,.01):
            s=state(4);u=.5*s.grid.edges_m;z=np.zeros(5)
            for _ in range(round(.2/dt)):s=advect_ale(s,u,z,dt,left=CLOSED,right=ext()).state
            errors.append(abs(s.thickness_m[0,0]-math.exp(-.1)))
        self.assertGreater(errors[0]/errors[1],3.8);self.assertGreater(errors[1]/errors[2],3.8)
    def test_mask_memory_cancel(self):
        s=state();z=np.zeros(17);b=WorkBudget(10)
        with self.assertRaises(MemoryLimitError):advect_ale(s,z,z,.1,left=CLOSED,right=CLOSED,budget=b)
        self.assertEqual(b.reserved_bytes,0)
        with self.assertRaises(TectonicsError):advect_ale(s,np.ma.array(z),z,.1,left=CLOSED,right=CLOSED)
        e=threading.Event();e.set()
        with self.assertRaises(CancelledError):advect_ale(s,z,z,.1,left=CLOSED,right=CLOSED,cancel=e)

class TopologyTests(unittest.TestCase):
    def test_owner_endpoint_conventions(self):
        t=topology();self.assertEqual(t.owner_at([0,.499,.5,1]),('p','p','q','q'))
        with self.assertRaises(TectonicsError):t.owner_at([1.1])
    def test_bad_partition(self):
        t=topology()
        with self.assertRaises(TectonicsError):replace(t,boundaries=())
        with self.assertRaises(TectonicsError):replace(t,blocks=(t.blocks[0],t.blocks[0]))
        with self.assertRaises(TectonicsError):topology((0,.5,.5))
    def test_polarity_same_plate(self):
        with self.assertRaises(TectonicsError):BoundaryRecord('s','subduction')
        with self.assertRaises(TectonicsError):replace(topology(),blocks=(BlockRecord('a','p'),BlockRecord('b','p')),
            boundaries=(BoundaryRecord('s','subduction',True,'left'),))
    def test_split_preserves_material(self):
        w=world();r=split_block(w,'left',.25,BlockRecord('l1','p',('left',)),BlockRecord('l2','p',('left',)),BoundaryRecord('new'),
            event_id='split',expected_parent_id=w.model_id)
        self.assertIs(r.material,w.material);self.assertIn('left',r.topology.retired_block_ids);self.assertEqual(len(r.topology.blocks),3)
    def test_new_plate_lineage(self):
        w=world();r=split_block(w,'left',.25,BlockRecord('l1','p',('left',)),BlockRecord('l2','child',('left',)),BoundaryRecord('ridge','ridge'),
            new_plates=(PlateRecord('child',('p',)),),event_id='new',expected_parent_id=w.model_id)
        self.assertEqual(r.topology.owner_at([.1,.4]),('p','child'));close(inv(r.material),inv(w.material))
    def test_split_bad_lineage_cut(self):
        w=world()
        with self.assertRaises(TectonicsError):split_block(w,'left',.25,BlockRecord('a','p'),BlockRecord('b','p'),BoundaryRecord('x'),event_id='s',expected_parent_id=w.model_id)
        with self.assertRaises(TectonicsError):split_block(w,'left',.75,BlockRecord('a','p',('left',)),BlockRecord('b','p',('left',)),BoundaryRecord('x'),event_id='s',expected_parent_id=w.model_id)
    def test_merge_retains_ids(self):
        w=world();r=merge_blocks(w,('left','right'),BlockRecord('merged','p',('left','right')),event_id='merge',expected_parent_id=w.model_id)
        self.assertEqual(r.topology.retired_boundary_ids,('middle',));self.assertEqual(r.topology.retired_block_ids,('left','right'))
        self.assertEqual(tuple(p.plate_id for p in r.topology.plates),('p','q'));close(inv(w.material),inv(r.material))
    def test_merge_requires_adjacency(self):
        w=world()
        for ids,b in ((('right','left'),BlockRecord('z','p',('right','left'))),(('left','right'),BlockRecord('left','p'))):
            with self.assertRaises(TectonicsError):merge_blocks(w,ids,b,event_id='m',expected_parent_id=w.model_id)
    def test_membership_not_age(self):
        w=world();r=reassign_blocks(w,{'left':'q'},event_id='assign',expected_parent_id=w.model_id)
        self.assertEqual(r.topology.owner_at([.2]),('q',));self.assertEqual(r.material.state_id,w.material.state_id)
        entry=next(t for t in r.receipt['ownership_transfers'] if t['from_plate']=='p');close(entry['volume_m2'],[.5,.25])
    def test_lineage_redefinition_or_cycles_refused(self):
        w=world()
        with self.assertRaises(TectonicsError):reassign_blocks(w,{'left':'p'},event_id='x',expected_parent_id=w.model_id,new_plates=(PlateRecord('p',('q',)),))
        with self.assertRaises(TectonicsError):replace(topology(),plates=(PlateRecord('p',('q',)),PlateRecord('q',('p',))))
    def test_activity_and_reactivation(self):
        w=world();r=change_boundary(w,BoundaryRecord('middle','rift',False),event_id='off',expected_parent_id=w.model_id)
        a=change_boundary(r,BoundaryRecord('middle','subduction',True,'right'),event_id='on',expected_parent_id=r.model_id)
        self.assertTrue(a.topology.boundaries[0].active);self.assertEqual(a.material.state_id,w.material.state_id)
    def test_parent_and_replay(self):
        w=world();r=change_boundary(w,BoundaryRecord('middle','rift',False),event_id='off',expected_parent_id=w.model_id)
        with self.assertRaises(TectonicsError):change_boundary(r,BoundaryRecord('middle','rift'),event_id='off',expected_parent_id=r.model_id)
        with self.assertRaises(TectonicsError):change_boundary(r,BoundaryRecord('middle','rift'),event_id='x',expected_parent_id=w.model_id)
    def test_cut_reclassification_has_transfer_account(self):
        w=world();r=move_partition(w,[0,.75,1],event_id='move',expected_parent_id=w.model_id)
        self.assertEqual(r.material.state_id,w.material.state_id)
        e=next(t for t in r.receipt['ownership_transfers'] if t['from_plate']=='q' and t['to_plate']=='p');close(e['volume_m2'],[.25,.125])
    def test_coverage_deletion_refused(self):
        w=world()
        with self.assertRaises(TectonicsError):move_partition(w,[.1,.6,1],event_id='delete',expected_parent_id=w.model_id)
    def test_physical_boundary_fluxes_shared(self):
        w=world();x=w.material.grid.edges_m
        r=advance_plate_state(w,np.full(17,.1),.01*x,.05,left=ext(),right=ext(),event_id='step',expected_parent_id=w.model_id)
        close(r.topology.cuts.edges_m,[0,.50025,1.0005]);close(r.material.thickness_m,w.material.thickness_m)
        accounts=r.receipt['block_accounts']
        for a,b in zip(accounts[0]['cohorts'],accounts[1]['cohorts']):self.assertEqual(a['right_exchange_m2'],-b['left_exchange_m2'])
    def test_explicit_mesh_alignment(self):
        w=TectonicState1D(state(),topology((0,.43,1)))
        with self.assertRaises(TectonicsError):advance_plate_state(w,np.zeros(17),np.zeros(17),.1,left=CLOSED,right=CLOSED,event_id='s',expected_parent_id=w.model_id)
        target=ColumnGrid1D(np.union1d(w.material.grid.edges_m,w.topology.cuts.edges_m),frame_id='test-frame')
        r=regrid_plate_state(w,target,event_id='align',expected_parent_id=w.model_id);z=np.zeros(target.cells+1)
        out=advance_plate_state(r,z,z,.1,left=CLOSED,right=CLOSED,event_id='s',expected_parent_id=r.model_id)
        close(inv(out.material),inv(w.material));self.assertEqual(out.topology.topology_id,w.topology.topology_id)
    def test_accounted_birth_and_recycling(self):
        w=world();new=MaterialCohort('new','basalt','ridge',1.)
        ev=MaterialEvent('birth',w.material.state_id,1.,'birth',new,'mantle-source')
        r=apply_plate_material_event(w,ev,np.full(16,.1),expected_parent_id=w.model_id)
        self.assertEqual(r.topology.topology_id,w.topology.topology_id);close(inv(r.material),[1,.5,.1])
        ev=MaterialEvent('sink',r.material.state_id,1.,'remove',new,'mantle-sink')
        out=apply_plate_material_event(r,ev,np.full(16,.1),expected_parent_id=r.model_id);close(inv(out.material),[1,.5,0])
    def test_topology_budget_cancel(self):
        w=world();b=WorkBudget(32)
        with self.assertRaises(MemoryLimitError):move_partition(w,[0,.7,1],event_id='x',expected_parent_id=w.model_id,budget=b)
        self.assertEqual(b.reserved_bytes,0);e=threading.Event();e.set()
        with self.assertRaises(CancelledError):move_partition(w,[0,.7,1],event_id='x',expected_parent_id=w.model_id,cancel=e)
    def test_receipt_views_and_restore(self):
        w=world();r=move_partition(w,[0,.7,1],event_id='x',expected_parent_id=w.model_id)
        d=r.receipt;d['operation']='wrong';self.assertNotEqual(r.receipt['operation'],'wrong')
        self.assertEqual(pickle.loads(pickle.dumps(r)).model_id,r.model_id)

class MarkerTests(unittest.TestCase):
    def test_marker_clock_uses_material_interval_validation(self):
        m=MaterialMarkers1D(('a',),('c',),[.5],time_s=1e16,epoch_id='e',frame_id='test-frame')
        g=grid(1)
        with self.assertRaisesRegex(TectonicsError,'represented clock interval'):
            move_material_markers(m,g,g,3.)
        with self.assertRaisesRegex(TectonicsError,'unresolvable'):
            move_material_markers(m,g,g,1.)
        self.assertEqual(move_material_markers(m,g,g,4.).time_s-m.time_s,4.)
        self.assertEqual(move_material_markers(m,g,g,0.).marker_state_id,m.marker_state_id)
    def test_affine_map_inverse_and_ids(self):
        g=grid(8);t=ColumnGrid1D(2*g.edges_m+3,frame_id='test-frame')
        m=MaterialMarkers1D(('x','y','z'),('a','b','a'),[0,.25,1],time_s=1,epoch_id='e',frame_id='test-frame')
        r=move_material_markers(m,g,t,1);close(r.positions_m,[3,3.5,5]);close(r.log_stretch,math.log(2));self.assertEqual(r.marker_ids,m.marker_ids)
        b=move_material_markers(r,t,g,1);close(b.positions_m,m.positions_m);close(b.log_stretch,0)
    def test_nonuniform_mapping(self):
        a=ColumnGrid1D([0,.5,1],frame_id='f');b=ColumnGrid1D([0,.25,1],frame_id='f')
        m=MaterialMarkers1D(('a','b'),('c','c'),[.25,.75],time_s=0,epoch_id='e',frame_id='f')
        r=move_material_markers(m,a,b,1);close(r.positions_m,[.125,.625]);close(r.log_stretch,np.log([.5,1.5]))
    def test_outside_or_noncorresponding_refused(self):
        m=MaterialMarkers1D(('a',),('c',),[2],time_s=1,epoch_id='e',frame_id='test-frame')
        with self.assertRaises(TectonicsError):move_material_markers(m,grid(8),grid(8),1)
        with self.assertRaises(TectonicsError):move_material_markers(m,grid(8),grid(9),1)
    def test_marker_immutability_ids(self):
        m=MaterialMarkers1D(('a',),('c',),[.5],time_s=1,epoch_id='e',frame_id='test-frame')
        with self.assertRaises(ValueError):m.positions_m.setflags(write=True)
        with self.assertRaises(TectonicsError):MaterialMarkers1D(('a','a'),('c','c'),[.5,.6],time_s=1,epoch_id='e',frame_id='f')

class PersistenceAndExecutionTests(unittest.TestCase):
    def test_material_mesh_store(self):
        s=remap_materials(state(),grid(23))
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'s.db',limits()) as store:
            save_material_state(s,store);r=load_material_state(store,s.state_id);self.assertEqual(r.state_id,s.state_id)
            with self.assertRaises(ValueError):r.thickness_m.setflags(write=True)
    def test_model_cold_backup(self):
        w=world();r=move_partition(w,[0,.75,1],event_id='m',expected_parent_id=w.model_id)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'s.db'
            with ArrayStore(path,limits()) as store:
                save_tectonic_state(w,store);count=store.statistics()['unique_chunks'];save_tectonic_state(r,store)
                self.assertEqual(store.statistics()['unique_chunks'],count+1);store.backup_to(Path(tmp)/'b.db')
            path.unlink()
            with ArrayStore(Path(tmp)/'b.db',limits()) as store:
                out=load_tectonic_state(store,r.model_id);self.assertEqual(r.model_id,out.model_id);self.assertEqual(r.receipt,out.receipt)
    def test_missing_chunk_refused(self):
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'s.db',limits()) as store:
            w=world();save_tectonic_state(w,store);store._db.execute('DELETE FROM chunks WHERE id=(SELECT id FROM chunks LIMIT 1)')
            with self.assertRaises(StoreError):load_tectonic_state(store,w.model_id)
    def test_remap_cache_history_invalidation(self):
        s=state();t=grid(29);always=CachePolicy(mode='always')
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'s.db',limits()) as store:
            a=cached_material_remap(s,t,store=store,cache_policy=always);b=cached_material_remap(s,t,store=store,cache_policy=always)
            self.assertEqual(a.state_id,b.state_id);self.assertEqual(store.statistics()['snapshots'],1)
            other=MaterialState(s.grid,(replace(COHORTS[0],origin_id='different'),COHORTS[1]),s.thickness_m,time_s=1,epoch_id=s.epoch_id)
            cached_material_remap(other,t,store=store,cache_policy=always);self.assertEqual(store.statistics()['snapshots'],2)
    def test_ale_cache_motion_and_events(self):
        s=state();u=np.full(17,.1);w=np.zeros(17);always=CachePolicy(mode='always')
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'s.db',limits()) as store:
            a=cached_ale_transport(s,u,w,.01,left=ext(),right=ext(),store=store,cache_policy=always)
            b=cached_ale_transport(s,u,w,.01,left=ext(),right=ext(),store=store,cache_policy=always)
            self.assertEqual(a.state.state_id,b.state.state_id);self.assertEqual(store.statistics()['snapshots'],1)
            cached_ale_transport(s,u,np.full(17,.01),.01,left=ext(),right=ext(),store=store,cache_policy=always)
            self.assertEqual(store.statistics()['snapshots'],2)
            with self.assertRaises(TectonicsError):cached_ale_transport(s,u,w,.01,left=ext(),right=ext(),event_times_s=(1.005,),store=store,cache_policy=always)
    def test_source_inventory_covers_new_methods(self):
        import atlas_tectonics.remapping as mod
        ctx=ExecutionContext('numba')
        with mock.patch.object(mod,'_inventories',lambda *a:None):
            with self.assertRaises(TectonicsError):ctx.verify()
        ctx.verify()
    def test_ale_execution_modes(self):
        s=state(8);requests=[(np.full(9,.1),np.zeros(9)),(np.full(9,.2),np.zeros(9))]
        expected=[advect_ale(s,u,w,.01,left=ext(),right=ext()) for u,w in requests]
        for mode in ('serial','threads','processes'):
            with self.subTest(mode=mode),KernelExecutor(ExecutionPolicy(mode=mode,max_workers=2,max_inflight=2)) as executor:
                actual=list(executor.ale_transports(requests,s,.01,left=ext(),right=ext()))
                self.assertEqual([r.state.state_id for r in actual],[r.state.state_id for r in expected])
            self.assertEqual(executor.statistics()['reserved_bytes'],0)
    def test_remap_execution_modes(self):
        s=state(8);targets=[grid(13),grid(17)];expected=[remap_materials(s,g) for g in targets]
        for mode in ('serial','threads','processes'):
            with self.subTest(mode=mode),KernelExecutor(ExecutionPolicy(mode=mode,max_workers=2,max_inflight=2)) as executor:
                actual=list(executor.material_remaps([g.edges_m for g in targets],s))
                self.assertEqual([r.state_id for r in actual],[r.state_id for r in expected])
    def test_executor_refuses_downgrade(self):
        with KernelExecutor() as executor:
            with self.assertRaises(TectonicsError):executor.ale_transports([],state(),.1,left=CLOSED,right=CLOSED,scheme='auto')
    def test_cache_cancel_no_commit(self):
        e=threading.Event();e.set()
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'s.db',limits()) as store:
            with self.assertRaises(CancelledError):cached_material_remap(state(),grid(19),store=store,cache_policy=CachePolicy(mode='always'),cancel=e)
            self.assertEqual(store.statistics()['snapshots'],0)


class IntegratedW02Tests(unittest.TestCase):
    def test_event_sequence_regrid_motion_birth_split_merge_restore(self):
        w=world();initial=inv(w.material)
        w=split_block(w,'left',.25,BlockRecord('l1','p',('left',)),BlockRecord('l2','p',('left',)),
            BoundaryRecord('new-cut'),event_id='split',expected_parent_id=w.model_id)
        w=regrid_plate_state(w,grid(32),event_id='refine',expected_parent_id=w.model_id)
        velocity=.1*w.material.grid.edges_m
        w=advance_plate_state(w,velocity,velocity,.1,left=CLOSED,right=CLOSED,event_id='stretch',expected_parent_id=w.model_id)
        close(inv(w.material),initial)
        born=MaterialCohort('new','basalt','prescribed-ridge',w.material.time_s)
        birth=MaterialEvent('birth',w.material.state_id,w.material.time_s,'birth',born,'mantle')
        w=apply_plate_material_event(w,birth,np.full(32,.1),expected_parent_id=w.model_id)
        added=inv(w.material)[-1]
        w=merge_blocks(w,('l1','l2'),BlockRecord('joined','p',('l1','l2')),event_id='merge',expected_parent_id=w.model_id)
        close(inv(w.material),[initial[0],initial[1],added])
        self.assertEqual(w.material.ages_s(),(1.1,None,0.))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'w.db'
            with ArrayStore(path,limits()) as store:save_tectonic_state(w,store)
            with ArrayStore(path,limits()) as store:
                restored=load_tectonic_state(store,w.model_id)
                self.assertEqual(restored.model_id,w.model_id);self.assertEqual(restored.applied_event_ids,('split','refine','stretch','birth','merge'))
                v=.1*restored.material.grid.edges_m
                a=advance_plate_state(restored,v,v,.1,left=CLOSED,right=CLOSED,event_id='continue',expected_parent_id=restored.model_id)
                b=advance_plate_state(w,v,v,.1,left=CLOSED,right=CLOSED,event_id='continue',expected_parent_id=w.model_id)
                self.assertEqual(a.model_id,b.model_id)
    def test_lagrangian_reversal_recovers_material_and_geometry(self):
        s=state(16,np.vstack([2+np.sin(grid().centres_m),np.ones(16)]));x=s.grid.edges_m
        u=.1*np.sin(2*np.pi*x);u[[0,8,-1]]=0  # exact stationary sine nodes
        first=advect_ale(s,u,u,.2,left=CLOSED,right=CLOSED).state
        second=advect_ale(first,-u,-u,.2,left=CLOSED,right=CLOSED).state
        close(second.grid.edges_m,x);close(second.thickness_m,s.thickness_m);close(inv(second),inv(s))
        self.assertEqual(second.ages_s(),(1.4,None))
    def test_random_valid_moving_cases_conserve_each_cohort(self):
        rng=np.random.default_rng(4731)
        for trial in range(12):
            x=np.r_[0,np.cumsum(rng.uniform(.5,1.5,24))];x=x/x[-1]
            g=ColumnGrid1D(x,frame_id='test-frame');h=rng.uniform(.01,5,(2,24))
            s=MaterialState(g,COHORTS,h,time_s=1,epoch_id='test-epoch')
            u=rng.uniform(-.05,.05,25);w=rng.uniform(-.02,.02,25)
            dt=.2*ale_timestep_limit(s,u,w,left=ext(),right=ext())
            a=advect_ale(s,u,w,dt,left=ext(),right=ext());b=advect_ale(s,u,w,dt,left=ext(),right=ext(),backend='reference')
            close(a.state.thickness_m,b.state.thickness_m)
            close(a.accounts[:,1],a.accounts[:,0]+a.accounts[:,2]-a.accounts[:,3])
            self.assertTrue(np.all(a.state.thickness_m>=0))
    def test_marker_snapshot(self):
        from atlas_tectonics.markers import save_material_markers,load_material_markers
        m=MaterialMarkers1D(('a','b'),('origin-a','origin-b'),[.2,.8],time_s=1,epoch_id='e',frame_id='test-frame')
        m=move_material_markers(m,grid(),ColumnGrid1D(grid().edges_m*1.1,frame_id='test-frame'),1)
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'m.db',limits()) as store:
            save_material_markers(m,store);r=load_material_markers(store,m.marker_state_id)
            self.assertEqual(r.marker_state_id,m.marker_state_id);close(r.log_stretch,m.log_stretch)
    def test_new_kernels_strict_compiler_and_readonly_restore(self):
        from atlas_tectonics import _mesh_native as native
        for f in (native.remap_rows,native.advance_ale,native.inventories,native.mapped_points):
            self.assertFalse(f.targetoptions['fastmath']);self.assertTrue(f.targetoptions['nogil'])
            self.assertNotIn('parallel',f.targetoptions)
        r=pickle.loads(pickle.dumps(topology()))
        self.assertEqual(r.topology_id,topology().topology_id)
    def test_restored_remap_wrong_inventory_refused(self):
        from atlas_tectonics.remapping import restore_remap_result
        s=state();t=grid(19);p=RemapPlan(s.grid,t)
        with self.assertRaises(TectonicsError):restore_remap_result(s,t,np.ones((2,19))*100,plan=p,scheme='linear',backend='numba')
    def test_bounded_allocation_during_combined_sequence(self):
        budget=WorkBudget(8<<20);s=state(256)
        r=remap_materials(s,grid(511),budget=budget)
        u=np.full(512,.1);w=np.zeros(512)
        # Keep this allocation test inside the existing clock-resolution
        # contract: 1 + .001 does not represent .001 within 128eps.
        out=advect_ale(r,u,w,1/1024,left=ext(),right=ext(),budget=budget)
        self.assertLess(budget.peak_reserved_bytes,budget.max_bytes);self.assertEqual(budget.reserved_bytes,0)
        with tempfile.TemporaryDirectory() as tmp,ArrayStore(Path(tmp)/'x.db',limits(),budget=WorkBudget(64<<20)) as store:
            save_material_state(out.state,store);restored=load_material_state(store,out.state.state_id)
            self.assertEqual(out.state.state_id,restored.state_id)

class JointMeshReconstructionTests(unittest.TestCase):
    """Composition changes must not fabricate a change in the total field."""
    def source(self, values=None, edges=(0.,1.,2.,3.)):
        cohorts=COHORTS+(MaterialCohort('c','granite','origin-c',0.),)
        h=np.array([[.2,.4,.4],[.4,.3,.4],[.4,.3,.2]]) if values is None else np.asarray(values)
        return MaterialState(ColumnGrid1D(edges,frame_id='test-frame'),cohorts,h,time_s=0.,epoch_id='e')

    def aggregate(self,s):
        total=np.array([math.fsum(s.thickness_m[:,i]) for i in range(s.grid.cells)])
        return MaterialState(s.grid,(COHORTS[0],),total[None,:],time_s=s.time_s,epoch_id=s.epoch_id)

    def test_three_cohort_refinement_preserves_constant_total(self):
        s=self.source();target=ColumnGrid1D([0.,1.,1.5,2.,3.],frame_id='test-frame')
        for backend in ('reference','numba'):
            r=remap_materials(s,target,backend=backend)
            # Independent exact total; old separate slopes gave 1.025 and .975.
            assert_allclose(np.sum(r.thickness_m,axis=0),1.,rtol=0,atol=2e-15)
            close(inv(r),inv(s));self.assertGreaterEqual(float(r.thickness_m.min()),0.)
            self.assertEqual(r.transition_record['operation'],'conservative-remap-v2')

    def test_nonuniform_variable_total_matches_scalar_remap(self):
        s=self.source([[.1,.9,.4,.05],[.7,.01,.6,.3],[.2,.4,.01,.8]],edges=[0.,.25,.75,1.5,3.])
        target=ColumnGrid1D([0.,.1,.4,.9,1.2,2.,3.],frame_id='test-frame')
        results=[]
        for backend in ('reference','numba'):
            result=remap_materials(s,target,backend=backend)
            scalar=remap_materials(self.aggregate(s),target,backend=backend)
            close(np.sum(result.thickness_m,axis=0),scalar.thickness_m[0])
            close(inv(result),inv(s));results.append(result.thickness_m)
            self.assertGreaterEqual(float(result.thickness_m.min()),0.)
        close(*results)

    def test_joint_traces_follow_scalar_for_each_geometry_and_stage(self):
        from atlas_tectonics.remapping import _joint_slopes_reference,_slopes_reference,_ale_reference
        from atlas_tectonics._mesh_native import joint_slopes
        h=self.source().thickness_m;x=np.array([0.,1.,2.,3.]);y=np.array([0.,1.05,1.98,3.])
        # Independent first-stage finite-volume balance from reconstructed traces.
        slopes=_joint_slopes_reference(h,x,True);a=np.array([0.,-.5,.2,0.]);dt=.1
        lower=h-.5*np.diff(x)*slopes;upper=h+.5*np.diff(x)*slopes
        flux=np.zeros((3,4));flux[:,1:-1]=a[1:-1]*np.where(a[1:-1]>=0,upper[:,:-1],lower[:,1:])
        stage=(h*np.diff(x)+dt*(flux[:,:-1]-flux[:,1:]))/np.diff(y)
        for fields,edges in ((h,x),(stage,y)):
            total=np.array([math.fsum(fields[:,i]) for i in range(3)])
            expected=_slopes_reference(total,edges,True)
            for actual in (_joint_slopes_reference(fields,edges,True),joint_slopes(fields,edges,True)):
                close(np.sum(actual,axis=0),expected)
                self.assertTrue(np.all(fields-.5*np.diff(edges)*actual>=0))
                self.assertTrue(np.all(fields+.5*np.diff(edges)*actual>=0))

    def test_stationary_and_deforming_mesh_preserve_constant_total(self):
        s=self.source();open_left=MaterialBoundary('open',{'a':.2,'b':.4,'c':.4},'outside')
        cases=((np.ones(4),np.zeros(4),open_left,MaterialBoundary('open',None,'outside')),
               (np.zeros(4),np.array([0.,.1,-.05,0.]),CLOSED,CLOSED))
        for u,w,left,right in cases:
            for backend in ('reference','numba'):
                result=advect_ale(s,u,w,.125,left=left,right=right,backend=backend)
                assert_allclose(np.sum(result.state.thickness_m,axis=0),1.,rtol=0,atol=3e-15)
                close(inv(result.state)-inv(s),result.accounts[:,6]+result.accounts[:,7])
                self.assertEqual(result.numerical_method,'ale-cohort-ssprk2-v2-muscl-'+backend)

    def test_variable_total_ale_matches_scalar_and_each_cohort_account(self):
        s=self.source([[.1,.9,.4,.05],[.7,.01,.6,.3],[.2,.4,.01,.8]],edges=[0.,.25,.75,1.5,3.])
        u=np.array([.2,.12,-.08,.15,.2]);w=np.array([0.,.02,-.01,.03,0.])
        incoming=MaterialBoundary('open',{'a':.3,'b':.2,'c':.5},'outside')
        total_in=MaterialBoundary('open',{'a':1.},'outside');outgoing=MaterialBoundary('open',None,'outside')
        results=[]
        for backend in ('reference','numba'):
            result=advect_ale(s,u,w,.125,left=incoming,right=outgoing,backend=backend)
            scalar=advect_ale(self.aggregate(s),u,w,.125,left=total_in,right=outgoing,backend=backend)
            close(np.sum(result.state.thickness_m,axis=0),scalar.state.thickness_m[0])
            close(np.sum(result.face_flux_m2_s,axis=0),scalar.face_flux_m2_s[0])
            close(inv(result.state)-inv(s),result.accounts[:,6]+result.accounts[:,7])
            self.assertGreaterEqual(float(result.state.thickness_m.min()),0.)
            results.append(result.state.thickness_m)
        close(*results)

    def test_joint_smooth_remap_second_order(self):
        def means(x):
            dx=np.diff(x)
            sine=(np.cos(2*np.pi*x[:-1])-np.cos(2*np.pi*x[1:]))/(2*np.pi*dx)
            cosine=(np.sin(2*np.pi*x[1:])-np.sin(2*np.pi*x[:-1]))/(2*np.pi*dx)
            a=.2+.1*sine;b=.3+.1*cosine
            return np.vstack((a,b,1.-a-b))
        for backend in ('reference','numba'):
            errors=[]
            for n in (32,64,128):
                x=np.linspace(0.,1.,n+1);y=np.linspace(0.,1.,2*n+1)**1.2
                s=self.source(means(x),x)
                result=remap_materials(s,ColumnGrid1D(y,frame_id='test-frame'),backend=backend)
                errors.append(float(np.sum(abs(result.thickness_m-means(y))*np.diff(y))))
                close(np.sum(result.thickness_m,axis=0),np.ones(2*n));close(inv(result),inv(s))
            self.assertGreater(errors[0]/errors[1],3.)
            self.assertGreater(errors[1]/errors[2],3.)

    def test_explicit_first_order_routes_retain_rational_result(self):
        s=self.source();target=ColumnGrid1D([0.,.5,1.,2.,3.],frame_id='test-frame')
        for backend in ('reference','numba'):
            mapped=remap_materials(s,target,scheme='constant',backend=backend)
            assert_array_equal(mapped.thickness_m,s.thickness_m[:,[0,0,1,2]])
            left=MaterialBoundary('open',{'a':.2,'b':.4,'c':.4},'outside')
            result=advect_ale(s,np.ones(4),np.zeros(4),.25,left=left,
                              right=MaterialBoundary('open',None,'outside'),scheme='upwind',backend=backend)
            expected=np.array([[.2,.35,.4],[.4,.325,.375],[.4,.325,.225]])
            close(result.state.thickness_m,expected);close(inv(result.state)-inv(s),result.accounts[:,6]+result.accounts[:,7])

    def test_added_joint_work_is_admitted_and_code_constants_are_bound(self):
        from atlas_tectonics import remapping as module
        from atlas_tectonics import _mesh_native as native
        s=self.source();target=ColumnGrid1D([0.,1.,1.5,2.,3.],frame_id='test-frame')
        c,n=3,3;nt=4
        for backend in ('reference','numba'):
            old_remap=48*c*(n+nt)+224*(n+nt)+8192*c+16384
            old_ale=96*c*n+256*n+16384*c+16384
            for budget,call in ((WorkBudget(old_remap),lambda b:remap_materials(s,target,backend=backend,budget=b)),
                    (WorkBudget(old_ale),lambda b:advect_ale(s,np.zeros(4),np.zeros(4),.125,
                        left=CLOSED,right=CLOSED,backend=backend,budget=b))):
                with self.assertRaises(MemoryLimitError):call(budget)
                self.assertEqual(budget.reserved_bytes,0)
        for obj,name in ((module,'_joint_slopes_reference'),(module,'_ALE_METHOD'),
                         (native,'joint_slopes'),(native,'_cohort_flux')):
            with ExecutionContext('numba') as context:
                with mock.patch.object(obj,name,object()):
                    with self.assertRaises(TectonicsError):context.verify()


class AdditionalContractTests(unittest.TestCase):
    def test_result_names_ale_not_fixed_grid(self):
        s=state();a=advect_ale(s,np.zeros(17),np.zeros(17),0,left=CLOSED,right=CLOSED)
        self.assertEqual(a.numerical_method,'ale-cohort-ssprk2-v2-muscl-numba')
    def test_overflow_motion_and_advice_refuse(self):
        s=state();u=np.full(17,1e308);w=-u
        for call in (lambda:advect_ale(s,u,w,1,left=ext(),right=ext()),
                     lambda:ale_timestep_limit(s,u,w,left=ext(),right=ext())):
            with self.assertRaises(TectonicsError):call()
    def test_stage_average_flux_in_world_account(self):
        model=world();u=np.full(17,.03);w=np.zeros(17)
        moved=advance_plate_state(model,u,w,.1,left=ext(2,1),right=ext(),event_id='advection',expected_parent_id=model.model_id)
        rows=moved.receipt['block_accounts']
        self.assertEqual(rows[0]['cohorts'][0]['right_exchange_m2'],-rows[1]['cohorts'][0]['left_exchange_m2'])

if __name__=='__main__':unittest.main()
