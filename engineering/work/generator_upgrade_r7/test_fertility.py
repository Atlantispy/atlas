from dataclasses import replace
from fractions import Fraction
import math
import unittest

import numpy as np
from scipy.integrate import solve_ivp

from . import fertility as f

E = 'SYNTHETIC TEST: unfertilised finite natural reference; no empirical calibration'


def chemistry():
    return f.Chemistry('matrix-01', 6., .2, 'SYNTHETIC_JOINT_EFFECTIVE_CEC', E)


def law(nutrient='N', **overrides):
    return replace(f.NutrientLaw(nutrient, .01, 0., 1., 293.15, 0., 8.314462618,
                                'matrix-01', 'NET_MINERALISABLE_'+nutrient, E), **overrides)


def exposure(**overrides):
    return replace(f.WaterExposure(10., 293.15, 1., .1, .001, 0., None, E), **overrides)


def run(pool=None, kinetics=None, segments=None, **kwargs):
    return f.advance_nutrient(pool or f.NutrientPool('N', .2, .1, E), kinetics or law(),
                              segments or (exposure(),), sorbent_mass_kg_m2=100.,
                              chemistry=kwargs.get('chemistry', chemistry()), support_id='profile-01')


def exchange():
    c = chemistry()
    return f.exchange_capacity((f.ExchangeComponent('mineral', 90., 10., c.cec_method, E),
                                f.ExchangeComponent('organic', 10., 100., c.cec_method, E)),
                               dry_fine_earth_and_organic_mass_kg_m2=100., chemistry=c, support_id='profile-01')


def protocol():
    return f.FertilityProtocol('SYNTHETIC_NPK_CHARGE', .01, .002, .01, 1000., E)


def results():
    return {n: run(f.NutrientPool(n, .2, .1, E), law(n)) for n in f.NUTRIENTS}


