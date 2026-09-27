"""I01 force-driven motion with thermal and weakening feedback in a layered column, WORKING NON-CANON.

A constant external driving force is balanced at every integration stage by disjoint generalised drag
and the layered column resistance at that stage's own temperature and plastic history. Column creep and
plastic dissipation from the same solved state are conducted on the mechanical Gauss control volumes;
external drag dissipation never heats the column. Fixed geometry and width, small strain; no advection,
finite strain, melting, rupture, world assembly or native-code integration.
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
from scipy.optimize import brentq
import threadpoolctl
from threadpoolctl import threadpool_limits

import check_i01_column_heat as heat
import check_i01_motion_coupling as motion

weakening = heat.weakening
column = weakening.column
if motion.w is not weakening:
    raise ImportError("column-heat and motion adapters must share the reviewed weakening module")

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT/"cases/i01_thermomechanical_motion_v1.json"
SCHEMA = "atlas.i01-thermomechanical-motion-case.v1"
PASS = "PASS_BOUNDED_THERMOMECHANICAL_MOTION_ONLY"
TINY = weakening.TINY
number, positive = weakening.number, weakening.positive
relative_change, verdict, check_deadline = weakening.relative_change, weakening.verdict, weakening.check_deadline
NEW_FILES = ("tools/check_i01_thermomechanical_motion.py", "cases/i01_thermomechanical_motion_v1.json",
             "docs/I01_THERMOMECHANICAL_MOTION.md", "tests/test_i01_thermomechanical_motion.py")
RETAINED = ("tools/check_i01_column_heat.py", "tools/check_i01_motion_coupling.py", "tools/check_i01_weakening.py",
            "tools/check_i01_column.py", "cases/i01_column_heat_v1.json", "cases/i01_motion_coupling_v1.json",
            "cases/i01_weakening_v1.json")
ACCEPTED_RECEIPTS = {
    "evidence/i01-column-heat-r2.json": "325f55b13ba18186e0262e3990ad4aa2f2d1236e5d83b4e864e3d9cb8e13dfd4",
    "evidence/i01-motion-coupling-r1.json": "a8afc8c4bfdc143160dc5c45941d2d09e3ebee8bd7ea3c6878b9d052427d526c"}
IMPORTED = {"tools/check_i01_column_heat.py": heat, "tools/check_i01_motion_coupling.py": motion,
            "tools/check_i01_weakening.py": weakening, "tools/check_i01_column.py": column}
INPUTS = {"column_heat_case": "cases/i01_column_heat_v1.json", "motion_case": "cases/i01_motion_coupling_v1.json"}
REPRESENTATION = {
    "geometry": "fixed laterally uniform column and belt width; material depth coordinates; small strain; no advection",
    "control": "constant external driving force balanced by disjoint generalised drag and the layered column "
               "resistance at every stage",
    "thermal": "reviewed column-heat conduction on the mechanical Gauss control volumes with constant declared layer "
               "properties; initial state is its discrete steady reference",
    "heating": "column creep plus plastic dissipation deposited once per control volume; external drag dissipation "
               "is not column heat",
    "time_integration": "retained ETD2 conduction with Heun history, strain, displacement and work; accepted endpoint "
                        "re-solved before commit",
}
REPRESENTATION_LIMITS = {"max_axial_strain", "max_temperature_step_k"}
MOTION_POWER_RELATIVE = 2e-10      # hard-coded stage-power and integrated-work gates of check_i01_motion_coupling
NEW_GATES = {"maximum_seconds": 120., "time_history_relative": 1e-4, "time_work_relative": 1e-4,
             "depth_history_relative": .01, "depth_work_relative": .003}
CAMPAIGN_KEYS = {"reference_order", "reference_steps", "time_steps", "orders", "homogeneous", "states", "refusal"}
REFUSAL_KEYS = {"order", "strain_steps", "strain_step_duration_s", "strain_bound_factor", "temperature_steps",
                "temperature_guard_k", "deadline_steps", "compressive_volume_m3_mol"}
# Heun-integrated accounts: (account, stage value). Motion terms are W/m of strike (J/m integrated);
# column terms are W/m^2 of column (J/m^2); one column account times width is its motion account.
STAGE_ACCOUNTS = (("drive_work_j_m", "drive_power_w_m"), ("drag_work_j_m", "drag_power_w_m"),
                  ("column_creep_work_j_m", "creep_power_w_m"), ("column_plastic_work_j_m", "plastic_power_w_m"),
                  ("column_work_j_m2", "work"), ("creep_work_j_m2", "creep_work"),
                  ("plastic_work_j_m2", "plastic_work"), ("heat_j_m2", "heat"), ("stored_j_m2", "stored"))
THERMAL_ACCOUNTS = ("surface_loss_j_m2", "base_gain_j_m2", "thermal_change_j_m2")
REST = dict(rate=0., velocity_m_s=0., x=None, force=0., drive_power_w_m=0., drag_power_w_m=0., creep_power_w_m=0.,
            plastic_power_w_m=0., work=0., creep_work=0., plastic_work=0., heat=0., stored=0., force_relative=0.,
            power_relative=0., same_stress=True, evaluations=0, iterations=0)


class CountdownDeadline(float):
    """Deterministic stand-in for the cooperative deadline, used only by refusal controls and tests.

    ``time.perf_counter() > deadline`` consults this float subclass first (reflected comparison), so the
    budget expires after a fixed number of retained ``check_deadline`` calls, independent of machine speed.
    """

    def __new__(cls, checks):
        self = super().__new__(cls, math.inf)
        self.remaining = int(checks)
        return self

    def __lt__(self, now):
        self.remaining -= 1
        return self.remaining < 0


def expired(deadline):
    return deadline is not None and time.perf_counter() > deadline


def ratio(residual, scale):
    """|residual|/|scale|. A zero account (rest) reports its absolute residual, which must then be zero."""
    return abs(residual)/abs(scale) if scale else abs(residual)


def departure(theta0, size):
    theta = np.asarray(theta0)
    if theta.dtype.kind not in "fiu" or theta.shape != (size,) or not np.all(np.isfinite(theta)):
        raise ValueError("initial temperature departure must be finite and real, one value per material point")
    return theta.astype(float)


# ----------------------------------------------------------------------------- one force-balanced stage

def stage(prep, law, kappa, drive, fractions, *, warm=None, deadline=None):
    """Solve F = D v + F_column(v/width, kappa) at this preparation, then take heat from that same state.

    The retained motion.solve finds the rate. The retained heat.mechanics re-evaluates the same
    preparation, history and rate, starting from the root's log-stresses, and returns the pointwise
    source in W/m^2 per control volume (quadrature width already included). Zero drive is exact rest:
    no mechanics call, zero source and zero history rate. ``warm`` is an initial guess only.
    """
    root = motion.solve(prep, law, kappa, drive, warm=warm, deadline=deadline)
    if root["rate"] == 0:
        zero = weakening.frozen(np.zeros(prep.size))
        return dict(REST, source=zero, kdot=zero, plastic_rate=zero)
    mech = heat.mechanics(prep, law, kappa, root["rate"], root["x"], fractions)
    width = drive.width_m
    creep_power, plastic_power = width*mech["creep_work"], width*mech["plastic_work"]
    drive_power, drag_power = root["drive_power_w_m"], root["drag_power_w_m"]
    return dict(rate=root["rate"], velocity_m_s=root["velocity_m_s"], x=root["x"], force=mech["force"],
                drive_power_w_m=drive_power, drag_power_w_m=drag_power, creep_power_w_m=creep_power,
                plastic_power_w_m=plastic_power, work=mech["work"], creep_work=mech["creep_work"],
                plastic_work=mech["plastic_work"], heat=mech["heat"], stored=mech["stored"], source=mech["source"],
                kdot=mech["kdot"], plastic_rate=mech["plastic_rate"], force_relative=root["force_relative"],
                power_relative=abs(drive_power-drag_power-creep_power-plastic_power)/drive_power,
                same_stress=bool(np.array_equal(mech["stress"], root["stress"])),
                evaluations=root["evaluations"], iterations=root["iterations"]+mech["iterations"])


def note(stats, s):
    """Scalar diagnostics of one committed stage; no per-stage history is retained."""
    stats["max_force_relative"] = max(stats["max_force_relative"], s["force_relative"])
    stats["max_power_relative"] = max(stats["max_power_relative"], s["power_relative"])
    stats["min_source_w_m2"] = min(stats["min_source_w_m2"], float(np.min(s["source"])))
    stats["min_dissipation_w_m"] = min(stats["min_dissipation_w_m"], s["drag_power_w_m"], s["creep_power_w_m"],
                                       s["plastic_power_w_m"])
    stats["restress_mismatches"] += int(not s["same_stress"])
    stats["evaluations"] += s["evaluations"]
    stats["iterations"] += s["iterations"]
    stats["stages"] += 1


def reference_throughput(thermal, elapsed):
    """Balanced steady-reference fluxes (radiogenic throughput), reported apart from the departure accounts."""
    top, bottom = thermal.boundary_temperature
    g_top, g_bot = thermal.boundary_conductance
    out = g_top*(float(thermal.steady_k[0])-top) if top is not None else 0.
    into = g_bot*(bottom-float(thermal.steady_k[-1])) if bottom is not None else 0.
    radiogenic = math.fsum(thermal.radiogenic)
    return dict(surface_outflow_w_m2=out, basal_inflow_w_m2=into, radiogenic_w_m2=radiogenic,
                balance_relative=ratio(out-into-radiogenic, abs(out)+abs(into)+abs(radiogenic)), elapsed_s=elapsed,
                surface_outflow_j_m2=out*elapsed, basal_inflow_j_m2=into*elapsed, radiogenic_j_m2=radiogenic*elapsed)


# ----------------------------------------------------------------------------- coupled evolution

def evolve(base, thermal, law, kappa0, drive, *, duration_s, steps, strain_bound, temperature_step_k, fractions,
           policy, feedback=True, theta0=None, warm_start=True, propagator=None, provider=None, inputs=None,
           deadline=None):
    """Constant-drive evolution of temperature departure theta, raw history kappa, strain and displacement.

    Every stage (initial, predictor, accepted endpoint) rebuilds the temperature-dependent creep terms at
    its own temperature, balances the drive and deposits heat from that same preparation, history and rate.
    Conduction is the retained ETD2 step with the source linear between the stages; history, strain,
    displacement and work use the same Heun stages. The endpoint is re-solved before anything is booked.
    Strain, temperature-step and deadline refusals return the accepted prefix unchanged. With feedback off,
    every stage uses the preparation at the initial temperature while heat is still conducted.
    """
    if type(base) is not weakening.PreparedColumn or type(thermal) is not heat.ThermalColumn:
        raise ValueError("reviewed mechanical preparation and thermal support required")
    if type(law) is not weakening.WeakeningLaw or type(drive) is not motion.Drive:
        raise ValueError("typed weakening law and external drive required")
    if inputs is not None and weakening.fingerprint(*inputs) != base.fingerprint:
        raise ValueError("prepared coefficients are stale for these inputs; prepare again")
    if thermal.mechanical_fingerprint != base.fingerprint:
        raise ValueError("thermal support was prepared for a different mechanical column")
    if not heat.same_support(thermal, base):            # a matching label is not evidence of equal support
        raise ValueError("thermal layers, depths or widths differ from the mechanical quadrature")
    heat.policy_limits(policy)
    if type(steps) is not int or not 1 <= steps <= policy["max_steps"]:
        raise ValueError("accepted steps must be an integer in 1..256")
    if type(feedback) is not bool or type(warm_start) is not bool:
        raise ValueError("feedback and warm_start must be boolean")
    bound = weakening.strain_limit(strain_bound)
    limit = positive(temperature_step_k, "temperature step guard")
    if limit > 5.:
        raise ValueError("temperature step guard above the declared 5 K ceiling")
    duration = positive(duration_s, "duration")
    fractions = heat.heat_fractions(fractions)
    law.certify(base)
    kappa0 = weakening.history_array(base, kappa0).copy()
    theta = np.zeros(base.size) if theta0 is None else departure(theta0, base.size)
    theta_start = theta.copy()
    dt = duration/steps
    prop = heat.prepare_propagator(thermal, dt) if propagator is None else propagator
    if type(prop) is not heat.Propagator or prop.fingerprint != thermal.fingerprint or prop.dt != dt:
        raise ValueError("conduction propagator prepared for different support or step")
    arrhenius = heat.ArrheniusUpdate.of(base)
    fixed = arrhenius.at(thermal.steady_k+theta)        # also refuses a nonpositive initial temperature

    def solve_stage(th, k, previous):
        prep = arrhenius.at(thermal.steady_k+th) if feedback else fixed
        warm = previous if warm_start and previous is not None and previous["x"] is not None else None
        return stage(prep, law, k, drive, fractions, warm=warm, deadline=deadline)

    current = solve_stage(theta, kappa0, None)
    first, kappa, strain, displacement = current, kappa0.copy(), 0., 0.
    acc = dict.fromkeys([key for key, _ in STAGE_ACCOUNTS]+list(THERMAL_ACCOUNTS), 0.)
    stats = dict(max_force_relative=0., max_power_relative=0., min_source_w_m2=math.inf, min_dissipation_w_m=math.inf,
                 restress_mismatches=0, evaluations=0, iterations=0, stages=0)
    note(stats, current)
    yield_stages = (current["plastic_rate"] > 0).astype(int)
    g_top, g_bot = thermal.boundary_conductance
    worst_energy = worst_step = 0.
    accepted, status = 0, "COMPLETE"
    for _ in range(steps):
        try:
            check_deadline(deadline)
            p = prop if provider is None else provider()
            if type(p) is not heat.Propagator or p.fingerprint != thermal.fingerprint or p.dt != dt:
                raise ValueError("replacement propagator changed the support or step")
            theta_a, _ = heat.conduct(p, theta, current["source"])
            predictor = solve_stage(theta_a, kappa+dt*current["kdot"], current)
            new_theta, integral = heat.conduct(p, theta, current["source"], predictor["source"])
            new_kappa = kappa+dt*(current["kdot"]+predictor["kdot"])/2
            new_strain = strain+dt*(current["rate"]+predictor["rate"])/2
            if abs(new_strain) > bound:
                status = "REFUSED_SMALL_STRAIN"
                break
            jump = float(np.abs(new_theta-theta).max())
            if jump > limit:
                status = "REFUSED_TEMPERATURE_STEP"
                break
            if np.any(thermal.steady_k+new_theta <= 0) or np.any(new_kappa < kappa):
                raise RuntimeError("temperature nonpositive or raw history decreased")
            if np.any(new_kappa-kappa0 > 2*abs(new_strain)*(1+1e-10)):
                raise RuntimeError("plastic history exceeds the total-strain bound")
            endpoint = solve_stage(new_theta, new_kappa, predictor)     # re-solved before anything is booked
        except RuntimeError:
            if not expired(deadline):
                raise
            status = "REFUSED_DEADLINE"
            break
        heat_step = dt*(current["heat"]+predictor["heat"])/2
        surface = g_top*integral[0]                  # departure heat leaving at the surface
        base_in = -g_bot*integral[-1]                # departure heat entering at the base
        change = math.fsum(thermal.capacity*(new_theta-theta))
        worst_energy = max(worst_energy, ratio(change-(heat_step-surface+base_in),
                                               abs(heat_step)+abs(surface)+abs(base_in)))
        for key, name in STAGE_ACCOUNTS:
            acc[key] += dt*(current[name]+predictor[name])/2
        acc["surface_loss_j_m2"] += surface
        acc["base_gain_j_m2"] += base_in
        acc["thermal_change_j_m2"] += change
        displacement += dt*(current["velocity_m_s"]+predictor["velocity_m_s"])/2
        theta, kappa, strain, current = new_theta, new_kappa, new_strain, endpoint
        worst_step = max(worst_step, jump)
        accepted += 1
        for s in (predictor, endpoint):
            note(stats, s)
            yield_stages += s["plastic_rate"] > 0
    fc, fp = fractions
    drive_work, drag_work = acc["drive_work_j_m"], acc["drag_work_j_m"]
    column_m = acc["column_creep_work_j_m"]+acc["column_plastic_work_j_m"]
    column_a = acc["creep_work_j_m2"]+acc["plastic_work_j_m2"]
    ideal = fc*acc["creep_work_j_m2"]+fp*acc["plastic_work_j_m2"]
    boundary = acc["heat_j_m2"]-acc["surface_loss_j_m2"]+acc["base_gain_j_m2"]
    acc.update(
        motion_work_relative=ratio(drive_work-drag_work-column_m, drive_work),
        drive_displacement_relative=ratio(drive_work-drive.force_n_m*displacement, drive_work),
        width_relative=ratio(drive.width_m*column_a-column_m, column_m),
        partition_relative=ratio(column_a-acc["column_work_j_m2"], acc["column_work_j_m2"]),
        column_energy_relative=ratio(acc["column_work_j_m2"]-acc["heat_j_m2"]-acc["stored_j_m2"],
                                     acc["column_work_j_m2"]),
        work_to_heat_relative=ratio(acc["heat_j_m2"]-ideal, ideal),
        drag_excluded_relative=ratio(drive.width_m*(acc["heat_j_m2"]+acc["stored_j_m2"])-(drive_work-drag_work),
                                     drive_work),
        energy_relative=ratio(acc["thermal_change_j_m2"]-boundary, abs(acc["heat_j_m2"])
                              + abs(acc["surface_loss_j_m2"])+abs(acc["base_gain_j_m2"])))
    switching = (yield_stages > 0) & (yield_stages < stats["stages"])
    return dict(status=status, accepted_steps=accepted, elapsed_s=accepted*dt, time_step_s=dt, strain=strain,
                displacement_m=displacement, theta=theta, theta0=theta_start, kappa=kappa, kappa0=kappa0,
                mean_history_gain=math.fsum(base.weight*(kappa-kappa0))/math.fsum(base.weight),
                velocity_start_m_s=first["velocity_m_s"], velocity_end_m_s=current["velocity_m_s"],
                column_force_start_n_m=first["force"], column_force_end_n_m=current["force"], accounts=acc,
                reference=reference_throughput(thermal, accepted*dt), max_step_energy_relative=worst_energy,
                max_temperature_step_k=worst_step, yield_switching_points=int(np.count_nonzero(switching)),
                final=current, **stats)


# ----------------------------------------------------------------------------- independent scalar oracle

def scalar_balance(layer, law, drive, temperature, kappa):
    """Independent force balance of a uniform supplied-pressure layer.

    Column kernel LocalLaw (not the vectorised helper), ASPECT-transcribed weakening factors and SciPy Brent
    in x = |v| D/|F| on [0, 1]; x = 0 is the continuous zero-stress limit.
    """
    mechanisms = tuple(column.Creep(**c) for c in layer["creep"])
    lc, lf = weakening.aspect_factors(kappa, law)
    local = column.LocalLaw.prepare(
        mechanisms, temperature, layer["mean_pressure_pa"][0], grain_m=layer["grain_m"],
        cohesion_pa=layer["cohesion_pa"]*lc, friction_rad=layer["friction_rad"]*lf,
        pore_pressure_pa=layer["pore_pressure_pa"][0], plastic_viscosity_pa_s=layer["plastic_viscosity_pa_s"])
    target, sign = abs(drive.force_n_m), math.copysign(1., drive.force_n_m)
    rate_scale = target/drive.drag_pa_s/drive.width_m

    def residual(x):
        return -1. if x == 0 else x+2*layer["thickness_m"]*local.solve(rate_scale*x)["stress_pa"]/target-1.
    x = brentq(residual, 0., 1., xtol=1e-15, rtol=1e-13, maxiter=200)
    r = local.solve(rate_scale*x)
    return dict(velocity_m_s=sign*target/drive.drag_pa_s*x, rate=sign*rate_scale*x, stress_pa=r["stress_pa"],
                creep_rate_s=math.fsum(r["creep_rates_s"]), plastic_rate_s=r["plastic_rate_s"])


def force_oracle(layer, thermal, law, drive, kappa0, duration, fractions):
    """Insulated uniform layer under constant drive: DOP853 on (T, kappa, strain), balance re-solved per call."""
    rho_cp = thermal["density_kg_m3"]*thermal["heat_capacity_j_kg_k"]
    t0 = float(layer["temperature_k"][0])

    def rhs(_t, y):
        r = scalar_balance(layer, law, drive, float(y[0]), float(y[1]))
        heating = 2*r["stress_pa"]*(fractions[0]*r["creep_rate_s"]+fractions[1]*r["plastic_rate_s"])
        return [heating/rho_cp, 2*r["plastic_rate_s"], r["rate"]]
    sol = solve_ivp(rhs, (0., duration), [t0, float(kappa0), 0.], method="DOP853", rtol=1e-10,
                    atol=[1e-9, 1e-14, 1e-14])
    if not sol.success:
        raise RuntimeError("scalar force-driven oracle failed")
    t_end, k_end, strain = map(float, sol.y[:, -1])
    start = scalar_balance(layer, law, drive, t0, float(kappa0))
    end = scalar_balance(layer, law, drive, t_end, k_end)
    return dict(temperature_rise=t_end-t0, history_gain=k_end-kappa0, strain=strain,
                velocity_start_m_s=start["velocity_m_s"], velocity_end_m_s=end["velocity_m_s"],
                evaluations=int(sol.nfev), always_yielding=start["plastic_rate_s"] > 0 and end["plastic_rate_s"] > 0)


# ----------------------------------------------------------------------------- case

def policy_ceilings(heat_policy, motion_case):
    """Retained tolerances may be tightened, never relaxed; the new gates are frozen here before any run."""
    return dict(NEW_GATES, force_relative=motion.FORCE_TOL, power_relative=MOTION_POWER_RELATIVE,
                work_relative=MOTION_POWER_RELATIVE, energy_relative=heat_policy["energy_relative"],
                work_heat_relative=heat_policy["work_heat_relative"], flow_relative=heat_policy["flow_relative"],
                oracle_relative=heat_policy["oracle_relative"], uniform_relative=heat_policy["uniform_relative"],
                time_temperature_k=heat_policy["time_temperature_k"],
                depth_energy_relative=heat_policy["depth_energy_relative"],
                feedback_depth_relative=heat_policy["feedback_depth_relative"],
                time_velocity_relative=motion_case["time_relative"], depth_velocity_relative=motion_case["depth_relative"],
                root_parity_relative=motion_case["parity_relative"], parity_relative=motion_case["parity_relative"])


def doubled(values, ceiling):
    if (type(values) is not list or len(values) != 3 or any(type(n) is not int or not 1 <= n <= ceiling for n in values)
            or values[1] != 2*values[0] or values[2] != 2*values[1]):
        raise ValueError("three doubled integer refinements required within the fixed ceilings")
    return values


def validate_case(spec):
    """Strict schema; forcing and physics come only from the two reviewed cases, loaded by their own helpers."""
    fields = {"schema", "status", "scope", "provenance", "representation", "inputs", "drive", "campaign", "policy"}
    if type(spec) is not dict or set(spec) != fields or spec["schema"] != SCHEMA:
        raise ValueError("thermomechanical-motion case schema or top-level fields mismatch")
    rep = spec["representation"]
    if type(rep) is not dict or set(rep) != set(REPRESENTATION) | REPRESENTATION_LIMITS:
        raise ValueError("representation must declare only the supported fields")
    for key, text in REPRESENTATION.items():
        if rep[key] != text:
            raise ValueError("only the declared thermomechanical representation is supported: "+key)
    bound = weakening.strain_limit(rep["max_axial_strain"])
    if not 0 < number(rep["max_temperature_step_k"], "temperature step guard") <= 5:
        raise ValueError("temperature step guard must lie in (0, 5] K")
    if spec["inputs"] != INPUTS:
        raise ValueError("only the reviewed column-heat and motion-coupling cases are admitted")
    heat_spec, weak = heat.load_case(ROOT/INPUTS["column_heat_case"])
    if motion.CASE.resolve() != (ROOT/INPUTS["motion_case"]).resolve():
        raise ValueError("the motion adapter reads a different case")
    mspec = motion.load_case()
    drive = motion.Drive(mspec["drive_n_m"], mspec["drag_pa_s"], mspec["width_m"])
    d = spec["drive"]
    if type(d) is not dict or set(d) != {"source", "duration_s", "drag_only_rate_bound_s"}:
        raise ValueError("drive declares only its source, duration and drag-only bound; forcing is the motion case's")
    duration = positive(d["duration_s"], "duration")
    rate_bound = abs(drive.force_n_m)/drive.drag_pa_s/drive.width_m          # |a| <= |F|/(D w) for any column state
    if relative_change(rate_bound, positive(d["drag_only_rate_bound_s"], "drag-only rate bound")) > 1e-12:
        raise ValueError("declared drag-only rate bound differs from the motion case")
    if rate_bound*duration > bound:
        raise ValueError("duration exceeds the small-strain window guaranteed by the drag-only bound")
    camp = spec["campaign"]
    if type(camp) is not dict or set(camp) != CAMPAIGN_KEYS:
        raise ValueError("campaign fields mismatch")
    h, s, r = camp["homogeneous"], camp["states"], camp["refusal"]
    if (type(h) is not dict or set(h) != {"order", "steps"} or type(s) is not dict
            or set(s) != {"order", "steps", "rest_amplitude_k"} or type(r) is not dict or set(r) != REFUSAL_KEYS):
        raise ValueError("campaign sub-fields mismatch")
    doubled(camp["time_steps"], 256), doubled(camp["orders"], 128), doubled(h["steps"], 256)
    counts = (camp["reference_steps"], s["steps"], r["strain_steps"], r["temperature_steps"], r["deadline_steps"])
    levels = (camp["reference_order"], h["order"], s["order"], r["order"], *camp["orders"])
    if (any(type(n) is not int or not 1 <= n <= 256 for n in counts)
            or any(type(q) is not int or not 2 <= q <= 128 for q in levels)):
        raise ValueError("step counts must be integers in 1..256 and quadrature orders in 2..128")
    if camp["reference_steps"] != camp["time_steps"][-1] or camp["reference_order"] != camp["orders"][1]:
        raise ValueError("the reference run is the finest time level and the middle depth level")
    if r["strain_steps"] < 2 or r["deadline_steps"] < 2 or number(r["strain_bound_factor"], "strain factor") <= 1:
        raise ValueError("atomic refusal fixtures need a later step to refuse")
    if not 0 < number(r["temperature_guard_k"], "refusal temperature guard") <= 5:
        raise ValueError("refusal temperature guard must lie in (0, 5] K")
    positive(r["strain_step_duration_s"], "refusal step duration")
    positive(r["compressive_volume_m3_mol"], "refusal activation volume")
    positive(s["rest_amplitude_k"], "rest departure amplitude")
    pol = spec["policy"]
    ceilings = policy_ceilings(heat_spec["policy"], mspec)
    if (type(pol) is not dict or set(pol) != set(ceilings) | {"max_steps", "coupling_resolution_factor",
                                                             "oracle_order_range"} or pol["max_steps"] != 256):
        raise ValueError("policy fields mismatch or step ceiling changed")
    for key, ceiling in ceilings.items():
        if not 0 < number(pol[key], key) <= ceiling:
            raise ValueError("policy relaxes a retained or frozen tolerance: "+key)
    if number(pol["coupling_resolution_factor"], "resolution factor") < heat_spec["policy"]["coupling_resolution_factor"]:
        raise ValueError("policy relaxes the retained feedback-resolution factor")
    span, retained = pol["oracle_order_range"], heat_spec["policy"]["oracle_order_range"]
    if type(span) is not list or len(span) != 2 or not retained[0] <= span[0] < span[1] <= retained[1]:
        raise ValueError("oracle order range must lie within the retained range")
    return spec, dict(heat=heat_spec, weak=weak, motion=mspec, drive=drive, law=weakening.law_of(weak))


def load_case(path=CASE):
    return validate_case(json.loads(Path(path).read_text(encoding="utf-8")))


# ----------------------------------------------------------------------------- fixtures from the reviewed cases

def layered(ctx, order):
    """Reviewed mechanical preparation, its paired thermal support, and the inputs key proving freshness."""
    base, thermal, layers = heat.setup(ctx["heat"], ctx["weak"], order=order)
    return base, thermal, (layers, order, weakening.LITHOSTATIC, ctx["weak"]["representation"]["gravity_m_s2"])


def homogeneous_setup(ctx, order):
    """The column-heat case's insulated uniform layer, unchanged; only the forcing differs (motion case)."""
    h = ctx["heat"]["campaign"]["homogeneous"]
    layer = h["layer"]
    base = weakening.prepare([layer], order, closure=weakening.SUPPLIED)
    props = [dict(name=layer["name"], conductivity_w_m_k=h["thermal"]["conductivity_w_m_k"],
                  heat_capacity_j_kg_k=h["thermal"]["heat_capacity_j_kg_k"], radiogenic_w_m3=0.)]
    thermal = heat.prepare_thermal(base.layer, base.depth_m, base.weight, [layer["thickness_m"]], props,
                                   [h["thermal"]["density_kg_m3"]],
                                   dict(top=dict(type="insulated"), bottom=dict(type="insulated")),
                                   reference_temperature=layer["temperature_k"][0],
                                   mechanical_fingerprint=base.fingerprint)
    return base, thermal, h


