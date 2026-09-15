"""Independent actual R4 climate/SWE/R3 temporal and changing-terrain checks.

Before running this experiment: first-order evidence requires successive
difference ratios in [1.4,3.0], above the declared per-quantity floors. The
initial strict-inner attempt fails numerically and is retained as a regression.
The separate actual-default-inner experiment reports which fields meet that
criterion, rather than relabelling unresolved or faster convergence as first
order. Inner controls and all scientific data are identical across its caps.
One explicit coequal member is used to bound test cost, not as a preferred model.
"""
from copy import deepcopy
from fractions import Fraction as F
import math
import unittest
from unittest.mock import patch

from . import pipeline as p, reference, climate
from work.generator_upgrade_r3.test_coupled_refinement import physical_head_distance

CAPS=(120,60,30)
RATIO_BAND=(1.4,3.0)
FLOORS={'sediment_export_kg':1e-6,'terrain_change_m':1e-10,'water_export_m3':1e-8,
        'swe_m':1e-18,'precipitation_m3':1e-10,'temperature_c':1e-12,'head_integral_m2':1e-9}
SOURCE='0'*64


def experiment(cap):
    recipe=reference.recipe()
    recipe['physical_recipe']['coupling_controls'].update(initial_dt_seconds=cap,max_dt_seconds=cap,min_dt_seconds=1)
    return recipe


def strict_inner_experiment(cap):
    recipe=experiment(cap)
    recipe['physical_recipe']['water_controls'].update(theta_atol=1e-8,head_atol_m=1e-8,
        flux_integral_atol_m=1e-10,relative_tolerance=1e-6,
        nonlinear_mass_atol_m=1e-12,total_mass_atol_m=1e-10)
    return recipe


def execute(recipe):
    model=p.parse(recipe,SOURCE);scenario=model.scenarios[0];state=p.initial(model,scenario)
    for event in recipe['events']:state=p.advance_event(model,state,event,scenario)
    final=p.atmosphere(model,state['physical'],recipe['events'][-1])
    return model,state,final


def measures(model,state,final):
    history=state['physical']['history']
    return {
        'sediment_export_kg':float(sum((F(r['exported_mass_kg']) for h in history for r in h['terrain']['material_balances']),F())),
        'terrain_change_m':float(sum((abs(profile.column.surface_m-model.physical.profiles[k].column.surface_m)
                                    for k,profile in state['physical']['profiles'].items()),F())),
        'water_export_m3':float(sum((F(h[k]) for h in history for k in ('bottom_out_m3','runoff_export_m3','sediment_porewater_export_m3')),F())),
        'swe_m':float(sum((snow.swe_m for snow in state['snow'].values()),F())),
        'precipitation_m3':float(sum((F(h['precipitation_m3']) for h in state['joint_history']),F())),
        'temperature_c':sum(row['temperature_c'] for row in final['cells'].values())}


def run_refinement():
    recipes=[experiment(cap) for cap in CAPS]
    runs=[execute(recipe) for recipe in recipes]
    values=[measures(*run) for run in runs]
    differences={k:[abs(values[i][k]-values[i+1][k]) for i in (0,1)] for k in values[0]}
    # The retained independent helper compares actual absolute-elevation
    # intervals, never material indices or each column's own shifted depth.
    heads=[physical_head_distance({'state':p.r3.serialise(runs[i][1]['physical'])},
                                  {'state':p.r3.serialise(runs[i+1][1]['physical'])}) for i in (0,1)]
    differences['head_integral_m2']=[h[0] for h in heads]
    return recipes,runs,{'caps_seconds':CAPS,'measures':values,'differences':differences,
        'ratios':{k:(a/b if b else None) for k,(a,b) in differences.items()},
        'observed_orders':{k:(math.log2(a/b) if a>0 and b>0 else None) for k,(a,b) in differences.items()},
        'head_nonoverlap_m':[h[1] for h in heads],'predeclared_ratio_band':RATIO_BAND,'predeclared_floors':FLOORS,
        'first_order_criterion_met':{k:(min(a,b)>FLOORS[k] and RATIO_BAND[0]<=a/b<=RATIO_BAND[1]) for k,(a,b) in differences.items()},
        'inner_controls':'UNMODIFIED_REFERENCE_DEFAULTS; initial stricter-inner attempt fails and is separately tested',
        'interpretation':'No full-chain first-order claim: zero/unresolved fields and faster solid convergence are reported, not retuned'}


class CoupledClimateRefinementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.recipes,cls.runs,cls.report=run_refinement()

    def order(self,key):
        a,b=self.report['differences'][key]
        self.assertGreater(min(a,b),FLOORS[key],('unresolved difference is not evidence of order',self.report))
        self.assertGreaterEqual(a/b,RATIO_BAND[0],self.report)
        self.assertLessEqual(a/b,RATIO_BAND[1],self.report)

    def test_solid_export_difference_decreases_without_relabelling_as_first_order(self):
        a,b=self.report['differences']['sediment_export_kg']
        self.assertGreater(a,b);self.assertGreater(b,FLOORS['sediment_export_kg'])
        self.assertFalse(self.report['first_order_criterion_met']['sediment_export_kg'])
    def test_changed_terrain_is_below_predeclared_order_resolution(self):
        a,b=self.report['differences']['terrain_change_m']
        self.assertLess(b,a);self.assertLess(a,FLOORS['terrain_change_m'])
        self.assertFalse(self.report['first_order_criterion_met']['terrain_change_m'])
    def test_water_export_first_order(self):self.order('water_export_m3')
    def test_tiny_swe_difference_meets_numeric_band_not_physical_accuracy_claim(self):self.order('swe_m')
    def test_total_precipitation_does_not_falsely_prove_order(self):
        self.assertEqual(self.report['differences']['precipitation_m3'],[0,0])
        self.assertFalse(self.report['first_order_criterion_met']['precipitation_m3'])
    def test_temperature_does_not_falsely_prove_order_at_roundoff(self):
        self.assertLess(max(self.report['differences']['temperature_c']),FLOORS['temperature_c'])
        self.assertFalse(self.report['first_order_criterion_met']['temperature_c'])
    def test_head_on_actual_physical_support_first_order(self):self.order('head_integral_m2')

    def test_no_scientific_or_inner_accuracy_retuning_between_caps(self):
        templates=deepcopy(self.recipes)
        for r in templates:
            for k in ('initial_dt_seconds','max_dt_seconds'):r['physical_recipe']['coupling_controls'].pop(k)
        self.assertEqual(templates[0],templates[1]);self.assertEqual(templates[1],templates[2])

    def test_actual_accepted_steps_not_only_reported_maximum(self):
        for cap,(model,state,_) in zip(CAPS,self.runs):
            history=state['joint_history']
            self.assertEqual({F(row['duration_seconds']) for row in history},{F(cap,2)})
            self.assertEqual(sum((F(row['duration_seconds']) for row in history),F()),240)
            self.assertEqual(state['physical']['completed_events'],2)

    def test_actual_atmosphere_support_tracks_every_accepted_changed_terrain(self):
        for model,state,final in self.runs:
            physical=state['physical']['history'];joint=state['joint_history']
            self.assertEqual(len(physical),len(joint))
            for h,air in zip(physical,joint):
                receipt=air['atmospheric_moisture_ledger']
                for row in receipt['cells']:
                    self.assertEqual(row['elevation_m'],float(F(h['terrain']['initial_surfaces_m'][row['cell_id']])) )
                    self.assertEqual(F(row['area_m2']),model.physical.profiles[row['cell_id']].column.area_m2)
                self.assertEqual(F(receipt['water_mass_residual_kg_s']),0)
            self.assertNotEqual(joint[0]['antecedent_terrain_sha256'],joint[-1]['antecedent_terrain_sha256'])
            for row in final['receipt']['cells']:
                self.assertEqual(row['elevation_m'],float(state['physical']['profiles'][row['cell_id']].column.surface_m))

    def test_snow_and_soil_are_not_independent_replays(self):
        for model,state,_ in self.runs:
            for key in state['snow']:
                rows=[h['cells'][key]['snow_ledger'] for h in state['joint_history']]
                for a,b in zip(rows,rows[1:]):self.assertEqual(a['final_swe_m'],b['initial_swe_m'])
                self.assertEqual(F(rows[-1]['final_swe_m']),state['snow'][key].swe_m)
                self.assertGreater(sum((F(r['melt_m']) for r in rows),F()),0)
            for h in state['physical']['history']:
                for balance in h['terrain']['material_balances']:self.assertEqual(F(balance['mass_residual_kg']),0)
            self.assertGreater(sum((F(h['actual_et_m3']) for h in state['physical']['history']),F()),0)
            self.assertLess(abs(float(sum((F(h['joint_residual_m3']) for h in state['joint_history']),F()))),len(state['joint_history'])*model.recipe['coupling_controls']['joint_budget_atol_m3'])


