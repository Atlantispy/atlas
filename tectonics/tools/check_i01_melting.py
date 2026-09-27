"""I01 dry retained-melt decompression controls, WORKING NON-CANON.

Katz et al. (2003) dry equilibrium fractions and approximate isentropic path.
No extraction, melt transport, crust production or native/world integration.
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
import scipy
from scipy.integrate import RK45, DOP853
from scipy.optimize import brentq

ROOT = Path(__file__).resolve().parents[1]
POLICY = dict(max_steps=256, max_evaluations=4096, max_pressure_gpa=3.5,
              max_fraction=0.4, relative_tolerance=1e-8,
              temperature_tolerance_k=0.002, fraction_tolerance=2e-6,
              path_residual_tolerance_j_kg_k=0.003,
              benchmark_repetitions=5)


def number(value, name, *, positive=False):
    if isinstance(value, (bool, str, bytes)):
        raise ValueError(name + " must be a number")
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(name + " outside finite support")
    return value


@dataclass(frozen=True)
class Model:
    """Dry fixed-composition batch parcel; fractions are mass fractions.

    Published Table 2 defaults. Modal cpx 0.15 is an explicit composition choice.
    cp and thermal expansion/density remain constant within each phase.
    """
    modal_cpx: float = 0.15
    cp_j_kg_k: float = 1000.
    entropy_fusion_j_kg_k: float = 300.
    alpha_s_k: float = 40e-6
    alpha_f_k: float = 68e-6
    rho_s_kg_m3: float = 3300.
    rho_f_kg_m3: float = 2900.

    def __post_init__(self):
        for key in self.__dataclass_fields__:
            object.__setattr__(self, key, number(getattr(self, key), key, positive=True))
        if not 0.01 <= self.modal_cpx <= 0.2:
            raise ValueError("modal cpx supported only within 0.01..0.2")

    def expansion(self, fraction):
        return ((1-fraction)*self.alpha_s_k/self.rho_s_kg_m3
                + fraction*self.alpha_f_k/self.rho_f_kg_m3)

    def phase(self, pressure_gpa, temperature_k):
        """Return F, dF/dT [/K], dF/dP [/GPa], and named branch.

        The derivatives are differentiated from equations 2--9, including the
        moving cpx-exhaustion fraction/temperature; no finite differences.
        """
        p = number(pressure_gpa, "pressure")
        t = number(temperature_k, "temperature", positive=True)
        if not 0 <= p <= POLICY["max_pressure_gpa"]:
            raise ValueError("pressure outside 0..3.5 GPa")
        s = 1085.7 + 132.9*p - 5.1*p*p + 273.15
        b = 1475. + 80.*p - 3.2*p*p + 273.15
        l = 1780. + 45.*p - 2.*p*p + 273.15
        sp, bp, lp = 132.9-10.2*p, 80.-6.4*p, 45.-4.*p
        r = 0.5+0.08*p
        fc, fcp = self.modal_cpx/r, -self.modal_cpx*0.08/(r*r)
        u = fc**(2/3)
        c = s+u*(b-s)
        cp = sp+u*(bp-sp)+(b-s)*(2/3)*fc**(-1/3)*fcp
        if not s < c < l:
            raise ValueError("unordered melting branches")
        if t <= s:
            return 0., 0., 0., "solid"
        if t >= l:
            return 1., 0., 0., "liquid"
        if t <= c:
            y = (t-s)/(b-s)
            ft = 1.5*math.sqrt(y)/(b-s)
            return y**1.5, ft, ft*(-sp-y*(bp-sp)), "cpx_present"
        z = (t-c)/(l-c)
        ft = (1-fc)*1.5*math.sqrt(z)/(l-c)
        fp = fcp*(1-z**1.5)+ft*(-cp-z*(lp-cp))
        return fc+(1-fc)*z**1.5, ft, fp, "cpx_exhausted"


def _trajectory(model, start_gpa, end_gpa, temperature_k, *, cancel=None,
                reference=False, finite_difference=False):
    """Bounded solver kernel; diagnostic switches are not public model options."""
    p0, p1 = number(start_gpa, "start pressure"), number(end_gpa, "end pressure")
    t0 = number(temperature_k, "initial temperature", positive=True)
    if type(model) is not Model or not 0 <= p1 < p0 <= POLICY["max_pressure_gpa"]:
        raise ValueError("typed model and decreasing supported pressure interval required")
    initial_f = model.phase(p0, t0)[0]
    if initial_f > POLICY["max_fraction"]:
        raise ValueError("initial melt fraction exceeds admitted batch support")
    evaluations = 0
    branches = set()
    cp, ds = model.cp_j_kg_k, model.entropy_fusion_j_kg_k

    def rhs(p, y):
        nonlocal evaluations
        if cancel is not None and cancel.is_set():
            raise CancelledError("melting control cancelled; no result published")
        evaluations += 1
        if evaluations > POLICY["max_evaluations"]:
            raise ValueError("melting evaluation budget exhausted")
        t = float(y[0])
        f, ft, fp, branch = model.phase(p, t)
        if f > POLICY["max_fraction"]:
            raise ValueError("melt fraction exceeds admitted batch support")
        branches.add(branch)
        if finite_difference:
            # Diagnostic baseline only: same law/controller/tolerances. Never
            # used to accept the analytic derivatives (independent tests do).
            dt, dp = 1e-3, 1e-6
            ft = (model.phase(p, t+dt)[0]-model.phase(p, t-dt)[0])/(2*dt)
            lo, hi = max(0., p-dp), min(POLICY["max_pressure_gpa"], p+dp)
            fp = (model.phase(hi, t)[0]-model.phase(lo, t)[0])/(hi-lo)
        a = model.expansion(f)*1e9  # GPa integration, SI thermal coefficients.
        denominator = cp/t+ds*ft
        if not math.isfinite(denominator) or denominator <= 0:
            raise ValueError("nonpositive thermal tangent")
        tp = (a-ds*fp)/denominator
        fp_path = fp+ft*tp
        return [tp, a, t*a, t*ds*fp_path]

    # Retain only current state and four accounts, never all RK stage histories.
    # A tighter different-order solver is a bounded independent control only.
    solver_type = DOP853 if reference else RK45
    rtol = 2e-11 if reference else POLICY["relative_tolerance"]
    atol = np.array([1e-8, 1e-8, 1e-3, 1e-3]) if reference else np.array([1e-6, 1e-6, .01, .01])
    solver = solver_type(rhs, p0, [t0, 0., 0., 0.], p1,
                         rtol=rtol, atol=atol, max_step=(p0-p1)/8)
    steps = 0
    while solver.status == "running":
        if steps >= POLICY["max_steps"]:
            raise ValueError("melting accepted-step budget exhausted")
        failure = solver.step()
        steps += 1
        if solver.status == "failed":
            raise ValueError("melting integrator failed: " + str(failure))
    t, a_path, q_adiabatic, q_latent = (float(v) for v in solver.y)
    f, _, _, final_branch = model.phase(p1, t)
    # This is a differential-path residual, NOT an absolute entropy state
    # function: A depends on F and the approximate coefficients need not be
    # thermodynamically integrable away from this path.
    path_residual = cp*math.log(t/t0)+ds*(f-initial_f)-a_path
    heat_residual = cp*(t-t0)-q_adiabatic+q_latent
    if abs(path_residual) > POLICY["path_residual_tolerance_j_kg_k"]:
        raise ValueError("approximate isentropic path accounting failed")
    if abs(heat_residual) > .01 or f < initial_f-1e-10:
        raise ValueError("thermal equation accounting or net production failed")
    return dict(temperature_k=t, initial_fraction=initial_f, final_fraction=f,
                net_produced_fraction=f-initial_f, final_branch=final_branch,
                evaluated_branches=sorted(branches), accepted_steps=steps,
                evaluations=evaluations, path_residual_j_kg_k=path_residual,
                thermal_adiabatic_j_kg=q_adiabatic, latent_term_j_kg=q_latent,
                thermal_equation_residual_j_kg=heat_residual)


def decompress(model, start_gpa, end_gpa, temperature_k, *, mass_kg, cancel=None):
    """Evolve a closed, retained-melt parcel along decreasing pressure.

    No clock is supplied: production is a mass increment, not a kg/s flux.
    An immutable Model can be reused across parcels without caching mutable
    state. Unsupported or unconverged cases raise, never return clipped output.
    """
    mass = number(mass_kg, "parcel mass", positive=True)
    result = _trajectory(model, start_gpa, end_gpa, temperature_k, cancel=cancel)
    melt = mass*result["final_fraction"]
    result.update(retained_melt_mass_kg=melt, solid_mass_kg=mass-melt,
                  net_produced_melt_kg=mass*result["net_produced_fraction"])
    if not all(math.isfinite(result[k]) for k in
               ("retained_melt_mass_kg", "solid_mass_kg", "net_produced_melt_kg")):
        raise ValueError("mass accounts not representable")
    return result


def constant_expansion_oracle(model, p0, p1, t0):
    """Independent endpoint root, valid ONLY for equal alpha/rho phases."""
    if not math.isclose(model.alpha_s_k/model.rho_s_kg_m3,
                        model.alpha_f_k/model.rho_f_kg_m3, rel_tol=1e-14):
        raise ValueError("constant-expansion oracle needs equal phase alpha/rho")
    f0 = model.phase(p0, t0)[0]
    def residual(t):
        return (model.cp_j_kg_k*math.log(t/t0)
                + model.entropy_fusion_j_kg_k*(model.phase(p1, t)[0]-f0)
                - model.expansion(0)*(p1-p0)*1e9)
    return brentq(residual, 500., t0, xtol=1e-10)


def campaign(spec):
    model = Model(**spec["model"])
    controls = []
    for case in spec["paths"]:
        args = (model, case["start_gpa"], case["end_gpa"], case["temperature_k"])
        start = time.perf_counter()
        observed = decompress(*args, mass_kg=spec["mass_kg"])
        elapsed = time.perf_counter()-start
        reference = _trajectory(*args, reference=True)
        dt = abs(observed["temperature_k"]-reference["temperature_k"])
        df = abs(observed["final_fraction"]-reference["final_fraction"])
        controls.append(dict(name=case["name"], result=observed, seconds=elapsed,
            tighter_reference=reference, temperature_difference_k=dt,
            fraction_difference=df, passed=bool(dt <= POLICY["temperature_tolerance_k"]
                and df <= POLICY["fraction_tolerance"])))
    # Unmelted exact adiabat; the hot constant-A case also crosses cpx exhaustion.
    dry = decompress(model, 3.5, .1, 1250., mass_kg=spec["mass_kg"])
    exact = 1250.*math.exp(model.expansion(0)*(-3.4e9)/model.cp_j_kg_k)
    constant = Model(alpha_f_k=model.alpha_s_k, rho_f_kg_m3=model.rho_s_kg_m3)
    hot = decompress(constant, 3.5, .1, 1780., mass_kg=spec["mass_kg"])
    oracle = constant_expansion_oracle(constant, 3.5, .1, 1780.)
    # Compare analytic derivatives with numerical differentiation, not with an
    # artificially disabled cache. Same physics, initial state and RK tolerances.
    samples = {}
    for label, numerical in (("finite_difference", True), ("analytic", False)):
        times, answers, evaluations = [], [], []
        for _ in range(POLICY["benchmark_repetitions"]):
            start = time.perf_counter()
            r = _trajectory(model, 3.5, .1, 1693., finite_difference=numerical)
            times.append(time.perf_counter()-start)
            answers.append(r["temperature_k"])
            evaluations.append(r["evaluations"])
        samples[label] = dict(median_seconds=float(np.median(times)), samples_seconds=times,
                              final_temperature_k=answers, evaluations=evaluations)
    cold, fast = samples["finite_difference"], samples["analytic"]
    saved = cold["median_seconds"]-fast["median_seconds"]
    parity = max(abs(a-b) for a, b in zip(cold["final_temperature_k"], fast["final_temperature_k"]))
    passed = (all(c["passed"] for c in controls) and abs(dry["temperature_k"]-exact) < 1e-6
              and abs(hot["temperature_k"]-oracle) < POLICY["temperature_tolerance_k"]
              and parity < POLICY["temperature_tolerance_k"])
    return dict(passed=bool(passed), controls=controls,
                exact_solid_adiabat_error_k=abs(dry["temperature_k"]-exact),
                constant_expansion_error_k=abs(hot["temperature_k"]-oracle),
                benchmark=dict(**samples, saved_seconds=saved,
                    saved_percent=100*saved/cold["median_seconds"],
                    max_temperature_difference_k=parity,
                    scope="five bounded parcel solves per method; no generator-wide speedup"))


def bindings():
    names = ["tools/check_i01_melting.py", "tests/test_i01_melting.py",
             "cases/i01_melting_v1.json", "docs/I01_MELTING.md"]
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        start = time.perf_counter()
        report = dict(schema="atlas.i01-melting.v1", status="INCOMPLETE", scientific_acceptance=False,
                      runtime=dict(python=platform.python_version(), numpy=np.__version__,
                                   scipy=scipy.__version__, system=platform.system()))
        try:
            report["source_sha256"] = bindings()
            spec = json.loads((ROOT/"cases/i01_melting_v1.json").read_text(encoding="utf-8"))
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
