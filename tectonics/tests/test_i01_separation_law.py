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
        self.assertEqual(values.bond_state(0., 1500., 2e9), "BONDED")          # no plastic history: never broken
        self.assertEqual(values.bond_state(0.999, 500., 1e8), "BONDED")        # partly softened, or healed below
        self.assertEqual(values.bond_state(1.0, 500., 1e8), "BROKEN")
        self.assertEqual(values.bond_state(3.0, 700., 3e8), "BROKEN")          # support bounds are inclusive
        self.assertEqual(values.bond_state(3.0, 700.001, 1e8), "UNRESOLVED")
        self.assertEqual(values.bond_state(1e-9, 1500., 1e8), "UNRESOLVED")
        self.assertEqual(law(residual_state="weakened_intact").bond_state(5.0, 500., 1e8), "BONDED")
        for row in RC["bond_states"]:
            with self.subTest(row["id"]):
                found = law(**row.get("law_changes", {})).bond_state(
                    row["history"], row["temperature_k"], row["effective_pressure_pa"])
                self.assertEqual(found, row["expected"])


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
        self.assertEqual([e["event"] for e in result["events"]], ["yield", "cohesion_lost"])
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
        self.assertIn("cohesion_lost", [e["event"] for e in narrow["events"]])
        self.assertEqual(narrow["bond_state"], "BROKEN")

    def test_mixed_creep_and_plastic_bands_against_independent_rk4(self):
        for width, viscosity, horizon in ((1000.0, 1e22, 2e13), (100.0, 1e20, 3e13)):
            with self.subTest(width=width):
                values = dict(RC["law"], band_width_m=width)
                load = dict(RC["stable_loading"], creep_viscosity_pa_s=viscosity)
                result = m.Prepared(m.SofteningLaw(**values), m.Loading(**load)).advance(start(), horizon)
                oracle = rk4(values, load, TAU0, 0., horizon, 40000)
                losses = [e["time_s"] for e in result["events"] if e["event"] == "cohesion_lost"]
                self.assertEqual(len(losses), 1)
                close(losses[0], oracle["completion"], 1e-6)
                close(result["state"].traction_pa, oracle["traction"], 1e-6)
                close(result["state"].history, oracle["history"], 1e-6)
                close(result["accounts"]["work_j_m2"], oracle["work"], 1e-6)
                close(result["accounts"]["creep_dissipation_j_m2"], oracle["creep"], 1e-6)
                close(result["accounts"]["plastic_dissipation_j_m2"], oracle["plastic"], 1e-6)
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
        crust = values.bond_state(1.2, 500., 1e8)                     # frictional band, completed softening
        ductile = values.bond_state(0., 1400., 1.5e9)                  # creeping mantle: no plastic history
        capped = values.bond_state(0.4, 1400., 1.5e9)                  # plastic history outside the support
        brittle = values.bond_state(1.1, 650., 2.5e8)
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
                 (lambda: m.rate_independent_reference(law(), loading(creep_viscosity_pa_s=1e22), TAU0), m.INVALID))
        for index, (build, code) in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(m.Refusal) as caught:
                    build()
                self.assertEqual(caught.exception.code, code)

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


if __name__ == "__main__":
    unittest.main()
