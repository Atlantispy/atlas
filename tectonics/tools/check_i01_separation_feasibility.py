"""Resolved 1D shear-band feasibility, not lithosphere separation acceptance.

SPDX-License-Identifier: AGPL-3.0-only
The physical and input contracts are in I01_SEPARATION_FEASIBILITY.md.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.linalg import cholesky_banded, cho_solve_banded

from check_i01_separation_law import (
    Loading, SofteningLaw, Refusal, INVALID, OUTSIDE,
    negative_example_thickness,
)

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases/i01_separation_feasibility_v1.json"
POLICY = {"refinement_relative": 0.03, "account_relative": 1e-6,
          "filter_relative": 0.01, "maximum_seconds": 60.0,
          "maximum_cells": 256, "maximum_steps": 20000}
FILES = ("tools/check_i01_separation_feasibility.py", "tests/test_i01_separation_feasibility.py",
         "docs/I01_SEPARATION_FEASIBILITY.md", "cases/i01_separation_feasibility_v1.json",
         "tools/check_i01_separation_law.py")


def real(value, name, *, positive=False, nonnegative=False):
    if type(value) not in (int, float):
        raise Refusal(INVALID, name + " must be a finite real")
    try:
        value = float(value)
    except OverflowError:
        raise Refusal(INVALID, name + " is not representable") from None
    if not math.isfinite(value) or (positive and value <= 0) or (nonnegative and value < 0):
        raise Refusal(INVALID, name + " is outside its numeric support")
    return value


@dataclass(frozen=True)
class BondHistory:
    """Material history separate from recoverable strength; no inferred initial certificate."""
    cohort: str
    ever_broken: bool
    support: str

    def __post_init__(self):
        if type(self.cohort) is not str or not self.cohort.strip():
            raise Refusal(INVALID, "cohort identity required")
        if type(self.ever_broken) is not bool or self.support not in ("INSIDE", "UNKNOWN", "VIOLATED"):
            raise Refusal(INVALID, "explicit bond and support histories required")

    def observe(self, law, filtered_history, temperature_k, effective_pressure_pa, *, increment_support):
        """Update a latch, never overwrite it with the current filtered strength history.

        increment_support certifies the whole new segment and every raw-history
        contributor to this filtered value, not just endpoint temperature/pressure.
        """
        history = real(filtered_history, "filtered history", nonnegative=True)
        temperature = real(temperature_k, "temperature", positive=True)
        pressure = real(effective_pressure_pa, "effective pressure", nonnegative=True)
        if increment_support not in ("INSIDE", "UNKNOWN", "VIOLATED"):
            raise Refusal(INVALID, "whole-segment support must be explicit")
        records = (self.support, increment_support)
        support = ("VIOLATED" if "VIOLATED" in records or not law.inside(temperature, pressure)
                   else "UNKNOWN" if "UNKNOWN" in records else "INSIDE")
        broke = (self.ever_broken or (support == "INSIDE"
                 and law.residual_state == "broken_surface_sliding"
                 and history >= law.softening_history))
        return replace(self, ever_broken=broke, support=support)

    @property
    def bond(self):
        # An unsupported later interval does not erase an already evidenced break.
        # Its mechanics/event eligibility is separately refused by support != INSIDE.
        return "BROKEN" if self.ever_broken else "BONDED" if self.support == "INSIDE" else "UNRESOLVED"


def preserve_bond_cohorts(records):
    """Transport contract: preserve distinct identities instead of averaging bond flags.

    This read-only identity operation is not an I05 conservative remapper.
    """
    records = tuple(records)
    if not records or any(not isinstance(record, BondHistory) for record in records):
        raise Refusal(INVALID, "explicit material bond records required")
    if len({record.cohort for record in records}) != len(records):
        raise Refusal(INVALID, "duplicate cohort identity; a spatial remapper must retain support")
    return records


class Band:
    """Finite-volume Neumann Helmholtz filter and force-balanced shear mechanics.

    Physical coefficients stay fixed under refinement. The band is transversely
    resolved and homogeneous along slip/strike; no normal opening or material flux.
    """
    def __init__(self, law, loading, *, cells, ell_m, contrast, length_provenance):
        if type(cells) is not int or not 4 <= cells <= POLICY["maximum_cells"]:
            raise Refusal(INVALID, "cells outside bounded control")
        self.ell = real(ell_m, "physical Helmholtz length", positive=True)
        contrast = real(contrast, "cohesion contrast", nonnegative=True)
        if contrast >= 1 or not isinstance(length_provenance, str) or not length_provenance.strip():
            raise Refusal(INVALID, "contrast below one and physical length provenance required")
        if not law.inside(loading.temperature_k, loading.effective_pressure_pa):
            raise Refusal(OUTSIDE, "fixed loading outside cohesion-loss support")
        self.law, self.loading, self.n = law, loading, cells
        self.h = law.band_width_m / cells
        # Four/eight cells per ell are the predeclared resolution requirement.
        if self.ell / self.h < 4:
            raise Refusal(INVALID, "fewer than four cells per physical Helmholtz length")
        self.x = (np.arange(cells) + 0.5) * self.h
        q = (self.ell / self.h) ** 2
        self.ab = np.zeros((3, cells))
        self.ab[0, 1:] = -q
        self.ab[2, :-1] = -q
        self.ab[1, :] = 1 + 2 * q
        self.ab[1, (0, -1)] = 1 + q
        # I + ell^2 L is positive definite, including the Neumann constant mode.
        # Geometry is fixed for this Band: factor once, never once per RK stage.
        factor = cholesky_banded(self.ab[:2], check_finite=True)
        self._filter_factor = np.frombuffer(factor.tobytes(), dtype=float).reshape(factor.shape)
        self.ab = np.frombuffer(self.ab.tobytes(), dtype=float).reshape(self.ab.shape)
        peak, residual = law.yields(loading.effective_pressure_pa)
        cohesion = law.peak_cohesion_pa * math.cos(law.peak_friction_rad)
        # Weak centre, strong edges; one smooth physical profile for every mesh.
        self.peak = peak + contrast * cohesion * np.cos(2 * np.pi * self.x / law.band_width_m)
        self.residual = residual
        if np.min(self.peak) <= residual:
            raise Refusal(INVALID, "cohesion profile is not softening throughout")
        self.initial_traction = None

    def filtered(self, raw):
        raw = np.asarray(raw, dtype=float)
        if raw.shape != (self.n,) or not np.all(np.isfinite(raw)):
            raise Refusal(INVALID, "one finite raw history per cell required")
        result = cho_solve_banded((self._filter_factor, False), raw, check_finite=False)
        if not np.all(np.isfinite(result)):
            raise Refusal(INVALID, "unrepresentable filtered history")
        return result

    def rates(self, state):
        traction, raw = state[0], state[1:1+self.n]
        kbar = self.filtered(raw)
        yield_pa = self.peak - (self.peak-self.residual) * np.minimum(kbar/self.law.softening_history, 1)
        plastic = np.maximum(traction-yield_pa, 0) / self.law.plastic_viscosity_pa_s
        creep = 0 if self.loading.creep_viscosity_pa_s is None else traction/self.loading.creep_viscosity_pa_s
        band_rate = self.h * float(np.sum(plastic)) + self.law.band_width_m * creep
        derivative = np.zeros_like(state)
        derivative[0] = self.loading.stiffness_pa_m * (self.loading.loading_rate_m_s-band_rate)
        derivative[1:1+self.n] = plastic
        # Accounts are independently integrated, never filled as balance residuals.
        derivative[-5:] = (traction*self.loading.loading_rate_m_s,
                            self.law.band_width_m*traction*creep,
                            self.h*float(np.sum((yield_pa-self.residual)*plastic)),
                            self.h*self.residual*float(np.sum(plastic)),
                            self.h*self.law.plastic_viscosity_pa_s*float(np.dot(plastic, plastic)))
        return derivative

    def rk4(self, state, dt):
        a = self.rates(state)
        b = self.rates(state+dt*a/2)
        c = self.rates(state+dt*b/2)
        d = self.rates(state+dt*c)
        out = state + dt*(a+2*b+2*c+d)/6
        if not np.all(np.isfinite(out)) or np.min(out[:1+self.n]) < 0:
            raise Refusal(INVALID, "time step produced unsupported traction/history")
        return out

    def run(self, *, dt_s, horizon_s, traction_pa, support, deadline=None):
        dt = real(dt_s, "time step", positive=True)
        horizon = real(horizon_s, "horizon", positive=True)
        traction = real(traction_pa, "initial traction", nonnegative=True)
        if support != "INSIDE":
            raise Refusal(OUTSIDE, "resolved feasibility requires certified whole-approach support")
        steps = math.ceil(horizon/dt)
        if steps > POLICY["maximum_steps"]:
            raise Refusal(INVALID, "bounded control step budget exceeded")
        dt = horizon/steps
        # A sufficient explicit stability bound on elastic/plastic and softening rates.
        bound = (self.loading.stiffness_pa_m*self.law.band_width_m
                 + float(np.max(self.peak))-self.residual)/self.law.plastic_viscosity_pa_s
        if self.loading.creep_viscosity_pa_s is not None:
            bound += self.loading.stiffness_pa_m*self.law.band_width_m/self.loading.creep_viscosity_pa_s
        if dt*bound > 0.1:
            raise Refusal(INVALID, "time step exceeds predeclared explicit stability bound")
        state = np.zeros(1+self.n+5)
        state[0] = traction
        broken = np.zeros(self.n, dtype=bool)
        bracket = None
        width = None
        for step in range(steps):
            if deadline is not None and step % 128 == 0 and time.monotonic() > deadline:
                raise Refusal("REFUSED_TIME_BUDGET", "bounded campaign deadline reached")
            state = self.rk4(state, dt)
            kbar = self.filtered(state[1:1+self.n])
            if self.law.residual_state == "broken_surface_sliding":
                broken |= kbar >= self.law.softening_history
            if bracket is None and np.any(broken):
                bracket = [step*dt, (step+1)*dt]
                activity = self.rates(state)[1:1+self.n] * state[0]
                norm = self.h*float(np.dot(activity, activity))
                width = (self.h*float(np.sum(activity)))**2/norm if norm else None
        work, creep, breakdown, friction, overstress = map(float, state[-5:])
        elastic = (state[0]**2-traction**2)/(2*self.loading.stiffness_pa_m)
        scale = max(abs(work), abs(elastic)+creep+breakdown+friction+overstress)
        error = abs(work-elastic-creep-breakdown-friction-overstress)/scale if scale else 0.0
        # Exact geometry of this 1D strip: anchors touch opposite faces. A full
        # transversely broken cell spans the prescribed homogeneous slip/strike
        # dimensions. This cannot infer exterior paths in an actual lithosphere.
        return {"cells": self.n, "dt_s": dt, "ell_m": self.ell,
                "band_width_m": self.law.band_width_m,
                "bond_loss_bracket_s": bracket, "shear_displacement_bracket_m": None if bracket is None else
                [t*self.loading.loading_rate_m_s for t in bracket],
                "bonded_connectivity": "DISCONNECTED" if np.any(broken) else "CONNECTED",
                "point_set_connectivity": "CONNECTED", "broken_cells": int(np.sum(broken)),
                "plastic_participation_width_m_at_loss": width,
                "traction_pa": float(state[0]), "raw_history_range": [float(np.min(state[1:1+self.n])),
                float(np.max(state[1:1+self.n]))],
                "work_j_m2": work, "elastic_change_j_m2": float(elastic),
                "creep_dissipation_j_m2": creep, "breakdown_dissipation_j_m2": breakdown,
                "residual_friction_j_m2": friction, "overstress_dissipation_j_m2": overstress,
                "account_relative_error": error, "support": "INSIDE",
                "event_authorised": False, "scientific_acceptance": False}


def relative(a, b):
    if a == b:
        return 0.0
    return abs(a-b)/max(abs(a), abs(b))


def compare(a, b):
    x, y = a["bond_loss_bracket_s"], b["bond_loss_bracket_s"]
    if x is None or y is None:
        return {"pass": False, "reason": "missing bracket"}
    overlap = max(x[0], y[0]) <= min(x[1], y[1])
    midpoint = relative(sum(x)/2, sum(y)/2)
    shear = relative(sum(a["shear_displacement_bracket_m"])/2, sum(b["shear_displacement_bracket_m"])/2)
    energy = relative(a["breakdown_dissipation_j_m2"], b["breakdown_dissipation_j_m2"])
    passed = overlap and max(midpoint, shear, energy) <= POLICY["refinement_relative"]
    return {"pass": passed, "brackets_overlap": overlap, "time_relative": midpoint,
            "shear_displacement_relative": shear, "breakdown_relative": energy}


def load_case():
    spec = json.loads(CASE.read_text(encoding="utf-8"))
    if spec["schema"] != "atlas.i01-separation-feasibility-case.v1" or spec["policy"] != POLICY:
        raise Refusal(INVALID, "predeclared case/policy changed")
    return spec


def campaign(spec):
    start = time.monotonic()
    deadline = start+POLICY["maximum_seconds"]
    law, loading, control = SofteningLaw(**spec["law"]), Loading(**spec["loading"]), spec["resolved"]

    def run(*, cells=64, dt=None, ell=None, current_law=law, current_loading=loading, contrast=None):
        band = Band(current_law, current_loading, cells=cells,
                    ell_m=control["helmholtz_length_m"] if ell is None else ell,
                    contrast=control["cohesion_contrast"] if contrast is None else contrast,
                    length_provenance=control["length_provenance"])
        return band.run(dt_s=control["dt_s"] if dt is None else dt,
                        horizon_s=control["horizon_s"], traction_pa=control["initial_traction_pa"],
                        support=control["initial_history_support"], deadline=deadline)

    coarse, fine = [run(cells=n) for n in control["cells"]]
    half = run(dt=control["dt_s"]/2)
    refinement = {"space": compare(coarse, fine), "time": compare(fine, half)}
    sensitivities = {}
    changes = spec["physical_sensitivities"]
    for factor in changes["helmholtz_length_factors"]:
        sensitivities["ell_"+str(factor)] = run(ell=control["helmholtz_length_m"]*factor)
    for field, factors in (("band_width_m", changes["band_width_factors"]),
                           ("softening_history", changes["softening_history_factors"]),
                           ("plastic_viscosity_pa_s", changes["plastic_viscosity_factors"])):
        for factor in factors:
            sensitivities[field+"_"+str(factor)] = run(current_law=replace(law, **{field: getattr(law, field)*factor}))
    # Timing of unstable softening is explicitly viscosity dependent, not tuned.
    unstable = replace(loading, stiffness_pa_m=changes["unstable_stiffness_pa_m"])
    for factor in (0.5, 1.0, 2.0):
        sensitivities["unstable_eta_"+str(factor)] = run(current_loading=unstable,
            current_law=replace(law, plastic_viscosity_pa_s=law.plastic_viscosity_pa_s*factor))
    creep_spec = spec["creep_control"]
    creep = run(current_loading=replace(loading, creep_viscosity_pa_s=creep_spec["viscosity_pa_s"]),
                dt=control["dt_s"]*creep_spec["dt_factor"])
    intact = run(current_law=replace(law, residual_state="weakened_intact"))
    negative = [{"opening": u, "thickness": negative_example_thickness(u, h_c=64, a=1, c=1, w=1),
                 "bond": BondHistory("positive-film", False, "INSIDE").observe(law, 0, 300, 10,
                     increment_support="INSIDE").bond} for u in (0, 32, 48, 56, 60, 62, 63, 64)]
    all_runs = [coarse, fine, half, creep, intact, *sensitivities.values()]
    checks = {"spatial_refinement": refinement["space"]["pass"],
              "temporal_refinement": refinement["time"]["pass"],
              "all_accounts": all(r["account_relative_error"] <= POLICY["account_relative"] for r in all_runs),
              "creep_keeps_bonds": creep["bonded_connectivity"] == "CONNECTED" and creep["raw_history_range"] == [0., 0.],
              "intact_residual_keeps_bonds": intact["bonded_connectivity"] == "CONNECTED",
              "negative_example_keeps_bonds": all(x["thickness"] > 0 and x["bond"] == "BONDED" for x in negative)}
    return {"schema": "atlas.i01-separation-feasibility.v2", "status": "WORKING_NON_CANON",
            "result": "PASS_BOUNDED_RESOLVED_FEASIBILITY_ONLY" if all(checks.values()) else "FAIL",
            "checks": checks, "scientific_acceptance": False, "event_authorised": False,
            "refinement": refinement, "runs": [coarse, fine, half], "physical_sensitivities": sensitivities,
            "creep_control": creep, "intact_control": intact, "negative_example": negative,
            "elapsed_seconds_after_imports": time.monotonic()-start}


def bindings():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="new file only; stdout if omitted")
    args = parser.parse_args(argv)
    # Reserve the destination before computation; exclusive creation also closes
    # the check/create race. A refused campaign leaves its actual failure visible.
    destination = nullcontext(None) if args.output is None else args.output.open("x", encoding="utf-8", newline="\n")
    with destination as stream:
        started = time.monotonic()
        before = None
        try:
            before = bindings()
            result = campaign(load_case())
            if bindings() != before:
                raise Refusal("REFUSED_SOURCE_CHANGED", "source changed during control")
            result["source_sha256"] = before
            result["runtime"] = {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__}
            payload = json.dumps(result, indent=2, allow_nan=False)+"\n"
        except Exception as error:
            if stream is not None:
                failure = {"schema": "atlas.i01-separation-feasibility.v2", "result": "FAILED_CAMPAIGN",
                           "scientific_acceptance": False, "event_authorised": False,
                           "error_type": type(error).__name__, "error": str(error),
                           "elapsed_seconds_after_imports": time.monotonic()-started,
                           "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                                       "scipy": scipy.__version__}}
                if before is not None:
                    failure["source_sha256"] = before
                json.dump(failure, stream, indent=2)
                stream.write("\n")
            raise
        if stream is None:
            print(payload, end="")
        else:
            stream.write(payload)
            print(json.dumps({"result": result["result"], "checks": result["checks"]}))
    return 0 if result["result"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
