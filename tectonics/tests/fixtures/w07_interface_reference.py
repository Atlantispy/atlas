"""Independent continuum references, not a discrete Stokes operator.

ASPECT v3.0.0 solcx.h uses rho=-sin(pi*z)*cos(pi*x); its manual and
Atlas frozen Step1 instead state rho=sin(pi*x)*cos(pi*z). Both are named
explicitly here. No generated third-party solution implementation is copied.
For psi=phi(x)sin(k*z): eta*(d_x^2-k^2)^2 phi=g'(x), f_z=g(x)sin(k*z).
Eight boundary/interface equations determine each mode's homogeneous terms.
"""
from functools import lru_cache
import math
import numpy as np


def layered_velocity(z, interface=.37, lower=1., upper=1000.):
    z=np.asarray(z)
    tau=1./(interface/lower+(1-interface)/upper)
    return tau*(np.minimum(z,interface)/lower+np.maximum(z-interface,0)/upper)


def layered_sites(nx,nz,interface=.37,lower=1.,upper=1000.):
    """Exact series compliance over each vertical shear dual interval.

    Normal coefficients are exact point values: their strain vanishes in this
    reference, so they do not stand in for an unspecified general mixture law.
    """
    zc=(np.arange(nz)+.5)/nz
    zv=np.arange(nz+1)/nz
    lo=np.maximum(0.,zv-.5/nz); hi=np.minimum(1.,zv+.5/nz)
    below=np.maximum(0.,np.minimum(hi,interface)-lo)
    compliance=below/lower+(hi-lo-below)/upper
    return (np.broadcast_to(np.where(zc[:,None]<interface,lower,upper),(nz,nx)).copy(),
            np.broadcast_to(((hi-lo)/compliance)[:,None],(nz+1,nx+1)).copy())


def _basis(x,lo,hi,k,d):
    # Stable exp(-k*distance) basis and its exact derivatives; never exp(+k).
    x=np.asarray(x)
    out=[]
    for t,sgn in ((x-lo,1.),(hi-x,-1.)):
        e=np.exp(-k*t); a=(-k)**d
        out.extend((sgn**d*a*e,
                    sgn**d*(a*t+(d*(-k)**(d-1) if d else 0.))*e))
    return np.stack(out,axis=-1)


def _g(x,d,variant,n):
    p=np.pi
    if variant=='aspect-source':
        return p**d*np.cos(p*np.asarray(x)+d*p/2)
    b=4*n/(p*(n*n-1))
    return -b*p**d*np.sin(p*np.asarray(x)+d*p/2)


@lru_cache(maxsize=520)
def _mode(variant,n,jump,interface):
    k=n*np.pi
    def values(side,x,d):
        eta=1. if side==0 else jump
        lo,hi=(0.,interface) if side==0 else (interface,1.)
        return _basis(x,lo,hi,k,d),_g(x,d+1,variant,n)/(eta*(np.pi**2+k*k)**2)
    rows=[]; rhs=[]
    def equation(terms):
        row=np.zeros(8); known=0.
        for side,x,d,scale in terms:
            basis,particular=values(side,x,d)
            row[4*side:4*side+4]+=scale*basis
            known+=scale*particular
        scale=np.max(np.abs(row))
        rows.append(row/scale);rhs.append(-known/scale)
    for side,x in ((0,0.),(1,1.)):
        equation([(side,x,0,1.)]);equation([(side,x,2,1.)])
    for d in (0,1):equation([(0,interface,d,1.),(1,interface,d,-1.)])
    # Full shear and normal traction continuity, not eta*velocity gradients.
    equation([(0,interface,2,1.),(0,interface,0,k*k),
              (1,interface,2,-jump),(1,interface,0,-jump*k*k)])
    equation([(0,interface,3,1.),(0,interface,1,-3*k*k),
              (1,interface,3,-jump),(1,interface,1,3*jump*k*k)])
    matrix=np.asarray(rows);target=np.asarray(rhs)
    coeff=np.linalg.solve(matrix,target)
    if np.max(np.abs(matrix@coeff-target))>1e-12:
        raise ArithmeticError('independent interface solve residual')
    return tuple(coeff)


