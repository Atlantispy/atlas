"""I01 evolving plastic weakening of a layered rock column, WORKING NON-CANON.

A laterally uniform, coaxial plane-strain column at small strain: prescribed
temperature, lithostatic vertical stress and raw plastic history at material
points. It returns transmitted resistance for a supplied state; it does not
localise, rupture, neck or generate breakup.
I02.2a: the preparation, weakening law and stress response are owned by
atlas_tectonics._integration_weakening. This tool re-exports those same objects and
keeps its own rate/force evolution, envelopes, oracles, case, campaign and CLI.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.integrate import solve_ivp
from threadpoolctl import threadpool_limits

from atlas_tectonics import _integration_column, _integration_weakening
# The package-owned response, re-exported: these are the same objects, not copies.
from atlas_tectonics._integration_weakening import (
    LITHOSTATIC, SUPPLIED, COMMON_LAYER_KEYS, LAYER_KEYS, CREEP_KEYS, TOL, number, positive, check_deadline,
    WeakeningLaw, validate_creep, validate_layers, fingerprint, frozen, PreparedColumn, prepare, history_array,
    _evaluate, stresses, respond)

import check_i01_column as column

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT/"cases/i01_weakening_v1.json"
COLUMN_CASE = ROOT/"cases/i01_column_v1.json"
COLUMN_RECEIPT = ROOT/"evidence/i01-column-r2.json"
SCHEMA = "atlas.i01-weakening-case.v1"
REPRESENTATION = {
    "geometry": "laterally uniform column; coaxial plane-strain pure shear; material depth coordinates; small strain",
    "vertical_stress": "lithostatic from supplied layer densities below a free, unloaded surface",
    "temperature": "prescribed and fixed at material points; no conduction, heating or advection feedback",
    "pore_pressure": "supplied and fixed at material points",
    "history": "raw engineering plastic shear per material point; local weakening input; never overwritten",
}
POLICY_KEYS = {"max_steps", "maximum_seconds", "force_iterations", "kernel_parity_relative",
               "closed_form_relative", "fixed_point_relative", "work_relative", "history_bound_relative",
               "monotone_relative", "oracle_relative", "order_range", "uniform_relative", "time_relative",
               "depth_relative", "feedback_depth_relative", "coupling_resolution_factor", "force_relative",
               "inverse_rate_relative", "force_work_relative"}
TINY = np.finfo(float).tiny


def relative_change(value, reference):
    return float(abs(value-reference)/max(abs(reference), TINY))


def verdict(checks, **data):
    checks = {name: bool(value) for name, value in checks.items()}
    return dict(passed=all(checks.values()), checks=checks, **data)


# ----------------------------------------------------------------------------- inputs

OFF = WeakeningLaw(0., 1., 1., 1.)


def strain_limit(value, *, allow_zero=False):
    bound = number(value, "strain allowance", nonnegative=True)
    if bound > .05 or (bound == 0 and not allow_zero):
        raise ValueError("small-strain allowance must lie in [0, 0.05] (positive for evolution)")
    return bound


def execution_policy(policy):
    """Direct helper calls cannot bypass the declared resource/solver ceilings."""
    if type(policy) is not dict:
        raise ValueError("execution policy required")
    for key, cap in (("max_steps", 256), ("force_iterations", 96)):
        value = policy.get(key)
        if type(value) is not int or not 1 <= value <= cap:
            raise ValueError(key+" outside the fixed execution ceiling")
    for key in ("force_relative", "history_bound_relative"):
        if positive(policy.get(key), key) > 1e-10:
            raise ValueError(key+" exceeds the supported tolerance")


# ----------------------------------------------------------------------------- constitutive response

def respond_force(prep, law, kappa, force, *, rate_guess, guess=None, policy):
    """Invert the strictly increasing F(a) for a supplied state: safeguarded Newton in log rate."""
    execution_policy(policy)
    force = number(force, "transmitted force")
    if force == 0:
        raise ValueError("a nonzero transmitted force is required")
    target, sign = abs(force), math.copysign(1., force)
    u = math.log(positive(abs(rate_guess), "rate guess"))
    lo, hi = -math.inf, math.inf
    cur = respond(prep, law, kappa, sign*math.exp(u), guess)
    iterations = cur["iterations"]
    for evaluation in range(policy["force_iterations"]):
        ratio = abs(cur["force"])/target
        if abs(ratio-1.) <= policy["force_relative"]:
            return dict(cur, iterations=iterations, force_evaluations=evaluation+1)
        r = math.log(ratio)
        if r > 0:
            hi = u
        else:
            lo = u
        slope = abs(cur["rate"])*cur["dforce"]/abs(cur["force"])
        trial = u-r/slope
        if math.isfinite(lo) and math.isfinite(hi):
            candidate = trial if lo < trial < hi else (lo+hi)/2
        else:
            candidate = u+max(min(trial-u, 4.), -4.)
        if candidate == u or not -120. < candidate < 0.:
            raise ValueError("force inversion left the supported rate range or lost resolution")
        u = candidate
        cur = respond(prep, law, kappa, sign*math.exp(u), cur["x"])
        iterations += cur["iterations"]
    raise ValueError("force inversion did not converge")


# ----------------------------------------------------------------------------- evolution

def evolve(prep, law, kappa0, *, control, value, duration_s, steps, strain_bound, policy,
           rate_guess=None, provider=None, inputs=None, deadline=None):
    """Heun steps of raw history under constant axial rate or constant transmitted force.

    Accepted steps are atomic. Only current state, one stage and scalar/per-point
    accounts are retained, never iterate history. Refused steps book nothing.
    """
    if type(prep) is not PreparedColumn or type(law) is not WeakeningLaw:
        raise ValueError("prepared column and typed weakening law required")
    execution_policy(policy)
    if inputs is not None and fingerprint(*inputs) != prep.fingerprint:
        raise ValueError("prepared coefficients are stale for these inputs; prepare again")
    if control not in ("rate", "force"):
        raise ValueError("control must be rate or force")
    if type(steps) is not int or not 1 <= steps <= policy["max_steps"]:
        raise ValueError("accepted steps must be an integer in 1..256")
    bound = strain_limit(strain_bound)
    duration = positive(duration_s, "duration")
    value = number(value, "control value")
    if value == 0:
        raise ValueError("nonzero control value required")
    if control == "force" and rate_guess is None:
        raise ValueError("force control needs an initial rate guess")
    law.certify(prep)
    kappa0 = history_array(prep, kappa0).copy()
    kappa, dt, strain = kappa0.copy(), duration/steps, 0.

    def stage(p, k, previous):
        if control == "rate":
            return respond(p, law, k, value, None if previous is None else previous["x"])
        guess_rate = rate_guess if previous is None else previous["rate"]
        return respond_force(p, law, k, value, rate_guess=guess_rate,
                             guess=None if previous is None else previous["x"], policy=policy)

    current = stage(prep, kappa, None)
    first = current
    layers = int(prep.layer.max())+1
    external = creep = plastic = 0.
    layer_plastic = np.zeros(layers)
    energy = np.zeros(prep.size)          # dissipated J/m^3 per material point (diagnostic)
    yield_stages = (current["plastic_rate"] > 0).astype(int)
    stages, iterations, accepted, status = 1, current["iterations"], 0, "COMPLETE"
    magnitude = [abs(current["force"])]*2
    rates = [abs(current["rate"])]*2
    worst_force_rise = worst_rate_fall = -math.inf
    for _ in range(steps):
        check_deadline(deadline)
        p = prep if provider is None else provider()
        if type(p) is not PreparedColumn or p.fingerprint != prep.fingerprint:
            raise ValueError("replacement preparation changed fixed column inputs")
        trial = kappa+dt*current["kdot"]
        predictor = stage(p, trial, current)
        new_kappa = kappa+dt*(current["kdot"]+predictor["kdot"])/2
        new_strain = strain+dt*(current["rate"]+predictor["rate"])/2
        if abs(new_strain) > bound:
            status = "REFUSED_SMALL_STRAIN"
            break
        if np.any(new_kappa < kappa):
            raise RuntimeError("raw history decreased")
        if np.any(new_kappa-kappa0 > 2*abs(new_strain)*(1+policy["history_bound_relative"])):
            raise RuntimeError("plastic history exceeds the total-strain bound")
        external += dt*(current["work"]+predictor["work"])/2
        creep += dt*(current["creep_work"]+predictor["creep_work"])/2
        plastic += dt*(current["plastic_work"]+predictor["plastic_work"])/2
        for r in (current, predictor):
            layer_plastic += dt/2*np.bincount(prep.layer, 2*prep.weight*r["stress"]*r["plastic_rate"],
                                              minlength=layers)
            energy += dt/2*2*r["stress"]*abs(r["rate"])
        yield_stages += predictor["plastic_rate"] > 0
        kappa, strain = new_kappa, new_strain
        accepted += 1
        previous = current
        current = stage(p, kappa, predictor)
        yield_stages += current["plastic_rate"] > 0
        stages += 2
        iterations += predictor["iterations"]+current["iterations"]
        worst_force_rise = max(worst_force_rise,
                               (abs(current["force"])-abs(previous["force"]))/abs(previous["force"]))
        worst_rate_fall = max(worst_rate_fall,
                              (abs(previous["rate"])-abs(current["rate"]))/abs(previous["rate"]))
        magnitude = [min(magnitude[0], abs(current["force"])), max(magnitude[1], abs(current["force"]))]
        rates = [min(rates[0], abs(current["rate"])), max(rates[1], abs(current["rate"]))]
    residual = abs(creep+plastic-external)/external if external else 0.
    if not accepted:
        worst_force_rise = worst_rate_fall = None
    return dict(status=status, accepted_steps=accepted, strain=strain, kappa=kappa, kappa0=kappa0,
                force_start=first["force"], force_end=current["force"],
                rate_start=first["rate"], rate_end=current["rate"],
                force_magnitude_range=magnitude, rate_magnitude_range=rates,
                max_step_force_rise_relative=worst_force_rise, max_step_rate_fall_relative=worst_rate_fall,
                accounts=dict(external_work_j_m2=external, creep_work_j_m2=creep,
                              plastic_work_j_m2=plastic, partition_relative=residual),
                layer_plastic_work_j_m2=layer_plastic.tolist(), energy_density_j_m3=energy,
                yield_stages=yield_stages, stages=stages, scalar_iterations=int(iterations),
                final=current)


def force_envelope(prep, law, kappa, rates, duration_s, strain_bound):
    """|F| bounds over a window with |a| in [lo, hi]: history rises by at most 2 max|a| t."""
    bound = strain_limit(strain_bound)
    lo, hi = (number(r, "rate bound") for r in rates)
    if lo*hi <= 0 or abs(lo) > abs(hi):
        raise ValueError("rate bounds must share a nonzero sign and be ordered by magnitude")
    allowance = abs(hi)*positive(duration_s, "window")
    if allowance > bound:
        raise ValueError("window leaves the small-strain representation")
    law.certify(prep)
    kappa = history_array(prep, kappa)
    return dict(minimum=abs(respond(prep, law, kappa+2*allowance, lo)["force"]),
                maximum=abs(respond(prep, law, kappa, hi)["force"]), history_allowance=2*allowance)


def rate_envelope(prep, law, kappa, force, strain_allowance, *, rate_guess, policy):
    """|a| bounds at constant force when history can rise by at most 2 strain_allowance."""
    strain_allowance = strain_limit(strain_allowance, allow_zero=True)
    law.certify(prep)
    kappa = history_array(prep, kappa)
    slow = respond_force(prep, law, kappa, force, rate_guess=rate_guess, policy=policy)
    fast = respond_force(prep, law, kappa+2*strain_allowance, force, rate_guess=slow["rate"], policy=policy)
    return dict(minimum=abs(slow["rate"]), maximum=abs(fast["rate"]))


# ----------------------------------------------------------------------------- case

def validate_case(spec):
    """Strict schema: no silently supplied elastic, healing, pore-fluid or nonlocal law."""
    fields = {"schema", "status", "scope", "provenance", "representation", "weakening",
              "diagnostic_thermal", "layers", "campaign", "policy"}
    if type(spec) is not dict or set(spec) != fields or spec["schema"] != SCHEMA:
        raise ValueError("weakening case schema or top-level fields mismatch")
    rep = spec["representation"]
    extra = {"pressure_closure", "gravity_m_s2", "max_axial_strain", "nonlocal_depth_length_m", "healing_per_s"}
    if type(rep) is not dict or set(rep) != set(REPRESENTATION) | extra:
        raise ValueError("representation must declare only the supported column fields")
    for key, text in REPRESENTATION.items():
        if rep[key] != text:
            raise ValueError("only the declared column representation is supported: "+key)
    if rep["pressure_closure"] != LITHOSTATIC:
        raise ValueError("the campaign uses the lithostatic vertical-stress closure")
    positive(rep["gravity_m_s2"], "gravity")
    strain_limit(rep["max_axial_strain"])
    if rep["nonlocal_depth_length_m"] != 0:
        raise ValueError("no depth-nonlocal weakening: the uniform-rate column cannot localise in depth")
    if rep["healing_per_s"] != 0:
        raise ValueError("no healing law is admitted; raw history only accumulates")
    WeakeningLaw.from_spec(spec["weakening"])
    diag = spec["diagnostic_thermal"]
    if type(diag) is not dict or set(diag) != {"heat_capacity_J_kg_K", "conductivity_W_m_K"}:
        raise ValueError("diagnostic thermal inputs are capacity and conductivity only")
    for key in diag:
        positive(diag[key], key)
    validate_layers(spec["layers"], LITHOSTATIC)
    camp = spec["campaign"]
    if type(camp) is not dict or set(camp) != {
            "rate_s", "total_strain", "initial_history_by_layer", "reference_order", "reference_steps",
            "time_steps", "orders", "warm_offset_k", "homogeneous", "plastic", "force", "refusal"}:
        raise ValueError("campaign fields mismatch")
    history = camp["initial_history_by_layer"]
    if type(history) is not list or len(history) != len(spec["layers"]):
        raise ValueError("one initial history value per layer")
    for value in history:
        number(value, "initial history", nonnegative=True)
    if not 0 < camp["total_strain"] < rep["max_axial_strain"]:
        raise ValueError("campaign strain must stay inside the small-strain bound")
    for n in camp["time_steps"]+[camp["reference_steps"]]+camp["homogeneous"]["steps"]+[camp["force"]["steps"]]:
        if type(n) is not int or not 1 <= n <= 256:
            raise ValueError("step counts must be integers in 1..256")
    pol = spec["policy"]
    if type(pol) is not dict or set(pol) != POLICY_KEYS or pol["max_steps"] != 256:
        raise ValueError("policy fields mismatch or step ceiling changed")
    execution_policy(pol)
    return spec


def load_case(path=CASE):
    return validate_case(json.loads(Path(path).read_text(encoding="utf-8")))


def law_of(spec):
    return WeakeningLaw.from_spec(spec["weakening"])


def base_prepare(spec, order=None, offset_k=0., offsets=None):
    layers = copy.deepcopy(spec["layers"])
    for i, layer in enumerate(layers):
        shift = offset_k if offsets is None else offsets[i]
        layer["temperature_k"] = [t+shift for t in layer["temperature_k"]]
    order = spec["campaign"]["reference_order"] if order is None else order
    rep = spec["representation"]
    return prepare(layers, order, closure=rep["pressure_closure"], gravity=rep["gravity_m_s2"]), layers


def initial_history(prep, spec):
    return np.asarray(spec["campaign"]["initial_history_by_layer"], dtype=float)[prep.layer]


def run(spec, prep, law, kappa0, *, steps=None, control="rate", value=None, rate_guess=None,
        strain=None, provider=None, deadline=None):
    camp = spec["campaign"]
    return evolve(prep, law, kappa0, control=control,
                  value=camp["rate_s"] if value is None else value,
                  duration_s=(camp["total_strain"] if strain is None else strain)/camp["rate_s"],
                  steps=camp["reference_steps"] if steps is None else steps,
                  strain_bound=spec["representation"]["max_axial_strain"], policy=spec["policy"],
                  rate_guess=rate_guess, provider=provider, deadline=deadline)


def summary(out, prep):
    """Reportable scalars only; per-point arrays stay in memory."""
    data = {k: out[k] for k in ("status", "accepted_steps", "strain", "force_start", "force_end",
                                "rate_start", "rate_end", "force_magnitude_range", "rate_magnitude_range",
                                "max_step_force_rise_relative", "max_step_rate_fall_relative", "accounts",
                                "layer_plastic_work_j_m2", "stages", "scalar_iterations")}
    gain = out["kappa"]-out["kappa0"]
    data["max_history_gain_by_layer"] = [float(gain[prep.layer == i].max()) for i in range(int(prep.layer.max())+1)]
    yielding = out["final"]["plastic_rate"] > 0
    data["yielding_points_final"] = int(np.count_nonzero(yielding))
    data["yielding_depth_km_by_layer_final"] = [
        [float(prep.depth_m[m].min()/1e3), float(prep.depth_m[m].max()/1e3)] if m.any() else None
        for m in (yielding & (prep.layer == i) for i in range(int(prep.layer.max())+1))]
    data["never_yielded_points"] = int(np.count_nonzero(out["yield_stages"] == 0))
    data["quadrature_points"] = prep.size
    return data


# ----------------------------------------------------------------------------- oracles

def closed_form(layer_values, sigma_v, rate, lam=(1., 1.)):
    """Negligible creep, lithostatic closure: s = (C cos phi + (sv-Pp) sin phi + 2 eta e)/(1 +- sin phi)."""
    c = layer_values["cohesion_pa"]*lam[0]
    phi = layer_values["friction_rad"]*lam[1]
    e, eta, pore = abs(rate), layer_values["plastic_viscosity_pa_s"], layer_values["pore_pressure_pa"][0]
    sign = math.copysign(1., rate)
    s = (c*math.cos(phi)+(sigma_v-pore)*math.sin(phi)+2*eta*e)/(1+sign*math.sin(phi))
    if sigma_v-sign*s-pore <= 0:                     # compressive-friction clamp reached
        s = c*math.cos(phi)+2*eta*e
        if sigma_v-sign*s-pore > 0:
            raise ValueError("closed-form branch ambiguous")
    return s


def aspect_factors(kappa, law):
    """Independent scalar transcription of ASPECT's calculate_plastic_weakening."""
    cut = min(max(kappa, law.start), law.end)
    fraction = (cut-law.start)/(law.start-law.end)
    return 1.+(1.-law.cohesion_factor)*fraction, 1.+(1.-law.friction_factor)*fraction


