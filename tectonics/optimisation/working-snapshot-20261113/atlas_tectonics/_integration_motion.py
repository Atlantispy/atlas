"""I02.2a package owner of the I01 force/drag/column motion root. WORKING NON-CANON.

F = D v + F_column(v/width, kappa) on the admitted monotone branch, by safeguarded Newton in log scaled rate or by
SciPy Brent, with disjoint drag and column power accounts. Moved without change from
tools/check_i01_motion_coupling.py, which re-exports these same objects and keeps its fixed-temperature evolution,
case loading and campaign.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.optimize import brentq

from . import _integration_weakening as w

FORCE_TOL = 1e-10
MAX_ITERATIONS = 96


@dataclass(frozen=True)
class Drive:
    """Generalised external force, disjoint drag and physical belt width.

    F [N/m], D [Pa s], v [m/s], width [m]. D is NOT basal eta/H [Pa s/m].
    The scalar degree of freedom is signed edge separation in a declared frame.
    """
    force_n_m: float
    drag_pa_s: float
    width_m: float

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = w.number(getattr(self, name), name, positive=name != "force_n_m")
            object.__setattr__(self, name, value)
        if self.force_n_m:
            w.positive(abs(self.force_n_m) / self.drag_pa_s / self.width_m,
                       "representable drag-only axial rate")


def solve(prep, law, kappa, drive, *, method="newton", warm=None, deadline=None):
    """Solve F=Dv+Fcolumn(v/width,kappa) on the admitted monotone branch.

    The analytic bracket is x=|v|/(|F|/D) in [0,1]. Zero is evaluated as the
    continuous zero-stress/zero-dissipation limit, never by log(0).
    warm is an initial guess ONLY, not a cached result; every state is resolved.
    """
    if type(prep) is not w.PreparedColumn or type(law) is not w.WeakeningLaw or type(drive) is not Drive:
        raise ValueError("typed preparation, law and drive required")
    if method not in ("newton", "brent"):
        raise ValueError("unknown motion solver")
    kappa = w.history_array(prep, kappa)
    law.certify(prep)
    w.check_deadline(deadline)
    target = abs(drive.force_n_m)
    if target == 0:
        return dict(velocity_m_s=0., rate=0., force=0., force_relative=0.,
                    drive_power_w_m=0., drag_power_w_m=0., creep_power_w_m=0.,
                    plastic_power_w_m=0., power_relative=0., kdot=np.zeros(prep.size),
                    x=None, evaluations=0, iterations=0)
    sign = math.copysign(1., drive.force_n_m)
    velocity_scale = target / drive.drag_pa_s
    rate_scale = velocity_scale / drive.width_m
    w.positive(velocity_scale, "representable velocity scale")
    w.positive(rate_scale, "representable axial-rate scale")
    guess = None if warm is None else warm["x"]
    evaluations = iterations = 0

    def evaluate(x):
        nonlocal guess, evaluations, iterations
        w.check_deadline(deadline)
        if not 0 < x <= 1:
            raise ValueError("positive scaled rate left the drag bracket")
        r = w.respond(prep, law, kappa, sign * rate_scale * x, guess)
        evaluations += 1
        iterations += r["iterations"]
        if warm is not None:
            guess = r["x"]
        residual = x + abs(r["force"]) / target - 1.
        tangent = 1. + r["dforce"] * rate_scale / target
        if not math.isfinite(tangent) or tangent <= 0:
            raise ValueError("motion tangent outside monotone finite support")
        return residual, tangent, r

    if method == "brent":
        def residual(x):
            return -1. if x == 0 else evaluate(x)[0]
        x = brentq(residual, 0., 1., xtol=1e-15, rtol=1e-12, maxiter=MAX_ITERATIONS)
        residual_value, _, r = evaluate(x)
    else:
        lo, hi = 0., 1.
        x = .5 if warm is None else min(max(abs(warm["rate"]) / rate_scale, 1e-12), 1.)
        for _ in range(MAX_ITERATIONS):
            residual_value, tangent, r = evaluate(x)
            if abs(residual_value) <= FORCE_TOL:
                break
            if residual_value > 0:
                hi = x
            else:
                lo = x
            # Newton in log(x), limited to a factor two. A linear-x step can
            # jump near zero where plastic stress increments lose resolution,
            # even though the wanted root is comfortably representable.
            log_step = max(-math.log(2), min(math.log(2), -residual_value / (x * tangent)))
            trial = x * math.exp(log_step)
            candidate = trial if lo < trial < hi else (lo + hi) / 2
            if candidate == x:
                raise ValueError("motion root lost resolution")
            x = candidate
        else:
            raise ValueError("motion force balance did not converge")
    if abs(residual_value) > FORCE_TOL:
        raise ValueError("motion force balance exceeds fixed tolerance")
    v = sign * velocity_scale * x
    drive_power = drive.force_n_m * v
    drag_power = drive.drag_pa_s * v * v
    creep_power = drive.width_m * r["creep_work"]
    plastic_power = drive.width_m * r["plastic_work"]
    power_relative = abs(drive_power - drag_power - creep_power - plastic_power) / drive_power
    if not math.isfinite(power_relative) or power_relative > 2e-10:
        raise ValueError("motion power account failed")
    return dict(r, velocity_m_s=v, force_relative=abs(residual_value),
                drive_power_w_m=drive_power, drag_power_w_m=drag_power,
                creep_power_w_m=creep_power, plastic_power_w_m=plastic_power,
                power_relative=power_relative, evaluations=evaluations, iterations=iterations)
