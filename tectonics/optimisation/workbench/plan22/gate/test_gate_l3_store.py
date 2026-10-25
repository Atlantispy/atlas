"""Combined-gate cases for L3 on composed helpers: real sealed stores, nothing mocked.

Run by gate_child.py against a composed helpers folder (S3 + L3 + S1 Stage A when composed); imports only that
folder's modules. The stores are built as test_item14_page_layer's fixture builds them, with eight more intervals so
that interval 0's native handle can be evicted.

G0  control: an unchanged store; the second batch adopts the carried pages and serves the same exact values.
G1  between two batches of a view that carries pages, the evicted interval 0 file is replaced on disk (identical
    bytes, a new file; os.replace, as test_s1a_guarded_read does): the next batch refuses at entry, adopts nothing
    and drops the carry. A resident interval cannot be replaced at all (open handles).
G2  compact_store's nested shape (compact_store.py:612 enters a columns batch and a record batch together): the
    inner view carries when its batch exits, before the outer batch's closing identity check; the file then
    changes inside the outer batch (read-only attribute cleared: a real change to the token). The outer exit
    refuses, and the next batch of the inner view refuses at entry without adopting the carry made before the
    check (contract C-L3S1 (a) and (c)).
"""
from contextlib import contextmanager
import gc
import os
from pathlib import Path
import shutil
import stat
import tempfile
from types import SimpleNamespace
import unittest

from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet
from segment_store import SegmentBackend
import record_tables as T
import record_views as M
from test_item14_page_layer import SCHEMA, make_value

INTERVALS = 9


def delta(before):
    after = M.carry_stats()
    return {name: after[name]-before[name] for name in after}


def read_values(record, count=6):
    """One outer batch reading one value from each of the first int.bytes pages and each small column."""
    cols = record._columns
    total = cols.descriptors['int.bytes']['shape'][0]
    values = {}
    with record._read_batch():
        for start in list(range(0, total, T.CHUNK))[:count]:
            values[('int.bytes', start)] = cols.value('int.bytes', start)
        for name in ('node.kind', 'node.payload'):
            if cols.descriptors[name]['shape'][0]:
                values[(name, 0)] = cols.value(name, 0)
    return values


@contextmanager
def store(test):
    """A sealed store set reopened from its catalog: interval 0 holds the test record, 1-8 small ones."""
    budget = WorkBudget(1 << 30)
    scope = create_retained_scope(budget, process_epoch='gate-l3-store')
    directory = Path(tempfile.mkdtemp(prefix='g-'))
    stores = reopened = None
    opened = []
    try:
        stores = IntervalStoreSet.create_migration(str(directory/'catalog.json'), workflow_id='1'*64, scope=scope)
        backend, refs = SegmentBackend(), []
        for index in range(INTERVALS):
            value = make_value() if index == 0 else make_value(40, seed=100+index)
            candidate = stores.begin_interval(None if index == 0 else stores.head, producer_identity='2'*64,
                                              runtime_identity='3'*64)
            try:
                packed = T.RecordCodec().pack_record(value, record_schema=SCHEMA, scope=scope, check=lambda: None)
                with packed.metadata_bytes() as held:
                    ref = backend.publish(candidate, record_schema=SCHEMA, identity=packed.identity(),
                        metadata=held.value, arrays=packed.array_sources, producer='2'*64,
                        representation_profile=T.SCHEMA, scope=scope)
                packed.close()
                del packed, held
                promoted = candidate.seal(ref)
                stores.promote(promoted, expected_catalog_digest=promoted.expected_catalog_digest)
                del promoted
            finally:
                candidate.close()
            refs.append(ref)
        stores.close()
        stores = None
        reopened = IntervalStoreSet.open_catalog(str(directory/'catalog.json'), scope=scope)

        def record(*, cached=True):
            segment = backend.open(reopened, refs[0], scope=scope)
            made = M.CompactRecord.from_segment(segment, use_page_cache=cached)
            opened.append((made, segment))
            return made
        yield SimpleNamespace(directory=directory, stores=reopened, record=record,
                              path=directory/'interval-0000.sqlite')
    finally:
        for made, segment in reversed(opened):
            made.close()
            segment.close()
        opened.clear()
        gc.collect()
        for owner in (reopened, stores):
            if owner is not None:
                owner.close()
        gc.collect()
        scope.close()
        shutil.rmtree(directory, ignore_errors=True)
        test.assertEqual(budget.reserved_bytes, 0)


