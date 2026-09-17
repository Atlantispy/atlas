"""W02 cohort verification: conserved extensive data, not advected material IDs.

Analytic and rational expectations, native/reference comparisons, lossless state
round trips and pressure/failure checks. No timing thresholds or changed old tests.
"""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import replace
from fractions import Fraction
import copy
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import pickle
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from atlas_tectonics import *
from atlas_tectonics.materials import (material_work_bytes,restore_material_state,
    pack_material_result,unpack_material_result,_hash_array,validate_material_result)
from atlas_tectonics.regional import advect_regional
from atlas_tectonics._validation import frozen
from atlas_tectonics.storage import ArrayStore,StoreLimits,Compression,StoreError
from atlas_tectonics.resources import WorkBudget,MemoryLimitError
from atlas_tectonics.reuse import (cached_material_transport,CachePolicy,ExecutionContext,PreparedInput)
from atlas_tectonics.execution import KernelExecutor,ExecutionPolicy

CASE=json.loads((Path(__file__).resolve().parents[1]/'cases/material_transport.json').read_text())
RTOL=CASE['tests']['relative_tolerance'];ATOL=CASE['tests']['absolute_tolerance']
COHORTS=(MaterialCohort('a','basalt','older-crust',-100.),MaterialCohort('b','basalt','younger-crust',-10.))
CLOSED=MaterialBoundary('closed')


def state(h=None,n=16,time=0.,cohorts=COHORTS):
    if h is None:h=np.vstack((np.ones(n),np.full(n,2.)))
    return MaterialState(RegionalGrid1D(h.shape[1],float(h.shape[1])),cohorts,h,time_s=time,epoch_id='synthetic')


def boundary(a=1.,b=2.,reservoir='outside'):
    return MaterialBoundary('open',{'a':a,'b':b},reservoir)


def step(s=None,u=None,dt=.2,**kw):
    s=state() if s is None else s
    u=np.ones(s.grid.cells+1) if u is None else u
    return advect_materials(s,u,dt,left=kw.pop('left',boundary()),right=kw.pop('right',boundary()),**kw)


def same(test,a,b):
    test.assertEqual(a.state.thickness_m.tobytes(),b.state.thickness_m.tobytes())
    test.assertEqual(a.face_flux_m2_s.tobytes(),b.face_flux_m2_s.tobytes())
    test.assertEqual(a.accounts.tobytes(),b.accounts.tobytes())
    test.assertEqual(a.state.cohorts,b.state.cohorts)


