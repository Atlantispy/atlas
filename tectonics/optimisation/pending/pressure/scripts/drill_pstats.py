"""Inclusive-time drill-down of one function in a .pstats file (T/ps, read-only).

For the named function (file-name substring + function name), walks its callees and prints
each callee's cumulative seconds attributed from that caller (pstats' per-caller split), to a
depth, largest first, with a cut-off fraction of the root. Also prints the top own-time
functions inside the subtree (approximate: functions reached from the root).
Usage: drill_pstats.py FILE.pstats FILE_SUBSTRING:FUNCTION [--depth 4] [--cut 0.02]
"""
import argparse
import pstats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pstats')
    ap.add_argument('root')
    ap.add_argument('--depth', type=int, default=4)
    ap.add_argument('--cut', type=float, default=0.02)
    args = ap.parse_args()
    stats = pstats.Stats(args.pstats)
    table = stats.stats
    callees = {}
    for func, (_, _, _, _, callers) in table.items():
        for caller, (_, _, _, cum) in callers.items():
            callees.setdefault(caller, []).append((cum, func))
    part, name = args.root.split(':')
    roots = [f for f in table if part in f[0] and f[2] == name]
    if not roots:
        raise SystemExit('no such function')
    short = lambda f: '%s:%d(%s)' % (f[0].replace('\\', '/').rsplit('/', 1)[-1], f[1], f[2])
    reached = set()
    for root in roots:
        total = table[root][3]
        print('ROOT %s calls %d cumulative %.2f s' % (short(root), table[root][1], total))

        def walk(func, depth, seen):
            reached.add(func)
            if depth > args.depth:
                return
            for cum, child in sorted(callees.get(func, ()), reverse=True):
                if cum < args.cut*total or child in seen:
                    continue
                print('%s%-70s %8.2f s %5.1f%%' % ('  '*depth, short(child), cum, 100*cum/total))
                walk(child, depth+1, seen | {child})
        walk(root, 1, {root})
    print('\nTOP OWN TIME IN SUBTREE (whole-profile tottime of reached functions)')
    for func in sorted(reached, key=lambda f: -table[f][2])[:20]:
        print('%-70s %8.2f s own, %9d calls' % (short(func), table[func][2], table[func][1]))


if __name__ == '__main__':
    main()
