"""Three alternating source-version pairs for complete W01-W04 links."""
import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[key] = '1'
parser = argparse.ArgumentParser()
parser.add_argument('--repo',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--source',type=Path)
parser.add_argument('--baseline',type=Path)
parser.add_argument('--candidate',type=Path)
args = parser.parse_args()
if args.output.exists():
    raise RuntimeError('refusing existing evidence destination')

def write(path,value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2,allow_nan=False)
        stream.write('\n')

if args.source is None:
    if args.baseline is None or args.candidate is None:
        parser.error('paired mode requires baseline and candidate sources')
    args.output.mkdir(parents=True)
    results = {'baseline':[],'candidate':[]}
    started = time.perf_counter()
    for trial in range(3):
        sequence = ('baseline','candidate') if trial%2==0 else ('candidate','baseline')
        for label in sequence:
            output = args.output/f'{label}-{trial}.json'
            command = [sys.executable,'-B',str(Path(__file__).resolve()),'--repo',str(args.repo),
                       '--source',str(getattr(args,label)),'--output',str(output)]
            completed = subprocess.run(command,check=True,capture_output=True,text=True,timeout=90)
            print(completed.stdout,end='',flush=True)
            if completed.stderr:
                print(completed.stderr,end='',file=sys.stderr)
            results[label].append(json.loads(output.read_text(encoding='utf-8')))
    expected = results['baseline'][0]['scientific_outputs']
    for label,records in results.items():
        for trial,record in enumerate(records):
            if record['scientific_outputs'] != expected:
                raise AssertionError(f'full output mismatch {label} trial {trial}; raw evidence retained')
            if record['source_sha256'] != records[0]['source_sha256']:
                raise AssertionError('source changed between paired trials')
    measurements = {}
    for route in results['baseline'][0]['seconds']:
        raw = {label:[r['seconds'][route] for r in records] for label,records in results.items()}
        a,b = (statistics.median(raw[label]) for label in ('baseline','candidate'))
        measurements[route] = dict(seconds=raw,baseline_median_s=a,candidate_median_s=b,
            saved_s=a-b,saved_percent=100*(a-b)/a)
    write(args.output/'summary.json',dict(schema='atlas.w11-early-paired.v1',
        status='PASS_EXACT_FULL_SCIENTIFIC_OUTPUTS',trials=3,alternating=True,
        wall_seconds=time.perf_counter()-started,measurements=measurements,
        source_versions={label:records[0]['source_sha256'] for label,records in results.items()},
        identity_policy=results['baseline'][0]['identity_policy'],
        scope='Synthetic 128-cell W01-W04 and 48-cell nonzero W02 transport. Complete timed calls include source checks, admission, outputs and owned preparation/closure. Worker import and untimed fixture preparation excluded. No whole-world prediction.'))
    print('PASS exact output bytes/descriptors across all six source-bound trials',flush=True)
    raise SystemExit

sys.path[:0] = [str(args.source.resolve()),str(args.repo/'tectonics/tests')]
import numpy as np
from atlas_tectonics import (FlexureParameters,W03ExecutionContext,advance_w03_columns,
    W04SupportPolicy,W04SurfaceInputs,PreparedW04Support,project_w04_support)
from atlas_tectonics.regional_workflow import PreparedRegionalWorkflow
from test_w03_workflow import initialise,workflow_fixture,STEP
from test_w01_workflow import workflow_fixture as moving_fixture,LEFT,RIGHT

def sources():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((args.source/'atlas_tectonics').glob('*.py'))}

before = sources()
seconds = {}
raw = {}
identities = {}
arrays = {}

def bind(label,value):
    if type(value) is not str or len(value)!=64:
        raise AssertionError('only explicit derived identities may be rebound in comparison')
    identities.setdefault(value,'<derived:'+label+'>')

def array(value):
    a = np.asarray(value)
    key='array_'+str(len(arrays))
    arrays[key]=a
    return dict(array_key=key,dtype=a.dtype.str,shape=list(a.shape),sha256=hashlib.sha256(a.tobytes()).hexdigest())

def timed(name,run):
    started=time.perf_counter(); result=run(); seconds[name]=time.perf_counter()-started
    return result

def workflow_output(label,state):
    sample=state.initial_samples
    motion=state.forcing.samples.descriptor()
    bind(label+':samples',sample.sample_id)
    bind(label+':sample-plan',sample.descriptor()['plan_id'])
    bind(label+':forcing',state.forcing.forcing_id)
    bind(label+':motion-plan',motion['plan_id'])
    bind('reference-execution',motion['execution_id'])
    bind(label+':motion-samples',state.forcing.samples.identity)
    bind(label+':workflow',state.workflow_id)
    if state.parent is not None:
        bind(label+':parent-workflow',state.parent.workflow_id)
    bind('reference-execution',state.execution_id)
    raw[label]=dict(workflow=state.descriptor(),sample=sample.descriptor(),
        sample_arrays={k:array(sample.array(k)) for k in sample._buffers},
        forcing=state.forcing.descriptor(),forcing_arrays={k:array(v) for k,v in state.forcing.arrays().items()},
        material=state.material.descriptor(),material_array=array(state.material.thickness_m))