class CohortStateTests(unittest.TestCase):
    def test_required_explicit_ids_and_formation(self):
        for args in (('','rock','o',0),('x',' ','o',0),('x','r','o',True),('x','r','o',np.inf)):
            with self.assertRaises(TectonicsError):MaterialCohort(*args)
        self.assertIsNone(MaterialCohort('x','rock','origin',None).formation_time_s)

    def test_sorted_unique_catalogue(self):
        for cs in (tuple(reversed(COHORTS)),(COHORTS[0],COHORTS[0]),[],()):
            with self.assertRaises(TectonicsError):state(cohorts=cs)

    def test_shape_and_mask_rejection(self):
        for h in (np.ones((3,16)),np.ones(16),np.ma.array(np.ones((2,16))),np.full((2,16),np.nan),np.full((2,16),-1.)):
            with self.assertRaises(TectonicsError):MaterialState(RegionalGrid1D(16,16),COHORTS,h,time_s=0,epoch_id='x')

    def test_future_formation_and_epoch(self):
        with self.assertRaises(TectonicsError):state(cohorts=(COHORTS[0],replace(COHORTS[1],formation_time_s=1)))
        with self.assertRaises(TectonicsError):MaterialState(RegionalGrid1D(1,1),COHORTS,np.ones((2,1)),time_s=0,epoch_id='')

    def test_capture_and_private_array_descriptors(self):
        h=np.ones((2,16));s=state(h);h[:]=55
        a=s.thickness_m;a.shape=(32,);a.dtype='u8'
        self.assertEqual(s.thickness_m.shape,(2,16));assert_array_equal(s.thickness_m,1)
        with self.assertRaises(ValueError):s.thickness_m.setflags(write=True)
        self.assertIsInstance(s._payload,bytes)

    def test_identity_binds_composition_history_time_epoch(self):
        s=state();ids={s.state_id}
        for cs in ((replace(COHORTS[0],origin_id='new'),COHORTS[1]),
                   (replace(COHORTS[0],formation_time_s=-99),COHORTS[1])):
            ids.add(state(cohorts=cs).state_id)
        ids.add(state(np.vstack((np.full(16,2.),np.ones(16)))).state_id)
        ids.add(state(time=1).state_id)
        ids.add(MaterialState(s.grid,s.cohorts,s.thickness_m,time_s=0,epoch_id='different').state_id)
        self.assertEqual(len(ids),6)

    def test_pickle_and_deepcopy_preserve_bytes(self):
        s=state()
        for r in (copy.deepcopy(s),pickle.loads(pickle.dumps(s))):
            self.assertEqual(s.state_id,r.state_id)
            self.assertEqual(s._payload,r._payload)
            with self.assertRaises(ValueError):r.thickness_m.setflags(write=True)

    def test_restore_refuses_changed_metadata(self):
        s=state();d=s.descriptor();d['time_s']=1
        with self.assertRaises(TectonicsError):restore_material_state(d,s.thickness_m,s.state_id)
        d=s.descriptor();d['cohorts'][0]['formation_time_s']=100
        with self.assertRaises(TectonicsError):restore_material_state(d,s.thickness_m,s.state_id)

    def test_known_unknown_age_and_no_per_cell_age_array(self):
        cs=(COHORTS[0],replace(COHORTS[1],formation_time_s=None))
        s=state(cohorts=cs,time=5);self.assertEqual(s.ages_s(),(105.,None))
        self.assertEqual(s.nbytes,2*16*8)

    def test_fractions_empty_mask_and_bounds(self):
        h=np.vstack((np.arange(16.),np.arange(16.)*2));s=state(h)
        f,m=s.fractions();self.assertFalse(m[0]);assert_array_equal(f[:,0],0)
        assert_allclose(f[:,1:].sum(axis=0),1,rtol=RTOL,atol=ATOL)
        self.assertTrue(np.all((f>=0)&(f<=1)))
        with self.assertRaises(ValueError):m.setflags(write=True)

    def test_exact_column_total_against_fraction(self):
        cs=tuple(MaterialCohort(f'{i:02d}','r','o',0) for i in range(4))
        h=np.array([[1e16,1.],[1.,1e-300],[1.,1e-300],[2.,2.]])
        s=state(h,cohorts=cs)
        exact=np.array([float(sum(map(Fraction,h[:,i]),Fraction())) for i in range(2)])
        assert_array_equal(s.total_thickness(),exact)
        assert_array_equal(s.total_thickness(backend='reference'),exact)

    def test_state_budget_before_capture(self):
        h=np.ones((2,100))
        with mock.patch('atlas_tectonics.materials.snapshot',side_effect=AssertionError('copied')):
            with self.assertRaises(MemoryLimitError):state_with=MaterialState(RegionalGrid1D(100,100),COHORTS,h,time_s=0,epoch_id='x',budget=WorkBudget(10))

    def test_zero_inventory_catalogue_retained(self):
        s=state(np.zeros((2,16)));assert_array_equal(s.total_thickness(),0)
        self.assertEqual(len(s.cohorts),2);self.assertEqual(s.ages_s(),(100.,10.))


