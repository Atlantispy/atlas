"""Independent dimensional and finite-stock oracles; no biological defaults."""
from copy import deepcopy
from fractions import Fraction as F
from itertools import permutations
import json
import unittest

from . import stock as s

E = 'SYNTHETIC TEST: explicitly supplied joint scenario, not Diadem biology'
K = 'SYNTHETIC TEST'


def context(**kw):
    result = dict(species_id='test-organism', counting_unit='independent test entities',
        life_stage='explicit test mature stage', spatial_scope_id='two-cell-test',
        time_basis='one explicitly dated snapshot, not annual throughput', snapshot_id='test-instant',
        joint_scenario_id='joint-A', supplier='test fixture', evidence=E, source_status=K)
    result.update(kw)
    return result


def density_cell(ident='a', **kw):
    row = dict(cell_id=ident, eligible=True, measure={'value': 100, 'unit': 'm2'},
        habitat_fraction='3/5', occupied_fraction='1/2',
        density={'value': '2/3', 'denominator_unit': 'm2', 'basis': 'PER_OCCUPIED_MEASURE'},
        evidence=E, source_status=K)
    row.update(kw)
    return row


def stock_cell(ident='a', **kw):
    row = dict(cell_id=ident, eligible=True, weight=1, capacity_expected_entities=100,
        occupied_measure={'value': 20, 'unit': 'm2'}, evidence=E, source_status=K)
    row.update(kw)
    return row


def density_spec(cells=None, **kw):
    out = dict(schema='diadem.declared-density-input.r9', context=context(),
        cells=[density_cell()] if cells is None else cells)
    out.update(kw)
    return out


def stock_spec(**kw):
    out = dict(schema='diadem.prescribed-stock-input.r9', context=context(),
        total_expected_entities=100, cells=[stock_cell('a'), stock_cell('b')])
    out.update(kw)
    return out


def val(quantity):
    return None if quantity is None else F(quantity['exact'])


