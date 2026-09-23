"""Source/SI/refill integration, not a repeat of the core continuum suite."""
import unittest
from unittest import mock
import numpy as np
from atlas_tectonics.regional_execution import PreparedRegionalStokes2D,RegionalMechanicsScales
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget
from w07_interface_reference import layered_sites,layered_velocity


def layer(n=8,interface=.37,budget=None):
    ec,ev=layered_sites(n,n,interface)
    types={s:{'u':'velocity','w':'velocity'} for s in ('left','right','bottom','top')}
    plan=PreparedRegionalStokes2D(n,n,1.,1.,1.,types,scales=RegionalMechanicsScales(1.,1.),
        frame_id='reference',vertical_datum='z0',material_source='layered synthetic',
        physical_mean_pressure_pa=10.,viscosity_center_pa_s=ec,viscosity_vertex_pa_s=ev,
        material_sampling='exact vertical dual-support series compliance',budget=budget)
    bc={s:{c:(layered_velocity(plan.coordinates((s,c))[1],interface) if c=='u' else 0.)
           for c in ('u','w')} for s in types}
    return plan,ec,ev,bc


def solve(plan,bc):
    d=plan.descriptor();n=d['nx']
    return plan.solve(np.zeros((n,n+1)),np.zeros((n+1,n)),bc,frame_id='reference',epoch_id='e',
                      time_s=0.,force_source='explicit zero',boundary_source='exact layered velocity')


class MaterialExecution(unittest.TestCase):
    def test_all_velocity_physical_datum_and_exact_reuse(self):
        plan,ec,ev,bc=layer()
        with plan:
            a=solve(plan,bc)
            np.testing.assert_allclose(a.array('physical_pressure_pa'),10.,atol=1e-8)
            np.testing.assert_allclose(a.array('deviatoric_stress_xz_pa'),1/(.37+.63/1000),atol=1e-8)
            ec[:]=6.;ev[:]=7.
            self.assertIs(a,solve(plan,bc))
            self.assertFalse(a.array('viscosity_center_pa_s').flags.writeable)

    def test_refill_matches_cold_and_changes_identity(self):
        plan,ec,ev,bc=layer()
        with plan:
            first=solve(plan,bc); oldid=plan.plan_id; derivative=plan._core._Bx
            plan.update_viscosity(2*ec,2*ev,material_source='twice',material_sampling='exact layered series')
            self.assertNotEqual(oldid,plan.plan_id);self.assertIs(derivative,plan._core._Bx)
            b=solve(plan,bc)
            np.testing.assert_allclose(b.array('u_m_s'),first.array('u_m_s'),atol=1e-12)
            np.testing.assert_allclose(b.array('deviatoric_stress_xz_pa'),2*first.array('deviatoric_stress_xz_pa'),atol=1e-9)
            self.assertEqual(plan.statistics()['coefficient_refills'],1)
            plan.update_viscosity(2*ec,2*ev,material_source='new provenance',material_sampling='exact layered series')
            self.assertEqual(plan.statistics()['coefficient_reuse_hits'],1)
            self.assertNotEqual(b.result_id,solve(plan,bc).result_id)

    def test_refill_failure_is_closed_to_scientific_reuse(self):
        owner=WorkBudget(128*1024**2)
        plan,ec,ev,bc=layer(budget=owner)
        with plan:
            solve(plan,bc)
            with mock.patch.object(plan._core,'refill_viscosity',side_effect=RuntimeError('numeric failure')):
                with self.assertRaises(RuntimeError):
                    plan.update_viscosity(2*ec,ev,material_source='x',material_sampling='y')
            with self.assertRaises(TectonicsError):solve(plan,bc)
        self.assertEqual(owner.statistics()['reserved_bytes'],0)

    def test_bad_support_or_missing_sampling_refuses(self):
        plan,ec,ev,bc=layer()
        with plan:
            for a,b,tag in ((ec,ev[:-1],'series'),(ec,ev,None),(ec*0,ev,'series')):
                with self.assertRaises(TectonicsError):
                    plan.update_viscosity(a,b,material_source='x',material_sampling=tag)
            self.assertTrue(solve(plan,bc).descriptor()['diagnostics']['gates_passed'])


if __name__=='__main__':unittest.main()