class MaterialTransportTests(unittest.TestCase):
    def test_accuracy_and_native_are_defaults(self):
        sig=inspect.signature(advect_materials)
        self.assertEqual(sig.parameters['scheme'].default,'muscl')
        self.assertEqual(sig.parameters['backend'].default,'numba')
        r=step();self.assertEqual((r.scheme,r.backend),('muscl','numba'))

    def test_one_cohort_matches_scalar_scheme(self):
        h=2+np.sin(np.arange(32.)*.2);s=state(h[None,:],cohorts=(COHORTS[0],))
        left=MaterialBoundary('open',{'a':3.},'left');right=MaterialBoundary('open',{'a':4.},'right')
        u=np.linspace(-.4,.6,33)
        for scheme in ('upwind','muscl'):
            a=step(s,u,scheme=scheme,left=left,right=right)
            b=advect_regional(h,u,s.grid,.2,left=TransportBoundary('open',3.),right=TransportBoundary('open',4.),scheme=scheme)
            self.assertEqual(a.state.thickness_m[0].tobytes(),b.thickness_m.tobytes())
            self.assertEqual(a.face_flux_m2_s[0].tobytes(),b.face_flux_m2_s.tobytes())

    def test_multi_matches_individual_native_rows(self):
        rng=np.random.default_rng(2507);s=state(rng.uniform(.1,10,(2,31)));u=rng.uniform(-1,1,32)
        for scheme in ('muscl','upwind'):
            result=step(s,u,scheme=scheme)
            for k,c in enumerate(s.cohorts):
                amount=1 if k==0 else 2
                r=advect_regional(s.thickness_m[k],u,s.grid,.2,left=TransportBoundary('open',amount),
                                  right=TransportBoundary('open',amount),scheme=scheme)
                self.assertEqual(result.state.thickness_m[k].tobytes(),r.thickness_m.tobytes())
                self.assertEqual(result.face_flux_m2_s[k].tobytes(),r.face_flux_m2_s.tobytes())

    def test_independent_reference_random_fields(self):
        rng=np.random.default_rng(20)
        for n in (1,2,3,31,64):
            s=state(rng.uniform(0,5,(2,n)));u=rng.uniform(-1,1,n+1)
            for scheme in ('muscl','upwind'):
                a=step(s,u,.1,scheme=scheme);b=step(s,u,.1,scheme=scheme,backend='reference')
                assert_allclose(a.state.thickness_m,b.state.thickness_m,rtol=RTOL,atol=ATOL)
                assert_allclose(a.accounts,b.accounts,rtol=RTOL,atol=ATOL)

    def test_exact_rational_open_upwind(self):
        s=state(np.array([[1.,2.,3.],[2.,4.,6.]]));u=np.array([1.,-.5,.25,-.75]);dt=.25
        r=step(s,u,dt,scheme='upwind')
        for k,h in enumerate(s.thickness_m):
            el=Fraction(k+1);er=Fraction(k+1);old=list(map(Fraction,h));vel=list(map(Fraction,u));d=Fraction(dt)
            flux=[vel[0]*(el if vel[0]>0 else old[0])]
            flux += [vel[j]*(old[j-1] if vel[j]>=0 else old[j]) for j in (1,2)]
            flux += [vel[3]*(er if vel[3]<0 else old[2])]
            expected=[float(old[i]+d*(flux[i]-flux[i+1])) for i in range(3)]
            assert_array_equal(r.state.thickness_m[k],expected)
            self.assertEqual(r.accounts[k,6],float(d*flux[0]));self.assertEqual(r.accounts[k,7],float(-d*flux[-1]))

    def test_interval_mean_flux_reconciles(self):
        rng=np.random.default_rng(81);s=state(rng.uniform(.1,2,(2,64)));u=np.linspace(-.5,.75,65)
        r=step(s,u)
        for k,a in enumerate(r.accounts):
            self.assertEqual(a[6],.2*r.face_flux_m2_s[k,0]);self.assertEqual(a[7],-.2*r.face_flux_m2_s[k,-1])
            self.assertLessEqual(abs(a[4]),128*np.finfo(float).eps*max(a[0],a[1],a[2],a[3]))

    def test_closed_and_stationary_preserve(self):
        s=state(np.arange(32.).reshape(2,16));r=step(s,np.zeros(17),left=CLOSED,right=CLOSED)
        self.assertEqual(s._payload,r.state._payload);assert_array_equal(r.face_flux_m2_s,0)
        self.assertEqual(r.state.ages_s(),(100.2,10.2))

    def test_zero_duration_preserves_inventory_and_time(self):
        s=state();r=step(s,dt=0.)
        self.assertEqual(s._payload,r.state._payload);self.assertEqual(s.time_s,r.state.time_s)
        assert_array_equal(r.accounts[:,2:5],0)

    def test_closed_nonzero_velocity_refused(self):
        with self.assertRaises(TectonicsError):step(left=CLOSED)
        with self.assertRaises(TectonicsError):step(right=CLOSED)

    def test_reversal_requires_supplied_composition(self):
        left=MaterialBoundary('open',None,'outside')
        step(u=-np.ones(17),left=left)
        with self.assertRaises(TectonicsError):step(left=left)

    def test_empty_explicit_inflow_is_zero_not_missing(self):
        b=MaterialBoundary('open',{},'vacuum')
        r=step(left=b);assert_array_equal(r.accounts[:,6],0)
        self.assertTrue(np.all(r.state.thickness_m[:,0]<state().thickness_m[:,0]))

    def test_partial_map_means_known_absent_cohorts(self):
        r=step(left=MaterialBoundary('open',{'a':4.},'left'))
        self.assertEqual(r.accounts[0,6],.8);self.assertEqual(r.accounts[1,6],0.)

    def test_unknown_boundary_cohort_refused_even_outgoing(self):
        with self.assertRaises(TectonicsError):step(right=MaterialBoundary('open',{'unknown':1},'r'))

    def test_boundary_immutable_copy_and_bad_data(self):
        d={'a':1.};b=MaterialBoundary('open',d,'r');d['a']=999
        self.assertEqual(b.exterior,(('a',1.),))
        for args in (('closed',{},None),('open',{},None),('open',(('a',1),('a',2)),'r'),('open',{'a':-1},'r')):
            with self.assertRaises(TectonicsError):MaterialBoundary(*args)

    def test_scheme_courant_never_auto_downgraded(self):
        with self.assertRaises(TectonicsError):step(dt=.75)
        r=step(dt=.75,scheme='upwind');self.assertEqual(r.scheme,'upwind')

    def test_time_overflow_and_unresolvable_step(self):
        with self.assertRaises(TectonicsError):step(state(time=1e30),dt=.2)
        with self.assertRaises(TectonicsError):step(dt=-1)

    def test_expanding_and_contracting_uniform_material(self):
        s=state();u=.05*(np.arange(17)-8)
        r=step(s,u)
        factor=1-.05*.2+(.05*.2)**2/2
        assert_allclose(r.state.thickness_m,s.thickness_m*factor,atol=ATOL,rtol=RTOL)
        b=boundary();r2=step(s,-u,left=b,right=b)
        self.assertTrue(np.all(r2.state.thickness_m[:,1:-1]>s.thickness_m[:,1:-1]))

    def test_thin_sharp_front_nonnegative(self):
        h=np.zeros((2,64));h[0,15:25]=1.;h[1,30:45]=1e-8;s=state(h)
        empty=MaterialBoundary('open',{},'outside')
        for _ in range(20):s=step(s,np.ones(65),.4,left=empty,right=empty).state
        self.assertTrue(np.all(s.thickness_m>=0));self.assertLessEqual(s.thickness_m[0].max(),1+ATOL)
        self.assertEqual(s.ages_s(),(108.,18.))

    def test_native_flags_and_no_auto_precision(self):
        step();from atlas_tectonics._materials_native import advance_cohorts
        self.assertFalse(advance_cohorts.targetoptions['fastmath']);self.assertTrue(advance_cohorts.targetoptions['nogil'])
        self.assertNotIn('parallel',advance_cohorts.targetoptions)
        self.assertEqual(step().state.thickness_m.dtype,np.dtype('f8'))

    def test_missing_native_never_falls_back(self):
        import builtins
        original=builtins.__import__
        def guarded(name,*a,**kw):
            if name.endswith('_materials_native'):raise ImportError('test missing backend')
            return original(name,*a,**kw)
        with mock.patch('builtins.__import__',side_effect=guarded):
            with self.assertRaises(TectonicsError):step()
        step(backend='reference')

    def test_cancellation_before_and_after_native(self):
        token=threading.Event();token.set()
        with self.assertRaises(CancelledError):step(cancel=token)
        token.clear();from atlas_tectonics import _materials_native as native
        old=native.advance_cohorts
        def cancel_after(*a):
            r=old(*a);token.set();return r
        with mock.patch.object(native,'advance_cohorts',side_effect=cancel_after):
            with self.assertRaises(CancelledError):step(cancel=token)

    def test_memory_refusal_before_native_and_release(self):
        b=WorkBudget(100)
        with mock.patch('atlas_tectonics._materials_native.advance_cohorts',side_effect=AssertionError('native')):
            with self.assertRaises(MemoryLimitError):step(budget=b)
        self.assertEqual(b.reserved_bytes,0)
        with self.assertRaises(TectonicsError):step(dt=1,budget=WorkBudget(1<<20))

    def test_output_fields_immutable_and_descriptor_independent(self):
        r=step();a=r.face_flux_m2_s;a.shape=(34,)
        self.assertEqual(r.face_flux_m2_s.shape,(2,17))
        for value in (r.state.thickness_m,r.face_flux_m2_s,r.accounts):
            with self.assertRaises(ValueError):value.setflags(write=True)
        same(self,r,pickle.loads(pickle.dumps(r)))

    def test_pack_roundtrip_and_inconsistent_metrics(self):
        s=state();u=np.ones(17);r=step(s,u);p=pack_material_result(r)
        rr=unpack_material_result(p,s,.2,boundary(),boundary(),'muscl','numba',_hash_array(u))
        self.assertEqual(r.state.state_id,rr.state.state_id);same(self,r,rr)
        bad=p.copy();bad[0,-8]+=1
        with self.assertRaises(TectonicsError):unpack_material_result(bad,s,.2,boundary(),boundary(),'muscl','numba',_hash_array(u))

    def test_total_is_derived_without_fraction_renormalisation(self):
        rng=np.random.default_rng(25);r=step(state(rng.uniform(0,4,(2,16))))
        expected=np.array([math.fsum(r.state.thickness_m[:,i]) for i in range(16)])
        assert_array_equal(r.state.total_thickness(),expected)
        original=r.state._payload;r.state.fractions();self.assertEqual(original,r.state._payload)


