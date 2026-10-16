"""A/B harness r7 (T/hs): same-call heat control on the genuine W4 call, one fresh process per arm.

r5 (16 Oct; Michael 14:05 "Memory start gates by need" and 14:08 "Have the gate predict peak usage to decide
each threshold") differs from r2 only in the start gate and in the peak records; observer, child() and every
check are r2's. r2 required a blanket 10 GiB available before each arm. r5 predicts each arm's peak and gates
on predicted x 1.2 + 1 GiB free floor + 1 GiB small-job allowance (the queue's mem_need):
  predicted = the largest measured peak of completed PASS arms with the same route (mode and layout), the
              same worker count and the same input, from --history summary.json files and the earlier arms
              of this run. Where a record has per-process peaks, parent + workers x per-worker peak is used
              when it is larger than the tree peak. Else the ticket's RUNQ_PRED_PEAK_GIB, else --pred-peak-gib.
              No prediction (or a non-positive / non-finite one) refuses the arm; it never defaults low.
Each arm records predicted_peak_gib, prediction_basis, start_gate_gib, free_gib_at_start, gate_waited_s and,
besides the tree peak, parent_peak_mib, worker_peak_mib and worker_processes. The in-run guards (12 GiB tree
working set, 1 GiB available floor) are unchanged; they are what protect the machine.

r7 (16 Oct) answers r6's independent refuter (one medium point, four minor); everything else is r6's:
  (a') r6 ignored serial-fallback records. A worker that dies mid-call still leaves used == [6, 6] and a
       PASS arm, possibly with the largest peak, so ignoring it could LOWER a gate. r7 counts such a record
       only upward: it raises a prediction above a clean measurement or a fallback value and is never the
       only basis (fallback-only history with no valid RUNQ_PRED_PEAK_GIB / --pred-peak-gib refuses). r7
       never predicts lower than r5 for the same input; its one new start is r6 (b).
  - the first arm of every route is predicted before OUTDIR exists or any arm runs: a missing basis, an
    invalid record or a non-finite gate refuses at once, not after earlier arms ran;
  - a peak too large for a float, a non-finite parent + 6 x worker sum or a non-finite gate refuses; a
    record without 'arm' no longer raises KeyError;
  - each layout must hold the control.json its child reads.

r6 (16 Oct) fixes the four minor points of r5's independent refuter; gate formula, guards, observer, child()
and outputs are r5's:
  (a) an arm whose heat call fell back to serial (fallback != [None, None]) is not a measured peak of the
      worker route, so it can no longer lower a later arm's gate;
  (b) an invalid RUNQ_PRED_PEAK_GIB is skipped (and named in the basis) and --pred-peak-gib is used; with
      no valid value the arm is refused, as before;
  (c) history must be a summary with an arms list of records, checked before OUTDIR exists; a matching
      PASS record whose tree peak is not a finite number > 0, or whose parent/worker peak is not a finite
      number >= 0, refuses the arm (it is never skipped: it might have been the largest);
  (d) every arm spec is parsed before OUTDIR exists or any arm starts, and an option after the specs is
      refused.

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
  python -B ab_heat_r7.py run OUTDIR [--history SUMMARY.json]... [--pred-peak-gib G] MODE:LABEL:LAYOUT ...
  python -B ab_heat_r7.py child MODE LAYOUT OUTDIR K          (one arm; started by run)

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
predicted start gate (r5, above) must hold, waiting up to 10 min. The tree is sampled twice a second and ended by its own PIDs if
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


def _peak(value, positive):
    """A measured peak in MiB as a finite float (> 0 when positive, else >= 0), else None (r7: also an int
    too large for a float)."""
    if type(value) not in (int, float):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        return None
    return value


def _gate(predicted):
    """The start gate in bytes for a predicted peak in GiB, or None if it is not finite (r7)."""
    gate = (predicted*1.2+2)*GIB
    return int(gate) if math.isfinite(gate) else None


def predict(arm, history, cli_gib=None):
    """(GiB, basis) of the arm's predicted tree peak, or (None, why) -> the arm is refused."""
    best = tainted = None
    for source, a in history:
        # Records written before r5 have no 'input': every ab_heat revision runs only INPUT.
        if (a.get('mode'), a.get('layout'), a.get('used'), a.get('input', INPUT)) != (
                arm['mode'], arm['layout'], [WORKERS, WORKERS], INPUT):
            continue
        if a.get('status') != 'PASS' or a.get('exit_code') != 0 or a.get('stopped'):
            continue
        where = '%s arm %s' % (source, a.get('arm'))
        mib = _peak(a.get('tree_peak_mib'), True)
        if mib is None:     # r6 (c): never skipped, it might have been the largest
            return None, 'invalid measured tree_peak_mib %r in %s' % (a.get('tree_peak_mib'), where)
        if a.get('parent_peak_mib') is not None or a.get('worker_peak_mib') is not None:
            parent, worker = _peak(a.get('parent_peak_mib'), False), _peak(a.get('worker_peak_mib'), False)
            if parent is None or worker is None:
                return None, 'invalid measured parent/worker peak %r/%r in %s' % (
                    a.get('parent_peak_mib'), a.get('worker_peak_mib'), where)
            mib = max(mib, parent+WORKERS*worker)
        if not math.isfinite(mib):
            return None, 'measured peak of %s is not finite' % where
        if a.get('fallback') == [None, None]:
            if best is None or mib > best[0]:
                best = (mib, where)
        elif tainted is None or mib > tainted[0]:
            # r7 (a): a call fell back to serial; a worker may have died after growing. Such a record may
            # raise a prediction, never lower one, and is never its only basis.
            tainted = (mib, where)
    if best:
        if tainted and tainted[0] > best[0]:
            return tainted[0]/1024, 'measured: %s, %d MiB (serial-fallback record, above clean %s, %d MiB)' % (
                tainted[1], tainted[0], best[1], best[0])
        return best[0]/1024, 'measured: %s, %d MiB' % (best[1], best[0])
    skipped = []        # r6 (b): an invalid value is skipped and named; none valid -> refuse
    for name, value in (('RUNQ_PRED_PEAK_GIB', os.environ.get('RUNQ_PRED_PEAK_GIB')), ('--pred-peak-gib', cli_gib)):
        if value is None or value == '':
            continue
        try:
            gib = float(value)
        except (TypeError, ValueError):
            skipped.append('%s=%r is not a number' % (name, value))
            continue
        if not (math.isfinite(gib) and gib > 0):
            skipped.append('%s=%r is not a positive finite peak' % (name, value))
            continue
        note = ''.join('; skipped '+s for s in skipped)
        if tainted and tainted[0]/1024 > gib:
            return tainted[0]/1024, 'measured: %s, %d MiB (serial-fallback record, above fallback %s=%s)%s' % (
                tainted[1], tainted[0], name, value, note)
        return gib, 'fallback %s (no measured arm of this route)%s%s' % (
            name, note, '' if not tainted else '; above serial-fallback %s, %d MiB' % (tainted[1], tainted[0]))
    if tainted:
        return None, ('only serial-fallback records of this route (largest %s, %d MiB) and no valid '
                      'RUNQ_PRED_PEAK_GIB or --pred-peak-gib%s' % (tainted[1], tainted[0], ''.join('; '+s for s in skipped)))
    if skipped:
        return None, '; '.join(skipped)
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
            pid, steps = m.pid, 0      # bounded: a PID-reuse cycle in stale tags must not hang the guard loop
            while tags.get(tags[pid][1], (False,))[0] and steps < len(tags):
                pid, steps = tags[pid][1], steps+1
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


