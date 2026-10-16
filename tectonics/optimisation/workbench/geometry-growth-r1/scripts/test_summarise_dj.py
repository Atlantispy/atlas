"""Mutant proof of summarise_dj.py (VOID-ENVIRONMENT verdict) and run_dj_rearm.sh (generations, merge).

Usage: python -B -I test_summarise_dj.py WORK      (WORK must not exist; small lane, no runtime loaded)
Summary cases: synthetic D-j outputs shaped like the real ones (16 Oct files: session gates at
decision.interface_batches.gates and decision.wall_parallel.rolling.gates, each with the gate's own
reading; session reason/detail/last_error beside them; a session refused at a gate records no later
gate; peaks at concurrency.controllers.*.peak_live; workers_policy and package_digest at the top).
A clean set must PASS (0). An arm asking for more than two workers whose sessions a cpu or memory gate
held to <= 2, with that gate's reading showing the machine could not fit 3 though a quiet one could,
and which then ran normally (or was refused by that gate alone), failing only its peak check, must be
VOID (3). Every other defect, alone or beside a void arm, must FAIL (1): refuter 16 Oct P1 cases are a
cap with an idle reading, free_cores 4.0, a machine too small for 3, over-RAM per-worker sizes, a
policy of 2, a stopped or erroring session, a refusal with a later gate or another gate's detail, and
a package other than the serial pass's. Round 3: a memory booking other than the r6 policy's (P2); a
gate-less session that stopped for anything but 'eligible work below threshold', erred or is missing
(P3); an IV1 peak from a non-batch controller; superseded attempts (P1) that failed, have an unknown
name or are not arm attempts.
Harness cases: run_dj_rearm.sh refuses bad starts (exit 2) before running anything, including leading
zeros, repeated specs and any existing output, store or log (P3c, P3d); its own newest() and merge
sections, cut from the script, run on fake folders: the newest generation up to <gen> stands in, this
generation's arm is required, and the r4 serial replaces r2view's serial only if it ran r2's package
(P3e). Round 3 (P1): every attempt up to <gen> that the newest replaced is copied to superseded/ and
judged, so a rerun over a failed attempt FAILs. Round 3 re-review (P1): each case runs on a fresh fake
tree mirroring the real evidence's names and must refuse for its own reason; an attempt log or store
with no JSON (crashed or killed), a generation at or above <gen> (or above it at the merge), a rerun
named other than -r<k>, k >= 2, or of an arm with no first attempt refuses the start and FAILs the
merge before anything is merged.
Writes WORK/proof.json; exit 0 only if every case is as expected.
"""
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
SUMMARY = HERE/'summarise_dj.py'
HARNESS = HERE/'run_dj_rearm.sh'
BASH = 'C:/Program Files/Git/usr/bin/bash.exe'
WORK = Path(sys.argv[1])
GIB = 1 << 30
PW, RES = 805306368, 2 << 30   # the r6 policy's memory booking, which round 3 (P2) pins
RAM = psutil.virtual_memory().total   # the summary reads the same figure
results = {}
DROP = object()


def reading(name, w, trimmed):
    """The gate's own record, as the runtime writes it (cpu fits n when free_cores >= n+1; memory when
    available >= n*per_worker+reserve): a gate that trimmed to w fits w but not w+1; any other is idle."""
    if name == 'cpu':
        free = w + 1.01 if trimmed else 7.5
        return dict(physical_cores=8, logical_cpus=16, busy_cpus=round(8-free, 2), free_cores=free,
                    idle_cores=free, workers=w)
    if name == 'memory':
        return dict(available_bytes=w*PW + RES + PW//2 if trimmed else 21*GIB, per_worker_bytes=PW,
                    reserve_bytes=RES, workers=w)
    return dict(workers=w)


def gates(*trims, incoming=6):
    """Session gates in the runtime's order; trims maps a gate name to its workers after it. A gate
    that leaves 0 workers refuses the session and the runtime records no later gate."""
    names, out, w = ('cpu', 'memory', 'budget', 'predicate units'), [], incoming
    trims = dict(trims)
    for name in names:
        w = trims.get(name, w)
        out.append(dict(gate=name, value=reading(name, w, name in trims), passed=w > 0))
        if w == 0:
            break
    return out


def session(family, *trims, incoming=6):
    g = gates(*trims, incoming=incoming)
    s: dict = dict(family=family, workers=g[-1]['value']['workers'], notes=[], last_error=None, gates=g)
    if g[-1]['passed']:
        s.update(route='parallel', reason='selected', detail='no request in the lookahead has an estimate')
    else:
        s.update(route='serial', reason='session not opened', detail='%s: refused' % g[-1]['gate'])
    return s


def arm(name, which):
    d: dict = dict(records_sha256='R'*64, streams_sha256='S'*64, error=None, wall_s=1.0, package_digest='P'*64,
                   workers_policy=1, parent_peak_working_set_mib=1, decision=dict(reason='mode', gates=[]),
                   concurrency=dict(controllers={}, peak_children_rss_mib=0))
    if which == 'serial':
        return d
    n = int(which[1:])
    d['workers_policy'] = n
    dec, ctrl = d['decision'], d['concurrency']['controllers']
    if name == 'iv2' and n == 2:
        dec.update(reason='selected', gates=[dict(gate='interface-route', value={}, passed=True)])
        return d
    dec['gates'] = [dict(gate='interface-route', value={}, passed=False)]
    dec['reason'] = 'interface batches selected'
    work = n - 1
    dec['interface_batches'] = session('interface', ('cpu', work), incoming=n)
    ctrl['interface_batches'] = dict(peak_live=work)
    if name == 'iv1':
        dec['wall_parallel'] = dict(rolling=session('wall', ('cpu', work), incoming=n))
        ctrl['wall_batches'] = dict(peak_live=work)
    return d


