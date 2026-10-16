"""Read-only: compare heat-control arrays saved by heat_control_on_frozen.py child (SAVE_ARRAYS_DIR).

Usage: python -B compare_saved_arrays.py DIR_A DIR_B [DIR_C ...]

For every array name present in all directories, against DIR_A: bit-identical; equal as a multiset
(the same values in another order); else the largest absolute and relative difference and the count
of differing entries. Prints one line per (directory, array).
"""
import json
import sys
from pathlib import Path

import numpy as np


def main():
    dirs = [Path(path) for path in sys.argv[1:]]
    names = set(json.loads((dirs[0]/'arrays.json').read_text(encoding='utf8')))
    for other in dirs[1:]:
        names &= set(json.loads((other/'arrays.json').read_text(encoding='utf8')))
    base = {name: np.load(dirs[0]/(name+'.npy')) for name in sorted(names)}
    for other in dirs[1:]:
        for name in sorted(names):
            a, b = base[name], np.load(other/(name+'.npy'))
            if a.shape != b.shape:
                print(f'{other.name} {name}: shape {a.shape} vs {b.shape}')
                continue
            if a.tobytes() == b.tobytes():
                verdict = 'bit-identical'
            elif np.array_equal(np.sort(a, axis=None), np.sort(b, axis=None)):
                verdict = 'same values in another order (permutation)'
            else:
                diff = np.abs(a.astype(np.float64)-b.astype(np.float64))
                scale = np.maximum(np.abs(a.astype(np.float64)), 1e-300)
                verdict = (f'VALUES DIFFER: {int(np.count_nonzero(diff))}/{diff.size} entries, '
                           f'max abs {diff.max():.3e}, max rel {(diff/scale).max():.3e}')
            print(f'{other.name} {name} {list(a.shape)}: {verdict}')


if __name__ == '__main__':
    main()