def homogeneous_oracle(layer, law, rate, kappa0, duration):
    """Scalar DOP853 history with the column kernel re-prepared at every evaluation."""
    mechanisms = tuple(column.Creep(**c) for c in layer["creep"])
    t, p, pore = layer["temperature_k"][0], layer["mean_pressure_pa"][0], layer["pore_pressure_pa"][0]

    def local(k):
        lc, lf = aspect_factors(k, law)
        return column.LocalLaw.prepare(
            mechanisms, t, p, grain_m=layer["grain_m"], cohesion_pa=layer["cohesion_pa"]*lc,
            friction_rad=layer["friction_rad"]*lf, pore_pressure_pa=pore,
            plastic_viscosity_pa_s=layer["plastic_viscosity_pa_s"]).solve(abs(rate))

    sol = solve_ivp(lambda _t, y: [2*local(float(y[0]))["plastic_rate_s"]], (0., duration), [kappa0],
                    method="DOP853", rtol=1e-10, atol=1e-14)
    if not sol.success:
        raise RuntimeError("scalar oracle failed")
    end = float(sol.y[0, -1])
    return dict(history_gain=end-kappa0,
                force=math.copysign(2*layer["thickness_m"]*local(end)["stress_pa"], rate),
                evaluations=int(sol.nfev), always_yielding=local(kappa0)["plastic_rate_s"] > 0)


