"""I04.2: D1 on the I03 sphere with GPE from P1 columns (decisions proposal C-1 to C-6; cases/i04_controls_v1.json).

Every expected value is analytic or an existing tolerance, fixed before the run. Balance alone does not validate a
force law: these controls verify geometry, signs, frame, power, ownership and refusals, not Earth motions.
"""
from fractions import Fraction
from pathlib import Path
import math
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import check_i01_closures as closures                       # noqa: E402

import i03_fixtures as F                                    # noqa: E402
import i04_fixtures as X                                    # noqa: E402
from atlas_tectonics import integration_driving as D       # noqa: E402
from atlas_tectonics import integration_ports as P         # noqa: E402
from atlas_tectonics import integration_sphere as S        # noqa: E402
from atlas_tectonics import integration_transfer as T      # noqa: E402

ALGEBRA = X.POLICY['algebra_relative']
R = X.RADIUS_M


def rel(actual, expected):
    actual, expected = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    return float(np.linalg.norm(actual-expected)/max(float(np.linalg.norm(expected)), np.finfo(float).tiny))


def unit(v):
    v = np.asarray(v, dtype=float)
    return v/np.linalg.norm(v)


EPS = float(np.finfo(float).eps)


def edge_bound(rings):
    """Derived rounding bound on D.edge_sum, elementwise (rulings A1.4; derivation in I04_CAUSAL_START R4-1):
    eps [sum_e (7/cos(t/2) + 1.5/cos^2(t/2) + 4)|b - a| + (n_e + 1) sum_e |b - a|]."""
    total, lengths, count = 0., 0., 0
    for ring in rings:
        ring = np.asarray(ring, dtype=float)
        for a, b in zip(ring, np.roll(ring, -1, axis=0)):
            half = math.atan2(float(np.linalg.norm(np.cross(a, b))), float(a @ b))/2
            d = float(np.linalg.norm(b-a))
            total += (7/math.cos(half)+1.5/math.cos(half)**2+4)*d
            lengths += d
            count += 1
    return EPS*(total+(count+1)*lengths)


def moment_bound(rings):
    """|dS| elementwise <= C7/3 + (edge bound + eps sum|b - a|)/6, C7 being I03's measure bound (fails closed)."""
    c7 = S._measure_bound([np.asarray(r, dtype=float) for r in rings])
    if c7 is None:
        raise AssertionError('C7 undefined for this face: no per-face comparison is made')
    lengths = sum(float(np.linalg.norm(b-a)) for ring in rings
                  for a, b in zip(np.asarray(ring, dtype=float), np.roll(np.asarray(ring, dtype=float), -1, axis=0)))
    return c7/3+(edge_bound(rings)+EPS*lengths)/6


def exact_edge_sum(rings):
    """The same edge sum in exact rational arithmetic on the same binary64 inputs."""
    total = [[Fraction(0)]*3 for _ in range(3)]
    for ring in rings:
        ring = [[Fraction(float(x)) for x in v] for v in np.asarray(ring, dtype=float)]
        for a, b in zip(ring, ring[1:]+ring[:1]):
            d = [b[i]-a[i] for i in range(3)]
            x = [d[1]*a[2]-d[2]*a[1], d[2]*a[0]-d[0]*a[2], d[0]*a[1]-d[1]*a[0]]
            q = 1+sum(a[i]*b[i] for i in range(3))
            c = [v/q for v in x]
            s = [a[i]+b[i] for i in range(3)]
            for i in range(3):
                for j in range(3):
                    total[i][j] += c[i]*s[j]+s[i]*c[j]
    return total


