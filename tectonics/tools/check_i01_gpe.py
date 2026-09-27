"""I01 dry compensated columns -> GPE traction -> bounded spherical torque.

WORKING NON-CANON. No native world evolution or extra ridge-push force.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import platform
import time
import numpy as np
import scipy
from check_i01_closures import drag_matrix, solve_torque

ROOT = Path(__file__).resolve().parents[1]
POLICY = dict(max_columns=32768, max_layers=32, max_stencil_points=8192,
              max_density_anomaly=.1, algebra_relative=1e-11,
              finest_torque_relative=.001, benchmark_repetitions=5)


def number(value, name, *, positive=False):
    if isinstance(value, (bool, str, bytes)) or np.ndim(value) != 0:
        raise ValueError(name+" must be a real scalar")
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(name+" outside finite support")
    return value


def real_array(value):
    a = np.asarray(value)
    if a.dtype.kind not in "fiu" or not np.all(np.isfinite(a)):
        raise ValueError("finite real arrays required")
    return np.asarray(a, dtype=float)


@dataclass(frozen=True)
class Datum:
    """Common basal pressure, vertical origin, gravity and reference mantle."""
    pressure_pa: float
    compensation_elevation_m: float
    mantle_density_kg_m3: float = 3300.
    gravity_m_s2: float = 9.81
    reference_temperature_k: float = 293.15

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, number(getattr(self, name), name,
                positive=name != "compensation_elevation_m"))


def _moments(h, rb, rt):
    """Exact moments for linear density, layer order bottom to top."""
    load = h*(rb+rt)/2
    local_moment = h*h*(rb+2*rt)/6
    base = np.cumsum(h, axis=1)-h
    return load.sum(axis=1), (base*load+local_moment).sum(axis=1)


def columns(datum, thickness_m, reference_density_kg_m3, alpha_per_k,
            bottom_temperature_k, top_temperature_k):
    """Static dry support and GPE from the SAME prescribed material columns.

    h is (columns,layers); other inputs must broadcast to that exact shape.
    Temperature is linear within each layer. Reference material mass is not
    replaced by effective buoyancy load. Mantle fill is diagnostic, not a
    transported or conserved inventory. Inputs are not modified or cached.
    """
    if not isinstance(datum, Datum):
        raise ValueError("one shared Datum required")
    h = real_array(thickness_m)
    if (h.ndim != 2 or not 1 <= h.shape[0] <= POLICY["max_columns"] or
            not 1 <= h.shape[1] <= POLICY["max_layers"] or np.any(h <= 0)):
        raise ValueError("positive bounded column/layer thicknesses required")
    rho, alpha, tb, tt = [np.broadcast_to(real_array(v), h.shape) for v in
        (reference_density_kg_m3, alpha_per_k, bottom_temperature_k, top_temperature_k)]
    if np.any(rho <= 0) or np.any(alpha < 0) or np.any(tb <= 0) or np.any(tt <= 0):
        raise ValueError("positive densities/Kelvin and nonnegative expansivity required")
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        db = alpha*(tb-datum.reference_temperature_k)
        dt = alpha*(tt-datum.reference_temperature_k)
        if max(float(np.max(np.abs(db))), float(np.max(np.abs(dt)))) > POLICY["max_density_anomaly"]:
            raise ValueError("thermal density anomaly exceeds Boussinesq control support")
        load, moment = _moments(h, rho*(1-db), rho*(1-dt))
        rm, g = datum.mantle_density_kg_m3, datum.gravity_m_s2
        fill = (datum.pressure_pa/g-load)/rm
        if np.any(fill < 0):
            raise ValueError("column extends below supported compensation pressure")
        # Algebraically subtract the common pure-mantle column BEFORE evaluation.
        # Avoid cancellation between two ~1e15 J/m2 absolute energies.
        anomaly = g*(moment-load*load/(2*rm))
        result = dict(surface_elevation_m=datum.compensation_elevation_m+fill+h.sum(axis=1),
            mantle_fill_m=fill, gpe_anomaly_j_m2=anomaly,
            effective_rock_load_kg_m2=load,
            reference_rock_mass_kg_m2=(rho*h).sum(axis=1),
            pressure_residual_pa=g*(rm*fill+load)-datum.pressure_pa)
    if not all(np.all(np.isfinite(v)) for v in result.values()):
        raise ValueError("column result not representable")
    return result


def immutable(a):
    return np.frombuffer(a.tobytes(), dtype=float).reshape(a.shape)


@dataclass(frozen=True)
class SphericalStencil:
    """Reusable central great-circle differences; no interpolation or pole divide.

    Callers sample their physical columns at sample_directions, shape (N,2,2,3):
    point, minus/plus, tangent axis, xyz. Discontinuous fields need a separately
    resolved interface; this control does not infer or smooth jumps.
    """
    directions: np.ndarray = field(repr=False, compare=False)
    angular_step_rad: float
    sample_directions: np.ndarray = field(init=False, repr=False, compare=False)
    tangents: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        n = real_array(self.directions)
        delta = number(self.angular_step_rad, "angular step", positive=True)
        if (n.ndim != 2 or n.shape[1] != 3 or not 1 <= len(n) <= POLICY["max_stencil_points"]
                or delta > .1 or np.max(np.abs(np.linalg.norm(n, axis=1)-1)) > 1e-12):
            raise ValueError("bounded unit directions and 0 < angular step <= .1 required")
        # Least-aligned Cartesian axis keeps the cross product away from zero.
        axis = np.eye(3)[np.argmin(np.abs(n), axis=1)]
        e1 = np.cross(n, axis)
        e1 /= np.linalg.norm(e1, axis=1)[:, None]
        tangents = np.stack((e1, np.cross(n, e1)), axis=1)
        offsets = math.sin(delta)*tangents
        samples = np.stack((math.cos(delta)*n[:, None]-offsets,
                            math.cos(delta)*n[:, None]+offsets), axis=1)
        object.__setattr__(self, "angular_step_rad", delta)
        for name, a in (("directions", n), ("tangents", tangents), ("sample_directions", samples)):
            object.__setattr__(self, name, immutable(a))

    def traction(self, sampled_gpe_j_m2, *, radius_m, reduction):
        radius = number(radius_m, "radius", positive=True)
        gamma = number(reduction, "common L0/L", positive=True)
        u = real_array(sampled_gpe_j_m2)
        if u.shape != self.sample_directions.shape[:-1]:
            raise ValueError("GPE samples must match the prepared stencil")
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            gradient = (u[:, 1]-u[:, 0])/(2*self.angular_step_rad*radius)
            result = -gamma*np.einsum("ni,nij->nj", gradient, self.tangents)
        if not np.all(np.isfinite(result)):
            raise ValueError("traction not representable")
        return result


def _quadrature(order):
    """Two hemispheres, independent Gauss-Legendre mu and periodic longitude."""
    if type(order) is not int or not 4 <= order <= 32:
        raise ValueError("hemisphere order must be 4..32")
    x, w = np.polynomial.legendre.leggauss(order)
    mu = np.r_[-(x+1)/2, (x+1)/2]
    phi = np.arange(4*order)*2*np.pi/(4*order)
    z, p = np.meshgrid(mu, phi, indexing="ij")
    n = np.stack((np.sqrt(1-z*z)*np.cos(p), np.sqrt(1-z*z)*np.sin(p), z), axis=-1)
    weight = np.repeat(np.tile(w/2, 2), len(phi))*2*np.pi/len(phi)
    return n.reshape(-1, 3), weight


def sphere_control(spec, order):
    """A manufactured crust field feeds the retained D1 solver, not imposed torque."""
    start = time.perf_counter()
    datum = Datum(**spec["datum"])
    n, weights = _quadrature(order)
    radius, gamma, drag = spec["radius_m"], spec["reduction"], spec["drag_pa_s_m"]
    stencil = SphericalStencil(n, np.pi/(8*order))
    directions = stencil.sample_directions.reshape(-1, 3)
    h0, amplitude, rho = spec["mean_crust_m"], spec["thickness_squared_amplitude_m2"], spec["crust_density_kg_m3"]
    h = np.sqrt(h0*h0+amplitude*directions[:, 0])[:, None]
    state = columns(datum, h, rho, 0., 1000., 1000.)
    traction = stencil.traction(state["gpe_anomaly_j_m2"].reshape(len(n), 2, 2),
                                radius_m=radius, reduction=gamma)
    r, area = n*radius, weights*radius**2
    coefficient = .5*datum.gravity_m_s2*rho*(1-rho/datum.mantle_density_kg_m3)*amplitude
    torques, omegas, errors, work_errors = [], [], [], []
    for sign in (-1, 1):
        mask = n[:, 2]*sign > 0
        torque = np.sum(np.cross(r[mask], traction[mask])*area[mask, None], axis=0)
        matrix = drag_matrix(r[mask], area[mask], drag)
        omega = solve_torque(matrix, torque)
        exact_torque = -gamma*coefficient*np.pi*radius**2*np.array([0., sign, 0.])
        exact_omega = exact_torque/(4*np.pi/3*drag*radius**4)
        errors.append(float(np.linalg.norm(omega-exact_omega)/np.linalg.norm(exact_omega)))
        velocity = np.cross(omega, r[mask])
        power = float(torque@omega)
        distributed = float(np.sum(area[mask]*np.einsum("ij,ij->i", traction[mask], velocity)))
        dissipated = float(np.sum(area[mask]*drag*np.sum(velocity**2, axis=1)))
        work_errors.append(max(abs(power-distributed), abs(power-dissipated))/power)
        torques.append(torque)
        omegas.append(omega.tolist())
    cancellation = float(np.linalg.norm(np.sum(torques, axis=0))/np.linalg.norm(torques[0]))
    return dict(order=order, quadrature_points=len(n), column_samples=len(h),
        angular_step_rad=stencil.angular_step_rad, relative_rotation_error=max(errors),
        expected_central_difference_error=1-math.sin(stencil.angular_step_rad)/stencil.angular_step_rad,
        global_torque_cancellation_relative=cancellation, work_relative=max(work_errors),
        pressure_residual_relative=float(np.max(np.abs(state["pressure_residual_pa"]))/datum.pressure_pa),
        angular_velocities_rad_s=omegas, seconds=time.perf_counter()-start)


def _loop_moments(h, rb, rt):
    """Same exact formula as production, scalar-loop performance comparator."""
    load, moment = np.zeros(len(h)), np.zeros(len(h))
    for i in range(len(h)):
        base = 0.
        for j in range(h.shape[1]):
            height, bottom, top = h[i, j], rb[i, j], rt[i, j]
            mass = height*(bottom+top)/2
            load[i] += mass
            moment[i] += base*mass+height*height*(bottom+2*top)/6
            base += height
    return load, moment


def campaign(spec):
    controls = [sphere_control(spec, order) for order in spec["orders"]]
    # Five interleaved comparisons on equal, prevalidated inputs. No cache
    # disabled, no weaker arithmetic, and no expensive process parallelism.
    n = spec["benchmark_columns"]
    x = np.arange(n)[:, None]/n
    h = np.broadcast_to(np.array([60e3, 20e3, 15e3])*(1+.1*np.sin(2*np.pi*x)), (n, 3)).copy()
    rb = np.broadcast_to([3250., 2900., 2700.], h.shape)
    rt = np.broadcast_to([3280., 2930., 2740.], h.shape)
    times = {"scalar": [], "vectorised": []}
    answers = {}
    for repeat in range(POLICY["benchmark_repetitions"]):
        methods = [("scalar", _loop_moments), ("vectorised", _moments)]
        for name, method in methods[::1 if repeat % 2 == 0 else -1]:
            start = time.perf_counter()
            answers[name] = method(h, rb, rt)
            times[name].append(time.perf_counter()-start)
    parity = max(float(np.max(np.abs(a-b))/max(1., np.max(np.abs(a))))
                 for a, b in zip(answers["scalar"], answers["vectorised"]))
    slow, fast = (float(np.median(times[k])) for k in ("scalar", "vectorised"))
    errors = [c["relative_rotation_error"] for c in controls]
    ratios = [a/b for a, b in zip(errors[:-1], errors[1:])]
    passed = (errors[-1] < POLICY["finest_torque_relative"] and all(3.8 < r < 4.2 for r in ratios)
        and all(max(c["global_torque_cancellation_relative"], c["work_relative"],
                    c["pressure_residual_relative"]) < POLICY["algebra_relative"] for c in controls)
        and parity < POLICY["algebra_relative"])
    return dict(passed=bool(passed), controls=controls, refinement_error_ratios=ratios,
        benchmark=dict(columns=n, layers=3, samples_seconds=times, scalar_median_seconds=slow,
            vectorised_median_seconds=fast, saved_seconds=slow-fast, saved_percent=100*(slow-fast)/slow,
            maximum_relative_difference=parity,
            scope="prevalidated exact column moment kernel only; not whole-world runtime"))


def bindings():
    names = ["tools/check_i01_gpe.py", "tests/test_i01_gpe.py", "cases/i01_gpe_v1.json",
             "docs/I01_GPE.md", "tools/check_i01_closures.py"]
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        start = time.perf_counter()
        report = dict(schema="atlas.i01-gpe.v1", status="INCOMPLETE", scientific_acceptance=False,
            runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                         system=platform.system()))
        try:
            report["source_sha256"] = bindings()
            spec = json.loads((ROOT/"cases/i01_gpe_v1.json").read_text(encoding="utf-8"))
            if spec["policy"] != POLICY:
                raise ValueError("case policy differs from executable")
            report.update(campaign(spec))
            report["source_unchanged"] = report["source_sha256"] == bindings()
            report["status"] = "PASS_BOUNDED_CONTROLS_ONLY" if report["passed"] and report["source_unchanged"] else "FAIL"
        except Exception as exc:
            report.update(status="FAIL", error_type=type(exc).__name__, error=str(exc))
        report["elapsed_seconds"] = time.perf_counter()-start
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps({k: report[k] for k in ("status", "elapsed_seconds")}))
    return 0 if report["status"] == "PASS_BOUNDED_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
