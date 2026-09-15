"""Focused heterogeneous finite-column bridge checks; no world fixture runs."""
from dataclasses import replace
from fractions import Fraction as F
import unittest

from work.geology_r1 import composite
from work.native_terrain_r1 import materials as m
from work.terrain_model_r7.hillslope_kernel import Grid


def descriptor(name, density, porosity, phase, mixed=False):
    parts = [{'unit_id': name, 'bulk_weight': '1',
              'grain_density_kg_m3': str(density), 'porosity': str(porosity)}]
    if mixed:
        parts[0]['bulk_weight'] = '1/2'
        parts.append({'unit_id': name + '-second', 'bulk_weight': '1/2',
                      'grain_density_kg_m3': str(density * 2), 'porosity': str(porosity)})
    return composite.create(parts, '0', phase=phase, evidence='Synthetic bridge verification')


def fixture():
    tt = m.native()
    descriptors = [descriptor('rock', 2800, 0, 'bedrock'),
                   descriptor('weathered', 2500, F(1, 4), 'immobile_regolith'),
                   descriptor('soil-a', 2000, F(1, 2), 'mobile_sediment', True),
                   descriptor('soil-b', 2700, F(1, 3), 'mobile_sediment')]
    palette = {d['material_id']: d for d in descriptors}
    def layer(i, bulk):
        d = descriptors[i]
        rho, porosity = F(d['grain_density_kg_m3']), F(d['porosity'])
        return tt.Layer(d['material_id'], F(bulk) * rho * (1 - porosity), rho,
                        porosity, d['phase'], d['evidence'])
    columns = tuple((key, tt.Column(F(1), F(), (
        (layer(0, 3), layer(1, 1), layer(2, 2), layer(3, 1))
        if key == 'a' else (layer(0, 1),)), 'SYNTHETIC TEST')) for key in 'abcd')
    state = tt.LandscapeState(columns)
    packing = {d['material_id']: F(d['porosity']) for d in descriptors if d['phase'] == 'mobile_sediment'}
    return state, palette, packing, layer


def face(identity, donor, receiver, volume):
    return {'id': identity, 'donor': donor, 'receiver': receiver,
            'requested_bulk_m3': volume, 'boundary_id': 'explicit-test-toe' if receiver is None else None}


def controls(quantum=F(1, 2**40), budget=F(1, 10**8)):
    return m.AllocationControls(quantum, budget, 'SOURCE_CELL_LAYER_FACE_ASCENDING',
                                'Frozen test allocation budget, not PDE accuracy')


def apply(state, palette, packing, faces, c=None):
    return m.apply(state, tuple('abcd'), faces, palette, packing, c or controls(),
                   operation_id='test-1', start_year=state.elapsed_years,
                   duration_years=F(1), evidence='Synthetic finite-layer trial')