class DimensionalDensityTests(unittest.TestCase):
    def test_exact_joint_area_habitat_occupancy_density(self):
        out = s.declared_density(density_spec()); row = out['cells']['a']
        self.assertEqual(out['status'], 'MODELLED')
        self.assertEqual(val(row['physical_measure']), 100)
        self.assertEqual(val(row['habitat_measure']), 60)
        self.assertEqual(val(row['occupied_measure']), 30)
        self.assertEqual(val(out['total_expected_entities']), 20)
        self.assertIsNone(row['occupancy_probability'])
        self.assertIsNone(row['observed_entities'])

    def test_whole_cell_density_not_occupancy_weighted_twice(self):
        row = density_cell(density={'value': '1/5', 'denominator_unit': 'm2', 'basis': 'PER_WHOLE_CELL_MEASURE'})
        out = s.declared_density(density_spec([row]))
        self.assertEqual(val(out['total_expected_entities']), 20)
        self.assertEqual(val(out['cells']['a']['density_denominator_measure']), 100)

    def test_habitat_density_uses_habitat_not_occupied_denominator(self):
        row = density_cell(occupied_fraction=None,
            density={'value': '1/3', 'denominator_unit': 'm2', 'basis': 'PER_HABITAT_MEASURE'})
        out = s.declared_density(density_spec([row]))
        self.assertEqual(val(out['total_expected_entities']), 20)
        self.assertIsNone(out['cells']['a']['occupied_measure'])

    def test_whole_cell_density_can_remain_known_with_unknown_fractions(self):
        row = density_cell(habitat_fraction=None, occupied_fraction=None,
            density={'value': '1/5', 'denominator_unit': 'm2', 'basis': 'PER_WHOLE_CELL_MEASURE'})
        out = s.declared_density(density_spec([row]))
        self.assertEqual(out['status'], 'MODELLED')
        self.assertEqual(val(out['total_expected_entities']), 20)
        self.assertIsNone(out['cells']['a']['occupied_measure'])

    def test_area_kilometre_density_conversion_is_exact(self):
        row = density_cell(measure={'value': '1/100', 'unit': 'km2'}, habitat_fraction=1,
            occupied_fraction='1/2', density={'value': 4, 'denominator_unit': 'km2', 'basis': 'PER_OCCUPIED_MEASURE'})
        out = s.declared_density(density_spec([row]))['cells']['a']
        self.assertEqual(val(out['physical_measure']), 10000)
        self.assertEqual(val(out['density_per_si_unit']), F(1, 250000))
        self.assertEqual(val(out['expected_entities']), F(1, 50))

    def test_length_density_has_no_inferred_width(self):
        row = density_cell(measure={'value': 2, 'unit': 'km'}, habitat_fraction='1/2', occupied_fraction='1/4',
            density={'value': 80, 'denominator_unit': 'km', 'basis': 'PER_OCCUPIED_MEASURE'})
        out = s.declared_density(density_spec([row]))['cells']['a']
        self.assertEqual(out['measure_unit'], 'm')
        self.assertEqual(val(out['occupied_measure']), 250)
        self.assertEqual(val(out['expected_entities']), 20)

    def test_volume_density_has_no_inferred_height(self):
        row = density_cell(measure={'value': 1, 'unit': 'km3'}, habitat_fraction='1/2', occupied_fraction='1/4',
            density={'value': '4/1000000', 'denominator_unit': 'm3', 'basis': 'PER_OCCUPIED_MEASURE'})
        out = s.declared_density(density_spec([row]))['cells']['a']
        self.assertEqual(out['measure_unit'], 'm3')
        self.assertEqual(val(out['expected_entities']), 500)
        row['density'].update(value=4000, denominator_unit='km3')
        self.assertEqual(val(s.declared_density(density_spec([row]))['total_expected_entities']), 500)

    def test_cross_dimension_conversion_rejects(self):
        for unit in ('m', 'km', 'm3', 'km3'):
            with self.subTest(unit=unit), self.assertRaisesRegex(ValueError, 'dimension differs'):
                row = density_cell(); row['density']['denominator_unit'] = unit
                s.declared_density(density_spec([row]))

    def test_unknown_required_fraction_density_or_measure_is_not_zero(self):
        for key in ('habitat_fraction', 'occupied_fraction', 'density', 'measure'):
            with self.subTest(key=key):
                row = density_cell()
                if key in ('density', 'measure'): row[key]['value'] = None
                else: row[key] = None
                out = s.declared_density(density_spec([row]))
                self.assertEqual(out['status'], 'UNKNOWN')
                self.assertIsNone(out['total_expected_entities'])
                self.assertIsNone(out['cells']['a']['expected_entities'])

    def test_known_subtotal_separate_from_unknown_total(self):
        out = s.declared_density(density_spec([density_cell('a'), density_cell('b', occupied_fraction=None)]))
        self.assertEqual(val(out['known_subtotal_expected_entities']), 20)
        self.assertIsNone(out['total_expected_entities'])

    def test_explicit_exclusion_is_zero_without_missing_biology_defaults(self):
        row = density_cell(eligible=False, habitat_fraction=None, occupied_fraction=None)
        row['density']['value'] = None; row['measure']['value'] = None
        out = s.declared_density(density_spec([row]))
        self.assertEqual(out['cells']['a']['status'], 'EXCLUDED')
        self.assertEqual(val(out['total_expected_entities']), 0)
        self.assertIsNone(out['cells']['a']['density_per_si_unit'])

    def test_unknown_eligibility_and_source_are_not_exclusion(self):
        for kw in ({'eligible': None}, {'eligible': False, 'source_status': 'UNKNOWN'}):
            out = s.declared_density(density_spec([density_cell(**kw)]))
            self.assertIsNone(out['total_expected_entities'])

    def test_empty_footprint_is_explicit_zero_only_with_known_scope(self):
        self.assertEqual(val(s.declared_density(density_spec([]))['total_expected_entities']), 0)
        out = s.declared_density(density_spec([], context=context(source_status='UNKNOWN')))
        self.assertEqual(out['status'], 'UNKNOWN'); self.assertIsNone(out['total_expected_entities'])

    def test_positive_whole_cell_density_cannot_contradict_zero_footprint(self):
        for key in ('habitat_fraction', 'occupied_fraction'):
            row = density_cell(**{key: 0}); row['density']['basis'] = 'PER_WHOLE_CELL_MEASURE'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'zero habitat/occupied'):
                s.declared_density(density_spec([row]))

    def test_known_zero_fraction_blocks_positive_count_despite_other_unknown_fraction(self):
        for h, f in ((None, 0), (0, None)):
            row = density_cell(habitat_fraction=h, occupied_fraction=f)
            row['density']['basis'] = 'PER_WHOLE_CELL_MEASURE'
            with self.subTest(h=h, f=f), self.assertRaisesRegex(ValueError, 'zero habitat/occupied'):
                s.declared_density(density_spec([row]))

    def test_joint_scenarios_not_marginal_product(self):
        low = density_cell(occupied_fraction='1/4'); low['density']['value'] = 4
        high = density_cell(occupied_fraction=1); high['density']['value'] = 1
        results = [val(s.declared_density(density_spec([r]))['total_expected_entities']) for r in (low, high)]
        self.assertEqual(results, [60, 60])
        self.assertNotEqual(sum(results)/2, 60*F(5, 8)*F(5, 2))

    def test_fractional_expected_count_does_not_invent_bernoulli_presence(self):
        row = density_cell(); row['density']['value'] = '1/300'
        out = s.declared_density(density_spec([row]))['cells']['a']
        self.assertEqual(val(out['expected_entities']), F(1, 10))
        self.assertIsNone(out['occupancy_probability'])


