"""Focused native Q-channel tests; synthetic fixtures, no example evolution."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import unittest

from work.geology_r1 import native as g1
from work.native_terrain_r1.domain import Domain, channel_layer_sources
from work.terrain_model_r7.hillslope_kernel import Grid
from . import channel, numerics as n

EVIDENCE = 'R2 Q-channel independent synthetic regression'


def fixture(cells=2, coefficient=F(1, 1024), settling=F(), thin=False):
    tt = g1.ground_gate.backend()[1]
    grid = Grid(2, cells, 1, 1)
    ids = tuple('c'+str(i) for i in range(grid.size))
    columns, edges = [], []
    for i, key in enumerate(ids):
        row, col = divmod(i, cells)
        layers = (tt.Layer('rock', 10, 10, 0, 'bedrock', EVIDENCE),
                  tt.Layer('lower', 8, 8, F(1, 4), 'mobile_sediment', EVIDENCE),
                  tt.Layer('upper', 16, 8, 0, 'mobile_sediment', EVIDENCE))
        if thin:
            layers += (replace(layers[-2], mass_kg=3*n.Q, evidence=EVIDENCE+' distinct thin source'),)
        columns.append((key, tt.Column(1, 100+cells-col, layers, 'SYNTHETIC TEST')))
        for dr, dc in ((-1, 0), (0, -1), (0, 1), (1, 0)):
            rr, cc = row+dr, col+dc
            if 0 <= rr < 2 and 0 <= cc < cells:
                other = ids[rr*cells+cc]
                edges.append(tt.Connector(key+'->'+other, key, other, 1, None, EVIDENCE))
        if col == cells-1:
            edges.append(tt.Connector('outlet'+str(row), key, None, 1, 0, EVIDENCE))
    def prop(name, value, unit):
        return tt.PhysicalProperty(name, value, unit, EVIDENCE, 'SYNTHETIC TEST')
    laws = tuple(tt.ErosionLaw(material, phase,
        prop('erosion_coefficient_at_reference_runoff', k, '1/year'),
        prop('reference_runoff', 1, 'm/year')) for material, phase, k in (
            ('rock', 'bedrock', F()), ('rock', 'mobile_sediment', F()),
            ('lower', 'mobile_sediment', coefficient), ('upper', 'mobile_sediment', coefficient)))
    sediment = tuple(tt.SedimentLaw(material, settling, F(1, 4), index, EVIDENCE)
                     for index, material in enumerate(('rock', 'lower', 'upper')))
    controls = tt.TrialControls(F(1, 2), F(1, 2), EVIDENCE)
    return Domain(grid, ids, tuple(edges)), tt.LandscapeState(tuple(columns)), {
        key: F(1) for key in ids}, laws, sediment, controls


def invoke(data, state=None):
    domain, original, runoff, laws, sediment, controls = data
    return channel.trial(domain, original if state is None else state, runoff, 1,
                         laws, sediment, controls, evidence_id=EVIDENCE)


class ChannelTests(unittest.TestCase):
    def assert_quantum_and_closure(self, before, result):
        tt = g1.ground_gate.backend()[1]
        self.assertIs(type(result), tt.TerrainTrial)
        mapping = channel_layer_sources(before, result)
        for key, column in result.state.columns:
            self.assertEqual(len(mapping[key]), len(column.layers))
            for layer in column.layers:
                self.assertLessEqual(n.units(layer.mass_kg).bit_length(), 256)
                self.assertLessEqual(layer.mass_kg.denominator.bit_length(), 65)
        for event in result.erosion_events:
            n.units(event['eroded_mass_kg'])
            n.units(event['remaining_mass_kg'])
        for event in result.deposit_events:
            n.units(event['mass_kg'])
            for source in event['sources']:
                n.units(source['mass_kg'])
        for event in result.exports:
            n.units(event['mass_kg'])
        for row in result.receipt['material_balances']:
            self.assertEqual(row['mass_residual_kg'], 0)
            self.assertEqual(row['solid_residual_m3'], 0)
        self.assertEqual(result.receipt['water_residual_m3'], 0)
        error = result.receipt['numeric_compaction']
        self.assertEqual(error['total_l1_units'], error['erosion_rounding_l1_units']+error['packet_split_l1_units'])
        self.assertEqual(error['total_l1_units'], sum(error['by_material_l1_units'].values()))
        self.assertEqual(error['total_l1_bound_kg'], n.mass(error['total_l1_units']))
        for row in error['erosion_rounding']:
            actual = row['proposed_mass_kg']-row['applied_mass_kg']
            self.assertGreaterEqual(actual, 0)
            self.assertLess(actual, n.Q)
            self.assertLessEqual(2*actual, n.mass(row['paired_l1_units']))
        for row in result.receipt['sediment_transfers']:
            self.assertEqual(row['incoming_kg'], row['deposited_kg']+row['outgoing_kg'])
            actual = row['proposed_outgoing_kg']-row['outgoing_kg']
            self.assertGreaterEqual(actual, 0)
            self.assertLess(actual, n.Q)
            self.assertLessEqual(2*actual, n.mass(row['compaction_paired_l1_units']))

    def test_quantum_exact_native_state_and_events_parity(self):
        data = fixture()
        domain, state, runoff, laws, sediment, controls = data
        expected = domain.trial(state, runoff, 1, laws, sediment, controls, evidence_id=EVIDENCE)
        actual = invoke(data)
        self.assertEqual(actual.state, expected.state)
        self.assertEqual(actual.erosion_state, expected.erosion_state)
        self.assertEqual(actual.erosion_events, expected.erosion_events)
        self.assertEqual(actual.deposit_events, expected.deposit_events)
        self.assertEqual(actual.exports, expected.exports)
        self.assertEqual(actual.receipt['actual_R14_erosion_receipt'], expected.receipt['actual_R14_erosion_receipt'])
        self.assertEqual(actual.receipt['numeric_compaction']['total_l1_units'], 0)
        for field in ('water_routing', 'material_balances', 'relief_checks', 'water_exports_m3'):
            self.assertEqual(actual.receipt[field], expected.receipt[field])
        self.assert_quantum_and_closure(state, actual)

    def test_mixed_packets_round_down_and_keep_exact_complements(self):
        data = fixture(2, settling=F(1))
        result = invoke(data)
        self.assertTrue(result.deposit_events)
        self.assertGreater(result.receipt['numeric_compaction']['packet_split_l1_units'], 0)
        self.assert_quantum_and_closure(data[1], result)

    def test_tiny_partial_zero_applied_retains_all_stock(self):
        data = fixture(coefficient=F(1, 2**100))
        result = invoke(data)
        self.assertFalse(result.erosion_events)
        self.assertFalse(result.exports)
        self.assertEqual([c.layers for _, c in result.state.columns], [c.layers for _, c in data[1].columns])
        self.assertEqual(result.state.elapsed_years, 1)
        rows = result.receipt['numeric_compaction']['erosion_rounding']
        self.assertTrue(rows)
        self.assertTrue(all(row['applied_mass_kg'] == 0 and row['paired_l1_units'] == 2 for row in rows))
        self.assert_quantum_and_closure(data[1], result)

    def test_full_contact_keeps_input_index_and_exact_stock(self):
        data = fixture(thin=True, settling=F(1))
        result = invoke(data)
        event = result.erosion_events[0]
        self.assertEqual((event['source_layer_index'], event['eroded_mass_kg'], event['remaining_mass_kg']), (3, 3*n.Q, 0))
        record = result.receipt['numeric_compaction']['erosion_rounding'][0]
        self.assertEqual(record['contact_kind'], 'FULL_CONTACT_EXACT_APPLIED_STOCK')
        self.assertEqual(record['paired_l1_units'], 0)
        self.assertEqual(result.erosion_events[1]['source_layer_index'], 2)
        self.assertEqual({row['material_id'] for row in result.deposit_events}, {'lower', 'upper'})
        self.assert_quantum_and_closure(data[1], result)

    def test_zero_erosion_and_empty_compaction_error(self):
        data = fixture(2, coefficient=F())
        result = invoke(data)
        self.assertFalse(result.erosion_events)
        self.assertEqual(result.receipt['numeric_compaction']['total_l1_units'], 0)
        self.assert_quantum_and_closure(data[1], result)

    def test_80_repeated_channel_passes_keep_mass_bits_bounded(self):
        data = fixture(2, coefficient=F(1, 2**20), settling=F(1))
        state = data[1]
        initial = sum((column.mass_kg for _, column in state.columns), F())
        exported = F()
        for _ in range(80):
            result = invoke(data, state)
            self.assert_quantum_and_closure(state, result)
            exported += sum((row['mass_kg'] for row in result.exports), F())
            n.units(exported)
            state = result.state
        self.assertEqual(state.elapsed_years, 80)
        self.assertEqual(initial, sum((column.mass_kg for _, column in state.columns), F())+exported)
        self.assertEqual(g1.ground_gate.backend()[1].MAX_BITS, 8192)

    def test_nonquantum_input_and_invalid_error_ledger_refused(self):
        data = fixture()
        key, column = data[1].columns[0]
        changed = replace(data[1], columns=((key, replace(column,
            layers=(*column.layers[:-1], replace(column.layers[-1], mass_kg=F(1, 3))))), *data[1].columns[1:]))
        with self.assertRaises(ValueError):
            invoke(data, changed)
        with self.assertRaises(ValueError):
            channel._floor_pair(-n.Q)
        error = deepcopy(invoke(data).receipt['numeric_compaction'])
        error['erosion_rounding_l1_units'] += 1
        with self.assertRaises(ArithmeticError):
            channel._finish_compaction(error)
        with self.assertRaises(ValueError):
            channel._floor_pair(n.mass(2**255)*3)


if __name__ == '__main__':
    unittest.main()
