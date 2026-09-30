"""Automatic choice between the matrix-free and assembled regional 3D solvers.

SPDX-License-Identifier: AGPL-3.0-only

Routing, out-of-range inputs, explicit overrides, resource refusal, changed
coefficients, prepared-state reuse and continuation of saved evolution states.
The rule itself is exercised on recorded features (no solves); plan checks use
small grids, except the 8-cell cases that reach the multigrid branch on a
realistic workload.
"""
from concurrent.futures import CancelledError
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_array_equal

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src'), str(Path(__file__).resolve().parent)]
import test_regional_execution3d as reference
from atlas_tectonics import regional_multigrid3d as multigrid3d
from atlas_tectonics import regional_solver_selection3d as selection
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.regional_elements3d import TaylorHoodBox
from atlas_tectonics.regional_execution import RegionalMechanicsScales
from atlas_tectonics.regional_execution3d import PreparedRegionalStokes3D, SIDES
from atlas_tectonics.resources import MemoryLimitError, WorkBudget

LARGE = 64*1024**3


def features(cells=(8, 8, 8), contrast=3., aspect=1., closed=True):
    return dict(cells=list(cells), cell_count=int(np.prod(cells)), min_axis_cells=min(cells),
                element_aspect=aspect, log10_viscosity_contrast=contrast, closed_box=closed,
                traction_components=0 if closed else 3)


def choose(f, *, needs=(100, 100), available=1000):
    return selection.select(f, dict(gmres=needs[0], multigrid=needs[1]), available)


def case(name, n):
    from benchmark_regional3d_solvers import case_inputs
    return case_inputs(name, n)


def plan_for(spec, method='auto', budget=None, eta=None, **kwargs):
    length, speed = spec['scales']
    return PreparedRegionalStokes3D(list(spec['cells']), spec['lengths'], spec['eta'] if eta is None else eta,
        spec['boundary'], scales=RegionalMechanicsScales(length, speed),
        reference_viscosity_pa_s=spec['reference_viscosity'], frame_id='benchmark-Cartesian',
        vertical_datum='box-bottom-z-zero', material_source=kwargs.pop('material_source', 'selection-test'),
        physical_mean_pressure_pa=spec['mean_pressure'], method=method,
        budget=WorkBudget(LARGE) if budget is None else budget, **kwargs)


def solve_spec(plan, spec):
    tractions = {side: np.zeros(plan.coordinates(side).shape) for side in SIDES}
    return plan.solve(spec['force'], spec['velocity'], tractions, parent_state_id='selection-parent',
                      epoch_id='same-time', time_s=0., force_source='selection-force',
                      boundary_source='selection-boundary')


def assert_same_arrays(a, b):
    assert a.array_names == b.array_names
    for name in b.array_names:
        assert_array_equal(a.array(name), b.array(name))


class SelectionRuleTests(unittest.TestCase):
    """The rule on recorded features; no plan is prepared."""
    def test_admission_decides_first(self):
        self.assertIsNone(choose(features(), available=99)['method'])
        only = choose(features(), needs=(100, 200), available=150)
        self.assertEqual((only['method'], only['reason']), ('gmres', 'only gmres is admitted by the budget'))
        only = choose(features(contrast=9.), needs=(200, 100), available=150)
        self.assertEqual(only['method'], 'multigrid')
        self.assertIn('outside its shown range', only['reason'])
        self.assertFalse(only['multigrid_supported'])

    def test_multigrid_inside_its_shown_range(self):
        top = selection.MAX_LOG10_CONTRAST
        for f in (features((4, 4, 4), 0.), features((8, 8, 8), top), features((24, 24, 24), 3.),
                  features((16, 16, 8), top, selection.MAX_ELEMENT_ASPECT), features((5, 7, 9), 1., 1.3),
                  features((16, 16, 4), selection.FLAT_LOG10_CONTRAST, selection.FLAT_ELEMENT_ASPECT)):
            with self.subTest(features=f):
                record = choose(f)
                self.assertEqual(record['method'], 'multigrid')
                self.assertTrue(record['multigrid_supported'])
                self.assertEqual(record['unsupported'], [])

    def test_known_weak_inputs_keep_the_assembled_route(self):
        for f, reason in ((features(contrast=selection.MAX_LOG10_CONTRAST+.1), 'contrast'),
                          (features(aspect=selection.FLAT_ELEMENT_ASPECT*1.1, contrast=0.), 'aspect'),
                          (features(aspect=selection.MAX_ELEMENT_ASPECT*1.1,
                                    contrast=selection.FLAT_LOG10_CONTRAST+.1), 'with viscosity contrast'),
                          (features(cells=(3, 8, 8)), 'cells along an axis'),
                          (features(cells=(2, 2, 2)), 'cells along an axis')):
            with self.subTest(reason=reason):
                record = choose(f)
                self.assertEqual((record['method'], record['reason']),
                                 ('gmres', 'outside the range where multigrid has been shown to converge'))
                self.assertTrue(any(reason in r for r in record['unsupported']))

    def test_record_is_deterministic(self):
        f = features((9, 7, 8), 3.2, 1.5)
        self.assertEqual(choose(f), choose(dict(f)))
        self.assertEqual(choose(f)['policy'], selection.POLICY)

    def test_features_are_scale_free(self):
        cells, spacing = (4, 4, 2), (1., 1., .5)
        eta = np.full((32, 27), 3e21)
        eta[:16] *= 1e-3
        f = selection.workload_features(cells, spacing, eta, reference.pattern())
        self.assertEqual((f['log10_viscosity_contrast'], f['element_aspect'], f['cell_count'],
                          f['min_axis_cells']), (3., 2., 32, 2))
        self.assertEqual(f, selection.workload_features(cells, np.asarray(spacing)*7, eta*1e5, reference.pattern()))
        self.assertTrue(f['closed_box'])


