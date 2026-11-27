"""Independent full-line uniform-plate quadrature; no Atlas imports.

Returns numerical uncertainty ESTIMATES, not rigorous continuum certificates.
The unsampled Green tails have an explicit analytic bound. All quadrature uses
separation/alpha coordinates, so SI kilometre scales cannot disappear between
the samples of an infinite-interval integrator. Cell means use nested quadrature
only for requested cells; this helper is intentionally not a full-grid solver.
"""
import math
import warnings

import numpy as np
from scipy.integrate import IntegrationWarning, quad


def _positive(value, name):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(name+' must be positive and finite')
    return value


def _finite(value, name):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(name+' must be finite')
    return value


def _alpha(rigidity_n_m, restoring_pa_per_m):
    d = _positive(rigidity_n_m, 'rigidity')
    k = _positive(restoring_pa_per_m, 'restoring coefficient')
    return math.exp((math.log(4.)+math.log(d)-math.log(k))/4.), k


def _kernel(separation_over_alpha, derivative):
    """Dimensionless alpha-integrated G, G', G'' (remaining factors 1/K/alpha^j)."""
    r = abs(separation_over_alpha)
    envelope = math.exp(-r)
    if derivative == 0:
        return .5*envelope*(math.cos(r)+math.sin(r))
    if derivative == 1:
        return -math.copysign(1., separation_over_alpha)*envelope*math.sin(r)
    return envelope*(math.sin(r)-math.cos(r))


def green_response(separation_m, *, rigidity_n_m, restoring_pa_per_m):
    """Point kernel (G,G',G'') in physical coordinates, not a load response."""
    alpha, k = _alpha(rigidity_n_m, restoring_pa_per_m)
    r = _finite(separation_m, 'separation')/alpha
    return np.asarray([_kernel(r, j)/(k*alpha**(j+1)) for j in range(3)])


def _quad(function, left, right, absolute_tolerance, relative_tolerance):
    with warnings.catch_warnings():
        warnings.simplefilter('error', IntegrationWarning)
        value, error = quad(function, left, right, epsabs=absolute_tolerance,
                            epsrel=relative_tolerance, limit=150)
    if not math.isfinite(value) or not math.isfinite(error):
        raise ArithmeticError('nonfinite quadrature result')
    return value, error


def _point(x, load, load_breaks, peak, alpha, k, atol, rtol, orders=(0, 1, 2)):
    x = _finite(x, 'evaluation coordinate')
    atol = tuple(_positive(v, 'absolute tolerance') for v in atol)
    rtol = _positive(rtol, 'relative tolerance')
    if len(atol) != len(orders) or rtol < 1e-13:
        raise ValueError('one absolute tolerance per derivative and rtol >= 1e-13 required')
    if peak == 0:
        return np.zeros(len(orders)), np.zeros(len(orders))
    # Integrating |kernel| on both |s|/alpha > radius tails gives these bounds.
    constants = (math.sqrt(2.), 2., 2.*math.sqrt(2.))
    scales = [1./(k*alpha**j) for j in orders]
    envelopes = [constants[j]*peak*scale for j, scale in zip(orders, scales)]
    radius = max(8., *(math.log(bound)+math.log(8.)-math.log(tol)
                       for bound, tol in zip(envelopes, atol)))
    cuts = {-radius, radius, 0.}
    cuts.update(v for v in (-16., -4., -1., 1., 4., 16.) if -radius < v < radius)
    cuts.update((x-b)/alpha for b in load_breaks if -radius < (x-b)/alpha < radius)
    cuts = sorted(cuts)
    values, errors = [], []
    for j, scale, tolerance, envelope in zip(orders, scales, atol, envelopes):
        pieces, estimates = [], []
        for left, right in zip(cuts[:-1], cuts[1:]):
            result, error = _quad(lambda s: load(x-alpha*s)*_kernel(s, j)*scale,
                left, right, tolerance/(4.*(len(cuts)-1)), rtol)
            pieces.append(result); estimates.append(error)
        value = math.fsum(pieces)
        error = math.fsum(estimates)+envelope*math.exp(-radius)
        if error > tolerance+rtol*abs(value):
            raise ArithmeticError('point response exceeds requested quadrature estimate')
        values.append(value); errors.append(error)
    return np.asarray(values), np.asarray(errors)


def _smooth(displacement_m, depth_m, decay_length_m, density_kg_m3, gravity_m_s2):
    a = _finite(displacement_m, 'displacement')
    if a < 0:
        raise ValueError('rightward displacement required')
    d = _positive(depth_m, 'depth'); length = _positive(decay_length_m, 'decay length')
    amplitude = d*_positive(density_kg_m3, 'density')*_positive(gravity_m_s2, 'gravity')
    difference = -math.expm1(-a/length)
    def load(relative_x):
        if relative_x <= 0 or a == 0:
            return 0.
        if relative_x < a:
            return amplitude*math.expm1(-relative_x/length)
        return -amplitude*math.exp(-(relative_x-a)/length)*difference
    # Fronts plus decay-scale divisions protect narrow exponential tails.
    return load, (0., a, a+length, a+4.*length, a+16.*length), amplitude*difference


