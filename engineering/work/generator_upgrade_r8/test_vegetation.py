from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction as F
import json
import math
import unittest

from scipy.integrate import solve_ivp

from . import vegetation as v

E='SYNTHETIC TEST: explicit uncalibrated PFT and seasonal water hypothesis'
S='SYNTHETIC TEST'
DAYS=(31,28,31,30,31,30,31,31,30,31,30,31)


def calendar(day=1):return v.Calendar('synthetic-calendar',tuple(F(d*day) for d in DAYS),F(day),E)
def capacity(c=1):return v.WaterCapacity(c,2.,'actual-physical-profile',E,S)
def events(i=.005,d=.01,temps=None,active=None,day=1):
    return tuple(v.Event('month-'+str(m),m,F(dt*day),10. if temps is None else temps[m-1],
        i if type(i) in (int,float) else i[m-1],d if type(d) in (int,float) else d[m-1],
        True if active is None else active[m-1],E,S) for m,dt in enumerate(DAYS,1))
def constraints(limits=None,**kw):
    c=v.PFTConstraints('hypothetical-woody-PFT',5.,.4,
        (v.Limit('active_actual_to_potential_transpiration_ratio',.3,None,E,S),) if limits is None else limits,
        (),E,S)
    return replace(c,**kw)
def evaluate(ev=None,c=None,pft=None,gate=None):
    return v.evaluate(c or capacity(),calendar(),ev or events(),pft or constraints(),gate or {})


class ReservoirTests(unittest.TestCase):
    def test_decay_independent_decimal(self):
        r=v.advance_reservoir(1.,.8,F(30),0.,.01)
        with localcontext() as ctx:
            ctx.prec=60
            expected=Decimal.from_float(.8)*(-Decimal.from_float(.01)*30).exp()
        self.assertAlmostEqual(r['final_m'],float(expected),places=15)
        self.assertAlmostEqual(r['actual_transpiration_m'],.8-float(expected),places=15)

    def test_uniform_input_analytical(self):
        r=v.advance_reservoir(1.,.2,25,.004,.01)
        expected=.4+(.2-.4)*math.exp(-.25)
        self.assertAlmostEqual(r['final_m'],expected,places=15)
        self.assertAlmostEqual(r['actual_transpiration_m'],.1+.2-expected,places=15)

    def test_capacity_hit_and_independent_fluxes(self):
        r=v.advance_reservoir(1.,0.,100,.04,.01)
        hit=math.log(4/3)/.01
        self.assertAlmostEqual(r['capacity_hit_seconds'],hit,places=12)
        self.assertAlmostEqual(r['overflow_m'],.03*(100-hit),places=14)
        self.assertAlmostEqual(r['actual_transpiration_m'],.04*hit-1+.01*(100-hit),places=14)
        self.assertEqual(r['final_m'],1.)

    def test_no_demand_fill_then_overflow(self):
        r=v.advance_reservoir(.7,.2,100,.01,0.)
        self.assertEqual(r['final_m'],.7)
        self.assertAlmostEqual(r['capacity_hit_seconds'],50)
        self.assertAlmostEqual(r['overflow_m'],.5)
        self.assertEqual(r['actual_transpiration_m'],0)

    def test_capacity_equilibrium(self):
        for duration in (1.,13.,1e5):
            r=v.advance_reservoir(.3,.3,duration,.002,.002)
            self.assertEqual(r['final_m'],.3)
            self.assertAlmostEqual(r['actual_transpiration_m'],duration*.002)

    def test_zero_forcing_identity(self):
        r=v.advance_reservoir(1.,.7,31,0.,0.)
        self.assertEqual(r['final_m'],.7)
        self.assertEqual(r['numerical_residual_m'],'0')

    def test_instant_cap_surplus(self):
        r=v.advance_reservoir(1.,1.,10,.03,.01)
        self.assertEqual(r['capacity_hit_seconds'],0)
        self.assertAlmostEqual(r['overflow_m'],.2)
        self.assertAlmostEqual(r['actual_transpiration_m'],.1)

    def test_tiny_dose_continuous_litter_analogue(self):
        r=v.advance_reservoir(1.,0.,1e-5,1e-5,1e-5)
        expected=.5*1e-5*1e-5*1e-10
        self.assertAlmostEqual(r['actual_transpiration_m']/expected,1,places=9)

    def test_dop853_independent_unsaturated_oracle(self):
        for initial,i,d,duration in ((.2,.001,.01,30),(.9,.02,.04,80),(.01,.005,.01,7)):
            r=v.advance_reservoir(1.,initial,duration,i,d)
            oracle=solve_ivp(lambda t,y:[i-d*y[0],d*y[0]],[0,duration],[initial,0],rtol=1e-12,atol=1e-14,method='DOP853')
            self.assertTrue(oracle.success)
            self.assertAlmostEqual(r['final_m'],oracle.y[0,-1],places=12)
            self.assertAlmostEqual(r['actual_transpiration_m'],oracle.y[1,-1],places=12)

    def test_refinement_composes_across_cap(self):
        full=v.advance_reservoir(1.,.2,100,.03,.01)
        a=v.advance_reservoir(1.,.2,40,.03,.01)
        b=v.advance_reservoir(1.,a['final_m'],60,.03,.01)
        self.assertAlmostEqual(full['final_m'],b['final_m'],places=14)
        for key in ('actual_transpiration_m','overflow_m'):
            self.assertAlmostEqual(full[key],a[key]+b[key],places=14)

    def test_balance_is_independent_not_definition(self):
        r=v.advance_reservoir(.7,.4,31,.001,.01)
        residual=F(.4)+F(.001)*31-F(r['final_m'])-F(r['actual_transpiration_m'])-F(r['overflow_m'])
        self.assertEqual(F(r['numerical_residual_m']),residual)
        self.assertLess(abs(float(residual)),1e-15)

    def test_invalid_and_underflow_rejected(self):
        for args in ((0.,0.,1,0.,0.),(1.,2.,1,0.,0.),(True,0.,1,0.,0.),(1.,0.,0,0.,0.),(1.,0.,1,float('nan'),0.)):
            with self.assertRaises(ValueError):v.advance_reservoir(*args)
        with self.assertRaises(ArithmeticError):v.advance_reservoir(1.,0.,1e-200,1e-200,0.)


