"""H4: heat polygon reconstruction worker count, identity and timing on the genuine W4 call (read-only).

Usage:
  python -B h4_heat_workers.py run LAYOUT OUTDIR REFERENCE N [N ...]
  python -B h4_heat_workers.py child LAYOUT OUT_JSON N REFERENCE      (one arm; started by run)

LAYOUT is a prepared same-call control layout (step7_same_call_heat_control --prepare, for
instance probes/step8/g13l1); REFERENCE its reviewed control output (g13-same-call-live1.json).

child: puts the layout's import paths first exactly as the control's child does, imports the
layout's own private_heat_functionals_parallel_r1 and sets its worker count through its public
configure() (the documented driver route; no code object, attribute or file is changed), then
runs the control's unchanged child(). Both advances of the call (verbatim r12 packaging and
compact r13) reconstruct their faces on the configured workers. Afterwards the module's own
report() gives every reconstruction call (workers used, seconds, per-worker compute and peaks).
The arm is IDENTICAL only if the control PASSes and its arrays, result IDs and metadata digests
of both packagings equal REFERENCE's: same layout, same paths, so nothing may differ; a None or
missing value is a difference. System load during the arm (busy logical CPUs from psutil.cpu_times,
minus this arm's own parent and worker CPU) is recorded as a noise indicator, and so are the global
hooks (profile/trace functions, tracemalloc, monitoring tools) before and after the control: none
is installed here. OUT_JSON must not exist.

run: one fresh process an arm, in the order given (give a symmetric order, e.g. 6 8 10 12 8 6,
so drift cancels). Before each arm the 10 GiB start gate must hold (waits up to 10 minutes);
while it runs the process tree is sampled twice a second and ended by its own PIDs if it
exceeds 12 GiB working set or the machine falls below 1 GiB available. OUTDIR must not exist.
Writes OUTDIR/arm-K.json, OUTDIR/arm-K.log and OUTDIR/summary.json (exclusive creation); prints
the table. Run it as an EXCLUSIVE queue ticket (runq.py run): it times worker counts.

FAIL CLOSED (review 16 Oct 2026). summary.json records every arm's start-gate decision, and for
every reconstruction call the workers the module was set to (configured), the workers it used, the
workers expected (the arm's count, at most the faces to reconstruct; none below the module's minimum
faces or under two) and its fallback. `run` exits 0 only if every requested arm ran (gate passed,
child exit 0, every summary field present, the module's count fields integers), every arm is
IDENTICAL, every call of the arm is recorded (report() keeps the last 16) and had the module set to
the arm's count, every call used the workers expected without a fallback, and the layout's files and
the reference are byte-unchanged afterwards. Exit 1: an arm missing, stopped, failed or not IDENTICAL,
a field or call missing, the module set otherwise, or the layout or reference changed. Exit 3: every
arm IDENTICAL but a call used fewer workers than expected or fell back, so that arm's time is not its
count's (listed in workers_reduced).
"""
import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from time import perf_counter, sleep

import psutil

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
GIB = 1 << 30
RSS_GUARD = 12*GIB
FREE_FLOOR = 1*GIB
START_GATE = 10*GIB
GATE_WAIT_SECONDS = 600
SAME = ('result_id', 'metadata_sha256', 'metadata_bytes')
CALL_FIELDS = ('faces', 'to_reconstruct', 'configured', 'workers', 'collected', 'in_caller', 'fallback', 'ready_seconds',
               'seconds', 'worker_compute_seconds', 'parallel_efficiency', 'worker_working_set_peak_max',
               'worker_private_peak_max')


def _busy(times):
    values = times._asdict()
    return sum(values.values())-values['idle']


def _call_summary(call):
    rows = call['processes']
    seconds = call['seconds'] or 0.
    compute = sum(row['compute_seconds'] for row in rows)
    used = call['workers']
    return dict({name: call[name] for name in (
        'faces', 'to_reconstruct', 'configured', 'workers', 'collected', 'in_caller', 'fallback', 'restarted',
        'second_fallback', 'ready_seconds', 'seconds', 'slowest_face_seconds', 'shared_input_bytes', 'result_bytes')},
        worker_compute_seconds=round(compute, 3),
        parallel_efficiency=round(compute/(used*seconds), 3) if used and seconds else None,
        worker_ready_seconds_max=max((row['ready_seconds'] or 0. for row in rows), default=None),
        worker_busy_seconds_max=max((row['busy_seconds'] for row in rows), default=None),
        worker_faces=[row['faces'] for row in rows],
        worker_working_set_peak_max=max((row['working_set_peak_bytes'] for row in rows), default=0),
        worker_private_peak_max=max((row['private_peak_bytes'] for row in rows), default=0))


