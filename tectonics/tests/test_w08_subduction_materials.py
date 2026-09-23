"""Independent finite retirement, section-flux and extensive-stock controls."""
from concurrent.futures import CancelledError
from threading import Event
import unittest
import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.materials import MaterialCohort
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.subduction_materials import (SubductionInventory,
    PreparedSubductionRetirement, RetirementExhaustionError, DESTINATIONS, SECTION_POLICY)


def inventory(**kwargs):
    arguments = dict(cohorts=(MaterialCohort('a-crust', 'basalt', 'oceanic-crust', -10.),
                              MaterialCohort('b-mantle', 'peridotite', 'oceanic-mantle', None)),
        layer_kinds=('crust', 'mantle'), mass_kg=[120., 400.], component_ids=('A', 'B'),
        component_mass_kg=[[30., 90.], [160., 240.]], enthalpy_j=[-600., 2000.],
        time_s=0., epoch_id='synthetic-seconds', source_id='finite-source-material',
        enthalpy_source='synthetic-signed-reference-enthalpy')
    arguments.update(kwargs)
    return SubductionInventory(**arguments)


def prepare(initial=None, **kwargs):
    arguments = dict(density_kg_m3=[2., 4.], thickness_m=[3., 5.],
        material_velocity_m_s=[[.5, 3., 4.], [.25, -2., 1.]],
        boundary_velocity_m_s=np.zeros((2, 3)), outward_normal=[1., 0., 0.],
        strike_direction=[0., 1., 0.], section_width_m=2., frame_id='synthetic-xyz-metres',
        section_policy=SECTION_POLICY, destination_kinds=DESTINATIONS,
        destination_ids=('accreted-wedge', 'deep-slab', 'external-export'),
        destination_fractions=[[.25, .5, .25], [.1, .2, .7]],
        flux_source='prescribed-constant-section-flow', partition_source='prescribed-finite-partition',
        source_id='synthetic-retirement-plan')
    arguments.update(kwargs)
    return PreparedSubductionRetirement(inventory() if initial is None else initial, **arguments)


