"""Frozen A07 and bounded joined W08 conservation/restart controls."""
from concurrent.futures import CancelledError
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.geometry import PlanarGeometry
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore,Compression,StoreLimits,StoreError
from atlas_tectonics.w08_inventory import W08Inventory
from atlas_tectonics.w08_region import W08Region
from atlas_tectonics.w08_workflow import PreparedW08Workflow,RegimeInterval,W08ExhaustionError


CASE_PATH = Path(__file__).resolve().parents[1]/'cases/w08_joined_r1.json'
CASE_SHA = '01269a9de5e3c94f7adf04f8aed5e970364af5f8af49889bd733e9f97d4395d4'
LIMITS = StoreLimits(65536,8*1024**2,64*1024**2)
NODES = ('a-accretion','b-crust','c-deep','d-export','e-extrusion',
         'f-intrusion','g-mantle','h-melt','i-reservoir','j-solid')
KINDS = ('accretion','crust','deep-storage','export','extrusion','intrusion',
         'mantle','source-melt','reservoir','source-solid')


def open_store(path,budget,cls=ArrayStore):
    return cls(Path(path)/'w08.sqlite',limits=LIMITS,compression=Compression(codec='raw',shuffle='none'),budget=budget)


def fixture_inputs(*,parcels=8,partitions=1,case='joined',budget=None):
    owner = WorkBudget(128*1024**2) if budget is None else budget
    c = np.zeros((10,2)); c[1]=[8,2]; c[6]=[10,10]; c[7]=[7,3]; c[8]=[1,1]; c[9]=[2,3]
    inv = W08Inventory(NODES,KINDS,('A','B'),c,c.sum(axis=1)*10,
        formation_time_s=np.full(10,-1.),origin_ids=tuple('origin-'+n for n in NODES),
        source_id='initial-synthetic-stocks',enthalpy_source='synthetic-enthalpy',budget=owner)
    polygons = tuple(PlanarGeometry.polygon([(10*j/parcels,0),(10*(j+1)/parcels,0),
        (10*(j+1)/parcels,10),(10*j/parcels,10)],frame_id='xy-si',budget=owner) for j in range(parcels))
    ids = tuple('parcel-'+str(j).zfill(3) for j in range(parcels))
    region = W08Region(polygons,ids,(NODES[0],NODES[1],NODES[4],NODES[5],NODES[6]),
        [3,3,3,3,3],np.full((5,parcels),1/parcels),
        ('existing-column','existing-column','extrusive','underplating','existing-column'),
        source_id='synthetic-regional-placement',epoch_id='epoch-si',datum_id='datum-si',
        gravity_m_s2=10,budget=owner)
    retirement = dict(selected_node_ids=[NODES[1],NODES[6]],destination_ids=[NODES[0],NODES[2],NODES[3]],
        parameters=dict(epoch_id='epoch-si',density_kg_m3=[1,1],thickness_m=[3,1],
            material_velocity_m_s=[[1,0,0],[1,0,0]],boundary_velocity_m_s=[[0,0,0],[0,0,0]],
            outward_normal=[1,0,0],strike_direction=[0,1,0],section_width_m=1,
            frame_id='xy-si',section_policy='translation-invariant-along-strike',
            destination_fractions=[[.25,.5,.25],[.25,.5,.25]],flux_source='prescribed-flux',
            partition_source='prescribed-destinations'))
    selected = [NODES[i] for i in (3,4,5,7,8,9)]
    rates = np.zeros((6,6)); rates[3,4]=2; rates[4,1]=rates[4,2]=1
    magmatism = dict(selected_node_ids=selected,rates_kg_s=rates.tolist(),heat_w=None)
    if case=='A07':
        specs = [(1.5,'subduction',None,retirement,None),(3.,'cessation',None,None,None)]
    else:
        specs = [(1.,'shortening',dict(gradient_s=[[math.log(.8),0],[0,0]],velocity_m_s=[0,0],anchor_m=[0,0]),None,None),
            (2.,'transform',dict(gradient_s=[[0,.5],[0,0]],velocity_m_s=[0,0],anchor_m=[0,0]),None,None),
            (3.5,'subduction',None,retirement,None),(4.5,'magmatism',None,None,magmatism),
            (5.5,'cessation',None,None,None)]
    intervals=[];previous=None;start=0.
    for end,regime,motion,retire,magma in specs:
        transition = None if previous is None else dict(event_id='event-'+regime,
            from_regime=previous,to_regime=regime,boundary_id='declared-interface',geometry_policy='continuous',
            polarity='positive-x',coupling_source='prescribed-coupling',kinematics_source='prescribed-motion',
            thermal_source=inv.enthalpy_source)
        for part in range(partitions):
            t = start+(end-start)*(part+1)/partitions
            intervals.append(RegimeInterval(t,regime,'source-'+regime,transition=transition if part==0 else None,
                motion=motion,retirement=retire,magmatism=magma))
        previous,start=regime,end
    return inv,region,tuple(intervals),owner


