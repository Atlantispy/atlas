"""Exact logical parity and ownership at the compact heat boundary."""
import gc
from hashlib import sha256
from pathlib import Path
import sys
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'), str(HERE.parent)]
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import ChargeSpec, create_retained_scope
from heat_ledger_tables import CompactHeatSnapshot, MAX_FIELD_BYTES
from record_tables import StreamingRows, canonical
from record_views import RecordRef, _owned


class HeatLedgerTests(unittest.TestCase):
    def setUp(self):
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='heat-ledger')

    def tearDown(self):
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def owned(self, value):
        with self.scope.reserve(ChargeSpec('heat-row-fixture', 32 << 20)) as reservation:
            return reservation.commit(value)

    def test_legacy_identity_exact_spellings_native_float_bytes(self):
        data = {'cells': [{'q': ['0x2', '0x4']}, {'q': ['-0x0', '+0x4']}],
                'decimal': ['01', '1.0'], 'unicode': 'é\ud800'}
        arrays = {'x': np.array([-0., 0., np.nextafter(1., 2.)]), 'empty': np.empty(0)}
        legacy = RegionalMechanicalSnapshot(data, arrays)
        streamed = dict(data, cells=StreamingRows(2, lambda: (self.owned(r) for r in data['cells'])))
        compact = CompactHeatSnapshot.from_components(streamed, arrays, scope=self.scope)
        self.assertEqual(compact.result_id, legacy.result_id)
        self.assertEqual(compact.metadata_identity.sha256, sha256(legacy._metadata).hexdigest())
        self.assertEqual(compact.metadata_identity.canonical_bytes, len(legacy._metadata))
        self.assertEqual(compact.nbytes, legacy.nbytes)
        for key in arrays:
            self.assertEqual(compact.array(key).tobytes(), legacy.array(key).tobytes())
        with compact.field('cells') as field:
            self.assertEqual(field.value, data['cells'])
        with self.assertRaisesRegex(ContractError, 'whole heat descriptor'):
            compact.descriptor()
        compact.close()

    def test_measured_giant_rational_widths_roundtrip(self):
        numerator = (1 << (2_054_462-1))+3
        denominator = (1 << (2_054_539-1))+1
        data = {'q': [hex(numerator), hex(denominator)]}
        compact = CompactHeatSnapshot.from_components(data, {'x': np.zeros(1)}, scope=self.scope)
        with compact.field('q', max_logical_bytes=2 << 20, max_owned_bytes=32 << 20) as held:
            self.assertEqual(held.value, data['q'])
        self.assertEqual(compact.metadata_identity.sha256, sha256(canonical(data)).hexdigest())
        compact.close()

    def test_escaped_array_remains_funded_after_close(self):
        baseline = self.scope.stats().retained_bytes
        compact = CompactHeatSnapshot.from_components({'q': ['0x1', '0x2']},
            {'x': np.arange(10, dtype=np.float64)}, scope=self.scope)
        escaped = compact.array('x')
        compact.close()
        self.assertGreater(self.scope.stats().retained_bytes, 80)
        self.assertFalse(escaped.flags.writeable)
        self.assertEqual(escaped[-1], 9.)
        del escaped
        gc.collect()
        self.assertEqual(self.scope.stats().retained_bytes, baseline)

    def test_field_bounds_identity_refusal_and_cancellation(self):
        compact = CompactHeatSnapshot.from_components({'rows': [1]*100}, {'x': np.zeros(1)}, scope=self.scope)
        with self.assertRaises(ContractError):
            compact.field('rows', max_logical_bytes=10, max_owned_bytes=65536)
        compact.close()
        with self.assertRaisesRegex(ContractError, 'identity differs'):
            CompactHeatSnapshot.from_components({}, {'x': np.zeros(1)}, scope=self.scope,
                                                expected_result_id='f'*64)
        with self.assertRaisesRegex(RuntimeError, 'cancel'):
            CompactHeatSnapshot.from_components({}, {'x': np.zeros(1)}, scope=self.scope,
                                                check=lambda: (_ for _ in ()).throw(RuntimeError('cancel')))
        self.assertEqual(MAX_FIELD_BYTES, 512 << 20)

    def test_custom_reference_uses_actual_scalar_and_actual_width(self):
        compact = CompactHeatSnapshot.from_components({'template': '0'*64}, {'x': np.zeros(1)}, scope=self.scope)
        class WiderScalar(RecordRef):
            def _logical_length(self):
                return len(canonical('é'*10000))

            def scalar(self, *, max_owned_bytes):
                return _owned(self.scope, 100000, lambda: 'é'*10000)
        with compact.ledger as root, root.field('template') as scalar:
            actual = WiderScalar(scalar._view, scalar.index)
        with self.assertRaises(ContractError):
            actual.export(max_logical_bytes=100000, max_owned_bytes=700000)
        with actual.export(max_logical_bytes=100000, max_owned_bytes=1 << 20) as value:
            self.assertEqual(value.value, 'é'*10000)
        actual.close()
        compact.close()


if __name__ == '__main__':
    unittest.main()
