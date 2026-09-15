from copy import deepcopy
from dataclasses import replace
import math
import unittest

from capture import CaptureState
import shoreline_fixtures as fixtures
from shoreline_materials import hillslope_trial


class MaterialBridgeTests(unittest.TestCase):
    def test_original_fixture_is_preserved_and_soil_once(self):
        first = fixtures.near_flat(); second = fixtures.near_flat()
        self.assertEqual(first, second)
        original = fixtures.retained_recipe()
        self.assertEqual(first['original_recipe'], original)
        self.assertEqual(first['forcing'], original['operations'][1])
        self.assertEqual(len(first['soil_prefix_result']['operations']), 1)
        self.assertEqual(first['initial_state'].time_years, 0.)
        self.assertFalse(any(first['initial_state'].liquid_m3))
        self.assertFalse(any(first['initial_state'].suspended_solid_m3))
        area = 100.; rho = 2700.
        b0 = original['initial']['bedrock_m']; b1 = first['initial_state'].bedrock_m
        mobile0 = math.fsum(original['initial']['mobile_solid_m3'])
        mobile1 = math.fsum(first['initial_state'].bed_solid_m3)
        dissolved = first['soil_dissolved_rock_export_kg']
        rock_loss = math.fsum((a-b)*area*rho for a,b in zip(b0,b1))
        self.assertAlmostEqual(rock_loss, rho*(mobile1-mobile0)+dissolved, delta=1e-6)
        self.assertAlmostEqual(dissolved, 17.780838330238975, delta=1e-12)
        self.assertEqual(first['coupled_duration_years'], .8)

    def test_retained_r2_failure_is_still_failure(self):
        with self.assertRaisesRegex(ValueError, 'relative link relief'):
            fixtures.io.execute(fixtures.retained_recipe())

    def test_pairwise_flux_and_phase_identity(self):
        # Square 2x2, one higher mobile cell. Two identical face transfers:
        # Qsolid=K*(drop/distance)*width*dt = .1*1*1*.1=.01.
        state = CaptureState((2,2), (1.,)*4, (0.,)*4, (2.,1.,1.,1.),
                             (.5,)*4, (.01,)*4)
        final, report = hillslope_trial(state, dx_m=1., dy_m=1.,
                    diffusivity_m2_year=[.1]*4, dt_years=.1)
        self.assertEqual(final.bed_solid_m3, (1.98,1.01,1.01,1.))
        self.assertEqual(final.liquid_m3, state.liquid_m3)
        self.assertEqual(final.suspended_solid_m3, state.suspended_solid_m3)
        self.assertEqual(final.time_years, state.time_years)
        self.assertEqual(report['explicit_cfl'], .020000000000000004)
        self.assertAlmostEqual(report['solid_volume_residual_m3'], 0., delta=1e-14)

    def test_zero_diffusivity_exactly_preserves_one_row(self):
        state = CaptureState((1,2), (1.,)*2, (0.,1.), (0.,)*2, (0.,)*2, (0.,)*2)
        final, _ = hillslope_trial(state, dx_m=1., dy_m=1.,
                    diffusivity_m2_year=[0.,0.], dt_years=1.)
        self.assertIs(final, state)

    def test_original_cfl_and_area_guards(self):
        state = CaptureState((2,2), (1.,)*4, (0.,)*4, (2.,1.,1.,1.), (0.,)*4, (0.,)*4)
        with self.assertRaisesRegex(ValueError, 'stability bound'):
            hillslope_trial(state, dx_m=1., dy_m=1., diffusivity_m2_year=[1.]*4, dt_years=1.)
        with self.assertRaisesRegex(ValueError, 'native area'):
            hillslope_trial(state, dx_m=2., dy_m=1., diffusivity_m2_year=[.1]*4, dt_years=.1)


if __name__ == '__main__': unittest.main()
