"""Small synthetic R13 physics/numerics tests; no Diadem calibration claims."""
from copy import deepcopy
import math
import unittest
from unittest.mock import patch

import numpy as np

from work.generator_upgrade_r13 import soil


PROVENANCE = {"evidence": "Explicit synthetic numerical-test coefficients; not Diadem calibration", "source_status": "SYNTHETIC TEST"}


def fixture(n=1):
    """Public compact JSON contract, also usable by adapter/driver fixtures."""
    model = {"layers": [dict(layer_id="synthetic-"+str(i), thickness_m=.1,
        theta_r=.05, theta_s=.45, vg_alpha_per_m=2., vg_n=1.6, mualem_l=.5,
        saturated_conductivity_m_s=1e-6, ice_impedance=7., dry_heat_capacity_j_m3_k=1.4e6,
        conductivity_dry_w_m_k=.25, conductivity_saturated_unfrozen_w_m_k=1.6,
        conductivity_saturated_frozen_w_m_k=2.2, **PROVENANCE) for i in range(n)],
        "constants": {"water_density_kg_m3": 1000., "water_heat_capacity_j_kg_k": 4180.,
                      "ice_heat_capacity_j_kg_k": 2100., "latent_heat_j_kg": 334000.,
                      "melting_temperature_k": 273.15, "gravity_m_s2": 9.80665}, **PROVENANCE}
    event = {"duration_s": 100., "surface_water_flux_m_s": 0., "surface_water_temperature_k": 274.,
             "top_heat": {"kind": "flux", "value": 0., **PROVENANCE},
             "bottom_heat": {"kind": "flux", "value": 0., **PROVENANCE},
             "bottom_water": {"kind": "noflow", **PROVENANCE},
             "root_withdrawal_m_s": [0.]*n, **PROVENANCE}
    controls = {"initial_step_s": 100., "min_step_s": 1e-4, "max_step_s": 1000.,
        "water_atol_m": 1e-8, "water_fraction_atol": 1e-5, "energy_atol_j_m2": .1,
        "head_atol_m": 1e-3, "temperature_atol_k": 1e-3, "relative_tolerance": 1e-4,
        "nonlinear_water_atol_m": 1e-11, "nonlinear_energy_atol_j_m2": 1e-4,
        "min_head_m": -1000., "max_head_m": 100., "min_temperature_k": 230.,
        "max_temperature_k": 330., "max_steps": 2000, "max_nonlinear_evaluations": 80}
    return model, event, controls


def insulate_material(model):
    for layer in model["layers"]:
        layer["conductivity_dry_w_m_k"] = 0.
        layer["conductivity_saturated_unfrozen_w_m_k"] = 0.
        layer["conductivity_saturated_frozen_w_m_k"] = 0.


def independent_enthalpy(model, state):
    c = model["constants"]
    terms = []
    for i, layer in enumerate(model["layers"]):
        liquid, ice, t = (state[k][i] for k in ("liquid_water", "ice_water", "temperature_k"))
        capacity = layer["dry_heat_capacity_j_m3_k"]+c["water_density_kg_m3"]*(c["water_heat_capacity_j_kg_k"]*liquid+c["ice_heat_capacity_j_kg_k"]*ice)
        terms.append(layer["thickness_m"]*(capacity*(t-c["melting_temperature_k"])+c["water_density_kg_m3"]*c["latent_heat_j_kg"]*liquid))
    return terms


