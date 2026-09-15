"""Source-locked dual-mode R8 verification, with an explicit pending release gate.

No predecessor acceptance suite is counted as new R8 testing. Wall times are
execution receipts only, never performance or optimisation comparisons.
"""
import argparse
from fractions import Fraction as F
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
import types
import unittest

HERE=Path(__file__).resolve().parent
TASK=HERE.parents[1]
OUTPUT_ROOT=TASK/'outputs/generator-upgrade-r8'
SUITES=('test_binding','test_biomes','test_vegetation','test_seasonal','test_pipeline','test_verification')
EXPECTED_COUNT=237
INVENTORY_SHA256='8e7af78f8fc4a5fba52e89bf6f0ee6173dcb10f9745bced82d4b7d1cb1cad0c2'
PRODUCT_CONTRACT_READY=True
ENTRY_SOURCE_SHA256=None
R4_SEAL_SHA256='f7382693a5284ebf111dc8a0622e5811440ccc7e2b546047943462b849926996'
RESULT_SCHEMA='diadem.biomes-vegetation-result.r8'
ARTIFACT_NAMES=frozenset(('recipe.json','full-result.json','stop-result.json','restart-result.json',
    'stop-checkpoint.json','full-checkpoint.json','restart-checkpoint.json'))


def sha(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def inventory_digest(ids):
    return sha(json.dumps(ids,separators=(',',':'),ensure_ascii=True).encode())


def utility():
    """Execute the exact preserved capture utility, not a canonical import."""
    seal=TASK/'outputs/generator-upgrade-r4/connected-reference-01/VERIFICATION.json'
    raw=seal.read_bytes()
    if sha(raw)!=R4_SEAL_SHA256: raise ValueError('retained verifier seal changed')
    record=json.loads(raw); path=TASK/'work/generator_upgrade_r4/verify.py'
    raw=path.read_bytes(); digest=record['source_snapshot'][str(path)]
    if sha(raw)!=digest: raise ValueError('retained verification utility changed')
    module=types.ModuleType('_r8_exact_verification_utilities'); module.__file__=str(path)
    exec(compile(raw,str(path),'exec',dont_inherit=True),module.__dict__)
    return module,path,digest


def install():
    if ENTRY_SOURCE_SHA256 is None or any(k.startswith('work.') for k in sys.modules):
        raise ValueError('fresh source-compiled standalone verifier required')
    helper,path,digest=utility(); capture=helper.ExecutionCapture()
    for key,value in ((str(HERE/'verify.py'),ENTRY_SOURCE_SHA256),(str(path),digest)):
        capture.compiled[key]=value; capture.executed[key]=value; helper.READS[key]=value
    sys.addaudithook(capture.observe); sys.meta_path.insert(0,helper.SourceFinder())
    return helper,capture


def source_map(identity,helper):
    r7=identity['retained_source_identity']; r6=r7['retained_source_identity']
    r5=r6['retained_source_identity']
    result=helper.source_map(r5['retained_source_identity'])
    maps=(r5['r5_sources'],r6['r6_sources'],r7['r7_sources'],
        r7['external_test_reference_sources'],identity['r8_sources'],external_sources(identity))
    for mapping in maps:
        for path,digest in mapping.items():
            key=helper.canonical(path)
            if key in result and result[key]!=digest: raise ValueError('conflicting source binding')
            result[key]=digest
    return result


def external_sources(identity):
    """Optional explicit R8 ledger map; pending science cannot receive a seal."""
    rows=identity.get('external_reference_sources',{})
    if type(rows) is not dict: raise ValueError('explicit external reference map required')
    for path,digest in rows.items():
        if (type(path) is not str or not Path(path).is_absolute() or '..' in Path(path).parts
                or type(digest) is not str or not re.fullmatch('[0-9a-f]{64}',digest)):
            raise ValueError('exact external reference path and digest required')
    return dict(rows)


def validate_external_sources(bundle):
    rows=external_sources(bundle.identity)
    for path,digest in rows.items():
        bundle.storage.plain_path(path)
        if sha(Path(path).read_bytes())!=digest: raise ValueError('external source bytes changed')
    return rows


def required_sources():
    names=(*SUITES,'binding','provenance','pipeline','reference','biomes','vegetation','seasonal','verify')
    return [HERE/(name+'.py') for name in names]+[
        TASK/('work/generator_upgrade_'+version+'/'+name+'.py') for version,name in (
        ('r7','binding'),('r7','provenance'),('r7','pipeline'),('r7','formation'),('r7','organic'),('r7','fertility'),('r7','verify'),
        ('r6','binding'),('r6','provenance'),('r6','soil_water'),('r6','hydraulic_jacobian'),
        ('r4','pipeline'),('r4','climate'),('r4','hydromet'),('r3','pipeline'),('r3','soil_inputs'),('r3','terrain_transport'))]


def validate_execution(executed,identity,helper):
    if type(executed) is not dict or not executed: raise ValueError('actual executed source map required')
    expected=source_map(identity,helper); canonical={}
    for path,digest in executed.items():
        key=helper.canonical(path)
        if key in canonical or expected.get(key)!=digest or sha(Path(key).read_bytes())!=digest:
            raise ValueError('executed scientific byte identity differs')
        canonical[key]=digest
    if any(helper.canonical(path) not in canonical for path in required_sources()):
        raise ValueError('required actual source was not executed')


def stable(bundle,helper,capture,*,required=False):
    bundle.verify(); expected=source_map(bundle.identity,helper)
    if bundle.identity['r8_sources'].get(str(HERE/'verify.py'))!=ENTRY_SOURCE_SHA256:
        raise ValueError('entrypoint actual source differs')
    for path,digest in capture.executed.items():
        if expected.get(helper.canonical(path))!=digest or sha(Path(path).read_bytes())!=digest:
            raise ValueError('executed/current source differs from captured identity: '+path)
    if capture.derived_executed: raise ValueError('derived/re-written scientific source not authorised')
    for path,digest in helper.READS.items():
        if capture.executed.get(path)!=digest: raise ValueError('loader/actual execution disagreement')
    validate_external_sources(bundle)
    if required: validate_execution(capture.executed,bundle.identity,helper)


def discover(helper):
    if {p.name for p in HERE.glob('test_*.py')}!={name+'.py' for name in SUITES}:
        raise ValueError('test file inventory differs')
    loader=unittest.TestLoader()
    suite=loader.loadTestsFromNames(['work.generator_upgrade_r8.'+name for name in SUITES])
    if loader.errors: raise ValueError('test discovery failed: '+repr(loader.errors))
    ids=[test.id() for test in helper.flatten(suite)]
    if not ids or len(ids)!=len(set(ids)): raise ValueError('unique nonempty test inventory required')
    return suite,ids


def require_inventory(ids):
    if (type(EXPECTED_COUNT) is not int or EXPECTED_COUNT<=0 or type(INVENTORY_SHA256) is not str
            or not re.fullmatch('[0-9a-f]{64}',INVENTORY_SHA256)):
        raise ValueError('reviewed test inventory pending; no final seal')
    if (type(ids) is not list or any(type(v) is not str or not v for v in ids)
            or len(ids)!=EXPECTED_COUNT or len(set(ids))!=EXPECTED_COUNT or inventory_digest(ids)!=INVENTORY_SHA256):
        raise ValueError('exact reviewed test identities differ')


def require_release_ready(ids):
    require_inventory(ids)
    if PRODUCT_CONTRACT_READY is not True: raise ValueError('scientific product contract pending; no final seal')


def validate_tests(record):
    require_inventory(record['test_ids'])
    if record.get('status')!='PASS' or type(record.get('tests')) is not int or record['tests']!=EXPECTED_COUNT:
        raise ValueError('complete successful test inventory required')
    for name in ('failures','errors','skips','expected_failures','unexpected_successes'):
        if type(record.get(name)) is not int or record[name]!=0: raise ValueError('no omitted/failed tests permitted')
    for name in ('started','stopped','passed'):
        if record.get(name)!=record['test_ids']: raise ValueError('actual executed test identity inventory differs')
    if record.get('inventory_sha256')!=inventory_digest(record['test_ids']): raise ValueError('test inventory hash differs')


def run_suite(suite,ids,helper):
    stream=io.StringIO(); start=time.perf_counter()
    result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=helper.Result).run(suite)
    duration=time.perf_counter()-start
    return {'status':'PASS' if result.wasSuccessful() else 'FAIL','tests':result.testsRun,'test_ids':ids,
        'inventory_sha256':inventory_digest(ids),'started':result.started,'stopped':result.stopped,'passed':result.passed,
        'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
        'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses),
        'test_duration_seconds':duration,'test_log':stream.getvalue()}


