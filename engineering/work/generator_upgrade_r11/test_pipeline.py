"""Current producer connections, exact inputs, chronology and causal budgets."""
from copy import deepcopy
from fractions import Fraction as F
import unittest
from unittest.mock import patch
from . import binding, fixtures, pipeline as p, snapshot


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = binding.load()
        cls.parent = fixtures.parent(cls.bundle)
        cls.recipe = cls.bundle.reference.recipe(cls.bundle)
        cls.groups = p.parent_units(cls.bundle, cls.recipe, cls.parent)

    def test_nine_alternatives_eighteen_units_retained(self):
        self.assertEqual(len(self.groups), 9)
        self.assertEqual(sum(map(len, self.groups.values())), 18)

    def test_actual_source_wrong_recipe_rejected(self):
        recipe = deepcopy(self.recipe); recipe['parent_recipe']['evidence'] += ' changed'
        with self.assertRaisesRegex(ValueError, 'actual source'):
            p.parent_units(self.bundle, recipe, self.parent)

    def test_incomplete_parent_rejected(self):
        parent = deepcopy(self.parent); parent['status'] = 'STOPPED_AT_UNIT_BOUNDARY'
        with self.assertRaises(ValueError):
            p.parent_units(self.bundle, self.recipe, parent)

    def test_missing_coequal_scenario_rejected(self):
        parent = deepcopy(self.parent)
        first = next(iter(parent['state']['results']))
        prefix = first.rsplit('/', 1)[0]+'/'
        parent['state']['results'] = {k: v for k, v in parent['state']['results'].items() if not k.startswith(prefix)}
        with self.assertRaisesRegex(ValueError, 'coequal'):
            p.parent_units(self.bundle, self.recipe, parent)

    def test_lost_physical_cell_rejected(self):
        parent = deepcopy(self.parent); parent['state']['results'].pop(next(iter(parent['state']['results'])))
        with self.assertRaisesRegex(ValueError, 'support'):
            p.parent_units(self.bundle, self.recipe, parent)

    def test_all_surface_exports_counted_once(self):
        for group in self.groups.values():
            spec, joins = p.water_inputs(self.bundle, self.recipe, group)
            source = sum((F(row['surface_export_m3']) for row in joins), F())
            applied = sum((F(row['volume_m3']) for event in spec['events'] for row in event['inflows']), F())
            self.assertEqual(source, applied)
            self.assertTrue(all(row['groundwater_recharge_from_internal_drainage_m3'] == '0' for row in joins))
            self.assertEqual(len({row['allocation_id'] for e in spec['events'] for row in e['inflows']}), 24)

    def test_month_duration_exact(self):
        group = next(iter(self.groups.values())); spec, _ = p.water_inputs(self.bundle, self.recipe, group)
        self.assertEqual(sum((F(x['duration_seconds']) for x in spec['events']), F()), 365*86400)
        for event in spec['events']:
            mid = event['event_id'].split('-')[-1]
            self.assertEqual(F(event['duration_seconds']), F(group['upper']['hydrology']['months'][mid]['duration_seconds']))

    def test_double_area_conversion_rejected(self):
        group = deepcopy(next(iter(self.groups.values())))
        group['upper']['downstream']['local_water_supply']['1']['local_surface_export_m3']['exact'] = '9999'
        with self.assertRaisesRegex(ValueError, 'area conversion'):
            p.water_inputs(self.bundle, self.recipe, group)

    def test_changed_groundwater_boundary_not_ignored(self):
        group = deepcopy(next(iter(self.groups.values())))
        group['upper']['initial_condition']['boundary']['kind'] = 'fixed_head'
        with self.assertRaisesRegex(ValueError, 'groundwater boundary'):
            p.water_inputs(self.bundle, self.recipe, group)

    def test_no_flowing_state_borrowed_from_other_scenario(self):
        parent = deepcopy(self.parent); first = next(iter(parent['state']['results']))
        packed = parent['state']['results'].pop(first)
        parent['state']['results']['wrong/'+first] = packed
        with self.assertRaisesRegex(ValueError, 'identity'):
            p.parent_units(self.bundle, self.recipe, parent)

    def test_explicit_conductance_change_rebinds_initial_state(self):
        group = next(iter(self.groups.values())); recipe = deepcopy(self.recipe)
        recipe['parameters']['network_conductance_multiplier'] = '2'
        old, _ = p.water_inputs(self.bundle, self.recipe, group); new, _ = p.water_inputs(self.bundle, recipe, group)
        self.assertNotEqual(old['initial']['network_sha256'], new['initial']['network_sha256'])
        self.assertEqual(new['initial']['nodes'], old['initial']['nodes'])

    def test_recipe_malformed_or_extra_parameter_rejects(self):
        recipe = deepcopy(self.recipe); recipe['parameters']['new_implicit_law'] = 1
        with self.assertRaises(ValueError):
            p.parse(self.bundle, recipe)

    def test_bool_routing_resolution_rejected(self):
        recipe = deepcopy(self.recipe); recipe['parameters']['routing_substeps_per_shortest_month'] = True
        with self.assertRaises(ValueError):
            p.parse(self.bundle, recipe)

    def test_food_fraction_bounds_rejected(self):
        for value in ('-1/2', '3/2', None):
            recipe = deepcopy(self.recipe); recipe['parameters']['edible_fraction_of_test_harvest'] = value
            with self.assertRaises(ValueError):
                p.parse(self.bundle, recipe)

    def test_zero_cursor_no_scientific_evaluation(self):
        with patch.object(p, 'evaluate_group', side_effect=AssertionError('must not execute')):
            result = p.run_from_parent(self.bundle, self.recipe, self.parent, stop_after=0)
        self.assertEqual(result['state']['results'], {})
        self.assertEqual(result['status'], 'STOPPED_AT_SCENARIO_BOUNDARY')

    def test_checkpoint_zero_exact(self):
        first = p.run_from_parent(self.bundle, self.recipe, self.parent, stop_after=0)
        cp = self.bundle.checkpoint(first)
        self.assertEqual(first, p.run_from_parent(self.bundle, self.recipe, self.parent, stop_after=0, resume=cp))

    def test_checkpoint_forged_prefix_rejected(self):
        first = p.run_from_parent(self.bundle, self.recipe, self.parent, stop_after=0); cp = self.bundle.checkpoint(first)
        cp['state']['parent_result_sha256'] = '0'*64; cp['state_sha256'] = snapshot.sha(cp['state'])
        with self.assertRaisesRegex(ValueError, 'semantic replay'):
            p.run_from_parent(self.bundle, self.recipe, self.parent, stop_after=0, resume=cp)

    def test_checkpoint_changed_parent_rejected(self):
        first = p.run_from_parent(self.bundle, self.recipe, self.parent, stop_after=0); cp = self.bundle.checkpoint(first)
        cp['recipe_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'identity'):
            p.run_from_parent(self.bundle, self.recipe, self.parent, stop_after=0, resume=cp)


if __name__ == '__main__':
    unittest.main()