def compressive_column(ctx, volume):
    """Retained pressure-branch fixture: a 1 km lid whose creep volume makes compressive creep non-monotone."""
    weak = ctx["weak"]
    lid = weak["layers"][2]
    single = dict(lid, thickness_m=1000., creep=[dict(lid["creep"][0], volume_m3_mol=volume)])
    tiny = weakening.prepare([single], 2, closure=weakening.LITHOSTATIC, gravity=weak["representation"]["gravity_m_s2"])
    ends = dict(top=dict(type="temperature", value_k=lid["temperature_k"][0]),
                bottom=dict(type="temperature", value_k=lid["temperature_k"][1]))
    thermal = heat.prepare_thermal(tiny.layer, tiny.depth_m, tiny.weight, [1000.], [dict(ctx["heat"]["thermal_layers"][2])],
                                   [lid["density_kg_m3"]], ends, mechanical_fingerprint=tiny.fingerprint)
    return tiny, thermal


def run(spec, ctx, base, thermal, key, *, steps, drive=None, kappa0=None, **kw):
    rep = spec["representation"]
    kw.setdefault("duration_s", spec["drive"]["duration_s"])
    kw.setdefault("fractions", ctx["heat"]["heat_fractions"])
    return evolve(base, thermal, ctx["law"], weakening.initial_history(base, ctx["weak"]) if kappa0 is None else kappa0,
                  ctx["drive"] if drive is None else drive, steps=steps, strain_bound=rep["max_axial_strain"],
                  temperature_step_k=rep["max_temperature_step_k"], policy=spec["policy"], inputs=key, **kw)