class PrescribedStockTests(unittest.TestCase):
    def test_hand_weighted_allocation_and_conservation(self):
        out = s.allocate_stock(stock_spec(cells=[stock_cell('a', weight=1), stock_cell('b', weight=3)]))
        self.assertEqual(out['status'], 'MODELLED_ALLOCATION_COMPLETE')
        self.assertEqual(val(out['cells']['a']['allocation_expected_entities']), 25)
        self.assertEqual(val(out['cells']['b']['allocation_expected_entities']), 75)
        self.assertEqual(val(out['placed_expected_entities']) + val(out['unplaced_expected_entities']), 100)
        self.assertEqual(val(out['conservation_residual_expected_entities']), 0)

    def test_excluded_weight_remains_in_denominator_without_redistribution(self):
        out = s.allocate_stock(stock_spec(cells=[stock_cell('a'), stock_cell('b', eligible=False)]))
        self.assertEqual(val(out['normalisation_weight']), 2)
        self.assertEqual(val(out['cells']['a']['allocation_expected_entities']), 50)
        self.assertEqual(val(out['cells']['b']['allocation_expected_entities']), 0)
        self.assertEqual(val(out['unplaced_expected_entities']), 50)

    def test_capped_share_stays_unplaced(self):
        out = s.allocate_stock(stock_spec(cells=[stock_cell('a', capacity_expected_entities=5), stock_cell('b')]))
        self.assertEqual(out['cells']['a']['status'], 'CAPPED')
        self.assertEqual(val(out['cells']['b']['allocation_expected_entities']), 50)
        self.assertEqual(val(out['unplaced_expected_entities']), 45)

    def test_unknown_weight_prevents_known_subset_renormalisation(self):
        out = s.allocate_stock(stock_spec(cells=[stock_cell('a'), stock_cell('b', weight=None)]))
        self.assertEqual(out['status'], 'UNKNOWN')
        self.assertIsNone(out['normalisation_weight'])
        self.assertTrue(all(row['allocation_expected_entities'] is None for row in out['cells'].values()))
        self.assertEqual(val(out['placed_expected_entities']), 0)
        self.assertEqual(val(out['unplaced_expected_entities']), 100)

    def test_unknown_excluded_weight_still_cannot_be_discarded(self):
        out = s.allocate_stock(stock_spec(cells=[stock_cell('a'), stock_cell('b', eligible=False, weight=None)]))
        self.assertIsNone(out['cells']['a']['allocation_expected_entities'])
        self.assertEqual(val(out['unplaced_expected_entities']), 100)

    def test_unknown_local_cap_or_eligibility_retains_other_original_share(self):
        for kw in ({'capacity_expected_entities': None}, {'eligible': None}):
            out = s.allocate_stock(stock_spec(cells=[stock_cell('a'), stock_cell('b', **kw)]))
            self.assertEqual(out['status'], 'UNKNOWN')
            self.assertEqual(val(out['cells']['a']['allocation_expected_entities']), 50)
            self.assertIsNone(out['cells']['b']['allocation_expected_entities'])
            self.assertEqual(val(out['cells']['b']['committed_expected_entities']), 0)
            self.assertEqual(val(out['unplaced_expected_entities']), 50)

    def test_excluded_cell_needs_no_invented_capacity(self):
        out = s.allocate_stock(stock_spec(cells=[stock_cell('a'), stock_cell('b', eligible=False, capacity_expected_entities=None)]))
        self.assertEqual(out['status'], 'MODELLED_PARTLY_UNPLACED')
        self.assertEqual(val(out['placed_expected_entities']), 50)

    def test_absent_geography_retains_all_known_stock_unplaced(self):
        out = s.allocate_stock(stock_spec(cells=None))
        self.assertEqual(out['status'], 'UNKNOWN'); self.assertEqual(out['cells'], {})
        self.assertEqual(val(out['total_expected_entities']), 100)
        self.assertEqual(val(out['unplaced_expected_entities']), 100)

    def test_empty_or_zero_weight_geography_does_not_create_allocation(self):
        for cells in ([], [stock_cell('a', weight=0), stock_cell('b', weight=0)]):
            out = s.allocate_stock(stock_spec(cells=cells))
            self.assertEqual(out['status'], 'MODELLED_PARTLY_UNPLACED')
            self.assertEqual(val(out['placed_expected_entities']), 0)
            self.assertEqual(val(out['unplaced_expected_entities']), 100)

    def test_unknown_total_or_total_source_is_never_zero_stock(self):
        for kw in ({'total_expected_entities': None}, {'context': context(source_status='UNKNOWN')}):
            out = s.allocate_stock(stock_spec(**kw))
            self.assertEqual(out['status'], 'UNKNOWN')
            self.assertIsNone(out['total_expected_entities']); self.assertIsNone(out['unplaced_expected_entities'])
            self.assertIsNone(out['conservation_residual_expected_entities'])

    def test_unknown_row_source_masks_allocation_and_measure(self):
        out = s.allocate_stock(stock_spec(cells=[stock_cell('a'), stock_cell('b', source_status='UNKNOWN')]))
        self.assertEqual(val(out['unplaced_expected_entities']), 100)
        self.assertIsNone(out['cells']['b']['occupied_measure'])
        self.assertIsNone(out['cells']['b']['implied_density_per_si_unit'])

    def test_zero_stock_known_scope_is_complete_without_invented_counts(self):
        out = s.allocate_stock(stock_spec(total_expected_entities=0))
        self.assertEqual(out['status'], 'MODELLED_ALLOCATION_COMPLETE')
        self.assertEqual(val(out['placed_expected_entities']), 0)
        self.assertEqual(val(out['unplaced_expected_entities']), 0)

    def test_positive_stock_on_zero_occupied_measure_is_conflict(self):
        out = s.allocate_stock(stock_spec(cells=[stock_cell('a', occupied_measure={'value': 0, 'unit': 'm2'})]))
        self.assertEqual(out['status'], 'CONFLICT')
        self.assertEqual(out['cells']['a']['status'], 'CONFLICT')
        self.assertIsNone(out['cells']['a']['allocation_expected_entities'])
        self.assertEqual(val(out['unplaced_expected_entities']), 100)

    def test_implied_density_requires_measure_not_new_population(self):
        for unit, scale in (('m', 1), ('km', 1000), ('m2', 1), ('km2', 1000000), ('m3', 1), ('km3', 1000000000)):
            out = s.allocate_stock(stock_spec(cells=[stock_cell('a', occupied_measure={'value': 2, 'unit': unit})]))
            self.assertEqual(val(out['cells']['a']['implied_density_per_si_unit']), F(50, scale))
        out = s.allocate_stock(stock_spec(cells=[stock_cell('a', occupied_measure=None)]))
        self.assertEqual(val(out['placed_expected_entities']), 100)
        self.assertIsNone(out['cells']['a']['implied_density_per_si_unit'])

    def test_exact_fractional_stock_caps_and_sensitivity(self):
        rows = [stock_cell('a', weight='1/3', capacity_expected_entities='2/7'), stock_cell('b', weight='2/3')]
        out = s.allocate_stock(stock_spec(total_expected_entities='7/3', cells=rows))
        self.assertEqual(val(out['cells']['a']['allocation_expected_entities']), F(2, 7))
        self.assertEqual(val(out['cells']['b']['allocation_expected_entities']), F(14, 9))
        self.assertEqual(val(out['unplaced_expected_entities']), F(31, 63))
        rows[0]['capacity_expected_entities'] = '3/7'
        higher = s.allocate_stock(stock_spec(total_expected_entities='7/3', cells=rows))
        self.assertEqual(val(higher['placed_expected_entities'])-val(out['placed_expected_entities']), F(1, 7))
        self.assertEqual(higher['cells']['b'], out['cells']['b'])

    def test_permutations_deterministic_and_inputs_unmodified(self):
        rows = [stock_cell('a', weight=1), stock_cell('b', weight=2), stock_cell('c', weight=3)]
        original = deepcopy(rows); results = [s.allocate_stock(stock_spec(cells=list(p))) for p in permutations(rows)]
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(rows, original)


