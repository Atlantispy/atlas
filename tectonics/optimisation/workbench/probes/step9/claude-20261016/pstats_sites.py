"""Read-only: which of the item 11 commit-window calls an existing pstats profile contains.

Usage: python -B pstats_sites.py <file.pstats>
Prints ncalls / cumtime for every profiled function whose name is one of the observed stage
entry points (projection, packaging, checkpoint save, R3 checks, exterior finish, publish) or
their spatial-workflow callers, so a profile's coverage of the commit window can be read off.
cProfile adds overhead: the shares, not the absolute seconds, are the evidence. Nothing is written.
"""
import os
import pstats
import sys

NAMES = {'project', 'package_result', 'save', '_r3_after_heat_checkpoint', 'finish', '_publish',
         'advance_spatial', 'heat_from_spatial', 'endpoint_from_transport', '_advance_verified', 'forward',
         'advance', 'seal_and_promote', 'publish'}


def main(path):
    stats = pstats.Stats(path).stats
    total = max(item[3] for item in stats.values())
    print('largest cumtime', f'{total:.1f}s', 'entries', len(stats))
    rows = sorted(((cumulative, calls, f'{os.path.basename(filename)}:{line} {name}')
                   for (filename, line, name), (primitive, calls, own, cumulative, callers) in stats.items()
                   if name in NAMES), reverse=True)
    for cumulative, calls, label in rows[:40]:
        print(f'  cum {cumulative:8.2f}s  calls {calls:6d}  {label}')


if __name__ == '__main__':
    main(sys.argv[1])
