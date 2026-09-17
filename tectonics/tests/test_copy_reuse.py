"""Copy/alias regression checks: no timing thresholds or new simulation cases."""
from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_array_equal

from atlas_tectonics import (Rotation, PeriodicGrid1D, PeriodicFlexure,
    FlexureParameters, ThermalParameters, half_space_temperature, advect_thickness,
    TectonicsError)
from atlas_tectonics._validation import array, read_array, frozen, snapshot
from atlas_tectonics import reuse
from atlas_tectonics.reuse import CachePolicy
from atlas_tectonics.storage import ArrayStore, StoreLimits

THERMAL = ThermalParameters('synthetic', 'copy tests', 300., 1300., 1.)
ELASTIC = FlexureParameters('synthetic', 'copy tests', 12., 1., 0., 1., 1.)


class CopyContractTests(unittest.TestCase):
    def test_mutable_owner_is_detached(self):
        source = np.arange(16.)
        for fn in (array, read_array, snapshot):
            result = fn(source, 'x')
            self.assertFalse(np.shares_memory(result, source))
            source[0] = 900
            self.assertNotEqual(result[0], 900)
            source[0] = 0

    def test_readonly_flag_does_not_prove_immutable_ownership(self):
        source = np.arange(16.)
        source.setflags(write=False)
        result = read_array(source, 'x')
        self.assertFalse(np.shares_memory(result, source))
        source.setflags(write=True)
        source[:] = 900
        assert_array_equal(result, np.arange(16.))

    def test_readonly_memoryview_over_bytearray_not_borrowed(self):
        owner = bytearray(np.arange(16.).tobytes())
        source = np.frombuffer(memoryview(owner).toreadonly(), dtype=np.float64)
        result = read_array(source, 'x')
        owner[:] = np.zeros(16).tobytes()
        assert_array_equal(result, np.arange(16.))
        self.assertFalse(np.shares_memory(result, source))

    def test_true_immutable_buffer_is_shared_with_private_metadata(self):
        source = frozen(np.arange(24.).reshape(4, 6))
        result = read_array(source, 'x')
        self.assertTrue(np.shares_memory(result, source))
        self.assertIsNot(result, source)
        source.shape = (24,)
        self.assertEqual(result.shape, (4, 6))
        with self.assertRaises(ValueError):
            result.setflags(write=True)

    def test_immutable_contiguous_slice_and_scalar(self):
        source = frozen(np.arange(100.))
        for value in (source[10:30], frozen(np.array(2.))):
            result = read_array(value, 'x')
            self.assertTrue(np.shares_memory(result, value))
            assert_array_equal(result, value)

    def test_small_published_slice_does_not_pin_large_owner(self):
        source = frozen(np.arange(100000.))
        for result in (frozen(source[10:13]), snapshot(source[10:13], 'x')):
            self.assertFalse(np.shares_memory(result, source))
            owner = result
            while type(owner) is np.ndarray:
                owner = owner.base
            self.assertIs(type(owner), bytes)
            self.assertEqual(len(owner), 24)
            assert_array_equal(result, [10., 11., 12.])

    def test_noncontiguous_and_non_native_data_are_copied(self):
        source = frozen(np.arange(100.))[::2]
        result = read_array(source, 'x')
        self.assertFalse(np.shares_memory(source, result))
        self.assertTrue(result.flags.c_contiguous)
        swapped = np.arange(20.).astype('>f8')
        assert_array_equal(snapshot(swapped, 'x'), np.arange(20.))

    def test_subclasses_are_not_trusted_for_zero_copy(self):
        class Other(np.ndarray):
            pass
        source = frozen(np.arange(8.)).view(Other)
        result = read_array(source, 'x')
        self.assertFalse(np.shares_memory(source, result))

    def test_invalid_immutable_values_still_fail(self):
        for bad in (np.frombuffer(np.array([np.nan]).tobytes()),
                    np.frombuffer(b'', dtype=np.float64)):
            for fn in (read_array, snapshot):
                with self.assertRaises(TectonicsError):
                    fn(bad, 'x')
        with self.assertRaises(TectonicsError):
            read_array(frozen([-1.]), 'x', nonnegative=True)
        with self.assertRaises(TectonicsError):
            read_array(frozen([1.]), 'x', ndim=2)

    def test_masks_and_bool_sequences_rejected(self):
        for bad in (np.ma.array([1.], mask=False), [True, 2.], [[np.ma.masked]], []):
            for fn in (read_array, snapshot):
                with self.assertRaises(TectonicsError): fn(bad, 'x')

    def test_refreezing_immutable_result_does_not_duplicate_payload(self):
        source = frozen(np.arange(100.))
        again = frozen(source)
        self.assertTrue(np.shares_memory(source, again))
        self.assertIsNot(source, again)
        with self.assertRaises(ValueError): again.setflags(write=True)

    def test_copy_contracts_do_not_change_calculations(self):
        h = np.linspace(1., 3., 64)
        u = np.sin(np.arange(64.))
        g = PeriodicGrid1D(64, 64.)
        for arrays in ((h,u), (frozen(h),frozen(u))):
            result = advect_thickness(*arrays, g, .2)
            expected = advect_thickness(h,u,g,.2)
            self.assertEqual(result.thickness_m.tobytes(), expected.thickness_m.tobytes())
        op = PeriodicFlexure(g, ELASTIC)
        self.assertEqual(op.solve(h).tobytes(), op.solve(frozen(h)).tobytes())
        self.assertEqual(half_space_temperature(h,1.,THERMAL).tobytes(),
                         half_space_temperature(frozen(h),1.,THERMAL).tobytes())
        r = Rotation.from_axis_angle([1,2,3], .3)
        p = np.arange(30.).reshape(10,3)
        self.assertEqual(r.apply(p).tobytes(), r.apply(frozen(p)).tobytes())

    def test_concurrent_calls_do_not_share_mutable_scratch(self):
        h = frozen(np.linspace(0., 1., 256))
        u = frozen(np.sin(np.arange(256.)))
        g = PeriodicGrid1D(256,256.)
        expected = advect_thickness(h,u,g,.2).thickness_m.tobytes()
        with ThreadPoolExecutor(4) as pool:
            outputs = list(pool.map(lambda _:advect_thickness(h,u,g,.2),range(12)))
        for result in outputs:
            self.assertEqual(result.thickness_m.tobytes(),expected)
            with self.assertRaises(ValueError):result.thickness_m.setflags(write=True)
        self.assertFalse(np.shares_memory(outputs[0].thickness_m,outputs[1].thickness_m))


class CachedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ArrayStore(Path(self.tmp.name)/'cache.db', StoreLimits(1024,1<<20,4<<20))
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)

    def test_cooling_wrapper_and_kernel_share_one_input_snapshot(self):
        import atlas_tectonics.thermal as thermal
        observed = []
        original = thermal.array
        def capture(value, *args, **kwargs):
            result = original(value,*args,**kwargs)
            observed.append(np.shares_memory(value, result))
            return result
        with mock.patch.object(thermal,'array',side_effect=capture):
            result = reuse.cached_temperature(np.arange(20.),1.,THERMAL,store=self.store,cache_policy=CachePolicy(mode="always"))
        self.assertEqual(observed,[True,True])
        assert_array_equal(result, half_space_temperature(np.arange(20.),1.,THERMAL))

    def test_flexure_snapshot_is_not_recopied(self):
        import atlas_tectonics.flexure as flexure
        op = PeriodicFlexure(PeriodicGrid1D(16,16),ELASTIC)
        original = flexure.array
        observed = []
        def capture(value,*args,**kwargs):
            result = original(value,*args,**kwargs)
            observed.append(np.shares_memory(value,result))
            return result
        with mock.patch.object(flexure,'array',side_effect=capture):
            reuse.cached_flexure(op,np.arange(16.),store=self.store,cache_policy=CachePolicy(mode="always"))
        self.assertEqual(observed,[True])

    def test_caller_mutation_after_capture_does_not_change_hash_or_compute(self):
        h = np.arange(16.)
        saved = h.copy()
        op = PeriodicFlexure(PeriodicGrid1D(16,16),ELASTIC)
        original = PeriodicFlexure.solve
        def calculate(instance, captured, **kwargs):
            h[:] = 999.
            return original(instance,captured,**kwargs)
        with mock.patch.object(PeriodicFlexure,'solve',calculate):
            result = reuse.cached_flexure(op,h,store=self.store,cache_policy=CachePolicy(mode="always"))
        assert_array_equal(result,original(op,saved))
        with self.assertRaises(ValueError):result.setflags(write=True)


class OptionalNativeImportTests(unittest.TestCase):
    def test_reference_does_not_require_numba_and_explicit_native_refuses_absence(self):
        import os, subprocess, sys
        code = """import builtins
real = builtins.__import__
def blocked(name, *a, **kw):
    if name == 'numba' or name.startswith('numba.'):
        raise ImportError('deliberately unavailable')
    return real(name, *a, **kw)
builtins.__import__ = blocked
import numpy as np
from atlas_tectonics import advect_thickness, PeriodicGrid1D, TectonicsError
g = PeriodicGrid1D(8,8)
advect_thickness(np.ones(8),np.zeros(8),g,1,backend="reference")
try:
    advect_thickness(np.ones(8),np.zeros(8),g,1,backend='numba')
except TectonicsError as exc:
    assert 'unavailable' in str(exc)
else:
    raise AssertionError('silently fell back')
"""
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),
                   PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable,'-B','-c',code], env=env,
                                capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
