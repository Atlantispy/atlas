"""I01 conservative motion admission on the evolving finite-strain column, WORKING NON-CANON; not physical rupture.

The retained exact linear-envelope gate (check_i01_column_admission, check_i01_decoupling) is connected to the
retained material-following finite-strain strip (check_i01_finite_strain). An envelope is prepared once from an
issued state at stretch L, raw-history floor kappa_f and elapsed time t_f, all measured from the absolute reference
preparation at lam = 1. Under a positive constant extension force every later state has lam >= L, kappa >= kappa_f
and 0 < v <= F/D, so its column resistance is at most Ybar + Abar v at any temperature inside the admitted window:

    Ybar = 2 g sum((q0/L) (Cmax + (P0/L) min(1, phimax))),   Abar = 4 g sum(q0 eta)/(w0 L^2),   g = 1 + 2^-50.

Provenance: only reference_state() and evolved() issue a State, evolved() by running the retained evolve itself for
one Evolution, and only prepare() issues an envelope. The issue mark is no constructor argument and replace() never
copies it, so a built, edited or imported state or envelope is refused, and admit() takes a state only from the
envelope's own evolution. A raw evolution output is never evolution evidence; introspection is not defended.
A certificate covers a declared future window of that model inside its frozen stretch, temperature and time scope;
failure means NOT certified by this bound. No solver switch, separation, rupture, necking or world assembly.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from concurrent.futures import CancelledError
import copy
import dataclasses
from dataclasses import dataclass
from fractions import Fraction
import json
import math
from pathlib import Path
import platform
import statistics
import threading
import time

import numpy as np
import scipy
import threadpoolctl
from threadpoolctl import threadpool_limits

import check_i01_column_admission as ca
import check_i01_finite_strain as fs

d, tm, heat, motion, w = ca.d, fs.tm, fs.heat, fs.motion, fs.weakening
if ca.m is not motion or ca.w is not w:
    raise ImportError("column-admission and finite-strain adapters must share the reviewed modules")

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT/"cases/i01_finite_admission_v1.json"
SCHEMA = "atlas.i01-finite-admission-case.v1"
PASS = "PASS_BOUNDED_FINITE_ADMISSION_ONLY"
CERTIFIED, NOT_CERTIFIED = "CERTIFIED_FINITE_WINDOW", "NOT_CERTIFIED_BY_BOUND"
# column_at and stage form fl(q0/lam), fl(P0/lam), fl(w0 lam), fl(|F|/D) and the axial rate from them, each by one
# exactly rounded binary64 operation. The rounded weight, pressure and rate therefore exceed their exact affine values
# by at most (1+u)^3/(1-u)^2 < 1 + 6u, u = 2^-53; the envelope carries g = 1 + 8u instead of treating them as exact.
DERIVED_ROUNDING = Fraction(2**50+1, 2**50)
HORIZON_CEILING_S = 1e14                   # frozen: the accepted finite-strain duration from the reference geometry
SCOPE = ("represented Gauss-point finite-strain strip measured from its absolute reference; states issued by this "
         "tool's own run of one retained evolution; positive constant extension force; stretch and raw history at or "
         "above the prepared floors; any temperature inside the admitted window; zero pore pressure; holds while the "
         "retained model continues inside its temperature window and constitutive support; not the continuous depth "
         "model, the coupled thermal trajectory or physical separation")
NEW_FILES = ("tools/check_i01_finite_admission.py", "cases/i01_finite_admission_v1.json",
             "docs/I01_FINITE_ADMISSION.md", "tests/test_i01_finite_admission.py")
RETAINED = ("tools/check_i01_finite_strain.py", "tools/check_i01_column_admission.py", "tools/check_i01_decoupling.py",
            "tools/check_i01_thermomechanical_motion.py", "tools/check_i01_column_heat.py",
            "tools/check_i01_motion_coupling.py", "tools/check_i01_weakening.py", "tools/check_i01_column.py",
            "cases/i01_finite_strain_v1.json", "cases/i01_column_admission_v1.json",
            "cases/i01_thermomechanical_motion_v1.json", "cases/i01_column_heat_v1.json",
            "cases/i01_motion_coupling_v1.json", "cases/i01_weakening_v1.json")
ACCEPTED_RECEIPTS = {
    "evidence/i01-finite-strain-r2.json": "e356000b7d467bc3d43bb4dd0637cdc89d06c32f0bac5e335697d5a8d7e97b34",
    "evidence/i01-column-admission-r1.json": "abe11697a0ea3b3feb4089dc77231bda90780e2ff504ee0de4a45687d77d0520"}
IMPORTED = {"tools/check_i01_finite_strain.py": fs, "tools/check_i01_column_admission.py": ca,
            "tools/check_i01_decoupling.py": d, "tools/check_i01_thermomechanical_motion.py": tm,
            "tools/check_i01_column_heat.py": heat, "tools/check_i01_motion_coupling.py": motion,
            "tools/check_i01_weakening.py": w, "tools/check_i01_column.py": w.column}
INPUTS = {"finite_strain_case": "cases/i01_finite_strain_v1.json",
          "column_admission_case": "cases/i01_column_admission_v1.json"}
CONTRACT_KEYS = {"stretch_window", "temperature_window_k", "horizon_s", "pore_pressure_pa"}
CAMPAIGN_KEYS = {"layered_order", "homogeneous_order", "steps_per_horizon", "committed_steps", "relative_tolerances",
                 "displacement_limit_m", "analytic"}
ANALYTIC_KEYS = {"order", "stretch", "duration_s", "weakened_history"}
POLICY_KEYS = {"maximum_seconds", "numerical_allowance_relative", "oracle_relative", "repetitions", "batches"}
VIEW = ("status", "relative_error_limit", "speed_error_bound_m_s", "displacement_error_bound_m",
        "driving_work_error_bound_J_m", "speed_lower_bound_m_s", "yield_bound_n_m", "linear_bound_pa_s",
        "window_start_s", "window_end_s", "stretch_start", "stretch_floor", "stretch_reach_upper",
        "generated_separation_authorised")


# ----------------------------------------------------------------------------- issued states

@dataclass(frozen=True, eq=False)
class Evolution:
    """One authorised retained evolution from the absolute reference at one fixed time step; it runs nothing itself.

    The reference preparation and its paired support are held by identity; law, drive, inputs key, initial history
    and temperature and the retained settings by value, copied so that later caller edits cannot reach them. Every
    construction, dataclasses.replace() included, is validated, so any instance is a valid evolution. States are
    issued from it only by reference_state() and evolved(), and each carries this object as its provenance.
    """
    base: w.PreparedColumn
    thermal: heat.ThermalColumn
    law: w.WeakeningLaw
    drive: motion.Drive
    key: tuple                        # inputs reproducing the reference preparation
    kappa0: np.ndarray                # initial raw history, read-only
    step_s: float                     # the fixed time step of every state issued by evolved()
    window: dict                      # the retained stretch/temperature refusal window
    temperature_step_k: float
    fractions: tuple
    policy: dict
    modes: object = dataclasses.field(default=None, init=False, repr=False)  # owned eigensystem; built once
    theta0: np.ndarray = None         # initial temperature departure, read-only; zero when omitted

    def __post_init__(self):
        if type(self.law) is not w.WeakeningLaw or type(self.drive) is not motion.Drive:
            raise ValueError("typed weakening law and external drive required")
        if type(self.key) is not tuple or len(self.key) != 4:
            raise ValueError("the inputs key of the reference preparation is required")
        key = copy.deepcopy(self.key)
        try:       # the retained pairing: typed objects, fresh key, paired support, zero pore pressure, eigensystem
            modes = fs.paired(self.base, self.thermal, modes=None, conduction=True, rebuild=None, inputs=key)
        except TypeError as exc:
            raise ValueError("inputs do not reproduce the reference preparation") from exc
        _, _, tlo, thi = fs.window_of(self.window)
        heat.policy_limits(self.policy)
        theta = np.zeros(self.base.size) if self.theta0 is None else tm.departure(self.theta0, self.base.size)
        temperature = np.asarray(self.thermal.steady_k)+theta
        if not np.all((temperature >= tlo) & (temperature <= thi)):
            raise ValueError("initial material temperatures lie outside the evolution window")
        for name, value in (("key", key), ("kappa0", w.frozen(w.history_array(self.base, self.kappa0))),
                            ("step_s", w.positive(self.step_s, "time step")), ("window", copy.deepcopy(self.window)),
                            ("temperature_step_k", w.positive(self.temperature_step_k, "temperature step guard")),
                            ("fractions", heat.heat_fractions(self.fractions)), ("policy", copy.deepcopy(self.policy)),
                            ("modes", modes), ("theta0", w.frozen(theta))):
            object.__setattr__(self, name, value)


@dataclass(frozen=True, eq=False)
class State:
    """One committed finite-strain state measured from its absolute reference; arrays are read-only copies.

    ``stretch`` and ``elapsed_s`` are cumulative from lam = 1 at zero time and ``reference`` is the fingerprint of the
    reference preparation. ``evolution`` is set only when this module issues the state. It is no constructor argument
    and dataclasses.replace() never copies it, so a built, edited or imported state carries None and prepare() and
    admit() refuse it, whatever its values. Nothing is re-based at a later state.
    """
    stretch: float
    elapsed_s: float
    width_m: float
    thickness_m: float
    kappa: np.ndarray
    theta: np.ndarray
    reference: str
    evolution: object = dataclasses.field(default=None, init=False, repr=False)    # the issuing Evolution

    def __post_init__(self):
        for name in ("stretch", "elapsed_s", "width_m", "thickness_m"):
            object.__setattr__(self, name, w.number(getattr(self, name), name))
        for name in ("kappa", "theta"):
            values = np.asarray(getattr(self, name))
            if values.dtype.kind not in "fiu" or values.ndim != 1:
                raise ValueError(name+" must hold one real value per material point")
            object.__setattr__(self, name, w.frozen(values))
        if type(self.reference) is not str:
            raise ValueError("reference fingerprint required")


def reference_state(evolution):
    """The evolution's reference, issued: lam = 1 at zero elapsed time with its initial history and temperature."""
    if type(evolution) is not Evolution:
        raise ValueError("an authorised evolution is required")
    e = evolution
    state = State(1., 0., e.drive.width_m*1., e.base.thickness_m/1., e.kappa0, e.theta0, e.base.fingerprint)
    object.__setattr__(state, "evolution", e)        # the issue mark; no constructor or replace() sets it
    return state


