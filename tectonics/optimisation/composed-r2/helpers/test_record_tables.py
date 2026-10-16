"""WP2 component evidence; synthetic records, no scientific run or migration."""
import ast
from collections.abc import Mapping, Sequence
from concurrent.futures import CancelledError
from copy import deepcopy
import gc
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'))

import numpy as np
from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import create_retained_scope
import record_tables as T
from record_views import CompactRecord, LogicalExchange


def corpus():
    """Execute the existing corpus constructor verbatim, not another imitation."""
    source = (HERE.parent/'test_materialise_endpoint.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and
                  n.name == 'test_canonical_check_matches_metadata_encoder_and_bound')
    cut = next(i for i, n in enumerate(method.body) if isinstance(n, ast.Assign) and
               any(isinstance(t, ast.Name) and t.id == 'budget' for t in n.targets))
    prefix = ast.Module(body=method.body[:cut], type_ignores=[])
    env = {'M': SimpleNamespace(W=SimpleNamespace(canonical=T.canonical))}
    exec(compile(prefix, str(HERE.parent/'test_materialise_endpoint.py'), 'exec'), env)
    return env['spellings']


def streamed(record, chunk=65536):
    result = []
    with record.iter_json(max_chunk_bytes=chunk) as stream:
        for block in stream:
            with block:
                if len(block.value) > chunk:
                    raise AssertionError('unbounded yielded chunk')
                result.append(block.value)
    return b''.join(result)


class RecordTablesTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(3 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='wp2-test')
        self.codec = T.RecordCodec()

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def pack(self, value):
        return self.codec.pack_record(value, record_schema='test.generic.v1', scope=self.scope, check=lambda: None)

    def test_1217_original_spelling_corpus_and_exact_identity(self):
        spellings = corpus()
        self.assertEqual(len(spellings), 1217)
        for raw in spellings:
            value = json.loads(raw)
            record = self.pack(value)
            expected = T.canonical(value)
            self.assertEqual(streamed(record, 97), expected)
            self.assertEqual(record.identity().sha256, sha256(expected).hexdigest())
            record.close()
        del record

    def test_giant_heat_magnitudes_and_chunked_dyadics(self):
        numerator = (1 << (2_054_462-1))+3
        denominator = (1 << (2_054_539-1))+17
        pair = [hex(-numerator), hex(denominator)]
        self.assertEqual(len(T.canonical(pair)), 1_027_263)
        value = dict(pair=pair, same_den=[hex(numerator+2), pair[1]],
                     dyadic=['-0x1', hex(1 << 2_054_539)])
        cap = sys.get_int_max_str_digits()
        record = self.pack(value)
        self.assertEqual(streamed(record), T.canonical(value))
        with record.storage_payload() as held:
            _, arrays = held.value
            self.assertEqual(len(arrays['int.sign']), 5)
            self.assertEqual(sum(arrays['int.mode']), 1)
            self.assertLess(max(np.diff(arrays['int.offset'])), T.MAX_INTEGER_BYTES)
        root = record.root(); pair_ref = root.field('pair'); scalar = pair_ref.at(0)
        with self.assertRaisesRegex(ContractError, 'before decode'):
            scalar.scalar(max_owned_bytes=65536)
        with scalar.scalar(max_owned_bytes=16 << 20) as held:
            self.assertEqual(held.value, pair[0])
        self.assertEqual(sys.get_int_max_str_digits(), cap)
        scalar.close(); pair_ref.close(); root.close(); record.close()

    def test_exact_spelling_fallback_and_non_mapping(self):
        value = {'strings': ['0x01', '+0x1', '0XFF', '-0x0', '001', '1e3', 'é\ud800'],
                 'q': ['0x2', '0x4'], 'float': -0.0, 'null': None, 'unknown_domain_field': {'x': 1}}
        record = self.pack(value)
        self.assertEqual(streamed(record, 3), T.canonical(value))
        root = record.root()
        self.assertFalse(isinstance(root, (Mapping, Sequence)))
        with self.assertRaises(TypeError):
            dict(root)
        with self.assertRaises(KeyError):
            root.field('absent')
        null = root.field('null')
        with null.scalar(max_owned_bytes=16384) as held:
            self.assertIsNone(held.value)
        null.close(); root.close(); record.close()

    def test_export_refusal_preallocation_and_composite_identity(self):
        value = dict(a=[1, 2, 3], nested={'key': 'value'})
        record = self.pack(value)
        before = self.scope.stats().retained_bytes
        with self.assertRaises(ContractError):
            record.export(max_logical_bytes=1, max_owned_bytes=1 << 20)
        self.assertEqual(before, self.scope.stats().retained_bytes)
        with record.export(max_logical_bytes=1 << 20, max_owned_bytes=1 << 20) as exported:
            self.assertEqual(exported.value, value)
            self.assertGreater(self.scope.stats().retained_bytes, before)
        exchange = LogicalExchange(record, record._root)
        expected = T.canonical(dict(state_id='a'*64, exchange=value))
        identity = exchange.composite_identity('a'*64)
        self.assertEqual(identity.sha256, sha256(expected).hexdigest())
        self.assertEqual(identity.canonical_bytes, len(expected))
        exchange.close(); record.close()

    def test_shape_interning_narrow_indices_and_payload_roundtrip(self):
        value = [dict(a=i, b=['0x1', '0x2']) for i in range(20)]
        record = self.pack(value)
        with record.storage_payload() as held:
            metadata, arrays = held.value
            self.assertEqual(len(arrays['shape.offset']), 2)
            self.assertEqual(arrays['node.payload'].dtype.str, '|u1')
            restored = CompactRecord.from_payload(metadata, arrays, scope=self.scope, check=lambda: None)
            self.assertEqual(streamed(restored), T.canonical(value))
            restored.close()
        record.close()

    def test_unknown_corrupt_schema_shape_order_and_node_refusal(self):
        record = self.pack({'a': 1, 'b': 2})
        with record.storage_payload() as held:
            metadata, arrays = held.value
            parsed = json.loads(metadata)
            for key, bad in [('schema', 'future'), ('features', ['unknown']), ('profile', 'future')]:
                changed = deepcopy(parsed); changed[key] = bad
                with self.assertRaises(ContractError):
                    CompactRecord.from_payload(T.canonical(changed), arrays, scope=self.scope, check=lambda: None)
            for name, mutate in [('node.kind', lambda a: a.__setitem__(-1, 255)),
                                 ('shape.key', lambda a: a.__setitem__(slice(None), a[::-1])),
                                 ('edge.child', lambda a: a.__setitem__(0, len(arrays['node.kind'])-1))]:
                altered = dict(arrays); altered[name] = arrays[name].copy(); mutate(altered[name])
                changed = deepcopy(parsed)
                changed['arrays'][name]['sha256'] = sha256(altered[name].tobytes()).hexdigest()
                with self.assertRaises(ContractError):
                    CompactRecord.from_payload(T.canonical(changed), altered, scope=self.scope, check=lambda: None)
        record.close()

    def test_cancel_leaves_no_record_and_no_budget_leak(self):
        calls = 0
        def check():
            nonlocal calls
            calls += 1
            if calls == 9:
                raise CancelledError()
        with self.assertRaises(CancelledError):
            self.codec.pack_record([{'a': i} for i in range(100)], record_schema='test.v1', scope=self.scope, check=check)

    def test_owner_children_rows_and_yielded_blocks_remain_charged(self):
        record = self.pack([dict(a=i, nested=[i]*3) for i in range(9)])
        root = record.root()
        with self.assertRaises(RuntimeError):
            record.close()
        stream = root.iter_rows(max_rows=2, max_owned_bytes=32768, fields=['a'])
        rows = next(stream)
        self.assertEqual(len(rows.value), 2)
        with self.assertRaises(KeyError):
            rows.value[0].field('nested')
        stream.close()
        for row in rows.value:
            child = row.field('a')
            with child.scalar(max_owned_bytes=16384) as held:
                self.assertIsInstance(held.value, int)
            child.close(); row.close()
        rows.close()
        blocks = record.iter_json(max_chunk_bytes=16)
        escaped = next(blocks)
        blocks.close()
        root.close(); record.close()
        self.assertGreater(self.scope.stats().retained_bytes, 0)
        self.assertTrue(escaped.value)
        escaped.close()

    def test_200mb_graph_second_copy_under_three_percent(self):
        # More than 200 MB of logical graph, bounded input memory, exact ordered
        # duplicate graph fields. This exercises actual streaming, not a size claim.
        row = {'id': 'a'*64, 'receipt': 'x'*4096, 'q': ['0x123456789abcdef', '0x10000000000000000']}
        graph = {'cells': [row]*48_000}
        one = self.pack(graph)
        self.assertGreater(one.identity().canonical_bytes, 200_000_000)
        expected = sha256()
        for token in json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                                      allow_nan=False).iterencode(graph):
            expected.update(token.encode('ascii'))
        self.assertEqual(one.identity().sha256, expected.hexdigest())
        single_logical_bytes = one.identity().canonical_bytes
        with one.storage_payload() as held:
            first_bytes = sum(a.nbytes for a in held.value[1].values())
        one.close()
        double = self.pack({'graph': graph, 'finite_graph': graph})
        with double.storage_payload() as held:
            second_bytes = sum(a.nbytes for a in held.value[1].values())
        self.assertLessEqual(second_bytes-first_bytes, first_bytes*0.03)
        self.assertEqual(double.identity().canonical_bytes, 2*(4+len('"cells":')+48_000*len(T.canonical(row))+47_999)+len('{"finite_graph":,"graph":}'))
        print(json.dumps(dict(wp2_graph_logical_bytes=single_logical_bytes,
            first_columns_bytes=first_bytes, second_columns_bytes=second_bytes,
            incremental_column_ratio=(second_bytes-first_bytes)/first_bytes,
            peak_run_reserved_bytes=self.budget.peak_reserved_bytes,
            peak_retained_bytes=self.scope.stats().peak_retained_bytes), sort_keys=True))
        double.close()

    def test_fixed_builder_and_row_workspace_ceilings(self):
        # The fixed ceilings are unchanged and still refuse before allocation;
        # they now apply to honest (measured) bookings, so the bounds are
        # exercised with the ceilings patched down rather than with inputs that
        # only refused because of the old 32 B/character booking.
        from unittest.mock import patch
        from atlas_tectonics.resources import MemoryLimitError
        self.assertEqual((T.MAX_BUILD_BYTES, T.MAX_ROW_WORK_BYTES, T.MAX_DEPTH), (256 << 20, 32 << 20, 128))
        with self.assertRaisesRegex(ContractError, 'container count exceeds bound'):
            self.pack([None]*(T.MAX_ITEMS+1))
        with patch.object(T, 'MAX_ROW_WORK_BYTES', 1 << 16):
            before = self.budget.peak_reserved_bytes
            with self.assertRaisesRegex(ContractError, 'row workspace exceeds'):
                self.pack({'k%05d' % i: i for i in range(4000)})
            self.assertLess(self.budget.peak_reserved_bytes-before, 4 << 20)
        with patch.object(T, 'MAX_BUILD_BYTES', 2 << 20):
            with self.assertRaises(MemoryLimitError):
                self.pack([str(i)*3 for i in range(60_000)])
        gc.collect()
        # The 8 MiB+1 string the old booking refused is spilled, not resident.
        record = self.pack('x'*(T.MAX_BUILD_BYTES//32+1))
        self.assertEqual(record.identity().canonical_bytes, T.MAX_BUILD_BYTES//32+3)
        self.assertLess(self.budget.peak_reserved_bytes, 24 << 20)
        record.close()

    def test_child_close_and_failed_stream_retains_allocations(self):
        record = self.pack({'array': [1, 2, 3]})
        root = record.root(); child = root.field('array')
        with self.assertRaises(RuntimeError):
            root.close()
        child.close(); root.close(); record.close()
        error = None
        calls = 0
        def check():
            nonlocal calls
            calls += 1
            if calls == 8:
                raise CancelledError('held failure')
        try:
            self.codec.pack_record({'values': ['x'*2048]*10}, record_schema='test.v1',
                                   scope=self.scope, check=check)
        except CancelledError as failure:
            error = failure
        self.assertIsNotNone(error)
        self.assertGreater(self.budget.reserved_bytes, self.scope.stats().retained_bytes)
        error.__traceback__ = None
        del error


if __name__ == '__main__':
    unittest.main()
