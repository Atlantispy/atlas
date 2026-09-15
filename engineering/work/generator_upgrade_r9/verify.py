"""Source-locked dual-mode R9 verification, with an explicit pending release gate.

No predecessor acceptance suite is counted as new R9 testing. Wall times are
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
OUTPUT_ROOT=TASK/'outputs/generator-upgrade-r9'
SUITES=('test_binding','test_sources','test_owner_inputs','test_spatial','test_stock','test_phases','test_upstream','test_pipeline','test_verification')
EXPECTED_COUNT=298
INVENTORY_SHA256='85a1239c1c035be59080860fbfcf1c756047450e4791a7915dd3ddc16a3fe9f5'
PRODUCT_CONTRACT_READY=True
ENTRY_SOURCE_SHA256=None
R4_SEAL_SHA256='f7382693a5284ebf111dc8a0622e5811440ccc7e2b546047943462b849926996'
RESULT_SCHEMA='diadem.species-spatial-result.r9'
VERIFIED_STATUS='BOUNDED_SPECIES_SPATIAL_ENGINE_VERIFIED_WITH_INPUT_GAPS'
ARTIFACT_NAMES=frozenset(('recipe.json','full-result.json','stop-result.json','restart-result.json',
    'stop-checkpoint.json','full-checkpoint.json','restart-checkpoint.json','parent-result.json'))


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
    module=types.ModuleType('_r9_exact_verification_utilities'); module.__file__=str(path)
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
    r8=identity['retained_source_identity']; r7=r8['retained_source_identity']
    r6=r7['retained_source_identity']; r5=r6['retained_source_identity']
    result=helper.source_map(r5['retained_source_identity'])
    maps=(r5['r5_sources'],r6['r6_sources'],r7['r7_sources'],r7['external_test_reference_sources'],
        r8['r8_sources'],r8['external_reference_sources'],identity['r9_sources'],external_sources(identity))
    for mapping in maps:
        for path,digest in mapping.items():
            key=helper.canonical(path)
            if key in result and result[key]!=digest: raise ValueError('conflicting source binding')
            result[key]=digest
    return result


def external_sources(identity):
    """Both source providers must contribute explicit nonempty bound evidence."""
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
    names=(*SUITES,'binding','provenance','pipeline','reference','sources','owner_inputs','spatial','stock','phases','upstream','verify')
    return [HERE/(name+'.py') for name in names]+[
        TASK/('work/generator_upgrade_'+version+'/'+name+'.py') for version,name in (
        ('r8','binding'),('r8','provenance'),('r8','pipeline'),('r8','biomes'),('r8','vegetation'),('r8','seasonal'),('r8','verify'),
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
    if bundle.identity['r9_sources'].get(str(HERE/'verify.py'))!=ENTRY_SOURCE_SHA256:
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
    suite=loader.loadTestsFromNames(['work.generator_upgrade_r9.'+name for name in SUITES])
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



def validate_envelope(result,recipe,bundle,parent,*,complete):
    """Identity/unit cursor only; not a biological-coverage certificate."""
    s=bundle.storage; parent_sha=sha(s.encoded(parent))
    if (result.get('schema')!=RESULT_SCHEMA or result.get('source_sha256')!=bundle.source_sha256
            or result.get('recipe_sha256')!=sha(s.encoded(recipe))
            or parent.get('schema')!='diadem.biomes-vegetation-result.r8'
            or parent.get('source_sha256')!=bundle.parent.source_sha256
            or parent.get('recipe_sha256')!=sha(s.encoded(recipe['parent_recipe']))
            or result.get('parent_result_sha256')!=parent_sha):
        raise ValueError('actual recipe/source/separately saved parent binding required')
    state=result['state']
    if set(state)!={'completed_units','parent_result_sha256','environment_sha256','results'}:
        raise ValueError('exact bounded unit-boundary state required')
    if state['parent_result_sha256']!=parent_sha or state['environment_sha256']!=sha(s.encoded(result['environment'])):
        raise ValueError('actual parent/environment support identity differs')
    rows=state['results']
    if type(rows) is not dict or any(type(organisms) is not dict for organisms in rows.values()):
        raise ValueError('explicit scenario/organism/season results required')
    units=[]
    for scenario,organisms in rows.items():
        for organism,seasons in organisms.items():
            if type(seasons) is not dict: raise ValueError('explicit season result map required')
            units.extend((scenario,organism,season) for season in seasons)
    cursor=state['completed_units']
    ordered=sorted((scenario,organism,season['season_id']) for scenario in result['environment']['scenarios']
        for organism in recipe['organisms'] for season in recipe['seasons'])
    if (type(cursor) is not int or cursor!=len(units) or not units
            or sorted(units)!=ordered[:cursor] or (complete and cursor!=len(ordered)) or (not complete and cursor!=1)):
        raise ValueError('actual complete/partial unit cursor differs')
    return units


def close(actual,expected,name):
    if (type(actual) not in (int,float,F) or type(expected) not in (int,float,F)
            or not math.isfinite(actual) or not math.isfinite(expected)
            or abs(actual-expected)>1e-12+1e-12*max(abs(actual),abs(expected))):
        raise ValueError(name+' differs from independent physical accounting')


def amount(row):
    if row is None: return None
    if type(row) is not dict or set(row)!={'exact','value'} or type(row['exact']) is not str:
        raise ValueError('exact represented quantity and finite display required')
    value=F(row['exact'])
    if type(row['value']) not in (int,float) or row['value']!=float(value):
        raise ValueError('quantity display differs from exact representation')
    return value


def known_distances(cells,edges,origins):
    """Independent Bellman-Ford costs; no optimistic path becomes a route."""
    known={'CANON','WORKING NON-CANON','SYNTHETIC TEST','MODELLED'}
    passable={k for k,c in cells.items() if c['source_status'] in known and c['traversable'] is True}
    distances={o['cell_id']:F() for o in (origins or []) if o['source_status'] in known and o['cell_id'] in passable}
    usable=[e for e in edges if e['source_status'] in known and e['enabled'] is True
        and e['travel_cost'] is not None and e['capacity_expected_individuals'] is not None
        and F(e['capacity_expected_individuals'])>0 and {e['source'],e['target']}<=passable]
    for _ in range(len(cells)-1):
        changed=False
        for e in usable:
            if e['source'] in distances:
                candidate=distances[e['source']]+F(e['travel_cost'])
                if e['target'] not in distances or candidate<distances[e['target']]:
                    distances[e['target']]=candidate; changed=True
        if not changed: break
    return distances,{e['edge_id']:e for e in usable}


def validate_range(result):
    inputs=result['inputs']; rule=inputs['rule']; cells={c['cell_id']:c for c in inputs['cells']}
    if (result['inputs_sha256']!=sha(encoded(inputs)) or result['species_id']!=rule['species_id']
            or result['season_id']!=inputs['season_id'] or set(result['cells'])!=set(cells)):
        raise ValueError('actual spatial inputs/identity differ')
    distances,edges=known_distances(cells,inputs['edges'],inputs['origins']); total=F(); unknown=False
    for ident,row in result['cells'].items():
        cell=cells[ident]; area=F(cell['area_m2']); probability=row['occupancy_probability']
        known={'CANON','WORKING NON-CANON','SYNTHETIC TEST','MODELLED'}
        trusted=cell['source_status'] in known and rule['source_status'] in known
        support=cell['habitat_support'] if trusted else None
        fraction=F(cell['habitat_fraction']) if trusted and cell['habitat_fraction'] is not None else None
        threshold=rule['suitability_minimum'] if rule['source_status'] in known else None
        habitat='FAIL' if fraction==0 or support is not None and threshold is not None and support<threshold else 'PASS' if support is not None and fraction is not None and threshold is not None else 'UNKNOWN'
        if amount(row['area_m2'])!=area or row['habitat_support']!=support or row['habitat_status']!=habitat:
            raise ValueError('physical area/habitat support changed at occupancy boundary')
        access=row['accessibility']
        if ident in distances:
            if amount(access['least_cost'])!=distances[ident]: raise ValueError('independent shortest-path cost differs')
            path=access['path_edge_ids']; target=ident; cost=F()
            for edge_id in reversed(path):
                edge=edges.get(edge_id)
                if edge is None or edge['target']!=target: raise ValueError('access route crosses a barrier or wrong endpoint')
                cost+=F(edge['travel_cost']); target=edge['source']
            if cost!=distances[ident] or target not in {o['cell_id'] for o in inputs['origins']}:
                raise ValueError('access route lacks actual origin/cost support')
            expected_access='ACCESSIBLE' if rule['travel_budget'] is not None and distances[ident]<=F(rule['travel_budget']) else None
            if expected_access and access['status']!=expected_access: raise ValueError('known within-budget access misclassified')
        occupied=amount(row['expected_occupied_fraction']); occupied_area=amount(row['expected_occupied_area_m2'])
        population=amount(row['expected_individuals'])
        if row['realised_occupied_fraction'] is not None or row['observed_individuals'] is not None or row['active_bonds'] is not None:
            raise ValueError('model expectation promoted to census or bonds')
        excluded=access['status']=='INACCESSIBLE' or row['habitat_status']=='FAIL'
        if excluded:
            if probability!=0 or any(v!=0 for v in (occupied,occupied_area,population)):
                raise ValueError('known exclusion must remain a separately justified zero')
        elif probability is not None:
            if access['status']!='ACCESSIBLE' or row['habitat_status']!='PASS': raise ValueError('unknown support promoted to known occupancy')
            z=float(rule['logit_intercept'])+float(rule['logit_slope'])*float(cell['habitat_support'])
            expected=1/(1+math.exp(-z)) if z>=0 else math.exp(z)/(1+math.exp(z))
            close(probability,expected,'explicit logistic occupancy')
            fraction=F(cell['habitat_fraction'])*F(rule['conditional_occupied_fraction'])*F(probability)
            if occupied!=fraction or occupied_area!=area*fraction:
                raise ValueError('expected occupied fraction/physical area ledger differs')
            if rule['density_per_occupied_m2'] is None:
                if population is not None: raise ValueError('unknown density became a population')
            else:
                conditional=area*F(cell['habitat_fraction'])*F(rule['conditional_occupied_fraction'])*F(rule['density_per_occupied_m2'])
                if amount(row['conditional_expected_individuals_if_occupied'])!=conditional:
                    raise ValueError('conditional abundance support differs')
                if conditional<1:
                    if population is not None or row['abundance_status']!='OUTSIDE_REGIME':
                        raise ValueError('less than one conditional individual promoted to complete abundance')
                elif population!=occupied_area*F(rule['density_per_occupied_m2']):
                    raise ValueError('density-times-occupied-area abundance differs')
        elif occupied is not None or occupied_area is not None or population is not None:
            raise ValueError('unknown occupancy cannot create numerical area/abundance')
        if population is None: unknown=True
        else: total+=population
    if amount(result['known_subtotal_expected_individuals'])!=total or amount(result['total_expected_individuals'])!=(None if unknown else total):
        raise ValueError('partial known subtotal relabelled total abundance')
    return {'status':result['status'],'total_expected_individuals':None if unknown else str(total)}


def validate_movement(movement,departure,arrival,spec,*,explicit_stock=None):
    if (movement['range_inputs_sha256']!=departure['inputs_sha256']
            or movement['destination_range_inputs_sha256']!=arrival['inputs_sha256']
            or movement['destination_season_id']!=arrival['season_id']):
        raise ValueError('movement departure/arrival biological context differs')
    declared=spec['movement']; requests=sorted(declared['requests'],key=lambda x:x['priority'])
    movement_inputs={'departure_range_inputs_sha256':departure['inputs_sha256'],
        'arrival_range_inputs_sha256':arrival['inputs_sha256'],
        'requests':[{**r,'expected_individuals':None if r['expected_individuals'] is None else str(F(r['expected_individuals']))} for r in requests],
        'receiving_capacity':{k:None if value is None else str(F(value)) for k,value in declared['receiving_capacity'].items()},
        'evidence':declared['evidence'],'source_status':declared['source_status']}
    if explicit_stock is not None:
        if movement.get('declared_departure_stock')!=explicit_stock: raise ValueError('same-cohort stock source or phase continuity differs')
        movement_inputs['declared_departure_stock']=explicit_stock
    if movement['movement_inputs_sha256']!=sha(encoded(movement_inputs)):
        raise ValueError('movement request/capacity/evidence binding differs')
    if spec['rule']['movement_mode']=='NONMOVING':
        if movement['status']!='NOT_APPLICABLE' or movement['paths'] or movement['requests'] or movement['cells'] is not None:
            raise ValueError('rooted nonmoving stage acquired adult movement')
        return {'status':'NOT_APPLICABLE'}
    if movement['status']!='MODELLED_FEASIBLE_ALLOCATION': raise ValueError('complete engine reference needs feasible movement accounting')
    inputs=departure['inputs']; es={e['edge_id']:e for e in inputs['edges']}; cs={c['cell_id']:c for c in inputs['cells']}
    dest={c['cell_id']:c for c in arrival['inputs']['cells']}; outgoing={k:F() for k in cs}; incoming=dict(outgoing); used={k:F() for k in es}
    if set(movement['cells'])!=set(cs) or set(movement['edges'])!=set(es): raise ValueError('complete movement cell/edge ledger required')
    if [r['request_id'] for r in movement['requests']]!=[r['request_id'] for r in requests]: raise ValueError('declared movement priority/identity changed')
    for path in movement['paths']:
        volume=amount(path['expected_individuals']); cursor=path['source']; cost=F(); visited={cursor}
        if volume is None or volume<=0: raise ValueError('nonpositive realised model flow')
        for edge_id in path['edge_ids']:
            edge=es[edge_id]
            if (edge['source']!=cursor or edge['enabled'] is not True or edge['travel_cost'] is None
                    or edge['source_status'] not in ('CANON','WORKING NON-CANON','SYNTHETIC TEST','MODELLED')
                    or cs[cursor]['traversable'] is not True or cs[edge['target']]['traversable'] is not True
                    or edge['target'] in visited): raise ValueError('flow crosses a barrier/cycle or wrong directed edge')
            cursor=edge['target']; visited.add(cursor); cost+=F(edge['travel_cost']); used[edge_id]+=volume
        if (cursor!=path['target'] or cost!=amount(path['travel_cost']) or cost>F(spec['rule']['travel_budget'])
                or dest[cursor]['traversable'] is not True or arrival['cells'][cursor]['habitat_status']!='PASS'):
            raise ValueError('flow lacks allowed arrival habitat or travel budget')
        outgoing[path['source']]+=volume; incoming[path['target']]+=volume
    allocated_indices=[]
    for actual,request in zip(movement['requests'],requests):
        if any(actual[k]!=request[k] for k in ('source','target','priority')): raise ValueError('movement request endpoints changed')
        indices=actual['path_indices']; allocated_indices.extend(indices)
        paths=[movement['paths'][i] for i in indices]
        if any(p['request_id']!=actual['request_id'] or p['source']!=actual['source'] or p['target']!=actual['target'] for p in paths):
            raise ValueError('flow assigned to another request')
        transferred=sum((amount(p['expected_individuals']) for p in paths),F()); requested=F(request['expected_individuals'])
        if (amount(actual['requested_expected_individuals'])!=requested or amount(actual['transferred_expected_individuals'])!=transferred
                or amount(actual['unmet_expected_individuals'])!=requested-transferred or not 0<=transferred<=requested):
            raise ValueError('requested/transferred/unmet movement ledger differs')
    if sorted(allocated_indices)!=list(range(len(movement['paths']))): raise ValueError('flow path counted twice or omitted')
    for ident,row in movement['cells'].items():
        initial=amount(departure['cells'][ident]['expected_individuals']) if explicit_stock is None else F(dict(explicit_stock['counts'])[ident])
        capacity=F(spec['movement']['receiving_capacity'][ident])
        if (amount(row['initial_expected_individuals'])!=initial or outgoing[ident]>initial or incoming[ident]>capacity
                or amount(row['outgoing_expected_individuals'])!=outgoing[ident] or amount(row['incoming_expected_individuals'])!=incoming[ident]
                or amount(row['final_expected_individuals'])!=initial-outgoing[ident]+incoming[ident]
                or amount(row['unused_receiving_capacity'])!=capacity-incoming[ident]
                or amount(movement['receiving_capacity'][ident])!=capacity):
            raise ValueError('stock, no-retransmission or receiving-place conservation differs')
        if explicit_stock is not None and amount(row['final_expected_individuals'])>0:
            if (arrival['cells'][ident]['habitat_status']!='PASS' or dest[ident]['traversable'] is not True
                    or dest[ident]['source_status'] not in ('CANON','WORKING NON-CANON','SYNTHETIC TEST','MODELLED')
                    or row.get('arrival_persistence_status')!='PASS'):
                raise ValueError('conserved resident stock lacks admissible arrival persistence')
    for ident,row in movement['edges'].items():
        if amount(row['used_expected_individuals'])!=used[ident] or amount(row['remaining_expected_individuals'])!=F(es[ident]['capacity_expected_individuals'])-used[ident] or used[ident]>F(es[ident]['capacity_expected_individuals']):
            raise ValueError('shared finite corridor capacity ledger differs')
    if sum(outgoing.values(),F())!=sum(incoming.values(),F()) or amount(movement['transfer_conservation_residual_expected_individuals'])!=0:
        raise ValueError('movement total stock conservation differs')
    return {'status':movement['status'],'transferred_expected_individuals':str(sum(outgoing.values(),F()))}


def validate_environment(environment,parent,recipe):
    """Recalculate scalar supports from actual parent rows, not its projection code."""
    parent_sha=sha(encoded(parent))
    if (environment['schema']!='diadem.species-environment.r9'
            or environment['parent_result_sha256']!=parent_sha
            or environment['parent_source_sha256']!=parent['source_sha256']
            or environment['seasons_sha256']!=sha(encoded(recipe['seasons']))):
        raise ValueError('seasonal environment parent/configuration binding differs')
    expected_scenarios={snow+'/'+family for snow,cells in parent['state']['members'].items()
        for family in next(iter(cells.values()))['pft_results']}
    if set(environment['scenarios'])!=expected_scenarios: raise ValueError('coequal family/snow inventory differs')
    count=unknown=0
    for scenario_id,scenario in environment['scenarios'].items():
        snow=scenario['snow_id']; family=scenario['biome_family_id']
        if scenario_id!=snow+'/'+family: raise ValueError('scenario identity changed')
        original=parent['state']['members'][snow]; seasonal=parent['seasonal']['members'][snow]
        terrain={row['cell_id']:row for row in seasonal['formed_terrain']}
        if set(scenario['seasons'])!={row['season_id'] for row in recipe['seasons']}: raise ValueError('season inventory differs')
        for season in recipe['seasons']:
            projected=scenario['seasons'][season['season_id']]
            if projected['months']!=season['months'] or projected['evidence']!=season['evidence'] or set(projected['cells'])!=set(original):
                raise ValueError('physical seasonal supports differ')
            for cell_id,cell in projected['cells'].items():
                prior=original[cell_id]; soil=parent['soil_result']['state']['members'][snow][cell_id]
                if (cell['cell_id']!=cell_id or cell['area_m2']!=prior['area_m2']
                        or cell['parent_cell_sha256']!=sha(encoded(prior)) or cell['soil_support_id']!=prior['soil_support_id']
                        or cell['domain']!=prior['classification']['domain']
                        or cell['potential_biome']!=prior['classification']['broad'] or cell['potential_formation']!=prior['classification']['formation']):
                    raise ValueError('actual area/domain/soil/vegetation join differs')
                expected={}
                def scalar(name,value,unit,pair=None):
                    expected[name]=(value,unit,None if value is None else [value,value] if pair is None else pair)
                chemistry=(soil.get('fertility') or {}).get('exchange')
                chemistry=None if chemistry is None else chemistry['chemistry']
                scalar('elevation_m',terrain[cell_id]['elevation_m'],'m')
                scalar('soil_ph_water',None if chemistry is None else chemistry['ph_water'],'1')
                scalar('soil_ec_ds_m',None if chemistry is None else chemistry['electrical_conductivity_ds_m'],'dS/m')
                horizons=soil['horizons']
                scalar('mineral_solum_m',float(F(horizons['mineral_pedogenic_solum_depth_m'])) if horizons['solum_status']=='MODELLED' else None,'m')
                cycle=seasonal['cells'][cell_id]
                months=[row for row in cycle['months'] if row['month_id'] in season['months']] if cycle['status']=='MODELLED_PERIODIC_SNOW' else []
                for name in ('temperature_mean_c','temperature_min_month_c','temperature_max_month_c','precipitation_m','liquid_water_m','reference_pet_m'):
                    scalar(name,None,'degC' if name.startswith('temperature') else 'm')
                if months:
                    if {row['month_id'] for row in months}!=set(season['months']): raise ValueError('incomplete actual seasonal months')
                    duration=sum((F(row['duration_seconds']) for row in months),F())
                    scalar('temperature_mean_c',float(sum((F(row['temperature_c'])*F(row['duration_seconds']) for row in months),F())/duration),'degC')
                    scalar('temperature_min_month_c',min(row['temperature_c'] for row in months),'degC')
                    scalar('temperature_max_month_c',max(row['temperature_c'] for row in months),'degC')
                    for key,field in (('precipitation_m','precipitation_m_s'),('reference_pet_m','potential_evaporation_m_s')):
                        scalar(key,float(sum((F(row[field])*F(row['duration_seconds']) for row in months),F())),'m')
                    scalar('liquid_water_m',float(sum((F(row['snow']['ledger']['liquid_to_soil_m']) for row in months),F())),'m')
                for pft_id,pft in prior['pft_results'][family].items():
                    prefix='pft.'+pft_id+'.'; capacity=prior['capacities'][pft_id]
                    scalar(prefix+'annual_admissibility',1 if pft['status']=='PASS' else 0 if pft['status']=='FAIL' else None,'1')
                    scalar(prefix+'rooted_capacity_m',capacity['capacity_m'] if capacity['status']=='MODELLED' else None,'m')
                    ratios=[]
                    if pft['water']['status']=='MODELLED_PERIODIC_BRACKET':
                        for side in ('lower','upper'):
                            events=[row for row in pft['water'][side]['events'] if row['month_id'] in season['months'] and row['active']]
                            demand=math.fsum(row['potential_transpiration_m'] for row in events)
                            if demand: ratios.append(math.fsum(row['actual_transpiration_m'] for row in events)/demand)
                    pair=[min(ratios),max(ratios)] if len(ratios)==2 else None
                    scalar(prefix+'seasonal_water_ratio',None if pair is None else sum(pair)/2,'1',pair)
                if set(cell['metrics'])!=set(expected): raise ValueError('actual physical metric inventory differs')
                for name,(value,unit,pair) in expected.items():
                    metric=cell['metrics'][name]
                    if (metric['unit']!=unit or not metric['evidence'] or parent_sha not in metric['evidence']
                            or metric['status']!=('UNKNOWN' if value is None else 'MODELLED')):
                        raise ValueError('metric unit/evidence/status differs')
                    if value is None:
                        unknown+=1
                        if metric['value'] is not None or metric['interval'] is not None: raise ValueError('missing actual physical support replaced by a number')
                    else:
                        close(metric['value'],value,name)
                        if type(metric['interval']) is not list or len(metric['interval'])!=2: raise ValueError('actual metric interval required')
                        for a,b in zip(metric['interval'],pair): close(a,b,name+' bracket')
                count+=1
    return {'scenario_count':len(expected_scenarios),'physical_cell_season_supports':count,'explicit_unknown_metrics':unknown}


def validate_habitat(habitat,physical,spec):
    if physical['domain']['kind']=='UNKNOWN' or physical['domain']['source_status'] in ('UNKNOWN','INCOMPLETE','CONFLICT'):
        if habitat['status']!='UNKNOWN' or habitat['support'] is not None or habitat['interval'] is not None or habitat['factors']:
            raise ValueError('unresolved independent domain promoted to habitat')
        return
    if physical['domain']['kind'] not in spec['allowed_domains'] and physical['domain']['kind']!='UNKNOWN' and physical['domain']['source_status'] not in ('UNKNOWN','INCOMPLETE','CONFLICT'):
        if habitat['status']!='EXCLUDED_DOMAIN' or habitat['interval']!=[0,0] or habitat['factors']: raise ValueError('explicit domain exclusion differs')
        return
    if len(habitat['factors'])!=len(spec['requirements']): raise ValueError('declared biological factor inventory differs')
    intervals=[]
    for factor,rule in zip(habitat['factors'],spec['requirements']):
        metric=physical['metrics'][rule['metric']]
        if factor['actual']!=metric or factor['rule']!=rule or factor['metric']!=rule['metric']:
            raise ValueError('habitat substituted physical support or biological requirement')
        if metric['interval'] is None: pair=None
        else:
            points=rule['points']
            def response(x):
                if x<points[0][0]: return points[0][1] if rule['outside']=='HOLD' else 0
                if x>points[-1][0]: return points[-1][1] if rule['outside']=='HOLD' else 0
                for a,b in zip(points,points[1:]):
                    if a[0]<=x<=b[0]: return float(F(a[1])+(F(b[1])-F(a[1]))*(F(x)-F(a[0]))/(F(b[0])-F(a[0])))
                raise ValueError('unsupported response coordinate')
            lo,hi=metric['interval']; values=[response(x) for x in [lo,hi]+[x for x,y in points if lo<x<hi]]
            pair=[min(values),max(values)]
        if factor['support_interval']!=pair: raise ValueError('piecewise habitat-response accounting differs')
        intervals.append(pair)
    if any(pair is None for pair in intervals):
        if habitat['status']!='UNKNOWN' or habitat['support'] is not None or habitat['interval'] is not None: raise ValueError('unknown biological support replaced by zero/favourable support')
    else:
        expected=[]
        for index in (0,1):
            values=[pair[index] for pair in intervals]
            expected.append(min(values) if spec['habitat_operator']=='MINIMUM' else 0. if 0 in values else math.exp(math.fsum(math.log(v) for v in values)/len(values)))
        if habitat['status']!='MODELLED_SUPPORT': raise ValueError('known habitat status differs')
        close(habitat['support'],expected[0],'habitat lower support')
        for a,b in zip(habitat['interval'],expected): close(a,b,'habitat combined interval')


def validate_spatial_join(result,habitat,physical,spec,recipe,bound):
    inputs=result['inputs']; rule=dict(spec['rule'])
    for key in ('conditional_occupied_fraction','density_per_occupied_m2','travel_budget'):
        rule[key]=None if rule[key] is None else str(F(rule[key]))
    if inputs['rule']!=rule or inputs['origins']!=(None if spec['origins'] is None else sorted(spec['origins'],key=lambda r:r['cell_id'])):
        raise ValueError('species law/origin evidence differs')
    # Acceptance fixture supplies no population-rescaling constraint.
    if inputs['prescribed_total'] is not None or spec['prescribed_total'] is not None: raise ValueError('unreviewed total-population constraint in reference')
    cells={row['cell_id']:row for row in inputs['cells']}
    if set(cells)!=set(physical) or set(habitat)!=set(physical): raise ValueError('spatial support inventory differs')
    for ident,cell in cells.items():
        h=habitat[ident]; p=physical[ident]; extra=spec['cells'][ident]
        excluded=h['status']=='EXCLUDED_DOMAIN'
        if (F(cell['area_m2'])!=F(p['area_m2']) or cell['habitat_support']!=(None if h['interval'] is None else h['interval'][bound])
                or cell['habitat_fraction']!=('0' if excluded else None if extra['habitat_fraction'] is None else str(F(extra['habitat_fraction'])))
                or cell['traversable']!=(False if excluded else extra['traversable']) or cell['source_status']!=extra['source_status']
                or cell['evidence']!=extra['evidence']+'; actual physical projection '+sha(encoded(p))):
            raise ValueError('actual species habitat/area/availability/source join differs')
    adjacency={frozenset((e['a'],e['b'])):e for e in recipe['parent_recipe']['edges']}
    edges={e['edge_id']:e for e in inputs['edges']}
    if set(edges)!={e['edge_id'] for e in spec['edges']}: raise ValueError('corridor edge inventory differs')
    for declared in spec['edges']:
        edge=edges[declared['edge_id']]; support=adjacency[frozenset((declared['source'],declared['target']))]
        cost=None if declared['cost_per_m'] is None else str(F(declared['cost_per_m'])*F(support['length_m']))
        if (any(edge[k]!=declared[k] for k in ('source','target','enabled','source_status')) or edge['travel_cost']!=cost
                or edge['capacity_expected_individuals']!=(None if declared['capacity_expected_individuals'] is None else str(F(declared['capacity_expected_individuals'])))
                or edge['evidence']!=declared['evidence']+'; physical adjacency '+sha(encoded(support))):
            raise ValueError('corridor cost/capacity lacks actual adjacency support')


def validate_draws(unit,recipe,organism,season):
    ranges=unit['range_endpoint_cases']
    if set(unit['cells'])!=set(ranges['lower_habitat']['cells']): raise ValueError('snapshot draw support differs')
    for ident,row in unit['cells'].items():
        seed={'seed':recipe['placement_seed'],'organism':organism,'season':season,'cell':ident}
        digest=sha(encoded(seed)); raw=bytes.fromhex(sha(digest.encode())); uniform=F(int.from_bytes(raw[:8],'big')>>11,2**53)
        endpoints=[ranges[side]['cells'][ident] for side in ('lower_habitat','upper_habitat')]
        probabilities=[e['occupancy_probability'] for e in endpoints]
        bounds=None if None in probabilities else [min(probabilities),max(probabilities)]
        presence=None if bounds is None or F(bounds[0])<=uniform<F(bounds[1]) else uniform<F(bounds[0])
        expected={'occupancy_probability_interval':bounds}
        for field in ('expected_occupied_area_m2','expected_individuals'):
            values=[amount(e[field]) for e in endpoints]
            expected[field+'_interval']=None if None in values else [str(min(values)),str(max(values))]
        threshold=recipe['organisms'][organism]['seasons'][season]['rule']['suitability_minimum']
        interval=unit['habitat'][ident]['interval']
        if interval is not None and threshold is not None and interval[0]<threshold<=interval[1]:
            presence=None; expected={key:None for key in expected}
        if (row['modelled_presence'] is not presence or row['observed_presence'] is not None
                or row['status']!=('UNKNOWN' if presence is None else 'MODELLED_SNAPSHOT_DRAW')
                or row['draw_uniform_exact']!=str(uniform) or row['draw_binding_sha256']!=digest
                or any(row[key]!=value for key,value in expected.items())):
            raise ValueError('seeded conditional draw/expectation promoted or changed')


def validate_overlap(full,recipe):
    rows=full['state']['results']; environment=full['environment']['scenarios']
    if set(full['overlap_products'])!=set(environment): raise ValueError('overlap scenario inventory differs')
    for scenario,physical in environment.items():
        if set(full['overlap_products'][scenario])!=set(physical['seasons']): raise ValueError('overlap season inventory differs')
        for season,context in physical['seasons'].items():
            products=full['overlap_products'][scenario][season]
            if set(products)!={'RETAINED','SYNTHETIC_TEST'}: raise ValueError('retained/test overlap populations mixed')
            for group,product in products.items():
                ids=[key for key,value in recipe['organisms'].items() if value['applicability']=='SPATIAL' and (value['source_status']!='SYNTHETIC TEST')==(group=='RETAINED')]
                if sorted(product['eligible_organism_ids'])!=sorted(ids) or set(product['cells'])!=set(context['cells']): raise ValueError('overlap eligible denominator differs')
                for ident,cell in product['cells'].items():
                    values=[None if rows[scenario][taxon][season].get('cells') is None else rows[scenario][taxon][season]['cells'][ident]['modelled_presence'] for taxon in ids]
                    known=sum(value is not None for value in values); present=sum(value is True for value in values)
                    expected={'represented_cell_area_m2':context['cells'][ident]['area_m2'],'eligible_taxa':len(ids),
                        'evaluated_presence_taxa':known,'unknown_or_unexecuted_taxa':len(ids)-known,
                        'modelled_present_taxa':present,'modelled_absent_taxa':known-present,'observed_richness':None}
                    if cell!=expected: raise ValueError('overlap unknown/absence/area denominator accounting differs')


def validate_stock_result(result,spec):
    """Independent dimensional or finite-stock accounting; no spatial redistribution."""
    canonical=dict(spec)
    if spec['cells'] is not None: canonical['cells']=sorted(spec['cells'],key=lambda row:row['cell_id'])
    if result['inputs_sha256']!=sha(encoded(canonical)) or result['context']!=spec['context']:
        raise ValueError('joint abundance input/context identity differs')
    rows=spec['cells']; known={'CANON','WORKING NON-CANON','SYNTHETIC TEST','MODELLED'}
    context_known=spec['context']['source_status'] in known
    if set(result['cells'])!={r['cell_id'] for r in rows or []}: raise ValueError('abundance footprint inventory differs')
    def rational(value): return None if value is None else F(value)
    def measure(value):
        if value is None: return None,None
        if value['unit'] not in ('m2','km2'): raise ValueError('actual parent abundance support is area only')
        return None if value['value'] is None else F(value['value'])*(1000000 if value['unit']=='km2' else 1),'m2'
    if spec['schema']=='diadem.declared-density-input.r9':
        subtotal=F(); unknown=False
        for source in rows:
            row=result['cells'][source['cell_id']]; area,unit=measure(source['measure'])
            trusted=context_known and source['source_status'] in known
            if not trusted: area=None
            habitat=None if area is None or source['habitat_fraction'] is None else area*F(source['habitat_fraction'])
            occupied=None if habitat is None or source['occupied_fraction'] is None else habitat*F(source['occupied_fraction'])
            density=source['density']; basis=density['basis']
            if density['denominator_unit'] not in ('m2','km2'): raise ValueError('actual density denominator lacks matching area dimension')
            denominator={'PER_WHOLE_CELL_MEASURE':area,'PER_HABITAT_MEASURE':habitat,'PER_OCCUPIED_MEASURE':occupied}[basis]
            converted=None if not trusted or density['value'] is None else F(density['value'])/(1000000 if density['denominator_unit']=='km2' else 1)
            excluded=trusted and source['eligible'] is False
            count=F() if excluded else None if not trusted or source['eligible'] is None or denominator is None or converted is None else denominator*converted
            if count is None: unknown=True
            else: subtotal+=count
            expected={'physical_measure':area,'habitat_measure':habitat,'occupied_measure':occupied,
                'density_per_si_unit':converted,'density_denominator_measure':denominator,'expected_entities':count}
            if (any(amount(row[key])!=value for key,value in expected.items()) or row['measure_unit']!=unit
                    or row['density_basis']!=basis or row['eligible'] is not source['eligible']
                    or row['status']!=('EXCLUDED' if excluded else 'UNKNOWN' if count is None else 'MODELLED')
                    or row['observed_entities'] is not None or row['occupancy_probability'] is not None):
                raise ValueError('dimensional density/occupancy-basis accounting differs')
        if (amount(result['known_subtotal_expected_entities'])!=subtotal
                or amount(result['total_expected_entities'])!=(None if unknown else subtotal)
                or result['status']!=('UNKNOWN' if unknown else 'MODELLED')):
            raise ValueError('unknown dimensional abundance promoted to complete total')
        return {'status':result['status'],'total_expected_entities':None if unknown else str(subtotal)}
    if spec['schema']!='diadem.prescribed-stock-input.r9': raise ValueError('unreviewed abundance mode')
    total=rational(spec['total_expected_entities']) if context_known else None
    missing_weight=any(r['weight'] is None or r['source_status'] not in known for r in rows or [])
    weights=None if missing_weight else sum((F(r['weight']) for r in rows or []),F())
    placed=F(); unknown=total is None or rows is None or missing_weight; conflict=False
    for source in rows or []:
        row=result['cells'][source['cell_id']]; nominal=None if total is None or missing_weight else F() if not weights else total*F(source['weight'])/weights
        allocation=None; committed=F(); status='UNKNOWN'; physical,unit=measure(source['occupied_measure'])
        if nominal==0: allocation=F(); status='ZERO_WEIGHT'
        elif nominal is not None:
            if source['eligible'] is False: allocation=F(); status='EXCLUDED'
            elif source['eligible'] is None or source['capacity_expected_entities'] is None: unknown=True
            else:
                allocation=min(nominal,F(source['capacity_expected_entities']))
                if allocation and physical==0: allocation=None; conflict=True; status='CONFLICT'
                else:
                    committed=allocation; status='CAPPED' if committed<nominal else 'ALLOCATED'
        placed+=committed
        implied=None if allocation is None or physical in (None,0) else allocation/physical
        expected={'nominal_share_expected_entities':nominal,'allocation_expected_entities':allocation,
            'committed_expected_entities':committed,'unplaced_share_expected_entities':None if nominal is None else nominal-committed,
            'occupied_measure':physical,'implied_density_per_si_unit':implied}
        if (any(amount(row[key])!=value for key,value in expected.items()) or row['status']!=status
                or row['eligible'] is not source['eligible'] or row['measure_unit']!=unit or row['observed_entities'] is not None):
            raise ValueError('scoped stock share/cap/implied-density accounting differs')
    unplaced=None if total is None else total-placed
    status='CONFLICT' if conflict else 'UNKNOWN' if unknown else 'MODELLED_ALLOCATION_COMPLETE' if unplaced==0 else 'MODELLED_PARTLY_UNPLACED'
    expected={'total_expected_entities':total,'placed_expected_entities':placed,'unplaced_expected_entities':unplaced,
        'conservation_residual_expected_entities':None if total is None else F(),'normalisation_weight':weights}
    if (any(amount(result[key])!=value for key,value in expected.items()) or result['status']!=status
            or total is not None and (placed<0 or unplaced<0 or placed+unplaced!=total)):
        raise ValueError('stock placed/unplaced conservation or unknown scope differs')
    return {'status':status,'placed_expected_entities':str(placed),'unplaced_expected_entities':None if unplaced is None else str(unplaced)}


def validate_abundance(full,recipe,owner):
    products=full['abundance_models']; environment=full['environment']['scenarios']; states=full['state']['results']
    if (products['scenarios_and_seasons_are_not_additive'] is not True or products['observed_density_supplied'] is not False
            or products['whole_diadem_population_derived'] is not False): raise ValueError('alternative model stock promoted to a census')
    alternatives=products['alternative_scenarios']; report={}
    if set(alternatives)!={s['scenario_id'] for s in recipe['abundance_scenarios']}: raise ValueError('joint abundance scenario inventory differs')
    for spec in recipe['abundance_scenarios']:
        actual=alternatives[spec['scenario_id']]
        if any(actual[key]!=spec[key] for key in ('organism_id','season_id','mode')): raise ValueError('abundance organism/season/mode differs')
        selected=set(environment) if spec['physical_scenario_id']=='ALL_COEQUAL' else {spec['physical_scenario_id']}
        if set(actual['physical_scenarios'])!=selected: raise ValueError('abundance physical scenario inventory differs')
        for scenario,output in actual['physical_scenarios'].items():
            physical=environment[scenario]['seasons'][spec['season_id']]['cells']; model=deepcopy(spec['model'])
            expected={key:{'area_m2':cell['area_m2'],'parent_cell_sha256':cell['parent_cell_sha256']} for key,cell in physical.items()}
            if (output['actual_cell_bindings']!=expected or output['parent_result_sha256']!=full['parent_result_sha256']
                    or output['declared_model_sha256']!=sha(encoded(spec['model']))): raise ValueError('abundance actual geometry/source joins differ')
            if model['cells'] is not None:
                if {row['cell_id'] for row in model['cells']}!=set(physical): raise ValueError('actual abundance footprint differs')
                for cell in model['cells']:
                    unit=states[scenario][spec['organism_id']][spec['season_id']]; support=None
                    if 'range_endpoint_cases' in unit:
                        rows=[r['cells'][cell['cell_id']] for r in unit['range_endpoint_cases'].values()]
                        support=True if all(r['habitat_status']=='PASS' and r['accessibility']['status']=='ACCESSIBLE' for r in rows) else False if all(r['habitat_status']=='FAIL' or r['accessibility']['status']=='INACCESSIBLE' for r in rows) else None
                    declared=cell['eligible']; effective=False if declared is False or support is False else True if declared is True and support is True else None
                    joined=output['admissibility'][cell['cell_id']]
                    if joined['declared'] is not declared or joined['actual_required_support_and_accessibility'] is not support or joined['effective'] is not effective:
                        raise ValueError('declared abundance geography overrode actual habitat/accessibility')
                    cell['eligible']=effective
                    measure=cell['measure'] if spec['mode']=='DECLARED_DENSITY' else cell['occupied_measure']
                    if measure is not None and measure['value'] is not None:
                        area=F(measure['value'])*(1000000 if measure['unit']=='km2' else 1); actual_area=F(physical[cell['cell_id']]['area_m2'])
                        if measure['unit'] not in ('m2','km2') or (area!=actual_area if spec['mode']=='DECLARED_DENSITY' else area>actual_area):
                            raise ValueError('dimensional abundance measure exceeds/lacks actual area support')
            report[spec['scenario_id']+'/'+scenario]=validate_stock_result(output['model'],model)
    register=products['owner_stock_register']
    if set(register)!=set(owner): raise ValueError('owner stock register inventory differs')
    for ident,source in owner.items():
        row=register[ident]; population=source['population_reference']; allocation=row['allocation']
        if row['source_population_reference']!=population or row['not_wild_generation'] is not (source['retained_hs'] in (14,19)):
            raise ValueError('scoped owner stock or exceptional wild interpretation changed')
        context={'species_id':ident,'counting_unit':'UNKNOWN' if population is None else population['counted_entity'],
            'life_stage':'UNKNOWN' if population is None else population['counted_entity'],
            'spatial_scope_id':'UNKNOWN' if population is None else population['scope'],
            'time_basis':'UNKNOWN' if population is None else population['temporal_basis'],
            'snapshot_id':sha(encoded(recipe['parent_recipe'])),'joint_scenario_id':'OWNER_STOCK_UNPLACED',
            'supplier':'Bound R9 Ecology/Population owners','evidence':source['evidence'],'source_status':'WORKING NON-CANON'}
        spec={'schema':'diadem.prescribed-stock-input.r9','context':context,
            'total_expected_entities':None if population is None else population['working_total'],'cells':None}
        validate_stock_result(allocation,spec)
        if allocation['status']!='UNKNOWN' or allocation['cells'] or amount(allocation['placed_expected_entities'])!=0:
            raise ValueError('unlocated working stock forced onto new terrain')
    return {'alternative_case_count':len(report),'owner_unplaced_stock_records':len(register),'cases':report,
        'scope':'explicit alternative counts, not additional occupancy populations; unknown footprints remain unplaced'}


def validate_cohorts(full,recipe):
    chains=full['seasonal_cohort_chains']; stocks=full['abundance_models']['alternative_scenarios']; report={}
    if set(chains)!={row['chain_id'] for row in recipe['cohort_chains']}: raise ValueError('finite cohort chain inventory differs')
    for spec in recipe['cohort_chains']:
        chain=chains[spec['chain_id']]; allocated=stocks[spec['allocation_scenario_id']]
        if (any(chain[key]!=spec[key] for key in ('organism_id','allocation_scenario_id','evidence','source_status'))
                or set(chain['scenarios'])!=set(allocated['physical_scenarios'])):
            raise ValueError('same-cohort allocation source/scenario differs')
        for scenario,endpoints in chain['scenarios'].items():
            initial=allocated['physical_scenarios'][scenario]['model']; context=initial['context']
            if set(endpoints)!={'lower_habitat','upper_habitat'}: raise ValueError('cohort habitat endpoint inventory differs')
            for side,endpoint in endpoints.items():
                current={key:amount(row['committed_expected_entities']) for key,row in initial['cells'].items()}
                total=amount(initial['total_expected_entities']); unplaced=amount(initial['unplaced_expected_entities'])
                if (endpoint['status']!='MODELLED_CONSERVED_COHORT' or total!=32 or unplaced!=0
                        or current!={'lower':F(16),'upper':F(16)} or spec['seasons']!=['warm','cold','warm']
                        or {key:amount(row) for key,row in endpoint['initial_counts'].items()}!=current
                        or endpoint['completed_phase_count']!=2 or len(endpoint['phases'])!=2):
                    raise ValueError('reviewed initial finite 32-member cohort/support differs')
                trajectory=[{key:str(value) for key,value in current.items()}]
                for index,phase in enumerate(endpoint['phases']):
                    departure,arrival=spec['seasons'][index:index+2]
                    if phase['index']!=index or phase['departure']!=departure or phase['arrival']!=arrival: raise ValueError('same-cohort phase order differs')
                    unit=full['state']['results'][scenario][spec['organism_id']]
                    departure_range=deepcopy(unit[departure]['range_endpoint_cases'][side])
                    arrival_range=deepcopy(unit[arrival]['range_endpoint_cases'][side])
                    for support in (departure_range,arrival_range):
                        for key in ('logit_intercept','logit_slope','conditional_occupied_fraction','density_per_occupied_m2'):
                            support['inputs']['rule'][key]=None
                        support['inputs']['prescribed_total']=None
                        support['inputs_sha256']=sha(encoded(support['inputs']))
                    stock={'species_id':spec['organism_id'],'counting_unit':context['counting_unit'],'cohort_id':spec['chain_id'],
                        'scope_id':context['spatial_scope_id'],'snapshot_id':full['parent_result_sha256'],'phase_id':departure,
                        'counts':[[key,str(value)] for key,value in sorted(current.items())],
                        'evidence':spec['evidence'],'source_status':spec['source_status']}
                    movement=phase['result']; season_spec=recipe['organisms'][spec['organism_id']]['seasons'][departure]
                    validate_movement(movement,departure_range,arrival_range,season_spec,explicit_stock=stock)
                    current={key:amount(row['final_expected_individuals']) for key,row in movement['cells'].items()}
                    expected={'lower':F(11),'upper':F(21)} if index==0 else {'lower':F(16),'upper':F(16)}
                    if current!=expected or sum(current.values(),F())+unplaced!=total:
                        raise ValueError('actual same-cohort transfer trajectory or total conservation differs')
                    trajectory.append({key:str(value) for key,value in current.items()})
                if ({key:amount(row) for key,row in endpoint['final_committed_counts'].items()}!=current
                        or amount(endpoint['unplaced_expected_entities'])!=unplaced or amount(endpoint['total_expected_entities'])!=total
                        or amount(endpoint['conservation_residual_expected_entities'])!=0):
                    raise ValueError('finite cohort final/unplaced stock differs')
                report[spec['chain_id']+'/'+scenario+'/'+side]={'total':'32','unplaced':'0','trajectory':trajectory,'phase_transfers':['5','5']}
    if len(report)!=18: raise ValueError('reviewed all-coequal cohort endpoint coverage differs')
    return {'endpoint_cases':len(report),'actual_phase_transfers':2*len(report),'cases':report,
        'scope':'same finite cohort across phases, never sum of seasonal populations'}


def validate_products(full,bundle,recipe,parent):
    if PRODUCT_CONTRACT_READY is not True:
        raise ValueError('scientific product contract pending; no final seal')
    units=validate_envelope(full,recipe,bundle,parent,complete=True)
    if any(full[key] is not False for key in ('observations_used_as_forcing','production_installed','canon_changed','optimisation_performed')):
        raise ValueError('bounded expectation status differs')
    if full['actual_occurrence_overlays']!=recipe['actual_occurrence_overlays']: raise ValueError('separate occurrence overlay differs')
    preserved=bundle.parent.graph.load('work.generator_upgrade_r8.verify').validate_products(parent,bundle.parent,recipe['parent_recipe'])
    environment=validate_environment(full['environment'],parent,recipe)
    roster={row['hs']:row for row in bundle.pipeline.sources.retained_roster()['organisms']}
    owner=bundle.pipeline.owner_inputs.biological_roster()
    retained=[taxon['retained_hs'] for taxon in recipe['organisms'].values() if taxon['retained_hs'] is not None]
    synthetic={key for key,taxon in recipe['organisms'].items() if taxon['source_status']=='SYNTHETIC TEST'}
    if (sorted(retained)!=sorted(roster) or synthetic!={'TEST-PLANT','TEST-ANIMAL'} or len(units)!=684
            or len(owner)!=36 or sum(row['kind']=='PLANT' for row in owner.values())!=17
            or set(recipe['organisms'])!=set(owner)|synthetic or full['biological_owner_contracts']!=owner):
        raise ValueError('reviewed owner 36-organism plus two-engine-fixture reference inventory differs')
    statuses={key:[] for key in recipe['organisms']}; report={}; count=flows=0
    for scenario,organism,season in units:
        taxon=recipe['organisms'][organism]; unit=full['state']['results'][scenario][organism][season]
        if unit['organism_id']!=organism or unit['season_id']!=season: raise ValueError('biological unit identity differs')
        statuses[organism].append(unit['status']); hs=taxon['retained_hs']
        if organism in owner and any(taxon[key]!=owner[organism][key] for key in ('name','kind','retained_hs','source_status')):
            raise ValueError('owner-bound organism identity/status differs')
        if hs is not None and taxon['name']!=roster[hs]['species']: raise ValueError('retained biological identity changed')
        if hs in (14,19):
            if (unit['status']!='NOT_APPLICABLE' or unit['cells'] is not None or unit['movement'] is not None
                    or unit['wild_expected_individuals']!=('0' if hs==19 else None)
                    or unit['applicability']!=('ABSENT_WILD' if hs==19 else 'NONSPATIAL_EVENT')):
                raise ValueError('nonspatial event or absent-wild exception semantics changed')
            continue
        if organism in owner:
            if (taxon['seasons'][season] is not None or unit['status']!='INCOMPLETE_BIOLOGICAL_RULES'
                    or unit['source_status']!='UNKNOWN' or unit['cells'] is not None or unit['movement'] is not None
                    or not unit['missing'] or 'wild_expected_individuals' in unit):
                raise ValueError('missing retained biology promoted to numerical/complete products')
            continue
        if taxon['source_status']!='SYNTHETIC TEST' or unit['status']!='MODELLED' or unit['biological_rule_sha256']!=sha(encoded(taxon)):
            raise ValueError('explicit complete numerical-engine fixture required')
        spec=taxon['seasons'][season]; physical=full['environment']['scenarios'][scenario]['seasons'][season]['cells']
        for ident,habitat in unit['habitat'].items(): validate_habitat(habitat,physical[ident],spec)
        for bound,side in enumerate(('lower_habitat','upper_habitat')):
            actual=unit['range_endpoint_cases'][side]
            if actual['season_id']!=season or actual['species_id']!=organism or actual['status']!='MODELLED': raise ValueError('range species/season/completeness differs')
            validate_spatial_join(actual,unit['habitat'],physical,spec,recipe,bound)
            scalar=validate_range(actual); count+=1
            arrival=full['state']['results'][scenario][organism][spec['movement']['destination_season_id']]['range_endpoint_cases'][side]
            movement=validate_movement(unit['movement_endpoint_cases'][side],actual,arrival,spec); flows+=movement['status']=='MODELLED_FEASIBLE_ALLOCATION'
            report['/'.join((scenario,organism,season,side))]={'range':scalar,'movement':movement}
        validate_draws(unit,recipe,organism,season)
    expected_coverage={'requested_organism_count':len(statuses),'completed_units':len(units),'expected_units':len(units),'all_units_executed':True,
        'organisms':{key:{'source_status':recipe['organisms'][key]['source_status'],'retained_hs':recipe['organisms'][key]['retained_hs'],
            'unit_statuses':sorted(set(values)),'required_products_complete':len(values)==18 and all(value in ('MODELLED','NOT_APPLICABLE') for value in values)} for key,values in statuses.items()},
        'all_required_products_complete':False,'no_complete_universal_plant_animal_roster_claim':True}
    if full['roster_coverage']!=expected_coverage: raise ValueError('engine completeness promoted to biological roster completeness')
    validate_overlap(full,recipe)
    abundance=validate_abundance(full,recipe,owner)
    cohorts=validate_cohorts(full,recipe)
    return {'status':VERIFIED_STATUS,'actual_parent_checks':preserved,
        'environment':environment,'executed_units':len(units),'retained_organisms':20,'owner_bound_organisms':36,
        'owner_bound_plants':17,'retained_biological_rule_gaps':34,
        'nonspatial_or_absent_exceptions':2,'complete_synthetic_engine_organisms':2,'range_endpoint_cases':count,
        'feasible_movement_endpoint_cases':flows,'all_required_products_complete':False,
        'independent_scientific_accounting':report,'independent_abundance_accounting':abundance,
        'independent_same_cohort_accounting':cohorts,
        'scope':'coequal conditional scenarios are alternatives, never additive world population or observed richness'}


def artifacts(bundle,root):
    root.mkdir(exist_ok=False); s=bundle.storage
    s.write_json(root/'recipe.json',bundle.reference.recipe(bundle)); recipe=s.read_json(root/'recipe.json')
    # The actual R8 product retains its own unchanged 8 MiB envelope.
    s.write_json(root/'parent-result.json',bundle.parent.run(recipe['parent_recipe']))
    parent=s.read_json(root/'parent-result.json')
    full=bundle.run(recipe); stop=bundle.run(recipe,stop_after=1)
    s.write_json(root/'stop-checkpoint.json',bundle.checkpoint(stop))
    restart=bundle.run(recipe,resume=s.read_json(root/'stop-checkpoint.json'))
    for name,value in (('full-result.json',full),('stop-result.json',stop),('restart-result.json',restart),
            ('full-checkpoint.json',bundle.checkpoint(full)),('restart-checkpoint.json',bundle.checkpoint(restart))):
        s.write_json(root/name,value)
    record={'path':str(root),'files':{p.name:sha(p.read_bytes()) for p in sorted(root.iterdir())},
        'reference_sha256':sha(s.encoded(full)),'parent_result_sha256':sha(s.encoded(parent)),
        'entrypoint':'actual public binding.Bundle.run/checkpoint; separately saved actual R8 parent; exclusive JSON and restart readback',
        'scientific_checks':validate_products(full,bundle,recipe,parent)}
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
    full=values['full-result.json']; recipe=values['recipe.json']; parent=values['parent-result.json']
    if full!=values['restart-result.json'] or values['full-checkpoint.json']!=values['restart-checkpoint.json']:
        raise ValueError('actual full/restart state differs')
    validate_envelope(full,recipe,bundle,parent,complete=True)
    validate_envelope(values['stop-result.json'],recipe,bundle,parent,complete=False)
    if record['reference_sha256']!=sha(s.encoded(full)) or record['parent_result_sha256']!=sha(s.encoded(parent)):
        raise ValueError('actual reference/parent digest differs')
    for stage in ('full','stop','restart'):
        if values[stage+'-checkpoint.json']!=bundle.checkpoint(values[stage+'-result.json']):
            raise ValueError('saved checkpoint identity differs')
    if record.get('scientific_checks')!=validate_products(full,bundle,recipe,parent): raise ValueError('scientific readback differs')
    return full


def private_executions(bundle):
    records={}; current=bundle
    for label in ('r9','r8','r7','r6'):
        records[label]=dict(current.graph.executed)
        if label!='r6': current=current.parent
    return records


def validate_private_executions(records,executed,bundle,helper):
    if type(records) is not dict or set(records)!={'r9','r8','r7','r6'}:
        raise ValueError('complete actual private graph chain required')
    expected=source_map(bundle.identity,helper)
    observed={helper.canonical(k):v for k,v in executed.items()}
    graphs={'r9':bundle.graph,'r8':bundle.parent.graph,'r7':bundle.parent.parent.graph,'r6':bundle.parent.parent.parent.graph}
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
    from work.generator_upgrade_r9 import binding
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
        scope='bounded actual parent/roster/spatial ecology scientific-source/restart verification; no optimisation')
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
    from work.generator_upgrade_r9 import binding
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
    seal={'schema':'diadem.species-spatial-verification.r9','status':VERIFIED_STATUS,
        'source_identity':bundle.identity,'source_sha256':bundle.source_sha256,'source_snapshot':bundle.identity['r9_sources'],
        'test_ids':ids,'test_count_per_mode':len(ids),'inventory_sha256':inventory_digest(ids),
        'workers':{label:{'path':str(root/(label+'-worker.json')),'sha256':sha((root/(label+'-worker.json')).read_bytes())} for label in ('n','o')},
        'normal_oo_parity':'EXACT_SCIENTIFIC_RESULT_AND_CHECKPOINT_PASS','parent_optimisation_flag':sys.flags.optimize,
        'actual_worker_flags':[r['optimisation_flag'] for r in records],
        'external_reference_sources':validate_external_sources(bundle),
        'complete_synthetic_engine_organisms':2,'owner_bound_organisms':36,'retained_biological_rule_gaps':34,
        'all_required_products_complete':False,'world_species_ranges_complete':False,
        'production_installed':False,'canon_changed':False,'optimisation_performed':False,
        'scope':'bounded actual retained seasonal environment -> explicitly supplied species spatial reference; incomplete biology stays UNKNOWN; no world production'}
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
    raw=Path(__file__).read_bytes(); namespace={'__file__':__file__,'__name__':'_r9_fresh_verification_entry'}
    exec(compile(raw,__file__,'exec',dont_inherit=True),namespace)
    namespace['ENTRY_SOURCE_SHA256']=sha(raw)
    raise SystemExit(namespace['main']())
