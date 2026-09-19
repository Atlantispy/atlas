"""Independent small R4.2 physical fixtures; no Atlas operator manufactures RHS.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
import numpy as np
from atlas_tectonics import (StokesBox2D, BoussinesqMaterial, DiffusiveScales,
    reference_rheology, ThermalBoundary2D, ThermochemicalProblem, ThermochemicalState,
    PrescribedMACVelocity)


def problem(nx=8,nz=None,width=1.,height=1.,fixed=True,k=.01,heating=0.,contrast=.01,gravity=(0.,-1.)):
    b=StokesBox2D(nx,nx if nz is None else nz,width,height,'r4-2-synthetic-cartesian')
    m=BoussinesqMaterial('synthetic-constant-properties','Authored numerical control, not Earth calibration',
        1.,1.,k,.001,300.,contrast,heating,(1.,1000.))
    bc=ThermalBoundary2D('fixed-top-bottom',310.,300.) if fixed else ThermalBoundary2D('insulated')
    return ThermochemicalProblem(b,m,bc,reference_rheology('constant'),
        DiffusiveScales('test-scales',width,k,1.,300.,10.,height),gravity,'test-epoch','synthetic-heavy-constituent','test specification')


def initial(p,T=None,C=None):
    x,z=np.meshgrid(*p.box.axes())
    if T is None:T=310.-10*z/p.box.height_m+np.sin(np.pi*z/p.box.height_m)*np.cos(np.pi*x/p.box.width_m)
    if C is None:C=.4+.1*np.cos(np.pi*x/p.box.width_m)*np.cos(np.pi*z/p.box.height_m)
    return ThermochemicalState(p,np.broadcast_to(T,x.shape),np.broadcast_to(C,x.shape),time_s=0.,source='analytic initial cell averages')


def rest(p):
    b=p.box
    return PrescribedMACVelocity(b,np.zeros((b.nz,b.nx+1)),np.zeros((b.nz+1,b.nx)),source='explicit zero velocity')


def circulation(p,amplitude=.01):
    """Corner streamfunction -> flux velocities, exactly telescoping in real arithmetic."""
    b=p.box;x=np.linspace(0,b.width_m,b.nx+1);z=np.linspace(0,b.height_m,b.nz+1)
    xx,zz=np.meshgrid(x,z)
    psi=amplitude*np.sin(np.pi*xx/b.width_m)*np.sin(np.pi*zz/b.height_m)
    psi[[0,-1]]=0;psi[:,[0,-1]]=0
    return PrescribedMACVelocity(b,np.diff(psi,axis=0)/(b.height_m/b.nz),-np.diff(psi,axis=1)/(b.width_m/b.nx),source='authored corner-streamfunction circulation')


def rotation(p,omega=1.):
    """Linear rotation inside r=.35; stationary walls via a C1 outer cutoff."""
    b=p.box;x=np.linspace(0,1,b.nx+1);z=np.linspace(0,1,b.nz+1);xx,zz=np.meshgrid(x,z)
    r=np.hypot(xx-.5,zz-.5)
    psi=-.5*omega*r*r
    # Offset at r=.35 allows a smooth transition without changing inner velocity.
    a=.35;c=.47;s=np.clip((r-a)/(c-a),0,1)
    psi=(psi+.5*omega*c*c)*(1-3*s*s+2*s*s*s)
    psi[r>=c]=0;psi[[0,-1]]=0;psi[:,[0,-1]]=0
    return PrescribedMACVelocity(b,np.diff(psi,axis=0)/(b.height_m/b.nz),-np.diff(psi,axis=1)/(b.width_m/b.nx),source='authored linear interior rotation, stationary outer wall collar')


def dense_diffusion(p):
    """Independent face-pair balance matrix with half-cell boundary coefficients."""
    b=p.box;n=b.nx*b.nz;A=np.zeros((n,n));f=np.zeros(n)
    hx=b.width_m/b.nx;hz=b.height_m/b.nz;k=p.diffusivity_m2_s
    for j in range(b.nz):
        for i in range(b.nx):
            a=j*b.nx+i
            for dj,di,spacing in ((0,1,hx),(1,0,hz)):
                if j+dj<b.nz and i+di<b.nx:
                    c=(j+dj)*b.nx+i+di;r=k/spacing**2
                    A[a,a]-=r;A[c,c]-=r;A[a,c]+=r;A[c,a]+=r
            if p.boundary.kind=='fixed-top-bottom':
                for wall,temp in ((0,p.boundary.bottom_temperature_k),(b.nz-1,p.boundary.top_temperature_k)):
                    if j==wall:
                        r=2*k/hz**2;A[a,a]-=r;f[a]+=r*temp
    return A,f


def dense_upwind(p,v):
    """Independent donor-cell matrix (MC slopes vanish on the registered 2x2 grid)."""
    b=p.box;A=np.zeros((b.nx*b.nz,b.nx*b.nz));u=v.array('u_m_s');w=v.array('w_m_s')
    for j in range(b.nz):
        for i in range(1,b.nx):
            l=j*b.nx+i-1;r=l+1;speed=u[j,i]/(b.width_m/b.nx);donor=l if speed>=0 else r
            A[l,donor]-=speed;A[r,donor]+=speed
    for j in range(1,b.nz):
        for i in range(b.nx):
            lower=(j-1)*b.nx+i;upper=lower+b.nx;speed=w[j,i]/(b.height_m/b.nz);donor=lower if speed>=0 else upper
            A[lower,donor]-=speed;A[upper,donor]+=speed
    return A


def rotating_cell_averages(n,angle):
    """Independent 4x4 Gauss averages of a compact C3 bump in solid rotation."""
    nodes,weights=np.polynomial.legendre.leggauss(4)
    x,z=np.meshgrid((np.arange(n)+.5)/n,(np.arange(n)+.5)/n);out=np.zeros_like(x)
    cx=.5+.17*np.cos(angle);cz=.5+.17*np.sin(angle)
    for a,wa in zip(nodes,weights):
        for b,wb in zip(nodes,weights):
            radius=np.hypot(x+a/(2*n)-cx,z+b/(2*n)-cz)/.1
            out+=wa*wb*np.maximum(1-radius*radius,0.)**4/4
    return out


def rotation_experiment(n,duration=.5):
    """Matched-error transport verification, no alternate production time driver."""
    import math
    from atlas_tectonics._thermochemical_native import face_transfers,euler_update
    from atlas_tectonics.thermochemical_execution import _courant_arrays
    from atlas_tectonics import ThermochemicalPolicy
    p=problem(n);v=rotation(p);c=rotating_cell_averages(n,0.)
    q=np.stack((300+10*c,c));steps=math.ceil(duration*n/.12);dt=duration/steps
    cx,cz,courant,_=_courant_arrays(p.box,v.array('u_m_s'),v.array('w_m_s'),dt,ThermochemicalPolicy())
    fx=np.empty((2,n,n+1));fz=np.empty((2,n+1,n));q1=np.empty_like(q);q2=np.empty_like(q)
    for _ in range(steps):
        face_transfers(q,cx,cz,fx,fz);euler_update(q,fx,fz,q1)
        face_transfers(q1,cx,cz,fx,fz);euler_update(q1,fx,fz,q2)
        q[:]=q+.5*(q2-q)
    exact=rotating_cell_averages(n,duration)
    return dict(cells_per_axis=n,steps=steps,outgoing_courant=courant,
        mean_absolute_error=float(np.mean(abs(q[1]-exact))),minimum=float(q[1].min()),maximum=float(q[1].max()),
        volume_error=float(np.sum(q[1]-c)/n**2))


def independent_two_by_two_rhs(p,y):
    """Only four pressure cells: derive the single divergence-free circulation.

    All four normal walls are zero; continuity leaves velocity (a,-a,-a*dz/dx,
    a*dz/dx). Project body force onto this mode; its free-slip viscous eigenvalue
    is 2/dx^2+2/dz^2. This does NOT call an Atlas Stokes operator or solver.
    """
    from atlas_tectonics import PrescribedMACVelocity
    T=y[:4].reshape(2,2);C=y[4:].reshape(2,2);m=p.material;b=p.box
    rho=-m.density_kg_m3*m.expansion_per_k*(T-m.reference_temperature_k)+m.composition_density_contrast_kg_m3*C
    gx,gz=p.gravity_m_s2;hx=b.width_m/2;hz=b.height_m/2
    f=np.concatenate((rho.mean(axis=1)*gx,rho.mean(axis=0)*gz))
    g=np.array([1.,-1.,-hz/hx,hz/hx]);eigen=2/hx**2+2/hz**2
    eta=p.scales.viscosity_pa_s*dict(p.rheology.parameters)['eta']
    a=float(g@f)/(eta*eigen*(g@g));u=np.zeros((2,3));w=np.zeros((3,2))
    u[:,1]=(a,-a);w[1]=(-a*hz/hx,a*hz/hx)
    v=PrescribedMACVelocity(b,u,w,source='independent projected 2x2 circulation')
    A=dense_upwind(p,v);D,fixed=dense_diffusion(p)
    return np.concatenate((D@T.ravel()+fixed+A@T.ravel()+m.internal_heating_w_m3/p.heat_capacity_j_m3_k,A@C.ravel()))
