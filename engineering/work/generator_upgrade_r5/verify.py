"""Focused exact-source R5 checks, retained Water regression and restart proof.

Only the sealed R4 verifier's source-loader/audit/test-result utilities are reused.
This is not a rerun or recount of its whole historical verification programme.
"""
from __future__ import annotations

import argparse
import importlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import types
import unittest

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
OUTPUT_ROOT = TASK / 'outputs/generator-upgrade-r5'
SUITES = ('test_binding', 'test_soil_diagnostics', 'test_experiments')
EXPECTED_NEW_COUNT = 52
NEW_INVENTORY_SHA256 = 'e6fbdaed2a442db78ced0de78dd3a917b05c3bfb23dd61b5e28c66cc239accba'
EXPECTED_RETAINED_COUNT = 29
RETAINED_INVENTORY_SHA256 = '02267a810378ea40d47872de8fb982b8c48c20f0b83afb80a7269134efe0bc9a'
ENTRY_SOURCE_SHA256 = None
R4_SEAL_SHA256 = 'f7382693a5284ebf111dc8a0622e5811440ccc7e2b546047943462b849926996'
WORKER_TIMEOUT_SECONDS = 600
RETAINED_PREFIX = 'retained-regression:work.generator_upgrade_r3.test_soil_water'


def sha(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def inventory_digest(ids):
    return sha(json.dumps(ids, separators=(',', ':'), ensure_ascii=True).encode())


def utility():
    """Fresh exact sealed bytes; no canonical predecessor module is modified."""
    seal = TASK / 'outputs/generator-upgrade-r4/connected-reference-01/VERIFICATION.json'
    raw = seal.read_bytes()
    if sha(raw) != R4_SEAL_SHA256:
        raise ValueError('retained verifier seal changed')
    record = json.loads(raw)
    path = TASK / 'work/generator_upgrade_r4/verify.py'
    raw = path.read_bytes()
    digest = record['source_snapshot'][str(path)]
    if sha(raw) != digest:
        raise ValueError('retained verifier utility source changed')
    module = types.ModuleType('_r5_sealed_verification_utilities')
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    return module, path, digest


def install():
    if ENTRY_SOURCE_SHA256 is None or any(k.startswith('work.') for k in sys.modules):
        raise ValueError('fresh source-compiled standalone verifier required')
    helper, path, digest = utility()
    capture = helper.ExecutionCapture()
    # These are the exact two bootstrapped executions preceding the audit hook.
    for key, value in ((str(HERE/'verify.py'), ENTRY_SOURCE_SHA256), (str(path), digest)):
        capture.compiled[key] = value
        capture.executed[key] = value
        helper.READS[key] = value
    sys.addaudithook(capture.observe)
    sys.meta_path.insert(0, helper.SourceFinder())
    return helper, capture


def source_map(identity, helper):
    result = helper.source_map(identity['retained_source_identity'])
    for path, digest in identity['r5_sources'].items():
        key = helper.canonical(path)
        if key in result and result[key] != digest:
            raise ValueError('conflicting exact source binding')
        result[key] = digest
    return result


def required_sources():
    return (tuple(HERE/(name+'.py') for name in (*SUITES, 'binding', 'verify', 'soil_water', 'experiments'))
        + tuple(TASK/('work/generator_upgrade_r4/'+name+'.py') for name in ('verify','pipeline','reference','climate','hydromet'))
        + tuple(TASK/('work/generator_upgrade_r3/'+name+'.py') for name in ('pipeline','test_soil_water','soil_inputs','terrain_transport')))


def validate_executed(executed, identity, helper, *, required=(), check_current=False):
    if type(executed) is not dict or not executed:
        raise ValueError('actual executed source evidence required')
    expected = source_map(identity, helper)
    seen = set()
    for path, digest in executed.items():
        key = helper.canonical(path)
        if key in seen or expected.get(key) != digest:
            raise ValueError('executed bytes differ from exact source capture')
        seen.add(key)
        if check_current and sha(Path(key).read_bytes()) != digest:
            raise ValueError('executed source changed after execution')
    if any(helper.canonical(path) not in seen for path in required):
        raise ValueError('required source was not actually executed')


def stable(bundle, helper, capture):
    bundle.verify()
    if bundle.identity['r5_sources'].get(str(HERE/'verify.py')) != ENTRY_SOURCE_SHA256:
        raise ValueError('entrypoint capture differs from bound source')
    validate_executed(capture.executed, bundle.identity, helper, check_current=True)
    if capture.derived_executed:
        raise ValueError('this bounded successor does not authorise derived source execution')
    for path, digest in helper.READS.items():
        if capture.executed.get(path) != digest:
            raise ValueError('fresh loader and actual execution records differ')


def discover(bundle, helper):
    if {p.name for p in HERE.glob('test_*.py')} != {name+'.py' for name in SUITES}:
        raise ValueError('test file inventory differs; no undisclosed suite')
    loader = unittest.TestLoader()
    new = loader.loadTestsFromNames(['work.generator_upgrade_r5.'+name for name in SUITES])
    retained_module = bundle.retained_soil_tests()
    retained = loader.loadTestsFromModule(retained_module)
    if loader.errors:
        raise ValueError('test import/discovery failed: '+repr(loader.errors))
    new_ids = [test.id() for test in helper.flatten(new)]
    old_prefix = retained_module.__name__
    def normalise(value):
        if not value.startswith(old_prefix+'.'):
            raise ValueError('retained test identity does not belong to exact private module')
        return RETAINED_PREFIX+value[len(old_prefix):]
    retained_ids = [normalise(test.id()) for test in helper.flatten(retained)]
    for ids in (new_ids, retained_ids):
        if not ids or len(ids) != len(set(ids)):
            raise ValueError('nonempty unique test identities required')
    return new, new_ids, retained, retained_ids, normalise


def require_inventory(ids, *, retained=False):
    count, digest = ((EXPECTED_RETAINED_COUNT, RETAINED_INVENTORY_SHA256) if retained
                     else (EXPECTED_NEW_COUNT, NEW_INVENTORY_SHA256))
    if type(count) is not int or count <= 0 or type(digest) is not str:
        raise ValueError('reviewed inventory is PENDING; no final seal authorised')
    if (type(ids) is not list or any(type(v) is not str for v in ids) or len(ids) != count
            or len(set(ids)) != count or inventory_digest(ids) != digest):
        raise ValueError('exact reviewed test inventory differs')
    return digest


def validate_tests(record, *, retained=False):
    count = EXPECTED_RETAINED_COUNT if retained else EXPECTED_NEW_COUNT
    keys = ('tests','failures','errors','skips','expected_failures','unexpected_successes')
    if any(type(record.get(key)) is not int for key in keys):
        raise ValueError('integer test counts required; bool is not a count')
    digest = require_inventory(record['test_ids'], retained=retained)
    if record.get('status') != 'PASS' or record['tests'] != count or any(record[k] for k in keys[1:]):
        raise ValueError('complete unskipped actual suite did not pass')
    if (record['inventory_sha256'] != digest or
            not record['test_ids'] == record['started'] == record['stopped'] == record['passed']):
        raise ValueError('discovery/start/stop/pass identities disagree')


def run_suite(suite, ids, helper, normalise=lambda value: value):
    stream = io.StringIO()
    start = time.perf_counter()
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helper.Result).run(suite)
    duration = time.perf_counter()-start
    return {'status': 'PASS' if result.wasSuccessful() else 'FAIL', 'tests': result.testsRun,
        'test_ids': ids, 'inventory_sha256': inventory_digest(ids),
        'started': list(map(normalise,result.started)), 'stopped': list(map(normalise,result.stopped)),
        'passed': list(map(normalise,result.passed)), 'failures':len(result.failures), 'errors':len(result.errors),
        'skips':len(result.skipped), 'expected_failures':len(result.expectedFailures),
        'unexpected_successes':len(result.unexpectedSuccesses), 'test_duration_seconds':duration,
        'test_log': stream.getvalue()}


