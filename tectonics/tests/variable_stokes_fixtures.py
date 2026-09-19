"""Independent R4.3 analytic controls; never form force by probing Atlas K*x.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
import numpy as np
from atlas_tectonics import (StokesBox2D, DiffusiveScales, reference_rheology,
                            NonlinearStokesPolicy, PreparedVariableStokes2D)
from stokes_fixtures import unit_box, unit_scales, request, errors


def analytic_variable(box, *, beta=1.3, gamma=-.4, amplitude=.04, pressure=.3):
    """u=curl(psi), psi=A sin(pi*x/W)sin(pi*z/H), eta=exp(beta*x/W+gamma*z/H).

    f=grad(p)-div(2 eta e). The separate coefficient-gradient terms below
    distinguish full variable stress from the incorrect eta*velocity-Laplacian.
    All physical coefficients are nondimensional SI controls, not mantle fits.
    """
    kx=np.pi/box.width_m;kz=np.pi/box.height_m
    a=2*kx;b=kz
    def field(x,z):
        eta=np.exp(beta*x/box.width_m+gamma*z/box.height_m)
        u=amplitude*kz*np.sin(kx*x)*np.cos(kz*z)
        w=-amplitude*kx*np.cos(kx*x)*np.sin(kz*z)
        ex=amplitude*kx*kz*np.cos(kx*x)*np.cos(kz*z)
        ez=-ex;shear=amplitude*(kx*kx-kz*kz)*np.sin(kx*x)*np.sin(kz*z)
        etax=eta*beta/box.width_m;etaz=eta*gamma/box.height_m
        fx=eta*(kx*kx+kz*kz)*u-2*etax*ex-etaz*shear-pressure*a*np.sin(a*x)*np.cos(b*z)
        fz=eta*(kx*kx+kz*kz)*w-etax*shear-2*etaz*ez-pressure*b*np.cos(a*x)*np.sin(b*z)
        return eta,u,w,fx,fz
    xp,zp=np.meshgrid(*box.axes());xu,zu=np.meshgrid(*box.axes('force_x'));xw,zw=np.meshgrid(*box.axes('force_z'))
    xv,zv=np.meshgrid(np.arange(1,box.nx)*box.width_m/box.nx,np.arange(1,box.nz)*box.height_m/box.nz)
    c=field(xp,zp)[0];v=field(xv,zv)[0]
    _,u,_,fx,_=field(xu,zu);_,_,w,_,fz=field(xw,zw)
    p=pressure*np.cos(a*xp)*np.cos(b*zp)
    return fx,fz,c,v,u,w,p


def refinement(n):
    box=unit_box(2*n,n,2.,1.);vals=analytic_variable(box)
    with PreparedVariableStokes2D(box,unit_scales()) as s:r=s.solve(*vals[:4],**request(box))
    return dict(n=n,**errors(r,(vals[0],vals[1],*vals[4:])),
                linear_iterations=r.descriptor()['nonlinear_history'][0]['linear_iterations'])


def forcing(n=12,amplitude=.02,key='tosi-2'):
    b=unit_box(n);x,z=np.meshgrid(*b.axes());T=2-z+amplitude*np.cos(np.pi*x)*np.sin(np.pi*z)
    fx=np.zeros((n,n-1));fz=100*(.5*(T[:-1]+T[1:])-1.)
    return b,unit_scales(),fx,fz,T,reference_rheology(key)


def two_cell_solution(force=1.,temperature=1.6,*,relaxation=1.):
    b=unit_box(2);fx=force*np.array([[1.],[-1.]]);fz=force*np.array([[-1.,1.]])
    p=NonlinearStokesPolicy(relaxation=relaxation)
    with PreparedVariableStokes2D(b,unit_scales(),policy=p) as s:
        r=s.solve_rheology(fx,fz,np.full((2,2),temperature),reference_rheology('tosi-2'),**request(b))
    return r


def independent_two_cell_amplitude(force,temperature):
    """Continuity leaves (a,-a,-a,a); strain invariant is 2|a|.

    Project the stress balance onto that circulation. eta_star > 0 ensures the
    regularised Tosi relation is monotone. No Atlas law or operator is evaluated.
    """
    import math
    from scipy.optimize import brentq
    eta_linear=math.exp(-math.log(1e5)*(temperature-1.))
    def residual(a):
        q=math.sqrt(2.)*2*abs(a)
        inverse_plastic=q/(.001*q+1.)
        eta=2*eta_linear/(1+eta_linear*inverse_plastic)
        return 16*eta*a-abs(force)
    if force==0:return 0.
    hi=max(1.,abs(force)*1e6)
    a=brentq(residual,0.,hi,xtol=1e-13,rtol=1e-14)
    return math.copysign(a,force)


def coupled_problem(n=6,key='tosi-2'):
    from thermochemical_fixtures import problem
    return replace(problem(n),rheology=reference_rheology(key),mechanical_mode='variable-r4.3')


def independent_nonlinear_two_cell_rhs(problem,y):
    """Analytical continuity reduction + independent scalar root, not Atlas Stokes.

    The four pressure cells leave one circulation. For a unit box its work
    equation is 16*a*sum(eta_i(a))=g dot force, with engineering shear zero at
    the only interior vertex. Thus differing centre temperatures/viscosities
    still give a scalar root. The retained independent donor/heat matrices
    complete the eight-variable continuous-time semidiscrete ODE.
    """
    import math
    from scipy.optimize import brentq
    from thermochemical_fixtures import dense_upwind,dense_diffusion
    from atlas_tectonics import PrescribedMACVelocity
    b=problem.box;m=problem.material;s=problem.scales
    if b.nx!=2 or b.nz!=2 or b.width_m!=1. or b.height_m!=1. or problem.rheology.name!='tosi-2-constitutive-v1':
        raise ValueError('independent oracle is specifically unit-square Tosi case 2')
    T=y[:4].reshape(2,2);C=y[4:].reshape(2,2)
    rho=-m.density_kg_m3*m.expansion_per_k*(T-m.reference_temperature_k)+m.composition_density_contrast_kg_m3*C
    gx,gz=problem.gravity_m_s2;f=np.r_[rho.mean(axis=1)*gx,rho.mean(axis=0)*gz];g=np.array([1.,-1.,-1.,1.])
    projection=float(g@f)
    linear=np.exp(-math.log(1e5)*(T.ravel()-s.surface_temperature_k)/s.temperature_scale_k)
    def residual(a):
        q=math.sqrt(2.)*2*a*s.time_s
        invp=q/(.001*q+1.)
        eta=2*linear/(1+linear*invp)*s.viscosity_pa_s
        return 16*a*eta.sum()-abs(projection)
    amplitude=0. if projection==0 else math.copysign(brentq(residual,0.,max(1.,abs(projection)*1e7),xtol=1e-14,rtol=1e-14),projection)
    u=np.zeros((2,3));w=np.zeros((3,2));u[:,1]=(amplitude,-amplitude);w[1]=(-amplitude,amplitude)
    v=PrescribedMACVelocity(b,u,w,source='independent variable-viscosity scalar root')
    A=dense_upwind(problem,v);D,fixed=dense_diffusion(problem)
    return np.r_[D@T.ravel()+fixed+A@T.ravel()+m.internal_heating_w_m3/problem.heat_capacity_j_m3_k,A@C.ravel()]
