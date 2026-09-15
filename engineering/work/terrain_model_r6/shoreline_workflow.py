"""Bounded synthetic shoreline recipes with independently replayed recovery.

This is a Windows local reference workflow, not physical/production authority.
It calls the shoreline driver, never the prescribed-port capture integrator.
"""
from __future__ import annotations

import argparse
import builtins
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import stat
import sys
import tempfile
import time
import types
import uuid

HERE = Path(__file__).resolve().parent
OUTPUT_ROOT = HERE.parents[1]/'outputs'/'terrain-model-r6-shoreline'
MAX_BYTES = 64*1024*1024
MAX_STEPS = 128
VECTOR_FIELDS = ('runoff_m_year','sediment_k_per_year','rock_k_per_year',
                 'diffusivity_m2_year','incoming_liquid_m3_year','incoming_solid_m3_year')
FORCING_FIELDS = {'steps','dt_years','dx_m','dy_m','external_outlets','connectivity',
                  'cover_scale_m','settling_m_year','basin_settling_m_year',
                  'critical_gradient','erosion_reference_runoff_m_year',*VECTOR_FIELDS}
COUNT_FIELDS = ('trial_calls','trial_cell_evaluations','scalar_rhs_evaluations',
                'closed_event_solver_calls','accepted_substeps','rejected_proposals')


def _path(path):
    path=Path(os.path.abspath(path))
    for p in (*reversed(path.parents),path):
        try:s=p.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:
            raise ValueError('linked/reparse workflow path: '+str(p))
        if p!=path and not stat.S_ISDIR(s.st_mode):raise ValueError('non-directory workflow ancestor')
        if p==path and stat.S_ISREG(s.st_mode) and s.st_nlink!=1:
            raise ValueError('hardlinked workflow file')
    return path