class SubductionMaterialTests(unittest.TestCase):
    def test_boundary_relative_per_strike_flux_and_declared_width(self):
        with prepare() as plan:
            np.testing.assert_array_equal(plan.normal_velocity_m_s, [.5, .25])
            np.testing.assert_array_equal(plan.mass_flux_kg_m_s, [3., 5.])
            np.testing.assert_array_equal(plan.mass_flux_kg_s, [6., 10.])
            np.testing.assert_array_equal(plan.along_strike_velocity_m_s, [3., -2.])
            np.testing.assert_array_equal(plan.tangential_velocity_m_s, [[0., 3., 4.], [0., -2., 1.]])
        with prepare(section_width_m=5.) as wider:
            np.testing.assert_array_equal(wider.mass_flux_kg_s, [15., 25.])

    def test_exact_mass_component_and_signed_heat_accounts_by_cohort(self):
        with prepare() as plan:
            result = plan.evaluate(10.)
            np.testing.assert_array_equal(result.retired_mass_kg, [60., 100.])
            np.testing.assert_array_equal(result.retired_component_mass_kg, [[15., 45.], [40., 60.]])
            np.testing.assert_array_equal(result.retired_enthalpy_j, [-300., 500.])
            np.testing.assert_array_equal(result.remaining.mass_kg, [60., 300.])
            np.testing.assert_array_equal(result.remaining.enthalpy_j, [-300., 1500.])
            np.testing.assert_array_equal(result.destination_mass_kg, [[15., 10.], [30., 20.], [15., 70.]])
            np.testing.assert_array_equal(result.destination_enthalpy_j, [[-75., 50.], [-150., 100.], [-75., 350.]])
            np.testing.assert_allclose(result.destination_component_mass_kg.sum(axis=2),
                                       result.destination_mass_kg, rtol=1e-15)
            np.testing.assert_allclose(result.account_residuals, 0., atol=2e-14)
            self.assertEqual(result.remaining.cohorts, plan.inventory.cohorts)
            self.assertEqual(result.remaining.layer_kinds, ('crust', 'mantle'))
            self.assertEqual(result.remaining.enthalpy_source, plan.inventory.enthalpy_source)
            self.assertEqual(result.remaining.time_s, 10.)

    def test_first_exact_exhaustion_and_unsupported_continuation_refusal(self):
        with prepare() as plan:
            self.assertEqual(plan.cohort_exhaustion_durations_s, (20., 40.))
            self.assertEqual(plan.exhaustion_duration_s, 20.)
            self.assertEqual(plan.exhausted_cohort_ids, ('a-crust',))
            end = plan.evaluate(20.)
            np.testing.assert_array_equal(end.remaining.mass_kg, [0., 200.])
            np.testing.assert_array_equal(end.remaining.component_mass_kg[0], [0., 0.])
            self.assertEqual(end.remaining.enthalpy_j[0], 0.)
            with self.assertRaises(RetirementExhaustionError) as failure:
                plan.evaluate(np.nextafter(20., np.inf))
            self.assertEqual(failure.exception.exhaustion_duration_s, 20.)
            self.assertEqual(failure.exception.exhausted_cohort_ids, ('a-crust',))
            self.assertEqual(plan.evaluate(20.).result_id, end.result_id)
            np.testing.assert_array_equal(plan.inventory.mass_kg, [120., 400.])

    def test_near_exhaustion_preserves_small_remaining_composition(self):
        with prepare() as plan:
            result = plan.evaluate(np.nextafter(20., 0.))
            self.assertGreater(result.remaining.mass_kg[0], 0.)
            np.testing.assert_allclose(result.remaining.component_mass_kg[0]/result.remaining.mass_kg[0], [.25, .75], rtol=1e-15)
            self.assertAlmostEqual(result.remaining.enthalpy_j[0]/result.remaining.mass_kg[0], -5.)

    def test_destination_order_does_not_change_allocation_or_identity(self):
        order = [2, 0, 1]
        with prepare() as first, prepare(destination_kinds=tuple(DESTINATIONS[i] for i in order),
                destination_ids=tuple(('accreted-wedge', 'deep-slab', 'external-export')[i] for i in order),
                destination_fractions=np.array([[.25, .5, .25], [.1, .2, .7]])[:, order]) as permuted:
            self.assertEqual(first.plan_id, permuted.plan_id)
            self.assertEqual(first.evaluate(10.).result_id, permuted.evaluate(10.).result_id)
            # All outlets receive their fraction even at the shared limiting event.
            np.testing.assert_array_equal(first.evaluate(20.).destination_mass_kg[:, 0], [30., 60., 30.])

    def test_common_frame_translation_and_moving_boundary(self):
        material = np.array([[.5, 3., 4.], [.25, -2., 1.]])
        shift = np.array([7., -9., 2.])
        with prepare() as first, prepare(material_velocity_m_s=material+shift,
                boundary_velocity_m_s=np.tile(shift, (2, 1))) as shifted:
            np.testing.assert_array_equal(first.mass_flux_kg_s, shifted.mass_flux_kg_s)
            np.testing.assert_array_equal(first.evaluate(10.).destination_mass_kg,
                                          shifted.evaluate(10.).destination_mass_kg)
        with prepare(boundary_velocity_m_s=[[.25, 0., 0.], [.125, 0., 0.]]) as moving:
            np.testing.assert_array_equal(moving.mass_flux_kg_s, [3., 5.])
            self.assertEqual(moving.exhaustion_duration_s, 40.)

    def test_tangential_motion_and_cessation_do_not_empty_stock(self):
        velocities = np.array([[0., 3., 4.], [0., -5., 6.]])
        with prepare(material_velocity_m_s=velocities) as stopped:
            self.assertIsNone(stopped.exhaustion_duration_s)
            np.testing.assert_array_equal(stopped.mass_flux_kg_s, [0., 0.])
            np.testing.assert_array_equal(stopped.tangential_velocity_m_s, velocities)
            result = stopped.evaluate(1000.)
            np.testing.assert_array_equal(result.remaining.mass_kg, stopped.inventory.mass_kg)
            np.testing.assert_array_equal(result.remaining.enthalpy_j, stopped.inventory.enthalpy_j)
            self.assertFalse(np.any(result.destination_mass_kg))

    def test_empty_finite_source_stops_at_zero_without_pass_through(self):
        initial = inventory(mass_kg=[0., 400.], component_mass_kg=[[0., 0.], [160., 240.]], enthalpy_j=[0., 2000.])
        with prepare(initial) as plan:
            self.assertEqual(plan.exhaustion_duration_s, 0.)
            self.assertFalse(np.any(plan.evaluate(0.).retired_mass_kg))
            with self.assertRaises(RetirementExhaustionError): plan.evaluate(1.)
        with self.assertRaises(TectonicsError):
            inventory(mass_kg=[0., 400.], component_mass_kg=[[0., 0.], [160., 240.]], enthalpy_j=[1., 2000.])

    def test_unresolvable_positive_stock_exhaustion_cannot_retire_at_zero_time(self):
        tiny = np.nextafter(0., 1.)
        initial = inventory(mass_kg=[tiny, 400.],
            component_mass_kg=[[tiny, 0.], [160., 240.]], enthalpy_j=[0., 2000.])
        with self.assertRaisesRegex(TectonicsError, 'exhaustion time is unresolvable'):
            prepare(initial)

    def test_invalid_stock_flux_geometry_and_partition_refuse(self):
        for changes in (dict(mass_kg=[-1., 400.]), dict(component_mass_kg=[[20., 90.], [160., 240.]]),
                        dict(layer_kinds=('unknown', 'mantle')), dict(enthalpy_source=''),
                        dict(enthalpy_j=[np.nan, 1.]), dict(component_ids=('B', 'A'))):
            with self.assertRaises(TectonicsError): inventory(**changes)
        for changes in (dict(material_velocity_m_s=[[-.1, 0., 0.], [.25, 0., 0.]]),
                        dict(material_velocity_m_s=np.zeros((2, 2))), dict(outward_normal=[2., 0., 0.]),
                        dict(strike_direction=[1., 0., 0.]), dict(section_policy=''),
                        dict(section_width_m=0.), dict(density_kg_m3=[0., 4.]),
                        dict(thickness_m=[-1., 5.]), dict(destination_fractions=[[.2, .2, .2], [.1, .2, .7]]),
                        dict(destination_fractions=[[-.1, .5, .6], [.1, .2, .7]]),
                        dict(destination_ids=('same', 'same', 'other'))):
            with self.assertRaises(TectonicsError): prepare(**changes)
        with prepare() as plan:
            for duration in (-1., True, float('nan'), float('inf')):
                with self.assertRaises(TectonicsError): plan.evaluate(duration)

    def test_immutable_result_source_identity_budget_and_cancellation(self):
        with self.assertRaises(MemoryLimitError): prepare(budget=WorkBudget(100))
        budget = WorkBudget(4*1024**2); stop = Event(); stop.set()
        with self.assertRaises(CancelledError): prepare(budget=budget, cancel=stop)
        self.assertEqual(budget.reserved_bytes, 0)
        plan = prepare(budget=budget); retained = budget.reserved_bytes
        self.assertGreater(retained, 0)
        with self.assertRaises(CancelledError): plan.evaluate(10., cancel=stop)
        self.assertEqual(budget.reserved_bytes, retained)
        result = plan.evaluate(10.)
        for array in (plan.mass_flux_kg_s, result.destination_mass_kg, result.remaining.enthalpy_j,
                      result.account_residuals, result.retired_component_mass_kg):
            with self.assertRaises(ValueError): array.setflags(write=True)
        with self.assertRaises(AttributeError): plan.exhaustion_duration_s = 100.
        with self.assertRaises(AttributeError): result.duration_s = 20.
        descriptor = plan.descriptor(); descriptor['source'] = 'changed'
        self.assertNotEqual(plan.descriptor()['source'], 'changed')
        with prepare(source_id='different') as other: self.assertNotEqual(plan.plan_id, other.plan_id)
        plan.close(); plan.close(); self.assertEqual(budget.reserved_bytes, 0)
        with self.assertRaises(TectonicsError): plan.evaluate(1.)
        np.testing.assert_array_equal(result.remaining.mass_kg, [60., 300.])


if __name__ == '__main__': unittest.main()
