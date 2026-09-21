"""Analytic checks for diagnostic-only cell-integral reconstruction."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location('probe', Path(__file__).parents[1]/'tools/probe_convection_r4_4.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_conduction_is_exact_and_source_unchanged(self):
        n = 8
        T = np.broadcast_to(2-(np.arange(n)+.5)[:, None]/n, (n, n)).copy()
        saved = T.copy()
        for m in (8, 16, 32):
            fine = probe.temperature_on_grid(T, m)
            expected = np.broadcast_to(2-(np.arange(m)+.5)[:, None]/m, (m, m))
            np.testing.assert_allclose(fine, expected, rtol=0, atol=2e-15)
        np.testing.assert_array_equal(T, saved)

    def test_exact_mode_cell_integrals_and_coarse_restriction(self):
        def field(n):
            x = (np.arange(n)+.5)/n
            return 2-x[:, None]+.01*np.sin(3*np.pi*x[:, None])*np.cos(2*np.pi*x)*np.sinc(3/(2*n))*np.sinc(2/(2*n))
        coarse = field(8)
        fine = probe.temperature_on_grid(coarse, 32)
        np.testing.assert_allclose(fine, field(32), rtol=0, atol=2e-15)
        np.testing.assert_allclose(fine.reshape(8,4,8,4).mean(axis=(1,3)), coarse, rtol=0, atol=2e-15)

    def test_free_slip_quadratic_surface_exact(self):
        n = 16
        x = np.arange(n+1)/n
        y = 1-(np.arange(n)+.5)/n
        u = (1+3*y[:, None]**2)*np.sin(np.pi*x)
        u[:, [0,-1]] = 0
        result = probe.surface_probes(u)
        self.assertAlmostEqual(result['quadratic_free_slip_wall']['rms'], 1/np.sqrt(2), places=14)
        self.assertAlmostEqual(result['quadratic_free_slip_wall']['maximum_signed'], 1., places=14)
        self.assertGreater(result['registered_nearest_row']['maximum_signed'], 1.)

    def test_invalid_inputs_refused(self):
        for value, n in ((np.ones((3,4)),8), (np.full((4,4),np.nan),8), (np.zeros((4,4)),8), (np.ones((4,4)),2)):
            with self.assertRaises(ValueError): probe.temperature_on_grid(value,n)
        with self.assertRaises(ValueError): probe.surface_probes(np.ones((4,5)))


if __name__ == '__main__':
    unittest.main()
