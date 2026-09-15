"""Exact-source dual-mode soil-stage verification; no performance benchmark."""
import argparse
from fractions import Fraction as F
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import types
import unittest

HERE=Path(__file__).resolve().parent
TASK=HERE.parents[1]
OUTPUT_ROOT=TASK/'outputs/generator-upgrade-r7'
SUITES=('test_binding','test_formation','test_organic','test_fertility','test_pipeline')
EXPECTED_COUNT=200
INVENTORY_SHA256='856ff9fe1a470177f389da251bacc76a95ddb7bf9558c4750ab0082924c57d92'
ENTRY_SOURCE_SHA256=None
R4_SEAL_SHA256='f7382693a5284ebf111dc8a0622e5811440ccc7e2b546047943462b849926996'


def sha(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def inventory_digest(ids):
    return sha(json.dumps(ids,separators=(',',':'),ensure_ascii=True).encode())


def utility():
    seal=TASK/'outputs/generator-upgrade-r4/connected-reference-01/VERIFICATION.json'
    raw=seal.read_bytes()
    if sha(raw)!=R4_SEAL_SHA256: raise ValueError('retained verifier seal changed')
    record=json.loads(raw); path=TASK/'work/generator_upgrade_r4/verify.py'
    raw=path.read_bytes(); digest=record['source_snapshot'][str(path)]
    if sha(raw)!=digest: raise ValueError('retained verification utility changed')
    module=types.ModuleType('_r7_exact_verification_utilities'); module.__file__=str(path)
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
    r6=identity['retained_source_identity']; r5=r6['retained_source_identity']
    result=helper.source_map(r5['retained_source_identity'])
    for mapping in (r5['r5_sources'],r6['r6_sources'],identity['r7_sources'],identity['external_test_reference_sources']):
        for path,digest in mapping.items():
            key=helper.canonical(path)
            if key in result and result[key]!=digest: raise ValueError('conflicting source binding')
            result[key]=digest
    return result


def stable(bundle,helper,capture,*,required=False):
    bundle.verify(); expected=source_map(bundle.identity,helper)
    if bundle.identity['r7_sources'].get(str(HERE/'verify.py'))!=ENTRY_SOURCE_SHA256:
        raise ValueError('entrypoint actual source differs')
    for path,digest in capture.executed.items():
        if expected.get(helper.canonical(path))!=digest or sha(Path(path).read_bytes())!=digest:
            raise ValueError('executed/current source differs from captured scientific identity: '+path)
    if capture.derived_executed: raise ValueError('derived/re-written scientific source not authorised')
    for path,digest in helper.READS.items():
        if capture.executed.get(path)!=digest: raise ValueError('loader/actual execution disagreement')
    if required: validate_execution(capture.executed,bundle.identity,helper)


def required_sources():
    names=(*SUITES,'binding','provenance','pipeline','reference','formation','organic','fertility','verify')
    return ([HERE/(name+'.py') for name in names]+[TASK/'work/terrain_model_r2/materials.py']+
        [TASK/('work/generator_upgrade_'+version+'/'+name+'.py') for version,name in
        (('r6','binding'),('r6','provenance'),('r6','soil_water'),('r6','hydraulic_jacobian'),
         ('r4','pipeline'),('r4','climate'),('r4','hydromet'),('r3','pipeline'),('r3','soil_inputs'),('r3','terrain_transport'))])


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


def external_test_bindings(bundle):
    from work.generator_upgrade_r7 import test_formation
    rows=test_formation.test_data_bindings()
    if rows!=bundle.identity['external_test_reference_sources']:
        raise ValueError('test references differ from explicitly captured validation-only sources')
    for path,digest in rows.items():
        bundle.storage.plain_path(path)
        if sha(Path(path).read_bytes())!=digest: raise ValueError('independent retained test reference changed')
    return rows


def discover(helper):
    if {p.name for p in HERE.glob('test_*.py')}!={name+'.py' for name in SUITES}:
        raise ValueError('test file inventory differs')
    loader=unittest.TestLoader(); suite=loader.loadTestsFromNames(['work.generator_upgrade_r7.'+name for name in SUITES])
    if loader.errors: raise ValueError('test discovery failed: '+repr(loader.errors))
    ids=[test.id() for test in helper.flatten(suite)]
    if not ids or len(ids)!=len(set(ids)): raise ValueError('unique nonempty test inventory required')
    return suite,ids


def require_inventory(ids):
    if type(EXPECTED_COUNT) is not int or type(INVENTORY_SHA256) is not str:
        raise ValueError('reviewed test inventory pending; no final seal')
    if (type(ids) is not list or any(type(v) is not str for v in ids)
            or len(ids)!=EXPECTED_COUNT or len(set(ids))!=EXPECTED_COUNT or inventory_digest(ids)!=INVENTORY_SHA256):
        raise ValueError('exact reviewed test identities differ')


def validate_tests(record):
    require_inventory(record['test_ids'])
    if record.get('status')!='PASS' or type(record.get('tests')) is not int or record['tests']!=EXPECTED_COUNT:
        raise ValueError('complete successful test inventory required')
    for name in ('failures','errors','skips','expected_failures','unexpected_successes'):
        if type(record.get(name)) is not int or record[name]!=0: raise ValueError('no omitted/failed tests permitted')
    for name in ('started','stopped','passed'):
        if record[name]!=record['test_ids']: raise ValueError('actual executed test identity inventory differs')
    if record.get('inventory_sha256')!=inventory_digest(record['test_ids']): raise ValueError('test inventory hash differs')


def run_suite(suite,ids,helper):
    stream=io.StringIO(); start=time.perf_counter()
    result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=helper.Result).run(suite)
    return {'status':'PASS' if result.wasSuccessful() else 'FAIL','tests':result.testsRun,'test_ids':ids,
        'inventory_sha256':inventory_digest(ids),'started':result.started,'stopped':result.stopped,'passed':result.passed,
        'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
        'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses),
        'test_duration_seconds':time.perf_counter()-start,'test_log':stream.getvalue()}


