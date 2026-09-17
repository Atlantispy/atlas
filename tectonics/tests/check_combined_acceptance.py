#!/usr/bin/env python3
"""Bounded item-12 integration/resource drill, callable on Linux or Windows.

Fresh child processes run three explicitly selected combinations. Parent sampling
includes workers and native allocations; RSS sums can double-count shared pages,
so USS/PSS are reported separately when available. Sampling can miss short peaks:
this is measured headroom evidence, never an OS-level hard memory guarantee.

No installer, repository writes, broad tuning sweep or geological simulation.
Temporary files and subprocesses are owned by this drill. Measurements deliberately
include native compilation in first use and retain five warm repetitions.
"""
from __future__ import annotations
import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024**2
CASES = ('serial-raw', 'auto-balanced', 'spawn-compact')


def digest(a):
    return hashlib.sha256(a.tobytes()).hexdigest()


def run_case(name, directory):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT/'src'))
    import numpy as np
    import scipy, numba, blosc2, threadpoolctl
    from atlas_tectonics import (ThermalParameters, FlexureParameters, PeriodicGrid1D,
        PeriodicFlexure, Rotation, advect_thickness, half_space_temperature)
    from atlas_tectonics.resources import WorkBudget, DEFAULT_BUDGET
    from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
    from atlas_tectonics.execution import KernelExecutor, ExecutionPolicy
    from atlas_tectonics.reuse import cached_temperature, PreparedInput, CachePolicy
    from atlas_tectonics._validation import frozen
    thermal=ThermalParameters('synthetic-acceptance','not Earth calibration',300.,1300.,1.)
    elastic=FlexureParameters('synthetic-acceptance','not Earth calibration',12.,1.,0.,1.,1.)
    n=262144
    mode={'serial-raw':'serial','auto-balanced':'auto','spawn-compact':'processes'}[name]
    chunk={'serial-raw':16384,'auto-balanced':65536,'spawn-compact':262144}[name]
    ceiling=(384 if mode=='processes' else 96)*MIB
    budget=WorkBudget(ceiling)
    config=StoreLimits(chunk,32*MIB,64*MIB,decoded_cache_bytes=4*MIB,
        max_manifest_bytes=128*1024,max_chunks=4096,staging_memory_bytes=32768,
        max_staging_bytes=32*MIB,verified_cache_entries=512,insert_batch_bytes=32768)
    compression=Compression(codec='raw',palette=False) if mode=='serial' else Compression(
        codec='zstd',level=3 if mode=='processes' else 1,shuffle='byte')
    # These capacities are per file/writer, not a total filesystem reservation.
    # One live DB + its journal + one staged writer + one independent backup.
    disk_capacity=3*config.max_store_bytes+config.max_staging_bytes
    if shutil.disk_usage(directory).free < disk_capacity:
        raise RuntimeError('insufficient free storage for the declared acceptance envelope')
    times=[]; outputs={}; invariants={}; executor_stats={}; store_stats={}
    os_baseline_before=None
    import psutil
    process=psutil.Process()
    os_baseline_before=process.memory_info().rss
    initialise=time.perf_counter()
    # Charge caller-owned fields and retained operator data independently of the
    # per-call scratch reservations. The lease ends only after the final consumer.
    with budget.reserve(16*MIB,category='caller-retained'):
        depths=PreparedInput(np.linspace(0,10,n),budget=budget)
        points=frozen(np.column_stack((np.linspace(0,10,16384),np.ones(16384),np.zeros(16384))))
        h=frozen(np.linspace(1.,2.,65536));u=frozen(np.sin(np.arange(65536.)/30)*.1)
        op=PeriodicFlexure(PeriodicGrid1D(n,float(n)),elastic)
        rotation=Rotation.from_axis_angle([1.,2.,3.],.3)
        # First use includes the chosen Numba backend's compilation/import cost.
        t0=time.perf_counter()
        transport=advect_thickness(h,u,PeriodicGrid1D(65536,65536.),.2,budget=budget)
        native_first=time.perf_counter()-t0
        reference=advect_thickness(h,u,PeriodicGrid1D(65536,65536.),.2,backend='reference',budget=budget)
        if transport.thickness_m.tobytes()!=reference.thickness_m.tobytes():
            raise AssertionError('native transport changed fields')
        if transport.face_flux_m2_s.tobytes()!=reference.face_flux_m2_s.tobytes():
            raise AssertionError('native transport changed face transfers')
        if transport.balance_residual_m2.hex()!=reference.balance_residual_m2.hex():
            raise AssertionError('native transport changed accounting')
        invariants['native_transport_bit_equal']=True
        del transport,reference
        initialisation=time.perf_counter()-initialise
        t0=time.perf_counter()
        with ArrayStore(directory/'state.db',config,compression,budget=budget) as store:
            policy=ExecutionPolicy(mode=mode,max_workers=2,max_inflight=2,max_work_bytes=64*MIB)
            with KernelExecutor(policy,budget=budget) as executor:
                for repeat in range(6):
                    begin=time.perf_counter()
                    # Completed cooling results are persisted while the executor
                    # may still own queued/running independent queries.
                    requests=[(depths.array,1.),(depths.array,4.)]
                    for i,value in enumerate(executor.temperatures(requests,thermal)):
                        with budget.reserve(2*value.nbytes,category='consumer-output'):
                            key=hashlib.sha256(f'cool-{repeat}-{i}'.encode()).hexdigest()
                            store.put(key,{'temperature':value},budget=budget)
                            restored=store.get(key,budget=budget)['temperature']
                            if digest(value)!=digest(restored):raise AssertionError('cooling store changed data')
                            outputs[f'cool-{i}']=digest(value)
                            del restored
                    # Complete-domain loads, never independently solved tiles.
                    load=frozen(np.sin(np.arange(n)*2*np.pi/n))
                    with budget.reserve(load.nbytes,category='caller-load'):
                        for i,value in enumerate(executor.flexure([load,load],op)):
                            with budget.reserve(2*value.nbytes,category='consumer-output'):
                                key=hashlib.sha256(f'flex-{repeat}-{i}'.encode()).hexdigest()
                                store.put(key,{'deflection':value},budget=budget)
                                restored=store.get(key,budget=budget)['deflection']
                                if digest(value)!=digest(restored):raise AssertionError('flexure store changed data')
                                outputs['flexure']=digest(value);del restored
                    del load,value
                    for value in executor.rotations([points],rotation):
                        expected=rotation.apply(points,backend='reference',budget=budget)
                        np.testing.assert_allclose(value,expected,rtol=1e-12,atol=1e-12)
                        outputs['rotation']=digest(value)
                    del value,expected
                    # Forced persistence is a correctness comparison, not a claim
                    # that the ordinary admission policy should cache cheap work.
                    always=CachePolicy(mode='always')
                    a=cached_temperature(depths,1.,thermal,store=store,budget=budget,cache_policy=always)
                    with budget.reserve(a.nbytes,category='consumer-output'):
                        b=cached_temperature(depths,1.,thermal,store=store,budget=budget,cache_policy=always)
                        if digest(a)!=digest(b):raise AssertionError('cache differed from its fresh result')
                        del b
                    del a
                    parent=hashlib.sha256(f'flex-{repeat}-0'.encode()).hexdigest()
                    before=store.statistics()['unique_chunks']
                    unchanged=hashlib.sha256(f'branch-{repeat}'.encode()).hexdigest()
                    store.put_incremental(unchanged,parent,{},budget=budget)
                    if store.statistics()['unique_chunks']!=before:
                        raise AssertionError('unchanged snapshot duplicated payloads')
                    # Replace exactly one chunk while retaining the remaining ones.
                    part=store.read_chunk(parent,'deflection',0,budget=budget)[1].copy()
                    part[0]+=1.
                    changed=hashlib.sha256(f'edited-{repeat}'.encode()).hexdigest()
                    store.put_incremental(changed,parent,{'deflection':{0:part}},budget=budget)
                    if store.get(parent,budget=budget)['deflection'][0]==part[0]:
                        raise AssertionError('branch changed its parent')
                    times.append(time.perf_counter()-begin)
                executor_stats=executor.statistics()
                invariants['no_remaining_inflight']=executor_stats['reserved_bytes']==0
            store_stats=store.statistics()
            invariants['decoded_cache_within_limit']=store_stats['decoded_cache_bytes']<=config.decoded_cache_bytes
            invariants['verified_entries_within_limit']=store_stats['verified_cache_entries']<=config.verified_cache_entries
            expected_backup=outputs['flexure']
            store.backup_to(directory/'backup.db')
            resource_allowances=store.resource_requirements()
        state_path=directory/'state.db'
        state_path.unlink()  # Own temporary drill data only; not user history.
        with ArrayStore(directory/'backup.db',config,compression,budget=budget) as backup:
            restored=backup.get(hashlib.sha256(b'flex-0-0').hexdigest(),budget=budget)['deflection']
            if digest(restored)!=expected_backup:raise AssertionError('isolated backup mismatch')
        invariants['independent_backup_after_source_removal']=True
    invariants['shared_budget_fully_released']=budget.reserved_bytes==0
    invariants['shared_budget_within_limit']=budget.peak_reserved_bytes<=ceiling
    invariants['default_budget_fully_released']=DEFAULT_BUDGET.reserved_bytes==0
    if not all(invariants.values()):raise AssertionError(invariants)
    return dict(case=name,status='PASS_BOUNDED_COMBINATION', samples_per_field=n,
        first_cycle_s=times[0],warm_cycles_s=times[1:],warm_median_s=statistics.median(times[1:]),
        initialisation_s=initialisation,native_first_call_s=native_first,
        process_rss_before_case_bytes=os_baseline_before,output_sha256=outputs,
        invariants=invariants,shared_budget=budget.statistics(),executor=executor_stats,
        storage=store_stats,storage_allowances=resource_allowances,
        declared_disk_capacity_bytes=disk_capacity,stored_bytes_after_backup=(directory/'backup.db').stat().st_size,
        runtime=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,
                     numba=numba.__version__,blosc2=blosc2.__version__,threadpoolctl=threadpoolctl.__version__,
                     sqlite=__import__('sqlite3').sqlite_version,
                     native_libraries=[{k:x.get(k) for k in ('internal_api','prefix','version','num_threads','threading_layer')}
                                       for x in threadpoolctl.threadpool_info()]))


