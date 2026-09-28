"""Focused, independent checks of the cohesion-loss separation slice; nothing is run or written on import."""
import dataclasses
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT/"tools/check_i01_separation_law.py"
SPEC = importlib.util.spec_from_file_location("i01_separation_law", PATH)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
CASE = json.loads((ROOT/"cases/i01_separation_law_v1.json").read_text(encoding="utf-8"))
RC = CASE["runnable_controls"]
# Fixture values written out independently of the tool: sin(phi0) = 0.6 and cos(phi0) = 0.8 by construction.
PEAK, RESIDUAL, WIDTH, ETA, K, V, TAU0 = 7.6e7, 6.0e7, 1000.0, 1.0e19, 3.2e4, 1.0e-10, 5.0e7
SOFT = PEAK-RESIDUAL                       # strength lost per unit history for kappa_c = 1


def close(actual, expected, relative=1e-12):
    if not abs(actual-expected) <= relative*max(abs(actual), abs(expected), 1e-300):
        raise AssertionError("%r != %r within relative %g" % (actual, expected, relative))


def law(**changes):
    return m.SofteningLaw(**dict(RC["law"], **changes))


def loading(**changes):
    return m.Loading(**dict(RC["stable_loading"], **changes))


def start():
    return m.State(**RC["initial_state"])


# The review reproducer, written out: Y0 = 2, Yr = 0 and k = w_s = eta_v = eta_p = kappa_c = 1, so the net drive at
# exact yield is V - 2 and, in the softening phase, kappa'' = 2 (kappa - kappa0) + (V - Y(kappa0)).
ROOT2 = math.sqrt(2.)


def review_law(**changes):
    values = dict(peak_cohesion_pa=2., peak_friction_rad=0., residual_cohesion_pa=0., residual_friction_rad=0.,
                  softening_history=1., band_width_m=1., width_basis="physical", plastic_viscosity_pa_s=1.,
                  residual_state="broken_surface_sliding", provenance="synthetic review",
                  support_temperature_k=(1., 3.), support_effective_pressure_pa=(0., 3.))
    return m.SofteningLaw(**dict(values, **changes))


def review_prepared(rate):
    return m.Prepared(review_law(), m.Loading(1., rate, 1., 1., 2.))


def review_run(rate, tau=2., dt=30.):
    return review_prepared(rate).advance(m.State(tau, 0.), dt)


def completion_after(kappa0, over0, excess):
    """Time for the reproducer's softening phase to reach kappa = 1 from (kappa0, o0), with excess = V - Y(kappa0).

    w = kappa - kappa0 + excess/2 obeys w'' = 2 w with w(0) = excess/2 and w'(0) = o0, so completion solves
    (w0 + B) e^(2r) - 2 w1 e^r + (w0 - B) = 0 with r = sqrt(2) t, B = o0/sqrt(2) and w1 = 1 - kappa0 + w0.
    """
    w0, b = excess/2, over0/ROOT2
    w1 = 1-kappa0+w0
    return math.log((w1+math.sqrt(w1*w1-w0*w0+b*b))/(w0+b))/ROOT2


def rk4(values, load, tau, kappa, horizon, steps):
    """Explicit RK4 of the same band ODE with max(., 0) switching: an algorithm independent of the exact phases."""
    pressure = load["effective_pressure_pa"]
    peak = values["peak_cohesion_pa"]*math.cos(values["peak_friction_rad"])+pressure*math.sin(values["peak_friction_rad"])
    residual = (values["residual_cohesion_pa"]*math.cos(values["residual_friction_rad"])
                + pressure*math.sin(values["residual_friction_rad"]))
    kc, width, eta = values["softening_history"], values["band_width_m"], values["plastic_viscosity_pa_s"]
    k, v = load["stiffness_pa_m"], load["loading_rate_m_s"]
    creep = 0. if load["creep_viscosity_pa_s"] is None else width/load["creep_viscosity_pa_s"]

    def rates(y):
        strength = residual if y[1] >= kc else peak-(peak-residual)*y[1]/kc
        over = max(y[0]-strength, 0.)
        creep_slip, plastic_slip = creep*y[0], width*over/eta
        return (k*(v-creep_slip-plastic_slip), over/eta, v*y[0], y[0]*creep_slip, y[0]*plastic_slip)

    y, h, completion = [tau, kappa, 0., 0., 0.], horizon/steps, None
    for i in range(steps):
        k1 = rates(y)
        k2 = rates([a+h/2*b for a, b in zip(y, k1)])
        k3 = rates([a+h/2*b for a, b in zip(y, k2)])
        k4 = rates([a+h*b for a, b in zip(y, k3)])
        new = [a+h/6*(p+2*q+2*r+s) for a, p, q, r, s in zip(y, k1, k2, k3, k4)]
        if completion is None and new[1] >= kc > y[1]:
            completion = h*(i+(kc-y[1])/(new[1]-y[1]))
        y = new
    return dict(traction=y[0], history=y[1], work=y[2], creep=y[3], plastic=y[4], completion=completion)


