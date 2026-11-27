"""R2 execution/index tests, with unchanged analytical/reference expectations.

No timings are acceptance gates. Small synthetic geometries exercise broad-phase
conservatism; old exact overlap checks and serial sampling remain explicit oracles.
"""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import json
import math
import subprocess
import sys
import threading
import tempfile
from pathlib import Path
import unittest

import numpy as np
import shapely

from atlas_tectonics import (
    PreparedPrecursor, PrecursorExecutionPolicy, PrecursorSamplingLimits,
    InitialSamplingCell, SphericalFrame, SphericalChart, SphericalGeometry,
    GeometryLimits, GeologyError, InitialScalarField,
    ThermalInitialProfile, FeatureGeometry, GeologicalProvince, SurfaceSelector,
    FeaturePrecedence, save_initial_samples, load_initial_samples,
)
import atlas_tectonics.integration.parallel.execution as execution
from atlas_tectonics.integration.parallel.execution import ExecutionPolicy, KernelExecutor, _AdmittedCall
from atlas_tectonics.integration.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.codecs.storage import ArrayStore, StoreLimits
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.planet._spherical_candidates import SphericalCandidateIndex, spherical_cap
from atlas_tectonics.crust.precursor_sampling import _check_cell_overlaps, _check_cell_overlaps_reference
from tests.fixtures.precursor_fixtures import state, case, mixed_case, cell, rectangle, REQUEST, SOURCE
from tests.crust.test_precursor_sampling import prior_state


def policy(mode='threads', points=3, cells=2, workers=2, **kwargs):
    return PrecursorExecutionPolicy(kernel=ExecutionPolicy(mode=mode, max_workers=workers,
        max_inflight=3, **kwargs), point_batch_size=points, cell_batch_size=cells)


def patch(chart, x=0., y=0., size=.01):
    xy = np.array([(x-size,y-size),(x+size,y-size),(x+size,y+size),(x-size,y+size)])
    return SphericalGeometry.polygon(chart._unproject(xy), chart=chart)


@contextmanager
def foreign_lease():
    """Hold the process-wide native-thread lease on a helper thread.

    While it is held, entering a KernelExecutor on any other thread is refused
    with the executor's own TectonicsError. A request that returns, or raises
    its own refusal, inside this block therefore entered no executor.
    """
    held = threading.Event(); done = threading.Event(); failure = []
    def hold():
        try:
            with KernelExecutor(ExecutionPolicy(mode='serial')):
                held.set(); done.wait()
        except BaseException as exc:
            failure.append(exc)
        finally:
            held.set()
    holder = threading.Thread(target=hold); holder.start(); held.wait()
    try:
        if failure:
            raise failure[0]
        yield
    finally:
        done.set(); holder.join()


def leases():
    """Process-wide executor claims: (native-thread lease users, CPU pool slots)."""
    return execution._LIMIT_USERS, execution._POOL_SLOTS


def native_limits():
    from threadpoolctl import threadpool_info
    import scipy.special  # the executor loads it before recording the limits it restores
    return sorted((x['filepath'], x['num_threads']) for x in threadpool_info())


class WorkerGate:
    """A cancel token that tells a dispatch's workers from the thread driving it.

    The dispatching thread asks first, before any worker exists, and is never
    held. Every other thread that asks is one of that dispatch's workers: it
    reports entry and waits for release. ``cancel=True`` then cancels the call.
    """
    def __init__(self, cancel=False):
        self.cancel = cancel; self.driver = None
        self.entered = threading.Event(); self.release = threading.Event()

    def is_set(self):
        me = threading.current_thread()
        if self.driver is None:
            self.driver = me
        elif me is not self.driver:
            self.entered.set(); self.release.wait(30)
        return self.cancel and self.entered.is_set()


