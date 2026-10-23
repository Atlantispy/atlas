"""Synthetic retained-share carrier measurement and accounting controls.
Measures a cold scope after warm-up, including allocator rounding; carrier-only charges use CARRIER_BYTES.
Other charges retain the OWNER_BYTES floor, and releasing shares must return the retained budget.
This is a bounded empirical check, not a universal physical-memory bound.
"""
import array
import gc
import tracemalloc
import unittest
from unittest import mock

import content_cache as CC
from atlas_tectonics.resources import WorkBudget

COUNT, FLOOR = 4096, 16


def rounded(size):
    block = -(-max(size, 1)//16)*16
    return block if size <= 512 else block+16


def measure(count=COUNT):
    """(worst rounded bytes per carrier over n >= FLOOR, mean, booked per carrier, booked left after release)."""
    # A run budget holds one live retained scope, so the throwaway warm-up scope gets its own.
    warm_run, run = WorkBudget(1 << 30), WorkBudget(1 << 30)
    warm_scope = CC.create_retained_scope(warm_run, process_epoch='plan18-carrier-selftest-warm')
    warm_owner = warm_scope.reserve(CC.ChargeSpec('selftest-backing', 4096)).commit(bytearray(16))
    warm = [warm_owner.retain() for _ in range(256)]
    scope = CC.create_retained_scope(run, process_epoch='plan18-carrier-selftest')
    owner = scope.reserve(CC.ChargeSpec('selftest-backing', 4096)).commit(bytearray(16))
    start = scope.retained_budget.reserved_bytes
    shares, traced = [None]*count, array.array('q', bytes(8*(count+1)))
    gc.collect()
    tracemalloc.start(1)
    try:
        base = tracemalloc.get_traced_memory()[0]
        for index in range(count):
            shares[index] = owner.retain()
            traced[index+1] = tracemalloc.get_traced_memory()[0]-base
        gc.collect()
        snapshot = tracemalloc.take_snapshot()
    finally:
        tracemalloc.stop()
    booked = (scope.retained_budget.reserved_bytes-start)/count
    sizes = [trace.size for trace in snapshot.traces]
    rounding = (sum(rounded(size) for size in sizes)-sum(sizes))/count
    worst = max(traced[n]/n for n in range(FLOOR, count+1))+rounding
    mean = traced[count]/count+rounding
    del snapshot, sizes
    for index in range(count):
        shares[index] = None
    gc.collect()
    left = scope.retained_budget.reserved_bytes-start
    del warm, warm_owner
    return worst, mean, booked, left


def carrier_problems(count=COUNT):
    worst, mean, booked, left = measure(count)
    problems = []
    if booked != CC.CARRIER_BYTES:
        problems.append('a carrier books %s bytes, not CARRIER_BYTES %d' % (booked, CC.CARRIER_BYTES))
    if worst > CC.CARRIER_BYTES:
        problems.append('measured worst %.1f bytes per carrier exceeds CARRIER_BYTES %d' % (worst, CC.CARRIER_BYTES))
    if left:
        problems.append('%d booked bytes left after release' % left)
    return problems, dict(worst=round(worst, 1), mean=round(mean, 1), booked=booked)


class OwnerCarrierBooking(unittest.TestCase):
    def test_constant_covers_the_measured_carrier(self):
        problems, figures = carrier_problems()
        self.assertEqual(problems, [], figures)
        self.assertLessEqual(figures['mean'], figures['worst'])

    def test_forged_oversized_carrier_is_reported(self):
        new = CC.Owned._new.__func__

        def forged(cls, allocation, **options):
            result = new(cls, allocation, **options)
            if options.get('carrier') is not None:
                result._forged = bytearray(2*CC.CARRIER_BYTES)
            return result
        with mock.patch.object(CC.Owned, '_new', classmethod(forged)):
            problems, figures = carrier_problems(1024)
        self.assertTrue(any('exceeds' in problem for problem in problems), figures)

    def test_guard_admits_the_constant_only_for_a_carrier(self):
        self.assertLess(CC.CARRIER_BYTES, CC.OWNER_BYTES)
        self.assertEqual(CC.ChargeSpec('owner-carrier', 0, CC.CARRIER_BYTES).total_bytes, CC.CARRIER_BYTES)
        refused = {
            'below the carrier floor': ('owner-carrier', 0, CC.CARRIER_BYTES-1, 0),
            'carrier with backing': ('owner-carrier', 1, CC.CARRIER_BYTES, 0),
            'carrier with index bytes': ('owner-carrier', 0, CC.CARRIER_BYTES, 1),
            'other purpose': ('mesh-row', 0, CC.CARRIER_BYTES, 0),
        }
        for name, (purpose, backing, owner, index) in refused.items():
            with self.subTest(name), self.assertRaises(ValueError):
                CC.ChargeSpec(purpose, backing, owner, index)
        self.assertEqual(CC.ChargeSpec('mesh-row', 0).owner_bytes, CC.OWNER_BYTES)

    def test_a_retained_share_books_the_constant(self):
        run = WorkBudget(1 << 26)
        scope = CC.create_retained_scope(run, process_epoch='plan18-carrier-selftest-share')
        owner = scope.reserve(CC.ChargeSpec('selftest-backing', 4096)).commit(bytearray(16))
        before = scope.retained_budget.statistics()['categories'].get('retained:owner-carrier', 0)
        share = owner.retain()
        after = scope.retained_budget.statistics()['categories'].get('retained:owner-carrier', 0)
        self.assertEqual(share._carrier.spec.purpose, 'owner-carrier')
        self.assertEqual(after-before, CC.CARRIER_BYTES)
        share.close()
        del share
        gc.collect()
        self.assertEqual(scope.retained_budget.statistics()['categories'].get('retained:owner-carrier', 0), before)


if __name__ == '__main__':
    unittest.main()