def fixed_point_parity(prep, law, kappa, response):
    """Kernel re-prepared at P* = sv - sign(a) s must reproduce every adapter stress."""
    lam_c, lam_f = law.factors(np.asarray(kappa, float))
    sign, e = math.copysign(1., response["rate"]), abs(response["rate"])
    worst, compared, skipped, tensile = 0., 0, 0, 0
    for i in range(prep.size):
        s = float(response["stress"][i])
        p_star = float(prep.reference_pa[i])-sign*s
        mechanisms, grain, eta = prep.layer_inputs[int(prep.layer[i])]
        tensile += p_star < 0                        # compressive-friction clamp, no tensile law
        if p_star < 0 and any(m.volume_m3_mol > 0 for m in mechanisms):
            skipped += 1
            continue
        kernel = column.LocalLaw.prepare(
            mechanisms, float(prep.temperature_k[i]), max(p_star, 0.), grain_m=grain,
            cohesion_pa=float(prep.cohesion_pa[i]*lam_c[i]), friction_rad=float(prep.friction_rad[i]*lam_f[i]),
            pore_pressure_pa=float(prep.pore_pa[i]), plastic_viscosity_pa_s=eta).solve(e)
        worst = max(worst, abs(kernel["stress_pa"]-s)/s)
        compared += 1
    return dict(max_relative=worst, compared=compared, skipped=skipped, tensile_mean_stress_points=int(tensile))