def _history(name):
    """(source, record) pairs of one summary.json; a malformed file raises (r6 (c), before OUTDIR exists)."""
    data = json.loads(Path(name).read_text(encoding='utf8'))
    if type(data) is not dict or type(data.get('arms')) is not list or any(type(a) is not dict for a in data['arms']):
        raise ValueError('%s: a summary with an arms list of records is required' % name)
    return [(str(name), a) for a in data['arms']]


def _specs(specs):
    """Every arm, parsed before OUTDIR exists or any arm starts (r6 (d))."""
    parsed = []
    for k, spec in enumerate(specs):
        parts = spec.split(':', 2)
        if len(parts) != 3 or parts[0] not in ('time', 'proof', 'prof') or not parts[2]:
            raise SystemExit('arm spec %d %r: MODE:LABEL:LAYOUT, mode time, proof or prof' % (k, spec))
        layout = Path(parts[2]).resolve()
        if not (layout/'control.json').is_file():     # r7: the child reads it; a typo must not surface late
            raise SystemExit('arm spec %d %r: layout %s has no control.json' % (k, spec, layout))
        parsed.append(dict(arm=k, mode=parts[0], label=parts[1], layout=str(layout)))
    return parsed


def _preflight(parsed, history, pred_cli):
    """r7: the first arm of every route needs a finite gate before OUTDIR exists or any arm starts. A later
    arm of a route has the same history and fallbacks plus this run's records; the loop still checks it."""
    for arm in parsed:
        if any((p['mode'], p['layout']) == (arm['mode'], arm['layout']) for p in parsed[:arm['arm']]):
            continue
        predicted, basis = predict(arm, history, pred_cli)
        if predicted is None or _gate(predicted) is None:
            raise SystemExit('arm %d %s:%s: no finite start-gate prediction, refused before any arm runs: %s' % (
                arm['arm'], arm['mode'], arm['label'], basis))


def run(outdir, specs, history_files=(), pred_cli=None):
    history = []
    for name in history_files:      # unreadable or malformed history fails here, before OUTDIR exists
        history += _history(name)
    parsed = _specs(specs)
    _preflight(parsed, history, pred_cli)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    arms = []
    for arm in parsed:
        k, mode = arm['arm'], arm['mode']
        arms.append(arm)
        predicted, basis = predict(arm, history+[('this run', a) for a in arms[:-1]], pred_cli)
        arm.update(input=INPUT, predicted_peak_gib=None if predicted is None else round(predicted, 3),
                   prediction_basis=basis)
        if predicted is None:
            arm['stopped'] = 'start gate: no peak prediction'
            break
        gate = _gate(predicted)
        if gate is None:
            arm['stopped'] = 'start gate: prediction not finite'
            break
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
        late = [a for a in args if a.startswith('--')]
        if late:
            raise SystemExit('options must come before the arm specs: %s' % ' '.join(late))
        run(sys.argv[2], args, history, pred)
    else:
        raise SystemExit('run or child')


if __name__ == '__main__':
    main()
