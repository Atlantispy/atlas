"""Bounded analytical and native initial-motion checks; no time campaign."""
from concurrent.futures import CancelledError
import copy
import math
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src')]
from test_new_world_structure import plan
from new_world_layout import generate_layout_candidate
from new_world_structure import generate_structure
from new_world_contract import ContractError
from new_world_arcs import crust_intervals
import new_world_motion as motion
from atlas_tectonics.plate_layout import evaluate_plate_kinematics, require_geological_layout_acceptance


class InitialMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = plan(seed=41)
        cls.candidate = generate_layout_candidate(cls.plan)
        cls.atlas = cls.candidate.atlas
        cls.structure = generate_structure(cls.plan)
        cls.motion = motion.generate_motion(cls.plan, cls.candidate, cls.structure)
        cls.r = cls.motion.descriptor()

    def test_repeat_detached_descriptor_and_retained_physical_status(self):
        again = motion.generate_motion(self.plan, self.candidate, self.structure)
        self.assertEqual(again.motion_id, self.motion.motion_id)
        d = again.descriptor(); d['segments'].clear()
        self.assertTrue(again.descriptor()['segments'])
        self.assertEqual(self.r['event']['column_age_context'], self.structure.report['columns'])
        self.assertEqual(self.r['event']['new_crust_volume_m3'], 0.)
        self.assertEqual(self.r['event']['onset_time_s'], self.structure.state.case.time_s)
        self.assertIsNone(self.r['event']['polarity'])
        self.assertTrue(all(not z['active'] for z in self.r['inherited_zones']))
        with self.assertRaises(Exception) as caught:
            require_geological_layout_acceptance(self.atlas)
        self.assertIn('acceptance', str(caught.exception))

    def test_all_boundary_spans_vectors_signs_and_area_closure(self):
        r, a = self.r, self.atlas
        velocities = r['angular_velocities_rad_s']
        self.assertEqual(velocities[r['rotation_frame']['anchor_plate_id']], [0., 0., 0.])
        by_edge = {}
        for s in r['segments']:
            by_edge.setdefault(s['edge_index'], []).append(s)
            e = a.edge(s['edge_index'])
            self.assertEqual((s['left_plate'], s['right_plate']), (e.left_plate_id, e.right_plate_id))
            point = np.asarray(s['position'])
            delta = np.subtract(velocities[e.right_plate_id], velocities[e.left_plate_id])
            expected = np.cross(delta, point)*a.sphere.radius_m
            np.testing.assert_allclose(s['relative_velocity_m_s'], expected, atol=1e-23, rtol=1e-12)
            self.assertLess(abs(np.dot(expected, point)), 1e-23)
            lo, hi = s['opening_range_m_s']
            self.assertLessEqual(lo-1e-23, s['opening_midpoint_m_s'])
            self.assertGreaterEqual(hi+1e-23, s['opening_midpoint_m_s'])
            if s['regime'] == 'incipient-extension':
                self.assertGreater(s['opening_midpoint_m_s'], 0.)
                self.assertGreaterEqual(lo, -1e-22)
            elif s['regime'] == 'incipient-shortening':
                self.assertLess(s['opening_midpoint_m_s'], 0.)
                self.assertLessEqual(hi, 1e-22)
        self.assertEqual(set(by_edge), set(a.interplate_edges))
        for spans in by_edge.values():
            spans.sort(key=lambda s:s['start_fraction'])
            self.assertAlmostEqual(spans[0]['start_fraction'], 0., places=14)
            self.assertAlmostEqual(spans[-1]['end_fraction'], 1., places=14)
            for s,t in zip(spans,spans[1:]):
                self.assertAlmostEqual(s['end_fraction'], t['start_fraction'], places=14)
        self.assertLess(max(map(abs, r['diagnostics']['own_area_rate_sr_s'].values())), 1e-25)

    def test_junctions_independent_velocity_equations(self):
        a, r = self.atlas, self.r
        self.assertGreater(len(r['junctions']), 0)
        for j in r['junctions']:
            point, velocity = np.asarray(j['position']), np.asarray(j['velocity_m_s'])
            self.assertLess(abs(point@velocity), 1e-23)
            for index in j['edge_indices']:
                e = a.edge(index)
                va = np.cross(r['angular_velocities_rad_s'][e.left_plate_id], point)*a.sphere.radius_m
                vb = np.cross(r['angular_velocities_rad_s'][e.right_plate_id], point)*a.sphere.radius_m
                normal = a.frames([index]).right_normal[0]
                self.assertLess(abs(normal@(velocity-.5*(va+vb))), 1e-21)

    def test_crust_changes_actual_reconciled_directions(self):
        empty = generate_structure(plan(seed=41, fraction=0.))
        spans = crust_intervals(self.atlas, empty)
        result = motion._reconcile(self.atlas, spans,
            {c.column_id:c.crust_type for c in empty.state.case.columns}, self.plan['streams']['plate_motion'])
        base = np.asarray([self.r['angular_velocities_rad_s'][p] for p in result[0]])
        other = result[2]
        # Different directions after normalisation, not only a cache key or speed multiplier.
        nonzero = np.linalg.norm(base, axis=1) > 1e-30
        b = base[nonzero]/np.linalg.norm(base[nonzero], axis=1)[:,None]
        c = other[nonzero]/np.linalg.norm(other[nonzero], axis=1)[:,None]
        self.assertGreater(float(np.linalg.norm(b-c)), .01)

    def test_common_rotation_relative_invariance(self):
        common = np.array([1e-16, -2e-16, 3e-16])
        original = self.r['angular_velocities_rad_s']
        shifted = {p:(np.asarray(w)+common).tolist() for p,w in original.items()}
        x = evaluate_plate_kinematics(self.atlas, original)
        y = evaluate_plate_kinematics(self.atlas, shifted)
        np.testing.assert_allclose(x['values'], y['values'], rtol=1e-12, atol=1e-22)

    def test_cancellation_memory_binding_refusals(self):
        event = threading.Event(); event.set()
        with self.assertRaises(CancelledError):
            motion.generate_motion(self.plan, self.candidate, self.structure, cancel=event)
        with patch.object(motion, '_LOADED_HASH', '0'*64):
            with self.assertRaises(ContractError) as caught:
                motion.check_motion(self.plan, self.atlas, self.structure, self.motion, current=True)
            self.assertEqual(caught.exception.code, 'SOURCE_MISMATCH')
        with self.assertRaises(ContractError):
            motion.check_motion(plan(seed=42), self.atlas, self.structure, self.motion)
        # Exercise this adapter's reservation after contract admission; mocking
        # the native budget class itself correctly trips native source protection.
        tiny = copy.deepcopy(self.plan)
        tiny['request']['resources']['max_work_bytes'] = 1024
        with patch.object(motion, 'validate_plan', return_value=tiny):
            with self.assertRaises(ContractError) as caught:
                motion.generate_motion(self.plan, self.candidate, self.structure)
            self.assertEqual(caught.exception.code, 'MEMORY_LIMIT')

    def test_corrupt_saved_motion_refuses_without_regeneration(self):
        r = self.motion.descriptor(); r['segments'].pop()
        with self.assertRaises(ContractError):
            motion.check_motion(self.plan,self.atlas,self.structure,motion.WorldMotion(motion._encode(r)))
        r = self.motion.descriptor(); r['event']['column_age_context'] = []
        with self.assertRaises(ContractError):
            motion.check_motion(self.plan,self.atlas,self.structure,motion.WorldMotion(motion._encode(r)))