def vertical_load_as_mean_pressure(layers, history_by_layer, law, gravity, order, rate):
    """Kernel force when the lithostatic vertical load is supplied as absolute mean pressure.

    This is the sign-symmetric convention the column kernel leaves to the mechanics owner.
    """
    top, kernel_layers = 0., []
    for layer, k in zip(layers, history_by_layer):
        lc, lf = aspect_factors(k, law)
        bottom = top+number(layer["density_kg_m3"], "density")*gravity*number(layer["thickness_m"], "thickness")
        kernel_layers.append({key: layer[key] for key in COMMON_LAYER_KEYS - {"name"}} | dict(
            mean_pressure_pa=[top, bottom], cohesion_pa=layer["cohesion_pa"]*lc,
            friction_rad=layer["friction_rad"]*lf))
        top = bottom
    return column.Column(kernel_layers, order).solve(rate)["force_n_m"]


def order(errors):
    return [math.log2(a/b) if a > 0 and b > 0 else math.nan for a, b in zip(errors, errors[1:])]


# ----------------------------------------------------------------------------- controls

def kernel_control(spec, deadline=None):
    """Exact limits: kernel parity, closed forms, pressure-closure fixed point and issue."""
    pol, camp, rep = spec["policy"], spec["campaign"], spec["representation"]
    reviewed = json.loads(COLUMN_CASE.read_text(encoding="utf-8"))
    if reviewed["policy"] != column.POLICY:
        raise ValueError("reviewed column case policy differs from the imported kernel")
    rate = reviewed["axial_rate_s"]
    kernel_column = column.Column(reviewed["layers"], camp["reference_order"])
    begin = time.perf_counter()
    kernel = kernel_column.solve(rate)
    kernel_seconds = time.perf_counter()-begin
    supplied = prepare(reviewed["layers"], camp["reference_order"], closure=SUPPLIED)
    begin = time.perf_counter()
    ours = respond(supplied, OFF, np.zeros(supplied.size), rate)
    ours_seconds = time.perf_counter()-begin
    point = max(relative_change(ours["stress"][i], law_.solve(abs(rate))["stress_pa"])
                for i, (_, law_) in enumerate(kernel_column.points))
    # Closed forms with negligible creep and the lithostatic closure.
    pl = camp["plastic"]
    law = law_of(spec)
    base = dict(spec["layers"][0], creep=[pl["negligible_creep"]], density_kg_m3=pl["density_kg_m3"])
    closed = []
    for thickness in (pl["deep_thickness_m"], pl["shallow_thickness_m"]):
        prep = prepare([dict(base, thickness_m=thickness)], 2, closure=LITHOSTATIC, gravity=rep["gravity_m_s2"])
        for k, sign in ((0., 1.), (0., -1.), (pl["weakened_history"], 1.), (pl["weakened_history"], -1.)):
            lam = aspect_factors(k, law)
            res = respond(prep, law, np.full(prep.size, k), sign*camp["rate_s"])
            for i in range(prep.size):
                exact = closed_form(base, float(prep.reference_pa[i]), sign*camp["rate_s"], lam)
                closed.append(relative_change(res["stress"][i], exact))
    # The issue: the kernel with supplied mean pressure equal to the vertical load.
    prep, _ = base_prepare(spec)
    kappa0 = initial_history(prep, spec)
    ext = respond(prep, law, kappa0, camp["rate_s"])
    comp = respond(prep, law, kappa0, -camp["rate_s"])
    fp_ext, fp_comp = fixed_point_parity(prep, law, kappa0, ext), fixed_point_parity(prep, law, kappa0, comp)
    legacy = vertical_load_as_mean_pressure(spec["layers"], camp["initial_history_by_layer"], law,
                                            rep["gravity_m_s2"], camp["reference_order"], camp["rate_s"])
    checks = dict(
        kernel_force_parity=relative_change(ours["force"], kernel["force_n_m"]) <= pol["kernel_parity_relative"],
        kernel_work_parity=relative_change(ours["plastic_work"], kernel["plastic_work_w_m2"]) <= pol["kernel_parity_relative"],
        kernel_point_parity=point <= pol["kernel_parity_relative"],
        closed_forms=max(closed) <= pol["closed_form_relative"],
        fixed_point=max(fp_ext["max_relative"], fp_comp["max_relative"]) <= pol["fixed_point_relative"],
        all_points_compared=fp_ext["skipped"] == 0 and fp_comp["skipped"] == 0,
        extension_compression_asymmetry=ext["force"] < legacy < -comp["force"])
    return verdict(checks, reviewed_case_force=dict(kernel=kernel["force_n_m"], adapter=ours["force"],
                   relative=relative_change(ours["force"], kernel["force_n_m"]), max_point_relative=point,
                   kernel_seconds=kernel_seconds, adapter_seconds=ours_seconds,
                   scope="one prepared 192-point column solve each; not a speed claim"),
                   closed_form_max_relative=max(closed), closed_form_cases=len(closed),
                   fixed_point=dict(extension=fp_ext, compression=fp_comp),
                   pressure_closure_issue=dict(
                       supplied_mean_equal_vertical_load_n_m=legacy, lithostatic_extension_n_m=ext["force"],
                       lithostatic_compression_n_m=comp["force"], extension_ratio=ext["force"]/legacy,
                       compression_ratio=-comp["force"]/legacy))


