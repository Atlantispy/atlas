"""Independent bounded thermal-density/isostatic controls, not field calibration."""
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

from atlas_tectonics import (ThermalParameters, PlateCoolingParameters, BoussinesqMaterial,
    ThermalSupportParameters, thermal_density, thermal_column_response, plate_thermal_response,
    thermal_support_columns, finite_plate_temperature, boussinesq_response, TectonicsError,
    CoolingHistory, GeologicalCase)
from atlas_tectonics.reuse import cached_plate_thermal_response, CachePolicy, ReuseController
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.storage import ArrayStore, StoreLimits
from test_w01_geological_description import ingredients
from test_w01_initial_sampling import initial, regional_case

MAT = BoussinesqMaterial('thermal-support-test', 'Authored analytic fixture, not Earth fit',
    3300., 1000., 3.3, 3e-5, 1300., 0., 0., (300., 1300.), .05)
PLATE = PlateCoolingParameters(ThermalParameters('support-cooling', 'synthetic', 300., 1300., 1e-6), 1e5, 3.3)
SUPPORT = ThermalSupportParameters('ridge-reference', 'synthetic uniform local compensation',
    'local-surface', 'column-isostasy', 3300., 1000., 10., .1)
TIME = PLATE.thickness_m**2/PLATE.thermal.diffusivity_m2_s


