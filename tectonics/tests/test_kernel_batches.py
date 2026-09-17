"""Items 4/5: backend, batching, accuracy and ownership; no timing thresholds."""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import math
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (Rotation, PeriodicFlexure, PeriodicGrid1D,
    FlexureParameters, ThermalParameters, half_space_temperature, TectonicsError)
from atlas_tectonics._validation import frozen
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.thermal import cooling_work_bytes
from atlas_tectonics.reuse import CachePolicy
from atlas_tectonics.storage import ArrayStore, StoreLimits
from atlas_tectonics.reuse import cached_temperature, cached_flexure

THERMAL = ThermalParameters('synthetic', 'batch verification, not Earth', 300., 1300., 1.)
ELASTIC = FlexureParameters('synthetic', 'batch verification, not Earth', 12., 1., 0., 1., 1.)
# Existing foundation tolerance. No older test or acceptance constant is edited.
RTOL, ATOL = 1e-12, 1e-12


def old_cooling(depth, age, params):
    """Independent scalar-erf formula and legacy operation order, for verification."""
    d, t = np.broadcast_arrays(np.asarray(depth, dtype=float), np.asarray(age, dtype=float))
    result = np.empty(d.shape)
    for index in np.ndindex(d.shape):
        if d[index] == 0:
            result[index] = params.surface_temperature_k
        elif t[index] == 0:
            result[index] = params.mantle_temperature_k
        else:
            length = (2 * math.sqrt(params.diffusivity_m2_s)) * math.sqrt(t[index])
            result[index] = params.surface_temperature_k + (params.mantle_temperature_k - params.surface_temperature_k) * math.erf(d[index] / length)
    return result


