"""I01 MC-01 candidate: cohesion-loss separation law. Local slice only: not a resolved neck or a separation event.

WORKING NON-CANON. The retained D2 plane-strain yield Y = C cos(phi) + P_eff sin(phi) softens linearly in the
strength-controlling plastic history kappa, from the peak Y0 to the residual Yr at kappa_c. In a band of declared
physical width w_s this is linear slip weakening over D_c = kappa_c w_s with breakdown energy G = (Y0 - Yr) D_c / 2
per unit area: derived locally and pressure dependent, never a universal fracture energy. Where the law's provenance
declares its residual state to be sliding on a broken (cohesionless, so zero residual cohesion) surface, the state
lies inside its declared support and the whole history is recorded as accumulated inside that support, material with
kappa >= kappa_c is BROKEN: it still carries frictional traction but no bond. A section separates only when no BONDED
path of tracked crust, mantle lithosphere or their union joins the declared anchors.

The exact local control loads one band through an elastic surroundings spring that keeps the stored traction, with
optional Newtonian band creep and the viscoplastic branch in series, at fixed temperature and effective pressure,
with no healing and no geometry evolution. Its three linear phases are integrated exactly.
Method: tectonics/docs/I01_SEPARATION_LAW.md. Nothing here authorises an event, a split or MC-01 closure.
Run: python -B tectonics/tools/check_i01_separation_law.py --output NEW.json
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "atlas.cohesion-loss-separation.v1"
EVIDENCE_SCHEMA = "atlas.i01-separation-law.v1"
CASE_SCHEMA = "atlas.i01-separation-law-case.v1"
CASE = "cases/i01_separation_law_v1.json"
DECISION_CASE = "cases/i01_separation_decision_v1.json"
PASS = "PASS_BOUNDED_CONTROLS_ONLY"
NEW_FILES = ("tools/check_i01_separation_law.py", "tests/test_i01_separation_law.py",
             "cases/i01_separation_law_v1.json", "docs/I01_SEPARATION_LAW.md")
RETAINED = ("cases/i01_separation_decision_v1.json", "docs/I01_SEPARATION_DECISION.md")
CASE_FIELDS = frozenset({"schema", "status", "contract", "document", "kind", "scientific_acceptance",
                         "event_authorised", "mc01", "policy", "decision", "runnable_controls",
                         "unimplemented_resolved_comparison", "proposed_wording_corrections", "sources"})
# Frozen before execution; cases/i01_separation_law_v1.json must carry exactly this policy.
POLICY = {
    "closed_form_relative": 1e-12,     # exact algebra evaluated in floating point
    "event_relative": 1e-11,           # kernel event times and states against independent scalar solutions
    "event_bracket_relative": 1e-13,   # bisection bracket width relative to the event time
    "energy_relative": 1e-10,          # balances of Gauss quadrature on the exact solution
    "gauss_points": 16,
    "subinterval_exponent": 4.0,       # (|m| + q) h per Gauss sub-interval
    "maximum_exponent": 600.0,         # (|m| + q) t per exact segment, well inside the double range
    "maximum_segments": 4096,
    "series_threshold": 0.5,           # q t at or below which J1, J2 use the division-free series
    "series_terms": 28,
    "bisection_iterations": 200,
    "timing_calls": 50,
    "timing_repetitions": 5,
    "maximum_seconds": 60.0,
}

INVALID = "REFUSED_INVALID_INPUT"
NOT_PHYSICAL = "REFUSED_WIDTH_NOT_PHYSICAL"
NO_SOFTENING = "REFUSED_NO_SOFTENING"
NO_PROVENANCE = "REFUSED_MISSING_PROVENANCE"
OUTSIDE = "REFUSED_OUTSIDE_SUPPORT"
HEALING = "REFUSED_HEALING_NOT_IN_SLICE"
REVERSE = "REFUSED_REVERSE_OR_TENSILE_LOADING"
OPENING = "REFUSED_OPENING_NOT_OWNED"
FIELD = "REFUSED_UNSUPPORTED_FIELD"
SECTION = "REFUSED_INVALID_SECTION"
RANGE = "REFUSED_NUMERIC_RANGE"
BALANCE = "REFUSED_UNRESOLVED_BALANCE"
INCONSISTENT = "REFUSED_INCONSISTENT_RESIDUAL"

RESIDUAL_STATES = ("broken_surface_sliding", "weakened_intact")
# Support record of an accumulated plastic history: only INSIDE (every increment produced inside the law's declared
# support) is classified; the current temperature and pressure never certify an earlier history.
HISTORY_SUPPORT = ("INSIDE", "UNKNOWN", "VIOLATED")
BONDS = ("BONDED", "BROKEN", "UNRESOLVED")
FACES = ("WELDED", "COHESIONLESS", "UNRESOLVED")
MATERIALS = ("crust", "mantle_lithosphere", "exterior")
SELECTIONS = {"crust": frozenset({"crust"}), "mantle_lithosphere": frozenset({"mantle_lithosphere"}),
              "union": frozenset({"crust", "mantle_lithosphere"})}
CELL_FIELDS = frozenset({"material", "bond"})
CONNECTIVITY = ("CONNECTED", "DISCONNECTED", "UNRESOLVED")
ACCOUNTS = ("work_j_m2", "stored_change_j_m2", "creep_dissipation_j_m2", "plastic_dissipation_j_m2",
            "overstress_dissipation_j_m2", "breakdown_dissipation_j_m2", "residual_friction_dissipation_j_m2",
            "plastic_slip_m")
REQUIREMENTS = ("the resolved comparison of the method's section 9, with support along the whole approach",
                "along-strike and exterior coverage with both new-boundary ends on the network (I03/I07)",
                "the whole-window replacement-motion comparison with I02's eps_v (separation decision section 4)",
                "conservative D6 transfers and one I02 commit")
_NODES, _WEIGHTS = np.polynomial.legendre.leggauss(POLICY["gauss_points"])
GAUSS = tuple((float(node), float(weight)) for node, weight in zip(_NODES, _WEIGHTS))


class Refusal(ValueError):
    """One refusal type with a stable machine code; inputs are never modified."""

    def __init__(self, code, message):
        super().__init__(code+": "+message)
        self.code = code


def _real(value, name, *, positive=False, nonnegative=False):
    if type(value) not in (int, float):
        raise Refusal(INVALID, name+" must be a finite real number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise Refusal(INVALID, name+" must be a finite real number")
    value = float(value)
    if positive and value <= 0:
        raise Refusal(INVALID, name+" must be positive")
    if nonnegative and value < 0:
        raise Refusal(INVALID, name+" must be nonnegative")
    return value


def _interval(value, name):
    if type(value) not in (tuple, list) or len(value) != 2:
        raise Refusal(INVALID, name+" must be a (lower, upper) pair")
    lower, upper = (_real(item, name) for item in value)
    if not lower < upper:
        raise Refusal(INVALID, name+" needs lower < upper")
    return lower, upper


# ----------------------------------------------------------------------------- the law

@dataclass(frozen=True)
class SofteningLaw:
    """Retained D2 plane-strain yield, softened linearly in its strength-controlling history (method section 3.1).

    Every value is an explicit IN-04 input with provenance; nothing here is a planetary default. width_basis must be
    "physical": a width counted in grid cells or regularisation lengths would make toughness, and even the brittle
    regime, mesh dependent (method section 3.6). No fracture energy is accepted as an input; G is derived.
    """
    peak_cohesion_pa: float
    peak_friction_rad: float
    residual_cohesion_pa: float
    residual_friction_rad: float
    softening_history: float
    band_width_m: float
    width_basis: str
    plastic_viscosity_pa_s: float
    residual_state: str
    provenance: str
    support_temperature_k: tuple
    support_effective_pressure_pa: tuple

    def __post_init__(self):
        for name in ("peak_cohesion_pa", "residual_cohesion_pa"):
            object.__setattr__(self, name, _real(getattr(self, name), name, nonnegative=True))
        for name in ("peak_friction_rad", "residual_friction_rad"):
            angle = _real(getattr(self, name), name, nonnegative=True)
            if angle >= math.pi/2:
                raise Refusal(INVALID, name+" must be below pi/2")
            object.__setattr__(self, name, angle)
        for name in ("softening_history", "band_width_m", "plastic_viscosity_pa_s"):
            object.__setattr__(self, name, _real(getattr(self, name), name, positive=True))
        if self.width_basis != "physical":
            raise Refusal(NOT_PHYSICAL, "the band width must be a declared physical length fixed under refinement, "
                          "not a number of grid cells or regularisation lengths")
        if self.residual_state not in RESIDUAL_STATES:
            raise Refusal(INVALID, "residual_state must be one of "+", ".join(RESIDUAL_STATES))
        if type(self.provenance) is not str or not self.provenance.strip():
            raise Refusal(NO_PROVENANCE, "softening and residual parameters need a stated provenance")
        temperature = _interval(self.support_temperature_k, "support_temperature_k")
        pressure = _interval(self.support_effective_pressure_pa, "support_effective_pressure_pa")
        if temperature[0] <= 0 or pressure[0] < 0:
            raise Refusal(INVALID, "support needs absolute temperature > 0 and effective pressure >= 0")
        object.__setattr__(self, "support_temperature_k", temperature)
        object.__setattr__(self, "support_effective_pressure_pa", pressure)
        for value in pressure:          # both yields are affine in P_eff, so the two ends cover the support
            peak, residual = self._yields(value)
            if not peak > residual >= 0:
                raise Refusal(NO_SOFTENING, "the peak yield must exceed a nonnegative residual across the support")
        if self.residual_state == "broken_surface_sliding" and self.residual_cohesion_pa != 0:
            raise Refusal(INCONSISTENT, "a broken_surface_sliding residual has lost its cohesion, so its residual "
                          "cohesion must be zero; a cohesive fracture state would need its own admitted law")
        slip = self.softening_history*self.band_width_m
        for value in pressure:          # G and k_soft are affine in P_eff and 1/D_c, so the two ends bound them
            peak, residual = self._yields(value)
            energy = (peak-residual)*slip/2
            if not (math.isfinite(slip) and slip >= sys.float_info.min and 0 < energy < math.inf
                    and 0 < (peak-residual)/slip < math.inf):
                raise Refusal(RANGE, "breakdown slip, energy or softening stiffness not representable")

    def _yields(self, pressure):
        return (self.peak_cohesion_pa*math.cos(self.peak_friction_rad)+pressure*math.sin(self.peak_friction_rad),
                self.residual_cohesion_pa*math.cos(self.residual_friction_rad)
                + pressure*math.sin(self.residual_friction_rad))

    def inside(self, temperature_k, effective_pressure_pa):
        (t_low, t_high), (p_low, p_high) = self.support_temperature_k, self.support_effective_pressure_pa
        return t_low <= temperature_k <= t_high and p_low <= effective_pressure_pa <= p_high

    def yields(self, effective_pressure_pa):
        """(Y0, Yr) in Pa at one effective pressure inside the declared support."""
        pressure = _real(effective_pressure_pa, "effective pressure", nonnegative=True)
        low, high = self.support_effective_pressure_pa
        if not low <= pressure <= high:
            raise Refusal(OUTSIDE, "effective pressure outside the softening law's declared support")
        return self._yields(pressure)

    def breakdown_slip_m(self):
        """D_c = kappa_c w_s: fixed under refinement because w_s is physical."""
        return self.softening_history*self.band_width_m

    def fracture_energy_j_m2(self, effective_pressure_pa):
        """G = (Y0 - Yr) D_c / 2 per unit band area: area between the slip-weakening curve and the residual."""
        peak, residual = self.yields(effective_pressure_pa)
        return (peak-residual)*self.breakdown_slip_m()/2

    def softening_stiffness_pa_m(self, effective_pressure_pa):
        peak, residual = self.yields(effective_pressure_pa)
        return (peak-residual)/self.breakdown_slip_m()

    def strength_pa(self, history, effective_pressure_pa):
        peak, residual = self.yields(effective_pressure_pa)
        kappa = _real(history, "history", nonnegative=True)
        if kappa >= self.softening_history:
            return residual
        return peak-(peak-residual)/self.softening_history*kappa

    def bond_state(self, history, temperature_k, effective_pressure_pa, *, history_support):
        """BONDED, BROKEN or UNRESOLVED for a history with a declared support record (method section 3.3).

        Only a history recorded as accumulated wholly INSIDE the declared support is classified. The current
        (T, P_eff) never certifies an earlier history, so an UNKNOWN or VIOLATED record stays UNRESOLVED even after
        the point returns inside the support.
        """
        kappa = _real(history, "history", nonnegative=True)
        temperature = _real(temperature_k, "temperature", positive=True)
        pressure = _real(effective_pressure_pa, "effective pressure", nonnegative=True)
        if history_support not in HISTORY_SUPPORT:
            raise Refusal(INVALID, "history_support must be one of "+", ".join(HISTORY_SUPPORT))
        if kappa == 0:
            return "BONDED"             # creep and elastic loading never remove cohesion
        if not self.inside(temperature, pressure) or history_support != "INSIDE":
            return "UNRESOLVED"         # plastic history beyond the reach, or the record, of the cohesion-loss evidence
        if self.residual_state == "broken_surface_sliding" and kappa >= self.softening_history:
            return "BROKEN"
        return "BONDED"


@dataclass(frozen=True)
class Loading:
    """Constant over one advance: surroundings stiffness k (Pa/m) storing the retained traction, far-field loading
    rate V (m/s, one shear sense), optional Newtonian band creep eta_v (Pa s; None = no creep branch), effective
    pressure and temperature. The control fixes temperature and pressure and has no healing and no geometry
    evolution, so the healing rate must be zero. Strength recovery would not by itself rejoin broken material: a
    future reconnection needs its own admitted irreversible bond or surface history, which is not implemented here."""
    stiffness_pa_m: float
    loading_rate_m_s: float
    creep_viscosity_pa_s: float | None
    effective_pressure_pa: float
    temperature_k: float
    healing_rate_s: float = 0.

    def __post_init__(self):
        object.__setattr__(self, "stiffness_pa_m", _real(self.stiffness_pa_m, "stiffness", positive=True))
        rate = _real(self.loading_rate_m_s, "loading rate")
        if rate < 0:
            raise Refusal(REVERSE, "one shear sense only: reverse loading needs the general resolved route")
        object.__setattr__(self, "loading_rate_m_s", rate)
        if self.creep_viscosity_pa_s is not None:
            object.__setattr__(self, "creep_viscosity_pa_s",
                               _real(self.creep_viscosity_pa_s, "creep viscosity", positive=True))
        object.__setattr__(self, "effective_pressure_pa",
                           _real(self.effective_pressure_pa, "effective pressure", nonnegative=True))
        object.__setattr__(self, "temperature_k", _real(self.temperature_k, "temperature", positive=True))
        if _real(self.healing_rate_s, "healing rate", nonnegative=True) != 0:
            raise Refusal(HEALING, "this control has no healing h(T): it fixes temperature and pressure, and strength "
                          "recovery is not an admitted reconnection law")
        object.__setattr__(self, "healing_rate_s", 0.)


@dataclass(frozen=True)
class State:
    """One band: the retained shear traction (never reset), its strength-controlling history, the clock and the
    support record of that history (HISTORY_SUPPORT; UNKNOWN unless the caller declares it). An advance adds only
    history produced inside the support; it never upgrades an UNKNOWN or VIOLATED record."""
    traction_pa: float
    history: float
    time_s: float = 0.
    history_support: str = "UNKNOWN"

    def __post_init__(self):
        object.__setattr__(self, "traction_pa", _real(self.traction_pa, "traction", nonnegative=True))
        object.__setattr__(self, "history", _real(self.history, "history", nonnegative=True))
        object.__setattr__(self, "time_s", _real(self.time_s, "time", nonnegative=True))
        if self.history_support not in HISTORY_SUPPORT:
            raise Refusal(INVALID, "history_support must be one of "+", ".join(HISTORY_SUPPORT))


# ----------------------------------------------------------------------------- exact linear phases

@dataclass(frozen=True)
class _Phase:
    """x' = B x + c for x = (traction, history), with real eigenvalues m +/- q and q >= |m| because det B <= 0."""
    name: str
    b: tuple
    c: tuple
    m: float
    q: float


