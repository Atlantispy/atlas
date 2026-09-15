"""Commit two verified R4 shoreline reports; never publish/adopt terrain."""
from __future__ import annotations

# Only this forwarding bootstrap runs before source capture. The release module
# itself is then compiled again, under its canonical name, from captured bytes.
if __name__ == '__main__':
    from pathlib import Path as _BootstrapPath
    import sys as _bootstrap_sys
    import types as _bootstrap_types
    _helper_path = _BootstrapPath(__file__).absolute().with_name('release_source_runtime.py')
    _helper_raw = _helper_path.read_bytes()
    _helper = _bootstrap_types.ModuleType('_r5_release_source_runtime')
    _helper.__file__ = str(_helper_path)
    _helper.EXECUTED_SOURCE_BYTES = _helper_raw
    _bootstrap_sys.modules[_helper.__name__] = _helper
    exec(compile(_helper_raw, str(_helper_path), 'exec', dont_inherit=True, optimize=0), _helper.__dict__)
    raise SystemExit(_helper.launch(_helper_path.parent))

import argparse
import hashlib
import io as string_io
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import unittest

try:
    import msvcrt
except ImportError:  # The sealed commit path deliberately fails closed elsewhere.
    msvcrt=None

import shoreline_verification as verification
from r4_io import io

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1] / 'outputs' / 'terrain-model-r5'
NAMES = ('EVIDENCE-A.json','EVIDENCE-B.json','SCIENTIFIC-RESULT.json','RECEIPT.json')
MAX_FILE = 16*1024*1024
MAX_TOTAL = 64*1024*1024
# The 26 replay-heavy workflow regressions alone measured 198.061 seconds.
# This total worker bound does not enlarge any numerical generation deadline.
TEST_WORKER_TIMEOUT_SECONDS = 600
REQUIRED_RUNTIME_FILES = ('capture.py', 'phase_storage.py', 'r3_bindings.py', 'r4_io.py',
                          'release_shoreline_reference.py', 'release_source_runtime.py',
                          'shoreline_driver.py', 'shoreline_verification.py')
EXPECTED_TEST_COUNT = 367
EXPECTED_TEST_MODULES = (
    'test_capture','test_capture_workflow','test_continuous_pool','test_event_settling',
    'test_exact_forced_endpoint','test_forced_drying','test_phase_storage',
    'test_predecessor_binding','test_release_shoreline_reference','test_repairs',
    'test_shoreline','test_shoreline_driver','test_shoreline_materials',
    'test_shoreline_network','test_shoreline_verification','test_shoreline_workflow',
)
EXPECTED_TEST_FILES = tuple(name+'.py' for name in EXPECTED_TEST_MODULES)
EXPECTED_TEST_IDS_SHA256 = '29780ad1a1e2e35f8c300c781c8c6be6489ff42c08a959754bf1dd50881cb7de'
# Compared against the frozen R4 report: all nested shapes/types are identical
# after replacing only its 64-row source list with the current 111-row closure.
EXPECTED_TIMED_REPORT_SHAPE_SHA256 = 'd4fe64c7fb2dba7ff47319b5fe3246033c8ffed234623ea35f19a8b0e540eae1'
EXPECTED_SCIENTIFIC_REPORT_SHAPE_SHA256 = '96a5c33f5727fa2fd3bbfcf35e6c87f17275d9b14b020c8ac3eadf424f8f640f'

IDENTITY_KEYS = {'sources','controls','python','platform','generation_id','physical_acceptance',
                 'production_authorised','diadem_canon_changed'}
CONTROL_KEYS = {'verification_dts','repeat_dt','duration_years','extra_finer','scope',
                'expected_test_count','expected_test_modules','expected_test_ids_sha256'}
REPORT_KEYS = {
    'schema','status','scope','prepared_state_sha256','prepared_state','prepared_control_sha256',
    'soil_dissolved_rock_export_kg','sources','cases','initial_refinement','refinement',
    'recipient_stability','additional_reference_requested','identical_repeat',
    'json_checkpoint_restart','whole_verification_wall_seconds','physical_acceptance',
    'production_authorised','workflow_adoption','fresh_optimisation_speedup_established',
    'optimisation_speedup_percent','retained_r2_rejection','comparison_soil_preparation_count',
    'soil_prefix_result_sha256','original_recipe_sha256',
}
RECEIPT_KEYS = {'identity','products','test_workers','executed_local_sources','scientific_result_sha256',
                'physical_acceptance','production_authorised','diadem_canon_changed'}
