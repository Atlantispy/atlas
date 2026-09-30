"""I01 physical breakup closure: force-balanced long-wave necking and its analytical pinch-off, WORKING NON-CANON.

A belt is a chain of material columns carrying one transmitted force; each column thins by its own pure shear and the
existing D1 drive/drag balance sets that force. Material connectivity would be lost when the thinnest column reaches
zero thickness after finite opening. For one fixed power law a = A(X) (F/2h)^n every column obeys
h^n = h0^n - A(X) Psi(t) for any force history (Hutchinson and Neale 1977), so the continuum opening at pinch-off is
exact: finite for a non-degenerate quadratic weakness minimum iff n > 2. This tool establishes only that analytical
continuum feasibility, for a constant 2 < n <= 4 inside the long-wave slope bound, and verifies the time-stepped chain
against the exact discrete chain at the first detection level. A resolved connectivity-loss certificate for a general
column law is not implemented and stays UNRESOLVED. n > 4 is refused from its asymptotics whatever the sampled slopes;
brittle, plastic-dominated and fixed-width necks are unsupported regimes owned by the resolved I07 neck. The retained
layered column is evaluated read-only at the accepted finite-strain initial state and classified. Decoupling,
separation and ocean birth remain separate records. No rupture threshold, prescribed event, world run, native code or
physical acceptance.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import functools
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.integrate import solve_ivp
from scipy.optimize import brentq
from scipy.special import hyp2f1
import threadpoolctl
from threadpoolctl import threadpool_limits

import check_i01_finite_strain as fs

tm, heat, motion, weakening = fs.tm, fs.heat, fs.motion, fs.weakening
column = weakening.column

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT/"cases/i01_breakup_closure_v1.json"
SCHEMA = "atlas.i01-breakup-closure-case.v1"
PASS = "PASS_BOUNDED_BREAKUP_CLOSURE_ONLY"
LAW = "atlas.necking-connectivity-breakup.v1"
EVENT = "atlas.connectivity-loss-event.v1"
FEASIBLE = "ANALYTICAL_CONTINUUM_PINCH_FEASIBLE"                   # never a resolved connectivity-loss event
NO_LIMIT = "NOT_ESTABLISHED_NO_FINITE_LIMIT"
OUTSIDE = "REFUSED_OUTSIDE_LONG_WAVE_VALIDITY"
UNSUPPORTED = "REFUSED_UNSUPPORTED_BASIS"
ILL_POSED = "REFUSED_ILL_POSED_RATE_INDEPENDENT"
UNRESOLVED = "UNRESOLVED"
POWER_LAW = "fixed_single_mechanism_power_law"
QUADRATIC = "non_degenerate_quadratic_minimum"
BASIS_FIELDS = {"law", "exponent", "profile", "thickness_m", "half_width_m", "weakness_length_m"}
CONSISTENT = "PREMISE_CONSISTENT_WITH_REDUCED_PINCH"
RESOLVED_NECK = "REFUSED_REQUIRES_RESOLVED_NECK"
EPS = float(np.finfo(float).eps)
TINY = float(np.finfo(float).tiny)
RECEIPT = "evidence/i01-finite-strain-r5.json"
FAULT_CASE = "cases/i01_fault2d_v1.json"
NEW_FILES = ("tools/check_i01_breakup_closure.py", "cases/i01_breakup_closure_v1.json",
             "docs/I01_BREAKUP_CLOSURE.md", "tests/test_i01_breakup_closure.py")
RETAINED = ("tools/check_i01_finite_strain.py", "tools/check_i01_thermomechanical_motion.py",
            "tools/check_i01_column_heat.py", "tools/check_i01_motion_coupling.py", "tools/check_i01_weakening.py",
            "tools/check_i01_column.py", "cases/i01_finite_strain_v1.json", "cases/i01_thermomechanical_motion_v1.json",
            "cases/i01_column_heat_v1.json", "cases/i01_motion_coupling_v1.json", "cases/i01_weakening_v1.json")
_PACKAGE_IMPORTS = {name: module for name, module in fs.IMPORTED.items() if name.startswith("src/")}
RETAINED += tuple(_PACKAGE_IMPORTS)
ACCEPTED_RECEIPTS = {RECEIPT: "d2a08846976b6ce5db1fac11e322cb8f6c37b1e4e42450b686949d3fa7970ce1"}
IMPORTED = {"tools/check_i01_finite_strain.py": fs, "tools/check_i01_thermomechanical_motion.py": tm,
            "tools/check_i01_column_heat.py": heat, "tools/check_i01_motion_coupling.py": motion,
            "tools/check_i01_weakening.py": weakening, "tools/check_i01_column.py": column}
IMPORTED.update(_PACKAGE_IMPORTS)
CASE_FIELDS = {"schema", "status", "task", "kind", "contract_document", "refines", "decision", "distinctions",
               "rejected_routes", "ports", "units", "control_policy", "control_parameters", "parameter_provenance",
               "acceptance_claim"}
# Frozen before any execution; cases/i01_breakup_closure_v1.json must equal both dictionaries exactly.
POLICY = {
    "maximum_seconds": 60.0,
    "gauss_orders": [192, 384],
    "quadrature_relative": 1e-10,
    "closed_form_relative": 1e-10,
    "derivative_relative": 1e-9,
    "decoupling_relative": 1e-9,
    "root_relative": 1e-14,
    "ode_rtol": 1e-12,
    "ode_atol": 1e-13,
    "ode_span_scaled": 100.0,
    "invariant_absolute": 1e-9,
    "chain_oracle_relative": 1e-8,
    "uniform_spread_relative": 1e-12,
    "uniform_relative": 1e-9,
    "accounts_relative": 1e-9,
    "force_variation_min": 2.0,
    "history_time_difference_min": 0.01,
    "ladder_window": 3,
    "ratio_max": 0.9,
    "ratio_spread": 0.02,
    "divergence_ratio": 0.99,
    "exponent_tolerance": 0.01,
    "tail_opening_relative": 1e-4,
    "tail_time_relative": 1e-3,
    "refinement_order_range": [1.8, 2.2],
    "refinement_finest_relative": 1e-4,
    "slope_bound": 0.25,
    "parity_relative": 1e-9,
    "mesh_ratio_relative": 1e-12,
    "scope": "long-wave necking chain under one transmitted force; exact power-law controls; analytical continuum "
             "pinch feasibility for a fixed power law with a non-degenerate quadratic minimum; no resolved "
             "connectivity-loss certificate; retained column classified read-only; not rupture, ocean birth or "
             "calibration",
}
PARAMETERS = {
    "chain": {"thickness_m": 100000.0, "half_width_m": 300000.0, "weakness_length_m": 600000.0,
              "drive_n_m": 2e13, "drag_pa_s": 5e22, "initial_belt_share": 0.5},
    "exponents": {"reference": 3.0, "second": 3.5, "subcritical": [1.0, 2.0], "outside_validity": 5.0},
    "ladder_levels": 12,
    "detection_fraction": 0.1,
    "chain_columns": [256, 1024],
    "uniform_columns": [1, 8],
    "refinement_columns": [256, 512, 1024, 2048],
    "prescribed_force": {"mean_share": 0.5, "relative_amplitude": 0.5, "period_scaled": 0.1},
    "plateau_fraction": 0.2,
    "fixed_neck_width_m": 5000.0,
    "slender_thickness_m": 1000.0,
    "rigid_plastic_columns": [64, 128, 256],
    "parallel_plastic": {"exponent": 3.0, "scaled_creep": 1e-4, "stress_multiples": [10.0, 100.0, 1000.0, 10000.0]},
    "decoupling_share": 0.01,
    "hypergeometric_deltas": [0.25, 0.5, 0.8],
    "retained": {"order": 64, "stretches": [1.0, 1.2, 1.4], "rate_multipliers": [1.0, 10.0, 100.0, 1000.0],
                 "plastic_share_max": 0.1, "creep_rate_sensitivity": [0.25, 0.5]},
}


# ----------------------------------------------------------------------------- small validated helpers

def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(name+" must be a real number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(name+" must be finite")
    return value


def positive(value, name):
    value = number(value, name)
    require(value > 0, name+" must be positive")
    return value


def fraction(value, name):
    value = number(value, name)
    require(0 < value < 1, name+" must lie in (0, 1)")
    return value


def exponent(value):
    n = number(value, "stress exponent")
    require(1 <= n <= 20, "stress exponent must lie in [1, 20]")
    return n


def integer(value, name, low=1, high=8192):
    require(type(value) is int and low <= value <= high, f"{name} must be an integer in {low}..{high}")
    return value


def relative(value, reference):
    return abs(value-reference)/max(abs(reference), TINY)


def max_relative(values, reference):
    values, reference = np.asarray(values, dtype=float), np.asarray(reference, dtype=float)
    return float(np.max(np.abs(values-reference)/np.maximum(np.abs(reference), TINY)))


def check_deadline(deadline):
    if deadline is not None and time.perf_counter() > deadline:
        raise RuntimeError("cooperative time budget exhausted; nothing further committed")


def finish(checks, **data):
    checks = {name: bool(value) for name, value in checks.items()}
    return dict(passed=all(checks.values()), checks=checks, **data)


@functools.lru_cache(maxsize=len(POLICY["gauss_orders"]))           # one entry per declared order
def gauss(order):
    """Gauss-Legendre nodes and weights on [-1, 1], prepared once per order and shared read-only.

    The retained helper backs them by immutable bytes: unlike a flag on an owning array, this cannot be made writeable.
    """
    integer(order, "Gauss-Legendre order", 8, 4096)
    nodes, weights = np.polynomial.legendre.leggauss(order)
    return weakening.frozen(nodes), weakening.frozen(weights)


# ----------------------------------------------------------------------------- the authored control belt

@dataclass(frozen=True)
class Chain:
    """Uniform thickness H, material half-width L, weakness alpha = 1 - (X/ell)^2 and the D1 drive and drag."""
    thickness_m: float
    half_width_m: float
    weakness_length_m: float
    drive_n_m: float
    drag_pa_s: float
    initial_belt_share: float

    def __post_init__(self):
        for name in ("thickness_m", "half_width_m", "weakness_length_m", "drive_n_m", "drag_pa_s"):
            object.__setattr__(self, name, positive(getattr(self, name), name))
        object.__setattr__(self, "initial_belt_share", fraction(self.initial_belt_share, "initial belt share"))
        require(self.half_width_m < self.weakness_length_m, "the weakness must stay positive across the belt: L < ell")

    @property
    def speed_limit(self):
        """Drag-only edge speed v_inf = F_drive/D [m/s]."""
        return self.drive_n_m/self.drag_pa_s

    def width_scale(self, uniform=False):
        """Lambda = integral alpha dX [m]; dU/dtheta at theta = 0 is Lambda/n. Uniform alpha = 1 gives 2 L."""
        L, ell = self.half_width_m, self.weakness_length_m
        return 2*L if uniform else 2*L*(1-L*L/(3*ell*ell))

    def g0(self, n):
        """Drag-to-belt ratio at theta = 0 that reproduces the declared initial belt share s0: (1 - s0)/s0^n."""
        s0 = self.initial_belt_share
        return (1-s0)/s0**exponent(n)


def share(g, n):
    """Belt share phi = F_belt/F_drive in (0, 1] solving phi + g phi^n = 1, for g >= 0 and n >= 1 (vectorised).

    f(phi) = phi + g phi^n - 1 is increasing and convex on phi > 0, so Newton from min(1, g^(-1/n)), which is never below
    the root, descends monotonically. The edge speed is v = v_inf (1 - phi).
    """
    n = exponent(n)
    g = np.asarray(g, dtype=float)
    require(bool(np.all(np.isfinite(g))) and bool(np.all(g >= 0)), "drag-to-belt ratio g must be finite and >= 0")
    phi = np.where(g > 0, np.minimum(1.0, np.where(g > 0, g, 1.0)**(-1.0/n)), 1.0)
    for _ in range(100):
        step = (phi+g*phi**n-1.0)/(1.0+n*g*phi**(n-1.0))
        phi = phi-step
        if np.all(np.abs(step) <= 4*EPS*phi):
            return phi
    raise ValueError("belt-share root did not converge")


def share1(g, n):
    """Scalar form of share() for the chain right-hand side; n must already be a validated exponent."""
    require(math.isfinite(g) and g >= 0, "drag-to-belt ratio g must be finite and >= 0")
    phi = 1.0 if g == 0 else min(1.0, g**(-1.0/n))
    for _ in range(100):
        step = (phi+g*phi**n-1.0)/(1.0+n*g*phi**(n-1.0))
        phi -= step
        if abs(step) <= 4*EPS*phi:
            return phi
    raise ValueError("belt-share root did not converge")


# ----------------------------------------------------------------------------- the continuum chain (exact invariant)

def profile(delta, n, half_width, length, order):
    """Opening U [m] and dU/dtheta [m] of the continuum chain, alpha = 1 - (X/length)^2 on [-half_width, half_width].

    lambda = (1 - theta alpha)^(-1/n) with delta = 1 - theta in (0, 1]. X = w sinh(s), w = length sqrt(delta/theta),
    turns 1 - theta alpha into delta cosh(s)^2, so one Gauss-Legendre rule on [0, asinh(half_width/w)] resolves the neck
    (width w) and the flanks together. theta = 0 is exact: U = 0 and dU/dtheta = (2 L/n)(1 - L^2/(3 ell^2)).
    """
    p = 1.0/exponent(n)
    L, ell = positive(half_width, "half-width"), positive(length, "weakness length")
    require(L < ell, "the weakness must stay positive across the belt: L < ell")
    d = np.atleast_1d(np.asarray(delta, dtype=float))
    require(d.ndim == 1 and bool(np.all(np.isfinite(d) & (d > 0) & (d <= 1))), "delta = 1 - theta must lie in (0, 1]")
    theta = 1.0-d
    opening = np.zeros(d.shape)
    rate = np.full(d.shape, 2*p*L*(1-L*L/(3*ell*ell)))
    live = theta > 0
    if np.any(live):
        dl, th = d[live], theta[live]
        w = ell*np.sqrt(dl/th)
        top = np.arcsinh(L/w)
        nodes, weights = gauss(order)
        s = top[:, None]*(nodes[None, :]+1)/2
        ws = top[:, None]/2*weights[None, :]
        c = np.cosh(s)
        j0 = np.sum(ws*c**(1-2*p), axis=1)
        j1 = np.sum(ws*(1-(dl/th)[:, None]*np.sinh(s)**2)*c**(-2*p-1), axis=1)
        opening[live] = 2*(w*dl**(-p)*j0-L)
        rate[live] = 2*p*w*dl**(-p-1)*j1
    return opening, rate


def hypergeometric_profile(delta, n, half_width, length):
    """Independent closed form for |z| < 1: integral_0^L (delta + b X^2)^-q dX = L delta^-q 2F1(q, 1/2; 3/2; z) and
    integral_0^L X^2 (delta + b X^2)^-q dX = (L^3/3) delta^-q 2F1(q, 3/2; 5/2; z), b = theta/ell^2, z = -b L^2/delta."""
    p = 1.0/exponent(n)
    L, ell = positive(half_width, "half-width"), positive(length, "weakness length")
    d = number(delta, "delta")
    require(0 < d < 1, "delta must lie in (0, 1)")
    z = -(1.0-d)*L*L/(ell*ell*d)
    require(abs(z) < 1, "the hypergeometric check is restricted to |z| < 1")
    i0 = L*d**(-p)*hyp2f1(p, 0.5, 1.5, z)
    i1 = L*d**(-p-1)*hyp2f1(p+1, 0.5, 1.5, z)
    i2 = L**3/3*d**(-p-1)*hyp2f1(p+1, 1.5, 2.5, z)
    return float(2*(i0-L)), float(2*p*(i1-i2/(ell*ell)))


def closed_opening(delta, n, half_width, length):
    """Exact openings for n = 1 (arctan) and n = 2 (asinh) at any delta in (0, 1)."""
    L, ell = positive(half_width, "half-width"), positive(length, "weakness length")
    d = np.atleast_1d(np.asarray(delta, dtype=float))
    require(bool(np.all(np.isfinite(d) & (d > 0) & (d < 1))), "delta must lie in (0, 1)")
    b = (1.0-d)/(ell*ell)
    r = L*np.sqrt(b/d)
    if exponent(n) == 1.0:
        inner = np.arctan(r)/np.sqrt(b*d)
    elif n == 2.0:
        inner = np.arcsinh(r)/np.sqrt(b)
    else:
        raise ValueError("closed forms are used here only for n = 1 and n = 2")
    return 2*(inner-L)


def opening_limit(n, half_width, length):
    """Opening at pinch-off (theta -> 1): 2 [ell^(2/n) L^(1-2/n)/(1-2/n) - L]; None when it diverges (n <= 2)."""
    p = 1.0/exponent(n)
    L, ell = positive(half_width, "half-width"), positive(length, "weakness length")
    if 2*p >= 1:
        return None
    return 2*(ell**(2*p)*L**(1-2*p)/(1-2*p)-L)


def max_slope(delta, n, thickness, half_width, length):
    """Largest |dh/dx| (current coordinates) of the parabolic neck: 2 H p sqrt(theta)/ell max_s s (delta + s^2)^(2p-1)."""
    p = 1.0/exponent(n)
    d = np.asarray(delta, dtype=float)
    theta = 1.0-d
    edge = np.sqrt(theta)*positive(half_width, "half-width")/positive(length, "weakness length")
    s = edge if p >= 0.25 else np.minimum(edge, np.sqrt(d/(1-4*p)))
    return 2*positive(thickness, "thickness")*p*np.sqrt(theta)/length*s*(d+s*s)**(2*p-1)


def clock_time(delta_end, n, chain, order):
    """D1 time [s] until delta = delta_end: (1/v_inf) integral_(delta_end)^1 U'/(1 - phi) d delta with delta = e^-y."""
    n = exponent(n)
    d_end = number(delta_end, "delta")
    require(0 < d_end < 1, "delta must lie in (0, 1)")
    y_end = -math.log(d_end)
    nodes, weights = gauss(order)
    y = y_end*(nodes+1)/2
    d = np.exp(-y)
    _, du = profile(d, n, chain.half_width_m, chain.weakness_length_m, order)
    phi = share(chain.g0(n)*du/(chain.width_scale()/n), n)
    return float(np.sum(y_end/2*weights*du*d/(1-phi)))/chain.speed_limit