class NutrientTests(unittest.TestCase):
    def test_closed_release(self):
        r=run(segments=(exposure(downward_m_s=0.),))
        self.assertAlmostEqual(r['reserve_kg_m2'], .2*math.exp(-.1), places=14)
        self.assertAlmostEqual(r['labile_kg_m2'], .1+.2*(-math.expm1(-.1)), places=14)
        self.assertEqual(Fraction(r['exported_kg_m2']), 0)

    def test_equal_release_flush(self):
        r=run()
        self.assertAlmostEqual(r['labile_kg_m2'], (.1+.01*.2*10)*math.exp(-.1), places=14)

    def test_no_release(self):
        r=run(kinetics=law(release_per_s=0.))
        self.assertEqual(r['reserve_kg_m2'], .2)
        self.assertAlmostEqual(r['labile_kg_m2'], .1*math.exp(-.1), places=14)

    def test_no_flow_no_release_identity(self):
        r=run(kinetics=law(release_per_s=0.), segments=(exposure(downward_m_s=0.),))
        self.assertEqual((r['reserve_kg_m2'],r['labile_kg_m2']),(.2,.1))

    def test_zero_duration(self):
        r=run(segments=(exposure(duration_s=0.),))
        self.assertEqual((r['reserve_kg_m2'],r['labile_kg_m2']),(.2,.1))
        self.assertEqual(Fraction(r['exported_kg_m2']), 0)

    def test_zero_nutrient_stays_zero(self):
        r=run(f.NutrientPool('N',0.,0.,E))
        self.assertEqual(r['labile_kg_m2'],0.)
        self.assertEqual(Fraction(r['exported_kg_m2']),0)

    def test_imported_constant_oracle(self):
        r=run(kinetics=law(release_per_s=0.),segments=(exposure(upward_m_s=.0005,upward_concentration_kg_m3=.2),))
        self.assertAlmostEqual(r['labile_kg_m2'], .1*math.exp(-.1)+.01*(-math.expm1(-.1)),places=14)
        self.assertAlmostEqual(float(Fraction(r['imported_kg_m2'])),.001)

    def test_upward_does_not_cancel_gross_downward(self):
        a=run(); b=run(segments=(exposure(upward_m_s=.001,upward_concentration_kg_m3=0.),))
        self.assertEqual(a['labile_kg_m2'],b['labile_kg_m2'])
        self.assertGreater(float(Fraction(b['exported_kg_m2'])),0)

    def test_positive_upward_unknown_refused(self):
        with self.assertRaises(ValueError):exposure(upward_m_s=.001)

    def test_dry_flow_refused(self):
        with self.assertRaises(ValueError):exposure(water_storage_m=0.)

    def test_dry_labile_is_not_solution(self):
        r=run(segments=(exposure(water_storage_m=0.,downward_m_s=0.,wetness=0.),))
        self.assertEqual(r['dissolved_kg_m2'],0.)
        self.assertEqual(r['reversibly_sorbed_kg_m2'],0.)
        self.assertEqual(r['dry_labile_kg_m2'],.1)

    def test_sorption_reduces_export(self):
        a=run();b=run(kinetics=law(kd_m3_kg=.01))
        self.assertGreater(b['labile_kg_m2'],a['labile_kg_m2'])
        self.assertGreater(b['reversibly_sorbed_kg_m2'],0)
        self.assertAlmostEqual(b['reversibly_sorbed_kg_m2']/b['dissolved_kg_m2'],10.)

    def test_nitrate_not_cec_sorbed(self):
        with self.assertRaises(ValueError):law(species='NITRATE_N',kd_m3_kg=.001)

    def test_partition_closes(self):
        r=run(kinetics=law(kd_m3_kg=.01))
        self.assertAlmostEqual(r['dissolved_kg_m2']+r['reversibly_sorbed_kg_m2']+r['dry_labile_kg_m2'],r['labile_kg_m2'],places=14)

    def test_nutrient_ledger_independent(self):
        r=run(segments=(exposure(upward_m_s=.0001,upward_concentration_kg_m3=.3),))
        residual=Fraction(r['initial_kg_m2'])+Fraction(r['imported_kg_m2'])-Fraction(r['reserve_kg_m2'])-Fraction(r['labile_kg_m2'])-Fraction(r['exported_kg_m2'])
        self.assertEqual(residual,Fraction(r['numerical_residual_kg_m2']))
        self.assertLess(abs(float(residual)),1e-13)

    def test_dop853_independent_oracle(self):
        q=exposure(duration_s=173.,upward_m_s=.00013,upward_concentration_kg_m3=.02)
        k=law(release_per_s=.007,kd_m3_kg=.001)
        r=run(kinetics=k,segments=(q,))
        lam=.001/(.1+.001*100)
        def fun(t,y):return [-.007*y[0],.007*y[0]-lam*y[1]+.00013*.02,lam*y[1]]
        oracle=solve_ivp(fun,[0,173],[.2,.1,0],method='DOP853',rtol=1e-12,atol=1e-14)
        self.assertTrue(oracle.success)
        np.testing.assert_allclose([r['reserve_kg_m2'],r['labile_kg_m2'],float(Fraction(r['exported_kg_m2']))],oracle.y[:,-1],rtol=1e-11,atol=1e-13)

    def test_segment_composition(self):
        a=run(segments=(exposure(duration_s=30.),))
        b=run(segments=(exposure(),)*3)
        self.assertAlmostEqual(a['labile_kg_m2'],b['labile_kg_m2'],places=14)
        self.assertAlmostEqual(float(Fraction(a['exported_kg_m2'])),float(Fraction(b['exported_kg_m2'])),places=14)

    def test_warming_changes_release(self):
        k=law(activation_energy_j_mol=50000.)
        a=run(kinetics=k);b=run(kinetics=k,segments=(exposure(temperature_k=303.15),))
        self.assertLess(b['reserve_kg_m2'],a['reserve_kg_m2'])

    def test_dryness_reduces_release(self):
        a=run();b=run(segments=(exposure(wetness=.1),))
        self.assertGreater(b['reserve_kg_m2'],a['reserve_kg_m2'])

    def test_chemistry_binding_refused(self):
        with self.assertRaises(ValueError):run(chemistry=replace(chemistry(),chemistry_id='wrong'))

    def test_wrong_element_refused(self):
        with self.assertRaises(ValueError):run(kinetics=law('P'))

    def test_empty_exposure_refused(self):
        with self.assertRaises(ValueError):f.advance_nutrient(f.NutrientPool('N',1.,1.,E),law(),(),sorbent_mass_kg_m2=100.,chemistry=chemistry(),support_id='profile-01')

    def test_extreme_exponential_regime_refused(self):
        with self.assertRaises(ValueError):run(segments=(exposure(duration_s=1e10),))

    def test_invalid_numbers(self):
        for value in (True,float('nan'),float('inf'),-1.,10**1000):
            with self.subTest(value=str(value)[:30]):
                with self.assertRaises(ValueError):f.NutrientPool('N',value,0.,E)

    def test_inputs_immutable(self):
        p=f.NutrientPool('N',.2,.1,E); before=repr(p)
        run(p);self.assertEqual(repr(p),before)

    def test_positive_import_underflow_refused(self):
        with self.assertRaises(ValueError):run(segments=(exposure(upward_m_s=1e-200,upward_concentration_kg_m3=1e-200),))

    def test_positive_integrated_import_underflow_refused(self):
        with self.assertRaises(ValueError):run(segments=(exposure(duration_s=1e-200,upward_m_s=1e-100,upward_concentration_kg_m3=1e-100),))


