"""Bounded 3C measurements: construction/setup/query costs, not physics forecasts.

No timing pass threshold. Native imports and one small build are warmed first;
first use is recorded separately. Real allocations in native libraries can exceed
WorkBudget's conservative estimates. No global baseline or tuning framework.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT/'src'))
import numpy as np
import scipy
from atlas_tectonics import (SphericalFrame, PlanetPartitionSettings,
    generate_planetary_partition, prepare_planetary_partition, generated_partition_id)
from atlas_tectonics.resources import WorkBudget


def timed(fn, repeats=5):
    values=[];result=None
    for _ in range(repeats):
        start=time.perf_counter();result=fn();values.append(time.perf_counter()-start)
    return result, {'median_s':statistics.median(values),'min_s':min(values),
                    'max_s':max(values),'repetitions':repeats}


def main():
    sphere=SphericalFrame(1.,'synthetic-performance-sphere')
    begin=time.perf_counter();generate_planetary_partition(sphere,PlanetPartitionSettings(12,72))
    first=time.perf_counter()-begin
    report={'scope':'W01 3C synthetic geometry only; warmed comparisons; no global-world evolution',
            'runtime':{'python':platform.python_version(),'numpy':np.__version__,
                       'scipy':scipy.__version__,'platform':platform.system()},
            'first_generation_s':first,'cases':[]}
    for n in (12,64,128):
        budget=WorkBudget(256*1024**2)
        atlas,generate_time=timed(lambda:generate_planetary_partition(sphere,PlanetPartitionSettings(n,72),budget=budget))
        source=atlas.descriptor()['source_bindings']['partition_generation']
        sites=dict(zip(source['site_ids'],source['site_directions']))
        plan,prep_time=timed(lambda:prepare_planetary_partition(sphere,sites,budget=budget))
        auto,auto_time=timed(lambda:plan.build(budget=budget))
        fan,fan_time=timed(lambda:plan.build(patch_layout='triangles',budget=budget))
        rng=np.random.Generator(np.random.PCG64(512))
        queries=rng.normal(size=(512,3));queries/=np.linalg.norm(queries,axis=1)[:,None]
        start=time.perf_counter();index=auto.index(budget=budget);setup=time.perf_counter()-start
        try:hits,query_time=timed(lambda:index.query(queries,budget=budget))
        finally:index.close()
        expected=np.argmax(queries@plan.site_directions.T,axis=1)
        assert hits.pairs.shape==(512,2)
        assert np.array_equal(hits.pairs[:,1],expected)
        assert generated_partition_id(auto)==generated_partition_id(fan)
        area_delta=max(abs(auto.areas()[k]-fan.areas()[k]) for k in auto.plate_ids)
        assert area_delta <= 2e-12
        assert budget.reserved_bytes==0
        report['cases'].append({'plate_count':n,'generation':generate_time,'prepare_topology':prep_time,
            'build_auto_from_plan':auto_time,'build_fan_from_plan':fan_time,
            'patch_counts':{'auto':len(auto.patches),'triangles':len(fan.patches)},
            'prepared_bytes_estimate':plan.retained_bytes_estimate,
            'atlas_bytes_estimate':auto.retained_bytes_estimate,
            'peak_reserved_bytes':budget.peak_reserved_bytes,'reservations_released':True,
            'candidate_count':source['generation']['candidate_count'],
            'area_closure_residual_sr':auto.statistics['area_residual_sr'],
            'layout_max_area_difference_sr':area_delta,'same_intrinsic_partition':True,
            'index_setup_s':setup,'query_512':query_time,
            'query_candidate_pairs':hits.candidate_pairs,'exhaustive_pairs':hits.exhaustive_pairs,
            'independent_nearest_site_agreement':True})
    report['source_sha256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [ROOT/'src/atlas_tectonics/planetary_generation.py',Path(__file__)]}
    print(json.dumps(report,indent=2,allow_nan=False))


if __name__=='__main__':main()
