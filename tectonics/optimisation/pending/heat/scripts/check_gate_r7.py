"""Checks for ab_heat_r7's predicted start gate: r6's cases (check_gate_r6.py), changed where r7 changes them,
plus r6's refuter (one medium point, four minor).

ab_heat_r7.run() runs in-process. psutil.virtual_memory is faked, sleep() becomes a counter, and
subprocess.Popen becomes a recorder that raises before any child starts, so no heat work runs. Cases 1, 2, 4,
4b, 5, 6, 7, 8 are r6's. Changed or new:
  3. no basis for the first arm of a route: refused by the pre-flight, before OUTDIR exists (r6 wrote a stopped
     summary; r7 never creates OUTDIR for a run whose first arm cannot start).
  9. (a') serial-fallback records (fallback != [None, None], or no fallback field), in history or in this run:
     they raise a prediction above a clean record or above RUNQ_PRED_PEAK_GIB / --pred-peak-gib, never lower
     one, and never are its only basis. The refuter's own example (1031 clean, 9000 [None, 'worker died'])
     predicts what r5 predicts.
  10. r6's invalid peaks plus bool parent/worker, an int too large for a float (tree or parent) and a
     parent + 6 x worker sum that overflows: all refuse; a record without 'arm' no longer raises KeyError.
  11. malformed history refused before OUTDIR (r6); a NaN peak in a history file now refuses in the pre-flight.
  12. r6's bad specs plus: a layout without control.json; a second route with no basis; a second route with an
     invalid record. All refused before OUTDIR and before any child; two valid routes launch arm 0.
  13. r7 == r5 on the real q03 history (evidence/h12-r1/summary.json), read through r7's _history.
  14. _gate: 1e308 -> None, 1.0 -> int(3.2 GiB); env '1e308' and a 1e308 MiB measured peak refuse in the
     pre-flight; with the pre-flight disabled the run loop itself stops 'start gate: prediction not finite'.
  15. seeded differential fuzz (random.Random(20261016), 20,000 histories of valid and r5-skipped peaks, all
     records carrying 'arm'): r7 equals an independent oracle of the r7 rule, r7 >= r5 wherever both predict,
     and r7 predicts where r5 did not only through r6 (b) (invalid env skipped, valid CLI used).
MUTANTS: planted copies must FAIL: r5's four; r6's invalid-peak-skipped, parent-worker-unchecked,
invalid-env-refuses, history-shape-unchecked, specs-after-outdir, late-options-through; and r7's
tainted-counted-as-clean, tainted-ignored (r6's behaviour), tainted-not-above-fallback, tainted-alone-starts,
sum-finite-unchecked, overflow-unguarded, gate-not-finite-unchecked, loop-gate-unchecked, preflight-removed,
preflight-after-outdir, preflight-first-route-only, layout-unchecked.
Exit 0 only if the real file passes every case and every mutant is caught.
"""
import importlib.util
import json
import os
import random
import sys
import tempfile
import types
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
REAL = HS/'scripts'/'ab_heat_r7.py'
R5 = HS/'scripts'/'ab_heat_r5.py'
Q03 = HS/'evidence'/'h12-r1'/'summary.json'
LW = str((HS/'lw').resolve())
LD = str((HS/'ld3').resolve())
GIB = 1 << 30
TMP = Path(tempfile.mkdtemp())
NAN, INF = float('nan'), float('inf')
FUZZ_N, FUZZ_SEED = 20000, 20261016


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


def attempt(m, d, specs, hists, cli=None):
    """'refused: <message>' (SystemExit, OUTDIR absent), 'after OUTDIR', 'launched' or 'ran'."""
    try:
        m.run(d, specs, hists, cli)
        return 'ran'
    except SystemExit as e:
        return 'refused: %s' % e if not Path(d).exists() else 'after OUTDIR'
    except Launched:
        return 'launched'


def oracle(m, t, recs, e, cli):
    """The r7 rule written out independently: (GiB or None)."""
    peaks = []
    for _, a in recs:
        if (a.get('mode'), a.get('layout'), a.get('used'), a.get('input', m.INPUT)) != (
                t['mode'], t['layout'], [6, 6], m.INPUT):
            continue
        if a.get('status') != 'PASS' or a.get('exit_code') != 0 or a.get('stopped'):
            continue
        tree, parent, worker = a.get('tree_peak_mib'), a.get('parent_peak_mib'), a.get('worker_peak_mib')
        if type(tree) not in (int, float) or not tree > 0:
            return None
        if parent is not None or worker is not None:
            if type(parent) not in (int, float) or type(worker) not in (int, float) or parent < 0 or worker < 0:
                return None
            tree = max(tree, parent+6*worker)
        peaks.append((a.get('fallback') == [None, None], tree))
    clean = [p for c, p in peaks if c]
    tainted = [p for c, p in peaks if not c]
    if clean:
        return max(clean+tainted)/1024
    for value in (e, cli):
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if v == v and 0 < v < INF:
            return max([v]+[p/1024 for p in tainted])
    return None