class MaterialEventTests(unittest.TestCase):
    def event(self,s,operation='add',cohort=None,**kwargs):
        return MaterialEvent('e1',s.state_id,s.time_s,operation,cohort or s.cohorts[0],'reservoir',**kwargs)

    def test_existing_material_add_keeps_formation(self):
        s=state();r=apply_material_event(s,self.event(s),np.ones(16))
        self.assertEqual(r.transferred_volume_m2,16);self.assertEqual(r.state.ages_s(),s.ages_s())
        assert_array_equal(r.state.thickness_m[0],2);assert_array_equal(s.thickness_m[0],1)

    def test_birth_registers_new_cohort_and_zero_age(self):
        s=state();c=MaterialCohort('c','new-rock','source',0)
        r=apply_material_event(s,self.event(s,'birth',c),np.full(16,3.))
        self.assertEqual(len(r.state.cohorts),3);self.assertEqual(r.state.ages_s(),(100.,10.,0.))
        self.assertEqual(r.transferred_volume_m2,48.);self.assertEqual(r.balance_residual_m2,0.)

    def test_birth_wrong_time_refused(self):
        s=state()
        with self.assertRaises(TectonicsError):self.event(s,'birth')
        with self.assertRaises(TectonicsError):apply_material_event(s,replace(self.event(s),time_s=.1),np.ones(16))

    def test_removal_account_and_history_retained_when_empty(self):
        s=state();r=apply_material_event(s,self.event(s,'remove'),np.ones(16))
        assert_array_equal(r.state.thickness_m[0],0);self.assertEqual(r.state.cohorts,s.cohorts)
        self.assertEqual(r.after_volume_m2,0);self.assertEqual(r.before_volume_m2,16)

    def test_overremoval_refuses_without_mutation(self):
        s=state();before=s._payload
        with self.assertRaises(TectonicsError):apply_material_event(s,self.event(s,'remove'),np.full(16,2.))
        self.assertEqual(s._payload,before)

    def test_event_parent_prevents_double_application_and_retry_is_pure(self):
        s=state();e=self.event(s);a=apply_material_event(s,e,np.ones(16));b=apply_material_event(s,e,np.ones(16))
        self.assertEqual(a.state.state_id,b.state.state_id)
        with self.assertRaises(TectonicsError):apply_material_event(a.state,e,np.ones(16))

    def test_noop_event_still_has_lineage(self):
        s=state();e=self.event(s);r=apply_material_event(s,e,np.zeros(16))
        self.assertNotEqual(s.state_id,r.state.state_id);self.assertEqual(s._payload,r.state._payload)
        with self.assertRaises(TectonicsError):apply_material_event(r.state,e,np.zeros(16))

    def test_cannot_reassign_material_origin_or_birth_time(self):
        s=state();different=replace(COHORTS[0],origin_id='wrong')
        with self.assertRaises(TectonicsError):apply_material_event(s,self.event(s,cohort=different),np.ones(16))
        with self.assertRaises(TectonicsError):register_cohorts(s,(different,))

    def test_register_zero_cohort_no_volume_change(self):
        s=state();r=register_cohorts(s,(MaterialCohort('c','r','o',None),))
        assert_array_equal(r.total_thickness(),s.total_thickness());self.assertIsNone(r.ages_s()[-1])
        self.assertIs(register_cohorts(s,(COHORTS[0],)),s)

    def test_registered_cohort_can_enter_from_boundary(self):
        s=register_cohorts(state(),(MaterialCohort('c','r','o',None),))
        r=step(s,left=MaterialBoundary('open',{'c':1},'left'),right=MaterialBoundary('open',None,'right'))
        self.assertGreater(r.state.thickness_m[2,0],0);self.assertIsNone(r.state.ages_s()[2])

    def test_future_existing_add_and_unknown_removal_refused(self):
        s=state();future=MaterialCohort('c','r','o',1)
        with self.assertRaises(TectonicsError):apply_material_event(s,self.event(s,cohort=future),np.ones(16))
        with self.assertRaises(TectonicsError):apply_material_event(s,self.event(s,'remove',MaterialCohort('c','r','o',0)),np.ones(16))

    def test_transfer_mask_negative_overflow_and_budget(self):
        s=state();e=self.event(s)
        for amounts in (np.ma.array(np.ones(16)),-np.ones(16),np.full(16,np.inf),np.full(16,1e308)):
            with self.assertRaises(TectonicsError):apply_material_event(s,e,amounts)
        with self.assertRaises(MemoryLimitError):apply_material_event(s,e,np.ones(16),budget=WorkBudget(10))

    def test_split_step_birth_then_transport_account(self):
        s=step(dt=.2).state;c=MaterialCohort('c','r','new',s.time_s)
        born=apply_material_event(s,self.event(s,'birth',c),np.full(16,1.)).state
        r=step(born,np.zeros(17),.3,left=CLOSED,right=CLOSED)
        self.assertAlmostEqual(r.state.ages_s()[-1],.3);assert_array_equal(r.state.thickness_m,born.thickness_m)


class MaterialPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'m.db'
        self.limits=StoreLimits(1024,8<<20,16<<20,decoded_cache_bytes=4096)
        self.store=ArrayStore(self.path,self.limits)

    def tearDown(self):self.store.close();self.tmp.cleanup()

    def cached(self,s=None,**kw):
        s=state() if s is None else s
        return cached_material_transport(s,np.ones(s.grid.cells+1),.2,left=kw.pop('left',boundary()),
            right=kw.pop('right',boundary()),store=self.store,cache_policy=CachePolicy(mode='always'),**kw)

    def test_state_save_restore_no_pickle(self):
        s=step().state;save_material_state(s,self.store);r=load_material_state(self.store,s.state_id)
        self.assertEqual(s.state_id,r.state_id);self.assertEqual(s.descriptor(),r.descriptor())
        self.assertEqual(s._payload,r._payload)

    def test_formation_metadata_changes_not_duplicating_payload(self):
        s=state();save_material_state(s,self.store);count=self.store.statistics()['unique_chunks']
        cs=(replace(COHORTS[0],formation_time_s=-101),COHORTS[1]);s2=state(cohorts=cs)
        save_material_state(s2,self.store)
        self.assertEqual(count,self.store.statistics()['unique_chunks'])
        self.assertNotEqual(load_material_state(self.store,s.state_id).ages_s(),load_material_state(self.store,s2.state_id).ages_s())

    def test_cold_independent_backup_restores_history(self):
        s=step().state;save_material_state(s,self.store)
        target=self.store.backup_to(Path(self.tmp.name)/'backup.db');self.store.close();self.path.unlink()
        with ArrayStore(target,self.limits) as other:
            self.assertEqual(load_material_state(other,s.state_id).descriptor(),s.descriptor())

    def test_cached_and_direct_match_and_immutable(self):
        direct=step();a=self.cached();b=self.cached()
        same(self,direct,a);same(self,a,b);self.assertEqual(direct.state.state_id,b.state.state_id)
        self.assertEqual(self.store.statistics()['snapshots'],1)
        with self.assertRaises(ValueError):b.accounts.setflags(write=True)

    def test_same_total_different_cohorts_invalidates(self):
        a=self.cached();b=self.cached(state(np.vstack((np.full(16,2.),np.ones(16)))))
        self.assertEqual(self.store.statistics()['snapshots'],2)
        # Independently limited partial fields need not sum bit-identically to
        # a separately transported total; pre-existing numerical tolerance applies.
        assert_allclose(a.state.total_thickness(),b.state.total_thickness(),rtol=RTOL,atol=ATOL)
        self.assertNotEqual(a.state._payload,b.state._payload)

    def test_changed_formation_epoch_reservoir_invalidates(self):
        self.cached();self.cached(state(cohorts=(replace(COHORTS[0],formation_time_s=-99),COHORTS[1])))
        self.cached(left=boundary(reservoir='other'))
        self.assertEqual(self.store.statistics()['snapshots'],3)

    def test_prepared_input_and_off_policy(self):
        s=state();u=PreparedInput(np.ones(17));a=cached_material_transport(s,u,.2,left=boundary(),right=boundary(),
             store=self.store,cache_policy=CachePolicy(mode='off'))
        same(self,a,step());self.assertEqual(self.store.statistics()['snapshots'],0)

    def test_invalid_boundary_and_budget_cannot_hide_behind_hit(self):
        self.cached()
        with self.assertRaises(TectonicsError):self.cached(left=MaterialBoundary('open',None,'left'))
        with self.assertRaises(MemoryLimitError):self.cached(budget=WorkBudget(10))

    def test_corrupt_payload_refused(self):
        self.cached();db=sqlite3.connect(self.path)
        db.execute('UPDATE chunks SET payload=?',(b'broken',));db.commit();db.close()
        with self.assertRaises(StoreError):self.cached()

    def test_duplicate_requests_safe_same_state(self):
        self.cached() # exclude first compilation and lazy import from coordination
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.cached(),range(4)))
        self.assertEqual(len({r.state.state_id for r in results}),1)
        self.assertEqual(self.store.statistics()['snapshots'],1)

    def test_native_definition_change_invalidates_context(self):
        from atlas_tectonics import _materials_native as native
        ctx=ExecutionContext('numba');ctx.verify()
        original=native.advance_cohorts
        with mock.patch.object(native,'advance_cohorts',lambda *a:None):
            with self.assertRaises(TectonicsError):ctx.verify()
        self.assertIs(native.advance_cohorts,original)

    def test_cache_fresh_process_preserves_one_snapshot(self):
        a=self.cached()
        code='''import numpy as np,sys
from atlas_tectonics import *
from atlas_tectonics.reuse import cached_material_transport,CachePolicy
from atlas_tectonics.storage import ArrayStore,StoreLimits
cs=(MaterialCohort('a','basalt','older-crust',-100.),MaterialCohort('b','basalt','younger-crust',-10.))
s=MaterialState(RegionalGrid1D(16,16.),cs,np.vstack((np.ones(16),np.full(16,2.))),time_s=0.,epoch_id='synthetic')
b=MaterialBoundary('open',{'a':1.,'b':2.},'outside')
with ArrayStore(sys.argv[1],StoreLimits(1024,8<<20,16<<20,4096)) as st:
 r=cached_material_transport(s,np.ones(17),.2,left=b,right=b,store=st,cache_policy=CachePolicy(mode='always'))
 print(st.statistics()['snapshots']);print(r.state.state_id)
'''
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),PYTHONDONTWRITEBYTECODE='1')
        p=subprocess.run([sys.executable,'-B','-c',code,str(self.path)],env=env,text=True,capture_output=True,timeout=45)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),f'1\n{a.state.state_id}')


