"""Independent physical joins and bounded habitat-response tests."""
from copy import deepcopy
from fractions import Fraction as F
import unittest
from . import binding, upstream as u


class HabitatTests(unittest.TestCase):
    def setUp(self):
        self.cell={'domain':{'kind':'LAND','source_status':'WORKING NON-CANON'},
            'metrics':{'mineral_solum_m':u.metric(1,'m','test',[0,2])}}
        self.rule={'metric':'mineral_solum_m','unit':'m','points':[[0,0],[1,1],[2,0]],'outside':'HOLD','evidence':'test'}

    def test_interior_peak_not_just_endpoint_response(self):
        self.assertEqual(u.habitat(self.cell,[self.rule],'MINIMUM')['interval'],[0,1])

    def test_affine_interpolation(self):
        self.cell['metrics']['mineral_solum_m']=u.metric(0.25,'m','test')
        self.assertEqual(u.habitat(self.cell,[self.rule],'MINIMUM')['interval'],[0.25,0.25])

    def test_zero_exterior_with_known_endpoint_discontinuity(self):
        self.rule.update(points=[[0,1],[1,1]],outside='ZERO')
        self.assertEqual(u.habitat(self.cell,[self.rule],'MINIMUM')['interval'],[0,1])

    def test_unknown_input_is_not_favourable_or_zero(self):
        self.cell['metrics']['mineral_solum_m']=u.metric(None,'m','test')
        row=u.habitat(self.cell,[self.rule],'MINIMUM')
        self.assertEqual(row['status'],'UNKNOWN'); self.assertIsNone(row['support'])

    def test_unknown_domain_is_not_land(self):
        self.cell['domain']['kind']='UNKNOWN'
        self.assertEqual(u.habitat(self.cell,[self.rule],'MINIMUM')['status'],'UNKNOWN')

    def test_units_rejected_not_converted_silently(self):
        self.rule['unit']='cm'
        with self.assertRaises(ValueError): u.habitat(self.cell,[self.rule],'MINIMUM')

    def test_unknown_metric_cannot_smuggle_known_value(self):
        self.cell['metrics']['mineral_solum_m']['status']='UNKNOWN'
        with self.assertRaises(ValueError): u.habitat(self.cell,[self.rule],'MINIMUM')

    def test_modelled_metric_requires_value_and_interval(self):
        for key in ('value','interval'):
            cell=deepcopy(self.cell); cell['metrics']['mineral_solum_m'][key]=None
            with self.assertRaises(ValueError): u.habitat(cell,[self.rule],'MINIMUM')

    def test_no_food_or_actual_cover_proxy_injection(self):
        for name in ('food_mass','actual_cover','observed_occurrence'):
            cell=deepcopy(self.cell); cell['metrics'][name]=u.metric(1,'m','test')
            rule={**self.rule,'metric':name}
            with self.assertRaises(ValueError): u.habitat(cell,[rule],'MINIMUM')

    def test_geometric_combination(self):
        self.cell['metrics']['mineral_solum_m']=u.metric(0.25,'m','test')
        self.cell['metrics']['elevation_m']=u.metric(1,'m','test')
        second={**self.rule,'metric':'elevation_m'}
        self.assertEqual(u.habitat(self.cell,[self.rule,second],'GEOMETRIC')['interval'],[0.5,0.5])

    def test_duplicate_requirements_rejected(self):
        with self.assertRaises(ValueError): u.habitat(self.cell,[self.rule,self.rule],'MINIMUM')

    def test_invalid_knots_rejected(self):
        for points in ([[0,0],[0,1]],[[1,0],[0,1]],[[0,-1],[1,1]],[[0,0],[1,float('nan')]],[[False,0],[1,1]]):
            with self.assertRaises(ValueError): u.habitat(self.cell,[{**self.rule,'points':points}],'MINIMUM')

    def test_season_id_and_month_validation(self):
        good={'season_id':'winter','months':[12,1,2],'evidence':'explicit'}
        self.assertEqual(u.validate_seasons([good]),[good])
        for months in ([0],[13],[True],[1,1],[]):
            with self.assertRaises(ValueError): u.validate_seasons([{**good,'months':months}])
        with self.assertRaises(ValueError): u.validate_seasons([good,good])

    def test_json_hash_is_order_independent_and_rejects_nonstring_keys(self):
        self.assertEqual(u.digest({'a':1,'b':F(1,3)}),u.digest({'b':'1/3','a':1}))
        with self.assertRaises(ValueError): u.digest({1:'bad'})


class PhysicalProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle=binding.load(); cls.recipe=cls.bundle.reference.recipe(cls.bundle)
        cls.parent=cls.bundle.parent.run(cls.recipe['parent_recipe'])
        cls.env=u.project(cls.bundle,cls.parent,cls.recipe['seasons'])

    def test_nine_coequal_physical_scenarios(self):
        self.assertEqual(len(self.env['scenarios']),9)
        self.assertEqual({s['biome_family_id'] for s in self.env['scenarios'].values()},{'R8_A','R8_B','R8_C'})
        self.assertEqual(len({s['snow_id'] for s in self.env['scenarios'].values()}),3)

    def test_parent_and_cell_hash_and_area_joins(self):
        self.assertEqual(self.env['parent_result_sha256'],u.digest(self.parent))
        for scenario in self.env['scenarios'].values():
            for season in scenario['seasons'].values():
                for ident,cell in season['cells'].items():
                    original=self.parent['state']['members'][scenario['snow_id']][ident]
                    self.assertEqual(cell['parent_cell_sha256'],u.digest(original))
                    self.assertEqual(F(cell['area_m2']),F(2000000 if ident=='lower' else 1000000))
                    self.assertEqual(cell['soil_support_id'],original['soil_support_id'])

    def test_actual_selected_month_water_and_weighted_temperature(self):
        for scenario in self.env['scenarios'].values():
            raw=self.parent['seasonal']['members'][scenario['snow_id']]['cells']
            for sid,season in scenario['seasons'].items():
                for ident,cell in season['cells'].items():
                    rows=[r for r in raw[ident]['months'] if r['month_id'] in season['months']]
                    duration=sum((F(r['duration_seconds']) for r in rows),F())
                    temp=sum((F(r['temperature_c'])*F(r['duration_seconds']) for r in rows),F())/duration
                    precip=sum((F(r['precipitation_m_s'])*F(r['duration_seconds']) for r in rows),F())
                    liquid=sum((F(r['snow']['ledger']['liquid_to_soil_m']) for r in rows),F())
                    self.assertEqual(cell['metrics']['temperature_mean_c']['value'],float(temp))
                    self.assertEqual(cell['metrics']['precipitation_m']['value'],float(precip))
                    self.assertEqual(cell['metrics']['liquid_water_m']['value'],float(liquid))

    def test_actual_ph_and_solum_not_inferred_nutrient_adequacy(self):
        for scenario in self.env['scenarios'].values():
            for ident,cell in scenario['seasons']['warm']['cells'].items():
                soil=self.parent['soil_result']['state']['members'][scenario['snow_id']][ident]
                self.assertEqual(cell['metrics']['soil_ph_water']['value'],soil['fertility']['exchange']['chemistry']['ph_water'])
                self.assertEqual(cell['metrics']['mineral_solum_m']['value'],float(F(soil['horizons']['mineral_pedogenic_solum_depth_m'])))
                self.assertIn('nutrient sufficiency',cell['not_modelled'])

    def test_incomplete_or_wrong_parent_rejected(self):
        for key,value in (('source_sha256','0'*64),('schema','wrong')):
            bad={**self.parent,key:value}
            with self.assertRaises(ValueError): u.project(self.bundle,bad,self.recipe['seasons'])
        bad={**self.parent,'state':{**self.parent['state'],'completed_cells':0}}
        with self.assertRaises(ValueError): u.project(self.bundle,bad,self.recipe['seasons'])

    def test_no_actual_cover_food_mass_or_occurrence_metrics(self):
        for scenario in self.env['scenarios'].values():
            for cell in scenario['seasons']['warm']['cells'].values():
                self.assertFalse({'actual_cover','food_mass','observed_occurrence'} & set(cell['metrics']))


if __name__=='__main__': unittest.main()