def _phi1(z):
    return 1. if z == 0 else math.expm1(z)/z


def _coefficients(m, q, t):
    """e^{mt}cosh(qt), e^{mt}sinh(qt)/q and their integrals J1, J2 over [0, t], for q >= |m| and t >= 0."""
    u, v = m*t, q*t
    if v <= POLICY["series_threshold"]:
        # e^{u s}cosh(v s) = sum Q_n s^n/n! and e^{u s}sinh(v s)/v = sum P_n s^n/n! on s in [0, 1], with
        # Q_{n+1} = u Q_n + v^2 P_n and P_{n+1} = Q_n + u P_n: no division by a small v; |u| + v <= 1.
        big_q, big_p, factorial = 1., 0., 1.
        cosh_sum = sinh_sum = cosh_integral = sinh_integral = 0.
        for n in range(POLICY["series_terms"]):
            cosh_sum += big_q/factorial
            sinh_sum += big_p/factorial
            cosh_integral += big_q/(factorial*(n+1))
            sinh_integral += big_p/(factorial*(n+1))
            big_q, big_p = u*big_q+v*v*big_p, big_q+u*big_p
            factorial *= n+1
        return cosh_sum, t*sinh_sum, t*cosh_integral, t*t*sinh_integral
    up, down = u+v, u-v
    if up > POLICY["maximum_exponent"]+1:
        raise Refusal(RANGE, "exact segment exponent outside the bounded range")
    grow, decay = math.exp(up), math.exp(down)
    phi_up, phi_down = _phi1(up), _phi1(down)
    # 2v > 1 here, so neither difference can cancel catastrophically.
    return (grow+decay)/2, t*(grow-decay)/(2*v), t*(phi_up+phi_down)/2, t*t*(phi_up-phi_down)/(2*v)


def _turning_time(slope, curvature, q):
    """Positive root of slope cosh(qt) + curvature sinh(qt)/q = 0, if any; at most one, since tanh(qt)/q rises."""
    if slope == 0 or curvature == 0 or (slope > 0) == (curvature > 0):
        return None
    target = -slope/curvature
    if q == 0:
        return target
    z = q*target
    return math.atanh(z)/q if z < 1 else None


