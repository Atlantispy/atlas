"""A3 heat fixes: H5, S7IO-5, M4 and L21 acceptance tests.

H5: exact RATIONAL ledger rows use an explicit scalar streaming route whose
bound derives from the 1 MiB magnitude ceiling; r10 _equations equals r9 at
IV1 widths and on the hex mutation corpus. S7IO-5: exact_rows books from the
part bit lengths. M4: the compact codec lease covers only the three scalars.
L21: from_components refuses non-finite fields exactly like r12.

Byte identity is checked against the unchanged base modules (a3ref_*.py,
byte copies of the base tree) on adversarial inputs.
"""
from copy import deepcopy
import gc
import random
import sys
import tracemalloc
import unittest

import numpy as np

import test_heat_cold_patch as HCT  # noqa: E402  (sets the runtime/compact paths)
from atlas_tectonics.resources import WorkBudget  # noqa: E402
from content_cache import OWNER_BYTES, create_retained_scope  # noqa: E402
from compact_contracts import ContractError  # noqa: E402
from heat_ledger_tables import CompactHeatSnapshot  # noqa: E402
from record_tables import MAX_INTEGER_BYTES, RecordCodec  # noqa: E402
import a3ref_heat_cold_patch as BASE_HC  # noqa: E402
import a3ref_heat_ledger_issuer_patch as BASE_ISSUER  # noqa: E402
import a3ref_heat_ledger_tables as BASE_TABLES  # noqa: E402
import heat_cold_patch as HC  # noqa: E402
import heat_ledger_issuer_patch as ISSUER  # noqa: E402
import private_heat_checkpoint_consumer_r10 as C  # noqa: E402

RNG = random.Random(20261015)
IV1_WIDTHS = (1_724_160, 2_054_539)
CEILING_BITS = 8*MAX_INTEGER_BYTES


def wide(bits, odd=True):
    value = RNG.getrandbits(bits) | (1 << (bits-1))
    return value | 1 if odd else value


def equations():
    original = (HCT.HISTORICAL/'private_heat_checkpoint_consumer_r9.py').read_text(encoding='utf8')
    return HCT.extract(original, '_equations'), HCT.extract(C.transform(original), '_equations')


def run(fn, ar, meta, geometry, arrays, plan):
    try:
        fn(ar, meta, geometry, arrays, plan, 1.)
        result = ('pass',)
    except Exception as exc:  # parity of every outcome, including refusals
        result = (type(exc).__name__, str(exc))
    return result, ar.trace


class HexArithmetic(HCT.Arithmetic):
    """The reviewer's pair-shape checking decoder (parity_hex_mutations.py)."""
    def decode(self, value):
        if type(value) in (tuple, list):
            if len(value) != 2 or any(type(v) is not str for v in value):
                raise ValueError('pair shape')
        elif type(value) not in (int, float):
            raise TypeError('Original binary64 or exact owned rational/pair required')
        return super().decode(value)


def hex_fixture():
    meta, arrays, geometry, plan = HCT.fixture()
    convert = lambda pair: [hex(int(pair[0])), hex(int(pair[1]))]
    for key, value in tuple(meta.items()):
        if key.startswith('exact_') and type(value) is list and value and type(value[0]) is list:
            meta[key] = [convert(row) for row in value]
        elif key.startswith('exact_') or key == 'independently_supplied_absolute_residual_target':
            meta[key] = convert(value)
    plan['absolute_residual_target'] = ['0x1', '0x1']
    return meta, arrays, geometry, plan


class ParityCase:
    def compare(self, old, new, meta, arrays, geometry, plan, arithmetic=HCT.Arithmetic):
        expected = run(old, arithmetic(), deepcopy(meta), geometry, arrays, plan)
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='a3-h5-parity')
        snapshot = CompactHeatSnapshot.from_components(meta, arrays, scope=scope)
        with HC.ledger_access(snapshot, budget, None, HCT.RESOURCES) as view:
            ar = HC.ledger_arithmetic(HCT.RESOURCES)
            class Traced(ar, arithmetic):
                pass
            actual = run(new, Traced(), view.value, geometry, arrays, plan)
        snapshot.close()
        del snapshot, view
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)
        return expected, actual