def pinch_time(n, chain, order):
    """D1 time [s] to pinch-off for n > 2: delta = (1 - u)^(2/kappa), kappa = 1/2 - 1/n, u in (0, 1).

    U' delta falls like delta^kappa, so the integrand in u vanishes linearly at u = 1 and the rule converges fast.
    """
    n = exponent(n)
    kappa = 0.5-1.0/n
    require(kappa > 0, "pinch-off time is finite only for n > 2")
    nodes, weights = gauss(order)
    u = (nodes+1)/2
    d = (1-u)**(2/kappa)
    _, du = profile(d, n, chain.half_width_m, chain.weakness_length_m, order)
    phi = share(chain.g0(n)*du/(chain.width_scale()/n), n)
    return float(np.sum(weights/2*du*d/(1-phi)*2/(kappa*(1-u))))/chain.speed_limit


def integrated_opening(delta_end, n, half_width, length, order):
    """integral_(delta_end)^1 dU/dtheta d delta (= U(delta_end)); an independent check of the derivative."""
    y_end = -math.log(number(delta_end, "delta"))
    nodes, weights = gauss(order)
    y = y_end*(nodes+1)/2
    d = np.exp(-y)
    _, du = profile(d, n, half_width, length, order)
    return float(np.sum(y_end/2*weights*du*d))