class ClosedFormMoments(unittest.TestCase):
    """C-1 and C-2: exact spherical second moments (relative 1e-11, the existing algebra gate)."""

    def moment(self, ring):
        rings = [np.array([unit(v) for v in ring])]
        return D.polygon_moment(rings, S._measure(rings)), S._measure(rings)

    def test_octant_analytic(self):
        m, area = self.moment([(1, 0, 0), (0, 1, 0), (0, 0, 1)])
        expected = np.full((3, 3), 1/3)
        np.fill_diagonal(expected, math.pi/6)
        self.assertLess(rel(m, expected), ALGEBRA)
        self.assertLess(abs(np.trace(m)-area)/area, ALGEBRA)

    def test_lune_analytic(self):
        for lo, hi in ((0., 50.), (20., 170.), (-30., 100.)):
            a, b = math.radians(lo), math.radians(hi)
            ring = [(0, 0, -1)]+[F.direction(hi, lat) for lat in (-60, -20, 20, 60)]+[(0, 0, 1)] + \
                   [F.direction(lo, lat) for lat in (60, 20, -20, -60)]
            m, _ = self.moment(ring)
            # int over theta of sin^3 = 4/3, of cos^2 sin = 2/3; longitudes from a to b.
            xx = 4/3*((b-a)/2+(math.sin(2*b)-math.sin(2*a))/4)
            yy = 4/3*((b-a)/2-(math.sin(2*b)-math.sin(2*a))/4)
            xy = 4/3*(math.sin(b)**2-math.sin(a)**2)/2
            expected = np.array([[xx, xy, 0.], [xy, yy, 0.], [0., 0., 2/3*(b-a)]])
            self.assertLess(rel(m, expected), ALGEBRA, (lo, hi))

    def test_rotation_covariance_and_additivity(self):
        """Per-face comparisons use the derived absolute bound, never a flat relative 1e-11 (rulings A1.4)."""
        for size in (.5, 1e-2, 1e-5):
            quad = [unit(np.array((1., 0., 0.))+size*np.asarray(v)) for v in ((0, -1, -.4), (0, 1, -.6),
                                                                              (0, .7, 1), (0, -.9, .8))]
            m, _ = self.moment(quad)
            q, _ = X.frame_rotation()
            turned_ring = [q @ v for v in quad]
            turned, _ = self.moment(turned_ring)
            # Rotating inputs moves each vertex by at most ~3 eps: Lipschitz term 3.4 n_e delta (R4-1 derivation),
            # plus rotating S itself (~6 eps |S|).
            perturbation = 3.4*4*3*EPS+6*EPS*float(np.max(np.abs(m)))
            self.assertLessEqual(float(np.max(np.abs(turned-q @ m @ q.T))),
                                 moment_bound([quad])+moment_bound([turned_ring])+perturbation, size)
            first, _ = self.moment(quad[:3])
            second, _ = self.moment([quad[0], quad[2], quad[3]])
            self.assertLessEqual(float(np.max(np.abs(first+second-m))),
                                 moment_bound([quad])+moment_bound([quad[:3]])
                                 + moment_bound([[quad[0], quad[2], quad[3]]]), size)

    def test_kernel_rounding_bound_is_verified_exactly(self):
        """The derived edge-sum bound holds against exact rational arithmetic, including slivers and tiny faces."""
        rng = np.random.default_rng(20261003)
        worst = 0.
        for trial in range(200):
            centre = unit(rng.normal(size=3))
            e1 = unit(np.cross(centre, rng.normal(size=3)))
            e2 = np.cross(centre, e1)
            scale = 10**rng.uniform(-7, -.3)
            squash = 1. if trial % 3 else 10**rng.uniform(-6, -1)
            count = int(rng.integers(3, 7))
            angles = np.sort(rng.uniform(0, 2*math.pi, size=count))
            ring = [unit(centre+scale*(math.cos(t)*e1+squash*math.sin(t)*e2)) for t in angles]
            computed = D.edge_sum([np.array(ring)])
            exact = exact_edge_sum([np.array(ring)])
            error = max(abs(Fraction(float(computed[i, j]))-exact[i][j]) for i in range(3) for j in range(3))
            bound = edge_bound([np.array(ring)])
            self.assertLessEqual(float(error), bound, trial)
            worst = max(worst, float(error)/bound)
        self.assertLess(worst, 1.)

    def test_orientation_guard(self):
        octant = np.array([unit(v) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))])
        with self.assertRaises(D.DrivingRefused):
            D.edge_sum([octant[::-1]])
        outer = np.array([unit(v) for v in ((1, -.3, -.3), (1, .3, -.3), (1, .3, .3), (1, -.3, .3))])
        hole = np.array([unit(v) for v in ((1, -.1, -.1), (1, -.1, .1), (1, .1, .1), (1, .1, -.1))])  # clockwise
        D.edge_sum([outer, hole])
        with self.assertRaises(D.DrivingRefused):
            D.edge_sum([outer, hole[::-1]])
        full = D.polygon_moment([outer, hole], S._measure([outer, hole]))
        plain = D.polygon_moment([outer], S._measure([outer]))
        inner = D.polygon_moment([hole[::-1]], S._measure([hole[::-1]]))
        self.assertLessEqual(float(np.max(np.abs(full-(plain-inner)))),
                             moment_bound([outer, hole])+moment_bound([outer])+moment_bound([hole[::-1]]))

    def test_network_hemisphere_and_sphere(self):
        network = X.octahedron()
        areas, moments = D.face_moments(network)
        north = [i for i, f in enumerate(network.faces) if f.plate_id == 'north']
        self.assertLess(rel(moments[north].sum(axis=0), 2*math.pi/3*np.eye(3)), ALGEBRA)
        self.assertLess(rel(moments.sum(axis=0), 4*math.pi/3*np.eye(3)), ALGEBRA)
        self.assertLess(abs(areas.sum()-4*math.pi)/(4*math.pi), ALGEBRA)

    def test_moved_network_moments_in_sphere_axes(self):
        """After a step, plate frames are not the identity: moments must still be in the sphere's axes."""
        state = F.crust(F.three_plates())
        moved = T.advance(state, F.one_plate_motion(20.), end_time_s=state.time_s+F.MYR_S).state.network
        self.assertFalse(np.allclose(moved.frames['A'].matrix, np.eye(3)))
        areas, moments = D.face_moments(moved)
        index = {vertex: i for i, vertex in enumerate(moved.vertex_ids)}
        for k, face in enumerate(moved.faces):
            ring = np.array([moved.vertex_direction[index[v]] for v in face.vertex_ids])
            local = moved.face_coordinates(k)
            expected = D.polygon_moment([ring], S._measure([ring]))
            # Plate copies may differ from the shared positions by I03's C10 band (64 eps + 4 eps): Lipschitz term
            # 3.4 n_e delta from the R4-1 derivation, plus rotating S into the sphere's axes (~6 eps |S|).
            n_e = len(face.vertex_ids)
            allowed = (moment_bound(local)+moment_bound([ring])+3.4*n_e*68*EPS
                       + 6*EPS*float(np.max(np.abs(expected))))
            self.assertLessEqual(float(np.max(np.abs(moments[k]-expected))), allowed, face.face_id)

    def test_tool_drag_matrix_parity(self):
        """C-2: the closed forms equal the retained tool on its own exact point rules."""
        network = X.octahedron()
        forcing = X.authored_forcing(network, {}, interface={'equator': X.D1['interface_k_pa_s']},
                                     omitted=('gpe', 'slab_pull', 'mantle_traction', 'authored_torque'))
        prepared = D.prepare(network, forcing)
        drag, k = X.D1['basal_drag_pa_s_m'], X.D1['interface_k_pa_s']
        north = R/math.sqrt(3)*np.array([[a, b, 1.] for a in (-1., 1.) for b in (-1., 1.)])
        basal = closures.drag_matrix(north, np.full(4, 2*math.pi*R**2/4), drag)
        angle = np.arange(8)*2*math.pi/8
        equator = R*np.column_stack((np.cos(angle), np.sin(angle), np.zeros(8)))
        edge = closures.drag_matrix(equator, np.full(8, 2*math.pi*R/8), k)
        i = prepared.plate_ids.index('north')
        self.assertLess(rel(prepared.basal[i], basal), ALGEBRA)
        self.assertLess(rel(prepared.interfaces[0][3], edge), ALGEBRA)
        # The same equator as eight 45 degree arcs: the closed form must still give pi k R^3 diag(1, 1, 2).
        eighths = X.hemispheres(8)
        forcing = X.authored_forcing(eighths, {}, interface={'equator': k},
                                     omitted=('gpe', 'slab_pull', 'mantle_traction', 'authored_torque'))
        self.assertLess(rel(D.prepare(eighths, forcing).interfaces[0][3], edge), ALGEBRA)
        a, b = np.array([1., 0., 0.]), np.asarray(F.direction(50., 0.))
        m, theta = D.arc_moment(a, b)
        nodes, weights = np.polynomial.legendre.leggauss(16)
        s = (nodes+1)*theta/2
        points = np.outer(np.cos(s), a)+np.outer(np.sin(s), np.array([0., 1., 0.]))
        quadrature = np.einsum('k,ki,kj->ij', weights*theta/2, points, points)
        self.assertLess(rel(m, quadrature), ALGEBRA)