class RationalRouteTests(ParityCase, unittest.TestCase):
    def test_r9_r10_parity_at_iv1_widths_and_the_magnitude_ceiling(self):
        old, new = equations()
        cases = []
        for bits in (1_000_000, 1_650_000, 1_700_000) + IV1_WIDTHS:
            K = (1 << (bits-1)) | 3
            cases.append(('enthalpy-%d' % bits, 'pass',
                lambda m, K=K: m['exact_corrected_enthalpy_j'].__setitem__(0, [hex(10*K), hex(K)])))
        K = wide(IV1_WIDTHS[0])
        cases.append(('enthalpy-wrong-value-%d' % IV1_WIDTHS[0], 'ValueError',
            lambda m, K=K: m['exact_corrected_enthalpy_j'].__setitem__(0, [hex(11*K), hex(K)])))
        for bits in (IV1_WIDTHS[1], CEILING_BITS):
            K = (1 << (bits-1)) | 1
            cases.append(('storage-zero-over-%d' % bits, 'pass',
                lambda m, K=K: m['exact_cell_storage_residual_j'].__setitem__(0, ['0x0', hex(K)])))
        K = (1 << (IV1_WIDTHS[1]-1)) | 5
        cases.append(('face-zero-over-%d' % IV1_WIDTHS[1], 'pass',
            lambda m, K=K: m['exact_paired_face_energy_j'].__setitem__(1, ['0x0', hex(K)])))
        cases.append(('source-zero-over-ceiling', 'pass',
            lambda m: m.update(exact_source_energy_j=['0x0', hex((1 << (CEILING_BITS-1)) | 1)])))
        for name, outcome, mutate in cases:
            with self.subTest(name=name):
                meta, arrays, geometry, plan = HCT.fixture()
                mutate(meta)
                expected, actual = self.compare(old, new, meta, arrays, geometry, plan)
                self.assertEqual(actual, expected)
                self.assertEqual(actual[0][0], outcome)

    def test_hex_mutation_corpus_parity(self):
        """The reviewer's 22 hex-spelling mutations: identical outcome and trace."""
        old, new = equations()
        M = [('valid', lambda m, a: None),
            ('stock', lambda m, a: m['exact_corrected_enthalpy_j'].__setitem__(0, ['0xb', '0x1'])),
            ('stock-unreduced-equal', lambda m, a: m['exact_corrected_enthalpy_j'].__setitem__(0, ['0x14', '0x2'])),
            ('stock-negzero-den', lambda m, a: m['exact_corrected_enthalpy_j'].__setitem__(0, ['0xa', '-0x1'])),
            ('target', lambda m, a: m.update(independently_supplied_absolute_residual_target=['0x2', '0x1'])),
            ('face-count', lambda m, a: m['exact_paired_face_energy_j'].pop()),
            ('face', lambda m, a: m['exact_paired_face_energy_j'].__setitem__(0, ['0x1', '0x1'])),
            ('retained', lambda m, a: m['exact_retained_solver_residual_j'].__setitem__(0, ['0x1', '0x1'])),
            ('projection', lambda m, a: m['exact_stock_projection_residual_j'].__setitem__(0, ['0x1', '0x1'])),
            ('storage', lambda m, a: m['exact_cell_storage_residual_j'].__setitem__(0, ['0x1', '0x1'])),
            ('source', lambda m, a: m.update(exact_source_energy_j=['0x1', '0x1'])),
            ('boundary', lambda m, a: m.update(exact_outward_boundary_energy_j=['0x1', '0x1'])),
            ('float-stock', lambda m, a: a['enthalpy_j'].__setitem__(0, 11.)),
            ('temperature', lambda m, a: a['temperature_k'].__setitem__(0, 11.)),
            ('row-as-float', lambda m, a: m['exact_corrected_enthalpy_j'].__setitem__(0, 10.0)),
            ('row-as-int', lambda m, a: m['exact_corrected_enthalpy_j'].__setitem__(0, 10)),
            ('row-as-bool', lambda m, a: m['exact_corrected_enthalpy_j'].__setitem__(0, True)),
            ('row-triple', lambda m, a: m['exact_corrected_enthalpy_j'].__setitem__(0, ['0xa', '0x1', '0x1'])),
            ('residual-key-missing', lambda m, a: m.pop('exact_retained_solver_residual_j')),
            ('source-as-float', lambda m, a: m.update(exact_source_energy_j=0.0)),
            ('target-as-string', lambda m, a: m.update(independently_supplied_absolute_residual_target='0x1')),
            ('dyadic-wide-den', lambda m, a: m['exact_corrected_enthalpy_j'].__setitem__(
                0, [hex(10 << 400_000), hex(1 << 400_000)])),
        ]
        for name, mutate in M:
            with self.subTest(name=name):
                meta, arrays, geometry, plan = hex_fixture()
                mutate(meta, arrays)
                expected, actual = self.compare(old, new, meta, arrays, geometry, plan, HexArithmetic)
                self.assertEqual(actual, expected)

    def test_route_equals_base_export_on_adversarial_spellings(self):
        rows = [['0x0', '0x1'], ['-0x1', '0x3'], ['0x14', '0x2'], ['0xa', '-0x1'],
                [hex(1 << 4_000_003), hex(1 << 77)], [hex(-(1 << 999_999)), hex(3)],
                [hex(-wide(1_000_000)), hex(wide(999_999))],
                [hex(wide(IV1_WIDTHS[0])), hex(wide(IV1_WIDTHS[1]))],
                [hex((1 << CEILING_BITS)-1), hex(1 << (CEILING_BITS-1))]]
        others = [['10', '1'], ['0xa', '0x1', '0x1'], 1.5, ['0x1', 'x'], {'a': '0x1'}]
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='a3-h5-route')
        record = RecordCodec().pack_record(dict(rows=rows+others), record_schema='a3.rows', scope=scope, check=lambda: None)
        with record.root() as root, root.field('rows') as values:
            for at, row in enumerate(rows):
                with values.at(at) as ref:
                    with HC.rational_row(ref, lambda: None) as owned:
                        self.assertEqual(owned.value, row)
                        if len(row[0])+len(row[1]) < 400_000:
                            with ref.export(max_logical_bytes=32 << 20, max_owned_bytes=32 << 20) as base:
                                self.assertEqual(owned.value, base.value)
                        self.assertEqual([type(v) for v in owned.value], [str, str])
            for at in range(len(others)):
                with values.at(len(rows)+at) as ref:
                    self.assertIsNone(HC.rational_row(ref, lambda: None))
        record.close()
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_ledger_rows_keep_base_values_below_row_bytes(self):
        """Every value base r10 already accepted is returned unchanged."""
        meta, arrays, _, _ = hex_fixture()
        meta['exact_paired_face_energy_j'] = [[hex(-wide(n)), hex(wide(n+3))] for n in (1, 64, 30_000, 400_000)]
        meta['decimal_rows'] = [['10', '1'], ['-3', '7']]
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='a3-h5-base')
        snapshot = CompactHeatSnapshot.from_components(meta, arrays, scope=scope)
        for module in (BASE_HC, HC):
            with module.ledger_access(snapshot, budget, None, HCT.RESOURCES) as view:
                faces = [row.value for row in view.value['exact_paired_face_energy_j']]
                target = view.value['independently_supplied_absolute_residual_target']
                self.assertEqual(faces, meta['exact_paired_face_energy_j'])
                self.assertEqual(target, meta['independently_supplied_absolute_residual_target'])
                self.assertEqual(view.value['decimal_rows'], meta['decimal_rows'])
                del faces, target
        snapshot.close()
        del snapshot, view
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_route_cancellation_failure_funding_and_tamper_bound(self):
        from concurrent.futures import CancelledError
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='a3-h5-cancel')
        record = RecordCodec().pack_record([[hex(wide(IV1_WIDTHS[1])), '0x1']], record_schema='a3.rows', scope=scope, check=lambda: None)
        baseline = budget.reserved_bytes
        def cancelled():
            raise CancelledError('explicit test cancellation')
        held = []
        with record.root() as root, root.at(0) as ref:
            try:
                HC.rational_row(ref, cancelled)
            except CancelledError as error:
                held.append(error)
        self.assertGreater(budget.reserved_bytes, baseline)
        held.clear()
        gc.collect()
        self.assertEqual(budget.reserved_bytes, baseline)
        # A declared width beyond the 1 MiB ceiling refuses before allocation.
        with record.root() as root, root.at(0) as ref:
            original = ref._view._v
            def forged(name, index):
                value = original(name, index)
                return HC.HEX_SCALAR_LOGICAL+1 if name == 'node.length' and value > 1000 else value
            ref._view._v = forged
            try:
                with self.assertRaises(ContractError):
                    HC.rational_row(ref, lambda: None)
            finally:
                del ref._view._v
        record.close()
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_rational_row_booking_measured_on_unique_iv1_rows(self):
        """real <= booked <= 1.3 x real (tracemalloc, memory only)."""
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='a3-h5-measure')
        rows = [[hex(-wide(IV1_WIDTHS[1])), hex(wide(IV1_WIDTHS[1]))],
                [hex(wide(IV1_WIDTHS[0])), hex(wide(IV1_WIDTHS[0]))],
                ['0x0', hex(wide(IV1_WIDTHS[1]))],
                # The census mean string (356.5 MB over 23,984 strings) is about 14.9 KB.
                [hex(wide(59_600)), hex(wide(59_600))]]
        record = RecordCodec().pack_record(rows, record_schema='a3.rows', scope=scope, check=lambda: None)
        del rows
        gc.collect()
        for at in range(4):
            with record.root() as root, root.at(at) as ref:
                lengths = [ref._view._v('node.length', ref._view._child(ref.index, i)) for i in (0, 1)]
                retained_booked = HC.RATIONAL_ROW_FIXED+sum(lengths)
                peak_booked = retained_booked+OWNER_BYTES+HC.rational_transient(lengths)
                # Warm the record's own column caches, which the record owns.
                HC.rational_row(ref, lambda: None).close()
                before = budget.reserved_bytes
                tracemalloc.start()
                start = tracemalloc.get_traced_memory()[0]
                owned = HC.rational_row(ref, lambda: None)
                current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                held_booked = budget.reserved_bytes-before
                retained_real, peak_real = current-start, peak-start
                with self.subTest(row=at, retained_real=retained_real, retained_booked=held_booked,
                                  peak_real=peak_real, peak_booked=peak_booked):
                    # The scope adds its fixed 4 KiB owner charge.
                    self.assertEqual(held_booked, retained_booked+OWNER_BYTES)
                    self.assertLessEqual(retained_real, held_booked)
                    self.assertLessEqual(held_booked, 1.3*retained_real)
                    self.assertLessEqual(peak_real, peak_booked)
                    self.assertLessEqual(peak_booked, 1.3*peak_real)
                owned.close()
                del owned
        record.close()
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


