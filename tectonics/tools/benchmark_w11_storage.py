"""Bounded synthetic storage/cpu probe; no source writes or historical rebind."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
import types


def summary(values):
    return dict(median_s=statistics.median(values), samples_s=values)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--storage-only', action='store_true')
    args = p.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    root = args.repo/'tectonics'
    sys.path[:0] = [str(root/'src'), str(root/'tests')]
    import numpy as np
    import scipy
    import blosc2
    from atlas_tectonics import storage
    from atlas_tectonics import ThermalParameters, FlexureParameters, PeriodicGrid1D, PeriodicFlexure, Rotation
    from atlas_tectonics._validation import frozen
    from atlas_tectonics.execution import KernelExecutor, ExecutionPolicy
    from measure_storage_profiles import data
    begun = time.perf_counter()
    source = (args.baseline if args.baseline else Path(storage.__file__)).read_text(encoding='utf-8')
    old = "                    for start in range(0, a.size, width):\n                        # Only one flat chunk copied, including strided caller data.\n                        ids.append(capture(a.flat[start:start+width]))"
    new = "                    # C-order views avoid a temporary chunk copy before capture's\n                    # detached bytes. Strided arrays keep bounded flat slicing.\n                    flat = np.asarray(a).reshape(-1) if a.flags.c_contiguous else a.flat\n                    for start in range(0, a.size, width):\n                        ids.append(capture(flat[start:start+width]))"
    if source.count(old) != 1:
        raise ValueError('candidate target changed')
    candidate_source = source.replace(old, new)
    if args.baseline and candidate_source != Path(storage.__file__).read_text(encoding='utf-8'):
        raise ValueError('current source differs from reviewed candidate')
    candidate = types.ModuleType('atlas_tectonics._w11_storage_candidate')
    candidate.__file__ = str(Path(storage.__file__))
    candidate.__package__ = 'atlas_tectonics'
    sys.modules[candidate.__name__] = candidate
    exec(compile(candidate_source, '<w11-memory-only-storage-candidate>', 'exec'), candidate.__dict__)
    baseline = storage
    if args.baseline:
        baseline = types.ModuleType('atlas_tectonics._w11_storage_baseline')
        baseline.__file__ = str(args.baseline)
        baseline.__package__ = 'atlas_tectonics'
        sys.modules[baseline.__name__] = baseline
        exec(compile(source, str(args.baseline), 'exec'), baseline.__dict__)
        candidate = storage
    report = dict(scope='bounded synthetic storage and independent kernel scheduling only',
                  runtime=dict(python=platform.python_version(), platform=platform.platform(),
                               numpy=np.__version__, scipy=scipy.__version__, blosc2=blosc2.__version__),
                  source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                  candidate_source_sha256=hashlib.sha256(candidate_source.encode()).hexdigest(),
                  candidate_old=old, candidate_new=new, storage=[], execution=[])
    arrays = data(262144)
    with tempfile.TemporaryDirectory() as d:
        for layout in ('contiguous', 'strided'):
            fields = arrays if layout == 'contiguous' else {k:v[::2] for k,v in arrays.items()}
            for codec in ('raw', 'zstd'):
                times = {k:[] for k in ('baseline', 'candidate')}
                store_stats = {}
                for pair in range(5):
                    variants = [('baseline',baseline),('candidate',candidate)]
                    if pair%2: variants.reverse()
                    contents = {}
                    for label, module in variants:
                        limits = module.StoreLimits(65536, 16<<20, 64<<20, 4<<20)
                        with module.ArrayStore(Path(d)/f'{layout}-{codec}-{pair}-{label}.db',limits,
                                               module.Compression(codec=codec)) as store:
                            key=hashlib.sha256(b'identical synthetic invocation').hexdigest()
                            start=time.perf_counter();store.put(key,fields);times[label].append(time.perf_counter()-start)
                            restored=store.get(key)
                            if any(restored[k].tobytes()!=v.tobytes() for k,v in fields.items()):
                                raise AssertionError('storage output changed')
                            contents[label]=store._db.execute('SELECT * FROM chunks ORDER BY id').fetchall()
                            store_stats[label]=store.statistics()
                    if contents['baseline'] != contents['candidate']:
                        raise AssertionError('chunk IDs or stored bytes changed')
                before,after=(statistics.median(times[k]) for k in ('baseline','candidate'))
                report['storage'].append(dict(layout=layout,codec=codec,input_bytes=sum(v.nbytes for v in fields.values()),
                    times={k:summary(v) for k,v in times.items()},saved_percent=100*(before-after)/before,
                    identical_chunk_rows=True, exact_round_trip=True, statistics=store_stats))
    thermal=ThermalParameters('synthetic','bounded W11 scheduling',300.,1300.,1.)
    elastic=FlexureParameters('synthetic','bounded W11 scheduling',12.,1.,0.,1.,1.)
    rotation=Rotation.from_axis_angle([1.,2.,3.],.7)
    for n in (() if args.storage_only else (65536,262144)):
        x=frozen(np.linspace(0,10,n));points=frozen(np.resize(x,(n,3)))
        operator=PeriodicFlexure(PeriodicGrid1D(n,float(n)),elastic)
        for kind in ('cooling','rotation','flexure'):
            timings={k:[] for k in ('serial','auto','threads')}; first={};stats={};expected=None
            with ExitStack() as stack:
                executors={k:stack.enter_context(KernelExecutor(ExecutionPolicy(mode=k,max_workers=2,max_inflight=4))) for k in timings}
                def run(ex):
                    if kind=='cooling':return list(ex.temperatures([(x,1.)]*8,thermal))
                    if kind=='rotation':return list(ex.rotations([points]*8,rotation))
                    return list(ex.flexure([x]*8,operator))
                for mode,ex in executors.items():
                    start=time.perf_counter();result=run(ex);first[mode]=time.perf_counter()-start
                    payload=[v.tobytes() for v in result]
                    if expected is None:expected=payload
                    if payload!=expected:raise AssertionError('execution output changed')
                for pair in range(5):
                    modes=list(executors)
                    if pair%2:modes.reverse()
                    for mode in modes:
                        start=time.perf_counter();result=run(executors[mode]);timings[mode].append(time.perf_counter()-start)
                        if [v.tobytes() for v in result]!=expected:raise AssertionError('execution output changed')
                stats={k:v.statistics() for k,v in executors.items()}
            report['execution'].append(dict(kind=kind,n=n,jobs=8,first_s=first,times={k:summary(v) for k,v in timings.items()},
                                             exact_output_bytes=True,statistics=stats))
    report['wall_s']=time.perf_counter()-begun
    with args.report.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2,allow_nan=False)
    print(json.dumps(dict(report=str(args.report),wall_s=report['wall_s'],storage=[{k:r[k] for k in ('layout','codec','saved_percent')} for r in report['storage']],
        execution=[dict(kind=r['kind'],n=r['n'],median_s={k:v['median_s'] for k,v in r['times'].items()}) for r in report['execution']]),indent=2))


if __name__=='__main__':main()