def _hooks():
    """Global hooks active now: profile/trace functions, tracemalloc, sys.monitoring tools."""
    tracing = sys.modules.get('tracemalloc')
    return dict(profile=sys.getprofile() is not None, trace=sys.gettrace() is not None,
                tracemalloc=bool(tracing is not None and tracing.is_tracing()),
                monitoring_tools=[tool for tool in range(6) if sys.monitoring.get_tool(tool) is not None])


def child(layout, out, workers, reference):
    layout, out = Path(layout).resolve(), Path(out)
    if out.exists():
        raise SystemExit('the output exists: %s' % out)
    info = json.loads((layout/'control.json').read_text(encoding='utf8'))
    paths = info['paths']
    sys.path[:0] = paths
    import private_heat_functionals_parallel_r1 as PAR
    where = Path(PAR.__file__ or '').resolve()
    if not any(where.parent == Path(path).resolve() for path in paths):
        raise SystemExit('functionals_parallel_r1 did not load from the layout: '+str(where))
    default = PAR.configure()
    PAR.configure(workers=workers)
    del sys.path[:len(paths)]           # the control's child puts them first itself, as in an ordinary run
    sys.path.append(str(C))
    import step7_same_call_heat_control as CONTROL
    me = psutil.Process()
    hooks_before = _hooks()
    cpu0, own0, t0 = psutil.cpu_times(), me.cpu_times(), perf_counter()
    CONTROL.child(str(layout), str(out))
    wall = perf_counter()-t0
    cpu1, own1 = psutil.cpu_times(), me.cpu_times()
    hooks_after = _hooks()
    report = PAR.report()
    calls = [_call_summary(call) for call in report['calls']]
    worker_compute = sum(call['worker_compute_seconds'] for call in calls)
    parent_cpu = (own1.user+own1.system)-(own0.user+own0.system)
    system_busy = _busy(cpu1)-_busy(cpu0)
    result = json.loads(out.read_text(encoding='utf8'))
    expected = json.loads(Path(reference).read_text(encoding='utf8'))
    differing = [f'{side}.{key}' for side in ('legacy', 'compact') for key in SAME
                 if result[side][key] is None or result[side][key] != expected[side][key]]
    if type(expected.get('arrays')) is not dict or not expected['arrays'] or result.get('arrays') != expected['arrays']:
        differing.append('arrays')
    result['h4'] = dict(
        workers_configured=workers, module_default_workers=default, module_file=str(where),
        module_sha256=sha256(where.read_bytes()).hexdigest(), minimum_faces=report['minimum_faces'],
        totals=report['totals'], calls=calls,
        fallbacks=report['fallbacks'], control_wall_seconds=round(wall, 3),
        parent_cpu_seconds=round(parent_cpu, 3), worker_compute_seconds=round(worker_compute, 3),
        system_busy_cpu_seconds=round(system_busy, 3),
        other_load_cpus=round((system_busy-parent_cpu-worker_compute)/wall, 2),
        logical_cpus=psutil.cpu_count(), physical_cores=psutil.cpu_count(logical=False),
        hooks_before=hooks_before, hooks_after=hooks_after,
        reference=str(reference), reference_sha256=sha256(Path(reference).read_bytes()).hexdigest(),
        differing_from_reference=differing,
        identical=result.get('status') == 'PASS' and not differing)
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf8')
    print(json.dumps(dict(workers=workers, status=result.get('status'), identical=result['h4']['identical'],
                          differing=differing, seconds=[call['seconds'] for call in calls],
                          used=[call['workers'] for call in calls])), flush=True)


def _tree(process):
    try:
        return [process, *process.children(recursive=True)]
    except psutil.Error:
        return [process]


def _end(members):
    for member in reversed(members):            # children first, then the arm's own process, by PID
        try:
            member.kill()
        except psutil.Error:
            pass


def _gate():
    """The start gate (unchanged rule): (passed, seconds waited, bytes available at the decision)."""
    waited = 0
    while True:
        available = psutil.virtual_memory().available
        if available >= START_GATE:
            return True, waited, available
        if waited >= GATE_WAIT_SECONDS:
            return False, waited, available
        sleep(15)
        waited += 15


