"""Complete numerical reference; unresolved actual taxa remain explicitly separate."""
from copy import deepcopy
from . import binding, owner_inputs, upstream

E='SYNTHETIC TEST: engineering occupancy/density/transfer hypothesis on actual R8 physics; not established Diadem biology or calibrated occurrence'


def recipe(bundle,*,include_retained=True):
    parent=bundle.parent.reference.recipe(bundle.parent)
    seasons=[{'season_id':'warm','months':[6,7,8],'evidence':E},
             {'season_id':'cold','months':[12,1,2],'evidence':E}]
    taxa={}
    for ident,kind,moving,density in (('TEST-PLANT','PLANT',False,'1/100'),('TEST-ANIMAL','ANIMAL',True,'1/10000')):
        models={}
        for season in seasons:
            sid=season['season_id']
            requirements=[{'metric':'mineral_solum_m','unit':'m','points':[[0,0],[0.1,1],[100,1]],'outside':'HOLD','evidence':E},
                {'metric':'temperature_mean_c','unit':'degC','points':[[-100,0],[-20,1],[40,1],[100,0]],'outside':'HOLD','evidence':E}]
            if sid=='warm':
                requirements.append({'metric':'pft.grass.seasonal_water_ratio','unit':'1','points':[[0,0],[1,1]],'outside':'HOLD','evidence':E+'; potential plant water-adequacy response, not food biomass'})
            rule={'species_id':ident,'suitability_minimum':0.1,'logit_intercept':-1.,'logit_slope':3.,
                  'conditional_occupied_fraction':'1/2','density_per_occupied_m2':density,
                  'travel_budget':2000 if moving else 0,'travel_unit':'m',
                  'movement_mode':'SEASONAL_MOVEMENT' if moving else 'NONMOVING','evidence':E,'source_status':'SYNTHETIC TEST'}
            edges=[]
            if moving:
                for a,b in (('lower','upper'),('upper','lower')):
                    edges.append({'edge_id':a+'-to-'+b,'source':a,'target':b,'cost_per_m':1,
                        'enabled':True,'capacity_expected_individuals':10,'evidence':E,'source_status':'SYNTHETIC TEST'})
            source,target=('lower','upper') if sid=='warm' else ('upper','lower')
            models[sid]={'requirements':requirements,'habitat_operator':'MINIMUM','allowed_domains':['LAND'],
                'rule':rule,'cells':{c:{'habitat_fraction':'1/2','traversable':True,'evidence':E+'; independently declared test microhabitat area, not biome support relabelled area','source_status':'SYNTHETIC TEST'} for c in ('lower','upper')},
                'origins':[{'cell_id':c,'evidence':E+'; explicit accessibility domain source, not observed occurrence','source_status':'SYNTHETIC TEST'} for c in (('lower',) if moving else ('lower','upper'))],
                'edges':edges,'prescribed_total':None,
                'movement':{'destination_season_id':'cold' if sid=='warm' else 'warm',
                    'requests':[{'request_id':sid+'-transfer','source':source,'target':target,'expected_individuals':5,'priority':0,'evidence':E,'source_status':'SYNTHETIC TEST'}] if moving else [],
                    'receiving_capacity':{'lower':10,'upper':10},'evidence':E+'; independently supplied additional receiving places, not inferred food/carrying capacity','source_status':'SYNTHETIC TEST'}}
        taxa[ident]={'name':ident,'kind':kind,'retained_hs':None,'applicability':'SPATIAL','evidence':E,'source_status':'SYNTHETIC TEST','seasons':models}
    if include_retained:
        for ident,record in owner_inputs.biological_roster().items():
            hs=record['retained_hs']
            taxa[ident]={'name':record['name'],'kind':record['kind'],'retained_hs':hs,
                'applicability':'NONSPATIAL_EVENT' if hs==14 else 'ABSENT_WILD' if hs==19 else 'SPATIAL',
                'evidence':record['evidence']+'; quantitative spatial inputs remain UNKNOWN; full counting/phase constraints retained in biological_owner_contracts.',
                'source_status':'WORKING NON-CANON','seasons':{s['season_id']:None for s in seasons}}
    context={'species_id':'TEST-ANIMAL','counting_unit':'synthetic test animal','life_stage':'explicit mobile test cohort',
        'spatial_scope_id':'R9_REFERENCE_DISJOINT_CELLS','time_basis':'fixed representative test snapshot',
        'snapshot_id':upstream.digest(parent),'joint_scenario_id':'TEST_DENSITY_1','supplier':'Engineering fixture',
        'evidence':E,'source_status':'SYNTHETIC TEST'}
    density={'schema':'diadem.declared-density-input.r9','context':context,
        'cells':[{'cell_id':ident,'eligible':True,'measure':{'value':area,'unit':'m2'},'habitat_fraction':'1/2','occupied_fraction':'1/2',
            'density':{'value':'1/10000','denominator_unit':'m2','basis':'PER_OCCUPIED_MEASURE'},'evidence':E,'source_status':'SYNTHETIC TEST'} for ident,area in (('lower',2000000),('upper',1000000))]}
    allocation={'schema':'diadem.prescribed-stock-input.r9','context':{**context,'joint_scenario_id':'TEST_STOCK_1'},'total_expected_entities':32,
        'cells':[{'cell_id':ident,'eligible':True,'weight':1,'capacity_expected_entities':20,
            'occupied_measure':{'value':area//4,'unit':'m2'},'evidence':E,'source_status':'SYNTHETIC TEST'} for ident,area in (('lower',2000000),('upper',1000000))]}
    abundance=[{'scenario_id':mode,'organism_id':'TEST-ANIMAL','physical_scenario_id':'ALL_COEQUAL','season_id':'warm','mode':mode,'model':model}
        for mode,model in (('DECLARED_DENSITY',density),('PRESCRIBED_STOCK',allocation))]
    return {'schema':binding.RECIPE_SCHEMA,'source_status':'WORKING NON-CANON','source_sha256':bundle.source_sha256,
            'evidence':E,'parent_recipe':parent,'seasons':seasons,'organisms':taxa,
            'placement_seed':'R9-explicit-snapshot-test-seed-1','actual_occurrence_overlays':[],'abundance_scenarios':abundance,
            'cohort_chains':[{'chain_id':'TEST-ANIMAL-SAME-COHORT','organism_id':'TEST-ANIMAL','allocation_scenario_id':'PRESCRIBED_STOCK',
                'seasons':['warm','cold','warm'],'evidence':E+'; finite same-cohort stock accounting, not population history','source_status':'SYNTHETIC TEST'}],
            'limits':'Complete engineering test profiles are separate from retained organism coverage. Missing domain biology/occupancy/density/movement parameters remain incomplete. No actual cover, food biomass, measured occurrence, carrying-capacity or production claim.'}
