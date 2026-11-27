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
from typing import cast

import numpy as np

from atlas_tectonics._validation import scalar, input_shape, read_array
from atlas_tectonics.history.geological_records import (GeologyError, GeologicalLayer, SurfaceSelector,
    _name, _text, _names, STACK_RELATIVE_TOLERANCE)
from atlas_tectonics.history.geological_case import (GeologicalCase, _json, _snapshot,
    restore_geological_case)
from atlas_tectonics.history.geological_domain import GeologicalDomain
from atlas_tectonics.planet.geometry import _check_cancel, GeometryLimits
from atlas_tectonics.materials.material_library import EarthMaterialLibrary, restore_material_library
from atlas_tectonics.integration.resources import select_budget
from atlas_tectonics.integration.resources import _immutable_deepcopy
from atlas_tectonics.planet.spherical_atlas import SphericalAtlas

_SCHEMA = 'atlas.geological-precursor.v1'
_INITIAL_SCHEMA = 'atlas.initial-condition-state.v1'
_SNAPSHOT = 'atlas.geological-precursor-snapshot.v1'
_MAX_RECORDS = 20_000
_MAX_DEFINITION_BYTES = 4 * 1024**2


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _unique(records, cls, key, label):
    if len(records) > _MAX_RECORDS or any(type(x) is not cls for x in records):
        raise GeologyError('bounded typed ' + label + ' required')
    result = tuple(sorted(records, key=lambda x: getattr(x, key)))
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
        _text(self.basis_id, 'origin basis', 2048)
        if self.kind != 'model_evolved' and self.parent_state_id is not None:
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
        _name(self.name, 'prior name'); _name(self.frame_id, 'prior frame')
        if type(self.seed) is not int or not 0 <= self.seed < 2**64:
            raise GeologyError('prior seed must be an unsigned 64-bit integer')
        object.__setattr__(self, 'mean', scalar(self.mean, 'prior mean'))
        object.__setattr__(self, 'amplitude', scalar(self.amplitude, 'prior amplitude', nonnegative=True))
        if not math.isfinite(abs(self.mean) + self.amplitude):
            raise GeologyError('prior value envelope exceeds binary64')
        scales = tuple(scalar(x, 'prior wavelength', positive=True) for x in self.wavelengths_m)
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
        n = shape[0]
        with select_budget(budget).reserve(64*n + 160*min(n, batch_points)+8192, category='precursor-prior'):
            points = read_array(coordinates_m, 'prior coordinates', ndim=2)
            out = np.full(n, self.mean, dtype=np.float64)
            for start in range(0, n, batch_points):
                _check_cancel(cancel)
                p = points[start:start+batch_points] - np.asarray(self.origin_m)
                for kx, ky, kz, phase in self._waves:
                    # Component-wise expression has no batch-dependent BLAS reduction.
                    angle = p[:, 0]*kx + p[:, 1]*ky + p[:, 2]*kz + phase
                    out[start:start+len(p)] += (self.amplitude/len(self._waves))*np.cos(angle)
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
        _text(self.interpretation, 'field interpretation')
        expected = {'temperature_offset': {'K'}, 'stress': {'Pa'}, 'damage': {'1'},
                    'prescribed_forcing': {'Pa', 'N/m3', 'm/s'}}
        if self.unit not in expected[self.role]:
            raise GeologyError('initial field unit does not match its role')
        if sum(x is not None for x in (self.constant_value, self.prior, self.unknown_reason)) != 1:
            raise GeologyError('field must be exactly one of constant, named prior or explicitly unknown')
        if self.constant_value is not None:
            object.__setattr__(self, 'constant_value', scalar(self.constant_value, 'initial field value'))
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
    sampling_domain: GeologicalDomain
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
        initial = type(self) is InitialConditionState
        topology = case.topology
        domain = (topology if type(topology) is GeologicalDomain else
                  GeologicalDomain(topology.sphere if type(topology) is SphericalAtlas else topology.domain, case.source_id))
        origins = _unique(origins, InputOrigin, 'source_id', 'origins')
        history = _unique(cooling_history, CoolingHistory, 'profile_id', 'cooling histories')
        bases = _unique(material_bases, MaterialVolumeBasis, 'material_id', 'material bases')
        fields = _unique(fields, InitialScalarField, 'name', 'initial fields')
        bodies = _unique(bodies, SubsurfaceBody, 'body_id', 'subsurface bodies')
        _names(body_order, 'body precedence', ordered=True)
        count = sum(map(len, (origins, history, bases, fields, bodies))) + sum(len(b.layer.components) for b in bodies)
        selector_bound = min(_MAX_RECORDS, len(topology.regions)*(len(case.provinces)+len(case.weak_zones)))
        estimate = (case.retained_bytes_estimate + 8192*count + 1024*len(topology.regions)
                    + 128*selector_bound + (0 if library is None else 4*library.nbytes) + 65536)
        with select_budget(budget).reserve(estimate, category='precursor-definition'):
            sources = {s.source_id: s for s in case.sources}
            origin_map = {o.source_id: o for o in origins}
            for o in origins:
                if o.kind == 'observed' and not sources[o.source_id].references:
                    raise GeologyError('observed origin requires cited source evidence')
            def source(key):
                if key not in sources:
                    raise GeologyError('unknown precursor source: ' + str(key))
            thermal = {p.profile_id: p for p in case.thermal_profiles}
            history_map = {h.profile_id: h for h in history}
            for h in history:
                source(h.source_id)
                p = thermal[h.profile_id]
            materials = {m.material_id: m for m in case.materials}
            base_map = {b.material_id: b for b in bases}
            # Library-bound profiles carry their basis and exact evidence. A
            # changed reference definition is not silently rebound to this version.
            for m in case.materials:
                if m.source_id.startswith('earth-ref-'):
                    expected, evidence = cast(EarthMaterialLibrary, library).definitions((m.material_id,), reference_temperature_k=m.reference_temperature_k)
                    derived = MaterialVolumeBasis(m.material_id, cast(EarthMaterialLibrary, library)[m.material_id].basis, m.source_id)
                    base_map[m.material_id] = derived
            bases = tuple(base_map[k] for k in sorted(base_map))
            for b in bases:
                source(b.source_id)
            cohorts = {c.cohort.cohort_id: c.cohort for c in case.cohorts}
            geometry = {g.key: g.geometry for g in case.geometries}
            # Keep the original case/topology verbatim. Only resolve its selectors
            # into shared patch references; never union a globe into one chart.
            selectors = {}
            owners = {'plates': {}, 'regions': {}}
            for i, region in enumerate(topology.regions):
                rid = topology.patches[i].region_id if type(topology) is SphericalAtlas else region.region_id
                owners['plates'].setdefault(region.plate_id, []).append(region)
                owners['regions'].setdefault(rid, []).append(region)
            links = 0
            for selector in (p.selector for p in (*case.provinces, *case.weak_zones)):
                token = (selector.kind, selector.keys)
                if token in selectors:
                    continue
                if selector.kind in ('domain', 'geometry'):
                    selectors[token] = selector.keys
                    continue
                keys = []
                for owner in selector.keys:
                    for region in owners[selector.kind][owner]:
                        links += 1
                        if links > _MAX_RECORDS:
                            raise GeologyError('topology selector links exceed the initial-state record envelope')
                        key = 'w01-support-'+_digest((region.region_id, region.geometry.geometry_id))
                        geometry[key] = region.geometry
                        keys.append(key)
                selectors[token] = tuple(keys)
            units = []
            for c in case.columns:
                for i, layer in enumerate(c.layers):
                    units.append(PrecursorUnit('column', c.column_id, layer, c.layer_edges_m[i], c.layer_edges_m[i+1],
                                               c.thermal_profile_id, c.fluid_material_id))
            for b in bodies:
                source(b.source_id); source(b.layer.source_id)
                units.append(PrecursorUnit('body', b.body_id, b.layer, b.top_depth_m, b.bottom_depth_m,
                                           b.thermal_profile_id, b.fluid_material_id))
            for u in units:
                p = thermal[u.thermal_profile_id]
            used_prior_ids = set()
            for f in fields:
                source(f.source_id)
                if f.prior is not None:
                    p = f.prior
                    o = origin_map[f.source_id]
                    used_prior_ids.add(p.prior_id)
                elif origin_map[f.source_id].kind == 'sampled_prior':
                    raise GeologyError('sampled-prior scalar input must retain its prior definition')
            for o in origins:
                if o.kind == 'sampled_prior' and o.basis_id not in used_prior_ids:
                    raise GeologyError('sampled-prior source has no retained prior definition')
            d = {'schema': _INITIAL_SCHEMA if initial else _SCHEMA, 'case_definition_id': case.definition_id,
                 'origins': [asdict(o) for o in origins], 'cooling_history': [asdict(h) for h in history],
                 'material_bases': [asdict(b) for b in bases], 'fields': [f.descriptor() for f in fields],
                 'bodies': [asdict(b) for b in bodies], 'body_order': body_order,
                 'library_id': None if library is None else library.library_id}
            raw = _json(d)
            if len(raw) > _MAX_DEFINITION_BYTES:
                raise GeologyError('precursor definition exceeds byte limit')
            for key, value in dict(case=case, sampling_domain=domain, origins=origins, cooling_history=history, material_bases=bases,
                    fields=fields, bodies=bodies, body_order=body_order, library=library, units=tuple(units),
                    state_id=hashlib.sha256(raw).hexdigest(), _definition=raw).items():
                object.__setattr__(self, key, value)
            maps = {'origins': origin_map, 'thermal': thermal, 'cooling': history_map, 'materials': materials,
                    'bases': base_map, 'cohorts': cohorts, 'geometry': geometry,
                    'fields': {f.name: f for f in fields}, 'bodies': {b.body_id: b for b in bodies},
                    'selectors': selectors}
            object.__setattr__(self, '_maps', MappingProxyType({k: MappingProxyType(v) for k, v in maps.items()}))
            _check_cancel(cancel)

    def descriptor(self):
        return json.loads(self._definition)

    def selector_keys(self, selector):
        return self._maps['selectors'].get((selector.kind, selector.keys), selector.keys)

    @property
    def retained_bytes_estimate(self):
        topology = self.case.topology
        retained = topology.retained_bytes if type(topology) is GeologicalDomain else topology.retained_bytes_estimate
        return (len(self._definition) + self.case.retained_bytes_estimate + retained
                + sum(g.retained_bytes for g in self._maps['geometry'].values())
                + 128*sum(len(keys) for keys in self._maps['selectors'].values())
                + 4096*len(self.units) + (0 if self.library is None else 4*self.library.nbytes))

    def preflight(self, *, require_temperature=False, require_porosity=False, required_fields=()):
        """Return all requested gaps. Unrequested stress/damage remain unresolved.

        Passing this input gate does not supply constitutive/thermal evolution,
        pressure-qualified laws or physical validation. Requirements are explicit.
        """
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

    def require_reference_densities(self, temperature_k, *, material_ids=None):
        """Reference mass bookkeeping only; does not evaluate hot/pressurised mass."""
        t = scalar(temperature_k, 'density reference temperature', nonnegative=True)
        if material_ids is not None:
            _names(material_ids, 'reference-density materials')
        return t

    __deepcopy__ = _immutable_deepcopy


