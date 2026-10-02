"""Frozen B07 and open/ALE transport boundary checks; no full campaign.

SPDX-License-Identifier: AGPL-3.0-only
Analytic cell means and boundary integrals are derived directly from the PDE,
independently of the finite-volume numerical stencil.
"""
import math
import unittest
from concurrent.futures import CancelledError
from threading import Event

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.regional_transport import (
    RectangularTransportGrid, HeatBoundary, PreparedHeatTransport,
    MaterialRegion2D, translate_material_regions)


def grid(nx=16, nz=8, width=1., height=.5, origin=(0., 0.)):
    return RectangularTransportGrid(nx, nz, width, height, 'synthetic-cartesian', origin)


def exact_temperature(g, time, origin=None, speed=1.):
    x, z = g.edges(origin)
    k = 2*math.pi
    means = 1.+.1*math.exp(-.01*k*k*time)*(np.sin(k*(x[1:]-speed*time))-
                                            np.sin(k*(x[:-1]-speed*time)))/(k*g.dx)
    return np.broadcast_to(means, (g.nz, g.nx)).copy()


def sinusoidal_boundaries(speed=1.):
    k = 2*math.pi
    def temperature(x, z, time):
        return 1.+.1*np.exp(-.01*k*k*time)*np.cos(k*(x-speed*time))
    def right_flux(x, z, time):
        return .01*.1*k*np.exp(-.01*k*k*time)*np.sin(k*(x-speed*time))
    return {'left': HeatBoundary(temperature, 'outward_flux', lambda x,z,t:-right_flux(x,z,t)),
            'right': HeatBoundary(temperature, 'outward_flux', right_flux),
            'bottom': HeatBoundary(temperature, 'outward_flux', 0.),
            'top': HeatBoundary(temperature, 'outward_flux', 0.)}


def uniform_boundaries(value=1.):
    return {side: HeatBoundary(value, 'temperature', value)
            for side in ('left', 'right', 'bottom', 'top')}


def run_sinusoid(nx, steps, *, nz=4, duration=.08, mesh=(0.,0.), speed=1.):
    g = grid(nx, nz)
    plan = PreparedHeatTransport(g, .01, 1.)
    u = np.full((nz, nx+1), speed)
    w = np.zeros((nz+1, nx))
    result = plan.evolve(exact_temperature(g, 0., speed=speed), u, w, duration,
                         steps=steps, boundaries=sinusoidal_boundaries(speed), mesh_velocity_m_s=mesh)
    exact = exact_temperature(g, duration, result['origin_m'], speed)
    error = np.linalg.norm(result['temperature_k']-exact)/np.linalg.norm(exact-1.)
    return error, result


