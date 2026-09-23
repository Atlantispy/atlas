"""Focused W06 Step-2 checks against independent scalar birth trajectories."""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError
import hashlib
import json
import math
from pathlib import Path
from threading import Event
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (ColumnGrid1D, PreparedRidgeSpreading, RidgeMotion,
                             SpreadingPhase, ridge_cell_geometry)
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from w06_spreading_reference import (parcel_position_m, reference_accounts,
                                     reference_birth_moments, reference_geometry)


ROOT = Path(__file__).resolve().parents[1]
CASE = json.loads((ROOT/'cases/w06_spreading.json').read_text(encoding='utf-8'))
YEAR = CASE['seconds_per_year']
ROUNDOFF = CASE['material_roundoff_eps_multiplier']*np.finfo(np.float64).eps


def motion_arguments(case=CASE):
    result = dict(case['motion'])
    for name in ('left', 'right', 'ridge'):
        result[name+'_velocity_m_s'] = result.pop(name+'_velocity_m_per_year')/case['seconds_per_year']
    return result


def reference_arguments(motion):
    return {name: getattr(motion, name) for name in (
        'ridge_position_m', 'left_velocity_m_s', 'right_velocity_m_s', 'ridge_velocity_m_s')}


def phase_records(phases):
    return [{name: getattr(phase, name) for name in (
        'thickness_m', 'density_kg_m3', 'stock_kg')} for phase in phases]