def validate_envelope(result,recipe,bundle,*,complete):
    """Identity/cursor guard, deliberately not a scientific product certificate."""
    s=bundle.storage
    if (result.get('schema')!=RESULT_SCHEMA or result.get('source_sha256')!=bundle.source_sha256
            or result.get('recipe_sha256')!=sha(s.encoded(recipe))):
        raise ValueError('actual recipe/source-bound R8 result required')
    state=result['state']; soil=result['soil_result']; seasonal=result['seasonal']
    if set(state)!={'completed_cells','soil_result_sha256','seasonal_sha256','members'}:
        raise ValueError('exact cell-boundary state required')
    if (soil.get('source_sha256')!=bundle.parent.source_sha256
            or soil.get('schema')!='diadem.soil-formation-result.r7'
            or state['soil_result_sha256']!=sha(s.encoded(soil))
            or state['seasonal_sha256']!=sha(s.encoded(seasonal))):
        raise ValueError('actual soil/seasonal parent binding differs')
    if (type(state['members']) is not dict or set(state['members'])!=set(soil['state']['members'])
            or any(type(cells) is not dict for cells in state['members'].values())):
        raise ValueError('complete coequal scenario inventory required, including empty partial members')
    expected={(scenario,cell) for scenario,cells in soil['state']['members'].items() for cell in cells}
    actual={(scenario,cell) for scenario,cells in state['members'].items() for cell in cells}
    cursor=state['completed_cells']
    if (not expected or type(cursor) is not int or cursor!=len(actual) or not actual<=expected
            or (complete and actual!=expected) or (not complete and cursor!=1)):
        raise ValueError('actual complete/partial cell cursor differs')
    return len(expected)


def close(actual,expected,name,*,atol=1e-12,rtol=1e-12):
    if (type(actual) not in (int,float,F) or type(expected) not in (int,float,F)
            or not math.isfinite(actual) or not math.isfinite(expected)
            or abs(actual-expected)>atol+rtol*max(abs(actual),abs(expected))):
        raise ValueError(name+' differs from actual physical support')


def validate_capacity(capacity,cell,spec,support):
    """Independent layer/retention accounting, not a new texture-to-K model."""
    if capacity['status']!='MODELLED':
        if capacity['status']!='UNKNOWN' or capacity['capacity_m'] is not None or capacity['rooted_depth_m'] is not None:
            raise ValueError('unknown hydraulic support cannot become known capacity')
        return False
    water=cell['formed_soil_water']; geometry=cell['geometry']; laws=water['column']['layers']
    if (capacity['support_id']!=support or capacity['geometry_sha256']!=sha(encoded(geometry))
            or capacity['hydraulic_material_sha256']!=sha(encoded(water['column']))
            or capacity['rooting_hypothesis']!=spec or water['geometry_sha256']!=sha(encoded(geometry))
            or [x['layer_id'] for x in geometry]!=[x['layer_id'] for x in laws]):
        raise ValueError('actual rooting geometry/hydraulic material binding differs')
    remaining=F(spec['maximum_root_depth_m']); expected=[]
    for g,law in zip(geometry,laws):
        if not remaining or g['phase'] not in spec['allowed_phases']: break
        depth=min(remaining,F(g['thickness_m'])); expected.append((g,law,depth)); remaining-=depth
    if len(capacity['layers'])!=len(expected): raise ValueError('rooting layer inventory differs')
    total=F(); rooted=F()
    for row,(g,law,depth) in zip(capacity['layers'],expected):
        if (row['layer_id']!=g['layer_id'] or F(row['rooted_thickness_m'])!=depth
                or law['thickness_m']!=float(F(g['thickness_m'])) or law['theta_s']!=float(F(g['porosity']))):
            raise ValueError('actual rooted layer/porosity differs')
        for label,head in (('theta_upper',spec['upper_head_m']),('theta_lower',spec['lower_head_m'])):
            m=1-1/law['n']; theta=law['theta_r']+(law['theta_s']-law['theta_r'])*(1+(law['alpha_per_m']*abs(head))**law['n'])**(-m)
            close(row[label],theta,'independent retention endpoint',atol=2e-14)
        contribution=(F(row['theta_upper'])-F(row['theta_lower']))*depth
        if contribution<0 or F(row['available_water_m'])!=contribution: raise ValueError('layer available-water ledger differs')
        total+=contribution; rooted+=depth
    if (F(capacity['capacity_exact_m'])!=total or F(capacity['rooted_depth_exact_m'])!=rooted
            or capacity['capacity_m']!=float(total) or capacity['rooted_depth_m']!=float(rooted)):
        raise ValueError('whole-profile available-water/accessible-depth ledger differs')
    return True


