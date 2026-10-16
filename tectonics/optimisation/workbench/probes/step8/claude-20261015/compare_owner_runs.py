"""Compare two measure_live_owner result.json files (before/after).

Usage: python -B compare_owner_runs.py BEFORE_DIR AFTER_DIR OUT.json
Reports: cleanup, identities, array digest equality per family, logical record
sizes/hashes, stage timings and memory at each checkpoint, store bytes.
"""
import json
import os
import sys


def load(directory):
    with open(os.path.join(directory, 'result.json'), encoding='utf-8') as f:
        return json.load(f)


def stage_rows(result):
    rows, start = {}, None
    previous = None
    for row in result['checkpoints']:
        if row['stage'] == 'measured-start':
            start = row['elapsed_seconds']
        rows[row['stage']] = dict(elapsed=row['elapsed_seconds'],
            delta=None if previous is None else row['elapsed_seconds']-previous,
            rss=row['rss_bytes'], private=row['private_bytes'], peak_rss=row['process_peak_rss_bytes'],
            reserved=row['logical_reserved_bytes'], logical_peak=row['logical_peak_bytes'],
            disk=row['disk_bytes'])
        previous = row['elapsed_seconds']
    return rows, start


def main():
    before, after = load(sys.argv[1]), load(sys.argv[2])
    report = dict(before=sys.argv[1], after=sys.argv[2])
    report['cleanup'] = {k: dict(cleanup=r.get('cleanup'), retained_after_close_bytes=r.get('retained_after_close_bytes'))
                         for k, r in (('before', before), ('after', after))}
    report['identities'] = {k: dict(before=before['identities'][k], after=after['identities'][k],
                                    equal=before['identities'][k] == after['identities'][k])
                            for k in before['identities']}
    arrays = {}
    for family in ('numeric_arrays', 'heat_arrays', 'native_arrays'):
        a, b = before.get(family, {}), after.get(family, {})
        arrays[family] = dict(count=len(a), names_equal=set(a) == set(b),
            digests_equal=all(a[n]['sha256'] == b.get(n, {}).get('sha256') for n in a),
            differing=[n for n in a if a[n]['sha256'] != b.get(n, {}).get('sha256')])
    report['arrays'] = arrays
    report['logical_records'] = {k: dict(before=before['logical_records'][k], after=after['logical_records'].get(k),
                                         equal=before['logical_records'][k] == after['logical_records'].get(k))
                                 for k in before['logical_records']}
    stages_a, start_a = stage_rows(before)
    stages_b, start_b = stage_rows(after)
    report['stages'] = {k: dict(before=stages_a[k], after=stages_b.get(k)) for k in stages_a}
    end = 'numeric-commit-and-seal'
    report['measured_seconds'] = dict(before=stages_a[end]['elapsed']-start_a, after=stages_b[end]['elapsed']-start_b)
    report['store_statistics_equal'] = before.get('store_statistics') == after.get('store_statistics')
    with open(sys.argv[3], 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1, sort_keys=True)
    print('cleanup', report['cleanup'])
    print('measured seconds', report['measured_seconds'])
    for k, v in report['identities'].items():
        print('identity', k, 'equal' if v['equal'] else 'DIFFERS')
    for k, v in arrays.items():
        print('arrays', k, v['count'], 'digests_equal', v['digests_equal'], v['differing'][:8])
    for k, v in report['logical_records'].items():
        print('record', k, 'equal' if v['equal'] else 'DIFFERS', v['before'], v['after'])


if __name__ == '__main__':
    main()
