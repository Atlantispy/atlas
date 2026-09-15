from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import unittest
from unittest.mock import patch
from . import pipeline as p, storage as st, hydromet as hm
from .reference import recipe, twelve_month_windows

SOURCE='0'*64


class ConnectedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recipe=recipe(); cls.result=p.run(cls.recipe,source_sha256=SOURCE)
        cls.model=p.parse(cls.recipe,SOURCE)

    def test_all_coequal_members_really_advance(self):
        self.assertEqual(set(self.result['state']['members']),{s.scenario_id for s in self.model.scenarios})
        for member in self.result['state']['members'].values():
            self.assertEqual(member['physical']['elapsed'],'240')
            self.assertEqual(member['physical']['completed_events'],2)
            self.assertEqual(len(member['joint_history']),4)
            self.assertTrue(all(v['elapsed_seconds']=='240' for v in member['snow'].values()))

    def test_joint_water_closure(self):
        for value in self.result['members'].values():
            self.assertLess(abs(float(F(value['joint_residual_m3']))),self.recipe['coupling_controls']['joint_budget_atol_m3'])

    def test_snow_is_distinct_and_not_reset(self):
        final=[]
        for member in self.result['state']['members'].values():
            first,last=member['joint_history'][0],member['joint_history'][-1]
            for key in member['snow']:
                rows=[r['cells'][key]['snow_ledger'] for r in member['joint_history']]
                for a,b in zip(rows,rows[1:]):self.assertEqual(a['final_swe_m'],b['initial_swe_m'])
                self.assertEqual(rows[-1]['final_swe_m'],member['snow'][key]['swe_m'])
                self.assertEqual(F(first['cells'][key]['snow_ledger']['rain_m']),0)
                self.assertGreater(F(last['cells'][key]['snow_ledger']['rain_m']),0)
            final.append(member['snow']['upper']['swe_m'])
        self.assertEqual(len(set(final)),3)

    def test_generated_liquid_is_rain_plus_melt_not_all_precipitation(self):
        for member in self.result['state']['members'].values():
            for joint,physical in zip(member['joint_history'],member['physical']['history']):
                expected=F()
                for key,row in joint['cells'].items():
                    ledger=row['snow_ledger']; area=self.model.physical.profiles[key].column.area_m2
                    self.assertEqual(F(ledger['liquid_to_soil_m']),F(ledger['rain_m'])+F(ledger['melt_m']))
                    expected+=(F(ledger['liquid_to_soil_m'])+F(row['liquid_transfer_roundoff_m']))*area
                self.assertAlmostEqual(float(expected),float(F(physical['liquid_input_m3'])),places=9)

    def test_actual_et_is_positive_but_not_assumed_equal_to_potential(self):
        for member in self.result['state']['members'].values():
            actual=sum((F(r['actual_et_m3']) for r in member['physical']['history']),F())
            potential=sum((F(c['potential_root_demand_m'])*self.model.physical.profiles[k].column.area_m2
                           for r in member['joint_history'] for k,c in r['cells'].items()),F())
            self.assertGreater(actual,0); self.assertGreater(potential,actual)

    def test_terrain_and_physical_material_actually_change(self):
        for member in self.result['state']['members'].values():
            self.assertNotEqual(member['physical']['profiles']['upper'],self.recipe['physical_recipe']['cells']['upper']['profile'])
            self.assertTrue(any(F(b['exported_mass_kg'])>0 for r in member['physical']['history'] for b in r['terrain']['material_balances']))

    def test_atmospheric_water_never_exceeds_finite_inlet(self):
        for member in self.result['state']['members'].values():
            for row in member['joint_history']:
                a=row['atmospheric_moisture_ledger']
                self.assertEqual(F(a['water_mass_residual_kg_s']),0)
                self.assertLessEqual(F(a['precipitation_kg_s']),F(a['inlet_water_kg_s']))

    def test_air_to_surface_roundoff_is_separate_and_in_complete_budget(self):
        for member in self.result['state']['members'].values():
            for joint,physical in zip(member['joint_history'],member['physical']['history']):
                self.assertEqual(F(joint['precipitation_m3'])-F(joint['atmospheric_precipitation_m3']),F(joint['atmosphere_surface_transfer_roundoff_m3']))
                residual=F(joint['initial_total_water_m3'])+F(joint['atmospheric_precipitation_m3'])+F(physical['bottom_in_m3']) \
                    -F(physical['actual_et_m3'])-F(physical['bottom_out_m3'])-F(physical['runoff_export_m3']) \
                    -F(physical['sediment_porewater_export_m3'])-F(joint['final_total_water_m3'])
                self.assertEqual(residual,F(joint['joint_residual_m3']))

    def test_actual_humidity_aware_phase_is_used(self):
        for member in self.result['state']['members'].values():
            for row in member['joint_history']:
                for value in row['cells'].values():
                    self.assertEqual(value['phase_temperature_basis'],'SUPPLIED_WET_BULB')
                    self.assertLessEqual(value['phase_temperature_c'],value['temperature_c'])

    def test_final_diagnostic_recomputed_for_final_terrain(self):
        for name,value in self.result['members'].items():
            raw=self.result['state']['members'][name]['physical']['profiles']
            self.assertEqual(value['final_terrain_sha256'],p.digest(raw))
            elevations={r['cell_id']:r['elevation_m'] for r in value['final_terrain_climate_diagnostic']['receipt']['cells']}
            for key,profile in raw.items():
                actual=p.r3.si.HydraulicProfile.from_dict(profile)
                self.assertEqual(elevations[key],float(actual.column.surface_m))
            self.assertNotEqual(value['final_terrain_sha256'],self.result['state']['members'][name]['joint_history'][-1]['antecedent_terrain_sha256'])

    def test_all_accepted_intervals_pass_whole_chain_gate(self):
        for member in self.result['state']['members'].values():
            gates=[r['coupled_acceptance'] for r in member['joint_history'] if 'coupled_acceptance' in r]
            self.assertEqual(len(gates),2)
            for gate in gates:
                for interval in gate['accepted_intervals']:
                    self.assertLessEqual(interval['error_ratio'],1)
                    self.assertIn('upper/potential_reference_evaporation_m',interval['components'])
                    self.assertIn('upper/snow_change',interval['components'])

    def test_scope_does_not_claim_production_or_annual_history(self):
        self.assertFalse(self.result['production_installed']);self.assertFalse(self.result['canon_changed'])
        self.assertIn('not a global circulation model',self.result['limits'][0])
        self.assertEqual(self.result['source_status'],'WORKING NON-CANON')

    def test_saved_stop_resume_equals_uninterrupted_exactly(self):
        first=p.run(self.recipe,stop_after=1,source_sha256=SOURCE)
        cp=st.checkpoint(first['state'],recipe_sha256=p.digest(self.recipe),source_sha256=SOURCE)
        resumed=p.run(self.recipe,resume=cp,source_sha256=SOURCE)
        self.assertEqual(resumed,self.result)


