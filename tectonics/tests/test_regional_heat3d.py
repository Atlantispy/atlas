"""Independent finite-volume, conservation and lifecycle controls for 3D heat."""
from concurrent.futures import CancelledError
import math
import threading
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics import regional_heat3d
from atlas_tectonics.regional_heat3d import PreparedRegionalHeat3D, SIDES
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


def insulated():
    return {side: ('flux', 0.) for side in SIDES}


def advance(plan, enthalpy, *, duration=1., boundaries=None, source=0., **kwargs):
    return plan.advance(enthalpy, duration, insulated() if boundaries is None else boundaries,
                        source, source_id='independent-analytical-heat-control', **kwargs)


def cell_centres(cells, lengths):
    return np.meshgrid(*[(np.arange(n)+.5)*length/n
                         for n, length in zip(cells, lengths)], indexing='ij')


class RegionalHeat3DTests(unittest.TestCase):
    def assert_controls(self, result):
        d = result.descriptor()
        self.assertLessEqual(d['linear_relative_residual'], 1e-11)
        self.assertLessEqual(d['energy_balance_relative_residual'], 1e-11)
        self.assertEqual(d['energy_balance_absolute_error_j'], abs(d['energy_balance_error_j']))
        self.assertEqual(set(d['outward_boundary_energy_j']), set(SIDES))
        self.assertFalse(d['scientific_acceptance'])

    def test_uniform_insulated_temperature_and_energy_unchanged(self):
        cells, lengths, capacity = (3, 4, 2), (2., 3., 4.), 7.
        volume = math.prod(lengths)/math.prod(cells)
        old = np.full(cells, capacity*volume*620.)
        with PreparedRegionalHeat3D(cells, lengths, capacity, 2.) as plan:
            result = advance(plan, old, duration=11.)
        self.assert_controls(result)
        assert_allclose(result.array('temperature_k'), 620., rtol=2e-14, atol=0.)
        assert_allclose(result.array('enthalpy_j'), old, rtol=2e-14, atol=0.)
        self.assertLess(result.descriptor()['energy_balance_absolute_error_j'], 1e-8)

    def test_linear_harmonic_profiles_on_each_axis_use_half_cell_distance(self):
        cells, lengths, capacity, conductivity = (3, 4, 5), (2., 3., 4.), 5., 7.
        centres = cell_centres(cells, lengths)
        volume = math.prod(lengths)/math.prod(cells)
        for axis in range(3):
            exact = 300.+17.*centres[axis]
            boundaries = insulated()
            boundaries['xyz'[axis]+'0'] = ('temperature', 300.)
            boundaries['xyz'[axis]+'1'] = ('temperature', 300.+17.*lengths[axis])
            with self.subTest(axis=axis), PreparedRegionalHeat3D(cells, lengths, capacity, conductivity) as plan:
                result = advance(plan, capacity*volume*exact, duration=3., boundaries=boundaries)
            self.assert_controls(result)
            assert_allclose(result.array('temperature_k'), exact, rtol=2e-14, atol=2e-11)
            boundary_energy = result.descriptor()['outward_boundary_energy_j']
            magnitude = conductivity*17.*math.prod(lengths)/lengths[axis]*3.
            self.assertAlmostEqual(boundary_energy['xyz'[axis]+'0'], magnitude, delta=2e-8)
            self.assertAlmostEqual(boundary_energy['xyz'[axis]+'1'], -magnitude, delta=2e-8)

    def test_three_axis_affine_harmonic_state_and_face_arrays(self):
        cells, lengths, capacity = (3, 4, 2), (2., 5., 3.), 2.
        xyz = cell_centres(cells, lengths)
        slope = (3., -2., 7.)
        exact = 300.+sum(s*x for s, x in zip(slope, xyz))
        boundaries = {}
        for side in SIDES:
            axis = 'xyz'.index(side[0])
            face = [slice(None)]*3
            face[axis] = 0 if side[1] == '0' else -1
            value = exact[tuple(face)] + slope[axis]*lengths[axis]/cells[axis]*(
                -.5 if side[1] == '0' else .5)
            boundaries[side] = ('temperature', value)
        volume = math.prod(lengths)/math.prod(cells)
        with PreparedRegionalHeat3D(cells, lengths, capacity, 4.) as plan:
            result = advance(plan, capacity*volume*exact, duration=.7, boundaries=boundaries)
        self.assert_controls(result)
        assert_allclose(result.array('temperature_k'), exact, atol=1e-11, rtol=2e-14)

    def test_uniform_volumetric_source_has_exact_independent_increment(self):
        cells, lengths, capacity, duration, source = (3, 2, 4), (6., 2., 4.), 6., .125, 12.
        volume = math.prod(lengths)/math.prod(cells)
        old = np.full(cells, 700.*volume*capacity)
        with PreparedRegionalHeat3D(cells, lengths, capacity, 3.) as plan:
            result = advance(plan, old, duration=duration, source=source)
        self.assert_controls(result)
        assert_allclose(result.array('temperature_k')-700., duration*source/capacity, rtol=0., atol=2e-12)
        increment = float(np.sum(result.array('enthalpy_j')-old))
        expected = source*math.prod(lengths)*duration
        self.assertAlmostEqual(increment, expected, delta=2e-9)
        self.assertEqual(result.descriptor()['source_energy_j'], expected)
        self.assertLess(result.descriptor()['energy_exchange_relative_residual'], 1e-10)
        self.assertGreater(result.descriptor()['energy_roundoff_allowance_j'], 0.)

    def test_outward_flux_sign_and_face_area_energy_on_every_axis(self):
        cells, lengths, capacity = (2, 3, 4), (2., 3., 8.), 6.
        volume, duration = math.prod(lengths)/math.prod(cells), .25
        for side in SIDES:
            axis = 'xyz'.index(side[0])
            face_shape = tuple(cells[j] for j in range(3) if j != axis)
            flux = np.arange(math.prod(face_shape), dtype=float).reshape(face_shape)+1.
            boundaries = insulated()
            boundaries[side] = ('flux', flux)
            old = np.full(cells, 500.*volume*capacity)
            with self.subTest(side=side), PreparedRegionalHeat3D(cells, lengths, capacity, 2.) as plan:
                result = advance(plan, old, duration=duration, boundaries=boundaries)
            self.assert_controls(result)
            area = math.prod(lengths[j]/cells[j] for j in range(3) if j != axis)
            expected = duration*area*float(flux.sum())
            self.assertEqual(result.descriptor()['outward_boundary_energy_j'][side], expected)
            self.assertAlmostEqual(float(np.sum(result.array('enthalpy_j')-old)), -expected, delta=2e-9)
            self.assertLess(float(np.min(result.array('temperature_k'))), 500.)

    def test_discrete_three_axis_eigenmode_has_exact_backward_euler_decay(self):
        cells, lengths, capacity, conductivity, duration = (4, 3, 5), (2., 3., 4.), 5., 2., .35
        xyz = cell_centres(cells, lengths)
        mode = np.sin(np.pi*xyz[0]/lengths[0])
        for axis in (1, 2):
            mode *= np.sin(np.pi*xyz[axis]/lengths[axis])
        eigenvalue = conductivity/capacity*sum(4.*np.sin(np.pi/(2*n))**2/(length/n)**2
                                               for n, length in zip(cells, lengths))
        volume = math.prod(lengths)/math.prod(cells)
        boundaries = {side: ('temperature', 300.) for side in SIDES}
        old = capacity*volume*(300.+25.*mode)
        with PreparedRegionalHeat3D(cells, lengths, capacity, conductivity) as plan:
            result = advance(plan, old, duration=duration, boundaries=boundaries)
        self.assert_controls(result)
        expected = 300.+25.*mode/(1.+duration*eigenvalue)
        assert_allclose(result.array('temperature_k'), expected, rtol=2e-14, atol=2e-11)

    def test_temporal_refinement_converges_to_semidiscrete_exponential(self):
        cells, lengths, capacity, conductivity, duration = (3, 4, 2), (2., 3., 4.), 5., 2., 1.2
        xyz = cell_centres(cells, lengths)
        mode = np.prod(np.stack([np.sin(np.pi*x/length) for x, length in zip(xyz, lengths)]), axis=0)
        rate = conductivity/capacity*sum(4.*np.sin(np.pi/(2*n))**2/(length/n)**2
                                         for n, length in zip(cells, lengths))
        volume = math.prod(lengths)/math.prod(cells)
        boundaries = {side: ('temperature', 300.) for side in SIDES}
        expected = 300.+25.*mode*np.exp(-rate*duration)
        errors = []
        with PreparedRegionalHeat3D(cells, lengths, capacity, conductivity) as plan:
            for steps in (2, 4, 8):
                enthalpy = capacity*volume*(300.+25.*mode)
                for _ in range(steps):
                    result = advance(plan, enthalpy, duration=duration/steps, boundaries=boundaries)
                    self.assert_controls(result)
                    enthalpy = result.array('enthalpy_j')
                exact_discrete = 300.+25.*mode/(1+rate*duration/steps)**steps
                assert_allclose(result.array('temperature_k'), exact_discrete, atol=3e-11, rtol=2e-14)
                errors.append(float(np.max(np.abs(result.array('temperature_k')-expected))))
        self.assertGreater(errors[0]/errors[1], 1.6)
        self.assertGreater(errors[1]/errors[2], 1.8)
        self.assertLess(errors[1]/errors[2], 2.1)

    def test_factor_reuse_changes_values_and_sources_but_not_physical_identity(self):
        old = np.full((2, 2, 2), 300.)
        boundaries = insulated()
        boundaries['x0'] = ('temperature', 310.)
        with PreparedRegionalHeat3D((2, 2, 2), (2., 2., 2.), 1., 2.) as plan:
            first = advance(plan, old, boundaries=boundaries)
            boundaries['x0'] = ('temperature', 320.)
            second = advance(plan, old, boundaries=boundaries, source=5.)
            self.assertEqual(plan.statistics()['factorizations'], 1)
            self.assertEqual(plan.statistics()['factor_reuses'], 1)
            self.assertTrue(np.all(second.array('temperature_k') > first.array('temperature_k')))
            self.assertNotEqual(first.result_id, second.result_id)
            advance(plan, old, duration=2., boundaries=boundaries)
            advance(plan, old, duration=2.)
            self.assertEqual(plan.statistics()['factorizations'], 3)
            # Returning to an earlier key rebuilds: only one factor is retained.
            advance(plan, old, boundaries=boundaries)
            self.assertEqual(plan.statistics()['factorizations'], 4)

    def test_single_cell_all_faces_and_negative_source(self):
        boundaries = insulated()
        boundaries['x0'], boundaries['z1'] = ('flux', 2.), ('flux', -1.)
        with PreparedRegionalHeat3D((1, 1, 1), (2., 3., 4.), 5., 3.) as plan:
            result = advance(plan, np.full((1, 1, 1), 60000.), duration=.5,
                             boundaries=boundaries, source=-2.)
        self.assert_controls(result)
        expected = 60000.-.5*(2.*24.+2.*12.-1.*6.)
        assert_allclose(result.array('enthalpy_j'), expected, atol=1e-10, rtol=0.)

    def test_results_are_immutable_and_detached(self):
        old = np.full((2, 2, 2), 300.)
        with PreparedRegionalHeat3D((2, 2, 2), (2., 2., 2.), 1., 2.) as plan:
            result = advance(plan, old, source=1.)
        old[:] = 2.
        assert_allclose(result.array('temperature_k'), 301., atol=1e-11)
        for name in result.array_names:
            with self.assertRaises(ValueError):
                result.array(name).setflags(write=True)
        with self.assertRaises(TectonicsError):
            result.result_id = 'overwritten'
        descriptor = result.descriptor()
        descriptor['outward_boundary_energy_j']['x0'] = 100.
        self.assertEqual(result.descriptor()['outward_boundary_energy_j']['x0'], 0.)

    def test_explicit_invalid_inputs_and_nonpositive_output_refused(self):
        old = np.full((2, 2, 2), 300.)
        with PreparedRegionalHeat3D((2, 2, 2), (2., 2., 2.), 1., 2.) as plan:
            for changes in ({'duration': 0.}, {'duration': float('inf')},
                            {'source': float('nan')}, {'source': True},
                            {'source': np.zeros((2, 2))}, {'source': -1000.}):
                with self.subTest(changes=changes), self.assertRaises(TectonicsError):
                    advance(plan, old, **changes)
            for value in (np.zeros((2, 2, 2)), np.ones((2, 2)), np.ones((2, 2, 2), dtype=bool),
                          np.ma.array(old, mask=False)):
                with self.assertRaises(TectonicsError):
                    advance(plan, value)
            for item in (('temperature', 0.), ('flux', np.zeros((2, 3))),
                         ('insulated', 0.), ['flux', 0.], (np.array(['flux']), 0.)):
                boundary = insulated()
                boundary['z0'] = item
                with self.assertRaises(TectonicsError):
                    advance(plan, old, boundaries=boundary)
            with self.assertRaises(TectonicsError):
                advance(plan, old, boundaries={})
            with self.assertRaises(TectonicsError):
                plan.advance(old, 1., insulated(), 0., source_id='')
            with self.assertRaises(TectonicsError):
                advance(plan, old, source=np.finfo(float).max, duration=10.)
        with self.assertRaisesRegex(TectonicsError, 'closed'):
            advance(plan, old)

    def test_budget_refuses_before_grid_allocation_and_failed_prepare_releases(self):
        budget = WorkBudget(1024)
        with mock.patch.object(regional_heat3d.np, 'arange', side_effect=AssertionError('allocated')):
            with self.assertRaises(MemoryLimitError):
                PreparedRegionalHeat3D((64, 64, 64), (1., 1., 1.), 2., 3., budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        budget = WorkBudget(32*1024**2)
        with self.assertRaises(TectonicsError):
            PreparedRegionalHeat3D((2, 2, 2), (1e200, 1e200, 1e200), 2., 3., budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        for cells, capacity, conductivity in (((65, 2, 2), 2., 3.), ((True, 2, 2), 2., 3.),
                                               ((2, 2, 2), 0., 3.), ((2, 2, 2), 2., -1.)):
            with self.assertRaises(TectonicsError):
                PreparedRegionalHeat3D(cells, (1., 1., 1.), capacity, conductivity, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_cancellation_owner_and_source_guards_release_budget(self):
        budget = WorkBudget(32*1024**2)
        old = np.full((2, 2, 2), 300.)
        event = threading.Event()
        event.set()
        with PreparedRegionalHeat3D((2, 2, 2), (2., 2., 2.), 1., 2., budget=budget) as plan:
            with self.assertRaises(CancelledError):
                advance(plan, old, cancel=event)
            errors = []
            def other_owner():
                try:
                    advance(plan, old)
                except TectonicsError as error:
                    errors.append(str(error))
            thread = threading.Thread(target=other_owner)
            thread.start()
            thread.join()
            self.assertEqual(len(errors), 1)
            self.assertIn('single-owner', errors[0])
            with mock.patch.object(PreparedRegionalHeat3D, '_build_diffusion', lambda *_: None):
                with self.assertRaisesRegex(TectonicsError, 'implementation changed'):
                    advance(plan, old)
            self.assertEqual(plan.statistics()['advances'], 0)
            result = advance(plan, old)
            self.assert_controls(result)
        self.assertEqual(budget.reserved_bytes, 0)
        with mock.patch.object(regional_heat3d, '_LOADED_SOURCE_SHA256', '0'*64):
            with self.assertRaisesRegex(TectonicsError, 'source changed'):
                PreparedRegionalHeat3D((2, 2, 2), (2., 2., 2.), 1., 2., budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