class SoilTests(unittest.TestCase):
    def assert_modelled(self, result):
        self.assertEqual(result["status"], "MODELLED", (result["reason"], result.get("numerics", {}).get("last_trial")))
        self.assertFalse(result["physical_acceptance"])
        self.assertEqual(result["last_accepted_state"], result["final_state"])

    def test_unfrozen_retention_and_positive_head_are_preserved(self):
        model, _, _ = fixture(2)
        state = soil.initial_state(model, [-1., .03], [275., 276.])
        expected = .05+.4*(1+2.**1.6)**(-(1-1/1.6))
        self.assertAlmostEqual(state["total_water"][0], expected, places=15)
        self.assertEqual(state["liquid_water"], state["total_water"])
        self.assertEqual(state["ice_water"], [0., 0.])
        self.assertEqual(state["head_m"][1], .03)
        self.assertEqual(state["liquid_head_m"][1], .03)

    def test_phase_matches_independent_published_equations(self):
        model, _, _ = fixture()
        head, temperature = -2., 272.8
        state = soil.initial_state(model, [head], [temperature])
        onset = 273.15+9.80665*273.15*head/334000.
        psi = head+334000./(9.80665*onset)*(temperature-onset)
        expected = .05+.4*(1+(2.*abs(psi))**1.6)**(-(1-1/1.6))
        self.assertAlmostEqual(state["liquid_water"][0], expected, places=14)
        self.assertGreater(state["ice_water"][0], 0)
        self.assertGreater(state["liquid_water"][0], .05)
        self.assertAlmostEqual(state["enthalpy_j_m2"][0], independent_enthalpy(model, state)[0], places=7)

    def test_unsaturated_freezing_point_is_depressed(self):
        model, _, _ = fixture()
        onset = 273.15*(1+9.80665*(-10.)/334000.)
        state = soil.initial_state(model, [-10.], [(onset+273.15)/2])
        self.assertLess(state["temperature_k"][0], 273.15)
        self.assertEqual(state["ice_water"], [0.])

    def test_frozen_positive_pressure_is_not_silently_extrapolated(self):
        model, _, _ = fixture()
        with self.assertRaisesRegex(soil.ConstitutiveDomainError, "ice-pressure"):
            soil.initial_state(model, [.01], [272.])

    def test_mutated_state_and_model_are_rejected(self):
        model, event, controls = fixture()
        state = soil.initial_state(model, [-1.], [275.])
        altered = deepcopy(state); altered["enthalpy_j_m2"][0] += 1
        with self.assertRaisesRegex(ValueError, "state binding"):
            soil.advance(model, altered, event, controls)
        changed = deepcopy(model); changed["layers"][0]["ice_impedance"] += 1
        with self.assertRaisesRegex(ValueError, "state binding"):
            soil.advance(changed, state, event, controls)

    def test_unknown_is_not_zero(self):
        model, event, controls = fixture()
        state = soil.initial_state(model, [-1.], [275.])
        model["layers"][0]["source_status"] = "UNKNOWN"
        result = soil.advance(model, state, event, controls)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIsNone(result["final_state"])
        self.assertIsNone(result["ledger"])

    def test_boolean_coefficient_and_unphysical_bounds_rejected(self):
        model, event, controls = fixture()
        model["layers"][0]["ice_impedance"] = True
        with self.assertRaises(ValueError):
            soil.initial_state(model, [-1.], [274.])
        model, event, controls = fixture()
        state = soil.initial_state(model, [-1.], [274.])
        controls["min_head_m"] = -1000000.
        with self.assertRaisesRegex(ValueError, "Clapeyron"):
            soil.advance(model, state, event, controls)

    def test_sealed_isothermal_noop_has_no_invented_flux(self):
        model, event, controls = fixture()
        state = soil.initial_state(model, [-1.], [274.])
        result = soil.advance(model, state, event, controls)
        self.assert_modelled(result)
        for k in ("head_m", "temperature_k", "total_water", "enthalpy_j_m2"):
            self.assertEqual(result["final_state"][k], state[k])
        self.assertEqual(result["ledger"]["face_water_m"], [0., 0.])

    def test_unfrozen_analytical_heat_limit_and_time_refinement(self):
        model, event, controls = fixture()
        layer = model["layers"][0]
        layer["saturated_conductivity_m_s"] = 0.
        for key in ("conductivity_dry_w_m_k", "conductivity_saturated_unfrozen_w_m_k", "conductivity_saturated_frozen_w_m_k"):
            layer[key] = 1.
        state = soil.initial_state(model, [-1.], [274.])
        event["duration_s"] = 2000.
        event["top_heat"] = {"kind": "temperature", "value": 280., **PROVENANCE}
        controls.update(temperature_atol_k=100., energy_atol_j_m2=1e8, relative_tolerance=0.)
        capacity = (1.4e6+1000.*4180.*state["total_water"][0])*.1
        exact = 280.+(274.-280.)*math.exp(-20.*event["duration_s"]/capacity)
        errors = []
        for dt in (1000., 500., 250.):
            controls.update(initial_step_s=dt, max_step_s=dt)
            result = soil.advance(model, state, event, controls)
            self.assert_modelled(result)
            errors.append(abs(result["final_state"]["temperature_k"][0]-exact))
        self.assertGreater(errors[0]/errors[1], 1.8)
        self.assertGreater(errors[1]/errors[2], 1.8)
        self.assertLess(errors[-1], .01)

    def test_freezing_reduces_flow_and_changes_thermal_properties(self):
        model, event, controls = fixture()
        insulate_material(model)
        event["surface_water_flux_m_s"] = 1e-7
        event["surface_water_temperature_k"] = 273.
        event["bottom_water"] = {"kind": "free_drainage", **PROVENANCE}
        warm = soil.advance(model, soil.initial_state(model, [-1.], [274.]), event, controls)
        cold = soil.advance(model, soil.initial_state(model, [-1.], [272.9]), event, controls)
        self.assert_modelled(warm); self.assert_modelled(cold)
        self.assertLess(cold["ledger"]["infiltration_m"], warm["ledger"]["infiltration_m"]*.1)
        self.assertLess(cold["ledger"]["bottom_downward_m"], warm["ledger"]["bottom_downward_m"]*.1)
        self.assertGreater(cold["final_state"]["ice_water"][0], 0)
        unmodified, _, _ = fixture()
        a = soil._properties(unmodified, [-1.], [274.])
        b = soil._properties(unmodified, [-1.], [272.9])
        self.assertNotEqual(a["thermal_conductivity"][0], b["thermal_conductivity"][0])
        self.assertNotEqual(a["capacity"][0], b["capacity"][0])

    def test_subfreezing_liquid_advection_uses_common_enthalpy_datum(self):
        model, event, controls = fixture(2)
        insulate_material(model)
        event.update(duration_s=10., surface_water_flux_m_s=1e-10, surface_water_temperature_k=272.8)
        for layer in model["layers"]:
            layer["saturated_conductivity_m_s"] = 1e-4
        state = soil.initial_state(model, [-1., -2.], [272.9, 272.5])
        result = soil.advance(model, state, event, controls)
        self.assert_modelled(result)
        ledger = result["ledger"]
        self.assertGreater(ledger["infiltration_m"], 0)
        expected = ledger["infiltration_m"]*1000.*(334000.+4180.*(272.8-273.15))
        self.assertAlmostEqual(ledger["face_advective_energy_j_m2"][0], expected, places=10)
        independent_delta = math.fsum(independent_enthalpy(model, result["final_state"]))-math.fsum(independent_enthalpy(model, state))
        self.assertAlmostEqual(independent_delta, expected, delta=controls["energy_atol_j_m2"])
        self.assertGreater(abs(ledger["face_advective_energy_j_m2"][1]), 0)
        self.assertLess(abs(ledger["energy_residual_j_m2"]), controls["energy_atol_j_m2"])
        self.assertLess(abs(ledger["water_residual_m"]), controls["water_atol_m"])

    def test_fixed_head_inflow_and_direct_root_sink_are_accounted(self):
        model, event, controls = fixture()
        insulate_material(model)
        event["bottom_water"] = {"kind": "head", "head_m": 0., "temperature_k": 280., **PROVENANCE}
        event["root_withdrawal_m_s"] = [1e-8]
        result = soil.advance(model, soil.initial_state(model, [-1.], [274.]), event, controls)
        self.assert_modelled(result)
        ledger = result["ledger"]
        self.assertGreater(ledger["bottom_upward_m"], 0)
        self.assertAlmostEqual(ledger["storage_change_m"], ledger["bottom_upward_m"]-ledger["root_withdrawal_m"]-ledger["surface_exfiltration_m"], delta=1e-8)
        self.assertAlmostEqual(ledger["enthalpy_change_j_m2"], ledger["face_advective_energy_j_m2"][0]-ledger["face_advective_energy_j_m2"][-1]-ledger["root_enthalpy_j_m2"], delta=.1)

    def test_feddes_root_demand_is_reduced_by_freezing_suction(self):
        model, event, controls = fixture()
        insulate_material(model)
        event.pop("root_withdrawal_m_s")
        event.update(potential_root_demand_m_s=1e-8, uptake={"weights": [1.], "dry_zero_head_m": -100.,
            "dry_full_head_m": -1., "wet_full_head_m": -.1, "wet_zero_head_m": 0.})
        warm = soil.advance(model, soil.initial_state(model, [-1.], [274.]), event, controls)
        frozen = soil.advance(model, soil.initial_state(model, [-1.], [270.]), event, controls)
        self.assert_modelled(warm); self.assert_modelled(frozen)
        self.assertGreater(warm["ledger"]["root_withdrawal_m"], 0)
        self.assertEqual(frozen["ledger"]["root_withdrawal_m"], 0.)

    def test_material_thickness_is_preserved_and_noop_thin_layer_passes(self):
        model, event, controls = fixture(3)
        model["layers"][1]["thickness_m"] = 2.3e-8
        for layer in model["layers"]:
            layer["saturated_conductivity_m_s"] = 0.
        state = soil.initial_state(model, [-1.]*3, [274.]*3)
        result = soil.advance(model, state, event, controls)
        self.assert_modelled(result)
        self.assertEqual(result["ledger"]["layers"][1]["thickness_m"], 2.3e-8)
        self.assertEqual(len(result["final_state"]["total_water"]), 3)

    def test_failed_trial_never_enters_accepted_prefix(self):
        model, event, controls = fixture()
        model["layers"][0]["saturated_conductivity_m_s"] = 0.
        event["duration_s"] = 1000.
        controls.update(initial_step_s=100., max_step_s=100., max_steps=1)
        state = soil.initial_state(model, [-1.], [274.], elapsed_seconds=123.)
        result = soil.advance(model, state, event, controls)
        self.assertEqual(result["status"], "NUMERICAL_FAILURE")
        self.assertIsNone(result["final_state"])
        self.assertEqual(len(result["accepted_steps"]), 1)
        self.assertEqual(result["last_accepted_state"]["elapsed_seconds"], 223.)
        self.assertEqual(result["ledger"]["elapsed_s"], 100.)

    def test_full_time_clock_and_zero_duration(self):
        model, event, controls = fixture()
        event["duration_s"] = .3
        controls.update(initial_step_s=.1, max_step_s=.1)
        state = soil.initial_state(model, [-1.], [274.], elapsed_seconds=1000.)
        result = soil.advance(model, state, event, controls)
        self.assert_modelled(result)
        self.assertEqual(result["final_state"]["elapsed_seconds"], 1000.+.3)
        event["duration_s"] = 0.
        zero = soil.advance(model, state, event, controls)
        self.assert_modelled(zero)
        self.assertEqual(zero["final_state"], state)

    def test_constitutive_analytic_derivatives_match_finite_differences(self):
        model, _, _ = fixture()
        for head, temperature in ((-1., 274.), (-2., 272.8)):
            base = soil._properties(model, [head], [temperature])
            for delta, keys, position in ((1e-5, (("theta", "theta_h"), ("liquid", "liquid_h"), ("conductivity", "k_h"), ("thermal_conductivity", "lambda_h"), ("energy", "energy_h")), 0),
                                          (1e-5, (("liquid", "liquid_t"), ("conductivity", "k_t"), ("thermal_conductivity", "lambda_t"), ("energy", "energy_t")), 1)):
                plus = soil._properties(model, [head+delta if position == 0 else head], [temperature+delta if position else temperature])
                minus = soil._properties(model, [head-delta if position == 0 else head], [temperature-delta if position else temperature])
                for value, derivative in keys:
                    estimated = (plus[value][0]-minus[value][0])/(2*delta)
                    self.assertAlmostEqual(base[derivative][0], estimated, delta=max(1e-14, abs(estimated)*2e-4), msg=(head, temperature, value, derivative))

    def test_full_365_day_seasonal_column_freezes_and_thaws(self):
        model, event, controls = fixture()
        model["layers"][0]["saturated_conductivity_m_s"] = 0.
        state = soil.initial_state(model, [-1.], [273.5])
        initial = deepcopy(state)
        controls.update(initial_step_s=10000., max_step_s=86400., temperature_atol_k=.02,
                        water_fraction_atol=5e-4, relative_tolerance=1e-3, energy_atol_j_m2=1000.)
        days = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
        temperatures = (271.5, 271.8, 272.5, 274., 276., 278., 279., 278., 276., 274., 272.5, 271.5)
        ice, heat, water = [], [], []
        for month_days, boundary_temperature in zip(days, temperatures):
            event["duration_s"] = month_days*86400.
            event["top_heat"] = {"kind": "temperature", "value": boundary_temperature, **PROVENANCE}
            result = soil.advance(model, state, event, controls)
            self.assert_modelled(result)
            state = result["final_state"]
            ice.append(state["ice_water"][0])
            heat.append(result["ledger"]["face_conductive_energy_j_m2"][0])
            water.append(result["ledger"]["storage_change_m"])
        self.assertEqual(state["elapsed_seconds"], 365*86400.)
        self.assertGreater(max(ice), .1)
        self.assertEqual(min(ice), 0.)
        self.assertAlmostEqual(math.fsum(water), 0., delta=1e-8)
        independent_delta = math.fsum(independent_enthalpy(model, state))-math.fsum(independent_enthalpy(model, initial))
        self.assertAlmostEqual(independent_delta, math.fsum(heat), delta=.1)

    def test_unfrozen_conduction_spatial_refinement_against_cosine_solution(self):
        # Uniform volumetric heat capacity, ks=0 and insulated boundaries have
        # an independent continuum Fourier-mode solution. Initial values and
        # oracle are CELL AVERAGES, not samples mistaken for averages. A small
        # common dt keeps time error below the finest admitted spatial error.
        errors = []
        length, mean, amplitude, duration = .4, 280., 2., 10000.
        for n in (3, 6, 12):
            model, event, controls = fixture(n)
            for layer in model["layers"]:
                layer["thickness_m"] = length/n
                layer["saturated_conductivity_m_s"] = 0.
                for key in ("conductivity_dry_w_m_k", "conductivity_saturated_unfrozen_w_m_k", "conductivity_saturated_frozen_w_m_k"):
                    layer[key] = 1.
            half_angle = math.pi/(2*n)
            averaged_mode = np.cos(math.pi*(np.arange(n)+.5)/n)*math.sin(half_angle)/half_angle
            temperatures = mean+amplitude*averaged_mode
            state = soil.initial_state(model, [-1.]*n, temperatures.tolist())
            capacity = 1.4e6+1000.*4180.*state["total_water"][0]
            oracle = mean+amplitude*math.exp(-(math.pi/length)**2*duration/capacity)*averaged_mode
            event["duration_s"] = duration
            controls.update(initial_step_s=100., max_step_s=100., temperature_atol_k=100.,
                            energy_atol_j_m2=1e8, relative_tolerance=0.)
            result = soil.advance(model, state, event, controls)
            self.assert_modelled(result)
            errors.append(float(np.sqrt(np.mean((np.asarray(result["final_state"]["temperature_k"])-oracle)**2))))
        self.assertGreater(errors[0]/errors[1], 3.)
        self.assertGreater(errors[1]/errors[2], 3.)
        self.assertLess(errors[-1], .005)


