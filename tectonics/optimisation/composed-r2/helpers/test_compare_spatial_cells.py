"""compare_spatial_records compares compact state cells by their exact byte streams.

Audit D4(i), 16 Oct 2026: the reopen check compared two borrows of the same
compact cells with ``==``; RecordRef defines no value equality, so identical
cells compared unequal. Compact values are now compared like the thermal mesh:
exact canonical byte streams in order, never a hash in place of the bytes.
"""
import gc
import importlib.machinery
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'), str(HERE.parent)]
OLD_BODY = HERE.parent/'probes'/'step8'/'claude-20261015'/'before-src'/'private_heat_indexed_runtime.py.before-d4'

import private_heat_indexed_runtime as P
from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope
from record_tables import RecordCodec

CELLS = [{'cell_id': 'a', 'exact': {'enthalpy_j': ['0x3', '0x7']}, 'volume_m3': ['0x1', '0x2']},
         {'cell_id': 'b', 'exact': {'enthalpy_j': ['-0x5', '0x2']}, 'volume_m3': ['0x9', '0x4']}]


def old_runtime():
    """The pre-16-Oct comparison: the mutant."""
    loader = importlib.machinery.SourceFileLoader('private_heat_indexed_runtime_before_d4', str(OLD_BODY))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


class CompareSpatialCellsTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(64 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='compare-spatial-cells')
        self.records = []

    def tearDown(self):
        for record in self.records:
            record.close()
        self.records = None
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def cells(self, value):
        record = RecordCodec().pack_record(value, record_schema='test.compact-cells.v1', scope=self.scope,
                                           check=lambda: None)
        self.records.append(record)
        return record.root()

    def state(self, record):
        return SimpleNamespace(_snapshot=None, _budget=self.budget, record=lambda: record)

    def compare(self, module, actual, expected):
        try:
            module.compare_spatial_records(self, self.state(actual), expected)
        finally:
            gc.collect()

    def test_identical_compact_cells_compare_equal_by_bytes(self):
        actual = {'state_id': 's', 'cells': self.cells(CELLS)}
        expected = {'state_id': 's', 'cells': self.cells(CELLS)}
        self.compare(P, actual, expected)
        # A compact side against an ordinary list of the same cells.
        self.compare(P, actual, {'state_id': 's', 'cells': CELLS})
        # The mutant: two borrows of identical cells were unequal under ==.
        with self.assertRaises(AssertionError):
            self.compare(old_runtime(), actual, expected)
        for value in (actual['cells'], expected['cells']):
            value.close()

    def test_differences_are_refused(self):
        changed = [dict(CELLS[0]), dict(CELLS[1], volume_m3=['0x9', '0x5'])]
        base = self.cells(CELLS)
        for expected in ({'state_id': 's', 'cells': self.cells(changed)},
                         {'state_id': 's', 'cells': changed},
                         {'state_id': 't', 'cells': self.cells(CELLS)},
                         {'cells': self.cells(CELLS)},
                         {'state_id': 's', 'cells': self.cells(CELLS[:1])}):
            with self.subTest(expected=sorted(expected)), self.assertRaises(AssertionError):
                self.compare(P, {'state_id': 's', 'cells': base}, expected)
            if hasattr(expected.get('cells'), 'close'):
                expected['cells'].close()
        base.close()

    def test_plain_records_keep_ordinary_equality(self):
        self.compare(P, {'state_id': 's', 'cells': CELLS}, {'state_id': 's', 'cells': CELLS})
        with self.assertRaises(AssertionError):
            self.compare(P, {'state_id': 's', 'cells': CELLS}, {'state_id': 's', 'cells': CELLS[:1]})


if __name__ == '__main__':
    unittest.main()
