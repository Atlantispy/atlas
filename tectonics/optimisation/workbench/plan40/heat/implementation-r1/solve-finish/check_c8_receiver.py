"""Actual imported C8 receiver, inventory and native ownership boundary checks."""
if not __debug__:
    raise RuntimeError('Normal Python required')
import argparse
import ast
from concurrent.futures import CancelledError
from dataclasses import fields,is_dataclass
from decimal import Decimal
import gc
from hashlib import sha256
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
from unittest.mock import patch

for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
PINS={
 'private_heat_interval_assembly_kernel_plan40b_c8_r1':'248afad46838af857c1170c3083b7a0558fb2c85921e54b9011f3b024816d7f5',
 'private_heat_interval_inventory_plan40b_c8_r1':'28d3bf9c604309e402d4e979ef3bba07d5ff78900038af53bf862cbb0a1672a0',
 'private_heat_interval_assessment_plan40b_c8_r1':'3347757f84789019b7b326de293be6617aa817c09efa6682c426f1876742af33'}
MAP_SHA='ce77c8f2922e0d8780e241ba9204e775388fa093935968eaee7c577606baaccc'

def require(value,message):
    if not value:raise RuntimeError(message)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    require(not args.output.exists(),'Result must be new')
    root=Path(__file__).resolve().parent;repo=args.repo.resolve()
    map_path=repo/'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
    require(sha256(map_path.read_bytes()).hexdigest()==MAP_SHA,'Selected source map changed')
    entries={Path(e['member']).name:e for e in json.loads(map_path.read_bytes())['entries']}
    consumed={}
    def selected(name):
        e=entries[name];p=repo/e['public_path']
        require(sha256(p.read_bytes()).hexdigest()==e['public_sha256'],'Selected dependency changed: '+name)
        consumed[e['public_path']]=e['public_sha256'];return p
    class SelectedModules(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname in PINS:
                p=root/(fullname+'.py')
                require(sha256(p.read_bytes()).hexdigest()==PINS[fullname],'Successor dependency changed')
                return importlib.util.spec_from_file_location(fullname,p)
            if fullname.startswith('atlas_tectonics.') or fullname.startswith('private_heat_') or ('.' not in fullname and fullname+'.py' in entries):
                return importlib.util.spec_from_file_location(fullname,selected(fullname.rsplit('.',1)[-1]+'.py'))
            return None
    package=ModuleType('atlas_tectonics');package.__path__=[]
    sys.modules['atlas_tectonics']=package
    finder=SelectedModules();sys.meta_path.insert(0,finder)
    import private_heat_interval_assessment_plan40b_c8_r1 as receiver
    import private_heat_interval_assembly_kernel_r2 as baseline
    from atlas_tectonics.resources import WorkBudget,MemoryLimitError
    G=receiver.A.B._library()
    require(G is not None,'Selected actual native arithmetic unavailable')
    receiver._verify_sources(None)

    def functions(path):
        return {n.name:ast.dump(n) for n in ast.parse(path.read_text()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    old_inventory=functions(selected('private_heat_interval_inventory_r4.py'))
    new_inventory=functions(Path(receiver.I.__file__))
    for name in ('derive','AssessmentInventory','_check','_size'):
        require(old_inventory[name]==new_inventory[name],'Inventory arithmetic/accounting changed: '+name)
    old_receiver=functions(selected('private_heat_interval_assembly_kernel_r5.py'))
    new_receiver=functions(Path(receiver.__file__))
    require(old_receiver==new_receiver,'Receiver executable functions changed beyond import/pin wiring')

    def canonical(v):
        if isinstance(v,G.mpq):return ['mpq',int(v.numerator),int(v.denominator)]
        if isinstance(v,Decimal):return ['Decimal',list(v.as_tuple()),str(v)]
        if is_dataclass(v):return [type(v).__name__,{f.name:canonical(getattr(v,f.name)) for f in fields(v)}]
        if isinstance(v,(tuple,list)):return [canonical(x) for x in v]
        if isinstance(v,dict):return {str(k):canonical(x) for k,x in v.items()}
        return v
    def row(fid,owners,coeff):return dict(face_id=fid,owners=owners,ordered_keys=tuple(coeff),bounds=coeff)
    rows=[row('a',((0,1),(1,-1)),{('cell',0):(G.mpq(2),)*2,('cell',1):(G.mpq(-3),)*2}),
          row('b',((1,1),),{('cell',1):(G.mpq(0),)*2,('wall','w'):(G.mpq(2),)*2})]
    boundary={'w':('temperature',1.25)};metadata=dict(witness={'fixture':True},source_bindings={'source':'a'*64})
    def assess(budget,**extra):return receiver.assess(rows,2,boundary,budget=budget,**metadata,**extra)
    checks=[]
    budget=WorkBudget(64*2**20)
    owner=assess(budget)
    expected=baseline._assemble(rows,2,boundary,**metadata,cancel=None,gmp=G,collect=True)
    require(canonical(owner.value)==canonical(expected),'Actual owned receiver numerical output changed')
    require(budget.reserved_bytes==owner.accounted_bytes>0,'Owner charge not retained')
    view=owner.rounded_system(boundary)
    require(view.operator==owner.value.operator,'Actual rounded-system consumer changed')
    del view
    first=owner.accounted_bytes
    later=assess(budget,retained=(owner,))
    require(later.retained_generation_count==1 and budget.reserved_bytes==first+later.accounted_bytes,'Retained generation not charged')
    owner.close()
    require(budget.reserved_bytes==later.accounted_bytes and canonical(later.value)==canonical(expected),'Prior owner close invalidated retained receiver')
    try:owner.value
    except RuntimeError:pass
    else:raise RuntimeError('Closed owner remained usable')
    amount=later.accounted_bytes
    later.close();require(budget.reserved_bytes==0,'Final close leaked reservation')
    checks.append(dict(name='actual_owned_receiver_view_and_retained_generation',status='PASS',first_bytes=first,later_bytes=amount,peak_bytes=budget.peak_reserved_bytes))

    tiny=G.mpq(1,10**100)
    ambiguous=[row('p',((0,1),),{('cell',0):(G.mpq(1),1+tiny)}),row('m',((0,1),),{('cell',0):(G.mpq(-1),-1+tiny)})]
    owner=receiver.assess(ambiguous,2,boundary,budget=budget,**metadata)
    require(type(owner.value) is receiver.RefinementRequired,'Actual refinement owner missing')
    try:owner.rounded_system(boundary)
    except receiver.UnresolvedRounding:pass
    else:raise RuntimeError('Refinement request exposed numerical system')
    owner.close();require(budget.reserved_bytes==0,'Refinement owner close leaked')
    checks.append(dict(name='actual_owned_refinement_refuses_numerical_view',status='PASS'))

    for label,small,extra,expected_type in [('budget_refusal',WorkBudget(1),{},MemoryLimitError),('initial_cancellation',WorkBudget(64*2**20),{'cancel':lambda:True},CancelledError)]:
        try:assess(small,**extra)
        except expected_type:pass
        else:raise RuntimeError('Missing '+label)
        require(small.reserved_bytes==0,'Pre-admission refusal left charge')
        checks.append(dict(name=label,status='PASS'))

    # Fail after genuine receiver admission, then verify the native existing
    # custody rule with a held exception and separately retained traceback.
    caught=None
    with patch.object(receiver.A,'_assemble',side_effect=MemoryError('injected after real receiver admission')):
        try:assess(budget)
        except MemoryError as error:caught=error
    require(caught is not None and budget.reserved_bytes>0,'Failed receiver dropped native charge early')
    charged=budget.reserved_bytes;held_traceback=caught.__traceback__;caught=None
    gc.collect();require(held_traceback is not None and budget.reserved_bytes==charged,'Traceback-only custody lost charge')
    del held_traceback
    gc.collect();require(budget.reserved_bytes==0,'Final traceback drop leaked native charge')
    checks.append(dict(name='native_failure_exception_and_traceback_custody',status='PASS',charged_bytes=charged))

    with tempfile.TemporaryDirectory(dir=root,prefix='c8-source-fault-') as temporary:
        for label,module in [('inventory_pin',receiver.I),('kernel_pin',receiver.A)]:
            changed=Path(temporary)/Path(module.__file__).name
            changed.write_bytes(b'# disposable wrong source\n')
            with patch.object(module,'__file__',str(changed)):
                try:assess(budget)
                except ValueError as error:
                    require('changed' in str(error),'Unexpected source refusal')
                else:raise RuntimeError('Source drift accepted')
            require(budget.reserved_bytes==0,'Source refusal reached/leaked admission')
            checks.append(dict(name=label+'_drift_refusal',status='PASS'))
    receiver._verify_sources(None)
    for path,expected_hash in consumed.items():require(sha256((repo/path).read_bytes()).hexdigest()==expected_hash,'Consumed source changed')
    result=dict(schema='plan40b-c8-receiver/v1',status='PASS',source_map_sha256=MAP_SHA,successor_pins=PINS,
                control_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),sources=consumed,checks=checks,
                actual_native_WorkBudget_and_OwnedWorkspace=True,inventory_formulas_and_receiver_functions_unchanged=True,
                timing_executed=False,workers_launched=False,production_selected=False,
                limits='New selected-public binding and additive owning receiver; not historical private replay, OS allocator proof, full heat dispatch or scientific acceptance.',
                preparation_failures=['First builder invocation refused because its literal map pin omitted one zero; corrected against unchanged selected map before any files were written.',
                  'First receiver import refused missing live_spatial_patch because the focused source loader did not cover selected top-level live helpers; loader extended to exact selected entries without modifying production modules.'])
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'status':'PASS','checks':len(checks),'loaded_selected_files':len(consumed)}))

if __name__=='__main__':main()