SCALARS = ("status", "accepted_steps", "elapsed_s", "strain", "displacement_m", "velocity_start_m_s",
           "velocity_end_m_s", "column_force_start_n_m", "column_force_end_n_m", "mean_history_gain",
           "max_step_energy_relative", "max_temperature_step_k", "max_force_relative", "max_power_relative",
           "min_source_w_m2", "min_dissipation_w_m", "restress_mismatches", "stages", "evaluations", "iterations",
           "yield_switching_points")


def summary(out, base):
    """Reportable scalars only; per-point arrays stay in memory."""
    theta, gain = out["theta"], out["kappa"]-out["kappa0"]
    i = int(np.argmax(theta))
    layers = range(int(base.layer.max())+1)
    return dict({k: out[k] for k in SCALARS}, accounts=out["accounts"], reference=out["reference"],
                max_temperature_departure_k=float(theta[i]), depth_of_max_departure_km=float(base.depth_m[i]/1e3),
                min_temperature_departure_k=float(theta.min()), warming_by_layer_k=heat.layer_warming(theta, base),
                max_history_gain_by_layer=[float(gain[base.layer == li].max()) for li in layers],
                yielding_points_final=int(np.count_nonzero(out["final"]["plastic_rate"] > 0)))


def orders(changes):
    return [None if math.isnan(o) else o for o in weakening.order(changes)]