n=128
workflow=timed('w01_w02_initialise',lambda:workflow_fixture(cells=n,length_m=100000.,width_m=1000.))
workflow_output('stationary-root',workflow)
state=timed('w03_initialise',lambda:initialise(workflow,subdivisions={'upper':32,'lower':32}))
bind('w03-execution',state.execution_id)
bind('w03-root',state.state_id)
ids=tuple(c['cell_id'] for c in workflow.initial_samples.descriptor()['cells'])
policy=W04SupportPolicy('synthetic-uniform-plate-benchmark','periodic-repetition','flexure',
    0.,1000.,.05,.01,FlexureParameters('synthetic','timing fixture, not calibration',7e10,1000.,.25,3300.,10.))
reference_surface=W04SurfaceInputs(state,ids,np.full(n,state.reservoir_fluid_m3/n),np.zeros(n),source_id='reference-placement')
bind('reference-surface',reference_surface.input_id)
schedule=tuple(((j+1)*STEP,1e6 if j%2==0 else 0.) for j in range(3))

def advance(prepared):
    current=state; out=[]
    with W03ExecutionContext() if prepared else nullcontext() as context:
        for now,load in schedule:
            current=advance_w03_columns(current,time_s=now,top_effective_stress_pa=load,context=context)
            out.append(current)
    return tuple(out)

cold=timed('w03_three_changed_cold',lambda:advance(False))
states=timed('w03_three_changed_prepared',lambda:advance(True))
for i,(a,b) in enumerate(zip(cold,states)):
    assert a.state_id==b.state_id and a.descriptor()==b.descriptor()
    bind('w03-step-'+str(i),b.state_id)
    for name in ('_grain','_state','_area','_traction'):
        assert getattr(a.compaction,name)==getattr(b.compaction,name)
    assert np.array_equal(a.material.thickness_m,b.material.thickness_m)
for i,s in enumerate((state,*states)):
    raw['w03-'+str(i)]=dict(descriptor=s.descriptor(),material=s.material.descriptor(),
        material_array=array(s.material.thickness_m),compaction=s.compaction.descriptor(),
        compaction_arrays={k:array(getattr(s.compaction,k)) for k in ('grain_volume_m3','void_ratio',
            'maximum_effective_stress_pa','area_m2','top_effective_stress_pa')})
surfaces=tuple(W04SurfaceInputs(s,ids,np.full(n,s.reservoir_fluid_m3/n),
    (j+1)*100.*np.cos(2*np.pi*np.arange(n)/n),source_id='placement-'+str(j)) for j,s in enumerate(states))
for j,surface in enumerate(surfaces):
    bind('surface-'+str(j),surface.input_id)
    raw['surface-'+str(j)]=dict(source=surface.source_id,reservoir=surface.reservoir_id,
        cells=surface.cell_ids,volume=array(surface.reservoir_volume_m3),pressure=array(surface.external_downward_pressure_pa))

def project(prepared,identical=False):
    if prepared:
        with PreparedW04Support(state,reference_surface,policy) as plan:
            chosen=tuple(zip(states,surfaces)) if not identical else ((states[0],surfaces[0]),)*3
            return tuple(plan.solve(s,u) for s,u in chosen)
    return tuple(project_w04_support(state,s,reference_surface,u,policy) for s,u in zip(states,surfaces))

a=timed('w04_three_changed_cold',lambda:project(False))
b=timed('w04_three_changed_prepared',lambda:project(True))
c=timed('w04_three_identical_prepared',lambda:project(True,True))
for i,(x,y) in enumerate(zip(a,b)):
    assert (x.result_id,x._metadata,x._payload,x._wet)==(y.result_id,y._metadata,y._payload,y._wet)
    metadata=json.loads(x._metadata)
    bind('w04-plan',metadata['plan_id'])
    raw['w04-'+str(i)]=dict(metadata=metadata,values=array(x.values),wet=array(x.reservoir_surface_known))
for x in c:
    assert (x.result_id,x._metadata,x._payload,x._wet)==(a[0].result_id,a[0]._metadata,a[0]._payload,a[0]._wet)

fixture=moving_fixture(cells=48,duration=.06)
def moving():
    with PreparedRegionalWorkflow(*fixture,backend='reference') as plan:
        root=plan.initialise()
        final=plan.advance(root,left=LEFT,right=RIGHT)
        return root,final
moving_root,moving_final=timed('w02_moving_setup_and_continue',moving)
workflow_output('moving-root',moving_root)
workflow_output('moving-final',moving_final)
def normalise(value):
    if isinstance(value,dict): return {k:normalise(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [normalise(v) for v in value]
    if isinstance(value,str): return identities.get(value,value)
    return value
if sources()!=before:
    raise AssertionError('source changed during benchmark')
np.savez_compressed(args.output.with_suffix('.npz'),**arrays)
write(args.output,dict(schema='atlas.w11-early-worker.v1',status='PASS',seconds=seconds,
    benchmark_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    source_sha256=before,scientific_outputs=normalise(raw),raw_descriptors=raw,
    derived_identity_map=identities,
    identity_policy='Only explicitly collected source-execution and transitive sample/forcing/workflow/W03/surface/W04-plan identities are substituted for cross-version comparison. All complete array bytes, dtype/shape, remaining descriptors, policies, accounts and scientific identities are exact. Cold/prepared/identical routes additionally match full raw identities within each source version.'))
print(args.output.name,json.dumps(seconds),flush=True)