class D1Algebra(unittest.TestCase):
    """C-3 and C-6: the retained I01 closures control on I03 geometry, plus linear force-parameter challenges."""

    def setUp(self):
        self.network = X.octahedron()
        self.drive = np.asarray(X.D1['driving_torque_n_m'], dtype=float)
        self.torques = {'north': tuple(self.drive), 'south': tuple(-self.drive)}
        self.k = X.D1['interface_k_pa_s']

    def solve(self, network=None, torques=None, **changes):
        network = self.network if network is None else network
        values = dict(interface={'equator': self.k})
        values.update(changes)
        return D.balance(network, X.authored_forcing(network, self.torques if torques is None else torques,
                                                     **values))

    def test_analytic_rotation_power_and_repeat(self):
        result = self.solve()
        drag = X.D1['basal_drag_pa_s_m']
        diag = 4*math.pi/3*drag*R**4+2*math.pi*self.k*R**3*np.array([1., 1., 2.])
        self.assertLess(rel(result.omega('north'), self.drive/diag), ALGEBRA)
        self.assertLess(rel(result.omega('south'), -self.drive/diag), ALGEBRA)
        self.assertLessEqual(result.residual, ALGEBRA)
        self.assertLess(result.power['closure_relative'], ALGEBRA)
        self.assertGreater(result.power['interface_dissipation_w'], 0)
        again = self.solve()
        self.assertTrue(np.array_equal(again.omega_rad_s, result.omega_rad_s))
        self.assertEqual(again.balance_id, result.balance_id)
        # The issued record is read-only: its mappings cannot be changed after issue.
        with self.assertRaises(TypeError):
            result.terms['extra'] = np.zeros((2, 3))
        with self.assertRaises(TypeError):
            result.power['closure_relative'] = .5
        record = result.record()
        record['power']['closure_relative'] = .5
        self.assertNotEqual(result.power['closure_relative'], .5)

    def test_zero_drive_is_exact_rest(self):
        result = self.solve(torques={'north': (0., 0., 0.), 'south': (0., 0., 0.)})
        self.assertTrue(np.all(result.omega_rad_s == 0))

    def test_frame_covariance(self):
        q, rotation = X.frame_rotation()
        turned = S.rotate_frame(self.network, rotation, 'i04-rotated-frame')
        result = self.solve()
        rotated = self.solve(network=turned, torques={p: tuple(q @ np.asarray(v)) for p, v in self.torques.items()})
        for plate in ('north', 'south'):
            self.assertLess(rel(rotated.omega(plate), q @ result.omega(plate)), ALGEBRA)

    def test_inverse_drag_scaling(self):
        base = self.solve(interface=None)
        doubled = self.solve(interface=None, drag=2*X.D1['basal_drag_pa_s_m'])
        self.assertLess(rel(doubled.omega_rad_s, .5*base.omega_rad_s), ALGEBRA)
        both = self.solve(drag=2*X.D1['basal_drag_pa_s_m'], interface={'equator': 2*self.k})
        self.assertLess(rel(both.omega_rad_s, .5*self.solve().omega_rad_s), ALGEBRA)

    def test_net_rotation_is_reported_never_subtracted(self):
        same = self.solve(torques={'north': tuple(self.drive), 'south': tuple(self.drive)}, interface=None)
        self.assertLess(rel(same.net_rotation_rad_s, same.omega('north')), ALGEBRA)
        self.assertLess(rel(same.omega('north'), same.omega('south')), ALGEBRA)
        opposite = self.solve(interface=None)
        self.assertLess(float(np.linalg.norm(opposite.net_rotation_rad_s)),
                        ALGEBRA*float(np.linalg.norm(opposite.omega('north'))))
        self.assertGreater(float(np.linalg.norm(opposite.omega('north'))), 0)
        # Unequal plates: the net rotation is the least-squares rotation, sum_i J_i (omega_i - omega_net) = 0.
        sectors = F.three_plates()
        forcing = X.authored_forcing(sectors, {'A': (1e25, 0., 3e24), 'B': (0., 2e24, 0.)},
                                     slab_omitted=('boundary-m04',), omitted=('gpe', 'mantle_traction', 'interface'))
        result = D.balance(sectors, forcing, datum=X.datum())
        prepared = D.prepare(sectors, forcing)
        moment = np.einsum('pij,pj->i', prepared.geometry, result.omega_rad_s-result.net_rotation_rad_s)
        scale = float(np.linalg.norm(np.einsum('pij,pj->i', prepared.geometry, result.omega_rad_s)))
        self.assertLess(float(np.linalg.norm(moment)), ALGEBRA*scale)
        self.assertGreater(rel(result.net_rotation_rad_s, result.omega_rad_s.mean(axis=0)), 1e-3)

    def test_mantle_traction(self):
        omega_m = np.asarray(X.CASE['mantle']['omega_rad_s'])
        network = self.network
        forcing = D.Forcing(basal_drag_pa_s_m={p: X.D1['basal_drag_pa_s_m'] for p in network.plate_ids},
                            mantle_omega_rad_s=tuple(omega_m), provenance=X.CASE['mantle']['source'],
                            omitted=('gpe', 'slab_pull', 'authored_torque', 'interface'),
                            frame_id=network.sphere.frame_id)
        alone = D.balance(network, forcing)
        for plate in network.plate_ids:
            self.assertLess(rel(alone.omega(plate), omega_m), ALGEBRA)
        driven = D.balance(network, X.authored_forcing(network, self.torques, mantle_omega_rad_s=tuple(omega_m),
                                                       omitted=('gpe', 'slab_pull', 'interface')))
        self.assertLess(driven.power['closure_relative'], ALGEBRA)
        # One driven plate: the power delivered into the moving mantle is then not zero by symmetry.
        lopsided = D.balance(network, X.authored_forcing(network, {'north': tuple(self.drive), 'south': (0., 0., 0.)},
                                                         mantle_omega_rad_s=tuple(omega_m),
                                                         omitted=('gpe', 'slab_pull', 'interface')))
        self.assertGreater(abs(lopsided.power['to_mantle_w']), 1e-3*abs(lopsided.power['driving_w']))
        self.assertLess(lopsided.power['closure_relative'], ALGEBRA)
        # A plate held nearly at rest against the moving mantle: driving power is tiny next to the dissipation and
        # mantle terms, yet the exact balance must not appear to fail the power gate.
        prepared = D.prepare(network, X.authored_forcing(network, {}, omitted=(
            'gpe', 'slab_pull', 'mantle_traction', 'authored_torque', 'interface')))
        i = prepared.plate_ids.index('north')
        hold = -(1-1e-8)*(prepared.basal[i] @ omega_m)
        held = D.balance(network, X.authored_forcing(network, {'north': tuple(hold), 'south': (0., 0., 0.)},
                                                     mantle_omega_rad_s=tuple(omega_m),
                                                     omitted=('gpe', 'slab_pull', 'interface')))
        self.assertLess(held.power['closure_relative'], ALGEBRA)
        # D -> 2D halves omega - omega_m (C-6).
        doubled = D.balance(network, X.authored_forcing(network, self.torques, mantle_omega_rad_s=tuple(omega_m),
                                                        drag=2*X.D1['basal_drag_pa_s_m'],
                                                        omitted=('gpe', 'slab_pull', 'interface')))
        self.assertLess(rel(doubled.omega_rad_s-omega_m, .5*(driven.omega_rad_s-omega_m)), ALGEBRA)

    def test_power_closure_with_mantle_rotation_and_small_torque(self):
        """Round-2 ruling: the closure scale includes the mantle-traction power |omega . M omega_m|."""
        sectors = F.three_plates()
        d = X.D1['basal_drag_pa_s_m']
        omega_m = tuple(X.CASE['mantle']['omega_rad_s'])
        for torque in (1e14, 1e18, 1e22):
            forcing = D.Forcing(basal_drag_pa_s_m={'A': d, 'B': 2*d, 'C': d/2},
                                interface_k_pa_s={'boundary-m02': 1e21}, mantle_omega_rad_s=omega_m,
                                authored_torque_n_m={'B': (torque, 0., 0.)}, slab_omitted=('boundary-m04',),
                                provenance='round-2 power-scale control', omitted=('gpe',),
                                frame_id=sectors.sphere.frame_id)
            result = D.balance(sectors, forcing)
            self.assertLessEqual(result.residual, ALGEBRA)
            self.assertLess(result.power['closure_relative'], ALGEBRA, torque)

    def test_prepared_reuse_and_stale_refusal(self):
        forcing = X.authored_forcing(self.network, self.torques, interface={'equator': self.k})
        prepared = D.prepare(self.network, forcing)
        self.assertTrue(np.array_equal(D.balance(self.network, forcing, prepared=prepared).omega_rad_s,
                                       D.balance(self.network, forcing).omega_rad_s))
        other = X.authored_forcing(self.network, self.torques, interface={'equator': self.k},
                                   drag=2*X.D1['basal_drag_pa_s_m'])
        with self.assertRaises(D.DrivingRefused) as caught:
            D.balance(self.network, other, prepared=prepared)
        self.assertEqual(caught.exception.code, D.STALE)


