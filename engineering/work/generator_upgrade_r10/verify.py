"""Source-locked dual-mode R10 verification, with an explicit pending release gate.

No predecessor acceptance suite is counted as new R10 testing. Wall times are
execution receipts only, never performance or optimisation comparisons.
"""
import argparse
from copy import deepcopy
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
OUTPUT_ROOT=TASK/'outputs/generator-upgrade-r10'
SUITES=('test_binding','test_climate','test_hydraulics','test_richards_numerics','test_plants','test_seasonal_carbon','test_payloads','test_pipeline','test_verification')
EXPECTED_COUNT=331
INVENTORY_SHA256='278aff7bd67070b0c4286870873d1d202c0ee8f464ba828c405bebb989499d6b'
PRODUCT_CONTRACT_READY=True
ENTRY_SOURCE_SHA256=None
R4_SEAL_SHA256='f7382693a5284ebf111dc8a0622e5811440ccc7e2b546047943462b849926996'
RESULT_SCHEMA='diadem.seasonal-world-result.r10'
VERIFIED_STATUS='BOUNDED_SEASONAL_WORLD_REFERENCE_VERIFIED_WITH_DOWNSTREAM_INPUT_GAPS'
ARTIFACT_NAMES=frozenset(('recipe.json','full-result.json','stop-result.json','restart-result.json',
    'stop-checkpoint.json','full-checkpoint.json','restart-checkpoint.json','parent-result.json','physical-parent-result.json'))


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
    module=types.ModuleType('_r10_exact_verification_utilities'); module.__file__=str(path)
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
    r9=identity['retained_source_identity']; r8=r9['retained_source_identity']; r7=r8['retained_source_identity']
    r6=r7['retained_source_identity']; r5=r6['retained_source_identity']
    result=helper.source_map(r5['retained_source_identity'])
    maps=(r5['r5_sources'],r6['r6_sources'],r7['r7_sources'],r7['external_test_reference_sources'],
        r8['r8_sources'],r8['external_reference_sources'],r9['r9_sources'],r9['external_reference_sources'],
        identity['r10_sources'],external_sources(identity))
    for mapping in maps:
        for path,digest in mapping.items():
            key=helper.canonical(path)
            if key in result and result[key]!=digest: raise ValueError('conflicting source binding')
            result[key]=digest
    return result


def external_sources(identity):
    """Explicit seasonal owner/authority evidence; never an empty fallback."""
    rows=identity.get('external_reference_sources')
    if type(rows) is not dict or not 1<=len(rows)<=256: raise ValueError('explicit external reference map required')
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
    own=(*SUITES,'binding','provenance','pipeline','reference','owner_inputs','fixtures','climate','hydraulics','richards_numerics','plants','seasonal_carbon','carbon_bridge','payloads','verify')
    inherited={
        'r9':('binding','provenance','pipeline','reference','owner_inputs','sources','spatial','stock','phases','upstream','verify'),
        'r8':('binding','provenance','pipeline','biomes','vegetation','seasonal','verify'),
        'r7':('binding','provenance','pipeline','formation','organic','fertility','verify'),
        'r6':('binding','provenance','soil_water','hydraulic_jacobian'),
        'r4':('pipeline','climate','hydromet'),
        'r3':('pipeline','soil_inputs','terrain_transport')}
    return [HERE/(name+'.py') for name in own]+[
        TASK/('work/generator_upgrade_'+version+'/'+name+'.py') for version,names in inherited.items() for name in names]


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
    if bundle.identity['r10_sources'].get(str(HERE/'verify.py'))!=ENTRY_SOURCE_SHA256:
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
    suite=loader.loadTestsFromNames(['work.generator_upgrade_r10.'+name for name in SUITES])
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



def validate_envelope(result,recipe,bundle,parent,physical,*,complete):
    """Only parent/source/unit identity; scientific acceptance is separate."""
    s=bundle.storage; parent_sha=sha(s.encoded(parent)); physical_sha=sha(s.encoded(physical))
    if (result.get('schema')!=RESULT_SCHEMA or result.get('source_sha256')!=bundle.source_sha256
            or result.get('recipe_sha256')!=sha(s.encoded(recipe))
            or parent.get('schema')!='diadem.species-spatial-result.r9'
            or parent.get('source_sha256')!=bundle.parent.source_sha256
            or parent.get('recipe_sha256')!=sha(s.encoded(recipe['parent_recipe']))
            or physical.get('schema')!='diadem.biomes-vegetation-result.r8'
            or physical.get('source_sha256')!=bundle.parent.parent.source_sha256
            or physical.get('recipe_sha256')!=sha(s.encoded(recipe['parent_recipe']['parent_recipe']))
            or parent.get('parent_result_sha256')!=physical_sha
            or result.get('parent_result_sha256')!=parent_sha
            or result.get('physical_parent_result_sha256')!=physical_sha):
        raise ValueError('actual recipe/source/separate R9 and R8 parent join differs')
    state=result['state']
    if set(state)!={'completed_units','parent_result_sha256','physical_parent_result_sha256','results'}:
        raise ValueError('exact bounded seasonal-year state required')
    if state['parent_result_sha256']!=parent_sha or state['physical_parent_result_sha256']!=physical_sha:
        raise ValueError('state parent support identity differs')
    ordered=sorted(member+'/'+hypothesis+'/'+cell for member,cells in physical['state']['members'].items()
        for hypothesis in recipe['hydraulic_hypotheses'] for cell in cells)
    cursor=state['completed_units']; results=state['results']
    if (type(cursor) is not int or type(results) is not dict or cursor!=len(results)
            or sorted(results)!=ordered[:cursor] or complete and cursor!=len(ordered) or not complete and cursor!=1):
        raise ValueError('complete/partial whole-year unit cursor differs')
    return ordered[:cursor]


def validate_products(full,bundle,recipe,parent,physical):
    if PRODUCT_CONTRACT_READY is not True:
        raise ValueError('scientific product contract pending; no final seal')
    keys=validate_envelope(full,recipe,bundle,parent,physical,complete=True)
    retained=bundle.parent.graph.load('work.generator_upgrade_r9.verify')
    parent_checks=retained.validate_products(parent,bundle.parent,recipe['parent_recipe'],physical)
    if (full['status']!='COMPLETE_BOUNDED_SEASONAL_EXECUTION' or full['source_status']!='WORKING NON-CANON'
            or any(full[k] is not True for k in ('hypotheses_are_coequal_not_additive','physical_soil_water_is_not_pft_bucket_water',
                'soil_is_not_periodic_or_spun_up','r9_species_result_retained_separately'))
            or any(full[k] is not False for k in ('production_installed','canon_changed','optimisation_performed'))
            or full['limits']!=recipe['limits']): raise ValueError('seasonal execution scope/source labels differ')
    refs=full['owner_sources']
    owner_refs=bundle.graph.load('work.generator_upgrade_r10.owner_inputs').source_bindings()
    if (sorted(refs,key=lambda r:r['path'])!=sorted(owner_refs,key=lambda r:r['path'])
            or any(bundle.identity['external_reference_sources'].get(row['path'])!=row['sha256'] for row in refs)):
        raise ValueError('current seasonal owner contracts/source roles differ')
    climate_checks=validate_climate(full['climate'],physical); pft_count=0
    activities=decode_payload(full['plant_activity'],bundle)
    if set(activities)!=set(physical['state']['members']): raise ValueError('coequal plant snow scenarios omitted')
    for snow,member in physical['state']['members'].items():
        if set(activities[snow])!=set(member): raise ValueError('actual plant cells omitted')
        for cell,source in member.items():
            if set(activities[snow][cell])!=set(source['pft_results']): raise ValueError('coequal plant families omitted')
            for family,pfts in source['pft_results'].items():
                if set(activities[snow][cell][family])!=set(pfts): raise ValueError('potential functional types omitted')
                for pft,actual in pfts.items():
                    validate_plant_activity(activities[snow][cell][family][pft],actual,snow+'/'+family+'/'+cell+'/'+pft); pft_count+=1
    species=validate_species_phenology(full['species_phenology'],parent['biological_owner_contracts'])
    physical_recipe=recipe['parent_recipe']['parent_recipe']; summaries={}; carbon_count=0
    for key in keys:
        snow,hypothesis_id,cell=key.split('/'); row=decode_payload(full['state']['results'][key],bundle)
        h=recipe['hydraulic_hypotheses'][hypothesis_id]; spec=h['columns'][cell]
        source=physical['state']['members'][snow][cell]; soil=physical['soil_result']['state']['members'][snow][cell]
        probe=soil['formed_soil_water']; water=row['hydrology']; inputs=water['inputs']
        if (row['snow_id']!=snow or row['hydraulic_hypothesis_id']!=hypothesis_id or row['cell_id']!=cell
                or row['physical_cell_sha256']!=sha(encoded(source)) or row['formed_soil_sha256']!=sha(encoded(soil))
                or row['initial_water_source_sha256']!=sha(encoded(probe)) or row['initial_condition']!=spec
                or inputs['column']!=probe['column'] or inputs['initial_state']!=probe['result']['state']
                or inputs['scenario_id']!=key or inputs['source_binding_sha256']!=bundle.source_sha256):
            raise ValueError('actual formed material/profile/initial pressure/scenario support differs')
        for field in ('water_density_kg_m3','gravity_m_s2','duration_atol_s','budget_atol_m'):
            if inputs[field]!=recipe[field]: raise ValueError('explicit hydraulic physical/numerical input differs')
        if inputs['controls']!=recipe['hydraulic_controls']: raise ValueError('seasonal controls changed silently')
        validate_numerical_binding(water,bundle.identity['numerical_implementation']['runtime_binding'])
        layer_ids=[l['layer_id'] for l in probe['column']['layers']]; face=layer_ids.index(spec['root_boundary_above_layer_id'])
        pft=physical_recipe['pfts'][h['pft_id']]; weights=[spec['root_weights_by_layer'].get(k,0.) for k in layer_ids]
        geometry={g['layer_id']:g for g in soil['geometry']}
        if (inputs['root_boundary_index']!=face or face<1 or not set(spec['root_weights_by_layer'])<=set(layer_ids)
                or any(w and (i>=face or geometry[k]['phase'] not in pft['rooting']['allowed_phases']) for i,(k,w) in enumerate(zip(layer_ids,weights)))
                or math.fsum(l['thickness_m'] for l in probe['column']['layers'][:face])>pft['rooting']['maximum_root_depth_m']+1e-12):
            raise ValueError('uptake or root face exceeds actual supplied physical/PFT support')
        actual_events=physical['seasonal']['members'][snow]['cells'][cell]['events']
        if len(inputs['events'])!=len(actual_events): raise ValueError('once-only snow-liquid event count differs')
        multiplier=physical_recipe['family_demand_multipliers'][h['family_id']]
        for event,actual in zip(inputs['events'],actual_events):
            active=actual['temperature_c']>pft['active_above_temperature_c']
            demand=actual['potential_evaporation_m_s']*pft['reference_transpiration_fraction']*multiplier if active else 0.
            if (event['event_id']!=actual['event_id'] or event['month_id']!=actual['month_id']
                    or F(event['duration_seconds'])!=F(actual['duration_seconds'])
                    or F(event['liquid_input_m_s'])!=F(actual['liquid_input_m_s'])
                    or F(event['potential_root_demand_m_s'])!=F(demand) or event['air_temperature_c']!=actual['temperature_c']
                    or event['uptake']!={**spec['uptake'],'weights':weights} or event['boundary']!=spec['boundary']
                    or event['vegetation_hypothesis_id']!=hypothesis_id or event['soil_thermal_regime']!=spec['soil_thermal_regime']
                    or event['thermal_evidence']!=spec['thermal_evidence'] or event['source_status']!=h['source_status']):
                raise ValueError('physical water forcing/demand/root/boundary differs from actual R8 support and explicit scenario')
        summary=validate_hydraulic_year(water)
        if water['status']!='MODELLED_SEASONAL_HYDRAULICS': raise ValueError('reference seasonal hydraulic year is not complete')
        carbon_count+=validate_carbon_join(row['carbon'],water,soil,recipe['carbon'],bundle.source_sha256,key)
        downstream=row['downstream']; area=F(source['area_m2'])
        unavailable=('river_flow_m3_s','lake_level_m','wetland_hydroperiod_seconds','soil_ice_fraction','crop_yield_kg','food_supply_kg',
            'route_passability','settlement_water_security','slope_failure_probability','seasonal_population_growth','political_boundary_change')
        if (F(downstream['represented_area_m2'])!=area or any(downstream[k] is not None for k in unavailable)
                or downstream['states_are_not_extra_water_or_food_sources'] is not True
                or set(downstream['local_water_supply'])!=set(water['months'])): raise ValueError('local physical export promoted to unsupported downstream mechanisms')
        for month,monthly in water['months'].items():
            export=F(monthly['ledger_m']['surface_runoff_m'])*area; out=downstream['local_water_supply'][month]
            if quantity(out['local_surface_export_m3'])!=export or quantity(out['local_mean_export_supply_m3_s'])!=export/F(monthly['duration_seconds']):
                raise ValueError('local surface export area/time conversion differs')
        summaries[key]=summary
    return {'status':'BOUNDED_SEASONAL_REFERENCE_CHECKED','retained_species_engine':parent_checks,'climate':climate_checks,
        'coequal_complete_hydraulic_years':len(keys),'conditional_pft_year_profiles':pft_count,'species_phenology':species,
        'conditional_carbon_layer_years':carbon_count,'hydraulic_years':summaries,
        'numerical_implementation':bundle.identity['numerical_implementation'],
        'lossless_unit_payloads':{key:{'sha256':full['state']['results'][key]['sha256'],'uncompressed_byte_length':full['state']['results'][key]['byte_length']} for key in keys},
        'lossless_plant_payload':{'sha256':full['plant_activity']['sha256'],'uncompressed_byte_length':full['plant_activity']['byte_length']},
        'counterfactual_water_use_summed':False,'dynamic_river_lake_freeze_growth_claim':False}


