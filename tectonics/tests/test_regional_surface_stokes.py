"""Independent mapped weak-form and geometry checks; no B09 time campaign.

SPDX-License-Identifier: AGPL-3.0-only
"""
import unittest
from threading import Event
from concurrent.futures import CancelledError

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.regional_surface_stokes import PreparedSurfaceStokes2D


def mesh(nx,nz,amplitude=.1,width=2.,height=1.,internal=.0):
    x=np.linspace(0.,width,2*nx+1)
    level=np.linspace(0.,1.,2*nz+1)
    X,S=np.meshgrid(x,level)
    Z=S*(height+amplitude*np.cos(np.pi*X/width))
    Z+=internal*np.sin(np.pi*S)*np.cos(2*np.pi*X/width)
    return np.stack((X,Z),axis=-1)


class SurfaceStokesTests(unittest.TestCase):
    def test_curved_hydrostatic_pressure_is_physical_affine(self):
        for method in ('direct','gmres'):
            with self.subTest(method=method),PreparedSurfaceStokes2D(4,3,method=method) as plan:
                nodes=mesh(4,3,internal=.02)
                result=plan.solve(nodes,3.,(0.,-2.),top_pressure_pa=lambda x,z:7.-2*z)
                points=result['quadrature_points_m']
                np.testing.assert_allclose(result['pressure_q_pa'],7.-2*points[...,1],rtol=0.,atol=2e-10)
                self.assertLess(np.max(np.abs(result['velocity_nodes_m_s'])),2e-11)
                self.assertLess(np.max(np.abs(result['strain_q_s_1'])),2e-10)
                self.assertTrue(result['diagnostics']['gates_passed'])
                self.assertEqual(result['diagnostics']['physical_pressure'],'top-traction-determined; no gauge removal')
                self.assertGreater(result['diagnostics']['minimum_jacobian_m2'],0.)
                self.assertLess(result['diagnostics']['quadrature_scatter_difference_n_per_m'],1e-11)
                self.assertLess(result['diagnostics']['quadrature_continuity_difference_m2_s'],1e-12)

    def test_flat_free_surface_rest_and_gauge_not_removed(self):
        with PreparedSurfaceStokes2D(4,2) as plan:
            admitted=plan.validate_geometry(mesh(4,2,amplitude=0.))
            self.assertAlmostEqual(admitted['domain_area_m2'],2.)
            result=plan.solve(mesh(4,2,amplitude=0.),1.,(0.,-1.),top_pressure_pa=3.)
            np.testing.assert_allclose(result['pressure_q_pa'],4.-result['quadrature_points_m'][...,1],rtol=0.,atol=1e-11)
            self.assertLess(np.max(np.abs(result['velocity_nodes_m_s'])),1e-11)
            trace=plan.top_trace(result)
            np.testing.assert_allclose(trace['pressure_q_pa'],3.,rtol=0.,atol=1e-11)
            self.assertAlmostEqual(float(np.sum(result['element_volume_m2'])),2.)
            self.assertEqual(trace['basis'].shape,(5,3))

    def test_mapped_affine_couette_and_current_quadrature_viscosity(self):
        # Deform internal nodes while keeping physical top/bottom flat. The
        # exact physical u=z remains in the isoparametric Q2 velocity space.
        nodes=mesh(6,3,amplitude=0.,internal=.04)
        with PreparedSurfaceStokes2D(6,3) as plan:
            result=plan.solve(nodes,2.,(0.,0.),top_pressure_pa=5.,top_shear_traction_pa=2.,
                boundary_velocity_m_s={'left_u':lambda x,z:z,'right_u':lambda x,z:z},
                side_shear_traction_pa={'left':-2.,'right':2.})
            np.testing.assert_allclose(result['velocity_nodes_m_s'][...,0],nodes[...,1],rtol=0.,atol=2e-10)
            np.testing.assert_allclose(result['velocity_nodes_m_s'][...,1],0.,rtol=0.,atol=2e-10)
            np.testing.assert_allclose(result['stress_q_pa'][...,2],2.,rtol=0.,atol=2e-9)
            self.assertAlmostEqual(result['diagnostics']['dissipation_w_per_m'],4.,places=8)
            d=result['diagnostics']
            self.assertAlmostEqual(d['dissipation_w_per_m']-d['pressure_work_w_per_m']-
                d['body_work_w_per_m']-d['traction_work_w_per_m']-d['reaction_work_w_per_m'],
                d['work_residual_w_per_m'],places=12)
            element=np.asarray([[0,0],[1,2],[2,5]])
            reference=np.asarray([[.2,-.3],[-.1,.8],[1.,1.]])
            sampled=plan.evaluate_reference(result,element,reference)
            np.testing.assert_allclose(sampled['velocity_m_s'][:,0],sampled['points_m'][:,1],rtol=0.,atol=2e-10)
            np.testing.assert_allclose(sampled['pressure_pa'],5.,rtol=0.,atol=2e-9)
            self.assertFalse(sampled['velocity_m_s'].flags.writeable)

    def test_nonconstant_viscosity_force_and_surface_traction(self):
        # Physical u=z,w=0, eta=1+z: div(tau)=(1,0), so f=(-1,0).
        # On flat top eta=2, tangential traction=2. Normal P=4.
        nodes=mesh(4,3,amplitude=0.,internal=.03)
        with PreparedSurfaceStokes2D(4,3) as plan:
            result=plan.solve(nodes,lambda x,z:1.+z,(-1.,0.),top_pressure_pa=4.,top_shear_traction_pa=2.,
                boundary_velocity_m_s={'left_u':lambda x,z:z,'right_u':lambda x,z:z},
                side_shear_traction_pa={'left':lambda x,z:-1.-z,'right':lambda x,z:1.+z})
            np.testing.assert_allclose(result['velocity_nodes_m_s'][...,0],nodes[...,1],rtol=0.,atol=1e-9)
            np.testing.assert_allclose(result['pressure_q_pa'],4.,rtol=0.,atol=1e-9)
            self.assertLess(result['diagnostics']['normalised_work_residual'],1e-9)

    def test_laplacian_linear_extension_and_zero_motion(self):
        nodes=mesh(8,4,amplitude=0.,internal=.03)
        with PreparedSurfaceStokes2D(8,4) as plan:
            result=plan.laplacian_mesh_velocity(nodes,np.full(17,.25))
            np.testing.assert_allclose(result,.25*nodes[...,1],rtol=0.,atol=1e-11)
            self.assertLess(plan.laplacian_diagnostics()['linear_residual'],1e-12)
            zero=plan.laplacian_mesh_velocity(nodes,np.zeros(17))
            np.testing.assert_array_equal(zero,np.zeros_like(zero))
            self.assertEqual(plan.laplacian_diagnostics()['iterations'],0)

    def test_scaled_si_hydrostatic_and_metric_cache(self):
        nodes=mesh(4,2,amplitude=10.,width=200.,height=100.)
        with PreparedSurfaceStokes2D(4,2,length_scale_m=100.,velocity_scale_m_s=2.,viscosity_scale_pa_s=30.) as plan:
            a=plan.solve(nodes,30.,(0.,-.2),top_pressure_pa=lambda x,z:70.-.2*z)
            same=plan._geometry
            plan.top_trace(a)
            self.assertIs(plan._geometry,same)
            np.testing.assert_allclose(a['pressure_q_pa'],70.-.2*a['quadrature_points_m'][...,1],rtol=0.,atol=1e-9)
            self.assertLess(np.max(np.abs(a['velocity_nodes_m_s'])),2e-9)
            changed=nodes.copy();changed[1:-1,:,1]*=1.001
            b=plan.solve(changed,30.,(0.,-.2),top_pressure_pa=lambda x,z:70.-.2*z)
            self.assertNotEqual(a['geometry_id'],b['geometry_id'])

    def test_jacobian_inversion_between_gauss_points_refuses(self):
        # Vertical scale q(xi) has a tiny negative pocket at xi=.4 that is
        # missed by order-4 Gauss abscissae. The exact quadratic minimum fails.
        nodes=mesh(1,1,amplitude=0.,width=2.)
        x=nodes[0,:,0]-1.
        height=(x-.4)**2-.0001
        nodes[...,1]=np.linspace(0.,1.,3)[:,None]*height[None,:]
        with PreparedSurfaceStokes2D(1,1,quadrature_order=4) as plan:
            with self.assertRaisesRegex(TectonicsError,'Jacobian'):
                plan.solve(nodes,1.,(0.,0.))

    def test_geometry_resource_boundary_and_cancellation_refusals(self):
        with self.assertRaises(MemoryLimitError):
            PreparedSurfaceStokes2D(64,16,method='direct')
        with self.assertRaises(MemoryLimitError):
            PreparedSurfaceStokes2D(4,2,budget=WorkBudget(4096))
        owner=WorkBudget(128*1024**2)
        with PreparedSurfaceStokes2D(4,2,budget=owner) as plan:
            nodes=mesh(4,2)
            distorted=nodes.copy();distorted[1,1,0]+=.1
            with self.assertRaisesRegex(TectonicsError,'affine'):
                plan.solve(distorted,1.,(0.,0.))
            with self.assertRaisesRegex(TectonicsError,'corner'):
                plan.solve(nodes,1.,(0.,0.),boundary_velocity_m_s={'bottom':(1.,0.)})
            with self.assertRaisesRegex(TectonicsError,'viscosity'):
                plan.solve(nodes,-1.,(0.,0.))
            stop=Event();stop.set()
            with self.assertRaises(CancelledError):
                plan.solve(nodes,1.,(0.,0.),cancel=stop)
        self.assertEqual(owner.reserved_bytes,0)


if __name__=='__main__':
    unittest.main()