class W06SpreadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = ExecutionContext('reference')

    @classmethod
    def tearDownClass(cls):
        cls.context.close()

    def fixture(self, *, edges=None, dx=500., motion=None, phases=None, **changes):
        if edges is None:
            left, right = CASE['domain_m']
            edges = np.linspace(left, right, round((right-left)/dx)+1)
        grid = ColumnGrid1D(edges, frame_id=CASE['frame_id'])
        motion = RidgeMotion(**motion_arguments()) if motion is None else motion
        phases = tuple(SpreadingPhase(**row) for row in CASE['phases']) if phases is None else phases
        arguments = dict(time_s=CASE['time_s'], epoch_id=CASE['epoch_id'],
                         width_m=CASE['width_m'], source_id=CASE['case_id'], context=self.context)
        arguments.update(changes)
        return PreparedRidgeSpreading(grid, motion, phases, **arguments)

    def assert_geometry(self, actual, expected):
        self.assertEqual(actual.dtype, np.dtype('float64'))
        self.assertEqual(actual.shape, expected.shape)
        assert_array_equal(actual[..., 0] > 0., expected[..., 0] > 0.)
        assert_allclose(actual[..., 0], expected[..., 0], rtol=0., atol=CASE['position_error_m'])
        assert_allclose(actual[..., 1:], expected[..., 1:], rtol=0., atol=CASE['age_error_s'])
        assert_array_equal(actual[actual[..., 0] == 0.], 0.)

    def assert_accounts(self, actual, expected, phases):
        self.assertEqual(actual.shape, (len(phases), 6))
        for index, phase in enumerate(phases):
            scale = max(*(abs(float(x)) for x in expected[index, (0, 2, 3, 4)]),
                        np.finfo(float).tiny)
            assert_allclose(actual[index, (0, 2, 3, 4)], expected[index, (0, 2, 3, 4)],
                            rtol=0., atol=ROUNDOFF*scale)
            self.assertLessEqual(abs(float(actual[index, 5])), ROUNDOFF*scale)
            self.assertAlmostEqual(float(actual[index, 0]+actual[index, 1]), phase.stock_kg,
                                   delta=ROUNDOFF*max(phase.stock_kg, np.finfo(float).tiny))
            self.assertAlmostEqual(float(actual[index, 1]), float(expected[index, 1]),
                                   delta=ROUNDOFF*max(phase.stock_kg, np.finfo(float).tiny))

    def test_frozen_case_and_all_outputs_on_three_grids(self):
        design = ROOT/CASE['frozen_design']['path']
        self.assertEqual(hashlib.sha256(design.read_bytes()).hexdigest(),
                         CASE['frozen_design']['sha256'], 'review changed design; no silent repin')
        outputs = sorted((*CASE['output_years'], CASE['partial_cell_years']))
        for dx in CASE['grid_spacing_m']:
            with self.subTest(dx=dx), self.fixture(dx=dx) as plan:
                state = plan.initial
                args = reference_arguments(plan.motion)
                for years in outputs:
                    time = years*YEAR
                    state = plan.advance(state, time_s=time)
                    expected = reference_geometry(plan.grid.edges_m, time, **args)
                    self.assert_geometry(state.cell_geometry, expected)
                    self.assert_geometry(ridge_cell_geometry(plan.grid, plan.motion, time), expected)
                    account = reference_accounts(plan.grid.edges_m, time, phase_records(plan.phases),
                        width_m=plan.width_m, **args)
                    self.assert_accounts(state.accounts_kg, account, plan.phases)
                    occupied = np.sum(expected[..., 0], axis=0)/plan.grid.widths_m
                    projected = np.array([p.thickness_m for p in plan.phases])[:, None]*occupied
                    assert_allclose(plan.phase_thickness(state), projected, rtol=0.,
                                    atol=CASE['position_error_m'])
                    self.assertAlmostEqual(math.fsum(state.cell_geometry[..., 0].flat),
                        .04*years, delta=CASE['position_error_m'])
                assert_allclose(state.accounts_kg[:, 0], CASE['final_created_mass_kg'],
                                rtol=ROUNDOFF, atol=0.)

    def test_partial_cells_preserve_full_formation_distribution_and_moments(self):
        elapsed = CASE['partial_cell_years']*YEAR
        epoch_offset = 7.*YEAR
        with self.fixture(dx=500., time_s=epoch_offset) as plan:
            state = plan.advance(plan.initial, time_s=epoch_offset+elapsed)
            geometry = state.cell_geometry
            occupied = geometry[..., 0] > 0.
            partial = (geometry[..., 0] > 0.) & (geometry[..., 0] < 500.-CASE['position_error_m'])
            self.assertEqual(int(np.sum(partial)), 2)
            assert_allclose(geometry[..., 0][partial], 125., rtol=0., atol=CASE['position_error_m'])
            youngest_birth = elapsed-geometry[..., 1]
            oldest_birth = elapsed-geometry[..., 2]
            expected = reference_birth_moments(plan.grid.edges_m, elapsed, **reference_arguments(plan.motion))
            reference_cells = reference_geometry(plan.grid.edges_m, elapsed, **reference_arguments(plan.motion))
            self.assert_geometry(geometry, reference_cells)
            first = geometry[..., 0]*(.5*youngest_birth+.5*oldest_birth)
            second = geometry[..., 0]*(oldest_birth**2+oldest_birth*youngest_birth+youngest_birth**2)/3.
            # Compare means using each integrator's own occupied width. Widths
            # have their separate frozen metre gate; mixing denominators would
            # multiply harmless area roundoff by the large epoch offset.
            width = geometry[..., 0][occupied]
            reference_width = reference_cells[..., 0][occupied]
            self.assertLessEqual(float(np.max(np.abs(first[occupied]/width-
                                                     expected[..., 0][occupied]/reference_width))),
                                 CASE['age_error_s'])
            self.assertLessEqual(float(np.max(np.abs(second[occupied]/width-
                                                     expected[..., 1][occupied]/reference_width))),
                                 2.*elapsed*CASE['age_error_s'])
            self.assertTrue(np.all(youngest_birth[occupied] > oldest_birth[occupied]))
            self.assertEqual(len(state.strips), 2)
            for strip, side in zip(state.strips, ('left', 'right')):
                self.assertEqual(strip.side, side)
                self.assertEqual(strip.plate_id, getattr(plan.motion, side+'_plate_id'))
                self.assertEqual(strip.ridge_id, plan.motion.ridge_id)
                self.assertEqual(strip.event_id, plan.motion.event_id)
                velocity = getattr(plan.motion, side+'_velocity_m_s')
                for position, birth in ((strip.left_m, strip.birth_offset_left_s),
                                        (strip.right_m, strip.birth_offset_right_s)):
                    expected_position = parcel_position_m(birth, elapsed,
                        ridge_position_m=plan.motion.ridge_position_m,
                        ridge_velocity_m_s=plan.motion.ridge_velocity_m_s,
                        plate_velocity_m_s=velocity)
                    self.assertAlmostEqual(position, expected_position, delta=CASE['position_error_m'])

    def test_independent_exports_and_enlarged_domain(self):
        end = CASE['duration_years']*YEAR
        outputs = []
        for bounds in (CASE['domain_m'], CASE['enlarged_domain_m'], CASE['export_domain_m']):
            edges = np.linspace(*bounds, round((bounds[1]-bounds[0])/500.)+1)
            with self.fixture(edges=edges) as plan:
                state = plan.advance(plan.initial, time_s=end)
                reference = reference_accounts(edges, end, phase_records(plan.phases),
                    width_m=plan.width_m, **reference_arguments(plan.motion))
                self.assert_accounts(state.accounts_kg, reference, plan.phases)
                centres = plan.grid.centres_m
                common = (centres > -100000.) & (centres < 100000.)
                outputs.append(state.cell_geometry[:, common, :])
                if bounds == CASE['export_domain_m']:
                    assert_allclose(state.accounts_kg[0, (2, 3, 4)], [4.06e12, 6.09e12, 6.09e12],
                                    rtol=ROUNDOFF, atol=0.)
                else:
                    assert_array_equal(state.accounts_kg[:, 3:5], 0.)
        assert_array_equal(outputs[0], outputs[1])
        assert_array_equal(outputs[0], outputs[2])

    def test_32_64_128_partitions_do_not_bin_history_or_duplicate_births(self):
        end = CASE['duration_years']*YEAR
        with self.fixture() as plan:
            direct = plan.advance(plan.initial, time_s=end)
            for count in CASE['time_intervals']:
                state = plan.initial
                for index in range(1, count+1):
                    state = plan.advance(state, time_s=end*index/count)
                self.assertEqual(state.intervals, count)
                assert_array_equal(state.cell_geometry, direct.cell_geometry)
                assert_array_equal(state.accounts_kg, direct.accounts_kg)
                self.assertEqual(state.strips, direct.strips)
                self.assertNotEqual(state.state_id, direct.state_id)

    def test_empty_repeated_endpoints_and_immutable_views(self):
        with self.fixture(dx=1000.) as plan:
            initial = plan.initial
            self.assertEqual(initial.time_s, 0.)
            self.assertEqual(initial.intervals, 0)
            assert_array_equal(initial.cell_geometry, 0.)
            assert_array_equal(initial.accounts_kg[:, (0, 2, 3, 4, 5)], 0.)
            self.assertIs(plan.advance(initial, time_s=0.), initial)
            state = plan.advance(initial, time_s=5e6*YEAR)
            self.assertIs(plan.advance(state, time_s=state.time_s), state)
            self.assertEqual(state.parent_state_id, initial.state_id)
            ages = state.cell_geometry[..., 1:]
            valid = state.cell_geometry[..., 0] > 0.
            self.assertEqual(float(np.min(ages[..., 0][valid])), 0.)
            self.assertAlmostEqual(float(np.max(ages[..., 1][valid])), state.elapsed_s, delta=1.)
            for array in (state.cell_geometry, state.accounts_kg, plan.phase_thickness(state)):
                with self.assertRaises(ValueError):
                    array.setflags(write=True)
            view = state.cell_geometry
            view.shape = (view.size,)
            self.assertEqual(state.cell_geometry.shape, (2, plan.grid.cells, 3))
            with self.assertRaises(FrozenInstanceError):
                state.time_s = 0.
            with self.assertRaises(FrozenInstanceError):
                plan.phases[0].stock_kg = 1.

    def test_nonuniform_cell_straddling_ridge_retains_both_sides(self):
        motion = RidgeMotion(.1, -.2, .35, 0., 'left', 'right', 'ridge', 'onset', 'motion')
        edges = [-3., -.2, .15, .8, 3.]
        with self.fixture(edges=edges, motion=motion) as plan:
            state = plan.advance(plan.initial, time_s=4.)
            expected = reference_geometry(edges, 4., **reference_arguments(motion))
            self.assert_geometry(state.cell_geometry, expected)
            self.assertTrue(np.all(state.cell_geometry[:, 1, 0] > 0.))
            self.assertAlmostEqual(float(np.sum(state.cell_geometry[:, 1, 0])), .35, delta=1e-15)
            self.assertEqual(state.cell_geometry[0, 1, 1], 0.)
            self.assertEqual(state.cell_geometry[1, 1, 1], 0.)

    def test_finite_stock_exhaustion_is_transactional_and_exact_endpoint_supported(self):
        motion = RidgeMotion(0., -.5, .5, 0., 'left', 'right', 'ridge', 'onset', 'motion')
        phases = (SpreadingPhase('crust', 'finite-a', 4., 2., 48.),
                  SpreadingPhase('mantle', 'finite-b', 5., 3., 90.))
        with self.fixture(edges=[-4., 0., 4.], motion=motion, phases=phases, width_m=2.) as plan:
            original = (plan.initial.state_id, plan.initial.cell_geometry.tobytes(), plan.initial.accounts_kg.tobytes())
            with self.assertRaises(TectonicsError):
                plan.advance(plan.initial, time_s=4.)
            self.assertEqual(original, (plan.initial.state_id, plan.initial.cell_geometry.tobytes(),
                                       plan.initial.accounts_kg.tobytes()))
            final = plan.advance(plan.initial, time_s=3.)
            assert_array_equal(final.accounts_kg[:, 1], 0.)
            self.assertIs(plan.advance(final, time_s=3.), final)
            with self.assertRaises(TectonicsError):
                plan.advance(final, time_s=3.01)
            assert_array_equal(final.accounts_kg[:, 0], [48., 90.])

    def test_constant_asymmetry_migration_and_frame_change(self):
        args = dict(ridge_position_m=.125, left_velocity_m_s=-.02,
                    right_velocity_m_s=.04, ridge_velocity_m_s=.005,
                    left_plate_id='left', right_plate_id='right', ridge_id='ridge',
                    event_id='onset', source_id='moving-ridge')
        elapsed = 20.
        edges = np.array([-2., -.7, -.1, .2, .5, 1., 3.])
        with self.fixture(edges=edges, motion=RidgeMotion(**args)) as plan:
            state = plan.advance(plan.initial, time_s=elapsed)
            self.assert_geometry(state.cell_geometry, reference_geometry(edges, elapsed,
                                 **reference_arguments(plan.motion)))
            baseline_geometry, baseline_accounts = state.cell_geometry, state.accounts_kg
        # A moving-frame output changes all velocities by V and output bounds
        # by V*t, with a further fixed origin translation. Both tests stay inside
        # the supported outward-in-this-frame family and have no boundary loss.
        shift, velocity_shift = 1234., .01
        changed = dict(args, ridge_position_m=args['ridge_position_m']+shift)
        for name in ('left_velocity_m_s', 'right_velocity_m_s', 'ridge_velocity_m_s'):
            changed[name] += velocity_shift
        transformed_edges = edges+shift+velocity_shift*elapsed
        with self.fixture(edges=transformed_edges, motion=RidgeMotion(**changed)) as plan:
            state = plan.advance(plan.initial, time_s=elapsed)
            self.assert_geometry(state.cell_geometry, baseline_geometry)
            self.assert_accounts(state.accounts_kg, baseline_accounts, plan.phases)

    def test_invalid_motion_definitions_and_backwards_clock_refuse(self):
        arguments = motion_arguments()
        for changes in (dict(left_velocity_m_s=1.), dict(right_velocity_m_s=-1.),
                        dict(ridge_velocity_m_s=arguments['right_velocity_m_s']),
                        dict(ridge_velocity_m_s=arguments['left_velocity_m_s']),
                        dict(ridge_position_m=math.nan), dict(ridge_id='')):
            with self.subTest(changes=changes), self.assertRaises(TectonicsError):
                motion = RidgeMotion(**dict(arguments, **changes))
                with self.fixture(motion=motion):
                    pass
        for changes in (dict(density_kg_m3=0.), dict(thickness_m=-1.),
                        dict(stock_kg=-1.), dict(stock_kg=math.inf), dict(source_id='')):
            with self.subTest(changes=changes), self.assertRaises(TectonicsError):
                SpreadingPhase(**dict(CASE['phases'][0], **changes))
        for changes in (dict(epoch_id=''), dict(width_m=0.), dict(source_id='')):
            with self.subTest(changes=changes), self.assertRaises(TectonicsError):
                self.fixture(**changes)
        with self.fixture() as plan:
            state = plan.advance(plan.initial, time_s=1.)
            for target in (0., math.nan, math.inf):
                with self.assertRaises(TectonicsError):
                    plan.advance(state, time_s=target)
        outside = RidgeMotion(0., -.02, .04, .01, 'left', 'right', 'ridge', 'onset', 'motion')
        with self.fixture(edges=[-1., 0., 1.], motion=outside) as plan:
            with self.assertRaises(TectonicsError):
                plan.advance(plan.initial, time_s=200.)

    def test_cancel_budget_foreign_closed_and_live_source_guards(self):
        owner = WorkBudget(CASE['work_budget_bytes'])
        event = Event(); event.set()
        with self.assertRaises(CancelledError):
            self.fixture(budget=owner, cancel=event)
        self.assertEqual(owner.reserved_bytes, 0)
        with self.assertRaises(MemoryLimitError):
            self.fixture(budget=WorkBudget(1))
        plan = self.fixture(budget=owner)
        retained = owner.reserved_bytes
        try:
            with self.fixture(source_id='other-plan') as foreign:
                with self.assertRaises(TectonicsError):
                    plan.advance(foreign.initial, time_s=1.)
            with self.assertRaises(CancelledError):
                plan.advance(plan.initial, time_s=1., cancel=event)
            with self.assertRaises(CancelledError):
                ridge_cell_geometry(plan.grid, plan.motion, 1., cancel=event)
            with self.assertRaises(MemoryLimitError):
                plan.advance(plan.initial, time_s=1., budget=WorkBudget(1, parent=owner))
            with self.assertRaises(MemoryLimitError):
                plan.phase_thickness(plan.initial, budget=WorkBudget(1, parent=owner))
            self.assertEqual(owner.reserved_bytes, retained)
            import atlas_tectonics.spreading as spreading
            with mock.patch.object(spreading, 'ridge_cell_geometry', lambda *args, **kwargs: None):
                with self.assertRaises(TectonicsError):
                    plan.advance(plan.initial, time_s=1.)
            with mock.patch.object(self.context, 'verify', wraps=self.context.verify) as verify:
                plan.advance(plan.initial, time_s=0.)
                self.assertEqual(verify.call_count, 1)
            with mock.patch.object(self.context, 'verify', wraps=self.context.verify) as verify:
                plan.phase_thickness(plan.initial)
                self.assertEqual(verify.call_count, 2)  # Bracket computed projections with source checks.
        finally:
            plan.close()
        self.assertEqual(owner.reserved_bytes, 0)
        with self.assertRaises(TectonicsError):
            plan.advance(plan.initial, time_s=1.)
        with self.assertRaises(TectonicsError):
            plan.phase_thickness(plan.initial)

    def test_accepted_interval_ceiling_is_256(self):
        with self.fixture(edges=[-1., 0., 1.]) as plan:
            state = plan.initial
            for time in range(1, CASE['maximum_intervals']+1):
                state = plan.advance(state, time_s=float(time))
            self.assertEqual(state.intervals, 256)
            self.assertIs(plan.advance(state, time_s=256.), state)
            with self.assertRaises(TectonicsError):
                plan.advance(state, time_s=257.)


if __name__ == '__main__':
    unittest.main()
