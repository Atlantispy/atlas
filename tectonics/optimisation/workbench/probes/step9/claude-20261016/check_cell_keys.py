"""Read-only: the frozen heat control's third criterion, cells matched by a provenance-free key.

Usage: python -B check_cell_keys.py BASE_DIR OTHER_DIR [OTHER_DIR ...] [--key NAME] [--contrast] [--report PATH]

Each DIR is saved by heat_control_on_frozen.py child ... SAVE_ARRAYS_DIR: <array>.npy,
arrays.json, cell_keys.json (per cell, in the result's order, its mesh row's key fields) and
frozen_check.json (the child's verdict and the control's own SHA-256 of every array).
Criteria (Coordinator D-l, 16 Oct 2026):
  1. PRIMARY, key-matched: every cell of BASE is found in OTHER by --key (default
     logical_cell_id), keys present, not None and unique on both sides, the same key set, and
     every array value of the matched cell bit-identical. Unlike the row multiset this detects
     two cells that swap values.
  2. SECONDARY, the whole-row multiset (check_permutation.py / tuple_multiset.py).
  3. Positional digests only between reruns of one composition (reported, never required).
Also prints each run's order digests: sha256 of its key sequence and of its cell_id sequence,
the values D-l records in run.json so that an order change is visible.

FAIL CLOSED (review 16 Oct 2026). Every DIR must hold the complete evidence of a PASSing child:
frozen_check.json status PASS; every array named in arrays.json loaded (no pickles) with the
control's SHA-256; one array entry and one key entry per cell; the control's cell count;
mesh_row_order_equal True. There must be at least one OTHER_DIR, and the names must differ.
Exit status: 0 PASS; 1 FAIL (complete evidence, a criterion not met); 2 INVALID (incomplete or
inconsistent evidence, a missing arm or file, bad arguments, an existing report).
--contrast: the key is a contrast (cell_id binds provenance, so it may differ between routes);
its criteria are reported, not required: exit 0 when every arm's evidence is valid, else 2.
--report PATH: write the report to PATH (exclusive creation; an existing file refuses) instead of
stdout. A one-line verdict goes to stderr.
"""
import json
import re
import sys
from hashlib import sha256
from pathlib import Path

import numpy as np

ARRAY_NAME = re.compile(r'[A-Za-z0-9_]+')


class Invalid(Exception):
    """The evidence of an arm, or the arguments, cannot support a verdict."""


def _need(condition, message):
    if not condition:
        raise Invalid(message)


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf8'))
    except (OSError, ValueError) as error:
        raise Invalid('%s: %s' % (path.name, error)) from None


def load(directory):
    """(names, cells, rows) of one saved arm; Invalid when its evidence is incomplete or inconsistent."""
    _need(directory.is_dir(), 'no such directory')
    table = _read_json(directory/'arrays.json')
    keys = _read_json(directory/'cell_keys.json')
    verdict = _read_json(directory/'frozen_check.json')
    _need(type(verdict) is dict and verdict.get('status') == 'PASS',
          'the child did not pass: %r' % (verdict.get('status') if type(verdict) is dict else verdict,))
    _need(type(table) is dict and len(table) > 0, 'arrays.json lists no arrays')
    digests = verdict.get('arrays')
    _need(type(digests) is dict and set(digests) == set(table), 'frozen_check.json arrays differ from arrays.json')
    names = sorted(table)
    arrays = {}
    for name in names:
        _need(ARRAY_NAME.fullmatch(name) is not None, 'array name %r is not plain' % (name,))
        try:
            array = np.load(directory/(name+'.npy'), allow_pickle=False)
        except (OSError, ValueError) as error:
            raise Invalid('%s.npy: %s' % (name, error)) from None
        _need(array.ndim >= 1, '%s.npy has no cell axis' % name)
        _need(sha256(array.tobytes()).hexdigest() == digests[name], '%s.npy is not the control result (SHA-256)' % name)
        arrays[name] = array
    _need(type(keys) is dict and type(keys.get('cells')) is list, 'cell_keys.json has no cell list')
    cells = keys['cells']
    count = len(cells)
    _need(count > 0, 'no cells')
    _need(all(type(cell) is dict for cell in cells), 'a cell entry is not a mapping')
    _need(all(len(arrays[name]) == count for name in names), 'cell keys and arrays differ in length')
    _need(verdict.get('cell_count') == count, 'cell count %r, the control has %r' % (count, verdict.get('cell_count')))
    _need(keys.get('mesh_row_order_equal') is True, 'mesh_row_order_equal is %r' % (keys.get('mesh_row_order_equal'),))
    rows = [tuple(arrays[name][i].tobytes() for name in names) for i in range(count)]
    return names, cells, rows


def digest(values):
    return sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()