def evolved(evolution, steps, *, deadline=None):
    """Run the retained evolve of ``evolution`` from its reference for ``steps`` fixed steps; issue the endpoint.

    Returns (raw output, issued State). Only a COMPLETE run of exactly ``steps`` steps at the evolution's own step
    issues a state, whose values are that run's committed endpoint copied read-only. The raw output serves the
    numerical diagnostics only: neither it nor any other dictionary can become an issued state.
    """
    if type(evolution) is not Evolution:
        raise ValueError("an authorised evolution is required")
    if type(steps) is not int or steps < 1:
        raise ValueError("a positive whole number of evolution steps is required")
    e = evolution
    out = fs.evolve(e.base, e.thermal, e.law, e.kappa0, e.drive, duration_s=e.step_s*steps, steps=steps,
                    window=e.window, temperature_step_k=e.temperature_step_k, fractions=e.fractions, policy=e.policy,
                    modes=e.modes, theta0=e.theta0, inputs=e.key, deadline=deadline)
    if out["status"] != "COMPLETE" or out["accepted_steps"] != steps or out["time_step_s"] != e.step_s:
        raise ValueError("a complete retained finite-strain evolution of whole steps is required; no state issued")
    state = State(out["stretch"], out["elapsed_s"], out["width_m"], out["thickness_m"], out["kappa"], out["theta"],
                  e.base.fingerprint)
    object.__setattr__(state, "evolution", e)
    return out, state


def issued(state, base, thermal, law, drive):
    """The evolution that issued ``state`` from exactly these objects; built, edited or imported states are refused."""
    if type(state) is not State:
        raise ValueError("a committed finite-strain state is required; a raw or imported output is not evolution "
                         "evidence")
    e = state.evolution
    if type(e) is not Evolution:
        raise ValueError("state was not issued by an authorised evolution: built, edited and imported states are "
                         "refused whatever their values")
    if e.base is not base or e.thermal is not thermal or e.law != law or e.drive != drive:
        raise ValueError("state was evolved with a different preparation, support, law or drive")
    return e


# ----------------------------------------------------------------------------- envelope and admission

@dataclass(frozen=True, eq=False)
class FiniteEnvelope:
    """Exact linear resistance envelope over every later state of one evolution; immutable, reusable.

    Issued only by prepare(), which records the preparing state's ``evolution``; a built or dataclasses.replace()-d
    envelope carries None and admit() refuses it, so horizon, window, floors and coefficients cannot be edited.
    """
    base: w.PreparedColumn            # absolute reference preparation at lam = 1
    thermal: heat.ThermalColumn       # its paired support; its fixed steady reference turns departures into T
    law: w.WeakeningLaw
    drive: motion.Drive               # drive.width_m is the reference width w0
    window: tuple                     # (stretch low, stretch high, temperature low, temperature high)
    horizon_s: float                  # cumulative elapsed ceiling from the reference
    stretch_floor: float              # L: the preparing state's stretch
    elapsed_floor_s: float            # the preparing state's elapsed time
    history_floor: np.ndarray         # the preparing state's raw history, read-only
    balance: d.Balance                # F, D, Ybar, Abar and exponent 1: the retained exact gate's input
    evolution: object = dataclasses.field(default=None, init=False, repr=False)    # the preparing state's Evolution


def paired(base, thermal, law, drive):
    """Typed objects of one reference evolution under the retained finite-strain and bound assumptions."""
    if (type(base) is not w.PreparedColumn or type(thermal) is not heat.ThermalColumn
            or type(law) is not w.WeakeningLaw or type(drive) is not motion.Drive):
        raise ValueError("reviewed preparation, thermal support, weakening law and drive required")
    if thermal.mechanical_fingerprint != base.fingerprint or not heat.same_support(thermal, base):
        raise ValueError("thermal support was prepared for a different mechanical column")
    if drive.force_n_m <= 0 or base.closure not in (w.LITHOSTATIC, w.SUPPLIED):
        raise ValueError("positive extension and supported pressure closure required")
    if np.any(np.asarray(base.pore_pa) != 0):
        raise ValueError("supplied pore pressure is not transported under finite strain")
    if not np.all(base.plastic) or not np.all(np.isfinite(base.eta) & (base.eta > 0)):
        raise ValueError("every point needs finite positive plastic regularisation")
    law.certify(base)


def located(base, thermal, drive, state, window, horizon, *, floors=None):
    """Exact position of a committed state inside the admitted scope; anything else is refused, never repaired.

    ``floors`` are an envelope's (stretch, elapsed time, raw history); without them the state need only lie at or
    beyond the reference. Returns the exact stretch and elapsed time with v0 = F/D and w0.
    """
    if type(state) is not State:
        raise ValueError("a committed finite-strain state is required")
    lo, hi, tlo, thi = window
    stretch_floor, elapsed_floor, history_floor = (1., 0., None) if floors is None else floors
    lam, t = state.stretch, state.elapsed_s
    if state.reference != base.fingerprint:
        raise ValueError("state belongs to another reference preparation")
    if state.width_m != drive.width_m*lam or state.thickness_m != base.thickness_m/lam:   # the retained expressions
        raise ValueError("state geometry is not measured from this reference preparation and width")
    kappa = w.history_array(base, state.kappa)
    temperature = np.asarray(thermal.steady_k)+tm.departure(state.theta, base.size)
    if not np.all((temperature >= tlo) & (temperature <= thi)):
        raise ValueError("state temperature lies outside the admitted window")
    if history_floor is not None and np.any(kappa < history_floor):
        raise ValueError("raw history has fallen below the prepared floor")
    if not stretch_floor <= lam <= hi:
        raise ValueError("stretch lies outside the prepared supported range")
    if not elapsed_floor <= t <= horizon:
        raise ValueError("elapsed time lies before the preparation or beyond the cumulative horizon")
    exact_lam, exact_t = ca.fraction(lam), ca.fraction(t)
    w0, v0 = ca.fraction(drive.width_m), ca.fraction(drive.force_n_m)/ca.fraction(drive.drag_pa_s)
    # Consistency with 0 < v <= F/D since the reference. Resisted motion leaves slack here, so this inequality
    # cannot detect an edited clock; the issued-state provenance checked before it does.
    if exact_lam > 1+v0*exact_t/w0:
        raise ValueError("stretch is not reachable from the reference in the stated elapsed time")
    return exact_lam, exact_t, v0, w0


def envelope_balance(base, law, drive, stretch, history, *, cancel=None, deadline=None):
    """Ybar and Abar at stretch floor L = ``stretch`` and raw-history floor ``history``, exactly, as the retained
    exponent-1 Balance. The formula only: prepare() adds every premise, scope and provenance check, and admit()
    certifies nothing from a Balance alone."""
    lam, w0 = ca.fraction(w.positive(stretch, "stretch floor")), ca.fraction(drive.width_m)
    floor = w.history_array(base, history)
    cohesive = frictional = viscous = Fraction(0)
    for j in range(base.size):
        ca.check_stop(cancel, deadline)
        q0, kappa = ca.fraction(base.weight[j]), ca.fraction(floor[j])
        if q0 <= 0:
            raise ValueError("positive quadrature weights required")
        # No healing: history only rises above its floor, where C and phi are largest. cos(phi) <= 1 and
        # sin(phi) <= min(1, phi); extension only lowers the lithostatic effective pressure below P0/lam.
        cohesive += q0*ca.fraction(base.cohesion_pa[j])*ca.factor_at(kappa, law, "cohesion_factor")
        phi = ca.fraction(base.friction_rad[j])*ca.factor_at(kappa, law, "friction_factor")
        frictional += q0*ca.fraction(base.reference_pa[j])*min(Fraction(1), phi)
        viscous += q0*ca.fraction(base.eta[j])
    g = DERIVED_ROUNDING
    return d.Balance(drive.force_n_m, drive.drag_pa_s, 2*g*(cohesive+frictional/lam)/lam,
                     4*g*viscous/(w0*lam*lam), 1)