class IndependentCallTests(unittest.TestCase):
    def test_changed_real_terrain_changes_condensation_in_declared_moist_regime(self):
        # Separate physical regime, declared before this test: supersaturated
        # cold inflow. AIR_TEMPERATURE phase avoids using an unsaturated-only
        # psychrometric approximation outside its domain. Main recipe unchanged.
        recipe=experiment(120);recipe['events'][0]['atmosphere']['inlet_specific_humidity']=.003
        recipe['phase']['temperature_basis']='AIR_TEMPERATURE';recipe['phase_controls']=None
        recipe['evidence']+='; separate cold near-saturated inflow sensitivity, not temporal-order tuning'
        model=p.parse(recipe,SOURCE);scenario=model.scenarios[0];before=p.initial(model,scenario)
        first=p.atmosphere(model,before['physical'],recipe['events'][0])
        after=p.trial(model,before,recipe['events'][0],scenario,F(30))
        second=p.atmosphere(model,after['physical'],recipe['events'][0])
        self.assertEqual(first['receipt']['inlet_water_kg_s'],second['receipt']['inlet_water_kg_s'])
        regimes={r['regime'] for row in first['receipt']['cells'] for r in row['microphysics']}
        self.assertIn('CONDENSATION_AND_DELAYED_FALLOUT',regimes)
        self.assertLess(after['physical']['profiles']['upper'].column.surface_m,before['physical']['profiles']['upper'].column.surface_m)
        self.assertGreater(second['cells']['upper']['temperature_c'],first['cells']['upper']['temperature_c'])
        self.assertLess(second['cells']['upper']['precipitation_m_s'],first['cells']['upper']['precipitation_m_s'])
        self.assertNotEqual(second['cells']['upper']['specific_humidity_kg_kg'],first['cells']['upper']['specific_humidity_kg_kg'])
        self.assertEqual(F(first['receipt']['water_mass_residual_kg_s']),0)
        self.assertEqual(F(second['receipt']['water_mass_residual_kg_s']),0)

    def test_stricter_inner_solver_failure_is_preserved_not_converted_to_pass(self):
        recipe=strict_inner_experiment(120);model=p.parse(recipe,SOURCE);scenario=model.scenarios[0]
        before=p.initial(model,scenario);saved=p.serialise({'selected':before},0)
        with self.assertRaisesRegex(p.r3.CoupledStepFailure,'NUMERICAL_FAILURE.*minimum time step'):
            p.trial(model,before,recipe['events'][0],scenario,F(30))
        self.assertEqual(p.serialise({'selected':before},0),saved)

    def test_real_generate_is_called_again_after_real_terrain_changes(self):
        recipe=experiment(120);model=p.parse(recipe,SOURCE);scenario=model.scenarios[0]
        before=p.initial(model,scenario);calls=[];actual=climate.generate
        def traced(cells,air,controls):
            out=actual(cells,air,controls);calls.append((cells,air,out));return out
        with patch.object(climate,'generate',side_effect=traced):
            after=p.trial(model,before,recipe['events'][0],scenario,F(30))
            p.trial(model,after,recipe['events'][0],scenario,F(30))
        self.assertEqual(len(calls),2)
        for index,state in enumerate((before,after)):
            cells,air,out=calls[index]
            for cell in cells:
                self.assertEqual(cell.elevation_m,float(state['physical']['profiles'][cell.cell_id].column.surface_m))
                self.assertAlmostEqual(out['cells'][cell.cell_id]['temperature_c'],air.reference_temperature_c-air.lapse_k_m*(cell.elevation_m-air.reference_elevation_m),places=12)
        self.assertNotEqual([c.elevation_m for c in calls[0][0]],[c.elevation_m for c in calls[1][0]])
        self.assertNotEqual(calls[0][2]['cells']['upper']['temperature_c'],calls[1][2]['cells']['upper']['temperature_c'])


if __name__=='__main__':unittest.main()