def _bisect(holds, lower, upper):
    """Bracket where holds() first becomes true on a monotone piece: false at lower, true at upper."""
    for _ in range(POLICY["bisection_iterations"]):
        if upper-lower <= POLICY["event_bracket_relative"]*upper:
            break
        middle = lower+(upper-lower)/2
        if not lower < middle < upper:
            break
        if holds(middle):
            upper = middle
        else:
            lower = middle
    return lower, upper


@dataclass(frozen=True, init=False)
class Prepared:
    """Immutable coefficients of one law under one constant loading; rebuild when either changes.

    Phases: sub-yield (traction relaxes by creep; history frozen), softening (kappa < kappa_c) and residual
    (kappa >= kappa_c). Each phase is linear, so an advance is exact up to rounding and quadrature (method section 6).
    """
    law: SofteningLaw
    loading: Loading
    peak_pa: float
    residual_pa: float
    softening_pa: float
    creep_rate_s: float
    plastic_rate_s: float
    drive_pa_s: float
    sub: _Phase
    softening: _Phase
    residual: _Phase

    def __init__(self, law, loading):
        if type(law) is not SofteningLaw or type(loading) is not Loading:
            raise Refusal(INVALID, "typed SofteningLaw and Loading required")
        if not law.inside(loading.temperature_k, loading.effective_pressure_pa):
            raise Refusal(OUTSIDE, "loading state outside the softening law's declared support")
        peak, residual = law.yields(loading.effective_pressure_pa)
        k, width, eta = loading.stiffness_pa_m, law.band_width_m, law.plastic_viscosity_pa_s
        a = 0. if loading.creep_viscosity_pa_s is None else k*width/loading.creep_viscosity_pa_s
        b = k*width/eta
        s = (peak-residual)/law.softening_history          # strength lost per unit history, Pa
        drive = k*loading.loading_rate_m_s
        sigma = s/eta
        ratio = k*law.breakdown_slip_m()/(peak-residual) if peak > residual else math.inf
        for name, value in (("creep rate", a), ("plastic rate", b), ("softening", s), ("drive", drive),
                            ("softening rate", sigma), ("inverse plastic viscosity", 1/eta),
                            ("stability ratio", ratio)):
            if not math.isfinite(value):
                raise Refusal(RANGE, name+" not representable")
        m = (sigma-a-b)/2
        phases = (_Phase("sub_yield", ((-a, 0.), (0., 0.)), (drive, 0.), -a/2, a/2),
                  _Phase("softening", ((-(a+b), -b*s), (1/eta, sigma)), (drive+b*peak, -peak/eta),
                         m, math.hypot(m, math.sqrt(a*sigma))),
                  _Phase("residual", ((-(a+b), 0.), (1/eta, 0.)), (drive+b*residual, -residual/eta),
                         -(a+b)/2, (a+b)/2))
        for name, value in zip(self.__dataclass_fields__, (law, loading, peak, residual, s, a, b, drive)+phases):
            object.__setattr__(self, name, value)

    def strength(self, history):
        if history >= self.law.softening_history:
            return self.residual_pa
        return self.peak_pa-self.softening_pa*history

    def stability_ratio(self):
        """k D_c/(Y0 - Yr); below 1 the rate-independent limit has no quasi-static breakdown path."""
        return self.loading.stiffness_pa_m*self.law.breakdown_slip_m()/(self.peak_pa-self.residual_pa)

    def _net_drive(self, tau):
        """k V - (k w_s/eta_v) tau, rounded once from its exact value in the represented coefficients.

        On the yield surface its sign decides the phase; near the steady creep traction the rounding of the product
        alone could flip that sign, while exact rational arithmetic cannot. An unrepresentable value is refused.
        """
        exact = Fraction(self.drive_pa_s)-Fraction(self.creep_rate_s)*Fraction(tau)
        try:
            value = float(exact)
        except OverflowError:
            value = math.inf
        if not math.isfinite(value) or (value == 0 and exact != 0):
            raise Refusal(RANGE, "net drive not representable")
        return value

    def _phase_of(self, x):
        """The phase whose field the declared ODE follows from x (method section 6).

        tau - Y is a difference of two doubles, so its sign is exact. Off the yield surface that sign decides. On it
        both fields agree and the net drive decides: any strictly positive drive enters plastic flow, because the
        overstress then grows as its integral; zero or negative drive stays sub-yield. No margin is applied.
        """
        tau, kappa = x
        overstress = tau-self.strength(kappa)
        if overstress > 0 or (overstress == 0 and self._net_drive(tau) > 0):
            return self.residual if kappa >= self.law.softening_history else self.softening
        return self.sub

    def _rate(self, phase, x):
        """The physical rate at x, equal to B x + c of the phase (tested) but formed without cancelling products."""
        tau, kappa = x
        relax = self._net_drive(tau)
        if phase is self.sub:
            return relax, 0.
        overstress = self._overstress(phase, x)
        return relax-self.plastic_rate_s*overstress, overstress/self.law.plastic_viscosity_pa_s

    @staticmethod
    def _bend(phase, rate):
        (b11, b12), (b21, b22) = phase.b
        return (b11-phase.m)*rate[0]+b12*rate[1], b21*rate[0]+(b22-phase.m)*rate[1]

    @staticmethod
    def _at(phase, x0, rate, bent, t):
        """x(t) = x0 + J1 v + J2 (B - mI) v with v the rate at x0: exact for the linear phase, singular B included.
        Each increment is formed before it is added, so a change far smaller than x0 keeps its digits."""
        _, _, j1, j2 = _coefficients(phase.m, phase.q, t)
        return x0[0]+(j1*rate[0]+j2*bent[0]), x0[1]+(j1*rate[1]+j2*bent[1])

    def _overstress(self, phase, x):
        return x[0]-(self.residual_pa if phase is self.residual else self.peak_pa-self.softening_pa*x[1])

    def _overstress_path(self, phase, x0, rate, bent):
        """(o0, slope, curvature) with o(t) = o0 + (J1 slope + J2 curvature) along the exact segment.

        The overstress is a linear function of the state, so it has its own exact path. Forming it as the difference
        of a traction and a strength of similar size would round a small overstress away near the yield surface.
        """
        grad = self.softening_pa if phase is self.softening else 0.
        return x0[0]-self.strength(x0[1]), rate[0]+grad*rate[1], bent[0]+grad*bent[1]

    def _next_event(self, phase, x0, rate, bent, span):
        """First event in (0, span]: ("yield" | "unload" | "softening_complete", lower, upper), or None.

        softening_complete is the constitutive event kappa = kappa_c. Whether it removes cohesion is the law's bond
        state, recorded separately by advance; a weakened_intact residual completes softening and stays BONDED.
        """
        at = lambda t: self._at(phase, x0, rate, bent, t)
        start, slope, curvature = self._overstress_path(phase, x0, rate, bent)

        def over(t):
            _, _, j1, j2 = _coefficients(phase.m, phase.q, t)
            return start+(j1*slope+j2*curvature)

        if phase is self.sub:
            # The traction rises monotonically towards k V/a (without bound without creep), so yield is reachable
            # only if the exact net drive at the frozen strength is positive.
            if not self._net_drive(self.strength(x0[1])) > 0 or over(span) < 0:
                return span, None
            lower, upper = _bisect(lambda t: over(t) >= 0, 0., span)
            return upper, ("yield", lower, upper)
        cuts = [0., span]
        if phase is self.softening:
            turn = _turning_time(slope, curvature, phase.q)
            if turn is not None and 0 < turn < span:
                cuts = [0., turn, span]
        # In the residual phase the traction relaxes monotonically (decoupled scalar), so one piece suffices.
        unload = None
        for lower, upper in zip(cuts, cuts[1:]):
            if over(upper) <= 0:
                unload = _bisect(lambda t: over(t) <= 0, lower, upper)
                break
        if phase is self.softening:
            limit = span if unload is None else unload[1]
            target = self.law.softening_history
            if at(limit)[1] >= target:          # history does not decrease while the overstress is nonnegative
                lower, upper = _bisect(lambda t: at(t)[1] >= target, 0., limit)
                return upper, ("softening_complete", lower, upper)
        if unload is not None:
            return unload[1], ("unload",)+unload
        return span, None

    def _account(self, phase, x0, rate, bent, t, x1, totals):
        """Add one exact segment's work, stored-energy change and dissipations; return its balance residual.

        Dissipations are positive Gauss integrals of the exact solution, never a residual set to close a balance.
        """
        pieces = min(POLICY["maximum_segments"],
                     max(1, math.ceil((abs(phase.m)+phase.q)*t/POLICY["subinterval_exponent"])))
        step = t/pieces
        plastic = phase is not self.sub
        start, slope, curvature = self._overstress_path(phase, x0, rate, bent)
        sum_tau = sum_tau2 = sum_tau_over = sum_over2 = 0.
        for j in range(pieces):
            for node, weight in GAUSS:
                _, _, j1, j2 = _coefficients(phase.m, phase.q, step*(j+(node+1)/2))
                tau = x0[0]+(j1*rate[0]+j2*bent[0])          # the tau component of _at, sharing J1 and J2
                sum_tau += weight*tau
                sum_tau2 += weight*tau*tau
                if plastic:
                    over = start+(j1*slope+j2*curvature)
                    sum_tau_over += weight*tau*over
                    sum_over2 += weight*over*over
        half = step/2
        load, width, eta = self.loading, self.law.band_width_m, self.law.plastic_viscosity_pa_s
        dk = x1[1]-x0[1]
        part = dict(
            work_j_m2=load.loading_rate_m_s*sum_tau*half,
            stored_change_j_m2=(x1[0]-x0[0])*(x1[0]+x0[0])/(2*load.stiffness_pa_m),
            creep_dissipation_j_m2=(0. if load.creep_viscosity_pa_s is None
                                    else width/load.creep_viscosity_pa_s*sum_tau2*half),
            plastic_dissipation_j_m2=width/eta*sum_tau_over*half if plastic else 0.,
            overstress_dissipation_j_m2=width/eta*sum_over2*half if plastic else 0.,
            breakdown_dissipation_j_m2=(width*dk*((self.peak_pa-self.residual_pa)-self.softening_pa*(x0[1]+x1[1])/2)
                                        if phase is self.softening else 0.),
            residual_friction_dissipation_j_m2=width*self.residual_pa*dk if plastic else 0.,
            plastic_slip_m=width*dk)
        mechanical = (part["work_j_m2"], -part["stored_change_j_m2"], -part["creep_dissipation_j_m2"],
                      -part["plastic_dissipation_j_m2"])
        split = (part["plastic_dissipation_j_m2"], -part["overstress_dissipation_j_m2"],
                 -part["breakdown_dissipation_j_m2"], -part["residual_friction_dissipation_j_m2"])
        if not all(math.isfinite(value) for value in part.values()):
            raise Refusal(RANGE, "segment accounts not representable")      # a NaN would pass the comparisons below
        residual = 0.
        for terms in (mechanical, split):
            scale = math.fsum(abs(term) for term in terms)
            if scale:
                residual = max(residual, abs(math.fsum(terms))/scale)
        if (residual > POLICY["energy_relative"] or part["creep_dissipation_j_m2"] < 0
                or part["overstress_dissipation_j_m2"] < 0):
            raise Refusal(BALANCE, "segment work, stored energy and dissipation do not balance")
        for key, value in part.items():
            totals[key] += value
        return residual

    def advance(self, state, dt):
        """Exact evolution over dt: events with brackets, bond states and cumulative accounts, totals and the final
        bond state.

        The input state is not modified; stored traction is carried through every event and never reset. History
        added here is produced inside the support (the loading was checked on preparation), so an empty history
        becomes INSIDE, while a nonzero history keeps its declared record: an advance never recertifies it.
        """
        if type(state) is not State:
            raise Refusal(INVALID, "typed State required")
        dt = _real(dt, "interval", positive=True)
        end_time = state.time_s+dt
        if not end_time > state.time_s:
            raise Refusal(RANGE, "interval not representable at this clock")
        x, elapsed, segments, worst = (state.traction_pa, state.history), 0., 0, 0.
        totals, events = dict.fromkeys(ACCOUNTS, 0.), []
        support = "INSIDE" if state.history == 0 else state.history_support
        temperature, pressure = self.loading.temperature_k, self.loading.effective_pressure_pa
        while elapsed < dt:
            segments += 1
            if segments > POLICY["maximum_segments"]:
                raise Refusal(RANGE, "exact segment budget exhausted")
            phase = self._phase_of(x)
            rate = self._rate(phase, x)
            bent = self._bend(phase, rate)
            remaining = dt-elapsed
            bound = abs(phase.m)+phase.q
            span = remaining if bound*remaining <= POLICY["maximum_exponent"] else POLICY["maximum_exponent"]/bound
            t, event = self._next_event(phase, x, rate, bent, span)
            x1 = self._at(phase, x, rate, bent, t)
            worst = max(worst, self._account(phase, x, rate, bent, t, x1, totals))
            if event is not None:
                if event[0] == "softening_complete":
                    x1 = (x1[0], self.law.softening_history)
                else:                                   # yield or unload: sit exactly on the yield surface
                    x1 = (self.strength(x1[1]), x1[1])
                begin = state.time_s+elapsed
                events.append(dict(event=event[0], time_s=begin+t, bracket_s=[begin+event[1], begin+event[2]],
                                   traction_pa=x1[0], history=x1[1], phase=phase.name,
                                   bond_state=self.law.bond_state(x1[1], temperature, pressure,
                                                                  history_support=support),
                                   accounts=dict(totals)))
            x = x1
            elapsed = dt if t >= remaining else elapsed+t
        tau = x[0]
        if tau < 0:
            if -tau > POLICY["closed_form_relative"]*max(state.traction_pa, self.peak_pa):
                raise Refusal(RANGE, "negative traction: reverse shear is outside this slice")
            tau = 0.                                    # rounding of an exactly decaying traction, not a clip
        final = State(tau, x[1], end_time, support)
        return dict(state=final, events=events, accounts=totals, balance_relative_residual=worst,
                    bond_state=self.law.bond_state(final.history, temperature, pressure,
                                                   history_support=final.history_support),
                    stability_ratio=self.stability_ratio(), elasticity_retained=True)


