"""Opt-in native verification: run via verify.py --native, no installation."""
import math
from fractions import Fraction
import pickle
from unittest import mock
import unittest

import numpy as np
from numpy.testing import assert_array_equal
import test_foundations as foundations
from atlas_tectonics import advect_thickness, PeriodicGrid1D, TectonicsError
from atlas_tectonics._validation import frozen
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics._transport_native import positive_sum, advance


def bit_equal(test, actual, expected):
    test.assertEqual(actual.thickness_m.tobytes(), expected.thickness_m.tobytes())
    test.assertEqual(actual.face_flux_m2_s.tobytes(), expected.face_flux_m2_s.tobytes())
    for attr in ('solid_volume_per_width_before_m2','solid_volume_per_width_after_m2',
                 'balance_residual_m2','maximum_outflow_fraction'):
        test.assertEqual(float(getattr(actual,attr)).hex(),float(getattr(expected,attr)).hex(),attr)


class ExistingTransportTestsNative(foundations.TransportTests):
    """Run every existing transport contract against the actual compiled path."""
    def setUp(self):
        patcher = mock.patch.object(foundations,'advect_thickness',
            lambda *a,**k: advect_thickness(*a,**k,backend='numba'))
        patcher.start()
        self.addCleanup(patcher.stop)


class ExactSumTests(unittest.TestCase):
    def test_rounding_ties_and_subnormal_carries(self):
        cases = [[1., 2.**-53], [1.,2.**-53,2.**-1000],
                 [float.fromhex('0x1.0000000000001p+0'),2.**-53],
                 [np.nextafter(0.,1.)]*257,
                 [np.finfo(float).tiny,-0.,np.nextafter(0.,1.)],
                 [0.,-0.], [np.finfo(float).max]]
        for numbers in cases:
            with self.subTest(numbers=numbers[:3]):
                v = np.array(numbers,dtype=np.float64)
                exact = float(sum((Fraction.from_float(float(x)) for x in v),Fraction()))
                self.assertEqual(positive_sum(v).hex(),exact.hex())
                self.assertEqual(positive_sum(v).hex(),math.fsum(v).hex())

    def test_wide_exponent_exact_comparisons(self):
        rng = np.random.default_rng(64170)
        for i in range(200):
            v = np.ldexp(rng.uniform(.5,1.,128),rng.integers(-1074,1010,128))
            exact = float(sum((Fraction.from_float(float(x)) for x in v),Fraction()))
            self.assertEqual(positive_sum(v).hex(),exact.hex(),i)
            self.assertEqual(positive_sum(v).hex(),math.fsum(v).hex(),i)

    def test_overflow_and_invalid_data_refused(self):
        for v in (np.array([np.finfo(float).max]*2),):
            with self.assertRaises(OverflowError):positive_sum(v)
            with self.assertRaises(OverflowError):math.fsum(v)
        for v in (np.array([-1.]),np.array([np.nan]),np.array([np.inf])):
            with self.assertRaises(ValueError):positive_sum(v)


