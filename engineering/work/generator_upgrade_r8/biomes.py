"""R8 potential-natural formation hypotheses, not realised vegetation cover.

Three explicitly supplied engineering families share the retained BM1R3 legend
and aggregation semantics. Ecological admissibility, support, uncertainty and
nonterrestrial masks remain separate. No political/species/settlement forcing.
"""
from fractions import Fraction
import math
import json

BROAD_NAMES={1:'Alpine tundra or sparse highland',2:'Cold conifer or subalpine',
    3:'Temperate mixed forest or woodland',4:'Dry grassland or steppe'}
FORMATION_NAMES={1:'Nival or perennial-snow-capable highland',2:'Alpine sparse vegetation',
    3:'Subalpine scrub or open conifer',4:'Cold conifer forest',5:'Montane mixed forest',
    6:'Humid macroforest-capable formation',7:'Mesic temperate forest or woodland',
    8:'Forest-steppe mosaic',9:'Mesic grassland',10:'Dry steppe or scrub'}
COMPATIBILITY={1:(1,2,3),2:(3,4,5),3:(5,6,7,8),4:(8,9,10)}
KNOWN={'CANON','WORKING NON-CANON','SYNTHETIC TEST'}
UNRESOLVED={'UNKNOWN','INCOMPLETE','CONFLICT'}
GUILDS={'COLD_HERB','COLD_SHRUB','COLD_CONIFER','TEMPERATE_TREE','MACROFOREST_TREE','GRASS','DRY_SHRUB'}
NONTERRESTRIAL={'SEA','CONFIRMED_OPEN_WATER','OUTSIDE'}
PHYSICAL_METRIC_UNITS={'warmest_month_temperature_c':'degC','coldest_month_temperature_c':'degC',
    'annual_precipitation_to_reference_pet_ratio':'1','snow_persistence_fraction':'1',
    'annual_precipitation_m':'m','annual_reference_pet_m':'m','mineral_solum_depth_m':'m'}
PFT_METRIC_UNITS={'coldest_month_temperature_c':'degC','warmest_month_temperature_c':'degC',
    'growing_degree_days':'K * supplied calendar day','rooted_depth_m':'m',
    'active_actual_to_potential_transpiration_ratio':'1','dry_active_duration_s':'s','longest_dry_active_spell_s':'s'}


def source_bindings():
    base='C:/Users/LOCAL_USER/Documents/Codex/2026-07-11/referenced-chatgpt-conversation-this-is-untrusted/work/biome_map/'
    owner='C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace/02_Working_Files/Geography/Climate_Biomes_Soils/Scientific_Upgrade_Decisions/2026-09-10-R1/'
    rows=[
        (base+'bm1r3_builder/BM1R3_METHOD_CONTRACT.json','1622e4c00ddcec48340dbb98ad2b67b1c412f926154b63b3a00af5882fdb5abc','retained owner-bound classification semantics'),
        (base+'bm1r3_builder/build_bm1r3_1km.py','9d0e78199ed1f2e772d8729f0173308dae6bcb9beaddc924099b0e24fce95853','reviewed geometric consensus; not executed by new producer'),
        (base+'bm1r2_builder/build_bm1r2_1km.py','1e6208340e799b7da2427fc46fe29ca339fb27c81e1ab48b5a0dde5728d3ed6a','exact retained legend, AST-read in regression only'),
        (base+'bm1r2_scaffold/bm1r2_core.py','6aa5ab6bdbd5f1a28e34ba337e5f6ac85fa045e7502cb0f15d432baf30fb9646','retained compatibility and median semantics, AST-read only'),
        (owner+'CLIMATE_SOILS_OWNER_DECISION_2026-09-10_R1.md','ba909d8a3e34a1722cba51925d602eca28d749a91a7bbf2162baf99221b4de19','owner meanings and current source-status distinctions'),
        (owner+'CLIMATE_SOILS_SOURCE_BINDINGS_2026-09-10_R1.md','b71dc5050baf8f1cedfa6e31473de476fdf1b3e7faee4b842792accc3c244512','owner source closure')]
    return [{'path':path,'sha256':sha,'role':role} for path,sha,role in rows]


def _text(value,name):
    if type(value) is not str or not value.strip() or len(value)>4096:raise ValueError(name+' requires bounded explicit text')
    return value


