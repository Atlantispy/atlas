"""Compact parent selection and coupling composition; no solve or acceptance.

Uses the composed temporary package and actual tiny owners of
test_geometry_transfer_compact. Parent bodies are SYNTHETIC native-schema
fixtures, not historical-reader or scientific acceptance receipts.
"""
import ast
from copy import deepcopy
import gc
from hashlib import sha256
import unittest
from unittest import mock

import continuation_transfer as X
import test_continuation_transfer as TC
import test_geometry_transfer_compact as GC
import test_native_transfer as TN


def setUpModule():
    GC.install('ctc-')


def tearDownModule():
    GC.uninstall()


def _digest(text):
    return sha256(text.encode('utf8')).hexdigest()


class CouplingCompositionTests(unittest.TestCase):
    def test_coupling_composes_after_partition_reader_to_pinned_digest(self):
        frozen = (TN.BASE/'integration_differential_coupling.py').read_text(encoding='utf8')
        reader = GC.PN.transform_coupling(frozen)
        composed = X.coupling_source(reader)
        compile(composed, '<composed-coupling>', 'exec')
        self.assertEqual((_digest(frozen), _digest(reader), _digest(composed)),
            (X.COUPLING_SOURCE_SHA256, X.COUPLING_COMPACT_SOURCE_SHA256, X.COUPLING_COMPACT_RESULT_SHA256))
        self.assertEqual(GC.STAGES['coupling_compact'], X.COUPLING_COMPACT_RESULT_SHA256)
        # Erasing only the capability plumbing restores the reader input exactly.
        restored = TC.RemovePlumbing().visit(ast.parse(composed))
        self.assertEqual(ast.dump(ast.parse(reader)), ast.dump(restored))
        # The ordinary frozen input keeps its reviewed, unpinned-output route.
        self.assertEqual(_digest(X.coupling_source(frozen)),
                         'ef9bd662bb47993f3f0258edd0cad46ece2455ee5d3a3daced8e1bb87ca4f9f1')
        for source in (composed, X.coupling_source(frozen), reader+'\n', frozen+'\n'):
            with self.subTest(source=_digest(source)[:12]):
                with self.assertRaises(X.ContinuationTransferRefused):
                    X.coupling_source(source)
        with self.assertRaises(ValueError):
            GC.PN.transform_coupling(X.coupling_source(frozen))
        # An admitted input whose edits no longer give the pinned result refuses.
        with mock.patch.object(X, 'COUPLING_COMPACT_RESULT_SHA256', '0'*64):
            with self.assertRaises(X.ContinuationTransferRefused):
                X.coupling_source(reader)


class CompactParentSelectionTests(GC.CompactParentFixture, unittest.TestCase):
    def test_select_parent_transfer_exact_current_and_foreign_compact_parents(self):
        view = GC.compact(self.body, self.supports, self.budget)
        bridge = self.bind(view)
        parent = self.admit(view, bridge)
        operands = (self.funding, self.collar, self.budget)
        self.assertIsNone(X.select_parent_transfer(parent, *operands, None))
        decode = mock.patch('workflow_transfer._decode_allocation',
                            side_effect=AssertionError('compact marker _json decoded as a body'))
        with decode, mock.patch.object(GC.PT.CompactPartition, 'legacy_record',
                                      side_effect=AssertionError('compact parent exported')):
            self.assertIs(X.select_parent_transfer(parent, *operands, bridge), bridge)
        for args in ((parent, *operands, object()), (parent, object(), self.collar, self.budget, bridge),
                     (parent, self.funding, self.collar, GC.WorkBudget(1 << 20), bridge)):
            with self.subTest(args=[type(a).__name__ for a in args[1:]]):
                with self.assertRaises(X.ContinuationTransferRefused):
                    X.select_parent_transfer(*args)
        # A current-plan compact parent stays on the strict default route.
        current_view = GC.compact(dict(deepcopy(self.body), collar_plan_id=self.collar.plan_id),
                                  self.supports, self.budget)
        current = self.admit(current_view)
        self.assertIsNone(X.select_parent_transfer(current, *operands, bridge))
        # Another exact parent is admitted by its own binding, never this one.
        body_b, supports_b = GC.foreign_parent(self.body, self.supports)
        foreign_view = GC.compact(body_b, supports_b, self.budget)
        foreign_bridge = self.bind(foreign_view)
        foreign = self.admit(foreign_view, foreign_bridge)
        with self.assertRaises(X.ContinuationTransferRefused):
            X.select_parent_transfer(foreign, *operands, bridge)
        with self.assertRaises(X.ContinuationTransferRefused):
            X.select_parent_transfer(parent, *operands, foreign_bridge)
        self.assertIs(X.select_parent_transfer(foreign, *operands, foreign_bridge), foreign_bridge)
        # The compact-issued binding still selects the same legacy parent.
        legacy = self.restore(bridge)
        self.assertIs(X.select_parent_transfer(legacy, *operands, bridge), bridge)
        self.assertEqual(self.collar._native.statistics()['accepted_intervals'], 0)
        categories = self.budget.statistics()['categories']
        self.assertEqual(categories.get('geometry-transfer-match-scratch', 0), 0)
        del view, bridge, parent, current_view, current, foreign_view, foreign_bridge, foreign, legacy, args
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, self.baseline)


if __name__ == '__main__':
    unittest.main(verbosity=2)
