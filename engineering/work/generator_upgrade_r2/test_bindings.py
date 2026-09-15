from dataclasses import replace
from fractions import Fraction
import hashlib
from pathlib import Path
import tempfile
import unittest

from .bindings import (Product, SnowPacket, compatibility_plan, climate_role,
    consume_snow_liquid, owner_bindings, captured, strict_json, ecology_role)


def h(s):return hashlib.sha256(s.encode()).hexdigest()


def products():
    dependencies={'terrain':{},'substrate':{},'climate_macro':{'terrain':h('terrain')},
        'climate_local':{'terrain':h('terrain'),'climate_macro':h('climate_macro')},
        'snowfall':{'climate_local':h('climate_local')},'snowmelt':{'snowfall':h('snowfall')},
        'water':{'terrain':h('terrain'),'climate_local':h('climate_local'),'snowmelt':h('snowmelt')},
        'soil_hydraulic':{'water':h('water'),'climate_local':h('climate_local'),'substrate':h('substrate')},
        'soil_substrate':{'substrate':h('substrate')},
        'biomes':{'climate_local':h('climate_local'),'soil_hydraulic':h('soil_hydraulic')}}
    return [Product(r,r,h(r),'grid',p,'WORKING NON-CANON') for r,p in dependencies.items()]


def snow():return SnowPacket('swe-output','snow-ledger','month01','catchment','climate',10,5,8,7,'synthetic')


def consume(packet=None,**changes):
    kw=dict(total_precipitation_m3=20,rain_m3=15,expected_producer_id='snow-ledger',
            period_id='month01',domain_id='catchment',climate_id='climate')
    kw.update(changes)
    return consume_snow_liquid(packet or snow(),**kw)


