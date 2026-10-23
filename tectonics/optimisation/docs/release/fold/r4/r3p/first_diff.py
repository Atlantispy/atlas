"""The first differing cell between two saved heat results, by key and field, with both values (read-only).

    python -B first_diff.py REFERENCE_SAVE_DIR SAVE_DIR

For the stop report after the prep rows gate (rows_equal.py) or r9's cells-ra / cells-ab (cells_keyed.py) has failed.
It is not a gate and not one of the pinned tools; it judges nothing.

How a cell is keyed:
- An exterior row (kind 'exterior', or no kind and a voxel_index) by ('logical', logical_cell_id).
- A collar row with physical_cell_id by ('physical', physical_cell_id).
- A collar row without one (an HCF save) has no cross-composition key. Such rows are paired by equal content; the
  rest are listed as unmatched, with their values.

Prints JSON:
- the keyed cells compared;
- the first differing keyed cell, in the reference's cell order: its key, and each differing field or array with the
  reference value and the value (floats also as hex);
- up to five unmatched cells per side, with their values.
Exit 0 if no difference was found, 1 otherwise.
"""
from collections import Counter
import json
from pathlib import Path
import sys

import numpy as np

IDS = ('cell_id', 'logical_cell_id')


def show(value):
    array = np.asarray(value)
    out = dict(value=array.tolist())
    if array.dtype.kind == 'f':
        out['hex'] = [float(x).hex() for x in array.ravel()]
    return out


def load(directory):
    d = Path(directory)
    table = json.loads((d/'arrays.json').read_text(encoding='utf8'))
    arrays = {name: np.load(d/(name + '.npy'), allow_pickle=False) for name in sorted(table)}
    cells = json.loads((d/'cell_keys.json').read_text(encoding='utf8'))['cells']
    keyed, loose = {}, []
    for i, cell in enumerate(cells):
        kind = cell.get('kind', 'exterior' if 'voxel_index' in cell else 'collar')
        fields = {k: v for k, v in cell.items() if k not in IDS}
        values = {name: array[i] for name, array in arrays.items()}
        if kind == 'exterior':
            keyed[('logical', cell['logical_cell_id'])] = (fields, values)
        elif 'physical_cell_id' in cell:
            keyed[('physical', cell['physical_cell_id'])] = (fields, values)
        else:
            loose.append((cell.get('cell_id'), fields, values))
    return sorted(arrays), keyed, loose


def differences(a, b):
    (fa, va), (fb, vb) = a, b
    out = [dict(field=k, reference=fa.get(k), value=fb.get(k)) for k in sorted(set(fa) | set(fb))
           if fa.get(k) != fb.get(k)]
    for name in sorted(set(va) | set(vb)):
        x, y = va.get(name), vb.get(name)
        if x is None or y is None or np.asarray(x).tobytes() != np.asarray(y).tobytes():
            out.append(dict(array=name, reference=None if x is None else show(x), value=None if y is None else show(y)))
    return out


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    (na, ka, la), (nb, kb, lb) = load(argv[0]), load(argv[1])
    report: dict = dict(array_names_equal=na == nb, keyed_compared=len(set(ka) & set(kb)), first=None)
    for key in ka:
        if key in kb:
            diff = differences(ka[key], kb[key])
            if diff:
                report['first'] = dict(key='%s:%s' % key, differences=diff)
                break

    def content(row):
        _, fields, values = row
        return json.dumps(fields, sort_keys=True), tuple(np.asarray(values[n]).tobytes() for n in sorted(values))
    left = Counter(content(r) for r in la) - Counter(content(r) for r in lb)
    right = Counter(content(r) for r in lb) - Counter(content(r) for r in la)

    def unmatched(rows, extra):
        extra, listed = Counter(extra), []
        for cell_id, fields, values in rows:
            row = content((cell_id, fields, values))
            if extra[row] > 0 and len(listed) < 5:
                extra[row] -= 1
                listed.append(dict(cell_id=cell_id, fields=fields, values={n: show(v) for n, v in values.items()}))
        return listed
    report.update(
        keyed_only=[['%s:%s' % k for k in list(ka.keys() - kb.keys())[:5]],
                    ['%s:%s' % k for k in list(kb.keys() - ka.keys())[:5]]],
        unkeyed_unmatched=[unmatched(la, left), unmatched(lb, right)])
    print(json.dumps(report, indent=1))
    same = (report['first'] is None and na == nb and not any(report['keyed_only'])
            and not any(report['unkeyed_unmatched']))
    return 0 if same else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
