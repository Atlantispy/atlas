"""Focused numerical connections and source/context refusal, all synthetic."""
from copy import deepcopy
from fractions import Fraction as F
import unittest

from work.generator_upgrade_r22 import species as s
from work.generator_upgrade_r22 import _native_ecosystem as e
from work.generator_upgrade_r22 import _native_spatial as spatial
from work.generator_upgrade_r22 import _native_stock as stock
from work.generator_upgrade_r22 import _native_organic as organic
from work.generator_upgrade_r22 import _native_fertility as fertility

S, E = 'SYNTHETIC TEST', 'Isolated R22 interface test; no real biological coefficients'
REF = {'path': 'SYNTHETIC_ONLY_SOURCE', 'sha256': 'a'*64, 'locator': 'test-fixture', 'raw_source_status': S}
DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def context(support='support-a', unit='m2'):
    return dict(life_stage='ADULT', cohort_id='cohort-a', scope_id='test-scope', support_id=support,
        snapshot_id='test-snapshot', physical_scenario_id='test-physical', time_basis='EXPLICIT_PHASE',
        calendar_id='test-calendar', phase_id='one-year', within_period_aggregation='HELD_CONSTANT',
        joint_scenario_id='test-selection', natural_or_managed='NATURAL', counting_unit='test entities',
        native_measure_unit=unit, start_seconds='0', duration_seconds='365', time_units_seconds={'day': '1', 'year': '365'})


def row(field, value, unit, c=None, *, kind='PLANT'):
    c = c or context()
    return dict(record_id=c['support_id']+':'+field, organism_id='TEST_PLANT', kind=kind,
        field_id=field, value=value, unit=unit, source_status=S, model_use='SELECTED_FOR_R22',
        evidence=E, source_refs=[REF], use_decision_ref=REF, context=deepcopy(c))


def registry(rows):
    return s.Registry(dict(schema=s.SCHEMA, scope=S, source_bindings=[{'path': REF['path'], 'sha256': REF['sha256']}], records=rows))


def plant_rows():
    return [row('plant.net_light_use_efficiency', '1/1000', 'kg C/J'),
        row('plant.carbon_fraction_dry_matter', '2/5', '1'),
        row('plant.turnover_rate', '0', '1/year'), row('plant.litter_fast_fraction', '3/4', '1'),
        row('plant.temperature_response', {'law': 'PIECEWISE_LINEAR_NO_EXTRAPOLATION', 'knots': [[270,0],[290,1],[310,1],[330,0]]}, 'K,1'),
        *[row('plant.nutrient_ratio.'+n, v, 'kg '+n+'/kg C') for n,v in [('N','1/10'),('P','1/50'),('K','1/20')]],
        *[row('plant.uptake_rate.'+n, 10, '1/day') for n in ('N','P','K')]]


def native_inputs():
    tri = lambda n: tuple((k, F(n)) for k in ('N','P','K'))
    olaw = organic.OrganicLaw(fast_rate_per_s=.001, slow_rate_per_s=.0002, fast_to_slow_fraction=F(1,5),
        carbon_fraction_dry_matter=F(1,2), reference_temperature_k=300., fast_activation_energy_j_mol=0.,
        slow_activation_energy_j_mol=0., gas_constant_j_mol_k=8.314, minimum_temperature_k=250., maximum_temperature_k=340.,
        moisture_curve=((0.,0.),(1.,1.)), redox_factors=(('OXIC',1.,1.),('ANOXIC',.1,.2)), regimes=('AERATED_MINERAL',), evidence=E, source_status=S)
    chemistry = fertility.Chemistry('test-chemistry', 6.5, .1, 'EXPLICIT_TEST', E)
    nlaws = tuple(fertility.NutrientLaw(n, .0003, .01, 1., 300., 0., 8.314, chemistry.chemistry_id, 'NET_'+n, E) for n in ('N','P','K'))
    ncontext = e.NutrientContext(chemistry, nlaws, F(10), E, S)
    ostate = organic.OrganicState('layer-a','support-a', F(2), F(3), F(1000), E, S)
    initial = e.State(ostate, F(1), tri('1/10'), tri(1), tri('1/10'), F(100), E, S)
    calendar = e.Calendar('test-calendar', tuple(F(d) for d in DAYS), F(1), E)
    events = []
    for month, day in enumerate(DAYS,1):
        forcing = organic.OrganicForcing(F(day), F(), F(), 300., .5, 'OXIC', 'AERATED_MINERAL',
            'soil-temperature', 'water-'+str(month), E, E, E, S)
        exposure = fertility.WaterExposure(float(day),300.,.5,.2,0.,0.,0.,E)
        events.append(e.Event('m'+str(month),month,'layer-a','support-a',forcing,(exposure,)*3,
            F(day),F(300),F(1),F(1),F(),forcing.water_state_id,'thermal-state',E,E,S))
    return dict(initial_state=initial, organic_law=olaw, nutrient_context=ncontext, calendar=calendar,
        events=tuple(events), numerics=organic.Numerics(), geometry_sha256='b'*64, source_binding_sha256='c'*64, evidence=E)