def _keys(value,names,name):
    if type(value) is not dict or set(value)!=set(names):raise ValueError(name+' has missing or unexpected fields')


def _number(value,name):
    if type(value) not in (int,float):raise ValueError(name+' must be a finite JSON number, not boolean/string')
    try:out=float(value)
    except OverflowError as exc:raise ValueError(name+' outside numerical representation') from exc
    if not math.isfinite(out) or value!=0 and out==0:raise ValueError(name+' outside finite numerical representation')
    return out


def _fraction(value,name):
    out=_number(value,name)
    if not 0<=out<=1:raise ValueError(name+' outside [0,1]')
    return out


def _sequence(value,name,maximum=64):
    if type(value) is not list or len(value)>maximum:raise ValueError(name+' requires a bounded JSON list')


def _points(points):
    _sequence(points,'response points',32)
    if len(points)<2:raise ValueError('at least two response points required')
    result=[]
    for pair in points:
        if type(pair) is not list or len(pair)!=2:raise ValueError('response point must be [physical value, support]')
        result.append((_number(pair[0],'response physical value'),_fraction(pair[1],'response support')))
    if any(a[0]>=b[0] for a,b in zip(result,result[1:])):raise ValueError('response coordinates must increase strictly')
    return result


def response(value,points,outside):
    """Declared piecewise-linear ecological response; no hidden clipping.

    HOLD extends endpoint support; ZERO excludes physical values outside the
    declared interval. Both are scenario assumptions, not fitted probabilities.
    """
    x=_number(value,'actual metric');pairs=_points(points)
    if outside not in {'HOLD','ZERO'}:raise ValueError('explicit response exterior policy required')
    if x<pairs[0][0]:return pairs[0][1] if outside=='HOLD' else 0.
    if x>pairs[-1][0]:return pairs[-1][1] if outside=='HOLD' else 0.
    for coordinate,y in pairs:
        if x==coordinate:return y
    for (x0,y0),(x1,y1) in zip(pairs,pairs[1:]):
        if x0<x<x1:
            # Exact represented affine interpolation avoids overflowing x1-x0.
            weight=(Fraction(x)-Fraction(x0))/(Fraction(x1)-Fraction(x0))
            exact=Fraction(y0)*(1-weight)+Fraction(y1)*weight
            out=float(exact)
            if exact>0 and out==0:raise ValueError('positive ecological response underflowed')
            return out
    raise ArithmeticError('unresolved response interval')


def _combine(values,operation):
    if not values:raise ValueError('empty ecological factor combination')
    if any(value is None for value in values):return None
    if operation=='MINIMUM':return min(values)
    if operation=='MAXIMUM':return max(values)
    if operation!='GEOMETRIC':raise ValueError('unknown factor combination')
    if 0 in values:return 0.
    result=math.exp(math.fsum(math.log(value) for value in values)/len(values))
    if result==0 or not math.isfinite(result):raise ValueError('positive geometric support unrepresentable')
    return result


def _metric_record(record,unit,name):
    _keys(record,('value','unit','source_status','evidence'),'physical metric '+name)
    _text(record['evidence'],'metric evidence')
    if name not in PHYSICAL_METRIC_UNITS or record['unit']!=unit or unit!=PHYSICAL_METRIC_UNITS[name]:raise ValueError('physical metric unit/name mismatch: '+name)
    status=record['source_status']
    if type(status) is not str or status not in KNOWN|UNRESOLVED:raise ValueError('physical metric source status required')
    if status in UNRESOLVED:return None
    value=_number(record['value'],'physical metric '+name)
    if name.endswith('temperature_c') and value<=-273.15:raise ValueError('temperature outside physical regime')
    if name=='snow_persistence_fraction' and not 0<=value<=1:raise ValueError('snow persistence outside [0,1]')
    if name=='annual_precipitation_to_reference_pet_ratio' and value<0:raise ValueError('negative annual water-demand ratio')
    if name in ('annual_precipitation_m','annual_reference_pet_m','mineral_solum_depth_m') and value<0:raise ValueError('negative physical depth')
    return value


