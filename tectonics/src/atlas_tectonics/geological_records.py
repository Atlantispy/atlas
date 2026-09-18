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

from ._validation import TectonicsError, scalar
from .coordinates import _label
from .materials import MaterialCohort


FRACTION_ABSOLUTE_TOLERANCE = 1e-12
STACK_RELATIVE_TOLERANCE = 1e-12


class GeologyError(TectonicsError):
    """Invalid, contradictory or unsupported geological description."""


def _name(value, label):
    return _label(value, label)


def _choice(value, values, label):
    if type(value) is not str or value not in values:
        raise GeologyError(label + ' must be one of ' + ', '.join(sorted(values)))
    return value


def _text(value, label, max_length=4096):
    if type(value) is not str or not value.strip() or len(value) > max_length:
        raise GeologyError(label + ' must be nonblank bounded text')
    return value


def _tuple(value, label, *, allow_empty=True):
    if type(value) is not tuple or (not allow_empty and not value):
        raise GeologyError(label + ' must be an immutable tuple' + (' (nonempty)' if not allow_empty else ''))
    return value


def _names(value, label, *, allow_empty=True, ordered=False):
    _tuple(value, label, allow_empty=allow_empty)
    for name in value:
        _name(name, label)
    if len(set(value)) != len(value):
        raise GeologyError(label + ' contains duplicate identifiers')
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
        _choice(self.kind, {'authored', 'generated', 'observation', 'literature', 'synthetic', 'unknown'}, 'source kind')
        _text(self.statement, 'source statement')
        _tuple(self.references, 'references')
        for ref in self.references:
            _text(ref, 'reference', 2048)
        if len(set(self.references)) != len(self.references):
            raise GeologyError('duplicate provenance references')
        if self.kind in ('observation', 'literature') and not self.references:
            raise GeologyError('observational/literature provenance requires an explicit reference')
        if self.content_sha256 is not None:
            h = self.content_sha256
            if type(h) is not str or len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
                raise GeologyError('content_sha256 must be a lowercase SHA256 identity')


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
        _choice(self.material_class, {'solid', 'fluid'}, 'material class')
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
        if self.thermal_expansion_per_k is not None and (self.density_kg_m3 is None or self.reference_temperature_k is None):
            raise GeologyError('expansion coefficient requires reference density and temperature')
        if self.valid_temperature_k is not None:
            v = _tuple(self.valid_temperature_k, 'temperature interval')
            if len(v) != 2:
                raise GeologyError('temperature interval needs two endpoints')
            lo, hi = (scalar(x, 'temperature interval', nonnegative=True) for x in v)
            if hi <= lo:
                raise GeologyError('temperature interval must increase')
            if self.reference_temperature_k is not None and not lo <= self.reference_temperature_k <= hi:
                raise GeologyError('reference temperature lies outside declared validity interval')
            object.__setattr__(self, 'valid_temperature_k', (lo, hi))


