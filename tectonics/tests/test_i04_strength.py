"""I04.3 the material-dependent boundary response (D2 reduced belts) on the I03 network: the kernels, the line
operator, the belt geometry and its refusals, the belt balance and P6/P7. Criteria are tectonics/cases/
i04_controls_v1.json part_b, fixed before running. Executed in the scratch candidate on Windows/CPython 3.12.14
(candidate controls, not acceptance).
SPDX-License-Identifier: AGPL-3.0-only
"""
import hashlib
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i03_fixtures as F                                    # noqa: E402
import i04_fixtures as F4                                   # noqa: E402
import i04_strength_fixtures as Z                           # noqa: E402

from atlas_tectonics import _integration_weakening as W   # noqa: E402
from atlas_tectonics import damage_regularisation as DR   # noqa: E402
from atlas_tectonics import integration_driving as D      # noqa: E402
from atlas_tectonics import integration_feedback as B     # noqa: E402
from atlas_tectonics import integration_material as M     # noqa: E402
from atlas_tectonics import integration_ports as P        # noqa: E402
from atlas_tectonics import integration_properties as R   # noqa: E402
from atlas_tectonics import integration_strength as G     # noqa: E402


def strength_of(state, moving_state):
    """P2 at the state's own start (Part A evaluation)."""
    interval = Z.interval(state)
    header = B._header('P2', state.state_id, state, interval, interval[2], R.piece_support_id(state), F4.datum(),
                       moving_state.moving_id)
    return R.strength_port(moving_state, state, header, F4.datum(), healing_law_id=G.HEALING_NONE)


def start_balance(state, moving_state, inputs):
    return B.solve_at(state, moving_state, inputs, interval=Z.interval(state), parent_state_id=state.state_id,
                      evaluation='start')


class KernelReproduction(unittest.TestCase):
    """The oblique solve is the package's vectorised stress solve with the closure sign replaced by c = a/e."""

    @classmethod
    def setUpClass(cls):
        cls.prep = W.prepare(Z.LAYERS, 32, closure=W.LITHOSTATIC, gravity=9.81)
        cls.law = W.WeakeningLaw.from_spec(Z.WEAKENING['weakening'])
        cls.factors = cls.law.factors(np.full(cls.prep.size, 1.7))

    def test_pure_shear_is_the_package_solve_bit_for_bit(self):
        for rate in (1e-15, -1e-15, 3e-14, -3e-14):
            ref = W.stresses(self.prep, self.factors, rate)
            mine = G.oblique_stresses(self.prep, self.factors, abs(rate), math.copysign(1., rate))
            for key in ('stress', 'creep_rate', 'plastic_rate', 'yield_pa', 'tangent'):
                self.assertTrue(np.array_equal(ref[key], mine[key]), (rate, key))
            resp = W.respond(self.prep, self.law, np.full(self.prep.size, 1.7), rate)
            value, slope, _, _ = G.resultant(self.prep, self.factors, abs(rate), math.copysign(1., rate))
            self.assertEqual(2*value, abs(resp['force']))           # F = 2 sum w s (I01 pure shear)
            self.assertEqual(2*slope, resp['dforce'])

    def test_simple_shear_is_the_column_with_the_lithostatic_stress_as_mean_pressure(self):
        """c = 0: tau_zz = 0, so the mean pressure is sigma_v exactly (the kernel's supplied closure)."""
        supplied, top = [], 0.
        for layer in Z.LAYERS:
            bottom = top+layer['density_kg_m3']*9.81*layer['thickness_m']
            item = {k: v for k, v in layer.items() if k != 'density_kg_m3'}
            item['mean_pressure_pa'] = [top, bottom]
            supplied.append(item)
            top = bottom
        prep = W.prepare(supplied, 32, closure=W.SUPPLIED)
        for e in (1e-15, 3e-14):
            self.assertTrue(np.array_equal(G.oblique_stresses(self.prep, self.factors, e, 0.)['stress'],
                                           W.stresses(prep, self.factors, e)['stress']))

    def test_the_inverse_reproduces_the_rate(self):
        for c in (-.3, 0., .6, 1.):
            value = G.resultant(self.prep, self.factors, 2e-15, c)[0]
            e, back = G.invert_resultant(self.prep, self.factors, value, c)[:2]
            self.assertLessEqual(abs(back/value-1), G.TOL)
            self.assertLessEqual(abs(e/2e-15-1), 1e-9)

    def test_the_closure_sensitivity_is_the_derivative_of_the_resultant(self):
        """dS/dc at fixed e (ruling C1(1)) against a central difference of the same kernel (step 1e-6)."""
        for c, e in ((.3, 1e-14), (-.2, 1e-15), (.8, 3e-14)):
            _, _, exact, _ = G.resultant(self.prep, self.factors, e, c)
            plus = G.resultant(self.prep, self.factors, e, c+1e-6)[0]
            minus = G.resultant(self.prep, self.factors, e, c-1e-6)[0]
            self.assertLessEqual(abs(exact-(plus-minus)/2e-6), 1e-4*abs(exact), (c, e))

    def test_only_the_declared_yield_convention_is_admitted(self):
        material = Z.materials()[0][1]
        with self.assertRaises(G.StrengthRefused) as caught:
            G.BeltMaterial(material.cohesion_pa, material.friction_rad, material.plastic_viscosity_pa_s,
                           material.grain_m, material.weakening_interval, material.cohesion_factor,
                           material.friction_factor, 'atlas.mohr-coulomb-3d.v1', Z.SOURCE)
        self.assertEqual((caught.exception.code, caught.exception.detail), (G.UNSUPPORTED, 'yield_convention'))


