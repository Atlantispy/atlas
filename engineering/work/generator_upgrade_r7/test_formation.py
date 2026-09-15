"""Independent finite-stock, kinetic and operational-profile checks; no maps."""
from dataclasses import replace
from decimal import Decimal as D, localcontext
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from . import formation as f
from . import organic as o

E='Synthetic dimensional coefficient/protocol; not a Diadem calibrated value'
S='SYNTHETIC TEST'
OLD_PATH=Path(__file__).resolve().parents[1]/'terrain_model_r2'/'materials.py'
OLD_SHA256='097f7f3ca8c5dd2af9f06e1b7478aa3081c55e22f1dba4384159ad471cc4f961'


def test_data_bindings():
    return {str(OLD_PATH):OLD_SHA256,str(f.OWNER_PATH):f.OWNER_SHA256}


def layer(key='rock',phase='bedrock',mass=2000,material='one',porosity=0,candidates=None):
    if candidates is None:candidates=('R',) if phase=='bedrock' else ('C',)
    return f.FormationLayer(key,material,phase,F(mass),F(2000),F(porosity),(F(mass),F(),F(),F()),candidates,E,S)


def state(*layers):return f.FormationState('column',tuple(layers) if layers else (layer(),),F(10))


def law(material='one',**changes):
    values=dict(material_id=material,bare_rate_m_s=.001,cover_scale_m=.5,regolith_porosity=F(1,2),
        dissolved_mass_fraction=F(),reference_temperature_k=300.,activation_energy_j_mol=0.,gas_constant_j_mol_k=8.314,
        minimum_temperature_k=270.,maximum_temperature_k=330.,regime='DEPTH_LIMITED_NONSELECTIVE_ROCK_DISAGGREGATION',
        evidence=E,source_status=S)
    values.update(changes);return f.ProductionLaw(**values)


def exposure(key='exposure',**changes):
    values=dict(exposure_id=key,duration_seconds=F(100),soil_temperature_k=300.,water_filled_pore_fraction=1.,
        environment_state_id='actual-water-and-declared-soil-temperature',evidence=E,source_status=S)
    values.update(changes);return f.ExposureSegment(**values)


def produce(initial=None,segment=None,parameters=None,cover=F()):
    return f.form_snapshot(state() if initial is None else initial,(exposure() if segment is None else segment,),
        (law() if parameters is None else parameters,),organic_cover_m=cover)


def fragment(initial=None,segment=None,rate=.003):
    return f.alter_particle_sizes(layer('soil','immobile_regolith',100,porosity=F(1,2)) if initial is None else initial,
        rate_per_second=rate,exposure=exposure() if segment is None else segment,
        reference_temperature_k=300.,activation_energy_j_mol=0.,gas_constant_j_mol_k=8.314,
        minimum_temperature_k=270.,maximum_temperature_k=330.,evidence=E)


def organic(key,carbon=F(),support='column',status=S):
    initial=o.initial_state(key,support,F(carbon),F(),evidence=E,source_status=status)
    parameters=o.OrganicLaw(0.,0.,F(),F(1,2),300.,0.,0.,8.314,270.,330.,((0.,0.),(1.,1.)),
        (('OXIC',1.,1.),),('AERATED_MINERAL','ORGANIC_DOMINATED'),E,S)
    forcing=o.OrganicForcing(F(),F(),F(),300.,1.,'OXIC','AERATED_MINERAL','climate','water',E,E,E,S)
    return o.advance_layer(initial,(forcing,),parameters)


def protocol():return f.HorizonProtocol('declared-carbon-enrichment',F(1,100),F(3,200),E)


def inverse_integral_oracle(h,rate,scale,gamma,duration,available):
    """Independent 80-digit monotone integral inversion, not producer log1p."""
    with localcontext() as ctx:
        ctx.prec=80
        h,p,L,g,t,cap=[D(str(x)) for x in (h,rate,scale,gamma,duration,available)]
        lo,hi=D(0),cap
        for _ in range(280):
            x=(lo+hi)/2
            elapsed=(h/L).exp()*((g*x/L).exp()-1)*L/(g*p) if g else (h/L).exp()*x/p
            if elapsed<t:lo=x
            else:hi=x
        return float((lo+hi)/2)