def mode_derivatives(x, *,variant='aspect-source',n=1,jump=1e6,interface=.5,side=None):
    x=np.asarray(x,dtype=float)
    coeff=np.asarray(_mode(variant,n,float(jump),float(interface)))
    k=n*np.pi; right=(x>interface) if side is None else np.full(x.shape,bool(side))
    eta=np.where(right,jump,1.)
    values=[]
    for d in range(5):
        left=_basis(np.clip(x,0.,interface),0.,interface,k,d)@coeff[:4]
        right_value=_basis(np.clip(x,interface,1.),interface,1.,k,d)@coeff[4:]
        values.append(np.where(right,right_value,left)+_g(x,d+1,variant,n)/(eta*(np.pi**2+k*k)**2))
    return values,eta


def interface_fields(x,z, *,variant='aspect-source',modes=128,jump=1e6,interface=.5):
    """Return u,w,p,fx,fz,exx,ezz,exz,txx,tzz,txz on broadcast points.

    Frozen-manual Fourier truncation is explicit and checked independently;
    the actual ASPECT-source solution has exactly one mode.
    """
    if variant not in ('aspect-source','frozen-manual'):
        raise ValueError('named reference variant required')
    x,z=np.broadcast_arrays(np.asarray(x,float),np.asarray(z,float))
    if np.any((x<0)|(x>1)|(z<0)|(z>1)) or not np.isfinite(x+z).all():
        raise ValueError('unit-box finite reference points required')
    if type(modes) is not int or not 1<=modes<=256:
        raise ValueError('at most256 Fourier modes')
    out=[np.zeros_like(x) for _ in range(11)]
    for n in ((1,) if variant=='aspect-source' else range(2,2*modes+1,2)):
        k=n*np.pi; (phi,d1,d2,d3,_),eta=mode_derivatives(x,variant=variant,n=n,jump=jump,interface=interface)
        s,c=np.sin(k*z),np.cos(k*z)
        u=k*phi*c; w=-d1*s
        # Sum the slow Fourier antiderivative of the manual's body-force term
        # analytically; only the rapidly decaying mechanical part is truncated.
        pressure=(eta*(d3-k*k*d1)-(0. if variant=='frozen-manual' else _g(x,0,variant,n)))*c/k
        exx=k*d1*c; exz=-(d2+k*k*phi)*s/2
        values=(u,w,pressure,0.,0.,exx,-exx,exz,2*eta*exx,-2*eta*exx,2*eta*exz)
        for target,value in zip(out,values):target+=value
    out[4][...]=np.cos(np.pi*x)*np.sin(np.pi*z) if variant=='aspect-source' else -np.sin(np.pi*x)*np.cos(np.pi*z)
    if variant=='frozen-manual':
        out[2]+=np.sin(np.pi*x)*(-np.sin(np.pi*z)/np.pi+2/np.pi**2)
    return tuple(out)


def interface_sites(nx,nz, *,jump=1e6,interface=.5):
    """Declared aligned discontinuous coefficient: centre point, shear series.

    At shear vertices take the exact horizontal compliance integral over the
    dual interval; this is a declared interface representation, not a universal
    phase-mixture rule. Unaligned meshes need separate error evidence.
    """
    xc=(np.arange(nx)+.5)/nx; xv=np.arange(nx+1)/nx
    lo=np.maximum(0.,xv-.5/nx);hi=np.minimum(1.,xv+.5/nx)
    left=np.maximum(0.,np.minimum(hi,interface)-lo)
    ev=(hi-lo)/(left+(hi-lo-left)/jump)
    return np.broadcast_to(np.where(xc<=interface,1.,jump),(nz,nx)).copy(),np.broadcast_to(ev,(nz+1,nx+1)).copy()
