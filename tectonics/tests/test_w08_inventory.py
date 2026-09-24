"""Whole-stock W08 conservation and shared-row transition controls."""
from concurrent.futures import CancelledError
import gc
import json
from threading import Event
import unittest

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.magmatic_transfer import MagmaticExhaustionError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.subduction_materials import RetirementExhaustionError, SECTION_POLICY
from atlas_tectonics.w08_inventory import (
    W08Inventory, advance_magmatic, advance_retirement)


def stock(**kwargs):
    values = dict(node_ids=('a-accretion', 'b-crust', 'c-deep', 'd-export',
                           'e-intrusion', 'f-melt', 'g-reservoir', 'h-mantle'),
        node_kinds=('accretion', 'crust', 'deep-storage', 'export',
                    'intrusion', 'source-melt', 'reservoir', 'mantle'),
        component_ids=('A', 'B'), component_mass_kg=[
            [1, 1], [30, 90], [2, 3], [0, 0], [0, 0], [0, 10], [2, 0], [160, 240]],
        enthalpy_j=[-3, -600, 20, 0, 0, 100, 0, 2000],
        source_id='shared-initial-stock', enthalpy_source='signed-synthetic-J',
        formation_time_s=[-100, -10, -100, -100, -100, -4, -5, -20],
        origin_ids=tuple('origin-'+str(i) for i in range(8)))
    values.update(kwargs)
    return W08Inventory(**values)


def retirement_parameters(**kwargs):
    values = dict(epoch_id='synthetic-seconds', density_kg_m3=[2., 4.],
        thickness_m=[3., 5.], material_velocity_m_s=[[.5, 3, 4], [.25, -2, 1]],
        boundary_velocity_m_s=np.zeros((2, 3)), outward_normal=[1., 0., 0.],
        strike_direction=[0., 1., 0.], section_width_m=2., frame_id='synthetic-xyz',
        section_policy=SECTION_POLICY, destination_fractions=[[.25, .5, .25], [.1, .2, .7]],
        flux_source='prescribed-section-flow', partition_source='supplied-three-way-shares')
    values.update(kwargs)
    return values


