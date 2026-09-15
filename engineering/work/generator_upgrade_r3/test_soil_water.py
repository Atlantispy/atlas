"""Small analytical, independent time-integrator, refinement and restart checks."""
from dataclasses import replace
from fractions import Fraction as F
import json
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from scipy.integrate import solve_ivp
from . import soil_water as w

E = "EXPLICIT SYNTHETIC MATRIX-FLOW CASE; NO DIADEM OR CROP CALIBRATION"
S = "SYNTHETIC TEST"


def layer(i="a", dz=.1, k=1e-5, **changes):
    return replace(w.HydraulicLayer(str(i), dz, .05, .4, 2, 2, .5, k, E, S), **changes)


def column(n=4, root=None, layers=None):
    return w.Column("synthetic", layers or tuple(layer(i) for i in range(n)), n if root is None else root, E, S)


def controls(**changes):
    return replace(w.Controls(10, 1e-5, 60, 1e-6, 1e-4, 1e-8, 1e-4, 1e-11, 1e-8, -1e5, 100, 10000, 300), **changes)


def forcing(t=60, rain=1e-6, et=0, uptake=None):
    return w.Forcing(t, rain, et, uptake, E, S)


def boundary(kind="free_drainage", head=None):
    return w.Boundary(kind, head, E, S)


def solve(c=None, heads=None, f=None, b=None, ctl=None):
    c = c or column()
    return w.advance(c, w.initial_state(c, heads or (-1.,)*len(c.layers)), f or forcing(), b or boundary(), ctl or controls(), water_density_kg_m3=1000, gravity_m_s2=9.81)


def independent_theta_solution(c, initial_heads, duration, rain):
    """Independent theta-state DOP853 discretisation, no production hydraulics call.

    This checks transient integration independently; spatial accuracy separately
    uses equilibrium, layered Darcy and mesh refinement checks.
    """
    dz = np.array([p.thickness_m for p in c.layers])
    def theta(h, p):
        return p.theta_r+(p.theta_s-p.theta_r)*(1+(p.alpha_per_m*abs(h))**p.n)**(-(1-1/p.n))
    initial = np.array([theta(h, p) for h, p in zip(initial_heads, c.layers)])
    def rhs(t, content):
        heads, ks = [], []
        for th, p in zip(content, c.layers):
            se = (th-p.theta_r)/(p.theta_s-p.theta_r); m = 1-1/p.n
            heads.append(-((se**(-1/m)-1)**(1/p.n))/p.alpha_per_m)
            ks.append(p.ksat_m_s*se**p.mualem_l*(1-(1-se**(1/m))**m)**2)
        q = [min(rain, ks[0]*(1-heads[0]/(dz[0]/2)))]
        for i in range(1,len(heads)):
            kface = (dz[i-1]+dz[i])/(dz[i-1]/ks[i-1]+dz[i]/ks[i])
            q.append(kface*(1-(heads[i]-heads[i-1])/((dz[i-1]+dz[i])/2)))
        q.append(ks[-1])
        return -np.diff(q)/dz
    answer = solve_ivp(rhs, (0, duration), initial, method="DOP853", rtol=1e-11, atol=1e-13)
    if not answer.success:
        raise AssertionError("independent transient oracle failed")
    return answer.y[:,-1]


