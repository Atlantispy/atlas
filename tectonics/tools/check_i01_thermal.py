"""I01 bounded thermal and plastic-history evolution, outside native production.

SPDX-License-Identifier: AGPL-3.0-only
Material (reference) coordinates of the small-strain periodic square used by the
reviewed D2 strength/fault helpers, which are imported read-only and bound by
their bytes. The affine mean velocity is a strain-rate input only: no field is
advected by it, and states beyond the declared displacement-gradient bound are
refused. Temperature, raw plastic history and energy accounts follow material
points. No elastic, pore-fluid, healing or large-strain law is represented.
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
from scipy.integrate import solve_ivp
from threadpoolctl import threadpool_limits

import check_i01_strength as strength

base = strength.base
ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases/i01_thermal_v1.json"
SCHEMA = "atlas.i01-thermal-case.v1"
COORDINATES = ("material (reference) coordinates of the periodic square; geometrically linear; "
               "fields attached to material points")
AFFINE_USE = "imposed mean strain-rate input only; never used to advect any field"
TINY = np.finfo(float).tiny


def finite(value, name):
    return base.finite(value, name)


def positive(value, name):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(name + " must be positive and finite")
    return value


def rms(value):
    return float(np.sqrt(np.mean(np.asarray(value)**2)))


def relative_change(value, reference):
    return float(abs(value-reference)/max(abs(reference), TINY))


def verdict(checks, **data):
    checks = {name: bool(value) for name, value in checks.items()}
    return dict(passed=all(checks.values()), checks=checks, **data)


def spectral_resample(field, cells):
    """Trigonometric interpolation from a centred odd grid onto a finer centred odd grid.

    PeriodicPlane centres its samples on zero, so the two array origins differ by
    L(1/cells-1/n)/2; the phase shift aligns them before exact zero padding.
    """
    field = finite(field, "field")
    n = field.shape[0]
    if field.shape != (n, n) or n % 2 != 1 or type(cells) is not int or cells < n or (cells-n) % 2:
        raise ValueError("square odd source and finer odd target grid required")
    modes = np.fft.fftfreq(n, d=1./n)
    phase = np.exp(2j*np.pi*modes*.5*(1/cells-1/n))
    spectrum = np.fft.fftshift(fft2(field)*phase[None, :]*phase[:, None])
    padded = np.pad(spectrum, (cells-n)//2)
    return ifft2(np.fft.ifftshift(padded)).real*(cells/n)**2


def validate_case(spec):
    """Strict schema: no silently supplied elastic, pore-fluid or healing law."""
    fields = {"schema", "scope", "provenance", "representation", "mechanics", "thermal",
              "history", "initial", "campaign", "policy"}
    if type(spec) is not dict or set(spec) != fields or spec["schema"] != SCHEMA:
        raise ValueError("thermal case schema or top-level fields mismatch")
    rep = spec["representation"]
    if type(rep) is not dict or set(rep) != {"coordinates", "affine_mean_velocity", "mean_spin_per_s", "max_displacement_gradient"}:
        raise ValueError("representation must declare coordinates, affine use, spin and strain bound")
    if rep["coordinates"] != COORDINATES or rep["affine_mean_velocity"] != AFFINE_USE:
        raise ValueError("only the declared material/reference coordinates and non-advecting affine input are supported")
    if rep["mean_spin_per_s"] != 0:
        raise ValueError("a rotating reference cell is not represented")
    limit = float(rep["max_displacement_gradient"])
    if not 0 < limit <= .1:
        raise ValueError("small-strain bound must lie in (0, 0.1]")
    th = spec["thermal"]
    if set(th) != {"density_kg_m3", "heat_capacity_J_kg_K", "diffusivity_m2_s",
                   "viscous_heat_fraction", "plastic_heat_fraction"}:
        raise ValueError("thermal inputs must be exactly density, capacity, diffusivity and heat fractions")
    for name in ("density_kg_m3", "heat_capacity_J_kg_K", "diffusivity_m2_s"):
        positive(th[name], name)
    for name in ("viscous_heat_fraction", "plastic_heat_fraction"):
        if not (math.isfinite(th[name]) and 0 <= th[name] <= 1):
            raise ValueError(name + " must lie in [0, 1]")
    if set(spec["history"]) != {"healing_per_s"} or spec["history"]["healing_per_s"] != 0:
        raise ValueError("no healing law is admitted; raw history only accumulates")
    mech = spec["mechanics"]
    if type(mech) is not dict or set(mech) != {
            "domain_m", "physical_length_m", "stress_scale_Pa", "rate_scale_per_s",
            "reference_temperature_K", "activation_energy_J_per_mol", "reference_viscosity_scaled",
            "plastic_viscosity_scaled", "cohesion_scaled", "reference_pressure_scaled",
            "pore_pressure_scaled", "friction_degrees", "critical_plastic_shear",
            "residual_cohesion_fraction", "imposed_engineering_rate_scaled"}:
        raise ValueError("mechanics must contain only the supported pressure/temperature strength inputs")
    imposed = finite(mech["imposed_engineering_rate_scaled"], "imposed rate")
    if imposed.shape != (2,) or not np.linalg.norm(imposed) > 0:
        raise ValueError("two nonzero imposed engineering-rate components required")
    return spec


def load_case(path=CASE):
    return validate_case(json.loads(Path(path).read_text(encoding="utf-8")))


def capacity(thermal):
    return thermal["density_kg_m3"]*thermal["heat_capacity_J_kg_K"]      # J m^-3 K^-1


def phi_functions(z):
    """phi1=(e^z-1)/z and phi2=(e^z-1-z)/z^2 for z<=0, without small-z cancellation."""
    z = np.asarray(z, dtype=float)
    if not np.isfinite(z).all() or np.any(z > 0):
        raise ValueError("decay exponents must be finite and nonpositive")
    phi1, phi2 = np.ones_like(z), np.full_like(z, .5)
    nonzero = z != 0
    phi1[nonzero] = np.expm1(z[nonzero])/z[nonzero]
    large = np.abs(z) >= 1e-2
    phi2[large] = (np.expm1(z[large])-z[large])/z[large]**2
    small = nonzero & ~large
    zs = z[small]
    phi2[small] = .5+zs*(1/6+zs*(1/24+zs*(1/120+zs*(1/720+zs/5040))))
    return phi1, phi2


class ThermalStepper:
    """Exact periodic conduction with second-order exponential source quadrature.

    Variation of constants with the source linear over the step:
    T(n+1) = E T(n) + dt phi1 S(n) + dt phi2 (S(stage) - S(n)), S=Q/(rho cp).
    The zero mode has E=1, phi1=1, phi2=1/2, so the mean is the trapezoid of S.
    """
    def __init__(self, grid, diffusivity, dt):
        self.dt = positive(dt, "time step")
        z = -positive(diffusivity, "diffusivity")*grid.k2*self.dt
        self.decay = np.exp(z)
        self.phi1, self.phi2 = phi_functions(z)
        self.stiffness = float(-z.min())

    def predict(self, temperature, source):
        return ifft2(self.decay*fft2(temperature)+self.dt*self.phi1*fft2(source)).real

    def correct(self, predicted, source_start, source_stage):
        return predicted+ifft2(self.dt*self.phi2*fft2(source_stage-source_start)).real


def observe_translated(grid, field, displacement):
    """Eulerian view of a material field after a uniform (periodic) translation d."""
    d = finite(displacement, "displacement")
    if d.shape != (2,):
        raise ValueError("two displacement components required")
    phase = np.exp(-1j*(grid.kx*d[0]+grid.ky*d[1]))
    return ifft2(fft2(finite(field, "field"))*phase).real


def eulerian_transport(grid, field, velocity_gradient, translation, duration):
    """Refuse the false periodic advection of an affine mean velocity."""
    gradient = finite(velocity_gradient, "velocity gradient")
    if gradient.shape != (2, 2):
        raise ValueError("2x2 mean velocity gradient required")
    if np.any(gradient != 0):
        raise ValueError("affine mean velocity is not periodic; fields stay in material coordinates")
    return observe_translated(grid, field, finite(translation, "translation")*positive(duration, "duration"))


def cohesion_from_history(grid, history, mech):
    """Nonlocal field for weakening only; the raw history is never overwritten."""
    smoothed = grid.smooth(history)
    if float(smoothed.min()) < -1e-10:
        raise RuntimeError("negative nonlocal history: spectral support unresolved")
    fraction = np.minimum(smoothed/mech["critical_plastic_shear"], 1.)
    return mech["cohesion_scaled"]*(1-(1-mech["residual_cohesion_fraction"])*fraction), smoothed


def max_singular(h):
    a, b, c, d = h[0, 0], h[0, 1], h[1, 0], h[1, 1]
    frob, det = a*a+b*b+c*c+d*d, a*d-b*c
    return np.sqrt((frob+np.sqrt(np.maximum(frob*frob-4*det*det, 0.)))/2)


def evaluate(grid, temperature, history, spec, fractions, *, frozen_cohesion=None,
             initial=None, deadline=None):
    """One converged D2 mechanical state and its owned sources, in SI units."""
    mech = spec["mechanics"]
    cohesion = cohesion_from_history(grid, history, mech)[0] if frozen_cohesion is None else frozen_cohesion
    imposed = np.asarray(mech["imposed_engineering_rate_scaled"], dtype=float)
    out = strength.solve(grid, cohesion, temperature, imposed, mech, spec["policy"],
                         initial=initial, deadline=deadline)
    stress, g, plastic = out["stress"], out["g"], out["plastic"]
    s = np.sqrt(np.sum(stress*stress, axis=0))
    eta_v = strength.viscosity(temperature, mech["reference_viscosity_scaled"],
                               mech["reference_temperature_K"], mech["activation_energy_J_per_mol"])
    total = np.sum(stress*g, axis=0)                  # t.g = s q, the whole dissipation
    viscous, plastic_power = s*s/eta_v, s*plastic     # s q_v and s q_p, each counted once
    split = float(np.max(abs(viscous+plastic_power-total))/max(float(np.max(abs(total))), TINY))
    power = mech["stress_scale_Pa"]*mech["rate_scale_per_s"]   # W m^-3 per scaled unit
    fv, fp = fractions
    rate = mech["rate_scale_per_s"]
    exx, exy, spin = g[0]/2, g[1]/2, out["chi"]      # chi is the periodic vorticity
    gradient = rate*np.array([[exx, exy-spin/2], [exy+spin/2, -exx]])
    unit = imposed/np.linalg.norm(imposed)
    return dict(solution=dict(pressure=out["pressure"], chi=out["chi"]),
                heat=(fv*viscous+fp*plastic_power)*power,
                stored=((1-fv)*viscous+(1-fp)*plastic_power)*power,
                history_rate=plastic*rate, gradient=gradient,
                macro_work=float(np.dot(stress.mean(axis=(1, 2)), imposed))*power,
                stress_Pa=float(np.dot(stress.mean(axis=(1, 2)), unit))*mech["stress_scale_Pa"],
                split=split, iterations=np.array([out["pressure_iterations"], out["newton_iterations"],
                                                  out["cg_iterations"]]))


def evolve(grid, spec, steps, total_strain, temperature0, history0, *, heating=True,
           weakening=True, warm=True, deadline=None):
    """Accepted-step thermal/history evolution; a refused step is never committed."""
    validate_case(spec)
    if type(steps) is not int or not 1 <= steps <= 256:
        raise ValueError("1..256 accepted steps required")
    mech, th, policy = spec["mechanics"], spec["thermal"], spec["policy"]
    temperature, history = finite(temperature0, "temperature").copy(), finite(history0, "history").copy()
    if temperature.shape != (grid.n, grid.n) or history.shape != temperature.shape:
        raise ValueError("temperature and history must match the grid")
    if np.any(history < 0):
        raise ValueError("raw accumulated plastic shear cannot be negative")
    fractions = (th["viscous_heat_fraction"], th["plastic_heat_fraction"]) if heating else (0., 0.)
    heat_capacity = capacity(th)
    engineering_rate = float(np.linalg.norm(mech["imposed_engineering_rate_scaled"]))*mech["rate_scale_per_s"]
    dt = positive(total_strain, "total engineering strain")/engineering_rate/steps
    stepper = ThermalStepper(grid, th["diffusivity_m2_s"], dt)
    limit = spec["representation"]["max_displacement_gradient"]
    frozen = None if weakening else cohesion_from_history(grid, history, mech)[0]
    kwargs = dict(frozen_cohesion=frozen, deadline=deadline)
    mean_t0, mean_h0 = float(temperature.mean()), float(history.mean())
    t0, h0 = temperature.copy(), history.copy()
    displacement = np.zeros((2, 2, grid.n, grid.n))
    accounts = dict(macro_work_J_m3=0., heat_J_m3=0., stored_J_m3=0., history=0.)
    start = time.perf_counter()
    now = evaluate(grid, temperature, history, spec, fractions, **kwargs)
    iterations, solves, split = now["iterations"].copy(), 1, now["split"]
    status, accepted, max_step = "COMPLETE", 0, 0.
    for _ in range(steps):
        source = now["heat"]/heat_capacity
        predicted = stepper.predict(temperature, source)
        stage = evaluate(grid, predicted, history+dt*now["history_rate"], spec, fractions,
                         initial=now["solution"] if warm else None, **kwargs)
        iterations += stage["iterations"]; solves += 1; split = max(split, stage["split"])
        new_t = stepper.correct(predicted, source, stage["heat"]/heat_capacity)
        new_h = history+.5*dt*(now["history_rate"]+stage["history_rate"])
        new_d = displacement+.5*dt*(now["gradient"]+stage["gradient"])
        change = float(np.max(abs(new_t-temperature)))
        if change > policy["max_temperature_step_K"]:
            status = "REFUSED_TEMPERATURE_STEP"; break
        if float(max_singular(new_d).max()) > limit:
            status = "REFUSED_SMALL_STRAIN"; break
        if np.any(new_h < history):
            raise RuntimeError("raw history decreased without an admitted healing law")
        # Commit the step and its trapezoidal accounts together.
        for key, a, b in (("macro_work_J_m3", now["macro_work"], stage["macro_work"]),
                          ("heat_J_m3", float(now["heat"].mean()), float(stage["heat"].mean())),
                          ("stored_J_m3", float(now["stored"].mean()), float(stage["stored"].mean())),
                          ("history", float(now["history_rate"].mean()), float(stage["history_rate"].mean()))):
            accounts[key] += .5*dt*(a+b)
        temperature, history, displacement = new_t, new_h, new_d
        accepted += 1; max_step = max(max_step, change)
        now = evaluate(grid, temperature, history, spec, fractions,
                       initial=stage["solution"] if warm else None, **kwargs)
        iterations += now["iterations"]; solves += 1; split = max(split, now["split"])
    thermal = heat_capacity*(float(temperature.mean())-mean_t0)
    history_gain = float(history.mean())-mean_h0
    work = accounts["macro_work_J_m3"]
    return dict(status=status, cells=grid.n, steps=steps, accepted_steps=accepted, dt_s=dt,
                seconds=time.perf_counter()-start, solves=solves,
                pressure_iterations=int(iterations[0]), newton_iterations=int(iterations[1]),
                cg_iterations=int(iterations[2]), max_power_split_relative=split,
                diffusion_stiffness=stepper.stiffness, max_temperature_step_K=max_step,
                max_displacement_gradient=float(max_singular(displacement).max()),
                stress_Pa=now["stress_Pa"], mean_temperature_rise_K=float(temperature.mean())-mean_t0,
                temperature_change_rms_K=rms(temperature-t0),
                mean_history_increment=history_gain, history_increment_rms=rms(history-h0),
                accounts=accounts, thermal_energy_J_m3=thermal,
                heat_quadrature_relative=relative_change(thermal, accounts["heat_J_m3"]) if accounts["heat_J_m3"] else abs(thermal),
                energy_balance_relative=float(abs(thermal+accounts["stored_J_m3"]-work)/max(abs(work), TINY)),
                history_quadrature_relative=relative_change(history_gain, accounts["history"]) if accounts["history"] else abs(history_gain),
                _temperature=temperature, _history=history)


def seeds(grid, centres, amplitudes, scale):
    """Smooth periodic Gaussian seeds at fixed physical coordinates on every grid."""
    total = np.zeros((grid.n, grid.n))
    for (cx, cy), amplitude in zip(centres, amplitudes, strict=True):
        dx = grid.length/np.pi*np.sin(np.pi*(grid.x/grid.length-cx))
        dy = grid.length/np.pi*np.sin(np.pi*(grid.y/grid.length-cy))
        total += amplitude*np.exp(-(dx*dx+dy*dy)/scale**2)
    return total


def initial_fields(grid, spec):
    """Inherited temperature and raw history attached to material coordinates.

    A large-scale thermal mode plus a warm spot, and two history seeds, all at
    fixed physical coordinates: an initial geological assumption, not nucleation.
    """
    phase_x, phase_y = 2*np.pi*grid.x/grid.length, 2*np.pi*grid.y/grid.length
    mech, init = spec["mechanics"], spec["initial"]
    temperature = (mech["reference_temperature_K"]
                   + init["temperature_amplitude_K"]*np.cos(phase_x)*np.cos(phase_y)
                   + seeds(grid, init["seed_centres_fraction"][:1], [init["warm_spot_K"]], init["warm_spot_scale_m"]))
    history = init["history_amplitude"]*seeds(grid, init["seed_centres_fraction"],
                                              init["seed_relative_amplitudes"], init["seed_scale_m"])
    return temperature, history


def homogeneous_oracle(spec, temperature, history, total_strain):
    """Independent scalar laws integrated by DOP853: the uniform-state reference."""
    mech, th = spec["mechanics"], spec["thermal"]
    q = float(np.linalg.norm(mech["imposed_engineering_rate_scaled"]))
    phi = math.radians(mech["friction_degrees"])
    confinement = max(mech["reference_pressure_scaled"]-mech["pore_pressure_scaled"], 0.)
    heat_capacity = capacity(th)
    power = mech["stress_scale_Pa"]*mech["rate_scale_per_s"]

    def rates(_, y):
        t, k = y
        eta_v = mech["reference_viscosity_scaled"]*math.exp(
            mech["activation_energy_J_per_mol"]/strength.GAS_CONSTANT*(1/t-1/mech["reference_temperature_K"]))
        eta_p = mech["plastic_viscosity_scaled"]
        weak = min(k/mech["critical_plastic_shear"], 1.)
        y_s = mech["cohesion_scaled"]*(1-(1-mech["residual_cohesion_fraction"])*weak)*math.cos(phi)+confinement*math.sin(phi)
        if eta_v*q <= y_s:
            s, qp = eta_v*q, 0.
        else:
            s = (q+y_s/eta_p)/(1/eta_v+1/eta_p); qp = (s-y_s)/eta_p
        qv = s/eta_v
        heat = (th["viscous_heat_fraction"]*s*qv+th["plastic_heat_fraction"]*s*qp)*power
        return [heat/heat_capacity, qp*mech["rate_scale_per_s"]]

    duration = total_strain/(q*mech["rate_scale_per_s"])
    out = solve_ivp(rates, (0., duration), [temperature, history], method="DOP853",
                    rtol=1e-12, atol=[1e-12, 1e-15])
    if out.status != 0:
        raise RuntimeError("homogeneous oracle integration failed")
    return float(out.y[0, -1]-temperature), float(out.y[1, -1]-history)


def order(errors):
    return [math.log2(a/b) if a > 0 and b > 0 else float("inf") for a, b in zip(errors, errors[1:])]


def translation_control(spec):
    c = spec["campaign"]["translation"]; tol = spec["policy"]["translation_relative"]
    grid = strength.PressurePlane(c["cells"], spec["mechanics"]["domain_m"], spec["mechanics"]["physical_length_m"])
    kx, ky = 2*np.pi/grid.length, 2*np.pi/grid.length
    amplitude = 7.
    temperature = 1000.+amplitude*np.cos(2*kx*grid.x+ky*grid.y)+.5*amplitude*np.sin(3*ky*grid.y)
    history = np.where(abs(grid.x) < grid.length/8, .05, 0.)*(abs(grid.y) < grid.length/5)
    before_t, before_h = temperature.copy(), history.copy()
    d = np.array(c["displacement_cells"], dtype=float)*grid.length/grid.n
    seen = observe_translated(grid, temperature, d)
    exact = 1000.+amplitude*np.cos(2*kx*(grid.x-d[0])+ky*(grid.y-d[1]))+.5*amplitude*np.sin(3*ky*(grid.y-d[1]))
    back = observe_translated(grid, observe_translated(grid, history, d), -d)
    roll = observe_translated(grid, history, np.array([2., -3.])*grid.length/grid.n)
    rolled = np.roll(history, shift=(-3, 2), axis=(0, 1))
    try:
        eulerian_transport(grid, temperature, [[1e-14, 0.], [0., -1e-14]], [0., 0.], 1e12)
        affine_refused = False
    except ValueError:
        affine_refused = True
    uniform = eulerian_transport(grid, temperature, np.zeros((2, 2)), d/1e12, 1e12)
    checks = dict(
        material_fields_unchanged=bool(np.array_equal(temperature, before_t) and np.array_equal(history, before_h)),
        band_limited_shift_exact=float(np.max(abs(seen-exact)))/amplitude <= tol,
        mean_preserved=abs(float(seen.mean())-float(temperature.mean()))/1000. <= tol,
        shift_round_trip=float(np.max(abs(back-history)))/.05 <= tol,
        integer_shift_is_roll=float(np.max(abs(roll-rolled)))/.05 <= tol,
        affine_eulerian_advection_refused=affine_refused,
        uniform_translation_allowed=float(np.max(abs(uniform-seen)))/amplitude <= tol)
    return verdict(checks,
                errors=dict(band_limited=float(np.max(abs(seen-exact)))/amplitude,
                            round_trip=float(np.max(abs(back-history)))/.05,
                            integer=float(np.max(abs(roll-rolled)))/.05),
                scope="transport-only: uniform translation; affine mean flow refused")


def manufactured_control(spec):
    """Thermal integrator alone: exact diffusion plus a manufactured forced solution."""
    c = spec["campaign"]["manufactured"]; policy = spec["policy"]
    mech, th = spec["mechanics"], spec["thermal"]
    grid = strength.PressurePlane(c["cells"], mech["domain_m"], mech["physical_length_m"])
    kappa = th["diffusivity_m2_s"]
    duration = c["duration_s"]; omega = 2*np.pi/duration
    (m1, a1), (m2, a2) = [(np.array(m, float)*2*np.pi/grid.length, a) for m, a in zip(c["modes"], c["amplitudes_K"])]
    b = c["mean_heating_K_per_s"]
    phase1, phase2 = m1[0]*grid.x+m1[1]*grid.y, m2[0]*grid.x+m2[1]*grid.y
    k1, k2 = float(m1 @ m1), float(m2 @ m2)

    def exact(t):
        return 1000.+b*t+a1*np.sin(omega*t)*np.cos(phase1)+a2*np.cos(omega*t)*np.sin(phase2)

    def source(t):   # dT/dt - kappa Laplacian(T), in K/s
        return (b+a1*np.cos(phase1)*(omega*np.cos(omega*t)+kappa*k1*np.sin(omega*t))
                +a2*np.sin(phase2)*(-omega*np.sin(omega*t)+kappa*k2*np.cos(omega*t)))

    errors, stiffness = [], []
    for steps in c["steps"]:
        dt = duration/steps; stepper = ThermalStepper(grid, kappa, dt); t = exact(0.)
        for n in range(steps):
            s0, s1 = source(n*dt), source((n+1)*dt)
            t = stepper.correct(stepper.predict(t, s0), s0, s1)
        errors.append(float(np.max(abs(t-exact(duration))))/a1); stiffness.append(stepper.stiffness)
    orders = order(errors)
    stepper = ThermalStepper(grid, kappa, duration/c["steps"][0]); t = 1000.+a1*np.cos(phase1)+a2*np.sin(phase2)
    zero = np.zeros_like(t)
    for _ in range(c["steps"][0]):
        t = stepper.correct(stepper.predict(t, zero), zero, zero)
    decay = 1000.+a1*np.exp(-kappa*k1*duration)*np.cos(phase1)+a2*np.exp(-kappa*k2*duration)*np.sin(phase2)
    diffusion_error = float(np.max(abs(t-decay)))/a1
    low, high = policy["order_range"]
    checks = dict(second_order=all(low <= o <= high for o in orders),
                  finest_error=errors[-1] <= policy["manufactured_relative"],
                  pure_diffusion_exact=diffusion_error <= policy["translation_relative"],
                  stiff_modes_present=max(stiffness) > 1.)
    return verdict(checks, steps=c["steps"], errors=errors,
                orders=orders, diffusion_error=diffusion_error, max_diffusion_stiffness=max(stiffness),
                scope="thermal-only: exponential conduction and source quadrature")


def homogeneous_control(spec, deadline=None):
    c = spec["campaign"]["homogeneous"]; policy = spec["policy"]
    mech = spec["mechanics"]
    grid = strength.PressurePlane(c["cells"], mech["domain_m"], mech["physical_length_m"])
    t0, h0 = np.full((grid.n, grid.n), c["temperature_K"]), np.full((grid.n, grid.n), c["history"])
    strain = c["total_engineering_strain"]
    exact_t, exact_h = homogeneous_oracle(spec, c["temperature_K"], c["history"], strain)
    rows, errors = [], []
    for steps in c["steps"]:
        out = evolve(grid, spec, steps, strain, t0, h0, deadline=deadline)
        uniform = max(float(np.ptp(out["_temperature"]))/c["temperature_K"], float(np.ptp(out["_history"])))
        err = max(relative_change(out["mean_temperature_rise_K"], exact_t),
                  relative_change(out["mean_history_increment"], exact_h))
        errors.append(err)
        rows.append({k: v for k, v in out.items() if not k.startswith("_")} | dict(uniformity=uniform, oracle_relative=err))
    orders = order(errors)
    half = dict(spec, thermal=dict(spec["thermal"], plastic_heat_fraction=.5))
    split_t, split_h = homogeneous_oracle(half, c["temperature_K"], c["history"], strain)
    split = evolve(grid, half, c["steps"][-1], strain, t0, h0, deadline=deadline)
    split_err = max(relative_change(split["mean_temperature_rise_K"], split_t),
                    relative_change(split["mean_history_increment"], split_h))
    slow = dict(spec, mechanics=dict(mech, imposed_engineering_rate_scaled=[c["subyield_rate_scaled"], 0.]))
    sub = evolve(grid, slow, 8, c["subyield_strain"], t0, h0, deadline=deadline)
    low, high = policy["order_range"]
    checks = dict(
        second_order=all(low <= o <= high for o in orders),
        oracle=errors[-1] <= policy["oracle_relative"],
        uniform=max(r["uniformity"] for r in rows) <= policy["algebra_relative"],
        power_split=max(r["max_power_split_relative"] for r in rows) <= policy["algebra_relative"],
        energy=max(r["energy_balance_relative"] for r in rows+[split]) <= policy["energy_relative"],
        heat_quadrature=max(r["heat_quadrature_relative"] for r in rows) <= policy["quadrature_relative"],
        history_quadrature=max(r["history_quadrature_relative"] for r in rows) <= policy["algebra_relative"],
        partial_heating_owned=split_err <= policy["oracle_relative"] and split["accounts"]["stored_J_m3"] > 0,
        subyield_keeps_history=sub["mean_history_increment"] == 0. and sub["history_increment_rms"] == 0.,
        subyield_viscous_heating=sub["mean_temperature_rise_K"] > 0)
    return verdict(checks, oracle=dict(temperature_rise_K=exact_t, history_increment=exact_h),
                runs=rows, orders=orders, partial_heating={k: v for k, v in split.items() if not k.startswith("_")} | dict(oracle_relative=split_err),
                subyield={k: v for k, v in sub.items() if not k.startswith("_")},
                scope="coupled uniform state versus independent scalar integration")


def metrics(run):
    return {k: run[k] for k in ("stress_Pa", "mean_temperature_rise_K", "temperature_change_rms_K",
                                "mean_history_increment", "history_increment_rms")}


def coupled_control(spec, deadline=None):
    c = spec["campaign"]["coupled"]; policy = spec["policy"]
    mech = spec["mechanics"]
    runs, grids = {}, {}
    for cells in c["cells"]:
        grid = strength.PressurePlane(cells, mech["domain_m"], mech["physical_length_m"])
        grids[cells] = grid
        runs[str(cells)] = evolve(grid, spec, c["steps"], c["total_engineering_strain"], *initial_fields(grid, spec), deadline=deadline)
    middle = c["cells"][1]; grid = grids[middle]; fields = initial_fields(grid, spec)
    fine = evolve(grid, spec, c["fine_steps"], c["total_engineering_strain"], *fields, deadline=deadline)
    no_heat = evolve(grid, spec, c["steps"], c["total_engineering_strain"], *fields, heating=False, deadline=deadline)
    no_weak = evolve(grid, spec, c["steps"], c["total_engineering_strain"], *fields, weakening=False, deadline=deadline)
    cold = evolve(grid, spec, c["steps"], c["total_engineering_strain"], *fields, warm=False, deadline=deadline)
    base_run = runs[str(middle)]
    coarse, finest = runs[str(c["cells"][-2])], runs[str(c["cells"][-1])]

    def increments(run, cells):
        t0, h0 = initial_fields(grids[cells], spec)
        return run["_temperature"]-t0, run["_history"]-h0

    def field_changes(low, high):
        a, b = increments(runs[str(low)], low), increments(runs[str(high)], high)
        return {name: rms(spectral_resample(x, high)-y)/max(rms(y), TINY)
                for name, x, y in (("temperature_change_field", a[0], b[0]), ("history_increment_field", a[1], b[1]))}

    mesh = {k: relative_change(coarse[k], finest[k]) for k in metrics(finest)}
    mesh |= field_changes(c["cells"][-2], c["cells"][-1])
    coarse_mesh = field_changes(c["cells"][0], c["cells"][1])
    temporal = {k: relative_change(base_run[k], fine[k]) for k in metrics(fine)}
    step_a, step_b = increments(base_run, middle), increments(fine, middle)
    temporal |= {"temperature_change_field": rms(step_a[0]-step_b[0])/max(rms(step_b[0]), TINY),
                 "history_increment_field": rms(step_a[1]-step_b[1])/max(rms(step_b[1]), TINY)}
    resolution = max(mesh["stress_Pa"], temporal["stress_Pa"])
    thermal_effect = relative_change(no_heat["stress_Pa"], base_run["stress_Pa"])
    history_effect = relative_change(no_weak["stress_Pa"], base_run["stress_Pa"])
    parity = max(relative_change(cold[k], base_run[k]) for k in metrics(base_run))
    every = list(runs.values())+[fine, no_heat, no_weak, cold]
    factor = policy["coupling_resolution_factor"]
    heating_signature = base_run["_temperature"]-no_heat["_temperature"]
    checks = dict(
        completed=all(r["status"] == "COMPLETE" for r in every),
        mesh=max(mesh.values()) <= policy["mesh_relative"],
        time=max(temporal.values()) <= policy["time_relative"],
        energy=max(r["energy_balance_relative"] for r in every) <= policy["energy_relative"],
        heat_quadrature=max(r["heat_quadrature_relative"] for r in every if r["accounts"]["heat_J_m3"]) <= policy["quadrature_relative"],
        history_quadrature=max(r["history_quadrature_relative"] for r in every) <= policy["algebra_relative"],
        power_split=max(r["max_power_split_relative"] for r in every) <= policy["algebra_relative"],
        small_strain=max(r["max_displacement_gradient"] for r in every) <= spec["representation"]["max_displacement_gradient"],
        heating_feedback_resolved=thermal_effect >= factor*resolution,
        history_feedback_resolved=history_effect >= factor*resolution,
        heating_off_is_transport_only=no_heat["mean_temperature_rise_K"] == 0. or abs(no_heat["mean_temperature_rise_K"]) <= 1e-9,
        warm_start_parity=parity <= policy["warm_parity_relative"])
    clean = lambda r: {k: v for k, v in r.items() if not k.startswith("_")}
    return verdict(checks,
                meshes={k: clean(v) for k, v in runs.items()}, fine_time=clean(fine),
                heating_off=clean(no_heat), weakening_off=clean(no_weak), cold_start=clean(cold),
                mesh_changes=mesh, coarse_mesh_field_changes=coarse_mesh, time_changes=temporal,
                thermal_feedback_relative=thermal_effect,
                history_feedback_relative=history_effect, resolution_relative=resolution,
                heating_temperature_K=dict(mean=float(heating_signature.mean()),
                                           minimum=float(heating_signature.min()),
                                           maximum=float(heating_signature.max())),
                warm_cold_parity=parity,
                reuse=dict(warm_seconds=base_run["seconds"], cold_seconds=cold["seconds"],
                           saved_seconds=cold["seconds"]-base_run["seconds"],
                           saved_percent=100*(1-base_run["seconds"]/cold["seconds"]),
                           warm_cg=base_run["cg_iterations"], cold_cg=cold["cg_iterations"]),
                scope="genuinely coupled: temperature and filtered history both feed the D2 solve")


def refusal_control(spec, deadline=None):
    c = spec["campaign"]["refusal"]; mech = spec["mechanics"]
    grid = strength.PressurePlane(c["cells"], mech["domain_m"], mech["physical_length_m"])
    fields = initial_fields(grid, spec)
    out = evolve(grid, spec, c["strain_steps"], c["total_engineering_strain"], *fields, deadline=deadline)
    hot = evolve(grid, spec, c["temperature_steps"], c["total_engineering_strain"], *fields, deadline=deadline)
    refused = []
    for mutate in (lambda s: s["history"].update(healing_per_s=1e-15),
                   lambda s: s["thermal"].update(plastic_heat_fraction=1.5),
                   lambda s: s["representation"].update(mean_spin_per_s=1e-15),
                   lambda s: s["representation"].update(max_displacement_gradient=.5),
                   lambda s: s.update(elastic_modulus_Pa=3e10)):
        bad = json.loads(json.dumps(spec)); mutate(bad)
        try:
            validate_case(bad); refused.append(False)
        except ValueError:
            refused.append(True)
    try:
        evolve(grid, spec, 257, .01, *initial_fields(grid, spec)); ceiling = False
    except ValueError:
        ceiling = True
    checks = dict(small_strain_refused=out["status"] == "REFUSED_SMALL_STRAIN" and out["accepted_steps"] < c["strain_steps"],
                  temperature_step_refused=hot["status"] == "REFUSED_TEMPERATURE_STEP" and hot["accepted_steps"] < c["temperature_steps"],
                  refused_step_not_booked=max(out["energy_balance_relative"], hot["energy_balance_relative"]) <= spec["policy"]["energy_relative"],
                  unadmitted_laws_refused=all(refused), step_ceiling=ceiling)
    clean = lambda r: {k: v for k, v in r.items() if not k.startswith("_")}
    return verdict(checks, refused_run=clean(out), temperature_refused_run=clean(hot))


CONTROLS = (("translation", translation_control, False), ("manufactured", manufactured_control, False),
            ("homogeneous", homogeneous_control, True), ("coupled", coupled_control, True),
            ("refusal", refusal_control, True))


def bindings():
    paths = [Path(__file__), CASE, ROOT/"docs/I01_THERMAL.md", ROOT/"tests/test_i01_thermal.py",
             Path(strength.__file__), Path(base.__file__), ROOT/"cases/i01_strength_v1.json",
             ROOT/"tests/test_i01_strength.py", ROOT/"tests/test_i01_fault2d.py"]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def reviewed_helpers(current):
    """Compare imported helper bytes with the hashes their own receipts recorded."""
    out = {}
    for receipt in ("evidence/i01-strength-r1.json", "evidence/i01-fault2d-r1.json"):
        recorded = json.loads((ROOT/receipt).read_text(encoding="utf-8"))["source_sha256"]
        for path in ("tools/check_i01_strength.py", "tools/check_i01_fault2d.py"):
            if path in recorded:
                out[receipt+":"+path] = recorded[path] == current[path]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream, threadpool_limits(limits=1, user_api="blas"):
        result = dict(schema="atlas.i01-thermal-evidence.v1", status="INCOMPLETE", scientific_acceptance=False,
                      runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                                   system=platform.system(), machine=platform.machine(), blas_threads=1),
                      controls={})
        start = time.perf_counter()
        try:
            before = bindings(); spec = load_case()
            result.update(source_sha256=before, helper_bytes_match_reviewed_receipts=reviewed_helpers(before), spec=spec)
            deadline = time.perf_counter()+spec["policy"]["maximum_seconds"]
            for name, run, timed in CONTROLS:
                begin = time.perf_counter()
                try:
                    data = run(spec, deadline) if timed else run(spec)
                    result["controls"][name] = dict(status="PASS" if data["passed"] else "FAIL",
                                                    seconds=time.perf_counter()-begin, **data)
                except (ValueError, RuntimeError) as exc:
                    result["controls"][name] = dict(status="FAIL", seconds=time.perf_counter()-begin,
                                                    error_type=type(exc).__name__, error=str(exc))
            result["source_unchanged"] = before == bindings()
            passed = (result["source_unchanged"] and all(result["helper_bytes_match_reviewed_receipts"].values())
                      and all(c["status"] == "PASS" for c in result["controls"].values()))
            result["status"] = "PASS_BOUNDED_THERMAL_HISTORY_ONLY" if passed else "FAIL"
        except Exception as exc:
            # Deliberately do not publish arbitrary exception paths or tracebacks.
            result.update(status="FAIL", error_type=type(exc).__name__)
            if isinstance(exc, (ValueError, RuntimeError)):
                result["error"] = str(exc).replace(str(ROOT), "TECTONICS_ROOT")
        result["elapsed_seconds"] = time.perf_counter()-start
        json.dump(result, stream, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({key: result.get(key) for key in ("status", "elapsed_seconds", "error")}
                     | {"controls": {k: v["status"] for k, v in result["controls"].items()}}))
    return 0 if result["status"] == "PASS_BOUNDED_THERMAL_HISTORY_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