class GPEOnTheSphere(unittest.TestCase):
    """C-4 and C-5: the I01 two-hemisphere exact solution on I03 geometry, at the existing gates."""

    def control(self, edges):
        network = X.hemispheres(edges)
        support = P.trace_support(network)
        port = X.single_layer_columns(network, support, X.degree_one)
        return network, D.balance(network, X.gpe_forcing(network), support=support, columns_port=port,
                                  datum=X.datum())

    def test_exact_solution_refinement(self):
        gpe = X.GPE
        datum = X.datum()
        rho, rm = gpe['crust_density_kg_m3'], datum.mantle_density_kg_m3
        b = .5*datum.gravity_m_s2*rho*(1-rho/rm)*gpe['thickness_squared_amplitude_m2']
        errors = []
        for edges, receipt in zip(gpe['equator_edges'], gpe['receipt_errors']):
            network, result = self.control(edges)
            exact = {p: -gpe['reduction']*b*math.pi*R**2*np.array([0., s, 0.])/(4*math.pi/3*gpe['drag_pa_s_m']*R**4)
                     for p, s in (('north', 1.), ('south', -1.))}
            error = max(rel(result.omega(p), exact[p]) for p in exact)
            delta = math.pi/edges
            self.assertLess(abs(error-(1-math.sin(delta)/delta)), X.POLICY['sinc_error_absolute'])
            self.assertLess(abs(error-receipt), X.POLICY['sinc_error_absolute'])
            terms = result.terms['gpe']
            self.assertLess(float(np.linalg.norm(terms.sum(axis=0)))/float(np.max(np.linalg.norm(terms, axis=1))),
                            ALGEBRA)
            self.assertLess(result.power['closure_relative'], ALGEBRA)
            errors.append(error)
        self.assertLess(errors[-1], X.POLICY['finest_torque_relative'])
        low, high = X.POLICY['refinement_ratio_window']
        for coarse, fine in zip(errors, errors[1:]):
            self.assertTrue(low < coarse/fine < high, coarse/fine)

    def test_uniform_field_gives_no_torque(self):
        network = X.hemispheres(32)
        support = P.trace_support(network)
        port = X.single_layer_columns(network, support, lambda d, s: X.GPE['mean_crust_m'])
        result = D.balance(network, X.gpe_forcing(network), support=support, columns_port=port, datum=X.datum())
        anomaly = D.trace_anomaly(X.datum(), port)[0]
        scale = abs(anomaly)*R*R*2*math.pi
        self.assertLess(float(np.max(np.abs(result.terms['gpe']))), ALGEBRA*scale)

    def test_jump_cancels_globally_and_is_published(self):
        network = X.hemispheres(32)
        support = P.trace_support(network)

        def stepped(direction, side):
            # Left (north) columns thicker than right (south), varying along the boundary.
            return X.degree_one(direction, side)+(4000. if side == 0 else 0.)*(1+float(direction[1]))
        port = X.single_layer_columns(network, support, stepped)
        result = D.balance(network, X.gpe_forcing(network), support=support, columns_port=port, datum=X.datum())
        terms = result.terms['gpe']
        self.assertLess(float(np.linalg.norm(terms.sum(axis=0)))/float(np.max(np.linalg.norm(terms, axis=1))),
                        ALGEBRA)
        (name, jump), = result.jump_sensitivity
        self.assertEqual(name, 'equator')
        self.assertGreater(float(np.linalg.norm(jump)), 0)
        self.assertEqual(result.trace_partition, .5)
        # The partition's motion is published: tau_L(w) = tau_L(1/2) + (w - 1/2) J_b, so w = 1 adds J_b/2 on the
        # left and -J_b/2 on the right; the reported delta omega is exactly that response.
        (moved, delta, peak), = result.partition_motion
        prepared = D.prepare(network, X.gpe_forcing(network))
        rhs = np.zeros((2, 3))
        rhs[result.plate_ids.index('north')] = np.asarray(jump)/2
        rhs[result.plate_ids.index('south')] = -np.asarray(jump)/2
        self.assertLess(rel(delta, np.linalg.solve(prepared.matrix, rhs.reshape(-1)).reshape(2, 3)), ALGEBRA)
        self.assertGreater(peak, 0)
        self.assertIn('explicit', result.evaluation)
        self.assertIsNone(result.partition_motion_evaluation)
        self.assertNotIn('partition_motion_evaluation', result.record())

    def test_linear_gamma_challenge(self):
        network = X.hemispheres(32)
        support = P.trace_support(network)
        port = X.single_layer_columns(network, support, X.degree_one)
        authored = {'north': tuple(1e24*np.array([1., 0., 2.])), 'south': (0., 0., 0.)}

        def run(gamma):
            forcing = X.gpe_forcing(network, gamma=gamma, authored_torque_n_m=authored,
                                    omitted=('slab_pull', 'mantle_traction', 'interface'))
            return D.balance(network, forcing, support=support, columns_port=port, datum=X.datum())
        one, two = run(1.), run(2.)
        prepared = D.prepare(network, X.gpe_forcing(network))
        predicted = np.linalg.solve(prepared.matrix, one.terms['gpe'].reshape(-1)).reshape(-1, 3)
        self.assertLess(rel(two.omega_rad_s-one.omega_rad_s, predicted), ALGEBRA)

    def test_frame_covariance(self):
        network = X.hemispheres(32)
        q, rotation = X.frame_rotation()
        turned = S.rotate_frame(network, rotation, 'i04-rotated-frame')
        results = []
        for net, field in ((network, X.degree_one), (turned, lambda d, s: X.degree_one(q.T @ d, s))):
            support = P.trace_support(net)
            port = X.single_layer_columns(net, support, field)
            results.append(D.balance(net, X.gpe_forcing(net), support=support, columns_port=port, datum=X.datum()))
        for plate in ('north', 'south'):
            self.assertLess(rel(results[1].omega(plate), q @ results[0].omega(plate)), ALGEBRA)

    def test_airy_water_and_refusals(self):
        network = X.hemispheres(32)
        support = P.trace_support(network)
        water = X.CASE['water']
        depths = np.full(2*support.edges, water['depth_m'])
        dry = X.single_layer_columns(network, support, X.degree_one)
        label = water['source_label']
        wet = X.single_layer_columns(network, support, X.degree_one, water_depth_m=depths, water_source=label)
        zero = X.single_layer_columns(network, support, X.degree_one, water_depth_m=np.zeros_like(depths),
                                      water_source=label)
        with self.assertRaises(P.PortRefused) as caught:
            X.single_layer_columns(network, support, X.degree_one, water_depth_m=depths,
                                   water_source='an unnamed ocean model')
        self.assertEqual((caught.exception.code, caught.exception.detail), (P.UNSUPPORTED, 'water_source'))
        datum = X.datum()
        self.assertTrue(np.array_equal(D.trace_anomaly(datum, dry),
                                       D.trace_anomaly(datum, zero, water_regime='airy',
                                                       water_density_kg_m3=water['density_kg_m3'])))
        self.assertTrue(np.all(D.trace_anomaly(datum, wet, water_regime='airy',
                                               water_density_kg_m3=water['density_kg_m3'])
                               > D.trace_anomaly(datum, dry)))
        forcing = X.gpe_forcing(network)
        for kwargs, code, detail in ((dict(columns_port=wet), P.UNSUPPORTED, 'water regime not declared'),
                                     (dict(columns_port=wet, water_regime='finite'), P.UNSUPPORTED,
                                      'REFUSED_CORE_PLACEMENT_ABSENT'),
                                     (dict(columns_port=dry, water_regime='airy',
                                           water_density_kg_m3=water['density_kg_m3']), P.MISSING_VALUE, None)):
            with self.assertRaises(P.PortRefused) as caught:
                D.balance(network, forcing, support=support, datum=datum, **kwargs)
            self.assertEqual((caught.exception.code, caught.exception.detail), (code, detail))
        light = X.single_layer_columns(network, support, X.degree_one, density=900., water_depth_m=depths,
                                       water_source=label)
        with self.assertRaises(P.PortRefused) as caught:
            D.trace_anomaly(datum, light, water_regime='airy', water_density_kg_m3=water['density_kg_m3'])
        self.assertEqual(caught.exception.detail, 'REFUSED_WATER_IN_ROCK_COLUMN')
        # A missing water density is a named refusal, not a TypeError.
        with self.assertRaises(D.DrivingRefused) as caught:
            D.trace_anomaly(datum, wet, water_regime='airy')
        self.assertEqual(caught.exception.code, D.MISSING_FORCE)
        # A column outside the kernel's support carries the kernel message as detail.
        hot = X.single_layer_columns(network, support, X.degree_one, alpha=1e-3)
        with self.assertRaises(P.PortRefused) as caught:
            D.trace_anomaly(datum, hot)
        self.assertIn('Boussinesq', caught.exception.detail)
        # The water regime and density are part of the balance record, not only of its identity.
        result = D.balance(network, X.gpe_forcing(network), support=support, columns_port=wet, datum=datum,
                           water_regime='airy', water_density_kg_m3=water['density_kg_m3'])
        self.assertEqual((result.record()['water_regime'], result.record()['water_density_kg_m3']),
                         ('airy', water['density_kg_m3']))
        as_int = D.balance(network, X.gpe_forcing(network), support=support, columns_port=wet, datum=datum,
                           water_regime='airy', water_density_kg_m3=int(water['density_kg_m3']))
        self.assertEqual(as_int.balance_id, result.balance_id)
        with self.assertRaises(D.DrivingRefused):
            D.balance(network, X.gpe_forcing(network), support=support, columns_port=dry, datum=datum,
                      water_density_kg_m3=1025.)


