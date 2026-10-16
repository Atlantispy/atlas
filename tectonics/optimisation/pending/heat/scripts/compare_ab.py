"""Read-only D-b check of two proof arms saved by ab_heat.py (OUTDIR/arm-K/).

Usage: python -B compare_ab.py ARM_DIR_A ARM_DIR_B [ROOT_A ROOT_B]

1. Every array is bit-identical (same names, shapes, dtypes and bytes).
2. Metadata: the canonical JSON is parsed and walked. Every differing leaf is listed with
   its path. A leaf is "digest" when both sides are 64-hex sha256 strings, and "path"
   when the strings become equal after ROOT_A is replaced by ROOT_B (in plain and
   JSON-escaped spellings). Any other difference is NUMERIC/OTHER and fails.
Prints a compact summary; exit 0 only when arrays are identical and every metadata
difference is digest or path.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np

HEX = re.compile(r'^[0-9a-f]{64}$')


def leaves(value, path=''):
    if isinstance(value, dict):
        for key in value:
            yield from leaves(value[key], f'{path}/{key}')
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from leaves(item, f'{path}[{i}]')
    else:
        yield path, value


def main():
    a, b = Path(sys.argv[1]), Path(sys.argv[2])
    roots = sys.argv[3:5]
    ok = True
    na = json.loads((a/'arrays.json').read_text(encoding='utf8'))
    nb = json.loads((b/'arrays.json').read_text(encoding='utf8'))
    if list(na) != list(nb):
        print('ARRAY NAMES DIFFER', list(na), list(nb))
        ok = False
    for name in na:
        x, y = np.load(a/(name+'.npy')), np.load(b/(name+'.npy'))
        same = x.dtype == y.dtype and x.shape == y.shape and x.tobytes() == y.tobytes()
        print(f'array {name} {x.dtype} {list(x.shape)}: {"bit-identical" if same else "DIFFERS"}')
        ok &= same
    ma, mb = (a/'legacy_metadata.json').read_bytes(), (b/'legacy_metadata.json').read_bytes()
    print('metadata bytes', len(ma), len(mb), 'identical' if ma == mb else 'differ')
    ja, jb = json.loads(ma), json.loads(mb)
    la, lb = dict(leaves(ja)), dict(leaves(jb))
    if list(la) != list(lb):
        only = sorted(set(la) ^ set(lb))
        print('STRUCTURE DIFFERS:', len(only), only[:10])
        ok = False
    subs = []
    if roots:
        ra, rb = roots
        subs = [(ra, rb), (ra.replace('\\', '\\\\'), rb.replace('\\', '\\\\')), (ra.replace('\\', '/'), rb.replace('\\', '/'))]
    kinds = {}
    examples = {}
    for path in la:
        if path not in lb or la[path] == lb[path]:
            continue
        x, y = la[path], lb[path]
        if type(x) is str and type(y) is str and HEX.match(x) and HEX.match(y):
            kind = 'digest'
        elif type(x) is str and type(y) is str and subs and _sub(x, subs) == y:
            kind = 'path'
        else:
            kind = 'NUMERIC/OTHER'
            ok = False
        kinds[kind] = kinds.get(kind, 0)+1
        examples.setdefault(kind, []).append((path, str(x)[:100], str(y)[:100]))
    print('metadata differing leaves by kind:', kinds)
    for kind, rows in examples.items():
        print(f'  {kind}: first of {len(rows)}')
        for row in rows[:8]:
            print('    ', row[0], '|', row[1], '|', row[2])
        generic = sorted({re.sub(r'\[\d+\]', '[]', r[0]) for r in rows})
        print('    distinct paths:', generic[:20])
    print('D-b PASS' if ok else 'D-b FAIL')
    sys.exit(0 if ok else 1)


def _sub(text, subs):
    for old, new in subs:
        text = text.replace(old, new)
    return text


if __name__ == '__main__':
    main()