class CoolingBatchTests(unittest.TestCase):
    def test_default_and_reference_across_layouts(self):
        pairs = [(2., 1.), (np.arange(17.), 1.), (1., np.arange(17.)),
                 (np.arange(17.)[:, None], np.array([0., 1., 4.])[None, :]),
                 (np.arange(60.).reshape(3,4,5)[:,::2,::-1], np.ones((1,2,1))),
                 (np.arange(16.).astype('>f8')[::2], np.ones(8)),
                 (np.asfortranarray(np.arange(35.).reshape(5,7)), np.ones((5,1)))]
        for depth, age in pairs:
            for size in (1, 7, 65_536):
                with self.subTest(shape=np.shape(depth), age=np.shape(age), batch=size):
                    a = half_space_temperature(depth, age, THERMAL, batch_elements=size)
                    b = half_space_temperature(depth, age, THERMAL, backend='reference', batch_elements=size)
                    assert_allclose(a, old_cooling(depth, age, THERMAL), rtol=RTOL, atol=ATOL)
                    assert_allclose(a, b, rtol=2e-15, atol=ATOL)
                    self.assertEqual(a.shape, np.broadcast_shapes(np.shape(depth), np.shape(age)))
                    with self.assertRaises(ValueError): a.setflags(write=True)

    def test_batch_partition_preserves_bits(self):
        d = np.linspace(0., 7., 37)[:,None]
        t = np.array([0., 1e-100, 1., 1e100])[None,:]
        for backend in ('reference', 'scipy'):
            expected = half_space_temperature(d,t,THERMAL,backend=backend)
            for size in (1, 3, 17, 65536):
                self.assertEqual(expected.tobytes(), half_space_temperature(d,t,THERMAL,backend=backend,batch_elements=size).tobytes())

    def test_age_factor_is_computed_before_broadcast(self):
        import atlas_tectonics.thermal as thermal
        shapes = []
        original = np.sqrt
        def traced(value, *args, **kwargs):
            shapes.append(np.shape(value)); return original(value, *args, **kwargs)
        with mock.patch.object(thermal.np, 'sqrt', traced):
            half_space_temperature(np.arange(1024.)[:,None],np.array([[0.,1.,4.]]),THERMAL)
        self.assertEqual(shapes, [(1,3)])

    def test_oversized_batch_hint_is_bounded_by_actual_output(self):
        expected=half_space_temperature([0.,1.,2.],1.,THERMAL)
        actual=half_space_temperature([0.,1.,2.],1.,THERMAL,batch_elements=10**100)
        assert_array_equal(actual,expected)

    def test_erf_calls_are_bounded(self):
        import scipy.special
        counts = []
        original = scipy.special.erf
        def traced(value, **kwargs):
            counts.append(value.size);return original(value, **kwargs)
        with mock.patch.object(scipy.special,'erf',traced):
            half_space_temperature(np.arange(100.)[:,None],np.ones((1,13)),THERMAL,batch_elements=31)
        self.assertEqual(sum(counts),1300)
        self.assertLessEqual(max(counts),31)

    def test_zero_age_surface_equal_temperatures_and_saturation(self):
        d=np.array([0.,-0.,1.,1e308])[:,None];t=np.array([0.,-0.,1.,1e-300])[None,:]
        a=half_space_temperature(d,t,THERMAL)
        assert_array_equal(a[:2],np.full((2,4),300.))
        assert_array_equal(a[2:,0],np.full(2,1300.))
        self.assertTrue(np.all((300<=a)&(a<=1300)))
        p=replace(THERMAL,mantle_temperature_k=300.)
        assert_array_equal(half_space_temperature(d,t,p),np.full((4,4),300.))

    def test_invalid_inputs_and_batch_size(self):
        for bad in (np.ma.array([1.]), [True,1.], [np.nan], [-1.], [], np.array([])):
            with self.assertRaises(TectonicsError):half_space_temperature(bad,1,THERMAL)
        for size in (True,0,-1,3.5):
            with self.assertRaises(TectonicsError):half_space_temperature([1.],1,THERMAL,batch_elements=size)
        with self.assertRaises(TectonicsError):half_space_temperature(np.ones(2),np.ones(3),THERMAL)
        with self.assertRaises(TectonicsError):half_space_temperature(1,1,THERMAL,backend='auto')

    def test_extreme_diffusion_length_refused(self):
        p=replace(THERMAL,diffusivity_m2_s=1e308)
        with self.assertRaises(TectonicsError):half_space_temperature(1.,1e308,p)

    def test_budget_refuses_broadcast_before_capture_or_allocation(self):
        depth=np.ones((32768,1));age=np.ones((1,32768));b=WorkBudget(1<<20)
        with mock.patch('atlas_tectonics.thermal.array',side_effect=AssertionError('captured')):
            with self.assertRaises(MemoryLimitError):half_space_temperature(depth,age,THERMAL,budget=b)
        self.assertEqual(b.reserved_bytes,0)

    def test_exact_budget_and_failure_release(self):
        shape=(11,3);b=WorkBudget(cooling_work_bytes((11,1),(1,3),7))
        half_space_temperature(np.ones((11,1)),np.ones((1,3)),THERMAL,batch_elements=7,budget=b)
        self.assertEqual(b.reserved_bytes,0)
        with mock.patch('scipy.special.erf',side_effect=RuntimeError('cancelled')):
            with self.assertRaises(RuntimeError):half_space_temperature(np.ones((11,1)),np.ones((1,3)),THERMAL,batch_elements=7,budget=b)
        self.assertEqual(b.reserved_bytes,0)

    def test_caller_mutation_after_return_does_not_change_result(self):
        d=np.arange(10.);a=half_space_temperature(d,1,THERMAL);before=a.tobytes();d[:]=999
        self.assertEqual(a.tobytes(),before)