class LineOperator(unittest.TestCase):
    """kappa_bar - ell^2 kappa_bar'' = kappa on the belt cells, zero flux at the closed belt sides."""

    def test_uniform_cells_reproduce_the_package_operator(self):
        rng = np.random.default_rng(7)
        for cells, ell in ((40, 2500.), (80, 5000.), (160, 5000.)):
            kappa = rng.uniform(0., 3., cells)
            mine = G.nonlocal_line(kappa, [1e5/cells]*cells, ell)
            with DR.PreparedDamageRegularisation(DR.DamageLengthScale('test', 1e5, ell, cells, 'test')) as plan:
                ref = plan.apply(kappa)
            s = (ell/(1e5/cells))**2
            self.assertLessEqual(float(np.max(np.abs(mine-ref))), 128*G.EPS*(1+4*s)*float(np.max(kappa)))

    def test_second_order_on_the_closures_manufactured_solution(self):
        """The existing D2 operator check (check_i01_closures: L = 1, ell = 0.1, 40/80/160 cells): ratio in
        (3.8, 4.2), a spatial second-order window, unchanged."""
        errors = []
        for cells in (40, 80, 160):
            x = (np.arange(cells)+.5)/cells
            kappa = 2+np.cos(2*np.pi*x)
            exact = 2+np.cos(2*np.pi*x)/(1+(0.2*np.pi)**2)
            errors.append(float(np.max(np.abs(G.nonlocal_line(kappa, [1./cells]*cells, .1)-exact))))
        for coarse, fine in zip(errors, errors[1:]):
            self.assertTrue(3.8 < coarse/fine < 4.2, errors)

    def test_uniform_history_stays_exactly_uniform_on_unequal_cells(self):
        value = G.nonlocal_line([1.25]*7, [3e3, 1e4, 7e2, 2e4, 5e3, 5e3, 9e3], 5e3)
        self.assertEqual(set(value.tolist()), {1.25})

    def test_raw_history_is_never_written_and_bad_input_refuses(self):
        kappa = np.array([0., 1., 2., .5])
        before = kappa.copy()
        G.nonlocal_line(kappa, [1., 2., 1., 3.], .5)
        self.assertTrue(np.array_equal(kappa, before))
        for bad in ([-1., 0., 0., 0.], [math.nan, 0., 0., 0.]):
            with self.assertRaises(G.StrengthRefused):
                G.nonlocal_line(bad, [1., 2., 1., 3.], .5)

    def test_a_depth_below_a_crossed_column_refuses(self):
        """Ruling B1(2): kappa_j(z) is undefined below cell j's base; no extrapolation."""
        tops, bottoms = np.array([0., 5e3]), np.array([5e3, 1e4])
        thin = (np.array([0.]), np.array([8e3]))
        columns = [(1e4, np.array([2e3, 9e3]), (tops, bottoms), np.array([1., 2.])),
                   (1e4, np.array([4e3]), thin, np.array([1.5]))]
        with self.assertRaises(G.StrengthRefused) as caught:
            G.nonlocal_points(columns, 5e3)
        self.assertEqual((caught.exception.code, caught.exception.detail), (G.UNRESOLVED_BELT, 'depth'))