def semantic(value):
    """Remove only the declared observational timer; retain all physics/gates."""
    if type(value) is dict:
        return {key:semantic(child) for key, child in value.items() if key != 'elapsed_wall_seconds'}
    if type(value) is list:
        return [semantic(child) for child in value]
    return value


def collect_experiments(bundle):
    module = importlib.import_module('work.generator_upgrade_r5.test_experiments')
    reports = bundle.storage.decoded(bundle.storage.encoded(module.StrictExperimentTests.reports))
    oracle = bundle.storage.read_json(module.ORACLE)
    if sha(module.ORACLE.read_bytes()) != module.ORACLE_SHA:
        raise ValueError('independent oracle test data changed')
    result = {'reports':reports, 'semantic_sha256':sha(encoded(semantic(reports))),
        'external_test_data':{'path':str(module.ORACLE),'sha256':module.ORACLE_SHA,
            'role':'pinned independent-integrator diagnostic test data, not executed code or physical input binding'},
        'oracle_final_head':oracle['independent_integrations'][-1]['final_head']}
    validate_experiments(result, bundle.source_sha256)
    return result


def validate_experiments(value, digest):
    reports = value.get('reports')
    if type(reports) is not list or len(reports) != 3:
        raise ValueError('three actual explicit-control experiment reports required')
    if [r.get('status') for r in reports] != ['NUMERICAL_FAILURE','NUMERICAL_FAILURE','MODELLED']:
        raise ValueError('original strict failure and explicitly supported sensitivity must remain distinguished')
    if value.get('semantic_sha256') != sha(encoded(semantic(reports))):
        raise ValueError('actual scientific diagnostic digest differs')
    for report in reports:
        if report.get('source_sha256') != digest or report.get('input_state_unchanged') is not True:
            raise ValueError('experiment source/input preservation differs')
    for report in reports[:2]:
        if 'following_state' in report:
            raise ValueError('failed experiment must not expose usable state')
    if 'following_state' not in reports[2]:
        raise ValueError('supported experiment actual state missing')
    data = value.get('external_test_data',{})
    if (type(data.get('sha256')) is not str or not re.fullmatch('[0-9a-f]{64}',data['sha256'])
            or type(data.get('path')) is not str or not Path(data['path']).is_absolute()):
        raise ValueError('exact external test-data identity required')


