"""Bounded, explicitly labelled later-reproduction comparison; never R4.4."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

import numpy as np
from atlas_tectonics.subduction import PreparedSubduction


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cases',nargs='+',choices=['1a','1b','1c','2a','2b'],default=['1a','1b','1c','2a','2b'])
    parser.add_argument('--spacing',nargs='+',type=float,default=[6,3,1.5])
    parser.add_argument('--mesh-grading',choices=['interface-r3','corner-r4','corner-r5'],default='interface-r3')
    parser.add_argument('--coupling-trace',choices=['nodal-p2-v1','mesh-linear-first-edge-v1'],default='nodal-p2-v1')
    parser.add_argument('--timing',action='store_true')
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    fixture_path=root/'cases/w08_subduction_r2.json'
    fixture=json.loads(fixture_path.read_text())
    digest=hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    kwargs=dict(source_id=fixture['adapter_id']+':'+digest,
        outflow_operator=fixture['thermal_outflow_operator'],mesh_grading=args.mesh_grading,
        coupling_trace=args.coupling_trace)
    start=time.perf_counter(); rows=[]
    sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root/'src/atlas_tectonics').glob('*.py'))}
    def write_report(*, finished=False, refinement=None, timings=None):
        # Retain completed comparisons even if a later bounded solve is cancelled.
        # RUNNING is not a completed campaign or a passed acceptance assessment.
        result=dict(schema='atlas.w08-subduction-comparison.v1',source_status='WORKING NON-CANON',
            run_status='FINISHED' if finished else 'RUNNING',
            original2008_acceptance='BLOCKED_SOURCE_ADAPTER',fixture_sha256=digest,
            driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            sources=sources,requested_cases=args.cases,requested_spacing_km=args.spacing,
            requested_mesh_grading=args.mesh_grading,
            requested_coupling_trace=args.coupling_trace,
            environment=dict(python=platform.python_version(),system=platform.system(),numpy=np.__version__),
            rows=rows,refinement=refinement or {},timings=timings,elapsed_s=time.perf_counter()-start)
        args.report.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        return result
    write_report()
    for h in args.spacing:
        with PreparedSubduction(h,**kwargs) as plan:
            for case in args.cases:
                t=time.perf_counter()
                try:
                    result=plan.solve(case)
                    error=np.asarray(result.diagnostics_c)-fixture['reference_rows'][case]
                    row=dict(case=case,spacing_km=h,status='COMPUTED',identity=result.identity,
                        execution_id=plan.execution_id,triangles=len(plan.mesh.cells),
                        thermal_nodes=len(plan.mesh.points),wedge_triangles=len(plan.wedge.cells),
                        diagnostics_C=result.diagnostics_c,error_C=error.tolist(),
                        comparison_error_gate=bool(np.max(np.abs(error))<=fixture['diagnostic_comparison_error_max_C']),
                        nonlinear_iterations=result.iterations,statistics=result.statistics)
                    del result  # the row contains diagnostics, not the full field
                except ValueError as exc:
                    row=dict(case=case,spacing_km=h,status='REFUSED',reason=str(exc))
                row['elapsed_s']=time.perf_counter()-t
                rows.append(row); write_report()
                print(json.dumps(dict(case=case,h=h,status=row['status'],elapsed_s=row['elapsed_s'],
                    diagnostics_C=row.get('diagnostics_C'),error_C=row.get('error_C'),reason=row.get('reason'))),flush=True)
    timings=None
    if args.timing:
        measured={'fresh':[],'prepared':[]}; ids={}
        for repeat in range(3):
            for mode in (('fresh','prepared') if repeat%2==0 else ('prepared','fresh')):
                t=time.perf_counter(); produced=[]
                if mode=='fresh':
                    for _ in range(3):
                        with PreparedSubduction(12.,**kwargs) as plan: produced.append(plan.solve('1c').identity)
                else:
                    with PreparedSubduction(12.,**kwargs) as plan:
                        produced=[plan.solve('1c').identity for _ in range(3)]
                measured[mode].append(time.perf_counter()-t); ids[mode]=produced
        if ids['fresh']!=ids['prepared']: raise RuntimeError('timing output identity mismatch')
        cold,warm=(statistics.median(measured[k]) for k in ('fresh','prepared'))
        timings=dict(samples_s=measured,fresh_median_s=cold,prepared_median_s=warm,
            saved_s=cold-warm,saved_percent=100*(cold-warm)/cold,identical_outputs=True,
            scope='3 identical complete 12km case1c requests; setup/source verification/materialisation/close included')
    refinement={}
    for case in args.cases:
        candidates=sorted((r for r in rows if r['case']==case and r['status']=='COMPUTED'),
            key=lambda r:r['spacing_km'],reverse=True)
        if len(candidates)>=3:
            a,b=candidates[-2:]
            change=(np.asarray(b['diagnostics_C'])-a['diagnostics_C']).tolist()
            refinement[case]=dict(finest_change_C=change,comparison_change_gate=max(map(abs,change))<=fixture['finest_comparison_change_max_C'])
    current={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root/'src/atlas_tectonics').glob('*.py'))}
    if current!=sources: raise RuntimeError('source changed during comparison; partial evidence retained, no completion claim')
    result=write_report(finished=True,refinement=refinement,timings=timings)
    print(json.dumps(dict(report=str(args.report),elapsed_s=result['elapsed_s'],timings=timings)),flush=True)


if __name__=='__main__': main()
