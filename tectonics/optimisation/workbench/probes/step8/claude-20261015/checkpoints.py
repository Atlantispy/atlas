"""Print a capacity run's checkpoints compactly.

Usage: python -B checkpoints.py CAPACITY.json
One line per phase: seconds, process RSS and private bytes, OS peak RSS, tracked
reserved and peak bytes, retained-scope bytes and output disk bytes. Then the
status, failure message (if any) and final figures.
"""
import json
import sys


def mb(value):
    return '-' if value is None else '%.1f' % (value/1e6)


def main():
    record = json.loads(open(sys.argv[1], encoding='utf-8').read())
    print('%-52s %8s %9s %9s %9s %10s %10s %9s %9s' % ('phase', 'seconds', 'rss_MB', 'priv_MB', 'peak_MB',
          'track_MB', 'tpeak_MB', 'ret_MB', 'disk_MB'))
    for row in record.get('checkpoints', []):
        process, tracked, scope = row.get('process') or {}, row.get('tracked') or {}, row.get('scope') or {}
        print('%-52s %8.1f %9s %9s %9s %10s %10s %9s %9s' % (row['name'][:52], row['seconds'],
              mb(process.get('rss_bytes')), mb(process.get('private_bytes')), mb(process.get('os_peak_rss_bytes')),
              mb(tracked.get('reserved_bytes')), mb(tracked.get('peak_reserved_bytes')),
              mb(scope.get('retained_bytes')), mb(row.get('output_disk_bytes'))))
    print('status', record.get('status'), 'elapsed', record.get('elapsed_seconds'))
    if record.get('failure'):
        print('failure', record['failure'].get('type'), record['failure'].get('message'))
    final = record.get('final_process') or {}
    print('final rss', mb(final.get('rss_bytes')), 'os peak', mb(final.get('os_peak_rss_bytes')),
          'tracked peak', mb((record.get('final_tracked') or {}).get('peak_reserved_bytes')),
          'disk', mb(record.get('output_disk_bytes')))


if __name__ == '__main__':
    main()
