"""I01 D2 pressure/temperature coupling controls, outside native production.

SPDX-License-Identifier: AGPL-3.0-only
No change to the bound isothermal probe. Temperature and material history are
supplied snapshots, not advanced here. All mechanics use scaled stress/rate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.fft import fft2, ifft2
from scipy.sparse.linalg import LinearOperator, cg
from threadpoolctl import threadpool_limits

import check_i01_fault2d as base

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases/i01_strength_v1.json"
GAS_CONSTANT = 8.31446261815324  # J mol^-1 K^-1


def positive(value, name, *, zero=False):
    out = base.finite(value, name)
    if np.any(out < 0 if zero else out <= 0):
        raise ValueError(name + " outside positive support")
    return out


def viscosity(temperature, reference, tref, activation):
    """Reference-normalised n=1, fixed-grain-size Arrhenius creep branch.

    No strain-rate floor, viscosity clipping or silently supplied material law.
    This branch has zero activation volume; pressure acts on friction only.
    """
    temperature = positive(temperature, "absolute temperature")
    reference = positive(reference, "reference viscosity")
    tref = positive(tref, "reference absolute temperature")
    activation = positive(activation, "activation energy", zero=True)
    with np.errstate(over="raise", under="raise", invalid="raise", divide="raise"):
        try:
            return positive(reference*np.exp(activation/GAS_CONSTANT*(1/temperature-1/tref)), "viscosity")
        except FloatingPointError as exc:
            raise ValueError("temperature law outside representable support") from exc


def yield_strength(cohesion, reference_pressure, dynamic_pressure, pore_pressure, friction):
    cohesion = positive(cohesion, "cohesion", zero=True)
    reference_pressure = positive(reference_pressure, "reference pressure", zero=True)
    pore_pressure = positive(pore_pressure, "pore pressure", zero=True)
    dynamic_pressure = base.finite(dynamic_pressure, "dynamic pressure")
    if not math.isfinite(friction) or not 0 <= friction < math.pi/2:
        raise ValueError("friction must be radians in [0, pi/2)")
    effective = np.maximum(reference_pressure+dynamic_pressure-pore_pressure, 0.)
    return cohesion*math.cos(friction)+effective*math.sin(friction)


class PressurePlane(base.PeriodicPlane):
    def __init__(self, cells, length, ell):
        super().__init__(cells, length, ell)
        # B perpendicular to A; p_hat=B.t_hat, with the zero mode prescribed.
        self.b = np.array([self.a[1], -self.a[0]])

    def pressure(self, stress):
        result = ifft2(np.sum(self.b*fft2(stress), axis=0)).real
        return result-result.mean()

    def momentum(self, stress, pressure):
        t1, t2 = fft2(stress)
        p = fft2(pressure)
        return np.array([ifft2(1j*(self.kx*(t1-p)+self.ky*t2)).real,
                         ifft2(1j*(self.kx*t2-self.ky*(t1+p))).real])


def rms(value):
    return float(np.sqrt(np.mean(np.asarray(value)**2)))


def budget(deadline):
    if deadline is not None and time.perf_counter() > deadline:
        raise RuntimeError("bounded pressure control time budget exhausted")


def frozen_solve(grid, strength, imposed, eta_v, eta_p, policy, initial, scale, deadline):
    """Convex ONLY at frozen strength. Never apply CG to the coupled law."""
    chi = initial.copy()
    total_cg = 0
    for iteration in range(policy["max_newton_iterations"]+1):
        budget(deadline)
        g = grid.project(chi)+imposed[:, None, None]
        stress, _, a, b, direction, potential = base.constitutive(g, strength, eta_v, eta_p)
        residual = grid.adjoint(stress)
        if rms(residual)/scale <= policy["equilibrium_relative"]:
            return chi, iteration, total_cg
        if iteration == policy["max_newton_iterations"]:
            raise RuntimeError("frozen-strength equilibrium unresolved")

        def product(vector):
            field = vector.reshape(chi.shape)
            dg = grid.project(field)
            dt = b*dg+(a-b)*direction*np.sum(direction*dg, axis=0)
            return (grid.adjoint(dt)+field.mean()).ravel()

        count = [0]
        def callback(_):
            count[0] += 1
            budget(deadline)
        operator = LinearOperator((chi.size, chi.size), matvec=product, dtype=float)
        delta, info = cg(operator, -residual.ravel(), rtol=1e-5, atol=0.,
                         maxiter=policy["max_cg_iterations"], callback=callback)
        total_cg += count[0]
        if info:
            raise RuntimeError("frozen-strength tangent solve unresolved")
        delta = delta.reshape(chi.shape); delta -= delta.mean()
        slope, objective = float(np.mean(residual*delta)), float(potential.mean())
        if slope >= 0:
            raise RuntimeError("non-descent frozen-strength direction")
        step = 1.
        for _ in range(policy["max_line_search_halvings"]+1):
            budget(deadline)
            trial = chi+step*delta
            value = base.constitutive(grid.project(trial)+imposed[:, None, None], strength, eta_v, eta_p)[-1]
            if float(value.mean()) <= objective+1e-4*step*slope+1e-15*max(1., abs(objective)):
                chi = trial
                break
            step *= .5
        else:
            raise RuntimeError("frozen-strength line search unresolved")


def validate_policy(policy):
    for name in ("max_newton_iterations", "max_cg_iterations", "max_line_search_halvings", "max_pressure_iterations"):
        if type(policy[name]) is not int or not 1 <= policy[name] <= 500:
            raise ValueError("invalid iteration policy: "+name)
    for name in ("equilibrium_relative", "pressure_relative", "momentum_relative", "work_relative"):
        if not math.isfinite(policy[name]) or not 0 < policy[name] < 1:
            raise ValueError("invalid residual policy: "+name)
    if not math.isfinite(policy["pressure_relaxation"]) or not 0 < policy["pressure_relaxation"] <= 1:
        raise ValueError("invalid pressure relaxation")


def solve(grid, cohesion, temperature, imposed, params, policy, *, initial=None, deadline=None):
    """Under-relaxed pressure Picard with a verified, internally consistent return.

    The returned p is the pressure USED by the returned strength and stress,
    not a fresh reconstruction paired with stale constitutive data.
    """
    start = time.perf_counter()
    validate_policy(policy)
    shape = (grid.n, grid.n)
    cohesion, temperature = base.finite(cohesion, "cohesion"), base.finite(temperature, "temperature")
    imposed = base.finite(imposed, "imposed engineering rate")
    if cohesion.shape != shape or temperature.shape != shape or imposed.shape != (2,):
        raise ValueError("matching scalar fields and two imposed components required")
    # This local periodic experiment has a uniform reference, not an unbalanced
    # lithostatic gradient or a pressure-dependent activation-volume creep law.
    for name in ("reference_viscosity_scaled", "reference_temperature_K", "activation_energy_J_per_mol",
                 "plastic_viscosity_scaled", "reference_pressure_scaled", "pore_pressure_scaled", "friction_degrees"):
        if np.asarray(params[name]).ndim != 0:
            raise ValueError("uniform scalar material parameter required: "+name)
    eta_v = viscosity(temperature, params["reference_viscosity_scaled"], params["reference_temperature_K"], params["activation_energy_J_per_mol"])
    eta_p = float(positive(params["plastic_viscosity_scaled"], "plastic viscosity"))
    phi = math.radians(params["friction_degrees"])
    pref, pore = params["reference_pressure_scaled"], params["pore_pressure_scaled"]
    p, chi = np.zeros(shape), np.zeros(shape)
    if initial is not None:
        p, chi = (base.finite(initial[key], key).copy() for key in ("pressure", "chi"))
        if p.shape != shape or chi.shape != shape:
            raise ValueError("initial field shape mismatch")
        if abs(float(p.mean())) > 1e-12*max(1., rms(p)):
            raise ValueError("initial dynamic pressure must have zero mean")
        p -= p.mean(); chi -= chi.mean()
    strength = yield_strength(cohesion, pref, p, pore, phi)
    scale = max(1., rms(strength), float(eta_v.mean())*float(np.linalg.norm(imposed)))
    total_newton, total_cg = 0, 0
    for outer in range(policy["max_pressure_iterations"]):
        budget(deadline)
        strength = yield_strength(cohesion, pref, p, pore, phi)
        chi, newton, iterations = frozen_solve(grid, strength, imposed, eta_v, eta_p, policy, chi, scale, deadline)
        total_newton += newton; total_cg += iterations
        g = grid.project(chi)+imposed[:, None, None]
        stress, plastic, *_ = base.constitutive(g, strength, eta_v, eta_p)
        reconstructed = grid.pressure(stress)
        # Unrelaxed residual; arbitrarily small damping cannot manufacture a pass.
        pressure_residual = rms(reconstructed-p)/scale
        force_residual = rms(grid.momentum(stress, p))*grid.ell/scale
        projected_residual = rms(grid.adjoint(stress))/scale
        if (pressure_residual <= policy["pressure_relative"]
                and projected_residual <= policy["equilibrium_relative"]
                and force_residual <= policy["momentum_relative"]):
            work = float(np.mean(np.sum(stress*g, axis=0)))
            macro = float(np.dot(stress.mean(axis=(1, 2)), imposed))
            work_residual = abs(work-macro)/max(abs(work), 1e-30)
            if work_residual > policy["work_relative"]:
                raise RuntimeError("local dissipation and macroscopic work disagree")
            return dict(pressure=p, chi=chi, stress=stress, strength=strength, g=g,
                        plastic=plastic, work=work, work_residual=work_residual,
                        pressure_residual=pressure_residual, momentum_residual=force_residual,
                        projected_residual=projected_residual, pressure_iterations=outer+1,
                        newton_iterations=total_newton, cg_iterations=total_cg,
                        seconds=time.perf_counter()-start)
        p += policy["pressure_relaxation"]*(reconstructed-p)
        p -= p.mean()
    raise RuntimeError(f"pressure feedback unresolved: pressure={pressure_residual:.6g}, momentum={force_residual:.6g}")


def fixture(grid, params):
    phase_x, phase_y = 2*np.pi*grid.x/grid.length, 2*np.pi*grid.y/grid.length
    temperature = params["reference_temperature_K"]+params["temperature_amplitude_K"]*np.cos(phase_x)*np.cos(phase_y)
    history = params["history_amplitude"]*(1+np.cos(phase_x)*np.sin(phase_y))/2
    smoothed = grid.smooth(history)
    cohesion = params["cohesion_scaled"]*(1-(1-params["residual_cohesion_fraction"])*np.minimum(smoothed/params["critical_plastic_shear"], 1.))
    return temperature, cohesion


def manufactured(grid, params, policy, deadline=None):
    """Independent all-yielded one-dimensional oracle WITH dynamic pressure."""
    t = params["reference_temperature_K"]+params["temperature_amplitude_K"]*np.cos(2*np.pi*grid.x/grid.length)
    c = np.full_like(t, params["cohesion_scaled"])
    ev = viscosity(t, params["reference_viscosity_scaled"], params["reference_temperature_K"], params["activation_energy_J_per_mol"])
    ep = params["plastic_viscosity_scaled"]
    alpha = ev/(ev+ep)
    phi = math.radians(params["friction_degrees"])
    y0 = c*math.cos(phi)+(params["reference_pressure_scaled"]-params["pore_pressure_scaled"])*math.sin(phi)
    beta = alpha*math.sin(phi)
    k = ev*ep/(ev+ep)+alpha*y0
    mean_stress = float(np.mean(k/(1-beta))/np.mean(1/(1-beta)))
    exact_p = (k-mean_stress)/(1-beta)
    exact_y = yield_strength(c, params["reference_pressure_scaled"], exact_p, params["pore_pressure_scaled"], phi)
    if not (np.all(ev > exact_y) and np.all(params["reference_pressure_scaled"]+exact_p-params["pore_pressure_scaled"] > 0)):
        raise ValueError("manufactured oracle outside all-yielded positive-confinement branch")
    out = solve(grid, c, t, [1., 0.], params, policy, deadline=deadline)
    error = max(float(np.max(abs(out["pressure"]-exact_p))),
                float(np.max(abs(out["stress"][0]-(exact_p+mean_stress)))))/mean_stress
    return dict(relative_error=error, passed=error <= policy["analytic_relative"], seconds=out["seconds"])


def summary(out, grid, params):
    keys = ("seconds", "pressure_iterations", "newton_iterations", "cg_iterations",
            "work_residual", "pressure_residual", "momentum_residual", "projected_residual")
    return dict(cells=grid.n, stress_work_Pa=out["work"]*params["stress_scale_Pa"],
                dynamic_pressure_rms_Pa=rms(out["pressure"])*params["stress_scale_Pa"],
                plastic_rate_rms_per_s=rms(out["plastic"])*params["rate_scale_per_s"],
                **{key:out[key] for key in keys})


def campaign(spec, report):
    params, policy = spec["parameters"], spec["policy"]
    deadline = time.perf_counter()+policy["maximum_seconds"]
    report["meshes"] = []
    for n in spec["campaign"]["cells"]:
        grid = PressurePlane(n, params["domain_m"], params["physical_length_m"])
        temperature, cohesion = fixture(grid, params)
        out = solve(grid, cohesion, temperature, [1., 0.], params, policy, deadline=deadline)
        report["meshes"].append(summary(out, grid, params))
        if n == spec["campaign"]["cells"][1]:
            middle = (grid, temperature, cohesion, out)
    grid, temperature, cohesion, out = middle
    report["manufactured"] = manufactured(grid, params, policy, deadline)
    changed_t = temperature+params["warm_temperature_change_K"]
    warm = solve(grid, cohesion, changed_t, [1., 0.], params, policy, initial=out, deadline=deadline)
    cold = solve(grid, cohesion, changed_t, [1., 0.], params, policy, deadline=deadline)
    parity = max(rms(warm[k]-cold[k])/max(rms(cold[k]), 1e-30) for k in ("stress", "pressure", "g"))
    report["nearby_temperature_reuse"] = dict(warm=summary(warm, grid, params), cold=summary(cold, grid, params),
        field_relative=parity, saved_seconds=cold["seconds"]-warm["seconds"],
        saved_percent=100*(1-warm["seconds"]/cold["seconds"]))
    coarse, fine = report["meshes"][-2:]
    changes = {key:abs(coarse[key]-fine[key])/abs(fine[key])
               for key in ("stress_work_Pa", "dynamic_pressure_rms_Pa", "plastic_rate_rms_per_s")}
    report["mesh_changes"] = changes
    report["checks"] = dict(mesh=max(changes.values()) <= policy["mesh_relative"],
                            manufactured=report["manufactured"]["passed"],
                            reuse=parity <= policy["warm_parity_relative"])


def bindings():
    paths = [Path(__file__), Path(base.__file__), CASE, ROOT/"docs/I01_STRENGTH.md",
             ROOT/"tests/test_i01_strength.py"]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream, threadpool_limits(limits=1, user_api="blas"):
        result = dict(schema="atlas.i01-strength-evidence.v1", status="INCOMPLETE", scientific_acceptance=False,
                      runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, system=platform.system(), blas_threads=1))
        start = time.perf_counter()
        try:
            before = bindings(); spec = json.loads(CASE.read_text(encoding="utf-8"))
            result.update(source_sha256=before, spec=spec)
            campaign(spec, result)
            result["source_unchanged"] = before == bindings()
            result["status"] = "PASS_BOUNDED_PRESSURE_TEMPERATURE_ONLY" if result["source_unchanged"] and all(result["checks"].values()) else "FAIL"
        except Exception as exc:
            # Deliberately do not publish arbitrary exception paths or tracebacks.
            result.update(status="FAIL", error_type=type(exc).__name__)
            if isinstance(exc, (ValueError, RuntimeError)):
                result["error"] = str(exc)
        result["elapsed_seconds"] = time.perf_counter()-start
        json.dump(result, stream, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({key:result.get(key) for key in ("status", "elapsed_seconds", "error")}))
    return 0 if result["status"] == "PASS_BOUNDED_PRESSURE_TEMPERATURE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
