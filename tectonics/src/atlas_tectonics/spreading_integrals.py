"""W06 age-distributed, phase-resolved finite-plate cooling integrals.

These are uniform *age-distribution* means, never a mean-age approximation.
Young columns use W03 image primitives and adaptive integration in sqrt(age);
mature columns use exact exponential age averages. No instantaneous birth flux
is requested. The returned arrays have immutable, detached backing.
"""
from __future__ import annotations

import math

import numpy as np

from ._validation import TectonicsError, frozen, input_shape, read_array
from .plate_cooling import (_IMAGE_LIMIT, _MODES, _cancel, _erfc_mean,
                            _fourier_age, _parameters, plate_cooling_heat)
from .resources import elements, select_budget
from .stokes_execution import _factored_scale


_BATCH = 128
_MAX_DEPTH = 24
_MAX_PANELS = 32768
_EPS = np.finfo(np.float64).eps
# Absolute error in normalised phase-mean temperature and full-column heat.
# The extra dimensional gate keeps large temperature contrasts honest.
_NORMALISED_TOLERANCE = 2e-12
_MEAN_TEMPERATURE_TOLERANCE_K = 1e-6
_RULES = tuple(np.polynomial.legendre.leggauss(n) for n in (8, 16))


def _young_values(fo, x, width, plate, budget, cancel, erfc):
    """Normalised phase deficits and cumulative heat, one bounded sample batch."""
    root = 2*np.sqrt(fo)
    result = np.zeros((len(fo), len(width)+2))
    positive = fo > 0
    if not np.any(positive):
        return result
    scale = root[positive]
    for j, (lo, hi) in enumerate(zip(x[:-1], x[1:])):
        # Integrate the deficit directly: subtracting a temperature from Tb
        # would erase very young, small but nonzero heat/deficit accounts.
        value = _erfc_mean(lo/scale, hi/scale, erfc)
        for shift in (2., 4.):
            value -= _erfc_mean((shift-hi)/scale, (shift-lo)/scale, erfc)
            value += _erfc_mean((shift+lo)/scale, (shift+hi)/scale, erfc)
        result[positive, j] = value
    ages = _factored_scale(fo[positive], (plate.thickness_m, plate.thickness_m),
                           (plate.thermal.diffusivity_m2_s,), 'quadrature age')
    heat = plate_cooling_heat(ages, plate, budget=budget, cancel=cancel)
    contrast = plate.thermal.mantle_temperature_k-plate.thermal.surface_temperature_k
    result[positive, -2:] = _factored_scale(heat, (),
        (plate.volumetric_heat_capacity_j_m3_k, contrast, plate.thickness_m),
        'normalised cumulative heat')
    return result