def decode_payload(record,bundle):
    value=bundle.graph.load('work.generator_upgrade_r10.payloads').unpack(record)
    raw=encoded(value)
    if len(raw)>8*1024*1024 or len(raw)!=record['byte_length'] or sha(raw)!=record['sha256']:
        raise ValueError('lossless scientific payload changed its canonical byte identity or size')
    return value


def validate_carbon_join(product,water,soil,scenario,source_sha,unit_key):
    cell=unit_key.split('/')[-1]; expected_ids={cell+s for s in scenario['selected_layer_suffixes']}
    if (product['status']!='CONDITIONAL_DIAGNOSTIC_ONLY' or set(product['layers'])!=expected_ids
            or product['water_product_sha256']!=sha(encoded(water)) or product['geometry_feedback']!='NOT_APPLIED_DIAGNOSTIC_ONLY'
            or any(product[k] is not True for k in ('same_pool_age_initialised_once','physical_geometry_and_water_not_modified','selected_layers_not_whole_soil_inventory'))):
        raise ValueError('carbon diagnostic feedback/source/selected-layer scope differs')
    unknown=product['actual_field_prediction']
    if unknown['status']!='UNKNOWN' or any(unknown[k] is not None for k in ('soil_temperature_k','redox','litter_carbon_kg_m2_s')):
        raise ValueError('declared carbon drivers promoted to actual field prediction')
    layers=water['column']['layers']; ids=[l['layer_id'] for l in layers]
    for layer_id,item in product['layers'].items():
        source=soil['surface_organic'] if soil['surface_organic']['layer_id']==layer_id else soil['organic_by_layer'][layer_id]
        carbon=item['diagnostic']; inputs=carbon['inputs']; index=ids.index(layer_id); layer=layers[index]
        native_initial={'schema':'diadem.organic-pool-state.r7',**source['state']}
        for field in ('fast_carbon_kg_m2','slow_carbon_kg_m2','elapsed_seconds'):
            value=F(source['state'][field]); native_initial[field]=[value.numerator,value.denominator]
        if (item['initial_pool_source_sha256']!=sha(encoded(source)) or inputs['initial_state']!=native_initial
                or inputs['law']!=source['law'] or inputs['numerics']!=source['numerics']
                or inputs['geometry_sha256']!=sha(encoded(soil['geometry'])) or inputs['source_binding_sha256']!=source_sha
                or inputs['scenario_id']!=unit_key+'/'+layer_id or inputs['calendar']!=water['inputs']['calendar']):
            raise ValueError('seasonal carbon did not carry exact retained pools/law/geometry/calendar')
        state=water['initial_state']; elapsed=F(); suffix=layer_id[len(cell):]
        if len(inputs['events'])!=len(water['events']): raise ValueError('carbon/water event inventory differs')
        for event,hydraulic in zip(inputs['events'],water['events']):
            forcing=event['forcing']; month=hydraulic['month_id']-1; dt=F(hydraulic['duration_seconds'])
            if (event['event_id']!=hydraulic['event_id'] or event['month_id']!=hydraulic['month_id']
                    or event['layer_id']!=layer_id or event['moisture_hold']!='EVENT_START_SAMPLE_HELD'
                    or F(event['water_sample_seconds_in_year'])!=elapsed or F(forcing['duration_seconds'])!=dt
                    or forcing['soil_temperature_k']!=scenario['soil_temperature_k_by_month'][month]
                    or forcing['redox']!=scenario['redox'] or forcing['regime']!=scenario['regime_by_suffix'][suffix]
                    or forcing['climate_state_id']!='declared-soil-temperature/'+sha(encoded(scenario))
                    or forcing['water_state_id']!='actual-water-start/'+sha(encoded(state))):
                raise ValueError('actual own-layer start-held water/carbon driver source or timing differs')
            close(forcing['water_filled_pore_fraction'],theta(layer,state['head_m'][index])/layer['theta_s'],'actual own-layer liquid pore fraction')
            for field in ('fast_litter_carbon_kg_m2_s','slow_litter_carbon_kg_m2_s'):
                if F(forcing[field])!=F(scenario[field+'_by_month'][month]): raise ValueError('seasonal litter repeated, omitted or invented')
            state=hydraulic['solver_result']['state']; elapsed+=dt
        validate_carbon_year(carbon)
        if carbon['status']!='MODELLED_SEASONAL_CARBON_DIAGNOSTIC': raise ValueError('reference conditional carbon year is incomplete')
    return len(expected_ids)


def close(actual,expected,name,*,atol=1e-12):
    if (type(actual) not in (int,float,F) or type(expected) not in (int,float,F)
            or not math.isfinite(actual) or not math.isfinite(expected)
            or abs(actual-expected)>atol+1e-12*max(abs(actual),abs(expected))):
        raise ValueError(name+' differs from independent accounting')


def theta(layer,head):
    """Independent scalar retention, not another call to the time integrator."""
    if head>=0: return layer['theta_s']
    value=(1+(-layer['alpha_per_m']*head)**layer['n'])**(-(1-1/layer['n']))
    return layer['theta_r']+(layer['theta_s']-layer['theta_r'])*value


def quantity(row):
    if type(row) is not dict or set(row)!={'exact','value'} or type(row['exact']) is not str:
        raise ValueError('explicit exact quantity and represented display required')
    value=F(row['exact'])
    if type(row['value']) not in (int,float) or row['value']!=float(value): raise ValueError('quantity/display representation differs')
    return value