def decoupling(n, chain, share_limit, order):
    """First state with belt share phi = share_limit; phi decreases with theta, so decoupling is then permanent."""
    n = exponent(n)
    eps = fraction(share_limit, "decoupling share")
    require(eps < chain.initial_belt_share, "decoupling share must lie below the initial belt share")
    L, ell = chain.half_width_m, chain.weakness_length_m
    target = (chain.width_scale()/n)*(1-eps)/(chain.g0(n)*eps**n)

    def gap(y):
        return math.log(float(profile(math.exp(-y), n, L, ell, order)[1][0]))-math.log(target)
    y = brentq(gap, 0.0, 100.0, xtol=1e-12, rtol=4*EPS, maxiter=200)
    d = math.exp(-y)
    opening, du = profile(d, n, L, ell, order)
    phi = float(share(chain.g0(n)*du/(chain.width_scale()/n), n)[0])
    return dict(delta=d, thinnest_fraction=d**(1/n), opening_m=float(opening[0]),
                time_s=clock_time(d, n, chain, order), share=phi, share_relative=relative(phi, eps))


# ----------------------------------------------------------------------------- ladder verdict and feasibility

def ladder_verdict(values, policy):
    """Increment ratios on a halving detection ladder: a consistent geometric tail, divergence, or unresolved."""
    v = np.asarray(values, dtype=float)
    window = policy["ladder_window"]
    require(v.ndim == 1 and v.size >= window+2, "detection ladder too short for the declared window")
    if not np.all(np.isfinite(v)):
        return dict(verdict=UNRESOLVED, reason="nonfinite ladder value", ratios=[])
    increments = np.diff(v)
    if np.any(increments <= 0):
        return dict(verdict=UNRESOLVED, reason="ladder values are not strictly increasing", ratios=[])
    ratios = increments[1:]/increments[:-1]
    last = ratios[-window:]
    out = dict(ratios=ratios.tolist(), last_ratios=last.tolist())
    if last.max() <= policy["ratio_max"] and last.max()-last.min() <= policy["ratio_spread"]:
        r = float(last[-1])
        tail = float(increments[-1]*r/(1-r))
        return dict(out, verdict="FINITE_LIMIT", exponent=-math.log2(r), limit=float(v[-1])+tail, remaining=tail)
    if last.min() >= policy["divergence_ratio"]:
        return dict(out, verdict="NO_FINITE_LIMIT")
    return dict(out, verdict=UNRESOLVED, reason="increment ratios neither consistently geometric nor divergent")


def power_law_basis(n, thickness, half_width, length):
    """The one basis analytical feasibility accepts: a = A_max alpha(X) (F/2h)^n with a single constant n, uniform
    thickness H and alpha = 1 - (X/ell)^2, whose minimum is non-degenerate (q = 2). Validated by basis_refusal."""
    return dict(law=POWER_LAW, exponent=n, profile=QUADRATIC, thickness_m=thickness, half_width_m=half_width,
                weakness_length_m=length)


def basis_refusal(basis):
    """None for the supported basis, else why it is refused. An exponent inferred at one finite state, a smooth but
    degenerate minimum (a quartic has q = 4) or any other law or profile is not the declared power-law basis."""
    if type(basis) is not dict or set(basis) != BASIS_FIELDS:
        return "an explicit analytical basis with exactly the declared fields is required"
    if basis["law"] != POWER_LAW:
        return "only a fixed single-mechanism power law with one constant exponent is supported"
    if basis["profile"] != QUADRATIC:
        return "only a non-degenerate quadratic weakness minimum (q = 2) is supported"
    try:
        exponent(basis["exponent"])
        positive(basis["thickness_m"], "thickness")
        L, ell = positive(basis["half_width_m"], "half-width"), positive(basis["weakness_length_m"], "weakness length")
        require(L < ell, "the weakness must stay positive across the belt: L < ell")
    except ValueError as exc:
        return str(exc)
    return None


def feasibility(openings, times, slopes, basis, policy):
    """Analytical continuum pinch feasibility of the declared basis; never a resolved connectivity-loss event.

    Malformed ladders raise. n > 4 is refused whatever the sampled slopes: the neck-tip slope grows as
    (H/ell)(h/H)^((4-n)/2), so a slender enough belt would pass any finite ladder. For 2 <= n <= 4 the largest slope
    rises monotonically to its theta -> 1 limit, which must also lie inside the bound. FEASIBLE needs 2 < n <= 4, finite
    opening and time limits, the opening exponent n/2 - 1 and the closed-form U*; n <= 2 gives NO_LIMIT only when both
    ladders diverge. Anything that disagrees with the exact solution of the declared basis is UNRESOLVED.
    """
    u, t, s = (np.asarray(v, dtype=float) for v in (openings, times, slopes))
    require(u.ndim == 1 and u.shape == t.shape == s.shape and u.size >= policy["ladder_window"]+2,
            "opening, time and slope ladders must be one-dimensional with one value per rung")
    require(bool(np.all(np.isfinite(u))) and bool(np.all(np.isfinite(t))) and bool(np.all(np.isfinite(s))),
            "ladder and slope values must be finite")
    require(bool(np.all(u > 0)) and bool(np.all(t > 0)) and bool(np.all(s >= 0)),
            "openings and times must be positive and slopes non-negative")
    record = dict(resolved_event=UNRESOLVED)
    reason = basis_refusal(basis)
    if reason is not None:
        return dict(record, status=UNSUPPORTED, reason=reason)
    n, H, L, ell = (float(basis[key]) for key in ("exponent", "thickness_m", "half_width_m", "weakness_length_m"))
    outside = np.flatnonzero(s > policy["slope_bound"])
    record.update(basis=dict(basis), expected_exponent=n/2-1, opening_limit_m=opening_limit(n, L, ell),
                  opening=ladder_verdict(u, policy), time=ladder_verdict(t, policy), max_slope=float(np.max(s)),
                  first_level_outside=int(outside[0])+1 if outside.size else None,
                  slope_limit=float(max_slope(0.0, n, H, L, ell)) if 2 <= n <= 4 else None)
    if n > 4:
        return dict(record, status=OUTSIDE, reason="n > 4: the neck-tip slope grows as (H/ell)(h/H)^((4-n)/2) "
                                                   "without bound, whatever the sampled slopes")
    if outside.size or (record["slope_limit"] is not None and record["slope_limit"] > policy["slope_bound"]):
        return dict(record, status=OUTSIDE, reason="a sampled or limiting neck slope exceeds the long-wave bound")
    verdicts = (record["opening"]["verdict"], record["time"]["verdict"])
    if n <= 2:
        if verdicts == ("NO_FINITE_LIMIT", "NO_FINITE_LIMIT"):
            return dict(record, status=NO_LIMIT, reason="n <= q = 2: the exact opening at pinch-off diverges")
        return dict(record, status=UNRESOLVED, reason="the ladders disagree with the divergent exact solution")
    if (verdicts == ("FINITE_LIMIT", "FINITE_LIMIT")
            and abs(record["opening"]["exponent"]-record["expected_exponent"]) <= policy["exponent_tolerance"]
            and relative(record["opening"]["limit"], record["opening_limit_m"]) <= policy["tail_opening_relative"]):
        return dict(record, status=FEASIBLE, reason="the exact continuum solution pinches off at finite opening and "
                                                    "time; no resolved event is certified")
    return dict(record, status=UNRESOLVED, reason="the ladders disagree with the finite exact solution")


