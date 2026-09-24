#!/usr/bin/env python3
"""Source-bound cold/prepared timings for the two evolving mechanics adapters.

Both routes perform the same three changed requests and complete output hashes.
Fixtures are synthetic; this is not a geological calibration or world campaign.
"""
from dataclasses import asdict
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'),str(ROOT/'tests')]
import numpy as np
import scipy
from atlas_tectonics.evolving_mechanics import (RegionalInputContext, RegionalInputBlock,
    RegionalMechanicalRequest, PreparedEvolvingRegionalMechanics)
from atlas_tectonics.regional_execution import RegionalMechanicsScales
from atlas_tectonics.regional_stokes import boundary_coordinates
from atlas_tectonics.evolving_flexure import (W04RigidityState, W04AbsoluteReferenceLoad,
    PreparedEvolvingW04Support)
from atlas_tectonics.w04_workflow import W04SurfaceInputs, W04SupportPolicy
from atlas_tectonics.parameters import FlexureParameters
from atlas_tectonics.variable_flexure import RigidityProfile1D, VariableFlexureAccuracy
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.reuse import _source_bytes
from atlas_tectonics.stokes_execution import _native_lease
# Reuse only the real typed W01-W03 producer fixture, not its test oracle.
# Every imported test-helper file is bound below along with all production files.
from test_w03_workflow import workflow_fixture, initialise


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def signature(result):
    h = hashlib.sha256(encoded(result.descriptor()))
    h.update(result.result_id.encode())
    arrays = ([result.array(n) for n in result.array_names] if hasattr(result,'array_names')
              else [result.values,result.absolute_values,result.reservoir_surface_known])
    for a in arrays:
        h.update(encoded(dict(shape=a.shape,dtype=a.dtype.str)))
        h.update(a.tobytes())
    return h.hexdigest()


def regional_fixture():
    n = 12
    kinds = {s:{c:'velocity' for c in ('u','w')} for s in ('left','right','bottom','top')}
    requests = []
    controls = []
    for i,(eta,shear) in enumerate(((1.,.5),(2.,1.),(2.,1.5))):
        c = RegionalInputContext(n,n,1.,1.,'synthetic-section','z0','seconds',float(i),0.,0.)
        material = RegionalInputBlock(c,'material',{'centre':np.full((n,n),eta),'vertex':np.full((n+1,n+1),eta)},
            source_id='supplied Newtonian fixture',producer_state_id=f'material-{i}',sampling='uniform exact stress sites')
        forces = RegionalInputBlock(c,'body-force',{'u':np.zeros((n,n+1)),'w':np.zeros((n+1,n))},
            source_id='known zero force',producer_state_id=f'force-{i}',sampling='full MAC faces',effect_ids=('no-body-force',))
        boundary = RegionalInputBlock(c,'boundary',{s+'_'+k:(shear*boundary_coordinates(n,n,1.,1.,s,k)[1] if k=='u' else 0.)
            for s in kinds for k in ('u','w')},source_id='analytic simple shear',producer_state_id=f'boundary-{i}',
            sampling='exact affine trace',effect_ids=('plate-motion',),boundary_types=kinds)
        requests.append(RegionalMechanicalRequest(material,(forces,),boundary))
        controls.append((eta,shear))
    def create(budget):
        return PreparedEvolvingRegionalMechanics(requests[0].context,kinds,scales=RegionalMechanicsScales(1.,1.),
            viscosity_scale_pa_s=1.,physical_mean_pressure_pa=0.,budget=budget)
    def solve(plan,index):
        result = plan.evaluate(requests[index])
        eta,shear = controls[index]
        expected_u = np.broadcast_to(shear*(np.arange(n)+.5)[:,None]/n,(n,n+1))
        np.testing.assert_allclose(result.array('u_m_s'),expected_u,rtol=0.,atol=1e-9)
        np.testing.assert_allclose(result.array('w_m_s'),0.,rtol=0.,atol=1e-9)
        np.testing.assert_allclose(result.array('deviatoric_stress_xz_pa'),eta*shear,rtol=0.,atol=1e-8)
        return result
    return create,solve,dict(grid=[n,n],requests=[r.request_id for r in requests],controls=controls,
                             oracle='u=shear*z, w=0, shear stress=eta*shear; supplied affine boundary')


