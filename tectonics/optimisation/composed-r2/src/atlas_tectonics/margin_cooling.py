"""W06 inherited, stationary continental-column conduction and local support.

The actual W01 initial field is retained. A compatible piecewise-linear profile
evolves about its steady linear field, using exact sine coefficients at mature
times and the equivalent odd-periodic heat-kernel images at young times. Cell
and cumulative boundary-heat integrals are analytic; narrow smooth cell
integrals use bounded eight-point Gaussian integration to avoid cancellation.
No cooling age is inferred, no hot birth is imposed, and no mass is created.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import math

import numpy as np

from ._validation import TectonicsError, scalar, text, frozen, input_shape, read_array
from .constitutive import BoussinesqMaterial
from .materials import _json
from .parameters import PlateCoolingParameters, identity
from .precursor import PrecursorState, InitialConditionState
from .regional import _cancelled
from .resources import select_budget, reserve_budgets
from .reuse import ExecutionContext
from .spreading import _within_budget
from .thermal_support import ThermalSupportParameters, _owner, _temperature


_IMAGE_LIMIT = 1. / 16.
_TAIL_K = 1e-10
_MAX_MODES = 256
_MAX_IMAGES = 16
_MAX_KNOTS = 4096
_MAX_CELLS = 65536
_MAX_IMAGE_INTERACTIONS = 1_000_000
_GAUSS_X = (-.9602898564975363, -.7966664774136267, -.5255324099163290,
            -.1834346424956498, .1834346424956498, .5255324099163290,
            .7966664774136267, .9602898564975363)
_GAUSS_W = (.1012285362903763, .2223810344533745, .3137066458778873,
            .3626837833783620, .3626837833783620, .3137066458778873,
            .2223810344533745, .1012285362903763)


def _tail_integral(r, tau):
    """Integral from |r| to infinity of heat-smoothed ReLU minus ReLU.

    K=tau*((1/2+q*q)*erfc(q)-q*exp(-q*q)/sqrt(pi)), q=|r|/(2sqrt(tau)).
    It also equals half the time integral of erfc(q). This shared primitive
    makes depth energy and top/base flux use exactly the same PDE solution.
    """
    q = abs(r)/(2*math.sqrt(tau))
    if q > 27.:
        return 0.
    return tau*((.5+q*q)*math.erfc(q)-q*math.exp(-q*q)/math.sqrt(math.pi))


def _smoothed_corner(r, tau):
    q = abs(r)/(2*math.sqrt(tau))
    if q > 27.:
        return 0.
    return math.sqrt(tau/math.pi)*(math.exp(-q*q)-math.sqrt(math.pi)*q*math.erfc(q))


def _corner_mean(left, right, tau, *, width=None):
    """True interval mean of the smoothed corner, stable for tiny intervals."""
    width = right-left if width is None else width
    if left < 0 < right:
        # Split the known derivative kink before the smooth Gaussian branch.
        return ((-left)*_corner_mean(left, 0., tau)+right*_corner_mean(0., right, tau))/width
    if width <= math.sqrt(tau)/16.:
        middle = left+.5*width
        return .5*math.fsum(w*_smoothed_corner(middle+.5*width*x, tau)
                           for x, w in zip(_GAUSS_X, _GAUSS_W))
    if left >= 0:
        return (_tail_integral(left, tau)-_tail_integral(right, tau))/width
    return (_tail_integral(right, tau)-_tail_integral(left, tau))/width


def _initial_means(edges, knots, temperatures):
    """Integrate each original linear segment, without sampled-state evolution."""
    out = np.zeros(len(edges)-1)
    for i, (left, right) in enumerate(zip(edges[:-1], edges[1:])):
        first = max(0, int(np.searchsorted(knots, left, side='right'))-1)
        last = min(len(knots)-2, int(np.searchsorted(knots, right, side='left')))
        pieces = []
        for j in range(first, last+1):
            lo, hi = max(left, knots[j]), min(right, knots[j+1])
            if hi <= lo:
                continue
            fraction = ((lo-knots[j])+.5*(hi-lo))/(knots[j+1]-knots[j])
            mean = temperatures[j]+fraction*(temperatures[j+1]-temperatures[j])
            pieces.append((hi-lo)/(right-left)*mean)
        out[i] = math.fsum(pieces)
    return out


def _moments(knots, perturbation):
    total, first = [], []
    for a, b, va, vb in zip(knots[:-1], knots[1:], perturbation[:-1], perturbation[1:]):
        h = b-a
        mean = (va+vb)*.5
        total.append(h*mean)
        first.append(h*(a*mean+h*(va+2*vb)/6.))
    moment = math.fsum(first)
    return math.fsum(total)-moment, moment


def _spectral_tail(amplitude, modes, tau):
    # |b_n| <= amplitude/n^2; sum(n>N) n^-2 <= 1/N.
    return amplitude*math.exp(-math.pi**2*tau*modes*modes)/modes


@dataclass(frozen=True, slots=True)
class MarginThermalResult:
    source_state_id: str
    plan_id: str
    state_id: str
    execution_id: str
    epoch_id: str
    source_time_s: float
    time_s: float
    elapsed_s: float
    depth_edges_m: np.ndarray
    mean_temperature_k: np.ndarray
    initial_reference_temperature_k: np.ndarray
    temperature_change_k: np.ndarray
    outward_heat_j_m2: np.ndarray
    temperature_truncation_bound_k: float
    heat_truncation_bound_j_m2: float
    source_column: object
    source_profile: object
    material_definitions: tuple
    cooling_history: object
    thinning_source_id: str
    geometry_reference_id: str
    source_state: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class MarginSupportResult:
    thermal: MarginThermalResult
    support_id: str
    thermal_owner: str
    sheet_anomaly_kg_m2: float
    downward_load_pa: float
    downward_displacement_m: float
    initial_depth_m: float
    water_depth_m: float
    area_m2: float
    reference_water_m3: float
    water_change_m3: float
    represented_water_m3: float
    water_remaining_m3: float
    water_source_id: str
    reference_material_mass_kg: tuple
    trajectory_depth_bounds_m: tuple


@dataclass(frozen=True, slots=True, init=False)
class PreparedMarginCooling:
    """Source-bound constant-property evolution of one actual inherited column.

    Source conductivity and rho*cp must agree with the selected plate. Unknown
    porosity, mixed layers, bodies and temperature-offset fields refuse in this
    first stationary route. The named thinning source is retained evidence, not
    a newly solved thinning event or an inferred pre-thinning geometry.
    """
    initial_state: object
    source_column: object
    source_profile: object
    material_definitions: tuple
    cooling_history: object
    plate: PlateCoolingParameters
    thinning_source_id: str
    geometry_reference_id: str
    execution_id: str
    plan_id: str
    _knots: object = field(repr=False, compare=False)
    _temperatures: object = field(repr=False, compare=False)
    _jumps: object = field(repr=False, compare=False)
    _coefficients: object = field(repr=False, compare=False)
    _moments: tuple = field(repr=False, compare=False)
    _slopes: tuple = field(repr=False, compare=False)
    _amplitude: float = field(repr=False, compare=False)
    _context: object = field(repr=False, compare=False)
    _owns_context: bool = field(repr=False, compare=False)
    _budget: object = field(repr=False, compare=False)
    _lease: object = field(repr=False, compare=False)
    _closed: bool = field(repr=False, compare=False)

    def __init__(self, initial_state, column_id, plate, *, thinning_source_id,
                 geometry_reference_id, context=None, budget=None, cancel=None):
        _cancelled(cancel)
        if type(initial_state) not in (PrecursorState, InitialConditionState):
            raise TectonicsError('source-bound W01 initial state required')
        if type(plate) is not PlateCoolingParameters:
            raise TectonicsError('explicit PlateCoolingParameters required')
        text(column_id, 'column ID'); text(thinning_source_id, 'thinning source')
        text(geometry_reference_id, 'geometry reference')
        case = initial_state.case
        columns = {c.column_id: c for c in case.columns}
        if column_id not in columns:
            raise TectonicsError('unknown inherited source column')
        column = columns[column_id]
        if column.crust_type not in ('continental', 'transitional'):
            raise TectonicsError('inherited continental or transitional column required')
        if thinning_source_id not in {s.source_id for s in case.sources}:
            raise TectonicsError('thinning source is absent from the original W01 sources')
        if geometry_reference_id not in (case.depth_reference_id, initial_state.sampling_domain.domain_id):
            raise TectonicsError('geometry reference must identify the actual source datum or domain')
        if (column.lithosphere_thickness_m != plate.thickness_m or
                column.layer_edges_m[-1] != plate.thickness_m):
            raise TectonicsError('source column and finite plate thickness must match exactly')
        if initial_state.bodies or any(f.role == 'temperature_offset' for f in initial_state.fields):
            raise TectonicsError('body overrides or temperature-offset fields need an explicit resolved column import')
        profile = initial_state._maps['thermal'][column.thermal_profile_id]
        if profile.mode not in ('tabulated', 'constant'):
            raise TectonicsError('unsupported inherited profile; only compatible tabulated or constant fields are supported')
        temperatures = profile.temperatures_k
        depths = profile.depths_m
        if profile.mode == 'constant':
            temperatures = temperatures*2
            depths = (0., plate.thickness_m)
        if (depths[-1] != plate.thickness_m or
                temperatures[0] != plate.thermal.surface_temperature_k or
                temperatures[-1] != plate.thermal.mantle_temperature_k):
            raise TectonicsError('inherited profile must exactly span L and match fixed Ts/Tb')
        if len(depths) > _MAX_KNOTS:
            raise TectonicsError('inherited profile exceeds bounded knot envelope')
        materials = []
        for layer in column.layers:
            if layer.porosity != 0. or len(layer.components) != 1 or layer.components[0].solid_volume_fraction != 1.:
                raise TectonicsError('this margin route requires nonporous single-component source layers')
            cohort = initial_state._maps['cohorts'][layer.components[0].cohort_id]
            material = initial_state._maps['materials'][cohort.material_id]
            if (material.material_class != 'solid' or material.density_kg_m3 is None or
                    material.specific_heat_j_kg_k is None or
                    material.conductivity_w_m_k != plate.conductivity_w_m_k or
                    material.heat_production_w_m3 != 0. or
                    not math.isclose(material.density_kg_m3*material.specific_heat_j_kg_k,
                                     plate.volumetric_heat_capacity_j_m3_k, rel_tol=2e-14)):
                raise TectonicsError('source material does not match homogeneous unheated conductive plate')
            if material.valid_temperature_k is not None and not (
                    material.valid_temperature_k[0] <= min(temperatures) <= max(temperatures) <= material.valid_temperature_k[1]):
                raise TectonicsError('full initial temperature field exceeds source material validity')
            materials.append(material)
        resource = select_budget(budget)
        lease = resource.reserve(initial_state.retained_bytes_estimate+512*len(depths)+65536,
                                 category='margin-prepared')
        lease.__enter__()
        owned, ctx = context is None, None
        try:
            ctx = ExecutionContext('reference') if owned else context
            if type(ctx) is not ExecutionContext or ctx.backend != 'reference':
                raise TectonicsError('reference ExecutionContext required for margin conduction')
            execution_id = ctx.identity
            knots = np.asarray(depths)/plate.thickness_m
            if np.any(np.diff(knots) <= 0):
                raise TectonicsError('normalised source knots are not numerically resolvable')
            values = np.asarray(temperatures)
            slopes = np.diff(values)/np.diff(knots)
            jumps = np.diff(slopes)
            amplitude = scalar(2*math.fsum(abs(v) for v in jumps)/math.pi**2,
                               'spectral coefficient bound', nonnegative=True)
            modes = 8
            while _spectral_tail(amplitude, modes, _IMAGE_LIMIT) > _TAIL_K:
                modes *= 2
                if modes > _MAX_MODES:
                    raise TectonicsError('inherited spectral error unresolved within finite mode cap')
            coefficients = np.zeros(modes)
            for n in range(1, modes+1):
                coefficients[n-1] = -2*math.fsum(float(d)*math.sin(n*math.pi*float(x))
                    for x, d in zip(knots[1:-1], jumps))/(n*math.pi)**2
            perturbation = values-(values[0]+(values[-1]-values[0])*knots)
            descriptor = dict(method='atlas.w06-inherited-margin.v1', source_state=initial_state.state_id,
                source_column=column_id, plate=identity(plate), thinning_source=thinning_source_id,
                geometry_reference=geometry_reference_id, execution=execution_id)
            captured = dict(initial_state=initial_state, source_column=column, source_profile=profile,
                material_definitions=tuple(materials), cooling_history=initial_state._maps['cooling'][profile.profile_id],
                plate=plate, thinning_source_id=thinning_source_id, geometry_reference_id=geometry_reference_id,
                execution_id=execution_id, plan_id=hashlib.sha256(_json(descriptor)).hexdigest(),
                _knots=frozen(knots), _temperatures=frozen(values), _jumps=frozen(jumps),
                _coefficients=frozen(coefficients), _moments=_moments(knots, perturbation),
                _slopes=(float(slopes[0]), float(slopes[-1])), _amplitude=amplitude,
                _context=ctx, _owns_context=owned, _budget=resource, _lease=lease, _closed=False)
            for key, value in captured.items():
                object.__setattr__(self, key, value)
            ctx.verify(); _cancelled(cancel)
        except BaseException:
            lease.__exit__(None, None, None)
            if owned and ctx is not None:
                ctx.close()
            raise

    def _check(self, budget, cancel):
        if self._closed:
            raise TectonicsError('margin preparation is closed')
        _cancelled(cancel); self._context.verify()
        resource = self._budget if budget is None else select_budget(budget)
        _within_budget(resource, self._budget)
        return resource

    def _images(self, edges, tau, cancel):
        total_jump = self._amplitude*math.pi**2/2
        images = 1
        while True:
            tail = 4*total_jump*math.exp(-images*images/tau)/(1-math.exp(-(2*images+1)/tau))
            temperature_bound = tail*math.sqrt(tau/math.pi)
            heat_bound = tail*tau
            if max(temperature_bound, heat_bound) <= _TAIL_K*min(1., tau):
                break
            images += 1
            if images > _MAX_IMAGES:
                raise TectonicsError('inherited image error unresolved within finite image cap')
        # Byte admission alone does not bound this scalar corner-by-cell work.
        # Refuse an oversized young-time request before looping; no knot/age
        # binning or reduction of the image accuracy is implied by this limit.
        interactions = (len(edges)-1)*int(np.count_nonzero(self._jumps))*2*(2*images+1)
        if interactions > _MAX_IMAGE_INTERACTIONS:
            raise TectonicsError('young inherited image interaction budget exceeded')
        sums = np.zeros(len(edges)+1)
        correction = np.zeros_like(sums)
        sums[-2:] = self._slopes[0]*tau, -self._slopes[1]*tau
        for knot, jump in zip(self._knots[1:-1], self._jumps):
            _cancelled(cancel)
            if jump == 0.:
                continue
            for m in range(-images, images+1):
                for centre, weight in ((knot+2*m, jump), (-knot+2*m, -jump)):
                    term = np.empty_like(sums)
                    for i, (left, right) in enumerate(zip(edges[:-1], edges[1:])):
                        term[i] = weight*_corner_mean(float(left-centre), float(right-centre), tau,
                                                    width=float(right-left))
                    for where, sign, index in ((0., -1., -2), (1., 1., -1)):
                        r = float(where-centre)
                        term[index] = sign*weight*math.copysign(_tail_integral(r, tau), r)
                    adjusted = term-correction
                    updated = sums+adjusted
                    correction = (updated-sums)-adjusted
                    sums = updated
        return sums[:-2], sums[-2:], temperature_bound, heat_bound

    def _spectral(self, edges, tau):
        ts, tb = self._temperatures[[0, -1]]
        means = ts+(tb-ts)*(edges[:-1]+.5*np.diff(edges))
        top, base = [(tb-ts)*tau, self._moments[0]], [-(tb-ts)*tau, self._moments[1]]
        for n, coefficient in enumerate(self._coefficients, 1):
            decayed = coefficient*math.exp(-n*n*math.pi**2*tau)
            # sinc is stable even when a requested depth cell is extremely thin.
            means += decayed*np.sin(n*math.pi*(edges[:-1]+.5*np.diff(edges)))*np.sinc(.5*n*np.diff(edges))
            top.append(-decayed/(n*math.pi))
            base.append(decayed*((-1.)**n)/(n*math.pi))
        tail = _spectral_tail(self._amplitude, len(self._coefficients), tau)
        return means, np.array([math.fsum(top), math.fsum(base)]), tail, tail/(math.pi*len(self._coefficients))

    def evaluate(self, *, time_s, epoch_id, depth_edges_m, budget=None, cancel=None):
        resource = self._check(budget, cancel)
        text(epoch_id, 'epoch')
        if epoch_id != self.initial_state.case.epoch_id:
            raise TectonicsError('margin epoch mismatch')
        end = scalar(time_s, 'margin time')
        start = self.initial_state.case.time_s
        elapsed = scalar(end-start, 'elapsed from inherited epoch', nonnegative=True)
        if start+elapsed != end:
            raise TectonicsError('clock cannot resolve inherited elapsed time')
        shape = input_shape(depth_edges_m)
        if len(shape) != 1 or not 2 <= shape[0] <= _MAX_CELLS+1:
            raise TectonicsError('bounded one-dimensional margin depth edges required')
        # Image corrections stream one source corner at a time, without a
        # dense cells-by-knots/image matrix or a growing output history.
        work = 512*(shape[0]+len(self._knots))+65536
        with reserve_budgets(work, resource, self._budget, category='margin-evaluation'):
            physical = read_array(depth_edges_m, 'margin depth edges', nonnegative=True)
            if (physical.shape != shape or physical[0] != 0. or physical[-1] != self.plate.thickness_m
                    or np.any(np.diff(physical) <= 0)):
                raise TectonicsError('depth edges must strictly increase and exactly span the inherited plate')
            edges = physical/self.plate.thickness_m
            if np.any(np.diff(edges) <= 0):
                raise TectonicsError('normalised depth cells are not numerically resolvable')
            initial = _initial_means(edges, self._knots, self._temperatures)
            tau = scalar((elapsed/self.plate.thickness_m)*(self.plate.thermal.diffusivity_m2_s/self.plate.thickness_m),
                         'dimensionless inherited time', nonnegative=True)
            if elapsed > 0 and tau == 0:
                raise TectonicsError('positive inherited time underflows')
            if elapsed == 0:
                means, change, heat, t_error, h_error = initial.copy(), np.zeros_like(initial), np.zeros(2), 0., 0.
            elif tau <= _IMAGE_LIMIT:
                change, heat, t_error, h_error = self._images(edges, tau, cancel)
                means = initial+change
            else:
                means, heat, t_error, h_error = self._spectral(edges, tau)
                change = means-initial
            heat_scale = scalar(self.plate.volumetric_heat_capacity_j_m3_k*self.plate.thickness_m,
                                'column heat scale', positive=True)
            heat = frozen(heat*heat_scale)
            arrays = tuple(frozen(a) for a in (physical, means, initial, change))
            state_id = hashlib.sha256(_json(dict(plan=self.plan_id, time_s=end, epoch=epoch_id))+
                                      b''.join(a.tobytes() for a in (*arrays, heat))).hexdigest()
            result = MarginThermalResult(self.initial_state.state_id, self.plan_id, state_id,
                self.execution_id, epoch_id, start, end, elapsed, *arrays, heat,
                t_error, scalar(h_error*heat_scale, 'heat truncation bound', nonnegative=True),
                self.source_column, self.source_profile, self.material_definitions, self.cooling_history,
                self.thinning_source_id, self.geometry_reference_id, self.initial_state)
        self._context.verify(); _cancelled(cancel)
        return result

    def support(self, *, time_s, epoch_id, materials, parameters, initial_depth_m,
                area_m2, water_stock_m3, water_source_id, budget=None, cancel=None):
        """One water-loaded isostatic response relative to the imported geometry.

        Stock is the complete available water before occupying this finite area,
        so reference water and all subsequent infill are both booked. Outputs
        are candidates, not a shared-reservoir commit. Emergence refuses.
        """
        self._check(budget, cancel); _owner(parameters)
        if (parameters.reference_id != self.geometry_reference_id or
                parameters.depth_reference_id != self.initial_state.case.depth_reference_id):
            raise TectonicsError('support reference must match inherited geometry and datum')
        if type(materials) is not dict or set(materials) != {m.material_id for m in self.material_definitions}:
            raise TectonicsError('exact source-material to Boussinesq mapping required')
        if parameters.fill_density_kg_m3 <= 0:
            raise TectonicsError('wet margin requires positive water density')
        for original in self.material_definitions:
            selected = materials[original.material_id]
            if (type(selected) is not BoussinesqMaterial or selected.name != original.material_id or
                    selected.source != original.source_id or selected.density_kg_m3 != original.density_kg_m3 or
                    selected.heat_capacity_j_kg_k != original.specific_heat_j_kg_k or
                    selected.conductivity_w_m_k != original.conductivity_w_m_k or
                    selected.expansion_per_k != original.thermal_expansion_per_k or
                    selected.reference_temperature_k != original.reference_temperature_k or
                    selected.internal_heating_w_m3 != original.heat_production_w_m3 or
                    selected.composition_density_contrast_kg_m3 != 0.):
                raise TectonicsError('Boussinesq material differs from original source material')
            # Maximum principle checks the full retained profile, not warm means.
            _temperature(self._temperatures, selected)
        depth = scalar(initial_depth_m, 'inherited reference water depth', positive=True)
        area = scalar(area_m2, 'finite inherited area', positive=True)
        stock = scalar(water_stock_m3, 'finite water stock', nonnegative=True)
        text(water_source_id, 'finite water source')
        reference = scalar(depth*area, 'reference margin water', nonnegative=True)
        if reference > stock:
            raise TectonicsError('finite margin water reservoir cannot fill inherited reference geometry')
        # Arbitrary nonuniform fields need not cool or subside monotonically.
        # The maximum principle bounds every point for the whole future, so
        # these conservative layer-weighted bounds certify the entire path,
        # including any unrequested intermediate water/deflection extremum.
        initial_means = _initial_means(np.asarray(self.source_column.layer_edges_m)/self.plate.thickness_m,
                                       self._knots, self._temperatures)
        tmin, tmax = min(self._temperatures), max(self._temperatures)
        sheet_bounds = tuple(math.fsum((float(initial)-extreme)*layer.bulk_thickness_m*
                                     m.density_kg_m3*m.thermal_expansion_per_k
            for initial, layer, m in zip(initial_means, self.source_column.layers, self.material_definitions))
                             for extreme in (tmax, tmin))
        displacement_bounds = tuple(s/parameters.restoring_density_contrast_kg_m3 for s in sheet_bounds)
        trajectory_depths = tuple(scalar(depth+s, 'bounded trajectory depth') for s in displacement_bounds)
        if (max(abs(s) for s in displacement_bounds)/self.plate.thickness_m > parameters.max_relative_deflection
                or trajectory_depths[0] <= 0 or trajectory_depths[1]*area > stock):
            raise TectonicsError('inherited trajectory water/wet/deflection validity is unproven within conservative bounds')
        result = self.evaluate(time_s=time_s, epoch_id=epoch_id,
            depth_edges_m=self.source_column.layer_edges_m, budget=budget, cancel=cancel)
        sheet = math.fsum(-float(delta)*layer.bulk_thickness_m*m.density_kg_m3*m.thermal_expansion_per_k
            for delta, layer, m in zip(result.temperature_change_k, self.source_column.layers, self.material_definitions))
        displacement = scalar(sheet/parameters.restoring_density_contrast_kg_m3, 'margin displacement')
        if abs(displacement)/self.plate.thickness_m > parameters.max_relative_deflection:
            raise TectonicsError('margin support exceeds small-deflection validity envelope')
        current_depth = scalar(depth+displacement, 'current wet margin depth', positive=True)
        water = scalar(current_depth*area, 'represented margin water', nonnegative=True)
        if water > stock:
            raise TectonicsError('finite margin water reservoir exhausted')
        masses = tuple((layer.layer_id, m.material_id, scalar(area*layer.bulk_thickness_m*m.density_kg_m3,
                       'unchanged reference layer mass', positive=True))
                       for layer, m in zip(self.source_column.layers, self.material_definitions))
        support_id = hashlib.sha256(_json(dict(thermal=result.state_id, parameters=asdict(parameters),
            materials={key: asdict(value) for key, value in materials.items()}, depth=depth, area=area,
            water_stock=stock, water_source=water_source_id))).hexdigest()
        self._context.verify(); _cancelled(cancel)
        return MarginSupportResult(result, support_id, 'column-isostasy', scalar(sheet, 'thermal sheet'),
            scalar(sheet*parameters.gravity_m_s2, 'thermal pressure'), displacement, depth, current_depth,
            area, reference, scalar(displacement*area, 'margin water change'), water, stock-water,
            water_source_id, masses, trajectory_depths)

    def close(self):
        if not self._closed:
            object.__setattr__(self, '_closed', True)
            try:
                if self._owns_context:
                    self._context.close()
            finally:
                self._lease.__exit__(None, None, None)

    def __enter__(self):
        self._check(None, None)
        return self

    def __exit__(self, *args):
        self.close()