@dataclass(frozen=True, slots=True, init=False)
class InitialConditionState(PrecursorState):
    """W01 Stage 5 inputs on regional, whole-sphere or pre-partition geology.

    Shares the R2 contracts while retaining the actual geological case, its
    topology, source records and precedence. No motion or evolving W02 state is
    inferred. Spatial-prior domain IDs refer to the original topology identity.
    """


def _precursor_snapshot(state):
    cm, ca = _snapshot(state.case)
    arrays = {'case__'+k: v for k, v in ca.items()}
    arrays['precursor_definition'] = np.frombuffer(state._definition, dtype='u1')
    if state.library is not None:
        arrays['material_library'] = np.frombuffer(state.library._payload, dtype='u1')
    meta = {'schema': _SNAPSHOT, 'state_id': state.state_id, 'case': cm}
    return meta, arrays


def _restore_prior(d):
    args = dict(d); args.pop('schema')
    for k in ('wavelengths_m', 'origin_m'):
        args[k] = tuple(args[k])
    return SeededSpatialPrior(**args)


def restore_precursor_state(metadata, arrays, expected_id, *, budget=None, cancel=None):
    """Strict self-contained restoration; no imports from metadata or regeneration."""
    _check_cancel(cancel)
    a = arrays['precursor_definition']
    raw = a.tobytes()
    try:
        d = json.loads(raw)
        if type(d) is not dict or d.get('schema') not in (_SCHEMA, _INITIAL_SCHEMA) or _json(d) != raw:
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
            from atlas_tectonics.history.geological_records import LayerComponent
            bodies = []
            for b in d['bodies']:
                layer = dict(b['layer']); layer['components'] = tuple(LayerComponent(**c) for c in layer['components'])
                selector = dict(b['selector']); selector['keys'] = tuple(selector['keys'])
                bodies.append(SubsurfaceBody(**(dict(b) | {'layer': GeologicalLayer(**layer), 'selector': SurfaceSelector(**selector)})))
            cls = InitialConditionState if d['schema'] == _INITIAL_SCHEMA else PrecursorState
            result = cls(case, origins=tuple(InputOrigin(**r) for r in d['origins']),
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
    policy = store._budget if budget is None else budget
    _check_cancel(cancel)
    with select_budget(policy).reserve(4*state.retained_bytes_estimate+65536, category='precursor-save'):
        metadata, arrays = _precursor_snapshot(state)
        return store.put(state.state_id, arrays, metadata, budget=policy, cancel=cancel)


def load_precursor_state(store, state_id, *, budget=None, cancel=None):
    _check_cancel(cancel)
    policy = store._budget if budget is None else budget
    arrays = store.get(state_id, budget=policy)
    if arrays is None:
        return None
    return restore_precursor_state(store.metadata(state_id), arrays, state_id, budget=policy, cancel=cancel)