class BindingTests(unittest.TestCase):
    def test_actual_five_owner_decision_files(self):
        r=owner_bindings()
        self.assertEqual(len(r['owner_slices']),5)
        self.assertIn('physical_frame',r['pending_owners'])
        self.assertFalse(r['global_generation_hold'])
        self.assertFalse(r['physical_acceptance'])
        self.assertEqual(r['ecology_delta']['owner_sha256'],'e43b6edabced8f9c652da23e8f1dfa49fa2d7ff30488eaf79eac49edce08965b')

    def test_ecology_reference_cannot_certify_candidate_climate(self):
        r=ecology_role(parent_branch='ECO_01_RETAINED_REFERENCE',selected_climate_branch='R1T14C_A_G_CANDIDATE',
            arrays_match_parents=True,water_topology_bound=True,organism_id=17)
        self.assertEqual(r['state'],'CONDITIONAL_UNKNOWN');self.assertFalse(r['global_hold'])

    def test_ecology_new_water_topology_required_not_old_reach_freeze(self):
        r=ecology_role(parent_branch='SUCCESSOR_CANDIDATE',selected_climate_branch='R1T14C_A_G_CANDIDATE',
            arrays_match_parents=False,water_topology_bound=False,organism_id=10)
        self.assertEqual(len(r['reasons']),2);self.assertTrue(r['parent_independent_meanings_reusable'])

    def test_hs11_binding_limits_only_dependent_products(self):
        kw=dict(parent_branch='SUCCESSOR_CANDIDATE',selected_climate_branch='R1T14C_A_G_CANDIDATE',
            arrays_match_parents=True,water_topology_bound=True,requires_hs11_host_gate=True)
        self.assertEqual(ecology_role(**kw,organism_id=11)['state'],'CONDITIONAL_UNKNOWN')
        self.assertEqual(ecology_role(**kw,organism_id=10)['state'],'BOUND_SCENARIO_ONLY')
        self.assertEqual(ecology_role(**kw,organism_id=11,hs11_host_decision_bound=True)['state'],'BOUND_SCENARIO_ONLY')

    def test_hs11_material_permission_is_bound_not_still_pending(self):
        r=owner_bindings()['hs11_permission']
        self.assertFalse(r['essential_permission_choice_pending'])
        self.assertFalse(r['guild_support_alone_proves_recruitment'])
        self.assertFalse(r['named_guild_or_rate_selected'])
        self.assertEqual(r['primary_source_status'],'PRIMARY_DOMAIN_SOURCE_STATUS_UNVERIFIED')

    def test_distributed_organism_not_fake_individual_density(self):
        r=ecology_role(parent_branch='ECO_01_RETAINED_REFERENCE',selected_climate_branch='C1_R1_ORIGINAL',
            arrays_match_parents=True,water_topology_bound=True,organism_id=19)
        self.assertEqual(r['entity_density'],'NOT_APPLICABLE');self.assertFalse(r['realised_range_generated'])

    def test_unchanged_declared_dependencies(self):
        p=products();r=compatibility_plan(p,{x.role:x.content_sha256 for x in p},frame_id='grid')
        self.assertTrue(all(x['state']=='REUSABLE_BY_IDENTITY' for x in r['products'].values()))
        self.assertFalse(r['physical_acceptance'])

    def test_terrain_change_invalidates_only_dependent_fields(self):
        p=products();selected={x.role:x.content_sha256 for x in p};selected['terrain']=h('new terrain')
        r=compatibility_plan(p,selected,frame_id='grid')['products']
        for name in ('terrain','climate_macro','climate_local','snowfall','snowmelt','water','soil_hydraulic','biomes'):
            self.assertEqual(r[name]['state'],'RECOMPUTE_OR_BIND')
        for name in ('substrate','soil_substrate'):self.assertEqual(r[name]['state'],'REUSABLE_BY_IDENTITY')

    def test_climate_stale_hydraulic_soil_not_reusable(self):
        p=products();selected={x.role:x.content_sha256 for x in p};selected['climate_local']=h('new climate')
        r=compatibility_plan(p,selected,frame_id='grid')['products']
        self.assertEqual(r['soil_hydraulic']['state'],'RECOMPUTE_OR_BIND')
        self.assertEqual(r['soil_substrate']['state'],'REUSABLE_BY_IDENTITY')

    def test_missing_output_is_not_global_stop(self):
        p=products();selected={x.role:x.content_sha256 for x in p};p=[x for x in p if x.role!='snowmelt']
        r=compatibility_plan(p,selected,frame_id='grid')
        self.assertEqual(r['products']['water']['state'],'RECOMPUTE_OR_BIND')
        self.assertEqual(r['products']['substrate']['state'],'REUSABLE_BY_IDENTITY')
        self.assertFalse(r['global_hold'])

    def test_wrong_frame_rejects_reuse(self):
        p=products();r=compatibility_plan(p,{x.role:x.content_sha256 for x in p},frame_id='other')
        self.assertTrue(all(x['state']=='RECOMPUTE_OR_BIND' for x in r['products'].values()))

    def test_required_parents_cannot_be_omitted(self):
        with self.assertRaises(ValueError):Product('soil_hydraulic','s',h('s'),'grid',{},'WORKING NON-CANON')

    def test_duplicate_roles_cannot_select_coequal_winner(self):
        p=products()
        with self.assertRaises(ValueError):compatibility_plan(p+p,{x.role:x.content_sha256 for x in p},frame_id='grid')

    def test_cycle_rejected(self):
        p=[Product('terrain','t',h('t'),'g',{'substrate':h('s')},'WORKING NON-CANON'),
           Product('substrate','s',h('s'),'g',{'terrain':h('t')},'WORKING NON-CANON')]
        with self.assertRaises(ValueError):compatibility_plan(p,{'terrain':h('t'),'substrate':h('s')},frame_id='g')

    def test_unknown_source_not_reused(self):
        p=[replace(products()[0],source_status='UNKNOWN')]
        self.assertEqual(compatibility_plan(p,{'terrain':h('terrain')},frame_id='grid')['products']['terrain']['state'],'RECOMPUTE_OR_BIND')

    def test_parent_identity_cannot_be_mutated_after_validation(self):
        parents={'terrain':h('terrain')}
        p=Product('climate_macro','c',h('c'),'grid',parents,'WORKING NON-CANON')
        parents['terrain']=h('changed')
        self.assertEqual(p.parents['terrain'],h('terrain'))
        with self.assertRaises(TypeError):p.parents['terrain']=h('changed')

    def test_g_c4_placeholder_cannot_be_sensitivity(self):
        with self.assertRaises(ValueError):climate_role(branch='R1T14C_A_G_CANDIDATE',sensitivity='G_C4_LOWER_EVAPORATION',terrain_matches=True,purpose='RECONCILED_SNAPSHOT')

    def test_c4_cannot_cross_parent(self):
        with self.assertRaises(ValueError):climate_role(branch='R1T14C_A_G_CANDIDATE',sensitivity='C4_UNRESOLVED_SENSITIVITY',terrain_matches=True,purpose='RECONCILED_SNAPSHOT')

    def test_evaporation_alternatives_remain_separate(self):
        for sensitivity in ('A_EVAP_750','A_EVAP_900'):
            r=climate_role(branch='R1T14C_A_G_CANDIDATE',sensitivity=sensitivity,terrain_matches=False,purpose='RECONCILED_SNAPSHOT')
            self.assertEqual(r['action'],'RECOMPUTE_MACRO_LOCAL_AND_AFFECTED_DESCENDANTS')
            self.assertIsNone(r['chosen_evaporation_endpoint'])

    def test_fixed_forcing_does_not_certify_reconciled_snapshot(self):
        r=climate_role(branch='C1_R1_ORIGINAL',sensitivity='R1',terrain_matches=False,purpose='FIXED_FORCING_COMPARISON')
        self.assertEqual(r['action'],'FIXED_FORCING_COMPARISON_ONLY')

    def test_hash_check_prevents_repins(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source';p.write_bytes(b'abc')
            self.assertEqual(captured(p,hashlib.sha256(b'abc').hexdigest()),b'abc')
            with self.assertRaises(ValueError):captured(p,h('wrong'))
            with self.assertRaises(ValueError):captured(p,hashlib.sha256(b'abc').hexdigest(),2)

    def test_strict_json_rejects_duplicate_nonfinite(self):
        for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}'):
            with self.assertRaises(ValueError):strict_json(raw)

    def test_actual_snow_to_liquid_conservation(self):
        r=consume();self.assertEqual(r['liquid_input_m3'],'23');self.assertEqual(r['retained_swe_m3'],'7')
        self.assertEqual(r['water_residual_m3'],'0')

    def test_melt_consumed_once_across_json_restart(self):
        import json
        r=consume();history=json.loads(json.dumps(r['consumed']))
        with self.assertRaises(ValueError):consume(consumed=history)

    def test_snow_history_growth_stays_within_bound(self):
        r=consume(consumed=[str(i) for i in range(4095)])
        self.assertEqual(len(r['consumed']),4096)
        with self.assertRaises(ValueError):consume(consumed=[str(i) for i in range(4096)])

    def test_renamed_packet_cannot_double_melt(self):
        r=consume()
        with self.assertRaises(ValueError):consume(replace(snow(),packet_id='renamed'),consumed=r['consumed'])

    def test_snow_total_precipitation_is_not_liquid_twice(self):
        with self.assertRaises(ValueError):consume(rain_m3=20)

    def test_wrong_snow_producer_cannot_add_second_flux(self):
        with self.assertRaises(ValueError):consume(expected_producer_id='other-producer')

    def test_snow_parent_period_domain_must_match(self):
        for key in ('climate_id','period_id','domain_id'):
            with self.assertRaises(ValueError):consume(**{key:'wrong'})

    def test_unknown_snow_volume_is_not_zero(self):
        for key in ('initial_swe_m3','snowfall_m3','melt_m3','final_swe_m3'):
            with self.assertRaises(ValueError):replace(snow(),**{key:None})

    def test_snow_mass_imbalance_rejected(self):
        with self.assertRaises(ValueError):replace(snow(),melt_m3=9)

    def test_fractional_water_and_prior_storage(self):
        p=SnowPacket('p','snow-ledger','month01','catchment','climate',Fraction(1,3),0,Fraction(1,6),Fraction(1,6),'test')
        r=consume(p,total_precipitation_m3=0,rain_m3=0)
        self.assertEqual(r['liquid_input_m3'],'1/6')


if __name__=='__main__':unittest.main()
