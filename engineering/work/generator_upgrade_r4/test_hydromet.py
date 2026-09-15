"""Independent numerical/physical limits and actual retained-source comparisons."""
from dataclasses import replace
from decimal import Decimal as D, localcontext
from fractions import Fraction as F
import math
import unittest
from unittest.mock import patch
import numpy as np
from scipy.integrate import quad
from . import hydromet as h

E='EXPLICIT SYNTHETIC FORCING; NOT DIADEM MEASUREMENT'
S='SYNTHETIC TEST'
B='a'*64
I='b'*64


def scenario():return h.SnowScenario('LOW_DDF3_SIGMA2',3.,2.,'COEQUAL_SENSITIVITY')


def state(s=None,swe=F(1,100)):
    return h.initial_snow('cell',s or scenario(),swe,binding_sha256=B,elapsed_seconds=0,evidence=E)


def snow(st=None,s=None,**changes):
    s=s or scenario();st=st or state(s)
    args=dict(temperature_c=1.,precipitation_m_s=F(1,1000000),snowfall_m_s=F(1,2000000),
        start_seconds=st.elapsed_seconds,duration_seconds=3600,day_seconds=86400,interval_id='interval',
        input_sha256=I,binding_sha256=B,evidence=E,source_status=S,temperature_distribution_evidence=E)
    args.update(changes)
    return h.snow_step(st,s,**args)


def air(**changes):
    p=100000.;ea=1400.;eps=.622
    values={'temperature_c':20.,'pressure_pa':p,'specific_humidity_kg_kg':eps*ea/(p-(1-eps)*ea),
            'saturation_vapour_pressure_pa':2300.,'saturation_slope_pa_k':145.,
            'moist_air_density_kg_m3':1.2,'saturation_convention':'LIQUID_WATER','vapour_pressure_pa':ea}
    values.update(changes);return values


def constants():return h.DemandConstants(1013.,2450000.,.622,1000.,E)


def surface(**changes):return replace(h.DemandSurface(150.,10.,100.,70.,E),**changes)


def demand(a=None,sf=None,c=None):return h.penman_monteith(a or air(),sf or surface(),c or constants(),evidence=E,source_status=S)