def rate_independent_reference(law, loading, traction_pa):
    """The eta_p -> 0 limit without creep, from a start at or below peak: slip-weakening displacements and energies."""
    if type(law) is not SofteningLaw or type(loading) is not Loading:
        raise Refusal(INVALID, "typed SofteningLaw and Loading required")
    if loading.creep_viscosity_pa_s is not None:
        raise Refusal(INVALID, "the rate-independent reference has no creep branch")
    peak, residual = law.yields(loading.effective_pressure_pa)
    tau = _real(traction_pa, "traction", nonnegative=True)
    if tau > peak:
        raise Refusal(INVALID, "start at or below the peak yield")
    k, slip = loading.stiffness_pa_m, law.breakdown_slip_m()
    soft = (peak-residual)/slip
    out = dict(yield_loading_m=(peak-tau)/k, softening_stiffness_pa_m=soft, stability_ratio=k/soft,
               breakdown_energy_j_m2=(peak-residual)*slip/2, strength_work_to_completion_j_m2=(peak+residual)*slip/2,
               residual_friction_to_completion_j_m2=residual*slip)
    if k > soft:
        out.update(stable=True, completion_loading_after_yield_m=slip*(1-soft/k), released_excess_j_m2=0.)
    else:
        # Energy an arrest at the residual equilibrium would release beyond breakdown and residual friction:
        # a dynamic or viscoplastic resolution must own it (method section 5).
        out.update(stable=False, completion_loading_after_yield_m=0.,
                   released_excess_j_m2=(peak-residual)/2*((peak-residual)/k-slip))
    if not all(math.isfinite(value) for value in out.values() if type(value) is float):
        raise Refusal(RANGE, "rate-independent reference quantities not representable")
    return out


# ----------------------------------------------------------------------------- surface form

def surface_projection(stress_pa, normal, jump_m, pore_pressure_pa=0.):
    """Frame-indifferent scalars of one closed surface element in plane strain (method section 3.5).

    t = sigma n; shear traction t.m and slip [u].m use m = n turned by +90 degrees. An opening (or interpenetrating)
    jump is refused: a void, fluid or magma filling would need accounts that no owner supplies. A traction or jump
    component outside the double range is refused before any decision, never returned as NaN or infinity.
    """
    try:
        (sxx, sxy), (syx, syy) = stress_pa
        nx, ny = normal
        ju, jv = jump_m
    except (TypeError, ValueError):
        raise Refusal(INVALID, "a 2x2 stress, a 2-vector normal and a 2-vector jump are required") from None
    sxx, sxy, syx, syy = (_real(value, "stress") for value in (sxx, sxy, syx, syy))
    nx, ny, ju, jv = (_real(value, "vector component") for value in (nx, ny, ju, jv))
    pore = _real(pore_pressure_pa, "pore pressure", nonnegative=True)
    if abs(sxy-syx) > POLICY["closed_form_relative"]*max(abs(sxx), abs(sxy), abs(syx), abs(syy)):
        raise Refusal(INVALID, "the stress must be symmetric")
    if abs(math.hypot(nx, ny)-1) > POLICY["closed_form_relative"]:
        raise Refusal(INVALID, "a unit normal is required")
    mx, my = -ny, nx
    tx, ty = sxx*nx+sxy*ny, syx*nx+syy*ny
    normal_traction, shear = tx*nx+ty*ny, tx*mx+ty*my
    opening, slip = ju*nx+jv*ny, ju*mx+jv*my
    if not all(math.isfinite(value) for value in (tx, ty, normal_traction, shear, opening, slip)):
        raise Refusal(RANGE, "surface traction or jump components not representable")
    if abs(opening) > POLICY["closed_form_relative"]*max(abs(slip), abs(opening)):
        raise Refusal(OPENING, "an admitted contact stays closed: opening needs a void, fluid or magma account "
                      "that is not owned here")
    return dict(normal_traction_pa=normal_traction, shear_traction_pa=abs(shear),
                effective_pressure_pa=max(-normal_traction-pore, 0.), slip_m=abs(slip),
                shear_sense=(shear > 0)-(shear < 0), slip_sense=(slip > 0)-(slip < 0))


# ----------------------------------------------------------------------------- bonded section connectivity

