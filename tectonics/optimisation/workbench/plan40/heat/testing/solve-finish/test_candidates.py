"""Bounded selected-source controls, not production or WorkBudget qualification."""
if not __debug__:
    raise RuntimeError('Optimised execution is unsupported: control assertions are required')

import argparse
import ast
import copy
from concurrent.futures import CancelledError
from contextlib import ExitStack
from dataclasses import dataclass
from decimal import Decimal as D, localcontext, ROUND_HALF_EVEN, getcontext
from fractions import Fraction
from hashlib import sha256
import json
import os
from operator import index
from pathlib import Path
import sys
from types import SimpleNamespace as NS, ModuleType

for _key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[_key] = '1'

BASE = Path(__file__).resolve().parents[2]
ROOT = BASE / 'repo'
MAP = ROOT / 'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
MAP_HASH = '1d1e2c79fe7825e276e2a33f2d5c18fe3157da8ef4b41ab0c3c347bca9295fcf'
SOURCES = {}
ENTRIES = None
SOURCE_TEXT = {}
FUNCTION_TEXT = {}
LOAD_CODE = {}
TEXT_CODE = {}
NODE_CACHE = {}
FRAGMENTS = {}
CACHE_MODE = False

def source(name):
    global ENTRIES
    if CACHE_MODE and name in SOURCE_TEXT:
        return SOURCE_TEXT[name]
    raw = MAP.read_bytes()
    if sha256(raw).hexdigest() != MAP_HASH:
        raise ValueError('Selected source map drift')
    if ENTRIES is None:
        ENTRIES = {Path(e['member']).name: e for e in json.loads(raw)['entries']}
    entry = ENTRIES[name]
    raw = (ROOT / entry['public_path']).read_bytes()
    if sha256(raw).hexdigest() != entry['public_sha256']:
        raise ValueError('Selected source drift: '+name)
    SOURCES[entry['public_path']] = entry['public_sha256']
    SOURCE_TEXT[name]=raw.decode('utf-8')
    return SOURCE_TEXT[name]

