#!/usr/bin/env python3
"""Bounded load construction: literal scalar reference versus batched kernel.

This is a new-kernel baseline, NOT an old Atlas/whole-generator speed claim.
Both routes use identical prevalidated immutable snapshots. Construction is
reported separately; no disk hits, workers, relaxed physics or tolerance tuning.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import numpy as np
from atlas_tectonics import LoadSupport, LoadPhase, ColumnLoadState, column_load_change
from atlas_tectonics.constitutive import BoussinesqMaterial
from atlas_tectonics.resources import WorkBudget


def fixture(n):
    i = np.arange(n, dtype=np.float64)
    area = 10000.+i%17
    support = LoadSupport(tuple('c'+str(j) for j in range(n)), area, np.full(n,2000.),
        geometry_source='synthetic-timing-footprints',frame_id='synthetic-planar',datum_id='fixed-bottom')
    thermal = BoussinesqMaterial('synthetic','benchmark only',3300.,1000.,3.,3e-5,1300.,0.,0.,(300.,1500.))
    phases = tuple(LoadPhase('p'+str(j),'sediment-grain',2600.+30*j,'synthetic') for j in range(6)) + (
        LoadPhase('water','pore-water',1025.,'synthetic'),
        LoadPhase('plate','rock',3300.,'synthetic',thermal,'same-fixed-rock-coverage'))
    volume = area[:,None]*(20.+np.arange(8)[None,:]+(i%13)[:,None])
    new = volume.copy()
    new[:,:7] += area[:,None]*((i%11)[:,None]-5)*.0625
    fill = np.full(n,1025.); new_fill = fill+(i%5 == 0)*5.
    temp = (1200.+i%7)[:,None]
    reference = ColumnLoadState(support,phases,volume,fill,source_id='synthetic-before',epoch_id='t0',temperature_k=temp)
    current = ColumnLoadState(support,phases,new,new_fill,source_id='synthetic-after',epoch_id='t1',temperature_k=temp-60.)
    return reference,current


def scalar_reference(reference,current,g):
    """Independent per-column finite-volume equations with math.fsum."""
    rv,cv = reference.volume_m3,current.volume_m3
    rf,cf = reference.fill_density_kg_m3,current.fill_density_kg_m3
    rt,ct = reference.temperature_k,current.temperature_k
    areas,heights = reference.support.area_m2,reference.support.height_m
    output = np.empty((len(areas),4))
    for i in range(len(areas)):
        area = float(areas[i]); before = [float(x) for x in rv[i]]
        after = [float(x) for x in cv[i]]
        dh = [(c-r)/area for r,c in zip(before,after)]
        gap = area*float(heights[i])-math.fsum(before)
        fill_delta = gap/area*(float(cf[i])-float(rf[i]))
        inventory = math.fsum(p.density_kg_m3*h for p,h in zip(reference.phases,dh))
        replacement = math.fsum([fill_delta]+[-float(cf[i])*h for h in dh])
        mechanical = [fill_delta]+[(p.density_kg_m3-float(cf[i]))*h for p,h in zip(reference.phases,dh)]
        thermal_terms = []; k = 0
        for j,p in enumerate(reference.phases):
            m = p.thermal_material
            if m is not None:
                if before[j] != after[j]:
                    raise ValueError('moving thermal support')
                thermal_terms.append(-m.density_kg_m3*m.expansion_per_k*(float(ct[i,k])-float(rt[i,k]))*before[j]/area)
                k += 1
        output[i] = inventory,replacement,math.fsum(thermal_terms),g*math.fsum(mechanical+thermal_terms)
    if not np.isfinite(output).all():
        raise ValueError('nonfinite scalar result')
    return np.frombuffer(output.tobytes(),dtype=np.float64).reshape(output.shape)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    n = 65536; gravity = 9.81
    start = time.perf_counter(); ref,cur = fixture(n); setup = time.perf_counter()-start
    budget = WorkBudget(128*1024**2)
    def fast():
        return column_load_change(ref,cur,gravity,budget=budget)
    slow = lambda: scalar_reference(ref,cur,gravity)
    baseline, candidate = slow(),fast()
    np.testing.assert_allclose(candidate,baseline,rtol=2e-13,atol=2e-9)
    timings = {'scalar_reference': [],'batched': []}
    for repeat in range(3):
        pair = [('scalar_reference',slow),('batched',fast)]
        if repeat%2:
            pair.reverse()
        for label,run in pair:
            start = time.perf_counter(); result = run(); elapsed = time.perf_counter()-start
            np.testing.assert_array_equal(result,baseline if label=='scalar_reference' else candidate)
            timings[label].append(elapsed)
    before,after = (statistics.median(timings[k]) for k in ('scalar_reference','batched'))
    sources = [ROOT/'src/atlas_tectonics/column_loads.py',ROOT/'src/atlas_tectonics/reuse.py',Path(__file__)]
    record = dict(status='PASS_INDEPENDENT_SCALAR_AGREEMENT',columns=n,phases=8,
        thermal_phases=1,repetitions=3,platform=platform.platform(),python=sys.version.split()[0],
        numpy=np.__version__,setup_seconds=setup,timings_seconds=timings,
        median_scalar_seconds=before,median_batched_seconds=after,
        saved_seconds=before-after,saved_percent=100*(before-after)/before,speedup=before/after,
        max_absolute_difference_by_field=np.max(np.abs(candidate-baseline),axis=0).tolist(),
        accounted_peak_workspace_bytes=budget.peak_reserved_bytes,
        scope='New kernel versus straightforward scalar equations on identical prepared snapshots. Includes all four accounts. Construction separate. No full terrain, flexure, whole-generator, cache-hit or parallel speed claim.',
        source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    payload = json.dumps(record,indent=2)
    print(payload)
    if args.output:
        args.output.write_text(payload+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
