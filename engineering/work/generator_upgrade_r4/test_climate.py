"""Independent atmospheric budgets, thermodynamic limits and spatial cases."""
from dataclasses import replace
from decimal import Decimal as D, localcontext
from fractions import Fraction as F
import json
import math
import unittest
from unittest.mock import patch

import numpy as np
from scipy.integrate import solve_ivp
from . import climate as c

E='EXPLICIT SYNTHETIC TRANSECT; NOT DIADEM CALIBRATION'


def atmosphere(**kw):
    a=c.AirMass(0,20,101325,.0065,10,0,1e6,.012,0,9.80665,287.05,.621945,1000,E)
    return replace(a,**kw)


def controls(**kw):
    s=c.Controls(100,600,600,1,0,1e-6,.5,.1,10,E)
    return replace(s,**kw)


def cells(heights=(0,0,500,1000,1500,500,0),length=5000,width=1000):
    return tuple(c.Cell(str(i),length,width,z,E) for i,z in enumerate(heights))


class ClimateTests(unittest.TestCase):
    def audit(self,result):
        r=result['receipt'];F0=F(0)
        self.assertEqual(F(r['inlet_water_kg_s']),F(r['outlet_vapour_kg_s'])+F(r['outlet_cloud_kg_s'])+F(r['precipitation_kg_s']))
        self.assertEqual(F(r['water_mass_residual_kg_s']),0)
        total=F0
        for row in r['cells']:
            self.assertEqual(F(row['inlet_vapour_kg_s'])+F(row['inlet_cloud_kg_s']),
                F(row['outlet_vapour_kg_s'])+F(row['outlet_cloud_kg_s'])+F(row['precipitation_kg_s']))
            total+=F(row['precipitation_kg_s'])
            for step in row['microphysics']:
                self.assertEqual(F(step['initial_vapour'])+F(step['initial_cloud']),
                    F(step['final_vapour'])+F(step['final_cloud'])+F(step['precipitated']))
        self.assertEqual(total,F(r['precipitation_kg_s']))
        json.dumps(result,allow_nan=False)

    def run_case(self,*args,**kwargs):
        result=c.generate(*args,**kwargs);self.audit(result);return result

    def test_murphy_koop_independent_decimal_formula(self):
        with localcontext() as context:
            context.prec=60
            for kelvin in (180,220,250,273.16,293.15,320):
                t=D(str(kelvin));x=D('.0415')*(t-D('218.8'));ex=(2*x).exp();h=(ex-1)/(ex+1)
                b=D('53.878')-D('1331.22')/t-D('9.44523')*t.ln()+D('.014025')*t
                expected=(D('54.842763')-D('6763.22')/t-D('4.210')*t.ln()+D('.000367')*t+h*b).exp()
                actual,_=c.saturation_liquid(kelvin-273.15)
                self.assertLess(abs(actual/float(expected)-1),5e-14)

    def test_saturation_triple_point_physical_reference(self):
        self.assertAlmostEqual(c.saturation_liquid(.01)[0],611.657,delta=.02)

    def test_saturation_derivative_independent_difference(self):
        for t in (-60,-20,0,20,50):
            es,slope=c.saturation_liquid(t);h=.001
            finite=(c.saturation_liquid(t+h)[0]-c.saturation_liquid(t-h)[0])/(2*h)
            self.assertGreater(es,0);self.assertLess(abs(slope/finite-1),1e-7)

    def test_saturation_domain_unknown_bool_nonfinite(self):
        for bad in (None,True,float('nan'),float('inf'),-151,59):
            with self.assertRaises(ValueError):c.saturation_liquid(bad)

    def test_temperature_lapse_and_isothermal_hydrostatic_oracle(self):
        a=atmosphere(inlet_specific_humidity=.001,lapse_k_m=0)
        result=self.run_case(cells((0,1000)),a,controls())
        expected=101325*math.exp(-a.gravity_m_s2*1000/(a.dry_air_gas_constant_j_kg_k*293.15))
        self.assertAlmostEqual(result['cells']['1']['pressure_pa'],expected,places=9)
        self.assertEqual(result['cells']['1']['temperature_c'],20)
        other=self.run_case(cells((0,1000)),replace(a,lapse_k_m=.0065),controls())
        self.assertAlmostEqual(other['cells']['1']['temperature_c'],13.5,places=12)

    def test_tiny_lapse_has_continuous_isothermal_limit(self):
        a=atmosphere(inlet_specific_humidity=.001,lapse_k_m=0)
        p0=c._thermo(cells((1000,))[0],a)[1]
        p1=c._thermo(cells((1000,))[0],replace(a,lapse_k_m=1e-25))[1]
        self.assertEqual(p0,p1)

    def test_moist_specific_humidity_pressure_density_identity(self):
        a=atmosphere();result=self.run_case(cells(),a,controls())
        for row in result['cells'].values():
            q=row['specific_humidity_kg_kg'];p=row['pressure_pa'];t=row['temperature_c']+273.15
            e=p*q/(a.epsilon+(1-a.epsilon)*q)
            density=(p-e)/(a.dry_air_gas_constant_j_kg_k*t)+e/(a.dry_air_gas_constant_j_kg_k/a.epsilon*t)
            self.assertEqual(e,row['vapour_pressure_pa'])
            self.assertAlmostEqual(density,row['moist_air_density_kg_m3'],places=14)
            self.assertEqual(row['saturation_convention'],'LIQUID_WATER')

    def test_cloud_is_not_in_specific_humidity(self):
        base=atmosphere(inlet_specific_humidity=.005,inlet_condensate_kg_per_kg_dry_air=.01)
        out=self.run_case(cells((0,)),base,controls(evaporation_seconds=1e20))
        row=out['cells']['0']
        self.assertAlmostEqual(row['specific_humidity_kg_kg'],.005,places=14)
        self.assertGreater(row['cloud_mixing_ratio_kg_per_kg_dry_air'],0)

    def test_equal_timescale_two_exponential_wait_oracle(self):
        v,cloud,rain,_=c._transition(F(3,100),F(1,100),F(1,100),200,controls(condensation_seconds=100,fallout_seconds=100))
        dec=math.exp(-2);excess=.02
        self.assertAlmostEqual(float(v),.01+excess*dec,places=15)
        self.assertAlmostEqual(float(cloud),.01*dec+excess*2*dec,places=15)
        self.assertAlmostEqual(float(rain),.04-float(v)-float(cloud),places=15)

    def test_unequal_timescale_against_independent_ode(self):
        con=controls(condensation_seconds=130,fallout_seconds=740)
        actual=c._transition(F(3,100),F(1,100),F(1,100),321,con)
        def rhs(t,y):
            cond=(y[0]-.01)/130;fall=y[1]/740
            return (-cond,cond-fall,fall)
        oracle=solve_ivp(rhs,(0,321),(.03,.01,0),rtol=2e-12,atol=1e-14,method='DOP853').y[:,-1]
        np.testing.assert_allclose([float(v) for v in actual[:3]],oracle,rtol=3e-11,atol=1e-13)

    def test_lee_evaporation_parallel_competing_rates_oracle(self):
        con=controls(evaporation_seconds=100,fallout_seconds=200)
        v,cloud,rain,_=c._transition(0,F(1,100),1,20,con)
        lost=.01*-math.expm1(-.015*20)
        self.assertAlmostEqual(float(v),lost*2/3,places=16)
        self.assertAlmostEqual(float(rain),lost/3,places=16)
        self.assertAlmostEqual(float(cloud),.01-lost,places=16)

    def test_evaporation_saturation_switch_does_not_overfill_vapour(self):
        con=controls(evaporation_seconds=100,fallout_seconds=200)
        v,cloud,rain,_=c._transition(0,F(1,100),F(1,1000),200,con)
        self.assertEqual(v,F(1,1000));self.assertEqual(v+cloud+rain,F(1,100))
        self.assertGreater(cloud,0);self.assertGreater(rain,0)

    def test_flat_dry_air_has_no_created_precipitation(self):
        out=self.run_case(cells((0,0,0)),atmosphere(inlet_specific_humidity=.003),controls())
        self.assertEqual(F(out['receipt']['precipitation_kg_s']),0)
        self.assertTrue(all(row['specific_humidity_kg_kg']==.003 for row in out['cells'].values()))

    def test_ridge_condenses_and_depletes_finite_incoming_vapour(self):
        flat=self.run_case(cells((0,)*7),atmosphere(),controls())
        ridge=self.run_case(cells(),atmosphere(),controls())
        self.assertEqual(F(flat['receipt']['precipitation_kg_s']),0)
        self.assertGreater(F(ridge['receipt']['precipitation_kg_s']),0)
        self.assertLess(F(ridge['receipt']['outlet_vapour_kg_s']),F(ridge['receipt']['inlet_water_kg_s']))

    def test_reversed_wind_reverses_actual_traversal_and_rain_shadow(self):
        terrain=cells((0,500,1000,1500,1000,500,0))
        a=self.run_case(terrain,atmosphere(),controls())
        b=self.run_case(terrain,atmosphere(wind_east_10m_m_s=-10),controls())
        self.assertEqual(b['receipt']['traversal'],list(reversed(a['receipt']['traversal'])))
        for i in range(7):self.assertEqual(a['cells'][str(i)]['precipitation_m_s'],b['cells'][str(6-i)]['precipitation_m_s'])
        self.assertEqual(a['cells']['0']['wind_from_degrees'],270)
        self.assertEqual(b['cells']['0']['wind_from_degrees'],90)

    def test_finite_fallout_displaces_peak_downwind(self):
        # Uniform cold terrain, supersaturated open inflow: known two-stage
        # condensation/fallout pulse, not an elevation-only rain mapping.
        terrain=cells((0,)*20,length=1000)
        a=atmosphere(reference_temperature_c=5,inlet_specific_humidity=.012)
        fast=self.run_case(terrain,a,controls(condensation_seconds=300,fallout_seconds=100))
        slow=self.run_case(terrain,a,controls(condensation_seconds=300,fallout_seconds=1000))
        def peak(r):return max(range(20),key=lambda i:r['cells'][str(i)]['precipitation_m_s'])
        self.assertGreater(peak(slow),peak(fast))

    def test_mountain_width_matters_even_with_same_heights(self):
        narrow=self.run_case(cells(),atmosphere(),controls())
        wide=self.run_case(cells(length=10000),atmosphere(),controls())
        self.assertNotAlmostEqual(float(F(narrow['receipt']['precipitation_kg_s'])),float(F(wide['receipt']['precipitation_kg_s'])),places=7)

    def test_piecewise_constant_spatial_subdivision_semigroup(self):
        terrain=cells((0,1000,0))
        fine=tuple(c.Cell(f'{row.cell_id}:{i}',row.length_m/2,row.width_m,row.elevation_m,E) for row in terrain for i in (0,1))
        a=self.run_case(terrain,atmosphere(),controls())
        b=self.run_case(fine,atmosphere(),controls())
        for name in ('precipitation_kg_s','outlet_cloud_kg_s','outlet_vapour_kg_s'):
            self.assertAlmostEqual(float(F(a['receipt'][name])),float(F(b['receipt'][name])),delta=1e-9)

    def test_precipitation_depth_and_mass_units(self):
        air=atmosphere();out=self.run_case(cells(),air,controls())
        for row in out['receipt']['cells']:
            field=out['cells'][row['cell_id']]
            exact=F(row['precipitation_kg_s'])/(F(row['area_m2'])*F(air.water_density_kg_m3))
            self.assertEqual(F(field['precipitation_m_s'])-exact,F(field['precipitation_representation_error_m_s']))
            delivered=F(field['precipitation_m_s'])*F(row['area_m2'])*F(air.water_density_kg_m3)
            self.assertEqual(delivered,F(row['delivered_precipitation_kg_s']))
            self.assertEqual(delivered-F(row['precipitation_kg_s']),F(row['precipitation_flux_conversion_error_kg_s']))
        self.assertEqual(sum((F(r['delivered_precipitation_kg_s']) for r in out['receipt']['cells']),F()),F(out['receipt']['delivered_precipitation_kg_s']))
        self.assertEqual(F(out['receipt']['delivered_precipitation_kg_s'])-F(out['receipt']['precipitation_kg_s']),F(out['receipt']['precipitation_flux_conversion_error_kg_s']))

    def test_smooth_ridge_spatial_refinement(self):
        # Declared before this experiment: a midpoint thermal approximation can
        # mix first/second order near phase boundaries. Broad ratio band [1.3,6]
        # must show decreasing nonzero differences, not empirical calibration.
        results=[self.run_case(cells(tuple(1500*math.sin(math.pi*(i+.5)/n)**2 for i in range(n)),length=80000/n),atmosphere(),controls()) for n in (8,16,32)]
        vectors=[[float(F(r['receipt'][k])) for k in ('precipitation_kg_s','outlet_vapour_kg_s','outlet_cloud_kg_s')] for r in results]
        differences=[sum(abs(a-b) for a,b in zip(vectors[i],vectors[i+1])) for i in (0,1)]
        self.assertGreater(min(differences),1e-8)
        self.assertGreaterEqual(differences[0]/differences[1],1.3)
        self.assertLessEqual(differences[0]/differences[1],6)

    def test_continuous_cloud_peak_not_hidden_by_small_endpoints(self):
        air=atmosphere(reference_pressure_pa=100000,lapse_k_m=0,wind_east_10m_m_s=5,
                       dry_air_flux_kg_s=10000,inlet_specific_humidity=.025)
        con=controls(condensation_seconds=10,fallout_seconds=10,evaporation_seconds=100,maximum_cloud_mixing_ratio=.0001)
        rs=c._thermo(cells((0,),length=1000)[0],air)[4]
        excess=float(F(.025)/(1-F(.025))-rs)
        self.assertGreater(excess/math.e,con.maximum_cloud_mixing_ratio)
        self.assertLess(excess*10*math.exp(-10),con.maximum_cloud_mixing_ratio)
        with self.assertRaisesRegex(ValueError,'continuous cloud envelope'):
            c.generate(cells((0,),length=1000),air,con)

    def test_long_fallout_retains_or_rejects_positive_tail_never_erases_it(self):
        for vapour,saturation in ((F(1,100),F(1,100)),(F(),F(1,100))):
            with self.assertRaisesRegex(ValueError,'branch vanished'):
                c._transition(vapour,F(1,1000),saturation,50,controls(fallout_seconds=1,evaporation_seconds=1))

    def test_calm_crosswind_and_unknown_not_zero_climate(self):
        for air in (atmosphere(wind_east_10m_m_s=0),atmosphere(wind_north_10m_m_s=1)):
            with self.assertRaises(ValueError):c.generate(cells(),air,controls())
        for bad in (None,True,float('nan'),float('inf'),1):
            with self.assertRaises(ValueError):atmosphere(inlet_specific_humidity=bad)

    def test_regime_duplicate_width_and_steepness_rejected(self):
        for terrain in ((cells()[0],cells()[0]),(cells()[0],replace(cells()[1],width_m=900)),cells((0,10000),length=100)):
            with self.assertRaises(ValueError):c.generate(terrain,atmosphere(),controls())
        with self.assertRaises(ValueError):c.generate(cells(),atmosphere(),controls(maximum_supersaturation=1))

    def test_extreme_arithmetic_rejected_not_silently_zero_branch(self):
        with self.assertRaises(ValueError):c._transition(1,0,F(1,10),1e-300,controls(condensation_seconds=1e300,fallout_seconds=1e300,evaporation_seconds=1e300))
        with self.assertRaises(ValueError):c._transition(1,0,F(1,10),1e10,controls())

    def test_negative_matrix_probability_cannot_be_conserved_by_clipping(self):
        with patch.object(c,'expm',return_value=np.array([[1,0,0],[-.01,1,0],[.01,0,1]])):
            with self.assertRaisesRegex(ValueError,'negative matrix'):c._transition(F(3,100),0,F(1,100),10,controls())

    def test_read_real_retained_A_monthly_cell_not_G_or_new_terrain(self):
        r=c.retained_candidate_cell(100,100)
        self.assertEqual(r['months'][0],'Jan');self.assertEqual(sum(r['days']),365)
        self.assertFalse(r['new_terrain_compatible']);self.assertEqual(r['cell_km'],5)
        self.assertEqual(r['source_bindings']['monthly']['sha256'],'461cc7680c62ccf1f68aedec6085081031f24c5c67f6caf9f726bedf64b8a39c')
        self.assertIn('identity placeholder',r['G_role'])
        self.assertEqual(r['parent_elevation_m'],1032.98583984375)
        self.assertTrue(all(0<=s<=p for s,p in zip(r['fields']['snowfall_we_mm'],r['fields']['precipitation_mm'])))

    def test_retained_sea_cell_not_land_and_bad_window_rejected(self):
        with self.assertRaises(ValueError):c.retained_candidate_cell(200,200)
        for row,col in ((True,0),(-1,0),(372,0),(0,440)):
            with self.assertRaises(ValueError):c.retained_candidate_cell(row,col)

    def test_new_reference_does_not_claim_old_A_G_recomputation(self):
        r=self.run_case(cells(),atmosphere(),controls())['receipt']
        self.assertFalse(r['old_climate_parent_reused']);self.assertFalse(r['production_authorised'])
        self.assertIn('externally maintained',r['thermal_profile'])


if __name__=='__main__':unittest.main()
