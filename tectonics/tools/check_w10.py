#!/usr/bin/env python3
"""Bounded W10 assessment; implementation verification is not field validation.

Runs an explicit method selection, validates reusable evidence without repeating
its solves, and evaluates the fixed observational screen. No discovery fallback,
auto-installation, fitting, held convection run, old-report rewrite or plotting.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY_KEYS = {'assessment_completion_is_physical_acceptance',
    'numerical_failure_or_skip_can_pass', 'missing_or_stale_required_evidence_can_pass',
    'ensemble_spread_is_calibrated_uncertainty', 'downstream_science_implemented_here',
    'whole_tectonics_field_validated', 'production_ready'}


def read_json(path):
    raw=path.read_bytes()
    if len(raw)>4*1024**2: raise ValueError('bounded assessment input exceeds 4 MiB')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    def invalid(value): raise ValueError('nonfinite JSON constant: '+value)
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def local(path):
    p=ROOT/path
    if Path(path).is_absolute() or '..' in Path(path).parts or not p.is_file() or p.is_symlink():
        raise ValueError('required local assessment input missing or unsafe: '+str(path))
    p.resolve().relative_to(ROOT.resolve())
    return p


def validate_profile(data):
    if data['schema']!='atlas.w10-tectonics-profile.v1': raise ValueError('unknown W10 profile')
    if data['max_selected_methods']!=26 or not data['gates'] or any(not group for group in data['gates'].values()):
        raise ValueError('W10 method budget or coverage changed')
    names=[name for group in data['gates'].values() for name in group]
    if (len(names)!=26 or len(names)!=len(set(names))
            or any(len(name.split('.'))!=3 or not name.split('.')[-1].startswith('test_') for name in names)):
        raise ValueError('W10 requires a bounded, unique, exact-method selection')
    if (set(data['status_policy'])!=POLICY_KEYS
            or any(value is not False for value in data['status_policy'].values())
            or data['held_campaign']!='R4.4 HELD_INCOMPLETE'):
        raise ValueError('W10 scientific/status safeguards changed')
    return data


def profile():
    return validate_profile(read_json(local('cases/w10_tectonics_r1.json')))


def verifier():
    spec=importlib.util.spec_from_file_location('atlas_w10_verifier',ROOT/'verify.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class Measurements(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.rows={};self._starts={}
    def startTest(self,test):
        self._starts[test.id()]=time.perf_counter()
        self.rows[test.id()]={'status':'INCOMPLETE'}
        super().startTest(test)
    def stopTest(self,test):
        row=self.rows[test.id()]
        if row['status']=='INCOMPLETE' and row.get('skipped_subtests'):
            row['status']='PASS_WITH_SKIPPED_SUBTESTS'
        row['seconds']=time.perf_counter()-self._starts.pop(test.id())
        super().stopTest(test)
    def addSuccess(self,test):
        row=self.rows[test.id()]
        row['status']='PASS_WITH_SKIPPED_SUBTESTS' if row.get('skipped_subtests') else 'PASS'
        super().addSuccess(test)
    def addFailure(self,test,err):
        self.rows.setdefault(test.id(),{})['status']='FAIL';super().addFailure(test,err)
    def addError(self,test,err):
        self.rows.setdefault(test.id(),{})['status']='ERROR';super().addError(test,err)
    def addSkip(self,test,reason):
        self.rows.setdefault(test.id(),{}).update(status='SKIPPED',reason=reason)
        # unittest sends a skipped subtest without startTest(subtest). Keep its
        # separate record and disclose the gap on the enclosing successful test.
        parent=getattr(test,'test_case',None)
        if parent is not None and parent.id() in self.rows:
            self.rows[parent.id()].setdefault('skipped_subtests',[]).append(test.id())
        super().addSkip(test,reason)
    def addSubTest(self,test,subtest,err):
        if err is not None:
            status='FAIL' if issubclass(err[0],test.failureException) else 'ERROR'
            if self.rows[test.id()]['status']!='ERROR':self.rows[test.id()]['status']=status
        super().addSubTest(test,subtest,err)


def check_history(path):
    """Reuse only an exact current production/runtime/fixture binding."""
    import numpy as np
    import scipy
    from atlas_tectonics.reuse import _source_bytes
    data=read_json(path)
    actual={name:json.loads(raw) for name,raw in _source_bytes().items()}
    if data['schema']!='atlas.tectonic-history-evidence.v1' or data['status']!='PASS':
        raise ValueError('invalid retained history evidence')
    if data['sources']['production']!=actual: raise ValueError('history production binding is stale')
    for name,sha in data['sources']['tools_and_fixtures'].items():
        if digest(local(name))!=sha: raise ValueError('history fixture/tool binding is stale: '+name)
    expected=dict(python=platform.python_version(),platform=platform.platform(),numpy=np.__version__,scipy=scipy.__version__)
    if any(data['runtime'].get(k)!=v for k,v in expected.items()):
        raise ValueError('history runtime binding is stale')
    rows=data['routes']
    if {r['route'] for r in rows}!={'underthrust','w04','regional'} or len(rows)!=3:
        raise ValueError('history evidence route coverage mismatch')
    for r in rows:
        if r['status']!='PASS' or not r['complete_output_hash_parity'] or r['final_reserved_bytes']!=0:
            raise ValueError('retained history did not pass')
        if len(r['observations'])!=6: raise ValueError('incomplete retained history repetitions')
        for row in r['observations']:
            stats=row['statistics'];restored=row['restore']
            if stats['computed_outputs']!=(0 if restored else 3) or stats['restored_outputs']!=int(restored):
                raise ValueError('history replay accounting mismatch')
    return dict(status='REUSED_CURRENT_EXACT_BINDING',path=path.relative_to(ROOT).as_posix(),
                sha256=digest(path),routes=[r['route'] for r in rows],physical_replays=0,
                avoided_historical_driver_wall_seconds=data['wall_s'])


def retained_subduction(path):
    """Authenticate historical results; expose drift, never relabel as current."""
    data=read_json(path);reports={}
    if digest(local('cases/'+data['adapter']))!=data['adapter_sha256']:
        raise ValueError('subduction adapter differs from acceptance record')
    for name,sha in data['report_sha256'].items():
        p=local('evidence/'+name)
        if digest(p)!=sha: raise ValueError('changed historical subduction report: '+name)
        report=read_json(p)
        changed=[key for key,old in report['sources'].items()
                 if digest(local('src/atlas_tectonics/'+key))!=old]
        reports[name]=dict(sha256=sha,changed_recorded_sources=changed,
                           full_runtime_binding_reused=False)
    return dict(status='AUTHENTICATED_HISTORICAL_NUMERICAL_REFERENCE',reports=reports,
                current_full_campaign=False,field_validation=False)


def check_surface(path):
    """The W10 surface run must name current production, not dated summaries."""
    import numpy as np
    import scipy
    from check_w07_surface import sources, convergence
    data=read_json(path)
    if (data['schema']!='atlas.w07-surface-evidence.v1' or data['status']!='PASS'
            or data['mode']!='acceptance' or data.get('fatal')):
        raise ValueError('surface assessment failed or has wrong scope')
    if data['source_sha256']!=sources(): raise ValueError('surface convergence evidence is not current')
    expected=dict(python=sys.version,platform=platform.platform(),numpy=np.__version__,scipy=scipy.__version__)
    if any(data['runtime'].get(k)!=v for k,v in expected.items()):
        raise ValueError('surface runtime binding is stale')
    if data['limits']!=dict(accounted_bytes=128*1024**2,native_threads=1,accepted_steps_per_trajectory=256):
        raise ValueError('surface limits changed')
    budget=data['budget']
    if (budget['max_bytes']!=128*1024**2 or budget['reserved_bytes']!=0
            or budget['refusals']!=0 or budget['peak_reserved_bytes']>budget['max_bytes']):
        raise ValueError('surface resource gates failed')
    rows=data['checks'];by_name={row['name']:row for row in rows}
    trajectories={(nx,nz,n,a):f'B09/{nx}x{nz}/{n}/{a}' for a in (1e-4,5e-5)
                  for nx,nz,n in ((4,2,64),(8,4,64),(16,8,16),(16,8,32),(16,8,64))}
    if (len(rows)!=12 or set(by_name)!=set(trajectories.values())|{'B09/independent-oracle','B09/convergence'}
            or any(row['status']!='PASS' for row in rows)):
        raise ValueError('surface checks failed or incomplete')
    measured=convergence({key:by_name[name]['result'] for key,name in trajectories.items()})
    if measured!=by_name['B09/convergence']['result']: raise ValueError('surface convergence summary mismatch')
    return dict(status='CURRENT_B09_PASS',path=path.relative_to(ROOT).as_posix(),sha256=digest(path),
        checks=len(rows),trajectories=len(trajectories),convergence=measured,
        budget=budget,physical_replays=0,field_validation=False)


def decide(checks_passed,source_unchanged,evidence_errors,observation):
    observation_complete=bool(observation and observation.get('all_numerical_checks_passed') is True
        and observation.get('status') in ('CONSISTENT_WITH_OBSERVED_DISPERSION','NOT_CONSISTENT_WITH_OBSERVED_DISPERSION')
        and observation.get('calibration_performed') is False
        and observation.get('calibrated_confidence') is False
        and observation.get('whole_tectonics_acceptance') is False)
    completed=bool(checks_passed and source_unchanged and not evidence_errors and observation_complete)
    return dict(status='ASSESSMENT_COMPLETE' if completed else 'FAIL_OR_INCOMPLETE',
        selected_implementation_checks_passed=bool(checks_passed and source_unchanged),
        assessment_completed=completed,whole_tectonics_field_validated=False,
        calibrated_uncertainty=False,production_ready=False,R4_4_status='HELD_INCOMPLETE',
        physical_screen=None if observation is None else observation.get('status','UNRESOLVED'),
        next_work='W11 scoped performance and scale; W12 assembly after applicable gates')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args(argv)
    if args.report is not None and args.report.exists(): raise FileExistsError('new evidence path required')
    sys.dont_write_bytecode=True
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),str(ROOT/'tools')]
    import numpy as np
    import scipy
    from atlas_tectonics import reuse
    import atlas_tectonics
    if Path(atlas_tectonics.__file__).resolve()!=ROOT/'src/atlas_tectonics/__init__.py':
        raise ValueError('wrong tectonics checkout imported')
    cfg=profile();verify=verifier();before=verify.source_inventory(ROOT)
    dependencies=[local(cfg[k]) for k in ('retained_history_report','current_surface_report','subduction_acceptance')]
    extra_before={p.relative_to(ROOT).as_posix():digest(p) for p in dependencies}
    suite,selection=verify._acceptance_suite(cfg['gates'],'W10')
    started=time.perf_counter()
    result=unittest.TextTestRunner(stream=sys.stderr,verbosity=1,resultclass=Measurements).run(suite)
    elapsed=time.perf_counter()-started
    evidence={};errors=[];observation=None
    for name,fn,path in zip(('recovery','free_surface','subduction_reference'),
                           (check_history,check_surface,retained_subduction),dependencies):
        try: evidence[name]=fn(path)
        except (ValueError,KeyError,OSError,TypeError,AssertionError,RuntimeError) as exc:
            errors.append(dict(gate=name,error=str(exc)))
    try:
        from w10_ocean import CASE_PATH, run_challenge
        if local(cfg['observational_fixture'])!=CASE_PATH: raise ValueError('observation fixture selection mismatch')
        observation=run_challenge()
    except (ValueError,KeyError,OSError,TypeError,ImportError,AssertionError,RuntimeError) as exc:
        errors.append(dict(gate='ocean_observations',error=str(exc)))
    after=verify.source_inventory(ROOT)
    extra_after={p.relative_to(ROOT).as_posix():digest(p) for p in dependencies}
    unchanged=before==after and extra_before==extra_after
    passed=verify._checks_passed(result,unchanged)
    record=dict(schema='atlas.w10-assessment.v1',source_status='WORKING NON-CANON',
        decision=decide(passed,unchanged,errors,observation),
        scope=cfg['scope'],selected_tests_by_gate=selection,results=result.rows,
        tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),
        failure_details=[dict(test=t.id(),traceback=detail) for t,detail in result.failures],
        error_details=[dict(test=t.id(),traceback=detail) for t,detail in result.errors],
        skip_details=[dict(test=t.id(),reason=reason) for t,reason in result.skipped],
        evidence_errors=errors,evidence=evidence,observational_challenge=observation,
        physical_envelopes=cfg['physical_envelopes'],downstream_owned=cfg['downstream_owned'],
        source_sha256=before,source_unchanged=unchanged,
        source_changes={k:dict(before=before.get(k),after=after.get(k)) for k in before.keys()|after.keys()
                        if before.get(k)!=after.get(k)},
        evidence_sha256=extra_before,
        evidence_changes={k:dict(before=extra_before.get(k),after=extra_after.get(k)) for k in extra_before.keys()|extra_after.keys()
                          if extra_before.get(k)!=extra_after.get(k)},
        runtime=dict(python=platform.python_version(),platform=platform.platform(),numpy=np.__version__,scipy=scipy.__version__,
                     interpreter_sha256=reuse._loaded_binary(reuse._interpreter_binary())),
        selected_test_seconds=elapsed,wall_s=time.perf_counter()-started)
    if args.report is not None:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        with args.report.open('x',encoding='utf-8') as stream:
            json.dump(record,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
        print(json.dumps(dict(record['decision'],tests_run=result.testsRun,failures=len(result.failures),
            errors=len(result.errors),evidence_errors=errors,wall_s=record['wall_s']),sort_keys=True))
    else: print(json.dumps(record,indent=2,sort_keys=True,allow_nan=False))
    return 0 if record['decision']['assessment_completed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
