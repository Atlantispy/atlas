"""Read-only: total CPU, leaves and status counts of geometry replay shards (one JSON row per query).

Usage: python -B sum_replay_cpu.py LABEL=SHARD[,SHARD...] [LABEL=...]
Rows without 'cpu_s' (shard headers) are skipped. Prints per label: queries, CPU s, wall s,
leaves, statuses, and the CPU ratio to the first label.
"""
import json
import sys
from collections import Counter


def main():
    first = None
    for item in sys.argv[1:]:
        label, paths = item.split('=', 1)
        queries, cpu, wall, leaves, status = 0, 0., 0., 0, Counter()
        for path in paths.split(','):
            with open(path, encoding='utf8') as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if 'cpu_s' not in row:
                        continue
                    queries += 1
                    cpu += row['cpu_s']
                    wall += row.get('wall_s', 0.)
                    leaves += row.get('leaves', 0)
                    status[row.get('status')] += 1
        first = first or cpu
        print(f'{label:14s} queries {queries:6d} cpu {cpu:9.1f} s wall {wall:9.1f} s leaves {leaves:9d} '
              f'cpu/first {cpu/first:5.2f}  {dict(status)}')


if __name__ == '__main__':
    main()