def fuzz(m, old):
    rng = random.Random(FUZZ_SEED)
    t = dict(mode='time', layout=LW)
    counts = dict(equal=0, raised=0, r7_refuses=0, both_refuse=0, new_b=0)
    bad = []
    for i in range(FUZZ_N):
        recs = []
        for k in range(rng.randint(0, 6)):
            a = dict(arm=k, mode=rng.choice(['time']*3+['proof']), label='x', layout=rng.choice([LW]*3+[LD]),
                     status=rng.choice(['PASS']*5+['FAIL']), exit_code=rng.choice([0]*5+[1]),
                     used=rng.choice([[6, 6]]*5+[[8, 8]]))
            if rng.random() < 0.1:
                a['stopped'] = 'guard'
            if rng.random() < 0.1:
                a['input'] = 'other'
            f = rng.random()
            if f < 0.55:
                a['fallback'] = [None, None]
            elif f < 0.75:
                a['fallback'] = [None, 'worker died']
            elif f < 0.9:
                a['fallback'] = ['serial', 'serial']
            p = rng.random()
            a['tree_peak_mib'] = (rng.randint(1, 12000) if p < 0.6 else rng.uniform(0.5, 12000) if p < 0.95
                                  else rng.choice([0, 0.0, None]))
            q = rng.random()
            if q < 0.3:
                a['parent_peak_mib'], a['worker_peak_mib'] = rng.randint(0, 3000), rng.randint(0, 1500)
            elif q < 0.33:
                a['parent_peak_mib'] = rng.randint(0, 3000)
            recs.append((rng.choice(['h', 'this run']), a))
        e = rng.choice([None, None, '', '1.5', '0.25', '20', 'nan', 'abc', '0', '-1'])
        cli = rng.choice([None, None, '1.0', '0.1', '30', 'nan'])
        env(e)
        v7, b7 = m.predict(t, recs, cli)
        v5, b5 = old.predict(t, recs, cli)
        want = oracle(m, t, recs, e, cli)
        if v7 != want:
            bad.append(('oracle', i, v7, want, b7))
        elif v5 is not None and v7 is not None:
            if v7 < v5:
                bad.append(('below r5', i, v7, v5, b7))
            counts['equal' if v7 == v5 else 'raised'] += 1
        elif v5 is not None:
            counts['r7_refuses'] += 1
        elif v7 is None:
            counts['both_refuse'] += 1
        elif b5.startswith('RUNQ_PRED_PEAK_GIB=') and 'skipped RUNQ_PRED_PEAK_GIB' in b7:
            counts['new_b'] += 1
        else:
            bad.append(('new start not (b)', i, v7, b5, b7))
        if len(bad) >= 5:
            break
    env(None)
    return counts, bad


