"""Optimised default selection; no benchmarks or changed mathematical criteria."""
from __future__ import annotations
import ast
import inspect
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest

import numpy as np
from atlas_tectonics import (
    advect_thickness, half_space_temperature, PeriodicGrid1D, ThermalParameters,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ThermalParameters('synthetic', 'default-selection regression', 300., 1300., 1.)


class OptimisedDefaultTests(unittest.TestCase):
    def test_transport_selects_native_by_default(self):
        h = np.linspace(1., 2., 32)
        u = np.sin(np.arange(32.))
        grid = PeriodicGrid1D(32, 32.)
        default = advect_thickness(h, u, grid, .2)
        explicit = advect_thickness(h, u, grid, .2, backend='numba')
        reference = advect_thickness(h, u, grid, .2, backend='reference')
        self.assertEqual(default.backend, 'numba')
        self.assertEqual(reference.backend, 'reference')
        self.assertEqual(default.thickness_m.tobytes(), explicit.thickness_m.tobytes())
        self.assertEqual(default.face_flux_m2_s.tobytes(), reference.face_flux_m2_s.tobytes())
        self.assertEqual(default.thickness_m.tobytes(), reference.thickness_m.tobytes())
        self.assertEqual(default.solid_volume_per_width_after_m2, reference.solid_volume_per_width_after_m2)

    def test_cooling_selects_bulk_backend_by_default(self):
        depth = np.linspace(0., 10., 129)[:, None]
        age = np.array([0., 1., 4.])[None, :]
        default = half_space_temperature(depth, age, PROFILE)
        explicit = half_space_temperature(depth, age, PROFILE, backend='scipy')
        reference = half_space_temperature(depth, age, PROFILE, backend='reference')
        self.assertEqual(default.tobytes(), explicit.tobytes())
        np.testing.assert_allclose(default, reference, rtol=2e-15, atol=1e-12)
        with self.assertRaises(ValueError):
            default.setflags(write=True)

    def test_public_signatures_have_explicit_optimised_defaults(self):
        self.assertEqual(inspect.signature(advect_thickness).parameters['backend'].default, 'numba')
        self.assertEqual(inspect.signature(half_space_temperature).parameters['backend'].default, 'scipy')

    def test_cached_cooling_signature_matches_kernel_default(self):
        # Structural coverage only: persistent store behaviour is unchanged and
        # belongs to the existing full storage/reuse tests.
        tree = ast.parse((ROOT / 'src/atlas_tectonics/reuse.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'cached_temperature')
        defaults = dict(zip((a.arg for a in fn.args.kwonlyargs), fn.args.kw_defaults))
        self.assertEqual(ast.literal_eval(defaults['backend']), 'scipy')

    def test_dependencies_support_normal_default_calls(self):
        metadata = tomllib.loads((ROOT / 'pyproject.toml').read_text())
        self.assertIn('numba==0.65.1', metadata['project']['dependencies'])
        self.assertIn('scipy>=1.15,<2', metadata['project']['dependencies'])

    def _missing_dependency(self, dependency: str):
        code = r'''
import builtins
real = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == BLOCK or name.startswith(BLOCK + '.'):
        raise ImportError('deliberately unavailable')
    return real(name, *args, **kwargs)
builtins.__import__ = blocked
import numpy as np
from atlas_tectonics import advect_thickness, half_space_temperature, PeriodicGrid1D, ThermalParameters, TectonicsError
p = ThermalParameters('synthetic', 'missing-dependency test', 300., 1300., 1.)
g = PeriodicGrid1D(8, 8.)
if BLOCK == 'numba':
    args = (np.ones(8), np.zeros(8), g, .2)
    fn = advect_thickness
else:
    args = (np.arange(8.), 1., p)
    fn = half_space_temperature
fn(*args, backend='reference')
try:
    fn(*args)
except TectonicsError as exc:
    assert 'unavailable' in str(exc), str(exc)
else:
    raise AssertionError('default silently fell back')
'''
        code = 'BLOCK = ' + repr(dependency) + '\n' + code
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1')
        proc = subprocess.run([sys.executable, '-B', '-c', code], env=env,
                              capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_missing_numba_refuses_default_not_reference(self):
        self._missing_dependency('numba')

    def test_missing_scipy_refuses_default_not_reference(self):
        self._missing_dependency('scipy')

    def test_historical_result_restoration_keeps_reference_label(self):
        from atlas_tectonics.transport import _restore_result
        restored = _restore_result(np.ones(8), np.zeros(8), 8., 8., 0., 0.)
        self.assertEqual(restored.backend, 'reference')

if __name__ == '__main__':
    unittest.main()
