"""Named rows from .prof/.pstats files (T/ps, read-only): ncalls, tottime, cumtime, top callers.

Usage: rows_pstats.py OUT.txt FILE.prof[,FILE2.prof] FILESUB:FUNC [FILESUB:FUNC ...] [--top-under FILESUB:FUNC N]
A FUNC of * matches every function in files containing FILESUB. --top-under prints the N largest
cumulative functions reached from that root (by caller edges), for call-count summaries.
"""
import pstats
import sys


def short(f):
    return '%s:%d(%s)' % (f[0].replace('\\', '/').rsplit('/', 1)[-1], f[1], f[2])


def main():
    out, files, specs = sys.argv[1], sys.argv[2].split(','), sys.argv[3:]
    top = None
    if '--top-under' in specs:
        i = specs.index('--top-under')
        top, specs = (specs[i+1], int(specs[i+2])), specs[:i]+specs[i+3:]
    lines = []
    for path in files:
        stats = pstats.Stats(path)
        table = stats.stats  # noqa
        lines.append('## %s (total %.1f s)' % (path.replace('\\', '/').rsplit('/', 2)[-2:], stats.total_tt))
        for spec in specs:
            sub, name = spec.split(':')
            rows = [f for f in table if sub in f[0] and (name == '*' or f[2] == name)]
            for f in sorted(rows, key=lambda f: -table[f][3])[:12]:
                cc, nc, tt, ct, callers = table[f]
                top_callers = sorted(callers.items(), key=lambda kv: -kv[1][3])[:3]
                lines.append('%-58s ncalls %9d tottime %7.2f cumtime %7.2f | callers: %s' % (
                    short(f), nc, tt, ct, '; '.join('%s %.2fs' % (short(c), v[3]) for c, v in top_callers)))
            if not rows:
                lines.append('%-58s not called' % spec)
        if top:
            sub, name = top[0].split(':')
            roots = [f for f in table if sub in f[0] and f[2] == name]
            callees = {}
            for func, (_, _, _, _, callers) in table.items():
                for caller in callers:
                    callees.setdefault(caller, set()).add(func)
            seen, stack = set(), list(roots)
            while stack:
                f = stack.pop()
                if f in seen:
                    continue
                seen.add(f)
                stack.extend(callees.get(f, ()))
            lines.append('-- top %d cumulative under %s (calls, cum s, own s)' % (top[1], top[0]))
            for f in sorted(seen, key=lambda f: -table[f][3])[:top[1]]:
                lines.append('   %-58s %10d %8.2f %8.2f' % (short(f), table[f][1], table[f][3], table[f][2]))
    with open(out, 'w', encoding='utf8') as stream:
        stream.write('\n'.join(lines)+'\n')
    print('\n'.join(lines[:60]))


if __name__ == '__main__':
    main()