class RegionalHeatTransportTests(unittest.TestCase):
    def test_b07_spatial_refinement_open_translation(self):
        errors = []
        for nx, steps in ((16,64), (32,128), (64,256)):
            error, result = run_sinusoid(nx, steps)
            errors.append(error)
            self.assertLess(result['balance_relative'], 1e-9)
            self.assertLess(result['maximum_step_balance_relative'], 1e-9)
            self.assertGreater(result['advective_energy_j']['right'], 0.)
            self.assertLess(result['advective_energy_j']['left'], 0.)
            self.assertGreaterEqual(result['minimum_k'], .9)
            self.assertLessEqual(result['maximum_k'], 1.1)
        print('B07 spatial relative perturbation errors:', errors)
        self.assertGreater(errors[0], errors[1])
        self.assertGreater(errors[1], errors[2])
        self.assertLessEqual(errors[-1], .01)

    def test_b07_time_partition_error_decreases(self):
        # The same spatial operator is compared against a finer time partition;
        # continuum accuracy is checked separately above, not conflated with dt.
        states = [run_sinusoid(32, steps)[1]['temperature_k'] for steps in (32,64,128,256)]
        errors = [float(np.linalg.norm(T-states[-1])) for T in states[:-1]]
        print('B07 temporal errors against 256 intervals:', errors)
        self.assertGreater(errors[0], errors[1])
        self.assertGreater(errors[1], errors[2])

    def test_b07_prescribed_ale_translation(self):
        error, result = run_sinusoid(64, 256, mesh=(.3, -.2), nz=12)
        self.assertLess(error, .01)
        self.assertAlmostEqual(result['origin_m'][0], .024)
        self.assertAlmostEqual(result['origin_m'][1], -.016)
        self.assertEqual(result['geometric_conservation_residual_m3'], 0.)
        self.assertLess(result['balance_relative'], 1e-9)

    def test_two_dimensional_stationary_temperature_on_moving_mesh(self):
        g = grid(20, 12, width=2., height=1.)
        plan = PreparedHeatTransport(g, .01, 2.)
        def T(x,z,t):
            return 2.+.1*x+.2*z
        x,z = g.edges()
        X,Z = np.meshgrid(x[:-1]+g.dx/2,z[:-1]+g.dz/2)
        boundaries = {s:HeatBoundary(T,'temperature',T) for s in ('left','right','bottom','top')}
        u,w = np.zeros((g.nz,g.nx+1)),np.zeros((g.nz+1,g.nx))
        result = plan.evolve(T(X,Z,0.),u,w,.02,steps=32,boundaries=boundaries,
                             mesh_velocity_m_s=(.3,-.2))
        exact = T(X+.006,Z-.004,.02)
        self.assertLess(np.max(np.abs(result['temperature_k']-exact)), 1e-12)
        self.assertLess(result['balance_relative'],1e-9)
        # Independent continuum boundary-flux and moving-volume storage checks.
        for side, value in dict(left=2e-5,right=-2e-5,bottom=8e-5,top=-8e-5).items():
            self.assertAlmostEqual(result['diffusive_energy_j'][side],value,places=13)
        self.assertAlmostEqual(result['heat_after_j']-result['heat_before_j'],-.0008,places=12)

    def test_oblique_two_dimensional_mode(self):
        g=grid(64,32,width=1.,height=1.)
        U,W,kx,kz=.6,-.3,2*math.pi,math.pi
        duration=.04
        sx,sz=np.sinc(kx*g.dx/(2*math.pi)),np.sinc(kz*g.dz/(2*math.pi))
        def amplitude(t):
            return .1*np.exp(-.01*(kx*kx+kz*kz)*t)
        def boundary(side):
            def T(x,z,t):
                tangent=sz if side in ('left','right') else sx
                return 1.+amplitude(t)*np.cos(kx*(x-U*t))*np.cos(kz*(z-W*t))*tangent
            def flux(x,z,t):
                if side in ('left','right'):
                    return (-1 if side=='left' else 1)*.01*amplitude(t)*kx*np.sin(kx*(x-U*t))*np.cos(kz*(z-W*t))*sz
                return (-1 if side=='bottom' else 1)*.01*amplitude(t)*kz*np.cos(kx*(x-U*t))*np.sin(kz*(z-W*t))*sx
            return HeatBoundary(T,'outward_flux',flux)
        x,z=g.edges();X,Z=np.meshgrid(x[:-1]+g.dx/2,z[:-1]+g.dz/2)
        initial=1.+amplitude(0.)*np.cos(kx*X)*np.cos(kz*Z)*sx*sz
        plan=PreparedHeatTransport(g,.01,1.)
        result=plan.evolve(initial,np.full((g.nz,g.nx+1),U),np.full((g.nz+1,g.nx),W),
                           duration,steps=128,boundaries={s:boundary(s) for s in ('left','right','bottom','top')})
        exact=1.+amplitude(duration)*np.cos(kx*(X-U*duration))*np.cos(kz*(Z-W*duration))*sx*sz
        self.assertLess(np.linalg.norm(result['temperature_k']-exact)/np.linalg.norm(exact-1.),.01)
        self.assertLess(result['balance_relative'],1e-9)

    def test_constant_state_gcl_and_maximum_principle(self):
        g = grid()
        plan = PreparedHeatTransport(g,.01,2.)
        result = plan.evolve(np.ones((g.nz,g.nx)),np.ones((g.nz,g.nx+1)),
                             np.full((g.nz+1,g.nx),-.2),.02,steps=16,
                             boundaries=uniform_boundaries(),mesh_velocity_m_s=(.3,.1))
        np.testing.assert_allclose(result['temperature_k'],1.,rtol=0.,atol=5e-15)
        initial = np.ones((g.nz,g.nx));initial[2:5,5:10]=2.
        result = plan.evolve(initial,np.ones((g.nz,g.nx+1)),np.zeros((g.nz+1,g.nx)),
                             .02,steps=16,boundaries=uniform_boundaries())
        self.assertGreaterEqual(result['minimum_k'],1.-5e-14)
        self.assertLessEqual(result['maximum_k'],2.+5e-14)

    def test_inflow_must_equal_a_prescribed_face_temperature(self):
        # Pure advection, u=1, CFL 0.4, declared inflow 450 K on the left. A face
        # temperature of 100 K has no conductive role here, yet it shaped the
        # boundary cell's slope: that cell fell to 395 K, below every advected
        # state, and the step was accepted.
        g=RectangularTransportGrid(4,2,1.,1.,'synthetic-cartesian')
        T=np.array([[500.,1000.,1000.,1000.]]*2)
        u,w=np.ones((2,5)),np.zeros((3,4))
        closed=HeatBoundary(None,'outward_flux',0.)
        def step(left,conductivity=0.,u=u,right=closed):
            return PreparedHeatTransport(g,conductivity,1.).step(T,u,w,.1,
                boundaries=dict(left=left,right=right,bottom=closed,top=closed))
        for conductivity in (0.,.01):
            result=step(HeatBoundary(450.,'temperature',450.),conductivity)
            self.assertGreater(result['minimum_k'],450.)
            self.assertLessEqual(result['maximum_k'],1000.)
            for face in (100.,2000.,float(np.nextafter(450.,451.)),lambda x,z,t:450.+z):
                with self.subTest(conductivity=conductivity,face=face),self.assertRaises(TectonicsError):
                    step(HeatBoundary(450.,'temperature',face),conductivity)
        # Only inward faces are compared: row 1 leaves through the left side.
        counter=u*np.array([[1.],[-1.]])
        opposite=HeatBoundary(450.,'outward_flux',0.)
        result=step(HeatBoundary(np.array([450.,777.]),'temperature',450.),u=counter,right=opposite)
        self.assertGreater(result['minimum_k'],450.)
        self.assertLessEqual(result['maximum_k'],1000.)
        for left in (HeatBoundary(np.array([777.,450.]),'temperature',450.),
                     HeatBoundary(450.,'temperature',np.array([777.,450.]))):
            with self.assertRaises(TectonicsError):
                step(left,u=counter,right=opposite)

    def test_wall_temperature_does_not_drive_closed_or_turning_advection(self):
        # Inflow turns in the last column and leaves to the left, optionally
        # also through the right face. A 2000 K wall formerly made that column
        # export 400 K fluid and warm from 500 to 522 K, even with subnormal
        # conductivity. Check both extrema and all four side orientations.
        dt=.04
        for side in ('left','right','bottom','top'):
            for outward in (0.,.25):
                u=np.full((2,5),-1.);u[:,-1]=outward
                w=np.zeros((3,4));w[1,3]=-2*(1+outward);w[2,3]=-4*(1+outward)
                hot=np.full((2,4),400.);hot[:,3]=500.
                if side=='left':
                    hot,u,w=hot[:,::-1],-u[:,::-1],w[:,::-1]
                elif side in ('bottom','top'):
                    hot,u,w=hot.T,w.T,u.T
                    if side=='bottom':
                        hot,u,w=hot[::-1],u[::-1],-w[::-1]
                nz,nx=hot.shape
                g=RectangularTransportGrid(nx,nz,1.,1.,'synthetic-cartesian')
                for wall_temperature,inflow,T in ((2000.,500.,hot),(100.,400.,900.-hot)):
                    closed=HeatBoundary(inflow,'outward_flux',0.)
                    bc={s:closed for s in ('left','right','bottom','top')}
                    reference=PreparedHeatTransport(g,0.,1.).step(T,u,w,dt,boundaries=bc)
                    bc[side]=HeatBoundary(inflow,'temperature',wall_temperature)
                    for conductivity in (0.,float(np.nextafter(0.,1.)),1e-9):
                        with self.subTest(side=side,outward=outward,wall=wall_temperature,k=conductivity):
                            result=PreparedHeatTransport(g,conductivity,1.).step(T,u,w,dt,boundaries=bc)
                            # The largest possible wall contribution over dt is
                            # its half-cell conductance times the largest jump.
                            # This tends to zero with k, unlike the old 22 K jump.
                            bound=dt*2*conductivity*max(abs(wall_temperature-400.),
                                abs(wall_temperature-500.))/min(g.dx,g.dz)**2
                            self.assertLessEqual(result['maximum_k'],500.+bound+1e-11)
                            self.assertGreaterEqual(result['minimum_k'],400.-bound-1e-11)
                            self.assertLess(result['balance_relative'],1e-12)
                            if conductivity==0.:
                                np.testing.assert_array_equal(result['temperature_k'],reference['temperature_k'])
                                self.assertEqual(result['advective_energy_j'],reference['advective_energy_j'])
                                self.assertEqual(result['diffusive_energy_j'][side],0.)

    def test_outflow_reconstruction_uses_interior_temperature(self):
        g=RectangularTransportGrid(4,2,1.,1.,'synthetic-cartesian')
        x,z=g.edges();X,Z=np.meshgrid(x[:-1]+g.dx/2,z[:-1]+g.dz/2)
        T=500.+100.*X
        closed=HeatBoundary(None,'outward_flux',0.)
        inflow=lambda x,z,t:500.-100.*t
        for wall_temperature in (100.,2000.):
            with self.subTest(wall=wall_temperature):
                result=PreparedHeatTransport(g,0.,1.).step(T,np.ones((2,5)),np.zeros((3,4)),.05,
                    boundaries=dict(left=HeatBoundary(inflow,'temperature',inflow),
                        right=HeatBoundary(None,'temperature',wall_temperature),bottom=closed,top=closed))
                np.testing.assert_allclose(result['temperature_k'],T-5.,rtol=0.,atol=1e-12)
                self.assertAlmostEqual(result['advective_energy_j']['right'],.05*(600.-2.5),places=12)
                self.assertLess(result['balance_relative'],1e-12)
        # A steep outgoing gradient must not extrapolate below absolute zero
        # and turn positive fluid export into a negative heat flux.
        T=np.array([[1000.,1000.,1000.,1.]]*2)
        result=PreparedHeatTransport(g,0.,1.).step(T,np.ones((2,5)),np.zeros((3,4)),.01,
            boundaries=dict(left=HeatBoundary(1000.,'temperature',1000.),
                right=HeatBoundary(None,'temperature',1.),bottom=closed,top=closed))
        self.assertGreater(result['advective_energy_j']['right'],0.)
        self.assertGreater(result['minimum_k'],0.)
        self.assertLessEqual(result['maximum_k'],1000.)

    def test_conducting_wall_can_change_fluid_extrema(self):
        # Why a conducting face is counted: in still fluid nothing is advected, and
        # heat conducted from the wall alone lifts the last column above every
        # cell state.
        g=RectangularTransportGrid(4,2,1.,1.,'synthetic-cartesian')
        closed=HeatBoundary(None,'outward_flux',0.)
        wall=HeatBoundary(None,'temperature',2000.)
        still=PreparedHeatTransport(g,.01,1.).step(np.full((2,4),500.),np.zeros((2,5)),np.zeros((3,4)),
            .05,boundaries=dict(left=closed,right=wall,bottom=closed,top=closed))
        self.assertGreater(still['maximum_k'],500.)
        self.assertLess(still['maximum_k'],2000.)
        conducted=-still['diffusive_energy_j']['right']
        self.assertGreater(conducted,0.)
        self.assertAlmostEqual(still['heat_after_j']-still['heat_before_j'],conducted)

    def test_source_and_diffusive_accounts_use_si_strike_width(self):
        g = RectangularTransportGrid(8,6,2.,3.,'synthetic',strike_width_m=4.)
        plan = PreparedHeatTransport(g,0.,3.)
        bc={s:HeatBoundary(None,'outward_flux',0.) for s in ('left','right','bottom','top')}
        result=plan.step(np.full((6,8),2.),np.zeros((6,9)),np.zeros((7,8)),.1,
                         boundaries=bc,source_w_m3=6.)
        np.testing.assert_allclose(result['temperature_k'],2.2,rtol=0.,atol=1e-14)
        self.assertAlmostEqual(result['source_energy_j'],14.4)
        self.assertLess(result['balance_relative'],1e-14)
        bc['top']=HeatBoundary(None,'outward_flux',2.)
        result=plan.step(np.full((6,8),2.),np.zeros((6,9)),np.zeros((7,8)),.01,
                         boundaries=bc)
        self.assertAlmostEqual(result['diffusive_energy_j']['top'],.16)
        self.assertAlmostEqual(result['heat_before_j']-result['heat_after_j'],.16)

    def test_required_inflow_divergence_step_mesh_and_resource_refusals(self):
        g=grid();plan=PreparedHeatTransport(g,.01,1.)
        T=np.ones((g.nz,g.nx));u=np.ones((g.nz,g.nx+1));w=np.zeros((g.nz+1,g.nx))
        bc=uniform_boundaries();bc['left']=HeatBoundary(None,'temperature',1.)
        with self.assertRaisesRegex(TectonicsError,'inflow'):
            plan.step(T,u,w,.001,boundaries=bc)
        with self.assertRaisesRegex(TectonicsError,'divergence'):
            plan.step(T,u*np.linspace(1,2,g.nx+1),w,.001,boundaries=uniform_boundaries())
        with self.assertRaisesRegex(TectonicsError,'timestep'):
            plan.step(T,u,w,1.,boundaries=uniform_boundaries())
        with self.assertRaisesRegex(TectonicsError,'256'):
            plan.evolve(T,u,w,.1,steps=257,boundaries=uniform_boundaries())
        with self.assertRaisesRegex(TectonicsError,'distorted'):
            plan.step(T,u,w,.001,boundaries=uniform_boundaries(),mesh_velocity_m_s=u)
        with self.assertRaises(MemoryLimitError):
            PreparedHeatTransport(g,.01,1.,budget=WorkBudget(4096))
        with self.assertRaisesRegex(TectonicsError,'2 to 64'):
            PreparedHeatTransport(grid(1048576,1048576),.01,1.)
        with self.assertRaises(CancelledError):
            plan.step(T,u,w,.001,boundaries=uniform_boundaries(),cancel=lambda:True)
        with self.assertRaisesRegex(TectonicsError,'unresolvable'):
            grid(origin=(1e16,0.))

    def test_shared_budget_cap_and_event_cancellation(self):
        parent=WorkBudget(256*1024**2)
        g=grid();plan=PreparedHeatTransport(g,.01,1.,budget=parent)
        T=np.ones((g.nz,g.nx));u=np.ones((g.nz,g.nx+1));w=np.zeros((g.nz+1,g.nx))
        self.assertEqual(plan.budget.max_bytes,128*1024**2)
        with self.assertRaises(MemoryLimitError), plan.budget.reserve(129*1024**2):
            pass
        with parent.reserve(parent.max_bytes-plan.work_bytes+1):
            with self.assertRaises(MemoryLimitError):
                plan.step(T,u,w,.001,boundaries=uniform_boundaries())
        self.assertEqual(parent.reserved_bytes,0)
        self.assertEqual(plan.budget.reserved_bytes,0)
        cancelled=Event();cancelled.set()
        with self.assertRaises(CancelledError):
            plan.step(T,u,w,.001,boundaries=uniform_boundaries(),cancel=cancelled)