def artifacts(bundle,root):
    root.mkdir(exist_ok=False); s=bundle.storage
    recipe=bundle.reference.recipe(bundle)
    s.write_json(root/'recipe.json',recipe); recipe=s.read_json(root/'recipe.json')
    full=bundle.run(recipe); stop=bundle.run(recipe,stop_after=1)
    s.write_json(root/'stop-checkpoint.json',bundle.checkpoint(stop))
    restart=bundle.run(recipe,resume=s.read_json(root/'stop-checkpoint.json'))
    for name,value in (('full-result.json',full),('stop-result.json',stop),('restart-result.json',restart),
                       ('full-checkpoint.json',bundle.checkpoint(full)),('restart-checkpoint.json',bundle.checkpoint(restart))):
        s.write_json(root/name,value)
    record={'path':str(root),'files':{p.name:sha(p.read_bytes()) for p in sorted(root.iterdir())},
        'reference_sha256':sha(s.encoded(full)),'entrypoint':'actual public binding.Bundle.run/checkpoint; exclusive saved JSON and restart readback'}
    record['scientific_checks']=validate_products(full,bundle)
    validate_artifacts(record,bundle)
    return record


def validate_artifacts(record,bundle):
    s=bundle.storage; root=s.plain_path(record['path'])
    names={'recipe.json','full-result.json','stop-result.json','restart-result.json','stop-checkpoint.json','full-checkpoint.json','restart-checkpoint.json'}
    if set(record['files'])!=names or {p.name for p in root.iterdir()}!=names: raise ValueError('artifact inventory differs')
    values={}
    for name,digest in record['files'].items():
        values[name]=s.read_json(root/name)
        if sha((root/name).read_bytes())!=digest: raise ValueError('artifact readback hash differs')
    full=values['full-result.json']
    if full!=values['restart-result.json'] or values['full-checkpoint.json']!=values['restart-checkpoint.json']:
        raise ValueError('actual full/restart state differs')
    if (full['source_sha256']!=bundle.source_sha256 or full['schema']!='diadem.soil-formation-result.r7'
            or full['state']['completed_exposures']!=len(values['recipe.json']['soil_exposures'])
            or values['stop-result.json']['state']['completed_exposures']!=1
            or record['reference_sha256']!=sha(s.encoded(full))): raise ValueError('actual completed source-bound result required')
    for stage in ('full','stop','restart'):
        if values[stage+'-checkpoint.json']!=bundle.checkpoint(values[stage+'-result.json']):
            raise ValueError('saved checkpoint identity differs')
    if record.get('scientific_checks')!=validate_products(full,bundle): raise ValueError('actual scientific product readback differs')
    return full


