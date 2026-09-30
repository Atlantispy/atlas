"""I01 material-following finite-strain column under a constant driving force, WORKING NON-CANON.

A closed, laterally uniform, incompressible plane-strain strip of unit strike deforms by affine pure shear about its
surface: w = w0 lam, z = z0/lam, h = h0/lam, lam_dot = a lam and edge speed v = w a = w0 lam_dot. Temperature, raw
plastic history and material labels stay at their material points. Every stage rebuilds the current geometry,
quadrature widths, overburden and creep coefficients before balancing F = D v + F_column(v/w). Conduction follows the
material-coordinate heat equation, whose whole-strip operator is lam^2 times the reference one, so one eigensystem is
advanced along a thermal clock. No inflow, extraction, lateral localisation, rupture, melting or world assembly.
I02.2a: the coupled solver (evolve and its geometry, stage, clock and conduction helpers) is owned by
atlas_tectonics.integration_evolution. This tool re-exports those same objects and keeps the prescribed-history
conduction control, independent oracles, case, campaign, evidence and CLI. I02.2b: evolve is now the compatibility
wrapper over that module's continuable core, and the declared representation texts are the package's one copy.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.integrate import solve_ivp
from scipy.linalg import expm
from scipy.optimize import brentq
import threadpoolctl
from threadpoolctl import threadpool_limits

from atlas_tectonics import (_integration_column, _integration_heat, _integration_motion,
                             _integration_thermomechanical, _integration_weakening, integration_evolution)
# The package-owned solver, re-exported: these are the same objects, not copies.
from atlas_tectonics.integration_evolution import (
    STRETCH_CEILING, TEMPERATURE_CEILING_K, REPRESENTATION, REPRESENTATION_LIMITS, REBUILD_KEYS, STAGE_ACCOUNTS,
    THERMAL_ACCOUNTS, Refused, coefficients, column_at, stage, clock, clock_source, eigensystem, clock_propagator,
    rebuilt_propagator, check_rebuild, advance_map, window_of, paired, weighted, evolve)

import check_i01_thermomechanical_motion as tm

heat, motion, weakening = tm.heat, tm.motion, tm.weakening
column = weakening.column

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT/"cases/i01_finite_strain_v1.json"
SCHEMA = "atlas.i01-finite-strain-case.v1"
PASS = "PASS_BOUNDED_FINITE_STRAIN_ONLY"
TINY = weakening.TINY
# Volume, mass and whole-strip heat capacity are conserved to round-off: at most five correctly rounded operations
# separate the current and reference products on either side, so 16 u bounds the comparison with margin.
CONSERVATION_ROUNDOFF = 16*np.finfo(float).eps/2
BOUND_TOLERANCE = 1e-12                  # float comparison of the declared and computed drag-only stretch bound
number, positive = weakening.number, weakening.positive
relative_change, verdict, check_deadline = weakening.relative_change, weakening.verdict, weakening.check_deadline
ratio, expired, CountdownDeadline, mutated = tm.ratio, tm.expired, tm.CountdownDeadline, tm.mutated
orders, in_range = tm.orders, tm.in_range
# I02.2a: the solver is package-owned, so this tool's own sources include that package file; the retained helpers'
# package owners must likewise have been recorded by the accepted upstream receipts before they can vouch for them.
NEW_FILES = ("tools/check_i01_finite_strain.py", "cases/i01_finite_strain_v1.json", "docs/I01_FINITE_STRAIN.md",
             "tests/test_i01_finite_strain.py", "src/atlas_tectonics/integration_evolution.py")
RETAINED = ("tools/check_i01_thermomechanical_motion.py", "tools/check_i01_column_heat.py",
            "tools/check_i01_motion_coupling.py", "tools/check_i01_weakening.py", "tools/check_i01_column.py",
            "cases/i01_thermomechanical_motion_v1.json", "cases/i01_column_heat_v1.json",
            "cases/i01_motion_coupling_v1.json", "cases/i01_weakening_v1.json",
            "src/atlas_tectonics/_integration_thermomechanical.py", "src/atlas_tectonics/_integration_heat.py",
            "src/atlas_tectonics/_integration_motion.py", "src/atlas_tectonics/_integration_weakening.py",
            "src/atlas_tectonics/_integration_column.py")
ACCEPTED_RECEIPTS = {
    "evidence/i01-thermomechanical-motion-r4.json": "59b91c7d453340b9ee32cd7827f87ee48677cdef498e7cae25aefc207e0eaa13",
    "evidence/i01-column-heat-r5.json": "576ea2153ac23b3e6458594832926d5a9d733bed07eec124ea5280767e7b08a2",
    "evidence/i01-motion-coupling-r3.json": "6aa3837acd8a0e150c0f2dfda581479deb6bdc8eacfb5e51241f0c6f13fb7297"}
IMPORTED = {"tools/check_i01_thermomechanical_motion.py": tm, "tools/check_i01_column_heat.py": heat,
            "tools/check_i01_motion_coupling.py": motion, "tools/check_i01_weakening.py": weakening,
            "tools/check_i01_column.py": column,
            "src/atlas_tectonics/integration_evolution.py": integration_evolution,
            "src/atlas_tectonics/_integration_thermomechanical.py": _integration_thermomechanical,
            "src/atlas_tectonics/_integration_heat.py": _integration_heat,
            "src/atlas_tectonics/_integration_motion.py": _integration_motion,
            "src/atlas_tectonics/_integration_weakening.py": _integration_weakening,
            "src/atlas_tectonics/_integration_column.py": _integration_column}
INPUTS = {"thermomechanical_case": "cases/i01_thermomechanical_motion_v1.json"}
NEW_GATES = {"maximum_seconds": 120., "time_stretch_relative": 1e-4, "depth_stretch_relative": .003}
SPECIAL_POLICY = {"max_steps", "coupling_resolution_factor", "oracle_order_range"}
CAMPAIGN_KEYS = {"reference_order", "reference_steps", "time_steps", "orders", "kinematics", "clock", "homogeneous",
                 "states", "refusal"}
SUB_KEYS = {"kinematics": {"order", "steps", "uniform_departure_k"},
            "clock": {"order", "steps", "final_stretch", "scaling_stretch", "recovery_steps"},
            "homogeneous": {"order", "steps"},
            "states": {"order", "steps", "rest_amplitude_k"},
            "refusal": {"order", "steps", "window_steps", "temperature_margin_k", "temperature_guard_k",
                        "compressive_volume_m3_mol"}}
MECHANICAL = ("drive_work_j_m", "drag_work_j_m", "creep_work_j_m", "plastic_work_j_m", "column_work_j_m", "heat_j_m",
              "stored_j_m")


# ----------------------------------------------------------------------------- exact prescribed-history control

def conduct_history(thermal, stretch, *, duration_s, steps, window, theta0=None, modes=None, deadline=None):
    """EXACT CONTROL ONLY: conduction of material temperatures along a PRESCRIBED smooth stretch history.

    ``stretch(t)`` gives lam at every step end; it starts at 1 and stays inside the window. There is no mechanics,
    drive or history, so this is not generated motion. The clock, eigensystem, clock source and departure accounts
    (J/m^2 of reference area) are those of ``evolve``.
    """
    if type(thermal) is not heat.ThermalColumn:
        raise ValueError("reviewed thermal support required")
    lo, hi, tlo, thi = window_of(window)
    modes = eigensystem(thermal, modes)
    if type(steps) is not int or not 1 <= steps <= 256:
        raise ValueError("accepted steps must be an integer in 1..256")
    duration = positive(duration_s, "duration")
    dt = duration/steps

    def at(n):
        value = number(stretch(n*dt), "prescribed stretch", positive=True)
        if not lo <= value <= hi:
            raise ValueError("prescribed stretch leaves the declared window")
        return value
    if at(0) != 1.:
        raise ValueError("a prescribed history starts at the reference geometry")
    for n in range(1, steps+1):
        at(n)
    theta = np.zeros(thermal.size) if theta0 is None else tm.departure(theta0, thermal.size)
    reference = np.asarray(thermal.steady_k)
    if not np.all((reference+theta >= tlo) & (reference+theta <= thi)):
        raise ValueError("initial material temperatures lie outside the declared window")
    theta_start = theta.copy()
    r0, capacity, zero = np.asarray(thermal.radiogenic), np.asarray(thermal.capacity), np.zeros(thermal.size)
    produced = math.fsum(r0)
    g_top, g_bot = thermal.boundary_conductance
    acc = dict(radiogenic_j_m2=0., reference_outflow_j_m2=0., departure_surface_loss_j_m2=0.,
               departure_basal_gain_j_m2=0., thermal_change_j_m2=0.)
    lam, tau, worst, accepted, status = 1., 0., 0., 0, "COMPLETE"
    for n in range(steps):
        if expired(deadline):
            status = "REFUSED_DEADLINE"
            break
        lam_a = at(n+1)
        dtau, _, _ = clock(lam, lam_a, dt)
        new, integral = advance_map(thermal, modes, None, dtau, dt)(theta, clock_source(r0, zero, lam),
                                                                    clock_source(r0, zero, lam_a))
        if expired(deadline):
            status = "REFUSED_DEADLINE"
            break
        if not np.all(np.isfinite(new)):
            raise RuntimeError("prescribed-history temperature is not finite")
        if not np.all((reference+new >= tlo) & (reference+new <= thi)):
            status = "REFUSED_TEMPERATURE_WINDOW"
            break
        radiogenic, outflow = produced*dt, produced*dtau
        surface, base_in = g_top*integral[0], -g_bot*integral[-1]
        change = math.fsum(capacity*(new-theta))
        worst = max(worst, ratio(change-(radiogenic-outflow-surface+base_in),
                                 abs(radiogenic-outflow)+abs(surface)+abs(base_in)))
        acc["radiogenic_j_m2"] += radiogenic
        acc["reference_outflow_j_m2"] += outflow
        acc["departure_surface_loss_j_m2"] += surface
        acc["departure_basal_gain_j_m2"] += base_in
        acc["thermal_change_j_m2"] += change
        theta, lam, tau = new, lam_a, tau+dtau
        accepted += 1
    return dict(status=status, accepted_steps=accepted, elapsed_s=accepted*dt, time_step_s=dt, clock_s=tau,
                stretch=lam, theta=theta, theta0=theta_start, accounts=acc, max_step_energy_relative=worst)


# ----------------------------------------------------------------------------- independent finite-strain oracle

def stretch_balance(layer, law, drive, temperature, kappa, stretch):
    """Independent force balance of a uniform supplied-overburden layer at stretch lam.

    Column kernel LocalLaw at overburden P0/lam, thickness h0/lam and width w0 lam, ASPECT-transcribed weakening
    factors and SciPy Brent in x = |v| D/|F| on [0, 1]; x = 0 is the continuous zero-stress limit.
    """
    mechanisms = tuple(column.Creep(**c) for c in layer["creep"])
    lc, lf = weakening.aspect_factors(kappa, law)
    local = column.LocalLaw.prepare(
        mechanisms, temperature, layer["mean_pressure_pa"][0]/stretch, grain_m=layer["grain_m"],
        cohesion_pa=layer["cohesion_pa"]*lc, friction_rad=layer["friction_rad"]*lf,
        pore_pressure_pa=layer["pore_pressure_pa"][0], plastic_viscosity_pa_s=layer["plastic_viscosity_pa_s"])
    target, sign = abs(drive.force_n_m), math.copysign(1., drive.force_n_m)
    thickness, rate_scale = layer["thickness_m"]/stretch, target/drive.drag_pa_s/(drive.width_m*stretch)

    def residual(x):
        return -1. if x == 0 else x+2*thickness*local.solve(rate_scale*x)["stress_pa"]/target-1.
    x = brentq(residual, 0., 1., xtol=1e-15, rtol=1e-13, maxiter=200)
    r = local.solve(rate_scale*x)
    return dict(velocity_m_s=sign*target/drive.drag_pa_s*x, rate=sign*rate_scale*x, stress_pa=r["stress_pa"],
                creep_rate_s=math.fsum(r["creep_rates_s"]), plastic_rate_s=r["plastic_rate_s"])


def stretch_oracle(layer, thermal, law, drive, kappa0, duration, fractions):
    """Insulated uniform layer under constant drive: DOP853 on (T, kappa, lam), balance re-solved per call."""
    rho_cp = thermal["density_kg_m3"]*thermal["heat_capacity_j_kg_k"]
    t0 = float(layer["temperature_k"][0])

    def rhs(_t, y):
        r = stretch_balance(layer, law, drive, float(y[0]), float(y[1]), float(y[2]))
        heating = 2*r["stress_pa"]*(fractions[0]*r["creep_rate_s"]+fractions[1]*r["plastic_rate_s"])
        return [heating/rho_cp, 2*r["plastic_rate_s"], r["velocity_m_s"]/drive.width_m]
    sol = solve_ivp(rhs, (0., duration), [t0, float(kappa0), 1.], method="DOP853", rtol=1e-10,
                    atol=[1e-9, 1e-14, 1e-14])
    if not sol.success:
        raise RuntimeError("scalar finite-strain oracle failed")
    t_end, k_end, lam_end = map(float, sol.y[:, -1])
    start = stretch_balance(layer, law, drive, t0, float(kappa0), 1.)
    end = stretch_balance(layer, law, drive, t_end, k_end, lam_end)
    return dict(temperature_rise=t_end-t0, history_gain=k_end-kappa0, stretch=lam_end, log_stretch=math.log(lam_end),
                velocity_start_m_s=start["velocity_m_s"], velocity_end_m_s=end["velocity_m_s"],
                evaluations=int(sol.nfev), always_yielding=start["plastic_rate_s"] > 0 and end["plastic_rate_s"] > 0)


# ----------------------------------------------------------------------------- case

def policy_ceilings(tm_policy, heat_policy, weak_policy):
    """Retained tolerances may be tightened, never relaxed; the two new stretch gates are frozen here."""
    out = {key: value for key, value in tm_policy.items() if key not in SPECIAL_POLICY}
    out.update(eigen_finest_k=heat_policy["eigen_finest_k"], kernel_parity_relative=weak_policy["kernel_parity_relative"])
    out.update(NEW_GATES)
    return out


def declared_window(spec):
    rep = spec["representation"]
    return dict(stretch=rep["stretch_window"], temperature_k=rep["temperature_window_k"])


def validate_case(spec):
    """Strict schema; physics and forcing come only from the reviewed thermomechanical case and its inputs."""
    fields = {"schema", "status", "scope", "provenance", "representation", "inputs", "drive", "campaign", "policy"}
    if type(spec) is not dict or set(spec) != fields or spec["schema"] != SCHEMA:
        raise ValueError("finite-strain case schema or top-level fields mismatch")
    rep = spec["representation"]
    if type(rep) is not dict or set(rep) != set(REPRESENTATION) | REPRESENTATION_LIMITS:
        raise ValueError("representation must declare only the supported fields")
    for key, text in REPRESENTATION.items():
        if rep[key] != text:
            raise ValueError("only the declared finite-strain representation is supported: "+key)
    lo, hi, _, _ = window_of(declared_window(spec))
    if not 0 < number(rep["max_temperature_step_k"], "temperature step guard") <= 5:
        raise ValueError("temperature step guard must lie in (0, 5] K")
    if spec["inputs"] != INPUTS:
        raise ValueError("only the reviewed thermomechanical-motion case is admitted")
    if tm.CASE.resolve() != (ROOT/INPUTS["thermomechanical_case"]).resolve():
        raise ValueError("the thermomechanical adapter reads a different case")
    tm_spec, ctx = tm.load_case()
    ends = ctx["heat"]["boundaries"]
    if (ends["top"].get("value_k"), ends["bottom"].get("value_k")) != TEMPERATURE_CEILING_K:
        raise ValueError("the frozen temperature ceiling no longer matches the reviewed boundary temperatures")
    d = spec["drive"]
    if type(d) is not dict or set(d) != {"source", "duration_s", "drag_only_stretch_bound"}:
        raise ValueError("drive declares only its source, duration and drag-only bound; forcing is the reviewed case's")
    drive = ctx["drive"]
    duration = positive(d["duration_s"], "duration")
    bound = abs(drive.force_n_m)/drive.drag_pa_s/drive.width_m*duration     # |lam - 1| <= |F| t/(D w0), any column
    if relative_change(bound, positive(d["drag_only_stretch_bound"], "drag-only stretch bound")) > BOUND_TOLERANCE:
        raise ValueError("declared drag-only stretch bound differs from the reviewed forcing and duration")
    if lo > 1-bound+BOUND_TOLERANCE or hi < 1+bound-BOUND_TOLERANCE:
        raise ValueError("duration exceeds the stretch window guaranteed by the drag-only bound")
    camp = spec["campaign"]
    if type(camp) is not dict or set(camp) != CAMPAIGN_KEYS:
        raise ValueError("campaign fields mismatch")
    for key, keys in SUB_KEYS.items():
        if type(camp[key]) is not dict or set(camp[key]) != keys:
            raise ValueError("campaign sub-fields mismatch: "+key)
    k, c, h, s, r = (camp[key] for key in ("kinematics", "clock", "homogeneous", "states", "refusal"))
    tm.doubled(camp["time_steps"], 256), tm.doubled(camp["orders"], 128)
    tm.doubled(c["steps"], 256), tm.doubled(h["steps"], 256)
    counts = (camp["reference_steps"], k["steps"], s["steps"], r["steps"], r["window_steps"], c["recovery_steps"])
    levels = (camp["reference_order"], k["order"], c["order"], h["order"], s["order"], r["order"], *camp["orders"])
    if (any(type(n) is not int or not 1 <= n <= 256 for n in counts)
            or any(type(q) is not int or not 2 <= q <= 128 for q in levels)):
        raise ValueError("step counts must be integers in 1..256 and quadrature orders in 2..128")
    if camp["reference_steps"] != camp["time_steps"][-1] or camp["reference_order"] != camp["orders"][1]:
        raise ValueError("the reference run is the finest time level and the middle depth level")
    if r["steps"] < 4 or r["window_steps"] < 2:
        raise ValueError("atomic refusal fixtures need later steps to refuse")
    for value, name in ((k["uniform_departure_k"], "uniform departure"), (s["rest_amplitude_k"], "rest amplitude"),
                        (r["temperature_margin_k"], "temperature margin"),
                        (r["compressive_volume_m3_mol"], "refusal activation volume")):
        positive(value, name)
    if not 0 < number(r["temperature_guard_k"], "refusal temperature guard") <= 5:
        raise ValueError("refusal temperature guard must lie in (0, 5] K")
    for key in ("final_stretch", "scaling_stretch"):
        values = c[key]
        if type(values) is not list or not values or any(not lo <= number(v, key) <= hi or v == 1 for v in values):
            raise ValueError(key+" values must lie inside the stretch window and differ from 1")
    pol = spec["policy"]
    ceilings = policy_ceilings(tm_spec["policy"], ctx["heat"]["policy"], ctx["weak"]["policy"])
    if type(pol) is not dict or set(pol) != set(ceilings) | SPECIAL_POLICY or pol["max_steps"] != 256:
        raise ValueError("policy fields mismatch or step ceiling changed")
    for key, ceiling in ceilings.items():
        if not 0 < number(pol[key], key) <= ceiling:
            raise ValueError("policy relaxes a retained or frozen tolerance: "+key)
    if number(pol["coupling_resolution_factor"], "resolution factor") < tm_spec["policy"]["coupling_resolution_factor"]:
        raise ValueError("policy relaxes the retained feedback-resolution factor")
    span, retained = pol["oracle_order_range"], tm_spec["policy"]["oracle_order_range"]
    if type(span) is not list or len(span) != 2 or not retained[0] <= span[0] < span[1] <= retained[1]:
        raise ValueError("oracle order range must lie within the retained range")
    return spec, dict(ctx, tm=tm_spec)


def load_case(path=CASE):
    return validate_case(json.loads(Path(path).read_text(encoding="utf-8")))


# ----------------------------------------------------------------------------- fixtures from the reviewed cases

def layered(ctx, order):
    """Reviewed layered preparation, paired support, inputs key and the thermal inputs of a rebuilt comparator."""
    base, thermal, key = tm.layered(ctx, order)
    layers = key[0]
    rebuild = dict(thicknesses=[layer["thickness_m"] for layer in layers], props=ctx["heat"]["thermal_layers"],
                   densities=[layer["density_kg_m3"] for layer in layers], boundaries=ctx["heat"]["boundaries"],
                   reference_temperature=None)
    return base, thermal, key, rebuild


def run(spec, ctx, base, thermal, key, *, steps, drive=None, kappa0=None, **kw):
    kw.setdefault("duration_s", spec["drive"]["duration_s"])
    kw.setdefault("fractions", ctx["heat"]["heat_fractions"])
    kw.setdefault("window", declared_window(spec))
    kw.setdefault("temperature_step_k", spec["representation"]["max_temperature_step_k"])
    return evolve(base, thermal, ctx["law"], weakening.initial_history(base, ctx["weak"]) if kappa0 is None else kappa0,
                  ctx["drive"] if drive is None else drive, steps=steps, policy=spec["policy"], inputs=key, **kw)


SCALARS = ("status", "reason", "accepted_steps", "elapsed_s", "clock_s", "stretch", "log_strain",
           "log_strain_quadrature", "log_path", "width_m", "thickness_m", "displacement_m", "velocity_start_m_s",
           "velocity_end_m_s", "column_force_start_n_m", "column_force_end_n_m", "mean_history_gain",
           "max_step_energy_relative", "max_temperature_step_k", "max_force_relative", "max_power_relative",
           "min_source_w_m2", "min_dissipation_w_m", "restress_mismatches", "stages", "evaluations", "iterations",
           "yield_switching_points")


def summary(out, base):
    """Reportable scalars only; per-point arrays stay in memory."""
    theta, gain = out["theta"], out["kappa"]-out["kappa0"]
    i = int(np.argmax(theta))
    layers = range(int(base.layer.max())+1)
    return dict({k: out[k] for k in SCALARS}, accounts=out["accounts"], conservation=out["conservation"],
                max_temperature_departure_k=float(theta[i]), material_depth_of_max_km=float(base.depth_m[i]/1e3),
                current_depth_of_max_km=float(base.depth_m[i]/out["stretch"]/1e3),
                min_temperature_departure_k=float(theta.min()), warming_by_layer_k=heat.layer_warming(theta, base),
                max_history_gain_by_layer=[float(gain[base.layer == li].max()) for li in layers],
                yielding_points_final=int(np.count_nonzero(out["final"]["plastic_rate"] > 0)))


def conserved(out):
    return all(value is None or value <= CONSERVATION_ROUNDOFF for value in out["conservation"].values())


def closed(out, pol):
    """Every retained account identity plus the new absolute heat-flow and conservation identities."""
    a = out["accounts"]
    return (out["status"] == "COMPLETE" and out["max_force_relative"] <= pol["force_relative"]
            and out["max_power_relative"] <= pol["power_relative"] and out["restress_mismatches"] == 0
            and max(a["motion_work_relative"], a["drive_displacement_relative"], a["drag_excluded_relative"])
            <= pol["work_relative"]
            and max(a["partition_relative"], a["column_energy_relative"], a["work_to_heat_relative"])
            <= pol["work_heat_relative"]
            and max(a["energy_relative"], out["max_step_energy_relative"]) <= pol["energy_relative"]
            and a["absolute_energy_relative"] <= pol["flow_relative"] and conserved(out))


def same_prefix(a, b):
    return (b is not None and a["accepted_steps"] == b["accepted_steps"] and a["elapsed_s"] == b["elapsed_s"]
            and a["stretch"] == b["stretch"] and a["displacement_m"] == b["displacement_m"]
            and np.array_equal(a["theta"], b["theta"]) and np.array_equal(a["kappa"], b["kappa"])
            and a["velocity_end_m_s"] == b["velocity_end_m_s"] and a["accounts"] == b["accounts"])


def relmax(a, b):
    return float(np.max(np.abs(np.asarray(a)-np.asarray(b))))/max(float(np.max(np.abs(np.asarray(b)))), TINY)


def scaling(thermal, inputs, stretch):
    """The retained support assembled at the current geometry versus the lam^2-scaled reference operator.

    Whole strip, w C(lam) = w0 C0 and w K(lam) = w0 lam^2 K0 including boundary conductances. Also reports the heat a
    reset to the stretched steady geotherm would inject, which the fixed enthalpy reference avoids.
    """
    now = heat.prepare_thermal(thermal.layer, thermal.depth_m/stretch, thermal.volume_m/stretch,
                               [h/stretch for h in inputs["thicknesses"]], inputs["props"], inputs["densities"],
                               inputs["boundaries"], reference_temperature=inputs["reference_temperature"])
    moved = np.asarray(now.steady_k)-np.asarray(thermal.steady_k)
    return dict(stretch=stretch,
                capacity_relative=float(np.max(np.abs(now.capacity*stretch-thermal.capacity)/thermal.capacity)),
                conductance_relative=float(np.max(np.abs(now.conductance-stretch*thermal.conductance)
                                                  / (stretch*thermal.conductance))),
                boundary_relative=max(ratio(a-stretch*b, stretch*b)
                                      for a, b in zip(now.boundary_conductance, thermal.boundary_conductance)),
                reset_heat_j_m2=math.fsum(thermal.capacity*moved), reset_max_k=float(np.abs(moved).max()))


# ----------------------------------------------------------------------------- controls

def kinematics_control(spec, ctx, deadline=None):
    """Exact affine thinning with conserved volume, mass and capacity; labels, history and temperature stay at their
    material points. Conduction is explicitly off for the nonuniform temperature and on for the uniform one."""
    pol, k = spec["policy"], spec["campaign"]["kinematics"]
    small = ctx["heat"]["representation"]["max_axial_strain"]
    base, thermal, key, _ = layered(ctx, k["order"])
    layers = key[0]
    thick = [layer["thickness_m"] for layer in layers]
    props = [dict(p, radiogenic_w_m3=0.) for p in ctx["heat"]["thermal_layers"]]
    reference = TEMPERATURE_CEILING_K[0]
    still = heat.prepare_thermal(base.layer, base.depth_m, base.weight, thick, props,
                                 [layer["density_kg_m3"] for layer in layers],
                                 dict(top=dict(type="insulated"), bottom=dict(type="insulated")),
                                 reference_temperature=reference, mechanical_fingerprint=base.fingerprint)
    theta0 = np.asarray(thermal.steady_k)-reference              # the reviewed nonuniform geotherm as a departure
    carried = run(spec, ctx, base, still, key, steps=k["steps"], fractions=(0., 0.), conduction=False, theta0=theta0,
                  deadline=deadline)
    lam = carried["stretch"]
    labels, current = np.asarray(base.layer), np.asarray(base.depth_m)/lam
    faces = np.concatenate([[0.], np.cumsum(thick)])/lam
    within = bool(np.all((faces[labels] < current) & (current < faces[labels+1])))
    unyielded = ~carried["yielded"]
    hb, ht, h = tm.homogeneous_setup(ctx, spec["campaign"]["homogeneous"]["order"])
    level = np.full(hb.size, float(k["uniform_departure_k"]))
    uniform = evolve(hb, ht, ctx["law"], np.full(hb.size, float(h["initial_history"])), ctx["drive"],
                     duration_s=spec["drive"]["duration_s"], steps=k["steps"], window=declared_window(spec),
                     temperature_step_k=spec["representation"]["max_temperature_step_k"], fractions=(0., 0.),
                     policy=pol, theta0=level, deadline=deadline)
    spread = float(np.ptp(uniform["theta"]))/float(np.abs(uniform["theta"]).max())
    drift = float(np.abs(uniform["theta"]-level).max())/float(level[0])
    a = carried["accounts"]
    checks = dict(
        complete=carried["status"] == "COMPLETE" and uniform["status"] == "COMPLETE",
        genuine_finite_stretch=min(carried["log_strain"], uniform["log_strain"]) > small,
        exact_affine_geometry=within and carried["final"]["width_m"] == carried["width_m"]
        and carried["final"]["thickness_m"] == carried["thickness_m"],
        conserved_volume_mass_capacity=conserved(carried) and conserved(uniform),
        labels_follow_material=within and np.array_equal(labels, np.asarray(still.layer)),
        history_follows_material=bool(np.array_equal(carried["kappa"][unyielded], carried["kappa0"][unyielded]))
        and bool(np.any(carried["kappa"] > carried["kappa0"])),
        nonuniform_temperature_carried_bitwise=np.array_equal(carried["theta"], theta0),
        no_heat_exchanged=all(a[name] == 0 for name in THERMAL_ACCOUNTS+("heat_j_m",)),
        uniform_temperature_preserved=spread <= pol["uniform_relative"] and drift <= pol["uniform_relative"],
        uniform_no_heat=uniform["accounts"]["heat_j_m"] == 0
        and uniform["accounts"]["departure_surface_loss_j_m"] == 0)
    return verdict(checks, conduction_off_layered=summary(carried, base), uniform_conducting=summary(uniform, hb),
                   uniform_relative_spread=spread, uniform_relative_drift=drift,
                   current_layer_faces_km=[float(z/1e3) for z in faces],
                   never_yielded_points=int(np.count_nonzero(unyielded)), finite_strain_threshold=small)


def recovery(spec, ctx, steps):
    """Zero deformation reproduces the retained conduction, preparation, stage and rest evolution bitwise."""
    base, thermal, key, _ = layered(ctx, spec["campaign"]["refusal"]["order"])
    law, drive, fractions = ctx["law"], ctx["drive"], tuple(ctx["heat"]["heat_fractions"])
    dt = spec["drive"]["duration_s"]/spec["campaign"]["reference_steps"]
    # The retained propagator's own eigensystem serves as the reusable modes, so the comparison isolates the clock.
    theirs = heat.prepare_propagator(thermal, dt)
    ours = clock_propagator(eigensystem(thermal, theirs), dt)
    factors = ("lam", "to_modal", "source_modal", "from_modal", "e", "p1", "p2", "p3")
    theta, source = np.sin(np.arange(thermal.size, dtype=float)), np.asarray(thermal.radiogenic)
    conducted = all(np.array_equal(a, b) for a, b in zip(heat.conduct(ours, theta, source, 2*source),
                                                         heat.conduct(theirs, theta, source, 2*source)))
    steady = np.array(thermal.steady_k)
    coeffs = coefficients(base)
    mine, reviewed = column_at(base, coeffs, 1., steady), heat.ArrheniusUpdate.of(base).at(steady)
    kappa0 = weakening.initial_history(base, ctx["weak"])
    a = stage(base, coeffs, law, 1., steady, kappa0, drive, fractions)
    b = tm.stage(reviewed, law, kappa0, drive, fractions)
    rest_drive = motion.Drive(0., drive.drag_pa_s, drive.width_m)
    bump = 2.*np.sin(math.pi*np.asarray(base.depth_m)/thermal.thickness_m)
    ours_rest = run(spec, ctx, base, thermal, key, steps=steps, duration_s=dt*steps, drive=rest_drive, theta0=bump,
                    modes=theirs)
    rep = ctx["tm"]["representation"]
    theirs_rest = tm.evolve(base, thermal, law, kappa0, rest_drive, duration_s=dt*steps, steps=steps,
                            strain_bound=rep["max_axial_strain"], temperature_step_k=rep["max_temperature_step_k"],
                            fractions=fractions, policy=ctx["tm"]["policy"], theta0=bump, propagator=theirs, inputs=key)
    checks = dict(
        conduction_factors_bitwise=all(np.array_equal(getattr(ours, f), getattr(theirs, f)) for f in factors),
        conduction_bitwise=conducted,
        preparation_bitwise=mine.thickness_m == reviewed.thickness_m
        and all(np.array_equal(getattr(mine, f), getattr(reviewed, f))
                for f in ("log_c", "volume_rt", "weight", "depth_m", "reference_pa", "temperature_k")),
        stage_bitwise=all(a[name] == b[name] for name in ("rate", "velocity_m_s", "force", "work", "heat",
                                                          "drive_power_w_m", "drag_power_w_m"))
        and all(np.array_equal(a[name], b[name]) for name in ("source", "kdot", "x")),
        rest_bitwise=ours_rest["status"] == theirs_rest["status"] == "COMPLETE" and ours_rest["stretch"] == 1.
        and np.array_equal(ours_rest["theta"], theirs_rest["theta"])
        and np.array_equal(ours_rest["kappa"], theirs_rest["kappa"]))
    return dict(checks=checks, data=dict(recovery_steps=steps, step_s=dt, rest_departure_end_k=float(np.abs(
        ours_rest["theta"]).max()), rest_accounts=ours_rest["accounts"]))


def clock_control(spec, ctx, deadline=None):
    """Transformed-coordinate conduction oracles along prescribed smooth affine histories, the lam^2 operator identity
    through the retained assembly, and bitwise zero-deformation recovery. Prescribed histories are exact controls
    only, not generated motion."""
    pol, c = spec["policy"], spec["campaign"]["clock"]
    window = declared_window(spec)
    em = ctx["heat"]["campaign"]["eigenmode"]
    h1, h2 = em["thickness_m"]
    k1, k2 = em["conductivity_w_m_k"]
    c1, c2 = (d*cp for d, cp in zip(em["density_kg_m3"], em["heat_capacity_j_kg_k"]))
    mu, mode = heat.two_layer_mode(h1, h2, k1, k2, c1, c2)
    slab_inputs = dict(
        thicknesses=[h1, h2], densities=list(em["density_kg_m3"]), reference_temperature=None,
        props=[dict(name=n, conductivity_w_m_k=kk, heat_capacity_j_kg_k=cc, radiogenic_w_m3=0.)
               for n, kk, cc in zip(("a", "b"), em["conductivity_w_m_k"], em["heat_capacity_j_kg_k"])],
        boundaries=dict(top=dict(type="temperature", value_k=em["boundary_k"]),
                        bottom=dict(type="temperature", value_k=em["boundary_k"])))
    lay, dep, wt = heat.geometry([h1, h2], c["order"])
    slab = heat.prepare_thermal(lay, dep, wt, slab_inputs["thicknesses"], slab_inputs["props"],
                                slab_inputs["densities"], slab_inputs["boundaries"])
    modes = eigensystem(slab)
    theta0 = em["amplitude_k"]*mode(dep)
    half = np.sqrt(np.asarray(slab.capacity))
    symmetric = slab.operator()/half[:, None]/half[None, :]
    histories = {}
    for final in c["final_stretch"]:
        duration = em["efolds"]/(mu*(1+final+final*final)/3)      # tau(T) = T (1 + lam_f + lam_f^2)/3 = efolds/mu
        slope = (final-1)/duration
        tau = duration*(1+slope*duration+(slope*duration)**2/3)    # exact clock of lam = 1 + slope t
        exact = (expm(-tau*symmetric)@(half*theta0))/half          # independent semi-discrete solution
        analytic = em["amplitude_k"]*mode(dep)*math.exp(-mu*tau)  # continuous two-layer mode on material coordinates
        runs = [conduct_history(slab, lambda t, s=slope: 1.+s*t, duration_s=duration, steps=n, window=window,
                                theta0=theta0, modes=modes, deadline=deadline) for n in c["steps"]]
        scale = float(np.abs(exact).max())
        errors = [float(np.abs(r["theta"]-exact).max())/scale for r in runs]
        histories[final] = dict(duration_s=duration, exact_clock_s=tau, scheme_clock_s=runs[-1]["clock_s"],
                                clock_relative=relative_change(runs[-1]["clock_s"], tau), steps=c["steps"],
                                relative_errors=errors, orders=orders(errors),
                                analytic_max_error_k=float(np.abs(runs[-1]["theta"]-analytic).max()),
                                max_step_energy_relative=max(r["max_step_energy_relative"] for r in runs),
                                complete=all(r["status"] == "COMPLETE" for r in runs))
    _, thermal, _, inputs = layered(ctx, spec["campaign"]["reference_order"])
    identity = ([dict(scaling(thermal, inputs, s), support="layered") for s in c["scaling_stretch"]]
                + [dict(scaling(slab, slab_inputs, s), support="two-layer slab") for s in c["scaling_stretch"]])
    worst = max(max(d["capacity_relative"], d["conductance_relative"], d["boundary_relative"]) for d in identity)
    back = recovery(spec, ctx, c["recovery_steps"])
    span = pol["oracle_order_range"]
    checks = dict(
        complete=all(v["complete"] for v in histories.values()),
        clock_second_order=all(in_range(v["orders"], span) for v in histories.values()),
        clock_finest=max(v["relative_errors"][-1] for v in histories.values()) <= pol["oracle_relative"],
        continuous_mode=max(v["analytic_max_error_k"] for v in histories.values()) <= pol["eigen_finest_k"],
        energy=max(v["max_step_energy_relative"] for v in histories.values()) <= pol["energy_relative"],
        lam2_operator_identity=worst <= pol["flow_relative"], **back["checks"])
    return verdict(checks, eigenvalue_per_s=mu, histories=histories, operator_identity=identity,
                   operator_identity_worst_relative=worst, reference_width_m=ctx["drive"].width_m,
                   recovery=back["data"])


def homogeneous_control(spec, ctx, deadline=None):
    """Insulated uniform force-driven layer at finite stretch versus an independent integrator and scalar roots."""
    pol, hc = spec["policy"], spec["campaign"]["homogeneous"]
    base, thermal, h = tm.homogeneous_setup(ctx, hc["order"])
    layer, law, drive = h["layer"], ctx["law"], ctx["drive"]
    duration, fractions = spec["drive"]["duration_s"], tuple(ctx["heat"]["heat_fractions"])
    oracle = stretch_oracle(layer, h["thermal"], law, drive, h["initial_history"], duration, fractions)
    kappa0 = np.full(base.size, float(h["initial_history"]))
    modes = eigensystem(thermal)
    runs = [evolve(base, thermal, law, kappa0, drive, duration_s=duration, steps=n, window=declared_window(spec),
                   temperature_step_k=spec["representation"]["max_temperature_step_k"], fractions=fractions,
                   policy=pol, modes=modes, deadline=deadline) for n in hc["steps"]]
    fine = runs[-1]
    t_err = [relative_change(float(r["theta"][0]), oracle["temperature_rise"]) for r in runs]
    k_err = [relative_change(float(r["kappa"][0])-h["initial_history"], oracle["history_gain"]) for r in runs]
    s_err = [relative_change(r["log_strain"], oracle["log_stretch"]) for r in runs]
    v_err = [relative_change(r["velocity_end_m_s"], oracle["velocity_end_m_s"]) for r in runs]
    end = stretch_balance(layer, law, drive, float(thermal.steady_k[0]+fine["theta"][0]), float(fine["kappa"][0]),
                          fine["stretch"])
    roots = dict(initial=relative_change(fine["velocity_start_m_s"], oracle["velocity_start_m_s"]),
                 final_state=relative_change(fine["velocity_end_m_s"], end["velocity_m_s"]))
    spread = max(max(float(np.ptp(r["theta"]))/float(np.abs(r["theta"]).max()),
                     float(np.ptp(r["kappa"]))/float(r["kappa"].max())) for r in runs)
    span = pol["oracle_order_range"]
    small = ctx["heat"]["representation"]["max_axial_strain"]
    boundary = ("radiogenic_j_m", "reference_outflow_j_m", "departure_surface_loss_j_m", "departure_basal_gain_j_m")
    checks = dict(
        complete=all(r["status"] == "COMPLETE" for r in runs), always_yielding=oracle["always_yielding"],
        genuine_finite_stretch=fine["log_strain"] > small, uniform=spread <= pol["uniform_relative"],
        temperature_order=in_range(orders(t_err), span), history_order=in_range(orders(k_err), span),
        finest=max(t_err[-1], k_err[-1], s_err[-1], v_err[-1]) <= pol["oracle_relative"],
        independent_roots=max(roots.values()) <= pol["root_parity_relative"],
        thins_and_accelerates=fine["thickness_m"] < base.thickness_m
        and fine["velocity_end_m_s"] > fine["velocity_start_m_s"] and float(fine["theta"][0]) > 0,
        insulated_no_boundary_heat=all(r["accounts"][name] == 0 for r in runs for name in boundary),
        accounts_close=all(closed(r, pol) for r in runs))
    return verdict(checks, oracle=oracle, steps=hc["steps"], temperature_errors=t_err, history_errors=k_err,
                   log_stretch_errors=s_err, velocity_errors=v_err, temperature_orders=orders(t_err),
                   history_orders=orders(k_err), log_stretch_orders=orders(s_err), velocity_orders=orders(v_err),
                   root_relative=roots, uniform_relative_spread=spread, finest=summary(fine, base),
                   drag_share=fine["accounts"]["drag_work_j_m"]/fine["accounts"]["drive_work_j_m"])


def physics(out, base, thermal, thicknesses):
    """Reported physical state of a layered run: current geometry, heat flow and resistance (no gate)."""
    lam = out["stretch"]
    g_top, t_top = thermal.boundary_conductance[0], thermal.boundary_temperature[0]
    first = float(thermal.steady_k[0]+out["theta0"][0])-t_top
    last = float(thermal.steady_k[0]+out["theta"][0])-t_top
    return dict(stretch=lam, width_km=out["width_m"]/1e3, thickness_km=out["thickness_m"]/1e3,
                layer_thickness_km=[h/lam/1e3 for h in thicknesses],
                surface_heat_flow_w_m2=dict(initial=g_top*first, final=lam*g_top*last),
                whole_strip_surface_outflow_w_m=dict(initial=out["width_m"]/lam*g_top*first,
                                                     final=out["width_m"]*lam*g_top*last),
                column_force_n_m=dict(start=out["column_force_start_n_m"], end=out["column_force_end_n_m"]),
                velocity_m_s=dict(start=out["velocity_start_m_s"], end=out["velocity_end_m_s"]),
                mean_history_gain=out["mean_history_gain"])


def connection_control(spec, ctx, deadline=None):
    """Force-driven finite stretch with heat and history: time/depth refinement of geometry, temperature, history,
    motion and work/energy; closed accounts; geometric feedback resolved beyond numerical refinement."""
    pol, camp = spec["policy"], spec["campaign"]
    ref_q, ref_n = camp["reference_order"], camp["reference_steps"]
    prepared = {q: layered(ctx, q) for q in camp["orders"]}
    modes = {q: eigensystem(prepared[q][1]) for q in camp["orders"]}

    def go(q, n, geometry=True):
        base, thermal, key, _ = prepared[q]
        return run(spec, ctx, base, thermal, key, steps=n, modes=modes[q], geometry_feedback=geometry,
                   deadline=deadline)
    by_steps = {n: go(ref_q, n) for n in camp["time_steps"]}
    by_order = {q: by_steps[ref_n] if q == ref_q else go(q, ref_n) for q in camp["orders"]}
    frozen = {q: go(q, ref_n, False) for q in camp["orders"]}
    ts, qs = camp["time_steps"], camp["orders"]
    base, thermal, key, _ = prepared[ref_q]
    on, off = by_order[ref_q], frozen[ref_q]

    def changes(runs, metric):
        return [metric(a, b) for a, b in zip(runs, runs[1:])]       # each pair compared with its finer run

    def account(name):
        return lambda a, b: relative_change(a["accounts"][name], b["accounts"][name])
    stretch = lambda a, b: relative_change(a["log_strain"], b["log_strain"])
    velocity = lambda a, b: relative_change(a["velocity_end_m_s"], b["velocity_end_m_s"])
    temperature = lambda a, b: float(np.abs(a["theta"]-b["theta"]).max())
    history = lambda a, b: float(np.abs(a["kappa"]-b["kappa"]).max())/max(float((b["kappa"]-b["kappa0"]).max()), TINY)
    work = lambda a, b: max(account("drive_work_j_m")(a, b), account("heat_j_m")(a, b))
    t_runs, d_runs = [by_steps[n] for n in ts], [by_order[q] for q in qs]
    in_time = dict(stretch=changes(t_runs, stretch), velocity=changes(t_runs, velocity),
                   temperature_k=changes(t_runs, temperature), history=changes(t_runs, history),
                   work_heat=changes(t_runs, work))
    in_depth = dict(stretch=changes(d_runs, stretch), velocity=changes(d_runs, velocity),
                    thermal_energy=changes(d_runs, account("thermal_change_j_m")), heat=changes(d_runs, account("heat_j_m")),
                    drive_work=changes(d_runs, account("drive_work_j_m")),
                    mean_history=changes(d_runs, lambda a, b: relative_change(a["mean_history_gain"], b["mean_history_gain"])))
    feedback = {q: (by_order[q]["velocity_end_m_s"]-frozen[q]["velocity_end_m_s"])/frozen[q]["velocity_end_m_s"]
                for q in qs}
    feedback_depth = relative_change(feedback[qs[-2]], feedback[qs[-1]])
    resolution = max(in_time["velocity"][-1], in_depth["velocity"][-1])
    geometric = t_runs+[by_order[q] for q in qs if q != ref_q]
    runs = geometric+list(frozen.values())
    small = ctx["heat"]["representation"]["max_axial_strain"]
    checks = dict(
        all_complete=all(r["status"] == "COMPLETE" for r in runs),
        genuine_finite_stretch=on["log_strain"] > small,
        time_stretch=in_time["stretch"][-1] <= pol["time_stretch_relative"],
        time_velocity=in_time["velocity"][-1] <= pol["time_velocity_relative"],
        time_temperature=in_time["temperature_k"][-1] <= pol["time_temperature_k"],
        time_history=in_time["history"][-1] <= pol["time_history_relative"],
        time_work_heat=in_time["work_heat"][-1] <= pol["time_work_relative"],
        depth_stretch=in_depth["stretch"][-1] <= pol["depth_stretch_relative"],
        depth_velocity=in_depth["velocity"][-1] <= pol["depth_velocity_relative"],
        depth_energy=max(in_depth["thermal_energy"][-1], in_depth["heat"][-1]) <= pol["depth_energy_relative"],
        depth_history=in_depth["mean_history"][-1] <= pol["depth_history_relative"],
        depth_work=in_depth["drive_work"][-1] <= pol["depth_work_relative"],
        thinning_speeds_extension=feedback[ref_q] > 0 and on["thickness_m"] < base.thickness_m,
        feedback_resolved=feedback[ref_q] >= pol["coupling_resolution_factor"]*resolution,
        feedback_depth=feedback_depth <= pol["feedback_depth_relative"],
        rate_follows_current_width=all(abs(r["log_strain_quadrature"]-r["log_strain"])
                                       <= pol["time_stretch_relative"]*abs(r["log_strain"]) for r in geometric),
        accounts_close=all(closed(r, pol) for r in runs),
        nonnegative_dissipation=min(min(r["min_source_w_m2"], r["min_dissipation_w_m"]) for r in runs) >= 0,
        reference_balanced=on["reference"]["balance_relative"] <= pol["flow_relative"],
        heats_the_column=float(on["theta"].max()) > 0 and on["accounts"]["heat_j_m"] > 0)
    thick = [layer["thickness_m"] for layer in key[0]]
    return verdict(
        checks, finite_strain=summary(on, base), geometry_feedback_off=summary(off, base),
        physics=dict(finite_strain=physics(on, base, thermal, thick), geometry_off=physics(off, base, thermal, thick)),
        velocity_feedback_by_order=feedback, feedback_depth_change=feedback_depth,
        refinement_resolution=resolution, time_steps=ts, time_changes=in_time,
        time_orders=dict(stretch=orders(in_time["stretch"]), temperature=orders(in_time["temperature_k"]),
                         history=orders(in_time["history"]), velocity=orders(in_time["velocity"])),
        yield_switching_points={n: by_steps[n]["yield_switching_points"] for n in ts}, orders=qs,
        depth_changes=in_depth, log_strain_quadrature_relative=max(
            abs(r["log_strain_quadrature"]-r["log_strain"])/abs(r["log_strain"]) for r in geometric),
        note="geometry feedback off is a comparator only: its mechanics stays at the reference geometry while its "
             "kinematics and conduction follow lam; orders are reported, not gated, because yield states switch")


def freshness(ctx, base, thermal, key, out, *, drive=None):
    """Independent route to a committed endpoint: the retained kernel preparation at the current layer thicknesses,
    the retained Arrhenius rebuild at the transported temperatures and a cold retained stage."""
    lam = out["stretch"]
    temperature = np.asarray(thermal.steady_k)+out["theta"]
    layers, order, closure, gravity = key
    again = weakening.prepare([dict(layer, thickness_m=layer["thickness_m"]/lam) for layer in layers], order,
                              closure=closure, gravity=gravity)
    again = heat.ArrheniusUpdate.of(again).at(temperature)
    ours = column_at(base, coefficients(base), lam, temperature)
    active = np.asarray(base.active)
    geometry = max(relmax(ours.depth_m, again.depth_m), relmax(ours.weight, again.weight),
                   relmax(ours.reference_pa, again.reference_pa),
                   relmax(np.asarray(ours.log_c)[active], np.asarray(again.log_c)[active]),
                   relative_change(ours.thickness_m, again.thickness_m))
    drive = ctx["drive"] if drive is None else drive
    cold = tm.stage(again, ctx["law"], out["kappa"], motion.Drive(drive.force_n_m, drive.drag_pa_s, drive.width_m*lam),
                    tuple(ctx["heat"]["heat_fractions"]))
    final = out["final"]
    parity = max(relative_change(final["velocity_m_s"], cold["velocity_m_s"]),
                 relative_change(final["force"], cold["force"]), relmax(final["source"], cold["source"]))
    return dict(geometry_relative=geometry, stage_relative=parity, stretch=lam)


def states_control(spec, ctx, deadline=None):
    """Rest, supported extension and compression with signed work, fresh current-state mechanics and unmodified
    caller inputs."""
    pol, s = spec["policy"], spec["campaign"]["states"]
    base, thermal, key, _ = layered(ctx, s["order"])
    modes = eigensystem(thermal)
    drive = ctx["drive"]
    common = dict(steps=s["steps"], modes=modes, deadline=deadline)
    rest_drive = motion.Drive(0., drive.drag_pa_s, drive.width_m)
    bump = s["rest_amplitude_k"]*np.sin(math.pi*np.asarray(base.depth_m)/thermal.thickness_m)
    kappa0 = weakening.initial_history(base, ctx["weak"])
    supplied_theta, supplied_kappa = bump.copy(), kappa0.copy()
    rest = run(spec, ctx, base, thermal, key, drive=rest_drive, theta0=supplied_theta, kappa0=supplied_kappa, **common)
    still = run(spec, ctx, base, thermal, key, drive=rest_drive, **common)
    ext = run(spec, ctx, base, thermal, key, **common)
    squeeze = motion.Drive(-drive.force_n_m, drive.drag_pa_s, drive.width_m)
    comp = run(spec, ctx, base, thermal, key, drive=squeeze, **common)
    fresh = [freshness(ctx, base, thermal, key, out, drive=forcing) for out, forcing in ((ext, drive), (comp, squeeze))]
    ra = rest["accounts"]
    immutable = (np.array_equal(supplied_theta, bump) and np.array_equal(supplied_kappa, kappa0)
                 and weakening.fingerprint(*key) == base.fingerprint
                 and not any(np.asarray(v).flags.writeable
                             for v in (base.weight, base.reference_pa, base.log_c, thermal.capacity, modes.lam)))
    checks = dict(
        rest_no_motion=rest["stretch"] == 1. and all(rest[name] == 0 for name in (
            "velocity_start_m_s", "velocity_end_m_s", "displacement_m", "log_strain")),
        rest_no_mechanical_heat_or_history=all(ra[name] == 0 for name in MECHANICAL)
        and np.array_equal(rest["kappa"], rest["kappa0"]),
        rest_departure_conducts=rest["status"] == "COMPLETE" and ra["thermal_change_j_m"] < 0
        and float(np.abs(rest["theta"]).max()) < float(np.abs(bump).max()),
        rest_energy=ra["energy_relative"] <= pol["energy_relative"] and ra["departure_surface_loss_j_m"] > 0
        and ra["radiogenic_j_m"] == ra["reference_outflow_j_m"],
        rest_without_departure_bitwise=not np.any(still["theta"]) and still["stretch"] == 1.
        and np.array_equal(still["kappa"], still["kappa0"]),
        extension=ext["stretch"] > 1 and ext["thickness_m"] < base.thickness_m and ext["velocity_end_m_s"] > 0
        and closed(ext, pol),
        compression=comp["stretch"] < 1 and comp["thickness_m"] > base.thickness_m and comp["velocity_end_m_s"] < 0
        and closed(comp, pol),
        signed_work=ext["accounts"]["drive_work_j_m"] > 0 and comp["accounts"]["drive_work_j_m"] > 0
        and ext["displacement_m"] > 0 > comp["displacement_m"],
        both_heat_the_column=float(ext["theta"].max()) > 0 and float(comp["theta"].max()) > 0,
        nonnegative_dissipation=all(min(r["min_source_w_m2"], r["min_dissipation_w_m"]) >= 0 for r in (rest, ext, comp)),
        fresh_geometry_pressure_coefficients=max(f["geometry_relative"] for f in fresh) <= pol["kernel_parity_relative"],
        fresh_stage_and_heat_source=max(f["stage_relative"] for f in fresh) <= pol["root_parity_relative"],
        immutable_inputs=immutable)
    return verdict(checks, rest=dict(accounts=ra, max_departure_start_k=float(np.abs(bump).max()),
                                     max_departure_end_k=float(np.abs(rest["theta"]).max())),
                   extension=summary(ext, base), compression=summary(comp, base), freshness=fresh,
                   compression_to_extension_speed=abs(comp["velocity_end_m_s"])/ext["velocity_end_m_s"])


CASE_MUTATIONS = (
    ("eulerian_geometry", ("representation", "geometry"), "Eulerian column with advective face fluxes"),
    ("asthenospheric_inflow", ("representation", "inflow_velocity_m_s"), 1e-10),
    ("accumulated_strain_as_geometry", ("representation", "finite_strain"),
     "accumulated engineering strain used as geometry"),
    ("prescribed_main_motion", ("representation", "control"), "prescribed smooth affine stretch history"),
    ("stationary_thermal_reference", ("representation", "thermal"),
     "fixed-geometry conduction with the steady geotherm reset at every stage"),
    ("drag_heats_column", ("representation", "heating"), "column and external drag dissipation deposited in the column"),
    ("latent_heat", ("representation", "latent_heat_j_kg"), 3e5),
    ("frozen_propagator", ("representation", "time_integration"), "one propagator reused unchanged for every step"),
    ("widened_stretch", ("representation", "stretch_window"), [.5, 1.5]),
    ("window_not_guaranteed", ("representation", "stretch_window"), [.7, 1.3]),
    ("widened_temperature", ("representation", "temperature_window_k"), [200., 1700.]),
    ("temperature_guard", ("representation", "max_temperature_step_k"), 50.),
    ("duration_beyond_bound", ("drive", "duration_s"), 1.1e14),
    ("bound_mismatch", ("drive", "drag_only_stretch_bound"), .3),
    ("tuned_force", ("drive", "force_n_m"), 3e13),
    ("other_input", ("inputs", "thermomechanical_case"), "cases/i01_column_heat_v1.json"),
    ("step_ceiling", ("policy", "max_steps"), 512),
    ("relaxed_force_residual", ("policy", "force_relative"), 1e-8),
    ("relaxed_energy", ("policy", "energy_relative"), 1e-6),
    ("relaxed_stretch_gate", ("policy", "time_stretch_relative"), 1e-3),
    ("relaxed_resolution", ("policy", "coupling_resolution_factor"), 2.),
    ("oversized_time_series", ("campaign", "time_steps"), [128, 256, 512]),
    ("missing_policy_key", ("policy", "work_heat_relative"), KeyError))


def nothing_lost(out, pol):
    """A refused run keeps whole accepted steps only, with conserved material and closed heat accounts."""
    return (out["elapsed_s"] == out["accepted_steps"]*out["time_step_s"] and conserved(out)
            and out["accounts"]["energy_relative"] <= pol["energy_relative"])


def refusal_control(spec, ctx, deadline=None):
    """Unadmitted cases and direct inputs refuse; window, step and deadline refusals are atomic, including a refused
    final endpoint, and lose or duplicate no material, heat or accepted time."""
    pol, rep, r = spec["policy"], spec["representation"], spec["campaign"]["refusal"]
    refused = {}

    def expect(name, fn):
        try:
            fn()
        except ValueError:
            refused[name] = True
        else:
            refused[name] = False

    for name, path, value in CASE_MUTATIONS:
        expect(name, lambda bad=mutated(spec, path, value): validate_case(bad))
    base, thermal, key, rebuild = layered(ctx, r["order"])
    modes = eigensystem(thermal)
    law, drive = ctx["law"], ctx["drive"]
    kappa0 = weakening.initial_history(base, ctx["weak"])
    window = declared_window(spec)
    duration = spec["drive"]["duration_s"]
    common = dict(duration_s=duration, window=window, temperature_step_k=rep["max_temperature_step_k"],
                  fractions=ctx["heat"]["heat_fractions"], policy=pol)

    def call(**kw):
        return evolve(kw.pop("base", base), kw.pop("thermal", thermal), law, kw.pop("kappa0", kappa0),
                      kw.pop("drive", drive), **dict(common, **kw))
    for n in (0, 257, 2.):
        expect("steps_%r" % (n,), lambda n=n: call(steps=n))
    thick = [layer["thickness_m"] for layer in key[0]]
    dens = [layer["density_kg_m3"] for layer in key[0]]
    other, _ = weakening.base_prepare(ctx["weak"], order=r["order"], offset_k=1.)
    foreign = heat.prepare_thermal(*heat.geometry(thick[::-1], r["order"]), thick[::-1], ctx["heat"]["thermal_layers"],
                                   dens, ctx["heat"]["boundaries"], mechanical_fingerprint=base.fingerprint)
    stale = copy.deepcopy(key[0])
    stale[0]["temperature_k"] = [t+1e-9 for t in stale[0]["temperature_k"]]
    wet_layers = copy.deepcopy(key[0])
    wet_layers[0]["pore_pressure_pa"] = [0., 1e6]
    wet = weakening.prepare(wet_layers, r["order"], closure=key[2], gravity=key[3])
    wet_thermal = heat.prepare_thermal(wet.layer, wet.depth_m, wet.weight, thick, ctx["heat"]["thermal_layers"], dens,
                                       ctx["heat"]["boundaries"], mechanical_fingerprint=wet.fingerprint)
    steady = np.array(thermal.steady_k)
    wrong = dict(rebuild, props=[dict(p, conductivity_w_m_k=3.) for p in rebuild["props"]])
    for name, kw in (
            ("window_wide_stretch", dict(window=dict(window, stretch=[.5, 1.4]))),
            ("window_wide_temperature", dict(window=dict(window, temperature_k=[273., 1700.]))),
            ("window_without_reference", dict(window=dict(window, stretch=[1.1, 1.4]))),
            ("window_malformed", dict(window=dict(stretch=[.6, 1.4]))),
            ("guard_above_ceiling", dict(temperature_step_k=6.)),
            ("untyped_drive", dict(drive=(drive.force_n_m, drive.drag_pa_s, drive.width_m))),
            ("amplified_heat", dict(fractions=(1.5, 1.))), ("theta_shape", dict(theta0=np.zeros(3))),
            ("nonpositive_temperature", dict(theta0=-steady)),
            ("initial_outside_window", dict(theta0=np.full(base.size, 1000.))),
            ("negative_history", dict(kappa0=-kappa0)), ("warm_start_flag", dict(warm_start=1)),
            ("geometry_flag", dict(geometry_feedback=1)), ("conduction_flag", dict(conduction=1)),
            ("thermal_for_other_column", dict(base=other)),
            ("temperature_prepared_base", dict(base=heat.ArrheniusUpdate.of(base).at(steady))),
            ("stretched_preparation_as_base", dict(base=column_at(base, coefficients(base), 1.1, steady))),
            ("stale_preparation", dict(inputs=(stale, *key[1:]))),
            ("support_same_size_foreign", dict(thermal=foreign)),
            ("support_replaced_copy", dict(thermal=dataclasses.replace(thermal, depth_m=weakening.frozen(
                thermal.depth_m+1.)))),
            ("modes_of_other_support", dict(modes=eigensystem(foreign))),
            ("modes_without_conduction", dict(conduction=False, modes=modes)),
            ("conduction_off_with_fixed_temperatures", dict(conduction=False)),
            ("rebuild_with_modes", dict(rebuild=rebuild, modes=modes)),
            ("rebuild_not_reproducing_support", dict(rebuild=wrong)),
            ("transported_pore_pressure", dict(base=wet, thermal=wet_thermal, kappa0=np.zeros(wet.size)))):
        expect(name, lambda kw=kw: call(steps=2, **kw))
    expect("history_not_from_reference", lambda: conduct_history(thermal, lambda t: 1.1, duration_s=duration, steps=2,
                                                                  window=window, modes=modes))
    expect("history_leaves_window", lambda: conduct_history(thermal, lambda t: 1.+t/duration, duration_s=duration,
                                                             steps=2, window=window, modes=modes))
    tiny, tiny_thermal = tm.compressive_column(ctx, r["compressive_volume_m3_mol"])
    squeeze = motion.Drive(-drive.force_n_m, drive.drag_pa_s, drive.width_m)
    expect("compressive_nonmonotone_creep", lambda: call(steps=2, base=tiny, thermal=tiny_thermal,
                                                         kappa0=np.zeros(tiny.size), drive=squeeze))
    # Atomic refusals: every returned prefix equals an independent run of exactly its accepted steps.
    n = r["steps"]
    dt = duration/n
    w0 = drive.width_m

    def prefix(k, **kw):
        return call(steps=k, duration_s=dt*k, modes=modes, **kw)
    full, last_but_one, third = prefix(n), prefix(n-1), prefix(3)
    lam_last = last_but_one["stretch"]+dt*last_but_one["velocity_end_m_s"]/w0     # the n-th Euler stretch, bitwise
    lam_fourth = third["stretch"]+dt*third["velocity_end_m_s"]/w0
    endpoint_fixture = last_but_one["stretch"] < lam_last < full["stretch"]
    low = window["stretch"][0]
    at_endpoint = prefix(n, window=dict(window, stretch=[low, (lam_last+full["stretch"])/2]))
    at_predictor = prefix(n, window=dict(window, stretch=[low, (third["stretch"]+lam_fourth)/2]))
    hot = prefix(2, temperature_step_k=r["temperature_guard_k"])
    hb, ht, h = tm.homogeneous_setup(ctx, r["order"])
    hk0 = np.full(hb.size, float(h["initial_history"]))
    hn = r["window_steps"]
    hdt = duration/hn
    capped_window = dict(window, temperature_k=[window["temperature_k"][0],
                                                float(ht.steady_k[0])+r["temperature_margin_k"]])

    def warm_prefix(k):
        return evolve(hb, ht, law, hk0, drive, steps=k, **dict(common, duration_s=hdt*k, window=capped_window))
    capped = warm_prefix(hn)
    kt = capped["accepted_steps"]
    capped_prefix = warm_prefix(kt) if kt else None
    probe = CountdownDeadline(10**9)
    prefix(n, deadline=probe)
    used = 10**9-probe.remaining
    cut = prefix(n, deadline=CountdownDeadline(used//2))
    kd = cut["accepted_steps"]
    cut_prefix = prefix(kd) if kd else None
    final_cut = prefix(n, deadline=CountdownDeadline(used-1))       # expires inside the final endpoint's re-solve
    try:
        prefix(2, deadline=0.)
        expired_start_raises = False
    except RuntimeError:
        expired_start_raises = True
    checks = {("refuse_"+name): value for name, value in refused.items()}
    checks.update(
        stretch_predictor_atomic=at_predictor["status"] == "REFUSED_STRETCH_WINDOW" and same_prefix(at_predictor, third),
        stretch_final_endpoint_atomic=endpoint_fixture and at_endpoint["status"] == "REFUSED_STRETCH_WINDOW"
        and same_prefix(at_endpoint, last_but_one),
        temperature_step_atomic=hot["status"] == "REFUSED_TEMPERATURE_STEP" and hot["accepted_steps"] == 0
        and not np.any(hot["theta"]) and np.array_equal(hot["kappa"], kappa0) and hot["stretch"] == 1.
        and all(value == 0 for value in hot["accounts"].values()),
        temperature_window_atomic=capped["status"] == "REFUSED_TEMPERATURE_WINDOW" and 0 < kt < hn
        and same_prefix(capped, capped_prefix),
        deadline_atomic=cut["status"] == "REFUSED_DEADLINE" and 0 < kd < n and same_prefix(cut, cut_prefix),
        deadline_final_endpoint_atomic=final_cut["status"] == "REFUSED_DEADLINE"
        and same_prefix(final_cut, last_but_one),
        expired_budget_before_first_balance_raises=expired_start_raises,
        nothing_lost_or_duplicated=all(nothing_lost(o, pol) for o in (at_predictor, at_endpoint, hot, capped, cut,
                                                                      final_cut)))
    return verdict(checks, refused_cases=sorted(refused), stretch_window_fixture=dict(
                       last_but_one=last_but_one["stretch"], euler_last=lam_last, final=full["stretch"],
                       third=third["stretch"], euler_fourth=lam_fourth),
                   accepted_before_refusal=dict(stretch_predictor=at_predictor["accepted_steps"],
                                                stretch_endpoint=at_endpoint["accepted_steps"],
                                                temperature_window=kt, deadline=kd,
                                                deadline_final_endpoint=final_cut["accepted_steps"]),
                   deadline_checks_probe=used)


def reuse_control(spec, ctx, deadline=None):
    """One matched comparison: warm guesses and one reference eigensystem along the clock versus cold roots and the
    current-geometry conduction operator re-assembled and eigendecomposed at every accepted step."""
    pol, camp = spec["policy"], spec["campaign"]
    base, thermal, key, rebuild = layered(ctx, camp["reference_order"])
    n = camp["reference_steps"]
    begin = time.perf_counter()
    warm = run(spec, ctx, base, thermal, key, steps=n, modes=eigensystem(thermal), deadline=deadline)
    warm_seconds = time.perf_counter()-begin
    begin = time.perf_counter()
    cold = run(spec, ctx, base, thermal, key, steps=n, warm_start=False, rebuild=rebuild, deadline=deadline)
    cold_seconds = time.perf_counter()-begin
    parity = max(relative_change(warm["velocity_end_m_s"], cold["velocity_end_m_s"]),
                 relative_change(warm["log_strain"], cold["log_strain"]),
                 float(np.abs(warm["theta"]-cold["theta"]).max())/max(float(np.abs(cold["theta"]).max()), TINY),
                 float(np.abs(warm["kappa"]-cold["kappa"]).max()),
                 relative_change(warm["accounts"]["heat_j_m"], cold["accounts"]["heat_j_m"]),
                 relative_change(warm["accounts"]["drive_work_j_m"], cold["accounts"]["drive_work_j_m"]),
                 relative_change(warm["accounts"]["thermal_change_j_m"], cold["accounts"]["thermal_change_j_m"]))
    gates = all(closed(r, pol) for r in (warm, cold))
    return verdict(dict(parity=parity <= pol["parity_relative"], same_gates=gates),
                   warm_prepared_seconds=warm_seconds, cold_rebuilt_seconds=cold_seconds,
                   saved_seconds=cold_seconds-warm_seconds, saved_percent=100*(cold_seconds-warm_seconds)/cold_seconds,
                   parity_relative=parity, warm_evaluations=warm["evaluations"], cold_evaluations=cold["evaluations"],
                   warm_iterations=warm["iterations"], cold_iterations=cold["iterations"],
                   scope="one matched reference evolution after the other controls; warm root/stress guesses and one "
                         "reference eigensystem with per-step clock factors versus cold roots and the retained "
                         "support re-assembled at the step's effective geometry and eigendecomposed every accepted "
                         "step; creep terms rebuilt at every stage in both; not a generator or world forecast")


CONTROLS = (("kinematics", kinematics_control), ("clock", clock_control), ("homogeneous", homogeneous_control),
            ("connection", connection_control), ("states", states_control), ("refusal", refusal_control),
            ("reuse", reuse_control))


# ----------------------------------------------------------------------------- evidence

def digest(name):
    return hashlib.sha256((ROOT/name).read_bytes()).hexdigest()


def bindings():
    return {name: digest(name) for name in NEW_FILES+RETAINED+tuple(ACCEPTED_RECEIPTS)}


def evidence_match(current):
    """Accepted receipts are their declared bytes; every source they recorded (including the retained tools and
    cases imported here, their documents and tests, and the earlier receipts they bound) still has those bytes; the
    imported modules resolve to their bound paths."""
    receipts = {name: current[name] == value for name, value in ACCEPTED_RECEIPTS.items()}
    recorded = {}
    for name in ACCEPTED_RECEIPTS:
        for source, value in json.loads((ROOT/name).read_text(encoding="utf-8"))["source_sha256"].items():
            recorded.setdefault(source, set()).add(value)
    sources = {}
    for source, values in sorted(recorded.items()):
        present = (ROOT/source).is_file()
        now = current[source] if source in current else (digest(source) if present else None)
        sources[source] = present and len(values) == 1 and now in values
    retained = {name: sources.get(name, False) for name in RETAINED}
    imported = {name: Path(module.__file__).resolve() == (ROOT/name).resolve() for name, module in IMPORTED.items()}
    return dict(receipts=receipts, recorded_sources=sources, retained=retained, imported=imported)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream, threadpool_limits(limits=1, user_api="blas"):
        result = dict(schema="atlas.i01-finite-strain-evidence.v1", status="INCOMPLETE", scientific_acceptance=False,
                      runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                                   threadpoolctl=threadpoolctl.__version__, system=platform.system(),
                                   machine=platform.machine(), blas_threads=1),
                      controls={})
        start = time.perf_counter()
        try:
            before = bindings()
            match = evidence_match(before)
            result.update(source_sha256=before, evidence_match=match)
            if not all(all(group.values()) for group in match.values()):
                raise ValueError("bound sources or accepted receipts differ from the reviewed evidence; no control ran")
            spec, ctx = load_case()
            result["case"] = spec
            deadline = start+spec["policy"]["maximum_seconds"]          # cooperative budget counted after imports
            for name, control in CONTROLS:
                begin = time.perf_counter()
                try:
                    data = control(spec, ctx, deadline)
                    result["controls"][name] = dict(status="PASS" if data["passed"] else "FAIL",
                                                    seconds=time.perf_counter()-begin, **data)
                except (ValueError, RuntimeError) as exc:
                    result["controls"][name] = dict(status="FAIL", seconds=time.perf_counter()-begin,
                                                    error_type=type(exc).__name__,
                                                    error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
            result["source_unchanged"] = before == bindings()
            passed = (result["source_unchanged"] and len(result["controls"]) == len(CONTROLS)
                      and all(c["status"] == "PASS" for c in result["controls"].values()))
            result["status"] = PASS if passed else "FAIL"
        except Exception as exc:
            # Deliberately do not publish arbitrary exception paths or tracebacks.
            result.update(status="FAIL", error_type=type(exc).__name__)
            if isinstance(exc, (ValueError, RuntimeError)):
                result["error"] = str(exc).replace(str(ROOT), "TECTONICS_ROOT")
        result["elapsed_seconds_after_imports"] = time.perf_counter()-start
        try:
            text = json.dumps(result, indent=2, allow_nan=False)
        except (TypeError, ValueError) as exc:          # never leave a partial record behind
            result = dict(schema=result["schema"], status="FAIL", scientific_acceptance=False,
                          runtime=result["runtime"], error_type=type(exc).__name__,
                          error="evidence record not serialisable: "+str(exc)[:200], controls={},
                          elapsed_seconds_after_imports=result["elapsed_seconds_after_imports"])
            text = json.dumps(result, indent=2, allow_nan=False)
        stream.write(text+"\n")
    print(json.dumps({key: result.get(key) for key in ("status", "elapsed_seconds_after_imports", "error")}
                     | {"controls": {k: v["status"] for k, v in result["controls"].items()}}))
    return 0 if result["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