def _read(path):
    path=_path(path);before=path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size>MAX_BYTES:raise ValueError('bounded regular workflow file required')
    def signature(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_nlink,getattr(s,'st_file_attributes',0)
    with path.open('rb') as f:
        if signature(os.fstat(f.fileno()))!=signature(before):raise ValueError('workflow file changed before read')
        raw=f.read(MAX_BYTES+1)
        if signature(os.fstat(f.fileno()))!=signature(before):raise ValueError('workflow file changed during read')
    _path(path)
    if len(raw)>MAX_BYTES or signature(path.lstat())!=signature(before):raise ValueError('workflow file changed/oversized')
    return raw


def _sha(raw):return hashlib.sha256(raw).hexdigest()


def _local_sources():
    return {p.name:_read(p) for p in sorted(HERE.iterdir()) if p.suffix in {'.py','.json','.md'}}


# Capture source bytes BEFORE constructing a private numerical graph. Module
# paths alone would not distinguish stale same-path Python imports from bytes
# subsequently hashed on disk. Only modules requested by imports are executed.
_SOURCE_BYTES=_local_sources()
_MODULES={}
_NAMESPACE='_r6_shoreline_bound_'+uuid.uuid4().hex+'_'


def _load(name):
    if name in _MODULES:return _MODULES[name]
    raw=_SOURCE_BYTES[name+'.py'];module=types.ModuleType(_NAMESPACE+name)
    module.__file__=str(HERE/(name+'.py'));_MODULES[name]=module
    sys.modules[module.__name__]=module
    def bound_import(request,globals=None,locals=None,fromlist=(),level=0):
        if level==0 and request+'.py' in _SOURCE_BYTES and request!='shoreline_workflow':return _load(request)
        return builtins.__import__(request,globals,locals,fromlist,level)
    module.__dict__['__builtins__']={**vars(builtins),'__import__':bound_import}
    exec(compile(raw,module.__file__,'exec',dont_inherit=True,optimize=0),module.__dict__)
    return module


driver=_load('shoreline_driver')
capture=driver.capture
_binding=_load('r4_io')
io=_binding.io


def source_pins():
    return [{'name':name,'bytes':len(raw),'sha256':_sha(raw)} for name,raw in _local_sources().items()]+_binding.verify_dependencies()


LOADED_SOURCE_PINS=[{'name':name,'bytes':len(raw),'sha256':_sha(raw)} for name,raw in _SOURCE_BYTES.items()]+_binding.verify_dependencies()
if source_pins()!=LOADED_SOURCE_PINS:raise ValueError('shoreline sources changed while importing exact bytes')


def validate(recipe):
    io.require_keys(recipe,{'schema','purpose','scenario_id','source_label','state','forcing','limits',
                           'constraints','physical_acceptance','production_authorised'},'shoreline recipe')
    if recipe['schema']!='diadem.terrain.shoreline.recipe.r6' or recipe['purpose']!='SYNTHETIC_ENGINEERING_ONLY':
        raise ValueError('only explicit synthetic R6 shoreline recipes are authorised')
    if recipe['physical_acceptance'] is not False or recipe['production_authorised'] is not False:
        raise ValueError('recipe cannot grant physical or production authority')
    if type(recipe['scenario_id']) is not str or not 1<=len(recipe['scenario_id'])<=128:
        raise ValueError('bounded scenario ID required')
    if type(recipe['source_label']) is not str or not recipe['source_label'].startswith('SYNTHETIC ') or len(recipe['source_label'])>1024:
        raise ValueError('explicit bounded synthetic forcing source required')
    io.require_keys(recipe['limits'],{'max_product_bytes','wall_seconds'},'shoreline limits')
    for name,cap in (('max_product_bytes',MAX_BYTES),('wall_seconds',120)):
        if type(recipe['limits'][name]) is not int or not 1<=recipe['limits'][name]<=cap:raise ValueError('invalid '+name)
    if type(recipe['state']) is not dict:raise ValueError('complete native state object required')
    try:state=capture.CaptureState(**recipe['state'])
    except TypeError as exc:raise ValueError('invalid shoreline state fields') from exc
    if state.size>driver.forced_drying.MAX_NATIVE_CELLS:raise ValueError('driver native-cell envelope exceeded')
    capture.check_controls(state,recipe['constraints'])
    f=recipe['forcing'];io.require_keys(f,FORCING_FIELDS,'shoreline forcing')
    if type(f['steps']) is not int or not 1<=f['steps']<=MAX_STEPS or f['steps']*state.size>2097152:
        raise ValueError('bounded outer-step/checkpoint envelope exceeded')
    for name in ('dt_years','dx_m','dy_m','cover_scale_m'):capture.number(f[name],name,0,True)
    for name in ('settling_m_year','basin_settling_m_year'):capture.number(f[name],name,0)
    for name in VECTOR_FIELDS:capture.vector(f[name],state.size,name,0)
    if f['critical_gradient'] is not None:
        for value in capture.vector(f['critical_gradient'],state.size,'critical gradient',0):
            capture.number(value,'critical gradient',0,True)
    if f['erosion_reference_runoff_m_year'] is not None:
        capture.number(f['erosion_reference_runoff_m_year'],'erosion reference runoff',0,True)
    if any(s and not w for w,s in zip(f['incoming_liquid_m3_year'],f['incoming_solid_m3_year'])):
        raise ValueError('incoming suspension requires same-cell liquid carrier')
    if type(f['connectivity']) is not int or f['connectivity'] not in (4,8):raise ValueError('explicit 4/8 connectivity required')
    outlets=f['external_outlets']
    if type(outlets) is not list or any(type(i) is not int or not 0<=i<state.size for i in outlets) or len(set(outlets))!=len(outlets):
        raise ValueError('unique native external outlets required')
    rows,cols=state.shape
    if any(i//cols not in (0,rows-1) and i%cols not in (0,cols-1) for i in outlets):raise ValueError('external outlets must be native edges')
    if any(a!=f['dx_m']*f['dy_m'] for a in state.cell_area_m2):
        raise ValueError('retained hillslope bridge requires rectangular uniform native area')
    previous=state.time_years
    for i in range(f['steps']):previous=capture.number(state.time_years+(i+1)*f['dt_years'],'outer target',previous,True)
    return state


def _move_new(source,target):
    _path(source);_path(target)
    if os.name!='nt':raise ValueError('atomic local shoreline persistence currently requires Windows')
    win=ctypes.WinDLL('kernel32',use_last_error=True)
    win.MoveFileExW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD]
    win.MoveFileExW.restype=wintypes.BOOL
    if not win.MoveFileExW(str(source),str(target),8):raise ctypes.WinError(ctypes.get_last_error())


def _atomic_new(path,data):
    path=_path(path)
    if path.exists():raise FileExistsError(path)
    # A killed pre-rename write leaves only a sibling temporary, never a
    # truncated checkpoint. It is not admitted as generation evidence.
    fd,name=tempfile.mkstemp(prefix='.shoreline-atomic-',suffix='.tmp',dir=path.parent.parent)
    temporary=Path(name)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        if _read(temporary)!=data:raise ValueError('atomic temporary readback differs')
        _move_new(temporary,path)
        if _read(path)!=data:raise ValueError('atomic product readback differs')
    finally:
        if temporary.exists():_path(temporary).unlink()  # This invocation's exact owned file only.


@contextmanager
def _writer_lock(path):
    _path(path)
    if os.name!='nt':raise ValueError('local shoreline writer lock currently requires Windows')
    win=ctypes.WinDLL('kernel32',use_last_error=True)
    win.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    win.CreateFileW.restype=wintypes.HANDLE
    win.CloseHandle.argtypes=[wintypes.HANDLE];win.CloseHandle.restype=wintypes.BOOL
    handle=win.CreateFileW(str(path),0xC0000000,0,None,4,0x80,None)
    if handle==ctypes.c_void_p(-1).value:raise ValueError('shoreline output writer lock unavailable')
    try:
        _path(path.parent)
        yield
    finally:win.CloseHandle(handle)


def _inventory(directory,allowed,budget):
    _path(directory)
    names={p.name for p in directory.iterdir()}
    if names-allowed:raise ValueError('foreign shoreline product inventory')
    products={name:{'bytes':len(raw),'sha256':_sha(raw)} for name in sorted(names) for raw in [_read(directory/name)]}
    if sum(p['bytes'] for p in products.values())>budget:raise ValueError('shoreline product storage envelope exceeded')
    return products


def _counts(report):
    if type(report) is not dict or report.get('whole_interval_completed') is not True:
        raise ValueError('driver did not complete requested interval')
    if report.get('physical_acceptance') is not False or report.get('production_authorised') is not False:
        raise ValueError('driver cannot promote physical/production authority')
    values=report.get('counts');io.require_keys(values,COUNT_FIELDS,'per-step driver counts')
    if any(type(v) is not int or v<0 for v in values.values()):raise ValueError('invalid per-step driver work counts')
    return values


def run(recipe_path,output,*,resume=False,interrupt_after_step=None,interrupt_at=None):
    started=time.monotonic()
    if type(resume) is not bool:raise ValueError('resume must be Boolean')
    if interrupt_after_step is not None and (type(interrupt_after_step) is not int or not 1<=interrupt_after_step<=MAX_STEPS):raise ValueError('invalid injected checkpoint interruption')
    if interrupt_at not in (None,'after_products','after_receipt'):raise ValueError('invalid injected interruption')
    recipe_path=_path(recipe_path);output=_path(output);allowed=_path(OUTPUT_ROOT)
    if output==allowed or not output.is_relative_to(allowed) or recipe_path.is_relative_to(allowed):
        raise ValueError('output outside bounded R6 shoreline root or contains its recipe')
    raw=_read(recipe_path);recipe=io.parse_json(raw);initial=validate(recipe)
    pins=source_pins()
    if pins!=LOADED_SOURCE_PINS:raise ValueError('shoreline source drift since import; use fresh process')
    identity={'recipe_sha256':_sha(raw),'canonical_recipe_sha256':_sha(io.canonical(recipe)),
              'implementation':pins,'python':sys.version,'platform':platform.platform(),
              'mode':'general_native_shoreline_reference_r6'}
    identity['generation_id']=_sha(io.canonical(identity))
    deadline=started+recipe['limits']['wall_seconds'];budget=recipe['limits']['max_product_bytes']
    output.parent.mkdir(parents=True,exist_ok=True);_path(output.parent)
    count=recipe['forcing']['steps'];names=[f'CHECKPOINT-{i:06d}.json' for i in range(1,count+1)]
    allowed_names={'RECIPE.json','RESULT.json','RECEIPT.json',*names}
    completed=0;last_checkpoint=None;state=initial;completed_counts=dict.fromkeys(COUNT_FIELDS,0);attempt_counts=None
    def current():
        if source_pins()!=pins or _read(recipe_path)!=raw:raise ValueError('shoreline source/recipe drift')
        if time.monotonic()>deadline:raise ValueError('whole shoreline workflow wall-time envelope exceeded')
    with _writer_lock(output.with_name('.'+output.name+'.writer.lock')):
        current();committed=output.exists()
        pending=output.with_name(output.name+'.pending-'+identity['generation_id'][:16])
        peers=list(output.parent.glob(output.name+'.pending-*'))
        if any(p!=pending for p in peers):raise ValueError('partial shoreline belongs to another recipe/source identity')
        if committed:
            if not resume:raise FileExistsError(output)
            if peers:raise ValueError('committed output has an ambiguous pending sibling')
            directory=output
        elif pending.exists():
            if not resume:raise FileExistsError('partial shoreline requires explicit resume')
            directory=_path(pending)
        else:
            if resume:raise FileNotFoundError('no shoreline generation to resume')
            pending.mkdir(exist_ok=False);directory=pending
        _inventory(directory,allowed_names,budget)
        def save(name,value):
            data=io.canonical(value);path=directory/name
            if path.exists():
                if _read(path)!=data:raise ValueError('replayed shoreline product differs: '+name)
            else:
                if committed:raise ValueError('missing committed shoreline product: '+name)
                current();sizes=_inventory(directory,allowed_names,budget)
                if sum(v['bytes'] for v in sizes.values())+len(data)>budget:raise ValueError('shoreline product storage envelope exceeded')
                _atomic_new(path,data)
            if _read(path)!=data:raise ValueError('shoreline product changed at readback')
        try:
            existing={p.name for p in directory.iterdir()}
            checkpoints=[name for name in names if name in existing]
            if checkpoints!=names[:len(checkpoints)]:raise ValueError('noncontiguous shoreline checkpoint prefix')
            if ('RESULT.json' in existing or 'RECEIPT.json' in existing) and len(checkpoints)!=count:
                raise ValueError('terminal shoreline product lacks complete checkpoint prefix')
            if 'RECEIPT.json' in existing and 'RESULT.json' not in existing:raise ValueError('receipt lacks result')
            if existing and 'RECIPE.json' not in existing:raise ValueError('checkpoint prefix lacks recipe')
            save('RECIPE.json',recipe)
            previous=_sha(io.canonical(initial.as_dict()));totals=dict.fromkeys(COUNT_FIELDS,0);step_counts=[]
            for i,name in enumerate(names):
                current();target=initial.time_years+(i+1)*recipe['forcing']['dt_years']
                attempt_counts=None
                kwargs={**recipe['forcing'],'steps':1,'dt_years':target-state.time_years,
                        'wall_seconds':min(120.,deadline-time.monotonic())}
                next_state,diagnostics=driver.advance(state,**kwargs)
                if next_state.time_years!=target:raise ValueError('driver did not reach exact represented outer target')
                capture.check_controls(next_state,recipe['constraints']);counts=_counts(diagnostics)
                attempt_counts=dict(counts)
                totals={key:totals[key]+counts[key] for key in COUNT_FIELDS}
                if (totals['accepted_substeps']>driver.MAX_SUBSTEPS or totals['rejected_proposals']>driver.MAX_REJECTS or
                        totals['trial_cell_evaluations']>driver.MAX_CELL_TRIALS):
                    raise ValueError('aggregate shoreline driver work envelope exceeded')
                checkpoint={'schema':'diadem.terrain.shoreline.checkpoint.r6','generation_id':identity['generation_id'],
                    'previous_state_sha256':previous,'completed_steps':i+1,'target_time_years':target,
                    'state':next_state.as_dict(),'driver_diagnostics':diagnostics,
                    'step_counts':counts,'cumulative_counts':totals}
                save(name,checkpoint)
                loaded=io.parse_json(_read(directory/name))
                if io.canonical(loaded)!=io.canonical(checkpoint):raise ValueError('checkpoint changed before restoration')
                state=capture.CaptureState(**loaded['state']);previous=_sha(io.canonical(state.as_dict()))
                completed=i+1;last_checkpoint=str(directory/name);step_counts.append(dict(counts))
                completed_counts=dict(totals);attempt_counts=None;current()
                if interrupt_after_step is not None and completed>=interrupt_after_step:
                    raise RuntimeError('injected interruption after shoreline checkpoint')
            result={'schema':'diadem.terrain.shoreline.result.r6','generation_id':identity['generation_id'],
                'scenario_id':recipe['scenario_id'],'source_label':recipe['source_label'],
                'state':state.as_dict(),'physical_bed_m':list(state.bed_m),'checkpoints':names,
                'step_counts':step_counts,'counts':totals,'whole_interval_completed':True,
                'model_selection':{
                    'hillslope_law':'LINEAR' if recipe['forcing']['critical_gradient'] is None else 'ROERING_NONLINEAR',
                    'critical_gradient':recipe['forcing']['critical_gradient'],
                    'erosion_forcing_model':('LEGACY_CONTRIBUTING_AREA_FIXED_RUNOFF_PROXY'
                        if recipe['forcing']['erosion_reference_runoff_m_year'] is None else
                        'DISCHARGE_NORMALISED_BY_EXPLICIT_REFERENCE_RUNOFF'),
                    'erosion_reference_runoff_m_year':recipe['forcing']['erosion_reference_runoff_m_year']},
                'physical_acceptance':False,'production_authorised':False,
                'scope':'BOUNDED_SYNTHETIC_SHORELINE_DRIVER_ONLY'}
            save('RESULT.json',result)
            if interrupt_at=='after_products':raise RuntimeError('injected interruption after shoreline products')
            products={name:pin for name,pin in _inventory(directory,allowed_names,budget).items() if name!='RECEIPT.json'}
            receipt={'schema':'diadem.terrain.shoreline.receipt.r6','identity':identity,'products':products,
                     'physical_acceptance':False,'production_authorised':False}
            save('RECEIPT.json',receipt);current()
            actual=_inventory(directory,allowed_names,budget)
            if set(actual)!=allowed_names:raise ValueError('incomplete final shoreline inventory')
            if {name:pin for name,pin in actual.items() if name!='RECEIPT.json'}!=products:
                raise ValueError('shoreline products changed before commit')
            if interrupt_at=='after_receipt':raise RuntimeError('injected interruption after shoreline receipt')
            if not committed:_move_new(directory,output)
            final=_inventory(output,allowed_names,budget)
            if final!=actual:raise ValueError('shoreline committed readback differs')
            current()
            return {'status':'VERIFIED_SHORELINE_REUSE' if committed else 'COMMITTED_SHORELINE_REFERENCE',
                    'generation_id':identity['generation_id'],'output':str(output),'counts':totals,
                    'independent_prefix_replay':True,'production_authorised':False}
        except Exception as exc:
            # Preserve the native exception/certificate. No failed state is
            # adopted, no error is converted to a success receipt.
            exc.shoreline_workflow_failure={'status':'SHORELINE_WORKFLOW_NOT_COMPLETED',
                'generation_id':identity['generation_id'],'completed_replayed_steps':completed,
                'last_verified_checkpoint':last_checkpoint,'output_committed':output.exists(),
                'completed_driver_counts':completed_counts,
                'driver_counts':getattr(exc,'coupling_counts',getattr(exc,'driver_counts',attempt_counts))}
            raise


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recipe',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--resume',action='store_true');args=p.parse_args(argv)
    try:result=run(args.recipe,args.output,resume=args.resume)
    except Exception as exc:
        print(json.dumps({'error':type(exc).__name__,'message':str(exc),
                          'workflow':getattr(exc,'shoreline_workflow_failure',None)},sort_keys=True),file=sys.stderr)
        return 2
    print(json.dumps(result,sort_keys=True,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