def _section(cells, contacts, anchors):
    """Validate a declared section: cells {id: {material, bond}}, contacts [(id, id, face)], anchors left/right."""
    if type(cells) is not dict or not cells:
        raise Refusal(SECTION, "cells must be a nonempty mapping")
    for key, cell in cells.items():
        if type(key) is not str or type(cell) is not dict:
            raise Refusal(SECTION, "cells map string identifiers to mappings")
        if set(cell) != CELL_FIELDS:
            raise Refusal(FIELD, "cells carry exactly a material and a bond state; thickness, fraction or cutoff "
                          "fields cannot decide connectivity")
        if cell["material"] not in MATERIALS or cell["bond"] not in BONDS:
            raise Refusal(SECTION, "unknown material or bond state")
    if type(contacts) not in (list, tuple):
        raise Refusal(SECTION, "contacts must be a sequence")
    edges = []
    for contact in contacts:
        if type(contact) not in (list, tuple) or len(contact) != 3:
            raise Refusal(SECTION, "each contact is (cell, cell, face state)")
        first, second, face = contact
        if (type(first) is not str or type(second) is not str or first not in cells or second not in cells
                or first == second or face not in FACES):
            raise Refusal(SECTION, "contacts join two distinct declared cells with a known face state")
        edges.append((first, second, face))
    if type(anchors) is not dict or set(anchors) != {"left", "right"}:
        raise Refusal(SECTION, "anchors are exactly left and right")
    sides = []
    for name in ("left", "right"):
        side = anchors[name]
        if (type(side) not in (list, tuple) or not side
                or any(type(key) is not str or key not in cells for key in side)):
            raise Refusal(SECTION, "each anchor side lists declared cells")
        sides.append(tuple(side))
    if set(sides[0]) & set(sides[1]):
        raise Refusal(SECTION, "anchor sides must be disjoint")
    return edges, sides[0], sides[1]


def _reaches(cells, edges, chosen, left, right, cell_ok, face_ok):
    usable = {key for key, cell in cells.items() if cell["material"] in chosen and cell_ok(cell["bond"])}
    neighbours = {key: [] for key in usable}
    for first, second, face in edges:
        if first in usable and second in usable and face_ok(face):
            neighbours[first].append(second)
            neighbours[second].append(first)
    targets = {key for key in right if key in usable}
    seen = {key for key in left if key in usable}
    frontier = list(seen)
    while frontier:
        key = frontier.pop()
        if key in targets:
            return True
        for other in neighbours[key]:
            if other not in seen:
                seen.add(other)
                frontier.append(other)
    return False


def connectivity(cells, contacts, anchors, selection, *, mode="bonded"):
    """CONNECTED, DISCONNECTED or UNRESOLVED between the anchors of the selected materials (method section 3.4).

    mode="bonded" is the law: BONDED cells across WELDED contacts, with unresolved states evaluated both ways.
    mode="set" uses every selected cell and contact (point-set adjacency). It is reported only to expose the
    wording issue of method section 10 and never decides an event.
    """
    edges, left, right = _section(cells, contacts, anchors)
    if selection not in SELECTIONS or mode not in ("bonded", "set"):
        raise Refusal(SECTION, "unknown selection or mode")
    chosen = SELECTIONS[selection]
    left = tuple(key for key in left if cells[key]["material"] in chosen)
    right = tuple(key for key in right if cells[key]["material"] in chosen)
    if not left or not right:
        raise Refusal(SECTION, "each side needs an anchor of the selected material")
    if mode == "set":
        linked = _reaches(cells, edges, chosen, left, right, lambda bond: True, lambda face: True)
        return "CONNECTED" if linked else "DISCONNECTED"
    if any(cells[key]["bond"] != "BONDED" for key in left+right):
        raise Refusal(SECTION, "anchors are declared intact tracked material")
    if _reaches(cells, edges, chosen, left, right, lambda bond: bond == "BONDED", lambda face: face == "WELDED"):
        return "CONNECTED"
    if not _reaches(cells, edges, chosen, left, right, lambda bond: bond != "BROKEN",
                    lambda face: face != "COHESIONLESS"):
        return "DISCONNECTED"
    return "UNRESOLVED"


def section_diagnostics(cells, contacts, anchors):
    """Bonded crust, mantle-lithosphere and union connectivity, with point-set union connectivity beside them."""
    out = {name: connectivity(cells, contacts, anchors, name) for name in SELECTIONS}
    out["set_union"] = connectivity(cells, contacts, anchors, "union", mode="set")
    return out


def classify_interval(before, after):
    """Compare two supplied bonded section diagnostics (method section 3.4); never a split.

    The record labels a change between two graph summaries supplied by the caller. It knows nothing of their times,
    footprint or physical history, so it is not a time- or footprint-bound regional event certificate, and
    RECONNECTED between supplied graphs is not a simulated healing or rejoining result.
    """
    for record in (before, after):
        if type(record) is not dict or any(record.get(key) not in CONNECTIVITY
                                           for key in ("crust", "mantle_lithosphere", "union")):
            raise Refusal(SECTION, "bonded crust, mantle-lithosphere and union diagnostics are required")
    first, last = before["union"], after["union"]
    if "UNRESOLVED" in (first, last):
        event = "UNRESOLVED"
    elif first == "DISCONNECTED":
        event = "INHERITED_DISCONNECTION" if last == "DISCONNECTED" else "RECONNECTED"
    elif last == "DISCONNECTED":
        event = "BRACKETED_UNION_LOSS"
    else:
        event = "NO_UNION_EVENT"
    return dict(union_event=event,
                crustal_milestone=before["crust"] == "CONNECTED" and after["crust"] == "DISCONNECTED",
                section_only=True, graph_comparison_only=True, plate_split_authorised=False,
                requires=list(REQUIREMENTS) if event == "BRACKETED_UNION_LOSS" else [])


def negative_example_thickness(opening, *, h_c, a, c, w):
    """The exact positive-thickness field of I01_SEPARATION_DECISION section 5, positive at every finite opening.

    Supplied only to show that no law or connectivity function here reads a thickness. The knee excess u - u_a and
    the linear branch are exact rationals of the represented inputs, rounded once, so a thin film cannot cancel to
    zero near the knee. A positive thickness that is not a normal double is refused: underflow must never look like
    a finite physical disconnection.
    """
    u, h_c, a, c, w = (_real(value, name) for value, name in
                       ((opening, "opening"), (h_c, "H_c"), (a, "a"), (c, "c"), (w, "w")))
    film = Fraction(a)*Fraction(w)
    if min(h_c, a, c, w) <= 0 or film >= h_c or u < 0:
        raise Refusal(INVALID, "the counterexample needs positive H_c, a, c, w with a w < H_c and a nonnegative opening")
    excess = Fraction(u)-Fraction(c)*(Fraction(h_c)-film)             # u - u_a
    try:
        if excess <= 0:
            thickness = float(Fraction(h_c)-Fraction(u)/Fraction(c))   # exactly H_c - u/c >= a w, rounded once
        else:
            thickness = float(film)*math.exp(-float(excess/(Fraction(c)*film)))
    except OverflowError:
        thickness = math.inf
    if not (math.isfinite(thickness) and thickness >= sys.float_info.min):
        raise Refusal(RANGE, "the exact thickness is positive but not representable as a normal double; zero is "
                      "never an admitted thickness")
    return thickness


# ----------------------------------------------------------------------------- predeclared controls

def check_case(spec):
    if (type(spec) is not dict or set(spec) != CASE_FIELDS or spec["schema"] != CASE_SCHEMA
            or spec["contract"] != CONTRACT or spec["policy"] != POLICY
            or spec["scientific_acceptance"] is not False or spec["event_authorised"] is not False):
        raise ValueError("case fields, schema, contract, policy or status differ from the executable")
    return spec


def load_case(path=None):
    return check_case(json.loads((ROOT/CASE if path is None else Path(path)).read_text(encoding="utf-8")))


def make_law(values, **changes):
    return SofteningLaw(**dict(values, **changes))


def make_loading(values, **changes):
    return Loading(**dict(values, **changes))


def _deadline(deadline):
    if deadline is not None and time.perf_counter() > deadline:
        raise RuntimeError("bounded campaign deadline exceeded")


def _near(actual, expected, relative=None):
    tolerance = POLICY["closed_form_relative"] if relative is None else relative
    return abs(actual-expected) <= tolerance*max(abs(actual), abs(expected), 1e-300)


def _root(function, lower, upper):
    """Bisection of a declared sign-changing bracket; independent of the kernel's phases and events."""
    low, high = function(lower), function(upper)
    if low == 0:
        return lower
    if high == 0:
        return upper
    if (low > 0) == (high > 0):
        raise ValueError("the declared bracket does not contain the root")
    for _ in range(200):
        middle = lower+(upper-lower)/2
        if not lower < middle < upper:
            break
        if (function(middle) > 0) == (low > 0):
            lower = middle
        else:
            upper = middle
    return lower+(upper-lower)/2


def _finish(checks, **data):
    return dict(passed=all(checks.values()), checks=checks, **data)