def validate_snow(cycle,calendar,member,cell,binding_sha,*,atol):
    """Exact SWE, month chronology and liquid conversion; UNKNOWN stays null."""
    if cycle['status']!='MODELLED_PERIODIC_SNOW':
        if cycle['status']!='UNKNOWN' or cycle.get('events') is not None:
            raise ValueError('unresolved seasonal snow cannot supply fabricated events')
        return None
    months=cycle['months']; events=cycle['events']; day=F(calendar['day_seconds'])
    if [x['month_id'] for x in months]!=list(range(1,13)) or len({e['event_id'] for e in events})!=len(events):
        raise ValueError('complete unique chronological seasonal forcing required')
    if [e['month_id'] for e in events]!=sorted(e['month_id'] for e in events): raise ValueError('seasonal events reordered')
    initial=F(cycle['initial_swe_m']); stock=initial; time_cursor=F(); precipitation=F(); liquid=F(); chain=None
    for number,month in enumerate(months,1):
        dt=F(calendar['month_days'][number-1])*day
        snow=month['snow']; ledger=snow['ledger']; forcing=snow['forcing']; state=snow['state']
        if F(month['duration_seconds'])!=dt or snow['status']!='MODELLED': raise ValueError('actual complete snow month required')
        if (F(ledger['initial_swe_m'])!=stock or F(forcing['start_seconds'])!=time_cursor
                or F(forcing['duration_seconds'])!=dt or forcing['binding_sha256']!=binding_sha
                or state['binding_sha256']!=binding_sha or state['scenario_id']!=member or state['cell_id']!=cell
                or state['chain_sha256']!=sha(encoded(forcing))
                or forcing['input_sha256']!=sha(encoded({k:v for k,v in month.items() if k!='snow'}))
                or snow['scenario']!=cycle['scenario'] or forcing['scenario']!=cycle['scenario']
                or (chain is not None and forcing['prior']!=chain)):
            raise ValueError('actual snow state/source/time chain differs')
        p=F(month['precipitation_m_s'])*dt; sf=F(month['snowfall_m_s'])*dt
        scenario=cycle['scenario']; temperature=month['temperature_c']; sigma=scenario['temperature_sigma_c']
        z=temperature/sigma if sigma else 0.
        positive=max(temperature,0.) if not sigma else temperature*.5*(1+math.erf(z/math.sqrt(2)))+sigma*math.exp(-z*z/2)/math.sqrt(2*math.pi)
        close(float(F(ledger['potential_melt_m'])),scenario['degree_day_factor_mm_c_day']*positive/1000*float(dt/day),
            'independent Gaussian positive-temperature melt capacity')
        melt=min(stock+sf,F(ledger['potential_melt_m'])); final=stock+sf-melt
        if (F(ledger['precipitation_m'])!=p or F(ledger['snowfall_m'])!=sf or F(ledger['rain_m'])!=p-sf
                or F(ledger['melt_m'])!=melt or F(ledger['final_swe_m'])!=final
                or F(ledger['liquid_to_soil_m'])!=p-sf+melt or F(ledger['snow_residual_m'])!=0
                or F(ledger['total_water_residual_m'])!=0 or F(state['swe_m'])!=final):
            raise ValueError('actual rain/snow/melt physical ledger differs')
        selected=[e for e in events if e['month_id']==number]
        if not selected or sum((F(e['duration_seconds']) for e in selected),F())!=dt:
            raise ValueError('melt event durations do not cover exact month')
        converted=sum((F(e['liquid_input_m_s'])*F(e['duration_seconds'])-F(e['liquid_conversion_error_m']) for e in selected),F())
        if converted!=F(ledger['liquid_to_soil_m']): raise ValueError('snow liquid counted twice or dropped at PFT boundary')
        for event in selected:
            if (F(event['duration_seconds'])<=0 or event['temperature_c']!=month['temperature_c']
                    or event['potential_evaporation_m_s']!=month['potential_evaporation_m_s']):
                raise ValueError('actual seasonal event thermal/demand support differs')
        stock=final; time_cursor+=dt; precipitation+=p; liquid+=F(ledger['liquid_to_soil_m']); chain=state['chain_sha256']
        if F(state['elapsed_seconds'])!=time_cursor: raise ValueError('snow elapsed month cursor differs')
    if (stock!=F(cycle['final_swe_m']) or initial+precipitation-stock-liquid!=0
            or F(cycle['annual_water_residual_m'])!=0 or time_cursor!=365*day
            or abs(float(stock-initial))>atol or not 0<=cycle['periodic_error_m']<=atol):
        raise ValueError('annual snow time/water/periodic closure differs')
    return {'precipitation_m':str(precipitation),'liquid_m':str(liquid),'duration_seconds':str(time_cursor),
        'initial_swe_m':str(initial),'final_swe_m':str(stock),'water_residual_m':'0'}


