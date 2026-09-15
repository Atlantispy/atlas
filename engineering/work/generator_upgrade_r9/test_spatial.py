"""Independent hand-graph, probability, area and exact transfer oracles."""
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction as F
from itertools import permutations
import json
import unittest

from . import spatial as s

E = 'SYNTHETIC TEST: hypothetical species at explicit finite cell support'
K = 'SYNTHETIC TEST'


def cell(ident, **kw):
    return replace(s.Cell(ident, F(20), 1., F(1), True, E, K), **kw)


def edge(ident, a, b, **kw):
    return replace(s.Edge(ident, a, b, F(1), True, F(20), E, K), **kw)


def rule(**kw):
    return replace(s.SpeciesRule('hypothetical-animal', .5, 0., 0., F(1), F(1),
                                F(5), 'm', 'SEASONAL_MOVEMENT', E, K), **kw)


def origin(ident='a', **kw):
    return replace(s.Origin(ident, E, K), **kw)


def request(ident='move', a='a', b='b', amount=5, priority=0, **kw):
    return replace(s.MovementRequest(ident, a, b, F(amount), priority, E, K), **kw)


def value(q):
    return None if q is None else F(q['exact'])


def evaluate(cells=None, edges=None, origins=None, r=None, **kw):
    return s.evaluate_range((cell('a'), cell('b')) if cells is None else cells,
                            (edge('ab', 'a', 'b'),) if edges is None else edges,
                            (origin(),) if origins is None else origins,
                            rule() if r is None else r, season_id='warm', **kw)


def movements(cells=None, edges=None, origins=None, r=None, requests=None, capacity=None, **kw):
    cs = (cell('a'), cell('b')) if cells is None else cells
    return s.route_movements(cs, (edge('ab', 'a', 'b'),) if edges is None else edges,
        (origin(),) if origins is None else origins, rule() if r is None else r,
        (request(),) if requests is None else requests, season_id='warm',
        receiving_capacity={c.cell_id: F(20) for c in cs} if capacity is None else capacity,
        evidence=E, source_status=K, **kw)


