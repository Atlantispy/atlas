"""Exclusive, exact-inventory R2 verification; old suites are not rerun."""
from __future__ import annotations
import argparse
import hashlib
import importlib.abc
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import time
import unittest

HERE=Path(__file__).resolve().parent
TASK=HERE.parents[1]
sys.path.insert(0,str(TASK))
READS={}
SUITES=('test_bindings','test_food_accounting','test_multicommodity','test_soil_physics','test_integration','test_verification')
EXPECTED_TEST_COUNT=177
INVENTORY_SHA256='c4420c55ce14561f1fe544fc06b99b08c2c6c412b25d6fe3d434bcac3e80c239'
R1_SEAL=TASK/'outputs/generator-upgrade-r1/integrated-reference-01/VERIFICATION.json'
R1_SHA='5f34947fcd9d87c62461ef86862af4e05e5d2cf879be3eb1f226ff8f98b5b5d5'
OLD_SEAL=TASK/'outputs/module-review-2026-09-10/FINAL_VERIFICATION.json'
OLD_SHA='6181ff1ced0e8fe7c6a96240bb702f38c55fbda2cfaccabe0c892336eda32b48'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path,data):
    with Path(path).open('x',encoding='utf-8') as stream:
        json.dump(data,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')


class SourceLoader(importlib.abc.Loader):
    def __init__(self,path):self.path=path
    def create_module(self,spec):return None
    def exec_module(self,module):
        raw=self.path.read_bytes();key=str(self.path);digest=hashlib.sha256(raw).hexdigest()
        if key in READS and READS[key]!=digest:raise ValueError('executed source changed')
        READS[key]=digest;module.__file__=key
        exec(compile(raw,key,'exec',dont_inherit=True),module.__dict__)


class SourceFinder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if not fullname.startswith('work.'):return None
        base=TASK.joinpath(*fullname.split('.'))
        for candidate,package in ((base.with_suffix('.py'),False),(base/'__init__.py',True)):
            if candidate.is_file():
                return importlib.util.spec_from_file_location(fullname,candidate,loader=SourceLoader(candidate),
                    submodule_search_locations=[str(base)] if package else None)
        return None


def snapshot():
    return {str(p):sha(p) for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
            and p.suffix in {'.py','.md','.json'}}


def predecessor_readback():
    if sha(R1_SEAL)!=R1_SHA or sha(OLD_SEAL)!=OLD_SHA:raise ValueError('predecessor seal changed; no implicit repin')
    r1=json.loads(R1_SEAL.read_text());old=json.loads(OLD_SEAL.read_text())
    for source_map in (r1['source_snapshot'],old['candidate_source_snapshot']):
        for path,expected in source_map.items():
            if sha(path)!=expected:raise ValueError('predecessor source changed: '+path)
    pins=r1['predecessor_readback']['catalogue_pins']
    for name,expected in pins.items():
        if sha(TASK/'work/generator_capabilities_r1'/name)!=expected:raise ValueError('18-category contract changed: '+name)
    return {'r1_seal_sha256':R1_SHA,'r1_source_files_unchanged':len(r1['source_snapshot']),
        'old_seal_sha256':OLD_SHA,'old_source_files_unchanged':len(old['candidate_source_snapshot']),
        'catalogue_pins':pins,'old_tests_rerun':False,
        'meaning':'source preservation only; previous 134 and 938 checks not recounted'}


def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item


class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.started=[];self.stopped=[];self.passed=[]
    def startTest(self,test):self.started.append(test.id());super().startTest(test)
    def stopTest(self,test):self.stopped.append(test.id());super().stopTest(test)
    def addSuccess(self,test):self.passed.append(test.id());super().addSuccess(test)


def worker(path):
    sys.meta_path.insert(0,SourceFinder())
    before=snapshot();prior=predecessor_readback()
    from work.generator_upgrade_r2.bindings import owner_bindings
    owners=owner_bindings()
    suite=unittest.defaultTestLoader.loadTestsFromNames(['work.generator_upgrade_r2.'+s for s in SUITES])
    inventory=[t.id() for t in flatten(suite)]
    digest=hashlib.sha256(json.dumps(inventory,separators=(',',':')).encode()).hexdigest()
    if len(inventory)!=EXPECTED_TEST_COUNT or len(set(inventory))!=len(inventory) or digest!=INVENTORY_SHA256:
        raise ValueError('test inventory differs from exact reviewed inventory')
    output=io.StringIO();start=time.perf_counter()
    result=unittest.TextTestRunner(stream=output,verbosity=2,resultclass=Result).run(suite)
    elapsed=time.perf_counter()-start
    valid=(result.wasSuccessful() and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses
           and inventory==result.started==result.stopped==result.passed)
    reference=None
    if valid:
        from work.generator_upgrade_r2.reference import food_reference
        from work.generator_upgrade_r2.soil_physics import verification_reference
        reference={'actual_crop_food_transport':food_reference(),'actual_soil_physics':verification_reference()}
    if snapshot()!=before or predecessor_readback()!=prior or owner_bindings()!=owners:
        raise ValueError('source or owner decision drift during verification')
    for file,expected in READS.items():
        if sha(file)!=expected:raise ValueError('executed source drift: '+file)
    import numpy,scipy
    receipt={'status':'PASS' if valid else 'FAIL','test_ids':inventory,'inventory_sha256':digest,
        'tests':result.testsRun,'started':result.started,'stopped':result.stopped,'passed':result.passed,
        'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
        'duration_seconds':elapsed,'optimisation_flag':sys.flags.optimize,'source_snapshot':before,
        'executed_source_hashes':READS,'predecessor_readback':prior,'owner_bindings':owners,'reference':reference,
        'runtime':{'python':platform.python_version(),'numpy':numpy.__version__,'scipy':scipy.__version__},
        'test_log':output.getvalue()}
    dump(path,receipt)
    print(json.dumps({k:receipt[k] for k in ('status','tests','failures','errors','skips','duration_seconds')}))
    return 0 if valid else 1


def validate_workers(records,before,prior):
    """Validate receipts against parent capture, not only against one another."""
    if type(records) is not list or len(records)!=2:raise ValueError('exactly two mode receipts required')
    a,b=records
    for r,flag in zip(records,(0,2)):
        if r['optimisation_flag']!=flag:raise ValueError('required normal/-OO interpreter mode was not executed')
        if (r['status']!='PASS' or r['tests']!=EXPECTED_TEST_COUNT
                or any(r[k]!=0 for k in ('failures','errors','skips'))):raise ValueError('worker did not pass complete suite')
        ids=r['test_ids']
        actual=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()
        if (len(ids)!=EXPECTED_TEST_COUNT or len(set(ids))!=len(ids) or actual!=INVENTORY_SHA256
                or r['inventory_sha256']!=actual or not ids==r['started']==r['stopped']==r['passed']):
            raise ValueError('worker inventory/execution mismatch')
        if r['source_snapshot']!=before or r['predecessor_readback']!=prior:
            raise ValueError('worker source differs from parent capture')
        for path,digest in r['executed_source_hashes'].items():
            if path in before and before[path]!=digest:raise ValueError('executed package bytes differ from parent capture')
    for key in ('test_ids','inventory_sha256','source_snapshot','executed_source_hashes','predecessor_readback','owner_bindings','runtime','reference'):
        if a[key]!=b[key]:raise ValueError('normal/-OO disagreement: '+key)


def child_environment():
    environment=os.environ.copy()
    # An inherited option must not turn the nominal normal child into -O/-OO.
    environment.pop('PYTHONOPTIMIZE',None)
    return environment


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id');parser.add_argument('--worker',type=Path)
    args=parser.parse_args()
    if args.worker:return worker(args.worker)
    if not args.run_id or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',args.run_id):parser.error('new bounded --run-id required')
    root=TASK/'outputs/generator-upgrade-r2'/args.run_id
    for p in (root,*root.parents):
        if p.exists():
            info=p.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('linked/reparse output parent')
    root.mkdir(parents=True,exist_ok=False)
    before=snapshot();prior=predecessor_readback();records=[]
    for label,flags in (('normal',[]),('assertions_disabled',['-OO'])):
        path=root/(label+'.json')
        proc=subprocess.run([sys.executable,'-B',*flags,str(Path(__file__).resolve()),'--worker',str(path)],
            cwd=TASK,capture_output=True,text=True,timeout=180,env=child_environment())
        dump(root/(label+'-process.json'),{'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr})
        if proc.returncode:raise RuntimeError('verification failed; diagnostics preserved at '+str(root))
        records.append(json.loads(path.read_text()))
    a,b=records
    validate_workers(records,before,prior)
    if before!=snapshot() or prior!=predecessor_readback():raise ValueError('verification drift')
    receipt={'schema':'diadem.scientific-upgrade-tranche.r2','status':'REFERENCE_IMPLEMENTED_AND_VERIFIED',
        'distinct_named_checks':len(a['test_ids']),'runs_per_check':2,'failures':0,'errors':0,'skips':0,
        'test_ids':a['test_ids'],'inventory_sha256':a['inventory_sha256'],'source_snapshot':before,
        'predecessor_readback':prior,'owner_bindings':a['owner_bindings'],'runtime':a['runtime'],
        'workers':[{'path':str(root/(label+'.json')),'sha256':sha(root/(label+'.json'))} for label in ('normal','assertions_disabled')],
        'reference_sha256':hashlib.sha256(json.dumps(a['reference'],sort_keys=True,allow_nan=False).encode()).hexdigest(),
        'production_installed':False,'whole_generator_upgraded':False,'all_categories_physically_accepted':False,
        'new_world_generated':False,'canon_changed':False,'generation_speedup_percent':None,
        'scope':'mixed-food source/accounting/lossy shared-capacity transport; actual soil reference; scoped owner/parent and single-snow input checks'}
    dump(root/'VERIFICATION.json',receipt)
    print(json.dumps({k:receipt[k] for k in ('status','distinct_named_checks','runs_per_check','failures','errors','skips','whole_generator_upgraded')}))
    return 0


if __name__=='__main__':raise SystemExit(main())
