"""D1-B: the carried start holds an index of compact rows, never every decoded row.

The transformed _carried_start_cells (the actual owner source through every
existing transform) is compared on the same rows with
- the pre-D1-B compact transform (every row decoded and held): identical keys
  in identical order, identical rows including their canonical key order and
  type, and identical refusals;
- the untransformed native function on plain dictionaries: identical keys in
  identical order and equal rows (compact rows were already canonically
  key-ordered before D1-B), and identical refusals.
The compact route keeps at most the reader's current rows live; its index
booking is checked against the measured index memory.
"""
import ast
import gc
import tracemalloc
import unittest
from hashlib import sha256

from test_spatial_compact_cells import (
    RT,
    E,
    I,
    O,
    S,
    V,
    WorkBudget,
    X,
    create_retained_scope,
    native_methods,
)

FAMILY = 'differential-plate-component-partition-v1'
PARTITION = 'p'*64
# The pre-D1-B owner_source edits of _carried_start_cells.
BEFORE_D1B = (
    ("previous = {row['cell_id']: row for row in state['cells']}",
     "previous = {row['cell_id']: row for row in _SV.rows(state['cells'])}"),
    ('carried[child] = dict(old, cell_id=child)', 'carried[child] = _SV.copy_row(old, cell_id=child)'),
)


def _compiled(source, env, label):
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == '_carried_start_cells')
    # The actual owner function, compiled as test_spatial_compact_cells does.
    exec(compile(ast.Module(body=[node], type_ignores=[]), label, 'exec'), env)  # noqa: S102
    return env['_carried_start_cells']


def native_function():
    """The untransformed native _carried_start_cells (the dictionary route)."""
    source = (I/'atlas_tectonics'/'integration_spatial_owner.py').read_text(encoding='utf8')
    return _compiled(source, dict(O.__dict__), '<native-carried-start>')


def before_d1b_function():
    """The pre-D1-B compact transform: every carried row decoded and held at once."""
    source = (I/'atlas_tectonics'/'integration_spatial_owner.py').read_text(encoding='utf8')
    held = V._function(E.holder_source(X.transform(S.spatial_owner_source(source))),
                       '_carried_start_cells', BEFORE_D1B)
    return _compiled(held, {**O.__dict__, '_SV': V}, '<pre-d1b-carried-start>')


def cell(i, *, history=0, cell_id=None):
    return {'cell_id': cell_id or sha256(b'cell'+str(i).encode()).hexdigest(),
            'source_key': ['synthetic', i], 'volume_m3': O._enc(i+1),
            'geometry_volume_error_m3': [O._enc(0), O._enc(i)],
            'exact': {'mass_kg': O._enc(i+1), 'enthalpy_j': O._enc(3*(i+1))}, 'history': 'h'*history}


def start(cells):
    return {'cells': cells, 'thermal_mesh': {'partition_id': PARTITION}}


def geometry(cells, *, children=None):
    children = children or ['child:'+str(i) for i in range(len(cells))]
    pairs = list(zip(cells, children, strict=True))
    return {'physical_geometry_family': FAMILY, 'parent_partition_id': PARTITION,
            'identity_start_cells': [{'parent_cell_id': row['cell_id'], 'cell_id': child}
                                     for row, child in pairs],
            'cells': [{'cell_id': child, 'kind': 'exterior', 'source_key': row['source_key']}
                      for row, child in pairs]}


def new_child(bounds):
    return ({'parent_cell_id': 'gone', 'cell_id': 'child:new'},
            {'cell_id': 'child:new', 'kind': 'exterior', 'source_key': ['x'],
             'start_volume_bounds_m3': [O._enc(v) for v in bounds]})


