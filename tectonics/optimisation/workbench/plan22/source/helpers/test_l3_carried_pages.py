"""L3: verified page pins carried between read batches of one view (record_views).

Runs from a composition's helpers folder whose record_views.py is the L3
candidate, beside test_item14_page_layer.py (its sealed fixture and pinned
item-14 origin, loaded as O). Each L3-M case below fails on its planted mutant.
"""
from contextlib import contextmanager, nullcontext
import gc
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from compact_contracts import ContractError
from content_cache import ChargeSpec, create_retained_scope
import record_tables as T
import record_views as M
from test_item14_page_layer import O, close_sealed, make_value, open_sealed, page_misses, sealed
from test_record_tables import streamed

REGISTRY = 'retained:record-batch-page-borrows'


def delta(before):
    after = M.carry_stats()
    return {name: after[name]-before[name] for name in after}


def read_pages(record, count=None):
    """One outer batch reading one value from each native int.bytes page and each small column."""
    cols = record._columns
    total = cols.descriptors['int.bytes']['shape'][0]
    starts = list(range(0, total, T.CHUNK))[:count]
    values = {}
    with record._read_batch():
        for start in starts:
            values[('int.bytes', start)] = cols.value('int.bytes', start)
        for name in ('node.kind', 'node.payload'):
            if cols.descriptors[name]['shape'][0]:
                values[(name, 0)] = cols.value(name, 0)
    return values


def expected_pages(fx, values):
    return {key: fx.arrays[key[0]][key[1]].item() for key in values}


def booked(cols):
    return cols._carried.charged_bytes+sum(page._owner.charged_bytes for page in cols._carried.value.values())


@contextmanager
def failing_batch(segment, *, at, observed=None, cols=None):
    """The store set's read batch refuses at entry or at its closing identity check."""
    original = segment.resolver.read_batch

    @contextmanager
    def batch(*, cancel=None):
        if observed is not None:
            observed.append(cols._batch_pages)
        if at == 'entry':
            raise ContractError('sealed file identity changed (test)')
        with original(cancel=cancel):
            yield
        raise ContractError('sealed file identity changed at close (test)')
    with patch.object(segment.resolver, 'read_batch', batch):
        yield


@contextmanager
def counting_verifier(cols, calls):
    original = cols.cache.verifier

    def verifier(key, value):
        calls.append(key)
        return original(key, value)
    with patch.object(cols.cache, 'verifier', verifier):
        yield


@contextmanager
def synthetic_columns(*, pin_entry=False):
    """Real retained page owners and batch registry, with no store reads."""
    scope = create_retained_scope(M.WorkBudget(512 << 20), process_epoch='l3-touched-regression')
    segment = SimpleNamespace(scope=scope, cancel=None, _read_lock=threading.RLock(),
                              verified_read=nullcontext)
    if pin_entry:
        with scope.reserve(ChargeSpec('l3-synthetic-segment', 0)) as reservation:
            segment._owner = reservation.commit(None)

        @contextmanager
        def verified_read():
            # SegmentView.verified_read reserves this required carrier before yielding.
            with segment._read_lock:
                pin = segment._owner.retain()
                try:
                    yield
                finally:
                    pin.close()
        segment.verified_read = verified_read
    cols = M._Segment(segment, {}, use_page_cache=False)
    cols.cache = object()
    try:
        yield cols, scope
    finally:
        cols.release()
        if pin_entry:
            segment._owner.close()
        scope.close()


