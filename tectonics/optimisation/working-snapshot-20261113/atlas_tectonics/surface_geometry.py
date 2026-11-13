"""Conservative Q2 graph ALE; contract: docs/W07_SURFACE_STRENGTH.md.
SPDX-License-Identifier: AGPL-3.0-only
"""
import numpy as np

from ._validation import TectonicsError, scalar, input_shape, read_array, frozen


def _banded_solvers():
    try:
        from scipy.linalg import cholesky_banded, cho_solve_banded
    except ImportError as exc:
        raise TectonicsError('scipy backend unavailable for surface projection') from exc
    return cholesky_banded, cho_solve_banded


def q2(q):
    q=np.asarray(q,dtype=float)
    return np.stack((.5*q*(q-1),1-q*q,.5*q*(q+1)),axis=-1)


def dq2(q):
    q=np.asarray(q,dtype=float)
    return np.stack((q-.5,-2*q,q+.5),axis=-1)


def graph_mesh(width_m,bottom_m,surface_m,nz):
    width=scalar(width_m,'width',positive=True);bottom=scalar(bottom_m,'bottom')
    shape=input_shape(surface_m)
    if len(shape)!=1 or shape[0]<5 or shape[0]>129 or shape[0]%2!=1:
        raise TectonicsError('surface requires 2*nx+1 Q2 nodes, nx=2..64')
    if type(nz) is not int or not 2<=nz<=64:
        raise TectonicsError('nz must be 2..64')
    h=read_array(surface_m,'surface elevation')
    if np.any(h<=bottom):raise TectonicsError('surface must stay above the bottom')
    x=np.broadcast_to(np.linspace(0.,width,shape[0]),(2*nz+1,shape[0]))
    z=bottom+np.linspace(0.,1.,2*nz+1)[:,None]*(h[None]-bottom)
    return frozen(np.stack((x,z),axis=-1))


def elements(mesh):
    """Bound and gather Q2 cells; callers already hold their workspace budget."""
    shape=input_shape(mesh)
    if (len(shape)!=3 or shape[-1]!=2 or any(s<5 or s>129 or s%2!=1 for s in shape[:2])):
        raise TectonicsError('Q2 mesh requires odd 5..129 node dimensions and x,z')
    mesh=read_array(mesh,'physical Q2 mesh')
    nz,nx=(shape[0]-1)//2,(shape[1]-1)//2
    ids=(2*np.arange(nz)[:,None,None,None]+np.arange(3)[None,None,:,None])*shape[1]
    ids=ids+(2*np.arange(nx)[None,:,None,None]+np.arange(3)[None,None,None,:])
    return mesh.reshape(-1,2)[ids],ids


def cell_volume_and_flux(mesh,velocity=None,*,order=5):
    """Green area/flux, independent of mechanics; faces left,right,bottom,top."""
    if type(order) is not int or not 3<=order<=6:raise TectonicsError('bounded face quadrature required')
    cell,ids=elements(mesh)
    q,w=np.polynomial.legendre.leggauss(order);N,dN=q2(q),dq2(q)
    if velocity is not None:
        if input_shape(velocity)!=input_shape(mesh):raise TectonicsError('nodal velocity support mismatch')
        v=read_array(velocity,'nodal physical or mesh velocity').reshape(-1,2)[ids]
    area=np.zeros(cell.shape[:2]);flux=np.zeros((*cell.shape[:2],4))
    edges=(cell[:,:, :,0,:],cell[:,:,:,2,:],cell[:,:,0,:,:],cell[:,:,2,:,:])
    vedges=None if velocity is None else (v[:,:,:,0,:],v[:,:,:,2,:],v[:,:,0,:,:],v[:,:,2,:,:])
    for side,(edge,sign) in enumerate(zip(edges,(-1.,1.,-1.,1.))):
        position=np.einsum('qa,...ac->...qc',N,edge)
        tangent=np.einsum('qa,...ac->...qc',dN,edge)
        normal=(np.stack((tangent[...,1],-tangent[...,0]),axis=-1) if side<2 else
                np.stack((-tangent[...,1],tangent[...,0]),axis=-1))*sign
        area += .5*np.einsum('...qc,...qc,q->...',position,normal,w)
        if velocity is not None:
            value=np.einsum('qa,...ac->...qc',N,vedges[side])
            flux[...,side]=np.einsum('...qc,...qc,q->...',value,normal,w)
    if not np.isfinite(area).all() or np.any(area<=0.):raise TectonicsError('nonpositive physical cell volume')
    if not np.isfinite(flux).all():raise TectonicsError('nonfinite face flux')
    return area,flux