@contextmanager
def make_workflow_fixture(*,store=None,budget=None,**kwargs):
    inv,region,intervals,owner = fixture_inputs(budget=budget,**kwargs)
    with PreparedW08Workflow(inv,region,intervals,source_id='joined-fixture',store=store,budget=owner) as plan:
        yield plan


def signature(out):
    return dict(output_id=out.output_id,components=out.inventory.component_mass_kg.tolist(),
        enthalpy=out.inventory.enthalpy_j.tolist(),geometry=[g.geometry_id for g in out.polygons],
        deformation=out.deformation_gradient.tolist(),regional_id=out.regional.view_id)


class InterruptingStore(ArrayStore):
    fail=False
    after_commit=False
    def put(self,*args,**kwargs):
        original=kwargs.pop('publication_check',None)
        def check():
            if original is not None: original()
            if self.fail:
                self.fail=False
                raise CancelledError('test before atomic commit')
        result=super().put(*args,publication_check=check,**kwargs)
        if self.after_commit:
            self.after_commit=False
            raise CancelledError('test after commit before adoption')
        return result


def mutate_metadata(store,key,mutate):
    row=store._db.execute('SELECT body,digest FROM snapshots WHERE id=?',(key,)).fetchone()
    manifest=json.loads(row[0]);m=manifest['metadata'];mutate(m)
    encode=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    m['content_id']=hashlib.sha256(encode({k:v for k,v in m.items() if k!='content_id'})).hexdigest()
    body=encode(manifest)
    store._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?',(body,hashlib.sha256(body).hexdigest(),key))


