"""Step 5 bounded native-row input for the unchanged exact JSON DAG codec."""
import gc
from hashlib import sha256
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'))

from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import ChargeSpec, create_retained_scope
import record_tables as T
from test_record_tables import streamed


class StreamingRowsTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='stream-rows')

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def owned(self, value, scope=None):
        reservation = (scope or self.scope).reserve(ChargeSpec('test-row', 65536))
        assert reservation is not None
        with reservation:
            return reservation.commit(value)

    def pack(self, value, check=lambda: None):
        return T.RecordCodec().pack_record(
            value, record_schema='test.streaming.v1', scope=self.scope, check=check)

    def test_exact_nested_rows_and_single_live_row(self):
        values = [{'i': i, 'same': ['0x1', '0x2'], 'tag': 'é\ud800'}
                  for i in range(200)]
        calls = []
        def rows():
            calls.append(True)
            previous = None
            for value in values:
                if previous is not None:
                    with self.assertRaises(RuntimeError):
                        _ = previous.value
                previous = self.owned(value)
                yield previous
        record = self.pack({'rows': T.StreamingRows(len(values), rows)})
        expected = T.canonical({'rows': values})
        self.assertEqual(len(calls), 1)
        self.assertEqual(streamed(record), expected)
        self.assertEqual(record.identity().sha256, sha256(expected).hexdigest())
        record.close()

    def test_empty_and_rational_pair_match_ordinary_arrays(self):
        for values in ([], ['0x1', '0x2']):
            record = self.pack(T.StreamingRows(len(values), lambda: (
                self.owned(value) for value in values)))
            ordinary = self.pack(values)
            self.assertEqual(record.identity(), ordinary.identity())
            with record.storage_payload() as a, ordinary.storage_payload() as b:
                self.assertEqual(a.value[0], b.value[0])
                for name in a.value[1]:
                    self.assertEqual(a.value[1][name].tobytes(), b.value[1][name].tobytes())
            ordinary.close()
            record.close()

    def test_declared_count_and_owned_values_are_required(self):
        for count, values in ((0, [1]), (2, [1])):
            with self.assertRaisesRegex(ContractError, 'count'):
                self.pack(T.StreamingRows(count, lambda: (
                    self.owned(value) for value in values)))
        with self.assertRaisesRegex(ContractError, 'owned'):
            self.pack(T.StreamingRows(1, lambda: iter([1])))
        with self.assertRaisesRegex(ContractError, 'unsupported'):
            self.pack(iter([1]))
        for count in (-1, True, T.MAX_ITEMS+1):
            with self.assertRaises(ContractError):
                T.StreamingRows(count, lambda: iter(()))

    def test_foreign_scope_refused(self):
        budget = WorkBudget(1 << 30)
        foreign = create_retained_scope(budget, process_epoch='foreign-rows')
        row = self.owned(1, foreign)
        with self.assertRaisesRegex(ContractError, 'same scope'):
            self.pack(T.StreamingRows(1, lambda: iter([row])))
        row.close()
        foreign.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_failed_row_retains_charge_with_traceback(self):
        before = self.scope.stats().retained_bytes
        failure = None
        try:
            self.pack(T.StreamingRows(1, lambda: iter([self.owned(object())])))
        except ContractError as exc:
            failure = exc
        self.assertIsNotNone(failure)
        self.assertGreater(self.scope.stats().retained_bytes, before)
        del failure
        gc.collect()
        self.assertEqual(self.scope.stats().retained_bytes, before)


if __name__ == '__main__':
    unittest.main()

