"""A/B harness r4 (T/hs): same-call heat control on the genuine W4 call, one fresh process per arm.

r4 (16 Oct; Michael 14:05 "Memory start gates by need" and 14:08 "Have the gate predict peak usage to decide
each threshold") differs from r2 only in the start gate and in the peak records; observer, child() and every
check are r2's. r2 required a blanket 10 GiB available before each arm. r4 predicts each arm's peak and gates
on predicted x 1.2 + 1 GiB free floor + 1 GiB small-job allowance (the queue's mem_need):
  predicted = the largest measured peak of completed PASS arms with the same route (mode and layout), the
              same worker count and the same input, from --history summary.json files and the earlier arms
              of this run. Where a record has per-process peaks, parent + workers x per-worker peak is used
              when it is larger than the tree peak. Else the ticket's RUNQ_PRED_PEAK_GIB, else --pred-peak-gib.
              No prediction (or a non-positive / non-finite one) refuses the arm; it never defaults low.
Each arm records predicted_peak_gib, prediction_basis, start_gate_gib, free_gib_at_start, gate_waited_s and,
besides the tree peak, parent_peak_mib, worker_peak_mib and worker_processes. The in-run guards (12 GiB tree
working set, 1 GiB available floor) are unchanged; they are what protect the machine.

r2 (16 Oct, coordinator-approved for q10) differs from ab_heat.py only in the proof observer.
r1 used sys.setprofile with a hook that built a Path for every Python return in the parent,
which made a proof arm take 19.5 min (q03 arm-0; heat calls 27.7 + 26.9 s). r2 uses Python
3.12 sys.monitoring PY_RETURN. The callback captures exactly what r1 captured, at the same two
issuer returns (the first non-None return of the issuer file's advance_legacy_packaging, and of
its advance, which ends the observation). It returns sys.monitoring.DISABLE for every other
return site, so each such site costs one callback in the whole run. Checked before use
(scripts/check_monitor_observer.py): loaded-identity code digests unchanged, and captures
byte-identical to the r1 observer on a toy issuer flow; then one real lw proof arm compared
with q03 arm-0.

Usage (PYTHONHASHSEED=0; take the heavy-run lock around `run`):
  python -B ab_heat_r4.py run OUTDIR [--history SUMMARY.json]... [--pred-peak-gib G] MODE:LABEL:LAYOUT ...
  python -B ab_heat_r4.py child MODE LAYOUT OUTDIR K          (one arm; started by run)

Each arm runs the control's unchanged child() (C/step7_same_call_heat_control.py) on LAYOUT,
a layout prepared by that control's --prepare. That means the verbatim r12 packaging and the
compact r13 advance on ONE issued call, with 6 reconstruction workers (the module default,
recorded). Modes:
  time   nothing else: wall and CPU of both advances, and per-call reconstruction seconds and
         worker compute from functionals_parallel_r1.report()
  proof  as time, plus a read-only sys.monitoring observer. It saves the legacy result's
         canonical metadata bytes (equal to the compact ones, checked by the control) and
         every array of the r13 result, to OUTDIR/arm-K/. Proof arms are still not used for
         timing.
  prof   as time, with HS_PROF_DIR and the harness sitecustomize (T/hs/workerprof) on
         PYTHONPATH, so each reconstruction worker writes a cProfile file to OUTDIR/arm-K/
Afterwards every loaded module file under the workspace must lie in the layout's paths, the
environment or this harness: the leak check of probes/step9/.../heat_control_on_frozen.py.
run: arms in the order given (use a symmetric order such as A B B A). Before each arm the
predicted start gate (r4, above) must hold, waiting up to 10 min. The tree is sampled twice a second and ended by its own PIDs if
it passes 12 GiB working set, or if the machine falls below 1 GiB available.
"""
import json
import math
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from time import perf_counter, process_time, sleep

import psutil

HERE = Path(__file__).resolve().parent
HS = HERE.parent
WORKSPACE = HS.parent
R = WORKSPACE/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
C = R/'compact-geometry-r1'
ENV = WORKSPACE/'.r44-env'
ISSUER = 'private_heat_native_issuer_r13.py'
GIB = 1 << 30
RSS_GUARD, FREE_FLOOR = 12*GIB, 1*GIB
WORKERS = 6     # the control's reconstruction workers (module default); check_arms requires used == [6, 6]
INPUT = 'W4 same-call control (C/step7_same_call_heat_control.py)'   # the only input any ab_heat runs
WORKER_TAG = 'private_heat_functionals_parallel_r1.py'   # in every reconstruction worker's command line