def cases(path, tag):
    out = []
    env(None)
    hist = history_file(tag, [rec(peak=1031)])
    gate = int((1031/1024*1.2+2)*GIB)
    t = dict(mode='time', layout=LW)

    m = load(path, 'g7_%s_1' % tag)
    calls = fake(m, gate-1)
    d = TMP/tag/'below'
    m.run(d, ['time:x:'+LW], [hist])
    a = summary(d)
    ok = (a.get('stopped') == 'start gate' and calls == dict(sleep=40, popen=0) and a.get('gate_waited_s') == 600
          and a.get('predicted_peak_gib') == round(1031/1024, 3) and str(a.get('prediction_basis')).startswith('measured:')
          and a.get('start_gate_gib') == round(gate/GIB, 2) and a.get('free_gib_at_start') == round((gate-1)/GIB, 2))
    out.append(('1 below predicted gate refused', ok, json.dumps(dict(a, **calls))))

    m = load(path, 'g7_%s_2' % tag)
    calls = fake(m, gate)
    try:
        m.run(TMP/tag/'at', ['time:x:'+LW], [hist])
        launched = False
    except Launched:
        launched = True
    out.append(('2 at gate launches', launched and calls == dict(sleep=0, popen=1), json.dumps(calls)))

    m = load(path, 'g7_%s_3' % tag)
    calls = fake(m, 1 << 40)
    got = attempt(m, TMP/tag/'nopred', ['time:x:'+LW], [history_file(tag+'-other', [rec(mode='proof')])])
    out.append(('3 no prediction refused before OUTDIR', got.startswith('refused: arm 0 time:x:')
                and 'refused before any arm runs' in got and 'no measured arm of this route' in got
                and calls == dict(sleep=0, popen=0), repr((got, calls))))

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

    old = load(R5, 'g7_%s_r5' % tag)
    clean = ('h', rec(arm=0, peak=1000))
    died = ('h', rec(arm=11, peak=9000, fallback=[None, 'worker died']))
    small = ('h', rec(arm=11, peak=500, fallback=[None, 'worker died']))
    nofield = rec(arm=12, peak=9010)
    del nofield['fallback']
    refuter = [('h', rec(arm=0, peak=1031)), died]
    s = dict(
        above_clean=m.predict(t, [clean, died]), above_clean_rev=m.predict(t, [died, clean]),
        below_clean=m.predict(t, [clean, small]), above_cli=m.predict(t, [died], '1.0'),
        below_cli=m.predict(t, [small], '1.0'), alone=m.predict(t, [died]), nofield=m.predict(t, [clean, ('h', nofield)]),
        nofield_alone=m.predict(t, [('h', nofield)]),
        this_run=m.predict(t, [('this run', rec(arm=0, peak=5000, fallback=['serial', None]))], '0.5'),
        refuter=(m.predict(t, refuter), old.predict(t, refuter)))
    env('nan')
    s['env_skipped_above'], s['env_skipped_below'] = m.predict(t, [died], '1.0'), m.predict(t, [small], '1.0')
    env('2.0')
    s['env_below_tainted'] = m.predict(t, [died], '30')
    env(None)
    ok = (s['above_clean'][0] == s['above_clean_rev'][0] == 9000/1024 and 'serial-fallback' in s['above_clean'][1]
          and 'h arm 11' in s['above_clean'][1] and 'above clean h arm 0' in s['above_clean'][1]
          and s['below_clean'] == (1000/1024, 'measured: h arm 0, 1000 MiB')
          and s['above_cli'][0] == 9000/1024 and 'above fallback --pred-peak-gib=1.0' in s['above_cli'][1]
          and s['below_cli'] == (1.0, 'fallback --pred-peak-gib (no measured arm of this route); above serial-fallback '
                                      'h arm 11, 500 MiB')
          and s['alone'][0] is None and s['alone'][1].startswith('only serial-fallback records')
          and s['nofield'][0] == 9010/1024 and s['nofield_alone'][0] is None
          and s['this_run'][0] == 5000/1024 and 'this run' in s['this_run'][1]
          and s['refuter'][0] == s['refuter'][1] and s['refuter'][0][0] == 9000/1024
          and s['env_skipped_above'][0] == 9000/1024 and "skipped RUNQ_PRED_PEAK_GIB='nan'" in s['env_skipped_above'][1]
          and s['env_skipped_below'][0] == 1.0 and "skipped RUNQ_PRED_PEAK_GIB='nan'" in s['env_skipped_below'][1]
          and s['env_below_tainted'][0] == 9000/1024 and 'RUNQ_PRED_PEAK_GIB=2.0' in s['env_below_tainted'][1])
    out.append(('9 serial-fallback records only raise, never the sole basis', ok, repr(s)))

    refused, kept, finite = [], [], []
    for peak in (NAN, INF, '2000', -5, 0, True, None, 10**400):
        refused.append(m.predict(t, [('h', rec(arm=0, peak=1000)), ('h', rec(arm=1, peak=peak))], '1.0'))
        kept.append(m.predict(t, [('h', rec(arm=0, peak=1000)), ('h', rec(arm=1, mode='proof', peak=peak)),
                                  ('h', rec(arm=2, status='FAIL', peak=peak))], '1.0'))
    for pw in ((NAN, 10), (-1, 10), ('a', 1), (10, None), (None, 10), (10, INF), (True, 10), (10, False), (10**400, 1)):
        refused.append(m.predict(t, [('h', rec(arm=0, peak=1000)),
                                     ('h', rec(arm=1, peak=1000, parent_peak_mib=pw[0], worker_peak_mib=pw[1]))], '1.0'))
    finite.append(m.predict(t, [('h', rec(arm=0, peak=1000)),
                                ('h', rec(arm=1, peak=1000, parent_peak_mib=1e308, worker_peak_mib=1e308))], '1.0'))
    finite.append(m.predict(t, [('h', rec(arm=1, peak=1000, parent_peak_mib=1e308, worker_peak_mib=1e308,
                                          fallback=[None, 'x']))], '1.0'))
    zero = m.predict(t, [('h', rec(arm=0, peak=1000, parent_peak_mib=0, worker_peak_mib=0))])
    noarm = rec(peak=1031)
    del noarm['arm']
    try:
        noarm_got = m.predict(t, [('h', noarm)])
    except KeyError as e:
        noarm_got = ('KeyError', e)
    ok = (all(r[0] is None and r[1].startswith('invalid measured') and 'h arm 1' in r[1] for r in refused)
          and all(k[0] == 1000/1024 for k in kept) and zero[0] == 1000/1024
          and all(f == (None, 'measured peak of h arm 1 is not finite') for f in finite)
          and noarm_got == (1031/1024, 'measured: h arm None, 1031 MiB'))
    out.append(('10 invalid measured peaks refuse (route-scoped); no KeyError', ok,
                repr((refused, kept, finite, zero, noarm_got))))

    m = load(path, 'g7_%s_11' % tag)
    calls = fake(m, 1 << 40)
    shapes = []
    for n, raw in enumerate(('[]', '{"arms": {}}', '{"arms": [1]}', '{"x": 1}', '{"arms": [[]]}')):
        d = TMP/tag/('shape%d' % n)
        try:
            m.run(d, ['time:x:'+LW], [history_file('%s-shape%d' % (tag, n), None, raw)])
            shapes.append('accepted')
        except (ValueError, KeyError, TypeError) as e:
            shapes.append(type(e).__name__ if not d.exists() else 'after OUTDIR')
    nan = attempt(m, TMP/tag/'nanhist', ['time:x:'+LW], [history_file(tag+'-nan', [rec(peak=NAN)])])
    ok = (shapes == ['ValueError']*5 and calls == dict(sleep=0, popen=0)
          and nan.startswith('refused: ') and 'invalid measured tree_peak_mib nan' in nan)
    out.append(('11 malformed history refused before OUTDIR', ok, repr((shapes, calls, nan))))

    m = load(path, 'g7_%s_12' % tag)
    calls = fake(m, 1 << 40)
    specs = []
    for n, (bad_spec, cli) in enumerate((('bogus:x:'+LW, None), ('time:x', None), ('time:x:', None),
                                         ('time:x:'+str(TMP/'no-layout'), '1.0'))):
        specs.append(attempt(m, TMP/tag/('spec%d' % n), ['time:x:'+LW, bad_spec], [hist], cli))
    hist_b = history_file(tag+'-b', [rec(peak=1031), rec(arm=1, mode='proof', layout=LD, peak=NAN)])
    route_b = [attempt(m, TMP/tag/'route-b', ['time:x:'+LW, 'proof:y:'+LD], [hist]),
               attempt(m, TMP/tag/'route-b-nan', ['time:x:'+LW, 'proof:y:'+LD], [hist_b], '1.0')]
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
    refusals = dict(calls)
    both = attempt(m, TMP/tag/'route-ab', ['time:x:'+LW, 'proof:y:'+LD], [hist], '1.0')
    ok = (all(s.startswith('refused: arm spec 1 ') for s in specs) and 'has no control.json' in specs[3]
          and route_b[0].startswith('refused: arm 1 proof:y:') and 'no measured arm of this route' in route_b[0]
          and route_b[1].startswith('refused: arm 1 proof:y:') and 'invalid measured tree_peak_mib nan' in route_b[1]
          and late == 'options must come before the arm specs: --pred-peak-gib'
          and refusals == dict(sleep=0, popen=0) and both == 'launched' and calls == dict(sleep=0, popen=1))
    out.append(('12 specs, layouts, every route and late options refused before OUTDIR', ok,
                repr((specs, route_b, late, refusals, both, calls))))

    records = m._history(str(Q03))
    routes = [dict(mode='proof', layout=str((HS/n).resolve())) for n in ('lw', 'lc', 'ld')]+[t]
    same = [(m.predict(r, records, '1.25'), old.predict(r, records, '1.25')) for r in routes]
    ok = all(a == b for a, b in same) and same[0][0][0] == 1031/1024 and same[1][0][0] == 1034/1024
    out.append(('13 r5 == r7 on the real q03 history', ok, repr(same)))

    m = load(path, 'g7_%s_14' % tag)
    calls = fake(m, 1 << 40)
    env('1e308')
    big_env = attempt(m, TMP/tag/'big-env', ['time:x:'+LW], [])
    env(None)
    big_rec = attempt(m, TMP/tag/'big-rec', ['time:x:'+LW], [history_file(tag+'-big', [rec(peak=1e308)])])
    m._preflight = lambda *_args: None
    env('1e308')
    d = TMP/tag/'big-loop'
    loop = attempt(m, d, ['time:x:'+LW], [])
    env(None)
    stopped = summary(d).get('stopped') if loop == 'ran' else None
    ok = (m._gate(1e308) is None and m._gate(1.0) == int(3.2*GIB) and m._gate(INF) is None
          and big_env.startswith('refused: ') and 'no finite start-gate prediction' in big_env
          and big_rec.startswith('refused: ') and 'no finite start-gate prediction' in big_rec
          and stopped == 'start gate: prediction not finite' and calls == dict(sleep=0, popen=0))
    out.append(('14 non-finite gates refused (pre-flight and loop)', ok, repr((big_env, big_rec, loop, stopped, calls))))

    counts, bad = fuzz(m, old)
    ok = not bad and counts['equal'] > 1000 and counts['raised'] > 100 and counts['new_b'] > 100
    out.append(('15 fuzz %d vs r5 + oracle' % FUZZ_N, ok, repr((counts, bad))))
    if tag == 'real':
        print('fuzz counts', json.dumps(counts))

    tags = {1: (False, 0), 10: (True, 1), 11: (True, 10), 20: (True, 1), 21: (True, 20), 30: (True, 31), 31: (True, 30)}
    groups = m._worker_groups([types.SimpleNamespace(pid=p) for p in (1, 10, 11, 20, 21, 30, 31)], tags)
    out.append(('8 worker groups + cycle bounded', {k: groups.get(k) for k in (1, 10, 11, 20, 21)} ==
                {1: None, 10: 10, 11: 10, 20: 20, 21: 20} and set(groups) >= {30, 31}, repr(groups)))
    out.append(('7 in-run guards unchanged', (m.RSS_GUARD, m.FREE_FLOOR) == (12*GIB, 1*GIB), repr((m.RSS_GUARD, m.FREE_FLOOR))))

    m = load(path, 'g7_%s_6' % tag)
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
     "    parsed = _specs(specs)\n    _preflight(parsed, history, pred_cli)\n    outdir = Path(outdir)\n"
     "    outdir.mkdir(parents=True, exist_ok=False)\n",
     "    outdir = Path(outdir)\n    outdir.mkdir(parents=True, exist_ok=False)\n    parsed = _specs(specs)\n"
     "    _preflight(parsed, history, pred_cli)\n"),
    ('late-options-through', "        if late:\n", "        if False:\n"),
    ('tainted-counted-as-clean', "        if a.get('fallback') == [None, None]:\n", "        if True:\n"),
    ('tainted-ignored', "        elif tainted is None or mib > tainted[0]:\n", "        elif False:\n"),
    ('tainted-not-above-fallback', "        if tainted and tainted[0]/1024 > gib:\n", "        if False:\n"),
    ('tainted-alone-starts', "    if tainted:\n        return None, (", "    if tainted:\n        return tainted[0]/1024, ("),
    ('sum-finite-unchecked', "        if not math.isfinite(mib):\n", "        if False:\n"),
    ('overflow-unguarded', "    except OverflowError:\n        return None\n", "    except ZeroDivisionError:\n        return None\n"),
    ('gate-not-finite-unchecked', "    return int(gate) if math.isfinite(gate) else None\n", "    return int(gate)\n"),
    ('loop-gate-unchecked', "        if gate is None:\n            arm['stopped']", "        if False:\n            arm['stopped']"),
    ('preflight-removed', "    _preflight(parsed, history, pred_cli)\n", ""),
    ('preflight-after-outdir',
     "    _preflight(parsed, history, pred_cli)\n    outdir = Path(outdir)\n    outdir.mkdir(parents=True, exist_ok=False)\n",
     "    outdir = Path(outdir)\n    outdir.mkdir(parents=True, exist_ok=False)\n    _preflight(parsed, history, pred_cli)\n"),
    ('preflight-first-route-only', "    for arm in parsed:\n        if any(", "    for arm in parsed[:1]:\n        if any("),
    ('layout-unchecked',
     "        if not (layout/'control.json').is_file():     # r7: the child reads it; a typo must not surface late\n",
     "        if False:\n"),
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
