"""Independent W06.3 scalar reference; deliberately no production imports.

Temperature uses the Dirichlet plate's scalar image/Fourier solutions. Phase
means use adaptive DEPTH quadrature, then cell means use adaptive AGE quadrature
(a=y**2 at the ridge). Accounts integrate parcel birth times and freeze cooling
at boundary exit. Neither cell sums nor production heat/support functions are
used to construct the accounting reference. All quadrature is dimensionless.
"""
from __future__ import annotations

from functools import lru_cache
import math

import numpy as np
from scipy.integrate import quad

from w06_spreading_reference import reference_geometry


def scalar_temperature_fraction(depth_fraction, fourier_time):
    """(T-Ts)/(Tb-Ts), including exact initial/boundary values, no age floor."""
    x, t = float(depth_fraction), float(fourier_time)
    if not 0. <= x <= 1. or t < 0.:
        raise ValueError('depth/age outside reference plate')
    if x == 0.:
        return 0.
    if x == 1. or t == 0.:
        return 1.
    if t < .08:
        scale = 2.*math.sqrt(t)
        deficit = []
        for j in range(64):
            a = math.erfc((2*j+x)/scale)
            b = math.erfc((2*j+2-x)/scale)
            deficit.append(a-b)
            if j and a < 1.e-17:
                break
        else:
            raise ArithmeticError('image reference did not converge')
        return 1.-math.fsum(deficit)
    terms = []
    for n in range(1, 1025):
        damping = math.exp(-n*n*math.pi**2*t)
        terms.append(2.*math.sin(n*math.pi*x)*damping/(n*math.pi))
        if damping < 1.e-17:
            break
    else:
        raise ArithmeticError('Fourier reference did not converge')
    return x+math.fsum(terms)


def scalar_boundary_heat_fraction(fourier_time):
    """Cumulative outward top/base heat divided by C*(Tb-Ts)*L.

Young-time expressions integrate the image heat-flux series analytically:
integral exp(-d*d/y*y)dy = y exp(-d*d/y*y)-d sqrt(pi) erfc(d/y).
The independent older branch integrates the sine-series boundary derivatives.
"""
    t = float(fourier_time)
    if t < 0.:
        raise ValueError('negative reference age')
    if t == 0.:
        return 0., 0.
    if t < .08:
        y = math.sqrt(t)

        def primitive(d):
            return y*math.exp(-(d/y)**2)-d*math.sqrt(math.pi)*math.erfc(d/y)

        top = 2./math.sqrt(math.pi)*(y+2.*math.fsum(primitive(n) for n in range(1, 9)))
        base = -4./math.sqrt(math.pi)*math.fsum(primitive(n+.5) for n in range(9))
        return top, base
    damped = [math.exp(-n*n*math.pi**2*t)/(n*n) for n in range(1, 65)]
    top = t+1./3.-2./math.pi**2*math.fsum(damped)
    base = -t+1./6.+2./math.pi**2*math.fsum((-1)**n*v for n, v in enumerate(damped, 1))
    return top, base