def validate_pft_water(result,capacity,cycle,spec,multiplier,calendar,support,family):
    inputs=result['inputs']; link=result['source_binding']; water=result['water']
    if (link['soil_support_id']!=support or link['capacity_sha256']!=sha(encoded(capacity))
            or link['seasonal_cycle_sha256']!=sha(encoded(cycle)) or link['family_id']!=family
            or inputs['capacity']['capacity_m']!=capacity['capacity_m'] or inputs['capacity']['support_id']!=support
            or inputs['capacity']['rooted_depth_m']!=capacity['rooted_depth_m'] or result['pft_id']!=spec['constraints']['pft_id']
            or inputs['constraints']!=spec['constraints']):
        raise ValueError('PFT physical/trait/source binding differs')
    expected_calendar=[str(F(day)*F(calendar['day_seconds'])) for day in calendar['month_days']]
    if (inputs['calendar']['calendar_id']!=calendar['calendar_id'] or inputs['calendar']['month_durations_seconds']!=expected_calendar
            or F(inputs['calendar']['day_seconds'])!=F(calendar['day_seconds'])):
        raise ValueError('PFT supplied physical calendar differs')
    if water['status']!='MODELLED_PERIODIC_BRACKET': raise ValueError('complete reference requires actual periodic PFT water')
    events=inputs['events']; source=cycle['events']
    if len(events)!=len(source): raise ValueError('actual snow/PFT event inventory differs')
    for event,original in zip(events,source):
        active=original['temperature_c']>spec['active_above_temperature_c']
        demand=original['potential_evaporation_m_s']*spec['reference_transpiration_fraction']*multiplier if active else 0.
        for key in ('event_id','month_id','duration_seconds','temperature_c','liquid_input_m_s'):
            if event[key]!=original[key]: raise ValueError('PFT did not consume actual melt event '+key)
        if event['active'] is not active or event['potential_transpiration_m_s']!=demand:
            raise ValueError('PFT demand/phenology hypothesis differs')
    c=capacity['capacity_m']; n=water['numerics']; results={}
    if water['capacity_m']!=c: raise ValueError('periodic reservoir capacity differs')
    for bracket in ('lower','upper'):
        row=water[bracket]; steps=row['events']; stock=row['initial_m']; initial=stock
        if len(steps)!=len(events): raise ValueError('PFT actual water event inventory differs')
        residual=F(); incoming=F(); actual=F(); overflow=F(); duration=F(); conversion=F(); active_actual=[]; active_demand=[]
        for event,step in zip(events,steps):
            dt=float(F(event['duration_seconds'])); i=event['liquid_input_m_s']; d=event['potential_transpiration_m_s']
            if (step['initial_m']!=stock or step['duration_seconds']!=dt or step['supplied_duration_seconds']!=event['duration_seconds']
                    or step['liquid_input_m_s']!=i or step['potential_transpiration_m_s']!=d
                    or step['capacity_m']!=c or step['event_id']!=event['event_id'] or step['month_id']!=event['month_id']
                    or step['active'] is not event['active']): raise ValueError('periodic water step/source continuity differs')
            transfer=F(i)*F(dt); r=F(stock)+transfer-F(step['final_m'])-F(step['actual_transpiration_m'])-F(step['overflow_m'])
            tol=n['flux_atol_m']+n['relative_tolerance']*max(c,i*dt,d*dt,stock)
            if (F(step['numerical_residual_m'])!=r or abs(float(r))>tol or not 0<=step['final_m']<=c
                    or step['actual_transpiration_m']<0 or step['actual_transpiration_m']>d*dt+tol or step['overflow_m']<0
                    or step['input_m']!=i*dt or step['potential_transpiration_m']!=d*dt):
                raise ValueError('independent PFT water stock/input/ET/surplus ledger differs')
            if event['active']: active_actual.append(step['actual_transpiration_m']); active_demand.append(d*dt)
            dc=F(dt)-F(event['duration_seconds'])
            if F(step['duration_conversion_residual_s'])!=dc: raise ValueError('PFT duration representation ledger differs')
            stock=step['final_m']; residual+=r; incoming+=transfer; actual+=F(step['actual_transpiration_m'])
            overflow+=F(step['overflow_m']); duration+=F(event['duration_seconds']); conversion+=dc
        if (stock!=row['final_m'] or F(row['numerical_residual_m'])!=residual or F(row['duration_conversion_residual_s'])!=conversion
                or duration!=365*F(calendar['day_seconds']) or F(initial)+incoming-F(stock)-actual-overflow!=residual):
            raise ValueError('annual PFT water/time closure differs')
        for key,values in (('active_actual_transpiration_m',active_actual),('active_potential_transpiration_m',active_demand),
                ('input_m',[step['input_m'] for step in steps]),('overflow_m',[step['overflow_m'] for step in steps]),
                ('all_actual_transpiration_m',[step['actual_transpiration_m'] for step in steps])):
            if row[key]!=math.fsum(values): raise ValueError('reported PFT integrated quantity differs')
        if active_demand and math.fsum(active_demand)>0:
            close(row['active_actual_to_potential_transpiration_ratio'],math.fsum(active_actual)/math.fsum(active_demand),'actual/demand ratio')
        liquid=sum((F(m['snow']['ledger']['liquid_to_soil_m']) for m in cycle['months']),F())
        liquid_error=incoming-liquid
        if abs(float(liquid_error))>1e-12+1e-9*abs(float(liquid)): raise ValueError('melt/available-water interface conversion exceeds bound')
        results[bracket]={'water_residual_m':str(residual),'snow_liquid_conversion_m':str(liquid_error),
            'combined_snow_pft_residual_m':str(residual-liquid_error),'actual_transpiration_m':float(actual),
            'unpartitioned_surplus_m':float(overflow),'active_actual_demand_ratio':row['active_actual_to_potential_transpiration_ratio']}
    if water['upper']['initial_m']-water['lower']['initial_m']>n['storage_atol_m']+n['relative_tolerance']*c:
        raise ValueError('periodic initial-water bracket unresolved')
    for key in ('active_actual_to_potential_transpiration_ratio','dry_active_duration_s','longest_dry_active_spell_s'):
        low,high=water['lower'][key],water['upper'][key]
        if low is not None and high is not None:
            if result['metric_intervals'][key]!=[min(low,high),max(low,high)] or result['metrics'][key]!=low+(high-low)/2:
                raise ValueError('PFT metric substituted for actual numerical bracket')
    return results


