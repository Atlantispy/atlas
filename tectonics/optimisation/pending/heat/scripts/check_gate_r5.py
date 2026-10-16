"""Checks for ab_heat_r5's predicted start gate (Michael 14:05/14:08; review = delta review + mutants).

ab_heat_r5.run() runs in-process. psutil.virtual_memory is faked, sleep() becomes a counter, and
subprocess.Popen becomes a recorder that raises before any child starts, so no heat work runs. Cases:
  1. free 1 byte below the gate predicted from a measured history record: the arm is refused ('start gate')
     after the full 600 s wait (40 sleeps), with no child. Prediction, basis, gate and free are recorded.
  2. free exactly at the gate: the child is launched (Popen once, no sleeps).
  3. no history, no RUNQ_PRED_PEAK_GIB, no --pred-peak-gib: refused at once ('start gate: no peak
     prediction'), even with 1 TiB free.
  4. a None/invalid fallback (RUNQ_PRED_PEAK_GIB 'None', 'nan', '0', '-1', 'inf'; --pred-peak-gib 'None')
     refuses; it never defaults low.
  5. prediction rules (predict() directly):
     - the largest matching record wins;
     - records of another mode, layout or worker count, other inputs, FAIL, stopped or zero-peak records
       are ignored;
     - parent + 6 x worker is used when larger than the tree peak;
     - the env fallback comes before the CLI;
     - an earlier arm of this run counts.
  6. unreadable history refuses before OUTDIR exists.
  7. the in-run guards are r2's: 12 GiB tree working set, 1 GiB available floor.
  8. _worker_groups: venv launcher + interpreter pairs group under the launcher; a non-worker parent stays
     the arm's own; a PID-reuse cycle in stale tags terminates (r5's fix of r4's unbounded climb).
MUTANTS: planted copies must FAIL. The planted defects are:
  - the refusal check removed;
  - a missing prediction defaulting to 1.05 GiB;
  - the mode dropped from the route key;
  - the env fallback accepting None as 0.
Exit 0 only if the real file passes every case and every mutant is caught.
"""
import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
REAL = HS/'scripts'/'ab_heat_r5.py'
LW = str((HS/'lw').resolve())
LD = str((HS/'ld3').resolve())
GIB = 1 << 30
TMP = Path(tempfile.mkdtemp())


class Launched(Exception):
    pass


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake(module, free_bytes):
    calls = dict(sleep=0, popen=0)
    real = module.psutil
    module.psutil = types.SimpleNamespace(Process=real.Process, Error=real.Error, cpu_times=real.cpu_times,
                                          virtual_memory=lambda: types.SimpleNamespace(available=free_bytes))

    def sleep(_):
        calls['sleep'] += 1

    def popen(*_args, **_kwargs):
        calls['popen'] += 1
        raise Launched()
    module.sleep = sleep
    module.subprocess = types.SimpleNamespace(Popen=popen, STDOUT=-2)
    return calls


def rec(arm=0, mode='time', layout=LW, peak=1031, **kw):
    return dict(dict(arm=arm, mode=mode, label='x', layout=layout, status='PASS', exit_code=0, used=[6, 6],
                     tree_peak_mib=peak), **kw)


def history_file(tag, arms):
    p = TMP/tag/'hist'/'summary.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dict(arms=arms)), encoding='utf8')
    return str(p)


def summary(d):
    return json.loads((d/'summary.json').read_text(encoding='utf8'))['arms'][0]


