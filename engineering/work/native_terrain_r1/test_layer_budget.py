"""Focused layer-guard successor checks; no analytical or physical reruns."""
from dataclasses import replace
from fractions import Fraction as F
import importlib.util
from pathlib import Path
import unittest

from work.native_terrain_r1 import materials as m
from work.native_terrain_r1.domain import Domain, DEFAULT_EVIDENCE, channel_layer_sources
from work.native_terrain_r1.test_domain import fixture as domain_fixture
from work.native_terrain_r1.test_materials import fixture as material_fixture, controls
from work.topography_r1 import kernels


EVIDENCE = 'SYNTHETIC bounded layer-envelope successor regression'


def layered_fixture(layers_per_cell=65):
    grid, ids, edges, base, runoff, _, _, trial_controls = domain_fixture(4, 8, F())
    state, palette, packing, _ = material_fixture()
    tt = m.native()
    rock, mobile = state.column_map['a'].layers[0], state.column_map['a'].layers[-1]
    layers = (rock,) * (layers_per_cell - 1) + (mobile,)
    expanded = replace(base, columns=tuple((key, replace(column, layers=layers))
                                          for key, column in base.columns))
    def prop(name, value, unit):
        return tt.PhysicalProperty(name, value, unit, EVIDENCE, 'SYNTHETIC TEST')
    laws, sediment = [], []
    for order, (mid, descriptor) in enumerate(sorted(palette.items())):
        for phase in sorted({descriptor['phase'], 'mobile_sediment'}):
            laws.append(tt.ErosionLaw(mid, phase,
                prop('erosion_coefficient_at_reference_runoff', F(), '1/year'),
                prop('reference_runoff', 1, 'm/year')))
        sediment.append(tt.SedimentLaw(mid, F(1), F(descriptor['porosity']), order, EVIDENCE))
    return grid, ids, edges, expanded, runoff, tuple(laws), tuple(sediment), trial_controls, palette, packing


class LayerBudgetTests(unittest.TestCase):
    def test_2080_distinct_layers_exact_zero_transactions_and_old_guard(self):
        grid, ids, edges, state, runoff, laws, sediment, trial_controls, palette, packing = layered_fixture()
        tt = m.native()
        self.assertEqual(sum(len(c.layers) for _, c in state.columns), 2080)
        result = m.apply(state, ids, [], palette, packing, controls(), operation_id='zero-hillside',
                         start_year=F(), duration_years=F(1), evidence=EVIDENCE)
        self.assertEqual(result.state.as_dict(), state.as_dict())
        self.assertTrue(result.receipt['exact_source_layer_closure'])
        self.assertEqual(sum(len(rows) for rows in result.layer_sources.values()), 2080)
        trial = Domain(grid, ids, edges).trial(state, runoff, F(1), laws, sediment, trial_controls)
        mapping = channel_layer_sources(state, trial)
        self.assertEqual(sum(len(rows) for rows in mapping.values()), 2080)
        self.assertEqual([c.layers for _, c in trial.state.columns], [c.layers for _, c in state.columns])
        self.assertTrue(all(row['mass_residual_kg'] == row['solid_residual_m3'] == 0
                            for row in trial.receipt['material_balances']))
        with self.assertRaises(tt.TerrainContractError):
            kernels.trial(state, runoff, edges, laws, sediment, duration_years=F(1),
                          controls=trial_controls, evidence_id=DEFAULT_EVIDENCE)
        self.assertEqual((tt.MAX_LAYERS, tt.MAX_BITS), (2048, 8192))
        self.assertEqual(tt.landscape.MAX_TOTAL_LAYERS, 16384)

    def test_above8192_guard_rejects_without_merging_or_native_limit_change(self):
        grid, ids, edges, state, runoff, *_, palette, packing = layered_fixture(257)
        self.assertEqual(sum(len(c.layers) for _, c in state.columns), 8224)
        with self.assertRaisesRegex(ValueError, 'layer'):
            m.hillside_view(state, ids, grid, palette, packing)
        with self.assertRaisesRegex(ValueError, '8192'):
            Domain(grid, ids, edges).route(state, runoff, F(1))
        self.assertEqual(sum(len(c.layers) for _, c in state.columns), 8224)
        self.assertEqual(m.native().MAX_BITS, 8192)

    def test_belowcap_exact_native_physics_parity(self):
        grid, ids, edges, state, runoff, laws, sediment, trial_controls = domain_fixture(2, 2)
        expected = kernels.trial(state, runoff, edges, laws, sediment, duration_years=F(1),
                                 controls=trial_controls, evidence_id=DEFAULT_EVIDENCE)
        actual = Domain(grid, ids, edges).trial(state, runoff, F(1), laws, sediment, trial_controls)
        self.assertEqual(actual, expected)

    def test_migration_only_accepts_authenticated_exact_source_replacements(self):
        path = Path(__file__).resolve().parents[2] / 'outputs/native-terrain-r1/upgrade_layers.py'
        spec = importlib.util.spec_from_file_location('native_layer_upgrade_test', path)
        upgrade = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(upgrade)
        for name in upgrade.REPLACEMENTS:
            archived = (upgrade.ARCHIVE / name).read_bytes()
            self.assertEqual(upgrade.expected_successor(name, archived), (Path(m.__file__).parent / name).read_bytes())
            with self.assertRaisesRegex(ValueError, 'archived'):
                upgrade.expected_successor(name, archived + b'\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