class StockSchemaTests(unittest.TestCase):
    def test_exact_fields_and_schema_required(self):
        for function, spec in ((s.declared_density, density_spec()), (s.allocate_stock, stock_spec())):
            bad = deepcopy(spec); bad['surprise'] = 1
            with self.assertRaises(ValueError): function(bad)
            bad = deepcopy(spec); bad['schema'] = 'old'
            with self.assertRaises(ValueError): function(bad)
            bad = deepcopy(spec); del bad['context']['life_stage']
            with self.assertRaises(ValueError): function(bad)
            bad = deepcopy(spec); bad['cells'][0]['unexpected'] = 1
            with self.assertRaises(ValueError): function(bad)

    def test_duplicate_cells_and_non_boolean_eligibility_reject(self):
        for function, spec in ((s.declared_density, density_spec()), (s.allocate_stock, stock_spec())):
            bad = deepcopy(spec); bad['cells'] = [deepcopy(spec['cells'][0]), deepcopy(spec['cells'][0])]
            with self.assertRaises(ValueError): function(bad)
            for eligible in (0, 1, 'False', [], {}):
                bad = deepcopy(spec); bad['cells'][0]['eligible'] = eligible
                with self.assertRaises(ValueError): function(bad)

    def test_numeric_boolean_nonfinite_negative_and_expansion_reject(self):
        for number in (True, False, float('nan'), float('inf'), -1, '1e999999999', '1/0', 'x', '1'*257):
            with self.subTest(number=str(number)), self.assertRaises(ValueError):
                s.allocate_stock(stock_spec(total_expected_entities=number))
        for number in ('1.01', -1, True):
            with self.assertRaises(ValueError): s.declared_density(density_spec([density_cell(habitat_fraction=number)]))

    def test_unrecognised_status_units_basis_and_context_reject(self):
        for status in ('APPROVED', True, None):
            with self.assertRaises(ValueError): s.allocate_stock(stock_spec(context=context(source_status=status)))
        for unit in ('hectare', 'individuals', [], 3):
            row = density_cell(); row['measure']['unit'] = unit
            with self.assertRaises(ValueError): s.declared_density(density_spec([row]))
        row = density_cell(); row['density']['basis'] = []
        with self.assertRaises(ValueError): s.declared_density(density_spec([row]))
        with self.assertRaises(ValueError): s.allocate_stock(stock_spec(context=context(evidence=' ')))

    def test_exact_number_forms_and_json_safe_outputs(self):
        row = stock_cell('a', weight=F(1, 3)); row['capacity_expected_entities'] = '0.5'
        out = s.allocate_stock(stock_spec(total_expected_entities=F(2, 3), cells=[row]))
        self.assertEqual(val(out['placed_expected_entities']), F(1, 2))
        self.assertEqual(val(out['unplaced_expected_entities']), F(1, 6))
        json.dumps(out, allow_nan=False)
        json.dumps(s.declared_density(density_spec()), allow_nan=False)

    def test_source_identity_changes_with_scope_and_scenario_not_cell_order(self):
        a = s.declared_density(density_spec([density_cell('a'), density_cell('b')]))
        b = s.declared_density(density_spec([density_cell('b'), density_cell('a')]))
        self.assertEqual(a, b)
        c = s.declared_density(density_spec([density_cell('a'), density_cell('b')], context=context(joint_scenario_id='joint-B')))
        self.assertNotEqual(a['inputs_sha256'], c['inputs_sha256'])
        self.assertEqual(a['total_expected_entities'], c['total_expected_entities'])


if __name__ == '__main__':
    unittest.main()
