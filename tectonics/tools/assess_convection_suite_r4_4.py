#!/usr/bin/env python3
"""Collate all applicable source-bound R4.4 case and combined acceptance gates.
SPDX-License-Identifier: AGPL-3.0-only

The manifest names actual closed run directories, never user-written PASS flags.
Each run is re-audited. Missing studies, unresolved reference conventions or an
unverified resource/regression record keep R4.4 IN_PROGRESS. This is a numerical
benchmark gate, not observational validation or approval for later R5 work.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools')]
import atlas_tectonics as atlas
import analyse_convection_r4_4 as audit
from run_convection_r4_4 import atomic_new,digest,safe_path,source_record


def expected_cases():
    return [dict(name=name,yield_stress=None) for name in ('tosi-1','tosi-2','tosi-3','tosi-4','tosi-5a')]+[
        dict(name='tosi-5b',yield_stress=3+i/10) for i in range(21)]


def case_key(case):
    valid=atlas.TosiCase(**case)
    return (valid.name,valid.yield_stress)


def resolve(base,value):
    path=Path(value)
    if not path.is_absolute():path=base/path
    safe_path(path)
    return path.absolute()


def verification_gate(path):
    """Recheck the actual final-source inventory; old full-suite passes do not bind."""
    if path is None:return {'passed':False,'reason':'No combined full regression/resource record supplied'}
    safe_path(path);record=json.loads(path.read_bytes())
    spec=importlib.util.spec_from_file_location('atlas_current_verify',ROOT/'verify.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    inventory=module.source_inventory(ROOT)
    tests_ok=bool(record.get('tests_run',0)>0 and record.get('failures')==0 and record.get('errors')==0 and
        record.get('skips')==0 and record.get('source_unchanged_during_tests') is True and
        record.get('source_sha256_before')==inventory and record.get('source_sha256_after')==inventory and
        record.get('status')=='PASS_MATHEMATICAL_TESTS_ONLY' and
        record.get('profile')=='combined-resource-acceptance')
    resources_ok=(record.get('resource_acceptance') or {}).get('status')=='PASS_BOUNDED_CURRENT_PLATFORM'
    return dict(passed=tests_ok and resources_ok,tests_passed_on_current_source=tests_ok,
        bounded_platform_resources_passed=resources_ok,tests_run=record.get('tests_run'),
        record_sha256=digest(path.read_bytes()),runtime=record.get('runtime'),
        limitation='Current tested platform only; hashes are integrity observations, not signatures')



def visual_gate(entry, base, case, representatives):
    """Bind a separately recorded inspection to actual renderer outputs and state."""
    if not entry:return {'passed':False,'reason':'No actual-code visual inspection record supplied'}
    inspection_path=resolve(base,entry)
    inspection=json.loads(inspection_path.read_bytes())
    metadata_path=resolve(inspection_path.parent,inspection['metadata'])
    metadata=json.loads(metadata_path.read_bytes())
    allowed_states={r['latest_diagnostics_state_id'] for r in representatives}
    errors=[]
    if metadata.get('output_kind')!='RAW_DATA_AND_PLOTS':errors.append('raw-only export is not visual evidence')
    required_files={'raw_fields_and_history.npz','01_temperature.png','02_viscosity.png','03_pressure.png',
                    '04_velocity.png','05_heat_flux_history.png','06_temperature_history.png'}
    if not required_files<=set(metadata.get('files',{})):errors.append('complete plotted outputs missing')
    if metadata['state_id'] not in allowed_states:errors.append('visual state is not a finest accepted run endpoint')
    if metadata['source']!=source_record():errors.append('visual source identity differs')
    if case_key(metadata['configuration']['case'])!=case_key(case):errors.append('visual case differs')
    if metadata['renderer_sha256']!=digest((ROOT/'tools/visual_convection_r4_4.py').read_bytes()):errors.append('renderer changed')
    if inspection.get('metadata_sha256')!=digest(metadata_path.read_bytes()):errors.append('inspection metadata hash differs')
    if inspection.get('state_id')!=metadata['state_id'] or inspection.get('flow_id')!=metadata['flow_id']:errors.append('inspection endpoint differs')
    if inspection.get('passed') is not True:errors.append('inspection not recorded as passed')
    if not metadata.get('files'):errors.append('no actual raw/visual outputs')
    for name,sha in metadata.get('files',{}).items():
        if Path(name).name!=name:raise ValueError('visual manifest contains a nonlocal filename')
        file=metadata_path.parent/name;safe_path(file)
        if digest(file.read_bytes())!=sha:errors.append('visual/raw file changed: '+name)
    return dict(passed=not errors,errors=errors,inspection_sha256=digest(inspection_path.read_bytes()),
        user_visual_approval=inspection.get('user_visual_approval','NOT_RECORDED'))


def unresolved_references(spec):
    result=[]
    try:audit.case5b_reference.load_reference(spec)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        result.append('Case 5b numerical reference targets not verified: '+str(exc))
    if not audit.case5a_mapping_verified(spec):
        result.append('Case 5a explicit derived dissipation mapping missing or changed')
    for case in ('tosi-5a','tosi-5b'):
        try:audit.reference_contributors(case,spec)
        except ValueError as exc:result.append(str(exc))
    return result


def matched_representative_regimes(representatives):
    regimes=[r.get('regime','steady' if r['case']['name'] in ('tosi-1','tosi-2','tosi-3','tosi-4') else 'unresolved') for r in representatives]
    return dict(passed=len(regimes)==3 and len(set(regimes))==1 and regimes[0] in ('steady','periodic'),regimes=regimes)


def preflight(manifest_path):
    """Inspect only the plan, run configurations and specification, never arrays."""
    from run_convection_r4_4 import schedule_feasibility
    safe_path(manifest_path);manifest=json.loads(manifest_path.read_bytes());base=manifest_path.parent
    if manifest.get('schema')!='atlas.convection-campaign-r4-4.v1':raise ValueError('unknown campaign schema')
    spec=json.loads((ROOT/'cases/convection_r4_4.json').read_bytes());current=source_record()
    expected={case_key(c) for c in expected_cases()};requested={};issues=[];runs={};references=[]
    for entry in manifest.get('cases',[]):
        key=case_key(entry['case'])
        if key in requested:issues.append('duplicate campaign case: '+str(key))
        if key not in expected:issues.append('unexpected campaign case: '+str(key))
        requested[key]=entry
    for case in expected_cases():
        key=case_key(case);entry=requested.get(key,{})
        for axis in ('mesh','timestep','nonlinear'):
            values=entry.get(axis,[]);label=str(key)+' '+axis
            if type(values) is not list or len(values)!=3 or any(type(v) is not str for v in values):
                issues.append(label+': three planned run paths required');continue
            paths=[resolve(base,v) for v in values];configs=[]
            if len(set(paths))!=3:issues.append(label+': repeated path cannot supply three independent study coordinates')
            for path in paths:
                references.append(str(path))
                if path not in runs:
                    config_path=path/'run.json';safe_path(config_path)
                    if not config_path.is_file():runs[path]={'path':str(path),'status':'MISSING_RUN_CONFIGURATION'}
                    else:
                        try:
                            config=json.loads(config_path.read_bytes())
                            runs[path]=dict(path=str(path),status='CONFIGURATION_READ',configuration=config,
                                schedule=schedule_feasibility(config,spec))
                        except (ValueError,KeyError,TypeError,ArithmeticError,atlas.TectonicsError) as exc:
                            runs[path]=dict(path=str(path),status='INVALID_RUN_CONFIGURATION',reason=str(exc))
                run=runs[path];config=run.get('configuration')
                if config is None:issues.append(label+': '+run['status']+' '+str(path));continue
                try:
                    if case_key(config['case'])!=key:raise ValueError('run belongs to another case')
                    if config['identities']!=current:raise ValueError('run source/runner/specification differs')
                    configs.append(config)
                except (ValueError,KeyError,TypeError,atlas.TectonicsError) as exc:issues.append(label+': '+str(exc))
            if len(configs)==3:
                try:
                    coordinate,required=audit.study_controls(configs,axis,spec['predeclared_acceptance']['adequacy'])
                    if not np.allclose(coordinate,required,rtol=1e-12,atol=0):
                        issues.append(label+': coordinates do not match the predeclared adequacy study')
                except (ValueError,KeyError,TypeError,ArithmeticError) as exc:issues.append(label+': '+str(exc))
    for run in runs.values():run.pop('configuration',None)
    reuse=[dict(path=path,planned_uses=references.count(path)) for path in sorted(set(references)) if references.count(path)>1]
    return dict(schema='atlas.convection-suite-preflight-r4-4.v1',status='PLANNING_ONLY_NOT_ACCEPTANCE',
        unresolved_reference_requirements=unresolved_references(spec),study_configuration_issues=issues,
        planned_run_references=len(references),distinct_planned_runs=len(runs),planned_run_reuse=reuse,
        runs=list(runs.values()),run_arrays_read=False,full_benchmark_accepted=False,
        campaign_sha256=digest(manifest_path.read_bytes()),source=current,
        limitation='Configurations and necessary schedule conditions only; normal assessment must authenticate all trajectories and gates')


def assess(manifest_path):
    safe_path(manifest_path)
    manifest=json.loads(manifest_path.read_bytes());base=manifest_path.parent
    if manifest.get('schema')!='atlas.convection-campaign-r4-4.v1':raise ValueError('unknown campaign schema')
    entries=manifest.get('cases',[])
    requested={}
    for entry in entries:
        key=case_key(entry['case'])
        if key in requested:raise ValueError('duplicate campaign case')
        requested[key]=entry
    cached={};cycle_cache={};case_reports=[]
    for case in expected_cases():
        key=case_key(case);entry=requested.get(key,{})
        studies={};representatives=[]
        for axis in ('mesh','timestep','nonlinear'):
            paths=entry.get(axis,[])
            if len(paths)!=3:
                studies[axis]={'status':'MISSING_THREE_RUN_STUDY','passed':False};continue
            paths=[resolve(base,value) for value in paths]
            # At most the current three final cycles; scalar reports remain cached.
            cycle_cache={path:value for path,value in cycle_cache.items() if path in paths}
            reports=[]
            for path in paths:
                if path not in cached or (cached[path].get('regime')=='periodic' and path not in cycle_cache):
                    cycle={};cached[path]=audit.analyse_run(path,phase_fields=cycle)
                    if cached[path].get('regime')=='periodic':cycle_cache[path]=cycle
                report=cached[path]
                if case_key(report['case'])!=key:raise ValueError('study path belongs to another campaign case')
                reports.append(report)
            result=audit.study(reports,axis,phase_fields=[cycle_cache.get(path) for path in paths])
            result['passed']=result['status']=='ADEQUACY_GATE_PASSED'
            result['run_config_ids']=[r['config_id'] for r in reports]
            studies[axis]=result;representatives.append(reports[-1])
        per_run=[]
        for r in representatives:
            per_run.append(dict(config_id=r['config_id'],receipt_head=r['receipt_head'],
                passed=bool(r.get('mature_regime_gate') and r.get('work_gate',{}).get('passed') and
                    r.get('every_accepted_step',{}).get('conservation_passed') and
                    r.get('table_comparison',{}).get('all_available_metrics_within_envelope')),
                mature_regime=r.get('mature_regime_gate',False),work=r.get('work_gate',{}),
                conservation=r.get('every_accepted_step',{}).get('conservation_passed',False),
                table_comparison=r.get('table_comparison',{})))
        visual=visual_gate(entry.get('visual_qa'),base,case,representatives)
        regime_gate=matched_representative_regimes(representatives)
        passed=bool(all(s['passed'] for s in studies.values()) and len(per_run)==3 and
            all(r['passed'] for r in per_run) and visual['passed'] and regime_gate['passed'])
        case_reports.append(dict(case=case,passed=passed,studies=studies,finest_run_gates=per_run,visual_qa=visual,matched_regime_gate=regime_gate))
    verification=manifest.get('combined_verification')
    combined=verification_gate(None if verification is None else resolve(base,verification))
    # Reference blocks are explicit even if no expensive run has been supplied.
    spec=json.loads((ROOT/'cases/convection_r4_4.json').read_bytes())
    unresolved=unresolved_references(spec)
    passed=bool(not unresolved and combined['passed'] and all(r['passed'] for r in case_reports))
    return dict(schema='atlas.convection-suite-acceptance-r4-4.v1',
        status='PASS_R4_4_NUMERICAL_SCOPE' if passed else 'INCOMPLETE_R4_4',
        R4_status='COMPLETE_2D_NUMERICAL_SCOPE' if passed else 'IN_PROGRESS',full_benchmark_accepted=passed,
        expected_case_configurations=len(case_reports),passed_cases=sum(r['passed'] for r in case_reports),
        evaluated_distinct_trajectories=len(cached),cases=case_reports,combined=combined,
        unresolved_reference_requirements=unresolved,source=source_record(),
        campaign_sha256=digest(manifest_path.read_bytes()),evaluator_sha256=digest(Path(__file__).read_bytes()),
        visual_user_approval='NOT_ASSERTED',R5_authorised=False,
        limitation='No Earth/Diadem observational validation, spherical dynamics, universal scaling or additional platform acceptance')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--preflight',action='store_true',help='read only configurations and specification; do not open run arrays')
    args=p.parse_args();safe_path(args.output)
    report=(preflight if args.preflight else assess)(args.manifest.absolute());atomic_new(args.output,report)
    if args.preflight:
        print(json.dumps({k:report[k] for k in ('status','distinct_planned_runs','full_benchmark_accepted')}))
        return 0
    print(json.dumps({k:report[k] for k in ('status','expected_case_configurations','passed_cases','full_benchmark_accepted')}))
    return 0 if report['full_benchmark_accepted'] else 1


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,KeyError,TypeError,OSError,atlas.TectonicsError) as exc:
        print(json.dumps({'status':'REFUSED','error':str(exc)}),file=sys.stderr);raise SystemExit(2)