class SnapshotTests(unittest.TestCase):
    def test_support_probability_occupied_area_and_abundance_are_distinct(self):
        result = evaluate(cells=(cell('a', area_m2=F(100), habitat_fraction=F(3, 5)),), edges=(),
                          r=rule(conditional_occupied_fraction=F(1, 2), density_per_occupied_m2=F(2, 3)))
        row = result['cells']['a']
        self.assertEqual(row['habitat_support'], 1.)
        self.assertEqual(row['occupancy_probability'], .5)
        self.assertEqual(value(row['expected_occupied_fraction']), F(3, 20))
        self.assertEqual(value(row['expected_occupied_area_m2']), 15)
        self.assertEqual(value(row['expected_individuals']), 10)
        self.assertIsNone(row['realised_occupied_fraction'])
        self.assertIsNone(row['observed_individuals'])
        self.assertIsNone(row['active_bonds'])

    def test_logistic_probability_independent_decimal(self):
        out = evaluate(r=rule(logit_intercept=-2., logit_slope=3.))
        with localcontext() as ctx:
            ctx.prec = 60
            expected = 1/(1+(-Decimal(1)).exp())
        self.assertAlmostEqual(out['cells']['b']['occupancy_probability'], float(expected), places=15)

    def test_negative_logistic_slope_is_explicit_not_assumed_monotone(self):
        r = rule(logit_slope=-2.)
        low = evaluate(cells=(cell('a', habitat_support=.5),), edges=(), r=r)
        high = evaluate(cells=(cell('a'),), edges=(), r=r)
        self.assertGreater(low['cells']['a']['occupancy_probability'], high['cells']['a']['occupancy_probability'])

    def test_suitability_threshold_is_inclusive(self):
        at = evaluate(cells=(cell('a', habitat_support=.5),), edges=())
        below = evaluate(cells=(cell('a', habitat_support=.499),), edges=())
        self.assertEqual(at['cells']['a']['habitat_status'], 'PASS')
        self.assertEqual(below['cells']['a']['habitat_status'], 'FAIL')
        self.assertEqual(value(below['total_expected_individuals']), 0)

    def test_known_absent_habitat_is_zero_without_unknown_density(self):
        out = evaluate(cells=(cell('a', habitat_fraction=F()),), edges=(), r=rule(density_per_occupied_m2=None))
        self.assertEqual(out['status'], 'MODELLED')
        self.assertEqual(value(out['total_expected_individuals']), 0)

    def test_missing_support_stays_unknown_and_partial_total_is_labelled(self):
        out = evaluate(cells=(cell('a'), cell('b', habitat_support=None)))
        self.assertEqual(out['status'], 'UNKNOWN')
        self.assertIsNone(out['total_expected_individuals'])
        self.assertIsNone(out['cells']['b']['expected_individuals'])
        self.assertEqual(value(out['known_subtotal_expected_individuals']), 10)

    def test_missing_density_does_not_destroy_known_occupancy(self):
        out = evaluate(r=rule(density_per_occupied_m2=None))
        self.assertEqual(out['cells']['a']['occupancy_status'], 'MODELLED')
        self.assertEqual(out['cells']['a']['abundance_status'], 'UNKNOWN')
        self.assertEqual(out['cells']['a']['occupancy_probability'], .5)
        self.assertIsNone(out['total_expected_individuals'])

    def test_conditional_abundance_cannot_contradict_presence_probability(self):
        out = evaluate(cells=(cell('a', area_m2=F(1, 2)),), edges=())
        self.assertEqual(out['status'], 'UNKNOWN')
        self.assertEqual(out['cells']['a']['occupancy_probability'], .5)
        self.assertEqual(out['cells']['a']['abundance_status'], 'OUTSIDE_REGIME')
        self.assertEqual(value(out['cells']['a']['conditional_expected_individuals_if_occupied']), F(1, 2))
        self.assertIsNone(out['total_expected_individuals'])

    def test_zero_density_with_positive_occurrence_is_not_valid_abundance(self):
        out = evaluate(r=rule(density_per_occupied_m2=F()))
        self.assertEqual(out['cells']['a']['abundance_status'], 'OUTSIDE_REGIME')
        self.assertIsNone(out['cells']['a']['expected_individuals'])

    def test_explicit_zero_conditional_occupied_fraction_is_structural_absence(self):
        out = evaluate(r=rule(conditional_occupied_fraction=F(), density_per_occupied_m2=None))
        self.assertEqual(out['status'], 'MODELLED')
        self.assertEqual(out['cells']['a']['habitat_status'], 'PASS')
        self.assertEqual(out['cells']['a']['occupancy_probability'], 0.)
        self.assertEqual(value(out['total_expected_individuals']), 0)

    def test_missing_occupancy_law_is_not_support_renaming(self):
        for missing in ('logit_intercept', 'logit_slope', 'conditional_occupied_fraction'):
            with self.subTest(missing=missing):
                out = evaluate(r=rule(**{missing: None}))
                self.assertEqual(out['status'], 'UNKNOWN')
                self.assertIsNone(out['cells']['b']['expected_occupied_area_m2'])

    def test_extreme_logit_fails_closed_instead_of_fabricating_exact_zero_one(self):
        for intercept in (-1000., 1000.):
            with self.subTest(intercept=intercept):
                out = evaluate(r=rule(logit_intercept=intercept))
                self.assertEqual(out['status'], 'NUMERICAL_FAILURE')
                self.assertIsNone(out['cells']['a']['occupancy_probability'])

    def test_directed_access_has_no_implicit_reverse_edge(self):
        out = evaluate(origins=(origin('b'),))
        self.assertEqual(out['cells']['a']['accessibility']['status'], 'INACCESSIBLE')
        self.assertEqual(out['cells']['b']['accessibility']['status'], 'ACCESSIBLE')
        self.assertEqual(value(out['cells']['a']['expected_individuals']), 0)

    def test_exact_cost_budget_boundary_and_longer_path(self):
        cs = (cell('a'), cell('b'), cell('c'))
        es = (edge('ab', 'a', 'b', travel_cost=F(1, 3)), edge('bc', 'b', 'c', travel_cost=F(2, 3)))
        yes = evaluate(cs, es, r=rule(travel_budget=F(1)))
        no = evaluate(cs, es, r=rule(travel_budget=F(999, 1000)))
        self.assertEqual(yes['cells']['c']['accessibility']['status'], 'ACCESSIBLE')
        self.assertEqual(value(yes['cells']['c']['accessibility']['least_cost']), 1)
        self.assertEqual(no['cells']['c']['accessibility']['status'], 'INACCESSIBLE')

    def test_unknown_barrier_yields_unknown_not_zero_or_access(self):
        for change in ({'enabled': None}, {'travel_cost': None}, {'capacity_expected_individuals': None}, {'source_status': 'UNKNOWN'}):
            with self.subTest(change=change):
                out = evaluate(edges=(edge('ab', 'a', 'b', **change),))
                self.assertEqual(out['cells']['b']['accessibility']['status'], 'UNKNOWN')
                self.assertIsNone(out['cells']['b']['expected_individuals'])

    def test_unknown_bridge_cell_propagates_downstream(self):
        out = evaluate((cell('a'), cell('b', traversable=None), cell('c')),
                       (edge('ab', 'a', 'b'), edge('bc', 'b', 'c')))
        self.assertEqual(out['cells']['c']['accessibility']['status'], 'UNKNOWN')

    def test_known_closed_and_zero_capacity_edges_are_barriers(self):
        for change in ({'enabled': False}, {'capacity_expected_individuals': F()}):
            with self.subTest(change=change):
                out = evaluate(edges=(edge('ab', 'a', 'b', **change),))
                self.assertEqual(out['cells']['b']['accessibility']['status'], 'INACCESSIBLE')

    def test_origin_unknown_empty_and_known_are_different_hypotheses(self):
        args = ((cell('a'),), (), rule())
        unknown = s.evaluate_range(args[0], args[1], None, args[2], season_id='warm')
        absent = s.evaluate_range(args[0], args[1], (), args[2], season_id='warm')
        self.assertEqual(unknown['status'], 'UNKNOWN')
        self.assertEqual(absent['status'], 'MODELLED')
        self.assertEqual(value(absent['total_expected_individuals']), 0)
        self.assertEqual(evaluate(cells=args[0], edges=())['cells']['a']['occupancy_probability'], .5)

    def test_unknown_origin_does_not_establish_presence(self):
        out = evaluate(origins=(origin(source_status='UNKNOWN'),))
        self.assertEqual(out['cells']['a']['accessibility']['status'], 'UNKNOWN')
        self.assertIsNone(out['cells']['a']['occupancy_probability'])

    def test_zero_cost_cycles_terminate_without_repeating_cells(self):
        out = evaluate((cell('a'), cell('b'), cell('c')),
                       (edge('ab', 'a', 'b', travel_cost=F()), edge('ba', 'b', 'a', travel_cost=F()), edge('bc', 'b', 'c')))
        self.assertEqual(out['cells']['c']['accessibility']['path_edge_ids'], ['ab', 'bc'])

    def test_unsuitable_transit_matrix_is_not_forced_to_be_occupied(self):
        out = evaluate((cell('a'), cell('b', habitat_support=0.), cell('c')),
                       (edge('ab', 'a', 'b'), edge('bc', 'b', 'c')))
        self.assertEqual(value(out['cells']['b']['expected_individuals']), 0)
        self.assertEqual(out['cells']['c']['accessibility']['status'], 'ACCESSIBLE')
        self.assertEqual(value(out['cells']['c']['expected_individuals']), 10)

    def test_shortest_costs_independent_exhaustive_simple_path_oracle(self):
        cs = tuple(cell(k) for k in 'abcd')
        template = (('a', 'b'), ('b', 'c'), ('c', 'd'), ('a', 'd'), ('c', 'a'), ('b', 'd'))
        for mask in range(64):
            es = tuple(edge(str(i), a, b, travel_cost=F(i % 3))
                       for i, (a, b) in enumerate(template) if mask & (1 << i))
            expected = {}
            def visit(node, cost, visited):
                expected[node] = min(expected.get(node, cost), cost)
                for e in es:
                    if e.source == node and e.target not in visited:
                        visit(e.target, cost+F(e.travel_cost), visited+(e.target,))
            visit('a', F(), ('a',))
            result = evaluate(cs, es, r=rule(travel_budget=F(100)))
            for ident in 'abcd':
                self.assertEqual(value(result['cells'][ident]['accessibility']['least_cost']), expected.get(ident))

    def test_equal_cost_tie_and_complete_output_are_input_order_independent(self):
        cs = (cell('a'), cell('b'), cell('c'), cell('d'))
        es = (edge('a-first', 'a', 'b'), edge('b-last', 'b', 'd'),
              edge('c-first', 'a', 'c'), edge('d-last', 'c', 'd'))
        out = evaluate(cs, es)
        self.assertEqual(out['cells']['d']['accessibility']['path_edge_ids'], ['a-first', 'b-last'])
        for p in permutations(es): self.assertEqual(evaluate(tuple(reversed(cs)), p), out)

    def test_prescribed_total_matches_or_conflicts_without_rescaling(self):
        matching = evaluate(prescribed_total=s.PrescribedTotal(F(20), E, K))
        conflicting = evaluate(prescribed_total=s.PrescribedTotal(F(200), E, K))
        self.assertEqual(matching['prescribed_total_check']['status'], 'MATCH')
        self.assertEqual(conflicting['status'], 'CONFLICT')
        self.assertEqual(value(conflicting['total_expected_individuals']), 20)
        self.assertEqual(value(conflicting['prescribed_total_check']['difference']), -180)

    def test_total_with_unresolved_density_is_unknown_not_allocation_target(self):
        out = evaluate(r=rule(density_per_occupied_m2=None), prescribed_total=s.PrescribedTotal(F(100), E, K))
        self.assertEqual(out['prescribed_total_check']['status'], 'UNKNOWN')
        self.assertIsNone(out['total_expected_individuals'])

    def test_unknown_source_status_cannot_promote_supplied_numbers(self):
        out = evaluate(r=rule(source_status='UNKNOWN'))
        self.assertEqual(out['status'], 'UNKNOWN')
        self.assertIsNone(out['cells']['a']['habitat_support'])


