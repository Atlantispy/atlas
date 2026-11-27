"""Heat speed plan r1, H-C only: `heat-accounting-fa-fb-r1.md` T-1 to T-3 and mutants M-1 to M-4.

Today's reserve and F-B are kept in this file as the reference. Synthetic inputs only.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import random
import sys
import unittest
from unittest import mock

from atlas_tectonics.integration import resources as RES
from atlas_tectonics._private.integration.heat import closed_owned as CL
from atlas_tectonics._private.integration.heat import finish_arithmetic as A
from atlas_tectonics._private.integration.heat import gmp_resources as GMP
from atlas_tectonics._private.integration.heat import projection_numerics as PN

G = A.exact_library()

def _q(rng, bits):
    den = rng.getrandbits(bits) | (1 << (bits-1)) | 1
    return G.mpq(rng.getrandbits(bits)-(1 << (bits-1)), den)


def _system(seed, cells, bits, common=False):
    rng = random.Random(seed)
    base = rng.getrandbits(bits) | 1
    def amount():
        if rng.random() < 0.1:
            return G.mpq(0)
        return G.mpq(rng.getrandbits(bits//2+1), base) if common else _q(rng, bits)
    energy = [amount() for _ in range(cells)]
    load = [amount() for _ in range(cells)]
    faces = []
    for _ in range(rng.randrange(0, 3*cells+1)):
        i = rng.randrange(cells)
        j = None if cells == 1 or rng.random() < 0.3 else rng.randrange(cells)
        faces.append((i, j, amount()))
    return energy, load, faces


SYSTEMS = [(seed, cells, bits, common) for seed, (cells, bits, common) in enumerate(
    [(1, 64, False), (1, 64, True), (7, 64, False), (7, 4096, True), (50, 256, False), (200, 64, False),
     (200, 128, True), (3, 65536, False), (3, 65536, True)])]



class _RecordingWorkspace(GMP.OwnedWorkspace):
    """The real F-B; records the lease count after each call."""
    def resize_before_allocation_or_after_drop(self, count):
        super().resize_before_allocation_or_after_drop(count)
        self.counts.append(self.lease.count)


class _OldWorkspace(GMP.OwnedWorkspace):
    """Today's F-B: every call reaches the lease."""
    def resize_before_allocation_or_after_drop(self, count):
        if not self.entered or self.finished:
            raise RuntimeError('workspace is not active')
        self.checkpoint()
        self.lease.resize(count)
        self.counts.append(self.lease.count)


class _OldReserve(PN._ProjectionArithmetic):
    """Today's reserve: both allowances on every call."""
    def reserve(self, bits):
        self.check()
        peak = max(self.peak_bits, bits, 1)
        slot = self.R.native_slot_allowance(self.R.RationalShape(peak, peak))
        amount = self.containers+self.history+self.live+64*slot+self.R.native_workspace_allowance(8*peak, 64)
        if amount > sys.maxsize:
            raise OverflowError('Fixed correction exceeds addressable memory')
        self.workspace.resize_before_allocation_or_after_drop(amount)
        self.peak_bits = peak


class _CachedOnce(PN._ProjectionArithmetic):
    """M-1: the fixed allowance cached once, ignoring the peak."""
    def reserve(self, bits):
        self.check()
        peak = max(self.peak_bits, bits, 1)
        if self._fixed_peak is None:
            slot = self.R.native_slot_allowance(self.R.RationalShape(peak, peak))
            self._fixed = 64*slot+self.R.native_workspace_allowance(8*peak, 64)
            self._fixed_peak = peak
        self.workspace.resize_before_allocation_or_after_drop(self.containers+self.history+self.live+self._fixed)
        self.peak_bits = peak