class BeltGeometry(unittest.TestCase):
    """The normal line through each trace edge, walked through the faces it crosses."""

    @classmethod
    def setUpClass(cls):
        cls.network = Z.twin()
        cls.support = P.trace_support(cls.network)

    def test_the_cells_span_exactly_w_with_the_left_plate_first(self):
        for edge in range(self.support.edges):
            cells = G.belt_cells(self.network, self.support, edge, Z.WIDTH_M)
            self.assertLessEqual(abs(math.fsum(c.length_m for c in cells)-Z.WIDTH_M), 4*G.EPS*Z.WIDTH_M)
            plates = [self.network.face_plate(c.face_id) for c in cells]
            self.assertEqual(plates, ['north', 'south'])
            self.assertEqual([c.side for c in cells], ['left', 'right'])
        right = G.belt_cells(Z.one_sided(), P.trace_support(Z.one_sided()), 0, Z.WIDTH_M, 'right')
        self.assertTrue(all(c.side == 'right' and c.y0 >= 0 for c in right))
        self.assertLessEqual(abs(math.fsum(c.length_m for c in right)-Z.WIDTH_M), 4*G.EPS*Z.WIDTH_M)

    def test_a_line_that_re_crosses_a_trace_refuses(self):
        """Ruling B1(3): a belt wide enough to reach the next boundary refuses. Plate B is one 60 degree sector, so a
        10 000 km belt from one of its boundaries reaches the other (three_plates' 120 degree sectors are wider than
        the quarter-sphere limit)."""
        network = F.sector_world(*F.mesh('sector6'), plates=('A', 'B', 'A', 'A', 'A', 'A'))
        support = P.trace_support(network)
        for edge in range(support.edges):
            G.belt_cells(network, support, edge, Z.WIDTH_M)          # the declared width is admitted
        with self.assertRaises(G.StrengthRefused) as caught:
            for edge in range(support.edges):
                G.belt_cells(network, support, edge, 1e7)
        self.assertEqual((caught.exception.code, caught.exception.detail), (G.UNRESOLVED_BELT, 'trace'))