class ExactRowTests(unittest.TestCase):
    def values(self):
        import gmpy2
        return [gmpy2.mpq(0), gmpy2.mpq(-1, 3), gmpy2.mpq(1 << 400_000, 3),
                gmpy2.mpq(-wide(IV1_WIDTHS[1]), wide(IV1_WIDTHS[1])),
                gmpy2.mpq(wide(IV1_WIDTHS[0]), wide(IV1_WIDTHS[0]-17)),
                gmpy2.mpq(7, 1 << 2_000_000), gmpy2.mpq(wide(64), wide(64))]

    def test_rows_and_packed_identity_equal_base(self):
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='a3-rows-parity')
        values = self.values()
        packed = []
        for module in (BASE_ISSUER, ISSUER):
            packed.append(RecordCodec().pack_record(module.exact_rows(values, scope, lambda: None),
                record_schema='a3.exact-rows', scope=scope, check=lambda: None))
        self.assertEqual(packed[0].identity(), packed[1].identity())
        with packed[1].root() as root:
            for at, value in enumerate(values):
                with root.at(at) as ref, HC.rational_row(ref, lambda: None) as row:
                    self.assertEqual(row.value, [hex(int(value.numerator)), hex(int(value.denominator))])
        for record in packed:
            record.close()
        del packed
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_row_booking_measured_from_bit_lengths(self):
        """Committed row charge vs the retained row; peak charge vs traced peak."""
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='a3-rows-measure')
        values = self.values()[3:6]
        stream = ISSUER.exact_rows(values, scope, lambda: None).rows_factory()
        for value in values:
            bits = (value.numerator.bit_length(), value.denominator.bit_length())
            parts = [ISSUER.row_part_bytes(b) for b in bits]
            size = ISSUER.ROW_FIXED_BYTES+parts[0][0]+parts[1][0]
            work = 4096+max(parts[0][1], parts[1][1])
            before = budget.reserved_bytes
            tracemalloc.start()
            start = tracemalloc.get_traced_memory()[0]
            row = next(stream)
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            retained = sys.getsizeof(row.value)+sum(sys.getsizeof(p) for p in row.value)
            with self.subTest(bits=bits, size=size, retained=retained, traced_peak=peak-start,
                              peak_booked=size+work, old_booking=4096+16*sys.getsizeof(value)):
                self.assertEqual(budget.reserved_bytes-before, size+OWNER_BYTES)
                self.assertLessEqual(retained, size)
                self.assertLessEqual(size+OWNER_BYTES, 1.3*retained)
                # tracemalloc sees the Python int and text; the GMP copy is
                # outside it, so the traced peak is a lower bound.
                self.assertLessEqual(peak-start, size+work)
                self.assertLess(size+work, 4096+16*sys.getsizeof(value))
            row.close()
            del row
        stream.close()
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