def _score_pft(pft_id,spec,result):
    _keys(spec,('metric','unit','points','evidence'),'PFT score rule')
    for key in ('metric','unit','evidence'):_text(spec[key],'PFT score '+key)
    if PFT_METRIC_UNITS.get(spec['metric'])!=spec['unit']:raise ValueError('only actual seasonal PFT metric names/units permitted')
    _points(spec['points'])
    if result is None:return None,{'pft_id':pft_id,'status':'UNKNOWN','reason':'actual PFT evaluation missing'}
    if (type(result) is not dict or result.get('schema')!='diadem.pft-seasonal-admissibility.r8'
            or result.get('pft_id')!=pft_id):raise ValueError('actual PFT schema/identity mismatch')
    units=result.get('metric_units')
    if type(units) is not dict or units.get(spec['metric'])!=spec['unit']:raise ValueError('actual PFT metric unit mismatch')
    status=result.get('status')
    if status=='FAIL':return 0.,{'pft_id':pft_id,'status':'INADMISSIBLE','score':0.,'support_interval':[0.,0.],'reason':'actual ecological constraint failed'}
    if status in ('UNKNOWN','NUMERICAL_FAILURE'):return None,{'pft_id':pft_id,'status':'UNKNOWN','reason':status}
    if status!='PASS':raise ValueError('unknown PFT evaluation status')
    metrics=result.get('metrics')
    if type(metrics) is not dict or spec['metric'] not in metrics:raise ValueError('passing PFT result lacks requested actual metric')
    metric=metrics[spec['metric']]
    if metric is None:return None,{'pft_id':pft_id,'status':'UNKNOWN','reason':'requested ecological score metric unavailable'}
    # Scalar units are explicit in the score rule and retained as the supplied
    # producer contract; arbitrary caller-created affinity scores are not input.
    actual=_number(metric,'actual PFT metric')
    score=response(actual,spec['points'],'HOLD')
    intervals=result.get('metric_intervals')
    pair=intervals.get(spec['metric']) if type(intervals) is dict else None
    if type(pair) is not list or len(pair)!=2:raise ValueError('actual PFT numerical metric bracket required')
    low,high=(_number(v,'PFT metric bracket') for v in pair)
    if not low<=actual<=high:raise ValueError('PFT metric outside its numerical bracket')
    probes=[low,high]+[x for x,y in _points(spec['points']) if low<x<high]
    mapped=[response(x,spec['points'],'HOLD') for x in probes]
    return score,{'pft_id':pft_id,'status':'ADMISSIBLE','metric':spec['metric'],'unit':spec['unit'],
        'actual_value':actual,'metric_interval':[low,high],'score':score,'support_interval':[min(mapped),max(mapped)],
        'rule':spec,'meaning':'normalised declared ecological support, not NPP/probability/cover'}


def _validate_rule(rule,pft_scores,pft_guilds):
    _keys(rule,('code','pft_ids','pft_operator','responses','factor_operator','evidence'),'formation rule')
    code=rule['code']
    if type(code) is not int or code not in FORMATION_NAMES:raise ValueError('exact formation code 1..10 required')
    _text(rule['evidence'],'formation-rule evidence');_sequence(rule['pft_ids'],'required PFT identities')
    if len(rule['pft_ids'])!=len(set(rule['pft_ids'])):raise ValueError('duplicate PFT identity in formation rule')
    for key in rule['pft_ids']:
        _text(key,'PFT identity')
        if key not in pft_scores or key not in pft_guilds:raise ValueError('formation references unresolved PFT definition')
    operation=rule['pft_operator']
    if operation=='NONVEGETATED':
        if code!=1 or rule['pft_ids']:raise ValueError('only explicit F1 snow-capable endpoint may omit viable plants')
    elif operation not in ('ANY','ALL') or not rule['pft_ids']:raise ValueError('explicit nonempty ANY/ALL PFT requirement needed')
    guilds={pft_guilds[key]['guild'] for key in rule['pft_ids']}
    allowed={2:{'COLD_HERB','COLD_SHRUB'},3:{'COLD_SHRUB','COLD_CONIFER'},4:{'COLD_CONIFER'},
        5:{'COLD_CONIFER','TEMPERATE_TREE'},7:{'TEMPERATE_TREE'},9:{'GRASS'},10:{'GRASS','DRY_SHRUB'}}
    if code in allowed and not guilds<=allowed[code]:raise ValueError('PFT guild does not support retained formation meaning F'+str(code))
    if code==5 and (operation!='ALL' or guilds!={'COLD_CONIFER','TEMPERATE_TREE'}):raise ValueError('F5 requires both conifer and temperate-tree potential, not inferred actual mixture')
    if code==6:
        macro=[pft_guilds[key]['guild']=='MACROFOREST_TREE' for key in rule['pft_ids']]
        if not any(macro) or operation=='ANY' and not all(macro):raise ValueError('F6 requires unavoidable explicit macroforest PFT capacity evidence')
    if code==8:
        if operation!='ALL' or not guilds&{'TEMPERATE_TREE','COLD_CONIFER'} or 'GRASS' not in guilds:raise ValueError('F8 requires simultaneous tree and grass admissibility, not inferred realised mosaic')
    if rule['factor_operator'] not in ('GEOMETRIC','MINIMUM'):raise ValueError('explicit family factor combination required')
    _sequence(rule['responses'],'independent climate responses')
    if not rule['responses']:raise ValueError('each formation requires declared independent physical diagnostic response')
    required_metrics=[]
    for item in rule['responses']:
        _keys(item,('metric','unit','points','outside','required','evidence'),'climate response')
        for key in ('metric','unit','evidence'):_text(item[key],'response '+key)
        if PHYSICAL_METRIC_UNITS.get(item['metric'])!=item['unit']:raise ValueError('only named physical climate responses permitted')
        _points(item['points'])
        if type(item['required']) is not bool or item['outside'] not in ('HOLD','ZERO'):raise ValueError('response missing/exterior policies required')
        if item['required']:required_metrics.append(item['metric'])
    if code==1 and not {'snow_persistence_fraction','warmest_month_temperature_c'}<=set(required_metrics):raise ValueError('F1 requires independent snow and thermal support')


