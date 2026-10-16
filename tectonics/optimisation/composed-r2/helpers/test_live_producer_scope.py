"""Live producer charges (coordinator decision D2-A, 16 Oct 2026).

A scope created for a live producer charges in-memory compact producer columns
to its own named child of the run budget; every other purpose stays on the
256 MiB retained aggregate. A scope without a producer allowance (cold or
fresh-process reader) is unchanged: everything stays on the retained aggregate.
"""
import gc
import unittest

from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from compact_contracts import RETAINED_BYTES
from content_cache import (
    LIVE_PRODUCER_BYTES,
    PRODUCER_PURPOSES,
    ChargeSpec,
    create_retained_scope,
)
from record_tables import RecordCodec

RETAINED_ONLY = ('heat-field', 'interval-owned', 'record-export', 'partition-support-index',
                 'record-segment-view', 'test')


def hold(scope, purpose, size, *, required=True):
    reservation = scope.reserve(ChargeSpec(purpose, size), required=required)
    if reservation is None:
        return None
    with reservation:
        return reservation.commit(bytearray(1))


class LiveProducerScopeTests(unittest.TestCase):
    def make(self, producer=LIVE_PRODUCER_BYTES, run=4 << 30, epoch='live-producer-test'):
        budget = WorkBudget(run)
        scope = create_retained_scope(budget, process_epoch=epoch, live_producer_bytes=producer)
        self.addCleanup(gc.collect)
        return budget, scope

    def test_cold_scope_is_unchanged(self):
        _, scope = self.make(producer=None)
        self.assertIsNone(scope.producer_budget)
        held = [hold(scope, purpose, 1 << 20) for purpose in sorted(PRODUCER_PURPOSES)]
        stats = scope.stats()
        self.assertGreaterEqual(stats.retained_bytes, len(held) << 20)
        self.assertEqual((stats.producer_limit_bytes, stats.producer_bytes), (0, 0))
        for purpose in PRODUCER_PURPOSES:
            self.assertGreater(stats.purpose_bytes['retained:'+purpose], 0)
        del held

    def test_producer_purposes_leave_the_retained_aggregate(self):
        budget, scope = self.make()
        base = scope.stats().retained_bytes
        producer = [hold(scope, purpose, 1 << 20) for purpose in sorted(PRODUCER_PURPOSES)]
        retained = [hold(scope, purpose, 1 << 20) for purpose in RETAINED_ONLY]
        stats = scope.stats()
        self.assertEqual(stats.producer_limit_bytes, LIVE_PRODUCER_BYTES)
        self.assertEqual(stats.producer_bytes, sum(ChargeSpec(p, 1 << 20).total_bytes for p in PRODUCER_PURPOSES))
        self.assertEqual(stats.retained_bytes-base, sum(ChargeSpec(p, 1 << 20).total_bytes for p in RETAINED_ONLY))
        for purpose in PRODUCER_PURPOSES:
            self.assertGreater(stats.producer_purpose_bytes['live-producer:'+purpose], 0)
            self.assertNotIn('retained:'+purpose, {k for k, v in stats.purpose_bytes.items() if v})
        # Producer charges are excluded from the retained cache/ownership counters.
        self.assertEqual(stats.non_cache_owned_bytes+stats.pending_bytes+stats.pinned_bytes+stats.evictable_bytes,
                         stats.retained_bytes)
        # Both children count inside the one run budget (logical guard unchanged).
        self.assertGreaterEqual(budget.reserved_bytes, stats.retained_bytes+stats.producer_bytes)
        del producer, retained
        gc.collect()
        stats = scope.stats()
        self.assertEqual((stats.producer_bytes, stats.retained_bytes), (0, base))
        self.assertGreater(stats.producer_peak_bytes, 0)

    def test_producer_cap_refuses_without_touching_retained_or_caches(self):
        _, scope = self.make(producer=8 << 20)
        base = scope.stats()
        kept = hold(scope, 'record-tables', 6 << 20)
        with self.assertRaises(MemoryLimitError):
            hold(scope, 'mesh-memory-columns', 4 << 20)
        self.assertIsNone(hold(scope, 'record-tables', 4 << 20, required=False))
        stats = scope.stats()
        self.assertEqual(stats.retained_bytes, base.retained_bytes)
        self.assertEqual(stats.optional_declines, base.optional_declines+1)
        self.assertGreaterEqual(stats.producer_refusals, 1)
        # A retained-only purpose is still admitted while the producer child is full.
        other = hold(scope, 'record-export', 4 << 20)
        self.assertIsNotNone(other)
        del kept, other
        gc.collect()
        self.assertEqual(scope.stats().producer_bytes, 0)

    def test_close_refuses_while_a_producer_owner_is_live(self):
        budget, scope = self.make(epoch='live-producer-close')
        kept = hold(scope, 'record-tables', 1 << 20)
        with self.assertRaises(RuntimeError):
            scope.close()
        del kept
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_one_allowance_per_run_scope_and_validated(self):
        budget, scope = self.make(epoch='live-producer-same')
        self.assertIs(create_retained_scope(budget, process_epoch='live-producer-same',
                                            live_producer_bytes=LIVE_PRODUCER_BYTES), scope)
        with self.assertRaises(ValueError):
            create_retained_scope(budget, process_epoch='live-producer-same')
        with self.assertRaises(ValueError):
            create_retained_scope(budget, process_epoch='live-producer-same', live_producer_bytes=1 << 20)
        for bad in (0, -1, 1.5, True, (8 << 30)+1):
            with self.assertRaises(ValueError):
                create_retained_scope(WorkBudget(8 << 30), process_epoch='bad', live_producer_bytes=bad)
        self.assertEqual(scope.retained_budget.max_bytes, RETAINED_BYTES)

    def test_packed_record_is_exact_and_charged_to_the_producer_child(self):
        value = {'schema': 'atlas.live-producer-test.v1',
                 'rows': [{'cell_id': f'{at:064x}', 'exact': ['0x7', '0x3']} for at in range(512)]}
        identities = []
        for producer in (None, LIVE_PRODUCER_BYTES):
            budget = WorkBudget(4 << 30)
            scope = create_retained_scope(budget, process_epoch='pack-'+str(producer),
                                          live_producer_bytes=producer)
            base = scope.stats().retained_bytes
            record = RecordCodec().pack_record(value, record_schema=value['schema'], scope=scope, check=lambda: None)
            stats = scope.stats()
            identities.append(record.identity().to_wire())
            if producer is None:
                self.assertGreater(stats.purpose_bytes['retained:record-tables'], 0)
            else:
                self.assertEqual(stats.retained_bytes, base)
                self.assertGreater(stats.producer_purpose_bytes['live-producer:record-tables'], 0)
            record.close()
            del record
            gc.collect()
            scope.close()
            self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(identities[0], identities[1])


if __name__ == '__main__':
    unittest.main()