def validate_classification(row,recipe,biome_module):
    classification=row['classification']; records=classification['family_records']
    expected={r['family_id'] for r in recipe['families']}
    if (classification['status']!='MODELLED_POTENTIAL' or classification['cell_id']!=row['cell_id']
            or {r['family_id'] for r in records}!=expected or len(records)!=3
            or classification['actual_vegetation_used_as_forcing'] is not False
            or classification['protected_water_modifier_used_as_formation_forcing'] is not False):
        raise ValueError('complete coequal unforced reference classification required')
    for family in records:
        declared=next(item for item in recipe['families'] if item['family_id']==family['family_id'])
        actual_pfts=row['pft_results'][family['family_id']]
        if set(family['pfts'])!=set(actual_pfts): raise ValueError('classifier omitted actual PFT experiment')
        for ident,record in family['pfts'].items():
            actual=actual_pfts[ident]; rule=declared['pft_score_rules'][ident]
            if actual['status']=='FAIL':
                if record['status']!='INADMISSIBLE' or record['score']!=0: raise ValueError('failed ecological PFT promoted to support')
            elif actual['status']=='PASS':
                value=actual['metrics'][rule['metric']]
                if (record['status']!='ADMISSIBLE' or record['actual_value']!=value or record['rule']!=rule
                        or record['metric_interval']!=actual['metric_intervals'][rule['metric']]):
                    raise ValueError('classifier support is not bound to actual PFT metric')
                close(record['score'],independent_response(value,rule['points']),'declared PFT support response')
            elif record['status']!='UNKNOWN': raise ValueError('unknown PFT promoted to known support')
        for formation in family['formations'].values():
            scores=[]
            for factor in formation['factors']:
                if factor['kind']=='INDEPENDENT_PHYSICAL_RESPONSE':
                    value=row['climate_metrics'][factor['metric']]['value']
                    if factor['actual_value']!=value: raise ValueError('formation response detached from actual physical climate')
                    score=independent_response(value,factor['rule']['points'],factor['rule']['outside'])
                else:
                    values=[family['pfts'][key]['score'] for key in factor['pft_ids']]
                    score=(max if factor['operator']=='ANY' else min)(values)
                close(factor['score'],score,'formation constituent support'); scores.append(score)
            support=min(scores) if formation['operator']=='MINIMUM' else math.prod(scores)**(1/len(scores))
            close(formation['support'],support,'independent formation factor aggregation')
        for code,compatible in biome_module.COMPATIBILITY.items():
            actual=family['broad_support'][str(code)]
            expected_support=max(family['formations'][str(k)]['support'] for k in compatible)
            close(actual,expected_support,'within-family compatible formation hierarchy')
    for code in biome_module.BROAD_NAMES:
        supports=[family['broad_support'][str(code)] for family in records]
        consensus=math.prod(supports)**(1/3)
        close(classification['broad_consensus_support'][str(code)],consensus,'independent geometric family consensus')
    for code in biome_module.FORMATION_NAMES:
        median=sorted(family['formations'][str(code)]['support'] for family in records)[1]
        if classification['formation_median_support'][str(code)]!=median: raise ValueError('independent family median differs')
    broad=classification['broad']; formation=classification['formation']
    if (formation['primary_code'] not in biome_module.COMPATIBILITY[broad['primary_code']]
            or formation['primary_code'] not in formation['plausible_codes']
            or broad['primary_code'] not in broad['plausible_codes']
            or 'COMPETITION_AND_DISTURBANCE_UNRESOLVED' not in classification['uncertainty']):
        raise ValueError('formation compatibility or uncertainty semantics differ')
    return {'broad_code':broad['primary_code'],'formation_code':formation['primary_code'],
        'uncertainty':classification['uncertainty'],'plausible_formations':classification['all_plausible_formation_codes']}


def independent_response(value,points,outside='HOLD'):
    if value<points[0][0]: return points[0][1] if outside=='HOLD' else 0.
    if value>points[-1][0]: return points[-1][1] if outside=='HOLD' else 0.
    for (lo,a),(hi,b) in zip(points,points[1:]):
        if lo<=value<=hi: return a+(b-a)*(value-lo)/(hi-lo)
    raise ValueError('response outside explicit points')