def _family(family,pft_results,climate_metrics,pft_guilds):
    _keys(family,('family_id','evidence','pft_score_rules','formations'),'family')
    _text(family['family_id'],'family identity');_text(family['evidence'],'family evidence')
    definitions=family['pft_score_rules']
    if type(definitions) is not dict or not 1<=len(definitions)<=64:raise ValueError('bounded PFT score rules required')
    if type(pft_results) is not dict or set(pft_results)-set(definitions):raise ValueError('PFT result outside defined family')
    scores={};pft_records={}
    for key,spec in sorted(definitions.items()):scores[key],pft_records[key]=_score_pft(key,spec,pft_results.get(key))
    _sequence(family['formations'],'formation inventory',10)
    if any(type(item) is not dict for item in family['formations']):raise ValueError('typed formation rule records required')
    if len(family['formations'])!=10 or {item.get('code') for item in family['formations']}!=set(FORMATION_NAMES):raise ValueError('each family must supply each retained formation exactly once')
    formations={};optional_unknown=[]
    for rule in sorted(family['formations'],key=lambda row:row['code']):
        _validate_rule(rule,scores,pft_guilds);factors=[];bounds=[];records=[]
        if rule['pft_operator']!='NONVEGETATED':
            value=_combine([scores[key] for key in rule['pft_ids']], 'MAXIMUM' if rule['pft_operator']=='ANY' else 'MINIMUM')
            pft_bounds=[pft_records[key].get('support_interval') for key in rule['pft_ids']]
            operator='MAXIMUM' if rule['pft_operator']=='ANY' else 'MINIMUM'
            bounds.append(None if any(x is None for x in pft_bounds) else [_combine([x[i] for x in pft_bounds],operator) for i in (0,1)])
            factors.append(value);records.append({'kind':'PFT_ADMISSIBILITY_AND_SEASONAL_SUPPORT','pft_ids':rule['pft_ids'],'operator':rule['pft_operator'],'score':value})
        for item in rule['responses']:
            raw=climate_metrics.get(item['metric'])
            value=None if raw is None else _metric_record(raw,item['unit'],item['metric'])
            score=None if value is None else response(value,item['points'],item['outside'])
            missing=value is None
            if missing and not item['required']:
                score=1.;optional_unknown.append(item['metric'])
            bounds.append(None if score is None else [score,score])
            factors.append(score);records.append({'kind':'INDEPENDENT_PHYSICAL_RESPONSE','metric':item['metric'],'actual_value':value,
                'unit':item['unit'],'score':score,'missing':missing,'neutral_abstention':missing and not item['required'],'rule':item})
        value=_combine(factors,rule['factor_operator'])
        interval=None if any(x is None for x in bounds) else [_combine([x[i] for x in bounds],rule['factor_operator']) for i in (0,1)]
        formations[rule['code']]={'support':value,'status':'UNKNOWN' if value is None else 'SUPPORTED' if value>0 else 'INADMISSIBLE',
            'support_interval':interval,'factors':records,'operator':rule['factor_operator'],'evidence':rule['evidence']}
    # New explicitly declared R8 hierarchy: maximum compatible formation
    # potential, not a claim to reproduce the old independent EP1 broad scores.
    broad={code:_combine([formations[k]['support'] for k in compatible],'MAXIMUM') for code,compatible in COMPATIBILITY.items()}
    broad_intervals={code:None if any(formations[k]['support_interval'] is None for k in compatible) else
        [max(formations[k]['support_interval'][i] for k in compatible) for i in (0,1)] for code,compatible in COMPATIBILITY.items()}
    return {'family_id':family['family_id'],'evidence':family['evidence'],'pfts':pft_records,'formations':formations,
        'broad_support':broad,'broad_support_intervals':broad_intervals,'optional_missing_metrics':sorted(set(optional_unknown))}