@dataclass(frozen=True, slots=True)
class CohortDescription:
    """Reuse W02 origin/formation identity without confusing origin with evidence."""
    cohort: MaterialCohort
    source_id: str

    def __post_init__(self):
        if type(self.cohort) is not MaterialCohort:
            raise GeologyError('explicit W02 MaterialCohort required')
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
        _choice(self.mode, {'unknown','constant','tabulated','half_space'}, 'thermal mode')
        if self.interpolation != 'linear' or self.extrapolation != 'refuse':
            raise GeologyError('only declared linear tables with refused extrapolation are supported')
        _tuple(self.depths_m, 'depths'); _tuple(self.temperatures_k, 'temperatures')
        z = tuple(scalar(x, 'profile depth', nonnegative=True) for x in self.depths_m)
        t = tuple(scalar(x, 'temperature', nonnegative=True) for x in self.temperatures_k)
        object.__setattr__(self, 'depths_m', z); object.__setattr__(self, 'temperatures_k', t)
        if self.mode == 'unknown':
            if z or t or self.diffusivity_m2_s is not None or self.cooling_start_time_s is not None:
                raise GeologyError('unknown profile cannot carry guessed numeric values')
            _text(self.unknown_reason, 'unknown thermal reason')
            return
        if self.unknown_reason is not None:
            raise GeologyError('known profile cannot also be unknown')
        if self.mode == 'half_space':
            if z or len(t) != 2 or t[1] < t[0]:
                raise GeologyError('half-space profile needs ordered surface/mantle temperatures')
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
        v = _float(self, 'solid_volume_fraction', positive=True)
        if v > 1:
            raise GeologyError('solid volume fraction exceeds one')


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
        _choice(self.role, {'sediment','crust','lithospheric_mantle'}, 'layer role')
        _float(self, 'bulk_thickness_m', positive=True)
        _tuple(self.components, 'components', allow_empty=False)
        if any(type(c) is not LayerComponent for c in self.components):
            raise GeologyError('typed LayerComponent records required')
        ids = [c.cohort_id for c in self.components]
        if len(set(ids)) != len(ids):
            raise GeologyError('a cohort is repeated within one layer')
        if not math.isclose(math.fsum(c.solid_volume_fraction for c in self.components), 1., rel_tol=0, abs_tol=FRACTION_ABSOLUTE_TOLERANCE):
            raise GeologyError('solid volume fractions must sum to one; no renormalisation')
        object.__setattr__(self, 'components', tuple(sorted(self.components, key=lambda c:c.cohort_id)))
        if self.porosity is None:
            _text(self.unknown_porosity_reason, 'unknown porosity reason')
        else:
            p = _float(self, 'porosity', nonnegative=True)
            if p >= 1 or self.unknown_porosity_reason is not None:
                raise GeologyError('porosity must be below one, with no contradictory unknown reason')


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
        _choice(self.crust_type, {'continental','oceanic','transitional','unknown'}, 'crust type')
        _tuple(self.layers, 'layers', allow_empty=False)
        if any(type(x) is not GeologicalLayer for x in self.layers):
            raise GeologyError('typed GeologicalLayer records required')
        if len({x.layer_id for x in self.layers}) != len(self.layers):
            raise GeologyError('duplicate layer ID in column')
        ranks = {'sediment':0, 'crust':1, 'lithospheric_mantle':2}
        r = [ranks[x.role] for x in self.layers]
        if 1 not in r or r != sorted(r):
            raise GeologyError('stack needs crust, with sediment above and mantle below it')
        try:
            total = math.fsum(x.bulk_thickness_m for x in self.layers)
        except OverflowError as exc:
            raise GeologyError('layer thickness total exceeds numerical range') from exc
        litho = _float(self, 'lithosphere_thickness_m', positive=True)
        if not math.isclose(total, litho, rel_tol=STACK_RELATIVE_TOLERANCE, abs_tol=0):
            raise GeologyError('layer stack differs from declared lithosphere thickness')
        # Check that even a very thin layer remains a distinct represented interval.
        z = 0.
        for layer in self.layers:
            new = z + layer.bulk_thickness_m
            if new <= z or not math.isfinite(new):
                raise GeologyError('layer boundary is not resolvable in binary64')
            z = new
        if any(x.porosity is not None and x.porosity > 0 for x in self.layers) and self.fluid_material_id is None:
            raise GeologyError('nonzero porosity requires an explicit pore-fluid material')
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
        _choice(self.kind, {'domain','plates','regions','geometry'}, 'selector kind')
        object.__setattr__(self, 'keys', _names(self.keys,'selector keys',allow_empty=self.kind=='domain'))
        if self.kind == 'domain' and self.keys:
            raise GeologyError('domain selector takes no keys')


@dataclass(frozen=True, slots=True)
class GeologicalProvince:
    province_id: str
    column_id: str
    selector: SurfaceSelector
    source_id: str

    def __post_init__(self):
        for key in ('province_id','column_id','source_id'):
            _name(getattr(self,key),key)
        if type(self.selector) is not SurfaceSelector:
            raise GeologyError('explicit SurfaceSelector required')


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
        dip = _float(self,'dip_rad',positive=True)
        if dip > math.pi/2:
            raise GeologyError('dip must lie in (0, pi/2] radians')
        _choice(self.dip_side,{'left','right'},'dip side')


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
        if type(self.selector) is not SurfaceSelector:
            raise GeologyError('typed SurfaceSelector required')
        _depths(self)
        if self.half_width_m is not None:
            _float(self,'half_width_m',positive=True)
        if self.strength_factor is None:
            _text(self.unknown_reason,'unknown strength reason')
        else:
            factor = _float(self,'strength_factor',positive=True)
            if factor > 1 or self.unknown_reason is not None:
                raise GeologyError('weakness factor must be in (0,1], without unknown reason')


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
        _choice(self.weak_zone_mode, {'retain_all','ordered_override'}, 'weak zone precedence')
        _names(self.weak_zone_order,'weak-zone precedence',ordered=True)
        if self.weak_zone_mode == 'retain_all' and self.weak_zone_order:
            raise GeologyError('retain_all must not also specify an override order')
