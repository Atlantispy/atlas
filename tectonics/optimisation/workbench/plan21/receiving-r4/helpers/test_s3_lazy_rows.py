"""S3 (backlog item 12): carried rows read by item export single fields, exactly.

On the same compact rows, against get() (the whole-row export, unchanged since D1-B):
- each single-field read (volume_m3, geometry_volume_error_m3, exact[name]) is strictly
  equal (same types all the way down) and exports neither the whole row nor a copy;
- every other read (another key, get, membership, iteration, length, views, equality,
  repr) is the whole row's, from one whole export kept on the row;
- absent fields, non-object exact values, non-string keys, absent cells and over-wide
  rows fail with the whole row's error type and arguments;
- r2: single fields answer only while every row passes the whole-row export's own
  refusals (logical width, stats walk, booked charge), pinned to the real export's
  threshold; a scalar whose own charge refuses is the whole row's; decode KeyErrors
  propagate; membership and a lazy exact held across the whole export are the row's;
- r3: wherever the whole row's read answers under a budget, the single field answers it
  (a budget refusal of the field path is the whole row's); a single field may answer where
  only another field's decode refuses (documented contract);
- r4: so too on a sealed segment, how spatial records are opened, where a failed chunk read
  keeps its leases until a collection: the fallback runs after one, and no booking survives
  the read;
- r5: the admission stats walk reserves the exporter's scratch first; failed walks keep
  it booked with their tracebacks, and insufficient funding falls back before allocation;
- booking returns to its base after each read and when the mapping is dropped;
- the owner's close_graph and transport row reads, checked verbatim against the owner
  source, give identical results on item-read and whole rows.
"""
from fractions import Fraction as Q
import gc
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from atlas_tectonics.resources import MemoryLimitError
from compact_contracts import ContractError
from interval_store_set import IntervalStoreSet
import record_views as RV
from segment_store import SegmentBackend
from test_spatial_compact_cells import I, O, RT, V, WorkBudget, create_retained_scope
from test_d1b_carried_start import cell, same

