"""S3 (backlog item 12): carried rows read by item export only the fields read. Helper-only.

Builds r1/ from the pinned composed helpers:
- spatial_validation_patch.py: _LazyRow/_LazyExact after _key_value; _StartRows and _CarriedRows
  __getitem__ return a _LazyRow (get() unchanged); docstrings say so;
- test_d1b_carried_start.py: assert_exact checks get() (the whole row, unchanged type) and the
  item read (a _LazyRow) against the pre-D1-B rows, strictly;
- test_s3_lazy_rows.py: copied from src/.
Every seam must occur exactly once. Writes r1/, r1-diffs/ and build.log beside this script.

Usage: python -B build_s3.py COMPOSED_HELPERS_DIR
"""
import difflib
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT, DIFFS = HERE/'r1', HERE/'r1-diffs'
SVP, D1B, NEW = 'spatial_validation_patch.py', 'test_d1b_carried_start.py', 'test_s3_lazy_rows.py'
PINS = {SVP: '556f2242', D1B: 'aef680d2'}

LAZY = '''

# S3 (backlog item 12, 16 Oct 2026): a carried row read by item exports only
# the fields read. The owner's close_graph reads one field of every carried row
# per pass (volume_m3; geometry_volume_error_m3; exact[name]) and its transport
# reads prior rows' volume_m3, while a whole-row export decodes every field
# (IV1: 0.253 ms a row; volume_m3 alone 0.126 ms, exact[name] 0.186 ms). get()
# keeps the whole row: transport reads a row's volume and all of its exact
# values, which one whole export serves more cheaply than single fields.
_ROW_FIELDS = frozenset(('volume_m3', 'geometry_volume_error_m3'))


def _field_value(field):
    """One field's exact decoded value, under the whole-row export's bounds."""
    owned = (field.scalar(max_owned_bytes=ROW_BYTES) if field.kind == 'scalar' else
             field.export(max_logical_bytes=ROW_BYTES, max_owned_bytes=ROW_BYTES))
    with owned:
        return owned.value


class _LazyRow(Mapping):
    """A carried row read by item: single-field exports, else the whole row (S3).

    row['volume_m3'] and row['geometry_volume_error_m3'] export that field
    alone, and row['exact'][name] exports exact.<name> alone. Each returns the
    value the whole-row export holds there (the same canonical bytes through
    the same JSON decode). A row wider than ROW_BYTES refuses with the
    whole-row export's logical-bound error before any field is read. When a
    field is absent (or exact is not an object) the whole row answers, so the
    error is the row dictionary's. Every other read (another key, get,
    membership, iteration, length, views, equality, repr) exports the whole
    row once, exactly as before S3 (copy_row for a carried child), and later
    reads use it, so its types, booking and errors are unchanged.
    """
    __slots__ = ('_at', '_child', '_start', '_whole')

    def __init__(self, start, at, child=_MISSING):
        self._start, self._at, self._child, self._whole = start, at, child, None

    def _row(self):
        if self._whole is None:
            whole = self._start._row(self._at)
            self._whole = whole if self._child is _MISSING else copy_row(whole, cell_id=self._child)
        return self._whole

    def _field(self, name, inner=None):
        """row[name], or row[name][inner], from that field alone; _MISSING if the whole row must answer."""
        with self._start._cells.at(self._at) as row, ExitStack() as stack:
            # The whole-row export's first refusal, kept for a row read field by field.
            if row._logical_length() > ROW_BYTES:
                raise ContractError('logical export bound exceeded')
            try:
                field = stack.enter_context(row.field(name))
                if inner is not None:
                    if field.kind != 'object':
                        return _MISSING
                    field = stack.enter_context(field.field(inner))
            except KeyError:
                return _MISSING
            return _field_value(field)

    def __getitem__(self, name):
        if self._whole is None and type(name) is str:
            if name in _ROW_FIELDS:
                value = self._field(name)
                if value is not _MISSING:
                    return value
            elif name == 'exact':
                return _LazyExact(self)
        return self._row()[name]

    def get(self, name, default=None):
        return self._row().get(name, default)

    def __contains__(self, name):
        return name in self._row()

    def __iter__(self):
        return iter(self._row())

    def __reversed__(self):
        return reversed(self._row())

    def __len__(self):
        return len(self._row())

    def keys(self):
        return self._row().keys()

    def items(self):
        return self._row().items()

    def values(self):
        return self._row().values()

    def __eq__(self, other):
        return self._row() == (other._row() if type(other) is _LazyRow else other)

    def __repr__(self):
        return repr(self._row())


class _LazyExact(Mapping):
    """row['exact'] of a _LazyRow: [name] exports exact.<name> alone; any other read is the whole row's."""
    __slots__ = ('_parent',)

    def __init__(self, parent):
        self._parent = parent

    def _exact(self):
        return self._parent._row()['exact']

    def __getitem__(self, name):
        if self._parent._whole is None and type(name) is str:
            value = self._parent._field('exact', name)
            if value is not _MISSING:
                return value
        return self._exact()[name]

    def get(self, name, default=None):
        return self._exact().get(name, default)

    def __contains__(self, name):
        return name in self._exact()

    def __iter__(self):
        return iter(self._exact())

    def __reversed__(self):
        return reversed(self._exact())

    def __len__(self):
        return len(self._exact())

    def keys(self):
        return self._exact().keys()

    def items(self):
        return self._exact().items()

    def values(self):
        return self._exact().values()

    def __eq__(self, other):
        return self._exact() == (other._exact() if type(other) is _LazyExact else other)

    def __repr__(self):
        return repr(self._exact())
'''