class D1BCarriedStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compact = staticmethod(native_methods()['_carried_start_cells'])
        cls.native = staticmethod(native_function())
        cls.before = staticmethod(before_d1b_function())

    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='d1b-carried-start')
        self.held = []

    def tearDown(self):
        for packed, root in reversed(self.held):
            root.close()
            packed.close()
        self.held = []
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def state(self, cells):
        packed = RT.RecordCodec().pack_record(cells, record_schema='atlas.spatial-cells.v1',
                                              scope=self.scope, check=lambda: None)
        root = packed.root()
        self.held.append((packed, root))
        return start(root)

    def both(self, cells, shape):
        native = self.native(start(cells), shape)
        compact = self.compact(self.state(cells), shape)
        before = self.before(self.state(cells), shape)
        self.assert_exact(before, compact)
        return native, compact

    def assert_exact(self, before, compact):
        """D1-B against the pre-D1-B compact route: identical in every observable."""
        self.assertIs(type(before), dict)
        self.assertEqual(list(compact), list(before))
        for key, row in before.items():
            self.assertIs(type(compact[key]), type(row))
            self.assertEqual(list(compact[key].items()), list(row.items()))

    def assert_same(self, native, compact):
        self.assertEqual(list(compact), list(native))
        self.assertEqual(len(compact), len(native))
        for key in native:
            self.assertIn(key, compact)
            self.assertEqual(compact[key], native[key])
            self.assertEqual(compact.get(key), native[key])
        self.assertIsNone(compact.get('absent'))
        self.assertNotIn('absent', compact)
        self.assertEqual(dict(compact.items()), dict(native.items()))

    def test_plain_family_returns_the_exact_start_mapping(self):
        cells = [cell(i) for i in range(12)]
        native, compact = self.both(cells, {})
        self.assertIs(type(compact), V._StartRows)
        self.assert_same(native, compact)

    def test_duplicate_cell_ids_keep_first_position_and_last_row(self):
        cells = [cell(i) for i in range(6)]
        cells.insert(4, cell(99, cell_id=cells[1]['cell_id']))
        native, compact = self.both(cells, {})
        self.assertEqual(len(native), 6)
        self.assert_same(native, compact)

    def test_differential_identity_returns_the_exact_carried_mapping(self):
        cells = [cell(i) for i in range(10)]
        # A permuted mapping order: the carried order is the mapping's order.
        order = [3, 0, 9, 1, 8, 2, 7, 4, 6, 5]
        shape = geometry([cells[i] for i in order], children=['child:'+str(i) for i in order])
        native, compact = self.both(cells, shape)
        self.assertIs(type(compact), V._CarriedRows)
        self.assert_same(native, compact)
        self.assertEqual([row['cell_id'] for _, row in compact.items()], list(native))

    def test_absent_old_with_zero_bounds_is_skipped_in_both(self):
        cells = [cell(i) for i in range(4)]
        shape = geometry(cells)
        item, row = new_child((0, 0))
        shape['identity_start_cells'].append(item)
        shape['cells'].append(row)
        native, compact = self.both(cells, shape)
        self.assertNotIn('child:new', native)
        self.assert_same(native, compact)

    def test_refusals_match_the_native_function(self):
        cells = [cell(i) for i in range(5)]
        lineage = geometry(cells)
        lineage['cells'][2]['source_key'] = ['changed']
        omitted = geometry(cells)
        del omitted['identity_start_cells'][3]
        duplicate = geometry(cells)
        duplicate['identity_start_cells'][1] = dict(duplicate['identity_start_cells'][0])
        positive = geometry(cells)
        item, row = new_child((0, 1))
        positive['identity_start_cells'].append(item)
        positive['cells'].append(row)
        stale = geometry(cells)
        stale['parent_partition_id'] = 'q'*64
        for shape in (lineage, omitted, duplicate, positive, stale):
            with self.assertRaises(O.TectonicsError) as native:
                self.native(start(cells), shape)
            with self.assertRaises(O.TectonicsError) as compact:
                self.compact(self.state(cells), shape)
            with self.assertRaises(O.TectonicsError) as before:
                self.before(self.state(cells), shape)
            self.assertEqual(str(compact.exception), str(native.exception))
            self.assertEqual(str(before.exception), str(native.exception))

    def test_dictionary_states_keep_the_native_route(self):
        cells = [cell(i) for i in range(5)]
        previous = self.compact(start(cells), {})
        self.assertIs(type(previous), dict)
        carried = self.compact(start(cells), geometry(cells))
        self.assertIs(type(carried), dict)
        self.assertEqual(carried, self.native(start(cells), geometry(cells)))

    def test_only_the_readers_current_rows_are_live(self):
        cells = [cell(i, history=2000) for i in range(120)]
        state = self.state(cells)
        base = self.budget.reserved_bytes
        held = {row['cell_id']: row for row in V.rows(state['cells'])}
        all_rows = self.budget.reserved_bytes-base
        del held
        gc.collect()
        carried = self.compact(state, geometry(cells))
        index = self.budget.reserved_bytes-base
        peak = 0
        starts = {}
        for key, value in carried.items():      # close_graph's pass pattern
            peak = max(peak, self.budget.reserved_bytes-base)
            starts[key] = O._q(value['volume_m3'])
        value = None
        self.assertEqual(starts, {'child:'+str(i): O._q(row['volume_m3']) for i, row in enumerate(cells)})
        one = peak-index
        self.assertLess(index+one, all_rows/20, (index, one, all_rows))
        del carried
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, base)

    def test_index_booking_covers_measured_index_memory(self):
        cells = [cell(i) for i in range(3000)]
        state = self.state(cells)
        first = self.budget.reserved_bytes
        gc.collect()
        tracemalloc.start()
        try:
            before = tracemalloc.get_traced_memory()[0]
            previous = V.start_rows(state['cells'])
            gc.collect()
            index_real = tracemalloc.get_traced_memory()[0]-before
            index_booked = self.budget.reserved_bytes-first
            mid = self.budget.reserved_bytes
            before = tracemalloc.get_traced_memory()[0]
            carried = V.carried_rows(previous)
            for i, row in enumerate(cells):
                carried._carry(sha256(b'child'+str(i).encode()).hexdigest(), row['cell_id'])
            gc.collect()
            carried_real = tracemalloc.get_traced_memory()[0]-before
            carried_booked = self.budget.reserved_bytes-mid
        finally:
            tracemalloc.stop()
        # Child ids are created here for the measurement; in the owner they are
        # the geometry mapping's existing strings, so subtract their objects.
        child_strings = 3000*(49+64)
        self.assertLessEqual(index_real, index_booked, (index_real, index_booked))
        self.assertLessEqual(index_booked, 1.6*index_real, (index_real, index_booked))
        # A dict's slot cost swings about 3x between resizes; the booking takes
        # its post-resize maximum, so a carried index is at most about 2x over
        # (a few hundred KB at interval two).
        self.assertLessEqual(carried_real-child_strings, carried_booked, (carried_real, carried_booked))
        self.assertLessEqual(carried_booked, 2.5*max(carried_real-child_strings, 1),
                             (carried_real, carried_booked))
        del carried, previous


if __name__ == '__main__':
    unittest.main()