def smooth_listric_response(x_m, displacement_m, *, depth_m, decay_length_m,
        trace_m, density_kg_m3, gravity_m_s2, rigidity_n_m, restoring_pa_per_m,
        absolute_tolerances=(1e-6, 1e-10, 1e-14), relative_tolerance=1e-10):
    """(values, estimates), each shape (3,), for full-line (w,w',w'')."""
    alpha, k = _alpha(rigidity_n_m, restoring_pa_per_m)
    load, breaks, peak = _smooth(displacement_m, depth_m, decay_length_m, density_kg_m3, gravity_m_s2)
    return _point(_finite(x_m, 'x')-_finite(trace_m, 'trace'), load, breaks, peak,
                  alpha, k, absolute_tolerances, relative_tolerance)


def _piecewise(edges_m, pressure_pa, far_left_pa, far_right_pa):
    edges = np.asarray(edges_m, dtype=float)
    pressure = np.asarray(pressure_pa, dtype=float)
    if (edges.ndim != 1 or len(edges) < 2 or pressure.shape != (len(edges)-1,)
            or not np.isfinite(edges).all() or not np.isfinite(pressure).all()
            or np.any(np.diff(edges) <= 0)):
        raise ValueError('finite increasing edges and one pressure per source cell required')
    left = _finite(far_left_pa, 'left halfline pressure')
    right = _finite(far_right_pa, 'right halfline pressure')
    origin = float(edges[0]); local = edges-origin
    def load(x):
        i = int(np.searchsorted(local, x, side='right'))-1
        return left if i < 0 else (right if i >= len(pressure) else float(pressure[i]))
    return load, local, max(abs(left), abs(right), float(np.max(np.abs(pressure)))), origin


def piecewise_constant_response(x_m, edges_m, pressure_pa, *, rigidity_n_m,
        restoring_pa_per_m, far_left_pa=0., far_right_pa=0.,
        absolute_tolerances=(1e-6, 1e-10, 1e-14), relative_tolerance=1e-10):
    """Small cell-constant source grid; zero outside unless halfline loads supplied."""
    alpha, k = _alpha(rigidity_n_m, restoring_pa_per_m)
    load, breaks, peak, origin = _piecewise(edges_m, pressure_pa, far_left_pa, far_right_pa)
    return _point(_finite(x_m, 'x')-origin, load, breaks, peak, alpha, k,
                  absolute_tolerances, relative_tolerance)


def _cell_mean(left, right, load, breaks, peak, alpha, k, atol, rtol):
    left = _finite(left, 'cell left'); right = _finite(right, 'cell right')
    atol = _positive(atol, 'mean absolute tolerance')
    if right <= left or atol > .01:
        raise ValueError('positive cell width and mean uncertainty target <=0.01 m required')
    width = right-left
    inner_errors = []
    def response(t):
        values, errors = _point(left+width*t, load, breaks, peak, alpha, k,
                                (atol/16.,), rtol, orders=(0,))
        inner_errors.append(float(errors[0]))
        return float(values[0])
    cuts = sorted({0., 1., *((b-left)/width for b in breaks if left < b < right)})
    values, errors = [], []
    for lo, hi in zip(cuts[:-1], cuts[1:]):
        value, error = _quad(response, lo, hi, atol/(4.*(len(cuts)-1)), rtol)
        values.append(value); errors.append(error)
    estimate = math.fsum(errors)+max(inner_errors, default=0.)
    if estimate > atol:
        raise ArithmeticError('cell mean exceeds its absolute quadrature uncertainty target')
    return math.fsum(values), estimate


def smooth_listric_cell_mean(left_m, right_m, displacement_m, *, depth_m,
        decay_length_m, trace_m, density_kg_m3, gravity_m_s2, rigidity_n_m,
        restoring_pa_per_m, absolute_tolerance_m=1e-5, relative_tolerance=1e-10):
    """(mean w, estimated absolute uncertainty); no centre-for-mean substitution."""
    alpha, k = _alpha(rigidity_n_m, restoring_pa_per_m)
    load, breaks, peak = _smooth(displacement_m, depth_m, decay_length_m, density_kg_m3, gravity_m_s2)
    trace = _finite(trace_m, 'trace')
    return _cell_mean(left_m-trace, right_m-trace, load, breaks, peak, alpha, k,
                      absolute_tolerance_m, relative_tolerance)


def piecewise_constant_cell_mean(left_m, right_m, edges_m, pressure_pa, *,
        rigidity_n_m, restoring_pa_per_m, far_left_pa=0., far_right_pa=0.,
        absolute_tolerance_m=1e-5, relative_tolerance=1e-10):
    """Cell-mean w for a small cell-constant grid, with explicit error admission."""
    alpha, k = _alpha(rigidity_n_m, restoring_pa_per_m)
    load, breaks, peak, origin = _piecewise(edges_m, pressure_pa, far_left_pa, far_right_pa)
    return _cell_mean(left_m-origin, right_m-origin, load, breaks, peak, alpha, k,
                      absolute_tolerance_m, relative_tolerance)