class FormationTests(unittest.TestCase):
    def test_age_zero_is_exact_identity_of_materials(self):
        initial=state();result=produce(initial,exposure(duration_seconds=0))
        self.assertEqual(result['state'].layers,initial.layers)
        self.assertFalse(result['geometry_changed']);self.assertEqual(result['transfers'],[])

    def test_wfps_zero_or_zero_bare_rate_means_explicit_no_production(self):
        for segment,parameters in ((exposure(water_filled_pore_fraction=0),law()),(exposure(),law(bare_rate_m_s=0))):
            result=produce(segment=segment,parameters=parameters)
            self.assertEqual(result['state'].layers,state().layers)
            self.assertFalse(result['requires_water_rebind'])

    def test_single_contact_matches_independent_integral_inversion(self):
        initial=state(layer('cover','mobile_sediment',100,porosity=F(1,2)),layer())
        result=produce(initial,parameters=law(dissolved_mass_fraction=F(1,4)))
        expected=inverse_integral_oracle(.1,.001,.5,1.5,100,1)
        self.assertAlmostEqual(float(result['transfers'][0]['rock_consumed_kg_m2']/2000),expected,delta=2e-16)
        self.assertEqual(result['state'].layers[0],initial.layers[0])

    def test_density_yield_bulk_geometry_and_exact_origin_closure(self):
        initial=state(replace(layer(),porosity=F(1,4)))
        result=produce(initial,parameters=law(dissolved_mass_fraction=F(1,5)))
        transfer=result['transfers'][0];consumed=transfer['rock_consumed_kg_m2']
        self.assertEqual(transfer['regolith_produced_kg_m2'],consumed*F(4,5))
        self.assertEqual(transfer['dissolved_kg_m2'],consumed*F(1,5))
        self.assertEqual(sum(transfer['size_origin_consumed_kg_m2']),consumed)
        self.assertEqual(sum(transfer['size_origin_dissolved_kg_m2']),transfer['dissolved_kg_m2'])
        self.assertEqual(result['final_surface_elevation_m']-result['initial_surface_elevation_m'],
            consumed*F(4,5)/1000-consumed/1500)
        self.assertEqual(result['mineral_balances'][0]['residual_kg_m2'],0)

    def test_retained_r2_actual_operator_matching_units_density_yield(self):
        code=OLD_PATH.read_bytes();self.assertEqual(hashlib.sha256(code).hexdigest(),OLD_SHA256)
        name='_r7_retained_r2_material_reference';module=types.ModuleType(name);module.__file__=str(OLD_PATH)
        sys.modules[name]=module
        try:
            exec(compile(code,str(OLD_PATH),'exec'),module.__dict__)
            # Explicit synthetic 1000-second reference year; no implicit terrestrial calendar.
            old=module.soil_production_step(area_m2=1,rock_available_kg=2000,regolith_kg=100,mobile_kg=0,
                duration_years=.1,parameters=module.SoilProductionParameters(1,.5,2000,.25,2000,.5,2000,.5,.25,0,E))
            result=produce(state(layer('cover','immobile_regolith',100,porosity=F(1,2)),
                replace(layer(),porosity=F(1,4))),parameters=law(dissolved_mass_fraction=F(1,4)))
            transfer=result['transfers'][0]
            self.assertAlmostEqual(float(transfer['rock_consumed_kg_m2']),old.rock_consumed_kg,delta=2e-12)
            self.assertAlmostEqual(float(transfer['regolith_produced_kg_m2']),old.regolith_produced_kg,delta=2e-12)
            self.assertAlmostEqual(float(result['final_surface_elevation_m']-result['initial_surface_elevation_m']),old.surface_change_m,delta=2e-15)
        finally:sys.modules.pop(name,None)

    def test_explicit_fixed_organic_cover_attenuates_without_mineral_mass(self):
        bare=produce();covered=produce(cover=F(1,2))
        self.assertLess(covered['transfers'][0]['rock_consumed_kg_m2'],bare['transfers'][0]['rock_consumed_kg_m2'])
        self.assertEqual(covered['mineral_balances'][0]['initial_kg_m2'],2000)

    def test_all_dissolved_gamma_zero_has_finite_linear_lowering(self):
        result=produce(parameters=law(dissolved_mass_fraction=1))
        transfer=result['transfers'][0]
        self.assertAlmostEqual(float(transfer['rock_consumed_kg_m2']),200,delta=2e-13)
        self.assertIsNone(transfer['product_layer_id']);self.assertEqual(transfer['regolith_produced_kg_m2'],0)
        self.assertEqual(transfer['dissolved_kg_m2'],transfer['rock_consumed_kg_m2'])

    def test_two_finite_material_contacts_preserve_identity_and_inactive_tail(self):
        initial=state(layer('upper',mass=2),layer('lower',mass=3,material='two'))
        result=f.form_snapshot(initial,(exposure(duration_seconds=100),),(law(),law('two')),organic_cover_m=0)
        self.assertEqual(len(result['transfers']),2)
        self.assertEqual([r['rock_consumed_kg_m2'] for r in result['transfers']],[2,3])
        self.assertEqual([r['material_id'] for r in result['mineral_balances']],['one','two'])
        self.assertTrue(all(l.phase=='immobile_regolith' for l in result['state'].layers))
        self.assertGreater(result['exposures'][0]['inactive_or_exhausted_seconds'],0)
        self.assertEqual(sum(r['final_kg_m2'] for r in result['mineral_balances']),5)

    def test_all_dissolved_contact_time_uses_remaining_interval_for_next_material(self):
        initial=state(layer('upper',mass=20),layer('lower',mass=2000,material='two'))
        result=f.form_snapshot(initial,(exposure(duration_seconds=100),),(law(dissolved_mass_fraction=1),
            law('two',bare_rate_m_s=.002,dissolved_mass_fraction=1)),organic_cover_m=0)
        first,second=result['transfers']
        self.assertAlmostEqual(float(first['interval_end_seconds']),10,delta=1e-12)
        self.assertAlmostEqual(float(second['rock_consumed_kg_m2']),360,delta=1e-11)

    def test_no_buried_material_touched_before_top_contact_exhausted(self):
        initial=state(layer(),layer('deep',material='two'))
        result=f.form_snapshot(initial,(exposure(),),(law(),law('two')),organic_cover_m=0)
        self.assertEqual(result['state'].layers[-1],initial.layers[-1])

    def test_equal_driver_time_partition_preserves_bulk_solution(self):
        full=produce()
        half=produce(segment=exposure('first',duration_seconds=50))
        fine=produce(half['state'],exposure('second',duration_seconds=50))
        self.assertAlmostEqual(float(full['state'].surface_elevation_m),float(fine['state'].surface_elevation_m),delta=5e-15)
        self.assertAlmostEqual(float(full['state'].layers[-1].mineral_mass_kg_m2),float(fine['state'].layers[-1].mineral_mass_kg_m2),delta=1e-12)
        self.assertEqual(len(fine['state'].layers),3)  # Separate cohorts are not flattened.

    def test_positive_temperature_and_moisture_drivers_change_real_mass(self):
        parameters=law(activation_energy_j_mol=40000)
        cool=produce(segment=exposure(soil_temperature_k=290.),parameters=parameters)
        warm=produce(segment=exposure(soil_temperature_k=310.),parameters=parameters)
        dry=produce(segment=exposure(water_filled_pore_fraction=.2),parameters=parameters)
        reference=produce(parameters=parameters)
        self.assertLess(cool['transfers'][0]['rock_consumed_kg_m2'],warm['transfers'][0]['rock_consumed_kg_m2'])
        self.assertLess(dry['transfers'][0]['rock_consumed_kg_m2'],reference['transfers'][0]['rock_consumed_kg_m2'])

    def test_unknown_required_driver_produces_no_partial_stock(self):
        for segment in (exposure(soil_temperature_k=None),exposure(source_status='UNKNOWN')):
            result=produce(segment=segment);self.assertEqual(result['status'],'UNKNOWN');self.assertIsNone(result['state'])

    def test_outside_thermal_range_and_underflow_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'outside'):produce(segment=exposure(soil_temperature_k=260))
        with self.assertRaisesRegex(ValueError,'underflow'):produce(segment=exposure(water_filled_pore_fraction=1e-200),parameters=law(bare_rate_m_s=1e-200))
        with self.assertRaisesRegex(ValueError,'under'):produce(cover=1000)

    def test_replay_unknown_law_and_interbedded_geometry_refused(self):
        result=produce()
        with self.assertRaisesRegex(ValueError,'replay'):produce(result['state'])
        with self.assertRaisesRegex(ValueError,'every finite'):f.form_snapshot(state(),(exposure(),),(),organic_cover_m=0)
        with self.assertRaisesRegex(ValueError,'interbedded'):produce(state(layer(),layer('buried','immobile_regolith')))

    def test_fresh_product_not_aged_or_automatically_A_or_B(self):
        result=produce();fresh=result['state'].layers[0]
        self.assertEqual(fresh.inherited_horizon_candidates,('C',))
        self.assertEqual(fresh.particle_masses_kg_m2[1:],(0,0,0))
        self.assertIn('no full-interval',result['transfers'][0]['exposure_inheritance'])

    def test_exact_state_roundtrip_and_unrecognised_fields_reject(self):
        result=produce()['state'];record=json.loads(json.dumps(f.state_to_dict(result),allow_nan=False))
        self.assertEqual(f.state_from_dict(record),result)
        record['invented']=1
        with self.assertRaises(ValueError):f.state_from_dict(record)

    def test_dataclass_domain_and_identity_guards(self):
        with self.assertRaises(ValueError):replace(layer(),mineral_mass_kg_m2=True)
        with self.assertRaises(ValueError):replace(layer(),porosity=1)
        with self.assertRaises(ValueError):replace(layer(),particle_masses_kg_m2=(F(1),)*4)
        with self.assertRaises(ValueError):state(layer(),layer())
        with self.assertRaises(ValueError):state(layer(),replace(layer('other'),grain_density_kg_m3=2200))
        for candidate in ('A','E','B','O'):
            with self.assertRaises(ValueError):replace(layer(),inherited_horizon_candidates=(candidate,))