def validate_climate(product,physical):
    if (product['schema']!='diadem.seasonal-climate-state.r10' or product['parent_result_sha256']!=sha(encoded(physical))
            or product['parent_source_sha256']!=physical['source_sha256'] or product['calendar']!=physical['seasonal']['calendar']
            or product['calendar_sha256']!=sha(encoded(product['calendar'])) or set(product['members'])!=set(physical['seasonal']['members'])):
        raise ValueError('actual representative climate/physical/calendar source binding differs')
    calendar=product['calendar']; durations=[F(calendar['day_seconds'])*d for d in calendar['month_days']]
    year=sum(durations,F()); months_count=events_count=0; totals={}
    amounts=('precipitation_m','snowfall_swe_m','rain_m','melt_m','liquid_to_soil_m','reference_potential_evaporation_m','potential_condensation_m')
    for member_id,member in product['members'].items():
        original=physical['seasonal']['members'][member_id]
        if member['formed_terrain_sha256']!=sha(encoded(original['formed_terrain'])) or set(member['cells'])!=set(original['cells']):
            raise ValueError('formed terrain or seasonal climate cell support differs')
        for cell_id,cell in member['cells'].items():
            source=original['cells'][cell_id]
            if source['status']!='MODELLED_PERIODIC_SNOW':
                if cell['status']!='UNKNOWN' or any(cell[key] is not None for key in ('months','events','annual')):
                    raise ValueError('incomplete atmosphere/snow promoted to a seasonal state')
                continue
            if (cell['status']!='MODELLED_REPRESENTATIVE_SEASONS' or cell['source_cell_sha256']!=sha(encoded(source))
                    or [row['month_id'] for row in cell['months']]!=list(range(1,13))): raise ValueError('actual climate month inventory differs')
            clock=F(); swe=F(source['initial_swe_m']); annual={key:F() for key in amounts}; monthly=[]
            for row,prior,atmosphere,dt in zip(cell['months'],source['months'],original['atmosphere'],durations):
                if (F(row['duration_seconds'])!=dt or F(row['start_seconds'])!=clock or F(row['end_seconds'])!=clock+dt
                        or row['snow_source_sha256']!=sha(encoded(prior['snow'])) or row['monthly_source_sha256']!=sha(encoded(prior))
                        or row['atmosphere_source_sha256']!=sha(encoded(atmosphere))): raise ValueError('month event clock or source support differs')
                snow=prior['snow']['ledger']
                expected={'precipitation_m':F(prior['precipitation_m_s'])*dt,'snowfall_swe_m':F(snow['snowfall_m']),
                    'rain_m':F(snow['rain_m']),'melt_m':F(snow['melt_m']),'liquid_to_soil_m':F(snow['liquid_to_soil_m']),
                    'reference_potential_evaporation_m':F(prior['potential_evaporation_m_s'])*dt,
                    'potential_condensation_m':F(prior['potential_condensation_m_s'])*dt}
                if (quantity(row['initial_swe_m'])!=swe or quantity(row['final_swe_m'])!=swe+expected['snowfall_swe_m']-expected['melt_m']
                        or expected['precipitation_m']!=expected['snowfall_swe_m']+expected['rain_m']
                        or expected['liquid_to_soil_m']!=expected['rain_m']+expected['melt_m']): raise ValueError('seasonal snow/rain/melt conservation or continuity differs')
                for key,value in expected.items():
                    if quantity(row[key])!=value: raise ValueError('actual monthly atmosphere/snow integral differs')
                    annual[key]+=value
                regimes=atmosphere['regimes']; weights=[F(r['weight']) for r in regimes]; airs=[r['products'][cell_id]['air'] for r in regimes]
                if sum(weights,F())!=1: raise ValueError('actual regime support weights differ')
                fields=('temperature_c','specific_humidity_kg_kg','pressure_pa','vapour_pressure_pa','relative_humidity_liquid',
                    'wind_east_10m_m_s','wind_north_10m_m_s','mean_scalar_speed_10m_m_s')
                means={key:sum((weight*F(air[key]) for weight,air in zip(weights,airs)),F()) for key in fields}
                for key,value in means.items():
                    if quantity(row['air'][key])!=value: raise ValueError('actual regime-weighted moist-air component differs')
                east,north=means['wind_east_10m_m_s'],means['wind_north_10m_m_s']
                close(row['air']['resultant_speed_10m_m_s'],math.hypot(float(east),float(north)),'wind vector resultant')
                if east==north==0:
                    if row['air']['wind_from_degrees'] is not None or row['air']['wind_direction_status']!='UNDEFINED_ZERO_RESULTANT': raise ValueError('zero wind acquired a direction')
                else:
                    close(row['air']['wind_from_degrees'],math.degrees(math.atan2(-float(east),-float(north)))%360,'meteorological wind-from direction')
                    if row['air']['wind_direction_status']!='MODELLED_VECTOR_RESULTANT': raise ValueError('known wind vector status differs')
                deficit=sum((w*(F(a['saturation_vapour_pressure_pa'])-F(a['vapour_pressure_pa'])) for w,a in zip(weights,airs)),F())
                if quantity(row['air']['vapour_pressure_deficit_pa'])!=deficit: raise ValueError('supplied humidity/vapour support differs')
                if any(row[key] is not None for key in ('soil_temperature_c','soil_freeze_fraction','river_flow_m3_s','lake_level_m')):
                    raise ValueError('atmosphere/snow substituted for missing thermal or routed-water models')
                monthly.append(expected); swe=quantity(row['final_swe_m']); clock+=dt; months_count+=1
            if clock!=year: raise ValueError('representative climate year duration differs')
            for key,value in annual.items():
                if quantity(cell['annual'][key])!=value: raise ValueError('annual climate integral differs')
            weighted=sum((quantity(row['air']['temperature_c'])*dt for row,dt in zip(cell['months'],durations)),F())/year
            arithmetic=sum((quantity(row['air']['temperature_c']) for row in cell['months']),F())/12
            if (quantity(cell['annual']['duration_weighted_temperature_c'])!=weighted
                    or quantity(cell['annual']['arithmetic_mean_of_monthly_means_temperature_c'])!=arithmetic
                    or F(cell['annual']['duration_seconds'])!=year
                    or quantity(cell['annual']['snow_water_residual_m'])!=annual['precipitation_m']+F(source['initial_swe_m'])-annual['liquid_to_soil_m']-swe):
                raise ValueError('annual weighted climate/whole snow balance differs')
            expected_deficit=sum((max(m['reference_potential_evaporation_m']-m['precipitation_m'],F()) for i,m in enumerate(monthly,1) if i in (5,6,7,8,9)),F())
            if cell['annual']['warm_climatic_deficit_month_ids']!=[5,6,7,8,9] or quantity(cell['annual']['warm_climatic_deficit_m'])!=expected_deficit: raise ValueError('owner-defined warm climatic deficit differs')
            wet=[i for i,m in enumerate(monthly,1) if m['precipitation_m']>=m['reference_potential_evaporation_m']]
            dry=[i for i,m in enumerate(monthly,1) if m['precipitation_m']<m['reference_potential_evaporation_m']/2]
            longest=max((next((n for n in range(12) if (start+n)%12+1 not in dry),12) for start in range(12)),default=0)
            support=cell['monthly_climatic_support']
            if support['wet_month_ids']!=wet or support['strongly_dry_month_ids']!=dry or support['longest_circular_strongly_dry_run_months']!=longest: raise ValueError('circular climatic support differs from monthly P/PET')
            for label,ids in (('warm',[4,5,6,7,8,9]),('cool',[10,11,12,1,2,3])):
                selected=[row for row in cell['months'] if row['month_id'] in ids]; duration=sum((F(row['duration_seconds']) for row in selected),F())
                summary=cell['seasonal_summaries'][label]
                if summary['month_ids']!=ids or F(summary['duration_seconds'])!=duration: raise ValueError('declared seasonal summary support differs')
                for key in ('precipitation_m','reference_potential_evaporation_m'):
                    if quantity(summary[key])!=sum((quantity(row[key]) for row in selected),F()): raise ValueError('seasonal integrated climate supply differs')
                for key in ('temperature_c','specific_humidity_kg_kg','wind_east_10m_m_s','wind_north_10m_m_s','mean_scalar_speed_10m_m_s'):
                    expected=sum((quantity(row['air'][key])*F(row['duration_seconds']) for row in selected),F())/duration
                    if quantity(summary['duration_weighted_air'][key])!=expected: raise ValueError('seasonal duration-weighted air differs')
            clock=F(); liquids={i:F() for i in range(1,13)}; spans={i:F() for i in range(1,13)}
            if len(cell['events'])!=len(source['events']): raise ValueError('actual liquid event inventory differs')
            for event,prior in zip(cell['events'],source['events']):
                dt=F(prior['duration_seconds']); represented=F(prior['liquid_input_m_s'])*dt; error=F(prior['liquid_conversion_error_m']); mid=prior['month_id']
                if (event['event_id']!=prior['event_id'] or event['month_id']!=mid or event['source_sha256']!=sha(encoded(prior))
                        or F(event['start_seconds'])!=clock or F(event['end_seconds'])!=clock+dt or F(event['duration_seconds'])!=dt
                        or quantity(event['represented_liquid_m'])!=represented or quantity(event['representation_error_m'])!=error
                        or quantity(event['exact_snow_liquid_m'])!=represented-error): raise ValueError('once-only liquid supply/event representation differs')
                liquids[mid]+=represented-error; spans[mid]+=dt; clock+=dt; events_count+=1
            if clock!=year or any(spans[i]!=durations[i-1] or liquids[i]!=monthly[i-1]['liquid_to_soil_m'] for i in range(1,13)):
                raise ValueError('event/month chronology or liquid conservation differs')
            totals[member_id+'/'+cell_id]={'precipitation_m':str(annual['precipitation_m']),'liquid_to_soil_m':str(annual['liquid_to_soil_m']),
                'duration_weighted_temperature_c':str(weighted),'final_swe_m':str(swe)}
    return {'actual_months':months_count,'actual_liquid_events':events_count,'duration_seconds':str(year),'cells':totals}


HYDRAULIC_LEDGER=('surface_input_m','infiltration_m','rain_excess_runoff_m',
    'surface_exfiltration_m','surface_runoff_m','actual_et_m','potential_et_m',
    'bottom_downward_m','bottom_upward_m','root_zone_gross_downward_m','root_zone_upward_capillary_m')