# ----------------------------------------------------------------------------- the discrete chain

def columns(size, half_width, length, kind="parabolic", plateau=0.0):
    """Midpoint material columns: X_i, q_i = 1 - alpha_i, alpha_i and the common material width dX."""
    size = integer(size, "column count")
    L, ell = positive(half_width, "half-width"), positive(length, "weakness length")
    require(L < ell, "the weakness must stay positive across the belt: L < ell")
    dx = 2*L/size
    x = -L+(np.arange(size)+0.5)*dx
    if kind == "parabolic":
        q = (x/ell)**2
    elif kind == "uniform":
        q = np.zeros(size)
    elif kind == "plateau":
        b = number(plateau, "plateau half-width")
        require(0 < b < L, "plateau half-width must lie in (0, L)")
        q = (np.maximum(np.abs(x)-b, 0.0)/ell)**2
    else:
        raise ValueError("unknown weakness profile")
    return x, q, 1.0-q, dx


def discrete_oracle(q, alpha, dx, n, g0, width_scale, h_fraction, order):
    """Exact per-column solution of the discrete chain at detection: opening [m] and tau = t v_inf/width_scale.

    With z the log-thinning of the thinnest column, 1 - theta alpha_i = ((q_i - q_min) + alpha_i e^-z)/alpha_max, so no
    difference of nearly equal numbers is formed; the D1 clock is integrated in z by Gauss-Legendre.
    """
    n = exponent(n)
    p = 1.0/n
    q, alpha = np.asarray(q, dtype=float), np.asarray(alpha, dtype=float)
    hf = fraction(h_fraction, "detection fraction")
    amax, qmin = float(alpha.max()), float(q.min())
    z_end = -n*math.log(hf)
    nodes, weights = gauss(order)
    z = z_end*(nodes+1)/2
    ez = np.exp(-z)
    base = ((q-qmin)[None, :]+alpha[None, :]*ez[:, None])/amax
    du = p*dx*np.sum(alpha[None, :]*base**(-p-1), axis=1)
    phi = share(g0*du/(p*width_scale), n)
    tau = float(np.sum(z_end/2*weights*(du/width_scale)*(ez/amax)/(1-phi)))
    end = ((q-qmin)+alpha*hf**n)/amax
    return float(dx*np.sum(end**(-p)-1)), tau


def run_chain(q, alpha, dx, n, g0, width_scale, h_fraction, policy, *, prescribed=None, deadline=None):
    """Time-stepped necking chain in tau = t v_inf/width_scale until the thinnest column reaches h_fraction of H.

    State: ln(lambda_i), the clock theta, scaled edge displacement and scaled drive, drag and belt work. Every stage
    solves the D1 root phi + g phi^n = 1 with g = g0 sum(dX alpha lambda^(n+1))/width_scale; the rates are
    dln(lambda_i)/dtau = g0 alpha_i phi^n lambda_i^n. With ``prescribed`` the share phi(tau) is supplied (load-history
    control) and no drive balance is booked. The invariant lambda^-n = 1 - theta alpha is never used to integrate.
    """
    check_deadline(deadline)
    n = exponent(n)
    q, alpha = np.asarray(q, dtype=float), np.asarray(alpha, dtype=float)
    size = alpha.size
    require(size >= 1 and q.shape == alpha.shape == (size,), "one q and one alpha per column")
    require(bool(np.all((alpha > 0) & (alpha <= 1))) and bool(np.all(np.abs(1-q-alpha) <= 4*EPS)),
            "alpha must equal 1 - q and lie in (0, 1]")
    dx, width_scale, g0 = positive(dx, "column width"), positive(width_scale, "width scale"), positive(g0, "g0")
    hf = fraction(h_fraction, "detection fraction")
    weight = dx/width_scale
    wa = weight*alpha
    target = -math.log(hf)

    def belt_share(tau, lam):
        if prescribed is None:
            return share1(g0*float(np.dot(wa, lam**(n+1))), n)
        phi = float(prescribed(tau))
        require(0 < phi <= 1, "prescribed belt share must lie in (0, 1]")
        return phi

    def rhs(tau, y):
        check_deadline(deadline)                    # inside the solve, so a slow integration stops at the budget
        lam = np.exp(y[:size])
        phi = belt_share(tau, lam)
        rate = g0*phi**n*alpha*lam**n
        speed = float(weight*np.sum(lam*rate))
        out = np.empty(size+5)
        out[:size] = rate
        out[size] = n*g0*phi**n
        out[size+1] = speed
        out[size+2] = speed
        out[size+3] = speed*speed
        out[size+4] = phi*speed
        return out

    def thinnest(tau, y):
        return float(np.max(y[:size]))-target
    thinnest.terminal, thinnest.direction = True, 1
    sol = solve_ivp(rhs, (0.0, policy["ode_span_scaled"]), np.zeros(size+5), method="DOP853",
                    rtol=policy["ode_rtol"], atol=policy["ode_atol"], events=thinnest)
    check_deadline(deadline)
    require(sol.status == 1 and len(sol.t_events[0]) == 1, "the detection thickness was not reached inside the span")
    tau = float(sol.t_events[0][0])
    y = np.asarray(sol.y_events[0][0], dtype=float)
    lam = np.exp(y[:size])
    theta = float(y[size])
    opening = float(dx*np.sum(lam-1))
    edge = float(y[size+1])*width_scale
    top = float(np.max(y[:size]))
    out = dict(tau=tau, opening_m=opening, clock_theta=theta,
               invariant_residual=float(np.max(np.abs(lam**(-n)-((1-theta)+theta*q)))),
               edge_m=edge, kinematic_relative=relative(edge, opening), thinnest_fraction=float(math.exp(-top)),
               share_start=belt_share(0.0, np.ones(size)), share_end=belt_share(tau, lam),
               column_spread_relative=(top-float(np.min(y[:size])))/max(top, EPS),
               steps=int(sol.t.size), evaluations=int(sol.nfev))
    if prescribed is None:
        drive, drag, belt = (float(v) for v in y[size+2:size+5])
        g_end = g0*float(np.dot(wa, lam**(n+1)))
        phi_end = out["share_end"]
        out.update(work_scaled=dict(drive=drive, drag=drag, belt=belt), work_relative=abs(drive-drag-belt)/drive,
                   root_residual=abs(phi_end+g_end*phi_end**n-1))
    return out


def affine_time(n, g0, h_fraction, order):
    """Scaled time of the uniform (affine) belt: tau = integral_1^(H/h) d lambda/(1 - phi(g0 lambda^(n+1)))."""
    n = exponent(n)
    top = 1/fraction(h_fraction, "detection fraction")
    nodes, weights = gauss(order)
    lam = 1+(top-1)*(nodes+1)/2
    phi = share(positive(g0, "g0")*lam**(n+1), n)
    return float(np.sum((top-1)/2*weights/(1-phi)))


def rigid_plastic_opening(size, chain, h_fraction):
    """Rate-independent long-wave chain: once the weakest material set yields, thinning lowers its yield force and every
    other column unloads, so that set takes all extension; its opening at detection is |set| dX (H/h - 1)."""
    _, _, alpha, dx = columns(size, chain.half_width_m, chain.weakness_length_m)
    strength = 2*chain.thickness_m*(2-alpha)            # yield force per column, Y_i = Y0 (2 - alpha_i) with Y0 = 1
    weakest = np.flatnonzero(np.isclose(strength, strength.min(), rtol=1e-12, atol=0.0))
    return dict(columns=size, weakest_columns=int(weakest.size),
                opening_m=float(weakest.size*dx*(1/fraction(h_fraction, "detection fraction")-1)))


def parallel_plastic(sigma, n, k):
    """Scaled retained point law r = k sigma^n + max(sigma - 1, 0), evaluated above yield.

    Stress is in units of the yield stress Y, rate in units of Y/(2 eta) and k = 2 eta A Y^(n-1): creep and regularised
    plastic rates add at one stress, as in the retained kernel. Returns the rate, the plastic share of the dissipation
    and the local exponent d ln r/d ln sigma. For n > 1 the share falls as sigma^(1-n)/k and the exponent tends to n.
    """
    n, k = exponent(n), positive(k, "scaled creep coefficient")
    s = np.asarray(sigma, dtype=float)
    require(s.ndim == 1 and bool(np.all(np.isfinite(s) & (s > 1))), "stress multiples must be finite and above yield")
    creep, plastic = k*s**n, s-1.0
    rate = creep+plastic
    return dict(rate=rate, plastic_share=plastic/rate, local_exponent=(n*creep+s)/rate)