def predict(arm, history, cli_gib=None):
    """(GiB, basis) of the arm's predicted tree peak, or (None, why) -> the arm is refused."""
    best = None
    for source, a in history:
        # Records written before r4 have no 'input': every ab_heat revision runs only INPUT.
        if (a.get('mode'), a.get('layout'), a.get('used'), a.get('input', INPUT)) != (
                arm['mode'], arm['layout'], [WORKERS, WORKERS], INPUT):
            continue
        if a.get('status') != 'PASS' or a.get('exit_code') != 0 or a.get('stopped') or not a.get('tree_peak_mib'):
            continue
        mib = a['tree_peak_mib']
        if a.get('parent_peak_mib') is not None and a.get('worker_peak_mib') is not None:
            mib = max(mib, a['parent_peak_mib']+WORKERS*a['worker_peak_mib'])
        if best is None or mib > best[0]:
            best = (mib, '%s arm %s' % (source, a['arm']))
    if best:
        return best[0]/1024, 'measured: %s, %d MiB' % (best[1], best[0])
    for name, value in (('RUNQ_PRED_PEAK_GIB', os.environ.get('RUNQ_PRED_PEAK_GIB')), ('--pred-peak-gib', cli_gib)):
        if value is None or value == '':
            continue
        try:
            gib = float(value)
        except ValueError:
            return None, '%s=%r is not a number' % (name, value)
        if not (math.isfinite(gib) and gib > 0):
            return None, '%s=%r is not a positive finite peak' % (name, value)
        return gib, 'fallback %s (no measured arm of this route)' % name
    return None, 'no measured arm of this route, no RUNQ_PRED_PEAK_GIB, no --pred-peak-gib'


def _worker_groups(members, tags):
    """{pid: group} for reconstruction-worker processes; group = the outermost worker-tagged ancestor (a
    worker may be a venv launcher plus the interpreter it starts, both with the worker command line)."""
    for m in members:
        if m.pid not in tags:
            try:
                tags[m.pid] = (WORKER_TAG in ' '.join(m.cmdline()), m.ppid())
            except psutil.Error:
                pass        # counted as the arm's own this sample; asked again next sample
    groups = {}
    for m in members:
        if m.pid in tags and tags[m.pid][0]:
            pid = m.pid
            while tags.get(tags[pid][1], (False,))[0]:
                pid = tags[pid][1]
            groups[m.pid] = pid
    return groups


def _observer(directory):
    """Read-only sys.monitoring observer; returns stop(). Same captures as r1's setprofile hook."""
    import numpy as np
    directory.mkdir(parents=True, exist_ok=True)
    M = sys.monitoring
    tool = next(i for i in range(6) if M.get_tool(i) is None)
    M.use_tool_id(tool, 'ab_heat_r2 proof observer')
    targets = ('advance_legacy_packaging', 'advance')

    def stop():
        M.set_events(tool, 0)
        M.register_callback(tool, M.events.PY_RETURN, None)
        M.free_tool_id(tool)

    def on_return(code, offset, retval):
        if code.co_name not in targets or Path(code.co_filename).name != ISSUER:
            return M.DISABLE                 # never a capture site: this return site is not seen again
        if retval is None:
            return None
        if code.co_name == 'advance_legacy_packaging':
            (directory/'legacy_metadata.json').write_bytes(bytes(retval._snapshot._metadata))
        else:
            M.set_events(tool, 0)            # observation ends here, as r1's hook removed itself here
            names = list(retval.array_names)
            for array in names:
                np.save(directory/(array+'.npy'), np.array(retval.array(array), copy=True))
            (directory/'arrays.json').write_text(json.dumps({a: list(retval.array(a).shape) for a in names}),
                                                 encoding='utf8')
        return None

    M.register_callback(tool, M.events.PY_RETURN, on_return)
    M.set_events(tool, M.events.PY_RETURN)
    return stop


