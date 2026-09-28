"""Focused I01 basal-closure tests: the selected boundary prescription, moving-control-volume balances and mesh
conventions, datum and flow-work separation, finite accounts with atomic refusal, inventories bound to geometry, thermal
conditions bound to segment and flow, endpoint proposals bound to their account, the I05 open-base interface and its
lithosphere guard, the exact pure-shear work control and case guards. Each advertised property has an oracle written
here, independent of the tool's own booking.
No world generation, native import or solver; the grouped controls are called directly and the CLI is exercised only for
exclusive creation.
SPDX-License-Identifier: AGPL-3.0-only
"""
import ast
import copy
from fractions import Fraction as F
import json
import math
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import check_i01_basal_closure as b

SPEC = b.load_case()
RET = b.retained_inputs()
PAR = SPEC["control_parameters"]
CFG = PAR["configuration"]
SIDE = b.per_aspect_year(CFG["side_velocity_m_per_aspect_year"], CFG["aspect_year_s"])
DT = PAR["interval_aspect_years"]*b.ASPECT_YEAR_S
W, ZB, HL = CFG["width_m"], CFG["base_depth_m"], CFG["lithosphere_thickness_m"]
TB, TS, TREF = CFG["base_temperature_k"], CFG["surface_temperature_k"], CFG["datum_k"]
RHO_A = PAR["asthenosphere"]["density_kg_m3"]
CP_A = PAR["asthenosphere"]["heat_capacity_j_kg_k"]
TOL = F(b.POLICY["closure_relative"])


def config(**changes):
    return b.mutated(b.configuration(SPEC, RET), *(((key,), value) for key, value in changes.items()))


def code_of(function, *args, **kwargs):
    """The refusal code raised by a call, or None when it is accepted."""
    return b.refusal_code(function, *args, **kwargs)


def near(value, exact, scale):
    return abs(F(value)-F(exact)) <= TOL*F(scale)


class PrescriptionTests(unittest.TestCase):
    def test_selected_components_reactions_and_pressure(self):
        rule = b.resolved_prescription(b.configuration(SPEC, RET))
        base, left, right, top = (rule["segments"][n] for n in ("base", "left", "right", "top"))
        self.assertEqual((rule["status"], rule["stokes_solution"]), (b.PRESCRIPTION_ONLY, False))
        self.assertEqual((base["normal"]["prescribed"], base["tangential"]["prescribed"]), ("velocity", "traction"))
        self.assertEqual(base["tangential"]["traction_pa"], 0.0)
        self.assertEqual(base["normal"]["distribution"], "uniform (declared)")
        # The literal ASPECT rule v*2*d/w at the deeper base, evaluated exactly.
        self.assertTrue(near(-base["normal"]["outward_velocity_m_s"], 2*F(SIDE)*F(ZB)/F(W), SIDE))
        for side in (left, right):
            self.assertEqual((side["normal"]["prescribed"], side["tangential"]["prescribed"]), ("velocity", "traction"))
            self.assertEqual(side["normal"]["outward_velocity_m_s"], SIDE)
            self.assertEqual(side["temperature"]["type"], "insulating")
        self.assertEqual((top["normal"]["prescribed"], top["tangential"]["prescribed"]), ("traction", "traction"))
        self.assertEqual(rule["pressure"]["normalisation"], "none")
        self.assertTrue(rule["pressure"]["nullspace"].startswith("none"))
        self.assertEqual(rule["geometry"]["asthenosphere_layer_m"], ZB-HL)
        self.assertNotIn("sources", rule)                        # a prescription books nothing
        self.assertTrue(near(rule["initial_domain_volume_rate_m2_s"], 0, 2*SIDE*ZB))

    def test_dirichlet_only_where_material_enters(self):
        inflow = b.resolved_prescription(b.configuration(SPEC, RET))["segments"]["base"]
        still = b.resolved_prescription(b.configuration(SPEC, RET, side=0.0))["segments"]["base"]
        outflow = b.resolved_prescription(b.configuration(SPEC, RET, side=0.0, rule="declared_uniform",
                                                          basal=1e-11))["segments"]["base"]
        self.assertEqual([s["flow"] for s in (inflow, still, outflow)], ["inflow", "impermeable", "outflow"])
        self.assertEqual([s["temperature"]["type"] for s in (inflow, still, outflow)],
                         ["dirichlet", "dirichlet", "zero_conductive_flux"])
        self.assertEqual([s["composition"]["type"] for s in (inflow, still, outflow)],
                         ["fixed_on_inflow", "natural", "natural"])
        self.assertEqual(inflow["temperature"]["value_k"], TB)
        self.assertEqual(inflow["composition"]["raw_plastic_history"], 0.0)

    def test_free_surface_absorbs_a_declared_imbalance(self):
        u = -1e-11
        rule = b.resolved_prescription(b.configuration(SPEC, RET, rule="declared_uniform", basal=u))
        # Independent: net outward flux 2 v z_b + u W; the domain volume changes at minus that rate.
        self.assertTrue(near(rule["initial_domain_volume_rate_m2_s"], -(2*F(SIDE)*F(ZB)+F(u)*F(W)), 2*SIDE*ZB))

    def test_one_condition_per_component(self):
        both = b.mutated(b.configuration(SPEC, RET), (("segments", "base", "normal"), ["velocity", "traction"]))
        none = b.mutated(b.configuration(SPEC, RET), (("segments", "left", "tangential"), []))
        kept = copy.deepcopy(both)
        self.assertEqual(code_of(b.resolved_prescription, both), b.OVERDETERMINED)
        self.assertEqual(both, kept)
        self.assertEqual(code_of(b.resolved_prescription, none), b.UNDERDETERMINED)
        tangential = b.mutated(b.configuration(SPEC, RET), (("segments", "base", "tangential"), ["velocity"]))
        self.assertEqual(code_of(b.resolved_prescription, tangential), b.NOT_SELECTED)

    def test_closed_box_compatibility_and_pressure_nullspace(self):
        lid = [(("segments", "top", "normal"), ["velocity"]), (("top_outward_velocity_m_s",), 0.0)]
        balanced = b.mutated(b.configuration(SPEC, RET), *lid)
        self.assertEqual(code_of(b.resolved_prescription, balanced), b.NULLSPACE)
        unbalanced = b.mutated(b.configuration(SPEC, RET, rule="declared_uniform", basal=-2e-11), *lid)
        # Independent: 2 v z_b - 2e-11 W is not zero, so no incompressible solution exists without a traction boundary.
        self.assertNotEqual(2*F(SIDE)*F(ZB)-F(2e-11)*F(W), 0)
        self.assertEqual(code_of(b.resolved_prescription, unbalanced), b.INCOMPATIBLE_FLUX)
        missing = b.mutated(b.configuration(SPEC, RET), (("segments", "top", "normal"), ["velocity"]))
        self.assertEqual(code_of(b.resolved_prescription, missing), b.INVALID)

    def test_separation_needs_an_asthenosphere_layer(self):
        at_base = b.configuration(SPEC, RET, depth=HL)
        self.assertEqual(code_of(b.resolved_prescription, at_base), b.NO_LAYER)
        self.assertEqual(b.resolved_prescription(dict(at_base, consumer="i05_accounts"))["status"], b.PRESCRIPTION_ONLY)
        self.assertEqual(code_of(b.resolved_prescription, b.configuration(SPEC, RET, depth=0.9*HL,
                                                                           consumer="i05_accounts")), b.NO_LAYER)

    def test_incoming_state_and_unit_refusals(self):
        ocean = {"role": "oceanic_crust", "density_kg_m3": 2900.0, "heat_capacity_j_kg_k": 750.0,
                 "components": {"basalt": 1.0}}
        cases = {b.POTENTIAL: [(("incoming", "temperature_kind"), "potential")],
                 b.MELT: [(("incoming", "phase"), "partially_molten")],
                 b.NOT_ASTHENOSPHERE: [(("materials", "ocean"), ocean), (("incoming", "material"), "ocean")],
                 b.LOCAL_FIELD: [(("basal_rule",), "total_flux")],
                 b.SIDE_INFLOW: [(("side_outward_velocity_m_s",), [-SIDE, SIDE])]}
        for expected, changes in cases.items():
            with self.subTest(code=expected):
                self.assertEqual(code_of(b.resolved_prescription, b.mutated(b.configuration(SPEC, RET), *changes)),
                                 expected)
        for key, value in (("width_m", math.inf), ("width_m", True), ("width_m", "2e5"), ("extra", 1)):
            with self.subTest(key=key, value=value):
                self.assertEqual(code_of(b.resolved_prescription, config(**{key: value})), b.INVALID)
        self.assertEqual(code_of(b.resolved_prescription, config(side_outward_velocity_m_s=[0.0025, 0.0025])), b.WINDOW)
        self.assertEqual(code_of(b.resolved_prescription, b.mutated(
            b.configuration(SPEC, RET), (("incoming", "temperature_k"), TB+273.15))), b.WINDOW)
        self.assertEqual(code_of(b.per_aspect_year, 0.0025, 365.25*86400.0), b.UNIT)
        self.assertEqual(b.per_aspect_year(0.0025, 31556952.0), 0.0025/31556952.0)


