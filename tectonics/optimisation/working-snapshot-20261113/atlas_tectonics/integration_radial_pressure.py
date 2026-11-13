"""Source-bound hydrostatic pressure moments on prescribed physical shells.

This producer does not choose a shared interface traction, free elevation, GPE,
or deforming-material mean stress. Side columns remain separate. Constant
gravity and the retained piecewise-constant thermal-density law are explicit.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
from contextlib import ExitStack
from fractions import Fraction as Q
import hashlib
import json
import math

import numpy as np

from . import integration_driving as D
from . import integration_material as M
from . import integration_patch_heat as PH
from . import integration_ports as P
from . import integration_properties as Properties
from . import integration_state as State
from . import integration_support as Support
from . import integration_volume as V
from .materials import _json
from .resources import select_budget


DATUM_SCHEMA = 'atlas.radial-pressure-datum.v1'
TRACE_SCHEMA = 'atlas.radial-pressure-trace.v1'
MODEL = 'prescribed-radii-constant-g-hydrostatic-pressure'


class RadialPressureRefused(P.PortRefused):
    """Unsupported source, geometry or pressure declaration; no partial port."""


def _refuse(message, detail, code=P.UNSUPPORTED):
    raise RadialPressureRefused(message, code, detail=detail)


def _number(value, name, *, zero=False):
    if isinstance(value, (bool, str, bytes)) or not isinstance(value, (int, float, np.integer, np.floating)):
        _refuse(name+' requires an explicit finite real scalar', name, P.MISSING_VALUE)
    try:
        value = float(value)
    except (ValueError, OverflowError):
        _refuse(name+' is not representable', name)
    if not math.isfinite(value) or (value < 0 if zero else value <= 0):
        _refuse(name+' must be finite and '+('nonnegative' if zero else 'positive'), name)
    return value


@dataclass(frozen=True, slots=True)
class RadialDatum:
    """Fixed spherical source/support radii; the base supplies a normal reaction.

    ``provenance`` declares the surface load (including an explicit zero) and
    radial constraint. The mantle extension is support only, never new stock.
    """
    reference_radius_m: float
    gravity_m_s2: float
    reference_temperature_k: float
    support_radius_m: float
    mantle_density_kg_m3: float
    surface_pressure_pa: float
    provenance: str
    basal_support: str = 'radial_constraint'

    def __post_init__(self):
        for name in ('reference_radius_m', 'gravity_m_s2', 'reference_temperature_k',
                     'support_radius_m', 'mantle_density_kg_m3', 'surface_pressure_pa'):
            object.__setattr__(self, name, _number(getattr(self, name), name, zero=name == 'surface_pressure_pa'))
        if not self.support_radius_m < self.reference_radius_m:
            _refuse('support sphere must lie strictly inside the reference sphere', 'support_radius_m')
        if type(self.provenance) is not str or not self.provenance.strip():
            _refuse('surface load and radial support require explicit provenance', 'provenance', P.MISSING_VALUE)
        if type(self.basal_support) is not str or self.basal_support != 'radial_constraint':
            _refuse('only the explicitly prescribed radial normal constraint is implemented', 'basal_support')

    def record(self):
        return dict(schema=DATUM_SCHEMA, model=MODEL,
                    **{name: getattr(self, name) for name in self.__dataclass_fields__})

    @property
    def datum_id(self):
        return hashlib.sha256(_json(self.record())).hexdigest()


@dataclass(frozen=True, init=False, eq=False, slots=True)
class RadialPressureTrace(State._Immutable):
    """Two separate source-bound sides per material subarc, ordered 2*edge+side.

    ``pressure_moment_n_m`` has units N/m, not torque N m. It is a finite
    binary64 projection of ``exact_pressure_moment_n_m``. Diagnostics include
    support-only mantle rows, explicitly marked and outside material inventory.
    """
    header: P.Header
    datum: RadialDatum
    source_state_id: str
    moving_id: str
    material_id: str
    support_id: str
    patch_ids: tuple
    cohort_ids: tuple
    geometry_ids: tuple
    exact_pressure_moment_n_m: tuple
    exact_support_pressure_pa: tuple
    pressure_moment_n_m: np.ndarray = field(repr=False)
    support_pressure_pa: np.ndarray = field(repr=False)
    layer_offsets: np.ndarray = field(repr=False)
    top_radius_m: np.ndarray = field(repr=False)
    bottom_radius_m: np.ndarray = field(repr=False)
    effective_density_kg_m3: np.ndarray = field(repr=False)
    pressure_top_pa: np.ndarray = field(repr=False)
    pressure_bottom_pa: np.ndarray = field(repr=False)
    layer_pressure_moment_n_m: np.ndarray = field(repr=False)
    mantle_extension: np.ndarray = field(repr=False)
    port_id: str
    _record: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('RadialPressureTrace is issued by radial_pressure_trace()')

    @property
    def points(self):
        return len(self.patch_ids)

    @property
    def datum_id(self):
        return self.datum.datum_id

    def record(self):
        return dict(json.loads(self._record), port_id=self.port_id)


def _finite(value, name):
    try:
        out = float(value)
    except (ValueError, OverflowError):
        _refuse('radial '+name+' is outside finite binary64 evaluation', name)
    if not math.isfinite(out) or (value != 0 and out == 0):
        _refuse('radial '+name+' is outside finite nonzero binary64 evaluation', name)
    return out


def _encoded(value):
    return PH.rational_text(value)


def _integer_bytes(value):
    """Actual rational integer payload, excluding separately charged objects."""
    return (abs(value.numerator).bit_length()+value.denominator.bit_length()+7)//8


def _hex_length(value):
    """Exact character count of PH.rational_text, without allocating a string."""
    return (5+max(1, (abs(value.numerator).bit_length()+3)//4)
            +max(1, (value.denominator.bit_length()+3)//4)+(value < 0))


def _row_data(row):
    geometric, _, _, density, top, bottom, moment, _ = row
    return geometric.top_radius_m, geometric.bottom_radius_m, density, top, bottom, moment


def _retain_row(row, leases, budget):
    geometric, _, temperature, density, top, bottom, moment, _ = row
    values = (geometric.radius_m, geometric.top_depth_m, geometric.bottom_depth_m,
              density, top, bottom, moment)+(() if temperature is None else (temperature,))
    # Fraction/two-int/tuple/geometry/context bookkeeping is bounded by 2048
    # bytes per row; four payload copies cover Python's integer digit layout
    # and the temporary values crossing from arithmetic to retained ownership.
    leases.enter_context(budget.reserve(2048+4*sum(_integer_bytes(v) for v in values),
                                         category='radial-pressure-retained'))


def _column(record, column, patch, heat, sphere, datum, intervals, budget, leases):
    heights, energy, allowances, reference = column
    geometry = M.layer_geometry(record, heights, budget=budget)
    if geometry[0].top_depth_m != 0 or geometry[-1].bottom_radius_m < Q(datum.support_radius_m):
        _refuse('the prescribed support sphere must underlie the actual surface-bound source column',
                'support_radius_m', P.INCOMPATIBLE_SUPPORT)
    piece = Support.piece_of(patch, sphere.material.phases)
    ratios = M._thickness_ratios(record, piece, sphere.material.phases, budget=budget)
    M._check_reference_mass(record, piece, ratios, sphere.material.phases, intervals, budget=budget)
    if any(abs(q-patch.stock[0]*u) > allowance for q, u, allowance in zip(heat, energy, allowances)):
        _refuse('physical field and exact source heat exceed their operation allowance', 'physical_columns')
    pressure, gravity = Q(datum.surface_pressure_pa), Q(datum.gravity_m_s2)
    rows, total = [], Q(0)
    for index, (layer, geometric, u) in enumerate(zip(record.sublayers, geometry, energy)):
        # Reuse the geometry owner's rational-operation envelope, with the
        # CURRENT cumulative pressure/moment widths. Only this layer is active;
        # other columns' scratch is not reserved simultaneously.
        with V._work((u, reference, layer.reference_density_kg_m3, layer.heat_capacity_j_kg_k,
                      layer.alpha_per_k, datum.reference_temperature_k, pressure, gravity, total,
                      geometric.radius_m, geometric.top_depth_m, geometric.bottom_depth_m), budget):
            capacity = Q(layer.reference_density_kg_m3)*Q(layer.heat_capacity_j_kg_k)*geometric.volume_per_area_m
            # Never reconstruct temperature from rounded extensive heat or the
            # original cohort endpoints after a physical local source has acted.
            temperature = Q(reference)+u/capacity
            anomaly = Q(layer.alpha_per_k)*(temperature-Q(datum.reference_temperature_k))
            if temperature <= 0 or abs(anomaly) > Q(D.POLICY['max_density_anomaly']):
                _refuse('temperature/density lies outside the retained Boussinesq support', 'density anomaly')
            density = Q(layer.reference_density_kg_m3)*(1-anomaly)
            bottom = pressure+density*gravity*geometric.thickness_m
            moment = geometric.integrate_linear_per_area(pressure, bottom)
            row = (geometric, index, temperature, density, pressure, bottom, moment, False)
            _retain_row(row, leases, budget)
            rows.append(row)
            total += moment
            pressure = bottom
    last = geometry[-1]
    if last.bottom_radius_m > Q(datum.support_radius_m):
        geometric = V.RadialLayer(datum.reference_radius_m, last.bottom_depth_m,
                                  Q(datum.reference_radius_m)-Q(datum.support_radius_m), budget=budget)
        with V._work((datum.mantle_density_kg_m3, pressure, gravity, total, geometric.radius_m,
                      geometric.top_depth_m, geometric.bottom_depth_m), budget):
            density = Q(datum.mantle_density_kg_m3)
            bottom = pressure+density*gravity*geometric.thickness_m
            moment = geometric.integrate_linear_per_area(pressure, bottom)
            row = (geometric, None, None, density, pressure, bottom, moment, True)
            _retain_row(row, leases, budget)
            rows.append(row)
            total += moment
            pressure = bottom
    leases.enter_context(budget.reserve(512+4*(_integer_bytes(total)+_integer_bytes(pressure)),
                                         category='radial-pressure-retained'))
    return tuple(rows), total, pressure


def radial_pressure_trace(moving, sphere, support, header, datum, *, budget=None):
    """Produce exact sided hydrostatic moments from retained physical shell fields.

    No central trace, gamma, GPE, free elevation, P2 stress closure, or basal
    tangential resistance is selected here. The radial constraint's reaction is
    published; for rigid rotations its normal traction has zero torque/work.
    """
    Properties._endpoint(moving, sphere, header, 'P1')
    if type(datum) is not RadialDatum or header.datum_id != datum.datum_id:
        _refuse('one exactly bound RadialDatum is required', 'datum_id', P.STALE_IDENTITY)
    if datum.reference_radius_m != sphere.network.sphere.radius_m:
        _refuse('datum radius differs from the actual source sphere', 'reference_radius_m', P.STALE_IDENTITY)
    if (type(support) is not P.TraceSupport or support.material_id != sphere.material.material_id or
            support.network_id != sphere.network.network_id or header.support_id != support.support_id or
            support.radius_m != datum.reference_radius_m or support.patch_ids is None):
        _refuse('a material-resolved trace of this exact source is required', 'support', P.INCOMPATIBLE_SUPPORT)
    if moving._physical_columns is None or moving._patch_heat is None:
        _refuse('historical means do not establish physical source columns', 'physical_columns')
    records = {r.cohort_id: r for r in moving.cohorts}
    if any(r.volume_convention != V.PHYSICAL_RADIAL_SHELL or
           r.reference_radius_m != datum.reference_radius_m for r in records.values()):
        _refuse('all source records must explicitly declare this physical shell radius', 'volume_convention')
    patches = Support.required(sphere.material).patches
    resource = select_budget(budget)
    # Lookup/reference arrays precede exact pressure arithmetic and remain live
    # while its separately charged output is assembled.
    with resource.reserve(65536+512*(len(patches)+len(moving._physical_columns)+len(moving._patch_heat)
                                     +2*support.edges), category='radial-pressure-source'):
        return _assemble(moving, sphere, support, header, datum, records, patches, resource)


def _assemble(moving, sphere, support, header, datum, records, patches, resource):
    lookup = {p.patch_id: p for p in patches}
    points = tuple(key for pair in support.patch_ids for key in pair)
    if len(points) != 2*support.edges or not 0 < len(points) <= P.MAX_POINTS or any(p not in lookup for p in points):
        _refuse('every trace side must name an actual patch', 'patch_ids', P.INCOMPATIBLE_SUPPORT)
    fields, heat = dict(moving._physical_columns), dict(moving._patch_heat)
    count = sum(len(records[lookup[p].cohort_id].sublayers)+1 for p in points)
    # Float arrays, row/dictionary objects, and repeated reference lists. Exact
    # cached rows and temporary arithmetic are independently accounted below;
    # neither is multiplied by every occurrence of a source patch on the trace.
    size = 65536+2048*len(points)+4096*count
    with resource.reserve(size, category='radial-pressure-trace'), ExitStack() as retained:
        owners = {f.face_id: f.plate_id for f in sphere.network.faces}
        for edge, pair in enumerate(support.patch_ids):
            for side, key in enumerate(pair):
                patch = lookup[key]
                if ((patch.face_id, patch.cohort_id) != tuple(support.piece_keys[edge][side]) or
                        owners[patch.face_id] != support.plates[edge][side]):
                    _refuse('trace side and retained source owner differ', 'patch_ids', P.INCOMPATIBLE_SUPPORT)
        cache, rows, offsets, moments, pressures, ids, cohorts = {}, [], [0], [], [], [], []
        for key in points:
            patch = lookup[key]
            if key not in cache:
                h, u, allowance = fields[key]
                # This column's source-check/geometry references remain live
                # during its layer arithmetic, then are released before the
                # next unique column. No maximum-layer multiplier is applied.
                source_bytes = sum(_integer_bytes(q) for q in (*u, *allowance, *heat[key], *patch.stock))
                with resource.reserve(65536+4096*len(h)+64*source_bytes,
                                      category='radial-pressure-column'):
                    cache[key] = _column(records[patch.cohort_id], (h, u, allowance, moving.enthalpy_reference_k),
                        patch, heat[key], sphere, datum, moving.step-moving.declared_step, resource, retained)
            column, moment, pressure = cache[key]
            rows.extend(column); offsets.append(len(rows)); moments.append(moment); pressures.append(pressure)
            ids.append(tuple(row[0].layer_id for row in column)); cohorts.append(patch.cohort_id)
        # Preflight every repeated encoded output BEFORE building its strings.
        # 1024 ASCII bytes/row bounds fixed keys, punctuation and geometry labels;
        # rational text lengths below are exact. Source names allow up to twelve
        # escaped ASCII bytes per Unicode character. Eight complete encodings
        # cover retained strings, encoder chunks/joined text, UTF-8 and identity
        # copies; Python row/array/object overhead is charged above separately.
        encoded = 16384+12*len(datum.provenance)
        for row in rows:
            geometric, _, temperature, _, _, _, _, _ = row
            numbers = _row_data(row)+(geometric.radius_m, geometric.top_depth_m, geometric.bottom_depth_m)
            if temperature is not None:
                numbers += (temperature,)
            encoded += 1024+sum(_hex_length(q) for q in numbers)
        for key, cohort, geometry, moment, pressure in zip(points, cohorts, ids, moments, pressures):
            encoded += 1024+12*(len(key)+len(cohort))+68*len(geometry)+_hex_length(moment)+_hex_length(pressure)
        retained.enter_context(resource.reserve(8*encoded, category='radial-pressure-encoding'))
        names = ('top_radius_m', 'bottom_radius_m', 'effective_density_kg_m3', 'pressure_top_pa',
                 'pressure_bottom_pa', 'layer_pressure_moment_n_m')
        values = [[] for _ in names]
        diagnostics = []
        for geometric, index, temperature, density, top, bottom, moment, mantle in rows:
            data = _row_data((geometric, index, temperature, density, top, bottom, moment, mantle))
            for target, name, value in zip(values, names, data):
                target.append(_finite(value, name))
            diagnostics.append(dict(geometry=geometric.record(), source_sublayer=index,
                source_temperature_exact_k=None if temperature is None else _encoded(temperature),
                **{name: _encoded(value) for name, value in zip(names, data)}, mantle_extension=mantle))
        arrays = {name: P._frozen(value, np.float64) for name, value in zip(names, values)}
        arrays.update(pressure_moment_n_m=P._frozen([_finite(v, 'pressure moment') for v in moments], np.float64),
            support_pressure_pa=P._frozen([_finite(v, 'support pressure') for v in pressures], np.float64),
            layer_offsets=P._frozen(offsets, np.int64), mantle_extension=P._frozen([row[-1] for row in rows], np.bool_))
        record = dict(schema=TRACE_SCHEMA, model=MODEL, header=header.record(), datum=datum.record(),
            datum_id=datum.datum_id, source_state_id=sphere.state_id, moving_id=moving.moving_id,
            material_id=sphere.material.material_id, support_id=support.support_id, patch_ids=list(points),
            cohort_ids=cohorts, geometry_ids=ids, layer_offsets=offsets, layer_rows=diagnostics,
            pressure_moment_exact_n_m=[_encoded(v) for v in moments],
            support_pressure_exact_pa=[_encoded(v) for v in pressures],
            units=dict(pressure_moment_n_m='N/m', pressure='Pa', radius='m'),
            thermal_representation='retained exact areal heat; one volume-mean temperature per actual sublayer',
            support_ownership='mantle extension is support-only; no material, mass or heat is added',
            basal_normal_reaction='required hydrostatic pressure at the prescribed common support sphere',
            interface_rule=None, source_inventory_unchanged=True)
        return State._issue(RadialPressureTrace, header=header, datum=datum, source_state_id=sphere.state_id,
            moving_id=moving.moving_id, material_id=sphere.material.material_id, support_id=support.support_id,
            patch_ids=points, cohort_ids=tuple(cohorts), geometry_ids=tuple(ids),
            exact_pressure_moment_n_m=tuple(moments), exact_support_pressure_pa=tuple(pressures),
            port_id=P._digest(record, tuple(sorted(arrays.items()))), _record=_json(record), **arrays)
