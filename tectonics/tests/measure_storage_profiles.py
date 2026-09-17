"""Bounded items 9–11 comparisons; synthetic storage, never geological execution.

Run with --baseline pointing to the previous delivered tectonics directory.
Measures encode/decode tuning separately from whole-store calls. Five paired
comparisons include validation and transaction publication. No timing test gates.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time

import numpy as np
import blosc2
from atlas_tectonics import storage as current


def key(s):return hashlib.sha256(s.encode()).hexdigest()

def timed(call):
    t=time.perf_counter();r=call();return time.perf_counter()-t,r

def stats(values):
    return dict(median_s=statistics.median(values),min_s=min(values),max_s=max(values),repetitions=len(values))

def data(n=32768):
    rng=np.random.default_rng(911)
    return {'uniform':np.full(n,1200.), 'categories':rng.integers(0,8,n,dtype='u4'),
        'layers':np.repeat(np.arange((n+255)//256,dtype='i4'),256)[:n],
        'smooth':np.sin(np.linspace(0,40,n)), 'rough':rng.normal(size=n),
        'signed_zeros':np.resize(np.array([0.,-0.]),n)}

def tune(root):
    arrays=data()
    records=[]
    configurations=[('raw',current.Compression('raw',palette=False))]
    configurations += [(f'zstd-{level}-{shuffle}',current.Compression('zstd',level,shuffle))
                       for level in (1,3,6) for shuffle in ('none','byte','bit')]
    for size in (16384,65536,262144):
        for name,compression in configurations:
            with current.ArrayStore(root/f'{size}-{name}.db',current.StoreLimits(size,8<<20,32<<20),compression) as store:
                encoded_total=0;encode=[];decode=[];by_field={}
                for field,a in arrays.items():
                    width=size//a.itemsize;chunks=[a[start:start+width].tobytes() for start in range(0,a.size,width)]
                    field_bytes=0;et=[];dt=[]
                    for raw in chunks:
                        out=None
                        for _ in range(3):
                            t,out=timed(lambda:store._encode(raw,a.dtype));et.append(t)
                            t,restored=timed(lambda:store._decode(*out,a.dtype,len(raw)//a.itemsize));dt.append(t)
                            assert restored==raw
                        field_bytes+=len(out[1])
                    encoded_total+=field_bytes;encode+=et;decode+=dt
                    by_field[field]=dict(input_bytes=a.nbytes,encoded_bytes=field_bytes,
                                        encode_seconds=sum(et)/3,decode_seconds=sum(dt)/3)
                records.append(dict(chunk_bytes=size,configuration=name,encoded_bytes=encoded_total,
                    input_bytes=sum(a.nbytes for a in arrays.values()),
                    encode_seconds=sum(encode)/3,decode_seconds=sum(decode)/3,fields=by_field,round_trip=True))
    dictionary=[]
    # Similar small records and longer smooth/noisy chunks. No shared training set
    # or external dictionary is smuggled into the storage dependencies.
    for length in (2048,8192,65536):
        for kind in ('records','smooth','rough'):
            if kind=='records':
                raw=(b'{"material":"basalt","temperature":1200,"age":1000000,"region":3}\n'*((length//32)+2))[:length]
                dt=np.dtype('u1')
            else:
                a=(np.sin(np.arange(length//8)/30) if kind=='smooth' else np.random.default_rng(11).normal(size=length//8))
                raw=a.tobytes();dt=a.dtype
            for enabled in (False,True):
                c=current.Compression('zstd',3,'byte',False,use_dict=enabled)
                with current.ArrayStore(root/f'dict-{length}-{kind}-{enabled}.db',current.StoreLimits(65536,8<<20,32<<20),c) as s:
                    ts=[];ds=[]
                    try:
                        for _ in range(3):
                            t,out=timed(lambda:s._encode(raw,dt));ts.append(t)
                            t,r=timed(lambda:s._decode(*out,dt,len(raw)//dt.itemsize));ds.append(t);assert r==raw
                        dictionary.append(dict(bytes=len(raw),kind=kind,enabled=enabled,encoded_bytes=len(out[1]),encode=stats(ts),decode=stats(ds),exact=True))
                    except (RuntimeError,ValueError) as e:
                        dictionary.append(dict(bytes=len(raw),kind=kind,enabled=enabled,error=str(e)))
    return {'candidates':records,'dictionary':dictionary}


def load_baseline(path):
    pkg=path/'src/atlas_tectonics'
    spec=importlib.util.spec_from_file_location('atlas_storage_baseline',pkg/'__init__.py',submodule_search_locations=[str(pkg)])
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return __import__('atlas_storage_baseline.storage',fromlist=['ArrayStore'])


def comparisons(root,old):
    a=data(65536); nbytes=sum(v.nbytes for v in a.values());result={}
    for codec in ('raw','zstd'):
        times={'previous':[],'current':[]};reads={'previous':[],'current':[]};first_reads={'previous':[],'current':[]};transactions={'previous':[],'current':[]};db={};operations={}
        for repeat in range(5):
            order=[('previous',old),('current',current)]
            if repeat%2:order.reverse()
            for label,m in order:
                path=root/f'whole-{codec}-{repeat}-{label}.db'
                limits=m.StoreLimits(65536,16<<20,64<<20,4<<20)
                comp=m.Compression(codec,3,'byte',True)
                with m.ArrayStore(path,limits,comp) as s:
                    begins=[]
                    def trace(statement):
                        if statement == 'BEGIN IMMEDIATE':begins.append(time.perf_counter())
                    s._db.set_trace_callback(trace)
                    t,_=timed(lambda:s.put(key('same'),a));finish=time.perf_counter();times[label].append(t)
                    s._db.set_trace_callback(None)
                    transactions[label].append(finish-begins[-1])
                    t,out=timed(lambda:s.get(key('same')));first_reads[label].append(t)
                    assert all(out[k].tobytes()==v.tobytes() for k,v in a.items())
                    t,out=timed(lambda:s.get(key('same')));reads[label].append(t)
                    db[label]=s.statistics()['database_bytes']
                    if label=='current':operations[label]=s.statistics()['operations']
        result[codec]=dict(write={k:stats(v) for k,v in times.items()},warm_read={k:stats(v) for k,v in reads.items()},first_decode={k:stats(v) for k,v in first_reads.items()},writer_interval={k:stats(v) for k,v in transactions.items()},database_bytes=db,input_bytes=nbytes,operations=operations)
    incremental={}
    for label,m in (('previous',old),('current',current)):
        limits=m.StoreLimits(65536,16<<20,64<<20,4<<20)
        with m.ArrayStore(root/f'incremental-{label}.db',limits,m.Compression('zstd',3,'byte',True)) as s:
            s.put(key('base'),a);initial=s.statistics();elapsed=[]
            for i in range(5):
                if label=='previous':t,_=timed(lambda:s.put(key(f'child{i}'),a))
                else:t,_=timed(lambda:s.put_incremental(key(f'child{i}'),key('base'),{}))
                elapsed.append(t)
            changed={k:v.copy() for k,v in a.items()};changed['smooth'][4]+=1
            before=s.statistics()
            if label=='previous':t,_=timed(lambda:s.put(key('changed'),changed))
            else:t,_=timed(lambda:s.put_incremental(key('changed'),key('base'),{'smooth':{0:changed['smooth'][:8192]}}))
            after=s.statistics()
            assert s.get(key('changed'))['smooth'].tobytes()==changed['smooth'].tobytes()
            incremental[label]=dict(unchanged_snapshots=stats(elapsed),changed_write_s=t,
                new_chunks=after['unique_chunks']-before['unique_chunks'],initial_chunks=initial['unique_chunks'],
                operations=after.get('operations',{}))
    result['incremental']=incremental
    # Is queue/prefetch overhead worthwhile for this serialised local store?
    # Same repeated full read, verified output; executor exists before timing.
    with current.ArrayStore(root/'prefetch.db',current.StoreLimits(65536,16<<20,64<<20,4<<20)) as s:
        s.put(key('p'),a);s.get(key('p')); serial=[];threaded=[]
        with ThreadPoolExecutor(1) as pool:
            for i in range(5):
                t,_=timed(lambda:[s.get(key('p')) for _ in range(4)]);serial.append(t)
                t,_=timed(lambda:list(pool.map(lambda _:s.get(key('p')),range(4))));threaded.append(t)
        result['async_read_probe']=dict(serial=stats(serial),queued_worker=stats(threaded),scope='four full reads, pre-existing one-thread executor, not overlapped compute')
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--mode',choices=('tune','compare'),required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    report={'scope':'bounded storage only; synthetic arrays; no geological or whole-world claim',
            'runtime':{'python':platform.python_version(),'numpy':np.__version__,'blosc2':blosc2.__version__,
                       'zstd':blosc2.clib_info(blosc2.Codec.ZSTD)[1].decode(),'platform':platform.system()},
            'source_sha256':hashlib.sha256(Path(current.__file__).read_bytes()).hexdigest(),
            'baseline_storage_sha256':hashlib.sha256((args.baseline/'src/atlas_tectonics/storage.py').read_bytes()).hexdigest()}
    with tempfile.TemporaryDirectory() as tmp:
        report[args.mode]=tune(Path(tmp)) if args.mode=='tune' else comparisons(Path(tmp),load_baseline(args.baseline))
    args.out.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(args.out)


if __name__=='__main__':main()