def homogeneous_control(spec, deadline=None):
    pol, h = spec["policy"], spec["campaign"]["homogeneous"]
    law = law_of(spec)
    layer = h["layer"]
    prep = prepare([layer], h["order"], closure=SUPPLIED)
    rate = spec["campaign"]["rate_s"]
    duration = h["total_strain"]/rate
    oracle = homogeneous_oracle(layer, law, rate, h["initial_history"], duration)
    kappa0 = np.full(prep.size, float(h["initial_history"]))
    runs = [evolve(prep, law, kappa0, control="rate", value=rate, duration_s=duration, steps=n,
                   strain_bound=spec["representation"]["max_axial_strain"], policy=pol, deadline=deadline)
            for n in h["steps"]]
    gains = [float(r["kappa"][0]-h["initial_history"]) for r in runs]
    errors = [relative_change(g, oracle["history_gain"]) for g in gains]
    force_errors = [relative_change(r["force_end"], oracle["force"]) for r in runs]
    spread = max(float(np.ptp(r["kappa"]))/float(r["kappa"].max()) for r in runs)
    orders = order(errors)
    lo, hi = pol["order_range"]
    fine = runs[-1]
    checks = dict(uniform=spread <= pol["uniform_relative"], always_yielding=bool(np.all(fine["yield_stages"] == fine["stages"])),
                  inside_interval=law.start < h["initial_history"] and float(fine["kappa"].max()) < law.end,
                  order=all(lo <= o <= hi for o in orders), finest_history=errors[-1] <= pol["oracle_relative"],
                  finest_force=force_errors[-1] <= pol["oracle_relative"],
                  work=all(r["accounts"]["partition_relative"] <= pol["work_relative"] for r in runs))
    return verdict(checks, oracle=oracle, steps=h["steps"], history_gains=gains, history_errors=errors,
                   force_errors=force_errors, observed_orders=orders, uniform_relative_spread=spread)


def local_control(spec, deadline=None):
    """No hidden coupling under rate control; published interval unreachable from zero history."""
    law = law_of(spec)
    prep, layers = base_prepare(spec)
    kappa0 = initial_history(prep, spec)
    a = run(spec, prep, law, kappa0, deadline=deadline)
    offsets = [0.]+[spec["campaign"]["warm_offset_k"]]*(len(layers)-1)
    other, _ = base_prepare(spec, offsets=offsets)
    b = run(spec, other, law, kappa0, deadline=deadline)
    target = prep.layer == 0
    off = run(spec, prep, OFF, kappa0, deadline=deadline)
    zero = run(spec, prep, law, np.zeros(prep.size), deadline=deadline)
    checks = dict(
        upper_crust_history_bitwise=np.array_equal(a["kappa"][target], b["kappa"][target]),
        perturbation_acted=not np.array_equal(a["kappa"][~target], b["kappa"][~target]),
        weakening_off_force_constant=off["force_magnitude_range"][0] == off["force_magnitude_range"][1],
        unreachable_interval_bitwise=zero["force_end"] == off["force_end"] and zero["force_start"] == off["force_start"],
        unreachable_history_below_start=float(zero["kappa"].max()) < law.start,
        history_accumulates_without_weakening=float(zero["kappa"].max()) > 0)
    return verdict(checks, upper_crust_points=int(target.sum()),
                   off_force_n_m=off["force_end"], zero_history_max=float(zero["kappa"].max()),
                   interval_start=law.start,
                   minimum_homogeneous_axial_strain_to_reach_interval=law.start/2)