def in_range(values, span):
    return bool(values) and all(o is not None and span[0] <= o <= span[1] for o in values)


# ----------------------------------------------------------------------------- controls

def limits_control(spec, ctx, deadline=None):
    """No heating reproduces retained motion at the same thermal-reference preparation, bitwise; heating
    with feedback off keeps that motion and history while its thermal accounts close."""
    pol, camp, rep = spec["policy"], spec["campaign"], spec["representation"]
    base, thermal, key = layered(ctx, camp["reference_order"])
    steps, duration = camp["reference_steps"], spec["drive"]["duration_s"]
    fixed = heat.ArrheniusUpdate.of(base).at(np.array(thermal.steady_k))
    reviewed = motion.evolve(fixed, ctx["law"], weakening.initial_history(base, ctx["weak"]), ctx["drive"],
                             duration_s=duration, steps=steps, strain_bound=rep["max_axial_strain"], deadline=deadline)
    prop = heat.prepare_propagator(thermal, duration/steps)
    cold = run(spec, ctx, base, thermal, key, steps=steps, fractions=(0., 0.), propagator=prop, deadline=deadline)
    frozen = run(spec, ctx, base, thermal, key, steps=steps, feedback=False, propagator=prop, deadline=deadline)
    pairs = (("drive_work_j_m", "drive"), ("drag_work_j_m", "drag"), ("column_creep_work_j_m", "creep"),
             ("column_plastic_work_j_m", "plastic"))

    def same(out):
        return (out["status"] == reviewed["status"] and out["accepted_steps"] == reviewed["accepted_steps"]
                and np.array_equal(out["kappa"], reviewed["kappa"]) and out["strain"] == reviewed["strain"]
                and out["velocity_start_m_s"] == reviewed["velocity_start_m_s"]
                and out["velocity_end_m_s"] == reviewed["velocity_end_m_s"]
                and all(out["accounts"][a] == reviewed["energy_j_m"][b] for a, b in pairs))
    ca, fa = cold["accounts"], frozen["accounts"]
    checks = dict(
        no_heating_temperature_bitwise=not np.any(cold["theta"]),
        no_heating_motion_bitwise=same(cold),
        no_heating_stored_all_work=ca["heat_j_m2"] == 0
        and relative_change(ca["stored_j_m2"], ca["column_work_j_m2"]) <= pol["work_heat_relative"],
        no_feedback_motion_bitwise=same(frozen),
        no_feedback_heats=float(frozen["theta"].max()) > 0,
        no_feedback_energy=fa["energy_relative"] <= pol["energy_relative"]
        and frozen["max_step_energy_relative"] <= pol["energy_relative"],
        no_feedback_work_to_heat=fa["work_to_heat_relative"] <= pol["work_heat_relative"],
        drag_not_column_heat=fa["drag_excluded_relative"] <= pol["work_relative"],
        motion_work=max(r["accounts"]["motion_work_relative"] for r in (cold, frozen)) <= pol["work_relative"],
        same_state_booked=cold["restress_mismatches"] == 0 and frozen["restress_mismatches"] == 0)
    return verdict(checks, reviewed={k: reviewed[k] for k in ("status", "accepted_steps", "strain", "velocity_start_m_s",
                                                              "velocity_end_m_s", "energy_j_m", "work_relative")},
                   no_feedback=summary(frozen, base))