class AnalyticalArcTests(unittest.TestCase):
    def test_pure_sliding_is_numerically_unresolved_in_any_orientation(self):
        for a,b in ((np.array([1.,0,0]),np.array([0.,1,0])),
                    (np.array([.2,.3,.93]),np.array([.8,-.1,.4]))):
            a /= np.linalg.norm(a); b /= np.linalg.norm(b)
            u,left,angle = motion._arc(a,b)
            A,B = float(left@u),-float(left@a)
            bound = motion._opening_uncertainty(np.zeros(3),left,1.,angle)
            self.assertLessEqual(math.hypot(A,B),bound)

    def test_tiny_interval_positive_speed_integral(self):
        a=np.array([1.,0,0]); u=np.array([0.,1.,0])
        lo,hi=1.,1.+1e-8; d=hi-lo; mid=.5*(lo+hi)
        radial=a*math.cos(mid)+u*math.sin(mid)
        value=motion._speed_integral(radial,a,u,lo,hi)
        self.assertGreater(value,0.)
        self.assertAlmostEqual(value/(d**3/12),1.,places=12)

    def test_interior_sign_crossing_reversal_and_range(self):
        a = np.array([1., 0., 0.]); b = np.array([0., 1., 0.])
        u, left, angle = motion._arc(a,b)
        delta = np.array([2., 1., 3.])
        A, B = float(delta@u), -float(delta@a)
        roots = motion._opening_breaks(A, B, angle)
        self.assertEqual(len(roots), 1)
        self.assertAlmostEqual(roots[0], math.atan(.5), places=14)
        ur, lr, ar = motion._arc(b,a)
        reverse_delta = -delta
        for f in (.1,.5,.9):
            opening = A*math.cos(f*angle)+B*math.sin(f*angle)
            reverse = (reverse_delta@ur)*math.cos((1-f)*ar)-(reverse_delta@b)*math.sin((1-f)*ar)
            self.assertAlmostEqual(opening, reverse, places=14)
            self.assertAlmostEqual(delta@left, reverse_delta@lr, places=14)
        self.assertEqual(motion._opening_breaks(0.,0.,angle), [])
        self.assertEqual(motion._opening_range(0.,0.,0.,angle), (0.,0.))

    def test_exact_integral_subdivision_rotation_and_quadrature(self):
        a = np.array([1.,0.,0.]); u=np.array([0.,1.,0.])
        lo, mid, hi = .15,.53,1.4
        G = motion._speed_gram(a,u,lo,hi)
        np.testing.assert_allclose(G, motion._speed_gram(a,u,lo,mid)+motion._speed_gram(a,u,mid,hi), atol=4e-16)
        x,w = np.polynomial.legendre.leggauss(24)
        s = .5*(hi+lo)+.5*(hi-lo)*x
        r = np.cos(s)[:,None]*a+np.sin(s)[:,None]*u
        numerical = sum(weight*.5*(hi-lo)*(np.eye(3)-np.outer(point,point)) for point,weight in zip(r,w))
        np.testing.assert_allclose(G,numerical,atol=4e-16)
        from atlas_tectonics.kinematics import Rotation
        Q=Rotation.from_axis_angle((1.,2.,3.),.9).matrix
        np.testing.assert_allclose(motion._speed_gram(Q@a,Q@u,lo,hi),Q@G@Q.T,atol=5e-16)


if __name__ == '__main__':
    unittest.main()
