"""Focused public coupling checks; transport/constitutive references live separately."""
import math
import unittest
import numpy as np
from atlas_tectonics import (PreparedRegionalStokes2D,RegionalMechanicsScales,RegionalReferencePressure,
    RectangularTransportGrid,PreparedHeatTransport,HeatBoundary,MaterialRegion2D,
    RegionalThermalBodyForce,advance_regional_thermomechanics,temperature_stress_sites,TectonicsError)
from atlas_tectonics.constitutive import DiffusiveScales,RheologyProfile
from atlas_tectonics.resources import WorkBudget


def fixture(*,velocity=0.,shear=0.,reference=None,budget=None):
    n=4
    pattern={s:{'u':'velocity','w':'velocity'} for s in ('left','right','bottom','top')}
    plan=PreparedRegionalStokes2D(n,n,1.,1.,1.,pattern,scales=RegionalMechanicsScales(1.,1.),
        frame_id='test',vertical_datum='bottom',material_source='seed',physical_mean_pressure_pa=0.,
        reference_pressure=reference,budget=budget)
    boundary={s:{'u':velocity+shear*plan.coordinates((s,'u'))[1],'w':0.} for s in pattern}
    heat=PreparedHeatTransport(RectangularTransportGrid(n,n,1.,1.,'test'),0.,1.,budget=budget)
    profile=RheologyProfile('exp','tosi-linear','analytic reference',(('contrast_T',math.e),('contrast_z',1.)))
    scale=DiffusiveScales('synthetic SI',1.,1.,1.,300.,1000.,1.)
    return plan,heat,profile,scale,boundary


def advance(plan,heat,profile,scale,boundary,**kwargs):
    args=dict(heat_steps=2,heat_boundaries={s:HeatBoundary(800.,'outward_flux',0.) for s in boundary},
        frame_id='test',epoch_id='e',time_s=2.,thermal_source='initial T',material_source='law',
        force_source='explicit no other forces',boundary_source='velocity traces',
        heat_boundary_source='open constant samples',heat_source='volumetric heater',
        thermal_sampling='cell-mean-linear-centre-and-vertex-v1',source_w_m3=10.)
    args.update(kwargs)
    return advance_regional_thermomechanics(plan,heat,profile,scale,np.full((4,4),800.),
        np.zeros((4,5)),np.zeros((5,4)),boundary,.01,**args)


class Thermomechanical(unittest.TestCase):
    def test_heat_updates_endpoint_viscosity_and_stress_without_history_growth(self):
        owner=WorkBudget(128*1024**2)
        plan,heat,profile,scale,boundary=fixture(shear=1.,budget=owner)
        with plan:
            result=advance(plan,heat,profile,scale,boundary)
            self.assertGreater(float(result.temperature_k.mean()),800.09)
            _,vertex=temperature_stress_sites(result.temperature_k)
            expected=np.exp(-(vertex-300.)/1000.)
            np.testing.assert_allclose(result.mechanics.array('viscosity_vertex_pa_s'),expected,atol=1e-12)
            np.testing.assert_allclose(result.mechanics.array('stress_xz_pa'),
                2*expected*result.mechanics.array('strain_xz_s_1'),atol=1e-12)
            self.assertEqual(result.mechanics.descriptor()['request']['time_s'],2.01)
            self.assertLess(result.descriptor()['heat']['balance_relative'],1e-12)
            self.assertNotEqual(result.initial_mechanics.result_id,result.mechanics.result_id)
            with self.assertRaises(ValueError):result.temperature_k.setflags(write=True)
        self.assertEqual(owner.statistics()['reserved_bytes'],0)

    def test_translating_grid_does_not_translate_stationary_material(self):
        plan,heat,profile,scale,boundary=fixture()
        region=MaterialRegion2D('rock',(-1.,2.,-1.,2.),3.)
        with plan:
            result=advance(plan,heat,profile,scale,boundary,mesh_velocity_m_s=(.2,0.),
                material_regions=(region,),source_w_m3=0.)
            np.testing.assert_allclose(result.temperature_k,800.,atol=1e-12)
            np.testing.assert_allclose(result.material_regions[0].bounds_m,region.bounds_m,atol=1e-15)
            np.testing.assert_allclose(result.descriptor()['heat']['origin_m'],[.002,0.],atol=1e-16)
            np.testing.assert_allclose(result.material_mass_kg.sum(),3.,atol=1e-12)
            self.assertAlmostEqual(result.descriptor()['material']['inflow_kg'],.006)

    def test_total_thermal_gravity_and_reference_pressure_not_double_counted(self):
        plan,heat,profile,scale,boundary=fixture(reference=RegionalReferencePressure(0.,2.,'rho0 g'))
        body=RegionalThermalBodyForce(2.,1.,.0001,800.,'linear Boussinesq test')
        with plan:
            result=advance(plan,heat,profile,scale,boundary,thermal_body_force=body,source_w_m3=0.)
            p=2.*(.5-(np.arange(4)+.5)/4)
            np.testing.assert_allclose(result.mechanics.array('physical_pressure_pa'),np.broadcast_to(p[:,None],(4,4)),atol=1e-10)
            np.testing.assert_allclose(result.mechanics.array('u_m_s'),0.,atol=1e-13)

    def test_affine_temperature_reconstruction_and_refusal_boundaries(self):
        x,z=np.meshgrid((np.arange(4)+.5)/4,(np.arange(4)+.5)/4)
        c,v=temperature_stress_sites(500.+100*x+200*z)
        xv,zv=np.meshgrid(np.arange(5)/4,np.arange(5)/4)
        np.testing.assert_allclose(v,500.+100*xv+200*zv,atol=1e-12)
        plan,heat,profile,scale,boundary=fixture(shear=1.)
        with plan:
            for options in ({'frame_id':'wrong'}, {'thermal_sampling':'unknown'},
                            {'heat_steps':257}, {'source_w_m3':lambda x,z,t:0.}):
                with self.assertRaises(TectonicsError):advance(plan,heat,profile,scale,boundary,**options)
            with self.assertRaisesRegex(TectonicsError,'uniform physical'):
                advance(plan,heat,profile,scale,boundary,material_regions=(MaterialRegion2D('rock',(0.,1.,0.,1.),3.),))

    def test_boundary_support_refused_before_copying(self):
        from atlas_tectonics.regional_rheology import _validate_boundary_support
        d={'nx':4,'nz':4,'boundary_types':{s:{} for s in ('left','right','bottom','top')}}
        values={s:{'u':0.,'w':0.} for s in d['boundary_types']}
        values['left']['u']=np.zeros(7)
        with self.assertRaises(TectonicsError):_validate_boundary_support(d,values)


if __name__=='__main__':unittest.main()