class PainterKarraTests(unittest.TestCase):
    def fixture(self, n=1):
        model, event, controls = fixture(n)
        model.update(freezing_model=soil.PAINTER_KARRA, clapeyron_beta=1.)
        return model, event, controls

    def test_option_is_explicit_and_unfrozen_limit_is_original_vg(self):
        model, _, _ = self.fixture(2)
        state = soil.initial_state(model, [-1., .1], [275., 276.])
        original = deepcopy(model)
        original.pop("freezing_model"); original.pop("clapeyron_beta")
        baseline = soil.initial_state(original, [-1., .1], [275., 276.])
        for key in ("head_m", "total_water", "liquid_water", "ice_water", "liquid_head_m", "enthalpy_j_m2"):
            self.assertEqual(state[key], baseline[key])
        self.assertNotEqual(state["model_sha256"], baseline["model_sha256"])
        model.pop("clapeyron_beta")
        with self.assertRaises(soil.UnknownInput):
            soil.initial_state(model, [-1., .1], [275., 276.])

    def test_independent_apparent_pore_identity_and_phase_bounds(self):
        model, _, _ = self.fixture()
        phi = .45
        for head in (-100., -1., -.001, 0., .1):
            a = (.05+.4*(1+(2*abs(min(head, 0)))**1.6)**(-(1-1/1.6)))/phi
            for temperature in (270., 273.149, 273.15, 280.):
                cold_head = -334000./9.80665*max(0., (273.15-temperature)/273.15)
                b = (.05+.4*(1+(2*abs(cold_head))**1.6)**(-(1-1/1.6)))/phi
                sl = min(a, b)
                si = 1-sl/a
                state = soil.initial_state(model, [head], [temperature])
                self.assertAlmostEqual(state["liquid_water"][0]/phi, sl, places=14)
                self.assertAlmostEqual(state["ice_water"][0]/phi, si, places=14)
                self.assertAlmostEqual(sl, (1-si)*a, places=14)
                self.assertLessEqual(state["total_water"][0], phi)
                self.assertGreaterEqual(state["ice_water"][0], 0.)
                self.assertEqual(state["liquid_head_m"], [head])

    def test_phase_tie_is_continuous(self):
        model, _, _ = self.fixture()
        h = -1.
        onset = 273.15*(1+9.80665*h/334000.)
        warm = soil.initial_state(model, [h], [onset+1e-8])
        cold = soil.initial_state(model, [h], [onset-1e-8])
        self.assertEqual(warm["ice_water"], [0.])
        self.assertLess(cold["ice_water"][0], 1e-5)
        self.assertAlmostEqual(warm["total_water"][0], cold["total_water"][0], delta=1e-6)

    def test_phase_and_coupled_storage_derivatives(self):
        model, _, _ = self.fixture()
        for h, t in ((-1., 274.), (-1., 272.9), (.02, 273.1)):
            base = soil._properties(model, [h], [t])
            for axis, step in ((0, 1e-5), (1, 1e-6)):
                suffix = "_h" if axis == 0 else "_t"
                plus = soil._properties(model, [h+step if axis == 0 else h], [t+step if axis == 1 else t])
                minus = soil._properties(model, [h-step if axis == 0 else h], [t-step if axis == 1 else t])
                for value, key in (("theta", "theta"), ("liquid", "liquid"), ("conductivity", "k"), ("thermal_conductivity", "lambda"), ("energy", "energy")):
                    finite_difference = (plus[value][0]-minus[value][0])/(2*step)
                    self.assertAlmostEqual(base[key+suffix][0], finite_difference,
                        delta=max(1e-13, abs(finite_difference)*5e-4), msg=(h, t, value, suffix))

    def test_saturated_frozen_pressure_changes_flow_not_storage(self):
        model, event, controls = self.fixture()
        a = soil.initial_state(model, [.01], [273.1])
        b = soil.initial_state(model, [.03], [273.1])
        for key in ("total_water", "liquid_water", "ice_water", "enthalpy_j_m2"):
            self.assertEqual(a[key], b[key])
        event["bottom_water"] = {"kind": "head", "head_m": .1, "temperature_k": 273.1, **PROVENANCE}
        pa = soil._properties(model, [.01], [273.1])
        pb = soil._properties(model, [.03], [273.1])
        ra, rb = (soil._rates(model, p, np.asarray([273.1]), event) for p in (pa, pb))
        self.assertNotEqual(ra["water"][-1], rb["water"][-1])
        self.assertGreater(ra["water_jac"][-1, 0], 0.)
        advanced = soil.advance(model, a, event, controls)
        self.assertEqual(advanced["status"], "MODELLED", advanced["reason"])
        self.assertGreater(advanced["final_state"]["head_m"][0], 0.)
        self.assertGreater(advanced["final_state"]["ice_water"][0], 0.)
        self.assertEqual(advanced["head_semantics"], "LIQUID_PRESSURE_HEAD")

    def test_cold_unsaturated_saturated_unsaturated_cycle_preserves_both_ledgers(self):
        model, event, controls = self.fixture()
        model["layers"][0].update(saturated_conductivity_m_s=.001, ice_impedance=0.)
        state = soil.initial_state(model, [-.2], [273.1])
        initial = deepcopy(state)
        event.update(duration_s=10000., surface_water_temperature_k=273.1)
        event["top_heat"] = {"kind": "temperature", "value": 273.1, **PROVENANCE}
        event["bottom_heat"] = {"kind": "temperature", "value": 273.1, **PROVENANCE}
        event["bottom_water"] = {"kind": "head", "head_m": .2, "temperature_k": 273.1, **PROVENANCE}
        controls.update(initial_step_s=1., min_step_s=1e-12, max_step_s=1000.)
        charged = soil.advance(model, state, event, controls)
        self.assertEqual(charged["status"], "MODELLED", (charged["reason"], charged.get("numerics", {}).get("last_trial")))
        self.assertGreater(charged["final_state"]["head_m"][0], 0.)
        self.assertGreater(charged["final_state"]["ice_water"][0], 0.)
        event["duration_s"] = 1000.
        event["bottom_water"]["head_m"] = -.3
        drained = soil.advance(model, charged["final_state"], event, controls)
        self.assertEqual(drained["status"], "MODELLED", (drained["reason"], drained.get("numerics", {}).get("last_trial")))
        self.assertLess(drained["final_state"]["head_m"][0], 0.)
        self.assertLess(drained["final_state"]["total_water"][0], .45)
        for result in (charged, drained):
            self.assertLess(abs(result["ledger"]["water_residual_m"]), controls["water_atol_m"])
            self.assertLess(abs(result["ledger"]["energy_residual_j_m2"]), controls["energy_atol_j_m2"])
        boundary_energy = math.fsum(r["ledger"]["face_conductive_energy_j_m2"][0]+r["ledger"]["face_advective_energy_j_m2"][0]
            -r["ledger"]["face_conductive_energy_j_m2"][-1]-r["ledger"]["face_advective_energy_j_m2"][-1] for r in (charged, drained))
        independent_delta = math.fsum(independent_enthalpy(model, drained["final_state"]))-math.fsum(independent_enthalpy(model, initial))
        self.assertAlmostEqual(independent_delta, boundary_energy, delta=.1)

    def test_endpoint_projection_preserves_inventory_and_historical_fill(self):
        model, event, controls = self.fixture()
        model["layers"][0].update(saturated_conductivity_m_s=.001, ice_impedance=0.)
        event["bottom_water"] = {"kind": "head", "head_m": .2, "temperature_k": 273.1, **PROVENANCE}
        temperature = np.asarray([273.1])
        offset = temperature-273.15
        p = soil._properties(model, [.01], temperature, temperature_offset=offset)
        rates = soil._rates(model, p, temperature, event, temperature_offset=offset)
        original_rates = deepcopy(rates)
        h, projected, diagnostic = soil._project_endpoint(model, [.01], temperature, p, rates, event, controls, 8, temperature_offset=offset)
        self.assertAlmostEqual(h[0], .1, places=14)
        self.assertEqual(diagnostic["evaluations"], 2)  # Crosses surface active set.
        for key in ("theta", "liquid", "ice", "energy", "theta_deficit", "liquid_deficit"):
            np.testing.assert_array_equal(projected[key], p[key])
        for key in rates:
            np.testing.assert_array_equal(rates[key], original_rates[key])
        self.assertLessEqual(abs(diagnostic["flux_residual_m_s"][0]), diagnostic["flux_roundoff_limit_m_s"][0])
        # A filling BE step retains its original positive net input, even
        # though its projected endpoint has zero instantaneous net input.
        old = soil._properties(model, [-1e-4], temperature, temperature_offset=offset)
        step, why = soil._step(model, np.asarray([-1e-4]), temperature, 1., event, controls, temperature_offset=offset)
        self.assertIsNone(why)
        self.assertGreater(step["head"][0], 0.)
        self.assertNotEqual(step["endpoint_pressure_projection"]["integration_head_m"], step["endpoint_pressure_projection"]["endpoint_head_m"])
        change, _ = soil._changes(model, old, step["props"], temperature, step["temperature"], old_offset=offset, new_offset=step["temperature_offset"])
        self.assertGreater(change[0], 0.)
        self.assertAlmostEqual(change[0], step["water"][0]-step["water"][1], delta=controls["nonlinear_water_atol_m"])

    def test_endpoint_projection_includes_saturated_neighbours(self):
        model, event, controls = self.fixture(2)
        event["bottom_water"] = {"kind": "head", "head_m": .4, "temperature_k": 273.1, **PROVENANCE}
        temperature = np.asarray([273.1, 273.1])
        offset = temperature-273.15
        p = soil._properties(model, [.07, .27], temperature, temperature_offset=offset)
        rates = soil._rates(model, p, temperature, event, temperature_offset=offset)
        h, projected, diagnostic = soil._project_endpoint(model, [.07, .27], temperature, p, rates, event, controls, 8, temperature_offset=offset)
        np.testing.assert_allclose(h, [.1, .3], rtol=0., atol=1e-14)
        self.assertEqual(diagnostic["layer_indices"], [0, 1])
        endpoint = soil._rates(model, projected, temperature, event, temperature_offset=offset)
        np.testing.assert_allclose(endpoint["water"], [-p["conductivity"][0]]*3, rtol=1e-13, atol=0.)

    def test_thin_layer_linear_darcy_endpoint_roundoff_oracle(self):
        model, event, controls = self.fixture(4)
        thickness = np.asarray([.1, 2.3e-8, 2.3e-8, .1])
        for layer, dz in zip(model["layers"], thickness):
            layer["thickness_m"] = float(dz)
        event["bottom_water"] = {"kind": "head", "head_m": .5, "temperature_k": 273.1, **PROVENANCE}
        temperature = np.full(4, 273.1); offset = temperature-273.15
        length = math.fsum(thickness)
        oracle_head = .5*(np.cumsum(thickness)-thickness/2)/length
        p = soil._properties(model, oracle_head, temperature, temperature_offset=offset)
        rates = soil._rates(model, p, temperature, event, temperature_offset=offset)
        h, projected, diagnostic = soil._project_endpoint(model, oracle_head, temperature, p, rates, event, controls, 80, temperature_offset=offset)
        np.testing.assert_array_equal(h, oracle_head)
        self.assertEqual(diagnostic["evaluations"], 0)
        exact_flux = p["conductivity"][0]*(1-.5/length)
        absolute_error = np.abs(rates["water"]-exact_flux)
        self.assertTrue(np.all(absolute_error <= 128*np.finfo(float).eps*rates["water_roundoff_operands"]))
        for key in ("theta", "liquid", "ice", "energy"):
            np.testing.assert_array_equal(projected[key], p[key])

    def test_accepted_projection_log_omits_only_empty_records(self):
        for saturated in (False, True):
            model, event, controls = self.fixture()
            event["duration_s"] = 1.
            if saturated:
                event["bottom_water"] = {"kind": "head", "head_m": .2, "temperature_k": 273.1, **PROVENANCE}
            state = soil.initial_state(model, [.1 if saturated else -1.], [273.1])
            result = soil.advance(model, state, event, controls)
            self.assertEqual(result["status"], "MODELLED", result["reason"])
            self.assertTrue(result["accepted_steps"])
            for row in result["accepted_steps"]:
                self.assertEqual("endpoint_pressure_projection" in row, saturated)
                if saturated:
                    self.assertEqual(set(row["endpoint_pressure_projection"]), {"full", "first_half", "second_half"})
                    self.assertTrue(all(record["layer_indices"] for record in row["endpoint_pressure_projection"].values()))

    def test_column_budget_polishes_locally_acceptable_early_stop(self):
        model, event, controls = self.fixture()
        controls["max_steps"] = 20000
        event["surface_water_flux_m_s"] = 1e-8
        head, temperature = np.asarray([-1.]), np.asarray([274.])
        original_solver = soil.least_squares
        early_residual = []
        def early_stop(fun, *args, **kwargs):
            result = original_solver(fun, *args, **kwargs)
            result.x[0] += 1e-10
            early_residual.append(fun(result.x)[0]*controls["nonlinear_water_atol_m"])
            return result
        with patch.object(soil, "least_squares", side_effect=early_stop):
            step, why = soil._step(model, head, temperature, 1., event, controls)
        self.assertIsNone(why)
        limit = controls["water_atol_m"]/(4*controls["max_steps"])
        self.assertEqual(step["solver_status"], "TRUST_REGION_SUCCEEDED")
        self.assertGreater(abs(early_residual[0]), limit)
        self.assertLess(abs(early_residual[0]), controls["nonlinear_water_atol_m"])
        self.assertLessEqual(abs(step["column_water_residual"]), limit)
        self.assertLess(abs(step["column_water_residual"]), abs(early_residual[0])/1000.)
        self.assertLessEqual(2*controls["max_steps"]*limit, controls["water_atol_m"]/2)

    def test_saturated_warm_newton_is_real_and_budgeted(self):
        model, event, controls = self.fixture()
        event["bottom_water"] = {"kind": "head", "head_m": .2, "temperature_k": 280., **PROVENANCE}
        event["top_heat"] = {"kind": "temperature", "value": 282., **PROVENANCE}
        controls["max_nonlinear_evaluations"] = 3
        with patch.object(soil, "least_squares", side_effect=AssertionError("Newton path must not fabricate a least-squares result")):
            step, why = soil._step(model, np.asarray([.1]), np.asarray([280.]), 1., event, controls)
        self.assertIsNone(why)
        self.assertEqual(step["solver_status"], "NEWTON_CONVERGED")
        self.assertEqual(step["warm_start_newton_evaluations"], 2)
        self.assertLessEqual(step["nfev"], 3)
        controls["max_nonlinear_evaluations"] = 1
        with patch.object(soil, "_rates", wraps=soil._rates) as rates:
            failed, why = soil._step(model, np.asarray([.1]), np.asarray([280.]), 1., event, controls)
        self.assertIsNone(failed)
        self.assertIn("budget", why)
        self.assertEqual(rates.call_count, 1)

    def test_warm_newton_failure_falls_back_without_new_budget_or_gauge_bypass(self):
        model, event, controls = self.fixture()
        event["bottom_water"] = {"kind": "head", "head_m": .2, "temperature_k": 280., **PROVENANCE}
        event["top_heat"] = {"kind": "temperature", "value": 282., **PROVENANCE}
        actual_solve, calls = np.linalg.solve, []
        def fail_first(matrix, residual):
            calls.append(1)
            if len(calls) == 1:
                raise np.linalg.LinAlgError("injected Newton candidate failure")
            return actual_solve(matrix, residual)
        with patch.object(np.linalg, "solve", side_effect=fail_first), patch.object(soil, "least_squares", wraps=soil.least_squares) as fallback:
            step, why = soil._step(model, np.asarray([.1]), np.asarray([280.]), 1., event, controls)
        self.assertIsNone(why)
        self.assertEqual(step["solver_status"], "TRUST_REGION_SUCCEEDED")
        self.assertEqual(fallback.call_args.kwargs["max_nfev"], controls["max_nonlinear_evaluations"]-1)
        self.assertLessEqual(step["nfev"], controls["max_nonlinear_evaluations"])
        # A truly unanchored saturated/no-flow column remains inadmissible.
        model, event, controls = self.fixture()
        failed, why = soil._step(model, np.asarray([.01]), np.asarray([280.]), 1., event, controls)
        self.assertIsNone(failed)
        self.assertTrue("rank" in why or "Singular" in why, why)

    def test_endpoint_projection_rejects_branch_gauge_and_work_budget(self):
        for case in ("negative", "gauge", "budget"):
            model, event, controls = self.fixture()
            temperature = np.asarray([273.1]); offset = temperature-273.15
            head = [.01] if case != "negative" else [.1]
            if case != "gauge":
                event["bottom_water"] = {"kind": "head", "head_m": -.1 if case == "negative" else .2, "temperature_k": 273.1, **PROVENANCE}
            p = soil._properties(model, head, temperature, temperature_offset=offset)
            rates = soil._rates(model, p, temperature, event, temperature_offset=offset)
            message = {"negative": "nonnegative", "gauge": "rank deficient", "budget": "budget"}[case]
            with self.assertRaisesRegex(ValueError, message):
                soil._project_endpoint(model, head, temperature, p, rates, event, controls, 0 if case == "budget" else 8, temperature_offset=offset)

    def test_complementary_storage_retains_microscopic_saturation_deficit(self):
        model, _, _ = self.fixture()
        old = soil._properties(model, [-1e-12], [273.1])
        new = soil._properties(model, [0.], [273.1])
        self.assertEqual(old["theta"][0], new["theta"][0])
        self.assertGreater(old["theta_deficit"][0], 0.)
        dw, _ = soil._changes(model, old, new, [273.1], [273.1])
        self.assertGreater(dw[0], 0.)
        self.assertEqual(dw[0], model["layers"][0]["thickness_m"]*old["theta_deficit"][0])

    def test_frozen_coupled_fixed_step_refinement(self):
        model, event, controls = self.fixture()
        model["layers"][0]["saturated_conductivity_m_s"] = 1e-4
        state = soil.initial_state(model, [-1.], [272.9])
        event.update(duration_s=8., surface_water_flux_m_s=1e-8, surface_water_temperature_k=273.1)
        event["top_heat"] = {"kind": "temperature", "value": 270., **PROVENANCE}
        states = []
        for dt in (1., .5, .25):
            controls.update(initial_step_s=dt, max_step_s=dt)
            result = soil.advance(model, state, event, controls)
            self.assertEqual(result["status"], "MODELLED", result["reason"])
            self.assertEqual(len(result["accepted_steps"]), int(8/dt))
            states.append(result["final_state"])
        # Successive changes of both primary fields shrink with dt. This is a
        # convergence diagnostic, not an independent empirical validation.
        for key in ("head_m", "temperature_k"):
            coarse = abs(states[0][key][0]-states[1][key][0])
            fine = abs(states[1][key][0]-states[2][key][0])
            self.assertGreater(coarse, fine*1.7, msg=key)

    def test_authoritative_offset_preserves_sub_kelvin_ulp_gradient(self):
        model, event, controls = self.fixture(2)
        for layer in model["layers"]:
            layer["thickness_m"] = 2.3e-8
            layer["saturated_conductivity_m_s"] = 0.
        offsets = [-3., -3.+1e-14]
        tm = model["constants"]["melting_temperature_k"]
        readable = [tm+x for x in offsets]
        self.assertEqual(readable[0], readable[1])
        state = soil.initial_state(model, [-1., -1.], readable, temperature_offset_k=offsets)
        props = soil._properties(model, [-1., -1.], readable, temperature_offset=offsets)
        rates = soil._rates(model, props, np.asarray(readable), event, temperature_offset=offsets)
        self.assertNotEqual(rates["heat"][1], 0.)
        self.assertEqual(soil._read_state(model, state)[2].tolist(), offsets)
        event["duration_s"] = 0.
        result = soil.advance(model, state, event, controls)
        self.assertEqual(result["status"], "MODELLED")
        self.assertEqual(result["final_state"]["temperature_offset_k"], offsets)
        changed = deepcopy(state); changed["temperature_k"][0] += .01
        with self.assertRaisesRegex(ValueError, "recompose"):
            soil.advance(model, changed, event, controls)

    def test_offset_controls_consistent_at_rounded_readable_boundary(self):
        model, event, controls = self.fixture()
        tm = model["constants"]["melting_temperature_k"]
        event["duration_s"] = 0.
        for boundary, direction in ((controls["max_temperature_k"], -math.inf),
                                    (controls["min_temperature_k"], math.inf)):
            offset = math.nextafter(boundary-tm, direction)
            readable = tm+offset
            state = soil.initial_state(model, [-1.], [readable], temperature_offset_k=[offset])
            result = soil.advance(model, state, event, controls)
            self.assertEqual(result["status"], "MODELLED")
            self.assertEqual(result["final_state"], state)
            exact_boundary = soil.initial_state(model, [-1.], [boundary], temperature_offset_k=[boundary-tm])
            with self.assertRaisesRegex(ValueError, "outside"):
                soil.advance(model, exact_boundary, event, controls)

    def test_accepted_step_proposal_uses_declared_error_budget(self):
        _, _, controls = self.fixture()
        self.assertEqual(soil._accepted_step_proposal(30., .142331, controls), 60.)
        self.assertAlmostEqual(soil._accepted_step_proposal(30., .81, controls), 30.)
        self.assertAlmostEqual(soil._accepted_step_proposal(30., 1., controls), 27.)
        self.assertEqual(soil._accepted_step_proposal(700., 0., controls), controls["max_step_s"])
        self.assertEqual(soil._accepted_step_proposal(controls["min_step_s"], 1., controls), controls["min_step_s"])
        for error in (-1., 1.01, math.nan):
            with self.assertRaises(ValueError):
                soil._accepted_step_proposal(30., error, controls)


if __name__ == "__main__":
    unittest.main()