SVP_EDITS = (
    ("        return owned.value\n\n\nclass _StartRows(Mapping):\n",
     "        return owned.value\n" + LAZY + "\n\nclass _StartRows(Mapping):\n"),
    ("    reader drops it; membership, length and key iteration never decode a row.\n",
     "    reader drops it; membership, length and key iteration never decode a row.\n"
     "    S3: an item read returns a _LazyRow, which exports only the fields read;\n"
     "    get() returns the whole row as before.\n"),
    ("    def __getitem__(self, key):\n        return self._row(self._index[key])\n",
     "    def __getitem__(self, key):\n        return _LazyRow(self, self._index[key])\n"),
    ("    dict(old, cell_id=child). Insertion order is the native carried order.\n",
     "    dict(old, cell_id=child). Insertion order is the native carried order.\n"
     "    S3: an item read returns a _LazyRow of the parent's position; its whole\n"
     "    row (any read other than a single field) is that copy_row.\n"),
    ("    def __getitem__(self, child):\n"
     "        return copy_row(self._start._row(self._parents[child]), cell_id=child)\n",
     "    def __getitem__(self, child):\n"
     "        return _LazyRow(self._start, self._parents[child], child)\n"),
)

D1B_EDITS = (
    ('''    def assert_exact(self, before, compact):
        """D1-B against the pre-D1-B compact route: identical in every observable."""
        self.assertIs(type(before), dict)
        self.assertEqual(list(compact), list(before))
        for key, row in before.items():
            self.assertIs(type(compact[key]), type(row))
            self.assertEqual(list(compact[key].items()), list(row.items()))
''', '''    def assert_exact(self, before, compact):
        """D1-B against the pre-D1-B compact route: identical in every observable.

        S3: get() is the whole row, of the pre-S3 type; an item read is a
        _LazyRow whose every read equals the pre-D1-B row, strictly.
        """
        self.assertIs(type(before), dict)
        self.assertEqual(list(compact), list(before))
        for key, row in before.items():
            whole = compact.get(key)
            self.assertIs(type(whole), type(row))
            self.assertEqual(list(whole.items()), list(row.items()))
            same(self, whole, row)
            lazy = compact[key]
            self.assertIs(type(lazy), V._LazyRow)
            for name in ('volume_m3', 'geometry_volume_error_m3'):
                same(self, compact[key][name], row[name])
            for name, value in row['exact'].items():
                same(self, compact[key]['exact'][name], value)
            same(self, list(lazy.items()), list(row.items()))
'''),
    ('''def cell(i, *, history=0, cell_id=None):
''', '''def same(test, a, b):
    """Strict equality: equal values of the same types all the way down (S3)."""
    test.assertIs(type(a), type(b), (a, b))
    if isinstance(b, dict):
        test.assertEqual(list(a), list(b))
        for key in b:
            same(test, a[key], b[key])
    elif isinstance(b, (list, tuple)):
        test.assertEqual(len(a), len(b))
        for x, y in zip(a, b):
            same(test, x, y)
    else:
        test.assertEqual(repr(a), repr(b))


def cell(i, *, history=0, cell_id=None):
'''),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def edit(text, edits, label):
    for old, new in edits:
        count = text.count(old)
        if count != 1:
            sys.exit('%s: seam count %d: %r' % (label, count, old[:70]))
        text = text.replace(old, new)
    return text


def main():
    helpers = Path(sys.argv[1])
    log = []
    for name, pin in PINS.items():
        got = sha(helpers/name)
        if not got.startswith(pin):
            sys.exit('%s: sha %s, pinned %s' % (name, got[:8], pin))
        log.append('base %s %s' % (name, got))
    if OUT.exists() or DIFFS.exists():
        sys.exit('r1/ or r1-diffs/ exists; remove it first')
    OUT.mkdir()
    DIFFS.mkdir()
    for name, edits in ((SVP, SVP_EDITS), (D1B, D1B_EDITS)):
        base = (helpers/name).read_text(encoding='utf8')
        text = edit(base, edits, name)
        compile(text, name, 'exec')
        (OUT/name).write_text(text, encoding='utf8', newline='\n')
        diff = ''.join(difflib.unified_diff(base.splitlines(True), text.splitlines(True),
                                            'a/'+name, 'b/'+name))
        (DIFFS/(name[:-3]+'.diff')).write_text(diff, encoding='utf8', newline='\n')
        log.append('r1 %s %s (diff %d lines)' % (name, sha(OUT/name), diff.count('\n')))
    shutil.copyfile(HERE/'src'/NEW, OUT/NEW)
    log.append('r1 %s %s (new)' % (NEW, sha(OUT/NEW)))
    (HERE/'build.log').write_text('\n'.join(log)+'\n', encoding='utf8')
    print('\n'.join(log))


if __name__ == '__main__':
    main()