class CompactCodecLeaseTests(unittest.TestCase):
    def test_compact_lease_covers_only_the_three_scalars(self):
        import gmpy2
        from heat_ledger_issuer_patch import compact_codec_bytes
        if str(HCT.HISTORICAL) not in sys.path:
            sys.path.append(str(HCT.HISTORICAL))
        import private_heat_issuer_resources_r1 as R1
        q = lambda bits: gmpy2.mpq(wide(bits), wide(bits))
        # Census proportions at 1/64 width (as codec_overbooking.py), with
        # scalars at IV1 row widths so the measured lease is not all fixed cost.
        exact = dict(new=[q(1700) for _ in range(855)], retained=[q(1700) for _ in range(855)],
                     projection=[q(1700) for _ in range(855)], public=[q(1700) for _ in range(855)],
                     canonical=[q(600) for _ in range(8569)], target=q(64), source_total=q(IV1_WIDTHS[1]),
                     outward=q(IV1_WIDTHS[0]))
        groups = tuple(exact[k] for k in ('new', 'retained', 'projection', 'public', 'canonical'))
        groups += ((exact['target'], exact['source_total'], exact['outward']),)
        budget = WorkBudget(4 << 30)
        legacy = R1.projection_output_plan(groups, budget=budget)['bytes']
        compact = compact_codec_bytes(exact, R1, budget, None)
        tracemalloc.start()
        start = tracemalloc.get_traced_memory()[0]
        scalars = [[hex(int(v.numerator)), hex(int(v.denominator))]
                   for v in (exact['target'], exact['source_total'], exact['outward'])]
        peak = tracemalloc.get_traced_memory()[1]-start
        tracemalloc.stop()
        held = sum(sys.getsizeof(pair)+sys.getsizeof(pair[0])+sys.getsizeof(pair[1]) for pair in scalars)
        with self.subTest(legacy=legacy, compact=compact, held=held, traced_peak=peak):
            self.assertLessEqual(held, compact)
            self.assertLessEqual(peak, compact)
            self.assertLessEqual(compact, 1.3*peak)
            self.assertLess(compact, legacy/10)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_projection_source_changes_only_the_compact_lease(self):
        import difflib
        import private_heat_indexed_runtime as P
        source = P.projection_source(
            (HCT.HISTORICAL/'private_heat_native_projection_r4.py').read_text(encoding='utf8'))
        new, old = ISSUER.projection_source(source), BASE_ISSUER.projection_source(source)
        compile(new, '<a3-projection>', 'exec')
        changed = [line for line in difflib.ndiff(old.splitlines(), new.splitlines())
                   if line[:2] in ('- ', '+ ')]
        self.assertEqual(changed, [
            "-         work.stack.enter_context(R.workspace(budget, codec['bytes'], cancel=cancel,",
            "+         work.stack.enter_context(R.workspace(budget, codec['bytes'] if record_scope is None else",
            "+                                              HEAT_LEDGER.compact_codec_bytes(exact, R, budget, cancel), cancel=cancel,"])
        # The legacy route (record_scope None) still reserves the whole plan.
        self.assertIn("codec['bytes'] if record_scope is None else", new)