class MaterialExecutionTests(unittest.TestCase):
    def test_serial_thread_spawn_agree_without_scheme_change(self):
        s=state();expected=step()
        for mode in ('serial','auto','threads','processes'):
            b=WorkBudget(384<<20)
            with KernelExecutor(ExecutionPolicy(mode=mode,max_workers=1,max_inflight=1),budget=b) as ex:
                for r in ex.material_transports([np.ones(17),np.ones(17)],s,.2,left=boundary(),right=boundary()):
                    same(self,r,expected);self.assertEqual(r.scheme,'muscl');self.assertEqual(r.state.state_id,expected.state.state_id)
            self.assertEqual(b.reserved_bytes,0)

    def test_auto_parallel_selection_never_changes_accuracy(self):
        with KernelExecutor() as ex:
            self.assertFalse(ex._parallel(16,'materials','numba'))
            self.assertTrue(ex._parallel(ex.policy.min_parallel_elements,'materials','numba'))
            self.assertFalse(ex._parallel(ex.policy.min_parallel_elements,'materials','reference'))

    def test_executor_refusal_and_early_close(self):
        s=state();b=WorkBudget(1<<20)
        with KernelExecutor(ExecutionPolicy(mode='serial'),budget=b) as ex:
            stream=ex.material_transports([np.ones(17)]*10,s,.2,left=boundary(),right=boundary())
            next(stream);stream.close();self.assertEqual(b.reserved_bytes,0)
        with KernelExecutor(ExecutionPolicy(mode='serial'),budget=WorkBudget(10)) as ex:
            with self.assertRaises(MemoryLimitError):list(ex.material_transports([np.ones(17)],s,.2,left=boundary(),right=boundary()))

    def test_invalid_worker_descriptor_refuses(self):
        s=state();r=step();bad=replace(r,_flux=b'bad')
        with self.assertRaises(TectonicsError):validate_material_result(bad,s,.2)
        with self.assertRaises(TectonicsError):validate_material_result(r,state(time=1),.2)


