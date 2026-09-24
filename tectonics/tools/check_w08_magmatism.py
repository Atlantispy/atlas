"""Matched bounded Step5 timings with materialised identical scientific products."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

import numpy as np

from atlas_tectonics.magmatic_transfer import MagmaticInventory, PreparedMagmaticTransfer
from atlas_tectonics.magmatic_thermodynamics import MagmaticThermodynamics, invert_enthalpy
from atlas_tectonics.magmatic_emplacement import EmplacementTarget, emplace_magma, accounting_entries
from atlas_tectonics.resources import WorkBudget


def inputs(owner):
    law=MagmaticThermodynamics(('basalt','granitoid'),[1480,1370],[400000,270000],
        melting_temperature_k=1200,reference_temperature_k=300,source_id='Calogero2020-Table1',
        provenance='Physical properties only; rates and common-Tm are declared scenarios',budget=owner)
    inventory=MagmaticInventory(('intrusion','reservoir','source'),('intrusion','reservoir','source-melt'),
        law.component_ids,[[0,0],[0,2000],[10000,0]],
        [0,2000*(1370*1000+270000),10000*(1480*(1423.15-300)+400000)],
        source_id='timing-finite-feed',enthalpy_source=law.thermodynamics_id,budget=owner)
    q=np.zeros((3,3)); q[2,1]=100; q[1,0]=100
    target=EmplacementTarget(tuple('c'+str(i) for i in range(32)),np.full(32,2/32),
        np.full(32,2900.),np.full(32,1/32),geometry_source='timing-area',
        frame_id='planar',datum_id='fixed',epoch_id='scenario',budget=owner)
    return law,inventory,q,target


def materialise(plan, duration, law, target, owner):
    result=plan.evaluate(duration)
    state=invert_enthalpy(result.remaining.component_mass_kg,result.remaining.enthalpy_j,law,budget=owner)
    payload=result.payload(0,2830.,budget=owner)
    placed=emplace_magma(payload,target,mode='underplating',source_id='timing-placement',budget=owner)
    entries=accounting_entries((placed,),budget=owner)
    # Read complete products, not just a timer around a lazily returned handle.
    h=hashlib.sha256(json.dumps(entries,sort_keys=True).encode())
    for value in (result.remaining.component_mass_kg,result.remaining.enthalpy_j,
            result.transferred_component_mass_kg,result.transferred_enthalpy_j,
            state.temperature_k,placed.incoming,placed.geometry,placed.incoming_component_mass_kg):
        h.update(np.asarray(value,dtype=float).tobytes())
    return h.hexdigest()


def timed(durations, reuse):
    started=time.perf_counter(); owner=WorkBudget(128*1024**2)
    law,inventory,q,target=inputs(owner); outputs=[]
    if reuse:
        with PreparedMagmaticTransfer(inventory,q,source_id='timing',thermodynamics=law,budget=owner) as plan:
            identity=plan.context.identity
            for duration in durations: outputs.append(materialise(plan,duration,law,target,owner))
    else:
        for duration in durations:
            with PreparedMagmaticTransfer(inventory,q,source_id='timing',thermodynamics=law,budget=owner) as plan:
                identity=plan.context.identity
                outputs.append(materialise(plan,duration,law,target,owner))
    return dict(seconds=time.perf_counter()-started,outputs=outputs,
                peak_reserved_bytes=owner.peak_reserved_bytes,execution_id=identity)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args(); root=Path(__file__).resolve().parents[1]
    fixture=root/'cases/w08_magmatism_r1.json'
    records={}
    for label,durations in (('different_outputs',[1.,2.,3.]),('identical_outputs',[3.,3.,3.])):
        rows={'fresh':[],'reused':[]}
        for repeat in range(3):
            for mode in (('fresh','reused') if repeat%2==0 else ('reused','fresh')):
                rows[mode].append(timed(durations,mode=='reused'))
        keys=[r['outputs'] for rs in rows.values() for r in rs]
        if any(k!=keys[0] for k in keys): raise ValueError('matched output identity differs')
        base=statistics.median(r['seconds'] for r in rows['fresh'])
        fast=statistics.median(r['seconds'] for r in rows['reused'])
        records[label]=dict(durations_s=durations,trials=rows,baseline_median_s=base,
            reused_median_s=fast,saved_s=base-fast,saved_percent=100*(base-fast)/base,
            identical_output_identities=True)
    sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((root/'src/atlas_tectonics').glob('*.py'))}
    report=dict(schema='atlas.w08-magmatism-timing.v1',source_status='WORKING NON-CANON',
        run_status='FINISHED',platform=platform.platform(),python=platform.python_version(),
        fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),source_sha256=sources,
        method='Three rotated repeats; complete setup, source verification, thermodynamics, placement and output materialisation',
        baseline='Fresh plan and source context for each requested output; common immutable inputs shared in both routes',
        reuse='One prepared plan and bounded latest-result/operator cache; no persistence or history cache',
        native_threads=1,max_work_bytes=128*1024**2,results=records)
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:{name:v[name] for name in ('baseline_median_s','reused_median_s','saved_s','saved_percent')}
                      for k,v in records.items()},indent=2))


if __name__=='__main__': main()