class RecipeAndReplayTests(unittest.TestCase):
    def invalid(self,mutator):
        r=recipe();mutator(r)
        with self.assertRaises((ValueError,TypeError)):p.parse(r,SOURCE)

    def test_unknown_top_field(self):self.invalid(lambda r:r.update(unbound='bad'))
    def test_duplicate_interval_rejected(self):self.invalid(lambda r:r['events'][1].update(interval_id=r['events'][0]['interval_id']))
    def test_absent_roots_with_canopy_rejected(self):self.invalid(lambda r:r['physical_recipe']['cells']['upper']['stability_roots'].update(mode='ABSENT',basal_cohesion_pa=0,maximum_active_depth_m=0))
    def test_atmospheric_area_mismatch(self):self.invalid(lambda r:r['transect'][0].update(width_m=100))
    def test_duplicate_transect_cell(self):self.invalid(lambda r:r['transect'][1].update(cell_id='upper'))
    def test_hidden_template_rain_rejected(self):self.invalid(lambda r:r['physical_recipe']['events'][0]['cells']['upper'].update(liquid_input_m_s=1e-6))
    def test_template_event_limit_not_bypassed_with_hidden_history(self):self.invalid(lambda r:r['physical_recipe']['events'].append(deepcopy(r['physical_recipe']['events'][0])))
    def test_wrong_water_density(self):self.invalid(lambda r:r['demand_constants'].update(water_density_kg_m3=999))
    def test_wrong_atmospheric_epsilon(self):self.invalid(lambda r:r['events'][0]['atmosphere'].update(epsilon=.61))
    def test_unbound_surface_rejected(self):self.invalid(lambda r:r['events'][0]['surfaces'].pop('upper'))
    def test_unknown_boundary_rejected(self):self.invalid(lambda r:r['events'][0]['boundaries']['upper'].update(source_status='UNKNOWN'))
    def test_negative_duration(self):self.invalid(lambda r:r['events'][0].update(duration_seconds=-1))
    def test_month_13_rejected(self):self.invalid(lambda r:r['events'][0].update(month=13))
    def test_no_silent_calendar_change(self):self.invalid(lambda r:r.update(calendar='360'))
    def test_physical_year_and_model_calendar_must_agree(self):self.invalid(lambda r:r.update(model_day_seconds=43200))
    def test_unused_wet_bulb_controls_rejected(self):self.invalid(lambda r:r['phase'].update(temperature_basis='AIR_TEMPERATURE'))
    def test_coefficient_day_unit_sensitivity_is_separate_from_calendar(self):
        r=recipe();r['day_seconds']=43200
        result=p.run(r,stop_after=0,source_sha256=SOURCE)
        self.assertEqual(result['degree_day_units_status'],'EXPLICIT_COEFFICIENT_UNIT_SENSITIVITY_NOT_RETAINED_REPLAY')
        self.assertEqual(result['model_calendar_day_seconds'],86400)
    def test_explicit_air_temperature_alternative(self):
        r=recipe();r['phase']['temperature_basis']='AIR_TEMPERATURE';r['phase_controls']=None
        self.assertEqual(p.parse(r,SOURCE).phase.temperature_basis,'AIR_TEMPERATURE')
    def test_nonfinite_air(self):self.invalid(lambda r:r['events'][0]['atmosphere'].update(reference_temperature_c=float('nan')))
    def test_wrong_canopy_fraction(self):self.invalid(lambda r:r['events'][0]['vegetation']['upper'].update(reference_demand_fraction=1.1))
    def test_twelve_month_window_schedule_is_supported(self):
        model=p.parse(twelve_month_windows(),SOURCE)
        self.assertEqual(len(model.recipe['events']),12)
        self.assertEqual(len(model.physical.recipe['events']),1)
        self.assertEqual(sum(e['duration_seconds'] for e in model.recipe['events']),360)

    def test_all_twelve_representative_windows_actually_advance_without_snow_reset(self):
        r=twelve_month_windows()
        # Explicit zero-erodibility limit isolates the twelve-window scheduling
        # and storage contract; the separate connected reference has erosion.
        for law in r['physical_recipe']['erosion']: law['k_per_year']=0
        result=p.run(r,source_sha256=SOURCE)
        self.assertEqual(result['state']['completed_events'],12)
        for member in result['state']['members'].values():
            self.assertEqual(member['physical']['elapsed'],'360')
            self.assertEqual({row['month'] for row in member['joint_history']},set(range(1,13)))
            for a,b in zip(member['joint_history'],member['joint_history'][1:]):
                for key in member['snow']:
                    self.assertEqual(a['cells'][key]['snow_ledger']['final_swe_m'],b['cells'][key]['snow_ledger']['initial_swe_m'])

    def test_equal_precipitation_totals_different_event_timing_changes_water_response(self):
        base=recipe()
        for law in base['physical_recipe']['erosion']:law['k_per_year']=0
        for key in base['initial_swe_m']:base['initial_swe_m'][key]=0
        for row in base['physical_recipe']['cells'].values():row['surface_water_m3']='0'
        warm=deepcopy(base['events'][1]);warm['duration_seconds']=60
        warm['atmosphere'].update(reference_temperature_c=20,dry_air_flux_kg_s=30000000)
        for row in warm['vegetation'].values():row['reference_demand_fraction']=0
        for row in warm['boundaries'].values():row.update(kind='no_flow',head_m=None)
        base['events']=[deepcopy(warm),deepcopy(warm)]
        for i,event in enumerate(base['events']):event['interval_id']='event-'+str(i)
        burst=deepcopy(base);burst['events'][0]['atmosphere']['dry_air_flux_kg_s']*=2
        burst['events'][1]['atmosphere']['inlet_condensate_kg_per_kg_dry_air']=0
        states=[]
        for r in (base,burst):
            m=p.parse(r,SOURCE);scenario=m.scenarios[0];state=p.initial(m,scenario)
            for event in r['events']:state=p.advance_event(m,state,event,scenario)
            states.append(state)
        rain=[sum((F(row['precipitation_m3']) for row in s['joint_history']),F()) for s in states]
        self.assertEqual(rain[0],rain[1])
        runoff=[sum(s['physical']['surface'].values(),F())+sum((F(row['runoff_export_m3']) for row in s['physical']['history']),F()) for s in states]
        self.assertGreater(abs(float(runoff[0]-runoff[1])),1e-4)

    def checkpoint(self):
        r=recipe();a=p.run(r,stop_after=0,source_sha256=SOURCE)
        return r,st.checkpoint(a['state'],recipe_sha256=p.digest(r),source_sha256=SOURCE)

    def test_zero_cursor_forged_snow_even_with_new_checksum_rejected(self):
        r,cp=self.checkpoint();cp['state']['members']['LOW_DDF3_SIGMA2']['snow']['upper']['swe_m']='1'
        cp['state_sha256']=st.sha(st.encoded(cp['state']))
        with self.assertRaisesRegex(ValueError,'deterministic'):p.run(r,stop_after=0,resume=cp,source_sha256=SOURCE)

    def test_missing_coequal_member_rejected(self):
        r,cp=self.checkpoint();cp['state']['members'].pop('LOW_DDF3_SIGMA2');cp['state_sha256']=st.sha(st.encoded(cp['state']))
        with self.assertRaisesRegex(ValueError,'deterministic'):p.run(r,stop_after=0,resume=cp,source_sha256=SOURCE)

    def test_changed_source_rejects_replay(self):
        r,cp=self.checkpoint()
        with self.assertRaisesRegex(ValueError,'different recipe or actual source'):p.run(r,stop_after=0,resume=cp,source_sha256='a'*64)

    def test_changed_terrain_recipe_rejects_replay(self):
        r,cp=self.checkpoint()
        row=r['physical_recipe']['cells']['upper'];profile=p.r3.si.HydraulicProfile.from_dict(row['profile'])
        row['profile']=replace(profile,column=replace(profile.column,basal_elevation_m=profile.column.basal_elevation_m+1)).as_dict()
        with self.assertRaisesRegex(ValueError,'different recipe or actual source'):p.run(r,stop_after=0,resume=cp,source_sha256=SOURCE)

    def test_boolean_or_past_end_cursor_rejected(self):
        for value in (True,-1,3):
            with self.assertRaises(ValueError):p.run(recipe(),stop_after=value,source_sha256=SOURCE)

    def test_atmosphere_reversal_changes_transport_not_cell_identity(self):
        r=recipe();m=p.parse(r,SOURCE);s=p.initial(m,m.scenarios[0]);event=deepcopy(r['events'][0])
        forward=p.atmosphere(m,s['physical'],event);event['atmosphere']['wind_east_10m_m_s']=-5
        reverse=p.atmosphere(m,s['physical'],event)
        self.assertEqual(forward['receipt']['traversal'],list(reversed(reverse['receipt']['traversal'])))
        self.assertNotEqual(forward['cells']['upper']['precipitation_m_s'],reverse['cells']['upper']['precipitation_m_s'])

    def test_rejected_trial_never_mutates_parent(self):
        r=recipe();m=p.parse(r,SOURCE);s=p.initial(m,m.scenarios[0]);before=p.serialise({'x':s},0)
        with patch.object(p.r3,'trial',side_effect=p.r3.CoupledStepFailure('deliberate')):
            with self.assertRaises(p.r3.CoupledStepFailure):p.trial(m,s,r['events'][0],m.scenarios[0],F(30))
        self.assertEqual(p.serialise({'x':s},0),before)

    def test_zero_canopy_fraction_still_gates_reference_demand(self):
        r=recipe();m=p.parse(r,SOURCE);s=p.initial(m,m.scenarios[0]);fake={'physical':s['physical'],'snow':s['snow'],
            'joint_history':[{'cells':{k:{'snow_ledger':{'precipitation_m':'0','melt_m':'0'},'potential_reference_evaporation_m':'1',
                'potential_root_demand_m':'0','potential_condensation_m':'0','temperature_c':0,'specific_humidity_kg_kg':0}
                for k in s['snow']}}]}
        fine=deepcopy(fake)
        for cell in fine['joint_history'][0]['cells'].values():cell['potential_reference_evaporation_m']='2'
        with patch.object(p.r3,'compare',return_value=(0,{})):
            error,parts=p.compare(m,fake,fine,s)
        self.assertGreater(error,1);self.assertGreater(parts['upper/potential_reference_evaporation_m'],1)


if __name__=='__main__':unittest.main()
