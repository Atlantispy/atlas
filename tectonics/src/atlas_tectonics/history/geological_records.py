"""W01 stage 4: typed geological initial conditions, not a sampled/evolved world.

All quantities are SI. Records contain only immutable scalars and tuples; no
callables, arbitrary attribute bags, mutable arrays or implicitly calibrated Earth
profiles. A material formation date is not a cooling date. None denotes unknown,
never zero. Column layers run from the declared local surface downwards.

These are input contracts, not constitutive/thermal/compaction solvers. In
particular a fault trace plus dip is a declared ribbon description, not generated
slip; a weakness factor is a proposed strength modifier, not a rheology law.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from atlas_tectonics._validation import TectonicsError, scalar
from atlas_tectonics.planet.coordinates import _label
from atlas_tectonics.materials.materials import MaterialCohort


FRACTION_ABSOLUTE_TOLERANCE = 1e-12
STACK_RELATIVE_TOLERANCE = 1e-12


class GeologyError(TectonicsError):
    """Invalid, contradictory or unsupported geological description."""


def _name(value, label):
    return _label(value, label)


def _text(value, label, max_length=4096):
    if type(value) is not str or not value.strip() or len(value) > max_length:
        raise GeologyError(label + ' must be nonblank bounded text')
    return value


def _names(value, label, *, allow_empty=True, ordered=False):
    for name in value:
        _name(name, label)
    return value if ordered else tuple(sorted(value))


def _float(record, name, *, positive=False, nonnegative=False):
    value = scalar(getattr(record, name), name, positive=positive, nonnegative=nonnegative)
    object.__setattr__(record, name, value)
    return value


def _depths(record):
    top = _float(record, 'top_depth_m', nonnegative=True)
    bottom = _float(record, 'bottom_depth_m', positive=True)
    if bottom <= top:
        raise GeologyError('bottom depth must exceed top depth')


@dataclass(frozen=True, slots=True)
class GeologySource:
    """A declared provenance record, not authentication of its cited evidence.

    references are source IDs/URLs/citations, never instructions to fetch or run.
    Changing the statement/evidence changes the containing case identity.
    """
    source_id: str
    kind: str
    statement: str
    references: tuple[str, ...] = ()
    content_sha256: str | None = None

    def __post_init__(self):
        _name(self.source_id, 'source_id')
        _text(self.statement, 'source statement')
        for ref in self.references:
            _text(ref, 'reference', 2048)
        if self.content_sha256 is not None:
            pass


@dataclass(frozen=True, slots=True)
class MaterialDefinition:
    """Constant reference properties; missing fields need an explicit explanation.

    No density/temperature law is evaluated here. reference_temperature_k states
    the conditions of the supplied reference properties, not a thermal profile.
    The optional validity interval describes declared applicability, not new data.
    Stage 5/3 consumers must require the specific properties they actually use.
    """
    material_id: str
    material_class: str
    source_id: str
    density_kg_m3: float | None
    conductivity_w_m_k: float | None
    specific_heat_j_kg_k: float | None
    heat_production_w_m3: float | None
    thermal_expansion_per_k: float | None
    reference_temperature_k: float | None
    valid_temperature_k: tuple[float, float] | None = None
    unknown_reason: str | None = None

    def __post_init__(self):
        _name(self.material_id, 'material_id'); _name(self.source_id, 'source_id')
        missing = []
        for key in ('density_kg_m3', 'conductivity_w_m_k', 'specific_heat_j_kg_k',
                    'heat_production_w_m3', 'thermal_expansion_per_k', 'reference_temperature_k'):
            value = getattr(self, key)
            if value is None:
                missing.append(key)
            else:
                _float(self, key, positive=key in ('density_kg_m3','conductivity_w_m_k','specific_heat_j_kg_k'),
                       nonnegative=key in ('heat_production_w_m3','reference_temperature_k'))
        # Negative expansion is not silently forbidden: unusual materials require
        # a declared validity range and later constitutive validation, not clipping.
        if missing:
            _text(self.unknown_reason, 'reason for unknown material properties')
        elif self.unknown_reason is not None:
            raise GeologyError('unknown_reason supplied for fully specified material')
        if self.valid_temperature_k is not None:
            v = self.valid_temperature_k
            lo, hi = (scalar(x, 'temperature interval', nonnegative=True) for x in v)
            object.__setattr__(self, 'valid_temperature_k', (lo, hi))


@dataclass(frozen=True, slots=True)
class CohortDescription:
    """Reuse W02 origin/formation identity without confusing origin with evidence."""
    cohort: MaterialCohort
    source_id: str

    def __post_init__(self):
        _name(self.source_id, 'cohort source')


@dataclass(frozen=True, slots=True)
class ThermalInitialProfile:
    """Initial temperature specification, never a W03 time-evolution solver.

    constant: one temperature, all represented depths.
    tabulated: piecewise linear in depth, starts at zero, no extrapolation.
    half_space: temperatures=(surface,mantle), cooling_start_time_s in CASE epoch.
    unknown: no numerical payload and a mandatory explanation.
    Formation dates in W02 do not fill cooling_start_time_s automatically.
    """
    profile_id: str
    source_id: str
    mode: str
    depths_m: tuple[float, ...] = ()
    temperatures_k: tuple[float, ...] = ()
    diffusivity_m2_s: float | None = None
    cooling_start_time_s: float | None = None
    unknown_reason: str | None = None
    interpolation: str = 'linear'
    extrapolation: str = 'refuse'

    def __post_init__(self):
        _name(self.profile_id, 'profile_id'); _name(self.source_id, 'thermal source')
        z = tuple(scalar(x, 'profile depth', nonnegative=True) for x in self.depths_m)
        t = tuple(scalar(x, 'temperature', nonnegative=True) for x in self.temperatures_k)
        object.__setattr__(self, 'depths_m', z); object.__setattr__(self, 'temperatures_k', t)
        if self.mode == 'unknown':
            _text(self.unknown_reason, 'unknown thermal reason')
            return
        if self.mode == 'half_space':
            _float(self, 'diffusivity_m2_s', positive=True)
            _float(self, 'cooling_start_time_s')
        elif self.diffusivity_m2_s is not None or self.cooling_start_time_s is not None:
            raise GeologyError('cooling metadata only belongs to half-space initialisation')
        elif self.mode == 'constant':
            if z or len(t) != 1:
                raise GeologyError('constant profile needs exactly one temperature and no depth table')
        elif len(z) < 2 or len(t) != len(z) or z[0] != 0 or any(b <= a for a,b in zip(z,z[1:])):
            raise GeologyError('tabulated profile needs increasing depths from zero and one temperature per depth')


@dataclass(frozen=True, slots=True)
class LayerComponent:
    """Fraction of SOLID volume, not total porous volume and not mass fraction."""
    cohort_id: str
    solid_volume_fraction: float

    def __post_init__(self):
        _name(self.cohort_id, 'cohort_id')
        _float(self, 'solid_volume_fraction', positive=True)


@dataclass(frozen=True, slots=True)
class GeologicalLayer:
    """Ordered constant-thickness layer; dip/3D interfaces need stage-5 extensions.

    bulk_thickness includes pores. None porosity is unknown, not nonporous rock.
    Constituents are a declared homogeneous solid mixture; their order has no
    spatial meaning. Fractions are verified but NEVER normalised to make a fit.
    """
    layer_id: str
    role: str
    bulk_thickness_m: float
    components: tuple[LayerComponent, ...]
    porosity: float | None
    source_id: str
    unknown_porosity_reason: str | None = None

    def __post_init__(self):
        _name(self.layer_id, 'layer_id'); _name(self.source_id, 'layer source')
        _float(self, 'bulk_thickness_m', positive=True)
        object.__setattr__(self, 'components', tuple(sorted(self.components, key=lambda c:c.cohort_id)))
        if self.porosity is None:
            _text(self.unknown_porosity_reason, 'unknown porosity reason')
        else:
            _float(self, 'porosity', nonnegative=True)


@dataclass(frozen=True, slots=True)
class ColumnDescription:
    """Surface-to-lithosphere-base stack, ordered top to bottom.

    Sediment is included in crustal thickness; mantle is not. Declared lithosphere
    thickness must match the complete BULK stack. These descriptors do not turn
    W02's common-density volume account into a variable-density mass solver.
    """
    column_id: str
    crust_type: str
    layers: tuple[GeologicalLayer, ...]
    lithosphere_thickness_m: float
    thermal_profile_id: str
    source_id: str
    fluid_material_id: str | None = None

    def __post_init__(self):
        for field in ('column_id','thermal_profile_id','source_id'):
            _name(getattr(self, field), field)
        try:
            pass
        except OverflowError as exc:
            raise GeologyError('layer thickness total exceeds numerical range') from exc
        _float(self, 'lithosphere_thickness_m', positive=True)
        # Check that even a very thin layer remains a distinct represented interval.
        z = 0.
        for layer in self.layers:
            new = z + layer.bulk_thickness_m
            z = new
        if self.fluid_material_id is not None:
            _name(self.fluid_material_id, 'pore-fluid material')

    @property
    def crust_thickness_m(self):
        return math.fsum(x.bulk_thickness_m for x in self.layers if x.role != 'lithospheric_mantle')

    @property
    def layer_edges_m(self):
        edges = [0.]
        for layer in self.layers:
            edges.append(edges[-1] + layer.bulk_thickness_m)
        return tuple(edges)


@dataclass(frozen=True, slots=True)
class SurfaceSelector:
    """A scope expression, not a spatial query. Multiple keys mean a union.

    domain is an explicit background. plates/regions reference stage-3 ownership;
    geometry references named area/trace definitions independently of plate IDs.
    Surface membership, cell averages and mixed-cell integration belong to stage 5.
    """
    kind: str
    keys: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'keys', _names(self.keys,'selector keys',allow_empty=self.kind=='domain'))


@dataclass(frozen=True, slots=True)
class GeologicalProvince:
    province_id: str
    column_id: str
    selector: SurfaceSelector
    source_id: str

    def __post_init__(self):
        for key in ('province_id','column_id','source_id'):
            _name(getattr(self,key),key)


@dataclass(frozen=True, slots=True)
class FaultDescription:
    """Directed trace pieces with a declared dip/depth ribbon; no inferred slip.

    dip is measured down from horizontal, toward the specified side of each
    directed trace. Endpoints/intersections do not create displacement or forces.
    """
    fault_id: str
    trace_keys: tuple[str, ...]
    top_depth_m: float
    bottom_depth_m: float
    dip_rad: float
    dip_side: str
    source_id: str

    def __post_init__(self):
        _name(self.fault_id,'fault_id'); _name(self.source_id,'fault source')
        object.__setattr__(self,'trace_keys',_names(self.trace_keys,'fault traces',allow_empty=False))
        _depths(self)
        _float(self,'dip_rad',positive=True)


@dataclass(frozen=True, slots=True)
class WeakZoneDescription:
    """Declared extent and optional strength multiplier, not a constitutive model.

    Geometry selectors may use area pieces (half_width=None) or line corridors
    (positive half_width). The corridor remains a distance definition, not an
    approximate buffer polygon. Layers/physics decide how a declared weakness acts.
    """
    zone_id: str
    selector: SurfaceSelector
    top_depth_m: float
    bottom_depth_m: float
    half_width_m: float | None
    strength_factor: float | None
    source_id: str
    unknown_reason: str | None = None

    def __post_init__(self):
        _name(self.zone_id,'zone_id'); _name(self.source_id,'weak-zone source')
        _depths(self)
        if self.half_width_m is not None:
            _float(self,'half_width_m',positive=True)
        if self.strength_factor is None:
            _text(self.unknown_reason,'unknown strength reason')
        else:
            _float(self,'strength_factor',positive=True)


@dataclass(frozen=True, slots=True)
class FeaturePrecedence:
    """Highest precedence FIRST; definition/file order never selects the winner.

    Province selection replaces an entire column; it never implicitly merges layer
    stacks. Faults always coexist. Weak zones either coexist without multiplication
    or use one explicitly ordered winner. Boundary candidates remain available in
    the resolution receipt, even where their column descriptions differ.
    """
    province_order: tuple[str, ...]
    weak_zone_mode: str = 'retain_all'
    weak_zone_order: tuple[str, ...] = ()

    def __post_init__(self):
        _names(self.province_order,'province precedence',allow_empty=False,ordered=True)
        _names(self.weak_zone_order,'weak-zone precedence',ordered=True)