class SeasonalTests(unittest.TestCase):
    def test_constant_forcing_independent_fixed_point(self):
        r=v.periodic_water(capacity(),calendar(),events(),dry_stress_fraction=.4)
        self.assertEqual(r['status'],'MODELLED_PERIODIC_BRACKET')
        self.assertLessEqual(r['lower']['initial_m'],.5)
        self.assertGreaterEqual(r['upper']['initial_m'],.5)
        self.assertAlmostEqual(r['lower']['active_actual_to_potential_transpiration_ratio'],.5,places=8)

    def test_uniform_split_events_equivalent(self):
        ev=events();split=tuple(part for e in ev for part in (replace(e,event_id=e.event_id+'a',duration_seconds=e.duration_seconds/2),replace(e,event_id=e.event_id+'b',duration_seconds=e.duration_seconds/2)))
        a=evaluate(ev);b=evaluate(split)
        for key in v.METRICS:self.assertEqual(a['metrics'][key],b['metrics'][key]) if key not in ('active_actual_to_potential_transpiration_ratio',) else self.assertAlmostEqual(a['metrics'][key],b['metrics'][key],places=12)

    def test_seasonality_same_annual_rain_changes_active_stress(self):
        active=[False]*6+[True]*6
        # Same two liquid totals but their ordering differs relative to demand.
        durations=[F(d) for d in DAYS];total=F(1)
        early=[float(total/sum(durations[:6]))]*6+[0.]*6
        late=[0.]*6+[float(total/sum(durations[6:]))]*6
        d=[0.]*6+[.01]*6
        a=evaluate(events(early,d,active=active));b=evaluate(events(late,d,active=active))
        self.assertGreater(b['metrics']['active_actual_to_potential_transpiration_ratio'],a['metrics']['active_actual_to_potential_transpiration_ratio'])

    def test_independent_dry_exponential_crossing(self):
        row=v.advance_reservoir(1.,1.,100,0.,.01)
        interval=v._dry_interval(row,.5)
        self.assertAlmostEqual(interval[0],math.log(2)/.01,places=12)
        self.assertEqual(interval[1],100)

    def test_independent_dry_linear_fill_crossing(self):
        row=v.advance_reservoir(1.,0.,100,.01,0.)
        self.assertEqual(v._dry_interval(row,.3),(0.,30.))

    def test_circular_dry_duration_not_double_year(self):
        r=evaluate(events(i=.002))
        self.assertEqual(r['metrics']['dry_active_duration_s'],365.)
        self.assertEqual(r['metrics']['longest_dry_active_spell_s'],365.)

    def test_inactive_intervals_break_dry_spells(self):
        active=[True]*12;active[5]=False
        r=evaluate(events(i=.002,active=active))
        self.assertEqual(r['metrics']['dry_active_duration_s'],335.)
        self.assertEqual(r['metrics']['longest_dry_active_spell_s'],335.)

    def test_nonunique_zero_input_and_zero_demand_unknown(self):
        n=v.Numerics(max_cycles=3)
        r=v.periodic_water(capacity(),calendar(),events(0.,0.),dry_stress_fraction=.5,numerics=n)
        self.assertEqual(r['status'],'UNKNOWN')
        self.assertIsNone(r['lower']['active_actual_to_potential_transpiration_ratio'])

    def test_no_active_demand_ratio_is_unknown_not_one(self):
        r=evaluate(events(active=[False]*12))
        self.assertIsNone(r['metrics']['active_actual_to_potential_transpiration_ratio'])
        self.assertEqual(r['status'],'UNKNOWN')

    def test_periodic_work_limit_is_unknown(self):
        r=v.periodic_water(capacity(),calendar(),events(),dry_stress_fraction=.4,numerics=v.Numerics(max_cycles=1))
        self.assertEqual(r['status'],'UNKNOWN')

    def test_complete_cycle_independent_water_ledger(self):
        w=evaluate()['water']['lower']
        exact_input=sum((F(r['liquid_input_m_s'])*F(r['duration_seconds']) for r in w['events']),F())
        actual=sum((F(r['actual_transpiration_m']) for r in w['events']),F())
        overflow=sum((F(r['overflow_m']) for r in w['events']),F())
        self.assertEqual(F(w['initial_m'])+exact_input-F(w['final_m'])-actual-overflow,F(w['numerical_residual_m']))

    def test_fractional_event_seconds_record_conversion(self):
        r=v.advance_reservoir(1.,.5,F(1,3),.001,.002)
        self.assertEqual(r['supplied_duration_seconds'],'1/3')
        self.assertEqual(F(r['duration_conversion_residual_s']),F(float(F(1,3)))-F(1,3))

    def test_soil_capacity_changes_seasonal_exposure(self):
        ev=events([.02]*6+[0.]*6)
        a=evaluate(ev,c=capacity(.1));b=evaluate(ev,c=capacity(1.))
        self.assertGreater(b['metrics']['active_actual_to_potential_transpiration_ratio'],a['metrics']['active_actual_to_potential_transpiration_ratio'])