def law_control(spec, deadline):
    """Closed-form strengths, breakdown slip, energy and stiffness; pressure dependence; the bond-state table."""
    rc = spec["runnable_controls"]
    expected = rc["expected"]
    law = make_law(rc["law"])
    pressure = rc["stable_loading"]["effective_pressure_pa"]
    peak, residual = law.yields(pressure)
    friction = make_law(rc["law"], residual_friction_rad=rc["friction_softening"]["residual_friction_rad"])
    energies = [friction.fracture_energy_j_m2(value) for value in rc["friction_softening"]["pressures_pa"]]
    checks = dict(
        peak_yield=_near(peak, expected["peak_yield_pa"]),
        residual_yield=_near(residual, expected["residual_yield_pa"]),
        breakdown_slip=_near(law.breakdown_slip_m(), expected["breakdown_slip_m"]),
        fracture_energy=_near(law.fracture_energy_j_m2(pressure), expected["fracture_energy_j_m2"]),
        softening_stiffness=_near(law.softening_stiffness_pa_m(pressure), expected["softening_stiffness_pa_m"]),
        cohesion_only_energy_pressure_free=_near(law.fracture_energy_j_m2(2*pressure),
                                                 law.fracture_energy_j_m2(pressure)),
        friction_energy_rises_with_pressure=(all(_near(value, target) for value, target
                                                 in zip(energies, expected["friction_softening_energy_j_m2"]))
                                             and _near(energies[1]-energies[0],
                                                       expected["friction_softening_energy_difference_j_m2"])))
    bonds = {}
    for row in rc["bond_states"]:
        _deadline(deadline)
        found = make_law(rc["law"], **row.get("law_changes", {})).bond_state(
            row["history"], row["temperature_k"], row["effective_pressure_pa"], history_support=row["history_support"])
        bonds[row["id"]] = found
        checks["bond_"+row["id"]] = found == row["expected"]
    return _finish(checks, bond_states=bonds, friction_softening_energies_j_m2=energies)


def memory_control(spec, deadline):
    """Retained stored traction, exact yield and completion times, energy parts and time-subdivision parity."""
    rc = spec["runnable_controls"]
    expected, horizon = rc["expected"], rc["horizons_s"]
    law, load = make_law(rc["law"]), make_loading(rc["stable_loading"])
    op, start = Prepared(law, load), State(**rc["initial_state"])
    kept = op.advance(start, horizon["stable"])
    _deadline(deadline)
    forgotten = op.advance(State(0., 0.), horizon["forgotten"])
    _deadline(deadline)
    names = [event["event"] for event in kept["events"]]
    if names != ["yield", "softening_complete"]:
        return _finish(dict(event_sequence=False), events=names)
    k, v, width, eta = load.stiffness_pa_m, load.loading_rate_m_s, law.band_width_m, law.plastic_viscosity_pa_s
    s, residual = op.softening_pa, op.residual_pa
    block = expected["stable_completion"]
    rate = (k*width-s)/eta                                      # |g|, the decay rate of the stable softening mode
    right = law.softening_history*(k*width-s)**2/(eta*k*v)
    root = _root(lambda x: x-1+math.exp(-x)-right, *block["X_bracket"])
    closed_yield = (op.peak_pa-start.traction_pa)/(k*v)
    closed_completion = closed_yield+root/rate
    closed_traction = residual+(k*v/rate)*-math.expm1(-root)
    reference = rate_independent_reference(law, load, start.traction_pa)
    at_completion = kept["events"][1]
    parts = at_completion["accounts"]
    pieces, state, sums, events = rc["subdivisions"], start, dict.fromkeys(ACCOUNTS, 0.), []
    for _ in range(pieces):
        _deadline(deadline)
        part = op.advance(state, horizon["stable"]/pieces)
        state, events = part["state"], events+part["events"]
        for key in ACCOUNTS:
            sums[key] += part["accounts"][key]
    totals = kept["accounts"]
    gross = math.fsum(abs(totals[key]) for key in ACCOUNTS if key != "plastic_slip_m")
    tolerance = POLICY["event_relative"]
    ri = expected["rate_independent"]
    checks = dict(
        event_sequence=True,
        rate_equation=_near(right, block["right_hand_side"]),
        root_in_declared_bracket=block["X_bracket"][0] < root < block["X_bracket"][1],
        yield_time=(_near(kept["events"][0]["time_s"], closed_yield, tolerance)
                    and _near(closed_yield, expected["yield_time_retained_s"])),
        forgotten_yield=([event["event"] for event in forgotten["events"]] == ["yield"]
                         and _near(forgotten["events"][0]["time_s"], expected["yield_time_forgotten_s"], tolerance)),
        memory_advance=_near(forgotten["events"][0]["time_s"]-kept["events"][0]["time_s"],
                             expected["memory_advance_s"], tolerance),
        completion_time=_near(at_completion["time_s"], closed_completion, tolerance),
        traction_continuous_at_bond_loss=_near(at_completion["traction_pa"], closed_traction, tolerance),
        breakdown_is_fracture_energy=_near(parts["breakdown_dissipation_j_m2"], expected["fracture_energy_j_m2"],
                                           tolerance),
        residual_friction=_near(parts["residual_friction_dissipation_j_m2"],
                                expected["residual_friction_to_completion_j_m2"], tolerance),
        strength_work=_near(parts["breakdown_dissipation_j_m2"]+parts["residual_friction_dissipation_j_m2"],
                            expected["strength_work_to_completion_j_m2"], tolerance),
        bond_before=law.bond_state(start.history, load.temperature_k, load.effective_pressure_pa,
                                   history_support=start.history_support) == "BONDED",
        bond_lost_at_completion=([event["bond_state"] for event in kept["events"]] == ["BONDED", "BROKEN"]),
        bond_after=kept["bond_state"] == "BROKEN",
        stability_ratio=_near(kept["stability_ratio"], expected["stability_ratio_stable"]),
        rate_independent_reference=(reference["stable"] is True
                                    and _near(reference["yield_loading_m"], ri["yield_loading_m"])
                                    and _near(reference["completion_loading_after_yield_m"],
                                              ri["completion_loading_after_yield_m"])
                                    and _near(reference["completion_loading_after_yield_m"]/v,
                                              ri["completion_time_after_yield_s"])),
        viscoplastic_lag=(_near(closed_completion-closed_yield-ri["completion_time_after_yield_s"],
                                -math.expm1(-root)/rate, 1e-9)
                          and _near(1/rate, ri["viscoplastic_lag_s"])),
        balance=max(kept["balance_relative_residual"], forgotten["balance_relative_residual"])
                <= POLICY["energy_relative"],
        subdivision_state=(_near(state.traction_pa, kept["state"].traction_pa, tolerance)
                           and _near(state.history, kept["state"].history, tolerance)),
        subdivision_accounts=(all(abs(sums[key]-totals[key]) <= POLICY["energy_relative"]*gross
                                  for key in ACCOUNTS if key != "plastic_slip_m")
                              and _near(sums["plastic_slip_m"], totals["plastic_slip_m"], tolerance)),
        subdivision_events=([event["event"] for event in events] == names
                            and all(_near(first["time_s"], second["time_s"], tolerance)
                                    for first, second in zip(events, kept["events"]))))
    return _finish(checks, events=[{key: event[key] for key in ("event", "time_s", "bracket_s", "traction_pa",
                                                               "bond_state")}
                                   for event in kept["events"]],
                   completion_root=root, closed_completion_s=closed_completion,
                   accounts_at_completion=parts, final_accounts=totals,
                   balance_relative_residual=kept["balance_relative_residual"])


def _exact_yield_checks(rc, deadline):
    """The review reproducer: a state exactly on the yield surface under positive, zero and negative net drive.

    With k = w_s = eta_v = eta_p = kappa_c = 1, Y0 = 2 and Yr = 0, the net drive is delta = V - 2 as represented and
    the softening phase gives kappa(t) = delta/2 (cosh(sqrt(2) t) - 1) and o(t) = delta sinh(sqrt(2) t)/sqrt(2).
    """
    exact = rc["exact_yield"]
    law, start, horizon = make_law(exact["law"]), State(**exact["state"]), exact["horizon_s"]
    peak = law.yields(exact["loading"]["effective_pressure_pa"])[0]
    runs = {}
    for name, value in exact["loading_rates_m_s"].items():
        _deadline(deadline)
        runs[name] = Prepared(law, make_loading(exact["loading"], loading_rate_m_s=value)).advance(start, horizon)
    rates = exact["loading_rates_m_s"]
    delta = rates["positive"]-peak                              # exact: both lie within a factor of two
    completion = math.acosh(1+2*law.softening_history/delta)/math.sqrt(2)
    positive, zero, negative = runs["positive"], runs["zero"], runs["negative"]
    tolerance = POLICY["event_relative"]
    events = positive["events"]
    relaxed = rates["negative"]+(peak-rates["negative"])*math.exp(-horizon)
    checks = dict(
        exact_positive_drive_completes=(
            [event["event"] for event in events] == ["softening_complete"]
            and events[0]["bond_state"] == "BROKEN" and positive["bond_state"] == "BROKEN"
            and exact["completion_bracket_s"][0] < completion < exact["completion_bracket_s"][1]
            and _near(events[0]["time_s"], completion, tolerance)
            and _near(events[0]["traction_pa"], math.sqrt(2*(1+delta)), tolerance)),
        exact_zero_drive_stationary=(zero["events"] == [] and zero["bond_state"] == "BONDED"
                                     and (zero["state"].traction_pa, zero["state"].history) == (peak, 0.)),
        exact_negative_drive_relaxes=(negative["events"] == [] and negative["state"].history == 0
                                      and negative["bond_state"] == "BONDED"
                                      and _near(negative["state"].traction_pa, relaxed)),
        exact_balance=max(run["balance_relative_residual"] for run in runs.values()) <= POLICY["energy_relative"])
    return checks, dict(exact_yield_completion_s=completion,
                        exact_yield_events=[{key: event[key] for key in ("event", "time_s", "bracket_s", "traction_pa",
                                                                         "bond_state")} for event in events])


