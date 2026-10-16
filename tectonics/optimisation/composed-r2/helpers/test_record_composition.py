"""Shared Step 6 views: exact identity and bounded imports, without Mapping."""
from collections.abc import Mapping
import gc
from hashlib import sha256
import unittest
import sys
from unittest.mock import patch

import test_record_tables as fixtures
from compact_contracts import ContractError
from content_cache import create_retained_scope
from atlas_tectonics.resources import WorkBudget
from record_views import RecordRef, LogicalExchange
import record_tables as T


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(3 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='step6-compose')

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def pack(self, value):
        return T.RecordCodec().pack_record(value, record_schema='test.v1',
                                          scope=self.scope, check=lambda: None)

    def test_overlay_projection_and_import_preserve_canonical_identity(self):
        graph = {'cells': [{'id': 'a'*64, 'q': ['0x2', '0x4'], 's': 'é\ud800'}]*5}
        value = {'graph': graph, 'finite': graph, 'time': -0.0}
        record = self.pack(value)
        exchange = LogicalExchange.from_body(record, state_id='b'*64, result_id='c'*64)
        expected = dict(value, state_id='b'*64, result_id='c'*64)
        self.assertFalse(isinstance(exchange, Mapping))
        self.assertEqual(fixtures.streamed(exchange, 7), T.canonical(expected))
        body = exchange.body()
        self.assertEqual(body.identity().sha256, record.identity().sha256)
        self.assertEqual(body.composite_identity('b'*64).sha256,
                         sha256(T.canonical({'state_id': 'b'*64, 'exchange': value})).hexdigest())
        # Repacking imports only shallow views/scalars; no container export.
        with patch.object(RecordRef, 'export', side_effect=AssertionError('container expansion')):
            imported = self.pack({'first': body, 'second': body})
        self.assertEqual(fixtures.streamed(imported), T.canonical({'first': value, 'second': value}))
        with imported.storage_payload() as held:
            _, arrays = held.value
            self.assertEqual(len(arrays['float.value']), 1)
        imported.close()
        body.close(); exchange.close(); record.close()

    def test_compose_children_without_reencoding_and_escaping_child(self):
        record = self.pack({'id': 1, 'payload': [1, 2]})
        root = record.root()
        header = root.select(('id',))
        child = root.field('payload')
        merged = LogicalExchange.from_records(header, payload=child)
        self.assertEqual(fixtures.streamed(merged), T.canonical({'id': 1, 'payload': [1, 2]}))
        escaped = merged.field('payload')
        with self.assertRaises(RuntimeError):
            child.close()
        merged.close()
        with escaped.at(0) as first, first.scalar(max_owned_bytes=65536) as scalar:
            self.assertEqual(scalar.value, 1)
        escaped.close(); child.close(); header.close(); root.close(); record.close()

    def test_explicit_small_values_and_refusal_bounds(self):
        record = self.pack({'rows': [1], 'name': 'test'})
        root = record.root()
        with root.keys() as keys:
            self.assertEqual(keys.value, ('name', 'rows'))
        with root.get('name') as name:
            self.assertEqual(name.value, 'test')
        with root.get('missing', 3) as missing:
            self.assertEqual(missing.value, 3)
        with root.get('rows') as rows:
            self.assertIsInstance(rows, RecordRef)
        for call in (lambda: root.keys(max_owned_bytes=0),
                     lambda: root.select(('absent',)),
                     lambda: root.select(('name', 'name'))):
            with self.assertRaises((ContractError, KeyError)):
                call()
        gc.collect()
        selected = root.select(('name',))
        with self.assertRaises(ContractError):
            selected.export(max_logical_bytes=1, max_owned_bytes=65536)
        selected.close(); root.close(); record.close()

    def test_foreign_scope_import_refuses(self):
        other_budget = WorkBudget(1 << 30)
        other_scope = create_retained_scope(other_budget, process_epoch='step6-foreign')
        record = T.RecordCodec().pack_record([1], record_schema='test.v1',
                                            scope=other_scope, check=lambda: None)
        root = record.root()
        with self.assertRaises(ContractError):
            self.pack(root)
        root.close(); record.close()
        gc.collect(); other_scope.close()
        self.assertEqual(other_budget.reserved_bytes, 0)

    def test_direct_export_funds_actual_python_objects_and_preserves_independence(self):
        pair = [hex(1 << 4096), hex((1 << 4096)+3)]
        value = {'empty': [[] for _ in range(100)], 'q': [pair]*100,
                 'wide': ['ascii'*300+'\U0001f600']*40,
                 'rows': [{'\u0100': i, 'float': -0.0, 'bool': True} for i in range(100)]}
        record = self.pack(value)
        with record.export(max_logical_bytes=4 << 20, max_owned_bytes=4 << 20) as held:
            self.assertEqual(held.value, value)
            seen, pending, actual = set(), [held.value], 0
            while pending:
                item = pending.pop()
                if id(item) in seen:
                    continue
                seen.add(id(item))
                actual += sys.getsizeof(item)
                if type(item) is dict:
                    pending.extend(item)
                    pending.extend(item.values())
                elif type(item) is list:
                    pending.extend(item)
            self.assertLessEqual(actual, held.charged_bytes)
            held.value['q'][0][0] = 'changed'
            self.assertEqual(held.value['q'][1], pair)
        self.assertEqual(fixtures.streamed(record), T.canonical(value))
        record.close()


if __name__ == '__main__':
    unittest.main()