def _selection(scores,margin,tie_tolerance,threshold,intervals=None):
    if any(value is None for value in scores.values()):return {'status':'UNKNOWN','primary_code':None,'tied_codes':[],
        'plausible_codes':[],'selected_support':None,'top_two_margin':None,'low_support':None}
    positive={key:value for key,value in scores.items() if value>0}
    intervals={key:[value,value] for key,value in scores.items()} if intervals is None else intervals
    potential=[key for key,pair in intervals.items() if pair[1]>0]
    if not positive:return {'status':'NUMERICAL_SUPPORT_UNRESOLVED' if potential else 'NO_ADMISSIBLE_CANDIDATE',
        'primary_code':None,'tied_codes':[],'plausible_codes':sorted(potential),'selected_support':0.,'top_two_margin':None,'low_support':True}
    best=max(positive.values());tied=sorted(key for key,value in positive.items() if best-value<=tie_tolerance)
    best_lower=max(pair[0] for pair in intervals.values())
    nearby=sorted(key for key,pair in intervals.items() if pair[1]>0 and best_lower-pair[1]<=margin)
    nearby=sorted(set(nearby)|set(tied))
    ordered=sorted(scores.values(),reverse=True)
    return {'status':'MODELLED_POTENTIAL','primary_code':tied[0],'tied_codes':tied,'plausible_codes':nearby,
        'selected_support':scores[tied[0]],'top_two_margin':ordered[0]-ordered[1] if len(ordered)>1 else ordered[0],
        'low_support':intervals[tied[0]][0]<threshold,'numerical_support_intervals':intervals,
        'nonzero_numerical_interval':any(pair[0]!=pair[1] for pair in intervals.values()),
        'numerically_distinct_primary':all(intervals[tied[0]][0]>pair[1]+tie_tolerance for code,pair in intervals.items() if code!=tied[0]),
        'primary_meaning':'stable lowest tied code for display, not unique ecological dominance'}