def validate_products(full,bundle,recipe=None):
    if PRODUCT_CONTRACT_READY is not True:
        raise ValueError('scientific product contract pending; no final seal')
    recipe=bundle.reference.recipe(bundle) if recipe is None else recipe
    validate_envelope(full,recipe,bundle,complete=True)
    for key in ('actual_vegetation_used_as_classifier_input','production_installed','canon_changed','optimisation_performed'):
        if full[key] is not False: raise ValueError('bounded potential-reference status must be explicit')
    if full['actual_vegetation_overlays']!=recipe['actual_vegetation_overlays']: raise ValueError('separate overlays differ')
    soil=full['soil_result']; seasonal=full['seasonal']; config=recipe['seasonal']; s=bundle.storage
    preserved=bundle.parent.graph.load('work.generator_upgrade_r7.verify').validate_products(soil,bundle.parent)
    ids={r.scenario_id for r in bundle.parent.parent.pipeline.hm.snow_scenarios()}
    if (set(full['state']['members'])!=ids or set(seasonal['members'])!=ids or set(full['map_products'])!=ids
            or seasonal['schema']!='diadem.seasonal-vegetation-forcing.r8' or seasonal['status']!='DECLARED_REPRESENTATIVE_YEAR'
            or seasonal['soil_result_sha256']!=sha(encoded(soil)) or seasonal['configuration_sha256']!=sha(encoded(config))
            or seasonal['binding_sha256']!=sha(encoded({'soil_result_sha256':sha(encoded(soil)),'configuration':config}))
            or seasonal['calendar']!=config['calendar']): raise ValueError('actual seasonal/soil/configuration binding differs')
    biome=bundle.pipeline.biomes
    expected_legend=bundle.pipeline.seasonal.plain({'broad':biome.BROAD_NAMES,'formation':biome.FORMATION_NAMES,'compatibility':biome.COMPATIBILITY})
    if full['legend']!=expected_legend: raise ValueError('retained compatible legend differs')
    report={}; cell_count=pft_count=climate_calls=0
    for member,cells in full['state']['members'].items():
        source=seasonal['members'][member]; terrain=source['formed_terrain']; atmosphere=source['atmosphere']
        if {r['cell_id'] for r in terrain}!=set(cells) or [m['month_id'] for m in atmosphere]!=list(range(1,13)):
            raise ValueError('new twelve-month atmosphere/current-terrain inventory differs')
        for item in terrain:
            cell=soil['state']['members'][member][item['cell_id']]
            height=F(cell['formation_state']['base_elevation_m'])+sum((F(g['thickness_m']) for g in cell['geometry']),F())
            if item['elevation_m']!=float(height): raise ValueError('new seasonal producer used stale preformation elevation')
        for actual,declared in zip(atmosphere,config['months']):
            if [r['regime_id'] for r in actual['regimes']]!=[r['regime_id'] for r in declared['regimes']]:
                raise ValueError('monthly circulation mixture differs')
            for regime,spec in zip(actual['regimes'],declared['regimes']):
                climate_calls+=1; receipt=regime['generated']['receipt']
                if (regime['weight']!=spec['weight'] or receipt['status']!='BOUNDED_MECHANISTIC_REFERENCE'
                        or receipt['old_climate_parent_reused'] is not False or receipt['production_authorised'] is not False
                        or F(receipt['water_mass_residual_kg_s'])!=0
                        or F(receipt['inlet_water_kg_s'])-F(receipt['outlet_vapour_kg_s'])-F(receipt['outlet_cloud_kg_s'])-F(receipt['precipitation_kg_s'])!=0
                        or F(receipt['delivered_precipitation_kg_s'])-F(receipt['precipitation_kg_s'])!=F(receipt['precipitation_flux_conversion_error_kg_s'])):
                    raise ValueError('actual new climate atmospheric water ledger differs')
                terrain_by_id={r['cell_id']:r for r in terrain}
                for physical in receipt['cells']:
                    if (physical['elevation_m']!=terrain_by_id[physical['cell_id']]['elevation_m']
                            or F(physical['water_mass_residual_kg_s'])!=0):
                        raise ValueError('climate transfer does not refer to actual formed terrain')
                if set(regime['products'])!=set(cells) or set(regime['generated']['cells'])!=set(cells):
                    raise ValueError('actual air/phase/demand cell inventory differs')
                for cell_id,product in regime['products'].items():
                    demand=product['demand']; phase=product['phase']
                    if (product['air']!=regime['generated']['cells'][cell_id]
                            or demand['surface']!=spec['surfaces'][cell_id] or demand['constants']!=config['demand_constants']
                            or any(value!=product['air'][key] for key,value in demand['atmospheric_inputs'].items())
                            or F(phase['precipitation_m_s'])!=F(product['air']['precipitation_m_s'])):
                        raise ValueError('actual atmosphere did not supply phase/potential demand')
                    if demand['actual_et_m_s'] is not None or demand['actual_condensation_m_s'] is not None or demand['status']!='MODELLED':
                        raise ValueError('potential demand was relabelled realised water use')
                    if F(phase['rain_m_s'])+F(phase['snowfall_m_s'])!=F(phase['precipitation_m_s']): raise ValueError('actual phase partition mass differs')
        report[member]={}
        for cell_id,row in cells.items():
            cell_count+=1; cell=soil['state']['members'][member][cell_id]; cycle=source['cells'][cell_id]
            support=sha(encoded({'soil_cell':cell,'member':member,'cell_id':cell_id}))
            if row['soil_support_id']!=support or row['cell_id']!=cell_id: raise ValueError('actual formed soil support ID differs')
            snow=validate_snow(cycle,config['calendar'],member,cell_id,seasonal['binding_sha256'],atol=config['snow_atol_m'])
            if snow is None: raise ValueError('complete reference requires modelled seasonal snow, not fabricated UNKNOWN')
            expected_scenario=next(x for x in bundle.parent.parent.pipeline.hm.snow_scenarios() if x.scenario_id==member)
            if cycle['scenario']!=bundle.pipeline.seasonal.plain(expected_scenario): raise ValueError('coequal snow physical scenario changed')
            for actual,month in zip(atmosphere,cycle['months']):
                for section,field in (('air','temperature_c'),('air','precipitation_m_s'),('phase','snowfall_m_s'),('demand','potential_evaporation_m_s')):
                    value=sum((F(r['weight'])*F(r['products'][cell_id][section][field]) for r in actual['regimes']),F())
                    if F(month[field])!=value and month[field]!=float(value): raise ValueError('monthly aggregation not from actual atmospheric products')
            if set(row['capacities'])!=set(recipe['pfts']) or set(row['pft_results'])!={r['family_id'] for r in recipe['families']}:
                raise ValueError('complete PFT/counterfactual family inventory required')
            summaries={}
            for ident,spec in recipe['pfts'].items():
                if not validate_capacity(row['capacities'][ident],cell,spec['rooting'],support):
                    raise ValueError('complete reference requires modelled formed-soil rooting capacity')
            for family,results in row['pft_results'].items():
                if set(results)!=set(recipe['pfts']): raise ValueError('PFT family omitted a required experiment')
                summaries[family]={}
                for ident,result in results.items():
                    pft_count+=1
                    if result['status'] not in ('PASS','FAIL','UNKNOWN'): raise ValueError('scientific PFT numerical failure')
                    summaries[family][ident]=validate_pft_water(result,row['capacities'][ident],cycle,recipe['pfts'][ident],
                        recipe['family_demand_multipliers'][family],config['calendar'],support,family)
            classified=validate_classification(row,recipe,biome)
            report[member][cell_id]={'soil_support_id':support,'snow':snow,'classification':classified,
                'capacity_m':{k:v['capacity_m'] for k,v in row['capacities'].items()},'pft_water':summaries}
        areas={}
        for cell_id,row in cells.items():
            area=F(soil['actual_exposure']['members'][member][cell_id]['area_m2'])
            if F(row['area_m2'])!=area: raise ValueError('source physical cell area differs')
            key=str(row['classification']['formation']['primary_code']); areas[key]=areas.get(key,F())+area
        maprow=full['map_products'][member]
        if ({k:F(v) for k,v in maprow['class_area_m2'].items()}!=areas or F(maprow['represented_area_m2'])!=sum(areas.values(),F())
                or maprow['coverage']!='ALL_SUPPLIED_CELLS' or maprow['transitions']['classes_modified'] is not False):
            raise ValueError('actual classified-area/transition accounting differs')
    if cell_count!=6 or pft_count!=108: raise ValueError('bounded acceptance fixture requires six cells and 108 PFT experiments')
    return {'scope':'actual source-bound reference only; UNKNOWN remains supported outside complete acceptance fixture',
        'cell_count':cell_count,'pft_experiment_count':pft_count,'actual_climate_calls':climate_calls,
        'retained_soil_scalar_audit':preserved,'members':report,
        'physical_ledgers':'ACTUAL_ATMOSPHERE_SNOW_AVAILABLE_WATER_AND_AREA_CHECKED',
        'nonclaims':['realised vegetation','NPP','nutrient sufficiency','species occurrence','world production','optimisation']}


