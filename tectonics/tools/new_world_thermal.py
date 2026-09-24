"""Bounded initial-condition temperature tables; WORKING NON-CANON.

These are deterministic scenario assumptions, not reconstructed geological
histories or scientifically accepted planetary models. Depth is positive down.
The tables approximate analytical, constant-property, plane-parallel conduction
solutions. Their error bounds concern linear interpolation of the exact model,
not native floating-point evaluation, physical model error, or spherical means.

Sources (equations/approach, not a calibration of these scenario defaults):
* https://doi.org/10.1029/JB082i005p00803 (finite-plate cooling)
* https://aspect-documentation.readthedocs.io/en/latest/parameters/Initial_20temperature_20model.html
  (layered steady continental conduction initial conditions)
* Native W03 equations and solver limitations: docs/W03_THERMAL_COLUMNS.md.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from numbers import Real
from pathlib import Path

from atlas_tectonics.parameters import PlateCoolingParameters, ThermalParameters
from atlas_tectonics.plate_cooling import finite_plate_temperature


SECONDS_PER_MA = 1_000_000.0 * 365.25 * 86400.0
OCEAN_MIN_AGE_S = 10.0 * SECONDS_PER_MA
OCEAN_MAX_AGE_S = 120.0 * SECONDS_PER_MA
MAX_NODES = 4097
MAX_INTERPOLATION_ERROR_K = 0.05
# Leave margin below the requested bound; this is not an empirical fit.
_SPACING_ERROR_K = 0.04
_DIFFUSIVITY_M2_S = 1.0e-6
_CONDUCTIVITY_W_M_K = 3.3
_SOURCE_PATH = Path(__file__).resolve()
_SOURCE_SHA256 = hashlib.sha256(_SOURCE_PATH.read_bytes()).hexdigest()


def source_hash():
    """Return this imported implementation's digest, refusing changed bytes."""
    try:
        current = hashlib.sha256(_SOURCE_PATH.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError('SOURCE_MISMATCH: new-world thermal source is unavailable') from exc
    if current != _SOURCE_SHA256:
        raise ValueError('SOURCE_MISMATCH: new-world thermal source changed after import')
    return current


@dataclass(frozen=True, slots=True)
class ThermalProfile:
    """Immutable knots; ``descriptor()`` gives detached, JSON-ready metadata."""

    depths_m: tuple[float, ...]
    temperatures_k: tuple[float, ...]
    max_error_bound_k: float
    model_json: str

    def descriptor(self):
        return json.loads(self.model_json)


def _number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'{name} must be a finite real number, not a boolean')
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f'{name} is not representable') from exc
    if not math.isfinite(result):
        raise ValueError(f'{name} must be finite')
    if positive and result <= 0.0:
        raise ValueError(f'{name} must be positive')
    if nonnegative and result < 0.0:
        raise ValueError(f'{name} must be nonnegative')
    return result


def _sequence(values, name, **validation):
    try:
        count = len(values)
    except TypeError as exc:
        raise ValueError(f'{name} must be a bounded sequence') from exc
    if not 1 <= count <= MAX_NODES:
        raise ValueError(f'{name} must contain 1 to {MAX_NODES} values')
    captured = tuple(_number(value, name, **validation) for value in values)
    if len(captured) != count:
        raise ValueError(f'{name} changed size during capture')
    return captured


def _finite(value, name):
    if not math.isfinite(value):
        raise ValueError(f'{name} is outside the supported numerical range')
    return value


def _segments(length, curvature):
    """For |T''| <= M, linear interpolation error is <= M h**2 / 8."""
    root = math.sqrt(curvature)
    required = _finite(length * root / math.sqrt(8.0 * _SPACING_ERROR_K),
                       'required table size')
    if required > MAX_NODES - 1:
        raise ValueError(f'interpolation bound requires more than {MAX_NODES} nodes')
    count = max(1, math.ceil(required))
    # This ordering avoids overflowing h**2 for large, weakly curved layers.
    bound = (root * (length / count) / math.sqrt(8.0)) ** 2
    return count, _finite(bound, 'interpolation error bound')