def validate_plant_activity(product,actual,source_id):
    if (product['schema']!='diadem.pft-seasonal-activity.r10' or product['pft_id']!=actual['pft_id']
            or product['ecological_admissibility']!=actual['status'] or product['source_status']!=actual['source_status']
            or product['source']!={'context_id':source_id,'pft_payload_sha256':sha(encoded(actual)),'producer_binding':actual.get('source_binding')}
            or product['calendar']!=actual['inputs']['calendar']): raise ValueError('actual PFT payload/admissibility/calendar source join differs')
    source_events=actual['inputs']['events']; durations=[F(v) for v in actual['inputs']['calendar']['month_durations_seconds']]
    water=actual['water']; modelled=water['status']=='MODELLED_PERIODIC_BRACKET'
    if (product['status']!=('MODELLED_CONDITIONAL_ACTIVITY' if modelled else water['status'])
            or [r['month_id'] for r in product['months']]!=list(range(1,13))): raise ValueError('conditional PFT water/status inventory differs')
    active_total=F()
    def bracket(a,b): return {'lower':min(a,b),'upper':max(a,b)}
    for month,(row,dt) in enumerate(zip(product['months'],durations),1):
        events=[e for e in source_events if e['month_id']==month]
        known=all(e['source_status'] in ('CANON','WORKING NON-CANON','MODELLED','SYNTHETIC TEST') and type(e['active']) is bool for e in events)
        active=sum((F(e['duration_seconds']) for e in events if e['active']),F()) if known else None
        if (F(row['duration_seconds'])!=dt or row['event_ids']!=[e['event_id'] for e in events]
                or row['physiological_active_duration_seconds']!=(None if active is None else str(active))
                or row['physiological_active_fraction']!=(None if active is None else float(active/dt))
                or row['activity_status']!=('MODELLED_HYPOTHESIS' if known else 'UNKNOWN') or row['water_status']!=water['status']
                or any(row[key] is not None for key in ('dry_active_duration_s','leaf_on','dormancy','flowering','growth_biomass_kg'))):
            raise ValueError('PFT activation relabelled calendar means, species phenology or growth')
        if active is not None: active_total+=active
        if not modelled:
            if row['available_water'] is not None: raise ValueError('missing PFT water evidence replaced by a numerical bracket')
            continue
        low,high=([e for e in water[side]['events'] if e['month_id']==month] for side in ('lower','upper'))
        expected={'initial_storage_m':bracket(low[0]['initial_m'],high[0]['initial_m']),
            'final_storage_m':bracket(low[-1]['final_m'],high[-1]['final_m']),'capacity_m':water['capacity_m'],
            'minimum_storage_m':bracket(min(min(e['initial_m'],e['final_m']) for e in low),min(min(e['initial_m'],e['final_m']) for e in high)),
            'maximum_storage_m':bracket(max(max(e['initial_m'],e['final_m']) for e in low),max(max(e['initial_m'],e['final_m']) for e in high))}
        for key in ('input_m','potential_transpiration_m','actual_transpiration_m','overflow_m'):
            expected[key]=bracket(math.fsum(e[key] for e in low),math.fsum(e[key] for e in high))
        for key in ('potential_transpiration_m','actual_transpiration_m'):
            expected['active_'+key]=bracket(math.fsum(e[key] for e in low if e['active']),math.fsum(e[key] for e in high if e['active']))
        demand=expected['active_potential_transpiration_m']['lower']
        if demand!=expected['active_potential_transpiration_m']['upper']: raise ValueError('PFT numerical initial state changed supplied demand')
        expected['active_actual_to_potential_transpiration_ratio']=None if demand==0 else bracket(expected['active_actual_transpiration_m']['lower']/demand,expected['active_actual_transpiration_m']['upper']/demand)
        expected['represented_demand_minus_actual_m']=bracket(float(sum((F(e['potential_transpiration_m'])-F(e['actual_transpiration_m']) for e in low),F())),float(sum((F(e['potential_transpiration_m'])-F(e['actual_transpiration_m']) for e in high),F())))
        residuals={}
        for side,events in (('lower_trajectory',low),('upper_trajectory',high)):
            residual=sum((F(e['initial_m'])+F(e['liquid_input_m_s'])*F(e['duration_seconds'])-F(e['final_m'])-F(e['actual_transpiration_m'])-F(e['overflow_m']) for e in events),F())
            if residual!=sum((F(e['numerical_residual_m']) for e in events),F()): raise ValueError('actual PFT reservoir ledger differs')
            residuals[side]=str(residual)
        expected['numerical_residual_m']=residuals
        if row['available_water']!=expected: raise ValueError('actual PFT available-water event/bracket aggregation differs')
    cyclic=product['cyclic_drought']; threshold=actual['inputs']['constraints'].get('dry_stress_fraction')
    if cyclic['threshold_fraction']!=threshold: raise ValueError('retained physiological dry threshold differs')
    known=True
    for target,key in (('dry_active_duration_s','dry_active_duration_s'),('longest_cyclic_dry_active_spell_s','longest_dry_active_spell_s')):
        values=[water[side].get(key) for side in ('lower','upper')] if modelled else [None,None]
        expected=None if None in values else bracket(*values)
        if cyclic[target]!=expected: raise ValueError('retained whole-cycle dry-crossing diagnostics changed')
        if expected is None: known=False
    if cyclic['status']!=('MODELLED_RETAINED_DIAGNOSTIC' if known else 'UNKNOWN'): raise ValueError('unsupported monthly drought chronology inferred')
    return {'pft_id':product['pft_id'],'ecological_admissibility':product['ecological_admissibility'],
        'conditional_water_status':product['status'],'active_duration_seconds':str(active_total),'actual_species_phenology':None}


def validate_species_phenology(product,roster):
    plants={key:value for key,value in roster.items() if value['kind']=='PLANT'}
    if (product['schema']!='diadem.plant-owner-phenology-status.r10' or product['status']!='UNKNOWN'
            or product['roster_payload_sha256']!=sha(encoded(roster)) or set(product['plants'])!=set(plants)):
        raise ValueError('owner plant/phenology status binding differs')
    for ident,source in plants.items():
        row=product['plants'][ident]
        if (any(row[key]!=source[key] for key in ('organism_id','name','source_status','source_binding','evidence'))
                or row['qualitative_constraints']!=source['special_details'] or row['status']!='UNKNOWN'
                or any(row[key] is not None for key in ('leaf_on_windows','dormancy_windows','flowering_windows','fruiting_windows','seed_or_spore_release_windows','growth_or_reproduction_rates'))):
            raise ValueError('qualitative plant evidence promoted to numerical phenology')
    return {'owner_bound_plants':len(plants),'numerical_species_phenology':'UNKNOWN'}


def validate_carbon_year(product):
    """Independent exact carbon/dry-origin stocks, interval holds and retained ages."""
    inputs=product['inputs']; calendar=inputs['calendar']; events=inputs['events']; actual=product['events']
    if (product['schema']!='diadem.seasonal-organic-carbon.r10' or product['inputs_sha256']!=sha(encoded(inputs))
            or product['geometry_feedback']!='NOT_APPLIED_DIAGNOSTIC_ONLY'
            or any(product[key]!=inputs[key] for key in ('geometry_sha256','source_binding_sha256','scenario_id'))):
        raise ValueError('diagnostic carbon source/geometry/scenario binding differs')
    durations=[F(d) for d in calendar['month_durations_seconds']]; year=sum(durations,F())
    if len(durations)!=12 or any(d<=0 for d in durations) or year!=365*F(calendar['day_seconds']): raise ValueError('explicit carbon year differs')
    if (len(actual)!=len(events) or len({e['event_id'] for e in events})!=len(events)
            or [e['month_id'] for e in events]!=sorted(e['month_id'] for e in events)
            or any(sum((F(e['forcing']['duration_seconds']) for e in events if e['month_id']==m),F())!=durations[m-1] for m in range(1,13))):
        raise ValueError('exact carbon event/month coverage differs')
    def pool(record):
        if record.get('schema')!='diadem.organic-pool-state.r7': raise ValueError('retained organic state schema required')
        values=dict(record); del values['schema']
        for key in ('fast_carbon_kg_m2','slow_carbon_kg_m2','elapsed_seconds'):
            pair=values[key]
            if type(pair) is not list or len(pair)!=2 or any(type(v) is not int for v in pair) or pair[1]<=0: raise ValueError('exact retained organic state representation required')
            values[key]=str(F(*pair))
        return values
    def stock(state): return F(state['fast_carbon_kg_m2'])+F(state['slow_carbon_kg_m2'])
    initial=pool(inputs['initial_state']); state=initial; elapsed=F(); rows=[]; stopped=False
    if (product['layer_id']!=initial['layer_id'] or product['support_id']!=initial['support_id']
            or F(product['calendar_start_pool_age_seconds'])!=F(initial['elapsed_seconds'])): raise ValueError('retained organic initial support/age differs')
    fraction=inputs['law']['carbon_fraction_dry_matter']
    fraction=None if fraction is None else F(fraction)
    for index,(event,row) in enumerate(zip(events,actual)):
        forcing=event['forcing']; dt=F(forcing['duration_seconds'])
        if (row['event_id']!=event['event_id'] or row['month_id']!=event['month_id']
                or event['layer_id']!=initial['layer_id'] or event['support_id']!=initial['support_id']): raise ValueError('carbon event layer/support differs')
        if row['status']!='MODELLED':
            if stopped and row['status'] not in ('NOT_ADVANCED_PRIOR_GAP','NOT_ADVANCED_STOPPED'): raise ValueError('carbon state resumed through unresolved/stopped event')
            if not stopped and row['status'] not in ('UNKNOWN','OUTSIDE_REGIME','NUMERICAL_FAILURE','NOT_ADVANCED_STOPPED'): raise ValueError('unrecognised incomplete carbon event')
            stopped=True; continue
        if stopped or pool(row['initial_state'])!=state: raise ValueError('organic pools reset or skipped between intervals')
        if (F(row['start_seconds_in_year'])!=elapsed or F(row['duration_seconds'])!=dt
                or F(row['represented_duration_residual_s'])!=F(float(dt))-dt
                or row['moisture_hold']!=event['moisture_hold'] or row['water_sample_seconds_in_year']!=event['water_sample_seconds_in_year']):
            raise ValueError('carbon interval/sample chronology differs')
        hold=event['moisture_hold']; timestamp=event['water_sample_seconds_in_year']
        if (hold=='EVENT_START_SAMPLE_HELD' and F(timestamp)!=elapsed
                or hold=='EVENT_END_SAMPLE_HELD' and F(timestamp)!=elapsed+dt
                or hold=='EXPLICIT_INTERVAL_VALUE_HELD' and timestamp is not None or hold=='UNKNOWN'):
            raise ValueError('carbon sample incorrectly described as actual interval mean')
        produced=row['producer_result']; after=produced['state']
        if (produced['schema']!='diadem.organic-carbon-snapshot.r7' or produced['status']!='MODELLED'
                or produced['layer_id']!=initial['layer_id'] or produced['support_id']!=initial['support_id']
                or any(after[k]!=initial[k] for k in ('layer_id','support_id'))
                or F(after['elapsed_seconds'])!=F(state['elapsed_seconds'])+dt
                or len(produced['segments'])!=1 or produced['segments'][0]['forcing']!=forcing):
            raise ValueError('actual retained organic producer/support/clock differs')
        supplied=(F(forcing['fast_litter_carbon_kg_m2_s'])+F(forcing['slow_litter_carbon_kg_m2_s']))*dt
        before=stock(state); final=stock(after); export=F(produced['carbon']['exported_atmospheric_carbon_kg_m2'])
        if export<0 or before+supplied!=final+export: raise ValueError('independent event carbon conservation failed')
        expected={'initial_kg_m2':before,'input_kg_m2':supplied,'final_kg_m2':final,'exported_atmospheric_carbon_kg_m2':export,'residual_kg_m2':F()}
        if any(F(produced['carbon'][k])!=v for k,v in expected.items()): raise ValueError('event carbon ledger differs from actual pools/litter')
        expected={'initial_kg_m2':before/fraction,'input_kg_m2':supplied/fraction,'final_kg_m2':final/fraction,
            'decomposed_dry_matter_origin_kg_m2':export/fraction,'residual_kg_m2':F(),'carbon_fraction_dry_matter':fraction}
        if (any(F(produced['organic_dry_matter'][k])!=v for k,v in expected.items())
                or F(produced['final_organic_carbon_kg_m2'])!=final or F(produced['final_organic_dry_mass_kg_m2'])!=final/fraction):
            raise ValueError('dry-origin mass or organic totals differ from explicit carbon fraction')
        segment=produced['segments'][0]
        for key,value in (('start_seconds',F(state['elapsed_seconds'])),('duration_seconds',dt),('initial_carbon_kg_m2',before),
                ('input_carbon_kg_m2',supplied),('final_carbon_kg_m2',final),('exported_atmospheric_carbon_kg_m2',export),('residual_kg_m2',F())):
            if F(segment[key])!=value: raise ValueError('actual organic segment ledger differs')
        rows.append(row); state=after; elapsed+=dt
    if product['completed_events']!=len(rows): raise ValueError('accepted organic cursor differs')
    def aggregate(value,selected,start,end,dt):
        if (F(value['duration_seconds'])!=dt or pool(value['initial_state'])!=start or pool(value['end_state'])!=end
                or value['geometry_feedback']!='NOT_APPLIED_DIAGNOSTIC_ONLY'): raise ValueError('carbon aggregate support/endpoints differ')
        supplied=sum((F(r['producer_result']['carbon']['input_kg_m2']) for r in selected),F())
        export=sum((F(r['producer_result']['carbon']['exported_atmospheric_carbon_kg_m2']) for r in selected),F())
        expected={'initial':stock(start),'input':supplied,'final':stock(end),'exported_carbon_origin':export,'residual':F()}
        if stock(start)+supplied!=stock(end)+export or any(F(value['carbon_kg_m2'][k])!=v for k,v in expected.items()): raise ValueError('independent accumulated carbon budget differs')
        dry={('decomposed_origin' if k=='exported_carbon_origin' else k):v/fraction for k,v in expected.items()}
        if any(F(value['dry_origin_kg_m2'][k])!=v for k,v in dry.items()): raise ValueError('accumulated dry-origin budget differs')
    months=0
    for month,dt in enumerate(durations,1):
        selected=[r for r in rows if r['month_id']==month]; expected=[e for e in events if e['month_id']==month]; value=product['months'][str(month)]
        if len(selected)==len(expected):
            if value['status']!='MODELLED' or value['month_id']!=month: raise ValueError('accepted carbon month status differs')
            aggregate(value,selected,pool(selected[0]['initial_state']),selected[-1]['producer_result']['state'],dt); months+=1
        elif any(value[k] is not None for k in ('carbon_kg_m2','dry_origin_kg_m2','end_state')): raise ValueError('incomplete carbon month gained accepted totals/state')
    if product['completed_months']!=months: raise ValueError('carbon completed month cursor differs')
    if not stopped:
        if (product['status']!='MODELLED_SEASONAL_CARBON_DIAGNOSTIC' or elapsed!=year or pool(product['final_state'])!=state): raise ValueError('complete carbon year boundary differs')
        aggregate(product['annual'],rows,initial,state,year)
    elif (product['status'] not in ('UNKNOWN','OUTSIDE_REGIME','NUMERICAL_FAILURE','STOPPED')
            or product['annual'] is not None or product['final_state'] is not None): raise ValueError('incomplete carbon year promoted to final totals')
    checkpoint=product['checkpoint']
    if checkpoint is not None:
        expected={'schema':'diadem.seasonal-organic-carbon-checkpoint.r10','inputs_sha256':product['inputs_sha256'],
            'completed_events':len(rows),'elapsed_seconds_in_year':str(elapsed),'state':checkpoint['state'],'accepted_prefix_sha256':sha(encoded(rows))}
        if (pool(checkpoint['state'])!=state or checkpoint!={**expected,'checkpoint_sha256':sha(encoded(expected))}): raise ValueError('saved carbon prefix/state identity differs')
    return {'status':product['status'],'completed_events':len(rows),'completed_months':months,
        'elapsed_seconds_in_year':str(elapsed),'geometry_feedback':'NOT_APPLIED_DIAGNOSTIC_ONLY',
        'annual':product['annual']}


