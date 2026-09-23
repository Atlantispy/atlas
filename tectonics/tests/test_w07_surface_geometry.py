import unittest
import numpy as np
from atlas_tectonics.surface_geometry import graph_mesh,cell_volume_and_flux,SurfaceProjection


class SurfaceGeometry(unittest.TestCase):
    def test_exact_quadratic_volume_and_independent_flux(self):
        x=np.linspace(0.,2.,9);h=1.+.2*x*(2.-x)
        m=graph_mesh(2.,0.,h,3)
        area,flux=cell_volume_and_flux(m,np.stack((m[...,0],-m[...,1]),axis=-1))
        self.assertAlmostEqual(area.sum(),2.+.2*4./3.,places=13)
        np.testing.assert_allclose(flux.sum(axis=-1),0.,atol=1e-14)
        zero=np.zeros_like(m);zero[...,1]=m[...,1]
        dt=.03;new=m+dt*zero
        changed,_=cell_volume_and_flux(new)
        _,meshflux=cell_volume_and_flux(m,zero)
        np.testing.assert_allclose(changed-area,dt*meshflux.sum(axis=-1),atol=1e-14)

    def test_surface_projection_retains_volume_without_constant_correction(self):
        x=np.linspace(0.,2.,17);h=1.+.1*np.cos(np.pi*x)
        v=np.column_stack((.03*np.sin(np.pi*x),.2*np.cos(np.pi*x)))
        projection=SurfaceProjection(x)
        rate,account=projection.rate(h,v)
        self.assertAlmostEqual(projection.integral(rate),account['physical_surface_flux_m2_s'],places=14)
        self.assertLess(abs(account['projection_volume_residual_m2_s']),1e-14)
        _,affine=projection.rate(1.+.2*x,np.column_stack((np.ones_like(x),2.+3*x)))
        self.assertLess(affine['kinematic_projection_l2_m_s'],2e-14)


if __name__=='__main__':unittest.main()