class CoolingReference:
    """Small scalar reference with bounded exact-key reuse, never age binning.

Each timed scalar run creates a fresh object; caches only remove duplicate
left/right intervals within that run. Tightened controls can independently
audit the reported quadrature uncertainty. ``max_quad_error`` is dimensionless.
    """
    def __init__(self, cooling, phases, *, tolerance=None, cache_size=8192):
        self.cooling = dict(cooling)
        self.phases = tuple(dict(p) for p in phases)
        self.tolerance = float(tolerance or cooling['reference_quadrature_tolerance'])
        self.max_quad_error = 0.
        self.length = cooling['plate_thickness_m']
        self.ts = cooling['surface_temperature_k']
        self.tb = cooling['base_temperature_k']
        self.delta = self.tb-self.ts
        self.time_scale = self.length**2/cooling['diffusivity_m2_s']
        self.capacity = cooling['conductivity_w_m_k']/cooling['diffusivity_m2_s']
        self.energy = self.capacity*self.delta*self.length
        self.depths = np.concatenate(([0.], np.cumsum([p['thickness_m'] for p in phases])))/self.length
        if self.depths[-1] != 1.:
            raise ValueError('reference phases must partition the plate')
        self._at = lru_cache(maxsize=cache_size)(self._at_uncached)
        self._mean = lru_cache(maxsize=cache_size)(self._mean_uncached)

    def _quad(self, function, left=0., right=1., *, points=None):
        value, error = quad(function, left, right, epsabs=self.tolerance,
                            epsrel=self.tolerance, points=points, limit=200)
        self.max_quad_error = max(self.max_quad_error, error)
        if error > max(32*self.tolerance, abs(value)*32*self.tolerance):
            raise ArithmeticError('adaptive scalar reference uncertainty exceeded')
        return value

    def _at_uncached(self, age_s):
        if age_s < 0.:
            raise ValueError('negative cooling age')
        t = age_s/self.time_scale
        deficits = []
        for a, b in zip(self.depths[:-1], self.depths[1:]):
            # Explicitly expose the thin newborn boundary layer to QUADPACK;
            # no finite sampled grid can silently miss it at small positive age.
            points = [v for v in (2*math.sqrt(t), 8*math.sqrt(t)) if a < v < b]
            deficit = 0. if t == 0. else self._quad(
                lambda x: 1.-scalar_temperature_fraction(x, t), a, b, points=points)
            deficits.append(deficit)
        means = [self.tb-self.delta*d/(b-a)
                 for d, a, b in zip(deficits, self.depths[:-1], self.depths[1:])]
        sheet = self.delta*self.length*math.fsum(
            p['density_kg_m3']*alpha*d for p, alpha, d in
            zip(self.phases, self.cooling['phase_expansion_per_k'], deficits))
        subsidence = sheet/(self.cooling['compensation_density_kg_m3']-self.cooling['water_density_kg_m3'])
        top, base = scalar_boundary_heat_fraction(t)
        return tuple(means+[sheet, subsidence, self.cooling['axial_depth_m']+subsidence,
                            top*self.energy, base*self.energy])

    def point(self, age_s):
        return np.asarray(self._at(float(age_s)))

    def _age_knots(self, young, old):
        # A quadrature error estimate alone can miss a shallow-layer tail. Force
        # geometric diffusion-scale partitions around EVERY phase interface.
        ages = {self.time_scale*z*z*2.**power for z in self.depths[1:]
                for power in range(-32, 17, 2)}
        return sorted(a for a in ages if young < a < old)

    def _mean_uncached(self, young, old):
        if young < 0. or old < young:
            raise ValueError('reversed/negative reference age range')
        if young == old:
            return self._at(young)
        # Integrate normalised fields so a single quadrature contract covers K,
        # kg/m2, metres and heat; the independent depth quadrature remains inside.
        scales = [self.delta]*len(self.phases)+[
            self.cooling['compensation_density_kg_m3']*self.length,
            self.length, self.length, self.energy, self.energy]
        if young == 0.:
            transform = lambda q: (old*q*q, 2*q)
            knots = [math.sqrt(a/old) for a in self._age_knots(young, old)]
        else:
            transform = lambda q: (young+(old-young)*q, 1.)
            knots = [(a-young)/(old-young) for a in self._age_knots(young, old)]
        values = []
        for column, scale in enumerate(scales):
            def integrand(q):
                age, weight = transform(q)
                return weight*self._at(age)[column]/scale
            values.append(self._quad(integrand, points=knots)*scale)
        return tuple(values)

    def mean(self, youngest_s, oldest_s):
        return np.asarray(self._mean(float(youngest_s), float(oldest_s)))

    def fields(self, edges_m, elapsed_s, **motion):
        """All occupied cell means and centres, computed from birth preimages."""
        edges = np.asarray(edges_m, dtype=float)
        geometry = reference_geometry(edges, elapsed_s, **motion)
        widths = geometry[:, :, 0].sum(axis=0)
        cell = np.zeros((edges.size-1, len(self.phases)+5))
        centre = np.zeros_like(cell)
        valid = np.zeros(edges.size-1, dtype=bool)
        for i in range(edges.size-1):
            if widths[i] > 0.:
                for side in range(2):
                    width, young, old = geometry[side, i]
                    if width > 0.:
                        cell[i] += (width/widths[i])*self.mean(young, old)
            x = (edges[i]+edges[i+1])/2.
            if elapsed_s == 0.:
                continue
            ridge = motion['ridge_position_m']+motion['ridge_velocity_m_s']*elapsed_s
            u = motion['left_velocity_m_s'] if x < ridge else motion['right_velocity_m_s']
            tau = (x-motion['ridge_position_m']-u*elapsed_s)/(motion['ridge_velocity_m_s']-u)
            if 0. <= tau <= elapsed_s:
                valid[i] = True
                centre[i] = self.point(elapsed_s-tau)
        return dict(cell_values=cell, centre_values=centre,
                    ocean_fraction=widths/np.diff(edges), centre_valid=valid)

    def accounts(self, bounds_m, elapsed_s, *, width_m, **motion):
        """Independent birth-time integrals, including affine migrating exit ages."""
        time = float(elapsed_s)
        p = len(self.phases)
        birth_area = (motion['right_velocity_m_s']-motion['left_velocity_m_s'])*time*width_m
        birth = birth_area*self.energy
        resident, exports = 0., [0., 0.]
        resident_water, water_exports = 0., [0., 0.]
        top, basal = 0., 0.
        for side, boundary, velocity in zip((0, 1), bounds_m,
                (motion['left_velocity_m_s'], motion['right_velocity_m_s'])):
            relative = abs(velocity-motion['ridge_velocity_m_s'])
            if time == 0.:
                continue
            # x(t,tau)=r0+u*t+(vr-u)*tau. The independently solved
            # boundary crossing partitions the BIRTH-time interval, not x-cells.
            crossing = (boundary-motion['ridge_position_m']-velocity*time)/(motion['ridge_velocity_m_s']-velocity)
            last_exported_birth = min(time, max(0., crossing))
            for exported, a, b in ((True, 0., last_exported_birth),
                                    (False, last_exported_birth, time)):
                if b <= a:
                    continue
                area = (b-a)*relative*width_m

                def age_at(q):
                    tau = a+(b-a)*q
                    if exported:
                        return (boundary-motion['ridge_position_m']-motion['ridge_velocity_m_s']*tau)/velocity
                    return time-tau

                # Resident ages include zero at q=1. Transform birth time so
                # the independent quadrature resolves its sqrt-age endpoint.
                def integrate(function):
                    if not exported and b == time:
                        span = time-a
                        knots = [math.sqrt(age/span) for age in self._age_knots(0., span)]
                        return self._quad(lambda y: 2*y*function(span*y*y), points=knots)
                    lo, hi = age_at(0.), age_at(1.)
                    knots = ([] if lo == hi else sorted((age-lo)/(hi-lo)
                        for age in self._age_knots(min(lo, hi), max(lo, hi))))
                    return self._quad(lambda q: function(age_at(q)), points=knots)

                enthalpy = area*self.energy*integrate(lambda age:
                    math.fsum((self._at(age)[j]-self.ts)/self.delta*
                        (self.depths[j+1]-self.depths[j]) for j in range(p)))
                water = area*self.length*integrate(lambda age: self._at(age)[p+2]/self.length)
                top += area*self.energy*integrate(lambda age: self._at(age)[p+3]/self.energy)
                basal -= area*self.energy*integrate(lambda age: self._at(age)[p+4]/self.energy)
                if exported:
                    exports[side] += enthalpy
                    water_exports[side] += water
                else:
                    resident += enthalpy
                    resident_water += water
        residual = math.fsum((resident, *exports, top, -basal, -birth))
        normalisation = max(birth, math.fsum((abs(top), abs(basal), *map(abs, exports))), 1.)
        water = math.fsum((resident_water, *water_exports))
        return (np.asarray((birth, self.cooling['birth_enthalpy_stock_j']-birth,
                basal, self.cooling['basal_heat_stock_j']-basal, top, resident,
                *exports, residual, residual/normalisation)),
                np.asarray((water, self.cooling['water_stock_m3']-water,
                            resident_water, *water_exports, 0.)))