class VolumeTests(unittest.TestCase):
    def test_constant_volume_is_the_special_case(self):
        q = 7.5e8
        result = b.volume_account(3e10, 3e10, [0.0]*4, [q], [q/2, q/2])
        self.assertTrue(result["inflow_equals_outflow"])
        self.assertEqual(result["change_m2"], 0.0)

    def test_moving_surface_changes_volume_without_crossing(self):
        before = b.polygon_area([(0.0, 0.0), (W, 0.0), (W, ZB), (0.0, ZB)])
        after = b.polygon_area([(0.0, 0.0), (W, 0.0), (W, ZB-750.0), (0.0, ZB-750.0)])
        self.assertEqual((before, after), (W*ZB, W*(ZB-750.0)))                 # shoelace against the rectangle
        inflow, outflow = 6.0e8, 7.5e8
        result = b.volume_account(before, after, [0.0, 0.0, 0.0, after-before], [inflow], [outflow])
        self.assertFalse(result["inflow_equals_outflow"])
        self.assertEqual(result["net_material_inflow_m2"], inflow-outflow)
        self.assertEqual(code_of(b.volume_account, before, after, [0.0]*4, [inflow], [outflow]), b.VOLUME)
        self.assertEqual(code_of(b.volume_account, before, after, [0.0, 0.0, 0.0, after-before], [outflow], [outflow]),
                         b.VOLUME)
        self.assertEqual(code_of(b.volume_account, before, before, [0.0]*4, [inflow], [outflow]), b.VOLUME)

    def test_corner_relaxation_of_the_literal_rule(self):
        # Flat surface offset eta at the corners, sides of height d + eta, base inflow fixed at 2 v d: over 10 Myr,
        # eta = eta0 exp(-2 v t / W) and the side export exceeds the inflow by W eta0 (1 - exp(-2 v t / W)).
        book = PAR["cookbook"]
        v, w, d, eta0, t = SIDE, book["width_m"], book["depth_m"], 800.0, 10*DT
        eta1 = eta0*math.exp(-2*v*t/w)
        side_out = 2*v*d*t+w*eta0*(1-math.exp(-2*v*t/w))
        result = b.volume_account(w*(d+eta0), w*(d+eta1), [0.0, 0.0, 0.0, w*(eta1-eta0)], [2*v*d*t], [side_out])
        self.assertFalse(result["inflow_equals_outflow"])
        self.assertAlmostEqual(result["change_m2"]/(w*eta0), math.exp(-0.25)-1, delta=1e-9)

    def test_one_flow_two_mesh_conventions(self):
        w0, lam1 = 1e5, 1.25
        face = b.strip_open_base(route="open_base", reference_width_m=w0, base_depth_m=ZB, lithosphere_thickness_m=HL,
                                 stretch_start=1.0, stretch_end=lam1)
        self.assertEqual(face["base_flux"], {"direction": "in", "volume_m2": w0*ZB*0.25})
        sides = [face["segments"][n]["swept_volume_m2"] for n in ("left", "right")]
        self.assertEqual(sides, [w0*ZB*0.125, w0*ZB*0.125])
        lagrange = b.volume_account(face["volume_start_m2"], face["volume_end_m2"],
                                    [s["swept_volume_m2"] for s in face["segments"].values()],
                                    [face["base_flux"]["volume_m2"]], [])
        self.assertFalse(lagrange["inflow_equals_outflow"])                   # no side outflow at all
        euler = w0*ZB*math.log(lam1)
        fixed = b.volume_account(w0*ZB, w0*ZB, [0.0]*4, [euler], [euler/2, euler/2])
        self.assertTrue(fixed["inflow_equals_outflow"])
        self.assertGreater(face["base_flux"]["volume_m2"]-euler, 0.1*euler)   # 0.25 against ln 1.25 = 0.223

    def test_free_surface_mesh_projection(self):
        slope, u = -0.02, (3e-11, 1e-12)
        top = b.Segment(W, ZB+slope*W, 0.0, ZB)
        normal = top.crossing_rate(u, top.normal_projection(u))
        self.assertLessEqual(abs(normal), 1e-12*abs(u[0])*W)
        # A mesh following only the vertical material velocity lets rock cross at -slope u_x W (exact on a line).
        crossing = top.crossing_rate(u, (0.0, u[1]))
        self.assertTrue(near(crossing, -F(slope)*F(u[0])*F(W), abs(crossing)))
        self.assertAlmostEqual(b.polygon_area([(0.0, 0.0), (2.0, 0.0), (0.0, 3.0)]), 3.0, delta=0.0)


