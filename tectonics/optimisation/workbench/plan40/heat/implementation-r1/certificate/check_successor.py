"""Bounded real-import/consumer checks for additive C3; no timings or workers."""
import sys
if not __debug__:
    raise RuntimeError('Normal Python mode required')
import argparse
import gc
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import types

p=argparse.ArgumentParser()
p.add_argument('--repo',type=Path,required=True)
p.add_argument('--controls',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
args=p.parse_args()
if args.output.exists():
    p.error('--output must be new')
import psutil
process=psutil.Process()
process.cpu_affinity(process.cpu_affinity()[:1])
root=Path(__file__).resolve().parent
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
if sha(args.controls)!='0b68ec4a49bbac0d36504271a2eae30e4f753ee2fe28b60b33828ab0f30f3b84':
    raise RuntimeError('control source changed')
spec=importlib.util.spec_from_file_location('accepted_controls',args.controls)
H=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=H
spec.loader.exec_module(H)
delta=json.loads((root/'SOURCE-DELTA.json').read_text())
for name,expected in delta['successors'].items():
    if sha(root/'source/helpers'/name)!=expected:
        raise RuntimeError('successor changed')
# Keep unchanged dependency resolution source-map checked. Ordinary PathFinder
# resolves the two full successor modules before that fallback resolver.
finders=[finder for finder in sys.meta_path if isinstance(finder,H.SourceFinder)]
for finder in finders:
    sys.meta_path.remove(finder)
    sys.meta_path.append(finder)
sys.path.insert(0,str(root/'source/helpers'))
K=importlib.import_module('private_heat_certification_kernel_r1')
CERT=importlib.import_module('private_heat_certification_kernel_r3')
BOUND=importlib.import_module('private_heat_functional_bounds_kernel_r2')
if CERT.K is not K or BOUND.K is not K or BOUND.CERT is not CERT:
    raise RuntimeError('real caller import split')
native=K._h3_module()
if native is None or native._H3_SEAL!=(str((root/'source/helpers/private_heat_compiled_dot_r1.py').resolve()),K._H3_SHA256):
    raise RuntimeError('real loader failed to bind native successor')
H.NATIVE=H.native_module()
checks=[]
for n,precision in [(2,80),(4,320),(20,320)]:
    rows=H.matrix(n)
    rhs=tuple(H.G.mpq(i+1,8) for i in range(n))
    ref=H.kernel(native=True)
    baseline,_=H.solve_case(ref,rows,rhs,precision,physical=True)
    actual,_=H.solve_case(vars(K),rows,rhs,precision,physical=True)
    if actual!=baseline or actual['outcome'][0]!='return':
        raise RuntimeError('complete solve/physical differs '+str(n))
    for position in (1,max(2,len(actual['trace'])//2),len(actual['trace'])):
        b,_=H.solve_case(ref,rows,rhs,precision,position,physical=True)
        c,_=H.solve_case(vars(K),rows,rhs,precision,position,physical=True)
        if b!=c or c['outcome'][0]!='raise':
            raise RuntimeError('cancellation differs')
    checks.append(dict(rank=n,precision=precision,solve_physical_binary_flags_trace='PASS',cancellation='PASS'))

def real_attempt(rows,rhs,cancel_at=None,budget_bytes=256*1024*1024):
    budget=H.WorkBudget(budget_bytes)
    count=0
    def cancel():
        nonlocal count
        count+=1
        return count==cancel_at
    keys=[('cell',i) for i in range(len(rows))]
    evidence=[]
    held_error=None
    try:
        result,reason=CERT._attempt(rows,rhs,keys,keys[:2],H.G.mpq(0),[H.G.mpq(1)]*len(rows),{},
            precision=320,largest_owned_bytes=max(sys.getsizeof(q) for row in rows for q in row),
            budget=budget,cancelled=cancel,audit={},resource_evidence=evidence)
        outcome=('refused',reason) if result is None else ('return',H.sig(result.value))
        if result is not None:
            result.close()
            try:
                result.value
                raise RuntimeError('closed result borrowed')
            except RuntimeError as error:
                if str(error)=='closed result borrowed':
                    raise
    except Exception as error:
        outcome=('raise',type(error).__name__,str(error))
        held_error=error
    held=budget.reserved_bytes
    failure_funded=held_error is not None and held>0
    held_error=None
    gc.collect()
    return dict(outcome=outcome,checks=count,resource_evidence=evidence,after_drop_bytes=budget.reserved_bytes,held_bytes=held,failure_funded=failure_funded)

attempts=[]
for label,rows,cancel_at,limit in [('success',H.matrix(4),None,256*1024*1024),
    ('singular',tuple(tuple(H.G.mpq(0) for j in range(4)) for i in range(4)),None,256*1024*1024),
    ('cancel',H.matrix(4),15,256*1024*1024),('admission',H.matrix(4),None,1)]:
    rhs=tuple(H.G.mpq(i+1,8) for i in range(4))
    baseline,_=H.attempt(H.kernel(native=True),rows,rhs,320,cancel_at=cancel_at,budget_bytes=limit)
    actual=real_attempt(rows,rhs,cancel_at,limit)
    for field in ('outcome','checks','resource_evidence','after_drop_bytes'):
        if actual[field]!=baseline[field]:
            raise RuntimeError('real r3 '+label+' '+field+' differs')
    attempts.append(dict(case=label,status='PASS',after_drop_bytes=actual['after_drop_bytes']))

# Actual pin/fallback loader branches in disposable fixture directories.
faults=root/(args.output.stem+'-loader-fixtures')
faults.mkdir(exist_ok=False)
for label in ('missing','changed','stale-seal'):
    folder=faults/label
    folder.mkdir()
    kernel_path=folder/'private_heat_certification_kernel_r1.py'
    kernel_path.write_bytes((root/'source/helpers/private_heat_certification_kernel_r1.py').read_bytes())
    if label!='missing':
        raw=(root/'source/helpers/private_heat_compiled_dot_r1.py').read_bytes()
        (folder/'private_heat_compiled_dot_r1.py').write_bytes(raw+(b'\n' if label=='changed' else b''))
    spec=importlib.util.spec_from_file_location('fault_'+label.replace('-','_'),kernel_path)
    candidate=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
    old=sys.modules.get(K._H3_NAME)
    if label=='stale-seal':
        sys.modules[K._H3_NAME]=types.SimpleNamespace(_H3_SEAL=('wrong',K._H3_SHA256))
    try:
        try:
            answer=candidate._h3_module()
        except RuntimeError:
            if label=='missing':
                raise
        else:
            if label!='missing' or answer is not None:
                raise RuntimeError('loader fault accepted '+label)
            ref=H.kernel(native=False)
            rows=H.matrix(4)
            rhs=tuple(H.G.mpq(i+1,8) for i in range(4))
            a,_=H.solve_case(ref,rows,rhs,320,physical=True)
            b,_=H.solve_case(vars(candidate),rows,rhs,320,physical=True)
            if a!=b or a['outcome'][0]!='return':
                raise RuntimeError('full Python fallback consumer differs')
    finally:
        sys.modules[K._H3_NAME]=old
result=dict(status='PASS',selected=['C3'],successors=delta['successors'],check_sha256=sha(Path(__file__)),
    real_imports=['certificate r3 -> successor r1','functional bounds r2 -> same r1/r3'],
    complete_consumers=checks,actual_r3_attempts=attempts,loader_faults=['missing fallback','changed bytes refused','stale loaded seal refused'],
    sources=H.SOURCES,limits=['No worker, cold/restart or production binding qualification.','No implementation timing; measurements belong to accepted prototype.'])
args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'status':'PASS','complete_consumers':len(checks),'real_attempts':len(attempts),'loader_faults':3}))
