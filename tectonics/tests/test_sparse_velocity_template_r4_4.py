"""Fixed sparse velocity-block structure reuse for R4.4.

SPDX-License-Identifier: AGPL-3.0-only
The tests independently reconstruct B.T @ diag(eta) @ B; they do not accept the
new contribution table as their mathematical oracle.
"""
import unittest
from unittest import mock
import numpy as np
from scipy.sparse import diags

import atlas_tectonics as at
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.variable_stokes import _StressMACOperator, check_variable_support
from atlas_tectonics import _mechanics_native
from variable_stokes_fixtures import unit_box, unit_scales, analytic_variable, request


def independent_velocity(op, cell, vertex):
    centre=diags(2*cell.ravel(),format='csr')
    shear=diags(vertex.ravel(),format='csr')
    return (op.bx.T@centre@op.bx+op.bz.T@centre@op.bz+
            op.shear.T@shear@op.shear).tocsc()


class VelocityTemplateTests(unittest.TestCase):
    def operator(self,nx=7,nz=5,width=2.,height=1.,compiled=True):
        b=unit_box(nx,nz,width,height);hx,hz=check_variable_support(b,unit_scales())
        return _StressMACOperator(b,hx,hz,compiled=compiled)

    def test_template_matches_independent_sparse_formula(self):
        rng=np.random.default_rng(361)
        for shape in ((2,2),(7,5),(5,9),(13,8)):
            op=self.operator(*shape,width=3.25,height=.7)
            c=np.exp(rng.uniform(-5,5,(op.nz,op.nx)))
            v=np.exp(rng.uniform(-5,5,(op.nz-1,op.nx-1)))
            op.set_viscosity(c,v)
            got=op.velocity_matrix();expected=independent_velocity(op,c,v)
            np.testing.assert_allclose(got.toarray(),expected.toarray(),rtol=4e-16,atol=2e-11)
            self.assertTrue(got.has_sorted_indices);self.assertTrue(got.has_canonical_format)

    def test_compiled_template_matches_independent_direct_assembly_exactly(self):
        rng=np.random.default_rng(362);direct=self.operator(9,6,compiled=False);native=self.operator(9,6,compiled=True)
        c=np.exp(rng.uniform(-3,3,(6,9)));v=np.exp(rng.uniform(-3,3,(5,8)))
        direct.set_viscosity(c,v);native.set_viscosity(c,v)
        np.testing.assert_array_equal(native.velocity_matrix().toarray(),direct.velocity_matrix().toarray())

    def test_template_is_read_only_and_viscosity_independent(self):
        op=self.operator();names=('_velocity_indices','_velocity_indptr','_velocity_term_indptr','_velocity_term_component',
               '_velocity_term_coefficient','_velocity_term_left','_velocity_term_right')
        before={name:getattr(op,name).tobytes() for name in names}
        self.assertTrue(all(not getattr(op,name).flags.writeable for name in names))
        for factor in (1.,17.,.03125):
            op.set_viscosity(np.full((op.nz,op.nx),factor),np.full((op.nz-1,op.nx-1),factor*2))
            op.velocity_matrix()
        self.assertEqual(before,{name:getattr(op,name).tobytes() for name in names})

    def test_each_matrix_gets_fresh_numerical_data(self):
        op=self.operator();c=np.ones((op.nz,op.nx));v=np.ones((op.nz-1,op.nx-1))
        op.set_viscosity(c,v);first=op.velocity_matrix();saved=first.data.copy()
        op.set_viscosity(c*9,v*7);second=op.velocity_matrix()
        self.assertFalse(np.shares_memory(first.data,second.data))
        np.testing.assert_array_equal(first.data,saved)
        self.assertGreater(np.max(np.abs(first.data-second.data)),0.)

    def test_retained_template_has_declared_linear_memory_bound(self):
        for nx,nz in ((2,2),(7,5),(16,16),(64,32)):
            op=self.operator(nx,nz)
            self.assertLessEqual(op.velocity_template_nbytes,768*nx*nz+8)

    def test_native_fill_owns_result_and_uses_current_coefficients(self):
        op=self.operator(6,4,compiled=True);c=np.ones((4,6));v=np.ones((3,5))
        op.set_viscosity(c,v);a=op.velocity_matrix();old=a.data.copy()
        op.set_viscosity(c*3,v*5);b=op.velocity_matrix()
        self.assertFalse(np.shares_memory(a.data,b.data));np.testing.assert_array_equal(a.data,old)
        np.testing.assert_allclose(b.toarray(),independent_velocity(op,c*3,v*5).toarray(),rtol=5e-16,atol=2e-12)

    def test_factor_reuse_policy_is_not_broadened(self):
        b=unit_box(6);a=analytic_variable(b);pol=at.NonlinearStokesPolicy(ilu_fill_factor=17.)
        with at.PreparedVariableStokes2D(b,unit_scales(),policy=pol,budget=WorkBudget(128<<20)) as plan:
            names=('_velocity_indices','_velocity_indptr','_velocity_term_indptr','_velocity_term_component',
                   '_velocity_term_coefficient','_velocity_term_left','_velocity_term_right')
            structure={name:getattr(plan._op,name).tobytes() for name in names}
            plan.solve(*a[:4],**request(b));s1=plan.statistics().copy()
            plan.solve(*a[:4],**request(b));s2=plan.statistics().copy()
            changed=(a[2]*1.0001,a[3]*1.0001)
            plan.solve(a[0],a[1],*changed,**request(b));s3=plan.statistics().copy()
            self.assertEqual(structure,{name:getattr(plan._op,name).tobytes() for name in names})
        self.assertGreater(s2['factor_reuses'],s1['factor_reuses'])
        self.assertGreater(s3['factor_builds'],s2['factor_builds'])

    def test_template_build_is_admitted_and_released_on_failure(self):
        b=unit_box(8);budget=WorkBudget(1)
        with self.assertRaises(MemoryLimitError):
            at.PreparedVariableStokes2D(b,unit_scales(),budget=budget)
        self.assertEqual(budget.reserved_bytes,0)

    def test_native_fill_callable_change_invalidates_context(self):
        b=unit_box(4);pol=at.NonlinearStokesPolicy(ilu_fill_factor=17.)
        with at.PreparedVariableStokes2D(b,unit_scales(),policy=pol,budget=WorkBudget(128<<20)) as plan:
            original=_mechanics_native.weighted_velocity_data
            with mock.patch.object(_mechanics_native,'weighted_velocity_data',lambda *args: original(*args)):
                a=analytic_variable(b)
                with self.assertRaises(at.TectonicsError):plan.solve(*a[:4],**request(b))

    def test_direct_reference_remains_independent_of_native_fill(self):
        b=unit_box(5);a=analytic_variable(b);pol=at.NonlinearStokesPolicy(method='direct')
        with mock.patch.object(_mechanics_native,'weighted_velocity_data',side_effect=AssertionError):
            with at.PreparedVariableStokes2D(b,unit_scales(),policy=pol,budget=WorkBudget(128<<20)) as plan:
                result=plan.solve(*a[:4],**request(b))
        self.assertTrue(np.isfinite(result.array('pressure_pa')).all())


if __name__=='__main__':unittest.main()