def cases(path, tag):
    out = []
    os.environ.pop('RUNQ_PRED_PEAK_GIB', None)
    hist = history_file(tag, [rec(peak=1031)])
    gate = int((1031/1024*1.2+2)*GIB)

    m = load(path, 'g4_%s_1' % tag)
    calls = fake(m, gate-1)
    d = TMP/tag/'below'
    m.run(d, ['time:x:'+LW], [hist])
    a = summary(d)
    ok = (a.get('stopped') == 'start gate' and calls == dict(sleep=40, popen=0) and a.get('gate_waited_s') == 600
          and a.get('predicted_peak_gib') == round(1031/1024, 3) and str(a.get('prediction_basis')).startswith('measured:')
          and a.get('start_gate_gib') == round(gate/GIB, 2) and a.get('free_gib_at_start') == round((gate-1)/GIB, 2))
    out.append(('1 below predicted gate refused', ok, json.dumps(dict(a, **calls))))

    m = load(path, 'g4_%s_2' % tag)
    calls = fake(m, gate)
    try:
        m.run(TMP/tag/'at', ['time:x:'+LW], [hist])
        launched = False
    except Launched:
        launched = True
    out.append(('2 at gate launches', launched and calls == dict(sleep=0, popen=1), json.dumps(calls)))

    m = load(path, 'g4_%s_3' % tag)
    calls = fake(m, 1 << 40)
    d = TMP/tag/'nopred'
    m.run(d, ['time:x:'+LW], [history_file(tag+'-other', [rec(mode='proof')])])
    a = summary(d)
    out.append(('3 no prediction refused', a.get('stopped') == 'start gate: no peak prediction'
                and a.get('predicted_peak_gib') is None and calls == dict(sleep=0, popen=0), json.dumps(dict(a, **calls))))

    bad = []
    for env, cli in (('None', None), ('nan', None), ('0', None), ('-1', None), ('inf', None), (None, 'None'), ('', '-2')):
        if env is None:
            os.environ.pop('RUNQ_PRED_PEAK_GIB', None)
        else:
            os.environ['RUNQ_PRED_PEAK_GIB'] = env
        got = m.predict(dict(mode='time', layout=LW), [], cli)
        bad.append(got[0] is None)
    os.environ.pop('RUNQ_PRED_PEAK_GIB', None)
    out.append(('4 None/invalid fallback refuses', all(bad), repr(bad)))

    H = [('h', rec(arm=0, peak=1000)), ('h', rec(arm=1, peak=1100)), ('h', rec(arm=2, mode='proof', peak=9000)),
         ('h', rec(arm=3, layout=LD, peak=9001)), ('h', rec(arm=4, used=[8, 8], peak=9002)),
         ('h', rec(arm=5, status='FAIL', peak=9003)), ('h', rec(arm=6, stopped='guard', peak=9004)),
         ('h', rec(arm=7, peak=0)), ('h', rec(arm=8, input='other', peak=9005)), ('h', rec(arm=9, exit_code=1, peak=9006))]
    t = dict(mode='time', layout=LW)
    r1 = m.predict(t, H)
    r2 = m.predict(t, H+[('h', rec(arm=10, peak=900, parent_peak_mib=400, worker_peak_mib=120))])
    os.environ['RUNQ_PRED_PEAK_GIB'] = '2.5'
    r3 = m.predict(t, [], '1.0')
    os.environ.pop('RUNQ_PRED_PEAK_GIB')
    r4 = m.predict(t, [], '1.5')
    r5 = m.predict(t, [('this run', rec(arm=3, peak=1500))], '0.5')
    ok = (r1[0] == 1100/1024 and 'arm 1' in r1[1] and r2[0] == 1120/1024 and 'arm 10' in r2[1]
          and r3 == (2.5, 'fallback RUNQ_PRED_PEAK_GIB (no measured arm of this route)')
          and r4[0] == 1.5 and r5[0] == 1500/1024 and 'this run' in r5[1])
    out.append(('5 prediction rules', ok, repr((r1, r2, r3, r4, r5))))

    d = TMP/tag/'badhist'
    try:
        m.run(d, ['time:x:'+LW], [str(TMP/'no-such'/'summary.json')])
        refused = False
    except (OSError, ValueError, KeyError):
        refused = True
    out.append(('6 unreadable history refused before OUTDIR', refused and not d.exists(), repr((refused, d.exists()))))
    tags = {1: (False, 0), 10: (True, 1), 11: (True, 10), 20: (True, 1), 21: (True, 20), 30: (True, 31), 31: (True, 30)}
    groups = m._worker_groups([types.SimpleNamespace(pid=p) for p in (1, 10, 11, 20, 21, 30, 31)], tags)
    out.append(('8 worker groups + cycle bounded', {k: groups.get(k) for k in (1, 10, 11, 20, 21)} ==
                {1: None, 10: 10, 11: 10, 20: 20, 21: 20} and set(groups) >= {30, 31}, repr(groups)))
    out.append(('7 in-run guards unchanged', (m.RSS_GUARD, m.FREE_FLOOR) == (12*GIB, 1*GIB), repr((m.RSS_GUARD, m.FREE_FLOOR))))
    return out


def mutant(name, old, new):
    text = REAL.read_bytes().decode('utf8')
    assert text.count(old) == 1, name
    p = TMP/'mutants'/(name+'.py')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.replace(old, new).encode('utf8'))
    return p


failures = 0
for name, ok, detail in cases(REAL, 'real'):
    print('%s %s%s' % ('PASS' if ok else 'FAIL', name, '' if ok else ' | '+detail))
    failures += not ok
MUTANTS = (
    ('refusal-removed', "        if free < gate:\n", "        if free < 0:\n"),
    ('missing-defaults-low', "    return None, 'no measured arm of this route, no RUNQ_PRED_PEAK_GIB, no --pred-peak-gib'\n",
     "    return 1.05, 'default'\n"),
    ('mode-not-in-key', "                arm['mode'], arm['layout'], [WORKERS, WORKERS], INPUT):\n",
     "                a.get('mode'), arm['layout'], [WORKERS, WORKERS], INPUT):\n"),
    ('none-as-zero', "            gib = float(value)\n", "            gib = float(value) if value != 'None' else 1.0\n"),
)
for mname, old, new in MUTANTS:
    try:
        caught = [n for n, ok, _ in cases(mutant(mname, old, new), mname) if not ok]
    except Exception as e:      # a crash also counts as caught; it is named
        caught = ['crash: %s' % type(e).__name__]
    print('%s mutant %s caught by %s' % ('PASS' if caught else 'FAIL', mname, caught or 'nothing'))
    failures += not caught
print('RESULT', 'PASS' if not failures else 'FAIL %d' % failures)
sys.exit(1 if failures else 0)
