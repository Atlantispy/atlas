"""W03.2: thermal density, reference-column load and one local support owner.

First-order Boussinesq/isostatic diagnostics, not a variable-density mass update.
No empirical age-depth offset, flexural displacement or mechanical force is added.
See docs/W03_THERMAL_SUPPORT.md for equations, references and validity limits.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
import math

import numpy as np

from ._validation import TectonicsError, read_array, input_shape, frozen, scalar, text
from .constitutive import BoussinesqMaterial
from .parameters import PlateCoolingParameters, identity
from .resources import elements, select_budget
from .stokes_execution import _factored_scale
from .thermal import _batch_count, DEFAULT_COOLING_BATCH_ELEMENTS


@dataclass(frozen=True, slots=True)
class ThermalSupportParameters:
    """One declared thermal-support owner and a fixed compensation/fill model.

    The material's EOS reference and this elevation/reference-column datum are
    different concepts. max_relative_deflection is the caller's validity limit,
    not a clamp or a claim that any chosen limit is empirically calibrated.
    """
    reference_id: str
    provenance: str
    depth_reference_id: str
    thermal_owner: str
    compensation_density_kg_m3: float
    fill_density_kg_m3: float
    gravity_m_s2: float
    max_relative_deflection: float

    def __post_init__(self):
        for key in ('reference_id', 'provenance', 'depth_reference_id'):
            text(getattr(self, key), key)
        if type(self.thermal_owner) is not str or self.thermal_owner not in ('column-isostasy', 'mechanical-buoyancy', 'flexure', 'empirical-age-depth'):
            raise TectonicsError('one explicit thermal support owner required')
        for key in ('compensation_density_kg_m3', 'gravity_m_s2', 'max_relative_deflection'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, positive=True))
        object.__setattr__(self, 'fill_density_kg_m3', scalar(self.fill_density_kg_m3, 'fill density', nonnegative=True))
        if self.fill_density_kg_m3 >= self.compensation_density_kg_m3:
            raise TectonicsError('positive mantle/fill restoring density contrast required')
        if self.max_relative_deflection >= 1:
            raise TectonicsError('small-deflection validity envelope must be below column thickness')

    @property
    def restoring_density_contrast_kg_m3(self):
        return self.compensation_density_kg_m3-self.fill_density_kg_m3


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError()


def _material(material):
    if type(material) is not BoussinesqMaterial:
        raise TectonicsError('explicit BoussinesqMaterial required')


def _owner(parameters):
    if type(parameters) is not ThermalSupportParameters:
        raise TectonicsError('explicit ThermalSupportParameters required')
    if parameters.thermal_owner != 'column-isostasy':
        raise TectonicsError('thermal support already assigned to '+parameters.thermal_owner+'; cannot also apply column isostasy')


def _temperature(T, material):
    if np.any((T < material.temperature_range_k[0]) | (T > material.temperature_range_k[1])):
        raise TectonicsError('temperature outside material validity interval')
    # This is the SAME linear thermal term used by boussinesq_response; its
    # compositional term is not thermal support and is deliberately not added.
    with np.errstate(over='ignore', invalid='ignore'):
        fraction = material.expansion_per_k*(T-material.reference_temperature_k)
    if not np.isfinite(fraction).all() or np.any(np.abs(fraction) > material.max_relative_density_anomaly):
        raise TectonicsError('thermal density outside Boussinesq validity envelope')
    return fraction


def thermal_density(temperature_k, material, *, budget=None, cancel=None):
    """rho0[1-alpha(T-T0)] in kg/m3; thermal-only (composition reference C=0).

    Diagnostic density for buoyancy, not a replacement for W02's conserved mass
    reference. Constant alpha is volumetric, not a linear length expansion value.
    """
    _material(material); _cancel(cancel)
    shape = input_shape(temperature_k)
    with select_budget(budget).reserve(64*elements(shape)+8192, category='thermal-density'):
        T = read_array(temperature_k, 'temperature_k')
        if T.shape != shape:
            raise TectonicsError('temperature shape changed during capture')
        fraction = _temperature(T, material)
        density = _factored_scale(1-fraction, (material.density_kg_m3,), (), 'thermal density')
        _cancel(cancel)
        return frozen(density)


def thermal_column_work_bytes(temperature_shape, reference_shape, edge_shape,
                              batch_elements=DEFAULT_COOLING_BATCH_ELEMENTS):
    batch = _batch_count(batch_elements)
    try:
        shape = np.broadcast_shapes(temperature_shape, reference_shape)
    except ValueError as exc:
        raise TectonicsError('column temperatures cannot broadcast') from exc
    if not shape or not elements(shape) or edge_shape != (shape[-1]+1,):
        raise TectonicsError('temperature final axis needs matching depth edges')
    rows = elements(shape)//shape[-1]
    return (64*(elements(temperature_shape)+elements(reference_shape)+elements(edge_shape))
            + 128*rows + 256*min(elements(shape), batch) + 8192)


def _response(mean_temperature_change, thickness, material, parameters):
    """Packed sheet anomaly [kg/m2], pressure [Pa], downward displacement [m]."""
    output = np.zeros(mean_temperature_change.shape+(3,))
    if material.expansion_per_k == 0:
        return output
    factors = (material.density_kg_m3, material.expansion_per_k, thickness)
    output[..., 0] = _factored_scale(mean_temperature_change, factors, (), 'thermal sheet anomaly')
    output[..., 1] = _factored_scale(mean_temperature_change, factors+(parameters.gravity_m_s2,), (), 'thermal load')
    output[..., 2] = _factored_scale(mean_temperature_change, factors,
        (parameters.restoring_density_contrast_kg_m3,), 'local thermal displacement')
    relative = _factored_scale(np.abs(output[..., 2]), (), (thickness,), 'relative thermal displacement')
    if np.any(relative > parameters.max_relative_deflection):
        raise TectonicsError('local support exceeds supplied small-deflection validity envelope')
    return output


def thermal_column_response(temperature_k, reference_temperature_k, depth_edges_m,
                            material, parameters, *, budget=None,
                            batch_elements=DEFAULT_COOLING_BATCH_ELEMENTS, cancel=None):
    """Integrate true cell means against a reference of identical geometry/material.

    Output final axis: (buoyancy sheet anomaly kg/m2, downward load Pa,
    TOTAL downward displacement from the named reference m). Positive is cooling/
    sinking. No new material mass is created and no elevation array is mutated.
    Both temperature fields must be supplied, not inferred from the EOS T0.
    Generic cell means do not certify unknown subcell temperature extrema.
    """
    _material(material); _owner(parameters); _cancel(cancel)
    ts, rs, es = input_shape(temperature_k), input_shape(reference_temperature_k), input_shape(depth_edges_m)
    required = thermal_column_work_bytes(ts, rs, es, batch_elements)
    with select_budget(budget).reserve(required, category='thermal-column-support'):
        T = read_array(temperature_k, 'temperature_k')
        R = read_array(reference_temperature_k, 'reference_temperature_k')
        edges = read_array(depth_edges_m, 'depth_edges_m', nonnegative=True)
        if T.shape != ts or R.shape != rs or edges.shape != es:
            raise TectonicsError('column shape changed during capture')
        widths = np.diff(edges)
        if edges[0] != 0 or np.any(widths <= 0):
            raise TectonicsError('positive-down column edges must start at zero and increase')
        _temperature(T, material); _temperature(R, material)
        shape = np.broadcast_shapes(ts, rs); cells = shape[-1]
        thickness = float(edges[-1])
        weights = _factored_scale(widths, (), (thickness,), 'normalised cell thickness')
        means = np.zeros(elements(shape)//cells); compensation = np.zeros_like(means)
        # C-order buffered traversal bounds scratch even for noncontiguous or
        # broadcast inputs. Compensate joins across chunks of the same column.
        offset = 0
        with np.nditer([T, R, weights], flags=['external_loop', 'buffered'],
                op_flags=[['readonly']]*3, order='C', buffersize=min(batch_elements, elements(shape))) as iterator:
            for current, reference, weight in iterator:
                _cancel(cancel)
                difference = reference-current
                values = difference*weight
                if material.expansion_per_k != 0 and np.any((difference != 0) & (values == 0)):
                    raise TectonicsError('nonzero weighted temperature contribution is unrepresentable')
                starts = np.r_[0, np.arange(cells-offset % cells, values.size, cells)]
                sums = np.add.reduceat(values, starts)
                row = np.arange(offset//cells, offset//cells+len(starts))
                corrected = sums-compensation[row]
                total = means[row]+corrected
                compensation[row] = (total-means[row])-corrected
                means[row] = total
                offset += values.size
        response = _response(means.reshape(shape[:-1]), thickness, material, parameters)
        return frozen(response)


def _plate_material(plate, material, parameters):
    _material(material); _owner(parameters)
    if type(plate) is not PlateCoolingParameters:
        raise TectonicsError('explicit PlateCoolingParameters required')
    # Maximum principle: check the entire analytic temperature interval, not just
    # a warm cell mean which could conceal an invalid cold surface or hot base.
    _temperature(np.array([plate.thermal.surface_temperature_k, plate.thermal.mantle_temperature_k]), material)
    if (not math.isclose(material.conductivity_w_m_k, plate.conductivity_w_m_k, rel_tol=1e-12)
            or not math.isclose(material.density_kg_m3*material.heat_capacity_j_kg_k,
                                plate.volumetric_heat_capacity_j_m3_k, rel_tol=1e-12)):
        raise TectonicsError('cooling and density material need the same conductivity and reference heat capacity')
    if material.internal_heating_w_m3 != 0:
        raise TectonicsError('finite-plate cooling does not include internal heating')


def plate_thermal_response(age_s, reference_age_s, plate, material, parameters, *,
                           budget=None, batch_elements=DEFAULT_COOLING_BATCH_ELEMENTS, cancel=None):
    """Exact whole-column integral of the selected linear finite-plate model.

    Same packed output as thermal_column_response, without constructing a depth
    grid or subtracting rounded absolute densities/old limiting temperatures.
    Age differences may be negative, producing warming/uplift relative to reference.
    """
    from .plate_integrals import plate_cooling_deficit_change
    _plate_material(plate, material, parameters); _cancel(cancel)
    try:
        shape = np.broadcast_shapes(input_shape(age_s), input_shape(reference_age_s))
    except ValueError as exc:
        raise TectonicsError('cooling/reference ages cannot broadcast') from exc
    resource = select_budget(budget)
    with resource.reserve(128*elements(shape)+8192, category='plate-thermal-support'):
        change = plate_cooling_deficit_change(age_s, reference_age_s, plate, budget=resource,
            batch_elements=batch_elements, cancel=cancel)
        result = _response(change, plate.thickness_m, material, parameters)
        _cancel(cancel)
        return frozen(result)


@dataclass(frozen=True, slots=True)
class ThermalSupportColumns:
    """Named reference-to-current diagnostic; never an accumulated elevation step."""
    source_state_id: str
    epoch_id: str
    depth_reference_id: str
    time_s: float
    reference_time_s: float
    reference_id: str
    thermal_owner: str
    profile_ids: tuple[str, ...]
    history_source_ids: tuple[str, ...]
    cooling_model_ids: tuple[str, ...]
    material_ids: tuple[str, ...]
    support_policy_id: str
    cooling_age_s: np.ndarray
    reference_cooling_age_s: np.ndarray
    buoyancy_sheet_kg_m2: np.ndarray
    downward_load_pa: np.ndarray
    downward_displacement_from_reference_m: np.ndarray


def thermal_support_columns(initial_state, cooling_models, materials, parameters, *,
                            time_s, reference_time_s, epoch_id, store=None, budget=None,
                            context=None, controller=None, cache_policy=None, cancel=None):
    """Source-bound W03 cooling histories -> one total local thermal response.

    Maps explicitly select cooling and material models for the same profile IDs.
    Same geometry/composition/fill and named compensation datum at both times;
    original W01 temperature and W02 volume/mass records remain unchanged. The
    reference is the selected cooling model at reference_time_s, not a claim of
    equality to the original authored initial temperature field.
    """
    from .precursor import PrecursorState
    from .reuse import cached_plate_thermal_response
    from .storage import ArrayStore
    _owner(parameters); _cancel(cancel)
    if not isinstance(initial_state, PrecursorState):
        raise TectonicsError('source-bound PrecursorState required')
    if epoch_id != initial_state.case.epoch_id or parameters.depth_reference_id != initial_state.case.depth_reference_id:
        raise TectonicsError('thermal support epoch/depth datum mismatch')
    time_s = scalar(time_s, 'time_s'); reference_time_s = scalar(reference_time_s, 'reference_time_s')
    if min(time_s, reference_time_s) < initial_state.case.time_s:
        raise TectonicsError('support/reference evaluation predates source state')
    if type(cooling_models) is not dict or not cooling_models or type(materials) is not dict or set(materials) != set(cooling_models):
        raise TectonicsError('explicit matching nonempty cooling/material profile maps required')
    history = {h.profile_id: h for h in initial_state.cooling_history}
    if any(type(k) is not str or k not in history for k in cooling_models):
        raise TectonicsError('unknown cooling profile selected')
    profiles = tuple(sorted(cooling_models)); ages = []; reference_ages = []
    sources = []; model_ids = []; material_ids = []; groups = {}
    for i, profile in enumerate(profiles):
        plate = cooling_models[profile]; material = materials[profile]
        _plate_material(plate, material, parameters)
        h = history[profile]
        if h.start_time_s is None:
            raise TectonicsError('unknown cooling history: '+profile+'; '+h.unknown_reason)
        ages.append(scalar(time_s-h.start_time_s, 'cooling age', nonnegative=True))
        reference_ages.append(scalar(reference_time_s-h.start_time_s, 'reference cooling age', nonnegative=True))
        if time_s != reference_time_s and ages[-1] == reference_ages[-1]:
            raise TectonicsError('distinct evaluation times collapse to one representable cooling age')
        sources.append(h.source_id); model_ids.append(identity(plate)); material_ids.append(identity(material))
        groups.setdefault((model_ids[-1], material_ids[-1]), []).append(i)
    if budget is None and isinstance(store, ArrayStore):
        budget = store._budget
    resource = select_budget(budget)
    with resource.reserve(256*len(profiles)+8192, category='thermal-support-columns'):
        response = np.empty((len(profiles), 3))
        for indices in groups.values():
            _cancel(cancel)
            profile = profiles[indices[0]]
            response[indices] = cached_plate_thermal_response(
                [ages[i] for i in indices], [reference_ages[i] for i in indices],
                cooling_models[profile], materials[profile], parameters, store=store,
                budget=resource, context=context, controller=controller, cache_policy=cache_policy, cancel=cancel)
        return ThermalSupportColumns(initial_state.state_id, epoch_id, parameters.depth_reference_id,
            time_s, reference_time_s, parameters.reference_id, parameters.thermal_owner,
            profiles, tuple(sources), tuple(model_ids), tuple(material_ids), identity(parameters),
            frozen(ages), frozen(reference_ages), frozen(response[:, 0]), frozen(response[:, 1]), frozen(response[:, 2]))
