"""Read-only: numerator/denominator bit widths of exact geometry quantities, by interval and depth.

Quantities (bits = |numerator|.bit_length(), denominator.bit_length()):
  stored     every rational stored in a REFERENCED support constraint record
             (directions, rates, durations, offsets, normals), by snapshot depth;
  posed      G._constraint_pose(c, t, t, level) at both endpoint instants (0, duration)
             and the given levels: normal components, error bound, offset, by depth;
  volumes    exact endpoint volumes from replay rows ('exact': lower, upper, witness),
             by the query's max snapshot depth;
  surfaces   exact interface/wall bounds from surface replay rows (inward/outward);
  iv3        PROJECTION: each referenced IV2 constraint wrapped exactly as
             prepare_interval_partition carries it (integration_differential_geometry
             line ~2638: snapshot-rotated, offset = the old interval's end, rate = the new
             plate rate), with IV2's duration and the support's IV2 plate rate standing in
             for interval 3's; stored and posed widths of those depth d+1 records.
Posing is deduplicated by (encoded record, instant, level). Process CPU only; one process.
Usage: measure_bitwidths.py --runtime rc1 --supports S --label IV1 [--volumes GLOB] [--surfaces GLOB]
       [--levels 0,24] [--pose-every 1] [--iv3] --output OUT.json
"""
import argparse
import glob
import gzip
import json
import sys
import time
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402


def bits(q):
    return abs(q.numerator).bit_length(), q.denominator.bit_length()


class Stats:
    def __init__(self):
        self.num, self.den = defaultdict(list), defaultdict(list)
        self.inexact = defaultdict(int)

    def add(self, key, q):
        if type(q) not in (int, Fraction):
            self.inexact[' / '.join(map(str, key)) + ' / ' + type(q).__name__] += 1
            return
        n, d = bits(q)
        self.num[key].append(n)
        self.den[key].append(d)

    def summary(self):
        out = {}
        for key in sorted(self.num, key=str):
            nums, dens = sorted(self.num[key]), sorted(self.den[key])
            p99 = lambda xs: xs[min(len(xs)-1, int(0.99*len(xs)))]
            out[' / '.join(map(str, key))] = dict(count=len(nums), num_max=nums[-1], num_p99=p99(nums),
                                                   den_max=dens[-1], den_p99=p99(dens))
        if self.inexact:
            out['NOT RATIONAL'] = dict(self.inexact)
        return out


def depth(c):
    d = 0
    while c.get('kind') == 'snapshot-rotated':
        d += 1
        c = c['constraint']
    return d


def history(c):
    """Rotation steps in the record: snapshot wrappers plus every ray's prior rotations (max over rays)."""
    steps = 0
    while c.get('kind') == 'snapshot-rotated':
        steps += 1
        c = c['constraint']
    return steps + max((len(ray.get('prior_rotations', ())) for ray in c.get('rays', ())), default=0)