def _profile(depths, temperatures, bound, model):
    depths = tuple(float(value) for value in depths)
    temperatures = tuple(float(value) for value in temperatures)
    if (not 2 <= len(depths) <= MAX_NODES or len(temperatures) != len(depths)
            or any(not math.isfinite(value) for value in depths + temperatures)
            or any(b <= a for a, b in zip(depths, depths[1:]))
            or min(temperatures) < 0.0):
        raise ValueError('temperature table is not finite, ordered and nonnegative')
    if not 0.0 <= bound <= MAX_INTERPOLATION_ERROR_K:
        raise ValueError('temperature table does not meet its interpolation bound')
    model.update({
        'status': 'WORKING NON-CANON; uncalibrated initial-condition scenario',
        'depth_coordinate': 'metres positive downward; plane-parallel model',
        'table_representation': 'piecewise-linear approximation, not exact PDE solution',
        'error_bound_scope': 'analytic interpolation error against exact model; excludes floating-point and physical model error',
        'max_error_bound_k': bound,
        'max_nodes': MAX_NODES,
        'node_count': len(depths),
        'spherical_volume_mean': False,
        'formation_age_inferred': False,
        'mantle_extension': 'none; caller must explicitly model depths below the last knot',
    })
    return ThermalProfile(depths, temperatures, bound,
                          json.dumps(model, sort_keys=True, allow_nan=False))


def ocean_profile(age_s, thickness_m=125000.0, surface_k=273.15, base_k=1573.15,
                  *, budget=None):
    """Finite-plate cooling table for an explicitly admitted 10--120 Ma age.

    ``age_s`` is elapsed thermal cooling time, never crust formation age. The
    base temperature is an actual imposed boundary temperature, not mantle
    potential temperature. No ridge, spreading rate or subduction is inferred.

    For a=pi**2*kappa*t/L**2 the Fourier series gives
    |T''| <= 2*pi*dT/L**2 * sum(n*exp(-a*n*n)). Since each term is bounded by
    integral[n-1,n] (x+1)*exp(-a*x*x) dx, a conservative all-depth bound is
    M=dT*(1/(pi*kappa*t)+sqrt(pi)/(L*sqrt(kappa*t))). Spacing uses M*h**2/8.
    This also bounds the young-age branch evaluated by native image summation.
    """
    age = _number(age_s, 'age_s', positive=True)
    length = _number(thickness_m, 'thickness_m', positive=True)
    surface = _number(surface_k, 'surface_k', nonnegative=True)
    base = _number(base_k, 'base_k', nonnegative=True)
    if not OCEAN_MIN_AGE_S <= age <= OCEAN_MAX_AGE_S:
        raise ValueError('ocean cooling age must lie within the admitted 10--120 Ma interval')
    if base < surface:
        raise ValueError('ocean base_k must be at least surface_k')
    diffusion_area = _DIFFUSIVITY_M2_S * age
    curvature = _finite((base - surface) * (
        1.0 / (math.pi * diffusion_area)
        + math.sqrt(math.pi) / length / math.sqrt(diffusion_area)), 'ocean curvature bound')
    count, bound = _segments(length, curvature)
    depths = tuple(length * (index / count) for index in range(count)) + (length,)
    if base == surface:
        temperatures = (surface,) * len(depths)
    else:
        parameters = PlateCoolingParameters(
            thermal=ThermalParameters(
                profile_id='new-world-ocean-constant-property-v1',
                provenance='Explicit uncalibrated new-world scenario; native W03 finite plate',
                surface_temperature_k=surface, mantle_temperature_k=base,
                diffusivity_m2_s=_DIFFUSIVITY_M2_S),
            thickness_m=length, conductivity_w_m_k=_CONDUCTIVITY_W_M_K)
        temperatures = finite_plate_temperature(depths, age, parameters,
                                                batch_elements=MAX_NODES, budget=budget)
    return _profile(depths, temperatures, bound, {
        'model': 'constant-property 1-D finite-plate cooling',
        'native_evaluator': 'atlas_tectonics.plate_cooling.finite_plate_temperature (point samples)',
        'cooling_age_s': age,
        'admitted_cooling_age_s': [OCEAN_MIN_AGE_S, OCEAN_MAX_AGE_S],
        'seconds_per_ma': SECONDS_PER_MA,
        'thickness_m': length,
        'surface_temperature_k': surface,
        'base_temperature_k': base,
        'diffusivity_m2_s': _DIFFUSIVITY_M2_S,
        'conductivity_w_m_k': _CONDUCTIVITY_W_M_K,
        'volumetric_heat_capacity_j_m3_k': _CONDUCTIVITY_W_M_K / _DIFFUSIVITY_M2_S,
        'volumetric_heating_w_m3': 0.0,
        'initial_condition': 'interior initially at prescribed base temperature; fixed surface and base thereafter',
        'curvature_bound_k_m2': curvature,
        'history_inference': 'none: no ridge, spreading, subduction or crust-formation history',
        'sources': ['https://doi.org/10.1029/JB082i005p00803',
                    'tectonics/docs/W03_THERMAL_COLUMNS.md'],
    })


