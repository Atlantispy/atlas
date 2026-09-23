import unittest
import numpy as np
from w07_interface_reference import interface_fields,mode_derivatives,_g,layered_sites,layered_velocity


class IndependentInterfaces(unittest.TestCase):
    def test_piecewise_equation_and_tractions(self):
        for variant,n in (('aspect-source',1),('frozen-manual',2),('frozen-manual',32)):
            x=np.array([.1,.3,.7,.9]); k=n*np.pi
            d,eta=mode_derivatives(x,variant=variant,n=n)
            np.testing.assert_allclose(eta*(d[4]-2*k*k*d[2]+k**4*d[0]),_g(x,1,variant,n),atol=2e-10,rtol=1e-10)
            left,_=mode_derivatives(np.array([.5]),variant=variant,n=n,side=0)
            right,_=mode_derivatives(np.array([.5]),variant=variant,n=n,side=1)
            for index in (0,1):np.testing.assert_allclose(left[index],right[index],atol=2e-13)
            np.testing.assert_allclose(left[2]+k*k*left[0],1e6*(right[2]+k*k*right[0]),atol=2e-11)
            np.testing.assert_allclose(left[3]-3*k*k*left[1],1e6*(right[3]-3*k*k*right[1]),atol=2e-11)

    def test_boundaries_gauge_and_sign(self):
        v=np.linspace(0,1,33)
        for x in (0.,1.):
            f=interface_fields(x,v)
            np.testing.assert_allclose(f[0],0,atol=1e-13)
            np.testing.assert_allclose(f[10],0,atol=1e-11)
        for z in (0.,1.):
            f=interface_fields(v,z)
            np.testing.assert_allclose(f[1],0,atol=1e-13)
            np.testing.assert_allclose(f[10],0,atol=1e-11)
        x,z=np.meshgrid((np.arange(32)+.5)/32,(np.arange(32)+.5)/32)
        f=interface_fields(x,z)
        self.assertLess(abs(float(np.mean(f[2]))),1e-12)
        self.assertGreater(float(np.sum(f[1]*f[4])),0.)

    def test_frozen_variant_spectral_convergence(self):
        x,z=np.meshgrid((np.arange(16)+.5)/16,(np.arange(16)+.5)/16)
        a=interface_fields(x,z,variant='frozen-manual',modes=64)
        b=interface_fields(x,z,variant='frozen-manual',modes=128)
        c=interface_fields(x,z,variant='frozen-manual',modes=256)
        for i in (0,1,2):
            self.assertLess(np.linalg.norm(c[i]-b[i]),np.linalg.norm(b[i]-a[i]))
            self.assertLess(np.linalg.norm(c[i]-b[i])/np.linalg.norm(c[i]),2e-5)

    def test_exact_series_layer(self):
        for a in (.37,.5):
            for n in (16,32,64):
                _,eta=layered_sites(n,n,a)
                zv=np.arange(n+1)/n
                lo=np.maximum(0.,zv-.5/n); hi=np.minimum(1.,zv+.5/n)
                shear=eta[:,0]*(layered_velocity(hi,a)-layered_velocity(lo,a))/(hi-lo)
                np.testing.assert_allclose(shear,1/(a+(1-a)/1000),rtol=5e-11)


if __name__=='__main__':unittest.main()
