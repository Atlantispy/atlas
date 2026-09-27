"""I01 D2 bounded 2D equilibrium/localisation probe, outside native production.

SPDX-License-Identifier: AGPL-3.0-only
Odd periodic grids; divergence-free streamfunction; fixed material coordinates,
temperature and confining pressure. No friction-pressure, transport or rupture
acceptance. Native Atlas physics and I01 r1 files are never imported or changed.
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
from scipy.fft import fft2, ifft2, fftfreq
from scipy.sparse.linalg import LinearOperator, cg
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases/i01_fault2d_v1.json"


def finite(value, name):
    out = np.asarray(value, dtype=float)
    if not np.isfinite(out).all():
        raise ValueError(name + " must be finite")
    return out


class PeriodicPlane:
    """g=(2 e_xx,2 e_xy)=G+A chi, where chi=-Laplacian(psi).

    A=(-2 kx ky/k2, (kx2-ky2)/k2), hence A* A=1 on nonzero modes.
    This removes the k^4 conditioning of a bare streamfunction minimisation.
    Zero-mean chi fixes the null mode; no numerical viscosity floor is used.
    """
    def __init__(self, cells, length, ell):
        if type(cells) is not int or not 9 <= cells <= 257 or cells % 2 != 1:
            raise ValueError("9..257 odd cells required; even Nyquist modes unsupported")
        if not (math.isfinite(length) and math.isfinite(ell) and length > 0 and ell > 0):
            raise ValueError("positive finite domain and regularisation length required")
        self.n, self.length, self.ell = cells, length, ell
        k = 2 * np.pi * fftfreq(cells, d=length/cells)
        self.kx, self.ky = np.meshgrid(k, k)
        self.k2 = self.kx**2 + self.ky**2
        safe = self.k2.copy(); safe[0, 0] = 1.
        self.a = np.array([-2*self.kx*self.ky/safe,
                           (self.kx**2-self.ky**2)/safe])
        self.helmholtz = 1/(1+ell**2*self.k2)
        # Periodic cell locations centred on zero; fixed continuous seed on all grids.
        axis = (np.arange(cells)-(cells-1)/2)*length/cells
        self.x, self.y = np.meshgrid(axis, axis)

    def project(self, chi):
        return ifft2(self.a * fft2(chi)).real

    def adjoint(self, tensor):
        return ifft2(np.sum(self.a * fft2(tensor), axis=0)).real

    def smooth(self, raw):
        # Preserve uniform history exactly, without smoothing it back into storage.
        base = float(raw[0, 0])
        return base + ifft2(fft2(raw-base)*self.helmholtz).real


def constitutive(g, strength, eta_v, eta_p):
    """q=2 epsilon_II; q=s/eta_v+<s-Y>/eta_p; kappa_dot=<s-Y>/eta_p.

    Stress vector t=(tau_xx,tau_xy)=s*g/q. t.g is physical dissipation.
    Returned potential has derivative t, with its continuous yielded branch.
    """
    q = np.sqrt(np.sum(g*g, axis=0))
    cutoff = strength/eta_v
    yielded = q > cutoff
    tangent = np.where(yielded, eta_v*eta_p/(eta_v+eta_p), eta_v)
    s = np.where(yielded, (q+strength/eta_p)*eta_v*eta_p/(eta_v+eta_p), eta_v*q)
    direction = np.divide(g, q, out=np.zeros_like(g), where=q > 0)
    b = np.divide(s, q, out=np.full_like(q, eta_v), where=q > 0)
    stress = b*g
    excess = np.maximum(q-cutoff, 0)
    potential = np.where(yielded, .5*strength**2/eta_v + strength*excess
                         + .5*tangent*excess**2, .5*eta_v*q*q)
    plastic = np.maximum(s-strength, 0)/eta_p
    return stress, plastic, tangent, b, direction, potential


def equilibrium(grid, strength, imposed, eta_v, eta_p, policy, initial=None, deadline=None):
    strength, imposed = finite(strength, "strength"), finite(imposed, "imposed strain rate")
    if strength.shape != (grid.n, grid.n) or imposed.shape != (2,) or np.any(strength <= 0):
        raise ValueError("positive matching strength and two imposed components required")
    if not all(math.isfinite(v) and v > 0 for v in (eta_v, eta_p)):
        raise ValueError("positive finite viscosities required")
    chi = np.zeros_like(strength) if initial is None else finite(initial, "initial field").copy()
    if chi.shape != strength.shape:
        raise ValueError("initial field shape mismatch")
    chi -= chi.mean()
    scale = max(float(strength.mean()), eta_v*float(np.linalg.norm(imposed)), 1.)
    cg_total = 0
    for iteration in range(policy["max_newton_iterations"]+1):
        if deadline is not None and time.perf_counter() > deadline:
            raise RuntimeError("bounded control time budget exhausted")
        g = grid.project(chi) + imposed[:, None, None]
        stress, plastic, a, b, direction, potential = constitutive(g, strength, eta_v, eta_p)
        residual = grid.adjoint(stress)
        relative = float(np.linalg.norm(residual)/math.sqrt(residual.size)/scale)
        # The pressure-eliminated physical force is |k| times this residual.
        force = ifft2(1j*np.sqrt(grid.k2)*fft2(residual))
        force_relative = float(np.linalg.norm(force)/math.sqrt(force.size)*grid.ell/scale)
        if relative <= policy["equilibrium_relative"] and force_relative <= policy["projected_force_relative"]:
            break
        if iteration == policy["max_newton_iterations"]:
            raise RuntimeError(f"equilibrium unresolved: residual={relative:.6g}, force={force_relative:.6g}")

        def product(vector):
            field = vector.reshape(chi.shape)
            dg = grid.project(field)
            dt = b*dg + (a-b)*direction*np.sum(direction*dg, axis=0)
            return (grid.adjoint(dt)+field.mean()).ravel()

        operator = LinearOperator((chi.size, chi.size), matvec=product, dtype=float)
        iterations = [0]
        def count(_):
            iterations[0] += 1
            if deadline is not None and time.perf_counter() > deadline:
                raise RuntimeError("bounded control time budget exhausted")
        delta, info = cg(operator, -residual.ravel(), rtol=1e-5, atol=0.,
                         maxiter=policy["max_cg_iterations"], callback=count)
        cg_total += iterations[0]
        if info:
            raise RuntimeError(f"Newton tangent solve failed: cg info={info}")
        delta = delta.reshape(chi.shape); delta -= delta.mean()
        slope, objective = float(np.mean(residual*delta)), float(potential.mean())
        if slope >= 0:
            raise RuntimeError("non-descent Newton direction")
        step = 1.
        for _ in range(policy["max_line_search_halvings"]+1):
            candidate = chi+step*delta
            trial = constitutive(grid.project(candidate)+imposed[:, None, None], strength, eta_v, eta_p)
            if float(trial[-1].mean()) <= objective+1e-4*step*slope+1e-15*max(1., abs(objective)):
                chi = candidate
                break
            step *= .5
        else:
            raise RuntimeError("equilibrium line search failed")
    work = float(np.mean(np.sum(stress*g, axis=0)))
    macro = float(np.dot(np.mean(stress, axis=(1, 2)), imposed))
    work_relative = abs(work-macro)/max(abs(work), 1e-30)
    if work_relative > policy["work_relative"]:
        raise RuntimeError("macroscopic work and local dissipation disagree")
    return dict(chi=chi, stress=stress, plastic=plastic, g=g,
                residual=relative, force_residual=force_relative, work=work,
                work_residual=work_relative, newton=iteration, cg=cg_total)


def initial_strength(grid, params):
    deficit = np.zeros((grid.n, grid.n))
    for (cx, cy), amplitude in zip(params["seed_centres_fraction"], params["seed_relative_amplitudes"], strict=True):
        # Smooth periodic distance, rather than a nearest-image kink.
        dx = grid.length/np.pi*np.sin(np.pi*(grid.x/grid.length-cx))
        dy = grid.length/np.pi*np.sin(np.pi*(grid.y/grid.length-cy))
        deficit += amplitude*np.exp(-(dx*dx+dy*dy)/params["seed_scale_m"]**2)
    return 1-params["strength_deficit_fraction"]*deficit


def evolve(cells, steps, spec, *, turn=False, uniform=False, deadline=None):
    p, policy = spec["parameters"], spec["policy"]
    if type(steps) is not int or not 1 <= steps <= 256:
        raise ValueError("1..256 control increments required")
    grid = PeriodicPlane(cells, p["domain_m"], p["physical_length_m"])
    y0 = np.ones((cells, cells)) if uniform else initial_strength(grid, p)
    imposed = np.array([1., 0.])
    if turn:
        y0 = np.rot90(y0); imposed *= -1
    history = np.zeros_like(y0); chi = None
    dt = p["total_imposed_engineering_strain"]/steps
    maxima = dict(residual=0., force_residual=0., work_residual=0.)
    total_cg, total_newton = 0, 0
    start = time.perf_counter()
    for index in range(steps+1):
        smooth = grid.smooth(history)
        if float(smooth.min()) < -1e-10:
            raise RuntimeError("negative nonlocal history: spectral support unresolved")
        strength = y0*(1-(1-p["residual_strength_fraction"])*np.minimum(smooth/p["critical_plastic_shear"], 1.))
        out = equilibrium(grid, strength, imposed, p["creep_viscosity_scaled"],
                          p["plastic_viscosity_scaled"], policy, initial=chi, deadline=deadline)
        chi = out["chi"]
        total_cg += out["cg"]; total_newton += out["newton"]
        for key in maxima:
            maxima[key] = max(maxima[key], out[key])
        if index < steps:
            history += dt*out["plastic"]
    mean, square = float(history.mean()), float(np.mean(history**2))
    # Participation area measures all bands without selecting/clipping their pixels.
    participation = grid.length**2*mean**2/square if square > 0 else 0.
    metrics = dict(cells=cells, steps=steps, seconds=time.perf_counter()-start,
                   effective_stress_Pa=out["work"]*p["strength_scale_Pa"],
                   participation_area_m2=participation, peak_to_mean=float(history.max()/mean) if mean else 0.,
                   peak_history=float(history.max()), min_history=float(history.min()),
                   mean_history=mean, newton_iterations=total_newton, cg_iterations=total_cg,
                   **{"max_"+key:value for key, value in maxima.items()})
    return metrics, history


def laminate_control(spec):
    """Rotated manufactured laminates: analytical orientation check, not 2D emergence."""
    policy, errors = spec["policy"], []
    grid = PeriodicPlane(65, 1., .05)
    for mx, my in ((5, 0), (4, 3), (3, 4), (0, 5)):
        phase = 2*np.pi*(mx*grid.x+my*grid.y)
        strength = 1+.1*np.cos(phase)
        imposed = np.array([-2*mx*my, mx*mx-my*my], float)/(mx*mx+my*my)
        # eta_v=10, eta_p=1 yields s=20/11 > max(Y): analytic all-yielded branch.
        exact_stress = 20/11
        exact_rate = exact_stress/10 + (exact_stress-strength)
        out = equilibrium(grid, strength, imposed, 10., 1., policy)
        errors.append(dict(wave=[mx, my], stress_relative=float(np.max(abs(out["stress"]-exact_stress*imposed[:, None, None]))/exact_stress),
                           strain_relative=float(np.max(abs(out["g"]-exact_rate*imposed[:, None, None])))))
    return dict(passed=max(max(r["stress_relative"], r["strain_relative"]) for r in errors) <= policy["laminate_relative"], cases=errors)


def differences(coarse, fine):
    return {key:abs(coarse[key]-fine[key])/abs(fine[key])
            for key in ("effective_stress_Pa", "participation_area_m2")}


def campaign(spec):
    policy, plan = spec["policy"], spec["campaign"]
    deadline = time.perf_counter()+policy["maximum_seconds"]
    rows, fields = [], []
    for cells in plan["cells"]:
        row, field = evolve(cells, plan["steps"], spec, deadline=deadline)
        rows.append(row); fields.append(field)
    fine_time, _ = evolve(plan["cells"][1], plan["fine_steps"], spec, deadline=deadline)
    rotated, rotated_field = evolve(plan["cells"][1], plan["steps"], spec, turn=True, deadline=deadline)
    uniform, uniform_field = evolve(33, plan["steps"], spec, uniform=True, deadline=deadline)
    spatial, temporal = differences(rows[-2], rows[-1]), differences(rows[1], fine_time)
    rotation_error = float(np.linalg.norm(rotated_field-np.rot90(fields[1]))/np.linalg.norm(fields[1]))
    checks = dict(mesh=max(spatial.values()) <= policy["mesh_relative"],
                  time=max(temporal.values()) <= policy["time_relative"],
                  right_angle=rotation_error <= policy["right_angle_rotation_relative"],
                  uniform=float(np.ptp(uniform_field)) == 0.,
                  localisation=rows[-1]["peak_to_mean"] > 2.)
    return dict(passed=all(checks.values()), checks=checks, meshes=rows, fine_time=fine_time,
                rotated=rotated, uniform=uniform, mesh_changes=spatial, time_changes=temporal,
                right_angle_history_relative=rotation_error)


def bindings():
    paths = [Path(__file__), CASE, ROOT/"docs/I01_FAULT2D.md"]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    # Small Krylov dot products do not justify nested native worker teams.
    # Scoped to this CLI only, restored on return; library callers own resources.
    with args.output.open("x", encoding="utf-8", newline="\n") as stream, threadpool_limits(limits=1, user_api="blas"):
        result = dict(schema="atlas.i01-fault2d-evidence.v1", status="INCOMPLETE", scientific_acceptance=False,
                      runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, system=platform.system(), blas_threads=1))
        start = time.perf_counter()
        try:
            before = bindings(); spec = json.loads(CASE.read_text(encoding="utf-8"))
            result.update(source_sha256=before, spec=spec, laminate=laminate_control(spec))
            result["campaign"] = campaign(spec)
            result["source_unchanged"] = before == bindings()
            result["status"] = "PASS_BOUNDED_2D_CONTROLS_ONLY" if result["source_unchanged"] and result["laminate"]["passed"] and result["campaign"]["passed"] else "FAIL"
        except Exception as exc:
            result.update(status="FAIL", error_type=type(exc).__name__, error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
        result["elapsed_seconds"] = time.perf_counter()-start
        json.dump(result, stream, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({key:result.get(key) for key in ("status", "elapsed_seconds", "error")}))
    return 0 if result["status"] == "PASS_BOUNDED_2D_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
