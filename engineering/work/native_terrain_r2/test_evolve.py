"""Five bounded R2 integration checks; no saved physical-case continuation."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from work.native_terrain_r1 import evolve as old, materials as m
from work.native_terrain_r1.test_evolve import connection
from . import evolve as e, migration as mig, numerics as n, provenance as p


def source(cell, index, fraction):
    return {'source_cell': cell, 'source_layer_index': index,
            'fraction_of_source_mass': fraction}


class CompositionTests(unittest.TestCase):
    def test_exact_quantum_margins_error_and_order_independence(self):
        lineage = {'a': [{'origin-1': 2 * n.Q, 'origin-2': 3 * n.Q}],
                   'b': [{'origin-1': n.Q, 'origin-3': 2 * n.Q}]}
        mapping = {'left': [[source('a', 0, F(2, 5)), source('b', 0, F(1, 3))]],
                   'right': [[source('a', 0, F(1, 5))]]}
        transfers = [source('a', 0, F(2, 5)), source('b', 0, F(2, 3))]
        exports = {'origin-1': 7 * n.Q}
        result, bound = e._compose(lineage, mapping, transfers, exports)
        self.assertEqual(sum(result['left'][0].values(), F()), 3 * n.Q)
        self.assertEqual(sum(result['right'][0].values(), F()), n.Q)
        self.assertEqual(sum(exports.values(), F()) - 7 * n.Q, 4 * n.Q)
        for origin, expected in {'origin-1': 10, 'origin-2': 3, 'origin-3': 2}.items():
            retained = sum((row.get(origin, F()) for rows in result.values() for row in rows), F())
            self.assertEqual(retained + exports.get(origin, F()), expected * n.Q)
        ideal = {
            'left': {'origin-1': F(17, 15) * n.Q, 'origin-2': F(6, 5) * n.Q,
                     'origin-3': F(2, 3) * n.Q},
            'right': {'origin-1': F(2, 5) * n.Q, 'origin-2': F(3, 5) * n.Q},
            'export': {'origin-1': (7 + F(22, 15)) * n.Q,
                       'origin-2': F(6, 5) * n.Q, 'origin-3': F(4, 3) * n.Q}}
        actual = {'left': result['left'][0], 'right': result['right'][0], 'export': exports}
        measured = sum((abs(actual[key].get(origin, F()) - amount)
                        for key, row in ideal.items() for origin, amount in row.items()), F())
        self.assertLessEqual(measured, n.mass(bound))
        self.assertNotIn('origin-3', result['right'][0])
        for row in actual.values():
            for amount in row.values():
                self.assertGreater(n.units(amount), 0)
        reversed_lineage = {key: [dict(reversed(list(row.items()))) for row in rows]
                            for key, rows in reversed(list(lineage.items()))}
        reversed_mapping = {key: [list(reversed(row)) for row in rows]
                            for key, rows in reversed(list(mapping.items()))}
        again_exports = {'origin-1': 7 * n.Q}
        again, again_bound = e._compose(reversed_lineage, reversed_mapping,
                                       list(reversed(transfers)), again_exports)
        self.assertEqual((again, again_bound, again_exports), (result, bound, exports))

    def test_later_invalid_source_does_not_partially_change_exports(self):
        lineage = {'a': [{'origin-a': n.Q}], 'b': [{'origin-b': n.Q}]}
        exports = {'previous-origin': n.Q}
        original = deepcopy(exports)
        # Source a is processed and entirely exported before the invalid b
        # account. A rejected composition must not leave that first debit.
        mapping = {'kept': [[source('b', 0, F(1, 2))]]}
        with self.assertRaises(ValueError):
            e._compose(lineage, mapping, [source('a', 0, F(1))], exports)
        self.assertEqual(exports, original)
        self.assertEqual(lineage, {'a': [{'origin-a': n.Q}], 'b': [{'origin-b': n.Q}]})


class ContinuingStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='native-r2-evolve-')
        cls.addClassCleanup(cls.directory.cleanup)
        predecessor, envelope, cls.acceptance = connection()
        state = old._native(envelope['body'])
        body = deepcopy(envelope['body'])
        index = len(state.column_map['a'].layers) - 1
        layer = state.column_map['a'].layers[index]
        origin = next(iter(body['lineage']['a'][index]))
        tiny = F(1, 10**435)
        donor = replace(state.column_map['a'], layers=(*state.column_map['a'].layers[:index],
                        replace(layer, mass_kg=layer.mass_kg - 2 * tiny)))
        destination = replace(state.column_map['b'], layers=(*state.column_map['b'].layers,
                              replace(layer, mass_kg=tiny)))
        state = replace(state, columns=tuple((key, donor if key == 'a' else
                        destination if key == 'b' else column) for key, column in state.columns))
        body.update(state=state.as_dict(), initial_state_sha256=p.sha(state.as_dict()))
        body['lineage']['a'][index][origin] = str(layer.mass_kg - 2 * tiny)
        body['lineage']['b'].append({origin: str(tiny)})
        body['exported_origin_mass_kg'][origin] = str(tiny)
        envelope = old._seal(body, envelope['binding'])
        path = Path(cls.directory.name) / 'predecessor.json'
        raw = p.encoded(envelope)
        path.write_bytes(raw)
        reference = {'checkpoint_path': str(path.resolve()),
                     'checkpoint_sha256': hashlib.sha256(raw).hexdigest(),
                     'body_sha256': envelope['body_sha256'], 'history_count': 0}
        cls.migrated, cls.migration_receipt = mig.migrate(envelope, predecessor,
                                                       predecessor_ref=reference)
        cls.executor = e.from_executor(predecessor)
        cls.migrated_snapshot = deepcopy(cls.migrated)
        cls.first = cls.executor.advance(cls.migrated, F(1), cls.acceptance,
                                        operation_id='successor-once')

    def test_tiny_migration_couples_with_exact_origins_once_only_time_and_reload(self):
        self.assertGreater(self.migration_receipt['numeric_l1_units'], 0)
        self.assertEqual(self.migrated, self.migrated_snapshot)
        body = e.validate(self.first)
        state = old._native(body)
        self.assertEqual(state.elapsed_years, F(1))
        self.assertEqual(body['parent'], self.migrated['body']['parent'])
        self.assertEqual(len(body['history']), 1)
        row = body['history'][0]
        self.assertEqual(row['parent_state_sha256'], p.sha(self.migrated['body']['state']))
        self.assertEqual(row['accepted_method'], 'TWO_HALF_STEPS_FULL_TRIAL_DISCARDED')
        self.assertEqual(sum((F(s['surface_runoff_m3']) for s in row['substeps']), F()), F(2, 5))
        self.assertEqual(F(body['surface_water_exported_m3']), F(2, 5))
        self.assertTrue(any(s['hillslope']['transfers'] for s in row['substeps']))
        self.assertTrue(any(F(balance['exported_mass_kg']) > 0 for s in row['substeps']
                            for balance in s['channel']['material_balances']))
        old._lineage_check(body, state)
        for _, column in state.columns:
            for layer in column.layers:
                self.assertLessEqual(n.units(layer.mass_kg).bit_length(), 256)
        for rows in body['lineage'].values():
            for atoms in rows:
                for amount in atoms.values():
                    self.assertGreater(n.units(F(amount)), 0)
        added = sum(s['numeric_compaction']['total_l1_units'] for s in row['substeps'])
        self.assertEqual(body['numeric_l1_units'], self.migration_receipt['numeric_l1_units'] + added)
        restored = json.loads(json.dumps(self.first, sort_keys=True, allow_nan=False))
        self.assertEqual(e.validate(restored), body)

    def test_rejection_duplicate_and_bad_source_leave_inputs_immutable(self):
        exact = replace(self.acceptance, max_surface_error_m=F(),
                        max_material_bulk_l1_error_m3=F(), max_halvings=0)
        with self.assertRaisesRegex(ValueError, 'refinement budget'):
            self.executor.advance(self.migrated, F(1), exact, operation_id='rejected')
        self.assertEqual(self.migrated, self.migrated_snapshot)
        accepted_snapshot = deepcopy(self.first)
        with self.assertRaisesRegex(ValueError, 'unique|replay'):
            self.executor.advance(self.first, F(1), self.acceptance, operation_id='successor-once')
        self.assertEqual(self.first, accepted_snapshot)
        malformed = deepcopy(self.first)
        malformed['binding']['sources']['evolve.py'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'binding|source'):
            self.executor.advance(malformed, F(1), self.acceptance, operation_id='bad-source')
        self.assertEqual(self.first, accepted_snapshot)

    def test_migration_counter_and_accepted_chain_tampering_are_rejected(self):
        forged = deepcopy(self.migrated['body'])
        forged['numeric_l1_units'] = 0
        forged['continuation_base']['numeric_l1_units'] = 0
        with self.assertRaises(ValueError):
            e.validate(e._seal(forged, self.migrated['binding']))
        forged = deepcopy(self.first['body'])
        forged['history'][0]['parent_state_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            e.validate(e._seal(forged, self.first['binding']))
        forged = deepcopy(self.first['body'])
        forged['history'][0]['substeps'][0]['numeric_compaction']['total_l1_units'] += 1
        with self.assertRaises(ValueError):
            e.validate(e._seal(forged, self.first['binding']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
