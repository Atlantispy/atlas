"""Focused case2a adaptive-marking checks."""
import gc
import json
import threading
import unittest

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.constitutive import CancelledError
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.subduction_mesh import build_mesh

from atlas_tectonics import subduction_refinement as candidate


class SubductionRefinementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geometry_budget = WorkBudget(128*1024**2)
        cls.mesh = build_mesh(24., grading='corner-r5', budget=cls.geometry_budget)
        cls.wedge = cls.mesh.wedge()

    @classmethod
    def tearDownClass(cls):
        cls.wedge.close()
        cls.mesh.close()
        assert cls.geometry_budget.reserved_bytes == 0

    def fields(self):
        t = 500.+self.mesh.points[:, 1]
        p = self.wedge.points/660.
        v = np.column_stack((p[:, 0]*p[:, 1], p[:, 0]**2))
        return t, v

    def test_affine_velocity_constant_temperature_empty(self):
        owner = WorkBudget(128*1024**2)
        v = (self.wedge.points-50.)@np.array([[.3, -.2], [.1, .4]])+17.
        points, metadata = candidate.select_refinement_points(self.mesh, self.wedge,
            np.full(len(self.mesh.points), 1000.), v, budget=owner)
        self.assertEqual(points.shape, (0, 2))
        self.assertEqual(metadata['decision'], 'zero-indicators')
        self.assertEqual(metadata['velocity_normalisation_max'], 0.)
        self.assertEqual(metadata['viscosity_normalisation_max'], 0.)
        del points, metadata
        gc.collect()
        self.assertEqual(owner.reserved_bytes, 0)

    def test_deterministic_tie_and_minimal_squared_bulk(self):
        selected, _, _, fraction, preceding = candidate._bulk(np.ones(12), np.zeros(12))
        np.testing.assert_array_equal(selected, [0, 1, 2])
        self.assertEqual(fraction, .25)
        self.assertLess(preceding, .25)
        selected2, *_ = candidate._bulk(np.ones(12), np.zeros(12))
        np.testing.assert_array_equal(selected, selected2)
        with self.assertRaises(MemoryLimitError):
            candidate._bulk(np.ones(16385), np.zeros(16385))

    def test_real_mesh_finite_centroids_immutability_and_retained_lifetime(self):
        owner = WorkBudget(128*1024**2)
        t, v = self.fields()
        points, metadata = candidate.select_refinement_points(self.mesh, self.wedge, t, v, budget=owner)
        self.assertGreater(len(points), 0)
        self.assertTrue(np.isfinite(points).all())
        self.assertTrue(np.all((points[:, 1] > 50.) & (points[:, 1] < points[:, 0])
                               & (points[:, 0] < 660.) & (points[:, 1] < 600.)))
        self.assertGreaterEqual(metadata['achieved_squared_fraction'], .25)
        self.assertLess(metadata['preceding_squared_fraction'], .25)
        self.assertEqual(metadata['geometry_id'], self.mesh.geometry_id)
        json.dumps(metadata, allow_nan=False)
        with self.assertRaises(ValueError):
            points.setflags(write=True)
        retained = owner.reserved_bytes
        self.assertEqual(retained, 512+points.nbytes+8192+128*len(points))
        view = points[:]
        del points
        gc.collect()
        self.assertEqual(owner.reserved_bytes, retained)
        del view
        gc.collect()
        self.assertEqual(owner.reserved_bytes, 8192+128*metadata['selected_count'])
        del metadata
        gc.collect()
        self.assertEqual(owner.reserved_bytes, 0)

    def test_budget_refusal_and_cancellation_leave_no_lease(self):
        t, v = self.fields()
        owner = WorkBudget(1024)
        with self.assertRaises(MemoryLimitError):
            candidate.select_refinement_points(self.mesh, self.wedge, t, v, budget=owner)
        self.assertEqual(owner.reserved_bytes, 0)
        owner = WorkBudget(128*1024**2)
        event = threading.Event()
        event.set()
        with self.assertRaises(CancelledError):
            candidate.select_refinement_points(self.mesh, self.wedge, t, v, budget=owner, cancel=event)
        class DuringWork:
            calls = 0
            def is_set(self):
                self.calls += 1
                return self.calls == 5
        with self.assertRaises(CancelledError):
            candidate.select_refinement_points(self.mesh, self.wedge, t, v, budget=owner, cancel=DuringWork())
        self.assertEqual(owner.reserved_bytes, 0)

    def test_invalid_fields_and_unrelated_wedge_refused(self):
        owner = WorkBudget(128*1024**2)
        t, v = self.fields()
        for invalid in (t[:-1], np.full(t.shape, np.nan), np.zeros(t.shape)):
            with self.assertRaises(TectonicsError):
                candidate.select_refinement_points(self.mesh, self.wedge, invalid, v, budget=owner)
        with build_mesh(25., budget=owner) as other, other.wedge() as other_wedge:
            with self.assertRaises(TectonicsError):
                candidate.select_refinement_points(self.mesh, other_wedge, t,
                    np.zeros((len(other_wedge.points), 2)), budget=owner)
        self.assertEqual(owner.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