class SurfaceProjection:
    """One fixed-x Q2 surface mass factor; O(nx) solve, geometry-independent."""
    def __init__(self,x_m,*,order=5):
        cholesky_banded, _ = _banded_solvers()
        shape=input_shape(x_m)
        if len(shape)!=1 or shape[0]<5 or shape[0]>129 or shape[0]%2!=1:
            raise TectonicsError('odd bounded surface node count required')
        self.x=frozen(read_array(x_m,'surface x'))
        if np.any(np.diff(self.x)<=0.):raise TectonicsError('surface overturning/nonmonotone x')
        self.nx=(shape[0]-1)//2;self.order=order
        self.q,self.w=np.polynomial.legendre.leggauss(order)
        self.N,self.dN=q2(self.q),dq2(self.q)
        self.ids=2*np.arange(self.nx)[:,None]+np.arange(3)[None]
        dx=self.x[2::2]-self.x[:-2:2]
        if not np.allclose(self.x[1::2],.5*(self.x[:-2:2]+self.x[2::2]),rtol=0.,atol=1e-13*float(dx.min())):
            raise TectonicsError('surface x must be affine within each element')
        self.dx_weights=.5*dx[:,None]*self.w
        local=np.einsum('qa,qb,eq->eab',self.N,self.N,self.dx_weights)
        bands=np.zeros((3,shape[0]))
        for a in range(3):
            for b in range(a+1):np.add.at(bands[a-b],self.ids[:,b],local[:,a,b])
        self.factor=cholesky_banded(bands,lower=True,check_finite=True)

    def rate(self,height,velocity):
        _, cho_solve_banded = _banded_solvers()
        if input_shape(height)!=self.x.shape or input_shape(velocity)!=(len(self.x),2):
            raise TectonicsError('surface state/velocity support mismatch')
        h=read_array(height,'surface heights');v=read_array(velocity,'surface velocity')
        slope=np.einsum('qa,ea->eq',self.dN,h[self.ids])/(.5*(self.x[2::2]-self.x[:-2:2]))[:,None]
        vq=np.einsum('qa,eac->eqc',self.N,v[self.ids])
        physical_rate=vq[...,1]-vq[...,0]*slope
        rhs=np.zeros_like(self.x)
        local=np.einsum('qa,eq,eq->ea',self.N,physical_rate,self.dx_weights)
        np.add.at(rhs,self.ids,local)
        rate=cho_solve_banded((self.factor,True),rhs,check_finite=True)
        represented=np.einsum('qa,ea->eq',self.N,rate[self.ids])
        flux=float(np.sum(physical_rate*self.dx_weights))
        projected=float(np.sum(represented*self.dx_weights))
        return rate,dict(physical_surface_flux_m2_s=flux,mesh_surface_flux_m2_s=projected,
            projection_volume_residual_m2_s=projected-flux,
            kinematic_projection_l2_m_s=float(np.sqrt(np.sum((represented-physical_rate)**2*self.dx_weights)/np.sum(self.dx_weights))))

    def integral(self,height):
        if input_shape(height)!=self.x.shape:raise TectonicsError('surface height support mismatch')
        return float(np.sum(np.einsum('qa,ea->eq',self.N,read_array(height,'height')[self.ids])*self.dx_weights))
