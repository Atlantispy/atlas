#!/usr/bin/env python3
"""Measure exact recovery versus recomputing three already-completed outputs.

Bounded synthetic fixtures, no broad acceptance campaign. Existing producer
preparation is retained on both paths; persistent reads reopen the store each
time. This measures saved prefix work, not a faster new physical simulation.
"""
import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'),str(ROOT/'tests')]
import numpy as np
import scipy
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.reuse import _source_bytes
from atlas_tectonics.tectonic_history import PreparedTectonicHistory
from atlas_tectonics.tectonic_history_codec import pack_history_result
from test_tectonic_history import make_history_case,open_store,SOURCE,ROUTES


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def signature(output,budget):
    arrays,meta = pack_history_result(output.result,budget=budget)
    h = hashlib.sha256(encoded(dict(record=output.descriptor(),output_id=output.output_id,payload=meta)))
    for name,a in sorted(arrays.items()):
        h.update(encoded(dict(name=name,shape=a.shape,dtype=a.dtype.str)))
        h.update(a.tobytes())
    return h.hexdigest()


def source_binding():
    supporting = {Path(__file__).resolve(),ROOT/'cases/w08_regimes.json',ROOT/'cases/w07_mechanics.json'}
    for name,module in tuple(sys.modules.items()):
        path = getattr(module,'__file__',None)
        if name.startswith('test_') and path and Path(path).resolve().parent == ROOT/'tests':
            supporting.add(Path(path).resolve())
    return dict(production={name:json.loads(raw) for name,raw in _source_bytes().items()},
        tools_and_fixtures={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(supporting)})


def measure(route):
    owner = WorkBudget(128 << 20)
    prepared,inputs = make_history_case(route,budget=owner,regional_n=12,cells=8)
    raw = dict(recompute=[],restore=[]); observations=[]
    with prepared,TemporaryDirectory(prefix='atlas-history-') as tmp:
        path = Path(tmp)/'history.sqlite'
        started=perf_counter()
        with open_store(path,owner) as store:
            with PreparedTectonicHistory(prepared,inputs,source_id=SOURCE,store=store) as history:
                complete=history.run(); baseline=signature(complete,owner)
            stored=store.statistics()
        initial_publication_s=perf_counter()-started
        for repeat in range(3):
            for restore in ((False,True) if repeat%2==0 else (True,False)):
                started=perf_counter()
                with (open_store(path,owner) if restore else nullcontext(None)) as store:
                    with PreparedTectonicHistory(prepared,inputs,source_id=SOURCE,store=store) as history:
                        output=history.run(); fingerprint=signature(output,owner)
                        stats=history.statistics()
                elapsed=perf_counter()-started
                if fingerprint != baseline: raise AssertionError('complete recovered scientific bytes or IDs changed')
                if stats['computed_outputs'] != (0 if restore else 3):
                    raise AssertionError('unexpected physical output reuse/replay')
                if stats['restored_outputs'] != (1 if restore else 0):
                    raise AssertionError('expected latest complete output restoration')
                raw['restore' if restore else 'recompute'].append(elapsed)
                observations.append(dict(repeat=repeat+1,restore=restore,statistics=stats))
        peak=owner.peak_reserved_bytes
    if owner.reserved_bytes != 0: raise AssertionError('leaked shared reservation')
    cold,warm=(statistics.median(raw[k]) for k in ('recompute','restore'))
    return dict(status='PASS',route=route,outputs=3,raw_seconds=raw,
        recompute_median_s=cold,restore_median_s=warm,seconds_saved=cold-warm,
        percent_saved=100*(cold-warm)/cold,complete_output_sha256=baseline,
        complete_output_hash_parity=True,observations=observations,
        initial_publication_s=initial_publication_s,store=stored,
        peak_accounted_bytes=peak,final_reserved_bytes=owner.reserved_bytes)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists(): raise FileExistsError('new evidence path required')
    started=perf_counter(); sources=source_binding()
    routes=[measure(route) for route in ROUTES]
    if source_binding()!=sources: raise AssertionError('source changed during measurement')
    report=dict(schema='atlas.tectonic-history-evidence.v1',status='PASS',sources=sources,routes=routes,
        runtime=dict(platform=platform.platform(),python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__),
        wall_s=perf_counter()-started,
        included='fresh history owner, live source checks, three physical outputs or latest checkpoint recovery, full result hashing, close; recovery reopens its store',
        excluded='imports, immutable producer inputs, borrowed producer preparation, initial publication and report writing',
        initial_publication='separately measured; raw lossless store, existing exact chunk deduplication',
        scope='2-parcel section; 8-cell elastic support; 12x12 regional mechanics; synthetic saved-work timing, not new-simulation or whole-generator acceleration',
        resource_measurement='shared accounted bytes, not process RSS')
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps({r['route']:{k:r[k] for k in ('recompute_median_s','restore_median_s','seconds_saved','percent_saved','peak_accounted_bytes')}
                      for r in routes},sort_keys=True))


if __name__=='__main__': main()
