"""Independent native-operator, buffer, runtime and preparation checks for dev33.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError, ThreadPoolExecutor
import threading
import unittest
from unittest import mock
import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from atlas_tectonics import PreparedVariableStokes2D, NonlinearStokesPolicy, TectonicsError
from atlas_tectonics import _mechanics_native as native, reuse
from atlas_tectonics.variable_stokes import _StressMACOperator
from atlas_tectonics.resources import WorkBudget
from variable_stokes_fixtures import unit_box, unit_scales, analytic_variable, request


class FusedOperator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):native.prepare()

    def pair(self,nx=7,nz=5,hx=.37,hz=.13,contrast=4.):
        box=unit_box(nx,nz);ref=_StressMACOperator(box,hx,hz)
        fast=_StressMACOperator(box,hx,hz,compiled=True)
        rng=np.random.default_rng(718);c=np.exp(rng.uniform(-contrast,contrast,(nz,nx)))
        v=np.exp(rng.uniform(-contrast,contrast,(nz-1,nx-1)))
        for op in (ref,fast):op.set_viscosity(c,v)
        return ref,fast,rng.normal(size=ref.n)

    def test_rectangular_full_action_matches_independent_numpy(self):
        for nx,nz in ((2,2),(2,7),(9,2),(3,5),(6,9),(16,16),(31,19)):
            for contrast in (0.,4.,12.):
                with self.subTest(nx=nx,nz=nz,contrast=contrast):
                    ref,fast,x=self.pair(nx,nz,contrast=contrast)
                    assert_array_equal(fast.matvec(x),ref.matvec(x))

    def test_minimum_and_thin_grid_basis_including_boundaries(self):
        for nx,nz in ((2,2),(2,4),(4,2),(5,3)):
            ref,fast,x=self.pair(nx,nz)
            for k in range(ref.n):
                x.fill(0.);x[k]=1.
                assert_array_equal(fast.matvec(x),ref.matvec(x))

    def test_independent_sparse_assembly(self):
        ref,fast,x=self.pair()
        assert_allclose(fast.matvec(x),ref.sparse_reference()@x,rtol=3e-14,atol=3e-12)

    def test_nonunit_and_anisotropic_spacing(self):
        for hx,hz in ((.013,.71),(12.,.002),(1e-30,1e-30),(1e30,1e30)):
            ref,fast,x=self.pair(hx=hx,hz=hz)
            assert_array_equal(fast.matvec(x),ref.matvec(x))

    def test_extreme_finite_vector_scales(self):
        ref,fast,x=self.pair()
        for scale in (1e-240,1e-120,1.,1e120,1e240):
            assert_array_equal(fast.matvec(x*scale),ref.matvec(x*scale))

    def test_gauge_reduction_retains_numpy_sum(self):
        ref,fast,x=self.pair(33,17)
        x.fill(0.);x[ref.nv:-1]=np.tile([1e20,1.,-1e20],ref.np//3+1)[:ref.np]
        assert_array_equal(fast.matvec(x),ref.matvec(x))

    def test_pure_gauge_multiplier(self):
        ref,fast,x=self.pair();x.fill(0.);x[-1]=3.
        out=fast.matvec(x)
        assert_array_equal(out[:ref.nv],0.);assert_array_equal(out[ref.nv:-1],3.*ref.c)
        self.assertEqual(out[-1],0.)

    def test_inputs_and_viscosity_are_not_modified(self):
        ref,fast,x=self.pair();before=[a.copy() for a in (x,fast.eta_c,fast.eta_v)]
        fast.matvec(x)
        for old,now in zip(before,(x,fast.eta_c,fast.eta_v)):assert_array_equal(old,now)

    def test_read_only_and_strided_inputs(self):
        ref,fast,x=self.pair();back=np.zeros(2*x.size);back[::2]=x;x=back[::2];x.flags.writeable=False
        c=fast.eta_c[:,::-1];v=fast.eta_v[:,::-1];c.flags.writeable=False;v.flags.writeable=False
        ref.set_viscosity(c,v);fast.set_viscosity(c,v)
        assert_array_equal(fast.matvec(x),ref.matvec(x))

    def test_returned_buffers_are_independent_and_writable(self):
        ref,fast,x=self.pair();first=fast.matvec(x);keep=first.copy();second=fast.matvec(-x)
        self.assertFalse(np.shares_memory(first,second));self.assertFalse(np.shares_memory(first,x))
        self.assertEqual(first.dtype,np.float64);self.assertTrue(first.flags.c_contiguous)
        second.fill(1.);assert_array_equal(first,keep);first.fill(99.)
        assert_array_equal(fast.matvec(x),ref.matvec(x))

    def test_changed_viscosity_is_consumed_immediately(self):
        ref,fast,x=self.pair();old=fast.matvec(x);c=fast.eta_c.copy();v=fast.eta_v.copy();c[0,0]*=7.;v[-1,-1]*=.1
        ref.set_viscosity(c,v);fast.set_viscosity(c,v)
        self.assertFalse(np.array_equal(old,fast.matvec(x)))
        assert_array_equal(fast.matvec(x),ref.matvec(x))

    def test_no_shared_scratch_between_concurrent_native_calls(self):
        ref,fast,x=self.pair(17,23);inputs=[x*(i+1) for i in range(4)]
        with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(fast.matvec,inputs))
        for y,inp in zip(out,inputs):assert_array_equal(y,ref.matvec(inp))

    def test_numpy_residual_reference_is_not_routed_through_native(self):
        ref,_,x=self.pair()
        with mock.patch.object(native,'stress_saddle',side_effect=AssertionError('native called')):
            out=ref.matvec(x)
        self.assertTrue(np.isfinite(out).all())

    def test_scipy_column_and_matrix_callbacks(self):
        from scipy.sparse.linalg import LinearOperator
        ref,fast,x=self.pair()
        a=LinearOperator((fast.n,fast.n),matvec=fast.matvec,dtype=np.float64)
        assert_array_equal(a.matvec(x[:,None]),ref.matvec(x)[:,None])
        matrix=np.column_stack((x,2*x,-x))
        assert_array_equal(a.matmat(matrix),np.column_stack([ref.matvec(matrix[:,i]) for i in range(3)]))

    def test_wrong_vector_length_refused_before_native_access(self):
        _,fast,_=self.pair()
        with mock.patch.object(native,'stress_saddle',side_effect=AssertionError('must not enter native')):
            for n in (fast.n-1,fast.n+1):
                with self.assertRaises(ValueError):fast.matvec(np.zeros(n))

    def test_nopython_signature_and_no_fastmath(self):
        self.assertTrue(native.stress_saddle.nopython_signatures)
        self.assertFalse(native.stress_saddle.targetoptions['fastmath'])
        self.assertTrue(native.stress_saddle.targetoptions['nogil'])
        self.assertNotIn('parallel',native.stress_saddle.targetoptions)
        self.assertEqual(native.stress_saddle._cache.__class__.__name__,'NullCache')


class PreparedNativeContracts(unittest.TestCase):
    def setUp(self):
        self.box=unit_box(4);self.values=analytic_variable(self.box);self.budget=WorkBudget(128<<20)
    def plan(self,**kw):return PreparedVariableStokes2D(self.box,unit_scales(),budget=self.budget,**kw)
    def solve(self,p):return p.solve(*self.values[:4],**request(self.box))

    def test_gmres_uses_native_and_binds_numba_runtime(self):
        with self.plan() as p:
            self.assertIs(p._op._native,native);self.assertEqual(p._context.backend,'numba');self.solve(p)
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_explicit_direct_reference_stays_independent(self):
        with self.plan(policy=NonlinearStokesPolicy(method='direct')) as p:
            self.assertIsNone(p._op._native);self.assertEqual(p._context.backend,'scipy');self.solve(p)
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_dispatcher_replacement_is_refused(self):
        with self.plan() as p:
            with mock.patch.object(native,'stress_saddle',lambda *args:None):
                with self.assertRaises(TectonicsError):self.solve(p)
            self.solve(p)

    def test_jit_option_change_is_refused(self):
        with self.plan() as p:
            with mock.patch.dict(native.stress_saddle.targetoptions,{'fastmath':True}):
                with self.assertRaises(TectonicsError):self.solve(p)
            self.solve(p)

    def test_new_native_callable_membership_is_refused(self):
        with self.plan() as p:
            with mock.patch.object(native,'unregistered_callable',lambda:0,create=True):
                with self.assertRaises(TectonicsError):self.solve(p)

    def test_compilation_failure_releases_admission_and_never_falls_back(self):
        with mock.patch.object(native,'prepare',side_effect=RuntimeError('test compiler failure')):
            with self.assertRaisesRegex(RuntimeError,'compiler failure'):self.plan()
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_disabled_jit_is_refused(self):
        with mock.patch.object(native.numba.config,'DISABLE_JIT',1):
            with self.assertRaisesRegex(ImportError,'no fallback'):self.plan()
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_pre_cancelled_preparation_does_not_compile(self):
        cancel=threading.Event();cancel.set()
        with mock.patch.object(native,'prepare',side_effect=AssertionError('must not compile')):
            with self.assertRaises(CancelledError):self.plan(cancel=cancel)
        self.assertEqual(self.budget.reserved_bytes,0)

    def test_native_and_compiler_inventory_is_recorded(self):
        signatures,_,_=reuse._callable_inventory('numba')
        self.assertIn('atlas_tectonics._mechanics_native.stress_saddle',signatures)
        record=reuse._runtime_record('numba')
        self.assertIn('numba_helper',record['binaries']);self.assertIn('llvmlite',record['binaries'])

    def test_no_hidden_request_history_after_different_force(self):
        with self.plan() as p:
            first=self.solve(p);p.solve(self.values[0]*1.5,*self.values[1:4],**request(self.box));again=self.solve(p)
            self.assertEqual(first.result_id,again.result_id)
        self.assertEqual(self.budget.reserved_bytes,0)