def validate_products(full,bundle):
    expected={row.scenario_id for row in bundle.parent.pipeline.hm.snow_scenarios()}
    if set(full['state']['members'])!=expected or set(full['parent_result']['state']['members'])!=expected:
        raise ValueError('complete three-coequal-member producer/product required')
    parent_sha=sha(bundle.storage.encoded(full['parent_result']))
    if (parent_sha!=full['state']['parent_result_sha256'] or parent_sha!=full['actual_exposure']['parent_result_sha256']
            or full['parent_result']['source_sha256']!=bundle.parent.source_sha256): raise ValueError('actual parent result binding differs')
    report={}
    for scenario,cells in full['state']['members'].items():
        parent_cells=full['parent_result']['state']['members'][scenario]['physical']['profiles']
        if set(cells)!=set(parent_cells): raise ValueError('actual parent/formed cell inventory differs')
        report[scenario]={}
        for cell,row in cells.items():
            dry=row['total_dry_mass_accounting']; water=row['formed_soil_water']; assay=row['fertility']
            if (F(dry['residual_kg_m2'])!=0 or F(dry['initial_mineral_kg_m2'])!=F(dry['final_mineral_kg_m2'])
                    or F(dry['final_combined_dry_kg_m2'])!=sum((F(g['total_dry_mass_kg_m2']) for g in row['geometry']),F())):
                raise ValueError('actual formed mineral/organic dry stock ledger failed')
            if water['status']!='MODELLED_NEW_GEOMETRY_WATER_PROBE' or water['result']['status']!='MODELLED':
                raise ValueError('actual fresh formed-profile Water required')
            if water['geometry_sha256']!=sha(bundle.storage.encoded(row['geometry'])): raise ValueError('fresh Water geometry binding differs')
            b=water['water_accounting']
            residual=sum((F(b[k]) for k in ('parent_porewater_m','parent_surface_water_m','reservoir_initial_m','external_liquid_m','bottom_in_m')),F())-sum((F(b[k]) for k in ('formed_final_porewater_m','surface_final_m','reservoir_final_m','bottom_out_m','actual_et_m')),F())
            if residual!=F(b['physical_numerical_residual_m']) or abs(float(residual))>water['inputs']['controls']['total_mass_atol_m']:
                raise ValueError('fresh physical water reservoir/surface ledger failed')
            if assay['assay_support']['actual_formed_water_sha256']!=sha(bundle.storage.encoded(water)):
                raise ValueError('fertility does not use actual fresh formed Water')
            if assay['status']!='MODELLED_NATURAL_REFERENCE' or not 0<=assay['index_0_1']<=1:
                raise ValueError('complete explicit inherent reference fertility required')
            depths=row['horizons']
            if depths['solum_status']!='MODELLED' or F(depths['mineral_pedogenic_solum_depth_m'])<=0 or F(depths['surface_organic_thickness_m'])<=0:
                raise ValueError('reference requires actual positive separate mineral solum and O mantle')
            for event in row['exposure_history']:
                if any(F(b['residual_kg_m2']) for b in event['production']['mineral_balances']): raise ValueError('production material ledger failed')
                for organic in (*event['organic_results'].values(),event['surface_organic_result']):
                    carbon=organic['carbon']
                    if F(carbon['initial_kg_m2'])+F(carbon['input_kg_m2'])-F(carbon['final_kg_m2'])-F(carbon['exported_atmospheric_carbon_kg_m2']):
                        raise ValueError('actual organic carbon ledger failed')
            report[scenario][cell]={'mineral_solum_depth_m':float(F(depths['mineral_pedogenic_solum_depth_m'])),
                'separate_o_thickness_m':float(F(depths['surface_organic_thickness_m'])),
                'final_organic_dry_kg_m2':float(F(dry['final_organic_kg_m2'])),'inherent_reference_index':assay['index_0_1'],
                'physical_water_residual_m':str(residual),'formed_water_sha256':sha(bundle.storage.encoded(water)),
                'material_carbon_dry_origin_ledgers':'EXACT_REPRESENTED_PASS',
                'geometry_and_fresh_water_fertility_binding':'PASS'}
    return report