def _young_means(lo, hi, x, width, plate, budget, cancel, erfc, tolerance):
    """Adaptive Gauss 8/16 with accumulated componentwise error estimates.

    Each accepted panel must meet its share of the complete interval tolerance.
    Embedded-rule disagreement is inflated by eight, and roundoff is included.
    Depth diffusion scales are mandatory breakpoints: an arbitrarily shallow
    phase's initial transition cannot hide between all the quadrature nodes.
    Refinement and storage are finite; unmet error estimates raise visibly.
    """
    size = len(lo); components = len(width)+2
    output = np.zeros((size, components)); uncertainty = np.zeros_like(output)
    first = np.sqrt(lo); last = np.sqrt(hi)
    # Rationalised difference retains intervals narrower than sqrt's own ulp.
    delta = (hi-lo)/(first+last)
    pending = []
    for i in range(size):
        cuts = [0., 1.]
        for edge in x[1:-1]:
            q = (.5*edge-first[i])/delta[i]
            if 0. < q < 1.:
                cuts.append(float(q))
        cuts.sort()
        pending.extend((i, a, b, 0) for a, b in zip(cuts[:-1], cuts[1:]) if b > a)
    evaluated = 0
    while pending:
        _cancel(cancel)
        batch = pending[-_BATCH:]; del pending[-len(batch):]
        evaluated += len(batch)
        if evaluated > _MAX_PANELS:
            raise TectonicsError('spreading thermal quadrature exceeded its panel bound')
        ids = np.array([row[0] for row in batch], dtype=np.intp)
        a = np.array([row[1] for row in batch]); b = np.array([row[2] for row in batch])
        span = b-a
        values = []
        for nodes, weights in _RULES:
            q = a[:, None] + .5*span[:, None]*(1+nodes)
            roots = first[ids, None]+delta[ids, None]*q
            sampled = _young_values((roots*roots).reshape(-1), x, width,
                                     plate, budget, cancel, erfc)
            sampled = sampled.reshape(len(batch), len(nodes), components)
            jacobian = 2*roots/(first[ids, None]+last[ids, None])
            values.append(.5*span[:, None]*np.sum(
                sampled*(weights[None, :]*jacobian)[:, :, None], axis=1))
        estimate = 8*np.abs(values[1]-values[0])+64*_EPS*np.abs(values[1])
        accepted = np.all(estimate <= span[:, None]*tolerance, axis=1)
        for j, (i, start, end, depth) in enumerate(batch):
            if accepted[j]:
                output[i] += values[1][j]; uncertainty[i] += estimate[j]
            else:
                mid = start+.5*(end-start)
                if depth >= _MAX_DEPTH or mid == start or mid == end:
                    raise TectonicsError('spreading thermal quadrature error bound not met')
                pending.extend(((i, start, mid, depth+1), (i, mid, end, depth+1)))
    if np.any(uncertainty > tolerance*(1+128*_EPS)):
        raise TectonicsError('spreading thermal accumulated quadrature error bound not met')
    return output


def _mature_means(lo, hi, steady, modes):
    """Exact age integral of the W03 bounded Fourier representation."""
    span = hi-lo
    mid = lo+.5*span
    output = np.empty((len(lo), len(steady)+2))
    output[:, :-2] = steady
    output[:, -2] = mid+1/3
    output[:, -1] = -mid+1/6
    for n in range(1, _MODES+1):
        rate = n*n*math.pi**2
        with np.errstate(over='ignore', invalid='ignore'):
            scaled = rate*span
            factor = np.ones_like(span)
            np.divide(-np.expm1(-scaled), scaled, out=factor, where=scaled != 0)
            average = np.exp(-rate*lo)*factor
        output[:, :-2] -= average[:, None]*modes[n-1]
        term = 2/(n*n*math.pi**2)*average
        output[:, -2] -= term
        output[:, -1] += (-1)**n*term
    return output