def prepare(base, thermal, law, drive, key, state, *, window, horizon_s, cancel=None, deadline=None):
    """Envelope of the represented finite-strain column over every later state of the state's own evolution.

    ``state`` must be issued by an evolution of exactly these objects; it fixes the floors: its stretch L, raw
    history kappa_f and elapsed time. ``key`` must reproduce the reference preparation, so a stretched or
    re-referenced column cannot pose as lam = 1. Every coefficient is an exact rational of represented inputs; creep
    never enters, so neither does temperature.
    """
    ca.check_stop(cancel, deadline)
    paired(base, thermal, law, drive)
    try:
        fresh = type(key) is tuple and len(key) == 4 and w.fingerprint(*key) == base.fingerprint
    except (TypeError, ValueError):
        fresh = False
    if not fresh:
        raise ValueError("inputs do not reproduce the reference preparation (stretched or stale column)")
    scope = fs.window_of(window)
    horizon = w.positive(horizon_s, "horizon")
    if horizon > HORIZON_CEILING_S:
        raise ValueError("horizon beyond the accepted finite-strain duration")
    evolution = issued(state, base, thermal, law, drive)
    located(base, thermal, drive, state, scope, horizon)
    floor = w.history_array(base, state.kappa)
    balance = envelope_balance(base, law, drive, state.stretch, floor, cancel=cancel, deadline=deadline)
    ca.check_stop(cancel, deadline)
    envelope = FiniteEnvelope(base, thermal, law, drive, scope, horizon, state.stretch, state.elapsed_s,
                              w.frozen(floor), balance)
    object.__setattr__(envelope, "evolution", evolution)     # the issue mark; no constructor or replace() sets it
    return envelope


def lower_float(value):
    """Inward display of a lower bound: the largest binary64 value not above ``value``."""
    return -d.upper_float(-value)+0.


def admit(envelope, base, thermal, law, drive, state, *, duration_s, relative_tolerance, displacement_limit_m,
          cancel=None, deadline=None):
    """Sufficient certificate for the future window [t, t + duration] from an issued state of the envelope's evolution.

    The state carries the absolute stretch and cumulative time its own evolution produced, so a later call can
    neither reset the reference nor regain a used horizon. Failure of the bound is NOT evidence that the actual motion
    error is large.
    """
    ca.check_stop(cancel, deadline)
    if type(envelope) is not FiniteEnvelope or type(envelope.evolution) is not Evolution:
        raise ValueError("an envelope issued by prepare() is required; a built or edited envelope is refused")
    if base is not envelope.base or thermal is not envelope.thermal or law != envelope.law or drive != envelope.drive:
        raise ValueError("changed preparation, support, law or drive requires a new envelope")
    if issued(state, base, thermal, law, drive) is not envelope.evolution:
        raise ValueError("state was issued by a different evolution than the envelope's")
    floors = (envelope.stretch_floor, envelope.elapsed_floor_s, envelope.history_floor)
    lam, t, v0, w0 = located(base, thermal, drive, state, envelope.window, envelope.horizon_s, floors=floors)
    duration = d.rational(duration_s, "duration", positive=True)
    if t+duration > ca.fraction(envelope.horizon_s):
        raise ValueError("window extends beyond the cumulative horizon")
    reach = lam+v0*duration/w0                      # drag-only reach: 0 < v <= F/D for every column state
    if reach > ca.fraction(envelope.window[1]):
        raise ValueError("drag-only reach leaves the admitted stretch window")
    result = d.window_admission(envelope.balance, envelope.balance, duration_s=duration,
                                relative_tolerance=relative_tolerance, displacement_limit_m=displacement_limit_m)
    result.pop("snapshot_passed")                   # the envelope is an upper bound, not the actual snapshot
    b = envelope.balance
    lower = max(Fraction(0), (b.force-b.yield_force)/(b.drag+b.coefficient))
    result.update(status=CERTIFIED if result["numerical_admissible"] else NOT_CERTIFIED, window_start_s=float(t),
                  window_end_s=d.upper_float(t+duration), horizon_s=envelope.horizon_s, stretch_start=float(lam),
                  stretch_floor=envelope.stretch_floor, stretch_reach_upper=d.upper_float(reach),
                  speed_lower_bound_m_s=lower_float(lower), **ca.bounds(envelope), scope=SCOPE)
    ca.check_stop(cancel, deadline)
    return result


# ----------------------------------------------------------------------------- case

def declared(spec):
    c = spec["contract"]
    return dict(stretch=c["stretch_window"], temperature_k=c["temperature_window_k"])


def scope_of(spec):
    return dict(window=declared(spec), horizon_s=spec["contract"]["horizon_s"])


def step_s(spec):
    return spec["contract"]["horizon_s"]/spec["campaign"]["steps_per_horizon"]


def settings(spec, ctx):
    """The accepted finite-strain evolution settings at the campaign's fixed step: Evolution keyword arguments."""
    fspec = ctx["fs"]
    return dict(step_s=step_s(spec), window=fs.declared_window(fspec),
                temperature_step_k=fspec["representation"]["max_temperature_step_k"],
                fractions=ctx["fs_ctx"]["heat"]["heat_fractions"], policy=fspec["policy"])


def validate_case(spec):
    """Strict schema; physics, forcing and scope come only from the accepted finite-strain case."""
    fields = {"schema", "status", "scope", "provenance", "inputs", "contract", "campaign", "policy"}
    if type(spec) is not dict or set(spec) != fields or spec["schema"] != SCHEMA:
        raise ValueError("finite-admission case schema or top-level fields mismatch")
    if spec["inputs"] != INPUTS:
        raise ValueError("only the accepted finite-strain and column-admission cases are admitted")
    if (fs.CASE.resolve() != (ROOT/INPUTS["finite_strain_case"]).resolve()
            or ca.CASE.resolve() != (ROOT/INPUTS["column_admission_case"]).resolve()):
        raise ValueError("a retained adapter reads a different case")
    fs_spec, fs_ctx = fs.load_case()
    retained = json.loads(ca.CASE.read_text(encoding="utf-8"))
    if retained["schema"] != "atlas.i01-column-admission-case.v1" or retained["policy"] != ca.POLICY:
        raise ValueError("the retained column-admission case differs from its executable")
    c, rep = spec["contract"], fs_spec["representation"]
    if type(c) is not dict or set(c) != CONTRACT_KEYS:
        raise ValueError("contract fields mismatch")
    if (c["stretch_window"] != rep["stretch_window"] or c["temperature_window_k"] != rep["temperature_window_k"]
            or c["horizon_s"] != fs_spec["drive"]["duration_s"] or c["pore_pressure_pa"] != 0):
        raise ValueError("contract differs from the accepted finite-strain scope")
    fs.window_of(declared(spec))
    if w.positive(c["horizon_s"], "horizon") > HORIZON_CEILING_S:
        raise ValueError("horizon beyond the accepted finite-strain duration")
    camp, accepted = spec["campaign"], fs_spec["campaign"]
    if (type(camp) is not dict or set(camp) != CAMPAIGN_KEYS or type(camp["analytic"]) is not dict
            or set(camp["analytic"]) != ANALYTIC_KEYS):
        raise ValueError("campaign fields mismatch")
    if (camp["layered_order"] not in accepted["orders"]
            or camp["homogeneous_order"] != accepted["homogeneous"]["order"]
            or camp["steps_per_horizon"] not in accepted["time_steps"]):
        raise ValueError("fixtures use only the accepted campaign's quadrature orders and time levels")
    steps = camp["committed_steps"]
    if (type(steps) is not list or len(steps) != 3 or any(type(n) is not int for n in steps)
            or not 1 <= steps[0] < steps[1] < steps[2] <= camp["steps_per_horizon"]):
        raise ValueError("three increasing committed step counts within one horizon required")
    eps = camp["relative_tolerances"]
    if (type(eps) is not list or not eps or any(not 0 < w.number(e, "relative tolerance") < 1 for e in eps)
            or eps != sorted(set(eps)) or retained["relative_tolerance"] not in eps):
        raise ValueError("relative tolerances lie in (0, 1), increase and include the retained allowance")
    w.positive(camp["displacement_limit_m"], "displacement limit")
    a = camp["analytic"]
    if a["order"] != 2:
        raise ValueError("the exact closed forms use order-2 Gauss widths h/2")
    if not 1 < w.number(a["stretch"], "analytic stretch") <= c["stretch_window"][1]:
        raise ValueError("analytic stretch must lie inside the extension window")
    w.positive(a["duration_s"], "analytic duration")
    w.number(a["weakened_history"], "weakened history", nonnegative=True)
    pol = spec["policy"]
    if type(pol) is not dict or set(pol) != POLICY_KEYS:
        raise ValueError("policy fields mismatch")
    if not 0 < w.number(pol["maximum_seconds"], "maximum seconds") <= 120:
        raise ValueError("cooperative budget must lie in (0, 120] s")
    for key, ceiling in (("numerical_allowance_relative", ca.POLICY["inequality_relative"]),
                         ("oracle_relative", ca.POLICY["oracle_relative"])):
        if not 0 < w.number(pol[key], key) <= ceiling:
            raise ValueError("policy relaxes a retained tolerance: "+key)
    for key, cap in (("repetitions", 100), ("batches", 9)):
        if type(pol[key]) is not int or not 1 <= pol[key] <= cap:
            raise ValueError(key+" outside the bounded benchmark")
    return spec, dict(case=spec, fs=fs_spec, fs_ctx=fs_ctx, retained=retained)


def load_case(path=CASE):
    return validate_case(json.loads(Path(path).read_text(encoding="utf-8")))


CASE_MUTATIONS = (
    ("widened_stretch", ("contract", "stretch_window"), [.6, 1.5]),
    ("widened_temperature", ("contract", "temperature_window_k"), [200., 1700.]),
    ("horizon_beyond", ("contract", "horizon_s"), 1.1e14),
    ("pore_pressure", ("contract", "pore_pressure_pa"), 1e6),
    ("other_input", ("inputs", "finite_strain_case"), "cases/i01_thermomechanical_motion_v1.json"),
    ("unaccepted_order", ("campaign", "layered_order"), 48),
    ("unaccepted_time_level", ("campaign", "steps_per_horizon"), 100),
    ("steps_beyond_horizon", ("campaign", "committed_steps"), [32, 96, 256]),
    ("tolerance_at_one", ("campaign", "relative_tolerances"), [.01, 1.]),
    ("retained_allowance_dropped", ("campaign", "relative_tolerances"), [.1]),
    ("relaxed_allowance", ("policy", "numerical_allowance_relative"), 1e-6),
    ("relaxed_oracle", ("policy", "oracle_relative"), 1e-6),
    ("budget_beyond_ceiling", ("policy", "maximum_seconds"), 300.),
    ("missing_policy_key", ("policy", "batches"), KeyError))


