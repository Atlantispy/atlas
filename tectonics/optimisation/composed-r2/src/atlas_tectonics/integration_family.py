"""I04.1 the declared starting family on the I03 spherical network (atlas.i04-starting-family.v1). WORKING NON-CANON.

A seed and a scenario determine one labelled initial-condition prior: provinces of the minority crust type on the
majority background, inherited columns with their geotherms, inherited sutures of unknown strength, a plate layout with
sites in proportion to crust area (anchored first on the largest provinces), boundary kinds from the crust types of
the plates' sites, and one attached initial slab per trench. It is a prior with origins, not mechanics and not an
appearance objective. Nothing here is a force balance, a reconstruction or a calibration, and no family world is
advanced with D1 output here: generic Voronoi
vertices are three-line junctions, which I03 refuses without supplied junction paths. Ocean formation ages are
unknown; each plate's ocean carries one declared, assumed thermal age instead. Dry land is unknown: crust type is
never relabelled as land.

Which crust does what (the swap is exact). For f <= 0.5 (f = 0.5 included, as in _footprints) the background is
oceanic and the provinces continental: n_a = floor(N f + 1/2) minority sites are continental (the largest
continental provinces, majors and fragments alike, anchor them; slots the anchors cannot fill are drawn inside
continental crust), continental crust rejects free sites, and the N - n_a free sites are oceanic. For f > 0.5 the
background is continental and the provinces oceanic: n_a = floor(N (1 - f) + 1/2) minority sites are oceanic
(anchored on the largest oceanic provinces, else drawn inside oceanic crust), oceanic crust rejects free sites, and
free sites are continental. n_a is evaluated exactly, on the Fraction of the binary64 f (1 minus it under the swap),
rounding half up; for 0 < f < 1 it is clamped to [1, N - 1]; f = 0 or 1 gives no province, so every site is free and
of the background type (ruling F6').

Sutures and their sites (ruling family-01). A suture is the great-circle chord between outline vertices i and
j = i + span, with span uniform in [K/4, 3K/4] (K = 64, a declared scenario prior): neither side of the chord keeps
less than a quarter of the outline, so no sliver part forms. A sutured anchor's two sites are derived, with no number:
the area centroid of the larger side (the union of the province pieces on one side of the suture's great circle; the
circle may cut the outline more than twice), and its mirror across that circle, so the pair's Voronoi bisector lies on
the suture. Both sites are anchors and take the province's crust type, wherever the mirror lands (round-2 ruling,
option 1): the site's own crust does not decide it.

Boundary kinds (ruling F6', a kinematic initial-condition prior, not mechanics). Each plate takes its site's crust
type. Continental-site against oceanic-site plates is a trench with the oceanic-site plate subducting; the same type on
both sides is a ridge, f = 1/2 (between continent-bearing plates, an Atlantic-type basin); the bisector edge of a
suture's mirrored site pair is a transform without carrier (an inherited weakness, locked in I03).

Province areas. The minority area A_min = 4 pi min(f, 1 - f) is split by the fragment-share parameter s: the
fragments together receive s A_min (none when no fragment remains), the majors the rest; within each group a province
gets A_floor + (group area - n A_floor) w_k / sum w, with A_floor = pi (k H_max / R)^2 (RD-05; H_max is the declared
150 km scenario maximum). Fragments are dropped first, then majors, down to one; a single province below A_floor is
refused.

The continuous geometry (province polygons, sutures, sites, the spherical Voronoi diagram with its boundary kinds,
slabs and columns) never refers to the sampling level L, and every predicate that can change it is evaluated on the
continuous polygons. L only decides how the I03 network samples it: each Voronoi edge is cut at t = k/2^L by one
elementwise expression, the reversal-symmetric slerp for edges up to 120 degrees and a rotation about the bisector
pole beyond, so a point two levels share is the same binary64 value; each plate is fanned from its site in 2^L
rings. Material pieces per face come from I03's exact triangle clipping against the province fan triangles, a face
no outline reaches is taken whole by I03's exact containment, and the background is the remainder. A request whose
sampled network or material exceeds the work budget is refused by name (BUDGET_EXCEEDED, LAYOUT_REFUSED); for
example N = 30 or 52 at L = 3 under the default 256 MiB budget. A caller may pass a larger WorkBudget.

P1 (family_columns) delivers the declared columns at the boundary trace under one shared Datum. The family's columns
are declared under the datum mantle fill rho_m = 3300 kg/m3 at T_ref = 293.15 K, whose derived lithospheric-mantle
reference density removes the density jump at the base of the lithosphere (ruling P6). A Datum that derives another
rho_ref is refused, not rebuilt: rebuilding would leave the slabs and the I03 material on the declared datum.

Reproductions, tested bitwise against the New World tools from the tests (the package never imports a tool):
``stream_seed`` (tools/new_world_contract.py), the label draw ``unit`` (tools/new_world_structure.py ``_draw``) and
``continental_profile`` / ``ocean_profile`` (tools/new_world_thermal.py). Geology reads only the continental_structure,
crustal_structure and thermal_structure streams, and never the plate count or the sampling level. Plate sites and slab
lengths read plate_layout. Per-plate ocean draws are keyed by plate identity on the geology streams.

Sources: the I04a decisions proposal, section 4, and the coordinator's rulings of 3 October 2026 (B, C, F6', P6), which
define the rule set implemented here; the New World structure and thermal tools (inherited, uncalibrated scenario
ranges, reused unchanged); the finite-plate cooling evaluator of plate_cooling (doi:10.1029/JB082i005p00803, as cited
by the thermal tool) and the layered steady-conduction initial condition the thermal tool cites (ASPECT
documentation). alpha = 3e-5 /K is inherited from the i01_transitions_v1.json attribution to Clennett et al. (2023,
Table S1), not newly read. Nothing was newly consulted for this module.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from fractions import Fraction
import hashlib
import json
import math
from numbers import Real
import re
from types import MappingProxyType

import numpy as np

from . import integration_driving as D
from . import integration_ports as P
from . import integration_sphere as S
from . import integration_state as _state
from . import integration_support as Q
from . import integration_transfer as T
from . import integration_volume as V
from ._validation import TectonicsError
from .coordinates import SphericalFrame
from .kinematics import Rotation
from .material_library import earth_material_library
from .materials import _name
from .parameters import PlateCoolingParameters, ThermalParameters
from .plate_cooling import finite_plate_temperature
from .resources import MemoryLimitError, select_budget
from .spherical_geometry import SphericalChart


SCHEMA = 'atlas.i04-starting-family.v1'
RADIAL_SCHEMA = 'atlas.i04-starting-family.v2'
GEOMETRY_SCHEMA = 'atlas.i04-starting-family-geometry.v1'
STATUS = 'WORKING NON-CANON'
SCIENTIFIC_STATUS = 'DECLARED_INITIAL_CONDITION_PRIOR'
FRAME_ID = 'i04-family-frame'
SAMPLED = 'sampled-uncalibrated-uniform'

INVALID_REQUEST, STRUCTURE_REFUSED, LAYOUT_REFUSED = 'INVALID_REQUEST', 'STRUCTURE_REFUSED', 'LAYOUT_REFUSED'
CODES = (INVALID_REQUEST, STRUCTURE_REFUSED, LAYOUT_REFUSED)

GEOLOGY_STREAMS = ('continental_structure', 'crustal_structure', 'thermal_structure')
LAYOUT_STREAM = 'plate_layout'
CONTINENTAL, OCEANIC = 'continental', 'oceanic'
MAJOR, FRAGMENT = 'major', 'fragment'

# Request domain: the New World plate-count domain, the structure tool's radius admission (150 km/R <= 0.05) and the
# New World radius upper bound; support levels are the sampling resolutions this producer offers.
RADIUS_RANGE_M = (3e6, 1e8)
PLATE_COUNT_RANGE = (2, 52)
MIN_VORONOI_SITES = 4          # supported N in v1 is 4..52 (ruling C2); 2 and 3 are refused by name
SUPPORT_LEVELS = (0, 1, 2, 3)
TIME_LIMIT_S = 1e18            # the New World epoch-time bound

# Declared constants of the prior (decisions proposal section 4).
MYR_S = 365.25*86400*1e6       # as tools/new_world_structure.py
H_MAX_M = 150000.0             # the deepest declared column: continental lithosphere 110-150 km (ocean 125 km)
OUTLINE_VERTICES = 64          # K
LOBE_HARMONICS = (2, 3, 4, 5)
BISECTIONS = 56                # the _footprints fixed bisection count
AREA_TOLERANCE = 2e-11         # the _footprints relative area tolerance
CAP_LIMIT_RAD = math.radians(80.)
MAX_ATTEMPTS = 64              # per province and per free site; then refused, never a seed retry
# Suture span (ruling family-01, a declared scenario prior): j - i in [K/4, 3K/4] outline vertices, so neither side of
# the chord keeps less than a quarter of the outline and no sliver part forms.
SUTURE_SPAN_VERTICES = (OUTLINE_VERTICES//4, 3*OUTLINE_VERTICES//4)
SUTURE_SITES = ('the area centroid of the larger side (the union of the province pieces on one side of the suture '
                'great circle), and its mirror across that circle (their Voronoi bisector is the suture circle); no '
                'offset number; both sites take the province crust type')
MINORITY_SITES_RULE = ("n_a = floor(N s + 1/2), exact on the Fraction of the binary64 f (s = f, or 1 - f under the "
                       'f > 0.5 swap), rounding half up; clamped to [1, N - 1] when 0 < f < 1; 0 for f = 0 or 1')
# A conservative float prefilter that decides nothing (review family-06). For unit c, v, p the computed (c x v).p
# differs from the exact value by at most about 5 eps |c||v||p| (two products and a difference per cross component,
# three products and two sums in the dot), about 1.1e-15; a margin of 1e-12 can only admit extra candidates, which the
# exact integer signs then decide, and can never drop a true containment.
PREFILTER_MARGIN = 1e-12
SUBLAYERS = 10                 # per declared layer: 3 x 10 = 30 <= the P1 bound of 32
SURFACE_K, BASE_K = 273.15, 1573.15
EPS = float(np.finfo(float).eps)
# Edge points (ruling B2): slerp up to 120 degrees, a rotation about the bisector pole beyond. No point bound may
# exceed I03's 64 eps attachment band; the rotation's interior rounding allowance is derived in _edge below.
SLERP_LIMIT_RAD = 2*math.pi/3
POINT_BAND_RAD = S.ATTACHMENT_BAND_RAD
ROTATION_ROUNDING = 4*EPS
# Coefficients (ruling P6). alpha is a scenario assumption: the library has no admissible instantaneous expansivity.
# The lithospheric-mantle reference density is derived from the I01/D5 datum fill so the LAB has no density jump.
ALPHA_PER_K = 3.0e-5
ALPHA_LABEL = ('scenario assumption; the library has no admissible instantaneous expansivity (3e-5 /K inherited from '
               'the i01_transitions_v1.json attribution to Clennett et al. 2023, Table S1)')
MANTLE_DATUM_KG_M3, DATUM_REFERENCE_K = 3300.0, 293.15


def mantle_reference_density(mantle_density_kg_m3, reference_temperature_k):
    """rho_ref = rho_m / (1 - alpha (T_base - T_ref)) (ruling P6): no density jump at the base of the lithosphere."""
    return mantle_density_kg_m3/(1-ALPHA_PER_K*(BASE_K-reference_temperature_k))


MANTLE_REFERENCE_KG_M3 = mantle_reference_density(MANTLE_DATUM_KG_M3, DATUM_REFERENCE_K)
MANTLE_DENSITY_LABEL = ('derived: rho_m / (1 - alpha (T_base - T_ref)), rho_m = 3300 kg/m3 at T_ref = 293.15 K '
                        '(the I01/D5 datum fill), T_base = 1573.15 K; not library peridotite')
THIN_GEOTHERM = 'the 1-D geotherm is not representative even at its centre'
CONTINENTAL_CONDUCTIVITY = (2.5, 2.5, 3.3)          # top-down, as new_world_structure
CONTINENTAL_HEATING = (1e-6, .25e-6, .02e-6)        # W/m3, top-down, as new_world_structure
OCEAN_LITHOSPHERE_M = 125000.
PHASES = ('crust', 'mantle-lid')
ROCKS = ('rock.basalt', 'rock.gabbro', 'rock.granite')      # crust densities from the library
IDENTITY = Rotation((1., 0., 0., 0.))
BAND = S.ATTACHMENT_BAND_RAD

RANGES = MappingProxyType({
    'default': MappingProxyType(dict(
        majors=(3, 7), fragments=(0, 6), fragment_share=(.02, .10), weight_log=math.log(4.), aspect=(1., 3.),
        lobe=(0., .30), floor_k=1., slab_length_m=(100e3, 600e3))),
    'wide': MappingProxyType(dict(
        majors=(1, 12), fragments=(0, 16), fragment_share=(0., .30), weight_log=math.log(8.), aspect=(1., 6.),
        lobe=(0., .45), floor_k=.5, slab_length_m=(0., 1200e3))),
})


class FamilyRefused(TectonicsError):
    """A starting family that cannot be issued; ``code`` is INVALID_REQUEST, STRUCTURE_REFUSED or LAYOUT_REFUSED."""

    def __init__(self, message, code):
        if code not in CODES:
            raise ValueError('unknown starting-family refusal code')
        super().__init__(message)
        self.code = code


# ----------------------------------------------------------------------------- seed streams (reproductions)

def _hex32(value, label):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{32}', value):
        raise FamilyRefused(label+' must be 32 lowercase hexadecimal characters', INVALID_REQUEST)
    return value


def stream_seed(seed, name):
    """The New World named stream (tools/new_world_contract.py stream_seed), reproduced byte for byte."""
    _hex32(seed, 'seed')
    if type(name) is not str or not re.fullmatch(r'[a-z0-9_.-]{1,64}', name):
        raise FamilyRefused('random stream names are bounded lowercase identifiers', INVALID_REQUEST)
    message = (b'atlas.new-world.stream.v1\0' + bytes.fromhex(seed) + b'\0' + name.encode('ascii'))
    return hashlib.sha256(message).hexdigest()[:32]


def _bits(stream_hex, label):
    _hex32(stream_hex, 'stream seed')
    if type(label) is not str or not label or not label.isascii():
        raise FamilyRefused('a draw label is nonblank ASCII text', INVALID_REQUEST)
    raw = hashlib.sha256(bytes.fromhex(stream_hex) + b'\0' + label.encode('ascii')).digest()
    return int.from_bytes(raw[:8], 'big') >> 11


def unit(stream_hex, label):
    """One label-keyed draw in [0, 1) (tools/new_world_structure.py _draw), reproduced byte for byte."""
    return _bits(stream_hex, label) * 2.**-53


class _Draws:
    """The four named streams of one seed and a record of every value drawn from them, with its origin."""

    def __init__(self, seed):
        self.streams = {name: stream_seed(seed, name) for name in (*GEOLOGY_STREAMS, LAYOUT_STREAM)}
        self.records = []

    def raw(self, stream, label):
        return unit(self.streams[stream], label)

    def note(self, stream, label, u, value, distribution):
        self.records.append(dict(stream=stream, label=label, unit=u, value=value, distribution=distribution,
                                 origin=SAMPLED))
        return value

    def formula(self, stream, label, rule, distribution):
        """A value from one draw by an inherited formula, evaluated exactly as its source writes it."""
        u = self.raw(stream, label)
        return self.note(stream, label, u, rule(u), distribution)

    def uniform(self, stream, label, lo, hi):
        u = self.raw(stream, label)
        return self.note(stream, label, u, lo+(hi-lo)*u, 'uniform [%r, %r)' % (lo, hi))

    def integer(self, stream, label, lo, hi):
        """Uniform integer in [lo, hi] from the draw's 53 bits, in exact integer arithmetic."""
        bits = _bits(self.streams[stream], label)
        value = lo+((bits*(hi-lo+1)) >> 53)
        return self.note(stream, label, bits*2.**-53, value, 'uniform integer [%d, %d]' % (lo, hi))