class GateL3StoreTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        gc.collect()
        self.assertEqual(M.carry_stats()['booked'], 0, 'carried bytes left by an earlier test')

    def tearDown(self):
        gc.collect()
        self.assertEqual(M.carry_stats()['booked'], 0, 'carried bytes left by this test')

    def test_g0_unchanged_store_adopts_and_serves_exact_values(self):
        with store(self) as fx:
            exact = read_values(fx.record(cached=False))
            record = fx.record()
            first = read_values(record)
            before = M.carry_stats()
            second = read_values(record)
            change = delta(before)
            self.assertEqual(first, exact)
            self.assertEqual(second, exact)
            self.assertEqual(change['adopted'], 1)
            self.assertIsNotNone(record._columns._carried)

    def test_g1_replaced_evicted_file_refuses_before_the_carry_is_adopted(self):
        with store(self) as fx:
            record = fx.record()
            read_values(record)
            read_values(record)
            self.assertIsNotNone(record._columns._carried, 'no carry to test')
            for index in range(1, INTERVALS):
                fx.stores.borrow_handle(index).close()
            self.assertNotIn(0, fx.stores._handles, 'interval 0 is still resident')
            self.assertIn(0, fx.stores._verified_tokens)
            resident, copy = fx.directory/'interval-0001.sqlite', fx.directory/'replacement.bin'
            shutil.copyfile(resident, copy)
            with self.assertRaises(PermissionError):   # a resident file is never replaced
                os.replace(copy, resident)
            shutil.copyfile(fx.path, copy)
            os.chmod(copy, stat.S_IREAD)
            old = os.stat(fx.path)
            os.chmod(fx.path, stat.S_IWRITE | stat.S_IREAD)   # MoveFileEx will not replace a read-only target
            os.replace(copy, fx.path)                          # real replacement between batches
            new = os.stat(fx.path)
            self.assertEqual(new.st_size, old.st_size)
            self.assertNotEqual((new.st_ino, new.st_ctime_ns), (old.st_ino, old.st_ctime_ns), 'not a new file')
            before, served = M.carry_stats(), []
            with self.assertRaisesRegex(ContractError, 'identity changed'):
                served.append(read_values(record))
            change = delta(before)
            self.assertEqual(served, [])
            self.assertEqual((change['adopted'], change['dropped_entry']), (0, 1))
            self.assertIsNone(record._columns._carried)
            with self.assertRaisesRegex(ContractError, 'identity changed'):   # never re-pinned
                read_values(record)

    def test_g2_nested_batch_change_refuses_and_the_early_carry_is_never_adopted(self):
        with store(self) as fx:
            outer, inner = fx.record(), fx.record()
            exact = read_values(inner)
            read_values(inner)
            held = inner._columns._carried
            self.assertIsNotNone(held, 'no carry to test')
            reached, inside = [], {}
            try:
                with self.assertRaisesRegex(ContractError, 'identity changed'):
                    with outer._columns.read_batch():
                        with inner._read_batch():
                            inside['adopted'] = inner._columns._batch_pages is held
                            inside['values'] = {key: inner._columns.value(*key) for key in exact}
                        inside['carried'] = inner._columns._carried is held
                        os.chmod(fx.path, stat.S_IWRITE | stat.S_IREAD)   # changes inside the outer batch
                        reached.append('inner exit passed')
                self.assertEqual(reached, ['inner exit passed'])   # refused only by the outer exit
                self.assertEqual(inside['values'], exact)
                self.assertTrue(inside['adopted'], 'the inner view did not adopt its carry')
                self.assertTrue(inside['carried'], 'the inner view did not carry before the outer check')
                del held
                before, served = M.carry_stats(), []
                with self.assertRaisesRegex(ContractError, 'identity changed'):
                    served.append(read_values(inner))
                change = delta(before)
                self.assertEqual(served, [])
                self.assertEqual((change['adopted'], change['dropped_entry']), (0, 1))
                self.assertIsNone(inner._columns._carried)
            finally:
                os.chmod(fx.path, stat.S_IREAD)


if __name__ == '__main__':
    unittest.main()
