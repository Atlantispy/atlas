"""Analytical R4.1 fixtures: continuous derivatives, never discrete operator RHS.
SPDX-License-Identifier: AGPL-3.0-only
"""
import numpy as np
from atlas_tectonics import StokesBox2D, DiffusiveScales, reference_rheology


def unit_box(nx=12,nz=None,width=1.,height=1.):
    return StokesBox2D(nx,nx if nz is None else nz,width,height,'r4-cartesian-x-right-z-up')


def unit_scales():
    return DiffusiveScales('analytical-SI-unit-scales',1.,1.,1.,1.,1.,1.)


def request(box):
    return dict(frame_id=box.frame_id,epoch_id='manufactured-steady-epoch',time_s=0.,
                source='Independent analytic free-slip trigonometric solution; synthetic verification')


def analytic(box,*,viscosity=1.,amplitude=.05,pressure=.3,m=1,n=1,pm=2,pn=1):
    """psi=A sin(kx*x)sin(kz*z); u=psi_z, w=-psi_x. p is separate.

    f=-eta*laplacian(v)+grad(p). These derivatives are analytical; no assembly
    or discrete gradients from the implementation are used to build f.
    """
    xu,zu=np.meshgrid(*box.axes('force_x'))
    xw,zw=np.meshgrid(*box.axes('force_z'))
    xp,zp=np.meshgrid(*box.axes('pressure'))
    kx=m*np.pi/box.width_m;kz=n*np.pi/box.height_m
    a=pm*np.pi/box.width_m;b=pn*np.pi/box.height_m
    u=amplitude*kz*np.sin(kx*xu)*np.cos(kz*zu)
    w=-amplitude*kx*np.cos(kx*xw)*np.sin(kz*zw)
    p=pressure*np.cos(a*xp)*np.cos(b*zp)
    fx=viscosity*(kx*kx+kz*kz)*u-pressure*a*np.sin(a*xu)*np.cos(b*zu)
    fz=viscosity*(kx*kx+kz*kz)*w-pressure*b*np.cos(a*xw)*np.sin(b*zw)
    return fx,fz,u,w,p


def errors(result,analytic_values):
    _,_,u,w,p=analytic_values
    return dict(u_l2=float(np.sqrt(np.mean((result.array('u_m_s')[:,1:-1]-u)**2))),
                w_l2=float(np.sqrt(np.mean((result.array('w_m_s')[1:-1]-w)**2))),
                p_l2=float(np.sqrt(np.mean((result.array('pressure_pa')-p)**2))))
