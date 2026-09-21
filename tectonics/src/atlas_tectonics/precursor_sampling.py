"""R2 point sampling and conservative initial prism/shell-sector inventories.

No plate ID is required or emitted. Constant-depth layers and explicit body bands
are intersected with actual area geometry, in declared precedence order. Mixed
cells are split before accounting; a point winner is never a cell average.
Thermal means are volume-weighted temperatures, NOT conserved heat inventories.
The spherical metric uses true radial shell volume, not surface area * depth.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack, nullcontext
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass, field, asdict
import hashlib
import json
import math
import threading
import warnings
from types import MappingProxyType

import numpy as np
import shapely
from shapely.strtree import STRtree

from ._validation import scalar, input_shape, read_array, TectonicsError
from .geological_records import GeologyError, _name, _names, _tuple
from .geological_case import _json, _check_geometry_frame
from .geometry import PlanarGeometry, GeometryLimits, GeometryError, _check_cancel
from .spherical_geometry import SphericalGeometry, _directions
from .geometry_index import GeometryIndex, GeometryFeature
from ._spherical_candidates import SphericalCandidateIndex
from .precursor import PrecursorState, InitialConditionState, SeededSpatialPrior, _digest
from .parameters import ThermalParameters
from .thermal import half_space_temperature
from .resources import select_budget
from .reuse import ExecutionContext

_METHOD = 'atlas.precursor-sampling.v3'


@dataclass(frozen=True, slots=True)
class PrecursorSamplingLimits:
    """Finite work and explicitly registered numerical policy, not physical scale.

    Inventory tolerance diagnoses round-off from unsnapped binary64 overlays; it
    never changes geometry or renormalises material. Thermal tolerances apply to
    quadrature of INITIAL profiles, not to a W03 evolution timestep.
    """
    max_points: int = 1_000_000
    max_cells: int = 100_000
    max_rows: int = 1_000_000
    max_work_items: int = 2_000_000
    batch_points: int = 32768
    thermal_absolute_k: float = 1e-8
    thermal_relative: float = 1e-11
    inventory_relative: float = 2e-11
    quadrature_intervals: int = 128

    def __post_init__(self):
        for name in ('max_points', 'max_cells', 'max_rows', 'max_work_items', 'batch_points', 'quadrature_intervals'):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise GeologyError(name+' must be a positive integer')
        for name in ('thermal_absolute_k', 'thermal_relative', 'inventory_relative'):
            object.__setattr__(self, name, scalar(getattr(self, name), name, positive=True))
        if self.thermal_relative >= 1 or self.inventory_relative >= 1:
            raise GeologyError('relative tolerances must be below one')


@dataclass(frozen=True, slots=True)
class InitialSamplingCell:
    """A query support, not a plate: area footprint times a constant depth band.

    Planar volume uses metres cubed in the declared frame. On a sphere, the
    footprint follows minor arcs and depth is radial inward. Bands are half-open
    [top,bottom) for point ownership; surfaces have zero extensive volume.
    """
    cell_id: str
    footprint: PlanarGeometry | SphericalGeometry
    top_depth_m: float
    bottom_depth_m: float

    def __post_init__(self):
        _name(self.cell_id, 'sampling cell')
        if type(self.footprint) not in (PlanarGeometry, SphericalGeometry) or self.footprint.is_empty or self.footprint.kind not in ('Polygon', 'MultiPolygon'):
            raise GeologyError('sampling cells require nonempty area footprints')
        top = scalar(self.top_depth_m, 'cell top', nonnegative=True)
        bottom = scalar(self.bottom_depth_m, 'cell bottom', positive=True)
        if bottom <= top:
            raise GeologyError('sampling cell depth interval must increase')
        object.__setattr__(self, 'top_depth_m', top); object.__setattr__(self, 'bottom_depth_m', bottom)
        if type(self.footprint) is SphericalGeometry and bottom >= self.footprint.chart.sphere.radius_m:
            raise GeologyError('spherical sample must remain outside the centre')

    def descriptor(self):
        return {'cell_id': self.cell_id, 'footprint_id': self.footprint.geometry_id,
                'top_depth_m': self.top_depth_m, 'bottom_depth_m': self.bottom_depth_m}

    @property
    def volume_m3(self):
        return _volume(self.footprint, self.top_depth_m, self.bottom_depth_m)


def _depth_factor(top, bottom, radius=None):
    delta = bottom-top
    if radius is None:
        return delta
    # Factor a difference of cubes to preserve thin-shell resolution. Working in
    # radius ratios also avoids cubing planet-sized SI coordinates unnecessarily.
    a = (radius-top)/radius; b = (radius-bottom)/radius
    value = delta*(a*a+a*b+b*b)/3
    if not math.isfinite(value) or value <= 0:
        raise GeologyError('radial volume metric is outside numerical range')
    return value


def _volume(geometry, top, bottom):
    radius = geometry.chart.sphere.radius_m if type(geometry) is SphericalGeometry else None
    v = geometry.area_m2*_depth_factor(top, bottom, radius)
    if not math.isfinite(v) or v <= 0:
        raise GeologyError('sampled extensive volume is outside numerical range')
    return v


def _temperature(profile, depths, time_s, budget):
    """Reuse existing E04 for half-space values; tabulation never extrapolates."""
    if profile.mode == 'unknown':
        raise GeologyError('initial temperature is unresolved: '+profile.profile_id)
    if profile.mode == 'constant':
        return np.full(len(depths), profile.temperatures_k[0], dtype=np.float64)
    if profile.mode == 'tabulated':
        if np.any(depths < 0) or np.any(depths > profile.depths_m[-1]):
            raise GeologyError('thermal table extrapolation is refused')
        return np.interp(depths, profile.depths_m, profile.temperatures_k)
    return half_space_temperature(depths, time_s-profile.cooling_start_time_s,
        ThermalParameters(profile.profile_id, profile.source_id, *profile.temperatures_k, profile.diffusivity_m2_s), budget=budget)


def _profile_mean(profile, top, bottom, time_s, radius, limits, cancel):
    """Initial temperature mean and numerical error estimate on one depth band.

    Constant/linear tables integrate analytically with the radial quadratic
    weight. E04 uses bounded adaptive quadrature on a normalised interval, split
    at its known diffusion scale. Failure to meet the declared error refuses the
    result; no coarser or isothermal fallback is allowed.
    """
    if profile.mode == 'unknown':
        raise GeologyError('cannot average unresolved initial temperature')
    if profile.mode == 'constant':
        return profile.temperatures_k[0], 0.
    delta = bottom-top
    denominator = _depth_factor(top, bottom, radius)
    if profile.mode == 'tabulated':
        if bottom > profile.depths_m[-1]:
            raise GeologyError('thermal table extrapolation is refused')
        lo = bisect_right(profile.depths_m, top)
        hi = bisect_left(profile.depths_m, bottom)
        cuts = (top, *profile.depths_m[lo:hi], bottom)
        # Capture/interpolate the table once, not once per integration segment.
        # Same knots, segment formula and fsum order as the retained algorithm.
        temperatures = np.interp(cuts, profile.depths_m, profile.temperatures_k)
        values = []
        for a, b, ta, tb in zip(cuts, cuts[1:], temperatures, temperatures[1:]):
            h = b-a
            if radius is None:
                value = h*(ta+tb)/2
            else:
                r = (radius-a)/radius; q = h/radius
                w0 = r*r-r*q+q*q/3
                w1 = r*r/2-2*r*q/3+q*q/4
                value = h*(ta*w0+(tb-ta)*w1)
            values.append(value)
        result = math.fsum(values)/denominator
        if not math.isfinite(result) or result < 0:
            raise GeologyError('thermal mean outside numerical range')
        return result, 0.
    age = time_s-profile.cooling_start_time_s
    length = 2*math.sqrt(profile.diffusivity_m2_s)*math.sqrt(age)
    if not math.isfinite(length) or (age > 0 and length <= 0):
        raise GeologyError('thermal diffusion scale is not representable')
    ts, tm = profile.temperatures_k
    if age == 0:
        # The surface has zero volume; all positive-depth interior is at Tm.
        return tm, 0.
    def fn(q):
        _check_cancel(cancel)
        z = top+q*delta
        temperature = ts+(tm-ts)*math.erf(z/length)
        weight = 1. if radius is None else ((radius-z)/radius)**2
        return temperature*weight*delta/denominator
    cuts = sorted({(f*length-top)/delta for f in (.01, .1, 1., 2., 4., 8.) if top < f*length < bottom})
    from scipy.integrate import quad, IntegrationWarning
    with warnings.catch_warnings():
        warnings.simplefilter('error', IntegrationWarning)
        try:
            mean, error = quad(fn, 0., 1., epsabs=limits.thermal_absolute_k,
                epsrel=limits.thermal_relative, limit=limits.quadrature_intervals, points=cuts or None)
        except IntegrationWarning as exc:
            raise GeologyError('initial thermal quadrature did not converge') from exc
    if not math.isfinite(mean) or not math.isfinite(error) or mean < 0 or error > max(limits.thermal_absolute_k, limits.thermal_relative*abs(mean)):
        raise GeologyError('initial thermal quadrature error exceeds its registered policy')
    return mean, error


def _temperature_bounds(profile, top, bottom, time_s, budget):
    """Extrema of the declared constant, piecewise-linear or monotone E04 profile."""
    if profile.mode == 'constant':
        return profile.temperatures_k[0], profile.temperatures_k[0]
    if profile.mode == 'tabulated':
        zs, ts = profile.depths_m, profile.temperatures_k
        if top < 0 or bottom > zs[-1]:
            raise GeologyError('thermal table extrapolation is refused')
        def at(z):
            i = bisect_right(zs, z)-1
            if i == len(zs)-1:
                return ts[i]
            return ts[i]+(ts[i+1]-ts[i])*((z-zs[i])/(zs[i+1]-zs[i]))
        a, b = at(top), at(bottom)
        lower, upper = min(a,b), max(a,b)
        for i in range(bisect_right(zs, top), bisect_left(zs, bottom)):
            lower = min(lower,ts[i]); upper = max(upper,ts[i])
        return lower, upper
    values = _temperature(profile, np.array([top, bottom]), time_s, budget)
    return float(min(values)), float(max(values))


def _material_temperature_validity(state, unit, lower, upper):
    """Check declared temperature ranges, without inventing constitutive laws.

    Missing ranges are explicitly uncertified. An out-of-range active solid or
    pore fluid refuses the requested thermal result, even if its cell mean fits.
    """
    known = True
    for mid in _active_materials(state, unit):
        interval = state._maps['materials'][mid].valid_temperature_k
        if interval is None:
            known = False
        elif np.any(lower < interval[0]) or np.any(upper > interval[1]):
            raise GeologyError('initial temperature outside material validity: '+mid)
    return known


def _active_materials(state, unit):
    materials = {state._maps['cohorts'][c.cohort_id].material_id for c in unit.layer.components
                 if c.solid_volume_fraction > 0}
    if unit.fluid_material_id is not None and unit.layer.porosity != 0:
        materials.add(unit.fluid_material_id)
    return materials


def _sinc_minus_one(x):
    if abs(x) < 1e-3:
        xx = x*x
        return xx*(-1/6+xx*(1/120-xx/5040))
    return math.sin(x)/x-1


def _ring_wave_integral(coordinates, kx, ky, centre, cancel=None):
    """Complex area integral by the divergence theorem, orientation preserved.

    Subtract the analytically cancelling constant boundary term before summing.
    expm1/sinc-style expressions avoid cancellation for long-wavelength priors.
    This is geometric integration of a declared prior, not a physical law.
    """
    norm2 = kx*kx+ky*ky
    pts = [(float(x)-centre[0], float(y)-centre[1]) for x, y in coordinates]
    signed_area = math.fsum(a[0]*b[1]-b[0]*a[1] for a, b in zip(pts, pts[1:]))/2
    if norm2 == 0:
        return complex(signed_area, 0.)
    real = []; imag = []
    for index, ((x, y), (xx, yy)) in enumerate(zip(pts, pts[1:])):
        if index % 1024 == 0:
            _check_cancel(cancel)
        dx, dy = xx-x, yy-y
        angle = kx*(x+xx)/2+ky*(y+yy)/2
        half = (kx*dx+ky*dy)/2
        if max(abs(angle), abs(half)) > 2**40:
            raise GeologyError('cell prior phase is insufficiently resolved')
        sm1 = _sinc_minus_one(half); sinc = 1+sm1
        c = kx*dy-ky*dx
        real.append(c*((-2*math.sin(angle/2)**2)*sinc+sm1))
        imag.append(c*math.sin(angle)*sinc)
    # Divide by i*|k|^2.
    return complex(math.fsum(imag)/norm2, -math.fsum(real)/norm2)


def _polygons(shape):
    if shape.geom_type == 'Polygon':
        yield shape
    elif shape.geom_type in ('MultiPolygon', 'GeometryCollection'):
        for g in shape.geoms:
            yield from _polygons(g)


def _prior_mean(prior, footprint, top, bottom, cancel=None):
    """Analytic planar-prism cosine average; spherical point priors remain valid.

    General spherical volume integration of Cartesian modes is not implemented:
    refuse that requested mean instead of substituting the cell centre. Spherical
    material inventories and radial base-profile means are supported separately.
    """
    if type(footprint) is not PlanarGeometry:
        raise GeologyError('spherical cell means of Cartesian priors are not implemented; point sampling is supported')
    centre = ((footprint.bounds[0]+footprint.bounds[2])/2, (footprint.bounds[1]+footprint.bounds[3])/2)
    values = []
    for kx, ky, kz, phase in prior._waves:
        _check_cancel(cancel)
        pieces = []
        for polygon in _polygons(footprint._geom):
            ext = _ring_wave_integral(polygon.exterior.coords, kx, ky, centre, cancel)
            # Ring orientation is input provenance, not a signed material volume.
            sign = 1 if polygon.exterior.is_ccw else -1
            area = ext*sign
            for hole in polygon.interiors:
                val = _ring_wave_integral(hole.coords, kx, ky, centre, cancel)
                area -= val*(1 if hole.is_ccw else -1)
            pieces.append(area)
        horizontal = complex(math.fsum(v.real for v in pieces), math.fsum(v.imag for v in pieces))/footprint.area_m2
        a = (centre[0]-prior.origin_m[0])*kx + (centre[1]-prior.origin_m[1])*ky + ((top+bottom)/2-prior.origin_m[2])*kz + phase
        half = kz*(bottom-top)/2
        if max(abs(a), abs(half)) > 2**40:
            raise GeologyError('prior prism phase is insufficiently resolved')
        phase_factor = complex(math.cos(a), math.sin(a))*(1+_sinc_minus_one(half))
        values.append((horizontal*phase_factor).real)
    result = prior.mean + prior.amplitude*math.fsum(values)/len(values)
    if not math.isfinite(result) or abs(result-prior.mean) > prior.amplitude*(1+1e-10)+1e-12:
        raise GeologyError('prior cell integral failed its analytic range check')
    return result


@dataclass(frozen=True, slots=True, init=False)
class InitialSamples:
    """Immutable compact result. Array descriptor mutations never alter ownership.

    ``array`` returns a fresh view on private immutable bytes. Unknown numeric
    payloads have separate known masks; ``temperature`` and ``field_values``
    refuse unknowns by default. Phase rows preserve cohort IDs and origin dates
    through the shared precursor, not an object copied into every sampling cell.
    """
    state: PrecursorState
    sample_id: str
    kind: str
    _metadata: bytes = field(repr=False)
    _buffers: object = field(repr=False)

    def __init__(self, state, kind, metadata, arrays):
        buffers = {}
        hashes = {}
        for name, value in arrays.items():
            a = np.asarray(value, order='C')
            if a.dtype.kind not in 'biuf' or (a.dtype.kind == 'f' and not np.isfinite(a).all()):
                raise GeologyError('sample arrays must have finite plain numeric payloads')
            raw = a.tobytes()
            buffers[name] = (a.dtype.str, tuple(a.shape), raw)
            hashes[name] = {'dtype': a.dtype.str, 'shape': a.shape, 'sha256': hashlib.sha256(raw).hexdigest()}
        md = dict(metadata, schema='atlas.initial-samples.v1', kind=kind, state_id=state.state_id, arrays=hashes)
        raw = _json(md)
        for key, val in dict(state=state, kind=kind, sample_id=hashlib.sha256(raw).hexdigest(), _metadata=raw,
                             _buffers=MappingProxyType(buffers)).items():
            object.__setattr__(self, key, val)

    def descriptor(self):
        return json.loads(self._metadata)

    @property
    def nbytes(self):
        return len(self._metadata)+sum(len(v[2]) for v in self._buffers.values())

    def array(self, name):
        try:
            dtype, shape, raw = self._buffers[name]
        except KeyError as exc:
            raise GeologyError('unknown initial-sample array: '+str(name)) from exc
        return np.frombuffer(raw, dtype=dtype).reshape(shape)

    def temperature(self):
        if not self.array('temperature_known').all():
            raise GeologyError('temperature contains unresolved initial values')
        return self.array('temperature_k')

    def field_values(self, name):
        fields = self.descriptor()['requested_fields']
        if name not in fields:
            raise GeologyError('field was not sampled')
        index = fields.index(name)
        if not self.array('field_known')[:, index].all():
            raise GeologyError('requested field is unresolved')
        return self.array('field_values')[:, index]


def _sparse_associations(count, rows, codes):
    """COO -> CSR, preserving the caller's precedence within each query row."""
    if not rows:
        return np.zeros(count+1, dtype=np.int64), np.empty(0, dtype=np.int32)
    indices = np.concatenate(rows); values = np.concatenate(codes)
    order = np.argsort(indices, kind='stable')
    offsets = np.zeros(count+1, dtype=np.int64)
    offsets[1:] = np.cumsum(np.bincount(indices, minlength=count))
    return offsets, values[order]


