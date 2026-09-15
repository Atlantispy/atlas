"""Exact R8 physical projection and declared species habitat requirements."""
from fractions import Fraction as F
import hashlib
import json
import math

BASE_METRICS=frozenset(('elevation_m','soil_ph_water','soil_ec_ds_m','mineral_solum_m',
    'temperature_mean_c','temperature_min_month_c','temperature_max_month_c','precipitation_m','liquid_water_m','reference_pet_m'))


def plain(value):
    if isinstance(value,F): return str(value)
    if isinstance(value,dict):
        if any(type(k) is not str for k in value): raise ValueError('explicit string JSON keys required')
        return {k:plain(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [plain(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(plain(value),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def exact_fields(value,keys,name):
    if type(value) is not dict or set(value)!=set(keys): raise ValueError(name+': exact fields required')
    return value


def text(value):
    if type(value) is not str or not value.strip() or len(value)>4096: raise ValueError('bounded explicit text/evidence required')
    return value


def number(value,*,minimum=0,maximum=1e12):
    if type(value) not in (int,float,F): raise ValueError('explicit finite number required')
    if not minimum<=value<=maximum: raise ValueError('number outside declared bounds')
    represented=float(value)
    if not math.isfinite(represented) or value and represented==0: raise ValueError('number outside representation')
    return represented


def validate_seasons(seasons):
    if type(seasons) is not list or not 1<=len(seasons)<=24: raise ValueError('bounded explicit seasons required')
    seen=set()
    for season in seasons:
        exact_fields(season,('season_id','months','evidence'),'season'); text(season['season_id']); text(season['evidence'])
        months=season['months']
        if season['season_id'] in seen or type(months) is not list or not months or len(set(months))!=len(months) or any(type(m) is not int or not 1<=m<=12 for m in months):
            raise ValueError('unique season/month identities required')
        seen.add(season['season_id'])
    return seasons


def metric(value,unit,evidence,interval=None):
    if value is None: return {'value':None,'interval':None,'unit':unit,'evidence':evidence,'status':'UNKNOWN'}
    value=number(value,minimum=-1e12)
    pair=[value,value] if interval is None else [number(v,minimum=-1e12) for v in interval]
    if len(pair)!=2 or not pair[0]<=value<=pair[1]: raise ValueError('physical metric outside explicit bracket')
    return {'value':value,'interval':pair,'unit':unit,'evidence':evidence,'status':'MODELLED'}


def project(bundle,parent,seasons):
    validate_seasons(seasons)
    if parent['schema']!='diadem.biomes-vegetation-result.r8' or parent['source_sha256']!=bundle.parent.source_sha256:
        raise ValueError('actual source-bound R8 result required')
    if parent['state']['completed_cells']!=sum(len(v) for v in parent['soil_result']['state']['members'].values()):
        raise ValueError('complete upstream cells required')
    source_sha=digest(parent); scenarios={}
    for snow_id,cells in sorted(parent['state']['members'].items()):
        source=parent['seasonal']['members'][snow_id]
        terrain={r['cell_id']:r for r in source['formed_terrain']}
        if set(terrain)!=set(cells): raise ValueError('actual terrain/cell support differs')
        family_sets={tuple(sorted(c['pft_results'])) for c in cells.values()}
        if len(family_sets)!=1: raise ValueError('coequal upstream family inventory differs across cells')
        for family_id in next(iter(family_sets)):
            scenario_id=snow_id+'/'+family_id; scenario={}
            for season in sorted(seasons,key=lambda x:x['season_id']):
                selection=set(season['months']); projected={}
                for cell_id,cell in sorted(cells.items()):
                    cycle=source['cells'][cell_id]; soil=parent['soil_result']['state']['members'][snow_id][cell_id]
                    binding_note='Actual R8 '+source_sha+'; '+snow_id+'/'+family_id+'/'+cell_id+'; '+season['evidence']
                    metrics={'elevation_m':metric(terrain[cell_id]['elevation_m'],'m',binding_note)}
                    chemistry=(soil.get('fertility') or {}).get('exchange')
                    chemistry=None if chemistry is None else chemistry['chemistry']
                    metrics['soil_ph_water']=metric(None if chemistry is None else chemistry['ph_water'],'1',binding_note+'; common whole-profile assay, not nutrient sufficiency')
                    metrics['soil_ec_ds_m']=metric(None if chemistry is None else chemistry['electrical_conductivity_ds_m'],'dS/m',binding_note)
                    horizons=soil['horizons']
                    metrics['mineral_solum_m']=metric(float(F(horizons['mineral_pedogenic_solum_depth_m'])) if horizons['solum_status']=='MODELLED' else None,'m',binding_note)
                    season_months=[]
                    if cycle['status']=='MODELLED_PERIODIC_SNOW':
                        season_months=[r for r in cycle['months'] if r['month_id'] in selection]
                    duration=sum((F(r['duration_seconds']) for r in season_months),F())
                    for name,unit in (('temperature_mean_c','degC'),('temperature_min_month_c','degC'),('temperature_max_month_c','degC'),('precipitation_m','m'),('liquid_water_m','m'),('reference_pet_m','m')):
                        metrics[name]=metric(None,unit,binding_note+'; complete seasonal forcing required')
                    if season_months:
                        if {r['month_id'] for r in season_months}!=selection: raise ValueError('season missing actual months')
                        metrics['temperature_mean_c']=metric(float(sum((F(r['temperature_c'])*F(r['duration_seconds']) for r in season_months),F())/duration),'degC',binding_note)
                        metrics['temperature_min_month_c']=metric(min(r['temperature_c'] for r in season_months),'degC',binding_note+'; mean-month minimum, not daily extremes')
                        metrics['temperature_max_month_c']=metric(max(r['temperature_c'] for r in season_months),'degC',binding_note+'; mean-month maximum, not daily extremes')
                        for key,field in (('precipitation_m','precipitation_m_s'),('reference_pet_m','potential_evaporation_m_s')):
                            metrics[key]=metric(float(sum((F(r[field])*F(r['duration_seconds']) for r in season_months),F())),'m',binding_note)
                        liquid=sum((F(r['snow']['ledger']['liquid_to_soil_m']) for r in season_months),F())
                        metrics['liquid_water_m']=metric(float(liquid),'m',binding_note+'; snow liquid once only, not groundwater/food mass')
                    for pft_id,pft in sorted(cell['pft_results'][family_id].items()):
                        prefix='pft.'+pft_id+'.'
                        metrics[prefix+'annual_admissibility']=metric(1 if pft['status']=='PASS' else 0 if pft['status']=='FAIL' else None,'1',binding_note+'; potential annual PFT constraints, not actual cover')
                        cap=cell['capacities'][pft_id]
                        metrics[prefix+'rooted_capacity_m']=metric(cap['capacity_m'] if cap['status']=='MODELLED' else None,'m',binding_note)
                        ratios=[]
                        if pft['water']['status']=='MODELLED_PERIODIC_BRACKET':
                            for side in ('lower','upper'):
                                events=[r for r in pft['water'][side]['events'] if r['month_id'] in selection and r['active']]
                                demand=math.fsum(r['potential_transpiration_m'] for r in events)
                                if not demand: break
                                ratios.append(math.fsum(r['actual_transpiration_m'] for r in events)/demand)
                        pair=[min(ratios),max(ratios)] if len(ratios)==2 else None
                        metrics[prefix+'seasonal_water_ratio']=metric(None if pair is None else sum(pair)/2,'1',binding_note+'; actual/potential transpiration, not occurrence probability',pair)
                    projected[cell_id]={'cell_id':cell_id,'area_m2':cell['area_m2'],'domain':cell['classification']['domain'],
                        'soil_support_id':cell['soil_support_id'],'parent_cell_sha256':digest(cell),'metrics':metrics,
                        'potential_biome':cell['classification']['broad'],'potential_formation':cell['classification']['formation'],
                        'not_modelled':['actual vegetation cover','food mass or productivity','nutrient sufficiency','wetland hydroperiod','species occurrence'],
                        'source_status':'WORKING NON-CANON'}
                scenario[season['season_id']]={'cells':projected,'months':season['months'],'evidence':season['evidence']}
            scenarios[scenario_id]={'snow_id':snow_id,'biome_family_id':family_id,'seasons':scenario}
    return {'schema':'diadem.species-environment.r9','parent_result_sha256':source_sha,
            'parent_source_sha256':bundle.parent.source_sha256,'seasons_sha256':digest(seasons),
            'scenarios':scenarios,'source_status':'WORKING NON-CANON',
            'scope':'actual R8 physics and potential vegetation, not measured species data; coequal families are alternatives, not additive areas/populations'}


def habitat(cell,requirements,operator):
    """Necessary physical responses with explicit units and unknown intervals."""
    if type(requirements) is not list or not 1<=len(requirements)<=64 or operator not in ('MINIMUM','GEOMETRIC'):
        raise ValueError('bounded explicit species habitat model required')
    domain=cell['domain']
    if domain['kind']=='UNKNOWN' or domain['source_status'] in ('UNKNOWN','INCOMPLETE','CONFLICT'):
        return {'status':'UNKNOWN','support':None,'interval':None,'factors':[],'reason':'independent domain unresolved'}
    factors=[]; seen=set()
    for row in requirements:
        exact_fields(row,('metric','unit','points','outside','evidence'),'habitat response'); text(row['evidence'])
        name=text(row['metric'])
        pieces=name.split('.')
        if name in seen or name not in cell['metrics'] or not (name in BASE_METRICS or len(pieces)==3 and pieces[0]=='pft' and pieces[2] in ('annual_admissibility','rooted_capacity_m','seasonal_water_ratio')):
            raise ValueError('unrecognised/duplicate actual physical metric')
        seen.add(name); actual=cell['metrics'][name]
        exact_fields(actual,('value','interval','unit','evidence','status'),'physical metric record')
        text(actual['evidence'])
        if actual['status'] not in ('MODELLED','UNKNOWN'): raise ValueError('physical status not supported')
        if actual['status']=='UNKNOWN' and (actual['value'] is not None or actual['interval'] is not None): raise ValueError('UNKNOWN metric cannot supply a known value')
        if actual['status']=='MODELLED':
            if actual['value'] is None or actual['interval'] is None: raise ValueError('MODELLED metric requires value and bracket')
            metric(actual['value'],actual['unit'],actual['evidence'],actual['interval'])
        if row['unit']!=actual['unit'] or row['outside'] not in ('HOLD','ZERO'): raise ValueError('explicit physical unit/exterior policy required')
        points=row['points']
        if type(points) is not list or not 2<=len(points)<=32: raise ValueError('bounded response knots required')
        for pair in points:
            if type(pair) is not list or len(pair)!=2: raise ValueError('response pair required')
            number(pair[0],minimum=-1e12); number(pair[1],maximum=1)
        if any(a[0]>=b[0] for a,b in zip(points,points[1:])): raise ValueError('increasing response coordinates required')
        def response(x):
            if x<points[0][0]: return points[0][1] if row['outside']=='HOLD' else 0.
            if x>points[-1][0]: return points[-1][1] if row['outside']=='HOLD' else 0.
            for coordinate,value in points:
                if x==coordinate: return value
            for (a,fa),(b,fb) in zip(points,points[1:]):
                if a<x<b:
                    exact=F(fa)+(F(fb)-F(fa))*(F(x)-F(a))/(F(b)-F(a))
                    return number(exact,maximum=1)
            raise ArithmeticError('response interval not resolved')
        if actual['interval'] is None: pair=None
        else:
            lo,hi=actual['interval']; probes=[lo,hi]+[x for x,y in points if lo<x<hi]
            # ZERO exterior is discontinuous at the supplied endpoints.
            values=[response(x) for x in probes]; pair=[min(values),max(values)]
        factors.append({'metric':name,'actual':actual,'rule':row,'support_interval':pair})
    if any(r['support_interval'] is None for r in factors):
        return {'status':'UNKNOWN','support':None,'interval':None,'factors':factors,'reason':'required ecological input is unknown; no zero/favourable substitute'}
    def combine(values):
        if operator=='MINIMUM': return min(values)
        if 0 in values: return 0.
        result=math.exp(math.fsum(math.log(v) for v in values)/len(values))
        if result==0: raise ArithmeticError('positive habitat support underflowed')
        return number(result,maximum=1)
    pair=[combine([r['support_interval'][i] for r in factors]) for i in (0,1)]
    return {'status':'MODELLED_SUPPORT','support':pair[0],'interval':pair,'factors':factors,
            'meaning':'conservative lower bound of declared habitat-response support, not probability, occupied fraction or density',
            'operator':operator,'source_status':'WORKING NON-CANON'}