def selected_account(**kwargs):
    return b.box_account(SPEC, RET, width=W, depth=ZB, dt=DT, parent="test", **kwargs)


def end_state(account, proposal):
    """Start plus booked transfers per cohort, and start plus booked caloric change: an end state that should close."""
    cohorts = account["domain"]["cohorts"]
    mass = {n: c["mass_kg"]+proposal["domain"]["cohorts"].get(n, {"mass_kg": 0.0})["mass_kg"] for n, c in cohorts.items()}
    mass.update({n: c["mass_kg"] for n, c in proposal["domain"]["new_cohorts"].items()})
    return mass, math.fsum([c["energy_j"] for c in cohorts.values()]+[proposal["domain"]["energy_j"]])


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.account = selected_account(side_velocity=SIDE, inflow_volume=2*SIDE*ZB*DT)
        self.proposal = b.propose_interval(self.account)

    def test_constant_volume_box_against_closed_forms(self):
        layers, v_dt = RET["layers"], F(SIDE)*F(DT)
        rho_a, cp_a = F(RHO_A), F(CP_A)
        gain = 2*v_dt*sum((rho_a-F(l["density_kg_m3"]))*F(l["thickness_m"]) for l in layers)
        e_in = rho_a*cp_a*(F(TB)-F(TREF))*2*v_dt*F(ZB)
        e_out = 2*v_dt*(sum(F(l["density_kg_m3"])*F(l["heat_capacity_j_kg_k"])*F(l["thickness_m"])
                            * ((F(l["temperature_k"][0])+F(l["temperature_k"][1]))/2-F(TREF)) for l in layers)
                        + rho_a*cp_a*(F(ZB)-F(HL))*(F(TB)-F(TREF)))
        heat = ((-F(RET["surface_heat_flow_w_m2"])+sum(F(l["radiogenic_w_m3"])*F(l["thickness_m"]) for l in layers))
                * F(W)*F(DT)+F(PAR["heat_fraction"])*F(PAR["dissipation_j"]))
        self.assertGreater(gain, 0)                                # constant volume, yet the domain gains mass
        self.assertTrue(near(self.proposal["domain"]["mass_kg"], gain, 2*RHO_A*2*SIDE*ZB*DT))
        self.assertTrue(near(self.proposal["domain"]["energy_j"], e_in-e_out+heat, e_in+e_out+abs(heat)))
        self.assertTrue(self.proposal["volume"]["inflow_equals_outflow"])
        self.assertEqual((self.proposal["status"], self.proposal["evidence"], self.proposal["stokes_solution"]),
                         (b.PROPOSED, b.SUPPLIED_ONLY, False))

    def test_components_sources_and_receivers_book_consistently(self):
        p = self.proposal
        self.assertEqual(p["sources"]["exterior-asthenosphere"]["mass_kg"], -(RHO_A*(2*SIDE*ZB*DT)))
        new = list(p["domain"]["new_cohorts"].values())
        self.assertEqual(len(new), 1)
        self.assertEqual((new[0]["material"], new[0]["raw_plastic_history"], new[0]["temperature_k"]),
                         ("asthenosphere", 0.0, TB))
        for layer in RET["layers"]:
            exported = 2*layer["density_kg_m3"]*(SIDE*DT*layer["thickness_m"])
            self.assertTrue(near(p["domain"]["cohorts"][layer["name"]]["mass_kg"], -exported, exported))
            received = math.fsum(p["receivers"][r]["components_kg"][layer["name"]] for r in ("left-far-field",
                                                                                          "right-far-field"))
            self.assertTrue(near(received, exported, exported))
        debit = -p["sources"]["exterior-asthenosphere"]["mass_kg"]
        credit = math.fsum(r["mass_kg"] for r in p["receivers"].values())
        self.assertTrue(near(p["domain"]["mass_kg"], debit-credit, debit+credit))

    def test_caller_account_is_never_modified(self):
        kept = copy.deepcopy(self.account)
        b.propose_interval(self.account)
        self.assertEqual(self.account, kept)

    def test_datum_shift_moves_energy_by_capacity_only(self):
        for new in (0.0, 1000.0):
            with self.subTest(datum=new):
                moved = b.propose_interval(b.shift_datum(self.account, new))
                self.assertEqual(moved["domain"]["mass_kg"], self.proposal["domain"]["mass_kg"])
                # Every material has Cp 750: the caloric change moves by (T_ref - T_new) Cp dM, nothing else.
                shift = F(moved["domain"]["energy_j"])-F(self.proposal["domain"]["energy_j"])
                expected = (F(TREF)-F(new))*F(CP_A)*F(self.proposal["domain"]["mass_kg"])
                scale = 4*abs(F(self.proposal["thermal"]["advected_in_j"]))+abs(expected)
                self.assertLessEqual(abs(shift-expected), TOL*scale)
        mixed = b.mutated(self.account, (("domain", "cohorts", "asthenosphere-initial", "datum_k"), 0.0))
        self.assertEqual(code_of(b.propose_interval, mixed), b.DATUM)

    def test_flow_work_is_work_not_heat(self):
        mat = b.Material("a", "asthenosphere", RHO_A, CP_A, (("a", 1.0),))
        pressure = 4.0e9
        self.assertAlmostEqual((b.specific_enthalpy(mat, TB, pressure, TREF)-mat.specific_energy(TB, TREF))*RHO_A,
                               pressure, delta=1e-6*pressure)
        self.assertEqual(b.flow_work(-pressure, -2.5), pressure*2.5)   # compression, inflow: the exterior works
        self.assertLess(b.flow_work(-pressure, 2.5), 0)                # outflow: the domain works on the exterior
        stock = self.account["sources"]["exterior-asthenosphere"]["mass_kg"]
        enthalpy = b.mutated(self.account, (("sources", "exterior-asthenosphere", "energy_j"),
                                            stock*b.specific_enthalpy(mat, TB, pressure, TREF)))
        self.assertEqual(code_of(b.propose_interval, enthalpy), b.SOURCE_STATE)
        as_heat = b.mutated(self.account, (("interior", "boundary_work_j"), 1.0))
        self.assertEqual(code_of(b.propose_interval, as_heat), b.THERMAL)
        self.assertNotIn("boundary_work_in_j", self.proposal["thermal"])

    def test_mechanical_ledger(self):
        self.assertEqual(self.proposal["mechanical"]["status"], "CLOSED")
        gravity = self.account["interior"]["gravity_work_j"]
        cases = ((("interior", "gravity_work_j"), gravity*(1+1e-7)), (("boundary_work_in_j", "top"), 1.0))
        for path, value in cases:
            with self.subTest(path=path):
                self.assertEqual(code_of(b.propose_interval, b.mutated(self.account, (path, value))), b.LEDGER)
        no_work = b.mutated(self.account, (("boundary_work_in_j",), b.DELETE))
        self.assertEqual(code_of(b.propose_interval, no_work), b.LEDGER)            # gravity without boundary work
        neither = b.mutated(no_work, (("interior", "gravity_work_j"), b.DELETE))
        self.assertEqual(b.propose_interval(neither)["mechanical"]["status"], "NOT_SUPPLIED")

    def test_zero_flow_books_only_heat_exchange(self):
        still = selected_account()
        p = b.propose_interval(still)
        self.assertEqual((p["sources"], p["receivers"], p["domain"]["mass_kg"]), ({}, {}, 0.0))
        heat = math.fsum(still["conduction_in_j"].values())+still["interior"]["radiogenic_j"]+PAR["dissipation_j"]
        self.assertTrue(near(p["domain"]["energy_j"], heat, abs(heat)+PAR["dissipation_j"]))

    def test_reversed_flow_exports_the_actual_state(self):
        volume = 2e8
        state = (1600.0, [1590.0, 1610.0])
        account = selected_account(base_outflow=(volume, 1605.0), surface_swept=-volume, asthenosphere_state=state)
        p = b.propose_interval(account)
        credit = p["receivers"]["exterior-asthenosphere-sink"]
        self.assertTrue(near(credit["energy_j"], F(RHO_A)*F(volume)*F(CP_A)*(F(1605.0)-F(TREF)), credit["energy_j"]))
        self.assertEqual(p["sources"], {})
        refusals = {"reset to the inflow temperature": (("streams", 0, "temperature_k"), TB),
                    "into the finite source": (("streams", 0, "receiver"), "exterior-asthenosphere"),
                    "no stated state": (("streams", 0, "temperature_k"), b.DELETE)}
        for name, change in refusals.items():
            with self.subTest(name=name):
                item = b.mutated(account, change)
                if name == "into the finite source":
                    item["receivers"].append("exterior-asthenosphere")
                self.assertEqual(code_of(b.propose_interval, item), b.OUTFLOW)
        # 90% leaving at 1590 K would leave a remainder at (1600 - 0.9 x 1590)/0.1 = 1690 K: not this cohort's state.
        mass = RHO_A*W*(ZB-HL)
        hot = selected_account(base_outflow=(0.9*mass/RHO_A, 1590.0), surface_swept=-0.9*mass/RHO_A,
                               asthenosphere_state=state)
        self.assertEqual(code_of(b.propose_interval, hot), b.OUTFLOW)