def _tree_digest(root):
    """SHA-256 over every file below ROOT (relative path and content digest)."""
    root = Path(root)
    digest = sha256()
    for path in sorted(item for item in root.rglob('*') if item.is_file()):
        digest.update(('%s\0%s\0' % (path.relative_to(root).as_posix(), sha256(path.read_bytes()).hexdigest()))
                      .encode('utf8'))
    return digest.hexdigest()


def _read_arm(arm, out):
    """Copy a completed child's result into its arm record; None, or why the result is incomplete."""
    try:
        result = json.loads(out.read_text(encoding='utf8'))
        h4 = result['h4']
        if type(h4['minimum_faces']) is not int:
            raise TypeError('minimum_faces is %r' % (h4['minimum_faces'],))
        calls = []
        for call in h4['calls']:
            row = {name: call[name] for name in CALL_FIELDS}
            for name in ('faces', 'to_reconstruct', 'configured', 'workers'):     # the module's own int fields
                if type(row[name]) is not int:
                    raise TypeError('call field %s is %r' % (name, row[name]))
            usable = min(arm['workers'], row['to_reconstruct']) if row['to_reconstruct'] >= h4['minimum_faces'] else 0
            row['expected_workers'] = usable if usable >= 2 else 0
            row['as_configured'] = (row['configured'] == arm['workers'] and row['workers'] == row['expected_workers']
                                    and (row['expected_workers'] == 0 or row['fallback'] is None))
            calls.append(row)
        arm.update(status=result['status'], identical=h4['identical'], differing=h4['differing_from_reference'],
                   legacy_advance_seconds=round(result['legacy']['seconds'], 3),
                   compact_advance_seconds=round(result['compact']['seconds'], 3),
                   control_elapsed_seconds=round(result['elapsed_seconds'], 3),
                   parent_peak_working_set=result['peak_working_set_bytes'], calls=calls,
                   total_calls=h4['totals']['calls'], total_fallbacks=h4['totals']['fallbacks'],
                   fallbacks=h4['fallbacks'], other_load_cpus=h4['other_load_cpus'], module_sha256=h4['module_sha256'],
                   hooks=dict(before=h4['hooks_before'], after=h4['hooks_after']))
    except (OSError, ValueError, KeyError, TypeError) as error:
        return 'the arm result is incomplete: %s: %s' % (type(error).__name__, error)
    return None


def _verdict(summary):
    """(exit status, failures, reduced) of a sweep: 0 PASS, 1 FAIL, 3 every arm IDENTICAL but workers reduced."""
    failures, reduced = [], []
    counts, arms = summary['counts'], summary['arms']
    if not counts:
        failures.append('no worker counts')
    if len(arms) != len(counts):
        failures.append('%d of %d arms ran' % (len(arms), len(counts)))
    for arm, count in zip(arms, counts, strict=False):     # fewer arms than counts is reported above
        name = 'arm %s (%s workers)' % (arm.get('arm'), count)
        if arm.get('workers') != count:
            failures.append('%s: recorded as %s workers' % (name, arm.get('workers')))
        if 'stopped' in arm:
            failures.append('%s: %s' % (name, arm['stopped']))
            continue
        if arm.get('status') != 'PASS' or arm.get('identical') is not True or arm.get('differing') != []:
            failures.append('%s: not IDENTICAL (status %s, differing %s)' % (name, arm.get('status'), arm.get('differing')))
        calls = arm.get('calls') or []
        if not calls:
            failures.append('%s: no reconstruction call recorded' % name)
        if arm.get('total_calls') != len(calls):       # report() keeps the last KEPT_CALLS calls only
            failures.append('%s: %d calls recorded of %s made' % (name, len(calls), arm.get('total_calls')))
        for k, call in enumerate(calls):
            if call['configured'] != count:
                failures.append('%s call %d: the module was set to %s workers' % (name, k, call['configured']))
            elif not call['as_configured']:
                reduced.append('%s call %d: %s workers used, %s expected, fallback %s' % (
                    name, k, call['workers'], call['expected_workers'], call['fallback']))
    if summary.get('layout_sha256_before') is None or summary.get('layout_sha256_before') != summary.get(
            'layout_sha256_after'):
        failures.append('the layout changed during the run (or was not digested)')
    if summary.get('reference_sha256') is None or summary.get('reference_sha256') != summary.get(
            'reference_sha256_after'):
        failures.append('the reference changed during the run (or was not digested)')
    return (1 if failures else 3 if reduced else 0), failures, reduced