def validate_hydraulic_checkpoint(product):
    """Cross-check the public event checkpoint against its actual accepted prefix."""
    cp=product['checkpoint']; inputs=product['inputs']; saved=cp['state']; events=inputs['events']
    if (set(cp)!={'schema','source_binding_sha256','inputs_sha256','state_sha256','state'}
            or cp['schema']!='diadem.seasonal-layered-water-checkpoint.r10'
            or cp['inputs_sha256']!=product['inputs_sha256'] or cp['source_binding_sha256']!=inputs['source_binding_sha256']
            or product['source_binding_sha256']!=inputs['source_binding_sha256'] or product['scenario_id']!=inputs['scenario_id']
            or cp['state_sha256']!=sha(encoded(saved))): raise ValueError('seasonal event checkpoint source/state binding differs')
    expected_fields={'completed_events','elapsed_seconds_in_year','continuing_state','accepted_event_rows',
        'completed_months','month_summaries','accumulated_ledger_m','last_completed_event_id','next_event_id'}
    if set(saved)!=expected_fields: raise ValueError('exact seasonal checkpoint state required')
    count=saved['completed_events']; rows=saved['accepted_event_rows']
    if (type(count) is not int or not 0<=count<=len(events) or count!=product['completed_events'] or len(rows)!=count
            or rows!=product['events'][:count] or any(row['status']!='MODELLED' for row in rows)):
        raise ValueError('seasonal checkpoint accepted prefix differs')
    elapsed=sum((F(e['duration_seconds']) for e in events[:count]),F())
    current=rows[-1]['solver_result']['state'] if rows else product['initial_state']
    summaries={k:r for k,r in product['months'].items() if r['status']=='MODELLED'}
    if (F(saved['elapsed_seconds_in_year'])!=elapsed or saved['continuing_state']!=current
            or saved['completed_months']!=len(summaries) or saved['month_summaries']!=summaries
            or saved['last_completed_event_id']!=(events[count-1]['event_id'] if count else None)
            or saved['next_event_id']!=(events[count]['event_id'] if count<len(events) else None)):
        raise ValueError('checkpoint clock, store, next-event or monthly continuity differs')
    if not rows:
        if saved['accumulated_ledger_m'] is not None: raise ValueError('zero-step checkpoint has invented accumulated fluxes')
    else:
        accumulated=saved['accumulated_ledger_m']
        for key in HYDRAULIC_LEDGER:
            if F(accumulated[key])!=sum((F(row['solver_result']['ledger'][key]) for row in rows),F()): raise ValueError('checkpoint accumulated flux differs')
        for target,key in (('supplied_liquid_input_m','liquid_input_m_s'),('supplied_potential_root_demand_m','potential_root_demand_m_s')):
            if F(accumulated[target])!=sum((F(e[key])*F(e['duration_seconds']) for e in events[:count]),F()): raise ValueError('checkpoint supplied forcing integral differs')
        layers=product['column']['layers']
        start=sum((F(theta(layer,head)*layer['thickness_m']) for layer,head in zip(layers,product['initial_state']['head_m'])),F())
        end=sum((F(theta(layer,head)*layer['thickness_m']) for layer,head in zip(layers,current['head_m'])),F())
        close(F(accumulated['initial_storage_m']),start,'checkpoint initial storage')
        close(F(accumulated['final_storage_m']),end,'checkpoint continuing storage')
        if product['annual'] is not None and accumulated!=product['annual']['ledger_m']: raise ValueError('final checkpoint differs from accepted year ledger')
    return {'completed_events':count,'elapsed_seconds_in_year':str(elapsed),'checkpoint_sha256':sha(encoded(cp))}


