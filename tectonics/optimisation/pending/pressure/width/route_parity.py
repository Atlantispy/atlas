"""Pressure route parity of the posed boundaries, before and after the pose width rounding (condition 1).

Usage: route_parity.py OUT_JSON BEFORE_RUNTIME AFTER_RUNTIME INTERVAL_GZ@SHA256 [INTERVAL_GZ@SHA256 ...]
       (runtimes as frozen:<folder>; each interval file is a gzip JSON whose 'interval' key is a
       differential interval record; its sha256 is checked before anything is read)

For every interval, boundary and endpoint ('start', 'end') the pose is built as
integration_differential_geometry.posed_boundary builds it (the runtime's own _history, _load_vec,
_store_vec and _qtext; E._representative_pose at the production max_operator_error 1e-20;
CartesianCell.rotated), then read back as integration_differential_pressure._boundary_views reads
the issued record (rotation_matrix, pose_operator_error_bound, boundary_rotations), and classified
by the spatial-pressure route decisions that read the pose:
  exact    pose._error == 0                                   (spatial_pressure: exact planes/rays)
  axis     P._pose_axis(pose) is not None                     (invariant-axis paths)
  inexact  otherwise                                          (the inexact-pose route)
plus, for the axis route, which coordinate wall normals are invariant (not any(cross(normal, axis))).
Each runtime is a separate child process. Besides the real records, each boundary is also posed on
two derived SYNTHETIC histories: its real steps followed by a step about a tilted axis (multi-axis)
and a zero-rate/zero-time padded copy of its real steps; they are labelled as synthetic.
Exit 0 only if every pose takes the same route, axis and invariant normals in both runtimes.
"""
import gzip
import hashlib
import json
import subprocess
import sys
from collections import Counter
from fractions import Fraction as Q
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOAL = Q(1, 10**20)
NORMALS = {'+x': (1, 0, 0), '+y': (0, 1, 0), '+z': (0, 0, 1)}


def _bits(values):
    return max(max(abs(v.numerator).bit_length(), v.denominator.bit_length()) for v in values)