class SpeciesTests(unittest.TestCase):
    def test_native_selected_growth_nutrients_and_unknown_suffix(self):
        reg = registry(plant_rows())
        out = s.run_plant_year(e,organic,fertility,reg,'TEST_PLANT',context(),**native_inputs())
        result = out['result']
        self.assertEqual(result['status'],'MODELLED_SEASONAL_ECOSYSTEM')
        self.assertEqual(result['completed_months'],12)
        self.assertEqual(result['events'][0]['organic_producer']['schema'],'diadem.organic-carbon-snapshot.r7')
        carbon = {k:F(v) for k,v in result['annual_budgets_kg_m2']['C'].items()}
        self.assertEqual(carbon['net_atmospheric_input'],F(365,1000))
        self.assertEqual(carbon['initial']+carbon['net_atmospheric_input']+carbon['external_litter_input'],
            carbon['final']+carbon['heterotrophic_export']+carbon['harvest_export'])
        for nutrient in ('N','P','K'):
            budget = {k:F(v) for k,v in result['annual_budgets_kg_m2'][nutrient].items()}
            self.assertEqual(budget['initial']+budget['external_input'],budget['final']+budget['water_export']+budget['harvest_export']+budget['numerical_residual'])
        absent = registry([r for r in plant_rows() if r['field_id'] != 'plant.uptake_rate.P'])
        stopped = s.run_plant_year(e,organic,fertility,absent,'TEST_PLANT',context(),**native_inputs())
        self.assertEqual(stopped['status'],'UNKNOWN')
        self.assertEqual(stopped['result']['completed_events'],0)
        self.assertIn('plant.uptake_rate.P',stopped['biology']['unresolved_fields'])

    def test_density_native_dimensions_and_source_basis(self):
        for unit in ('m','m2','m3'):
            c = context('a',unit)
            rows = [row('density.value',2,'test entities/'+unit,c),row('habitat.habitat_fraction','1/2','1',c),
                row('density.occupied_fraction','1/4','1',c),row('density.basis','PER_OCCUPIED_MEASURE','text',c)]
            cells = [dict(cell_id='a',eligible=True,measure={'value':100,'unit':unit},evidence=E,source_status=S)]
            out = s.run_density(stock,registry(rows),'TEST_PLANT',context(unit=unit),cells=cells,basis='PER_OCCUPIED_MEASURE')
            self.assertEqual(out['result']['total_expected_entities']['exact'],'25')
            with self.assertRaisesRegex(ValueError,'basis differs'):
                s.run_density(stock,registry(rows),'TEST_PLANT',context(unit=unit),cells=cells,basis='PER_WHOLE_CELL_MEASURE')

    def test_stock_remains_unplaced_under_missing_weights(self):
        rows = [row('stock.total_expected_entities',10,'test entities'),
            row('stock.allocation_weight',1,'1 relative weight',context('a')),
            row('stock.capacity_expected_entities',4,'test entities',context('a'))]
        cells = [dict(cell_id=k,eligible=True,occupied_measure=None,evidence=E,source_status=S) for k in ('a','b')]
        out = s.run_stock(stock,registry(rows),'TEST_PLANT',context(),cells=cells)['result']
        self.assertEqual(out['status'],'UNKNOWN')
        self.assertEqual(out['placed_expected_entities']['exact'],'0')
        self.assertEqual(out['unplaced_expected_entities']['exact'],'10')
        self.assertEqual(out['conservation_residual_expected_entities']['exact'],'0')

    def test_actual_range_kernel_receives_selected_coefficients(self):
        rows = [row(f,v,u) for f,v,u in [
            ('habitat.suitability_minimum','1/2','1'),('occupancy.logit_intercept',0,'1'),
            ('occupancy.logit_slope',0,'1 per unit habitat_support'),('occupancy.conditional_occupied_fraction','1/2','1'),
            ('density.value',2,'test entities/m2'),('density.basis','PER_OCCUPIED_MEASURE','text'),
            ('movement.mode','NONMOVING','text'),('movement.budget',0,'m')]]
        cells = (spatial.Cell('a',F(100),1.,F(1),True,E,S),)
        origins = (spatial.Origin('a',E,S),)
        out = s.run_range(spatial,registry(rows),'TEST_PLANT',context(),cells=cells,edges=(),origins=origins,travel_unit='m')
        self.assertEqual(out['result']['cells']['a']['expected_individuals']['exact'],'50')

    def test_source_day_recruitment_and_residence_separate(self):
        c = context(); c['duration_seconds']='20'; c['time_units_seconds']={'day':'10'}
        rows = [row('recruitment.law','PRESCRIBED_SUCCESSFUL_RECRUITMENT_FLUX','text',c),
            row('recruitment.rate',3,'test entities/day',c),row('residence.scoped_cohort_entities',8,'test entities',c),
            row('residence.fraction','1/4','1',c)]
        reg = registry(rows)
        self.assertEqual(s.recruitment_flux(reg,'TEST_PLANT',c)['successful_recruits'],'6')
        self.assertEqual(s.residence_exposure(reg,'TEST_PLANT',c)['entity_seconds'],'40')
        c['time_units_seconds']={}
        for r in rows: r['context']=deepcopy(c)
        with self.assertRaisesRegex(ValueError,'time unit'):
            s.recruitment_flux(registry(rows),'TEST_PLANT',c)

    def test_source_selection_and_context_refusals(self):
        rows=plant_rows()
        changed=deepcopy(rows); changed[0]['source_refs'][0]['sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'unbound'): registry(changed)
        with self.assertRaisesRegex(ValueError,'duplicate'): registry(rows+[rows[0]])
        changed=deepcopy(rows); changed[0]['value']=True
        with self.assertRaisesRegex(ValueError,'not bool'): s.compile_plant_law(e,registry(changed),'TEST_PLANT',context())
        changed=deepcopy(rows); changed[0]['use_decision_ref']=None
        with self.assertRaisesRegex(ValueError,'selection decision'): registry(changed)
        c=context(); c['cohort_id']='different-cohort'
        absent=s.compile_plant_law(e,registry(rows),'TEST_PLANT',c)
        self.assertEqual(absent['status'],'UNKNOWN')
        self.assertEqual(len(absent['receipt']['unresolved_fields']),11)

    def test_owner_biology_binds_to_replaceable_application(self):
        document = registry(plant_rows()).document
        for r in document['records']:
            r['context'] = {'life_stage':'ADULT', 'natural_or_managed':'NATURAL'}
        bound = s.bind_application(document,'TEST_PLANT',context(),application_ref=REF)
        compiled = s.compile_plant_law(e,bound,'TEST_PLANT',context())
        self.assertEqual(compiled['status'],'SELECTED_NUMERICAL_LAW')
        self.assertEqual(bound.records[0]['owner_context'],{'life_stage':'ADULT','natural_or_managed':'NATURAL'})
        alternative = context(); alternative['physical_scenario_id']='replacement-terrain'
        changed = s.bind_application(document,'TEST_PLANT',alternative,application_ref=REF)
        self.assertNotEqual(bound.register_sha256,changed.register_sha256)
        self.assertEqual(bound.records[0]['value'],changed.records[0]['value'])


if __name__ == '__main__': unittest.main()