class SlabPull(unittest.TestCase):
    """R4-3: declared attached slab versus the declared reduced omission (C-6 linear challenge)."""

    def setUp(self):
        self.network = F.three_plates()
        slab = X.CASE['slab']
        self.slab = D.Slab(slab['section_mass_anomaly_kg_m'], slab['transmission'], slab['source'])

    def forcing(self, slabs=None, omitted_slabs=(), **changes):
        values = dict(basal_drag_pa_s_m={p: X.D1['basal_drag_pa_s_m'] for p in self.network.plate_ids},
                      slabs=slabs if slabs is not None else {'boundary-m04': self.slab}, slab_omitted=omitted_slabs,
                      provenance=X.CASE['slab']['source'],
                      omitted=('gpe', 'mantle_traction', 'authored_torque', 'interface'),
                      frame_id=self.network.sphere.frame_id)
        values.update(changes)
        return D.Forcing(**values)

    def test_slab_pulls_the_subducting_plate_toward_the_trench(self):
        """At every trench edge midpoint the subducting plate moves INTO the overriding plate, for both sides.

        The direction comes from the boundary geometry alone: for an edge a -> b the left plate lies toward a x b.
        """
        for side in ('left', 'right'):
            network = F.three_plates(kinds={4: dict(kind=S.TRENCH, subducting_side=side)})
            result = D.balance(network, self.forcing(), datum=X.datum())
            boundary = network.boundary('boundary-m04')
            self.assertEqual(boundary.subducting_side, side)
            subducting = boundary.left_plate_id if side == 'left' else boundary.right_plate_id
            for plate in network.plate_ids:
                if plate != subducting:
                    self.assertTrue(np.all(result.omega(plate) == 0))
            index = {v: i for i, v in enumerate(network.vertex_ids)}
            chain = [np.asarray(network.vertex_direction[index[v]]) for v in boundary.vertex_ids]
            omega = result.omega(subducting)
            for a, b in zip(chain, chain[1:]):
                middle = unit(a+b)
                into_left = unit(np.cross(a, b))
                into_overriding = -into_left if side == 'left' else into_left
                velocity = np.cross(omega, middle*R)
                self.assertGreater(float(velocity @ into_overriding), 0, (side, a, b))
            self.assertLess(result.power['closure_relative'], ALGEBRA)
        # C-6: C from 1 to 0.5, not past its stated upper limit (rulings P6.4).
        result = D.balance(self.network, self.forcing(), datum=X.datum())
        halved = D.balance(self.network, self.forcing(slabs={'boundary-m04': D.Slab(
            self.slab.section_mass_anomaly_kg_m, .5*self.slab.transmission, self.slab.source)}), datum=X.datum())
        self.assertLess(rel(halved.omega_rad_s, .5*result.omega_rad_s), ALGEBRA)

    def test_exact_torque_along_the_trench(self):
        result = D.balance(self.network, self.forcing(), datum=X.datum())
        boundary = self.network.boundary('boundary-m04')
        chain = [np.asarray(self.network.vertex_direction[self.network.vertex_ids.index(v)])
                 for v in boundary.vertex_ids]
        sign = 1. if boundary.subducting_side == 'left' else -1.
        g = X.datum().gravity_m_s2
        expected = sign*self.slab.transmission*g*self.slab.section_mass_anomaly_kg_m*R*R*(chain[-1]-chain[0])
        plate = boundary.left_plate_id if sign > 0 else boundary.right_plate_id
        self.assertLess(rel(result.terms['slab_pull'][result.plate_ids.index(plate)], expected), ALGEBRA)

    def test_missing_and_misplaced_slab_refuse(self):
        with self.assertRaises(D.DrivingRefused) as caught:
            D.Forcing(basal_drag_pa_s_m={p: 1e14 for p in self.network.plate_ids}, provenance='test',
                      omitted=('gpe', 'mantle_traction', 'authored_torque', 'interface'))
        self.assertEqual(caught.exception.code, D.MISSING_FORCE)
        with self.assertRaises(D.DrivingRefused) as caught:
            D.balance(self.network, self.forcing(slabs={'boundary-m02': self.slab}), datum=X.datum())
        self.assertEqual(caught.exception.code, D.INVALID)
        omitted = D.balance(self.network, self.forcing(slabs={}, omitted_slabs=('boundary-m04',),
                                                       authored_torque_n_m={'A': (0., 0., 1e25)},
                                                       omitted=('gpe', 'mantle_traction', 'interface')))
        # Every trench omitted: no slab term at all, and the omission is recorded per trench (and needs no datum).
        self.assertNotIn('slab_pull', omitted.terms)
        self.assertEqual(omitted.omitted_slabs, ('boundary-m04',))
        self.assertEqual(omitted.record()['omitted_slabs'], ['boundary-m04'])
        self.assertEqual(omitted.unauthored_plates, ('B', 'C'))


