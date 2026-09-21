"""Small matched complete-adapter comparison; no dynamics, installs or parameter sweep."""
from pathlib import Path
import argparse, hashlib, json, os, platform, statistics, sys, time


def inventory(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root/'tectonics').rglob('*')) if p.is_file() and '__pycache__' not in str(p)}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args=ap.parse_args(); root=args.source.resolve()
    if args.output.exists(): ap.error('output exists; preserve earlier measurements')
    sys.path.insert(0,str(root/'tectonics/src'))
    start=time.perf_counter()
    import numpy as np
    import scipy, shapely, numba
    from atlas_tectonics import (PlanarGeometry, BoundaryRegion, build_boundary_network,
                                RegionalGrid1D, GeometryLimits)
    from atlas_tectonics.regional_forcing import (PrescribedPlateMotion, PlanarRegionalSection,
        RegionalMotionDefinition, RegionalReduction, PreparedRegionalForcing)
    from atlas_tectonics.geological_records import GeologySource
    from atlas_tectonics.resources import WorkBudget
    import_seconds=time.perf_counter()-start
    before=inventory(root)
    source=GeologySource('s6-timing','synthetic','Eight fixed strips, equal compatible translations and co-rotating frame; complete adapter timing only')
    units=dict(length_unit='m',velocity_unit='m/s',angular_velocity_unit='rad/s')
    def rectangle(x0,x1):
        return PlanarGeometry.polygon(((x0,-100.),(x1,-100.),(x1,100.),(x0,100.)),frame_id='timing-plane')
    setup_start=time.perf_counter()
    domain=rectangle(0.,8192.)
    net=build_boundary_network(domain,tuple(BoundaryRegion('strip'+str(i),'P'+str(i),rectangle(1024.*i,1024.*(i+1))) for i in range(8)))
    motions=tuple(PrescribedPlateMotion('P'+str(i),'timing-plane','epoch',0.,'planar-rigid',
        (1.25,0.,0.),(0.,0.,.125),(0.,0.,0.),source,**units) for i in range(8))
    definition=RegionalMotionDefinition(net,motions,'epoch',0.,.25,'s',source)
    section=PlanarRegionalSection('section','timing-plane','epoch',0.,(0.,0.,0.),(1.,0.),8192.,
        (.125,0.,0.),(0.,0.,.125),source,**units)
    reduction=RegionalReduction('planar-columns','frozen-at-start',source,1.)
    grid=RegionalGrid1D(4095,8192.)
    geometry_setup=time.perf_counter()-setup_start
    kwargs=dict(frame_id='timing-plane',epoch_id='epoch',start_time_s=0.,duration_s=.25)
    budget=WorkBudget(256*1024**2)
    b=time.perf_counter()
    plan=PreparedRegionalForcing(definition,section,reduction,limits=GeometryLimits(batch_points=512),budget=budget)
    preparation=time.perf_counter()-b
    rows=[]; first={}; ids={}; equality=[]
    try:
        # First complete call per route is recorded separately; no JIT in this adapter.
        for mode in ('reference','vectorised'):
            t=time.perf_counter(); f=plan.faces(grid,backend=mode,**kwargs)
            first[mode]=time.perf_counter()-t
            ids[mode]=f.forcing_id
        for rep in range(5):
            order=('reference','vectorised') if rep%2==0 else ('vectorised','reference')
            results={}
            for mode in order:
                c=time.process_time(); t=time.perf_counter()
                f=plan.faces(grid,backend=mode,**kwargs)
                elapsed=time.perf_counter()-t; cpu=time.process_time()-c
                if f.forcing_id != ids[mode]: raise AssertionError('hidden state or nondeterministic replay')
                results[mode]=f
                rows.append(dict(repetition=rep,backend=mode,seconds=elapsed,cpu_seconds=cpu,forcing_id=f.forcing_id))
            reference=results['reference']; vectorised=results['vectorised']
            # In this exactly aligned fixture, EVERY published numerical array is exact.
            checks={k:np.array_equal(a,vectorised.arrays()[k]) for k,a in reference.arrays().items()}
            if not all(checks.values()): raise AssertionError(checks)
            # Independent relative velocity and strip-ownership expectations.
            s=vectorised.samples.offsets_m
            owners=np.minimum((s/1024).astype(int),7)
            expected=np.full(len(s),1.25-.125)
            expected_pairs=np.column_stack((np.arange(len(s)),owners))
            if not np.array_equal(vectorised.samples.owner_pairs,expected_pairs): raise AssertionError('analytic ownership mismatch')
            if not np.array_equal(vectorised.face_velocity_m_s,expected): raise AssertionError('analytic velocity mismatch')
            equality.append(checks)
        peak=budget.peak_reserved_bytes
    finally:
        plan.close()
    if budget.reserved_bytes: raise AssertionError('reservation leak')
    summary={}
    for mode in ('reference','vectorised'):
        times=[x['seconds'] for x in rows if x['backend']==mode]
        summary[mode]=dict(raw_seconds=times,median_seconds=statistics.median(times),min_seconds=min(times),max_seconds=max(times))
    base=summary['reference']['median_seconds']; candidate=summary['vectorised']['median_seconds']
    out=dict(scope='complete prepared faces() on identical fixed definitions; no transport evolution',
        workload=dict(plates=8,cells=4095,faces=4096,batch_points=512,length_m=8192.,repetitions=5,
                      angular_rate_rad_s=.125,frame_speed_m_s=.125,plate_speed_m_s=1.25),
        baseline='same candidate implementation, clear scalar velocity arithmetic; identical source/index/ownership/validation/provenance work',
        unavailable_baseline='no earlier Stage-6 production adapter; not a measured pipeline or old-release speedup',
        import_seconds=import_seconds,geometry_definition_setup_seconds=geometry_setup,
        prepared_plan_setup_seconds=preparation,first_complete_query_seconds=first,
        JIT='not used by this adapter; no compilation hidden in timed calls',
        rows=rows,summary=summary,speedup=base/candidate,less_time_percent=100*(1-candidate/base),
        ranges_overlap=not(summary['reference']['min_seconds']>summary['vectorised']['max_seconds'] or summary['vectorised']['min_seconds']>summary['reference']['max_seconds']),
        exact_fields=equality,analytic_strip_velocities_pass=True,repeated_ids_exact=True,
        peak_admitted_bytes=peak,budget_limit_bytes=256*1024**2,reserved_after_close=budget.reserved_bytes,
        source_unchanged=before==inventory(root),source_hashes=before,
        driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        python=sys.version,platform=platform.platform(),versions={m.__name__:m.__version__ for m in (np,scipy,shapely,numba)},
        threads={k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS')},
        command=[sys.executable,'-I','-B',str(Path(__file__).resolve()),*sys.argv[1:]])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps({k:out[k] for k in ('summary','speedup','less_time_percent','ranges_overlap','geometry_definition_setup_seconds','prepared_plan_setup_seconds','first_complete_query_seconds','peak_admitted_bytes','reserved_after_close','source_unchanged')},indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
