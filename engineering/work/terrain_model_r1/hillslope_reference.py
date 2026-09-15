"""Bounded, static, 1-D soil-mantled hillslope numerical reference.

This is NEW implementation, not recovered historical code or a Diadem terrain
producer. It solves a steady flux law; it does not simulate elapsed time, soil
production, chemical mass transfer, bedrock failure, or downstream deposition.
The critical gradient bounds this law's domain, never all real-world slopes.
Only the CLI's stdout is written. All calculations use the standard library.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

CONTRACT_PATH = Path(__file__).with_name("hillslope_benchmark.json")
CONTRACT_SHA256 = "3f5e42aecef8e008b6472ca791088eeadf1d84e567d7797c2417054dc68d2f93"
MAX_CELLS = 100_000
MAX_BISECTION_ITERATIONS = 256
FLUX_ATOL = 1e-12
FLUX_RTOL = 1e-10
IMPORTED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class ReferenceError(ValueError):
    """Unsupported inputs or failed numerical-reference checks."""


def _number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReferenceError(f"{name} must be a finite real number")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise ReferenceError(f"{name} cannot be represented in binary64") from exc
    if not math.isfinite(value):
        raise ReferenceError(f"{name} must be finite")
    if positive and value <= 0:
        raise ReferenceError(f"{name} must be positive")
    if nonnegative and value < 0:
        raise ReferenceError(f"{name} must be nonnegative")
    return value


@dataclass(frozen=True)
class HillslopeParameters:
    K_m2_per_yr: float
    Co_m_per_yr: float
    density_ratio: float
    critical_gradient: float

    def __post_init__(self):
        for name in ("K_m2_per_yr", "density_ratio", "critical_gradient"):
            object.__setattr__(self, name, _number(getattr(self, name), name, positive=True))
        object.__setattr__(self, "Co_m_per_yr", _number(self.Co_m_per_yr, "Co_m_per_yr", nonnegative=True))
        supply = self.density_ratio * self.Co_m_per_yr
        a = supply / self.K_m2_per_yr
        if not math.isfinite(supply) or not math.isfinite(a):
            raise ReferenceError("Derived supply or curvature exceeds binary64 range")
        if self.Co_m_per_yr > 0 and (supply == 0 or a == 0):
            raise ReferenceError("Derived supply or curvature underflows binary64")

    @property
    def supply_m_per_yr(self):
        """Bulk sediment supply, not rock-equivalent lowering or porosity."""
        return self.density_ratio * self.Co_m_per_yr


@dataclass(frozen=True)
class HillslopeProfile:
    x_m: tuple[float, ...]
    elevation_m: tuple[float, ...]
    midpoint_x_m: tuple[float, ...]
    midpoint_slope: tuple[float, ...]
    midpoint_flux_m2_per_yr: tuple[float, ...]
    toe_flux_m2_per_yr: float
    spacing_m: float
    maximum_flux_residual_m2_per_yr: float


def sediment_flux(slope, parameters: HillslopeParameters):
    """Downslope magnitude q=K*s/(1-(s/Sc)^2), bulk m²/year."""
    slope = _number(slope, "slope", nonnegative=True)
    if slope >= parameters.critical_gradient:
        raise ReferenceError("Slope is outside this soil-transport law: s must be below Sc")
    ratio = slope / parameters.critical_gradient
    denominator = 1.0 - ratio * ratio
    if denominator <= 0:
        raise ReferenceError("Critical denominator cannot be represented positively")
    value = parameters.K_m2_per_yr * slope / denominator
    if not math.isfinite(value):
        raise ReferenceError("Flux exceeds binary64 range")
    return value


def slope_for_flux(flux, parameters: HillslopeParameters):
    """Invert monotonically by scalar bisection, not the oracle's quadratic."""
    flux = _number(flux, "flux", nonnegative=True)
    if flux == 0:
        return 0.0
    lo = 0.0
    hi = math.nextafter(parameters.critical_gradient, 0.0)
    if hi <= 0:
        raise ReferenceError("No representable positive subcritical gradient")
    try:
        maximum_flux = sediment_flux(hi, parameters)
    except ReferenceError:
        maximum_flux = math.inf
    if maximum_flux < flux:
        raise ReferenceError("Requested flux requires an unrepresentable subcritical slope")
    for _ in range(MAX_BISECTION_ITERATIONS):
        mid = lo + (hi - lo) / 2.0
        if mid == lo or mid == hi:
            break
        try:
            observed = sediment_flux(mid, parameters)
        except ReferenceError:
            observed = math.inf
        if observed == flux:
            return mid
        if observed < flux:
            lo = mid
        else:
            hi = mid
    candidates = []
    for slope in (lo, hi):
        try:
            residual = abs(sediment_flux(slope, parameters) - flux)
            candidates.append((residual, slope))
        except ReferenceError:
            pass
    if not candidates:
        raise ReferenceError("No finite flux solution found")
    residual, result = min(candidates)
    if result <= 0 or residual > FLUX_ATOL + FLUX_RTOL * flux:
        raise ReferenceError("Bisection did not meet the frozen flux tolerance")
    return result