class FiniteFieldTests(unittest.TestCase):
    def test_nonfinite_fields_refuse_like_r12_and_release(self):
        from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
        from atlas_tectonics._validation import TectonicsError
        meta = dict(schema='a3.finite', value=['0x1', '0x3'])
        for bad in (np.nan, np.inf, -np.inf):
            for position in (0, 65_535, 65_536, 200_000):
                fields = dict(a=np.ones(4), b=np.ones(200_001))
                fields['b'][position] = bad
                with self.subTest(bad=bad, position=position):
                    with self.assertRaises(TectonicsError) as legacy:
                        RegionalMechanicalSnapshot(meta, fields)
                    budget = WorkBudget(1 << 30)
                    scope = create_retained_scope(budget, process_epoch='a3-finite')
                    with self.assertRaises(TectonicsError) as compact:
                        CompactHeatSnapshot.from_components(meta, fields, scope=scope)
                    self.assertEqual(str(compact.exception), str(legacy.exception))
                    del compact
                    gc.collect()
                    scope.close()
                    self.assertEqual(budget.reserved_bytes, 0)

    def test_finite_fields_byte_identical_to_base_and_r12(self):
        from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
        meta = dict(schema='a3.finite', rows=[['0x0', '0x1'], [hex(-wide(5000)), hex(wide(77))]],
                    text='0x1F', number=-0.0)
        fields = dict(a=np.array([-0.0, 5e-324, np.nextafter(0, 1), -1e308]), b=np.zeros((3, 1)),
                      c=np.linspace(-1, 1, 131_073))
        legacy = RegionalMechanicalSnapshot(meta, fields)
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='a3-finite-parity')
        new = CompactHeatSnapshot.from_components(meta, fields, scope=scope)
        base = BASE_TABLES.CompactHeatSnapshot.from_components(meta, fields, scope=scope)
        self.assertEqual(new.result_id, legacy.result_id)
        self.assertEqual(new.result_id, base.result_id)
        self.assertEqual(new.metadata_identity, base.metadata_identity)
        for name in fields:
            self.assertEqual(new.array(name).tobytes(), base.array(name).tobytes())
            self.assertEqual(new.array(name).tobytes(), legacy.array(name).tobytes())
        new.close(); base.close()
        del new, base
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
