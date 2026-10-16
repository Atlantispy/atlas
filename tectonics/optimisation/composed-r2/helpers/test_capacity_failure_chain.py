"""Capacity harness failure records name the first-raised stop and release the whole chain.

A stop (guard or cancel) raised inside nested record decoding was followed by
close refusals from the unwinding RecordRef wrappers: an owned key inventory
keeps its dependency borrow while its failed frame is alive, so the enclosing
RecordRef.__exit__ refused to close its owner. The harness therefore records
the first-raised exception of the chain and clears the frames of every
traceback in it, so that the scope closes without a collection (the
measurement runs with gc disabled). Seen in capacity-claude-iv1-combined-r2
(16 Oct 2026): the guard's free-memory stop was recorded as "owner has live
child borrows" and cleanup then failed on the still-held borrows.

Since R1a's generation RecordRef.__exit__ retires its owners on a failure path
(each closes when its last borrower drops), so the stop itself propagates; the
unmodified exit (close on every path) is kept below as the mutant.

R1 (same generation): an ordinary reference now decodes straight from the
columns, with no nested RecordRefs or key inventories, so on that route no
child borrow exists for a closing exit to trip over. Composites
(_ObjectRecordRef: from_records/select/without) still decode through owned key
inventories and child wrappers, so the mutant demonstrations below run on a
composite whose 'outer' member is itself a composite.
"""
import gc
import traceback
import unittest
from concurrent.futures import CancelledError
from unittest.mock import patch

import measure_live_capacity as CAP
import record_views
from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope
from record_tables import RecordCodec

# Over the 32 KiB small-row fast path (one C JSON decode, no nested wrappers),
# so the export takes the structural route through nested RecordRefs as the
# authentic mesh supports do.
VALUE = {'outer': {'middle': {'inner': list(range(6)), 'tag': 'x'}, 'other': [1, 2, 3]},
         'side': {'deep': {'deeper': {'leaf': 'y'}}}, 'top': 7, 'blob': 'z'*40000}


def _support_shell(root):
    """A SupportSource whose one support is a borrow of ``root`` (open() checks the type)."""
    from support_source import SupportSource
    source = object.__new__(SupportSource)
    source.ref_for = lambda identity: root.borrow()
    return source


def support_open(root, ref=None):
    """The export through mesh_tables.SharedSupportRecord.open, as the mesh supports use it."""
    from mesh_tables import SharedSupportRecord
    return SharedSupportRecord(view=_support_shell(root if ref is None else ref), identity='s'*64).open()


def old_support_open(root, ref=None):
    """The pre-16-Oct open() body (close in ``finally``): the mutant the fix removes."""
    from mesh_tables import MAX_SUPPORT_BYTES
    ref = _support_shell(root if ref is None else ref).ref_for('s'*64)
    try:
        return ref.export(max_logical_bytes=MAX_SUPPORT_BYTES, max_owned_bytes=256 << 20)
    finally:
        ref.close()


class Composite:
    """{'outer': <composite over outer>, other members from root}: the remaining wrapper route.

    Built before the stop is armed; ``close`` releases it after a success.
    After a failure the failed frames own it until their tracebacks are freed.
    """
    def __init__(self, root):
        self.outer = root.field('outer')
        self.inner = self.outer.without(())
        self.ref = record_views.LogicalExchange.from_records(root, outer=self.inner)

    def export(self, root):
        return self.ref.export(max_logical_bytes=1 << 20, max_owned_bytes=16 << 20)

    def support_open(self, root):
        return support_open(root, ref=self.ref)

    def old_support_open(self, root):
        return old_support_open(root, ref=self.ref)

    def close(self):
        self.ref.close()
        self.inner.close()
        self.outer.close()


def closing_exit(self, *_):
    """RecordRef.__exit__ before R1a's generation (close on every path): the mutant the fix removes."""
    self.close()


def clear_frames(chain):
    for item in chain:
        traceback.clear_frames(item.__traceback__)
        item.__traceback__ = None


def clear_chain(error, *, whole=True):
    """The harness's handling; ``whole=False`` is the previous last-traceback-only mutant."""
    chain = CAP.exception_chain(error)
    first, kinds = chain[-1], tuple(type(item).__name__ for item in chain)
    clear_frames(chain if whole else chain[:1])
    return first, kinds, () if whole else tuple(chain[1:])


class CapacityFailureChainTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='capacity-failure-chain-test')

    def tearDown(self):
        gc.collect()

    def export_with_stop(self, stop_at, *, whole=True, export=None, composite=False):
        """Export the nested record with a stop at the stop_at-th check; None if it never fires.

        ``composite``: export through a Composite built before the stop is
        armed; ``export`` then names its method ('export', 'support_open' or
        'old_support_open').
        """
        calls, armed = 0, False

        def check():
            nonlocal calls
            if armed:
                calls += 1
                if calls == stop_at:
                    raise CancelledError('stop inside nested decode')

        record = RecordCodec().pack_record(VALUE, record_schema='test.capacity-chain.v1',
                                           scope=self.scope, check=check)
        root = record.root()
        made = Composite(root) if composite else None
        if made is not None:
            export = getattr(made, export or 'export')
        armed = True
        result = None
        try:
            exported = (root.export(max_logical_bytes=1 << 20, max_owned_bytes=16 << 20)
                        if export is None else export(root))
        except BaseException as error:  # noqa: BLE001 - the recorded chain is the subject
            result = clear_chain(error, whole=whole)
        else:
            self.assertEqual(exported.value, VALUE)
            exported.close()
            if made is not None:
                made.close()
        armed = False
        # After a failure only the failed frames (and so the recorded chain) own the composite.
        del made, export
        return record, root, result

    def test_every_stop_point_names_the_stop_and_releases_without_collection(self):
        baseline = self.budget.reserved_bytes
        for composite in (False, True):      # R1: the ordinary column route and the composite wrapper route
            stops, masked = 0, 0
            gc.disable()
            try:
                for stop_at in range(1, 2000):
                    record, root, result = self.export_with_stop(stop_at, composite=composite)
                    fired = result is not None
                    if result is not None:
                        first, kinds, _ = result
                        stops += 1
                        masked += len(kinds) > 1
                        self.assertIs(type(first), CancelledError, (stop_at, kinds))
                        self.assertEqual(str(first), 'stop inside nested decode')
                        del first
                    result = None
                    # With every traceback frame cleared, the refused wrappers have
                    # lost their last references, so the owners close and the scope
                    # returns to its baseline without any collection.
                    root.close()
                    record.close()
                    del root, record
                    self.assertEqual(self.budget.reserved_bytes, baseline, (composite, stop_at))
                    if not fired:      # stop_at passed the last check: every point was covered
                        break
            finally:
                gc.enable()
            self.assertGreater(stops, 10, composite)
            # RecordRef exits retire instead of close on a failure path (R1a's
            # generation), so no stop point is masked by a close refusal any more.
            self.assertEqual(masked, 0, composite)

    def test_clearing_only_the_last_traceback_keeps_borrows(self):
        """Why the whole chain is cleared: the earlier tracebacks hold the borrows.

        Run with the unmodified exit (the mutant), which still builds such chains;
        it also shows the masking the retiring exit removes. R1: on the
        composite route, the one that still nests wrappers.
        """
        baseline = self.budget.reserved_bytes
        refused = 0
        gc.disable()
        try:
            with patch.object(record_views.RecordRef, '__exit__', closing_exit):
                for stop_at in range(1, 2000):
                    record, root, result = self.export_with_stop(stop_at, whole=False, composite=True)
                    if result is None:
                        root.close()
                        record.close()
                        break
                    first, kinds, held = result
                    result = None
                    if len(kinds) > 1:
                        self.assertEqual(kinds[0], 'RuntimeError', stop_at)
                        with self.assertRaisesRegex(RuntimeError, 'live child borrows'):
                            root.close()
                        refused += 1
                    clear_frames(held)
                    del first, held
                    root.close()
                    record.close()
                    del root, record
                    self.assertEqual(self.budget.reserved_bytes, baseline, stop_at)
        finally:
            gc.enable()
        self.assertGreater(refused, 0)

    def chain_length(self, stop_at, export=None, composite=False):
        record, root, result = self.export_with_stop(stop_at, export=export, composite=composite)
        root.close()
        record.close()
        del root, record
        return None if result is None else len(result[1])

    def test_support_open_adds_no_close_refusal_after_a_failed_export(self):
        """SharedSupportRecord.open closes only after success (16 Oct): no extra layer.

        open() first borrows the support (one more check), so its stop k is the
        direct export's stop k-1. The fixed open() never lengthens the chain;
        the old ``finally: ref.close()`` body does whenever the failed export
        still holds child borrows. R1: an ordinary support decodes from the
        columns without child borrows, so there neither body lengthens it; a
        composite support still holds them while its export fails.
        """
        baseline = self.budget.reserved_bytes
        compared, lengthened = 0, 0
        gc.disable()
        try:
            for stop_at in range(2, 2000):
                direct = self.chain_length(stop_at-1)
                fixed = self.chain_length(stop_at, support_open)
                old = self.chain_length(stop_at, old_support_open)
                self.assertEqual(self.budget.reserved_bytes, baseline, stop_at)
                if direct is None:
                    self.assertIsNone(fixed)
                    break
                self.assertEqual(fixed, direct, stop_at)
                lengthened += old is not None and old > direct
                compared += 1
        finally:
            gc.enable()
        self.assertGreater(compared, 10)
        self.assertEqual(lengthened, 0)
        compared, lengthened = 0, 0
        gc.disable()
        try:
            for stop_at in range(1, 4000):
                fixed = self.chain_length(stop_at, 'support_open', composite=True)
                old = self.chain_length(stop_at, 'old_support_open', composite=True)
                self.assertEqual(self.budget.reserved_bytes, baseline, stop_at)
                self.assertEqual(fixed is None, old is None, stop_at)    # same checks up to the export
                if fixed is None:
                    break
                self.assertEqual(fixed, 1, stop_at)
                lengthened += old > fixed
                compared += 1
        finally:
            gc.enable()
        self.assertGreater(compared, 10)
        self.assertGreater(lengthened, 0)

    def test_chain_walk_is_bounded_and_cycle_safe(self):
        first, second = RuntimeError('a'), ValueError('b')
        first.__context__, second.__context__ = second, first
        self.assertEqual(CAP.exception_chain(first), [first, second])
        third = KeyError('c')
        third.__cause__ = first
        self.assertEqual(CAP.exception_chain(third), [third, first, second])


if __name__ == '__main__':
    unittest.main()