def _grid(half_length_m, spacing_m):
    length = _number(half_length_m, "half_length_m", positive=True)
    spacing = _number(spacing_m, "spacing_m", positive=True)
    count = length / spacing
    if not math.isfinite(count) or count < 1 or count > MAX_CELLS:
        raise ReferenceError(f"Grid must contain 1..{MAX_CELLS} cells")
    cells = round(count)
    if abs(count - cells) > 16 * sys.float_info.epsilon * max(1.0, count):
        raise ReferenceError("Length must be an integer multiple of spacing")
    return length, spacing, cells


def reconstruct_half_hillslope(parameters: HillslopeParameters, *, half_length_m,
                               spacing_m, toe_elevation_m=0.0):
    """q(x)=rho_ratio*Co*x; integrate slopes backwards from the fixed toe."""
    length, spacing, cells = _grid(half_length_m, spacing_m)
    toe = _number(toe_elevation_m, "toe_elevation_m")
    toe_flux = parameters.supply_m_per_yr * length
    if not math.isfinite(toe_flux):
        raise ReferenceError("Toe flux exceeds binary64 range")
    if parameters.Co_m_per_yr > 0 and toe_flux == 0:
        raise ReferenceError("Positive toe flux underflows binary64")
    # Explicitly establish that the toe remains within the numerical law.
    slope_for_flux(toe_flux, parameters)
    midpoints = tuple((i + 0.5) * spacing for i in range(cells))
    if not (0 < midpoints[0] < midpoints[-1] < length) and cells > 1:
        raise ReferenceError("Distinct interior midpoints cannot be represented")
    if cells == 1 and not 0 < midpoints[0] < length:
        raise ReferenceError("Interior midpoint cannot be represented")
    fluxes = tuple(parameters.supply_m_per_yr * x for x in midpoints)
    slopes = tuple(slope_for_flux(q, parameters) for q in fluxes)
    elevations = [toe] * (cells + 1)
    for i in range(cells - 1, -1, -1):
        elevations[i] = elevations[i + 1] + spacing * slopes[i]
        if not math.isfinite(elevations[i]):
            raise ReferenceError("Integrated elevation exceeds binary64 range")
    x = tuple(i * spacing for i in range(cells)) + (length,)
    residual = max(abs(sediment_flux(s, parameters) - q) for s, q in zip(slopes, fluxes))
    return HillslopeProfile(x, tuple(elevations), midpoints, slopes, fluxes,
                            toe_flux, spacing, residual)


def analytic_elevation(x_m, parameters: HillslopeParameters, *, half_length_m,
                       toe_elevation_m=0.0):
    """Independent closed-form oracle; never called by the reconstruction.

    a=ratio*Co/K, c=2a/Sc, u=c*x, t=sqrt(1+u²).
    Integral_0^x s(v)dv = Sc/c * [(t-1)-log((1+t)/2)].
    Differentiation recovers the quadratic root Sc*u/(sqrt(1+u²)+1).
    Rationalised t-1 and log1p avoid small-gradient cancellation.
    """
    x = _number(x_m, "x_m", nonnegative=True)
    length = _number(half_length_m, "half_length_m", positive=True)
    toe = _number(toe_elevation_m, "toe_elevation_m")
    if x > length:
        raise ReferenceError("Oracle coordinate lies beyond the toe")
    if x == length or parameters.Co_m_per_yr == 0:
        return toe
    a = parameters.supply_m_per_yr / parameters.K_m2_per_yr
    c = 2.0 * a / parameters.critical_gradient
    if not math.isfinite(c) or c == 0:
        raise ReferenceError("Oracle scaling exceeds binary64 range")

    def integral(position):
        u = c * position
        if not math.isfinite(u):
            raise ReferenceError("Oracle argument exceeds binary64 range")
        t = math.hypot(1.0, u)
        d = (u / (t + 1.0)) * u
        return (parameters.critical_gradient / c) * (d - math.log1p(d / 2.0))

    value = toe + integral(length) - integral(x)
    if not math.isfinite(value):
        raise ReferenceError("Oracle elevation exceeds binary64 range")
    return value


def height_error_bound(parameters: HillslopeParameters, *, half_length_m,
                       spacing_m, toe_elevation_m=0.0):
    """Published-law-independent midpoint bound plus frozen numerical margins."""
    length, spacing, cells = _grid(half_length_m, spacing_m)
    toe = _number(toe_elevation_m, "toe_elevation_m")
    a = parameters.supply_m_per_yr / parameters.K_m2_per_yr
    curvature_bound = 8.0 * a * a / parameters.critical_gradient
    quadrature = length * spacing * spacing * curvature_bound / 24.0
    q_toe = parameters.supply_m_per_yr * length
    inversion = length * (FLUX_ATOL + FLUX_RTOL * q_toe) / parameters.K_m2_per_yr
    rounding = (64.0 * sys.float_info.epsilon * (cells + 1)
                * max(1.0, abs(toe) + length * parameters.critical_gradient))
    total = quadrature + inversion + rounding
    if not math.isfinite(total):
        raise ReferenceError("Error bound exceeds binary64 range")
    return {"quadrature_m": quadrature, "inversion_m": inversion,
            "roundoff_allowance_m": rounding, "total_m": total}