def rationals(value, decode):
    """Every stored rational (hex numerator/denominator pair) inside a record."""
    if isinstance(value, list) and len(value) == 2 and all(isinstance(x, str) and x.lstrip('-').startswith('0x') for x in value):
        yield decode(value)
        return
    if isinstance(value, dict):
        for v in value.values():
            yield from rationals(v, decode)
    elif isinstance(value, list):
        for v in value:
            yield from rationals(v, decode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runtime', default='rc1')
    ap.add_argument('--supports', required=True)
    ap.add_argument('--label', required=True)
    ap.add_argument('--volumes', default=None)
    ap.add_argument('--surfaces', default=None)
    ap.add_argument('--levels', default='0,24')
    ap.add_argument('--pose-every', type=int, default=1, help='pose only supports with index %% k == 0')
    ap.add_argument('--iv3', action='store_true')
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0, as production does')
    out = Path(args.output)
    if out.exists():
        raise SystemExit('output exists')
    rc1_env.install(args.runtime)
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_volume_bounds as B
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    levels = [int(x) for x in args.levels.split(',')]
    stored, posed, vols, surf, steps = Stats(), Stats(), Stats(), Stats(), Stats()
    seen_pose = set()
    t0 = time.process_time()
    supports = poses = 0
    with gzip.open(args.supports, 'rt', encoding='utf8') as f:
        f.readline()
        for index, line in enumerate(f):
            r = json.loads(line)
            supports += 1
            duration = W._decode(r['duration_s'])
            used = {n for p in r['components'] for n, _ in p['constraints']}
            pose_here = index % args.pose_every == 0
            plate = r.get('material_angular_velocity_rad_s')
            for name in used:
                c = r['constraints'][name]
                d = depth(c)
                for q in rationals(c, W._decode):
                    stored.add((args.label, 'depth %d' % d), q)
                records = [(args.label, d, c, (Fraction(0), duration))]
                if args.iv3 and plate is not None:
                    carried = dict(kind='snapshot-rotated', constraint=c, snapshot_offset_s=r['duration_s'],
                                   angular_velocity_rad_s=plate)
                    for q in rationals(dict(o=carried['snapshot_offset_s'], w=plate), W._decode):
                        stored.add(('IV3 proxy', 'depth %d' % (d+1)), q)
                    for q in rationals(c, W._decode):
                        stored.add(('IV3 proxy', 'depth %d' % (d+1)), q)
                    records.append(("IV3 proxy", d+1, carried, (Fraction(0), duration)))
                if not pose_here:
                    continue
                for label, dd, record, instants in records:
                    key = G._encoded(record)
                    for t in instants:
                        for level in levels:
                            token = (key, t, level)
                            if token in seen_pose:
                                continue
                            seen_pose.add(token)
                            with B._Arena(budget) as arena:
                                normal, error, offset = G._constraint_pose(record, t, t, level, arena)
                            poses += 1
                            for q in normal:
                                posed.add((label, 'depth %d' % dd, 'level %d' % level, 'normal'), q)
                                steps.add((label, 'rotation steps %d' % history(record), 'level %d' % level, 'normal'), q)
                            posed.add((label, 'depth %d' % dd, 'level %d' % level, 'error'), error)
                            steps.add((label, 'rotation steps %d' % history(record), 'level %d' % level, 'error'), error)
                            posed.add((label, 'depth %d' % dd, 'level %d' % level, 'offset'), offset)
    pose_cpu = time.process_time()-t0
    if args.volumes:
        for path in sorted(glob.glob(args.volumes)):
            for line in open(path, encoding='utf8'):
                r = json.loads(line)
                if 'exact' not in r:
                    continue
                for name, value in zip(('lower', 'upper', 'witness'), r['exact']):
                    q = W._decode(value)
                    if q:
                        vols.add((args.label, 'depth %d' % r.get('max_snapshot_depth', -1), name), q)
    if args.surfaces:
        for path in sorted(glob.glob(args.surfaces)):
            for line in open(path, encoding='utf8'):
                r = json.loads(line)
                for side in ('inward', 'outward'):
                    for value in (r.get(side) or ()):
                        q = W._decode(value)
                        if q:
                            surf.add((args.label, r['kind'], side), q)
    report = dict(label=args.label, runtime=args.runtime, supports=supports, poses=poses, levels=levels,
                  pose_every=args.pose_every, pose_cpu_s=round(pose_cpu, 1), package_digest=rc1_env.package_digest(),
                  stored=stored.summary(), posed=posed.summary(), posed_by_rotation_steps=steps.summary(),
                  volumes=vols.summary(), surfaces=surf.summary(),
                  note='nonzero values only for volumes/surfaces; exact zeros carry no width')
    with out.open('x', encoding='utf8') as sink:
        json.dump(report, sink, indent=1)
    print(json.dumps(dict(supports=supports, poses=poses, pose_cpu_s=round(pose_cpu, 1))))


if __name__ == '__main__':
    main()