def layered_control(spec, deadline=None):
    """Physical sensitivity (+100 K, weakening on/off), time/depth refinement, accounting, envelope."""
    pol, camp = spec["policy"], spec["campaign"]
    law = law_of(spec)
    ref_order, ref_steps = camp["reference_order"], camp["reference_steps"]
    prep, _ = base_prepare(spec)
    kappa0 = initial_history(prep, spec)
    base_on = run(spec, prep, law, kappa0, deadline=deadline)
    base_off = run(spec, prep, OFF, kappa0, deadline=deadline)
    warm, _ = base_prepare(spec, offset_k=camp["warm_offset_k"])
    warm_on = run(spec, warm, law, kappa0, deadline=deadline)
    warm_off = run(spec, warm, OFF, kappa0, deadline=deadline)
    by_steps = {ref_steps: base_on}
    for n in camp["time_steps"]:
        if n not in by_steps:
            by_steps[n] = run(spec, prep, law, kappa0, steps=n, deadline=deadline)
    by_order = {ref_order: base_on}
    for q in camp["orders"]:
        if q not in by_order:
            p, _ = base_prepare(spec, order=q)
            by_order[q] = run(spec, p, law, initial_history(p, spec), deadline=deadline)
    ts, qs = sorted(by_steps), sorted(by_order)
    time_changes = [relative_change(by_steps[a]["force_end"], by_steps[b]["force_end"]) for a, b in zip(ts, ts[1:])]
    depth_changes = [relative_change(by_order[a]["force_end"], by_order[b]["force_end"]) for a, b in zip(qs, qs[1:])]
    feedback = lambda r: (r["force_start"]-r["force_end"])/r["force_start"]
    fb_order = {q: feedback(by_order[q]) for q in qs}
    fb_depth = relative_change(fb_order[qs[-2]], fb_order[qs[-1]])
    resolution = max(time_changes[-1], depth_changes[-1])
    diag = spec["diagnostic_thermal"]
    energy = base_on["energy_density_j_m3"]
    heating = float((energy/(prep.density*diag["heat_capacity_J_kg_K"])).max())
    duration = camp["total_strain"]/camp["rate_s"]
    diffusivity = diag["conductivity_W_m_K"]/(float(prep.density.min())*diag["heat_capacity_J_kg_K"])
    envelope = force_envelope(prep, law, kappa0, (camp["rate_s"], camp["rate_s"]), duration,
                              spec["representation"]["max_axial_strain"])
    fp = fixed_point_parity(prep, law, base_on["kappa"], base_on["final"])
    runs = dict(base_on=base_on, base_off=base_off, warm_on=warm_on, warm_off=warm_off)
    unchanged = base_on["yield_stages"] == 0
    margin = 1+pol["monotone_relative"]
    checks = dict(
        time_refinement=time_changes[-1] <= pol["time_relative"],
        depth_refinement=depth_changes[-1] <= pol["depth_relative"],
        feedback_depth_refinement=fb_depth <= pol["feedback_depth_relative"],
        feedback_resolved=feedback(base_on) >= pol["coupling_resolution_factor"]*resolution,
        warm_feedback_resolved=feedback(warm_on) >= pol["coupling_resolution_factor"]*resolution,
        warmer_is_weaker=warm_on["force_start"] < base_on["force_start"] and warm_on["force_end"] < base_on["force_end"],
        weakening_off_constant=all(r["force_magnitude_range"][0] == r["force_magnitude_range"][1] for r in (base_off, warm_off)),
        monotone_weakening=all(r["max_step_force_rise_relative"] <= pol["monotone_relative"] for r in (base_on, warm_on)),
        work_partition=all(r["accounts"]["partition_relative"] <= pol["work_relative"]
                           for r in list(runs.values())+list(by_steps.values())+list(by_order.values())),
        subyield_history_bitwise=np.array_equal(base_on["kappa"][unchanged], kappa0[unchanged]),
        envelope=envelope["minimum"]/margin <= base_on["force_magnitude_range"][0]
        and base_on["force_magnitude_range"][1] <= envelope["maximum"]*margin,
        end_state_fixed_point=fp["max_relative"] <= pol["fixed_point_relative"] and fp["skipped"] == 0,
        all_complete=all(r["status"] == "COMPLETE" for r in list(runs.values())+list(by_steps.values())+list(by_order.values())))
    names = [layer["name"] for layer in spec["layers"]]
    plastic_share = lambda r: dict(zip(names, (np.asarray(r["layer_plastic_work_j_m2"])/r["accounts"]["external_work_j_m2"]).tolist()))
    return verdict(
        checks,
        runs={k: summary(v, warm if k.startswith("warm") else prep) for k, v in runs.items()},
        evolving_force_reduction=dict(base=feedback(base_on), warm=feedback(warm_on)),
        inherited_force_reduction=dict(base=(base_off["force_start"]-base_on["force_start"])/base_off["force_start"],
                                       warm=(warm_off["force_start"]-warm_on["force_start"])/warm_off["force_start"]),
        plastic_work_share_by_layer=dict(base=plastic_share(base_on), warm=plastic_share(warm_on)),
        time_steps=ts, time_force_changes=time_changes, time_observed_order=order(time_changes),
        orders=qs, depth_force_changes=depth_changes, feedback_by_order=fb_order,
        feedback_depth_change=fb_depth, force_envelope_n_m=envelope, end_state_fixed_point=fp,
        subyield_points=int(unchanged.sum()),
        diagnostics=dict(max_dissipation_j_m3=float(energy.max()), equivalent_adiabatic_heating_k=heating,
                         conduction_length_m=math.sqrt(diffusivity*duration), duration_s=duration,
                         note="diagnostic only; prescribed temperature receives no heat or conduction feedback"))


