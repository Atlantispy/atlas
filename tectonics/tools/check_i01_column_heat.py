"""I01 layered-column conduction and dissipation feeding evolving strength, WORKING NON-CANON.

Fixed-geometry, small-strain, laterally uniform column at a supplied axial rate.
Heat is conducted exactly per step on the mechanical Gauss control volumes;
creep and plastic dissipation are deposited once, and temperature feeds back into
the reviewed creep/plastic/weakening law. No advection, finite strain, rupture or breakup.
I02.2a: thermal support, conduction, Arrhenius update and heat deposition are owned by
atlas_tectonics._integration_heat. This tool re-exports those same objects and keeps its
supplied-rate evolution, analytical oracles, case, campaign and CLI.
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
from threadpoolctl import threadpool_limits

from atlas_tectonics import _integration_column, _integration_heat, _integration_weakening
# The package-owned heat connection, re-exported: these are the same objects, not copies.
from atlas_tectonics._integration_heat import (
    R, TOL, UNIT_ROUNDOFF, THERMAL_KEYS, BOUNDARY_TYPES, phi_functions, ThermalColumn, thermal_identity,
    valid_thermal, scalar, validate_thermal_layers, validate_boundaries, width_tolerance, validate_support,
    prepare_thermal, Propagator, prepare_propagator, conduct, ArrheniusUpdate, mechanics, heat_fractions,
    policy_limits, same_support)

import check_i01_weakening as weakening

column = weakening.column
ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT/"cases/i01_column_heat_v1.json"
WEAKENING_RECEIPT = ROOT/"evidence/i01-weakening-r2.json"
SCHEMA = "atlas.i01-column-heat-case.v1"
number, positive = weakening.number, weakening.positive
relative_change, verdict, check_deadline = weakening.relative_change, weakening.verdict, weakening.check_deadline
REPRESENTATION = {
    "geometry": "fixed laterally uniform column; material depth coordinates; small strain; no advection",
    "thermal_support": "one control volume per mechanical Gauss point; widths equal its quadrature weight; interfaces exact",
    "conduction": "conservative one-dimensional finite volume; series interface resistance; constant per-layer properties",
    "time_integration": "exact modal conduction with second-order source quadrature; Heun history; atomic accepted steps",
    "heating": "creep plus plastic dissipation of the reviewed law deposited once; radiogenic heat only in the steady reference",
    "control": "supplied axial rate",
}
REPRESENTATION_LIMITS = {"max_axial_strain", "max_temperature_step_k"}
POLICY_KEYS = {"max_steps", "maximum_seconds", "steady_order_range", "steady_finest_k",
               "flow_relative", "cookbook_temperature_k", "uniform_source_relative", "eigen_order_range",
               "eigen_finest_k", "energy_relative", "work_heat_relative", "oracle_order_range", "oracle_relative",
               "uniform_relative", "time_force_relative", "time_temperature_k",
               "depth_force_relative", "depth_energy_relative", "feedback_depth_relative",
               "coupling_resolution_factor"}


# ----------------------------------------------------------------------------- thermal support

def geometry(thicknesses, order):
    """Kernel/weakening quadrature geometry, reproduced with identical float operations."""
    if type(order) is not int or not 2 <= order <= column.POLICY["max_order"]:
        raise ValueError("quadrature order must be 2..128")
    nodes, weights = np.polynomial.legendre.leggauss(order)
    layer, depth, weight, top = [], [], [], 0.
    for li, h in enumerate(thicknesses):
        h = positive(h, "thickness")
        for node, w in zip(nodes, weights):
            layer.append(li)
            depth.append(top+(float(node)+1)/2*h)
            weight.append(number(float(w)*h/2, "quadrature weight", positive=True))
        top += h
    return np.array(layer), np.array(depth), np.array(weight)


# ----------------------------------------------------------------------------- coupled evolution

def evolve_heat(base, thermal, law, kappa0, *, rate, duration_s, steps, strain_bound, temperature_step_k,
                fractions, policy, feedback=True, theta0=None, propagator=None, provider=None, deadline=None):
    """Supplied-rate evolution of temperature departure theta and raw history kappa.

    Stage values at (T_n, kappa_n) and at the predicted (T_a, kappa_a) drive an exact
    modal conduction step (ETD2) and Heun history. The committed state is re-solved and
    reused as the next first stage. Temperature-dependent creep terms are rebuilt at every
    stage from the kernel expression; nothing temperature dependent is reused.
    """
    if type(base) is not weakening.PreparedColumn or type(thermal) is not ThermalColumn:
        raise ValueError("reviewed mechanical preparation and thermal support required")
    if type(law) is not weakening.WeakeningLaw:
        raise ValueError("typed weakening law required")
    if thermal.mechanical_fingerprint != base.fingerprint:
        raise ValueError("thermal support was prepared for a different mechanical column")
    if not same_support(thermal, base):                     # a matching label is not evidence of equal support
        raise ValueError("thermal preparation or reference density differs from the mechanical quadrature")
    policy_limits(policy)
    if type(steps) is not int or not 1 <= steps <= policy["max_steps"]:
        raise ValueError("accepted steps must be an integer in 1..256")
    bound = weakening.strain_limit(strain_bound)
    limit = positive(temperature_step_k, "temperature step guard")
    if limit > 5.:
        raise ValueError("temperature step guard above the declared 5 K ceiling")
    rate = number(rate, "axial rate")
    if rate == 0:
        raise ValueError("a nonzero supplied axial rate is required")
    duration = positive(duration_s, "duration")
    fractions = heat_fractions(fractions)
    law.certify(base)
    kappa0 = weakening.history_array(base, kappa0).copy()
    theta = np.zeros(base.size) if theta0 is None else np.asarray(theta0, dtype=float).copy()
    if theta.shape != (base.size,) or not np.all(np.isfinite(theta)):
        raise ValueError("initial temperature departure must be finite, one value per point")
    dt = duration/steps
    prop = prepare_propagator(thermal, dt) if propagator is None else propagator
    if type(prop) is not Propagator or prop.fingerprint != thermal.fingerprint or prop.dt != dt:
        raise ValueError("conduction propagator prepared for different support or step")
    arrhenius = ArrheniusUpdate.of(base)
    fixed = arrhenius.at(thermal.steady_k+theta)
    state = (lambda th: arrhenius.at(thermal.steady_k+th)) if feedback else (lambda th: fixed)
    kappa, strain = kappa0.copy(), 0.

    def stage(th, k, previous):
        return mechanics(state(th), law, k, rate, None if previous is None else previous["x"], fractions)

    current = stage(theta, kappa, None)
    first, accepted, status = current, 0, "COMPLETE"
    acc = dict(external_work_j_m2=0., creep_work_j_m2=0., plastic_work_j_m2=0., heat_j_m2=0., stored_j_m2=0.,
               surface_loss_j_m2=0., base_gain_j_m2=0., thermal_change_j_m2=0.)
    worst_energy, worst_step, stages, iterations = 0., 0., 1, current["iterations"]
    yield_stages = (current["plastic_rate"] > 0).astype(int)
    g_top, g_bot = thermal.boundary_conductance
    for _ in range(steps):
        check_deadline(deadline)
        p = prop if provider is None else provider()
        if type(p) is not Propagator or p.fingerprint != thermal.fingerprint or p.dt != dt:
            raise ValueError("replacement propagator changed the support or step")
        theta_a, _ = conduct(p, theta, current["source"])
        predictor = stage(theta_a, kappa+dt*current["kdot"], current)
        new_theta, integral = conduct(p, theta, current["source"], predictor["source"])
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
        heat = dt*(current["heat"]+predictor["heat"])/2
        surface = g_top*integral[0]              # perturbation heat leaving at the surface
        base_in = -g_bot*integral[-1]            # perturbation heat entering at the base
        change = math.fsum(thermal.capacity*(new_theta-theta))
        worst_energy = max(worst_energy, abs(change-(heat-surface+base_in))
                           / max(abs(heat)+abs(surface)+abs(base_in), 1e-300))
        for key, value in (("external_work_j_m2", dt*(current["work"]+predictor["work"])/2),
                           ("creep_work_j_m2", dt*(current["creep_work"]+predictor["creep_work"])/2),
                           ("plastic_work_j_m2", dt*(current["plastic_work"]+predictor["plastic_work"])/2),
                           ("heat_j_m2", heat), ("stored_j_m2", dt*(current["stored"]+predictor["stored"])/2),
                           ("surface_loss_j_m2", surface), ("base_gain_j_m2", base_in), ("thermal_change_j_m2", change)):
            acc[key] += value
        theta, kappa, strain = new_theta, new_kappa, new_strain
        worst_step = max(worst_step, jump)
        accepted += 1
        current = stage(theta, kappa, predictor)
        yield_stages += (predictor["plastic_rate"] > 0).astype(int)+(current["plastic_rate"] > 0).astype(int)
        stages += 2
        iterations += predictor["iterations"]+current["iterations"]
    total = acc["heat_j_m2"]-acc["surface_loss_j_m2"]+acc["base_gain_j_m2"]
    scale = abs(acc["heat_j_m2"])+abs(acc["surface_loss_j_m2"])+abs(acc["base_gain_j_m2"])
    acc["energy_relative"] = abs(acc["thermal_change_j_m2"]-total)/scale if scale else 0.
    acc["partition_relative"] = (abs(acc["creep_work_j_m2"]+acc["plastic_work_j_m2"]-acc["external_work_j_m2"])
                                 / acc["external_work_j_m2"] if acc["external_work_j_m2"] else 0.)
    ideal = fractions[0]*acc["creep_work_j_m2"]+fractions[1]*acc["plastic_work_j_m2"]
    acc["work_to_heat_relative"] = abs(acc["heat_j_m2"]-ideal)/ideal if ideal else 0.
    return dict(status=status, accepted_steps=accepted, strain=strain, theta=theta, kappa=kappa, kappa0=kappa0,
                force_start=first["force"], force_end=current["force"], accounts=acc,
                max_step_energy_relative=worst_energy, max_temperature_step_k=worst_step,
                stages=stages, scalar_iterations=int(iterations), final=current,
                yield_switching_points=int(np.count_nonzero((yield_stages > 0) & (yield_stages < stages))))


# ----------------------------------------------------------------------------- analytic oracles

def layered_steady(thicknesses, props, boundaries):
    """Continuous steady solution k T'' + A = 0 with flux continuity; T linear in surface flow."""
    ts, tb = validate_boundaries(boundaries)
    if ts is None or tb is None:
        raise ValueError("analytic layered reference uses two fixed temperatures")

    def run(q0):
        t, q, rows = ts, q0, []
        for h, p in zip(thicknesses, props):
            k, a = p["conductivity_w_m_k"], p["radiogenic_w_m3"]
            rows.append((t, q, k, a))
            t, q = t+q/k*h-a*h*h/(2*k), q-a*h
        return t, rows

    t0, _ = run(0.)
    t1, _ = run(1.)
    q0 = (tb-t0)/(t1-t0)
    _, rows = run(q0)
    tops = np.concatenate([[0.], np.cumsum(thicknesses)])

    def temperature(z, li):
        t, q, k, a = rows[li]
        d = z-tops[li]
        return t+q/k*d-a*d*d/(2*k)
    return dict(surface_flow=q0, interface_temperature=[r[0] for r in rows[1:]],
                interface_flow=[r[1] for r in rows[1:]], base_flow=rows[-1][1]-rows[-1][3]*thicknesses[-1],
                temperature=temperature)


def two_layer_mode(h1, h2, k1, k2, c1, c2):
    """First Dirichlet eigenmode of a two-layer slab with flux continuity (transcendental root)."""
    def f(mu):
        b1, b2 = math.sqrt(mu*c1/k1), math.sqrt(mu*c2/k2)
        return k1*b1*math.cos(b1*h1)*math.sin(b2*h2)+k2*b2*math.sin(b1*h1)*math.cos(b2*h2)
    lo = 1e-6*min(k1/(c1*h1*h1), k2/(c2*h2*h2))
    f_lo = f(lo)
    for _ in range(2000):
        hi = lo*1.02
        if f_lo*f(hi) < 0:
            break
        lo, f_lo = hi, f(hi)
    else:
        raise RuntimeError("eigenvalue bracket not found")
    for _ in range(200):
        mid = .5*(lo+hi)
        if f(lo)*f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    mu = .5*(lo+hi)
    b1, b2 = math.sqrt(mu*c1/k1), math.sqrt(mu*c2/k2)
    return mu, lambda z: np.where(z <= h1, np.sin(b1*z), math.sin(b1*h1)*np.sin(b2*(h1+h2-z))/math.sin(b2*h2))


def homogeneous_oracle(layer, thermal, law, rate, kappa0, duration, fractions):
    """Insulated uniform layer: scalar DOP853 on (T, kappa), kernel re-prepared at every evaluation."""
    mechanisms = tuple(column.Creep(**c) for c in layer["creep"])
    p, pore = layer["mean_pressure_pa"][0], layer["pore_pressure_pa"][0]
    rho_cp = thermal["density_kg_m3"]*thermal["heat_capacity_j_kg_k"]

    def local(t, k):
        lc, lf = weakening.aspect_factors(k, law)
        return column.LocalLaw.prepare(
            mechanisms, t, p, grain_m=layer["grain_m"], cohesion_pa=layer["cohesion_pa"]*lc,
            friction_rad=layer["friction_rad"]*lf, pore_pressure_pa=pore,
            plastic_viscosity_pa_s=layer["plastic_viscosity_pa_s"]).solve(abs(rate))

    def rhs(_t, y):
        r = local(float(y[0]), float(y[1]))
        heat = 2*r["stress_pa"]*(fractions[0]*math.fsum(r["creep_rates_s"])+fractions[1]*r["plastic_rate_s"])
        return [heat/rho_cp, 2*r["plastic_rate_s"]]

    t0 = layer["temperature_k"][0]
    sol = solve_ivp(rhs, (0., duration), [t0, kappa0], method="DOP853", rtol=1e-10, atol=[1e-9, 1e-14])
    if not sol.success:
        raise RuntimeError("scalar oracle failed")
    t_end, k_end = map(float, sol.y[:, -1])
    return dict(temperature_rise=t_end-t0, history_gain=k_end-kappa0,
                force=math.copysign(2*layer["thickness_m"]*local(t_end, k_end)["stress_pa"], rate),
                evaluations=int(sol.nfev), always_yielding=local(t0, kappa0)["plastic_rate_s"] > 0)


def order(errors):
    return weakening.order(errors)


# ----------------------------------------------------------------------------- case

def validate_case(spec):
    fields = {"schema", "status", "scope", "provenance", "representation", "mechanics", "thermal_layers",
              "boundaries", "heat_fractions", "cookbook_constants", "campaign", "policy"}
    if type(spec) is not dict or set(spec) != fields or spec["schema"] != SCHEMA:
        raise ValueError("column-heat case schema or top-level fields mismatch")
    rep = spec["representation"]
    if type(rep) is not dict or set(rep) != set(REPRESENTATION) | REPRESENTATION_LIMITS:
        raise ValueError("representation must declare only the supported column-heat fields")
    for key, text in REPRESENTATION.items():
        if rep[key] != text:
            raise ValueError("only the declared column-heat representation is supported: "+key)
    weakening.strain_limit(rep["max_axial_strain"])
    if not 0 < number(rep["max_temperature_step_k"], "temperature step guard") <= 5:
        raise ValueError("temperature step guard must lie in (0, 5] K")
    mech = spec["mechanics"]
    if type(mech) is not dict or set(mech) != {"weakening_case", "use"}:
        raise ValueError("mechanics must name the reviewed weakening case only")
    if mech["weakening_case"] != "cases/i01_weakening_v1.json":
        raise ValueError("only the reviewed weakening case is admitted")
    weak = weakening.load_case(ROOT/mech["weakening_case"])
    names = [layer["name"] for layer in weak["layers"]]
    validate_thermal_layers(spec["thermal_layers"], names)
    validate_boundaries(spec["boundaries"])
    heat_fractions(spec["heat_fractions"])
    camp = spec["campaign"]
    if type(camp) is not dict or set(camp) != {"reference_order", "reference_steps", "time_steps", "orders",
                                               "steady_orders", "homogeneous", "eigenmode", "uniform_source",
                                               "refusal"}:
        raise ValueError("campaign fields mismatch")
    for n in camp["time_steps"]+[camp["reference_steps"]]+camp["homogeneous"]["steps"]:
        if type(n) is not int or not 1 <= n <= 256:
            raise ValueError("step counts must be integers in 1..256")
    pol = spec["policy"]
    if type(pol) is not dict or set(pol) != POLICY_KEYS or pol["max_steps"] != 256:
        raise ValueError("policy fields mismatch or step ceiling changed")
    return spec, weak


def load_case(path=CASE):
    return validate_case(json.loads(Path(path).read_text(encoding="utf-8")))


def setup(spec, weak, order=None):
    """Reviewed mechanical preparation plus thermal support on the same points."""
    order = spec["campaign"]["reference_order"] if order is None else order
    base, layers = weakening.base_prepare(weak, order=order)
    thicknesses = [layer["thickness_m"] for layer in layers]
    thermal = prepare_thermal(base.layer, base.depth_m, base.weight, thicknesses, spec["thermal_layers"],
                              [layer["density_kg_m3"] for layer in layers], spec["boundaries"],
                              mechanical_fingerprint=base.fingerprint)
    return base, thermal, layers


def coupled_run(spec, weak, base, thermal, *, steps=None, feedback=True, fractions=None, provider=None,
                propagator=None, strain=None, deadline=None):
    camp, rep = weak["campaign"], spec["representation"]
    return evolve_heat(base, thermal, weakening.law_of(weak), weakening.initial_history(base, weak),
                       rate=camp["rate_s"], duration_s=(camp["total_strain"] if strain is None else strain)/camp["rate_s"],
                       steps=spec["campaign"]["reference_steps"] if steps is None else steps,
                       strain_bound=rep["max_axial_strain"], temperature_step_k=rep["max_temperature_step_k"],
                       fractions=spec["heat_fractions"] if fractions is None else fractions, policy=spec["policy"],
                       feedback=feedback, provider=provider, propagator=propagator, deadline=deadline)


def layer_warming(theta, prep):
    """Per layer: maximum departure and its volume mean sum(w theta)/sum(w) over the Gauss control volumes.

    Points cluster towards layer ends, so an unweighted point mean over-weights the edges.
    """
    rows = []
    for li in range(int(prep.layer.max())+1):
        m = prep.layer == li
        rows.append(dict(maximum=float(theta[m].max()),
                         volume_weighted_mean=math.fsum(prep.weight[m]*theta[m])/math.fsum(prep.weight[m])))
    return rows


def summary(out, base):
    theta = out["theta"]
    i = int(np.argmax(theta))
    gain = out["kappa"]-out["kappa0"]
    return dict({k: out[k] for k in ("status", "accepted_steps", "strain", "force_start", "force_end",
                                     "max_step_energy_relative", "max_temperature_step_k", "stages",
                                     "scalar_iterations", "yield_switching_points")},
                accounts=out["accounts"], max_temperature_rise_k=float(theta[i]),
                depth_of_max_rise_km=float(base.depth_m[i]/1e3), min_temperature_change_k=float(theta.min()),
                max_history_gain_by_layer=[float(gain[base.layer == li].max()) for li in range(int(base.layer.max())+1)],
                warming_by_layer_k=layer_warming(theta, base),
                yielding_points_final=int(np.count_nonzero(out["final"]["plastic_rate"] > 0)))


# ----------------------------------------------------------------------------- controls

def adapter_control(spec, weak, deadline=None):
    """Demonstrated equivalence of the new temperature preparation with the retained helpers."""
    base, thermal, layers = setup(spec, weak)
    thick = [layer["thickness_m"] for layer in layers]
    lay, dep, wt = geometry(thick, spec["campaign"]["reference_order"])
    arr = ArrheniusUpdate.of(base)
    same = arr.at(np.array(base.temperature_k))
    law = weakening.law_of(weak)
    kappa = weakening.initial_history(base, weak)
    rate = weak["campaign"]["rate_s"]
    reviewed = weakening.respond(base, law, kappa, rate)
    ours = mechanics(same, law, kappa, rate, None, (1., 1.))
    perturbed = np.array(base.temperature_k)+37.*np.sin(np.arange(base.size))
    moved = arr.at(perturbed)
    kernel_equal = True
    for i in range(base.size):
        mechanisms, grain, eta = base.layer_inputs[int(base.layer[i])]
        law_k = column.LocalLaw.prepare(mechanisms, float(perturbed[i]), float(base.reference_pa[i]), grain_m=grain,
                                        cohesion_pa=float(base.cohesion_pa[i]), friction_rad=float(base.friction_rad[i]),
                                        pore_pressure_pa=float(base.pore_pa[i]), plastic_viscosity_pa_s=eta)
        m = len(mechanisms)
        kernel_equal &= bool(np.array_equal(np.asarray(law_k.log_coefficients), moved.log_c[i, :m]))
        kernel_equal &= bool(np.array_equal(moved.volume_rt[i, :m], [mm.volume_m3_mol/(R*perturbed[i]) for mm in mechanisms]))
    heat_sum = math.fsum(ours["source"])
    checks = dict(
        geometry_bitwise=np.array_equal(lay, base.layer) and np.array_equal(dep, base.depth_m) and np.array_equal(wt, base.weight),
        same_temperature_bitwise=np.array_equal(same.log_c, base.log_c) and np.array_equal(same.volume_rt, base.volume_rt),
        perturbed_matches_kernel_bitwise=kernel_equal,
        new_state_new_fingerprint=moved.fingerprint != same.fingerprint != base.fingerprint,
        mechanics_equal_reviewed_respond=all(ours[k] == reviewed[k] for k in ("force", "work", "creep_work", "plastic_work"))
        and np.array_equal(ours["stress"], reviewed["stress"]) and np.array_equal(ours["kdot"], reviewed["kdot"]),
        heat_equals_work=relative_change(heat_sum, ours["work"]) <= spec["policy"]["work_heat_relative"],
        prepared_arrays_immutable=not moved.log_c.flags.writeable and not thermal.capacity.flags.writeable)
    return verdict(checks, points=base.size, heat_minus_work_relative=relative_change(heat_sum, ours["work"]))


def conduction_control(spec, weak, deadline=None):
    pol, camp = spec["policy"], spec["campaign"]
    thick = [layer["thickness_m"] for layer in weak["layers"]]
    dens = [layer["density_kg_m3"] for layer in weak["layers"]]
    ref = layered_steady(thick, spec["thermal_layers"], spec["boundaries"])
    cook = spec["cookbook_constants"]
    errors, flows = [], []
    for q in camp["steady_orders"]:
        lay, dep, wt = geometry(thick, q)
        th = prepare_thermal(lay, dep, wt, thick, spec["thermal_layers"], dens, spec["boundaries"])
        exact = np.array([ref["temperature"](z, int(li)) for z, li in zip(dep, lay)])
        errors.append(float(np.abs(th.steady_k-exact).max()))
        surface, internal, base_flow = th.upward_flows(th.steady_k)
        tops = np.cumsum(thick)[:-1]
        interface = [float(internal[np.argmin(np.abs(th.upper_face_m[:-1]-z))]) for z in tops]
        flows.append(dict(surface=float(surface), interfaces=interface, base=float(base_flow)))
        check_deadline(deadline)
    steady_orders = order(errors)
    f = flows[-1]
    flow_errors = ([relative_change(f["surface"], ref["surface_flow"]), relative_change(f["base"], ref["base_flow"])]
                   + [relative_change(a, b) for a, b in zip(f["interfaces"], ref["interface_flow"])])
    cook_errors = ([abs(ref["surface_flow"]-cook["surface_heat_flow_w_m2"])/cook["surface_heat_flow_w_m2"]]
                   + [abs(a-b)/b for a, b in zip(ref["interface_flow"][:2], cook["interface_heat_flow_w_m2"])])
    cook_t = max(abs(a-b) for a, b in zip(ref["interface_temperature"][:2], cook["interface_temperature_k"]))
    # Insulated uniform source: exact linear rise, independent of step count.
    u = camp["uniform_source"]
    lay, dep, wt = geometry([u["thickness_m"]], u["order"])
    props = [dict(name="uniform", conductivity_w_m_k=u["conductivity_w_m_k"],
                  heat_capacity_j_kg_k=u["heat_capacity_j_kg_k"], radiogenic_w_m3=0.)]
    th = prepare_thermal(lay, dep, wt, [u["thickness_m"]], props, [u["density_kg_m3"]],
                         dict(top=dict(type="insulated"), bottom=dict(type="insulated")),
                         reference_temperature=u["temperature_k"])
    prop = prepare_propagator(th, u["duration_s"]/u["steps"])
    sigma, theta = wt*u["source_w_m3"], np.zeros(wt.size)
    for _ in range(u["steps"]):
        theta, _ = conduct(prop, theta, sigma, sigma)
    rise = u["source_w_m3"]*u["duration_s"]/(u["density_kg_m3"]*u["heat_capacity_j_kg_k"])
    uniform_error = float(np.abs(theta-rise).max()/rise)
    # Zero source leaves the steady reference bitwise.
    zero_new, zero_int = conduct(prop, np.zeros(wt.size), np.zeros(wt.size), np.zeros(wt.size))
    # Two-layer transient eigenmode with different conductivity and capacity.
    em = camp["eigenmode"]
    h1, h2 = em["thickness_m"]
    k1, k2 = em["conductivity_w_m_k"]
    c1, c2 = (d*c for d, c in zip(em["density_kg_m3"], em["heat_capacity_j_kg_k"]))
    mu, mode = two_layer_mode(h1, h2, k1, k2, c1, c2)
    eprops = [dict(name=n, conductivity_w_m_k=k, heat_capacity_j_kg_k=c, radiogenic_w_m3=0.)
              for n, k, c in zip(("a", "b"), em["conductivity_w_m_k"], em["heat_capacity_j_kg_k"])]
    bc = dict(top=dict(type="temperature", value_k=em["boundary_k"]), bottom=dict(type="temperature", value_k=em["boundary_k"]))
    eigen_errors, eigen_energy = [], 0.
    for q in em["orders"]:
        lay, dep, wt = geometry([h1, h2], q)
        th = prepare_thermal(lay, dep, wt, [h1, h2], eprops, em["density_kg_m3"], bc)
        prop = prepare_propagator(th, em["efolds"]/mu/em["steps"])
        theta = em["amplitude_k"]*mode(dep)
        zero = np.zeros(wt.size)
        for _ in range(em["steps"]):
            new, integral = conduct(prop, theta, zero, zero)
            change = math.fsum(th.capacity*(new-theta))
            boundary = -th.boundary_conductance[0]*integral[0]-th.boundary_conductance[1]*integral[-1]
            eigen_energy = max(eigen_energy, abs(change-boundary)/abs(boundary))
            theta = new
        exact = em["amplitude_k"]*mode(dep)*math.exp(-em["efolds"])
        eigen_errors.append(float(np.abs(theta-exact).max()))
    eigen_orders = order(eigen_errors)
    lo, hi = pol["steady_order_range"]
    elo, ehi = pol["eigen_order_range"]
    checks = dict(
        steady_order=all(lo <= o <= hi for o in steady_orders),
        steady_finest=errors[-1] <= pol["steady_finest_k"],
        steady_flows=max(flow_errors) <= pol["flow_relative"],
        cookbook_reproduced=max(cook_errors) <= pol["flow_relative"] and cook_t <= pol["cookbook_temperature_k"],
        insulated_uniform_source=uniform_error <= pol["uniform_source_relative"],
        zero_source_bitwise=not np.any(zero_new) and not np.any(zero_int),
        eigen_order=all(elo <= o <= ehi for o in eigen_orders),
        eigen_finest=eigen_errors[-1] <= pol["eigen_finest_k"],
        eigen_energy=eigen_energy <= pol["energy_relative"])
    return verdict(checks, steady_orders_per_layer=camp["steady_orders"], steady_max_error_k=errors,
                   steady_observed_orders=steady_orders, finest_flows_w_m2=f,
                   analytic=dict(surface_flow=ref["surface_flow"], interface_flow=ref["interface_flow"],
                                 interface_temperature=ref["interface_temperature"], base_flow=ref["base_flow"]),
                   uniform_source_relative_error=uniform_error, eigenvalue_per_s=mu,
                   eigen_orders_per_layer=em["orders"], eigen_max_error_k=eigen_errors,
                   eigen_observed_orders=eigen_orders, eigen_energy_relative=eigen_energy)


def homogeneous_control(spec, weak, deadline=None):
    """Insulated uniform coupled layer versus an independent scalar oracle for T and history."""
    pol, h = spec["policy"], spec["campaign"]["homogeneous"]
    law = weakening.law_of(weak)
    layer = h["layer"]
    base = weakening.prepare([layer], h["order"], closure=weakening.SUPPLIED)
    props = [dict(name=layer["name"], conductivity_w_m_k=h["thermal"]["conductivity_w_m_k"],
                  heat_capacity_j_kg_k=h["thermal"]["heat_capacity_j_kg_k"], radiogenic_w_m3=0.)]
    thermal = prepare_thermal(base.layer, base.depth_m, base.weight, [layer["thickness_m"]], props,
                              [h["thermal"]["density_kg_m3"]], dict(top=dict(type="insulated"), bottom=dict(type="insulated")),
                              reference_temperature=layer["temperature_k"][0], mechanical_fingerprint=base.fingerprint)
    rate = h["rate_s"]
    duration = h["total_strain"]/rate
    fractions = tuple(spec["heat_fractions"])
    oracle = homogeneous_oracle(layer, h["thermal"], law, rate, h["initial_history"], duration, fractions)
    runs = [evolve_heat(base, thermal, law, np.full(base.size, float(h["initial_history"])), rate=rate,
                        duration_s=duration, steps=n, strain_bound=spec["representation"]["max_axial_strain"],
                        temperature_step_k=spec["representation"]["max_temperature_step_k"], fractions=fractions,
                        policy=pol, deadline=deadline) for n in h["steps"]]
    t_err = [relative_change(float(r["theta"][0]), oracle["temperature_rise"]) for r in runs]
    k_err = [relative_change(float(r["kappa"][0]-h["initial_history"]), oracle["history_gain"]) for r in runs]
    f_err = [relative_change(r["force_end"], oracle["force"]) for r in runs]
    spread = max(max(float(np.ptp(r["theta"]))/float(np.abs(r["theta"]).max()),
                     float(np.ptp(r["kappa"]))/float(r["kappa"].max())) for r in runs)
    lo, hi = pol["oracle_order_range"]
    checks = dict(uniform=spread <= pol["uniform_relative"],
                  temperature_order=all(lo <= o <= hi for o in order(t_err)),
                  history_order=all(lo <= o <= hi for o in order(k_err)),
                  finest=max(t_err[-1], k_err[-1], f_err[-1]) <= pol["oracle_relative"],
                  energy=all(r["accounts"]["energy_relative"] <= pol["energy_relative"] for r in runs),
                  insulated_no_boundary_heat=all(r["accounts"]["surface_loss_j_m2"] == 0 and r["accounts"]["base_gain_j_m2"] == 0 for r in runs),
                  work_to_heat=all(r["accounts"]["work_to_heat_relative"] <= pol["work_heat_relative"] for r in runs))
    return verdict(checks, oracle=oracle, steps=h["steps"], temperature_errors=t_err, history_errors=k_err,
                   force_errors=f_err, temperature_orders=order(t_err), history_orders=order(k_err),
                   uniform_relative_spread=spread)


def limits_control(spec, weak, deadline=None):
    """No heating and no feedback reduce exactly to the reviewed fixed-temperature evolution."""
    pol = spec["policy"]
    base, thermal, _ = setup(spec, weak)
    law = weakening.law_of(weak)
    fixed = ArrheniusUpdate.of(base).at(np.array(thermal.steady_k))
    camp = weak["campaign"]
    reviewed = weakening.evolve(fixed, law, weakening.initial_history(base, weak), control="rate", value=camp["rate_s"],
                                duration_s=camp["total_strain"]/camp["rate_s"], steps=spec["campaign"]["reference_steps"],
                                strain_bound=spec["representation"]["max_axial_strain"], policy=weak["policy"],
                                deadline=deadline)
    cold = coupled_run(spec, weak, base, thermal, fractions=(0., 0.), deadline=deadline)
    frozen_t = coupled_run(spec, weak, base, thermal, feedback=False, deadline=deadline)
    same = lambda out: (np.array_equal(out["kappa"], reviewed["kappa"]) and out["force_end"] == reviewed["force_end"]
                        and out["accounts"]["external_work_j_m2"] == reviewed["accounts"]["external_work_j_m2"])
    checks = dict(
        no_heating_temperature_bitwise=not np.any(cold["theta"]),
        no_heating_mechanics_bitwise=same(cold),
        no_heating_stored_all_work=relative_change(cold["accounts"]["stored_j_m2"], cold["accounts"]["external_work_j_m2"]) <= pol["work_heat_relative"],
        no_feedback_mechanics_bitwise=same(frozen_t),
        no_feedback_heats=float(frozen_t["theta"].max()) > 0,
        no_feedback_energy=frozen_t["accounts"]["energy_relative"] <= pol["energy_relative"],
        no_feedback_work_to_heat=frozen_t["accounts"]["work_to_heat_relative"] <= pol["work_heat_relative"])
    return verdict(checks, reviewed_force_end=reviewed["force_end"], no_feedback=summary(frozen_t, base))


def coupled_control(spec, weak, deadline=None):
    """Temperature feedback on the layered case, time/depth refinement and energy accounts."""
    pol, camp = spec["policy"], spec["campaign"]
    base, thermal, _ = setup(spec, weak)
    on = coupled_run(spec, weak, base, thermal, deadline=deadline)
    off = coupled_run(spec, weak, base, thermal, feedback=False, deadline=deadline)
    by_steps, by_order, off_order = {camp["reference_steps"]: on}, {camp["reference_order"]: on}, {camp["reference_order"]: off}
    off_steps = {camp["reference_steps"]: off}
    for n in camp["time_steps"]:
        if n not in by_steps:
            by_steps[n] = coupled_run(spec, weak, base, thermal, steps=n, deadline=deadline)
            off_steps[n] = coupled_run(spec, weak, base, thermal, steps=n, feedback=False, deadline=deadline)
    for q in camp["orders"]:
        if q not in by_order:
            b, t, _ = setup(spec, weak, order=q)
            by_order[q] = coupled_run(spec, weak, b, t, deadline=deadline)
            off_order[q] = coupled_run(spec, weak, b, t, feedback=False, deadline=deadline)
    ts, qs = sorted(by_steps), sorted(by_order)
    time_force = [relative_change(by_steps[a]["force_end"], by_steps[b]["force_end"]) for a, b in zip(ts, ts[1:])]
    time_temp = [float(np.abs(by_steps[a]["theta"]-by_steps[b]["theta"]).max()) for a, b in zip(ts, ts[1:])]
    depth_force = [relative_change(by_order[a]["force_end"], by_order[b]["force_end"]) for a, b in zip(qs, qs[1:])]
    depth_energy = [relative_change(by_order[a]["accounts"]["thermal_change_j_m2"], by_order[b]["accounts"]["thermal_change_j_m2"])
                    for a, b in zip(qs, qs[1:])]
    # Feedback-off mechanics never switch yield state: a smooth reference for the time order.
    smooth_temp = [float(np.abs(off_steps[a]["theta"]-off_steps[b]["theta"]).max()) for a, b in zip(ts, ts[1:])]
    smooth_force = [relative_change(off_steps[a]["force_end"], off_steps[b]["force_end"]) for a, b in zip(ts, ts[1:])]
    feedback = {q: (off_order[q]["force_end"]-by_order[q]["force_end"])/off_order[q]["force_end"] for q in qs}
    fb_depth = relative_change(feedback[qs[-2]], feedback[qs[-1]])
    resolution = max(time_force[-1], depth_force[-1])
    runs = list(by_steps.values())+list(by_order.values())+list(off_order.values())+list(off_steps.values())
    adiabatic = on["accounts"]["heat_j_m2"]
    olo, ohi = pol["oracle_order_range"]
    checks = dict(
        smooth_time_order=all(olo <= o <= ohi for o in order(smooth_temp)+order(smooth_force))
        and all(off_steps[n]["yield_switching_points"] == 0 for n in ts),
        time_force=time_force[-1] <= pol["time_force_relative"],
        time_temperature=time_temp[-1] <= pol["time_temperature_k"],
        depth_force=depth_force[-1] <= pol["depth_force_relative"],
        depth_energy=depth_energy[-1] <= pol["depth_energy_relative"],
        feedback_depth=fb_depth <= pol["feedback_depth_relative"],
        feedback_positive=feedback[camp["reference_order"]] > 0 and float(on["theta"].max()) > 0,
        feedback_resolved=feedback[camp["reference_order"]] >= pol["coupling_resolution_factor"]*resolution,
        energy=all(r["accounts"]["energy_relative"] <= pol["energy_relative"] and r["max_step_energy_relative"] <= pol["energy_relative"] for r in runs),
        work_to_heat=all(r["accounts"]["work_to_heat_relative"] <= pol["work_heat_relative"] for r in runs),
        partition=all(r["accounts"]["partition_relative"] <= pol["energy_relative"] for r in runs),
        all_complete=all(r["status"] == "COMPLETE" for r in runs))
    surface0, _, base0 = thermal.upward_flows(thermal.steady_k)
    surface1, _, base1 = thermal.upward_flows(thermal.steady_k+on["theta"])
    moved = np.flatnonzero((on["final"]["plastic_rate"] > 0) != (off["final"]["plastic_rate"] > 0))
    return verdict(
        checks, feedback_on=summary(on, base), feedback_off=summary(off, base),
        yield_state_changed_by_heat_km=[float(base.depth_m[i]/1e3) for i in moved],
        thermal_force_reduction=feedback, feedback_depth_change=fb_depth,
        time_steps=ts, time_force_changes=time_force, time_temperature_changes_k=time_temp,
        time_observed_order=order(time_force),
        yield_switching_points={n: by_steps[n]["yield_switching_points"] for n in ts},
        smooth_reference=dict(note="feedback off: same steps and heating law, mechanics held at the initial temperature, "
                                   "so no temperature-driven yield switching",
                              force_changes=smooth_force, temperature_changes_k=smooth_temp,
                              force_orders=order(smooth_force), temperature_orders=order(smooth_temp)),
        orders=qs, depth_force_changes=depth_force,
        depth_energy_changes=depth_energy,
        max_rise_by_order_k={q: float(by_order[q]["theta"].max()) for q in qs},
        heat_flows_w_m2=dict(surface_initial=float(surface0), surface_final=float(surface1),
                             base_initial=float(base0), base_final=float(base1)),
        retained_heat_fraction=on["accounts"]["thermal_change_j_m2"]/adiabatic if adiabatic else None)


def refusal_control(spec, weak, deadline=None):
    pol = spec["policy"]
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
            ("advection", ("representation", "advection_velocity_m_s"), 1e-10),
            ("eulerian_geometry", ("representation", "geometry"), "Eulerian finite-strain column"),
            ("strain_bound", ("representation", "max_axial_strain"), .2),
            ("temperature_guard", ("representation", "max_temperature_step_k"), 50.),
            ("force_control", ("representation", "control"), "supplied transmitted force"),
            ("latent_heat", ("thermal_layers", 0, "latent_heat_j_kg"), 3e5),
            ("variable_conductivity", ("thermal_layers", 0, "conductivity_w_m_k"), [2.5, 3e-3]),
            ("zero_conductivity", ("thermal_layers", 1, "conductivity_w_m_k"), 0.),
            ("negative_radiogenic", ("thermal_layers", 0, "radiogenic_w_m3"), -1e-6),
            ("renamed_layer", ("thermal_layers", 2, "name"), "mystery"),
            ("supplied_flux", ("boundaries", "bottom"), dict(type="flux", value_w_m2=.03)),
            ("amplified_heat", ("heat_fractions",), [1.5, 1.]),
            ("other_mechanics", ("mechanics", "weakening_case"), "cases/i01_column_v1.json"),
            ("step_ceiling", ("policy", "max_steps"), 512)):
        expect(name, mutated(path, value))
    base, thermal, layers = setup(spec, weak, order=8)
    law = weakening.law_of(weak)
    kappa0 = weakening.initial_history(base, weak)
    rate = weak["campaign"]["rate_s"]
    common = dict(rate=rate, duration_s=1e12, strain_bound=.05, temperature_step_k=5., fractions=(1., 1.), policy=pol)
    for n in (0, 257, 2.):
        expect("steps_%r" % (n,), lambda n=n: evolve_heat(base, thermal, law, kappa0, steps=n, **common))
    expect("zero_rate", lambda: evolve_heat(base, thermal, law, kappa0, steps=2, **dict(common, rate=0.)))
    expect("guard_above_ceiling", lambda: evolve_heat(base, thermal, law, kappa0, steps=2, **dict(common, temperature_step_k=6.)))
    other, _ = weakening.base_prepare(weak, order=8, offset_k=1.)
    expect("thermal_for_other_column", lambda: evolve_heat(other, thermal, law, kappa0, steps=2, **common))
    prop = prepare_propagator(thermal, 4e11)           # the call below takes 1e12/2 = 5e11 s steps
    expect("propagator_other_step", lambda: evolve_heat(base, thermal, law, kappa0, steps=2, propagator=prop, **common))
    expect("theta_shape", lambda: evolve_heat(base, thermal, law, kappa0, steps=2, theta0=np.zeros(3), **common))
    expect("nonpositive_temperature", lambda: ArrheniusUpdate.of(base).at(np.zeros(base.size)))
    expect("insulated_with_radiogenic", lambda: prepare_thermal(
        base.layer, base.depth_m, base.weight, [l["thickness_m"] for l in layers], spec["thermal_layers"],
        [l["density_kg_m3"] for l in layers], dict(top=dict(type="insulated"), bottom=dict(type="insulated")),
        reference_temperature=1000.))
    thick, dens = [l["thickness_m"] for l in layers], [l["density_kg_m3"] for l in layers]
    expect("support_volume_1pct", lambda: prepare_thermal(
        base.layer, base.depth_m, base.weight*1.01, thick, spec["thermal_layers"], dens, spec["boundaries"],
        mechanical_fingerprint=base.fingerprint))
    foreign = prepare_thermal(*geometry(thick[::-1], 8), thick[::-1], spec["thermal_layers"], dens,
                              spec["boundaries"], mechanical_fingerprint=base.fingerprint)   # valid, same size
    expect("support_same_size_foreign", lambda: evolve_heat(base, foreign, law, kappa0, steps=2, **common))
    moved = dataclasses.replace(thermal, depth_m=weakening.frozen(thermal.depth_m+1.))
    expect("support_replaced_copy", lambda: evolve_heat(base, moved, law, kappa0, steps=2, **common))
    wrong_density = prepare_thermal(base.layer, base.depth_m, base.weight, thick, spec["thermal_layers"],
                                    [rho*1.01 for rho in dens], spec["boundaries"],
                                    mechanical_fingerprint=base.fingerprint)
    expect("thermal_density_1pct", lambda: evolve_heat(base, wrong_density, law, kappa0, steps=2, **common))
    wrong_capacity = dataclasses.replace(thermal, capacity=weakening.frozen(thermal.capacity*1.01))
    expect("derived_capacity_replaced", lambda: evolve_heat(base, wrong_capacity, law, kappa0, steps=2, **common))
    r = spec["campaign"]["refusal"]
    hot = evolve_heat(base, thermal, law, kappa0, rate=r["fast_rate_s"], duration_s=r["strain"]/r["fast_rate_s"],
                      steps=r["steps"], strain_bound=.05, temperature_step_k=5., fractions=(1., 1.), policy=pol)
    strained = coupled_run(spec, weak, base, thermal, steps=r["strain_steps"], strain=r["excess_strain"], deadline=deadline)
    checks = {("refuse_"+k): v for k, v in refused.items()}
    checks.update(
        temperature_step_refused=hot["status"] == "REFUSED_TEMPERATURE_STEP" and hot["accepted_steps"] == 0
        and not np.any(hot["theta"]) and hot["accounts"]["heat_j_m2"] == 0,
        small_strain_refused=strained["status"] == "REFUSED_SMALL_STRAIN" and strained["accepted_steps"] < r["strain_steps"]
        and abs(strained["strain"]) <= spec["representation"]["max_axial_strain"],
        refused_accounts_close=strained["accounts"]["energy_relative"] <= pol["energy_relative"])
    return verdict(checks, refused_cases=sorted(refused), accepted_before_strain_refusal=strained["accepted_steps"])


def reuse_control(spec, weak, deadline=None):
    """One matched comparison: modal conduction prepared once versus rebuilt every accepted step."""
    base, thermal, _ = setup(spec, weak)
    camp = weak["campaign"]
    dt = camp["total_strain"]/camp["rate_s"]/spec["campaign"]["reference_steps"]
    begin = time.perf_counter()
    reused = coupled_run(spec, weak, base, thermal, propagator=prepare_propagator(thermal, dt), deadline=deadline)
    reused_seconds = time.perf_counter()-begin
    begin = time.perf_counter()
    rebuilt = coupled_run(spec, weak, base, thermal, provider=lambda: prepare_propagator(thermal, dt), deadline=deadline)
    rebuilt_seconds = time.perf_counter()-begin
    same = (np.array_equal(reused["theta"], rebuilt["theta"]) and np.array_equal(reused["kappa"], rebuilt["kappa"])
            and reused["force_end"] == rebuilt["force_end"] and reused["accounts"] == rebuilt["accounts"])
    return verdict(dict(bitwise_parity=same), reused_seconds=reused_seconds, rebuilt_seconds=rebuilt_seconds,
                   saved_seconds=rebuilt_seconds-reused_seconds,
                   saved_percent=100*(rebuilt_seconds-reused_seconds)/rebuilt_seconds,
                   scope="one matched reference evolution; eigendecomposition and exponential factors per step versus once; "
                         "temperature-dependent creep terms rebuilt at every stage in both")


CONTROLS = (("adapter", adapter_control), ("conduction", conduction_control), ("homogeneous", homogeneous_control),
            ("limits", limits_control), ("coupled", coupled_control), ("refusal", refusal_control),
            ("reuse", reuse_control))


def bindings():
    # I02.2a: the executed package owners are bound where they were imported from, outside ROOT refusing.
    paths = [Path(__file__), CASE, ROOT/"docs/I01_COLUMN_HEAT.md", ROOT/"tests/test_i01_column_heat.py",
             Path(weakening.__file__), weakening.CASE, ROOT/"docs/I01_WEAKENING.md", ROOT/"tests/test_i01_weakening.py",
             Path(column.__file__), weakening.COLUMN_CASE, weakening.COLUMN_RECEIPT, WEAKENING_RECEIPT,
             Path(_integration_heat.__file__), Path(_integration_weakening.__file__),
             Path(_integration_column.__file__)]
    return {p.resolve().relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def reviewed_helpers(current):
    """Imported helper/case bytes must equal the hashes recorded by the reviewed weakening r2 receipt.

    The package owners of those helpers are compared too: a receipt that never recorded them cannot vouch for them.
    """
    recorded = json.loads(WEAKENING_RECEIPT.read_text(encoding="utf-8"))["source_sha256"]
    names = ("tools/check_i01_weakening.py", "cases/i01_weakening_v1.json", "docs/I01_WEAKENING.md",
             "tests/test_i01_weakening.py", "tools/check_i01_column.py", "cases/i01_column_v1.json",
             "evidence/i01-column-r1.json", "src/atlas_tectonics/_integration_weakening.py",
             "src/atlas_tectonics/_integration_column.py")
    return {name: recorded.get(name) == current[name] for name in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream, threadpool_limits(limits=1, user_api="blas"):
        result = dict(schema="atlas.i01-column-heat-evidence.v1", status="INCOMPLETE", scientific_acceptance=False,
                      runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                                   system=platform.system(), machine=platform.machine(), blas_threads=1),
                      controls={})
        start = time.perf_counter()
        try:
            before = bindings()
            spec, weak = load_case()
            result.update(source_sha256=before, helpers_match_reviewed_weakening_r2=reviewed_helpers(before), spec=spec)
            deadline = time.perf_counter()+spec["policy"]["maximum_seconds"]
            for name, control in CONTROLS:
                begin = time.perf_counter()
                try:
                    data = control(spec, weak, deadline)
                    result["controls"][name] = dict(status="PASS" if data["passed"] else "FAIL",
                                                    seconds=time.perf_counter()-begin, **data)
                except (ValueError, RuntimeError) as exc:
                    result["controls"][name] = dict(status="FAIL", seconds=time.perf_counter()-begin,
                                                    error_type=type(exc).__name__,
                                                    error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
            result["source_unchanged"] = before == bindings()
            passed = (result["source_unchanged"] and all(result["helpers_match_reviewed_weakening_r2"].values())
                      and all(c["status"] == "PASS" for c in result["controls"].values()))
            result["status"] = "PASS_BOUNDED_COLUMN_HEAT_ONLY" if passed else "FAIL"
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
    return 0 if result["status"] == "PASS_BOUNDED_COLUMN_HEAT_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