class AdmissionPredictionTests(unittest.TestCase):
    def test_predicted_bytes_equal_each_methods_reservation(self):
        closed, open_top = reference.pattern(), case('lithosphere', 4)['boundary']
        mixed = dict(closed, z1=('traction',)*3, x1=('velocity', 'traction', 'traction'))
        for cells, lengths, boundary in (((2, 2, 2), (1., 1., 1.), closed), ((3, 2, 4), (1.3, .7, 1.1), mixed),
                                         ((4, 4, 4), (2., 2., 1.), open_top), ((5, 3, 4), (1., 1., 3.), mixed)):
            auto = reference.prepare(cells=cells, lengths=lengths, boundary=boundary, budget=WorkBudget(LARGE),
                                     physical_mean_pressure_pa=None)
            record = auto.solver_selection()
            auto.close()
            for method in ('gmres', 'multigrid'):
                budget = WorkBudget(LARGE)
                with reference.prepare(cells=cells, lengths=lengths, boundary=boundary, method=method,
                                       budget=budget, physical_mean_pressure_pa=None) as plan:
                    self.assertEqual(budget.peak_reserved_bytes, record['admission'][method]['bytes'],
                                     (cells, method))
                    if method == 'gmres':
                        nnz, free = selection.assembled_free_nonzeros(cells, boundary)
                        self.assertEqual((nnz, free), (plan._Af.nnz, plan._Af.shape[0]))

    def test_multigrid_levels_follow_the_prepared_hierarchy(self):
        for cells, lengths in (((16, 16, 8), (1., 1., 1.)), ((12, 12, 12), (1., 1., .1)), ((20, 6, 9), (3., 1., 1.))):
            mesh = TaylorHoodBox(cells, lengths)
            fixed = multigrid3d._node_mask(tuple(2*n+1 for n in cells), reference.pattern())
            geometry = multigrid3d.StructuredGeometry(mesh, reference.pattern(), np.flatnonzero(fixed),
                                                      np.flatnonzero(~fixed), np.zeros((1, 1)))
            projected = multigrid3d.projected_bytes(cells)
            expected = projected['structure']+projected['work']+multigrid3d.factor_allowance(geometry)
            self.assertEqual(selection.multigrid_bytes(cells, np.asarray(mesh._spacing), reference.pattern()),
                             expected, cells)


