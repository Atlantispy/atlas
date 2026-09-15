"""Bounded native physical parity and warm-restoration boundary checks."""
from copy import deepcopy
from fractions import Fraction
import unittest

from work.generator_upgrade_r26 import physical as p


class PhysicalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = p.fixtures()

    def test_all_native_paths_keep_exact_products_and_scope(self):
        self.assertEqual(set(self.inputs), set(p.OPERATIONS))
        results = {}
        for operation, inputs in self.inputs.items():
            with self.subTest(operation=operation):
                untouched = deepcopy(inputs)
                expected = p.baseline(operation, inputs)
                adapter = p.Adapter(operation)
                actual = adapter.run(inputs, {})
                adapter.validate_result(actual, inputs, {})
                adapter.verify()
                self.assertEqual(actual, expected)
                self.assertEqual(inputs, untouched)
                results[operation] = actual
        self.assertFalse(results['tectonic_snapshot']['validation']['category_complete'])
        self.assertFalse(results['regional_geology']['scientific']['production_authorised'])
        hazard = results['soil_stability']['cells'][0]
        self.assertEqual(hazard['mask'], 'VALID')
        route = results['surface_water_route']
        self.assertEqual(sum(map(Fraction, route['local_runoff_m3'].values())),
                         sum(map(Fraction, route['external_exports_m3'].values())))

    def test_warm_restore_rechecks_external_pins_and_parent_identity(self):
        inputs = deepcopy(self.inputs['tectonic_snapshot'])
        adapter = p.Adapter('tectonic_snapshot')
        result = adapter.run(inputs, {})
        name = next(iter(inputs['package_pins']))
        inputs['package_pins'][name] = '0'*64
        with self.assertRaisesRegex(ValueError, 'changed'):
            adapter.validate_result(result, inputs, {})
        inputs = deepcopy(self.inputs['geological_columns'])
        adapter = p.Adapter('geological_columns')
        result = adapter.run(inputs, {})
        inputs['packet']['source_package']['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'changed'):
            adapter.validate_result(result, inputs, {})
        inputs = deepcopy(self.inputs['geological_incise'])
        snapshot = inputs.pop('snapshot')
        adapter = p.Adapter('geological_incise')
        linked = adapter.run(inputs, {'geology': snapshot})
        self.assertEqual(linked, p.baseline('geological_incise', self.inputs['geological_incise']))
        linked['r18_input_scientific_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'parent identity'):
            adapter.validate_result(linked, inputs, {'geology': snapshot})

    def test_unknown_hazard_and_unsupported_water_are_not_filled(self):
        inputs = deepcopy(self.inputs['soil_stability'])
        quantity = inputs['cells'][0][0]['pore_pressure_pa']
        quantity.update(lower=None, upper=None, source_status='UNKNOWN')
        result = p.Adapter('soil_stability').run(inputs, {})
        self.assertEqual(result['cells'][0]['mask'], 'UNKNOWN')
        water = deepcopy(self.inputs['surface_water_route'])
        water['connectors'] = []
        with self.assertRaises(ValueError):
            p.Adapter('surface_water_route').run(water, {})


if __name__ == '__main__':
    unittest.main()
