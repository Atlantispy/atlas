"""Explicit synthetic SI scenarios; none are fitted Diadem measurements."""
from dataclasses import asdict, replace
from fractions import Fraction as F
from .deps import landscape as ls
from .soil_inputs import MaterialHydraulics, HydraulicProfile, bind_column
from .pipeline import SCHEMA, run

E='SYNTHETIC TEST: prescribed two-column bare mineral landscape; SI Earth-fluid numerical reference, not Diadem calibration'


def recipe():
    props={}
    for material,phase,k in (('substrate','bedrock',1e-6),('mineral','immobile_regolith',2e-6)):
        props[material]=MaterialHydraulics(material,phase,2600,F(1,4),F(1,32),2,2,F(1,2),k,2*k,1000,30,E,'SYNTHETIC TEST')
    cells={}
    for key,area,base in (('upper',1,1),('lower',2,0)):
        layers=tuple(ls.Layer(m,F(1,2)*area*p.grain_density_kg_m3*(1-p.porosity),p.grain_density_kg_m3,p.porosity,p.phase,E)
            for m,p in props.items())
        column=ls.Column(area,base,layers,'SYNTHETIC TEST')
        profile=bind_column(column,tuple(props.values()),tuple(key+'-'+m for m in props),
            tuple(l.porosity*l.bulk_volume_m3 for l in layers),profile_id=key,evidence=E)
        cells[key]={'profile':profile.as_dict(),'surface_water_m3':str(F(area,100)),
            'surface_residence_seconds':600,'saturated_initial_guess_m':0.1,
            'root_lower_layer_id':key+'-mineral','stability_layer_id':key+'-mineral','representative_slope_degrees':20,
            'stability_regime':'SHALLOW_TRANSLATIONAL_SOIL',
            'stability_roots':{'basal_cohesion_pa':0,'maximum_active_depth_m':0,'mode':'ABSENT','evidence':E}}
    erosion=[{'material_id':m,'phase':phase,'k_per_year':0.2 if m=='mineral' else 0.01,
        'reference_runoff_m_year':1.0,'evidence':E} for m,p in props.items() for phase in (p.phase,'mobile_sediment')]
    def event(head):
        return {'duration_seconds':120,'cells':{k:{'liquid_input_m_s':3e-6,'potential_et_m_s':0,'uptake':None,
            'boundary':{'kind':'fixed_head','head_m':head,'evidence':E,'source_status':'SYNTHETIC TEST'}} for k in cells},'evidence':E}
    return {'schema':SCHEMA,'evidence':E,'source_status':'SYNTHETIC TEST','seconds_per_year':31536000,
        'water_density_kg_m3':1000,'gravity_m_s2':9.81,'cells':cells,
        'connectors':[{'connector_id':'upper-lower','source_id':'upper','receiver_id':'lower','length_m':10,'outlet_elevation_m':None,'evidence':E},
            {'connector_id':'lower-exterior','source_id':'lower','receiver_id':None,'length_m':10,'outlet_elevation_m':-1,'evidence':E}],
        'erosion':erosion,'sediment':[{'material_id':m,'settling_m_year':500,'deposited_porosity':0.25,'deposition_order':i,'evidence':E} for i,m in enumerate(props)],
        'deposition_properties':[replace(p,phase='mobile_sediment').as_dict() for p in props.values()],
        'water_controls':{'initial_dt_s':60,'min_dt_s':0.0001,'max_dt_s':120,'theta_atol':1e-5,'head_atol_m':1e-4,
            'flux_integral_atol_m':1e-6,'relative_tolerance':0.005,'nonlinear_mass_atol_m':1e-10,'total_mass_atol_m':1e-8,
            'min_head_m':-1e5,'max_head_m':10,'max_steps':1000,'max_nfev':300},
        'terrain_controls':{'max_relief_change_fraction':0.25,'max_solid_liquid_ratio':0.1,'evidence':E},
        'coupling_controls':{'initial_dt_seconds':120,'min_dt_seconds':15,'max_dt_seconds':120,
            'water_atol_m3':1e-4,'height_atol_m':1e-6,'head_integral_atol_m2':1e-4,'mass_atol_kg':0.01,
            'relative_tolerance':0.01,'budget_atol_m3':1e-7,'max_attempts':100},
        'events':[event(1.05),event(0.95)]}


def verification_reference():
    return run(recipe())


if __name__=='__main__':
    import json
    r=verification_reference()
    print(json.dumps({'status':r['status'],'steps':len(r['state']['history']),
        'water_residual_m3':float(F(r['water_residual_m3'])),
        'surfaces':{k:float(HydraulicProfile.from_dict(p).column.surface_m) for k,p in r['state']['profiles'].items()},
        'stability':{k:p['stability']['mask'] for k,p in r['soil_products'].items()}}))