def homogeneous_control(spec, ctx, deadline=None):
    """Insulated uniform force-driven layer versus an independent integrator and independent scalar roots."""
    pol, hc = spec["policy"], spec["campaign"]["homogeneous"]
    base, thermal, h = homogeneous_setup(ctx, hc["order"])
    layer, law, drive = h["layer"], ctx["law"], ctx["drive"]
    duration, fractions = spec["drive"]["duration_s"], tuple(ctx["heat"]["heat_fractions"])
    oracle = force_oracle(layer, h["thermal"], law, drive, h["initial_history"], duration, fractions)
    kappa0 = np.full(base.size, float(h["initial_history"]))
    runs = [evolve(base, thermal, law, kappa0, drive, duration_s=duration, steps=n,
                   strain_bound=spec["representation"]["max_axial_strain"],
                   temperature_step_k=spec["representation"]["max_temperature_step_k"], fractions=fractions,
                   policy=pol, deadline=deadline) for n in hc["steps"]]
    fine = runs[-1]
    t_err = [relative_change(float(r["theta"][0]), oracle["temperature_rise"]) for r in runs]
    k_err = [relative_change(float(r["kappa"][0])-h["initial_history"], oracle["history_gain"]) for r in runs]
    s_err = [relative_change(r["strain"], oracle["strain"]) for r in runs]
    v_err = [relative_change(r["velocity_end_m_s"], oracle["velocity_end_m_s"]) for r in runs]
    end = scalar_balance(layer, law, drive, float(thermal.steady_k[0]+fine["theta"][0]), float(fine["kappa"][0]))
    roots = dict(initial=relative_change(fine["velocity_start_m_s"], oracle["velocity_start_m_s"]),
                 final_state=relative_change(fine["velocity_end_m_s"], end["velocity_m_s"]))
    spread = max(max(float(np.ptp(r["theta"]))/float(np.abs(r["theta"]).max()),
                     float(np.ptp(r["kappa"]))/float(r["kappa"].max())) for r in runs)
    span = pol["oracle_order_range"]
    checks = dict(
        complete=all(r["status"] == "COMPLETE" for r in runs), always_yielding=oracle["always_yielding"],
        uniform=spread <= pol["uniform_relative"],
        temperature_order=in_range(orders(t_err), span), history_order=in_range(orders(k_err), span),
        finest=max(t_err[-1], k_err[-1], s_err[-1], v_err[-1]) <= pol["oracle_relative"],
        independent_roots=max(roots.values()) <= pol["root_parity_relative"],
        accelerates=fine["velocity_end_m_s"] > fine["velocity_start_m_s"] and float(fine["theta"][0]) > 0,
        insulated_no_boundary_heat=all(r["accounts"]["surface_loss_j_m2"] == 0 and r["accounts"]["base_gain_j_m2"] == 0
                                       for r in runs),
        energy=all(r["accounts"]["energy_relative"] <= pol["energy_relative"] for r in runs),
        work_to_heat=all(r["accounts"]["work_to_heat_relative"] <= pol["work_heat_relative"] for r in runs),
        motion_work=all(r["accounts"]["motion_work_relative"] <= pol["work_relative"]
                        and r["accounts"]["drag_excluded_relative"] <= pol["work_relative"] for r in runs))
    return verdict(checks, oracle=oracle, steps=hc["steps"], temperature_errors=t_err, history_errors=k_err,
                   strain_errors=s_err, velocity_errors=v_err, temperature_orders=orders(t_err),
                   history_orders=orders(k_err), strain_orders=orders(s_err), velocity_orders=orders(v_err),
                   root_relative=roots, uniform_relative_spread=spread,
                   finest=dict(temperature_rise_k=float(fine["theta"][0]), velocity_start_m_s=fine["velocity_start_m_s"],
                               velocity_end_m_s=fine["velocity_end_m_s"], strain=fine["strain"],
                               drag_share=fine["accounts"]["drag_work_j_m"]/fine["accounts"]["drive_work_j_m"]))


