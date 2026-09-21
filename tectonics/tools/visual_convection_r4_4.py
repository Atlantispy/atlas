#!/usr/bin/env python3
"""Render actual closed-run R4.4 fields; no synthetic or smoothed evidence.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools')]
import numpy as np
import atlas_tectonics as atlas
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore,StoreLimits
import analyse_convection_r4_4 as audit
from run_convection_r4_4 import atomic_new,digest,safe_path,source_record


def render(run,output):
    safe_path(output)
    config,records,samples,steps,states,head=audit.read_run(run)
    output.mkdir(parents=False,exist_ok=False)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    budget=WorkBudget(512<<20)
    limits=StoreLimits(chunk_bytes=65536,max_store_bytes=2<<30,max_array_bytes=32<<20)
    with ArrayStore(run/'states.sqlite',limits,budget=budget) as store:
        state=atlas.load_thermochemical_state(store,records[-1]['state_id'],budget=budget)
    with atlas.PreparedVariableStokes2D(state.problem.box,state.problem.scales,
            policy=atlas.NonlinearStokesPolicy(**config['nonlinear_policy']),
            adaptive_inner_policy=None if 'adaptive_inner_policy' not in config else atlas.AdaptiveInnerPolicy(**config['adaptive_inner_policy']),
            anderson_policy=None if 'anderson_policy' not in config else atlas.AndersonPolicy(**config['anderson_policy']),
            preconditioner_reuse_policy=None if 'preconditioner_reuse_policy' not in config else atlas.PreconditionerReusePolicy(**config['preconditioner_reuse_policy']),budget=budget) as mechanics:
        flow=atlas.tosi_endpoint_flow(state,mechanics,budget=budget)
        diagnostic=atlas.tosi_state_diagnostics(state,flow,budget=budget)
    arrays={key:flow.array(key) for key in ('u_m_s','w_m_s','pressure_pa','viscosity_cell_pa_s','viscosity_vertex_pa_s')}
    arrays['temperature']=state.array('temperature_k')-1
    arrays['composition']=state.array('composition')
    arrays['sample_times']=np.array([s['time'] for s in samples])
    for key in audit._METRICS:arrays['history_'+key]=np.array([s['diagnostics'][key] for s in samples])
    np.savez_compressed(output/'raw_fields_and_history.npz',**arrays)
    case_label=config['case']['name']
    if config['case']['yield_stress'] is not None:case_label+=f" (yield = {config['case']['yield_stress']:.1f})"
    title=f"{case_label}, {config['cells']} × {config['cells']}, t = {state.time_s:.6g}"
    def finish(fig,name):
        fig.tight_layout();fig.savefig(output/name,dpi=160);plt.close(fig)
    def image(field,label,name):
        fig,ax=plt.subplots(figsize=(7,6))
        im=ax.imshow(field,origin='lower',extent=(0,1,0,1),interpolation='nearest')
        ax.set(xlabel='x / box width',ylabel='z / box height',title=title+'\n'+label+'\nExploratory output — not benchmark acceptance')
        fig.colorbar(im,ax=ax,label=label);finish(fig,name)
    image(arrays['temperature'],'Dimensionless temperature','01_temperature.png')
    image(np.log10(arrays['viscosity_cell_pa_s']),'log10 dimensionless cell viscosity','02_viscosity.png')
    image(arrays['pressure_pa'],'Dimensionless dynamic pressure','03_pressure.png')
    n=config['cells'];x=(np.arange(n)+.5)/n
    u=.5*(arrays['u_m_s'][:,:-1]+arrays['u_m_s'][:,1:])
    w=.5*(arrays['w_m_s'][:-1]+arrays['w_m_s'][1:])
    stride=max(1,(n+31)//32)
    fig,ax=plt.subplots(figsize=(7,6))
    ax.quiver(x[::stride],x[::stride],u[::stride,::stride],w[::stride,::stride])
    ax.set(xlim=(0,1),ylim=(0,1),aspect='equal',xlabel='x / box width',ylabel='z / box height',
        title=title+'\nSimultaneous endpoint velocity (dimensionless)\n'+
            f"RMS speed = {diagnostic['diagnostics']['velocity_rms']:.6g}; arrows use a within-plot scale")
    finish(fig,'04_velocity.png')
    fig,ax=plt.subplots(figsize=(9,5))
    for name in ('Nu_top','Nu_bottom'):
        ax.plot(arrays['sample_times'],arrays['history_'+name],label=name)
    ax.set(xlabel='Dimensionless time',ylabel='Instantaneous Nusselt number',
        title=title+'\nSaved sampled wall heat flux — not an interval heat ledger')
    ax.legend();finish(fig,'05_heat_flux_history.png')
    fig,ax=plt.subplots(figsize=(9,5))
    ax.plot(arrays['sample_times'],arrays['history_temperature_mean'])
    ax.set(xlabel='Dimensionless time',ylabel='Mean dimensionless temperature',
        title=title+'\nActual saved diagnostic history')
    finish(fig,'06_temperature_history.png')
    metadata=dict(schema='atlas.convection-visual-r4-4.v1',source=source_record(),receipt_head=head,
        renderer_sha256=digest(Path(__file__).read_bytes()),configuration=config,diagnostic=diagnostic,
        state_id=state.state_id,flow_id=flow.result_id,time=state.time_s,step=state.step_index,
        units='All plotted quantities dimensionless; stored SI-named flow arrays equal unit-box nondimensional values in this numerical embedding',
        sampling=dict(images='one pixel per original cell, nearest display, no interpolation/smoothing',
            arrows=f'centred face averages at every {stride} cell, linear arrow lengths, no unit-vector normalisation; automatic within-plot vector scale, not a common scale across figures',
            viscosity='cell support only; exact-wall diagnostic extrema are reported separately'),
        assistant_visual_inspection='NOT_RECORDED_BY_RENDERER',user_visual_approval='NOT_RECORDED',
        full_benchmark_accepted=False,budget_after_close=budget.statistics(),
        files={p.name:digest(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file()})
    atomic_new(output/'metadata.json',metadata)
    return metadata


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();result=render(args.run.absolute(),args.output.absolute())
    print(json.dumps({'output':str(args.output),'state_id':result['state_id'],'full_benchmark_accepted':False}))


if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,TypeError,OSError,atlas.TectonicsError) as exc:
        print(json.dumps({'status':'REFUSED','error':str(exc)}),file=sys.stderr);raise SystemExit(2)