def clean():
    files = {}
    for name, arms in (('iv2', ('serial', 'w2', 'w4', 'w6')), ('iv1', ('serial', 'w4', 'w6'))):
        for a in arms:
            files['out', '%s-%s' % (name, a)] = arm(name, a)
        files['r2', '%s-serial' % name] = arm(name, 'serial')
    return files


def write(root, files):
    for (where, stem), d in files.items():
        folder = root/where
        folder.mkdir(parents=True, exist_ok=True)
        (folder/(stem + '.json')).write_text(d if isinstance(d, str) else json.dumps(d), encoding='utf8')


def record(name, code, want, tail):
    ok = code == want
    results[name] = dict(exit=code, want=want, ok=ok, tail=tail)
    print('%-66s exit %s want %s  %s  %s' % (name, code, want, 'as expected' if ok else 'WRONG', tail[-140:]))


def case(name, want, mutate=None):
    files = clean()
    if mutate:
        mutate(files)
    root = WORK/('s%02d' % (len(results)+1))
    write(root, files)
    run = subprocess.run([sys.executable, '-B', '-I', str(SUMMARY), str(root/'out'), str(root/'r2')],
                         capture_output=True, text=True)
    record('summary: ' + name, run.returncode, want, (run.stdout+run.stderr).strip().replace('\n', ' | '))


def held(stem, *trims, peak=None, wall=None):
    """Arm whose sessions the given gates trimmed; peak follows the narrowest trim unless given."""
    def m(files):
        d = files['out', stem]
        n = int(stem.split('-w')[1])
        w = min([t[1] for t in trims] + [n])
        d['decision']['interface_batches'] = session('interface', *trims, incoming=n)
        d['concurrency']['controllers']['interface_batches']['peak_live'] = w if peak is None else peak
        if 'wall_parallel' in d['decision']:
            d['decision']['wall_parallel']['rolling'] = session('wall', *(wall or trims), incoming=n)
            d['concurrency']['controllers']['wall_batches']['peak_live'] = (
                min([t[1] for t in (wall or trims)] + [n]) if peak is None else peak)
    return m


def both(*ms):
    def m(files):
        for f in ms:
            f(files)
    return m


def setv(stem, path, value, where='out'):
    def m(files):
        d = files[where, stem]
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = value
    return m


def sess(files, stem, which):
    dec = files['out', stem]['decision']
    return dec['wall_parallel']['rolling'] if which == 'wall' else dec['interface_batches']


def set_reading(stem, gate, which='interface', **kv):
    """Change (or DROP) fields of one gate's recorded reading."""
    def m(files):
        for g in sess(files, stem, which)['gates']:
            if g['gate'] == gate:
                for k, v in kv.items():
                    g['value'].pop(k, None) if v is DROP else g['value'].__setitem__(k, v)
    return m


def set_session(stem, which='interface', **kv):
    def m(files):
        sess(files, stem, which).update(kv)
    return m


# --- summary verdicts ---------------------------------------------------------------------------
WORK.mkdir(parents=True, exist_ok=False)
case('clean set', 0)
case('iv2 w6 cpu gate held to 2, peak 2 (VOID)', 3, held('iv2-w6', ('cpu', 2)))
case('iv2 w6 cpu gate refused (0), session not opened (VOID)', 3,
     both(held('iv2-w6', ('cpu', 0)), lambda f: f['out', 'iv2-w6']['concurrency']['controllers'].clear()))
case('iv2 w6 memory gate held to 2 (VOID)', 3, held('iv2-w6', ('memory', 2)))
case('iv2 w6 memory gate refused (0) (VOID)', 3,
     both(held('iv2-w6', ('memory', 0)), lambda f: f['out', 'iv2-w6']['concurrency']['controllers'].clear()))
case('iv1 w6 both sessions cpu-held (VOID)', 3, held('iv1-w6', ('cpu', 2)))
case('iv2 w4 and iv1 w6 both void (VOID)', 3, both(held('iv2-w4', ('cpu', 1)), held('iv1-w6', ('memory', 2))))
case('iv2 w6 budget gate trimmed to 2 (FAIL: design)', 1, held('iv2-w6', ('budget', 2)))
case('iv2 w6 predicate units trimmed to 2 (FAIL)', 1, held('iv2-w6', ('predicate units', 2)))
case('iv2 w6 cpu 3 then budget 2: first <=2 is budget (FAIL)', 1, held('iv2-w6', ('cpu', 3), ('budget', 2)))
case('iv2 w6 gates allow 5 but peak 2 (FAIL: not machine)', 1, held('iv2-w6', ('cpu', 5), peak=2))
case('iv2 w6 peak 2, no session gates (FAIL)', 1,
     both(held('iv2-w6', ('cpu', 2)), setv('iv2-w6', ('decision', 'interface_batches', 'gates'), [])))
case('iv2 w6 peak 2, gate workers is a string (FAIL)', 1,
     both(held('iv2-w6', ('cpu', 2)),
          setv('iv2-w6', ('decision', 'interface_batches', 'gates', 0, 'value', 'workers'), '2'),
          setv('iv2-w6', ('decision', 'interface_batches', 'gates', 1, 'value', 'workers'), '2'),
          setv('iv2-w6', ('decision', 'interface_batches', 'gates', 2, 'value', 'workers'), 2)))
case('iv2 w6 peak 2, gate workers True (FAIL)', 1,
     both(held('iv2-w6', ('cpu', 2)),
          lambda f: [g['value'].update(workers=True) if g['gate'] == 'cpu' else g['value'].update(workers=6)
                     for g in f['out', 'iv2-w6']['decision']['interface_batches']['gates']]))
