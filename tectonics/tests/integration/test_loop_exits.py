"""Loops that need an exit refuse bad input instead of spinning (ruling 1947)."""
from fractions import Fraction
import threading
import unittest

import numpy as np


class LoopExits(unittest.TestCase):
    def test_unterminated_json_string(self):
        from atlas_tectonics._private.integration.geometry import geometry_transfer as G
        from atlas_tectonics._private import private_heat_issuer_resources_r1 as R1
        from atlas_tectonics._private import private_heat_issuer_resources_r4 as R4
        for call, error in ((G._json_decode_bytes, G.GeometryTransferRefused),
                            (R1.json_shape, ValueError), (R4.json_cost, ValueError)):
            with self.subTest(call=call.__module__), self.assertRaisesRegex(error, '(?i)unterminated'):
                call(b'{"a": "b')

    def test_q2_leaf_ceiling(self):
        from atlas_tectonics.integration.geometry import native_projection as N
        from atlas_tectonics.integration.resources import WorkBudget
        with self.assertRaisesRegex(Exception, 'leaf ceiling'):
            N._directed_q2_bounds({(1, 0): Fraction(1), (0, 0): Fraction(-1, 3)}, Fraction(1),
                                  max_width=Fraction(0), max_leaves=1, budget=WorkBudget(1 << 26))

    def test_subduction_mesh_bounds(self):
        from atlas_tectonics.subduction import mesh as M
        from atlas_tectonics._validation import TectonicsError
        with self.assertRaisesRegex(TectonicsError, 'spacing outside'):
            M.build_mesh(1e-4)
        with self.assertRaisesRegex(TectonicsError, 'vertex admission'):
            M._segment_points((0., 0.), (660., 0.), 1e-4, None, 'interface-r3')
        with self.assertRaisesRegex(TectonicsError, 'exceeds bounded'):
            M._interior_cloud(1e-4, None, 'interface-r3')

    def test_reentrant_revoke_refused(self):
        from atlas_tectonics.integration.parallel.owner import RevocableOwner
        seen = []
        def stop():
            try:
                owner.revoke()
            except RuntimeError as exc:
                seen.append(str(exc)); raise
        owner = RevocableOwner((), stop)
        worker = threading.Thread(target=lambda: self._quiet(owner.revoke), daemon=True)
        worker.start(); worker.join(30)
        self.assertFalse(worker.is_alive(), 're-entrant revoke deadlocked')
        self.assertTrue(seen and 'mandatory admissions' in seen[0])

    @staticmethod
    def _quiet(call):
        try:
            call()
        except Exception:
            pass

    def test_zero_progress_write(self):
        from atlas_tectonics._private.codecs import capture_store as S
        class Stuck:
            def write(self, view):
                return 0
        with self.assertRaisesRegex(OSError, 'no progress'):
            S._write_all(Stuck(), b'abc', lambda: None)

    def test_cyclic_prior_trajectory(self):
        from atlas_tectonics.integration.geometry import wall_measures as W
        class Budget:
            max_bytes = 4096
        cycle = []; cycle.append(cycle)
        with self.assertRaisesRegex(Exception, 'exceeds caller resource budget'):
            W.measure_walls(None, None, None, parent_state_id='p', start_time_s=0, end_time_s=1,
                            angular_velocity_rad_s=0, max_volume_error_m3=1, max_leaves=1,
                            budget=Budget(), prior_trajectory=cycle)

    def test_exact_sum_limb_capacity(self):
        from atlas_tectonics.crust._transport_native import _add_limb
        limbs = np.full(34, np.iinfo(np.uint64).max, dtype=np.uint64)
        with self.assertRaisesRegex(OverflowError, 'capacity'):
            _add_limb(limbs, 33, np.uint64(1))


if __name__ == '__main__':
    unittest.main()
