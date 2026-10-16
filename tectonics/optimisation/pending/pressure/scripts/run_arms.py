"""Run the pressure-stage profile arms back to back, sampling each arm's whole process tree.

Arm "spy": profile_pressure_stage.py --no-profile under py-spy (raw, --subprocesses,
--nonblocking, 100 Hz): unprofiled stage times plus sampled stacks of the parent AND any workers.
Arm "cprof": profile_pressure_stage.py with cProfile on the pressure call (exact call counts).
Each arm's tree (excluding py-spy itself) is sampled once a second: process count, summed
working set and private bytes, and CPU seconds, so the summary says how many cores the stage
keeps busy and the TOTAL peak. Writes <out>/<arm>/tree.jsonl and <out>/summary.json and prints
one compact line per arm. Requires PYTHONHASHSEED=0 (run_locked.sh exports it).
Usage: run_arms.py --out DIR --arm NAME=MODE@RUNTIME [--arm ...]
  MODE: spy (py-spy, no cProfile) | cprof (cProfile pressure) | cprof2 (cProfile admission + pressure)
        | cprofA (cProfile admission only; stops before the pressure stage)
  --extra ARG (repeatable) is passed to every arm's profile_pressure_stage.py (smoke: --extra=--small)
        a '+seed' suffix passes --seed-store SEED (run_arms.py --seed STORE@SHA256) to that arm
  RUNTIME: test:<folder> | frozen:<folder> (src/ + helpers/, e.g. composed-r2)
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
PY = sys.executable
PYSPY = str(Path(PY).parent / 'py-spy.exe')


def sample_tree(root, skip_names=('py-spy.exe',)):
    procs = [root]
    try:
        procs += root.children(recursive=True)
    except psutil.Error:
        pass
    rows = []
    for p in procs:
        try:
            with p.oneshot():
                if p.name().lower() in skip_names:
                    continue
                cpu = p.cpu_times()
                mem = p.memory_info()
                rows.append((p.pid, p.create_time(), cpu.user+cpu.system, mem.rss, getattr(mem, 'private', mem.vms)))
        except psutil.Error:
            pass
    return rows


def window(samples, lo, hi):
    """CPU/memory over the wall-clock window [lo, hi]."""
    inside = [s for s in samples if lo <= s['t'] <= hi]
    if len(inside) < 2:
        return None
    wall = inside[-1]['t']-inside[0]['t']
    # CPU seconds: per pid, last seen minus first seen inside the window (plus CPU of pids born
    # inside the window, counted from zero).
    first, last = {}, {}
    for s in inside:
        for pid, ct, cpu, _, _ in s['procs']:
            key = (pid, ct)
            first.setdefault(key, (cpu, ct))
            last[key] = cpu
    cpu = 0.
    for key, (c0, ct) in first.items():
        cpu += last[key] - (0. if ct >= lo else c0)
    busy = [s['cores'] for s in inside if s['cores'] is not None]
    return dict(wall_s=round(wall, 1), cpu_s=round(cpu, 1), mean_cores=round(cpu/wall, 2) if wall else None,
                max_procs=max(s['n'] for s in inside),
                pids=len(first),
                peak_total_wset_mib=round(max(s['wset'] for s in inside)/2**20),
                peak_total_private_mib=round(max(s['private'] for s in inside)/2**20),
                share_samples_over_1_5_cores=round(sum(b > 1.5 for b in busy)/len(busy), 3) if busy else None,
                share_samples_over_4_cores=round(sum(b > 4 for b in busy)/len(busy), 3) if busy else None)


def run_arm(name, mode, out, runtime, seed=None, extra=()):
    arm = out/name
    arm.mkdir(parents=True, exist_ok=False)
    cmd = [PY, '-B', str(HERE/'profile_pressure_stage.py'), '--output-dir', str(arm/'run'), '--runtime', runtime]
    if mode.endswith('+seed'):
        mode = mode[:-5]
        cmd += ['--seed-store', seed]
    if mode == 'cprof2':
        cmd += ['--profile-admission']
    if mode == 'cprofA':
        cmd += ['--profile-admission', '--admission-only', '--no-profile']
    cmd += list(extra)
    if mode == 'spy':
        cmd = [PYSPY, 'record', '--format', 'raw', '-o', str(arm/'pyspy.txt'), '--rate', '100',
               '--subprocesses', '--nonblocking', '--'] + cmd + ['--no-profile']
    log = open(arm/'arm.log', 'w', encoding='utf8')
    start = time.time()
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    root = psutil.Process(proc.pid)
    samples, prev = [], None
    with open(arm/'tree.jsonl', 'w', encoding='utf8') as f:
        while proc.poll() is None:
            t = time.time()
            rows = sample_tree(root)
            cpu_total = sum(r[2] for r in rows)
            cores = None
            if prev is not None:
                # Busy cores since the previous sample, from pids alive in both.
                before = {(r[0], r[1]): r[2] for r in prev[1]}
                delta = sum(r[2]-before.get((r[0], r[1]), 0.) for r in rows)
                cores = round(delta/(t-prev[0]), 2)
            s = dict(t=round(t, 2), n=len(rows), wset=sum(r[3] for r in rows), private=sum(r[4] for r in rows),
                     cpu=round(cpu_total, 2), cores=cores, procs=rows)
            samples.append(s)
            f.write(json.dumps({k: v for k, v in s.items() if k != 'procs'})+'\n')
            prev = (t, rows)
            time.sleep(1.)
    log.close()
    end = time.time()
    status = proc.returncode
    report = {}
    rp = arm/'run'/'report.json'
    if rp.is_file():
        report = json.loads(rp.read_text(encoding='utf8'))
    e = report.get('epoch', {})
    summary = dict(arm=name, mode=mode, runtime=runtime, phases=report.get('phases'), exit=status, wall_s=round(end-start, 1), times_cpu_wall_s=report.get('times_cpu_wall_s'),
                   parent_peak_wset_mib=report.get('peak_working_set_mib'),
                   parts_cpu_wall_s=report.get('parts_cpu_wall_s'), workflow_id=report.get('workflow_id'),
                   identities=report.get('identities'), seeded_store=report.get('seeded_store'),
                   store_unchanged_from_seed=report.get('store_unchanged_from_seed'),
                   store_sidecars=report.get('store_sidecars'),
                   whole=window(samples, start, end))
    if 'admission_end' in e:
        summary['admission'] = window(samples, e['admission_start'], e['admission_end'])
    if 'pressure_start' in e:
        summary['admission'] = window(samples, e['admission_start'], e['pressure_start'])
        summary['pressure'] = window(samples, e['pressure_start'], e['pressure_end'])
    return summary


REQUIRED = ('.bounds_id', '.geometry_id', '.partition_id')


def check(results):
    """Fail closed: every arm exited 0; every arm has each required identity and a real
    workflow_id; all arms agree on all of them; a seeded arm's store is unchanged from its pin and
    has no -wal/-journal/-shm. Anything missing is a failure, never a skip."""
    failures = []
    for r in results:
        name, ids, wf = r.get('arm'), r.get('identities') or {}, r.get('workflow_id')
        if r.get('exit') != 0:
            failures.append(f'{name}: exit {r.get("exit")}')
        for suffix in REQUIRED:
            if not any(k.endswith(suffix) and v for k, v in ids.items()):
                failures.append(f'{name}: missing *{suffix}')
        if not isinstance(wf, str) or not wf or wf.startswith('FAILED'):
            failures.append(f'{name}: workflow_id {wf!r}')
        if r.get('seeded_store') is not None:
            if r.get('store_unchanged_from_seed') is not True:
                failures.append(f'{name}: seeded store changed ({r.get("store_unchanged_from_seed")!r})')
            if r.get('store_sidecars') != []:
                failures.append(f'{name}: store sidecars {r.get("store_sidecars")!r}')
    if not results:
        failures.append('no arm ran')
    first = results[0] if results else {}
    for r in results[1:]:
        if (r.get('identities'), r.get('workflow_id')) != (first.get('identities'), first.get('workflow_id')):
            failures.append(f'{r.get("arm")} differs from {first.get("arm")}: identities or workflow_id')
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--arm', action='append', required=True)
    ap.add_argument('--seed', default=None)
    ap.add_argument('--extra', action='append', default=[])
    args = ap.parse_args()
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    results = []
    arms = []
    for spec in args.arm:
        name, rest = spec.split('=', 1)
        mode, runtime = rest.split('@', 1)
        if mode.endswith('+seed') and not args.seed:
            raise SystemExit('+seed needs --seed')
        if mode.removesuffix('+seed') not in ('spy', 'cprof', 'cprof2', 'cprofA'):
            raise SystemExit('bad mode '+mode)
        arms.append((name, mode, runtime))
    for name, mode, runtime in arms:
        r = run_arm(name, mode, out, runtime, args.seed, args.extra)
        results.append(r)
        (out/'summary.json').write_text(json.dumps(results, indent=1), encoding='utf8')
        p, a = r.get('pressure') or {}, r.get('admission') or {}
        print(time.strftime('%H:%M:%S'), name, 'exit', r['exit'], 'times', json.dumps(r['times_cpu_wall_s']),
              '| pressure cores', p.get('mean_cores'), 'procs', p.get('max_procs'), 'peak total MiB', p.get('peak_total_wset_mib'),
              '| admission cores', a.get('mean_cores'), 'peak', a.get('peak_total_wset_mib'),
              '| parts', json.dumps(r.get('parts_cpu_wall_s')), flush=True)
        # A failed arm (e.g. a refused seed) does not stop the next one.
    failures = check(results)
    (out/'check.json').write_text(json.dumps(dict(passed=not failures, failures=failures), indent=1), encoding='utf8')
    print('CHECK', 'PASS' if not failures else 'FAIL', json.dumps(failures), flush=True)
    sys.exit(0 if not failures else 1)


if __name__ == '__main__':
    main()