# ----------------------------------------------------------------------------- fixtures and comparisons

def single_layer(ctx, layer, order):
    """One authored supplied-pressure layer with an insulated support at its own temperature, built as the retained
    homogeneous fixture is; returns the preparation, the support and the inputs key."""
    base = w.prepare([layer], order, closure=w.SUPPLIED)
    hom = ctx["fs_ctx"]["heat"]["campaign"]["homogeneous"]["thermal"]
    props = [dict(name=layer["name"], conductivity_w_m_k=hom["conductivity_w_m_k"],
                  heat_capacity_j_kg_k=hom["heat_capacity_j_kg_k"], radiogenic_w_m3=0.)]
    insulated = dict(top=dict(type="insulated"), bottom=dict(type="insulated"))
    thermal = heat.prepare_thermal(base.layer, base.depth_m, base.weight, [layer["thickness_m"]], props,
                                   [hom["density_kg_m3"]], insulated, reference_temperature=layer["temperature_k"][0],
                                   mechanical_fingerprint=base.fingerprint)
    return base, thermal, ([layer], order, w.SUPPLIED, None)


def fixtures(spec, ctx, deadline=None):
    """Issued states of the accepted layered strip and its homogeneous fixture: one Evolution each, one fixed step.

    evolved() runs the retained evolve from the reference for n steps. A run of n steps over n dt reproduces the
    first n steps of any longer run with that step bitwise (the atomic-prefix property of the accepted finite-strain
    refusal control), so every issued state lies on one discrete trajectory. No solver step is re-implemented and no
    per-step history is kept; the raw outputs are kept only for the numerical diagnostics.
    """
    fc, camp = ctx["fs_ctx"], spec["campaign"]
    law, drive, common = fc["law"], fc["drive"], settings(spec, ctx)
    base, thermal, key, _ = fs.layered(fc, camp["layered_order"])
    hb, ht, h = tm.homogeneous_setup(fc, camp["homogeneous_order"])
    hkey = ([h["layer"]], camp["homogeneous_order"], w.SUPPLIED, None)
    out = {}
    for name, b, t, k, kappa0 in (("layered", base, thermal, key, w.initial_history(base, fc["weak"])),
                                  ("homogeneous", hb, ht, hkey, np.full(hb.size, float(h["initial_history"])))):
        evolution = Evolution(b, t, law, drive, k, kappa0, **common)
        runs, states = {}, {0: reference_state(evolution)}
        for n in camp["committed_steps"]:
            runs[n], states[n] = evolved(evolution, n, deadline=deadline)
        out[name] = dict(base=b, thermal=t, key=k, evolution=evolution, runs=runs, states=states)
    return out


def observed(f, start, end, dt):
    """The retained numerical continuation over steps [start, end] from raw outputs, which serve diagnostics only and
    are never evolution evidence: the two committed endpoint speeds and forces and the window's aggregate accounts."""
    last = f["runs"][end]
    if start == 0:
        speed, force, moved, work = last["velocity_start_m_s"], last["column_force_start_n_m"], 0., 0.
    else:
        s = f["runs"][start]
        speed, force = s["velocity_end_m_s"], s["column_force_end_n_m"]
        moved, work = s["displacement_m"], s["accounts"]["drive_work_j_m"]
    return dict(duration_s=dt*(end-start), speeds_m_s=[speed, last["velocity_end_m_s"]],
                forces_n_m=[force, last["column_force_end_n_m"]], displacement_m=last["displacement_m"]-moved,
                drive_work_j_m=last["accounts"]["drive_work_j_m"]-work, stretch_end=last["stretch"],
                kappa_end=last["kappa"], theta_end=last["theta"])


def compare(envelope, certificate, seen, start, allowance):
    """The numerical continuation against the exact envelope and the certificate: a diagnostic, never the proof.

    Every value is an exact rational of a computed float. ``allowance`` covers only the retained kernel's root
    tolerances and floating evaluation; it never enters an admission decision. Only what ``observed`` returns is
    inspected: the window's two committed endpoint stages (speed and column force), its aggregate displacement,
    drive work and stretch gain, and the endpoint history and temperatures. Intermediate predictor and committed
    stages are not seen and no trajectory is stored. Per-stage bounds imply the aggregate ones, not the reverse: the
    conditional argument of the method covers every balanced stage, these observations do not.
    """
    b, a = envelope.balance, Fraction(allowance)
    v0, duration = b.force/b.drag, Fraction(seen["duration_s"])
    lower = max(Fraction(0), (b.force-b.yield_force)/(b.drag+b.coefficient))
    speeds = [Fraction(v) for v in seen["speeds_m_s"]]
    forces = [Fraction(r) for r in seen["forces_n_m"]]
    moved, work = Fraction(seen["displacement_m"]), Fraction(seen["drive_work_j_m"])
    gain = Fraction(seen["stretch_end"])-Fraction(start.stretch)
    reach = v0*duration/Fraction(envelope.drive.width_m)
    _, _, tlo, thi = envelope.window
    temperature = np.asarray(envelope.thermal.steady_k)+seen["theta_end"]
    limits = [b.yield_force+b.coefficient*v for v in speeds]
    checks = dict(
        force_envelope=all(r <= limit*(1+a) for r, limit in zip(forces, limits)),
        speed_between_bound_and_free=all(lower*(1-a) <= v <= v0*(1+a) for v in speeds),
        displacement_between=lower*duration*(1-a) <= moved <= v0*duration*(1+a),
        drive_work_between=b.force*lower*duration*(1-a) <= work <= b.force*v0*duration*(1+a),
        stretch_within_reach=0 <= gain <= reach*(1+a),
        history_above_floor=bool(np.all(seen["kappa_end"] >= envelope.history_floor)),
        temperature_inside=bool(np.all((temperature >= tlo) & (temperature <= thi))))
    if certificate["numerical_admissible"]:
        checks.update(
            certified_speed=all(v0-v <= Fraction(certificate["speed_error_bound_m_s"])+a*v0 for v in speeds),
            certified_displacement=v0*duration-moved <= Fraction(certificate["displacement_error_bound_m"])
            + a*v0*duration,
            certified_drive_work=b.force*v0*duration-work <= Fraction(certificate["driving_work_error_bound_J_m"])
            + a*b.force*v0*duration)
    margins = dict(force_to_envelope=[float(r/limit) for r, limit in zip(forces, limits)],
                   speed_deficit=[float(1-v/v0) for v in speeds], speed_deficit_bound=float(1-lower/v0),
                   displacement_deficit=float(1-moved/(v0*duration)), stretch_gain=float(gain),
                   stretch_reach=float(reach))
    return {key: bool(value) for key, value in checks.items()}, margins


def view(result):
    """Reportable scalars of one admission result."""
    return {key: result[key] for key in VIEW if key in result}


def earliest(state, drive):
    """The earliest elapsed time consistent with a state's stretch under drag-only motion, rounded up. The controls
    use it to build clock rollbacks that this slack inequality alone would pass and provenance refuses."""
    return d.upper_float((Fraction(state.stretch)-1)*Fraction(drive.width_m)*Fraction(drive.drag_pa_s)
                         / Fraction(drive.force_n_m))


def unchanged(a, b):
    """Recursive equality of evolution outputs: dicts, arrays bitwise and scalars."""
    if type(a) is dict:
        return type(b) is dict and a.keys() == b.keys() and all(unchanged(a[k], b[k]) for k in a)
    if isinstance(a, np.ndarray):
        return isinstance(b, np.ndarray) and a.dtype == b.dtype and bool(np.array_equal(a, b))
    return type(a) is type(b) and a == b


def refusal(fn, reasons, kinds=(ValueError,)):
    """Whether ``fn`` refuses with an expected exception and reason; a returned result is never a refusal."""
    try:
        fn()
    except Exception as exc:                     # an unexpected kind or reason is recorded as a failed refusal
        text = str(exc).replace(str(ROOT), "TECTONICS_ROOT")
        return dict(refused=isinstance(exc, kinds) and any(r in text for r in reasons),
                    reason=type(exc).__name__+": "+text)
    return dict(refused=False, reason="returned a result")


# ----------------------------------------------------------------------------- controls

