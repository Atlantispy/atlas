"""ABBA fresh-process captured-call component comparison. Not an interval benchmark.

python -B measure.py --scripts G --base TREE --candidate TREE --capture DIR --out NEW.json
                    [--sample 128 --repeat 3]
Use --sample 8 --repeat 1 for the required representative entry-point trial.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import pickle
import statistics
import subprocess
import sys
import time
import traceback

p = argparse.ArgumentParser()
for name in ('scripts', 'base', 'candidate', 'capture', 'out'):
    p.add_argument('--'+name, required=True)
p.add_argument('--sample', type=int, default=128)
p.add_argument('--repeat', type=int, default=3)
p.add_argument('--arm', choices=('A', 'B'))
a = p.parse_args()
if os.environ.get('PYTHONHASHSEED') != '0' or sys.flags.isolated:
    raise SystemExit('requires PYTHONHASHSEED=0 without -I')
if a.sample < 1 or a.repeat < 1:
    raise SystemExit('sample and repeat must be positive')
out = Path(a.out)

def memory():
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(c), c.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return dict(working_set_bytes=c.WorkingSetSize, process_peak_working_set_bytes=c.PeakWorkingSetSize,
                    source='Windows GetProcessMemoryInfo; process lifetime peak')
    import psutil
    m = psutil.Process().memory_info()
    import resource
    return dict(working_set_bytes=m.rss, process_peak_working_set_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                source='psutil RSS and Linux getrusage process lifetime peak')

def manifest(tree):
    tree = Path(tree).resolve()
    raw = (tree/'TEST_COMPOSITION.json').read_bytes()
    record = json.loads(raw)
    sizes = {}
    for rel, expected in record['files'].items():
        data = (tree/rel).read_bytes()
        if sha256(data).hexdigest() != expected:
            raise ValueError('manifest mismatch '+str(tree/rel))
        sizes[rel] = len(data)
    package = {str(path.relative_to(tree)): path.stat().st_size
               for path in (tree/'atlas_tectonics').rglob('*') if path.is_file()
               and '__pycache__' not in path.parts}
    return dict(root=str(tree), manifest_sha256=sha256(raw).hexdigest(),
                manifest_file_bytes=sum(sizes.values()), manifest_file_count=len(sizes),
                package_bytes=sum(package.values()), package_file_count=len(package))

def child():
    selected = a.base if a.arm == 'A' else a.candidate
    binding = manifest(selected)
    sys.path.insert(0, str(Path(a.scripts).resolve()))
    import rc1_env
    rc1_env.install('test:'+Path(selected).resolve().as_posix())
    from atlas_tectonics import integration_wall_measures as W, exact_arithmetic as X
    from atlas_tectonics.resources import WorkBudget
    assert X.selection()['backend'] == 'gmpy2'
    if a.arm == 'B':
        from atlas_tectonics import integration_wall_measures_gmp as D
        assert D._resident() and D._module is W
    class Arena:
        def __init__(self):
            self.resource = WorkBudget(16 << 30)
        def work(self, count):
            pass
    jobs, captures = {}, {}
    for kind in ('clip2', 'rotated_normal', 'line'):
        raw = (Path(a.capture)/('calls-'+kind+'.pkl')).read_bytes()
        records = pickle.loads(raw)
        if not records:
            raise ValueError('empty captures '+kind)
        count = min(a.sample, len(records))
        indices = sorted({i*len(records)//count for i in range(count)})
        jobs[kind] = []
        for i in indices:
            argbytes, expected, _ = records[i]
            args = pickle.loads(argbytes)
            arena = Arena() if kind != 'line' else None
            callargs = (*args, arena) if arena is not None else args
            jobs[kind].append((callargs, expected, arena))
        captures[kind] = dict(file_sha256=sha256(raw).hexdigest(), total_records=len(records), indices=indices)
    # Correctness and warm-up are outside measured loops; there are no patched kernels/counters.
    for kind, rows in jobs.items():
        fn = getattr(W, '_'+kind)
        for callargs, expected, arena in rows:
            result = fn(*callargs)
            assert pickle.dumps(result, 5) == expected, 'captured value mismatch '+kind
            assert arena is None or arena.resource.reserved_bytes == 0
    before = memory()
    measurements = {}
    for kind, rows in jobs.items():
        fn = getattr(W, '_'+kind)
        callargs_only = [row[0] for row in rows]
        start_wall, start_cpu = time.perf_counter(), time.process_time()
        for _ in range(a.repeat):
            for callargs in callargs_only:
                fn(*callargs)
        elapsed_cpu, elapsed_wall = time.process_time()-start_cpu, time.perf_counter()-start_wall
        measurements[kind] = dict(calls=a.repeat*len(rows), wall_seconds=elapsed_wall, cpu_seconds=elapsed_cpu)
    after = memory()
    for rows in jobs.values():
        for _, _, arena in rows:
            assert arena is None or arena.resource.reserved_bytes == 0
    return dict(verdict='PASS', arm=a.arm, runtime=binding, backend=X.selection(),
                captured=captures, measurements=measurements, memory_before=before, memory_after=after,
                timing_scope='unpatched captured leaf kernels; input/budget setup and validation excluded',
                arena_scope='matching no-op work arena; real _Arena covered separately by checker',
                warmup='one validated replay of selected calls per fresh process',
                sample=a.sample, repeat=a.repeat)

def parent():
    records = []
    for i, arm in enumerate('ABBA'):
        dest = out.with_name(out.stem+'-'+str(i+1)+'-'+arm+'.json')
        if dest.exists():
            raise ValueError('arm output already exists: '+str(dest))
        env = {k:v for k,v in os.environ.items() if not k.upper().startswith('PYTHON')}
        env.update(PYTHONHASHSEED='0', ATLAS_EXACT_ARITHMETIC='gmpy2')
        command = [sys.executable, '-B', str(Path(__file__).resolve()), '--scripts', a.scripts,
                   '--base', a.base, '--candidate', a.candidate, '--capture', a.capture,
                   '--out', str(dest), '--sample', str(a.sample), '--repeat', str(a.repeat), '--arm', arm]
        done = subprocess.run(command, env=env, text=True, capture_output=True)
        if done.returncode or not dest.exists():
            raise RuntimeError(dict(arm=arm, exit=done.returncode, stdout=done.stdout, stderr=done.stderr))
        record = json.loads(dest.read_text())
        if record.get('verdict') != 'PASS':
            raise ValueError(record)
        records.append(record)
        print(json.dumps(dict(arm=arm, completed=i+1)), flush=True)
    assert all(r['captured'] == records[0]['captured'] for r in records)
    assert records[0]['runtime'] == records[3]['runtime']
    assert records[1]['runtime'] == records[2]['runtime']
    comparison = {}
    for kind in records[0]['measurements']:
        baseline = [r['measurements'][kind]['wall_seconds'] for r in records if r['arm'] == 'A']
        candidate = [r['measurements'][kind]['wall_seconds'] for r in records if r['arm'] == 'B']
        comparison[kind] = dict(base_wall_seconds=baseline, candidate_wall_seconds=candidate,
                               median_base_over_candidate=statistics.median(baseline)/statistics.median(candidate))
    return dict(verdict='PASS', scope='captured-call component measurement only; no interval speedup claim',
                sequence='ABBA', records=records, comparison=comparison,
                disk=dict(base=records[0]['runtime'], candidate=records[1]['runtime']),
                script_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                limits='Two fresh processes per arm; process lifetime peaks include imports and validation. '
                       'No allocation/RSS attribution to individual kernel; no summed whole-interval gain.')

try:
    report = child() if a.arm else parent()
except Exception as exc:
    report = dict(verdict='FAIL', error=repr(exc), traceback=traceback.format_exc())
out.write_text(json.dumps(report, indent=1)+'\n')
print(json.dumps(dict(verdict=report['verdict'], output=str(out))), flush=True)
raise SystemExit(0 if report['verdict'] == 'PASS' else 1)