B_NAME = 'material_quadrature_m3'
SCHEMA = 'atlas.spatial-cells.v1'
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
        self.segments = []

    def tearDown(self):
        for packed, root in reversed(self.held):
            root.close()
            packed.close()
        self.held = []
        gc.collect()
        directories = [item[0] for item in self.segments]
        while self.segments:
            directory, stores, candidate, segment, record = self.segments.pop()
            record.close()
            segment.close()
            candidate.close()
            stores.close()
            del record, segment, candidate, stores
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        # Drop carried-page/failure owners before Windows removes their files.
        gc.collect()
        for directory in directories:
            target = directory.resolve(strict=True)
            self.assertEqual(target, directory.absolute())
            self.assertEqual(target.parent, Path(tempfile.gettempdir()).resolve(strict=True))
            self.assertTrue(target.is_dir() and target.name.startswith('s3-') and len(target.name) > 3)

            def remove_readonly(function, path, error):
                if not isinstance(error, PermissionError):
                    raise error
                failed = Path(path).resolve(strict=True)
                self.assertIn(target, failed.parents)
                if not failed.is_file() or failed.stat().st_mode & stat.S_IWRITE:
                    raise error
                failed.chmod(stat.S_IWRITE)
                function(path)

            shutil.rmtree(target, onexc=remove_readonly)
            self.assertFalse(target.exists())

    def pack(self, cells):
        packed = RT.RecordCodec().pack_record(cells, record_schema='atlas.spatial-cells.v1',
                                              scope=self.scope, check=lambda: None)
        root = packed.root()
        self.held.append((packed, root))
        return root

    def mappings(self, cells, sealed=False):
        """The plain-family start rows and a differential identity carry of every row."""
        start = V.start_rows(self.seal(cells) if sealed else self.pack(cells))
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
            lazy_exact = row['exact']
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
            self.assertIs(lazy_exact[B_NAME], row._whole['exact'][B_NAME])
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
                for name in (*FIELDS, 'exact', 'absent'):
                    self.same_outcome(lambda: name in rows[key], lambda: name in rows.get(key))
                self.same_outcome(lambda: list(rows[key]['exact'].items()),
                                  lambda: list(rows.get(key)['exact'].items()))
            self.same_error(lambda: rows['absent'], lambda: {}['absent'])
            with self.assertRaises(KeyError):
                rows['absent']

    def test_over_wide_rows_refuse_as_the_whole_row_does(self):
        rows = [full(i) for i in range(3)]
        rows[1]['history'] = 'h'*200000
        start, carried = self.mappings(rows)
        for mapping in (start, carried):
            # Admitted at the full bound first: the admission follows the bound in force.
            wide = list(mapping)[1]
            same(self, mapping[wide]['volume_m3'], mapping.get(wide)['volume_m3'])
        with patch.object(V, 'ROW_BYTES', 150000):
            for mapping in (start, carried):
                wide, narrow = list(mapping)[1], list(mapping)[0]
                self.same_error(lambda: 'volume_m3' in mapping[wide], lambda: 'volume_m3' in mapping.get(wide))
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

    def test_owned_bound_rows_refuse_as_the_whole_row_does(self):
        """Within the logical bound but over the whole row's booked charge: every read refuses alike (r2)."""
        reads = (lambda r: r['volume_m3'], lambda r: r['geometry_volume_error_m3'], lambda r: r['exact'][B_NAME])
        cases = ((V.ROW_BYTES, dict(history='h'*800000)),
                 (V.ROW_BYTES, dict(exact={B_NAME: O._enc(Q(1, 3)), 'wide': 'w'*800000})),
                 (150000, dict(history='h'*40000)))
        for bound, changes in cases:
            rows = [full(i) for i in range(3)]
            rows[1].update(changes)
            start, carried = self.mappings(rows)
            with patch.object(V, 'ROW_BYTES', bound):
                for mapping in (start, carried):
                    wide, narrow = list(mapping)[1], list(mapping)[0]
                    for read in reads:
                        self.same_error(lambda: read(mapping[wide]), lambda: read(mapping.get(wide)))
                        with self.assertRaises(ContractError) as refused:
                            read(mapping[wide])
                        self.assertEqual(str(refused.exception), 'owned export bound exceeded before allocation')
                        same(self, read(mapping[narrow]), read(mapping.get(narrow)))

    def test_wide_scalars_answer_as_the_whole_row_does(self):
        """A text or hex scalar the whole row decodes is returned, though scalar() refuses its own charge (r2)."""
        hexed, text = '0x'+'f'*270000, 't'*280000
        rows = [full(i) for i in range(4)]
        rows[1]['volume_m3'] = hexed
        rows[2]['exact'][B_NAME] = hexed
        rows[3]['geometry_volume_error_m3'] = text
        reads = (lambda r: r['volume_m3'], lambda r: r['geometry_volume_error_m3'], lambda r: r['exact'][B_NAME])
        for mapping in self.mappings(rows):
            keys = list(mapping)
            same(self, mapping[keys[1]]['volume_m3'], hexed)
            same(self, mapping[keys[2]]['exact'][B_NAME], hexed)
            same(self, mapping[keys[3]]['geometry_volume_error_m3'], text)
            for key in keys:
                for read in reads:
                    self.same_outcome(lambda: read(mapping[key]), lambda: read(mapping.get(key)))
        # Over the whole row's own bound, both refuse alike.
        for mapping in self.mappings([full(0), full(1, volume_m3='x'*1000000)]):
            wide = list(mapping)[1]
            self.same_error(lambda: mapping[wide]['volume_m3'], lambda: mapping.get(wide)['volume_m3'])

    def test_admission_is_the_whole_row_exports_own_bound(self):
        """_admits(cells, at, cap) holds exactly when that row's own export at cap does not refuse (r2)."""
        rows = [full(0), full(1, history='h'*40000), full(2, volume_m3='0x'+'f'*90000),
                full(3, exact={B_NAME: O._enc(Q(2, 9)), **{'k%03d' % j: O._enc(j) for j in range(300)}}),
                full(4, geometry_volume_error_m3=[O._enc(j) for j in range(2000)]), full(5, history='\u00e9'*9000)]
        root = self.pack(rows)

        def exports(at, cap):
            try:
                with root.at(at) as ref, ref.export(max_logical_bytes=cap, max_owned_bytes=cap):
                    return True
            except ContractError:
                return False

        for at in range(len(rows)):
            low, high = 1, 16 << 20
            self.assertFalse(exports(at, low))
            self.assertTrue(exports(at, high))
            while high-low > 1:
                middle = (low+high)//2
                low, high = (low, middle) if exports(at, middle) else (middle, high)
            self.assertFalse(V._admits(root, at, low))
            self.assertTrue(V._admits(root, at, high))

    def test_admission_walks_no_row_over_the_logical_bound(self):
        """As the export: a row over the logical bound refuses before any stats walk (r2)."""
        root = self.pack([full(0), full(1, history='h'*200000)])
        walks = []

        def counted(real):
            def walk(*args, **kwargs):
                walks.append(real.__name__)
                return real(*args, **kwargs)
            return walk

        with patch.object(V._RV, '_node_stats', counted(V._RV._node_stats)), \
                patch.object(V._RV, '_decoded_stats', counted(V._RV._decoded_stats)):
            self.assertFalse(V._admits(root, 1, 150000))
            self.assertEqual(walks, [])
            self.assertTrue(V._admits(root, 0, 150000))
            self.assertTrue(walks)

    def test_replaced_export_preflight_uses_current_whole_row(self):
        """A changed exporter must not reuse cached admission of the old preflight."""
        start, carried = self.mappings([full(0)])
        key = next(iter(start))
        start[key]['volume_m3']  # cache the accepted generation's admission
        original = RV._export_ref
        calls = []
        def current(ref, **bounds):
            calls.append(ref.index)
            return original(ref, **bounds)
        for mapping, at in ((start, key), (carried, 'child:0')):
            with patch.object(RV, '_export_ref', current), patch.object(V, '_field_value') as field:
                same(self, mapping[at]['volume_m3'], mapping.get(at)['volume_m3'])
                self.assertFalse(V._admits(start._cells, 0, V.ROW_BYTES))
                field.assert_not_called()
        self.assertTrue(calls)

    def test_admission_is_checked_once_per_bound(self):
        start, carried = self.mappings(varied())
        calls, real = [], V._admits
        with patch.object(V, '_admits', lambda cells, at, bound: calls.append(bound) or real(cells, at, bound)):
            for _ in range(2):
                for rows in (start, carried):
                    for key in rows:
                        rows[key]['volume_m3']
                        rows[key]['exact'][B_NAME]
            self.assertEqual(calls, [V.ROW_BYTES]*len(start))

    def test_admission_walk_books_and_releases_its_scratch(self):
        """The small and large stats routes run under the exporter's real scratch reservation (r5)."""
        root = self.pack([full(0), full(1, history='h'*40000)])
        amount = 65536+256*256+RV.T.MAX_DEPTH*1024
        real_scratch, real_stats = RV.T.Scratch, RV._node_stats
        bookings, walks = [], []

        def funded(budget, count):
            before = self.budget.reserved_bytes
            scratch = real_scratch(budget, count)
            bookings.append((count, before, self.budget.reserved_bytes))
            return scratch

        def observe(*args, **kwargs):
            self.assertTrue(bookings, 'stats walk has no scratch reservation')
            count, before, after = bookings[-1]
            self.assertEqual(count, amount)
            self.assertEqual(after-before, amount)
            self.assertGreaterEqual(self.budget.reserved_bytes, after)
            walks.append(args[1])
            return real_stats(*args, **kwargs)

        base = self.budget.reserved_bytes
        with patch.object(RV.T, 'Scratch', funded), patch.object(RV, '_node_stats', observe):
            for at in range(2):
                self.assertTrue(V._admits(root, at, V.ROW_BYTES))
                self.assertEqual(self.budget.reserved_bytes, base)
        self.assertEqual(len(bookings), 2)
        self.assertEqual(len(walks), 2)

    def test_admission_scratch_funds_failure_frames_until_released(self):
        """Failure-frame workspace stays booked until its traceback is dropped and collected (r5)."""
        root = self.pack([full(0), full(1, history='h'*40000)])
        amount = 65536+256*256+RV.T.MAX_DEPTH*1024
        for at in range(2):
            for exception in (ContractError, MemoryLimitError, RuntimeError):
                base = self.budget.reserved_bytes
                failures = []

                def fail(*args, **kwargs):
                    self.assertGreaterEqual(self.budget.reserved_bytes, base+amount)
                    failure = exception('injected admission stats failure')
                    # A traceback and its allocating frame may form a cycle.
                    workspace = [None]*256
                    failure.workspace = (workspace, failure)
                    raise failure

                with patch.object(RV, '_node_stats', fail):
                    if exception is ContractError:
                        self.assertFalse(V._admits(root, at, V.ROW_BYTES))
                    else:
                        try:
                            V._admits(root, at, V.ROW_BYTES)
                        except exception as error:
                            failures.append(error)
                        self.assertEqual(len(failures), 1)
                        self.assertEqual(self.budget.reserved_bytes, base+amount)
                        failures.clear()
                        gc.collect()
                self.assertEqual(self.budget.reserved_bytes, base)

    def test_unfunded_admission_uses_whole_row_without_walking(self):
        """Insufficient walk funding takes the existing whole-row fallback before allocating stats (r5)."""
        start, carried = self.mappings([full(0)])
        amount = 65536+256*256+RV.T.MAX_DEPTH*1024
        real_row = V._StartRows._row
        calls = []

        def whole(this, at):
            calls.append(at)
            return real_row(this, at)

        for mapping in (start, carried):
            key = next(iter(mapping))
            base = self.budget.reserved_bytes
            with patch.object(V._StartRows, '_row', whole), patch.object(RV, '_node_stats') as stats:
                got = self.at_free(self.budget, amount-1, lambda: mapping[key]['volume_m3'])
                self.assertEqual(calls, [0])
                self.assertEqual(got[0], 'RAISE')
                self.assertIsNone(start._admitted)
                stats.assert_not_called()
            self.assertEqual(self.budget.reserved_bytes, base)
            self.assertEqual(got, self.at_free(self.budget, amount-1, lambda: mapping.get(key)['volume_m3']))
            self.assertEqual(self.budget.reserved_bytes, base)
            calls.clear()

    def test_decode_key_errors_are_not_absences(self):
        """A KeyError raised while a present row or field decodes propagates; it is not an absent cell or field."""
        start, carried = self.mappings([full(0), full(1)])
        for rows in (start, carried):
            key = list(rows)[1]
            with patch.object(V._StartRows, '_row', side_effect=KeyError('decode')):
                with self.assertRaises(KeyError) as raised:
                    rows.get(key)
                self.assertEqual(raised.exception.args, ('decode',))
            with patch.object(V, '_field_value', side_effect=KeyError('decode')):
                for read in (lambda r: r['volume_m3'], lambda r: r['exact'][B_NAME]):
                    with self.assertRaises(KeyError) as raised:
                        read(rows[key])
                    self.assertEqual(raised.exception.args, ('decode',))

    def at_free(self, budget, free, read):
        """read() with exactly ``free`` bytes left on ``budget``: ('OK', value) or ('RAISE', type, args)."""
        hold = budget.max_bytes-budget.reserved_bytes-free
        lease = budget.reserve(hold, category='s3-test-hold') if hold > 0 else None
        try:
            if lease is not None:
                lease.__enter__()
            try:
                return ('OK', read())
            except MemoryLimitError as error:
                return ('RAISE', type(error), error.args)
        finally:
            if lease is not None:
                lease.__exit__(None, None, None)

    def least_free(self, budget, read):
        """The least free bytes at which read() answers; it refuses one byte below."""
        low, high = 0, 64 << 20
        self.assertEqual(self.at_free(budget, high, read)[0], 'OK')
        while low < high:
            middle = (low+high)//2
            low, high = (low, middle) if self.at_free(budget, middle, read)[0] == 'OK' else (middle+1, high)
        self.assertEqual(self.at_free(budget, low-1, read)[0], 'RAISE')
        return low

    def test_budget_refusals_are_the_whole_rows(self):
        """Wherever the whole row's read answers, the single field answers it (refuter r2 P2-1, P2-2, P3-1; r3).

        Shapes whose field path books more than the whole row: a 100k text scalar (scalar() charge, retained
        budget), a 400k-character key (the key search's scratch, run budget) and a minimal one-name row (the
        field path's holders). One byte below the whole row's least, the field refuses alike or answers.
        """
        text = full(1, volume_m3='v'*100000)
        text['exact'][B_NAME] = 'x'*100000
        wide_key = dict(full(1), **{'gz'+'z'*400000: 1})
        minimal = {'cell_id': 'a', 'exact': {B_NAME: ['0x1', '0x1']}, 'volume_m3': ['0x1', '0x1']}
        reads = (lambda r: r['volume_m3'], lambda r: r['exact'][B_NAME])
        for row, which in ((text, 'retained'), (wide_key, 'run'), (minimal, 'retained')):
            start, carried = self.mappings([row])
            budget = self.scope.retained_budget if which == 'retained' else self.budget
            for mapping, key in ((start, next(iter(start))), (carried, 'child:0')):
                for read in reads:
                    whole = lambda: read(mapping.get(key))
                    item = lambda: read(mapping[key])
                    need = self.least_free(budget, whole)
                    answered = self.at_free(budget, need, item)
                    self.assertEqual(answered[0], 'OK', (which, answered))
                    same(self, answered[1], whole())
                    below = self.at_free(budget, need-1, item)
                    if below[0] == 'RAISE':
                        self.assertEqual(below, self.at_free(budget, need-1, whole))
                    else:
                        same(self, below[1], whole())

    def test_a_decode_refusal_elsewhere_in_the_row_is_the_whole_rows_only(self):
        """Documented contract (refuter r2 P2-3): a single field answers where only another field's decode refuses."""
        limit = sys.get_int_max_str_digits()
        sys.set_int_max_str_digits(0)
        try:
            start, carried = self.mappings([full(1, history=10**5000)])
            key = next(iter(start))
            expected = start.get(key)
        finally:
            sys.set_int_max_str_digits(limit)
        for mapping, at in ((start, key), (carried, 'child:0')):
            with self.assertRaisesRegex(ValueError, 'Exceeds the limit'):
                mapping.get(at)
            same(self, mapping[at]['volume_m3'], expected['volume_m3'])
            same(self, mapping[at]['exact'][B_NAME], expected['exact'][B_NAME])

    def seal(self, cells):
        """The rows as a promoted native segment, opened as spatial records are (spatial_records_patch)."""
        directory = Path(tempfile.mkdtemp(prefix='s3-'))
        stores = IntervalStoreSet.create_migration(str(directory/'catalog.json'), workflow_id='1'*64,
                                                   scope=self.scope)
        candidate = stores.begin_interval(None, producer_identity='2'*64, runtime_identity='3'*64)
        packed = RT.RecordCodec().pack_record(cells, record_schema=SCHEMA, scope=self.scope, check=lambda: None)
        backend = SegmentBackend()
        with packed.metadata_bytes() as held:
            ref = backend.publish(candidate, record_schema=SCHEMA, identity=packed.identity(),
                                  metadata=held.value, arrays=packed.array_sources, producer='2'*64,
                                  representation_profile=RT.SCHEMA, scope=self.scope)
        packed.close()
        del packed, held
        promoted = candidate.seal(ref)
        stores.promote(promoted, expected_catalog_digest=promoted.expected_catalog_digest)
        del promoted
        segment = backend.open(stores, ref, scope=self.scope)
        record = RV.CompactRecord.from_segment(segment)
        self.segments.append((directory, stores, candidate, segment, record))
        return record.root()

    def reserved(self):
        """(run, retained) reserved bytes with the page cache evicted."""
        self.scope.evict_unpinned(requested_bytes=1 << 40)
        return self.budget.reserved_bytes, self.scope.retained_budget.reserved_bytes

    def cold(self, budget, free, read):
        """at_free from a collected, evicted state; on a segment the outcome depends on both (refuter r3)."""
        gc.collect()
        self.reserved()
        return self.at_free(budget, free, read)

    def test_segment_refusals_release_their_bookings_before_the_whole_row(self):
        """On a sealed segment too, the single field answers wherever the whole row answers (refuter r3 P2-1, P3-1; r4).

        A failed chunk read keeps its leases in a reference cycle until a collection; without one before the
        fallback, the whole row answered with less budget than the base read gets. Owner-shaped rows on the
        retained budget, swept above the whole row's least; a 400k-character key on the run budget; wide hex and
        text scalars (scalar() refuses its own charge) at ample budget. With automatic collection off, no booking
        survives an item read.
        """
        def native(i, **changes):
            return dict({'cell_id': 'n%04d' % i, 'source_key': ['synthetic', i], 'volume_m3': O._enc(i+5),
                         'exact': {'enthalpy_j': O._enc(7*i+1)}}, **changes)
        retained, ample = self.scope.retained_budget, 1 << 40
        cases = (
            ([native(i) for i in range(3)], lambda r: r['exact']['enthalpy_j'], retained, None),
            ([native(0), dict(full(1), **{'gz'+'z'*400000: 1}), native(2)], lambda r: r['exact']['mass_kg'],
             self.budget, (14 << 20, 16 << 20, 18 << 20, 20 << 20)),
            ([native(0), native(1, volume_m3='0x'+'f'*270000), native(2)], lambda r: r['volume_m3'],
             self.budget, (ample,)),
            ([native(0), native(1, exact={'enthalpy_j': 't'*280000}), native(2)],
             lambda r: r['exact']['enthalpy_j'], self.budget, (ample,)))
        for rows, read, budget, frees in cases:
            start, carried = self.mappings(rows, sealed=True)
            for mapping, key in ((start, list(start)[1]), (carried, 'child:1')):
                whole = lambda m=mapping, k=key, r=read: r(m.get(k))
                item = lambda m=mapping, k=key, r=read: r(m[k])
                points = frees
                if points is None:
                    low, high = 0, 1 << 20
                    self.assertEqual(self.cold(budget, high, whole)[0], 'OK')
                    while low < high:
                        middle = (low+high)//2
                        low, high = (low, middle) if self.cold(budget, middle, whole)[0] == 'OK' else (middle+1, high)
                    points = range(low, low+600, 30)
                answered = 0
                for free in points:
                    expected = self.cold(budget, free, whole)
                    if expected[0] != 'OK':
                        continue
                    answered += 1
                    gc.collect()
                    gc.disable()
                    try:
                        before = self.reserved()
                        got = self.at_free(budget, free, item)
                        after = self.reserved()
                    finally:
                        gc.enable()
                    self.assertEqual(got[0], 'OK', (free, got))
                    same(self, got[1], expected[1])
                    self.assertEqual(after, before, free)
                self.assertGreaterEqual(answered, len(points)//2)
            del start, carried, mapping, whole, item

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
