"""Focused adapter parity and exact-array checks, no world generation."""
from copy import deepcopy
import json
import unittest

import numpy as np

from work.generator_upgrade_r26 import environment as e


class EnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = e.fixtures()
        shared = {}
        cls.adapters = {name: e.Adapter(name, cache=False, shared=shared)
                        for name in e.OPERATIONS}

    def test_actual_native_products_are_preserved(self):
        for operation, arguments in self.cases.items():
            with self.subTest(operation=operation):
                adapter = self.adapters[operation]
                native = adapter.native
                adapter.verify()
                if operation == 'climate_transect':
                    expected = native.generate([native.Cell(**row) for row in arguments['cells']],
                        native.AirMass(**arguments['atmosphere']), native.Controls(**arguments['controls']))
                elif operation == 'precipitation_phase':
                    supplied = deepcopy(arguments)
                    supplied['law'] = native.PhaseLaw(**supplied['law'])
                    raw = native.partition_precipitation(**supplied)
                    expected = adapter.r8.graph.load('work.generator_upgrade_r8.seasonal').plain(raw)
                    self.assertEqual(raw['rain_m_s']+raw['snowfall_m_s'], raw['precipitation_m_s'])
                elif operation == 'biome_cell':
                    expected = json.loads(json.dumps(native.classify_cell(**arguments), allow_nan=False))
                    self.assertEqual(expected['status'], 'MODELLED_POTENTIAL')
                elif operation == 'soil_heat_water':
                    expected = native.advance(**arguments)
                    self.assertEqual(expected['status'], 'MODELLED')
                    self.assertNotEqual(expected['initial_state'], expected['final_state'])
                    adapter.audit.event(arguments['model'], arguments['event'], expected, arguments['controls'])
                else:
                    config, arrays = native.build_resource(arguments['register'],
                        {key: e.unpack_array(value) for key, value in arguments['arrays'].items()},
                        shape=arguments['shape'])
                    expected = {'schema': 'diadem.native-resource-arrays.r26', 'config': config,
                        'products': {key: [e.pack_array(value) for value in values]
                                     for key, values in arrays.items()}}
                actual = adapter.run(arguments, {})
                self.assertEqual(actual, expected)
                json.dumps(actual, allow_nan=False)
                adapter.verify()

    def test_lossless_array_masks_empty_arrays_and_corruption(self):
        for array in (np.array([[0., -0., np.nan, np.inf]], dtype='>f4'),
                      np.array([], dtype=np.int64), np.empty((1, 0), dtype=np.float32)):
            packed = e.pack_array(array)
            restored = e.unpack_array(packed)
            self.assertEqual(array.dtype, restored.dtype)
            self.assertEqual(array.shape, restored.shape)
            self.assertEqual(array.tobytes(), restored.tobytes())
            broken = deepcopy(packed); broken['sha256'] = '0'*64
            with self.assertRaises(ValueError):
                e.unpack_array(broken)
        with self.assertRaises(ValueError):
            e.pack_array(np.array([object()], dtype=object))
        malformed = e.pack_array(np.ones((1,), dtype=np.float32))
        malformed['shape'] = [True]
        with self.assertRaises(ValueError):
            e.unpack_array(malformed)

    def test_unknown_physics_and_disjoint_inputs_preserved(self):
        adapter = self.adapters['soil_heat_water']
        arguments = deepcopy(self.cases['soil_heat_water'])
        arguments['model']['layers'][0]['source_status'] = 'UNKNOWN'
        result = adapter.run(arguments, {})
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertIsNone(result['final_state'])
        with self.assertRaises(ValueError):
            adapter.run(arguments, {'event': arguments['event']})
        phase = deepcopy(self.cases['precipitation_phase'])
        phase['source_status'] = 'UNKNOWN'
        self.assertEqual(self.adapters['precipitation_phase'].run(phase, {})['status'], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
