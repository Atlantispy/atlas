"""Reuse immutable R3-bound R2 persistence primitives; never import R3 capture.

Both predecessor release indices and source closures are checked on every
dependency verification. This module owns no output or authority directory.
"""
import builtins
import hashlib
import json
from pathlib import Path
import stat
import sys
import types
import uuid

import r3_bindings


_HERE = Path(__file__).resolve().parent
_R2 = _HERE.parent/'terrain_model_r2'
_R2_INDEX = _HERE.parents[1]/'outputs/terrain-model-r2/reference-r2-03/REFERENCE_VERIFICATION.json'
_R2_INDEX_SHA256 = '7eea0a8f30e64c34025330e55a667d4d6a7a1f589dc75f1c5c7067daf89bf1ba'
_R2_NAMES = ('core.py','workflow.py','materials.py','constructive.py','water.py',
             'basin_topology.py','NUMERICAL_CONTRACT.json','fixtures.py')


def _read_checked(path, expected, size=None):
    path = Path(path).absolute()
    for item in (path,*path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('linked/reparse predecessor source')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 16*1024*1024:
        raise ValueError('bounded singly-linked predecessor source required')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected or (size is not None and len(raw) != size):
        raise ValueError('captured predecessor source mismatch: '+path.name)
    return raw


_R2_EXPECTED = {row['name']:row for row in json.loads(
    _read_checked(_R2_INDEX,_R2_INDEX_SHA256))['implementation']}
_R2_RAW = {name:_read_checked(_R2/name,_R2_EXPECTED[name]['sha256'],_R2_EXPECTED[name]['bytes'])
           for name in _R2_NAMES}
_R2_MODULES = {}
_R2_NAMESPACE = '_r5_exact_r2_'+uuid.uuid4().hex+'_'


def _load_r2(name):
    if name in _R2_MODULES:
        return _R2_MODULES[name]
    filename = name+'.py';raw = _R2_RAW[filename];path = _R2/filename
    if _read_checked(path,_R2_EXPECTED[filename]['sha256']) != raw:
        raise ValueError('R2 source changed before private compilation')
    module = types.ModuleType(_R2_NAMESPACE+name);module.__file__ = str(path)
    _R2_MODULES[name] = module;sys.modules[module.__name__] = module
    def bound_import(request,globals=None,locals=None,fromlist=(),level=0):
        if level == 0 and request+'.py' in _R2_RAW:
            return _load_r2(request)
        return builtins.__import__(request,globals,locals,fromlist,level)
    module.__dict__['__builtins__'] = {**vars(builtins),'__import__':bound_import}
    try:
        exec(compile(raw,str(path),'exec',dont_inherit=True,optimize=0),module.__dict__)
        if _read_checked(path,_R2_EXPECTED[filename]['sha256']) != raw:
            raise ValueError('R2 source changed during private compilation')
    except BaseException:
        _R2_MODULES.pop(name,None)
        if sys.modules.get(module.__name__) is module:
            del sys.modules[module.__name__]
        raise
    return module


def _verify_r2():
    _read_checked(_R2_INDEX,_R2_INDEX_SHA256)
    pins = []
    for name,raw in _R2_RAW.items():
        actual = _read_checked(_R2/name,_R2_EXPECTED[name]['sha256'],len(raw))
        if actual != raw:
            raise ValueError('R2 captured source bytes changed')
        pins.append({'name':'R2/'+name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    for module in _R2_MODULES.values():
        if sys.modules.get(module.__name__) is not module:
            raise ValueError('private predecessor module identity changed')
    core = _R2_MODULES.get('core')
    if core is not None and core.CONTRACT != json.loads(_R2_RAW['NUMERICAL_CONTRACT.json']):
        raise ValueError('executed R2 contract differs from captured source')
    return pins


# Do not execute the preserved R3 r2_io path loader: it admits bare same-named
# R2 modules and timestamp-valid bytecode. The old index/records remain bound,
# while all six actual dependencies execute only captured hash-pinned bytes.
io = _load_r2('workflow')
_r3_io = types.SimpleNamespace(INDEX=_R2_INDEX,INDEX_SHA256=_R2_INDEX_SHA256,
                               io=io,verify_dependencies=_verify_r2)


def _receipt_pin(path, expected, name):
    data = io.read_bytes(path)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError('frozen predecessor release identity changed: '+name)
    return {'name':name, 'bytes':len(data), 'sha256':actual}


def verify_dependencies():
    here = Path(__file__).resolve().parent
    prior = io.parse_json(io.read_bytes(here/'R4_REPAIRED_PREDECESSOR.json'))
    if (prior.get('schema') != 'diadem.terrain.r5.predecessor.v1'
            or prior.get('source_directory') != '../terrain_model_r4_repair_r1'
            or prior.get('physical_acceptance') is not False
            or prior.get('production_authorised') is not False):
        raise ValueError('R5 repaired predecessor manifest differs')
    directory = io.unlinked(here/prior['source_directory'])
    if sorted(p.name for p in directory.iterdir() if p.is_file()) != sorted(row['name'] for row in prior['files']):
        raise ValueError('repaired R4 predecessor file inventory changed')
    r4_files = []
    for row in prior['files']:
        if Path(row['name']).name != row['name']:
            raise ValueError('predecessor file must be a direct child')
        actual = _receipt_pin(directory/row['name'],row['sha256'],'R4-repaired/'+row['name'])
        if actual['bytes'] != row['bytes']:
            raise ValueError('repaired R4 predecessor size changed')
        r4_files.append(actual)
    r4_receipt = _receipt_pin(here/prior['receipt_path'],prior['receipt_sha256'],
                             'R4-repaired/RECEIPT.json')
    r3_receipt = _receipt_pin(r3_bindings.INDEX, r3_bindings.INDEX_SHA256,
                             'R3/REFERENCE_VERIFICATION.json')
    r2_receipt = _receipt_pin(_r3_io.INDEX, _r3_io.INDEX_SHA256,
                             'R2/REFERENCE_VERIFICATION.json')
    closure = r3_bindings.verify_predecessor()
    r3_files = [{'name':'R3/'+name, **row} for name,row in sorted(closure.items())]
    return [r4_receipt,*r4_files,r3_receipt,r2_receipt,*r3_files,*_r3_io.verify_dependencies()]


verify_dependencies()