def observe(proc, directory, timeout=90., rss_ceiling=1024*MIB):
    """Sample only the drill's process tree; a exceeded envelope fails the run.

    This watchdog can miss transient spikes and may overcount shared pages. It is
    not a substitute for allocator/OS enforcement. Never kills unrelated processes.
    """
    import psutil
    root=psutil.Process(proc.pid)
    peak=dict(rss_sum_bytes=0,uss_sum_bytes=None,pss_sum_bytes=None,processes=0,threads=0,
              largest_child_rss_bytes=0,samples=0,missing_full_info_samples=0,
              visible_storage_peak_bytes=0)
    started=time.monotonic();error=None;known={}
    while proc.poll() is None:
        try: members=[root]+root.children(recursive=True)
        except psutil.NoSuchProcess:break
        rss=uss=pss=threads=0;have_uss=have_pss=True;live=0
        for p in members:
            try:
                known[p.pid]=p
                current=p.memory_info().rss
                rss+=current;threads+=p.num_threads();live+=1
                if p.pid!=proc.pid:peak['largest_child_rss_bytes']=max(peak['largest_child_rss_bytes'],current)
                try:
                    info=p.memory_full_info()
                    if hasattr(info,'uss'):uss+=info.uss
                    else:have_uss=False
                    if hasattr(info,'pss'):pss+=info.pss
                    else:have_pss=False
                except (psutil.AccessDenied,psutil.NoSuchProcess):have_uss=have_pss=False
            except psutil.NoSuchProcess:continue
        visible_bytes=0
        for path in directory.rglob('*'):
            try:
                if path.is_file():visible_bytes+=path.stat().st_size
            except FileNotFoundError:pass
        peak['visible_storage_peak_bytes']=max(peak['visible_storage_peak_bytes'],visible_bytes)
        peak['samples']+=1
        for label,value in (('rss_sum_bytes',rss),('processes',live),('threads',threads)):
            peak[label]=max(peak[label],value)
        for label,value,available in (('uss_sum_bytes',uss,have_uss),('pss_sum_bytes',pss,have_pss)):
            if available:peak[label]=max(peak[label] or 0,value)
        if not have_uss or not have_pss:peak['missing_full_info_samples']+=1
        if rss>rss_ceiling:error='sampled process-tree RSS sum exceeded declared envelope'
        if time.monotonic()-started>timeout:error='bounded combination timeout'
        if error:
            for p in reversed(list(known.values())):
                try:p.kill()
                except (psutil.NoSuchProcess,psutil.AccessDenied):pass
            break
        time.sleep(.01)
    proc.wait(timeout=10)
    remaining=[]
    # A spawn resource-tracker may exit just after its parent. Bounded wait avoids
    # declaring a live leaked worker a successful cleanup.
    for p in known.values():
        if p.pid==proc.pid:continue
        try:
            p.wait(timeout=2)
        except psutil.TimeoutExpired:
            remaining.append(p.pid)
            try:p.kill()
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        except psutil.NoSuchProcess:pass
    if remaining:error='child processes survived completion'
    peak['sampling_interval_target_s']=.01
    peak['elapsed_monitored_s']=time.monotonic()-started
    peak['sampled_rss_ceiling_bytes']=rss_ceiling
    peak['errors']=error
    peak['notes']='RSS sums can double-count shared mappings; sample peaks may miss brief peaks. USS/PSS availability is recorded. Visible-file storage excludes unnamed temporary spools; peak_prepared_bytes separately records staged logical bytes.'
    return peak