def continental_profile(boundaries_m, conductivities_w_m_k, heat_production_w_m3,
                        surface_k=273.15, base_k=1573.15):
    """Layered steady k*T''+H=0 with continuous T and upward flux k*T'.

    Boundaries start at zero. Each layer has positive constant conductivity and
    nonnegative *volumetric* heating in W/m3 (not specific heating in W/kg).
    Every interface is a table knot; slope jumps are never interpolated across.
    Boundary temperatures prescribe an equilibrium scenario, not an elapsed age.
    No basal-flux sign constraint is imposed: sufficiently strong internal heat
    can drive heat out through the base as well as the surface.
    """
    boundaries = _sequence(boundaries_m, 'boundaries_m', nonnegative=True)
    conductivity = _sequence(conductivities_w_m_k, 'conductivities_w_m_k', positive=True)
    heating = _sequence(heat_production_w_m3, 'heat_production_w_m3', nonnegative=True)
    surface = _number(surface_k, 'surface_k', nonnegative=True)
    base = _number(base_k, 'base_k', nonnegative=True)
    if (len(boundaries) < 2 or boundaries[0] != 0.0
            or any(b <= a for a, b in zip(boundaries, boundaries[1:]))):
        raise ValueError('boundaries_m must start at zero and increase strictly')
    if len(conductivity) != len(boundaries) - 1 or len(heating) != len(conductivity):
        raise ValueError('exactly one conductivity and heating value per layer is required')
    widths = tuple(b - a for a, b in zip(boundaries, boundaries[1:]))
    resistance = []
    heat_terms = []
    above_heating = 0.0
    subdivisions = []
    bound = 0.0
    node_count = 1
    for width, k, heat in zip(widths, conductivity, heating):
        layer_resistance = _finite(width / k, 'layer thermal resistance')
        layer_heating = _finite(heat * width, 'integrated layer heating')
        resistance.append(layer_resistance)
        heat_terms.append(_finite((above_heating + 0.5 * layer_heating) * layer_resistance,
                                  'layer heating temperature contribution'))
        above_heating = _finite(above_heating + layer_heating, 'total integrated heating')
        curvature = _finite(heat / k, 'continental curvature bound')
        count, layer_bound = _segments(width, curvature)
        subdivisions.append(count)
        node_count += count
        if node_count > MAX_NODES:
            raise ValueError(f'interpolation bound requires more than {MAX_NODES} nodes')
        bound = max(bound, layer_bound)
    try:
        total_resistance = _finite(math.fsum(resistance), 'total thermal resistance')
        heating_temperature = _finite(math.fsum(heat_terms), 'total heating contribution')
    except OverflowError as exc:
        raise ValueError('layered conduction exceeds the supported numerical range') from exc
    if total_resistance <= 0.0:
        raise ValueError('total thermal resistance is not numerically positive')
    surface_flux = _finite((base - surface + heating_temperature) / total_resistance,
                           'upward surface heat flux')
    depths = [0.0]
    temperatures = [surface]
    top_temperature = surface
    top_flux = surface_flux
    interface_fluxes = [surface_flux]
    for index, (width, k, heat, count) in enumerate(zip(widths, conductivity, heating, subdivisions)):
        for part in range(1, count + 1):
            offset = width * (part / count)
            depth = boundaries[index + 1] if part == count else boundaries[index] + offset
            temperature = top_temperature + (top_flux - 0.5 * heat * offset) * (offset / k)
            depths.append(depth)
            temperatures.append(_finite(temperature, 'continental temperature'))
        top_temperature = temperatures[-1]
        top_flux = _finite(top_flux - heat * width, 'upward interface heat flux')
        interface_fluxes.append(top_flux)
    # The prescribed endpoint is exact; retain the calculation residual visibly.
    base_residual = temperatures[-1] - base
    temperatures[-1] = base
    return _profile(depths, temperatures, bound, {
        'model': 'layered constant-property 1-D steady conduction',
        'equation': 'k_i d2T/dz2 + H_i = 0; T and k_i dT/dz continuous at interfaces',
        'boundaries_m': list(boundaries),
        'conductivities_w_m_k': list(conductivity),
        'heat_production_w_m3': list(heating),
        'surface_temperature_k': surface,
        'base_temperature_k': base,
        'upward_interface_heat_flux_w_m2': interface_fluxes,
        'integrated_heating_w_m2': above_heating,
        'computed_base_temperature_residual_k': base_residual,
        'elapsed_thermal_age': 'undefined: prescribed steady equilibrium, not an age inversion',
        'advection_and_internal_interfaces': 'no advection; no contact thermal resistance',
        'sources': ['https://aspect-documentation.readthedocs.io/en/latest/parameters/Initial_20temperature_20model.html'],
    })
