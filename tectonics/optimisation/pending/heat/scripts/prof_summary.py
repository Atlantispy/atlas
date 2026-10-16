"""Read-only: merge worker cProfile files and print a compact summary.

Usage: python -B prof_summary.py DIR [--top N] [--callers SUBSTR ...] [--json OUT]
- per-module self-time shares (private_heat_* by file, builtins, gmpy2 and the rest)
- top N functions by self time and by cumulative time (file:line function, calls)
- for each --callers SUBSTR: the callers of matching functions, with call counts and time
"""
import argparse
import json
import pstats
from collections import defaultdict
from pathlib import Path


def label(func):
    file, line, name = func
    base = Path(file).name if file not in ('~', '') else '~'
    return f'{base}:{line}:{name}'


def module(func):
    file, _, name = func
    if file == '~':
        if 'gmpy2' in name or 'mpz' in name or 'mpq' in name or 'mpfr' in name:
            return 'gmpy2 (C)'
        return 'builtins: ' + name.split(' of ')[0].strip('<>')[:40]
    stem = Path(file).stem
    return stem if stem.startswith('private_heat_') else 'other: ' + stem


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dir')
    ap.add_argument('--top', type=int, default=25)
    ap.add_argument('--callers', nargs='*', default=[])
    ap.add_argument('--json')
    args = ap.parse_args()
    files = sorted(str(p) for p in Path(args.dir).glob('worker-*.prof'))
    st = pstats.Stats(*files)
    total = sum(v[2] for v in st.stats.values())
    print(f'{len(files)} worker profiles, total self time {total:.1f} s')
    mods = defaultdict(float)
    for func, (cc, nc, tt, ct, callers) in st.stats.items():
        mods[module(func)] += tt
    print('self time by module (top 18):')
    for m, t in sorted(mods.items(), key=lambda x: -x[1])[:18]:
        print(f'  {100*t/total:5.1f}%  {t:8.1f} s  {m}')
    rows = [(label(f), nc, tt, ct) for f, (cc, nc, tt, ct, _) in st.stats.items()]
    print(f'top {args.top} by self time:')
    for lab, nc, tt, ct in sorted(rows, key=lambda r: -r[2])[:args.top]:
        print(f'  {tt:8.1f} s self {ct:8.1f} s cum {nc:>10} calls  {lab}')
    print(f'top {args.top} by cumulative time (private_heat only):')
    for lab, nc, tt, ct in sorted((r for r in rows if r[0].startswith('private_heat_')), key=lambda r: -r[3])[:args.top]:
        print(f'  {ct:8.1f} s cum {tt:8.1f} s self {nc:>10} calls  {lab}')
    for sub in args.callers:
        for func, (cc, nc, tt, ct, callers) in st.stats.items():
            if sub in label(func):
                print(f'callers of {label(func)} ({nc} calls, {tt:.1f} s self, {ct:.1f} s cum):')
                for caller, val in sorted(callers.items(), key=lambda x: -x[1][3])[:8]:
                    print(f'    {val[1]:>10} calls {val[3]:8.1f} s cum  {label(caller)}')
    if args.json:
        Path(args.json).write_text(json.dumps(dict(total=total, modules=dict(mods),
            top=[r for r in sorted(rows, key=lambda r: -r[2])[:200]]), indent=1), encoding='utf8')


if __name__ == '__main__':
    main()
