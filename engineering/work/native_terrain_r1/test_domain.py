"""Focused common-domain/ancestry checks; explicit synthetic parameters only."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction as F
import unittest

from work.geology_r1 import native as g1
from work.terrain_model_r7.hillslope_kernel import Grid
from work.topography_r1 import kernels
from .domain import Domain, DEFAULT_EVIDENCE, channel_layer_sources

EVIDENCE = 'native common-domain synthetic regression'


def fixture(rows=2, cols=2, erosion=F(1, 2**24)):
    tt = g1.ground_gate.backend()[1]
    grid = Grid(rows, cols, 2, 3)
    ids = tuple(f'c{i:03}' for i in range(grid.size))
    columns, edges = [], []
    for i, key in enumerate(ids):
        row, col = divmod(i, cols)
        # A finite rock support and porous mobile cover; all routes reach toe.
        layers = (tt.Layer('rock', 9000, 3000, F(1, 4), 'bedrock', EVIDENCE),
                  tt.Layer('silt', 3000, 2500, F(2, 5), 'mobile_sediment', EVIDENCE))
        columns.append((key, tt.Column(6, 100 + (rows-row)*10 + (cols-col)*10,
                                       layers, 'SYNTHETIC TEST')))
        for dr, dc in ((-1, 0), (0, -1), (0, 1), (1, 0)):
            rr, cc = row+dr, col+dc
            if 0 <= rr < rows and 0 <= cc < cols:
                other = ids[rr*cols+cc]
                edges.append(tt.Connector(key+'-'+other, key, other,
                                          3 if dr else 2, None, EVIDENCE))
    edges.append(tt.Connector('toe', ids[-1], None, 1, 0, EVIDENCE))
    def prop(name, value, unit):
        return tt.PhysicalProperty(name, value, unit, EVIDENCE, 'SYNTHETIC TEST')
    laws = tuple(tt.ErosionLaw(material, phase,
        prop('erosion_coefficient_at_reference_runoff', coefficient, '1/year'),
        prop('reference_runoff', 1, 'm/year'))
        for material, phase, coefficient in (('rock', 'bedrock', F()),
            ('rock', 'mobile_sediment', F()), ('silt', 'mobile_sediment', erosion)))
    sediment = (tt.SedimentLaw('rock', 1, F(1, 4), 0, EVIDENCE),
                tt.SedimentLaw('silt', 1, F(2, 5), 1, EVIDENCE))
    return (grid, ids, tuple(edges), tt.LandscapeState(tuple(columns)),
            {key: F(1) for key in ids}, laws, sediment,
            tt.TrialControls(F(1, 2), F(1, 5), EVIDENCE))


class DomainTests(unittest.TestCase):
    def test_small_exact_route_and_full_trial_receipt_parity(self):
        grid, ids, edges, state, runoff, laws, sediment, controls = fixture(4, 4)
        domain = Domain(grid, ids, edges)
        self.assertEqual(domain.route(state, runoff, F(1)),
            kernels.route_water(state, runoff, edges, duration_years=F(1)))
        expected = kernels.trial(state, runoff, edges, laws, sediment,
            duration_years=F(1), controls=controls, evidence_id=DEFAULT_EVIDENCE)
        actual = domain.trial(state, runoff, F(1), laws, sediment, controls)
        self.assertEqual(actual, expected)
        mapping = channel_layer_sources(state, actual)
        self.assertEqual(set(mapping), set(ids))
        self.assertTrue(actual.deposit_events)

    def test_full_256_cell_zero_erosion_and_unchanged_native_limits(self):
        grid, ids, edges, state, runoff, laws, sediment, controls = fixture(16, 16, F())
        tt = g1.ground_gate.backend()[1]
        domain = Domain(grid, ids, edges)
        flow = domain.route(state, runoff, 1)
        self.assertEqual(flow['external_exports_m3'], {'toe': F(256)})
        trial = domain.trial(state, runoff, 1, laws, sediment, controls)
        for key, column in trial.state.columns:
            self.assertEqual(column.layers, state.column_map[key].layers)
            self.assertEqual(column.source_status, 'WORKING NON-CANON')
        self.assertTrue(all(row['mass_residual_kg'] == row['solid_residual_m3'] == 0
                            for row in trial.receipt['material_balances']))
        self.assertEqual((tt.MAX_CELLS, tt.MAX_CONNECTORS, tt.MAX_LAYERS, tt.MAX_BITS),
                         (32, 256, 2048, 8192))
        with self.assertRaises(tt.TerrainContractError):
            kernels.route_water(state, runoff, edges, duration_years=1)
        self.assertEqual(len(channel_layer_sources(state, trial)), 256)

    def test_above32_low_erosion_conserves_all_material_and_lineage(self):
        grid, ids, edges, state, runoff, laws, sediment, controls = fixture(6, 6)
        trial = Domain(grid, ids, edges).trial(state, runoff, 1, laws, sediment, controls)
        mapping = channel_layer_sources(state, trial)
        self.assertTrue(trial.erosion_events)
        self.assertTrue(trial.deposit_events)
        self.assertEqual(trial.receipt['water_exports_m3'], {'toe': F(36)})
        for key, column in trial.state.columns:
            for layer, sources in zip(column.layers, mapping[key], strict=True):
                mass = sum((state.column_map[s['source_cell']].layers[s['source_layer_index']].mass_kg
                            * s['fraction_of_source_mass'] for s in sources), F())
                self.assertEqual(mass, layer.mass_kg)

    def test_missing_internal_connector_and_bad_lengths_rejected(self):
        grid, ids, edges, *_ = fixture()
        with self.assertRaisesRegex(ValueError, 'complete directed D4'):
            Domain(grid, ids, edges[1:])
        with self.assertRaisesRegex(ValueError, 'exact D4'):
            Domain(grid, ids, (replace(edges[0], length_m=9), *edges[1:]))

    def test_interior_fake_outlet_rejected(self):
        grid, ids, edges, *_ = fixture(3, 3)
        tt = g1.ground_gate.backend()[1]
        fake = tt.Connector('fake', ids[4], None, 1, 0, EVIDENCE)
        with self.assertRaisesRegex(ValueError, 'perimeter'):
            Domain(grid, ids, (*edges, fake))

    def test_support_mismatch_and_area_mismatch_rejected(self):
        grid, ids, edges, state, runoff, *_ = fixture()
        domain = Domain(grid, ids, edges)
        changed = replace(state, columns=(('other', state.columns[0][1]), *state.columns[1:]))
        with self.assertRaisesRegex(ValueError, 'whole native state'):
            domain.route(changed, runoff, 1)
        changed = replace(state, columns=((ids[0], replace(state.columns[0][1], area_m2=7)), *state.columns[1:]))
        with self.assertRaisesRegex(ValueError, 'support area'):
            domain.route(changed, runoff, 1)

    def test_connector_inputs_detached_and_domain_frozen(self):
        grid, ids, edges, *_ = fixture()
        supplied = list(edges)
        domain = Domain(grid, list(ids), supplied)
        supplied.clear()
        self.assertEqual(domain.connectors, edges)
        with self.assertRaises(FrozenInstanceError):
            domain.connectors = ()

    def test_no_implicit_outlets_and_boolean_runoff_rejected(self):
        grid, ids, edges, state, runoff, *_ = fixture()
        tt = g1.ground_gate.backend()[1]
        domain = Domain(grid, ids, edges[:-1])
        with self.assertRaises(tt.TerrainRegimeError):
            domain.route(state, runoff, 1)
        with self.assertRaises(tt.TerrainContractError):
            Domain(grid, ids, edges).route(state, dict(runoff, **{ids[0]: True}), 1)

    def test_lineage_rejects_tampered_event_and_missing_export(self):
        grid, ids, edges, state, runoff, laws, sediment, controls = fixture()
        trial = Domain(grid, ids, edges).trial(state, runoff, 1, laws, sediment, controls)
        changed = deepcopy(trial)
        changed.deposit_events[0]['sources'][0]['fraction_of_eroded_mass'] = F(1)
        with self.assertRaisesRegex(ValueError, 'deposit source material/fraction'):
            channel_layer_sources(state, changed)
        with self.assertRaisesRegex(ValueError, 'does not close exactly'):
            channel_layer_sources(state, replace(trial, exports=()))

    def test_layer_and_cell_envelopes_are_independent_and_unchanged(self):
        grid, ids, edges, state, runoff, *_ = fixture(16, 16)
        tt = g1.ground_gate.backend()[1]
        excessive = replace(state, columns=tuple((key, replace(column,
            layers=tuple(column.layers[0] for _ in range(9)))) for key, column in state.columns))
        with self.assertRaisesRegex(ValueError, '2048 total native layer'):
            Domain(grid, ids, edges).route(excessive, runoff, 1)
        with self.assertRaisesRegex(ValueError, 'at most 256'):
            Domain(Grid(2, 129, 1, 1), tuple(f'c{i}' for i in range(258)), ())
        self.assertEqual(tt.landscape.MAX_TOTAL_LAYERS, 16384)

    def test_lineage_retains_indices_through_complete_surface_contact(self):
        grid, ids, edges, state, runoff, laws, sediment, controls = fixture()
        key, column = state.columns[0]
        thin = replace(column.layers[-1], mass_kg=F(1, 2**20), evidence='distinct thin source')
        state = replace(state, columns=((key, column.deposit(thin)), *state.columns[1:]))
        trial = Domain(grid, ids, edges).trial(state, runoff, 1, laws, sediment, controls)
        events = [event for event in trial.erosion_events if event['source_cell'] == key]
        self.assertEqual([event['source_layer_index'] for event in events], [2, 1])
        self.assertEqual(events[0]['remaining_mass_kg'], 0)
        self.assertGreater(events[1]['remaining_mass_kg'], 0)
        mapping = channel_layer_sources(state, trial)
        self.assertEqual(mapping[key][1][0]['source_layer_index'], 1)
        contributing_indices = {source['source_layer_index'] for rows in mapping.values()
            for origins in rows for source in origins if source['source_cell'] == key}
        self.assertEqual(contributing_indices, {0, 1, 2})


if __name__ == '__main__':
    unittest.main()
