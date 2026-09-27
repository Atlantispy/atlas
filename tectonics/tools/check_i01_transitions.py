"""Bounded I01 D6 transition controls, NOT generated breakup, initiation or a world.

SPDX-License-Identifier: AGPL-3.0-only
No native package imports, installs, implicit retries or historical repinning.
Run with the existing scientific Python, -B, --output NEW.json. The declared
cases, parameters and acceptance thresholds below are fixed before collecting
results and must equal cases/i01_transitions_v1.json. Every control is a reduced
analytical or 1D model with authored inputs; none calibrates a planetary law.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform
import sys
import time

import numpy as np
import scipy
from scipy.integrate import quad, solve_ivp
from scipy.optimize import brentq

YEAR_S = 365.25 * 86400.0
MYR_S = 1e6 * YEAR_S
EPS = float(np.finfo(float).eps)
ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases/i01_transitions_v1.json"
DOC = ROOT / "docs/I01_TRANSITIONS.md"
POLICY = {
    "algebra_relative": 1e-11,
    "ode_relative": 1e-9,
    "quadrature_relative": 1e-8,
    "bracket_time_tolerance": 1e-10,
    "unstable_junction_min_relative": 1e-3,
    "melt_fraction_guard": 0.3,
    "scope": "event bracketing and simultaneity, rift decoupling, 1D melt supply, "
             "velocity-space junctions and oblique vectors, slab-inventory forces",
}
PARAMETERS = {
    "bracketing": {"lipschitz": 1.0, "tangency_resolution": 1e-8, "sample_budget": 100000},
    "separation": {"driving_force_N_per_m": 2e12, "basal_drag_Pa_s_per_m": 6.25e14,
                   "plate_width_m": 3.0e6, "rift_viscosity_Pa_s": 1e21,
                   "initial_thickness_m": 1.0e5, "active_width_m": 3.0e4,
                   "decoupling_ratio": 0.01, "follow_on_Myr": 5.0,
                   "cutoffs_m": [1000.0, 100.0, 10.0, 1.0]},
    "supply": {"mantle_density_kg_m3": 3300.0, "gravity_m_s2": 9.81,
               "crust_density_kg_m3": 2900.0, "entropy_change_J_kg_K": 300.0,
               "heat_capacity_J_kg_K": 1200.0, "kelvin_offset_K": 273.0,
               "adiabatic_gradient_K_per_m": 0.0,
               "cases_C_m": [[1300.0, 6000.0], [1300.0, 20000.0], [1300.0, 60000.0],
                             [1350.0, 6000.0], [1350.0, 20000.0]]},
    "migration": {"radius_m": 6371000.0, "junction_lat_lon_deg": [-20.0, 40.0],
                  "omega_deg_per_Myr": {"A": [0.1, -0.3, 0.6], "B": [-0.4, 0.2, 0.1],
                                        "C": [0.3, 0.5, -0.2]},
                  "frame_omega_deg_per_Myr": [0.7, -0.2, 0.4], "trench_rotation_deg": 10.0,
                  "threshold_classifier_deg": 60.0},
    "slab": {"gravity_m_s2": 9.81, "mantle_density_kg_m3": 3300.0, "expansivity_per_K": 3e-5,
             "diffusivity_m2_s": 1e-6, "temperature_drop_K": 1200.0, "plate_thickness_m": 125000.0,
             "ocean_crust_m": 6000.0, "ocean_crust_density_kg_m3": 2900.0,
             "continent_crust_m": 35000.0, "continent_crust_density_kg_m3": 2861.0,
             "transmission_C": 0.25, "resisting_force_N_per_m": 1e12,
             "slab_resistance_Pa_s": 1.1e21, "initial_slab_m": 400000.0,
             "attached_limit_m": 660000.0, "ocean_ahead_m": 300000.0,
             "collision_ages_Myr": [30.0, 80.0], "initiation_ages_Myr": [5.0, 30.0, 80.0, 150.0],
             "initiation_force_N_per_m": 3e12, "handoff_velocity_fraction": 0.01},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def positive(value, name):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return value


def relative(actual, expected):
    actual, expected = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    return float(np.linalg.norm(actual - expected) /
                 max(float(np.linalg.norm(expected)), np.finfo(float).tiny))


def finish(criteria, **data):
    criteria = {name: bool(value) for name, value in criteria.items()}
    return dict(passed=all(criteria.values()), criteria=criteria, **data)


# ---------------------------------------------------------------------------
# Common event bracketing: a trigger law must declare |dg/dt| <= L.
# ---------------------------------------------------------------------------

def first_crossing(g, t0, t1, *, lipschitz, tolerance, resolution, budget):
    """First sign change of trigger g on [t0, t1]; never a silent miss.

    Steps are max(|g|/L, tolerance). The minimum step can cross multiple zeros:
    same-sign endpoints need a Lipschitz exclusion certificate, not a silent miss.
    A local minimum of |g| within `resolution` without a sign change, or a
    budget exhausted while |g| shrinks towards zero, is a tangency the law has
    not resolved: it is refused, never accepted as an event or silently ignored.
    """
    t0, t1 = float(t0), float(t1)
    lipschitz, tolerance = positive(lipschitz, "Lipschitz bound"), positive(tolerance, "time tolerance")
    resolution = positive(resolution, "trigger resolution")
    require(math.isfinite(t0) and math.isfinite(t1) and t1 > t0
            and type(budget) is int and budget > 0, "finite ordered interval and sample budget required")
    samples = 0

    class SampleBudget(Exception):
        pass

    def evaluate(at):
        nonlocal samples
        if samples >= budget:
            raise SampleBudget
        samples += 1
        value = float(g(at))
        require(math.isfinite(value), "trigger must be finite")
        return value

    def exclude_zeros(a, fa, b, fb):
        # A minimum-sized step may be too long for its endpoint cones to
        # exclude two crossings. Subdivide only that uncertain interval;
        # never advance past it on the strength of equal endpoint signs.
        pending = [(a, fa, b, fb)]
        while pending:
            left, fleft, right, fright = pending.pop()
            if abs(fleft)+abs(fright) > lipschitz*(right-left)*(1+8*EPS):
                continue
            middle = left+(right-left)/2
            if not left < middle < right:
                return False
            fmiddle = evaluate(middle)
            if fmiddle == 0 or (fmiddle > 0) != (fleft > 0):
                return False
            pending.append((middle, fmiddle, right, fright))
            pending.append((left, fleft, middle, fmiddle))
        return True

    value = evaluate(t0)
    if value == 0.0:
        return {"status": "DUE_AT_START", "time": t0, "samples": samples}
    t = t0
    while t < t1:
        if samples >= budget:
            return {"status": "UNRESOLVED_BUDGET", "time": t, "samples": samples, "trigger": value}
        nxt = min(t + max(abs(value) / lipschitz, tolerance), t1)
        if nxt <= t:
            return {"status": "UNRESOLVED_TIME_RESOLUTION", "time": t, "samples": samples}
        new = evaluate(nxt)
        if new == 0.0:
            # A sampled zero alone does not establish the required crossing.
            probe = min(nxt+tolerance, t1)
            if probe <= nxt:
                return {"status": "UNRESOLVED_ENDPOINT_ZERO", "time": nxt, "samples": samples}
            if samples >= budget:
                return {"status": "UNRESOLVED_BUDGET", "time": nxt, "samples": samples}
            beyond = evaluate(probe)
            if beyond != 0.0 and (beyond > 0) != (value > 0):
                return {"status": "EVENT", "time": nxt, "samples": samples}
            return {"status": "UNRESOLVED_TANGENCY", "time": nxt, "samples": samples}
        if (new > 0) != (value > 0):
            try:
                root = brentq(evaluate, t, nxt, xtol=tolerance, rtol=4 * EPS)
            except SampleBudget:
                return {"status": "UNRESOLVED_BUDGET", "time": t, "samples": samples}
            return {"status": "EVENT", "time": float(root), "samples": samples}
        # For same-sign endpoints, a zero needs at least (|g0|+|g1|)/L
        # total time. Require strict exclusion, including conservative round-off.
        try:
            excluded = exclude_zeros(t, value, nxt, new)
        except SampleBudget:
            return {"status": "UNRESOLVED_BUDGET", "time": t, "samples": samples}
        if not excluded:
            return {"status": "UNRESOLVED_CROSSINGS", "time": t, "samples": samples}
        if abs(value) <= resolution and abs(new) > abs(value):
            return {"status": "UNRESOLVED_TANGENCY", "time": t, "samples": samples}
        t, value = nxt, new
    return {"status": "NO_EVENT", "time": None, "samples": samples}


def bracketing_control():
    p = PARAMETERS["bracketing"]; tol = POLICY["bracket_time_tolerance"]
    kwargs = dict(lipschitz=p["lipschitz"], tolerance=tol, resolution=p["tangency_resolution"],
                  budget=p["sample_budget"])
    double = lambda t: (t - 0.3) * (t - 0.7)
    naive_missed = double(0.0) * double(1.0) > 0      # one-step sign test sees no event
    two_roots = first_crossing(double, 0.0, 1.0, **kwargs)
    monotone = first_crossing(lambda t: math.exp(-t) - 0.5, 0.0, 2.0, **kwargs)
    tangent = first_crossing(lambda t: (t - 0.5) ** 2, 0.0, 1.0, **kwargs)
    at_start = first_crossing(lambda t: t - 0.25, 0.25, 1.0, **kwargs)
    quiet = first_crossing(lambda t: 1.0 + t, 0.0, 1.0, **kwargs)
    criteria = dict(
        naive_single_step_misses_double_crossing=naive_missed,
        safeguard_finds_first_of_two=two_roots["status"] == "EVENT" and abs(two_roots["time"] - 0.3) <= 2 * tol,
        monotone_root=monotone["status"] == "EVENT" and abs(monotone["time"] - math.log(2.0)) <= 2 * tol,
        tangency_refused=tangent["status"].startswith("UNRESOLVED") and abs(tangent["time"] - 0.5) <= 1e-3,
        exact_start_zero_is_previous_interval=at_start["status"] == "DUE_AT_START",
        no_invented_event=quiet["status"] == "NO_EVENT")
    return finish(criteria,
                results=dict(two_roots=two_roots, monotone=monotone, tangent=tangent,
                             at_start=at_start, no_event=quiet),
                limitation="declared-Lipschitz scalar triggers only; production triggers re-integrate from the parent")


# ---------------------------------------------------------------------------
# Simultaneous events: disjoint commute; overlapping are one joint proposal.
# ---------------------------------------------------------------------------

def validate_transaction(transaction):
    debits, credits = transaction["debits"], transaction["credits"]
    values = list(debits.values()) + list(credits.values())
    require(all(math.isfinite(v) and v >= 0 for v in values), "finite nonnegative transfers required")
    require(math.fsum(debits.values()) == math.fsum(credits.values()), "transaction does not balance")


def apply_transaction(stocks, transaction):
    """All-or-nothing debit/credit of named finite accounts; never clips inputs."""
    validate_transaction(transaction)
    require(all(math.isfinite(v) and v >= 0 for v in stocks.values()), "finite nonnegative stocks required")
    debits, credits = transaction["debits"], transaction["credits"]
    result = dict(stocks)
    for name, amount in debits.items():
        require(name in result and amount <= result[name], f"finite account {name} exhausted")
        result[name] -= amount
    for name, amount in credits.items():
        result[name] = result.get(name, 0.0) + amount
    require(all(math.isfinite(v) for v in result.values()), "account overflow")
    return result


def footprint(transaction):
    return set(transaction["debits"]) | set(transaction["credits"])


def commit_simultaneous(stocks, transactions):
    """Events inside one time tolerance. Order may never change the accepted state.

    Disjoint footprints commute and are applied in canonical ID order. Any
    shared account makes the group a single joint proposal: aggregated demands
    either all fit or the whole group is refused atomically. No first-come rule.
    """
    ids = [t["event_id"] for t in transactions]
    require(len(set(ids)) == len(ids), "unique event identities required")
    require(all(math.isfinite(v) and v >= 0 for v in stocks.values()), "finite nonnegative stocks required")
    # Individually invalid transfers must not cancel into a valid aggregate.
    for tx in transactions:
        validate_transaction(tx)
    shared = any(footprint(a) & footprint(b) for a, b in itertools.combinations(transactions, 2))
    if not shared:
        state = dict(stocks)
        for tx in sorted(transactions, key=lambda t: t["event_id"]):
            state = apply_transaction(state, tx)
        return {"status": "COMMITTED_DISJOINT", "state": state}
    joint = {"debits": {}, "credits": {}}
    for side in ("debits", "credits"):
        names = sorted({k for tx in transactions for k in tx[side]})
        joint[side] = {k: math.fsum(tx[side].get(k, 0.0) for tx in transactions) for k in names}
    try:
        return {"status": "COMMITTED_JOINT", "state": apply_transaction(stocks, joint)}
    except ValueError as exc:
        return {"status": "REFUSED_JOINT", "state": dict(stocks), "reason": str(exc)}


def sequential(stocks, transactions):
    """The prohibited method: first-come application, refusing whoever comes late."""
    state, refused = dict(stocks), []
    for tx in transactions:
        try:
            state = apply_transaction(state, tx)
        except ValueError:
            refused.append(tx["event_id"])
    return state, refused


def simultaneity_control():
    stocks = {"source_A": 1.0, "source_B": 1.0, "melt": 1.0}
    e1 = {"event_id": "e1", "debits": {"source_A": 0.25}, "credits": {"slab": 0.25}}
    e2 = {"event_id": "e2", "debits": {"source_B": 0.5}, "credits": {"accretion": 0.5}}
    orders = [commit_simultaneous(stocks, list(p))["state"] for p in itertools.permutations([e1, e2])]
    r1 = {"event_id": "r1", "debits": {"melt": 0.75}, "credits": {"crust_north": 0.75}}
    r2 = {"event_id": "r2", "debits": {"melt": 0.5}, "credits": {"crust_south": 0.5}}
    forward, back = sequential(stocks, [r1, r2]), sequential(stocks, [r2, r1])
    conflict = [commit_simultaneous(stocks, list(p)) for p in itertools.permutations([r1, r2])]
    small = dict(r2, event_id="r3", debits={"melt": 0.25}, credits={"crust_north": 0.25})
    feasible = [commit_simultaneous(stocks, list(p)) for p in itertools.permutations([small, r2])]
    # Cascade: blocking at t=1 stops convergence, so the attached-length trigger
    # (due at t=1.5 on the parent trajectory) must be re-evaluated and never fires.
    horizon, limit = 2.0, 1.5
    parent = {"blocking": 1.0, "attached_limit": limit / 1.0}
    batch = sorted(k for k, t in parent.items() if t <= horizon)     # prohibited method
    state, cascade, pending = {"clock": 0.0, "speed": 1.0, "attached": 0.0}, [], dict(parent)
    while pending:
        name, when = min(pending.items(), key=lambda kv: kv[1])
        if when > horizon:
            break
        state["attached"] += state["speed"] * (when - state["clock"]); state["clock"] = when
        cascade.append(name); del pending[name]
        if name == "blocking":
            state["speed"] = 0.0
        if "attached_limit" in pending:     # re-evaluated from the committed state
            pending["attached_limit"] = (state["clock"] + (limit - state["attached"]) / state["speed"]
                                         if state["speed"] > 0 else math.inf)
    criteria = dict(
        disjoint_orders_identical=orders[0] == orders[1],
        sequential_conflict_is_order_dependent=forward[0] != back[0] and forward[1] != back[1],
        conflict_refused_atomically=all(c["status"] == "REFUSED_JOINT" and c["state"] == stocks for c in conflict),
        feasible_joint_order_free=all(f["status"] == "COMMITTED_JOINT" for f in feasible)
            and feasible[0]["state"] == feasible[1]["state"] and feasible[0]["state"]["melt"] == 0.25,
        cascade_reevaluates_after_commit=cascade == ["blocking"] and batch == ["attached_limit", "blocking"])
    return finish(criteria,
                sequential_outcomes=dict(r1_then_r2=forward[1], r2_then_r1=back[1]),
                joint_refusal_reason=conflict[0].get("reason"), cascade_events=cascade,
                batch_from_parent_events=batch,
                limitation="exact binary accounts and permutation checks; production needs footprint graphs")


# ---------------------------------------------------------------------------
# Continental separation: force-coupled thinning and a decoupling handoff.
# ---------------------------------------------------------------------------

def rift_terms(p):
    return (positive(p["driving_force_N_per_m"], "driving force"),
            positive(p["basal_drag_Pa_s_per_m"], "basal drag") * positive(p["plate_width_m"], "plate width"),
            positive(p["rift_viscosity_Pa_s"], "rift viscosity"),
            positive(p["initial_thickness_m"], "initial thickness"), positive(p["active_width_m"], "active width"))


def rift_velocity(h, p):
    """Per-plate speed from F = D W v + 4 eta h (2v/w): plane-strain Trouton sheet."""
    force, drag, eta, _, width = rift_terms(p)
    return force / (drag + 8.0 * eta * h / width)


def rift_ratio(h, p):
    """Belt resistance divided by far-field resistance (dimensionless)."""
    _, drag, eta, _, width = rift_terms(p)
    return 8.0 * eta * h / (width * drag)


def rift_time(h, p):
    """Exact t(h) for dh/dt = -2 v h / w at fixed active width."""
    force, drag, eta, h0, width = rift_terms(p)
    require(0 < h <= h0, "thickness must lie in (0, h0]")
    return width * drag / (2 * force) * math.log(h0 / h) + 4 * eta / force * (h0 - h)


def separation_control():
    p = PARAMETERS["separation"]; tol = POLICY["ode_relative"]
    force, drag, eta, h0, width = rift_terms(p)
    ratio_c = positive(p["decoupling_ratio"], "decoupling ratio")
    h_c = ratio_c * width * drag / (8.0 * eta)
    exact_event = rift_time(h_c, p)

    def rhs(_, y):
        v = rift_velocity(y[0], p)
        return [-2.0 * v * y[0] / width, v, v * y[0]]

    def decoupled(_, y):
        return rift_ratio(y[0], p) - ratio_c
    decoupled.terminal, decoupled.direction = True, -1
    begin = time.perf_counter()
    solution = solve_ivp(rhs, (0.0, 2.0 * exact_event), [h0, 0.0, 0.0], method="DOP853",
                         rtol=1e-12, atol=[1e-9, 1e-7, 1e-3], events=decoupled)
    ode_seconds = time.perf_counter() - begin
    require(solution.status == 1 and len(solution.t_events[0]) == 1, "decoupling event not located")
    t_event = float(solution.t_events[0][0]); h_e, x_e, exported = solution.y_events[0][0]
    # Closed forms: x=(w/2)ln(h0/h); each side exports (w/2)(h0-h); w h + 2E = w h0.
    errors = dict(event_time=abs(t_event - exact_event) / exact_event,
                  event_thickness=abs(h_e - h_c) / h_c,
                  displacement=abs(x_e - width / 2 * math.log(h0 / h_c)) / (width / 2 * math.log(h0 / h_c)),
                  exported_material=abs(exported - width / 2 * (h0 - h_c)) / (width / 2 * (h0 - h_c)),
                  material_closure=abs(width * h_e + 2 * exported - width * h0) / (width * h0))
    power = []
    for h in (h0, 1e4, h_c):
        v = rift_velocity(h, p); strain_rate = 2 * v / width
        dissipation = 2 * drag * v * v + 4 * eta * strain_rate ** 2 * h * width   # independent integral
        power.append(abs(2 * force * v - dissipation) / (2 * force * v))
    tau = width * drag / (2 * force)
    cutoffs = [float(c) for c in p["cutoffs_m"]]
    cutoff_Myr = [rift_time(c, p) / MYR_S for c in cutoffs]
    decade_steps = [b - a for a, b in zip(cutoff_Myr, cutoff_Myr[1:])]
    v_inf = force / drag
    kinematic_Myr = [width / (2 * v_inf) * math.log(h0 / c) / MYR_S for c in cutoffs]
    zero_drag_Myr = [4 * eta / force * (h0 - c) / MYR_S for c in cutoffs]
    zero_drag_limit = 4 * eta * h0 / force / MYR_S
    # Handoff consistency: switching the belt to a zero-resistance divergent
    # boundary at ratio_c versus continuing the resolved belt for T.
    follow = positive(p["follow_on_Myr"], "follow-on interval") * MYR_S

    def resolved_displacement(h_start, t_start, span):
        h_end = brentq(lambda h: rift_time(h, p) - (t_start + span), 1e-300, h_start,
                       xtol=1e-300, rtol=4 * EPS)
        return width / 2 * math.log(h_start / h_end)
    resolved = resolved_displacement(h_c, exact_event, follow)
    switched = v_inf * follow
    bound = ratio_c / (1 + ratio_c) * switched
    later_c = ratio_c / 10
    h_later = later_c * width * drag / (8 * eta); t_later = rift_time(h_later, p)
    at_common = exact_event + follow
    later_total = (width / 2 * math.log(h_c / h_later)) + v_inf * (at_common - t_later)
    criteria = dict(
        integrator_matches_closed_form=max(errors.values()) <= tol,
        power_balance=max(power) <= POLICY["algebra_relative"],
        thickness_cutoff_times_diverge=all(step >= 0.99 * tau * math.log(10) / MYR_S for step in decade_steps),
        kinematic_mode_has_no_event_time=all(b - a >= 0.99 * width / (2 * v_inf) * math.log(10) / MYR_S
                                             for a, b in zip(kinematic_Myr, kinematic_Myr[1:])),
        zero_drag_idealisation_converges=all(abs(a - zero_drag_limit) > abs(b - zero_drag_limit)
                                             for a, b in zip(zero_drag_Myr, zero_drag_Myr[1:])),
        handoff_error_bounded=0 <= switched - resolved <= bound,
        handoff_choice_error_bounded=abs(later_total - switched) <= bound)
    return finish(criteria, relative_errors=errors,
                power_relative_residuals=power, ode_seconds=ode_seconds,
                decoupling_thickness_m=h_c, decoupling_time_Myr=exact_event / MYR_S,
                crossover_thickness_m=width * drag / (8 * eta),
                drag_limited_speed_m_per_yr=v_inf * YEAR_S,
                at_handoff=dict(active_material_m2_per_m=width * h_c,
                                exported_each_side_m2_per_m=width / 2 * (h0 - h_c),
                                continental_map_width_m=width + 2 * width / 2 * math.log(h0 / h_c),
                                ocean_area_created_m2_per_m=0.0),
                cutoffs_m=cutoffs, cutoff_event_times_Myr=cutoff_Myr,
                kinematic_cutoff_times_Myr=kinematic_Myr, zero_drag_cutoff_times_Myr=zero_drag_Myr,
                zero_drag_rupture_Myr=zero_drag_limit,
                handoff=dict(follow_on_Myr=follow / MYR_S, resolved_displacement_m=resolved,
                             switched_displacement_m=switched, difference_m=switched - resolved,
                             bound_m=bound, later_handoff_difference_m=abs(later_total - switched)),
                refused=dict(kinematic_generated_separation="REFUSED: prescribed velocity supplies no force balance",
                             thickness_cutoff_trigger="REFUSED: event time depends on the cutoff without a limit"),
                limitation="uniform Newtonian active belt at fixed width; no temperature, strain softening or rupture law")


# ---------------------------------------------------------------------------
# Supply after separation: decompression melt or exhumed mantle.
# Katz et al. (2003) anhydrous branch exactly as quoted by Brune et al. (2014).
# ---------------------------------------------------------------------------

def solidus_C(p_GPa):
    return -5.1 * p_GPa ** 2 + 132.9 * p_GPa + 1085.7


def liquidus_C(p_GPa):
    return -3.2 * p_GPa ** 2 + 80.0 * p_GPa + 1475.0


def melt_fraction(t_C, p_GPa):
    ts, tl = solidus_C(p_GPa), liquidus_C(p_GPa)
    require(tl > ts, "solidus must lie below liquidus")
    if t_C <= ts:
        return 0.0
    require(t_C < tl, "temperature beyond the quoted single-branch law")
    return ((t_C - ts) / (tl - ts)) ** 1.5


def latent_state(t0_C, p_GPa, s):
    """T = T0 - X(T) dS (T + 273)/Cp, solved as a monotone root (Brune Methods)."""
    ts = solidus_C(p_GPa)
    if t0_C <= ts:
        return t0_C, 0.0
    factor = s["entropy_change_J_kg_K"] / s["heat_capacity_J_kg_K"]
    offset = s["kelvin_offset_K"]
    t = brentq(lambda x: x - t0_C + melt_fraction(x, p_GPa) * factor * (x + offset), ts, t0_C,
               xtol=1e-12, rtol=4 * EPS)
    return t, melt_fraction(t, p_GPa)


def melt_column(tp_C, lid_m, s):
    """Melt-equivalent thickness H = integral X dz from lid base to solidus depth."""
    rho, g = positive(s["mantle_density_kg_m3"], "mantle density"), positive(s["gravity_m_s2"], "gravity")
    gamma = float(s["adiabatic_gradient_K_per_m"])
    require(math.isfinite(tp_C) and lid_m >= 0 and gamma >= 0, "valid column inputs required")
    pressure = lambda z: rho * g * z / 1e9
    source = lambda z: tp_C + gamma * z
    gap = lambda z: source(z) - solidus_C(pressure(z))
    require(gap(0.0) > 0, "mantle below the surface solidus cannot melt")
    solidus_depth = brentq(gap, 0.0, 400e3, xtol=1e-9, rtol=4 * EPS)
    if lid_m >= solidus_depth:
        return dict(solidus_depth_m=solidus_depth, H_m=0.0, H_quad_m=0.0, H_raw_m=0.0,
                    latent_J_m2=0.0, sensible_J_m2=0.0, max_fraction=0.0)
    fraction = lambda z: latent_state(source(z), pressure(z), s)[1]
    nodes, weights = np.polynomial.legendre.leggauss(400)
    z = lid_m + (solidus_depth - lid_m) * (nodes + 1) / 2
    w = weights * (solidus_depth - lid_m) / 2
    states = [latent_state(source(zi), pressure(zi), s) for zi in z]
    x = np.array([st[1] for st in states]); temp = np.array([st[0] for st in states])
    gauss = float(w @ x)
    adaptive = quad(fraction, lid_m, solidus_depth, epsabs=0.0, epsrel=1e-12, limit=400)[0]
    raw = float(w @ np.array([melt_fraction(source(zi), pressure(zi)) for zi in z]))
    latent = float(w @ (rho * x * s["entropy_change_J_kg_K"] * (temp + s["kelvin_offset_K"])))
    sensible = float(w @ (rho * s["heat_capacity_J_kg_K"] * (np.array([source(zi) for zi in z]) - temp)))
    return dict(solidus_depth_m=solidus_depth, H_m=gauss, H_quad_m=adaptive, H_raw_m=raw,
                latent_J_m2=latent, sensible_J_m2=sensible, max_fraction=float(x.max()))


def supply_control():
    s = PARAMETERS["supply"]; rows = []
    for tp, lid in s["cases_C_m"]:
        col = melt_column(float(tp), float(lid), s)
        rho, rho_c = s["mantle_density_kg_m3"], s["crust_density_kg_m3"]
        processed = rho * max(col["solidus_depth_m"] - lid, 0.0)
        melt = rho * col["H_m"]
        rows.append(dict(potential_C=tp, lid_m=lid, **col, crust_equivalent_m=melt / rho_c,
                         endmember_surface="magmatic_crust" if col["H_m"] > 0 else "exhumed_mantle",
                         accounts_kg_m2=dict(processed_mantle=processed, melt=melt, residue=processed - melt)))
    by = {(r["potential_C"], r["lid_m"]): r for r in rows}
    positive_rows = [r for r in rows if r["H_m"] > 0]
    criteria = dict(
        lid_below_solidus_exhumes_mantle=by[(1300.0, 60000.0)]["H_m"] == 0.0
            and by[(1300.0, 60000.0)]["endmember_surface"] == "exhumed_mantle",
        thicker_lid_less_melt=by[(1300.0, 6000.0)]["H_m"] > by[(1300.0, 20000.0)]["H_m"] > 0,
        hotter_mantle_more_melt=by[(1350.0, 6000.0)]["H_m"] > by[(1300.0, 6000.0)]["H_m"]
            and by[(1350.0, 20000.0)]["H_m"] > by[(1300.0, 20000.0)]["H_m"],
        latent_heat_reduces_melt=all(r["H_m"] < r["H_raw_m"] for r in positive_rows),
        quadrature_agreement=all(abs(r["H_m"] - r["H_quad_m"]) <= POLICY["quadrature_relative"] * r["H_m"]
                                 for r in positive_rows),
        enthalpy_identity=all(abs(r["latent_J_m2"] - r["sensible_J_m2"]) <= 1e-9 * r["sensible_J_m2"]
                              for r in positive_rows),
        single_branch_guard=all(r["max_fraction"] < POLICY["melt_fraction_guard"] for r in rows),
        no_fixed_crust_thickness=len({round(r["crust_equivalent_m"], 3) for r in positive_rows}) == len(positive_rows))
    return finish(criteria, columns=rows,
                reference="Katz et al. 2003 anhydrous solidus/liquidus and X exponent 3/2 as quoted in Brune et al. 2014 Methods",
                limitation="1D column melt inventory and full-extraction crust equivalent, not actual sea-floor supply; lid depth is a D4 input; no hydrous, cpx-out or melt-transport terms")


# ---------------------------------------------------------------------------
# Boundary migration and junction closure in the local tangent plane.
# ---------------------------------------------------------------------------

def tangent_frame(lat_deg, lon_deg, radius):
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    up = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.cross(up, east)
    return radius * up, east, north


def surface_velocity(omega, r, east, north):
    v = np.cross(omega, r)
    return np.array([v @ east, v @ north])


def planar(vector):
    vector = np.asarray(vector, dtype=float)
    require(vector.shape == (2,) and np.isfinite(vector).all(), "finite planar vector required")
    return vector


def perpendicular(vector):
    vector = planar(vector)
    require(0 < np.linalg.norm(vector) < math.inf, "finite nonzero planar vector required")
    return np.array([-vector[1], vector[0]]) / np.linalg.norm(vector)


def boundary_line(kind, strike, v, *, left, right, overriding=None, accretion_fraction=0.5):
    """Constraint n.J = n.c for a junction moving with a boundary (2D velocity plane)."""
    normal = perpendicular(strike)
    v = {side: planar(v[side]) for side in (left, right)}
    if kind == "ridge":
        require(0 <= accretion_fraction <= 1, "accretion partition must lie in [0, 1]")
        point = (1 - accretion_fraction) * v[left] + accretion_fraction * v[right]
    elif kind == "trench":
        require(overriding in (left, right), "trench polarity must name an overriding side")
        point = v[overriding]
    elif kind == "transform":
        slip = v[right] - v[left]
        require(abs(normal @ slip) <= 1e-12 * np.linalg.norm(slip), "transform has normal motion; use full vector")
        point = v[left]
    else:
        raise ValueError("unsupported boundary kind for junction closure")
    return normal, point


def junction(lines):
    a = np.asarray([n for n, _ in lines], dtype=float)
    points = np.asarray([p for _, p in lines], dtype=float)
    require(a.ndim == 2 and a.shape[1] == 2 and points.shape == a.shape
            and np.isfinite(a).all() and np.isfinite(points).all(), "finite planar junction constraints required")
    norms = np.linalg.norm(a, axis=1)
    require(np.all(norms > 0) and np.isfinite(norms).all(), "nonzero junction normals required")
    a = a/norms[:, None]
    origin = points[0]
    centred = points-origin
    b = np.sum(a*centred, axis=1)
    solution, _, rank, _ = np.linalg.lstsq(a, b, rcond=None)
    require(rank == 2, "junction velocity is underdetermined")
    # Both solve and normalisation use relative velocities, not the arbitrary
    # mantle/reference-frame speed. Pairwise diameter is also order independent.
    scale = float(np.max(np.linalg.norm(centred[:, None]-centred[None, :], axis=2)))
    error = float(np.linalg.norm(a @ solution-b))
    residual = error/scale if scale > 0 else (0.0 if error == 0 else math.inf)
    return solution+origin, residual


def decompose(v_left, v_right, normal):
    """Full relative vector: opening along normal, slip along tangent, no discard."""
    normal = -perpendicular(perpendicular(normal))
    tangent = np.array([-normal[1], normal[0]])
    dv = planar(v_right) - planar(v_left)
    return float(dv @ normal), float(dv @ tangent)


def migration_control():
    m = PARAMETERS["migration"]
    r, east, north = tangent_frame(*m["junction_lat_lon_deg"], m["radius_m"])
    scale = math.radians(1.0) / MYR_S
    omega = {k: np.array(w) * scale for k, w in m["omega_deg_per_Myr"].items()}
    v = {k: surface_velocity(w, r, east, north) for k, w in omega.items()}
    ridge = lambda a, b, vel: boundary_line("ridge", perpendicular(vel[b] - vel[a]), vel, left=a, right=b)
    rrr = [ridge("A", "B", v), ridge("B", "C", v), ridge("C", "A", v)]
    j_rrr, res_rrr = junction(rrr)
    radii = [np.linalg.norm(j_rrr - v[k]) for k in "ABC"]
    shift = surface_velocity(np.array(m["frame_omega_deg_per_Myr"]) * scale, r, east, north)
    v2 = {k: vel + shift for k, vel in v.items()}
    j_shift, res_shift = junction([ridge("A", "B", v2), ridge("B", "C", v2), ridge("C", "A", v2)])
    # RTF: orthogonal ridge AB, transform BC, trench CA with A overriding.
    bisector = ridge("A", "B", v)
    transform = boundary_line("transform", v["C"] - v["B"], v, left="B", right="C")
    j_star = np.linalg.solve(np.array([bisector[0], transform[0]]),
                             np.array([bisector[0] @ bisector[1], transform[0] @ transform[1]]))
    strike = j_star - v["A"]
    rtf = [bisector, transform, boundary_line("trench", strike, v, left="C", right="A", overriding="A")]
    j_rtf, res_rtf = junction(rtf)
    angle = math.radians(m["trench_rotation_deg"])
    turned = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]]) @ strike
    _, res_turned = junction([bisector, transform, boundary_line("trench", turned, v, left="C", right="A", overriding="A")])
    ttt = [boundary_line("trench", np.array(s), v, left=a, right=b, overriding=o)
           for s, a, b, o in (((1.0, 0.2), "A", "B", "A"), ((0.3, 1.0), "B", "C", "B"), ((-1.0, 0.7), "C", "A", "C"))]
    _, res_ttt = junction(ttt)
    # Oblique sweep: area uses only the normal component and changes continuously.
    speed = 1.0; angles = np.radians(np.arange(0.0, 90.0 + 0.5, 1.0)); n = np.array([1.0, 0.0])
    comps = [decompose([0.0, 0.0], speed * np.array([math.cos(a), math.sin(a)]), n) for a in angles]
    opening = np.array([c[0] for c in comps]); slip = np.array([c[1] for c in comps])
    threshold = math.radians(m["threshold_classifier_deg"])
    discarded = max(o for o, a in zip(opening, angles) if a > threshold)
    flipped = decompose(speed * np.array([0.6, 0.8]), [0.0, 0.0], -n)
    tol, unstable = POLICY["algebra_relative"], POLICY["unstable_junction_min_relative"]
    criteria = dict(
        rrr_closes_at_circumcentre=res_rrr <= tol and (max(radii) - min(radii)) <= tol * max(radii),
        common_rotation_translates_junction=res_shift <= tol and relative(j_shift, j_rrr + shift) <= tol,
        constructed_rtf_closes=res_rtf <= tol and relative(j_rtf, j_star) <= tol,
        rotated_trench_refused=res_turned >= unstable,
        generic_ttt_refused=res_ttt >= unstable,
        full_vector_preserved=float(np.max(abs(opening ** 2 + slip ** 2 - speed ** 2))) <= 4 * EPS,
        opening_continuous=float(np.max(abs(np.diff(opening)))) <= speed * math.radians(1.0) + 4 * EPS,
        pure_transform_creates_no_area=abs(opening[-1]) <= 4 * EPS,
        threshold_classifier_would_discard_opening=discarded > 0.4 * speed,
        side_convention_invariant=abs(flipped[0] - decompose([0.0, 0.0], speed * np.array([0.6, 0.8]), n)[0]) <= 4 * EPS)
    return finish(criteria,
                residuals=dict(rrr=res_rrr, frame_shifted=res_shift, rtf=res_rtf,
                               rotated_trench=res_turned, ttt=res_ttt),
                junction_velocity_m_per_yr=dict(rrr=(j_rrr * YEAR_S).tolist(), rtf=(j_rtf * YEAR_S).tolist()),
                threshold_discarded_opening_fraction=discarded / speed,
                rules=dict(ridge="normal speed = mean of flanks (declared symmetric accretion)",
                           trench="moves with the overriding plate edge; rollback needs a resolved back-arc",
                           transform="normal speed equals both plates; requires zero normal relative motion"),
                limitation="instantaneous local closure only; junction evolution/reorganisation law not supplied")


# ---------------------------------------------------------------------------
# Slab inventory forces: initiation state and continental arrival.
# ---------------------------------------------------------------------------

def theta_integral(depth, age_s, s):
    """Integral of (Tb-T)/(Tb-Ts) from 0 to depth for the hot-born plate series.

    age None selects the steady linear profile; age 0 is exactly zero (hot-born).
    """
    thick = positive(s["plate_thickness_m"], "plate thickness"); kappa = positive(s["diffusivity_m2_s"], "diffusivity")
    require(0 <= depth <= thick, "integration depth must lie in the plate")
    base = depth - depth * depth / (2 * thick)
    if age_s is None:
        return base
    require(age_s >= 0, "age cannot be negative")
    if age_s == 0:
        return 0.0
    total, n = 0.0, 1
    while True:
        decay = math.exp(-(n * math.pi) ** 2 * kappa * age_s / thick ** 2)
        term = decay * (1 - math.cos(n * math.pi * depth / thick)) / n ** 2
        total += term
        if decay < 1e-18 and n > 2:
            break
        n += 1
        require(n < 200000, "plate series did not converge")
    return base - 2 * thick / math.pi ** 2 * total


def column_excess(age_s, crust_m, crust_density, s):
    """Excess mass per area (kg/m2) of a column over the reference mantle at Tb."""
    rho, alpha, drop = s["mantle_density_kg_m3"], s["expansivity_per_K"], s["temperature_drop_K"]
    thick = s["plate_thickness_m"]
    crust_theta = theta_integral(crust_m, age_s, s)
    mantle_theta = theta_integral(thick, age_s, s) - crust_theta
    return (crust_density - rho) * crust_m + alpha * drop * (crust_density * crust_theta + rho * mantle_theta)


def slab_force(x, excess_ocean, excess_continent, s):
    """C g times excess mass of the attached window of subducted incoming material."""
    lead, limit, ahead = s["initial_slab_m"], s["attached_limit_m"], s["ocean_ahead_m"]
    top, bottom = x, max(-lead, x - limit)
    ocean = max(0.0, min(top, ahead) - bottom)
    continent = max(0.0, top - max(bottom, ahead))
    return s["transmission_C"] * s["gravity_m_s2"] * (excess_ocean * ocean + excess_continent * continent)


def collision_run(age_Myr, s):
    ocean = column_excess(age_Myr * MYR_S, s["ocean_crust_m"], s["ocean_crust_density_kg_m3"], s)
    continent = column_excess(None, s["continent_crust_m"], s["continent_crust_density_kg_m3"], s)
    k, resist = s["slab_resistance_Pa_s"], s["resisting_force_N_per_m"]
    lead, limit, ahead = s["initial_slab_m"], s["attached_limit_m"], s["ocean_ahead_m"]
    a1 = s["transmission_C"] * s["gravity_m_s2"] * ocean
    ac = s["transmission_C"] * s["gravity_m_s2"] * continent
    require(a1 * lead > resist and a1 * limit > resist, "declared initial slab must move")
    # Closed forms per regime: exponential growth, constant speed, exponential stall.
    y0, y1 = a1 * lead - resist, a1 * limit - resist
    t_saturate = k / a1 * math.log(y1 / y0)
    x_saturate = limit - lead
    t_arrive = t_saturate + (ahead - x_saturate) / (y1 / k)
    rate = (a1 - ac) / k
    stall = y1 / (a1 - ac)
    t_handoff = t_arrive + math.log(1 / s["handoff_velocity_fraction"]) / rate
    x_handoff = ahead + stall * (1 - s["handoff_velocity_fraction"])
    require(stall < limit, "continental entry must stay within the attached window")

    def rhs(_, y):
        return [max(slab_force(y[0], ocean, continent, s) - resist, 0.0) / k]

    def events(level):
        def f(_, y):
            return y[0] - level
        f.terminal, f.direction = True, 1
        return f

    def slow(_, y):
        return max(slab_force(y[0], ocean, continent, s) - resist, 0.0) / k - s["handoff_velocity_fraction"] * y1 / k
    slow.terminal, slow.direction = True, -1
    kwargs = dict(method="DOP853", rtol=1e-12, atol=1e-6)
    first = solve_ivp(rhs, (0, 2 * t_arrive), [0.0], events=events(x_saturate), **kwargs)
    second = solve_ivp(rhs, (first.t_events[0][0], 2 * t_arrive), first.y_events[0][0], events=events(ahead), **kwargs)
    third = solve_ivp(rhs, (second.t_events[0][0], 4 * t_handoff), second.y_events[0][0], events=slow, **kwargs)
    numeric = [first.t_events[0][0], second.t_events[0][0], third.t_events[0][0], third.y_events[0][0][0]]
    exact = [t_saturate, t_arrive, t_handoff, x_handoff]
    x = x_handoff
    accounts = dict(ocean_from_incoming_m=ahead, initial_slab_m=lead,
                    attached_ocean_m=limit - (x - ahead), detached_ocean_m=lead + x - limit,
                    subducted_continent_m=x - ahead)
    closure = abs(accounts["attached_ocean_m"] + accounts["detached_ocean_m"] - (lead + ahead)) / (lead + ahead)
    return dict(age_Myr=age_Myr, ocean_excess_kg_m2=ocean, continent_excess_kg_m2=continent,
                event_times_Myr=dict(attached_limit=t_saturate / MYR_S, continental_arrival=t_arrive / MYR_S,
                                     collision_handoff=t_handoff / MYR_S),
                arrival_speed_m_per_yr=y1 / k * YEAR_S, asymptotic_continental_entry_m=stall,
                remaining_after_handoff_m=stall * s["handoff_velocity_fraction"],
                accounts=accounts, account_closure=closure,
                integrator_relative=max(abs(a - b) / abs(b) for a, b in zip(numeric, exact)))


def forced_initiation(age_Myr, duration_factor, s):
    """Prescribed initiation (polarity, geometry, weakness supplied); new slab from x=0."""
    k, resist, forcing = s["slab_resistance_Pa_s"], s["resisting_force_N_per_m"], s["initiation_force_N_per_m"]
    a1 = s["transmission_C"] * s["gravity_m_s2"] * column_excess(age_Myr * MYR_S, s["ocean_crust_m"],
                                                                s["ocean_crust_density_kg_m3"], s)
    require(forcing > resist, "declared forcing must exceed resistance to start")
    if a1 > 0:
        t_star = k / a1 * math.log(forcing / (forcing - resist))
    else:
        t_star = math.inf
    reference = t_star if math.isfinite(t_star) else k / abs(a1) * math.log(forcing / (forcing - resist))
    stop = duration_factor * reference

    def rhs(t, y):
        applied = forcing if t < stop else 0.0
        v = max(applied + a1 * y[0] - resist, 0.0) / k
        return [v, k * v * v]
    run = solve_ivp(rhs, (0.0, stop), [0.0, 0.0], method="DOP853", rtol=1e-12, atol=[1e-6, 1e-3])
    x, dissipated = run.y[:, -1]
    after = max(a1 * x - resist, 0.0) / k
    work = forcing * x + 0.5 * a1 * x * x      # external work + buoyancy work
    balance = abs(work - resist * x - dissipated) / (forcing * x)
    state = "self_sustaining" if a1 * x >= resist else "stalled_incipient_underthrust"
    return dict(age_Myr=age_Myr, forcing_Myr=stop / MYR_S, convergence_m=x, state=state,
                speed_after_forcing_m_per_yr=after * YEAR_S,
                critical_attached_length_m=resist / a1 if a1 > 0 else None,
                work_relative_residual=balance, retained_underthrust_m=x)


def slab_control():
    s = PARAMETERS["slab"]
    neutral = brentq(lambda a: column_excess(a * MYR_S, s["ocean_crust_m"], s["ocean_crust_density_kg_m3"], s),
                     0.1, 100.0, xtol=1e-12)
    small = 1.0 * MYR_S; kappa = s["diffusivity_m2_s"]
    halfspace = abs(theta_integral(s["plate_thickness_m"], small, s) - 2 * math.sqrt(kappa * small / math.pi)) \
        / (2 * math.sqrt(kappa * small / math.pi))
    lengths = {}
    for age in s["initiation_ages_Myr"]:
        excess = column_excess(age * MYR_S, s["ocean_crust_m"], s["ocean_crust_density_kg_m3"], s)
        c = s["transmission_C"] * s["gravity_m_s2"] * excess
        lengths[str(age)] = s["resisting_force_N_per_m"] / c if c > 0 else None
    short, long_ = forced_initiation(80.0, 0.5, s), forced_initiation(80.0, 2.0, s)
    young = forced_initiation(5.0, 2.0, s)
    runs = [collision_run(a, s) for a in s["collision_ages_Myr"]]
    finite = [v for v in lengths.values() if v is not None]
    criteria = dict(
        halfspace_limit=halfspace <= POLICY["algebra_relative"],
        young_ocean_is_buoyant=lengths["5.0"] is None and neutral > 5.0,
        no_universal_initiation_length=all(a > b for a, b in zip(finite, finite[1:])),
        short_forcing_stalls_and_retains=short["state"] == "stalled_incipient_underthrust"
            and short["speed_after_forcing_m_per_yr"] == 0.0 and short["retained_underthrust_m"] > 0,
        long_forcing_self_sustains=long_["state"] == "self_sustaining" and long_["speed_after_forcing_m_per_yr"] > 0,
        convergence_alone_no_slab=young["state"] == "stalled_incipient_underthrust" and young["convergence_m"] > 0,
        work_owned=max(r["work_relative_residual"] for r in (short, long_, young)) <= POLICY["ode_relative"],
        collision_integrator=max(r["integrator_relative"] for r in runs) <= POLICY["ode_relative"],
        collision_accounts=max(r["account_closure"] for r in runs) <= POLICY["algebra_relative"],
        continental_entry_depends_on_inventory=runs[1]["asymptotic_continental_entry_m"]
            > runs[0]["asymptotic_continental_entry_m"] > 0)
    return finish(criteria, neutral_buoyancy_age_Myr=neutral,
                halfspace_relative=halfspace, self_sustaining_attached_length_m=lengths,
                initiation=dict(short=short, long=long_, young=young), collision=runs,
                refused=dict(convergence_label_without_weakness="REFUSED: initiation needs polarity, geometry and weakness",
                             generated_initiation="BLOCKED: resisting-force closure needs resolved D2 elasto-plastic bending"),
                limitation="reduced terminal-velocity balance with declared resistance; no bending, phase change or slab dynamics")


def binding():
    paths = [Path(__file__), CASE, DOC, ROOT / "tests/test_i01_transitions.py"]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


CONTROLS = (("bracketing", bracketing_control), ("simultaneity", simultaneity_control),
            ("separation", separation_control), ("supply", supply_control),
            ("migration", migration_control), ("slab", slab_control))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        result = dict(schema="atlas.i01-transition-controls.v1", status="INCOMPLETE",
                      scientific_acceptance=False, policy=POLICY, cases={},
                      runtime=dict(python=platform.python_version(), numpy=np.__version__,
                                   scipy=scipy.__version__, system=platform.system(), machine=platform.machine()))
        start = time.perf_counter()
        try:
            result["source_sha256"] = binding()
            spec = json.loads(CASE.read_text(encoding="utf-8"))
            require(spec["control_policy"] == POLICY, "case policy and executable differ")
            require(spec["control_parameters"] == PARAMETERS, "case parameters and executable differ")
            for name, run in CONTROLS:
                begin = time.perf_counter()
                try:
                    data = run()
                    result["cases"][name] = dict(status="PASS" if data["passed"] else "FAIL",
                                                 seconds=time.perf_counter() - begin, **data)
                except Exception as exc:
                    result["cases"][name] = dict(status="FAIL", seconds=time.perf_counter() - begin,
                                                 error_type=type(exc).__name__, error=str(exc))
            result["source_unchanged"] = result["source_sha256"] == binding()
            result["status"] = ("PASS_BOUNDED_CONTROLS_ONLY" if result["source_unchanged"] and
                                all(c["status"] == "PASS" for c in result["cases"].values()) else "FAIL")
        except Exception as exc:
            result.update(status="FAIL", error_type=type(exc).__name__,
                          error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
        result["elapsed_seconds"] = time.perf_counter() - start
        json.dump(result, output, indent=2, allow_nan=False); output.write("\n")
    print(json.dumps({"status": result["status"], "elapsed_seconds": result["elapsed_seconds"],
                      "cases": {k: v["status"] for k, v in result["cases"].items()}}))
    return 0 if result["status"] == "PASS_BOUNDED_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    sys.exit(main())
