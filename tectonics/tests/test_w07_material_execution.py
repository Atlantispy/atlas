"""Source/SI/refill integration, not a repeat of the core continuum suite."""
from concurrent.futures import CancelledError,ThreadPoolExecutor
import threading
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


# The two refusal texts are fixed by the R7 decision (1 October 2026): an
# interrupted refill names itself; closed, active and wrong-thread keep theirs.
INTERRUPTED='regional plan invalidated by an interrupted coefficient refill; close it and prepare a new plan'
BUSY='closed/active regional plan or wrong driving thread'


def refusal(call):
    try:call()
    except TectonicsError as exc:return str(exc)
    return None


def during_factorisation(plan,action):
    """Run ``action`` inside the numeric refill; an instance wrapper, not a module patch."""
    original=plan._core._numeric
    def numeric(coefficients,cancel):
        action()
        return original(coefficients,cancel)
    plan._core._numeric=numeric


class AcceptedThenCancel:
    """Cancel token that fires once, at the first check after the plan names ``source``.

    The definition changes only when the refill is accepted, so that check is the
    closing one of the operation. No production function is patched.
    """
    def __init__(self,plan,source):self.plan,self.source,self.fired=plan,source,False
    def is_set(self):
        if not self.fired and self.plan.descriptor()['material_source']==self.source:
            self.fired=True
            return True
        return False


class InterruptedRefill(unittest.TestCase):
    def test_interrupted_refill_refuses_by_name_until_closed(self):
        owner=WorkBudget(128*1024**2)
        plan,ec,ev,bc=layer(budget=owner)
        self.addCleanup(plan.close)
        solve(plan,bc)
        event=threading.Event()
        during_factorisation(plan,event.set)
        with self.assertRaises(CancelledError):
            plan.update_viscosity(2*ec,2*ev,material_source='x',material_sampling='y',cancel=event)
        del plan._core._numeric;event.clear()
        for call in (lambda:solve(plan,bc),lambda:plan.coordinates('p'),
                     lambda:plan.update_viscosity(ec,ev,material_source='x',material_sampling='y')):
            self.assertEqual(refusal(call),INTERRUPTED)
        plan.close()
        self.assertEqual(refusal(lambda:solve(plan,bc)),BUSY)
        self.assertEqual(owner.statistics()['reserved_bytes'],0)

    def test_call_during_a_refill_in_progress_is_refused_as_active_not_interrupted(self):
        plan,ec,ev,bc=layer()
        seen=[]
        def peek():
            # The refill is healthy and still running: same thread, then another.
            with ThreadPoolExecutor(max_workers=1) as worker:
                seen.extend((plan.usable,refusal(lambda:plan.coordinates('p')),
                             worker.submit(refusal,lambda:plan.coordinates('p')).result()))
        with plan:
            during_factorisation(plan,peek)
            plan.update_viscosity(2*ec,2*ev,material_source='twice',material_sampling='exact layered series')
            del plan._core._numeric
            self.assertEqual(seen,[False,BUSY,BUSY])
            self.assertTrue(plan.usable)
            np.testing.assert_array_equal(solve(plan,bc).array('viscosity_center_pa_s'),2*ec)
        # Closed without ever having been interrupted: not usable either.
        self.assertFalse(plan.usable)

    def test_usable_and_descriptor_not_the_exception_say_what_the_plan_holds(self):
        plan,ec,ev,bc=layer()
        self.addCleanup(plan.close)
        self.assertTrue(plan.usable)
        old=plan.descriptor();change=dict(material_source='new',material_sampling='y')
        # Raised before the numeric refill started: nothing changed.
        event=threading.Event();event.set()
        with self.assertRaises(CancelledError):
            plan.update_viscosity(2*ec,2*ev,cancel=event,**change)
        self.assertTrue(plan.usable);self.assertEqual(plan.descriptor(),old)
        np.testing.assert_array_equal(solve(plan,bc).array('viscosity_center_pa_s'),ec)
        # Raised by the closing check: the same exception type, but the new material is held.
        with self.assertRaises(CancelledError):
            plan.update_viscosity(2*ec,2*ev,cancel=AcceptedThenCancel(plan,'new'),**change)
        self.assertTrue(plan.usable);self.assertEqual(plan.descriptor()['material_source'],'new')
        np.testing.assert_array_equal(solve(plan,bc).array('viscosity_center_pa_s'),2*ec)
        # Raised inside the numeric refill: neither; the plan must be closed.
        event.clear();during_factorisation(plan,event.set)
        with self.assertRaises(CancelledError):
            plan.update_viscosity(ec,ev,material_source='old again',material_sampling='y',cancel=event)
        self.assertFalse(plan.usable)
        plan.close()
        self.assertFalse(plan.usable)


if __name__=='__main__':unittest.main()