def child(mode, layout, outdir, k):
    layout, outdir = Path(layout).resolve(), Path(outdir)
    info = json.loads((layout/'control.json').read_text(encoding='utf8'))
    paths = info['paths']
    sys.path[:0] = paths
    import private_heat_functionals_parallel_r1 as PAR
    where = Path(PAR.__file__).resolve()
    if not any(where.parent == Path(p).resolve() for p in paths):
        raise SystemExit('functionals_parallel_r1 did not load from the layout')
    workers = PAR.configure()
    del sys.path[:len(paths)]          # the control's child puts them first itself
    sys.path.append(str(C))
    import step7_same_call_heat_control as CONTROL
    out = outdir/f'arm-{k}.json'
    me = psutil.Process()
    t0, c0 = perf_counter(), process_time()
    stop = _observer(outdir/f'arm-{k}') if mode == 'proof' else None
    try:
        CONTROL.child(str(layout), str(out))
    finally:
        if stop is not None:
            stop()
    wall, cpu = perf_counter()-t0, process_time()-c0
    report = PAR.report()
    allowed = [Path(p).resolve() for p in paths]
    own = {Path(__file__).resolve(), Path(CONTROL.__file__).resolve()}
    leaks = sorted({str(Path(m.__file__).resolve()) for m in list(sys.modules.values())
                    if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(WORKSPACE)
                    and not Path(m.__file__).resolve().is_relative_to(ENV)
                    and not Path(m.__file__).resolve().is_relative_to(HS/'workerprof')
                    and Path(m.__file__).resolve() not in own
                    and not any(Path(m.__file__).resolve().is_relative_to(a) for a in allowed)})
    result = json.loads(out.read_text(encoding='utf8'))
    calls = [dict({n: call[n] for n in ('faces', 'to_reconstruct', 'workers', 'collected', 'in_caller', 'fallback',
                                        'restarted', 'ready_seconds', 'seconds', 'slowest_face_seconds')},
                  worker_compute_seconds=round(sum(r['compute_seconds'] for r in call['processes']), 3),
                  worker_working_set_peak_max=max((r['working_set_peak_bytes'] for r in call['processes']), default=0))
             for call in report['calls']]
    helpers = Path(paths[1]) if len(paths) > 1 else layout/'helpers'
    result['ab'] = dict(mode=mode, layout=str(layout), workers_configured=workers, calls=calls,
                        fallbacks=report['fallbacks'], control_wall_seconds=round(wall, 3),
                        parent_cpu_seconds=round(cpu, 3), leaks=leaks,
                        exact_growth_sha256=sha256((helpers/'private_heat_exact_growth_r1.py').read_bytes()).hexdigest(),
                        gmp_resources_sha256=sha256((helpers/'private_heat_gmp_resources_r1.py').read_bytes()).hexdigest(),
                        parent_peak_working_set=me.memory_info().peak_wset)
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf8')
    print(json.dumps(dict(mode=mode, status=result['status'], leaks=len(leaks),
                          recon=[c['seconds'] for c in calls], wall=round(wall, 1))), flush=True)


def _tree(process):
    try:
        return [process, *process.children(recursive=True)]
    except psutil.Error:
        return [process]