def orchestrate():
    import psutil  # Explicit acceptance dependency, never auto-installed.
    cases=[]
    with tempfile.TemporaryDirectory(prefix='atlas-item12-') as temp:
        root=Path(temp)
        for name in CASES:
            folder=root/name;folder.mkdir()
            output=folder/'result.json';stderr=folder/'stderr.txt'
            env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',
                     NUMBA_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
            with stderr.open('w',encoding='utf-8') as log:
                proc=subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),
                    '--case',name,'--directory',str(folder),'--output',str(output)],
                    env=env,stdout=subprocess.DEVNULL,stderr=log)
                try:
                    measured=observe(proc,folder)
                except BaseException:
                    # Clean up only this owned drill tree if measurement fails.
                    try: owned=psutil.Process(proc.pid).children(recursive=True)
                    except psutil.NoSuchProcess:owned=[]
                    for child in owned:
                        try:child.kill()
                        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
                    if proc.poll() is None:proc.kill()
                    proc.wait(timeout=10)
                    raise
            if proc.returncode!=0 or measured['errors'] or not output.exists():
                raise RuntimeError(f"{name} failed ({proc.returncode}): {measured['errors']}\n"+stderr.read_text()[-6000:])
            result=json.loads(output.read_text())
            result['process_tree_memory']=measured
            cases.append(result)
    digests=[c['output_sha256'] for c in cases]
    if not all(x==digests[0] for x in digests):raise AssertionError('execution/storage combinations changed output bytes')
    return dict(schema='atlas.combined-resource-acceptance.v1',
        status='PASS_BOUNDED_CURRENT_PLATFORM',platform=platform.system(),machine=platform.machine(),
        windows_accepted=platform.system()=='Windows',measurement_dependency_psutil=psutil.__version__,
        cross_combination_outputs_bit_equal=True,cases=cases,
        scope='Three synthetic integrated combinations, five warm repeats each; not item-1 broad tuning or world simulation.',
        limitations=['Other platforms are not accepted by this run.',
            'Configured allowances are not a total process RSS cap.',
            'Sampled RSS can count shared pages more than once; see separate USS/PSS observations.',
            'No power-loss durability, GPU, distributed mechanics or geological validation.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=CASES)
    parser.add_argument('--directory',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.case:
        if args.directory is None or not args.directory.is_dir():parser.error('--case requires existing --directory')
        record=run_case(args.case,args.directory)
    else:record=orchestrate()
    text=json.dumps(record,indent=2,allow_nan=False)+'\n'
    if args.output:args.output.write_text(text,encoding='utf-8')
    else:print(text,end='')


if __name__=='__main__':
    main()