class ExchangeTests(unittest.TestCase):
    def test_mass_weighted_charge(self):
        r=exchange();self.assertEqual(r['cec_cmolc_kg'],19.)
        self.assertEqual(r['exchange_capacity_cmolc_m2'],1900.)

    def test_organic_only_supported(self):
        c=chemistry();r=f.exchange_capacity((f.ExchangeComponent('organic',10.,100.,c.cec_method,E),),dry_fine_earth_and_organic_mass_kg_m2=10.,chemistry=c,support_id='profile-01')
        self.assertEqual(r['cec_cmolc_kg'],100.)

    def test_missing_mass_not_zero_cec(self):
        c=chemistry()
        with self.assertRaises(ValueError):f.exchange_capacity((f.ExchangeComponent('clay',10.,20.,c.cec_method,E),),dry_fine_earth_and_organic_mass_kg_m2=100.,chemistry=c,support_id='profile-01')

    def test_mixed_methods_rejected(self):
        with self.assertRaises(ValueError):f.exchange_capacity((f.ExchangeComponent('clay',10.,20.,'OTHER',E),),dry_fine_earth_and_organic_mass_kg_m2=10.,chemistry=chemistry(),support_id='profile-01')

    def test_duplicate_components_rejected(self):
        c=chemistry();x=f.ExchangeComponent('clay',10.,20.,c.cec_method,E)
        with self.assertRaises(ValueError):f.exchange_capacity((x,x),dry_fine_earth_and_organic_mass_kg_m2=20.,chemistry=c,support_id='profile-01')

    def test_no_soil_is_not_divide_by_zero(self):
        c=chemistry();x=f.ExchangeComponent('clay',0.,20.,c.cec_method,E)
        with self.assertRaises(ValueError):f.exchange_capacity((x,),dry_fine_earth_and_organic_mass_kg_m2=0.,chemistry=c,support_id='profile-01')


