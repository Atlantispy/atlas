"""Bounded, source-pinned Stage-5 timings; synthetic inputs, no evolution.

Run sequentially against frozen pre/post source directories in the SAME runtime.
Complete-query timing includes admission, validation and output construction.
Input/plan setup and optional diagnostic profiling are reported separately.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='directory containing atlas_tectonics')
    parser.add_argument('--output', type=Path, required=True, help='new output directory')
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output exists; refusing to overwrite measurement evidence')
    sys.path.insert(0,str(args.source.resolve()))
    import numpy as np
    import scipy
    import shapely
    from threadpoolctl import threadpool_limits
    from atlas_tectonics import (
        GeologySource, MaterialDefinition, MaterialCohort, CohortDescription,
        ThermalInitialProfile, GeologicalLayer, LayerComponent, ColumnDescription,
        SurfaceSelector, GeologicalProvince, FeaturePrecedence, GeologicalCase,
        InitialConditionState, InputOrigin, CoolingHistory, MaterialVolumeBasis,
        PlanarGeometry, BoundaryRegion, build_boundary_network,
        PreparedPrecursor, InitialSamplingCell, PrecursorExecutionPolicy,
        SphericalFrame, PlanetPartitionSettings, generate_planetary_partition,
        repatch_planetary_partition,
    )
    from atlas_tectonics.execution import ExecutionPolicy
    from atlas_tectonics.resources import WorkBudget

    package = args.source/'atlas_tectonics'
    def sources():
        return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob('*.py'))}
    before = sources()
    source = GeologySource('synthetic','synthetic','Stage-5 timing fixture, not physical calibration.')
    material = MaterialDefinition('rock','solid','synthetic',3000.,3.,1000.,0.,3e-5,300.,(0.,2000.))
    cohort = CohortDescription(MaterialCohort('old','rock','declared-origin',-100.),'synthetic')
    frame = 'benchmark-metres'
    def rectangle(x0,x1):
        return PlanarGeometry.polygon([(x0,0),(x1,0),(x1,100_000),(x0,100_000)],frame_id=frame)
    regional = build_boundary_network(rectangle(0,100_000),(
        BoundaryRegion('west','p1',rectangle(0,50_000)),BoundaryRegion('east','p2',rectangle(50_000,100_000))))

    def make_state(topology, layers=1, table=0):
        profile = (ThermalInitialProfile('thermal','synthetic','tabulated',
            depths_m=tuple(np.linspace(0.,120_000.,table)),
            temperatures_k=tuple(300.+1100.*np.linspace(0.,1.,table)**2)) if table else
            ThermalInitialProfile('thermal','synthetic','constant',temperatures_k=(500.,)))
        stack = tuple(GeologicalLayer(f'layer-{i:03d}','crust' if i < max(1,layers//2) else 'lithospheric_mantle',
            120_000./layers,(LayerComponent('old',1.),),0.,'synthetic') for i in range(layers))
        column = ColumnDescription('column','continental',stack,120_000.,'thermal','synthetic')
        case = GeologicalCase('benchmark',topology,time_s=0.,epoch_id='initial',depth_reference_id='surface',
            source_id='synthetic',sources=(source,),materials=(material,),cohorts=(cohort,),
            thermal_profiles=(profile,),columns=(column,),provinces=(
                GeologicalProvince('background','column',SurfaceSelector('domain'),'synthetic'),
                GeologicalProvince('selected','column',SurfaceSelector('plates',(topology.plate_ids[0],)),'synthetic')),
            precedence=FeaturePrecedence(('selected','background')))
        return InitialConditionState(case,origins=(InputOrigin('synthetic','authored','benchmark'),),
            cooling_history=(CoolingHistory('thermal','synthetic',None,'not supplied'),),
            material_bases=(MaterialVolumeBasis('rock','grain','synthetic'),))

    records = {}
    old = None if args.compare is None else json.loads((args.compare/'measurement.json').read_text())
    cfg = PrecursorExecutionPolicy(kernel=ExecutionPolicy(mode='serial',max_workers=1))
    start = time.perf_counter()
    state = make_state(regional,layers=256)
    n = 100_000
    points = np.column_stack((np.linspace(0.,100_000.,n),np.full(n,50_000.)))
    depths = np.linspace(.1,119_999.9,n)
    workloads = [('regional_layered_points',state,'points',(points,depths),time.perf_counter()-start)]
    start = time.perf_counter()
    state = make_state(regional,layers=128)
    cells = tuple(InitialSamplingCell(f'c{i}',rectangle(i*100_000/64,(i+1)*100_000/64),0.,120_000.) for i in range(64))
    workloads.append(('regional_layered_cells',state,'cells',(cells,),time.perf_counter()-start))
    start = time.perf_counter()
    state = make_state(regional,table=2049)
    cells = tuple(InitialSamplingCell(f't{i}',rectangle(i*100_000/24,(i+1)*100_000/24),float(i)*200.,120_000.-float(i)*200.) for i in range(24))
    workloads.append(('regional_tabulated_cells',state,'cells',(cells,),time.perf_counter()-start))
    start = time.perf_counter()
    planet = repatch_planetary_partition(generate_planetary_partition(
        SphericalFrame(6_000_000.,'benchmark-planet'),PlanetPartitionSettings(16,22)))
    state = make_state(planet)
    cells = tuple(InitialSamplingCell(f'{r.region_id}-{i}',r.geometry,i*15_000.,(i+1)*15_000.)
        for r in planet.regions for i in range(8))
    workloads.append(('planetary_depth_bands',state,'cells',(cells,),time.perf_counter()-start))

    args.output.mkdir(parents=True)
    with threadpool_limits(limits=1):
        for name,state,kind,inputs,construction in workloads:
            budget = WorkBudget(512<<20)
            request = dict(frame_id=state.sampling_domain.frame_id,epoch_id=state.case.epoch_id,
                           depth_reference_id=state.case.depth_reference_id)
            start = time.perf_counter(); plan = PreparedPrecursor(state,budget=budget,execution_policy=cfg)
            setup = time.perf_counter()-start
            try:
                call = getattr(plan,'sample_'+kind)
                elapsed = []
                for _ in range(3):
                    start = time.perf_counter(); result = call(*inputs,**request)
                    elapsed.append(time.perf_counter()-start)
                arrays = {k:result.array(k) for k in result._buffers}
                np.savez_compressed(args.output/(name+'.npz'),**arrays)
                parity = None
                if old is not None:
                    if old['workloads'][name]['state_id'] != state.state_id:
                        raise AssertionError('input state changed between measurements')
                    parity = {'exact':True,'max_float_absolute_error':0.}
                    with np.load(args.compare/(name+'.npz'),allow_pickle=False) as previous:
                        if set(previous.files) != set(arrays): raise AssertionError('array inventory changed')
                        for key,value in arrays.items():
                            prior = previous[key]
                            if value.dtype != prior.dtype or value.shape != prior.shape: raise AssertionError('representation changed')
                            if not np.array_equal(value,prior):
                                parity['exact'] = False
                                if value.dtype.kind != 'f': raise AssertionError('categorical/integer result changed')
                                error = float(np.max(np.abs(value-prior))) if value.size else 0.
                                parity['max_float_absolute_error'] = max(parity['max_float_absolute_error'],error)
                                # Only integrated temperatures may differ in floating rounding.
                                if key != 'temperature_k': raise AssertionError('non-temperature result changed: '+key)
                                np.testing.assert_allclose(value,prior,rtol=0.,atol=1e-10)
                record = dict(kind=kind,query_count=len(inputs[0]),layers=len(state.units),
                    table_points=len(state.case.thermal_profiles[0].depths_m),state_id=state.state_id,
                    input_construction_s=construction,prepared_setup_s=setup,complete_calls_s=elapsed,
                    median_complete_call_s=statistics.median(elapsed),warm_median_s=statistics.median(elapsed[1:]),
                    result_bytes=result.nbytes,execution=plan.execution_statistics(),parity=parity)
                if old is not None:
                    previous = old['workloads'][name]['median_complete_call_s']
                    record.update(saved_s=previous-record['median_complete_call_s'],
                        saved_percent=100*(previous-record['median_complete_call_s'])/previous)
                if args.profile:
                    import cProfile, pstats
                    profiler = cProfile.Profile(); profiler.runcall(call,*inputs,**request)
                    stats = pstats.Stats(profiler)
                    record['diagnostic_profile'] = [dict(function=f'{Path(k[0]).name}:{k[1]}:{k[2]}',calls=v[1],self_s=v[2],cumulative_s=v[3])
                        for k,v in sorted(stats.stats.items(),key=lambda item:item[1][3],reverse=True)[:18]]
                records[name] = record
                print(name, json.dumps({k:record[k] for k in ('query_count','complete_calls_s','parity')},allow_nan=False),flush=True)
            finally:
                plan.close()
            if budget.reserved_bytes: raise AssertionError('resource reservation leak')
            records[name]['resources'] = budget.statistics()
    if sources() != before: raise AssertionError('source changed during measurement')
    measurement = dict(schema='atlas.w01-sampling-timing.v1',workloads=records,source_sha256=before,
        benchmark_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        runtime=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,
                     shapely=shapely.__version__,platform=platform.system(),native_threads=1),
        scope='Synthetic complete-query workloads, not physical-world evolution or whole-generator forecasts; profiling excluded from timed samples.')
    (args.output/'measurement.json').write_text(json.dumps(measurement,indent=2,allow_nan=False)+'\n',encoding='utf-8')


if __name__ == '__main__': main()
