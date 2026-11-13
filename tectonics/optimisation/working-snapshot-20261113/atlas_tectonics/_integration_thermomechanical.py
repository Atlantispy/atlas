"""I02.2a package owner of one force-balanced thermomechanical stage. WORKING NON-CANON.

The motion root at a supplied preparation and history, with column heat taken once from that same solved state;
exact rest for zero drive; scalar stage diagnostics and the balanced steady-reference throughput. External drag
dissipation is never column heat. Moved without change from tools/check_i01_thermomechanical_motion.py, which
re-exports these same objects and keeps its fixed-geometry evolution, oracles, deterministic test deadline, case
loading and campaign.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

import math
import time

import numpy as np

from . import _integration_heat as heat
from . import _integration_motion as motion
from . import _integration_weakening as weakening

REST = dict(rate=0., velocity_m_s=0., x=None, force=0., drive_power_w_m=0., drag_power_w_m=0., creep_power_w_m=0.,
            plastic_power_w_m=0., work=0., creep_work=0., plastic_work=0., heat=0., stored=0., force_relative=0.,
            power_relative=0., same_stress=True, evaluations=0, iterations=0)


def expired(deadline):
    return deadline is not None and time.perf_counter() > deadline


def ratio(residual, scale):
    """|residual|/|scale|. A zero account (rest) reports its absolute residual, which must then be zero."""
    return abs(residual)/abs(scale) if scale else abs(residual)


def departure(theta0, size):
    theta = np.asarray(theta0)
    if theta.dtype.kind not in "fiu" or theta.shape != (size,) or not np.all(np.isfinite(theta)):
        raise ValueError("initial temperature departure must be finite and real, one value per material point")
    return theta.astype(float)


# ----------------------------------------------------------------------------- one force-balanced stage

def stage(prep, law, kappa, drive, fractions, *, warm=None, deadline=None):
    """Solve F = D v + F_column(v/width, kappa) at this preparation, then take heat from that same state.

    The retained motion.solve finds the rate. The retained heat.mechanics re-evaluates the same
    preparation, history and rate, starting from the root's log-stresses, and returns the pointwise
    source in W/m^2 per control volume (quadrature width already included). Zero drive is exact rest:
    no mechanics call, zero source and zero history rate. ``warm`` is an initial guess only.
    """
    root = motion.solve(prep, law, kappa, drive, warm=warm, deadline=deadline)
    if root["rate"] == 0:
        zero = weakening.frozen(np.zeros(prep.size))
        return dict(REST, source=zero, kdot=zero, plastic_rate=zero)
    mech = heat.mechanics(prep, law, kappa, root["rate"], root["x"], fractions)
    width = drive.width_m
    creep_power, plastic_power = width*mech["creep_work"], width*mech["plastic_work"]
    drive_power, drag_power = root["drive_power_w_m"], root["drag_power_w_m"]
    return dict(rate=root["rate"], velocity_m_s=root["velocity_m_s"], x=root["x"], force=mech["force"],
                drive_power_w_m=drive_power, drag_power_w_m=drag_power, creep_power_w_m=creep_power,
                plastic_power_w_m=plastic_power, work=mech["work"], creep_work=mech["creep_work"],
                plastic_work=mech["plastic_work"], heat=mech["heat"], stored=mech["stored"], source=mech["source"],
                kdot=mech["kdot"], plastic_rate=mech["plastic_rate"], force_relative=root["force_relative"],
                power_relative=abs(drive_power-drag_power-creep_power-plastic_power)/drive_power,
                same_stress=bool(np.array_equal(mech["stress"], root["stress"])),
                evaluations=root["evaluations"], iterations=root["iterations"]+mech["iterations"])


def note(stats, s):
    """Scalar diagnostics of one committed stage; no per-stage history is retained."""
    stats["max_force_relative"] = max(stats["max_force_relative"], s["force_relative"])
    stats["max_power_relative"] = max(stats["max_power_relative"], s["power_relative"])
    stats["min_source_w_m2"] = min(stats["min_source_w_m2"], float(np.min(s["source"])))
    stats["min_dissipation_w_m"] = min(stats["min_dissipation_w_m"], s["drag_power_w_m"], s["creep_power_w_m"],
                                       s["plastic_power_w_m"])
    stats["restress_mismatches"] += int(not s["same_stress"])
    stats["evaluations"] += s["evaluations"]
    stats["iterations"] += s["iterations"]
    stats["stages"] += 1


def reference_throughput(thermal, elapsed):
    """Balanced steady-reference fluxes (radiogenic throughput), reported apart from the departure accounts."""
    top, bottom = thermal.boundary_temperature
    g_top, g_bot = thermal.boundary_conductance
    out = g_top*(float(thermal.steady_k[0])-top) if top is not None else 0.
    into = g_bot*(bottom-float(thermal.steady_k[-1])) if bottom is not None else 0.
    radiogenic = math.fsum(thermal.radiogenic)
    return dict(surface_outflow_w_m2=out, basal_inflow_w_m2=into, radiogenic_w_m2=radiogenic,
                balance_relative=ratio(out-into-radiogenic, abs(out)+abs(into)+abs(radiogenic)), elapsed_s=elapsed,
                surface_outflow_j_m2=out*elapsed, basal_inflow_j_m2=into*elapsed, radiogenic_j_m2=radiogenic*elapsed)