class ConstraintTests(unittest.TestCase):
    def test_thermal_metrics_exact_supplied_calendar(self):
        temps=list(range(12));r=evaluate(events(temps=temps))
        self.assertEqual(r['metrics']['coldest_month_temperature_c'],0)
        self.assertEqual(r['metrics']['warmest_month_temperature_c'],11)
        self.assertEqual(r['metrics']['growing_degree_days'],sum(max(t-5,0)*d for t,d in zip(temps,DAYS)))

    def test_non_earth_day_is_explicit(self):
        c=calendar(90000);ev=events(i=.005/90000,d=.01/90000,day=90000)
        r=v.evaluate(capacity(),c,ev,constraints(),{})
        self.assertEqual(r['metrics']['growing_degree_days'],1825)
        self.assertAlmostEqual(r['metrics']['active_actual_to_potential_transpiration_ratio'],.5,places=8)

    def test_known_fail_overrides_missing_other_constraint(self):
        p=constraints((v.Limit('coldest_month_temperature_c',20,None,E,S),v.Limit('active_actual_to_potential_transpiration_ratio',.3,None,E,S)))
        ev=list(events());ev[3]=replace(ev[3],liquid_input_m_s=None)
        r=evaluate(tuple(ev),pft=p)
        self.assertEqual(r['status'],'FAIL');self.assertEqual([x['status'] for x in r['constraints']],['FAIL','UNKNOWN'])

    def test_missing_thermal_not_zero(self):
        ev=list(events());ev[0]=replace(ev[0],temperature_c=None)
        r=evaluate(tuple(ev),pft=constraints((v.Limit('coldest_month_temperature_c',None,0,E,S),)))
        self.assertIsNone(r['metrics']['coldest_month_temperature_c']);self.assertEqual(r['status'],'UNKNOWN')

    def test_missing_external_gate_is_unknown(self):
        r=evaluate(pft=constraints(external_requirements=('independent_hydroperiod',)))
        self.assertEqual(r['status'],'UNKNOWN')
        self.assertEqual(r['external_gates']['independent_hydroperiod']['status'],'UNKNOWN')

    def test_supplied_external_fail_is_not_truthy_pass(self):
        r=evaluate(pft=constraints(external_requirements=('salt_tolerance',)),gate={'salt_tolerance':{'status':'FAIL','evidence':E}})
        self.assertEqual(r['status'],'FAIL')
        with self.assertRaises(ValueError):evaluate(pft=constraints(external_requirements=('salt_tolerance',)),gate={'salt_tolerance':{'status':'FALSE','evidence':E}})

    def test_unknown_trait_limits_do_not_pass(self):
        p=constraints(source_status='UNKNOWN')
        self.assertEqual(evaluate(pft=p)['status'],'UNKNOWN')

    def test_boundary_bracket_straddling_is_unknown(self):
        r=evaluate(pft=constraints((v.Limit('active_actual_to_potential_transpiration_ratio',.5,None,E,S),)))
        self.assertEqual(r['status'],'UNKNOWN')

    def test_json_serialisable_and_semantics(self):
        r=evaluate();json.dumps(r,allow_nan=False)
        self.assertEqual(r['schema'],'diadem.pft-seasonal-admissibility.r8')
        self.assertEqual(r['metric_units']['active_actual_to_potential_transpiration_ratio'],'1')
        self.assertIn('not NPP',r['scope'])

    def test_exact_month_coverage_and_order(self):
        ev=events()
        for bad in (ev[:-1],tuple(reversed(ev)),(replace(ev[0],duration_seconds=30),)+ev[1:]):
            with self.assertRaises(ValueError):evaluate(bad)

    def test_half_defined_unknown_inputs(self):
        for key in ('liquid_input_m_s','potential_transpiration_m_s','active'):
            ev=list(events());ev[0]=replace(ev[0],**{key:None})
            self.assertEqual(evaluate(tuple(ev))['status'],'UNKNOWN')
        self.assertEqual(evaluate(c=replace(capacity(),capacity_m=None))['status'],'UNKNOWN')

    def test_invalid_boolean_nonfinite_and_schema(self):
        for key,value in (('temperature_c',True),('active',1),('liquid_input_m_s',float('inf')),('month_id',True)):
            with self.assertRaises(ValueError):replace(events()[0],**{key:value})
        with self.assertRaises(ValueError):replace(calendar(),day_seconds=True)
        with self.assertRaises(ValueError):replace(calendar(),month_durations_seconds=tuple(F(30) for _ in range(12)))
        with self.assertRaises(ValueError):v.Limit('not_a_metric',0.,1.,E,S)
        with self.assertRaises(ValueError):replace(events()[0],source_status=[])
        with self.assertRaises(ValueError):v.Limit([],0.,1.,E,S)

    def test_zero_capacity_not_desert(self):
        r=evaluate(c=capacity(0.))
        self.assertEqual(r['status'],'UNKNOWN');self.assertEqual(r['water']['status'],'OUTSIDE_REGIME')


if __name__=='__main__':unittest.main()
