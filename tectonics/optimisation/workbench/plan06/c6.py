"""Local genuine N9-W pose boundary validation; no final composition acceptance.
Usage: python -B c6.py --scripts G --runtime CANDIDATE --base BASE --out NEW.json
"""
import argparse
from contextlib import contextmanager
from fractions import Fraction as Q
from hashlib import sha256
import importlib.util
import inspect
import json
import os
from pathlib import Path
import pickle
import random
import sys
import traceback

p = argparse.ArgumentParser()
for name in ('scripts', 'runtime', 'base', 'out'):
    p.add_argument('--'+name, required=True)
a = p.parse_args()
report = dict(scope='local test-only N9-W+D5 boundary; no final N9/Plan31 acceptance')
out = Path(a.out)
if os.environ.get('PYTHONHASHSEED') != '0' or sys.flags.isolated:
    raise SystemExit('seed-zero non-isolated runtime required')

def main():
    sys.path.insert(0, str(Path(a.scripts).resolve()))
    import rc1_env
    rc1_env.install('test:'+Path(a.runtime).resolve().as_posix())
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics import integration_wall_measures_gmp as D
    from atlas_tectonics import exact_arithmetic as X
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.integration_volume_bounds import _Arena, NATIVE_RETAINED
    source = Path(a.base)/'atlas_tectonics/integration_wall_measures.py'
    assert sha256(source.read_bytes()).hexdigest() == 'a7a7dc432a45439aa47d912fd6d1424be7f7c1081d03bd079aa075be6550ebef'
    spec = importlib.util.spec_from_file_location('atlas_tectonics._c6_reference', source)
    R = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = R
    spec.loader.exec_module(R)
    assert D._resident() and D._module is W and X.selection()['backend'] == 'gmpy2'
    assert inspect.getsource(R._pose_vector) == inspect.getsource(W._pose_vector)
    for name in ('_round_to', '_round_up', '_floor_log2', '_ceil_log2'):
        assert inspect.getsource(getattr(R, name)) == inspect.getsource(getattr(W, name))

    class Recording(WorkBudget):
        @contextmanager
        def reserve(self, count, *, category='work'):
            events.append(('reserve', count, category))
            try:
                with super().reserve(count, category=category):
                    yield
            finally:
                events.append(('release', count, category))
    class Arena(_Arena):
        def work(self, n):
            events.append(('work', n))
            super().work(n)

    vectors = ((1, 0, 0), (Q(1, 3), Q(-2, 7), Q(5, 11)), (0, 0, 0))
    omegas = ((0, 0, 0), (0, 0, Q(1, 3)), (Q(1, 7), Q(-1, 5), Q(1, 11)))
    histories = ((), (((0, 0, Q(1, 3)), Q(1, 8)),),
                 (((0, Q(1, 7), 0), Q(-1, 4)), ((Q(1, 5), 0, 0), Q(1, 8))))
    cases = [(v, w, t0, t1, level, prior, inverse)
             for v in vectors for w in omegas for t0, t1 in ((Q(0), Q(0)), (Q(0), Q(1, 8)))
             for level in (-16, 0, 3) for prior in histories for inverse in (False, True)]
    failures, rows = [], []
    total_rounding = 0
    for index, (v, w, t0, t1, level, prior, inverse) in enumerate(cases):
        input_record = (v, w, t0, t1, level, prior, inverse)
        results = []
        for mod in (R, W):
            events, rounding = [], []
            originals = {n: getattr(mod, n) for n in ('_round_to', '_round_up')}
            def wrap(name):
                def call(*args):
                    result = originals[name](*args)
                    rounding.append((name, args, result))
                    return result
                return call
            for name in originals:
                setattr(mod, name, wrap(name))
            b = Recording(16 << 30)
            try:
                with Arena(b) as arena:
                    result = mod._pose_vector(v, w, t0, t1, level, arena, prior, inverse=inverse)
                error = None
            except Exception as exc:
                result, error = None, (type(exc).__name__, str(exc))
            finally:
                for name, original in originals.items():
                    setattr(mod, name, original)
            assert b.reserved_bytes == 0
            results.append((result, error, events, rounding))
        r, c = results
        problems = []
        if r[1] != c[1] or r[1] is not None:
            problems.append('unexpected/different exception')
        for protocol in (2, 3, 4, 5):
            if pickle.dumps((input_record, r[0]), protocol) != pickle.dumps((input_record, c[0]), protocol):
                problems.append('pickle type/value/alias difference protocol '+str(protocol))
        ordinary = [e for e in c[2] if e[0] == 'work' or e[2] != NATIVE_RETAINED]
        if ordinary != r[2]:
            problems.append('ordinary reservation/work trace')
        if r[3] != c[3]:
            problems.append('rounding sequence/inputs/results differ')
        native = [e for e in c[2] if e[0] != 'work' and e[2] == NATIVE_RETAINED]
        if sorted(e[1] for e in native if e[0] == 'reserve') != sorted(e[1] for e in native if e[0] == 'release'):
            problems.append('unbalanced native surcharge')
        total_rounding += len(c[3])
        rows.append(dict(case=index, level=level, history_steps=len(prior), inverse=inverse,
                         rounds=len(c[3]), native_events=len(native),
                         ordinary_trace_sha256=sha256(pickle.dumps(r[2], 5)).hexdigest(),
                         rounding_trace_sha256=sha256(pickle.dumps(r[3], 5)).hexdigest()))
        if problems:
            failures.append(dict(case=index, input=repr(input_record), problems=problems,
                                 reference=repr(r), candidate=repr(c)))
    assert total_rounding > 0 and D._resident() and any(row['native_events'] for row in rows)
    report.update(cases=len(cases), rounding_calls=total_rounding, rows=rows, failures=failures,
                  backend=X.selection(), resident=D._resident(), verdict='FAIL' if failures else 'PASS',
                  source_hashes={str(Path(m.__file__).resolve()): sha256(Path(m.__file__).read_bytes()).hexdigest()
                                 for m in (W, R, D)},
                  checker_sha256=sha256(Path(__file__).read_bytes()).hexdigest())

try:
    main()
except Exception as exc:
    report.update(verdict='FAIL', error=repr(exc), traceback=traceback.format_exc())
out.write_text(json.dumps(report, indent=1)+'\n')
print(json.dumps({k: report[k] for k in ('scope', 'verdict', 'cases', 'rounding_calls') if k in report}))
raise SystemExit(0 if report['verdict'] == 'PASS' else 1)
