"""Fused binary64 variable-stress MAC action; independent checks stay in NumPy.

SPDX-License-Identifier: AGPL-3.0-only
Private inputs are validated/admitted by PreparedVariableStokes2D. Each call owns
its scratch and returns a NEW vector: SciPy may retain or mutate its previous
matvec result. No retained output/workspace alias, disk cache, parallel reduction,
fast-math, changed physical coefficient or stale numerical factor is introduced.
The gauge sum is supplied by the NumPy wrapper to retain its reduction ordering.
"""
from __future__ import annotations
import numpy as np
import numba
from numba import njit


@njit(nogil=True, fastmath=False, cache=False, error_model='numpy')
def stress_saddle(vector, eta_c, eta_v, hx, hz, c, pressure_sum):
    """Apply [A G 0; G.T 0 c; 0 c.T 0] on eliminated free-slip faces.

    A is -div(2 eta e), not eta times a vector Laplacian. Normal stresses are
    centred, shear is at interior vertices, normal wall velocity and wall shear
    traction are zero. Operations retain the reference stencil's association;
    divergence separately retains face-division/addition ordering. These local
    arrays are covered by the existing conservative per-solve scratch allowance.
    """
    nz, nx = eta_c.shape
    nu = nz * (nx - 1)
    nv = nu + (nz - 1) * nx
    n = nv + nz * nx + 1
    xx = np.empty((nz, nx), dtype=np.float64)
    zz = np.empty((nz, nx), dtype=np.float64)
    shear = np.empty((nz - 1, nx - 1), dtype=np.float64)
    out = np.empty(n, dtype=np.float64)
    for j in range(nz):
        for i in range(nx):
            left = vector[j * (nx - 1) + i - 1] if i > 0 else 0.0
            right = vector[j * (nx - 1) + i] if i < nx - 1 else 0.0
            bottom = vector[nu + (j - 1) * nx + i] if j > 0 else 0.0
            top = vector[nu + j * nx + i] if j < nz - 1 else 0.0
            xx[j, i] = (2.0 * eta_c[j, i]) * ((right - left) / hx)
            zz[j, i] = (2.0 * eta_c[j, i]) * ((top - bottom) / hz)
            # Do not substitute (right-left)/hx: the old continuity equation
            # divides each face first, then accumulates x before z.
            div = 0.0
            if i < nx - 1:
                div += right / hx
            if i > 0:
                div -= left / hx
            if j < nz - 1:
                div += top / hz
            if j > 0:
                div -= bottom / hz
            out[nv + j * nx + i] = -div + c * vector[n - 1]
    for j in range(nz - 1):
        for i in range(nx - 1):
            du = (vector[(j + 1) * (nx - 1) + i] - vector[j * (nx - 1) + i]) / hz
            dw = (vector[nu + j * nx + i + 1] - vector[nu + j * nx + i]) / hx
            shear[j, i] = eta_v[j, i] * (du + dw)
    for j in range(nz):
        for i in range(nx - 1):
            value = -(xx[j, i + 1] - xx[j, i]) / hx
            if j == 0:
                value -= shear[0, i] / hz
            elif j == nz - 1:
                value += shear[j - 1, i] / hz
            else:
                value -= (shear[j, i] - shear[j - 1, i]) / hz
            value += (vector[nv + j * nx + i + 1] - vector[nv + j * nx + i]) / hx
            out[j * (nx - 1) + i] = value
    for j in range(nz - 1):
        for i in range(nx):
            value = -(zz[j + 1, i] - zz[j, i]) / hz
            if i == 0:
                value -= shear[j, 0] / hx
            elif i == nx - 1:
                value += shear[j, i - 1] / hx
            else:
                value -= (shear[j, i] - shear[j, i - 1]) / hx
            value += (vector[nv + (j + 1) * nx + i] - vector[nv + j * nx + i]) / hz
            out[nu + j * nx + i] = value
    out[n - 1] = c * pressure_sum
    return out


@njit(nogil=True, fastmath=False, cache=False, error_model='numpy')
def weighted_velocity_data(term_indptr, term_component, term_coefficient, term_left, term_right,
                           eta_c, eta_v, centre_count, nnz):
    """Fill fixed CSC velocity-block values with legacy operation grouping.

    The symbolic term tables depend only on geometry.  Contributions are grouped
    as the previous SciPy products were: Bx, then Bz, then shear.  Within each
    component the original derivative-product association is retained.  This
    preserves the predecessor matrix values while avoiding repeated sparse
    structure discovery.  Current viscosity is read on every call and only fresh
    numerical data is returned.
    """
    out = np.zeros(nnz, dtype=np.float64)
    centre = eta_c.reshape(eta_c.size)
    vertex = eta_v.reshape(eta_v.size)
    for entry in range(nnz):
        x_value = 0.0
        z_value = 0.0
        shear_value = 0.0
        for k in range(term_indptr[entry], term_indptr[entry + 1]):
            coefficient = term_coefficient[k]
            if coefficient < centre_count:
                value = term_left[k] * (term_right[k] * (2.0 * centre[coefficient]))
            else:
                value = term_left[k] * (term_right[k] * vertex[coefficient - centre_count])
            component = term_component[k]
            if component == 0:
                x_value += value
            elif component == 1:
                z_value += value
            else:
                shear_value += value
        out[entry] = (x_value + z_value) + shear_value
    return out


def prepare():
    """Compile a tiny, declared signature during preparation, never from a cache.

    Compilation may finish before a pending cooperative cancellation is observed.
    Compiler/runtime memory is separate interpreter headroom, not array admission.
    """
    if numba.__version__ != '0.65.1' or numba.config.DISABLE_JIT:
        raise ImportError('compiled mechanics requires enabled numba==0.65.1; no fallback')
    stress_saddle(np.zeros(9), np.ones((2, 2)), np.ones((1, 1)), 0.5, 0.5, 0.5, 0.0)
    weighted_velocity_data(np.array([0, 1], dtype=np.int32), np.zeros(1, dtype=np.uint8),
                           np.zeros(1, dtype=np.int32), np.ones(1), np.ones(1),
                           np.ones((1, 1)), np.ones((1, 1)), 1, 1)
