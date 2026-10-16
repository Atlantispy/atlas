"""Native identity and immutable-array parity of the compact result holder."""
import gc
from types import SimpleNamespace
import unittest
from concurrent.futures import CancelledError

import numpy as np
import test_spatial_records_patch as F
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
import live_spatial_patch as LIVE
import live_transport_result as RESULT


class ResultTests(unittest.TestCase):
    def test_exact_native_identity_arrays_and_bounded_record_view(self):
        budget = F.WorkBudget(256 << 20)
        scope = F.create_retained_scope(budget, process_epoch='transport-result-test')
        metadata = dict(schema='atlas.spatial-implicit-transport.v1', exact_stocks={
            'mass': [['0x1', '0x3'], ['0x2', '0x3']]}, cell_ids=['a', 'b'],
            nested={'literal': 'small', 'float': .125})
        arrays = {'stock:mass': np.array([1./3, 2./3]),
                  'matrix': np.arange(12., dtype='float64').reshape(2, 6)[:, ::2]}
        native = RegionalMechanicalSnapshot(metadata, arrays)
        with LIVE.construction(scope, budget=budget):
            compact = RESULT.make_snapshot(metadata, arrays, budget, RegionalMechanicalSnapshot)
        self.assertEqual(compact.result_id, native.result_id)
        self.assertEqual(RESULT.identity(compact, budget), native.result_id)
        object.__setattr__(compact, 'result_id', 'cached-id-is-not-authority')
        self.assertEqual(RESULT.identity(compact, budget), native.result_id)
        object.__setattr__(compact, 'result_id', native.result_id)
        with self.assertRaises(CancelledError):
            RESULT.identity(compact, budget, lambda: True)
        for name in compact.array_names:
            self.assertEqual(compact.array(name).tobytes(), native.array(name).tobytes())
            self.assertFalse(compact.array(name).flags.writeable)
        arrays['stock:mass'][:] = 99.
        self.assertEqual(compact.array('stock:mass').tobytes(), native.array('stock:mass').tobytes())
        view = RESULT.result_record(SimpleNamespace(_snapshot=compact, result_id=compact.result_id))
        held = view.export(max_logical_bytes=1 << 20, max_owned_bytes=1 << 20)
        self.assertEqual(held.value, dict(result_id=native.result_id, **metadata))
        with self.assertRaisesRegex(F.ContractError, 'owned record'):
            compact.descriptor()
        held.close(); view.close()
        escaped = compact.array('stock:mass')
        del held, view, compact
        self.assertGreater(budget.reserved_bytes, 5120)
        self.assertEqual(escaped.tobytes(), native.array('stock:mass').tobytes())
        del escaped
        self.assertEqual(budget.reserved_bytes, 5120)
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_no_context_preserves_native_snapshot(self):
        budget = F.WorkBudget(256 << 20)
        result = RESULT.make_snapshot({'test': True}, {'x': np.zeros(1)}, budget, RegionalMechanicalSnapshot)
        self.assertIs(type(result), RegionalMechanicalSnapshot)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_failed_array_capture_remains_paid_until_traceback_release(self):
        budget = F.WorkBudget(256 << 20)
        scope = F.create_retained_scope(budget, process_epoch='transport-result-failure')
        held = None
        from unittest.mock import patch
        with LIVE.construction(scope, budget=budget), patch.object(RESULT, 'canonical',
                side_effect=RuntimeError('binding failure')):
            try:
                RESULT.make_snapshot({'test': True}, {'x': np.zeros(1000)}, budget, RegionalMechanicalSnapshot)
            except RuntimeError as error:
                held = error
        self.assertIsNotNone(held)
        self.assertGreater(budget.reserved_bytes, 5120+8000)
        del held
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 5120)
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_identity_seal_skips_only_the_record_stream(self):
        """Audit X2: one record stream per snapshot object in this process; bytes always rehashed."""
        from dataclasses import replace
        from unittest.mock import patch
        budget = F.WorkBudget(256 << 20)
        scope = F.create_retained_scope(budget, process_epoch='transport-result-seal')
        metadata = {'schema': 'atlas.spatial-implicit-transport.v1',
                    'exact_stocks': {'mass': [['0x1', '0x3']]}, 'cell_ids': ['a']}
        other = dict(metadata, cell_ids=['b'])
        arrays = {'stock:mass': np.array([1./3])}
        native = RegionalMechanicalSnapshot(metadata, arrays)
        with LIVE.construction(scope, budget=budget):
            compact = RESULT.make_snapshot(metadata, arrays, budget, RegionalMechanicalSnapshot)
            different = RESULT.make_snapshot(other, arrays, budget, RegionalMechanicalSnapshot)
        # The construction's own complete computation sealed the object.
        self.assertEqual(compact._verified[0], native.result_id)
        stream = type(compact._record).iter_json
        with patch.object(type(compact._record), 'iter_json', side_effect=AssertionError('second record stream')):
            self.assertEqual(RESULT.identity(compact, budget), native.result_id)
            with self.assertRaises(CancelledError):
                RESULT.identity(compact, budget, lambda: True)
            hashed, real = [], RESULT.sha256
            with patch.object(RESULT, 'sha256', side_effect=lambda *a: hashed.append(1) or real(*a)):
                RESULT.identity(compact, budget)
            self.assertTrue(hashed)            # field bytes are rehashed on every call
        # A copy never inherits the seal; another record never matches it.
        copy = replace(compact)
        self.assertIsNone(copy._verified)
        object.__setattr__(different, '_verified', compact._verified)
        for unsealed in (copy, different):
            with patch.object(type(compact._record), 'iter_json', side_effect=AssertionError('streamed')), \
                    self.assertRaisesRegex(AssertionError, 'streamed'):
                RESULT.identity(unsealed, budget)
        self.assertEqual(RESULT.identity(copy, budget), native.result_id)
        self.assertEqual(RESULT.identity(different, budget), RegionalMechanicalSnapshot(other, arrays).result_id)
        self.assertIs(type(compact._record).iter_json, stream)
        self.assertEqual(copy, compact)
        del compact, copy, different, unsealed
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