def classify_cell(cell_id,domain,families,pft_results,climate_metrics,pft_guilds,*,controls):
    """JSON-native actual-PFT to retained-legend potential classification.

    Three family IDs are parameter hypotheses within ONE snow/soil/climate
    member, not the three coequal snow members themselves. Family order has no
    privileged member. Unknown is JSON null, never the outside-domain code zero.
    """
    _text(cell_id,'cell identity');_keys(domain,('kind','evidence','source_status'),'domain')
    _text(domain['evidence'],'domain evidence')
    if domain['kind'] not in {'LAND','UNKNOWN'}|NONTERRESTRIAL or domain['source_status'] not in KNOWN|UNRESOLVED:raise ValueError('explicit known/unknown domain required')
    _keys(controls,('low_support_threshold','broad_margin','formation_margin','tie_tolerance'),'classification controls')
    values={key:_fraction(value,key) for key,value in controls.items()}
    if values['tie_tolerance']>min(values['broad_margin'],values['formation_margin']):raise ValueError('tie tolerance cannot exceed plausible margins')
    result={'schema':'diadem.biome-potential-cell.r8','cell_id':cell_id,'domain':domain,'source_status':'WORKING NON-CANON',
        'broad':None,'formation':None,'family_records':[],'uncertainty':[],
        'meaning':'potential natural ecological admissibility/support, not realised cover, NPP or probability',
        'competitive_or_disturbance_resolution':'UNCONSTRAINED: admissibility does not identify unique dominance',
        'actual_vegetation_used_as_forcing':False,'protected_water_modifier_used_as_formation_forcing':False}
    if domain['kind']=='UNKNOWN' or domain['source_status'] in UNRESOLVED:
        result.update(status='UNKNOWN_DOMAIN');return result
    if domain['kind'] in NONTERRESTRIAL:
        result.update(status='NONTERRESTRIAL',broad={'primary_code':0},formation={'primary_code':0});return result
    _sequence(families,'coequal family inventory',3)
    if any(type(item) is not dict for item in families):raise ValueError('typed family records required')
    if len(families)!=3 or len({item.get('family_id') for item in families})!=3:raise ValueError('exactly three uniquely identified coequal families required')
    if type(pft_results) is not dict or set(pft_results)!={item['family_id'] for item in families}:raise ValueError('PFT family identities do not match')
    if type(climate_metrics) is not dict or type(pft_guilds) is not dict:raise ValueError('typed physical metrics and PFT guild metadata required')
    if set(climate_metrics)-set(PHYSICAL_METRIC_UNITS):raise ValueError('unrecognised physical climate metric input')
    for name,record in climate_metrics.items():_metric_record(record,PHYSICAL_METRIC_UNITS[name],name)
    for key,value in pft_guilds.items():
        _text(key,'PFT identity');_keys(value,('guild','evidence'),'PFT guild');_text(value['evidence'],'PFT guild evidence')
        if value['guild'] not in GUILDS:raise ValueError('unknown explicitly supported ecological guild')
    records=sorted((_family(family,pft_results[family['family_id']],climate_metrics,pft_guilds) for family in families),key=lambda row:row['family_id'])
    consensus={code:_combine([row['broad_support'][code] for row in records],'GEOMETRIC') for code in BROAD_NAMES}
    consensus_intervals={code:None if any(row['broad_support_intervals'][code] is None for row in records) else
        [_combine([row['broad_support_intervals'][code][i] for row in records],'GEOMETRIC') for i in (0,1)] for code in BROAD_NAMES}
    broad=_selection(consensus,values['broad_margin'],values['tie_tolerance'],values['low_support_threshold'],consensus_intervals)
    median={code:None if any(row['formations'][code]['support'] is None for row in records) else
        sorted(row['formations'][code]['support'] for row in records)[1] for code in FORMATION_NAMES}
    median_intervals={code:None if any(row['formations'][code]['support_interval'] is None for row in records) else
        [sorted(row['formations'][code]['support_interval'][i] for row in records)[1] for i in (0,1)] for code in FORMATION_NAMES}
    result.update(family_records=records,broad=broad,broad_consensus_support=consensus,formation_median_support=median,
        family_ids=[row['family_id'] for row in records],controls=values,
        broad_hierarchy='R8 maximum compatible formation within each family, then coequal geometric consensus; not historical EP1 numeric replay')
    if broad['primary_code'] is None:
        if broad['status']=='NO_ADMISSIBLE_CANDIDATE' and any(value is not None and value>0 for row in records for value in row['broad_support'].values()):
            broad['status']='NO_COMMON_FAMILY_SUPPORT'
            broad['plausible_codes']=sorted(code for code in BROAD_NAMES if any(row['broad_support'][code] and row['broad_support'][code]>0 for row in records))
            result['uncertainty'].append('FAMILY_STRUCTURAL_CONFLICT')
        result.update(status=broad['status'],formation={'primary_code':None,'status':broad['status'],'plausible_codes':[]});return result
    by_broad={code:_selection({k:median[k] for k in COMPATIBILITY[code]},values['formation_margin'],values['tie_tolerance'],values['low_support_threshold'],
        {k:median_intervals[k] for k in COMPATIBILITY[code]}) for code in broad['plausible_codes']}
    for code,selection in by_broad.items():
        if selection['status']=='NO_ADMISSIBLE_CANDIDATE':
            candidates=sorted(k for k in COMPATIBILITY[code] if any(row['formations'][k]['support']>0 for row in records))
            if candidates:
                selection.update(status='NO_MEDIAN_FORMATION_SUPPORT',plausible_codes=candidates)
                if 'FAMILY_STRUCTURAL_CONFLICT' not in result['uncertainty']:result['uncertainty'].append('FAMILY_STRUCTURAL_CONFLICT')
    formation=by_broad[broad['primary_code']]
    result.update(status='MODELLED_POTENTIAL' if formation['primary_code'] is not None else formation['status'],formation=formation,formations_by_plausible_broad=by_broad,
        all_plausible_formation_codes=sorted({k for selection in by_broad.values() for k in selection['plausible_codes']}))
    family_choices=[]
    for row in records:
        choice=_selection(row['broad_support'],values['broad_margin'],values['tie_tolerance'],values['low_support_threshold'],row['broad_support_intervals'])
        family_choices.append({'family_id':row['family_id'],'broad':choice})
    result['family_diagnostics']=family_choices
    if any(row['broad']['primary_code']!=broad['primary_code'] for row in family_choices):result['uncertainty'].append('FAMILY_DISAGREEMENT')
    if len(broad['tied_codes'])>1 or len(formation['tied_codes'])>1:result['uncertainty'].append('DISPLAY_TIE_WITHIN_DECLARED_TOLERANCE')
    if (broad['nonzero_numerical_interval'] and not broad['numerically_distinct_primary'] or
            formation.get('nonzero_numerical_interval',False) and not formation['numerically_distinct_primary']):result['uncertainty'].append('NUMERICAL_BRACKET_OVERLAP')
    if len(broad['plausible_codes'])>1 or len(formation['plausible_codes'])>1:result['uncertainty'].append('LOW_MARGIN_ALTERNATIVES')
    if broad['low_support'] or formation['low_support']:result['uncertainty'].append('LOW_ABSOLUTE_SUPPORT')
    if any(row['optional_missing_metrics'] for row in records):result['uncertainty'].append('OPTIONAL_PHYSICAL_CONTEXT_UNKNOWN_NEUTRAL')
    if formation['primary_code']==6:result['formation_specific_limit']='Macroforest capacity only; actual Great Forest/relic groves are separate historical overlays.'
    if formation['primary_code']==8:result['formation_specific_limit']='Tree/grass potential overlap; neither realised mosaic nor patch fractions predicted.'
    result['uncertainty'].append('COMPETITION_AND_DISTURBANCE_UNRESOLVED')
    json.dumps(result,allow_nan=False);return result


