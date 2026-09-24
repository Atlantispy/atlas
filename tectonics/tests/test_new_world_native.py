"""Bounded native S5 bridge checks; no physical evolution or world campaign."""
from concurrent.futures import CancelledError
import math
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

import numpy as np

TECTONICS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TECTONICS/'tools'), str(TECTONICS/'src')]
import new_world_native as bridge
from new_world_contract import ContractError
from new_world_layout import generate_layout_candidate
from new_world_structure import generate_structure
from new_world_motion import generate_motion
from new_world_project import SavedProject
from atlas_tectonics.resources import WorkBudget
from test_new_world_project import small_plan
from test_new_world_arcs import world, point


class NativeInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plan = small_plan()
        candidate = generate_layout_candidate(plan)
        if candidate.atlas is None:
            raise AssertionError('Fixed existing small fixture refused: '+repr(candidate.report['rejection']))
        structure = generate_structure(plan)
        motion = generate_motion(plan, candidate, structure)
        cls.project = SavedProject(dict(plan=plan, report=candidate.report,
            atlas_id=candidate.atlas.atlas_id), candidate.atlas, True, structure, motion)
        cls.result = bridge.assemble_input(cls.project, {})

    def test_real_s5_inventory_history_and_full_vector_connection(self):
        r = self.result
        md = r['metadata']
        self.assertNotEqual(md['initial_condition_id'], self.project.structure.state.state_id)
        self.assertEqual(md['geological_case_definition']['topology_id'], self.project.atlas.atlas_id)
        self.assertEqual(r['epoch_time_s'], self.project.structure.state.case.time_s)
        self.assertEqual([c['cohort_id'] for c in r['cohorts']], sorted(c['cohort_id'] for c in r['cohorts']))
        self.assertTrue(all(c['formation_time_s'] < r['epoch_time_s'] for c in r['cohorts']))
        self.assertTrue(all('mantle' not in c['cohort_id'] for c in r['cohorts']))
        self.assertEqual(md['column_id'], 'province-0')
        self.assertLess(r['gradient_s'][0][0], 0)
        delta = np.asarray(md['right_velocity_m_s'])-md['left_velocity_m_s']
        np.testing.assert_array_equal(np.asarray(r['gradient_s'])[:, 0]*40000., delta)
        np.testing.assert_array_equal(r['velocity_m_s'],
            (np.asarray(md['right_velocity_m_s'])+md['left_velocity_m_s'])/2)
        samples = md['native_samples']
        arrays, desc = samples['arrays'], samples['descriptor']
        for c, cohort in enumerate(r['cohorts']):
            for parcel in range(len(r['parcel_ids'])):
                source = math.fsum(v for j,v in enumerate(arrays['phase_volume_m3'])
                    if desc['cohort_ids'][arrays['phase_cohort_code'][j]] == cohort['cohort_id']
                    and arrays['row_cell'][arrays['phase_row'][j]] == parcel)
                self.assertEqual(r['volume_m3'][c][parcel], source)
        self.assertIn('intrinsic solid-volume unknown masks', md['inventory_semantics'])
        self.assertTrue(all(arrays['temperature_known']))
        self.assertFalse(all(arrays['solid_volume_known']))

    def test_deterministic_capture_and_partition_additivity(self):
        replay = bridge.assemble_input(self.project, {})
        self.assertEqual(bridge._payload_bytes(replay), bridge._payload_bytes(self.result))
        refined = bridge.assemble_input(self.project, dict(edge_index=self.result['metadata']['edge_index'], cells_across=8))
        for coarse, fine in zip(self.result['volume_m3'], refined['volume_m3']):
            self.assertLess(abs(math.fsum(coarse)-math.fsum(fine))/math.fsum(coarse), 2e-11)
        self.assertEqual(self.result['gradient_s'], refined['gradient_s'])

    def test_future_affine_bound_includes_translation_and_shear(self):
        from scipy.linalg import expm
        r = self.result
        bound = r['metadata']['approximation']['affine_trajectory_radius_bound_m']
        matrix = np.zeros((3,3))
        matrix[:2,:2] = r['gradient_s']
        matrix[:2,2] = r['velocity_m_s']
        vertices = np.asarray(r['polygons_m']).reshape(-1,2)
        homogeneous = np.column_stack((vertices, np.ones(len(vertices))))
        for fraction in (0., .25, .5, 1.):
            transformed = homogeneous @ expm(matrix*(r['max_elapsed_s']*fraction)).T
            self.assertLessEqual(float(np.max(np.linalg.norm(transformed[:,:2], axis=1))), bound)
        chart = r['metadata']['chart']
        np.testing.assert_allclose(np.cross(chart['basis_x'],chart['basis_y']), chart['centre'], atol=3e-16)

    def test_whole_footprint_refuses_boundary_despite_interior_centre(self):
        atlas, structure = world(((44.98,-10.), (60.,-10.), (60.,10.), (44.98,10.)))
        index = next(i for i,(a,b) in enumerate(atlas.edge_vertices)
            if {atlas.vertex_ids[a],atlas.vertex_ids[b]} == {'px','py'})
        geometry = next(g.geometry for g in structure.state.case.geometries)
        self.assertEqual(int(geometry.classify([point(45.)])[0]), 1)
        with self.assertRaisesRegex(ContractError, 'geological boundary'):
            bridge._footprint(atlas, structure.state, index, bridge._options({}),
                budget=WorkBudget(128 << 20), cancel=None)

    def test_arc_distance_interior_endpoints_and_rotation(self):
        starts = np.asarray([point(0.), point(60.)])
        ends = np.asarray([point(90.), point(90.)])
        p = point(45., 10.)
        d = bridge._arc_distances(p, starts, ends)
        self.assertAlmostEqual(d[0], math.radians(10), places=14)
        expected = math.atan2(np.linalg.norm(np.cross(p,starts[1])), float(p@starts[1]))
        self.assertAlmostEqual(d[1], expected, places=14)
        rotation = np.array([[0.,0.,1.],[1.,0.,0.],[0.,1.,0.]])
        np.testing.assert_allclose(bridge._arc_distances(rotation@p, starts@rotation.T, ends@rotation.T), d, atol=2e-16)
        with self.assertRaises(ContractError):
            bridge._arc_distances(p, starts[:1], -starts[:1])

    def test_options_source_cancellation_and_horizon_guards(self):
        for options in ({'fraction':0.}, {'fraction':1.}, {'width_m':float('nan')},
                        {'cells_across':True}, {'edge_index':True}, {'unexpected':1}):
            with self.subTest(options=options), self.assertRaises(ContractError):
                bridge._options(options)
        with patch.object(bridge, '_LOADED_HASH', '0'*64), self.assertRaisesRegex(ContractError, 'changed'):
            bridge.source_binding()
        cancelled = threading.Event(); cancelled.set()
        with self.assertRaises(CancelledError):
            bridge.assemble_input(self.project, {}, cancel=cancelled)
        with self.assertRaisesRegex(ContractError, 'trajectory bound|sweep'):
            bridge.assemble_input(self.project, dict(max_elapsed_s=1e18))


if __name__ == '__main__':
    unittest.main()
