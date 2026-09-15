"""R7 actual bound execution and independent small-domain numerical fixtures."""
from copy import deepcopy
import math
from pathlib import Path
import unittest
from unittest.mock import patch

import hillslope_binding as binding
import r4_io
import shoreline_verification as v
from test_shoreline_verification import tiny_prepared


class R7CorrectionTests(unittest.TestCase):
    def test_actual_binding_is_new_source_not_mutated_predecessor(self):
        self.assertEqual(Path(binding.kernel.__file__).parent.name,'terrain_model_r7')
        self.assertEqual(Path(binding.kernel.__file__).name,'hillslope_kernel.py')
        self.assertTrue(any(p['name']=='R6/hillslope_binding.py' for p in r4_io.verify_dependencies()))
        self.assertTrue(all(p['name'].startswith('R7-corrected-hillslope/') for p in binding.verify()))

    def test_positive_extreme_diffusion_is_not_lost(self):
        k=binding.kernel
        state=k.State(k.Grid(2,2,1,1),(1,0,1,0),(1,1,1,1),(0,0,0,0),2700,2700)
        final,report=k.hillslope_step(state,[1e-320]*4,1e308)
        expected=2*(1e-320*1e308)
        self.assertGreater(report['internal_transferred_solid_m3'],0)
        self.assertAlmostEqual(report['internal_transferred_solid_m3']/expected,1,places=13)
        self.assertEqual(math.fsum(final.mobile_solid_m3),4.)

    def test_harmonic_mean_independent_symmetry_and_extremes(self):
        mean=binding.kernel._harmonic_mean
        for a,b in ((1.,3.),(1e-320,1e-320),(5e-324,1e308),(1e308,1e308)):
            self.assertEqual(mean(a,b),mean(b,a))
            self.assertGreaterEqual(mean(a,b),min(a,b))
            self.assertLessEqual(mean(a,b),max(a,b))
        self.assertEqual(mean(1.,3.),1.5)

    def test_scaled_products_recover_finite_intermediate_overflow_and_underflow(self):
        product=binding.kernel._positive_product
        self.assertAlmostEqual(product((1e308,1e308,1e-308),'fixture')/1e308,1)
        self.assertAlmostEqual(product((1e-308,1e-308,1e308),'fixture')/1e-308,1)
        self.assertEqual(product((0.,1e308),'fixture'),0.)
        for values in ((1e308,1e308),(1e-308,1e-308),(-1.,2.),(math.nan,)):
            with self.subTest(values=values),self.assertRaises(ValueError):product(values,'fixture')

    def test_new_refinement_controls_are_forwarded_without_mutation(self):
        p=tiny_prepared();p['forcing'].update(critical_gradient=[2.],erosion_reference_runoff_m_year=1.)
        before=deepcopy(p['forcing']);args=v._arguments(p,.1,.8)
        self.assertEqual(args['critical_gradient'],[2.]);self.assertEqual(args['erosion_reference_runoff_m_year'],1.)
        args['critical_gradient'][0]=3.
        self.assertEqual(p['forcing'],before)

    def test_refinement_actual_execution_accepts_explicit_new_controls(self):
        p=tiny_prepared();p['forcing'].update(critical_gradient=[2.],erosion_reference_runoff_m_year=1.)
        args=v._arguments(p,.1,.8)
        final,report=v.driver.advance(p['initial_state'],**args)
        self.assertAlmostEqual(final.time_years,.8)
        self.assertAlmostEqual(math.fsum(final.liquid_m3),.8)

    def test_omitted_controls_preserve_legacy_and_unknown_control_rejected(self):
        p=tiny_prepared();args=v._arguments(p,.1,.8)
        self.assertNotIn('critical_gradient',args);self.assertNotIn('erosion_reference_runoff_m_year',args)
        p['forcing']['invented_physics']=1
        with self.assertRaises(v.VerificationError):v._arguments(p,.1,.8)

    def test_actual_invalid_critical_gradient_and_reference_fail(self):
        for change in ({'critical_gradient':[0.]},{'erosion_reference_runoff_m_year':0.}):
            p=tiny_prepared();p['forcing'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                v.driver.advance(p['initial_state'],**v._arguments(p,.1,.8))


if __name__=='__main__':unittest.main()
