"""S3 (backlog item 12): carried rows read by item export single fields, exactly.

On the same compact rows, against get() (the whole-row export, unchanged since D1-B):
- each single-field read (volume_m3, geometry_volume_error_m3, exact[name]) is strictly
  equal (same types all the way down) and exports neither the whole row nor a copy;
- every other read (another key, get, membership, iteration, length, views, equality,
  repr) is the whole row's, from one whole export kept on the row;
- absent fields, non-object exact values, non-string keys, absent cells and over-wide
  rows fail with the whole row's error type and arguments;
- booking returns to its base after each read and when the mapping is dropped;
- the owner's close_graph and transport row reads, checked verbatim against the owner
  source, give identical results on item-read and whole rows.
"""
from fractions import Fraction as Q
import gc
import re
import unittest
from unittest.mock import patch

from compact_contracts import ContractError
from test_spatial_compact_cells import I, O, RT, V, WorkBudget, create_retained_scope
from test_d1b_carried_start import cell, same

B_NAME = 'material_quadrature_m3'
FIELDS = ('volume_m3', 'geometry_volume_error_m3')
# The owner's reads of carried/previous rows, verbatim (integration_spatial_owner).
OWNER_READS = (
    "starts = {key: _q(row['volume_m3']) for key, row in carried.items()}",
    "errors = {key: tuple(map(_q, row['geometry_volume_error_m3']))\n"
    "                      for key, row in carried.items()}",
    "_q(carried[key]['exact'][B_NAME]) if key in carried else Q(0))",
    "_q(previous[key]['volume_m3']) if key in previous else",
    "before = previous.get(row['cell_id'])",
    "values = {k: _q(v) for k, v in before['exact'].items()}",
    "any(map(_q, before['exact'].values()))",
)


def full(i, **changes):
    row = cell(i)
    row['exact'][B_NAME] = O._enc(Q(i+1, 7))
    row.update(changes)
    return row


def varied():
    """Small rows, a row over the 32 KiB small-row decode, a field over it, rich exact values, a duplicate id."""
    rows = [full(i) for i in range(5)]
    rows.append(full(5, history='h'*40000))
    rows.append(full(6, geometry_volume_error_m3=[O._enc(j) for j in range(3000)]))
    rows.append(full(7, exact={B_NAME: O._enc(Q(-3, 11)), 'mass_kg': O._enc(0),
                               'nested': {'z': [1, 'b', None, True, False, 2**80], 'a': {'q': 'ü∂'}},
                               'text': 'é'}))
    rows.append(full(8, volume_m3=7, geometry_volume_error_m3=None))
    rows.append(full(9, cell_id=rows[1]['cell_id'], volume_m3=O._enc(99)))
    return rows


