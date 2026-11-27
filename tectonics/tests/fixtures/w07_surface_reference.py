"""Independent finite-depth linearised B09 references; no Atlas imports.

SPDX-License-Identifier: AGPL-3.0-only
"""
import math
import numpy as np


def decay_rate(k,height,eta=1.,rho_g=1.):
    q=k*height
    if q<.01:
        numerator=sum((2*q)**n/math.factorial(n) for n in range(3,18,2))
        denominator=math.cosh(2*q)+1+2*q*q
        ratio=numerator/denominator
    else:
        a=math.exp(-2*q)
        ratio=(1-a*a-4*q*a)/(1+a*a+2*a+4*q*q*a)
    return rho_g*ratio/(2*eta*k)


def traction_bvp_rate(k,H,eta=1.,rho_g=1.):
    """Solve biharmonic vertical modes with bottom w=w'=0, top shear=0.

    Normal traction eta*(3w'-w'''/k²)=-rho_g for unit top amplitude.
    Uses independent hyperbolic basis, not the closed decay expression.
    """
    s,c=math.sinh(k*H),math.cosh(k*H)
    v=np.array([s-k*H*c,H*s]);d=np.array([-k*k*H*s,s+k*H*c])
    dd=np.array([-k*k*s-k**3*H*c,2*k*c+k*k*H*s])
    ddd=np.array([-2*k**3*c-k**4*H*s,3*k*k*s+k**3*H*c])
    coeff=np.linalg.solve(np.array([dd+k*k*v,eta*(3*d-ddd/k**2)]),[0.,-rho_g])
    return -float(v@coeff)
