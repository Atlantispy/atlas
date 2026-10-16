"""The capacity state overlap's cleanup closes its cell record cleanly (16 Oct 2026).

capacity-claude-iv1-r3p measured its whole region and then failed its cleanup:
"retained scope still has live owners or reservations", with one 1,177,527 B
live-producer record-tables charge left: the state overlap's CellSink record.
Its explicit close was registered after run_overlaps had registered the clears
of ctx.keep (the issued state, whose snapshot borrows the cells) and of
ctx.shared (the cells root). Cleanup runs last-registered first, so the close
ran while both borrowers were alive and refused. ExitStack.close() kept no
context for that refusal when the scope's close failed later, and passed it to
every later callback as arguments, so its traceback kept the record and its
owner alive past the scope's close check. The workload's failure handler then
cleared the frames, and reference counting released the charge (the final
tracked bytes were the 5,120 B scope control).

The harness now releases the state's borrowers before that close (hold_state),
and CleanupStack records every cleanup failure and propagates it without its
frames. Production never closes this record explicitly: the composed finish
deletes its locals after owner._issue, so the record lives as long as the issued
state's cell borrow, and reference counting releases it when the state is
dropped. All tests run with gc disabled, as the capacity measurement does.
"""
import ast
import gc
import inspect
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
R = HERE.parent
I = R.parent/'runtime-integration-r1'/'runtime-src'
for directory in (I, R):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import live_spatial_patch as LIVE
import measure_live_capacity as CAP
import measure_live_capacity_overlaps as OVERLAPS
from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope

ROWS = [{'cell_id': f'c{index:03d}', 'volume_m3': [hex(index+3), '0x7'],
         'exact': {'enthalpy_j': [hex(index+1), '0x3']}} for index in range(64)]


class _Issued:
    """The issued state's hold on its cells: retained_snapshot keeps cells.borrow()."""
    def __init__(self, cells):
        self._cells = cells.borrow()


def clear_chain(error):
    for held in CAP.exception_chain(error):
        CAP.traceback.clear_frames(held.__traceback__)
        held.__traceback__ = None


class StateCleanupTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        # Capacity runs charge record tables to the named live-producer child.
        self.scope = create_retained_scope(self.budget, process_epoch='capacity-state-cleanup-test',
                                           live_producer_bytes=64 << 20)
        self.gc_was_enabled = gc.isenabled()
        gc.disable()

    def tearDown(self):
        if self.gc_was_enabled:
            gc.enable()
        gc.collect()
        if not self.scope._closed:
            self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())

    def producer_bytes(self):
        return self.scope.stats().producer_bytes

    def overlap(self, owners):
        """run_overlaps' registrations, then the state overlap's finished cells and record close."""
        ctx = SimpleNamespace(owners=owners, keep=[], shared={})
        owners.callback(self.scope.close)
        owners.callback(ctx.keep.clear)
        owners.callback(ctx.shared.clear)
        sink = LIVE.CellSink(self.scope, check=lambda: None)
        for row in ROWS:
            sink.append(dict(row))
        cells = sink.finish()
        owners.callback(sink._record.close)
        return ctx, cells, _Issued(cells)

    def test_the_state_borrowers_drop_before_the_record_closes(self):
        owners = CAP.CleanupStack()
        ctx, cells, issued = self.overlap(owners)
        OVERLAPS.hold_state(ctx, issued, cells)
        del cells, issued
        self.assertGreater(self.producer_bytes(), 0)
        owners.close()
        self.assertEqual(owners.failures, [])
        self.assertTrue(self.scope._closed)
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())

    def test_the_r3p_registration_masks_the_refusal_and_holds_the_record(self):
        """The mutant: the previous state overlap on a plain ExitStack."""
        owners = ExitStack()
        ctx, cells, issued = self.overlap(owners)
        held = self.producer_bytes()
        ctx.keep.append(issued)
        ctx.shared['state_cells'] = cells
        del cells, issued
        # Not assertRaises: it drops the traceback, and with it what this test observes.
        try:
            owners.close()
        except RuntimeError as caught:
            error = caught
        else:
            self.fail('the r3p registration closed cleanly')
        self.assertEqual(str(error), 'retained scope still has live owners or reservations')
        # The record close's refusal is not in the chain, but its frames hold the record.
        self.assertIsNone(error.__context__)
        self.assertEqual(ctx.keep, [])
        self.assertEqual(ctx.shared, {})
        self.assertEqual(self.producer_bytes(), held)
        clear_chain(error)
        del error
        self.assertEqual(self.producer_bytes(), 0)

    def test_cleanup_stack_records_the_refusal_and_releases_its_object(self):
        owners = CAP.CleanupStack()
        ctx, cells, issued = self.overlap(owners)
        ctx.keep.append(issued)
        ctx.shared['state_cells'] = cells
        del cells, issued
        with self.assertRaisesRegex(RuntimeError, 'owner has live child borrows'):
            owners.close()
        self.assertEqual([(row['callback'], row['type'], row['message']) for row in owners.failures],
                         [('CompactRecord.close', 'RuntimeError', 'owner has live child borrows')])
        self.assertIn('assert_unborrowed', owners.failures[0]['traceback'])
        # Without a collection the refused record closed once its borrowers dropped,
        # so the scope's own close succeeded.
        self.assertTrue(self.scope._closed)
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())

    def test_production_releases_the_record_with_its_state(self):
        owner = SimpleNamespace(_record_scope=self.scope)
        cells = LIVE.cell_sink(owner)
        self.assertIs(type(cells), LIVE.CellSink)
        for row in ROWS:
            cells.append(dict(row))
        LIVE.sort_cells(cells)
        record = {'cells': LIVE.state_cells(cells)}
        state = _Issued(record['cells'])
        # The composed finish: del record, cells, ... after owner._issue(record).
        del record, cells
        self.assertGreater(self.producer_bytes(), 0)
        del state
        self.assertEqual(self.producer_bytes(), 0)
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())


class RegistrationTests(unittest.TestCase):
    def test_the_state_overlap_holds_through_hold_state(self):
        tree = ast.parse(inspect.getsource(OVERLAPS.state))
        calls = [node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertIn('hold_state', calls)
        text = ast.unparse(tree)
        self.assertNotIn('ctx.keep.append', text)
        self.assertNotIn("ctx.shared['state_cells'] =", text)

    def test_both_workloads_clean_up_through_cleanup_stack(self):
        for function in (CAP.workload, OVERLAPS.standalone_workload):
            names = {ast.unparse(node.func) for node in ast.walk(ast.parse(inspect.getsource(function)))
                     if isinstance(node, ast.Call)}
            self.assertNotIn('ExitStack', names, function.__name__)
            self.assertTrue({'CleanupStack', 'CAP.CleanupStack'} & names, function.__name__)


if __name__ == '__main__':
    unittest.main()
