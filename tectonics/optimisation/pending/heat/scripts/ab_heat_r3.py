"""A/B harness r3 (T/hs): same-call heat control on the genuine W4 call, one fresh process per arm.

r3 (16 Oct, Michael 14:05 "Memory start gates by need") differs from r2 only in the start gate. r2 required
a blanket 10 GiB available before each arm. r3 requires the arm's projected need: peak x 1.2 + 1 GiB free
floor + 1 GiB small-job allowance (the queue's mem_need). It is taken from --start-gate-gib if given, else
from the ticket's RUNQ_MEM_NEED_GIB, else from the measured W4 tree peak (q03: 1.05 GiB, so 3.26 GiB).
A gate below 2 GiB (floor + allowance) is refused. Each arm records its gate, the gate's source and the
free memory at its start. The in-run guards (12 GiB tree working set, 1 GiB available floor) are
unchanged; they are what protect the machine. The observer, child() and every check are r2's.

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
  python -B ab_heat_r3.py run OUTDIR [--start-gate-gib G] MODE:LABEL:LAYOUT [MODE:LABEL:LAYOUT ...]
  python -B ab_heat_r3.py child MODE LAYOUT OUTDIR K          (one arm; started by run)

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
start gate (r3, above) must hold, waiting up to 10 min. The tree is sampled twice a second and ended by its own PIDs if
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
MEASURED_PEAK_GIB = 1.05   # q03 (evidence/h12-r1): W4 lw arm tree peak


def start_gate(cli_gib=None):
    """(bytes, GiB, source) of the per-arm start gate: projected peak x 1.2 + 1 GiB floor + 1 GiB small."""
    if cli_gib is not None:
        gib, source = cli_gib, '--start-gate-gib'
    elif os.environ.get('RUNQ_MEM_NEED_GIB'):
        gib, source = float(os.environ['RUNQ_MEM_NEED_GIB']), 'RUNQ_MEM_NEED_GIB'
    else:
        gib, source = round(MEASURED_PEAK_GIB*1.2+2, 2), 'measured W4 peak %.2f GiB (q03)' % MEASURED_PEAK_GIB
    if not (math.isfinite(gib) and gib >= 2.0):
        raise SystemExit('start gate %r GiB is below the 1 GiB floor + 1 GiB small-job allowance' % gib)
    return int(gib*GIB), gib, source


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


def run(outdir, specs, gate_gib=None):
    gate, gate_gib, gate_source = start_gate(gate_gib)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    arms = []
    for k, spec in enumerate(specs):
        mode, label, layout = spec.split(':', 2)
        if mode not in ('time', 'proof', 'prof'):
            raise SystemExit('mode must be time, proof or prof')
        arm = dict(arm=k, mode=mode, label=label, layout=str(Path(layout).resolve()))
        arms.append(arm)
        waited = 0
        free = psutil.virtual_memory().available
        while free < gate and waited < 600:
            sleep(15)
            waited += 15
            free = psutil.virtual_memory().available
        arm.update(start_gate_gib=gate_gib, start_gate_source=gate_source, free_gib_at_start=round(free/GIB, 2),
                   gate_waited_s=waited)
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
            while process.poll() is None:
                members = _tree(watched)
                ws = 0
                for m in members:
                    try:
                        ws += m.memory_info().rss
                    except psutil.Error:
                        pass
                available = psutil.virtual_memory().available
                peak_ws, low = max(peak_ws, ws), min(low, available)
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
                   tree_peak_mib=peak_ws >> 20, available_low_mib=low >> 20, machine_busy_cpu_seconds=round(busy, 1))
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
        args, gate_gib = sys.argv[3:], None
        if args[:1] == ['--start-gate-gib']:
            gate_gib, args = float(args[1]), args[2:]
        run(sys.argv[2], args, gate_gib)
    else:
        raise SystemExit('run or child')


if __name__ == '__main__':
    main()
