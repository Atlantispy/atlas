"""Two saved heat results compared cell by cell under the cross-composition key (FOLD.md §13 item 6; read-only).

    python -B cells_keyed.py REFERENCE_SAVE_DIR SAVE_DIR [OUT_JSON [EXTERIOR COLLAR]]

Each SAVE_DIR is an arms_r7 child save: <name>.npy, arrays.json, and cell_keys.json, whose key_fields name kind and
physical_cell_id. Each array must have the sha256 that arrays.json records and must hold one value per cell.

How a cell is keyed, by the mesh row's own kind (integration_exterior_mesh.py:655/697):
- An exterior cell is keyed by ('logical', logical_cell_id), a content hash (integration_exterior_mesh.py:693/901).
- A collar cell is keyed by ('physical', physical_cell_id), its geometric cell id (integration_volume.py:358; the
  row field is set at integration_exterior_mesh.py:657).
- cell_id is not used: it renumbers with any package byte change. A collar cell's logical_cell_id is not used
  either: it hashes funding_id.
- Any other kind, a collar cell without physical_cell_id, or a key repeated within one save, fails.

PASS iff all of these hold:
- both saves record kind and physical_cell_id among their key fields;
- the array names agree;
- each save has at least one cell, and every cell of each save is keyed;
- the two key sets are equal, so the mixed-key match covers every cell;
- for each key, the cell's key fields other than cell_id and logical_cell_id are equal, and so is its value in every
  array, bitwise;
- when EXTERIOR and COLLAR are given, the match has exactly that many exterior and collar cells (the case geometry
  has 172 and 64).

The report states the mixed-key match count: exterior, collar, total and cells per save. For the record it also
states whether cell order, cell ids and logical ids are equal, and whether the plain multiset of rows is equal.
Exit 0 iff PASS.
"""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np

IDS = ('cell_id', 'logical_cell_id')


class Refusal(Exception):
    pass


def load(directory):
    d = Path(directory)
    keys = json.loads((d/'cell_keys.json').read_text(encoding='utf8'))
    if not {'kind', 'physical_cell_id'} <= set(keys.get('key_fields', ())):
        raise Refusal('%s: cell_keys.json does not record kind and physical_cell_id among its key fields' % d.name)
    table = json.loads((d/'arrays.json').read_text(encoding='utf8'))
    arrays = {}
    for name, entry in table.items():
        array = np.load(d/(name + '.npy'), allow_pickle=False)
        if sha256(array.tobytes()).hexdigest() != entry['sha256']:
            raise Refusal('%s/%s.npy is not the array arrays.json records' % (d.name, name))
        arrays[name] = array
    cells = keys['cells']
    if not cells or not arrays or any(len(a) != len(cells) for a in arrays.values()):
        raise Refusal('%s: no cells, no arrays, or an array is not one value per cell' % d.name)
    names = sorted(arrays)
    keyed, kinds = {}, Counter()
    for i, cell in enumerate(cells):
        kind = cell.get('kind')
        if kind == 'exterior':
            key = ('logical', cell['logical_cell_id'])
        elif kind == 'collar' and 'physical_cell_id' in cell:
            key = ('physical', cell['physical_cell_id'])
        elif kind == 'collar':
            raise Refusal('%s: cell %d is a collar cell without physical_cell_id' % (d.name, i))
        else:
            raise Refusal('%s: cell %d has kind %r, not exterior or collar' % (d.name, i, kind))
        if key in keyed:
            raise Refusal('%s: key %s:%s is repeated' % (d.name, key[0], str(key[1])[:12]))
        content = json.dumps({k: v for k, v in cell.items() if k not in IDS}, sort_keys=True)
        keyed[key] = (kind, content, tuple(arrays[n][i].tobytes() for n in names))
        kinds[kind] += 1
    return names, keyed, kinds, cells


def compare(ref_dir, dir_, expect=None):
    (na, ka, kinds_a, ca), (nb, kb, kinds_b, cb) = load(ref_dir), load(dir_)
    common = set(ka) & set(kb)
    mismatched = []
    for key in sorted(common):
        (kind_a, content_a, values_a), (kind_b, content_b, values_b) = ka[key], kb[key]
        parts = [part for part, x, y in (('kind', kind_a, kind_b), ('key fields', content_a, content_b),
                                         ('values', values_a, values_b)) if x != y]
        if parts:
            mismatched.append('%s:%s %s' % (key[0], str(key[1])[:12], '+'.join(parts)))
    match = dict(exterior=sum(1 for key in common if ka[key][0] == 'exterior'),
                 collar=sum(1 for key in common if ka[key][0] == 'collar'), total=len(common),
                 cells=[len(ca), len(cb)], unmatched=[len(set(ka) - set(kb)), len(set(kb) - set(ka))])
    rows = [Counter((content, values) for _, content, values in k.values()) for k in (ka, kb)]
    counts_as_expected = expect is None or [match['exterior'], match['collar']] == list(expect)
    ok = na == nb and set(ka) == set(kb) and not mismatched and counts_as_expected
    return dict(status='PASS' if ok else 'FAIL', array_names_equal=na == nb, mixed_key_match=match,
                expected=None if expect is None else dict(exterior=expect[0], collar=expect[1]),
                counts_as_expected=counts_as_expected,
                kinds=[dict(kinds_a), dict(kinds_b)], rows_mismatched=len(mismatched), mismatched=mismatched[:5],
                rows_multiset_equal=rows[0] == rows[1],
                cell_order_equal=[c['cell_id'] for c in ca] == [c['cell_id'] for c in cb],
                cell_ids_equal=sorted(c['cell_id'] for c in ca) == sorted(c['cell_id'] for c in cb),
                logical_ids_equal=(sorted(c['logical_cell_id'] for c in ca)
                                   == sorted(c['logical_cell_id'] for c in cb)))


def main(argv):
    if len(argv) not in (2, 3, 5) or (len(argv) == 5 and not all(a.isdigit() for a in argv[3:])):
        print(__doc__)
        return 2
    try:
        report = compare(argv[0], argv[1], tuple(map(int, argv[3:])) if len(argv) == 5 else None)
    except Refusal as error:
        report = dict(status='FAIL', refusal=str(error))
    print(json.dumps(report))
    if len(argv) >= 3:
        Path(argv[2]).write_text(json.dumps(report, indent=1) + '\n', encoding='utf8', newline='\n')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