def parallel_kernel(sigma, n, k):
    """The same scaled law through the retained point kernel, with yield 1 Pa and plastic viscosity 1/2 Pa s."""
    point = parallel_plastic(sigma, n, k)
    law = column.LocalLaw((math.log(k),), (float(n),), 1.0, 0.5)
    out = [law.solve(float(rate)) for rate in point["rate"]]
    return dict(stress=np.array([o["stress_pa"] for o in out]),
                plastic_share=np.array([o["plastic_rate_s"] for o in out])/point["rate"])


def regime_reasons(plastic_share, rate_sensitivity, retained):
    """Frozen classification rule for one sampled state; an empty list means no reduced-route premise fails there.

    It is a regime diagnostic at that state only: it neither grants feasibility nor excludes a later pinch-off.
    """
    low, high = retained["creep_rate_sensitivity"]
    reasons = []
    if plastic_share > retained["plastic_share_max"]:
        reasons.append("frictional-plastic or regularised-plastic dissipation exceeds the declared share")
    if not low <= rate_sensitivity < high:
        reasons.append(f"rate sensitivity leaves the creep window [{low:g}, {high:g})")
    return reasons


# ----------------------------------------------------------------------------- controls

def continuum_ladder(n, chain, par, pol, deadline=None):
    """Openings, D1 times, neck slopes and belt shares at h_k = H 2^-k, each by a coarse and a fine rule."""
    n = exponent(n)
    levels = np.arange(1, integer(par["ladder_levels"], "ladder levels", 3, 30)+1)
    delta = 2.0**(-levels*n)
    coarse, fine = pol["gauss_orders"]
    L, ell = chain.half_width_m, chain.weakness_length_m
    u_fine, du_fine = profile(delta, n, L, ell, fine)
    u_coarse, du_coarse = profile(delta, n, L, ell, coarse)
    t_fine, t_coarse = [], []
    for d in delta:
        check_deadline(deadline)
        t_fine.append(clock_time(float(d), n, chain, fine))
        t_coarse.append(clock_time(float(d), n, chain, coarse))
    t_fine = np.array(t_fine)
    return dict(levels=levels, delta=delta, opening=u_fine, rate=du_fine, time=t_fine,
                quadrature=max(max_relative(u_coarse, u_fine), max_relative(du_coarse, du_fine),
                               max_relative(t_coarse, t_fine)),
                slope=max_slope(delta, n, chain.thickness_m, L, ell),
                share=share(chain.g0(n)*du_fine/(chain.width_scale()/n), n))