class MaterialReceiptTests(unittest.TestCase):
    def test_transition_metadata_detached_and_accounted(self):
        s=state();r=step(s);receipt=r.state.transition_record
        self.assertEqual(receipt['parent'],s.state_id)
        self.assertEqual(receipt['left']['reservoir_id'],'outside')
        self.assertEqual(receipt['cohort_accounts_m2']['a']['inflow_m2'],.2)
        receipt['cohort_accounts_m2']['a']['inflow_m2']=999
        self.assertEqual(r.state.transition_record['cohort_accounts_m2']['a']['inflow_m2'],.2)

    def test_restoration_rejects_inconsistent_transition(self):
        r=step();d=r.state.descriptor();d['transition']['duration_s']=99.
        with self.assertRaises(TectonicsError):restore_material_state(d,r.state.thickness_m,r.state.state_id)

    def test_event_receipt_survives_storage(self):
        s=state();e=MaterialEvent('extraction',s.state_id,0.,'remove',s.cohorts[0],'external-reservoir')
        r=apply_material_event(s,e,np.ones(16))
        with tempfile.TemporaryDirectory() as d:
            with ArrayStore(Path(d)/'x.db',StoreLimits(1024,1<<20,4<<20)) as st:
                save_material_state(r.state,st);restored=load_material_state(st,r.state.state_id)
                self.assertEqual(restored.transition_record['event']['event_id'],'extraction')
                self.assertEqual(restored.transition_record['transfer_m2'],16.)
                self.assertEqual(restored.transition_record['after_m2'],0.)

    def test_total_account_does_not_sum_courant(self):
        r=step();a=r.total_account()
        self.assertEqual(a['maximum_outflow_fraction'],.2)
        self.assertAlmostEqual(a['inflow_m2'],.6)
        self.assertEqual(a['solid_volume_per_width_before_m2'],48.)

    def test_incoming_same_material_different_formation_stays_separate(self):
        s=state(np.zeros((2,16)))
        r=step(s,left=boundary(a=1,b=2))
        self.assertEqual(r.state.cohorts[0].material_id,r.state.cohorts[1].material_id)
        self.assertEqual(r.state.ages_s(),(100.2,10.2))
        self.assertGreater(r.state.thickness_m[0,0],0)
        self.assertGreater(r.state.thickness_m[1,0],0)

    def test_parent_kept_after_branching(self):
        s=state();before=s._payload
        a=step(s);b=step(s,u=-np.ones(17))
        self.assertEqual(s._payload,before)
        self.assertEqual(a.state.parent_state_id,b.state.parent_state_id)
        self.assertNotEqual(a.state.transition_id,b.state.transition_id)

    def test_restored_scheme_cannot_disagree_with_receipt(self):
        s=state();r=step(s)
        with self.assertRaises(TectonicsError):validate_material_result(replace(r,scheme='upwind'),s,.2)

    def test_material_timestep_advice_and_zero_speed(self):
        s=state();lim=material_timestep_limit(s,np.ones(17),left=boundary(),right=boundary())
        self.assertLessEqual(lim.maximum_duration_s,.5)
        step(s,dt=lim.maximum_duration_s)
        none=material_timestep_limit(s,np.zeros(17),left=CLOSED,right=CLOSED)
        self.assertIsNone(none.maximum_duration_s)

    def test_timestep_advice_does_not_hide_missing_composition(self):
        with self.assertRaises(TectonicsError):material_timestep_limit(state(),np.ones(17),
            left=MaterialBoundary('open',None,'left'),right=boundary())

    def test_event_overflow_rejects_as_domain_error(self):
        s=state(np.full((2,16),1e308))
        e=MaterialEvent('x',s.state_id,0.,'remove',s.cohorts[0],'external')
        with self.assertRaises(TectonicsError):apply_material_event(s,e,np.zeros(16))

    def test_diagnostic_and_event_reservations_release(self):
        b=WorkBudget(1<<20);s=state()
        s.total_thickness(budget=b);s.fractions(budget=b)
        e=MaterialEvent('x',s.state_id,0.,'add',s.cohorts[0],'external')
        apply_material_event(s,e,np.ones(16),budget=b)
        self.assertEqual(b.reserved_bytes,0)


