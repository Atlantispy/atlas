"""Regression checks for plain, fully charged compact support headers.
Uses real record-reference owners and synthetic record values; forged headers must be reported.
"""
import copy
import dataclasses
import gc
import unittest
from types import SimpleNamespace
from unittest import mock

import content_cache as CC
import mesh_tables as M
import partition_routing_patch as RP
from atlas_tectonics.resources import WorkBudget
from record_views import RecordRef

VALUES = {'interval_id': 'f0' * 32, 'start_time_s': ['0x2f00cbfcd7c08aad8918ab19af', '0x1'], 'end_time_s': 1.5e9}


class HeaderRetention(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(64 << 20)
        self.scope = CC.create_retained_scope(self.budget, process_epoch='plan18-compact-header-retention')
        self.view = SimpleNamespace(name='view')
        self.record = self.commit('record-view')
        self.selection = self.commit('record-selection')
        self.ref = object.__new__(RecordRef)
        self.ref._view, self.ref.index, self.ref._fields = self.view, 0, None
        self.ref._owner, self.ref._selection_owner = self.record.retain(), self.selection.retain()
        self.exported = 0
        self.support = SimpleNamespace(_resource=self.budget, support_id='s'*64, _json=b'{}')
        patches = (mock.patch.object(RP, '_bound_ref', lambda support: self.ref),
                   mock.patch.object(RP.P, '_view_fields', self.view_fields),
                   mock.patch.object(RP, '_routing', lambda: SimpleNamespace(_decoded_json_capacity=lambda raw: 4096)))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.ref.close()
        del self.ref, self.record, self.selection
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())

    def commit(self, purpose):
        return self.scope.reserve(CC.ChargeSpec(purpose, 1024)).commit(bytearray(8))

    def exports_booked(self):
        return self.scope.retained_budget.statistics()['categories'].get('retained:record-export', 0)

    def view_fields(self, view, ref, fields):
        # The shape of partition_native_patch._view_fields's RecordRef branch: values, (estimate, exports, view).
        self.assertIs(view, self.view)
        self.assertIs(ref, self.ref)
        self.assertEqual(tuple(fields), RP.HEADER)
        exports = tuple(self.commit('record-export') for _ in fields)
        self.exported += len(exports)
        estimate = M._Allocation(self.budget, 4096+512*len(fields))
        return M.OwnedRow(copy.deepcopy(VALUES), (estimate, exports, view))

    def forged(self, handle, header):
        result = object.__new__(RP.CompactSupport)
        for field in dataclasses.fields(RP.CompactSupport):
            object.__setattr__(result, field.name, header if field.name == '_header' else getattr(handle, field.name))
        return result

    def test_built_header_is_plain_complete_and_charged_at_its_measured_size(self):
        before = self.budget.reserved_bytes
        handle = RP.retain_support(self.support)
        gc.collect()
        self.assertTrue(self.exported and self.exports_booked() == 0, 'an export stayed booked')
        self.assertEqual(handle._header.value, VALUES)
        allocation, view = handle._header._owner
        self.assertIs(type(allocation), M._Allocation)
        self.assertIs(view, self.view)
        self.assertEqual(allocation.size, RP._plain_bytes(handle._header.value))
        self.assertEqual(self.budget.reserved_bytes - before, 4096+allocation.size)
        self.assertEqual(RP.retained_header_problems(handle), [])
        gc.collect()
        self.assertEqual(self.exports_booked(), 0, 'the check left an export booked')

    def test_forged_headers_are_reported(self):
        handle = RP.retain_support(self.support)
        values = handle._header.value
        size = RP._plain_bytes(values)
        dropped = {key: value for key, value in values.items() if key != 'end_time_s'}
        fresh = RP.P._view_fields(self.view, self.ref, RP.HEADER)
        cases = {
            'dropped field': (M.OwnedRow(dropped, (M._Allocation(self.budget, size), self.view)), 'differ'),
            'export owner kept': (M.OwnedRow(fresh.value, fresh._owner), 'export owner'),
            'undercharged': (M.OwnedRow(copy.deepcopy(values), (M._Allocation(self.budget, 1), self.view)), 'below'),
            'non-plain value': (M.OwnedRow(dict(values, end_time_s=object()),
                                           (M._Allocation(self.budget, size), self.view)), 'plain'),
        }
        del fresh
        for name, (header, words) in cases.items():
            with self.subTest(name):
                problems = RP.retained_header_problems(self.forged(handle, header))
                self.assertTrue(any(words in problem for problem in problems), problems)
        del cases, handle


if __name__ == '__main__':
    unittest.main()