def analytic_control(spec, ctx, fix, deadline=None):
    """The envelope formula at authored floors against closed forms (a formula check: no state, clock or certificate),
    the retained stage at the current geometry against a closed form, the exact threshold admitted from the rate-linear
    layer's own issued reference state, a genuinely uncertifiable issued state and the unchanged fixed-column guard."""
    pol, camp = spec["policy"], spec["campaign"]
    a, fc = camp["analytic"], ctx["fs_ctx"]
    law, drive, scope, g = fc["law"], fc["drive"], scope_of(spec), DERIVED_ROUNDING
    allowance = Fraction(pol["numerical_allowance_relative"])
    lam, force, drag, w0 = (Fraction(x) for x in (a["stretch"], drive.force_n_m, drive.drag_pa_s, drive.width_m))
    window = dict(duration_s=a["duration_s"], displacement_limit_m=camp["displacement_limit_m"], deadline=deadline)

    def formula(base, rule, history, stretch=a["stretch"]):
        return envelope_balance(base, rule, drive, stretch, history, deadline=deadline)

    def stage(base, thermal, rule, kappa):
        return fs.stage(base, fs.coefficients(base), rule, a["stretch"], np.asarray(thermal.steady_k), kappa, drive,
                        (1., 1.), deadline=deadline)

    def obeys(b, s):
        v, r = Fraction(s["velocity_m_s"]), Fraction(s["force"])
        lower = max(Fraction(0), (b.force-b.yield_force)/(b.drag+b.coefficient))
        return bool(r <= (b.yield_force+b.coefficient*v)*(1+allowance) and lower*(1-allowance) <= v)

    def shown(b):
        return dict(yield_bound_n_m=d.upper_float(b.yield_force), linear_bound_pa_s=d.upper_float(b.coefficient))

    # Rate-linear layer without yield strength: Ybar = 0 and Abar is a closed form (order-2 widths are h/2 each).
    layer = ca.analytic_layer()
    base, thermal, key = single_layer(ctx, layer, a["order"])
    zero = np.zeros(base.size)
    linear = formula(base, w.OFF, zero)
    h0, eta, creep = (Fraction(x) for x in (layer["thickness_m"], layer["plastic_viscosity_pa_s"],
                                            layer["creep"][0]["a"]))
    stiffness = 2*h0/(w0*(creep+1/(2*eta)))         # e = (A + 1/(2 eta)) s at zero yield; R = 2 (h0/lam) s
    exact_v = force/(drag+stiffness/(lam*lam))
    s = stage(base, thermal, w.OFF, zero)
    # The exact threshold through the public route, from this layer's own issued reference state (lam = 1, t = 0).
    at = reference_state(Evolution(base, thermal, w.OFF, drive, key, zero, **settings(spec, ctx)))
    start = prepare(base, thermal, w.OFF, drive, key, at, **scope, deadline=deadline)
    b = start.balance
    edge = b.coefficient/(b.drag+b.coefficient)
    equality = admit(start, base, thermal, w.OFF, drive, at, relative_tolerance=edge, **window)
    tighter = admit(start, base, thermal, w.OFF, drive, at, relative_tolerance=edge-Fraction(1, 10**30), **window)
    # Weakened, pressure-sensitive homogeneous layer of the accepted case at order 2 and the represented overburden.
    hb, ht, h = tm.homogeneous_setup(fc, a["order"])
    uniform = h["layer"]
    floor, softest = np.full(hb.size, float(a["weakened_history"])), np.full(hb.size, float(law.end))
    weakened, softer, reference = formula(hb, law, floor), formula(hb, law, softest), formula(hb, law, floor, 1.)
    lc, lf = (Fraction(x) for x in w.aspect_factors(a["weakened_history"], law))    # independent ASPECT transcription
    kappa = Fraction(a["weakened_history"])
    c0, phi0, eta0, thick = (Fraction(x) for x in (uniform["cohesion_pa"], uniform["friction_rad"],
                                                   uniform["plastic_viscosity_pa_s"], uniform["thickness_m"]))
    loads = sum(Fraction(q)*Fraction(p) for q, p in zip(hb.weight, hb.reference_pa))     # represented overburden
    closed_y = 2*g*(thick*c0*lc+loads*min(Fraction(1), phi0*lf)/lam)/lam
    closed_a = 4*g*thick*eta0/(w0*lam*lam)
    at_floor, above = stage(hb, ht, law, floor), stage(hb, ht, law, softest)
    # The accepted layered strip at its issued reference state: its yield bound alone exceeds the drive.
    lx = fix["layered"]
    origin = lx["states"][0]
    first = step_s(spec)*camp["committed_steps"][0]
    layered = prepare(lx["base"], lx["thermal"], law, drive, lx["key"], origin, **scope, deadline=deadline)
    hopeless = admit(layered, lx["base"], lx["thermal"], law, drive, origin, duration_s=first,
                     relative_tolerance=1-2.**-20, displacement_limit_m=1e9, deadline=deadline)
    old = ca.prepare(lx["base"], law, origin.kappa, drive, deadline=deadline)
    guard = refusal(lambda: ca.admit(old, lx["base"], law, origin.kappa, drive, duration_s=first, used_strain=0.,
                                     relative_tolerance=ctx["retained"]["relative_tolerance"],
                                     displacement_limit_m=camp["displacement_limit_m"], deadline=deadline),
                    ("small-strain",))
    results = (equality, tighter, hopeless)
    checks = dict(
        linear_envelope_closed_form=sum(Fraction(q) for q in base.weight) == h0 and linear.yield_force == 0
        and linear.coefficient == 4*g*eta*h0/(w0*lam*lam) and b.yield_force == 0 and b.coefficient == 4*g*eta*h0/w0,
        prepare_uses_the_formula=b == formula(base, w.OFF, zero, 1.) and start.evolution is at.evolution,
        stage_at_current_geometry=w.relative_change(s["velocity_m_s"], float(exact_v)) <= pol["oracle_relative"]
        and s["width_m"] == drive.width_m*a["stretch"] and s["thickness_m"] == base.thickness_m/a["stretch"],
        linear_bound_holds=force/(drag+linear.coefficient) <= exact_v and obeys(linear, s),
        exact_threshold=equality["status"] == CERTIFIED and tighter["status"] == NOT_CERTIFIED,
        weakened_envelope_closed_form=sum(Fraction(q) for q in hb.weight) == thick
        and ca.factor_at(kappa, law, "cohesion_factor") == lc and ca.factor_at(kappa, law, "friction_factor") == lf
        and weakened.yield_force == closed_y and weakened.coefficient == closed_a,
        weakened_bound_holds=obeys(weakened, at_floor) and obeys(weakened, above) and obeys(softer, above),
        floors_tighten=softer.yield_force < weakened.yield_force < reference.yield_force
        and weakened.coefficient < reference.coefficient,
        layered_genuinely_uncertifiable=layered.balance.yield_force > layered.balance.force
        and hopeless["status"] == NOT_CERTIFIED and hopeless["speed_lower_bound_m_s"] == 0.,
        old_small_strain_guard_unchanged=guard["refused"],
        no_separation=not any(r["generated_separation_authorised"] for r in results))
    return w.verdict(
        checks,
        linear=dict(exact_speed_m_s=float(exact_v), stage_speed_m_s=s["velocity_m_s"],
                    stage_relative=w.relative_change(s["velocity_m_s"], float(exact_v)), threshold=float(edge),
                    equality=view(equality), tighter=view(tighter), formula_at_stretch=shown(linear),
                    at_reference=shown(b)),
        weakened=dict(factors=[float(lc), float(lf)], stage_force_to_envelope=float(
                          Fraction(at_floor["force"])/(weakened.yield_force+weakened.coefficient
                                                       * Fraction(at_floor["velocity_m_s"]))),
                      overburden_offset_pa=float(max(abs(Fraction(p)-Fraction(uniform["mean_pressure_pa"][0]))
                                                     for p in hb.reference_pa)),
                      floor=shown(weakened), fully_weakened=shown(softer), reference=shown(reference)),
        layered=dict(yield_bound_to_force=float(layered.balance.yield_force/layered.balance.force),
                     certificate=view(hopeless)),
        old_guard=guard,
        note="closed forms evaluate the envelope formula at authored floors, never a state; every certificate here is "
             "admitted from an issued reference state")


def trajectory_control(spec, ctx, fix, deadline=None):
    """Certificates from the issued reference and a later issued state against the retained numerical continuation
    of the accepted layered strip and its homogeneous fixture, while stretch, temperature and history evolve inside
    each window. Exact bounds, numerical values and the declared allowance are reported apart; the numerical side
    sees each window's two committed endpoint stages and its aggregates, not every intermediate stage."""
    pol, camp = spec["policy"], spec["campaign"]
    law, drive, dt = ctx["fs_ctx"]["law"], ctx["fs_ctx"]["drive"], step_s(spec)
    first, second, _ = camp["committed_steps"]
    small = ctx["fs_ctx"]["heat"]["representation"]["max_axial_strain"]      # the retained small-strain guard
    retained, coarse = ctx["retained"]["relative_tolerance"], max(camp["relative_tolerances"])
    rows, found, evolving = [], {}, []
    for name, f in fix.items():
        args = (f["base"], f["thermal"], law, drive)
        for start, end in ((0, first), (first, second)):
            origin = f["states"][start]
            envelope = prepare(*args, f["key"], origin, **scope_of(spec), deadline=deadline)
            seen = observed(f, start, end, dt)
            moved = dict(temperature_change_k=float(np.abs(seen["theta_end"]-origin.theta).max()),
                         history_gain=float((seen["kappa_end"]-origin.kappa).max()),
                         stretch=[origin.stretch, seen["stretch_end"]])
            evolving.append(moved["temperature_change_k"] > 0 and moved["history_gain"] > 0
                            and seen["stretch_end"] > origin.stretch)
            for eps in camp["relative_tolerances"]:
                cert = admit(envelope, *args, origin, duration_s=seen["duration_s"], relative_tolerance=eps,
                             displacement_limit_m=camp["displacement_limit_m"], deadline=deadline)
                checks, margins = compare(envelope, cert, seen, origin, pol["numerical_allowance_relative"])
                found[name, start, eps] = (cert, checks, seen)
                rows.append(dict(fixture=name, start_step=start, end_step=end, relative_tolerance=eps,
                                 certificate=view(cert), numerical=dict(margins, **moved), checks=checks))
    certs = {key: value[0] for key, value in found.items()}
    checks = dict(
        numerical_within_exact_bounds=all(all(value[1].values()) for value in found.values()),
        layered_visibly_uncertified=all(c["status"] == NOT_CERTIFIED and "speed_error_bound_m_s" not in c
                                        for (name, _, _), c in certs.items() if name == "layered"),
        weak_belt_certified_at_coarse_allowance=all(certs["homogeneous", s, coarse]["status"] == CERTIFIED
                                                    for s in (0, first)),
        weak_belt_not_certified_at_retained_allowance=all(certs["homogeneous", s, retained]["status"] == NOT_CERTIFIED
                                                          for s in (0, first)),
        state_evolves_in_every_window=all(evolving),
        certified_beyond_small_strain=math.log(found["homogeneous", first, coarse][2]["stretch_end"]) > small,
        no_separation=not any(c["generated_separation_authorised"] for c in certs.values()))
    return w.verdict(checks, windows=rows, numerical_allowance_relative=pol["numerical_allowance_relative"],
                     small_strain_guard=small,
                     note="numerical values come from the retained evolve's raw outputs: each window's two committed "
                          "endpoint stages and its aggregate displacement, drive work and stretch gain; intermediate "
                          "stages are not inspected; the allowance covers root tolerances and floating evaluation "
                          "only; a passing comparison is a diagnostic, not the proof")