def force_control(spec, deadline=None):
    pol, camp = spec["policy"], spec["campaign"]
    law = law_of(spec)
    prep, _ = base_prepare(spec)
    kappa0 = initial_history(prep, spec)
    a0 = camp["rate_s"]
    f_on = respond(prep, law, kappa0, a0)["force"]
    f_off = respond(prep, OFF, kappa0, a0)["force"]
    steps = camp["force"]["steps"]
    on = run(spec, prep, law, kappa0, control="force", value=f_on, rate_guess=a0, steps=steps, deadline=deadline)
    off = run(spec, prep, OFF, kappa0, control="force", value=f_off, rate_guess=a0, steps=steps, deadline=deadline)
    envelope = rate_envelope(prep, law, kappa0, f_on, spec["representation"]["max_axial_strain"],
                             rate_guess=a0, policy=pol)
    margin = 1+pol["inverse_rate_relative"]
    work_identity = relative_change(on["accounts"]["external_work_j_m2"], f_on*on["strain"])
    checks = dict(
        inverse_consistency=relative_change(on["rate_start"], a0) <= pol["inverse_rate_relative"],
        weakening_off_rate_constant=max(relative_change(r, a0) for r in off["rate_magnitude_range"]) <= pol["inverse_rate_relative"],
        accelerates=on["rate_end"] > on["rate_start"] and on["max_step_rate_fall_relative"] <= pol["inverse_rate_relative"],
        work_identity=work_identity <= pol["force_work_relative"],
        rate_envelope=envelope["minimum"]/margin <= on["rate_magnitude_range"][0]
        and on["rate_magnitude_range"][1] <= envelope["maximum"]*margin,
        complete=on["status"] == "COMPLETE" and off["status"] == "COMPLETE",
        work_partition=max(on["accounts"]["partition_relative"], off["accounts"]["partition_relative"]) <= pol["work_relative"])
    return verdict(checks, transmitted_force_n_m=f_on, weakening_on=summary(on, prep), weakening_off=summary(off, prep),
                   rate_gain=on["rate_end"]/on["rate_start"], strain_reached=on["strain"],
                   rate_envelope_s=envelope, work_identity_relative=work_identity)


def refusal_control(spec, deadline=None):
    pol, camp = spec["policy"], spec["campaign"]
    law = law_of(spec)
    refused = {}

    def expect(name, fn):
        try:
            fn()
        except ValueError:
            refused[name] = True
        else:
            refused[name] = False

    def mutated(path, value):
        bad = copy.deepcopy(spec)
        target = bad
        for key in path[:-1]:
            target = target[key]
        if value is KeyError:
            del target[path[-1]]
        else:
            target[path[-1]] = value
        return lambda: validate_case(bad)

    for name, path, value in (
            ("healing", ("representation", "healing_per_s"), 1e-15),
            ("depth_nonlocal", ("representation", "nonlocal_depth_length_m"), 5000.),
            ("large_strain_bound", ("representation", "max_axial_strain"), .2),
            ("eulerian_temperature", ("representation", "temperature"), "prescribed Eulerian geotherm"),
            ("supplied_closure_campaign", ("representation", "pressure_closure"), SUPPLIED),
            ("elastic_modulus", ("representation", "elastic_modulus_pa"), 1e11),
            ("pore_fluid_law", ("pore_pressure_law",), "drained"),
            ("zero_factor", ("weakening", "cohesion_factor"), 0.),
            ("strengthening_factor", ("weakening", "friction_factor"), 1.5),
            ("reversed_interval", ("weakening", "interval_engineering"), [3., 1.]),
            ("unknown_creep_key", ("layers", 0, "creep", 0, "healing"), 1.),
            ("missing_density", ("layers", 0, "density_kg_m3"), KeyError),
            ("step_ceiling", ("policy", "max_steps"), 512)):
        expect(name, mutated(path, value))
    prep, layers = base_prepare(spec)
    kappa0 = initial_history(prep, spec)
    common = dict(control="rate", value=camp["rate_s"], duration_s=1e12, strain_bound=.05, policy=pol)
    expect("friction_only_with_cohesion", lambda: WeakeningLaw(1., 3., 1., .25).certify(prep))
    for n in (0, 257, 2.):
        expect("steps_%r" % (n,), lambda n=n: evolve(prep, law, kappa0, steps=n, **common))
    expect("negative_history", lambda: evolve(prep, law, -kappa0, steps=2, **common))
    expect("history_shape", lambda: evolve(prep, law, kappa0[:3], steps=2, **common))
    expect("zero_rate", lambda: evolve(prep, law, kappa0, steps=2, **dict(common, value=0.)))
    stale = (_warmed(layers), camp["reference_order"], LITHOSTATIC, spec["representation"]["gravity_m_s2"])
    expect("stale_preparation", lambda: evolve(prep, law, kappa0, steps=2, inputs=stale, **common))
    expect("window_beyond_small_strain", lambda: force_envelope(prep, law, kappa0, (camp["rate_s"],)*2, 1e15, .05))
    r = camp["refusal"]
    single = dict(spec["layers"][2], thickness_m=1000., creep=[dict(spec["layers"][2]["creep"][0],
                                                                    volume_m3_mol=r["compressive_volume_m3_mol"])])
    tiny = prepare([single], 2, closure=LITHOSTATIC, gravity=spec["representation"]["gravity_m_s2"])
    expect("compressive_nonmonotone_creep", lambda: respond(tiny, OFF, np.zeros(2), -1e-12))
    strained = run(spec, prep, law, kappa0, steps=r["steps"], strain=r["total_strain"], deadline=deadline)
    gain = float((strained["kappa"]-kappa0).max())
    checks = {("refuse_"+k): v for k, v in refused.items()}
    checks.update(
        small_strain_refused=strained["status"] == "REFUSED_SMALL_STRAIN",
        refused_step_not_booked=strained["accepted_steps"] < r["steps"]
        and abs(strained["strain"]) <= spec["representation"]["max_axial_strain"],
        refused_history_bounded=gain <= 2*abs(strained["strain"])*(1+pol["history_bound_relative"]),
        refused_accounts_close=strained["accounts"]["partition_relative"] <= pol["work_relative"])
    return verdict(checks, refused_cases=sorted(refused), accepted_before_refusal=strained["accepted_steps"],
                   strain_at_refusal=strained["strain"])