def worker(path,parent_path,mode):
    start=time.perf_counter(); helper,capture=install()
    from work.generator_upgrade_r7 import binding
    bundle=binding.load(); parent=bundle.storage.read_json(parent_path)
    if (type(mode) is not int or sys.flags.optimize!=mode or parent['source_identity']!=bundle.identity
            or parent['source_sha256']!=bundle.source_sha256): raise ValueError('worker actual flags/source differ')
    suite,ids=discover(helper); require_inventory(ids)
    if external_test_bindings(bundle)!=parent['external_test_bindings']: raise ValueError('parent/worker test reference binding differs')
    tests=run_suite(suite,ids,helper)
    record={'status':'FAIL','optimisation_flag':sys.flags.optimize,'source_identity':bundle.identity,
        'source_sha256':bundle.source_sha256,'tests':tests,'external_test_bindings':external_test_bindings(bundle)}
    try: validate_tests(tests)
    except ValueError:
        bundle.storage.write_json(path,record); capture.active=False; return 1
    record['artifacts']=artifacts(bundle,path.parent/(path.stem+'-reference'))
    try: stable(bundle,helper,capture,required=True)
    except Exception as error:
        record.update(status='FAIL',failure=str(error),executed_source_hashes=dict(capture.executed))
        bundle.storage.write_json(path,record); capture.active=False
        raise
    record.update(status='PASS',executed_source_hashes=dict(capture.executed),
        private_r7_dependency_executions=dict(bundle.graph.executed),
        private_parent_dependency_executions=dict(bundle.parent.graph.executed),
        worker_duration_seconds=time.perf_counter()-start,
        scope='bounded soil-stage scientific/source/restart verification; no optimisation or performance comparison')
    bundle.storage.write_json(path,record); capture.active=False
    print(json.dumps({'status':'PASS','tests':len(ids),'actual_mode':mode}),flush=True)
    return 0


def validate_worker(record,bundle,helper,mode):
    validate_tests(record['tests'])
    if (type(record.get('optimisation_flag')) is not int or record['optimisation_flag']!=mode
            or record.get('status')!='PASS' or record.get('source_identity')!=bundle.identity
            or record.get('source_sha256')!=bundle.source_sha256): raise ValueError('actual worker identity/status differs')
    validate_execution(record['executed_source_hashes'],bundle.identity,helper)
    if record['external_test_bindings']!=external_test_bindings(bundle): raise ValueError('worker external test binding differs')
    for key in ('private_r7_dependency_executions','private_parent_dependency_executions'):
        records=record[key]
        if type(records) is not dict or not records: raise ValueError('actual private dependency execution required')
        expected=source_map(bundle.identity,helper)
        for row in records.values():
            if expected.get(helper.canonical(row['path']))!=row['sha256']: raise ValueError('private dependency binding differs')
    return validate_artifacts(record['artifacts'],bundle)