class OwnershipAndRefusals(unittest.TestCase):
    def setUp(self):
        self.network = X.octahedron()

    def test_double_ownership_refused(self):
        with self.assertRaises(D.DrivingRefused) as caught:
            X.authored_forcing(self.network, {'north': (1e24, 0., 0.)}, interface={'equator': 1e21},
                               regional_reactions={'equator': ((1., 0., 0.), (-1., 0., 0.))})
        self.assertEqual(caught.exception.code, D.DOUBLE_OWNERSHIP)

    def test_missing_force_is_never_zero(self):
        with self.assertRaises(D.DrivingRefused) as caught:
            D.Forcing(basal_drag_pa_s_m={'north': 1e14, 'south': 1e14}, provenance='test',
                      authored_torque_n_m={'north': (1e24, 0., 0.)}, omitted=('gpe', 'mantle_traction', 'interface'))
        self.assertEqual(caught.exception.code, D.MISSING_FORCE)
        result = D.balance(self.network, X.authored_forcing(self.network, {'north': (1e24, 0., 0.)}))
        self.assertEqual(result.omitted, ('gpe', 'interface', 'mantle_traction', 'slab_pull'))

    def test_forcing_frame_must_be_the_network_frame(self):
        forcing = X.authored_forcing(self.network, {'north': (1e24, 0., 0.)}, frame_id='another-frame')
        with self.assertRaises(D.DrivingRefused) as caught:
            D.balance(self.network, forcing)
        self.assertEqual(caught.exception.code, D.STALE)
        same = D.balance(self.network, X.authored_forcing(self.network, {'north': (1e24, 0., 0.)},
                                                          frame_id=self.network.sphere.frame_id))
        self.assertEqual(same.frame_id, self.network.sphere.frame_id)

    def test_axis_dependent_forcing_must_name_the_network_frame(self):
        sectors = F.three_plates()
        d = {p: X.D1['basal_drag_pa_s_m'] for p in sectors.plate_ids}
        for vectors in (dict(authored_torque_n_m={'A': (3e24, -1e24, 1e25)}, omitted=('gpe', 'mantle_traction', 'interface')),
                        dict(mantle_omega_rad_s=(1e-16, 0., 0.), omitted=('gpe', 'authored_torque', 'interface')),
                        dict(regional_reactions={'boundary-m02': ((1e20, 0., 0.), (-1e20, 0., 0.))},
                             omitted=('gpe', 'mantle_traction', 'authored_torque'))):
            unbound = D.Forcing(basal_drag_pa_s_m=d, slab_omitted=('boundary-m04',), provenance='unbound', **vectors)
            with self.assertRaises(D.DrivingRefused) as caught:
                D.balance(sectors, unbound)
            self.assertEqual(caught.exception.code, D.STALE)
        # Axis-free forcings (drag, slabs) need no frame.
        free = D.Forcing(basal_drag_pa_s_m=d, slabs={'boundary-m04': D.Slab(2e12, 1., 'test')}, provenance='free',
                         omitted=('gpe', 'mantle_traction', 'authored_torque', 'interface'))
        self.assertEqual(D.balance(sectors, free, datum=X.datum()).frame_id, sectors.sphere.frame_id)

    def test_interface_and_torque_omissions_are_recorded_per_item(self):
        sectors = F.three_plates()
        forcing = X.authored_forcing(sectors, {'A': (0., 0., 1e25)}, interface={'boundary-m02': 1e21},
                                     slab_omitted=('boundary-m04',), omitted=('gpe', 'mantle_traction'))
        result = D.balance(sectors, forcing)
        self.assertEqual(result.omitted_interfaces, ('boundary-m00', 'boundary-m04'))
        self.assertEqual(result.unauthored_plates, ('B', 'C'))
        record = result.record()
        self.assertEqual(record['omitted_interfaces'], ['boundary-m00', 'boundary-m04'])
        everything = D.balance(sectors, X.authored_forcing(sectors, {'A': (0., 0., 1e25)},
                                                           slab_omitted=('boundary-m04',),
                                                           omitted=('gpe', 'mantle_traction', 'interface')))
        self.assertEqual(everything.omitted_interfaces, ('boundary-m00', 'boundary-m02', 'boundary-m04'))

    def test_named_refusals_at_entry_and_numpy_scalars(self):
        forcing = X.authored_forcing(self.network, {'north': (1e24, 0., 0.)})
        with self.assertRaises(D.DrivingRefused) as caught:
            D.prepare(None, forcing)
        self.assertEqual(caught.exception.code, D.INVALID)
        network = X.hemispheres(32)
        support = P.trace_support(network)
        port = X.single_layer_columns(network, support, X.degree_one)
        with self.assertRaises(D.DrivingRefused) as caught:
            D.trace_anomaly(None, port)
        self.assertEqual(caught.exception.code, D.INVALID)
        gpe = X.gpe_forcing(network)
        for bad in ('columns', support):
            with self.assertRaises(P.PortRefused) as caught:
                D.balance(network, gpe, support=support, columns_port=bad, datum=X.datum())
            self.assertEqual((caught.exception.code, caught.exception.detail), (P.UNSUPPORTED, 'columns_port'))
        for fields in (dict(pressure_pa=None, compensation_elevation_m=0.), dict(pressure_pa=1j, compensation_elevation_m=0.)):
            with self.assertRaises(D.DrivingRefused) as caught:
                D.Datum(**fields)
            self.assertEqual(caught.exception.code, D.INVALID)
        with self.assertRaises(D.DrivingRefused) as caught:
            D.Forcing(basal_drag_pa_s_m={'north': 10**400, 'south': 1e14}, provenance='overflow',
                      omitted=('gpe', 'slab_pull', 'mantle_traction', 'authored_torque', 'interface'))
        self.assertEqual(caught.exception.code, D.INVALID)
        authored = X.authored_forcing(self.network, {'north': (1e24, 0., 0.)})
        for kwargs in (dict(water_regime='bogus'), dict(water_regime='finite'), dict(water_density_kg_m3=1000.)):
            with self.assertRaises(D.DrivingRefused) as caught:
                D.balance(self.network, authored, **kwargs)
            self.assertEqual(caught.exception.code, D.INVALID, kwargs)
        with self.assertRaises(P.PortRefused) as caught:
            D.balance(network, gpe, support='support', columns_port=port, datum=X.datum())
        self.assertEqual((caught.exception.code, caught.exception.detail), (P.INCOMPATIBLE_SUPPORT, 'support'))
        with self.assertRaises(P.PortRefused) as caught:
            D.balance(network, gpe, support=support, columns_port=port, datum=None)
        self.assertEqual((caught.exception.code, caught.exception.detail), (P.MISSING_VALUE, 'datum'))
        scalar = D.Forcing(basal_drag_pa_s_m={'north': np.float64(1e14), 'south': np.float64(1e14)},
                           authored_torque_n_m={'north': (1e24, 0., 0.)}, provenance='numpy scalars',
                           omitted=('gpe', 'slab_pull', 'mantle_traction', 'interface'))
        self.assertEqual(dict(scalar.basal_drag_pa_s_m)['north'], 1e14)

    def test_ill_conditioned_frame_refused(self):
        forcing = D.Forcing(basal_drag_pa_s_m={'north': 1e14, 'south': 1e-3}, provenance='test',
                            authored_torque_n_m={'north': (1e24, 0., 0.)},
                            omitted=('gpe', 'slab_pull', 'mantle_traction', 'interface'),
                            frame_id=self.network.sphere.frame_id)
        with self.assertRaises(D.DrivingRefused) as caught:
            D.balance(self.network, forcing)
        self.assertEqual(caught.exception.code, D.NULLSPACE)
        with self.assertRaises(D.DrivingRefused):
            D.Forcing(basal_drag_pa_s_m={'north': 1e14, 'south': 0.}, provenance='test',
                      omitted=('gpe', 'slab_pull', 'mantle_traction', 'authored_torque', 'interface'))

    def test_stale_and_unknown_columns_refused(self):
        network = X.hemispheres(32)
        support = P.trace_support(network)
        other = P.trace_support(X.hemispheres(64))
        port = X.single_layer_columns(network, support, X.degree_one)
        with self.assertRaises(P.PortRefused) as caught:
            D.balance(network, X.gpe_forcing(network), support=other, columns_port=port, datum=X.datum())
        self.assertEqual((caught.exception.code, caught.exception.detail), (P.STALE_IDENTITY, 'network_id'))
        same = X.single_layer_columns(network, support, X.degree_one)
        for change, code, detail in ((dict(datum_id='e'*64), P.STALE_IDENTITY, 'datum_id'),
                                     (dict(frame_id='another-frame'), P.STALE_IDENTITY, 'frame_id'),
                                     (dict(interval=(0, 1, -1e13, 0.), endpoint_s=0.), P.UNSUPPORTED, D.EVALUATION),
                                     (dict(interval=(0, 1, 0., 1e13), endpoint_s=1e13), P.UNSUPPORTED,
                                      D.EVALUATION)):
            values = dict((name, getattr(same.header, name)) for name in same.header.__dataclass_fields__)
            values.update(change)
            moved = P.columns_port(P.Header(**values), same.offsets, same.thickness_m, same.reference_density_kg_m3,
                                   same.alpha_per_k, same.bottom_temperature_k, same.top_temperature_k,
                                   sources=same.sources)
            with self.assertRaises(P.PortRefused) as caught:
                D.balance(network, X.gpe_forcing(network), support=support, columns_port=moved, datum=X.datum())
            self.assertEqual((caught.exception.code, caught.exception.detail), (code, detail), change)
        record = dict((name, getattr(same.header, name)) for name in same.header.__dataclass_fields__)
        record['support_id'] = 'f'*64
        foreign = P.columns_port(P.Header(**record), same.offsets, same.thickness_m, same.reference_density_kg_m3,
                                 same.alpha_per_k, same.bottom_temperature_k, same.top_temperature_k,
                                 sources=same.sources)
        with self.assertRaises(P.PortRefused) as caught:
            D.balance(network, X.gpe_forcing(network), support=support, columns_port=foreign, datum=X.datum())
        self.assertEqual(caught.exception.code, P.INCOMPATIBLE_SUPPORT)
        n = 2*support.edges
        unknown = np.zeros(n, bool)
        unknown[3] = True
        counts = np.where(unknown, 0, 1)
        offsets = np.r_[0, np.cumsum(counts)]
        m = int(offsets[-1])
        blind = P.columns_port(X.header('P1', network, support), offsets, np.full(m, 3e4), np.full(m, 2800.),
                               np.zeros(m), np.full(m, 1000.), np.full(m, 1000.), unknown=unknown,
                               sources=tuple('authored' for _ in range(n)))
        with self.assertRaises(P.PortRefused) as caught:
            D.balance(network, X.gpe_forcing(network), support=support, columns_port=blind, datum=X.datum())
        self.assertEqual(caught.exception.code, P.UNRESOLVED_COLUMN)