class RotationBatchTests(unittest.TestCase):
    def test_matrix_is_default_and_reused(self):
        rotation=Rotation.from_axis_angle([1,2,3],.6);x=np.arange(99.).reshape(33,3)
        actual=rotation.apply(x)
        assert_allclose(actual,rotation.apply(x,backend='reference'),rtol=RTOL,atol=ATOL)
        self.assertEqual(actual.tobytes(),rotation.apply(x,backend='matrix').tobytes())
        self.assertEqual(rotation.setup_bytes,72)
        self.assertTrue(np.shares_memory(rotation.matrix,rotation.matrix))
        with self.assertRaises(ValueError):rotation.matrix.setflags(write=True)
        view=rotation.matrix;view.shape=(9,)
        self.assertEqual(rotation.matrix.shape,(3,3))

    def test_rodrigues_independent_solution_and_norms(self):
        rng=np.random.default_rng(4517)
        for _ in range(32):
            axis=rng.normal(size=3);axis/=np.linalg.norm(axis);angle=rng.uniform(-math.pi,math.pi)
            rotation=Rotation.from_axis_angle(axis,angle);v=rng.normal(size=(37,3))
            expected=v*math.cos(angle)+np.cross(axis,v)*math.sin(angle)+(v@axis)[:,None]*axis*(1-math.cos(angle))
            actual=rotation.apply(v,batch_vectors=7)
            assert_allclose(actual,expected,rtol=RTOL,atol=ATOL)
            assert_allclose(np.linalg.norm(actual,axis=-1),np.linalg.norm(v,axis=-1),rtol=RTOL,atol=ATOL)
            assert_allclose(rotation.matrix@rotation.matrix.T,np.eye(3),rtol=RTOL,atol=ATOL)
            self.assertAlmostEqual(np.linalg.det(rotation.matrix),1.,places=12)

    def test_layout_scale_and_inverse(self):
        base=np.arange(90.).reshape(5,6,3)-45
        rotation=Rotation.from_axis_angle([1,3,2],.4)
        for data in (base,base[:,::2,:],np.asfortranarray(base),base.astype('>f8')):
            for scale in (1e-200,1.,1e150):
                actual=rotation.apply(data*scale,batch_vectors=11)
                reference=rotation.apply(data*scale,backend='reference')
                assert_allclose(actual/scale,reference/scale,rtol=RTOL,atol=ATOL)
                assert_allclose(rotation.inverse().apply(actual)/scale,data,rtol=RTOL,atol=ATOL)

    def test_subnormal_quaternion_and_negative_equivalent(self):
        tiny=float(np.nextafter(0.,1.))
        for scale in (tiny,1e-250,1.,1e300):
            r=Rotation((0.,scale,scale,scale))
            assert_allclose(np.linalg.norm(r.apply(np.eye(3)),axis=1),np.ones(3),atol=1e-14)
        p=Rotation((1,2,3,4));q=Rotation((-1,-2,-3,-4))
        assert_array_equal(p.matrix,q.matrix)

    def test_partition_equivalence_and_immutability(self):
        r=Rotation.from_axis_angle([1,2,3],.7);p=frozen(np.arange(303.).reshape(101,3))
        expected=r.apply(p)
        for n in (1,3,16,65536):
            a=r.apply(p,batch_vectors=n)
            assert_allclose(a,expected,rtol=RTOL,atol=ATOL)
            with self.assertRaises(ValueError):a.setflags(write=True)
        self.assertFalse(np.shares_memory(a,p))

    def test_limits_and_invalid_input(self):
        r=Rotation((1,0,0,0))
        for b in (0,False,-1,3.5):
            with self.assertRaises(TectonicsError):r.apply([1,2,3],batch_vectors=b)
        for p in ([1,2],np.ones((0,3)),np.ma.array([1,2,3])):
            with self.assertRaises(TectonicsError):r.apply(p)
        with self.assertRaises(TectonicsError):r.apply([1,2,3],backend='gpu')
        with mock.patch('atlas_tectonics.kinematics.array',side_effect=AssertionError('captured')):
            with self.assertRaises(MemoryLimitError):r.apply(np.ones((100,3)),budget=WorkBudget(16))

    def test_restore_rebuilds_operator(self):
        r=Rotation.from_axis_angle([1,2,3],.4)
        for restored in (copy.deepcopy(r),pickle.loads(pickle.dumps(r))):
            assert_allclose(restored.matrix,r.matrix,rtol=RTOL,atol=ATOL)
            with self.assertRaises(ValueError):restored.matrix.setflags(write=True)

    def test_streaming_no_prefetch_and_budget_release(self):
        r=Rotation.from_axis_angle([1,0,0],.7);seen=[];b=WorkBudget(1<<20)
        def inputs():
            for i in range(3):seen.append(i);yield np.full((7,3),i+1.)
        it=r.apply_batches(inputs(),budget=b,batch_vectors=3)
        first=next(it)
        self.assertEqual(seen,[0]);self.assertEqual(b.reserved_bytes,0)
        old=first.tobytes();next(it);self.assertEqual(first.tobytes(),old)
        it.close();self.assertEqual(seen,[0,1])