def repeat_control(spec, ctx, fix, deadline=None):
    """Admission again at a later issued state with the envelope prepared earlier and with one renewed there. The later
    state must lie inside the prepared floors; the evolution, absolute reference, cumulative horizon and history floor
    are carried, never reset. Edited, rebuilt or foreign states, and an envelope renewed from an edited state, are
    refused, including a partial clock rollback that the drag-only reachability inequality alone would pass."""
    pol, camp = spec["policy"], spec["campaign"]
    law, drive, dt = ctx["fs_ctx"]["law"], ctx["fs_ctx"]["drive"], step_s(spec)
    first, second, last = camp["committed_steps"]
    coarse, horizon = max(camp["relative_tolerances"]), spec["contract"]["horizon_s"]
    rows, refused, flags = [], {}, {}
    for name, f in fix.items():
        args = (f["base"], f["thermal"], law, drive)
        early, later = f["states"][first], f["states"][second]
        carried = prepare(*args, f["key"], early, **scope_of(spec), deadline=deadline)
        renewed = prepare(*args, f["key"], later, **scope_of(spec), deadline=deadline)
        whole = prepare(*args, f["key"], f["states"][0], **scope_of(spec), deadline=deadline)
        seen = observed(f, second, last, dt)
        kw = dict(duration_s=seen["duration_s"], relative_tolerance=coarse,
                  displacement_limit_m=camp["displacement_limit_m"], deadline=deadline)
        again, fresh = admit(carried, *args, later, **kw), admit(renewed, *args, later, **kw)
        carried_checks, carried_margins = compare(carried, again, seen, later, pol["numerical_allowance_relative"])
        fresh_checks, fresh_margins = compare(renewed, fresh, seen, later, pol["numerical_allowance_relative"])
        cb, rb = carried.balance, renewed.balance
        early_time, late_time = earliest(early, drive), earliest(later, drive)
        partial = dataclasses.replace(later, elapsed_s=(later.elapsed_s+late_time)/2)    # the reviewed reproduction
        rebuilt = State(later.stretch, partial.elapsed_s, later.width_m, later.thickness_m, later.kappa, later.theta,
                        later.reference)
        weaker = reference_state(dataclasses.replace(f["evolution"], kappa0=np.maximum(f["evolution"].kappa0,
                                                                                       law.end)))
        flags[name] = dict(
            carried_within_bounds=all(carried_checks.values()), renewed_within_bounds=all(fresh_checks.values()),
            inside_prepared_floors=later.stretch >= carried.stretch_floor
            and later.elapsed_s >= carried.elapsed_floor_s and bool(np.all(later.kappa >= carried.history_floor)),
            window_is_cumulative=again["window_start_s"] == later.elapsed_s and again["horizon_s"] == horizon
            and again["window_end_s"] == d.upper_float(Fraction(later.elapsed_s)+Fraction(seen["duration_s"])),
            renewed_at_least_as_tight=rb.yield_force <= cb.yield_force and rb.coefficient <= cb.coefficient
            and fresh["speed_lower_bound_m_s"] >= again["speed_lower_bound_m_s"],
            one_evolution_carried=carried.evolution is renewed.evolution is later.evolution is f["evolution"],
            # Each rollback keeps the clock above the earliest reachable time, and the foreign reference state lies
            # inside every floor of the whole-horizon envelope, so only provenance can refuse them.
            candidates_inside_old_checks=early_time < early.elapsed_s
            and late_time < partial.elapsed_s < later.elapsed_s and bool(np.all(weaker.kappa >= whole.history_floor)))
        unissued = ("not issued",)
        for key, fn, reasons in (
                ("beyond_horizon", lambda: admit(carried, *args, later, **dict(kw, duration_s=seen["duration_s"]+dt)),
                 ("cumulative horizon",)),
                ("partial_clock_rollback", lambda: admit(carried, *args, partial, **dict(
                    kw, duration_s=horizon-partial.elapsed_s)), unissued),
                ("renewed_envelope_rollback", lambda: prepare(*args, f["key"], partial, **scope_of(spec)), unissued),
                ("rebuilt_state", lambda: admit(carried, *args, rebuilt, **kw), unissued),
                ("reset_clock", lambda: admit(whole, *args, dataclasses.replace(later, elapsed_s=0.), **kw), unissued),
                ("before_preparation", lambda: admit(carried, *args, dataclasses.replace(early, elapsed_s=early_time),
                                                     **kw), unissued),
                ("re_referenced_state", lambda: admit(carried, *args, dataclasses.replace(later, stretch=1.), **kw),
                 unissued),
                ("relabelled_history", lambda: admit(carried, *args, dataclasses.replace(early, kappa=later.kappa),
                                                     **kw), unissued),
                ("state_of_another_evolution", lambda: admit(whole, *args, weaker, **dict(kw, duration_s=dt)),
                 ("different evolution",)),
                ("reference_below_floors", lambda: admit(carried, *args, f["states"][0], **dict(kw, duration_s=dt)),
                 ("below the prepared floor", "stretch lies outside"))):
            refused[name+":"+key] = refusal(fn, reasons)
        rows.append(dict(fixture=name, start_step=second, end_step=last, carried=view(again), renewed=view(fresh),
                         carried_numerical=carried_margins, renewed_numerical=fresh_margins,
                         carried_checks=carried_checks, renewed_checks=fresh_checks))

    def every(flag_name):
        return all(flag[flag_name] for flag in flags.values())

    certs = [row[k] for row in rows for k in ("carried", "renewed")]
    checks = dict(
        numerical_within_exact_bounds=every("carried_within_bounds") and every("renewed_within_bounds"),
        later_state_inside_prepared_floors=every("inside_prepared_floors"),
        window_is_cumulative=every("window_is_cumulative"),
        renewed_envelope_at_least_as_tight=every("renewed_at_least_as_tight"),
        one_evolution_carried=every("one_evolution_carried"),
        weak_belt_certified_again=all(row[k]["status"] == CERTIFIED for row in rows
                                      if row["fixture"] == "homogeneous" for k in ("carried", "renewed")),
        layered_visibly_uncertified=all(row[k]["status"] == NOT_CERTIFIED for row in rows
                                        if row["fixture"] == "layered" for k in ("carried", "renewed")),
        edited_rebuilt_or_foreign_states_refused=every("candidates_inside_old_checks")
        and all(r["refused"] for r in refused.values()),
        no_separation=not any(c["generated_separation_authorised"] for c in certs))
    return w.verdict(checks, windows=rows, state_flags=flags, refusals=refused)


