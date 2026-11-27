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
def face_transfers(q, cx, cz, fx, fz, temperature_walls=None):
    """Bounded MC reconstruction with zero material flux through every wall.

    Optional bottom/top Dirichlet values reconstruct field 0 (temperature) at
    vertical boundary cells using reflected ghosts. The slope is also limited
    by the reflected-wall jump: the extrapolated wall state cannot overshoot
    the supplied wall value. This retains exact linear reconstruction without
    relying on a reflected ghost being inside the physical temperature range.
    Insulated walls, sidewalls and composition retain zero boundary slopes.

    Each interior-face reconstruction lies between adjacent cell averages. Thus
    q_face <= 2*q_cell and 1-q_face <= 2*(1-q_cell) for bounded fractions.
    sum(outgoing Courant) <= 1/2 is a sufficient multidimensional Euler bound
    for both q and its complement when the MAC velocity is divergence-free.
    The wall-limited thermal slopes give the same bound relative to the range
    containing the input temperatures and supplied wall values.
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
                elif a == 0 and temperature_walls is not None:
                    if donor == 0:
                        wall_jump = 2.0*(q[a,0,i]-temperature_walls[0])
                        slope = _mc(wall_jump, q[a,1,i]-q[a,0,i])
                    else:
                        wall_jump = 2.0*(temperature_walls[1]-q[a,-1,i])
                        slope = _mc(q[a,-1,i]-q[a,-2,i], wall_jump)
                    slope = math.copysign(min(abs(slope), abs(wall_jump)), slope)
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
