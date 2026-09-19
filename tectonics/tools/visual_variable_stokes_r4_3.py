#!/usr/bin/env python3
"""Actual R4.3 variable/yielding mechanics and short coupled evolution visuals.
SPDX-License-Identifier: AGPL-3.0-only
Authored numerical inputs, not a reproduced Tosi convection benchmark or terrain.
"""
from __future__ import annotations
from pathlib import Path
import argparse,hashlib,json,os,shutil,sys,tempfile
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),str(ROOT)]
from atlas_tectonics import (PreparedVariableStokes2D,PreparedThermochemical2D,
                            boussinesq_response,face_force_from_density)
from atlas_tectonics.resources import WorkBudget
from variable_stokes_fixtures import forcing,request,refinement,coupled_problem
from thermochemical_fixtures import initial


def build_data():
    case=json.loads((ROOT/'cases/variable_stokes_r4_3.json').read_text());spec=case['visual_case']
    b,s,fx,fz,T,profile=forcing(spec['snapshot_grid'],key=spec['profile']);budget=WorkBudget(512<<20)
    with PreparedVariableStokes2D(b,s,budget=budget) as solver:
        r=solver.solve_rheology(fx,fz,T,profile,**request(b))
    data={'snapshot_'+k:r.array(k) for k in r.array_names}
    data['snapshot_x_m'],data['snapshot_z_m']=b.axes()
    params=dict(profile.parameters)
    _,z=np.meshgrid(*b.axes());linear=np.exp(-np.log(params['contrast_T'])*(T-1)+np.log(params['contrast_z'])*(1-z))
    data['viscosity_fraction_of_zero_rate']=r.array('viscosity_cell_pa_s')/(2*linear)
    history=r.descriptor()['nonlinear_history']
    data['nonlinear_momentum_residual']=np.asarray([h['momentum_linf'] for h in history])
    data['viscosity_log_change']=np.asarray([h['viscosity_log_change'] for h in history])
    refs=[refinement(n) for n in (8,16,32)]
    data['refinement_n']=np.asarray([x['n'] for x in refs])
    for key in ('u_l2','w_l2','p_l2'):data['refinement_'+key]=np.asarray([x[key] for x in refs])
    p=coupled_problem(spec['coupled_grid']);start=initial(p);st=start;records=[]
    with PreparedThermochemical2D(p,budget=budget) as solver:
        for _ in range(spec['coupled_steps']):
            step=solver.advance(st,spec['coupled_dt_s'],source='authored R4.3 short coupled numerical visual');st=step.state;records.append(step.descriptor()['record'])
    data.update(initial_temperature_k=start.array('temperature_k'),initial_composition=start.array('composition'),
                evolved_temperature_k=st.array('temperature_k'),evolved_composition=st.array('composition'))
    # Solve AGAIN from the accepted endpoint: do not mislabel the last RK stage.
    response=boussinesq_response(p.material,st.array('temperature_k'),st.array('composition'),p.gravity_m_s2,
                                np.zeros(st.array('temperature_k').shape+(2,)),budget=budget)
    forces=face_force_from_density(p.box,response['density_anomaly_kg_m3'],p.gravity_m_s2,budget=budget)
    with PreparedVariableStokes2D(p.box,p.scales,budget=budget) as solver:
        end=solver.solve_rheology(*forces,st.array('temperature_k'),p.rheology,frame_id=p.box.frame_id,epoch_id=p.epoch_id,
                                time_s=st.time_s,source='mechanics recomputed from accepted evolved fields')
    data.update(endpoint_u_m_s=end.array('u_m_s'),endpoint_w_m_s=end.array('w_m_s'))
    data['coupled_x_m'],data['coupled_z_m']=p.box.axes()
    provenance=dict(snapshot=r.descriptor(),snapshot_id=r.result_id,initial_state_id=start.state_id,final_state=st.descriptor(),final_state_id=st.state_id,
        endpoint_solution_id=end.result_id,step_records=records,coupled_problem=p.descriptor(),budget=budget.statistics(),
        origin='AUTHORED numerical controls. Mechanics SOLVED; final thermal/composition EVOLVED. Not calibrated Earth or full published convection.',
        viscosity_reduction='Continuous eta/(zero-rate Tosi eta); not a discrete yielded/not-yielded classification.',
        display_interpolation='Only arrows/speed use arithmetic face-to-centre means; raw staggered arrays retained.')
    return data,provenance,refs


