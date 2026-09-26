"""Small I01 design controls, NOT a generated world or production physics.

SPDX-License-Identifier: AGPL-3.0-only
No native package imports, installs, implicit retries or historical repinning.
Run with the existing scientific Python, -B, --output NEW.json. The declared
cases and acceptance thresholds below are fixed before collecting results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time

import numpy as np
import scipy
from scipy.linalg import cholesky_banded, cho_solve_banded

YEAR_S = 365.25 * 86400.0
MYR_S = 1e6 * YEAR_S
ROOT = Path(__file__).resolve().parents[1]
POLICY = {
    "algebra_relative": 1e-11,
    "d2_mesh_relative": 0.03,
    "d2_time_relative": 0.03,
    "d2_operator_error_ratio": [3.8, 4.2],
    "d5_volume_relative": 1e-11,
    "scope": "analytical torque, 1D shear, spherical-lune accounts, local Airy water",
}


def finite_array(value, name):
    result = np.asarray(value, dtype=float)
    if not np.isfinite(result).all():
        raise ValueError(f"{name} must be finite")
    return result


def positive(value, name):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return value


def relative(actual, expected):
    actual, expected = np.asarray(actual), np.asarray(expected)
    return float(np.linalg.norm(actual - expected) /
                 max(float(np.linalg.norm(expected)), np.finfo(float).tiny))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def drag_matrix(positions_m, weights, coefficient):
    """Integral D (|r|² I - r r^T): area or line weights must be explicit.

    Area: coefficient Pa s/m, weights m². Line: Pa s, weights m.
    Both return torque/angular-velocity resistance in N m s.
    """
    r = finite_array(positions_m, "positions")
    w = finite_array(weights, "quadrature weights")
    d = finite_array(coefficient, "resistance coefficient")
    if r.ndim != 2 or r.shape[1] != 3 or w.shape != (len(r),):
        raise ValueError("positions and positive quadrature weights must match")
    if np.any(w <= 0) or np.any(d <= 0) or d.shape not in ((), w.shape):
        raise ValueError("positive matching coefficients and weights required")
    r2 = np.einsum("ij,ij->i", r, r)
    if np.any(r2 == 0):
        raise ValueError("positions cannot be at the sphere centre")
    return (np.eye(3) * np.sum(w * d * r2)
            - np.einsum("i,ij,ik->jk", w * d, r, r))


def solve_torque(matrix, torque):
    matrix, torque = finite_array(matrix, "matrix"), finite_array(torque, "torque")
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or torque.shape != (len(matrix),):
        raise ValueError("square torque system required")
    if np.linalg.norm(matrix-matrix.T) > 1e-13*np.linalg.norm(matrix):
        raise ValueError("symmetric dissipative resistance required")
    eigenvalues = np.linalg.eigvalsh(matrix)
    if eigenvalues[0] <= 0 or eigenvalues[-1] / eigenvalues[0] > 1e12:
        raise ValueError("unresolved frame/nullspace or ill-conditioned resistance")
    omega = np.linalg.solve(matrix, torque)
    residual = relative(matrix @ omega, torque) if np.any(torque) else float(np.linalg.norm(omega))
    require(residual <= POLICY["algebra_relative"], "torque residual")
    return omega


def torque_control():
    # Eight cube vertices integrate the hemisphere second moments exactly.
    radius, drag, edge_drag = 6_371_000.0, 6.25e14, 1e21
    north = radius / math.sqrt(3) * np.array(
        [[a, b, 1.0] for a in (-1., 1.) for b in (-1., 1.)])
    weights = np.full(4, 2 * math.pi * radius**2 / 4)
    basal = drag_matrix(north, weights, drag)
    basal_exact = (4 * math.pi / 3) * drag * radius**4 * np.eye(3)
    angle = np.arange(8) * 2 * math.pi / 8
    equator = radius * np.column_stack((np.cos(angle), np.sin(angle), np.zeros(8)))
    edge = drag_matrix(equator, np.full(8, 2 * math.pi * radius / 8), edge_drag)
    edge_exact = math.pi * edge_drag * radius**3 * np.diag([1., 1., 2.])
    matrix = np.block([[basal + edge, -edge], [-edge, basal + edge]])
    drive = np.array([1e25, -2e25, 3e25])
    torque = np.r_[drive, -drive]
    start = time.perf_counter()
    omega = solve_torque(matrix, torque)
    cold = time.perf_counter() - start
    expected_one = drive / np.diag(basal_exact + 2 * edge_exact)
    expected = np.r_[expected_one, -expected_one]
    # Independent scalar dissipation integrals, not matrix @ omega again.
    v0 = np.cross(omega[:3], north)
    v1 = np.cross(omega[3:], -north)
    dv = np.cross(omega[:3] - omega[3:], equator)
    power = (drag * np.sum(weights * (np.sum(v0*v0, axis=1) + np.sum(v1*v1, axis=1)))
             + edge_drag * (2 * math.pi * radius / 8) * np.sum(dv*dv))
    work = float(torque @ omega)
    axis = np.array([1., 2., 3.]); axis /= np.linalg.norm(axis)
    cross = np.array([[0., -axis[2], axis[1]], [axis[2], 0., -axis[0]], [-axis[1], axis[0], 0.]])
    rotation = np.eye(3) + math.sin(.713)*cross + (1-math.cos(.713))*(cross @ cross)
    q = np.block([[rotation, np.zeros((3, 3))], [np.zeros((3, 3)), rotation]])
    rotated = solve_torque(q @ matrix @ q.T, q @ torque)
    doubled = solve_torque(2 * matrix, torque)
    zero = solve_torque(matrix, np.zeros(6))
    errors = dict(basal_integral=relative(basal, basal_exact),
                  edge_integral=relative(edge, edge_exact), solution=relative(omega, expected),
                  rotated_frame=relative(rotated, q @ omega),
                  inverse_resistance_scaling=relative(doubled, .5*omega),
                  work_dissipation=abs(work-power)/work)
    require(max(errors.values()) < POLICY["algebra_relative"] and np.all(zero == 0),
            "D1 analytical/frame/energy control failed")
    start = time.perf_counter(); reused = solve_torque(matrix, torque)
    warm = time.perf_counter() - start
    require(np.array_equal(omega, reused), "D1 repeated solve differs")
    return dict(relative_errors=errors, omega_rad_s=omega.tolist(), work_W=work,
                drag_Pa_s_per_m=drag, edge_drag_Pa_s=edge_drag,
                cold_solve_seconds=cold, repeated_solve_seconds=warm,
                reference="two exact hemisphere moments plus equatorial interface integral",
                limitation="linear resistance feasibility only; no calibrated force law or evolving plates")


def length_factor(cells, length_m, ell_m):
    if type(cells) is not int or not 3 <= cells <= 4096:
        raise ValueError("bounded control requires 3..4096 cells")
    length_m, ell_m = positive(length_m, "domain length"), positive(ell_m, "physical length")
    s = (ell_m / (length_m / cells))**2
    a = np.zeros((2, cells)); a[0] = 1 + 2*s
    a[0, 0] = a[0, -1] = 1+s; a[1, :-1] = -s
    return cholesky_banded(a, lower=True, check_finite=False)


def filtered(factor, raw):
    # L*1=1 exactly in the model. Solve only the departure from a constant so
    # Cholesky round-off cannot seed localisation in an exactly uniform field.
    # This is an equivalent well-balanced solve, not post-solve smoothing/clipping.
    reference = raw[0]
    return reference + cho_solve_banded((factor, True), raw-reference, check_finite=False)


def shear_rate(yield_pa, imposed_rate, creep_pa_s, plastic_pa_s):
    """Positive simple-shear control; gamma_dot=tau/eta_v+<tau-Y>/eta_p.

    Scalar stress is constant by momentum balance. A monotone scalar root enforces
    the imposed mean shear rate, without any strain-rate floor or stress clipping.
    """
    lo, hi = 0., imposed_rate * creep_pa_s
    for _ in range(64):
        stress = .5 * (lo+hi)
        total = stress/creep_pa_s + np.maximum(stress-yield_pa, 0)/plastic_pa_s
        if float(total.mean()) > imposed_rate:
            hi = stress
        else:
            lo = stress
    stress = .5 * (lo+hi)
    plastic = np.maximum(stress-yield_pa, 0)/plastic_pa_s
    total = stress/creep_pa_s + plastic
    return stress, total, plastic


def shear_case(cells, steps, *, ell_m=5000., speed_m_s=.01/YEAR_S, strength=1., seed=True):
    """Atlas candidate law in a fixed 1D isothermal simple-shear strip.

    This is a discriminating feasibility experiment, NOT the Duretz 2D model.
    Raw accumulated plastic engineering shear is distinct from filtered history.
    Temperature, pressure, advection and elastic transients are held fixed here.
    """
    if type(steps) is not int or not 1 <= steps <= 2048:
        raise ValueError("1..2048 explicit control steps required")
    positive(speed_m_s, "speed"); positive(strength, "strength")
    length, eta_v, eta_p = 100_000., 1e23, 1e20
    x = (np.arange(cells)+.5)*length/cells
    # Same continuous inherited heterogeneity at every mesh, never cell noise.
    initial_yield = strength * 30e6 * (1 - (.2 if seed else 0)*np.exp(-((x-length/2)/7500.)**2))
    residual_yield = .1 * initial_yield
    history = np.zeros(cells)
    factor = length_factor(cells, length, ell_m)
    dt = MYR_S/steps
    stresses = []
    max_rate_residual = 0.
    for _ in range(steps):
        smooth = filtered(factor, history)
        yield_pa = initial_yield - (initial_yield-residual_yield)*np.minimum(smooth/.3, 1.)
        stress, total, plastic = shear_rate(yield_pa, speed_m_s/length, eta_v, eta_p)
        max_rate_residual = max(max_rate_residual, abs(float(total.mean())-speed_m_s/length)/(speed_m_s/length))
        history += dt*plastic
        stresses.append(stress)
    smooth = filtered(factor, history)
    yield_pa = initial_yield - (initial_yield-residual_yield)*np.minimum(smooth/.3, 1.)
    stress, total, plastic = shear_rate(yield_pa, speed_m_s/length, eta_v, eta_p)
    amount = float(history.sum())
    require(amount > 0 and np.all(history >= 0), "D2 missing/negative plastic history")
    centre = float(x @ history / amount)
    width = 2 * math.sqrt(float(((x-centre)**2) @ history / amount))
    return dict(cells=cells, steps=steps, ell_m=ell_m, stress_Pa=stress,
                peak_history=float(history.max()), width_2sigma_m=width,
                peak_to_mean=float(history.max()/history.mean()),
                max_mean_rate_relative_error=max_rate_residual,
                final_dissipation_W_per_m2=float(np.mean(stress*total)*length),
                _history=history, _stresses=np.array(stresses), _x=x)


def localisation_control():
    modal = []
    for cells in (40, 80, 160):
        x = (np.arange(cells)+.5)/cells
        raw = 2 + np.cos(2*math.pi*x)
        factor = length_factor(cells, 1., .1)
        out = filtered(factor, raw)
        exact = 2 + np.cos(2*math.pi*x)/(1+(.2*math.pi)**2)
        modal.append(dict(cells=cells, error=float(np.max(abs(out-exact))),
                          mean_error=abs(float(out.mean()-raw.mean())), minimum=float(out.min())))
    ratios = [modal[i]["error"]/modal[i+1]["error"] for i in range(2)]
    require(all(POLICY["d2_operator_error_ratio"][0] < r < POLICY["d2_operator_error_ratio"][1] for r in ratios),
            "D2 operator refinement failed")
    cases = []
    for n, steps in ((80, 256), (160, 256), (320, 256), (160, 128)):
        start = time.perf_counter(); row = shear_case(n, steps)
        row["seconds"] = time.perf_counter()-start; cases.append(row)
    def differences(a, b):
        return {k: abs(a[k]-b[k])/abs(b[k]) for k in ("stress_Pa", "width_2sigma_m")}
    space = differences(cases[1], cases[2]); temporal = differences(cases[3], cases[1])
    uniform = shear_case(160, 256, seed=False)
    stronger = shear_case(160, 256, strength=2.)
    slower = shear_case(160, 256, speed_m_s=.005/YEAR_S)
    short_length = shear_case(160, 256, ell_m=2500.)
    criteria = dict(mesh=max(space.values()) <= POLICY["d2_mesh_relative"],
                    time=max(temporal.values()) <= POLICY["d2_time_relative"],
                    heterogeneous_localises=cases[1]["peak_to_mean"] > 2.,
                    homogeneous_stays_uniform=float(np.ptp(uniform["_history"])) < 1e-12,
                    increased_strength_raises_stress=stronger["stress_Pa"] > cases[1]["stress_Pa"],
                    lower_speed_lowers_peak_strain=slower["peak_history"] < cases[1]["peak_history"],
                    physical_length_changes_width=abs(short_length["width_2sigma_m"]-cases[1]["width_2sigma_m"]) > 50.,
                    momentum_rate=all(c["max_mean_rate_relative_error"] < 1e-11 for c in cases))
    clean = lambda row: {k:v for k,v in row.items() if not k.startswith("_")}
    return dict(passed=all(criteria.values()), criteria=criteria, modal=modal, modal_ratios=ratios,
                cases=[clean(c) for c in cases], mesh_relative_changes=space,
                timestep_relative_changes=temporal,
                contrasts={"homogeneous":clean(uniform), "stronger":clean(stronger),
                           "slower":clean(slower), "shorter_length":clean(short_length)},
                limitation="1D fixed-temperature candidate only; 2D orientation, rupture and coupled energy not proved")


def reserve_balances(stocks, debits):
    """Pure all-or-nothing finite-stock control; no clipping or input mutation."""
    stocks = finite_array(stocks, "stocks"); debits = finite_array(debits, "debits")
    if stocks.shape != debits.shape or np.any(stocks < 0) or np.any(debits < 0):
        raise ValueError("matching nonnegative accounts required")
    if np.any(debits > stocks):
        raise ValueError("finite source exhausted")
    return stocks-debits


def ocean_control():
    # Exact spherical lune: A = 2 R² delta-longitude. Normal angular rates are
    # relative to the moving ridge. Opposite equal sinks are a declared fixture,
    # not an algorithm which rescales sinks to force global balance.
    radius, rho, thickness = 6_371_000., 2900., 7000.
    sphere = 4*math.pi*radius**2
    available = sphere*rho*thickness
    birth_total = sink_total = 0.
    surface_area = sphere
    heat_per_kg = 1200.*1200.  # Declared cp*(Tbirth-Treference), no latent term.
    heat_source = available*heat_per_kg
    consumed_heat = 0.
    elapsed = 0.; ridge_angle = 0.
    inherited_birth_s = -100.*MYR_S
    cohorts = []
    stages = [(2*MYR_S, math.radians(2.)/MYR_S, math.radians(.5)/MYR_S),
              (3*MYR_S, math.radians(1.)/MYR_S, math.radians(-.25)/MYR_S)]
    sink_rates = [math.radians(1.5)/MYR_S, math.radians(1.25)/MYR_S]
    for (duration, omega_plate, omega_ridge), sink_rate in zip(stages, sink_rates, strict=True):
        relative_rate = omega_plate-omega_ridge
        birth_area = 2*radius**2*relative_rate*duration
        mass = birth_area*rho*thickness
        available, heat_source = reserve_balances([available, heat_source], [mass, mass*heat_per_kg])
        birth_total += mass
        # The sink is supplied independently by this matched-rate reference
        # scenario, not recalculated from a residual to repair global geometry.
        sink_area = 2*radius**2*sink_rate*duration
        sink_total += sink_area*rho*thickness
        surface_area += birth_area-sink_area
        consumed_heat += mass*heat_per_kg
        for cohort in cohorts:
            cohort["midpoint_longitude_rad"] += omega_plate*duration
        birth_angle = ridge_angle + omega_ridge*duration/2
        cohorts.append(dict(birth_start_s=elapsed, birth_end_s=elapsed+duration,
                            area_m2=birth_area, reference_mass_kg=mass,
                            midpoint_birth_longitude_rad=birth_angle,
                            midpoint_longitude_rad=birth_angle+omega_plate*duration/2))
        ridge_angle += omega_ridge*duration
        elapsed += duration
    # Residence ages are intervals, not midpoint ages masquerading as all parcels.
    ages = [[(elapsed-c["birth_end_s"])/MYR_S, (elapsed-c["birth_start_s"])/MYR_S] for c in cohorts]
    expected_area = 2*radius**2*math.radians(6.75)
    actual_area = math.fsum(c["area_m2"] for c in cohorts)
    residuals = dict(swept_area=abs(actual_area-expected_area)/expected_area,
                     sphere_area=abs(surface_area-sphere)/sphere, lithosphere_mass=abs(birth_total-sink_total)/birth_total,
                     source_mass=abs((sphere*rho*thickness-available)-birth_total)/birth_total,
                     heat=abs((sphere*rho*thickness*heat_per_kg-heat_source)-consumed_heat)/consumed_heat)
    require(max(residuals.values()) < 1e-11 and ages == [[3., 5.], [0., 3.]], "D3 history/account control failed")
    positions_deg = [math.degrees(c["midpoint_longitude_rad"]) for c in cohorts]
    require(np.allclose(positions_deg, [5.5, 2.125], rtol=0, atol=1e-12), "staged material trajectories")
    false_current_rate_age = (cohorts[0]["midpoint_longitude_rad"]-ridge_angle)/sink_rates[-1]/MYR_S
    require(abs(false_current_rate_age-4.) > .1, "control must distinguish history from current-rate age")
    return dict(relative_errors=residuals, birth_area_m2=actual_area, cohorts=cohorts,
                age_intervals_Myr=ages, inherited_age_at_endpoint_Myr=(elapsed-inherited_birth_s)/MYR_S,
                midpoint_longitudes_deg=positions_deg, first_midpoint_actual_age_Myr=4.,
                rejected_current_distance_over_rate_age_Myr=false_current_rate_age,
                limitation="exact staged lune and equal declared sink accounting; not arbitrary spherical remap/topology")


def sea_level(dry_elevation_m, area_m2, volume_m3, *, rho_m=3300., rho_w=1000.):
    """Local Airy + uniform connected sea, fixed compensation-pressure datum.

    z = z_dry - (rho_w/rho_m)*d, d=max(0,S-z), sum(A*d)=V.
    This is NOT a self-gravitating sea-level equation or regional flexure solver.
    """
    z0 = finite_array(dry_elevation_m, "dry elevation")
    area = finite_array(area_m2, "area")
    positive(rho_m, "mantle density"); positive(rho_w, "water density")
    if z0.ndim != 1 or not len(z0) or z0.shape != area.shape or np.any(area <= 0):
        raise ValueError("matching nonempty positive areas required")
    if not math.isfinite(volume_m3) or volume_m3 < 0 or not rho_w < rho_m:
        raise ValueError("finite nonnegative water volume and rho_w < rho_m required")
    beta = 1-rho_w/rho_m
    if volume_m3 == 0:
        return dict(sea_level_m=None, depth_m=np.zeros_like(z0), bed_m=z0.copy())
    order = np.argsort(z0, kind="stable"); sorted_z, sorted_a = z0[order], area[order]
    # Shift the datum before summing to avoid cancellation at large offsets.
    base = float(sorted_z[0]); offset = sorted_z-base
    cumulative_a = np.cumsum(sorted_a); cumulative_az = np.cumsum(sorted_a*offset)
    level = None
    for k in range(len(z0)):
        candidate = (beta*volume_m3+cumulative_az[k])/cumulative_a[k]
        if k == len(z0)-1 or candidate <= offset[k+1]:
            level = base+float(candidate); break
    depth = np.maximum(level-z0, 0)/beta
    return dict(sea_level_m=level, depth_m=depth, bed_m=z0-(rho_w/rho_m)*depth)


def water_control():
    z = np.array([-1000., 0., 2000.]); areas = np.array([2., 1., 3.])*1e12
    volume = 4e15; beta = 1-1000/3300
    out = sea_level(z, areas, volume)
    # Independent piecewise analytic expression: first two cells wet, third dry.
    expected_level = (beta*volume-2e15)/3e12
    require(0 < expected_level < 2000, "D5 independent wet-set fixture")
    residual = abs(float(areas @ out["depth_m"])-volume)/volume
    shifted = sea_level(z+777., areas, volume)
    split = sea_level(np.repeat(z, 2), np.repeat(areas/2, 2), volume)
    no_water = sea_level(z, areas, 0.)
    errors = dict(volume=residual, analytic_level=abs(out["sea_level_m"]-expected_level),
                  datum_depth=float(np.max(abs(shifted["depth_m"]-out["depth_m"]))),
                  split_level=abs(split["sea_level_m"]-out["sea_level_m"]),
                  hydrostatic=float(np.max(abs(np.maximum(out["sea_level_m"]-out["bed_m"],0)-out["depth_m"]))))
    require(residual < POLICY["d5_volume_relative"] and max(v for k,v in errors.items() if k != "volume") < 1e-9,
            "D5 analytic/volume/datum control failed")
    require(no_water["sea_level_m"] is None and np.array_equal(no_water["bed_m"], z), "zero-water datum invented")
    return dict(errors=errors, sea_level_m=out["sea_level_m"], bed_m=out["bed_m"].tolist(),
                depth_m=out["depth_m"].tolist(), volume_m3=volume,
                limitation="all depressions share one connected sea; no geoid, elastic loading or isolated lakes")


def binding():
    paths = [Path(__file__), ROOT/"cases/i01_closures_v1.json", ROOT/"docs/I01_PHYSICAL_CONTRACT.md"]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        result = dict(schema="atlas.i01-closure-controls.v1", status="INCOMPLETE",
                      scientific_acceptance=False, policy=POLICY, cases={},
                      runtime=dict(python=platform.python_version(), numpy=np.__version__,
                                   scipy=scipy.__version__, system=platform.system(), machine=platform.machine()))
        start = time.perf_counter()
        try:
            result["source_sha256"] = binding()
            spec = json.loads((ROOT/"cases/i01_closures_v1.json").read_text(encoding="utf-8"))
            require(spec["control_policy"] == POLICY, "case policy and executable differ")
            for name, run in (("D1", torque_control), ("D2", localisation_control),
                              ("D3", ocean_control), ("D5", water_control)):
                begin = time.perf_counter()
                try:
                    data = run()
                    passed = data.get("passed", True)
                    result["cases"][name] = dict(status="PASS" if passed else "FAIL", seconds=time.perf_counter()-begin, **data)
                except Exception as exc:
                    result["cases"][name] = dict(status="FAIL", seconds=time.perf_counter()-begin,
                                                 error_type=type(exc).__name__, error=str(exc))
            result["source_unchanged"] = result["source_sha256"] == binding()
            result["status"] = ("PASS_BOUNDED_CONTROLS_ONLY" if result["source_unchanged"] and
                                all(c["status"] == "PASS" for c in result["cases"].values()) else "FAIL")
        except Exception as exc:
            result.update(status="FAIL", error_type=type(exc).__name__,
                          error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
        result["elapsed_seconds"] = time.perf_counter()-start
        json.dump(result, output, indent=2, allow_nan=False); output.write("\n")
    print(json.dumps({"status":result["status"], "elapsed_seconds":result["elapsed_seconds"],
                      "cases":{k:v["status"] for k,v in result["cases"].items()}}))
    return 0 if result["status"] == "PASS_BOUNDED_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    sys.exit(main())