def feedback_control(spec, ctx, deadline=None):
    """Feedback on/off at identical drive, drag and history, with time and depth refinement of velocity,
    temperature, history and the work/heat accounts together."""
    pol, camp = spec["policy"], spec["campaign"]
    duration, ref_q, ref_n = spec["drive"]["duration_s"], camp["reference_order"], camp["reference_steps"]
    prepared = {q: layered(ctx, q) for q in camp["orders"]}

    def pair(q, n):
        base, thermal, key = prepared[q]
        prop = heat.prepare_propagator(thermal, duration/n)       # one support and step: shared by both runs
        return {fb: run(spec, ctx, base, thermal, key, steps=n, feedback=fb, propagator=prop, deadline=deadline)
                for fb in (True, False)}
    by_steps = {n: pair(ref_q, n) for n in camp["time_steps"]}
    by_order = {q: by_steps[ref_n] if q == ref_q else pair(q, ref_n) for q in camp["orders"]}
    ts, qs = camp["time_steps"], camp["orders"]
    base, thermal, _ = prepared[ref_q]
    on, off = by_steps[ref_n][True], by_steps[ref_n][False]

    def changes(runs, metric):
        return [metric(a, b) for a, b in zip(runs, runs[1:])]       # each pair compared with its finer run

    def account(name):
        return lambda a, b: relative_change(a["accounts"][name], b["accounts"][name])
    velocity = lambda a, b: relative_change(a["velocity_end_m_s"], b["velocity_end_m_s"])
    temperature = lambda a, b: float(np.abs(a["theta"]-b["theta"]).max())
    history = lambda a, b: float(np.abs(a["kappa"]-b["kappa"]).max())/max(float((b["kappa"]-b["kappa0"]).max()), TINY)
    work = lambda a, b: max(account("drive_work_j_m")(a, b), account("heat_j_m2")(a, b))
    t_on, t_off = [by_steps[n][True] for n in ts], [by_steps[n][False] for n in ts]
    d_on = [by_order[q][True] for q in qs]
    in_time = dict(velocity=changes(t_on, velocity), temperature_k=changes(t_on, temperature),
                   history=changes(t_on, history), work_heat=changes(t_on, work))
    in_depth = dict(velocity=changes(d_on, velocity), thermal_energy=changes(d_on, account("thermal_change_j_m2")),
                 heat=changes(d_on, account("heat_j_m2")), drive_work=changes(d_on, account("drive_work_j_m")),
                 mean_history=changes(d_on, lambda a, b: relative_change(a["mean_history_gain"], b["mean_history_gain"])))
    # Second order is claimed only for a smooth reference: feedback off and no yield-state switching.
    switching_off = sum(r["yield_switching_points"] for r in t_off)
    smooth = dict(claimed=switching_off == 0, yield_switching_points=switching_off,
                  temperature_orders=orders(changes(t_off, temperature)), history_orders=orders(changes(t_off, history)),
                  velocity_orders=orders(changes(t_off, velocity)),
                  note="feedback off: same drive, heating and history law, mechanics at the initial temperature; "
                       "velocity orders are reported but not gated because solver residuals approach its changes")
    feedback = {q: (by_order[q][True]["velocity_end_m_s"]-by_order[q][False]["velocity_end_m_s"])
                / by_order[q][False]["velocity_end_m_s"] for q in qs}
    feedback_depth = relative_change(feedback[qs[-2]], feedback[qs[-1]])
    resolution = max(in_time["velocity"][-1], in_depth["velocity"][-1])
    runs = [r for q in qs for r in by_order[q].values()]+[r for n in ts if n != ref_n for r in by_steps[n].values()]
    worst = lambda name: max(r["accounts"][name] for r in runs)
    checks = dict(
        all_complete=all(r["status"] == "COMPLETE" for r in runs),
        time_velocity=in_time["velocity"][-1] <= pol["time_velocity_relative"],
        time_temperature=in_time["temperature_k"][-1] <= pol["time_temperature_k"],
        time_history=in_time["history"][-1] <= pol["time_history_relative"],
        time_work_heat=in_time["work_heat"][-1] <= pol["time_work_relative"],
        smooth_time_order_where_claimed=not smooth["claimed"] or (
            in_range(smooth["temperature_orders"], pol["oracle_order_range"])
            and in_range(smooth["history_orders"], pol["oracle_order_range"])),
        depth_velocity=in_depth["velocity"][-1] <= pol["depth_velocity_relative"],
        depth_energy=max(in_depth["thermal_energy"][-1], in_depth["heat"][-1]) <= pol["depth_energy_relative"],
        depth_history=in_depth["mean_history"][-1] <= pol["depth_history_relative"],
        depth_work=in_depth["drive_work"][-1] <= pol["depth_work_relative"],
        feedback_speeds_motion=feedback[ref_q] > 0 and float(on["theta"].max()) > 0,
        feedback_resolved=feedback[ref_q] >= pol["coupling_resolution_factor"]*resolution,
        feedback_depth=feedback_depth <= pol["feedback_depth_relative"],
        stage_balance=max(r["max_force_relative"] for r in runs) <= pol["force_relative"]
        and max(r["max_power_relative"] for r in runs) <= pol["power_relative"],
        same_state_booked=all(r["restress_mismatches"] == 0 for r in runs),
        motion_work=max(worst("motion_work_relative"), worst("drive_displacement_relative"),
                        worst("width_relative"), worst("drag_excluded_relative")) <= pol["work_relative"],
        column_work=max(worst("partition_relative"), worst("column_energy_relative"),
                        worst("work_to_heat_relative")) <= pol["work_heat_relative"],
        thermal_energy=worst("energy_relative") <= pol["energy_relative"]
        and max(r["max_step_energy_relative"] for r in runs) <= pol["energy_relative"],
        nonnegative_dissipation=min(min(r["min_source_w_m2"], r["min_dissipation_w_m"]) for r in runs) >= 0,
        reference_balanced=on["reference"]["balance_relative"] <= pol["flow_relative"])
    surface0, _, base0 = thermal.upward_flows(thermal.steady_k)
    surface1, _, base1 = thermal.upward_flows(thermal.steady_k+on["theta"])
    moved = np.flatnonzero((on["final"]["plastic_rate"] > 0) != (off["final"]["plastic_rate"] > 0))
    return verdict(
        checks, feedback_on=summary(on, base), feedback_off=summary(off, base),
        velocity_feedback_by_order=feedback, feedback_depth_change=feedback_depth, refinement_resolution=resolution,
        velocity_gain=dict(on=on["velocity_end_m_s"]/on["velocity_start_m_s"],
                           off=off["velocity_end_m_s"]/off["velocity_start_m_s"]),
        time_steps=ts, time_changes=in_time, time_velocity_orders_feedback_on=orders(in_time["velocity"]),
        yield_switching_points={n: dict(on=by_steps[n][True]["yield_switching_points"],
                                        off=by_steps[n][False]["yield_switching_points"]) for n in ts},
        smooth_reference=smooth, orders=qs, depth_changes=in_depth,
        yield_state_changed_by_heat_km=[float(base.depth_m[i]/1e3) for i in moved],
        heat_flows_w_m2=dict(surface_initial=float(surface0), surface_final=float(surface1),
                             base_initial=float(base0), base_final=float(base1)),
        retained_heat_fraction=ratio(on["accounts"]["thermal_change_j_m2"], on["accounts"]["heat_j_m2"]))