class ThreadedSampling(unittest.TestCase):
    def compare(self, s, kind, inputs, *, kwargs=None, fields=(), limits=None):
        kw = REQUEST | (kwargs or {}) | {'fields': fields}
        with PreparedPrecursor(s, execution_policy=policy('serial'), limits=limits) as serial:
            expected = getattr(serial, 'sample_'+kind)(*inputs, **kw)
        for point_batch, cell_batch in ((1,1),(3,2),(7,4)):
            b = WorkBudget(128<<20)
            with PreparedPrecursor(s, execution_policy=policy(points=point_batch,cells=cell_batch),budget=b,limits=limits) as parallel:
                actual = getattr(parallel, 'sample_'+kind)(*inputs, **kw)
                self.assertEqual(actual.sample_id, expected.sample_id)
                for name in expected._buffers:
                    np.testing.assert_array_equal(actual.array(name), expected.array(name))
                self.assertEqual(parallel.execution_statistics()['route'], 'threads')
                self.assertLessEqual(parallel.execution_statistics()['peak_inflight'], 3)
                held = b.reserved_bytes
                # Reuse the same pool/plan; output identity must not encode worker order.
                again = getattr(parallel, 'sample_'+kind)(*inputs, **kw)
                self.assertEqual(again.sample_id, actual.sample_id)
                self.assertEqual(b.reserved_bytes, held)
            self.assertEqual(b.reserved_bytes, 0)

    def test_points_identical_with_mixed_provinces(self):
        x = np.column_stack((np.linspace(0.,10.,11),np.full(11,5.)))
        self.compare(state(mixed_case()), 'points', (x,np.arange(11,dtype=float)))

    def test_prior_points_identical_for_several_worker_batches(self):
        self.compare(prior_state(), 'points', (np.array([[i+.1,5.] for i in range(10)]),5.),
                     fields=('perturbation',))

    def test_half_space_points_identical(self):
        from atlas_tectonics import CoolingHistory
        t = ThermalInitialProfile('initial','fixture','half_space',temperatures_k=(300.,1400.),diffusivity_m2_s=1e-6,cooling_start_time_s=-100.)
        s=state(case(thermal_profiles=(t,)))
        self.compare(s,'points',(np.full((10,2),5.),np.linspace(0.,29.,10)))

    def test_unknown_temperature_masks_identical(self):
        t=ThermalInitialProfile('initial','fixture','unknown',unknown_reason='explicit unknown')
        self.compare(state(case(thermal_profiles=(t,))),'points',(np.full((10,2),5.),5.),
                     kwargs={'require_temperature':False})

    def test_cells_mixed_and_cross_batch_offsets_identical(self):
        cs=tuple(cell(str(i),rectangle(i,i+1)) for i in range(10))
        self.compare(state(mixed_case(edge=3.7)),'cells',(cs,))

    def test_cells_reference_mass_identical(self):
        cs=tuple(cell(str(i),rectangle(i,i+1)) for i in range(10))
        self.compare(state(mixed_case(edge=3.7)),'cells',(cs,),kwargs={'reference_mass_temperature_k':300.})

    def test_cells_prior_means_identical(self):
        self.compare(prior_state(),'cells',(tuple(cell(str(i),rectangle(i,i+1)) for i in range(10)),),
                     fields=('perturbation',))

    def test_cells_without_temperature_identical(self):
        self.compare(state(),'cells',(tuple(cell(str(i),rectangle(i,i+1)) for i in range(10)),),
                     kwargs={'include_temperature':False})

    def test_spherical_points_normalisation_identical(self):
        sf=SphericalFrame(1000.,'test-sphere')
        points=np.array([[1.,i/10.,.2] for i in range(10)])*7.
        self.compare(state(case(sf)),'points',(points,5.),kwargs={'frame_id':sf.frame_id})

    def test_spherical_cells_identical(self):
        sf=SphericalFrame(1000.,'test-sphere'); ch=SphericalChart(sf,(1.,0.,0.))
        cs=tuple(cell(str(i),patch(ch,x=i*.05,size=.005)) for i in range(8))
        self.compare(state(case(sf)),'cells',(cs,),kwargs={'frame_id':sf.frame_id})

    # R7 (s05-1): the plan no longer has an executor slot to inspect. The six tests
    # that asserted it was empty now run their request under foreign_lease(), which
    # turns any executor entry on this thread into the executor's own TectonicsError.

    def test_single_worker_never_creates_pool(self):
        with PreparedPrecursor(state(),execution_policy=policy(workers=1)) as p,foreign_lease():
            p.sample_points([[1.,2.]],5.,**REQUEST)
            self.assertEqual(p.execution_statistics()['route'],'serial')

    def test_auto_keeps_small_request_serial(self):
        with PreparedPrecursor(state()) as p,foreign_lease():
            p.sample_points([[1.,2.]],5.,**REQUEST)
            p.sample_cells((cell(),),**REQUEST)
            self.assertEqual(p.execution_statistics()['route'],'serial')

    def test_auto_uses_configured_point_threshold(self):
        cfg=replace(policy('auto'),min_parallel_points=6)
        with PreparedPrecursor(state(mixed_case()),execution_policy=cfg) as p:
            p.sample_points(np.ones((6,2)),5.,**REQUEST)
            self.assertEqual(p.execution_statistics()['parallel_jobs'],2)

    def test_auto_uses_configured_cell_threshold(self):
        cfg=replace(policy('auto'),min_parallel_cells=4)
        with PreparedPrecursor(state(),execution_policy=cfg) as p:
            p.sample_cells(tuple(cell(str(i),rectangle(i,i+1)) for i in range(4)),**REQUEST)
            self.assertEqual(p.execution_statistics()['parallel_jobs'],2)

    def test_explicit_nonadditive_overlaps_remain_labelled(self):
        cs=tuple(cell(str(i)) for i in range(3))
        self.compare(state(),'cells',(cs,),kwargs={'allow_overlapping_queries':True})

    def test_global_point_count_not_multiplied_by_batches(self):
        with PreparedPrecursor(state(),execution_policy=policy(points=1),limits=PrecursorSamplingLimits(max_points=3)) as p:
            with self.assertRaises(GeologyError):p.sample_points(np.ones((4,2)),5.,**REQUEST)

    def test_global_point_rows_not_multiplied_by_batches(self):
        b=WorkBudget(64<<20)
        with PreparedPrecursor(state(),execution_policy=policy(points=1),budget=b,limits=PrecursorSamplingLimits(max_rows=3)) as p:
            held=b.reserved_bytes
            with self.assertRaisesRegex(GeologyError,'whole-request'):p.sample_points(np.ones((4,2)),5.,**REQUEST)
            self.assertEqual(b.reserved_bytes,held)
            p.sample_points([[1.,1.]],5.,**REQUEST)
        self.assertEqual(b.reserved_bytes,0)

    def test_global_cell_rows_not_multiplied_by_batches(self):
        cs=tuple(cell(str(i),rectangle(i,i+1)) for i in range(3))
        with PreparedPrecursor(state(),execution_policy=policy(cells=1),limits=PrecursorSamplingLimits(max_rows=8)) as p:
            with self.assertRaisesRegex(GeologyError,'whole-request'):p.sample_cells(cs,**REQUEST)

    def test_global_cell_work_not_multiplied_by_batches(self):
        cs=tuple(cell(str(i),rectangle(i,i+1)) for i in range(3))
        with PreparedPrecursor(state(),execution_policy=policy(cells=1),limits=PrecursorSamplingLimits(max_work_items=4)) as p:
            with self.assertRaisesRegex(GeologyError,'whole-request'):p.sample_cells(cs,**REQUEST)

    def test_cancel_before_submission_no_pool_or_leak(self):
        b=WorkBudget(64<<20);e=threading.Event();e.set()
        with PreparedPrecursor(state(),execution_policy=policy(),budget=b) as p,foreign_lease():
            held=b.reserved_bytes
            with self.assertRaises(CancelledError):p.sample_points(np.ones((10,2)),5.,cancel=e,**REQUEST)
            self.assertNotIn('executor-inflight',b.statistics()['category_peaks'])
            self.assertEqual(b.reserved_bytes,held)

    def test_aggregate_memory_refusal_no_leak(self):
        b=WorkBudget(6<<20)
        with PreparedPrecursor(state(),execution_policy=policy(),budget=b) as p:
            held=b.reserved_bytes
            with self.assertRaises(MemoryLimitError):p.sample_points(np.ones((50000,2)),5.,**REQUEST)
            self.assertEqual(b.reserved_bytes,held)

    def test_individual_job_memory_refusal_no_leak(self):
        b=WorkBudget(64<<20)
        with PreparedPrecursor(state(),execution_policy=policy(max_work_bytes=100),budget=b) as p:
            held=b.reserved_bytes
            with self.assertRaises(MemoryLimitError):p.sample_points(np.ones((4,2)),5.,**REQUEST)
            self.assertEqual(b.reserved_bytes,held)

    def test_execution_configuration_not_scientific_identity(self):
        s=state()
        with PreparedPrecursor(s,execution_policy=policy('serial')) as a,PreparedPrecursor(s,execution_policy=policy()) as b:
            self.assertEqual(a.identity,b.identity)

    def test_auto_keeps_unindexed_points_serial(self):
        cfg=replace(policy('auto'),min_parallel_points=1)
        with PreparedPrecursor(state(),execution_policy=cfg) as p,foreign_lease():
            p.sample_points(np.ones((8,2)),5.,**REQUEST)
            self.assertEqual(p.execution_statistics()['route'],'serial')

    def test_default_cell_policy_does_not_force_measured_slow_threads(self):
        cfg=PrecursorExecutionPolicy()
        self.assertIsNone(cfg.min_parallel_cells)
        self.assertFalse(cfg.parallel('cells',10000))

    def test_global_geometry_hits_not_multiplied_by_batches(self):
        b=WorkBudget(64<<20)
        with PreparedPrecursor(state(mixed_case()),budget=b,execution_policy=policy(points=1),
                               geometry_limits=GeometryLimits(max_hits=3)) as p:
            held=b.reserved_bytes
            with self.assertRaisesRegex(GeologyError,'whole-request geometry-hit'):
                p.sample_points(np.ones((4,2)),5.,**REQUEST)
            self.assertEqual(b.reserved_bytes,held)
            p.sample_points([[1.,1.]],5.,**REQUEST)
        self.assertEqual(b.reserved_bytes,0)

    def test_threaded_snapshot_roundtrip_and_serial_dedup(self):
        for kind,args in (('points',(np.ones((7,2)),5.)),
                          ('cells',(tuple(cell(str(i),rectangle(i,i+1)) for i in range(7)),))):
            s=state(mixed_case())
            with PreparedPrecursor(s,execution_policy=policy()) as p:
                a=getattr(p,'sample_'+kind)(*args,**REQUEST)
            with PreparedPrecursor(s,execution_policy=policy('serial')) as p:
                reference=getattr(p,'sample_'+kind)(*args,**REQUEST)
            with tempfile.TemporaryDirectory() as td,ArrayStore(Path(td)/'result.db',StoreLimits(4096,8<<20,32<<20,8192)) as store:
                save_initial_samples(a,store);before=store.statistics()['unique_chunks']
                save_initial_samples(reference,store)
                self.assertEqual(store.statistics()['unique_chunks'],before)
                actual=load_initial_samples(store,a.sample_id)
                self.assertEqual(actual.sample_id,a.sample_id)
                for name in a._buffers:np.testing.assert_array_equal(actual.array(name),a.array(name))

    def test_real_sampler_cancelled_after_first_worker_enters(self):
        class WorkerCancellation:
            def __init__(self):self.seen=threading.Event();self.enabled=True
            def is_set(self):
                if self.enabled and threading.current_thread().name.startswith('atlas-kernel'):
                    self.seen.set()
                return self.enabled and self.seen.is_set()
        e=WorkerCancellation();b=WorkBudget(64<<20)
        with PreparedPrecursor(state(),budget=b,execution_policy=policy(points=1)) as p:
            held=b.reserved_bytes
            with self.assertRaises(CancelledError):p.sample_points(np.ones((8,2)),5.,cancel=e,**REQUEST)
            self.assertTrue(e.seen.is_set());self.assertEqual(b.reserved_bytes,held)
            e.enabled=False
            p.sample_points(np.ones((8,2)),5.,cancel=e,**REQUEST)
        self.assertEqual(b.reserved_bytes,0)