def artifact_reference(bundle, root):
    root.mkdir(exist_ok=False)
    s = bundle.storage
    recipe = bundle.wrap_recipe(bundle.reference.recipe(), evidence='SYNTHETIC default R4 reference with isolated R5 diagnostic solver; no implicit stricter controls')
    s.write_json(root/'recipe.json',recipe)
    recipe = s.read_json(root/'recipe.json')
    full = bundle.run(recipe)
    stopped = bundle.run(recipe,stop_after=1)
    stop_cp = bundle.checkpoint(stopped)
    s.write_json(root/'stop-result.json',stopped)
    s.write_json(root/'stop-checkpoint.json',stop_cp)
    restored = s.read_json(root/'stop-checkpoint.json')
    restarted = bundle.run(recipe,resume=restored)
    for stage,result in (('full',full),('restart',restarted)):
        s.write_json(root/(stage+'-result.json'),result)
        s.write_json(root/(stage+'-checkpoint.json'),bundle.checkpoint(result))
    names = ('recipe.json','stop-result.json','stop-checkpoint.json','full-result.json',
             'full-checkpoint.json','restart-result.json','restart-checkpoint.json')
    proof = {'path':str(root), 'files':{name:sha((root/name).read_bytes()) for name in names},
             'reference_sha256':sha(s.encoded(full)), 'entrypoint':'binding.Bundle.run and checkpoint; no new CLI claimed'}
    validate_artifacts(proof,bundle)
    return proof