def validate_numerical_binding(product,expected=None):
    """A retained result schema does not identify the algorithm that ran."""
    record=product['inputs'].get('numerical_binding')
    names={'implementation','adapter','retained_solver','retained_hydraulic_kernel'}
    if type(record) is not dict or set(record)!=names:
        raise ValueError('explicit complete numerical implementation binding required')
    implementation=record['implementation']
    if implementation not in ('R6_RETAINED_NUMERICAL_EXECUTION','R10_SATURATION_BRANCH_RESOLUTION'):
        raise ValueError('unreviewed numerical implementation')
    paths={'adapter':HERE/'richards_numerics.py','retained_solver':TASK/'work/generator_upgrade_r6/soil_water.py',
        'retained_hydraulic_kernel':TASK/'work/generator_upgrade_r6/hydraulic_jacobian.py'}
    for name,path in paths.items():
        row=record[name]
        if name=='adapter' and implementation=='R6_RETAINED_NUMERICAL_EXECUTION':
            if row is not None: raise ValueError('retained numerical execution has no successor adapter')
            continue
        if (type(row) is not dict or set(row)!={'path','sha256'} or row['path']!=str(path)
                or type(row['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',row['sha256']) is None):
            raise ValueError('exact numerical source path/hash record required')
    if expected is not None and record!=expected:
        raise ValueError('executed numerical implementation differs from source-bound successor')
    for event in product['events']:
        solved=event.get('solver_result')
        if solved is None: continue
        if implementation=='R10_SATURATION_BRANCH_RESOLUTION':
            if solved.get('numerical_implementation')!=implementation or solved.get('numerical_binding')!=record:
                raise ValueError('event numerical execution differs from restart-bound inputs')
        elif 'numerical_implementation' in solved or 'numerical_binding' in solved:
            raise ValueError('retained solver result relabelled with a successor implementation')
    return record


def validate_internal_clock(solved):
    """Independently sum actual binary64 step supports, not rounded end times."""
    if 'numerical_implementation' not in solved:
        return {'status':'RETAINED_R6_NO_EXACT_INTERNAL_CLOCK_RECEIPT'}
    if solved['numerical_implementation']!='R10_SATURATION_BRANCH_RESOLUTION':
        raise ValueError('unknown numerical implementation cannot claim a legacy clock receipt')
    if solved.get('status')!='MODELLED':
        return {'status':'INCOMPLETE_RESULT_NO_ACCEPTED_INTERVAL_CERTIFICATION'}
    numerics=solved['numerics']; rows=numerics['accepted_steps_detail']
    count=numerics['accepted_steps']; duration=solved['forcing']['duration_seconds']
    if (type(count) is not int or count<1 or type(rows) is not list or len(rows)!=count
            or type(duration) not in (float,int) or not math.isfinite(duration) or duration<=0):
        raise ValueError('complete accepted internal-clock inventory required')
    def exact(value):
        if type(value) is not str:
            raise ValueError('explicit exact internal-clock rational string required')
        try: result=F(value)
        except (ValueError,ZeroDivisionError) as error:
            raise ValueError('invalid exact internal-clock rational') from error
        if str(result)!=value: raise ValueError('canonical exact internal-clock rational required')
        return result
    duration_exact=exact(numerics['forcing_duration_seconds_exact'])
    if duration_exact!=F(float(duration)):
        raise ValueError('exact forcing duration differs from supplied binary64 interval')
    clock=F()
    for row in rows:
        dt=row['dt_seconds']; displayed_end=row['end_seconds']
        if (type(dt) not in (float,int) or not math.isfinite(dt) or dt<=0
                or type(displayed_end) not in (float,int) or not math.isfinite(displayed_end)):
            raise ValueError('finite positive internal step support required')
        step=exact(row['dt_seconds_exact']); end=exact(row['end_seconds_exact'])
        if step!=F(float(dt)) or step<=0:
            raise ValueError('exact step duration differs from actual binary64 duration')
        if end!=clock+step or end>duration_exact or displayed_end!=float(end):
            raise ValueError('accepted exact internal clock reset, overrun or display mismatch')
        clock=end
    if exact(numerics['elapsed_seconds_exact'])!=clock or clock!=duration_exact:
        raise ValueError('accepted internal steps do not exactly fill forcing interval')
    return {'status':'EXACT_BINARY64_INTERVAL_PARTITION_CHECKED','accepted_steps':count,
        'duration_seconds_exact':str(clock)}


def validate_hydraulic_year(product):
    """Independent event/month/year chronology, retention, pressure and water budgets."""
    if product['schema']!='diadem.seasonal-layered-water.r10': raise ValueError('actual seasonal Richards product required')
    numerical=validate_numerical_binding(product)
    clocks=[validate_internal_clock(row['solver_result']) for row in product['events'] if row.get('solver_result') is not None]
    exact_clocks=[row for row in clocks if row['status']=='EXACT_BINARY64_INTERVAL_PARTITION_CHECKED']
    clock_summary={'exactly_partitioned_complete_events':len(exact_clocks),
        'accepted_steps_in_exact_partitions':sum(row['accepted_steps'] for row in exact_clocks),
        'retained_r6_events_without_exact_internal_receipts':sum(row['status']=='RETAINED_R6_NO_EXACT_INTERNAL_CLOCK_RECEIPT' for row in clocks)}
    inputs=product['inputs']; original=inputs['column']; column=dict(original,root_boundary_index=inputs['root_boundary_index'])
    if (product['inputs_sha256']!=sha(encoded(inputs)) or product['column']!=column
            or product['original_column_sha256']!=sha(encoded(original)) or product['column_sha256']!=sha(encoded(column))):
        raise ValueError('seasonal actual column/input binding differs')
    layers=column['layers']; count=len(layers); root=inputs['root_boundary_index']; calendar=inputs['calendar']
    durations=[F(value) for value in calendar['month_durations_seconds']]
    if len(durations)!=12 or any(value<=0 for value in durations): raise ValueError('complete positive physical calendar required')
    initial=dict(inputs['initial_state'],column_sha256=product['column_sha256'])
    if product['initial_state']!=initial or F(product['calendar_start_elapsed_seconds'])!=F(initial['elapsed_seconds']):
        raise ValueError('initial seasonal heads/time reset or rebound incorrectly')
    if F(product['root_boundary_depth_m'])!=sum((F(row['thickness_m']) for row in layers[:root]),F()):
        raise ValueError('actual root-face depth differs')
    events=inputs['events']; actual=product['events']
    if len(actual)!=len(events) or len({event['event_id'] for event in events})!=len(events): raise ValueError('seasonal event inventory differs')
    if [event['month_id'] for event in events]!=sorted(event['month_id'] for event in events): raise ValueError('seasonal event order differs')
    for month,dt in enumerate(durations,1):
        if sum((F(event['duration_seconds']) for event in events if event['month_id']==month),F())!=dt:
            raise ValueError('event durations do not fill the declared month')
    validate_hydraulic_checkpoint(product)
    if product['status']!='MODELLED_SEASONAL_HYDRAULICS':
        if product['status'] not in ('UNKNOWN','NUMERICAL_FAILURE','PARTIAL_SEASONAL_HYDRAULICS','NO_ADVANCE') or product['annual'] is not None or product['final_state'] is not None or product['partial_results_only'] is not True:
            raise ValueError('incomplete causal year promoted to final state/totals')
        seen_gap=False
        for event,row in zip(events,actual):
            if row['event_id']!=event['event_id'] or row['month_id']!=event['month_id']: raise ValueError('partial causal event identity differs')
            if seen_gap and row['status'] not in ('NOT_ADVANCED_PRIOR_GAP','NOT_ADVANCED_REQUESTED_STOP'): raise ValueError('causal suffix resumed after an unresolved event')
            if row['status'] in ('UNKNOWN','NUMERICAL_FAILURE','NOT_ADVANCED_REQUESTED_STOP'): seen_gap=True
        return {'status':product['status'],'annual_and_final_state':None,'numerical_implementation':numerical['implementation'],
            'internal_clock_checks':clock_summary}
    if (product['partial_results_only'] is not False or product['accumulated_budget_failure'] is not False
            or product['completed_events']!=len(events) or product['completed_months']!=12
            or set(product['months'])!={str(i) for i in range(1,13)}): raise ValueError('complete seasonal year counters differ')
    state=initial; elapsed=F(); start_states={}; end_states={}; grouped={i:[] for i in range(1,13)}
    rho=float(inputs['water_density_kg_m3']); gravity=float(inputs['gravity_m_s2'])
    tolerance=F(inputs['budget_atol_m']); time_tolerance=F(inputs['duration_atol_s'])
    def storage(state): return [F(theta(layer,h))*F(layer['thickness_m']) for layer,h in zip(layers,state['head_m'])]
    for event,row in zip(events,actual):
        month=event['month_id']; dt=F(event['duration_seconds']); start_states.setdefault(month,state)
        if (row['status']!='MODELLED' or row['event_id']!=event['event_id'] or row['month_id']!=month
                or F(row['start_seconds_in_year'])!=elapsed or F(row['duration_seconds'])!=dt
                or any(row[key]!=event[key] for key in ('vegetation_hypothesis_id','soil_thermal_regime','thermal_evidence','air_temperature_c'))
                or row['soil_thermal_regime']!='UNFROZEN_CONDITIONAL'):
            raise ValueError('causal seasonal event/hypothesis/thermal support differs')
        solved=row['solver_result']; after=solved['state']; ledger=solved['ledger']; forcing=solved['forcing']
        supplied=F(event['liquid_input_m_s'])*dt; demand=F(event['potential_root_demand_m_s'])*dt
        if (solved['schema']!='diadem.layered-richards.r6' or solved['status']!='MODELLED'
                or after['column_sha256']!=product['column_sha256'] or len(solved['layers'])!=count
                or solved['lower_boundary']!=event['boundary'] or solved['numerics']['controls']!=inputs['controls']
                or forcing!={'duration_seconds':float(dt),'surface_input_m_s':float(F(event['liquid_input_m_s'])),
                    'potential_et_m_s':float(F(event['potential_root_demand_m_s'])),'uptake':event['uptake'],
                    'evidence':event['evidence'],'source_status':event['source_status']}
                or solved['fluid']!={'water_density_kg_m3':rho,'gravity_m_s2':gravity}
                or F(row['supplied_liquid_input_m'])!=supplied or F(row['supplied_potential_root_demand_m'])!=demand):
            raise ValueError('actual R6 forcing/boundary/control/fluid join differs')
        expected_time=F(initial['elapsed_seconds'])+elapsed+dt
        if (F(row['duration_conversion_residual_s'])!=F(float(dt))-dt
                or F(row['cumulative_elapsed_residual_s'])!=F(after['elapsed_seconds'])-expected_time
                or abs(F(after['elapsed_seconds'])-expected_time)>time_tolerance): raise ValueError('seasonal represented clock drift differs')
        before_water=storage(state); final_water=[]; depth=0.
        if len(ledger['face_downward_m'])!=count+1 or len(ledger['face_upward_m'])!=count+1: raise ValueError('complete internal-face water ledger required')
        for index,(layer,output,head) in enumerate(zip(layers,solved['layers'],after['head_m'])):
            if output['layer_id']!=layer['layer_id'] or output['head_m']!=head: raise ValueError('actual layer/end-head identity differs')
            close(output['theta_m3_m3'],theta(layer,head),'retention water content')
            water=F(output['theta_m3_m3'])*F(layer['thickness_m']); final_water.append(water)
            if F(output['water_m3_m2_exact_represented'])!=water: raise ValueError('actual water-content/thickness storage differs')
            close(output['water_m3_m2'],float(water),'layer storage')
            close(output['pore_saturation'],output['theta_m3_m3']/layer['theta_s'],'physical pore saturation')
            close(output['signed_pore_pressure_pa'],rho*gravity*head,'signed current pore pressure')
            close(output['positive_pore_pressure_pa'],max(0,rho*gravity*head),'positive-only diagnostic pressure')
            for key,value in (('top_depth_m',depth),('centre_depth_m',depth+layer['thickness_m']/2),('bottom_depth_m',depth+layer['thickness_m'])): close(output[key],value,'layer geometry')
            depth+=layer['thickness_m']
            residual=water-before_water[index]-F(ledger['face_downward_m'][index])+F(ledger['face_upward_m'][index])+F(ledger['face_downward_m'][index+1])-F(ledger['face_upward_m'][index+1])+F(output['et_m'])
            if abs(residual)>tolerance+F(1e-12): raise ValueError('independent layer/face/uptake conservation failed')
        residual=sum(before_water,F())+supplied+F(ledger['bottom_upward_m'])-sum(final_water,F())-F(ledger['bottom_downward_m'])-F(ledger['actual_et_m'])-F(ledger['surface_runoff_m'])
        if abs(residual)>tolerance+F(1e-12): raise ValueError('independent event water conservation failed')
        for key,value in (('bottom_downward_m',ledger['face_downward_m'][-1]),('bottom_upward_m',ledger['face_upward_m'][-1]),
                ('root_zone_gross_downward_m',ledger['face_downward_m'][root]),('root_zone_upward_capillary_m',ledger['face_upward_m'][root])):
            if ledger[key]!=value: raise ValueError('bottom/root gross physical face differs')
        grouped[month].append(row); elapsed+=dt; state=after; end_states[month]=state
    if product['final_state']!=state or elapsed!=sum(durations,F()): raise ValueError('whole-year final state/time differs')
    def aggregate(value,rows,start,end,duration):
        ledger=value['ledger_m']; start_storage=storage(start); end_storage=storage(end)
        if F(value['duration_seconds'])!=duration or value['end_state']!=end: raise ValueError('interval end state/time mislabelled')
        if value['end_layers']!=[{k:v for k,v in row.items() if k not in ('et_m','water_residual_m')} for row in rows[-1]['solver_result']['layers']]:
            raise ValueError('interval-end layers replaced by last-event flux or fictitious time mean')
        for key in HYDRAULIC_LEDGER:
            if F(ledger[key])!=sum((F(row['solver_result']['ledger'][key]) for row in rows),F()): raise ValueError('integrated seasonal flux sum differs')
        supplied=sum((F(row['supplied_liquid_input_m']) for row in rows),F()); demand=sum((F(row['supplied_potential_root_demand_m']) for row in rows),F())
        if F(ledger['supplied_liquid_input_m'])!=supplied or F(ledger['supplied_potential_root_demand_m'])!=demand:
            raise ValueError('integrated supplied forcing differs')
        close(F(ledger['initial_storage_m']),sum(start_storage,F()),'interval initial physical storage')
        close(F(ledger['final_storage_m']),sum(end_storage,F()),'interval final physical storage')
        residual=sum(start_storage,F())+supplied+F(ledger['bottom_upward_m'])-sum(end_storage,F())-F(ledger['bottom_downward_m'])-F(ledger['actual_et_m'])-F(ledger['surface_runoff_m'])
        if abs(residual)>tolerance+F(1e-12): raise ValueError('independent accumulated seasonal water balance failed')
        close(F(ledger['water_residual_m']),residual,'interval water residual')
        for kind in ('downward','upward'):
            key='face_'+kind+'_m'; expected=[sum((F(row['solver_result']['ledger'][key][i]) for row in rows),F()) for i in range(count+1)]
            if [F(v) for v in ledger[key]]!=expected: raise ValueError('seasonal internal-face gross accounting differs')
        uptake=[sum((F(row['solver_result']['layers'][i]['et_m']) for row in rows),F()) for i in range(count)]
        if [F(v) for v in ledger['layer_actual_et_m']]!=uptake: raise ValueError('seasonal layer uptake accounting differs')
        for i in range(count):
            expected=end_storage[i]-start_storage[i]-F(ledger['face_downward_m'][i])+F(ledger['face_upward_m'][i])+F(ledger['face_downward_m'][i+1])-F(ledger['face_upward_m'][i+1])+uptake[i]
            close(F(ledger['layer_water_residual_m'][i]),expected,'accumulated layer residual')
            if abs(expected)>tolerance+F(1e-12): raise ValueError('accumulated layer water conservation failed')
        for key,expected in (('liquid_representation_residual_m',F(ledger['surface_input_m'])-supplied),('demand_representation_residual_m',F(ledger['potential_et_m'])-demand)):
            if F(ledger[key])!=expected: raise ValueError('represented forcing conversion residual differs')
        if (F(ledger['bottom_net_downward_m'])!=F(ledger['bottom_downward_m'])-F(ledger['bottom_upward_m'])
                or F(ledger['storage_change_m'])!=F(ledger['final_storage_m'])-F(ledger['initial_storage_m'])):
            raise ValueError('net boundary transfer or initial-value storage drift differs')
        if (F(value['root_zone_gross_downward_mm'])!=1000*F(ledger['root_zone_gross_downward_m'])
                or F(value['root_zone_upward_capillary_mm'])!=1000*F(ledger['root_zone_upward_capillary_m'])): raise ValueError('gross root-zone mm conversion differs')
    for month in range(1,13):
        value=product['months'][str(month)]
        if value['status']!='MODELLED' or value['month_id']!=month: raise ValueError('monthly water status/identity differs')
        aggregate(value,grouped[month],start_states[month],end_states[month],durations[month-1])
    aggregate(product['annual'],actual,initial,state,elapsed)
    return {'status':product['status'],'events':len(actual),'months':12,'duration_seconds':str(elapsed),
        'numerical_implementation':numerical['implementation'],
        'internal_clock_checks':clock_summary,
        'actual_et_m':product['annual']['ledger_m']['actual_et_m'],'water_residual_m':product['annual']['ledger_m']['water_residual_m'],
        'periodic_hydraulic_state_claim':False,'soil_freezing_modelled':False}


def artifacts(bundle,root):
    root.mkdir(exist_ok=False); s=bundle.storage
    s.write_json(root/'recipe.json',bundle.reference.recipe(bundle)); recipe=s.read_json(root/'recipe.json')
    durations={}
    def timed(label,call):
        start=time.perf_counter(); result=call(); durations[label]=time.perf_counter()-start
        return result
    # Each actual parent retains the same strict 8 MiB envelope; neither is embedded.
    s.write_json(root/'parent-result.json',timed('actual_r9_parent',lambda:bundle.parent.run(recipe['parent_recipe'])))
    s.write_json(root/'physical-parent-result.json',timed('actual_r8_parent',lambda:bundle.parent.parent.run(recipe['parent_recipe']['parent_recipe'])))
    parent=s.read_json(root/'parent-result.json'); physical=s.read_json(root/'physical-parent-result.json')
    if parent['parent_result_sha256']!=sha(s.encoded(physical)): raise ValueError('separate actual R8 replay differs from R9 physical parent')
    full=timed('full',lambda:bundle.run(recipe))
    s.write_json(root/'full-result.json',full); s.write_json(root/'full-checkpoint.json',bundle.checkpoint(full))
    # Preserve a failed actual trajectory and reject its scientific claim before
    # attempting separate restart acceptance. No incomplete result is a seal.
    checks=validate_products(full,bundle,recipe,parent,physical)
    stop=timed('stop',lambda:bundle.run(recipe,stop_after=1))
    s.write_json(root/'stop-result.json',stop); s.write_json(root/'stop-checkpoint.json',bundle.checkpoint(stop))
    restart=timed('saved_checkpoint_restart',lambda:bundle.run(recipe,resume=s.read_json(root/'stop-checkpoint.json')))
    s.write_json(root/'restart-result.json',restart); s.write_json(root/'restart-checkpoint.json',bundle.checkpoint(restart))
    record={'path':str(root),'files':{name:sha((root/name).read_bytes()) for name in ARTIFACT_NAMES},
        'reference_sha256':sha(s.encoded(full)),'parent_result_sha256':sha(s.encoded(parent)),
        'physical_parent_result_sha256':sha(s.encoded(physical)),
        'elapsed_wall_seconds':durations,
        'scientific_checks':checks}
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
    full=values['full-result.json']; recipe=values['recipe.json']; parent=values['parent-result.json']; physical=values['physical-parent-result.json']
    if full!=values['restart-result.json'] or values['full-checkpoint.json']!=values['restart-checkpoint.json']:
        raise ValueError('actual full/restart state differs')
    validate_envelope(full,recipe,bundle,parent,physical,complete=True)
    validate_envelope(values['stop-result.json'],recipe,bundle,parent,physical,complete=False)
    if (record['reference_sha256']!=sha(s.encoded(full)) or record['parent_result_sha256']!=sha(s.encoded(parent))
            or record['physical_parent_result_sha256']!=sha(s.encoded(physical))):
        raise ValueError('actual reference/parent digest differs')
    for stage in ('full','stop','restart'):
        if values[stage+'-checkpoint.json']!=bundle.checkpoint(values[stage+'-result.json']):
            raise ValueError('saved checkpoint identity differs')
    if record.get('scientific_checks')!=validate_products(full,bundle,recipe,parent,physical): raise ValueError('scientific readback differs')
    return full


def private_executions(bundle):
    records={}; current=bundle
    for label in ('r10','r9','r8','r7','r6'):
        records[label]=dict(current.graph.executed)
        if label!='r6': current=current.parent
    return records


def validate_private_executions(records,executed,bundle,helper):
    if type(records) is not dict or set(records)!={'r10','r9','r8','r7','r6'}:
        raise ValueError('complete actual private graph chain required')
    expected=source_map(bundle.identity,helper)
    observed={helper.canonical(k):v for k,v in executed.items()}
    graphs={'r10':bundle.graph,'r9':bundle.parent.graph,'r8':bundle.parent.parent.graph,'r7':bundle.parent.parent.parent.graph,'r6':bundle.parent.parent.parent.parent.graph}
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


DIAGNOSTIC_YEARS=frozenset(('full','month_boundary_stop','month_boundary_resume','swe_depletion_stop',
    'swe_depletion_resume','half_daily_maximum_step'))
NUMERICAL_YEARS=frozenset(('DIAGNOSTIC_DDF4_SIGMA4/upper','HIGH_DDF5_SIGMA6/upper','LOW_DDF3_SIGMA2/upper',
    'DIAGNOSTIC_DDF4_SIGMA4/upper/half_daily','lower_original','lower_corrected','upper_depletion_stop','upper_depletion_resume'))


def collect_diagnostics(bundle,path):
    """Retain executed test experiments without rerunning their numerical solvers."""
    hydraulic=sys.modules['work.generator_upgrade_r10.test_hydraulics'].ACTUAL_YEAR_RECEIPTS
    numerical=sys.modules['work.generator_upgrade_r10.test_richards_numerics'].ACTUAL_NUMERICAL_RECEIPTS
    carbon=sys.modules['work.generator_upgrade_r10.test_seasonal_carbon'].SeasonalCarbonTests.refinement_products
    if set(hydraulic)!=DIAGNOSTIC_YEARS: raise ValueError('actual tested hydraulic restart/refinement inventory incomplete')
    if set(numerical)!=NUMERICAL_YEARS: raise ValueError('actual tested numerical successor inventory incomplete')
    packing=bundle.graph.load('work.generator_upgrade_r10.payloads')
    value={'schema':'diadem.seasonal-executed-diagnostics.r10','source_sha256':bundle.source_sha256,
        'hydraulic_years':{name:packing.pack(product) for name,product in hydraulic.items()},
        'numerical_years':{name:packing.pack(product) for name,product in numerical.items()},
        'carbon_refinement':carbon,'scope':'actual already-executed named tests; saved event restarts and bounded diagnostic refinement, not performance measurement'}
    bundle.storage.write_json(path,value)
    record={'path':str(path),'sha256':sha(path.read_bytes())}
    record['checks']=validate_diagnostics(record,bundle)
    return record


def validate_diagnostics(record,bundle):
    path=bundle.storage.plain_path(record['path']); value=bundle.storage.read_json(path)
    if (sha(path.read_bytes())!=record['sha256'] or value['schema']!='diadem.seasonal-executed-diagnostics.r10'
            or value['source_sha256']!=bundle.source_sha256 or set(value['hydraulic_years'])!=DIAGNOSTIC_YEARS
            or set(value['numerical_years'])!=NUMERICAL_YEARS):
        raise ValueError('executed scientific diagnostic source/readback inventory differs')
    years={key:decode_payload(row,bundle) for key,row in value['hydraulic_years'].items()}
    numerical={key:decode_payload(row,bundle) for key,row in value['numerical_years'].items()}
    numerical_checks=validate_numerical_year_receipts(numerical,bundle)
    summaries={key:validate_hydraulic_year(row) for key,row in years.items()}
    original=years['full']; fine=years['half_daily_maximum_step']; controls=original['inputs']['controls']
    if original!=years['month_boundary_resume'] or original!=years['swe_depletion_resume']:
        raise ValueError('actual saved event-boundary restart differs from full hydraulic year')
    for label,same_month in (('month_boundary_stop',False),('swe_depletion_stop',True)):
        product=years[label]; cursor=product['completed_events']; events=original['inputs']['events']
        if (not 0<cursor<len(events) or product['status']!='PARTIAL_SEASONAL_HYDRAULICS'
                or product['inputs']!=original['inputs'] or product['events'][:cursor]!=original['events'][:cursor]
                or (events[cursor-1]['month_id']==events[cursor]['month_id']) is not same_month):
            raise ValueError('restart did not preserve actual month/depletion event boundary')
    expected=deepcopy(original['inputs']); expected['controls']['max_dt_s']=43200.
    if controls['max_dt_s']!=86400. or fine['inputs']!=expected: raise ValueError('hydraulic refinement changed more than explicit maximum time step')
    differences={}
    for i,(a,b) in enumerate(zip(original['final_state']['head_m'],fine['final_state']['head_m'])):
        tolerance=controls['head_atol_m']+controls['relative_tolerance']*max(abs(a),abs(b))
        if abs(a-b)>tolerance: raise ValueError('actual daily/half-daily head refinement exceeds declared tolerance')
        differences['head_'+str(i)+'_m']=abs(a-b)
    for key in ('actual_et_m','surface_runoff_m','root_zone_gross_downward_m','root_zone_upward_capillary_m'):
        a=float(F(original['annual']['ledger_m'][key])); b=float(F(fine['annual']['ledger_m'][key]))
        tolerance=controls['flux_integral_atol_m']+controls['relative_tolerance']*max(abs(a),abs(b))
        if abs(a-b)>tolerance: raise ValueError('actual daily/half-daily integrated water refinement exceeds declared tolerance')
        differences[key]=abs(a-b)
    carbon=value['carbon_refinement']; exact=2*math.exp(-.001*(.2*365+.6*365/2))
    if carbon['subdivisions_per_month']!=[1,2,4] or carbon['predeclared_first_order_band']!=[1.95,2.05]:
        raise ValueError('independent carbon refinement supports or predeclared band differ')
    close(carbon['independent_exact_fast_carbon_kg_m2'],exact,'scalar variable-moisture carbon oracle')
    observed=carbon['actual_fast_carbon_kg_m2']
    if type(observed) is not list or len(observed)!=3: raise ValueError('all actual carbon refinement results required')
    errors=[abs(v-exact) for v in observed]
    if any(v<=0 for v in errors): raise ValueError('carbon refinement has no resolved positive errors')
    ratios=[errors[i]/errors[i+1] for i in (0,1)]
    if len(carbon['absolute_errors_kg_m2'])!=3 or len(carbon['error_ratios'])!=2: raise ValueError('complete scalar refinement error inventory required')
    for actual,expected in zip(carbon['absolute_errors_kg_m2'],errors): close(actual,expected,'carbon refinement error',atol=1e-15)
    for actual,expected in zip(carbon['error_ratios'],ratios): close(actual,expected,'carbon refinement ratio')
    if any(not 1.95<v<2.05 for v in ratios): raise ValueError('held-WFPS carbon diagnostic lost stated first-order scalar convergence')
    checks={'saved_event_restart_parity':'EXACT','hydraulic_years':summaries,'daily_half_daily_differences':differences,
        'numerical_successor':numerical_checks,
        'carbon_scalar_refinement':carbon,'scope':'separate fixed-geometry diagnostics; no fully coupled soil/thermal convergence claim'}
    if 'checks' in record and record['checks']!=checks: raise ValueError('saved scientific diagnostic checks differ')
    return checks


def validate_numerical_year_receipts(years,bundle):
    """Recheck saved successful saturation cases, not their test assertion counts."""
    if type(years) is not dict or set(years)!=NUMERICAL_YEARS:
        raise ValueError('complete actual numerical successor experiment inventory required')
    expected=bundle.identity['numerical_implementation']['runtime_binding']
    retained=deepcopy(expected); retained.update(implementation='R6_RETAINED_NUMERICAL_EXECUTION',adapter=None)
    checks={}
    for name,year in years.items():
        validate_numerical_binding(year,retained if name=='lower_original' else expected)
        if year['inputs']['source_binding_sha256']!=bundle.source_sha256:
            raise ValueError('numerical experiment belongs to different source capture')
        checks[name]=validate_hydraulic_year(year)
        status='PARTIAL_SEASONAL_HYDRAULICS' if name=='upper_depletion_stop' else 'MODELLED_SEASONAL_HYDRAULICS'
        if year['status']!=status: raise ValueError('numerical successor experiment did not complete its declared support')
    coarse=years['DIAGNOSTIC_DDF4_SIGMA4/upper']; fine=years['DIAGNOSTIC_DDF4_SIGMA4/upper/half_daily']
    fine_inputs=deepcopy(coarse['inputs']); fine_inputs['controls']['max_dt_s']=43200.
    if coarse['inputs']['controls']['max_dt_s']!=86400. or fine['inputs']!=fine_inputs:
        raise ValueError('upper refinement changed more than the declared time-step ceiling')
    original=years['lower_original']; corrected=years['lower_corrected']; corrected_inputs=deepcopy(original['inputs'])
    corrected_inputs['numerical_binding']=expected
    if corrected['inputs']!=corrected_inputs:
        raise ValueError('lower predecessor comparison changed physical inputs or controls')
    differences={}
    for name,left,right in (('upper_daily_half_daily',coarse,fine),('lower_retained_successor',original,corrected)):
        controls=left['inputs']['controls']; difference={}
        for i,(a,b) in enumerate(zip(left['final_state']['head_m'],right['final_state']['head_m'])):
            if abs(a-b)>controls['head_atol_m']+controls['relative_tolerance']*max(abs(a),abs(b)):
                raise ValueError('numerical comparison exceeds unchanged head allowance')
            difference['head_'+str(i)+'_m']=abs(a-b)
        for key in ('surface_runoff_m','actual_et_m','root_zone_gross_downward_m','root_zone_upward_capillary_m'):
            a=float(F(left['annual']['ledger_m'][key])); b=float(F(right['annual']['ledger_m'][key]))
            if abs(a-b)>controls['flux_integral_atol_m']+controls['relative_tolerance']*max(abs(a),abs(b)):
                raise ValueError('numerical comparison exceeds unchanged gross/integrated water allowance')
            difference[key]=abs(a-b)
        differences[name]=difference
    stopped=years['upper_depletion_stop']; resumed=years['upper_depletion_resume']; cursor=stopped['completed_events']
    events=coarse['inputs']['events']
    if (resumed!=coarse or not 0<cursor<len(events) or stopped['inputs']!=coarse['inputs']
            or stopped['events'][:cursor]!=coarse['events'][:cursor]
            or events[cursor-1]['month_id']!=events[cursor]['month_id']):
        raise ValueError('actual upper snow-depletion saved checkpoint did not preserve exact continuation')
    return {'experiments':checks,'comparisons':differences,'upper_saved_depletion_restart':'EXACT',
        'scope':'three upper conditional years, same-input lower comparison and bounded upper refinement; unchanged accuracy controls'}


def worker(path,parent_path,mode):
    start=time.perf_counter(); helper,capture=install()
    from work.generator_upgrade_r10 import binding
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
        record['scientific_diagnostics']=collect_diagnostics(bundle,path.parent/(path.stem+'-scientific-diagnostics.json'))
        record['artifacts']=artifacts(bundle,path.parent/(path.stem+'-reference'))
        stable(bundle,helper,capture,required=True)
        records=private_executions(bundle)
        validate_private_executions(records,capture.executed,bundle,helper)
        record.update(status='PASS',private_dependency_executions=records)
    except Exception as error:
        record['failure']=str(error)
    record.update(executed_source_hashes=dict(capture.executed),worker_duration_seconds=time.perf_counter()-start,
        scope='bounded actual seasonal-world scientific-source/restart verification; no optimisation')
    bundle.storage.write_json(path,record); capture.active=False
    print(json.dumps({'status':record['status'],'tests':len(ids),'actual_mode':mode}),flush=True)
    return 0 if record['status']=='PASS' else 1


def validate_worker(record,bundle,helper,mode):
    validate_worker_header(record,bundle,mode); validate_tests(record['tests'])
    validate_execution(record['executed_source_hashes'],bundle.identity,helper)
    if record['external_reference_sources']!=validate_external_sources(bundle): raise ValueError('worker external binding differs')
    validate_private_executions(record['private_dependency_executions'],record['executed_source_hashes'],bundle,helper)
    validate_diagnostics(record['scientific_diagnostics'],bundle)
    return validate_artifacts(record['artifacts'],bundle)


def final(run_id):
    if type(run_id) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,47}',run_id):
        raise ValueError('bounded new run ID required')
    helper,capture=install()
    from work.generator_upgrade_r10 import binding
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
    if records[0]['scientific_diagnostics']['sha256']!=records[1]['scientific_diagnostics']['sha256']:
        raise ValueError('normal/-OO actual event-restart/refinement diagnostics differ')
    stable(bundle,helper,capture)
    seal={'schema':'diadem.seasonal-world-verification.r10','status':VERIFIED_STATUS,
        'source_identity':bundle.identity,'source_sha256':bundle.source_sha256,'source_snapshot':bundle.identity['r10_sources'],
        'test_ids':ids,'test_count_per_mode':len(ids),'inventory_sha256':inventory_digest(ids),
        'workers':{label:{'path':str(root/(label+'-worker.json')),'sha256':sha((root/(label+'-worker.json')).read_bytes())} for label in ('n','o')},
        'normal_oo_parity':'EXACT_SCIENTIFIC_RESULT_AND_CHECKPOINT_PASS','parent_optimisation_flag':sys.flags.optimize,
        'actual_worker_flags':[r['optimisation_flag'] for r in records],
        'external_reference_sources':validate_external_sources(bundle),
        'production_installed':False,'canon_changed':False,'optimisation_performed':False,
        'scope':'bounded current seasonal climate/hydraulic/plant reference with explicit missing downstream mechanisms; no world production'}
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
    raw=Path(__file__).read_bytes(); namespace={'__file__':__file__,'__name__':'_r10_fresh_verification_entry'}
    exec(compile(raw,__file__,'exec',dont_inherit=True),namespace)
    namespace['ENTRY_SOURCE_SHA256']=sha(raw)
    raise SystemExit(namespace['main']())