class I03Handoff(unittest.TestCase):
    """The D1-driven motion advances only inside I03's supported classes; outside them I03 refuses."""

    def test_driven_sector_plate_advances(self):
        network = F.three_plates()
        state = F.crust(network)
        forcing = X.authored_forcing(network, {'A': (0., 0., 1e25)}, slab_omitted=('boundary-m04',),
                                     omitted=('gpe', 'mantle_traction', 'interface'))
        probe = D.balance(network, forcing)
        duration = math.radians(1.)/abs(float(probe.omega('A')[2]))
        interval = (0, 1, state.time_s, state.time_s+duration)
        result = D.balance(network, forcing, parent_state_id=state.state_id, interval=interval)
        self.assertTrue(np.all(result.omega('B') == 0) and np.all(result.omega('C') == 0))
        omega = result.omega('A')
        self.assertLess(float(np.linalg.norm(omega[:2])), ALGEBRA*abs(float(omega[2])))
        header = P.Header('P5', state.state_id, interval, state.time_s, network.network_id,
                          P.plate_support_id(network.network_id, network.plate_ids), None, forcing.forcing_id,
                          network.sphere.frame_id, 'I04', D.ROUTE)
        port = D.motion_port(result, header)
        self.assertTrue(np.array_equal(port.omega('A'), omega))
        self.assertEqual(port.evaluation, D.EVALUATION)
        self.assertEqual(port.duration_s, duration)
        motion = T.Motion(start_step=0, end_step=1, rotations=D.stage_rotations(port),
                          supplies=F.both_sides('boundary-m02'), sinks=(F.sink('boundary-m04'),))
        step = T.advance(state, motion, end_time_s=state.time_s+duration)
        self.assertEqual(step.state.step, 1)
        fields = {name: getattr(header, name) for name in header.__dataclass_fields__}
        other = X.hemispheres(32)
        for change, code, detail in (
                (dict(network_id=other.network_id), P.STALE_IDENTITY, 'network_id'),
                (dict(frame_id='another-frame'), P.STALE_IDENTITY, 'frame_id'),
                (dict(parameter_id='d'*64), P.STALE_IDENTITY, 'parameter_id'),
                (dict(datum_id='e'*64), P.STALE_IDENTITY, 'datum_id'),
                (dict(parent_state_id='c'*64), P.STALE_IDENTITY, 'parent_state_id'),
                (dict(interval=(0, 1, state.time_s, state.time_s+2*duration)), P.STALE_IDENTITY, 'interval'),
                (dict(support_id=P.trace_support(network).support_id), P.STALE_IDENTITY, 'support_id')):
            with self.assertRaises(P.PortRefused) as caught:
                D.motion_port(result, P.Header(**dict(fields, **change)))
            self.assertEqual((caught.exception.code, caught.exception.detail), (code, detail), change)
        # A balance bound to no parent state and interval cannot issue P5.
        with self.assertRaises(P.PortRefused) as caught:
            D.motion_port(probe, header)
        self.assertEqual(caught.exception.code, P.MISSING_VALUE)
        # P5 can be issued only through motion_port: there is no public constructor to forge omega with.
        self.assertFalse(hasattr(P, 'plate_motion'))
        with self.assertRaises(TypeError):
            P.PlateMotion()

    def test_general_axis_drive_is_refused_by_i03(self):
        network = F.three_plates()
        state = F.crust(network)
        forcing = X.authored_forcing(network, {'A': (3e24, 0., 1e25)}, slab_omitted=('boundary-m04',),
                                     omitted=('gpe', 'mantle_traction', 'interface'))
        probe = D.balance(network, forcing)
        duration = math.radians(1.)/float(np.linalg.norm(probe.omega('A')))
        interval = (0, 1, state.time_s, state.time_s+duration)
        result = D.balance(network, forcing, parent_state_id=state.state_id, interval=interval)
        header = P.Header('P5', state.state_id, interval, state.time_s, network.network_id,
                          P.plate_support_id(network.network_id, network.plate_ids), None, forcing.forcing_id,
                          network.sphere.frame_id, 'I04', D.ROUTE)
        motion = T.Motion(start_step=0, end_step=1, rotations=D.stage_rotations(D.motion_port(result, header)),
                          supplies=F.both_sides('boundary-m02'), sinks=(F.sink('boundary-m04'),))
        with self.assertRaises(T.TransferRefused):
            T.advance(state, motion, end_time_s=state.time_s+duration)


if __name__ == '__main__':
    unittest.main()
