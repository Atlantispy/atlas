"""Actual seasonal climate/snow accounting; no annual fields relabelled months."""
from fractions import Fraction as F
import hashlib
import json
import math


def plain(value):
    if isinstance(value,F): return str(value)
    if isinstance(value,dict):
        if any(type(k) is not str for k in value): raise ValueError('string JSON keys required')
        return {k:plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [plain(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(plain(value),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def quantity(value):
    if value is None: return None
    value=F(value); represented=float(value)
    if not math.isfinite(represented) or value and not represented: raise ValueError('unrepresentable seasonal quantity')
    return {'exact':str(value),'value':represented}


def rational(value,*,signed=False):
    if type(value) not in (str,int,float,F) or type(value) is str and len(value)>256: raise ValueError('explicit bounded seasonal number required')
    result=F(value)
    if max(result.numerator.bit_length(),result.denominator.bit_length())>4096 or abs(result)>10**18 or not signed and result<0: raise ValueError('seasonal number outside supported range')
    quantity(result)
    return result


def wind_summary(regimes,cell_id):
    if not regimes or len({r['regime_id'] for r in regimes})!=len(regimes): raise ValueError('unique actual circulation regimes required')
    weights=[rational(r['weight']) for r in regimes]
    if sum(weights,F())!=1 or any(w<=0 for w in weights): raise ValueError('actual circulation weights must sum exactly to one')
    airs=[r['products'][cell_id]['air'] for r in regimes]
    if any(a['source_status']!='WORKING NON-CANON' for a in airs): raise ValueError('actual source-bound representative air required')
    if any(not 0<=rational(a['specific_humidity_kg_kg'])<1 or rational(a['pressure_pa'])<=0 for a in airs): raise ValueError('invalid moist-air humidity/pressure')
    for a in airs:
        scalar=float(rational(a['mean_scalar_speed_10m_m_s']))
        east=float(rational(a['wind_east_10m_m_s'],signed=True));north=float(rational(a['wind_north_10m_m_s'],signed=True))
        resultant=math.hypot(east,north)
        if (scalar==0 and resultant>0) or scalar+16*math.ulp(max(scalar,resultant))<resultant: raise ValueError('child scalar wind speed is below its vector resultant')
    def weighted(field): return sum((w*rational(a[field],signed=True) for w,a in zip(weights,airs)),F())
    east,north=weighted('wind_east_10m_m_s'),weighted('wind_north_10m_m_s')
    speed=math.hypot(float(east),float(north))
    direction=None if east==north==0 else math.degrees(math.atan2(-float(east),-float(north)))%360
    values={k:quantity(weighted(k)) for k in ('temperature_c','specific_humidity_kg_kg','pressure_pa','vapour_pressure_pa','relative_humidity_liquid')}
    values.update(wind_east_10m_m_s=quantity(east),wind_north_10m_m_s=quantity(north),
        mean_scalar_speed_10m_m_s=quantity(weighted('mean_scalar_speed_10m_m_s')),
        resultant_speed_10m_m_s=speed,wind_from_degrees=direction,
        wind_direction_status='UNDEFINED_ZERO_RESULTANT' if direction is None else 'MODELLED_VECTOR_RESULTANT',
        vapour_pressure_deficit_pa=quantity(weighted('saturation_vapour_pressure_pa')-weighted('vapour_pressure_pa')),
        vapour_support=sorted({a['vapour_support'] for a in airs}),wind_support=sorted({a['wind_support'] for a in airs}),
        interpretation='stationary regime-weighted quantities; vector components averaged, not compass angles; not a resolved storm chronology')
    return values


def project(parent,expected_source_sha256):
    if parent['schema']!='diadem.biomes-vegetation-result.r8' or parent['source_sha256']!=expected_source_sha256: raise ValueError('exact actual R8 parent required')
    seasonal=parent['seasonal']; calendar=seasonal['calendar']; day=rational(calendar['day_seconds'])
    soil_sha=digest(parent['soil_result'])
    if (parent['state']['seasonal_sha256']!=digest(seasonal) or parent['state']['soil_result_sha256']!=soil_sha
            or seasonal['soil_result_sha256']!=soil_sha): raise ValueError('actual nested climate/soil source identities differ')
    days=calendar['month_days']
    if not day or len(days)!=12 or any(type(v) is not int or v<=0 for v in days): raise ValueError('explicit complete positive calendar required')
    durations=[day*v for v in days]; year=sum(durations,F()); members={}
    for member_id,member in seasonal['members'].items():
        cells={}
        for ident,cell in member['cells'].items():
            if cell['status']!='MODELLED_PERIODIC_SNOW':
                cells[ident]={'status':'UNKNOWN','months':None,'events':None,'annual':None,'reason':cell.get('reason','seasonal forcing/snow unresolved')}; continue
            monthly=cell['months']; atmosphere=member['atmosphere']
            if [m['month_id'] for m in monthly]!=list(range(1,13)) or [m['month_id'] for m in atmosphere]!=list(range(1,13)): raise ValueError('actual ordered twelve months required')
            months=[]; clock=F(); prior_swe=rational(cell['initial_swe_m'])
            for row,air,dt in zip(monthly,atmosphere,durations):
                if rational(row['duration_seconds'])!=dt: raise ValueError('actual month/calendar duration mismatch')
                ledger=row['snow']['ledger']; expected={k:rational(v,signed=True) for k,v in ledger.items()}
                if expected['initial_swe_m']!=prior_swe or expected['snow_residual_m'] or expected['total_water_residual_m']: raise ValueError('snow continuity/mass ledger mismatch')
                if expected['final_swe_m']!=prior_swe+expected['snowfall_m']-expected['melt_m'] or expected['precipitation_m']!=expected['rain_m']+expected['snowfall_m'] or expected['liquid_to_soil_m']!=expected['rain_m']+expected['melt_m']: raise ValueError('independent snow/rain/melt accounting failed')
                if rational(row['precipitation_m_s'])*dt!=expected['precipitation_m']: raise ValueError('monthly atmosphere/snow precipitation mismatch')
                actual=wind_summary(air['regimes'],ident)
                if float(F(actual['temperature_c']['exact']))!=row['temperature_c']: raise ValueError('monthly temperature/actual atmosphere join differs')
                months.append({'month_id':row['month_id'],'start_seconds':str(clock),'end_seconds':str(clock+dt),'duration_seconds':str(dt),
                    'air':actual,'precipitation_m':quantity(expected['precipitation_m']),
                    'snowfall_swe_m':quantity(expected['snowfall_m']),'rain_m':quantity(expected['rain_m']),
                    'melt_m':quantity(expected['melt_m']),'liquid_to_soil_m':quantity(expected['liquid_to_soil_m']),
                    'initial_swe_m':quantity(prior_swe),'final_swe_m':quantity(expected['final_swe_m']),
                    'reference_potential_evaporation_m':quantity(rational(row['potential_evaporation_m_s'])*dt),
                    'potential_condensation_m':quantity(rational(row['potential_condensation_m_s'])*dt),
                    'snow_source_sha256':digest(row['snow']),'monthly_source_sha256':digest(row),'atmosphere_source_sha256':digest(air),
                    'soil_temperature_c':None,'soil_freeze_fraction':None,'river_flow_m3_s':None,'lake_level_m':None,
                    'unresolved':'soil heat/freezing, routed channel flow and finite waterbody storage need separate models; air temperature/SWE/PET do not supply them'})
                prior_swe=expected['final_swe_m']; clock+=dt
            events=[]; clock=F(); by_month={m:F() for m in range(1,13)}; durations_by_month={m:F() for m in range(1,13)}; ids=set(); previous=1
            for event in cell['events']:
                mid=event['month_id']; dt=rational(event['duration_seconds'])
                if type(mid) is not int or not 1<=mid<=12 or mid<previous or not dt or event['event_id'] in ids: raise ValueError('positive unique chronologically ordered snow-liquid events required')
                ids.add(event['event_id']); previous=mid
                if (event['temperature_c']!=monthly[mid-1]['temperature_c'] or event['potential_evaporation_m_s']!=monthly[mid-1]['potential_evaporation_m_s']): raise ValueError('liquid event temperature/PET differs from its displayed monthly forcing')
                represented=rational(event['liquid_input_m_s'])*dt
                error=rational(event['liquid_conversion_error_m'],signed=True); exact=represented-error
                if exact<0: raise ValueError('negative exact snow-liquid supply')
                by_month[mid]+=exact; durations_by_month[mid]+=dt
                events.append({'event_id':event['event_id'],'month_id':mid,'start_seconds':str(clock),'end_seconds':str(clock+dt),
                    'duration_seconds':str(dt),'represented_liquid_m':quantity(represented),'exact_snow_liquid_m':quantity(exact),
                    'representation_error_m':quantity(error),'source_sha256':digest(event)})
                clock+=dt
            if clock!=year or any(durations_by_month[m['month_id']]!=F(m['duration_seconds']) or by_month[m['month_id']]!=F(m['liquid_to_soil_m']['exact']) for m in months): raise ValueError('event/month liquid or chronology mismatch')
            amounts=('precipitation_m','snowfall_swe_m','rain_m','melt_m','liquid_to_soil_m','reference_potential_evaporation_m','potential_condensation_m')
            annual={key:quantity(sum((F(m[key]['exact']) for m in months),F())) for key in amounts}
            annual['duration_weighted_temperature_c']=quantity(sum((F(m['air']['temperature_c']['exact'])*F(m['duration_seconds']) for m in months),F())/year)
            annual['arithmetic_mean_of_monthly_means_temperature_c']=quantity(sum((F(m['air']['temperature_c']['exact']) for m in months),F())/12)
            annual['duration_seconds']=str(year)
            annual['snow_water_residual_m']=quantity(F(annual['precipitation_m']['exact'])+F(cell['initial_swe_m'])-F(annual['liquid_to_soil_m']['exact'])-prior_swe)
            if F(annual['snow_water_residual_m']['exact']): raise ArithmeticError('annual snow mass conservation')
            selected={}
            for name,month_ids in (('warm',[4,5,6,7,8,9]),('cool',[10,11,12,1,2,3])):
                rows=[m for m in months if m['month_id'] in month_ids]; duration=sum((F(m['duration_seconds']) for m in rows),F())
                selected[name]={'month_ids':month_ids,'duration_seconds':str(duration),
                    'precipitation_m':quantity(sum((F(m['precipitation_m']['exact']) for m in rows),F())),
                    'reference_potential_evaporation_m':quantity(sum((F(m['reference_potential_evaporation_m']['exact']) for m in rows),F())),
                    'duration_weighted_air':{key:quantity(sum((F(m['air'][key]['exact'])*F(m['duration_seconds']) for m in rows),F())/duration) for key in ('temperature_c','specific_humidity_kg_kg','wind_east_10m_m_s','wind_north_10m_m_s','mean_scalar_speed_10m_m_s')},
                    'scope':'calendar-duration-weighted component/scalar summaries; no averaged compass angles'}
            annual['warm_climatic_deficit_month_ids']=[5,6,7,8,9]
            annual['warm_climatic_deficit_m']=quantity(sum((max(F(m['reference_potential_evaporation_m']['exact'])-F(m['precipitation_m']['exact']),F()) for m in months if m['month_id'] in (5,6,7,8,9)),F()))
            wet=[m['month_id'] for m in months if F(m['precipitation_m']['exact'])>=F(m['reference_potential_evaporation_m']['exact'])]
            dry=[m['month_id'] for m in months if F(m['precipitation_m']['exact'])<F(m['reference_potential_evaporation_m']['exact'])/2]
            flags=[i in dry for i in range(1,13)]; longest=run=0
            for flag in flags*2:
                run=min(12,run+1) if flag else 0; longest=max(longest,run)
            cells[ident]={'status':'MODELLED_REPRESENTATIVE_SEASONS','months':months,'events':events,'annual':annual,'seasonal_summaries':selected,
                'monthly_climatic_support':{'wet_month_ids':wet,'strongly_dry_month_ids':dry,'longest_circular_strongly_dry_run_months':longest,
                    'meaning':'monthly climate support from P/PET; not daily drought, soil saturation, hydroperiod or actual plant water stress'},
                'source_cell_sha256':digest(cell),'source_status':'WORKING NON-CANON'}
        members[member_id]={'cells':cells,'formed_terrain_sha256':digest(member['formed_terrain'])}
    return {'schema':'diadem.seasonal-climate-state.r10','source_status':'WORKING NON-CANON','parent_result_sha256':digest(parent),
        'parent_source_sha256':expected_source_sha256,'calendar':calendar,'calendar_sha256':digest(calendar),'members':members,
        'scope':'actual representative seasonal air, precipitation, snow and once-only liquid supply; no inferred daily storms, soil heat, aquifer, routing or adopted world climate'}