def runtime_sources(env_module):
    """sha256 of every loaded .py file under the selected runtime's src and helpers, relative to its folder.

    (rc1_env.loaded_sources() names files relative to the RC1 tree, so it cannot name a frozen: folder.)
    """
    roots = (env_module.RC1_ROOT, env_module.HELPERS)
    out = {}
    for _name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and path.endswith('.py'):
            p = Path(path).resolve()
            if any(p.is_relative_to(root) for root in roots):
                out[p.relative_to(env_module.RC1_ROOT.parent).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def child(runtime, out, paths):
    sys.path.insert(0, str(HERE.parent/'scripts'))
    import rc1_env
    rc1_env.install(runtime)
    from atlas_tectonics import integration_differential_geometry as D
    from atlas_tectonics import integration_differential_pressure as DP
    from atlas_tectonics import integration_exterior_mesh as E
    from atlas_tectonics import integration_spatial_pressure as P
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_volume_bounds as B
    from atlas_tectonics import integration_volume_overlap as O
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(1 << 32)

    def pose_of(history):
        steps = [dict(angular_velocity_rad_s=D._store_vec(w), start_time_s=D._qtext(Q(0)), end_time_s=D._qtext(dt))
                 for w, dt in history if dt and any(w)]
        with B._Arena(budget) as arena:
            quaternion, error = E._representative_pose(steps, GOAL, arena)
            basis = V.CartesianCell((0, 0, 0), (1, 1, 1), budget=budget).rotated(quaternion, budget=budget).basis
        record = dict(boundary_rotations=steps, rotation_matrix=[D._store_vec(row) for row in basis],
                      pose_operator_error_bound=D._qtext(error))
        views = tuple((tuple(map(W._decode, step['angular_velocity_rad_s'])),
                       W._decode(step['end_time_s'])-W._decode(step['start_time_s']))
                      for step in record['boundary_rotations'])
        pose = DP._KernelPose(tuple(tuple(map(W._decode, row)) for row in record['rotation_matrix']),
                              W._decode(record['pose_operator_error_bound']), history=views)
        axis = P._pose_axis(pose, budget)
        route = 'exact' if pose._error == 0 else 'axis' if axis is not None else 'inexact'
        invariant = sorted(k for k, n in NORMALS.items() if axis is not None and not any(O._cross(n, axis)))
        return dict(route=route, axis=None if axis is None else [V._encoded(Q(q)) for q in axis], invariant=invariant,
                    steps=len(steps), error=V._encoded(error), error_bits=_bits((error,)),
                    quaternion=[V._encoded(q) for q in quaternion], quaternion_bits=_bits(quaternion),
                    kernel_axis=pose._axis is not None)

    poses = {}
    for path in paths:
        record = json.loads(gzip.open(path).read())['interval']
        duration = W._decode(record['duration_s'])
        for boundary in record['boundary_paths']:
            prior = list(D._history(boundary.get('prior_rotations', ())))
            current = (D._load_vec(boundary['angular_velocity_rad_s']), duration)
            base = '%s/%s' % (record['interval_id'][:12], boundary['boundary_id'])
            for endpoint, history in (('start', prior), ('end', prior+[current])):
                poses['real %s %s' % (base, endpoint)] = pose_of(history)
            # derived synthetic histories (not real data): a tilted extra step makes the history multi-axis;
            # zero-rate and zero-time steps are filtered by the pose builder and must change nothing.
            w = current[0]
            speed = sum(map(abs, w))
            tilted = (speed*Q(3, 5), Q(0), speed*Q(4, 5))
            poses['synthetic multi-axis %s' % base] = pose_of(prior+[current, (tilted, duration)])
            poses['synthetic padded %s' % base] = pose_of([((Q(0),)*3, duration), *prior, (w, Q(0)), current])
    Path(out).write_text(json.dumps(dict(runtime=runtime, poses=poses, loaded_sources=runtime_sources(rc1_env)),
                                    indent=1), encoding='utf8')


def main():
    if sys.argv[1] == 'child':
        return child(sys.argv[2], sys.argv[3], sys.argv[4:])
    out, before, after, inputs = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4:]
    paths = []
    for item in inputs:
        path, _, want = item.rpartition('@')
        got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if got != want:
            raise SystemExit('input %s sha256 %s, expected %s' % (path, got, want))
        paths.append(path)
    results = {}
    for label, runtime in (('before', before), ('after', after)):
        part = out.with_name(out.stem+'-'+label+'.json')
        subprocess.run([sys.executable, '-B', '-I', __file__, 'child', runtime, str(part), *paths], check=True)
        results[label] = json.loads(part.read_text(encoding='utf8'))
    a, b = results['before']['poses'], results['after']['poses']
    fields = ('route', 'axis', 'invariant', 'steps', 'kernel_axis')
    mismatches = [key for key in a if key not in b or any(a[key][f] != b[key][f] for f in fields)]
    counts = {label: Counter('%s %s' % (k.split()[0], v['route']) for k, v in results[label]['poses'].items())
              for label in results}
    rows = []
    for key in sorted(a):
        ea, eb = (Q(int(n, 16), int(d, 16)) for n, d in (a[key]['error'], b[key]['error']))
        share = None if not ea else float((eb-ea)/ea)
        rows.append(dict(pose=key, route_before=a[key]['route'], route_after=b[key]['route'],
                         invariant=b[key]['invariant'], steps=a[key]['steps'], added_share=share,
                         quaternion_bits=(a[key]['quaternion_bits'], b[key]['quaternion_bits']),
                         error_bits=(a[key]['error_bits'], b[key]['error_bits'])))
        print('%-46s %-7s -> %-7s inv %-6s steps %d  share %-10s qbits %s' % (
            key, a[key]['route'], b[key]['route'], ','.join(b[key]['invariant']) or '-', a[key]['steps'],
            '-' if share is None else '%.3g' % share, rows[-1]['quaternion_bits']))
    out.write_text(json.dumps(dict(inputs=inputs, before=before, after=after, counts=counts, mismatches=mismatches,
                                   rows=rows), indent=1), encoding='utf8')
    print('route counts before:', dict(counts['before']))
    print('route counts after: ', dict(counts['after']))
    print('ROUTE PARITY %s (%d poses, %d mismatches)' % ('PASS' if not mismatches else 'FAIL', len(a), len(mismatches)))
    raise SystemExit(1 if mismatches else 0)


if __name__ == '__main__':
    main()