def refusal_control(spec, ctx, fix, deadline=None):
    """Unadmitted cases, changed identities, built, edited, imported or foreign states and envelopes, incomplete or
    expired evolutions, out-of-scope issued states and windows, malformed inputs, cancellation and deadlines refuse
    with their reason. A refusal issues nothing and changes no evolution output, issued state or envelope; the same
    candidate without its defect is certified."""
    camp, horizon = spec["campaign"], spec["contract"]["horizon_s"]
    law, drive, dt = ctx["fs_ctx"]["law"], ctx["fs_ctx"]["drive"], step_s(spec)
    f = fix["homogeneous"]
    base, thermal, key, ev = f["base"], f["thermal"], f["key"], f["evolution"]
    first, second, _ = camp["committed_steps"]
    origin, start, later = f["states"][0], f["states"][first], f["states"][second]
    args, scope, common = (base, thermal, law, drive), scope_of(spec), settings(spec, ctx)
    before = copy.deepcopy(f["runs"])
    envelope = prepare(*args, key, start, **scope, deadline=deadline)
    window = dict(duration_s=dt*(second-first), relative_tolerance=max(camp["relative_tolerances"]),
                  displacement_limit_m=camp["displacement_limit_m"], deadline=deadline)
    baseline = admit(envelope, *args, start, **window)
    layer = key[0][0]
    other, other_thermal, other_key = single_layer(ctx, dict(layer, cohesion_pa=layer["cohesion_pa"]/2), key[1])
    rigid, rigid_thermal, rigid_key = single_layer(ctx, dict(layer, plastic_viscosity_pa_s=None), key[1])
    wet, wet_thermal, wet_key = single_layer(ctx, dict(layer, pore_pressure_pa=[1e6, 1e6]), key[1])
    stale = (copy.deepcopy(key[0]), *key[1:])
    stale[0][0]["cohesion_pa"] = layer["cohesion_pa"]*(1+1e-12)
    steady = np.asarray(thermal.steady_k)
    stretched = fs.column_at(base, fs.coefficients(base), start.stretch, steady+start.theta)
    tlo, thi = spec["contract"]["temperature_window_k"]
    # Scope refusals use genuine issued states: the belt heats and widens between them, so an admitted window capped
    # at the earlier state's warmest point, or at stretch 1.2, excludes the later state.
    warmest, coolest = float((steady+start.theta).max()), float((steady+start.theta).min())
    capped = prepare(*args, key, start, window=dict(scope["window"], temperature_k=[tlo, warmest]), horizon_s=horizon,
                     deadline=deadline)
    tight = prepare(*args, key, start, window=dict(scope["window"], stretch=[scope["window"]["stretch"][0], 1.2]),
                    horizon_s=horizon, deadline=deadline)
    whole = prepare(*args, key, origin, **scope, deadline=deadline)
    partial = dataclasses.replace(later, elapsed_s=(later.elapsed_s+earliest(later, drive))/2)
    built = State(later.stretch, later.elapsed_s, later.width_m, later.thickness_m, later.kappa, later.theta,
                  later.reference)                     # every value genuine; only the issue mark is missing
    weaker = reference_state(dataclasses.replace(ev, kappa0=np.full(base.size, float(law.end))))
    foreign = reference_state(Evolution(other, other_thermal, law, drive, other_key, ev.kappa0, **common))
    brief = dict(ev.window, stretch=[ev.window["stretch"][0], 1.01])      # the belt leaves it within a few steps
    free = d.Balance(drive.force_n_m, drive.drag_pa_s, 0, 0, 1)
    squeeze = motion.Drive(-drive.force_n_m, drive.drag_pa_s, drive.width_m)
    rest = motion.Drive(0., drive.drag_pa_s, drive.width_m)
    cancelled = threading.Event()
    cancelled.set()
    changed, v = ("changed preparation, support, law or drive",), (ValueError,)
    unissued, forged, raw = ("not issued",), ("envelope issued by prepare",), ("committed finite-strain state",)

    def at(state, env=envelope, **kw):
        return admit(env, *args, state, **dict(window, **kw))

    def changes(**kw):
        parts = dict(dict(base=base, thermal=thermal, law=law, drive=drive), **kw)
        return admit(envelope, parts["base"], parts["thermal"], parts["law"], parts["drive"], start, **window)

    attempts = [("case_"+name, lambda bad=tm.mutated(ctx["case"], path, value): validate_case(bad), ("",), v)
                for name, path, value in CASE_MUTATIONS]
    attempts += [
        ("changed_law", lambda: changes(law=w.WeakeningLaw(law.start, law.end, .5, law.friction_factor)), changed, v),
        ("changed_force", lambda: changes(drive=motion.Drive(1.5*drive.force_n_m, drive.drag_pa_s, drive.width_m)),
         changed, v),
        ("changed_drag", lambda: changes(drive=motion.Drive(drive.force_n_m, 2*drive.drag_pa_s, drive.width_m)),
         changed, v),
        ("changed_reference_width", lambda: changes(drive=motion.Drive(drive.force_n_m, drive.drag_pa_s,
                                                                       2*drive.width_m)), changed, v),
        ("replaced_preparation_copy", lambda: changes(base=dataclasses.replace(base)), changed, v),
        ("replaced_support_copy", lambda: changes(thermal=dataclasses.replace(thermal)), changed, v),
        ("other_material", lambda: changes(base=other, thermal=other_thermal), changed, v),
        # Provenance: only this module issues states and envelopes, whatever values a candidate carries.
        ("built_state_of_genuine_values", lambda: at(built, duration_s=dt), unissued, v),
        ("partial_clock_rollback", lambda: at(partial, duration_s=horizon-partial.elapsed_s), unissued, v),
        ("renewed_envelope_rollback", lambda: prepare(*args, key, partial, **scope), unissued, v),
        ("reset_clock", lambda: at(dataclasses.replace(later, elapsed_s=0.), env=whole), unissued, v),
        ("before_preparation", lambda: at(dataclasses.replace(start, elapsed_s=earliest(start, drive))), unissued, v),
        ("edited_reference", lambda: at(dataclasses.replace(start, reference=other.fingerprint)), unissued, v),
        ("re_referenced_state", lambda: at(dataclasses.replace(later, stretch=1.)), unissued, v),
        ("edited_history", lambda: at(dataclasses.replace(start, kappa=later.kappa)), unissued, v),
        ("edited_history_shape", lambda: at(dataclasses.replace(start, kappa=np.zeros(3))), unissued, v),
        ("edited_temperature", lambda: at(dataclasses.replace(later, theta=start.theta), duration_s=dt), unissued, v),
        ("edited_compressed_state", lambda: prepare(*args, key, dataclasses.replace(
            origin, stretch=.9, width_m=drive.width_m*.9, thickness_m=base.thickness_m/.9), **scope), unissued, v),
        ("raw_output_admitted", lambda: at(f["runs"][second], duration_s=dt), raw, v),
        ("raw_output_prepared", lambda: prepare(*args, key, f["runs"][second], **scope), raw, v),
        ("state_of_another_evolution", lambda: at(weaker, env=whole, duration_s=dt), ("different evolution",), v),
        ("state_of_another_material", lambda: at(foreign, env=whole, duration_s=dt), ("different preparation",), v),
        ("edited_envelope_horizon", lambda: at(start, env=dataclasses.replace(envelope, horizon_s=2*horizon)),
         forged, v),
        ("edited_envelope_floors", lambda: at(origin, env=dataclasses.replace(
            envelope, stretch_floor=1., elapsed_floor_s=0., history_floor=origin.kappa), duration_s=dt), forged, v),
        ("edited_envelope_bound", lambda: at(start, env=dataclasses.replace(envelope, balance=free)), forged, v),
        ("built_envelope", lambda: at(start, env=FiniteEnvelope(
            base, thermal, law, drive, envelope.window, horizon, envelope.stretch_floor, envelope.elapsed_floor_s,
            envelope.history_floor, free)), forged, v),
        # An evolution issues only complete runs at its own settings.
        ("not_an_evolution", lambda: reference_state(dict(base=base)), ("authorised evolution",), v),
        ("evolution_steps", lambda: evolved(ev, 0), ("steps",), v),
        ("stale_evolution_key", lambda: Evolution(base, thermal, law, drive, stale, ev.kappa0, **common),
         ("stale",), v),
        ("evolution_starts_outside_window", lambda: dataclasses.replace(
            ev, theta0=np.full(base.size, thi-float(steady.min())+1.)), ("evolution window",), v),
        ("transported_pore_pressure", lambda: Evolution(wet, wet_thermal, law, drive, wet_key, ev.kappa0, **common),
         ("pore pressure",), v),
        ("incomplete_evolution", lambda: evolved(dataclasses.replace(ev, window=brief), first),
         ("complete retained",), v),
        ("expired_evolution", lambda: evolved(ev, first, deadline=time.perf_counter()-1.), ("time budget",),
         (RuntimeError,)),
        # Scope, with genuine issued states.
        ("temperature_above_window", lambda: at(later, env=capped, duration_s=dt), ("temperature",), v),
        ("temperature_below_window", lambda: prepare(*args, key, start, window=dict(
            scope["window"], temperature_k=[coolest+1., thi]), horizon_s=horizon), ("temperature",), v),
        ("earlier_state_below_floors", lambda: at(origin, duration_s=dt),
         ("below the prepared floor", "stretch lies outside"), v),
        ("stretch_beyond_window", lambda: at(later, env=tight, duration_s=dt), ("stretch lies outside",), v),
        ("beyond_horizon", lambda: at(later, duration_s=horizon-later.elapsed_s+dt), ("cumulative horizon",), v),
        ("reach_beyond_tighter_window", lambda: at(start, env=tight), ("drag-only reach",), v),
        ("full_horizon_from_reference", lambda: at(origin, env=whole, duration_s=horizon), ("drag-only reach",), v),
        ("compression_drive", lambda: prepare(base, thermal, law, squeeze, key, origin, **scope),
         ("positive extension",), v),
        ("zero_drive", lambda: prepare(base, thermal, law, rest, key, origin, **scope), ("positive extension",), v),
        ("widened_stretch_window", lambda: prepare(*args, key, start, window=dict(scope["window"], stretch=[.6, 1.5]),
                                                   horizon_s=horizon), ("window",), v),
        ("widened_temperature_window", lambda: prepare(*args, key, start, window=dict(
            scope["window"], temperature_k=[273., 1700.]), horizon_s=horizon), ("window",), v),
        ("horizon_beyond_accepted", lambda: prepare(*args, key, start, window=scope["window"], horizon_s=1.1*horizon),
         ("horizon",), v),
        ("stale_inputs", lambda: prepare(*args, stale, start, **scope), ("do not reproduce",), v),
        ("stretched_preparation_as_reference", lambda: prepare(stretched, thermal, law, drive, key, start, **scope),
         ("thermal support",), v),
        ("foreign_support", lambda: prepare(base, other_thermal, law, drive, key, start, **scope),
         ("thermal support",), v),
        ("missing_plastic_branch", lambda: prepare(rigid, rigid_thermal, law, drive, rigid_key, reference_state(
            Evolution(rigid, rigid_thermal, law, drive, rigid_key, ev.kappa0, **common)), **scope),
         ("plastic regularisation",), v),
        ("state_value", lambda: dataclasses.replace(start, stretch="1.1"), ("stretch",), v),
        ("not_an_envelope", lambda: admit(None, *args, start, **window), ("envelope",), v),
        ("not_a_state", lambda: at(dict(stretch=start.stretch)), ("committed finite-strain state",), v),
        ("cancelled_preparation", lambda: prepare(*args, key, start, **scope, cancel=cancelled), ("cancelled",),
         (CancelledError,)),
        ("cancelled_admission", lambda: at(start, cancel=cancelled), ("cancelled",), (CancelledError,)),
        ("expired_deadline", lambda: at(start, deadline=time.perf_counter()-1.), ("time budget",), (RuntimeError,))]
    attempts += [("duration_%r" % (x,), lambda x=x: at(start, duration_s=x), ("duration",), v)
                 for x in (0., -1., math.nan, math.inf, True, "1e13", None)]
    attempts += [("tolerance_%r" % (x,), lambda x=x: at(start, relative_tolerance=x), ("relative tolerance",), v)
                 for x in (1., 1.5, -.1, math.nan)]
    attempts += [("displacement_limit_%r" % (x,), lambda x=x: at(start, displacement_limit_m=x), ("displacement",), v)
                 for x in (-1., math.nan)]
    results = {name: refusal(fn, reasons, kinds) for name, fn, reasons, kinds in attempts}
    try:
        validate_case(ctx["case"])
        case_valid = True
    except ValueError:
        case_valid = False
    checks = dict(
        case_itself_valid=case_valid,
        baseline_certified=baseline["status"] == CERTIFIED,
        # The genuine later state really leaves the capped and tight windows; the rollback keeps the old slack; the
        # other evolution's reference lies inside every floor of the whole-horizon envelope.
        candidate_premises=float((steady+later.theta).max()) > warmest and later.stretch > tight.window[1]
        and earliest(later, drive) < partial.elapsed_s < later.elapsed_s
        and bool(np.all(weaker.kappa >= whole.history_floor)),
        every_candidate_refused_for_its_reason=all(r["refused"] for r in results.values()),
        evolution_outputs_unchanged=unchanged(before, f["runs"]),
        issued_states_read_only=all(s.evolution is ev and not s.kappa.flags.writeable and not s.theta.flags.writeable
                                    for s in f["states"].values())
        and not ev.kappa0.flags.writeable and not ev.theta0.flags.writeable,
        envelope_unchanged=not envelope.history_floor.flags.writeable and at(start) == baseline,
        no_separation=not baseline["generated_separation_authorised"])
    return w.verdict(checks, baseline=view(baseline), refusals=results, attempted=len(results))