def unstable_control(spec, deadline):
    """Softer surroundings than k_soft: the viscoplastic transient's exact completion and the unstable reference;
    the exact-yield reproducer, also below k_soft, under positive, zero and negative net drive."""
    rc = spec["runnable_controls"]
    expected, block = rc["expected"], rc["expected"]["unstable_completion"]
    law = make_law(rc["law"])
    load = make_loading(rc["stable_loading"], stiffness_pa_m=rc["unstable_stiffness_pa_m"])
    op, start = Prepared(law, load), State(**rc["initial_state"])
    run = op.advance(start, rc["horizons_s"]["unstable"])
    _deadline(deadline)
    names = [event["event"] for event in run["events"]]
    if names != ["yield", "softening_complete"]:
        return _finish(dict(event_sequence=False), events=names)
    exact_checks, exact_data = _exact_yield_checks(rc, deadline)
    k, v, width, eta = load.stiffness_pa_m, load.loading_rate_m_s, law.band_width_m, law.plastic_viscosity_pa_s
    s = op.softening_pa
    rate = (s-k*width)/eta                                      # g > 0: the regularised softening instability
    right = law.softening_history*(s-k*width)**2/(eta*k*v)
    root = _root(lambda x: math.expm1(x)-x-right, *block["X_bracket"])
    closed_yield = (op.peak_pa-start.traction_pa)/(k*v)
    reference = rate_independent_reference(law, load, start.traction_pa)
    tolerance = POLICY["event_relative"]
    checks = dict(
        event_sequence=True,
        rate_equation=_near(right, block["right_hand_side"]),
        root_in_declared_bracket=block["X_bracket"][0] < root < block["X_bracket"][1],
        yield_time=(_near(run["events"][0]["time_s"], closed_yield, tolerance)
                    and _near(closed_yield, block["yield_time_s"])),
        completion_time=_near(run["events"][1]["time_s"], closed_yield+root/rate, tolerance),
        stability_ratio=_near(run["stability_ratio"], expected["stability_ratio_unstable"]),
        rate_independent_unstable=(reference["stable"] is False
                                   and _near(reference["released_excess_j_m2"],
                                             expected["rate_independent"]["unstable_released_excess_j_m2"])),
        breakdown_is_fracture_energy=_near(run["events"][1]["accounts"]["breakdown_dissipation_j_m2"],
                                           expected["fracture_energy_j_m2"], tolerance),
        balance=run["balance_relative_residual"] <= POLICY["energy_relative"],
        bond_after=run["bond_state"] == "BROKEN" and run["events"][1]["bond_state"] == "BROKEN",
        **exact_checks)
    return _finish(checks, completion_root=root,
                   events=[{key: event[key] for key in ("event", "time_s", "bracket_s", "bond_state")}
                           for event in run["events"]],
                   final_accounts=run["accounts"], **exact_data)


def creep_control(spec, deadline):
    """Creep never removes cohesion; the physical width sets the regime; mixed creep-plastic bands still break."""
    rc = spec["runnable_controls"]
    expected, creep, horizon = rc["expected"], rc["creep"], rc["horizons_s"]
    law, start = make_law(rc["law"]), State(**rc["initial_state"])
    base = rc["stable_loading"]
    k, v = base["stiffness_pa_m"], base["loading_rate_m_s"]

    def run(width, viscosity, length):
        _deadline(deadline)
        chosen = law if width == law.band_width_m else make_law(rc["law"], band_width_m=width)
        op = Prepared(chosen, make_loading(base, creep_viscosity_pa_s=viscosity))
        relax = k*width/viscosity
        steady = k*v/relax
        return op, op.advance(start, length), relax, steady

    hot_op, hot, hot_relax, hot_steady = run(law.band_width_m, creep["hot_viscosity_pa_s"], horizon["hot_creep"])
    narrow_op, narrow, narrow_relax, narrow_steady = run(creep["narrow_band_width_m"], creep["hot_viscosity_pa_s"],
                                                         horizon["narrow_creep"])
    cold_op, cold, cold_relax, cold_steady = run(law.band_width_m, creep["cold_viscosity_pa_s"], horizon["cold_creep"])
    closed_hot = hot_steady+(start.traction_pa-hot_steady)*math.exp(-hot_relax*horizon["hot_creep"])
    narrow_yield = math.log((narrow_steady-start.traction_pa)/(narrow_steady-narrow_op.peak_pa))/narrow_relax
    cold_yield = math.log((cold_steady-start.traction_pa)/(cold_steady-cold_op.peak_pa))/cold_relax
    tolerance = POLICY["event_relative"]
    names = lambda result: [event["event"] for event in result["events"]]
    checks = dict(
        hot_steady=(_near(hot_steady, expected["hot_creep"]["steady_traction_pa"])
                    and _near(hot_relax, expected["hot_creep"]["relaxation_rate_s"])),
        hot_never_yields=(hot["events"] == [] and hot["state"].history == 0 and hot["bond_state"] == "BONDED"
                          and max(start.traction_pa, hot_steady) < hot_op.peak_pa),
        hot_traction=_near(hot["state"].traction_pa, closed_hot, tolerance),
        narrow_steady=(_near(narrow_steady, expected["narrow_creep"]["steady_traction_pa"])
                       and _near(narrow_relax, expected["narrow_creep"]["relaxation_rate_s"])),
        narrow_yields=names(narrow)[:1] == ["yield"] and _near(narrow["events"][0]["time_s"], narrow_yield, tolerance),
        narrow_breaks=("softening_complete" in names(narrow)
                       and narrow["bond_state"] == expected["narrow_creep"]["final_bond"]),
        cold_steady=(_near(cold_steady, expected["cold_creep"]["steady_traction_pa"])
                     and _near(cold_relax, expected["cold_creep"]["relaxation_rate_s"])),
        cold_yields=names(cold)[:1] == ["yield"] and _near(cold["events"][0]["time_s"], cold_yield, tolerance),
        cold_breaks=("softening_complete" in names(cold)
                     and cold["bond_state"] == expected["cold_creep"]["final_bond"]),
        creep_dissipates=cold["accounts"]["creep_dissipation_j_m2"] > 0 and hot["accounts"]["plastic_dissipation_j_m2"] == 0,
        balance=max(result["balance_relative_residual"] for result in (hot, narrow, cold)) <= POLICY["energy_relative"])
    return _finish(checks, hot_final_traction_pa=hot["state"].traction_pa, narrow_events=names(narrow),
                   cold_events=names(cold), narrow_yield_s=narrow_yield, cold_yield_s=cold_yield,
                   cold_accounts=cold["accounts"])


def objectivity_control(spec, deadline):
    """Surface scalars are unchanged by superposed rotations; zero jump means no slip; opening is refused."""
    surface = spec["runnable_controls"]["surface"]
    base = surface_projection(surface["stress_pa"], surface["normal"], surface["jump_m"])
    stress_scale = max(abs(value) for row in surface["stress_pa"] for value in row)
    slip_scale = math.hypot(*surface["jump_m"])
    checks = {"components": all(_near(base[key], value) for key, value in surface["expected"].items())}
    for angle in surface["rotations_rad"]:
        _deadline(deadline)
        c, s = math.cos(angle), math.sin(angle)
        turn = ((c, -s), (s, c))
        stress = [[math.fsum(turn[i][p]*surface["stress_pa"][p][r]*turn[j][r] for p in range(2) for r in range(2))
                   for j in range(2)] for i in range(2)]
        normal = [turn[i][0]*surface["normal"][0]+turn[i][1]*surface["normal"][1] for i in range(2)]
        jump = [turn[i][0]*surface["jump_m"][0]+turn[i][1]*surface["jump_m"][1] for i in range(2)]
        turned = surface_projection(stress, normal, jump)
        same = True
        for key, value in base.items():
            if key.endswith("_sense"):
                same = same and turned[key] == value
            else:
                scale = slip_scale if key == "slip_m" else stress_scale
                same = same and abs(turned[key]-value) <= POLICY["closed_form_relative"]*scale
        checks["rotation_%+.2f" % angle] = same
    checks["rigid_motion_no_slip"] = surface_projection(surface["stress_pa"], surface["normal"], [0., 0.])["slip_m"] == 0
    try:
        surface_projection(surface["stress_pa"], surface["normal"], [60., 80.])
    except Refusal as exc:
        checks["opening_refused"] = exc.code == OPENING
    else:
        checks["opening_refused"] = False
    return _finish(checks, components=base)


