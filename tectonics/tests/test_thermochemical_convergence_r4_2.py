"""Additional independent transport/coupling and numerical-range checks.
SPDX-License-Identifier: AGPL-3.0-only
"""
import unittest,math
from dataclasses import replace
from decimal import Decimal,localcontext
import numpy as np
from scipy.integrate import solve_ivp
from numpy.testing import assert_allclose
from atlas_tectonics import PreparedThermochemical2D,TectonicsError
from atlas_tectonics.thermochemical import _weighted_source,_attenuated_modes,_Diffusion2D
from thermochemical_fixtures import problem,initial,rotation_experiment,independent_two_by_two_rhs


class Convergence(unittest.TestCase):
    def test_rotating_compact_bump_refines_without_clipping(self):
        rows=[rotation_experiment(n) for n in (24,48,96)]
        for a,b in zip(rows,rows[1:]):self.assertGreater(a['mean_absolute_error']/b['mean_absolute_error'],3.)
        for r in rows:
            self.assertGreaterEqual(r['minimum'],0);self.assertLessEqual(r['maximum'],1)
            self.assertLess(abs(r['volume_error']),2e-16)
    def test_coupled_temporal_refinement_independent_ODE(self):
        p=problem(2,k=.2,contrast=.05,gravity=(1.,-2.));s=initial(p)
        y=np.concatenate((s.array('temperature_k').ravel(),s.array('composition').ravel()))
        end=1.;sol=solve_ivp(lambda t,q:independent_two_by_two_rhs(p,q),(0,end),y,method='DOP853',rtol=3e-13,atol=1e-13)
        self.assertTrue(sol.success);ref=sol.y[:,-1];errors=[]
        for steps in (4,8,16):
            q=s
            with PreparedThermochemical2D(p) as plan:
                for _ in range(steps):q=plan.advance(q,end/steps,source='coupled refinement').state
            actual=np.concatenate((q.array('temperature_k').ravel(),q.array('composition').ravel()))
            errors.append(float(np.max(abs(actual-ref))))
        for a,b in zip(errors,errors[1:]):self.assertGreater(a/b,3.7);self.assertLess(a/b,4.4)
    def test_scaled_source_impulse_not_multiplied_before_decay(self):
        a=np.array([[1e200]]);w=np.array([[1e-200]])
        assert_allclose(_weighted_source(a,w,1e200),1e200,rtol=4e-16)
    def test_subnormal_source_weight_combines_before_rounding(self):
        a=np.array([[1e200]]);w=np.array([[.5]]);dt=np.nextafter(0.,1.)
        with localcontext() as c:
            c.prec=100;expected=float(Decimal.from_float(1e200)*Decimal('.5')*Decimal.from_float(dt))
        assert_allclose(_weighted_source(a,w,dt),expected,rtol=4e-16,atol=0)
    def test_attenuation_preserves_large_modal_tail(self):
        a=np.array([[1e300]]);x=np.array([[800.]])
        with localcontext() as c:
            c.prec=90;expected=float(Decimal.from_float(1e300)*(-Decimal(800)).exp())
        assert_allclose(_attenuated_modes(a,x,np.exp(-x)),expected,rtol=2e-13,atol=0)
    def test_genuine_source_overflow_refused(self):
        with self.assertRaises(TectonicsError):_weighted_source(np.array([[1e308]]),np.array([[1.]]),1e308)

if __name__=='__main__':unittest.main()