class ExhaustionTests(unittest.TestCase):
    def stocked(self, account, mass):
        per_kg = CP_A*(TB-TREF)
        return b.mutated(account, (("sources", "exterior-asthenosphere", "mass_kg"), mass),
                         (("sources", "exterior-asthenosphere", "energy_j"), mass*per_kg))

    def setUp(self):
        self.volume = 3.3e7
        account = selected_account(inflow_volume=self.volume, surface_swept=self.volume)
        del account["boundary_work_in_j"], account["interior"]["gravity_work_j"]
        self.account = account
        self.demand = RHO_A*self.volume

    def test_exact_depletion_and_one_ulp_overdraft(self):
        p = b.propose_interval(self.stocked(self.account, self.demand))
        row = p["sources"]["exterior-asthenosphere"]
        self.assertEqual((row["remaining_mass_kg"], row["remaining_energy_j"]), (0.0, 0.0))
        short = self.stocked(self.account, math.nextafter(self.demand, 0.0))
        kept = copy.deepcopy(short)
        self.assertEqual(code_of(b.propose_interval, short), b.EXHAUSTED)
        self.assertEqual(short, kept)

    def test_joint_demand_is_refused_never_clipped(self):
        split = self.stocked(self.account, 0.6*self.demand)
        split["segments"] = {"west": {"kind": "base", "mesh": "fixed", "swept_volume_m2": 0.0},
                             "east": {"kind": "base", "mesh": "fixed", "swept_volume_m2": 0.0},
                             **{k: v for k, v in split["segments"].items() if k != "base"}}
        split["conduction_in_j"] = {"west": 0.0, "east": 0.0,
                                    **{k: v for k, v in split["conduction_in_j"].items() if k != "base"}}
        split["streams"] = [{"segment": s, "direction": "in", "volume_m2": self.volume/2,
                             "source": "exterior-asthenosphere"} for s in ("west", "east")]
        self.assertEqual(code_of(b.propose_interval, split), b.EXHAUSTED)
        half = b.mutated(split, (("streams",), split["streams"][:1]), (("segments", "top", "swept_volume_m2"),
                                                                        self.volume/2),
                         (("domain", "volume_end_m2"), split["domain"]["volume_start_m2"]+self.volume/2))
        self.assertEqual(b.propose_interval(half)["sources"]["exterior-asthenosphere"]["mass_kg"],
                         -(RHO_A*(self.volume/2)))

    def test_refusal_is_atomic(self):
        good = self.stocked(self.account, 2*self.demand)
        first = b.propose_interval(good)
        bad = b.mutated(good, (("streams", 0, "volume_m2"), 3*self.volume))
        self.assertEqual(code_of(b.propose_interval, bad), b.VOLUME)
        self.assertEqual(b.propose_interval(good), first)


