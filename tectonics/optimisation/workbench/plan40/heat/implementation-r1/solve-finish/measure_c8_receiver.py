"""Prepared actual C8 receiver comparison. Benchmark requires external queue GO."""
if not __debug__:
    raise RuntimeError('Normal Python required')
import argparse
from dataclasses import fields,is_dataclass
from decimal import Decimal
from hashlib import sha256
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType

for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
MAP_SHA='1d1e2c79fe7825e276e2a33f2d5c18fe3157da8ef4b41ab0c3c347bca9295fcf'
PINS={
 'private_heat_interval_assembly_kernel_plan40b_c8_r1':'248afad46838af857c1170c3083b7a0558fb2c85921e54b9011f3b024816d7f5',
 'private_heat_interval_inventory_plan40b_c8_r1':'28d3bf9c604309e402d4e979ef3bba07d5ff78900038af53bf862cbb0a1672a0',
 'private_heat_interval_assessment_plan40b_c8_r1':'3347757f84789019b7b326de293be6617aa817c09efa6682c426f1876742af33',
 'private_heat_interval_inventory_plan40b_reference_r1':'52ed881ae42706e506084f26ff281d3089327628d254b1308fe92b249b78da06',
 'private_heat_interval_assessment_plan40b_reference_r1':'f9be5f96f5c374716bca1ff0ca08789e061e6217bb6dd4f0eb3504f96da07d91'}

def require(condition,message):
    if not condition:raise RuntimeError(message)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--smoke',action='store_true')
    mode.add_argument('--benchmark',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    require(not args.output.exists(),'Output must be new')
    if args.benchmark:require(bool(os.environ.get('RUNQ_TICKET_GIB')),'External queue admission required; no timing executed')
    root=Path(__file__).resolve().parent;repo=args.repo.resolve()
    mapping=repo/'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
    require(sha256(mapping.read_bytes()).hexdigest()==MAP_SHA,'Selected map changed')
    entries={Path(e['member']).name:e for e in json.loads(mapping.read_bytes())['entries']}
    sources={}
    def selected(name):
        entry=entries[name];path=repo/entry['public_path']
        require(sha256(path.read_bytes()).hexdigest()==entry['public_sha256'],'Selected source changed: '+name)
        sources[entry['public_path']]=entry['public_sha256'];return path
    class SelectedModules(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname in PINS:
                target_path=root/(fullname+'.py')
                require(sha256(target_path.read_bytes()).hexdigest()==PINS[fullname],'Successor changed')
                return importlib.util.spec_from_file_location(fullname,target_path)
            if fullname.startswith('atlas_tectonics.') or fullname.startswith('private_heat_') or ('.' not in fullname and fullname+'.py' in entries):
                return importlib.util.spec_from_file_location(fullname,selected(fullname.rsplit('.',1)[-1]+'.py'))
            return None
    package=ModuleType('atlas_tectonics');package.__path__=[]
    sys.modules['atlas_tectonics']=package;sys.meta_path.insert(0,SelectedModules())
    import private_heat_interval_assessment_plan40b_reference_r1 as baseline
    import private_heat_interval_assessment_plan40b_c8_r1 as candidate
    from atlas_tectonics.resources import WorkBudget
    G=candidate.A.B._library()
    require(G is not None,'Selected GMP unavailable')
    def verify():
        require(sha256(mapping.read_bytes()).hexdigest()==MAP_SHA,'Selected map drift')
        for name,expected in PINS.items():require(sha256((root/(name+'.py')).read_bytes()).hexdigest()==expected,'Successor drift')
        for relative,expected in sources.items():require(sha256((repo/relative).read_bytes()).hexdigest()==expected,'Consumed source drift')
    def canonical(value):
        if isinstance(value,G.mpq):return ['mpq',int(value.numerator),int(value.denominator)]
        if isinstance(value,Decimal):return ['Decimal',list(value.as_tuple()),str(value)]
        if is_dataclass(value):return [type(value).__name__,{f.name:canonical(getattr(value,f.name)) for f in fields(value)}]
        if isinstance(value,(list,tuple)):return [canonical(v) for v in value]
        if isinstance(value,dict):return {str(k):canonical(v) for k,v in value.items()}
        return value
    def component(module):
        budget=WorkBudget(64*2**20)
        with budget.reserve(2**20,category='c8-fixture-inputs'):
            rows=[dict(face_id='a',owners=((0,1),(1,-1)),ordered_keys=(('cell',0),('cell',1)),
                       bounds={('cell',0):(G.mpq(2),)*2,('cell',1):(G.mpq(-3),)*2}),
                  dict(face_id='b',owners=((1,1),),ordered_keys=(('cell',1),('wall','w')),
                       bounds={('cell',1):(G.mpq(0),)*2,('wall','w'):(G.mpq(2),)*2})]
            boundary={'w':('temperature',1.25)}
            owner=module.assess(rows,2,boundary,witness={'fixture':True},source_bindings={'source':'a'*64},budget=budget)
            try:
                require(budget.reserved_bytes==2**20+owner.accounted_bytes,'Receiver lost native charge')
                output=canonical(owner.value)
            finally:owner.close()
            require(budget.reserved_bytes==2**20,'Owner teardown left a native charge')
            del owner,rows,boundary
        require(budget.reserved_bytes==0,'Fixture input lease not released')
        return output,budget.peak_reserved_bytes
    # Identical warm-up of actual imported routes; all per-call source checks,
    # input admission, inventory derivation and teardown remain inside component.
    verify()
    require(component(baseline)[0]==component(candidate)[0],'Prepared owning routes differ')
    repeats=3 if args.benchmark else 1
    batch=3;samples={key:[] for key in ('baseline','candidate')}
    digests={key:[] for key in samples};peaks={key:[] for key in samples}
    if args.benchmark:
        from time import perf_counter_ns
    for repetition in range(repeats):
        order=('baseline','candidate') if repetition%2==0 else ('candidate','baseline')
        for arm in order:
            module=baseline if arm=='baseline' else candidate
            if args.benchmark:started=perf_counter_ns()
            outputs=[component(module) for _ in range(batch)]
            if args.benchmark:samples[arm].append(perf_counter_ns()-started)
            digests[arm].append(sha256(json.dumps([item[0] for item in outputs],sort_keys=True).encode()).hexdigest())
            peaks[arm].append([item[1] for item in outputs])
    require(len(set(digests['baseline']+digests['candidate']))==1,'Actual receiver output drift')
    verify()
    result=dict(status='PASS',candidate='C8',schema='plan40b-c8-actual-receiver-measurement/v1',
        mode='benchmark' if args.benchmark else 'smoke',script_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        samples_ns=samples,batch=batch,repetitions=repeats,output_digests=digests,accounted_peak_bytes=peaks,
        successor_pins=PINS,sources=sources,source_map_sha256=MAP_SHA,timing_executed=bool(args.benchmark),
        workload={'cells':2,'faces':2,'owner_contributions':6,'budget_limit_bytes':64*2**20,'input_lease_bytes':2**20},
        limits='Actual complete portable reference and C8 r5/r4 receiver routes. Identical public binding changes in both arms; only assembly arithmetic differs. Includes source guards, inputs, native admission/inventory/owners, canonicalisation and release; imports and outer pin scans excluded. Tiny fixture only; no full-heat extrapolation.')
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'status':'PASS','candidate':'C8','mode':result['mode'],'script_sha256':result['script_sha256']}))

if __name__=='__main__':main()
