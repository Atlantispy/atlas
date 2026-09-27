"""I01 nonlinear constitutive/column controls, WORKING NON-CANON.

Prescribed pressure/temperature snapshots; no momentum, rupture or heat evolution.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from concurrent.futures import CancelledError
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
R = 8.31446261815324
POLICY = {"rate_relative_tolerance": 2e-11, "iterations": 96,
          "max_layers": 64, "max_mechanisms": 4, "max_order": 128,
          "column_refinement_tolerance": 0.003, "benchmark_repetitions": 10}


def number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, (bool, str, bytes)):
        raise ValueError(name+" must be a number")
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0) or (nonnegative and value < 0):
        raise ValueError(name+" outside finite support")
    return value


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError("column control cancelled; no result published")


def laboratory_prefactor(a, n, *, stress_unit_pa, grain_exponent=0., grain_unit_m=1.):
    """Axial lab rate/differential stress -> tensor invariants, SI units.

    Only use for that declared laboratory convention, never on ASPECT's already
    converted coefficients. A_II=3**((n+1)/2)/2*A_lab*S**(-n)*L**m.
    """
    a = number(a, "lab prefactor", positive=True)
    n = number(n, "stress exponent", positive=True)
    s = number(stress_unit_pa, "stress unit", positive=True)
    d = number(grain_unit_m, "grain unit", positive=True)
    m = number(grain_exponent, "grain exponent", nonnegative=True)
    out = math.exp(math.log(a)+(n+1)/2*math.log(3)-math.log(2)-n*math.log(s)+m*math.log(d))
    return number(out, "converted prefactor", positive=True)


@dataclass(frozen=True)
class Creep:
    a: float  # Already SI and invariant, Pa^-n m^m /s.
    n: float
    energy_j_mol: float
    volume_m3_mol: float = 0.
    grain_exponent: float = 0.

    def __post_init__(self):
        for key in ("a", "n", "energy_j_mol", "volume_m3_mol", "grain_exponent"):
            val = number(getattr(self, key), key, positive=key in ("a", "n"),
                         nonnegative=key not in ("a", "n"))
            object.__setattr__(self, key, val)
        if not 1 <= self.n <= 8 or self.grain_exponent > 4:
            raise ValueError("supported stress exponents 1..8 and grain exponents 0..4")


@dataclass(frozen=True)
class LocalLaw:
    log_coefficients: tuple[float, ...]
    exponents: tuple[float, ...]
    yield_pa: float
    plastic_viscosity_pa_s: float | None

    def __post_init__(self):
        if (type(self.log_coefficients) is not tuple or type(self.exponents) is not tuple
                or not 1 <= len(self.exponents) <= POLICY["max_mechanisms"]
                or len(self.exponents) != len(self.log_coefficients)):
            raise ValueError("matching bounded immutable mechanism coefficients required")
        for c, n in zip(self.log_coefficients, self.exponents):
            number(c, "log coefficient")
            if not 1 <= number(n, "exponent") <= 8:
                raise ValueError("stress exponents must be 1..8")
        number(self.yield_pa, "yield", nonnegative=True)
        if self.plastic_viscosity_pa_s is not None:
            number(self.plastic_viscosity_pa_s, "plastic viscosity", positive=True)

    @classmethod
    def prepare(cls, mechanisms, temperature_k, mean_pressure_pa, *,
                grain_m, cohesion_pa, friction_rad, pore_pressure_pa,
                plastic_viscosity_pa_s):
        if type(mechanisms) is not tuple or not 1 <= len(mechanisms) <= POLICY["max_mechanisms"]:
            raise ValueError("one to four immutable creep mechanisms required")
        if any(type(law) is not Creep for law in mechanisms):
            raise ValueError("typed creep mechanisms required")
        t = number(temperature_k, "temperature", positive=True)
        p = number(mean_pressure_pa, "absolute mean pressure", nonnegative=True)
        grain = number(grain_m, "grain size", positive=True)
        c = number(cohesion_pa, "cohesion", nonnegative=True)
        phi = number(friction_rad, "friction", nonnegative=True)
        if phi >= math.pi/2:
            raise ValueError("friction must be less than pi/2 radians")
        pore = number(pore_pressure_pa, "pore pressure", nonnegative=True)
        eta = None if plastic_viscosity_pa_s is None else number(
            plastic_viscosity_pa_s, "plastic viscosity", positive=True)
        y = number(c*math.cos(phi)+max(p-pore, 0.)*math.sin(phi), "yield", nonnegative=True)
        coefficients = tuple(number(math.log(law.a)-law.grain_exponent*math.log(grain)
            -(law.energy_j_mol+p*law.volume_m3_mol)/(R*t), "log creep coefficient") for law in mechanisms)
        return cls(coefficients, tuple(law.n for law in mechanisms), y, eta)

    def solve(self, strain_rate_s, *, method="newton", cancel=None):
        check_cancel(cancel)
        rate = number(strain_rate_s, "strain-rate invariant", nonnegative=True)
        if method not in ("newton", "bisection"):
            raise ValueError("unknown scalar method")
        if rate == 0:
            return dict(stress_pa=0., creep_rates_s=(0.,)*len(self.exponents),
                        plastic_rate_s=0., tangent_pa_s=None, iterations=0, rate_residual=0.)
        le = math.log(rate)
        bounds = [(le-c)/n for c, n in zip(self.log_coefficients, self.exponents)]
        eta, y = self.plastic_viscosity_pa_s, self.yield_pa
        if eta is not None:
            # log(Y + 2 eta eps), without overflowing a dimensional product.
            p = math.log(2)+math.log(eta)+le
            if y:
                q = math.log(y)
                p = max(p, q)+math.log1p(math.exp(-abs(p-q)))
            bounds.append(p)
        hi = min(bounds)
        lo = hi-math.log(len(bounds))
        if not -700 < lo <= hi < 700:
            raise ValueError("stress outside bounded representable support")
        x = hi
        for iteration in range(POLICY["iterations"]):
            check_cancel(cancel)
            tau = math.exp(x)
            scaled = tuple(math.exp(c+n*x-le) for c, n in zip(self.log_coefficients, self.exponents))
            plastic, derivative = 0., math.fsum(n*r for n, r in zip(self.exponents, scaled))
            if eta is not None and tau > y:
                # Do not form 0 * tau/(tau-Y) at the yield corner.
                inv = math.exp(-math.log(2)-math.log(eta)-le)
                plastic = (tau-y)*inv
                derivative += tau*inv
            total = math.fsum((*scaled, plastic))
            residual = total-1.
            if abs(residual) <= POLICY["rate_relative_tolerance"]:
                tangent = tau/rate/derivative
                if not math.isfinite(tangent) or tangent <= 0:
                    raise ValueError("constitutive tangent not representable")
                return dict(stress_pa=tau, creep_rates_s=tuple(r*rate for r in scaled),
                    plastic_rate_s=plastic*rate, tangent_pa_s=tangent,
                    iterations=iteration+1, rate_residual=residual)
            if residual > 0:
                hi = x
            else:
                lo = x
            trial = x-math.log(total)/(derivative/total) if method == "newton" else math.nan
            candidate = trial if lo < trial < hi else (lo+hi)/2
            if candidate == x:
                raise ValueError("scalar stress resolution exhausted before convergence")
            x = candidate
        raise ValueError("scalar creep/plasticity solve did not converge")


@dataclass(frozen=True, slots=True, init=False)
class Column:
    """Immutable prepared quadrature of supplied fields; no implicit reuse key.

    Every property/temperature/pressure/profile change requires a new Column.
    Only strain-rate changes can reuse this prepared constitutive snapshot.
    """
    points: tuple
    thickness_m: float
    order: int

    def __init__(self, layers, order=64):
        if type(layers) is not list or not 1 <= len(layers) <= POLICY["max_layers"]:
            raise ValueError("one to 64 layers required")
        if type(order) is not int or not 2 <= order <= POLICY["max_order"]:
            raise ValueError("quadrature order must be 2..128")
        nodes, weights = np.polynomial.legendre.leggauss(order)
        points, thickness = [], 0.
        for layer in layers:
            h = number(layer["thickness_m"], "thickness", positive=True)
            t0, t1 = (number(v, "temperature", positive=True) for v in layer["temperature_k"])
            p0, p1 = (number(v, "mean pressure", nonnegative=True) for v in layer["mean_pressure_pa"])
            w0, w1 = (number(v, "pore pressure", nonnegative=True) for v in layer["pore_pressure_pa"])
            mechanisms = tuple(Creep(**law) for law in layer["creep"])
            for node, weight in zip(nodes, weights):
                f = (float(node)+1)/2
                law = LocalLaw.prepare(mechanisms, t0*(1-f)+t1*f, p0*(1-f)+p1*f,
                    grain_m=layer["grain_m"], cohesion_pa=layer["cohesion_pa"],
                    friction_rad=layer["friction_rad"], pore_pressure_pa=w0*(1-f)+w1*f,
                    plastic_viscosity_pa_s=layer["plastic_viscosity_pa_s"])
                points.append((number(float(weight)*h/2, "quadrature weight", positive=True), law))
            thickness += h
        object.__setattr__(self, "points", tuple(points))
        object.__setattr__(self, "thickness_m", number(thickness, "total thickness", positive=True))
        object.__setattr__(self, "order", order)

    def solve(self, axial_rate_s, *, method="newton", cancel=None):
        e = number(axial_rate_s, "signed axial rate")
        stresses, creep_work, plastic_work, iterations = [], [], [], 0
        for weight, law in self.points:
            result = law.solve(abs(e), method=method, cancel=cancel)
            s = result["stress_pa"]
            stresses.append(2*weight*s)
            creep_work.append(2*weight*s*math.fsum(result["creep_rates_s"]))
            plastic_work.append(2*weight*s*result["plastic_rate_s"])
            iterations += result["iterations"]
        force = math.copysign(math.fsum(stresses), e) if e else 0.
        work = number(force*e, "work per area", nonnegative=True)
        viscous, plastic = math.fsum(creep_work), math.fsum(plastic_work)
        residual = abs(viscous+plastic-work)/work if work else 0.
        if residual > 2*POLICY["rate_relative_tolerance"]:
            raise ValueError("constitutive work partition failed")
        return dict(force_n_m=force, work_w_m2=work, creep_work_w_m2=viscous,
                    plastic_work_w_m2=plastic, work_relative_residual=residual,
                    scalar_iterations=iterations, quadrature_points=len(self.points))


def campaign(spec):
    rate = spec["axial_rate_s"]
    coarse, fine = Column(spec["layers"], 64), Column(spec["layers"], 128)
    start = time.perf_counter()
    a, b = coarse.solve(rate), fine.solve(rate)
    solve_s = time.perf_counter()-start
    relative = abs(a["force_n_m"]-b["force_n_m"])/abs(b["force_n_m"])
    warm_layers = json.loads(json.dumps(spec["layers"]))
    for layer in warm_layers:
        layer["temperature_k"] = [t+100. for t in layer["temperature_k"]]
    warm = Column(warm_layers, 128).solve(rate)
    faster = fine.solve(10*rate)
    # Identical prepared coefficients/nodes/tolerances; compare only root algorithm.
    sample = LocalLaw.prepare((Creep(1e-25, 1., 0.), Creep(1e-40, 3.5, 0.)),
        1000., 1e8, grain_m=.001, cohesion_pa=1e6, friction_rad=.5,
        pore_pressure_pa=0., plastic_viscosity_pa_s=1e21)
    observed = {}
    for method in ("bisection", "newton"):
        start = time.perf_counter()
        answers = [sample.solve(rate*(1+i/10), method=method)
                   for i in range(POLICY["benchmark_repetitions"])]
        observed[method] = dict(seconds=time.perf_counter()-start,
            stresses=[r["stress_pa"] for r in answers], iterations=sum(r["iterations"] for r in answers))
    baseline, new = observed["bisection"], observed["newton"]
    error = max(abs(x-y)/abs(x) for x, y in zip(baseline["stresses"], new["stresses"]))
    passed = (relative <= POLICY["column_refinement_tolerance"] and
        0 < warm["force_n_m"] < b["force_n_m"] < faster["force_n_m"] and error < 5e-11)
    return dict(passed=bool(passed), column_64=a, column_128=b, warm_100k=warm,
        tenfold_rate=faster, column_refinement_relative_change=relative,
        paired_column_seconds=solve_s, benchmark=dict(**observed,
            max_stress_relative_difference=error,
            saved_seconds=baseline["seconds"]-new["seconds"],
            saved_percent=100*(baseline["seconds"]-new["seconds"])/baseline["seconds"],
            scope="one ten-solve prepared local-law comparison, not generator speedup"))


def bindings():
    names = ["tools/check_i01_column.py", "tests/test_i01_column.py",
             "cases/i01_column_v1.json", "docs/I01_COLUMN.md"]
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        start = time.perf_counter()
        report = dict(schema="atlas.i01-column.v1", status="INCOMPLETE", scientific_acceptance=False,
            runtime=dict(python=platform.python_version(), numpy=np.__version__, system=platform.system()))
        try:
            report["source_sha256"] = bindings()
            spec = json.loads((ROOT/"cases/i01_column_v1.json").read_text(encoding="utf-8"))
            if spec["policy"] != POLICY:
                raise ValueError("case policy differs from executable")
            report.update(campaign(spec))
            report["source_unchanged"] = report["source_sha256"] == bindings()
            report["status"] = "PASS_BOUNDED_CONTROLS_ONLY" if report["passed"] and report["source_unchanged"] else "FAIL"
        except Exception as exc:
            report.update(status="FAIL", error_type=type(exc).__name__)
        report["elapsed_seconds"] = time.perf_counter()-start
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps({k: report[k] for k in ("status", "elapsed_seconds")}))
    return 0 if report["status"] == "PASS_BOUNDED_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