def states_control(spec, ctx, deadline=None):
    """Rest conducts only an existing departure; supported extension and compression dissipate nonnegatively."""
    pol, s = spec["policy"], spec["campaign"]["states"]
    base, thermal, key = layered(ctx, s["order"])
    drive = ctx["drive"]
    prop = heat.prepare_propagator(thermal, spec["drive"]["duration_s"]/s["steps"])
    common = dict(steps=s["steps"], propagator=prop, deadline=deadline)
    rest_drive = motion.Drive(0., drive.drag_pa_s, drive.width_m)
    bump = s["rest_amplitude_k"]*np.sin(math.pi*np.asarray(base.depth_m)/thermal.thickness_m)
    rest = run(spec, ctx, base, thermal, key, drive=rest_drive, theta0=bump, **common)
    still = run(spec, ctx, base, thermal, key, drive=rest_drive, **common)
    ext = run(spec, ctx, base, thermal, key, **common)
    comp = run(spec, ctx, base, thermal, key, drive=motion.Drive(-drive.force_n_m, drive.drag_pa_s, drive.width_m),
               **common)
    ra = rest["accounts"]
    mechanical = ("drive_work_j_m", "drag_work_j_m", "column_creep_work_j_m", "column_plastic_work_j_m",
                  "column_work_j_m2", "heat_j_m2", "stored_j_m2")

    def closed(r):
        a = r["accounts"]
        return (r["status"] == "COMPLETE" and r["max_force_relative"] <= pol["force_relative"]
                and r["restress_mismatches"] == 0
                and max(a["motion_work_relative"], a["drive_displacement_relative"], a["drag_excluded_relative"])
                <= pol["work_relative"] and a["work_to_heat_relative"] <= pol["work_heat_relative"]
                and a["energy_relative"] <= pol["energy_relative"])
    checks = dict(
        rest_no_motion=all(rest[k] == 0 for k in ("velocity_start_m_s", "velocity_end_m_s", "strain", "displacement_m")),
        rest_no_mechanical_heat_or_history=all(ra[k] == 0 for k in mechanical)
        and np.array_equal(rest["kappa"], rest["kappa0"]),
        rest_departure_conducts=rest["status"] == "COMPLETE" and not np.array_equal(rest["theta"], bump)
        and ra["thermal_change_j_m2"] < 0 and float(np.abs(rest["theta"]).max()) < float(np.abs(bump).max()),
        rest_energy=ra["energy_relative"] <= pol["energy_relative"] and ra["surface_loss_j_m2"] > 0,
        rest_without_departure_bitwise=not np.any(still["theta"]) and still["strain"] == 0
        and np.array_equal(still["kappa"], still["kappa0"]),
        extension=ext["strain"] > 0 and ext["velocity_end_m_s"] > 0 and closed(ext),
        compression=comp["strain"] < 0 and comp["velocity_end_m_s"] < 0 and comp["accounts"]["drive_work_j_m"] > 0
        and closed(comp),
        both_heat_the_column=float(ext["theta"].max()) > 0 and float(comp["theta"].max()) > 0,
        nonnegative_dissipation=all(min(r["min_source_w_m2"], r["min_dissipation_w_m"]) >= 0 for r in (rest, ext, comp)))
    return verdict(checks, rest=dict(accounts=ra, max_departure_start_k=float(np.abs(bump).max()),
                                     max_departure_end_k=float(np.abs(rest["theta"]).max())),
                   extension=summary(ext, base), compression=summary(comp, base),
                   compression_to_extension_speed=abs(comp["velocity_end_m_s"])/ext["velocity_end_m_s"])


CASE_MUTATIONS = (
    ("advection", ("representation", "advection_velocity_m_s"), 1e-10),
    ("finite_strain_geometry", ("representation", "geometry"), "Eulerian finite-strain column with thinning"),
    ("strain_allowance", ("representation", "max_axial_strain"), .2),
    ("temperature_guard", ("representation", "max_temperature_step_k"), 50.),
    ("rate_control", ("representation", "control"), "supplied axial rate"),
    ("drag_heats_column", ("representation", "heating"), "column and external drag dissipation deposited in the column"),
    ("drag_heat_fraction", ("representation", "drag_heat_fraction"), 1.),
    ("melting", ("representation", "melt_fraction"), 0.),
    ("duration_beyond_drag_bound", ("drive", "duration_s"), 2e13),
    ("tuned_force", ("drive", "force_n_m"), 3e13),
    ("drag_bound_mismatch", ("drive", "drag_only_rate_bound_s"), 1e-14),
    ("other_motion_case", ("inputs", "motion_case"), "cases/i01_weakening_v1.json"),
    ("other_heat_case", ("inputs", "column_heat_case"), "cases/i01_column_v1.json"),
    ("step_ceiling", ("policy", "max_steps"), 512),
    ("relaxed_force_residual", ("policy", "force_relative"), 1e-8),
    ("relaxed_energy", ("policy", "energy_relative"), 1e-6),
    ("oversized_time_series", ("campaign", "time_steps"), [128, 256, 512]),
    ("missing_policy_key", ("policy", "work_heat_relative"), KeyError))


def mutated(spec, path, value):
    bad = copy.deepcopy(spec)
    target = bad
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return bad


def same_prefix(a, b):
    return (a["accepted_steps"] == b["accepted_steps"] and np.array_equal(a["theta"], b["theta"])
            and np.array_equal(a["kappa"], b["kappa"]) and a["strain"] == b["strain"]
            and a["displacement_m"] == b["displacement_m"] and a["velocity_end_m_s"] == b["velocity_end_m_s"]
            and a["accounts"] == b["accounts"])