class S3LazyRowTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='s3-lazy-rows')
        self.held = []

    def tearDown(self):
        for packed, root in reversed(self.held):
            root.close()
            packed.close()
        self.held = []
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def pack(self, cells):
        packed = RT.RecordCodec().pack_record(cells, record_schema='atlas.spatial-cells.v1',
                                              scope=self.scope, check=lambda: None)
        root = packed.root()
        self.held.append((packed, root))
        return root

    def mappings(self, cells):
        """The plain-family start rows and a differential identity carry of every row."""
        start = V.start_rows(self.pack(cells))
        self.assertIs(type(start), V._StartRows)
        carried = V.carried_rows(start)
        for i, key in enumerate(start):
            V.carry(carried, 'child:%d' % i, key, None)
        return start, carried

    def same_error(self, item_read, whole_read):
        with self.assertRaises(Exception) as lazy:
            item_read()
        with self.assertRaises(Exception) as whole:
            whole_read()
        self.assertIs(type(lazy.exception), type(whole.exception))
        self.assertEqual(lazy.exception.args, whole.exception.args)

    def same_outcome(self, item_read, whole_read):
        """The same value, strictly, or the same error."""
        try:
            expected = whole_read()
        except Exception:  # noqa: BLE001 - any error must recur on the item read
            self.same_error(item_read, whole_read)
            return
        same(self, item_read(), expected)

    def test_single_field_reads_equal_the_whole_row_strictly(self):
        for rows in self.mappings(varied()):
            for key in rows:
                whole = rows.get(key)
                self.assertIs(type(rows[key]), V._LazyRow)
                for name in FIELDS:
                    same(self, rows[key][name], whole[name])
                for name, value in whole['exact'].items():
                    same(self, rows[key]['exact'][name], value)
                same(self, rows[key]['cell_id'], whole['cell_id'])
                same(self, rows[key]['source_key'], whole['source_key'])
                self.assertIs(type(rows[key]['exact']), V._LazyExact)
                same(self, dict(rows[key]['exact']), whole['exact'])
            if type(rows) is V._CarriedRows:
                self.assertEqual([rows[key]['cell_id'] for key in rows], list(rows))

    def test_single_field_reads_export_no_whole_row(self):
        start, carried = self.mappings(varied())
        calls = []
        real_row, real_copy = V._StartRows._row, V.copy_row

        def counted_row(this, at):
            calls.append(('row', at))
            return real_row(this, at)

        def counted_copy(value, **changes):
            calls.append(('copy',))
            return real_copy(value, **changes)

        with patch.object(V._StartRows, '_row', counted_row), patch.object(V, 'copy_row', counted_copy):
            for rows in (start, carried):
                for key, row in rows.items():
                    for name in FIELDS:
                        row[name]
                    rows[key]['exact'][B_NAME]
                for row in rows.values():
                    row['volume_m3']
            self.assertEqual(calls, [])
            row = carried['child:2']
            first = row['volume_m3']
            self.assertEqual(calls, [])
            self.assertEqual(len(row), len(carried.get('child:2')))
            self.assertEqual(calls, [('row', 2), ('copy',), ('row', 2), ('copy',)])
            del calls[:]
            list(row), row.get('x'), 'exact' in row, row == {}, repr(row), list(row.items())
            row['cell_id'], row['exact'].items(), len(row['exact'])
            self.assertEqual(calls, [])
            # Once whole, item reads are the whole row's own values.
            self.assertIs(row['volume_m3'], row._whole['volume_m3'])
            self.assertIs(row['exact'][B_NAME], row._whole['exact'][B_NAME])
            same(self, row['volume_m3'], first)
            self.assertEqual(calls, [])

    def test_other_reads_are_the_whole_rows(self):
        for rows in self.mappings(varied()):
            for key in rows:
                lazy, whole = rows[key], rows.get(key)
                self.assertEqual(list(lazy), list(whole))
                self.assertEqual(list(reversed(lazy)), list(reversed(whole)))
                self.assertEqual(len(lazy), len(whole))
                self.assertIn('volume_m3', lazy)
                self.assertNotIn('absent', lazy)
                self.assertEqual(lazy.get('absent', 5), 5)
                same(self, lazy.get('volume_m3'), whole['volume_m3'])
                for view in ('keys', 'items', 'values'):
                    self.assertIs(type(getattr(lazy, view)()), type(getattr(whole, view)()))
                    same(self, list(getattr(lazy, view)()), list(getattr(whole, view)()))
                same(self, dict(lazy), dict(whole))
                self.assertTrue(lazy == whole and whole == lazy and lazy == rows[key])
                self.assertFalse(lazy != whole or lazy == {} or lazy == rows.get(key) | {'x': 1})
                self.assertEqual(repr(lazy), repr(whole))
                exact, expected = rows[key]['exact'], whole['exact']
                self.assertIs(type(exact), V._LazyExact)
                self.assertEqual(list(exact), list(expected))
                self.assertEqual(list(reversed(exact)), list(reversed(expected)))
                self.assertEqual(len(exact), len(expected))
                self.assertIn(B_NAME, exact)
                self.assertNotIn('absent', exact)
                self.assertEqual(exact.get('absent', 5), 5)
                for view in ('keys', 'items', 'values'):
                    self.assertIs(type(getattr(exact, view)()), type(getattr(expected, view)()))
                    same(self, list(getattr(exact, view)()), list(getattr(expected, view)()))
                self.assertTrue(exact == expected and expected == exact and exact == rows[key]['exact'])
                self.assertFalse(exact != expected or exact == {})
                self.assertEqual(repr(exact), repr(expected))

    def test_errors_are_the_whole_rows(self):
        bad = [full(0), full(1), full(2), full(3), full(4)]
        del bad[0]['volume_m3']
        del bad[1]['exact']
        bad[2]['exact'] = None
        bad[3]['exact'] = [1, 2]
        del bad[4]['geometry_volume_error_m3']
        for rows in self.mappings(bad):
            keys = list(rows)
            for key in keys:
                for name in (*FIELDS, 'absent', 1, ('t',)):
                    self.same_outcome(lambda: rows[key][name], lambda: rows.get(key)[name])
                for name in (B_NAME, 'absent', 1):
                    self.same_outcome(lambda: rows[key]['exact'][name], lambda: rows.get(key)['exact'][name])
                self.same_error(lambda: rows[key][[1]], lambda: rows.get(key)[[1]])
                self.same_outcome(lambda: list(rows[key]['exact'].items()),
                                  lambda: list(rows.get(key)['exact'].items()))
            self.same_error(lambda: rows['absent'], lambda: {}['absent'])
            with self.assertRaises(KeyError):
                rows['absent']

    def test_over_wide_rows_refuse_as_the_whole_row_does(self):
        rows = [full(i) for i in range(3)]
        rows[1]['history'] = 'h'*200000
        start, carried = self.mappings(rows)
        with patch.object(V, 'ROW_BYTES', 150000):
            for mapping in (start, carried):
                wide, narrow = list(mapping)[1], list(mapping)[0]
                for read in (lambda r: r['volume_m3'], lambda r: r['geometry_volume_error_m3'],
                             lambda r: r['exact'][B_NAME]):
                    self.same_error(lambda: read(mapping[wide]), lambda: read(mapping.get(wide)))
                    with self.assertRaises(ContractError) as refused:
                        read(mapping[wide])
                    self.assertEqual(str(refused.exception), 'logical export bound exceeded')
                    same(self, read(mapping[narrow]), read(mapping.get(narrow)))

    def test_booking_returns_to_its_base(self):
        start, carried = self.mappings(varied())
        base = self.budget.reserved_bytes
        for rows in (start, carried):
            for key in rows:
                rows[key]['volume_m3']
                rows[key]['geometry_volume_error_m3']
                rows[key]['exact'][B_NAME]
                self.assertEqual(self.budget.reserved_bytes, base)
                row = rows[key]
                len(row)
                self.assertGreater(self.budget.reserved_bytes, base)
                row = None
                gc.collect()
                self.assertEqual(self.budget.reserved_bytes, base)
        del start, carried, rows
        gc.collect()
        self.assertLess(self.budget.reserved_bytes, base)

    def test_the_owner_reads_match_on_item_and_whole_rows(self):
        sources = [I/'atlas_tectonics'/'integration_spatial_owner.py']
        composed = I.parents[1]/'resumability-r1'/'composed-r2'/'src'/'atlas_tectonics'/'integration_spatial_owner.py'
        if composed.exists():
            sources.append(composed)
        for path in sources:
            text = re.sub(r'\s+', ' ', path.read_text(encoding='utf8'))
            for read in OWNER_READS:
                self.assertIn(re.sub(r'\s+', ' ', read), text, path)
        _q = O._q
        cells = [full(i) for i in range(8)]
        cells.append(full(8, cell_id=cells[2]['cell_id'], volume_m3=O._enc(99)))

        def owner_reads(carried, previous):
            starts = {key: _q(row['volume_m3']) for key, row in carried.items()}
            errors = {key: tuple(map(_q, row['geometry_volume_error_m3']))
                      for key, row in carried.items()}
            booked = {key: _q(carried[key]['exact'][B_NAME]) if key in carried else Q(0)
                      for key in [*carried, 'absent']}
            prior = {key: _q(previous[key]['volume_m3']) if key in previous else Q(0)
                     for key in [*previous, 'absent']}
            transport = {}
            for key in previous:
                before = previous.get(key)
                transport[key] = (_q(before['volume_m3']), {k: _q(v) for k, v in before['exact'].items()},
                                  any(map(_q, before['exact'].values())))
            return starts, errors, booked, prior, transport

        start, carried = self.mappings(cells)
        held = {key: carried.get(key) for key in carried}, {key: start.get(key) for key in start}
        for previous, whole_previous in ((start, held[1]), (carried, held[0])):
            lazy = owner_reads(carried, previous)
            same(self, lazy, owner_reads(held[0], whole_previous))
            self.assertEqual(len(lazy[0]), 8)


if __name__ == '__main__':
    unittest.main()