def pinch_case(n, chain, par, pol, deadline=None):
    """One exponent of the analytical window: ladder, independent checks, closed-form limit, pinch time and status.

    The rung neck scale w = ell (delta/theta)^(1/2) is the material half-width over which 1 - theta alpha doubles.
    """
    L, ell = chain.half_width_m, chain.weakness_length_m
    coarse, fine = pol["gauss_orders"]
    lad = continuum_ladder(n, chain, par, pol, deadline)
    limit = opening_limit(n, L, ell)
    t_star, t_star_coarse = pinch_time(n, chain, fine), pinch_time(n, chain, coarse)
    hyper = []
    for d in par["hypergeometric_deltas"]:
        u, du = profile(d, n, L, ell, fine)
        uh, duh = hypergeometric_profile(d, n, L, ell)
        hyper.append(max(relative(float(u[0]), uh), relative(float(du[0]), duh)))
    picks = (0, lad["delta"].size//2, lad["delta"].size-1)
    derivative = [relative(integrated_opening(float(lad["delta"][k]), n, L, ell, fine), float(lad["opening"][k]))
                  for k in picks]
    status = feasibility(lad["opening"], lad["time"], lad["slope"], power_law_basis(n, chain.thickness_m, L, ell), pol)
    opening_gap = None if limit is None else limit-lad["opening"]
    time_gap = t_star-lad["time"]
    return dict(exponent=n, levels=lad["levels"], thinnest_fraction=2.0**(-lad["levels"].astype(float)),
                opening_m=lad["opening"], time_s=lad["time"], max_slope=lad["slope"], belt_share=lad["share"],
                neck_material_scale_m=ell*np.sqrt(lad["delta"]/(1-lad["delta"])),
                quadrature_relative=max(lad["quadrature"], relative(t_star_coarse, t_star)),
                hypergeometric_relative=hyper, derivative_relative=derivative, opening_limit_m=limit,
                pinch_time_s=t_star, feasibility=status, opening_gap_m=opening_gap, time_gap_s=time_gap)


def refinement(n, chain, par, pol, deadline=None):
    """Exact discrete chains of 256..2048 columns against the continuum at the first detection level only; the deeper
    rungs are not resolved by these columns, so this is not a per-rung event certificate."""
    fine = pol["gauss_orders"][1]
    hf = fraction(par["detection_fraction"], "detection fraction")
    L, ell = chain.half_width_m, chain.weakness_length_m
    d_ref = hf**n
    u_ref = float(profile(d_ref, n, L, ell, fine)[0][0])
    t_ref = clock_time(d_ref, n, chain, fine)
    rows = []
    for size in par["refinement_columns"]:
        check_deadline(deadline)
        _, q, alpha, dx = columns(size, L, ell)
        u, tau = discrete_oracle(q, alpha, dx, n, chain.g0(n), chain.width_scale(), hf, fine)
        t = tau*chain.width_scale()/chain.speed_limit
        rows.append(dict(columns=size, opening_m=u, time_s=t, opening_error=relative(u, u_ref),
                         time_error=relative(t, t_ref)))
    orders = dict(opening=[math.log2(a["opening_error"]/b["opening_error"]) for a, b in zip(rows, rows[1:])],
                  time=[math.log2(a["time_error"]/b["time_error"]) for a, b in zip(rows, rows[1:])])
    return dict(detection_fraction=hf, continuum_opening_m=u_ref, continuum_time_s=t_ref, rows=rows, orders=orders,
                scope="lateral convergence at the first detection level only")


def invariant_control(spec, deadline=None):
    """Implementation and event detection, not physics: the time-stepped chain against its exact discrete solution."""
    check_deadline(deadline)
    pol, par = spec["control_policy"], spec["control_parameters"]
    chain = Chain(**par["chain"])
    n = exponent(par["exponents"]["reference"])
    L, ell = chain.half_width_m, chain.weakness_length_m
    g0, scale, fine = chain.g0(n), chain.width_scale(), pol["gauss_orders"][1]
    hf = fraction(par["detection_fraction"], "detection fraction")
    runs = {}
    for size in par["chain_columns"]:
        _, q, alpha, dx = columns(size, L, ell)
        run = run_chain(q, alpha, dx, n, g0, scale, hf, pol, deadline=deadline)
        opening, tau = discrete_oracle(q, alpha, dx, n, g0, scale, hf, fine)
        runs[size] = dict(run, oracle_opening_m=opening, oracle_tau=tau, time_s=run["tau"]*scale/chain.speed_limit,
                          opening_relative=relative(run["opening_m"], opening), time_relative=relative(run["tau"], tau))
    first = par["chain_columns"][0]
    _, q, alpha, dx = columns(first, L, ell)
    pf = par["prescribed_force"]
    mean, amplitude = fraction(pf["mean_share"], "mean share"), number(pf["relative_amplitude"], "relative amplitude")
    period = positive(pf["period_scaled"], "period")
    require(0 <= amplitude < 1 and mean*(1+amplitude) <= 1, "the prescribed share must stay inside (0, 1]")
    loaded = run_chain(q, alpha, dx, n, g0, scale, hf, pol, deadline=deadline,
                       prescribed=lambda tau: mean*(1+amplitude*math.sin(2*math.pi*tau/period)))
    uniform = {}
    for size in par["uniform_columns"]:
        _, uq, ualpha, udx = columns(size, L, ell, "uniform")
        uniform[size] = run_chain(uq, ualpha, udx, n, g0, chain.width_scale(uniform=True), hf, pol, deadline=deadline)
    affine_tau, affine_opening = affine_time(n, g0, hf, fine), 2*L*(1/hf-1)
    reference = runs[first]
    few, many = par["uniform_columns"][0], par["uniform_columns"][-1]
    every = list(runs.values())+[loaded]+list(uniform.values())
    checks = dict(
        invariant_holds=max(r["invariant_residual"] for r in every) <= pol["invariant_absolute"],
        detected_at_declared_thickness=all(relative(r["thinnest_fraction"], hf) <= pol["chain_oracle_relative"]
                                           for r in every),
        chain_matches_exact_discrete_opening=all(r["opening_relative"] <= pol["chain_oracle_relative"]
                                                 for r in runs.values()),
        chain_matches_exact_discrete_time=all(r["time_relative"] <= pol["chain_oracle_relative"] for r in runs.values()),
        kinematic_closure=all(r["kinematic_relative"] <= pol["accounts_relative"] for r in runs.values()),
        drive_equals_drag_plus_belt=all(r["work_relative"] <= pol["accounts_relative"] for r in runs.values()),
        force_root_closes=all(r["root_residual"] <= pol["root_relative"] for r in runs.values()),
        force_history_nontrivial=all(r["share_start"]/r["share_end"] >= pol["force_variation_min"]
                                     for r in runs.values()),
        opening_independent_of_force_history=relative(loaded["opening_m"], reference["opening_m"])
        <= pol["chain_oracle_relative"],
        time_depends_on_force_history=relative(loaded["tau"], reference["tau"]) >= pol["history_time_difference_min"],
        uniform_columns_identical=all(r["column_spread_relative"] <= pol["uniform_spread_relative"]
                                      for r in uniform.values()),
        uniform_is_affine_opening=all(relative(r["opening_m"], affine_opening) <= pol["uniform_relative"]
                                      for r in uniform.values()),
        uniform_is_affine_time=all(relative(r["tau"], affine_tau) <= pol["uniform_relative"] for r in uniform.values()),
        uniform_independent_of_column_count=relative(uniform[many]["tau"], uniform[few]["tau"]) <= pol["uniform_relative"])
    return finish(checks, exponent=n, detection_fraction=hf, time_scale_s=scale/chain.speed_limit,
                  chains={str(k): v for k, v in runs.items()}, prescribed_history=loaded,
                  uniform={str(k): v for k, v in uniform.items()}, affine=dict(opening_m=affine_opening, tau=affine_tau),
                  scope="tests the integration, force root, clock and event location against exact discrete solutions "
                        "at the first detection level; it neither shows that separation is predicted nor resolves "
                        "deeper rungs")


def pinch_control(spec, deadline=None):
    """Is pinch-off at finite opening and time analytically feasible for the declared power law? Not an event."""
    check_deadline(deadline)
    pol, par = spec["control_policy"], spec["control_parameters"]
    chain = Chain(**par["chain"])
    exps = par["exponents"]
    cases = {}
    for key in ("reference", "second"):
        cases[key] = pinch_case(exponent(exps[key]), chain, par, pol, deadline)
    n = exponent(exps["reference"])
    refined = refinement(n, chain, par, pol, deadline)
    dec = decoupling(n, chain, par["decoupling_share"], pol["gauss_orders"][1])
    ref = cases["reference"]
    lo, hi = pol["refinement_order_range"]
    checks = {}
    for key, case in cases.items():
        status, limit = case["feasibility"], case["opening_limit_m"]
        opening, timing = status.get("opening", {}), status.get("time", {})
        checks[key+"_quadrature_self_consistent"] = case["quadrature_relative"] <= pol["quadrature_relative"]
        checks[key+"_independent_hypergeometric"] = max(case["hypergeometric_relative"]) <= pol["closed_form_relative"]
        checks[key+"_derivative_identity"] = max(case["derivative_relative"]) <= pol["derivative_relative"]
        checks[key+"_finite_closed_form_limit"] = limit is not None and limit > 0
        checks[key+"_analytically_feasible"] = status["status"] == FEASIBLE
        checks[key+"_opening_tail_recovers_limit"] = (limit is not None and opening.get("verdict") == "FINITE_LIMIT"
                                                      and relative(opening["limit"], limit)
                                                      <= pol["tail_opening_relative"])
        checks[key+"_time_tail_recovers_limit"] = (timing.get("verdict") == "FINITE_LIMIT"
                                                   and relative(timing["limit"], case["pinch_time_s"])
                                                   <= pol["tail_time_relative"])
        checks[key+"_gaps_shrink"] = (case["opening_gap_m"] is not None and bool(np.all(case["opening_gap_m"] > 0))
                                      and bool(np.all(np.diff(case["opening_gap_m"]) < 0))
                                      and bool(np.all(case["time_gap_s"] > 0)) and bool(np.all(np.diff(case["time_gap_s"]) < 0)))
        checks[key+"_belt_share_decreases"] = bool(np.all(np.diff(case["belt_share"]) < 0))
    checks["refinement_opening_order"] = all(lo <= v <= hi for v in refined["orders"]["opening"])
    checks["refinement_time_order"] = all(lo <= v <= hi for v in refined["orders"]["time"])
    checks["refinement_finest"] = max(refined["rows"][-1]["opening_error"], refined["rows"][-1]["time_error"]) \
        <= pol["refinement_finest_relative"]
    checks["decoupling_located"] = dec["share_relative"] <= pol["decoupling_relative"]
    checks["decoupling_precedes_analytical_pinch_off"] = (0 < dec["time_s"] < ref["pinch_time_s"]
                                                          and ref["opening_limit_m"] is not None
                                                          and dec["opening_m"] < ref["opening_limit_m"]
                                                          and dec["thinnest_fraction"] > 0)
    after = dict(time_s=ref["pinch_time_s"]-dec["time_s"],
                 opening_m=None if ref["opening_limit_m"] is None else ref["opening_limit_m"]-dec["opening_m"])
    finest = 2*chain.half_width_m/max(par["refinement_columns"])
    resolution = dict(
        refinement_detection_fraction=refined["detection_fraction"], finest_column_width_m=finest,
        deepest_neck_material_scale_m={key: float(case["neck_material_scale_m"][-1]) for key, case in cases.items()},
        rungs_narrower_than_finest_column={key: int(np.sum(case["neck_material_scale_m"] < finest))
                                           for key, case in cases.items()},
        resolved_event=UNRESOLVED,
        reason="lateral convergence is checked only at the first detection level; the other rungs are continuum "
               "integrals and no per-rung resolved event certificate is implemented")
    return finish(checks, cases=cases, refinement=refined, decoupling=dict(dec, analytical_pinch_off_after=after),
                  resolution=resolution, law=LAW, event_record=EVENT,
                  scope="analytical continuum feasibility of the declared fixed power law with a non-degenerate "
                        "quadratic minimum, with the D1 clock; lateral refinement of the exact discrete chain only at "
                        "the first detection level; no resolved connectivity-loss event is certified")


def no_pinch_control(spec, deadline=None):
    """Negative cases: thinning, weakening and decoupling are real, yet material separation is not established."""
    check_deadline(deadline)
    pol, par = spec["control_policy"], spec["control_parameters"]
    chain = Chain(**par["chain"])
    L, ell, H = chain.half_width_m, chain.weakness_length_m, chain.thickness_m
    fine = pol["gauss_orders"][1]
    rows = {}
    for n in par["exponents"]["subcritical"]:
        n = exponent(n)
        lad = continuum_ladder(n, chain, par, pol, deadline)
        status = feasibility(lad["opening"], lad["time"], lad["slope"], power_law_basis(n, H, L, ell), pol)
        rows[f"n={n:g}"] = dict(exponent=n, opening_m=lad["opening"], time_s=lad["time"], max_slope=lad["slope"],
                                quadrature_relative=lad["quadrature"],
                                closed_form_relative=max_relative(lad["opening"], closed_opening(lad["delta"], n, L, ell)),
                                opening_limit_m=opening_limit(n, L, ell), feasibility=status,
                                decoupling=decoupling(n, chain, par["decoupling_share"], fine))
    n = exponent(par["exponents"]["reference"])
    levels = np.arange(1, par["ladder_levels"]+1)
    delta = 2.0**(-levels*n)
    uniform = 2*L*(2.0**levels-1)                        # delta^(-1/n) = H/h = 2^k exactly: the affine strip
    b = fraction(par["plateau_fraction"], "plateau fraction")*L
    plateau = 2*b*(delta**(-1/n)-1)+profile(delta, n, L-b, ell, fine)[0]
    plateau_slope = max_slope(delta, n, H, L-b, ell)
    width = positive(par["fixed_neck_width_m"], "fixed neck width")
    fixed = width*levels*math.log(2)                     # h = H exp(-U/w): U = w ln(H/h)
    d2 = json.loads((ROOT/FAULT_CASE).read_text(encoding="utf-8"))["parameters"]["physical_length_m"]
    kinematic = dict(uniform=dict(opening_m=uniform, verdict=ladder_verdict(uniform, pol)),
                     plateau=dict(opening_m=plateau, max_slope=plateau_slope, verdict=ladder_verdict(plateau, pol)),
                     fixed_width=dict(width_m=width, opening_m=fixed, verdict=ladder_verdict(fixed, pol)))
    checks = dict(
        subcritical_quadrature_self_consistent=all(r["quadrature_relative"] <= pol["quadrature_relative"]
                                                   for r in rows.values()),
        subcritical_closed_forms=all(r["closed_form_relative"] <= pol["closed_form_relative"] for r in rows.values()),
        subcritical_no_finite_limit=all(r["feasibility"]["status"] == NO_LIMIT and r["opening_limit_m"] is None
                                        for r in rows.values()),
        subcritical_inside_validity=all(r["feasibility"]["max_slope"] <= pol["slope_bound"] for r in rows.values()),
        decoupled_but_connected=all(r["decoupling"]["share_relative"] <= pol["decoupling_relative"]
                                    and r["decoupling"]["thinnest_fraction"] > 0
                                    and math.isfinite(r["decoupling"]["time_s"]) for r in rows.values()),
        uniform_affine_no_finite_limit=kinematic["uniform"]["verdict"]["verdict"] == "NO_FINITE_LIMIT",
        flat_plateau_no_finite_limit=(kinematic["plateau"]["verdict"]["verdict"] == "NO_FINITE_LIMIT"
                                      and float(np.max(plateau_slope)) <= pol["slope_bound"]),
        fixed_width_no_finite_limit=kinematic["fixed_width"]["verdict"]["verdict"] == "NO_FINITE_LIMIT",
        fixed_width_is_d2_length=number(d2, "D2 physical length") == width)
    return finish(checks, subcritical=rows, kinematic=kinematic, reference_exponent=n,
                  scope="n <= 2 and flat or fixed-width necks thin for ever; the D6 decoupling share is reached at "
                        "finite time while the material stays connected")


def validity_control(spec, deadline=None):
    """Refusals where the reduced dynamics would over-claim: cusped necks, also when every sampled slope is small, and
    rate-independent chains; and the regularised-plastic asymptote, which supports no universal no-pinch rule."""
    check_deadline(deadline)
    pol, par = spec["control_policy"], spec["control_parameters"]
    chain = Chain(**par["chain"])
    L, ell = chain.half_width_m, chain.weakness_length_m
    n = exponent(par["exponents"]["outside_validity"])
    lad = continuum_ladder(n, chain, par, pol, deadline)
    status = feasibility(lad["opening"], lad["time"], lad["slope"], power_law_basis(n, chain.thickness_m, L, ell), pol)
    thin = positive(par["slender_thickness_m"], "slender thickness")
    thin_slope = max_slope(lad["delta"], n, thin, L, ell)          # openings and times do not depend on H
    slender = feasibility(lad["opening"], lad["time"], thin_slope, power_law_basis(n, thin, L, ell), pol)
    reduced = ladder_verdict(lad["opening"], pol)
    limit = opening_limit(n, L, ell)
    hf = fraction(par["detection_fraction"], "detection fraction")
    plastic = [rigid_plastic_opening(size, chain, hf) for size in par["rigid_plastic_columns"]]
    ratios = [a["opening_m"]/b["opening_m"] for a, b in zip(plastic, plastic[1:])]
    mesh_dependent = all(abs(r-2) <= 2*pol["mesh_ratio_relative"] for r in ratios)
    check_deadline(deadline)
    pp = par["parallel_plastic"]
    m, k = exponent(pp["exponent"]), positive(pp["scaled_creep"], "scaled creep coefficient")
    sigma = np.asarray(pp["stress_multiples"], dtype=float)
    point, kernel = parallel_plastic(sigma, m, k), parallel_kernel(sigma, m, k)
    parity = max(max_relative(kernel["stress"], sigma), max_relative(kernel["plastic_share"], point["plastic_share"]))
    regimes = [regime_reasons(float(share), 1/float(e), par["retained"])
               for share, e in zip(point["plastic_share"], point["local_exponent"])]
    checks = dict(
        quadrature_self_consistent=lad["quadrature"] <= pol["quadrature_relative"],
        reduced_law_predicts_finite_pinch=limit is not None and reduced["verdict"] == "FINITE_LIMIT",
        cusped_neck_refused=status["status"] == OUTSIDE and status["first_level_outside"] is not None,
        slender_sampled_slopes_inside_bound=float(np.max(thin_slope)) <= pol["slope_bound"],
        slender_cusped_neck_refused=slender["status"] == OUTSIDE and slender["first_level_outside"] is None,
        rigid_plastic_two_weakest_columns=all(r["weakest_columns"] == 2 for r in plastic),
        rigid_plastic_opening_scales_with_column_width=mesh_dependent,
        parallel_kernel_parity=parity <= pol["parity_relative"],
        parallel_low_stress_refused=bool(regimes[0]),
        parallel_plastic_share_falls=bool(np.all(np.diff(point["plastic_share"]) < 0)),
        parallel_high_stress_creep_dominated=not regimes[-1],
        parallel_exponent_tends_to_creep=abs(float(point["local_exponent"][-1])-m) <= pol["exponent_tolerance"])
    return finish(checks, cusped=dict(exponent=n, opening_limit_m=limit, max_slope=lad["slope"],
                                      reduced_verdict=reduced, feasibility=status),
                  slender=dict(thickness_m=thin, max_slope=thin_slope, feasibility=slender),
                  rigid_plastic=dict(rows=plastic, successive_ratios=ratios,
                                     status=ILL_POSED if mesh_dependent else UNRESOLVED),
                  parallel_plastic=dict(exponent=m, scaled_creep=k, stress_multiples=sigma, rate_scaled=point["rate"],
                                        plastic_share=point["plastic_share"], local_exponent=point["local_exponent"],
                                        kernel_parity_relative=parity, regimes=regimes,
                                        scope="scaled point law of the retained additive form, independent of the "
                                              "mantle fixture, whose coefficients are not extrapolated; a "
                                              "mathematical counterexample, not a physical state"),
                  owner="I07 resolved x-z neck with a physical shear-zone width much smaller than the thickness")


def retained_control(spec, deadline=None):
    """Read-only regime evaluation of the accepted layered column at its committed initial state; no chain run."""
    check_deadline(deadline)
    pol, par = spec["control_policy"], spec["control_parameters"]
    r = par["retained"]
    chain = Chain(**par["chain"])
    fspec, ctx = fs.load_case()
    require(fspec["campaign"]["reference_order"] == r["order"], "premise order differs from the accepted reference")
    base, thermal, _, _ = fs.layered(ctx, r["order"])
    coeffs = fs.coefficients(base)
    law, drive, fractions = ctx["law"], ctx["drive"], ctx["heat"]["heat_fractions"]
    kappa0 = weakening.initial_history(base, ctx["weak"])
    temperature = np.asarray(thermal.steady_k, dtype=float)+np.zeros(base.size)
    check_deadline(deadline)
    first = fs.stage(base, coeffs, law, 1.0, temperature, kappa0, drive, fractions, deadline=deadline)
    recorded = json.loads((ROOT/RECEIPT).read_text(encoding="utf-8"))["controls"]["connection"]["finite_strain"]
    parity = dict(velocity=relative(float(first["velocity_m_s"]), recorded["velocity_start_m_s"]),
                  force=relative(float(first["force"]), recorded["column_force_start_n_m"]))
    operating = abs(float(first["rate"]))
    stretches, multipliers = r["stretches"], r["rate_multipliers"]
    rows = []
    for stretch in stretches:
        prep = fs.column_at(base, coeffs, stretch, temperature)
        for multiplier in multipliers:
            check_deadline(deadline)
            rate = operating*multiplier
            out = weakening.respond(prep, law, kappa0, rate)
            rows.append(dict(stretch=stretch, multiplier=multiplier, rate_s=rate, force_n_m=float(out["force"]),
                             rate_sensitivity=rate*float(out["dforce"])/float(out["force"]),
                             plastic_share=float(out["plastic_work"])/float(out["work"]),
                             partition_relative=abs(out["creep_work"]+out["plastic_work"]-out["work"])/out["work"],
                             yielding_points=int(np.count_nonzero(np.asarray(out["plastic_rate"]) > 0))))
    at = {(row["stretch"], row["multiplier"]): row for row in rows}
    thinning = {f"{m:g}": [-(math.log(at[(b, m)]["force_n_m"])-math.log(at[(a, m)]["force_n_m"]))/math.log(b/a)
                           for a, b in zip(stretches, stretches[1:])] for m in multipliers}
    necking = {f"{m:g}": thinning[f"{m:g}"][0]/at[(stretches[0], m)]["rate_sensitivity"] for m in multipliers}
    initial = [at[(stretches[0], m)] for m in multipliers]
    reasons = []
    for row in initial:
        reasons += [text for text in regime_reasons(row["plastic_share"], row["rate_sensitivity"], r)
                    if text not in reasons]
    classification = RESOLVED_NECK if reasons else CONSISTENT
    checks = dict(
        same_state_as_accepted_receipt=max(parity.values()) <= pol["parity_relative"],
        drive_and_thickness_match_chain=(drive.force_n_m == chain.drive_n_m and drive.drag_pa_s == chain.drag_pa_s
                                         and base.thickness_m == chain.thickness_m),
        force_rises_with_rate=all(at[(s, a)]["force_n_m"] < at[(s, b)]["force_n_m"]
                                  for s in stretches for a, b in zip(multipliers, multipliers[1:])),
        force_falls_with_stretch=all(at[(a, m)]["force_n_m"] > at[(b, m)]["force_n_m"]
                                     for m in multipliers for a, b in zip(stretches, stretches[1:])),
        rate_sensitivity_in_unit_interval=all(0 < row["rate_sensitivity"] <= 1+1e-9 for row in rows),
        work_partition_closes=all(row["partition_relative"] <= 2*weakening.TOL for row in rows),
        classification_reported=classification in (CONSISTENT, RESOLVED_NECK))
    return finish(checks, order=r["order"], receipt=RECEIPT, parity_relative=parity,
                  operating=dict(rate_s=operating, velocity_m_s=float(first["velocity_m_s"]),
                                 column_force_n_m=float(first["force"]),
                                 plastic_share=float(first["plastic_work"])/float(first["work"])),
                  rows=rows, thinning_sensitivity=thinning, necking_number=necking,
                  classification=classification, reasons=reasons, eventual_breakup=UNRESOLVED,
                  generated_breakup_authorised=False,
                  scope="regime of the accepted fixed-temperature column at sampled states, reported and not gated; "
                        "REFUSED_REQUIRES_RESOLVED_NECK marks a regime the reduced chain does not support and leaves "
                        "eventual breakup unresolved, not excluded; consistency would grant nothing, because an "
                        "exponent inferred at a finite state is not a constant-power-law basis")


CONTROLS = (("invariant", invariant_control), ("pinch", pinch_control), ("no_pinch", no_pinch_control),
            ("validity", validity_control), ("retained", retained_control))


# ----------------------------------------------------------------------------- case

def validate_parameters(par, pol):
    """Structural sanity of the frozen inputs; exact equality with the executable is checked by validate_case."""
    require(type(par) is dict and type(pol) is dict, "parameters and policy must be objects")
    require(0 < number(pol["maximum_seconds"], "maximum seconds") <= 60, "cooperative budget must lie in (0, 60] s")
    orders = pol["gauss_orders"]
    require(type(orders) is list and len(orders) == 2 and all(type(o) is int for o in orders)
            and 8 <= orders[0] < orders[1] <= 4096, "two increasing Gauss-Legendre orders required")
    chain = Chain(**par["chain"])
    e = par["exponents"]
    require(all(2 < exponent(e[key]) <= 4 for key in ("reference", "second")),
            "feasibility exponents must lie in the analytical window (2, 4]")
    require(type(e["subcritical"]) is list and e["subcritical"]
            and all(1 <= exponent(v) <= 2 for v in e["subcritical"]), "subcritical exponents must lie in [1, 2]")
    require(exponent(e["outside_validity"]) > 4, "the validity refusal needs n > 4")
    window = pol["ladder_window"]
    require(type(window) is int and window >= 2, "ladder window must be an integer >= 2")
    integer(par["ladder_levels"], "ladder levels", window+2, 16)
    fraction(par["detection_fraction"], "detection fraction")
    for key in ("chain_columns", "uniform_columns", "refinement_columns", "rigid_plastic_columns"):
        sizes = par[key]
        require(type(sizes) is list and len(sizes) >= 2 and all(type(s) is int and 1 <= s <= 8192 for s in sizes)
                and sizes == sorted(set(sizes)), key+" must be increasing distinct integers in 1..8192")
    for key in ("refinement_columns", "rigid_plastic_columns"):
        sizes = par[key]
        require(all(b == 2*a for a, b in zip(sizes, sizes[1:])) and all(s % 2 == 0 for s in sizes),
                key+" must double an even column count")
    require(pol["refinement_order_range"][0] < 2 < pol["refinement_order_range"][1], "refinement orders bracket 2")
    fraction(par["plateau_fraction"], "plateau fraction")
    positive(par["fixed_neck_width_m"], "fixed neck width")
    require(positive(par["slender_thickness_m"], "slender thickness") < chain.thickness_m,
            "the slender belt must be thinner than the control belt")
    pp = par["parallel_plastic"]
    require(type(pp) is dict and set(pp) == {"exponent", "scaled_creep", "stress_multiples"},
            "parallel-plastic counterexample fields mismatch")
    require(1 < exponent(pp["exponent"]) <= 8, "the counterexample needs a creep exponent in (1, 8], inside the kernel")
    positive(pp["scaled_creep"], "scaled creep coefficient")
    stresses = pp["stress_multiples"]
    require(type(stresses) is list and len(stresses) >= 2 and all(number(v, "stress multiple") > 1 for v in stresses)
            and all(a < b for a, b in zip(stresses, stresses[1:])), "stress multiples must increase above yield")
    require(fraction(par["decoupling_share"], "decoupling share") < chain.initial_belt_share,
            "decoupling share must lie below the initial belt share")
    L, ell = chain.half_width_m, chain.weakness_length_m
    for d in par["hypergeometric_deltas"]:
        d = fraction(d, "hypergeometric delta")
        require((1-d)*L*L/(ell*ell*d) < 1, "hypergeometric checks are restricted to |z| < 1")
    pf = par["prescribed_force"]
    require(fraction(pf["mean_share"], "mean share")*(1+number(pf["relative_amplitude"], "amplitude")) <= 1
            and 0 <= pf["relative_amplitude"] < 1 and positive(pf["period_scaled"], "period") > 0,
            "the prescribed share must stay inside (0, 1]")
    require(0 < pol["ratio_max"] < pol["divergence_ratio"] <= 1 and 0 < pol["ratio_spread"] < 1,
            "ladder ratio gates must satisfy 0 < ratio_max < divergence_ratio <= 1")
    require(0 < pol["slope_bound"] < 1, "long-wave slope bound must lie in (0, 1)")
    r = par["retained"]
    integer(r["order"], "retained order", 2, 128)
    require(r["stretches"][0] == 1.0 and all(a < b for a, b in zip(r["stretches"], r["stretches"][1:]))
            and r["stretches"][-1] <= fs.STRETCH_CEILING[1], "retained stretches start at 1 inside the frozen window")
    require(r["rate_multipliers"][0] == 1.0 and all(a < b for a, b in zip(r["rate_multipliers"], r["rate_multipliers"][1:])),
            "rate ladder starts at the operating rate and increases")
    fraction(r["plastic_share_max"], "plastic share limit")
    low, high = r["creep_rate_sensitivity"]
    require(0 < low < high < 1, "creep rate-sensitivity window must lie inside (0, 1)")
    return True


def validate_case(spec):
    require(type(spec) is dict and set(spec) == CASE_FIELDS and spec["schema"] == SCHEMA,
            "breakup-closure case schema or top-level fields mismatch")
    require(spec["status"] == "WORKING_NON_CANON", "status must stay WORKING_NON_CANON")
    decision = spec["decision"]
    require(type(decision) is dict and decision.get("selected_law") == LAW and decision.get("event_record") == EVENT,
            "selected law or event record differs from the executable")
    require(spec["control_policy"] == POLICY, "case policy and executable differ")
    require(spec["control_parameters"] == PARAMETERS, "case parameters and executable differ")
    validate_parameters(spec["control_parameters"], spec["control_policy"])
    return spec


def load_case(path=CASE):
    return validate_case(json.loads(Path(path).read_text(encoding="utf-8")))


# ----------------------------------------------------------------------------- evidence

def digest(name):
    return hashlib.sha256((ROOT/name).read_bytes()).hexdigest()


def bindings():
    return {name: digest(name) for name in NEW_FILES+RETAINED+(FAULT_CASE,)+tuple(ACCEPTED_RECEIPTS)}


def evidence_match(current):
    """Accepted receipt is its declared bytes; every source it recorded still has those bytes; imported modules resolve
    to their bound paths."""
    receipts = {name: current[name] == value for name, value in ACCEPTED_RECEIPTS.items()}
    recorded = {}
    for name in ACCEPTED_RECEIPTS:
        for source, value in json.loads((ROOT/name).read_text(encoding="utf-8"))["source_sha256"].items():
            recorded.setdefault(source, set()).add(value)
    sources = {}
    for source, values in sorted(recorded.items()):
        present = (ROOT/source).is_file()
        now = current[source] if source in current else (digest(source) if present else None)
        sources[source] = present and len(values) == 1 and now in values
    retained = {name: sources.get(name, False) for name in RETAINED}
    imported = {name: Path(module.__file__).resolve() == (ROOT/name).resolve() for name, module in IMPORTED.items()}
    return dict(receipts=receipts, recorded_sources=sources, retained=retained, imported=imported)


def jsonable(value):
    """Plain JSON types; non-finite floats are left in place so serialisation refuses them."""
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream, threadpool_limits(limits=1, user_api="blas"):
        result = dict(schema="atlas.i01-breakup-closure-evidence.v1", status="INCOMPLETE", scientific_acceptance=False,
                      generated_breakup_authorised=False, resolved_event=UNRESOLVED, law=LAW,
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
            spec = load_case()
            result["case"] = spec
            deadline = start+spec["control_policy"]["maximum_seconds"]      # cooperative budget counted after imports
            for name, control in CONTROLS:
                begin = time.perf_counter()
                try:
                    data = control(spec, deadline)
                    check_deadline(deadline)                # an overrunning control is not recorded as a pass
                    result["controls"][name] = dict(status="PASS" if data["passed"] else "FAIL",
                                                    seconds=time.perf_counter()-begin, **data)
                except (ValueError, RuntimeError, ArithmeticError) as exc:
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
            text = json.dumps(jsonable(result), indent=2, allow_nan=False)
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
