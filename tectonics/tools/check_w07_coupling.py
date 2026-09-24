"""Bounded active W07 thermal/mechanical coupling refinement diagnostic.

Default heat refinement 16 isolates coupling error in the recorded synthetic case.
Refinement 1 retains the known failing heat/coupling error-separation diagnostic.
Read-only Atlas imports; writes new evidence only. Not R4.4 or field validation.
Run with an existing compatible interpreter using -I -B; installs nothing.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
import traceback


CRITERIA = {
    'grid': [16, 16], 'width_m': 1.0, 'height_m': 1.0, 'total_time_s': 1.0,
    'mechanical_intervals': [8, 16, 32], 'heat_steps_per_interval': [4, 2, 1],
    'common_heat_dt_s': 1.0 / 32, 'heat_check_steps_per_interval': 2,
    'first_order_difference_ratio_min': 1.5, 'first_order_difference_ratio_max': 2.8,
    'thermal_substep_effect_max_fraction': 0.2,
    'initial_advection_rms_min_k_s': 1e-8,
    'active_minus_zero_velocity_final_temperature_rms_min_k': 8e-6,
    'relative_viscosity_change_min': 1e-4,
    'temperature_difference_roundoff_floor_k': 1e-10,
    'velocity_difference_roundoff_floor_m_s': 1e-12,
    'viscosity_difference_roundoff_floor_pa_s': 1e-12,
    'accounted_budget_bytes': 128 * 1024**2,
    'native_threads': 1,
    'no_retuning_or_gate_relaxation': True,
    'scope': 'same-grid time-splitting diagnostic; not a continuum or field oracle',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources(repo):
    root = repo / 'tectonics'
    paths = sorted((root / 'src/atlas_tectonics').glob('*.py'))
    paths += [root / 'tests/test_w07_thermomechanical.py',
              root / 'tests/test_w07_regional_rheology.py']
    return {str(p.relative_to(repo)).replace('\\', '/'): sha(p) for p in paths}


def error_record(exc, repo):
    """Retain error and stack location without publishing private absolute paths."""
    message = str(exc)
    for base in (str(repo), sys.prefix, sys.base_prefix, str(Path(__file__).parent)):
        message = message.replace(base, '<local>').replace(base.replace('\\', '/'), '<local>')
    return dict(type=type(exc).__name__, message=message,
        frames=[dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                for f in traceback.extract_tb(exc.__traceback__)])


@contextmanager
def claimed_outputs(report_path, fields_path):
    """Leave a valid INCOMPLETE receipt if setup or the second claim fails."""
    with report_path.open('x',encoding='utf-8') as handle:
        json.dump(dict(schema='atlas.w07.active-coupling.v1',status='INCOMPLETE',
            execution_complete=False,reason='output setup has not completed'),handle,indent=2)
        handle.flush()
        with fields_path.open('xb') as fields_handle:
            yield handle,fields_handle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path,
        help='Override repository root; normally inferred from tectonics/tools location')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--fields', type=Path, required=True)
    parser.add_argument('--heat-refinement', type=int, choices=(1,16), default=16,
        help='16: resolved heat-step check; 1: known failing error-separation diagnostic')
    args = parser.parse_args()
    refinement = args.heat_refinement
    refined_criteria = dict(CRITERIA,
        heat_refinement=refinement, base_heat_dt_s=CRITERIA['common_heat_dt_s'],
        common_heat_dt_s=CRITERIA['common_heat_dt_s']/refinement,
        heat_steps_per_interval=[v*refinement for v in CRITERIA['heat_steps_per_interval']],
        heat_check_steps_per_interval=CRITERIA['heat_check_steps_per_interval']*refinement,
        refinement_status=('known failing heat/coupling error-separation diagnostic' if refinement==1 else
                           'refined heat resolution; identical physical inputs and scientific criteria'),
        interval_limit_scope='<=256 heat substeps per public interval; not PreparedW07Workflow cumulative stepping')
    repo = (args.repo or Path(__file__).resolve().parents[2]).resolve(strict=True)
    if not (repo/'tectonics/src/atlas_tectonics').is_dir():
        parser.error('repository root does not contain tectonics/src/atlas_tectonics; supply --repo')
    # Claim both exact destinations before importing scientific dependencies.
    with claimed_outputs(args.report,args.fields) as (handle,fields_handle):
        report = dict(schema='atlas.w07.active-coupling.v1',
            status='INCOMPLETE', execution_complete=False, source_status='WORKING NON-CANON', criteria=refined_criteria,
            script_sha256=sha(__file__), python_executable_sha256=sha(sys.executable),
            python=sys.version, platform=platform.platform(), sources_before=sources(repo),
            runs=[], gates=[], no_production_edits=True, r44_run=False,
            resource_scope='shared accounted work cap; caller-retained diagnostic arrays and process RSS are separate')
        handle.seek(0);handle.truncate()
        json.dump(report, handle, indent=2)
        handle.flush()
        started = time.perf_counter()
        arrays = {}
        try:
            for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                        'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
                os.environ[key] = '1'
            sys.path.insert(0, str(repo / 'tectonics/src'))
            import numpy as np
            import scipy
            import threadpoolctl
            from atlas_tectonics import (PreparedRegionalStokes2D, RegionalMechanicsScales,
                RectangularTransportGrid, PreparedHeatTransport, HeatBoundary,
                advance_regional_thermomechanics)
            from atlas_tectonics.constitutive import DiffusiveScales, RheologyProfile
            from atlas_tectonics.resources import WorkBudget
            from atlas_tectonics.stokes_execution import _native_lease

            report['runtime'] = dict(numpy=np.__version__, scipy=scipy.__version__,
                threadpoolctl=threadpoolctl.__version__)
            n = 16
            x, z = np.meshgrid((np.arange(n)+.5)/n, (np.arange(n)+.5)/n)
            xw, zw = np.meshgrid((np.arange(n)+.5)/n, np.arange(n+1)/n)
            initial = 800. + 80.*np.cos(np.pi*x)*np.cos(2*np.pi*z)*np.sinc(1/(2*n))*np.sinc(1/n)
            fu, fw = np.zeros((n, n+1)), .1*np.sin(np.pi*xw)*np.cos(np.pi*zw)
            pattern = {s: {'u': 'velocity' if s in ('left','right') else 'traction',
                           'w': 'traction' if s in ('left','right') else 'velocity'}
                       for s in ('left', 'right', 'bottom', 'top')}
            boundary = {s: {'u': 0., 'w': 0.} for s in pattern}
            thermal_boundary = {s: HeatBoundary(None, 'outward_flux', 0.) for s in pattern}
            profile = RheologyProfile('review-active-thermal-split', 'tosi-linear',
                'preregistered synthetic numerical challenge, not a material calibration',
                (('contrast_T', math.exp(4)), ('contrast_z', 1.)))
            scales = DiffusiveScales('review explicit SI', 1., .01, 1., 300., 1000., 1.)
            arrays.update(initial_temperature_k=initial, x_centres_m=x, z_centres_m=z)

            def rms(a):
                return float(np.sqrt(np.mean(np.asarray(a)**2)))

            def gate(name, passed, **details):
                report['gates'].append(dict(name=name, passed=bool(passed), **details))

            def fields(result):
                return dict(temperature_k=np.array(result.temperature_k),
                    velocity_m_s=np.r_[result.mechanics.array('u_m_s').ravel(),
                                       result.mechanics.array('w_m_s').ravel()],
                    viscosity_pa_s=np.r_[result.mechanics.array('viscosity_center_pa_s').ravel(),
                                         result.mechanics.array('viscosity_vertex_pa_s').ravel()])

            def run(intervals, heat_steps, label):
                owner = WorkBudget(CRITERIA['accounted_budget_bytes'])
                heat = PreparedHeatTransport(RectangularTransportGrid(n,n,1.,1.,'review'), .01, 1., budget=owner)
                row = dict(label=label, intervals=intervals, heat_steps_per_interval=heat_steps,
                    accepted_heat_steps=intervals*heat_steps, status='RUNNING', completed_intervals=0)
                report['runs'].append(row)
                before = time.perf_counter()
                try:
                    with PreparedRegionalStokes2D(n,n,1.,1.,1.,pattern,
                            scales=RegionalMechanicsScales(1.,1.), frame_id='review',
                            vertical_datum='bottom', material_source='synthetic seed',
                            physical_mean_pressure_pa=0., budget=owner) as plan:
                        T = initial
                        balances = []
                        limits = []
                        for j in range(intervals):
                            result = advance_regional_thermomechanics(plan,heat,profile,scales,T,fu,fw,
                                boundary,1./intervals,heat_steps=heat_steps,heat_boundaries=thermal_boundary,
                                frame_id='review',epoch_id='review-forward',time_s=j/intervals,
                                thermal_source='same initial means then prior candidate endpoint',
                                material_source='fixed explicit T-dependent law',
                                force_source='fixed sine body force',boundary_source='closed free slip',
                                heat_boundary_source='closed zero flux',heat_source='uniform 20 W/m3',
                                thermal_sampling='cell-mean-linear-centre-and-vertex-v1',source_w_m3=20.)
                            if j == 0:
                                eta0 = np.r_[result.initial_mechanics.array('viscosity_center_pa_s').ravel(),
                                             result.initial_mechanics.array('viscosity_vertex_pa_s').ravel()]
                                u0,w0 = (result.initial_mechanics.array(k) for k in ('u_m_s','w_m_s'))
                                adv = ((u0[:,:-1]+u0[:,1:])*.5*(-80*np.pi*np.sin(np.pi*x)*np.cos(2*np.pi*z))
                                    +(w0[:-1]+w0[1:])*.5*(-160*np.pi*np.cos(np.pi*x)*np.sin(2*np.pi*z)))
                                row['initial_advection_tendency_rms_k_s'] = rms(adv)
                                row['initial_mechanics_id'] = result.initial_mechanics.result_id
                            T = result.temperature_k
                            balances.append(result.descriptor()['heat']['balance_relative'])
                            limits.append(result.descriptor()['heat']['timestep_limit_s'])
                            row['completed_intervals'] = j+1
                        out = fields(result)
                        row.update(status='COMPLETE', final_mechanics_id=result.mechanics.result_id,
                            maximum_heat_balance_relative=max(balances), minimum_heat_dt_limit_s=min(limits),
                            relative_viscosity_change=rms(out['viscosity_pa_s']-eta0)/rms(eta0),
                            final_diagnostics=result.mechanics.descriptor()['diagnostics'])
                        for key,value in out.items(): arrays[label+'_'+key]=value
                        arrays[label+'_u_m_s']=np.array(result.mechanics.array('u_m_s'))
                        arrays[label+'_w_m_s']=np.array(result.mechanics.array('w_m_s'))
                    return out
                except BaseException as exc:
                    row.update(status='INCOMPLETE' if isinstance(exc,KeyboardInterrupt) else 'FAILED',
                               error=error_record(exc,repo))
                    raise
                finally:
                    row.update(seconds=time.perf_counter()-before, budget=owner.statistics())
                    row['accounted_reservations_released'] = row['budget']['reserved_bytes']==0

            with _native_lease():
                report['native_pools'] = [dict(p,filepath=Path(p['filepath']).name)
                    for p in threadpoolctl.threadpool_info()]
                if any(p['num_threads'] != 1 for p in report['native_pools']):
                    raise RuntimeError('one-native-thread prerequisite failed')
                outputs = [run(N,h*refinement,'n'+str(N)) for N,h in zip((8,16,32),(4,2,1))]
                thermal_check = run(32,2*refinement,'n32_half_heat_dt')
                owner = WorkBudget(CRITERIA['accounted_budget_bytes'])
                heat = PreparedHeatTransport(RectangularTransportGrid(n,n,1.,1.,'review'), .01, 1., budget=owner)
                # Keep each existing heat.evolve call within its 256-step limit.
                # One or sixteen equal intervals preserve the chosen heat step.
                passive = initial
                for j in range(refinement):
                    passive = heat.evolve(passive,np.zeros_like(fu),np.zeros_like(fw),1./refinement,
                        steps=32,boundaries=thermal_boundary,time_s=j/refinement,
                        source_w_m3=20.)['temperature_k']
                arrays['zero_velocity_temperature_k']=passive
                report['passive_control_complete']=True
                report['passive_control_budget']=owner.statistics()
                for field, floor in (('temperature_k',1e-10),('velocity_m_s',1e-12),('viscosity_pa_s',1e-12)):
                    coarse = rms(outputs[0][field]-outputs[1][field])
                    fine = rms(outputs[1][field]-outputs[2][field])
                    ratio = coarse/fine if fine else None
                    thermal_effect = rms(thermal_check[field]-outputs[2][field])
                    gate('coupling-order/'+field, fine>floor and ratio is not None and 1.5<=ratio<=2.8,
                        coarse_difference_rms=coarse,fine_difference_rms=fine,ratio=ratio,roundoff_floor=floor)
                    gate('heat-error-separation/'+field, thermal_effect<.2*fine,
                        heat_effect_rms=thermal_effect,coupling_difference_rms=fine,max_fraction=.2)
                gate('active-advection',report['runs'][0]['initial_advection_tendency_rms_k_s']>1e-8,
                    initial_tendency_rms_k_s=report['runs'][0]['initial_advection_tendency_rms_k_s'])
                activity=rms(outputs[2]['temperature_k']-passive)
                gate('advection-affects-temperature',activity>8e-6,temperature_difference_rms_k=activity)
                change=report['runs'][2]['relative_viscosity_change']
                gate('temperature-changes-viscosity',change>1e-4,relative_change=change)
                report['execution_complete']=True
        except BaseException as exc:
            report['fatal'] = error_record(exc,repo)
            report['interrupted']=isinstance(exc,KeyboardInterrupt)
        finally:
            report['sources_after'] = sources(repo)
            report['script_sha256_after']=sha(__file__)
            unchanged = (report['sources_before'] == report['sources_after'] and
                         report['script_sha256']==report['script_sha256_after'])
            report['gates'].append(dict(name='unchanged-source',passed=unchanged))
            modules = {}
            for name,module in tuple(sys.modules.items()):
                path = getattr(module,'__file__',None)
                if path and Path(path).is_file() and (name.split('.')[0] in ('numpy','scipy','threadpoolctl') or
                        Path(path).suffix.lower() in ('.pyd','.dll','.so')):
                    modules[name] = dict(file=Path(path).name,sha256=sha(path))
            report['loaded_runtime_module_hashes'] = modules
            report['elapsed_seconds'] = time.perf_counter()-started
            required = {'unchanged-source','active-advection','advection-affects-temperature',
                        'temperature-changes-viscosity'}
            required.update(prefix+'/'+field for prefix in ('coupling-order','heat-error-separation')
                            for field in ('temperature_k','velocity_m_s','viscosity_pa_s'))
            names=[g['name'] for g in report['gates']]
            complete=(report['execution_complete'] and len(report['runs'])==4 and
                all(r['status']=='COMPLETE' for r in report['runs']) and
                len(names)==len(required) and set(names)==required)
            released=(all(r.get('accounted_reservations_released',False) for r in report['runs']) and
                report.get('passive_control_budget',{}).get('reserved_bytes')==0)
            report['accounted_reservations_released']=released
            report['status']=('INCOMPLETE' if report.get('interrupted') else
                'PASS' if complete and released and 'fatal' not in report and all(g['passed'] for g in report['gates']) else 'FAIL')
            if 'np' in locals():
                np.savez_compressed(fields_handle,**arrays)
                fields_handle.flush()
                report['output_arrays']={name:dict(shape=list(value.shape),dtype=value.dtype.str,
                    sha256=hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest())
                    for name,value in arrays.items()}
                report['fields_sha256']=sha(args.fields)
            report['field_keys'] = sorted(arrays)
            report['fields_file'] = args.fields.name
            handle.seek(0); handle.truncate()
            json.dump(report,handle,indent=2,allow_nan=False); handle.write('\n')
        print(json.dumps(dict(status=report['status'],elapsed_seconds=report['elapsed_seconds'],
            fatal=report.get('fatal'),gates=report['gates'],report=args.report.name,fields=args.fields.name)))
        return 0 if report['status']=='PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