class RegionalMaterialTransportTests(unittest.TestCase):
    def test_exact_translation_with_real_inflow_outflow(self):
        g=grid(16,8)
        regions=(MaterialRegion2D('a',(-1.,.37,-1.,2.),2.),
                 MaterialRegion2D('b',(.37,2.,-1.,2.),3.))
        result=translate_material_regions(g,regions,(1.,0.),.2)
        self.assertAlmostEqual(result['accounts']['a']['after_kg'],.57)
        self.assertAlmostEqual(result['accounts']['a']['inflow_kg'],.2)
        self.assertAlmostEqual(result['accounts']['b']['outflow_kg'],.3)
        np.testing.assert_allclose(result['cell_volume_fraction'].sum(axis=0),1.,atol=5e-14)
        for account in result['accounts'].values():
            self.assertLess(abs(account['balance_residual_kg']),1e-14)

    def test_stationary_material_and_mesh_motion_are_distinct(self):
        g=grid();r=(MaterialRegion2D('a',(-1.,.37,-1.,2.),2.),)
        moving=translate_material_regions(g,r,(0.,0.),.2,mesh_velocity_m_s=(.5,-.2))
        self.assertEqual(moving['regions'],r)
        self.assertAlmostEqual(moving['mass_after_kg'],.27)
        # Horizontal export .1 plus vertical throughflow .0256; the latter is
        # independently width-integrated along the diagonal mesh path.
        self.assertAlmostEqual(moving['outflow_kg'],.1256)
        self.assertAlmostEqual(moving['inflow_kg'],.0256)
        self.assertAlmostEqual(moving['origin_m'][1],-.04)
        comoving=translate_material_regions(g,r,(.5,-.2),.2,mesh_velocity_m_s=(.5,-.2))
        self.assertAlmostEqual(comoving['mass_before_kg'],comoving['mass_after_kg'])
        self.assertEqual(comoving['inflow_kg'],0.)
        self.assertEqual(comoving['outflow_kg'],0.)

    def test_material_crossing_entire_domain_is_accounted(self):
        g=grid();regions=(MaterialRegion2D('pulse',(-.4,-.2,.1,.3),5.),)
        result=translate_material_regions(g,regions,(1.,0.),2.)
        self.assertEqual(result['mass_before_kg'],0.)
        self.assertEqual(result['mass_after_kg'],0.)
        self.assertAlmostEqual(result['inflow_kg'],.2)
        self.assertAlmostEqual(result['outflow_kg'],.2)

    def test_diagonal_crossing_and_partition_preserve_exact_geometry(self):
        g=grid(12,7,width=1.2,height=.7)
        r=(MaterialRegion2D('a',(-.5,.45,-.6,.33),2.),)
        single=translate_material_regions(g,r,(.8,.7),.6,mesh_velocity_m_s=(.1,-.1))
        first=translate_material_regions(g,r,(.8,.7),.3,mesh_velocity_m_s=(.1,-.1))
        g2=grid(12,7,width=1.2,height=.7,origin=first['origin_m'])
        second=translate_material_regions(g2,first['regions'],(.8,.7),.3,mesh_velocity_m_s=(.1,-.1))
        np.testing.assert_allclose(single['cell_mass_kg'],second['cell_mass_kg'],rtol=0.,atol=5e-15)
        self.assertAlmostEqual(single['inflow_kg'],first['inflow_kg']+second['inflow_kg'])
        self.assertAlmostEqual(single['outflow_kg'],first['outflow_kg']+second['outflow_kg'])

    def test_material_rejects_overlap_and_deformation(self):
        r=MaterialRegion2D('a',(0.,1.,0.,1.),1.)
        with self.assertRaisesRegex(TectonicsError,'overlap'):
            translate_material_regions(grid(),(r,r),(0.,0.),.1)
        with self.assertRaisesRegex(TectonicsError,'distorted'):
            translate_material_regions(grid(),(r,),np.zeros((8,17)),.1)

    def test_material_catalogue_budget_and_event_admission(self):
        r=MaterialRegion2D('a',(0.,1.,0.,1.),1.)
        with self.assertRaisesRegex(TectonicsError,'catalogue admission'):
            translate_material_regions(grid(),(r,)*257,(0.,0.),.1)
        with self.assertRaises(MemoryLimitError):
            translate_material_regions(grid(),(r,),(0.,0.),.1,budget=WorkBudget(4096))
        cancelled=Event();cancelled.set()
        with self.assertRaises(CancelledError):
            translate_material_regions(grid(),(r,),(0.,0.),.1,cancel=cancelled)


if __name__=='__main__':
    unittest.main()