class MovementTests(unittest.TestCase):
    def test_actual_source_stock_and_exact_conservation(self):
        out = movements()
        self.assertEqual(out['status'], 'MODELLED_FEASIBLE_ALLOCATION')
        self.assertEqual(value(out['cells']['a']['initial_expected_individuals']), 10)
        self.assertEqual(value(out['cells']['a']['final_expected_individuals']), 5)
        self.assertEqual(value(out['cells']['b']['final_expected_individuals']), 15)
        self.assertEqual(value(out['edges']['ab']['used_expected_individuals']), 5)
        self.assertEqual(value(out['transfer_conservation_residual_expected_individuals']), 0)
        self.assertEqual(out['paths'][0]['edge_ids'], ['ab'])

    def test_finite_source_stock_limits_transfers(self):
        out = movements(requests=(request(amount=50),))
        row = out['requests'][0]
        self.assertEqual(value(row['transferred_expected_individuals']), 10)
        self.assertEqual(value(row['unmet_expected_individuals']), 40)
        self.assertEqual(row['status'], 'POLICY_UNMET')

    def test_additional_receiving_capacity_limits_transfers(self):
        out = movements(capacity={'a': F(20), 'b': F(2)})
        self.assertEqual(value(out['requests'][0]['transferred_expected_individuals']), 2)
        self.assertEqual(value(out['cells']['b']['unused_receiving_capacity']), 0)

    def test_edge_capacity_shared_across_requests(self):
        out = movements(edges=(edge('ab', 'a', 'b', capacity_expected_individuals=F(6)),),
                        requests=(request('first', amount=4), request('second', amount=4, priority=1)))
        self.assertEqual([value(r['transferred_expected_individuals']) for r in out['requests']], [4, 2])
        self.assertEqual(value(out['edges']['ab']['remaining_expected_individuals']), 0)

    def test_parallel_routes_are_allocated_when_first_saturates(self):
        cs = (cell('a'), cell('b'), cell('c'))
        es = (edge('ab', 'a', 'b', capacity_expected_individuals=F(3)),
              edge('ac', 'a', 'c', capacity_expected_individuals=F(4)), edge('cb', 'c', 'b', capacity_expected_individuals=F(4)))
        out = movements(cs, es, requests=(request(amount=7),))
        self.assertEqual([p['edge_ids'] for p in out['paths']], [['ab'], ['ac', 'cb']])
        self.assertEqual([value(p['expected_individuals']) for p in out['paths']], [3, 4])
        self.assertEqual(out['requests'][0]['status'], 'FULFILLED')

    def test_each_path_obeys_budget_not_just_cheapest_accessibility(self):
        cs = (cell('a'), cell('b'), cell('c'))
        es = (edge('ab', 'a', 'b', capacity_expected_individuals=F(3)), edge('ac', 'a', 'c'), edge('cb', 'c', 'b'))
        out = movements(cs, es, r=rule(travel_budget=F(1)), requests=(request(amount=7),))
        self.assertEqual(len(out['paths']), 1)
        self.assertEqual(value(out['requests'][0]['transferred_expected_individuals']), 3)

    def test_arrivals_cannot_be_reexported_as_fresh_origin_stock(self):
        cs = (cell('a'), cell('b'), cell('c'))
        out = movements(cs, (edge('ab', 'a', 'b'), edge('bc', 'b', 'c')),
                        requests=(request('ab', amount=10), request('bc', 'b', 'c', 20, 1)))
        self.assertEqual(value(out['requests'][1]['transferred_expected_individuals']), 10)
        self.assertEqual(value(out['cells']['b']['initial_expected_individuals']), 10)
        self.assertEqual(value(out['cells']['b']['incoming_expected_individuals']), 10)
        self.assertEqual(value(out['cells']['b']['outgoing_expected_individuals']), 10)

    def test_unknown_edge_does_not_create_flow(self):
        out = movements(edges=(edge('ab', 'a', 'b', enabled=None),))
        self.assertEqual(out['status'], 'UNKNOWN')
        self.assertEqual(out['paths'], [])
        self.assertEqual(value(out['edges']['ab']['used_expected_individuals']), 0)

    def test_unknown_bridge_preserves_movement_uncertainty(self):
        cs = (cell('a'), cell('b', traversable=None), cell('c'))
        out = movements(cs, (edge('ab', 'a', 'b'), edge('bc', 'b', 'c')), requests=(request(b='c'),))
        self.assertEqual(out['requests'][0]['status'], 'UNKNOWN')
        self.assertEqual(out['paths'], [])

    def test_known_barrier_is_policy_unmet_not_unknown(self):
        out = movements(edges=(edge('ab', 'a', 'b', enabled=False),))
        self.assertEqual(out['requests'][0]['status'], 'POLICY_UNMET')
        self.assertEqual(out['paths'], [])

    def test_missing_receiving_capacity_stays_unknown(self):
        out = movements(capacity={'a': F(20), 'b': None})
        self.assertEqual(out['status'], 'UNKNOWN')
        self.assertEqual(out['paths'], [])
        self.assertIsNone(out['cells']['b']['unused_receiving_capacity'])

    def test_nonmoving_life_stage_is_not_applicable_not_zero_migration(self):
        out = movements(r=rule(movement_mode='NONMOVING'), requests=())
        self.assertEqual(out['status'], 'NOT_APPLICABLE')
        self.assertIsNone(out['cells'])
        with self.assertRaises(ValueError): movements(r=rule(movement_mode='NONMOVING'))

    def test_unresolved_nonmoving_source_does_not_establish_not_applicable(self):
        out = movements(r=rule(movement_mode='NONMOVING', source_status='UNKNOWN'), requests=())
        self.assertEqual(out['status'], 'UNKNOWN')
        self.assertEqual(out['paths'], [])
        out = s.route_movements((cell('a'), cell('b')), (edge('ab', 'a', 'b'),),
            (origin(),), rule(movement_mode='NONMOVING'), (), season_id='warm',
            receiving_capacity={'a': F(20), 'b': F(20)}, evidence=E, source_status='UNKNOWN')
        self.assertEqual(out['status'], 'UNKNOWN')

    def test_unknown_movement_applicability_and_conflicting_total_block(self):
        self.assertEqual(movements(r=rule(movement_mode='UNKNOWN'))['status'], 'UNKNOWN')
        out = movements(prescribed_total=s.PrescribedTotal(F(100), E, K))
        self.assertEqual(out['status'], 'UNKNOWN')
        self.assertEqual(out['paths'], [])

    def test_arrival_season_habitat_is_independent_of_departure(self):
        kw = {'destination_cells': (cell('a'), cell('b', habitat_support=0.)),
              'destination_edges': (edge('ab', 'a', 'b'),), 'destination_origins': (origin(),),
              'destination_rule': rule(), 'destination_season_id': 'cold'}
        out = movements(**kw)
        self.assertEqual(out['destination_season_id'], 'cold')
        self.assertNotEqual(out['range_inputs_sha256'], out['destination_range_inputs_sha256'])
        self.assertEqual(out['paths'], [])
        self.assertEqual(out['requests'][0]['status'], 'POLICY_UNMET')
        kw['destination_cells'] = (cell('a'), cell('b', habitat_support=None))
        self.assertEqual(movements(**kw)['requests'][0]['status'], 'UNKNOWN')

    def test_arrival_traversability_barrier_is_not_ignored(self):
        out = movements(destination_cells=(cell('a'), cell('b', traversable=False)),
            destination_edges=(edge('ab', 'a', 'b'),), destination_origins=(origin(),),
            destination_rule=rule(), destination_season_id='cold')
        self.assertEqual(out['paths'], [])
        self.assertEqual(out['requests'][0]['status'], 'POLICY_UNMET')

    def test_arrival_zero_conditional_footprint_forbids_transfer(self):
        out = movements(destination_cells=(cell('a'), cell('b')), destination_edges=(edge('ab', 'a', 'b'),),
            destination_origins=(origin(),), destination_rule=rule(conditional_occupied_fraction=F()),
            destination_season_id='cold')
        self.assertEqual(out['paths'], [])
        self.assertEqual(out['requests'][0]['status'], 'POLICY_UNMET')
        self.assertEqual(value(out['requests'][0]['transferred_expected_individuals']), 0)

    def test_arrival_invalid_positive_occupancy_density_forbids_transfer(self):
        for density in (F(), F(1, 100)):
            with self.subTest(density=density):
                out = movements(destination_cells=(cell('a'), cell('b')), destination_edges=(edge('ab', 'a', 'b'),),
                    destination_origins=(origin(),), destination_rule=rule(density_per_occupied_m2=density),
                    destination_season_id='cold')
                self.assertEqual(out['paths'], [])
                self.assertEqual(out['requests'][0]['status'], 'UNKNOWN')

    def test_arrival_unknown_density_is_not_invented_when_headroom_is_independent(self):
        out = movements(destination_cells=(cell('a'), cell('b')), destination_edges=(edge('ab', 'a', 'b'),),
            destination_origins=(origin(),), destination_rule=rule(density_per_occupied_m2=None),
            destination_season_id='cold')
        self.assertEqual(out['requests'][0]['status'], 'FULFILLED')
        self.assertEqual(value(out['requests'][0]['transferred_expected_individuals']), 5)

    def test_arrival_prescribed_total_conflict_blocks_all_transfer(self):
        out = movements(destination_cells=(cell('a'), cell('b')), destination_edges=(edge('ab', 'a', 'b'),),
            destination_origins=(origin(),), destination_rule=rule(), destination_season_id='cold',
            destination_prescribed_total=s.PrescribedTotal(F(200), E, K))
        self.assertEqual(out['status'], 'UNKNOWN')
        self.assertEqual(out['paths'], [])
        self.assertEqual(out['arrival_total_check']['status'], 'CONFLICT')
        self.assertEqual(value(out['arrival_total_check']['difference']), -180)

    def test_matching_arrival_prescribed_total_permits_independent_transfer(self):
        out = movements(destination_cells=(cell('a'), cell('b')), destination_edges=(edge('ab', 'a', 'b'),),
            destination_origins=(origin(),), destination_rule=rule(), destination_season_id='cold',
            destination_prescribed_total=s.PrescribedTotal(F(20), E, K))
        self.assertEqual(out['status'], 'MODELLED_FEASIBLE_ALLOCATION')
        self.assertEqual(value(out['requests'][0]['transferred_expected_individuals']), 5)

    def test_unresolved_prescribed_totals_do_not_create_conditional_flows(self):
        unknown = s.PrescribedTotal(F(20), E, 'UNKNOWN')
        departure = movements(prescribed_total=unknown)
        arrival = movements(destination_cells=(cell('a'), cell('b')), destination_edges=(edge('ab', 'a', 'b'),),
            destination_origins=(origin(),), destination_rule=rule(), destination_season_id='cold',
            destination_prescribed_total=unknown)
        for out in (departure, arrival):
            self.assertEqual(out['status'], 'UNKNOWN')
            self.assertEqual(out['paths'], [])

    def test_arrival_total_without_arrival_scenario_is_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            movements(destination_prescribed_total=s.PrescribedTotal(F(20), E, K))

    def test_arrival_scenario_requires_same_species_and_physical_support(self):
        kw = {'destination_cells': (cell('a'), cell('b')), 'destination_edges': (),
              'destination_origins': (origin(),), 'destination_rule': rule(), 'destination_season_id': 'cold'}
        kw['destination_cells'] = (cell('a'), cell('b', area_m2=F(21)))
        with self.assertRaisesRegex(ValueError, 'geometry'): movements(**kw)
        kw['destination_cells'] = (cell('a'), cell('b'))
        kw['destination_rule'] = rule(species_id='different')
        with self.assertRaisesRegex(ValueError, 'species'): movements(**kw)
        with self.assertRaises(ValueError): movements(destination_cells=(cell('a'), cell('b')))

    def test_explicit_priority_policy_can_leave_globally_feasible_request_unmet(self):
        cs = tuple(cell(k, area_m2=F(2)) for k in ('a', 'b', 'x', 'y', 'z', 'u', 'v'))
        es = (edge('ax', 'a', 'x'), edge('xz', 'x', 'z', capacity_expected_individuals=F(1)),
              edge('zu', 'z', 'u'), edge('ay', 'a', 'y', travel_cost=F(2)),
              edge('yu', 'y', 'u', travel_cost=F(2)), edge('bx', 'b', 'x'), edge('zv', 'z', 'v'))
        requests = (request('a-u', 'a', 'u', 1, 0), request('b-v', 'b', 'v', 1, 1))
        out = movements(cs, es, (origin('a'), origin('b')), requests=requests)
        self.assertEqual([r['status'] for r in out['requests']], ['FULFILLED', 'POLICY_UNMET'])
        # Independent feasible alternative: a-y-u costs4, b-x-z-v costs3;
        # every capacity >=1 and no edge is shared between these two paths.
        alternative = (('ay', 'yu'), ('bx', 'xz', 'zv'))
        em = {e.edge_id: e for e in es}
        for path in alternative:
            self.assertLessEqual(sum((F(em[k].travel_cost) for k in path), F()), 5)
            self.assertTrue(all(em[k].capacity_expected_individuals >= 1 for k in path))
        self.assertFalse(set(alternative[0]) & set(alternative[1]))
        self.assertIn('not a global infeasibility', out['policy'])

    def test_request_tuple_order_does_not_override_explicit_priority(self):
        requests = (request('first', amount=4, priority=2), request('last', amount=9, priority=8))
        self.assertEqual(movements(requests=requests), movements(requests=tuple(reversed(requests))))