WORKER_KEYS = {'schema','status','tests_run','test_ids','test_ids_sha256','test_modules',
               'discovered_test_files','failures','errors','skipped','expected_failures',
               'unexpected_successes','loader_errors','source_snapshot_sha256',
               'sources_unchanged','python','platform','test_log_sha256','elapsed_seconds',
               'return_code','started_test_ids','stopped_test_ids','successful_test_ids',
               'executed_local_sources'}
AUTHORITY_FALSE = ('physical_acceptance','production_authorised')
AUTHORITY_FLAG_KEYS = {'physical_acceptance','production_authorised','workflow_adoption',
                       'diadem_canon_changed','canon_changed','shoreline_capture_acceptance'}
TIMING_KEYS = {'driver_and_validation_wall_seconds','whole_verification_wall_seconds'}


def _exact_keys(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(label+' schema differs')


def _finite_nonnegative(value, label):
    if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
        raise ValueError(label+' must be a finite nonnegative number')


def _walk_key_paths(value, names, prefix=()):
    found=[]
    if isinstance(value,dict):
        for key,item in value.items():
            path=prefix+(key,)
            if key in names:found.append(path)
            found.extend(_walk_key_paths(item,names,path))
    elif isinstance(value,list):
        for index,item in enumerate(value):found.extend(_walk_key_paths(item,names,prefix+(index,)))
    return found


def _require_false_authority_flags(value, prefix=()):
    if isinstance(value,dict):
        for key,item in value.items():
            if key in AUTHORITY_FLAG_KEYS and item is not False:
                raise ValueError('authority/adoption/canon flag is not false: '+'.'.join(map(str,prefix+(key,))))
            _require_false_authority_flags(item,prefix+(key,))
    elif isinstance(value,list):
        for index,item in enumerate(value):_require_false_authority_flags(item,prefix+(index,))


def _shape_digest(value):
    """Hash every nested JSON key, type and list length, but no scalar value."""
    digest=hashlib.sha256()
    def token(value):
        if type(value) is dict:
            digest.update(b'{');digest.update(str(len(value)).encode('ascii'));digest.update(b':')
            for key in sorted(value):
                raw=key.encode('utf-8');digest.update(str(len(raw)).encode('ascii'));digest.update(b':'+raw)
                token(value[key])
            digest.update(b'}')
        elif type(value) is list:
            digest.update(b'['+str(len(value)).encode('ascii')+b':')
            for item in value:token(item)
            digest.update(b']')
        elif value is None:digest.update(b'n')
        elif type(value) is bool:digest.update(b'b')
        elif type(value) is int:digest.update(b'i')
        elif type(value) is float:digest.update(b'f')
        elif type(value) is str:digest.update(b's')
        else:raise ValueError('verification report contains a non-JSON value')
    token(value)
    return digest.hexdigest()


def _allowed_timing_paths(report):
    paths=[('whole_verification_wall_seconds',)]
    paths.extend(('cases',index,'driver_and_validation_wall_seconds')
                 for index in range(len(report['cases'])))
    paths.extend((
        ('identical_repeat','run','driver_and_validation_wall_seconds'),
        ('json_checkpoint_restart','first','driver_and_validation_wall_seconds'),
        ('json_checkpoint_restart','second','driver_and_validation_wall_seconds'),
    ))
    return set(paths)


def _validate_report(report, identity, *, timed):
    expected_keys=REPORT_KEYS if timed else REPORT_KEYS-{'whole_verification_wall_seconds'}
    _exact_keys(report,expected_keys,'verification report')
    if report['schema']!='diadem.terrain.shoreline-verification.r4' or report['status']!='PASS':
        raise ValueError('verification report identity/status differs')
    if report['scope']!='BOUNDED_SYNTHETIC_NUMERICAL_DRIVER_VERIFICATION_ONLY':
        raise ValueError('verification report scope differs')
    if report['sources']!=identity['sources'] or report['additional_reference_requested'] is not False:
        raise ValueError('verification report source/control binding differs')
    for key in AUTHORITY_FALSE:
        if report.get(key) is not False:raise ValueError('verification report authority differs: '+key)
    if (report.get('workflow_adoption') is not False
            or report.get('fresh_optimisation_speedup_established') is not False
            or report.get('optimisation_speedup_percent') is not None):
        raise ValueError('verification report adoption/optimisation status differs')
    _require_false_authority_flags(report)
    if type(report['cases']) is not list or len(report['cases'])!=len(verification.DEFAULT_DTS):
        raise ValueError('verification report case inventory differs')
    if [row.get('dt_years') for row in report['cases']]!=list(verification.DEFAULT_DTS):
        raise ValueError('verification report timestep inventory differs')
    if any(type(row) is not dict or row.get('status')!='PASS' for row in report['cases']):
        raise ValueError('verification report contains an unsuccessful case')
    if (report['identical_repeat'].get('status')!='PASS'
            or report['json_checkpoint_restart'].get('status')!='PASS'
            or report['refinement'].get('status')!='PASS'
            or report['recipient_stability'].get('status')!='PASS'
            or report['retained_r2_rejection'].get('status')!='PASS_RETAINED_REJECTION'
            or report['retained_r2_rejection'].get('recipe_unchanged') is not True):
        raise ValueError('verification report proof gates differ')
    found=set(_walk_key_paths(report,TIMING_KEYS))
    expected=_allowed_timing_paths(report) if timed else set()
    if found!=expected:raise ValueError('verification timing field locations differ')
    for path in found:
        value=report
        for part in path:value=value[part]
        _finite_nonnegative(value,'verification timing')
    expected_shape=(EXPECTED_TIMED_REPORT_SHAPE_SHA256 if timed
                    else EXPECTED_SCIENTIFIC_REPORT_SHAPE_SHA256)
    if _shape_digest(report)!=expected_shape:raise ValueError('verification nested shape/type fingerprint differs')


def _strip_timing(value, identity):
    """Remove only the nine declared wall timings after strict schema validation."""
    _validate_report(value,identity,timed=True)
    result=io.parse_json(io.canonical(value))
    del result['whole_verification_wall_seconds']
    for row in result['cases']:del row['driver_and_validation_wall_seconds']
    del result['identical_repeat']['run']['driver_and_validation_wall_seconds']
    del result['json_checkpoint_restart']['first']['driver_and_validation_wall_seconds']
    del result['json_checkpoint_restart']['second']['driver_and_validation_wall_seconds']
    _validate_report(result,identity,timed=False)
    return result


def _reject_reparse_chain(path):
    lexical=Path(path).absolute()
    for current in (lexical,*lexical.parents):
        try:stat=current.lstat()
        except FileNotFoundError:continue
        junction=getattr(current,'is_junction',lambda:False)()
        if current.is_symlink() or junction or getattr(stat,'st_file_attributes',0)&0x400:
            raise ValueError('linked/reparse release path rejected: '+str(current))


def _guard(root, path, *, direct_child=False):
    _reject_reparse_chain(root);_reject_reparse_chain(path)
    root=io.unlinked(root);path=io.unlinked(path)
    _reject_reparse_chain(root);_reject_reparse_chain(path)
    if path==root or not path.is_relative_to(root):raise ValueError('release path escaped exact R4 evidence root')
    if direct_child and path.parent!=root:raise ValueError('release must be a direct child of exact R4 evidence root')
    return root,path


def _write_new(root, path, value):
    root,path=_guard(root,path)
    parent=io.unlinked(path.parent)
    if not parent.is_dir():raise ValueError('release product parent is not a normal directory')
    data=io.canonical(value)
    if len(data)>MAX_FILE:raise ValueError('release product exceeds per-file bound')
    _guard(root,path)
    with path.open('xb') as stream:
        opened=os.fstat(stream.fileno());_guard(root,path)
        visible=path.stat()
        if (opened.st_dev,opened.st_ino)!=(visible.st_dev,visible.st_ino):
            raise ValueError('release product path changed after exclusive creation')
        if opened.st_nlink!=1 or visible.st_nlink!=1:
            raise ValueError('hard-linked release product rejected before write')
        stream.write(data);stream.flush();os.fsync(stream.fileno())
        opened=os.fstat(stream.fileno());_guard(root,path);visible=path.stat()
        if (opened.st_dev,opened.st_ino,opened.st_size)!=(visible.st_dev,visible.st_ino,visible.st_size):
            raise ValueError('release product path changed during write')
        if opened.st_nlink!=1 or visible.st_nlink!=1:
            raise ValueError('hard-linked release product rejected after write')
    _guard(root,path)
    if io.read_bytes(path)!=data:raise ValueError('release product readback mismatch')


def _pin(directory,name):
    data=io.read_bytes(directory/name,MAX_FILE)
    return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def _source_runtime_check(sources=None):
    bootstrap=sys.modules.get('_r5_release_source_runtime')
    runtime=getattr(bootstrap,'ACTIVE',None)
    if runtime is None or runtime.root!=HERE:
        raise ValueError('release execution requires the exact-source CLI bootstrap in a fresh process')
    loaded=runtime.check()
    if sources is not None:
        local=[row for row in sources if '/' not in row['name']]
        if runtime.pins!=local:raise ValueError('captured release sources differ from identity')
    return loaded


def _validate_executed_sources(loaded,sources,*,tests=False):
    if type(loaded) is not list or not loaded:
        raise ValueError('executed release source inventory is empty')
    source_map={row['name']:row for row in sources}
    names=[]
    for row in loaded:
        _exact_keys(row,{'name','bytes','sha256'},'executed source pin')
        name=row['name']
        if type(name) is not str or '/' in name or '\\' in name or not name.endswith('.py'):
            raise ValueError('executed source is not a local Python file')
        if row!=source_map.get(name):raise ValueError('executed source bytes differ from source identity')
        names.append(name)
    if names!=sorted(set(names)):
        raise ValueError('executed source inventory is duplicate or unordered')
    required=set(REQUIRED_RUNTIME_FILES)
    if tests:
        required.update(row['name'] for row in sources
                        if '/' not in row['name'] and row['name'].endswith('.py'))
        required.update(EXPECTED_TEST_FILES)
    if not required<=set(names):raise ValueError('required executed release source missing')


def _identity():
    sources=verification.source_snapshot()
    _source_runtime_check(sources)
    controls={'verification_dts':list(verification.DEFAULT_DTS),'repeat_dt':.025,
              'duration_years':.8,'extra_finer':False,
              'scope':'BOUNDED_SYNTHETIC_NUMERICAL_SHORELINE_R4',
              'expected_test_count':EXPECTED_TEST_COUNT,
              'expected_test_modules':list(EXPECTED_TEST_MODULES),
              'expected_test_ids_sha256':EXPECTED_TEST_IDS_SHA256}
    core={'sources':sources,'controls':controls,'python':sys.version,'platform':platform.platform()}
    return {**core,'generation_id':hashlib.sha256(io.canonical(core)).hexdigest(),
            'physical_acceptance':False,'production_authorised':False,'diadem_canon_changed':False}


def _validate_identity(identity):
    _exact_keys(identity,IDENTITY_KEYS,'release identity')
    _exact_keys(identity['controls'],CONTROL_KEYS,'release controls')
    if type(identity['sources']) is not list or not identity['sources']:
        raise ValueError('release source inventory is empty')
    names=[]
    for row in identity['sources']:
        _exact_keys(row,{'name','bytes','sha256'},'release source pin')
        if (type(row['name']) is not str or type(row['bytes']) is not int or row['bytes']<0
                or type(row['sha256']) is not str or not re.fullmatch(r'[0-9a-f]{64}',row['sha256'])):
            raise ValueError('release source pin is malformed')
        names.append(row['name'])
    if len(set(names))!=len(names):raise ValueError('release source inventory contains duplicates')
    if identity['controls']!={
            'verification_dts':list(verification.DEFAULT_DTS),'repeat_dt':.025,
            'duration_years':.8,'extra_finer':False,
            'scope':'BOUNDED_SYNTHETIC_NUMERICAL_SHORELINE_R4',
            'expected_test_count':EXPECTED_TEST_COUNT,
            'expected_test_modules':list(EXPECTED_TEST_MODULES),
            'expected_test_ids_sha256':EXPECTED_TEST_IDS_SHA256}:
        raise ValueError('release controls differ')
    if any(identity.get(key) is not False for key in
           ('physical_acceptance','production_authorised','diadem_canon_changed')):
        raise ValueError('release identity asserts unavailable authority')
    core={key:identity[key] for key in ('sources','controls','python','platform')}
    if identity['generation_id']!=hashlib.sha256(io.canonical(core)).hexdigest():
        raise ValueError('release generation identity differs')


def _validate_worker(worker,identity):
    _exact_keys(worker,WORKER_KEYS,'test worker receipt')
    _validate_identity(identity)
    if worker['schema']!='diadem.terrain.shoreline-test-worker.r4' or worker['status']!='PASS':
        raise ValueError('test worker did not PASS')
    if (type(worker['tests_run']) is not int or worker['tests_run']!=EXPECTED_TEST_COUNT or type(worker['test_ids']) is not list
            or len(worker['test_ids'])!=EXPECTED_TEST_COUNT
            or len(set(worker['test_ids']))!=EXPECTED_TEST_COUNT):
        raise ValueError('test worker count/ID inventory differs')
    if (hashlib.sha256(io.canonical(worker['test_ids'])).hexdigest()!=EXPECTED_TEST_IDS_SHA256
            or worker['test_ids_sha256']!=EXPECTED_TEST_IDS_SHA256):
        raise ValueError('test worker ordered ID digest differs')
    for key in ('started_test_ids','stopped_test_ids','successful_test_ids'):
        if worker[key]!=worker['test_ids']:
            raise ValueError('test worker executed ID inventory differs: '+key)
    if worker['test_modules']!=list(EXPECTED_TEST_MODULES):raise ValueError('test worker module inventory differs')
    if worker['discovered_test_files']!=list(EXPECTED_TEST_FILES):raise ValueError('test worker file inventory differs')
    for key in ('failures','errors','skipped','expected_failures','unexpected_successes'):
        if type(worker[key]) is not int or worker[key]!=0:raise ValueError('test worker '+key+' is not integer zero')
    if worker['loader_errors']!=[] or type(worker['return_code']) is not int or worker['return_code']!=0:
        raise ValueError('test worker loader/process failed')
    expected_source=hashlib.sha256(io.canonical(identity['sources'])).hexdigest()
    if worker['sources_unchanged'] is not True or worker['source_snapshot_sha256']!=expected_source:
        raise ValueError('test worker source closure differs')
    _validate_executed_sources(worker['executed_local_sources'],identity['sources'],tests=True)
    if worker['python']!=identity['python'] or worker['platform']!=identity['platform']:
        raise ValueError('test worker runtime differs')
    _finite_nonnegative(worker['elapsed_seconds'],'test worker elapsed time')
    if not re.fullmatch(r'[0-9a-f]{64}',worker['test_log_sha256']):raise ValueError('test worker log digest malformed')


def verify(directory,identity):
    root,directory=_guard(ROOT,directory,direct_child=True)
    _validate_identity(identity)
    if not directory.is_dir():raise ValueError('release directory is absent')
    if {p.name for p in directory.iterdir()} != set(NAMES):raise ValueError('release file inventory differs')
    for name in NAMES:
        path=directory/name;_guard(root,path);stat=path.stat()
        if not path.is_file() or stat.st_nlink!=1:
            raise ValueError('release evidence must be a singly-linked regular file: '+name)
    receipt=io.read_json(directory/'RECEIPT.json');_exact_keys(receipt,RECEIPT_KEYS,'release receipt')
    if io.canonical(receipt['identity'])!=io.canonical(identity):raise ValueError('release identity/source changed')
    if type(receipt['products']) is not dict or set(receipt['products'])!=set(NAMES)-{'RECEIPT.json'}:
        raise ValueError('release receipt product list differs')
    for name,pin in receipt['products'].items():
        _exact_keys(pin,{'bytes','sha256'},'release product pin')
        if _pin(directory,name)!=pin:raise ValueError('release product corrupt: '+name)
    if type(receipt['test_workers']) is not list or len(receipt['test_workers'])!=2:
        raise ValueError('release requires exactly two test workers')
    for worker in receipt['test_workers']:_validate_worker(worker,identity)
    _validate_executed_sources(receipt['executed_local_sources'],identity['sources'])
    a,b,s=(io.read_json(directory/name) for name in NAMES[:3])
    _validate_report(a,identity,timed=True);_validate_report(b,identity,timed=True)
    _validate_report(s,identity,timed=False)
    if io.canonical(_strip_timing(a,identity))!=io.canonical(s) or io.canonical(_strip_timing(b,identity))!=io.canonical(s):
        raise ValueError('repeat scientific reports differ')
    if receipt['scientific_result_sha256']!=receipt['products']['SCIENTIFIC-RESULT.json']['sha256']:
        raise ValueError('scientific result receipt binding differs')
    if any(receipt.get(key) is not False for key in
           ('physical_acceptance','production_authorised','diadem_canon_changed')):
        raise ValueError('release receipt asserts unavailable authority')
    if sum(p.stat().st_size for p in directory.iterdir())>MAX_TOTAL:
        raise ValueError('release size envelope differs')
    _guard(root,directory,direct_child=True)
    return receipt


def _suite_ids(suite):
    result=[]
    for test in suite:
        result.extend(_suite_ids(test) if isinstance(test,unittest.TestSuite) else [test.id()])
    return result


class TrackedResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.started_ids=[];self.stopped_ids=[];self.success_ids=[]

    def startTest(self,test):
        self.started_ids.append(test.id());super().startTest(test)

    def stopTest(self,test):
        self.stopped_ids.append(test.id());super().stopTest(test)

    def addSuccess(self,test):
        self.success_ids.append(test.id());super().addSuccess(test)


def _executed_exactly(tested,ids):
    return (tested.started_ids==ids and tested.stopped_ids==ids and tested.success_ids==ids
            and tested.testsRun==len(ids) and len(set(ids))==len(ids)
            and tested.wasSuccessful() and not tested.failures and not tested.errors
            and not tested.skipped and not tested.expectedFailures and not tested.unexpectedSuccesses)


def _run_test_suite():
    before=verification.source_snapshot();loader=unittest.TestLoader()
    _source_runtime_check(before)
    suite=loader.discover(str(HERE),pattern='test_*.py',top_level_dir=str(HERE))
    ids=_suite_ids(suite);stream=string_io.StringIO()
    tested=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=TrackedResult).run(suite)
    after=verification.source_snapshot();modules=sorted({name.split('.',1)[0] for name in ids})
    executed_sources=_source_runtime_check(after)
    _validate_executed_sources(executed_sources,after,tests=True)
    files=sorted(path.name for path in HERE.glob('test_*.py'))
    ids_sha=hashlib.sha256(io.canonical(ids)).hexdigest()
    passed=(tested.testsRun==EXPECTED_TEST_COUNT==len(ids)>0 and len(set(ids))==len(ids)
            and ids_sha==EXPECTED_TEST_IDS_SHA256 and modules==list(EXPECTED_TEST_MODULES)
            and files==list(EXPECTED_TEST_FILES) and _executed_exactly(tested,ids)
            and not tested.skipped and not tested.expectedFailures and not tested.unexpectedSuccesses
            and not loader.errors and before==after==verification.LOADED_SOURCE_PINS)
    return {'schema':'diadem.terrain.shoreline-test-worker.r4','status':'PASS' if passed else 'FAIL',
            'tests_run':tested.testsRun,'test_ids':ids,'test_ids_sha256':ids_sha,
            'started_test_ids':tested.started_ids,'stopped_test_ids':tested.stopped_ids,
            'successful_test_ids':tested.success_ids,'executed_local_sources':executed_sources,
            'test_modules':modules,'discovered_test_files':files,
            'failures':len(tested.failures),'errors':len(tested.errors),'skipped':len(tested.skipped),
            'expected_failures':len(tested.expectedFailures),
            'unexpected_successes':len(tested.unexpectedSuccesses),'loader_errors':loader.errors,
            'source_snapshot_sha256':hashlib.sha256(io.canonical(before)).hexdigest(),
            'sources_unchanged':before==after==verification.LOADED_SOURCE_PINS,
            'python':sys.version,'platform':platform.platform(),
            'test_log_sha256':hashlib.sha256(stream.getvalue().encode()).hexdigest(),
            'elapsed_seconds':0.,'return_code':0 if passed else 1}