case('iv1 w6 interface cpu-held, wall allows 5 but peak 2 (FAIL)', 1,
     held('iv1-w6', ('cpu', 2), wall=[('cpu', 5)], peak=2))
case('iv2 w6 cpu-held but records differ (FAIL, not VOID)', 1,
     both(held('iv2-w6', ('cpu', 2)), setv('iv2-w6', ('records_sha256',), 'X'*64)))
case('iv2 w6 cpu-held but streams differ (FAIL)', 1,
     both(held('iv2-w6', ('cpu', 2)), setv('iv2-w6', ('streams_sha256',), 'X'*64)))
case('iv2 w6 cpu-held but error set (FAIL)', 1, both(held('iv2-w6', ('cpu', 2)), setv('iv2-w6', ('error',), 'boom')))
case('iv2 w6 cpu-held but interface-route gate passed (FAIL)', 1,
     both(held('iv2-w6', ('cpu', 2)), setv('iv2-w6', ('decision', 'gates'), [dict(gate='interface-route', passed=True)])))
case('iv2 w6 cpu-held but profile unbound (FAIL)', 1,
     both(held('iv2-w6', ('cpu', 2)), setv('iv2-w6', ('decision', 'reason'), 'no compatible observations')))
case('void arm beside a failed w2 gate (FAIL)', 1,
     both(held('iv2-w6', ('cpu', 2)), setv('iv2-w2', ('decision', 'reason'), 'mode')))
case('iv2 w2 reason not selected (FAIL)', 1, setv('iv2-w2', ('decision', 'reason'), 'interface batches selected'))
case('iv1 w4 peak 2, gates allow 3 (FAIL)', 1, held('iv1-w4', ('cpu', 3), peak=2))
case('iv2 w6 arm missing (FAIL)', 1, lambda f: f.pop(('out', 'iv2-w6')))
case('iv1 serial missing (FAIL, no crash)', 1, lambda f: f.pop(('out', 'iv1-serial')))
case('r2 serial missing (FAIL)', 1, lambda f: f.pop(('r2', 'iv2-serial')))
case('r2 serial differs (FAIL)', 1, setv('iv1-serial', ('streams_sha256',), 'Y'*64, where='r2'))
case('this serial differs from every arm (FAIL)', 1, setv('iv2-serial', ('records_sha256',), 'Z'*64))
# refuter 16 Oct P1: the gate's own reading, not its name, says the machine held the arm
CPU2 = held('iv2-w6', ('cpu', 2))
MEM2 = held('iv2-w6', ('memory', 2))
case('cpu workers 2 with an idle reading (FAIL: a cap, not the machine)', 1,
     both(CPU2, set_reading('iv2-w6', 'cpu', free_cores=7.5)))
case('cpu reading free_cores 3.99 (VOID: boundary)', 3, both(CPU2, set_reading('iv2-w6', 'cpu', free_cores=3.99)))
case('cpu reading free_cores 4.0 (FAIL: fits 3)', 1, both(CPU2, set_reading('iv2-w6', 'cpu', free_cores=4.0)))
case('cpu reading on a 3-core machine (FAIL: never fits 3)', 1,
     both(CPU2, set_reading('iv2-w6', 'cpu', physical_cores=3)))
case('cpu reading without free_cores (FAIL)', 1, both(CPU2, set_reading('iv2-w6', 'cpu', free_cores=DROP)))
case('cpu reading free_cores a string (FAIL)', 1, both(CPU2, set_reading('iv2-w6', 'cpu', free_cores='3.01')))
case('cpu reading free_cores True (FAIL)', 1, both(CPU2, set_reading('iv2-w6', 'cpu', free_cores=True)))
case('cpu reading not a dict beside workers (FAIL)', 1,
     both(CPU2, lambda f: sess(f, 'iv2-w6', 'interface')['gates'][0].update(value=2)))
case('memory workers 2 with an idle reading (FAIL)', 1,
     both(MEM2, set_reading('iv2-w6', 'memory', available_bytes=21*GIB)))
