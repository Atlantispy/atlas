"""E04 analytical half-space cooling: a reference, not an evolving thermal PDE."""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from ._validation import FloatArray, TectonicsError, array, frozen, input_shape
from .parameters import ThermalParameters
from .resources import elements, select_budget


def half_space_temperature(depth_m: Any, age_s: Any,
                           parameters: ThermalParameters, *, backend: str = "reference",
                           budget=None) -> FloatArray:
    """T=Ts+(Tm-Ts)*erf(z/(2*sqrt(kappa*t))); depth is positive downwards.

    Broadcast depth and age to sample independent positions/columns. At t=0 the
    interior is Tm and the prescribed surface is Ts. There is no hidden minimum age.
    math.erf is a transparent scalar reference inside the batch; no SciPy dependency.
    """
    if not isinstance(parameters, ThermalParameters):
        raise TectonicsError("explicit ThermalParameters required")
    if backend not in ("reference", "scipy"):
        raise TectonicsError("backend must be reference or scipy; no automatic fallback")
    try:
        shape = np.broadcast_shapes(input_shape(depth_m, "depth_m"), input_shape(age_s, "age_s"))
    except ValueError as exc:
        raise TectonicsError("depth and age cannot be broadcast") from exc
    # Conservative bound for copies, masks, indexed temporaries and publication.
    with select_budget(budget).reserve(128 * elements(shape)):
        depth = array(depth_m, "depth_m", nonnegative=True)
        age = array(age_s, "age_s", nonnegative=True)
        try:
            depth, age = np.broadcast_arrays(depth, age)
        except ValueError as exc:
            raise TectonicsError("depth and age cannot be broadcast") from exc
        ratio = np.zeros(depth.shape, dtype=np.float64)
        positive_age = age > 0
        with np.errstate(over="ignore", under="ignore", divide="ignore", invalid="ignore"):
            length = 2 * math.sqrt(parameters.diffusivity_m2_s) * np.sqrt(age[positive_age])
            if np.any(~np.isfinite(length)) or np.any(length <= 0):
                raise TectonicsError("thermal diffusion length outside numerical range")
            ratio[positive_age] = depth[positive_age] / length
        ratio[~positive_age & (depth > 0)] = np.inf
        if backend == "scipy":
            try:
                from scipy.special import erf as bulk_erf
            except ImportError as exc:
                raise TectonicsError("explicit scipy backend requested but unavailable") from exc
            bulk_erf(ratio, out=ratio)
            erf = ratio
        else:
            erf = np.fromiter((math.erf(float(x)) for x in ratio.flat),
                              dtype=np.float64, count=ratio.size).reshape(ratio.shape)
        return frozen(parameters.surface_temperature_k +
                      (parameters.mantle_temperature_k - parameters.surface_temperature_k) * erf)