class SoilWaterTests(unittest.TestCase):
    def modelled(self, result):
        self.assertEqual(result["status"], "MODELLED", result)
        self.assertLessEqual(abs(result["ledger"]["water_residual_m"]), 1e-8)

    def test_vg_n2_independent_closed_form(self):
        p=layer()
        for head in (-100,-1,-.1,0,1):
            theta,k=w.hydraulic_properties(p,head)
            se=1 if head>=0 else 1/math.sqrt(1+(2*head)**2)
            expected=.05+.35*se
            kr=se**.5*(1-math.sqrt(1-se*se))**2
            self.assertAlmostEqual(theta,expected,places=14)
            self.assertAlmostEqual(k,1e-5*kr,places=17)

    def test_dry_end_conductivity_not_cancelled_to_false_zero(self):
        _,k=w.hydraulic_properties(layer(),-1e5)
        self.assertGreater(k,0)
        self.assertLess(k,1e-20)

    def test_theta_inverse_round_trip(self):
        for h in (-1000,-5,-1,-.01):
            th,_=w.hydraulic_properties(layer(),h)
            self.assertAlmostEqual(w.head_from_theta(layer(),th),h,delta=abs(h)*1e-9)

    def test_saturated_stock_does_not_invent_pressure(self):
        with self.assertRaises(ValueError):w.head_from_theta(layer(),.4)
        self.assertEqual(w.head_from_theta(layer(),.4,saturated_head_m=2),2)
        with self.assertRaises(ValueError):w.head_from_theta(layer(),.4,saturated_head_m=-1)

    def test_hydrostatic_equilibrium_heterogeneous_profile(self):
        cells=(layer(0,.1,k=1e-5),layer(1,.2,k=1e-6,alpha_per_m=3),layer(2,.1,k=3e-5,n=1.7))
        c=column(3,layers=cells)
        depths=np.cumsum([x.thickness_m for x in cells])-np.array([x.thickness_m for x in cells])/2
        r=solve(c,tuple(float(x) for x in depths-.3),forcing(1000,0),boundary("fixed_head",.1))
        self.modelled(r)
        np.testing.assert_allclose(r["state"].head_m,depths-.3,atol=1e-12)
        self.assertLess(max(r["ledger"]["face_downward_m"]+r["ledger"]["face_upward_m"]),1e-12)

    def test_saturated_unit_gradient_and_excess_rain_oracle(self):
        r=solve(heads=(0.,)*4,f=forcing(100,2e-5))
        self.modelled(r)
        self.assertAlmostEqual(r["ledger"]["bottom_downward_m"],.001,places=11)
        self.assertAlmostEqual(r["ledger"]["rain_excess_runoff_m"],.001,places=11)
        self.assertAlmostEqual(r["ledger"]["initial_storage_m"],r["ledger"]["final_storage_m"],places=11)

    def test_layered_saturated_darcy_series_resistance_oracle(self):
        cells=(layer(0,.1,1e-5),layer(1,.2,2e-6),layer(2,.1,4e-6))
        c=column(3,layers=cells)
        q=-.1/sum(p.thickness_m/p.ksat_m_s for p in cells)
        resistance=0.;depth=0.;heads=[]
        for p in cells:
            heads.append(depth+p.thickness_m/2-q*(resistance+p.thickness_m/(2*p.ksat_m_s)))
            resistance+=p.thickness_m/p.ksat_m_s;depth+=p.thickness_m
        r=solve(c,tuple(heads),forcing(100,0),boundary("fixed_head",.5))
        self.modelled(r)
        self.assertAlmostEqual(r["ledger"]["bottom_upward_m"],-100*q,places=12)
        self.assertAlmostEqual(r["ledger"]["surface_exfiltration_m"],-100*q,places=12)
        self.assertEqual(r["ledger"]["infiltration_m"],0)

    def test_richards_transient_matches_independent_theta_integrator(self):
        c=column();heads=(-1.,)*4
        expected=independent_theta_solution(c,heads,300,3e-6)
        r=solve(c,heads,forcing(300,3e-6),ctl=controls(initial_dt_s=2,max_dt_s=5,relative_tolerance=1e-5))
        self.modelled(r)
        np.testing.assert_allclose([x["theta_m3_m3"] for x in r["layers"]],expected,atol=8e-6,rtol=0)

    def test_timestep_refinement_reduces_transient_error(self):
        c=column();heads=(-1.,)*4;expected=independent_theta_solution(c,heads,600,3e-6)
        errors=[]
        for dt in (60,15,3):
            r=solve(c,heads,forcing(600,3e-6),ctl=controls(initial_dt_s=dt,max_dt_s=dt,relative_tolerance=.5,theta_atol=.1,head_atol_m=1,flux_integral_atol_m=.1))
            self.modelled(r)
            errors.append(np.linalg.norm(np.array([x["theta_m3_m3"] for x in r["layers"]])-expected))
        self.assertGreater(errors[0],errors[1]);self.assertGreater(errors[1],errors[2])
        self.assertLess(errors[2],errors[0]/8)

    def test_spatial_refinement_converges_profile_storage(self):
        values=[]
        for n in (4,8,16):
            c=column(n,layers=tuple(layer(i,.4/n) for i in range(n)))
            r=solve(c,(-1.,)*n,forcing(300,3e-6),ctl=controls(initial_dt_s=2,max_dt_s=5))
            self.modelled(r)
            # Compare volume-weighted pressure-profile mean; fine-grid trend,
            # not conservation as a substitute for profile convergence.
            values.append(sum(x["head_m"]*.4/n for x in r["layers"]))
        self.assertLess(abs(values[2]-values[1]),abs(values[1]-values[0]))

    def test_gross_root_down_and_up_are_not_net_drainage(self):
        c=column(root=2)
        down=solve(c,f=forcing(100,1e-5));self.modelled(down)
        # Initial downward pressure-head gradient2 exceeds gravity1, so the
        # independent Darcy direction is upward at the root face immediately.
        up=solve(c,heads=(-1.,-.8,-.6,-.4),f=forcing(100,0),b=boundary("fixed_head",-.3));self.modelled(up)
        self.assertGreater(down["ledger"]["root_zone_gross_downward_m"],0)
        self.assertGreater(up["ledger"]["root_zone_upward_capillary_m"],0)
        self.assertGreater(up["ledger"]["bottom_upward_m"],0)

    def test_feddes_uptake_and_no_implicit_extra_et(self):
        uptake=w.Uptake((.5,.5,0,0),-100,-2,-.2,0,E,S)
        c=column(root=2)
        r=solve(c,f=forcing(60,0,1e-7,uptake));self.modelled(r)
        self.assertAlmostEqual(r["ledger"]["actual_et_m"],6e-6,places=13)
        self.assertEqual(r["layers"][2]["et_m"],0)
        self.assertLessEqual(r["ledger"]["actual_et_m"],r["ledger"]["potential_et_m"]*(1+1e-14))

    def test_dry_and_wet_stress_limit_actual_uptake(self):
        uptake=w.Uptake((1.,),-100,-2,-.2,0,E,S);c=column(1)
        for h in (-200,0):
            r=solve(c,(h,),forcing(60,0,1e-6,uptake),boundary("fixed_head",h+.05));self.modelled(r)
            self.assertLess(r["ledger"]["actual_et_m"],1e-10)

    def test_signed_pore_pressure_is_actual_water_state(self):
        r=solve(heads=(-1.,)*4);self.modelled(r)
        for row in r["layers"]:
            self.assertEqual(row["signed_pore_pressure_pa"],1000*9.81*row["head_m"])
            self.assertLess(row["signed_pore_pressure_pa"],0)
            self.assertEqual(row["positive_pore_pressure_pa"],0)

    def test_per_layer_exact_represented_water_is_not_a_score(self):
        c=column();r=solve(c);self.modelled(r)
        for p,row in zip(c.layers,r["layers"]):
            self.assertEqual(F(row["water_m3_m2_exact_represented"]),F(row["theta_m3_m3"])*F(p.thickness_m))
            self.assertGreaterEqual(row["pore_saturation"],0);self.assertLessEqual(row["pore_saturation"],1)

    def test_restart_roundtrip_and_continuation(self):
        c=column();r=solve(c,f=forcing(30));self.modelled(r)
        saved=w.state_to_json(r["state"]);restored=w.state_from_json(saved,c)
        self.assertEqual(restored,r["state"])
        args=(c,restored,forcing(30),boundary(),controls())
        a=w.advance(*args,water_density_kg_m3=1000,gravity_m_s2=9.81)
        b=w.advance(c,r["state"],forcing(30),boundary(),controls(),water_density_kg_m3=1000,gravity_m_s2=9.81)
        self.assertEqual(a,b)

    def test_macro_two_half_steps_preserve_budget_and_converge(self):
        c=column();whole=solve(c,f=forcing(120));self.modelled(whole)
        a=solve(c,f=forcing(60));b=w.advance(c,a["state"],forcing(60),boundary(),controls(),water_density_kg_m3=1000,gravity_m_s2=9.81);self.modelled(b)
        np.testing.assert_allclose(whole["state"].head_m,b["state"].head_m,atol=2e-5,rtol=0)

    def test_geometry_and_retention_changes_reject_stale_state(self):
        c=column();s=w.initial_state(c,(-1.,)*4)
        altered=replace(c,layers=(replace(c.layers[0],thickness_m=.11),*c.layers[1:]))
        with self.assertRaises(ValueError):w.advance(altered,s,forcing(),boundary(),controls(),water_density_kg_m3=1000,gravity_m_s2=9.81)

    def test_checkpoint_strict_unknown_fields_and_nonfinite_reject(self):
        c=column();raw=json.loads(w.state_to_json(w.initial_state(c,(-1.,)*4)))
        with self.assertRaises(ValueError):w.state_from_json(json.dumps({**raw,"extra":1}),c)
        with self.assertRaises(ValueError):w.state_from_json('{"schema":NaN}',c)
        with self.assertRaises(ValueError):w.state_from_json('{"x":1,"x":2}',c)

    def test_unknown_forcing_hydraulics_boundary_fail_closed(self):
        for c,f,b in ((column(layers=(layer(0,ksat_m_s=None),layer(1),layer(2),layer(3))),forcing(),boundary()),
                      (column(),forcing(rain=None),boundary()),(column(),forcing(),boundary("fixed_head",None))):
            r=solve(c,f=f,b=b);self.assertEqual(r["status"],"UNKNOWN");self.assertIsNone(r["state"])

    def test_no_solver_success_flag_can_override_mass_failure(self):
        with patch.object(w,"_step",return_value=None):
            r=solve(ctl=controls(initial_dt_s=.01,min_dt_s=.01))
        self.assertEqual(r["status"],"NUMERICAL_FAILURE");self.assertIsNone(r["state"])

    def test_work_budget_never_returns_partial_state(self):
        r=solve(f=forcing(1000),ctl=controls(max_steps=1,initial_dt_s=1,max_dt_s=1))
        self.assertEqual(r["status"],"NUMERICAL_FAILURE");self.assertIsNone(r["state"])

    def test_backend_success_with_wrong_storage_does_not_pass(self):
        fake=SimpleNamespace(success=True,x=np.full(4,2.),jac=np.eye(4),nfev=1)
        with patch.object(w,"least_squares",return_value=fake):
            r=solve(ctl=controls(max_steps=4))
        self.assertEqual(r["status"],"NUMERICAL_FAILURE");self.assertIsNone(r["state"])

    def test_impermeable_unsaturated_stock_and_runoff(self):
        c=column(1,layers=(layer(0,k=0),))
        r=solve(c,(-1.,),forcing(60,1e-5),boundary("no_flow"));self.modelled(r)
        self.assertEqual(r["ledger"]["infiltration_m"],0)
        self.assertAlmostEqual(r["ledger"]["surface_runoff_m"],.0006,places=14)
        self.assertEqual(r["state"].head_m,(-1.,))

    def test_biological_evidence_prevents_false_pure_synthetic_label(self):
        uptake=w.Uptake((1.,),-100,-2,-.2,0,E,"CANON")
        r=solve(column(1),f=forcing(10,0,1e-7,uptake));self.modelled(r)
        self.assertEqual(r["source_status"],"WORKING NON-CANON")
        self.assertFalse(r["physical_acceptance"])

    def test_zero_duration_does_not_certify_new_saturated_pressure(self):
        r=solve(f=forcing(0));self.assertEqual(r["status"],"NO_ADVANCE");self.assertIsNone(r["layers"])

    def test_isolated_saturated_cell_has_no_unique_pressure(self):
        c=column(1,layers=(layer(0,k=0),))
        r=solve(c,(1.,),forcing(1,0),boundary("no_flow"),controls(initial_dt_s=1,min_dt_s=1))
        self.assertEqual(r["status"],"NUMERICAL_FAILURE")

    def test_short_duration_cannot_certify_wrong_saturated_pressure(self):
        c=column(1)
        r=solve(c,(0.,),forcing(1e-6,0),boundary("fixed_head",.2),
                controls(initial_dt_s=1e-6,min_dt_s=1e-8,max_dt_s=1e-6))
        self.modelled(r)
        # Equal half-cell resistances; bottom total head .1 m and surface0.
        self.assertAlmostEqual(r["state"].head_m[0],.1,places=8)

    def test_numeric_ranges_and_biological_defaults_reject(self):
        for value in (True,float("nan"),float("inf"),-1):
            with self.subTest(value=value),self.assertRaises(ValueError):layer(ksat_m_s=value)
        with self.assertRaises(ValueError):layer(n=1)
        with self.assertRaises(ValueError):forcing(et=1e-7)
        with self.assertRaises(ValueError):replace(controls(),max_steps=True)
        with self.assertRaises(ValueError):w.Uptake((1.,),-1,-2,-.2,0,E,S)


if __name__=="__main__":unittest.main()
