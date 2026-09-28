"""Small independent controls; no scientific campaign on test import."""
import dataclasses
from decimal import Decimal as D, localcontext
import importlib.util
import math
from pathlib import Path
import sys
import unittest

PATH = Path(__file__).resolve().parents[1]/"tools/check_i01_elastic_memory.py"
SPEC = importlib.util.spec_from_file_location("i01_elastic_memory", PATH)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
KW = {"kinematics": m.KINEMATICS}


def oracle(g, eta, dt, s, e):
    """80-digit direct exponential integrals, independent of the production series/variance."""
    with localcontext() as ctx:
        ctx.prec = 80
        g, eta, dt, s, e = map(lambda x: D.from_float(float(x)), (g, eta, dt, s, e))
        t = eta/g
        a = (-dt/t).exp()
        steady, b = 2*eta*e, s-2*eta*e
        end = steady+b*a
        work = 2*e*(steady*dt+b*t*(1-a))
        heat = (steady*steady*dt+2*steady*b*t*(1-a)+b*b*t*(1-a*a)/2)/eta
        return tuple(map(float, (end, work, heat)))


class MemoryTests(unittest.TestCase):
    def close(self, a, b, rel=2e-12):
        self.assertLessEqual(abs(a-b), rel*max(abs(a), abs(b), 1e-290), (a,b))

    def test_independent_integrals_across_relaxation_scales(self):
        for z in (1e-12, 1e-8, .01, .5, math.nextafter(.5, math.inf), 1., 10., 1000.):
            for s in (0., .003, -.003):
                with self.subTest(z=z, s=s):
                    dt, e = 2*z, .001/(2*z)
                    r = m.Prepared(3., 6., dt).advance(m.State(s, 0., 0., 3.), e, **KW)
                    expected = oracle(3., 6., dt, s, e)
                    self.close(r["state"].stress_pa, expected[0])
                    self.close(r["heat_j_m3"], expected[2])
                    # Work can almost cancel during reversal. Round-off is bounded
                    # by gross stress work, not relative to that near-zero net.
                    gross_work = 2*abs(dt*e)*(abs(s)+2*3*abs(dt*e))
                    self.assertLessEqual(abs(r["work_j_m3"]-expected[1]), 2e-12*gross_work)

    def test_relaxation_releases_stored_energy(self):
        state = m.State(1e7, .2, .3, 3e10)
        r = m.Prepared(3e10, 3e21, 1e11).advance(state, 0., **KW)
        self.close(r["state"].stress_pa, state.stress_pa/math.e)
        self.close(r["heat_j_m3"], state.energy()*-math.expm1(-2))
        self.assertEqual(r["work_j_m3"], 0.)

    def test_loading_tiny_interval_heat_is_not_lost(self):
        dt, e, g, eta = 1e-9, .001, 3., 6.
        r = m.Prepared(g, eta, dt).advance(m.State(0., 0., 0., g), e, **KW)
        self.close(r["heat_j_m3"], 4*g*g*e*e*dt**3/(3*eta), 1e-9)
        self.assertGreater(r["heat_j_m3"], 0.)

    def test_steady_stress(self):
        r = m.Prepared(3., 6., 2.).advance(m.State(.012, 0., 0., 3.), .001, **KW)
        self.close(r["state"].stress_pa, .012)
        self.assertEqual(r["stored_change_j_m3"], 0.)
        self.close(r["heat_j_m3"], 4*6*.001**2*2)

    def test_elastic_limit_and_rotation_do_not_create_heat(self):
        state = m.State(.003, 0., .4, 3.)
        r = m.Prepared(3., None, 1.).advance(state, 0., math.pi/4, **KW)
        self.close(r["state"].tensor()[0][1], .003)
        self.assertEqual(r["state"].energy(), state.energy())
        self.assertEqual(r["heat_j_m3"], 0.)
        self.assertEqual(r["work_j_m3"], 0.)

    def test_loading_elastic_limit(self):
        r = m.Prepared(3., None, 1.).advance(m.State(.003, 0., 0., 3.), .001, **KW)
        self.close(r["state"].stress_pa, .009)
        self.close(r["work_j_m3"], (.009**2-.003**2)/6)
        self.assertEqual(r["heat_j_m3"], 0.)

    def test_negative_work_is_allowed_while_heat_positive(self):
        r = m.Prepared(3., 6., .1).advance(m.State(.03, 0., 0., 3.), -.001, **KW)
        self.assertLess(r["work_j_m3"], 0.)
        self.assertGreater(r["heat_j_m3"], 0.)

    def test_subdivision_preserves_state_and_accounts(self):
        initial = m.State(.012, .2, -.1, 3.)
        whole = m.Prepared(3., 6., 2.).advance(initial, -.001, .8, **KW)
        partial, work, heat = initial, [], []
        op = m.Prepared(3., 6., .2)
        for _ in range(10):
            r = op.advance(partial, -.001, .08, **KW)
            partial = r["state"]
            work.append(r["work_j_m3"])
            heat.append(r["heat_j_m3"])
        for name in ("stress_pa", "axis_rad", "log_stretch", "time_s"):
            self.close(getattr(partial,name), getattr(whole["state"],name))
        self.close(math.fsum(work), whole["work_j_m3"])
        self.close(math.fsum(heat), whole["heat_j_m3"])

    def test_initial_axes_and_superposed_rotation_covariance(self):
        op = m.Prepared(3., 6., .5)
        a = op.advance(m.State(.012, 0., .2, 3.), .001, .3, **KW)
        b = op.advance(m.State(.012, .4, .2, 3.), .001, .3, **KW)
        for key in ("heat_j_m3", "work_j_m3", "stored_change_j_m3"):
            self.assertEqual(a[key],b[key])
        # Explicit Q T Q^T, not the production double-angle formula.
        c,s = math.cos(.4),math.sin(.4)
        q = ((c,-s),(s,c))
        t = a["state"].tensor()
        rotated = [[sum(q[i][k]*t[k][l]*q[j][l] for k in range(2) for l in range(2))
                    for j in range(2)] for i in range(2)]
        for i in range(2):
            for j in range(2): self.close(rotated[i][j],b["state"].tensor()[i][j])

    def test_preparation_and_state_are_immutable(self):
        op, state = m.Prepared(3.,6.,1.), m.State(.01,0.,0.,3.)
        with self.assertRaises(dataclasses.FrozenInstanceError): op.dt_s = 2.
        with self.assertRaises(dataclasses.FrozenInstanceError): state.stress_pa = 0.
        self.assertEqual(op.advance(state,.001,**KW),op.advance(state,.001,**KW))
        self.assertEqual(state.stress_pa,.01)

    def test_unsupported_history_and_parameter_change_refused(self):
        op, state = m.Prepared(3.,6.,1.), m.State(.01,0.,0.,3.)
        for kind in ("general_shear", "constant_lab_D", "omit_elasticity"):
            with self.assertRaises(ValueError): op.advance(state,.001,kinematics=kind)
        with self.assertRaises(ValueError): op.advance(m.State(.01,0.,0.,4.),.001,**KW)
        with self.assertRaises(ValueError): op.advance(state,1.,**KW)
        with self.assertRaises(ValueError): op.advance(m.State(.01,0.,1.,3.),.001,**KW)
        with self.assertRaises(ValueError): op.advance(m.State(.01,0.,0.,3.,1e30),0.,**KW)

    def test_invalid_and_nonfinite_inputs(self):
        for bad in (True, float("nan"), float("inf"), -1., 0.):
            with self.assertRaises(ValueError): m.Prepared(bad,6.,1.)
            with self.assertRaises(ValueError): m.Prepared(3.,bad,1.)
            with self.assertRaises(ValueError): m.Prepared(3.,6.,bad)
        with self.assertRaises(ValueError): m.Prepared(3.,6.,1e10)
        with self.assertRaises(ValueError): m.State(.1,0.,0.,3.)
        with self.assertRaises(ValueError): m.State(.01,float("nan"),0.,3.)


if __name__ == "__main__": unittest.main()
