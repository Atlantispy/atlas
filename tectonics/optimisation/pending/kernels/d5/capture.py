"""D5 capture: record real calls of W._clip2, W._rotated_normal and W._line during a geometry replay.

Usage: python -B capture.py OUTDIR -- <replay_surfaces.py arguments>
Runs geometry's scripts/replay_surfaces.py unchanged in this process. After rc1_env.install (the original,
called first and in full) the three wall-measure functions are wrapped by module attribute, as replay_surfaces
itself wraps _Arena.work and _moving_interface_leaf for its diagnostics; no global profile/trace hook. Each
call's arguments (arena dropped) and result are pickled at call time, with the result's identity relation to
the inputs. Writes OUTDIR/calls-<kind>.pkl (a list of (args_bytes, result_bytes, relation)) and summary.json.
Read-only on geometry files; OUTDIR must not exist.
"""
import json
import pickle
import runpy
import sys
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
G = T/('fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/'
       'geometry-growth-r1')
LIMIT = 60000                      # per kind; later calls are counted, not stored
out = Path(sys.argv[1])
assert sys.argv[2] == '--'
out.mkdir(parents=True)
calls = {'clip2': [], 'rotated_normal': [], 'line': []}
counts = {k: 0 for k in calls}
inner = {'clip2_without_arena': 0}


def keep(kind, args, result, relation):
    counts[kind] += 1
    if len(calls[kind]) < LIMIT:
        calls[kind].append((pickle.dumps(args, protocol=5), pickle.dumps(result, protocol=5), relation))


def patch():
    from atlas_tectonics import integration_wall_measures as W
    clip2, rotated, line = W._clip2, W._rotated_normal, W._line

    def clip2_rec(poly, line_, arena=None):
        if arena is None:              # the reference's own recursion inside its lease (or a bare call)
            inner['clip2_without_arena'] += 1
            return clip2(poly, line_)
        result = clip2(poly, line_, arena)
        relation = ('poly' if result is poly else 'empty' if result == () else
                    [next((i for i, p in enumerate(poly) if p is r), None) for r in result])
        keep('clip2', (poly, line_), result, relation)
        return result

    def rotated_rec(normal, omega, t0, t1, level, arena):
        result = rotated(normal, omega, t0, t1, level, arena)
        keep('rotated_normal', (normal, omega, t0, t1, level), result, 'normal' if result[0] is normal else None)
        return result

    def line_rec(face, normal, offset=0):
        result = line(face, normal, offset)
        keep('line', (face, normal, offset), result, None)
        return result

    W._clip2, W._rotated_normal, W._line = clip2_rec, rotated_rec, line_rec


sys.path.insert(0, str(G/'scripts'))
import rc1_env  # noqa: E402
original_install = rc1_env.install


def install(runtime='rc1'):
    original_install(runtime)
    patch()


rc1_env.install = install
script = str(G/'scripts'/'replay_surfaces.py')
sys.argv = [script, *sys.argv[3:]]
status = 'ok'
try:
    runpy.run_path(script, run_name='__main__')
except SystemExit as exc:
    status = 'exit %r' % (exc.code,)
finally:
    for kind, rows in calls.items():
        (out/('calls-%s.pkl' % kind)).write_bytes(pickle.dumps(rows, protocol=5))
    stored = {k: len(v) for k, v in calls.items()}
    (out/'summary.json').write_text(json.dumps(dict(status=status, counts=counts, stored=stored, **inner), indent=1),
                                    encoding='utf8')
    print('capture', status, counts, inner)