class FlexureBatchTests(unittest.TestCase):
    def test_batched_matches_dense_periodic_operator(self):
        for n in (5,15,16,33):
            grid=PeriodicGrid1D(n,float(n));op=PeriodicFlexure(grid,ELASTIC)
            matrix=np.eye(n)
            for i in range(n):
                for offset,value in ((-2,1),(-1,-4),(0,6),(1,-4),(2,1)):
                    matrix[i,(i+offset)%n]+=value
            loads=np.random.default_rng(n).normal(size=(7,n))
            expected=np.linalg.solve(matrix,loads.T).T
            for size in (1,3,32):assert_allclose(op.solve(loads,batch_loads=size),expected,rtol=RTOL,atol=ATOL)

    def test_against_unbatched_fft_same_discrete_operator(self):
        for n in (15,64,257):
            op=PeriodicFlexure(PeriodicGrid1D(n,float(n)),ELASTIC)
            loads=np.cos(np.arange(2*5*n)).reshape(2,5,n)
            expected=np.fft.irfft(np.fft.rfft(loads,axis=-1)*op._gain,n=n,axis=-1)
            for size in (1,3,32):assert_allclose(op.solve(loads,batch_loads=size),expected,rtol=RTOL,atol=ATOL)

    def test_default_grouping_keeps_at_least_one_complete_domain(self):
        import atlas_tectonics.flexure as flexure
        op=PeriodicFlexure(PeriodicGrid1D(65,65),ELASTIC)
        self.assertEqual(flexure.DEFAULT_FLEXURE_BATCH_BYTES,8*1024**2)
        with mock.patch.object(flexure,'DEFAULT_FLEXURE_BATCH_BYTES',1):
            self.assertEqual(op._batch_loads(None),1)
            assert_allclose(op.solve(np.ones((3,65))),1.,rtol=RTOL,atol=ATOL)

    def test_fft_never_splits_a_domain(self):
        n=65;op=PeriodicFlexure(PeriodicGrid1D(n,n),ELASTIC);shapes=[];fn=np.fft.rfft
        def traced(value,**kwargs):shapes.append(value.shape);return fn(value,**kwargs)
        with mock.patch('numpy.fft.rfft',traced):op.solve(np.ones((11,n)),batch_loads=4)
        self.assertEqual(shapes,[(4,n),(4,n),(3,n)])

    def test_setup_unchanged_and_no_output_alias(self):
        op=PeriodicFlexure(PeriodicGrid1D(32,32),ELASTIC);before=op._gain.tobytes();identity=op.operator_id
        loads=np.ones((3,32));actual=op.solve(loads);loads[:]=99
        assert_allclose(actual,1.,rtol=RTOL,atol=ATOL)
        self.assertEqual(before,op._gain.tobytes());self.assertEqual(identity,op.operator_id)
        with self.assertRaises(ValueError):actual.setflags(write=True)

    def test_strides_and_leading_axes(self):
        op=PeriodicFlexure(PeriodicGrid1D(17,17),ELASTIC)
        x=np.arange(4*6*34.).reshape(4,6,34)[:,::2,::2]
        for data in (x,np.asfortranarray(x),x.astype('>f8')):
            a=op.solve(data,batch_loads=2)
            self.assertEqual(a.shape,(4,3,17))
            assert_allclose(a,op.solve(np.ascontiguousarray(x),batch_loads=32),rtol=RTOL,atol=ATOL)

    def test_batch_size_and_empty_refused(self):
        op=PeriodicFlexure(PeriodicGrid1D(16,16),ELASTIC)
        for size in (0,-1,False,2.5):
            with self.assertRaises(TectonicsError):op.solve(np.ones(16),batch_loads=size)
        for value in (np.ones((0,16)),np.ones(15),np.ma.array(np.ones(16))):
            with self.assertRaises(TectonicsError):op.solve(value)

    def test_exact_budget_and_failure_release(self):
        op=PeriodicFlexure(PeriodicGrid1D(32,32),ELASTIC);b=WorkBudget(op.work_bytes((11,32),batch_loads=3))
        op.solve(np.ones((11,32)),budget=b,batch_loads=3);self.assertEqual(b.reserved_bytes,0)
        with mock.patch('numpy.fft.rfft',side_effect=RuntimeError('cancelled')):
            with self.assertRaises(RuntimeError):op.solve(np.ones((11,32)),budget=b,batch_loads=3)
        self.assertEqual(b.reserved_bytes,0)
        with self.assertRaises(MemoryLimitError):op.solve(np.ones((11,32)),budget=WorkBudget(16))

    def test_streaming_complete_independent_results(self):
        op=PeriodicFlexure(PeriodicGrid1D(32,32),ELASTIC);seen=[];b=WorkBudget(1<<20)
        def batches():
            for i in range(3):seen.append(i);yield np.full((3,32),i+1.)
        it=op.solve_batches(batches(),budget=b,batch_loads=2);first=next(it)
        self.assertEqual(seen,[0]);assert_allclose(first,1.,rtol=RTOL,atol=ATOL)
        self.assertEqual(b.reserved_bytes,0);next(it);assert_allclose(first,1.,rtol=RTOL,atol=ATOL)
        it.close();self.assertEqual(seen,[0,1])


