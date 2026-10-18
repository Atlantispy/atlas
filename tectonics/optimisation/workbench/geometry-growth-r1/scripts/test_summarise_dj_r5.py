"""Mutant proof of summarise_dj.py (VOID-ENVIRONMENT verdict) and run_dj_rearm_r5.sh (Plan 03 / D08).

Usage: python -B -I test_summarise_dj_r5.py WORK [--r5-delta | --r4-delta | --r3-delta]
  (WORK must not exist; small lane, no runtime loaded)
Retains all 144 baseline summary/harness/merge cases from test_summarise_dj.py (2e2cbaf0...) and all
46 focused Plan 03 / D08 / R1 / R1b / R5 cases covering:
- Child PATH repair when parent PATH omits Git usr/bin (--preflight-only and harness start).
- Enforced finite deadline across the ENTIRE preflight probe and failure/cleanup path (R1 + R1b + R5):
  - Functional probe bounded by DJ_PREFLIGHT_TIMEOUT_S (default 60s) via GNU timeout -k;
  - Scratch directory removed inside probe before invoking PY;
  - Fallback scratch cleanup bounded by DJ_CLEANUP_TIMEOUT_S (default 2s) via rm without ever re-entering PY;
  - Exact preserved leftover scratch path emitted on EVERY failed probe (both timeout 124/137 and ordinary
    non-zero probe exit when fallback rm fails or times out);
  - Native and owned process survival checkers record psutil.AccessDenied as UNKNOWN (never swallowing it
    as absence and never mislabelling it as a confirmed survivor) and prevent a clean process-death PASS,
    verified by bounded injected-exception checks.
When --r5-delta is passed, runs only the 2 affected R5 checks (reusing proof-r4-delta-r2, proof-r3-delta,
and proof-r2). Writes WORK/proof.json; exit 0 only if every executed case is as expected.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
REAL_G = T/'fidelity-integration-20261005'/'continuation-repair-20261013'/'optimisation-20261014'/'resumability-r1'/'geometry-growth-r1'
REAL_SCRIPTS = REAL_G/'scripts'
SUMMARY = REAL_SCRIPTS/'summarise_dj.py'
HARNESS = HERE/'run_dj_rearm_r5.sh'
BASH = 'C:/Program Files/Git/usr/bin/bash.exe'
GIT_USR_BIN = Path('C:/Program Files/Git/usr/bin')
WORK = Path(sys.argv[1])
ONLY_R5_DELTA = '--r5-delta' in sys.argv[2:]
ONLY_R4_DELTA = ('--r4-delta' in sys.argv[2:]) or ONLY_R5_DELTA
ONLY_R3_DELTA = ('--r3-delta' in sys.argv[2:]) or ONLY_R4_DELTA
GIB = 1 << 30
PW, RES = 805306368, 2 << 30   # the r6 policy's memory booking, which round 3 (P2) pins
RAM = psutil.virtual_memory().total   # the summary reads the same figure
D08_MTIME_NS = 1792182120860677600
D08_LOG_SHA = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
D08_Q21B_SHA = '3ba3da59468bb4db3bc3a3fffd2c4ed0f263aafd2589364e7804285674fc1e3f'
REAL_OUT = REAL_G/'evidence'/'workers-dj'
REAL_Q21B = REAL_G/'work'/'dj-rearm-r3-q21b.log'
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


def ungated(stem, which, reason='eligible work below threshold', **kv):
    """The session stopped before any gate was read, as the runtime records it; its controller is gone."""
    def m(files):
        s = sess(files, stem, which)
        s.clear()
        s.update(dict(family=which, workers=0, notes=[], last_error=None, gates=[], route='serial', reason=reason,
                      detail='expected 15.564 s of eligible work in this pass'), **kv)
        files['out', stem]['concurrency']['controllers'].pop('wall_batches' if which == 'wall' else 'interface_batches', None)
    return m


def superseded(stem, d):
    return lambda f: f.__setitem__(('out/superseded', stem), d)


def arm_of(stem, *mutations):
    files = clean()
    for f in mutations:
        f(files)
    return files['out', stem]


CPU2 = held('iv2-w6', ('cpu', 2))
MEM2 = held('iv2-w6', ('memory', 2))
REF0 = both(held('iv2-w6', ('cpu', 0)), lambda f: f['out', 'iv2-w6']['concurrency']['controllers'].clear())
IV1H = held('iv1-w6', ('cpu', 2))

# --- summary verdicts ---------------------------------------------------------------------------
WORK.mkdir(parents=True, exist_ok=False)
if not ONLY_R3_DELTA:
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
    case('iv1 w4 batch peaks 2, another controller 3 (FAIL, round 3)', 1,
         both(held('iv1-w4', ('cpu', 3), peak=2),
              lambda f: f['out', 'iv1-w4']['concurrency']['controllers'].__setitem__('endpoints', dict(peak_live=3))))
    case('iv1 w4 interface peak 2, wall peak 3 (PASS)', 0,
         both(held('iv1-w4', ('cpu', 3)), setv('iv1-w4', ('concurrency', 'controllers', 'interface_batches', 'peak_live'), 2)))
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
def fake_harness(root, present=(), absent=(), d08_orphan=False, py_override=None, mutate_root=None):
    """The harness with only its G= and PY= lines changed, on a fresh fake evidence tree that mirrors
    the real one's names (folders empty, files '{}'); when d08_orphan=False, iv2-w6-r3.log is omitted
    so the 144 baseline pre-q21 controls run unchanged; when d08_orphan=True, the real 0-byte
    iv2-w6-r3.log (with its exact D08 mtime) and work/dj-rearm-r3-q21b.log are mirrored in place."""
    out = root/'evidence'/'workers-dj'
    (root/'scripts').mkdir(parents=True)
    (root/'work').mkdir(parents=True)
    out.mkdir(parents=True)
    for p in sorted(REAL_OUT.iterdir()):
        if p.name in absent:
            continue
        if p.name == 'iv2-w6-r3.log' and not d08_orphan:
            continue
        if p.name == 'iv2-w6-r3.log' and d08_orphan:
            dst = out/p.name
            dst.write_bytes(b'')
            os.utime(dst, ns=(D08_MTIME_NS, D08_MTIME_NS))
            continue
        (out/p.name).mkdir() if p.is_dir() else (out/p.name).write_text('{}', encoding='utf8')
    if d08_orphan and 'dj-rearm-r3-q21b.log' not in absent:
        shutil.copy2(REAL_Q21B, root/'work'/'dj-rearm-r3-q21b.log')
    for p in present:
        path = out/p.rstrip('/')
        path.mkdir(parents=True, exist_ok=True) if p.endswith('/') else path.write_text('{}', encoding='utf8')
    stub = root/'stub.sh'
    stub.write_bytes(
        b'#!/usr/bin/env bash\n'
        b'if [ "${1:-}" = "-B" ] && [ "${2:-}" = "parallel_parity.py" ]; then\n'
        b'  printf "called\\n" > "$(dirname "$0")/parity-called.marker"\n'
        b'fi\n'
        b'echo STUB-RUN "$@"\n'
        b'exit 0\n'
    )
    if mutate_root:
        mutate_root(root)
    py_target = py_override if py_override is not None else stub.as_posix()
    text = HARNESS.read_text(encoding='utf8')
    text, n1 = re.subn(r'^G=.*$', 'G="%s"' % root.as_posix(), text, count=1, flags=re.M)
    text, n2 = re.subn(r'^PY=.*$', 'PY="%s"' % py_target, text, count=1, flags=re.M)
    assert n1 == n2 == 1, (n1, n2)
    path = root/'harness-copy.sh'
    path.write_bytes(text.encode('utf8'))
    return path


def harness_run(args, present=(), absent=(), d08_orphan=False, env_overrides=None, py_override=None, mutate_root=None):
    root = WORK/('h%03d' % (len(results)+1))
    path = fake_harness(root, present, absent, d08_orphan=d08_orphan, py_override=py_override, mutate_root=mutate_root)
    env = dict(os.environ)
    if env_overrides:
        for k, v in env_overrides.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
    run = subprocess.run([BASH, str(path), *args], capture_output=True, text=True, timeout=120, env=env)
    return run.returncode, (run.stdout+run.stderr).strip(), root


def refuses(name, args, why, present=(), absent=(), d08_orphan=False, env_overrides=None, py_override=None, mutate_root=None):
    """The harness must exit 2 before starting, for the reason `why` (a fragment of its message)."""
    code, out, root = harness_run(args, present, absent, d08_orphan=d08_orphan, env_overrides=env_overrides,
                                  py_override=py_override, mutate_root=mutate_root)
    fine = (code == 2 and why in out and 'start' not in out and 'STUB-RUN' not in out
            and not (root/'parity-called.marker').exists())
    record('harness refuses: ' + name, 0 if fine else 1, 0, 'exit %d: %s' % (code, out.replace('\n', ' | ')[-140:]))


def proceeds(name, args, present=(), d08_orphan=False, env_overrides=None):
    code, out, _ = harness_run(args, present, d08_orphan=d08_orphan, env_overrides=env_overrides)
    record('harness control: ' + name,
           0 if code != 2 and 'start %s' % ' '.join(args) in out and 'STUB-RUN' in out else 1, 0,
           'exit %d: %s' % (code, out.replace('\n', ' | ')[-140:]))


def first_attempt(name, out_exists):
    """Round 3 re-check (P2): the first-attempt script must refuse an existing OUT before its lock wait,
    so it cannot write a first-attempt JSON over a crashed attempt; with no OUT it proceeds (stub)."""
    root = WORK/('h%03d' % (len(results)+1))
    fake_harness(root)
    if not out_exists:
        (root/'evidence'/'workers-dj').rename(root/'evidence'/'workers-dj-set-aside')
    text = (REAL_SCRIPTS/'run_workers_parity_dj.sh').read_text(encoding='utf8')
    text, n1 = re.subn(r'^G=.*$', 'G="%s"' % root.as_posix(), text, count=1, flags=re.M)
    text, n2 = re.subn(r'^PY=.*$', 'PY="%s"' % (root/'stub.sh').as_posix(), text, count=1, flags=re.M)
    assert n1 == n2 == 1, (n1, n2)
    path = root/'first-copy.sh'
    path.write_bytes(text.encode('utf8'))
    first_env = dict(os.environ, PATH='C:/Program Files/Git/usr/bin;' + os.environ.get('PATH', ''))
    run = subprocess.run([BASH, str(path)], capture_output=True, text=True, timeout=120, cwd=str(REAL_SCRIPTS), env=first_env)
    out = (run.stdout+run.stderr).strip()
    if out_exists:
        fine = run.returncode == 2 and 'exists:' in out and 'lock acquired' not in out
    else:
        fine = 'lock acquired' in out and 'summary exit 0' in out
    record('first-attempt script: ' + name, 0 if fine else 1, 0, 'exit %d: %s' % (run.returncode, out.replace('\n', ' | ')[-140:]))


TEXT = HARNESS.read_text(encoding='utf8')
AUDIT = re.search(r'^audit \(\) \{.*?^\}\n', TEXT, re.S | re.M)
TAIL = re.search(r'^newest \(\) \{.*\Z', TEXT, re.S | re.M)


def merge(name, want, gen, specs, present, check, r2=None, extra=(), d08_orphan=False, mutate_merge=None):
    """Run the harness's audit() + newest() + merge + summary section on a fake OUT holding `present`
    JSON files and `extra` entries (a trailing / makes a folder); r2 overrides the workers-six-r2
    serials."""
    root = WORK/('m%02d' % (len(results)+1))
    out, g = root/'out', root/'g'
    out.mkdir(parents=True)
    (g/'evidence'/'workers-six-r2').mkdir(parents=True)
    (g/'work').mkdir(parents=True)
    files = clean()
    for stem in ('iv2-serial', 'iv1-serial'):
        body = (r2 or {}).get(stem, files['r2', stem])
        (g/'evidence'/'workers-six-r2'/(stem + '.json')).write_text(json.dumps(body), encoding='utf8')
    for stem, d in present.items():
        base = stem.split('-r')[0] if re.search(r'-r\d+$', stem) else stem
        body = copy.deepcopy(files['out', base]) if d is None else d
        (out/(stem + '.json')).write_text(json.dumps(body), encoding='utf8')
    if d08_orphan:
        d08_log = out/'iv2-w6-r3.log'
        d08_log.write_bytes(b'')
        os.utime(d08_log, ns=(D08_MTIME_NS, D08_MTIME_NS))
        shutil.copy2(REAL_Q21B, g/'work'/'dj-rearm-r3-q21b.log')
    for p in extra:
        (out/p.rstrip('/')).mkdir() if p.endswith('/') else (out/p).write_text('', encoding='utf8')
    if mutate_merge:
        mutate_merge(out, g)
    if TAIL is None or AUDIT is None:
        record('merge: ' + name, 'no tail', want, 'audit() or newest() not found in the harness')
        return
    script = ('export PATH="/usr/bin:$PATH"\nOUT="%s"\nG="%s"\nPY="%s"\ngen=%s\nGN=%s\nM="$G/evidence/workers-dj-merged-$gen"\nset -- %s\n'
              % (out.as_posix(), g.as_posix(), Path(sys.executable).as_posix(), gen, gen[1:], ' '.join(specs))
              + AUDIT.group(0) + TAIL.group(0))
    run = subprocess.run([BASH, '-c', script], capture_output=True, text=True, cwd=str(REAL_SCRIPTS), timeout=120)
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


if not ONLY_R3_DELTA:
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

    first_attempt('refuses the real tree (existing OUT, crashed attempt cannot be overwritten)', True)
    first_attempt('control: proceeds when OUT does not exist (stub runtime)', False)

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


# --- Plan 03 / D08 / R1 / R1b / R5 additions ----------------------------------------------------
REQUIRED_UTILS = ('bash', 'timeout', 'date', 'seq', 'cp', 'rm', 'sleep', 'mkdir', 'basename', 'sha256sum', 'cut', 'cmp', 'cat')


def run_preflight_only(name, want, args=('--preflight-only',), env_overrides=None, want_substr=None):
    env = dict(os.environ)
    if env_overrides:
        for k, v in env_overrides.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
    run = subprocess.run([BASH, str(HARNESS), *args], capture_output=True, text=True, timeout=60, env=env)
    out = (run.stdout+run.stderr).strip()
    ok_check = (run.returncode == want
                and ('PREFLIGHT OK' in out and 'd08_orphan=INVALID_LAUNCH_ENVIRONMENT_VERIFIED' in out
                     if want == 0 else 'PREFLIGHT OK' not in out)
                and (want_substr is None or want_substr in out))
    record('plan03 preflight: ' + name, run.returncode if ok_check else 'bad-output', want, out.replace('\n', ' | '))


def make_filtered_bin(root, omit_util=None, custom_cp=None, custom_rm=None):
    """Build an isolated bin folder with wrappers for all required utilities except omit_util."""
    bdir = root/'isolated_bin'
    bdir.mkdir(parents=True, exist_ok=True)
    for u in REQUIRED_UTILS:
        if u == omit_util:
            continue
        target = bdir/u
        if u == 'cp' and custom_cp is not None:
            target.write_bytes(custom_cp)
            continue
        if u == 'rm' and custom_rm is not None:
            target.write_bytes(custom_rm)
            continue
        target.write_bytes(('#!/usr/bin/bash\nexec "/usr/bin/%s" "$@"\n' % u).encode('utf8'))
    return bdir


def _check_hanging_probe_cleanup(pid_file, process_factory=psutil.Process):
    """Wait up to 0.5s for OS process table reaping, then verify all recorded Windows PIDs are gone.
    Distinguishes confirmed survivors (alive) from psutil.AccessDenied (unknown)."""
    if not pid_file.is_file():
        return [], [], ['pid_file_missing']
    raw = [line.strip() for line in pid_file.read_text(encoding='utf8').splitlines() if line.strip().isdigit()]
    wpids = [int(x) for x in raw]
    deadline = time.monotonic() + 0.5

    def _probe_wpids():
        alive, unknown = [], []
        for pid in wpids:
            try:
                proc = process_factory(pid)
                if proc.is_running():
                    alive.append(pid)
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                unknown.append('UNKNOWN:%d' % pid)
        return alive, unknown

    alive, unknown = _probe_wpids()
    while (alive or unknown) and time.monotonic() < deadline:
        time.sleep(0.05)
        alive, unknown = _probe_wpids()
    return wpids, alive, unknown


def _check_native_identities(native_file, process_factory=psutil.Process):
    """Verify recorded native (pid, create_time) processes are no longer running before any watchdog acts.
    psutil.AccessDenied is recorded in `unknown` (never swallowed as absence and never labelled a survivor)."""
    if not native_file.is_file():
        return [], [], ['native_file_missing'], False
    entries = [json.loads(line) for line in native_file.read_text(encoding='utf8').splitlines() if line.strip()]
    deadline = time.monotonic() + 0.5

    def _still_running():
        alive, unknown = [], []
        for item in entries:
            pid = int(item['pid'])
            ct = float(item['create_time'])
            try:
                proc = process_factory(pid)
                if proc.is_running() and abs(proc.create_time() - ct) < 1.0:
                    alive.append(pid)
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                unknown.append('UNKNOWN:%d' % pid)
        return alive, unknown

    alive, unknown = _still_running()
    while (alive or unknown) and time.monotonic() < deadline:
        time.sleep(0.05)
        alive, unknown = _still_running()
    return [int(x['pid']) for x in entries], alive, unknown, True


def _check_owned_identities(owned_map, exclude_pid=None):
    """Check tracked psutil.Process descendants; record AccessDenied as UNKNOWN rather than absence."""
    alive, unknown = [], []
    for (pid, ct), proc in list(owned_map.items()):
        if exclude_pid is not None and pid == exclude_pid:
            continue
        try:
            if proc.is_running() and abs(proc.create_time() - ct) < 1.0:
                alive.append(pid)
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            unknown.append('UNKNOWN:%d' % pid)
    return alive, unknown


def _death_check_clean(alive_nat, unk_nat, alive_own, unk_own):
    """A clean process-death PASS requires zero confirmed survivors AND zero UNKNOWN (AccessDenied) states."""
    return alive_nat == [] and unk_nat == [] and alive_own == [] and unk_own == []


# R5.1: Ordinary probe failure + timed-out fallback rm bounds cleanup, stops children & reports exact leftover scratch path
def _test_ordinary_failure_and_timed_out_fallback_rm():
    root = WORK/('h%03d' % (len(results)+1))
    path = fake_harness(root, d08_orphan=True)
    pf_tmp = root/'pf_tmp'
    pf_tmp.mkdir(parents=True, exist_ok=True)
    pid_file = root/'hung-rm-ordinary.pids'
    corrupt_cp = (
        b'#!/usr/bin/bash\n'
        b'"/usr/bin/cp" "$@" || exit 1\n'
        b'for last; do :; done\n'
        b'printf "corrupted\\n" > "$last/a.txt"\n'
        b'exit 0\n'
    )
    hanging_rm = (
        '#!/usr/bin/bash\n'
        '"/usr/bin/cat" /proc/$$/winpid >> "%s" 2>/dev/null || true\n'
        '"/usr/bin/sleep" 30 &\n'
        'spid=$!\n'
        '"/usr/bin/cat" /proc/$spid/winpid >> "%s" 2>/dev/null || true\n'
        'wait $spid\n'
    ) % (pid_file.as_posix(), pid_file.as_posix())
    bdir = make_filtered_bin(root, custom_cp=corrupt_cp, custom_rm=hanging_rm.encode('utf8'))
    env = dict(
        os.environ,
        PATH=bdir.as_posix(),
        DJ_GIT_USR_BIN=bdir.as_posix(),
        DJ_PREFLIGHT_TIMEOUT_S='5',
        DJ_CLEANUP_TIMEOUT_S='1',
        DJ_PREFLIGHT_TMP=pf_tmp.as_posix(),
    )
    t0 = time.monotonic()
    run = subprocess.run([BASH, str(path), 'r4', 'iv2:6'], capture_output=True, text=True, timeout=5, env=env)
    elapsed = time.monotonic() - t0
    out = (run.stdout+run.stderr).strip()
    wpids, alive, unknown = _check_hanging_probe_cleanup(pid_file)
    leftover_scratch = list(pf_tmp.glob('dj-preflight-*'))
    exact_path_str = leftover_scratch[0].as_posix() if len(leftover_scratch) == 1 else '<none>'
    no_outputs = (not (root/'evidence'/'workers-dj'/'iv2-w6-r4.log').exists()
                  and not (root/'evidence'/'workers-dj'/'iv2-store-w6-r4').exists()
                  and not (root/'evidence'/'workers-dj-merged-r4').exists()
                  and not (root/'parity-called.marker').exists())
    fine = (run.returncode == 2
            and 'preflight failed: cmp a.txt' in out
            and ('preflight failed: probe exit 1 (leftover scratch: %s)' % exact_path_str) in out
            and elapsed < 3.5
            and len(wpids) >= 2
            and alive == []
            and unknown == []
            and len(leftover_scratch) == 1
            and no_outputs)
    record('plan03 R5.1: ordinary probe failure + timed-out rm reports exact leftover path',
           0 if fine else 1, 0,
           'exit=%d elapsed=%.2fs wpids=%s alive=%s unk=%s path=%s: %s'
           % (run.returncode, elapsed, wpids, alive, unknown, exact_path_str[-48:], out.replace('\n', ' | ')[-100:]))
_test_ordinary_failure_and_timed_out_fallback_rm()


# R5.2: Bounded injected psutil.AccessDenied check on survival checkers records UNKNOWN (not survivor) & prevents PASS
def _test_injected_access_denied_records_unknown():
    root = WORK/('h%03d' % (len(results)+1))
    root.mkdir(parents=True, exist_ok=True)
    native_file = root/'injected-native.jsonl'
    native_file.write_text(
        json.dumps({'role': 'interpreter', 'pid': 99991, 'create_time': 100.0}) + '\n'
        + json.dumps({'role': 'native_child', 'pid': 99992, 'create_time': 100.0}) + '\n',
        encoding='utf8',
    )

    class _FakeAccessDeniedProc:
        def __init__(self, pid):
            self.pid = pid

        def is_running(self):
            raise psutil.AccessDenied(self.pid)

        def create_time(self):
            raise psutil.AccessDenied(self.pid)

    def _injected_factory(pid):
        if pid == 99991:
            return _FakeAccessDeniedProc(pid)
        raise psutil.NoSuchProcess(pid)

    def _clean_factory(pid):
        raise psutil.NoSuchProcess(pid)

    nat_pids, alive_nat, unk_nat, file_ok = _check_native_identities(native_file, process_factory=_injected_factory)
    _, alive_nat_clean, unk_nat_clean, _ = _check_native_identities(native_file, process_factory=_clean_factory)
    owned_injected = {(99993, 100.0): _FakeAccessDeniedProc(99993)}
    alive_own, unk_own = _check_owned_identities(owned_injected)
    # Verify AccessDenied is recorded as UNKNOWN (never labelled a survivor in alive_*) and blocks _death_check_clean
    fine = (file_ok
            and nat_pids == [99991, 99992]
            and alive_nat == []
            and unk_nat == ['UNKNOWN:99991']
            and not _death_check_clean(alive_nat, unk_nat, [], [])
            and alive_own == []
            and unk_own == ['UNKNOWN:99993']
            and not _death_check_clean([], [], alive_own, unk_own)
            and alive_nat_clean == []
            and unk_nat_clean == []
            and _death_check_clean(alive_nat_clean, unk_nat_clean, [], []))
    record('plan03 R5.2: injected psutil.AccessDenied records UNKNOWN & blocks clean PASS',
           0 if fine else 1, 0,
           'alive_nat=%s unk_nat=%s alive_own=%s unk_own=%s blocked=%s clean_ok=%s'
           % (alive_nat, unk_nat, alive_own, unk_own,
              not _death_check_clean(alive_nat, unk_nat, [], []),
              _death_check_clean(alive_nat_clean, unk_nat_clean, [], [])))
_test_injected_access_denied_records_unknown()


if not ONLY_R5_DELTA:
    run_preflight_only('stripped parent PATH (C:/Windows/System32) passes via child PATH prefix', 0,
                       env_overrides={'PATH': 'C:/Windows/System32'}, want_substr='rm=/usr/bin/rm')
    run_preflight_only('invalid DJ_CLEANUP_TIMEOUT_S=0 refuses pre-output', 2,
                       env_overrides={'DJ_CLEANUP_TIMEOUT_S': '0'}, want_substr='preflight failed: invalid cleanup timeout 0')
    proceeds('plan03: stripped parent PATH proceeds on r4 with D08 orphan present', ['r4', 'iv2:6'],
             d08_orphan=True, env_overrides={'PATH': 'C:/Windows/System32'})

    # R1b: Hanging selected native Python interpreter (plus spawned native Python child) in both entry modes
    def _test_hanging_native_python(mode_label, tail_args):
        root = WORK/('h%03d' % (len(results)+1))
        scratch = root/'scratch'
        scratch.mkdir(parents=True, exist_ok=True)
        calls = root/'python-calls.txt'
        native_file = root/'native-pids.jsonl'
        payload_py = root/'hanging_payload.py'
        stub = root/'hanging-python.sh'
        py_exe = Path(sys.executable).as_posix()
        payload_py.write_text(
            'import json, os, subprocess, sys, time, psutil\n'
            'child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(30)"])\n'
            'me = psutil.Process(os.getpid())\n'
            'cp = psutil.Process(child.pid)\n'
            'with open(%r, "a", encoding="utf-8") as f:\n'
            '    f.write(json.dumps({"role": "interpreter", "pid": me.pid, "create_time": me.create_time()}) + "\\n")\n'
            '    f.write(json.dumps({"role": "native_child", "pid": cp.pid, "create_time": cp.create_time()}) + "\\n")\n'
            'time.sleep(30)\n' % native_file.as_posix(),
            encoding='utf8',
        )
        stub.write_bytes(
            ('#!/usr/bin/bash\n'
             'printf "%%s\\n" "$*" >> "%s"\n'
             'exec "%s" -B "%s"\n' % (calls.as_posix(), py_exe, payload_py.as_posix())).encode('utf8')
        )
        wrapper = fake_harness(root, d08_orphan=True, py_override=stub.as_posix())
        env = dict(
            os.environ,
            DJ_PREFLIGHT_TIMEOUT_S='1',
            DJ_PREFLIGHT_TMP=scratch.as_posix(),
            DJ_GIT_USR_BIN='/usr/bin',
            PYTHONHASHSEED='0',
        )
        owned = {}
        t0 = time.monotonic()
        with (root/'stdout.txt').open('w', encoding='utf8') as out_f, (root/'stderr.txt').open('w', encoding='utf8') as err_f:
            child = subprocess.Popen([BASH, str(wrapper), *tail_args], env=env, stdout=out_f, stderr=err_f)
            parent = psutil.Process(child.pid)
            owned[(parent.pid, parent.create_time())] = parent
            while child.poll() is None and time.monotonic() - t0 < 4.0:
                try:
                    for proc in parent.children(recursive=True):
                        owned[(proc.pid, proc.create_time())] = proc
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                time.sleep(0.05)
            watchdog_fired = child.poll() is None
            elapsed = time.monotonic() - t0
            native_pids, alive_native, unk_native, native_file_ok = _check_native_identities(native_file)
            alive_owned, unk_owned = _check_owned_identities(owned, exclude_pid=child.pid)
            for proc in reversed(list(owned.values())):
                try:
                    if proc.is_running():
                        proc.kill()
                except psutil.NoSuchProcess:
                    pass
            for pid in alive_native:
                try:
                    psutil.Process(pid).kill()
                except psutil.NoSuchProcess:
                    pass
            child.wait(timeout=2)
        out = ((root/'stdout.txt').read_text(encoding='utf8') + (root/'stderr.txt').read_text(encoding='utf8')).strip()
        call_lines = calls.read_text(encoding='utf8').splitlines() if calls.is_file() else []
        cleanup_reentered_py = any('shutil.rmtree' in line for line in call_lines)
        leftover_scratch = list(scratch.glob('dj-preflight-*'))
        no_outputs = (not (root/'evidence'/'workers-dj'/'iv2-w6-r4.log').exists()
                      and not (root/'evidence'/'workers-dj'/'iv2-store-w6-r4').exists()
                      and not (root/'evidence'/'workers-dj-merged-r4').exists()
                      and not (root/'parity-called.marker').exists())
        fine = (not watchdog_fired
                and child.returncode == 2
                and 'preflight failed: timed out after 1s (exit 124)' in out
                and 'PREFLIGHT OK' not in out
                and 'start' not in out
                and len(call_lines) == 1
                and not cleanup_reentered_py
                and native_file_ok
                and len(native_pids) >= 2
                and _death_check_clean(alive_native, unk_native, alive_owned, unk_owned)
                and leftover_scratch == []
                and no_outputs)
        record('plan03 R1b: hanging native Python in %s times out & kills native children' % mode_label,
               0 if fine else 1, 0,
               'exit=%s watchdog=%s elapsed=%.2fs py_calls=%d native=%s alive_nat=%s unk_nat=%s alive_own=%s unk_own=%s: %s'
               % (child.returncode, watchdog_fired, elapsed, len(call_lines), native_pids, alive_native,
                  unk_native, alive_owned, unk_owned, out.replace('\n', ' | ')[-80:]))

    _test_hanging_native_python('--preflight-only', ['--preflight-only'])
    _test_hanging_native_python('r4 launch', ['r4', 'iv2:6'])

    # R1b: Double-hang (hanging cp probe + hanging fallback rm)
    def _test_hanging_probe_and_hanging_fallback_rm():
        root = WORK/('h%03d' % (len(results)+1))
        path = fake_harness(root, d08_orphan=True)
        pf_tmp = root/'pf_tmp'
        pf_tmp.mkdir(parents=True, exist_ok=True)
        pid_file = root/'hung-double.pids'
        hanging_tool = (
            '#!/usr/bin/bash\n'
            '"/usr/bin/cat" /proc/$$/winpid >> "%s" 2>/dev/null || true\n'
            '"/usr/bin/sleep" 30 &\n'
            'spid=$!\n'
            '"/usr/bin/cat" /proc/$spid/winpid >> "%s" 2>/dev/null || true\n'
            'wait $spid\n'
        ) % (pid_file.as_posix(), pid_file.as_posix())
        bdir = make_filtered_bin(root, custom_cp=hanging_tool.encode('utf8'), custom_rm=hanging_tool.encode('utf8'))
        env = dict(
            os.environ,
            PATH=bdir.as_posix(),
            DJ_GIT_USR_BIN=bdir.as_posix(),
            DJ_PREFLIGHT_TIMEOUT_S='1',
            DJ_CLEANUP_TIMEOUT_S='1',
            DJ_PREFLIGHT_TMP=pf_tmp.as_posix(),
        )
        t0 = time.monotonic()
        run = subprocess.run([BASH, str(path), 'r4', 'iv2:6'], capture_output=True, text=True, timeout=6, env=env)
        elapsed = time.monotonic() - t0
        out = (run.stdout+run.stderr).strip()
        wpids, alive, unknown = _check_hanging_probe_cleanup(pid_file)
        leftover_scratch = list(pf_tmp.glob('dj-preflight-*'))
        no_outputs = (not (root/'evidence'/'workers-dj'/'iv2-w6-r4.log').exists()
                      and not (root/'evidence'/'workers-dj'/'iv2-store-w6-r4').exists()
                      and not (root/'evidence'/'workers-dj-merged-r4').exists()
                      and not (root/'parity-called.marker').exists())
        fine = (run.returncode == 2
                and 'preflight failed: timed out after 1s (exit 124) (leftover scratch:' in out
                and elapsed < 4.5
                and len(wpids) >= 4
                and alive == []
                and unknown == []
                and len(leftover_scratch) == 1
                and no_outputs)
        record('plan03 R1b: hanging cp + hanging fallback rm bounds cleanup & reports leftover scratch',
               0 if fine else 1, 0,
               'exit %d elapsed=%.2fs wpids=%s alive=%s unk=%s leftover=%d: %s'
               % (run.returncode, elapsed, wpids, alive, unknown, len(leftover_scratch), out.replace('\n', ' | ')[-90:]))
    _test_hanging_probe_and_hanging_fallback_rm()

    def _test_missing_rm():
        root = WORK/('h%03d' % (len(results)+1))
        path = fake_harness(root, d08_orphan=True)
        bdir = make_filtered_bin(root, omit_util='rm')
        env = dict(os.environ, PATH=bdir.as_posix(), DJ_GIT_USR_BIN=bdir.as_posix())
        run = subprocess.run([BASH, str(path), 'r4', 'iv2:6'], capture_output=True, text=True, timeout=60, env=env)
        out = (run.stdout+run.stderr).strip()
        no_outputs = (not (root/'evidence'/'workers-dj'/'iv2-w6-r4.log').exists()
                      and not (root/'evidence'/'workers-dj'/'iv2-store-w6-r4').exists()
                      and not (root/'evidence'/'workers-dj-merged-r4').exists()
                      and not (root/'parity-called.marker').exists())
        fine = (run.returncode == 2 and 'preflight failed: missing utility rm' in out
                and 'start' not in out and 'STUB-RUN' not in out and no_outputs)
        record('plan03 missing utility refuses pre-output: rm', 0 if fine else 1, 0,
               'exit %d: %s' % (run.returncode, out.replace('\n', ' | ')[-140:]))
    _test_missing_rm()


if not ONLY_R4_DELTA:
    run_preflight_only('extra argument to --preflight-only refuses', 2, args=('--preflight-only', 'extra'))
    run_preflight_only('invalid DJ_PREFLIGHT_TIMEOUT_S=abc refuses pre-output', 2,
                       env_overrides={'DJ_PREFLIGHT_TIMEOUT_S': 'abc'}, want_substr='preflight failed: invalid timeout abc')
    refuses('plan03 preflight: invalid DJ_PREFLIGHT_TIMEOUT_S=0 refuses pre-output on r4 launch', ['r4', 'iv2:6'],
            'preflight failed: invalid timeout 0', d08_orphan=True,
            env_overrides={'DJ_PREFLIGHT_TIMEOUT_S': '0'})

    def _test_hanging_probe_preflight_only():
        root = WORK/('h%03d' % (len(results)+1))
        path = fake_harness(root, d08_orphan=True)
        pf_tmp = root/'pf_tmp'
        pf_tmp.mkdir(parents=True, exist_ok=True)
        pid_file = root/'hung-pf.pids'
        hanging_cp = (
            '#!/usr/bin/bash\n'
            '"/usr/bin/cat" /proc/$$/winpid >> "%s" 2>/dev/null || true\n'
            '"/usr/bin/sleep" 30 &\n'
            'spid=$!\n'
            '"/usr/bin/cat" /proc/$spid/winpid >> "%s" 2>/dev/null || true\n'
            'wait $spid\n'
        ) % (pid_file.as_posix(), pid_file.as_posix())
        bdir = make_filtered_bin(root, custom_cp=hanging_cp.encode('utf8'))
        env = dict(
            os.environ,
            PATH=bdir.as_posix(),
            DJ_GIT_USR_BIN=bdir.as_posix(),
            DJ_PREFLIGHT_TIMEOUT_S='1',
            DJ_PREFLIGHT_TMP=pf_tmp.as_posix(),
        )
        t0 = time.monotonic()
        run = subprocess.run([BASH, str(path), '--preflight-only'], capture_output=True, text=True, timeout=15, env=env)
        elapsed = time.monotonic() - t0
        out = (run.stdout+run.stderr).strip()
        wpids, alive, unknown = _check_hanging_probe_cleanup(pid_file)
        leftover_scratch = list(pf_tmp.glob('dj-preflight-*'))
        fine = (run.returncode == 2
                and 'preflight failed: timed out after 1s' in out
                and 'PREFLIGHT OK' not in out
                and elapsed < 10.0
                and len(wpids) >= 2
                and alive == []
                and unknown == []
                and leftover_scratch == [])
        record('plan03 R1: hanging probe in --preflight-only times out & kills children',
               0 if fine else 1, 0,
               'exit %d elapsed=%.2fs wpids=%s alive=%s unk=%s scratch=%d: %s'
               % (run.returncode, elapsed, wpids, alive, unknown, len(leftover_scratch), out.replace('\n', ' | ')[-90:]))
    _test_hanging_probe_preflight_only()

    def _test_hanging_probe_ordinary_launch():
        root = WORK/('h%03d' % (len(results)+1))
        path = fake_harness(root, d08_orphan=True)
        pf_tmp = root/'pf_tmp'
        pf_tmp.mkdir(parents=True, exist_ok=True)
        pid_file = root/'hung-launch.pids'
        hanging_cp = (
            '#!/usr/bin/bash\n'
            '"/usr/bin/cat" /proc/$$/winpid >> "%s" 2>/dev/null || true\n'
            '"/usr/bin/sleep" 30 &\n'
            'spid=$!\n'
            '"/usr/bin/cat" /proc/$spid/winpid >> "%s" 2>/dev/null || true\n'
            'wait $spid\n'
        ) % (pid_file.as_posix(), pid_file.as_posix())
        bdir = make_filtered_bin(root, custom_cp=hanging_cp.encode('utf8'))
        env = dict(
            os.environ,
            PATH=bdir.as_posix(),
            DJ_GIT_USR_BIN=bdir.as_posix(),
            DJ_PREFLIGHT_TIMEOUT_S='1',
            DJ_PREFLIGHT_TMP=pf_tmp.as_posix(),
        )
        t0 = time.monotonic()
        run = subprocess.run([BASH, str(path), 'r4', 'iv2:6'], capture_output=True, text=True, timeout=15, env=env)
        elapsed = time.monotonic() - t0
        out = (run.stdout+run.stderr).strip()
        wpids, alive, unknown = _check_hanging_probe_cleanup(pid_file)
        leftover_scratch = list(pf_tmp.glob('dj-preflight-*'))
        no_outputs = (not (root/'evidence'/'workers-dj'/'iv2-w6-r4.log').exists()
                      and not (root/'evidence'/'workers-dj'/'iv2-store-w6-r4').exists()
                      and not (root/'evidence'/'workers-dj-merged-r4').exists()
                      and not (root/'parity-called.marker').exists())
        fine = (run.returncode == 2
                and 'preflight failed: timed out after 1s' in out
                and 'start' not in out
                and 'STUB-RUN' not in out
                and elapsed < 10.0
                and len(wpids) >= 2
                and alive == []
                and unknown == []
                and leftover_scratch == []
                and no_outputs)
        record('plan03 R1: hanging probe in r4 launch times out pre-output & kills children',
               0 if fine else 1, 0,
               'exit %d elapsed=%.2fs wpids=%s alive=%s unk=%s scratch=%d: %s'
               % (run.returncode, elapsed, wpids, alive, unknown, len(leftover_scratch), out.replace('\n', ' | ')[-90:]))
    _test_hanging_probe_ordinary_launch()

    for util_name in ('timeout', 'date', 'seq', 'cp', 'sleep', 'mkdir', 'basename', 'sha256sum', 'cut', 'cmp', 'cat'):
        def _test_missing(u=util_name):
            root = WORK/('h%03d' % (len(results)+1))
            path = fake_harness(root, d08_orphan=True)
            bdir = make_filtered_bin(root, omit_util=u)
            env = dict(os.environ, PATH=bdir.as_posix(), DJ_GIT_USR_BIN=bdir.as_posix())
            run = subprocess.run([BASH, str(path), 'r4', 'iv2:6'], capture_output=True, text=True, timeout=60, env=env)
            out = (run.stdout+run.stderr).strip()
            no_outputs = (not (root/'evidence'/'workers-dj'/'iv2-w6-r4.log').exists()
                          and not (root/'evidence'/'workers-dj'/'iv2-store-w6-r4').exists()
                          and not (root/'evidence'/'workers-dj-merged-r4').exists()
                          and not (root/'parity-called.marker').exists())
            fine = (run.returncode == 2 and ('preflight failed: missing utility %s' % u) in out
                    and 'start' not in out and 'STUB-RUN' not in out and no_outputs)
            record('plan03 missing utility refuses pre-output: ' + u, 0 if fine else 1, 0,
                   'exit %d: %s' % (run.returncode, out.replace('\n', ' | ')[-140:]))
        _test_missing()

    def _test_missing_bash():
        root = WORK/('h%03d' % (len(results)+1))
        path = fake_harness(root, d08_orphan=True)
        bdir = make_filtered_bin(root, omit_util='bash')
        env = dict(os.environ, PATH=bdir.as_posix(), DJ_GIT_USR_BIN=bdir.as_posix())
        run = subprocess.run([BASH, str(path), 'r4', 'iv2:6'], capture_output=True, text=True, timeout=60, env=env)
        out = (run.stdout+run.stderr).strip()
        no_outputs = not (root/'evidence'/'workers-dj'/'iv2-w6-r4.log').exists() and not (root/'parity-called.marker').exists()
        fine = (run.returncode == 2 and 'preflight failed: missing utility bash' in out
                and 'start' not in out and 'STUB-RUN' not in out and no_outputs)
        record('plan03 missing utility refuses pre-output: bash', 0 if fine else 1, 0,
               'exit %d: %s' % (run.returncode, out.replace('\n', ' | ')[-140:]))
    _test_missing_bash()

    def _test_synthetic_copy_fail():
        root = WORK/('h%03d' % (len(results)+1))
        path = fake_harness(root, d08_orphan=True)
        bdir = make_filtered_bin(root, custom_cp=b'#!/usr/bin/bash\nexit 1\n')
        env = dict(os.environ, PATH=bdir.as_posix(), DJ_GIT_USR_BIN=bdir.as_posix())
        run = subprocess.run([BASH, str(path), 'r4', 'iv2:6'], capture_output=True, text=True, timeout=60, env=env)
        out = (run.stdout+run.stderr).strip()
        no_outputs = not (root/'evidence'/'workers-dj'/'iv2-w6-r4.log').exists() and not (root/'parity-called.marker').exists()
        fine = (run.returncode == 2 and 'preflight failed: synthetic cp -r' in out
                and 'start' not in out and 'STUB-RUN' not in out and no_outputs)
        record('plan03 preflight synthetic cp -r failure refuses pre-output', 0 if fine else 1, 0,
               'exit %d: %s' % (run.returncode, out.replace('\n', ' | ')[-140:]))
    _test_synthetic_copy_fail()

    def _test_synthetic_copy_corrupt():
        root = WORK/('h%03d' % (len(results)+1))
        path = fake_harness(root, d08_orphan=True)
        corrupt_cp = (
            b'#!/usr/bin/bash\n'
            b'"/usr/bin/cp" "$@" || exit 1\n'
            b'for last; do :; done\n'
            b'printf "corrupted\\n" > "$last/a.txt"\n'
            b'exit 0\n'
        )
        bdir = make_filtered_bin(root, custom_cp=corrupt_cp)
        env = dict(os.environ, PATH=bdir.as_posix(), DJ_GIT_USR_BIN=bdir.as_posix())
        run = subprocess.run([BASH, str(path), 'r4', 'iv2:6'], capture_output=True, text=True, timeout=60, env=env)
        out = (run.stdout+run.stderr).strip()
        no_outputs = not (root/'evidence'/'workers-dj'/'iv2-w6-r4.log').exists() and not (root/'parity-called.marker').exists()
        fine = (run.returncode == 2 and 'preflight failed: cmp a.txt' in out
                and 'start' not in out and 'STUB-RUN' not in out and no_outputs)
        record('plan03 preflight synthetic copy byte corruption refuses', 0 if fine else 1, 0,
               'exit %d: %s' % (run.returncode, out.replace('\n', ' | ')[-140:]))
    _test_synthetic_copy_corrupt()

    refuses('plan03 preflight refuses non-zero PYTHONHASHSEED on real Python', ['r4', 'iv2:6'],
            'preflight failed: python/hash_seed/psutil', d08_orphan=True,
            env_overrides={'DJ_PYTHONHASHSEED': '1'}, py_override=Path(sys.executable).as_posix(),
            mutate_root=lambda r: [shutil.copy2(REAL_SCRIPTS/f, r/'scripts'/f)
                                   for f in ('parallel_parity.py', 'summarise_dj.py', 'rc1_env.py')])

    refuses('plan03 preflight refuses missing Python interpreter', ['r4', 'iv2:6'],
            'preflight failed: missing python interpreter', d08_orphan=True,
            py_override=(WORK/'no-such-python.exe').as_posix())

    def _test_actual_copy_fails():
        root = WORK/('h%03d' % (len(results)+1))
        path = fake_harness(root, d08_orphan=True)
        selective_fail_cp = (
            b'#!/usr/bin/bash\n'
            b'case "$*" in *dj-preflight-*) exec "/usr/bin/cp" "$@";; esac\n'
            b'exit 1\n'
        )
        bdir = make_filtered_bin(root, custom_cp=selective_fail_cp)
        env = dict(os.environ, PATH=bdir.as_posix(), DJ_GIT_USR_BIN=bdir.as_posix())
        run = subprocess.run([BASH, str(path), 'r4', 'iv2:6'], capture_output=True, text=True, timeout=60, env=env)
        out = (run.stdout+run.stderr).strip()
        fine = (run.returncode == 1
                and 'start r4 iv2:6' in out
                and 'FAIL: input-store copy failed for iv2 w6 r4' in out
                and not (root/'parity-called.marker').exists()
                and not (root/'evidence'/'workers-dj'/'iv2-w6-r4.log').exists()
                and not (root/'evidence'/'workers-dj'/'iv2-w6-r4.json').exists()
                and not (root/'evidence'/'workers-dj-merged-r4').exists())
        record('plan03 actual input-store copy failure refuses before parity', 0 if fine else 1, 0,
               'exit %d: %s' % (run.returncode, out.replace('\n', ' | ')[-140:]))
    _test_actual_copy_fails()

    def _test_actual_copy_corrupts():
        root = WORK/('h%03d' % (len(results)+1))
        path = fake_harness(root, d08_orphan=True)
        selective_corrupt_cp = (
            b'#!/usr/bin/bash\n'
            b'case "$*" in *dj-preflight-*) exec "/usr/bin/cp" "$@";; esac\n'
            b'for last; do :; done\n'
            b'printf "{\\"corrupt\\":true}\\n" > "$last"\n'
            b'exit 0\n'
        )
        bdir = make_filtered_bin(root, custom_cp=selective_corrupt_cp)
        env = dict(os.environ, PATH=bdir.as_posix(), DJ_GIT_USR_BIN=bdir.as_posix())
        run = subprocess.run([BASH, str(path), 'r4', 'iv2:6'], capture_output=True, text=True, timeout=60, env=env)
        out = (run.stdout+run.stderr).strip()
        fine = (run.returncode == 1
                and 'FAIL: input-store copy failed for iv2 w6 r4' in out
                and not (root/'parity-called.marker').exists()
                and not (root/'evidence'/'workers-dj'/'iv2-w6-r4.log').exists()
                and not (root/'evidence'/'workers-dj'/'iv2-w6-r4.json').exists())
        record('plan03 actual input-store corrupted copy refuses before parity', 0 if fine else 1, 0,
               'exit %d: %s' % (run.returncode, out.replace('\n', ' | ')[-140:]))
    _test_actual_copy_corrupts()

    def _test_missing_source_store():
        code, out, root = harness_run(['r4', 'iv2:6'], absent=['iv2-store'], d08_orphan=True)
        fine = (code == 1
                and 'FAIL: input-store copy failed for iv2 w6 r4' in out
                and not (root/'parity-called.marker').exists()
                and not (root/'evidence'/'workers-dj'/'iv2-w6-r4.log').exists())
        record('plan03 missing source input-store refuses before parity', 0 if fine else 1, 0,
               'exit %d: %s' % (code, out.replace('\n', ' | ')[-140:]))
    _test_missing_source_store()

    refuses('plan03 D08: r3 iv2:6 refuses overwrite of preserved iv2-w6-r3.log', ['r3', 'iv2:6'],
            'exists:', d08_orphan=True)
    refuses('plan03 D08: r3 iv1:6 refuses while r3 orphan exists (r3 not reusable)', ['r3', 'iv1:6'],
            'no JSON (crashed or killed): iv2-w6-r3.log', d08_orphan=True)
    proceeds('plan03 D08: r4 iv2:6 proceeds when exact D08 orphan facts hold', ['r4', 'iv2:6'],
             d08_orphan=True)

    def _tamper_orphan_bytes(root):
        p = root/'evidence'/'workers-dj'/'iv2-w6-r3.log'
        p.write_bytes(b'x')
        os.utime(p, ns=(D08_MTIME_NS, D08_MTIME_NS))

    def _tamper_orphan_mtime(root):
        p = root/'evidence'/'workers-dj'/'iv2-w6-r3.log'
        os.utime(p, ns=(D08_MTIME_NS + 1_000_000_000, D08_MTIME_NS + 1_000_000_000))

    def _tamper_outer_log(root):
        p = root/'work'/'dj-rearm-r3-q21b.log'
        p.write_bytes(p.read_bytes() + b' ')

    def _add_second_orphan_same_mtime(root):
        p = root/'evidence'/'workers-dj'/'iv2-w4-r3.log'
        p.write_bytes(b'')
        os.utime(p, ns=(D08_MTIME_NS, D08_MTIME_NS))

    def _add_r4_orphan_same_mtime(root):
        p = root/'evidence'/'workers-dj'/'iv2-w6-r4.log'
        p.write_bytes(b'')
        os.utime(p, ns=(D08_MTIME_NS, D08_MTIME_NS))

    refuses('plan03 D08: non-empty iv2-w6-r3.log (with D08 mtime) refuses r4', ['r4', 'iv2:6'],
            'no JSON (crashed or killed): iv2-w6-r3.log', d08_orphan=True, mutate_root=_tamper_orphan_bytes)
    refuses('plan03 D08: altered mtime on 0-byte iv2-w6-r3.log refuses r4', ['r4', 'iv2:6'],
            'no JSON (crashed or killed): iv2-w6-r3.log', d08_orphan=True, mutate_root=_tamper_orphan_mtime)
    refuses('plan03 D08: iv2-store-w6-r3 present alongside D08 orphan refuses r4', ['r4', 'iv2:6'],
            'no JSON (crashed or killed): iv2-w6-r3.log', present=['iv2-store-w6-r3/'], d08_orphan=True)
    refuses('plan03 D08: workers-dj-merged-r3 present alongside D08 orphan refuses r4', ['r4', 'iv2:6'],
            'no JSON (crashed or killed): iv2-w6-r3.log', present=['../workers-dj-merged-r3/'], d08_orphan=True)
    refuses('plan03 D08: missing outer dj-rearm-r3-q21b.log refuses r4', ['r4', 'iv2:6'],
            'no JSON (crashed or killed): iv2-w6-r3.log', absent=['dj-rearm-r3-q21b.log'], d08_orphan=True)
    refuses('plan03 D08: modified outer dj-rearm-r3-q21b.log refuses r4', ['r4', 'iv2:6'],
            'no JSON (crashed or killed): iv2-w6-r3.log', d08_orphan=True, mutate_root=_tamper_outer_log)
    refuses('plan03 D08: second unruled orphan (iv2-w4-r3.log, same mtime) refuses r4', ['r4', 'iv2:6'],
            'no JSON (crashed or killed): iv2-w4-r3.log', d08_orphan=True, mutate_root=_add_second_orphan_same_mtime)
    refuses('plan03 D08: unruled r4 orphan alongside D08 r3 orphan refuses r5', ['r5', 'iv2:6'],
            'no JSON (crashed or killed): iv2-w6-r4.log', d08_orphan=True, mutate_root=_add_r4_orphan_same_mtime)

    merge('plan03 D08: r4 merge retains D08 orphan in excluded/ and sources.txt, not superseded/', 0, 'r4', ['iv2:6'],
          dict(ALL, **{'iv2-w6': marked('iv2-w6@first'), 'iv2-w6-r2': marked('iv2-w6@r2'), 'iv2-w6-r4': marked('iv2-w6@r4')}),
          then(lambda m, t: same(m, 'iv2-w6', marked('iv2-w6@r4')),
               lambda m, t: superseded_are(m, 'iv2-w6.json', 'iv2-w6-r2.json'),
               lambda m, t: (m/'excluded'/'iv2-w6-r3.log').is_file() and (m/'excluded'/'iv2-w6-r3.log').stat().st_size == 0
               or 'excluded/iv2-w6-r3.log missing or non-empty',
               lambda m, t: (m/'excluded'/'dj-rearm-r3-q21b.log').is_file()
               or 'excluded/dj-rearm-r3-q21b.log missing',
               lambda m, t: (f'excluded/iv2-w6-r3.log {D08_LOG_SHA} INVALID_LAUNCH_ENVIRONMENT_D08' in (m/'sources.txt').read_text()
                             and f'excluded/dj-rearm-r3-q21b.log {D08_Q21B_SHA} INVALID_LAUNCH_ENVIRONMENT_D08' in (m/'sources.txt').read_text())
               or 'sources.txt missing D08 INVALID_LAUNCH_ENVIRONMENT_D08 provenance lines'),
          d08_orphan=True)

    merge('plan03 D08: r4 merge with second unruled orphan (iv1-w6-r3.log) FAILs before merge', 1, 'r4', ['iv2:6'],
          dict(ALL, **{'iv2-w6-r4': marked('iv2-w6@r4')}), extra=['iv1-w6-r3.log'],
          check=lambda m, t: ('no JSON (crashed or killed): iv1-w6-r3.log' in t and not m.exists())
          or 'did not refuse second unruled orphan at merge',
          d08_orphan=True)

    merge('plan03 D08: r4 merge with tampered D08 orphan mtime FAILs before merge', 1, 'r4', ['iv2:6'],
          dict(ALL, **{'iv2-w6-r4': marked('iv2-w6@r4')}),
          check=lambda m, t: ('no JSON (crashed or killed): iv2-w6-r3.log' in t and not m.exists())
          or 'did not refuse tampered D08 orphan at merge',
          d08_orphan=True,
          mutate_merge=lambda out, g: os.utime(out/'iv2-w6-r3.log', ns=(D08_MTIME_NS + 1_000_000_000, D08_MTIME_NS + 1_000_000_000)))

mode_str = 'r5-delta' if ONLY_R5_DELTA else ('r4-delta' if ONLY_R4_DELTA else ('r3-delta' if ONLY_R3_DELTA else 'full'))
ok = all(r['ok'] for r in results.values())
(WORK/'proof.json').write_text(json.dumps(dict(summary=str(SUMMARY), harness=str(HARNESS), mode=mode_str,
                                               results=results, ok=ok),
                                          indent=1), encoding='utf8')
print('PROOF', 'PASS' if ok else 'FAIL', '%d/%d as expected' % (sum(r['ok'] for r in results.values()), len(results)))
sys.exit(0 if ok else 1)