class InterfaceTests(unittest.TestCase):
    def test_i05_open_base_creates_one_asthenosphere_cohort(self):
        face = b.strip_open_base(route="open_base", reference_width_m=1e5, base_depth_m=HL,
                                 lithosphere_thickness_m=HL, stretch_start=1.0, stretch_end=1.25)
        self.assertEqual(face["placement"]["inflow_depth_range_m"], [HL/1.25, HL])
        low, high = face["placement"]["inflow_depth_range_m"]
        self.assertEqual(face["placement"]["width_m"]*(high-low), face["base_flux"]["volume_m2"])  # 1.25e5 x 2e4
        p = b.propose_interval(b.strip_account(SPEC, RET, face, depth=HL, dt=DT, parent="i05"))
        self.assertEqual(p["domain"]["cohorts"], {})                         # the lithosphere inventory is untouched
        (new,) = p["domain"]["new_cohorts"].values()
        self.assertEqual(new["mass_kg"], RHO_A*2.5e9)
        self.assertEqual(new["energy_j"], RHO_A*2.5e9*(CP_A*(TB-TREF)))
        self.assertEqual((new["role"], new["entry_interval_s"], new["segment"]), ("asthenosphere", [0.0, DT], "base"))

    def test_i05_shortening_exports_the_actual_state(self):
        face = b.strip_open_base(route="open_base", reference_width_m=1e5, base_depth_m=ZB, lithosphere_thickness_m=HL,
                                 stretch_start=1.0, stretch_end=0.875)
        self.assertEqual(face["base_flux"], {"direction": "out", "volume_m2": 1e5*ZB*0.125})
        p = b.propose_interval(b.strip_account(SPEC, RET, face, depth=ZB, dt=DT, parent="i05", outgoing=1605.0,
                                               asthenosphere_state=(1600.0, [1590.0, 1610.0])))
        self.assertEqual(set(p["domain"]["cohorts"]), {"asthenosphere-initial"})
        self.assertEqual((p["domain"]["new_cohorts"], p["sources"]), ({}, {}))
        self.assertEqual(code_of(b.strip_open_base, route="closed", reference_width_m=1e5, base_depth_m=ZB,
                                 lithosphere_thickness_m=HL, stretch_start=1.0, stretch_end=1.2), b.CLOSED)
        self.assertEqual(code_of(b.strip_open_base, route="open_base", reference_width_m=1e5, base_depth_m=ZB,
                                 lithosphere_thickness_m=HL, stretch_start=1.0, stretch_end=1.5), b.WINDOW)

    def test_prescription_and_diagnostics_stay_distinct(self):
        rule = b.resolved_prescription(b.configuration(SPEC, RET))
        account = selected_account(side_velocity=SIDE, inflow_volume=2*SIDE*ZB*DT)
        p = b.propose_interval(account)
        self.assertTrue({"segments", "pressure"} <= set(rule) and not {"sources", "domain"} & set(rule))
        self.assertTrue({"sources", "domain"} <= set(p) and not {"segments", "pressure"} & set(p))
        end, energy = end_state(account, p)
        volume = account["domain"]["volume_end_m2"]
        diagnosis = b.diagnose_endpoint(account, p, end, energy, volume)
        self.assertEqual((diagnosis["status"], diagnosis["stokes_solution"]), (b.ENDPOINT_CLOSES, False))
        self.assertEqual(code_of(b.diagnose_endpoint, account, p, end, energy*(1+1e-9), volume), b.ENDPOINT)
        self.assertEqual(code_of(b.diagnose_endpoint, account, p, dict(end, extra=1.0), energy, volume), b.ENDPOINT)


class InventoryTests(unittest.TestCase):
    """Cohort masses at their reference densities must fill the domain at both ends; nothing is rescaled."""

    def setUp(self):
        self.account = selected_account(side_velocity=SIDE, inflow_volume=2*SIDE*ZB*DT)

    def test_inventory_fills_the_domain_at_both_ends(self):
        table = self.account["materials"]
        exact = sum(F(c["mass_kg"])/F(table[c["material"]]["density_kg_m3"])
                    for c in self.account["domain"]["cohorts"].values())
        self.assertTrue(near(exact, F(W)*F(ZB), W*ZB))            # retained layers plus 50 km of asthenosphere
        p = b.propose_interval(self.account)
        self.assertTrue(near(p["volume"]["inventory_start_m2"], exact, W*ZB))
        self.assertTrue(near(p["volume"]["inventory_end_m2"], exact, W*ZB))      # constant volume
        rising = selected_account(inflow_volume=3.3e7, surface_swept=3.3e7)
        q = b.propose_interval(rising)
        self.assertTrue(near(q["volume"]["inventory_end_m2"], F(W)*F(ZB)+F(3.3e7), W*ZB))
        self.assertEqual(q["start_cohorts"]["asthenosphere-initial"]["mass_kg"],
                         rising["domain"]["cohorts"]["asthenosphere-initial"]["mass_kg"])

    def test_doubled_or_perturbed_inventory_is_refused_atomically(self):
        doubled = copy.deepcopy(self.account)
        for item in doubled["domain"]["cohorts"].values():                   # the same states, twice the rock
            item["mass_kg"], item["energy_j"] = 2*item["mass_kg"], 2*item["energy_j"]
        heavier = copy.deepcopy(self.account)                               # 4 m2 extra in 3e10 m2 at its mean state
        crust = heavier["domain"]["cohorts"][RET["layers"][0]["name"]]
        crust["mass_kg"], crust["energy_j"] = crust["mass_kg"]*(1+1e-9), crust["energy_j"]*(1+1e-9)
        for name, account in (("doubled", doubled), ("heavier", heavier)):
            with self.subTest(case=name):
                kept = copy.deepcopy(account)
                self.assertEqual(code_of(b.propose_interval, account), b.INVENTORY)
                self.assertEqual(account, kept)


