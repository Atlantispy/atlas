"""Read-only pstats breakdown: for each root function (file suffix:line name), list its direct callees by cumulative
time inside the root (callee cumtime attributed via the caller->callee edge), recursively to a depth, plus the top
callers of a named hot leaf. Usage: python -B pstats_tree_r1.py PSTATS --root SUFFIX:LINE:NAME [--root ...]
[--depth 3] [--min 0.05] [--leaf SUFFIX:LINE:NAME]"""
import argparse
import pstats


def match(key, spec):
    path, line, name = spec.rsplit(':', 2)
    return key[0].replace(chr(92), '/').endswith(path) and key[1] == int(line) and key[2] == name


def label(key):
    return '%s:%d %s' % (key[0].replace(chr(92), '/').rsplit('/', 1)[-1], key[1], key[2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pstats')
    ap.add_argument('--root', action='append', default=[])
    ap.add_argument('--leaf', action='append', default=[])
    ap.add_argument('--depth', type=int, default=3)
    ap.add_argument('--min', type=float, default=0.05)
    a = ap.parse_args()
    st = pstats.Stats(a.pstats).stats  # key -> (cc, nc, tt, ct, callers{caller: (cc, nc, tt, ct)})
    callees = {}
    for key, (_, _, _, _, callers) in st.items():
        for caller, edge in callers.items():
            callees.setdefault(caller, []).append((key, edge))

    def walk(key, depth, indent):
        rows = sorted(callees.get(key, []), key=lambda r: -r[1][3])
        for child, (cc, nc, tt, ct) in rows:
            if ct < a.min:
                continue
            print('%s%8.2fs cum %8.2fs self %9d calls  %s' % (indent, ct, tt, nc, label(child)))
            if depth > 1 and child != key:
                walk(child, depth-1, indent+'  ')

    for spec in a.root:
        keys = [k for k in st if match(k, spec)]
        for key in keys:
            cc, nc, tt, ct, _ = st[key]
            print('ROOT %s: %d calls, cum %.2fs, self %.2fs' % (label(key), nc, ct, tt))
            walk(key, a.depth, '  ')
        if not keys:
            print('ROOT %s: not found' % spec)
    for spec in a.leaf:
        for key in [k for k in st if match(k, spec)]:
            cc, nc, tt, ct, callers = st[key]
            print('LEAF %s: %d calls, cum %.2fs; top callers:' % (label(key), nc, ct))
            for caller, (c1, n1, t1, c2) in sorted(callers.items(), key=lambda r: -r[1][3])[:12]:
                print('  %8.2fs cum %9d calls  %s' % (c2, n1, label(caller)))


if __name__ == '__main__':
    main()
