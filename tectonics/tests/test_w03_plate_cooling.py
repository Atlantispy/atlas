"""Bounded W03.1 mathematical/engineering checks, not Earth calibration."""
from concurrent.futures import CancelledError
from dataclasses import replace
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from scipy.integrate import quad
from scipy.linalg import expm

from atlas_tectonics import (ThermalParameters, PlateCoolingParameters, TectonicsError,
    finite_plate_temperature, half_space_temperature, plate_cooling_heat,
    plate_cooling_columns, CoolingHistory, GeologicalCase)
from atlas_tectonics.parameters import identity
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.reuse import cached_plate_temperature, CachePolicy, ReuseController
from atlas_tectonics.storage import ArrayStore, StoreLimits
from test_w01_geological_description import ingredients
from test_w01_initial_sampling import initial, regional_case

P = PlateCoolingParameters(ThermalParameters('unit-plate', 'analytic synthetic', 0., 1., 1.), 1., 1.)


def reference(x, age):
    """Independent scalar eigenfunction evaluation; tests use resolved positive ages."""
    return x + math.fsum(2/(n*math.pi)*math.sin(n*math.pi*x)*math.exp(-n*n*math.pi**2*age)
                         for n in range(1, 301))


class PlateCoolingTests(unittest.TestCase):
    def test_zero_age_boundaries_isothermal_and_mature_limits(self):
        x = np.linspace(0, 1, 11)
        assert_array_equal(finite_plate_temperature(x, 0., P), [0.]+[1.]*10)
        assert_array_equal(finite_plate_temperature(x[:-1], 0., P, cell_bottom_m=x[1:]), np.ones(10))
        assert_array_equal(finite_plate_temperature(x, 100., P), x)
        assert_array_equal(finite_plate_temperature([0., 1.], np.logspace(-300, 300, 51)[:, None], P),
                           np.broadcast_to([0., 1.], (51, 2)))
        equal = replace(P, thermal=replace(P.thermal, surface_temperature_k=300., mantle_temperature_k=300.))
        assert_array_equal(finite_plate_temperature(x, .04, equal), np.full(11, 300.))
        assert_array_equal(plate_cooling_heat([0., .04, 10.], equal), np.zeros((3, 2)))

    def test_independent_series_both_branches_and_switch(self):
        x = np.linspace(0, 1, 61)
        ages = [1e-4, .005, .0625, np.nextafter(.0625, 1.), .3, 10.]
        expected = [[reference(z, age) for z in x] for age in ages]
        assert_allclose(finite_plate_temperature(x, np.array(ages)[:, None], P), expected, rtol=0, atol=3e-15)

    def test_half_space_limit_and_not_old_half_space(self):
        x = np.linspace(0, 1, 97)
        assert_allclose(finite_plate_temperature(x, 1e-4, P),
                        half_space_temperature(x, 1e-4, P.thermal), rtol=0, atol=2e-15)
        self.assertGreater(abs(float(finite_plate_temperature(.5, 1., P))
                               -float(half_space_temperature(.5, 1., P.thermal))), .2)
        # Resolve even a very thin newborn boundary layer without an age floor.
        assert_allclose(finite_plate_temperature(1e-150, 1e-300, P), math.erf(.5), rtol=2e-15)

    def test_cell_means_against_independent_quadrature_and_thin_cells(self):
        edges = np.array([0., .003, .07, .4, .8, 1.])
        for age in (.001, .0625, .063, 1.):
            expected = [quad(lambda z: reference(z, age), a, b, epsabs=2e-14)[0]/(b-a)
                        for a, b in zip(edges[:-1], edges[1:])]
            actual = finite_plate_temperature(edges[:-1], age, P, cell_bottom_m=edges[1:])
            assert_allclose(actual, expected, rtol=0, atol=4e-14)
        top = np.array([0., 1e-12, .3, .999999])
        bottom = np.nextafter(top, 1.)
        # A subnormal-width interval at zero is supported; test interior thin
        # cells separately from the physically discontinuous zero-age surface.
        assert_allclose(finite_plate_temperature(top, .01, P, cell_bottom_m=bottom),
                        finite_plate_temperature(top, .01, P), rtol=0, atol=4e-14)
        assert_allclose(finite_plate_temperature(0., .01, P, cell_bottom_m=1e-18),
                        1e-18/(.2*math.sqrt(math.pi)), rtol=3e-15, atol=0)

    def test_heat_accounts_and_refinement(self):
        ages = np.array([0., 1e-9, 1e-4, .01, .0625, .0625001, .2, 1., 100.])
        heat = plate_cooling_heat(ages, P)
        self.assertTrue(np.all(heat[:, 0] >= 0)); self.assertTrue(np.all(heat[:, 1] <= 0))
        for count in (1, 13, 64):
            edges = np.linspace(0, 1, count+1)
            means = finite_plate_temperature(edges[:-1], ages[:, None], P, cell_bottom_m=edges[1:])
            loss = np.sum((1-means)*np.diff(edges), axis=1)
            assert_allclose(heat.sum(axis=1), loss, rtol=0, atol=3e-14)
        assert_allclose(heat[1, 0], 2*math.sqrt(ages[1]/math.pi), rtol=2e-15)
        # Independent integration of boundary derivatives, away from t=0.
        t0, t1 = .02, .2
        for side in (0, 1):
            flux = lambda t: (1 if side == 0 else -1) * (1+2*math.fsum(
                ((-1)**n if side else 1)*math.exp(-n*n*math.pi**2*t) for n in range(1, 150)))
            expected = quad(flux, t0, t1, epsabs=1e-13)[0]
            q = plate_cooling_heat([t0, t1], P)
            self.assertAlmostEqual(q[1, side]-q[0, side], expected, places=13)
        # Splitting a time interval changes no physics or thermal age.
        q = plate_cooling_heat([0., .05, .2], P)
        assert_allclose((q[1]-q[0])+(q[2]-q[1]), q[2], atol=1e-16)

    def test_independent_finite_volume_conduction_grid_refinement(self):
        errors = []
        for count in (16, 32, 64):
            edges = np.linspace(0, 1, count+1); centres = .5*(edges[:-1]+edges[1:])
            matrix = np.diag(np.full(count, -2.)) + np.diag(np.ones(count-1), 1) + np.diag(np.ones(count-1), -1)
            matrix[0, 0] = matrix[-1, -1] = -3.
            matrix *= count**2
            expected = finite_plate_temperature(edges[:-1], .037, P, cell_bottom_m=edges[1:])
            field = centres + expm(.037*matrix)@(1-centres)
            errors.append(float(np.max(abs(field-expected))))
            half = expm(.0185*matrix)
            assert_allclose(centres+half@(half@(1-centres)), field, rtol=0, atol=3e-14)
        self.assertGreater(errors[0]/errors[1], 3.5)
        self.assertGreater(errors[1]/errors[2], 3.5)

    def test_si_scaling_and_range_safe_fourier_age(self):
        p = PlateCoolingParameters(ThermalParameters('si', 'synthetic', 273., 1573., 1e-6), 1e5, 3.)
        assert_allclose(finite_plate_temperature([0., 2e4, 1e5], 1e15, p),
                        273+1300*finite_plate_temperature([0., .2, 1.], .1, P), atol=2e-12)
        assert_allclose(plate_cooling_heat(1e15, p), plate_cooling_heat(.1, P)*3e6*1300*1e5, rtol=3e-15)
        huge = replace(P, thickness_m=1e150, thermal=replace(P.thermal, diffusivity_m2_s=1e150), conductivity_w_m_k=1e150)
        assert_allclose(finite_plate_temperature(2e149, 1e149, huge), finite_plate_temperature(.2, .1, P), atol=1e-15)
        with self.assertRaises(TectonicsError):
            finite_plate_temperature(1e-300, 0., replace(P, thickness_m=1e300))

    def test_contracts_broadcast_batches_and_admission(self):
        x = np.linspace(0, 1, 20)[::2]; ages = np.array([0., .01, .1, 3.])[:, None]
        assert_array_equal(finite_plate_temperature(x, ages, P, batch_elements=7), finite_plate_temperature(x, ages, P))
        xx, aa = np.broadcast_arrays(x, ages)
        assert_allclose(finite_plate_temperature(xx.copy(), aa.copy(), P),
                        finite_plate_temperature(x, ages, P), atol=2e-15, rtol=0)
        edges = np.linspace(0, 1, 21)
        top, aa = np.broadcast_arrays(edges[:-1], ages)
        bottom = np.broadcast_to(edges[1:], top.shape)
        assert_allclose(finite_plate_temperature(top.copy(), aa.copy(), P, cell_bottom_m=bottom.copy()),
                        finite_plate_temperature(edges[:-1], ages, P, cell_bottom_m=edges[1:]), atol=2e-15, rtol=0)
        value = finite_plate_temperature(x, ages, P)
        with self.assertRaises(ValueError): value.setflags(write=True)
        for depth, age, bottom in ((-1., 1., None), (2., 1., None), (0., -1., None), (0., math.inf, None),
                                   (0., True, None), (.3, .1, .3), (.4, .1, .2), (0., .1, 2.)):
            with self.assertRaises(TectonicsError):
                finite_plate_temperature(depth, age, P, cell_bottom_m=bottom)
        with self.assertRaises(TectonicsError): finite_plate_temperature(np.ma.array([.1]), 1., P)
        budget = WorkBudget(16)
        with self.assertRaises(MemoryLimitError): finite_plate_temperature(x, ages, P, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        flag = threading.Event(); flag.set()
        with self.assertRaises(CancelledError): finite_plate_temperature(x, ages, P, cancel=flag)
        with self.assertRaises(CancelledError): plate_cooling_heat(ages, P, cancel=flag)

    def test_verified_cache_separates_points_means_parameters_and_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            with ArrayStore(Path(folder)/'cooling.db', StoreLimits(1024, 1<<20, 8<<20, 4096)) as store:
                control = ReuseController()
                kwargs = dict(store=store, cache_policy=CachePolicy(mode='always'), controller=control)
                a = cached_plate_temperature([0., .2], .01, P, cell_bottom_m=[.2, 1.], **kwargs)
                b = cached_plate_temperature([0., .2], .01, P, cell_bottom_m=[.2, 1.], **kwargs)
                assert_array_equal(a, b)
                self.assertEqual(control.statistics()['writes'], 1)
                self.assertEqual(control.statistics()['hits'], 1)
                with patch('atlas_tectonics.plate_cooling.finite_plate_temperature', side_effect=AssertionError('must not trust changed executable')):
                    with self.assertRaises((AssertionError, TectonicsError)):
                        cached_plate_temperature([0., .2], .01, P, cell_bottom_m=[.2, 1.], **kwargs)
                b = cached_plate_temperature([0., .2], .01, P, cell_bottom_m=[.2, 1.], **kwargs)
                assert_array_equal(a, b)
                point = cached_plate_temperature([0., .2], .01, P, **kwargs)
                self.assertNotEqual(a[0], point[0])
                other = cached_plate_temperature([0., .2], .02, P, cell_bottom_m=[.2, 1.], **kwargs)
                self.assertNotEqual(a[0], other[0])
                changed = replace(P, thermal=replace(P.thermal, mantle_temperature_k=2.))
                assert_allclose(cached_plate_temperature([0., .2], .01, changed, cell_bottom_m=[.2, 1.], **kwargs), 2*a)


class ThermalAgeWorkflowTests(unittest.TestCase):
    def state(self, start=-.1):
        case = GeologicalCase(**ingredients())
        history = CoolingHistory('initial', 'synthetic', start,
                                 'explicitly unknown' if start is None else None)
        return initial(case, cooling_history=(history,))

    def test_join_preserves_provenance_age_and_parent_without_overwrite(self):
        state = self.state(); source = state.state_id
        result = plate_cooling_columns(state, {'initial': P}, [0., .1, .4, 1.], time_s=.2, epoch_id=state.case.epoch_id)
        self.assertEqual(result.source_state_id, source)
        self.assertEqual(result.profile_ids, ('initial',)); self.assertEqual(result.history_source_ids, ('synthetic',))
        self.assertEqual(result.model_ids, (identity(P),))
        self.assertAlmostEqual(result.cooling_age_s[0], .3)
        self.assertEqual(state.state_id, source)
        self.assertEqual(state.case.thermal_profiles[0].temperatures_k, (300.,))
        # Cohort formation is -100 s in this fixture; it must not become cooling age.
        assert_allclose(result.mean_temperature_k[0], finite_plate_temperature([0., .1, .4], .3, P, cell_bottom_m=[.1, .4, 1.]))
        assert_allclose(result.outward_heat_j_m2[0], plate_cooling_heat(.3, P))

    def test_unknown_wrong_epoch_and_nonspanning_grid_refuse(self):
        for state, epoch, edges, time in ((self.state(None), 'epoch', [0., 1.], .1),
                (self.state(), 'wrong', [0., 1.], .1), (self.state(), 'epoch', [0., .5], .1),
                (self.state(), 'epoch', [0., .5, .4, 1.], .1), (self.state(), 'epoch', [0., 1.], -.01)):
            # Use the actual fixture epoch except in the deliberate mismatch.
            if epoch == 'epoch': epoch = state.case.epoch_id
            with self.assertRaises(TectonicsError):
                plate_cooling_columns(state, {'initial': P}, edges, time_s=time, epoch_id=epoch)

    def test_profiles_share_model_work_without_sharing_cooling_ages(self):
        state = initial(regional_case(), cooling_history=(
            CoolingHistory('initial', 'synthetic', -.1), CoolingHistory('hot', 'synthetic', -.2)))
        result = plate_cooling_columns(state, {'initial': P, 'hot': P}, [0., .4, 1.],
            time_s=.2, epoch_id=state.case.epoch_id)
        self.assertEqual(result.profile_ids, ('hot', 'initial'))
        assert_allclose(result.cooling_age_s, [.4, .3])
        assert_allclose(result.mean_temperature_k,
            finite_plate_temperature([0., .4], np.array([.4, .3])[:, None], P, cell_bottom_m=[.4, 1.]))


if __name__ == '__main__':
    unittest.main()
