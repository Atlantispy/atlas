"""Focused conservation, face reconstruction and finite-inventory controls.

SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import threading
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import regional_transport3d as transport
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


def prepare(**kwargs):
    values = dict(divergence_rtol=1e-10, max_velocity_correction_m_s=2., max_relative_correction=2.)
    values.update(kwargs)
    return transport.PreparedRegionalTransport3D((2, 2, 2), (1., 1., 1.), **values)


def coordinates():
    return np.indices((5, 5, 5)).reshape(3, -1).T/4


def constant_stock(plan, mass_density=(2., 3.), h_density=17., history_density=11.):
    return {s: plan.boundary_stock(s, 1., np.asarray(mass_density), h_density,
                                   {'plastic': history_density}) for s in transport.SIDES}


class RegionalTransport3DTests(unittest.TestCase):
    def test_all_axes_constant_field_and_boundary_accounts(self):
        for axis in range(3):
            with self.subTest(axis=axis), prepare() as plan:
                velocity = np.zeros((125, 3)); velocity[:, axis] = .2
                flow = plan.project_velocity(velocity, source_result_id='analytic-translation')
                mass = np.broadcast_to(np.array([2., 3.])[:, None, None, None]*.125, (2, 2, 2, 2)).copy()
                heat = np.full((2, 2, 2), 17*.125); history = np.full((2, 2, 2), 11*.125)
                stocks = constant_stock(plan)
                result = plan.advect(mass, heat, {'plastic': history}, flow, .5, boundary_stocks=stocks)
                assert_allclose(result.array('component_mass_kg'), mass, atol=1e-15)
                assert_allclose(result.array('enthalpy_j'), heat, atol=1e-15)
                assert_allclose(result.array('tracer:plastic'), history, atol=1e-15)
                side = 'xyz'[axis]+'0'; outward = 'xyz'[axis]+'1'
                self.assertAlmostEqual(result.boundary_stocks[side].array('volume_m3').sum(), 3.9)
                self.assertAlmostEqual(result.exports[outward].array('volume_m3').sum(), .1)
                assert_array_equal(stocks[side].array('volume_m3'), np.ones((2, 2)))
                for account in result.descriptor()['accounts']:
                    self.assertAlmostEqual(account['balance_residual'], 0., delta=2e-14)

    def test_constant_state_with_all_three_simultaneous_streams(self):
        with prepare() as plan:
            velocity = np.broadcast_to([.2, -.3, .1], (125, 3))
            flow = plan.project_velocity(velocity, source_result_id='three-directions')
            mass = np.broadcast_to(np.array([2., 3.])[:, None, None, None]*.125, (2, 2, 2, 2))
            result = plan.advect(mass, np.full((2, 2, 2), 17*.125), {'plastic': np.full((2, 2, 2), 11*.125)},
                flow, .2, boundary_stocks=constant_stock(plan))
            assert_allclose(result.array('component_mass_kg'), mass, atol=1e-15)
            self.assertAlmostEqual(result.descriptor()['maximum_outgoing_courant'], .24)

    def test_closed_rest_exact_and_immutable(self):
        with prepare() as plan:
            flow = plan.project_velocity(np.zeros((125, 3)), source_result_id='rest')
            mass = np.arange(1., 17.).reshape(2, 2, 2, 2)
            history = np.arange(8.).reshape(2, 2, 2)
            stocks = plan.empty_boundary_stocks(2, ('plastic',))
            result = plan.advect(mass, -history, {'plastic': history}, flow, 10., boundary_stocks=stocks)
            assert_array_equal(result.array('component_mass_kg'), mass)
            assert_array_equal(result.array('enthalpy_j'), -history)
            assert_array_equal(result.array('tracer:plastic'), history)
            for name in result.array_names:
                with self.assertRaises(ValueError):
                    result.array(name).setflags(write=True)
            with self.assertRaises(AttributeError):
                result.result_id = 'changed'
            with self.assertRaises(TypeError):
                result.boundary_stocks['x0'] = stocks['x0']
            with self.assertRaises(AttributeError):
                plan.divergence_rtol = .1

    def test_counterflow_is_not_cancelled_before_donor_selection(self):
        with prepare() as plan:
            xyz = coordinates(); v = np.zeros_like(xyz); v[:, 0] = xyz[:, 1]-.25
            flow = plan.project_velocity(v, source_result_id='face-counterflow')
            self.assertAlmostEqual(flow.array('net_x_m3_s')[1, 0, 0], 0., delta=2e-17)
            self.assertGreater(flow.array('positive_x_m3_s')[1, 0, 0], 0.)
            self.assertGreater(flow.array('negative_x_m3_s')[1, 0, 0], 0.)
            mass = np.ones((1, 2, 2, 2)); mass[:, 0] = 0.
            stocks = {s: plan.boundary_stock(s, 1., [0.], 0.) for s in transport.SIDES}
            result = plan.advect(mass, np.zeros((2, 2, 2)), {}, flow, .1, boundary_stocks=stocks)
            self.assertGreater(result.array('component_mass_kg')[0, 0, 0, 0], 0.)
            self.assertLess(result.array('component_mass_kg:transfer_x')[0, 1, 0, 0], 0.)

    def test_projection_corrects_cells_and_preserves_every_boundary_sample(self):
        with prepare() as plan:
            xyz = coordinates(); x = xyz[:, 0]
            v = np.zeros_like(xyz); v[:, 0] = x*(1-x)
            flow = plan.project_velocity(v, source_result_id='interior-q2-bubble')
            d = flow.descriptor()
            self.assertGreater(d['raw_max_cell_net_m3_s'], .01)
            self.assertLess(d['corrected_max_cell_net_m3_s'], 1e-14)
            self.assertGreater(d['correction_max_m_s'], .01)
            for axis, label in enumerate('xyz'):
                for end in (0, -1):
                    assert_array_equal(np.take(flow.array('raw_normal_'+label+'_m_s'), end, axis=axis),
                        np.take(flow.array('normal_'+label+'_m_s'), end, axis=axis))
            self.assertEqual(plan.statistics()['factorizations'], 1)
            other = plan.project_velocity(v, source_result_id='same-flow-new-parent')
            assert_array_equal(other.array('net_x_m3_s'), flow.array('net_x_m3_s'))

    def test_q2_signed_face_integrals(self):
        with prepare() as plan:
            xyz = coordinates(); v = np.zeros_like(xyz); v[:, 0] = xyz[:, 1]**2+xyz[:, 2]**2
            flow = plan.project_velocity(v, source_result_id='q2-exact-face')
            # On y,z in [0,.5], integral(y²+z²) dy dz = 1/24.
            self.assertAlmostEqual(flow.array('net_x_m3_s')[0, 0, 0], 1/24, delta=2e-17)

    def test_projection_allowances_and_global_incompatibility_refuse(self):
        xyz = coordinates(); v = np.zeros_like(xyz); v[:, 0] = xyz[:, 0]*(1-xyz[:, 0])
        with prepare(max_velocity_correction_m_s=.01) as plan:
            with self.assertRaisesRegex(TectonicsError, 'correction exceeds'):
                plan.project_velocity(v, source_result_id='excess-correction')
        with prepare(max_relative_correction=.01) as plan:
            with self.assertRaisesRegex(TectonicsError, 'correction exceeds'):
                plan.project_velocity(v, source_result_id='excess-relative-correction')
        with prepare() as plan:
            with self.assertRaisesRegex(TectonicsError, 'global boundary'):
                plan.project_velocity(xyz, source_result_id='expanding-box')

    def test_finite_stock_exhaustion_atomic_and_exact_emptying(self):
        with prepare() as plan:
            v = np.broadcast_to([1., 0., 0.], (125, 3)); flow = plan.project_velocity(v, source_result_id='translation')
            mass = np.ones((1, 2, 2, 2)); heat = mass[0]*7
            stocks = plan.empty_boundary_stocks(1)
            original = mass.copy(); identities = {s: a.result_id for s, a in stocks.items()}
            with self.assertRaisesRegex(TectonicsError, 'stock exhausted'):
                plan.advect(mass, heat, {}, flow, .1, boundary_stocks=stocks)
            assert_array_equal(mass, original)
            self.assertEqual({s: a.result_id for s, a in stocks.items()}, identities)
            required = flow.array('positive_x_m3_s')[0]*.1
            stocks['x0'] = plan.boundary_stock('x0', required, [.2], 1.4)
            result = plan.advect(mass, heat, {}, flow, .1, boundary_stocks=stocks)
            assert_allclose(result.boundary_stocks['x0'].array('volume_m3'), 0., atol=1e-17)
            assert_allclose(result.boundary_stocks['x0'].array('component_mass_kg'), 0., atol=1e-16)

    def test_cfl_refusal_and_no_hidden_substeps(self):
        with prepare() as plan:
            flow = plan.project_velocity(np.broadcast_to([1., 0., 0.], (125, 3)), source_result_id='fast')
            stocks = {s: plan.boundary_stock(s, 10., [10.], 0.) for s in transport.SIDES}
            with self.assertRaisesRegex(TectonicsError, 'CFL'):
                plan.advect(np.ones((1, 2, 2, 2)), np.zeros((2, 2, 2)), {}, flow, .6, boundary_stocks=stocks)

    def test_cancellation_and_budget_cleanup(self):
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(CancelledError):
            prepare(cancel=cancel)
        budget = WorkBudget(8*1024**2)
        with prepare(budget=budget) as plan:
            retained = budget.reserved_bytes
            with self.assertRaises(CancelledError):
                plan.project_velocity(np.zeros((125, 3)), source_result_id='cancelled', cancel=cancel)
            self.assertEqual(budget.reserved_bytes, retained)
            flow = plan.project_velocity(np.zeros((125, 3)), source_result_id='rest')
            calls = 0
            def later():
                nonlocal calls
                calls += 1
                return calls >= 3
            with self.assertRaises(CancelledError):
                plan.advect(np.ones((1, 2, 2, 2)), np.zeros((2, 2, 2)), {}, flow, .1,
                    boundary_stocks=plan.empty_boundary_stocks(1), cancel=later)
            self.assertEqual(budget.reserved_bytes, retained)
        self.assertEqual(budget.reserved_bytes, 0)
        tiny = WorkBudget(100)
        with self.assertRaises(MemoryLimitError):
            prepare(budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)

    def test_realised_factor_is_checked_without_retained_copies(self):
        # No exported copies; both admission and the realised check account for
        # native initial allocation, growth storage and construction work.
        class Counted:
            def __init__(self, factor, entries):
                self.nnz = factor.nnz if entries is None else entries
                self.shape, self.solve = factor.shape, factor.solve

            @property
            def L(self):
                raise AssertionError('a factor copy was built')
            U = L
        original, entries = transport.splu, [None]
        xyz = coordinates(); v = np.zeros_like(xyz); v[:, 0] = xyz[:, 0]*(1-xyz[:, 0])
        with prepare() as plan:
            expected = plan.project_velocity(v, source_result_id='interior-q2-bubble')
        budget = WorkBudget(8*1024**2)
        with mock.patch.object(transport, 'splu', lambda *a, **k: Counted(original(*a, **k), entries[0])):
            with prepare(budget=budget) as plan:
                flow = plan.project_velocity(v, source_result_id='interior-q2-bubble')
                for name in expected.array_names:
                    assert_array_equal(flow.array(name), expected.array(name))
                fixed = 2*1024**2+1024*plan._nc+1024*(plan._nc-1)
                entries[0] = (plan._allowance-fixed)//24
            with prepare(budget=budget):
                pass                                # the largest count the allowance admits
            entries[0] += 1
            with self.assertRaises(MemoryLimitError):
                prepare(budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_preparation_admits_native_peak_before_constructing_the_grid(self):
        # Retained R7 Windows private-commit observations, not a fresh benchmark.
        observations = (((16, 16, 16), 22487040), ((20, 20, 20), 71081984),
                        ((24, 24, 24), 139448320), ((24, 24, 23), 133881856),
                        ((23, 21, 24), 115830784), ((22, 24, 24), 128786432))
        for cells, measured_peak in observations:
            self.assertGreaterEqual(transport._projection_bytes(cells), measured_peak, cells)
        budget = WorkBudget(115343360)  # old 24-cube allowance, below its measured peak
        with mock.patch.object(transport.sparse, 'csr_matrix') as build, \
                self.assertRaises(MemoryLimitError):
            transport.PreparedRegionalTransport3D((24, 24, 24), (1., 1., 1.),
                divergence_rtol=1e-10, max_velocity_correction_m_s=2.,
                max_relative_correction=2., budget=budget)
        build.assert_not_called()
        self.assertEqual((budget.reserved_bytes, budget.peak_reserved_bytes), (0, 0))

    def test_source_and_foreign_plan_guards(self):
        with prepare() as plan:
            with mock.patch.object(transport, '_sum', lambda _: 0.):
                with self.assertRaisesRegex(TectonicsError, 'implementation changed'):
                    plan.project_velocity(np.zeros((125, 3)), source_result_id='mutated')
            flow = plan.project_velocity(np.zeros((125, 3)), source_result_id='rest')
            with prepare(max_relative_correction=1.) as other:
                with self.assertRaisesRegex(TectonicsError, 'different prepared'):
                    other.advect(np.ones((1, 2, 2, 2)), np.zeros((2, 2, 2)), {}, flow, .1,
                        boundary_stocks=other.empty_boundary_stocks(1))

    def test_invalid_support_and_policy(self):
        for invalid in (0., 1e-6, float('nan'), True):
            with self.subTest(invalid=invalid), self.assertRaises(TectonicsError):
                prepare(divergence_rtol=invalid)
        with prepare() as plan:
            with self.assertRaises(TectonicsError):
                plan.project_velocity(np.zeros((5, 5, 5, 3)), source_result_id='wrong-shape')
            with self.assertRaises(TectonicsError):
                plan.boundary_stock('x0', 0., [1.], 0.)


if __name__ == '__main__':
    unittest.main()