case('memory per-worker over-booked, 3 fit in RAM (FAIL: not the policy, round 3 P2)', 1,
     both(MEM2, set_reading('iv2-w6', 'memory', per_worker_bytes=RAM//8, available_bytes=int(2.5*(RAM//8)) + RES)))
case('memory 3 per-worker sizes exceed physical RAM (FAIL)', 1,
     both(MEM2, set_reading('iv2-w6', 'memory', per_worker_bytes=RAM//2, available_bytes=int(2.5*(RAM//2)) + RES)))
case('memory reserve 1 GiB, not the policy (FAIL, round 3 P2)', 1,
     both(MEM2, set_reading('iv2-w6', 'memory', reserve_bytes=GIB)))
case('memory per-worker under-booked 512 MiB (FAIL, round 3 P2)', 1,
     both(MEM2, set_reading('iv2-w6', 'memory', per_worker_bytes=512 << 20, available_bytes=(1280 << 20) + RES)))
case('memory per-worker 768 MiB as a float (FAIL)', 1,
     both(MEM2, set_reading('iv2-w6', 'memory', per_worker_bytes=float(PW))))
case('memory reading without reserve (FAIL)', 1, both(MEM2, set_reading('iv2-w6', 'memory', reserve_bytes=DROP)))
case('iv1 w6 wall memory-held with an idle reading (FAIL)', 1,
     both(held('iv1-w6', ('memory', 2)), set_reading('iv1-w6', 'memory', 'wall', available_bytes=21*GIB)))
case('cpu-held arm that asked for 2 workers (FAIL)', 1, both(CPU2, setv('iv2-w6', ('workers_policy',), 2)))
case('cpu-held arm without workers_policy (FAIL)', 1, both(CPU2, lambda f: f['out', 'iv2-w6'].pop('workers_policy')))
case('cpu-held arm with workers_policy "6" (FAIL)', 1, both(CPU2, setv('iv2-w6', ('workers_policy',), '6')))
case('cpu-held session stopped: reason binding changed (FAIL)', 1,
     both(CPU2, set_session('iv2-w6', reason='binding changed')))
case('cpu-held session with last_error (FAIL)', 1, both(CPU2, set_session('iv2-w6', last_error='worker died')))
case('iv1 w6 wall session cpu-held but not selected (FAIL)', 1,
     both(held('iv1-w6', ('cpu', 2)), set_session('iv1-w6', 'wall', reason='funding refused')))
REF0 = both(held('iv2-w6', ('cpu', 0)), lambda f: f['out', 'iv2-w6']['concurrency']['controllers'].clear())
case('cpu refusal (0) with a later gate recorded (FAIL)', 1,
     both(REF0, lambda f: sess(f, 'iv2-w6', 'interface')['gates'].append(
         dict(gate='memory', value=reading('memory', 0, True), passed=False))))
case('cpu refusal (0) whose detail names budget (FAIL)', 1,
     both(REF0, set_session('iv2-w6', detail='budget: funding refused')))
case('cpu refusal (0) with reason selected (FAIL)', 1, both(REF0, set_session('iv2-w6', reason='selected')))
case('cpu refusal (0) with the gate marked passed (FAIL)', 1,
     both(REF0, lambda f: sess(f, 'iv2-w6', 'interface')['gates'][0].update(passed=True)))
case('cpu refusal (0) with an idle reading (FAIL)', 1, both(REF0, set_reading('iv2-w6', 'cpu', free_cores=7.5)))
case('iv2 w4 ran another package (FAIL)', 1, setv('iv2-w4', ('package_digest',), 'Q'*64))
case('cpu-held arm ran another package (FAIL, not VOID)', 1, both(CPU2, setv('iv2-w6', ('package_digest',), 'Q'*64)))
case('no package digests anywhere (FAIL)', 1,
     lambda f: [d.pop('package_digest') for (where, stem), d in f.items() if where == 'out'])


# refuter round 3, P3: a gate-less session voids nothing unless it stopped by design
def ungated(stem, which, reason='eligible work below threshold', **kv):
    """The session stopped before any gate was read, as the runtime records it; its controller is gone."""
    def m(files):
        s = sess(files, stem, which)
        s.clear()
        s.update(dict(family=which, workers=0, notes=[], last_error=None, gates=[], route='serial', reason=reason,
                      detail='expected 15.564 s of eligible work in this pass'), **kv)
        files['out', stem]['concurrency']['controllers'].pop('wall_batches' if which == 'wall' else 'interface_batches', None)
    return m


IV1H = held('iv1-w6', ('cpu', 2))
case('iv1 w6 interface cpu-held, wall gate-less below threshold (VOID)', 3, both(IV1H, ungated('iv1-w6', 'wall')))
case('iv1 w6 wall cpu-held, interface gate-less below threshold (VOID)', 3, both(IV1H, ungated('iv1-w6', 'interface')))
case('iv1 w6 cpu-held, gate-less wall: timing binding changed (FAIL, P3)', 1,
     both(IV1H, ungated('iv1-w6', 'wall', reason='timing binding changed')))
case('iv1 w6 cpu-held, gate-less wall: selection error (FAIL, P3)', 1,
     both(IV1H, ungated('iv1-w6', 'wall', reason='selection error')))
case('iv1 w6 cpu-held, gate-less wall: enclosure gate (FAIL)', 1, both(IV1H, ungated('iv1-w6', 'wall', reason='enclosure gate')))
case('iv1 w6 cpu-held, gate-less wall below threshold with last_error (FAIL)', 1,
     both(IV1H, ungated('iv1-w6', 'wall', last_error='schedule failed')))
case('iv1 w6 cpu-held, wall session missing (FAIL)', 1, both(IV1H, setv('iv1-w6', ('decision', 'wall_parallel', 'rolling'), None)))
case('iv1 w6 cpu-held, wall_parallel missing (FAIL)', 1, both(IV1H, lambda f: f['out', 'iv1-w6']['decision'].pop('wall_parallel')))
case('iv1 w6 both sessions gate-less below threshold (FAIL: nothing held)', 1,
     both(ungated('iv1-w6', 'wall'), ungated('iv1-w6', 'interface')))
case('iv2 w6 interface gate-less below threshold (FAIL: nothing held)', 1, ungated('iv2-w6', 'interface'))
# round 3: IV1's peak is the batch controllers' only
case('iv1 w4 batch peaks 2, another controller 3 (FAIL, round 3)', 1,
     both(held('iv1-w4', ('cpu', 3), peak=2),
          lambda f: f['out', 'iv1-w4']['concurrency']['controllers'].__setitem__('endpoints', dict(peak_live=3))))
case('iv1 w4 interface peak 2, wall peak 3 (PASS)', 0,
     both(held('iv1-w4', ('cpu', 3)), setv('iv1-w4', ('concurrency', 'controllers', 'interface_batches', 'peak_live'), 2)))


# refuter round 3, P1: every superseded attempt is judged and must be PASS or VOID
def superseded(stem, d):
    return lambda f: f.__setitem__(('out/superseded', stem), d)


def arm_of(stem, *mutations):
    files = clean()
    for f in mutations:
        f(files)
    return files['out', stem]


case('superseded attempt that passed (PASS)', 0, superseded('iv2-w6', arm('iv2', 'w6')))
case('superseded attempt the machine held (PASS: a VOID attempt)', 0, superseded('iv2-w6-r2', arm_of('iv2-w6', CPU2)))
case('superseded attempts, one PASS one VOID, current VOID (VOID)', 3,
     both(CPU2, superseded('iv2-w6', arm('iv2', 'w6')), superseded('iv2-w6-r2', arm_of('iv2-w6', CPU2))))
case('superseded attempt with other records (FAIL, P1)', 1, superseded('iv2-w6', dict(arm('iv2', 'w6'), records_sha256='X'*64)))
case('superseded r2 attempt: gates allow 5, peak 2 (FAIL, P1)', 1,
     superseded('iv2-w6-r2', arm_of('iv2-w6', held('iv2-w6', ('cpu', 5), peak=2))))
case('superseded iv1 attempt of another package (FAIL)', 1,
     superseded('iv1-w4-r3', dict(arm('iv1', 'w4'), package_digest='Q'*64)))
case('superseded file with an unknown name (FAIL)', 1, superseded('iv2-w6-x', arm('iv2', 'w6')))
case('superseded serial pass (FAIL: not an arm attempt)', 1, superseded('iv2-serial', arm('iv2', 'serial')))
case('superseded iv1 w2 (FAIL: not a D-j arm)', 1, superseded('iv1-w2', arm('iv1', 'w2')))
case('superseded -r02 (FAIL: leading zero)', 1, superseded('iv2-w6-r02', arm('iv2', 'w6')))
case('superseded attempt of a set whose serial is missing (FAIL)', 1,
     both(lambda f: f.pop(('out', 'iv1-serial')), superseded('iv1-w6', arm('iv1', 'w6'))))


# --- harness ------------------------------------------------------------------------------------
REAL_OUT = HERE.parent/'evidence'/'workers-dj'


def fake_harness(root, present=(), absent=()):
    """The harness with only its G= and PY= lines changed, on a fresh fake evidence tree that mirrors
    the real one's names (folders empty, files '{}'), so the controls also show that the real tree
    passes the attempt audit; `present` adds fake OUT entries (a trailing / makes a folder) and `absent`
    drops mirrored ones. A stub interpreter means a broken refusal cannot start a real run or write
    real evidence."""
    out = root/'evidence'/'workers-dj'
    (root/'scripts').mkdir(parents=True)
    out.mkdir(parents=True)
    for p in sorted(REAL_OUT.iterdir()):
        if p.name in absent:
            continue
        (out/p.name).mkdir() if p.is_dir() else (out/p.name).write_text('{}', encoding='utf8')
    for p in present:
        path = out/p.rstrip('/')
        path.mkdir() if p.endswith('/') else path.write_text('{}', encoding='utf8')
    stub = root/'stub.sh'
    stub.write_bytes(b'#!/usr/bin/env bash\necho STUB-RUN "$@"\nexit 0\n')
    text = HARNESS.read_text(encoding='utf8')
    text, n1 = re.subn(r'^G=.*$', 'G="%s"' % root.as_posix(), text, count=1, flags=re.M)
    text, n2 = re.subn(r'^PY=.*$', 'PY="%s"' % stub.as_posix(), text, count=1, flags=re.M)
    assert n1 == n2 == 1, (n1, n2)
    path = root/'harness-copy.sh'
    path.write_bytes(text.encode('utf8'))
    return path


def harness_run(args, present=(), absent=()):
    path = fake_harness(WORK/('h%03d' % (len(results)+1)), present, absent)
    run = subprocess.run([BASH, str(path), *args], capture_output=True, text=True, timeout=120)
    return run.returncode, (run.stdout+run.stderr).strip()


def refuses(name, args, why, present=(), absent=()):
    """The harness must exit 2 before starting, for the reason `why` (a fragment of its message)."""
    code, out = harness_run(args, present, absent)
    fine = code == 2 and why in out and 'start' not in out and 'STUB-RUN' not in out
    record('harness refuses: ' + name, 0 if fine else 1, 0, 'exit %d: %s' % (code, out.replace('\n', ' | ')[-140:]))


def proceeds(name, args, present=()):
    code, out = harness_run(args, present)
    record('harness control: ' + name,
           0 if code != 2 and 'start %s' % ' '.join(args) in out and 'STUB-RUN' in out else 1, 0,
           'exit %d: %s' % (code, out.replace('\n', ' | ')[-140:]))


proceeds('a valid start proceeds on the real tree (stub runtime)', ['r3', 'iv2:6'])
proceeds('two worker counts of one set proceed', ['r8', 'iv2:6', 'iv2:4'])
proceeds('earlier generations with their JSON proceed', ['r5', 'iv2:6'],
         present=['iv2-w6-r3.json', 'iv2-w6-r3.log', 'iv2-store-w6-r3/', 'iv1-w4-r4.json', 'iv1-store-w4-r4/',
                  '../workers-dj-merged-r3/', '../workers-dj-merged-r4/'])
refuses('no arguments', [], 'usage')
refuses('generation only', ['r3'], 'usage')
refuses('generation r1', ['r1', 'iv2:6'], 'bad generation')
refuses('generation without r', ['3', 'iv2:6'], 'bad generation')
refuses('generation r', ['r', 'iv2:6'], 'bad generation')
refuses('generation r3x', ['r3x', 'iv2:6'], 'bad generation')
refuses('generation r02 (leading zero)', ['r02', 'iv2:6'], 'bad generation')
refuses('generation r010 (leading zero)', ['r010', 'iv2:6'], 'bad generation')
refuses('unknown set', ['r3', 'iv3:6'], 'unknown set')
refuses('bad workers', ['r3', 'iv2:x'], 'bad workers')
refuses('workers 06 (leading zero)', ['r3', 'iv2:06'], 'bad workers')
refuses('workers 0', ['r3', 'iv2:0'], 'bad workers')
refuses('repeated spec', ['r3', 'iv2:6', 'iv2:6'], 'repeated')
refuses('repeated spec after another', ['r3', 'iv2:6', 'iv1:6', 'iv2:6'], 'repeated')
refuses('repeated r4serial', ['r3', 'iv2:r4serial', 'iv2:r4serial'], 'repeated')
refuses('existing r2 rerun store of iv2 w6', ['r2', 'iv2:6'], 'exists:')
refuses('existing r2 rerun after a good spec', ['r2', 'iv1:6', 'iv2:6'], 'exists:')
refuses('existing rerun output json', ['r5', 'iv2:4'], 'exists:', present=['iv2-w4-r5.json'])
refuses('existing rerun log', ['r5', 'iv2:4'], 'exists:', present=['iv2-w4-r5.log'])
refuses('existing r4 serial json', ['r3', 'iv1:r4serial'], 'exists:')
refuses('existing r4 serial store', ['r3', 'iv2:r4serial'], 'exists:', present=['iv2-store-r4enc/'])
refuses('existing r4 serial log', ['r3', 'iv2:r4serial'], 'exists:', present=['iv2-serial-r4enc.log'])
refuses('existing merged folder', ['r6', 'iv2:6'], 'exists:', present=['../workers-dj-merged-r6/'])
# Round 3 re-review (P1): attempts a rerun could hide.
refuses('crashed r3 (log and store, no JSON) before r4', ['r4', 'iv2:6'], 'no JSON (crashed or killed): iv2-w6-r3.log',
        present=['iv2-w6-r3.log', 'iv2-store-w6-r3/'])
refuses('crashed r3 store only, other arm', ['r4', 'iv2:6'], 'no JSON (crashed or killed): iv2-store-w4-r3',
        present=['iv2-store-w4-r3/'])
refuses('crashed first attempt (log, no JSON)', ['r3', 'iv2:6'], 'no JSON (crashed or killed): iv2-w6.log',
        absent=['iv2-w6.json'])
refuses('crashed r4 serial (log, no JSON)', ['r3', 'iv2:6'], 'r4 serial with no JSON', absent=['iv1-serial-r4enc.json'])
refuses('later r10 output exists (out of order)', ['r4', 'iv2:6'], 'generation above the one allowed (r3): iv2-w6-r10.json',
        present=['iv2-w6-r10.json'])
refuses('same generation on another arm exists', ['r4', 'iv2:6'], 'generation above the one allowed (r3): iv1-w6-r4.json',
        present=['iv1-w6-r4.json'])
refuses('later store only (out of order)', ['r4', 'iv2:6'], 'generation above the one allowed (r3): iv1-store-w6-r9',
        present=['iv1-store-w6-r9/'])
refuses('later merged folder exists', ['r4', 'iv2:6'], 'generation above the one allowed (r3): workers-dj-merged-r9',
        present=['../workers-dj-merged-r9/'])
refuses('merged folder with no generation number', ['r4', 'iv2:6'], 'merged folder with no generation number',
        present=['../workers-dj-merged-r03/'])
refuses('rerun named r03', ['r4', 'iv2:6'], 'no generation number (r2 or later): iv2-w6-r03.json', present=['iv2-w6-r03.json'])
refuses('rerun named r1', ['r4', 'iv2:6'], 'no generation number (r2 or later): iv2-w6-r1.json', present=['iv2-w6-r1.json'])
refuses('rerun named r3x', ['r4', 'iv2:6'], 'no generation number (r2 or later): iv2-w6-r3x.json', present=['iv2-w6-r3x.json'])
refuses('rerun of an arm with no first attempt', ['r4', 'iv2:6'], 'no first attempt: iv1-w2-r2.json',
        present=['iv1-w2-r2.json'])
refuses('unknown file among the attempts', ['r4', 'iv2:6'], 'unknown file among the attempts: iv2-w6.json.bak',
        present=['iv2-w6.json.bak'])
refuses('workers with a leading zero among the attempts', ['r4', 'iv2:6'], 'unknown file among the attempts: iv2-w06.json',
        present=['iv2-w06.json'])


def first_attempt(name, out_exists):
    """Round 3 re-check (P2): the first-attempt script must refuse an existing OUT before its lock wait,
    so it cannot write a first-attempt JSON over a crashed attempt; with no OUT it proceeds (stub)."""
    root = WORK/('h%03d' % (len(results)+1))
    fake_harness(root)
    if not out_exists:
        (root/'evidence'/'workers-dj').rename(root/'evidence'/'workers-dj-set-aside')
    text = (HERE/'run_workers_parity_dj.sh').read_text(encoding='utf8')
    text, n1 = re.subn(r'^G=.*$', 'G="%s"' % root.as_posix(), text, count=1, flags=re.M)
    text, n2 = re.subn(r'^PY=.*$', 'PY="%s"' % (root/'stub.sh').as_posix(), text, count=1, flags=re.M)
    assert n1 == n2 == 1, (n1, n2)
    path = root/'first-copy.sh'
    path.write_bytes(text.encode('utf8'))
    run = subprocess.run([BASH, str(path)], capture_output=True, text=True, timeout=120)
    out = (run.stdout+run.stderr).strip()
    if out_exists:
        fine = run.returncode == 2 and 'exists:' in out and 'lock acquired' not in out
    else:
        fine = 'lock acquired' in out and 'summary exit 0' in out
    record('first-attempt script: ' + name, 0 if fine else 1, 0, 'exit %d: %s' % (run.returncode, out.replace('\n', ' | ')[-140:]))


first_attempt('refuses the real tree (existing OUT, crashed attempt cannot be overwritten)', True)
first_attempt('control: proceeds when OUT does not exist (stub runtime)', False)

TEXT = HARNESS.read_text(encoding='utf8')
AUDIT = re.search(r'^audit \(\) \{.*?^\}\n', TEXT, re.S | re.M)
TAIL = re.search(r'^newest \(\) \{.*\Z', TEXT, re.S | re.M)


def merge(name, want, gen, specs, present, check, r2=None, extra=()):
    """Run the harness's audit() + newest() + merge + summary section on a fake OUT holding `present`
    JSON files and `extra` entries (a trailing / makes a folder); r2 overrides the workers-six-r2
    serials."""
    root = WORK/('m%02d' % (len(results)+1))
    out, g = root/'out', root/'g'
    out.mkdir(parents=True)
    (g/'evidence'/'workers-six-r2').mkdir(parents=True)
    files = clean()
    for stem in ('iv2-serial', 'iv1-serial'):
        body = (r2 or {}).get(stem, files['r2', stem])
        (g/'evidence'/'workers-six-r2'/(stem + '.json')).write_text(json.dumps(body), encoding='utf8')
    for stem, d in present.items():
        base = stem.split('-r')[0] if re.search(r'-r\d+$', stem) else stem
        body = copy.deepcopy(files['out', base]) if d is None else d
        (out/(stem + '.json')).write_text(json.dumps(body), encoding='utf8')
    for p in extra:
        (out/p.rstrip('/')).mkdir() if p.endswith('/') else (out/p).write_text('', encoding='utf8')
    if TAIL is None or AUDIT is None:
        record('merge: ' + name, 'no tail', want, 'audit() or newest() not found in the harness')
        return
    script = ('OUT="%s"\nG="%s"\nPY="%s"\ngen=%s\nGN=%s\nM="$G/evidence/workers-dj-merged-$gen"\nset -- %s\n'
              % (out.as_posix(), g.as_posix(), Path(sys.executable).as_posix(), gen, gen[1:], ' '.join(specs))
              + AUDIT.group(0) + TAIL.group(0))
    run = subprocess.run([BASH, '-c', script], capture_output=True, text=True, cwd=str(HERE), timeout=120)
    m = g/'evidence'/('workers-dj-merged-' + gen)
    text = (run.stdout+run.stderr).strip()
    detail = check(m, text) if run.returncode == want else None
    code = run.returncode if detail in (None, True) else 'check: %s' % detail
    record('merge: ' + name, code, want, text.replace('\n', ' | '))


def same(m, stem, src):
    return json.loads((m/(stem + '.json')).read_text()) == src or '%s is not the expected file' % stem


def marked(tag):
    d = clean()['out', tag.split('@')[0]]
    d['wall_s'] = tag   # a harmless field that tells the copies apart
    return d


def arm_with(stem, *mutations):
    files = clean()
    for f in mutations:
        f(files)
    return files['out', stem]


ALL = {s: None for s in ('iv2-serial', 'iv2-w2', 'iv2-w4', 'iv2-w6', 'iv1-serial', 'iv1-w4', 'iv1-w6')}
def superseded_are(m, *names):
    got = sorted(p.name for p in (m/'superseded').iterdir()) if (m/'superseded').is_dir() else None
    return got == sorted(names) or 'superseded/ holds %s, want %s' % (got, sorted(names))


def then(*checks):
    """All of these merge checks hold (each returns True or a message)."""
    def check(m, t):
        for c in checks:
            r = c(m, t)
            if r is not True:
                return r or 'check failed'
        return True
    return check


merge('r3 output stands in for first + r2, both judged', 0, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6': marked('iv2-w6@first'), 'iv2-w6-r2': marked('iv2-w6@r2'), 'iv2-w6-r3': marked('iv2-w6@r3')}),
      then(lambda m, t: same(m, 'iv2-w6', marked('iv2-w6@r3')),
           lambda m, t: superseded_are(m, 'iv2-w6.json', 'iv2-w6-r2.json'),
           lambda m, t: ('superseded iv2-w6.json PASS' in t and 'superseded iv2-w6-r2.json PASS' in t)
           or 'the summary did not judge both superseded attempts'))
merge('r2 stands in when r3 reran another arm', 0, 'r3', ['iv1:6'],
      dict(ALL, **{'iv2-w6': marked('iv2-w6@first'), 'iv2-w6-r2': marked('iv2-w6@r2'),
                   'iv1-w6': marked('iv1-w6@first'), 'iv1-w6-r3': marked('iv1-w6@r3')}),
      lambda m, t: same(m, 'iv2-w6', marked('iv2-w6@r2')) is True and same(m, 'iv1-w6', marked('iv1-w6@r3')))
merge('later generation r4 (failed) beside r3: FAIL, nothing merged (re-review P1)', 1, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r3': marked('iv2-w6@r3'), 'iv2-w6-r4': dict(marked('iv2-w6@r4'), records_sha256='X'*64)}),
      lambda m, t: ('generation above the one allowed (r3): iv2-w6-r4.json' in t and not m.exists())
      or 'refused for another reason, or merged')
merge('crashed r3 (log and store, no JSON) under a passing r4: FAIL (re-review P1)', 1, 'r4', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r4': None}), extra=['iv2-w6-r3.log', 'iv2-store-w6-r3/'],
      check=lambda m, t: ('no JSON (crashed or killed): iv2-w6-r3.log' in t
                          and 'no JSON (crashed or killed): iv2-store-w6-r3' in t and not m.exists())
      or 'refused for another reason, or merged')
merge('this generation crashed on one of two arms: FAIL', 1, 'r3', ['iv2:6', 'iv1:6'],
      dict(ALL, **{'iv2-w6-r3': None}), extra=['iv1-w6-r3.log', 'iv1-store-w6-r3/'],
      check=lambda m, t: 'no JSON (crashed or killed): iv1-w6-r3.log' in t or 'refused for another reason')
merge('rerun of an arm with no first attempt: FAIL', 1, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r3': None, 'iv1-w2-r2': marked('iv1-w4@r2')}),
      lambda m, t: 'no first attempt: iv1-w2-r2.json' in t or 'refused for another reason')
merge('rerun named r1 (failed): FAIL', 1, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r3': None, 'iv2-w6-r1': dict(marked('iv2-w6@r1'), records_sha256='X'*64)}),
      lambda m, t: 'no generation number (r2 or later): iv2-w6-r1.json' in t or 'refused for another reason')
merge('crashed r4 serial (store, no JSON): FAIL', 1, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r3': None}), extra=['iv1-store-r4enc/'],
      check=lambda m, t: 'r4 serial with no JSON (crashed or killed): iv1-store-r4enc' in t or 'refused for another reason')
merge('logs and stores beside their JSON: PASS', 0, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r2': None, 'iv2-w6-r3': None}),
      extra=['iv2-w6.log', 'iv2-store-w6/', 'iv2-w6-r2.log', 'iv2-store-w6-r2/', 'iv2-w6-r3.log', 'iv2-store-w6-r3/',
             'iv1-w4.log', 'iv1-store-w4/', 'iv2-store/', 'iv2-serial.log'],
      check=lambda m, t: superseded_are(m, 'iv2-w6.json', 'iv2-w6-r2.json'))
merge('r3 over a FAILED first attempt: FAIL (round 3 P1)', 1, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6': dict(marked('iv2-w6@first'), records_sha256='X'*64), 'iv2-w6-r3': None}),
      lambda m, t: 'superseded iv2-w6.json FAIL' in t or 'the failed first attempt was not judged')
merge('r3 over a void first and a FAILED r2: FAIL (P1)', 1, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6': arm_with('iv2-w6', held('iv2-w6', ('cpu', 2))),
                   'iv2-w6-r2': arm_with('iv2-w6', held('iv2-w6', ('cpu', 5), peak=2)), 'iv2-w6-r3': None}),
      lambda m, t: ('superseded iv2-w6.json VOID-ENVIRONMENT' in t and 'superseded iv2-w6-r2.json FAIL' in t)
      or 'verdicts of the superseded attempts not as planted')
merge('r3 passing over two void attempts: PASS', 0, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6': arm_with('iv2-w6', held('iv2-w6', ('cpu', 1))),
                   'iv2-w6-r2': arm_with('iv2-w6', held('iv2-w6', ('memory', 2))), 'iv2-w6-r3': None}),
      then(lambda m, t: superseded_are(m, 'iv2-w6.json', 'iv2-w6-r2.json'),
           lambda m, t: t.count('VOID-ENVIRONMENT peak') == 2 or 'both superseded attempts should be VOID'))
merge('non-numeric rerun names (failed): FAIL, nothing merged (re-review P1)', 1, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r3': marked('iv2-w6@r3'), 'iv2-w6-r3x': dict(marked('iv2-w6@r3x'), records_sha256='X'*64),
                   'iv2-w6-r03': dict(marked('iv2-w6@r03'), records_sha256='X'*64)}),
      lambda m, t: ('no generation number (r2 or later): iv2-w6-r3x.json' in t
                    and 'no generation number (r2 or later): iv2-w6-r03.json' in t and not m.exists())
      or 'refused for another reason, or merged')