def _key(cell, key):
    """The canonical form of a cell's key, or None when it is missing or None."""
    value = cell.get(key)
    return None if value is None else json.dumps(value, sort_keys=True, separators=(',', ':'))


def _index(cells, rows, key):
    """({key: row}, cells whose key is missing or None, cells whose key repeats an earlier one)."""
    index, missing, repeated = {}, 0, 0
    for cell, row in zip(cells, rows, strict=True):
        value = _key(cell, key)
        if value is None:
            missing += 1
        elif value in index:
            repeated += 1
        else:
            index[value] = row
    return index, missing, repeated


def _arguments(argv):
    argv = list(argv)
    key, contrast, report = 'logical_cell_id', False, None
    dirs = []
    while argv:
        item = argv.pop(0)
        if item == '--key':
            _need(argv and not argv[0].startswith('--'), '--key needs a name')
            key = argv.pop(0)
        elif item == '--report':
            _need(argv and not argv[0].startswith('--'), '--report needs a path')
            report = Path(argv.pop(0))
        elif item == '--contrast':
            contrast = True
        elif item.startswith('--'):
            raise Invalid('unknown option %s' % item)
        else:
            dirs.append(Path(item))
    _need(len(dirs) >= 2, 'give the base and at least one other directory (%d given)' % len(dirs))
    _need(len({d.name for d in dirs}) == len(dirs), 'directory names must differ')
    _need(report is None or not report.exists(), 'the report exists: %s' % report)
    return key, contrast, report, dirs


def compare(dirs, key, contrast):
    """The report; its 'verdict' is PASS, FAIL or INVALID."""
    report: dict = dict(key=key, contrast=contrast, base=dirs[0].name, cells=None, order_digests={},
                        invalid={}, against={})
    loaded = {}
    for directory in dirs:
        try:
            loaded[directory.name] = load(directory)
        except Invalid as error:
            report['invalid'][directory.name] = '%s: %s' % (directory, error)
    for name, (_, run_cells, _) in loaded.items():
        report['order_digests'][name] = dict(key_sequence=digest([cell.get(key) for cell in run_cells]),
                                             cell_id_sequence=digest([cell.get('cell_id') for cell in run_cells]))
    if report['base'] in loaded:
        names, cells, rows = loaded[report['base']]
        report['cells'] = len(rows)
        base, base_missing, base_repeated = _index(cells, rows, key)
        for name, (other_names, other_cells, other_rows) in loaded.items():
            if name == report['base']:
                continue
            other, missing, repeated = _index(other_cells, other_rows, key)
            differing = sorted(k for k in set(base) & set(other) if base[k] != other[k])
            entry: dict = dict(array_names_equal=other_names == names, cells=len(other_rows),
                               base_missing_keys=base_missing, base_repeated_keys=base_repeated,
                               missing_keys=missing, repeated_keys=repeated, same_key_set=set(base) == set(other),
                               missing_in_other=len(set(base)-set(other)), extra_in_other=len(set(other)-set(base)),
                               matched_cells_differing=len(differing), first_differing=differing[:5],
                               row_multiset_equal=sorted(rows) == sorted(other_rows),
                               positional_identical=rows == other_rows)
            entry['primary'] = ('PASS' if entry['array_names_equal'] and len(other_rows) == len(rows)
                                and not (base_missing or base_repeated or missing or repeated)
                                and entry['same_key_set'] and not differing else 'FAIL')
            entry['secondary'] = 'PASS' if entry['row_multiset_equal'] else 'FAIL'
            report['against'][name] = entry
    if report['invalid'] or not report['against']:
        report['verdict'] = 'INVALID'
    elif all(entry['primary'] == entry['secondary'] == 'PASS' for entry in report['against'].values()):
        report['verdict'] = 'PASS'
    else:
        report['verdict'] = 'FAIL'
    return report


def main(argv):
    try:
        key, contrast, path, dirs = _arguments(argv)
    except Invalid as error:
        print('check_cell_keys: INVALID: %s' % error, file=sys.stderr)
        return 2
    report = compare(dirs, key, contrast)
    code = {'PASS': 0, 'FAIL': 0 if contrast else 1}.get(report['verdict'], 2)
    report['exit_status'] = code
    text = json.dumps(report, indent=1)
    if path is None:
        print(text)
    else:
        try:
            with open(path, 'x', encoding='utf8') as handle:
                handle.write(text+'\n')
        except OSError as error:
            print('check_cell_keys: INVALID: cannot write the report: %s' % error, file=sys.stderr)
            return 2
    print('check_cell_keys: key=%s%s verdict=%s exit=%d invalid=%s' % (
        key, ' (contrast)' if contrast else '', report['verdict'], code, sorted(report['invalid'])), file=sys.stderr)
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