POINTS=np.array([[1.,5.],[8.,5.],[3.,3.],[6.,2.]])


class DispatchScopedExecutor(unittest.TestCase):
    """R7 (s05-1): each threaded dispatch owns its executor; the plan owns none.

    Where a helper thread makes a plan's first threaded call, that thread stays
    alive and the plan is closed on it in a ``finally``. Were a plan bound to its
    first caller again, that still releases the process-wide lease, so a failure
    here cannot fail every later test. A first caller that has already exited is
    exercised in a separate interpreter for the same reason.
    """
    def test_idle_plan_holds_no_pool_cpu_slots_or_native_lease(self):
        clean=leases();limits=native_limits();threads=set(threading.enumerate())
        with PreparedPrecursor(state(mixed_case()),execution_policy=policy()) as p:
            p.sample_points(POINTS,5.,**REQUEST)
            self.assertEqual(p.execution_statistics()['route'],'threads')
            self.assertEqual(leases(),clean);self.assertEqual(native_limits(),limits)
            self.assertEqual(set(threading.enumerate())-threads,set())
            def unrelated():
                with KernelExecutor(ExecutionPolicy(mode='serial')):return True
            with ThreadPoolExecutor(max_workers=1) as pool:self.assertTrue(pool.submit(unrelated).result(30))

    def test_plan_is_not_bound_to_its_first_threaded_caller(self):
        b=WorkBudget(64<<20);p=PreparedPrecursor(state(mixed_case()),budget=b,execution_policy=policy())
        cs=tuple(cell(str(i),rectangle(i,i+1)) for i in range(4))
        points=lambda:p.sample_points(POINTS,5.,**REQUEST).sample_id
        cells=lambda:(p.sample_cells(cs,**REQUEST).sample_id,p.execution_statistics()['route'])
        with ThreadPoolExecutor(max_workers=1) as first:
            try:
                with ThreadPoolExecutor(max_workers=1) as second:
                    ids=[first.submit(points).result(30),second.submit(points).result(30),points()]
                    self.assertEqual(len(set(ids)),1)
                    self.assertEqual(p.execution_statistics()['route'],'threads')
                    # The cell route dispatches through the same per-call executor.
                    self.assertEqual(second.submit(cells).result(30),first.submit(cells).result(30))
                    self.assertEqual(cells()[1],'threads')
                    second.submit(p.close).result(30)
                self.assertTrue(p._closed);self.assertEqual(b.reserved_bytes,0)
            finally:first.submit(p.close).result(30)

    def test_plan_outlives_the_thread_that_first_used_it(self):
        script='''import json,sys,threading
sys.path[:0]=sys.argv[1:]
from threadpoolctl import threadpool_info
import scipy.special
import atlas_tectonics.integration.parallel.execution as execution
from atlas_tectonics import PreparedPrecursor,PrecursorExecutionPolicy
from atlas_tectonics.integration.parallel.execution import ExecutionPolicy,KernelExecutor
from atlas_tectonics.integration.resources import WorkBudget
from tests.fixtures.precursor_fixtures import state,mixed_case,REQUEST
def native():return sorted((x['filepath'],x['num_threads']) for x in threadpool_info())
out={};b=WorkBudget(64<<20)
cfg=PrecursorExecutionPolicy(kernel=ExecutionPolicy(mode='threads',max_workers=2,max_inflight=3),point_batch_size=1)
p=PreparedPrecursor(state(mixed_case()),budget=b,execution_policy=cfg)
def attempt(name,call):
    try:out[name]=call()
    except Exception as exc:out[name]=type(exc).__name__+': '+str(exc)
def sample():return p.sample_points([[1.,5.],[8.,5.]],5.,**REQUEST).sample_id
def unrelated():
    with KernelExecutor(ExecutionPolicy(mode='serial')):return 'ok'
def close():p.close();return 'ok'
before=native()
caller=threading.Thread(target=attempt,args=('first',sample));caller.start();caller.join()
out['leases']=[execution._LIMIT_USERS,execution._POOL_SLOTS];out['limits_restored']=native()==before
# Started once the first caller has gone: if its thread identifier is handed straight back, this thread takes it.
keep=threading.Event();spare=threading.Thread(target=keep.wait);spare.start()
caller=threading.Thread(target=attempt,args=('second',sample));caller.start();caller.join()
attempt('constructor',sample);attempt('unrelated_executor',unrelated);attempt('close',close)
out['closed']=p._closed;out['reserved']=b.reserved_bytes
keep.set();spare.join()
print(json.dumps(out))
'''
        root=Path(__file__).resolve().parents[2]
        result=subprocess.run([sys.executable,'-I','-B','-c',script,str(root/'src'),
                               str(root.parent/'shared/src'),str(root)],
                              capture_output=True,text=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stderr)
        out=json.loads(result.stdout.strip().splitlines()[-1]);self.maxDiff=None
        self.assertEqual(len(out['first']),64,out)
        self.assertEqual(out,{'first':out['first'],'second':out['first'],'constructor':out['first'],
            'leases':[0,0],'limits_restored':True,'unrelated_executor':'ok','close':'ok','closed':True,'reserved':0})

    def test_threaded_calls_on_one_plan_take_turns(self):
        gate=WorkerGate();p=PreparedPrecursor(state(mixed_case()),execution_policy=policy())
        with ThreadPoolExecutor(max_workers=1) as first:
            try:
                with ThreadPoolExecutor(max_workers=1) as second:
                    try:
                        a=first.submit(lambda:p.sample_points(POINTS,5.,cancel=gate,**REQUEST).sample_id)
                        self.assertTrue(gate.entered.wait(30))
                        b=second.submit(lambda:p.sample_points(POINTS,5.,**REQUEST).sample_id)
                        # The second call queues on the dispatch lock. It neither runs beside the
                        # first nor meets the first call's native-thread lease, which would refuse it.
                        with self.assertRaises(TimeoutError):b.result(.25)
                    finally:gate.release.set()
                    self.assertEqual(a.result(30),b.result(30))
            finally:first.submit(p.close).result(30)
        self.assertTrue(p._closed)

    def test_callers_own_executor_conflict_is_refused_and_compatible_lease_is_returned(self):
        b=WorkBudget(64<<20)
        with PreparedPrecursor(state(mixed_case()),budget=b,execution_policy=policy()) as p:
            held=b.reserved_bytes
            with KernelExecutor(ExecutionPolicy(mode='serial',max_workers=1,inner_threads=2)):
                with self.assertRaises(TectonicsError) as refused:p.sample_points(POINTS,5.,**REQUEST)
                self.assertIs(type(refused.exception),TectonicsError)
                self.assertEqual(b.reserved_bytes,held)
                self.assertNotIn('executor-inflight',b.statistics()['category_peaks'])
            with KernelExecutor(ExecutionPolicy(mode='serial')):
                outer=leases()
                p.sample_points(POINTS,5.,**REQUEST)
                self.assertEqual(p.execution_statistics()['route'],'threads')
                self.assertEqual(leases(),outer)

    def test_failed_and_cancelled_dispatches_return_pool_and_lease(self):
        b=WorkBudget(64<<20);clean=leases();threads=set(threading.enumerate())
        with PreparedPrecursor(state(),budget=b,execution_policy=policy(points=1)) as p:
            held=b.reserved_bytes
            def returned():return leases(),b.reserved_bytes,set(threading.enumerate())-threads
            gate=WorkerGate(cancel=True);gate.release.set()
            with self.assertRaises(CancelledError):p.sample_points(np.ones((8,2)),5.,cancel=gate,**REQUEST)
            self.assertTrue(gate.entered.is_set());self.assertEqual(returned(),(clean,held,set()))
            p.sample_points(np.ones((8,2)),5.,**REQUEST)
            self.assertEqual(returned(),(clean,held,set()))

    def test_statistics_describe_only_the_last_dispatch(self):
        with PreparedPrecursor(state(mixed_case()),budget=WorkBudget(64<<20),execution_policy=policy(points=1)) as p:
            p.sample_points(np.ones((6,2)),5.,**REQUEST);large=p.execution_statistics()
            p.sample_points(np.ones((1,2)),5.,**REQUEST);small=p.execution_statistics()
        self.assertEqual((large['parallel_jobs'],large['peak_inflight']),(6,3))
        self.assertEqual((small['parallel_jobs'],small['peak_inflight']),(1,1))
        self.assertLess(small['accounted_executor_peak_bytes'],large['accounted_executor_peak_bytes'])

    def test_threaded_request_that_does_not_complete_keeps_the_earlier_statistics(self):
        # A guard for what the execution contract states, not a repair: it held before R7 too. A threaded request
        # writes the record only once all its jobs have completed, so the record can describe an earlier request.
        with PreparedPrecursor(state(),execution_policy=policy(points=1)) as p:
            p.sample_points(np.ones((6,2)),5.,**REQUEST);recorded=p.execution_statistics()
            self.assertEqual((recorded['route'],recorded['parallel_jobs']),('threads',6))
            gate=WorkerGate(cancel=True);gate.release.set()
            with self.assertRaises(CancelledError):p.sample_points(np.ones((8,2)),5.,cancel=gate,**REQUEST)
            self.assertTrue(gate.entered.is_set());self.assertEqual(p.execution_statistics(),recorded)
            p.sample_points(np.ones((2,2)),5.,**REQUEST)
            self.assertEqual(p.execution_statistics()['parallel_jobs'],2)


