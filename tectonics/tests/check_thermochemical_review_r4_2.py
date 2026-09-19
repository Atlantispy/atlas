#!/usr/bin/env python3
"""Finite corrective-review probes and paired same-work performance observations.

SPDX-License-Identifier: AGPL-3.0-only
--root explicitly selects either the delivered baseline or corrected checkout.
No installation, source acquisition, model change or general benchmark programme.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys, json, hashlib, time, math, platform
from dataclasses import replace
from decimal import Decimal, localcontext


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--save-state',type=Path)
    parser.add_argument('--load-state',type=Path)
    a=parser.parse_args();root=a.root.resolve()
    sys.dont_write_bytecode=True;sys.path[:0]=[str(root),str(root/'src'),str(root/'tests')]
    import numpy as np
    from verify import source_inventory
    from atlas_tectonics import (PreparedThermochemical2D,ThermochemicalState,ThermalBoundary2D,
        save_thermochemical_state,load_thermochemical_state,TectonicsError)
    from atlas_tectonics.thermochemical import _Diffusion2D,_weighted_source
    from atlas_tectonics.storage import ArrayStore,StoreLimits
    from atlas_tectonics.resources import WorkBudget
    from thermochemical_fixtures import problem,initial,rest,circulation
    before=source_inventory(root)
    def hashes(state):
        return {k:hashlib.sha256(state.array(k).tobytes()).hexdigest() for k in ('temperature_k','composition')}
    offset=[]
    T=np.array([[300.,302.],[304.,306.]])
    for ref in (300.,1e12,1e15,1e16):
        p=problem(2,fixed=False,gravity=(0.,0.))
        p=replace(p,material=replace(p.material,expansion_per_k=0.,reference_temperature_k=ref))
        d=_Diffusion2D(p);temperature,_=d.advance(T,d.transform(np.zeros_like(T)),1e-12,None)
        row=dict(reference_temperature_k=ref,diffusion_temperature_k=temperature.tolist(),
                 diffusion_max_departure_from_initial_k=float(abs(temperature-T).max()))
        try:
            with PreparedThermochemical2D(p) as plan:
                r=plan.advance(initial(p,T=T,C=.25),1e-12,source='offset conditioning probe',velocity=rest(p))
            row.update(complete_step_accepted=True,temperature_k=r.state.array('temperature_k').tolist())
        except TectonicsError as exc:row.update(complete_step_accepted=False,error=str(exc))
        offset.append(row)
    sources=[]
    for mode,weight,dt in ((1e200,.5,3*float(np.nextafter(0.,1.))),(1e200,1e-200,1e-120)):
        with localcontext() as c:
            c.prec=100;want=float(Decimal.from_float(mode)*Decimal.from_float(weight)*Decimal.from_float(dt))
        got=float(_weighted_source(np.array([[mode]]),np.array([[weight]]),dt)[0,0])
        sources.append(dict(mode=mode,weight=weight,dt=dt,independent_decimal=want,actual=got,relative_error=abs(got/want-1)))
    p=problem(2,fixed=False);base=initial(p,T=300.,C=.25)
    s=ThermochemicalState(p,base.array('temperature_k'),base.array('composition'),time_s=1e16,source='large named epoch')
    clock=[]
    for dt in (3.,4.):
        row=dict(input_time_s=s.time_s,dt_s=dt)
        try:
            with PreparedThermochemical2D(p) as plan:r=plan.advance(s,dt,source='clock probe',velocity=rest(p),extra_heating_w_m3=.125)
            row.update(accepted=True,represented_duration_s=r.state.time_s-s.time_s,
                       temperature_increment_k=(r.state.array('temperature_k')-300.).tolist())
        except TectonicsError as exc:row.update(accepted=False,error=str(exc))
        clock.append(row)
    timings=[]
    for n,fixed,coupled in ((64,True,False),(256,True,False),(64,False,False),(256,False,False),(128,True,True)):
        p=problem(n,fixed=fixed);s=initial(p);velocity=None if coupled else circulation(p)
        budget=WorkBudget(512<<20);t=time.perf_counter()
        with PreparedThermochemical2D(p,budget=budget) as plan:
            setup=time.perf_counter()-t;calls=[]
            for _ in range(6):
                t=time.perf_counter();r=plan.advance(s,1e-4,source='paired R4.2 review comparison',velocity=velocity);calls.append(time.perf_counter()-t)
            arrays={k:r.state.array(k).tolist() if n==64 else None for k in ('temperature_k','composition')}
            final_hashes=hashes(r.state)
        if budget.reserved_bytes:raise ValueError('final resource reservations were not released')
        timings.append(dict(n=n,fixed_walls=fixed,coupled=coupled,setup_s=setup,first_call_s=calls[0],
            complete_reused_calls_s=calls[1:],median_complete_s=float(np.median(calls[1:])),
            field_hashes=final_hashes,field_arrays_64=arrays,budget=budget.statistics()))
    snapshot=None
    if a.save_state is not None:
        if a.save_state.exists():raise FileExistsError('snapshot destination already exists')
        p=problem(4);s=initial(p)
        with PreparedThermochemical2D(p) as plan:state=plan.advance(s,.02,source='original dev28 genuine state',velocity=rest(p)).state
        with ArrayStore(a.save_state,StoreLimits(4096,16<<20,64<<20)) as store:save_thermochemical_state(state,store)
        snapshot=dict(state_id=state.state_id,metadata=state.descriptor(),field_sha256=hashes(state))
        a.save_state.with_suffix('.json').write_text(json.dumps(snapshot,indent=2)+'\n')
    if a.load_state is not None:
        expected=json.loads(a.load_state.with_suffix('.json').read_text())
        with ArrayStore(a.load_state,StoreLimits(4096,16<<20,64<<20)) as store:state=load_thermochemical_state(store,expected['state_id'])
        snapshot=dict(state_id_exact=state.state_id==expected['state_id'],metadata_exact=state.descriptor()==expected['metadata'],arrays_exact=hashes(state)==expected['field_sha256'])
        try:
            with PreparedThermochemical2D(state.problem) as plan:plan.advance(state,.02,source='do not rebind',velocity=rest(state.problem))
        except TectonicsError:snapshot['changed_source_continuation_refused']=True
        else:snapshot['changed_source_continuation_refused']=False
    after=source_inventory(root)
    if after!=before:raise ValueError('source changed during observation')
    result=dict(schema='atlas.r4-2-review-observation.v1',runtime=dict(python=platform.python_version(),numpy=np.__version__,scipy=__import__('scipy').__version__,numba=__import__('numba').__version__,platform=platform.system()),
        source_sha256_before=before,source_sha256_after=after,source_unchanged=True,
        observer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),offset_probes=offset,
        weighted_source_probes=sources,clock_probes=clock,complete_step_timings=timings,snapshot=snapshot,
        scope='Same host and equations; short registered comparisons, not isolated cold-process/planetary forecasts. Extreme probes are arithmetic controls, not realistic mantle scenarios.',
        physical_validation=False,R4_complete=False,R4_3_started=False,Windows_tested=False)
    print(json.dumps(result,indent=2,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
