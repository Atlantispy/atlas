"""K3 and sampler edge contracts, predeclared in i03_controls_v4.json before this run."""
import json
import math
import unittest

import numpy as np

import i03_fixtures as F
import test_i03_junction_paths as J
from atlas_tectonics import integration_junction_paths as P, integration_sphere as S, integration_transfer as T
from atlas_tectonics.integration_ledger import LedgerError
from atlas_tectonics.spherical_atlas import _ANGULAR_RESOLUTION
from atlas_tectonics.spherical_geometry import SphericalChart


CONTROL = json.loads((F.CASES/'i03_controls_v4.json').read_text(encoding='utf-8'))['controls']['junction_path_contract']
C1 = json.loads((F.CASES/'i01_transitions_v1.json').read_text(encoding='utf-8'))['control_policy']['algebra_relative']


class JunctionPathContractTests(unittest.TestCase):
    def test_accuracy_bounds_are_exclusive_and_not_algebra_tolerances(self):
        floor, cap = S.ATTACHMENT_BAND_RAD, math.pi/2
        for accuracy in (np.nextafter(floor, 0.), floor, cap, np.nextafter(cap, math.inf)):
            with self.subTest(accuracy=accuracy), self.assertRaisesRegex(LedgerError, 'accuracy'):
                P.JunctionPath('junction:N', 'O', F.IDENTITY, float(accuracy), CONTROL['exact_small_ceiling'])
        for accuracy in (np.nextafter(floor, math.inf), np.nextafter(cap, 0.)):
            path = P.JunctionPath('junction:N', 'O', F.IDENTITY, float(accuracy), CONTROL['exact_small_ceiling'])
            self.assertEqual(path.max_deviation_rad, accuracy)
        self.assertEqual(P.ALGEBRA_RELATIVE, C1)
        self.assertEqual(T.ALGEBRA_RELATIVE, P.ALGEBRA_RELATIVE)

    def test_dyadic_ceiling_refuses_without_rounding_it_up(self):
        point = np.asarray(CONTROL['small_circle_point_unscaled'], dtype=float)
        point /= np.linalg.norm(point)
        rate = np.asarray(CONTROL['small_circle_rate_rad'], dtype=float)
        low, enough = CONTROL['small_circle_ceilings']
        with self.assertRaisesRegex(LedgerError, 'segment ceiling'):
            P.sample(np.zeros(3), rate, point, CONTROL['small_circle_accuracy_rad'], low, None)
        points = P.sample(np.zeros(3), rate, point, CONTROL['small_circle_accuracy_rad'], enough, None)
        self.assertEqual(len(points)-1, enough)
        self.assertLessEqual(2*math.asin(float(rate @ rate)/(8*enough*enough)),
                             CONTROL['small_circle_accuracy_rad'])

    def test_exact_near_antipodal_arc_obeys_existing_chart_limits(self):
        point = np.asarray(CONTROL['point'], dtype=float)
        rate = (math.pi-CONTROL['near_antipodal_gap_rad'])*np.asarray(CONTROL['near_antipodal_axis'])
        low, enough = CONTROL['near_antipodal_ceilings']
        with self.assertRaisesRegex(LedgerError, 'segment ceiling'):
            P.sample(np.zeros(3), rate, point, CONTROL['accuracy_rad'], low, None)
        points = P.sample(np.zeros(3), rate, point, CONTROL['accuracy_rad'], enough, None)
        self.assertEqual(len(points)-1, enough)
        for a, b in zip(points, points[1:]):
            centre = (a+b)/np.linalg.norm(a+b)
            self.assertGreaterEqual(float(min(a @ centre, b @ centre)), S.CHART_MIN_COSINE)
            self.assertGreater(float(F.angle(a, b)), _ANGULAR_RESOLUTION)
            self.assertLess(float(F.angle(a, b)), math.pi-_ANGULAR_RESOLUTION)
            chart = SphericalChart(F.sphere(), tuple(centre), S.CHART_MIN_COSINE)
            self.assertTrue(np.all(np.isfinite(chart._project(np.asarray([a, b])))))

    def test_small_exact_arc_stays_sparse_but_unresolved_edge_refuses(self):
        point = np.asarray(CONTROL['point'], dtype=float)
        points = P.sample(np.zeros(3), np.asarray(CONTROL['exact_small_rate_rad']), point,
                          CONTROL['exact_small_accuracy_rad'], CONTROL['exact_small_ceiling'], None)
        self.assertEqual(len(points)-1, CONTROL['exact_small_ceiling'])
        with self.assertRaisesRegex(LedgerError, 'existing atlas resolution'):
            P.sample(np.zeros(3), np.asarray(CONTROL['subresolution_rate_eps'])*np.finfo(float).eps, point,
                     CONTROL['exact_small_accuracy_rad'], CONTROL['exact_small_ceiling'], None)
        with self.assertRaisesRegex(LedgerError, 'spans pi or more'):
            P.sample(np.zeros(3), math.pi*np.asarray(CONTROL['near_antipodal_axis']), point,
                     CONTROL['accuracy_rad'], CONTROL['near_antipodal_ceilings'][-1], None)

    def test_full_interval_normal_drift_certificate_and_c1_use_declared_history(self):
        network, motion = J.world(), J.motion()
        _, _, _, _, diagnostic = P.prepare(network, motion, None, T.TransferRefused)
        junction = next(j for j in network.junctions if j.junction_id == motion.junction_paths[0].junction_id)
        x0 = network.vertex_direction[network.vertex_ids.index(junction.vertex_id)]
        rate = P.vector(motion.junction_paths[0].relative_rotation)
        rates = {plate: P.vector(rotation) for plate, rotation in motion.rotations}
        boundaries = {b.boundary_id: b for b in network.boundaries}
        planes = dict(network._layout.poles)
        ds, initials, lowers, drifts, residual = [], [], [], [], []
        plates = set()
        for end in junction.boundary_ends:
            boundary = boundaries[end[0]]
            plates.update((boundary.left_plate_id, boundary.right_plate_id))
            carrier = (1-boundary.accretion_fraction)*rates[boundary.left_plate_id]+boundary.accretion_fraction*rates[boundary.right_plate_id]
            d = rate-carrier
            tangent = np.cross(d, x0)
            speed = np.linalg.norm(tangent)
            self.assertGreater(speed, S.ATTACHMENT_BAND_RAD)
            lower = speed-np.linalg.norm(d)*np.linalg.norm(rate)
            self.assertGreater(lower, 0.)
            ds.append(d)
            initials.append(np.cross(x0, tangent)/speed)
            lowers.append(lower)
            drifts.append(2*np.linalg.norm(d)*np.linalg.norm(rate)/lower)
            residual.append(float(np.asarray(planes[end]) @ tangent))
        plates = sorted(plates)
        scale = max(np.linalg.norm(np.cross(rates[a]-rates[b], x0))
                    for i, a in enumerate(plates) for b in plates[i+1:])
        self.assertLessEqual(float(np.linalg.norm(residual)/scale), C1)
        self.assertLessEqual(diagnostic[junction.vertex_id], C1)
        certified = [(i, j, np.linalg.norm(np.cross(a, b))-drifts[i]-drifts[j])
                     for i, a in enumerate(initials) for j, b in enumerate(initials) if j > i]
        self.assertTrue(any(lower >= T.SHALLOWEST_SINE for _, _, lower in certified))
        for s in np.linspace(0., 1., CONTROL['normal_samples']):
            x = S._placed(P.exponential(s*rate), x0)[0]
            normals = []
            for i, d in enumerate(ds):
                tangent = np.cross(d, x)
                self.assertGreaterEqual(np.linalg.norm(tangent), lowers[i])
                normal = np.cross(x, tangent)/np.linalg.norm(tangent)
                self.assertLessEqual(np.linalg.norm(normal-initials[i]), drifts[i])
                normals.append(normal)
            for i, j, lower in certified:
                self.assertGreaterEqual(np.linalg.norm(np.cross(normals[i], normals[j])), lower)


if __name__ == '__main__':
    unittest.main()