class PreparedPrecursor:
    """Reusable native indexes and compact units under the existing shared budget.

    The accepted state, native indexes and metadata remain reserved until close.
    A verified ExecutionContext covers source/runtime invalidation. The existing
    KernelExecutor provides admitted parallel batches; no second scheduler or
    alternative persistence service is added.
    Public scientific inputs are immutable. Close only after joining readers.
    """
    def __setattr__(self, name, value):
        if name in ('state', 'limits', 'geometry_limits', 'budget', 'identity', 'execution_policy') and hasattr(self, name):
            raise GeologyError('prepared scientific inputs are immutable; prepare a new state')
        object.__setattr__(self, name, value)

    def __init__(self, state, *, limits=None, geometry_limits=None, budget=None, cancel=None, execution_policy=None):
        _check_cancel(cancel)
        if type(state) not in (PrecursorState, InitialConditionState):
            raise GeologyError('typed geological precursor required')
        from .precursor_execution import PrecursorExecutionPolicy
        self.execution_policy = PrecursorExecutionPolicy() if execution_policy is None else execution_policy
        if type(self.execution_policy) is not PrecursorExecutionPolicy:
            raise GeologyError('typed PrecursorExecutionPolicy required')
        self._dispatch_lock = threading.Lock()
        self._executor = None
        self._last_execution = {'route': 'not-run', 'batches': 0, 'parallel_jobs': 0}
        self.state = state
        self.limits = PrecursorSamplingLimits() if limits is None else limits
        self.geometry_limits = GeometryLimits() if geometry_limits is None else geometry_limits
        if type(self.limits) is not PrecursorSamplingLimits or type(self.geometry_limits) is not GeometryLimits:
            raise GeologyError('typed sampling and geometry limits required')
        self.budget = select_budget(budget)
        self._lock = threading.Lock(); self._active = 0; self._closed = False
        # The secondary area tree and unit/source maps are additional to the
        # shared geometry and GeometryIndex. The 5 MiB allowance covers the
        # existing context's <=2 MiB source snapshot, its verification copy and
        # callable metadata. Charge before native setup; this is not an RSS cap.
        setup_allowance = (state.retained_bytes_estimate + 512*len(state._maps['geometry'])
                           + 512*len(state.units) + 5*1024**2)
        self._guard = self.budget.reserve(setup_allowance, category='precursor-plan-retained')
        self._guard.__enter__(); self._index = None; self._context = None; self._spherical_areas = None
        try:
            self._topology_footprints = frozenset(r.geometry.geometry_id for r in state.case.topology.regions)
            features = tuple(GeometryFeature(k, g) for k, g in state._maps['geometry'].items())
            if features:
                self._index = GeometryIndex(features, limits=self.geometry_limits, budget=self.budget)
            self._area_keys = tuple(k for k, g in state._maps['geometry'].items() if g.kind in ('Polygon', 'MultiPolygon'))
            self._area_tree = None
            if self._area_keys and state.sampling_domain.sphere is None:
                # Bounds only prune candidates; exact overlays remain authoritative.
                self._area_tree = STRtree([state._maps['geometry'][k]._geom for k in self._area_keys])
            elif self._area_keys:
                self._spherical_areas = SphericalCandidateIndex(
                    tuple(state._maps['geometry'][k] for k in self._area_keys),
                    budget=self.budget, cancel=cancel)
            self._column_units = {}
            self._body_units = {}
            for i, u in enumerate(state.units):
                if u.kind == 'column':
                    self._column_units.setdefault(u.owner_id, []).append(i)
                else:
                    self._body_units[u.owner_id] = i
            self._column_units = MappingProxyType({k: tuple(v) for k, v in self._column_units.items()})
            self._body_units = MappingProxyType(self._body_units)
            self._column_edges = MappingProxyType({c.column_id: c.layer_edges_m for c in state.case.columns})
            self._column_edge_arrays = MappingProxyType({k: np.frombuffer(np.asarray(v, dtype='f8').tobytes(), dtype='f8')
                                                        for k, v in self._column_edges.items()})
            lower = []; upper = []; known = []
            for unit in state.units:
                ranges = [state._maps['materials'][mid].valid_temperature_k for mid in _active_materials(state, unit)]
                lower.append(max((r[0] for r in ranges if r is not None), default=-math.inf))
                upper.append(min((r[1] for r in ranges if r is not None), default=math.inf))
                known.append(all(r is not None for r in ranges))
            self._unit_lower = np.frombuffer(np.asarray(lower, dtype='f8').tobytes(), dtype='f8')
            self._unit_upper = np.frombuffer(np.asarray(upper, dtype='f8').tobytes(), dtype='f8')
            self._unit_validity_known = np.frombuffer(np.asarray(known, dtype='?').tobytes(), dtype='?')
            self._province_codes = MappingProxyType({p.province_id: i for i, p in enumerate(state.case.provinces)})
            self._zone_codes = MappingProxyType({z.zone_id: i for i, z in enumerate(state.case.weak_zones)})
            self._cohort_ids = tuple(c.cohort.cohort_id for c in state.case.cohorts)
            self._cohort_codes = {k: i for i, k in enumerate(self._cohort_ids)}
            self._material_ids = tuple(m.material_id for m in state.case.materials)
            self._material_codes = {k: i for i, k in enumerate(self._material_ids)}
            self._context = ExecutionContext('scipy')
            self.identity = _digest({'method': _METHOD, 'state': state.state_id,
                'execution': self._context.identity, 'limits': asdict(self.limits),
                'geometry_limits': asdict(self.geometry_limits)})
            _check_cancel(cancel)
        except BaseException:
            try:
                if self._index is not None:
                    self._index.close()
                if self._spherical_areas is not None:
                    self._spherical_areas.close()
                if self._context is not None:
                    self._context.close()
            finally:
                self._guard.__exit__(None, None, None)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        with self._lock:
            if self._active:
                raise GeologyError('join active sampling calls before closing the precursor plan')
            if not self._closed:
                if self._executor is not None and self._executor._entered and threading.get_ident() != self._executor._owner_thread:
                    raise GeologyError('close the sampling executor on its driving thread')
                self._closed = True
                try:
                    if self._executor is not None:
                        self._executor.close()
                    if self._index is not None:
                        self._index.close()
                    if self._spherical_areas is not None:
                        self._spherical_areas.close()
                    self._context.close()
                finally:
                    # Source invalidation may make context.close raise. Native
                    # indexes/snapshots and their admission must still be released.
                    self._index = None; self._context = None; self._area_tree = None
                    self._guard.__exit__(None, None, None)

    @contextmanager
    def _operation(self, cancel):
        with self._lock:
            if self._closed:
                raise GeologyError('precursor plan is closed')
            self._active += 1
        try:
            _check_cancel(cancel); self._context.verify()
            yield
            _check_cancel(cancel); self._context.verify()
        finally:
            with self._lock:
                self._active -= 1

    def _check_request(self, frame_id, epoch_id, depth_reference_id):
        if self._closed:
            raise GeologyError('precursor plan is closed')
        case = self.state.case
        if frame_id != self.state.sampling_domain.frame_id or epoch_id != case.epoch_id or depth_reference_id != case.depth_reference_id:
            raise GeologyError('sampling frame, epoch or depth reference differs; explicit conversion is required')

    def _coordinate_points(self, points, depths):
        if self.state.sampling_domain.sphere is None:
            return np.column_stack((points, depths))
        return points*(self.state.sampling_domain.sphere.radius_m-depths[:, None])

    def _field_arrays(self, names, coordinates, cancel, budget=None):
        budget = self.budget if budget is None else budget
        _names(names, 'requested fields', ordered=True)
        values = np.zeros((len(coordinates), len(names)), dtype=np.float64)
        known = np.zeros_like(values, dtype=bool)
        for j, name in enumerate(names):
            f = self.state._maps['fields'].get(name)
            if f is None:
                raise GeologyError('unknown requested field: '+name)
            if f.unknown_reason is None:
                values[:, j] = f.constant_value if f.prior is None else f.prior.evaluate(coordinates,
                    budget=budget, cancel=cancel, batch_points=self.limits.batch_points)
                known[:, j] = True
        return values, known

    def _check_unit_temperature(self, code, lower, upper):
        if lower < self._unit_lower[code] or upper > self._unit_upper[code]:
            # Preserve the precise offending material diagnostic on refusal.
            _material_temperature_validity(self.state, self.state.units[code], lower, upper)
        return self._unit_validity_known[code]

    def execution_statistics(self):
        """Detached last-dispatch diagnostics; not part of scientific identity."""
        return dict(self._last_execution)

    def sample_points(self, points, depths_m, *, frame_id, epoch_id, depth_reference_id,
                      fields=(), require_temperature=True, cancel=None):
        from .precursor_execution import sample_points
        return sample_points(self, points, depths_m, frame_id=frame_id, epoch_id=epoch_id,
            depth_reference_id=depth_reference_id, fields=fields,
            require_temperature=require_temperature, cancel=cancel)

    def _sample_points_serial(self, points, depths_m, *, frame_id, epoch_id, depth_reference_id,
                      fields=(), require_temperature=True, cancel=None, _admitted_budget=None, _ledger=None):
        """Exact point membership with explicit precedence and all province matches.

        Spherical inputs are direction vectors, planar inputs are (x,y) metres.
        Depth is a scalar or an (n,) vector. Layer/body intervals are half-open;
        points below supplied material support are errors, never mantle guesses.
        """
        budget = self.budget if _admitted_budget is None else _admitted_budget
        self._check_request(frame_id, epoch_id, depth_reference_id)
        if type(require_temperature) is not bool:
            raise GeologyError('require_temperature must be bool')
        shape = input_shape(points, 'sampling points')
        dim = 2 if self.state.sampling_domain.sphere is None else 3
        if len(shape) != 2 or shape[1] != dim or not 0 < shape[0] <= self.limits.max_points:
            raise GeologyError('point dimensions or count outside sampling envelope')
        _names(fields, 'requested fields', ordered=True)
        n = shape[0]
        if input_shape(depths_m, 'depths') not in ((), (n,)):
            raise GeologyError('depth must be scalar or one value per point')
        if n*(len(self.state.case.weak_zones)+len(self.state.case.provinces)+len(self.state.bodies)+1) > self.limits.max_work_items:
            raise GeologyError('point selector work exceeds policy; request explicit smaller batches')
        # Worst-case hit counts are bounded before allocation; no dense N*feature
        # array is constructed. Native index query has its own joined allowance.
        row_bound = min(n*(len(self.state.case.provinces)+len(self.state.case.weak_zones)+1), self.limits.max_rows)
        hit_bound = min(n*len(self.state._maps['geometry']), self.geometry_limits.max_hits)
        required = 256*n + 32*n*len(fields) + 96*row_bound + 48*hit_bound + 65536
        with (self._operation(cancel) if _admitted_budget is None else nullcontext()), budget.reserve(required, category='precursor-points'):
            p = read_array(points, 'sampling points', ndim=2)
            if p.shape != shape:
                raise GeologyError('sampling point shape changed during capture')
            if dim == 3:
                p = _directions(p)
            zraw = read_array(depths_m, 'depths', nonnegative=True)
            z = np.full(n, float(zraw)) if zraw.ndim == 0 else zraw
            if z.shape != (n,):
                raise GeologyError('depth shape changed during capture')
            domain = self.state.sampling_domain
            if not domain.full_sphere and np.any(domain.domain.classify(p, limits=self.geometry_limits, budget=budget, cancel=cancel) < 0):
                raise GeologyError('sampling point outside declared geological domain')
            if domain.sphere is not None and np.any(z >= domain.sphere.radius_m):
                raise GeologyError('point lies at or below spherical centre')
            # Group sparse indexed hits once by feature. Native unions and grouped
            # searchsorted replace a Python set/object graph per point. No dense
            # point-by-all-features matrix is created.
            feature_points = {}
            if self._index is not None:
                hits = (self._index.query(p, budget=budget, cancel=cancel) if _admitted_budget is None else
                        self._index._admitted_query(p, budget=budget, cancel=cancel))
                if _ledger is not None:
                    _ledger.charge(hits=len(hits.pairs))
                pairs = hits.pairs
                if len(pairs):
                    order = np.argsort(pairs[:, 1], kind='stable')
                    grouped = pairs[order]
                    cuts = np.flatnonzero(np.diff(grouped[:, 1]))+1
                    for group in np.split(grouped, cuts):
                        feature_points[hits.feature_ids[int(group[0, 1])]] = group[:, 0]
            all_points = np.arange(n, dtype=np.int64)
            def selected_points(selector):
                if selector.kind == 'domain':
                    return all_points
                parts = [feature_points[k] for k in self.state.selector_keys(selector) if k in feature_points]
                return np.unique(np.concatenate(parts)) if parts else np.empty(0, dtype=np.int64)
            case = self.state.case
            pcodes = np.full(n, -1, dtype=np.int32); ucodes = np.full(n, -1, dtype=np.int32)
            province_rows = []; province_values = []; candidate_count = 0
            # Reverse traversal permits native overwrite by the higher-priority
            # province. CSR associations below retain every original match.
            for pid in reversed(case.precedence.province_order):
                _check_cancel(cancel)
                province = case._lookups['provinces'][pid]
                selected = selected_points(province.selector)
                candidate_count += len(selected)
                if candidate_count > self.limits.max_rows:
                    raise GeologyError('province-match result exceeds sparse-row envelope')
                code = self._province_codes[pid]
                pcodes[selected] = code
                province_rows.append(selected)
                province_values.append(np.full(len(selected), code, dtype=np.int32))
            offsets, candidate_codes = _sparse_associations(n, province_rows[::-1], province_values[::-1])
            for code in np.unique(pcodes):
                _check_cancel(cancel)
                if code < 0:
                    raise GeologyError('precursor provinces leave uncovered points')
                selected = np.flatnonzero(pcodes == code)
                column = case.column(case.provinces[int(code)].column_id)
                j = np.searchsorted(self._column_edge_arrays[column.column_id], z[selected], side='right')-1
                known = (j >= 0) & (j < len(column.layers))
                ucodes[selected[known]] = np.asarray(self._column_units[column.column_id], dtype=np.int32)[j[known]]
            for body_id in reversed(self.state.body_order):
                _check_cancel(cancel)
                body = self.state._maps['bodies'][body_id]
                selected = selected_points(body.selector)
                active = (z[selected] >= body.top_depth_m) & (z[selected] < body.bottom_depth_m)
                ucodes[selected[active]] = self._body_units[body_id]
            if np.any(ucodes < 0):
                raise GeologyError('point is below the supplied layer/body support')
            temperature = np.zeros(n); tknown = np.zeros(n, dtype=bool)
            for code in np.unique(ucodes):
                _check_cancel(cancel)
                selected = ucodes == code
                profile = self.state._maps['thermal'][self.state.units[int(code)].thermal_profile_id]
                if profile.mode != 'unknown':
                    temperature[selected] = _temperature(profile, z[selected], case.time_s, budget)
                    tknown[selected] = True
            xyz = self._coordinate_points(p, z)
            fv, fk = self._field_arrays(fields, xyz, cancel, budget)
            offsets_field = [f for f in self.state.fields if f.role == 'temperature_offset']
            if offsets_field:
                f = offsets_field[0]
                if f.unknown_reason is not None:
                    tknown[:] = False; temperature[:] = 0
                else:
                    extra = f.constant_value if f.prior is None else f.prior.evaluate(xyz, budget=budget, cancel=cancel,
                                                                                   batch_points=self.limits.batch_points)
                    temperature[tknown] += extra if np.ndim(extra) == 0 else extra[tknown]
            if np.any(temperature[tknown] < 0):
                raise GeologyError('initial temperature is below absolute zero')
            if require_temperature and not tknown.all():
                raise GeologyError('requested initial temperature is unresolved')
            bad = tknown & ((temperature < self._unit_lower[ucodes]) | (temperature > self._unit_upper[ucodes]))
            if np.any(bad):
                i = int(np.flatnonzero(bad)[0])
                self._check_unit_temperature(int(ucodes[i]), temperature[i], temperature[i])
            validity = tknown & self._unit_validity_known[ucodes]
            # Exact finite-trace distances, never buffer-polygon membership. Work
            # remains batched and bounded; each corridor is traversed separately.
            weak_rows = []; weak_values = []; weak_count = 0
            zone_order = (tuple(sorted(self._zone_codes)) if case.precedence.weak_zone_mode == 'retain_all'
                          else case.precedence.weak_zone_order)
            claimed = np.zeros(n, dtype=bool)
            zones = {zone.zone_id: zone for zone in case.weak_zones}
            for zid in zone_order:
                _check_cancel(cancel)
                zone = zones[zid]
                active = (z >= zone.top_depth_m) & (z < zone.bottom_depth_m)
                if zone.half_width_m is None:
                    possible = selected_points(zone.selector)
                    selected = possible[active[possible]]
                else:
                    possible = np.flatnonzero(active); mask = np.zeros(len(possible), dtype=bool)
                    for key in zone.selector.keys:
                        if len(possible):
                            mask |= self.state._maps['geometry'][key].within_distance(p[possible], zone.half_width_m,
                                limits=self.geometry_limits, budget=budget, cancel=cancel)
                    selected = possible[mask]
                if case.precedence.weak_zone_mode != 'retain_all':
                    selected = selected[~claimed[selected]]
                    claimed[selected] = True
                weak_count += len(selected)
                if weak_count+candidate_count > self.limits.max_rows:
                    raise GeologyError('point feature associations exceed sparse-row envelope')
                weak_rows.append(selected)
                weak_values.append(np.full(len(selected), self._zone_codes[zid], dtype=np.int32))
            if _ledger is not None:
                _ledger.charge(rows=weak_count+candidate_count)
            wo, wc = _sparse_associations(n, weak_rows, weak_values)
            arrays = dict(points=p, depths_m=z, unit_code=ucodes, province_code=pcodes,
                province_offsets=np.asarray(offsets, dtype=np.int64), province_candidates=np.asarray(candidate_codes, dtype=np.int32),
                weak_zone_offsets=np.asarray(wo, dtype=np.int64), weak_zone_codes=np.asarray(wc, dtype=np.int32),
                temperature_k=temperature, temperature_known=tknown, field_values=fv, field_known=fk,
                material_temperature_validity_known=validity)
            return InitialSamples(self.state, 'points', {'plan_id': self.identity, 'requested_fields': fields,
                'frame_id': frame_id, 'epoch_id': epoch_id, 'time_s': case.time_s, 'depth_reference_id': depth_reference_id,
                'temperature_semantics': 'initial point temperature; not evolved heat',
                'material_temperature_validity': 'declared ranges only; unknown ranges masked; not constitutive-law approval',
                'interval_policy': 'top-inclusive, bottom-exclusive; explicit areal precedence'}, arrays)

    def _candidate_keys(self, footprint, *, budget=None, prepaid=False, cancel=None):
        if self._area_tree is not None:
            return {self._area_keys[int(i)] for i in self._area_tree.query(footprint._geom)}
        if self._spherical_areas is not None:
            return {self._area_keys[int(i)] for i in self._spherical_areas.query(footprint, budget=budget, prepaid=prepaid, cancel=cancel)}
        return set()

    def _validate_cell_overlaps(self, cells, budget, cancel):
        """Reuse certified whole-sphere face disjointness, not a giant overlay.

        Only exact topology-owned footprints qualify. Arbitrary query polygons
        retain the existing explicit geometric overlap checks and refusals.
        """
        from .spherical_atlas import SphericalAtlas
        topology = self.state.case.topology
        if type(topology) is SphericalAtlas:
            if all(c.footprint.geometry_id in self._topology_footprints for c in cells):
                bands = {}
                for c in cells:
                    _check_cancel(cancel)
                    bands.setdefault(c.footprint.geometry_id, []).append((c.top_depth_m, c.bottom_depth_m))
                for intervals in bands.values():
                    intervals.sort()
                    if any(b[0] < a[1] for a, b in zip(intervals, intervals[1:])):
                        raise GeologyError('sampling cells overlap in positive volume')
                return
        _check_cell_overlaps(cells, self.geometry_limits, self.limits, budget, cancel)

    def _take(self, remaining, selector, possible, cancel, work, budget=None):
        """Take a selector union once from an existing cell-local remainder.

        Avoid building a global union across hemispheres. Contacts carry no
        volume, but no positive-area sliver is discarded by a feature-size cutoff.
        """
        budget = self.budget if budget is None else budget
        if remaining is None or remaining.area_m2 == 0:
            return [], None
        if selector.kind == 'domain':
            return [remaining], None
        selected = []
        for key in self.state.selector_keys(selector):
            if key not in possible or remaining is None:
                continue
            work[0] += 1
            if work[0] > self.limits.max_work_items:
                raise GeologyError('cell overlay work exceeds explicit policy')
            g = self.state._maps['geometry'][key]
            if remaining.geometry_id == g.geometry_id:
                selected.append(remaining)
                return selected, None
            if remaining.geometry_id in self._topology_footprints and g.geometry_id in self._topology_footprints:
                # Distinct validated topology faces have no positive-area
                # overlap. Shared seams do not require a cross-horizon overlay.
                continue
            if _provably_disjoint(remaining, g):
                continue
            part = remaining.overlay(g, 'intersection', limits=self.geometry_limits, budget=budget, cancel=cancel)
            if part.area_m2 > 0:
                selected.append(part)
                rest = remaining.overlay(g, 'difference', limits=self.geometry_limits, budget=budget, cancel=cancel)
                remaining = rest if rest.area_m2 > 0 else None
        return selected, remaining

    def sample_cells(self, cells, *, frame_id, epoch_id, depth_reference_id, fields=(),
                     include_temperature=True, reference_mass_temperature_k=None,
                     allow_overlapping_queries=False, cancel=None):
        from .precursor_execution import sample_cells
        return sample_cells(self, cells, frame_id=frame_id, epoch_id=epoch_id,
            depth_reference_id=depth_reference_id, fields=fields,
            include_temperature=include_temperature, reference_mass_temperature_k=reference_mass_temperature_k,
            allow_overlapping_queries=allow_overlapping_queries, cancel=cancel)

    def _sample_cells_serial(self, cells, *, frame_id, epoch_id, depth_reference_id, fields=(),
                     include_temperature=True, reference_mass_temperature_k=None,
                     allow_overlapping_queries=False, cancel=None, _admitted_budget=None,
                     _prevalidated=False, _ledger=None):
        """Conservative material-volume inventories plus supported intensive means.

        Output bulk rows describe disjoint unit portions; phase rows distribute
        their matrix/pore volumes without renormalising fractions. Grain-only
        mixtures have known true solid volume. Bulk-reference aggregate mixtures
        retain matrix volume but mask intrinsic solid volume as unresolved.

        Mass, when explicitly requested, is labelled REFERENCE mass at the given
        temperature, not the actual mass of hot/pressurised lithosphere. Material
        density/heat laws are not extrapolated. Weak-zone masks are point queries,
        not fabricated averaged damage values. Overlapping volume queries need
        explicit authorisation and their sum is not a whole-mesh inventory.
        """
        budget = self.budget if _admitted_budget is None else _admitted_budget
        self._check_request(frame_id, epoch_id, depth_reference_id)
        _tuple(cells, 'sampling cells', allow_empty=False)
        if len(cells) > self.limits.max_cells or any(type(c) is not InitialSamplingCell for c in cells):
            raise GeologyError('bounded tuple of typed initial sampling cells required')
        if len({c.cell_id for c in cells}) != len(cells):
            raise GeologyError('sampling cell IDs must be unique')
        if type(include_temperature) is not bool or type(allow_overlapping_queries) is not bool:
            raise GeologyError('sampling switches must be bool')
        _names(fields, 'requested fields', ordered=True)
        for name in fields:
            if name not in self.state._maps['fields']:
                raise GeologyError('unknown requested field: '+name)
        reference_t = None
        if reference_mass_temperature_k is not None:
            reference_t = scalar(reference_mass_temperature_k, 'density reference temperature', nonnegative=True)
        n = len(cells); state = self.state; case = state.case
        unique_supports = {c.footprint.geometry_id: c.footprint for c in cells}
        vertices = sum(g.vertex_count for g in unique_supports.values())
        if vertices > self.geometry_limits.max_vertices:
            raise GeologyError('cell support vertices exceed explicit geometry policy')
        input_allowance = sum(g.retained_bytes for g in unique_supports.values())
        repeated_supports = len(unique_supports) < n
        required = (input_allowance + 256*n + 32*n*len(fields) + 512*vertices + 65536
                    + (128*len(unique_supports) if repeated_supports else 0))
        with (self._operation(cancel) if _admitted_budget is None else nullcontext()), budget.reserve(required, category='precursor-cells'), ExitStack() as retained_rows:
            support_counts = Counter(c.footprint.geometry_id for c in cells) if repeated_supports else {}
            if not _prevalidated:
                for g in unique_supports.values():
                    _check_geometry_frame(case.topology, g, self.geometry_limits, budget)
                if not allow_overlapping_queries:
                    self._validate_cell_overlaps(cells, budget, cancel)
            expected = np.asarray([c.volume_m3 for c in cells], dtype=np.float64)
            totals = np.zeros(n); residual = np.zeros(n)
            tv = np.zeros(n); tk = np.full(n, include_temperature, dtype=bool); te = np.zeros(n)
            validity = np.full(n, include_temperature, dtype=bool)
            fv = np.zeros((n, len(fields))); fk = np.zeros_like(fv, dtype=bool)
            offsets = [0]; rows = []; phase_rows = []
            from .precursor_execution import _WorkCounter
            thermal_cache = {}; work = _WorkCounter(_ledger); reserved_capacity = 0
            density_cache = {}; routing_cache = {}
            def reference_mass(mid, volume):
                if reference_t is None or volume == 0:
                    return 0.
                if mid not in density_cache:
                    state.require_reference_densities(reference_t, material_ids=(mid,))
                    density_cache[mid] = state._maps['materials'][mid].density_kg_m3
                return volume*density_cache[mid]
            offset_field = next((f for f in state.fields if f.role == 'temperature_offset'), None)
            for cell_index, cell in enumerate(cells):
                _check_cancel(cancel)
                gid = cell.footprint.geometry_id
                route = routing_cache.get(gid)
                if route is None:
                    possible = self._candidate_keys(cell.footprint, budget=budget, prepaid=_admitted_budget is not None, cancel=cancel)
                    candidate_provinces = [p for p in case.provinces if p.selector.kind == 'domain' or possible.intersection(state.selector_keys(p.selector))]
                    candidate_provinces.sort(key=lambda p: case._province_rank[p.province_id])
                    candidate_bodies = [state._maps['bodies'][k] for k in state.body_order if
                        state._maps['bodies'][k].selector.kind == 'domain' or possible.intersection(state._maps['bodies'][k].selector.keys)]
                    local_vertices = cell.footprint.vertex_count + sum(state._maps['geometry'][k].vertex_count for k in possible)
                    # Only footprint routing is shared; depth, overlays and work
                    # accounting still run for every cell. Query-local, bounded,
                    # explicitly charged storage avoids shared mutable plan state.
                    if support_counts.get(gid, 0) > 1 and len(routing_cache) < 1024:
                        retained_rows.enter_context(budget.reserve(512+256*(len(possible)+len(candidate_provinces)+len(candidate_bodies)),
                                                                 category='precursor-cell-routing'))
                        routing_cache[gid] = (possible, candidate_provinces, candidate_bodies, local_vertices)
                else:
                    possible, candidate_provinces, candidate_bodies, local_vertices = route
                local_allowance = 4096*local_vertices + 4096*(len(candidate_bodies)+len(candidate_provinces)+1) + 131072
                with budget.reserve(local_allowance, category='precursor-cell-fragments'):
                    portions = []
                    remaining = cell.footprint
                    for p in candidate_provinces:
                        pieces, remaining = self._take(remaining, p.selector, possible, cancel, work, budget)
                        portions.extend((p, g) for g in pieces)
                    if remaining is not None and remaining.area_m2 > 0:
                        raise GeologyError('precursor provinces leave uncovered sample area')
                    accum = {}
                    def account(fragment, top, bottom, unit_code, province_code):
                        work[0] += 1
                        if work[0] > self.limits.max_work_items:
                            raise GeologyError('initial sampling work exceeds explicit policy')
                        u = state.units[unit_code]
                        if u.layer.porosity is None:
                            raise GeologyError('cannot invent solid/pore inventories for unknown porosity')
                        v = _volume(fragment, top, bottom)
                        mean = error = 0.
                        if include_temperature:
                            profile = state._maps['thermal'][u.thermal_profile_id]
                            radius = fragment.chart.sphere.radius_m if type(fragment) is SphericalGeometry else None
                            key = (u.thermal_profile_id, top, bottom, radius)
                            if key in thermal_cache:
                                mean, error, lower, upper = thermal_cache[key]
                            else:
                                lower, upper = _temperature_bounds(profile, top, bottom, case.time_s, budget)
                                mean, error = _profile_mean(profile, top, bottom, case.time_s, radius, self.limits, cancel)
                                if len(thermal_cache) < 1024:
                                    thermal_cache[key] = (mean, error, lower, upper)
                            if offset_field is not None:
                                if offset_field.unknown_reason is not None:
                                    raise GeologyError('initial temperature offset is unresolved')
                                # A positive mean alone cannot legitimise negative
                                # absolute temperatures hidden inside a mixed cell.
                                field_lower = (offset_field.constant_value if offset_field.prior is None
                                               else offset_field.prior.mean-offset_field.prior.amplitude)
                                field_upper = (offset_field.constant_value if offset_field.prior is None
                                               else offset_field.prior.mean+offset_field.prior.amplitude)
                                lower += field_lower; upper += field_upper
                                if lower < 0:
                                    raise GeologyError('cell temperature envelope permits sub-zero values; no physical mean is certified')
                                mean += offset_field.constant_value if offset_field.prior is None else _prior_mean(offset_field.prior, fragment, top, bottom, cancel)
                            if mean < 0 or not math.isfinite(mean):
                                raise GeologyError('invalid initial mean temperature')
                            validity[cell_index] &= self._check_unit_temperature(unit_code, lower, upper)
                        key = (unit_code, province_code)
                        if key not in accum:
                            if len(accum)+len(rows) >= self.limits.max_rows:
                                raise GeologyError('unit inventory exceeds sparse-row envelope')
                            accum[key] = _CompensatedTriple()
                        accum[key].add(v, v*mean, v*error)
                    for p, footprint in portions:
                        column = case.column(p.column_id)
                        a, b = cell.top_depth_m, cell.bottom_depth_m
                        cuts = sorted({a, b, *(z for z in self._column_edges[column.column_id] if a < z < b),
                            *(z for body in candidate_bodies for z in (body.top_depth_m, body.bottom_depth_m) if a < z < b)})
                        for top, bottom in zip(cuts, cuts[1:]):
                            _check_cancel(cancel)
                            rest = footprint
                            for body in candidate_bodies:
                                # Cuts include every body boundary, so comparing
                                # band endpoints avoids midpoint rounding at thin layers.
                                if body.top_depth_m <= top and bottom <= body.bottom_depth_m:
                                    pieces, rest = self._take(rest, body.selector, possible, cancel, work, budget)
                                    for fragment in pieces:
                                        account(fragment, top, bottom, self._body_units[body.body_id], -1)
                            if rest is not None and rest.area_m2 > 0:
                                edges = self._column_edges[column.column_id]
                                j = bisect_right(edges, top)-1
                                if j < 0 or j >= len(column.layers) or bottom > edges[j+1]:
                                    raise GeologyError('cell extends below supplied column/mantle-body support')
                                account(rest, top, bottom, self._column_units[column.column_id][j], self._province_codes[p.province_id])
                    # Reserve retained sparse records BEFORE building them. Capacity
                    # grows in small bounded blocks; it is not max_cells*all_materials.
                    new_phase_count = sum(len(state.units[u].layer.components)+(state.units[u].layer.porosity > 0) for u, _ in accum)
                    if _ledger is not None:
                        _ledger.charge(rows=len(accum)+new_phase_count)
                    needed = len(rows)+len(phase_rows)+len(accum)+new_phase_count
                    if needed > self.limits.max_rows:
                        raise GeologyError('phase inventory exceeds sparse-row envelope')
                    if needed > reserved_capacity:
                        additional = ((needed-reserved_capacity+255)//256)*256
                        retained_rows.enter_context(budget.reserve(1024*additional, category='precursor-inventory-retained'))
                        reserved_capacity += additional
                    cell_volumes = []; cell_temperatures = []; cell_errors = []
                    for (unit_code, province_code), acc in sorted(accum.items()):
                        v, temperature_integral, error_integral = acc.values
                        u = state.units[unit_code]; phi = u.layer.porosity
                        matrix = v*(1-phi); pores = v*phi
                        grain = all(state._maps['bases'][state._maps['cohorts'][c.cohort_id].material_id].basis == 'grain' for c in u.layer.components)
                        row_index = len(rows)
                        rows.append((cell_index, unit_code, province_code, v, matrix, pores, matrix if grain else 0., grain))
                        for component in u.layer.components:
                            cohort = state._maps['cohorts'][component.cohort_id]
                            volume = matrix*component.solid_volume_fraction
                            mass = reference_mass(cohort.material_id, volume)
                            phase_rows.append((row_index, self._cohort_codes[cohort.cohort_id], self._material_codes[cohort.material_id], 0, volume, mass))
                        if phi > 0:
                            mid = u.fluid_material_id
                            mass = reference_mass(mid, pores)
                            phase_rows.append((row_index, -1, self._material_codes[mid], 1, pores, mass))
                        cell_volumes.append(v); cell_temperatures.append(temperature_integral); cell_errors.append(error_integral)
                    offsets.append(len(rows))
                    total = math.fsum(cell_volumes)
                    totals[cell_index] = total; residual[cell_index] = total-expected[cell_index]
                    if not math.isfinite(total) or abs(residual[cell_index]) > self.limits.inventory_relative*expected[cell_index]:
                        raise GeologyError('initial inventory coverage residual exceeds policy; no renormalisation')
                    if include_temperature:
                        # Divide by the actual accounted volume; report geometric
                        # coverage residual separately, never alter phase volumes.
                        tv[cell_index] = math.fsum(cell_temperatures)/total
                        te[cell_index] = math.fsum(cell_errors)/total
                    for j, name in enumerate(fields):
                        f = state._maps['fields'][name]
                        if f.unknown_reason is None:
                            fv[cell_index, j] = f.constant_value if f.prior is None else _prior_mean(f.prior, cell.footprint, cell.top_depth_m, cell.bottom_depth_m, cancel)
                            fk[cell_index, j] = True
            arrays = dict(cell_volume_m3=expected, accounted_volume_m3=totals, coverage_residual_m3=residual,
                cell_offsets=np.asarray(offsets, dtype=np.int64), temperature_k=tv, temperature_known=tk,
                temperature_quadrature_error_k=te, field_values=fv, field_known=fk,
                material_temperature_validity_known=validity)
            # Explicit integer/float arrays preserve large IDs and avoid the silent
            # int->float->int route of a heterogeneous matrix conversion.
            for j, name, dtype in ((0, 'row_cell', 'i8'), (1, 'unit_code', 'i4'), (2, 'province_code', 'i4'),
                                  (3, 'bulk_volume_m3', 'f8'), (4, 'matrix_volume_m3', 'f8'),
                                  (5, 'explicit_pore_volume_m3', 'f8'), (6, 'solid_volume_m3', 'f8'),
                                  (7, 'solid_volume_known', '?')):
                arrays[name] = np.asarray([r[j] for r in rows], dtype=dtype)
            for j, name, dtype in ((0, 'phase_row', 'i8'), (1, 'phase_cohort_code', 'i4'), (2, 'phase_material_code', 'i4'),
                                  (3, 'phase_kind', 'i1'), (4, 'phase_volume_m3', 'f8'), (5, 'reference_mass_kg', 'f8')):
                arrays[name] = np.asarray([r[j] for r in phase_rows], dtype=dtype)
            # The established layer-fraction tolerance permits tiny declared
            # deficits/excesses. Keep those fractions and expose their residual;
            # never renormalise phase inventories to manufacture conservation.
            phase_sum = np.zeros(len(rows), dtype=np.float64)
            np.add.at(phase_sum, arrays['phase_row'], arrays['phase_volume_m3'])
            arrays['phase_volume_residual_m3'] = phase_sum-arrays['bulk_volume_m3']
            arrays['reference_mass_known'] = np.full(len(phase_rows), reference_t is not None, dtype=bool)
            for i, (gid, g) in enumerate(sorted(unique_supports.items())):
                arrays['support_'+str(i)] = np.frombuffer(g.wkb if type(g) is PlanarGeometry else g._projected.wkb, dtype='u1')
            supports = {gid: {'array': 'support_'+str(i), 'geometry': g.descriptor()} for i, (gid, g) in enumerate(sorted(unique_supports.items()))}
            return InitialSamples(state, 'cells', {'plan_id': self.identity, 'requested_fields': fields,
                'frame_id': frame_id, 'epoch_id': epoch_id, 'time_s': case.time_s, 'depth_reference_id': depth_reference_id,
                'cells': [c.descriptor() for c in cells], 'supports': supports,
                'cohort_ids': self._cohort_ids, 'material_ids': self._material_ids,
                'reference_mass_temperature_k': reference_t, 'reference_mass_is_in_situ_mass': False,
                'reference_mass_conditions': 'source-specific reference conditions; no common pressure inferred',
                'overlapping_queries_allowed': allow_overlapping_queries,
                'temperature_semantics': 'volume-weighted initial mean, not heat/energy inventory',
                'material_temperature_validity': 'whole-fragment envelope in declared ranges; unknown ranges masked; not constitutive-law approval',
                'solid_semantics': 'known only for grain-matrix rows; bulk-reference intrinsic pores unresolved',
                'weak_zones': 'point membership supported; no fabricated averaged damage',
                'overlay_work_items': work[0]}, arrays)


class _CompensatedTriple:
    """Bounded streaming accumulation; no list of every intersection fragment."""
    __slots__ = ('_sum', '_correction')
    def __init__(self):
        self._sum = [0., 0., 0.]; self._correction = [0., 0., 0.]
    def add(self, *values):
        for i, x in enumerate(values):
            if not math.isfinite(x):
                raise GeologyError('extensive initial inventory overflow')
            total = self._sum[i]+x
            self._correction[i] += ((self._sum[i]-total)+x if abs(self._sum[i]) >= abs(x) else (x-total)+self._sum[i])
            self._sum[i] = total
    @property
    def values(self):
        return tuple(a+b for a, b in zip(self._sum, self._correction))


def _cap(geometry):
    c = np.asarray(geometry.chart.centre)
    directions = geometry.chart._unproject(shapely.get_coordinates(geometry._projected._geom))
    cosine = float(np.min(directions@c))
    # The chart centre's cap below a hemisphere is geodesically convex. It
    # contains every edge and the areal interior, not only the listed vertices.
    return c, math.acos(max(-1., min(1., cosine)))+128*np.finfo(float).eps


def _provably_disjoint(a, b):
    if type(a) is PlanarGeometry:
        aa, bb = a.bounds, b.bounds
        return aa[2] < bb[0] or bb[2] < aa[0] or aa[3] < bb[1] or bb[3] < aa[1]
    ca, ra = _cap(a); cb, rb = _cap(b)
    angle = math.atan2(float(np.linalg.norm(np.cross(ca, cb))), float(np.dot(ca, cb)))
    return angle > ra+rb+128*np.finfo(float).eps


def _check_cell_overlaps(cells, geometry_limits, limits, budget, cancel, *, diagnostics=None):
    """Global request validation, using conservative spherical broad-phase bounds.

    Repeated footprints share one cap. Their depth intervals are swept in order,
    not compared quadratically. Between two footprint groups, one positive-depth
    intersection is sufficient to require the existing exact geometric predicate.
    No worker boundary can hide an overlap from this complete-request check.
    """
    if type(cells[0].footprint) is PlanarGeometry:
        return _check_cell_overlaps_reference(cells, geometry_limits, limits, budget, cancel)
    with budget.reserve(256*len(cells)+16384, category='spherical-overlap-groups'):
        unique = {}; groups = []
        for i, cell in enumerate(cells):
            _check_cancel(cancel)
            key = cell.footprint.geometry_id
            if key not in unique:
                unique[key] = len(groups); groups.append([])
            groups[unique[key]].append(i)
        # All cells have positive area and thickness. An overlap within one
        # identical-footprint group is already a proof of double-counted volume.
        for group in groups:
            group.sort(key=lambda i: (cells[i].top_depth_m, cells[i].bottom_depth_m, i))
            for ia, ib in zip(group, group[1:]):
                _check_cancel(cancel)
                if cells[ia].bottom_depth_m > cells[ib].top_depth_m:
                    raise GeologyError('sampling cells overlap in positive volume; their total would double-count material')
        footprints = tuple(cells[group[0]].footprint for group in groups)
        work = 0
        with SphericalCandidateIndex(footprints, budget=budget, cancel=cancel) as index:
            if diagnostics is not None:
                diagnostics['cap_builds'] = len(footprints)
                diagnostics['possible_pairs'] = len(cells)*(len(cells)-1)//2
            for gi, group in enumerate(groups):
                hits = index.query(index=gi, budget=budget, cancel=cancel, diagnostics=diagnostics)
                for gj in hits:
                    gj = int(gj)
                    if gj <= gi: continue
                    other = groups[gj]; ai = bi = 0; vertical_overlap = False
                    while ai < len(group) and bi < len(other):
                        _check_cancel(cancel)
                        work += 1
                        if work > limits.max_work_items:
                            raise GeologyError('overlap verification exceeds explicit work envelope')
                        a, b = cells[group[ai]], cells[other[bi]]
                        if max(a.top_depth_m, b.top_depth_m) < min(a.bottom_depth_m, b.bottom_depth_m):
                            vertical_overlap = True; break
                        if a.bottom_depth_m <= b.bottom_depth_m: ai += 1
                        else: bi += 1
                    if not vertical_overlap: continue
                    if diagnostics is not None:
                        diagnostics['exact_overlays'] = diagnostics.get('exact_overlays', 0)+1
                    try:
                        g = footprints[gi].overlay(footprints[gj], 'intersection', limits=geometry_limits,
                                                   budget=budget, cancel=cancel)
                    except GeometryError as exc:
                        raise GeologyError('cell disjointness cannot be certified in compatible conditioned charts; '
                                           'use compatible explicit patches or explicitly non-additive overlapping queries') from exc
                    if g.area_m2 > 0:
                        raise GeologyError('sampling cells overlap in positive volume; their total would double-count material')
            if diagnostics is not None:
                diagnostics['depth_interval_checks'] = work


def _check_cell_overlaps_reference(cells, geometry_limits, limits, budget, cancel):
    """Refuse positive-volume overlap by default; shared faces are valid."""
    planar = type(cells[0].footprint) is PlanarGeometry
    pairs = 0
    tree = STRtree([c.footprint._geom for c in cells]) if planar else None
    for i, a in enumerate(cells):
        _check_cancel(cancel)
        candidates = tree.query(a.footprint._geom) if tree is not None else range(i+1, len(cells))
        for jj in candidates:
            j = int(jj)
            if j <= i:
                continue
            b = cells[j]
            if max(a.top_depth_m, b.top_depth_m) >= min(a.bottom_depth_m, b.bottom_depth_m):
                continue
            pairs += 1
            if pairs > limits.max_work_items:
                raise GeologyError('overlap verification exceeds explicit work envelope')
            if _provably_disjoint(a.footprint, b.footprint):
                continue
            try:
                g = a.footprint.overlay(b.footprint, 'intersection', limits=geometry_limits, budget=budget, cancel=cancel)
            except GeometryError as exc:
                raise GeologyError('cell disjointness cannot be certified in compatible conditioned charts; '
                                   'use compatible explicit patches or explicitly non-additive overlapping queries') from exc
            if g.area_m2 > 0:
                raise GeologyError('sampling cells overlap in positive volume; their total would double-count material')


def save_initial_samples(samples, store, *, budget=None, cancel=None):
    """Persist sampled arrays, actual support geometry and precursor in one snapshot."""
    from .storage import ArrayStore
    from .precursor import _precursor_snapshot
    if type(samples) is not InitialSamples or not isinstance(store, ArrayStore):
        raise GeologyError('typed initial samples and ArrayStore required')
    policy = store._budget if budget is None else budget
    _check_cancel(cancel)
    with select_budget(policy).reserve(4*samples.state.retained_bytes_estimate+3*samples.nbytes+65536, category='initial-samples-save'):
        sm, sa = _precursor_snapshot(samples.state)
        arrays = {'state__'+k: v for k, v in sa.items()}
        arrays.update({'result__'+k: samples.array(k) for k in samples._buffers})
        arrays['result_definition'] = np.frombuffer(samples._metadata, dtype='u1')
        metadata = {'schema': 'atlas.initial-samples-snapshot.v1', 'sample_id': samples.sample_id, 'state': sm}
        return store.put(samples.sample_id, arrays, metadata, budget=policy, cancel=cancel)


def load_initial_samples(store, sample_id, *, budget=None, cancel=None):
    """Cold restoration verifies every definition/array and does not resample priors."""
    from .storage import ArrayStore
    from .geological_case import _sha
    from .precursor import restore_precursor_state
    if not isinstance(store, ArrayStore):
        raise GeologyError('ArrayStore required')
    _sha(sample_id); _check_cancel(cancel)
    policy = store._budget if budget is None else budget
    arrays = store.get(sample_id, budget=policy)
    if arrays is None:
        return None
    metadata = store.metadata(sample_id)
    if type(metadata) is not dict or set(metadata) != {'schema', 'sample_id', 'state'} or metadata['schema'] != 'atlas.initial-samples-snapshot.v1' or metadata['sample_id'] != sample_id:
        raise GeologyError('invalid stored initial-sample metadata')
    if 'result_definition' not in arrays:
        raise GeologyError('sample definition is missing')
    definition = arrays['result_definition']
    if definition.dtype != np.dtype('u1') or definition.ndim != 1 or definition.nbytes > 64*1024**2:
        raise GeologyError('invalid saved sample-definition bytes')
    raw = definition.tobytes()
    if hashlib.sha256(raw).hexdigest() != sample_id:
        raise GeologyError('sample definition identity mismatch')
    try:
        d = json.loads(raw)
        if d.get('schema') != 'atlas.initial-samples.v1' or _json(d) != raw:
            raise GeologyError('invalid canonical sample definition')
        with select_budget(policy).reserve(8*len(raw)+3*sum(v.nbytes for v in arrays.values())+65536, category='initial-samples-restore'):
            state = restore_precursor_state(metadata['state'], {k[7:]: v for k, v in arrays.items() if k.startswith('state__')},
                                            d['state_id'], budget=policy, cancel=cancel)
            payload = {k[8:]: v for k, v in arrays.items() if k.startswith('result__')}
            if set(payload) != set(d['arrays']) or any(k != 'result_definition' and not k.startswith(('state__', 'result__')) for k in arrays):
                raise GeologyError('sample array inventory differs from its definition')
            for k, a in payload.items():
                desc = d['arrays'][k]
                if desc != {'dtype': a.dtype.str, 'shape': list(a.shape), 'sha256': hashlib.sha256(a.tobytes()).hexdigest()}:
                    raise GeologyError('sample array identity mismatch')
            result = InitialSamples(state, d['kind'], d, payload)
            if result.sample_id != sample_id or result._metadata != raw:
                raise GeologyError('restored sample identity differs')
            _check_cancel(cancel)
            return result
    except (TypeError, KeyError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, GeologyError):
            raise
        raise GeologyError('malformed saved initial samples') from exc