class ThermalBoundaryTests(unittest.TestCase):
    """Conduction obeys the law's condition for each segment's kind and actual flow regime, from one shared table."""
    TABLE = {("base", "fixed", "inflow"): "dirichlet", ("base", "fixed", "impermeable"): "dirichlet",
             ("base", "fixed", "outflow"): "zero_conductive_flux", ("side", "tangential", "outflow"): "insulating",
             ("side", "fixed", "impermeable"): "insulating", ("side", "material", "impermeable"): "no_lateral_conduction",
             ("surface", "free_surface", "impermeable"): "dirichlet", ("surface", "free_surface", "outflow"): "dirichlet"}

    def test_one_table_for_prescription_and_accounts(self):
        for key, expected in self.TABLE.items():
            with self.subTest(segment=key):
                self.assertEqual(b.thermal_condition(*key), expected)
        configurations = {"inflow": b.configuration(SPEC, RET), "impermeable": b.configuration(SPEC, RET, side=0.0),
                          "outflow": b.configuration(SPEC, RET, side=0.0, rule="declared_uniform", basal=1e-11)}
        for flow, item in configurations.items():
            with self.subTest(base=flow):
                seg = b.resolved_prescription(item)["segments"]
                self.assertEqual((seg["base"]["flow"], seg["base"]["temperature"]["type"]),
                                 (flow, self.TABLE[("base", "fixed", flow)]))
                self.assertEqual((seg["left"]["temperature"]["type"], seg["top"]["temperature"]["type"]),
                                 ("insulating", "dirichlet"))

    def test_insulating_sides_and_outflow_base_take_no_heat(self):
        account = selected_account(side_velocity=SIDE, inflow_volume=2*SIDE*ZB*DT)
        self.assertEqual(b.propose_interval(account)["thermal"]["boundary_conditions"],
                         {"base": "dirichlet", "left": "insulating", "right": "insulating", "top": "dirichlet"})
        reverse = selected_account(base_outflow=(2e8, 1605.0), surface_swept=-2e8,
                                   asthenosphere_state=(1600.0, [1590.0, 1610.0]))
        self.assertEqual(b.propose_interval(reverse)["thermal"]["boundary_conditions"]["base"], "zero_conductive_flux")
        for original, name, value in ((account, "left", 1e12), (account, "right", -1e12), (reverse, "base", 1e12),
                                      (reverse, "base", 5e-324), (reverse, "left", 1.0)):
            with self.subTest(segment=name, value=value):
                item = b.mutated(original, (("conduction_in_j", name), value))
                kept = copy.deepcopy(item)
                self.assertEqual(code_of(b.propose_interval, item), b.THERMAL_BOUNDARY)
                self.assertEqual(item, kept)

    def test_declared_routes_keep_their_heat(self):
        # Inflow base at the lithosphere base: the retained mantle heat flow enters through the Dirichlet base.
        book = b.box_account(SPEC, RET, width=W, depth=HL, dt=DT, parent="lithosphere-base", side_velocity=SIDE,
                             inflow_volume=2*SIDE*HL*DT)
        self.assertGreater(book["conduction_in_j"]["base"], 0)
        self.assertEqual(b.propose_interval(book)["thermal"]["boundary_conditions"]["base"], "dirichlet")
        # Impermeable base: Dirichlet, so its conductive heat is the solved flux.
        still = b.mutated(selected_account(), (("conduction_in_j", "base"), 1e12))
        self.assertEqual(b.propose_interval(still)["thermal"]["conduction_in_j"]["base"], 1e12)
        # An owned surface exchange keeps the fixed surface temperature and its conductive heat.
        crossing = 1e6
        erosion = selected_account(surface_swept=-crossing)
        erosion["streams"] = [{"segment": "top", "direction": "out", "volume_m2": crossing,
                               "cohort": RET["layers"][0]["name"], "temperature_k": TS,
                               "receiver": "surface-process-sink"}]
        erosion["receivers"].append("surface-process-sink")
        erosion["segments"]["top"]["owner"] = "surface-process"
        self.assertLess(erosion["conduction_in_j"]["top"], 0)
        p = b.propose_interval(erosion)
        self.assertEqual((p["thermal"]["boundary_conditions"]["top"], p["thermal"]["conduction_in_j"]["top"]),
                         ("dirichlet", erosion["conduction_in_j"]["top"]))
        # The I05 strip's material-following sides: the supported zero-heat account passes; lateral heat is refused.
        face = b.strip_open_base(route="open_base", reference_width_m=1e5, base_depth_m=ZB, lithosphere_thickness_m=HL,
                                 stretch_start=1.0, stretch_end=1.2)
        strip = b.strip_account(SPEC, RET, face, depth=ZB, dt=DT, parent="i05")
        self.assertEqual(b.propose_interval(strip)["thermal"]["boundary_conditions"]["left"], "no_lateral_conduction")
        self.assertEqual(code_of(b.propose_interval, b.mutated(strip, (("conduction_in_j", "right"), 1e12))),
                         b.THERMAL_BOUNDARY)


class EndpointBindingTests(unittest.TestCase):
    """diagnose_endpoint recomputes the proposal from its account; a claimed identity never authenticates contents."""

    def setUp(self):
        self.account = selected_account(side_velocity=SIDE, inflow_volume=2*SIDE*ZB*DT)
        self.proposal = b.propose_interval(self.account)
        self.mass, self.energy = end_state(self.account, self.proposal)
        self.volume = self.account["domain"]["volume_end_m2"]

    def refusal(self, account, proposal, mass, energy, volume):
        records = (account, proposal, mass)
        kept = copy.deepcopy(records)
        code = code_of(b.diagnose_endpoint, account, proposal, mass, energy, volume)
        self.assertEqual(records, kept)
        return code

    def test_own_proposal_closes(self):
        d = b.diagnose_endpoint(self.account, self.proposal, self.mass, self.energy, self.volume)
        self.assertEqual((d["status"], d["stokes_solution"]), (b.ENDPOINT_CLOSES, False))
        self.assertTrue(near(d["volume_residual_m2"], 0, W*ZB) and near(d["inventory_residual_m2"], 0, W*ZB))

    def test_foreign_or_edited_account_is_refused(self):
        name = RET["layers"][0]["name"]
        item = self.account["domain"]["cohorts"][name]
        warmer = item["mass_kg"]*CP_A*(500.0-TREF)                # a start state inside its 273-633 K range
        top = self.account["conduction_in_j"]["top"]
        changes = {"foreign parent": ([(("parent",), "another-column")], 0.0),
                   "foreign interval": ([(("interval_s",), [DT, 2*DT])], 0.0),
                   "conduction edited after booking": ([(("conduction_in_j", "top"), 2*top)], top),
                   "start energy edited after booking": ([(("domain", "cohorts", name, "energy_j"), warmer)],
                                                         warmer-item["energy_j"])}
        for label, (edits, energy_shift) in changes.items():
            with self.subTest(changed=label):
                account = b.mutated(self.account, *edits)
                self.assertEqual(b.propose_interval(account)["status"], b.PROPOSED)    # valid in its own right
                # The end energy matches the edited account, so only the binding can refuse.
                self.assertEqual(self.refusal(account, self.proposal, self.mass, self.energy+energy_shift, self.volume),
                                 b.FOREIGN)

    def test_edited_deltas_and_other_proposals_are_refused(self):
        shift, keys = 1e12, ("status", "law", "parent", "interval_s")
        edited = b.mutated(self.proposal, (("domain", "energy_j"), self.proposal["domain"]["energy_j"]+shift))
        self.assertEqual([edited[k] for k in keys], [self.proposal[k] for k in keys])   # the claimed identity matches
        self.assertEqual(self.refusal(self.account, edited, self.mass, self.energy+shift, self.volume), b.FOREIGN)
        name = "asthenosphere-initial"
        delta = self.proposal["domain"]["cohorts"][name]["mass_kg"]
        heavier_export = b.mutated(self.proposal, (("domain", "cohorts", name, "mass_kg"), 2*delta))
        mass = dict(self.mass, **{name: self.mass[name]+delta})                     # consistent with the edit
        self.assertEqual(self.refusal(self.account, heavier_export, mass, self.energy, self.volume), b.FOREIGN)
        other = b.propose_interval(selected_account())            # same parent and interval, another account
        self.assertEqual([other[k] for k in keys], [self.proposal[k] for k in keys])
        self.assertEqual(self.refusal(self.account, other, self.mass, self.energy, self.volume), b.FOREIGN)
        self.assertEqual(self.refusal(self.account, None, self.mass, self.energy, self.volume), b.FOREIGN)

    def test_end_geometry_is_compared(self):
        self.assertEqual(self.refusal(self.account, self.proposal, self.mass, self.energy, self.volume*(1+1e-9)),
                         b.ENDPOINT)
        rising = selected_account(inflow_volume=3.3e7, surface_swept=3.3e7)
        p = b.propose_interval(rising)
        mass, energy = end_state(rising, p)
        end, start = rising["domain"]["volume_end_m2"], rising["domain"]["volume_start_m2"]
        self.assertEqual(b.diagnose_endpoint(rising, p, mass, energy, end)["status"], b.ENDPOINT_CLOSES)
        self.assertEqual(self.refusal(rising, p, mass, energy, start), b.ENDPOINT)       # the start geometry
        self.assertEqual(self.refusal(rising, p, {n: 2*m for n, m in mass.items()}, 2*energy, 2*end), b.ENDPOINT)


