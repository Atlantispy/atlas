"""Bounded supplied-property W03/W04 evolution, not a geological calibration."""
from concurrent.futures import CancelledError
from dataclasses import replace
import threading
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.evolving_flexure import (W04RigidityState, W04AbsoluteReferenceLoad,
    PreparedEvolvingW04Support, project_evolving_w04_support)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.variable_flexure import VariableRigidityFlexure
from atlas_tectonics.w03_workflow import advance_w03_columns
from atlas_tectonics.w04_workflow import PreparedW04Support
from test_w03_workflow import initialise, workflow_fixture
from test_w04_workflow import surface
from test_w04_regional_workflow import CONTINUOUS, exterior
from test_w04_variable_workflow import profile, ACCURACY


SOURCE = 'explicit synthetic absolute support datum and supplied property history'
PERIODIC = replace(CONTINUOUS,boundary='periodic-repetition',region_boundary=None)


def supplied(state,p):
    return W04RigidityState(state,p,source_id=SOURCE)


def datum(state,surface_input,pressure,policy=PERIODIC,**kwargs):
    return W04AbsoluteReferenceLoad(state,surface_input,policy,pressure,source_id=SOURCE,**kwargs)


class EvolvingW04Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = initialise(workflow_fixture(cells=8,length_m=8.))
        cls.s0 = surface(cls.ref)
        cls.p0 = profile(cls.ref,te=np.ones(8),far=False)
        cls.p1 = profile(cls.ref,te=np.full(8,2.),far=False)
        cls.r0 = supplied(cls.ref,cls.p0)
        cls.r1 = supplied(cls.ref,cls.p1)
        cls.pressure = 100.*np.sin(2*np.pi*(np.arange(8)+.5)/8)

    def prepare(self,pressure=None,**kwargs):
        q = self.pressure if pressure is None else pressure
        return PreparedEvolvingW04Support(self.ref,self.s0,PERIODIC,
            reference_rigidity=self.r0,reference_absolute_load=datum(self.ref,self.s0,q),
            accuracy=ACCURACY,**kwargs)

    def direct(self,p,q):
        with VariableRigidityFlexure(p,PERIODIC.elastic,'periodic',ACCURACY) as operator:
            return operator.solve(np.r_[q,0.,0.])[:,1,0]

    def test_changed_rigidity_unchanged_nonzero_load_is_not_zero(self):
        expected = self.direct(self.p1,self.pressure)-self.direct(self.p0,self.pressure)
        with self.prepare() as plan:
            result = plan.solve(self.ref,self.s0,rigidity=self.r1)
        assert_allclose(result.downward_displacement_from_reference_m,expected,rtol=0,atol=1e-15)
        self.assertGreater(np.max(np.abs(expected)),1e-5)
        assert_array_equal(result.downward_load_pa,np.zeros(8))
        assert_allclose(result.sediment_surface_change_m,-expected,rtol=0,atol=1e-15)
        self.assertEqual(result.descriptor()['response'],'current-absolute-minus-reference-absolute')
        self.assertTrue(result.descriptor()['total_reference_result'])
        self.assertEqual(result.descriptor()['thermal_owner'],'flexure')
        self.assertEqual(result.descriptor()['w03_local_displacement'],'diagnostic-only-excluded')
        with self.assertRaises(ValueError): result.absolute_values[0,0] = 0.

    def test_changed_rigidity_and_load_match_two_absolute_solves(self):
        extra = np.linspace(-10.,30.,8)
        now = surface(self.ref,pressure=extra)
        expected = self.direct(self.p1,self.pressure+extra)-self.direct(self.p0,self.pressure)
        with self.prepare() as plan:
            result = plan.solve(self.ref,now,rigidity=self.r1)
            again = plan.solve(self.ref,now,rigidity=self.r1)
        assert_allclose(result.downward_displacement_from_reference_m,expected,rtol=0,atol=1e-15)
        assert_array_equal(result.values,again.values)
        self.assertEqual(result.result_id,again.result_id)
        assert_array_equal(result.absolute_values[:,:2],np.column_stack((self.pressure,self.pressure+extra)))
        wrong = self.direct(self.p1,extra)
        self.assertGreater(np.max(np.abs(expected-wrong)),1e-5)
        one = project_evolving_w04_support(self.ref,self.ref,self.s0,now,PERIODIC,
            reference_rigidity=self.r0,current_rigidity=self.r1,
            reference_absolute_load=datum(self.ref,self.s0,self.pressure),accuracy=ACCURACY)
        self.assertEqual(result.result_id,one.result_id)

    def test_unchanged_profile_preserves_original_w04_change_and_once_owned_surfaces(self):
        now = surface(self.ref,pressure=np.linspace(0.,100.,8))
        with PreparedW04Support(self.ref,self.s0,PERIODIC,rigidity=self.p0,accuracy=ACCURACY) as old:
            expected = old.solve(self.ref,now)
        with self.prepare() as plan:
            result = plan.solve(self.ref,now,rigidity=self.r0)
            zero = plan.solve(self.ref,self.s0,rigidity=self.r0)
        assert_array_equal(result.values,expected.values)
        assert_array_equal(zero.values,np.zeros((8,8)))
        self.assertEqual(result.descriptor()['response'],'fixed-operator-load-delta')

    def test_real_w03_load_change_uses_existing_inventory_thermal_and_water_accounts(self):
        current = advance_w03_columns(self.ref,time_s=1e6,top_effective_stress_pa=0.)
        now = surface(current)
        p = profile(current,te=np.full(8,2.),far=False)
        with PreparedW04Support(self.ref,self.s0,PERIODIC,rigidity=self.p0,accuracy=ACCURACY) as old:
            expected = old.solve(current,now)
        with self.prepare() as plan:
            result = plan.solve(current,now,rigidity=supplied(current,p))
        assert_array_equal(result.values[:,:5],expected.values[:,:5])
        direct = self.direct(p,self.pressure+expected.downward_load_pa)-self.direct(self.p0,self.pressure)
        assert_allclose(result.downward_displacement_from_reference_m,direct,atol=1e-15,rtol=0)
        assert_allclose(result.sediment_surface_change_m+result.downward_displacement_from_reference_m,
            expected.sediment_surface_change_m+expected.downward_displacement_from_reference_m,atol=1e-15)
        self.assertGreater(np.max(np.abs(result.values[:,2])),0.)

    def test_profile_time_frame_geometry_and_absolute_datum_mismatches_refuse(self):
        current = advance_w03_columns(self.ref,time_s=1e6,top_effective_stress_pa=0.)
        with self.prepare() as plan:
            with self.assertRaisesRegex(TectonicsError,'exact W03 state/time'):
                plan.solve(current,surface(current),rigidity=self.r1)
            with self.assertRaisesRegex(TectonicsError,'geometry'):
                plan.solve(self.ref,self.s0,rigidity=supplied(self.ref,profile(self.ref,halo=1,far=False)))
        with self.assertRaisesRegex(TectonicsError,'frame/datum/epoch'):
            supplied(self.ref,profile(self.ref,frame='different',far=False))
        other = surface(self.ref,pressure=np.ones(8))
        with self.assertRaisesRegex(TectonicsError,'absolute reference datum'):
            PreparedEvolvingW04Support(self.ref,self.s0,PERIODIC,reference_rigidity=self.r0,
                reference_absolute_load=datum(self.ref,other,self.pressure),accuracy=ACCURACY)
        for value in (np.zeros(7),np.full(8,np.nan)):
            with self.assertRaises((TectonicsError,ValueError)):
                datum(self.ref,self.s0,value)

    def test_absolute_validity_is_not_hidden_by_zero_load_change(self):
        with self.assertRaisesRegex(TectonicsError,'absolute reference'):
            self.prepare(np.full(8,1e9))
        # The initial stiff plate passes, but the changed weak plate under the
        # same nonzero pressure fails even though delta load is exactly zero.
        strict = replace(PERIODIC,max_abs_slope=.0003)
        with PreparedEvolvingW04Support(self.ref,self.s0,strict,reference_rigidity=self.r1,
                reference_absolute_load=datum(self.ref,self.s0,self.pressure,strict),accuracy=ACCURACY) as plan:
            with self.assertRaisesRegex(TectonicsError,'absolute current'):
                plan.solve(self.ref,self.s0,rigidity=self.r0)

    def test_continuing_halos_use_both_absolute_exteriors_and_reject_unknown_load(self):
        old = exterior(self.ref,[80.],[20.],far=(30.,10.))
        now = exterior(self.ref,[40.],[60.],far=(15.,25.))
        p0 = profile(self.ref,halo=1,te=np.ones(10))
        p1 = profile(self.ref,halo=1,te=np.full(10,1.5))
        ref_load = datum(self.ref,self.s0,self.pressure,CONTINUOUS,exterior=old)
        with PreparedEvolvingW04Support(self.ref,self.s0,CONTINUOUS,
                reference_rigidity=supplied(self.ref,p0),reference_absolute_load=ref_load,
                accuracy=ACCURACY,reference_exterior=old) as plan:
            result = plan.solve(self.ref,self.s0,rigidity=supplied(self.ref,p1),exterior=now)
            with self.assertRaisesRegex(TectonicsError,'exterior uncertainty'):
                plan.solve(self.ref,self.s0,rigidity=supplied(self.ref,p1),
                           exterior=exterior(self.ref,[40.],[60.],bounds=(1.,0.)))
        responses = []
        for p,e in ((p0,old),(p1,now)):
            with VariableRigidityFlexure(p,CONTINUOUS.elastic,CONTINUOUS.region_boundary,ACCURACY) as operator:
                responses.append(operator.solve(np.r_[e.left_pressure_pa,self.pressure,e.right_pressure_pa,
                                                        e.far_left_pa,e.far_right_pa])[1:-1,1,0])
        assert_allclose(result.downward_displacement_from_reference_m,responses[1]-responses[0],atol=1e-15,rtol=0)

    def test_operator_replacement_cancellation_and_close_keep_bounded_retention(self):
        budget = WorkBudget(128<<20)
        plan = self.prepare(budget=budget)
        with plan:
            previous = None
            for thickness in (1.5,2.,2.5,1.5):
                r = supplied(self.ref,profile(self.ref,te=np.full(8,thickness),far=False))
                plan.solve(self.ref,self.s0,rigidity=r)
                if previous is not None:
                    self.assertTrue(previous._closed)
                    self.assertEqual(previous.setup_bytes,0)
                previous = plan._current_operator
                retained = budget.reserved_bytes
                plan.solve(self.ref,self.s0,rigidity=r)
                self.assertEqual(budget.reserved_bytes,retained)
            flag = threading.Event(); flag.set()
            with self.assertRaises(CancelledError):
                plan.solve(self.ref,self.s0,rigidity=self.r1,cancel=flag)
            plan.solve(self.ref,self.s0,rigidity=self.r0)
            self.assertIsNone(plan._current_operator)
            self.assertTrue(previous._closed)
            self.assertLessEqual(budget.peak_reserved_bytes,128<<20)
        self.assertEqual(budget.reserved_bytes,0)
        with self.assertRaisesRegex(TectonicsError,'closed'):
            plan.solve(self.ref,self.s0,rigidity=self.r0)
        tiny = WorkBudget(1024)
        with self.assertRaises(MemoryLimitError): self.prepare(budget=tiny)
        self.assertEqual(tiny.reserved_bytes,0)

    def test_loaded_implementation_change_is_refused(self):
        with self.prepare() as plan:
            with patch('atlas_tectonics.evolving_flexure.CAP',64<<20):
                with self.assertRaisesRegex(TectonicsError,'loaded implementation changed'):
                    plan.solve(self.ref,self.s0,rigidity=self.r0)


if __name__ == '__main__':
    unittest.main()