class NativeTransportTests(unittest.TestCase):
    def test_varied_fields_bit_equal(self):
        rng = np.random.default_rng(11684)
        for case in range(100):
            n = int(rng.integers(5,2049))
            h = np.ldexp(rng.uniform(.5,1.,n),rng.integers(-1050,800,n))
            u = rng.uniform(-1.,1.,n)
            grid = PeriodicGrid1D(n,float(n))
            bit_equal(self,advect_thickness(h,u,grid,.49,backend='numba'),
                      advect_thickness(h,u,grid,.49,backend="reference"))

    def test_signed_zeros_and_zero_duration(self):
        h = np.array([0.,-0.,1.,2.,3.,0.,0.,-0.])
        u = np.array([-0.,0.,1.,-1.,0.,0.,-0.,0.])
        grid = PeriodicGrid1D(8,8)
        for dt in (0.,-0.,.2):
            bit_equal(self,advect_thickness(h,u,grid,dt,backend='numba'),advect_thickness(h,u,grid,dt,backend="reference"))

    def test_courant_boundary_and_overflow_refusals(self):
        grid = PeriodicGrid1D(8,8.)
        for dt in (1., np.nextafter(1.,0.)):
            bit_equal(self,advect_thickness(np.ones(8),np.ones(8),grid,dt,backend='numba'),
                      advect_thickness(np.ones(8),np.ones(8),grid,dt,backend="reference"))
        for dt in (np.nextafter(1.,np.inf), np.inf, True, -1.):
            with self.assertRaises(TectonicsError):
                advect_thickness(np.ones(8),np.ones(8),grid,dt,backend='numba')
        for backend in ('reference','numba'):
            with self.assertRaises(TectonicsError):
                advect_thickness(np.full(8,1e308),np.zeros(8),grid,0,backend=backend)
            with self.assertRaises(TectonicsError):
                advect_thickness(np.full(8,1e307),np.full(8,1e308),grid,0,backend=backend)

    def test_nonunit_spacing_and_strided_inputs(self):
        h = np.linspace(1,100,64)[::2]
        u = np.sin(np.arange(64.))[::2]
        g = PeriodicGrid1D(32,77.)
        bit_equal(self,advect_thickness(h,u,g,.2,backend='numba'),advect_thickness(h,u,g,.2,backend="reference"))

    def test_freeze_restore_and_input_ownership(self):
        h=np.arange(16.);u=np.sin(h);g=PeriodicGrid1D(16,16.)
        out=advect_thickness(h,u,g,.2,backend='numba')
        expected=out.thickness_m.tobytes();h[:]=900;u[:]=900
        self.assertEqual(out.thickness_m.tobytes(),expected)
        restored=pickle.loads(pickle.dumps(out))
        self.assertEqual(restored.backend,'numba')
        self.assertEqual(restored.numerical_method,out.numerical_method)
        with self.assertRaises(ValueError):restored.thickness_m.setflags(write=True)
        with self.assertRaises(ValueError):out.face_flux_m2_s.setflags(write=True)

    def test_failed_candidate_and_budget_leave_accepted_state_unchanged(self):
        h=frozen(np.arange(16.));u=frozen(np.ones(16));g=PeriodicGrid1D(16,16.)
        before=h.tobytes();budget=WorkBudget(100000)
        with self.assertRaises(TectonicsError):advect_thickness(h,u,g,2,budget=budget,backend='numba')
        self.assertEqual(h.tobytes(),before);self.assertEqual(budget.reserved_bytes,0)
        with self.assertRaises(MemoryLimitError):advect_thickness(h,u,g,.2,budget=WorkBudget(1),backend='numba')
        self.assertEqual(h.tobytes(),before)

    def test_parallel_calls_have_private_outputs(self):
        from concurrent.futures import ThreadPoolExecutor
        h=frozen(np.linspace(1,2,256));u=frozen(np.sin(np.arange(256.)));g=PeriodicGrid1D(256,256.)
        expected=advect_thickness(h,u,g,.2,backend="reference")
        with ThreadPoolExecutor(4) as pool:
            results=list(pool.map(lambda _:advect_thickness(h,u,g,.2,backend='numba'),range(8)))
        for value in results:bit_equal(self,value,expected)
        self.assertFalse(np.shares_memory(results[0].thickness_m,results[1].thickness_m))

    def test_compiler_contract_and_no_disk_cache(self):
        advect_thickness(np.ones(8),np.zeros(8),PeriodicGrid1D(8,8),1.,backend='numba')
        self.assertTrue(advance.nopython_signatures)
        self.assertFalse(advance.targetoptions['fastmath'])
        self.assertTrue(advance.targetoptions['nogil'])
        self.assertNotIn('parallel',advance.targetoptions)
        for sig in advance.signatures:
            llvm=advance.inspect_llvm(sig)
            self.assertNotIn('fadd fast ',llvm)
            self.assertNotIn('fmul fast ',llvm)
            self.assertNotIn('llvm.fma.',llvm)

    def test_unknown_backend_never_falls_back(self):
        with self.assertRaises(TectonicsError):
            advect_thickness(np.ones(8),np.zeros(8),PeriodicGrid1D(8,8),1,backend='gpu')