def nodes(name, names):
    raw=source(name)
    key=(name,tuple(names))
    if CACHE_MODE and key in NODE_CACHE:return NODE_CACHE[key]
    found = [n for n in ast.parse(raw).body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    assert {n.name for n in found} == set(names)
    NODE_CACHE[key]=found
    return found

def load(name, names, namespace):
    source(name)
    key=(name,tuple(names))
    if key not in LOAD_CODE:
        LOAD_CODE[key]=compile(ast.Module(body=nodes(name,names),type_ignores=[]),name,'exec')
    exec(LOAD_CODE[key],namespace)
    return namespace

def function_text(name, function):
    source(name)
    key=(name,function)
    if key not in FUNCTION_TEXT:FUNCTION_TEXT[key]=ast.unparse(nodes(name,[function])[0])
    return FUNCTION_TEXT[key]

def compile_text(text, namespace):
    if text not in TEXT_CODE:TEXT_CODE[text]=compile(text,'<source-bound-candidate>','exec')
    exec(TEXT_CODE[text],namespace)
    return namespace

def outcome(call):
    try:
        return ('OK', call())
    except Exception as exc:
        if hasattr(exc,'numerical_diagnostics'):
            return ('ERROR',type(exc).__name__,str(exc),canonical(exc.numerical_diagnostics))
        return ('ERROR', type(exc).__name__, str(exc))

def flags(context):
    return tuple(sorted(k.__name__ for k, v in context.flags.items() if v))

def canonical(value):
    if type(value) is D:
        return ('Decimal', tuple(value.as_tuple()), str(value))
    if type(value) is G.mpfr:
        return ('MPFR', G.to_binary(value).hex(), value.rc, value.precision, bool(G.is_signed(value)))
    if type(value) in (G.mpq, Fraction):
        return ('Q', int(value.numerator), int(value.denominator))
    if hasattr(value, '__dataclass_fields__'):
        return (type(value).__name__, canonical(vars(value)))
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if hasattr(value, 'tolist'):
        return canonical(value.tolist())
    return value

def lu_namespace():
    return load('private_heat_mpfr_lu_r1.py', ['_check', '_mp', 'factor', 'solve'],
                dict(G=G, Decimal=D, CancelledError=CancelledError, perf_counter=lambda: 0))

def converter():
    return load('private_heat_rational_decimal_kernel_r1.py', ['_check','_integer','_compare_power','dec'],
                dict(Decimal=D,ROUND_HALF_EVEN=ROUND_HALF_EVEN,getcontext=getcontext,index=index,
                     CancelledError=CancelledError,_library=lambda:G))['dec']

class Owner:
    """Explicit synthetic lifetime seam; no claim of native allocation accounting."""
    def __init__(self, value):
        self.value = value
        self.closed = False
        self.audit = {'factor_entries': sum(map(len, value.get('rows', [])))} if isinstance(value, dict) else {}
        self._workspace = NS(lease=NS(count=4096))
    def __enter__(self):
        if self.closed:
            raise RuntimeError('Expired synthetic owner')
        return self
    def __exit__(self, *args):
        self.closed = True

def high_run(candidate=None, *, support=9, stop=None, bad_solve=False, boundary=None, low=False, dynamic_refusal=False, target='1e-70'):
    lu = lu_namespace()
    events, owners = [], []
    def checkpoint(cancel, observe, stage):
        events.append(stage)
        if stop == len(events):
            raise CancelledError('fixture cancellation')
    class M:
        METADATA_BYTES = 128
        @staticmethod
        def factor(rows, precision, **kwargs):
            owner = Owner(lu['factor'](rows, precision=precision))
            owners.append(owner)
            return owner
        @staticmethod
        def solve(factor, values, **kwargs):
            answer = lu['solve'](factor.value, values)
            if bad_solve:
                with G.context(precision=512):
                    answer = [G.mpfr(0) for _ in values]
            owner = Owner(answer)
            owners.append(owner)
            return owner
    # Only import indirection is injected. The selected _solve, LU, ordering,
    # residual loop and returned diagnostics execute unchanged except candidate.
    rd = ModuleType('private_heat_rational_decimal_r1')
    rd.dec = converter()
    old_module = sys.modules.get(rd.__name__)
    sys.modules[rd.__name__] = rd
    namespace = dict(D=D, perf_counter=lambda: 0, P=NS(_checkpoint=checkpoint), M=M,
                     PRECISION=512, _conversion_shape=lambda v,g:(512,513),
                     _conversion_inventory=lambda *args:8192, _SOURCES={})
    load('private_heat_decimal_sparse_core_r2.py', ['_require_mpfr_context'], namespace)
    text = function_text('private_heat_decimal_sparse_core_r1.py' if low else 'private_heat_decimal_sparse_core_r2.py', '_solve')
    namespace['_checkpoint']=checkpoint
    if candidate == 'C6':
        text = text.replace('dm, data, indices, indptr = ([], [], [], [0])', 'dm, approximate_nnz = [], 0')
        text = text.replace('indices.append(j)\n                    data.append(approximate)', 'approximate_nnz += 1')
        text = text.replace('        indptr.append(len(data))\n', '')
        start = text.index('    approximate = csr_matrix(')
        end = text.index('    k = dict(plan.counts)', start)
        text = text[:start]+'    del wall\n'+text[end:]
        text = text.replace('approximate.nnz', 'approximate_nnz')
        assert 'data.append' not in text
    if candidate == 'C20':
        text = text.replace('    op = [dict(row)', '    shared_zero = D(0)\n    retained_target = None\n    op = [dict(row)')
        text = text.replace('D(0)', 'shared_zero').replace('shared_zero = shared_zero', 'shared_zero = D(0)')
        text = text.replace('        if absolute <= D(target):', '        if retained_target is None:\n            retained_target = D(target)\n        if absolute <= retained_target:')
        text = text.replace('str(sign * value)', 'str(owner_sign(sign, value))')
        namespace['owner_sign'] = lambda sign,value: (value if sign == 1 else value.copy_negate()) if value.is_finite() and not value.is_subnormal() else sign*value
    if candidate == 'C19':
        text=text.replace('    fluxes = []','    boundary_cache = {}\n    fluxes = []')
        text=text.replace('D.from_float(float(boundary[key][1]))','boundary_value(boundary_cache, key, boundary[key][1])')
        def boundary_value(cache,key,raw):
            previous=cache.get(key)
            if type(raw) is float and previous is not None and previous[0] is raw:
                return previous[1]
            value=D.from_float(float(raw))
            if type(raw) is float:cache[key]=(raw,value)
            return value
        namespace['boundary_value']=boundary_value
    compile_text(text, namespace)
    system = NS(operator=(((0,D('1.25')),(1,D('-0.125'))), ((0,D('-0.125')),(1,D('1.5')),(2,D('-0.125'))), ((1,D('-0.125')),(2,D('1.25')))),
                wall=(D(0),)*3, rows=(NS(weights=((('cell',0),D('0.25')),(('cell',1),D('-0.25'))), owners=((0,1),(1,-1))),
                NS(weights=((('wall','w'),D('0.125')),), owners=((2,1),)),
                NS(weights=((('wall','w'),D('0.25')),), owners=((2,1),)),
                NS(weights=((('wall','w'),D('-0.125')),), owners=((2,-1),))), exact_operator_nnz=7, source_bindings=(), witness_json='{}')
    dynamic = NS(lease=NS(count=0))
    def resize(charge):
        if dynamic_refusal:raise MemoryError('synthetic dynamic conversion refusal')
        dynamic.lease.count=charge
    dynamic.resize_before_allocation_or_after_drop = resize
    with ExitStack() as stack, localcontext() as context:
        context.prec, context.rounding = 80, ROUND_HALF_EVEN
        context.clear_flags()
        try:
            if low:
                kwargs=dict(plan=NS(other_live_bytes=0,total_bytes=16384),workspace=NS(stack=stack),
                            resources=NS(audit_sparse_input=lambda *a,**k:None,audit_factor=lambda *a,**k:{'fixture':True}),cancel=None,observe=None)
            else:
                kwargs=dict(budget=None,plan=NS(counts=(('system_support_bound',support),),inventory=NS(total=lambda:16384)),components=(),
                            workspace=NS(stack=stack,lease=NS(count=16384)),dynamic=dynamic,resources=NS(R=None),G=G,cancel=None,observe=None)
            result = outcome(lambda: namespace['_solve'](system,[2.,3.,4.],[1.,1.,1.],0.125,[0.,0.,0.],
                {'w':('temperature',0.1)} if boundary is None else boundary, target, **kwargs))
            observed_flags = flags(context)
        finally:
            if old_module is None:
                sys.modules.pop(rd.__name__, None)
            else:
                sys.modules[rd.__name__] = old_module
    assert all(owner.closed for owner in owners)
    return canonical(result), events, observed_flags, len(owners)

def test_c6():
    cases = []
    for kwargs in ({}, {'support':6}, {'bad_solve':True}, {'boundary':{}}, {'stop':2}, {'stop':8}, {'stop':17},{'dynamic_refusal':True}):
        baseline, candidate = high_run(**kwargs), high_run('C6',**kwargs)
        assert baseline == candidate
        cases.append({'parameters':kwargs,'outcome':baseline[0][0], 'checkpoints':len(baseline[1])})
    assert cases[0]['outcome'] == 'OK' and cases[1]['outcome'] == 'ERROR'
    return {'status':'PASS','full_selected_high_solve_cases':cases,'resource_seam':'Synthetic owner/dynamic lease; actual selected guard/sticky converter; original conservative inventory retained, no native admission claim'}

def test_c7():
    lu = lu_namespace()
    matrix = [[(0,D('0')),(2,D('1.3')),(1,D('2.1'))],[(2,D('5.2')),(0,D('4.7')),(1,D('-2.2'))],[(1,D('3.1')),(2,D('0.9')),(0,D('-0.1'))]]
    factor = lu['factor'](matrix,precision=512)
    # Construct once and keep the factor private; arbitrary mutable dict calls
    # deliberately execute the reference. Two tuple refs per off-diagonal.
    frozen = dict(factor,rows=[dict(row) for row in factor['rows']],pivots=list(factor['pivots']))
    lower = [tuple((j,v) for j,v in row.items() if j < i) for i,row in enumerate(frozen['rows'])]
    upper = [tuple((j,v) for j,v in row.items() if j > i) for i,row in enumerate(frozen['rows'])]
    text = function_text('private_heat_mpfr_lu_r1.py','solve')
    text = text.replace('for j, v in row.items() if j < i','for j, v in lower[i]').replace('for j, v in a[i].items() if j > i','for j, v in upper[i]')
    # Return context flags before the local MPFR context exits.
    flag_names = ('underflow','overflow','inexact','invalid','erange','divzero')
    flag_fn = lambda: tuple(getattr(G.get_context(),n) for n in flag_names)
    modified = dict(lu,lower=lower,upper=upper,capture=flag_fn)
    compile_text(text.replace('return b','return b, capture()'), modified)
    reference = dict(lu,capture=flag_fn)
    compile_text(function_text('private_heat_mpfr_lu_r1.py','solve').replace('return b','return b, capture()'),reference)
    cases=0
    for rhs in ([D('1.1'),D('-2.7'),D(0)],[D(0)]*3,[D('1e-30'),D('2.03'),D('-17.333')]):
        assert canonical(reference['solve'](frozen,rhs)) == canonical(modified['solve'](frozen,rhs))
        cases+=1
    for stop in range(1,7):
        results=[]
        for solve in (reference['solve'],modified['solve']):
            count=[0]
            def cancel():
                count[0]+=1
                return count[0]==stop
            results.append(outcome(lambda:solve(frozen,[D(1)]*3,cancel=cancel)))
        assert results[0]==results[1]
    # External factor mutation cannot affect private snapshot; direct mutable
    # calls must fall back, and changing insertion order invalidates a view.
    original = canonical(modified['solve'](frozen,[D(1)]*3))
    factor['rows'][0].clear()
    assert canonical(modified['solve'](frozen,[D(1)]*3)) == original
    token = tuple(tuple(row) for row in frozen['rows'])
    changed = [dict(reversed(tuple(row.items()))) for row in frozen['rows']]
    assert tuple(tuple(row) for row in changed) != token
    assert outcome(lambda:modified['solve'](frozen,[])) == outcome(lambda:reference['solve'](frozen,[]))
    owner=Owner(frozen)
    owner.__exit__()
    assert outcome(owner.__enter__)[0]=='ERROR'
    class Views:
        def __init__(self,admitted):
            self.closed=False;self.admitted=admitted
            self.identity=(tuple(tuple((j,id(v)) for j,v in row.items()) for row in frozen['rows']),tuple(frozen['pivots']),frozen['precision'])
        def solve(self,rhs):
            if self.closed:raise RuntimeError('Expired triangular view owner')
            current=(tuple(tuple((j,id(v)) for j,v in row.items()) for row in frozen['rows']),tuple(frozen['pivots']),frozen['precision'])
            if current!=self.identity:raise RuntimeError('Factor mutation invalidated triangular views')
            return (modified if self.admitted else reference)['solve'](frozen,rhs)
        def close(self):self.closed=True
    viewed,fallback=Views(True),Views(False)
    assert canonical(viewed.solve([D(1)]*3))==canonical(fallback.solve([D(1)]*3))
    viewed.close()
    assert outcome(lambda:viewed.solve([D(1)]*3))[0]=='ERROR'
    stale=Views(True)
    frozen['pivots'][0]=0
    assert outcome(lambda:stale.solve([D(1)]*3))[0]=='ERROR'
    frozen['pivots'][0]=1
    return {'status':'PASS','rhs_cases':cases,'cancellation_positions':6,'pivot_order':frozen['pivots'],
            'off_diagonal_entries_retained':sum(map(len,lower))+sum(map(len,upper)),
            'lifetime_mutation_checks':7,'optional_storage_fallback':True,'resource_seam':'Views counted, not natively admitted. Synthetic view owner enforces expiry and factor/pivot/order identity, with optional-storage reference fallback; production private immutable factor owner still required.'}

def assembly_namespace():
    b=dict(Q=Fraction,D=D,localcontext=localcontext,ROUND_HALF_EVEN=ROUND_HALF_EVEN,
           CancelledError=CancelledError,dataclass=dataclass,json=json)
    load('private_heat_interval_assembly_kernel_r1.py',['UnresolvedRounding','CertifiedFace','CertifiedAssembly','_q','_dec','_check','context_signature','_boundary_signature','_rounded','_scale','_add'],b)
    ns=dict(B=NS(**b),CertifiedFace=b['CertifiedFace'],CertifiedAssembly=b['CertifiedAssembly'],
            UnresolvedRounding=b['UnresolvedRounding'],dataclass=dataclass,json=json,localcontext=localcontext,ROUND_HALF_EVEN=ROUND_HALF_EVEN)
    # Actual r2 rounding uses selected converter. Resolve its standalone
    # kernel rather than importing production/source-pinned package graphs.
    ns['dec']=converter()
    load('private_heat_interval_assembly_kernel_r2.py',['Contribution','AmbiguousAggregate','RefinementRequired','_rounded','_assemble'],ns)
    return ns

def row(fid,owners,keys,values):
    return dict(face_id=fid,owners=owners,ordered_keys=keys,bounds={key:(G.mpq(value),G.mpq(value)) for key,value in zip(keys,values,strict=True)})

def test_c8():
    rows=[row('a',((0,1),(1,-1)),(('cell',0),('cell',1)),(2,-3)),row('b',((1,1),),(('cell',1),('wall','w')),(0,2))]
    tiny=G.mpq(1,10**100)
    ambiguous=[row('p',((0,1),),(('cell',0),),(1,)),row('m',((0,1),),(('cell',0),),(-1,))]
    ambiguous[0]['bounds'][('cell',0)]=(G.mpq(1),G.mpq(1)+tiny)
    ambiguous[1]['bounds'][('cell',0)]=(-G.mpq(1),-G.mpq(1)+tiny)
    records=[]
    for candidate in (False,True):
        ns=assembly_namespace()
        if candidate:
            text=function_text('private_heat_interval_assembly_kernel_r2.py','_assemble')
            text=text.replace('contribution = B._scale(bounds, sign)','contribution = bounds if sign == 1 else (-bounds[1], -bounds[0])')
            compile_text(text,ns)
        trace=[]
        old_check=ns['B']._check
        ns['B']._check=lambda cancel:(trace.append(1),old_check(cancel))[1]
        values=[]
        for fixture in (rows,[dict(rows[0],owners=((0,1),(1,1)))],[dict(rows[0],bounds={('cell',0):(G.mpq(3),G.mpq(2)),('cell',1):(G.mpq(0),G.mpq(0))})],ambiguous):
            values.append(canonical(outcome(lambda:ns['_assemble'](fixture,2,{'w':('temperature',1.25)},witness={'fixture':1},source_bindings={'s':'a'*64},cancel=None,gmp=G,collect=True))))
        for stop in (1,10):
            calls=[0]
            def cancel():calls[0]+=1;return calls[0]==stop
            values.append(canonical(outcome(lambda:ns['_assemble'](rows,2,{'w':('temperature',1.25)},witness={'fixture':1},source_bindings={'s':'a'*64},cancel=cancel,gmp=G,collect=True))))
            assert values[-1][0]=='ERROR'
        records.append((values,len(trace)))
    assert records[0]==records[1] and records[0][0][0][0]=='OK'
    assert records[0][0][3][0]=='OK' and records[0][0][3][1][0]=='RefinementRequired'
    return {'status':'PASS','complete_assemble_cases':6,'aggregate_refinement_and_contributors':True,'checkpoints':records[0][1],'resource_seam':'No retained cache; actual selected r2 rounding/converter and Contribution records/cell owners preserved. Native diagnostic inventory not changed or qualified.'}

class Arena:
    """Instrumented GMP arithmetic/array arena; synthetic resource units only."""
    def __init__(self, stop=None, limit=100000):
        self.G=G; self.arrays=[]; self.trace=[]; self.stop=stop; self.limit=limit; self.peak=0; self.checks=0
    def check(self):
        self.trace.append(('check',))
        self.checks+=1
        if self.checks==self.stop:
            raise CancelledError('arena fixture cancellation')
    def array(self,n):
        self.check()
        if sum(len(v[1]) for v in self.arrays)+n>self.limit:
            raise MemoryError('synthetic retained slot bound')
        result=(len(self.arrays),[None]*n); self.arrays.append(result)
        self.peak=max(self.peak,sum(len(v[1]) for v in self.arrays))
        return result
    def put(self,array,i,value): array[1][i]=value
    def op(self,name,a,b):
        self.guard(name,a,b)
        return {'add':lambda:a+b,'subtract':lambda:a-b,'multiply':lambda:a*b,'divide':lambda:a/b}[name]()
    def guard(self,name,a,b):
        self.check(); self.trace.append((name,canonical(a),canonical(b)))
    def public(self,x): return float(x)
    def represented(self,x): return G.mpq(x)
    def equal(self,a,b): self.check(); return a==b
    def less(self,a,b): self.check(); return a<b
    def minimum(self,a,b): return a if self.less(a,b) else b
    def maximum(self,values): return max(values)
    def absolute(self,v): return abs(v)
    def copy(self,values):
        values=list(values); arr=self.array(len(values)); arr[1][:]=values; return arr
    def drop_to(self,mark): del self.arrays[mark:]
    def settle(self,*args): pass
    def bounds(self,energies,cap,bounds):
        passed=all(bounds[0]<=e/c<=bounds[1] for e,c in zip(energies,cap,strict=True))
        return dict(exact_pass=passed,actual_public_pass=passed)

def test_c9(arm=None):
    issue=nodes('private_heat_finish_issue_owned_r4.py',['_issue'])[0]
    begin=next(i for i,n in enumerate(issue.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='loaded')
    end=next(i for i,n in enumerate(issue.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='public_residual')
    if 'C9' not in FRAGMENTS:FRAGMENTS['C9']=ast.unparse(ast.Module(body=issue.body[begin:end+1],type_ignores=[]))
    text=FRAGMENTS['C9']
    candidate=text.replace('for f in exterior - set(fixed):','load_cache.capture(old, source, loaded[1])\nfor f in exterior - set(fixed):',1)
    candidate=candidate.replace("ar.put(load, i, ar.op('add', e, s))", "ar.put(load, i, load_cache.add(ar, i, e, s))")
    class LoadCache:
        def __init__(self,admit):self.saved=None;self.admit=admit;self.peak=0;self.additions=0
        def capture(self,old,src,base):
            # Separately pre-admitted optional capacity; no native arena gate
            # is moved or replaced. Three retained references per cell.
            if not self.admit:return
            self.saved=tuple(zip(old,src,base,strict=True));self.peak=3*len(base)
        def add(self,ar,i,e,s):
            ar.guard('add',e,s)
            if self.saved is not None:
                a,b,value=self.saved[i]
                if a is e and b is s:return value
            self.additions+=1
            return e+s
    method=next(n for n in nodes('private_heat_finish_issue_owned_r4.py',['_IssueArithmetic'])[0].body if isinstance(n,ast.FunctionDef) and n.name=='loaded_residual')
    ns={};exec(compile(ast.Module(body=[method],type_ignores=[]),'selected-issue-residual','exec'),ns)
    Arena.loaded_residual=ns['loaded_residual']
    results=[]
    for debit,admit,stop,limit in ((G.mpq(0),True,None,100000),(G.mpq(1,4),True,None,100000),
                                  (G.mpq(1,4),False,None,100000),(G.mpq(1,4),True,12,100000),
                                  (G.mpq(1,4),True,None,5)):
        if arm is not None and (debit!=G.mpq(1,4) or not admit or stop is not None or limit!=100000):continue
        records=[]
        for code in ((text,candidate) if arm is None else (candidate if arm=='candidate' else text,)):
            ar=Arena(stop=stop,limit=limit);cache=LoadCache(admit); old=[G.mpq(2),G.mpq(3)]; src=[G.mpq(1,4),G.mpq(1,4)]
            new=[old[0]+src[0]-debit,old[1]+src[1]]; faces=[(0,None,debit)]
            env=dict(ar=ar,load_cache=cache,old=old,source=src,cap=[G.mpq(1)]*2,new=new,faces=faces,exterior={0},fixed={},
                     temperatures=list(map(float,new)),stocks=list(map(float,new)),retained=[G.mpq(0)]*2,target=G.mpq(1))
            result=outcome(lambda:compile_text(code,env))
            if stop is not None or limit==5:assert result[0]=='ERROR'
            if result[0]=='OK':
                assert env['load'][1] is not env['loaded'][1]
                result=canonical([env[k] for k in ('bounds','exact_residual','public_residual')]+[env['load'][1],env['loaded'][1]])
            records.append((result,ar.peak,ar.trace,cache.peak,cache.additions))
        if arm is not None:return records[0][0]
        assert records[0][:3]==records[1][:3]
        results.append({'debit':str(debit),'optional_storage':admit,'cancel_at':stop,'arena_slot_limit':limit,
                        'peak_synthetic_slots':records[0][1],'optional_retained_references':records[1][3],
                        'second_native_adds':records[1][4]})
    cache=LoadCache(True);a,b=G.mpq(2),G.mpq(1,4);cache.capture([a],[b],[a+b]);ar=Arena()
    changed=G.mpq(3)
    assert cache.add(ar,0,changed,b)==changed+b and cache.additions==1
    return {'status':'PASS','actual_issue_audit_cases':results,'operand_replacement_fallback':True,
            'rejected_variant':'Attempt-1/2 numerical pass moved source load allocation earlier; superseded by optional retained base at first original use with both original arrays/admissions kept.',
            'resource_seam':'Synthetic separate pre-admitted 3n-reference cache, fallback if absent; native optional-owner integration remains unimplemented. Original array/check/operation-admission trace is now equal in fixtures.'}

def test_c18(arm=None):
    finish=load('private_heat_finish_arithmetic_r1.py',['rational','paired_global_balance'],dict(Q=Fraction,exact_library=lambda:G,CancelledError=CancelledError))
    low=load('private_heat_low_solver_kernel_r5.py',['_residual'],{})
    solve=nodes('private_heat_low_solver_kernel_r5.py',['_solve'])[0]
    def assigned(n): return ast.unparse(n.targets[0]) if isinstance(n,ast.Assign) else ''
    start=next(i for i,n in enumerate(solve.body) if assigned(n)=='public_balance')
    end=next(i for i,n in enumerate(solve.body) if assigned(n)=='relative')
    if 'C18' not in FRAGMENTS:FRAGMENTS['C18']=ast.unparse(ast.Module(body=solve.body[start:end+1],type_ignores=[]))
    text=FRAGMENTS['C18']
    candidate='public_exact = list(map(Q, public_energy))\n'+text.replace('list(map(Q, public_energy))','public_exact').replace('map(Q, public_energy)','public_exact')
    results=[]
    for public in ([0.,-0.,1.25,-2.5],[1e-300,1e300,.1]):
        for stop in (None,1,3,len(public)+3):
            if arm is not None and (stop is not None or len(public)!=4):continue
            records=[]
            for code in ((text,candidate) if arm is None else (candidate if arm=='candidate' else text,)):
                calls=[0]; checks=[0]
                def q(v): calls[0]+=1; return Fraction(v)
                def cancel(): checks[0]+=1; return checks[0]==stop
                env=dict(Q=q,A=NS(**finish),_residual=low['_residual'],public_energy=list(public),faces=[(0,1,Fraction(1,7)),(len(public)-1,None,Fraction(-2,3))],load=[Fraction(v)-Fraction(1,9) for v in public],delta=Fraction(1,2),src=[Fraction(1,3)]*len(public),e0=list(map(Fraction,public)),cancel=cancel)
                result=outcome(lambda:compile_text(code,env))
                if result[0]=='OK': result=canonical([env[k] for k in ('public_balance','global_balance','scale','relative')])
                records.append((result,checks[0],calls[0]))
            if arm is not None:return records[0][0]
            assert records[0][:2]==records[1][:2]
            if stop is None: assert records[0][2]-records[1][2]==2*len(public)
            results.append({'cells':len(public),'cancel_at':stop,'q_calls':[r[2] for r in records]})
    return {'status':'PASS','actual_audit_cases':results,'resource_seam':'One retained immutable Fraction vector n slots; selected ledger reserves 4n. Native owner layout/traceback charge not implemented.'}

def test_c19():
    rows=[row(str(i),((0,1),(1,-1)),(('wall','w'),),(1,)) for i in range(3)]
    class Mapping(dict):
        def __init__(self,sequence): super().__init__(w=('temperature',sequence[0])); self.sequence=sequence; self.reads=0
        def __getitem__(self,key):
            raw=self.sequence[min(self.reads,len(self.sequence)-1)]; self.reads+=1
            return ('temperature',raw)
    text=function_text('private_heat_interval_assembly_kernel_r2.py','_assemble')
    candidate=text.replace("B._q(boundary[index][1], gmp)","cached_boundary(index, boundary[index][1], gmp)")
    records=[]
    for available in (True,False):
        for sequence in ([.1]*12,[.1]*5+[-0.]*3+[.2]*4,[D('0.1')]*12):
            pair=[]
            for changed in (False,True):
                local=assembly_namespace(); cache={}; counts=[0]
                def convert(key,raw,gmp):
                    entry=cache.get(key)
                    if available and type(raw) in (float,int,Fraction,G.mpq) and entry is not None and entry[0] is raw:
                        return entry[1]
                    counts[0]+=1; value=local['B']._q(raw,gmp)
                    if available and type(raw) in (float,int,Fraction,G.mpq): cache[key]=(raw,value)
                    return value
                if changed: local['cached_boundary']=convert;compile_text(candidate,local)
                mapping=Mapping(sequence)
                result=canonical(outcome(lambda:local['_assemble'](rows,2,mapping,witness={'fixture':1},source_bindings={'s':'a'*64},cancel=None,gmp=G,collect=True)))
                pair.append((result,mapping.reads,counts[0],len(cache)))
            assert pair[0][:2]==pair[1][:2]
            records.append({'optional_storage':available,'raw_type':type(sequence[0]).__name__,'reads':pair[0][1],'candidate_conversions':pair[1][2],'retained_entries':pair[1][3]})
    numerical=[]
    for low in (False,True):
        for sequence in ([.1]*3,[.1,-0.,.2],[D('0.1')]*3):
            first,second=Mapping(sequence),Mapping(sequence)
            before,after=high_run(boundary=first,low=low),high_run('C19',boundary=second,low=low)
            assert before==after and first.reads==second.reads
            numerical.append({'low':low,'raw_type':type(sequence[0]).__name__,'reads':first.reads})
    return {'status':'PASS','actual_assembly_cases':records,'full_sparse_cases':numerical,'resource_seam':'Optional synthetic one-entry allowance; unavailable storage uses reference. No native entry/replacement-overlap admission claim. All original mapping reads retained.'}

def test_c20():
    rows=[]
    for kwargs in ({},{'bad_solve':True},{'stop':17},{'low':True},{'low':True,'target':'0'},{'low':True,'stop':17}):
        before,after=high_run(**kwargs),high_run('C20',**kwargs)
        assert before==after
        rows.append({'parameters':kwargs,'outcome':before[0][0]})
    signs=0
    for precision,emin,emax in ((80,-999999,999999),(8,-4,4)):
        for literal in ('0','-0','1.23456789','-1.23456789','1e-40','-1e-40'):
            for sign in (-1,1):
                results=[]
                for candidate in (False,True):
                    with localcontext() as context:
                        context.prec,context.rounding,context.Emin,context.Emax=precision,ROUND_HALF_EVEN,emin,emax
                        context.clear_flags()
                        value=D('1.125')*sum((D(literal),),D(0))
                        result=(value if sign==1 else value.copy_negate()) if candidate and value.is_finite() and not value.is_subnormal() else sign*value
                        results.append((canonical(result),flags(context)))
                assert results[0]==results[1]; signs+=1
    return {'status':'PASS','full_selected_sparse_cases':rows,'sign_context_cases':signs,'resource_seam':'Shared zero/target immutable local objects only. Exact str target fixture; unsupported target representations require reference. Actual LOW SuperLU and HIGH MPFR numerical consumers executed.'}

def test_c10(arm=None):
    # Full selected guard and full selected finish orchestration, with explicit
    # injected correction/issue/quadratic primitives. Not a native arena proof.
    arithmetic=load('private_heat_finish_arithmetic_r1.py',['feasible_scalar'],dict(exact_library=lambda:G))
    class Refused(ValueError):
        def __init__(self,message,detail):super().__init__(message);self.detail=detail
    text=function_text('private_heat_closed_owned_r5.py','_guard')
    candidate=text.replace('cert = certificate(theta)', 'states = {}\n        cert = certificate(theta, states)\n        if cert["passed"]:\n            cache.store((*states[theta], cert))',1)
    candidate=candidate.replace('reused = issued.get(theta)', 'reused = issued.get(theta)\n    if reused is None:\n        reused = cache.get(theta)')
    class Cache:
        def __init__(self,admit):self.held=None;self.admit=admit;self.peak=0
        def store(self,item):
            if not self.admit:return
            theta,energy,faces,cert=item
            self.peak=max(self.peak,(len(energy)+len(faces))*2)
            self.held=(theta,tuple(energy),tuple(faces),dict(cert))
        def get(self,theta):return self.held if self.held is not None and self.held[0]==theta else None
        def close(self):self.held=None
    results=[]
    for case,old,low,high in (('interior',[3,1],[2,2],[4,0]),('full',[4,1],[3,2],[4,1]),('zero_only',[2,2],[2,2],[3,1])):
        if arm is not None and case!='interior':continue
        for admit in (True,False):
            if arm is not None and not admit:continue
            records=[]
            for changed in ((False,True) if arm is None else (arm=='candidate',)):
                ar=Arena();cache=Cache(admit);calls=[0]
                def quadratic(ar,old,new,cap):
                    calls[0]+=1
                    val=sum(((b*b-a*a)/(2*c) for a,b,c in zip(old,new,cap,strict=True)),G.mpq(0))
                    return dict(nonincrease=val<=0,exact_change=val)
                ns=dict(A=NS(feasible_scalar=arithmetic['feasible_scalar'],SupplyGuardRefused=Refused),_quadratic=quadratic,cache=cache)
                load('private_heat_closed_owned_r5.py',['_residual','_equal_arrays','_reused_certificate'],ns)
                compile_text(candidate if changed else text,ns)
                oldq,lowq,highq=([G.mpq(x) for x in values] for values in (old,low,high))
                lf=[(0,1,oldq[0]-lowq[0])];hf=[(0,1,oldq[0]-highq[0])]
                guard_owner=[]
                def closed(*args,**kwargs):
                    value=ns['_guard'](ar,*args)
                    owner=Owner(value);owner.inventory={'fixture':True};guard_owner.append(owner);return owner
                correction=Owner((highq,hf,[G.mpq(1)],{'fixture':True}));correction._workspace.arithmetic=ar;correction.inventory={'fixture':True}
                def issue(*args,**kwargs):
                    owner=Owner(canonical(args[:7]));owner.inventory={'fixture':True};return owner
                finish_ns=dict(C=NS(correct=lambda *a,**k:correction),Q=NS(closed_guard=closed,**{k:ns[k] for k in ('_residual','_equal_arrays')}),I=NS(issue=issue),K=NS(_walk=lambda v,c:v),perf_counter=lambda:0)
                load('private_heat_finish_kernel_r11.py',['_run'],finish_ns)
                converted=dict(started=0,target=G.mpq(1),cap=[G.mpq(1)]*2,previous=oldq,source_energy=[G.mpq(0)]*2,load=oldq,low_energy=lowq,low_faces=lf,high_faces=hf,low_pair_defect=0,high_pair_defect=0,face_ids=['f'],fixed={},prescribed={},bounds=(G.mpq(0),G.mpq(5)),bindings={})
                try:
                    with ExitStack() as stack:
                        result=finish_ns['_run'](NS(stack=stack),None,converted,ar.check,None)
                finally:
                    # Both arms retire the adapter globals; the candidate also
                    # drops retained state/proof before returning to the clock.
                    cache.close()
                    finish_ns.clear()
                    ns.clear()
                assert correction.closed and all(o.closed for o in guard_owner)
                records.append((canonical(result),calls[0],cache.peak))
            if arm is not None:return records[0][0]
            assert records[0][0]==records[1][0]
            if case=='interior' and admit:assert records[0][1]-records[1][1]==3
            else:assert records[0][1]==records[1][1]
            results.append({'case':case,'optional_storage':admit,'quadratic_calls':[r[1] for r in records],'cache_replacement_slot_bound':records[1][2]})
    # Actual stale-state guard, including ordering and value mutation.
    ar=Arena(); guard=load('private_heat_closed_owned_r5.py',['_equal_arrays','_reused_certificate'],{})
    held=(G.mpq(1,3),[G.mpq(1),G.mpq(2)],[(0,1,G.mpq(1,7))],{'passed':True})
    stale=0
    for theta,energy,faces in ((G.mpq(1,2),held[1],held[2]),(held[0],[G.mpq(2),G.mpq(1)],held[2]),(held[0],held[1],[(1,0,G.mpq(1,7))]),(held[0],held[1],[(0,1,G.mpq(2,7))])):
        assert outcome(lambda:guard['_reused_certificate'](ar,theta,held,energy,faces))[0]=='ERROR';stale+=1
    return {'status':'PASS','actual_finish_guard_cases':results,'stale_state_refusals':stale,
            'resource_seam':'Synthetic copied-state cache charges replacement overlap; actual quadratic proof, native arena, correction and issuer/codec owners injected. No production resource/cancellation qualification for removed certificate calls.'}

TESTS={'C6':test_c6,'C7':test_c7,'C8':test_c8,'C9':test_c9,'C10':test_c10,'C18':test_c18,'C19':test_c19,'C20':test_c20}

def benchmark_assembly(candidate):
    ns=assembly_namespace()
    cache={}
    rows=[row('a',((0,1),(1,-1)),(('cell',0),('cell',1),('wall','w')),(2,-3,1)),
          row('b',((1,1),),(('cell',1),('wall','w')),(0,2))]
    text=function_text('private_heat_interval_assembly_kernel_r2.py','_assemble')
    if candidate=='C8':
        text=text.replace('contribution = B._scale(bounds, sign)','contribution = bounds if sign == 1 else (-bounds[1], -bounds[0])')
    if candidate=='C19':
        text=text.replace('B._q(boundary[index][1], gmp)','cached_boundary(index, boundary[index][1], gmp)')
        def cached_boundary(key,raw,gmp):
            item=cache.get(key)
            if type(raw) in (float,int,Fraction,G.mpq) and item is not None and item[0] is raw:return item[1]
            value=ns['B']._q(raw,gmp)
            if type(raw) in (float,int,Fraction,G.mpq):cache[key]=(raw,value)
            return value
        ns['cached_boundary']=cached_boundary
    try:
        compile_text(text,ns)
        return canonical(ns['_assemble'](rows,2,{'w':('temperature',.1)},witness={'fixture':1},source_bindings={'s':'a'*64},cancel=None,gmp=G,collect=True))
    finally:
        # Symmetric adapter teardown, including propagated consumer failures.
        cache.clear()
        ns.clear()

def benchmark_lu(candidate):
    lu=lu_namespace()
    matrix=[[(0,D('0')),(2,D('1.3')),(1,D('2.1'))],[(2,D('5.2')),(0,D('4.7')),(1,D('-2.2'))],[(1,D('3.1')),(2,D('0.9')),(0,D('-0.1'))]]
    factors=lu['factor'](matrix,precision=512)
    if candidate:
        lu['lower']=[tuple((j,v) for j,v in row.items() if j<i) for i,row in enumerate(factors['rows'])]
        lu['upper']=[tuple((j,v) for j,v in row.items() if j>i) for i,row in enumerate(factors['rows'])]
        text=function_text('private_heat_mpfr_lu_r1.py','solve').replace('for j, v in row.items() if j < i','for j, v in lower[i]').replace('for j, v in a[i].items() if j > i','for j, v in upper[i]')
        compile_text(text,lu)
    outputs=[canonical(lu['solve'](factors,rhs)) for rhs in ([D('1.1'),D('-2.7'),D(0)],[D(0)]*3,[D('1e-30'),D('2.03'),D('-17.333')])]
    lu.pop('lower',None);lu.pop('upper',None)
    del factors
    return outputs

def benchmark_arm(candidate,arm):
    changed=arm=='candidate'
    if candidate=='C6':return high_run('C6' if changed else None)
    if candidate=='C7':return benchmark_lu(changed)
    if candidate=='C8':return benchmark_assembly('C8' if changed else None)
    if candidate=='C9':return test_c9(arm)
    if candidate=='C10':return test_c10(arm)
    if candidate=='C18':return test_c18(arm)
    if candidate=='C19':return [benchmark_assembly('C19' if changed else None),high_run('C19' if changed else None),high_run('C19' if changed else None,low=True)]
    if candidate=='C20':return [high_run('C20' if changed else None),high_run('C20' if changed else None,low=True)]
    raise ValueError('Unknown candidate')

def prepare_benchmark(selected):
    # Preflight executes each arm once WITHOUT timing and caches immutable
    # verified source/code. Source guards bracket timed batches. Owner/cache
    # setup/release remains in the adapters, as does small adapter overhead.
    for name in selected:
        before=canonical(benchmark_arm(name,'baseline'))
        after=canonical(benchmark_arm(name,'candidate'))
        if before!=after:raise AssertionError('Benchmark arm mismatch: '+name)

def verify_sources():
    if sha256(MAP.read_bytes()).hexdigest()!=MAP_HASH:raise ValueError('Selected source map drift')
    for path,digest in SOURCES.items():
        if sha256((ROOT/path).read_bytes()).hexdigest()!=digest:raise ValueError('Selected source drift: '+path)

def run_benchmark(selected,repeats,batch,queue_id,*,timed=True):
    global CACHE_MODE
    from time import perf_counter_ns
    prepare_benchmark(selected)
    verify_sources()
    CACHE_MODE=True
    results={}
    for name in selected:
        arms={arm:[] for arm in ('baseline','candidate')}
        digests={arm:[] for arm in arms}
        for repetition in range(repeats):
            for arm in (('baseline','candidate') if repetition%2==0 else ('candidate','baseline')):
                started=perf_counter_ns() if timed else None
                outputs=[benchmark_arm(name,arm) for _ in range(batch)]
                elapsed=perf_counter_ns()-started if timed else None
                digest=sha256(json.dumps(canonical(outputs),sort_keys=True).encode()).hexdigest()
                if timed:arms[arm].append(elapsed)
                digests[arm].append(digest)
        if len(set(digests['baseline']+digests['candidate']))!=1:
            raise AssertionError('Benchmark output drift: '+name)
        results[name]={'status':'PASS','samples_ns':arms,'batch':batch,'output_digests':digests,
                       'limitations':'Deterministic tiny source-bound component/consumer adapters; cache/view construction and release plus adapter overhead included. Source validation/compilation outside timed samples. Synthetic owner seams; no full heat extrapolation.'}
    CACHE_MODE=False
    verify_sources()
    return {'queue_id':queue_id,'candidates':results}

def main():
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--correctness',action='store_true')
    mode.add_argument('--benchmark',action='store_true')
    mode.add_argument('--smoke',action='store_true',help='Same cached benchmark arm loop, one pair, no timing collected')
    parser.add_argument('--candidate',choices=list(TESTS),action='append')
    parser.add_argument('--repo',type=Path,help='Selected checkout; required when moved from the private test folder')
    parser.add_argument('--prepare-benchmark',action='store_true',help='Execute both benchmark arms once, without timing')
    parser.add_argument('--queue-id',help='Externally authorised queue job, required for any timed execution')
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--batch',type=int,default=3)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.benchmark and (not args.queue_id or not args.queue_id.startswith('q') or not args.queue_id[1:].isdigit()):
        parser.error('Benchmark execution requires external queue admission and --queue-id qNUMBER; this flag does not itself authorise a run')
    if not 1<=args.repeats<=5 or not 1<=args.batch<=10:
        parser.error('Bounded repeats 1..5 and batch 1..10 required')
    if args.output and args.output.exists():
        parser.error('--output must name a NEW_PATH')
    global G,ROOT,MAP
    if args.repo is not None:
        ROOT=args.repo.resolve();MAP=ROOT/'tectonics/optimisation/workbench/plans19-20/SOURCE-MAP.json'
    import gmpy2 as G
    selected=args.candidate or list(TESTS)
    results={}
    if args.benchmark:
        results=run_benchmark(selected,args.repeats,args.batch,args.queue_id)['candidates']
    elif args.smoke:
        results=run_benchmark(selected,1,1,None,timed=False)['candidates']
    elif args.prepare_benchmark:
        prepare_benchmark(selected)
        results={name:{'status':'PASS','checks':'Both complete benchmark adapter arms executed once; no clock/timing invoked'} for name in selected}
    else:
        for name in selected:
            try:results[name]=TESTS[name]()
            except Exception as exc:
                import traceback
                results[name]={'status':'FAIL','error':type(exc).__name__+': '+str(exc),'traceback':traceback.format_exc()}
    fixture=dict(high_cells=3,high_operator_nnz=7,high_face_rows=4,assembly_cells=2,lu_precision=512,lu_rhs=3,
                 finish_cells=2,finish_search_steps=64,public_audit_cells=[3,4],source_width='binary64 inputs plus exact tiny rationals; public audit includes 1e-300 and 1e300')
    for name,item in results.items():
        item.setdefault('checks',{k:v for k,v in item.items() if k not in ('status','resource_seam','gap','limitations')})
        item.setdefault('limitations',item.get('resource_seam',item.get('gap','Bounded fixture evidence only; not production qualification')))
    result=dict(schema='plan40b-solve-finish-test-r1',mode='benchmark' if args.benchmark else ('smoke' if args.smoke else ('benchmark-preflight' if args.prepare_benchmark else 'correctness')),source_map_sha256=MAP_HASH,
        sources=SOURCES,script_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),runtime={'python':sys.version,'gmpy2':G.version(),'gmp':G.mp_version(),'mpfr':G.mpfr_version()},
        projected_bounds={'processes':1,'native_threads':1,'memory_limit_claim':'Not measured; tiny fixed fixtures projected below 1 GiB','duration':'few minutes maximum, not a timing result'},
        workload=fixture,workload_sha256=sha256(json.dumps(fixture,sort_keys=True).encode()).hexdigest(),
        candidates=results,production_qualification=False,timing_executed=bool(args.benchmark),queue_id=args.queue_id if args.benchmark else None)
    result['status']='PASS' if set(results)==set(TESTS) and all(item.get('status')=='PASS' for item in results.values()) else 'FAIL'
    encoded=json.dumps(result,indent=2)+'\n'
    if args.output:
        with args.output.open('x',encoding='utf-8') as stream:stream.write(encoded)
    print(encoded)
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':
    raise SystemExit(main())
