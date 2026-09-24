"""Lossless scientific result records and hostile/corrupt envelope refusals."""
from concurrent.futures import CancelledError
from copy import deepcopy
from dataclasses import replace
from threading import Event
import unittest

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.evolving_flexure import PreparedEvolvingW04Support
from atlas_tectonics.evolving_mechanics import RegionalMechanicalRequest
from atlas_tectonics.regional_checkpoint import _hash, _json
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.tectonic_history_codec import (
    pack_history_result, restore_history_result, history_result_id, history_result_nbytes,
)
from test_underthrust import fixture, parcels, rectangle
from test_evolving_flexure import supplied, datum, PERIODIC, ACCURACY
from test_w03_workflow import initialise, workflow_fixture
from test_w04_workflow import surface
from test_w04_variable_workflow import profile
from test_evolving_mechanics import prepare, request, context, pressure, material, boundary, block, pattern


def reseal(meta):
    meta['content_id'] = _hash(_json({k:v for k,v in meta.items() if k != 'content_id'}))


class TectonicHistoryCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lower, upper = parcels()
        upper = replace(upper,specific_enthalpy_j_kg=None,enthalpy_source_id=None)
        with fixture(material=(lower,upper),receivers=(('visible',rectangle(-10.,2.,-20.,20.)),)) as plan:
            cls.under = plan.evaluate(1.)
        ref = initialise(workflow_fixture(cells=8,length_m=8.))
        initial = surface(ref)
        p0 = profile(ref,te=np.ones(8),far=False)
        p1 = profile(ref,te=np.full(8,2.),far=False)
        q = 100*np.sin(2*np.pi*(np.arange(8)+.5)/8)
        with PreparedEvolvingW04Support(ref,initial,PERIODIC,reference_rigidity=supplied(ref,p0),
                reference_absolute_load=datum(ref,initial,q),accuracy=ACCURACY) as plan:
            cls.flexure = plan.solve(ref,surface(ref,pressure=np.linspace(-10.,30.,8)),rigidity=supplied(ref,p1))
            cls.fixed = plan.solve(ref,initial,rigidity=supplied(ref,p0))
        c = context(time_s=3.)
        with prepare(c) as plan:
            cls.regional = plan.evaluate(request(c))

    def roundtrip(self, original):
        budget = WorkBudget(128 << 20)
        arrays,metadata = pack_history_result(original,budget=budget)
        restored = restore_history_result(arrays,metadata,budget=budget)
        self.assertIs(type(restored),type(original))
        self.assertEqual(history_result_id(restored),history_result_id(original))
        self.assertEqual(restored.descriptor(),original.descriptor())
        self.assertGreater(history_result_nbytes(restored),0)
        self.assertEqual(budget.reserved_bytes,0)
        for a in arrays.values():
            with self.assertRaises(ValueError): a.setflags(write=True)
        return restored

    def test_underthrust_complete_roundtrip_geometry_signed_unknown_heat(self):
        restored = self.roundtrip(self.under)
        self.assertEqual(restored.enthalpy_known,(True,False))
        self.assertLess(restored.enthalpy_j[0].sum(),0)
        self.assertEqual(restored.destination_ids,('visible','retained-exterior'))
        for field in ('volume_m3','mass_kg','enthalpy_j','boundary_work_j',
                      'gravitational_change_j','displacement_m'):
            np.testing.assert_array_equal(getattr(restored,field),getattr(self.under,field))
            with self.assertRaises(ValueError): getattr(restored,field).setflags(write=True)
        for actual,expected in zip(restored.polygons,self.under.polygons):
            self.assertEqual(actual.geometry_id,expected.geometry_id)
            self.assertEqual(actual.wkb,expected.wkb)

    def test_w04_changed_and_fixed_operator_absolute_and_delta_roundtrip(self):
        for original in (self.flexure,self.fixed):
            with self.subTest(response=original.descriptor()['response']):
                restored = self.roundtrip(original)
                for field in ('values','absolute_values','reservoir_surface_known'):
                    np.testing.assert_array_equal(getattr(restored,field),getattr(original,field))
                    with self.assertRaises(ValueError): getattr(restored,field).setflags(write=True)

    def test_regional_wrapper_and_all_fields_roundtrip(self):
        restored = self.roundtrip(self.regional)
        self.assertEqual(restored.mechanics.result_id,self.regional.mechanics.result_id)
        self.assertEqual(restored.array_names,self.regional.array_names)
        for name in restored.array_names:
            np.testing.assert_array_equal(restored.array(name),self.regional.array(name))
            with self.assertRaises(ValueError): restored.array(name).setflags(write=True)

    def test_regional_surface_pressure_input_binding_roundtrip(self):
        c = context(time_s=5.)
        with prepare(c,types=pattern(True)) as plan:
            result = plan.evaluate(request(c,top_traction=True,shear=0.,surface=pressure(c)))
        self.roundtrip(result)

    def test_regional_signed_zero_inputs_survive_sum_and_pressure_replacement(self):
        c = context(time_s=5.)
        body = block(c,'body-force',dict(u=np.full((c.nz,c.nx+1),-0.),
            w=np.full((c.nz+1,c.nx),-0.)),effects=('zero-force',))
        motion = boundary(c,0.,types=pattern(True),top_normal=-0.)
        supplied = RegionalMechanicalRequest(material(c),(body,),motion,surface_pressure=pressure(c,-0.))
        with prepare(c,types=pattern(True)) as plan:
            result = plan.evaluate(supplied)
        restored = self.roundtrip(result)
        self.assertEqual(restored.descriptor()['request'],supplied.descriptor())

    def test_malformed_descriptor_and_nonfinite_payload_refuse_cleanly(self):
        arrays,meta = pack_history_result(self.under)
        forged = deepcopy(meta); forged['descriptor']['parcels'] = None; reseal(forged)
        with self.assertRaises(TectonicsError): restore_history_result(arrays,forged)
        bad = dict(arrays); bad['fields'] = arrays['fields'].copy(); bad['fields'].flat[0] = np.nan
        with self.assertRaisesRegex(TectonicsError,'nonfinite'): restore_history_result(bad,meta)
        for arrays in ({'huge':np.empty((2_097_153,0))},{'object':np.array([object()])}):
            with self.assertRaises(TectonicsError): restore_history_result(arrays,meta)

    def test_invalid_type_and_forged_intrinsic_identity_refuse(self):
        for invalid in (None,self.regional.mechanics,object()):
            with self.subTest(value=type(invalid)),self.assertRaises(TectonicsError):
                pack_history_result(invalid)
        forged = replace(self.under,state_id='0'*64)
        with self.assertRaisesRegex(TectonicsError,'intrinsic identity'):
            pack_history_result(forged)

    def test_missing_extra_changed_arrays_and_catalogue_shape_refuse(self):
        arrays,meta = pack_history_result(self.flexure)
        candidates = [dict(arrays,extra=arrays['wet']),{k:v for k,v in arrays.items() if k != 'wet'}]
        changed = dict(arrays); changed['values'] = arrays['values'].copy(); changed['values'][0,0] += 1
        candidates.append(changed)
        for candidate in candidates:
            with self.subTest(fields=tuple(candidate)),self.assertRaises(TectonicsError):
                restore_history_result(candidate,meta)
        altered = dict(arrays); altered['absolute'] = arrays['absolute'].reshape(-1)
        forged = deepcopy(meta); forged['arrays']['absolute']['shape'] = list(altered['absolute'].shape)
        reseal(forged)
        with self.assertRaisesRegex(TectonicsError,'shape/dtype'):
            restore_history_result(altered,forged)

    def test_rehashed_unknown_heat_and_geometry_descriptors_refuse(self):
        arrays,meta = pack_history_result(self.under)
        for key,value in (('enthalpy_known',[True,True]),('current_geometry_ids',['0'*64]*2)):
            forged = deepcopy(meta); forged['descriptor'][key] = value; reseal(forged)
            with self.subTest(field=key),self.assertRaises(TectonicsError):
                restore_history_result(arrays,forged)

    def test_rehashed_regional_time_binding_refuses(self):
        arrays,meta = pack_history_result(self.regional)
        forged = deepcopy(meta)
        forged['descriptor']['request']['context']['time_s'] += 1
        # Even a caller able to rehash the wrapper cannot disguise its mismatch
        # against the actual dated mechanical result.
        forged['result_id'] = _hash(_json(forged['descriptor'])); reseal(forged)
        with self.assertRaises(TectonicsError):
            restore_history_result(arrays,forged)

    def test_cancellation_budget_and_nonfinite_metadata_release(self):
        stopped = Event(); stopped.set()
        arrays,meta = pack_history_result(self.under)
        budget = WorkBudget(128 << 20)
        for operation,args in ((pack_history_result,(self.under,)),(restore_history_result,(arrays,meta))):
            with self.assertRaises(CancelledError): operation(*args,budget=budget,cancel=stopped)
            tiny = WorkBudget(1)
            with self.assertRaises(MemoryLimitError): operation(*args,budget=tiny)
            self.assertEqual(tiny.reserved_bytes,0)
        forged = deepcopy(meta); forged['descriptor']['time_s'] = float('nan')
        with self.assertRaises(TectonicsError): restore_history_result(arrays,forged,budget=budget)
        self.assertEqual(budget.reserved_bytes,0)


if __name__ == '__main__':
    unittest.main()
