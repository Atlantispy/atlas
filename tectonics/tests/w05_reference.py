"""Independent quadrature references for the prescribed dry W05 kinematics.

No Atlas/production imports. Coordinates and thicknesses are metres; boundary
exchanges are signed INTO the fixed interval, in m2 per transverse width.
These small verification helpers are not a production solver or a history store.
"""
import math
import warnings

import numpy as np
from scipy.integrate import IntegrationWarning, quad


_QUAD_RTOL = 2e-13


def _geometry(depth_m, decay_length_m, trace_m):
    d, length, trace = map(float, (depth_m, decay_length_m, trace_m))
    if not all(map(math.isfinite, (d, length, trace))) or min(d, length) <= 0:
        raise ValueError('finite positive depth/decay length and finite trace required')
    return d, length, trace


def _displacement(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError('finite nonnegative rightward displacement required')
    return value


def _edges(values):
    values = np.asarray(values, dtype=float)
    if (values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all()
            or np.any(np.diff(values) <= 0)):
        raise ValueError('finite increasing cell edges required')
    return values


def _height(relative_x, depth, length):
    return 0.0 if relative_x <= 0 else -depth*math.expm1(-relative_x/length)


def _average(function, front):
    """Integrate on [0,1], retaining tiny means without an absolute-error floor."""
    points = [front] if 0 < front < 1 else None
    with warnings.catch_warnings():
        warnings.simplefilter('error', IntegrationWarning)
        value, error = quad(function, 0., 1., points=points,
                            epsabs=0., epsrel=_QUAD_RTOL, limit=100)
    if not math.isfinite(value) or error > _QUAD_RTOL*abs(value):
        raise ArithmeticError('reference quadrature did not meet its relative error target')
    return value


def hanging_wall_means(edges_m, displacement_m, *, depth_m, decay_length_m, trace_m):
    """Cell means of H0(x-a), using split quadrature, not a cumulative primitive."""
    d, length, trace = _geometry(depth_m, decay_length_m, trace_m)
    a = _displacement(displacement_m)
    edges = _edges(edges_m)
    means = []
    for left, right in zip(edges[:-1], edges[1:]):
        width = float(right-left)
        offset = float(left-trace)-a
        means.append(_average(lambda t: _height(offset+width*t, d, length),
                              -offset/width))
    return np.asarray(means)


def footwall_means(edges_m, *, crust_thickness_m, depth_m, decay_length_m, trace_m):
    """Independent mean F=Hc0+f; stationary, never translated with hanging wall."""
    d, length, trace = _geometry(depth_m, decay_length_m, trace_m)
    crust = float(crust_thickness_m)
    if not math.isfinite(crust) or crust <= d:
        raise ValueError('crust thickness must exceed detachment depth')
    edges = _edges(edges_m)
    means = []
    for left, right in zip(edges[:-1], edges[1:]):
        width = float(right-left)
        offset = float(left-trace)
        means.append(_average(lambda t: crust-_height(offset+width*t, d, length),
                              -offset/width))
    return np.asarray(means)


def boundary_exchanges(left_m, right_m, displacement_m, *, depth_m, decay_length_m, trace_m):
    """Cumulative signed (left, right) exchange from a=0 to the supplied heave.

    Integrate H0(boundary-s) ds over displacement, independently of volume
    differences. This supports a nonzero, time-varying analytic left inflow.
    """
    d, length, trace = _geometry(depth_m, decay_length_m, trace_m)
    left, right = _edges((left_m, right_m))
    a = _displacement(displacement_m)
    if a == 0:
        return (0., 0.)
    exchanges = []
    for boundary, sign in ((left, 1.), (right, -1.)):
        offset = float(boundary-trace)
        mean = _average(lambda t: _height(offset-a*t, d, length), offset/a)
        exchanges.append(sign*a*mean)
    return tuple(exchanges)


def fault_elevation(x_m, *, depth_m, decay_length_m, trace_m):
    """Point elevation f, positive upwards, with the daylight branch explicit."""
    d, length, trace = _geometry(depth_m, decay_length_m, trace_m)
    x = np.asarray(x_m, dtype=float)
    if not np.isfinite(x).all():
        raise ValueError('finite point coordinates required')
    relative = x-trace
    result = np.zeros_like(relative)
    active = relative > 0
    result[active] = d*np.expm1(-relative[active]/length)
    return float(result) if result.ndim == 0 else result


def parcel_map(x0_m, z0_m, displacement_m, *, depth_m, decay_length_m, trace_m):
    """Unflexed hanging-wall point map (x,z); no subcell stratigraphy inferred."""
    a = _displacement(displacement_m)
    x0, z0 = np.broadcast_arrays(np.asarray(x0_m, dtype=float), np.asarray(z0_m, dtype=float))
    if not np.isfinite(x0).all() or not np.isfinite(z0).all():
        raise ValueError('finite initial parcel coordinates required')
    geometry = dict(depth_m=depth_m, decay_length_m=decay_length_m, trace_m=trace_m)
    x = x0+a
    z = z0+(fault_elevation(x, **geometry)-fault_elevation(x0, **geometry))
    return (float(x), float(z)) if x.ndim == 0 else (x, z)


def homogeneous_dilation(edges_m, thickness_m, beta):
    """Separate material-following control: x=beta*X, H=H0/beta, no flux."""
    edges = _edges(edges_m)
    h = np.asarray(thickness_m, dtype=float)
    beta = float(beta)
    if (h.shape != (len(edges)-1,) or not np.isfinite(h).all() or np.any(h < 0)
            or not math.isfinite(beta) or beta <= 0):
        raise ValueError('nonnegative cell thickness and positive finite dilation required')
    return edges*beta, h/beta