class BeltBalance(unittest.TestCase):
    """The belt term inside the D1 balance at one state (Part A explicit evaluation at the start)."""

    @classmethod
    def setUpClass(cls):
        cls.state, cls.moving = Z.twin_case()
        cls.result, cls.term, cls.strength, _ = start_balance(cls.state, cls.moving, Z.inputs())

    def test_newton_converges_with_the_derived_closure_and_a_monotone_tangent(self):
        belt = self.result.belt
        self.assertLessEqual(belt['newton_relative'], 1e-10)
        self.assertTrue(belt['omega_increment'] <= 1e-10 or belt['condition']*1e-10 <= 1e-9)
        self.assertGreaterEqual(belt['symmetric_min_eigenvalue'], 0.)
        power = self.result.power
        self.assertLessEqual(power['column_closure_relative'], power['closure_bound'])
        self.assertLessEqual(power['closure_bound'], 1e-10+belt['u_residual']+4e-11)

    def test_every_result_is_labelled_and_reports_its_ratios(self):
        belt = self.result.belt
        self.assertIn(G.THIN_SHEET, belt['labels'])
        self.assertNotIn(G.LODE, belt['labels'])                     # the transform is the c = 0 end member
        eq = belt['boundaries']['equator']
        self.assertEqual(eq['width_over_thickness'], Z.WIDTH_M/Z.THICKNESS_M)
        self.assertIsNotNone(eq['raw_kappa_width_2sigma_over_thickness'])     # the raw-history (inherited) width
        self.assertGreater(eq['increment_width_2sigma_m'], 0.)                  # the interval's localisation width
        self.assertEqual(eq['gpe_omission_ratio'], 0.)               # identical columns on both sides
        self.assertTrue(eq['resolved'])
        self.assertLessEqual(abs(eq['c_max']), G.S.ATTACHMENT_BAND_RAD)
        tolerance = max(self.term.tolerance.values())
        self.assertTrue(all(abs(b-1) <= self.term.tolerance[f] for f, b in self.term.coverage.items()), tolerance)

    def test_increments_stay_within_their_bound_and_vanish_outside_the_belt(self):
        dt = Z.INTERVAL_MYR*Z.MYR
        increments, energy, bound = self.term.products(dt)
        belt_faces = {c.cell.face_id for line in self.term.lines for c in line.cells}
        for index, (face, _) in enumerate(self.strength.pieces):
            if face in belt_faces:
                # deeper sublayers that flow by creep only do not weaken: positive somewhere, never negative
                self.assertTrue(np.all(increments[index] >= 0) and np.any(increments[index] > 0))
                self.assertTrue(np.all(increments[index] <= bound[index]*(1+G.TOL+4*G.EPS)))
            else:
                self.assertEqual(increments[index].tolist(), [0.]*len(increments[index]))
                self.assertEqual(energy[index][0].tolist(), [0.]*len(increments[index]))

    def test_a_zero_velocity_jump_is_the_exact_zero_limit(self):
        """Ruling B2(1): U = 0 gives f = 0, S = 0 and no increment, with no kernel call (c is never formed)."""
        line = self.term.lines[0]
        original = G.oblique_stresses

        def forbidden(*args, **kwargs):
            raise AssertionError('the kernel was called at U = 0')
        G.oblique_stresses = forbidden
        try:
            response = G.solve_line(line, np.zeros(3), history=self.term.histories[0])
        finally:
            G.oblique_stresses = original
        self.assertEqual((response['resultant'], response['power'], response['c']), (0., 0., None))
        self.assertEqual(response['traction'].tolist(), [0., 0., 0.])
        self.assertIsNone(G.traction_tangent(line, response))

    def test_the_increment_width_is_the_localisation_width(self):
        """On refined rows with the smooth inherited weakness, the reported increment width is the second moment of
        the depth-mean plastic rate (computed here independently) and differs from the raw-history width."""
        state, moving = Z.twin_case(rows=4, kappa_profile=True)
        result, term, _, _ = start_balance(state, moving, Z.inputs())
        eq = result.belt['boundaries']['equator']
        widths = []
        for line, response in zip(term.lines, term.last[1]):
            y = np.array([(c.cell.y0+c.cell.y1)/2 for c in line.cells])
            h = np.array([float(np.sum(c.prep.weight*p['plastic_rate'])/np.sum(c.prep.weight))*c.cell.length_m
                          for c, p in zip(line.cells, response['points'])])
            centre = float(np.sum(y*h)/np.sum(h))
            widths.append(2*math.sqrt(float(np.sum((y-centre)**2*h)/np.sum(h))))
        self.assertLessEqual(abs(eq['increment_width_2sigma_m']/max(widths)-1), 1e-12)
        raw = eq['raw_kappa_width_2sigma_over_thickness']*Z.THICKNESS_M
        self.assertGreater(abs(eq['increment_width_2sigma_m']-raw), .05*raw)

    def test_the_exact_tangent_matches_a_central_difference(self):
        """df/d(dv) including dS/dc (ruling C1(1)), on an oblique jump, against central differences (step 1e-6)."""
        line, history = self.term.lines[0], self.term.histories[0]
        dv = 2e-9*line.tangent+6e-10*line.normal
        exact = G.traction_tangent(line, G.solve_line(line, dv, history=history))
        numeric = np.zeros((3, 3))
        for k, direction in enumerate(np.eye(3)):
            step = 1e-6*float(np.linalg.norm(dv))*direction
            plus = G.solve_line(line, dv+step, history=history)['traction']
            minus = G.solve_line(line, dv-step, history=history)['traction']
            numeric[:, k] = (plus-minus)/(2*step[k])
        plane = np.array([line.normal, line.tangent])
        self.assertLessEqual(float(np.max(np.abs(plane @ (exact-numeric) @ plane.T))),
                             1e-4*float(np.max(np.abs(plane @ exact @ plane.T))))
        self.assertGreater(abs(exact[0, 1]-exact[1, 0])+abs(exact[0, 2]-exact[2, 0])+abs(exact[1, 2]-exact[2, 1]),
                           0.)                                       # not symmetric when dS/dc != 0

    def test_depth_resolution_changes_the_belt_force_by_at_most_0_003(self):
        """The I01 layered control's Gauss-order gate, on the belt resultant (part_b depth_control_orders)."""
        values = []
        for order in Z.INPUTS['depth_control_orders']:
            inputs = Z.inputs(declaration=Z.declaration(order=order))
            result, _, _, _ = start_balance(self.state, self.moving, inputs)
            values.append(result.belt['boundaries']['equator']['peak_resultant_n_m'])
        self.assertLessEqual(abs(values[0]-values[1])/values[1], Z.CASE['tolerances']['depth_order_change'])