class MaterialAccuracyTests(unittest.TestCase):
    def test_smooth_cohort_refinement_second_order(self):
        errors=[]
        for n in CASE['tests']['refinement_cells']:
            grid=RegionalGrid1D(n,4.,-2.)
            edges=np.linspace(-2,2,n+1);dx=grid.spacing_m
            def average(x):return 1+.1*(np.sin(2*np.pi*(x+dx/2))-np.sin(2*np.pi*(x-dx/2)))/(2*np.pi*dx)
            x=(edges[:-1]+edges[1:])/2
            h=np.vstack((average(x),2*average(x-.3)))
            s=MaterialState(grid,COHORTS,h,time_s=0,epoch_id='synthetic');t=0.
            stop=CASE['tests']['translation_duration_s']
            while t<stop:
                dt=min(.4*dx,stop-t)
                # The scientific API specifies boundary forcing constant per step.
                # This case has analytic midpoint inflow; measure interior error
                # separated from physical inflow influence. Numerical boundary
                # effects remain included in the observed refinement error.
                left=MaterialBoundary('open',{'a':1+.1*math.cos(2*np.pi*(-2-t-dt/2)),
                                             'b':2+.2*math.cos(2*np.pi*(-2-t-dt/2-.3))},'left')
                s=advect_materials(s,np.ones(n+1),dt,left=left,right=MaterialBoundary('open',None,'right')).state
                t=s.time_s
            expected=np.vstack((average(x-stop),2*average(x-stop-.3)))
            interior=(x>-1.4)&(x<1.4)
            errors.append(float(np.mean(np.abs(s.thickness_m[:,interior]-expected[:,interior]))))
        self.assertGreater(errors[0]/errors[1],CASE['tests']['expected_refinement_ratio_minimum'])
        self.assertGreater(errors[1]/errors[2],CASE['tests']['expected_refinement_ratio_minimum'])


if __name__=='__main__':unittest.main()