def _warmed(layers):
    out = copy.deepcopy(layers)
    out[0]["temperature_k"] = [t+1e-9 for t in out[0]["temperature_k"]]
    return out


def reuse_control(spec, deadline=None):
    """Prepared coefficients reused while inputs are unchanged versus re-preparing each step."""
    law = law_of(spec)
    prep, layers = base_prepare(spec)
    kappa0 = initial_history(prep, spec)
    rep = spec["representation"]
    key = (layers, spec["campaign"]["reference_order"], LITHOSTATIC, rep["gravity_m_s2"])
    begin = time.perf_counter()
    reused = run(spec, prep, law, kappa0, deadline=deadline)
    reused_seconds = time.perf_counter()-begin
    begin = time.perf_counter()
    rebuilt = run(spec, prep, law, kappa0, deadline=deadline,
                  provider=lambda: prepare(layers, key[1], closure=LITHOSTATIC, gravity=key[3]))
    rebuilt_seconds = time.perf_counter()-begin
    same = (np.array_equal(reused["kappa"], rebuilt["kappa"]) and reused["force_end"] == rebuilt["force_end"]
            and reused["accounts"] == rebuilt["accounts"])
    checks = dict(bitwise_parity=same, fingerprint_matches=fingerprint(*key) == prep.fingerprint,
                  changed_input_changes_fingerprint=fingerprint(_warmed(layers), *key[1:]) != prep.fingerprint)
    return verdict(checks, reused_seconds=reused_seconds, rebuilt_seconds=rebuilt_seconds,
                   saved_seconds=rebuilt_seconds-reused_seconds,
                   saved_percent=100*(rebuilt_seconds-reused_seconds)/rebuilt_seconds,
                   scope="one matched reference evolution; re-preparation per accepted step versus reuse; not a generator speedup")


CONTROLS = (("kernel", kernel_control), ("homogeneous", homogeneous_control), ("local", local_control),
            ("layered", layered_control), ("force", force_control), ("refusal", refusal_control),
            ("reuse", reuse_control))


def bindings():
    # I02.2a: the executed package owners are bound where they were imported from, outside ROOT refusing.
    paths = [Path(__file__), CASE, ROOT/"docs/I01_WEAKENING.md", ROOT/"tests/test_i01_weakening.py",
             Path(column.__file__), COLUMN_CASE, COLUMN_RECEIPT,
             Path(_integration_weakening.__file__), Path(_integration_column.__file__)]
    return {p.resolve().relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def reviewed_helper(current):
    """Imported kernel bytes must equal those its reviewed receipt recorded.

    The package kernel file is compared too: a receipt that never recorded it cannot vouch for it.
    """
    recorded = json.loads(COLUMN_RECEIPT.read_text(encoding="utf-8"))["source_sha256"]
    return {name: recorded.get(name) == current[name]
            for name in ("tools/check_i01_column.py", "cases/i01_column_v1.json",
                         "src/atlas_tectonics/_integration_column.py")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream, threadpool_limits(limits=1, user_api="blas"):
        result = dict(schema="atlas.i01-weakening-evidence.v1", status="INCOMPLETE", scientific_acceptance=False,
                      runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                                   system=platform.system(), machine=platform.machine(), blas_threads=1),
                      controls={})
        start = time.perf_counter()
        try:
            before = bindings()
            spec = load_case()
            result.update(source_sha256=before, kernel_bytes_match_reviewed_receipt=reviewed_helper(before),
                          kernel_policy=column.POLICY, spec=spec)
            deadline = time.perf_counter()+spec["policy"]["maximum_seconds"]
            for name, control in CONTROLS:
                begin = time.perf_counter()
                try:
                    data = control(spec, deadline)
                    result["controls"][name] = dict(status="PASS" if data["passed"] else "FAIL",
                                                    seconds=time.perf_counter()-begin, **data)
                except (ValueError, RuntimeError) as exc:
                    result["controls"][name] = dict(status="FAIL", seconds=time.perf_counter()-begin,
                                                    error_type=type(exc).__name__,
                                                    error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
            result["source_unchanged"] = before == bindings()
            passed = (result["source_unchanged"] and all(result["kernel_bytes_match_reviewed_receipt"].values())
                      and all(c["status"] == "PASS" for c in result["controls"].values()))
            result["status"] = "PASS_BOUNDED_COLUMN_WEAKENING_ONLY" if passed else "FAIL"
        except Exception as exc:
            # Deliberately do not publish arbitrary exception paths or tracebacks.
            result.update(status="FAIL", error_type=type(exc).__name__)
            if isinstance(exc, (ValueError, RuntimeError)):
                result["error"] = str(exc).replace(str(ROOT), "TECTONICS_ROOT")
        result["elapsed_seconds"] = time.perf_counter()-start
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result.get(key) for key in ("status", "elapsed_seconds", "error")}
                     | {"controls": {k: v["status"] for k, v in result["controls"].items()}}))
    return 0 if result["status"] == "PASS_BOUNDED_COLUMN_WEAKENING_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