def spreading_thermal_means(youngest_age_s, oldest_age_s, depth_edges_m, plate,
                            *, budget=None, cancel=None):
    """Return ``(phase_deficit_k_m, outward_heat_j_m2)`` averaged over age.

    The final axes are respectively the <=16 disjoint phases spanning exactly
    [0,L], and (top, base). Age inputs broadcast, are finite and nonnegative, and
    require oldest >= youngest. Equal endpoints denote a point column; age zero
    has exactly zero deficit and heat. Base heat is negative, denoting inflow.
    Young quadrature tracks its uncertainty and refuses unmet tolerances rather
    than silently returning a fixed-node approximation. Reservations account for
    outputs, captured inputs, a bounded panel stack and nested W03 work.
    """
    _parameters(plate); _cancel(cancel)
    ys = input_shape(youngest_age_s); os = input_shape(oldest_age_s)
    es = input_shape(depth_edges_m)
    if len(es) != 1 or not 2 <= es[0] <= 17:
        raise TectonicsError('spreading thermal columns require 1 to 16 phases')
    try:
        shape = np.broadcast_shapes(ys, os)
    except ValueError as exc:
        raise TectonicsError('spreading cooling ages cannot broadcast') from exc
    size = elements(shape); phases = es[0]-1
    if size == 0:
        raise TectonicsError('nonempty spreading cooling ages required')
    # At most 128 panels x 16 nodes x 18 components are materialised. Panel
    # bookkeeping is bounded independently of the number of output cells.
    required = (32*(elements(ys)+elements(os)+es[0])+64*size*(phases+4)
                + 256*_MAX_PANELS + 512*_BATCH*16*(phases+2)+16384)
    resource = select_budget(budget)
    with resource.reserve(required, category='spreading-thermal-means'):
        from scipy.special import erfc
        young = read_array(youngest_age_s, 'youngest_age_s', nonnegative=True)
        old = read_array(oldest_age_s, 'oldest_age_s', nonnegative=True)
        edges = read_array(depth_edges_m, 'depth_edges_m', nonnegative=True)
        if young.shape != ys or old.shape != os or edges.shape != es:
            raise TectonicsError('spreading thermal input shape changed during capture')
        if (edges[0] != 0. or edges[-1] != plate.thickness_m
                or np.any(np.diff(edges) <= 0)):
            raise TectonicsError('depth edges must increase over exactly the full plate')
        young, old = np.broadcast_arrays(young, old)
        if np.any(old < young):
            raise TectonicsError('oldest cooling age precedes youngest cooling age')
        contrast = plate.thermal.mantle_temperature_k-plate.thermal.surface_temperature_k
        if contrast == 0:
            return frozen(np.zeros(shape+(phases,))), frozen(np.zeros(shape+(2,)))
        lo = _fourier_age(young, plate).reshape(-1)
        hi = _fourier_age(old, plate).reshape(-1)
        x = edges/plate.thickness_m
        widths_m = np.diff(edges); width = widths_m/plate.thickness_m
        mid = (edges[:-1]+.5*widths_m)/plate.thickness_m
        steady = ((plate.thickness_m-edges[:-1])+
                  (plate.thickness_m-edges[1:]))/(2*plate.thickness_m)
        modes = np.array([(2/(n*math.pi))*np.sin(n*math.pi*mid)*np.sinc(.5*n*width)
                          for n in range(1, _MODES+1)])
        tolerance = min(_NORMALISED_TOLERANCE,
                        _MEAN_TEMPERATURE_TOLERANCE_K/contrast)
        output = np.zeros((size, phases+2))
        for start in range(0, size, _BATCH):
            _cancel(cancel)
            a = lo[start:start+_BATCH]; b = hi[start:start+_BATCH]
            out = output[start:start+len(a)]
            points = a == b
            young_points = points & (a > 0) & (a <= _IMAGE_LIMIT)
            if np.any(young_points):
                out[young_points] = _young_values(a[young_points], x, width,
                    plate, resource, cancel, erfc)
            mature_points = points & (a > _IMAGE_LIMIT)
            if np.any(mature_points):
                out[mature_points] = _mature_means(a[mature_points], b[mature_points], steady, modes)
            intervals = ~points
            recent = intervals & (a < _IMAGE_LIMIT)
            if np.any(recent):
                end = np.minimum(b[recent], _IMAGE_LIMIT)
                weights = (end-a[recent])/(b[recent]-a[recent])
                out[recent] += weights[:, None]*_young_means(a[recent], end, x, width,
                    plate, resource, cancel, erfc, tolerance)
            mature = intervals & (b > _IMAGE_LIMIT)
            if np.any(mature):
                begin = np.maximum(a[mature], _IMAGE_LIMIT)
                weights = (b[mature]-begin)/(b[mature]-a[mature])
                out[mature] += weights[:, None]*_mature_means(begin, b[mature], steady, modes)
        deficit = _factored_scale(output[:, :-2]*widths_m, (contrast,), (),
                                  'spreading phase deficit')
        heat = _factored_scale(output[:, -2:],
            (plate.volumetric_heat_capacity_j_m3_k, contrast, plate.thickness_m), (),
            'spreading cumulative heat')
        return frozen(deficit.reshape(shape+(phases,))), frozen(heat.reshape(shape+(2,)))
