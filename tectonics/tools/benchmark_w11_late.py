"""Short matched scientific-field comparison of unchanged later workflows."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROUTES=('w05','w06-constant','w06-history','w06-margin','w08-joined',
        'underthrust','evolving-regional','evolving-flexure')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--current',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--worker',action='store_true')
    args=parser.parse_args()
    if args.output.exists(): raise FileExistsError('new output path required')
    os.environ['W11_REPO']=str(args.repo.resolve())
    if args.worker:
        import w11_late_profile as sample
        package=Path(os.environ['W11_SOURCE'])/'atlas_tectonics'
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob('*.py'))}
        rows=[]
        for route in ROUTES:
            started=time.perf_counter()
            signature,budget=sample.run(route,scientific=True)
            rows.append(dict(route=route,seconds=time.perf_counter()-started,signature=signature,budget=budget))
        if before!={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob('*.py'))}:
            raise RuntimeError('source drift during worker')
        args.output.write_text(json.dumps(dict(status='PASS',sources=before,routes=rows),indent=2)+'\n',encoding='utf-8')
        return
    if args.baseline is None or args.current is None: parser.error('baseline and current source roots required')
    for repeat in range(3):
        for mode in ('baseline','current'):
            if args.output.with_name(args.output.stem+f'-{repeat}-{mode}.json').exists():
                raise FileExistsError('new sample paths required')
    samples=[]
    for repeat in range(3):
        for mode in (('baseline','current') if repeat%2==0 else ('current','baseline')):
            destination=args.output.with_name(args.output.stem+f'-{repeat}-{mode}.json')
            env=dict(os.environ,W11_SOURCE=str(getattr(args,mode).resolve()),
                     W11_REPO=str(args.current.resolve().parents[1]))
            run=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--output',str(destination)],
                env=env,capture_output=True,text=True,timeout=90)
            if run.returncode:
                raise RuntimeError(f'{mode} repeat{repeat}: '+run.stdout+run.stderr)
            samples.append(dict(mode=mode,repeat=repeat,path=destination.name,record=json.loads(destination.read_text(encoding='utf-8'))))
            print(json.dumps(dict(mode=mode,repeat=repeat,seconds=sum(r['seconds'] for r in samples[-1]['record']['routes']))),flush=True)
    rows=[]
    for route in ROUTES:
        found=[(sample['mode'],next(r for r in sample['record']['routes'] if r['route']==route)) for sample in samples]
        expected=found[0][1]['signature']
        for _,row in found:
            if row['signature']!=expected:raise RuntimeError('scientific field parity failed: '+route)
        times={mode:[r['seconds'] for m,r in found if m==mode] for mode in ('baseline','current')}
        before,after=(statistics.median(times[m]) for m in ('baseline','current'))
        rows.append(dict(route=route,seconds=times,baseline_median_s=before,current_median_s=after,
            saved_s=before-after,saved_percent=100*(before-after)/before,exact_scientific_field_parity=True,
            signature=expected,peak_accounted_bytes={m:max(r['budget']['peak_reserved_bytes'] for key,r in found if key==m)
                for m in ('baseline','current')}))
    evidence=dict(status='PASS',schema='atlas.w11-late-scientific-fields.v1',repeats=3,routes=rows,
        scope='Setup-inclusive supported later workflow sequences; complete declared scientific array bytes and explicit physical metadata. Baseline/current source-derived IDs differ and are not claimed equal. W05 material transition accounts/support physical metadata; W06 complete scientific fields, export histories and margin physical/thermal metadata; W08 complete inventory, regional fields, footprint WKB and deformation; underthrust all arrays, polygons and non-source-derived descriptor; evolving mechanics all published arrays. This is not a complete metadata or execution-ID parity claim.',
        sample_files=[dict(mode=s['mode'],repeat=s['repeat'],path=s['path']) for s in samples])
    args.output.write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([{k:v for k,v in r.items() if k not in ('signature','seconds')} for r in rows],indent=2))


if __name__=='__main__':main()