class ParticleTests(unittest.TestCase):
    def test_coarse_chain_matches_independent_decimal_poisson_probabilities(self):
        result=fragment()
        with localcontext() as ctx:
            ctx.prec=80;x=D('0.3');survival=(-x).exp()
            expected=[survival,survival*x,survival*x*x/2,1-survival*(1+x+x*x/2)]
        masses=result['layer'].particle_masses_kg_m2
        for actual,wanted in zip(masses,expected):self.assertAlmostEqual(float(actual/100),float(wanted),delta=2e-16)
        self.assertEqual(sum(masses),100);self.assertEqual(result['chemical_release_kg_m2'],0)

    def test_mixed_particle_origins_close_and_no_upward_size_transfer(self):
        initial=replace(layer('soil','mobile_sediment',100),particle_masses_kg_m2=(F(10),F(20),F(30),F(40)))
        result=fragment(initial)
        self.assertEqual(sum(result['layer'].particle_masses_kg_m2),100)
        for origin,row in enumerate(result['transition_rows']):
            probabilities=row['represented_probabilities'];self.assertEqual(sum(probabilities),1)
            self.assertEqual(probabilities[:origin],(F(),)*origin)
        self.assertGreaterEqual(result['layer'].particle_masses_kg_m2[3],40)
        self.assertIn('NOT_PREDICTED',result['clay_mineralogy'])

    def test_zero_age_rate_and_moisture_identity(self):
        for segment,rate in ((exposure(duration_seconds=0),.1),(exposure(),0),(exposure(water_filled_pore_fraction=0),.1)):
            initial=layer('soil','immobile_regolith',100)
            self.assertEqual(fragment(initial,segment,rate)['layer'],initial)

    def test_explicit_cohort_semigroup(self):
        full=fragment();first=fragment(segment=exposure('a',duration_seconds=40))
        fine=fragment(first['layer'],exposure('b',duration_seconds=60))
        for actual,wanted in zip(fine['layer'].particle_masses_kg_m2,full['layer'].particle_masses_kg_m2):
            self.assertAlmostEqual(float(actual),float(wanted),delta=3e-14)

    def test_tiny_and_large_admitted_doses_retain_positive_branches(self):
        for dose in (1e-100,500):
            result=fragment(segment=exposure(duration_seconds=1),rate=dose)
            self.assertTrue(all(x>0 for x in result['layer'].particle_masses_kg_m2))
            self.assertEqual(sum(result['layer'].particle_masses_kg_m2),100)

    def test_intact_rock_unknown_and_unrepresented_dose_guard(self):
        with self.assertRaisesRegex(ValueError,'intact bedrock'):fragment(layer())
        self.assertEqual(fragment(segment=exposure(source_status='UNKNOWN'))['status'],'UNKNOWN')
        with self.assertRaisesRegex(ValueError,'underflow'):fragment(segment=exposure(duration_seconds=F(1,10**200)),rate=1e-200)
        with self.assertRaisesRegex(ValueError,'envelope'):fragment(rate=1000)

    def test_fault_injected_transition_tail_cannot_be_normalised_into_false_pass(self):
        with patch.object(f,'gammainc',return_value=.5):
            with self.assertRaisesRegex(ValueError,'probability closure'):fragment()


