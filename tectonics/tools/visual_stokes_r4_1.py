#!/usr/bin/env python3
"""Render real R4.1 constant-viscosity mechanical output; R4 remains in progress.

SPDX-License-Identifier: AGPL-3.0-only
The temperature anomaly is AUTHORED and stationary, not a thermal simulation.
The velocity and dynamic pressure are actually solved using the new Stokes API.
Cell-centred velocity averages are display interpolation only; raw staggered
fields, actual divergence and all forcing/provenance are retained in output.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from dataclasses import asdict
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'src'))
from atlas_tectonics import (StokesBox2D,DiffusiveScales,PreparedStokes2D,reference_rheology,
                            BoussinesqMaterial,boussinesq_response,face_force_from_density)
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.timebase import JULIAN_YEAR


def build_snapshot(n=64):
    budget=WorkBudget(128<<20)
    b=StokesBox2D(n,n,3e6,3e6,'authored-box-x-right-z-up')
    scales=DiffusiveScales('authored-3000km-SI',3e6,1e-6,1e21,1000.,100.,3e6)
    x,z=b.axes();xx,zz=np.meshgrid(x,z)
    a=100.;kx=np.pi/b.width_m;kz=np.pi/b.height_m
    temperature=1000.+a*np.sin(kx*xx)*np.sin(kz*zz)
    gradient=np.stack((a*kx*np.cos(kx*xx)*np.sin(kz*zz),a*kz*np.sin(kx*xx)*np.cos(kz*zz)),axis=-1)
    material=BoussinesqMaterial('authored-buoyancy-box','Illustrative SI mechanics test; not calibrated Earth',
        3300.,1250.,3.,3e-5,1000.,0.,0.,(1000.,1200.))
    local=boussinesq_response(material,temperature,0.,[0.,-9.81],gradient,budget=budget)
    forces=face_force_from_density(b,local['density_anomaly_kg_m3'],[0.,-9.81],budget=budget)
    with PreparedStokes2D(b,reference_rheology('constant'),scales,budget=budget) as p:
        result=p.solve(*forces,frame_id=b.frame_id,epoch_id='authored-static-mechanical-example',time_s=0.,
            source='R3 Boussinesq anomaly from T=1000+100 sin(pi*x/Lx)sin(pi*z/Lz); arithmetic cell-to-face force; gravity=(0,-9.81) m/s^2')
    data={k:result.array(k) for k in result.array_names}
    data.update(x_m=x,z_m=z,authored_temperature_k=temperature,density_anomaly_kg_m3=local['density_anomaly_kg_m3'])
    provenance={'solution_id':result.result_id,'solution':result.descriptor(),'material':asdict(material),
                'temperature_origin':'AUTHORED sinusoidal static anomaly; NOT thermally evolved',
                'kinematics_origin':'SOLVED constant-viscosity mechanical response; NOT prescribed velocities',
                'display_interpolation':'arithmetic face-to-centre velocity averages for arrows/speed only',
                'julian_year_s':JULIAN_YEAR.seconds_per_unit,'budget':budget.statistics()}
    return data,provenance


def render(destination):
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
    from verify import source_inventory
    from stokes_fixtures import unit_box,unit_scales,request,analytic,errors
    before=source_inventory(ROOT)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    data,provenance=build_snapshot()
    x=data['x_m']/1000;z=data['z_m']/1000
    uc=.5*(data['u_m_s'][:,1:]+data['u_m_s'][:,:-1])
    wc=.5*(data['w_m_s'][1:]+data['w_m_s'][:-1])
    speed=np.hypot(uc,wc)*100*JULIAN_YEAR.seconds_per_unit
    note='R4 IN PROGRESS | Steady free-slip 2D box, viscosity 10^21 Pa s | Authored buoyancy; no temperature evolution'
    def finish(fig,ax,name,title):
        ax.set_xlabel('Horizontal distance (km)');ax.set_ylabel('Height above bottom (km)')
        ax.set_title(title,pad=15);ax.set_aspect('equal');fig.text(.5,.022,note,ha='center',fontsize=8)
        fig.tight_layout(rect=(0,.045,1,1));fig.savefig(destination/name,dpi=175);plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,8))
    im=ax.pcolormesh(x,z,speed,shading='nearest');fig.colorbar(im,ax=ax,label='Display-centred speed (cm per Julian year)')
    step=4
    ax.quiver(x[::step],z[::step],uc[::step,::step],wc[::step,::step],angles='xy')
    finish(fig,ax,'01_solved_velocity.png','Atlas R4.1 | Solved instantaneous velocity')
    fig,ax=plt.subplots(figsize=(9,8))
    im=ax.pcolormesh(x,z,data['pressure_pa']/1e6,shading='nearest');fig.colorbar(im,ax=ax,label='Dynamic pressure (MPa), zero domain mean')
    finish(fig,ax,'02_dynamic_pressure.png','Atlas R4.1 | Solved pressure, not absolute lithostatic pressure')
    fig,ax=plt.subplots(figsize=(9,8))
    im=ax.pcolormesh(x,z,data['divergence_s_1'],shading='nearest');fig.colorbar(im,ax=ax,label='Actual staggered divergence (s^-1)')
    finish(fig,ax,'03_divergence_residual.png','Atlas R4.1 | Continuity residual (round-off, not physical compression)')
    fig,ax=plt.subplots(figsize=(9,8))
    im=ax.pcolormesh(x,z,data['authored_temperature_k'],shading='nearest');fig.colorbar(im,ax=ax,label='Authored input temperature (K)')
    finish(fig,ax,'04_authored_forcing_temperature.png','Atlas R4.1 | Input used to construct buoyancy — NOT an evolved field')
    refinements=[]
    for n in (8,16,32,64):
        b=unit_box(n);a=analytic(b)
        with PreparedStokes2D(b,reference_rheology('constant'),unit_scales()) as p:
            r=p.solve(*a[:2],**request(b))
        refinements.append({'n':n,**errors(r,a),'result_id':r.result_id})
    grid=np.asarray([r['n'] for r in refinements]);data['refinement_grid']=grid
    fig,ax=plt.subplots(figsize=(10,6))
    for key,label in (('u_l2','Horizontal velocity'),('w_l2','Vertical velocity'),('p_l2','Pressure')):
        values=np.asarray([r[key] for r in refinements]);data['refinement_'+key]=values
        ax.loglog(grid,values,marker='o',label=label)
    ax.loglog(grid,data['refinement_p_l2'][0]*(grid[0]/grid)**2,linestyle='--',label='Second-order reference slope')
    ax.set_xlabel('Cells per axis');ax.set_ylabel('RMS error in unit-scaled manufactured case')
    ax.set_title('Atlas R4.1 | Independent continuous-solution refinement')
    ax.legend();ax.grid(True,alpha=.25)
    fig.text(.5,.025,'Fixed analytic forcing and exact continuum fields | This verifies a mechanical component, not the full R4 stage',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.05,1,1));fig.savefig(destination/'05_mechanical_convergence.png',dpi=175);plt.close(fig)
    np.savez_compressed(destination/'actual_data.npz',**data)
    after=source_inventory(ROOT)
    if before!=after:raise ValueError('source changed during R4.1 rendering')
    record={'schema':'atlas.r4-1-visual-qa.v1','status':'RENDERED_AWAITING_VISUAL_REVIEW',
        'R4_status':'IN_PROGRESS','R4_complete':False,'source_sha256_before':before,'source_sha256_after':after,
        'source_unchanged':True,'provenance':provenance,'continuum_refinement':refinements,
        'human_visual_review_completed':False,'physical_validation':False,
        'data_hashes':{k:hashlib.sha256(v.tobytes()).hexdigest() for k,v in data.items()},
        'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.iterdir())}}
    (destination/'visual_manifest.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n')
    return record


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    destination=parser.parse_args(argv).output.absolute()
    if any(p.is_symlink() for p in (destination,*destination.parents)):raise ValueError('linked output destinations refused')
    if destination.exists():raise FileExistsError('use a new R4.1 visual output directory')
    destination.parent.mkdir(parents=True,exist_ok=True)
    claim=destination.with_name(destination.name+'.preparing')
    fd=os.open(claim,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    stage=None
    try:
        stage=Path(tempfile.mkdtemp(prefix='.atlas-r4-visual-',dir=destination.parent))
        r=render(stage)
        if destination.exists():raise FileExistsError('output appeared during rendering')
        stage.rename(destination)
        print(json.dumps({'status':r['status'],'outputs':list(r['outputs']),'R4_status':'IN_PROGRESS','source_unchanged':True}))
    finally:
        if stage is not None and stage.exists():shutil.rmtree(stage)
        claim.unlink(missing_ok=True)
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,ImportError) as e:
        print(json.dumps({'status':'BLOCKED_R4_1_VISUAL_QA','error':str(e)}),file=sys.stderr);raise SystemExit(2)
