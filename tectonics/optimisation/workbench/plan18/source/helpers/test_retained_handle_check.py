"""Retained-header and ownership-graph regression controls.
Uses real owners and shares with synthetic records. Unavailable references are reported before the
real field reader is called; unrelated reader failures propagate. Tests cover key/value forgeries,
charges, ownership, closed references and missing scope or view.
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
REAL_VIEW_FIELDS = RP.P._view_fields  # taken at import, before any test patches it


class RetainedHandleCheck(unittest.TestCase):
    def setUp(self):
        self.run = WorkBudget(64 << 20)
        self.scope = CC.create_retained_scope(self.run, process_epoch='plan18-retained-handle-check')
        self.view = SimpleNamespace(name='view')
        self.record = self.commit('record-view')
        self.selection = self.commit('record-selection')
        self.ref = self.reference()
        self.values = copy.deepcopy(VALUES)
        self.support = SimpleNamespace(_resource=self.run, support_id='s' * 64, _json=b'{}')
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
        self.assertEqual(self.run.reserved_bytes, 0, self.run.statistics())

    def commit(self, purpose):
        return self.scope.reserve(CC.ChargeSpec(purpose, 1024)).commit(bytearray(8))

    def reference(self, fields=None, owner=None):
        """A RecordRef as record_views builds it: a retained share of the record owner and of the selection."""
        ref = object.__new__(RecordRef)
        ref._view, ref.index, ref._fields = self.view, 0, fields
        ref._owner = owner if owner is not None else self.record.retain()
        ref._selection_owner = self.selection.retain()
        return ref

    def view_fields(self, view, ref, fields):
        # The shape of partition_native_patch._view_fields's RecordRef branch: values, (estimate, exports, view).
        exports = tuple(self.commit('record-export') for name in fields if name in self.values)
        estimate = M._Allocation(self.run, 4096 + 512 * len(fields))
        return M.OwnedRow({name: copy.deepcopy(self.values[name]) for name in fields if name in self.values},
                          (estimate, exports, view))

    def forged(self, handle, *, header=None, ref=None):
        result = object.__new__(RP.CompactSupport)
        for field in dataclasses.fields(RP.CompactSupport):
            value = getattr(handle, field.name)
            value = header if field.name == '_header' and header is not None else value
            value = ref if field.name == '_ref' and ref is not None else value
            object.__setattr__(result, field.name, value)
        return result

    def row(self, values, size=None, budget=None):
        size = RP._plain_bytes(values) if size is None else size
        return M.OwnedRow(values, (M._Allocation(budget or self.run, size), self.view))

    def test_built_handle_has_no_problems(self):
        handle = RP.retain_support(self.support)
        gc.collect()
        self.assertEqual(self.scope.retained_budget.statistics()['categories'].get('retained:record-export', 0), 0)
        self.assertEqual(RP.retained_header_problems(handle), [])

    def test_forged_headers_are_reported(self):
        handle = RP.retain_support(self.support)
        values = handle._header.value
        released = M._Allocation(self.run, RP._plain_bytes(values))
        guard, released.guard = released.guard, None
        guard.__exit__(None, None, None)
        other = WorkBudget(1 << 20)
        fresh = RP.P._view_fields(self.view, self.ref, RP.HEADER)
        cases = {
            'dropped field': (self.row({k: v for k, v in values.items() if k != 'end_time_s'}), 'keys'),
            'int for float': (self.row(dict(values, end_time_s=1500000000)), 'differ'),
            'export owner kept': (M.OwnedRow(fresh.value, fresh._owner), 'export owner'),
            'undercharged': (self.row(copy.deepcopy(values), size=1), 'below'),
            'non-plain value': (self.row(dict(values, end_time_s=object()), size=4096), 'plain'),
            'released allocation': (M.OwnedRow(copy.deepcopy(values), (released, self.view)), 'released'),
            'other budget': (self.row(copy.deepcopy(values), budget=other), 'support budget'),
        }
        for name, (header, words) in cases.items():
            with self.subTest(name):
                problems = RP.retained_header_problems(self.forged(handle, header=header))
                self.assertTrue(any(words in problem for problem in problems), problems)
        del cases, fresh

    def test_values_are_compared_as_canonical_bytes(self):
        self.values['end_time_s'] = 0.0
        handle = RP.retain_support(self.support)
        for name, value in (('negative zero', -0.0), ('int zero', 0), ('false', False)):
            with self.subTest(name):
                problems = RP.retained_header_problems(self.forged(handle, header=self.row(
                    dict(handle._header.value, end_time_s=value))))
                self.assertTrue(any('differ' in problem for problem in problems), problems)

    def test_field_missing_from_header_and_record_is_reported(self):
        del self.values['end_time_s']
        handle = RP.retain_support(self.support)
        problems = RP.retained_header_problems(handle)
        self.assertTrue(any('header keys' in problem for problem in problems), problems)
        self.assertTrue(any('support record keys' in problem for problem in problems), problems)

    def test_forged_ownership_graphs_are_reported(self):
        handle = RP.retain_support(self.support)
        released = self.record.retain()
        released._carrier.close()
        cases = {
            'record export reachable through fields': (self.reference(fields=(self.commit('record-export'),)),
                                                       'record-export'),
            'extra carrier reachable through fields': (self.reference(fields=(self.record.retain(),)),
                                                       'carriers are reachable'),
            'released reference carrier': (self.reference(owner=released), 'released'),
        }
        try:
            for name, (ref, words) in cases.items():
                with self.subTest(name):
                    problems = RP.retained_header_problems(self.forged(handle, ref=ref))
                    self.assertTrue(any(words in problem for problem in problems), problems)
        finally:
            for ref, _ in cases.values():
                ref.close()
            del cases, released

    def test_reference_without_a_scope_is_reported_not_raised(self):
        handle = RP.retain_support(self.support)
        problems = RP.retained_header_problems(self.forged(handle, ref=SimpleNamespace(_view=self.view)))
        self.assertTrue(any('scope unavailable' in problem for problem in problems), problems)

    def test_mixed_key_types_are_reported_not_raised(self):
        handle = RP.retain_support(self.support)
        values = dict(handle._header.value)
        values[1] = 'one'
        problems = RP.retained_header_problems(self.forged(handle, header=self.row(values, size=4096)))
        self.assertTrue(any('header keys' in problem for problem in problems), problems)

    def unmocked(self, handle, ref):
        """retained_header_problems on handle with ref, through the real partition_native_patch._view_fields."""
        with mock.patch.object(RP.P, '_view_fields', REAL_VIEW_FIELDS):
            return RP.retained_header_problems(self.forged(handle, ref=ref))

    def test_closed_record_reference_is_reported_through_the_real_reader(self):
        handle = RP.retain_support(self.support)
        ref = self.reference()
        ref.close()
        problems = self.unmocked(handle, ref)
        self.assertTrue(any(problem == 'record reference unavailable: closed owner' for problem in problems), problems)
        self.assertTrue(any('scope unavailable' in problem for problem in problems), problems)

    def test_reference_without_a_scope_is_reported_through_the_real_reader(self):
        handle = RP.retain_support(self.support)
        problems = self.unmocked(handle, SimpleNamespace(_view=self.view))
        self.assertTrue(any(problem.startswith('record reference unavailable: ') and 'row' in problem
                            for problem in problems), problems)
        self.assertTrue(any('scope unavailable' in problem for problem in problems), problems)

    def test_reference_without_a_view_is_reported_through_the_real_reader(self):
        handle = RP.retain_support(self.support)
        problems = self.unmocked(handle, SimpleNamespace())
        self.assertTrue(any(problem.startswith('record reference unavailable: ') and '_view' in problem
                            for problem in problems), problems)
        self.assertTrue(any('owner is not exactly' in problem for problem in problems), problems)

    def test_an_error_inside_the_read_propagates(self):
        handle = RP.retain_support(self.support)

        def failing(view, ref, fields):
            raise RuntimeError('failed inside the read')
        with mock.patch.object(RP.P, '_view_fields', failing):
            with self.assertRaisesRegex(RuntimeError, 'failed inside the read'):
                RP.retained_header_problems(handle)


if __name__ == '__main__':
    unittest.main()
