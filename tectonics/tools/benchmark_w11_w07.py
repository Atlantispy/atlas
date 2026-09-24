"""Same-source whole W07 caller comparison against its frozen previous workflow.

The old caller is loaded as a separately named comparison adapter. Both callers
use identical current scientific dependencies and live source verification, so
every output identity, descriptor and array byte must agree without filtering.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS'):
    os.environ[key] = '1'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--baseline-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): raise FileExistsError('new output path required')
    root = args.repo.resolve()/'tectonics'
    sys.path[:0] = [str(root/'src'), str(root/'tests')]
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.w07_workflow import PreparedW07Workflow, W07BoundaryMotion
    import test_w07_workflow as fixture
    oldpath = args.baseline_source.resolve()/'atlas_tectonics/w07_workflow.py'
    spec = importlib.util.spec_from_file_location('atlas_tectonics._w11_previous_workflow', oldpath)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    sources = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted((root/'src/atlas_tectonics').glob('*.py'))}
    old_sha = hashlib.sha256(oldpath.read_bytes()).hexdigest()
    evidence = dict(schema='atlas.w11-w07-verifier-comparison.v1', repeats=3,
        source_status='WORKING NON-CANON', baseline_workflow_sha256=old_sha,
        source_sha256=sources, routes=[], scope='Full W01/W02 fixture production, geological binding, W07 preparation, requested outputs and closure. Both old and current callers use identical current scientific dependencies and source/runtime identity; all complete outputs agree without removing any metadata or identity. Excludes initial imports and post-timing byte comparison. The extra retained verifier is admitted as 4MiB; accounted memory is not RSS.')
    started = time.perf_counter()
    for route in ('steady', 'thermal', 'surface'):
        rows={'old':[], 'candidate':[]}; expected=None; peak={}
        for repeat in range(3):
            for mode in (('old','candidate') if repeat%2==0 else ('candidate','old')):
                owner = WorkBudget(128 << 20)
                cls = old.PreparedW07Workflow if mode=='old' else PreparedW07Workflow
                boundary_cls=old.W07BoundaryMotion if mode=='old' else W07BoundaryMotion
                with patch.object(fixture, 'PreparedW07Workflow', cls), patch.object(fixture, 'W07BoundaryMotion', boundary_cls):
                    beginning=time.perf_counter()
                    with fixture.make_workflow_fixture(route, thermal=route=='thermal', budget=owner) as plan:
                        output=plan.run()
                    duration=time.perf_counter()-beginning
                signature=(fixture.output_signature(output),tuple(
                    (obj.array_names,tuple((obj.array(n).shape,obj.array(n).dtype.str,obj.array(n).tobytes())
                                          for n in obj.array_names)) for obj in (output.state,output.mechanics)))
                if expected is None: expected=signature
                if expected != signature: raise RuntimeError('complete output parity failed: '+route)
                if owner.reserved_bytes: raise RuntimeError('reservation leak')
                rows[mode].append(duration);peak[mode]=max(peak.get(mode,0),owner.peak_reserved_bytes)
        before,after=(statistics.median(rows[k]) for k in ('old','candidate'))
        evidence['routes'].append(dict(route=route,seconds=rows,old_median_s=before,candidate_median_s=after,
            saved_s=before-after,saved_percent=100*(before-after)/before,peak_accounted_bytes=peak,
            complete_output_sha256=hashlib.sha256(repr(expected).encode()).hexdigest(),full_output_parity=True))
        print(json.dumps(evidence['routes'][-1]),flush=True)
    if sources != {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted((root/'src/atlas_tectonics').glob('*.py'))}:
        raise RuntimeError('production sources changed during measurement')
    if old_sha != hashlib.sha256(oldpath.read_bytes()).hexdigest():
        raise RuntimeError('baseline caller changed')
    evidence['elapsed_s']=time.perf_counter()-started
    evidence['status']='PASS'
    args.output.write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