# ----------------------------------------------------------------------------- thermal tables (reproductions)

SECONDS_PER_MA = 1_000_000.0 * 365.25 * 86400.0
OCEAN_MIN_AGE_S = 10.0 * SECONDS_PER_MA
OCEAN_MAX_AGE_S = 120.0 * SECONDS_PER_MA
MAX_NODES = 4097
MAX_INTERPOLATION_ERROR_K = 0.05
_SPACING_ERROR_K = 0.04
_DIFFUSIVITY_M2_S = 1.0e-6
_CONDUCTIVITY_W_M_K = 3.3


@dataclass(frozen=True, slots=True)
class ThermalTable:
    """Immutable temperature knots (depth positive down); the same numbers as the tool's ThermalProfile."""
    depths_m: tuple
    temperatures_k: tuple
    max_error_bound_k: float
    model_json: str

    def descriptor(self):
        return json.loads(self.model_json)


def _refuse(message):
    raise FamilyRefused(message, INVALID_REQUEST)


def _number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, Real):
        _refuse(f'{name} must be a finite real number, not a boolean')
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise FamilyRefused(f'{name} is not representable', INVALID_REQUEST) from exc
    if not math.isfinite(result):
        _refuse(f'{name} must be finite')
    if positive and result <= 0.0:
        _refuse(f'{name} must be positive')
    if nonnegative and result < 0.0:
        _refuse(f'{name} must be nonnegative')
    return result


def _sequence(values, name, **validation):
    try:
        count = len(values)
    except TypeError as exc:
        raise FamilyRefused(f'{name} must be a bounded sequence', INVALID_REQUEST) from exc
    if not 1 <= count <= MAX_NODES:
        _refuse(f'{name} must contain 1 to {MAX_NODES} values')
    captured = tuple(_number(value, name, **validation) for value in values)
    if len(captured) != count:
        _refuse(f'{name} changed size during capture')
    return captured


def _finite(value, name):
    if not math.isfinite(value):
        _refuse(f'{name} is outside the supported numerical range')
    return value


def _segments(length, curvature):
    """For |T''| <= M, linear interpolation error is <= M h**2 / 8 (as the tool)."""
    root = math.sqrt(curvature)
    required = _finite(length * root / math.sqrt(8.0 * _SPACING_ERROR_K), 'required table size')
    if required > MAX_NODES - 1:
        _refuse(f'interpolation bound requires more than {MAX_NODES} nodes')
    count = max(1, math.ceil(required))
    bound = (root * (length / count) / math.sqrt(8.0)) ** 2
    return count, _finite(bound, 'interpolation error bound')


def _table(depths, temperatures, bound, model):
    depths = tuple(float(value) for value in depths)
    temperatures = tuple(float(value) for value in temperatures)
    if (not 2 <= len(depths) <= MAX_NODES or len(temperatures) != len(depths)
            or any(not math.isfinite(value) for value in depths + temperatures)
            or any(b <= a for a, b in zip(depths, depths[1:]))
            or min(temperatures) < 0.0):
        _refuse('temperature table is not finite, ordered and nonnegative')
    if not 0.0 <= bound <= MAX_INTERPOLATION_ERROR_K:
        _refuse('temperature table does not meet its interpolation bound')
    model.update({
        'status': 'WORKING NON-CANON; uncalibrated initial-condition scenario',
        'reproduces': 'tools/new_world_thermal.py (the same knots and temperatures)',
        'depth_coordinate': 'metres positive downward; plane-parallel model',
        'table_representation': 'piecewise-linear approximation, not exact PDE solution',
        'max_error_bound_k': bound,
        'bound_scope': 'table only: the tabulated knots against the exact model, not any column built from them',
        'node_count': len(depths),
        'formation_age_inferred': False,
    })
    return ThermalTable(depths, temperatures, bound, json.dumps(model, sort_keys=True, allow_nan=False))


def ocean_profile(age_s, thickness_m=125000.0, surface_k=273.15, base_k=1573.15, *, budget=None):
    """Finite-plate cooling table for an admitted 10-120 Ma assumed thermal age (tools/new_world_thermal.py).

    ``age_s`` is elapsed thermal cooling time, never crust formation age. The temperatures come from the package's
    finite_plate_temperature at the tool's knots, so the table is the tool's, number for number.
    """
    age = _number(age_s, 'age_s', positive=True)
    length = _number(thickness_m, 'thickness_m', positive=True)
    surface = _number(surface_k, 'surface_k', nonnegative=True)
    base = _number(base_k, 'base_k', nonnegative=True)
    if not OCEAN_MIN_AGE_S <= age <= OCEAN_MAX_AGE_S:
        _refuse('ocean cooling age must lie within the admitted 10--120 Ma interval')
    if base < surface:
        _refuse('ocean base_k must be at least surface_k')
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
                provenance='I04 starting family: the New World ocean table reproduced; native W03 finite plate',
                surface_temperature_k=surface, mantle_temperature_k=base,
                diffusivity_m2_s=_DIFFUSIVITY_M2_S),
            thickness_m=length, conductivity_w_m_k=_CONDUCTIVITY_W_M_K)
        temperatures = finite_plate_temperature(depths, age, parameters, batch_elements=MAX_NODES, budget=budget)
    return _table(depths, temperatures, bound, {
        'model': 'constant-property 1-D finite-plate cooling',
        'native_evaluator': 'atlas_tectonics.plate_cooling.finite_plate_temperature (point samples)',
        'cooling_age_s': age,
        'admitted_cooling_age_s': [OCEAN_MIN_AGE_S, OCEAN_MAX_AGE_S],
        'thickness_m': length,
        'surface_temperature_k': surface,
        'base_temperature_k': base,
        'diffusivity_m2_s': _DIFFUSIVITY_M2_S,
        'conductivity_w_m_k': _CONDUCTIVITY_W_M_K,
        'volumetric_heating_w_m3': 0.0,
        'curvature_bound_k_m2': curvature,
        'history_inference': 'none: an assumed thermal age, not a formation age or ridge history',
    })


def _continental(boundaries_m, conductivities_w_m_k, heat_production_w_m3, surface_k, base_k):
    """The tool's layered steady solution: (table, surface temperature, surface flux, per-layer (w, k, H))."""
    boundaries = _sequence(boundaries_m, 'boundaries_m', nonnegative=True)
    conductivity = _sequence(conductivities_w_m_k, 'conductivities_w_m_k', positive=True)
    heating = _sequence(heat_production_w_m3, 'heat_production_w_m3', nonnegative=True)
    surface = _number(surface_k, 'surface_k', nonnegative=True)
    base = _number(base_k, 'base_k', nonnegative=True)
    if (len(boundaries) < 2 or boundaries[0] != 0.0
            or any(b <= a for a, b in zip(boundaries, boundaries[1:]))):
        _refuse('boundaries_m must start at zero and increase strictly')
    if len(conductivity) != len(boundaries) - 1 or len(heating) != len(conductivity):
        _refuse('exactly one conductivity and heating value per layer is required')
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
            _refuse(f'interpolation bound requires more than {MAX_NODES} nodes')
        bound = max(bound, layer_bound)
    try:
        total_resistance = _finite(math.fsum(resistance), 'total thermal resistance')
        heating_temperature = _finite(math.fsum(heat_terms), 'total heating contribution')
    except OverflowError as exc:
        raise FamilyRefused('layered conduction exceeds the supported numerical range', INVALID_REQUEST) from exc
    if total_resistance <= 0.0:
        _refuse('total thermal resistance is not numerically positive')
    surface_flux = _finite((base - surface + heating_temperature) / total_resistance, 'upward surface heat flux')
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
    base_residual = temperatures[-1] - base
    temperatures[-1] = base
    table = _table(depths, temperatures, bound, {
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
    })
    return table, surface, surface_flux, tuple(zip(widths, conductivity, heating))


def continental_profile(boundaries_m, conductivities_w_m_k, heat_production_w_m3, surface_k=273.15,
                        base_k=1573.15):
    """Layered steady k T'' + H = 0 with continuous T and upward flux (tools/new_world_thermal.py), reproduced."""
    return _continental(boundaries_m, conductivities_w_m_k, heat_production_w_m3, surface_k, base_k)[0]


# ----------------------------------------------------------------------------- the request

def _real(value, label):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        _refuse(label+' must be a real number')
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise FamilyRefused(label+' is not representable in binary64', INVALID_REQUEST) from exc
    if not math.isfinite(result):
        _refuse(label+' must be finite')
    return result+0.


