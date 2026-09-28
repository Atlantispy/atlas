"""Analytical continuum verification for initiation prerequisites, not a slab model.

SPDX-License-Identifier: AGPL-3.0-only
P1 weak-form solve of -(eta*u')'=b. Stress and work are outputs, not fitted R.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
from time import perf_counter

import numpy as np
from scipy.linalg import solve_banded

from check_i01_elastic_memory import KINEMATICS, Prepared, State

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases/i01_initiation_verification_v1.json"


def real(x, name, positive=False):
    if type(x) not in (int, float) or not math.isfinite(x) or (positive and x <= 0):
        raise ValueError(name + ": finite real with required sign expected")
    return float(x)


class Channel:
    """Immutable mesh/operator reused for matching material and boundary support.

    Per unit tangential wall area: force N/m2, power W/m2. Positive u follows b.
    Bottom u=0; top either a prescribed traction or a separately declared clamp.
    The returned reaction is the discrete force conjugate to the wall velocity.
    """
    def __init__(self, height_m, viscosity_pa_s, *, top_mode):
        self.height = real(height_m, "height", True)
        eta = np.asarray(viscosity_pa_s)
        if eta.ndim != 1 or not 2 <= eta.size <= 8192 or eta.dtype.kind not in "fiu":
            raise ValueError("2..8192 real cell viscosities required")
        eta = np.array(eta, dtype=float, copy=True)
        if not np.all(np.isfinite(eta)) or np.any(eta <= 0):
            raise ValueError("positive finite viscosity required")
        if top_mode not in ("traction", "velocity"):
            raise ValueError("explicit top boundary mode required")
        self.mode = top_mode
        self.n = len(eta)
        self.dx = self.height / self.n
        self.eta = eta
        self.k = eta / self.dx
        self.x = np.linspace(0., self.height, self.n + 1)
        if not np.all(np.isfinite(self.k)) or np.any(self.k <= 0):
            raise ValueError("operator is not representable")
        count = self.n if top_mode == "traction" else self.n-1
        ab = np.zeros((3, count))
        ab[1] = (np.r_[self.k[:-1] + self.k[1:], self.k[-1]]
                 if top_mode == "traction" else self.k[:-1] + self.k[1:])
        ab[0, 1:] = -self.k[1:count]
        ab[2, :-1] = -self.k[1:count]
        self.ab = ab
        for a in (self.eta, self.k, self.x, self.ab):
            a.flags.writeable = False

    def solve(self, body_force_n_m3, *, top_value):
        b = real(body_force_n_m3, "body force")
        value = real(top_value, "explicit top traction or velocity")
        force = np.full(self.n+1, b*self.dx)
        force[[0, -1]] *= .5
        rhs = force[1:].copy() if self.mode == "traction" else force[1:-1].copy()
        rhs[-1] += value if self.mode == "traction" else self.k[-1]*value
        if not np.all(np.isfinite(rhs)):
            raise ValueError("load is not representable")
        u = np.zeros(self.n+1)
        if self.mode == "velocity":
            u[-1] = value
        if self.mode == "traction":
            u[1:] = solve_banded((1, 1), self.ab, rhs)
        else:
            u[1:-1] = solve_banded((1, 1), self.ab, rhs)
        du = np.diff(u)
        stress = self.k*du
        reactions = np.array([-stress[0]-force[0], stress[-1]-force[-1]])
        body_power = float(force @ u)
        boundary_power = float(reactions @ u[[0, -1]])
        heat = float(np.sum(self.k*du*du))
        balance = body_power + boundary_power - heat
        if not np.all(np.isfinite(u)) or not all(map(math.isfinite,
                (body_power, boundary_power, heat, balance))):
            raise ValueError("solution/work outside numeric support")
        return dict(velocity_m_s=u, stress_pa=stress, reactions_pa=reactions,
                    body_power_w_m2=body_power, boundary_power_w_m2=boundary_power,
                    dissipation_w_m2=heat, balance_w_m2=balance)


def bindings():
    names = ("tools/check_i01_initiation_verification.py",
             "tests/test_i01_initiation_verification.py",
             "cases/i01_initiation_verification_v1.json",
             "docs/I01_INITIATION_VERIFICATION.md",
             "tools/check_i01_elastic_memory.py")
    return {n: hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}


def controls():
    spec = json.loads(CASE.read_text(encoding="utf-8"))
    c, p = spec["channel"], spec["policy"]
    height, eta = c["height_m"], c["viscosity_pa_s"]
    b = c["density_contrast_kg_m3"]*c["gravity_m_s2"]*math.sin(c["dip_rad"])
    checks, errors, power_errors = {}, [], []
    t0 = perf_counter()
    for n in p["cells"]:
        plan = Channel(height, np.full(n, eta), top_mode="traction")
        result = plan.solve(b, top_value=0.)
        exact = b/(2*eta)*plan.x*(2*height-plan.x)
        norm = np.max(np.abs(exact))
        checks[f"constant_nodal_{n}"] = bool(np.max(np.abs(result["velocity_m_s"]-exact))/norm
            <= p["constant_nodal_relative_tolerance"])
        exact_power = b*b*height**3/(3*eta)
        power_errors.append(abs(result["dissipation_w_m2"]/exact_power-1))
        checks[f"balance_{n}"] = abs(result["balance_w_m2"]) <= p["relative_balance_tolerance"]*exact_power
        mid = (np.arange(n)+.5)/n
        variable = Channel(height, eta*(1+mid), top_mode="traction")
        actual = variable.solve(b, top_value=0.)
        reference = b*height/eta*(2*height*np.log1p(variable.x/height)-variable.x)
        errors.append(float(np.max(np.abs(actual["velocity_m_s"]-reference))/np.max(reference)))
    checks["variable_refinement"] = all(a/z >= p["minimum_refinement_ratio"] for a, z in zip(errors, errors[1:]))
    checks["variable_fine"] = errors[-1] <= p["fine_relative_velocity_tolerance"]
    checks["power_fine"] = power_errors[-1] <= p["fine_relative_power_tolerance"]
    checks["power_refinement"] = all(a/z >= p["minimum_refinement_ratio"] for a, z in zip(power_errors, power_errors[1:]))
    # Same body and material, distinct physical boundary laws; no velocity clamp on release.
    free = plan.solve(b, top_value=0.)
    held = Channel(height, np.full(n, eta), top_mode="velocity").solve(b, top_value=0.)
    still = plan.solve(0., top_value=0.)
    reverse = plan.solve(-b, top_value=0.)
    forced = plan.solve(0., top_value=b*height)
    checks["release_not_clamp"] = bool(free["velocity_m_s"][-1] > 0 and held["velocity_m_s"][-1] == 0
        and abs(held["reactions_pa"][-1]+b*height/2) <= 1e-10*b*height)
    checks["no_drive_no_motion"] = bool(np.all(still["velocity_m_s"] == 0.))
    checks["gravity_reversal"] = bool(np.allclose(reverse["velocity_m_s"], -free["velocity_m_s"], rtol=1e-12, atol=0.))
    checks["gravity_work_without_imposed_work"] = bool(free["body_power_w_m2"] > 0 and
        abs(free["boundary_power_w_m2"]) <= p["relative_balance_tolerance"]*free["dissipation_w_m2"])
    checks["external_traction_not_gravity"] = forced["boundary_power_w_m2"] > 0 and forced["body_power_w_m2"] == 0
    memory = State(.1, 0., 0., 10.)
    relaxation = Prepared(10., 20., .1).advance(memory, 0., kinematics=KINEMATICS)
    checks["stored_energy_is_not_gravity"] = (relaxation["heat_j_m3"] > 0 and
        relaxation["stored_change_j_m3"] < 0 and relaxation["work_j_m3"] == 0.)
    return dict(passed=all(checks.values()), checks=checks,
        variable_velocity_relative_errors=errors, power_relative_errors=power_errors,
        wall_velocity_m_s=float(free["velocity_m_s"][-1]),
        elapsed_seconds=perf_counter()-t0,
        scope="Analytical continuum and retained-memory controls only; no slab geometry, initiation or event admission")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as target:
        initial = bindings()
        report = dict(schema="atlas.i01-initiation-verification-result.v1",
            scientific_acceptance=False, generated_initiation_enabled=False,
            source_sha256=initial, python=platform.python_version(), numpy=np.__version__)
        try:
            report.update(controls())
            report["source_unchanged"] = initial == bindings()
            report["status"] = "PASS_BOUNDED_VERIFICATION_ONLY" if report["passed"] and report["source_unchanged"] else "FAIL"
        except Exception as exc:
            report.update(status="FAIL", error_type=type(exc).__name__)
        json.dump(report, target, indent=2, allow_nan=False)
        target.write("\n")
    print(json.dumps({k: report[k] for k in ("status", "scientific_acceptance")}))
    return 0 if report["status"] == "PASS_BOUNDED_VERIFICATION_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