def artifacts(bundle,root):
    root.mkdir(exist_ok=False); s=bundle.storage
    s.write_json(root/'recipe.json',bundle.reference.recipe(bundle)); recipe=s.read_json(root/'recipe.json')
    full=bundle.run(recipe); stop=bundle.run(recipe,stop_after=1)
    s.write_json(root/'stop-checkpoint.json',bundle.checkpoint(stop))
    restart=bundle.run(recipe,resume=s.read_json(root/'stop-checkpoint.json'))
    for name,value in (('full-result.json',full),('stop-result.json',stop),('restart-result.json',restart),
            ('full-checkpoint.json',bundle.checkpoint(full)),('restart-checkpoint.json',bundle.checkpoint(restart))):
        s.write_json(root/name,value)
    record={'path':str(root),'files':{p.name:sha(p.read_bytes()) for p in sorted(root.iterdir())},
        'reference_sha256':sha(s.encoded(full)),
        'entrypoint':'actual public binding.Bundle.run/checkpoint; exclusive saved JSON and restart readback',
        'scientific_checks':validate_products(full,bundle,recipe)}
    validate_artifacts(record,bundle)
    return record


def validate_artifacts(record,bundle):
    s=bundle.storage; root=s.plain_path(record['path'])
    if set(record['files'])!=ARTIFACT_NAMES or {p.name for p in root.iterdir()}!=ARTIFACT_NAMES:
        raise ValueError('artifact inventory differs')
    values={}
    for name,digest in record['files'].items():
        values[name]=s.read_json(root/name)
        if sha((root/name).read_bytes())!=digest: raise ValueError('artifact readback hash differs')
    full=values['full-result.json']; recipe=values['recipe.json']
    if full!=values['restart-result.json'] or values['full-checkpoint.json']!=values['restart-checkpoint.json']:
        raise ValueError('actual full/restart state differs')
    validate_envelope(full,recipe,bundle,complete=True)
    validate_envelope(values['stop-result.json'],recipe,bundle,complete=False)
    if record['reference_sha256']!=sha(s.encoded(full)): raise ValueError('actual reference digest differs')
    for stage in ('full','stop','restart'):
        if values[stage+'-checkpoint.json']!=bundle.checkpoint(values[stage+'-result.json']):
            raise ValueError('saved checkpoint identity differs')
    if record.get('scientific_checks')!=validate_products(full,bundle,recipe): raise ValueError('scientific readback differs')
    return full


def private_executions(bundle):
    records={}; current=bundle
    for label in ('r8','r7','r6'):
        records[label]=dict(current.graph.executed)
        if label!='r6': current=current.parent
    return records


def validate_private_executions(records,executed,bundle,helper):
    if type(records) is not dict or set(records)!={'r8','r7','r6'}:
        raise ValueError('complete actual private graph chain required')
    expected=source_map(bundle.identity,helper)
    observed={helper.canonical(k):v for k,v in executed.items()}
    graphs={'r8':bundle.graph,'r7':bundle.parent.graph,'r6':bundle.parent.parent.graph}
    for label,rows in records.items():
        if type(rows) is not dict or not rows: raise ValueError('actual private dependency execution required')
        for logical,row in rows.items():
            if type(logical) is not str or not logical.startswith('work.') or set(row)!={'path','sha256'}:
                raise ValueError('explicit private logical/source binding required')
            key=helper.canonical(row['path'])
            node=graphs[label].nodes.get(logical)
            if (node is None or helper.canonical(node[0])!=key or node[1]!=row['sha256']
                    or expected.get(key)!=row['sha256'] or observed.get(key)!=row['sha256']):
                raise ValueError('private/actual execution binding differs')


def validate_worker_header(record,bundle,mode):
    if (type(mode) is not int or mode not in (0,2) or type(record.get('optimisation_flag')) is not int
            or record['optimisation_flag']!=mode or record.get('status')!='PASS'
            or record.get('source_identity')!=bundle.identity or record.get('source_sha256')!=bundle.source_sha256):
        raise ValueError('actual worker identity/status/flags differ')


