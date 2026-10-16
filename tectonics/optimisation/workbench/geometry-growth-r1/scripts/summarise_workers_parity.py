"""Summary of run_workers_parity_r2.sh: byte parity across serial/1/2/4/6, and proof of concurrency.

An arm passes when its records and streams hashes equal the serial pass's and it raised no error.
The 4- and 6-worker arms must ALSO show more than two batch workers live at once in at least one
rolling controller (wall or interface); otherwise identical results would prove nothing about the
lifted cap, and the arm fails. Exit 0 only if every arm passes.
Usage: summarise_workers_parity.py OUT_DIR
"""
import json
import os
import sys

ARMS = ('serial', 'w1', 'w2', 'w4', 'w6')


def main():
    out = sys.argv[1]
    ok = True
    for name in ('iv1', 'iv2'):
        # Arms not run in this folder are skipped (r3 runs only w4/w6 and copies r2's serial baseline).
        rows = {arm: json.load(open('%s/%s-%s.json' % (out, name, arm))) for arm in ARMS
                if os.path.exists('%s/%s-%s.json' % (out, name, arm))}
        base = rows['serial']['records_sha256'], rows['serial']['streams_sha256']
        for arm, d in rows.items():
            same = (d['records_sha256'], d['streams_sha256']) == base and d['error'] is None
            controllers = d.get('concurrency', {}).get('controllers', {})
            peak = max((c['peak_live'] for c in controllers.values()), default=0)
            concurrent = arm not in ('w4', 'w6') or peak > 2
            ok &= same and concurrent
            bw = d['decision'].get('batch_workers') or {}
            print(name, arm.ljust(6), 'IDENTICAL' if same else 'DIFFERS',
                  '' if concurrent else 'NOT-CONCURRENT(peak<=2)',
                  'records', d['records'], 'error', d['error'], 'wall_s', d['wall_s'],
                  'parent_cpu_s', d['parent_cpu_s'],
                  'peak_live', {k: (c['peak_live'], c['session_workers']) for k, c in controllers.items()},
                  'peak_children', d.get('concurrency', {}).get('peak_child_processes'),
                  'children_rss_mib', d.get('concurrency', {}).get('peak_children_rss_mib'),
                  'parent_mib', d.get('parent_peak_working_set_mib'),
                  'started', bw.get('started'), 'jobs', bw.get('jobs'), 'adopted', bw.get('adopted'),
                  'reason', d['decision'].get('reason'))
    print('ALL IDENTICAL AND CONCURRENT' if ok else 'PARITY FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