def validate_artifacts(proof,bundle):
    root = bundle.storage.plain_path(proof['path'])
    names = {'recipe.json','stop-result.json','stop-checkpoint.json','full-result.json',
             'full-checkpoint.json','restart-result.json','restart-checkpoint.json'}
    if set(proof['files']) != names or {p.name for p in root.iterdir()} != names:
        raise ValueError('exact public wrapper artifact inventory differs')
    values = {}
    for name,digest in proof['files'].items():
        values[name] = bundle.storage.read_json(root/name)
        if sha((root/name).read_bytes()) != digest:
            raise ValueError('wrapper artifact changed after readback')
    full, restarted = values['full-result.json'], values['restart-result.json']
    if full != restarted or values['full-checkpoint.json'] != values['restart-checkpoint.json']:
        raise ValueError('actual full/restart state or checkpoint parity failed')
    if (full['source_sha256'] != bundle.source_sha256 or full['schema'] != 'diadem.precision-diagnostic-result.r5'
            or full['production_installed'] is not False or full['canon_changed'] is not False
            or proof['reference_sha256'] != sha(bundle.storage.encoded(full))
            or full['state']['completed_events'] != len(values['recipe.json']['retained_recipe']['events'])
            or values['stop-result.json']['state']['completed_events'] != 1):
        raise ValueError('actual completed source-bound R5 reference required')
    for stage in ('stop','full','restart'):
        result, cp = values[stage+'-result.json'], values[stage+'-checkpoint.json']
        if (cp != bundle.checkpoint(result) or cp['recipe_sha256'] != sha(bundle.storage.encoded(values['recipe.json']))):
            raise ValueError('saved recipe/result/checkpoint identity differs')
    return full


def worker(path,parent_path,mode):
    start = time.perf_counter()
    helper,capture = install()
    from work.generator_upgrade_r5 import binding
    bundle = binding.load()
    parent = bundle.storage.read_json(parent_path)
    if (sys.flags.optimize != mode or parent['source_identity'] != bundle.identity
            or parent['source_sha256'] != bundle.source_sha256):
        raise ValueError('worker actual mode/source differs from parent')
    new,ids,old,old_ids,normalise = discover(bundle,helper)
    require_inventory(ids); require_inventory(old_ids,retained=True)
    new_record = run_suite(new,ids,helper)
    old_record = run_suite(old,old_ids,helper,normalise)
    record = {'status':'FAIL','optimisation_flag':sys.flags.optimize,'source_identity':bundle.identity,
        'source_sha256':bundle.source_sha256,'new_tests':new_record,'retained_regression':old_record,
        'retained_regression_binding':'exact preserved R3 test bytes, explicit private R5 solver dependency; separately counted rerun'}
    try:
        validate_tests(new_record); validate_tests(old_record,retained=True)
    except ValueError:
        bundle.storage.write_json(path,record)
        capture.active = False
        return 1
    experiments = collect_experiments(bundle)
    experiment_path = path.parent/(path.stem+'-experiments.json')
    bundle.storage.write_json(experiment_path,experiments)
    record['experiments'] = {'path':str(experiment_path),'sha256':sha(experiment_path.read_bytes()),
        'semantic_sha256':experiments['semantic_sha256'],'external_test_data':experiments['external_test_data']}
    record['artifacts'] = artifact_reference(bundle,path.parent/(path.stem+'-reference'))
    stable(bundle,helper,capture)
    validate_executed(capture.executed,bundle.identity,helper,required=required_sources())
    record.update(status='PASS',executed_source_hashes=dict(capture.executed),
        private_dependency_executions=dict(bundle.graph.executed),
        test_duration_seconds=new_record['test_duration_seconds']+old_record['test_duration_seconds'],
        worker_duration_seconds=time.perf_counter()-start,
        duration_meaning='actual suite timing separate from source checks, three strict diagnostic trials cached by tests, default full/stop/restart and readback; no speedup benchmark')
    bundle.storage.write_json(path,record)
    capture.active = False
    print(json.dumps({'status':record['status'],'new_tests':len(ids),'retained_regression':len(old_ids),'actual_mode':mode}),flush=True)
    return 0