class StripGuardTests(unittest.TestCase):
    """The I05 lithosphere base h0/lam stays at or above the fixed base at both ends of the interval."""

    def code(self, depth, start, end):
        return code_of(b.strip_open_base, route="open_base", reference_width_m=1e5, base_depth_m=depth,
                       lithosphere_thickness_m=HL, stretch_start=start, stretch_end=end)

    def test_reviewed_case_is_refused_at_either_end(self):
        self.assertGreater(F(HL)/F(0.6), F(ZB))                  # 166.7 km of lithosphere under a 150 km base
        self.assertEqual(self.code(ZB, 0.6, 1.0), b.NO_LAYER)
        self.assertEqual(self.code(ZB, 1.0, 0.6), b.NO_LAYER)

    def test_equality_and_just_outside_at_start_and_end(self):
        edge, lam = 160000.0, 0.625                              # 5/8 is exact, so h0/lam is exactly 160 km
        self.assertEqual(F(HL)/F(lam), F(edge))
        below, thinner = math.nextafter(edge, 0.0), math.nextafter(lam, 0.0)
        self.assertGreater(HL/thinner, edge)                     # one ulp less stretch: the lithosphere base deeper
        for start, end in ((lam, 1.0), (1.0, lam)):
            with self.subTest(start=start, end=end):
                self.assertIsNone(self.code(edge, start, end))
                self.assertEqual(self.code(below, start, end), b.NO_LAYER)
        self.assertEqual(self.code(edge, thinner, 1.0), b.NO_LAYER)
        self.assertEqual(self.code(edge, 1.0, thinner), b.NO_LAYER)
        grown = b.strip_open_base(route="open_base", reference_width_m=1e5, base_depth_m=edge,
                                  lithosphere_thickness_m=HL, stretch_start=lam, stretch_end=1.0)
        self.assertEqual(grown["placement"]["inflow_depth_range_m"][0], grown["placement"]["lithosphere_base_depth_m"])

    def test_equality_exports_the_whole_asthenosphere_and_no_lithosphere(self):
        face = b.strip_open_base(route="open_base", reference_width_m=1e5, base_depth_m=160000.0,
                                 lithosphere_thickness_m=HL, stretch_start=1.0, stretch_end=0.625)
        self.assertEqual(face["placement"]["lithosphere_base_depth_m"], 160000.0)
        account = b.strip_account(SPEC, RET, face, depth=160000.0, dt=DT, parent="i05-edge", outgoing=TB)
        layer = account["domain"]["cohorts"]["asthenosphere-initial"]
        p = b.propose_interval(account)
        self.assertEqual(p["domain"]["cohorts"], {"asthenosphere-initial": {"mass_kg": -layer["mass_kg"],
                                                                            "energy_advected_j": -layer["energy_j"]}})
        self.assertEqual(p["volume"]["inventory_end_m2"], 1e5*HL)           # the lithosphere alone fills the column


class PureShearTests(unittest.TestCase):
    """The independent mechanical control: exact Newtonian pure shear, each power from its own physics, no solve."""

    def setUp(self):
        self.a, self.eta, self.g = 2*SIDE/W, PAR["pure_shear"]["viscosity_pa_s"], CFG["gravity_m_s2"]
        self.field = b.PureShear(F(self.a), F(self.eta), F(RHO_A), F(self.g), F(W), F(ZB))
        self.powers = b.pure_shear_powers(self.field)

    def test_powers_equal_the_closed_forms(self):
        a, eta, rho, g, w, h = F(self.a), F(self.eta), F(RHO_A), F(self.g), F(W), F(ZB)
        p = self.powers
        self.assertEqual(p["base"], a*rho*g*w*h**2)
        self.assertEqual(p["left"], p["right"])
        self.assertEqual(p["left"]+p["right"], 4*eta*a**2*w*h-a*rho*g*w*h**2/2)
        self.assertEqual(p["gravity"], -a*rho*g*w*h**2/2)
        self.assertEqual(p["dissipation"], 4*eta*a**2*w*h)
        self.assertEqual(p["top"], 0)
        self.assertEqual(p["base"]+p["left"]+p["right"]+p["top"]+p["gravity"], p["dissipation"])

    def test_field_is_the_stated_newtonian_solution(self):
        f = self.field
        a, eta, rho, g, w, h = f.a, f.eta, f.rho, f.g, f.width, f.height
        for x in (-w/2, F(0), w/3, w/2):
            for y in (F(0), h/3, h):
                with self.subTest(x=x, y=y):
                    self.assertEqual(f.stress(x, y), (4*eta*a-rho*g*(h-y), -rho*g*(h-y), 0))
                    self.assertEqual(f.momentum_residual(x, y), (0, 0))
                    rate = f.strain_rate(x, y)
                    self.assertEqual(rate[0]+rate[1], 0)                     # incompressible
        self.assertEqual((f.velocity(w/2, h/3)[0], f.velocity(-w/2, h/3)[0]), (a*w/2, -a*w/2))   # sides move out
        self.assertEqual(f.velocity(w/3, F(0))[1], a*h)                     # basal inflow a H
        self.assertEqual((f.velocity(w/3, h)[1], f.stress(w/3, h)[1:]), (0, (0, 0)))  # stationary, traction-free top
        self.assertTrue(near(float(a*h), 2*F(SIDE)*F(ZB)/F(W), float(a*h)))  # the selected reference rule

    def test_tool_ledger_closes_and_refuses_sign_and_double_count_errors(self):
        account = b.pure_shear_account(SPEC, self.field, DT, self.powers, "pure-shear")
        kept = copy.deepcopy(account)
        self.assertEqual(b.propose_interval(account)["mechanical"]["status"], "CLOSED")
        self.assertEqual(account, kept)
        work, inner = account["boundary_work_in_j"], account["interior"]
        # Oracle written here: the lithostatic base pressure times the inflow volume, P_b V_in, is the base work.
        p_base, v_in = RHO_A*self.g*ZB, account["streams"][0]["volume_m2"]
        self.assertTrue(near(work["base"], F(p_base)*F(v_in), p_base*v_in))
        lithostatic_side = float(-F(self.a)*F(RHO_A)*F(self.g)*F(W)*F(ZB)**2/4*F(DT))   # without viscous traction
        errors = {"inward normal": [(("boundary_work_in_j", n), -work[n]) for n in ("base", "left", "right")],
                  "base compression booked as tension": [(("boundary_work_in_j", "base"), -work["base"])],
                  "reversed gravity": [(("interior", "gravity_work_j"), -inner["gravity_work_j"])],
                  "base flow work counted twice": [(("boundary_work_in_j", "base"), 2*work["base"])],
                  "viscous side traction omitted": [(("boundary_work_in_j", n), lithostatic_side)
                                                    for n in ("left", "right")],
                  "dissipation omitted": [(("interior", "dissipation_j"), 0.0)]}
        for name, changes in errors.items():
            with self.subTest(error=name):
                item = b.mutated(account, *changes)
                kept = copy.deepcopy(item)
                self.assertEqual(code_of(b.propose_interval, item), b.LEDGER)
                self.assertEqual(item, kept)
        as_heat = b.mutated(account, (("interior", "boundary_work_j"), work["base"]))
        self.assertEqual(code_of(b.propose_interval, as_heat), b.THERMAL)