class ThermalSupportTests(unittest.TestCase):
    def test_density_matches_existing_boussinesq_law_and_limits(self):
        temperatures = np.array([300., 800., 1300.])
        expected = boussinesq_response(MAT, temperatures, 0., [0., -10.], [0., 0.])['density_anomaly_kg_m3']+MAT.density_kg_m3
        assert_allclose(thermal_density(temperatures, MAT), expected, rtol=2e-16, atol=1e-12)
        self.assertGreater(float(thermal_density(300., MAT)), float(thermal_density(1300., MAT)))
        assert_array_equal(thermal_density(temperatures, replace(MAT, expansion_per_k=0.)), [3300.]*3)
        for bad in (299., 1301., math.nan, np.ma.array([700.])):
            with self.assertRaises(TectonicsError): thermal_density(bad, MAT)
        with self.assertRaises(TectonicsError): thermal_density(300., replace(MAT, max_relative_density_anomaly=.01))

    def test_uniform_cooling_sign_dimensions_gravity_and_fill(self):
        response = thermal_column_response([1200., 1200.], 1300., [0., 4e4, 1e5], MAT, SUPPORT)
        sheet = 3300*3e-5*100*1e5
        assert_allclose(response, [sheet, sheet*10, sheet/2300], rtol=3e-15)
        reverse = thermal_column_response([1300., 1300.], 1200., [0., 4e4, 1e5], MAT, SUPPORT)
        assert_allclose(reverse, -response, rtol=3e-15)
        gravity = thermal_column_response([1200., 1200.], 1300., [0., 4e4, 1e5], MAT, replace(SUPPORT, gravity_m_s2=20.))
        assert_allclose(gravity, response*[1., 2., 1.], rtol=3e-15)
        empty = thermal_column_response([1200.], 1300., [0., 1e5], MAT, replace(SUPPORT, fill_density_kg_m3=0.))
        self.assertLess(empty[2], response[2])

    def test_eos_reference_is_not_the_isostatic_reference(self):
        rho = MAT.density_kg_m3*(1-MAT.expansion_per_k*(1000.-MAT.reference_temperature_k))
        shifted = replace(MAT, reference_temperature_k=1000., density_kg_m3=rho,
                          expansion_per_k=MAT.density_kg_m3*MAT.expansion_per_k/rho)
        assert_allclose(thermal_density([500., 1000., 1300.], MAT), thermal_density([500., 1000., 1300.], shifted), atol=1e-12)
        a = thermal_column_response([900., 1200.], [1000., 1300.], [0., 2e4, 1e5], MAT, SUPPORT)
        b = thermal_column_response([900., 1200.], [1000., 1300.], [0., 2e4, 1e5], shifted, SUPPORT)
        assert_allclose(a, b, rtol=2e-15)

    def test_equal_fields_zero_alpha_and_no_accumulated_elevation(self):
        T = [500., 1000., 1300.]; edges = [0., 1e4, 6e4, 1e5]
        assert_array_equal(thermal_column_response(T, T, edges, MAT, SUPPORT), np.zeros(3))
        assert_array_equal(thermal_column_response(T, 1300., edges, replace(MAT, expansion_per_k=0.), SUPPORT), np.zeros(3))
        first = plate_thermal_response(.2*TIME, 0., PLATE, MAT, SUPPORT)
        # The result is total from reference, not another increment to add on a repeated call.
        assert_array_equal(plate_thermal_response(.2*TIME, 0., PLATE, MAT, SUPPORT), first)

    def test_depth_repartition_and_chunk_boundaries_preserve_integral(self):
        edges = np.linspace(0., 1e5, 34)
        T = np.stack([np.linspace(400., 1200., 33), np.linspace(1300., 800., 33)])
        R = np.full(33, 1250.)
        actual = thermal_column_response(T, R, edges, MAT, SUPPORT, batch_elements=7)
        expected = []
        for row in T:
            sheet = math.fsum(3300*3e-5*(r-t)*dz for t, r, dz in zip(row, R, np.diff(edges)))
            expected.append([sheet, 10*sheet, sheet/2300])
        assert_allclose(actual, expected, rtol=4e-15)
        assert_allclose(thermal_column_response(T, R, edges, MAT, SUPPORT), actual, rtol=4e-15)
        refined = np.sort(np.r_[edges, .5*(edges[:-1]+edges[1:])])
        assert_allclose(thermal_column_response(np.repeat(T, 2, axis=1), 1250., refined, MAT, SUPPORT), actual, rtol=4e-15)

    def test_plate_integral_matches_cell_means_and_independent_old_young_limits(self):
        ages = np.array([0., 1e-5, .01, .0625, .063, 1., 10.])*TIME
        direct = plate_thermal_response(ages, 0., PLATE, MAT, SUPPORT)
        for count in (1, 17, 128):
            edges = np.linspace(0., 1e5, count+1)
            T = finite_plate_temperature(edges[:-1], ages[:, None], PLATE, cell_bottom_m=edges[1:])
            sampled = thermal_column_response(T, 1300., edges, MAT, SUPPORT)
            assert_allclose(direct, sampled, rtol=3e-13, atol=1e-7)
        limit = 3300*3e-5*1000*1e5/(2*2300)
        self.assertAlmostEqual(direct[-1, 2], limit, places=10)
        young = plate_thermal_response(1e-10*TIME, 0., PLATE, MAT, SUPPORT)[2]
        expected = 2*3300*3e-5*1000*math.sqrt(1e-6*1e-10*TIME/math.pi)/2300
        assert_allclose(young, expected, rtol=3e-15)

    def test_owner_envelopes_and_mismatched_cooling_material_refuse(self):
        for owner in ('mechanical-buoyancy', 'flexure', 'empirical-age-depth'):
            other = replace(SUPPORT, thermal_owner=owner)
            with self.assertRaisesRegex(TectonicsError, 'already assigned'):
                plate_thermal_response(TIME, 0., PLATE, MAT, other)
            with self.assertRaises(TectonicsError): thermal_column_response([900.], 1300., [0., 1e5], MAT, other)
        for kwargs in ({'thermal_owner': ('column-isostasy', 'flexure')}, {'fill_density_kg_m3': 3300.},
                       {'gravity_m_s2': 0.}, {'max_relative_deflection': 1.}):
            with self.assertRaises(TectonicsError): replace(SUPPORT, **kwargs)
        for material in (replace(MAT, heat_capacity_j_kg_k=900.), replace(MAT, conductivity_w_m_k=3.),
                         replace(MAT, internal_heating_w_m3=1e-6), replace(MAT, temperature_range_k=(400., 1200.))):
            with self.assertRaises(TectonicsError): plate_thermal_response(TIME, 0., PLATE, material, SUPPORT)
        with self.assertRaises(TectonicsError):
            plate_thermal_response(TIME, 0., PLATE, MAT, replace(SUPPORT, max_relative_deflection=.001))

    def test_shapes_invalid_geometry_cancellation_and_budget(self):
        for T, R, edges in (([900., 1000.], 1300., [0., 1e5]), ([900.], 1300., [1., 1e5]),
                             ([900., 1000.], 1300., [0., 1e5, 5e4]), ([900.], -1., [0., 1e5])):
            with self.assertRaises(TectonicsError): thermal_column_response(T, R, edges, MAT, SUPPORT)
        flag = threading.Event(); flag.set()
        with self.assertRaises(CancelledError): thermal_column_response([900.], 1300., [0., 1e5], MAT, SUPPORT, cancel=flag)
        budget = WorkBudget(16)
        with self.assertRaises(MemoryLimitError): thermal_column_response([900.], 1300., [0., 1e5], MAT, SUPPORT, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        result = thermal_column_response([900.], 1300., [0., 1e5], MAT, SUPPORT)
        with self.assertRaises(ValueError): result.setflags(write=True)

    def test_weighted_temperature_underflow_refuses_false_zero(self):
        temperature = 1e-308
        reference = np.nextafter(temperature, math.inf)
        material = replace(MAT, density_kg_m3=1e300, expansion_per_k=1.,
            reference_temperature_k=temperature, temperature_range_k=(temperature, reference))
        # Each half-weighted delta rounds to zero, but the final load would not.
        self.assertGreater(2.*material.density_kg_m3*(reference-temperature), 0.)
        with self.assertRaisesRegex(TectonicsError, 'weighted temperature'):
            thermal_column_response([temperature]*2, reference, [0., 1., 2.], material, SUPPORT)

    def test_cache_hits_invalidation_and_auto_bypass(self):
        with tempfile.TemporaryDirectory() as folder:
            with ArrayStore(Path(folder)/'support.db', StoreLimits(1024, 1<<20, 8<<20, 4096)) as store:
                control = ReuseController()
                cached_plate_thermal_response([TIME], 0., PLATE, MAT, SUPPORT, store=store, controller=control)
                self.assertEqual(store.statistics()['snapshots'], 0)
                kwargs = dict(store=store, controller=control, cache_policy=CachePolicy(mode='always'))
                a = cached_plate_thermal_response([TIME], 0., PLATE, MAT, SUPPORT, **kwargs)
                b = cached_plate_thermal_response([TIME], 0., PLATE, MAT, SUPPORT, **kwargs)
                assert_array_equal(a, b)
                self.assertEqual(control.statistics()['hits'], 1)
                self.assertEqual(control.statistics()['writes'], 1)
                c = cached_plate_thermal_response([TIME], .1*TIME, PLATE, MAT, SUPPORT, **kwargs)
                self.assertLess(c[0, 2], a[0, 2])
                changed = cached_plate_thermal_response([TIME], 0., PLATE, MAT,
                    replace(SUPPORT, fill_density_kg_m3=0.), **kwargs)
                self.assertLess(changed[0, 2], a[0, 2])
                with patch('atlas_tectonics.thermal_support.plate_thermal_response', side_effect=AssertionError('modified executable')):
                    with self.assertRaises((AssertionError, TectonicsError)):
                        cached_plate_thermal_response([TIME], 0., PLATE, MAT, SUPPORT, **kwargs)


class ThermalSupportWorkflowTests(unittest.TestCase):
    def test_source_bound_history_reference_and_grouping(self):
        case = regional_case()
        state = initial(case, cooling_history=(CoolingHistory('initial', 'synthetic', -1e15),
                                               CoolingHistory('hot', 'synthetic', -2e15)))
        parameters = replace(SUPPORT, depth_reference_id=case.depth_reference_id)
        result = thermal_support_columns(state, {'initial': PLATE, 'hot': PLATE},
            {'initial': MAT, 'hot': MAT}, parameters, time_s=1e15, reference_time_s=0., epoch_id=case.epoch_id)
        self.assertEqual(result.source_state_id, state.state_id)
        self.assertEqual(result.profile_ids, ('hot', 'initial'))
        self.assertEqual(result.reference_id, SUPPORT.reference_id)
        self.assertEqual(result.thermal_owner, 'column-isostasy')
        assert_array_equal(result.cooling_age_s, [3e15, 2e15])
        assert_array_equal(result.reference_cooling_age_s, [2e15, 1e15])
        direct = plate_thermal_response([3e15, 2e15], [2e15, 1e15], PLATE, MAT, parameters)
        assert_allclose(result.downward_displacement_from_reference_m, direct[:, 2], rtol=2e-15)
        self.assertEqual(state.case.thermal_profiles[0].temperatures_k, (500.,))
        self.assertEqual(result.history_source_ids, ('synthetic', 'synthetic'))

    def test_distinct_epochs_collapsing_to_equal_ages_refuse(self):
        case = regional_case()
        state = initial(case, cooling_history=(CoolingHistory('initial', 'synthetic', -1e15),
                                               CoolingHistory('hot', 'synthetic', -2e15)))
        parameters = replace(SUPPORT, depth_reference_id=case.depth_reference_id)
        with self.assertRaisesRegex(TectonicsError, 'distinct evaluation times'):
            thermal_support_columns(state, {'initial': PLATE}, {'initial': MAT}, parameters,
                time_s=.01, reference_time_s=0., epoch_id=case.epoch_id)

    def test_unknown_history_epoch_datum_and_missing_material_refuse(self):
        case = GeologicalCase(**ingredients()); state = initial(case)
        parameters = replace(SUPPORT, depth_reference_id=case.depth_reference_id)
        with self.assertRaisesRegex(TectonicsError, 'unknown cooling history'):
            thermal_support_columns(state, {'initial': PLATE}, {'initial': MAT}, parameters,
                time_s=1., reference_time_s=0., epoch_id=case.epoch_id)
        state = initial(case, cooling_history=(CoolingHistory('initial', 'synthetic', 0.),))
        for models, mats, p, epoch, reference in (({'initial': PLATE}, {}, parameters, case.epoch_id, 0.),
                ({'initial': PLATE}, {'initial': MAT}, parameters, 'wrong', 0.),
                ({'initial': PLATE}, {'initial': MAT}, replace(parameters, depth_reference_id='wrong'), case.epoch_id, 0.),
                ({'initial': PLATE}, {'initial': MAT}, parameters, case.epoch_id, -1.)):
            with self.assertRaises(TectonicsError):
                thermal_support_columns(state, models, mats, p, time_s=1., reference_time_s=reference, epoch_id=epoch)


if __name__ == '__main__':
    unittest.main()