def validate_workers(records,bundle,helper):
    if type(records) is not list or len(records) != 2:
        raise ValueError('exactly two worker receipts required')
    fulls,diags = [],[]
    for record,mode in zip(records,(0,2)):
        if type(record.get('optimisation_flag')) is not int or record['optimisation_flag'] != mode:
            raise ValueError('actual normal/-OO modes required; inherited flags are not evidence')
        validate_tests(record['new_tests']); validate_tests(record['retained_regression'],retained=True)
        if record.get('status') != 'PASS' or record['source_identity'] != bundle.identity or record['source_sha256'] != bundle.source_sha256:
            raise ValueError('worker source/status differs from parent')
        validate_executed(record['executed_source_hashes'],bundle.identity,helper,required=required_sources(),check_current=True)
        for key in ('test_duration_seconds','worker_duration_seconds'):
            value = record.get(key)
            if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
                raise ValueError('finite nonnegative timing required')
        if record['worker_duration_seconds'] < record['test_duration_seconds']:
            raise ValueError('complete worker shorter than tests')
        fulls.append(validate_artifacts(record['artifacts'],bundle))
        proof = record['experiments']
        diagnostic = bundle.storage.read_json(proof['path'])
        if sha(Path(proof['path']).read_bytes()) != proof['sha256'] or diagnostic['semantic_sha256'] != proof['semantic_sha256']:
            raise ValueError('saved scientific diagnostic changed')
        validate_experiments(diagnostic,bundle.source_sha256)
        if diagnostic['external_test_data'] != proof['external_test_data']:
            raise ValueError('external test data evidence differs')
        data = diagnostic['external_test_data']
        if sha(binding_checked(data['path'])) != data['sha256']:
            raise ValueError('independent oracle test data changed after worker')
        diags.append(semantic(diagnostic))
    for key in ('executed_source_hashes','private_dependency_executions'):
        if records[0][key] != records[1][key]:
            raise ValueError('actual mode execution-source disagreement')
    if fulls[0] != fulls[1] or diags[0] != diags[1]:
        raise ValueError('normal/-OO actual reference or scientific diagnostic disagreement')


def binding_checked(path):
    from work.generator_upgrade_r5 import binding
    return binding.checked(path)


