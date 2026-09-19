#!/usr/bin/env python3
"""Render actual R3 response curves and their numerical data; no new physics.

SPDX-License-Identifier: AGPL-3.0-only
Five separate figures: benchmark viscosity, strain weakening, healing history,
fixed-length filter refinement and local Boussinesq buoyancy. No Earth relief,
plate evolution, simulated strain localisation or invented diagram is presented.
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

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'src'))
from atlas_tectonics import (reference_rheology,PreparedRheology,DamageLengthScale,
    PreparedDamageRegularisation,BoussinesqMaterial,boussinesq_response)
from atlas_tectonics.resources import WorkBudget


def data_curves():
    """All plotted physical arrays come from the retained R3 API."""
    budget=WorkBudget(128<<20);data={};ids={}
    T=np.linspace(0,1,241);data['temperature_axis']=T
    for name in ('tosi-1','tosi-2','tosi-3','tosi-4','tosi-5a'):
        with PreparedRheology(reference_rheology(name),budget=budget) as plan:
            r=plan.evaluate(T,.5,1)
        data[name+'_viscosity']=r.array('viscosity');ids[name]=r.result_id
    rate=np.logspace(-3,9,241);data['strain_rate_axis']=rate
    with PreparedRheology(reference_rheology('bf23-memory'),budget=budget) as p:
        for damage in (0,5,10):
            r=p.evaluate(0,.1,rate,damage)
            data[f'damage_{damage}_stress']=r.array('stress_ii');ids[f'stress_{damage}']=r.result_id
        times=np.linspace(0,15,121);data['elapsed_axis']=times
        # Evaluate separate constant-coefficient intervals from the same initial
        # state. These are exact material-point responses, not time-discretised
        # temperature evolution. Curves deliberately cross dcrit=10.
        for T0 in (0.,.025,.05):
            vals=[];records=[]
            for elapsed in times:
                r=p.advance(20,0,T0,float(elapsed));vals.append(float(r.array('damage_after')));records.append(r.result_id)
            key=f'healing_T_{T0:g}';data[key]=np.asarray(vals);ids[key]=records
    # A prescribed smooth field tests a fixed physical length, not a shear band.
    exact_x=np.linspace(0,1000,401);data['length_exact_x_km']=exact_x
    data['length_exact_damage']=2+np.cos(2*np.pi*exact_x/1000)/(1+(.1*2*np.pi)**2)
    for n in (24,48,96):
        x=(np.arange(n)+.5)/n
        params=DamageLengthScale('authored-100km-response',1e6,1e5,n,'Atlas analytical visual test; not geologically calibrated')
        with PreparedDamageRegularisation(params,budget=budget) as p:
            data[f'length_{n}_x_km']=1000*x
            data[f'length_{n}_damage']=p.apply(2+np.cos(2*np.pi*x));ids[f'length_{n}']=p.identity
    data['buoyancy_temperature_k']=np.linspace(300,1500,121)
    material=BoussinesqMaterial('authored-buoyancy-test','Analytical SI example, not calibrated mantle',
        3000,1000,3,1e-5,1000,-100,0,(300,1500))
    for C in (0,.5,1):
        r=boussinesq_response(material,data['buoyancy_temperature_k'],C,[0,-10],[0,0],budget=budget)
        data[f'buoyancy_C_{C:g}']=r['body_force_n_m3'][:,1]
    return data,ids,budget.statistics()


def render(destination):
    sys.path.insert(0,str(ROOT))
    from verify import source_inventory
    before=source_inventory(ROOT)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    data,ids,budget=data_curves()
    def finish(fig,ax,name,xlabel,ylabel,title,note):
        ax.set_xlabel(xlabel);ax.set_ylabel(ylabel);ax.set_title(title,pad=14)
        ax.grid(True,alpha=.22);ax.legend(fontsize=9)
        fig.text(.5,.025,note,ha='center',fontsize=9)
        fig.tight_layout(rect=(0,.06,1,1))
        fig.savefig(destination/name,dpi=180);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,6))
    for name in ('tosi-1','tosi-2','tosi-3','tosi-4','tosi-5a'):
        ax.semilogy(data['temperature_axis'],data[name+'_viscosity'],label=name)
    finish(fig,ax,'01_viscosity_temperature.png','Dimensionless temperature T','Dimensionless viscosity',
           'Atlas R3 | Temperature-dependent viscosity',
           'Actual local-law outputs | depth = 0.5, strain-rate II = 1 | Tosi et al. 2015, eqs 6–10; no convection run')
    fig,ax=plt.subplots(figsize=(10,6))
    for d in (0,5,10):ax.loglog(data['strain_rate_axis'],data[f'damage_{d}_stress'],label=f'Stored damage d = {d}')
    finish(fig,ax,'02_yield_weakening.png','Dimensionless strain-rate second invariant','Dimensionless stress second invariant',
           'Atlas R3 | Yielding with retained damage',
           'Actual BF2023 local-law subset | T = 0, depth = 0.1 | No asthenosphere masks or hidden viscosity floor')
    fig,ax=plt.subplots(figsize=(10,6))
    for T in (0.,.025,.05):ax.plot(data['elapsed_axis'],data[f'healing_T_{T:g}'],label=f'Fixed T = {T:g}')
    ax.axhline(dict(reference_rheology('bf23-memory').parameters)['dcrit'],linestyle='--',label='Strength saturation threshold (not a history cap)')
    finish(fig,ax,'03_memory_healing.png','Dimensionless elapsed time','Stored strain-like damage d',
           'Atlas R3 | Healing without erasing prior damage',
           'Actual constant-temperature, zero-strain-rate material-point intervals | Initial d = 20 | Not thermal evolution')
    fig,ax=plt.subplots(figsize=(10,6))
    for n in (24,48,96):ax.plot(data[f'length_{n}_x_km'],data[f'length_{n}_damage'],marker='.',label=f'{n} finite-volume cells')
    ax.plot(data['length_exact_x_km'],data['length_exact_damage'],linestyle='--',label='Independent continuum cosine solution')
    finish(fig,ax,'04_fixed_length_refinement.png','Distance (km)','Filtered damage',
           'Atlas R3 | One physical length across mesh refinement',
           'Atlas-defined 1D no-flux operator | length scale = 100 km (authored test) | Not a coupled localisation result')
    fig,ax=plt.subplots(figsize=(10,6))
    for C in (0,.5,1):ax.plot(data['buoyancy_temperature_k'],data[f'buoyancy_C_{C:g}'],label=f'Composition fraction C = {C:g}')
    finish(fig,ax,'05_buoyancy_sign.png','Temperature (K)','Upward body force per volume (N/m³)',
           'Atlas R3 | Explicit thermal and compositional buoyancy',
           'Authored constant-property SI example | gravity points down | Body force only; no slab-pull traction added')
    np.savez_compressed(destination/'curve_data.npz',**data)
    after=source_inventory(ROOT)
    if after!=before:raise ValueError('source changed during R3 rendering')
    record={'schema':'atlas.r3-visual-qa.v1','status':'RENDERED_AWAITING_VISUAL_REVIEW',
        'source_sha256_before':before,'source_sha256_after':after,'source_unchanged':True,
        'record_ids':ids,'data_hashes':{k:hashlib.sha256(v.tobytes()).hexdigest() for k,v in data.items()},
        'scope':'Actual local constitutive curves and 1D length filter; no geological/solver/plate validation',
        'provenance':'Tosi2015 doi:10.1002/2015GC005807; Becker-Fuchs2023 doi:10.1029/2023GC011179; two explicitly authored analytical examples',
        'human_visual_review_completed':False,'budget':budget,
        'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(destination.iterdir())}}
    (destination/'visual_manifest.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n')
    return record


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    destination=parser.parse_args(argv).output.absolute()
    if any(p.is_symlink() for p in (destination,*destination.parents)):raise ValueError('linked output destinations refused')
    if destination.exists():raise FileExistsError('use a new R3 visual output directory')
    destination.parent.mkdir(parents=True,exist_ok=True)
    claim=destination.with_name(destination.name+'.preparing')
    fd=os.open(claim,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    stage=None
    try:
        stage=Path(tempfile.mkdtemp(prefix='.atlas-r3-visual-',dir=destination.parent))
        record=render(stage)
        if destination.exists():raise FileExistsError('output appeared during rendering')
        stage.rename(destination)
        print(json.dumps({'status':record['status'],'outputs':list(record['outputs']),'source_unchanged':True}))
    finally:
        if stage is not None and stage.exists():shutil.rmtree(stage)
        claim.unlink(missing_ok=True)
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ImportError,OSError,ValueError) as exc:
        print(json.dumps({'status':'BLOCKED_R3_VISUAL_QA','error':str(exc)}),file=sys.stderr);raise SystemExit(2)