def transition_diagnostics(cells,edges):
    """Inspect supplied physical neighbour edges; never smooth or alter classes."""
    _sequence(cells,'cell records',10000);_sequence(edges,'declared neighbour edges',40000)
    if any(type(row) is not dict for row in cells):raise ValueError('typed classified cell records required')
    mapping={row.get('cell_id'):row for row in cells}
    if len(mapping)!=len(cells) or None in mapping:raise ValueError('unique classified cell identities required')
    for row in cells:
        if row.get('schema')!='diadem.biome-potential-cell.r8':raise ValueError('actual classified cell schema required')
    seen=set();records=[]
    for edge in edges:
        _keys(edge,('a','b','length_m','evidence'),'neighbour edge');_text(edge['evidence'],'edge geometry evidence')
        a,b=edge['a'],edge['b'];length=_number(edge['length_m'],'edge length')
        if a not in mapping or b not in mapping or a==b or length<=0:raise ValueError('invalid physical adjacency')
        pair=tuple(sorted((a,b)))
        if pair in seen:raise ValueError('duplicate undirected neighbour edge')
        seen.add(pair);left,right=mapping[a],mapping[b]
        status='MODELLED_POTENTIAL'
        boundary=overlap=None
        if left['status']=='NONTERRESTRIAL' or right['status']=='NONTERRESTRIAL':status='NONTERRESTRIAL_DOMAIN_EDGE'
        elif left['status']!='MODELLED_POTENTIAL' or right['status']!='MODELLED_POTENTIAL':status='UNKNOWN_OR_NO_ADMISSIBLE_ENDPOINT'
        else:
            boundary=left['formation']['primary_code']!=right['formation']['primary_code']
            ls=set(left['all_plausible_formation_codes']);rs=set(right['all_plausible_formation_codes'])
            overlap=bool(ls&rs) and (len(ls)>1 or len(rs)>1)
        records.append({**edge,'status':status,'different_primary_formation':boundary,'overlapping_ambiguous_potential':overlap})
    return {'schema':'diadem.biome-neighbour-diagnostics.r8','edges':records,
        'meaning':'declared adjacency diagnostics, no inferred ecotone width/area or categorical smoothing','classes_modified':False}