class W08WorkflowTests(unittest.TestCase):
    def test_frozen_fixture_and_A07_cessation(self):
        self.assertEqual(hashlib.sha256(CASE_PATH.read_bytes()).hexdigest(),CASE_SHA)
        with make_workflow_fixture(case='A07') as p:
            out=p.run();m=out.inventory.mass_kg
            np.testing.assert_allclose(m[[0,2,3]],[1.5,3,1.5],rtol=0,atol=1e-13)
            np.testing.assert_array_equal(m[[7,8,9]],[10,2,5])
            self.assertEqual(out.descriptor()['applied_event_ids'],['event-cessation'])

    def test_joined_five_regimes_and_physical_views(self):
        with make_workflow_fixture() as p:
            out=p.run();m=out.inventory.mass_kg
            np.testing.assert_allclose(m[[1,6,7,8,5,4]],[5.5,18.5,8,2,1,1],rtol=0,atol=1e-13)
            np.testing.assert_allclose(out.deformation_gradient,np.broadcast_to([[.8,.5],[0,1]],(8,2,2)),rtol=0,atol=1e-13)
            self.assertAlmostEqual(sum(g.area_m2 for g in out.polygons),80)
            self.assertEqual(out.regional.descriptor()['heat_source_j'],0.)
            self.assertAlmostEqual(sum(out.regional.enthalpy_j.flat),275.)
            self.assertEqual(len(out.descriptor()['transfer_history']),5)
            self.assertEqual(p.statistics()['computed_intervals'],5)
            self.assertIs(p.run(),out)

    def test_partition_and_spatial_invariance(self):
        reference=None
        for n,parts in ((8,1),(16,2),(32,4)):
            with make_workflow_fixture(parcels=n,partitions=parts) as p:
                out=p.run();values=(out.inventory.component_mass_kg,out.inventory.enthalpy_j)
                if reference is None:reference=tuple(a.copy() for a in values)
                for a,b in zip(values,reference):np.testing.assert_allclose(a,b,rtol=1e-13,atol=1e-13)
                self.assertAlmostEqual(sum(g.area_m2 for g in out.polygons),80,places=10)

    def test_exact_restart_no_replayed_transfers(self):
        with TemporaryDirectory() as path:
            owner=WorkBudget(128*1024**2)
            with make_workflow_fixture(budget=owner) as p:expected=signature(p.run())
            with open_store(path,owner) as store:
                with make_workflow_fixture(store=store,budget=owner) as p:p.run(through=2)
                with make_workflow_fixture(store=store,budget=owner) as p:
                    out=p.run();self.assertEqual(signature(out),expected)
                    self.assertEqual(p.statistics()['computed_intervals'],2)
                    self.assertEqual(p.statistics()['restored_outputs'],1)
                    self.assertEqual(signature(p.load(4)),expected)

    def test_atomic_interruption_before_and_after_commit(self):
        for after in (False,True):
            with self.subTest(after_commit=after),TemporaryDirectory() as path:
                owner=WorkBudget(128*1024**2)
                with open_store(path,owner,InterruptingStore) as store:
                    with make_workflow_fixture(store=store,budget=owner) as p:
                        first=p.run(through=1)
                        store.after_commit=after;store.fail=not after
                        with self.assertRaises(CancelledError):p.run(through=2)
                        self.assertEqual(p._current.output_id,first.output_id)
                        out=p.run()
                        np.testing.assert_allclose(out.inventory.mass_kg[[0,2,3]],[1.5,3,1.5],rtol=0,atol=1e-13)

    def test_partial_history_and_mid_event_refusal(self):
        for mode in ('gap','phase','time','owner','cursor'):
            with self.subTest(mode=mode),TemporaryDirectory() as path:
                owner=WorkBudget(128*1024**2)
                with open_store(path,owner) as store:
                    with make_workflow_fixture(store=store,budget=owner) as p:
                        p.run(through=1);key=p.checkpoint_id(1)
                        if mode=='gap':store._db.execute('DELETE FROM snapshots WHERE id=?',(p.checkpoint_id(0),))
                        else:
                            def mutate(m):
                                r=m['receipt']
                                if mode=='phase':r['phase']='mid-event'
                                if mode=='time':r['end_time_s']=1.75
                                if mode=='owner':r['owners']['material']='another-owner'
                                if mode=='cursor':r['applied_event_ids']=[]
                            mutate_metadata(store,key,mutate)
                        with self.assertRaises((TectonicsError,StoreError)):p.load(1)

    def test_corrupt_array_and_explicit_stale_checkpoint(self):
        with TemporaryDirectory() as path:
            owner=WorkBudget(128*1024**2)
            with open_store(path,owner) as store:
                with make_workflow_fixture(store=store,budget=owner) as p:
                    p.run(through=0)
                    with self.assertRaises(TectonicsError):p.load(0,checkpoint_id='0'*64)
                    store._db.execute("UPDATE chunks SET payload=zeroblob(length(payload))")
                    with self.assertRaises((TectonicsError,StoreError)):p.load(0)

    def test_wrong_history_or_unstated_continental_law_refused(self):
        inv,region,history,owner=fixture_inputs()
        with self.assertRaises(TectonicsError):RegimeInterval(1,'continental-entry','no-law')
        d=history[2].descriptor();d['transition']=None
        bad=RegimeInterval(**d)
        with self.assertRaises(TectonicsError):PreparedW08Workflow(inv,region,history[:2]+(bad,)+history[3:],source_id='bad',budget=owner)
        d=history[3].descriptor();d['transition']['event_id']='event-subduction'
        with self.assertRaises(TectonicsError):PreparedW08Workflow(inv,region,history[:3]+(RegimeInterval(**d),)+history[4:],source_id='bad',budget=owner)

    def test_exhaustion_commits_exact_endpoint_and_refuses_continuation(self):
        inv,region,history,owner=fixture_inputs(case='A07')
        d=history[0].descriptor();d['end_time_s']=10.
        with PreparedW08Workflow(inv,region,(RegimeInterval(**d),),source_id='exhaustion',budget=owner) as p:
            with self.assertRaises(W08ExhaustionError) as stopped:p.run()
            self.assertIs(p._current,stopped.exception.output)
            self.assertEqual(p._current.inventory.time_s,10/3)
            self.assertEqual(p._current.inventory.mass_kg[1],0.)
            before=p._current.output_id
            with self.assertRaises(W08ExhaustionError):p.run()
            self.assertEqual(p._current.output_id,before)

    def test_source_drift_and_immutable_history(self):
        with make_workflow_fixture() as p:
            with self.assertRaises(AttributeError):p.initial=None
            with self.assertRaises(TectonicsError):p.run(through=.5)
            original=p._context._sources
            p._context._sources=dict(original,changed=b'changed')
            try:
                with self.assertRaises(TectonicsError):p.run()
            finally:p._context._sources=original


if __name__=='__main__':unittest.main()