def render(destination):
    from verify import source_inventory
    before=source_inventory(ROOT)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    data,provenance,refs=build_data();x=data['snapshot_x_m'];z=data['snapshot_z_m']
    u=.5*(data['snapshot_u_m_s'][:,1:]+data['snapshot_u_m_s'][:,:-1]);w=.5*(data['snapshot_w_m_s'][1:]+data['snapshot_w_m_s'][:-1])
    note='R4 IN PROGRESS | Authored unit-scale numerical control | Actual variable-viscosity solution, not Earth-calibrated convection'
    def finish(fig,ax,name,title):
        ax.set(xlabel='x (m, numerical control)',ylabel='Height above bottom (m)',title=title,aspect='equal')
        fig.text(.5,.025,note,ha='center',fontsize=8);fig.tight_layout(rect=(0,.05,1,1));fig.savefig(destination/name,dpi=170);plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,8));im=ax.pcolormesh(x,z,np.hypot(u,w),shading='nearest')
    fig.colorbar(im,ax=ax,label='Display-centred speed (m/s, unit-scale control)')
    ax.quiver(x[::3],z[::3],u[::3,::3],w[::3,::3],angles='xy');finish(fig,ax,'01_solved_velocity.png','Atlas R4.3 | Nonlinear solved velocity')
    for key,name,title,label in (
        ('snapshot_viscosity_cell_pa_s','02_variable_viscosity.png','Spatially varying effective viscosity','log10(viscosity / Pa s)'),
        ('viscosity_fraction_of_zero_rate','03_viscosity_reduction.png','Continuous plastic viscosity reduction','Effective viscosity / zero-rate Tosi viscosity'),
        ('snapshot_pressure_pa','04_dynamic_pressure.png','Solved dynamic pressure, zero domain mean','Dynamic pressure (Pa)')):
        values=np.log10(data[key]) if key=='snapshot_viscosity_cell_pa_s' else data[key]
        fig,ax=plt.subplots(figsize=(9,8));im=ax.pcolormesh(x,z,values,shading='nearest');fig.colorbar(im,ax=ax,label=label)
        finish(fig,ax,name,'Atlas R4.3 | '+title)
    fig,ax=plt.subplots(figsize=(10,6));its=np.arange(1,len(data['nonlinear_momentum_residual'])+1)
    for key,label in (('nonlinear_momentum_residual','True updated-law momentum residual'),('viscosity_log_change','Maximum log-viscosity change')):
        ax.semilogy(its,data[key],marker='o',label=label)
    ax.axhline(1e-9,linestyle=':',label='Momentum gate');ax.axhline(1e-8,linestyle='--',label='Log-viscosity gate')
    ax.set(xlabel='Picard iteration',ylabel='Normalised residual / log coefficient change',title='Atlas R4.3 | Convergence of the actual nonlinear equation')
    ax.legend();ax.grid(True,alpha=.25);fig.tight_layout();fig.savefig(destination/'05_nonlinear_convergence.png',dpi=170);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,6));n=data['refinement_n']
    for key,label in (('u_l2','Horizontal velocity'),('w_l2','Vertical velocity'),('p_l2','Pressure')):ax.loglog(n,data['refinement_'+key],marker='o',label=label)
    ax.loglog(n,data['refinement_p_l2'][0]*(n[0]/n)**2,linestyle='--',label='Second-order reference slope')
    ax.set(xlabel='Vertical cells (horizontal = 2x)',ylabel='RMS error in fixed analytical SI control',title='Atlas R4.3 | Independent variable-viscosity continuum refinement')
    ax.legend();ax.grid(True,alpha=.25);fig.tight_layout();fig.savefig(destination/'06_spatial_convergence.png',dpi=170);plt.close(fig)
    x=data['coupled_x_m'];z=data['coupled_z_m']
    fig,ax=plt.subplots(figsize=(9,8));im=ax.pcolormesh(x,z,data['evolved_temperature_k']-data['initial_temperature_k'],shading='nearest')
    fig.colorbar(im,ax=ax,label='Evolved minus authored initial temperature (K)')
    finish(fig,ax,'07_coupled_temperature_change.png','Atlas R4.3 | Actual short coupled thermal change')
    fig,ax=plt.subplots(figsize=(9,8));im=ax.pcolormesh(x,z,data['evolved_composition'],shading='nearest',vmin=0,vmax=1)
    fig.colorbar(im,ax=ax,label='Evolved constituent volume fraction')
    eu=.5*(data['endpoint_u_m_s'][:,1:]+data['endpoint_u_m_s'][:,:-1]);ew=.5*(data['endpoint_w_m_s'][1:]+data['endpoint_w_m_s'][:-1])
    ax.quiver(x[::2],z[::2],eu[::2,::2],ew[::2,::2],angles='xy')
    finish(fig,ax,'08_coupled_composition_flow.png','Atlas R4.3 | Evolved composition and re-solved endpoint flow')
    np.savez_compressed(destination/'actual_data.npz',**data)
    after=source_inventory(ROOT)
    if before!=after:raise ValueError('source changed during R4.3 rendering')
    record=dict(schema='atlas.r4-3-visual-qa.v1',status='RENDERED_AWAITING_VISUAL_REVIEW',R4_status='IN_PROGRESS',R4_complete=False,
        source_sha256_before=before,source_sha256_after=after,source_unchanged=True,provenance=provenance,continuum_refinement=refs,
        user_visual_review_completed=False,physical_validation=False,
        data_hashes={k:hashlib.sha256(v.tobytes()).hexdigest() for k,v in data.items()},
        outputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.iterdir())})
    (destination/'visual_manifest.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n');return record


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);dest=p.parse_args(argv).output.absolute()
    if any(x.is_symlink() for x in (dest,*dest.parents)):raise ValueError('linked output refused')
    if dest.exists():raise FileExistsError('use a new R4.3 visual output directory')
    dest.parent.mkdir(parents=True,exist_ok=True);claim=dest.with_name(dest.name+'.preparing')
    fd=os.open(claim,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd);stage=None
    try:
        stage=Path(tempfile.mkdtemp(prefix='.atlas-r4-3-',dir=dest.parent));r=render(stage)
        if dest.exists():raise FileExistsError('destination appeared during rendering')
        stage.rename(dest)
        print(json.dumps(dict(status=r['status'],outputs=list(r['outputs']),R4_status='IN_PROGRESS',source_unchanged=True)))
    finally:
        if stage is not None and stage.exists():shutil.rmtree(stage)
        claim.unlink(missing_ok=True)
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,ImportError) as exc:
        print(json.dumps(dict(status='BLOCKED_R4_3_VISUAL_QA',error=str(exc))),file=sys.stderr);raise SystemExit(2)
