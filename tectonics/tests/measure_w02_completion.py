"""Bounded W02 method/accuracy measurements, never whole-world forecasts.

Use the existing dependencies and one inner numerical-library thread. No timing
threshold is a test gate. Independent reference and compiled methods use the
same physics, reconstruction and numerical tolerances. No files are published.
"""
from __future__ import annotations
import hashlib,json,math,os,platform,sys,time,tracemalloc
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from atlas_tectonics.mesh import ColumnGrid1D
from atlas_tectonics.materials import MaterialState,MaterialCohort,MaterialBoundary
from atlas_tectonics.remapping import remap_materials,RemapPlan,advect_ale,_inventories
from atlas_tectonics.execution import KernelExecutor,ExecutionPolicy
from atlas_tectonics.resources import WorkBudget


def make_state(n,c):
    g=ColumnGrid1D(np.linspace(0,1,n+1),frame_id='synthetic')
    h=np.array([2+.2*np.sin((k+1)*2*np.pi*g.centres_m) for k in range(c)])
    return MaterialState(g,tuple(MaterialCohort(f'c{k:03d}','rock',f'o{k}',0.) for k in range(c)),h,time_s=1,epoch_id='test')

def compare(a,b,reps=5):
    left=[];right=[];last=None
    for i in range(reps):
        funcs=((a,left),(b,right)) if i%2==0 else ((b,right),(a,left))
        for f,values in funcs:
            start=time.perf_counter();last=f();values.append(time.perf_counter()-start)
    return {'a_median_s':float(np.median(left)),'b_median_s':float(np.median(right)),
            'a_samples_s':left,'b_samples_s':right}

def tracked(f):
    tracemalloc.start();result=f();peak=tracemalloc.get_traced_memory()[1];tracemalloc.stop()
    return peak

def main():
    s=make_state(8192,2);g=ColumnGrid1D(np.linspace(0,1,12289)**1.1,frame_id='synthetic')
    start=time.perf_counter();plan=RemapPlan(s.grid,g);r=remap_materials(s,g,plan=plan)
    first_remap=time.perf_counter()-start
    ref=remap_materials(s,g,backend='reference')
    remap_compare=compare(lambda:remap_materials(s,g,backend='reference'),lambda:remap_materials(s,g,plan=plan))
    reuse=compare(lambda:remap_materials(s,g),lambda:remap_materials(s,g,plan=plan))
    u=np.full(8193,.1);w=.01*np.sin(np.pi*s.grid.edges_m);w[-1]=0;dt=.2/8192/.1
    boundary=MaterialBoundary('open',{c.cohort_id:2. for c in s.cohorts},'outside')
    start=time.perf_counter();a=advect_ale(s,u,w,dt,left=boundary,right=boundary);first_ale=time.perf_counter()-start
    b=advect_ale(s,u,w,dt,left=boundary,right=boundary,backend='reference')
    ale_compare=compare(lambda:advect_ale(s,u,w,dt,left=boundary,right=boundary,backend='reference'),
                        lambda:advect_ale(s,u,w,dt,left=boundary,right=boundary))
    errors=[]
    for n in (32,64,128):
        x=np.linspace(0,1,n+1);h=2+(np.cos(2*np.pi*x[:-1])-np.cos(2*np.pi*x[1:]))/(2*np.pi*np.diff(x))
        source=MaterialState(ColumnGrid1D(x,frame_id='refinement'),(MaterialCohort('c','r','o',0.),),h[None,:],time_s=1,epoch_id='t')
        y=np.linspace(0,1,2*n+2);target=ColumnGrid1D(y,frame_id='refinement')
        actual=remap_materials(source,target)
        expected=2+(np.cos(2*np.pi*y[:-1])-np.cos(2*np.pi*y[1:]))/(2*np.pi*np.diff(y))
        errors.append({'cells':n,'L1_thickness_error_m':float(np.sum(abs(actual.thickness_m[0]-expected)*np.diff(y)))})
    # Independent full-domain scenarios, not fragments of one coupled domain.
    many=make_state(32768,8);c=len(many.cohorts);v=np.full(32769,.1);z=np.zeros(32769)
    bc=MaterialBoundary('open',{c.cohort_id:2. for c in many.cohorts},'outside');requests=[(v,z)]*4
    with KernelExecutor(ExecutionPolicy(mode='serial',max_workers=2),budget=WorkBudget(256<<20)) as serial, \
         KernelExecutor(ExecutionPolicy(mode='auto',max_workers=2),budget=WorkBudget(256<<20)) as auto:
        one=list(serial.ale_transports(requests,many,.00005,left=bc,right=bc))
        two=list(auto.ale_transports(requests,many,.00005,left=bc,right=bc))
        batches=compare(lambda:list(serial.ale_transports(requests,many,.00005,left=bc,right=bc)),
                        lambda:list(auto.ale_transports(requests,many,.00005,left=bc,right=bc)),3)
        batches.update(identical=[r.state.state_id for r in one]==[r.state.state_id for r in two],
                       serial_stats=serial.statistics(),auto_stats=auto.statistics())
    root=Path(__file__).resolve().parents[1]
    result={'scope':'W02 bounded synthetic remap/ALE and independent batching; not physical/Windows/global acceptance',
       'runtime':{'python':platform.python_version(),'numpy':np.__version__,'numba':__import__('numba').__version__,
                  'platform':platform.system(),'thread_env':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}},
       'source_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root/'src').rglob('*.py'))},
       'remap':{'source_cells':8192,'target_cells':12288,'cohorts':2,'first_native_with_setup_s':first_remap,
          'comparison_reference_then_native':remap_compare,'fresh_vs_reused_plan':reuse,'plan_bytes':plan.nbytes,
          'max_abs_reference_difference_m':float(np.max(abs(r.thickness_m-ref.thickness_m))),
          'inventory_residual_m2':(_inventories(r.thickness_m,g)-_inventories(s.thickness_m,s.grid)).tolist(),
          'native_tracked_peak_bytes':tracked(lambda:remap_materials(s,g,plan=plan)),
          'reference_tracked_peak_bytes':tracked(lambda:remap_materials(s,g,backend='reference'))},
       'ale':{'cells':8192,'cohorts':2,'first_native_s':first_ale,'comparison_reference_then_native':ale_compare,
          'max_abs_reference_difference_m':float(np.max(abs(a.state.thickness_m-b.state.thickness_m))),
          'accounts_residual_m2':a.accounts[:,4].tolist(),
          'native_tracked_peak_bytes':tracked(lambda:advect_ale(s,u,w,dt,left=boundary,right=boundary)),
          'reference_tracked_peak_bytes':tracked(lambda:advect_ale(s,u,w,dt,left=boundary,right=boundary,backend='reference'))},
       'remap_refinement':errors,'independent_ale_batches':batches,
       'limitations':['Tracked allocations omit native/compiler/runtime overhead.',
                      'No lower-order method selected for speed; reference and native solve identical selected models.',
                      'Formation metadata not averaged; no variable-density/momentum/energy equation in W02.']}
    print(json.dumps(result,indent=2,allow_nan=False))

if __name__=='__main__':main()