class Refusals(unittest.TestCase):

    def test_a_broken_belt_cohort_refuses_and_no_latch_changes(self):
        """Ruling P4: BROKEN (zero cohesion, broken-surface sliding) is not an intact belt column."""
        state = Z.crust(Z.twin())
        records = tuple(Z.record(c.cohort_id, kappa=Z.KAPPA0, broken=c.cohort_id == 'inherited-south')
                        for c in state.material.cohorts)
        moving = M.declare_moving(state, records, enthalpy_reference_k=Z.T_REF)
        with self.assertRaises(G.StrengthRefused) as caught:
            start_balance(state, moving, Z.inputs())
        self.assertEqual((caught.exception.code, caught.exception.detail), (G.UNSUPPORTED, 'bond'))
        self.assertTrue(moving.cohort('inherited-south').bond.ever_broken)

    def test_a_coarse_belt_is_labelled_for_its_whole_result(self):
        """Ruling B3(3): with no rows at the belt's edge, each belt face extends far beyond w/2 (beta << 1)."""
        network = Z.twin(rows=0)                                     # no rows at +-w/2R
        state = Z.crust(network)
        moving = Z.moving(state)
        result, term, _, _ = start_balance(state, moving, Z.inputs())
        self.assertIn(G.COARSE, result.belt['labels'])
        self.assertFalse(result.belt['boundaries']['equator']['resolved'])
        self.assertLess(result.belt['boundaries']['equator']['beta_max'], .1)

    def test_a_fully_yielded_belt_reports_its_event_refusal_and_edits_no_network(self):
        """No event is admitted (ruling P4). With the single-layer column every point yields: the transform (|c|
        within the LODE label's band) suggests no event, an opening belt reports the CM-07 refusal and a closing one the
        CM-11 refusal; the balance returns motion only."""
        state, moving = Z.twin_case(single=True)
        result, term, _, _ = start_balance(state, moving, Z.inputs())
        self.assertTrue(all(np.all(p['plastic_rate'] > 0) for r in term.last[1] for p in r['points']))
        self.assertEqual(term.events(), {})
        line = term.lines[0]
        opening = G.solve_line(line, 5e-9*line.normal, history=term.histories[0])
        self.assertTrue(all(np.all(p['plastic_rate'] > 0) for p in opening['points']))
        self.assertEqual(G.event_diagnostics([line], [opening]), {'equator': [G.EVENT_REFUSALS['separation']]})
        self.assertEqual(state.network.network_id, Z.twin().network_id)

    def test_a_missed_face_and_an_overcounted_face_refuse(self):
        """Ruling B3(1): a belt-plate face within h of the trace that no line crosses refuses 'missed'; a face covered
        more than 1 + tol (here by a duplicated line) refuses 'beta'. Both on the cheap twin, by editing its lines."""
        state, moving = Z.twin_case()
        _, term, _, _ = start_balance(state, moving, Z.inputs())
        support = P.trace_support(state.network)
        line = term.lines[0]
        for side in ('left', 'right'):
            cut = G.Line(line.edge, line.boundary_id, line.belt, tuple(c for c in line.cells if c.cell.side != side),
                         line.midpoint, line.normal, line.tangent, line.length_m, line.unresolved_bonds)
            term.lines = (cut,)+term.lines[1:]
            with self.assertRaises(G.StrengthRefused) as caught:
                term._coverage(state.network, support)
            self.assertEqual((caught.exception.code, caught.exception.detail), (G.UNRESOLVED_BELT, 'missed'))
        term.lines = (line, line)+term.lines[1:]
        with self.assertRaises(G.StrengthRefused) as caught:
            term._coverage(state.network, support)
        self.assertEqual((caught.exception.code, caught.exception.detail), (G.UNRESOLVED_BELT, 'beta'))

    def test_the_belt_term_and_the_balance_bind_p2(self):
        """P2 must be on this state's piece support, from this moving state, and name the balance's parent and
        interval (rulings P6 and P4: no BROKEN-bond bypass by omitting the moving state)."""
        state, moving = Z.twin_case()
        sibling, sibling_moving = Z.twin_case(kappa_profile=True)        # the same network, other pieces
        support = P.trace_support(state.network)
        declaration, datum = Z.declaration(), F4.datum()
        with self.assertRaises(G.StrengthRefused) as caught:
            G.BeltTerm(state, support, strength_of(state, moving), declaration, datum, None)
        self.assertEqual((caught.exception.code, caught.exception.detail), (G.INVALID, 'moving'))
        with self.assertRaises(G.StrengthRefused) as caught:
            G.BeltTerm(state, support, strength_of(state, moving), declaration, datum,
                       Z.moving(state, kappa=2.))
        self.assertEqual((caught.exception.code, caught.exception.detail), (G.STALE, 'parameter_id'))
        self.assertEqual(sibling.network.network_id, state.network.network_id)
        with self.assertRaises(G.StrengthRefused) as caught:
            G.BeltTerm(sibling, support, strength_of(state, moving), declaration, datum, sibling_moving)
        self.assertEqual((caught.exception.code, caught.exception.detail), (G.STALE, 'support_id'))
        # At an endpoint (the coupled route) P2's header names S0; one naming another parent is refused by the balance.
        interval = Z.interval(state)
        end = B.coupled_interval(state, moving, Z.inputs(0.), interval=interval)
        endpoint, end_moving = end.step.state, end.moving
        stranger = hashlib.sha256(b'test: not the parent').hexdigest()
        header = B._header('P2', stranger, endpoint, interval, interval[3], R.piece_support_id(endpoint), datum,
                           end_moving.moving_id)
        foreign = R.strength_port(end_moving, endpoint, header, datum, healing_law_id=G.HEALING_NONE)
        support_end = P.trace_support(endpoint.network)

        def refusal(term, **changes):
            values = dict(parent_state_id=state.state_id, interval=interval, belt_term=term, evaluation='end',
                          endpoint_state_id=endpoint.state_id, datum=datum)
            values.update(changes)
            with self.assertRaises(P.PortRefused) as caught:
                D.balance(endpoint.network, Z.forcing(), **values)
            return caught.exception.code, caught.exception.detail
        term = G.BeltTerm(endpoint, support_end, foreign, declaration, datum, end_moving)
        self.assertEqual(refusal(term), (P.STALE_IDENTITY, 'parent_state_id'))
        earlier = (interval[0], interval[1], interval[2]-1e6, interval[3])      # same end, another start
        header = B._header('P2', state.state_id, endpoint, earlier, interval[3], R.piece_support_id(endpoint), datum,
                           end_moving.moving_id)
        shifted = R.strength_port(end_moving, endpoint, header, datum, healing_law_id=G.HEALING_NONE)
        term = G.BeltTerm(endpoint, support_end, shifted, declaration, datum, end_moving)
        self.assertEqual(refusal(term), (P.STALE_IDENTITY, 'interval'))
        header = B._header('P2', state.state_id, endpoint, interval, interval[3], R.piece_support_id(endpoint), datum,
                           end_moving.moving_id)
        genuine = R.strength_port(end_moving, endpoint, header, datum, healing_law_id=G.HEALING_NONE)
        term = G.BeltTerm(endpoint, support_end, genuine, declaration, datum, end_moving)
        self.assertEqual(refusal(term, datum=None), (P.MISSING_VALUE, 'datum_id'))