class SphericalBroadPhase(unittest.TestCase):
    def setUp(self):
        self.sf=SphericalFrame(1000.,'index-sphere')
        self.ch=SphericalChart(self.sf,(1.,0.,0.))
        self.budget=WorkBudget(128<<20)
        self.gl=GeometryLimits();self.limits=PrecursorSamplingLimits()

    def check(self,cells,**kw):
        return _check_cell_overlaps(cells,self.gl,self.limits,self.budget,None,**kw)

    def test_common_chart_grid_prunes_pairs(self):
        cs=tuple(cell(str(i),patch(self.ch,x=(i%8)*.06,y=(i//8)*.06,size=.005)) for i in range(64))
        d={};self.check(cs,diagnostics=d)
        self.assertEqual(d['cap_builds'],64)
        self.assertEqual(d.get('exact_overlays',0),0)
        self.assertLessEqual(d['box_candidates'],64*2)
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_index_candidates_cover_all_exact_intersections(self):
        gs=tuple(patch(self.ch,x=(i%5)*.025,y=(i//5)*.025,size=.02) for i in range(20))
        with SphericalCandidateIndex(gs,budget=self.budget) as index:
            for i,a in enumerate(gs):
                hits=set(map(int,index.query(index=i)))
                self.assertEqual(list(index.query(index=i)),sorted(hits))
                for j,b in enumerate(gs):
                    if a.overlay(b,'intersection').area_m2>0:self.assertIn(j,hits)

    def test_thin_shapes_curved_edges_and_interior_fit_caps(self):
        # Long/concave footprints and tiny footprints must not use vertex-only
        # planar boxes in latitude/longitude. Sample their actual gnomonic interior.
        rings=(np.array([[-.7,-.01],[.7,-.01],[.7,.01],[-.7,.01]]),
               np.array([[0,0],[.3,0],[.3,.1],[.1,.1],[.1,.3],[0,.3]]),
               np.array([[0,0],[1e-7,0],[1e-7,1e-7],[0,1e-7]]))
        for xy in rings:
            g=SphericalGeometry.polygon(self.ch._unproject(xy),chart=self.ch)
            centre,radius=spherical_cap(g)
            edge=[]
            for a,b in zip(xy,np.roll(xy,-1,axis=0)):
                edge.extend(a+t*(b-a) for t in np.linspace(0,1,31))
            vs=self.ch._unproject(np.asarray(edge))
            angles=np.arctan2(np.linalg.norm(np.cross(vs,centre),axis=1),vs@centre)
            self.assertLessEqual(float(np.max(angles)),radius)

    def test_polar_overlaps_retained(self):
        ch=SphericalChart(self.sf,(0.,0.,1.))
        gs=(patch(ch),patch(ch,x=.005),patch(ch,x=.2))
        with SphericalCandidateIndex(gs,budget=self.budget) as index:
            self.assertIn(1,index.query(index=0));self.assertNotIn(2,index.query(index=0))

    def test_dateline_overlaps_retained(self):
        def chart(deg):return SphericalChart(self.sf,(math.cos(math.radians(deg)),math.sin(math.radians(deg)),0.))
        gs=(patch(chart(179.9)),patch(chart(-179.9)))
        with SphericalCandidateIndex(gs,budget=self.budget) as index:
            self.assertIn(1,index.query(index=0))
        self.assertGreater(gs[0].overlay(gs[1],'intersection').area_m2,0)

    def test_opposite_hemispheres_need_no_common_chart(self):
        gs=(patch(self.ch),patch(SphericalChart(self.sf,(-1.,0.,0.))))
        self.check(tuple(cell(str(i),g) for i,g in enumerate(gs)))

    def test_touching_spherical_faces_not_overlap(self):
        a=patch(self.ch,x=0.,size=.01);b=patch(self.ch,x=.02,size=.01)
        self.check((cell('a',a),cell('b',b)))

    def test_same_footprint_stacked_depths_linear_check(self):
        g=patch(self.ch)
        cs=tuple(cell(str(i),g,top=i*.01,bottom=(i+1)*.01) for i in range(1000))
        d={};self.check(cs,diagnostics=d)
        self.assertEqual(d['cap_builds'],1)
        self.assertEqual(d.get('exact_overlays',0),0)
        self.assertEqual(d['depth_interval_checks'],0)

    def test_interleaved_distinct_footprint_depth_bands(self):
        a=patch(self.ch);b=patch(self.ch,x=.005)
        cs=tuple(cell(str(i),a if i%2==0 else b,top=i,bottom=i+1.) for i in range(20))
        d={};self.check(cs,diagnostics=d)
        self.assertEqual(d.get('exact_overlays',0),0)
        self.assertLessEqual(d['depth_interval_checks'],20)

    def test_setup_and_query_memory_refusals_do_not_leak(self):
        g=patch(self.ch);tiny=WorkBudget(1)
        with self.assertRaises(MemoryLimitError):SphericalCandidateIndex((g,),budget=tiny)
        self.assertEqual(tiny.reserved_bytes,0)
        with SphericalCandidateIndex((g,),budget=self.budget) as index:
            held=self.budget.reserved_bytes
            with self.assertRaises(MemoryLimitError):index.query(index=0,budget=tiny)
            self.assertEqual(self.budget.reserved_bytes,held)
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_cancelled_index_setup_and_query_clean_up(self):
        e=threading.Event();e.set();g=patch(self.ch)
        with self.assertRaises(CancelledError):SphericalCandidateIndex((g,),budget=self.budget,cancel=e)
        self.assertEqual(self.budget.reserved_bytes,0)
        with SphericalCandidateIndex((g,),budget=self.budget) as index:
            with self.assertRaises(CancelledError):index.query(index=0,cancel=e)

    def test_queries_safe_for_parallel_readers(self):
        gs=tuple(patch(self.ch,x=i*.01) for i in range(20))
        with SphericalCandidateIndex(gs,budget=self.budget) as index:
            expected=index.query(index=5)
            with ThreadPoolExecutor(max_workers=2) as pool:
                values=list(pool.map(lambda _:index.query(index=5),range(4)))
            for actual in values:np.testing.assert_array_equal(actual,expected)

    def test_previous_reference_agrees_on_small_disjoint_case(self):
        cs=tuple(cell(str(i),patch(self.ch,x=i*.05,size=.005)) for i in range(12))
        self.check(cs)
        _check_cell_overlaps_reference(cs,self.gl,self.limits,self.budget,None)


    def test_holes_and_multipart_never_hide_candidate_intersections(self):
        shell=np.array([[-.2,-.2],[.2,-.2],[.2,.2],[-.2,.2]])
        hole=np.array([[-.05,-.05],[.05,-.05],[.05,.05],[-.05,.05]])
        holed=SphericalGeometry.polygon(self.ch._unproject(shell),holes=(self.ch._unproject(hole),),chart=self.ch)
        multi=patch(self.ch,x=-.3).overlay(patch(self.ch,x=.3),'union')
        gs=(holed,multi,patch(self.ch,x=.19),patch(self.ch,x=.3))
        with SphericalCandidateIndex(gs,budget=self.budget) as index:
            for i,a in enumerate(gs):
                hits=set(map(int,index.query(index=i)))
                for j,b in enumerate(gs):
                    if a.overlay(b,'intersection').area_m2>0:self.assertIn(j,hits)

    def test_query_enclosure_does_not_use_longitude_bounds(self):
        ch=SphericalChart(self.sf,(-1.,0.,0.))
        gs=(patch(ch,x=-.002),patch(ch,x=.002))
        with SphericalCandidateIndex(gs,budget=self.budget) as index:
            np.testing.assert_array_equal(index.query(geometry=patch(ch)),[0,1])

    def test_large_conditioned_cap_contains_sampled_minor_edges(self):
        xy=np.array([[-50.,-.1],[50.,-.1],[50.,.1],[-50.,.1]])
        g=SphericalGeometry.polygon(self.ch._unproject(xy),chart=self.ch)
        centre,radius=spherical_cap(g)
        edges=np.concatenate([np.linspace(a,b,100) for a,b in zip(xy,np.roll(xy,-1,axis=0))])
        dirs=self.ch._unproject(edges)
        angle=np.arctan2(np.linalg.norm(np.cross(dirs,centre),axis=1),dirs@centre)
        self.assertLessEqual(float(angle.max()),radius)


class AdmittedScheduler(unittest.TestCase):
    def test_ordered_calls_reuse_existing_executor(self):
        e=threading.Event();b=WorkBudget(8<<20)
        jobs=tuple(_AdmittedCall(lambda budget,i=i:i,lambda x:x,e.set,1,1024) for i in range(8))
        with KernelExecutor(ExecutionPolicy(mode='threads',max_workers=2,max_inflight=2),budget=b) as ex:
            self.assertEqual(list(ex._admitted_calls(jobs)),list(range(8)))
            self.assertEqual(ex.statistics()['parallel_jobs'],8)
            self.assertEqual(ex.statistics()['peak_inflight'],2)
        self.assertEqual(b.reserved_bytes,0)

    def test_cancellation_drains_already_running_native_jobs(self):
        entered=threading.Event();release=threading.Event();aborted=threading.Event();b=WorkBudget(8<<20)
        def first(budget):
            entered.wait(5)
            raise ValueError('intentional job failure')
        def second(budget):
            entered.set()
            release.wait(5)
            return 2
        def abort():aborted.set();release.set()
        tasks=(_AdmittedCall(first,lambda x:x,abort,1,1024),_AdmittedCall(second,lambda x:x,abort,1,1024))
        with KernelExecutor(ExecutionPolicy(mode='threads',max_workers=2),budget=b) as ex:
            with self.assertRaisesRegex(ValueError,'intentional'):list(ex._admitted_calls(tasks))
            self.assertTrue(aborted.is_set());self.assertEqual(b.reserved_bytes,0)
            good=_AdmittedCall(lambda budget:3,lambda x:x,abort,1,1024)
            self.assertEqual(list(ex._admitted_calls((good,))),[3])

    def test_close_unstarted_stream_has_no_tasks(self):
        with KernelExecutor(ExecutionPolicy(mode='threads')) as ex:
            stream=ex._admitted_calls(())
            stream.close()
            self.assertEqual(ex.statistics()['completed_jobs'],0)


if __name__ == '__main__':unittest.main()
