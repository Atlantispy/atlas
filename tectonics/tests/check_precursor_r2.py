#!/usr/bin/env python3
"""Finite R2 verification/measurement card, not the deferred baseline programme.

Cold and prepared timings exercise the same native API and complete output;
independent exhaustive membership is a correctness oracle, not a differently
accounted speed competitor. No machine capacity extrapolation is made.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import platform
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from verify import source_inventory


def main():
    import numpy as np
    import shapely
    from atlas_tectonics import PreparedPrecursor,save_initial_samples,load_initial_samples
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore,StoreLimits
    from precursor_fixtures import mixed_case,state,cell,rectangle,REQUEST
    from test_precursor_sampling import phase_totals
    before=source_inventory(ROOT)
    spec=json.loads((ROOT/'cases/precursor_r2.json').read_text())['bounded_execution_case']
    start=time.perf_counter();s=state(mixed_case(edge=3.7));state_setup=time.perf_counter()-start
    nx,ny=spec['point_grid']
    xx,yy=np.meshgrid((np.arange(nx)+.5)*10/nx,(np.arange(ny)+.5)*10/ny,indexing='ij')
    points=np.column_stack((xx.ravel(),yy.ravel()));depths=np.linspace(.1,29.9,len(points))
    budget=WorkBudget(128<<20);cold=[]
    for _ in range(spec['cold_repeats']):
        t=time.perf_counter()
        with PreparedPrecursor(s,budget=budget) as p: r=p.sample_points(points,depths,**REQUEST)
        cold.append(time.perf_counter()-t)
    t=time.perf_counter();plan=PreparedPrecursor(s,budget=budget);plan_setup=time.perf_counter()-t
    warm=[];grids=[]
    try:
        for _ in range(spec['prepared_repeats']):
            t=time.perf_counter();q=plan.sample_points(points,depths,**REQUEST);warm.append(time.perf_counter()-t)
            for name in r._buffers: np.testing.assert_array_equal(r.array(name),q.array(name))
        # Scalar exhaustive selector resolution independent of the index and
        # grouped assignments. GEOS predicates themselves are a shared dependency.
        c=s.case;expected_t=[];expected_unit=[];expected_province=[];expected_matches=[]
        shape={g.key:shapely.from_wkb(g.geometry.wkb) for g in c.geometries}
        for xyz,z in zip(points,depths):
            point=shapely.Point(*xyz)
            hit={key for key,g in shape.items() if g.covers(point)}
            chosen=c.resolve_provinces(tuple(p.province_id for p in c.provinces if p.selector.kind=='domain' or hit.intersection(p.selector.keys)))
            col=c.column(chosen.column_id)
            unit=next(i for i,u in enumerate(s.units) if u.kind=='column' and u.owner_id==col.column_id and u.top_depth_m<=z<u.bottom_depth_m)
            expected_unit.append(unit)
            expected_province.append(tuple(p.province_id for p in c.provinces).index(chosen.province_id))
            expected_matches.append(chosen.matching_province_ids)
            expected_t.append(next(t.temperatures_k[0] for t in c.thermal_profiles if t.profile_id==col.thermal_profile_id))
        error=float(np.max(np.abs(r.temperature()-expected_t)))
        if error>spec['point_max_absolute_error_k']: raise AssertionError('point reference mismatch')
        np.testing.assert_array_equal(r.array('unit_code'),expected_unit)
        np.testing.assert_array_equal(r.array('province_code'),expected_province)
        offsets=r.array('province_offsets');candidates=r.array('province_candidates');pids=tuple(p.province_id for p in c.provinces)
        for i,ids in enumerate(expected_matches):
            if tuple(pids[j] for j in candidates[offsets[i]:offsets[i+1]])!=ids: raise AssertionError('lost province association')
        for count in spec['horizontal_cell_counts']:
            cells=tuple(cell('cell-'+str(i),rectangle(i*10/count,(i+1)*10/count)) for i in range(count))
            t=time.perf_counter();sample=plan.sample_cells(cells,**REQUEST);elapsed=time.perf_counter()-t
            totals=phase_totals(sample);expected={'old':1890.,'young':1110.}
            rel=max(abs(totals[k]-v)/v for k,v in expected.items())
            if rel>spec['inventory_max_relative_error']: raise AssertionError('refinement inventory mismatch')
            grids.append({'cells':count,'seconds':elapsed,'cohort_volumes_m3':totals,
                'max_relative_inventory_error':rel,'max_absolute_coverage_residual_m3':float(np.max(np.abs(sample.array('coverage_residual_m3'))))})
        with tempfile.TemporaryDirectory() as tmp:
            with ArrayStore(Path(tmp)/'r2.db',StoreLimits(4096,8<<20,32<<20),budget=budget) as store:
                t=time.perf_counter();save_initial_samples(sample,store,budget=budget);save_seconds=time.perf_counter()-t
                t=time.perf_counter();restored=load_initial_samples(store,sample.sample_id,budget=budget);restore_seconds=time.perf_counter()-t
                for name in sample._buffers: np.testing.assert_array_equal(sample.array(name),restored.array(name))
                stats=store.statistics()
        held=budget.reserved_bytes
    finally:
        plan.close()
    after=source_inventory(ROOT)
    if before!=after: raise AssertionError('source changed during R2 check')
    if budget.reserved_bytes: raise AssertionError('budget reservation leak')
    record={'schema':'atlas.precursor-r2-bounded-evidence.v1','status':'PASS_BOUNDED_R2_INITIAL_SAMPLING',
        'branch':'remake','base_commit':'e79bf94ea5285a36bbce18b503234a8df56e3910',
        'scope':'new R2 static sampling only; no broad benchmark, reference acquisition, evolution or physical acceptance',
        'source_unchanged':True,'source_sha256_before':before,'source_sha256_after':after,
        'runtime':{'python':platform.python_version(),'numpy':np.__version__,'shapely':shapely.__version__,
            'platform':platform.system(),'machine':platform.machine(),
            'threads':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}},
        'state_id':s.state_id,'points':len(points),'point_reference_max_absolute_error_k':error,
        'point_unit_province_and_all_match_records_equal':True,
        'timings_seconds':{'state_construction':state_setup,'cold_complete_calls':cold,'prepared_setup':plan_setup,
            'prepared_complete_calls':warm,'save_self_contained_snapshot':save_seconds,'cold_snapshot_restore':restore_seconds},
        'grid_checks':grids,'restored_all_arrays_exact':True,
        'storage':{k:stats[k] for k in ('unique_chunks','encoded_payload_bytes','snapshots','database_bytes')},
        'resources':budget.statistics(),'held_plan_bytes_before_close':held,
        'claims':{'physical_validation':False,'production_ready':False,'RSS_cap':False,'universal_speedup':False,
                  'Windows_tested':False,'whole_planet_disjoint_mesh_accepted':False}}
    print(json.dumps(record,indent=2,allow_nan=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