def simpson(function, upper, intervals=20000):
    h = upper/intervals
    total = function(0.)+function(upper)
    total += 4*math.fsum(function((2*i-1)*h) for i in range(1, intervals//2+1))
    total += 2*math.fsum(function(2*i*h) for i in range(1, intervals//2))
    return total*h/3


def band_section(crust="BONDED", mantle="BONDED", face="WELDED"):
    """Left block | band | right block, crust over mantle lithosphere; the band-to-right contacts carry `face`."""
    cells = {"Lc": {"material": "crust", "bond": "BONDED"}, "Lm": {"material": "mantle_lithosphere", "bond": "BONDED"},
             "Bc": {"material": "crust", "bond": crust}, "Bm": {"material": "mantle_lithosphere", "bond": mantle},
             "Rc": {"material": "crust", "bond": "BONDED"}, "Rm": {"material": "mantle_lithosphere", "bond": "BONDED"}}
    contacts = [["Lc", "Lm", "WELDED"], ["Bc", "Bm", "WELDED"], ["Rc", "Rm", "WELDED"], ["Lc", "Bc", "WELDED"],
                ["Bc", "Rc", face], ["Lm", "Bm", "WELDED"], ["Bm", "Rm", face]]
    return cells, contacts, {"left": ["Lc", "Lm"], "right": ["Rc", "Rm"]}


class LawTests(unittest.TestCase):
    def test_closed_form_strength_breakdown_slip_and_energy(self):
        values = law()
        peak, residual = values.yields(1e8)
        close(peak, 0.8*2e7+0.6*1e8)
        close(residual, 0.6*1e8)
        close(values.breakdown_slip_m(), 1.0*WIDTH)
        close(values.fracture_energy_j_m2(1e8), SOFT*WIDTH/2)
        close(values.softening_stiffness_pa_m(1e8), SOFT/WIDTH)
        close(values.strength_pa(0.25, 1e8), PEAK-0.25*SOFT)
        close(values.strength_pa(2.0, 1e8), RESIDUAL)

    def test_breakdown_energy_is_local_not_universal(self):
        values = law()
        # Cohesion-only softening: G does not change with pressure. Friction softening: dG/dP = (sin0 - sinr) D_c/2.
        close(values.fracture_energy_j_m2(2e8), values.fracture_energy_j_m2(1e8))
        friction = law(residual_friction_rad=RC["friction_softening"]["residual_friction_rad"])
        close(friction.fracture_energy_j_m2(2e8)-friction.fracture_energy_j_m2(1e8), (0.6-0.1)*1e8*WIDTH/2, 1e-11)
        # G scales with the declared physical width, so no single energy can stand for every band.
        close(law(band_width_m=2*WIDTH).fracture_energy_j_m2(1e8), 2*values.fracture_energy_j_m2(1e8))
        with self.assertRaises(TypeError):
            m.SofteningLaw(**dict(RC["law"], fracture_energy_j_m2=1e6))

    def test_bond_state_rules(self):
        values = law()
        bond = lambda *args, record="INSIDE": values.bond_state(*args, history_support=record)
        self.assertEqual(bond(0., 1500., 2e9, record="UNKNOWN"), "BONDED")   # no plastic history: never broken
        self.assertEqual(bond(0.999, 500., 1e8), "BONDED")                   # partly softened
        self.assertEqual(bond(1.0, 500., 1e8), "BROKEN")
        self.assertEqual(bond(3.0, 700., 3e8), "BROKEN")                     # support bounds are inclusive
        self.assertEqual(bond(3.0, 700.001, 1e8), "UNRESOLVED")
        self.assertEqual(bond(1e-9, 1500., 1e8), "UNRESOLVED")
        self.assertEqual(law(residual_state="weakened_intact").bond_state(5.0, 500., 1e8, history_support="INSIDE"),
                         "BONDED")
        for row in RC["bond_states"]:
            with self.subTest(row["id"]):
                found = law(**row.get("law_changes", {})).bond_state(
                    row["history"], row["temperature_k"], row["effective_pressure_pa"],
                    history_support=row["history_support"])
                self.assertEqual(found, row["expected"])

    def test_the_current_state_never_recertifies_an_earlier_history(self):
        values = law()
        for record, expected in (("INSIDE", "BROKEN"), ("UNKNOWN", "UNRESOLVED"), ("VIOLATED", "UNRESOLVED")):
            with self.subTest(record=record):
                self.assertEqual(values.bond_state(2.0, 500., 1e8, history_support=record), expected)
        with self.assertRaises(TypeError):
            values.bond_state(2.0, 500., 1e8)                              # the record is a required declaration
        for bad in (lambda: values.bond_state(2.0, 500., 1e8, history_support="CURRENT_STATE"),
                    lambda: m.State(5e7, 1.5, 0., "RETURNED_INSIDE")):
            with self.assertRaises(m.Refusal) as caught:
                bad()
            self.assertEqual(caught.exception.code, m.INVALID)
        self.assertEqual(m.State(5e7, 1.5).history_support, "UNKNOWN")
        op = m.Prepared(values, loading())
        for record in ("UNKNOWN", "VIOLATED"):
            with self.subTest(advance=record):
                # History from elsewhere, now inside the support: the advance keeps the record and makes no claim.
                result = op.advance(m.State(5e7, 1.5, 0., record), 1e12)
                self.assertEqual(result["events"], [])
                self.assertEqual((result["state"].history_support, result["bond_state"]), (record, "UNRESOLVED"))
        fresh = op.advance(start(), 1.5e13)
        self.assertEqual((fresh["state"].history_support, fresh["bond_state"]), ("INSIDE", "BROKEN"))

    def test_broken_surface_residual_must_have_lost_its_cohesion(self):
        review = (2., 0., 1., 0., 1., 1., "physical", 1.)
        support = ("synthetic review", (1., 3.), (0., 3.))
        with self.assertRaises(m.Refusal) as caught:
            m.SofteningLaw(*review, "broken_surface_sliding", *support)
        self.assertEqual(caught.exception.code, m.INCONSISTENT)
        weakened = m.SofteningLaw(*review, "weakened_intact", *support)
        self.assertEqual(weakened.bond_state(1., 2., 1., history_support="INSIDE"), "BONDED")
        for changes, code in ((dict(residual_cohesion_pa=5e6), m.INCONSISTENT),
                              (dict(residual_cohesion_pa=2e7), m.NO_SOFTENING)):   # no softening is reported first
            with self.subTest(changes=changes):
                with self.assertRaises(m.Refusal) as caught:
                    law(**changes)
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(law(residual_state="weakened_intact", residual_cohesion_pa=5e6).residual_cohesion_pa, 5e6)


class KernelTests(unittest.TestCase):
    def test_stored_traction_is_kept_and_brings_failure_forward(self):
        op = m.Prepared(law(), loading())
        kept = op.advance(start(), 1.2e13)
        forgotten = op.advance(m.State(0., 0.), 2.5e13)
        t_kept, t_forgotten = kept["events"][0]["time_s"], forgotten["events"][0]["time_s"]
        close(t_kept, (PEAK-TAU0)/(K*V))
        close(t_forgotten-t_kept, TAU0/(K*V), 1e-11)
        close(kept["events"][0]["traction_pa"], PEAK)            # the event sits on the yield surface
        self.assertTrue(kept["elasticity_retained"])
        self.assertEqual(start(), m.State(**RC["initial_state"]))  # the input state is untouched

    def test_history_between_events_matches_closed_form(self):
        rate = (K*WIDTH-SOFT)/ETA                                  # |g|, decay rate of the stable softening mode
        t_yield, after = (PEAK-TAU0)/(K*V), 1.0e12
        result = m.Prepared(law(), loading()).advance(start(), t_yield+after)
        x = rate*after
        history = K*V/(ETA*rate*rate)*(x-1+math.exp(-x))
        close(result["state"].history, history, 1e-11)
        close(result["state"].traction_pa, PEAK-SOFT*history+K*V/rate*-math.expm1(-x), 1e-11)
        self.assertEqual(result["bond_state"], "BONDED")

    def test_stable_completion_matches_independent_scalar_solution(self):
        rate = (K*WIDTH-SOFT)/ETA
        right = (K*WIDTH-SOFT)**2/(ETA*K*V)
        close(right, 8.0)
        x = 9.0
        for _ in range(60):                                        # contraction with factor exp(-x) ~ 1e-4
            x = right+1-math.exp(-x)
        self.assertTrue(8.99987 < x < 8.99988)
        result = m.Prepared(law(), loading()).advance(start(), 1.5e13)
        self.assertEqual([e["event"] for e in result["events"]], ["yield", "softening_complete"])
        self.assertEqual([e["bond_state"] for e in result["events"]], ["BONDED", "BROKEN"])   # bond loss is the law's
        t_yield = (PEAK-TAU0)/(K*V)
        loss = result["events"][1]
        close(loss["time_s"], t_yield+x/rate, 1e-11)
        close(loss["traction_pa"], RESIDUAL+K*V/rate*-math.expm1(-x), 1e-11)   # continuous, never reset
        lower, upper = loss["bracket_s"]
        self.assertTrue(lower <= loss["time_s"] <= upper and upper-lower <= 1e-12*upper)
        self.assertEqual(result["bond_state"], "BROKEN")
        close(result["stability_ratio"], 2.0)

    def test_unstable_completion_matches_independent_scalar_solution(self):
        k = RC["unstable_stiffness_pa_m"]
        rate = (SOFT-k*WIDTH)/ETA                                  # g > 0: the regularised softening instability
        right = (SOFT-k*WIDTH)**2/(ETA*k*V)
        x = 2.44
        for _ in range(50):                                        # Newton on exp(x) - 1 - x - right
            x -= (math.expm1(x)-x-right)/math.expm1(x)
        self.assertTrue(2.4368 < x < 2.4369)
        op = m.Prepared(law(), loading(stiffness_pa_m=k))
        close(op.stability_ratio(), 0.5)
        result = op.advance(start(), 3.6e13)
        close(result["events"][1]["time_s"], (PEAK-TAU0)/(k*V)+x/rate, 1e-11)
        reference = m.rate_independent_reference(law(), loading(stiffness_pa_m=k), TAU0)
        self.assertFalse(reference["stable"])
        close(reference["released_excess_j_m2"], SOFT/2*(SOFT/k-WIDTH))

    def test_bond_loss_dissipates_exactly_the_breakdown_energy(self):
        result = m.Prepared(law(), loading()).advance(start(), 1.5e13)
        at = result["events"][1]["accounts"]
        close(at["breakdown_dissipation_j_m2"], SOFT*WIDTH/2, 1e-11)
        close(at["residual_friction_dissipation_j_m2"], RESIDUAL*WIDTH, 1e-11)
        close(at["plastic_slip_m"], WIDTH, 1e-11)
        total = result["accounts"]
        self.assertGreater(total["overstress_dissipation_j_m2"], 0)
        close(total["plastic_dissipation_j_m2"], total["overstress_dissipation_j_m2"]
              + total["breakdown_dissipation_j_m2"]+total["residual_friction_dissipation_j_m2"], 1e-10)
        close(total["work_j_m2"], total["stored_change_j_m2"]+total["creep_dissipation_j_m2"]
              + total["plastic_dissipation_j_m2"], 1e-10)
        tau = result["state"].traction_pa
        close(total["stored_change_j_m2"], (tau*tau-TAU0*TAU0)/(2*K), 1e-10)
        self.assertLessEqual(result["balance_relative_residual"], 1e-10)

    def test_exact_kernel_is_independent_of_interval_subdivision(self):
        op = m.Prepared(law(), loading())
        whole = op.advance(start(), 1.5e13)
        scale = abs(whole["accounts"]["work_j_m2"])
        for pieces in (7, 13):
            with self.subTest(pieces=pieces):
                state, sums, events = start(), dict.fromkeys(m.ACCOUNTS, 0.), []
                for _ in range(pieces):
                    part = op.advance(state, 1.5e13/pieces)
                    state, events = part["state"], events+part["events"]
                    for key in m.ACCOUNTS:
                        sums[key] += part["accounts"][key]
                close(state.traction_pa, whole["state"].traction_pa, 1e-11)
                close(state.history, whole["state"].history, 1e-11)
                self.assertEqual([e["event"] for e in events], [e["event"] for e in whole["events"]])
                for first, second in zip(events, whole["events"]):
                    close(first["time_s"], second["time_s"], 1e-11)
                for key in m.ACCOUNTS[:-1]:
                    self.assertLessEqual(abs(sums[key]-whole["accounts"][key]), 1e-10*scale)

    def test_vanishing_plastic_viscosity_recovers_rate_independent_slip_weakening(self):
        reference = m.rate_independent_reference(law(), loading(), TAU0)
        self.assertTrue(reference["stable"])
        close(reference["yield_loading_m"], (PEAK-TAU0)/K)
        close(reference["completion_loading_after_yield_m"], WIDTH*(1-SOFT/(K*WIDTH)))      # D_c (1 - k_soft/k)
        close(reference["strength_work_to_completion_j_m2"], (PEAK+RESIDUAL)*WIDTH/2)
        base = reference["completion_loading_after_yield_m"]/V
        lags = []
        for eta in (1e17, 1e16):
            result = m.Prepared(law(plastic_viscosity_pa_s=eta), loading()).advance(start(), 1.4e13)
            yield_time, loss = (event["time_s"] for event in result["events"][:2])
            lag = loss-yield_time-base
            close(lag, eta/(K*WIDTH-SOFT), 1e-6)      # (1 - exp(-X))/|g|, with exp(-X) negligible here
            lags.append(lag)
        close(lags[0]/lags[1], 10.0, 1e-6)

    def test_creeping_band_keeps_cohesion_and_the_physical_width_sets_the_regime(self):
        viscosity = RC["creep"]["hot_viscosity_pa_s"]
        hot = m.Prepared(law(), loading(creep_viscosity_pa_s=viscosity)).advance(start(), 1e14)
        self.assertEqual(hot["events"], [])
        self.assertEqual(hot["state"].history, 0.)
        self.assertEqual(hot["bond_state"], "BONDED")
        self.assertEqual(hot["accounts"]["plastic_dissipation_j_m2"], 0.)
        relax = K*WIDTH/viscosity
        close(hot["state"].traction_pa, K*V/relax+(TAU0-K*V/relax)*math.exp(-relax*1e14), 1e-11)
        narrow_width = RC["creep"]["narrow_band_width_m"]
        steady = viscosity*V/narrow_width                          # steady creep traction eta_v V / w_s
        self.assertGreater(steady, PEAK)
        narrow = m.Prepared(law(band_width_m=narrow_width), loading(creep_viscosity_pa_s=viscosity)).advance(start(), 3e13)
        relax = K*narrow_width/viscosity
        close(narrow["events"][0]["time_s"], math.log((steady-TAU0)/(steady-PEAK))/relax, 1e-11)
        self.assertIn("softening_complete", [e["event"] for e in narrow["events"]])
        self.assertEqual(narrow["bond_state"], "BROKEN")

    def test_mixed_creep_and_plastic_bands_against_independent_rk4(self):
        for width, viscosity, horizon in ((1000.0, 1e22, 2e13), (100.0, 1e20, 3e13)):
            with self.subTest(width=width):
                values = dict(RC["law"], band_width_m=width)
                load = dict(RC["stable_loading"], creep_viscosity_pa_s=viscosity)
                result = m.Prepared(m.SofteningLaw(**values), m.Loading(**load)).advance(start(), horizon)
                oracle = rk4(values, load, TAU0, 0., horizon, 40000)
                losses = [e["time_s"] for e in result["events"] if e["event"] == "softening_complete"]
                self.assertEqual(len(losses), 1)
                close(losses[0], oracle["completion"], 1e-6)
                close(result["state"].traction_pa, oracle["traction"], 1e-6)
                close(result["state"].history, oracle["history"], 1e-6)
                close(result["accounts"]["work_j_m2"], oracle["work"], 1e-6)
                close(result["accounts"]["creep_dissipation_j_m2"], oracle["creep"], 1e-6)
                close(result["accounts"]["plastic_dissipation_j_m2"], oracle["plastic"], 1e-6)
                self.assertLessEqual(result["balance_relative_residual"], 1e-10)

    def test_weakened_intact_completes_softening_without_losing_cohesion(self):
        residual = 0.8*5e6+0.6*1e8                                  # a cohesive residual, Yr = 6.4e7 Pa
        soft = PEAK-residual
        rate = (K*WIDTH-soft)/ETA
        right = (K*WIDTH-soft)**2/(ETA*K*V)
        close(right, 12.5)
        x = 13.5
        for _ in range(60):                                        # contraction with factor exp(-x) ~ 1e-6
            x = right+1-math.exp(-x)
        values = law(residual_state="weakened_intact", residual_cohesion_pa=5e6)
        result = m.Prepared(values, loading()).advance(start(), 1.6e13)
        self.assertEqual([e["event"] for e in result["events"]], ["yield", "softening_complete"])
        self.assertEqual([e["bond_state"] for e in result["events"]], ["BONDED", "BONDED"])
        completion = result["events"][1]
        close(completion["time_s"], (PEAK-TAU0)/(K*V)+x/rate, 1e-11)
        close(completion["traction_pa"], residual+K*V/rate*-math.expm1(-x), 1e-11)
        self.assertGreater(result["state"].history, 1.)             # the residual phase followed the completion
        self.assertEqual(result["bond_state"], "BONDED")
        self.assertLessEqual(result["balance_relative_residual"], 1e-10)

    def test_creep_unloads_a_residual_band_and_keeps_its_history(self):
        eta_v, horizon, tau0, kappa0 = 1e19, 1e11, 7e7, 1.5
        a = b = K*WIDTH/eta_v                                      # creep and viscoplastic rates, both 3.2e-12 s^-1
        lam = a+b
        steady = b*RESIDUAL/lam                                    # 3e7 Pa, below the residual strength
        t_unload = math.log((tau0-steady)/(RESIDUAL-steady))/lam
        kappa_u = kappa0+((tau0-steady)*-math.expm1(-lam*t_unload)/lam+(steady-RESIDUAL)*t_unload)/ETA
        op = m.Prepared(law(), loading(loading_rate_m_s=0., creep_viscosity_pa_s=eta_v))
        result = op.advance(m.State(tau0, kappa0, 0., "INSIDE"), horizon)
        self.assertEqual([e["event"] for e in result["events"]], ["unload"])
        event = result["events"][0]
        close(event["time_s"], t_unload, 1e-11)
        close(event["traction_pa"], RESIDUAL)
        self.assertEqual(event["bond_state"], "BROKEN")
        close(result["state"].history, kappa_u, 1e-11)
        close(result["state"].traction_pa, RESIDUAL*math.exp(-a*(horizon-t_unload)), 1e-11)
        self.assertEqual(result["bond_state"], "BROKEN")
        self.assertLessEqual(result["balance_relative_residual"], 1e-10)

    def test_creep_unloads_a_softening_band_against_independent_rk4(self):
        values = dict(RC["law"])
        load = dict(RC["stable_loading"], loading_rate_m_s=0., creep_viscosity_pa_s=1e19)
        tau0, kappa0, horizon = PEAK, 0.2, 1e11                    # 0.2 SOFT above the strength at kappa0
        result = m.Prepared(m.SofteningLaw(**values), m.Loading(**load)).advance(
            m.State(tau0, kappa0, 0., "INSIDE"), horizon)
        self.assertEqual([e["event"] for e in result["events"]], ["unload"])
        oracle = rk4(values, load, tau0, kappa0, horizon, 40000)
        close(result["state"].traction_pa, oracle["traction"], 1e-6)
        close(result["state"].history, oracle["history"], 1e-6)
        self.assertEqual(result["bond_state"], "BONDED")           # partly softened: cohesion kept
        self.assertLessEqual(result["balance_relative_residual"], 1e-10)

    def test_phase_matrices_match_the_physical_rates(self):
        for creep in (None, 1e22):
            op = m.Prepared(law(), loading(creep_viscosity_pa_s=creep))
            for phase, x in ((op.sub, (5e7, 0.3)), (op.softening, (7.7e7, 0.2)), (op.residual, (6.3e7, 1.4))):
                with self.subTest(creep=creep, phase=phase.name):
                    (b11, b12), (b21, b22) = phase.b
                    rate = op._rate(phase, x)
                    for row, (first, second), constant in ((0, (b11, b12), phase.c[0]), (1, (b21, b22), phase.c[1])):
                        terms = (first*x[0], second*x[1], constant)
                        self.assertLessEqual(abs(math.fsum(terms)-rate[row]),
                                             1e-13*math.fsum(abs(term) for term in terms))
                    trace, det = b11+b22, b11*b22-b12*b21
                    close(2*phase.m, trace, 1e-12)
                    self.assertGreaterEqual(phase.q, abs(phase.m))
                    self.assertLessEqual(abs(phase.m**2-phase.q**2-det), 1e-9*max(phase.q**2, abs(det), 1e-300))

    def test_series_and_exponential_coefficients_are_exact(self):
        for rate_m, rate_q in ((-0.3, 0.5), (0.2, 0.45), (-0.25, 0.25), (0.0, 0.0), (-2.0, 3.0)):
            times = (0.37, 2.0) if rate_q == 0 else (0.5/rate_q*(1-1e-9), 0.5/rate_q*(1+1e-9), 7.0/rate_q)
            for t in times:
                with self.subTest(m=rate_m, q=rate_q, t=t):
                    c, s, j1, j2 = m._coefficients(rate_m, rate_q, t)
                    sinhq = (lambda z: math.sinh(rate_q*z)/rate_q) if rate_q else (lambda z: z)
                    close(c, math.exp(rate_m*t)*math.cosh(rate_q*t), 1e-13)
                    close(s, math.exp(rate_m*t)*sinhq(t), 1e-13)
                    close(j1, simpson(lambda z: math.exp(rate_m*z)*math.cosh(rate_q*z), t), 1e-11)
                    close(j2, simpson(lambda z: math.exp(rate_m*z)*sinhq(z), t), 1e-11)

    def test_preparation_state_and_results_are_immutable_and_reusable(self):
        op, state = m.Prepared(law(), loading()), m.State(**RC["timing_state"])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            op.peak_pa = 1.
        with self.assertRaises(dataclasses.FrozenInstanceError):
            state.traction_pa = 0.
        first = op.advance(state, 1e11)
        self.assertEqual(first, op.advance(state, 1e11))
        self.assertEqual(first, m.Prepared(law(), loading()).advance(state, 1e11))
        self.assertEqual(state, m.State(**RC["timing_state"]))


class ExactYieldTests(unittest.TestCase):
    """The review reproducer: a state exactly on the yield surface under a small net drive (k w_s < s here)."""

    def test_positive_drive_at_exact_yield_follows_the_declared_ode(self):
        rate = 2.+1e-12
        delta = rate-2.                                            # the represented net drive, exact
        result = review_run(rate)
        t_c = math.acosh(1+2/delta)/ROOT2                          # kappa = delta/2 (cosh(sqrt(2) t) - 1) = 1
        self.assertTrue(20.5182 < t_c < 20.5184)
        self.assertEqual([e["event"] for e in result["events"]], ["softening_complete"])
        event = result["events"][0]
        close(event["time_s"], t_c, 1e-11)
        close(event["traction_pa"], math.sqrt(2*(1+delta)), 1e-11)  # delta sinh(sqrt(2) t_c)/sqrt(2)
        self.assertEqual(event["bond_state"], "BROKEN")
        # Residual phase from t_c: tau relaxes to V/2 at rate a + b = 2 and kappa grows by the integral of tau.
        span, far = 30.-t_c, rate/2
        tau_c = math.sqrt(2*(1+delta))
        close(result["state"].traction_pa, far+(tau_c-far)*math.exp(-2*span), 1e-11)
        close(result["state"].history, 1+far*span+(tau_c-far)*-math.expm1(-2*span)/2, 1e-11)
        self.assertEqual((result["bond_state"], result["state"].history_support), ("BROKEN", "INSIDE"))
        self.assertLessEqual(result["balance_relative_residual"], 1e-10)
        # Before completion the state is the declared closed form, not a sub-yield relaxation.
        early = review_run(rate, dt=10.)
        close(early["state"].history, delta/2*(math.cosh(10*ROOT2)-1), 1e-11)
        close(early["state"].traction_pa, 2+delta*(math.sinh(10*ROOT2)/ROOT2-(math.cosh(10*ROOT2)-1)), 1e-12)
        self.assertEqual(early["bond_state"], "BONDED")            # partly softened

    def test_zero_and_negative_drive_at_exact_yield(self):
        zero = review_run(2.)                                      # both fields vanish: an equilibrium
        self.assertEqual(zero["events"], [])
        self.assertEqual((zero["state"].traction_pa, zero["state"].history, zero["bond_state"]), (2., 0., "BONDED"))
        close(zero["accounts"]["work_j_m2"], 2*2*30)
        close(zero["accounts"]["creep_dissipation_j_m2"], 2*2*30)
        rate = 2.-1e-12
        negative = review_run(rate)                                # sub-yield: tau relaxes towards V
        self.assertEqual((negative["events"], negative["state"].history, negative["bond_state"]), ([], 0., "BONDED"))
        close(negative["state"].traction_pa, rate+(2-rate)*math.exp(-30.))

    def test_adjacent_ulp_states_follow_the_same_ode(self):
        rate = 2.+1e-12
        delta = rate-2.
        above, below = math.nextafter(2., 3.), math.nextafter(2., 1.)
        result = review_run(rate, tau=above)                       # plastic from the start with o0 = one ULP
        self.assertEqual([e["event"] for e in result["events"]], ["softening_complete"])
        close(result["events"][0]["time_s"], completion_after(0., above-2., delta), 1e-11)
        result = review_run(rate, tau=below)                       # yields at the exact crossing, then as above
        self.assertEqual([e["event"] for e in result["events"]], ["yield", "softening_complete"])
        t_yield = math.log1p((2.-below)/delta)
        close(result["events"][0]["time_s"], t_yield, 1e-11)
        close(result["events"][1]["time_s"], t_yield+math.acosh(1+2/delta)/ROOT2, 1e-11)
        smallest = math.nextafter(2., 3.)                          # the smallest represented positive drive
        result = review_run(smallest)
        close(result["events"][0]["time_s"], math.acosh(1+2/(smallest-2.))/ROOT2, 1e-11)
        self.assertEqual(result["bond_state"], "BROKEN")
        result = review_run(math.nextafter(2., 1.))                # the largest represented negative drive
        self.assertEqual((result["events"], result["state"].history, result["bond_state"]), ([], 0., "BONDED"))
        # Zero drive: one ULP of overstress still grows in this unstable regime; one ULP below never yields.
        result = review_run(2., tau=above)
        close(result["events"][0]["time_s"], completion_after(0., above-2., 0.), 1e-11)
        result = review_run(2., tau=below)
        self.assertEqual((result["events"], result["state"].history, result["bond_state"]), ([], 0., "BONDED"))
        close(result["state"].traction_pa, 2., 1e-15)

    def test_split_steps_follow_the_declared_ode(self):
        rate = 2.+1e-12
        op, whole = review_prepared(rate), review_run(rate)
        t_c = whole["events"][0]["time_s"]
        scale = abs(whole["accounts"]["work_j_m2"])
        for lengths in ((15., 15.), (15., 10., 5.)):
            with self.subTest(lengths=lengths):
                state, events, sums = m.State(2., 0.), [], dict.fromkeys(m.ACCOUNTS, 0.)
                for length in lengths:
                    part = op.advance(state, length)
                    state, events = part["state"], events+part["events"]
                    for key in m.ACCOUNTS:
                        sums[key] += part["accounts"][key]
                self.assertEqual([e["event"] for e in events], ["softening_complete"])
                close(events[0]["time_s"], t_c, 1e-11)
                close(state.traction_pa, whole["state"].traction_pa, 1e-11)
                close(state.history, whole["state"].history, 1e-11)
                for key in m.ACCOUNTS[:-1]:
                    self.assertLessEqual(abs(sums[key]-whole["accounts"][key]), 1e-10*scale)
                self.assertEqual(part["bond_state"], "BROKEN")
        # An early split: the second advance follows the declared ODE exactly from the state it is given, with the
        # law's strength evaluated at the stored history as the kernel evaluates it.
        first = op.advance(m.State(2., 0.), 1.)
        kappa, tau = first["state"].history, first["state"].traction_pa
        strength = 2.-2.*kappa
        second = op.advance(first["state"], 29.)
        found = second["events"][0]["time_s"]
        close(found, 1.+completion_after(kappa, tau-strength, rate-strength), 1e-11)
        self.assertEqual(second["bond_state"], "BROKEN")
        # The stored traction resolves the 1e-12 Pa overstress at 1 s only to about 4e-16 Pa. The unstable mode
        # turns that rounding into a completion shift of order 1e-4 s (estimated 1.5e-4 s at most): a conditioning
        # limit of the stored state, not a change of outcome, and not a kernel tolerance.
        self.assertLess(abs(found-t_c), 1e-4*t_c)


class SurfaceTests(unittest.TestCase):
    def test_surface_scalars_are_frame_indifferent_and_opening_is_refused(self):
        stress, normal, jump = [[-1.2e8, 3e7], [3e7, -8e7]], [0.6, 0.8], [-200., 150.]
        base = m.surface_projection(stress, normal, jump)
        close(base["normal_traction_pa"], -6.56e7)
        close(base["shear_traction_pa"], 1.08e7)
        close(base["effective_pressure_pa"], 6.56e7)
        close(base["slip_m"], 250.)
        close(m.surface_projection(stress, normal, jump, 1e7)["effective_pressure_pa"], 5.56e7)
        for angle in (0.3, 1.7, -2.5, math.pi):
            with self.subTest(angle=angle):
                c, s = math.cos(angle), math.sin(angle)
                q = ((c, -s), (s, c))
                rotated = [[sum(q[i][p]*stress[p][r]*q[j][r] for p in range(2) for r in range(2)) for j in range(2)]
                           for i in range(2)]
                turn = lambda vector: [q[i][0]*vector[0]+q[i][1]*vector[1] for i in range(2)]
                turned = m.surface_projection(rotated, turn(normal), turn(jump))
                for key in ("normal_traction_pa", "shear_traction_pa", "effective_pressure_pa"):
                    self.assertLessEqual(abs(turned[key]-base[key]), 1e-12*1.2e8)
                self.assertLessEqual(abs(turned["slip_m"]-250.), 1e-12*250.)
                self.assertEqual((turned["shear_sense"], turned["slip_sense"]), (1, 1))
        reverse = m.surface_projection(stress, normal, [200., -150.])
        self.assertEqual(reverse["slip_sense"], -1)
        close(reverse["slip_m"], 250.)
        self.assertEqual(m.surface_projection(stress, normal, [0., 0.])["slip_m"], 0.)
        with self.assertRaises(m.Refusal) as caught:
            m.surface_projection(stress, normal, [60., 80.])
        self.assertEqual(caught.exception.code, m.OPENING)
        with self.assertRaises(m.Refusal):
            m.surface_projection([[1., 2.], [3., 4.]], normal, jump)
        with self.assertRaises(m.Refusal):
            m.surface_projection(stress, [1., 1.], jump)


class SectionTests(unittest.TestCase):
    def diagnose(self, *section):
        return m.section_diagnostics(*section)

    def test_a_cohesionless_contact_separates_while_touching_but_set_wording_cannot(self):
        broken = self.diagnose(*band_section("BROKEN", "BROKEN"))
        surface = self.diagnose(*band_section(face="COHESIONLESS"))
        for found in (broken, surface):
            self.assertEqual((found["crust"], found["mantle_lithosphere"], found["union"]),
                             ("DISCONNECTED", "DISCONNECTED", "DISCONNECTED"))
            self.assertEqual(found["set_union"], "CONNECTED")      # the reading section 10 proposes to correct

    def test_crust_only_alternating_unresolved_and_film_cases(self):
        crust_only = self.diagnose(*band_section("BROKEN", "BONDED"))
        self.assertEqual((crust_only["crust"], crust_only["mantle_lithosphere"], crust_only["union"]),
                         ("DISCONNECTED", "CONNECTED", "CONNECTED"))
        unresolved = self.diagnose(*band_section("UNRESOLVED", "BROKEN"))
        self.assertEqual((unresolved["crust"], unresolved["union"]), ("UNRESOLVED", "UNRESOLVED"))
        undecided_face = self.diagnose(*band_section(face="UNRESOLVED"))
        self.assertEqual(undecided_face["union"], "UNRESOLVED")
        film = self.diagnose(*band_section())
        self.assertEqual(set(film.values()), {"CONNECTED"})
        cells = {"Lc": {"material": "crust", "bond": "BONDED"}, "Lm": {"material": "mantle_lithosphere", "bond": "BONDED"},
                 "M1": {"material": "mantle_lithosphere", "bond": "BONDED"}, "C1": {"material": "crust", "bond": "BONDED"},
                 "Rc": {"material": "crust", "bond": "BONDED"}, "Rm": {"material": "mantle_lithosphere", "bond": "BONDED"}}
        contacts = [["Lc", "Lm", "WELDED"], ["Rc", "Rm", "WELDED"], ["Lc", "M1", "WELDED"], ["M1", "C1", "WELDED"],
                    ["C1", "Rm", "WELDED"]]
        alternating = self.diagnose(cells, contacts, {"left": ["Lc", "Lm"], "right": ["Rc", "Rm"]})
        self.assertEqual((alternating["crust"], alternating["mantle_lithosphere"], alternating["union"]),
                         ("DISCONNECTED", "DISCONNECTED", "CONNECTED"))

    def test_bond_states_from_the_law_decide_the_section(self):
        values = law()
        bond = lambda *args: values.bond_state(*args, history_support="INSIDE")
        crust = bond(1.2, 500., 1e8)                                   # frictional band, completed softening
        ductile = bond(0., 1400., 1.5e9)                               # creeping mantle: no plastic history
        capped = bond(0.4, 1400., 1.5e9)                               # plastic history outside the support
        brittle = bond(1.1, 650., 2.5e8)
        self.assertEqual((crust, ductile, capped, brittle), ("BROKEN", "BONDED", "UNRESOLVED", "BROKEN"))
        self.assertEqual(self.diagnose(*band_section(crust, ductile))["union"], "CONNECTED")
        self.assertEqual(self.diagnose(*band_section(crust, capped))["union"], "UNRESOLVED")
        self.assertEqual(self.diagnose(*band_section(crust, brittle))["union"], "DISCONNECTED")

    def test_positive_thickness_counterexample_is_never_separation(self):
        ladder = RC["negative_example"]

        def exact(u, w):                                               # I01_SEPARATION_DECISION section 5, written out
            knee = 64.0-w
            return 64.0-u if u <= knee else w*math.exp(-(u-knee)/w)

        for w in (ladder["w_m"], ladder["halved_w_m"]):
            for u in ladder["opening_levels_m"]+[ladder["false_extrapolated_limit_m"]]:
                with self.subTest(w=w, u=u):
                    h = exact(u, w)
                    self.assertGreater(h, 0.)
                    close(m.negative_example_thickness(u, h_c=64, a=1, c=1, w=w), h)
                    found = self.diagnose(*band_section())             # the film is bonded material, h > 0
                    self.assertEqual(found["union"], "CONNECTED")
                    self.assertEqual(m.classify_interval(found, found)["union_event"], "NO_UNION_EVENT")
        close(exact(64., 1.), math.exp(-1))
        close(exact(64., 0.5), 0.5*math.exp(-1))
        cells, contacts, anchors = band_section()
        cells["Bc"]["thickness_m"] = math.exp(-1)
        with self.assertRaises(m.Refusal) as caught:
            m.connectivity(cells, contacts, anchors, "union")
        self.assertEqual(caught.exception.code, m.FIELD)

    def test_interval_records_never_split_a_plate(self):
        film = self.diagnose(*band_section())
        broken = self.diagnose(*band_section("BROKEN", "BROKEN"))
        crust_only = self.diagnose(*band_section("BROKEN", "BONDED"))
        unresolved = self.diagnose(*band_section("UNRESOLVED", "BROKEN"))
        cases = ((film, broken, "BRACKETED_UNION_LOSS", True), (film, crust_only, "NO_UNION_EVENT", True),
                 (crust_only, crust_only, "NO_UNION_EVENT", False), (broken, broken, "INHERITED_DISCONNECTION", False),
                 (broken, film, "RECONNECTED", False), (film, unresolved, "UNRESOLVED", False))
        for before, after, event, milestone in cases:
            with self.subTest(event=event):
                record = m.classify_interval(before, after)
                self.assertEqual((record["union_event"], record["crustal_milestone"]), (event, milestone))
                self.assertFalse(record["plate_split_authorised"])
                self.assertTrue(record["section_only"])
                self.assertTrue(record["graph_comparison_only"])     # supplied graphs, not a healing result
                self.assertEqual(bool(record["requires"]), event == "BRACKETED_UNION_LOSS")

    def test_invalid_sections_are_refused(self):
        cells, contacts, anchors = band_section()
        broken_anchor = dict(anchors, left=["Lc", "Lm", "Bc"])
        cells_broken = dict(cells, Bc={"material": "crust", "bond": "BROKEN"})
        for bad in ((cells_broken, contacts, broken_anchor), (cells, contacts+[["Lc", "Lc", "WELDED"]], anchors),
                    (cells, contacts+[["Lc", "Rc", "GLUED"]], anchors), (cells, contacts, {"left": ["Lc"]}),
                    (cells, contacts, {"left": ["Lc"], "right": ["Lc"]})):
            with self.assertRaises(m.Refusal) as caught:
                m.connectivity(*bad, "union")
            self.assertEqual(caught.exception.code, m.SECTION)


class RefusalAndCaseTests(unittest.TestCase):
    def test_refusals_leave_no_default(self):
        cases = ((lambda: law(width_basis="grid_cells"), m.NOT_PHYSICAL),
                 (lambda: law(provenance=""), m.NO_PROVENANCE),
                 (lambda: law(residual_friction_rad=1.0), m.NO_SOFTENING),
                 (lambda: law(residual_state="fractured"), m.INVALID),
                 (lambda: law(band_width_m=0.), m.INVALID),
                 (lambda: law(peak_cohesion_pa=float("nan")), m.INVALID),
                 (lambda: law(peak_cohesion_pa=True), m.INVALID),
                 (lambda: loading(healing_rate_s=1e-16), m.HEALING),
                 (lambda: loading(loading_rate_m_s=-1e-12), m.REVERSE),
                 (lambda: m.Prepared(law(), loading(temperature_k=900.)), m.OUTSIDE),
                 (lambda: m.Prepared(law(), loading(effective_pressure_pa=5e8)), m.OUTSIDE),
                 (lambda: m.State(-1., 0.), m.INVALID),
                 (lambda: m.Prepared(law(), loading()).advance(start(), 0.), m.INVALID),
                 (lambda: m.rate_independent_reference(law(), loading(creep_viscosity_pa_s=1e22), TAU0), m.INVALID),
                 (lambda: law(residual_cohesion_pa=1e6), m.INCONSISTENT))
        for index, (build, code) in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(m.Refusal) as caught:
                    build()
                self.assertEqual(caught.exception.code, code)

    def test_numeric_range_failures_are_refused_not_returned(self):
        shape = dict(h_c=64, a=1, c=1)
        close(m.negative_example_thickness(763., w=1, **shape), math.exp(-700.))
        for opening in (1000, 772.):                               # exp(-937) underflows; exp(-709) is subnormal
            with self.subTest(opening=opening):
                with self.assertRaises(m.Refusal) as caught:
                    m.negative_example_thickness(opening, w=1, **shape)
                self.assertEqual(caught.exception.code, m.RANGE)
        # A film far thinner than one ULP of H_c: the exact knee excess keeps it (the rounded knee returned 0.0).
        close(m.negative_example_thickness(64., h_c=64, a=1e-20, c=1, w=1), 1e-20*math.exp(-1))
        close(m.negative_example_thickness(63., h_c=64, a=1e-20, c=1, w=1), 1.)
        stress, normal = [[-1.2e8, 3e7], [3e7, -8e7]], [.6, .8]
        cases = ((lambda: m.surface_projection([[1.7e308, 1.7e308], [1.7e308, 1.7e308]], normal, [-.8, .6])),
                 (lambda: m.surface_projection(stress, normal, [1.7e308, -1.7e308])),
                 (lambda: law(softening_history=1e200, band_width_m=1e200)),        # D_c overflows
                 (lambda: law(softening_history=1e-200, band_width_m=1e-200)),      # D_c underflows
                 (lambda: m.Prepared(law(softening_history=1e200), loading(stiffness_pa_m=1e120))),  # k D_c/(Y0-Yr)
                 (lambda: m.rate_independent_reference(law(), loading(stiffness_pa_m=1e-300), TAU0)))
        for index, build in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(m.Refusal) as caught:
                    build()
                self.assertEqual(caught.exception.code, m.RANGE)

    def test_positive_fracture_energy_cannot_underflow_to_zero(self):
        # Both the product and the final division can lose a positive G.
        for peak, width in ((1e-200, 1e-200), (math.ldexp(1., -537), math.ldexp(1., -537))):
            with self.subTest(peak=peak, width=width):
                with self.assertRaises(m.Refusal) as caught:
                    review_law(peak_cohesion_pa=peak, band_width_m=width)
                self.assertEqual(caught.exception.code, m.RANGE)
        # A representable subnormal energy is not a physical cutoff or zero.
        small = math.ldexp(1., -536)
        admitted = review_law(peak_cohesion_pa=small, band_width_m=small)
        self.assertEqual(admitted.fracture_energy_j_m2(1.), math.ldexp(1., -1073))
        self.assertEqual(review_law(peak_cohesion_pa=2., band_width_m=3.).fracture_energy_j_m2(1.), 3.)

    def test_case_is_bound_to_the_executable_and_the_decision_case(self):
        self.assertIs(m.check_case(CASE), CASE)
        with self.assertRaises(ValueError):
            m.check_case(dict(CASE, policy=dict(CASE["policy"], energy_relative=1e-6)))
        with self.assertRaises(ValueError):
            m.check_case(dict(CASE, scientific_acceptance=True))
        decision = json.loads((ROOT/"cases/i01_separation_decision_v1.json").read_text(encoding="utf-8"))
        for key in ("H_c_m", "a", "c", "w_m", "c_w", "u_a_m", "thickness_levels_m", "opening_levels_m",
                    "false_extrapolated_limit_m", "halved_w_m"):
            self.assertEqual(RC["negative_example"][key], decision["negative_ladder"][key])
        resolved = CASE["unimplemented_resolved_comparison"]
        self.assertEqual(resolved["status"], "PREDECLARED_NOT_IMPLEMENTED")
        self.assertIsNone(resolved["eps_v"])
        self.assertFalse(CASE["event_authorised"])
        # The review reproducer in the case is the one written out here.
        exact = RC["exact_yield"]
        self.assertEqual(m.SofteningLaw(**exact["law"]), review_law(provenance=exact["law"]["provenance"]))
        self.assertEqual(exact["loading_rates_m_s"]["positive"], 2.+1e-12)
        self.assertTrue(all(row["history_support"] in m.HISTORY_SUPPORT for row in RC["bond_states"]))


if __name__ == "__main__":
    unittest.main()
