"""Focused 3D evolution controls; synthetic SI coefficients, not Earth fits.

SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import threading
import unittest
import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.constitutive import BoussinesqMaterial, RheologyProfile, DiffusiveScales
from atlas_tectonics.regional_execution import RegionalMechanicsScales
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.regional_execution3d import SIDES
from atlas_tectonics.regional_evolution3d import PreparedRegionalEvolution3D
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


def prepare(profile=None, cells=(2, 2, 2), heating=False, **kwargs):
    material = BoussinesqMaterial('synthetic-control', 'analytical-test-only',
        1., 1., .1, 0., 1.5, .02, 0., (1., 2.))
    if profile is None:
        profile = RheologyProfile('constant-control', 'constant', 'analytic', (('eta', 1.),))
    return PreparedRegionalEvolution3D(cells, (1., 1., 1.), material, profile,
        DiffusiveScales('synthetic-SI-scales', 1., 1., 1., 1., 1., 1.),
        RegionalMechanicsScales(1., 1.), {s: ('velocity',)*3 for s in SIDES},
        composition_values=(0., 1.), frame_id='synthetic-Cartesian',
        vertical_datum='bottom-z-zero', include_viscous_heating=heating,
        divergence_rtol=1e-10, max_velocity_correction_m_s=1e-8,
        max_relative_correction=1e-6, **kwargs)


def initial(plan, T=1.5, C=None, damage=0., histories=None):
    C = np.full(plan.cells, .25) if C is None else C
    return plan.initial_state(T, np.stack((1-C, C)), damage,
        time_s=0., state_source='synthetic-initial', scalar_histories=histories)


def advance(plan, state, dt=.1, **kwargs):
    values = dict(velocity_m_s=0., dynamic_traction_pa={s: 0. for s in SIDES},
        gravity_m_s2=(0., 0., 0.), additional_body_force_n_m3=0.,
        driving_source='frozen-synthetic-driving', heat_boundaries={s: ('flux', 0.) for s in SIDES},
        heat_source_w_m3=0., heat_source='explicit-no-external-heating',
        boundary_stocks=plan.empty_boundary_stocks())
    values.update(kwargs)
    return plan.advance(state, dt, **values)


def full_stocks(plan, T=1.5, C=.25, history=0.):
    return {s: plan.boundary_stock(s, 10., (10*(1-C), 10*C), 10*T,
                {'damage': 0., 'accumulated_strain_ii': 0., 'formation': 10*history})
            for s in SIDES}


class RegionalEvolution3DTests(unittest.TestCase):
    def test_quiescent_connection_and_repeated_operator_reuse(self):
        with prepare() as plan:
            state = initial(plan)
            first = advance(plan, state)
            second = advance(plan, first.state, boundary_stocks=first.transport.boundary_stocks)
            for name in state.array_names:
                assert_allclose(second.state.array(name), state.array(name), rtol=5e-14, atol=1e-15)
            self.assertEqual(second.state.descriptor()['time_s'], .2)
            self.assertEqual(second.state.descriptor()['parent_state_id'], first.state.result_id)
            self.assertEqual(second.initial_mechanics.result_id, first.mechanics.result_id)
            self.assertEqual(plan.statistics()['mechanical_preparations'], 1)
            self.assertEqual(plan.statistics()['endpoint_cache_hits'], 1)
            self.assertLess(first.mechanics.descriptor()['linear_relative_residual'], 2e-9)
            self.assertFalse(first.descriptor()['scientific_acceptance'])
            with self.assertRaises(ValueError):
                first.state.array('enthalpy_j').setflags(write=True)

    def test_solved_translation_moves_composition_enthalpy_and_history_all_axes(self):
        for axis in range(3):
            with self.subTest(axis=axis), prepare() as plan:
                C = np.indices(plan.cells)[axis]*.4+.1
                state = initial(plan, C=C, histories={'formation': 7.})
                nv = int(np.prod(2*np.array(plan.cells)+1))
                velocity = np.zeros((nv, 3)); velocity[:, axis] = .2
                result = advance(plan, state, .1, velocity_m_s=velocity,
                    boundary_stocks=full_stocks(plan, C=.1, history=7.))
                expected = C.copy()
                upper = [slice(None)]*3; upper[axis] = 1
                expected[tuple(upper)] -= .04*.4
                assert_allclose(result.state.array('component_mass_kg')[1]/.125, expected, atol=2e-11)
                assert_allclose(result.state.array('enthalpy_j'), 1.5*.125, atol=2e-12)
                assert_allclose(result.state.array('tracer:formation'), 7*.125, atol=2e-11)
                assert_allclose(result.mechanics.array('velocity_m_s'), velocity, atol=2e-10)

    def test_thermal_change_alters_viscosity_and_force_driven_motion(self):
        profile = RheologyProfile('thermal-control', 'tosi-linear', 'declared-analytic',
            (('contrast_T', 10.), ('contrast_z', 1.)))
        with prepare(profile) as plan:
            state = initial(plan, histories={'formation': 0.})
            xyz = np.indices((5, 5, 5)).reshape(3, -1).T/4
            mode = np.stack((xyz[:, 0], -xyz[:, 1], np.zeros(len(xyz))), axis=-1)[None]
            coupling = dict(boundary_modes_m=mode, external_generalized_force_j=np.array([1.]),
                external_resistance_j_s=np.array([[1.]]), source='synthetic-exterior-only')
            result = advance(plan, state, .02, heat_source_w_m3=2., coupling=coupling,
                boundary_stocks=full_stocks(plan))
            before = result.initial_mechanics.array('velocity_m_s')
            after = result.mechanics.array('velocity_m_s')
            self.assertGreater(np.max(after[:, 0]), np.max(before[:, 0])*1.01)
            self.assertGreater(plan.statistics()['mechanical_preparations'], 1)
            self.assertLess(result.descriptor()['endpoint_constitutive']['constitutive_log_residual'], 1e-8)
            self.assertAlmostEqual(result.descriptor()['volume_source_energy_j'], .04)

    def test_carried_memory_heals_without_resetting_passive_history(self):
        profile = RheologyProfile('memory-control', 'bf23-memory', 'declared-BF-local-law',
            (('E', 0.), ('eta0', 1.), ('a', 10.), ('b', 0.), ('dcrit', 10.),
             ('weakening', .5), ('B', .1), ('Ed', 0.)))
        with prepare(profile) as plan:
            state = initial(plan, damage=2., histories={'formation': 42.})
            result = advance(plan, state, .2, boundary_stocks=plan.empty_boundary_stocks(('formation',)))
            assert_allclose(result.state.array('tracer:damage')/.125, 2*np.exp(-.02), rtol=2e-13)
            assert_array_equal(result.state.array('tracer:formation'), state.array('tracer:formation'))

    def test_yielding_rheology_uses_solved_three_dimensional_invariant(self):
        profile = RheologyProfile('plastic-control', 'tosi-plastic', 'synthetic-Tosi-law',
            (('contrast_T', 1.), ('contrast_z', 1.), ('eta_star', 1.), ('sigma_y', .2)))
        with prepare(profile) as plan:
            state = initial(plan, histories={'formation': 0.})
            xyz = np.indices((5, 5, 5)).reshape(3, -1).T/4
            velocity = np.zeros((125, 3)); velocity[:, 0] = .2*xyz[:, 2]
            result = advance(plan, state, .01, velocity_m_s=velocity, boundary_stocks=full_stocks(plan))
            q = np.sqrt(2)*.1
            eta = 2/(1+q/(q+.2))
            assert_allclose(result.mechanics.array('extra_plus_viscous_stress_pa')[..., 0, 2], .2*eta, atol=2e-9)
            self.assertLess(result.descriptor()['endpoint_constitutive']['constitutive_log_residual'], 1e-8)

    def test_viscous_heat_uses_actual_three_dimensional_strain_once(self):
        with prepare(heating=True) as plan:
            state = initial(plan, histories={'formation': 0.})
            xyz = np.indices((5, 5, 5)).reshape(3, -1).T/4
            velocity = np.stack((.1*xyz[:, 2], .2*xyz[:, 0], .3*xyz[:, 1]), axis=-1)
            result = advance(plan, state, .1, velocity_m_s=velocity, boundary_stocks=full_stocks(plan))
            self.assertAlmostEqual(result.descriptor()['volume_source_energy_j'], .014, delta=3e-11)
            expected_rate = np.sqrt(.01+.04+.09)/2
            self.assertGreater(np.max(result.state.array('tracer:accumulated_strain_ii')), .002)
            self.assertLessEqual(np.max(result.state.array('tracer:accumulated_strain_ii'))/.125,
                                 expected_rate*.1+1e-10)

    def test_connected_cooling_has_first_order_time_convergence(self):
        errors = []
        cells = (2, 2, 2)
        mode = np.cos(np.pi*(np.indices(cells)[2]+.5)/2)
        exact = 1.5+.1*mode*np.exp(-.8*.4)
        for steps in (1, 2, 4):
            with prepare(cells=cells) as plan:
                state = initial(plan, T=1.5+.1*mode)
                stocks = plan.empty_boundary_stocks()
                for _ in range(steps):
                    result = advance(plan, state, .4/steps, boundary_stocks=stocks)
                    state, stocks = result.state, result.transport.boundary_stocks
                T = state.array('enthalpy_j')/.125
                errors.append(float(np.max(np.abs(T-exact))))
                self.assertAlmostEqual(np.sum(state.array('enthalpy_j')), 1.5, delta=1e-12)
        self.assertGreater(errors[0]/errors[1], 1.8)
        self.assertGreater(errors[1]/errors[2], 1.8)

    def test_atomic_refusal_for_exhausted_stock_and_cancel(self):
        with prepare() as plan:
            state = initial(plan)
            originals = {k: state.array(k).copy() for k in state.array_names}
            with self.assertRaises(TectonicsError):
                advance(plan, state, velocity_m_s=np.tile((1., 0., 0.), (125, 1)))
            event = threading.Event(); event.set()
            with self.assertRaises(CancelledError):
                advance(plan, state, cancel=event)
            self.assertEqual(plan.statistics()['accepted_intervals'], 0)
            for name in originals:
                assert_array_equal(state.array(name), originals[name])
            advance(plan, state)

    def test_no_implicit_memory_or_temperature_extrapolation(self):
        with prepare() as plan:
            with self.assertRaises(TectonicsError):
                initial(plan, damage=.1)
            with self.assertRaises(TectonicsError):
                initial(plan, T=3.)
            with self.assertRaises(TectonicsError):
                advance(plan, initial(plan), heat_source_w_m3=100.)
        with self.assertRaises(MemoryLimitError):
            prepare(budget=WorkBudget(1024))


PLASTIC = RheologyProfile('plastic-control', 'tosi-plastic', 'synthetic-Tosi-law',
    (('contrast_T', 1.), ('contrast_z', 1.), ('eta_star', 1.), ('sigma_y', .2)))
METHODS = ('auto', 'multigrid', 'gmres', 'direct')


def shear(rate):
    xyz = np.indices((5, 5, 5)).reshape(3, -1).T/4
    velocity = np.zeros((125, 3)); velocity[:, 0] = rate*xyz[:, 2]
    return velocity


def yielding(plan, state, stocks):
    return advance(plan, state, .01, velocity_m_s=shear(.2), boundary_stocks=stocks)


def force_driven(plan, state, stocks):
    xyz = np.indices((5, 5, 5)).reshape(3, -1).T/4
    mode = np.stack((xyz[:, 0], -xyz[:, 1], np.zeros(len(xyz))), axis=-1)[None]
    coupling = dict(boundary_modes_m=mode, external_generalized_force_j=np.array([1.]),
        external_resistance_j_s=np.array([[10.]]), source='synthetic-exterior-only')
    return advance(plan, state, .02, coupling=coupling, boundary_stocks=stocks)


def published(result):
    """Both mechanical solves, the next state and both constitutive records of one advance."""
    d = result.descriptor()
    return (result.initial_mechanics.result_id, result.state.result_id, result.mechanics.result_id,
            d['initial_constitutive'], d['endpoint_constitutive'])


def saved(plan, result):
    """What survives a restart: state and remaining stocks rebuilt from descriptors and arrays."""
    state = RegionalMechanicalSnapshot(result.state.descriptor(),
        {name: result.state.array(name).copy() for name in result.state.array_names})
    stocks = {}
    for side, stock in result.transport.boundary_stocks.items():
        histories = {name[7:]: stock.array(name).copy() for name in stock.array_names
                     if name.startswith('tracer:')}
        stocks[side] = plan.boundary_stock(side, stock.array('volume_m3').copy(),
            stock.array('component_mass_kg').copy(), stock.array('enthalpy_j').copy(), histories)
    return state, stocks


class DeclaredStartTests(unittest.TestCase):
    """Every mechanical solve starts from zero strain rate, so plan history is not an input."""
    _runs = {}

    @classmethod
    def runs(cls, method):
        """Two yielding intervals on one plan; then, on a new plan, the second and the first again.

        Computed once for each method and shared by the tests below.
        """
        if method not in cls._runs:
            with prepare(PLASTIC, mechanics_method=method) as plan:
                state = initial(plan, histories={'formation': 0.})
                stocks = full_stocks(plan)
                first = yielding(plan, state, stocks)
                second = yielding(plan, first.state, first.transport.boundary_stocks)
                hits = plan.statistics()['endpoint_cache_hits']
            with prepare(PLASTIC, mechanics_method=method) as plan:        # as after a process restart
                rebuilt = saved(plan, first)
                restarted = yielding(plan, *rebuilt)
                restart_hits = plan.statistics()['endpoint_cache_hits']
                after = yielding(plan, state, stocks)
            cls._runs[method] = dict(state=state, stocks=stocks, first=first, second=second, hits=hits,
                rebuilt=rebuilt, restarted=restarted, restart_hits=restart_hits, after=after)
        return cls._runs[method]

    def test_plan_definition_records_the_zero_start(self):
        with prepare() as plan:
            self.assertEqual(plan.descriptor()['constitutive_start'],
                             'zero strain rate at every mechanical solve')
            self.assertEqual(plan.descriptor()['constitutive_max_iterations'], 32)

    def test_restarted_interval_on_a_new_plan_reproduces_the_continuous_run(self):
        for method in METHODS:
            with self.subTest(method=method):
                run = self.runs(method)
                first, continuous, restarted = run['first'], run['second'], run['restarted']
                state, stocks = run['rebuilt']
                self.assertEqual(state.result_id, first.state.result_id)
                self.assertEqual({side: stock.result_id for side, stock in stocks.items()},
                    {side: stock.result_id for side, stock in first.transport.boundary_stocks.items()})
                # The continuous plan reused its endpoint as the next start; the new plan solved it.
                self.assertEqual((run['hits'], run['restart_hits']), (1, 0))
                self.assertEqual(published(restarted), published(continuous))
                for name in continuous.state.array_names:
                    assert_array_equal(restarted.state.array(name), continuous.state.array(name))
                for name in continuous.mechanics.array_names:
                    assert_array_equal(restarted.mechanics.array(name), continuous.mechanics.array(name))

    def test_result_is_independent_of_earlier_solves_on_the_plan(self):
        for method in METHODS:
            with self.subTest(method=method):
                run = self.runs(method)
                # The first interval again, on a plan that had just solved the second one.
                self.assertEqual(published(run['after']), published(run['first']))
                for name in run['first'].state.array_names:
                    assert_array_equal(run['after'].state.array(name), run['first'].state.array(name))

    def test_refused_advance_does_not_change_a_following_advance(self):
        run = self.runs('auto')
        with prepare(PLASTIC) as plan:
            # Start mechanics of the second interval converges; transport then finds no upstream stock.
            with self.assertRaises(TectonicsError):
                yielding(plan, run['first'].state, plan.empty_boundary_stocks(('formation',)))
            statistics = plan.statistics()
            self.assertGreater(statistics['mechanical_preparations'], 0)
            self.assertEqual(statistics['accepted_intervals'], 0)
            after = yielding(plan, run['state'], run['stocks'])
        self.assertEqual(published(after), published(run['first']))

    def test_force_driven_result_is_independent_of_earlier_solves(self):
        with prepare(PLASTIC) as plan:
            state = initial(plan, histories={'formation': 0.})
            stocks = full_stocks(plan)
            fresh = force_driven(plan, state, stocks)
            yielding(plan, state, stocks)                  # replaces the operator and its mode response
            again = force_driven(plan, state, stocks)
        self.assertEqual(published(again), published(fresh))
        self.assertGreater(fresh.descriptor()['initial_constitutive']['iterations'], 2)
        self.assertGreater(float(fresh.mechanics.array('generalized_rates_s_inv')[0]), 0.)


class ConstitutiveDepthTests(unittest.TestCase):
    def test_depth_is_measured_down_from_the_box_top_whatever_the_datum(self):
        profile = RheologyProfile('depth-control', 'tosi-linear', 'declared-analytic',
            (('contrast_T', 1.), ('contrast_z', 8.)))
        with prepare(profile) as plan:
            definition = plan.descriptor()
            self.assertIn('depth', definition)
            self.assertEqual(definition['vertical_datum'], 'bottom-z-zero')
            state = initial(plan, histories={'formation': 0.})
            xyz = np.indices((5, 5, 5)).reshape(3, -1).T/4
            velocity = np.zeros((125, 3)); velocity[:, 0] = .2*xyz[:, 1]
            result = advance(plan, state, .01, velocity_m_s=velocity, boundary_stocks=full_stocks(plan))
        # Horizontal shear is an exact solution for any viscosity layered in z,
        # so the published shear stress is 2*eta*D_xy = .2*eta at every Gauss point.
        points = np.polynomial.legendre.leggauss(3)[0]
        layer = np.indices((2, 2, 2)).reshape(3, -1).T[:, 2]
        point = np.indices((3, 3, 3)).reshape(3, -1).T[:, 2]
        height = (layer[:, None]+(points[point][None, :]+1)/2)/2
        stress = result.initial_mechanics.array('extra_plus_viscous_stress_pa')[..., 0, 1]
        assert_allclose(stress, .2*8.**(1.-height), rtol=1e-8)
        self.assertLess(stress[height > .9].max(), stress[height < .1].min())


if __name__ == '__main__':
    unittest.main()
