"""Independent native graph, ownership and disjoint runoff tests."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from r3_bindings import capture
import shoreline
import shoreline_network as net


def state(bed, *, water=None, solid=None, area=None, shape=None):
    n = len(bed)
    return capture.CaptureState(shape or [1, n], area or [1.] * n, bed, [0.] * n,
                                water or [0.] * n, solid or [0.] * n)


def network(value, *, runoff=0., outlets=None, connectivity=4, dx=1., dy=1., **kwargs):
    return net.build_network(value, dx_m=dx, dy_m=dy, external_outlets=[] if outlets is None else outlets,
                             runoff_m_year=runoff, connectivity=connectivity, **kwargs)


class ShorelineNetworkTests(unittest.TestCase):
    def test_zero_runoff_empty_pit_stays_dry_without_invented_lake(self):
        s = state([2., 0., 2.])
        r = network(s)
        self.assertEqual(r['pools'], [])
        self.assertEqual(r['zero_time_events'], [])
        self.assertEqual(r['dry_no_flow_terminals'], [1])
        self.assertEqual(r['channel_kwargs']['receivers'], [1, -1, 1])
        self.assertEqual(s.liquid_m3, (0., 0., 0.))

    def test_positive_runoff_activates_actual_zero_depth_bottom_only(self):
        s = state([2., 1., 0.])
        r = network(s, runoff=1.)
        g = r['channel_kwargs']
        self.assertEqual(g['receivers'], [1, 2, -1])
        self.assertEqual(g['contributing_area_m2'], [1., 2., 3.])
        self.assertEqual(g['incipient_pool_cells'], [2])
        self.assertEqual(g['pool_stages_m'], {'pool_0002': 0.})
        pool = r['pools'][0]
        self.assertEqual(pool['actual_liquid_inflow_m3_year'], 3.)
        self.assertEqual(pool['liquid_m3'], 0.)
        self.assertEqual(pool['suspended_solid_m3'], 0.)
        self.assertEqual(pool['next_native_wetting_stage_m'], 1.)
        self.assertEqual(r['zero_time_events'][0]['time_offset_years'], 0.)
        self.assertEqual(s.liquid_m3, (0., 0., 0.))

    def test_true_flat_bottom_is_one_incipient_zero_depth_component(self):
        r = network(state([1., 0., 0., 1.]), runoff=[1., 0., 0., 0.])
        self.assertEqual(r['channel_kwargs']['incipient_pool_cells'], [1, 2])
        self.assertEqual(r['pools'][0]['cell_indices'], [1, 2])
        self.assertEqual(r['pools'][0]['actual_liquid_inflow_m3_year'], 1.)
        self.assertEqual(r['pools'][0]['native_contributing_area_m2'], 4.)

    def test_draining_flat_with_positive_strict_terminal_does_not_become_lake(self):
        with self.assertRaisesRegex(net.NetworkError, 'draining flat') as rejected:
            network(state([0., 1., 1.]), runoff=[0., 0., 1.], outlets=[0])
        self.assertEqual(rejected.exception.context['flat_cells'], [1, 2])
        self.assertEqual(rejected.exception.context['lower_neighbours'], [0])

    def test_external_outlet_stops_raw_graph_and_exports_once(self):
        r = network(state([2., 1., 0.]), runoff=[1., 2., 3.], outlets=[2])
        self.assertEqual(r['pools'], [])
        self.assertEqual(r['channel_kwargs']['incipient_pool_cells'], [])
        self.assertEqual(r['liquid_rates']['external_delivery_m3_year'], 6.)
        self.assertEqual(r['liquid_rates']['routing_residual_m3_year'], 0.)
        self.assertTrue(all(d['kind'] == 'EXTERNAL' and d['cell_index'] == 2 for d in r['destinations']))

    def test_all_native_tributaries_contribute_area_once(self):
        r = network(state([4., 3., 4., 3., 2., 3., 4., 3., 4.], shape=[3, 3]), runoff=1.)
        expected = [4, 4, 4, 4, -1, 4, 4, 4, 4]
        self.assertEqual(r['channel_kwargs']['receivers'], expected)
        self.assertEqual(r['channel_kwargs']['contributing_area_m2'][4], 9.)
        self.assertEqual(r['pools'][0]['catchment_cell_indices'], list(range(9)))
        self.assertEqual(r['pools'][0]['actual_liquid_inflow_m3_year'], 9.)
        self.assertEqual(r['native_area_ledger']['source_area_m2'], 9.)
        self.assertEqual(r['native_area_ledger']['terminal_area_m2'], 9.)

    def test_retained_d8_tie_prefers_lower_native_receiver_id(self):
        r = network(state([0., 1., 0.]), outlets=[0, 2])
        self.assertEqual(r['raw_receivers'], [-1, 0, -1])

    def test_rectangular_spacing_uses_physical_slope_not_height_drop(self):
        r = network(state([0., 2., 1., 3.], shape=[2, 2]), runoff=1., dx=4., dy=1.)
        self.assertEqual(r['raw_receivers'], [-1, 0, 0, 1])
        self.assertEqual(r['raw_link_lengths_m'], [0., 4., 1., 1.])
        self.assertEqual(r['pools'][0]['native_contributing_area_m2'], 4.)

    def test_pool_and_dry_runoff_and_inlet_are_disjoint_once(self):
        s = state([3., 0., 4.], water=[0., 1., 0.], area=[2., 1., 3.])
        r = network(s, runoff=[2., 5., 7.], incoming_liquid_m3_year=[1., 2., 3.])
        pool = r['pools'][0]
        self.assertEqual(pool['local_runoff_m3_year'], 5.)
        self.assertEqual(pool['explicit_liquid_inlet_m3_year'], 2.)
        self.assertEqual(pool['dry_tributary_liquid_m3_year'], 29.)
        self.assertEqual(pool['actual_liquid_inflow_m3_year'], 36.)
        self.assertEqual(pool['native_contributing_area_m2'], 6.)
        self.assertEqual(r['liquid_rates']['source_total_m3_year'], 36.)
        self.assertEqual(r['liquid_rates']['routing_residual_m3_year'], 0.)

    def test_channel_kwargs_deliver_incipient_liquid_without_terminal_deposit(self):
        s = state([2., 1., 0.])
        r = network(s, runoff=1.)
        trial, report = shoreline.channel_trial(s, **r['channel_kwargs'], runoff_m_year=1.,
            sediment_k_per_year=0., rock_k_per_year=0., cover_scale_m=1., settling_m_year=0., dt_years=.5)
        self.assertEqual(trial, s)
        self.assertEqual(report['pool_liquid_transfer_m3'], 1.)
        self.assertEqual(report['pool_local_runoff_m3'], .5)
        self.assertEqual(report['pool_suspended_transfer_m3'], 0.)
        self.assertEqual(report['dry_deposition_solid_m3'], [0., 0., 0.])
        self.assertEqual(report['liquid_volume_residual_m3'], 0.)

    def test_channel_kwargs_pool_local_runoff_not_forwarded_twice(self):
        s = state([3., 0., 4.], water=[0., 1., 0.])
        r = network(s, runoff=[2., 5., 7.])
        _, report = shoreline.channel_trial(s, **r['channel_kwargs'], runoff_m_year=[2., 5., 7.],
            sediment_k_per_year=0., rock_k_per_year=0., cover_scale_m=1., settling_m_year=0., dt_years=1.)
        self.assertEqual(report['pool_liquid_transfer_m3'], 9.)
        self.assertEqual(report['pool_local_runoff_m3'], 5.)
        self.assertEqual(report['liquid_volume_residual_m3'], 0.)

    def test_diagonal_channel_delivery_does_not_merge_four_connected_pools(self):
        s = state([0., 3., 3., 0.], shape=[2, 2], water=[1., 0., 0., 1.])
        four = network(s, connectivity=4)
        eight = network(s, connectivity=8)
        self.assertEqual([p['wet_cell_indices'] for p in four['pools']], [[0], [3]])
        self.assertEqual([p['wet_cell_indices'] for p in eight['pools']], [[0, 3]])
        self.assertEqual(four['raw_receivers'], [-1, 0, 0, -1])

    def test_actual_stage_inverse_uses_exact_area_weighted_volume(self):
        s = state([-2., -1.], water=[3., 1.5], solid=[1., .5], area=[2., 2.])
        r = network(s)
        pool = r['pools'][0]
        self.assertEqual(pool['stage_m'], 0.)
        self.assertEqual(pool['exact_stage_m'], {'numerator': 0, 'denominator': 1})
        self.assertEqual(pool['solid_volume_fraction'], .25)

    def test_unrouted_nonlevel_or_unmixed_component_rejected(self):
        for s in (state([0., 0.], water=[1., 2.]),
                  state([0., 0.], water=[.75, .5], solid=[.25, .5])):
            with self.assertRaisesRegex(ValueError, 'conservation'):
                network(s)

    def test_exact_stage_margin_is_candidate_not_automatic_pool_member(self):
        r = network(state([0., 1.], water=[1., 0.]), runoff=[1., 0.])
        self.assertEqual(r['channel_kwargs']['pool_owner'], ['pool_0000', None])
        self.assertEqual(r['channel_kwargs']['incipient_pool_cells'], [])
        candidates = r['zero_depth_margin_candidates']
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['cell_index'], 1)
        self.assertTrue(candidates[0]['exact_stage_equals_bed'])
        self.assertIn('SETTLING', candidates[0]['activation'])

    def test_unowned_cell_below_existing_pool_surface_is_not_silently_absorbed(self):
        with self.assertRaisesRegex(net.NetworkError, 'below current pool stage'):
            network(state([0., .5], water=[1., 0.]))

    def test_immediate_external_spill_has_exact_saddle_receiver(self):
        r = network(state([5., 0., 3.], water=[0., 1., 0.]), outlets=[0, 2])
        spill = r['pools'][0]['spill']
        self.assertEqual(spill['spill_m'], 3.)
        self.assertEqual(spill['edge_cells'], [1, 2])
        self.assertEqual(spill['receiver_cell'], 2)
        self.assertEqual(spill['kind'], 'IMMEDIATE_EXTERNAL')
        self.assertTrue(spill['supports_current_driver'])

    def test_dry_corridor_spill_is_explicit_not_an_invented_external_export(self):
        r = network(state([5., 0., 2., 1., 3.], water=[0., 1., 0., 0., 0.]), outlets=[4])
        spill = r['pools'][0]['spill']
        self.assertEqual(spill['spill_m'], 2.)
        self.assertEqual(spill['receiver_cell'], 3)
        self.assertEqual(spill['kind'], 'DRY_CORRIDOR_REQUIRES_CHANNEL_ROUTING')
        self.assertFalse(spill['supports_current_driver'])
        self.assertEqual(len(r['unsupported_spill_routes']), 1)
        self.assertFalse(r['unsupported_spill_routes'][0]['at_exact_spill'])

    def test_full_dry_corridor_spill_identifies_current_limit_and_inflow(self):
        r = network(state([5., 0., 2., 1., 3.], water=[0., 2., 0., 0., 0.]), outlets=[4],
                    incoming_liquid_m3_year=[0., 1., 0., 0., 0.])
        limit = r['unsupported_spill_routes'][0]
        self.assertTrue(limit['at_exact_spill'])
        self.assertTrue(limit['actual_positive_liquid_input'])
        self.assertEqual(r['liquid_rates']['external_delivery_m3_year'], 0.)

    def test_native_area_partition_independent_path_walks_on_random_dry_graphs(self):
        rng = random.Random(202603)
        for _ in range(15):
            bed = [rng.random()*10 for _ in range(20)]
            area = [1.+rng.random() for _ in bed]
            r = network(state(bed, area=area, shape=[4, 5]), outlets=[0, 19])
            expected = [[] for _ in bed]
            for source in range(len(bed)):
                i = source
                seen = set()
                while True:
                    self.assertNotIn(i, seen)
                    seen.add(i)
                    expected[i].append(source)
                    j = r['channel_kwargs']['receivers'][i]
                    if j < 0:
                        self.assertEqual(r['destination_cell_indices'][source], i)
                        break
                    self.assertGreater(bed[i], bed[j])
                    i = j
            for i, sources in enumerate(expected):
                self.assertEqual(r['channel_kwargs']['contributing_area_m2'][i], math.fsum(area[j] for j in sources))
                self.assertEqual(int(r['catchment_membership_hex'][i], 16), sum(1 << j for j in sources))

    def test_source_state_and_forcing_preserved_and_output_finite_json(self):
        s = state([3., 0., 4.], water=[0., 1., 0.])
        forcing = [1., 2., 3.]
        before = deepcopy(s), list(forcing)
        a = network(s, runoff=forcing)
        b = network(s, runoff=forcing)
        self.assertEqual(a, b)
        self.assertEqual((s, forcing), before)
        json.dumps(a, allow_nan=False)
        self.assertFalse(a['assumptions']['phase_state_mutated'])
        self.assertFalse(a['assumptions']['production_authorised'])

    def test_invalid_spacing_connectivity_and_external_ownership_rejected(self):
        for bad in (True, 0., -1., float('inf'), float('nan'), 10**1000):
            with self.subTest(bad=str(bad)[:16]), self.assertRaises(ValueError):
                network(state([0.]), dx=bad)
        with self.assertRaises(ValueError):
            network(state([0.]), connectivity=True)
        with self.assertRaisesRegex(net.NetworkError, 'native edge'):
            network(state([0.]*9, shape=[3, 3]), outlets=[4])
        with self.assertRaisesRegex(net.NetworkError, 'disjoint'):
            network(state([0.], water=[1.]), outlets=[0])

    def test_asserted_margin_rebuilds_receivers_catchments_and_runoff_ownership(self):
        s = state([0., 1., 2.], water=[1., 0., 0.])
        before = network(s, runoff=1.)
        self.assertEqual(before['channel_kwargs']['receivers'], [-1, 0, 1])
        after = network(s, runoff=1., activated_margins={1: 'pool_0000'})
        g = after['channel_kwargs']
        self.assertEqual(g['receivers'], [-1, -1, 1])
        self.assertEqual(g['contributing_area_m2'], [1., 2., 1.])
        self.assertEqual(g['pool_owner'], ['pool_0000', 'pool_0000', None])
        self.assertEqual(g['incipient_pool_cells'], [1])
        self.assertEqual(after['pools'][0]['local_runoff_m3_year'], 2.)
        self.assertEqual(after['pools'][0]['dry_tributary_liquid_m3_year'], 1.)
        self.assertEqual(after['pools'][0]['catchment_cell_indices'], [0, 1, 2])
        self.assertEqual(after['pools'][0]['wet_cell_indices'], [0])
        self.assertIn('NOT_PROVEN', after['asserted_margin_activations'][0]['status'])
        self.assertEqual(s.liquid_m3, (1., 0., 0.))
        _, report = shoreline.channel_trial(s, **g, runoff_m_year=1., sediment_k_per_year=0.,
            rock_k_per_year=0., cover_scale_m=1., settling_m_year=0., dt_years=.1)
        self.assertAlmostEqual(report['pool_liquid_transfer_m3'], .1)
        self.assertAlmostEqual(report['pool_local_runoff_m3'], .2)

    def test_margin_assertion_cannot_choose_between_equal_stage_disconnected_pools(self):
        s = state([0., 1., 0.], water=[1., 0., 1.])
        before = network(s, runoff=0.)
        self.assertEqual(len(before['zero_depth_margin_candidates']), 2)
        with self.assertRaisesRegex(net.NetworkError, 'unambiguous'):
            network(s, runoff=1., activated_margins={1: 'pool_0000'})

    def test_invalid_margin_map_cannot_activate_wrong_or_remote_cells(self):
        s = state([0., 1., 2.], water=[1., 0., 0.])
        for assertion in ({True: 'pool_0000'}, {0: 'pool_0000'}, {2: 'pool_0000'},
                          {1: 'pool_9999'}, {1: 0}, [], {1: 'pool_0000', 2: 'pool_0000'}):
            with self.subTest(assertion=assertion), self.assertRaises(ValueError):
                network(s, runoff=1., activated_margins=assertion)

    def test_sub_ulp_exact_freeboard_cannot_be_activated_as_native_contact(self):
        s = state([0., 1.], water=[.7, 0.], solid=[.3, 0.])
        before = network(s, runoff=1.)
        margin = before['zero_depth_margin_candidates'][0]
        self.assertEqual(margin['stage_m'], 1.)
        self.assertFalse(margin['exact_stage_equals_bed'])
        self.assertEqual(Fraction(**margin['exact_freeboard_m']), Fraction(1, 2**54))
        with self.assertRaisesRegex(net.NetworkError, 'contact is not exact'):
            network(s, runoff=1., activated_margins={1: 'pool_0000'})

    def test_external_suspended_inlet_requires_its_own_carrier(self):
        with self.assertRaisesRegex(net.NetworkError, 'incoming liquid carrier'):
            network(state([0.]), runoff=1., incoming_solid_m3_year=[1.])

    def test_frozen_dependency_rechecked_after_graph_build(self):
        original = Path.read_bytes
        reads = 0
        def changed(path):
            nonlocal reads
            value = original(path)
            if path.name == 'water.py':
                reads += 1
                if reads == 2:
                    return value+b'\n# mocked change'
            return value
        with patch.object(Path, 'read_bytes', changed), self.assertRaisesRegex(ValueError, 'changed during'):
            network(state([0.]), runoff=1.)


if __name__ == '__main__':
    unittest.main()
