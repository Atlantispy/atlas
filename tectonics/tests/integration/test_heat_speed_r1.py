"""Heat speed plan r1: equal-results tests for H-D (cell sums), H-F (encoded equality), H-H (nought column), H-C.

H-D: `heat-cell-sums.md` T-S1, T-S2 and its four killing mutants. H-F: `uncovered-spans-heat.md` T-H2a to T-H2e and
its two mutants. H-H: `ladder-unresolved.md` T-L1 (synthetic solves), T-L4 (nought-column case), T-L5 (skipped rungs
open nothing) and T-L7; T-L3 and T-L6 belong to the parked null-vector form and have no case here. Today's loops are
kept in this file as the reference. Synthetic inputs only; captured-record forms ride the comparison run.
H-C: `heat-accounting-fa-fb-r1.md` T-1 to T-3 and mutants M-1 to M-4.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import random
import sys
import unittest
from unittest import mock

from atlas_tectonics.integration import resources as RES
from atlas_tectonics._private.integration.heat import closed_owned as CL
from atlas_tectonics._private.integration.heat import correction_owned as O
from atlas_tectonics._private.integration.heat import finish_arithmetic as A
from atlas_tectonics._private.integration.heat import finish_issue_owned as FI
from atlas_tectonics._private.integration.heat import gmp_resources as GMP
from atlas_tectonics._private.integration.heat import projection_numerics as PN
from atlas_tectonics._private import private_heat_certification_kernel_r1 as K
from atlas_tectonics._private import private_heat_finish_kernel_r3 as FK

G = A.exact_library()


class _Lease:
    count = 0


class _Workspace:
    """Records every resize; never refuses."""
    def __init__(self):
        self.lease, self.resizes = _Lease(), []

    def resize_before_allocation_or_after_drop(self, amount):
        self.resizes.append(amount)
        self.lease.count = amount


class _Counting(PN._ProjectionArithmetic):
    """Records the widest operand or result width any op met (T-S2's lower bound on the booked peak)."""
    widest = 0

    def op(self, operation, left, right):
        result = super().op(operation, left, right)
        for v in (left, right, result):
            s = self.shape(v)
            self.widest = max(self.widest, s.numerator_bits, s.denominator_bits)
        return result


def _owner(n, f, cls=_Counting):
    return cls(_Workspace(), G, GMP, n, f, 1075, lambda: None)


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


# Today's loops (cb43e88), kept as the reference.
def _old_loaded(ar, energy, faces, load):
    values = ar.array(len(energy))
    for i, (a, b) in enumerate(zip(energy, load, strict=True)):
        ar.put(values, i, ar.op('subtract', a, b))
    for i, j, q in faces:
        ar.put(values, i, ar.op('add', values[1][i], q))
        if j is not None:
            ar.put(values, j, ar.op('subtract', values[1][j], q))
    return values[1]


def _old_copy(ar, energy, faces):
    result = ar.copy(energy)
    for i, j, amount in faces:
        ar.put(result, i, ar.op('add', result[1][i], amount))
        if j is not None:
            ar.put(result, j, ar.op('subtract', result[1][j], amount))
    return result[1]


def _old_zero(ar, n, faces):
    """projection_numerics._calculate / checkpoint_consumer._equations: 0, then +-amount by owner sign."""
    out = ar.array(n)
    for at in range(n):
        ar.put(out, at, G.mpq(0))
    for i, j, amount in faces:
        for owner, sign in ((i, 1),) + (() if j is None else ((j, -1),)):
            increment = amount if sign == 1 else ar.neg(amount)
            ar.put(out, owner, ar.op('add', out[1][owner], increment))
    return out[1]


def _new_zero(ar, n, faces):
    zero = G.mpq(0)
    plus, minus = [[zero] for _ in range(n)], [[] for _ in range(n)]
    for i, j, amount in faces:
        plus[i].append(amount)
        if j is not None:
            minus[j].append(amount)
    return ar.cell_sums(plus, minus)[1]


def _same(case, got, want):
    case.assertEqual(len(got), len(want))
    for g, w in zip(got, want, strict=True):
        case.assertIs(type(g), G.mpq)
        case.assertEqual((g.numerator, g.denominator), (w.numerator, w.denominator))


class CellSums(unittest.TestCase):
    """T-S1 values, T-S2 counts and peak, at every call-site shape."""

    def _check(self, new, old, *args):
        for seed, cells, bits, common in SYSTEMS:
            with self.subTest(seed=seed, cells=cells, bits=bits, common=common):
                energy, load, faces = _system(seed, cells, bits, common)
                a, b = _owner(cells, len(faces)), _owner(cells, len(faces))
                inputs = {'loaded': (energy, faces, load), 'copy': (energy, faces), 'zero': (cells, faces)}[args[0]]
                got, want = new(a, *inputs), old(b, *inputs)
                _same(self, got, want)
                self.assertEqual(a.operations, b.operations)
                self.assertGreaterEqual(a.peak_bits, a.widest)

    def test_closed_residual(self):
        self._check(CL._residual, _old_loaded, 'loaded')

    def test_issue_loaded_residual(self):
        self._check(FI._IssueArithmetic.loaded_residual, _old_loaded, 'loaded')

    def test_correction_residual(self):
        self._check(lambda ar, e, f: O._Arithmetic.residual(ar, e, f)[1], _old_copy, 'copy')

    def test_zero_started_sites(self):
        self._check(_new_zero, _old_zero, 'zero')


class CellSumMutants(unittest.TestCase):
    """Each mutant must fail T-S1 or T-S2 (heat-cell-sums.md, killing mutants)."""

    def _killed(self, new, old, form):
        try:
            CellSums('test_closed_residual')._check(new, old, form)
        except AssertionError:
            return
        self.fail('mutant survived')

    def test_second_owner_in_first_list(self):
        def mutant(ar, energy, faces, load):
            plus, minus = [[a] for a in energy], [[b] for b in load]
            for i, j, q in faces:
                plus[i].append(q)
                if j is not None:
                    plus[j].append(q)
            return ar.cell_sums(plus, minus)[1]
        self._killed(mutant, _old_loaded, 'loaded')

    def test_final_subtract_dropped(self):
        class Mutant(_Counting):
            def cell_sums(self, plus, minus, into=None):
                result = self.array(len(plus))
                for at, terms in enumerate(plus):
                    self.put(result, at, self._tree(terms, 0, len(terms)))
                return result
        self._killed(lambda ar, *a: CL._residual(_rebind(ar, Mutant), *a), _old_loaded, 'loaded')

    def test_tree_skips_last_of_odd_list(self):
        class Mutant(_Counting):
            def _tree(self, terms, lo, hi):
                hi = hi-1 if (hi-lo) % 2 and hi-lo > 1 else hi
                return super()._tree(terms, lo, hi)
        self._killed(lambda ar, *a: _new_zero(_rebind(ar, Mutant), *a), _old_zero, 'zero')

    def test_bare_addition(self):
        class Mutant(_Counting):
            def _tree(self, terms, lo, hi):
                total = terms[lo]
                for v in terms[lo+1:hi]:
                    total = total+v
                return total
        self._killed(lambda ar, *a: _new_zero(_rebind(ar, Mutant), *a), _old_zero, 'zero')

    def test_zero_dropped(self):
        def mutant(ar, n, faces):
            plus, minus = [[] for _ in range(n)], [[] for _ in range(n)]
            for i, j, amount in faces:
                plus[i].append(amount)
                if j is not None:
                    minus[j].append(amount)
            plus = [terms or [G.mpq(0)] for terms in plus]
            return ar.cell_sums(plus, minus)[1]
        self._killed(mutant, _old_zero, 'zero')


def _rebind(ar, cls):
    ar.__class__ = cls
    return ar


class EncodedEqual(unittest.TestCase):
    """T-H2a to T-H2e on synthetic values in the writer's encoding."""

    VALUES = [G.mpq(0), G.mpq(1), G.mpq(-7, 3), G.mpq(2**200+1, 3**90), 5, G.mpq(-(2**4000)+3, 2**4001-1)]

    def _encoded(self):
        return [FK._encode_rational(G.mpq(v)) for v in self.VALUES]

    def _counted(self):
        ar = _owner(1, 1, PN._ProjectionArithmetic)
        ar.decodes = 0
        decode = ar.decode
        def counting(value):
            ar.decodes += 1
            return decode(value)
        ar.decode = counting
        return ar

    def test_a_first_path_no_decode(self):
        ar = self._counted()
        ar.encoded_equal(self.VALUES, self._encoded(), 'x')
        self.assertEqual(ar.decodes, 0)

    def test_b_unreduced_pair_second_path(self):
        ar = self._counted()
        ar.encoded_equal([G.mpq(1, 2)], [['2', '4']], 'x')
        self.assertEqual(ar.decodes, 1)

    def test_c_changed_pair_refused(self):
        ar = self._counted()
        encoded = self._encoded()
        encoded[3] = [str(int(encoded[3][0])+1), encoded[3][1]]
        with self.assertRaisesRegex(ValueError, 'Returned x differs from the actual original values'):
            ar.encoded_equal(self.VALUES, encoded, 'x')

    def test_d_recorded_figures_equal(self):
        new, old = self._counted(), _owner(1, 1, PN._ProjectionArithmetic)
        new.encoded_equal(self.VALUES, self._encoded(), 'x')
        for value, pair in zip(self.VALUES, self._encoded(), strict=True):
            self.assertTrue(old.equal(value, old.decode(pair)))
        self.assertEqual((new.peak_bits, new.operations, new.equality_evidence, new.workspace.resizes[-1]),
                         (old.peak_bits, old.operations, old.equality_evidence, old.workspace.resizes[-1]))

    def test_e_encoder_and_decode_inverse(self):
        ar = _owner(1, 1, PN._ProjectionArithmetic)
        for value in self.VALUES:
            self.assertEqual(ar.decode(FK._encode_rational(G.mpq(value))), value)

    def test_mutants(self):
        def refuse_on_string_difference(self, values, encoded, label):
            for value, pair in zip(values, encoded, strict=True):
                if pair != FK._encode_rational(G.mpq(value)):
                    raise ValueError('Returned '+label+' differs from the actual original values')
        def skip_second_path(self, values, encoded, label):
            for value, pair in zip(values, encoded, strict=True):
                self.equal(value, value)
        for mutant, test in ((refuse_on_string_difference, 'test_b_unreduced_pair_second_path'),
                             (skip_second_path, 'test_c_changed_pair_refused')):
            with self.subTest(mutant=mutant.__name__), \
                    mock.patch.object(PN._ProjectionArithmetic, 'encoded_equal', mutant):
                result = unittest.TestResult()
                EncodedEqual(test).run(result)
                self.assertFalse(result.wasSuccessful())


class NoughtColumn(unittest.TestCase):
    """H-H: proves or abstains (T-L7, M-2), ends HK1's ladder with today's outcome (T-L1, T-L4, T-L5)."""

    SINGULAR = [[2, 0, 1], [1, G.mpz(0), 3], [G.mpq(1, 2), G.mpq(0), 1]]
    FULL = [[2, 1, 0], [1, 3, 1], [0, 1, 4]]

    def test_claims(self):
        self.assertEqual(K.nought_column(self.SINGULAR), 1)
        self.assertIsNone(K.nought_column(self.FULL))

    def test_l7_nought_but_one_row(self):
        self.assertIsNone(K.nought_column([[1, 0], [2, 0], [3, G.mpq(1, 10**40)]]))

    def test_abstains_on_other_types_and_ragged(self):
        from fractions import Fraction
        for odd in (0.0, False, Fraction(0), -0.0):
            with self.subTest(odd=odd):
                self.assertIsNone(K.nought_column([[1, odd], [2, 0]]))
        self.assertIsNone(K.nought_column([[1, 0], [2]]))
        self.assertIsNone(K.nought_column([]))

    def test_l4_singular_unresolved_at_every_rung_today(self):
        for precision in K.PRECISIONS:
            with self.subTest(precision=precision), self.assertRaises(K.Unresolved):
                K.solve_enclosure(self.SINGULAR, [1, 0, 1], precision=precision)

    def _weights(self, matrix, rhs):
        audit = {}
        try:
            keys = [('cell', 0), ('cell', 1), ('cell', 2)]
            result = K.certified_weights(matrix, rhs, keys, tuple(keys[:2]), 0, [1, 1, 1], evidence=audit)
        except K.Unresolved as error:
            result = ('UNRESOLVED', str(error))
        return result, [{k: v for k, v in a.items() if k != 'seconds'} for a in audit['attempts']]

    def test_l5_skipped_rungs_open_nothing(self):
        with mock.patch.object(K, 'solve_enclosure', side_effect=AssertionError('rung ran')):
            result, attempts = self._weights(self.SINGULAR, [1, 0, 1])
        self.assertEqual(result, ('UNRESOLVED',
                                  'All declared certification precisions exhausted; exact route/refusal required'))
        self.assertEqual(attempts, [dict(status='UNRESOLVED', proof='nought-column', column=1)])

    def test_l1_outcomes_equal_with_and_without(self):
        for matrix, rhs in ((self.SINGULAR, [1, 0, 1]), (self.FULL, [1, 1, 1])):
            with self.subTest(matrix=matrix):
                got, _ = self._weights(matrix, rhs)
                with mock.patch.object(K, 'nought_column', return_value=None):
                    want, _ = self._weights(matrix, rhs)
                self.assertEqual(got, want)

    def test_scan_stopping_early_is_killed(self):
        def first_row_only(matrix):
            for column, value in enumerate(matrix[0]):
                if type(value) is int and value == 0:
                    return column
            return None
        with mock.patch.object(K, 'nought_column', first_row_only):
            result = unittest.TestResult()
            NoughtColumn('test_l7_nought_but_one_row').run(result)
        self.assertFalse(result.wasSuccessful())


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