def _accounting_run(ar_cls, ws_cls, seed, cells, bits, common):
    """One synthetic correction on a real budget: values, lease counts, admit/release calls, totals, peaks."""
    energy, load, faces = _system(seed, cells, bits, common)
    budget, calls, peaks = RES.WorkBudget(1 << 50), [], set()
    admit, release = RES._admit_budgets, RES._release

    def admit_rec(count, *budgets, category='work', **kw):
        calls.append(('admit', count, category))
        return admit(count, *budgets, category=category, **kw)

    def release_rec(charged, count, **kw):
        calls.append(('release', count))
        return release(charged, count, **kw)

    with mock.patch.object(RES, '_admit_budgets', admit_rec), mock.patch.object(RES, '_release', release_rec):
        ws = ws_cls(budget, 0)
        ws.counts = []
        with ws:
            ar = ar_cls(ws, G, GMP, cells, len(faces), 1075, lambda: None)
            reserve = ar.reserve

            def recorded(bits):
                reserve(bits)
                peaks.add(ar.peak_bits)
            ar.reserve = recorded
            values = [(v.numerator, v.denominator) for v in CL._residual(ar, energy, faces, load)]
        return values, ws.counts, calls, budget.reserved_bytes, budget.peak_reserved_bytes, peaks


ACCOUNTING = [s for s in SYSTEMS if s[2] >= 4096]


class Accounting(unittest.TestCase):
    """H-C T-1: values, lease counts, admit/release calls and budget totals equal to today's (U-3, U-4)."""

    def _runs(self, ar_cls, ws_cls):
        runs = [(case, _accounting_run(ar_cls, ws_cls, *case), _accounting_run(_OldReserve, _OldWorkspace, *case))
                for case in ACCOUNTING]
        # Not every case grows the peak; at least one must, twice, or a cached-once allowance goes unseen.
        self.assertTrue(any(len(want[5]) >= 3 for _, _, want in runs), 'fixture must grow the peak at least twice')
        return runs

    def test_t1_exactness(self):
        for case, got, want in self._runs(PN._ProjectionArithmetic, _RecordingWorkspace):
            with self.subTest(case=case):
                self.assertEqual(got[:5], want[:5])

    def test_m1_cached_once_is_killed(self):
        # Not assertRaises around subTest: subTest swallows the failure, so the mutant must differ directly.
        self.assertTrue(any(got[:5] != want[:5] for _, got, want in self._runs(_CachedOnce, _RecordingWorkspace)))


def _policy_fault(policy, clear=lambda: None):
    """T-2: None if a mismatch raises twice and a pass is not queried again; else the failed case."""
    clear()
    with mock.patch.object(GMP.G, 'version', return_value='0.0.0'):
        for call in ('first', 'second'):
            try:
                policy()
            except RuntimeError:
                continue
            return call
    policy()
    with mock.patch.object(GMP.G, 'version', side_effect=AssertionError('backend queried again')):
        try:
            policy()
        except AssertionError:
            return 'requery'
    return None


def _fb_fault(ws_cls):
    """T-3: None if F-B skips an equal resize and still checkpoints; else the failed case."""
    cancelled = [False]
    ws = ws_cls(RES.WorkBudget(1 << 30), 5, cancelled=lambda: cancelled[0])
    with ws:
        with mock.patch.object(ws.lease, 'resize', wraps=ws.lease.resize) as lease_resize:
            ws.resize_before_allocation_or_after_drop(5)
            if lease_resize.called:
                return 'lease call'
        cancelled[0] = True
        try:
            ws.resize_before_allocation_or_after_drop(5)
            return 'checkpoint'
        except CancelledError:
            cancelled[0] = False
    return None


class PolicyAndResize(unittest.TestCase):
    """H-C T-2 (policy once per process) and T-3 (F-B), with mutant M-4."""

    def tearDown(self):
        GMP._installed_policy.cache_clear()

    def test_t2_policy(self):
        self.assertIsNone(_policy_fault(GMP._installed_policy, GMP._installed_policy.cache_clear))

    def test_m4_flag_before_comparison_is_killed(self):
        passed = []

        def mutant():
            if passed:
                return
            passed.append(True)
            if (G.version(), G.mp_version(), G.mp_limbsize()) != ('2.3.2', 'GMP 6.3.0', 64):
                raise RuntimeError('GMP accounting policy requires the reviewed installed backend')
        self.assertEqual(_policy_fault(mutant), 'second')

    def test_t3_equal_resize(self):
        self.assertIsNone(_fb_fault(GMP.OwnedWorkspace))


if __name__ == '__main__':
    unittest.main()