def final(run_id):
    if type(run_id) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,47}',run_id): raise ValueError('bounded new run ID required')
    helper,capture=install()
    from work.generator_upgrade_r7 import binding
    bundle=binding.load(); _,ids=discover(helper); require_inventory(ids); stable(bundle,helper,capture)
    root=bundle.storage.plain_path(OUTPUT_ROOT/run_id); root.mkdir(parents=True,exist_ok=False)
    bundle.storage.write_json(root/'PARENT_SOURCE.json',{'source_identity':bundle.identity,
        'source_sha256':bundle.source_sha256,'parent_optimisation_flag':sys.flags.optimize,
        'external_test_bindings':external_test_bindings(bundle)})
    records=[]
    for label,mode,flags in (('n',0,[]),('o',2,['-OO'])):
        path=root/(label+'-worker.json')
        command=[sys.executable,'-B',*flags,str(HERE/'verify.py'),'--worker',str(path),'--parent-source',str(root/'PARENT_SOURCE.json'),'--mode',str(mode)]
        print('Executing exact-source scientific checks in mode '+str(mode),flush=True)
        try: process=subprocess.run(command,cwd=TASK,env=helper.child_environment(),capture_output=True,text=True,timeout=900)
        except subprocess.TimeoutExpired as error:
            bundle.storage.write_json(root/(label+'-process.json'),{'status':'TIMEOUT'}); raise RuntimeError('worker timed out; no PASS seal') from error
        bundle.storage.write_json(root/(label+'-process.json'),{'exit_code':process.returncode,'stdout':process.stdout,'stderr':process.stderr})
        if process.returncode: raise RuntimeError('worker failed; preserved attempt receipt: '+str(path))
        record=bundle.storage.read_json(path); validate_worker(record,bundle,helper,mode); records.append(record)
    for key in ('executed_source_hashes','private_r7_dependency_executions','private_parent_dependency_executions'):
        if records[0][key]!=records[1][key]: raise ValueError('cross-mode executed-code identity differs')
    if records[0]['artifacts']['reference_sha256']!=records[1]['artifacts']['reference_sha256']:
        raise ValueError('normal/-OO actual scientific result differs')
    stable(bundle,helper,capture)
    seal={'schema':'diadem.soil-stage-verification.r7','status':'BOUNDED_SOIL_FORMATION_REFERENCE_VERIFIED',
        'source_identity':bundle.identity,'source_sha256':bundle.source_sha256,'source_snapshot':bundle.identity['r7_sources'],
        'test_ids':ids,'test_count_per_mode':len(ids),'inventory_sha256':inventory_digest(ids),
        'workers':{label:{'path':str(root/(label+'-worker.json')),'sha256':sha((root/(label+'-worker.json')).read_bytes())} for label in ('n','o')},
        'normal_oo_parity':'EXACT_SCIENTIFIC_RESULT_AND_CHECKPOINT_PASS','parent_optimisation_flag':sys.flags.optimize,
        'actual_worker_flags':[r['optimisation_flag'] for r in records],
        'external_test_bindings':external_test_bindings(bundle),
        'production_installed':False,'canon_changed':False,'optimisation_performed':False,
        'scope':'bounded actual retained producer -> fixed-exposure formation/organic/fertility -> fresh formed-soil Water probe; no world production or invented historical climate'}
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
    raw=Path(__file__).read_bytes(); namespace={'__file__':__file__,'__name__':'_r7_fresh_verification_entry'}
    exec(compile(raw,__file__,'exec',dont_inherit=True),namespace)
    namespace['ENTRY_SOURCE_SHA256']=sha(raw)
    raise SystemExit(namespace['main']())