class L3CarriedPagesTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        gc.collect()
        self.assertEqual(M.carry_stats()['booked'], 0, 'carried bytes left by an earlier test')

    def test_carried_pages_are_exact_and_cut_reverification(self):
        # L3-M4 (wrong key): every carried page must serve its own exact values.
        value = make_value()
        expected = T.canonical(value)
        result = {}
        for label, module in (('origin', O), ('candidate', M)):
            with sealed(self, value, 'l3-exact-'+label) as fx:
                record, segment = open_sealed(fx, module)
                cols, calls = record._columns, []
                before, misses = M.carry_stats(), page_misses(fx.scope)
                with counting_verifier(cols, calls):
                    first = read_pages(record)
                    second = read_pages(record)
                    self.assertEqual(streamed(record, 4096), expected, label)
                    self.assertEqual(streamed(record, 4096), expected, label)
                self.assertEqual(first, expected_pages(fx, first), label)
                self.assertEqual(second, first, label)
                result[label] = dict(verifies=len(calls), misses=page_misses(fx.scope)-misses,
                                     adopted=delta(before)['adopted'])
                close_sealed(record, segment)
                del record, segment, cols
        self.assertLessEqual(result['candidate']['misses'], result['origin']['misses'])
        self.assertLess(result['candidate']['verifies'], result['origin']['verifies'])
        self.assertGreater(result['candidate']['adopted'], 0)
        self.assertEqual(result['origin']['adopted'], 0)
        print('L3 exact', result, file=sys.stderr)

    def test_wrong_carried_key_is_caught_by_exact_values(self):
        # L3-M4: the same exactness on a column whose pages are all carried.
        value = make_value()
        with sealed(self, value, 'l3-key') as fx:
            record, segment = open_sealed(fx, M)
            cols = record._columns
            read_pages(record)
            self.assertIsNotNone(cols._carried)
            total = cols.descriptors['int.bytes']['shape'][0]
            picks = [i for start in range(0, total, T.CHUNK) for i in (start, min(total-1, start+777))]
            with record._read_batch():
                got = [cols.value('int.bytes', i) for i in picks]
            self.assertEqual(got, [fx.arrays['int.bytes'][i].item() for i in picks])
            close_sealed(record, segment)
            del record, segment, cols

    def test_view_cap_trims_lru_first_and_process_cap_refuses(self):
        # L3-M1: caps.
        value = make_value()
        with sealed(self, value, 'l3-caps') as fx:
            record, segment = open_sealed(fx, M)
            cols = record._columns
            read_pages(record)
            full = booked(cols)
            pages = list(cols._carried.value)
            self.assertGreaterEqual(len(pages), 3)
            # Reopen the carry under a cap that keeps the registry and two pages.
            per_page = [cols._carried.value[key]._owner.charged_bytes for key in pages]
            cap = cols._carried.charged_bytes+sum(per_page[-2:])
            before = M.carry_stats()
            with patch.object(M, '_CARRY_VIEW_BYTES', cap):
                read_pages(record)
            kept = list(cols._carried.value)
            self.assertLessEqual(booked(cols), cap)
            self.assertEqual(cols._carried_booked, booked(cols))
            self.assertEqual(kept, pages[-len(kept):])
            self.assertLess(len(kept), len(pages))
            self.assertEqual(delta(before)['trimmed'], len(pages)-len(kept))
            self.assertLess(booked(cols), full)
            # Process cap below one view's carry: refused, dropped, counted.
            before = M.carry_stats()
            with patch.object(M, '_CARRY_TOTAL_BYTES', cols._carried_booked-1):
                read_pages(record)
            self.assertIsNone(cols._carried)
            self.assertEqual(delta(before)['refused'], 1)
            self.assertEqual(M.carry_stats()['booked'], 0)
            self.assertEqual(fx.scope.stats().purpose_bytes.get(REGISTRY, 0), 0)
            close_sealed(record, segment)
            del record, segment, cols

    def test_booked_bytes_are_the_existing_charges(self):
        # Accounting: registry charge plus each pin holder's charged bytes; raw = page bytes.
        value = make_value()
        with sealed(self, value, 'l3-booked') as fx:
            record, segment = open_sealed(fx, M)
            cols = record._columns
            read_pages(record)
            read_pages(record)
            registry = cols._carried
            self.assertEqual(fx.scope.stats().purpose_bytes[REGISTRY], registry.charged_bytes)
            self.assertEqual(registry.charged_bytes, 128*2048+4096+M.OWNER_BYTES)
            self.assertEqual(cols._carried_booked, booked(cols))
            self.assertEqual(cols._carried_raw, sum(len(p._owner.value.raw) for p in registry.value.values()))
            stats = M.carry_stats()
            self.assertEqual((stats['booked'], stats['raw']), (cols._carried_booked, cols._carried_raw))
            self.assertGreaterEqual(stats['view_peak_booked'], cols._carried_booked)
            self.assertGreater(fx.scope.stats().pinned_bytes, 0)
            close_sealed(record, segment)
            del record, segment, cols, registry
            gc.collect()
            self.assertEqual(fx.scope.stats().pinned_bytes, 0)

    def test_close_releases_carried_pins_with_an_access_alive(self):
        # L3-M2: an Access survives CompactRecord.close; scope close (fixture) must succeed.
        value = make_value()
        with sealed(self, value, 'l3-close') as fx:
            record, segment = open_sealed(fx, M)
            cols = record._columns
            access = record._access()
            column = access.column('int.bytes')
            with record._read_batch():
                first = column[0]
            self.assertIsNotNone(cols._carried)
            before = M.carry_stats()
            record.close()
            self.assertIsNone(cols._carried)
            self.assertEqual(delta(before)['dropped_close'], 1)
            self.assertEqual(M.carry_stats()['booked'], 0)
            purposes = fx.scope.stats().purpose_bytes
            for purpose in (REGISTRY, 'retained:record-page-keys', 'retained:record-page-cursors'):
                self.assertEqual(purposes.get(purpose, 0), 0, purpose)
            # The surviving access still reads exactly (uncached route), and nothing is carried again.
            self.assertEqual(column[0], first)
            self.assertEqual(column[T.CHUNK+5], fx.arrays['int.bytes'][T.CHUNK+5].item())
            self.assertIsNone(cols._carried)
            segment.close()
            self._keep = (access, column, cols)
        del self._keep

    def test_changed_segment_refuses_before_carried_pages_are_adopted(self):
        # L3-M3: entry refusal drops the carried pins before any adoption.
        value = make_value()
        with sealed(self, value, 'l3-fresh') as fx:
            record, segment = open_sealed(fx, M)
            cols = record._columns
            read_pages(record)
            self.assertIsNotNone(cols._carried)
            observed, ran = [], []
            before = M.carry_stats()
            with failing_batch(segment, at='entry', observed=observed, cols=cols):
                with self.assertRaises(ContractError):
                    with record._read_batch():
                        ran.append(True)
            self.assertEqual((observed, ran), ([None], []))
            self.assertIsNone(cols._carried)
            self.assertIsNone(cols._batch_pages)
            self.assertEqual(delta(before)['dropped_entry'], 1)
            self.assertEqual(M.carry_stats()['booked'], 0)
            self.assertEqual(fx.scope.stats().purpose_bytes.get(REGISTRY, 0), 0)
            close_sealed(record, segment)
            del record, segment, cols

    def test_closing_check_refusal_carries_nothing(self):
        # L3-M7 (closing boundary): a body that completes but fails the closing identity check.
        value = make_value()
        with sealed(self, value, 'l3-closing') as fx:
            record, segment = open_sealed(fx, M)
            cols = record._columns
            read_pages(record)
            before = M.carry_stats()
            with failing_batch(segment, at='exit'):
                with self.assertRaises(ContractError):
                    read_pages(record)
            self.assertIsNone(cols._carried)
            self.assertIsNone(cols._batch_pages)
            self.assertEqual(delta(before)['dropped_exception'], 1)
            self.assertEqual(M.carry_stats()['booked'], 0)
            gc.collect()
            self.assertEqual(fx.scope.stats().purpose_bytes.get(REGISTRY, 0), 0)
            # The next batch starts afresh and is exact.
            again = read_pages(record)
            self.assertEqual(again, expected_pages(fx, again))
            close_sealed(record, segment)
            del record, segment, cols

    def test_body_exception_carries_nothing_and_traceback_data_stays_paid(self):
        # L3-M7: an exception exit never leaves a reusable carried registry.
        value = make_value()
        with sealed(self, value, 'l3-raise') as fx:
            record, segment = open_sealed(fx, M)
            cols = record._columns
            read_pages(record)
            access = record._access()
            column = access.column('int.bytes')
            before = M.carry_stats()
            caught = None
            try:
                with record._read_batch():
                    column[T.CHUNK]
                    raise KeyError('body failed (test)')
            except KeyError as error:
                caught = error
            self.assertIsNone(cols._carried)
            self.assertIsNone(cols._batch_pages)
            self.assertEqual(delta(before)['dropped_exception'], 1)
            self.assertEqual(M.carry_stats()['booked'], 0)
            # A page still referenced from the failed operation (here its paged column) stays paid:
            # its holder is open and its allocation pinned until that reference goes.
            page = column._page
            self.assertIsNot(page, M._NO_PAGE)
            self.assertIsNotNone(page._owner._allocation)
            self.assertGreater(fx.scope.stats().pinned_bytes, 0)
            del caught, access, column, page
            gc.collect()
            self.assertEqual(fx.scope.stats().pinned_bytes, 0)
            self.assertEqual(fx.scope.stats().purpose_bytes.get(REGISTRY, 0), 0)
            close_sealed(record, segment)
            del record, segment, cols

    def test_uncached_fallback_drops_carried_pins(self):
        # L3-M5: the value()/raw() uncached fallback releases carried pins (pressure).
        value = make_value()
        with sealed(self, value, 'l3-fallback') as fx:
            record, segment = open_sealed(fx, M)
            cols = record._columns
            read_pages(record)
            self.assertGreater(fx.scope.stats().pinned_bytes, 0)

            class Declined(M._OptionalScratch):
                def __init__(self, budget, size, category='record-column-lookup'):
                    self.admitted = False
            before = M.carry_stats()
            with patch.object(M, '_OptionalScratch', Declined):
                got = cols.value('int.bytes', T.CHUNK+3)
            self.assertEqual(got, fx.arrays['int.bytes'][T.CHUNK+3].item())
            self.assertIsNone(cols._carried)
            self.assertEqual(delta(before)['dropped_fallback'], 1)
            self.assertEqual(M.carry_stats()['booked'], 0)
            self.assertEqual(fx.scope.stats().purpose_bytes.get(REGISTRY, 0), 0)
            self.assertEqual(fx.scope.stats().pinned_bytes, 0)
            close_sealed(record, segment)
            del record, segment, cols

    def test_no_reader_outside_a_batch_sees_a_carried_pin(self):
        # L3-M6: _batch_pages is None between batches; outside reads take the verified cache route,
        # including a stale paged column from the previous batch.
        value = make_value()
        with sealed(self, value, 'l3-outside') as fx:
            record, segment = open_sealed(fx, M)
            cols = record._columns
            access = record._access()
            column = access.column('int.bytes')
            with record._read_batch():
                column[T.CHUNK+1]
                cols.value('node.kind', 0)
            self.assertIsNotNone(cols._carried)
            self.assertIsNone(cols._batch_pages)
            for page in cols._carried.value.values():
                self.assertIsNone(page._view)
            calls = []
            with counting_verifier(cols, calls):
                self.assertEqual(cols.value('int.bytes', T.CHUNK+2), fx.arrays['int.bytes'][T.CHUNK+2].item())
                self.assertEqual(len(calls), 1)
                self.assertEqual(column[T.CHUNK+4], fx.arrays['int.bytes'][T.CHUNK+4].item())
                self.assertEqual(len(calls), 2)
                self.assertEqual(cols.value('node.kind', 1), fx.arrays['node.kind'][1].item())
                self.assertEqual(len(calls), 3)
                # Inside the next batch the carried pages serve without a re-verify.
                with record._read_batch():
                    self.assertEqual(column[T.CHUNK+6], fx.arrays['int.bytes'][T.CHUNK+6].item())
                    self.assertEqual(cols.value('node.kind', 2), fx.arrays['node.kind'][2].item())
                self.assertEqual(len(calls), 3)
            close_sealed(record, segment)
            del record, segment, cols, access, column

    def test_collected_view_returns_its_carried_bytes(self):
        # Backstop for a direct _Segment holder without release(): collection returns the total.
        value = make_value()
        with sealed(self, value, 'l3-collect') as fx:
            segment = fx.segment()
            record = M.CompactRecord.from_segment(segment)
            cols = record._columns
            read_pages(record)
            self.assertGreater(M.carry_stats()['booked'], 0)
            before = M.carry_stats()
            record._columns = None
            record.close()
            del cols
            gc.collect()
            self.assertEqual(delta(before)['dropped_collected'], 1)
            self.assertEqual(M.carry_stats()['booked'], 0)
            self.assertEqual(fx.scope.stats().purpose_bytes.get(REGISTRY, 0), 0)
            segment.close()
            del record, segment

    def test_no_page_cache_keeps_the_original_batch(self):
        value = make_value(800)
        with sealed(self, value, 'l3-nocache') as fx:
            segment = fx.segment()
            record = M.CompactRecord.from_segment(segment, use_page_cache=False)
            before = M.carry_stats()
            self.assertEqual(streamed(record, 4096), T.canonical(value))
            self.assertIsNone(record._columns._carried)
            self.assertEqual(delta(before), dict.fromkeys(before, 0))
            close_sealed(record, segment)
            del record, segment

    def test_touched_pages_stay_bounded_during_a_long_batch(self):
        # L3-M10: closed pages must not accumulate beyond the paid registry's 128-page cap.
        with synthetic_columns() as (cols, scope):
            dtype = M.np.dtype('|u1')
            with cols.read_batch():
                for index in range(4096):
                    with scope.reserve(ChargeSpec('l3-synthetic-page', 1)) as reservation:
                        owner = reservation.commit(SimpleNamespace(raw=b'\x07'))
                    page = cols._pin_page(('synthetic', index), owner)
                    page.scalar(0, dtype)
                    del page, owner, reservation
                    if index == 127:
                        initial_charge = scope.retained_budget.reserved_bytes
                registry_count = len(cols._batch_pages.value)
                touched_count = len(cols._touched)
                closed_count = sum(page._owner._allocation is None for page in cols._touched)
                final_charge = scope.retained_budget.reserved_bytes
        self.assertEqual(registry_count, 128)
        self.assertEqual(touched_count, registry_count)
        self.assertEqual(closed_count, 0)
        self.assertEqual(final_charge, initial_charge)

    def test_touched_page_is_unique_and_removed_on_fallback(self):
        # A page may expose both a cast view and an ndarray; withdrawing it needs one entry.
        with synthetic_columns() as (cols, scope):
            with cols.read_batch():
                with scope.reserve(ChargeSpec('l3-synthetic-page', 1)) as reservation:
                    owner = reservation.commit(SimpleNamespace(raw=b'\x07'))
                page = cols._pin_page(('synthetic', 0), owner)
                page.view('B')
                page.scalar(0, M.np.dtype('|i1'))
                touched_count = len(cols._touched)
                cols._drop_batch_pages()
                after_fallback = len(cols._touched)
                owner_closed = page._owner._allocation is None
        self.assertEqual(touched_count, 1)
        self.assertEqual(after_fallback, 0)
        self.assertTrue(owner_closed)

    def test_entry_pressure_can_reclaim_the_not_yet_adopted_carry(self):
        # L3-M11: the next verified read needs a required owner carrier before it can adopt pages.
        with synthetic_columns(pin_entry=True) as (cols, scope):
            with cols.read_batch():
                with scope.reserve(ChargeSpec('l3-synthetic-page', 1)) as reservation:
                    owner = reservation.commit(SimpleNamespace(raw=b'\x07'))
                page = cols._pin_page(('synthetic', 0), owner)
                page.scalar(0, M.np.dtype('|u1'))
                del page, owner, reservation
            room = scope.retained_budget.max_bytes-scope.retained_budget.reserved_bytes
            before = M.carry_stats()
            entered = False
            with scope.reserve(ChargeSpec('l3-entry-pressure', room-M.OWNER_BYTES)):
                full = scope.retained_budget.reserved_bytes == scope.retained_budget.max_bytes
                try:
                    with cols.read_batch():
                        entered = True
                except M.MemoryLimitError:
                    pass
            released = delta(before)['dropped_pressure']
        self.assertTrue(full)
        self.assertTrue(entered, 'optional carried pins blocked the required entry owner')
        self.assertEqual(released, 1)

    def test_eviction_releases_carried_pins_only_when_unpinned_pages_fall_short(self):
        # L3-M8: carried pins yield to an eviction request that unpinned pages cannot meet.
        value = make_value(20000)
        with sealed(self, value, 'l3-evict') as fx:
            record, segment = open_sealed(fx, M)
            cols = record._columns
            first = read_pages(record, count=2)
            # The open and first batches pin every page; drop that carry, then carry one small
            # batch, so the other pages stay cached and unpinned.
            cols._drop_batch_pages()
            read_pages(record, count=1)
            self.assertIsNotNone(cols._carried)
            self.assertGreater(fx.scope.stats().evictable_bytes, 0)
            before = M.carry_stats()
            # Called directly: the scope walks its cache set in no fixed order, and a page
            # cache that met the request first would never reach the reclaimer.
            self.assertGreater(M._RECLAIMERS[fx.scope]._evict(requested_bytes=1), 0)
            self.assertIsNotNone(cols._carried, 'an unpinned page met the request')
            self.assertEqual(delta(before)['dropped_pressure'], 0)
            fx.scope.evict_unpinned(requested_bytes=1 << 30, category='pages')
            self.assertIsNone(cols._carried)
            self.assertEqual(delta(before)['dropped_pressure'], 1)
            self.assertEqual(M.carry_stats()['booked'], 0)
            self.assertEqual(fx.scope.stats().pinned_bytes, 0)
            self.assertEqual(fx.scope.stats().purpose_bytes.get(REGISTRY, 0), 0)
            misses = page_misses(fx.scope)
            self.assertEqual(read_pages(record, count=2), first)
            self.assertGreater(page_misses(fx.scope), misses, 'the released pages were evicted')
            close_sealed(record, segment)
            del record, segment, cols

    def test_required_reservation_under_pressure_releases_the_carry(self):
        # L3-M8: a required reservation that fits only without the carried pins is admitted.
        value = make_value()
        with sealed(self, value, 'l3-pressure') as fx:
            record, segment = open_sealed(fx, M)
            cols = record._columns
            read_pages(record)
            read_pages(record)
            registry = cols._carried
            self.assertIsNotNone(registry)
            retained = fx.scope.retained_budget
            room = retained.max_bytes-retained.reserved_bytes
            spec = ChargeSpec('l3-pressure-test', room+registry.charged_bytes//2-M.OWNER_BYTES)
            del registry
            before = M.carry_stats()
            with fx.scope.reserve(spec, required=True):
                self.assertIsNone(cols._carried)
            self.assertEqual(delta(before)['dropped_pressure'], 1)
            self.assertEqual(M.carry_stats()['booked'], 0)
            close_sealed(record, segment)
            del record, segment, cols

    def test_scope_close_releases_carried_pins_of_a_live_view(self):
        # L3-M9: a view still alive (and carrying) at scope close does not block it.
        value = make_value()
        before = None
        with sealed(self, value, 'l3-scope-close') as fx:
            segment = fx.segment()
            record = M.CompactRecord.from_segment(segment)
            cols = record._columns
            read_pages(record)
            self.assertIsNotNone(cols._carried)
            record._columns = None
            record.close()
            segment.close()
            # Retire the item-14 memos as release() would (they are not L3's), keeping the carry.
            for name in ('_page_keys', '_page_cursors'):
                owner = getattr(cols, name)
                setattr(cols, name, None)
                if owner is not None:
                    owner.close()
            before = M.carry_stats()
            self._keep = cols
            del record, segment, cols
        # The fixture closed the stores and the scope (and asserted a zero budget) with the view alive.
        self.assertIsNone(self._keep._carried)
        self.assertEqual(delta(before)['dropped_scope_close'], 1)
        self.assertEqual(M.carry_stats()['booked'], 0)
        del self._keep


if __name__ == '__main__':
    unittest.main()