def run(layout, outdir, reference, counts):
    if not counts:
        raise SystemExit('give at least one worker count')
    if not (Path(layout)/'control.json').is_file():
        raise SystemExit('no layout: %s' % layout)
    reference_sha256 = sha256(Path(reference).read_bytes()).hexdigest()
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONHASHSEED='0', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    before = _tree_digest(layout)
    arms = []
    for k, count in enumerate(counts):
        arm: dict = {'arm': k, 'workers': count}
        arms.append(arm)
        passed, waited, available = _gate()
        arm['start_gate'] = dict(passed=passed, required_available_bytes=START_GATE, available_bytes=available,
                                 waited_seconds=waited)
        if not passed:
            arm['stopped'] = 'start gate: under 10 GiB available for 10 minutes'
            break
        out, log = outdir/f'arm-{k}.json', outdir/f'arm-{k}.log'
        command = [sys.executable, '-B', str(Path(__file__).resolve()), 'child', str(layout), str(out), str(count),
                   str(reference)]
        began = perf_counter()
        with open(log, 'xb') as handle:
            process = subprocess.Popen(command, cwd=C, env=env, stdout=handle, stderr=subprocess.STDOUT)
            watched = psutil.Process(process.pid)
            peak_ws = peak_private = 0
            low = psutil.virtual_memory().available
            while process.poll() is None:
                members = _tree(watched)
                ws = private = 0
                for member in members:
                    try:
                        info = member.memory_info()
                    except psutil.Error:
                        continue
                    ws, private = ws+info.rss, private+info.private
                available = psutil.virtual_memory().available
                peak_ws, peak_private, low = max(peak_ws, ws), max(peak_private, private), min(low, available)
                if ws > RSS_GUARD or available < FREE_FLOOR:
                    arm['stopped'] = f'guard: tree working set {ws} B, available {available} B'
                    _end(members)
                    break
                sleep(.5)
            process.wait()
        arm.update(exit_code=process.returncode, arm_wall_seconds=round(perf_counter()-began, 3),
                   tree_working_set_peak_sampled=peak_ws, tree_private_peak_sampled=peak_private,
                   available_low=low)
        problem = (_read_arm(arm, out) if out.is_file() and process.returncode == 0
                   else 'the arm did not complete; see its log')
        if problem is not None:
            arm.setdefault('stopped', problem)
            break
    summary = dict(layout=str(layout), reference=str(reference), reference_sha256=reference_sha256,
                   counts=list(counts), guards=dict(start_gate_bytes=START_GATE, gate_wait_seconds=GATE_WAIT_SECONDS,
                                                    tree_working_set_bytes=RSS_GUARD, free_floor_bytes=FREE_FLOOR),
                   layout_sha256_before=before, layout_sha256_after=_tree_digest(layout),
                   reference_sha256_after=sha256(Path(reference).read_bytes()).hexdigest(), arms=arms)
    status, failures, reduced = _verdict(summary)
    summary.update(verdict={0: 'PASS', 3: 'WORKERS_REDUCED'}.get(status, 'FAIL'), exit_status=status,
                   failures=failures, workers_reduced=reduced)
    with open(outdir/'summary.json', 'x', encoding='utf8') as handle:
        handle.write(json.dumps(summary, indent=1))
    print('arm workers identical recon_s(per call) advance_s(legacy,compact) used(expected) other_cpus tree_peak_MiB')
    for arm in arms:
        if 'stopped' in arm or 'calls' not in arm:
            print(arm['arm'], arm['workers'], 'STOPPED', arm.get('stopped'))
            continue
        print(arm['arm'], arm['workers'], arm['identical'], [call['seconds'] for call in arm['calls']],
              [arm['legacy_advance_seconds'], arm['compact_advance_seconds']],
              ['%s(%s)' % (call['workers'], call['expected_workers']) for call in arm['calls']],
              arm['other_load_cpus'], arm['tree_working_set_peak_sampled'] >> 20)
    print('verdict', summary['verdict'], 'exit', status)
    for line in failures+reduced:
        print('  '+line)
    return status


def main():
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    if sys.argv[1] == 'child':
        child(sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5])
    elif sys.argv[1] == 'run':
        raise SystemExit(run(Path(sys.argv[2]).resolve(), sys.argv[3], Path(sys.argv[4]).resolve(),
                             [int(n) for n in sys.argv[5:]]))
    else:
        raise SystemExit('run or child')


if __name__ == '__main__':
    main()