def _test_worker(identity):
    started=time.perf_counter()
    command=[sys.executable,'-B',str(Path(__file__).resolve()),'--test-worker']
    completed=subprocess.run(command,cwd=str(HERE.parents[1]),capture_output=True,
                             timeout=TEST_WORKER_TIMEOUT_SECONDS)
    try:report=io.parse_json(completed.stdout.strip())
    except Exception as exc:raise ValueError('fresh R4 test worker returned malformed evidence') from exc
    report['elapsed_seconds']=time.perf_counter()-started
    report['return_code']=completed.returncode
    if completed.stderr:raise ValueError('fresh R4 test worker wrote unexpected stderr')
    _validate_worker(report,identity)
    return report


def _lock_path(root,output):
    return root/(output.name+'.release.lock')


def _acquire_lock(root,output,generation):
    if sys.platform!='win32' or msvcrt is None:
        raise RuntimeError('sealed no-clobber release is implemented only for Windows')
    root,lock=_guard(root,_lock_path(root,output),direct_child=True)
    _guard(root,lock,direct_child=True)
    flags=os.O_CREAT|os.O_RDWR|getattr(os,'O_BINARY',0)
    descriptor=os.open(lock,flags,0o600)
    locked=False
    try:
        opened=os.fstat(descriptor);_guard(root,lock,direct_child=True);visible=lock.stat()
        if (opened.st_dev,opened.st_ino)!=(visible.st_dev,visible.st_ino):
            raise ValueError('release lock path changed during open')
        if opened.st_nlink!=1 or visible.st_nlink!=1:
            raise ValueError('hard-linked release lock rejected')
        os.lseek(descriptor,0,os.SEEK_SET)
        try:msvcrt.locking(descriptor,msvcrt.LK_NBLCK,1)
        except OSError as exc:raise FileExistsError('release target is locked by another live process') from exc
        locked=True
        stat=os.fstat(descriptor)
        identity=(stat.st_dev,stat.st_ino,stat.st_size)
        _guard(root,lock,direct_child=True);visible=lock.stat()
        if visible.st_nlink!=1 or stat.st_nlink!=1 or (visible.st_dev,visible.st_ino,visible.st_size)!=identity:
            raise ValueError('release lock changed during acquisition')
        return descriptor,lock,identity
    except BaseException:
        if locked:
            try:
                os.lseek(descriptor,0,os.SEEK_SET);msvcrt.locking(descriptor,msvcrt.LK_UNLCK,1)
            except OSError:pass
        os.close(descriptor)
        raise