def refusal_control(spec, ctx, deadline=None):
    """Unadmitted fixtures and direct inputs refuse; strain, temperature and deadline refusals are atomic."""
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
    base, thermal, key = layered(ctx, r["order"])
    kappa0 = weakening.initial_history(base, ctx["weak"])
    duration, drive = spec["drive"]["duration_s"], ctx["drive"]
    common = dict(duration_s=duration, strain_bound=rep["max_axial_strain"],
                  temperature_step_k=rep["max_temperature_step_k"], fractions=ctx["heat"]["heat_fractions"], policy=pol)

    def call(**kw):
        return evolve(kw.pop("base", base), kw.pop("thermal", thermal), ctx["law"], kw.pop("kappa0", kappa0),
                      kw.pop("drive", drive), **dict(common, **kw))
    for n in (0, 257, 2.):
        expect("steps_%r" % (n,), lambda n=n: call(steps=n))
    stale = copy.deepcopy(key[0])
    stale[0]["temperature_k"] = [t+1e-9 for t in stale[0]["temperature_k"]]
    thick = [layer["thickness_m"] for layer in ctx["weak"]["layers"]]
    dens = [layer["density_kg_m3"] for layer in ctx["weak"]["layers"]]
    other, _ = weakening.base_prepare(ctx["weak"], order=r["order"], offset_k=1.)
    for name, kw in (
            ("strain_allowance", dict(strain_bound=.051)), ("guard_above_ceiling", dict(temperature_step_k=6.)),
            ("untyped_drive", dict(drive=(drive.force_n_m, drive.drag_pa_s, drive.width_m))),
            ("amplified_heat", dict(fractions=(1.5, 1.))), ("theta_shape", dict(theta0=np.zeros(3))),
            ("nonpositive_temperature", dict(theta0=-np.asarray(thermal.steady_k))),
            ("negative_history", dict(kappa0=-kappa0)), ("warm_start_flag", dict(warm_start=1)),
            ("thermal_for_other_column", dict(base=other)),
            ("temperature_prepared_as_base", dict(base=heat.ArrheniusUpdate.of(base).at(np.array(thermal.steady_k)))),
            ("stale_preparation", dict(inputs=(stale, *key[1:]))),
            ("propagator_other_step", dict(propagator=heat.prepare_propagator(thermal, duration))),
            ("provider_other_step", dict(provider=lambda: heat.prepare_propagator(thermal, duration)))):
        expect(name, lambda kw=kw: call(steps=2, **kw))
    expect("zero_drag", lambda: motion.Drive(drive.force_n_m, 0., drive.width_m))
    foreign = heat.prepare_thermal(*heat.geometry(thick[::-1], r["order"]), thick[::-1], ctx["heat"]["thermal_layers"],
                                   dens, ctx["heat"]["boundaries"], mechanical_fingerprint=base.fingerprint)
    expect("support_same_size_foreign", lambda: call(steps=2, thermal=foreign))
    moved = dataclasses.replace(thermal, depth_m=weakening.frozen(thermal.depth_m+1.))
    expect("support_replaced_copy", lambda: call(steps=2, thermal=moved))
    tiny, tiny_thermal = compressive_column(ctx, r["compressive_volume_m3_mol"])
    squeeze = motion.Drive(-drive.force_n_m, drive.drag_pa_s, drive.width_m)
    expect("compressive_nonmonotone_creep", lambda: call(steps=2, base=tiny, thermal=tiny_thermal,
                                                         kappa0=np.zeros(tiny.size), drive=squeeze))
    # Atomic refusals: the returned prefix equals an independent run of exactly the accepted steps.
    step = r["strain_step_duration_s"]
    first = call(steps=1, duration_s=step, deadline=deadline)
    strained = call(steps=r["strain_steps"], duration_s=step*r["strain_steps"],
                    strain_bound=r["strain_bound_factor"]*abs(first["strain"]), deadline=deadline)
    hot = call(steps=r["temperature_steps"], temperature_step_k=r["temperature_guard_k"], deadline=deadline)
    probe = CountdownDeadline(10**9)
    call(steps=r["deadline_steps"], deadline=probe)
    cut = call(steps=r["deadline_steps"], deadline=CountdownDeadline((10**9-probe.remaining)//2))
    k = cut["accepted_steps"]
    prefix = call(steps=k, duration_s=duration/r["deadline_steps"]*k, deadline=deadline) if k else None
    try:
        call(steps=2, deadline=0.)
        expired_start_raises = False
    except RuntimeError:
        expired_start_raises = True
    checks = {("refuse_"+name): value for name, value in refused.items()}
    checks.update(
        small_strain_atomic=strained["status"] == "REFUSED_SMALL_STRAIN" and same_prefix(strained, first)
        and abs(strained["strain"]) <= rep["max_axial_strain"],
        temperature_step_atomic=hot["status"] == "REFUSED_TEMPERATURE_STEP" and hot["accepted_steps"] == 0
        and not np.any(hot["theta"]) and np.array_equal(hot["kappa"], kappa0) and hot["strain"] == 0
        and all(value == 0 for value in hot["accounts"].values()),
        deadline_atomic=cut["status"] == "REFUSED_DEADLINE" and 0 < k < r["deadline_steps"]
        and prefix is not None and same_prefix(cut, prefix),
        expired_budget_before_first_balance_raises=expired_start_raises,
        refused_prefix_accounts_close=strained["accounts"]["energy_relative"] <= pol["energy_relative"]
        and cut["accounts"]["energy_relative"] <= pol["energy_relative"])
    return verdict(checks, refused_cases=sorted(refused), accepted_before_strain_refusal=strained["accepted_steps"],
                   accepted_before_deadline_refusal=k, deadline_checks_probe=10**9-probe.remaining)


def reuse_control(spec, ctx, deadline=None):
    """One matched comparison: warm guesses and one prepared propagator versus cold starts and a rebuilt one."""
    pol, camp = spec["policy"], spec["campaign"]
    base, thermal, key = layered(ctx, camp["reference_order"])
    n = camp["reference_steps"]
    dt = spec["drive"]["duration_s"]/n
    begin = time.perf_counter()
    warm = run(spec, ctx, base, thermal, key, steps=n, propagator=heat.prepare_propagator(thermal, dt), deadline=deadline)
    warm_seconds = time.perf_counter()-begin
    begin = time.perf_counter()
    cold = run(spec, ctx, base, thermal, key, steps=n, warm_start=False,
               provider=lambda: heat.prepare_propagator(thermal, dt), deadline=deadline)
    cold_seconds = time.perf_counter()-begin
    parity = max(relative_change(warm["velocity_end_m_s"], cold["velocity_end_m_s"]),
                 relative_change(warm["strain"], cold["strain"]),
                 float(np.abs(warm["theta"]-cold["theta"]).max())/max(float(np.abs(cold["theta"]).max()), TINY),
                 float(np.abs(warm["kappa"]-cold["kappa"]).max()),
                 relative_change(warm["accounts"]["heat_j_m2"], cold["accounts"]["heat_j_m2"]),
                 relative_change(warm["accounts"]["drive_work_j_m"], cold["accounts"]["drive_work_j_m"]))
    gates = all(r["status"] == "COMPLETE" and r["max_force_relative"] <= pol["force_relative"]
                and r["accounts"]["energy_relative"] <= pol["energy_relative"]
                and r["accounts"]["motion_work_relative"] <= pol["work_relative"] for r in (warm, cold))
    return verdict(dict(parity=parity <= pol["parity_relative"], same_gates=gates),
                   warm_prepared_seconds=warm_seconds, cold_rebuilt_seconds=cold_seconds,
                   saved_seconds=cold_seconds-warm_seconds, saved_percent=100*(cold_seconds-warm_seconds)/cold_seconds,
                   parity_relative=parity, warm_evaluations=warm["evaluations"], cold_evaluations=cold["evaluations"],
                   warm_iterations=warm["iterations"], cold_iterations=cold["iterations"],
                   scope="one matched reference evolution after the other controls; warm root/stress guesses and one "
                         "propagator versus cold roots and a propagator rebuilt every accepted step; temperature-"
                         "dependent creep terms rebuilt at every stage in both; not a generator or world forecast")


CONTROLS = (("limits", limits_control), ("homogeneous", homogeneous_control), ("feedback", feedback_control),
            ("states", states_control), ("refusal", refusal_control), ("reuse", reuse_control))


# ----------------------------------------------------------------------------- evidence

def bindings():
    names = NEW_FILES+RETAINED+tuple(ACCEPTED_RECEIPTS)
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def evidence_match(current):
    """Accepted receipts must be the declared bytes; retained sources must equal what those receipts bound."""
    receipts = {name: current[name] == digest for name, digest in ACCEPTED_RECEIPTS.items()}
    recorded = [json.loads((ROOT/name).read_text(encoding="utf-8"))["source_sha256"] for name in ACCEPTED_RECEIPTS]
    retained = {}
    for name in RETAINED:
        seen = [r[name] for r in recorded if name in r]
        retained[name] = bool(seen) and all(digest == current[name] for digest in seen)
    imported = {name: Path(module.__file__).resolve() == (ROOT/name).resolve() for name, module in IMPORTED.items()}
    return dict(receipts=receipts, retained=retained, imported=imported)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream, threadpool_limits(limits=1, user_api="blas"):
        result = dict(schema="atlas.i01-thermomechanical-motion-evidence.v1", status="INCOMPLETE",
                      scientific_acceptance=False,
                      runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                                   threadpoolctl=threadpoolctl.__version__, system=platform.system(),
                                   machine=platform.machine(), blas_threads=1),
                      controls={})
        start = time.perf_counter()
        try:
            before = bindings()
            match = evidence_match(before)
            result.update(source_sha256=before, evidence_match=match)
            spec, ctx = load_case()
            result["case"] = spec
            deadline = time.perf_counter()+spec["policy"]["maximum_seconds"]
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
            matched = all(all(group.values()) for group in match.values())
            passed = (result["source_unchanged"] and matched
                      and all(c["status"] == "PASS" for c in result["controls"].values()))
            result["status"] = PASS if passed else "FAIL"
        except Exception as exc:
            # Deliberately do not publish arbitrary exception paths or tracebacks.
            result.update(status="FAIL", error_type=type(exc).__name__)
            if isinstance(exc, (ValueError, RuntimeError)):
                result["error"] = str(exc).replace(str(ROOT), "TECTONICS_ROOT")
        result["elapsed_seconds_after_imports"] = time.perf_counter()-start
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result.get(key) for key in ("status", "elapsed_seconds_after_imports", "error")}
                     | {"controls": {k: v["status"] for k, v in result["controls"].items()}}))
    return 0 if result["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
