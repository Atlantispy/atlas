"""Bounded source-reconstruction checks, not a geological experiment."""
from contextlib import redirect_stdout
import io
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import reconstruct_i01_initiation_case as target


class ReconstructionTests(unittest.TestCase):
    def test_retained_record_is_bound_and_still_not_an_admitted_case(self):
        path = Path(__file__).resolve().parents[1] / 'cases/i01_li_gurnis_reconstruction_v1.json'
        record = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(record['tool_sha256'], hashlib.sha256(Path(target.__file__).read_bytes()).hexdigest())
        self.assertFalse(record['scientific_acceptance'])
        self.assertFalse(record['runnable_configuration'])
        self.assertFalse(record['reference_curve_admitted'])
        self.assertEqual(record['source_files'], {
            name: {'bytes': size, 'sha256': digest} for name, (size, digest) in target.FILES.items()})
        row = record['diagnostic']
        self.assertEqual(record['raw_row_zero_based'], 2)
        self.assertEqual(row['sample_count'], 24)
        self.assertEqual(row['omitted_trailing_nan_pairs'], 16)
        self.assertAlmostEqual(row['nominal_convergence_m'][-1], 199584.34848181924)
        np.testing.assert_allclose(row['nominal_convergence_m'], np.array(row['time_Myr'])*40000)
        np.testing.assert_array_equal(row['compression_positive_column_force_N_per_m'],
                                      -np.array(row['raw_signed_column_force_N_per_m']))
        self.assertNotIn('force_N_per_m', row)  # cannot be mistaken for an admitted resistance curve
        source = record['source_code_derivations']
        self.assertEqual(source['effective_activation_energy_J_per_mol'], 504000)
        self.assertEqual(source['required_missing_external_files'], ['inputfile.txt', 'morbphase.txt'])

    def test_units_sign_and_initial_zero_retained(self):
        result = target.reconstruct_row([0., 1., 2., np.nan],
                                        [0., -3., 2., np.nan],
                                        .04 / target.SECONDS_PER_YEAR)
        np.testing.assert_allclose(result['nominal_convergence_m'], [0., 40000., 80000.])
        self.assertEqual(result['compression_positive_column_force_N_per_m'], [-0., 3., -2.])
        self.assertEqual(result['raw_signed_column_force_N_per_m'], [0., -3., 2.])
        self.assertEqual(result['sample_count'], 3)
        self.assertEqual(result['omitted_trailing_nan_pairs'], 1)

    def test_missing_unpaired_and_interior_padding_refused(self):
        for t, f in [([np.nan]*3, [np.nan]*3), ([0., np.nan, 1.], [1., np.nan, 2.]),
                     ([0., 1., np.nan], [1., 2., 3.]), ([0., 1., np.inf], [1., 2., np.nan])]:
            with self.subTest(t=t, f=f), self.assertRaises(ValueError):
                target.reconstruct_row(t, f, 1.)

    def test_order_shape_speed_and_overflow_refused(self):
        for t, f, u in [([0., 0.], [1., 2.], 1.), ([-1., 0.], [1., 2.], 1.),
                        ([1., 0.], [1., 2.], 1.), ([0., 1.], [1.], 1.),
                        ([0, 1], [1., 2.], 1.), ([0., 1.], [1., 2.], True),
                        ([0., 1.], [1., 2.], -1.), ([0., 1.], [1., 2.], np.inf),
                        ([0., 1e308], [1., 2.], 1.), ([float(i) for i in range(41)], [1.]*41, 1.)]:
            with self.subTest(t=t, u=u), self.assertRaises(ValueError):
                target.reconstruct_row(t, f, u)

    def test_row_inputs_unchanged(self):
        t = np.array([0., 1., np.nan]); f = np.array([0., -2., np.nan])
        before_t, before_f = t.copy(), f.copy()
        target.reconstruct_row(t, f, 1.)
        np.testing.assert_equal(t, before_t)
        np.testing.assert_equal(f, before_f)

    def test_changed_source_refused_before_npz_load(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'README.docx').write_bytes(b'not the original')
            with patch.object(target.np, 'load', side_effect=AssertionError('must not load')):
                with self.assertRaisesRegex(ValueError, 'changed or incompatible'):
                    target.reconstruct(directory)

    def test_exclusive_output_and_failure_do_not_write(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            output = Path(directory) / 'output.json'
            record = {'diagnostic': {'sample_count': 2}, 'scientific_acceptance': False}
            with patch.object(target, 'reconstruct', return_value=record):
                target.main([directory, '--output', str(output)])
                with self.assertRaises(FileExistsError):
                    target.main([directory, '--output', str(output)])
            self.assertEqual(json.loads(output.read_text()), record)
            fresh = Path(directory) / 'no-partial.json'
            with patch.object(target, 'reconstruct', side_effect=ValueError('source changed')):
                with self.assertRaises(ValueError):
                    target.main([directory, '--output', str(fresh)])
            self.assertFalse(fresh.exists())

    def test_activation_scaling_identity_is_not_silently_repaired(self):
        for temperature_C in (500., 1000., 1400.):
            exponent_from_code = 540000/(8.31*3*1500) * (
                1/(temperature_C/1400 + 273/1400) - 1/(1 + 273/1400))
            dimensional = 504000/(8.31*3) * (1/(temperature_C+273) - 1/1673)
            self.assertAlmostEqual(exponent_from_code, dimensional, places=12)
        self.assertFalse(math.isclose(504000., 540000.))


if __name__ == '__main__':
    unittest.main()
