"""W07 continuous oracles, derived without either discrete operator.

SPDX-License-Identifier: AGPL-3.0-only
Synthetic unit scales; x-right/z-up. No geological parameter defaults.
"""
from __future__ import annotations

import numpy as np


def dimensions(case):
    if case in ('hydrostatic', 'hydrostatic_traction'):
        return 2., 3.
    if case in ('extension', 'translated_extension'):
        return 2., 1.
    if case in ('vortex', 'couette', 'free_slip', 'rotation'):
        return 1., 1.
    raise ValueError('unknown W07 continuous case')


def fields(case, x, z):
    """Return (u,w,p,fx,fz,Dxx,Dzz,Dxz), all continuous point values."""
    x, z = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(z, dtype=float))
    zero = np.zeros_like(x)
    if case in ('hydrostatic', 'hydrostatic_traction'):
        p = -7.*(z-1.5) if case == 'hydrostatic' else 2.+7.*(3.-z)
        return zero, zero, p, zero, zero-7., zero, zero, zero
    if case in ('extension', 'translated_extension'):
        du, dw = (0., 0.) if case == 'extension' else (.3, -.2)
        return x-1.+du, -(z-.5)+dw, zero, zero, zero, zero+1., zero-1., zero
    if case == 'couette':
        return z, zero, zero+2., zero, zero, zero, zero, zero+.5
    if case == 'rotation':
        return -(z-.5), x-.5, zero, zero, zero, zero, zero, zero
    if case == 'vortex':
        def a(s): return s*s*(1.-s)**2
        def d(s): return 2.*s-6.*s*s+4.*s**3
        def dd(s): return 2.-12.*s+12.*s*s
        def ddd(s): return -12.+24.*s
        u, w = a(x)*d(z), -d(x)*a(z)
        return (u, w, x**3+z**3-.5,
                3.*x*x-dd(x)*d(z)-a(x)*ddd(z),
                3.*z*z+ddd(x)*a(z)+d(x)*dd(z),
                d(x)*d(z), -d(x)*d(z), .5*(a(x)*dd(z)-dd(x)*a(z)))
    if case == 'free_slip':
        k = np.pi
        u, w = .05*k*np.sin(k*x)*np.cos(k*z), -.05*k*np.cos(k*x)*np.sin(k*z)
        p = .3*np.cos(2*k*x)*np.cos(k*z)
        dxx = .05*k*k*np.cos(k*x)*np.cos(k*z)
        return (u, w, p, 2*k*k*u-.6*k*np.sin(2*k*x)*np.cos(k*z),
                2*k*k*w-.3*k*np.cos(2*k*x)*np.sin(k*z), dxx, -dxx, zero)
    raise ValueError('unknown W07 continuous case')


def body_force(case):
    return lambda x, z: fields(case, x, z)[3:5]


def boundaries(case):
    """Complete side/component declarations with physical outward traction."""
    result = {side: {'u': ('velocity', lambda x, z: fields(case, x, z)[0]),
                     'w': ('velocity', lambda x, z: fields(case, x, z)[1])}
              for side in ('left', 'right', 'bottom', 'top')}
    if case in ('hydrostatic', 'free_slip'):
        for side in ('left', 'right'):
            result[side]['w'] = ('traction', 0.)
        for side in ('bottom', 'top'):
            result[side]['u'] = ('traction', 0.)
    elif case in ('couette', 'hydrostatic_traction'):
        result['top'] = {'u': ('traction', 1. if case == 'couette' else 0.),
                         'w': ('traction', -2.)}
    return result


def quadrature(width, height, cells=32, order=3):
    """Independent tensor Gauss points/weights on a common evaluation partition."""
    q, v = np.polynomial.legendre.leggauss(order)
    x = ((np.arange(cells)[:, None]+.5+.5*q[None, :])*width/cells).ravel()
    z = ((np.arange(cells)[:, None]+.5+.5*q[None, :])*height/cells).ravel()
    wx = np.tile(v*.5*width/cells, cells)
    wz = np.tile(v*.5*height/cells, cells)
    xx, zz = np.meshgrid(x, z)
    return np.column_stack((xx.ravel(), zz.ravel())), np.outer(wz, wx).ravel()


def continuum_errors(case, points, weights, sampled):
    exact = fields(case, points[:, 0], points[:, 1])
    result = {}
    for name, target in zip(('u', 'w', 'p'), exact[:3]):
        difference = np.asarray(sampled[name])-target
        norm = float(np.sum(weights*target**2))
        error = float(np.sqrt(np.sum(weights*difference**2)))
        result[name+'_l2'] = error
        result[name+'_relative_l2'] = error/np.sqrt(norm) if norm > 0 else error/np.sqrt(np.sum(weights))
    numerator = sum(np.sum(weights*(np.asarray(sampled[key])-target)**2)
                    for key, target in zip(('u', 'w'), exact[:2]))
    denominator = sum(np.sum(weights*target**2) for target in exact[:2])
    result['velocity_relative_l2'] = float(np.sqrt(numerator/(denominator if denominator else np.sum(weights))))
    return result
