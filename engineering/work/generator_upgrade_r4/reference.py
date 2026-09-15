"""Declared SI numerical scenarios, not Diadem calibration or a weather history."""
from dataclasses import replace
from fractions import Fraction as F
from copy import deepcopy
from work.generator_upgrade_r3 import reference as old, soil_inputs as si
from work.generator_upgrade_r3.deps import landscape as ls
from .pipeline import SCHEMA

E = 'SYNTHETIC TEST: two kilometre-scale finite columns; prescribed circulation, thermal events and canopy over explicitly unfrozen soil; Earth-fluid SI reference, not Diadem calibration'


def recipe():
    physical = old.recipe()
    physical['evidence'] = E
    for key,row in physical['cells'].items():
        p = si.HydraulicProfile.from_dict(row['profile']); scale=F(1000000)
        layers=tuple(replace(l,mass_kg=l.mass_kg*scale) for l in p.column.layers)
        base=F(300 if key=='upper' else 0)
        column=ls.Column(p.column.area_m2*scale,base,layers,'SYNTHETIC TEST')
        profile=si.bind_column(column,tuple(b.properties for b in p.bindings),tuple(b.layer_id for b in p.bindings),
            tuple(b.water_volume_m3*scale*F(9,10) for b in p.bindings),profile_id=key,evidence=E)
        row['profile']=profile.as_dict(); row['surface_water_m3']=str(F(row['surface_water_m3'])*scale)
        row['stability_roots']={'basal_cohesion_pa':100,'maximum_active_depth_m':0.5,'mode':'BASAL','evidence':E}
    for connector in physical['connectors']: connector['length_m']=1000
    # A declared lower-erodibility steep transect stays in R3's dilute regime;
    # the existing physical rejection threshold is not weakened.
    for law in physical['erosion']: law['k_per_year'] *= 0.0001
    c=physical['coupling_controls']
    for name in ('water_atol_m3','mass_atol_kg','budget_atol_m3'):c[name]*=1000000
    template=physical['events'][0]
    for row in template['cells'].values():row.update(liquid_input_m_s=0,potential_et_m_s=0)
    physical['events']=[template]
    def event(ident,temperature,humidity,month):
        return {'interval_id':ident,'month':month,'duration_seconds':120,'evidence':E,
            'temperature_distribution_evidence':'Explicit Gaussian subinterval temperature hypothesis under each retained DDF/sigma pair; not unique meteorological history',
            'atmosphere':{'reference_elevation_m':0,'reference_temperature_c':temperature,'reference_pressure_pa':101325,
                'lapse_k_m':0.0065,'wind_east_10m_m_s':5,'wind_north_10m_m_s':0,'dry_air_flux_kg_s':1000000,
                'inlet_specific_humidity':humidity,'inlet_condensate_kg_per_kg_dry_air':0.001,
                'gravity_m_s2':9.81,'dry_air_gas_constant_j_kg_k':287.05,'epsilon':0.622,'water_density_kg_m3':1000,'evidence':E},
            'climate_controls':{'condensation_seconds':300,'fallout_seconds':600,'evaporation_seconds':600,
                'transect_east_unit':1,'transect_north_unit':0,'calm_threshold_m_s':1e-6,'maximum_relief_slope':0.5,
                'maximum_cloud_mixing_ratio':0.1,'maximum_supersaturation':3,'evidence':E},
            'surfaces':{k:{'net_radiation_w_m2':80 if temperature<0 else 180,'ground_heat_flux_w_m2':0,
                'aerodynamic_resistance_s_m':50,'surface_resistance_s_m':70,'evidence':E+'; supplied reference canopy energy/resistance'} for k in physical['cells']},
            'vegetation':{k:{'reference_demand_fraction':0.7,'evidence':E+'; prescribed living canopy transpiration allocation, not species inference',
                'uptake':{'by_layer_id':{k+'-mineral':1},'dry_zero_head_m':-2,'dry_full_head_m':-0.1,
                    'wet_full_head_m':-0.01,'wet_zero_head_m':0,'evidence':E+'; explicitly drought-sensitive synthetic canopy','source_status':'SYNTHETIC TEST'}} for k in physical['cells']},
            'boundaries':{k:{'kind':'fixed_head','head_m':0.1,'evidence':E,'source_status':'SYNTHETIC TEST'} for k in physical['cells']}}
    return {'schema':SCHEMA,'source_status':'SYNTHETIC TEST','evidence':E,'physical_recipe':physical,
        'transect':[{'cell_id':'upper','length_m':1000,'width_m':1000,'evidence':E},
                    {'cell_id':'lower','length_m':2000,'width_m':1000,'evidence':E}],
        'phase':{'snow_at_or_below_c':-1,'rain_at_or_above_c':2,'temperature_basis':'SUPPLIED_WET_BULB','evidence':E+'; explicit humidity-aware phase thresholds, not universal calibration'},
        'phase_controls':{'lower_bound_c':-80,'temperature_atol_c':1e-8,'vapour_atol_pa':1e-5,'max_iterations':100,'evidence':E+'; constant-gamma liquid psychrometric approximation'},
        'demand_constants':{'cp_air_j_kg_k':1004,'latent_heat_j_kg':2450000,'molecular_mass_ratio':0.622,'water_density_kg_m3':1000,'evidence':E},
        'initial_swe_m':{'upper':0.001,'lower':0.001},'day_seconds':86400,'model_day_seconds':86400,
        'calendar':'JAN_DEC_365_FEB28_REPORTING_NOT_EVENT_HISTORY',
        'coupling_controls':{'snow_atol_m':1e-7,'precipitation_atol_m':1e-7,'potential_demand_atol_m':1e-8,
            'temperature_atol_c':1e-4,'humidity_atol_kg_kg':1e-7,'joint_budget_atol_m3':0.3},
        'events':[event('cold-wet-01',-3,0.002,1),event('warm-drier-02',15,0.004,4)]}


def twelve_month_windows():
    """Twelve short representative monthly windows, explicitly NOT a year run."""
    result=recipe(); rows=[]
    for month in range(1,13):
        e=deepcopy(result['events'][0 if month in (1,2,3,10,11,12) else 1])
        e.update(interval_id='representative-window-'+str(month),month=month,duration_seconds=30)
        rows.append(e)
    result['events']=rows
    return result


def verification_reference():
    from .pipeline import run
    return run(recipe())