class HorizonTests(unittest.TestCase):
    def profile(self,carbon=2,**kwargs):
        initial=state(layer('a','mobile_sediment',100,porosity=F(1,2)),layer('c','immobile_regolith',200,porosity=F(1,2)),layer())
        rows={'a':organic('a',carbon),'c':organic('c')}
        return initial,rows,{'a':(F(),F()),'c':(F(),F())},kwargs

    def diagnose(self,carbon=2,geometry=True,**kwargs):
        initial,rows,parents,_=self.profile(carbon)
        if geometry:
            thickness={l.layer_id:l.thickness_m for l in initial.layers}
            thickness['a']+=(F(carbon)*2/F(1000))/(1-F(1,2))
            kwargs.update(reconciled_mineral_thickness_m=thickness,geometry_evidence=E)
        return f.diagnose_horizons(initial,rows,parents,protocol(),**kwargs)

    def test_actual_organic_output_makes_A_C_R_and_reconciled_solum(self):
        result=self.diagnose()
        self.assertEqual([r['candidates'] for r in result['horizons']],[('A',),('C',),('R',)])
        self.assertEqual(result['mineral_pedogenic_solum_depth_m'],F(108,1000))
        self.assertFalse(result['requires_geometry_reconciliation'])

    def test_positive_mixed_carbon_without_packing_cannot_claim_mineral_only_depth(self):
        result=self.diagnose(geometry=False)
        self.assertEqual(result['horizons'][0]['candidates'],('A',))
        self.assertIsNone(result['mineral_pedogenic_solum_depth_m'])
        self.assertIsNone(result['horizons'][0]['bottom_depth_m'])
        self.assertTrue(result['requires_geometry_reconciliation'])

    def test_threshold_interval_preserves_A_C_ambiguity(self):
        result=self.diagnose(carbon=F(5,4))
        self.assertEqual(result['horizons'][0]['candidates'],('A','C'))
        self.assertIsNone(result['mineral_pedogenic_solum_depth_m'])

    def test_explicit_parent_reference_not_deposition_age_controls_inherited_C(self):
        initial,rows,parents,_=self.profile()
        parents['a']=(F(2,100),F(2,100))
        result=f.diagnose_horizons(initial,rows,parents,protocol(),absent_solum_evidence=E,
            reconciled_mineral_thickness_m={l.layer_id:l.thickness_m+F(1,100) for l in initial.layers},geometry_evidence=E)
        self.assertEqual(result['horizons'][0]['candidates'],('C',))
        self.assertEqual(result['mineral_pedogenic_solum_depth_m'],0)

    def test_bare_C_R_zero_requires_explicit_absence_not_just_unclassified_profile(self):
        result=self.diagnose(carbon=0)
        self.assertIsNone(result['mineral_pedogenic_solum_depth_m'])
        self.assertEqual(self.diagnose(carbon=0,absent_solum_evidence=E)['mineral_pedogenic_solum_depth_m'],0)
        initial,rows,parents,_=self.profile(0);rows.pop('a')
        unknown=f.diagnose_horizons(initial,rows,parents,protocol(),absent_solum_evidence=E)
        self.assertIsNone(unknown['mineral_pedogenic_solum_depth_m'])

    def test_conflicting_absence_rejected(self):
        with self.assertRaisesRegex(ValueError,'conflicts'):self.diagnose(absent_solum_evidence=E)

    def test_inherited_E_B_preserved_but_not_invented_from_fragmentation(self):
        initial=state(layer('e','mobile_sediment',100,candidates=('E',)),layer('b','immobile_regolith',200,candidates=('B',)),layer())
        result=f.diagnose_horizons(initial,{'e':organic('e'),'b':organic('b')},{},protocol())
        self.assertEqual([r['candidates'] for r in result['horizons']],[('E',),('B',),('R',)])
        self.assertEqual(result['mineral_pedogenic_solum_depth_m'],F(3,20))
        self.assertEqual(fragment()['layer'].inherited_horizon_candidates,('C',))

    def test_O_mantle_is_separate_from_mineral_solum(self):
        mantle={'result':organic('o',2),'bulk_density_kg_m3':100,'layer_id':'o','evidence':E}
        result=self.diagnose(surface_organic=mantle)
        self.assertEqual(result['surface_organic_thickness_m'],F(4,100))
        self.assertEqual(result['mineral_pedogenic_solum_depth_m'],F(108,1000))
        self.assertEqual(result['horizons'][1]['top_depth_m'],F(4,100))

    def test_cross_layer_support_duplicate_mantle_and_forged_stock_reject(self):
        initial,rows,parents,_=self.profile()
        for bad in (dict(rows['a'],layer_id='c'),dict(rows['a'],support_id='other'),dict(rows['a'],schema='score'),
                    dict(rows['a'],final_organic_carbon_kg_m2=3)):
            with self.assertRaises(ValueError):f.diagnose_horizons(initial,dict(rows,a=bad),parents,protocol())
        with self.assertRaisesRegex(ValueError,'duplicates'):self.diagnose(surface_organic={
            'result':organic('a',2),'bulk_density_kg_m3':100,'layer_id':'a','evidence':E})

    def test_unknown_organic_and_O_are_unknown_not_zero(self):
        initial,rows,parents,_=self.profile();rows['a']=organic('a',status='UNKNOWN')
        result=f.diagnose_horizons(initial,rows,parents,protocol())
        self.assertEqual(result['horizons'][0]['candidates'],())
        self.assertIsNone(result['mineral_pedogenic_solum_depth_m'])
        mantle={'result':organic('o',status='UNKNOWN'),'bulk_density_kg_m3':100,'layer_id':'o','evidence':E}
        self.assertIsNone(self.diagnose(surface_organic=mantle)['surface_organic_thickness_m'])

    def test_geometry_identity_volume_and_provenance_guards(self):
        initial,rows,parents,_=self.profile()
        for mapping in ({'a':F(1)},dict(a=F(1,10000),c=F(1),rock=F(1))):
            with self.assertRaises(ValueError):f.diagnose_horizons(initial,rows,parents,protocol(),
                reconciled_mineral_thickness_m=mapping,geometry_evidence=E)
        with patch.object(f,'OWNER_SHA256','0'*64):
            with self.assertRaisesRegex(ValueError,'no silent repin'):self.diagnose()

    def test_unknown_conflicting_material_cannot_promote_inherited_horizons(self):
        for status in ('UNKNOWN','INCOMPLETE','CONFLICT'):
            initial=state(replace(layer('b','immobile_regolith',100,candidates=('B',)),source_status=status),layer())
            result=f.diagnose_horizons(initial,{'b':organic('b')},{},protocol(),
                reconciled_mineral_thickness_m={l.layer_id:l.thickness_m for l in initial.layers},geometry_evidence=E)
            self.assertEqual(result['horizons'][0]['candidates'],())
            self.assertEqual(result['material_geometry_status'],'UNKNOWN')
            self.assertIsNone(result['mineral_pedogenic_solum_depth_m'])
            self.assertIsNone(result['horizons'][0]['bottom_depth_m'])

    def test_serialised_organic_result_is_valid_actual_contract(self):
        initial,rows,parents,_=self.profile(0)
        decoded=json.loads(json.dumps(f.plain(rows),allow_nan=False))
        result=f.diagnose_horizons(initial,decoded,parents,protocol(),absent_solum_evidence=E)
        self.assertEqual(result['mineral_pedogenic_solum_depth_m'],0)


if __name__=='__main__':unittest.main()
