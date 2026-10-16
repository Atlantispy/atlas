"""Interval-2 interface serial-time projection that counts EVERY sampled query.

sample  replay rows of the 1-in-10 support sample at a short cap (all interface jobs);
deep    the same arm's rerun of every job the sample capped, at a longer cap.
Per arm: settled-in-sample CPU + deep CPU of the capped jobs (settled, certified or still
capped; a still-capped job counts at its cap, so the total is a LOWER bound whenever any
remain capped). Projection = sample total x (total interval-2 interface jobs / sampled jobs),
the plain ratio estimator over a systematic 1-in-10 support sample (support 880 alone holds
most of the hard jobs, so the estimate carries that clustering).
Usage: project_interfaces.py --total-jobs 63752 --arm NAME SAMPLE_GLOB DEEP_GLOB [--arm ...]
"""
import argparse
import glob
import json
from collections import Counter


def rows(pattern):
    out = {}
    for path in sorted(glob.glob(pattern)):
        for line in open(path, encoding='utf8'):
            r = json.loads(line)
            if r.get('kind') == 'interface':
                out[(r['support_index'], r['cell'], r.get('other'), r['constraint_name'])] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--total-jobs', type=int, required=True)
    ap.add_argument('--arm', nargs=3, action='append', required=True, metavar=('NAME', 'SAMPLE', 'DEEP'))
    args = ap.parse_args()
    report = {}
    for name, sample_glob, deep_glob in args.arm:
        sample, deep = rows(sample_glob), rows(deep_glob)
        settled = [r for r in sample.values() if r['status'] == 'met']
        capped = [k for k, r in sample.items() if r['status'] != 'met']
        missing = [k for k in capped if k not in deep]
        tally, cpu = Counter(), Counter()
        cap = max((r['cpu_s'] for r in deep.values() if r['status'] == 'capped'), default=None)
        for k in capped:
            r = deep.get(k)
            if r is None:
                continue
            kind = ('certified' if 'complementary' in (r.get('rule') or '') else
                    'settled' if r['status'] == 'met' else r['status'])
            tally[kind] += 1
            cpu[kind] += r['cpu_s']
        total = sum(r['cpu_s'] for r in settled) + sum(cpu.values())
        scale = args.total_jobs / len(sample)
        report[name] = dict(sampled_jobs=len(sample), settled_at_short_cap=len(settled),
            settled_cpu_s=round(sum(r['cpu_s'] for r in settled), 1), capped_at_short_cap=len(capped),
            deep_missing=len(missing), deep=dict(tally), deep_cpu_s={k: round(v, 1) for k, v in cpu.items()},
            deep_cap_s=cap, sample_total_cpu_s=round(total, 1), scale=round(scale, 3),
            projected_serial_hours=round(total*scale/3600, 2),
            lower_bound_only=bool(tally.get('capped')),
            projected_capped_jobs=round(tally.get('capped', 0)*scale))
    print(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