def read_contract(path=CONTRACT_PATH):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != CONTRACT_SHA256:
        raise ReferenceError("Frozen numerical benchmark contract changed")
    contract = json.loads(data)
    if (FLUX_ATOL != contract["tolerances"]["flux_absolute_m2_per_yr"] or
        FLUX_RTOL != contract["tolerances"]["flux_relative"] or
        MAX_CELLS != contract["method"]["maximum_cells"] or
        MAX_BISECTION_ITERATIONS != contract["method"]["maximum_bisection_iterations"]):
        raise ReferenceError("Implementation constants differ from the frozen benchmark")
    return contract


def profile_bytes(profile: HillslopeProfile):
    """Ordered binary64 proof, including signed zero (no tolerant equality)."""
    fields = (profile.x_m, profile.elevation_m, profile.midpoint_x_m,
              profile.midpoint_slope, profile.midpoint_flux_m2_per_yr,
              (profile.toe_flux_m2_per_yr, profile.spacing_m,
               profile.maximum_flux_residual_m2_per_yr))
    return b"".join(struct.pack("<Q", len(field)) +
                    b"".join(struct.pack("<d", value) for value in field)
                    for field in fields)


def run_benchmark(path=CONTRACT_PATH):
    """Small numerical-verification benchmark, not a performance measurement."""
    source_before = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if source_before != IMPORTED_SOURCE_SHA256:
        raise ReferenceError("Implementation changed since module import")
    contract = read_contract(path)
    results = []
    for case in [contract["reference_case"], *contract["held_out_numerical_stress_cases"]]:
        parameters = HillslopeParameters(*(case[k] for k in
            ("K_m2_per_yr", "Co_m_per_yr", "density_ratio", "critical_gradient")))
        errors = []
        grids = []
        for spacing in case["grid_spacings_m"]:
            options = {"half_length_m": case["half_length_m"], "spacing_m": spacing,
                       "toe_elevation_m": case["toe_elevation_m"]}
            profile = reconstruct_half_hillslope(parameters, **options)
            oracle = tuple(analytic_elevation(x, parameters,
                half_length_m=case["half_length_m"], toe_elevation_m=case["toe_elevation_m"])
                for x in profile.x_m)
            error = max(abs(a - b) for a, b in zip(profile.elevation_m, oracle))
            bound = height_error_bound(parameters, **options)
            if error > bound["total_m"]:
                raise ReferenceError(f"{case['id']}: analytical error exceeds frozen bound")
            encoded = profile_bytes(profile)
            repeat_exact = profile_bytes(reconstruct_half_hillslope(parameters, **options)) == encoded
            if not repeat_exact or profile.elevation_m[-1] != case["toe_elevation_m"]:
                raise ReferenceError(f"{case['id']}: repeatability or fixed-toe check failed")
            errors.append(error)
            grids.append({"spacing_m": spacing, "cells": len(profile.midpoint_x_m),
                "summit_elevation_m": profile.elevation_m[0],
                "maximum_analytic_error_m": error, "height_error_bound": bound,
                "maximum_flux_residual_m2_per_yr": profile.maximum_flux_residual_m2_per_yr,
                "toe_flux_m2_per_yr": profile.toe_flux_m2_per_yr,
                "profile_logical_sha256": hashlib.sha256(encoded).hexdigest(),
                "repeat_exact": repeat_exact})
        ratios = [errors[i] / errors[i + 1] for i in range(len(errors) - 1)]
        tolerance = contract["tolerances"]
        if not all(tolerance["observed_second_order_error_ratio_min"] <= r <=
                   tolerance["observed_second_order_error_ratio_max"] for r in ratios):
            raise ReferenceError(f"{case['id']}: second-order convergence check failed")
        results.append({"id": case["id"], "grids": grids, "error_ratios": ratios})
    read_contract(path)
    source_after = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if source_after != source_before:
        raise ReferenceError("Implementation changed during benchmark")
    return {"schema": "diadem.terrain.hillslope-reference-result.v1",
        "status": "PASS_NUMERICAL_REFERENCE_ONLY", "contract_sha256": CONTRACT_SHA256,
        "implementation_sha256": source_before,
        "source_unchanged_before_after": True,
        "python_version": sys.version, "float_mantissa_bits": sys.float_info.mant_dig,
        "cases": results, "physical_validation_passed": False,
        "construction_scope": "STATIC_1D_SYNTHETIC_SOIL_MANTLED_HALF_HILLSLOPE_ONLY",
        "diadem_parameters_established": False, "production_authorized": False,
        "complete_T03_CF04_L02": False, "optimisation_measured": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--benchmark", type=Path, default=CONTRACT_PATH,
                        help="Exact pre-frozen numerical benchmark contract")
    arguments = parser.parse_args(argv)
    try:
        result = run_benchmark(arguments.benchmark)
    except (OSError, ReferenceError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc),
                          "production_authorized": False}, allow_nan=False))
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
