"""The heat call's numbers per cell are unchanged between two saved results (read-only).

    python -B rows_equal.py REFERENCE_SAVE_DIR SAVE_DIR

Each SAVE_DIR is an HCF child SAVE_ARRAYS_DIR (<name>.npy, arrays.json, cell_keys.json); each array must have the
sha256 its arrays.json records. A cell's row is its key fields other than the two identities (voxel_index,
radial_band, chart) plus its value in each of the five arrays, bitwise. PASS iff the two results have the same array
names and the same multiset of rows. The cell identities (cell_id, logical_cell_id) and hence the result's cell order
are reported, not required: p20c-r2's partition_routing_patch (Plan 18) changes them for the same rows (r2p/bis,
23 Oct). Exit 0 iff PASS.
"""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np

IDS = ('cell_id', 'logical_cell_id')


def load(directory):
    d = Path(directory)
    table = json.loads((d/'arrays.json').read_text(encoding='utf8'))
    arrays = {}
    for name, entry in table.items():
        array = np.load(d/(name + '.npy'))
        if sha256(array.tobytes()).hexdigest() != entry['sha256']:
            raise SystemExit('%s/%s.npy is not the array arrays.json records' % (d.name, name))
        arrays[name] = array
    cells = json.loads((d/'cell_keys.json').read_text(encoding='utf8'))['cells']
    if any(len(a) != len(cells) for a in arrays.values()):
        raise SystemExit('%s: an array is not one value per cell' % d.name)
    names = sorted(arrays)
    rows = Counter((json.dumps({k: v for k, v in c.items() if k not in IDS}, sort_keys=True),)
                   + tuple(arrays[n][i].tobytes() for n in names) for i, c in enumerate(cells))
    return names, rows, cells


def main(ref_dir, dir_):
    (na, ra, ca), (nb, rb, cb) = load(ref_dir), load(dir_)
    report = dict(array_names_equal=na == nb, cells=[len(ca), len(cb)], rows_equal=na == nb and ra == rb,
                  distinct_rows=len(ra), cell_order_equal=[c['cell_id'] for c in ca] == [c['cell_id'] for c in cb],
                  cell_ids_equal=sorted(c['cell_id'] for c in ca) == sorted(c['cell_id'] for c in cb),
                  logical_ids_equal=sorted(c['logical_cell_id'] for c in ca) == sorted(c['logical_cell_id'] for c in cb))
    print(json.dumps(report))
    return 0 if report['rows_equal'] else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