def run(outdir, specs, history_files=(), pred_cli=None):
    history = []
    for name in history_files:      # unreadable history fails here, before OUTDIR exists
        history += [(str(name), a) for a in json.loads(Path(name).read_text(encoding='utf8'))['arms']]
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    arms = []
    for k, spec in enumerate(specs):
        mode, label, layout = spec.split(':', 2)
        if mode not in ('time', 'proof', 'prof'):
            raise SystemExit('mode must be time, proof or prof')
        arm = dict(arm=k, mode=mode, label=label, layout=str(Path(layout).resolve()))
        arms.append(arm)
        predicted, basis = predict(arm, history+[('this run', a) for a in arms[:-1]], pred_cli)
        arm.update(input=INPUT, predicted_peak_gib=None if predicted is None else round(predicted, 3),
                   prediction_basis=basis)
        if predicted is None:
            arm['stopped'] = 'start gate: no peak prediction'
            break
        gate = int((predicted*1.2+2)*GIB)
        waited = 0
        free = psutil.virtual_memory().available
        while free < gate and waited < 600:
            sleep(15)
            waited += 15
            free = psutil.virtual_memory().available
        arm.update(start_gate_gib=round(gate/GIB, 2), free_gib_at_start=round(free/GIB, 2), gate_waited_s=waited)
        if free < gate:
            arm['stopped'] = 'start gate'
            break
        env = dict(os.environ, PYTHONHASHSEED='0', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
        if mode == 'prof':
            (outdir/f'arm-{k}').mkdir()
            env['HS_PROF_DIR'] = str((outdir/f'arm-{k}').resolve())
            env['PYTHONPATH'] = str(HS/'workerprof')
        command = [sys.executable, '-B', str(Path(__file__).resolve()), 'child', mode, arm['layout'],
                   str(outdir.resolve()), str(k)]
        began = perf_counter()
        cpu0 = psutil.cpu_times()
        with open(outdir/f'arm-{k}.log', 'wb') as handle:
            process = subprocess.Popen(command, cwd=C, env=env, stdout=handle, stderr=subprocess.STDOUT)
            watched = psutil.Process(process.pid)
            peak_ws, low = 0, psutil.virtual_memory().available
            parent_peak, worker_peak, worker_pids, tags = 0, 0, set(), {}
            while process.poll() is None:
                members = _tree(watched)
                groups = _worker_groups(members, tags)
                ws, own, per_worker = 0, 0, {}
                for m in members:
                    try:
                        rss = m.memory_info().rss
                    except psutil.Error:
                        continue
                    ws += rss
                    if m.pid in groups:
                        per_worker[groups[m.pid]] = per_worker.get(groups[m.pid], 0)+rss
                    else:
                        own += rss
                available = psutil.virtual_memory().available
                peak_ws, low = max(peak_ws, ws), min(low, available)
                parent_peak, worker_peak = max(parent_peak, own), max([worker_peak, *per_worker.values()])
                worker_pids.update(per_worker)
                if ws > RSS_GUARD or available < FREE_FLOOR:
                    arm['stopped'] = f'guard: tree {ws} B, available {available} B'
                    for m in reversed(members):
                        try:
                            m.kill()
                        except psutil.Error:
                            pass
                    break
                sleep(.5)
            process.wait()
        cpu1 = psutil.cpu_times()
        busy = (sum(cpu1._asdict().values())-cpu1.idle)-(sum(cpu0._asdict().values())-cpu0.idle)
        arm.update(exit_code=process.returncode, arm_wall_seconds=round(perf_counter()-began, 2),
                   tree_peak_mib=peak_ws >> 20, available_low_mib=low >> 20, machine_busy_cpu_seconds=round(busy, 1),
                   parent_peak_mib=parent_peak >> 20, worker_peak_mib=worker_peak >> 20, worker_processes=len(worker_pids))
        out = outdir/f'arm-{k}.json'
        if process.returncode == 0 and out.is_file():
            res = json.loads(out.read_text(encoding='utf8'))
            ab = res['ab']
            own = ab['parent_cpu_seconds']+sum(c['worker_compute_seconds'] for c in ab['calls'])
            arm.update(status=res['status'], leaks=len(ab['leaks']), legacy_s=round(res['legacy']['seconds'], 2),
                       compact_s=round(res['compact']['seconds'], 2), recon_s=[c['seconds'] for c in ab['calls']],
                       worker_cpu_s=[c['worker_compute_seconds'] for c in ab['calls']],
                       fallback=[c['fallback'] for c in ab['calls']], used=[c['workers'] for c in ab['calls']],
                       other_load_cpus=round((busy-own)/max(arm['arm_wall_seconds'], 1e-9), 2),
                       arrays=res['arrays'], result_id=res['compact']['result_id'],
                       exact_growth=ab['exact_growth_sha256'][:12], gmp_resources=ab['gmp_resources_sha256'][:12])
        else:
            arm.setdefault('stopped', 'arm did not complete; see its log')
            break
    (outdir/'summary.json').write_text(json.dumps(dict(arms=arms), indent=1), encoding='utf8')
    print('arm mode label status leaks legacy_s compact_s recon_s worker_cpu_s other_cpus tree_MiB exact_growth')
    for a in arms:
        if 'status' not in a:
            print(a['arm'], a['mode'], a['label'], 'STOPPED', a.get('stopped'))
            continue
        print(a['arm'], a['mode'], a['label'], a['status'], a['leaks'], a['legacy_s'], a['compact_s'], a['recon_s'],
              a['worker_cpu_s'], a['other_load_cpus'], a['tree_peak_mib'], a['exact_growth'])


def main():
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    if sys.argv[1] == 'child':
        child(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))
    elif sys.argv[1] == 'run':
        args, history, pred = sys.argv[3:], [], None
        while args[:1] and args[0].startswith('--'):
            if args[0] == '--history':
                history.append(args[1])
            elif args[0] == '--pred-peak-gib':
                pred = args[1]
            else:
                raise SystemExit('unknown option %s' % args[0])
            args = args[2:]
        run(sys.argv[2], args, history, pred)
    else:
        raise SystemExit('run or child')


if __name__ == '__main__':
    main()
