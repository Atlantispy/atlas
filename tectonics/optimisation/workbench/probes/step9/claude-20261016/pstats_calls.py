"""Read-only: call counts and times from a pstats file for the item 11 call sites.

Usage: python -B pstats_calls.py <file.pstats>
Prints ncalls / tottime / cumtime for the heat finish and native projection entry points, and for
every function whose name suggests endpoint save/seal/promote/publish/commit with cumtime >= 1 s.
Nothing is written.
"""
import os
import pstats
import sys

SITES = (('private_heat_finish_kernel_r10.py', 'finish'), ('private_heat_native_projection_r4.py', 'project'))
WORDS = ('publish', 'seal', 'promote', 'save', 'commit', 'checkpoint', 'endpoint', 'advance_current_interval')


def main(path):
    stats = pstats.Stats(path).stats
    total = max(item[3] for item in stats.values())
    print('largest cumtime', f'{total:.1f}s', 'entries', len(stats))
    rows = []
    for (filename, line, name), (primitive, calls, own, cumulative, callers) in stats.items():
        base = os.path.basename(filename)
        site = any(base == want and name == func for want, func in SITES)
        word = cumulative >= 1 and any(token in name.lower() for token in WORDS)
        if site or word:
            rows.append((cumulative, calls, primitive, own, f'{base}:{line} {name}', callers))
    for cumulative, calls, primitive, own, label, callers in sorted(rows, reverse=True)[:25]:
        print(f'  cum {cumulative:8.1f}s  own {own:7.1f}s  calls {calls}/{primitive}  {label}')
        for (filename, line, name), detail in sorted(callers.items(), key=lambda kv: -kv[1][3])[:2]:
            print(f'      <- {os.path.basename(filename)}:{line} {name}  calls {detail[1]}  cum {detail[3]:.1f}s')


if __name__ == '__main__':
    main(sys.argv[1])
