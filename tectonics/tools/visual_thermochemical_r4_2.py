#!/usr/bin/env python3
"""Render actual R4.2 time evolution. No image generation, new physics or network.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,sys,tempfile
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools'),str(ROOT)]
from thermochemical_example import evolve_example
from atlas_tectonics.timebase import JULIAN_MEGAYEAR,JULIAN_YEAR


def render(destination):
    from verify import source_inventory
    before=source_inventory(ROOT)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    data,provenance=evolve_example()
    p=provenance['problem'];b=p['box'];n=b['nx'];m=b['nz']
    xe=np.linspace(0,b['width_m']/1000,n+1);ze=np.linspace(0,b['height_m']/1000,m+1)
    xm=.5*(xe[:-1]+xe[1:]);zm=.5*(ze[:-1]+ze[1:])
    age=provenance['final_time_s']/JULIAN_MEGAYEAR.seconds_per_unit
    note='R4 IN PROGRESS | 2D constant-property Boussinesq example | Authored start, solved evolution; not calibrated Earth'
    def finish(fig,ax,name,title):
        ax.set(xlabel='Horizontal distance (km)',ylabel='Height above bottom (km)',title=title,aspect='equal')
        fig.text(.5,.025,note,ha='center',fontsize=8);fig.tight_layout(rect=(0,.05,1,1))
        fig.savefig(destination/name,dpi=180);plt.close(fig)
    fields=[('initial_temperature_k','01_initial_temperature.png','Authored initial temperature','Temperature (K)',300.,1600.),
            ('final_temperature_k','02_evolved_temperature.png',f'Evolved temperature at {age:.3f} million Julian years','Temperature (K)',300.,1600.),
            ('initial_composition','03_initial_composition.png','Authored initial constituent fraction','Constituent bulk volume fraction',0.,1.),
            ('final_composition','04_evolved_composition.png',f'Constituent fraction after {provenance["steps"]} conservative steps','Constituent bulk volume fraction',0.,1.)]
    for key,file,title,label,lo,hi in fields:
        fig,ax=plt.subplots(figsize=(9,8));im=ax.pcolormesh(xe,ze,data[key],vmin=lo,vmax=hi,shading='flat')
        fig.colorbar(im,ax=ax,label=label);finish(fig,ax,file,'Atlas R4.2 | '+title)
    delta=data['temperature_change_k'];scale=float(abs(delta).max())
    fig,ax=plt.subplots(figsize=(9,8));im=ax.pcolormesh(xe,ze,delta,vmin=-scale,vmax=scale,shading='flat')
    fig.colorbar(im,ax=ax,label='Final minus initial temperature (K)')
    finish(fig,ax,'05_temperature_change.png','Atlas R4.2 | Actual temperature change, not a new input texture')
    u=.5*(data['final_u_m_s'][:,1:]+data['final_u_m_s'][:,:-1]);w=.5*(data['final_w_m_s'][1:]+data['final_w_m_s'][:-1])
    speed=np.hypot(u,w)*100*JULIAN_YEAR.seconds_per_unit
    fig,ax=plt.subplots(figsize=(9,8));im=ax.pcolormesh(xe,ze,speed,shading='flat')
    fig.colorbar(im,ax=ax,label='Display-centred speed (cm per Julian year)')
    ax.quiver(xm[::3],zm[::3],u[::3,::3],w[::3,::3],angles='xy')
    finish(fig,ax,'06_endpoint_velocity.png','Atlas R4.2 | Flow solved from the final accepted temperature/composition')
    fig,ax=plt.subplots(figsize=(10,6))
    for key,label in (('heat_relative_residual','Heat incl. signed boundary flux'),('composition_relative_residual','Constituent inventory')):
        ax.plot(np.arange(1,len(data[key])+1),data[key],label=label)
    ax.set(xlabel='Accepted time step',ylabel='Relative interval-balance residual',title='Atlas R4.2 | Independent heat and material accounting')
    ax.legend();ax.grid(True,alpha=.25)
    fig.text(.5,.02,'Numerical residuals, not physical sources or losses. Domain is closed to material, not to conductive heat.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.06,1,1));fig.savefig(destination/'07_conservation_residuals.png',dpi=180);plt.close(fig)
    np.savez_compressed(destination/'actual_data.npz',**data)
    after=source_inventory(ROOT)
    if before!=after:raise ValueError('source changed during R4.2 rendering')
    result=dict(schema='atlas.r4-2-visual-qa.v1',status='RENDERED_AWAITING_VISUAL_REVIEW',source_sha256_before=before,
        source_sha256_after=after,source_unchanged=True,provenance=provenance,
        human_visual_review_completed=False,physical_validation=False,R4_status='IN_PROGRESS',
        display_only_interpolation='Arithmetic face-to-centre average for velocity arrows/speed, not used for transport.',
        data_hashes={k:hashlib.sha256(a.tobytes()).hexdigest() for k,a in data.items()},
        outputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.iterdir())})
    (destination/'visual_manifest.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    destination=parser.parse_args(argv).output.absolute()
    if any(p.is_symlink() for p in (destination,*destination.parents)):raise ValueError('linked output destinations refused')
    if destination.exists():raise FileExistsError('use a new R4.2 visual output directory')
    destination.parent.mkdir(parents=True,exist_ok=True)
    claim=destination.with_name(destination.name+'.preparing')
    fd=os.open(claim,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd);stage=None
    try:
        stage=Path(tempfile.mkdtemp(prefix='.atlas-r4-2-visual-',dir=destination.parent));r=render(stage)
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
        print(json.dumps({'status':'BLOCKED_R4_2_VISUAL_QA','error':str(e)}),file=sys.stderr);raise SystemExit(2)
