"""R4.2 fused finite-volume face transport; no fast-math or disk JIT cache.

SPDX-License-Identifier: AGPL-3.0-only
Each oriented shared face is evaluated once and contributes with opposite signs
in adjacent cells. q holds temperature and a binary composition fraction. Face
Courant numbers already contain dt/dx or dt/dz, avoiding a potentially enormous
physical flux intermediate. Two-dimensional work is unsplit, not two 1D sweeps.
"""
from __future__ import annotations
import math
import numpy as np
from numba import njit


@njit(inline='always', fastmath=False, cache=False)
def _mc(left, right):
    if left > 0.0 and right > 0.0:
        return min(2.0*left, 0.5*left+0.5*right, 2.0*right)
    if left < 0.0 and right < 0.0:
        return -min(-2.0*left, -0.5*left-0.5*right, -2.0*right)
    return 0.0


@njit(nogil=True, fastmath=False, cache=False)
def face_transfers(q, cx, cz, fx, fz):
    """MC reconstruction with zero boundary-cell normal slopes; zero wall flux.

    Each reconstruction is between its two neighbouring cell averages. Thus
    q_face <= 2*q_cell and 1-q_face <= 2*(1-q_cell) for bounded fractions.
    sum(outgoing Courant) <= 1/2 is a sufficient multidimensional Euler bound
    for both q and its complement when the MAC velocity is divergence-free.
    There is no post-update clipping, mass renormalisation or first-order fallback.
    """
    nf, nz, nx = q.shape
    fx.fill(0.0); fz.fill(0.0)
    for a in range(nf):
        for j in range(nz):
            for i in range(1, nx):
                donor = i-1 if cx[j,i] >= 0.0 else i
                slope = 0.0
                if 0 < donor < nx-1:
                    slope = _mc(q[a,j,donor]-q[a,j,donor-1], q[a,j,donor+1]-q[a,j,donor])
                value = q[a,j,donor] + (0.5*slope if cx[j,i] >= 0.0 else -0.5*slope)
                fx[a,j,i] = cx[j,i]*value
        for j in range(1, nz):
            for i in range(nx):
                donor = j-1 if cz[j,i] >= 0.0 else j
                slope = 0.0
                if 0 < donor < nz-1:
                    slope = _mc(q[a,donor,i]-q[a,donor-1,i], q[a,donor+1,i]-q[a,donor,i])
                value = q[a,donor,i] + (0.5*slope if cz[j,i] >= 0.0 else -0.5*slope)
                fz[a,j,i] = cz[j,i]*value


@njit(nogil=True, fastmath=False, cache=False)
def euler_update(q, fx, fz, out):
    for a in range(q.shape[0]):
        for j in range(q.shape[1]):
            for i in range(q.shape[2]):
                out[a,j,i] = q[a,j,i] + (fx[a,j,i]-fx[a,j,i+1]) + (fz[a,j,i]-fz[a,j+1,i])


@njit(nogil=True, fastmath=False, cache=False)
def sum_compensated(a):
    """Deterministic Neumaier sum; no parallel reduction order or dense history."""
    total=0.0; correction=0.0
    for value in a.flat:
        new=total+value
        if abs(total)>=abs(value): correction+=(total-new)+value
        else: correction+=(value-new)+total
        total=new
    return total+correction