class AutoPlanTests(unittest.TestCase):
    def test_default_is_auto_and_records_the_choice(self):
        with reference.prepare() as plan:               # 2x2x2: too thin to coarsen
            d = plan.descriptor()
            self.assertEqual((plan.requested_method, plan.method), ('auto', 'gmres'))
            self.assertEqual((d['requested_method'], d['method']), ('auto', 'gmres'))
            self.assertEqual(d['solver_selection']['policy'], selection.POLICY)
            self.assertEqual(d['solver_selection'], plan.solver_selection())
            self.assertIn('fewer than 4 cells along an axis', d['solver_selection']['unsupported'])
            stats = plan.statistics()['solver_selection']
            self.assertEqual((stats['method'], stats['requested']), ('gmres', 'auto'))
            self.assertLess(stats['seconds'], 1.)
            result = reference.solve(plan, force=1.)
            self.assertEqual(result.descriptor()['plan']['solver_selection']['reason'], d['solver_selection']['reason'])
        with reference.prepare() as again:
            self.assertEqual(again.plan_id, plan.plan_id)
        with reference.prepare(cells=(4, 4, 4)) as plan:
            self.assertEqual(plan.method, 'multigrid')

    def test_explicit_methods_are_honoured_and_unrecorded(self):
        for method in ('gmres', 'direct', 'multigrid'):
            with self.subTest(method=method), reference.prepare(cells=(4, 4, 4), method=method) as plan:
                d = plan.descriptor()
                self.assertEqual((plan.method, plan.requested_method, d['method']), (method, method, method))
                self.assertNotIn('requested_method', d)
                self.assertNotIn('solver_selection', d)
                self.assertIsNone(plan.solver_selection())
                self.assertNotIn('solver_selection', plan.statistics())
        with self.assertRaisesRegex(TectonicsError, 'auto, gmres'):
            reference.prepare(method='ilu')

    def test_memory_decides_when_only_one_method_fits(self):
        spec = case('inclusion', 6)
        with plan_for(spec) as probe:
            needs = probe.solver_selection()['admission']
        budget = WorkBudget((needs['gmres']['bytes']+needs['multigrid']['bytes'])//2)
        with self.assertRaises(MemoryLimitError):
            plan_for(spec, method='gmres', budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        high = np.where(spec['eta'] < 1e20, 1e14, spec['eta'])                  # contrast 1e7
        with plan_for(spec, eta=high, budget=budget) as plan:
            self.assertEqual(plan.method, 'multigrid')
            self.assertEqual(plan.solver_selection()['reason'],
                             'only multigrid is admitted by the budget; outside its shown range')

    def test_refusal_when_neither_method_fits(self):
        budget = WorkBudget(1024)
        with self.assertRaisesRegex(MemoryLimitError, 'neither gmres .* nor multigrid'):
            reference.prepare(budget=budget)
        self.assertEqual((budget.reserved_bytes, budget.peak_reserved_bytes), (0, 0))

    def test_a_failed_multigrid_preparation_is_not_retried_with_gmres(self):
        spec = case('lithosphere', 8)
        budget = WorkBudget(LARGE)
        with mock.patch.object(multigrid3d, 'MultigridStokes', side_effect=ValueError('injected')), \
                self.assertRaisesRegex(TectonicsError, 'multigrid preparation refused: injected'):
            plan_for(spec, budget=budget)
        stats = budget.statistics()
        self.assertEqual(stats['reserved_bytes'], 0)
        self.assertNotIn('regional3d-assembly', stats['category_peaks'])
        self.assertIn('regional3d-multigrid', stats['category_peaks'])

    def test_auto_publishes_exactly_what_the_resolved_method_publishes(self):
        spec = case('lithosphere', 8)
        with plan_for(spec) as auto, plan_for(spec, method='multigrid') as explicit:
            self.assertEqual(auto.method, 'multigrid')
            a, b = solve_spec(auto, spec), solve_spec(explicit, spec)
            assert_same_arrays(a, b)
            self.assertEqual(a.descriptor()['krylov_iterations'], b.descriptor()['krylov_iterations'])
        small = case('smooth', 4)
        ramp = np.linspace(0, 1, 64*27).reshape(64, 27)
        steep = np.asarray(small['eta'])*10**((selection.MAX_LOG10_CONTRAST+1)*ramp)    # above the range
        with plan_for(small, eta=steep) as auto, plan_for(small, eta=steep, method='gmres') as explicit:
            self.assertEqual(auto.method, 'gmres')
            assert_same_arrays(solve_spec(auto, small), solve_spec(explicit, small))

    def test_changed_viscosity_selects_as_a_fresh_plan_and_reuses_only_within_a_method(self):
        spec = case('lithosphere', 8)
        budget = WorkBudget(LARGE)
        rough = np.where(spec['eta'] > 1e22, 1e27, spec['eta'])                 # contrast 1e7
        plan = plan_for(spec, budget=budget)
        self.assertEqual(plan.method, 'multigrid')
        switched = plan.with_viscosity(rough, material_source='rough', release=True)
        self.assertEqual(switched.method, 'gmres')
        self.assertIn('contrast', ' '.join(switched.solver_selection()['unsupported']))
        self.assertFalse(switched._reused)
        with plan_for(spec, eta=rough, material_source='rough') as fresh:
            self.assertEqual(fresh.plan_id, switched.plan_id)
        back = switched.with_viscosity(spec['eta'], material_source='back', release=True)
        self.assertEqual(back.method, 'multigrid')
        self.assertFalse(back.statistics()['geometry_reused'])
        kept = back.with_viscosity(spec['eta']*1.1, material_source='kept', release=True)
        self.assertEqual(kept.method, 'multigrid')
        self.assertTrue(kept.statistics()['geometry_reused'])
        with plan_for(spec, eta=spec['eta']*1.1, material_source='kept') as fresh:
            self.assertEqual(fresh.plan_id, kept.plan_id)
            assert_same_arrays(solve_spec(kept, spec), solve_spec(fresh, spec))
        kept.close()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_explicit_reuse_keeps_its_method(self):
        with reference.prepare(cells=(3, 3, 3), method='multigrid') as plan:
            with plan.with_viscosity(5., material_source='changed') as changed:
                self.assertEqual((changed.method, changed.requested_method), ('multigrid', 'multigrid'))
                self.assertIsNone(changed.solver_selection())
                self.assertTrue(changed.statistics()['geometry_reused'])

    def test_cancellation_returns_every_reservation(self):
        budget = WorkBudget(LARGE)
        event = threading.Event()
        event.set()
        for spec in (case('smooth', 4), case('lithosphere', 8)):
            with self.subTest(cells=spec['cells']), self.assertRaises(CancelledError):
                plan_for(spec, budget=budget, cancel=event)
            self.assertEqual(budget.reserved_bytes, 0)


class EvolutionSelectionTests(unittest.TestCase):
    def test_default_evolution_records_request_and_policy(self):
        import test_regional_evolution3d as evolution
        with evolution.prepare() as plan:
            d = plan.descriptor()
            self.assertEqual((d['mechanics_method'], d['mechanics_selection_policy']), ('auto', selection.POLICY))
            result = evolution.advance(plan, evolution.initial(plan))
            chosen = result.mechanics.descriptor()['plan']
            self.assertEqual((chosen['requested_method'], chosen['method']), ('auto', 'gmres'))
            stats = plan.statistics()
            self.assertEqual(stats['mechanical_methods'], {'gmres': stats['mechanical_preparations']})
            self.assertEqual(stats['mechanical_method_switches'], 0)
        for method in ('gmres', 'direct', 'multigrid'):
            with self.subTest(method=method), evolution.prepare(mechanics_method=method) as plan:
                self.assertNotIn('mechanics_selection_policy', plan.descriptor())

    def test_evolution_counts_resolved_methods_and_real_reuse(self):
        import test_regional_evolution3d as evolution
        from atlas_tectonics.constitutive import RheologyProfile
        profile = RheologyProfile('thermal-control', 'tosi-linear', 'declared-analytic',
                                  (('contrast_T', 10.), ('contrast_z', 1.)))
        with evolution.prepare(profile, cells=(4, 4, 4)) as plan:
            result = evolution.advance(plan, evolution.initial(plan))
            stats = plan.statistics()
            self.assertEqual(stats['mechanical_methods'], {'multigrid': stats['mechanical_preparations']})
            self.assertGreater(stats['mechanical_preparations'], 1)
            self.assertEqual(stats['mechanical_geometry_reuses'], stats['mechanical_preparations']-1)
            self.assertEqual(stats['mechanical_method_switches'], 0)
            self.assertEqual(result.mechanics.descriptor()['plan']['method'], 'multigrid')

    def test_saved_states_continue_only_under_their_recorded_method(self):
        import test_regional_evolution3d as evolution
        with evolution.prepare(mechanics_method='gmres') as recorded:
            state = evolution.advance(recorded, evolution.initial(recorded)).state
            with evolution.prepare() as auto, self.assertRaisesRegex(TectonicsError, 'different regional plan'):
                evolution.advance(auto, state)
            with evolution.prepare(mechanics_method=recorded.descriptor()['mechanics_method']) as same:
                self.assertEqual(same.plan_id, recorded.plan_id)
                continued = evolution.advance(same, state)
                self.assertEqual(continued.mechanics.descriptor()['plan']['method'], 'gmres')
                self.assertNotIn('solver_selection', continued.mechanics.descriptor()['plan'])
        with evolution.prepare() as first:
            state = evolution.advance(first, evolution.initial(first)).state
            with evolution.prepare(mechanics_method='gmres') as explicit, \
                    self.assertRaisesRegex(TectonicsError, 'different regional plan'):
                evolution.advance(explicit, state)
            with evolution.prepare() as reopened:
                self.assertEqual(reopened.plan_id, first.plan_id)
                resumed = evolution.advance(reopened, state).mechanics.descriptor()['plan']
                self.assertEqual((resumed['requested_method'], resumed['method']), ('auto', 'gmres'))
            # A different policy could decide differently: refused, not rerouted.
            with mock.patch('atlas_tectonics.regional_evolution3d._SELECTION_POLICY', 'another-policy'):
                with evolution.prepare() as other, self.assertRaisesRegex(TectonicsError, 'different regional plan'):
                    evolution.advance(other, state)

    def test_saved_auto_state_refuses_a_changed_admission_context(self):
        import test_regional_evolution3d as evolution
        with evolution.prepare(cells=(4, 4, 4), budget=WorkBudget(75*1024**2)) as recorded:
            admission = recorded.descriptor()['mechanics_selection_admission']
            self.assertEqual(admission, {'gmres': True, 'multigrid': False})
            first = evolution.advance(recorded, evolution.initial(recorded))
            self.assertEqual(first.mechanics.descriptor()['plan']['method'], 'gmres')
            with evolution.prepare(cells=(4, 4, 4), budget=WorkBudget(256*1024**2)) as reopened:
                self.assertEqual(reopened.descriptor()['mechanics_selection_admission'],
                                 {'gmres': True, 'multigrid': True})
                self.assertNotEqual(reopened.plan_id, recorded.plan_id)
                with self.assertRaisesRegex(TectonicsError, 'different regional plan'):
                    evolution.advance(reopened, first.state)
                self.assertEqual(reopened.statistics()['mechanical_preparations'], 0)

    def test_saved_auto_state_accepts_different_budgets_with_the_same_admission(self):
        import test_regional_evolution3d as evolution
        with evolution.prepare(cells=(4, 4, 4), budget=WorkBudget(75*1024**2)) as recorded:
            first = evolution.advance(recorded, evolution.initial(recorded))
            with evolution.prepare(cells=(4, 4, 4), budget=WorkBudget(76*1024**2)) as reopened:
                self.assertEqual(reopened.descriptor()['mechanics_selection_admission'],
                                 recorded.descriptor()['mechanics_selection_admission'])
                self.assertEqual(reopened.plan_id, recorded.plan_id)
                continued = evolution.advance(reopened, first.state)
                self.assertEqual(continued.mechanics.descriptor()['plan']['method'], 'gmres')
                self.assertAlmostEqual(continued.state.descriptor()['time_s'], .2)

    def test_temporary_budget_contention_refuses_without_rerouting_auto(self):
        import test_regional_evolution3d as evolution
        for parented in (False, True):
            with self.subTest(parented=parented):
                shared = WorkBudget(128*1024**2)
                budget = WorkBudget(128*1024**2, parent=shared) if parented else shared
                with evolution.prepare(cells=(4, 4, 4), budget=budget) as plan:
                    admission = plan.descriptor()['mechanics_selection_admission']
                    self.assertEqual(admission, {'gmres': True, 'multigrid': True})
                    plan_id = plan.plan_id
                    state = evolution.initial(plan)
                    retained = shared.reserved_bytes
                    # Leave enough for GMRES but not multigrid. The already prepared
                    # evolution must retain its choice and refuse the occupied budget.
                    with shared.reserve(shared.available_bytes-75*1024**2, category='test-contention'):
                        occupied = shared.reserved_bytes
                        with self.assertRaises(MemoryLimitError):
                            evolution.advance(plan, state)
                        self.assertEqual(shared.reserved_bytes, occupied)
                        self.assertEqual(plan.statistics()['mechanical_preparations'], 0)
                    self.assertEqual(shared.reserved_bytes, retained)
                    self.assertEqual(plan.plan_id, plan_id)
                    self.assertEqual(plan.descriptor()['mechanics_selection_admission'], admission)
                    resumed = evolution.advance(plan, state)
                    self.assertEqual(resumed.mechanics.descriptor()['plan']['method'], 'multigrid')
                    self.assertEqual(plan.statistics()['mechanical_method_switches'], 0)


if __name__ == '__main__':
    unittest.main()