class FertilityTests(unittest.TestCase):
    def test_index_is_limiting_factor(self):
        r=f.profile_fertility(results(),exchange(),protocol(),natural_reference_evidence=E)
        self.assertEqual(r['index_0_1'],min(r['factors'].values()))
        self.assertGreater(r['index_0_1'],0.)
        self.assertLess(r['index_0_1'],1.)

    def test_unknown_nutrient_propagates(self):
        rows=results();rows['P']=None
        r=f.profile_fertility(rows,exchange(),protocol(),natural_reference_evidence=E)
        self.assertIsNone(r['index_0_1']);self.assertEqual(r['status'],'UNKNOWN')

    def test_unknown_exchange_propagates(self):
        r=f.profile_fertility(results(),None,protocol(),natural_reference_evidence=E)
        self.assertIsNone(r['index_0_1'])

    def test_actual_zero_is_zero(self):
        rows=results();rows['P']=run(f.NutrientPool('P',0.,0.,E),law('P'))
        r=f.profile_fertility(rows,exchange(),protocol(),natural_reference_evidence=E)
        self.assertEqual(r['index_0_1'],0.)

    def test_no_silent_missing_nutrient(self):
        with self.assertRaises(ValueError):f.profile_fertility({'N':None},None,protocol(),natural_reference_evidence=E)

    def test_reference_must_be_positive(self):
        with self.assertRaises(ValueError):replace(protocol(),nitrogen_reference_kg_m2=0.)

    def test_external_import_not_inherent(self):
        rows=results();rows['N']=run(segments=(exposure(upward_m_s=.0001,upward_concentration_kg_m3=.1),))
        with self.assertRaises(ValueError):f.profile_fertility(rows,exchange(),protocol(),natural_reference_evidence=E)

    def test_mixed_exposure_rejected(self):
        rows=results();rows['N']=run(segments=(exposure(duration_s=20.),))
        with self.assertRaises(ValueError):f.profile_fertility(rows,exchange(),protocol(),natural_reference_evidence=E)

    def test_mixed_exchange_chemistry_rejected(self):
        ex=exchange();ex['chemistry']['ph_water']=7.
        with self.assertRaises(ValueError):f.profile_fertility(results(),ex,protocol(),natural_reference_evidence=E)

    def test_normalisation_is_not_crop_yield(self):
        r=f.profile_fertility(results(),exchange(),protocol(),natural_reference_evidence=E)
        self.assertIn('crop yield',r['excluded'])
        self.assertEqual(r['source_status'],'WORKING NON-CANON')

    def test_protocol_is_explicit_in_result(self):
        r=f.profile_fertility(results(),exchange(),protocol(),natural_reference_evidence=E)
        self.assertEqual(r['protocol']['protocol_id'],'SYNTHETIC_NPK_CHARGE')

    def test_nutrient_mass_mismatch_rejected(self):
        rows=results();rows['P']=f.advance_nutrient(f.NutrientPool('P',.2,.1,E),law('P'),(exposure(),),sorbent_mass_kg_m2=200.,chemistry=chemistry(),support_id='profile-01')
        with self.assertRaises(ValueError):f.profile_fertility(rows,exchange(),protocol(),natural_reference_evidence=E)

    def test_exchange_mass_mismatch_rejected(self):
        c=chemistry();ex=f.exchange_capacity((f.ExchangeComponent('mineral',1000.,10.,c.cec_method,E),),dry_fine_earth_and_organic_mass_kg_m2=1000.,chemistry=c,support_id='profile-01')
        with self.assertRaises(ValueError):f.profile_fertility(results(),ex,protocol(),natural_reference_evidence=E)

    def test_nutrient_support_mismatch_rejected(self):
        rows=results();rows['P']=f.advance_nutrient(f.NutrientPool('P',.2,.1,E),law('P'),(exposure(),),sorbent_mass_kg_m2=100.,chemistry=chemistry(),support_id='other-profile')
        with self.assertRaises(ValueError):f.profile_fertility(rows,exchange(),protocol(),natural_reference_evidence=E)

    def test_exchange_support_mismatch_rejected(self):
        c=chemistry();ex=f.exchange_capacity((f.ExchangeComponent('mineral',100.,10.,c.cec_method,E),),dry_fine_earth_and_organic_mass_kg_m2=100.,chemistry=c,support_id='other-profile')
        with self.assertRaises(ValueError):f.profile_fertility(results(),ex,protocol(),natural_reference_evidence=E)


if __name__ == '__main__':
    unittest.main()
