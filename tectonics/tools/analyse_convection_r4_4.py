#!/usr/bin/env python3
"""Audit saved R4.4 trajectories against explicit independent acceptance gates.
SPDX-License-Identifier: AGPL-3.0-only

One run cannot establish mesh/time/nonlinear adequacy. This tool therefore
reports per-run gates and optional three-run differences, but never silently
converts an incomplete case or combined R4.4 suite into PASS.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools')]
import numpy as np
import atlas_tectonics as atlas
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore,StoreLimits
from atlas_tectonics.convection_benchmark import _METRICS
from run_convection_r4_4 import encode,digest,safe_path,source_record,read_receipts,atomic_new


def compare_table(case, diagnostics, specification):
    """Published multi-code envelope is NOT a statistical confidence interval."""
    reference=specification['reported_values'].get(case)
    if reference is None:
        return {'status':'UNRESOLVED','reason':'No verified numerical reference table for this case',
                'comparisons':{},'all_available_metrics_within_envelope':False}
    margin=specification['predeclared_acceptance']['table_relative_margin']
    comparisons={}
    for key, values in reference.items():
        if key.startswith('printed_Phi'):
            comparisons[key]={'status':'UNRESOLVED','reason':'Printed dissipation normalisation remains ambiguous'}
            continue
        if key not in diagnostics:
            comparisons[key]={'status':'MISSING'};continue
        value=float(diagnostics[key])
        if not math.isfinite(value):raise ValueError('nonfinite comparison input')
        lo=min(values.values());hi=max(values.values());allowance=margin*max(abs(lo),abs(hi))
        comparisons[key]=dict(value=value,published_min=lo,published_max=hi,
            comparison_low=lo-allowance,comparison_high=hi+allowance,
            status='WITHIN_ENVELOPE' if lo-allowance<=value<=hi+allowance else 'OUTSIDE_ENVELOPE')
    ok=all(c['status']=='WITHIN_ENVELOPE' for c in comparisons.values())
    return dict(status='ALL_WITHIN_ENVELOPE' if ok else 'NOT_ALL_WITHIN_ENVELOPE',
        comparisons=comparisons,all_available_metrics_within_envelope=ok,
        meaning='One necessary comparison gate only; no benchmark acceptance from a snapshot')


def cycle_extrema(times, values, cycles=10):
    """Actual minima AND maxima averaged over the last complete peak-to-peak cycles."""
    if type(cycles) is not int or cycles < 1:raise ValueError('positive integral cycle count required')
    t=np.asarray(times,dtype=float);x=np.asarray(values,dtype=float)
    if t.shape!=x.shape or t.ndim!=1 or len(t)<3 or not np.isfinite(x).all() or not np.isfinite(t).all() or np.any(np.diff(t)<=0):
        raise ValueError('valid paired cycle samples required')
    peaks=np.flatnonzero((x[1:-1]>x[:-2])&(x[1:-1]>=x[2:]))+1
    if len(peaks)<cycles+1:return {'complete_cycles':max(0,len(peaks)-1),'resolved':False}
    peaks=peaks[-cycles-1:]
    lo=[float(x[a:b+1].min()) for a,b in zip(peaks[:-1],peaks[1:])]
    hi=[float(x[a:b+1].max()) for a,b in zip(peaks[:-1],peaks[1:])]
    return dict(resolved=True,complete_cycles=cycles,mean_cycle_minimum=float(np.mean(lo)),
        mean_cycle_maximum=float(np.mean(hi)),minimum=min(lo),maximum=max(hi),
        peak_times=t[peaks].tolist())


def phase_field_gate(states, peak_times, *, cycles=10, samples_per_period=100, tolerance=.01):
    """Bounded phase-by-phase comparison against the final complete cycle.

    Linear interpolation is diagnostic-only: no interpolated state is advanced
    or published as an accepted solution. Stored times must actually resolve
    each cycle; sparse checkpoint aliases do not pass. Phase normalisation is
    per-cycle, so a separate period-stability gate is mandatory.
    """
    if (type(cycles) is not int or cycles < 1 or type(samples_per_period) is not int or
            samples_per_period < 3 or not math.isfinite(tolerance) or tolerance <= 0):
        raise ValueError('valid finite phase-field policy required')
    if len(peak_times)<cycles+1 or len(states)<3:
        return {'passed':False,'reason':'insufficient complete cycles or stored fields'}
    peaks=np.asarray(peak_times[-cycles-1:],dtype=float)
    times=np.array([time for time,_ in states]);periods=np.diff(peaks)
    if (not np.isfinite(peaks).all() or not np.isfinite(times).all() or np.any(periods<=0) or
            np.any(np.diff(times)<=0) or any(not np.isfinite(field).all() for _,field in states)):
        raise ValueError('strictly increasing finite phase records required')
    if times[0]>peaks[0] or times[-1]<peaks[-1]:
        return {'passed':False,'reason':'saved fields do not cover the complete comparison cycles'}
    spans=np.diff(times)
    relevant=(times[:-1]<=peaks[-1])&(times[1:]>=peaks[0])
    max_gap=float(np.max(spans[relevant]))
    if max_gap>float(periods.min())/samples_per_period*(1+1e-9):
        return {'passed':False,'reason':'stored field cadence underresolves cycle',
                'maximum_gap':max_gap,'allowed_gap':float(periods.min())/samples_per_period}
    def interpolate(t):
        j=min(max(int(np.searchsorted(times,t,side='right'))-1,0),len(times)-2)
        weight=(t-times[j])/(times[j+1]-times[j])
        return (1-weight)*states[j][1]+weight*states[j+1][1]
    worst=0.
    for phase in np.linspace(0,1,samples_per_period+1):
        reference=interpolate(peaks[-2]+phase*periods[-1])
        for a,period in zip(peaks[:-2],periods[:-1]):
            worst=max(worst,float(np.max(np.abs(interpolate(a+phase*period)-reference))))
    return {'passed':worst<=tolerance,'temperature_linf':worst,'tolerance':tolerance,
            'cycles':cycles,'phase_samples':samples_per_period+1,'maximum_gap':max_gap}


def read_run(path, *, budget=None):
    safe_path(path)
    if (path/'RUNNING.lock').exists():raise ValueError('analyse a closed run, not a changing live trajectory')
    config=json.loads((path/'run.json').read_bytes())
    if config['identities']!=source_record():raise ValueError('run is not bound to this source/runner/specification')
    nonlinear_start=config.get('nonlinear_start','zero-rate')
    if nonlinear_start not in ('zero-rate','rk-stage0','previous-stage1'):
        raise ValueError('unsupported nonlinear starting policy')
    ap=None if 'anderson_policy' not in config else atlas.AndersonPolicy(**config['anderson_policy'])
    if ap is not None and encode(asdict(ap))!=encode(config['anderson_policy']):raise ValueError('noncanonical Anderson policy')
    pp=None if 'preconditioner_reuse_policy' not in config else atlas.PreconditionerReusePolicy(**config['preconditioner_reuse_policy'])
    if pp is not None and encode(asdict(pp))!=encode(config['preconditioner_reuse_policy']):raise ValueError('noncanonical reuse policy')
    config_id=digest(encode(config))
    records,head=read_receipts(path,config_id)
    samples=[sample for record in records for sample in record['samples']]
    steps=[step for record in records for step in record['stage_iteration_counts']]
    if [step['step'] for step in steps]!=list(range(1,records[-1]['step']+1)):
        raise ValueError('missing, duplicate or reordered accepted-step ledger')
    previous_step=None
    for step in steps:
        if step['dt']!=config['dt'] or len(step['mechanics'])!=2:
            raise ValueError('changed step schedule or missing current mechanical stage')
        from atlas_tectonics.anderson import check_summary
        for stage in step['mechanics']:
            from atlas_tectonics.preconditioner_reuse import check_summary as check_reuse
            if pp is not None:check_reuse(stage['preconditioner_reuse'],stage['nonlinear_iterations'],pp)
            elif 'preconditioner_reuse' in stage:raise ValueError('undeclared preconditioner reuse')
            if ap is not None:check_summary(stage['nonlinear_acceleration'],stage['nonlinear_iterations'],ap)
            elif 'nonlinear_acceleration' in stage:raise ValueError('undeclared Anderson stage')
        first,second=step['mechanics']
        if nonlinear_start in ('rk-stage0','previous-stage1'):
            if nonlinear_start=='previous-stage1':
                from atlas_tectonics.stokes_execution import _hex
                cs=step['cross_step_start']
                if set(cs)!={'input_state_id','input_guess_id','input_stage1_result_id',
                             'mechanical_plan_id','output_guess_id'}:
                    raise ValueError('incomplete cross-step starting ledger')
                for key in ('input_state_id','mechanical_plan_id','output_guess_id'):_hex(cs[key],key)
                input_id=records[0]['state_id'] if previous_step is None else previous_step['state_id']
                prev_id=None if previous_step is None else previous_step['cross_step_start']['output_guess_id']
                flow_id=None if previous_step is None else previous_step['mechanics'][1]['result_id']
                if (cs['input_state_id']!=input_id or cs['input_guess_id']!=prev_id or
                        cs['input_stage1_result_id']!=flow_id or
                        (first.get('initial_guess_id'),first.get('initial_guess_result_id'))!=(prev_id,flow_id)):
                    raise ValueError('cross-step guess is not linked to the previous accepted second stage')
                if previous_step is not None and cs['mechanical_plan_id']!=previous_step['cross_step_start']['mechanical_plan_id']:
                    raise ValueError('cross-step mechanical source/policy changed')
            elif first.get('initial_guess_id') is not None or first.get('initial_guess_result_id') is not None:
                raise ValueError('first stage may not retain a cross-step guess')
            seed=second.get('initial_guess_id')
            if (type(seed) is not str or len(seed)!=64 or any(c not in '0123456789abcdef' for c in seed)
                    or second.get('initial_guess_result_id')!=first['result_id']):
                raise ValueError('second-stage initial guess is not bound to this first stage')
        elif any('initial_guess_id' in v or 'initial_guess_result_id' in v for v in step['mechanics']):
            raise ValueError('run ledger uses an undeclared nonlinear starting policy')
        if nonlinear_start!='previous-stage1' and 'cross_step_start' in step:
            raise ValueError('undeclared cross-step provenance')
        previous_step=step
    accepted={0:(records[0]['state_id'],records[0]['time'])}
    for step in steps:
        expected_input=accepted[step['step']-1][1]
        if step['input_time']!=expected_input or not math.isfinite(step['dt']):
            raise ValueError('accepted-step input clock changed')
        accepted[step['step']]=(step['state_id'],expected_input+step['dt'])
    for sample in samples:
        if accepted.get(sample['step'])!=(sample['state_id'],sample['time']):
            raise ValueError('diagnostic sample/accepted state identity or clock mismatch')
    if samples and any(b['step']<=a['step'] or b['time']<=a['time'] for a,b in zip(samples,samples[1:])):
        raise ValueError('non-monotone diagnostic sampling')
    states=[]
    # Only retain the recent steady/periodic comparison interval, never the full spin-up.
    keep_since=records[-1]['time']-.05
    if len(samples)>=3:
        ext=cycle_extrema([q['time'] for q in samples],[q['diagnostics']['Nu_top'] for q in samples])
        if ext['resolved']:keep_since=min(keep_since,ext['peak_times'][0])
    keep_indices=[i for i,r in enumerate(records) if r['time']>=keep_since]
    if keep_indices and keep_indices[0]>0:keep_indices.insert(0,keep_indices[0]-1)
    keep_indices=set(keep_indices)
    maximum_retained_bytes=1024<<20
    if len(keep_indices)*config['cells']**2*8>maximum_retained_bytes:
        raise ValueError('saved-field analysis exceeds explicit 1 GiB retained-array envelope')
    budget=WorkBudget(512<<20) if budget is None else budget
    with ArrayStore(path/'states.sqlite',StoreLimits(chunk_bytes=65536,max_store_bytes=2<<30,max_array_bytes=32<<20),budget=budget) as store:
        case=atlas.TosiCase(**config['case']);pid=case.problem(config['cells']).problem_id
        for index,receipt in enumerate(records):
            state=atlas.load_thermochemical_state(store,receipt['state_id'],budget=budget)
            if (state.state_id!=receipt['state_id'] or state.step_index!=receipt['step'] or
                    state.time_s!=receipt['time'] or state.problem.problem_id!=pid):
                raise ValueError('stored checkpoint/receipt/physical case mismatch')
            if np.any(state.array('composition')):raise ValueError('published passive constituent is not zero')
            if state.step_index:
                record=state.descriptor()['step_record']['nonlinear_mechanics']
                if record.get('nonlinear_start','zero-rate')!=nonlinear_start:
                    raise ValueError('saved state uses a different nonlinear starting policy')
                if record.get('anderson_policy')!=config.get('anderson_policy'):raise ValueError('saved Anderson policy differs')
                if record.get('preconditioner_reuse_policy')!=config.get('preconditioner_reuse_policy'):raise ValueError('saved reuse policy differs')
                if record['stages']!=steps[state.step_index-1]['mechanics']:
                    raise ValueError('saved stage provenance differs from the run ledger')
                if nonlinear_start=='previous-stage1':
                    if (record['cross_step_start']!=steps[state.step_index-1]['cross_step_start'] or
                            state.next_initial_guess.guess_id!=record['cross_step_start']['output_guess_id']):
                        raise ValueError('saved starting fields differ from accepted ledger')
            if index in keep_indices:states.append((state.time_s,state.array('temperature_k').copy()-1))
    current,latest_head=read_receipts(path,config_id)
    if latest_head!=head or (path/'RUNNING.lock').exists() or config['identities']!=source_record():
        raise ValueError('trajectory/source changed during read-only audit')
    return config,records,samples,steps,states,head


def analyse_run(path):
    spec=json.loads((ROOT/'cases/convection_r4_4.json').read_bytes())
    config,records,samples,steps,states,head=read_run(path)
    case=config['case']['name'];policy=spec['predeclared_acceptance']
    last=records[-1]
    report=dict(schema='atlas.convection-analysis-r4-4.v1',case=config['case'],configuration=config,config_id=digest(encode(config)),
        receipt_head=head,source=source_record(),analysis_sha256=digest(Path(__file__).read_bytes()),
        accepted_step_count=last['step'],accepted_time=last['time'],saved_checkpoints=len(records),
        diagnostic_samples=len(samples),maximum_time_gap_between_saved_fields=max(np.diff([x[0] for x in states]),default=0.),
        full_benchmark_accepted=False,R4_status='IN_PROGRESS')
    if len(samples)<3:
        report['status']='INSUFFICIENT_DIAGNOSTIC_HISTORY';return report
    t=np.array([s['time'] for s in samples]);m={k:np.array([s['diagnostics'][k] for s in samples]) for k in _METRICS}
    steady_options={k:policy['steady'][k] for k in ('minimum_time','window','minimum_samples','relative_range','absolute_range')}
    steady=atlas.steady_window(t,m,**steady_options)
    periodic_options={k:policy['periodic'][k] for k in ('cycles','period_relative_range','extrema_relative_range','minimum_relative_amplitude','samples_per_period')}
    periodic={}
    for key in ('temperature_mean','Nu_top','velocity_rms','dissipation','dissipation_over_Ra'):
        vals=[s['diagnostics'][key] for s in samples]
        try: periodic[key]=atlas.periodic_window(t,vals,**periodic_options)
        except atlas.TectonicsError as exc:periodic[key]={'periodic_samples':False,'reason':str(exc)}
    report['steady_sampling']=steady;report['periodic_sampling']=periodic
    window=policy['steady']['window'];selected=[field for time,field in states if time>=last['time']-window]
    before=[time for time,_ in states if time<=last['time']-window]
    if selected and before and last['time']>=policy['steady']['minimum_time']:
        # Compare all saved fields to their latest field; coarse temporal sampling
        # is reported above and cannot on its own rule out unresolved oscillations.
        field_change=max(float(np.max(np.abs(field-selected[-1]))) for field in selected)
        field_ok=field_change<=policy['steady']['field_window_relative_linf']
    else:field_change=None;field_ok=False
    report['saved_field_steady_gate']=dict(change_linf=field_change,passed=field_ok,
        limitation='Finite stored-field sampling, not a proof that no between-sample oscillation exists')
    latest=samples[-1]['diagnostics'];report['latest_diagnostic_time']=float(t[-1]);report['latest_diagnostics']=latest
    endpoint_sample=bool(samples[-1]['state_id']==last['state_id'] and t[-1]==last['time'])
    report['latest_sample_is_saved_endpoint']=endpoint_sample
    report['latest_diagnostics_state_id']=samples[-1]['state_id']
    flux_error=abs(latest['Nu_top']-latest['Nu_bottom'])/max(abs(latest['Nu_top']),abs(latest['Nu_bottom']),1e-14)
    report['steady_heat_flux_gate']=dict(relative_imbalance=flux_error,passed=flux_error<=policy['steady']['thermal_flux_relative_imbalance'])
    report['work_gate']=dict(maximum_percent=max(s['diagnostics']['work_dissipation_percent'] for s in samples),
        passed=all(s['diagnostics']['work']>=0 and s['diagnostics']['work_dissipation_percent']<=policy['mechanical_work_percent_max'] for s in samples))
    balances={k:max((step['balances'][k] for step in steps),default=0.) for k in
        ('heat_relative_residual','composition_relative_residual','advective_local_residual','courant_stage0','courant_stage1')}
    report['every_accepted_step']=dict(count=len(steps),maxima=balances,
        max_picard_iterations=max((stage['nonlinear_iterations'] for step in steps for stage in step['mechanics']),default=0),
        max_linear_iterations=max((stage['linear_iterations'] for step in steps for stage in step['mechanics']),default=0),
        conservation_passed=max(balances[k] for k in ('heat_relative_residual','composition_relative_residual','advective_local_residual'))<=config['thermal_policy']['inventory_rtol'])
    if case in ('tosi-1','tosi-2','tosi-3','tosi-4'):
        report['table_comparison']=compare_table(case,latest,spec)
        report['mature_regime_gate']=bool(steady['steady_samples'] and field_ok and report['steady_heat_flux_gate']['passed'])
    elif case=='tosi-5a':
        periodic_metrics={}
        if periodic['Nu_top'].get('periodic_samples'):periodic_metrics['period']=periodic['Nu_top']['period']
        for k in ('temperature_mean','Nu_top','velocity_rms'):
            if periodic[k].get('periodic_samples'):
                periodic_metrics[k+'_min']=periodic[k]['minimum'];periodic_metrics[k+'_max']=periodic[k]['maximum']
        report['table_comparison']=compare_table(case,periodic_metrics,spec)
        ext=cycle_extrema(t,[q['diagnostics']['Nu_top'] for q in samples])
        field=phase_field_gate(states,ext.get('peak_times',[]),cycles=policy['periodic']['cycles'],
            samples_per_period=policy['periodic']['samples_per_period'],
            tolerance=policy['periodic']['field_phase_relative_linf'])
        report['periodic_field_gate']=field
        report['mature_regime_gate']=bool(field['passed'] and all(periodic[k].get('periodic_samples') for k in ('temperature_mean','Nu_top','velocity_rms','dissipation')))
        report['regime']='periodic' if report['mature_regime_gate'] else 'unresolved'
    else:
        report['table_comparison']=compare_table(case,{},spec)
        ext=cycle_extrema(t,[q['diagnostics']['Nu_top'] for q in samples])
        field=phase_field_gate(states,ext.get('peak_times',[]),cycles=policy['periodic']['cycles'],
            samples_per_period=policy['periodic']['samples_per_period'],
            tolerance=policy['periodic']['field_phase_relative_linf'])
        report['case5b_cycle_extrema']=ext;report['periodic_field_gate']=field
        stable=bool(steady['steady_samples'] and field_ok and report['steady_heat_flux_gate']['passed'])
        cyclic=bool(periodic['Nu_top'].get('periodic_samples') and field['passed'])
        report['mature_regime_gate']=stable or cyclic
        report['regime']='steady' if stable else ('periodic' if cyclic else 'unresolved')
    report['mature_regime_gate']=bool(report['mature_regime_gate'] and endpoint_sample)
    report['remaining_required_gates']=['Full matched-regime mesh adequacy','Full matched-regime timestep adequacy',
        'Full matched-regime nonlinear adequacy','Applicable case5b reference/regime comparison',
        'Case5a dissipation label resolution','Case5a/5b phase-matched field convergence',
        'Combined source-bound suite acceptance; one case never closes R4.4']
    report['status']='PER_RUN_GATES_REPORTED_NOT_FULL_ACCEPTANCE'
    return report


def study(reports,axis):
    if len(reports)!=3:raise ValueError('three source-bound run analyses required')
    if axis not in ('mesh','timestep','nonlinear'):raise ValueError('explicit study axis required')
    case=reports[0]['case']
    if any(r['case']!=case or r['source']!=reports[0]['source'] for r in reports):
        raise ValueError('study mixes cases or source identities')
    if not all(r.get('mature_regime_gate') for r in reports):
        return {'status':'NOT_A_MATURE_REGIME_ADEQUACY_STUDY','axis':axis,
                'full_benchmark_accepted':False,'reason':'All three independent mature-regime gates must pass first'}
    configs=[r['configuration'] for r in reports]
    settings=json.loads((ROOT/'cases/convection_r4_4.json').read_bytes())['predeclared_acceptance']['adequacy']
    normalised=[]
    for c in configs:
        d=json.loads(json.dumps(c))
        # Run duration and archive cadence are finite execution controls; the
        # mature regime and adequately sampled fields are checked separately.
        for k in ('maximum_steps','save_every','sample_every'):d.pop(k)
        d['thermal_policy'].pop('max_steps')
        if axis=='mesh':d.pop('cells')
        elif axis=='timestep':d.pop('dt')
        else:
            for k in ('linear_rtol','momentum_tolerance','viscosity_rtol'):d['nonlinear_policy'].pop(k)
        normalised.append(d)
    if normalised[1:]!=normalised[:-1]:raise ValueError('non-varied study controls differ')
    if axis=='mesh':
        coordinate=[c['cells'] for c in configs]
        expected=settings['mesh_cells']
    elif axis=='timestep':
        coordinate=[c['dt']/configs[0]['dt'] for c in configs]
        expected=settings['timestep_ratios']
    else:
        coordinate=[c['nonlinear_policy']['momentum_tolerance']/configs[0]['nonlinear_policy']['momentum_tolerance'] for c in configs]
        expected=settings['nonlinear_tolerance_factors']
        for k in ('linear_rtol','viscosity_rtol'):
            if not np.allclose([c['nonlinear_policy'][k]/configs[0]['nonlinear_policy'][k] for c in configs],expected,rtol=1e-12,atol=0):
                raise ValueError('incomplete declared nonlinear tightening study')
    if not np.allclose(coordinate,expected,rtol=1e-12,atol=0):
        return {'status':'EXPLORATORY_NOT_PREDECLARED_ADEQUACY_GRID','axis':axis,
            'coordinates':coordinate,'required':expected,'full_benchmark_accepted':False}
    regimes=[r.get('regime','steady' if case['name'] in ('tosi-1','tosi-2','tosi-3','tosi-4') else 'unresolved') for r in reports]
    if len(set(regimes))!=1 or regimes[0] not in ('steady','periodic'):
        raise ValueError('study has unmatched or unresolved physical regimes')
    if regimes[0]=='periodic':
        metric_sets=[]
        for r in reports:
            metrics={}
            for k in ('temperature_mean','Nu_top','velocity_rms','dissipation','dissipation_over_Ra'):
                signal=r['periodic_sampling'][k]
                if not signal.get('periodic_samples'):raise ValueError('periodic study missing resolved signal')
                for name in ('period','minimum','maximum'):metrics[k+'_'+name]=signal[name]
            metric_sets.append(metrics)
    else:metric_sets=[{k:r['latest_diagnostics'][k] for k in _METRICS} for r in reports]
    differences=atlas.refinement_differences(*metric_sets)
    threshold=settings[{'mesh':'mesh','timestep':'time','nonlinear':'nonlinear'}[axis]+'_finest_pair_relative_change']
    checks={}
    for key,d in differences.items():
        a,b,c=(m[key] for m in metric_sets)
        monotone=(b-a)*(c-b)>=0 or max(abs(b-a),abs(c-b))<=64*np.finfo(float).eps*max(1.,abs(c))
        checks[key]=bool(d['middle_to_fine']<=threshold and d['middle_to_fine']<=d['coarse_to_middle']+1e-14 and monotone)
    return {'status':'ADEQUACY_GATE_PASSED' if all(checks.values()) else 'ADEQUACY_GATE_FAILED',
            'axis':axis,'coordinates':coordinate,'threshold':threshold,'diagnostic_differences':differences,
            'per_metric_passed':checks,'full_benchmark_accepted':False}



def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--study-axis',choices=('mesh','timestep','nonlinear'))
    args=p.parse_args();safe_path(args.output)
    reports=[analyse_run(path.absolute()) for path in args.run]
    out={'runs':reports,'full_benchmark_accepted':False}
    if args.study_axis:out['study']=study(reports,args.study_axis)
    atomic_new(args.output,out)
    print(json.dumps({'analysed_runs':len(reports),'output':str(args.output),'full_benchmark_accepted':False}))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,atlas.TectonicsError) as exc:
        print(json.dumps({'status':'REFUSED','error':str(exc)}),file=sys.stderr);raise SystemExit(2)
