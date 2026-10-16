"""Checks for ab_heat_r6's predicted start gate: r5's cases (check_gate_r5.py) plus the refuter's four points.

ab_heat_r6.run() runs in-process. psutil.virtual_memory is faked, sleep() becomes a counter, and
subprocess.Popen becomes a recorder that raises before any child starts, so no heat work runs. Cases 1-8 are
r5's, with two changes: records carry fallback [None, None] (as real PASS arms do), and case 5's zero-peak
record moved to case 10 (r6 refuses it instead of skipping it). New cases:
  9. (a) a record whose call fell back to serial, or that has no fallback field, is not a measured peak of the
     worker route: ignored, in history and in this run.
  4b. (b) an invalid RUNQ_PRED_PEAK_GIB ('nan', 'abc', '0') is skipped and named in the basis and a valid
     --pred-peak-gib used; a valid env value still comes first; both invalid -> refused, both named.
  10. (c) a route-matching PASS record with a tree peak that is NaN, inf, a string, negative, 0, True or None,
     or a parent/worker peak that is NaN, negative, a string or only half present, refuses the arm (never
     skipped). The same values in another route's or a FAIL record do not. Parent/worker 0 is accepted.
  11. (c) malformed history (a list, arms not a list, a non-record arm, no arms) refuses before OUTDIR exists;
     a NaN peak written to a history file refuses the arm through run() with no child.
  12. (d) a bad later spec (bad mode, two fields, empty layout) refuses before OUTDIR exists and before any
     child; an option after the specs is refused by main() with its own message, before OUTDIR.
  13. on the real q03 history (evidence/h12-r1/summary.json), r6 predicts what r5 predicts for every route
     in it (lw, lc, ld proof; lw time).
MUTANTS: planted copies must FAIL. r5's four (refusal removed; missing defaults to 1.05 GiB; mode dropped from
the route key; None read as 1.0) plus r6's: fallback filter removed; invalid peak skipped; parent/worker check
removed; an invalid env value refusing again; history shape unchecked; specs parsed after OUTDIR; late
options let through.
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
REAL = HS/'scripts'/'ab_heat_r6.py'
R5 = HS/'scripts'/'ab_heat_r5.py'
Q03 = HS/'evidence'/'h12-r1'/'summary.json'
LW = str((HS/'lw').resolve())
LD = str((HS/'ld3').resolve())
GIB = 1 << 30
TMP = Path(tempfile.mkdtemp())
NAN, INF = float('nan'), float('inf')


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
                     fallback=[None, None], tree_peak_mib=peak), **kw)


def history_file(tag, arms, raw=None):
    p = TMP/tag/'hist'/'summary.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(raw if raw is not None else json.dumps(dict(arms=arms)), encoding='utf8')
    return str(p)


def summary(d):
    return json.loads((d/'summary.json').read_text(encoding='utf8'))['arms'][0]


def env(value):
    if value is None:
        os.environ.pop('RUNQ_PRED_PEAK_GIB', None)
    else:
        os.environ['RUNQ_PRED_PEAK_GIB'] = value


def cases(path, tag):
    out = []
    env(None)
    hist = history_file(tag, [rec(peak=1031)])
    gate = int((1031/1024*1.2+2)*GIB)
    t = dict(mode='time', layout=LW)

    m = load(path, 'g6_%s_1' % tag)
    calls = fake(m, gate-1)
    d = TMP/tag/'below'
    m.run(d, ['time:x:'+LW], [hist])
    a = summary(d)
    ok = (a.get('stopped') == 'start gate' and calls == dict(sleep=40, popen=0) and a.get('gate_waited_s') == 600
          and a.get('predicted_peak_gib') == round(1031/1024, 3) and str(a.get('prediction_basis')).startswith('measured:')
          and a.get('start_gate_gib') == round(gate/GIB, 2) and a.get('free_gib_at_start') == round((gate-1)/GIB, 2))
    out.append(('1 below predicted gate refused', ok, json.dumps(dict(a, **calls))))

    m = load(path, 'g6_%s_2' % tag)
    calls = fake(m, gate)
    try:
        m.run(TMP/tag/'at', ['time:x:'+LW], [hist])
        launched = False
    except Launched:
        launched = True
    out.append(('2 at gate launches', launched and calls == dict(sleep=0, popen=1), json.dumps(calls)))

    m = load(path, 'g6_%s_3' % tag)
    calls = fake(m, 1 << 40)
    d = TMP/tag/'nopred'
    m.run(d, ['time:x:'+LW], [history_file(tag+'-other', [rec(mode='proof')])])
    a = summary(d)
    out.append(('3 no prediction refused', a.get('stopped') == 'start gate: no peak prediction'
                and a.get('predicted_peak_gib') is None and calls == dict(sleep=0, popen=0), json.dumps(dict(a, **calls))))

    bad = []
    for e, cli in (('None', None), ('nan', None), ('0', None), ('-1', None), ('inf', None), (None, 'None'), ('', '-2'),
                   ('nan', 'abc')):
        env(e)
        bad.append(m.predict(t, [], cli))
    env(None)
    out.append(('4 None/invalid fallback refuses', all(g[0] is None for g in bad)
                and "RUNQ_PRED_PEAK_GIB='nan'" in bad[-1][1] and "--pred-peak-gib='abc'" in bad[-1][1], repr(bad)))

    got = []
    for e, cli in (('nan', '1.5'), ('abc', '2'), ('0', '0.75'), ('2.5', 'nan')):
        env(e)
        got.append(m.predict(t, [], cli))
    env(None)
    ok = ([g[0] for g in got] == [1.5, 2.0, 0.75, 2.5] and all('fallback --pred-peak-gib' in g[1] for g in got[:3])
          and "skipped RUNQ_PRED_PEAK_GIB='nan'" in got[0][1] and "skipped RUNQ_PRED_PEAK_GIB='abc'" in got[1][1]
          and got[3][1] == 'fallback RUNQ_PRED_PEAK_GIB (no measured arm of this route)')
    out.append(('4b invalid env skipped, CLI used, env first', ok, repr(got)))

    H = [('h', rec(arm=0, peak=1000)), ('h', rec(arm=1, peak=1100)), ('h', rec(arm=2, mode='proof', peak=9000)),
         ('h', rec(arm=3, layout=LD, peak=9001)), ('h', rec(arm=4, used=[8, 8], peak=9002)),
         ('h', rec(arm=5, status='FAIL', peak=9003)), ('h', rec(arm=6, stopped='guard', peak=9004)),
         ('h', rec(arm=8, input='other', peak=9005)), ('h', rec(arm=9, exit_code=1, peak=9006))]
    r1 = m.predict(t, H)
    r2 = m.predict(t, H+[('h', rec(arm=10, peak=900, parent_peak_mib=400, worker_peak_mib=120))])
    env('2.5')
    r3 = m.predict(t, [], '1.0')
    env(None)
    r4 = m.predict(t, [], '1.5')
    r5 = m.predict(t, [('this run', rec(arm=3, peak=1500))], '0.5')
    ok = (r1[0] == 1100/1024 and 'arm 1' in r1[1] and r2[0] == 1120/1024 and 'arm 10' in r2[1]
          and r3 == (2.5, 'fallback RUNQ_PRED_PEAK_GIB (no measured arm of this route)')
          and r4[0] == 1.5 and r5[0] == 1500/1024 and 'this run' in r5[1])
    out.append(('5 prediction rules', ok, repr((r1, r2, r3, r4, r5))))

    nofield = rec(arm=12, peak=9010)
    del nofield['fallback']
    serial = [('h', rec(arm=0, peak=1000)), ('h', rec(arm=11, peak=9009, fallback=[None, 'serial: one face'])),
              ('h', nofield), ('h', rec(arm=13, peak=9011, fallback=['serial', 'serial']))]
    s1 = m.predict(t, serial)
    s2 = m.predict(t, [('this run', rec(arm=0, peak=5000, fallback=['serial', None]))], '0.5')
    out.append(('9 serial-fallback records ignored', s1[0] == 1000/1024 and 'arm 0' in s1[1]
                and s2 == (0.5, 'fallback --pred-peak-gib (no measured arm of this route)'), repr((s1, s2))))

    refused, kept = [], []
    for peak in (NAN, INF, '2000', -5, 0, True, None):
        refused.append(m.predict(t, [('h', rec(arm=0, peak=1000)), ('h', rec(arm=1, peak=peak))], '1.0'))
        kept.append(m.predict(t, [('h', rec(arm=0, peak=1000)), ('h', rec(arm=1, mode='proof', peak=peak)),
                                  ('h', rec(arm=2, status='FAIL', peak=peak))], '1.0'))
    for pw in ((NAN, 10), (-1, 10), ('a', 1), (10, None), (None, 10), (10, INF)):
        refused.append(m.predict(t, [('h', rec(arm=0, peak=1000)),
                                     ('h', rec(arm=1, peak=1000, parent_peak_mib=pw[0], worker_peak_mib=pw[1]))], '1.0'))
    zero = m.predict(t, [('h', rec(arm=0, peak=1000, parent_peak_mib=0, worker_peak_mib=0))])
    ok = (all(r[0] is None and r[1].startswith('invalid measured') and 'h arm 1' in r[1] for r in refused)
          and all(k[0] == 1000/1024 for k in kept) and zero[0] == 1000/1024)
    out.append(('10 invalid measured peaks refuse (route-scoped)', ok, repr((refused, kept, zero))))

    m = load(path, 'g6_%s_11' % tag)
    calls = fake(m, 1 << 40)
    shapes = []
    for n, raw in enumerate(('[]', '{"arms": {}}', '{"arms": [1]}', '{"x": 1}', '{"arms": [[]]}')):
        d = TMP/tag/('shape%d' % n)
        try:
            m.run(d, ['time:x:'+LW], [history_file('%s-shape%d' % (tag, n), None, raw)])
            shapes.append('accepted')
        except (ValueError, KeyError, TypeError) as e:
            shapes.append(type(e).__name__ if not d.exists() else 'after OUTDIR')
    d = TMP/tag/'nanhist'
    m.run(d, ['time:x:'+LW], [history_file(tag+'-nan', [rec(peak=NAN)])])
    a = summary(d)
    ok = (shapes == ['ValueError']*5 and calls == dict(sleep=0, popen=0)
          and a.get('stopped') == 'start gate: no peak prediction'
          and str(a.get('prediction_basis')).startswith('invalid measured tree_peak_mib nan'))
    out.append(('11 malformed history refused before OUTDIR', ok, repr((shapes, calls, a))))

    m = load(path, 'g6_%s_12' % tag)
    calls = fake(m, 1 << 40)
    specs = []
    for n, bad_spec in enumerate(('bogus:x:'+LW, 'time:x', 'time:x:')):
        d = TMP/tag/('spec%d' % n)
        try:
            m.run(d, ['time:x:'+LW, bad_spec], [hist])
            specs.append('accepted')
        except SystemExit:
            specs.append('refused' if not d.exists() else 'after OUTDIR')
        except Launched:
            specs.append('launched')
    d = TMP/tag/'late'
    argv = sys.argv
    sys.argv = ['ab_heat', 'run', str(d), 'time:x:'+LW, '--pred-peak-gib', '2']
    try:
        m.main()
        late = 'accepted'
    except SystemExit as e:
        late = str(e) if not d.exists() else 'after OUTDIR'
    except Launched:
        late = 'launched'
    finally:
        sys.argv = argv
    ok = (specs == ['refused']*3 and late == 'options must come before the arm specs: --pred-peak-gib'
          and calls == dict(sleep=0, popen=0))
    out.append(('12 specs and late options refused before OUTDIR', ok, repr((specs, late, calls))))

    old = load(R5, 'g6_%s_r5' % tag)
    records = [(str(Q03), a) for a in json.loads(Q03.read_text(encoding='utf8'))['arms']]
    routes = [dict(mode='proof', layout=str((HS/n).resolve())) for n in ('lw', 'lc', 'ld')]+[t]
    same = [(m.predict(r, records, '1.25'), old.predict(r, records, '1.25')) for r in routes]
    ok = all(a == b for a, b in same) and same[0][0][0] == 1031/1024 and same[1][0][0] == 1034/1024
    out.append(('13 r5 == r6 on the real q03 history', ok, repr(same)))

    tags = {1: (False, 0), 10: (True, 1), 11: (True, 10), 20: (True, 1), 21: (True, 20), 30: (True, 31), 31: (True, 30)}
    groups = m._worker_groups([types.SimpleNamespace(pid=p) for p in (1, 10, 11, 20, 21, 30, 31)], tags)
    out.append(('8 worker groups + cycle bounded', {k: groups.get(k) for k in (1, 10, 11, 20, 21)} ==
                {1: None, 10: 10, 11: 10, 20: 20, 21: 20} and set(groups) >= {30, 31}, repr(groups)))
    out.append(('7 in-run guards unchanged', (m.RSS_GUARD, m.FREE_FLOOR) == (12*GIB, 1*GIB), repr((m.RSS_GUARD, m.FREE_FLOOR))))

    m = load(path, 'g6_%s_6' % tag)
    d = TMP/tag/'badhist'
    try:
        m.run(d, ['time:x:'+LW], [str(TMP/'no-such'/'summary.json')])
        refused6 = False
    except (OSError, ValueError, KeyError):
        refused6 = True
    out.append(('6 unreadable history refused before OUTDIR', refused6 and not d.exists(), repr((refused6, d.exists()))))
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
    ('fallback-filter-removed', "        if a.get('fallback') != [None, None]:\n", "        if False:\n"),
    ('invalid-peak-skipped', "        if mib is None:     # r6 (c): never skipped, it might have been the largest\n",
     "        if mib is None:     # r6 (c): never skipped, it might have been the largest\n            continue\n"),
    ('parent-worker-unchecked', "            if parent is None or worker is None:\n",
     "            parent, worker = parent or 0, worker or 0\n            if False:\n"),
    ('invalid-env-refuses', "            skipped.append('%s=%r is not a positive finite peak' % (name, value))\n            continue\n",
     "            return None, '%s=%r is not a positive finite peak' % (name, value)\n"),
    ('history-shape-unchecked',
     "    if type(data) is not dict or type(data.get('arms')) is not list or any(type(a) is not dict for a in data['arms']):\n",
     "    if False:\n"),
    ('specs-after-outdir',
     "    parsed = _specs(specs)\n    outdir = Path(outdir)\n    outdir.mkdir(parents=True, exist_ok=False)\n",
     "    outdir = Path(outdir)\n    outdir.mkdir(parents=True, exist_ok=False)\n    parsed = _specs(specs)\n"),
    ('late-options-through', "        if late:\n", "        if False:\n"),
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
