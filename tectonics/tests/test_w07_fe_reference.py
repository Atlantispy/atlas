"""Tiny independent-continuum checks of the non-production Q2/P1 reference."""
from pathlib import Path
import sys
import unittest

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from w07_fe_reference import FEReferenceError, prepare_reference, solve_reference, tensor_quadrature


SIDES=('left','right','bottom','top')


def velocity_boundaries(u=0.,w=0.):
    return {side:{'u':('velocity',u),'w':('velocity',w)} for side in SIDES}


def zero_force(x,z):
    return 0.,0.


def polynomial(s):
    return s*s*(1-s)**2


def first(s):
    return 2*s-6*s*s+4*s**3


def second(s):
    return 2-12*s+12*s*s


def third(s):
    return -12+24*s


def vortex_force(x,z):
    return (3*x*x-second(x)*first(z)-polynomial(x)*third(z),
            3*z*z+third(x)*polynomial(z)+first(x)*second(z))


def vortex_values(points):
    x,z=points.T
    return (polynomial(x)*first(z),-first(x)*polynomial(z),x**3+z**3-.5)


class FEReferenceTests(unittest.TestCase):
    def test_affine_extension_translation_and_rigid_rotation_are_exact(self):
        points,weights=tensor_quadrature(4,3,2.,1.,order=4)
        for offset in ((0.,0.),(.3,-.2)):
            boundaries=velocity_boundaries(lambda x,z:x-1+offset[0],lambda x,z:-(z-.5)+offset[1])
            result=solve_reference(4,2,2.,1.,1.,zero_force,boundaries,pressure_mean=0.)
            field=result.evaluate(points)
            assert_allclose(field['u'],points[:,0]-1+offset[0],rtol=0,atol=2e-12)
            assert_allclose(field['w'],-(points[:,1]-.5)+offset[1],rtol=0,atol=2e-12)
            assert_allclose(field['p'],0.,rtol=0,atol=2e-11)
            assert_allclose(field['strain'],np.tile([1.,-1.,0.],(len(points),1)),rtol=0,atol=2e-11)
            assert_allclose(field['stress'],np.tile([2.,-2.,0.],(len(points),1)),rtol=0,atol=5e-11)
            integrated=2*np.dot(weights,field['strain'][:,0]**2+field['strain'][:,1]**2+2*field['strain'][:,2]**2)
            self.assertAlmostEqual(integrated,8.,delta=1e-11)
            self.assertAlmostEqual(result.diagnostics['dirichlet_reaction_work'],8.,delta=2e-11)
            self.assertLess(abs(result.diagnostics['net_torque']),2e-11)
            assert_allclose(result.diagnostics['net_force'],0.,atol=2e-11)
        rotation=solve_reference(2,2,2.,1.,1.,zero_force,
            velocity_boundaries(lambda x,z:-(z-.5),lambda x,z:x-1),pressure_mean=0.)
        field=rotation.evaluate(points)
        assert_allclose(field['strain'],0.,atol=1e-12)
        self.assertLess(abs(rotation.diagnostics['dissipation']),1e-12)

    def test_couette_traction_fixes_physical_pressure_and_power(self):
        boundaries=velocity_boundaries(lambda x,z:z,0.)
        boundaries['top']={'u':('traction',1.),'w':('traction',-2.)}
        result=solve_reference(4,4,1.,1.,1.,zero_force,boundaries)
        points,weights=tensor_quadrature(5,5,1.,1.,order=4)
        field=result.evaluate(points)
        assert_allclose(field['u'],points[:,1],atol=3e-12,rtol=0)
        assert_allclose(field['w'],0.,atol=3e-12)
        assert_allclose(field['p'],2.,atol=3e-11,rtol=0)
        assert_allclose(field['stress'],np.tile([-2.,-2.,1.],(len(points),1)),atol=4e-11,rtol=0)
        self.assertEqual(result.diagnostics['pressure_kind'],'traction-fixed')
        self.assertIsNone(result.diagnostics['gauge_error'])
        self.assertAlmostEqual(result.diagnostics['applied_traction_work'],1.,delta=3e-12)
        self.assertAlmostEqual(result.diagnostics['dissipation'],1.,delta=1e-11)
        self.assertLess(result.diagnostics['scaled_work_residual'],1e-11)
        # Test outward sign directly, using solved full stress on top and bottom.
        boundary=result.evaluate(np.array([[.35,0.],[.65,1.]]))
        assert_allclose(boundary['stress'][0,[2,1]]*np.array([-1.,-1.]),[-1.,2.],atol=3e-11)
        assert_allclose(boundary['stress'][1,[2,1]],[1.,-2.],atol=3e-11)

    def test_hydrostatics_free_slip_gauge_and_top_traction_datum(self):
        boundaries={side:{'u':('velocity',0.) if side in ('left','right') else ('traction',0.),
                          'w':('velocity',0.) if side in ('bottom','top') else ('traction',0.)} for side in SIDES}
        points,_=tensor_quadrature(3,4,2.,3.,order=3)
        closed=solve_reference(2,3,2.,3.,1.,lambda x,z:(0.,-7.),boundaries,pressure_mean=0.)
        field=closed.evaluate(points)
        assert_allclose(field['u'],0.,atol=2e-12); assert_allclose(field['w'],0.,atol=2e-12)
        assert_allclose(field['p'],-7*(points[:,1]-1.5),rtol=0,atol=3e-11)
        self.assertLess(abs(closed.diagnostics['gauge_error']),1e-12)
        boundaries['top']['w']=('traction',-2.)
        opened=solve_reference(2,3,2.,3.,1.,lambda x,z:(0.,-7.),boundaries)
        field=opened.evaluate(points)
        assert_allclose(field['u'],0.,atol=3e-12); assert_allclose(field['w'],0.,atol=3e-12)
        assert_allclose(field['p'],2+7*(3-points[:,1]),rtol=0,atol=5e-11)
        self.assertAlmostEqual(opened.diagnostics['mean_pressure'],12.5,delta=2e-11)

    def test_polynomial_vortex_refines_against_independent_continuum_and_work(self):
        # Common 16x16 quadrature cells, distinct from all three FE meshes.
        points,weights=tensor_quadrature(16,16,1.,1.,order=4)
        exact_u,exact_w,exact_p=vortex_values(points)
        exact_velocity_norm=np.dot(weights,exact_u**2+exact_w**2)
        pressure_norm=np.dot(weights,exact_p**2)
        errors=[]
        for n in (2,4,8):
            result=solve_reference(n,n,1.,1.,1.,vortex_force,velocity_boundaries(),pressure_mean=0.)
            field=result.evaluate(points)
            ev=np.sqrt(np.dot(weights,(field['u']-exact_u)**2+(field['w']-exact_w)**2)/exact_velocity_norm)
            ep=np.sqrt(np.dot(weights,(field['p']-exact_p)**2)/pressure_norm)
            errors.append((ev,ep))
            self.assertLess(result.diagnostics['weak_continuity_scaled_max'],1e-10)
            self.assertLess(abs(result.diagnostics['gauge_error']),1e-12)
            self.assertLess(result.diagnostics['scaled_work_residual'],1e-9)
            strain=field['strain']
            independent_dissipation=2*np.dot(weights,strain[:,0]**2+strain[:,1]**2+2*strain[:,2]**2)
            force=np.array([vortex_force(x,z) for x,z in points])
            independent_power=np.dot(weights,field['u']*force[:,0]+field['w']*force[:,1])
            self.assertAlmostEqual(independent_dissipation,independent_power,delta=2e-12)
            self.assertAlmostEqual(independent_dissipation,result.diagnostics['dissipation'],delta=2e-12)
        errors=np.asarray(errors)
        self.assertTrue(np.all(errors[:-1]/errors[1:] >= 3.2),repr(errors))
        self.assertTrue(np.all(errors[-1] <= .01),repr(errors))

    def test_exact_factor_reuse_for_changed_rhs_and_boundary_values(self):
        plan=prepare_reference(2,2,1.,1.,1.,velocity_boundaries(),pressure_mean=0.)
        original_factor=plan._factor
        first_result=plan.solve(vortex_force)
        doubled=plan.solve(lambda x,z:tuple(2*v for v in vortex_force(x,z)))
        assert_allclose(doubled.velocity_coefficients,2*first_result.velocity_coefficients,atol=1e-13)
        assert_allclose(doubled.pressure_coefficients,2*first_result.pressure_coefficients,atol=1e-12)
        self.assertIs(plan._factor,original_factor)
        translated=plan.solve(vortex_force,boundaries=velocity_boundaries(.3,-.2))
        assert_allclose(translated.velocity_coefficients,first_result.velocity_coefficients+[.3,-.2],atol=2e-12)
        assert_allclose(translated.pressure_coefficients,first_result.pressure_coefficients,atol=2e-11)
        self.assertEqual(translated.operator_signature,first_result.operator_signature)
        for values in (translated.velocity_coefficients,translated.pressure_coefficients,translated.boundary_reaction_forces):
            with self.assertRaises(ValueError):
                values.flags.writeable=True
        changed=velocity_boundaries(); changed['top']['u']=('traction',0.)
        with self.assertRaisesRegex(FEReferenceError,'types changed'):
            plan.solve(zero_force,boundaries=changed)

    def test_pressure_policy_rigid_modes_conflicts_and_unbalanced_flux_refuse(self):
        with self.assertRaisesRegex(FEReferenceError,'explicit mean'):
            prepare_reference(2,2,1.,1.,1.,velocity_boundaries())
        traction=velocity_boundaries(); traction['top']['w']=('traction',0.)
        with self.assertRaisesRegex(FEReferenceError,'additional mean'):
            prepare_reference(2,2,1.,1.,1.,traction,pressure_mean=0.)
        all_traction={side:{'u':('traction',0.),'w':('traction',0.)} for side in SIDES}
        with self.assertRaisesRegex(FEReferenceError,'rigid modes'):
            prepare_reference(2,2,1.,1.,1.,all_traction)
        conflicting=velocity_boundaries(); conflicting['bottom']['u']=('velocity',1.)
        with self.assertRaisesRegex(FEReferenceError,'corner'):
            prepare_reference(2,2,1.,1.,1.,conflicting,pressure_mean=0.)
        with self.assertRaisesRegex(FEReferenceError,'flux'):
            prepare_reference(2,2,1.,1.,1.,velocity_boundaries(lambda x,z:x,0.),pressure_mean=0.)
        invalid=velocity_boundaries(); invalid['left']['u']=('velocity',0.,'traction',0.)
        with self.assertRaises(FEReferenceError):
            prepare_reference(2,2,1.,1.,1.,invalid,pressure_mean=0.)

    def test_direct_memory_preflight_and_coordinate_refusals(self):
        for options in ({'nx':16,'nz':16}, {'max_work_bytes':1024}, {'max_work_bytes':256*1024**2}):
            arguments=dict(nx=2,nz=2,width=1.,height=1.,eta=1.,boundaries=velocity_boundaries(),pressure_mean=0.)
            arguments.update(options)
            with self.assertRaisesRegex(FEReferenceError,'budget|allowance'):
                prepare_reference(**arguments)
        result=solve_reference(2,2,1.,1.,1.,zero_force,velocity_boundaries(),pressure_mean=0.)
        with self.assertRaises(FEReferenceError):
            result.evaluate([[1.1,0.]])
        with self.assertRaises(FEReferenceError):
            result.evaluate([[float('nan'),0.]])
        self.assertLess(result.projected_work_bytes,128*1024**2)


if __name__=='__main__':
    unittest.main()
