"""I01 retained elastic memory: exact coaxial Maxwell controls, not a rift solver.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass, asdict
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import time

ROOT = Path(__file__).resolve().parents[1]
KINEMATICS = "coaxial_stretch_plus_rigid_rotation"
POLICY = {"elastic_strain_limit": 0.01, "log_stretch_limit": 1.0,
          "maximum_z": 1e6, "relative_tolerance": 2e-12,
          "maximum_seconds": 10.0, "benchmark_calls": 2000, "benchmark_repeats": 5}
PSI = tuple((-1.)**k/math.factorial(k+2) for k in range(18))
CHI = tuple((-1.)**k/math.factorial(k+3) for k in range(18))
VAR = tuple((-1.)**k*(2**(k+2)*k+2)/math.factorial(k+4) for k in range(18))


def real(value, name, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(name+": finite real required")
    value = float(value)
    if positive and value <= 0:
        raise ValueError(name+": positive value required")
    return value


def horner(coefficients, z):
    value = 0.
    for c in reversed(coefficients):
        value = value*z+c
    return value


@dataclass(frozen=True)
class State:
    """Constructed F=R(axis) diag(exp(log_stretch), exp(-log_stretch),1).

    Stress is R diag(s,-s,0) R^T. No independent shear/stretch axes are accepted.
    This is a local material history; no spatial transport or persistence.
    """
    stress_pa: float
    axis_rad: float
    log_stretch: float
    shear_modulus_pa: float
    time_s: float = 0.

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, real(getattr(self, name), name, name == "shear_modulus_pa"))
        if self.time_s < 0 or abs(self.log_stretch) > POLICY["log_stretch_limit"]:
            raise ValueError("state outside time/stretch support")
        if abs(self.stress_pa)/self.shear_modulus_pa/2 > POLICY["elastic_strain_limit"]:
            raise ValueError("elastic strain outside declared support")
        object.__setattr__(self, "axis_rad", math.remainder(self.axis_rad, 2*math.pi))

    def tensor(self):
        c, s = math.cos(2*self.axis_rad), math.sin(2*self.axis_rad)
        return ((self.stress_pa*c, self.stress_pa*s), (self.stress_pa*s, -self.stress_pa*c))

    def energy(self):
        return real((self.stress_pa/self.shear_modulus_pa)*self.stress_pa/2, "stored energy")


@dataclass(frozen=True, init=False)
class Prepared:
    """Immutable coefficients reused only for identical G, eta and dt.

    eta=None is an explicitly elastic control, never a large-viscosity cutoff.
    Positive finite eta retains its actual relaxation time.
    """
    shear_modulus_pa: float
    viscosity_pa_s: float | None
    dt_s: float
    z: float
    decay: float
    loss: float
    phi: float
    psi: float
    chi: float
    variance: float

    def __init__(self, shear_modulus_pa, viscosity_pa_s, dt_s):
        g = real(shear_modulus_pa, "G", True)
        dt = real(dt_s, "dt", True)
        eta = None if viscosity_pa_s is None else real(viscosity_pa_s, "eta", True)
        gd = real(g*dt, "G dt", True)
        z = 0. if eta is None else real(gd/eta, "dt / relaxation time", True)
        if z > POLICY["maximum_z"]:
            raise ValueError("dimensionless interval outside numeric support")
        a, loss = math.exp(-z), -math.expm1(-z)
        phi = loss/z if z else 1.
        psi = horner(PSI, z) if z <= .5 else (1-phi)/z
        chi = horner(CHI, z) if z <= .5 else (.5-psi)/z
        var = horner(VAR, z) if z <= .5 else -math.expm1(-2*z)/(2*z)-phi*phi
        if not (psi > 0 and var > 0):
            raise ValueError("unresolved integral coefficients")
        for name, value in zip(self.__dataclass_fields__, (g, eta, dt, z, a, loss, phi, psi, chi, var)):
            object.__setattr__(self, name, value)

    def advance(self, state, principal_rate_s, rigid_rotation_rad=0., *, kinematics):
        if kinematics != KINEMATICS:
            raise ValueError("noncoaxial history requires the resolved finite-strain constitutive route")
        if type(state) is not State or state.shear_modulus_pa != self.shear_modulus_pa:
            raise ValueError("state modulus differs: changing stored energy requires an owned material law")
        e = real(principal_rate_s, "principal stretching rate")
        angle = real(rigid_rotation_rad, "superposed rigid rotation")
        if abs(angle) > 2*math.pi:
            raise ValueError("split rotations larger than one turn")
        s, g, dt, z = state.stress_pa, self.shear_modulus_pa, self.dt_s, self.z
        c = real(2*(g*dt)*e, "elastic loading increment")
        if z <= .5:
            end = math.fsum((self.decay*s, self.phi*c))
            # Centre the elastic path first; retain tiny work under load reversal.
            mean = math.fsum((s, c/2, -z*math.fsum((self.psi*s, self.chi*c))))
            variation = real(math.fsum((c, -z*s)), "stress variation")
            delta = self.phi*variation
            endpoint_sum = math.fsum((2*s, c, -z*mean))
            variance_term = self.variance*variation*variation
        else:
            steady = real(2*self.viscosity_pa_s*e, "steady stress")
            end = math.fsum((self.decay*s, self.loss*steady))
            mean = math.fsum((self.phi*s, (1-self.phi)*steady))
            variance_term = self.variance*(s-steady)*(s-steady)
            delta = self.loss*(steady-s)
            endpoint_sum = math.fsum((s, steady, self.decay*(s-steady)))
        new_time = real(state.time_s+dt, "new time")
        if new_time <= state.time_s:
            raise ValueError("interval is not representable at this clock")
        next_state = State(end, state.axis_rad+angle, state.log_stretch+e*dt, g, new_time)
        # Positive mean/variance integral; NOT heat = work minus elastic energy.
        heat = 0. if self.viscosity_pa_s is None else real(
            (dt/self.viscosity_pa_s)*(mean*mean+variance_term), "viscous heat")
        work = real(2*(dt*e)*mean, "mechanical work")
        stored_change = real(delta*(endpoint_sum/g/2), "stored-energy change")
        residual = math.fsum((work, -stored_change, -heat))
        scale = max(abs(work)+abs(stored_change)+abs(heat), 1e-300)
        if heat < 0 or abs(residual) > POLICY["relative_tolerance"]*scale:
            raise ValueError("unresolved mechanical/thermal balance")
        return {"state": next_state, "mean_stress_pa": mean, "work_j_m3": work,
                "heat_j_m3": heat, "stored_change_j_m3": stored_change,
                "balance_residual_j_m3": residual, "elasticity_omitted": False}


def bindings():
    names = ("tools/check_i01_elastic_memory.py", "tests/test_i01_elastic_memory.py",
             "cases/i01_elastic_memory_v1.json", "docs/I01_ELASTIC_MEMORY.md")
    return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}


def controls(spec):
    if spec != {"schema": "atlas.i01-elastic-memory-case.v1", "policy": POLICY,
                "kinematics": KINEMATICS, "fixture": {"G_pa": 3e10, "eta_pa_s": 3e21,
                "dt_s": 1e11, "stress_pa": 1e7, "rate_s": 1e-15}}:
        raise ValueError("case differs from predeclared control")
    f = spec["fixture"]
    p = Prepared(f["G_pa"], f["eta_pa_s"], f["dt_s"])
    state = State(f["stress_pa"], 0., 0., f["G_pa"])
    kw = {"kinematics": KINEMATICS}
    relax = p.advance(state, 0., **kw)
    loaded = p.advance(state, f["rate_s"], **kw)
    forgotten = p.advance(State(0., 0., 0., f["G_pa"]), f["rate_s"], **kw)
    elastic = Prepared(f["G_pa"], None, f["dt_s"]).advance(state, 0., math.pi/4, **kw)
    near = lambda a,b: abs(a-b) <= POLICY["relative_tolerance"]*max(abs(a), abs(b), 1e-300)
    checks = {"relaxation": near(relax["state"].stress_pa, f["stress_pa"]/math.e),
              "released_stored_heat": near(relax["heat_j_m3"], state.energy()*(1-math.exp(-2))),
              "memory_not_reset": near(loaded["state"].stress_pa-forgotten["state"].stress_pa,
                                       f["stress_pa"]/math.e),
              "rigid_rotation_no_heat": elastic["heat_j_m3"] == 0. and elastic["work_j_m3"] == 0.,
              "tensor_rotation": near(elastic["state"].tensor()[0][1], f["stress_pa"])}
    for route in ("general_shear", "jaumann_generic", "omit_elasticity"):
        try:
            p.advance(state, f["rate_s"], kinematics=route)
        except ValueError:
            checks[route+"_refused"] = True
        else:
            checks[route+"_refused"] = False
    deadline = time.perf_counter()+POLICY["maximum_seconds"]
    samples = {"prepared": [], "rebuilt": []}
    results = {}
    for rep in range(POLICY["benchmark_repeats"]):
        for mode in (("prepared", "rebuilt") if rep % 2 == 0 else ("rebuilt", "prepared")):
            begin = time.perf_counter()
            for _ in range(POLICY["benchmark_calls"]):
                op = p if mode == "prepared" else Prepared(f["G_pa"], f["eta_pa_s"], f["dt_s"])
                results[mode] = op.advance(state, f["rate_s"], **kw)
            samples[mode].append(time.perf_counter()-begin)
            if time.perf_counter() > deadline:
                raise ValueError("bounded campaign deadline exceeded")
    checks["reuse_bitwise_parity"] = results["prepared"] == results["rebuilt"]
    med = {k: statistics.median(v) for k,v in samples.items()}
    return {"passed": all(checks.values()), "checks": checks,
            "retained_memory_stress_pa": loaded["state"].stress_pa-forgotten["state"].stress_pa,
            "relaxation_heat_j_m3": relax["heat_j_m3"],
            "fixture_endpoint": asdict(loaded["state"]),
            "benchmark": {"seconds": samples, "medians_s": med,
                          "saved_s": med["rebuilt"]-med["prepared"],
                          "saved_percent": 100*(1-med["prepared"]/med["rebuilt"]),
                          "scope": "2000 independent identical local updates; setup reuse, not world speedup"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        start = time.perf_counter()
        result = {"schema": "atlas.i01-elastic-memory-control.v1", "status": "INCOMPLETE",
                  "scientific_acceptance": False, "resolved_neck": False,
                  "runtime": {"python": platform.python_version(), "system": platform.system()}}
        try:
            result["source_sha256"] = bindings()
            spec = json.loads((ROOT/"cases/i01_elastic_memory_v1.json").read_text(encoding="utf-8"))
            result.update(controls(spec))
            result["source_unchanged"] = result["source_sha256"] == bindings()
            result["status"] = "PASS_BOUNDED_CONTROLS_ONLY" if (result["passed"] and result["source_unchanged"]
                and time.perf_counter()-start <= POLICY["maximum_seconds"]) else "FAIL"
        except Exception as exc:
            result.update(status="FAIL", error_type=type(exc).__name__)
        result["elapsed_seconds"] = time.perf_counter()-start
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("status", "elapsed_seconds")}))
    return 0 if result["status"] == "PASS_BOUNDED_CONTROLS_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