def worker(path,parent_path,mode):
    start=time.perf_counter(); helper,capture=install()
    from work.generator_upgrade_r8 import binding
    bundle=binding.load(); parent=bundle.storage.read_json(parent_path)
    if (type(mode) is not int or mode not in (0,2) or sys.flags.optimize!=mode
            or parent['source_identity']!=bundle.identity or parent['source_sha256']!=bundle.source_sha256):
        raise ValueError('worker actual flags/source differ')
    suite,ids=discover(helper); require_release_ready(ids)
    external=validate_external_sources(bundle)
    if external!=parent['external_reference_sources']: raise ValueError('parent/worker external binding differs')
    tests=run_suite(suite,ids,helper)
    record={'status':'FAIL','optimisation_flag':sys.flags.optimize,'source_identity':bundle.identity,
        'source_sha256':bundle.source_sha256,'tests':tests,'external_reference_sources':external}
    try:
        validate_tests(tests)
        record['artifacts']=artifacts(bundle,path.parent/(path.stem+'-reference'))
        stable(bundle,helper,capture,required=True)
        records=private_executions(bundle)
        validate_private_executions(records,capture.executed,bundle,helper)
        record.update(status='PASS',private_dependency_executions=records)
    except Exception as error:
        record['failure']=str(error)
    record.update(executed_source_hashes=dict(capture.executed),worker_duration_seconds=time.perf_counter()-start,
        scope='bounded actual soil/seasonal/biome/vegetation scientific-source/restart verification; no optimisation')
    bundle.storage.write_json(path,record); capture.active=False
    print(json.dumps({'status':record['status'],'tests':len(ids),'actual_mode':mode}),flush=True)
    return 0 if record['status']=='PASS' else 1


def validate_worker(record,bundle,helper,mode):
    validate_worker_header(record,bundle,mode); validate_tests(record['tests'])
    validate_execution(record['executed_source_hashes'],bundle.identity,helper)
    if record['external_reference_sources']!=validate_external_sources(bundle): raise ValueError('worker external binding differs')
    validate_private_executions(record['private_dependency_executions'],record['executed_source_hashes'],bundle,helper)
    return validate_artifacts(record['artifacts'],bundle)


def final(run_id):
    if type(run_id) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,47}',run_id):
        raise ValueError('bounded new run ID required')
    helper,capture=install()
    from work.generator_upgrade_r8 import binding
    bundle=binding.load(); _,ids=discover(helper); require_release_ready(ids); stable(bundle,helper,capture)
    root=bundle.storage.plain_path(OUTPUT_ROOT/run_id); root.mkdir(parents=True,exist_ok=False)
    bundle.storage.write_json(root/'PARENT_SOURCE.json',{'source_identity':bundle.identity,
        'source_sha256':bundle.source_sha256,'parent_optimisation_flag':sys.flags.optimize,
        'external_reference_sources':validate_external_sources(bundle)})
    records=[]
    for label,mode,flags in (('n',0,[]),('o',2,['-OO'])):
        path=root/(label+'-worker.json')
        command=[sys.executable,'-B',*flags,str(HERE/'verify.py'),'--worker',str(path),
            '--parent-source',str(root/'PARENT_SOURCE.json'),'--mode',str(mode)]
        print('Executing exact-source scientific checks in mode '+str(mode),flush=True)
        try: process=subprocess.run(command,cwd=TASK,env=helper.child_environment(),capture_output=True,text=True,timeout=1800)
        except subprocess.TimeoutExpired as error:
            bundle.storage.write_json(root/(label+'-process.json'),{'status':'TIMEOUT'})
            raise RuntimeError('worker timed out; no PASS seal') from error
        bundle.storage.write_json(root/(label+'-process.json'),{'exit_code':process.returncode,'stdout':process.stdout,'stderr':process.stderr})
        if process.returncode: raise RuntimeError('worker failed; preserved attempt receipt: '+str(path))
        record=bundle.storage.read_json(path); validate_worker(record,bundle,helper,mode); records.append(record)
    for key in ('executed_source_hashes','private_dependency_executions'):
        if records[0][key]!=records[1][key]: raise ValueError('cross-mode executed-code identity differs')
    if records[0]['artifacts']['reference_sha256']!=records[1]['artifacts']['reference_sha256']:
        raise ValueError('normal/-OO actual scientific result differs')
    stable(bundle,helper,capture)
    seal={'schema':'diadem.biomes-vegetation-verification.r8','status':'BOUNDED_BIOMES_VEGETATION_REFERENCE_VERIFIED',
        'source_identity':bundle.identity,'source_sha256':bundle.source_sha256,'source_snapshot':bundle.identity['r8_sources'],
        'test_ids':ids,'test_count_per_mode':len(ids),'inventory_sha256':inventory_digest(ids),
        'workers':{label:{'path':str(root/(label+'-worker.json')),'sha256':sha((root/(label+'-worker.json')).read_bytes())} for label in ('n','o')},
        'normal_oo_parity':'EXACT_SCIENTIFIC_RESULT_AND_CHECKPOINT_PASS','parent_optimisation_flag':sys.flags.optimize,
        'actual_worker_flags':[r['optimisation_flag'] for r in records],
        'external_reference_sources':validate_external_sources(bundle),
        'production_installed':False,'canon_changed':False,'optimisation_performed':False,
        'scope':'bounded actual retained formed soil -> new twelve-month seasonal exposure -> biome and vegetation reference; no world production'}
    bundle.storage.write_json(root/'VERIFICATION.json',seal); capture.active=False
    print(json.dumps({'status':seal['status'],'path':str(root/'VERIFICATION.json'),'source_sha256':bundle.source_sha256}),flush=True)
    return 0


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--run-id'); parser.add_argument('--worker',type=Path)
    parser.add_argument('--parent-source',type=Path); parser.add_argument('--mode',type=int,choices=(0,2)); args=parser.parse_args()
    if args.worker:
        if args.parent_source is None or args.mode is None: parser.error('worker requires parent source and actual mode')
        return worker(args.worker,args.parent_source,args.mode)
    if not args.run_id: parser.error('new run ID required')
    return final(args.run_id)


if __name__=='__main__':
    raw=Path(__file__).read_bytes(); namespace={'__file__':__file__,'__name__':'_r8_fresh_verification_entry'}
    exec(compile(raw,__file__,'exec',dont_inherit=True),namespace)
    namespace['ENTRY_SOURCE_SHA256']=sha(raw)
    raise SystemExit(namespace['main']())