class HydrometTests(unittest.TestCase):
    def test_all_three_actual_pinned_scenarios_coequal(self):
        rows=h.snow_scenarios()
        self.assertEqual([(s.scenario_id,s.degree_day_factor_mm_c_day,s.temperature_sigma_c) for s in rows],
            [('LOW_DDF3_SIGMA2',3,2),('DIAGNOSTIC_DDF4_SIGMA4',4,4),('HIGH_DDF5_SIGMA6',5,6)])
        self.assertTrue(all(s.standing=='COEQUAL_SENSITIVITY' for s in rows))

    def test_no_invented_default_or_preferred_middle_scenario(self):
        with self.assertRaises(ValueError):replace(scenario(),standing='PREFERRED')
        with self.assertRaises(ValueError):replace(scenario(),degree_day_factor_mm_c_day=4.)

    def test_changed_retained_source_rejects(self):
        with patch.dict(h.PINS,{str(h.SNOW_SOURCE):'0'*64}):
            with self.assertRaisesRegex(ValueError,'protected'):h.snow_scenarios()

    def test_positive_temperature_independent_quadrature(self):
        for t,sigma in ((-20,2),(-2,2),(0,4),(4,6),(20,2)):
            expected=quad(lambda x:x*math.exp(-.5*((x-t)/sigma)**2)/(sigma*math.sqrt(2*math.pi)),0,max(100,t+15*sigma),epsabs=1e-28,epsrel=1e-11)[0]
            self.assertAlmostEqual(h.positive_temperature(t,sigma),expected,delta=max(1e-28,expected*2e-11))

    def test_zero_mean_closed_form_and_negative_mean_nonzero(self):
        self.assertEqual(h.positive_temperature(0,4),4/math.sqrt(2*math.pi))
        self.assertGreater(h.positive_temperature(-4,2),0)

    def test_unrepresentable_cold_tail_rejects_not_fake_zero(self):
        with self.assertRaises(ValueError):h.positive_temperature(-1000,2)

    def test_phase_limits_and_exact_mixture(self):
        law=h.PhaseLaw(-1.,3.,'AIR_TEMPERATURE',E)
        for t,frac in ((-10,F(1)),(-1,F(1)),(1,F(1,2)),(3,F(0)),(10,F(0))):
            r=h.partition_precipitation(F(1,123),t,law,evidence=E,source_status=S)
            self.assertEqual(r['snow_fraction'],frac)
            self.assertEqual(r['rain_m_s']+r['snowfall_m_s'],F(1,123))

    def test_wet_bulb_phase_distinct_from_air(self):
        law=h.PhaseLaw(-1.,3.,'SUPPLIED_WET_BULB',E)
        r=h.partition_precipitation(F(1,100),2,law,wet_bulb_c=0,evidence=E,source_status=S)
        self.assertEqual(r['snow_fraction'],F(3,4))
        with self.assertRaises(ValueError):h.partition_precipitation(1,2,law,wet_bulb_c=3,evidence=E,source_status=S)

    def test_unknown_phase_never_zero(self):
        r=h.partition_precipitation(None,2,h.PhaseLaw(-1,3,'AIR_TEMPERATURE',E),evidence=E,source_status=S)
        self.assertEqual(r['status'],'UNKNOWN');self.assertIsNone(r['rain_m_s'])

    def test_wet_bulb_analytic_linear_saturation_oracle(self):
        # es=1000+100*T; 1000+100*Tw-50*(10-Tw)=1200 -> Tw=14/3.
        r=h.psychrometric_wet_bulb(10,1200,50,saturation_liquid=lambda t:(1000+100*t,100),
            lower_bound_c=-5,temperature_atol_c=1e-10,vapour_atol_pa=1e-8,max_iterations=100,evidence=E)
        self.assertEqual(r['status'],'MODELLED');self.assertAlmostEqual(r['wet_bulb_c'],14/3,places=8)

    def test_wet_bulb_saturation_identity_and_unknown_regime(self):
        kwargs=dict(saturation_liquid=lambda t:(1000+100*t,100),lower_bound_c=-5,
                    temperature_atol_c=1e-8,vapour_atol_pa=1e-8,max_iterations=100,evidence=E)
        self.assertEqual(h.psychrometric_wet_bulb(10,2000,50,**kwargs)['wet_bulb_c'],10)
        self.assertEqual(h.psychrometric_wet_bulb(10,2100,50,**kwargs)['status'],'OUTSIDE_REGIME')
        kwargs['max_iterations']=1
        self.assertEqual(h.psychrometric_wet_bulb(10,1200,50,**kwargs)['status'],'NUMERICAL_FAILURE')

    def test_snow_and_total_water_exact_conservation(self):
        r=snow();l=r['ledger']
        self.assertEqual(l['snow_residual_m'],0);self.assertEqual(l['total_water_residual_m'],0)
        self.assertEqual(l['initial_swe_m']+l['precipitation_m'],l['final_swe_m']+l['liquid_to_soil_m'])
        self.assertEqual(r['liquid_input_m_s']*3600,l['liquid_to_soil_m'])

    def test_swe_never_melts_nonexistent_stock(self):
        r=snow(state(swe=F(1,10000)),temperature_c=20,duration_seconds=86400,precipitation_m_s=0,snowfall_m_s=0)
        self.assertEqual(r['ledger']['melt_m'],F(1,10000));self.assertEqual(r['state'].swe_m,0)
        self.assertIsNotNone(r['depletion_after_seconds'])

    def test_continuous_snowfall_does_not_arrive_all_at_start(self):
        r=snow(state(swe=0),temperature_c=20,duration_seconds=60)
        self.assertEqual(r['ledger']['melt_m'],F(60,2000000))
        self.assertEqual(r['state'].swe_m,0)
        self.assertEqual(r['mean_melt_m_s'],F(1,2000000))

    def test_exact_split_preserves_physical_snow_and_total_transfers(self):
        st=state(swe=F(1,10000))
        full=snow(st,temperature_c=20,duration_seconds=600)
        first=snow(st,temperature_c=20,duration_seconds=300)
        second=snow(first['state'],temperature_c=20,duration_seconds=300)
        self.assertEqual(full['state'].swe_m,second['state'].swe_m)
        for key in ('melt_m','liquid_to_soil_m','precipitation_m'):
            self.assertEqual(full['ledger'][key],first['ledger'][key]+second['ledger'][key])
        self.assertGreater(first['mean_melt_m_s'],second['mean_melt_m_s'])

    def test_no_implicit_earth_day(self):
        a=snow(temperature_c=1,duration_seconds=1000)
        b=snow(temperature_c=1,duration_seconds=1000,day_seconds=90000)
        self.assertEqual(a['ledger']['potential_melt_m']*86400,b['ledger']['potential_melt_m']*90000)
        self.assertIn('NOT_RETAINED_NUMERICS',b['coefficient_day_role'])

    def test_exact_depletion_split_has_no_smeared_initial_stock(self):
        initial=state(swe=F(1,10000))
        full=snow(initial,temperature_c=20,duration_seconds=600)
        tau=full['depletion_after_seconds'];self.assertGreater(tau,0);self.assertLess(tau,600)
        first=snow(initial,temperature_c=20,duration_seconds=tau)
        self.assertEqual(first['state'].swe_m,0)
        second=snow(first['state'],temperature_c=20,duration_seconds=F(600)-tau)
        self.assertEqual(second['mean_melt_m_s'],F(1,2000000))
        self.assertEqual(full['ledger']['melt_m'],first['ledger']['melt_m']+second['ledger']['melt_m'])

    def test_declared_varying_temperature_refinement(self):
        # Independent time integral of a linear temperature scenario; Gaussian
        # expectation is coded with erf here, not the production helper/ndtr.
        def capacity(t):
            mean=-4+8*t
            positive=2*math.exp(-mean*mean/8)/math.sqrt(2*math.pi)+mean*.5*(1+math.erf(mean/math.sqrt(8)))
            return .003*positive
        expected=quad(capacity,0,1,epsabs=1e-14,epsrel=1e-13)[0]
        errors=[]
        for n in (4,8,16):
            st=state(swe=1);total=F()
            for i in range(n):
                r=snow(st,temperature_c=-4+8*(i+.5)/n,precipitation_m_s=0,snowfall_m_s=0,duration_seconds=F(86400,n))
                st=r['state'];total+=r['ledger']['melt_m']
            errors.append(abs(float(total)-expected))
        self.assertGreater(errors[0]/errors[1],3.8);self.assertGreater(errors[1]/errors[2],3.8)

    def test_repeated_interval_and_changed_binding_reject(self):
        r=snow()
        with self.assertRaises(ValueError):snow(r['state'],start_seconds=0)
        with self.assertRaises(ValueError):snow(binding_sha256='c'*64)
        with self.assertRaises(ValueError):snow(start_seconds=1)

    def test_restart_no_annual_reset_and_exact_continuation(self):
        a=snow();restored=h.restore_snow(h.state_json(a['state']))
        self.assertEqual(snow(a['state']),snow(restored))
        b=snow(a['state'],temperature_c=-5)
        self.assertEqual(b['ledger']['initial_swe_m'],a['ledger']['final_swe_m'])

    def test_snow_checkpoint_unknown_fields_and_negative_stock_reject(self):
        raw=h.state_json(state())
        with self.assertRaises(ValueError):h.restore_snow({**raw,'extra':1})
        with self.assertRaises(ValueError):h.restore_snow({**raw,'swe_m':'-1'})

    def test_unknown_snow_forcing_has_no_usable_liquid(self):
        r=snow(temperature_c=None)
        self.assertEqual(r['status'],'UNKNOWN');self.assertIsNone(r['liquid_input_m_s']);self.assertIsNone(r['state'])

    def test_retained_actual_snow_year_matches_from_same_initial_store(self):
        from work.module_review_environment_r1 import bindings
        old=bindings.bind('cryosphere_science')
        sf=np.array([20,20,10,5,0,0,0,0,0,5,10,20],float).reshape(12,1,1)
        temp=np.array([-4,-3,0,2,6,10,12,10,5,2,-1,-3],float).reshape(12,1,1)
        days=(31,28,31,30,31,30,31,31,30,31,30,31)
        for s in h.snow_scenarios():
            prior=old.simulate_snow_year(sf,temp,np.ones((1,1),bool),s.degree_day_factor_mm_c_day,s.temperature_sigma_c)
            st=state(s,F(float(prior.initial_swe_mm[0,0]))/1000)
            for month,d in enumerate(days):
                duration=d*86400;rate=F(float(sf[month,0,0]))/1000/duration
                r=snow(st,s,temperature_c=float(temp[month,0,0]),precipitation_m_s=rate,snowfall_m_s=rate,duration_seconds=duration)
                self.assertAlmostEqual(float(r['ledger']['melt_m'])*1000,float(prior.monthly_melt_mm[month,0,0]),delta=1e-10)
                st=r['state']
            self.assertAlmostEqual(float(st.swe_m)*1000,float(prior.final_swe_mm[0,0]),delta=1e-10)

    def test_declared_disaggregation_exact_totals_no_default_weights(self):
        rows=h.disaggregate_total(F(1,10),(100,200,300),(F(1,2),F(1,3),F(1,6)),evidence=E)
        self.assertEqual(sum((r['rate_m_s']*r['duration_seconds'] for r in rows),F()),F(1,10))
        with self.assertRaises(ValueError):h.disaggregate_total(1,(100,100),(.1,.1),evidence=E)

    def test_penman_monteith_independent_decimal_formula(self):
        a=air();sf=surface();c=constants();r=demand(a,sf,c)
        with localcontext() as ctx:
            ctx.prec=60
            p=D(a['pressure_pa']);q=D(a['specific_humidity_kg_kg']);eps=D(c.molecular_mass_ratio)
            ea=p*q/(eps+(1-eps)*q);gamma=D(c.cp_air_j_kg_k)*p/(eps*D(c.latent_heat_j_kg))
            delta=D(a['saturation_slope_pa_k']);ra=D(sf.aerodynamic_resistance_s_m)
            expected=(delta*(D(sf.net_radiation_w_m2)-D(sf.ground_heat_flux_w_m2))+
                D(a['moist_air_density_kg_m3'])*D(c.cp_air_j_kg_k)*(D(a['saturation_vapour_pressure_pa'])-ea)/ra)/(
                delta+gamma*(1+D(sf.surface_resistance_s_m)/ra))
        self.assertAlmostEqual(r['signed_latent_heat_flux_w_m2'],float(expected),places=12)

    def test_published_fao56_example18_resistance_form_limit(self):
        # FAO56 Eq3 using rounded Example18 weather and its stated reference
        # resistance/virtual-temperature approximations; not field calibration.
        p=100100.;ea=1409.;eps=.622;t=16.9;u=2.078
        a=air(temperature_c=t,pressure_pa=p,specific_humidity_kg_kg=eps*ea/(p-(1-eps)*ea),
            vapour_pressure_pa=ea,saturation_vapour_pressure_pa=1997.,saturation_slope_pa_k=122.,
            moist_air_density_kg_m3=p/(287.*1.01*(t+273.)))
        r=demand(a,h.DemandSurface(13.28e6/86400,0,208/u,70,E))
        self.assertAlmostEqual(r['potential_evaporation_m_s']*86400*1000,3.88,delta=.015)

    def test_potential_demand_not_actual_et(self):
        r=demand();self.assertGreater(r['potential_evaporation_m_s'],0)
        self.assertIsNone(r['actual_et_m_s']);self.assertIsNone(r['actual_condensation_m_s'])

    def test_negative_energy_keeps_condensation_potential_signed(self):
        r=demand(sf=surface(net_radiation_w_m2=-100))
        self.assertLess(r['signed_latent_heat_flux_w_m2'],0)
        self.assertEqual(r['potential_evaporation_m_s'],0)
        self.assertGreater(r['potential_condensation_m_s'],0)

    def test_zero_energy_saturated_air_zero_flux(self):
        eps=.622;p=100000.;es=2300.
        a=air(specific_humidity_kg_kg=eps*es/(p-(1-eps)*es),vapour_pressure_pa=es)
        r=demand(a,surface(net_radiation_w_m2=0,ground_heat_flux_w_m2=0))
        self.assertAlmostEqual(r['signed_latent_heat_flux_w_m2'],0,places=11)

    def test_radiation_humidity_and_surface_resistance_sensitivity(self):
        base=demand()['potential_evaporation_m_s']
        self.assertGreater(demand(sf=surface(net_radiation_w_m2=300))['potential_evaporation_m_s'],base)
        self.assertLess(demand(sf=surface(surface_resistance_s_m=300))['potential_evaporation_m_s'],base)
        a=air(specific_humidity_kg_kg=0,vapour_pressure_pa=0)
        self.assertGreater(demand(a)['potential_evaporation_m_s'],base)

    def test_unknown_demand_and_wrong_thermodynamic_basis_reject(self):
        r=demand(air(saturation_slope_pa_k=None));self.assertEqual(r['status'],'UNKNOWN')
        with self.assertRaises(ValueError):demand(air(saturation_convention='ICE'))
        with self.assertRaises(ValueError):demand(air(vapour_pressure_pa=1600))
        with self.assertRaises(ValueError):demand(air(epsilon=.623))

    def test_actual_climate_producer_air_to_phase_snow_and_demand(self):
        from . import climate
        a=climate.AirMass(0,10,100000,.006,5,0,10000,.004,.001,9.81,287.05,.622,1000,E)
        c=climate.Controls(100,200,100,1,0,.01,1,.1,3,E)
        produced=climate.generate((climate.Cell('a',1000,1000,0,E),climate.Cell('b',1000,1000,100,E)),a,c)
        row=produced['cells']['b']
        pm=demand(row)
        self.assertEqual(pm['status'],'MODELLED');self.assertGreater(pm['potential_evaporation_m_s'],0)
        wb=h.psychrometric_wet_bulb(row['temperature_c'],row['vapour_pressure_pa'],pm['psychrometric_constant_pa_k'],
            saturation_liquid=climate.saturation_liquid,lower_bound_c=-50,temperature_atol_c=1e-8,
            vapour_atol_pa=1e-6,max_iterations=100,evidence=E)
        self.assertEqual(wb['status'],'MODELLED');self.assertLess(wb['wet_bulb_c'],row['temperature_c'])
        phase=h.partition_precipitation(row['precipitation_m_s'],row['temperature_c'],h.PhaseLaw(-1,3,'SUPPLIED_WET_BULB',E),
            wet_bulb_c=wb['wet_bulb_c'],evidence=E,source_status=S)
        result=snow(temperature_c=row['temperature_c'],precipitation_m_s=phase['precipitation_m_s'],snowfall_m_s=phase['snowfall_m_s'])
        self.assertEqual(result['status'],'MODELLED');self.assertEqual(result['ledger']['total_water_residual_m'],0)

    def test_numeric_and_physical_range_guards(self):
        for bad in (True,float('nan'),float('inf'),-1):
            with self.subTest(bad=bad),self.assertRaises(ValueError):snow(precipitation_m_s=bad)
        with self.assertRaises(ValueError):snow(snowfall_m_s=1)
        with self.assertRaises(ValueError):snow(day_seconds=0)
        with self.assertRaises(ValueError):surface(aerodynamic_resistance_s_m=0)
        with self.assertRaises(ValueError):demand(air(specific_humidity_kg_kg=1))
        with self.assertRaises(ValueError):h.partition_precipitation(1,-300,h.PhaseLaw(-1,3,'AIR_TEMPERATURE',E),evidence=E,source_status=S)


if __name__=='__main__':unittest.main()
