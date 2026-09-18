"""3C-R2: immutable geological precursor inputs, independent of final plates.

This module describes initial conditions, not their physical generation. Source
origins, material formation, cooling history, statistical priors and prescribed
forcing are separate records. A weak-zone strength factor is not a damage law.
The existing ArrayStore persists every decoding dependency in one transaction.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import json
import math
from types import MappingProxyType

import numpy as np

from ._validation import scalar, input_shape, read_array
from .geological_records import (GeologyError, GeologicalLayer, SurfaceSelector,
    _name, _choice, _text, _tuple, _names, STACK_RELATIVE_TOLERANCE)
from .geological_case import (GeologicalCase, _json, _sha, _snapshot,
    restore_geological_case, GeologyLimits, _check_geometry_frame)
from .geological_domain import GeologicalDomain
from .geometry import _check_cancel, GeometryLimits
from .material_library import EarthMaterialLibrary, restore_material_library
from .resources import select_budget

_SCHEMA = 'atlas.geological-precursor.v1'
_SNAPSHOT = 'atlas.geological-precursor-snapshot.v1'
_MAX_RECORDS = 20_000
_MAX_DEFINITION_BYTES = 4 * 1024**2


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _unique(records, cls, key, label):
    _tuple(records, label)
    if len(records) > _MAX_RECORDS or any(type(x) is not cls for x in records):
        raise GeologyError('bounded typed ' + label + ' required')
    result = tuple(sorted(records, key=lambda x: getattr(x, key)))
    if len({getattr(x, key) for x in result}) != len(result):
        raise GeologyError('duplicate ' + label)
    return result


@dataclass(frozen=True, slots=True)
class InputOrigin:
    """Origin of every source-bound input; a classification is not validation.

    basis_id identifies the observation, authored scenario, exact prior identity,
    or model/case used. Model-evolved inputs additionally retain their parent
    state hash. No constructor runs or independently approves that model.
    """
    source_id: str
    kind: str
    basis_id: str
    parent_state_id: str | None = None

    def __post_init__(self):
        _name(self.source_id, 'origin source')
        _choice(self.kind, {'observed', 'authored', 'sampled_prior', 'model_evolved'}, 'input origin')
        _text(self.basis_id, 'origin basis', 2048)
        if self.kind == 'sampled_prior':
            _sha(self.basis_id)
        if self.kind == 'model_evolved':
            _sha(self.parent_state_id)
        elif self.parent_state_id is not None:
            raise GeologyError('only model-evolved input has a parent model state')


@dataclass(frozen=True, slots=True)
class CoolingHistory:
    """Cooling onset in the case epoch; never copied from a cohort formation date."""
    profile_id: str
    source_id: str
    start_time_s: float | None
    unknown_reason: str | None = None

    def __post_init__(self):
        _name(self.profile_id, 'cooling profile'); _name(self.source_id, 'cooling source')
        if self.start_time_s is None:
            _text(self.unknown_reason, 'unknown cooling history')
        else:
            object.__setattr__(self, 'start_time_s', scalar(self.start_time_s, 'cooling onset'))
            if self.unknown_reason is not None:
                raise GeologyError('known cooling onset cannot also be unknown')


@dataclass(frozen=True, slots=True)
class MaterialVolumeBasis:
    """Density-volume convention; additional pores cannot be added to bulk rock.

    ``grain`` is the true solid constituent convention; ``bulk_reference`` is an
    aggregate measurement whose intrinsic pore volume is not resolved here.
    """
    material_id: str
    basis: str
    source_id: str

    def __post_init__(self):
        _name(self.material_id, 'material basis ID'); _name(self.source_id, 'basis source')
        _choice(self.basis, {'grain', 'bulk_reference', 'fluid'}, 'material volume basis')


@dataclass(frozen=True, slots=True)
class SeededSpatialPrior:
    """Named, mesh-independent band-limited Cartesian cosine prior.

    f(r) = mean + amplitude/N * sum_i cos(k_i . (r-origin) + phase_i).
    Each wavelength is an explicit feature scale, NOT a fitted correlation
    length. ``amplitude`` is a bound on absolute deviation, NOT a standard
    deviation. SHA256 per-mode streams avoid dependence on traversal, batching,
    NumPy RNG versions or mesh resolution. This is an initial statistical
    assumption, not a record of simulated geological events.

    Coordinates are (x,y,depth) for a planar domain and planet-centred Cartesian
    metres for a spherical domain, in its named frame. There is no longitude seam.
    """
    name: str
    seed: int
    mean: float
    amplitude: float
    wavelengths_m: tuple[float, ...]
    origin_m: tuple[float, float, float]
    domain_id: str
    frame_id: str
    _waves: tuple = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        _name(self.name, 'prior name'); _name(self.frame_id, 'prior frame'); _sha(self.domain_id)
        if type(self.seed) is not int or not 0 <= self.seed < 2**64:
            raise GeologyError('prior seed must be an unsigned 64-bit integer')
        object.__setattr__(self, 'mean', scalar(self.mean, 'prior mean'))
        object.__setattr__(self, 'amplitude', scalar(self.amplitude, 'prior amplitude', nonnegative=True))
        if not math.isfinite(abs(self.mean) + self.amplitude):
            raise GeologyError('prior value envelope exceeds binary64')
        _tuple(self.wavelengths_m, 'prior wavelengths', allow_empty=False)
        if len(self.wavelengths_m) > 64:
            raise GeologyError('at most 64 explicitly specified prior modes are supported')
        scales = tuple(scalar(x, 'prior wavelength', positive=True) for x in self.wavelengths_m)
        _tuple(self.origin_m, 'prior origin')
        if len(self.origin_m) != 3:
            raise GeologyError('prior origin needs three coordinates')
        origin = tuple(scalar(x, 'prior origin') for x in self.origin_m)
        object.__setattr__(self, 'wavelengths_m', scales)
        object.__setattr__(self, 'origin_m', origin)
        waves = []
        for i, scale in enumerate(scales):
            raw = hashlib.sha256(_json(('atlas.cosine-stream.v1', self.name, self.seed, i))).digest()
            # Fixed top-53-bit conversion produces reproducible binary64 uniforms.
            u = tuple((int.from_bytes(raw[j:j+8], 'big') >> 11) * 2.0**-53 for j in (0, 8, 16))
            z = 2*u[0]-1; theta = 2*math.pi*u[1]
            radial = math.sqrt(max(0., 1-z*z)); frequency = 2*math.pi/scale
            wave = (frequency*radial*math.cos(theta), frequency*radial*math.sin(theta), frequency*z, 2*math.pi*u[2])
            if not all(math.isfinite(v) for v in wave):
                raise GeologyError('prior wavelength is outside numerical range')
            waves.append(wave)
        object.__setattr__(self, '_waves', tuple(waves))

    def descriptor(self):
        return {'schema': 'atlas.spatial-cosine-prior.v1', **{k: getattr(self, k) for k in (
            'name', 'seed', 'mean', 'amplitude', 'wavelengths_m', 'origin_m', 'domain_id', 'frame_id')}}

    @property
    def prior_id(self):
        return _digest(self.descriptor())

    def evaluate(self, coordinates_m, *, budget=None, cancel=None, batch_points=4096):
        """Bulk native arithmetic, fixed mode order, no point-by-all-mode cube."""
        _check_cancel(cancel)
        shape = input_shape(coordinates_m, 'prior coordinates')
        if len(shape) != 2 or shape[1] != 3 or shape[0] == 0:
            raise GeologyError('prior evaluation requires nonempty (n,3) Cartesian coordinates')
        if type(batch_points) is not int or batch_points <= 0:
            raise GeologyError('positive prior batch size required')
        n = shape[0]
        with select_budget(budget).reserve(64*n + 160*min(n, batch_points)+8192, category='precursor-prior'):
            points = read_array(coordinates_m, 'prior coordinates', ndim=2)
            if points.shape != shape:
                raise GeologyError('prior input shape changed during capture')
            out = np.full(n, self.mean, dtype=np.float64)
            for start in range(0, n, batch_points):
                _check_cancel(cancel)
                p = points[start:start+batch_points] - np.asarray(self.origin_m)
                for kx, ky, kz, phase in self._waves:
                    # Component-wise expression has no batch-dependent BLAS reduction.
                    angle = p[:, 0]*kx + p[:, 1]*ky + p[:, 2]*kz + phase
                    if not np.isfinite(angle).all() or np.any(np.abs(angle) > 2**40):
                        raise GeologyError('prior phase is insufficiently resolved; change explicit support/scale')
                    out[start:start+len(p)] += (self.amplitude/len(self._waves))*np.cos(angle)
            if not np.isfinite(out).all():
                raise GeologyError('prior values exceed numerical range')
            _check_cancel(cancel)
            return np.frombuffer(out.tobytes(), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class InitialScalarField:
    """An explicitly supplied scalar input, or a named unresolved quantity.

    Stress components and forcing remain prescribed inputs. The field's
    interpretation states its component/frame/boundary meaning; no equation of
    state, rheology or automatic weakening is implemented by these records.
    """
    name: str
    role: str
    unit: str
    source_id: str
    interpretation: str
    constant_value: float | None = None
    prior: SeededSpatialPrior | None = None
    unknown_reason: str | None = None

    def __post_init__(self):
        _name(self.name, 'initial field'); _name(self.source_id, 'field source')
        _choice(self.role, {'temperature_offset', 'stress', 'damage', 'prescribed_forcing'}, 'initial field role')
        _text(self.interpretation, 'field interpretation')
        expected = {'temperature_offset': {'K'}, 'stress': {'Pa'}, 'damage': {'1'},
                    'prescribed_forcing': {'Pa', 'N/m3', 'm/s'}}
        if self.unit not in expected[self.role]:
            raise GeologyError('initial field unit does not match its role')
        if sum(x is not None for x in (self.constant_value, self.prior, self.unknown_reason)) != 1:
            raise GeologyError('field must be exactly one of constant, named prior or explicitly unknown')
        if self.constant_value is not None:
            object.__setattr__(self, 'constant_value', scalar(self.constant_value, 'initial field value'))
        if self.prior is not None and type(self.prior) is not SeededSpatialPrior:
            raise GeologyError('typed spatial prior required')
        if self.unknown_reason is not None:
            _text(self.unknown_reason, 'unknown initial field')

    def descriptor(self):
        return {k: getattr(self, k) for k in ('name', 'role', 'unit', 'source_id', 'interpretation',
                 'constant_value', 'unknown_reason')} | {'prior': None if self.prior is None else self.prior.descriptor()}


@dataclass(frozen=True, slots=True)
class SubsurfaceBody:
    """Authored/observed/prior/model-imported depth-band body, not inferred forces.

    Footprints use the case domain or existing named area geometries. Top and
    bottom are surface-relative constant depths; no dipping/curved 3D slab is
    inferred from a surface trace. Body precedence is explicit and may override
    columns. A mantle body can extend support below their lithosphere bases.
    """
    body_id: str
    kind: str
    selector: SurfaceSelector
    top_depth_m: float
    bottom_depth_m: float
    layer: GeologicalLayer
    thermal_profile_id: str
    source_id: str
    fluid_material_id: str | None = None

    def __post_init__(self):
        for key in ('body_id', 'thermal_profile_id', 'source_id'):
            _name(getattr(self, key), key)
        _choice(self.kind, {'mantle', 'slab'}, 'subsurface body kind')
        if type(self.selector) is not SurfaceSelector or self.selector.kind not in ('domain', 'geometry'):
            raise GeologyError('subsurface bodies cannot depend on final plate labels')
        top = scalar(self.top_depth_m, 'body top depth', nonnegative=True)
        bottom = scalar(self.bottom_depth_m, 'body bottom depth', positive=True)
        if bottom <= top or type(self.layer) is not GeologicalLayer:
            raise GeologyError('positive thickness and typed body layer required')
        if not math.isclose(bottom-top, self.layer.bulk_thickness_m, rel_tol=STACK_RELATIVE_TOLERANCE, abs_tol=0):
            raise GeologyError('body depths and layer thickness disagree')
        object.__setattr__(self, 'top_depth_m', top); object.__setattr__(self, 'bottom_depth_m', bottom)
        if self.fluid_material_id is not None:
            _name(self.fluid_material_id, 'body fluid')
        if self.layer.porosity is not None and self.layer.porosity > 0 and self.fluid_material_id is None:
            raise GeologyError('porous body requires an explicit pore fluid')


@dataclass(frozen=True, slots=True)
class PrecursorUnit:
    """Shared layer/body metadata. Samples store only integer indices into it."""
    kind: str
    owner_id: str
    layer: GeologicalLayer
    top_depth_m: float
    bottom_depth_m: float
    thermal_profile_id: str
    fluid_material_id: str | None

    @property
    def unit_id(self):
        return _digest((self.kind, self.owner_id, self.layer.layer_id))


@dataclass(frozen=True, slots=True, init=False)
class PrecursorState:
    """Complete mesh-independent initial definition with no physical plate IDs.

    GeologicalCase keeps the established catalogue and feature checks. This
    wrapper adds origin, cooling, volume-basis and initial-field contracts without
    rewriting old cases or assigning fictitious plates as a construction trick.
    """
    case: GeologicalCase
    origins: tuple[InputOrigin, ...]
    cooling_history: tuple[CoolingHistory, ...]
    material_bases: tuple[MaterialVolumeBasis, ...]
    fields: tuple[InitialScalarField, ...]
    bodies: tuple[SubsurfaceBody, ...]
    body_order: tuple[str, ...]
    library: EarthMaterialLibrary | None
    units: tuple[PrecursorUnit, ...]
    state_id: str
    _definition: bytes = field(repr=False, compare=False)
    _maps: object = field(repr=False, compare=False)

    def __init__(self, case, *, origins, cooling_history, material_bases=(), fields=(),
                 bodies=(), body_order=(), library=None, budget=None, cancel=None):
        _check_cancel(cancel)
        if type(case) is not GeologicalCase or type(case.topology) is not GeologicalDomain:
            raise GeologyError('precursor needs a GeologicalCase on a plate-independent GeologicalDomain')
        if library is not None and type(library) is not EarthMaterialLibrary:
            raise GeologyError('typed material library or explicit absence required')
        origins = _unique(origins, InputOrigin, 'source_id', 'origins')
        history = _unique(cooling_history, CoolingHistory, 'profile_id', 'cooling histories')
        bases = _unique(material_bases, MaterialVolumeBasis, 'material_id', 'material bases')
        fields = _unique(fields, InitialScalarField, 'name', 'initial fields')
        bodies = _unique(bodies, SubsurfaceBody, 'body_id', 'subsurface bodies')
        _names(body_order, 'body precedence', ordered=True)
        if set(body_order) != {b.body_id for b in bodies}:
            raise GeologyError('body precedence must name every body exactly once, highest first')
        count = sum(map(len, (origins, history, bases, fields, bodies))) + sum(len(b.layer.components) for b in bodies)
        if count > _MAX_RECORDS:
            raise GeologyError('precursor record envelope exceeded')
        estimate = case.retained_bytes_estimate + 8192*count + (0 if library is None else 4*library.nbytes) + 65536
        with select_budget(budget).reserve(estimate, category='precursor-definition'):
            sources = {s.source_id: s for s in case.sources}
            origin_map = {o.source_id: o for o in origins}
            if set(origin_map) != set(sources):
                raise GeologyError('every source must have exactly one explicit origin assignment')
            for o in origins:
                if o.kind == 'observed' and not sources[o.source_id].references:
                    raise GeologyError('observed origin requires cited source evidence')
            def source(key):
                if key not in sources:
                    raise GeologyError('unknown precursor source: ' + str(key))
            thermal = {p.profile_id: p for p in case.thermal_profiles}
            history_map = {h.profile_id: h for h in history}
            if set(history_map) != set(thermal):
                raise GeologyError('every thermal profile needs explicit known or unknown cooling history')
            for h in history:
                source(h.source_id)
                if h.start_time_s is not None and (h.start_time_s > case.time_s or not math.isfinite(case.time_s-h.start_time_s)):
                    raise GeologyError('cooling onset is after the initial epoch or age overflows')
                p = thermal[h.profile_id]
                if p.mode == 'half_space' and h.start_time_s != p.cooling_start_time_s:
                    raise GeologyError('half-space profile and independently labelled cooling history disagree')
            materials = {m.material_id: m for m in case.materials}
            base_map = {b.material_id: b for b in bases}
            # Library-bound profiles carry their basis and exact evidence. A
            # changed reference definition is not silently rebound to this version.
            for m in case.materials:
                if m.source_id.startswith('earth-ref-'):
                    if library is None:
                        raise GeologyError('source-bound Earth profiles require their actual library dependency')
                    expected, evidence = library.definitions((m.material_id,), reference_temperature_k=m.reference_temperature_k)
                    if expected != (m,) or sources.get(evidence[0].source_id) != evidence[0]:
                        raise GeologyError('material/source binding differs from the supplied library')
                    derived = MaterialVolumeBasis(m.material_id, library[m.material_id].basis, m.source_id)
                    if m.material_id in base_map and base_map[m.material_id] != derived:
                        raise GeologyError('declared material volume basis contradicts source binding')
                    base_map[m.material_id] = derived
            if set(base_map) != set(materials):
                raise GeologyError('every material requires an explicit or source-bound volume basis')
            bases = tuple(base_map[k] for k in sorted(base_map))
            for b in bases:
                source(b.source_id)
                if (b.basis == 'fluid') != (materials[b.material_id].material_class == 'fluid'):
                    raise GeologyError('material class and volume basis disagree')
            cohorts = {c.cohort.cohort_id: c.cohort for c in case.cohorts}
            if any(c.formation_time_s is not None and not math.isfinite(case.time_s-c.formation_time_s) for c in cohorts.values()):
                raise GeologyError('formation age exceeds binary64; choose a representable explicit epoch')
            geometry = {g.key: g.geometry for g in case.geometries}
            units = []
            for c in case.columns:
                for i, layer in enumerate(c.layers):
                    units.append(PrecursorUnit('column', c.column_id, layer, c.layer_edges_m[i], c.layer_edges_m[i+1],
                                               c.thermal_profile_id, c.fluid_material_id))
            for b in bodies:
                source(b.source_id); source(b.layer.source_id)
                if b.thermal_profile_id not in thermal:
                    raise GeologyError('unknown body thermal profile')
                if b.selector.kind == 'geometry' and any(k not in geometry or geometry[k].kind not in ('Polygon', 'MultiPolygon') for k in b.selector.keys):
                    raise GeologyError('body footprints require known area geometry')
                units.append(PrecursorUnit('body', b.body_id, b.layer, b.top_depth_m, b.bottom_depth_m,
                                           b.thermal_profile_id, b.fluid_material_id))
            for u in units:
                for component in u.layer.components:
                    if component.cohort_id not in cohorts:
                        raise GeologyError('unknown body/layer cohort')
                if u.fluid_material_id is not None and (u.fluid_material_id not in materials or materials[u.fluid_material_id].material_class != 'fluid'):
                    raise GeologyError('unknown or nonsensical pore fluid')
                if u.layer.porosity is not None and u.layer.porosity > 0 and any(base_map[cohorts[c.cohort_id].material_id].basis != 'grain' for c in u.layer.components):
                    raise GeologyError('cannot add porosity to already bulk-reference rock constituents')
                p = thermal[u.thermal_profile_id]
                if p.mode == 'tabulated' and p.depths_m[-1] < u.bottom_depth_m:
                    raise GeologyError('body thermal table does not reach its base; no extrapolation')
                if case.topology.sphere is not None and u.bottom_depth_m >= case.topology.sphere.radius_m:
                    raise GeologyError('represented depths must remain strictly outside the sphere centre')
            if sum(f.role == 'temperature_offset' for f in fields) > 1:
                raise GeologyError('at most one declared temperature-offset field; no implicit superposition')
            used_prior_ids = set()
            for f in fields:
                source(f.source_id)
                if f.prior is not None:
                    p = f.prior
                    if p.domain_id != case.topology.domain_id or p.frame_id != case.topology.frame_id:
                        raise GeologyError('prior belongs to a different domain/frame')
                    o = origin_map[f.source_id]
                    if o.kind != 'sampled_prior' or o.basis_id != p.prior_id:
                        raise GeologyError('sampled field requires its exact named-prior origin')
                    used_prior_ids.add(p.prior_id)
                elif origin_map[f.source_id].kind == 'sampled_prior':
                    raise GeologyError('sampled-prior scalar input must retain its prior definition')
            for o in origins:
                if o.kind == 'sampled_prior' and o.basis_id not in used_prior_ids:
                    raise GeologyError('sampled-prior source has no retained prior definition')
            d = {'schema': _SCHEMA, 'case_definition_id': case.definition_id,
                 'origins': [asdict(o) for o in origins], 'cooling_history': [asdict(h) for h in history],
                 'material_bases': [asdict(b) for b in bases], 'fields': [f.descriptor() for f in fields],
                 'bodies': [asdict(b) for b in bodies], 'body_order': body_order,
                 'library_id': None if library is None else library.library_id}
            raw = _json(d)
            if len(raw) > _MAX_DEFINITION_BYTES:
                raise GeologyError('precursor definition exceeds byte limit')
            for key, value in dict(case=case, origins=origins, cooling_history=history, material_bases=bases,
                    fields=fields, bodies=bodies, body_order=body_order, library=library, units=tuple(units),
                    state_id=hashlib.sha256(raw).hexdigest(), _definition=raw).items():
                object.__setattr__(self, key, value)
            maps = {'origins': origin_map, 'thermal': thermal, 'cooling': history_map, 'materials': materials,
                    'bases': base_map, 'cohorts': cohorts, 'geometry': geometry,
                    'fields': {f.name: f for f in fields}, 'bodies': {b.body_id: b for b in bodies}}
            object.__setattr__(self, '_maps', MappingProxyType({k: MappingProxyType(v) for k, v in maps.items()}))
            _check_cancel(cancel)

    def descriptor(self):
        return json.loads(self._definition)

    @property
    def retained_bytes_estimate(self):
        return (len(self._definition) + self.case.retained_bytes_estimate + self.case.topology.retained_bytes
                + sum(g.geometry.retained_bytes for g in self.case.geometries)
                + 4096*len(self.units) + (0 if self.library is None else 4*self.library.nbytes))

    def preflight(self, *, require_temperature=False, require_porosity=False, required_fields=()):
        """Return all requested gaps. Unrequested stress/damage remain unresolved.

        Passing this input gate does not supply constitutive/thermal evolution,
        pressure-qualified laws or physical validation. Requirements are explicit.
        """
        if type(require_temperature) is not bool or type(require_porosity) is not bool:
            raise GeologyError('preflight switches must be bool')
        _names(required_fields, 'required initial fields')
        issues = []
        if require_temperature:
            issues.extend(('thermal/'+p.profile_id, p.unknown_reason) for p in self.case.thermal_profiles if p.mode == 'unknown')
            issues.extend(('field/'+f.name, f.unknown_reason) for f in self.fields if f.role == 'temperature_offset' and f.unknown_reason is not None)
        if require_porosity:
            issues.extend(('unit/'+u.unit_id+'/porosity', u.layer.unknown_porosity_reason) for u in self.units if u.layer.porosity is None)
        for name in required_fields:
            f = self._maps['fields'].get(name)
            if f is None or f.unknown_reason is not None:
                issues.append(('field/'+name, 'not supplied' if f is None else f.unknown_reason))
        return tuple(issues)

    @property
    def unresolved_initial_state(self):
        issues = [(u.path, u.reason) for u in self.case.unresolved]
        issues.extend(self.preflight(require_temperature=True, require_porosity=True))
        issues.extend(('cooling/'+h.profile_id, h.unknown_reason) for h in self.cooling_history if h.start_time_s is None)
        for role in ('stress', 'damage'):
            fs = [f for f in self.fields if f.role == role]
            if not fs:
                issues.append((role, 'not supplied; neither zero nor inferred from a weak-zone multiplier'))
        issues.extend(('field/'+f.name, f.unknown_reason) for f in self.fields if f.unknown_reason is not None)
        return tuple(dict.fromkeys(issues))

    def require(self, **requirements):
        issues = self.preflight(**requirements)
        if issues:
            raise GeologyError('unsupported initial-state requirements: ' + '; '.join(p+': '+r for p, r in issues))
        return self

    def require_reference_densities(self, temperature_k):
        """Reference mass bookkeeping only; does not evaluate hot/pressurised mass."""
        t = scalar(temperature_k, 'density reference temperature', nonnegative=True)
        for m in self.case.materials:
            if m.density_kg_m3 is None or m.reference_temperature_k != t:
                raise GeologyError('density unavailable at the requested reference condition: '+m.material_id)
        return t

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self


def _precursor_snapshot(state):
    cm, ca = _snapshot(state.case)
    arrays = {'case__'+k: v for k, v in ca.items()}
    arrays['precursor_definition'] = np.frombuffer(state._definition, dtype='u1')
    if state.library is not None:
        arrays['material_library'] = np.frombuffer(state.library._payload, dtype='u1')
    meta = {'schema': _SNAPSHOT, 'state_id': state.state_id, 'case': cm}
    return meta, arrays


def _restore_prior(d):
    if type(d) is not dict or d.get('schema') != 'atlas.spatial-cosine-prior.v1':
        raise GeologyError('invalid stored prior')
    args = dict(d); args.pop('schema')
    for k in ('wavelengths_m', 'origin_m'):
        args[k] = tuple(args[k])
    return SeededSpatialPrior(**args)


def restore_precursor_state(metadata, arrays, expected_id, *, budget=None, cancel=None):
    """Strict self-contained restoration; no imports from metadata or regeneration."""
    _sha(expected_id); _check_cancel(cancel)
    if type(metadata) is not dict or set(metadata) != {'schema', 'state_id', 'case'} or metadata['schema'] != _SNAPSHOT or metadata['state_id'] != expected_id:
        raise GeologyError('invalid precursor snapshot metadata')
    if not isinstance(arrays, dict) or 'precursor_definition' not in arrays:
        raise GeologyError('precursor definition payload missing')
    a = arrays['precursor_definition']
    if type(a) is not np.ndarray or a.dtype != np.dtype('u1') or a.ndim != 1 or a.nbytes > _MAX_DEFINITION_BYTES:
        raise GeologyError('invalid precursor definition bytes')
    raw = a.tobytes()
    if hashlib.sha256(raw).hexdigest() != expected_id:
        raise GeologyError('precursor definition hash mismatch')
    try:
        d = json.loads(raw)
        if type(d) is not dict or d.get('schema') != _SCHEMA or _json(d) != raw:
            raise GeologyError('noncanonical precursor definition')
        for k in ('origins', 'cooling_history', 'material_bases', 'fields', 'bodies', 'body_order'):
            if type(d[k]) is not list or len(d[k]) > _MAX_RECORDS:
                raise GeologyError('invalid saved precursor inventory')
        extras = {'precursor_definition'} | ({'material_library'} if d['library_id'] is not None else set())
        if any(not (k in extras or k.startswith('case__')) for k in arrays) or not extras <= set(arrays):
            raise GeologyError('unexpected or missing precursor payload dependency')
        payload_bytes = sum(v.nbytes for v in arrays.values() if type(v) is np.ndarray)
        with select_budget(budget).reserve(8*len(raw)+3*payload_bytes+65536, category='precursor-restore'):
            case = restore_geological_case(metadata['case'], {k[6:]: v for k, v in arrays.items() if k.startswith('case__')},
                                           d['case_definition_id'], budget=budget, cancel=cancel)
            lib = None
            if d['library_id'] is not None:
                a = arrays['material_library']
                if type(a) is not np.ndarray or a.dtype != np.dtype('u1') or a.ndim != 1:
                    raise GeologyError('invalid saved library bytes')
                lib = restore_material_library(a.tobytes(), d['library_id'])
            fields = tuple(InitialScalarField(**(dict(f) | {'prior': None if f['prior'] is None else _restore_prior(f['prior'])})) for f in d['fields'])
            from .geological_records import LayerComponent
            bodies = []
            for b in d['bodies']:
                layer = dict(b['layer']); layer['components'] = tuple(LayerComponent(**c) for c in layer['components'])
                selector = dict(b['selector']); selector['keys'] = tuple(selector['keys'])
                bodies.append(SubsurfaceBody(**(dict(b) | {'layer': GeologicalLayer(**layer), 'selector': SurfaceSelector(**selector)})))
            result = PrecursorState(case, origins=tuple(InputOrigin(**r) for r in d['origins']),
                cooling_history=tuple(CoolingHistory(**r) for r in d['cooling_history']),
                material_bases=tuple(MaterialVolumeBasis(**r) for r in d['material_bases']),
                fields=fields, bodies=tuple(bodies), body_order=tuple(d['body_order']), library=lib, budget=budget, cancel=cancel)
            if result.state_id != expected_id or result._definition != raw or _precursor_snapshot(result)[0] != metadata:
                raise GeologyError('restored precursor identity/dependencies differ')
            return result
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, GeologyError):
            raise
        raise GeologyError('malformed precursor snapshot') from exc


def save_precursor_state(state, store, *, budget=None, cancel=None):
    """One existing transactional Zstd/deduplicated store; no new cache service."""
    from .storage import ArrayStore
    if type(state) is not PrecursorState or not isinstance(store, ArrayStore):
        raise GeologyError('typed precursor and ArrayStore required')
    policy = store._budget if budget is None else budget
    _check_cancel(cancel)
    with select_budget(policy).reserve(4*state.retained_bytes_estimate+65536, category='precursor-save'):
        metadata, arrays = _precursor_snapshot(state)
        return store.put(state.state_id, arrays, metadata, budget=policy, cancel=cancel)


def load_precursor_state(store, state_id, *, budget=None, cancel=None):
    from .storage import ArrayStore
    if not isinstance(store, ArrayStore):
        raise GeologyError('ArrayStore required')
    _sha(state_id); _check_cancel(cancel)
    policy = store._budget if budget is None else budget
    arrays = store.get(state_id, budget=policy)
    if arrays is None:
        return None
    return restore_precursor_state(store.metadata(state_id), arrays, state_id, budget=policy, cancel=cancel)