class BoundaryTests(unittest.TestCase):
    def test_numeric_booleans_nonfinite_negative_and_fraction_overflow_reject(self):
        for v in (True, float('nan'), float('inf'), -1, F(1, 10**2000)):
            with self.subTest(v=str(v)[:30]), self.assertRaises(ValueError): cell('a', area_m2=v)
        for v in (-.1, 1.1, True):
            with self.subTest(v=v), self.assertRaises(ValueError): cell('a', habitat_support=v)

    def test_explicit_units_statuses_barriers_and_modes_are_required(self):
        for changes in ({'travel_unit': 'distance'}, {'travel_unit': 'RESISTANCE:'},
                        {'source_status': 'truthy'}, {'movement_mode': 'AUTO'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): rule(**changes)
        with self.assertRaises(ValueError): edge('x', 'a', 'b', enabled=1)
        with self.assertRaises(ValueError): cell('a', traversable='yes')

    def test_graph_duplicate_endpoints_and_self_edges_reject(self):
        with self.assertRaises(ValueError): evaluate(cells=(cell('a'), cell('a')))
        with self.assertRaises(ValueError): evaluate(edges=(edge('ab', 'a', 'missing'),))
        with self.assertRaises(ValueError): evaluate(edges=(edge('ab', 'a', 'b'), edge('ab', 'a', 'b')))
        with self.assertRaises(ValueError): edge('self', 'a', 'a')
        with self.assertRaises(ValueError): evaluate(origins=(origin(), origin()))

    def test_request_priority_identity_and_complete_capacity_guards(self):
        with self.assertRaises(ValueError): movements(requests=(request('a'), request('b')))
        with self.assertRaises(ValueError): movements(requests=(request('same'), request('same', priority=1)))
        with self.assertRaises(ValueError): movements(capacity={'b': 5})
        with self.assertRaises(ValueError): request(a='a', b='a')
        with self.assertRaises(ValueError): request(priority=True)

    def test_json_safety_and_no_mutation(self):
        cs = (cell('a'), cell('b')); es = (edge('ab', 'a', 'b'),)
        before = s.plain({'cells': cs, 'edges': es})
        out = movements(cs, es)
        self.assertEqual(json.loads(json.dumps(out, allow_nan=False)), out)
        self.assertEqual(before, s.plain({'cells': cs, 'edges': es}))


if __name__ == '__main__':
    unittest.main()
