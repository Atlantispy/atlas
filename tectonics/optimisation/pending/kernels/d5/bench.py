"""D5 prototype check: replay captured W._clip2/_rotated_normal/_line calls through the reference and twin.py.

Usage: python -B bench.py CAPTURE_DIR OUT_JSON [ROUNDS]
Runtime: test:T/gg/final-f2 (rc1_env.install, the original). For every captured call, both routes run on the
same input objects with a recording budget and arena; the call passes only if
  - pickle bytes of (inputs, result) are equal at protocols 2-5 (values, types and every identity/memo
    relation between inputs and result, e.g. `poly` returned itself, kept vertices, shared objects),
  - the deep type shape is equal, including the int type inside every Fraction,
  - the reference result equals the captured one (the recording stubs changed nothing),
  - the ordered trace of arena.work(n) and budget.reserve(amount, category) entry/exit is equal,
  - exceptions (type and text) are equal, and the budget is released afterwards.
The twin's guard fallbacks (calls it hands to the reference) are counted, so a pass is not a fallback pass.
Timing: ROUNDS x ABBA (reference, twin, twin, reference) over all calls of a kind, process CPU, plain budget.
"""
import json
import pickle
import statistics
import sys
import time
from contextlib import contextmanager
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
G = T/('fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/'
       'geometry-growth-r1')
sys.path.insert(0, str(G/'scripts'))
import rc1_env  # noqa: E402

rc1_env.install('test:%s' % (T/'gg'/'final-f2').as_posix())
sys.path.insert(0, str(Path(__file__).resolve().parent))
import twin  # noqa: E402
from atlas_tectonics.resources import WorkBudget  # noqa: E402

cap, out = Path(sys.argv[1]), Path(sys.argv[2])
rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 3
LOG = []
FALLBACK = [0]


class Recording(WorkBudget):
    @contextmanager
    def reserve(self, count, *, category='work'):
        LOG.append(('reserve', count, category))
        with super().reserve(count, category=category):
            LOG.append(('held', self.reserved_bytes))
            yield
        LOG.append(('release', count, category))


class Arena:
    def __init__(self, resource, log=None):
        self.resource, self.log = resource, log

    def work(self, count):
        if self.log is not None:
            self.log.append(('work', count))


def counted(fn):
    def call(*args):
        FALLBACK[0] += 1
        return fn(*args)
    return call


REFS = dict(clip2=twin.REF_CLIP2, rotated_normal=twin.REF_ROTATED, line=twin.REF_LINE)
twin.REF_CLIP2, twin.REF_ROTATED, twin.REF_LINE = (counted(REFS[k]) for k in ('clip2', 'rotated_normal', 'line'))
ROUTES = dict(clip2=(twin.clip2, lambda a, arena: (*a, arena)),
              rotated_normal=(twin.rotated_normal, lambda a, arena: (*a, arena)),
              line=(twin.line, lambda a, arena: a))


def shape(v):
    t = type(v)
    if t is tuple or t is list:
        return (t.__name__, tuple(shape(x) for x in v))
    if t is twin.Q:
        return ('Fraction', type(v._numerator).__name__, type(v._denominator).__name__)
    return t.__name__


def run(fn, args):
    LOG.clear()
    try:
        result, error = fn(*args), None
    except Exception as exc:  # compared, not swallowed: both routes must raise the same
        result, error = None, (type(exc).__name__, str(exc))
    return result, error, list(LOG)


summary: dict = dict(runtime='test:gg/final-f2', backend=twin.X.selection(),
                     from_coprime=twin._from_coprime is not None, rounds=rounds)
for kind, (tw, build) in ROUTES.items():
    ref = REFS[kind]
    rows = pickle.loads((cap/('calls-%s.pkl' % kind)).read_bytes())
    calls = [pickle.loads(a) for a, _, _ in rows]
    bad, examples, raised = 0, [], 0
    FALLBACK[0] = 0
    for index, (args, (_, captured, _)) in enumerate(zip(calls, rows, strict=True)):
        budget = Recording(16 << 30)
        r_res, r_err, r_log = run(ref, build(args, Arena(budget, LOG)))
        t_res, t_err, t_log = run(tw, build(args, Arena(budget, LOG)))
        problems = []
        raised += r_err is not None
        if r_err != t_err:
            problems.append('errors %r / %r' % (r_err, t_err))
        if r_err is None and pickle.dumps(r_res, protocol=5) != captured:
            problems.append('reference differs from the captured result')
        for protocol in (2, 3, 4, 5):
            if pickle.dumps((args, r_res), protocol=protocol) != pickle.dumps((args, t_res), protocol=protocol):
                problems.append('pickle(inputs, result) differs at protocol %d' % protocol)
                break
        if shape(r_res) != shape(t_res):
            problems.append('type shape differs')
        if r_log != t_log:
            problems.append('trace differs: %d vs %d entries' % (len(r_log), len(t_log)))
        if budget.reserved_bytes != 0:
            problems.append('budget not released')
        if problems:
            bad += 1
            if len(examples) < 5:
                examples.append(dict(index=index, problems=problems))
    fallbacks = FALLBACK[0]
    del rows
    times = {'reference': [], 'twin': []}
    for _ in range(rounds):
        for name in ('reference', 'twin', 'twin', 'reference'):
            fn = ref if name == 'reference' else tw
            prepared = [build(args, Arena(WorkBudget(16 << 30))) for args in calls]
            t0 = time.process_time()
            for a in prepared:
                fn(*a)
            times[name].append(time.process_time()-t0)
    med = {k: statistics.median(v) for k, v in times.items()}
    summary[kind] = dict(calls=len(calls), fallbacks=fallbacks, raised=raised, bad=bad, examples=examples,
                         cpu_s={k: [round(x, 3) for x in v] for k, v in times.items()},
                         median_s={k: round(v, 3) for k, v in med.items()},
                         speedup=round(med['reference']/med['twin'], 2) if med['twin'] else None,
                         us_per_call={k: round(1e6*v/len(calls), 1) for k, v in med.items()})
    print(kind, json.dumps(summary[kind]), flush=True)
    del calls
out.write_text(json.dumps(summary, indent=1, default=str), encoding='utf8')
ok = all(summary[k]['bad'] == 0 for k in ROUTES)
print('D5 BENCH', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