class BatchReuseTests(unittest.TestCase):
    def test_default_cooling_cache_miss_hit_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'array.db';limits=StoreLimits(1024,1<<20,4<<20)
            d=np.arange(32.)[:,None];t=np.array([[0.,1.,4.]])
            with ArrayStore(path,limits) as store:
                a=cached_temperature(d,t,THERMAL,store=store,cache_policy=CachePolicy(mode="always"))
                b=cached_temperature(d,t,THERMAL,store=store,cache_policy=CachePolicy(mode="always"))
                self.assertEqual(a.tobytes(),b.tobytes());self.assertEqual(store.statistics()['snapshots'],1)
            with ArrayStore(path,limits) as store:
                c=cached_temperature(d,t,THERMAL,store=store,cache_policy=CachePolicy(mode="always"))
                self.assertEqual(a.tobytes(),c.tobytes())
                with self.assertRaises(ValueError):c.setflags(write=True)

    def test_batched_flexure_cache_and_changed_load(self):
        with tempfile.TemporaryDirectory() as tmp, ArrayStore(Path(tmp)/'a.db',StoreLimits(1024,1<<20,4<<20)) as store:
            op=PeriodicFlexure(PeriodicGrid1D(32,32),ELASTIC);load=np.cos(np.arange(7*32.)).reshape(7,32)
            for value in (load,load,load+1):
                a=cached_flexure(op,value,store=store,cache_policy=CachePolicy(mode="always"))
                assert_allclose(a,op.solve(value),rtol=RTOL,atol=ATOL)
            self.assertEqual(store.statistics()['snapshots'],2)

if __name__=='__main__':unittest.main()