def _release_lock(root,descriptor,lock,identity):
    error=None
    try:
        _guard(root,lock,direct_child=True);stat=lock.stat()
        if stat.st_nlink!=1 or (stat.st_dev,stat.st_ino,stat.st_size)!=identity:
            error=ValueError('release lock identity changed while held')
    except Exception as exc:error=exc
    try:
        os.lseek(descriptor,0,os.SEEK_SET);msvcrt.locking(descriptor,msvcrt.LK_UNLCK,1)
    finally:os.close(descriptor)
    if error is not None:raise error


def _commit_no_clobber(root,pending,output):
    if sys.platform!='win32':raise RuntimeError('sealed no-clobber release is implemented only for Windows')
    root,pending=_guard(root,pending,direct_child=True);_,output=_guard(root,output,direct_child=True)
    if not pending.is_dir():raise ValueError('sealed pending release is absent')
    try:output.lstat()
    except FileNotFoundError:pass
    else:raise FileExistsError(output)
    _guard(root,pending,direct_child=True);_guard(root,output,direct_child=True)
    os.rename(pending,output)  # Windows rename fails atomically if destination exists.


def run(output,*,resume=False,interrupt_at=None):
    _source_runtime_check()
    root=io.unlinked(ROOT)
    if not root.exists():
        parent=io.unlinked(root.parent)
        if not parent.is_dir():raise ValueError('R4 evidence parent is absent')
        root.mkdir(exist_ok=False)
    root=io.unlinked(root)
    _,output=_guard(root,output,direct_child=True)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',output.name):
        raise ValueError('release output name is not a safe identifier')
    identity=_identity();_validate_identity(identity);generation=identity['generation_id']
    descriptor,lock,lock_identity=_acquire_lock(root,output,generation)
    try:
        _guard(root,output,direct_child=True)
        if output.exists():
            if not resume:raise FileExistsError(output)
            receipt=verify(output,identity)
            if verification.source_snapshot()!=identity['sources']:raise ValueError('source drift on release reuse')
            _source_runtime_check(identity['sources'])
            return {'status':'VERIFIED_REUSE','receipt':receipt,'output':str(output)}
        pending=io.unlinked(output.with_name(output.name+'.pending-'+generation[:16]))
        _guard(root,pending,direct_child=True)
        if pending.exists():
            if not resume:raise FileExistsError('preserved pending release requires explicit resume')
            if {p.name for p in pending.iterdir()}!=set(NAMES):raise ValueError('pending release is not completely sealed')
            verify(pending,identity)
        else:
            if verification.source_snapshot()!=identity['sources']:raise ValueError('source drift before verification')
            test_workers=[_test_worker(identity),_test_worker(identity)]
            a=verification.verify_near_flat();b=verification.verify_near_flat()
            _validate_report(a,identity,timed=True);_validate_report(b,identity,timed=True)
            scientific=_strip_timing(a,identity)
            if io.canonical(scientific)!=io.canonical(_strip_timing(b,identity)):
                raise ValueError('repeat R4 scientific report differs')
            if verification.source_snapshot()!=identity['sources']:raise ValueError('source drift during release construction')
            executed_sources=_source_runtime_check(identity['sources'])
            _validate_executed_sources(executed_sources,identity['sources'])
            blobs={name:io.canonical(value) for name,value in zip(NAMES[:3],(a,b,scientific))}
            products={name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in blobs.items()}
            receipt={'identity':identity,'products':products,'test_workers':test_workers,
                     'executed_local_sources':executed_sources,
                     'scientific_result_sha256':products['SCIENTIFIC-RESULT.json']['sha256'],
                     'physical_acceptance':False,'production_authorised':False,'diadem_canon_changed':False}
            if sum(map(len,blobs.values()))+len(io.canonical(receipt))>MAX_TOTAL:raise ValueError('release total size exceeded')
            _guard(root,pending,direct_child=True);pending.mkdir(exist_ok=False)
            _guard(root,pending,direct_child=True)
            for name,value in zip(NAMES[:3],(a,b,scientific)):_write_new(root,pending/name,value)
            _write_new(root,pending/'RECEIPT.json',receipt)
            verify(pending,identity)
            if interrupt_at=='after_receipt':raise RuntimeError('injected interruption after sealed release')
        if verification.source_snapshot()!=identity['sources']:raise ValueError('source drift before release commit')
        _source_runtime_check(identity['sources'])
        _commit_no_clobber(root,pending,output);receipt=verify(output,identity)
        _source_runtime_check(identity['sources'])
        return {'status':'COMMITTED_BOUNDED_REFERENCE','receipt':receipt,'output':str(output)}
    finally:
        _release_lock(root,descriptor,lock,lock_identity)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--output',type=Path);parser.add_argument('--resume',action='store_true')
    parser.add_argument('--interrupt-at',choices=['after_receipt']);parser.add_argument('--test-worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    if args.test_worker:
        if args.output is not None or args.resume or args.interrupt_at is not None:parser.error('test worker accepts no release controls')
        report=_run_test_suite();sys.stdout.buffer.write(io.canonical(report)+b'\n')
        return 0 if report['status']=='PASS' else 1
    if args.output is None:parser.error('--output is required')
    print(json.dumps(run(args.output,resume=args.resume,interrupt_at=args.interrupt_at),sort_keys=True))
    return 0


if __name__=='__main__':raise SystemExit(main())
