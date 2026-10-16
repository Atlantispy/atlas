"""W3 Decision 5: CompactHeatSnapshot.from_components accepts zero-size fields as r12 does.

r12 (RegionalMechanicalSnapshot) accepts a zero-size binary64 field of any
shape, hashing it as sha256(b''). The base from_components raised TypeError
from memoryview.cast for a shape with a zero after its first axis. The fix
owns b'' for zero-size fields; every other field takes the unchanged route.
Round trip: result_id equals r12, field bytes and shapes are exact, and the
r4 store save/open reproduces the identity and arrays.
"""
import gc
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[4]
sys.path[:0] = [str(HERE.parents[1]/'runtime-integration-r1'/'runtime-src'), str(HERE.parent), str(HERE)]
import private_heat_snapshot_store_r4 as S
import w3ref_heat_ledger_tables as BASE
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.resources import WorkBudget
from compact_contracts import ContractError
from content_cache import create_retained_scope
from heat_ledger_tables import CompactHeatSnapshot
from interval_store_set import IntervalStoreSet

META = {'cell_ids': ['d'*64], 'face_ids': ['e'*64], 'q': ['0x2', '0x4'], 'rows': [1, 2]}
SHAPES = [(3, 0), (0,), (0, 0, 2), (1, 0, 5), (0, 4)]


class ZeroSizeFieldTests(unittest.TestCase):
    def test_zero_size_shapes_match_r12_and_round_trip(self):
        for shape in SHAPES:
            fields = {'a': np.array([-0., 1., 5e-324]), 'z': np.zeros(shape)}
            with self.subTest(shape=shape):
                legacy = RegionalMechanicalSnapshot(META, fields)
                budget = WorkBudget(1 << 30)
                scope = create_retained_scope(budget, process_epoch='w3-zero-size')
                new = CompactHeatSnapshot.from_components(META, fields, scope=scope)
                self.assertEqual(new.result_id, legacy.result_id)
                for name in fields:
                    self.assertEqual(new.array(name).shape, legacy.array(name).shape)
                    self.assertEqual(new.array(name).dtype, np.float64)
                    self.assertEqual(new.array(name).tobytes(), legacy.array(name).tobytes())
                if shape[0] == 0 and len(shape) == 1:
                    # Shapes the base already accepted: unchanged identity and bytes.
                    base = BASE.CompactHeatSnapshot.from_components(META, fields, scope=scope)
                    self.assertEqual(base.result_id, new.result_id)
                    self.assertEqual(base.metadata_identity, new.metadata_identity)
                    base.close()
                    del base
                else:
                    with self.assertRaises(TypeError):
                        BASE.CompactHeatSnapshot.from_components(META, fields, scope=scope)
                self.round_trip(new, fields, scope)
                new.close()
                del new
                gc.collect()
                scope.close()
                self.assertEqual(budget.reserved_bytes, 0)

    def round_trip(self, snapshot, fields, scope):
        (TASK/'_t').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='w3-zero-', dir=TASK/'_t') as temp:
            stores = IntervalStoreSet.create_migration(Path(temp)/'catalog.json', workflow_id='a'*64, scope=scope)
            candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
            bindings = {'source': 'f'*64, 'call': '1'*64}
            receipt = S.save(candidate, snapshot, bindings=bindings, scope=scope)
            with S.open(candidate, receipt, expected_result_id=snapshot.result_id,
                        bindings=bindings, scope=scope) as result:
                restored = result.value
                self.assertEqual(restored.result_id, snapshot.result_id)
                self.assertEqual(restored.nbytes, snapshot.nbytes)
                for name in fields:
                    self.assertEqual(restored.array(name).shape, fields[name].shape)
                    self.assertEqual(restored.array(name).tobytes(), fields[name].tobytes())
                restored.close()
            del restored, result
            candidate.close()
            stores.close()
            gc.collect()

    def test_nonfinite_and_nonnative_still_refused(self):
        from atlas_tectonics._validation import TectonicsError
        budget = WorkBudget(1 << 30)
        scope = create_retained_scope(budget, process_epoch='w3-zero-size-refusal')
        with self.assertRaises(TectonicsError):
            CompactHeatSnapshot.from_components(META, {'a': np.array([np.nan]), 'z': np.zeros((3, 0))}, scope=scope)
        for bad in (np.zeros((3, 0), dtype=np.float32), np.zeros((0, 3)).T, np.zeros((3, 0), dtype=np.int64)):
            with self.subTest(dtype=bad.dtype, contiguous=bad.flags.c_contiguous):
                if bad.dtype == np.float64 and bad.size == 0:
                    # numpy reports every zero-size array as C-contiguous; r12 accepts it too.
                    snap = CompactHeatSnapshot.from_components(META, {'z': bad}, scope=scope)
                    self.assertEqual(snap.result_id, RegionalMechanicalSnapshot(META, {'z': bad}).result_id)
                    snap.close()
                    del snap
                    continue
                with self.assertRaisesRegex(ContractError, 'bounded contiguous native binary64 arrays required'):
                    CompactHeatSnapshot.from_components(META, {'z': bad}, scope=scope)
        gc.collect()
        scope.close()
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