def final(run_id):
    if type(run_id) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,47}',run_id):
        raise ValueError('bounded new run ID required')
    helper,capture = install()
    from work.generator_upgrade_r5 import binding
    bundle = binding.load()
    _,ids,_,old_ids,_ = discover(bundle,helper)
    require_inventory(ids); require_inventory(old_ids,retained=True)
    root = bundle.storage.plain_path(OUTPUT_ROOT/run_id)
    root.mkdir(parents=True,exist_ok=False)
    bundle.storage.write_json(root/'PARENT_SOURCE.json',{'source_identity':bundle.identity,'source_sha256':bundle.source_sha256,
        'parent_optimisation_flag':sys.flags.optimize})
    records = []
    for label,mode,flags in (('n',0,[]),('o',2,['-OO'])):
        path = root/(label+'-worker.json')
        command = [sys.executable,'-B',*flags,str(HERE/'verify.py'),'--worker',str(path),
            '--parent-source',str(root/'PARENT_SOURCE.json'),'--mode',str(mode)]
        print('Executing source-bound mode '+str(mode),flush=True)
        try:
            result = subprocess.run(command,cwd=TASK,env=helper.child_environment(),capture_output=True,text=True,timeout=WORKER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            bundle.storage.write_json(root/(label+'-process.json'),{'status':'TIMEOUT','timeout_seconds':WORKER_TIMEOUT_SECONDS})
            raise RuntimeError('bounded verification worker timed out; no PASS seal') from error
        bundle.storage.write_json(root/(label+'-process.json'),{'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        if result.returncode:
            raise RuntimeError('verification worker failed; diagnostics preserved at '+str(root))
        records.append(bundle.storage.read_json(path))
    validate_workers(records,bundle,helper)
    stable(bundle,helper,capture)
    receipt = {'schema':'diadem.precision-diagnostic-verification.r5','status':'BOUNDED_DIAGNOSTIC_SUCCESSOR_VERIFIED',
        'source_identity':bundle.identity,'source_sha256':bundle.source_sha256,'source_snapshot':bundle.identity['r5_sources'],
        'new_distinct_checks':len(ids),'new_test_ids':ids,'new_inventory_sha256':NEW_INVENTORY_SHA256,
        'retained_regression_checks':len(old_ids),'retained_test_ids':old_ids,'retained_inventory_sha256':RETAINED_INVENTORY_SHA256,
        'retained_regression_is_new_tests':False,'actual_interpreter_modes':[0,2], 'parent_optimisation_flag':sys.flags.optimize,
        'runs_per_check':2,'failures':0,'errors':0,'skips':0,
        'workers':[{'path':str(root/(label+'-worker.json')),'sha256':sha((root/(label+'-worker.json')).read_bytes()),
            'test_duration_seconds':row['test_duration_seconds'],'worker_duration_seconds':row['worker_duration_seconds'],
            'experiments':row['experiments'],'artifacts':row['artifacts']} for label,row in zip(('n','o'),records)],
        'executed_source_hashes':records[0]['executed_source_hashes'],'private_dependency_executions':records[0]['private_dependency_executions'],
        'reference_sha256':records[0]['artifacts']['reference_sha256'],
        'strict_diagnostics_semantic_sha256':records[0]['experiments']['semantic_sha256'],
        'external_test_data':records[0]['experiments']['external_test_data'],
        'production_installed':False,'canon_changed':False,'world_generated':False,'generation_speedup_percent':None,
        'strict_original_case_now_passes':False,'nonlinear_or_physical_algorithm_changed':False,
        'scope':'isolated exact preserved climate/hydromet/terrain/soil pipeline; numerical diagnostics and explicit finite-work sensitivity, not implicit tolerance relaxation or universal precision support'}
    bundle.storage.write_json(root/'VERIFICATION.json',receipt)
    if bundle.storage.read_json(root/'VERIFICATION.json') != receipt:
        raise IOError('final receipt readback mismatch')
    capture.active = False
    print(json.dumps({'status':receipt['status'],'new_checks':len(ids),'retained_regression':len(old_ids)}),flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--inventory',action='store_true')
    action.add_argument('--run-id')
    action.add_argument('--worker',type=Path)
    parser.add_argument('--parent-source',type=Path)
    parser.add_argument('--mode',type=int,choices=(0,2))
    args = parser.parse_args()
    if args.inventory:
        helper,capture = install()
        from work.generator_upgrade_r5 import binding
        bundle = binding.load()
        _,ids,_,old_ids,_ = discover(bundle,helper)
        stable(bundle,helper,capture)
        capture.active = False
        print(json.dumps({'status':'DISCOVERY_ONLY_NOT_VERIFICATION','new_count':len(ids),'new_sha256':inventory_digest(ids),
            'retained_count':len(old_ids),'retained_sha256':inventory_digest(old_ids),'new_ids':ids,'retained_ids':old_ids}),flush=True)
        return 0
    if args.worker:
        if args.parent_source is None or args.mode is None:
            parser.error('worker requires parent-source and actual mode')
        return worker(args.worker,args.parent_source,args.mode)
    return final(args.run_id)


def bootstrap():
    path = Path(__file__).resolve()
    raw = path.read_bytes()
    namespace = {'__name__':'__verified_r5_entry__','__file__':str(path)}
    exec(compile(raw,str(path),'exec',dont_inherit=True),namespace)
    namespace['ENTRY_SOURCE_SHA256'] = sha(raw)
    return namespace['main']()


if __name__ == '__main__':
    raise SystemExit(bootstrap())
