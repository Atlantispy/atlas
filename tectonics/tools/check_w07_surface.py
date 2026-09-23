#!/usr/bin/env python3
"""Bounded B09 acceptance and equal-output latest-snapshot timing.

SPDX-License-Identifier: AGPL-3.0-only
Exclusive new reports preserve failures. 4x2, 8x4, 16x8 Q2/P1 elements;
16/32/64 SSP-RK2 intervals, two frozen amplitudes. No long geological run.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),str(ROOT/'tools')]
import numpy as np
from atlas_tectonics import PreparedFreeSurface2D, RegionalMechanicsScales
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.stokes_execution import _native_lease
from atlas_tectonics.surface_geometry import q2, cell_volume_and_flux
from w07_surface_reference import decay_rate, traction_bvp_rate
from check_w07_mechanics import Recorder, SourceChanged, _jsonable, _snapshot_hash

FROZEN_DESIGN='1748c9e2bd43f71ad0ce65fb9d68343d3f1379570f1b2b74882b85fa2c644378'
FROZEN_CASE='07954c94de0099bea8a7d188907a715ddcac2265e4d4a51ce7488505d89c32b9'


def sources():
    paths=[*sorted((ROOT/'src/atlas_tectonics').glob('*.py')),Path(__file__),
        ROOT/'tests/w07_surface_reference.py', ROOT/'tools/check_w07_mechanics.py',
        ROOT/'docs/W07_REGIONAL_MECHANICS.md',ROOT/'cases/w07_mechanics.json']
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


class SurfaceRecorder(Recorder):
    def verify(self):
        if sources()!=self.sources:raise SourceChanged('surface source/case bytes changed; no acceptance repin')


def plan(nx,nz,owner):
    return PreparedFreeSurface2D(nx,nz,2.,0.,1.,viscosity_pa_s=1.,density_kg_m3=1.,
        gravity_m_s2=1.,external_pressure_pa=0.,strike_width_m=1.,
        scales=RegionalMechanicsScales(1.,1.),frame_id='B09-x-right-z-up',
        vertical_datum='synthetic bottom z=0',material_source='B09 eta=rho=1 homogeneous isothermal',
        load_source='B09 explicit downward gravity1 and external pressure0',budget=owner)


def amplitude(state,harmonic=1):
    mesh=state.array('mesh_nodes_m');top=mesh[-1]
    local=top[np.arange((len(top)-1)//2)[:,None]*2+np.arange(3)]
    q,w=np.polynomial.legendre.leggauss(8);n=q2(q)
    x=np.einsum('qi,ei->eq',n,local[...,0]);h=np.einsum('qi,ei->eq',n,local[...,1])-1.
    # W=2, cosine squared integral=W/2=1; dx=hcell/2 dq.
    return float(np.sum(w[None,:]*h*np.cos(harmonic*np.pi*x)*(local[:,2,0]-local[:,0,0])[:,None]/2))


def oracle():
    ks=(.2,.7,1.,np.pi,6.)
    errors=[abs(decay_rate(k,1.)/traction_bvp_rate(k,1.)-1.) for k in ks]
    thin=abs(decay_rate(1e-4,1.)/(1e-8/3)-1.)
    deep=abs(decay_rate(30.,1.)/(1/60)-1.)
    if max(errors)>1e-11 or thin>2e-8 or deep>1e-12:raise AssertionError('independent finite-depth oracle/limits failed')
    return dict(gamma=decay_rate(np.pi,1.),biharmonic_boundary_value_relative_errors=errors,
        thin_limit_relative_error=thin,deep_limit_relative_error=deep,
        convention='positive decay; no-slip bottom, free-slip vertical sides, tractionfree top')


def trajectory(nx,nz,steps,a,owner):
    gamma=decay_rate(np.pi,1.);rows=[];maxima={};started=time.perf_counter()
    with plan(nx,nz,owner) as prepared:
        x=np.linspace(0.,2.,2*nx+1)
        state=prepared.initial_state(1+a*np.cos(np.pi*x),epoch_id='B09 synthetic relaxation')
        initial_volume=float(cell_volume_and_flux(state.array('mesh_nodes_m'))[0].sum())
        def capture(t):
            measured=amplitude(state);reference=a*np.exp(-gamma*t)
            volume=float(cell_volume_and_flux(state.array('mesh_nodes_m'))[0].sum())
            row=dict(time_s=t,scaled_time=gamma*t,amplitude_m=measured,reference_amplitude_m=reference,
                relative_amplitude_error=abs(measured/reference-1.),
                second_harmonic_m=amplitude(state,2),volume_relative_error=abs(volume/initial_volume-1.))
            rows.append(row)
        capture(0.)
        for quarter in range(4):
            result=prepared.advance(state,.25/gamma,steps=steps//4);state=result.state
            for interval in result.descriptor()['intervals']:
                for key in ('volume_residual_scaled','mass_residual_scaled','uniform_density_residual_scaled'):
                    maxima[key]=max(maxima.get(key,0.),interval[key])
            d=result.mechanics.descriptor()['diagnostics']
            if not d['gates_passed']:raise AssertionError('endpoint mechanical gates failed')
            for key in ('momentum_residual','weak_continuity_scaled_max','normalised_work_residual','linear_residual'):
                maxima[key]=max(maxima.get(key,0.),d[key])
            capture((quarter+1)*.25/gamma)
        stats=prepared.statistics()
        final_height=state.array('mesh_nodes_m')[-1,:,1].tolist()
    if max(r['volume_relative_error'] for r in rows)>1e-9:raise AssertionError('B09 trajectory volume gate failed')
    return dict(nx=nx,nz=nz,elements='Q2 velocity/geometry; physical P1-discontinuous pressure',
        accepted_steps=steps,initial_amplitude_m=a,observations=rows,maxima=maxima,
        final_surface_elevation_m=final_height,statistics=stats,elapsed_seconds=time.perf_counter()-started)


def convergence(results):
    evidence={}
    for a in (1e-4,5e-5):
        spatial=[results[(nx,nz,64,a)] for nx,nz in ((4,2),(8,4),(16,8))]
        errors=[max(row['relative_amplitude_error'] for row in r['observations']) for r in spatial]
        temporal=[results[(16,8,s,a)] for s in (16,32,64)]
        h=[np.array(r['final_surface_elevation_m']) for r in temporal]
        differences=[float(np.linalg.norm(h[0]-h[1])/a),float(np.linalg.norm(h[1]-h[2])/a)]
        if not errors[2]<errors[1]<errors[0] or errors[2]>.01:
            raise AssertionError('B09 spatial/amplitude gate failed: '+str(errors))
        if not 0.<differences[1]<differences[0]:raise AssertionError('B09 timestep refinement failed: '+str(differences))
        evidence[str(a)]=dict(spatial_max_relative_amplitude_errors=errors,
            temporal_successive_surface_l2_over_initial_amplitude=differences,
            temporal_difference_ratio=differences[0]/differences[1])
    full=results[(16,8,64,1e-4)]['observations'][-1]
    half=results[(16,8,64,5e-5)]['observations'][-1]
    evidence['amplitude_linearity']=dict(full_normalised=full['amplitude_m']/1e-4,
        half_normalised=half['amplitude_m']/5e-5,
        difference=abs(full['amplitude_m']/1e-4-half['amplitude_m']/5e-5),
        full_second_harmonic_m=full['second_harmonic_m'],half_second_harmonic_m=half['second_harmonic_m'])
    if evidence['amplitude_linearity']['difference']>1e-4:raise AssertionError('B09 small-amplitude linearity failed')
    return evidence


def timing(owner):
    raw={'fresh':[],'retained':[]};hashes={};orders=[]
    for repeat in range(3):
        order=('fresh','retained') if repeat%2==0 else ('retained','fresh');orders.append(order)
        for mode in order:
            began=time.perf_counter();prepared=None;actual=[]
            try:
                for i in range(3):
                    if prepared is None:
                        prepared=plan(16,8,owner)
                        x=np.linspace(0.,2.,33)
                        state=prepared.initial_state(1+1e-4*np.cos(np.pi*x),epoch_id='B09 timing')
                    snapshot=prepared.mechanics(state)
                    if not snapshot.descriptor()['diagnostics']['gates_passed']:raise AssertionError('timing gates failed')
                    actual.append(_snapshot_hash(snapshot))
                    if mode=='fresh':prepared.close();prepared=None
                if mode=='retained' and prepared.statistics()['latest_result_hits']!=2:
                    raise AssertionError('two identical snapshot hits required')
            finally:
                if prepared is not None:prepared.close()
            raw[mode].append(time.perf_counter()-began);hashes[(repeat,mode)]=actual
        if hashes[(repeat,'fresh')]!=hashes[(repeat,'retained')]:raise AssertionError('timing outputs not byte-identical')
    before,after=statistics.median(raw['fresh']),statistics.median(raw['retained'])
    return dict(raw_seconds=raw,rotating_order=orders,before_median_seconds=before,after_median_seconds=after,
        saved_seconds=before-after,saved_percent=100*(before-after)/before,output_parity='byte-identical all fields',
        scope='three identical 16x8 mechanical outputs; setup, source verification, hashing and close included; not evolving geometry')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--mode',choices=('acceptance','timing','all'),default='all')
    args=parser.parse_args()
    report=dict(schema='atlas.w07-surface-evidence.v1',source_status='WORKING NON-CANON',
        mode=args.mode,runtime=dict(python=sys.version,platform=platform.platform()),checks=[],
        limits=dict(accounted_bytes=128*1024**2,native_threads=1,accepted_steps_per_trajectory=256))
    with args.report.open('x',encoding='utf-8') as output:
        owner=WorkBudget(128*1024**2)
        try:
            pinned=sources();report['source_sha256']=pinned
            if pinned['docs/W07_REGIONAL_MECHANICS.md']!=FROZEN_DESIGN or pinned['cases/w07_mechanics.json']!=FROZEN_CASE:
                raise SourceChanged('frozen W07 design/case mismatch')
            import scipy
            from threadpoolctl import threadpool_info
            report['runtime'].update(numpy=np.__version__,scipy=scipy.__version__)
            recorder=SurfaceRecorder(report,pinned)
            with _native_lease(),owner.reserve(4*1024**2,category='surface-runner-caller'):
                report['runtime']['threadpools']=[{k:p.get(k) for k in ('internal_api','num_threads')} for p in threadpool_info()]
                if any(p['num_threads']!=1 for p in report['runtime']['threadpools']):raise RuntimeError('one native thread not established')
                if args.mode in ('all','acceptance'):
                    recorder.call('B09/independent-oracle',oracle);results={}
                    for a in (1e-4,5e-5):
                        for nx,nz,n in ((4,2,64),(8,4,64),(16,8,16),(16,8,32),(16,8,64)):
                            label=f'B09/{nx}x{nz}/{n}/{a}'
                            value=recorder.call(label,lambda nx=nx,nz=nz,n=n,a=a:trajectory(nx,nz,n,a,owner))
                            if value is None:raise RuntimeError('trajectory failed; stop without changing limits')
                            results[(nx,nz,n,a)]=value
                            print(json.dumps(dict(case=label,status='PASS',elapsed_seconds=value['elapsed_seconds'])),flush=True)
                    recorder.call('B09/convergence',lambda:convergence(results))
                if args.mode in ('all','timing'):recorder.call('timing/identical-requests',lambda:timing(owner))
            recorder.verify()
            if owner.reserved_bytes:recorder.gate('resource-cleanup',False,owner.statistics())
            report['status']='PASS' if all(r['status']=='PASS' for r in report['checks']) else 'FAIL'
        except BaseException as exc:
            report['status']='FAIL';report['fatal']=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc(limit=7))
        report['budget']=owner.statistics()
        json.dump(_jsonable(report),output,indent=2,allow_nan=False);output.write('\n');output.flush()
    print(json.dumps(dict(status=report['status'],checks=len(report['checks']),report=str(args.report),fatal=report.get('fatal'))))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
