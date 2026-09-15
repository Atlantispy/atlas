"""Load immutable R3 numerical primitives from verified bytes, without aliases.

No source is modified and R3 imports cannot accidentally select the R4 router.
"""
import builtins
import hashlib
import json
from pathlib import Path
import sys
import types

HERE=Path(__file__).resolve().parent
R3=HERE.parent/'terrain_model_r3'
INDEX=HERE.parents[1]/'outputs/terrain-model-r3/release-r3-01/REFERENCE_VERIFICATION.json'
INDEX_SHA256='d60511fef613e0d72e36cc930a7bf98dfd9791bfec3f807c2c2f32b7dc8916df'
raw=INDEX.read_bytes()
if hashlib.sha256(raw).hexdigest()!=INDEX_SHA256:raise ValueError('frozen R3 release index changed')
EXPECTED=json.loads(raw)['source_snapshot_before_and_after']['r3_source_closure']


def verify_predecessor():
    actual={}
    for path in sorted(R3.iterdir()):
        if path.suffix in {'.py','.json','.md','.ps1'}:
            data=path.read_bytes();actual[path.name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    if actual!=EXPECTED:raise ValueError('frozen R3 source closure changed')
    return actual


def bound_module(name,dependencies=None):
    path=R3/(name+'.py');data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=EXPECTED[path.name]['sha256']:raise ValueError('R3 numerical source mismatch')
    module=types.ModuleType('_terrain_r4_bound_r3_'+name);module.__file__=str(path)
    imports={} if dependencies is None else dependencies
    def import_bound(name,globals=None,locals=None,fromlist=(),level=0):
        if level==0 and name in imports:return imports[name]
        return builtins.__import__(name,globals,locals,fromlist,level)
    module.__dict__['__builtins__']={**vars(builtins),'__import__':import_bound}
    sys.modules[module.__name__]=module
    exec(compile(data,str(path),'exec'),module.__dict__)
    return module


verify_predecessor()
settling=bound_module('settling')
phase_storage=bound_module('phase_storage')
capture=bound_module('capture',{'settling':settling,'phase_storage':phase_storage})
verify_predecessor()
