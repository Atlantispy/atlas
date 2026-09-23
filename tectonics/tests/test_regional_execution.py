"""Focused W07 public boundary, source, scaling and reuse checks."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
import threading
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import regional_stokes, reuse
from atlas_tectonics.regional_execution import (PreparedRegionalStokes2D,
    RegionalMechanicsScales, RegionalReferencePressure)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics._validation import TectonicsError
from w07_reference_fields import fields, boundaries, dimensions


def pattern(case):
    return {side: {c: kind for c, (kind, _) in parts.items()}
            for side, parts in boundaries(case).items()}


def prepare(case='couette', n=4, **kwargs):
    width, height = dimensions(case)
    defaults = dict(scales=RegionalMechanicsScales(1., 1.), frame_id='synthetic-x-right-z-up',
                    vertical_datum='bottom-z-zero', material_source='synthetic-constant-Newtonian')
    defaults.update(kwargs)
    return PreparedRegionalStokes2D(n, n, width, height, 1., pattern(case), **defaults)


def inputs(case, plan):
    d = plan.descriptor()
    xu, zu = np.meshgrid(np.arange(d['nx']+1)*d['width_m']/d['nx'],
                         (np.arange(d['nz'])+.5)*d['height_m']/d['nz'])
    xw, zw = np.meshgrid((np.arange(d['nx'])+.5)*d['width_m']/d['nx'],
                         np.arange(d['nz']+1)*d['height_m']/d['nz'])
    values = {}
    for side, components in boundaries(case).items():
        values[side] = {}
        for c, (_, value) in components.items():
            x, z = regional_stokes.boundary_coordinates(d['nx'], d['nz'], d['width_m'], d['height_m'], side, c)
            values[side][c] = value(x, z) if callable(value) else value
    return fields(case, xu, zu)[3], fields(case, xw, zw)[4], values


def solve(case, plan, **kwargs):
    request = dict(frame_id='synthetic-x-right-z-up', epoch_id='steady-reference', time_s=0.,
                   force_source='independent continuous derivative', boundary_source='exact analytic trace')
    request.update(kwargs)
    return plan.solve(*inputs(case, plan), **request)


class RegionalExecutionTests(unittest.TestCase):
    def test_traction_pressure_and_complete_stress(self):
        with prepare() as plan:
            result = solve('couette', plan)
        assert_allclose(result.array('physical_pressure_pa'), 2., atol=1e-9)
        assert_allclose(result.array('stress_xx_pa'), -2., atol=1e-9)
        assert_allclose(result.array('stress_yy_pa'), -2., atol=1e-9)
        assert_allclose(result.array('stress_xz_pa'), 1., atol=1e-9)
        self.assertTrue(result.descriptor()['physical_pressure_defined'])

    def test_latest_reuse_is_exact_and_provenance_invalidates(self):
        with prepare() as plan:
            a = solve('couette', plan)
            b = solve('couette', plan)
            c = solve('couette', plan, time_s=1.)
            self.assertIs(a, b)
            self.assertNotEqual(a.result_id, c.result_id)
            self.assertEqual(plan.statistics()['solves'], 2)
            self.assertEqual(plan.statistics()['latest_result_hits'], 1)
            for key in a.array_names:
                assert_array_equal(a.array(key), c.array(key))

    def test_pressure_datum_is_not_a_solver_gauge(self):
        with prepare('extension', physical_mean_pressure_pa=10.) as plan:
            result = solve('extension', plan)
        assert_allclose(result.array('dynamic_pressure_pa'), 0., atol=1e-9)
        assert_allclose(result.array('physical_pressure_pa'), 10., atol=1e-9)
        assert_allclose(result.array('stress_xx_pa'), -8., atol=1e-9)
        with prepare('extension') as plan:
            relative = solve('extension', plan)
        self.assertFalse(relative.descriptor()['physical_pressure_defined'])
        self.assertNotIn('physical_pressure_pa', relative.array_names)
        with self.assertRaises(TectonicsError):
            prepare('couette', physical_mean_pressure_pa=10.)

    def test_background_hydrostatics_not_double_counted(self):
        reference = RegionalReferencePressure(2., 7., 'independent uniform-density hydrostatics')
        with prepare('hydrostatic_traction', reference_pressure=reference) as plan:
            result = solve('hydrostatic_traction', plan)
        assert_allclose(result.array('u_m_s'), 0., atol=1e-9)
        assert_allclose(result.array('w_m_s'), 0., atol=1e-9)
        assert_allclose(result.array('dynamic_pressure_pa'), 0., atol=1e-9)
        z = (np.arange(4)+.5)*3./4
        expected = np.broadcast_to((2.+7.*(3.-z))[:, None], (4, 4))
        assert_allclose(result.array('physical_pressure_pa'), expected, atol=1e-9)

    def test_nontrivial_scales_preserve_SI_solution(self):
        with prepare(scales=RegionalMechanicsScales(2., .25)) as plan:
            scaled = solve('couette', plan)
        with prepare() as plan:
            unit = solve('couette', plan)
        for field in ('u_m_s', 'w_m_s', 'physical_pressure_pa', 'stress_xz_pa'):
            assert_allclose(scaled.array(field), unit.array(field), rtol=1e-9, atol=1e-10)

    def test_arrays_and_descriptors_are_immutable_snapshots(self):
        with prepare() as plan:
            result = solve('couette', plan)
            desc = plan.descriptor()
            desc['width_m'] = 999.
            self.assertEqual(plan.descriptor()['width_m'], 1.)
        original = result.array('u_m_s').shape
        view = result.array('u_m_s')
        with self.assertRaises(ValueError):
            view.setflags(write=True)
        view.shape = (view.size,)
        self.assertEqual(result.array('u_m_s').shape, original)
        with self.assertRaises(TectonicsError):
            result.result_id = 'changed'
        desc = result.descriptor()
        desc['physical_pressure_defined'] = False
        self.assertTrue(result.descriptor()['physical_pressure_defined'])

    def test_boundary_values_are_detached_and_changed_values_invalidate(self):
        with prepare() as plan:
            fx, fz, value = inputs('couette', plan)
            args = dict(frame_id='synthetic-x-right-z-up', epoch_id='epoch', time_s=0.,
                        force_source='explicit', boundary_source='explicit')
            a = plan.solve(fx, fz, value, **args)
            value['top']['w'] = -3.
            b = plan.solve(fx, fz, value, **args)
            self.assertNotEqual(a.result_id, b.result_id)
            assert_allclose(a.array('physical_pressure_pa'), 2., atol=1e-9)
            assert_allclose(b.array('physical_pressure_pa'), 3., atol=1e-9)

    def test_memory_refusal_and_lifetime_release(self):
        tiny = WorkBudget(1024)
        with self.assertRaises(MemoryLimitError):
            prepare(budget=tiny)
        self.assertEqual(tiny.reserved_bytes, 0)
        budget = WorkBudget(128*1024**2)
        with prepare(budget=budget) as plan:
            solve('couette', plan)
            self.assertGreater(budget.reserved_bytes, 0)
        self.assertEqual(budget.reserved_bytes, 0)
        with self.assertRaises(MemoryLimitError):
            prepare(n=64, method='direct', budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_cancel_and_wrong_thread_preserve_preparation(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(CancelledError):
            prepare(cancel=event)
        with prepare() as plan:
            with self.assertRaises(CancelledError):
                solve('couette', plan, cancel=event)
            with ThreadPoolExecutor(max_workers=1) as worker:
                with self.assertRaises(TectonicsError):
                    worker.submit(solve, 'couette', plan).result()
            solve('couette', plan)
        with self.assertRaises(TectonicsError):
            solve('couette', plan)
        plan.close()

    def test_input_frame_shapes_and_nonfinite_values_refused(self):
        with prepare() as plan:
            with self.assertRaises(TectonicsError):
                solve('couette', plan, frame_id='wrong')
            for field in ('epoch_id', 'force_source', 'boundary_source'):
                with self.subTest(field=field), self.assertRaises(TectonicsError):
                    solve('couette', plan, **{field: ''})
            fx, fz, value = inputs('couette', plan)
            args = dict(frame_id='synthetic-x-right-z-up', epoch_id='epoch', time_s=0.,
                        force_source='explicit', boundary_source='explicit')
            for bad in (np.ones((4, 4)), np.full(fx.shape, np.nan), fx > 0, np.ma.array(fx)):
                with self.subTest(kind=str(type(bad))), self.assertRaises(TectonicsError):
                    plan.solve(bad, fz, value, **args)
            value['left']['u'] = np.zeros(2)
            with self.assertRaises(TectonicsError):
                plan.solve(fx, fz, value, **args)

    def test_source_drift_cannot_return_cached_result(self):
        with prepare() as plan:
            solve('couette', plan)
            original = reuse._source_bytes
            def changed():
                sources = original()
                sources['synthetic-change.py'] = b'not an accepted implementation'
                return sources
            with mock.patch.object(reuse, '_source_bytes', changed):
                with self.assertRaises(TectonicsError):
                    solve('couette', plan)

    def test_bad_scale_or_boundary_pattern_refused(self):
        for value in (0., -1., float('inf'), True):
            with self.assertRaises(TectonicsError):
                RegionalMechanicsScales(value, 1.)
        with self.assertRaises(TectonicsError):
            PreparedRegionalStokes2D(4, 4, 1., 1., 1., {'top': {'u': 'velocity'}},
                scales=RegionalMechanicsScales(1., 1.), frame_id='frame',
                vertical_datum='datum', material_source='material')


if __name__ == '__main__':
    unittest.main()