class W08InventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = ExecutionContext('scipy')

    @classmethod
    def tearDownClass(cls):
        cls.context.close()

    def magma(self, initial, duration, **kwargs):
        rates = np.zeros((3, 3)); rates[1, 2] = 1.; rates[2, 0] = 1.
        return advance_magmatic(initial, ('d-export', 'f-melt', 'g-reservoir'),
            rates, duration, source_id='prescribed-magma', context=self.context, **kwargs)

    def retire(self, initial, duration, **kwargs):
        return advance_retirement(initial, ('b-crust', 'h-mantle'),
            ('a-accretion', 'c-deep', 'd-export'), duration,
            source_id='prescribed-retirement', parameters=retirement_parameters(), **kwargs)

    def test_immutable_snapshot_identity_and_descriptor_roundtrip(self):
        initial = stock()
        for array in (initial.component_mass_kg, initial.enthalpy_j,
                      initial.mass_kg, initial.formation_time_s):
            with self.assertRaises(ValueError):
                array.setflags(write=True)
        view = initial.component_mass_kg
        view.shape = (16,)
        self.assertEqual(initial.component_mass_kg.shape, (8, 2))
        descriptor = json.loads(json.dumps(initial.descriptor(), allow_nan=False))
        descriptor.pop('schema')
        for name in ('node_ids', 'node_kinds', 'component_ids', 'origin_ids'):
            descriptor[name] = tuple(descriptor[name])
        restored = W08Inventory(component_mass_kg=initial.component_mass_kg,
            enthalpy_j=initial.enthalpy_j, **descriptor)
        self.assertEqual(initial.inventory_id, restored.inventory_id)
        descriptor['formation_time_s'][0] -= 1
        self.assertNotEqual(initial.inventory_id, W08Inventory(
            component_mass_kg=initial.component_mass_kg, enthalpy_j=initial.enthalpy_j,
            **descriptor).inventory_id)
        self.assertGreater(initial.nbytes, initial.component_mass_kg.nbytes)

    def test_invalid_shapes_nonfinite_stocks_metadata_and_zero_mass_enthalpy(self):
        for override in (dict(component_mass_kg=np.zeros((8, 1))),
                dict(enthalpy_j=[0]*7), dict(formation_time_s=[0]*7),
                dict(formation_time_s=[1]*8), dict(origin_ids=('unknown',)),
                dict(enthalpy_j=[-3, -600, 20, 1, 0, 100, 0, 2000]),
                dict(component_mass_kg=np.full((8, 2), np.nan)),
                dict(component_mass_kg=np.full((8, 2), -1)),
                dict(component_ids=('B', 'A')), dict(time_s=True),
                dict(node_kinds=('reservoir',)*7+('unclassified',))):
            with self.subTest(override=tuple(override)), self.assertRaises(TectonicsError):
                stock(**override)

    def test_retime_cessation_preserves_all_stocks_and_source_metadata(self):
        initial = stock()
        later = initial.retime(100.)
        for name in ('component_mass_kg', 'enthalpy_j', 'formation_time_s'):
            np.testing.assert_array_equal(getattr(initial, name), getattr(later, name))
        self.assertEqual(initial.origin_ids, later.origin_ids)
        self.assertEqual(initial.source_id, later.source_id)
        self.assertEqual(later.retime(101., source_id='cessation-event').source_id, 'cessation-event')
        with self.assertRaises(TectonicsError): later.retime(99.)

    def test_magmatic_maps_exact_rows_retains_unselected_and_books_heat_once(self):
        initial = stock()
        final, receipt = self.magma(initial, 3., heat_w=[0., 0., 4.])
        unaffected = [0, 1, 2, 4, 7]
        np.testing.assert_array_equal(final.component_mass_kg[unaffected],
                                      initial.component_mass_kg[unaffected])
        np.testing.assert_array_equal(final.enthalpy_j[unaffected], initial.enthalpy_j[unaffected])
        np.testing.assert_allclose(final.mass_kg[[3, 5, 6]], [3, 7, 2], atol=2e-14, rtol=0)
        np.testing.assert_allclose(final.component_mass_kg.sum(axis=0),
                                   initial.component_mass_kg.sum(axis=0), atol=2e-13, rtol=0)
        self.assertAlmostEqual(float(final.enthalpy_j.sum()-initial.enthalpy_j.sum()), 12., places=11)
        self.assertEqual(receipt['external_heat_total_j'], 12.)
        self.assertEqual(receipt['edge_ids'], [['f-melt', 'g-reservoir'], ['g-reservoir', 'd-export']])
        self.assertEqual(receipt['inventory_id'], final.inventory_id)
        json.dumps(receipt, allow_nan=False)

    def test_magmatic_finite_exhaustion_and_empty_pass_through_refusal(self):
        initial = stock()
        selected = ('e-intrusion', 'f-melt')
        rates = [[0., 0.], [2., 0.]]
        final, receipt = advance_magmatic(initial, selected, rates, 5.,
            source_id='finite-feed', context=self.context)
        self.assertEqual(final.mass_kg[5], 0.)
        self.assertEqual(final.mass_kg[4], 10.)
        self.assertEqual(receipt['exhausted_node_ids'], ['f-melt'])
        with self.assertRaises(MagmaticExhaustionError):
            advance_magmatic(initial, selected, rates, 5.1, source_id='too-long', context=self.context)
        with self.assertRaises(TectonicsError):
            advance_magmatic(final, selected, rates, 1., source_id='empty', context=self.context)
        solid = stock(node_kinds=initial.node_kinds[:5]+('source-solid',)+initial.node_kinds[6:])
        with self.assertRaises(TectonicsError):
            advance_magmatic(solid, selected, rates, 1., source_id='no-implicit-melting', context=self.context)

    def test_retirement_simultaneous_destinations_existing_stocks_and_signed_heat(self):
        initial = stock()
        final, receipt = self.retire(initial, 10.)
        np.testing.assert_array_equal(final.mass_kg[[1, 7]], [60., 300.])
        np.testing.assert_array_equal(final.mass_kg[[0, 2, 3]], [27., 55., 85.])
        np.testing.assert_array_equal(final.enthalpy_j[[0, 2, 3]], [-28., -30., 275.])
        np.testing.assert_array_equal(final.component_mass_kg[[4, 5, 6]],
                                      initial.component_mass_kg[[4, 5, 6]])
        np.testing.assert_array_equal(final.component_mass_kg.sum(axis=0), initial.component_mass_kg.sum(axis=0))
        self.assertEqual(float(final.enthalpy_j.sum()), float(initial.enthalpy_j.sum()))
        np.testing.assert_array_equal(receipt['transferred_mass_kg'], [[15, 10], [30, 20], [15, 70]])
        self.assertEqual(receipt['external_heat_total_j'], 0.)

    def test_retirement_carries_source_owned_origin_and_formation(self):
        initial = stock()
        final, receipt = self.retire(initial, 2.)
        cohorts = receipt['source_cohorts']
        self.assertEqual([c['origin_id'] for c in cohorts], ['origin-1', 'origin-7'])
        self.assertEqual([c['formation_time_s'] for c in cohorts], [-10., -20.])
        self.assertEqual(final.origin_ids, initial.origin_ids)
        np.testing.assert_array_equal(final.formation_time_s, initial.formation_time_s)

    def test_retirement_exhaustion_refusal_has_no_partial_spending(self):
        initial = stock()
        final, receipt = self.retire(initial, 20.)
        self.assertEqual(final.mass_kg[1], 0.)
        self.assertEqual(final.enthalpy_j[1], 0.)
        self.assertEqual(receipt['exhausted_node_ids'], ['b-crust'])
        self.assertEqual(receipt['exhaustion_duration_s'], 20.)
        with self.assertRaises(RetirementExhaustionError): self.retire(initial, 20.1)
        with self.assertRaises(RetirementExhaustionError): self.retire(final, 1.)
        self.assertEqual(initial.mass_kg[1], 120.)

    def test_selection_destination_types_and_complete_parameters_are_explicit(self):
        initial = stock()
        for selected in (('h-mantle', 'b-crust'), ('absent',), ('b-crust', 'b-crust')):
            with self.assertRaises(TectonicsError):
                advance_retirement(initial, selected, ('a-accretion', 'c-deep', 'd-export'),
                    1., source_id='invalid', parameters=retirement_parameters())
        for destinations in (('c-deep', 'a-accretion', 'd-export'),
                             ('a-accretion', 'c-deep', 'e-intrusion')):
            with self.assertRaises(TectonicsError):
                advance_retirement(initial, ('b-crust', 'h-mantle'), destinations,
                    1., source_id='invalid', parameters=retirement_parameters())
        values = retirement_parameters(); values.pop('flux_source')
        with self.assertRaises(TectonicsError):
            advance_retirement(initial, ('b-crust', 'h-mantle'),
                ('a-accretion', 'c-deep', 'd-export'), 1., source_id='invalid', parameters=values)

    def test_segmented_transitions_and_cessation_match_finite_stock_accounts(self):
        initial = stock()
        once, _ = self.retire(initial, 10.)
        split, _ = self.retire(initial, 4.)
        split, _ = self.retire(split, 6.)
        np.testing.assert_allclose(once.component_mass_kg, split.component_mass_kg, atol=2e-13, rtol=0)
        np.testing.assert_allclose(once.enthalpy_j, split.enthalpy_j, atol=2e-13, rtol=0)
        mixed, _ = self.magma(split, 3.)
        quiet = mixed.retime(50.)
        np.testing.assert_array_equal(mixed.component_mass_kg, quiet.component_mass_kg)
        np.testing.assert_allclose(quiet.component_mass_kg.sum(axis=0), initial.component_mass_kg.sum(axis=0),
                                   atol=2e-13, rtol=0)
        self.assertEqual(quiet.time_s, 50.)

    def test_cancellation_and_parent_budget_release(self):
        cancelled = Event(); cancelled.set()
        with self.assertRaises(CancelledError): stock(cancel=cancelled)
        initial = stock()
        with self.assertRaises(CancelledError): self.retire(initial, 1., cancel=cancelled)
        with self.assertRaises(CancelledError): self.magma(initial, 1., cancel=cancelled)
        tiny = WorkBudget(1024)
        with self.assertRaises(MemoryLimitError): stock(budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)
        owner = WorkBudget(2*1024**2)
        final, _ = self.retire(initial, 1., budget=owner)
        self.assertGreater(owner.reserved_bytes, 0)
        self.assertLessEqual(owner.peak_reserved_bytes, owner.max_bytes)
        del final
        gc.collect()
        self.assertEqual(owner.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
