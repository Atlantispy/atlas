"""W07 finite-volume heat and exact rectangular material translation.

SPDX-License-Identifier: AGPL-3.0-only
Cell temperatures are volume means; physical x is right and z is up. The mesh
may translate uniformly, never distort. Heat flux uses physical minus mesh
velocity. Material rectangles move at physical velocity only. Constant heat
capacity/conductivity, prescribed incompressible MAC motion and finite material
stocks are explicit support restrictions, not a general free-surface solver.

The heat adapter retains R4.2's multidimensional MC interior reconstruction and
SSP-RK2 formulation, adding open faces and conservative explicit diffusion.
See https://www.clawpack.org/pyclaw/solvers.html and ASPECT 3.0.0's
user/methods/freesurface/arbitrary-le-implementation.html for method context.
The old closed-wall diffusion operator and equal-extent W02 remap cannot be
reused on an open moving domain without violating their contracts.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
import math

import numpy as np

from ._validation import TectonicsError, scalar, text, read_array, frozen, input_shape
from .resources import select_budget, WorkBudget
from .thermochemical import _reference_transfers


_SIDES = ('left', 'right', 'bottom', 'top')
_SIGNS = (-1., 1., -1., 1.)
_MAX_MATERIAL_REGIONS = 256


def _cancel(cancel):
    if cancel is None:
        return
    if callable(cancel):
        stopped = cancel()
    elif callable(getattr(cancel, 'is_set', None)):
        stopped = cancel.is_set()
    else:
        raise TectonicsError('cancellation must be a callable or an Event')
    if stopped:
        raise CancelledError('regional transport cancelled')


def _pair(value, name):
    if input_shape(value, name) != (2,):
        raise TectonicsError(name + ': uniform two-component translation required; distorted grids unsupported')
    return tuple(scalar(v, name) for v in value)


def _sum(value):
    return math.fsum(np.asarray(value).flat)


@dataclass(frozen=True, slots=True)
class RectangularTransportGrid:
    """Frozen W07 rectangular support: 2 to 64 cells along each axis."""
    nx: int
    nz: int
    width_m: float
    height_m: float
    frame_id: str
    origin_m: tuple[float, float] = (0., 0.)
    strike_width_m: float = 1.

    def __post_init__(self):
        for name in ('nx', 'nz'):
            if type(getattr(self, name)) is not int or not 2 <= getattr(self, name) <= 64:
                raise TectonicsError(name + ': frozen W07 support is 2 to 64 cells per axis')
        for name in ('width_m', 'height_m', 'strike_width_m'):
            object.__setattr__(self, name, scalar(getattr(self, name), name, positive=True))
        object.__setattr__(self, 'frame_id', text(self.frame_id, 'frame_id'))
        object.__setattr__(self, 'origin_m', _pair(self.origin_m, 'origin_m'))
        # Constant-size geometry preflight precedes the bounded edge allocation.
        for n, spacing, start in ((self.nx, self.dx, self.origin_m[0]),
                                  (self.nz, self.dz, self.origin_m[1])):
            edge = np.asarray((start, start+spacing, start+(n-1)*spacing, start+n*spacing))
            if (spacing <= 0. or not np.isfinite(edge).all() or edge[1] <= edge[0] or
                    edge[3] <= edge[2] or max(abs((edge[1]-edge[0])/spacing-1.),
                    abs((edge[3]-edge[2])/spacing-1.)) > 1e-12 or
                    not math.isfinite(self.volume) or self.volume <= 0.):
                raise TectonicsError('unresolvable rectangular geometry; choose a suitable coordinate frame')

    @property
    def dx(self):
        return self.width_m / self.nx

    @property
    def dz(self):
        return self.height_m / self.nz

    @property
    def volume(self):
        return self.dx * self.dz * self.strike_width_m

    def edges(self, origin_m=None):
        origin = self.origin_m if origin_m is None else _pair(origin_m, 'origin_m')
        result = []
        for n, spacing, start in ((self.nx, self.dx, origin[0]), (self.nz, self.dz, origin[1])):
            # Refuse loss of the prescribed uniform geometry at large offsets.
            edge = start + np.arange(n + 1) * spacing
            if (not np.isfinite(edge).all() or np.any(np.diff(edge) <= 0.) or
                    np.max(np.abs(np.diff(edge) / spacing - 1.)) > 1e-12):
                raise TectonicsError('unresolvable rectangular geometry; choose a suitable coordinate frame')
            result.append(edge)
        return tuple(result)

    def moved_origin(self, velocity, duration):
        displacement = tuple(a * duration for a in velocity)
        origin = tuple(a + d for a, d in zip(self.origin_m, displacement))
        if any(d != 0. and b == a for a, b, d in zip(self.origin_m, origin, displacement)):
            raise TectonicsError('unresolvable prescribed mesh translation')
        self.edges(origin)
        return origin


@dataclass(frozen=True, slots=True)
class HeatBoundary:
    """All values are scalars, side arrays, or callables (x_m,z_m,time_s).

    Inflow temperature is required only on inward relative faces. Diffusion is
    either a face temperature (K), or outward conductive heat flux (W/m2).
    Specified Neumann fluxes and sources can change extrema: those cases have no
    unconditional homogeneous maximum principle. No post-update clipping occurs.
    """
    inflow_temperature_k: object
    diffusion_kind: str
    diffusion_value: object

    def __post_init__(self):
        if self.diffusion_kind not in ('temperature', 'outward_flux'):
            raise TectonicsError('diffusion_kind must be temperature or outward_flux')
        if self.diffusion_value is None:
            raise TectonicsError('every side needs explicit diffusive boundary data')


def _sample(value, x, z, time, name):
    if callable(value):
        value = value(x, z, time)
    shape = input_shape(value, name)
    if shape not in ((), x.shape):
        raise TectonicsError(name + ': wrong spatial support')
    if shape == ():
        return np.full(x.shape, scalar(value, name))
    return read_array(value, name)


@dataclass(frozen=True, slots=True, init=False)
class PreparedHeatTransport:
    """Reusable geometry and constant thermal coefficients; no result cache.

    A prepared plan has no stale velocity/boundary state. Each stage samples
    current boundary/source values at its physical coordinates and time.
    Array MAC velocity is a declared frozen-in-time interval field; a changing
    velocity requires a callable (time_s, origin_m) returning (u,w).
    """
    grid: RectangularTransportGrid
    conductivity: float
    capacity: float
    kappa: float
    budget: WorkBudget
    work_bytes: int

    def __init__(self, grid, conductivity_w_m_k, volumetric_heat_capacity_j_m3_k, *, budget=None):
        if type(grid) is not RectangularTransportGrid:
            raise TectonicsError('RectangularTransportGrid required')
        object.__setattr__(self, 'grid', grid)
        object.__setattr__(self, 'conductivity', scalar(conductivity_w_m_k, 'conductivity', nonnegative=True))
        object.__setattr__(self, 'capacity', scalar(volumetric_heat_capacity_j_m3_k, 'heat capacity', positive=True))
        object.__setattr__(self, 'kappa', self.conductivity / self.capacity)
        if not math.isfinite(self.kappa):
            raise TectonicsError('thermal diffusivity outside finite range')
        object.__setattr__(self, 'budget', WorkBudget(128*1024**2, parent=select_budget(budget)))
        object.__setattr__(self, 'work_bytes', 640*grid.nx*grid.nz + 512*(grid.nx+grid.nz) + 16384)
        with self.budget.reserve(self.work_bytes, category='w07-heat-admission'):
            pass

    def _coordinates(self, origin):
        g = self.grid
        x, z = g.edges(origin)
        xc, zc = x[:-1] + .5*g.dx, z[:-1] + .5*g.dz
        return ((np.full(g.nz, x[0]), zc), (np.full(g.nz, x[-1]), zc),
                (xc, np.full(g.nx, z[0])), (xc, np.full(g.nx, z[-1])))

    def _velocity(self, u, w, mesh, time, origin):
        g = self.grid
        if callable(u):
            if w is not None:
                raise TectonicsError('velocity callback returns both components; w must be None')
            u, w = u(time, origin)
        if input_shape(u, 'u') != (g.nz, g.nx+1) or input_shape(w, 'w') != (g.nz+1, g.nx):
            raise TectonicsError('physical velocities require full rectangular MAC face support')
        u, w = read_array(u, 'u'), read_array(w, 'w')
        scale = max(float(np.max(np.abs(u))) / g.dx, float(np.max(np.abs(w))) / g.dz,
                    np.finfo(float).tiny)
        div = np.diff(u, axis=1)/g.dx + np.diff(w, axis=0)/g.dz
        if float(np.max(np.abs(div))) > 1e-10 * scale:
            raise TectonicsError('heat transport requires divergence-free physical MAC velocity')
        return u-mesh[0], w-mesh[1]

    def _limit(self, u, w, boundaries):
        g = self.grid
        outgoing = (np.maximum(u[:, 1:], 0.) + np.maximum(-u[:, :-1], 0.))/g.dx
        outgoing += (np.maximum(w[1:], 0.) + np.maximum(-w[:-1], 0.))/g.dz
        loss = 2*outgoing + 2*self.kappa*(1/g.dx**2+1/g.dz**2)
        for side, at, spacing in (('left', (slice(None), 0), g.dx),
                                  ('right', (slice(None), -1), g.dx),
                                  ('bottom', (0, slice(None)), g.dz),
                                  ('top', (-1, slice(None)), g.dz)):
            # A Dirichlet half-cell distance adds one more diagonal loss.
            if boundaries[side].diffusion_kind == 'temperature':
                loss[at] += self.kappa/spacing**2
        maximum = float(np.max(loss))
        return .9/maximum if maximum else math.inf

    def _rhs(self, temperature, u, w, boundaries, source, time, origin):
        g = self.grid
        fx, fz = np.empty((1, g.nz, g.nx+1)), np.empty((1, g.nz+1, g.nx))
        # Reuse the retained multidimensional conservative MC reconstruction.
        _reference_transfers(temperature[None], u, w, fx, fz)
        ax, az = fx[0], fz[0]
        qx, qz = np.zeros_like(ax), np.zeros_like(az)
        qx[:, 1:-1] = -self.conductivity*np.diff(temperature, axis=1)/g.dx
        qz[1:-1] = -self.conductivity*np.diff(temperature, axis=0)/g.dz
        values = (temperature[:, 0], temperature[:, -1], temperature[0], temperature[-1])
        velocities = (u[:, 0], u[:, -1], w[0], w[-1])
        advfaces = (ax[:, 0], ax[:, -1], az[0], az[-1])
        difffaces = (qx[:, 0], qx[:, -1], qz[0], qz[-1])
        coords = self._coordinates(origin)
        extrema = [float(temperature.min()), float(temperature.max())]
        no_neumann_input = True
        interior_values = (temperature[:, 1], temperature[:, -2], temperature[1], temperature[-2])
        interior_faces = (ax[:, 1], ax[:, -2], az[1], az[-2])
        interior_velocity = (u[:, 1], u[:, -2], w[1], w[-2])
        for side, sign, T, v, af, df, (x, z), spacing in zip(
                _SIDES, _SIGNS, values, velocities, advfaces, difffaces, coords,
                (g.dx, g.dx, g.dz, g.dz)):
            boundary = boundaries[side]
            inward = sign*v < 0.
            upstream = T.copy()
            diffusion = _sample(boundary.diffusion_value, x, z, time, side+' diffusion')
            if boundary.diffusion_kind == 'temperature':
                # Reconstruct boundary cells with the SAME limited reflected
                # wall jump as R4.2, now on every side. Retain exact affine
                # fields on open Dirichlet boundaries without changing the
                # closed predecessor's support or adding an outflow condition.
                i = _SIDES.index(side)
                wall_jump = 2*sign*(diffusion-T)
                interior_jump = sign*(T-interior_values[i])
                slope = np.where(wall_jump*interior_jump > 0.,
                    np.sign(wall_jump)*np.minimum(np.minimum(2*np.abs(interior_jump),
                        np.abs(.5*wall_jump+.5*interior_jump)),np.abs(wall_jump)),0.)
                donor = sign*interior_velocity[i] < 0.
                interior_faces[i][donor] = interior_velocity[i][donor]*(T-.5*sign*slope)[donor]
                upstream = T+.5*sign*slope
            if np.any(inward):
                if boundary.inflow_temperature_k is None:
                    raise TectonicsError(side + ': thermal inflow state missing')
                inflow = _sample(boundary.inflow_temperature_k, x, z, time, side+' inflow')
                if np.any(inflow[inward] <= 0.):
                    raise TectonicsError('inflow temperature must be positive kelvin')
                upstream[inward] = inflow[inward]
                extrema.extend((float(inflow[inward].min()), float(inflow[inward].max())))
            af[:] = v*upstream
            if boundary.diffusion_kind == 'temperature':
                if np.any(diffusion <= 0.):
                    raise TectonicsError('boundary temperature must be positive kelvin')
                df[:] = sign*2*self.conductivity*(T-diffusion)/spacing
                extrema.extend((float(diffusion.min()), float(diffusion.max())))
            else:
                df[:] = sign*diffusion
                no_neumann_input = no_neumann_input and not np.any(diffusion)
        x, z = g.edges(origin)
        X, Z = np.meshgrid(x[:-1]+.5*g.dx, z[:-1]+.5*g.dz)
        H = _sample(source, X, Z, time, 'volumetric heat source')
        derivative = -(np.diff(ax, axis=1)/g.dx + np.diff(az, axis=0)/g.dz)
        derivative += (H - np.diff(qx, axis=1)/g.dx - np.diff(qz, axis=0)/g.dz)/self.capacity
        adv, diff = {}, {}
        for side, sign, af, df, area in zip(_SIDES, _SIGNS, advfaces, difffaces,
                                          (g.dz, g.dz, g.dx, g.dx)):
            adv[side] = sign*_sum(af)*area*g.strike_width_m*self.capacity
            diff[side] = sign*_sum(df)*area*g.strike_width_m
        account = dict(advective=adv, diffusive=diff, source=_sum(H)*g.volume)
        # The proven source-free maximum principle applies with all Dirichlet
        # boundaries (or exactly zero prescribed diffusive flux) and no source.
        bounded = not np.any(H) and no_neumann_input
        return derivative, account, (min(extrema), max(extrema)) if bounded else None

    def step(self, temperature_k, u_m_s, w_m_s, duration_s, *, boundaries,
             time_s=0., mesh_velocity_m_s=(0., 0.), source_w_m3=0., origin_m=None,
             cancel=None):
        """One accepted SSP-RK2 interval; every flux is outward-positive energy J."""
        _cancel(cancel)
        dt = scalar(duration_s, 'duration', positive=True)
        time = scalar(time_s, 'time')
        if time+dt <= time or not math.isfinite(time+dt):
            raise TectonicsError('unresolvable transport time interval')
        mesh = _pair(mesh_velocity_m_s, 'mesh_velocity_m_s')
        origin = self.grid.origin_m if origin_m is None else _pair(origin_m, 'origin_m')
        end_origin = tuple(a+dt*b for a, b in zip(origin, mesh))
        if any(a == b and m != 0. for a, b, m in zip(origin, end_origin, mesh)):
            raise TectonicsError('unresolvable prescribed mesh translation')
        if not isinstance(boundaries, dict) or set(boundaries) != set(_SIDES) or any(
                type(bc) is not HeatBoundary for bc in boundaries.values()):
            raise TectonicsError('all four typed thermal boundaries required')
        g = self.grid
        if input_shape(temperature_k, 'temperature') != (g.nz, g.nx):
            raise TectonicsError('temperature requires rectangular cell means')
        with self.budget.reserve(self.work_bytes, category='w07-open-heat'):
            self.grid.edges(origin)
            self.grid.edges(end_origin)
            T = read_array(temperature_k, 'temperature')
            if np.any(T <= 0.):
                raise TectonicsError('temperature must be positive kelvin')
            u0, w0 = self._velocity(u_m_s, w_m_s, mesh, time, origin)
            u1, w1 = self._velocity(u_m_s, w_m_s, mesh, time+dt, end_origin)
            limit = min(self._limit(u0, w0, boundaries), self._limit(u1, w1, boundaries))
            if dt > limit*(1+8*np.finfo(float).eps):
                raise TectonicsError(f'heat timestep exceeds monotonicity limit {limit:.17g} s')
            d0, a0, b0 = self._rhs(T, u0, w0, boundaries, source_w_m3, time, origin)
            stage = T+dt*d0
            if not np.isfinite(stage).all() or np.any(stage <= 0.):
                raise TectonicsError('thermal source or boundary flux exceeds positive-temperature support')
            if b0 is not None:
                tol = 128*np.finfo(float).eps*max(abs(b0[0]), abs(b0[1]))
                if stage.min() < b0[0]-tol or stage.max() > b0[1]+tol:
                    raise TectonicsError('source-free thermal Euler-stage maximum principle failed')
            _cancel(cancel)
            d1, a1, b1 = self._rhs(stage, u1, w1, boundaries, source_w_m3, time+dt, end_origin)
            result = .5*T+.5*(stage+dt*d1)
            if not np.isfinite(result).all() or np.any(result <= 0.):
                raise TectonicsError('thermal source or boundary flux exceeds positive-temperature support')
            if b0 is not None and b1 is not None:
                lo, hi = min(b0[0], b1[0]), max(b0[1], b1[1])
                tol = 128*np.finfo(float).eps*max(abs(lo), abs(hi))
                if result.min() < lo-tol or result.max() > hi+tol:
                    raise TectonicsError('source-free thermal maximum principle failed')
            adv = {s: .5*dt*(a0['advective'][s]+a1['advective'][s]) for s in _SIDES}
            diff = {s: .5*dt*(a0['diffusive'][s]+a1['diffusive'][s]) for s in _SIDES}
            source = .5*dt*(a0['source']+a1['source'])
            before = _sum(T)*g.volume*self.capacity
            after = _sum(result)*g.volume*self.capacity
            residual = math.fsum((after, -before, *adv.values(), *diff.values(), -source))
            scale = max(abs(before), abs(after), sum(map(abs, adv.values())),
                        sum(map(abs, diff.values())), abs(source), np.finfo(float).tiny)
            if abs(residual)/scale > 1e-9:
                raise TectonicsError('open heat storage/flux closure failed')
            return dict(temperature_k=frozen(result), time_s=time+dt, origin_m=end_origin,
                        advective_energy_j=adv, diffusive_energy_j=diff, source_energy_j=source,
                        heat_before_j=before, heat_after_j=after, balance_residual_j=residual,
                        balance_relative=abs(residual)/scale, minimum_k=float(result.min()),
                        maximum_k=float(result.max()), timestep_limit_s=limit,
                        geometric_conservation_residual_m3=0., accepted_steps=1)

    def evolve(self, temperature_k, u_m_s, w_m_s, duration_s, *, steps, boundaries,
               time_s=0., mesh_velocity_m_s=(0., 0.), source_w_m3=0., cancel=None):
        """Explicit prescribed partition; never silently substep or exceed 256."""
        if type(steps) is not int or not 1 <= steps <= 256:
            raise TectonicsError('W07 requires 1 to 256 accepted intervals')
        duration = scalar(duration_s, 'duration', positive=True)
        time_s = scalar(time_s, 'time')
        T, origin = temperature_k, self.grid.origin_m
        adv, diff, sources = {s: [] for s in _SIDES}, {s: [] for s in _SIDES}, []
        before = None
        maximum_balance = 0.
        for i in range(steps):
            start = time_s+duration*i/steps
            stop = time_s+duration*(i+1)/steps
            result = self.step(T, u_m_s, w_m_s, stop-start, boundaries=boundaries,
                               time_s=start, mesh_velocity_m_s=mesh_velocity_m_s,
                               source_w_m3=source_w_m3, origin_m=origin, cancel=cancel)
            before = result['heat_before_j'] if before is None else before
            maximum_balance = max(maximum_balance, result['balance_relative'])
            for s in _SIDES:
                adv[s].append(result['advective_energy_j'][s])
                diff[s].append(result['diffusive_energy_j'][s])
            sources.append(result['source_energy_j'])
            T, origin = result['temperature_k'], result['origin_m']
        result.update(advective_energy_j={s: math.fsum(adv[s]) for s in _SIDES},
                      diffusive_energy_j={s: math.fsum(diff[s]) for s in _SIDES},
                      source_energy_j=math.fsum(sources), heat_before_j=before,
                      accepted_steps=steps, maximum_step_balance_relative=maximum_balance)
        residual = math.fsum((result['heat_after_j'], -before,
                             *result['advective_energy_j'].values(),
                             *result['diffusive_energy_j'].values(), -result['source_energy_j']))
        result['balance_residual_j'] = residual
        result['balance_relative'] = abs(residual)/max(abs(before), abs(result['heat_after_j']))
        if result['balance_relative'] > 1e-9:
            raise TectonicsError('accumulated open heat storage/flux closure failed')
        return result


@dataclass(frozen=True, slots=True)
class MaterialRegion2D:
    """A finite uniform-density cohort rectangle in the grid's physical frame.

    The complete supplied list is the declared finite stock, including exterior
    inflow. Unrepresented space is explicitly vacuum, not inferred source matter.
    Density is inventory density, independent of mechanics' buoyancy density.
    """
    cohort_id: str
    bounds_m: tuple[float, float, float, float]
    mass_density_kg_m3: float

    def __post_init__(self):
        object.__setattr__(self, 'cohort_id', text(self.cohort_id, 'cohort_id'))
        if input_shape(self.bounds_m, 'region bounds') != (4,):
            raise TectonicsError('region needs xmin,xmax,zmin,zmax')
        b = tuple(scalar(v, 'region bound') for v in self.bounds_m)
        if b[1] <= b[0] or b[3] <= b[2]:
            raise TectonicsError('region must have positive finite area')
        object.__setattr__(self, 'bounds_m', b)
        object.__setattr__(self, 'mass_density_kg_m3', scalar(
            self.mass_density_kg_m3, 'inventory density', positive=True))


def _intersection(a, b):
    return max(0., min(a[1], b[1])-max(a[0], b[0])) * max(0., min(a[3], b[3])-max(a[2], b[2]))


def _swept_face_volume(bounds, domain, relative, dt, side, strike):
    """Exact piecewise-linear face-overlap integral, including throughflow.

    End-point set differences miss material entering AND leaving in one step.
    Each moving rectangle edge can cross a domain edge once. Splitting at those
    times makes trapezoidal integration exact, including diagonal corner paths.
    """
    axis = 0 if side < 2 else 1
    normal = relative[axis]
    if normal == 0. or dt == 0.:
        return 0.
    ni, ti = 2*axis, 2*(1-axis)
    face = domain[ni+(side % 2)]
    enter = (face-bounds[ni])/normal
    leave = (face-bounds[ni+1])/normal
    lo, hi = max(0., min(enter, leave)), min(dt, max(enter, leave))
    if hi <= lo:
        return 0.
    speed = relative[1-axis]
    cuts = [lo, hi]
    if speed != 0.:
        for a in bounds[ti:ti+2]:
            for b in domain[ti:ti+2]:
                crossing = (b-a)/speed
                if lo < crossing < hi:
                    cuts.append(crossing)
    cuts.sort()
    lengths = [max(0., min(bounds[ti+1]+speed*t, domain[ti+1])-
                      max(bounds[ti]+speed*t, domain[ti])) for t in cuts]
    integral = math.fsum(.5*(b-a)*(left+right)
                        for a, b, left, right in zip(cuts, cuts[1:], lengths, lengths[1:]))
    return _SIGNS[side]*normal*integral*strike


def translate_material_regions(grid, regions, physical_velocity_m_s, duration_s, *,
                               mesh_velocity_m_s=(0., 0.), budget=None, cancel=None):
    """Exact intersections for 2D constant translation and true in/out stocks.

    Returns cohort cell masses and cell volume fractions. The output region list
    retains exterior stock, so subsequent steps preserve sharp geometry instead
    of repeatedly remapping cell means. Each material point crosses a translating
    convex rectangle at most once in/out during this straight-line interval.
    Nonuniform/deforming material velocity is explicitly unsupported here.
    Catalogue admission is at most 256 rectangles (at most 32640 overlap
    comparisons); larger source catalogues require an explicitly expanded route.
    """
    _cancel(cancel)
    if type(grid) is not RectangularTransportGrid:
        raise TectonicsError('RectangularTransportGrid required')
    velocity = _pair(physical_velocity_m_s, 'physical_velocity_m_s')
    mesh = _pair(mesh_velocity_m_s, 'mesh_velocity_m_s')
    dt = scalar(duration_s, 'duration', nonnegative=True)
    if not isinstance(regions, (tuple, list)) or not regions:
        raise TectonicsError('explicit finite material-region catalogue required')
    if len(regions) > _MAX_MATERIAL_REGIONS:
        raise TectonicsError('W07 material catalogue admission is at most 256 rectangles')
    if any(type(r) is not MaterialRegion2D for r in regions):
        raise TectonicsError('explicit finite material-region catalogue required')
    ids = tuple(dict.fromkeys(r.cohort_id for r in regions))
    index = {key: i for i, key in enumerate(ids)}
    budget = WorkBudget(128*1024**2, parent=select_budget(budget))
    with budget.reserve(48*len(ids)*grid.nx*grid.nz + 256*len(regions) + 8192,
                        category='w07-material-intersection'):
        # A sorted sweep avoids comparing disjoint x ranges. Comparisons remain
        # bounded by genuinely overlapping x supports; no dense region matrix.
        active = []
        for region in sorted(regions, key=lambda r: r.bounds_m[0]):
            _cancel(cancel)
            active = [other for other in active if other.bounds_m[1] > region.bounds_m[0]]
            if any(_intersection(region.bounds_m, other.bounds_m) > 0. for other in active):
                raise TectonicsError('material source rectangles overlap')
            active.append(region)
        origin = grid.moved_origin(mesh, dt)
        x, z = grid.edges(origin)
        old = (grid.origin_m[0], grid.origin_m[0]+grid.width_m,
               grid.origin_m[1], grid.origin_m[1]+grid.height_m)
        # The final domain pulled back along physical material trajectories.
        pulled = (origin[0]-velocity[0]*dt, origin[0]+grid.width_m-velocity[0]*dt,
                  origin[1]-velocity[1]*dt, origin[1]+grid.height_m-velocity[1]*dt)
        relative = tuple(v-m for v, m in zip(velocity, mesh))
        mass = np.zeros((len(ids), grid.nz, grid.nx))
        fraction = np.zeros_like(mass)
        before, after, inward, outward, moved = [], [], [], [], []
        cohort_accounts = {key: dict(before_kg=[], after_kg=[], inflow_kg=[], outflow_kg=[]) for key in ids}
        for region in regions:
            _cancel(cancel)
            b = region.bounds_m
            displacement = (velocity[0]*dt, velocity[0]*dt, velocity[1]*dt, velocity[1]*dt)
            new_bounds = tuple(v+d for v, d in zip(b, displacement))
            if any(d != 0. and n == v for v, n, d in zip(b, new_bounds, displacement)):
                raise TectonicsError('unresolvable physical material translation')
            current = MaterialRegion2D(region.cohort_id, new_bounds, region.mass_density_kg_m3)
            moved.append(current)
            dx = np.maximum(0., np.minimum(x[1:], new_bounds[1])-np.maximum(x[:-1], new_bounds[0]))
            dz = np.maximum(0., np.minimum(z[1:], new_bounds[3])-np.maximum(z[:-1], new_bounds[2]))
            volume = dz[:, None]*dx[None, :]*grid.strike_width_m
            k = index[region.cohort_id]
            mass[k] += volume*region.mass_density_kg_m3
            fraction[k] += volume/grid.volume
            scale = grid.strike_width_m*region.mass_density_kg_m3
            first = _intersection(b, old)*scale
            last = _intersection(b, pulled)*scale
            face_mass = [_swept_face_volume(b, old, relative, dt, side, grid.strike_width_m)*
                         region.mass_density_kg_m3 for side in range(4)]
            entering = -math.fsum(min(0., value) for value in face_mass)
            exiting = math.fsum(max(0., value) for value in face_mass)
            before.append(first); after.append(last); inward.append(entering); outward.append(exiting)
            row = cohort_accounts[region.cohort_id]
            for key, value in zip(row, (first, last, entering, exiting)):
                row[key].append(value)
        accounts = {}
        for key, row in cohort_accounts.items():
            acc = {name: math.fsum(values) for name, values in row.items()}
            acc['balance_residual_kg'] = math.fsum((acc['after_kg'], -acc['before_kg'],
                                                   -acc['inflow_kg'], acc['outflow_kg']))
            inventory = _sum(mass[index[key]])
            acc['cell_inventory_residual_kg'] = inventory-acc['after_kg']
            scale = max(acc['before_kg'], acc['after_kg'], acc['inflow_kg'], acc['outflow_kg'],
                        np.finfo(float).tiny)
            if max(abs(acc['balance_residual_kg']), abs(acc['cell_inventory_residual_kg']))/scale > 1e-9:
                raise TectonicsError('material intersection inventory closure failed')
            accounts[key] = acc
        if np.any(fraction < 0.) or np.any(np.sum(fraction, axis=0) > 1.+1e-12):
            raise TectonicsError('material intersections exceed cell volume')
        return dict(cohort_ids=ids, cell_mass_kg=frozen(mass), cell_volume_fraction=frozen(fraction),
                    regions=tuple(moved), origin_m=origin, accounts=accounts,
                    inflow_kg=math.fsum(inward), outflow_kg=math.fsum(outward),
                    mass_before_kg=math.fsum(before), mass_after_kg=math.fsum(after),
                    geometric_conservation_residual_m3=0.)