merge('r10 beats r9 (numeric, not text, order)', 0, 'r10', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r9': marked('iv2-w6@r9'), 'iv2-w6-r10': marked('iv2-w6@r10')}),
      lambda m, t: same(m, 'iv2-w6', marked('iv2-w6@r10')))
merge('this generation missing: FAIL, not the r2 copy', 1, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r2': marked('iv2-w6@r2')}), lambda m, t: True)
merge('r4 serial replaces r2view serial without being named', 0, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r3': marked('iv2-w6@r3'), 'iv1-serial-r4enc': marked('iv1-serial@r4enc')}),
      lambda m, t: same(m/'r2view', 'iv1-serial', marked('iv1-serial@r4enc')))
merge('r4 serial with other hashes reaches the summary (FAIL)', 1, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r3': None, 'iv1-serial-r4enc': dict(clean()['r2', 'iv1-serial'], streams_sha256='Q'*64)}),
      lambda m, t: 'serial equals r2 serial: False' in t or 'the summary did not see the r4 serial')
merge('r4 serial of another package: FAIL before the summary (P3e)', 1, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r3': None, 'iv1-serial-r4enc': dict(clean()['r2', 'iv1-serial'], package_digest='Q'*64)}),
      lambda m, t: ("r4 serial is not r2's package" in t and not (m/'summary.txt').exists()
                    and same(m/'r2view', 'iv1-serial', clean()['r2', 'iv1-serial']) is True)
      or 'refused for another reason, or the summary ran')
merge('r2 serial without a package digest: FAIL (P3e)', 1, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r3': None, 'iv1-serial-r4enc': clean()['r2', 'iv1-serial']}),
      lambda m, t: "r4 serial is not r2's package" in t or 'refused for another reason',
      r2={'iv1-serial': {k: v for k, v in clean()['r2', 'iv1-serial'].items() if k != 'package_digest'}})
merge('void r3 arm passes the summary exit 3 through', 3, 'r3', ['iv2:6'],
      dict(ALL, **{'iv2-w6-r3': arm_with('iv2-w6', held('iv2-w6', ('cpu', 2)))}),
      lambda m, t: 'iv2-w6 ' in (m/'sources.txt').read_text() or 'sources.txt has no iv2-w6 line')
ok = all(r['ok'] for r in results.values())
(WORK/'proof.json').write_text(json.dumps(dict(summary=str(SUMMARY), harness=str(HARNESS), results=results, ok=ok),
                                          indent=1), encoding='utf8')
print('PROOF', 'PASS' if ok else 'FAIL', '%d/%d as expected' % (sum(r['ok'] for r in results.values()), len(results)))
sys.exit(0 if ok else 1)