def flexure_fixture():
    n = 32
    state = initialise(workflow_fixture(cells=n,length_m=40000.))
    ids = tuple(c['cell_id'] for c in state.source_workflow.initial_samples.descriptor()['cells'])
    reservoir = np.full(n,state.reservoir_fluid_m3/n)
    def surface(p): return W04SurfaceInputs(state,ids,reservoir,p,source_id='synthetic prescribed surface pressures')
    ref_surface = surface(np.zeros(n))
    elastic = FlexureParameters('evolving-control','synthetic',7e10,1000.,.25,3300.,10.)
    policy = W04SupportPolicy('synthetic','periodic-repetition','flexure',0.,100.,.1,.01,elastic)
    accuracy = VariableFlexureAccuracy('fixed benchmark gate',1e-3,1e-8,1e-11,1e-14)
    def rigidity(te):
        profile = RigidityProfile1D(state.material.grid,np.full(n,7e10),np.full(n,te),np.full(n,.25),
            source_id='supplied elastic properties',frame_id=state.source_workflow.initial_samples.descriptor()['frame_id'],
            datum_id=state.binding.depth_reference_id,epoch_id=state.binding.epoch_id)
        return W04RigidityState(state,profile,source_id='state-matched elastic scenario')
    r0,r1 = rigidity(1000.),rigidity(1200.)
    x = (np.arange(n)+.5)/n
    q0 = 2000.*np.sin(2*np.pi*x)
    datum = W04AbsoluteReferenceLoad(state,ref_surface,policy,q0,source_id='declared stress-free-geometry load datum')
    changed = [surface(i*500.*np.cos(2*np.pi*x)) for i in (1.,2.,3.)]
    profiles = (r0,r1,r1)
    def create(budget):
        return PreparedEvolvingW04Support(state,ref_surface,policy,reference_rigidity=r0,
            reference_absolute_load=datum,accuracy=accuracy,budget=budget)
    def solve(plan,index):
        result = plan.solve(state,changed[index],rigidity=profiles[index])
        np.testing.assert_allclose(result.downward_load_pa,changed[index].external_downward_pressure_pa,
                                   rtol=0.,atol=1e-10)
        if not np.isfinite(result.absolute_values).all(): raise AssertionError('nonfinite absolute response')
        return result
    return create,solve,dict(cells=n,length_m=40000.,w03_state_id=state.state_id,
        reference_load=datum.descriptor(),pressure_q0_pa=q0.tolist(),accuracy=asdict(accuracy),
        profiles=[p.input_id for p in profiles],surfaces=[s.input_id for s in changed],
        note='three changed elastic/load scenarios at one actual W03 instant; no inferred material evolution')


def source_binding():
    supporting = {Path(__file__).resolve(),ROOT/'cases/w08_regimes.json',ROOT/'cases/w07_mechanics.json'}
    for name,module in tuple(sys.modules.items()):
        path = getattr(module,'__file__',None)
        if name.startswith('test_') and path and Path(path).resolve().parent == ROOT/'tests':
            supporting.add(Path(path).resolve())
    return dict(production={name:json.loads(raw) for name,raw in _source_bytes().items()},
        tools_and_fixtures={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(supporting)})


def measure(fixture):
    create,solve,definition = fixture
    raw = {'cold':[],'prepared':[]}; controls=[]; baseline=None; peak=0
    for repeat in range(3):
        for reuse in ((False,True) if repeat%2 == 0 else (True,False)):
            owner = WorkBudget(128*1024**2); results=[]; stats=[]
            with owner.reserve(4*1024**2,category='evolving-benchmark-fixtures'):
                started = time.perf_counter()
                for indices in ((range(3),) if reuse else ((i,) for i in range(3))):
                    with create(owner) as plan:
                        for index in indices:
                            result = solve(plan,index)
                            results.append(signature(result)); del result
                        if hasattr(plan,'statistics'): stats.append(plan.statistics())
                elapsed = time.perf_counter()-started
            if owner.reserved_bytes != 0: raise AssertionError('leaked shared reservation')
            if baseline is None: baseline = results
            if baseline != results: raise AssertionError('complete cold/prepared response identity changed')
            if stats and (sum(s['changed_outputs'] for s in stats)!=3 or any(s['latest_hits'] for s in stats)):
                raise AssertionError('must compute all three changed outputs with no latest-result hits')
            raw['prepared' if reuse else 'cold'].append(elapsed)
            controls.append(dict(repeat=repeat+1,reuse=reuse,statistics=stats))
            peak=max(peak,owner.peak_reserved_bytes)
    cold,warm = (statistics.median(raw[k]) for k in ('cold','prepared'))
    return dict(status='PASS',inputs=definition,repeats_s=raw,cold_median_s=cold,prepared_median_s=warm,
        seconds_saved=cold-warm,percent_saved=100*(cold-warm)/cold,complete_output_sha256=baseline,
        complete_output_hash_parity=True,observations=controls,peak_accounted_bytes=peak,
        final_reserved_bytes=0,resource_measurement='accounted allocation, not process RSS')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    if args.report.exists(): raise FileExistsError('new evidence path required')
    started=time.perf_counter()
    sources=source_binding()
    with _native_lease():
        regional=measure(regional_fixture())
        flexure=measure(flexure_fixture())
    if source_binding()!=sources: raise AssertionError('source changed during measurement')
    report=dict(schema='atlas.evolving-inputs-evidence.v1',status='PASS',sources=sources,
        runtime=dict(platform=platform.platform(),python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,native_threads=1),
        regional=regional,flexure=flexure,wall_s=time.perf_counter()-started,
        included='cold preparation, live source checks, all three changing solves, output hashing, controls, close',
        excluded='imports, immutable upstream fixture construction, report writing',
        limits='synthetic 12x12 regional and 32-cell elastic scenarios, not whole-generator or empirical validation')
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,sort_keys=True,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps({name:{k:r[k] for k in ('cold_median_s','prepared_median_s','seconds_saved','percent_saved','peak_accounted_bytes')}
                      for name,r in (('regional',regional),('flexure',flexure))},sort_keys=True))


if __name__ == '__main__': main()
