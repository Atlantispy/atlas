"""Step 8 streamed state cells: exact bytes, native order, paid failures."""
import gc
import json
import random
import sys
import unittest
from concurrent.futures import CancelledError
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
R = HERE.parent
I = R.parent/'runtime-integration-r1'/'runtime-src'
for directory in (I, R):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import live_spatial_patch as LIVE
import record_tables as T
from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import create_retained_scope


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def stream(ref):
    output = []
    with ref.iter_json() as blocks:
        for block in blocks:
            with block:
                output.append(block.value)
    return b''.join(output)


def rows(count, seed=7):
    """Native finish rows: hex rationals, non-ASCII keys and late writes."""
    shuffled = random.Random(seed)
    result = []
    for i in range(count):
        cell_id = sha256(('cell'+str(i)).encode()).hexdigest()
        result.append({'cell_id': cell_id, 'source_key': 'src-é'+str(i % 5),
                       'volume_m3': ['0x'+format(i+3, 'x'), '0x7'],
                       'exact': {'enthalpy_j': ['-0x'+format(i+1, 'x'), '0x3'], 'ß': ['0x0', '0x1']}})
    shuffled.shuffle(result)
    return result


class StateCellTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='step8-state-cells-test')
        self.initial = self.budget.reserved_bytes
        self.owner = SimpleNamespace(_record_scope=self.scope, _budget=self.budget)

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def native(self, produced):
        """What the native finish issued: the sorted list, packed once."""
        expected = sorted(produced, key=lambda row: row['cell_id'])
        packed = T.RecordCodec().pack_record(expected, record_schema=LIVE.STATE_CELLS_SCHEMA,
                                             scope=self.scope, check=lambda: None)
        return expected, packed

    def produce(self, cells, source):
        """The native loop's write pattern: append, then maybe a late key."""
        produced = []
        for at, row in enumerate(source):
            cells.append(dict(row))
            produced.append(dict(row))
            if at % 3 == 0:
                cells[-1]['geometry_volume_error_m3'] = ['0x'+format(at, 'x'), '0x9']
                produced[-1]['geometry_volume_error_m3'] = ['0x'+format(at, 'x'), '0x9']
        return produced

    def test_streamed_cells_have_native_bytes_identity_and_order(self):
        for count in (0, 1, 2, 57):
            cells = LIVE.cell_sink(self.owner)
            self.assertIs(type(cells), LIVE.CellSink)
            produced = self.produce(cells, rows(count))
            LIVE.sort_cells(cells)
            root = LIVE.state_cells(cells)
            expected, packed = self.native(produced)
            self.assertEqual(root.kind, 'array')
            self.assertEqual(root.size, count)
            self.assertEqual(stream(root), canonical(expected))
            self.assertEqual(root.identity().sha256, packed.identity().sha256)
            self.assertEqual(root.identity().canonical_bytes, packed.identity().canonical_bytes)
            # The record keeps returning the same finished array.
            again = LIVE.state_cells(cells)
            self.assertEqual(stream(again), canonical(expected))
            again.close()
            root.close()
            packed.close()
            del cells, root, again, packed

    def test_only_the_newest_row_is_writable_and_finish_is_final(self):
        cells = LIVE.cell_sink(self.owner)
        with self.assertRaises(ContractError):
            cells[-1]
        cells.append(rows(2)[0])
        with self.assertRaises(ContractError):
            cells[0]
        root = LIVE.state_cells(cells)
        with self.assertRaises(ContractError):
            cells.sort_by_cell_id()
        root.close()

    def test_switch_off_and_scope_free_owners_keep_the_native_list(self):
        self.assertEqual(LIVE.cell_sink(SimpleNamespace(_budget=self.budget)), [])
        LIVE.STREAM_CELLS = False
        try:
            cells = LIVE.cell_sink(self.owner)
        finally:
            LIVE.STREAM_CELLS = True
        self.assertEqual(cells, [])
        source = rows(5)
        for row in source:
            cells.append(row)
        LIVE.sort_cells(cells)
        self.assertEqual(cells, sorted(source, key=lambda row: row['cell_id']))
        self.assertIs(LIVE.state_cells(cells), cells)

    def test_malformed_row_and_cancellation_refuse_and_stay_paid_until_released(self):
        cells = LIVE.cell_sink(self.owner)
        cells.append(rows(1)[0])
        cells.append({'no_cell_id': 1})
        with self.assertRaises(ContractError):
            LIVE.state_cells(cells)
        self.assertGreater(self.budget.reserved_bytes, self.initial)
        del cells
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.initial)
        calls = []
        def cancel():
            calls.append(1)
            return len(calls) > 3
        cells = LIVE.cell_sink(self.owner, cancel)
        caught = []
        try:
            for row in rows(20):
                cells.append(row)
            LIVE.state_cells(cells)
        except CancelledError as error:
            caught.append(error)
        self.assertEqual(len(caught), 1)
        self.assertGreater(self.budget.reserved_bytes, self.initial)
        del cells, caught
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.initial)


if __name__ == '__main__':
    unittest.main(verbosity=2)
