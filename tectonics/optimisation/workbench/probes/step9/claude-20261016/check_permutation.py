"""Read-only: is the difference between saved heat-control arrays ONE permutation of whole cell rows?

Usage: python -B check_permutation.py SAVED_DIR [SAVED_DIR ...] [--digests CONTROL_JSON ...]

SAVED_DIRs come from heat_control_on_frozen.py child ... SAVE_ARRAYS_DIR; the first is the base.
A cell row is the tuple of every saved array's value at one index, as bytes. For each other dir:
whether the multiset of rows equals the base's (stronger than per-array multisets: the values stay
together), whether the rows are unique (then the permutation is unique), the permutation itself
summarised (fixed points, reversal, equal to another dir's), and whether two dirs are bit-identical.
--digests: control outputs (result['arrays'] = sha256 of each array); each is matched against the
sha256 of every saved dir, so a run whose arrays were not saved is placed in an order class.
"""
import json
import sys
from hashlib import sha256
from pathlib import Path

import numpy as np


def load(directory):
    names = sorted(json.loads((directory/'arrays.json').read_text(encoding='utf8')))
    return {name: np.load(directory/(name+'.npy')) for name in names}


def main():
    argv = sys.argv[1:]
    digest_files = []
    if '--digests' in argv:
        at = argv.index('--digests')
        argv, digest_files = argv[:at], argv[at+1:]
    dirs = [Path(path) for path in argv]
    saved = {d.name: load(d) for d in dirs}
    base_name = dirs[0].name
    base = saved[base_name]
    names = sorted(base)
    count = len(base[names[0]])

    def rows(arrays):
        return [tuple(arrays[name][i].tobytes() for name in names) for i in range(count)]

    base_rows = rows(base)
    unique = len(set(base_rows)) == count
    where = {row: i for i, row in enumerate(base_rows)}
    report = dict(base=base_name, cells=count, arrays=names, base_rows_unique=unique, against={})
    perms = {}
    for name, arrays in saved.items():
        if name == base_name:
            continue
        other = rows(arrays)
        same_multiset = sorted(other) == sorted(base_rows)
        entry = dict(bit_identical=all(arrays[n].tobytes() == base[n].tobytes() for n in names),
                     same_row_multiset=same_multiset)
        if same_multiset and unique:
            perm = [where[row] for row in other]          # other[i] is base[perm[i]]
            perms[name] = perm
            entry.update(fixed_points=sum(1 for i, j in enumerate(perm) if i == j),
                         is_reversal=perm == list(range(count))[::-1],
                         first_moved=[[i, j] for i, j in enumerate(perm) if i != j][:8])
        report['against'][name] = entry
    keys = sorted(perms)
    report['permutations_equal'] = {f'{a}~{b}': perms[a] == perms[b] for k, a in enumerate(keys) for b in keys[k+1:]}
    report['pairwise_bit_identical'] = {
        f'{a}~{b}': all(saved[a][n].tobytes() == saved[b][n].tobytes() for n in names)
        for k, a in enumerate(sorted(saved)) for b in sorted(saved)[k+1:]}
    digests = {name: {n: sha256(arrays[n].tobytes()).hexdigest() for n in names} for name, arrays in saved.items()}
    report['digest_classes'] = {}
    for path in digest_files:
        recorded = json.loads(Path(path).read_text(encoding='utf8')).get('arrays', {})
        report['digest_classes'][Path(path).name] = sorted(
            name for name, table in digests.items() if all(recorded.get(n) == table[n] for n in names)) or 'none'
    print(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