def _integer(value):
    """A Python or NumPy integer as int (never a bool or a float); None otherwise."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        return None
    return int(value)


@dataclass(frozen=True, slots=True)
class FamilyRequest:
    """One request: seed, planet radius, exact plate count N, exact continental fraction f, epoch and time, the
    sampling level L, and the parameter range ('default', physically safe; 'wide', opt-in and recorded). Finite
    NumPy scalars are accepted where a number is taken and stored as Python int or float."""
    seed: str
    radius_m: float
    plate_count: int
    continental_fraction: float
    epoch_id: str
    time_s: float
    support_level: int
    range: str = 'default'
    volume_convention: str = V.REFERENCE_PRISM

    def __post_init__(self):
        _hex32(self.seed, 'seed')
        radius = _real(self.radius_m, 'radius_m')
        if not RADIUS_RANGE_M[0] <= radius <= RADIUS_RANGE_M[1]:
            _refuse('radius_m must lie in [3e6, 1e8] m (150 km/R <= 0.05 admission)')
        count = _integer(self.plate_count)
        if count is None or not PLATE_COUNT_RANGE[0] <= count <= PLATE_COUNT_RANGE[1]:
            _refuse('plate_count must be an integer in 2..52')
        fraction = _real(self.continental_fraction, 'continental_fraction')
        if not 0. <= fraction <= 1.:
            _refuse('continental_fraction must lie in [0, 1]')
        try:
            _name(self.epoch_id, 'epoch_id')
        except TectonicsError as exc:
            raise FamilyRefused(str(exc), INVALID_REQUEST) from exc
        time = _real(self.time_s, 'time_s')
        if abs(time) > TIME_LIMIT_S:
            _refuse('time_s must lie in [-1e18, 1e18] s')
        level = _integer(self.support_level)
        if level is None or level not in SUPPORT_LEVELS:
            _refuse('support_level must be an integer in 0..3')
        if type(self.range) is not str or self.range not in RANGES:
            _refuse("range must be 'default' or 'wide' (opt-in)")
        if (type(self.volume_convention) is not str or
                self.volume_convention not in (V.REFERENCE_PRISM, V.PHYSICAL_RADIAL_SHELL)):
            _refuse('an explicit supported volume convention is required')
        object.__setattr__(self, 'radius_m', radius)
        object.__setattr__(self, 'plate_count', count)
        object.__setattr__(self, 'support_level', level)
        object.__setattr__(self, 'continental_fraction', fraction)
        object.__setattr__(self, 'time_s', time)

    def record(self):
        row = dict(seed=self.seed, radius_m=self.radius_m, plate_count=self.plate_count,
                    continental_fraction=self.continental_fraction, epoch_id=self.epoch_id, time_s=self.time_s,
                    support_level=self.support_level, range=self.range)
        if self.volume_convention != V.REFERENCE_PRISM:
            row['volume_convention'] = self.volume_convention
        return row


# ----------------------------------------------------------------------------- spherical helpers

def _angle(a, b):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return 2*np.arctan2(np.sqrt(np.sum((a-b)*(a-b), axis=-1)), np.sqrt(np.sum((a+b)*(a+b), axis=-1)))


def _normalised(v):
    v = np.asarray(v, dtype=np.float64)
    return v/np.sqrt(np.sum(v*v, axis=-1, keepdims=True))


def _dot3(a, b):
    """Row-wise dot products of (..., 3) arrays, one product and sum per component (no BLAS reduction order)."""
    return a[..., 0]*b[..., 0]+a[..., 1]*b[..., 1]+a[..., 2]*b[..., 2]


def _ints(rows):
    """Rows of binary64 directions as exact primitive integer directions (I03's exact representation)."""
    return [T._primitive(v) for v in T._integers(np.asarray(rows, dtype=np.float64).reshape(-1, 3))]


def _det(a, b, c):
    return T._dot(a, T._cross(b, c))


def _caps_apart(c1, r1, c2, r2):
    """True only when two caps are certainly disjoint (the I03 sweep rejection, hemispheric caps only)."""
    return max(r1, r2)+BAND < math.pi/2 and float(_angle(c1, c2)) > r1+r2+2*BAND


def _anchored_area(unit, centre):
    """Van Oosterom-Strackee anchored sum in steradians, as tools/new_world_structure.py _footprints writes it."""
    other = np.roll(unit, -1, axis=0)
    numerator = np.einsum('ij,j->i', np.cross(unit-centre, other-centre), centre)
    denominator = 1 + unit@centre + other@centre + np.einsum('ij,ij->i', unit, other)
    return math.fsum(2*np.arctan2(numerator, denominator))


def area_moment(ring):
    """The first area moment int_Omega n dA (steradians times unit vector) of a ring counter-clockwise from outside.

    On the unit sphere the coordinates are degree-one harmonics, Laplace_s x = -2 x, so the divergence theorem gives
    int_Omega x dA = -1/2 oint nu ds, with nu the outward conormal. On the great-circle arc a -> b, nu = (b x a)/|b x a|
    is constant, so int_Omega x dA = 1/2 sum_arcs theta_ab (a x b)/|a x b|, theta_ab the arc angle. A hemisphere gives
    pi times its pole; the octant (x, y, z) gives (pi/4)(1, 1, 1). Its direction is the area centroid. An edge whose
    cross product rounds to zero (two consecutive vertices a few ulps apart, as a clipped piece can produce where a
    great circle passes through a vertex) has theta of a few eps and contributes nothing; it is taken as zero.
    """
    a = np.asarray(ring, dtype=np.float64)
    b = np.roll(a, -1, axis=0)
    cross = np.cross(a, b)
    norm = np.sqrt(np.sum(cross*cross, axis=-1, keepdims=True))
    pole = np.divide(cross, norm, out=np.zeros_like(cross), where=norm > 0)
    weight = _angle(a, b)
    return np.array([0.5*math.fsum(weight*pole[:, axis]) for axis in range(3)])


# ----------------------------------------------------------------------------- province outlines

class _Outline:
    """A star-shaped minor-arc polygon about its chart centre: its fan, caps and exact integer form (not stored)."""
    __slots__ = ('centre', 'outline', 'radius', 'tris', 'tri_rings', 'tri_centres', 'tri_radii', 'edge_centres',
                 'edge_radii', 'fan', 'ints')

    def __init__(self, centre, outline):
        c = np.asarray(centre, dtype=np.float64)
        v = np.asarray(outline, dtype=np.float64)
        after = np.roll(v, -1, axis=0)
        self.centre, self.outline = c, v
        self.radius = float(np.max(_angle(v, c)))
        ints = _ints(np.vstack([c[None, :], v]))
        middle, corners = ints[0], ints[1:]
        count = len(corners)
        self.ints = ints
        self.tris = [(middle, corners[j], corners[(j+1) % count]) for j in range(count)]
        if any(_det(*tri) <= 0 for tri in self.tris):
            raise FamilyRefused('a province outline is not star-shaped about its centre', STRUCTURE_REFUSED)
        self.tri_rings = [np.array([c, v[j], after[j]]) for j in range(count)]
        self.tri_centres = _normalised(c[None, :]+v+after)
        self.tri_radii = np.maximum(np.maximum(_angle(self.tri_centres, c), _angle(self.tri_centres, v)),
                                    _angle(self.tri_centres, after))
        self.edge_centres = _normalised(v+after)
        self.edge_radii = 0.5*_angle(v, after)
        # Float fan sides for the PREFILTER_MARGIN prefilter only: (c x v_j, v_j x v_j+1, v_j+1 x c); exact signs
        # decide every containment.
        self.fan = (np.cross(np.broadcast_to(c, v.shape), v), np.cross(v, after),
                    np.cross(after, np.broadcast_to(c, v.shape)))

    def contains(self, points):
        """Per point, True when it lies in the closed polygon: some fan triangle holds it, by exact integer signs."""
        p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        sides = [p @ np.ascontiguousarray(side.T) for side in self.fan]
        maybe = (sides[0] >= -PREFILTER_MARGIN) & (sides[1] >= -PREFILTER_MARGIN) & (sides[2] >= -PREFILTER_MARGIN)
        out = np.zeros(len(p), dtype=bool)
        for row in np.flatnonzero(np.any(maybe, axis=1)):
            q = _ints(p[row])[0]
            for j in np.flatnonzero(maybe[row]):
                a, b, d = self.tris[int(j)]
                if _det(a, b, q) >= 0 and _det(b, d, q) >= 0 and _det(d, a, q) >= 0:
                    out[row] = True
                    break
        return out

    def overlaps(self, other):
        """True when the two polygons share positive area: exact I03 triangle clipping of cap-near fan pairs."""
        if _caps_apart(self.centre, self.radius, other.centre, other.radius):
            return False
        gaps = _angle(self.tri_centres[:, None, :], other.tri_centres[None, :, :])
        reach = self.tri_radii[:, None]+other.tri_radii[None, :]+2*BAND
        hemispheric = np.maximum(self.tri_radii[:, None], other.tri_radii[None, :])+BAND < math.pi/2
        for i, j in zip(*np.nonzero(~(hemispheric & (gaps > reach)))):
            if T._exact_clipped_triangle(list(self.tris[int(i)]), list(other.tris[int(j)])) > 0:
                return True
        return False


@dataclass(frozen=True, eq=False, slots=True)
class Province:
    """One province of the minority crust type: its declared polygon and the parameters that made it."""
    name: str
    role: str
    crust_type: str
    target_area_sr: float
    area_sr: float
    scale: float
    attempt: int
    centre: np.ndarray = field(repr=False)
    outline: np.ndarray = field(repr=False)
    moment_sr: np.ndarray = field(repr=False)
    centroid: np.ndarray = field(repr=False)
    parameters: MappingProxyType = field(repr=False)
    geotherm_note: str | None = None

    def record(self):
        return dict(name=self.name, role=self.role, crust_type=self.crust_type, target_area_sr=self.target_area_sr,
                    area_sr=self.area_sr, scale=self.scale, attempt=self.attempt, parameters=dict(self.parameters),
                    geotherm_note=self.geotherm_note)


@dataclass(frozen=True, eq=False, slots=True)
class Suture:
    """An inherited weakness: the great-circle chord between two seeded outline vertices, of unknown strength.

    ``sites`` is its mirrored site pair (the larger side's area centroid, then its mirror across the suture circle);
    ``part_areas_sr`` the areas of the larger and the smaller side (each the union of the province pieces on that side
    of the circle).
    """
    suture_id: str
    province: str
    start: np.ndarray = field(repr=False)
    end: np.ndarray = field(repr=False)
    sites: np.ndarray = field(repr=False)
    part_areas_sr: tuple
    vertices: tuple
    strength: str = 'UNKNOWN'

    def record(self):
        return dict(suture_id=self.suture_id, province=self.province, strength=self.strength,
                    outline_vertices=list(self.vertices), part_areas_sr=list(self.part_areas_sr),
                    sites=SUTURE_SITES, origin=SCHEMA+'#inherited-suture')


@dataclass(frozen=True, eq=False, slots=True)
class Slab:
    """One attached initial slab per trench: a seeded length and the subducting column's thermal mass deficit."""
    boundary_id: str
    subducting_plate_id: str
    column_id: str
    length_m: float
    deficit_kg_m2: float
    section_anomaly_kg_m: float
    quadrature_bound_kg_m: float

    def record(self):
        return dict(boundary_id=self.boundary_id, subducting_plate_id=self.subducting_plate_id,
                    column_id=self.column_id, length_m=self.length_m, deficit_kg_m2=self.deficit_kg_m2,
                    section_anomaly_kg_m=self.section_anomaly_kg_m,
                    definition=('S = length * int rho_ref alpha (T_base - T(z)) dz over the subducting column '
                                'lithospheric mantle (its mantle-lid sublayers only; crust excluded)'),
                    quadrature=('trapezoid on the 10 mantle-lid sublayer boundaries (T linear within each '
                                'sublayer, as P1 delivers it)'),
                    quadrature_offset_bound_kg_m=self.quadrature_bound_kg_m,
                    quadrature_offset_bound=('derived, against the continuous profile: length rho_ref alpha sum_l '
                                             '(M_l h_l^3/12 + e_node h_l), M_l the curvature bound in sublayer l and '
                                             'e_node the node error (Column.record)'),
                    omitted='crustal compositional buoyancy (declared omission)', origin=SCHEMA+'#initial-slab')


def _planar(lobe, amplitudes, phases, aspect, azimuth):
    """The planar star shape: r(theta) = 1 + sum_m (A u_m/(m-1)) cos(m theta + phi_m), stretched by sqrt(e)."""
    theta = np.arange(OUTLINE_VERTICES) * (2*math.pi/OUTLINE_VERTICES)
    radial = np.ones(OUTLINE_VERTICES)
    for m, u, phase in zip(LOBE_HARMONICS, amplitudes, phases):
        radial = radial + (lobe*u/(m-1))*np.cos(m*theta+phase)
    x, y = radial*np.cos(theta), radial*np.sin(theta)
    c, s = math.cos(azimuth), math.sin(azimuth)
    root = math.sqrt(aspect)
    along, across = (x*c+y*s)*root, (y*c-x*s)/root
    return np.column_stack((along*c-across*s, along*s+across*c))


def _scale(name, xy, target, chart):
    """The fixed 56-step bisection of the _footprints rule, on [0, tan 80 deg / max |xy|]."""
    centre = np.asarray(chart.centre)
    lo, hi = 0., math.tan(CAP_LIMIT_RAD)/float(np.max(np.hypot(xy[:, 0], xy[:, 1])))
    if _anchored_area(chart._unproject(hi*xy), centre) < target:
        raise FamilyRefused('province %s: its 80-degree cap-limited area is below its target area: outside the fixed '
                            'shape envelope' % name, STRUCTURE_REFUSED)
    for _ in range(BISECTIONS):
        mid = (lo+hi)/2
        if _anchored_area(chart._unproject(mid*xy), centre) < target:
            lo = mid
        else:
            hi = mid
    return (lo+hi)/2


def _budgets(draws, rng, minority_sr, floor_sr):
    """Province counts and target areas, with the declared drop rule (fragments first, then majors, to one)."""
    stream = 'continental_structure'
    majors = draws.integer(stream, 'majors', *rng['majors'])
    fragments = draws.integer(stream, 'fragments', *rng['fragments'])
    share = draws.uniform(stream, 'fragment-share', *rng['fragment_share'])
    while True:
        fragment_budget = share*minority_sr if fragments else 0.
        major_budget = minority_sr-fragment_budget
        if (not fragments or fragment_budget >= fragments*floor_sr) and major_budget >= majors*floor_sr:
            break
        if fragments:
            fragments -= 1
        elif majors > 1:
            majors -= 1
        else:
            raise FamilyRefused('a single province remains and the minority area %.6g sr is below the RD-05 floor '
                                'pi (k H_max / R)^2 = %.6g sr (option A refusal)' % (minority_sr, floor_sr),
                                STRUCTURE_REFUSED)
    specs = []
    for role, count, budget in ((MAJOR, majors, major_budget), (FRAGMENT, fragments, fragment_budget)):
        names = ['%s-%02d' % (role, i) for i in range(count)]
        weights = [draws.formula(stream, name+'/weight', lambda u: math.exp(rng['weight_log']*(2*u-1)),
                                 'w = exp(%r (2u - 1))' % rng['weight_log']) for name in names]
        total = math.fsum(weights)
        for name, weight in zip(names, weights):
            specs.append((name, role, floor_sr+(budget-count*floor_sr)*weight/total))
    return dict(majors=majors, fragments=fragments, fragment_share=share, major_budget_sr=major_budget,
                fragment_budget_sr=fragment_budget), specs


def _provinces(sphere, draws, fraction, rng):
    """The province polygons, placed largest first; never reads the plate count or the sampling level."""
    if fraction in (0., 1.):
        return (), {}, ()
    minority = CONTINENTAL if fraction <= .5 else OCEANIC
    minority_sr = 4*math.pi*min(fraction, 1-fraction)
    floor_sr = math.pi*(rng['floor_k']*H_MAX_M/sphere.radius_m)**2
    counts, specs = _budgets(draws, rng, minority_sr, floor_sr)
    counts.update(minority_area_sr=minority_sr, floor_sr=floor_sr)
    stream = 'continental_structure'
    canonical = SphericalChart(sphere, (0., 0., 1.))
    placed, outlines = [], []
    for name, role, target in sorted(specs, key=lambda spec: (-spec[2], spec[0])):
        lobe = draws.uniform(stream, name+'/lobe-amplitude', *rng['lobe'])
        amplitudes = [draws.raw(stream, '%s/lobe/%d/amplitude' % (name, m)) for m in LOBE_HARMONICS]
        phases = [2*math.pi*draws.raw(stream, '%s/lobe/%d/phase' % (name, m)) for m in LOBE_HARMONICS]
        for m, u, phase in zip(LOBE_HARMONICS, amplitudes, phases):
            draws.note(stream, '%s/lobe/%d/amplitude' % (name, m), u, u, 'uniform [0, 1)')
            draws.note(stream, '%s/lobe/%d/phase' % (name, m), phase/(2*math.pi), phase, 'phi = 2 pi u')
        aspect = draws.uniform(stream, name+'/aspect', *rng['aspect'])
        azimuth = draws.formula(stream, name+'/azimuth', lambda u: math.pi*u, 'psi = pi u')
        xy = _planar(lobe, amplitudes, phases, aspect, azimuth)
        scale = _scale(name, xy, target, canonical)
        for attempt in range(MAX_ATTEMPTS):
            uz = draws.raw(stream, '%s/centre/%d/z' % (name, attempt))
            ua = draws.raw(stream, '%s/centre/%d/azimuth' % (name, attempt))
            z, phi = 2*uz-1, 2*math.pi*ua
            r = math.sqrt(max(0., 1-z*z))
            chart = SphericalChart(sphere, (r*math.cos(phi), r*math.sin(phi), z))
            candidate = _Outline(chart.centre, chart._unproject(scale*xy))
            if not any(candidate.overlaps(other) for other in outlines):
                break
        else:
            raise FamilyRefused('province %s found no position free of earlier provinces in %d attempts'
                                % (name, MAX_ATTEMPTS), STRUCTURE_REFUSED)
        draws.note(stream, '%s/centre/%d/z' % (name, attempt), uz, z, 'z = 2u - 1 (accepted attempt)')
        draws.note(stream, '%s/centre/%d/azimuth' % (name, attempt), ua, phi, 'phi = 2 pi u (accepted attempt)')
        area = _anchored_area(candidate.outline, candidate.centre)
        if abs(area-target) > AREA_TOLERANCE*target:
            raise FamilyRefused('province %s missed its declared area tolerance' % name, STRUCTURE_REFUSED)
        moment = area_moment(candidate.outline)
        outlines.append(candidate)
        placed.append(Province(
            name, role, minority, target, area, scale, attempt, S._frozen(candidate.centre, np.float64),
            S._frozen(candidate.outline, np.float64), S._frozen(moment, np.float64),
            S._frozen(_normalised(moment), np.float64),
            MappingProxyType(dict(lobe_amplitude=lobe, lobe_units=list(amplitudes), lobe_phases=list(phases),
                                  aspect=aspect, azimuth=azimuth, cap_radius_rad=candidate.radius)),
            THIN_GEOTHERM if rng['floor_k'] < 1 else None))
    return tuple(placed), counts, tuple(outlines)


def _clip(points, normal):
    """The part of a convex minor-arc polygon on the side normal.x >= 0 (one great-circle Sutherland-Hodgman pass)."""
    out = []
    for k, here in enumerate(points):
        after = points[(k+1) % len(points)]
        dp, dq = float(_dot3(here, normal)), float(_dot3(after, normal))
        if dp >= 0:
            out.append(here)
        if dp*dq < 0:
            cut = (dp*after-dq*here)*(1. if dp > dq else -1.)        # a positive combination: on the minor arc
            out.append(cut/np.linalg.norm(cut))
    return [x for k, x in enumerate(out) if not np.array_equal(x, out[k-1])] if len(out) > 1 else out


def _part(outline, normal):
    """(area in sr, first moment) of the part of a star polygon on the side normal.x >= 0, over its fan triangles."""
    areas, moments = [], []
    for ring in outline.tri_rings:
        piece = _clip(list(ring), normal)
        if len(piece) < 3:
            continue
        piece = np.array(piece)
        anchor = _normalised(np.array([math.fsum(piece[:, axis]) for axis in range(3)]))
        areas.append(_anchored_area(piece, anchor))
        moments.append(area_moment(piece))
    return math.fsum(areas), np.array([math.fsum(m[axis] for m in moments) for axis in range(3)])


def _suture_sites(outline, start, end):
    """The mirrored site pair of a suture (ruling family-01): the area centroid of the larger side (the union of the
    province pieces on one side of the suture's great circle), then its mirror across that circle, so their Voronoi
    bisector is the circle."""
    pole = S._stable_pole(np.asarray(start), np.asarray(end))
    plus, minus = _part(outline, pole), _part(outline, -pole)
    area, moment = plus if plus[0] >= minus[0] else minus
    norm = float(np.linalg.norm(moment))
    if not (area > 0 and math.isfinite(norm) and norm > 0):
        raise FamilyRefused('a suture part has no area centroid (SUTURE_PART)', STRUCTURE_REFUSED)
    larger = moment/norm
    mirror = larger-2*float(_dot3(larger, pole))*pole
    return np.array([larger, mirror]), (max(plus[0], minus[0]), min(plus[0], minus[0]))


def _sutures(provinces, outlines, draws):
    """0-2 inherited sutures per major continental province: chords between seeded outline vertices i and j = i +
    span, span in SUTURE_SPAN_VERTICES (declared), each with its derived mirrored site pair."""
    stream, out = 'continental_structure', []
    lo, hi = SUTURE_SPAN_VERTICES
    for province, outline in zip(provinces, outlines):
        if province.role != MAJOR or province.crust_type != CONTINENTAL:
            continue
        for index in range(draws.integer(stream, province.name+'/sutures', 0, 2)):
            first = draws.integer(stream, '%s/suture/%d/start' % (province.name, index), 0, OUTLINE_VERTICES-1)
            span = draws.integer(stream, '%s/suture/%d/span' % (province.name, index), lo, hi)
            second = (first+span) % OUTLINE_VERTICES
            start, end = province.outline[first], province.outline[second]
            sites, parts = _suture_sites(outline, start, end)
            out.append(Suture('%s/suture-%d' % (province.name, index), province.name,
                              S._frozen(start, np.float64), S._frozen(end, np.float64), S._frozen(sites, np.float64),
                              parts, (first, second)))
    return tuple(out)


# ----------------------------------------------------------------------------- columns

@dataclass(frozen=True, eq=False, slots=True)
class Column:
    """One declared column, top-down: three layers, each cut into SUBLAYERS sublayers with boundary temperatures.

    ``depths_m``/``temperatures_k`` hold the 31 sublayer boundaries; ``density_kg_m3``/``alpha_per_k`` one value per
    sublayer. The column is also the material cohort of the same identity.
    """
    column_id: str
    crust_type: str
    layers: tuple
    depths_m: np.ndarray = field(repr=False)
    temperatures_k: np.ndarray = field(repr=False)
    density_kg_m3: np.ndarray = field(repr=False)
    alpha_per_k: np.ndarray = field(repr=False)
    mass_per_area_kg_m2: tuple = ()
    thickness_m: tuple = ()
    formation_age_s: float | None = None
    thermal_age_s: float | None = None
    thermal: ThermalTable = field(default=None, repr=False)
    curvature_bound_k_m2: tuple = ()
    node_error_k: float = 0.
    volume_convention: str = V.REFERENCE_PRISM
    reference_radius_m: float | None = None
    volume_per_area_m: tuple = ()

    def _bounds(self):
        """(per-sublayer curvature bound M_l, thickness h_l) of the delivered linear sublayers."""
        return np.repeat(np.asarray(self.curvature_bound_k_m2, dtype=np.float64), SUBLAYERS), np.diff(self.depths_m)

    def interpolation_bound_k(self):
        """Derived bound on |delivered linear sublayer T - continuous profile|: max_l M_l h_l^2/8 + node error."""
        curvature, h = self._bounds()
        return float(np.max(curvature*h*h/8))+self.node_error_k

    def mantle_quadrature_bound_kg_m2(self):
        """Derived bound on |trapezoid S/length - int rho alpha (T_base - T) dz| over the mantle lid, against the
        continuous profile: sum_l rho alpha (M_l h_l^3/12 + e_node h_l) (the trapezoid rule error, plus node error)."""
        layer = [phase for _, phase, _ in self.layers].index('mantle-lid')
        rows = slice(layer*SUBLAYERS, (layer+1)*SUBLAYERS)
        curvature, h = self._bounds()
        return math.fsum(float(r)*float(a)*(float(m)*float(t)**3/12+self.node_error_k*float(t))
                         for r, a, m, t in zip(self.density_kg_m3[rows], self.alpha_per_k[rows], curvature[rows],
                                               h[rows]))

    def bottom_to_top(self):
        """(thickness, reference density, alpha, bottom T, top T) per sublayer, bottom first: the P1 layout."""
        depths, temps = self.depths_m, self.temperatures_k
        return (np.diff(depths)[::-1], self.density_kg_m3[::-1], self.alpha_per_k[::-1], temps[1:][::-1],
                temps[:-1][::-1])

    def mantle_deficit_kg_m2(self):
        """int rho_ref alpha (T_base - T(z)) dz over the lithospheric mantle (mantle-lid sublayers), T linear in
        each: the trapezoid on the 10 mantle-lid sublayer boundaries."""
        layer = [phase for _, phase, _ in self.layers].index('mantle-lid')
        rows = slice(layer*SUBLAYERS, (layer+1)*SUBLAYERS)
        depths, temps = self.depths_m, self.temperatures_k
        base = float(temps[-1])
        return math.fsum(float(r)*float(a)*float(h)*(base-0.5*(float(t0)+float(t1)))
                         for r, a, h, t0, t1 in zip(self.density_kg_m3[rows], self.alpha_per_k[rows],
                                                    np.diff(depths)[rows], temps[:-1][rows], temps[1:][rows]))

    def record(self):
        row = dict(column_id=self.column_id, crust_type=self.crust_type, layers=[list(x) for x in self.layers],
                    mass_per_area_kg_m2=list(self.mass_per_area_kg_m2), thickness_m=list(self.thickness_m),
                    formation_age_s=self.formation_age_s, thermal_age_s=self.thermal_age_s,
                    thermal_model=self.thermal.descriptor(), alpha_per_k=ALPHA_PER_K, alpha_origin=ALPHA_LABEL,
                    mantle_density_origin=MANTLE_DENSITY_LABEL,
                    table_bound='thermal_model.max_error_bound_k is table only, not this delivered column',
                    column_bound_k=self.interpolation_bound_k(),
                    column_bound=('derived: max over the 30 sublayers of M_l h_l^2/8 (linear interpolation of a '
                                  "profile with |T''| <= M_l) plus the node error"),
                    curvature_bound_k_m2=list(self.curvature_bound_k_m2), node_error_k=self.node_error_k,
                    node_error=('oceanic: the table bound (nodes interpolated from the table); continental: the '
                                'computed base residual (nodes from the exact layer formula)'))
        if self.volume_convention != V.REFERENCE_PRISM:
            row.update(volume_convention=self.volume_convention, reference_radius_m=self.reference_radius_m,
                       volume_per_area_m=list(self.volume_per_area_m),
                       thermal_interpretation='prescribed initial profile from a planar thermal prior; not radial '
                                              'steady equilibrium or a radial cooling-history solution')
        return row


def _radial_column(column, radius, budget):
    """Author a new column's shell stocks from its actual radial layer boundaries.

    This is only called before the new family's I03 stocks are created. It is
    not a migration of an already-issued material state. Sum each sublayer's
    density separately: a whole-column correction cannot preserve layered mass.
    """
    layers = tuple(V.RadialLayer(radius, float(a), float(b), budget=budget)
                   for a, b in zip(column.depths_m[:-1], column.depths_m[1:]))
    phases = tuple(phase for _, phase, _ in column.layers for _ in range(SUBLAYERS))
    volume = tuple(float(sum((layer.volume_per_area_m for layer, p in zip(layers, phases) if p == phase),
                             Fraction(0))) for phase in PHASES)
    mass = tuple(float(sum((Fraction(float(rho))*layer.volume_per_area_m
                            for layer, rho, p in zip(layers, column.density_kg_m3, phases) if p == phase),
                           Fraction(0))) for phase in PHASES)
    return replace(column, mass_per_area_kg_m2=mass, volume_per_area_m=volume,
                   volume_convention=V.PHYSICAL_RADIAL_SHELL, reference_radius_m=radius)


def _depths(edges):
    """Sublayer boundaries, each layer cut at width*(j/SUBLAYERS) as the tool cuts its knots; interfaces exact."""
    depths = [0.0]
    for i in range(len(edges)-1):
        width = edges[i+1]-edges[i]
        for j in range(1, SUBLAYERS+1):
            depths.append(edges[i+1] if j == SUBLAYERS else edges[i]+width*(j/SUBLAYERS))
    return depths


def continental_sublayers(boundaries_m):
    """(table, sublayer depths, sublayer temperatures) of a three-layer continental column, boundaries top-down.

    The table is continental_profile with the declared conductivities and heat production. The sublayer boundary
    temperatures use the tool's own within-layer formula T = T_top + (q_top - H s/2) s/k at the cuts width*(j/10), so
    every layer interface carries exactly the tool's interface knot and the base is the prescribed base temperature.
    """
    table, surface, flux, layers = _continental(tuple(boundaries_m), CONTINENTAL_CONDUCTIVITY, CONTINENTAL_HEATING,
                                                SURFACE_K, BASE_K)
    if len(layers) != 3:
        _refuse('a continental column has three layers')
    temperatures, top = [surface], surface
    for width, k, heat in layers:
        for j in range(1, SUBLAYERS+1):
            offset = width*(j/SUBLAYERS)
            temperatures.append(top + (flux - 0.5*heat*offset)*(offset/k))
        top = temperatures[-1]
        flux = flux - heat*width
    temperatures[-1] = BASE_K
    return table, _depths(list(table.descriptor()['boundaries_m'])), temperatures


def _column(column_id, crust_type, stack, temperatures, thermal, densities, *, formation_age_s=None,
            thermal_age_s=None, curvature=(), node_error=0.):
    edges = [0.]
    for _, _, thickness, _ in stack:
        edges.append(edges[-1]+thickness)
    depths = _depths(edges)
    density = np.repeat([densities[material] for _, _, _, material in stack], SUBLAYERS)
    widths = [edges[i+1]-edges[i] for i in range(len(stack))]
    crust = [(densities[m], w) for (_, phase, _, m), w in zip(stack, widths) if phase == 'crust']
    lid = [(densities[m], w) for (_, phase, _, m), w in zip(stack, widths) if phase == 'mantle-lid']
    mass = tuple(math.fsum(r*w for r, w in part) for part in (crust, lid))
    thickness = tuple(math.fsum(w for _, w in part) for part in (crust, lid))
    return Column(column_id, crust_type, tuple((name, phase, material) for name, phase, _, material in stack),
                  S._frozen(depths, np.float64), S._frozen(temperatures, np.float64), S._frozen(density, np.float64),
                  S._frozen(np.full(len(density), ALPHA_PER_K), np.float64), mass, thickness, formation_age_s,
                  thermal_age_s, thermal, tuple(float(m) for m in curvature), float(node_error))


def _continental_column(name, draws, densities):
    """A continental column with the New World scenario ranges and labels; the steady geotherm applied once."""
    stream = 'crustal_structure'
    crust = draws.formula(stream, name+'/thickness', lambda u: 30000 + 15000*u, 'crust_m = 30000 + 15000 u')
    litho = draws.formula(stream, name+'/lithosphere', lambda u: 110000 + 40000*u, 'lithosphere_m = 110000 + 40000 u')
    upper = draws.formula(stream, name+'/upper-fraction', lambda u: crust*(.45+.15*u),
                          'upper_m = crust_m (.45 + .15 u)')
    age = draws.formula(stream, name+'/formation', lambda u: (400+2600*u)*MYR_S,
                        'formation_age_s = (400 + 2600 u) Myr (inherited, labelled assumption)')
    stack = [('upper-crust', 'crust', upper, 'rock.granite'),
             ('lower-crust', 'crust', crust-upper, 'rock.gabbro'),
             ('mantle-lid', 'mantle-lid', litho-crust, 'rock.peridotite')]
    edges = [0.]
    for _, _, thickness, _ in stack:
        edges.append(edges[-1]+thickness)
    table, _, temperatures = continental_sublayers(edges)
    curvature = tuple(heat/k for k, heat in zip(CONTINENTAL_CONDUCTIVITY, CONTINENTAL_HEATING))   # |T''| = H/k
    residual = abs(table.descriptor()['computed_base_temperature_residual_k'])
    return _column('continental:'+name, CONTINENTAL, stack, temperatures, table, densities, formation_age_s=age,
                   curvature=curvature, node_error=residual)


def _oceanic_column(plate_id, draws, densities, budget):
    """A plate's ocean: crust 6.2-8.0 km, a 125 km plate, one assumed thermal age; formation age unknown."""
    crust = draws.formula('crustal_structure', 'ocean/%s/thickness' % plate_id, lambda u: 6200+1800*u,
                          'crust_m = 6200 + 1800 u')
    age = draws.formula('thermal_structure', 'ocean/%s/thermal-age' % plate_id, lambda u: (10+110*u)*MYR_S,
                        'assumed thermal age_s = (10 + 110 u) Myr (declared assumption, not a formation age)')
    stack = [('basalt', 'crust', .25*crust, 'rock.basalt'),
             ('gabbro', 'crust', .75*crust, 'rock.gabbro'),
             ('mantle-lid', 'mantle-lid', OCEAN_LITHOSPHERE_M-crust, 'rock.peridotite')]
    edges = [0.]
    for _, _, thickness, _ in stack:
        edges.append(edges[-1]+thickness)
    table = ocean_profile(age, thickness_m=edges[-1], budget=budget)
    temperatures = np.interp(_depths(edges), table.depths_m, table.temperatures_k)
    curvature = (table.descriptor()['curvature_bound_k_m2'],)*3          # ocean_profile's all-depth bound
    return _column('oceanic:'+plate_id, OCEANIC, stack, temperatures, table, densities, thermal_age_s=age,
                   curvature=curvature, node_error=table.max_error_bound_k)


# ----------------------------------------------------------------------------- the plate layout

def minority_sites(plate_count, fraction):
    """n_a of ruling F6', exactly: floor(N s + 1/2) on the Fraction of the binary64 f (s = f, or 1 - f under the
    f > 0.5 swap), rounding half up; clamped to [1, N - 1] when 0 < f < 1; 0 for f = 0 or 1."""
    f = Fraction(float(fraction))
    share = f if f <= Fraction(1, 2) else 1-f
    count = math.floor(plate_count*share+Fraction(1, 2))
    if 0 < f < 1:
        count = min(max(count, 1), plate_count-1)
    return int(count)


def _sites(sphere, plate_count, fraction, provinces, outlines, sutures, draws, rng):
    """Sites in proportion to crust area (ruling F6'): n_a minority sites, then N - n_a free sites, 2 k H_max apart.

    n_a = minority_sites(N, f). Anchors come first: the largest provinces first (majors and fragments alike, by
    decreasing target area) while minority slots remain. A province with an inherited suture offers its first suture's
    mirrored pair (Suture.sites), only while at least two of the n_a slots remain and only if both lie 2 k H_max from
    each other and from every earlier site; otherwise the suture is skipped as a site generator (recorded) and the
    province offers its area centroid alone, kept only if it too is clear (else recorded). Minority slots the anchors
    cannot fill are drawn uniformly inside the minority crust ('minority-drawn', not anchors); free sites are drawn
    uniformly and rejected inside it. Every drawn site (plate_layout, label-keyed draws) is also rejected within 2 k H_max of any site, at most
    MAX_ATTEMPTS each, then refused by name. Containment is exact, on the continuous province polygons.
    """
    separation = 2*rng['floor_k']*H_MAX_M/sphere.radius_m
    target = minority_sites(plate_count, fraction)
    first_suture = {}
    for suture in sutures:
        first_suture.setdefault(suture.province, suture)
    sites, origins, notes = [], [], []

    def clear(candidates):
        for n, x in enumerate(candidates):
            if any(float(_angle(x, y)) < separation for y in sites+candidates[:n]):
                return False
        return True

    for province in sorted(provinces, key=lambda p: (-p.target_area_sr, p.name)):
        room = target-len(sites)
        if not room:
            notes.append('%s anchors no site: no minority slot remains' % province.name)
            continue
        suture = first_suture.get(province.name)
        if suture is not None:
            pair = [np.array(site) for site in suture.sites]
            if room >= 2 and clear(pair):
                for site, label in zip(pair, ('larger', 'mirror')):
                    sites.append(site)
                    origins.append('anchor:%s:%s:%s' % (province.name, suture.suture_id, label))
                continue
            notes.append('%s skipped as a site generator: %s' % (
                suture.suture_id, 'one minority slot remains' if room < 2 else
                'its mirrored pair lies within 2 k H_max of itself or an earlier site'))
        centroid = np.array(province.centroid)
        if clear([centroid]):
            sites.append(centroid)
            origins.append('anchor:'+province.name)
        else:
            notes.append('%s anchors no site: its centroid lies within 2 k H_max of an earlier site' % province.name)

    def drawn(i, prefix, inside, origin, refusal):
        for attempt in range(MAX_ATTEMPTS):
            uz = draws.raw(LAYOUT_STREAM, '%s/%d/%d/z' % (prefix, i, attempt))
            ua = draws.raw(LAYOUT_STREAM, '%s/%d/%d/azimuth' % (prefix, i, attempt))
            z, phi = 2*uz-1, 2*math.pi*ua
            r = math.sqrt(max(0., 1-z*z))
            point = np.array((r*math.cos(phi), r*math.sin(phi), z))
            if any(bool(outline.contains(point)[0]) for outline in outlines) != inside:
                continue
            if not clear([point]):
                continue
            break
        else:
            raise FamilyRefused('%s site %d found no position %s the minority crust and 2 k H_max from every other '
                                'site in %d attempts (%s)' % (origin, i, 'inside' if inside else 'outside',
                                                              MAX_ATTEMPTS, refusal), LAYOUT_REFUSED)
        draws.note(LAYOUT_STREAM, '%s/%d/%d/z' % (prefix, i, attempt), uz, z, 'z = 2u - 1 (accepted attempt)')
        draws.note(LAYOUT_STREAM, '%s/%d/%d/azimuth' % (prefix, i, attempt), ua, phi,
                   'phi = 2 pi u (accepted attempt)')
        sites.append(point)
        origins.append('%s:attempt-%d' % (origin, attempt))

    for i in range(len(sites), target):
        drawn(i, 'minority-site', True, 'minority-drawn', 'MINORITY_SITE')
    for i in range(len(sites), plate_count):
        drawn(i, 'site', False, 'free', 'FREE_SITE')
    return np.array(sites, dtype=np.float64), tuple(origins), tuple(notes), target


def _suture_pairs(origins):
    """The (i, j) site pairs, i < j, mirrored across one suture: the cells whose bisector edge lies on it."""
    groups = {}
    for index, origin in enumerate(origins):
        parts = origin.split(':')
        if parts[0] == 'anchor' and len(parts) == 4:
            groups.setdefault((parts[1], parts[2]), []).append(index)
    return frozenset(tuple(sorted(group)) for group in groups.values() if len(group) == 2)


def off_plane(point, pole):
    """|x.p| / (|x| |p|): the angular distance of a point from the plane normal to ``pole``, numerator exact."""
    x = [Fraction(float(v)) for v in point]
    p = [Fraction(float(v)) for v in pole]
    dot = abs(x[0]*p[0]+x[1]*p[1]+x[2]*p[2])
    return float(dot)/math.sqrt(float(x[0]*x[0]+x[1]*x[1]+x[2]*x[2]))/math.sqrt(float(p[0]*p[0]+p[1]*p[1]+p[2]*p[2]))


def _edge(sites, vertices, i, j, a, b):
    """One Voronoi edge between cells i < j: canonical start, construction, point bound and C-8 term (ruling B2).

    The edge runs from its start by a positive rotation beta about w = (s_i - s_j)/|s_i - s_j|, so cell i is on its
    left (I03's convention). With theta = atan2(|a x b|, a.b) of the stored vertices:

    * theta <= 120 deg: slerp x(t) = sin((1-t) theta)/sin(theta) a + sin(t theta)/sin(theta) b, elementwise and
      reversal symmetric. Its points lie within (eps/2)(2 + 1/cos(theta/2)) of span(a, b) (ruling B2, verified in
      exact rationals); the C-8 term is eps theta (2 + 1/cos(theta/2)) (times R^2).
    * theta > 120 deg: x(t) = C a + S c with c = fl(w x a), C = fl(cos t beta), S = fl(sin t beta). Exactly,
      (w x a).w = 0, so x.w = C (a.w) + S (c - w x a).w plus the rounding of two products and one sum. Each component
      of c carries two product roundings and one difference rounding, |(c - w x a).w| <= (2u + u^2) sqrt(3) |a||w|^2,
      and the products and sum add at most (2u + u^2) sqrt(2) |w| max(|a|, |c|), u = eps/2. For unit inputs the
      distance from the plane normal to w is at most d_a + (sqrt 3 + sqrt 2) eps (1 + O(eps)) < d_a + 4 eps, with d_a
      the start vertex's own exact distance; the end point is the stored vertex (distance d_b). The point bound is
      max(d_a + 4 eps, d_b) and the C-8 term 2 beta bound (times R^2): both levels lie in that band about one plane.

    An edge whose point bound exceeds I03's 64 eps attachment band is refused by name. No minimum edge length.
    """
    w = _normalised(sites[i]-sites[j])
    tangent = np.cross(w, vertices[a])
    beta = math.atan2(float(_dot3(vertices[b], tangent)), float(_dot3(vertices[b], vertices[a])))
    if beta < 0:
        a, b = b, a
        tangent = np.cross(w, vertices[a])
        beta = math.atan2(float(_dot3(vertices[b], tangent)), float(_dot3(vertices[b], vertices[a])))
    va, vb = vertices[a], vertices[b]
    cross = np.cross(va, vb)
    theta = math.atan2(math.sqrt(cross[0]*cross[0]+cross[1]*cross[1]+cross[2]*cross[2]),
                       va[0]*vb[0]+va[1]*vb[1]+va[2]*vb[2])
    if theta <= SLERP_LIMIT_RAD:
        construction, angle = 'slerp', theta
        bound = 0.5*EPS*(2+1/math.cos(theta/2))
        term = EPS*theta*(2+1/math.cos(theta/2))
    else:
        construction, angle = 'rotation', beta
        bound = max(off_plane(va, w)+ROTATION_ROUNDING, off_plane(vb, w))
        term = 2*beta*bound
    if not bound <= POINT_BAND_RAD:
        raise FamilyRefused('Voronoi edge between cells %d and %d: its point bound %.3e rad exceeds I03\'s 64 eps '
                            'attachment band (EDGE_POINT_BOUND)' % (i, j, bound), LAYOUT_REFUSED)
    return dict(cells=(i, j), start=a, end=b, pole=w, tangent=tangent, beta=beta, theta=theta,
                construction=construction, angle=angle, bound=bound, term=term)


def _voronoi(sites):
    """The spherical Voronoi diagram of the sites from their convex hull; every vertex of degree 3.

    Vertices are the hull facets' circumcentre directions in sorted site-triple order (independent of Qhull's facet
    order). Cocircular site sets refuse by name: a set on one great circle has no hull, and bit-equal Voronoi vertices
    (four or more sites on one circle) would need a junction of degree four or more, which v1 refuses.
    """
    try:
        from scipy.spatial import ConvexHull, QhullError
    except ImportError as exc:
        raise FamilyRefused('the spherical Voronoi layout requires the declared SciPy dependency',
                            LAYOUT_REFUSED) from exc
    count = len(sites)
    try:
        hull = ConvexHull(sites)
    except (QhullError, ValueError) as exc:
        raise FamilyRefused('the sites are cocircular or otherwise degenerate: they have no convex hull '
                            '(COCIRCULAR_SITES)', LAYOUT_REFUSED) from exc
    simplices = [tuple(sorted(int(x) for x in row)) for row in hull.simplices]
    if (len(hull.vertices) != count or len(hull.coplanar) or len(simplices) != 2*count-4
            or len(set(simplices)) != len(simplices)):
        raise FamilyRefused('the sites do not form a simplicial hull with every site a vertex (COCIRCULAR_SITES)',
                            LAYOUT_REFUSED)
    order = sorted(range(len(simplices)), key=simplices.__getitem__)
    index = {facet: n for n, facet in enumerate(order)}
    vertices = np.empty((len(order), 3))
    for n, facet in enumerate(order):
        i, j, k = simplices[facet]
        v = np.cross(sites[j]-sites[i], sites[k]-sites[i])
        if float(_dot3(v, hull.equations[facet, :3])) < 0:
            v = -v
        vertices[n] = v/np.linalg.norm(v)
    if len(np.unique(vertices, axis=0)) != len(vertices):
        raise FamilyRefused('bit-equal Voronoi vertices: four or more sites on one circle make a junction of degree '
                            'four or more, refused in v1 (DEGENERATE_VORONOI_VERTEX)', LAYOUT_REFUSED)
    pairs = {}
    for facet, neighbours in enumerate(hull.neighbors):
        for other in neighbours:
            shared = tuple(sorted(set(simplices[facet]) & set(simplices[int(other)])))
            ends = tuple(sorted((index[facet], index[int(other)])))
            if len(shared) != 2 or pairs.setdefault(shared, ends) != ends:
                raise FamilyRefused('a Voronoi vertex is not of degree 3 (DEGENERATE_VORONOI_VERTEX)', LAYOUT_REFUSED)
    if len(pairs) != 3*count-6:
        raise FamilyRefused('the Voronoi diagram is not a degree-3 cell complex (DEGENERATE_VORONOI_VERTEX)',
                            LAYOUT_REFUSED)
    edges = tuple(_edge(sites, vertices, i, j, *pairs[i, j]) for i, j in sorted(pairs))
    by_vertices = {tuple(sorted((e['start'], e['end']))): n for n, e in enumerate(edges)}
    exact = _ints(np.vstack([sites, vertices]))
    cells = []
    for i in range(count):
        site = sites[i]
        axis = np.eye(3)[int(np.argmin(np.abs(site)))]
        e1 = _normalised(np.cross(axis, site))
        e2 = np.cross(site, e1)
        own = [index[f] for f in range(len(simplices)) if i in simplices[f]]
        own.sort(key=lambda v: math.atan2(float(_dot3(vertices[v], e2)), float(_dot3(vertices[v], e1))))
        for a, b in zip(own, own[1:]+own[:1]):
            edge = by_vertices.get(tuple(sorted((a, b))))
            if (edge is None or i not in edges[edge]['cells']
                    or not _det(exact[i], exact[count+a], exact[count+b]) > 0):
                raise FamilyRefused('cell %d is not a counter-clockwise ring of Voronoi edges '
                                    '(DEGENERATE_VORONOI_VERTEX)' % i, LAYOUT_REFUSED)
        cells.append(tuple(own))
    return vertices, tuple(cells), edges


def _arc(edge, vertices, t):
    """The point at dyadic fraction t of a Voronoi edge: one elementwise expression, never a recursive midpoint."""
    if t == 0:
        return vertices[edge['start']]
    if t == 1:
        return vertices[edge['end']]
    t = float(t)
    a = vertices[edge['start']]
    if edge['construction'] == 'slerp':
        b, theta = vertices[edge['end']], edge['theta']
        s = math.sin(theta)
        wa, wb = math.sin((1-t)*theta)/s, math.sin(t*theta)/s
        return np.array([wa*a[0]+wb*b[0], wa*a[1]+wb*b[1], wa*a[2]+wb*b[2]])
    g, angle = edge['tangent'], t*edge['beta']
    c, s = math.cos(angle), math.sin(angle)
    return np.array([c*a[0]+s*g[0], c*a[1]+s*g[1], c*a[2]+s*g[2]])


def _ray(site, point, t):
    """The point at fraction t of the minor arc from a site to a boundary point (rotation form of slerp)."""
    if t == 1:
        return point
    omega = float(_angle(site, point))
    toward = point-float(_dot3(site, point))*site
    toward = toward/np.linalg.norm(toward)
    angle = float(t)*omega
    return math.cos(angle)*site+math.sin(angle)*toward


def _kinds(site_types, suture_pairs, edges):
    """Ruling F6': each plate takes its site's crust type (kinematic labels, an initial-condition prior).

    Continental-site against oceanic-site plates is a trench with the oceanic-site plate subducting; the same type on
    both sides is a ridge (f = 1/2), except the bisector edge of a suture's mirrored pair, a transform without carrier.
    """
    kinds, subducting = [], []
    for edge in edges:
        left, right = (site_types[c] for c in edge['cells'])
        if tuple(edge['cells']) in suture_pairs:
            kinds.append(S.TRANSFORM)
            subducting.append(None)
        elif left == right:
            kinds.append(S.RIDGE)
            subducting.append(None)
        else:
            kinds.append(S.TRENCH)
            subducting.append('left' if left == OCEANIC else 'right')
    return tuple(kinds), tuple(subducting)


# ----------------------------------------------------------------------------- the declared geometry

@dataclass(frozen=True, init=False, eq=False, slots=True)
class DeclaredGeometry(_state._Immutable):
    """The continuous, sampling-independent geometry of one family; ``geometry_id`` covers all of it.

    It holds no subdivision identity, chain or network identity: those change with L (ruling B1).
    """
    radius_m: float
    range: str
    floor_k: float
    background_type: str
    minority_type: str
    counts: MappingProxyType
    provinces: tuple
    sutures: tuple
    sites: np.ndarray = field(repr=False)
    site_origins: tuple = field(repr=False)
    site_types: tuple = field(repr=False)
    anchor_notes: tuple = field(repr=False)
    plate_ids: tuple = field(repr=False)
    voronoi_vertices: np.ndarray = field(repr=False)
    cells: tuple = field(repr=False)
    edge_vertices: np.ndarray = field(repr=False)
    edge_cells: np.ndarray = field(repr=False)
    edge_poles: np.ndarray = field(repr=False)
    edge_angles_rad: np.ndarray = field(repr=False)
    edge_point_bounds_rad: np.ndarray = field(repr=False)
    edge_terms_sr: np.ndarray = field(repr=False)
    edge_constructions: tuple = field(repr=False)
    boundary_ids: tuple = field(repr=False)
    edge_kinds: tuple = field(repr=False)
    edge_subducting: tuple = field(repr=False)
    slabs: tuple = field(repr=False)
    geometry_id: str
    _edges: tuple = field(repr=False)
    _outlines: tuple = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('DeclaredGeometry is issued by starting_family()')

    def record(self):
        return dict(schema=GEOMETRY_SCHEMA, radius_m=self.radius_m, range=self.range, floor_k=self.floor_k,
                    background_type=self.background_type, minority_type=self.minority_type,
                    counts=dict(self.counts), provinces=[p.record() for p in self.provinces],
                    sutures=[s.record() for s in self.sutures], site_origins=list(self.site_origins),
                    site_types=list(self.site_types), anchor_notes=list(self.anchor_notes),
                    plate_ids=list(self.plate_ids), cells=[list(c) for c in self.cells],
                    edge_constructions=list(self.edge_constructions), boundary_ids=list(self.boundary_ids),
                    edge_kinds=list(self.edge_kinds), edge_subducting=list(self.edge_subducting),
                    slabs=[s.record() for s in self.slabs], suture_span_vertices=list(SUTURE_SPAN_VERTICES),
                    suture_sites=SUTURE_SITES, minority_sites_rule=MINORITY_SITES_RULE)

    def arrays(self):
        out = [('sites', self.sites), ('voronoi_vertices', self.voronoi_vertices),
               ('edge_vertices', self.edge_vertices), ('edge_cells', self.edge_cells),
               ('edge_poles', self.edge_poles), ('edge_angles_rad', self.edge_angles_rad),
               ('edge_point_bounds_rad', self.edge_point_bounds_rad), ('edge_terms_sr', self.edge_terms_sr)]
        for p in self.provinces:
            out += [('province:%s:%s' % (p.name, key), getattr(p, key))
                    for key in ('centre', 'outline', 'moment_sr', 'centroid')]
        for s in self.sutures:
            out += [('suture:%s:start' % s.suture_id, s.start), ('suture:%s:end' % s.suture_id, s.end),
                    ('suture:%s:sites' % s.suture_id, s.sites)]
        return tuple(out)

    def boundary_terms_m2(self):
        """Per plate, the C-8 boundary term: R^2 times the exactly rounded sum of its edges' terms (ruling B2)."""
        terms = {plate: [] for plate in self.plate_ids}
        for (left, right), term in zip(self.edge_cells, self.edge_terms_sr):
            terms[self.plate_ids[int(left)]].append(float(term))
            terms[self.plate_ids[int(right)]].append(float(term))
        return {plate: (math.fsum(values)*self.radius_m)*self.radius_m for plate, values in terms.items()}

    def province_at(self, direction):
        """The index of the province holding a direction (closed polygons, exact signs), else None."""
        for index, outline in enumerate(self._outlines):
            if bool(outline.contains(direction)[0]):
                return index
        return None

    def crust_at(self, direction):
        where = self.province_at(direction)
        return self.background_type if where is None else self.provinces[where].crust_type


# ----------------------------------------------------------------------------- sampling on the I03 network

def _point_id(fraction):
    return '%d/%d' % (fraction.numerator, fraction.denominator)


def _sampled(geometry, level, plate_ids, sphere, epoch_id, time_s, budget):
    """The I03 network of one sampling level: edges cut into 2^L arcs and cells fanned in 2^L rings."""
    n = 1 << level
    sites, vertices, edges = geometry.sites, geometry.voronoi_vertices, geometry._edges
    points = {'v:%d' % v: vertices[v] for v in range(len(vertices))}
    chains, by_vertices = [], {}
    for e, edge in enumerate(edges):
        chain = ['v:%d' % edge['start']]
        for k in range(1, n):
            t = Fraction(k, n)
            key = 'e:%d:%s' % (e, _point_id(t))
            points[key] = _arc(edge, vertices, t)
            chain.append(key)
        chain.append('v:%d' % edge['end'])
        chains.append(tuple(chain))
        by_vertices[edge['start'], edge['end']] = tuple(chain)
        by_vertices[edge['end'], edge['start']] = tuple(reversed(chain))
    faces = []
    for i, cell in enumerate(geometry.cells):
        ring = []
        for a, b in zip(cell, cell[1:]+cell[:1]):
            ring.extend(by_vertices[a, b][:-1])
        site_id = 's:%d' % i
        points[site_id] = sites[i]

        def at(r, k):
            if r == 0:
                return site_id
            if r == n:
                return ring[k]
            t = Fraction(r, n)
            key = 'c:%d:%s:%s' % (i, ring[k], _point_id(t))
            if key not in points:
                points[key] = _ray(sites[i], points[ring[k]], t)
            return key
        m = len(ring)
        for k in range(m):
            nk = (k+1) % m
            faces.append(S.Face('f%02d:r%d:k%03d' % (i, 0, k), plate_ids[i], (site_id, at(1, k), at(1, nk))))
            for r in range(1, n):
                faces.append(S.Face('f%02d:r%d:k%03d' % (i, r, k), plate_ids[i],
                                    (at(r, k), at(r+1, k), at(r+1, nk), at(r, nk))))
    origin = S.Origin(S.INITIAL, SCHEMA)
    boundaries = []
    for e, (edge, chain) in enumerate(zip(edges, chains)):
        kind, side = geometry.edge_kinds[e], geometry.edge_subducting[e]
        extra = dict(accretion_fraction=.5) if kind == S.RIDGE else dict(subducting_side=side) if kind == S.TRENCH \
            else {}
        left, right = (plate_ids[c] for c in edge['cells'])
        boundaries.append(S.Boundary(geometry.boundary_ids[e], kind, left, right, chain, origin, **extra))
    plates = tuple(S.Plate(plate, IDENTITY) for plate in plate_ids)
    try:
        return S.build_network(SphericalFrame(sphere.radius_m, FRAME_ID), points, tuple(faces), plates,
                               tuple(boundaries), epoch_id=epoch_id, time_s=time_s, budget=budget)
    except S.SphereError as exc:
        raise FamilyRefused('I03 refused the sampled network (I03_NETWORK): %s' % exc, LAYOUT_REFUSED) from exc


def _occupied(network, geometry, columns, budget):
    """Return the original piece stocks and their actual exact material footprints.

    A face no outline edge can reach (conservative cap certificate) lies wholly inside or outside a province; it is
    taken whole when I03's exact containment (integration_transfer._within) places it inside, never as a remainder.
    A face near an outline is clipped exactly against the province fan triangles its cap can reach, with I03's
    integer triangle clipping, which needs no shared chart; a face that is not a strictly convex fan falls back to
    I03's general exact overlap routine against single fan triangles, and any refusal there is raised by name.
    The same declared face/province rays also retain the clipped polygons, without normalising intersection
    vertices back to binary64. Stock arithmetic is unchanged; background geometry is the exact complement.
    """
    sphere, radius = network.sphere, network.sphere.radius_m
    shapes = T._Shapes(network)
    outlines = geometry._outlines
    owner = {face.face_id: face.plate_id for face in network.faces}
    pieces, footprints = [], {}
    for index, (face_id, measured) in enumerate(zip(network.face_ids, network.face_area_m2)):
        rings = shapes.rings(index)
        own_cells = Q.cells_of_rings(rings)
        centre, reach = T._cap(rings)
        measured = float(measured)
        plate = owner[face_id]
        shares, cells_by_cohort, fan = {}, {}, None
        for k, outline in enumerate(outlines):
            if _caps_apart(centre, reach, outline.centre, outline.radius):
                continue
            near = ~((_angle(outline.edge_centres, centre) > outline.edge_radii+reach+2*BAND)
                     & (outline.edge_radii+BAND < math.pi/2) & (reach+BAND < math.pi/2))
            if not np.any(near):
                if T._within(rings[0], outline.outline, outline.centre) is not True:
                    continue
                area = measured
                support_parts = own_cells
            else:
                if fan is None:
                    corners = _ints(rings[0])
                    fan = [[corners[0], corners[i], corners[i+1]] for i in range(1, len(corners)-1)]
                    if any(_det(*tri) <= 0 for tri in fan):
                        fan = False
                parts, support_parts = [], []
                for j in range(len(outline.tri_rings)):
                    if _caps_apart(centre, reach, outline.tri_centres[j], float(outline.tri_radii[j])):
                        continue
                    support_parts.extend(Q.intersection(own_cells, (tuple(outline.tris[j]),)))
                    if fan:
                        tri = list(outline.tris[j])
                        parts.extend(T._exact_clipped_triangle(own, tri) for own in fan)
                        continue
                    try:
                        parts.append(T._exact_overlap_sr(rings, [outline.tri_rings[j]], sphere, budget=budget))
                    except TectonicsError as exc:
                        raise FamilyRefused('face %s: the exact province intersection refused (PIECE_OVERLAP): %s'
                                            % (face_id, exc), LAYOUT_REFUSED) from exc
                area = (math.fsum(parts)*radius)*radius
                if not area > 0:
                    if support_parts:
                        raise FamilyRefused('face %s: positive province support has no representable stock '
                                            '(PIECE_FOOTPRINT)' % face_id, LAYOUT_REFUSED)
                    continue
            province = geometry.provinces[k]
            cohort = ('continental:'+province.name if province.crust_type == CONTINENTAL
                      else 'oceanic:'+plate)
            shares[cohort] = shares.get(cohort, 0.)+area
            cells_by_cohort.setdefault(cohort, []).extend(support_parts)
        background = 'continental:background' if geometry.background_type == CONTINENTAL else 'oceanic:'+plate
        remaining = Q.difference(own_cells, tuple(cell for cells in cells_by_cohort.values() for cell in cells))
        if remaining:
            cells_by_cohort.setdefault(background, []).extend(remaining)
        rest = measured-math.fsum(shares.values())
        if rest > S.RELATIVE_TOLERANCE*measured:
            shares[background] = shares.get(background, 0.)+rest
        elif shares:
            if rest < -S.RELATIVE_TOLERANCE*measured:
                raise FamilyRefused('face %s: province pieces exceed its measured area (PIECE_OVERLAP)' % face_id,
                                    LAYOUT_REFUSED)
            largest = max(sorted(shares), key=lambda cohort: shares[cohort])
            shares[largest] = measured-math.fsum(v for c, v in shares.items() if c != largest)
        else:
            shares[background] = measured
        if set(shares) != set(cells_by_cohort) or any(not cells for cells in cells_by_cohort.values()):
            raise FamilyRefused('face %s: piece stocks and positive material support have different owners '
                                '(PIECE_FOOTPRINT); no positive fragment is reassigned or erased' % face_id,
                                LAYOUT_REFUSED)
        for cohort in sorted(shares):
            area = shares[cohort]
            column = columns[cohort]
            pieces.append(S.Piece(face_id, cohort, area, tuple(area*m for m in column.mass_per_area_kg_m2),
                                  tuple(area*v for v in (column.volume_per_area_m
                                                        if column.volume_convention == V.PHYSICAL_RADIAL_SHELL
                                                        else column.thickness_m))))
            footprints[face_id, cohort] = Q.ExactFootprint(tuple(sorted(set(cells_by_cohort[cohort]))))
    return pieces, footprints


# ----------------------------------------------------------------------------- the family

@dataclass(frozen=True, init=False, eq=False, slots=True)
class StartingFamily(_state._Immutable):
    """One issued starting family: request, declared geometry, columns, I03 network, material and state.

    Compare families by ``family_id``. ``report()`` returns a fresh copy of the family's report.
    """
    request: FamilyRequest
    geometry: DeclaredGeometry
    columns: MappingProxyType
    network: object
    material: object
    state: object
    family_id: str
    _report: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('StartingFamily is issued by starting_family()')

    def report(self):
        return json.loads(self._report)

    def column_at(self, direction, plate_id):
        """The declared column at a direction on one plate's side, from the continuous polygons: a continental
        province's or the continental background's column, else that plate's ocean."""
        if plate_id not in self.geometry.plate_ids:
            raise FamilyRefused('unknown plate %r' % (plate_id,), LAYOUT_REFUSED)
        where = self.geometry.province_at(direction)
        if where is not None and self.geometry.provinces[where].crust_type == CONTINENTAL:
            return self.columns['continental:'+self.geometry.provinces[where].name]
        if where is None and self.geometry.background_type == CONTINENTAL:
            return self.columns['continental:background']
        return self.columns['oceanic:'+plate_id]


def starting_family(request, *, budget=None):
    """Issue the declared starting family of a request (proposal section 4 with the rulings); refusals are named.

    Every refusal is a FamilyRefused with a code. A request the work budget cannot hold (for example N = 30 or 52 at
    L = 3 under the default 256 MiB) is refused as BUDGET_EXCEEDED (LAYOUT_REFUSED); pass a larger WorkBudget.
    """
    try:
        return _starting_family(request, budget)
    except MemoryLimitError as exc:
        raise FamilyRefused('the family exceeds its work budget (BUDGET_EXCEEDED): %s; pass a larger WorkBudget'
                            % exc, LAYOUT_REFUSED) from exc


def starting_physical_family(request, *, budget=None):
    """Generate fresh physical radial-shell stocks; never reinterpret an old history.

    The prior's temperature profiles remain prescribed initial conditions, not
    solutions of radial conduction. Old ``starting_family`` requests retain
    their explicit reference-prism interpretation and original identities.
    """
    if type(request) is not FamilyRequest:
        raise FamilyRefused('a FamilyRequest is required', INVALID_REQUEST)
    return starting_family(replace(request, volume_convention=V.PHYSICAL_RADIAL_SHELL), budget=budget)


def family_moving(family, records, *, enthalpy_reference_k, budget=None):
    """Attach supplied material laws/history to the sampled family's real columns.

    Heat capacities, conductivities, heat sources and prior plastic/bond histories
    must be supplied, not fabricated from the thermal age or guessed from rock
    names. Each supplied layer must reproduce the generated physical profile.
    I05 then derives heat with that profile's declared volume convention.
    """
    from . import integration_material as M
    if type(family) is not StartingFamily:
        raise FamilyRefused('an issued StartingFamily is required', INVALID_REQUEST)
    if type(records) not in (tuple, list) or any(type(row) is not M.CohortRecord for row in records):
        raise FamilyRefused('explicit CohortRecord records are required', INVALID_REQUEST)
    expected = {c.cohort_id for c in family.material.cohorts}
    if len(records) != len(expected) or {r.cohort_id for r in records} != expected:
        raise FamilyRefused('exactly one record per used family cohort is required', INVALID_REQUEST)
    for record in records:
        column = family.columns[record.cohort_id]
        if (record.volume_convention != column.volume_convention or
                record.reference_radius_m != column.reference_radius_m):
            raise FamilyRefused('material record and family volume geometry differ', INVALID_REQUEST)
        if (column.volume_convention == V.PHYSICAL_RADIAL_SHELL and
                record.radial_depths_m != tuple(float(z) for z in column.depths_m)):
            raise FamilyRefused('material record must retain the sampled radial interfaces', INVALID_REQUEST)
        if len(record.sublayers) != len(column.density_kg_m3):
            raise FamilyRefused('material record must retain every sampled sublayer', INVALID_REQUEST)
        for j, layer in enumerate(record.sublayers):
            _, phase, material_id = column.layers[j//SUBLAYERS]
            actual = (layer.material_id, layer.phase, layer.thickness_m, layer.reference_density_kg_m3,
                      layer.alpha_per_k, layer.top_temperature_k, layer.bottom_temperature_k)
            sampled = (material_id, phase, float(column.depths_m[j+1]-column.depths_m[j]),
                       float(column.density_kg_m3[j]), float(column.alpha_per_k[j]),
                       float(column.temperatures_k[j]), float(column.temperatures_k[j+1]))
            if actual != sampled:
                raise FamilyRefused('material record changes the sampled family profile', INVALID_REQUEST)
    return M.declare_moving(family.state, records, enthalpy_reference_k=enthalpy_reference_k, budget=budget)


def _starting_family(request, budget):
    if type(request) is not FamilyRequest:
        raise FamilyRefused('a FamilyRequest is required', INVALID_REQUEST)
    if request.plate_count < MIN_VORONOI_SITES:
        raise FamilyRefused('N = %d is not supported in v1 (4..52): a spherical Voronoi diagram of three or fewer '
                            'sites has antipodal vertices and half-turn edges (N_UNSUPPORTED)' % request.plate_count,
                            LAYOUT_REFUSED)
    policy = select_budget(budget)
    rng = RANGES[request.range]
    sphere = SphericalFrame(request.radius_m, FRAME_ID)
    radius = sphere.radius_m
    draws = _Draws(request.seed)
    materials, _ = earth_material_library().definitions(ROCKS)
    densities = {m.material_id: float(m.density_kg_m3) for m in materials}
    densities['rock.peridotite'] = MANTLE_REFERENCE_KG_M3
    fraction, now = request.continental_fraction, request.time_s
    background = OCEANIC if fraction <= .5 else CONTINENTAL
    minority = OCEANIC if background == CONTINENTAL else CONTINENTAL

    # Geology: the province polygons, sutures and continental columns read the seed, radius, fraction and range only.
    provinces, counts, outlines = _provinces(sphere, draws, fraction, rng)
    sutures = _sutures(provinces, outlines, draws)
    columns = {}
    for province in provinces:
        if province.crust_type == CONTINENTAL:
            column = _continental_column(province.name, draws, densities)
            columns[column.column_id] = column
    if background == CONTINENTAL:
        column = _continental_column('background', draws, densities)
        columns[column.column_id] = column

    # Plate layout (F6'): minority sites in proportion to crust area, anchored first, then free sites from
    # plate_layout; then the Voronoi plates, each of its site's crust type.
    sites, site_origins, notes, minority_sites = _sites(sphere, request.plate_count, fraction, provinces, outlines,
                                                        sutures, draws, rng)
    site_kinds = tuple(origin.split(':')[0] for origin in site_origins)
    site_types = tuple(minority if kind in ('anchor', 'minority-drawn') else background for kind in site_kinds)
    counts = dict(counts, minority_sites=minority_sites)
    vertices, cells, edges = _voronoi(sites)
    plate_ids = tuple('plate-%02d' % i for i in range(len(sites)))
    if fraction < 1.:
        for plate in plate_ids:
            column = _oceanic_column(plate, draws, densities, policy)
            columns[column.column_id] = column
    if request.volume_convention == V.PHYSICAL_RADIAL_SHELL:
        columns = {key: _radial_column(column, radius, policy) for key, column in columns.items()}
    kinds, subducting = _kinds(site_types, _suture_pairs(site_origins), edges)
    boundary_ids = tuple('b%03d' % e for e in range(len(edges)))
    slabs = []
    for e, edge in enumerate(edges):
        if kinds[e] != S.TRENCH:
            continue
        plate = plate_ids[edge['cells'][0 if subducting[e] == 'left' else 1]]
        column = columns['oceanic:'+plate]
        length = draws.uniform(LAYOUT_STREAM, 'slab/%s/length' % boundary_ids[e], *rng['slab_length_m'])
        deficit = column.mantle_deficit_kg_m2()
        slabs.append(Slab(boundary_ids[e], plate, column.column_id, length, deficit, length*deficit,
                          length*column.mantle_quadrature_bound_kg_m2()))
    geometry = _state._issue(
        DeclaredGeometry, radius_m=radius, range=request.range, floor_k=rng['floor_k'],
        background_type=background, minority_type=minority, counts=MappingProxyType(dict(counts)),
        provinces=provinces, sutures=sutures, sites=S._frozen(sites, np.float64), site_origins=site_origins,
        site_types=site_types, anchor_notes=notes, plate_ids=plate_ids,
        voronoi_vertices=S._frozen(vertices, np.float64), cells=cells,
        edge_vertices=S._frozen([[e['start'], e['end']] for e in edges], np.int64).reshape(-1, 2),
        edge_cells=S._frozen([list(e['cells']) for e in edges], np.int64).reshape(-1, 2),
        edge_poles=S._frozen([e['pole'] for e in edges], np.float64).reshape(-1, 3),
        edge_angles_rad=S._frozen([e['angle'] for e in edges], np.float64),
        edge_point_bounds_rad=S._frozen([e['bound'] for e in edges], np.float64),
        edge_terms_sr=S._frozen([e['term'] for e in edges], np.float64),
        edge_constructions=tuple(e['construction'] for e in edges), boundary_ids=boundary_ids,
        edge_kinds=kinds, edge_subducting=subducting, slabs=tuple(slabs), geometry_id='', _edges=edges,
        _outlines=outlines)
    object.__setattr__(geometry, 'geometry_id', S._identity(S._canonical(geometry.record(), 'family geometry'),
                                                            geometry.arrays()))

    # Sampling: the I03 network of level L, its material pieces and the declared initial state.
    network = _sampled(geometry, request.support_level, plate_ids, sphere, request.epoch_id, now, policy)
    pieces, footprints = _occupied(network, geometry, columns, policy)
    used = sorted({piece.cohort_id for piece in pieces})
    schema = RADIAL_SCHEMA if request.volume_convention == V.PHYSICAL_RADIAL_SHELL else SCHEMA
    label = '%s#%s' % (schema, request.range)
    cohorts = tuple(S.Cohort(cohort, columns[cohort].crust_type+'-lithosphere', '%s:%s' % (label, cohort),
                             *((now-columns[cohort].formation_age_s,)*2 if columns[cohort].formation_age_s is not None
                               else (None, None)))
                    for cohort in used)
    try:
        material = S.build_material(network, phases=PHASES, cohorts=cohorts, pieces=tuple(pieces), budget=policy,
                                    footprints=footprints)
        state = S.initial_sphere(network, material)
    except (S.SphereError, Q.SupportError) as exc:
        raise FamilyRefused('I03 refused the family material (I03_MATERIAL): %s' % exc, LAYOUT_REFUSED) from exc

    # Report: realised quantities, the shares resting on assumed or unknown histories, and every sampled value.
    sphere_m2 = 4*math.pi*radius*radius                      # the C-9 denominator, exactly 4 pi R^2 (ruling B3)
    owner = {face.face_id: face.plate_id for face in network.faces}
    formation = {cohort.cohort_id: cohort.formation_start_s for cohort in cohorts}
    continental, minority_parts, everything, assumed, unknown = {p: [] for p in plate_ids}, [], [], [], []
    for piece in material.pieces():
        crust = columns[piece.cohort_id].crust_type
        everything.append(piece.area_m2)
        if crust == CONTINENTAL:
            continental[owner[piece.face_id]].append(piece.area_m2)
        if crust == minority:
            minority_parts.append(piece.area_m2)
        if columns[piece.cohort_id].thermal is not None:      # every declared geotherm rests on an assumed history
            assumed.append(piece.area_m2)
        if formation[piece.cohort_id] is None:
            unknown.append(piece.area_m2)
    total = math.fsum(everything)
    minority_fraction = math.fsum(minority_parts)/sphere_m2
    polygon_fraction = math.fsum(p.area_sr for p in provinces)/(4*math.pi)
    lengths = [float(a) for a in geometry.edge_angles_rad]
    tally = {kind: [math.fsum(length for length, k in zip(lengths, kinds) if k == kind),
                    sum(1 for k in kinds if k == kind)] for kind in (S.TRENCH, S.RIDGE, S.TRANSFORM)}
    perimeter = math.fsum(lengths)
    column_scale = rng['floor_k']*H_MAX_M/radius
    report = dict(
        schema=schema, status=STATUS, scientific_status=SCIENTIFIC_STATUS, request=request.record(),
        range=request.range, range_parameters=dict(rng), labels=dict(origin=label, boundary_origin=SCHEMA),
        geometry_id=geometry.geometry_id, network_id=network.network_id, material_id=material.material_id,
        state_id=state.state_id, plate_count=len(network.plate_ids),
        realised_continental_fraction=(minority_fraction if minority == CONTINENTAL else 1-minority_fraction),
        fraction_denominator='4 pi R^2 exactly; for f > 0.5, 1 - minority area / 4 pi R^2',
        province_continental_fraction=polygon_fraction if minority == CONTINENTAL else 1-polygon_fraction,
        plate_area_m2=network.plate_area_m2(),
        plate_continental_area_m2={p: math.fsum(v) for p, v in continental.items()},
        c8_boundary_term_m2=geometry.boundary_terms_m2(),
        assumed_thermal_history_share=math.fsum(assumed)/total,
        unknown_formation_age_share=math.fsum(unknown)/total,
        land='UNKNOWN',
        boundary_kinds=dict(zip(boundary_ids, kinds)),
        kind_shares={kind: dict(count=n, count_share=n/len(kinds), length_share=length/perimeter)
                     for kind, (length, n) in tally.items()},
        kind_rule=("F6': each plate takes its site's crust type; continental|oceanic trench (oceanic-site plate "
                   'subducting), same type ridge, suture bisector transform; kinematic only, an initial-condition '
                   'prior'),
        site_types=dict(zip(plate_ids, site_types)), anchor_notes=list(notes),
        site_counts=dict(minority_target=minority_sites, anchored=site_kinds.count('anchor'),
                         minority_drawn=site_kinds.count('minority-drawn'), free=site_kinds.count('free')),
        edges=dict(count=len(edges), slerp=sum(1 for e in edges if e['construction'] == 'slerp'),
                   rotation=sum(1 for e in edges if e['construction'] == 'rotation'),
                   shortest_rad=min(lengths), shortest_m=min(lengths)*radius,
                   shorter_than_column_scale=sum(1 for length in lengths if length < column_scale),
                   column_scale_rad=column_scale,
                   largest_point_bound_rad=float(np.max(geometry.edge_point_bounds_rad))),
        parameters=draws.records,
        declared=dict(
            alpha_per_k=ALPHA_PER_K, alpha_origin=ALPHA_LABEL, conductivity_w_m_k=list(CONTINENTAL_CONDUCTIVITY),
            heat_production_w_m3=list(CONTINENTAL_HEATING), surface_temperature_k=SURFACE_K,
            base_temperature_k=BASE_K, ocean_lithosphere_m=OCEAN_LITHOSPHERE_M, h_max_m=H_MAX_M,
            sublayers_per_layer=SUBLAYERS, outline_vertices=OUTLINE_VERTICES, max_attempts=MAX_ATTEMPTS,
            slerp_limit_rad=SLERP_LIMIT_RAD, point_band_rad=POINT_BAND_RAD, rotation_rounding_rad=ROTATION_ROUNDING,
            suture_span_vertices=list(SUTURE_SPAN_VERTICES), suture_sites=SUTURE_SITES,
            minority_sites_rule=MINORITY_SITES_RULE, prefilter_margin=PREFILTER_MARGIN,
            mantle_datum=dict(mantle_density_kg_m3=MANTLE_DATUM_KG_M3, reference_temperature_k=DATUM_REFERENCE_K,
                              derived_mantle_reference_kg_m3=MANTLE_REFERENCE_KG_M3),
            densities_kg_m3=densities,
            density_origins={'rock.basalt': 'material library', 'rock.gabbro': 'material library',
                             'rock.granite': 'material library', 'rock.peridotite': MANTLE_DENSITY_LABEL}),
        assumptions=[
            'a labelled initial-condition prior, not mechanics, a reconstruction or a calibration',
            'continental fraction is crustal coverage, not dry land; dry land is UNKNOWN (no D5 producer)',
            'ocean formation ages are UNKNOWN; each plate ocean has one declared assumed thermal age (10-120 Ma)',
            'continental geotherms are prescribed steady layered conduction applied once; formation ages inherited',
            'every thermal state rests on an assumed history (CM-02)',
            'sutures carry unknown strength; slab crustal compositional buoyancy is omitted',
            'sites follow crust area (F6\'): floor(N s + 1/2) minority sites, clamped to [1, N - 1] when both '
            'crust types exist; boundary kinds follow the site crust types: kinematic labels only, not mechanics',
            'the RD-05 floor covers the equivalent radius only: elongated or lobed provinces are locally narrower '
            '(minor semi-axis 0.41 k H at e = 6; lobes reach down to 0.0625 of the mean radius)',
            'no family world is advanced with D1 output: generic Voronoi vertices are three-line junctions, which '
            'I03 refuses without supplied junction paths; carrier-less transforms lock their plates; ridges need a '
            'supply per opening side',
            'material mass and volume are planar column values times face area; enthalpy is not carried'])
    if request.volume_convention == V.PHYSICAL_RADIAL_SHELL:
        report['assumptions'][-1] = ('physical radial-shell mass and volume from the sampled layer boundaries; '
                                    'surface areas retain I03 measurement uncertainty; heat is attached by '
                                    'family_moving with supplied thermophysical laws and histories')
        report['assumptions'].append('temperature profiles and slab priors remain prescribed planar-derived '
                                     'initial conditions; no claim of radial thermal equilibrium or spherical '
                                     'force balance; the reference-prism P1 route refuses this family')
    arrays = list(geometry.arrays())
    record_columns = []
    for column_id in sorted(columns):
        column = columns[column_id]
        record_columns.append(column.record())
        arrays += [('column:%s:%s' % (column_id, key), getattr(column, key))
                   for key in ('depths_m', 'temperatures_k', 'density_kg_m3', 'alpha_per_k')]
    record = S._canonical(dict(schema=schema, status=STATUS, request=request.record(), geometry=geometry.record(),
                               columns=record_columns, network_id=network.network_id,
                               material_id=material.material_id, state_id=state.state_id, report=report),
                          'family record')
    return _state._issue(StartingFamily, request=request, geometry=geometry, columns=MappingProxyType(columns),
                         network=network, material=material, state=state, family_id=S._identity(record, arrays),
                         _report=S._canonical(report, 'family report'))


# ----------------------------------------------------------------------------- P1: family columns at the trace

def family_columns(family, support, header, datum):
    """P1 columns of a family at its trace support under one shared Datum: each point's declared column, never averaged.

    Point 2e+s is edge e's midpoint on side s (left, right). The material there comes from the continuous polygons:
    a continental province's (or the continental background's) column, else the side plate's own ocean (its assumed
    thermal age). ``sources`` names each point's cohort. Every refusal is a PortRefused with a code and a detail:

    - network: the support or header names another network -> STALE_IDENTITY ('network_id');
    - support: the header names another support -> INCOMPATIBLE_SUPPORT ('support_id');
    - parent state or family: STALE_IDENTITY ('parent_state_id', 'parameter_id');
    - frame: STALE_IDENTITY ('frame_id');
    - datum: header.datum_id is not this Datum's identity, or this Datum derives a lithospheric-mantle reference
      density other than the family columns' -> STALE_IDENTITY ('datum_id'). The family is declared under rho_m =
      3300 kg/m3 at T_ref = 293.15 K; a different datum is refused, never rebuilt, because the slabs and the I03
      material are on the declared datum, and a silent density jump at the base of the lithosphere is never allowed;
    - time: the endpoint is not the start of the interval and the family time -> UNSUPPORTED (detail: the
      integration_driving evaluation label; Part A is an explicit start-of-interval evaluation).
    """
    if type(family) is not StartingFamily:
        raise P.PortRefused('family columns need an issued StartingFamily', P.UNSUPPORTED, detail='family')
    if family.request.volume_convention != V.REFERENCE_PRISM:
        raise P.PortRefused('physical radial-shell columns cannot use a reference-prism GPE port',
                            P.UNSUPPORTED, detail='volume convention')
    if type(support) is not P.TraceSupport:
        raise P.PortRefused('family columns are evaluated on a P1 trace support', P.INCOMPATIBLE_SUPPORT,
                            detail='support')
    if type(header) is not P.Header or header.port != 'P1':
        raise P.PortRefused('a P1 header is required', P.UNSUPPORTED, detail='header')
    if not isinstance(datum, D.Datum):
        raise P.PortRefused('one shared Datum is required', P.MISSING_VALUE, detail='datum')
    network_id = family.network.network_id
    if support.network_id != network_id or header.network_id != network_id:
        raise P.PortRefused('the support or header names another network', P.STALE_IDENTITY, detail='network_id')
    if header.support_id != support.support_id:
        raise P.PortRefused('the header names another support', P.INCOMPATIBLE_SUPPORT, detail='support_id')
    if header.parent_state_id != family.state.state_id:
        raise P.PortRefused('the header names another parent state', P.STALE_IDENTITY, detail='parent_state_id')
    if header.parameter_id != family.family_id:
        raise P.PortRefused('the header names another family', P.STALE_IDENTITY, detail='parameter_id')
    if header.frame_id != family.network.sphere.frame_id:
        raise P.PortRefused('the header names another frame', P.STALE_IDENTITY, detail='frame_id')
    if header.datum_id != D.datum_id(datum):
        raise P.PortRefused('the header names another datum', P.STALE_IDENTITY, detail='datum_id')
    if not header.endpoint_s == header.interval[2] == family.state.time_s:
        raise P.PortRefused('family columns are declared at the family time only, as an explicit start-of-interval '
                            'evaluation', P.UNSUPPORTED, detail=D.EVALUATION)
    if (datum.mantle_density_kg_m3 != MANTLE_DATUM_KG_M3
            or datum.reference_temperature_k != DATUM_REFERENCE_K):
        # Round-2 decision (a declared v1 limitation): families exist only on the 3300 kg/m3 / 293.15 K datum. Both
        # fields must match exactly, so a twin datum whose derived density happens to agree is refused too.
        raise P.PortRefused('v1 families exist only on the %r kg/m3 / %r K datum' % (MANTLE_DATUM_KG_M3,
                            DATUM_REFERENCE_K), P.STALE_IDENTITY, detail='datum_id')
    reference = mantle_reference_density(datum.mantle_density_kg_m3, datum.reference_temperature_k)
    offsets, values, sources = [0], [[] for _ in range(5)], []
    for e in range(support.edges):
        middle = support.midpoint[e]
        for side in (0, 1):
            try:
                column = family.column_at(middle, support.plates[e][side])
            except FamilyRefused as exc:
                raise P.PortRefused('no declared column at a trace point: %s' % exc, P.UNRESOLVED_COLUMN,
                                    detail=exc.code) from exc
            layer = [phase for _, phase, _ in column.layers].index('mantle-lid')
            lid = column.density_kg_m3[layer*SUBLAYERS:(layer+1)*SUBLAYERS]
            if not np.all(lid == reference):
                raise P.PortRefused('this datum derives a lithospheric-mantle reference density %r kg/m3, but the '
                                    'family columns are declared at %r: a density jump at the base of the '
                                    'lithosphere; refused, not rebuilt' % (reference, float(lid[0])),
                                    P.STALE_IDENTITY, detail='datum_id')
            for target, value in zip(values, column.bottom_to_top()):
                target.append(value)
            offsets.append(offsets[-1]+len(column.density_kg_m3))
            sources.append(column.column_id)
    joined = [np.concatenate(parts) for parts in values]
    return P.columns_port(header, np.asarray(offsets, dtype=np.int64), *joined, sources=tuple(sources))
