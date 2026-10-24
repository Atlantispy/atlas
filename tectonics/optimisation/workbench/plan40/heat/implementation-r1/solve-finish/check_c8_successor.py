"""Actual additive C8 module checks against the selected complete predecessor."""
if not __debug__:
    raise RuntimeError('Normal Python required')

import argparse
import ast
from concurrent.futures import CancelledError
from dataclasses import fields, is_dataclass
from decimal import Decimal, localcontext
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

MAP_SHA='1d1e2c79fe7825e276e2a33f2d5c18fe3157da8ef4b41ab0c3c347bca9295fcf'
SUCCESSOR_SHA='248afad46838af857c1170c3083b7a0558fb2c85921e54b9011f3b024816d7f5'


def require(condition,message):
    if not condition:raise RuntimeError(message)


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    require(not args.output.exists(),'Output must be new')
    repo=args.repo.resolve()
    source_map=repo/'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
    require(sha256(source_map.read_bytes()).hexdigest()==MAP_SHA,'Selected map drift')
    entries={Path(e['member']).name:e for e in json.loads(source_map.read_bytes())['entries']}
    sources={}
    def selected(name):
        entry=entries[name];path=repo/entry['public_path']
        require(sha256(path.read_bytes()).hexdigest()==entry['public_sha256'],'Selected source drift: '+name)
        sources[entry['public_path']]=entry['public_sha256']
        return path

    # Load complete selected modules under an isolated package namespace. Do not
    # execute the broad package __init__ or any scientific/worker entry point.
    package=ModuleType('atlas_tectonics')
    package.__path__=[str(selected('exact_arithmetic.py').parent)]
    sys.modules['atlas_tectonics']=package
    load('atlas_tectonics._validation',selected('_validation.py'))
    exact=load('atlas_tectonics.exact_arithmetic',selected('exact_arithmetic.py'))
    G=exact.library()
    require(G is not None,'Selected real GMP backend unavailable')
    for name in ('private_heat_decimal_sparse_core_r1','private_heat_interval_assembly_kernel_r1','private_heat_rational_decimal_kernel_r1'):
        load(name,selected(name+'.py'))
    baseline=load('private_heat_interval_assembly_kernel_r2',selected('private_heat_interval_assembly_kernel_r2.py'))
    successor=Path(__file__).with_name('private_heat_interval_assembly_kernel_plan40b_c8_r1.py')
    require(sha256(successor.read_bytes()).hexdigest()==SUCCESSOR_SHA,'C8 successor drift')
    candidate=load('private_heat_interval_assembly_kernel_plan40b_c8_r1',successor)

    # Complete source equivalence except the documented expression/docstring;
    # this also binds unchanged public wrappers/admission/cleanup definitions.
    before=ast.parse(Path(baseline.__file__).read_text())
    after=ast.parse(successor.read_text())
    before.body.pop(0);after.body.pop(0)
    replacements=0
    for node in ast.walk(before):
        if isinstance(node,ast.Assign) and ast.unparse(node)=='contribution = B._scale(bounds, sign)':
            node.value=ast.parse('bounds if sign == 1 else (-bounds[1], -bounds[0])',mode='eval').body
            replacements+=1
    require(replacements==1 and ast.dump(before)==ast.dump(after),'Unrelated executable source change')

    def canonical(value):
        if isinstance(value,G.mpq):return ['mpq',int(value.numerator),int(value.denominator)]
        if isinstance(value,Decimal):return ['Decimal',list(value.as_tuple()),str(value)]
        if is_dataclass(value):return [type(value).__name__,{f.name:canonical(getattr(value,f.name)) for f in fields(value)}]
        if isinstance(value,(tuple,list)):return [canonical(v) for v in value]
        if isinstance(value,dict):return {str(k):canonical(v) for k,v in value.items()}
        return value
    def row(fid,owners,bounds):
        return dict(face_id=fid,owners=owners,ordered_keys=tuple(bounds),bounds=bounds)
    good=[row('a',((0,1),(1,-1)),{('cell',0):(G.mpq(2),)*2,('cell',1):(G.mpq(-3),)*2}),
          row('b',((1,1),),{('cell',1):(G.mpq(0),)*2,('wall','w'):(G.mpq(2),)*2})]
    tiny=G.mpq(1,10**100)
    ambiguous=[row('p',((0,1),),{('cell',0):(G.mpq(1),1+tiny)}),
               row('m',((0,1),),{('cell',0):(G.mpq(-1),-1+tiny)})]
    wide=[row('wide',((0,1),(1,-1)),{('cell',0):(G.mpq(1,2**2048),)*2,('cell',1):(G.mpq(-7,2**512),)*2})]
    fixtures=[('valid',good),('wide',wide),('ambiguous',ambiguous)]
    for label,owners in [('bad_sign',((0,2),)),('bool_sign',((0,True),)),('same_sign',((0,1),(1,1))),('duplicate_owner',((0,1),(0,-1)))]:
        fixtures.append((label,[dict(good[0],owners=owners)]))
    fixtures.append(('reversed_bounds',[row('bad',((0,1),),{('cell',0):(G.mpq(2),G.mpq(1))})]))
    checks=[]
    def execute(module,rows,collect,stop=None,fail_add=False):
        calls=[0];scales=[0];adds=[0]
        old_check,old_scale,old_add=module.B._check,module.B._scale,module.B._add
        def check(cancel):calls[0]+=1;return old_check(cancel)
        def scale(*a):scales[0]+=1;return old_scale(*a)
        def add(*a):
            adds[0]+=1
            if fail_add and adds[0]==2:raise MemoryError('injected unchanged add failure')
            return old_add(*a)
        module.B._check, module.B._scale,module.B._add=check,scale,add
        cancel=lambda:calls[0]>=stop if stop is not None else False
        try:
            with localcontext() as context:
                context.clear_flags()
                try:
                    value=module._assemble(rows,2,{'w':('temperature',1.25)},witness={'fixture':True},source_bindings={'source':'a'*64},cancel=cancel,gmp=G,collect=collect)
                    outcome=['OK',canonical(value)]
                except (ValueError,CancelledError,MemoryError) as error:
                    outcome=['ERROR',type(error).__name__,str(error)]
                flags=sorted(k.__name__ for k,v in context.flags.items() if v)
            return dict(outcome=outcome,checks=calls[0],scale_calls=scales[0],adds=adds[0],flags=flags)
        finally:
            module.B._check,module.B._scale,module.B._add=old_check,old_scale,old_add
    def compare(name,rows,collect,**kw):
        left,right=execute(baseline,rows,collect,**kw),execute(candidate,rows,collect,**kw)
        scales=[left.pop('scale_calls'),right.pop('scale_calls')]
        require(left==right,'C8 changed result/checks/flags: '+name)
        checks.append(dict(name=name,collect=collect,status='PASS',outcome=left['outcome'][0],checkpoints=left['checks'],scale_calls=scales,
                           digest=sha256(json.dumps(left,sort_keys=True).encode()).hexdigest()))
        return left
    for collect in (False,True):
        for name,rows in fixtures:compare(name,rows,collect)
        for stop in (1,2,10):compare('cancel_'+str(stop),good,collect,stop=stop)
        compare('allocation_failure',good,collect,fail_add=True)
    require(checks[0]['scale_calls']==[6,1],'Expected five eligible cell-owner calls removed')
    for relative,expected in sources.items():require(sha256((repo/relative).read_bytes()).hexdigest()==expected,'Consumed source changed')
    result=dict(schema='plan40b-c8-implementation/v1',status='PASS',successor_sha256=SUCCESSOR_SHA,source_map_sha256=MAP_SHA,
                control_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),sources=sources,checks=checks,
                full_module_import=True,real_selected_gmp_backend=True,unchanged_executable_ast_except_c8=True,
                production_enabled=False,timing_executed=False,
                limits='Actual full assembler body and selected converter/backend tested. Unchanged owned public wrappers are source-identical, not newly qualified native resource integration; later owner/inventory/source closure wiring remains required.')
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'status':'PASS','cases':len(checks),'successor_sha256':SUCCESSOR_SHA}))


if __name__=='__main__':
    main()
