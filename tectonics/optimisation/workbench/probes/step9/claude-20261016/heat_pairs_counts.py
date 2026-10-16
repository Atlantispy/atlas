"""Read-only: call counts in an existing pstats profile for the functions Heat's observer pairs name.

Usage: python -B heat_pairs_counts.py <file.pstats>
Prints ncalls / cumtime of every profiled function with one of the names below, so the cost of a phase
marker (one phase write per call) or a tick (one count and one guard check per return) can be bounded
before the pairs join the observer. Nested functions appear under their own name. Nothing is written.
"""
import os
import pstats
import sys

NAMES = {'correct', 'closed_guard', 'issue', 'verified_private', 'calculate', 'metric_identity',
         'certificate', 'admissible', '_guard', 'finish', 'project', '_face', 'completed',
         'component_volume_bounds', 'reconstruct', 'solve'}


def main(path):
    stats = pstats.Stats(path).stats
    total = max(item[3] for item in stats.values())
    print('largest cumtime', f'{total:.1f}s', 'entries', len(stats))
    rows = sorted(((cumulative, calls, f'{os.path.basename(filename)}:{line} {name}')
                   for (filename, line, name), (primitive, calls, own, cumulative, callers) in stats.items()
                   if name in NAMES), reverse=True)
    for cumulative, calls, label in rows:
        print(f'  cum {cumulative:8.2f}s  calls {calls:8d}  {label}')


if __name__ == '__main__':
    main(sys.argv[1])