def reuse_control(spec, ctx, fix, deadline=None):
    """The same public admissions with the prepared envelope reused versus rebuilt from the same issued state at every
    call; answers must match exactly. Raw seconds of one small comparison, not a generator forecast."""
    pol, camp = spec["policy"], spec["campaign"]
    law, drive, dt = ctx["fs_ctx"]["law"], ctx["fs_ctx"]["drive"], step_s(spec)
    first, second, last = camp["committed_steps"]
    kw = dict(duration_s=dt*(last-second), displacement_limit_m=camp["displacement_limit_m"], deadline=deadline)
    prepared, answers = {}, {}
    for name, f in fix.items():
        args = (f["base"], f["thermal"], law, drive)
        prepared[name] = prepare(*args, f["key"], f["states"][first], **scope_of(spec), deadline=deadline)
        answers[name] = {eps: admit(prepared[name], *args, f["states"][second], relative_tolerance=eps, **kw)
                         for eps in camp["relative_tolerances"]}

    def call(name, cold, eps):
        f = fix[name]
        args = (f["base"], f["thermal"], law, drive)
        env = prepare(*args, f["key"], f["states"][first], **scope_of(spec), deadline=deadline) if cold \
            else prepared[name]
        return admit(env, *args, f["states"][second], relative_tolerance=eps, **kw)

    samples, parity = dict(cold=[], reused=[]), True
    for batch in range(pol["batches"]):
        for mode in (("cold", "reused") if batch % 2 == 0 else ("reused", "cold")):
            ca.check_stop(None, deadline)
            begin = time.perf_counter()
            for _ in range(pol["repetitions"]):
                for name in fix:
                    for eps in camp["relative_tolerances"]:
                        parity &= call(name, mode == "cold", eps) == answers[name][eps]
            samples[mode].append(time.perf_counter()-begin)
    slow, fast = (statistics.median(samples[k]) for k in ("cold", "reused"))
    statuses = {name: {str(eps): a["status"] for eps, a in by.items()} for name, by in answers.items()}
    checks = dict(same_answers=bool(parity),
                  both_outcomes_exercised=CERTIFIED in statuses["homogeneous"].values()
                  and set(statuses["layered"].values()) == {NOT_CERTIFIED})
    calls = pol["repetitions"]*len(fix)*len(camp["relative_tolerances"])
    return w.verdict(checks, statuses=statuses, benchmark=dict(
        calls_per_batch=calls, batches=pol["batches"], samples_seconds=samples, cold_median_seconds=slow,
        reused_median_seconds=fast, saved_seconds=slow-fast, saved_percent=100*(1-fast/slow),
        points=dict(layered=fix["layered"]["base"].size, homogeneous=fix["homogeneous"]["base"].size),
        scope="the same public admissions at a later committed state: envelope reused versus rebuilt from the same "
              "preparing state every call; state guards and the exact gate run in both; evolutions excluded; no "
              "cache, log or parallel worker; not a simulation or world speed-up"))


CONTROLS = (("analytic", analytic_control), ("trajectory", trajectory_control), ("refusal", refusal_control),
            ("repeat", repeat_control), ("reuse", reuse_control))


# ----------------------------------------------------------------------------- evidence

def bindings():
    return {name: fs.digest(name) for name in NEW_FILES+RETAINED+tuple(ACCEPTED_RECEIPTS)}


def evidence_match(current):
    """Accepted receipts are their declared bytes; every source they recorded (including the retained tools, cases,
    documents, tests and earlier receipts) still has those bytes; imported modules resolve to their bound paths."""
    receipts = {name: current[name] == value for name, value in ACCEPTED_RECEIPTS.items()}
    recorded = {}
    for name in ACCEPTED_RECEIPTS:
        for source, value in json.loads((ROOT/name).read_text(encoding="utf-8"))["source_sha256"].items():
            recorded.setdefault(source, set()).add(value)
    sources = {}
    for source, values in sorted(recorded.items()):
        present = (ROOT/source).is_file()
        now = current[source] if source in current else (fs.digest(source) if present else None)
        sources[source] = present and len(values) == 1 and now in values
    retained = {name: sources.get(name, False) for name in RETAINED}
    imported = {name: Path(module.__file__).resolve() == (ROOT/name).resolve() for name, module in IMPORTED.items()}
    return dict(receipts=receipts, recorded_sources=sources, retained=retained, imported=imported)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream, threadpool_limits(limits=1, user_api="blas"):
        result = dict(schema="atlas.i01-finite-admission-evidence.v1", status="INCOMPLETE", scientific_acceptance=False,
                      runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                                   threadpoolctl=threadpoolctl.__version__, system=platform.system(),
                                   machine=platform.machine(), blas_threads=1),
                      controls={})
        start = time.perf_counter()
        try:
            before = bindings()
            match = evidence_match(before)
            result.update(source_sha256=before, evidence_match=match)
            if not all(all(group.values()) for group in match.values()):
                raise ValueError("bound sources or accepted receipts differ from the reviewed evidence; no control ran")
            spec, ctx = load_case()
            result["case"] = spec
            deadline = start+spec["policy"]["maximum_seconds"]          # cooperative budget counted after imports
            begin = time.perf_counter()
            fix = fixtures(spec, ctx, deadline)
            result["fixture_seconds"] = time.perf_counter()-begin
            for name, control in CONTROLS:
                begin = time.perf_counter()
                try:
                    data = control(spec, ctx, fix, deadline)
                    result["controls"][name] = dict(status="PASS" if data["passed"] else "FAIL",
                                                    seconds=time.perf_counter()-begin, **data)
                except (ValueError, RuntimeError) as exc:
                    result["controls"][name] = dict(status="FAIL", seconds=time.perf_counter()-begin,
                                                    error_type=type(exc).__name__,
                                                    error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
            result["source_unchanged"] = before == bindings()
            passed = (result["source_unchanged"] and len(result["controls"]) == len(CONTROLS)
                      and all(c["status"] == "PASS" for c in result["controls"].values()))
            result["status"] = PASS if passed else "FAIL"
        except Exception as exc:
            # Deliberately do not publish arbitrary exception paths or tracebacks.
            result.update(status="FAIL", error_type=type(exc).__name__)
            if isinstance(exc, (ValueError, RuntimeError)):
                result["error"] = str(exc).replace(str(ROOT), "TECTONICS_ROOT")
        result["elapsed_seconds_after_imports"] = time.perf_counter()-start
        try:
            text = json.dumps(result, indent=2, allow_nan=False)
        except (TypeError, ValueError) as exc:          # never leave a partial record behind
            result = dict(schema=result["schema"], status="FAIL", scientific_acceptance=False,
                          runtime=result["runtime"], error_type=type(exc).__name__,
                          error="evidence record not serialisable: "+str(exc)[:200], controls={},
                          elapsed_seconds_after_imports=result["elapsed_seconds_after_imports"])
            text = json.dumps(result, indent=2, allow_nan=False)
        stream.write(text+"\n")
    print(json.dumps({key: result.get(key) for key in ("status", "elapsed_seconds_after_imports", "error")}
                     | {"controls": {k: c["status"] for k, c in result["controls"].items()}}))
    return 0 if result["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