def sections_control(spec, deadline):
    """Bonded versus point-set connectivity on the declared sections, and the interval records."""
    rc = spec["runnable_controls"]
    found, checks = {}, {}
    for name, section in rc["sections"].items():
        _deadline(deadline)
        found[name] = section_diagnostics(section["cells"], section["contacts"], section["anchors"])
        checks["section_"+name] = found[name] == section["expected"]
    for row in rc["intervals"]:
        record = classify_interval(found[row["before"]], found[row["after"]])
        checks["interval_"+row["id"]] = (record["union_event"] == row["expected"]["union_event"]
                                         and record["crustal_milestone"] == row["expected"]["crustal_milestone"]
                                         and record["plate_split_authorised"] is False)
    checks["wording_issue_demonstrated"] = all(found[name]["set_union"] == "CONNECTED"
                                               and found[name]["union"] == "DISCONNECTED"
                                               for name in ("cohesionless_surface", "broken_band"))
    return _finish(checks, diagnostics=found)


def negative_control(spec, deadline):
    """The exact positive-thickness counterexample stays connected; a supplied thickness is refused, never read."""
    rc = spec["runnable_controls"]
    ours = rc["negative_example"]
    ladder = json.loads((ROOT/DECISION_CASE).read_text(encoding="utf-8"))["negative_ladder"]
    copied = ("H_c_m", "a", "c", "w_m", "c_w", "u_a_m", "thickness_levels_m", "opening_levels_m",
              "false_extrapolated_limit_m", "halved_w_m")
    shape = dict(h_c=ours["H_c_m"], a=ours["a"], c=ours["c"])
    thickness = [negative_example_thickness(u, w=ours["w_m"], **shape) for u in ours["opening_levels_m"]]
    limit = ours["false_extrapolated_limit_m"]
    at_limit = negative_example_thickness(limit, w=ours["w_m"], **shape)
    halved = negative_example_thickness(limit, w=ours["halved_w_m"], **shape)
    film = rc["sections"][ours["film_section"]]
    found = section_diagnostics(film["cells"], film["contacts"], film["anchors"])
    record = classify_interval(found, found)
    cells = {key: dict(cell) for key, cell in film["cells"].items()}
    cells["Fc"]["thickness_m"] = at_limit
    try:
        connectivity(cells, film["contacts"], film["anchors"], "union")
    except Refusal as exc:
        refused = exc.code == FIELD
    else:
        refused = False
    try:                        # positive mathematically, but below the double range: refused, never 0.0
        negative_example_thickness(ours["unrepresentable_opening_m"], w=ours["w_m"], **shape)
    except Refusal as exc:
        underflow_refused = exc.code == RANGE
    else:
        underflow_refused = False
    _deadline(deadline)
    checks = dict(
        copied_from_decision_case=all(ladder[key] == ours[key] for key in copied),
        ladder_thicknesses_positive=(thickness == [float(value) for value in ours["thickness_levels_m"]]
                                     and min(thickness) > 0),
        positive_at_false_limit=at_limit > 0 and _near(at_limit, ours["w_m"]*math.exp(-1)),
        positive_with_halved_width=halved > 0 and _near(halved, ours["halved_w_m"]*math.exp(-1)),
        film_connected=found["union"] == ours["expected_union"],
        no_event=record["union_event"] == ours["expected_interval"] and record["plate_split_authorised"] is False,
        thickness_field_refused=refused,
        unrepresentable_thickness_refused=underflow_refused)
    return _finish(checks, thickness_at_false_limit_m=at_limit, halved_width_thickness_m=halved)


def refusals_control(spec, deadline):
    """Every declared refusal raises its stable code through the actual admission logic."""
    rc = spec["runnable_controls"]
    observed = {}
    for row in rc["refusals"]:
        _deadline(deadline)
        target = row["target"]
        try:
            if target == "law":
                make_law(rc["law"], **row["changes"])
            elif target == "loading":
                make_loading(rc["stable_loading"], **row["changes"])
            elif target == "prepared":
                Prepared(make_law(rc["law"]), make_loading(rc["stable_loading"], **row["changes"]))
            elif target == "section":
                section = json.loads(json.dumps(rc["sections"][row["section"]]))   # private deep copy
                if "field" in row:
                    section["cells"][row["cell"]][row["field"][0]] = row["field"][1]
                if "left_anchor" in row:
                    section["anchors"]["left"].append(row["left_anchor"])
                connectivity(section["cells"], section["contacts"], section["anchors"], "union")
            elif target == "surface":
                surface = rc["surface"]
                surface_projection(row.get("stress_pa", surface["stress_pa"]), row.get("normal", surface["normal"]),
                                   row["jump_m"])
            else:
                raise ValueError("unknown refusal target "+str(target))
            observed[row["id"]] = "ACCEPTED"
        except Refusal as exc:
            observed[row["id"]] = exc.code
    checks = {row["id"]: observed[row["id"]] == row["expected"] for row in rc["refusals"]}
    return _finish(checks, observed=observed)


def timing_control(spec, deadline):
    """Raw interleaved timings of identical advances with the preparation reused or rebuilt; no saving claimed."""
    rc = spec["runnable_controls"]
    law, load = make_law(rc["law"]), make_loading(rc["stable_loading"])
    state, interval = State(**rc["timing_state"]), rc["horizons_s"]["timing"]
    prepared = Prepared(law, load)
    samples, results = {"prepared": [], "rebuilt": []}, {}
    for repeat in range(POLICY["timing_repetitions"]):
        for mode in (("prepared", "rebuilt") if repeat % 2 == 0 else ("rebuilt", "prepared")):
            _deadline(deadline)
            begin = time.perf_counter()
            for _ in range(POLICY["timing_calls"]):
                op = prepared if mode == "prepared" else Prepared(law, load)
                results[mode] = op.advance(state, interval)
            samples[mode].append(time.perf_counter()-begin)
    medians = {key: statistics.median(value) for key, value in samples.items()}
    checks = dict(reuse_parity=results["prepared"] == results["rebuilt"],
                  finite_nonnegative=all(math.isfinite(value) and value >= 0
                                         for value in samples["prepared"]+samples["rebuilt"]))
    return _finish(checks, samples_seconds=samples, median_seconds=medians,
                   median_difference_seconds=medians["rebuilt"]-medians["prepared"],
                   scope="%d identical local advances per sample; setup reuse only, not a solver or world speedup"
                         % POLICY["timing_calls"])


CONTROLS = (("law", law_control), ("retained_memory", memory_control), ("unstable_softening", unstable_control),
            ("creep_regime", creep_control), ("objectivity", objectivity_control), ("sections", sections_control),
            ("negative_example", negative_control), ("refusals", refusals_control), ("timing", timing_control))


# ----------------------------------------------------------------------------- bindings and receipt

def digest(name):
    return hashlib.sha256((ROOT/name).read_bytes()).hexdigest()


def bindings():
    return {name: digest(name) for name in NEW_FILES+RETAINED}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        result = dict(schema=EVIDENCE_SCHEMA, status="INCOMPLETE", scientific_acceptance=False, contract=CONTRACT,
                      resolved_neck=False, event_authorised=False, mc01_closed=False,
                      runtime=dict(python=platform.python_version(), numpy=np.__version__,
                                   system=platform.system(), machine=platform.machine()),
                      controls={})
        start = time.perf_counter()
        try:
            before = bindings()
            result["source_sha256"] = before
            spec = load_case()
            deadline = start+POLICY["maximum_seconds"]      # cooperative budget, checked inside every control
            for name, control in CONTROLS:
                begin = time.perf_counter()
                try:
                    data = control(spec, deadline)
                    _deadline(deadline)                     # an overrunning control is not recorded as a pass
                    result["controls"][name] = dict(status="PASS" if data["passed"] else "FAIL",
                                                    seconds=time.perf_counter()-begin, **data)
                except (ValueError, RuntimeError, ArithmeticError, KeyError, TypeError, IndexError) as exc:
                    result["controls"][name] = dict(status="FAIL", seconds=time.perf_counter()-begin,
                                                    error_type=type(exc).__name__,
                                                    error=str(exc).replace(str(ROOT), "TECTONICS_ROOT"))
            result["source_unchanged"] = before == bindings()
            passed = (result["source_unchanged"] and len(result["controls"]) == len(CONTROLS)
                      and all(control["status"] == "PASS" for control in result["controls"].values()))
            result["status"] = PASS if passed else "FAIL"
        except Exception as exc:
            # Deliberately do not publish arbitrary exception paths or tracebacks.
            result.update(status="FAIL", error_type=type(exc).__name__)
            if isinstance(exc, (ValueError, RuntimeError)):
                result["error"] = str(exc).replace(str(ROOT), "TECTONICS_ROOT")
        result["elapsed_seconds_after_imports"] = time.perf_counter()-start
        try:
            body = json.dumps(result, indent=2, allow_nan=False)
        except (TypeError, ValueError) as exc:              # never leave a partial or non-finite record behind
            result = dict(schema=EVIDENCE_SCHEMA, status="FAIL", scientific_acceptance=False,
                          runtime=result["runtime"], error_type=type(exc).__name__,
                          error="evidence record not serialisable: "+str(exc)[:200], controls={},
                          elapsed_seconds_after_imports=result["elapsed_seconds_after_imports"])
            body = json.dumps(result, indent=2, allow_nan=False)
        stream.write(body+"\n")
    print(json.dumps({key: result.get(key) for key in ("status", "elapsed_seconds_after_imports", "error")}
                     | {"controls": {name: control["status"] for name, control in result["controls"].items()}}))
    return 0 if result["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
