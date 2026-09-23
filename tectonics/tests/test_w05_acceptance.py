"""One bounded coupled sweep shared by all tests and the verifier record."""
import unittest

from atlas_tectonics.materials import _ROUNDOFF
from w05_acceptance_case import ACCOUNT_ROUNDOFF, run_case


CASE_METRICS = None


class W05AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global CASE_METRICS
        if CASE_METRICS is None:
            CASE_METRICS = run_case()
        cls.metrics = CASE_METRICS

    def test_complete_frozen_grid_and_output_coverage(self):
        rows = self.metrics['grids']
        self.assertEqual({(r['spacing_m'], r['displacement_m']) for r in rows},
            {(dx, a) for dx in (500., 250., 125.) for a in (0., 250., 500., 1000.)})
        self.assertEqual(len(rows), 12)
        self.assertEqual(self.metrics['nonzero_reference_point_evaluations'], 5763)
        for row in rows:
            self.assertEqual(row['crop_cells'], round(120000/row['spacing_m']))
            self.assertEqual(row['crop_face_centre_points'], 2*row['crop_cells']+1)

    def test_all_cohort_accounts_history_and_stationary_footwall(self):
        self.assertEqual(ACCOUNT_ROUNDOFF, _ROUNDOFF)
        limit = self.metrics['limits']['geometry_quadrature_m']
        for row in self.metrics['grids']:
            with self.subTest(dx=row['spacing_m'], a=row['displacement_m']):
                account = row['accounts']
                for name in ('max_cohort_roundoff_fraction', 'total_roundoff_fraction',
                             'exchange_error_roundoff_fraction'):
                    self.assertLessEqual(account[name], 1.)
                for name in ('left_exchange_is_zero', 'right_exchange_is_export',
                             'cohort_history_unchanged', 'receipt_matches'):
                    self.assertTrue(account[name], name)
                for name in ('footwall_stationary', 'material_nonnegative', 'parent_history_matches'):
                    self.assertTrue(row[name], name)
                self.assertLessEqual(row['max_footwall_reference_error_m'], limit)

    def test_component_isolation_zero_and_output_fields(self):
        limits = self.metrics['limits']
        self.assertTrue(self.metrics['zero_motion_pass'])
        for row in self.metrics['grids']:
            self.assertTrue(row['output_identity'])
            self.assertTrue(row['repeated_output_same_checkpoint'])
            self.assertLessEqual(row['max_same_q_mean_error_m'], limits['matched_convolution_m'])
            self.assertLessEqual(row['max_same_q_point_error_m'], limits['matched_convolution_m'])
            self.assertLessEqual(row['max_q_error_as_height_m'], limits['geometry_quadrature_m'])
            if row['displacement_m'] == 0:
                self.assertTrue(row['zero_load_and_movement'])

    def test_full_crop_independent_accuracy_and_refinement(self):
        limits = self.metrics['limits']
        for row in self.metrics['grids']:
            self.assertLessEqual(row['max_point_reference_uncertainty_m'], limits['reference_uncertainty_m'])
            self.assertLessEqual(row['max_w_error_with_uncertainty_m'], limits['smooth_w_m'])
            if row['spacing_m'] == 125.:
                self.assertLessEqual(row['max_h_error_m'], limits['h_max_m'])
                self.assertLessEqual(row['h_relative_l1'], limits['h_relative_l1'])
        for displacement in (250., 500., 1000.):
            rows = [row for row in self.metrics['grids'] if row['displacement_m'] == displacement]
            for coarse, fine in zip(rows[:-1], rows[1:]):
                self.assertLess(fine['max_w_error_m'], coarse['max_w_error_m'])
            # Exact characteristic cell means are already at arithmetic precision;
            # no formal order is meaningful for their roundoff-sized differences.
            self.assertTrue(all(row['max_h_error_m'] <= limits['geometry_quadrature_m'] for row in rows))

    def test_independent_cell_mean_basin_and_footwall_extrema(self):
        limits = self.metrics['limits']
        for row in self.metrics['grids']:
            if not row['displacement_m']:
                continue
            for name in ('basin', 'footwall'):
                extremum = row[name]
                with self.subTest(dx=row['spacing_m'], a=row['displacement_m'], region=name):
                    self.assertGreater(extremum['candidates_integrated'], 0)
                    self.assertLessEqual(extremum['reference_uncertainty_m'], limits['reference_uncertainty_m'])
                    self.assertLessEqual(extremum['height_error_with_uncertainty_m'], limits['smooth_w_m'])
                    self.assertLessEqual(extremum['location_difference_bound_m'], limits['extrema_location_m'])
            self.assertLess(row['basin']['production_height_m'], 0.)
            self.assertLess(row['basin']['reference_height_m'], 0.)
            self.assertGreater(row['footwall']['production_height_m'], 0.)
            self.assertGreater(row['footwall']['reference_height_m'], 0.)

    def test_time_domain_and_physical_envelopes(self):
        limits = self.metrics['limits']
        self.assertEqual([row['intervals'] for row in self.metrics['time_partitions']], [32, 64, 128])
        for row in self.metrics['time_partitions']:
            self.assertEqual(row['accepted_intervals'], row['intervals'])
            self.assertLessEqual(row['accepted_intervals'], 256)
            self.assertEqual(row['support_evaluations'], 1)
            self.assertLessEqual(row['difference_from_requested_outputs_m'], limits['time_difference_m'])
        for row in self.metrics['time_comparisons']:
            self.assertLessEqual(row['max_surface_difference_m'], limits['time_difference_m'])
        self.assertLessEqual(self.metrics['domain_difference_with_exterior_bounds_m'], limits['domain_difference_m'])
        for row in self.metrics['grids']:
            self.assertLessEqual(row['continuous_validity_bounds'][0], limits['displacement_m'])
            self.assertLessEqual(row['continuous_validity_bounds'][1], limits['slope'])
            self.assertLessEqual(row['max_bending_strain_bound'], limits['bending_strain'])
        control = self.metrics['hydrostatic_control']
        self.assertAlmostEqual(control['unflexed_drop_m'], 951.625819640, delta=1e-9)
        self.assertAlmostEqual(control['net_subsidence_m'], 144.185730249, delta=1e-9)
        self.assertAlmostEqual(control['net_subsidence_m'], control['direct_density_fraction_subsidence_m'], delta=1e-10)


if __name__ == '__main__':
    unittest.main()