class ControlTests(unittest.TestCase):
    def test_every_grouped_control_passes(self):
        for name, control in b.CONTROLS:
            with self.subTest(control=name):
                data = control(SPEC, RET, time.perf_counter()+b.POLICY["maximum_seconds"])
                failed = [key for key, ok in data["checks"].items() if not ok]
                self.assertTrue(data["passed"], failed)

    def test_expired_budget_stops_every_control(self):
        for name, control in b.CONTROLS:
            with self.subTest(control=name), self.assertRaises(RuntimeError):
                control(SPEC, RET, time.perf_counter()-1.0)


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(b.CASE.read_text(encoding="utf-8"))

    def test_case_equals_executable_and_retained_cases(self):
        self.assertEqual(SPEC["control_policy"], b.POLICY)
        self.assertEqual(SPEC["control_parameters"], b.PARAMETERS)
        self.assertEqual(SPEC["units"], b.UNITS)
        self.assertEqual(SPEC["decision"]["selected_law"], b.LAW)
        self.assertTrue(b.check_retained(SPEC, RET))
        self.assertNotIn("BREAKUP_CERTIFIED", json.dumps(SPEC))

    def test_case_mutations_refused(self):
        mutations = ((("schema",), "atlas.other", b.INVALID), (("status",), "CANON", b.INVALID),
                     (("decision", "selected_law"), "atlas.lithostatic-base", b.NOT_SELECTED),
                     (("units", "temperature"), "degC", b.UNIT),
                     (("control_policy", "closure_relative"), 1e-9, b.INVALID),
                     (("control_policy", "scope"), "solved basal flow", b.INVALID),
                     (("control_parameters", "configuration", "base_depth_m"), 2e5, b.INVALID),
                     (("extra",), 1, b.INVALID))
        for path, value, expected in mutations:
            with self.subTest(path=path):
                self.assertEqual(code_of(b.validate_case, b.mutated(self.raw, (path, value))), expected)

    def test_retained_mismatches_refused(self):
        for key, value in (("base_temperature_k", 1340.0), ("lithosphere_thickness_m", 1.2e5),
                           ("surface_temperature_k", 293.0), ("gravity_m_s2", 9.8)):
            with self.subTest(key=key):
                spec = b.mutated(SPEC, (("control_parameters", "configuration", key), value))
                self.assertEqual(code_of(b.check_retained, spec, RET), b.RETAINED_MISMATCH)

    def test_structural_parameter_refusals(self):
        cases = (((("maximum_seconds",), 11.0), True, b.INVALID), ((("closure_relative",), 1e-6), True, b.INVALID),
                 ((("configuration", "base_depth_m"), 1e5), False, b.NO_LAYER),
                 ((("configuration", "aspect_year_s"), 31557600.0), False, b.UNIT),
                 ((("configuration", "surface_temperature_k"), 200.0), False, b.WINDOW),
                 ((("heat_fraction",), 1.5), False, b.INVALID), ((("datum_shifts_k",), [273.0]), False, b.INVALID),
                 ((("under_balance_factor",), 1.0), False, b.INVALID), ((("surface_slope",), 0.01), False, b.INVALID),
                 ((("reversed", "outgoing_temperature_k"), 1620.0), False, b.WINDOW),
                 ((("reversed", "cohort_temperature_range_k"), [1590.0, 1613.0]), False, b.INVALID),
                 ((("strip", "stretch_compression"), 1.1), False, b.INVALID),
                 ((("pure_shear", "viscosity_pa_s"), 0.0), False, b.INVALID))
        for (path, value), policy, expected in cases:
            with self.subTest(path=path):
                par, pol = b.PARAMETERS, b.POLICY
                if policy:
                    pol = b.mutated(pol, (path, value))
                else:
                    par = b.mutated(par, (path, value))
                self.assertEqual(code_of(b.validate_parameters, par, pol), expected)
        self.assertTrue(b.validate_parameters(copy.deepcopy(b.PARAMETERS), copy.deepcopy(b.POLICY)))
        self.assertEqual(SPEC["control_parameters"], b.PARAMETERS)          # the executable's constants untouched


class BindingTests(unittest.TestCase):
    def test_bound_files_exist(self):
        for name in b.NEW_FILES+b.RETAINED:
            self.assertTrue((b.ROOT/name).is_file(), name)

    def test_tool_imports_only_the_standard_library(self):
        tree = ast.parse(Path(b.__file__).read_text(encoding="utf-8"))
        names = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for alias in node.names}
        names |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertLessEqual(names, {"__future__", "argparse", "copy", "dataclasses", "fractions", "hashlib", "json",
                                     "math", "pathlib", "platform", "time"})

    def test_cli_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder)/"receipt.json"
            existing.write_text("{}", encoding="utf-8")
            argv = ["check_i01_basal_closure.py", "--output", str(existing)]
            with mock.patch.object(sys, "argv", argv), self.assertRaises(FileExistsError):
                b.main()
            self.assertEqual(existing.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