class Linear:
    """A synthetic belt term tau(omega) = -K omega reporting the tangent T (= K when exact), for the inner-solve
    branches only (rulings C1(2), C1(3), C2(4))."""

    def __init__(self, K, T=None):
        self.K, self.T = np.asarray(K, float), np.asarray(K if T is None else T, float)

    def evaluate(self, omega):
        w = np.asarray(omega, float).reshape(-1)
        return (-(self.K @ w)).reshape(-1, 3), self.T, dict(dissipation_w=0., column_work_w=0., u_residual=0.)


class InnerSolveRefusals(unittest.TestCase):
    """Each named refusal of the exact-tangent Newton solve fires, on synthetic belt terms with M = I."""

    def run_newton(self, term, start=None):
        return D._belt_newton(np.eye(3), np.array([1., 2., 3.]), term, 1, start)

    def test_a_monotone_non_symmetric_belt_converges(self):
        omega, relative, _, report = self.run_newton(Linear(np.array([[1., .5, 0.], [-.5, 1., 0.], [0., 0., 1.]])))
        self.assertLessEqual(relative, D.NEWTON_RELATIVE)
        self.assertGreater(report['symmetric_min_eigenvalue'], 0.)

    def test_each_inner_refusal_fires_by_name(self):
        cases = ((Linear(np.diag([-2., 0., 0.])), None, D.NON_MONOTONE, None),
                 (Linear(np.eye(3)*.5, T=-np.eye(3)*1.9), np.zeros(3), D.NONCONVERGED, 'halvings'),
                 (Linear(np.eye(3)*.5, T=-np.eye(3)*1.9), np.array([1., 2., 3.]), D.UNRESOLVED_INNER, None),
                 (Linear(np.diag([-1., 0., 0.])), np.array([1., 2., 3.]), D.NULLSPACE, None))   # M + J singular
        for term, start, code, detail in cases:
            with self.assertRaises(D.DrivingRefused) as caught:
                self.run_newton(term, start)
            self.assertEqual((caught.exception.code, caught.exception.detail), (code, detail))

    def test_a_tangent_that_is_not_representable_refuses_instead_of_halving(self):
        """Ruling C1(5): a trial whose belt tangent is not representable near U = 0 refuses by name; other kernel
        refusals on trials are halved."""
        class Tangent(Linear):
            calls = 0

            def evaluate(self, omega):
                self.calls += 1
                if self.calls > 1:
                    raise G.StrengthRefused('the belt tangent is not representable near U = 0', G.NONCONVERGED,
                                            'tangent')
                return Linear.evaluate(self, omega)
        with self.assertRaises(G.StrengthRefused) as caught:
            self.run_newton(Tangent(np.eye(3)), np.zeros(3))
        self.assertEqual(caught.exception.detail, 'tangent')


if __name__ == '__main__':
    unittest.main()
