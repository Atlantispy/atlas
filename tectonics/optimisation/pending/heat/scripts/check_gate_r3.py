"""Checks for ab_heat_r3's per-arm start gate (Michael 14:05 "Memory start gates by need"; review = delta + mutant).

Runs ab_heat_r3.run() in-process with psutil.virtual_memory faked, sleep() a counter and subprocess.Popen a
recorder that raises before any child starts, so no heat work runs. Cases:
  1. free 1 byte below a 3.3 GiB gate: arm refused ('start gate') after the full 600 s wait (40 sleeps),
     no child started, gate value/source/free recorded, summary.json written.
  2. free exactly at the gate: the child is launched (Popen called once).
  3. gate source precedence: --start-gate-gib > RUNQ_MEM_NEED_GIB > measured W4 peak (1.05 x 1.2 + 2 = 3.26).
  4. bad gates (1.5, nan, inf) refused before OUTDIR is created.
  5. the in-run guards are r2's: 12 GiB tree working set, 1 GiB available floor.
  6. MUTANTS: the same cases on planted copies must FAIL (refusal check removed; CLI gate ignored).
Exit 0 only if the real file passes every case and every mutant is caught.
"""
import importlib.util
import json
import math
import os
import sys
import tempfile
import types
from pathlib import Path

HS = Path(__file__).resolve().parents[1]
REAL = HS/'scripts'/'ab_heat_r3.py'
LAYOUT = str(HS/'lw')
GIB = 1 << 30
TMP = Path(tempfile.mkdtemp())


class Launched(Exception):
    pass


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake(module, free_bytes):
    calls = dict(sleep=0, popen=0)
    module.psutil = types.SimpleNamespace(**{k: getattr(module.psutil, k) for k in ('Process', 'Error', 'cpu_times')})
    module.psutil.virtual_memory = lambda: types.SimpleNamespace(available=free_bytes)

    def sleep(_):
        calls['sleep'] += 1

    def popen(*a, **k):
        calls['popen'] += 1
        raise Launched()
    module.sleep = sleep
    module.subprocess = types.SimpleNamespace(Popen=popen, STDOUT=-2)
    return calls


def cases(path, tag):
    """Returns a list of (name, ok, detail)."""
    out = []
    os.environ.pop('RUNQ_MEM_NEED_GIB', None)
    m = load(path, 'gate_' + tag + '_1')
    calls = fake(m, int(3.3*GIB) - 1)
    d1 = TMP/tag/'below'
    m.run(d1, ['time:x:' + LAYOUT], 3.3)
    arm = json.loads((d1/'summary.json').read_text(encoding='utf8'))['arms'][0]
    ok = (arm.get('stopped') == 'start gate' and calls['popen'] == 0 and calls['sleep'] == 40
          and arm.get('start_gate_gib') == 3.3 and arm.get('start_gate_source') == '--start-gate-gib'
          and arm.get('free_gib_at_start') == round((int(3.3*GIB)-1)/GIB, 2) and arm.get('gate_waited_s') == 600)
    out.append(('below gate refused', ok, json.dumps(dict(arm, **calls))))

    m = load(path, 'gate_' + tag + '_2')
    calls = fake(m, int(3.3*GIB))
    try:
        m.run(TMP/tag/'at', ['time:x:' + LAYOUT], 3.3)
        launched = False
    except Launched:
        launched = True
    out.append(('at gate launches', launched and calls['popen'] == 1 and calls['sleep'] == 0, json.dumps(calls)))

    m = load(path, 'gate_' + tag + '_3')
    got = []
    os.environ['RUNQ_MEM_NEED_GIB'] = '4.4'
    got.append(m.start_gate(5.0)[1:])
    got.append(m.start_gate()[1:])
    os.environ.pop('RUNQ_MEM_NEED_GIB')
    got.append(m.start_gate()[1:])
    want = [(5.0, '--start-gate-gib'), (4.4, 'RUNQ_MEM_NEED_GIB'), (3.26, 'measured W4 peak 1.05 GiB (q03)')]
    out.append(('gate source precedence', got == want and m.start_gate()[0] == int(3.26*GIB), repr(got)))

    refused = []
    for bad in (1.5, math.nan, math.inf):
        d = TMP/tag/('bad-%s' % bad)
        try:
            m.run(d, ['time:x:' + LAYOUT], bad)
            refused.append(False)
        except SystemExit:
            refused.append(not d.exists())
    out.append(('bad gates refused before OUTDIR', all(refused), repr(refused)))
    out.append(('in-run guards unchanged', (m.RSS_GUARD, m.FREE_FLOOR) == (12*GIB, 1*GIB), repr((m.RSS_GUARD, m.FREE_FLOOR))))
    return out


def mutant(name, old, new):
    text = REAL.read_bytes().decode('utf8')
    assert text.count(old) == 1, name
    p = TMP/'mutants'/(name + '.py')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.replace(old, new).encode('utf8'))
    return p


failures = 0
for name, ok, detail in cases(REAL, 'real'):
    print('%s %s%s' % ('PASS' if ok else 'FAIL', name, '' if ok else ' | ' + detail))
    failures += not ok
for mname, old, new in (('refusal-removed', "        if free < gate:\n", "        if free < 0:\n"),
                        ('cli-ignored', "    if cli_gib is not None:\n", "    if False:\n")):
    try:
        res = cases(mutant(mname, old, new), mname)
        caught = [n for n, ok, _ in res if not ok]
    except Exception as e:      # a crash also counts as caught, but say so
        caught = ['crash: %s' % type(e).__name__]
    print('%s mutant %s caught by %s' % ('PASS' if caught else 'FAIL', mname, caught or 'nothing'))
    failures += not caught
print('RESULT', 'PASS' if not failures else 'FAIL %d' % failures)
sys.exit(1 if failures else 0)