class FiniteBridgeTests(unittest.TestCase):
    def test_mixed_layers_proportional_exhaustion_and_order_independence(self):
        state, palette, packing, _ = fixture()
        requests = [face('b', 0, 1, 6), face('c', 0, 2, 3)]
        result = apply(state, palette, packing, requests)
        reverse = apply(state, palette, packing, list(reversed(requests)))
        self.assertEqual(result.state.as_dict(), reverse.state.as_dict())
        self.assertEqual(result.receipt, reverse.receipt)
        self.assertEqual(result.state.column_map['a'].layers, state.column_map['a'].layers[:2])
        events = result.receipt['transfers']
        self.assertEqual({e['source_layer_index'] for e in events}, {2, 3})
        for index in (2, 3):
            moved = [e for e in events if e['source_layer_index'] == index]
            self.assertEqual(sum((e['mass_kg'] for e in moved), F()), state.column_map['a'].layers[index].mass_kg)
            self.assertEqual(moved[0]['mass_kg'], 2 * moved[1]['mass_kg'])
        self.assertTrue(result.receipt['exact_source_layer_closure'])
        self.assertEqual(result.state.elapsed_years, state.elapsed_years)
        self.assertEqual(len(events[2]['constituents']), 2)

    def test_partial_leaves_exact_residual_and_does_not_touch_buried_layers(self):
        state, palette, packing, _ = fixture()
        result = apply(state, palette, packing, [face('partial', 0, 1, F(1, 7))])
        before, after = state.column_map['a'], result.state.column_map['a']
        self.assertEqual(before.layers[:-1], after.layers[:-1])
        self.assertGreater(after.layers[-1].mass_kg, 0)
        self.assertGreaterEqual(result.receipt['total_bulk_allocation_error_m3'], 0)

    def test_immobile_cap_and_bare_are_not_mobilised(self):
        state, palette, packing, layer = fixture()
        col = state.column_map['a']
        cap = replace(col, layers=(*col.layers, layer(1, F(1, 10))))
        capped = replace(state, columns=tuple((k, cap if k == 'a' else c) for k, c in state.columns))
        result = apply(capped, palette, packing, [face('cap', 0, 1, 100), face('bare', 2, 3, 100)])
        self.assertEqual(result.state.as_dict(), capped.as_dict())
        self.assertEqual(result.receipt['transfers'], [])

    def test_sub_quantum_stock_is_retained_or_exactly_exhausted_never_deleted(self):
        state, palette, packing, layer = fixture()
        col = state.column_map['a']
        thin = replace(layer(2, 1), mass_kg=F(1, 2**70))
        state = replace(state, columns=tuple((k, replace(col, layers=(col.layers[0], thin)) if k == 'a' else c)
                                            for k, c in state.columns))
        requests = [face('one', 0, 1, 1), face('two', 0, 2, 1)]
        result = apply(state, palette, packing, requests)
        self.assertEqual(len(result.state.column_map['a'].layers), 1)
        self.assertEqual(sum((e['mass_kg'] for e in result.receipt['transfers']), F()), thin.mass_kg)
        self.assertGreater(result.receipt['total_bulk_allocation_error_m3'], 0)

    def test_export_and_repacking_preserve_mass_solid_and_constituents(self):
        state, palette, packing, _ = fixture()
        packing = {key: F(3, 4) for key in packing}
        result = apply(state, palette, packing, [face('out', 0, None, 1), face('in', 0, 1, 1)])
        self.assertTrue(any(row['exported_mass_kg'] > 0 for row in result.receipt['global_material_balance']))
        self.assertEqual(result.state.column_map['b'].exposed.porosity, F(3, 4))
        restored = m.native().LandscapeState.from_dict(result.state.as_dict())
        self.assertEqual(restored.as_dict(), result.state.as_dict())

    def test_budget_and_invalid_faces_reject_atomically(self):
        state, palette, packing, _ = fixture()
        before = state.as_dict()
        with self.assertRaisesRegex(ValueError, 'budget'):
            apply(state, palette, packing, [face('one', 0, 1, F(1, 7))], controls(F(1), F()))
        with self.assertRaisesRegex(ValueError, 'unique'):
            apply(state, palette, packing, [face('same', 0, 1, 1), face('same', 0, 2, 1)])
        with self.assertRaisesRegex(ValueError, 'boundary'):
            apply(state, palette, packing, [{**face('out', 0, None, 1), 'boundary_id': None}])
        self.assertEqual(state.as_dict(), before)

    def test_derived_view_checks_support_and_packing_expansion(self):
        state, palette, packing, _ = fixture()
        packing = {key: F(3, 4) for key in packing}
        view = m.hillside_view(state, tuple('abcd'), Grid(2, 2, 1, 1), palette, packing)
        self.assertEqual(view['available_bulk_m3'], [3., 0., 0., 0.])
        self.assertGreaterEqual(view['receiving_expansion_max'], 8 / 3)
        with self.assertRaisesRegex(ValueError, 'area'):
            m.hillside_view(state, tuple('abcd'), Grid(2, 2, 2, 1), palette, packing)


if __name__ == '__main__':
    unittest.main()
