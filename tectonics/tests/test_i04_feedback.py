"""I04.4 the first property/motion feedback: the P5 -> I03 binding, the coupled endpoint fixed point, its ports (P5,
P6, P7, P9), the zero and refusal branches, the P9 swap algebra, an oblique balance, the fv-cell-mean obligation and
D1 provenance on an I02 ledger. Criteria are tectonics/cases/i04_controls_v1.json part_b, fixed before running.
Executed in the scratch candidate on Windows/CPython 3.12.14 (candidate controls, not acceptance).
SPDX-License-Identifier: AGPL-3.0-only
"""
import copy
from dataclasses import fields, replace
import gc
import hashlib
import math
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import weakref

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i02_workflow_fixtures as F2                          # noqa: E402
import i03_fixtures as F                                    # noqa: E402
import i04_fixtures as F4                                   # noqa: E402
import i04_strength_fixtures as Z                           # noqa: E402

from atlas_tectonics import integration_clock as K        # noqa: E402
from atlas_tectonics import integration_driving as D      # noqa: E402
from atlas_tectonics import integration_feedback as B     # noqa: E402
from atlas_tectonics import integration_ledger as L       # noqa: E402
from atlas_tectonics import integration_material as M     # noqa: E402
from atlas_tectonics import integration_ports as P        # noqa: E402
from atlas_tectonics import integration_properties as R   # noqa: E402
from atlas_tectonics import integration_strength as G     # noqa: E402
from atlas_tectonics import integration_transfer as T     # noqa: E402

TORQUE = 3e27      # N m about the world axis on the north plate (authored test input)
ALGEBRA = 1e-11    # the P9 swap's algebra_relative (part_b tolerances)


def part_a_motion(state, years_myr=.1, torque=TORQUE):
    """A Part A P5 (explicit start-of-interval D1 without belts) for the twin world: interface declared omitted."""
    forcing = D.Forcing((('north', Z.DRAG), ('south', Z.DRAG)), Z.SOURCE,
                        authored_torque_n_m=(('north', (0., 0., torque)),),
                        omitted=('gpe', 'slab_pull', 'mantle_traction', 'interface'), frame_id=F.FRAME)
    interval = Z.interval(state, years_myr)
    result = D.balance(state.network, forcing, parent_state_id=state.state_id, interval=interval)
    header = P.Header('P5', state.state_id, interval, interval[2], result.network_id,
                      P.plate_support_id(result.network_id, result.plate_ids), None, result.forcing_id,
                      result.frame_id, 'I04 (test)', 'tests/test_i04_feedback.py')
    return D.motion_port(result, header)


def relative(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    scale = max(float(np.max(np.abs(a))), float(np.max(np.abs(b))))
    return 0. if scale == 0. else float(np.max(np.abs(a-b)))/scale


class MotionBinding(unittest.TestCase):
    """Port record section 4 and ruling P2: whoever advances I03 from P5 checks the parent state, the start step and
    time, the end time, the frame, plates, network and per-plate support, and takes the rotations only from P5."""

    @classmethod
    def setUpClass(cls):
        cls.state = Z.crust(Z.twin())

    def test_advance_from_a_p5_value_matches_the_hand_built_motion(self):
        motion = part_a_motion(self.state)
        step = B.advance_from_motion(self.state, motion, end_time_s=motion.header.interval[3])
        interval = motion.header.interval
        hand = T.advance(self.state, T.Motion(interval[0], interval[1], D.stage_rotations(motion)),
                         end_time_s=interval[3])
        self.assertEqual(step.state.state_id, hand.state.state_id)
        self.assertEqual(step.motion.motion_id, hand.motion.motion_id)

    def test_each_binding_refuses_by_name(self):
        motion = part_a_motion(self.state)
        end = motion.header.interval[3]
        other = Z.crust(Z.twin(rows=2))
        with self.assertRaises(B.FeedbackRefused) as caught:                    # another parent state
            B.advance_from_motion(other, motion, end_time_s=end)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'parent_state_id'))
        with self.assertRaises(B.FeedbackRefused) as caught:                    # the same rotations, longer
            B.advance_from_motion(self.state, motion, end_time_s=end+Z.MYR)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'end_time_s'))
        moved = B.advance_from_motion(self.state, motion, end_time_s=end).state
        later = part_a_motion(moved)
        with self.assertRaises(B.FeedbackRefused) as caught:                    # a P5 for the next step
            B.advance_from_motion(self.state, later, end_time_s=later.header.interval[3])
        self.assertEqual(caught.exception.detail, 'parent_state_id')
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.advance_from_motion(self.state, 'not a P5', end_time_s=end)
        self.assertEqual(caught.exception.code, B.MISSING)

    def test_the_template_holds_only_supplies_sinks_and_a_mesh(self):
        """Ruling P2 (d) and (f): rotations, events, regional returns, junction paths and history splits refuse by
        name, in the helper and in the declared Inputs."""
        motion = part_a_motion(self.state)
        end = motion.header.interval[3]
        for name in sorted(B.REFUSED_TEMPLATE):
            with self.assertRaises(B.FeedbackRefused) as caught:
                B.advance_from_motion(self.state, motion, {name: ()}, end_time_s=end)
            self.assertEqual((caught.exception.code, caught.exception.detail), (B.UNSUPPORTED, name))
            with self.assertRaises(B.FeedbackRefused) as caught:
                Z.inputs(template=((name, ()),))
            self.assertEqual((caught.exception.code, caught.exception.detail), (B.UNSUPPORTED, name))
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.advance_from_motion(self.state, motion, dict(gravity=()), end_time_s=end)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.UNSUPPORTED, 'gravity'))
        with self.assertRaises(B.FeedbackRefused) as caught:      # the coupled route: a mesh is not replayable in v1
            Z.inputs(template=(('mesh', ()),))
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.UNSUPPORTED, 'mesh'))

    def test_the_twin_world_advances_several_intervals_without_mixing(self):
        """The primary fixture slides its transform under D1 output for three intervals, one piece per face."""
        state = self.state
        for _ in range(3):
            motion = part_a_motion(state)
            state = B.advance_from_motion(state, motion, end_time_s=motion.header.interval[3]).state
        counts = {}
        for piece in state.material.pieces():
            counts[piece.face_id] = counts.get(piece.face_id, 0)+1
        self.assertEqual(max(counts.values()), 1)
        self.assertEqual(state.network.step, 3)


class CoupledInterval(unittest.TestCase):
    """One coupled interval on the twin transform with the symmetric belt (single-interval controls keep 'both')."""

    @classmethod
    def setUpClass(cls):
        cls.state, cls.moving = Z.twin_case()
        cls.inputs = Z.inputs()
        cls.interval = Z.interval(cls.state)
        cls.result = B.coupled_interval(cls.state, cls.moving, cls.inputs, interval=cls.interval)

    def test_the_coupled_p5_names_the_parent_and_the_endpoint_balance(self):
        """Ruling P6: parent S0, S0's network and per-plate support, the commit interval, endpoint at its end,
        parameter_id = digest(forcing, declaration); value omega^k with the endpoint balance and its residual."""
        port, network = self.result.motion_port, self.state.network
        header = port.header
        self.assertEqual((header.parent_state_id, header.network_id, header.support_id),
                         (self.state.state_id, network.network_id,
                          P.plate_support_id(network.network_id, network.plate_ids)))
        self.assertEqual((tuple(header.interval), header.endpoint_s), (self.interval, self.interval[3]))
        self.assertEqual(header.parameter_id, self.inputs.parameter_id)
        self.assertEqual((port.evaluation, port.balance_id), (D.EVALUATION_ENDPOINT, self.result.balance.balance_id))
        self.assertLessEqual(port.coupling_residual, B.OUTER_RELATIVE)
        self.assertEqual(port.coupling_residual, relative(self.result.balance.omega_rad_s, port.omega_rad_s))
        balance = self.result.balance
        self.assertEqual((balance.evaluation, balance.parent_state_id, balance.endpoint_state_id),
                         (D.EVALUATION_ENDPOINT, self.state.state_id, self.result.step.state.state_id))

    def test_the_committed_increments_are_bounded_and_carried_by_p6(self):
        """D-P1 bound per piece and sublayer (ruling B5(1)), the applied increments are P6's, and the P6/P7 headers
        lie on the endpoint's piece support."""
        p6 = self.result.increment_port
        values, bound = np.asarray(p6.kappa_increment), np.asarray(p6.bound)
        self.assertTrue(np.all(values >= 0) and np.any(values > 0))
        self.assertTrue(np.all(values <= bound*(1+G.TOL+4*G.EPS)))
        issued = {piece: tuple(values) for piece, values in p6.increments() if any(values)}
        self.assertEqual(issued, {piece: tuple(values) for piece, values in self.result.advance.increments
                                  if any(values)})
        endpoint = self.result.step.state
        for port in (p6, self.result.dissipation_port):
            self.assertEqual(port.header.support_id, R.piece_support_id(endpoint))
            self.assertEqual(port.header.parent_state_id, self.state.state_id)
        report = self.result.report
        self.assertEqual(report['pieces_per_face']['max'], 1)
        for item in report['history']:
            self.assertIn('distinct', item['increments'])
            self.assertIn('sub_cohorts', item['increments'])

    def test_p7_records_energy_without_heat(self):
        p7 = self.result.dissipation_port
        self.assertEqual(p7.heat_rule, P.HEAT_NOT_CONVERTED)
        creep, plastic = np.asarray(p7.creep_energy_j_m3), np.asarray(p7.plastic_energy_j_m3)
        self.assertTrue(np.all(creep >= 0) and np.all(plastic >= 0) and np.any(plastic > 0))
        driving = self.result.advance.declared_driving()
        self.assertIn(G.HEAT_OMITTED, driving['labels'])
        self.assertGreater(driving['heat_omission']['interval_bound_k'], 0.)
        self.assertEqual(driving['heat_omission']['cumulative_bound_k'],
                         driving['heat_omission']['interval_bound_k'])

    def test_p9_carries_the_belt_reaction_exactly(self):
        """Ruling P3: the P9 power is the belt dissipation, its torques are the belt term at omega*, and the belt
        dissipation is -sum omega*.tau to ALGEBRA."""
        p9, balance = self.result.reaction_port, self.result.balance
        belt = balance.terms['belt']
        self.assertLessEqual(abs(p9.power_w()/balance.belt['dissipation_w']-1), ALGEBRA)
        network = self.result.step.state.network
        support = P.trace_support(network)
        middle = np.array([(support.start[e]+support.end[e])/np.linalg.norm(support.start[e]+support.end[e])
                           for e in range(support.edges)])
        torques = p9.torques(balance.plate_ids, support.plates, float(network.sphere.radius_m), middle)
        self.assertLessEqual(relative(torques, belt), ALGEBRA)
        self.assertLessEqual(abs(-math.fsum(float(x) for x in (balance.omega_rad_s*belt).reshape(-1))
                                 / balance.belt['dissipation_w']-1), ALGEBRA)

    def test_the_p9_swap_reproduces_the_belt_balance_algebraically(self):
        """Ruling P3: replacing the belt by its own P9 torques as regional reactions gives omega_swap = omega* -
        M^-1 r(omega*) to ALGEBRA; the regional-reaction work is on its own power line (no sign is imposed)."""
        balance = self.result.balance
        network = self.result.step.state.network
        belt = balance.terms['belt']
        reactions = (('equator', (tuple(float(x) for x in belt[0]), tuple(float(x) for x in belt[1]))),)
        forcing = Z.forcing(belts=(), regional_reactions=reactions)
        swap = D.balance(network, forcing)
        matrix = D.prepare(network, forcing).matrix
        omega = balance.omega_rad_s.reshape(-1)
        known = sum(v for k, v in balance.terms.items() if k != 'belt').reshape(-1)
        residual = matrix @ omega-known-belt.reshape(-1)
        self.assertLessEqual(relative(swap.omega_rad_s.reshape(-1), omega-np.linalg.solve(matrix, residual)), ALGEBRA)
        self.assertLess(swap.power['regional_reaction_w'], 0.)
        self.assertLessEqual(abs(-swap.power['regional_reaction_w']/balance.belt['dissipation_w']-1), 1e-8)

    def test_p7_closes_on_the_belt_work_and_the_heat_bound_is_per_piece(self):
        """Ruling C2(3): the P7 energies equal the belt's column work over dt within the derived bound; ruling P4: the
        omitted heat's pointwise bound is reported per piece, its maximum is the interval bound, and it is labelled."""
        report = self.result.report
        belt = self.result.balance.belt
        self.assertLessEqual(report['p7_closure_relative'], belt['u_residual']+D.PARTITION)
        heat = self.result.advance.declared_driving()['heat_omission']
        self.assertTrue(heat['per_piece_k'])
        self.assertEqual(max(row[2] for row in heat['per_piece_k']), heat['interval_bound_k'])
        self.assertEqual(heat['label'], G.HEAT_OMITTED)
        self.assertIsNone(heat['lateral_allowance_k'])                 # no lateral omission declared here
        # Independently of the gate: sum over P7 rows of (creep + plastic) x the P2 thickness x the piece area, against
        # the column work over dt; and plastic energy exactly where the P6 increment is (both bottom up, P2 order).
        p6, p7 = self.result.increment_port, self.result.dissipation_port
        endpoint = self.result.step.state
        interval = self.interval
        header = B._header('P2', self.state.state_id, endpoint, interval, interval[3], R.piece_support_id(endpoint),
                           F4.datum(), self.result.moving.moving_id)
        strength = R.strength_port(self.result.moving, endpoint, header, F4.datum(), healing_law_id=G.HEALING_NONE)
        areas = [float(p.area_m2) for p in endpoint.material.pieces()]
        offsets = np.asarray(p7.offsets)
        energy = (np.asarray(p7.creep_energy_j_m3)+np.asarray(p7.plastic_energy_j_m3))*np.asarray(strength.thickness_m)
        total = math.fsum(math.fsum(energy[int(offsets[i]):int(offsets[i+1])])*areas[i] for i in range(len(areas)))
        work = belt['column_work_w']*(interval[3]-interval[2])
        self.assertLessEqual(abs(total/work-1), belt['u_residual']+D.PARTITION)
        self.assertEqual((np.asarray(p7.plastic_energy_j_m3) > 0).tolist(),
                         (np.asarray(p6.kappa_increment) > 0).tolist())

    def test_the_labels_are_carried_by_the_driving_record(self):
        driving = self.result.advance.declared_driving()
        self.assertIsNone(driving['parent_driving_sha256'])             # a first interval
        self.assertIn(G.THIN_SHEET, driving['labels'])
        self.assertNotIn(G.ONE_SIDED, driving['labels'])
        # c = 0 contributes zero (ruling B4): here c is zero to rounding (inside the 64 eps band) and e dt < 1
        self.assertEqual(set(driving['normal_strain']), {'equator'})
        self.assertLess(driving['normal_strain']['equator'], 64*G.EPS)
        self.assertEqual(driving['coupling']['iterations'], len(driving['coupling']['history']))
        text = repr(driving)
        for word in ('perf_counter', 'seconds', 'wall', 'elapsed'):       # no wall-clock or cost data (ruling P1(4))
            self.assertNotIn(word, text)


class ZeroAndRefusals(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.state, cls.moving = Z.twin_case()
        cls.interval = Z.interval(cls.state)

    def test_zero_forcing_is_exactly_at_rest(self):
        """Ruling C1(5): zero forcing gives omega = 0, no increment, zero dissipation and zero P9, exactly."""
        zero = B.coupled_interval(self.state, self.moving, Z.inputs(0.), interval=self.interval)
        self.assertEqual(zero.motion_port.omega_rad_s.tolist(), [[0.]*3]*2)
        self.assertEqual(zero.advance.increments, ())
        self.assertEqual(zero.balance.belt['dissipation_w'], 0.)
        self.assertEqual(zero.reaction_port.power_w(), 0.)
        self.assertFalse(np.any(zero.increment_port.kappa_increment))
        self.assertFalse(np.any(zero.dissipation_port.plastic_energy_j_m3))
        self.assertEqual(zero.report['iterations'], 1)

    def test_the_cap_is_an_integer_that_can_only_be_lowered(self):
        for cap in (0, B.OUTER_ITERATIONS+1, 2.):
            with self.assertRaises(B.FeedbackRefused) as caught:
                B.coupled_interval(self.state, self.moving, Z.inputs(), interval=self.interval, outer_iterations=cap)
            self.assertEqual((caught.exception.code, caught.exception.detail), (B.UNSUPPORTED, 'cap'))

    def test_the_forcing_and_declaration_must_name_the_same_belts(self):
        with self.assertRaises(B.FeedbackRefused) as caught:
            Z.inputs(forcing=Z.forcing(belts=(), omitted=('gpe', 'slab_pull', 'mantle_traction', 'interface')))
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'belts'))

    def test_the_cumulative_strain_guard_and_the_parent_binding(self):
        """Ruling B4: E_b is the parent's value plus this interval's (accumulate_strain is the path _finish uses), and a
        total above the unchanged 0.05 guard refuses. The parent comes only from an object bound to this very state."""
        self.assertEqual(B.accumulate_strain({'equator': .049}, {'equator': .0009}), {'equator': .049+.0009})
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.accumulate_strain({'equator': .049}, {'equator': .002})
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.UNSUPPORTED, 'small strain'))
        with self.assertRaises(B.FeedbackRefused) as caught:           # a caller's dict is never a parent
            B.coupled_interval(self.state, self.moving, Z.inputs(0.), interval=self.interval,
                               parent=dict(schema=B.SCHEMA, endpoint_state_id=self.state.state_id))
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.UNSUPPORTED, 'parent'))
        zero = B.coupled_interval(self.state, self.moving, Z.inputs(0.), interval=self.interval)
        with self.assertRaises(B.FeedbackRefused) as caught:           # it ends at another state
            B.coupled_interval(self.state, self.moving, Z.inputs(0.), interval=self.interval, parent=zero)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'parent'))

    def test_the_outer_refusals_fire_by_name(self):
        """Ruling C2(5): a change that grows twice running after the second iterate refuses; a changed endpoint
        support between iterates refuses (increments are never remapped)."""
        growing = iter([1e-3, 2e-3, 3e-3, 4e-3, 5e-3])
        original = B._omega_relative
        B._omega_relative = lambda new, old: next(growing)
        try:
            with self.assertRaises(B.FeedbackRefused) as caught:
                B.coupled_interval(self.state, self.moving, Z.inputs(0.), interval=self.interval)
        finally:
            B._omega_relative = original
        self.assertEqual(caught.exception.code, B.NONCONVERGED)
        self.assertIn('stopped contracting', str(caught.exception))
        inputs = Z.inputs(0.)
        start, _, _, _ = B.solve_at(self.state, self.moving, inputs, interval=self.interval,
                                    parent_state_id=self.state.state_id, evaluation='start')
        trial = B._motion_port(self.state, inputs, self.interval, start.omega_rad_s, start.balance_id, None)
        with self.assertRaises(B.FeedbackRefused) as caught:
            B._advance(self.state, self.moving, trial, inputs, {('nowhere', 'none'): (.1,)}, self.interval)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.UNRESOLVED_SUPPORT, 'pieces'))


class ObliqueBalance(unittest.TestCase):
    """Ruling C1(3): a tilted relative pole makes the equatorial belt oblique (0 < |c| < 1); exact-tangent Newton
    converges, the tangent is non-symmetric and its symmetric part is positive definite (monotone)."""

    def test_a_tilted_pole_converges_with_a_non_symmetric_tangent(self):
        state, moving = Z.twin_case()
        tilt = math.radians(10.)
        inputs = Z.inputs(forcing=Z.forcing(axis=(math.sin(tilt), 0., math.cos(tilt))))
        result, term, _, _ = B.solve_at(state, moving, inputs, interval=Z.interval(state),
                                        parent_state_id=state.state_id, evaluation='start')
        belt = result.belt
        self.assertLessEqual(belt['newton_relative'], D.NEWTON_RELATIVE)
        self.assertIn(G.LODE, belt['labels'])
        eq = belt['boundaries']['equator']
        self.assertTrue(-1 < eq['c_min'] < 0 < eq['c_max'] < 1)
        _, tangent, _ = term.evaluate(result.omega_rad_s)
        self.assertGreater(relative(tangent, tangent.T), 1e-3)
        self.assertGreater(belt['symmetric_min_eigenvalue'], 0.)
        self.assertLessEqual(result.power['column_closure_relative'], result.power['closure_bound'])
        # B4 on an oblique belt: E_b = max_k |c e_k| dt, nonzero here (the transform adds only rounding)
        dt = Z.INTERVAL_MYR*Z.MYR
        expected = max(abs(r['c'])*max(r['rates'])*dt for r in term.last[1])
        self.assertGreater(expected, 0.)
        self.assertLessEqual(abs(term.normal_strain(dt)['equator']/expected-1), 1e-12)


class CellMeanObligation(unittest.TestCase):
    """Ruling P7(2): one coupled-balance evaluation with GPE on the I05a fv-cell-mean fixture (the 's00-merged' face
    beside the B|C boundary) records the trace indices of its cell-mean points and closes. The belt-free balance is
    evaluated: the obligation is the P1 representation inside the balance identity."""

    def test_an_endpoint_balance_with_gpe_records_its_cell_mean_points(self):
        import test_i05_properties as Q
        after, sphere = Q.PropertyPorts('test_a_mixed_face_of_identical_pieces_is_the_single_piece_column').mixed()
        interval = (sphere.network.step-1, sphere.network.step, F.START, sphere.network.time_s)
        support = P.trace_support(sphere.network)
        datum = F4.datum()
        forcing = F4.gpe_forcing(sphere.network)
        parent = hashlib.sha256(b'test: the interval parent S0').hexdigest()     # names S0; not replayed here
        header = B._header('P1', parent, sphere, interval, interval[3], support.support_id, datum, after.moving_id)
        columns = R.moving_columns(after, sphere, support, header, datum)
        result = D.balance(sphere.network, forcing, support=support, columns_port=columns, datum=datum,
                           parent_state_id=parent, interval=interval, evaluation='end',
                           endpoint_state_id=sphere.state_id)
        expected = tuple(i for i, entry in enumerate(columns.representation) if entry is not None)
        self.assertTrue(expected)
        self.assertEqual(result.cell_mean_points, expected)
        self.assertEqual(result.record()['cell_mean_points'], list(expected))
        self.assertEqual(result.record()['columns_id'], columns.port_id)
        self.assertLessEqual(result.power['closure_relative'], 1e-11)


class IssuedResultProvenance(unittest.TestCase):
    """The public result boundary: only unchanged, actually issued results can write or supply a parent record.
    Zero forcing keeps these provenance controls independent of nonlinear convergence cost."""

    @classmethod
    def setUpClass(cls):
        cls.prepared = F2.preparation()
        cls.sphere = Z.crust(Z.one_sided(epoch=F2.EPOCH, time_s=F2.START))
        cls.moving = Z.moving(cls.sphere)
        cls.inputs = Z.inputs(0., declaration=Z.side_declaration('right'))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)/'ledger.sqlite'
        self.store = F2.store(self.path)
        self.addCleanup(self.store.close)
        self.ledger, _ = L.Ledger.create(self.store, F2.root(8, prepared=self.prepared),
                                        sphere=self.sphere, moving=self.moving)
        self.result = B.step(self.ledger, self.inputs)

    def refused_before_use(self, candidate):
        before = (self.ledger.head().key, len(self.ledger.chain()), hashlib.sha256(self.path.read_bytes()).hexdigest())
        with patch.object(K.Clock, 'advance', side_effect=AssertionError('refusal must precede the writer')):
            with self.assertRaises(B.FeedbackRefused) as caught:
                B.commit(self.ledger, candidate)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'coupled'))
        self.assertEqual((self.ledger.head().key, len(self.ledger.chain()),
                          hashlib.sha256(self.path.read_bytes()).hexdigest()), before)
        endpoint = self.result.step.state
        with patch.object(B, 'solve_at', side_effect=AssertionError('refusal must precede the solver')):
            with self.assertRaises(B.FeedbackRefused) as caught:
                B.coupled_interval(endpoint, self.result.moving, self.inputs,
                                   interval=Z.interval(endpoint), parent=candidate)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'parent'))

    def test_copies_and_hand_construction_do_not_inherit_issuance(self):
        values = {f.name: getattr(self.result, f.name) for f in fields(B.CoupledInterval)}
        for candidate in (replace(self.result), copy.copy(self.result), B.CoupledInterval(**values)):
            with self.subTest(candidate=id(candidate)):
                self.refused_before_use(candidate)

    def test_replaced_and_hand_built_driving_record_refuse_before_a_write(self):
        driving = self.result.advance.declared_driving()
        driving['labels'] = []
        driving['heat_omission']['cumulative_bound_k'] = 123.
        original = self.result.advance
        forged = M.MovingAdvance(original.start_step, original.end_step, births=original.births,
                                 conduction=original.conduction, increments=original.increments, driving=driving)
        values = {f.name: getattr(self.result, f.name) for f in fields(B.CoupledInterval)}
        values['advance'] = forged
        for candidate in (replace(self.result, advance=forged), B.CoupledInterval(**values)):
            self.refused_before_use(candidate)

    def test_nested_public_report_mutation_refuses(self):
        self.result.report['history'][0]['omega_relative'] = 123.
        self.refused_before_use(self.result)

    def test_nested_public_balance_mutation_refuses(self):
        self.result.balance.belt['boundaries']['equator']['column_work_w'] = 123.
        self.refused_before_use(self.result)

    def test_malformed_public_report_refuses_by_name(self):
        self.result.report['history'].append(self.result.report)
        self.refused_before_use(self.result)

    def test_honest_commit_parent_continuation_and_cold_reopen(self):
        first = self.result
        with patch.object(B, 'solve_at', side_effect=AssertionError('commit must not re-solve')):
            produced = B.commit(self.ledger, first, deadline=time.perf_counter()+60.)
        self.assertTrue(B._trusted(produced))
        self.assertEqual(produced.status, B.PRODUCED)
        second = B.step(self.ledger, self.inputs, verified=produced)
        direct = B.coupled_interval(first.step.state, first.moving, self.inputs,
                                    interval=B.next_interval(self.ledger), parent=first)
        self.assertEqual(second.advance.record(), direct.advance.record())
        self.assertEqual(second.advance.declared_driving()['parent_driving_sha256'], B._digest(produced.record))
        final = B.commit(self.ledger, second, deadline=time.perf_counter()+60.)
        ledger_id = self.ledger.ledger_id
        self.store.close()
        with F2.store(self.path) as store:
            reopened = L.Ledger.open(store, ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
            replayed = B.verify_driving(reopened, reopened.head())
            self.assertEqual(replayed.status, B.REPLAYED)
            self.assertEqual(replayed.text, final.text)
            self.assertTrue(B._trusted(replayed))

    def test_released_results_are_not_retained_by_the_registry(self):
        result = self.result
        reference = weakref.ref(result)
        count = len(B._COUPLED_ISSUED)
        self.assertIn(result, B._COUPLED_ISSUED)
        self.result = None
        del result
        gc.collect()
        self.assertIsNone(reference())
        self.assertLess(len(B._COUPLED_ISSUED), count)


class Provenance(unittest.TestCase):
    """Rulings P1 and P2(e) on an I02 ledger: the coupled route reads and replays the parent commit's record itself
    (``step``), binds the interval and the inheritance before writing (``commit``, and I05 at every commit), and
    ``verify_driving`` solves each committed interval again from its verified parent, comparing every field. Forged
    inherited fields, a dropped inheritance and a malformed record refuse by name; a refused interval commits nothing.
    Multi-interval chains use the one-sided belt on the carrier (mid-build ruling, 4 October 2026)."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.directory.name)
        cls.prepared = F2.preparation()
        cls.inputs = Z.inputs(declaration=Z.side_declaration('right'))
        cls.stores = []
        cls.first_ledger = cls.make('chain')
        cls.first = B.step(cls.first_ledger, cls.inputs)                 # a first interval: no parent record
        cls.first_verified = B.commit(cls.first_ledger, cls.first, deadline=time.perf_counter()+600.)

    @classmethod
    def tearDownClass(cls):
        for store in cls.stores:
            store.close()
        cls.directory.cleanup()

    @classmethod
    def make(cls, name):
        network = Z.one_sided(side='right', epoch=F2.EPOCH, time_s=F2.START)
        sphere = Z.crust(network)
        store = F2.store(cls.folder/name/'ledger.sqlite')
        cls.stores.append(store)
        ledger, _ = L.Ledger.create(store, F2.root(8, prepared=cls.prepared), sphere=sphere, moving=Z.moving(sphere))
        return ledger

    @staticmethod
    def plain(ledger, coupled, driving=None):
        """The plain ledger path (no I04 checks before the write), with the driving record replaced if given."""
        advance = coupled.advance if driving is None else M.MovingAdvance(
            coupled.advance.start_step, coupled.advance.end_step, births=coupled.advance.births,
            conduction=coupled.advance.conduction, increments=coupled.advance.increments, driving=driving)
        return K.Clock(ledger).advance(steps=1, transfers=(coupled.motion, advance), deadline=time.perf_counter()+600.)

    def test_a_chain_inherits_from_its_parent_commit_and_replays(self):
        ledger = self.first_ledger
        self.assertEqual(self.first_verified.status, B.PRODUCED)
        first = self.first.advance.declared_driving()
        second = B.step(ledger, self.inputs, verified=self.first_verified)
        record = second.advance.declared_driving()
        self.assertEqual(record['parent_driving_sha256'], B._digest(first))
        self.assertEqual(record['heat_omission']['cumulative_bound_k'],
                         first['heat_omission']['cumulative_bound_k']+record['heat_omission']['interval_bound_k'])
        self.assertTrue(set(first['labels']) <= set(record['labels']))
        self.assertIn(G.ONE_SIDED, record['labels'])
        self.assertGreaterEqual(record['normal_strain']['equator'], first['normal_strain']['equator'])  # cumulative
        produced = B.commit(ledger, second, deadline=time.perf_counter()+600.)
        head = ledger.head()
        self.assertEqual(B.find_driving(ledger, head)['status'], B.RECORDED)
        cache = {}
        replayed = B.verify_driving(ledger, head, cache=cache)         # replays both intervals from the root
        self.assertEqual((replayed.status, replayed.text), (B.REPLAYED, produced.text))
        self.assertEqual(len(cache), 2)
        B.bind_commit_interval(head.interval, second.motion_port)
        root = ledger.chain()[0]
        self.assertIsNone(B.find_driving(ledger, root))
        self.assertEqual(B.omission_labels(ledger, root), ())
        self.assertEqual(B.omission_labels(ledger, head)[:2],
                         (G.HEAT_OMITTED, record['heat_omission']['cumulative_bound_k']))
        with self.assertRaises(B.FeedbackRefused) as caught:           # a Verified value of another commit
            B.step(ledger, self.inputs, verified=self.first_verified)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'verified'))
        token = B.Verified(produced.commit_key, produced.state_id, produced.moving_id, produced.text, B.REPLAYED)
        with self.assertRaises(B.FeedbackRefused) as caught:           # a hand-built value is never trusted
            B.step(ledger, self.inputs, verified=token)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'verified'))
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.coupled_interval(ledger.sphere(head), ledger.moving(head), self.inputs,
                               interval=B.next_interval(ledger), parent=token)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.UNSUPPORTED, 'parent'))
        with self.assertRaises(B.FeedbackRefused) as caught:           # nor accepted as a cache entry
            B.verify_driving(ledger, head, cache={head.key: token})
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'cache'))
        # Round 3: a cache hit certifies the chain behind it. Ledger Q2 (the same identity) commits a forged interval
        # 0 and then the honest interval-1 bytes through the plain path; the honest cache must not certify its head.
        q2 = self.make('q2')
        forged = self.first.advance.declared_driving()
        forged.update(labels=[], normal_strain={'equator': 0.})
        forged['heat_omission'].update(cumulative_bound_k=0.)
        self.assertEqual(self.plain(q2, self.first, forged).status, K.COMPLETED)
        outcome = self.plain(q2, second)
        self.assertEqual(outcome.status, K.COMPLETED, outcome.reason)
        self.assertEqual(outcome.head.key, head.key)                   # the honest cache's key
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.verify_driving(q2, outcome.head, cache=dict(cache))
        self.assertEqual(caught.exception.code, B.STALE)
        self.assertIn(caught.exception.detail, ('cache', 'parent_driving_sha256'))
        self.assertIs(B.verify_driving(ledger, head, cache=cache), replayed)   # a valid cache still certifies

    def test_forged_inherited_fields_refuse_by_name(self):
        """Ruling P1(3): a fabricated record committed through the plain path is refused by the reader, field by
        field: labels, the cumulative strain, the heat bound, and the replayed P5."""
        honest = self.first.advance.declared_driving()
        edits = (('labels', lambda r: r.update(labels=[])),
                 ('normal_strain', lambda r: r.update(normal_strain={'equator': 0.})),
                 ('heat_omission', lambda r: r['heat_omission'].update(cumulative_bound_k=0.)),
                 ('p5', lambda r: r['p5']['omega_rad_s'][0].__setitem__(2, r['p5']['omega_rad_s'][0][2]*(1+1e-6))))
        for name, edit in edits:
            ledger = self.make('forged-'+name)
            forged = copy.deepcopy(honest)
            edit(forged)
            outcome = self.plain(ledger, self.first, forged)
            self.assertEqual(outcome.status, K.COMPLETED, outcome.reason)      # the plain path accepts the bytes
            self.assertEqual(B.find_driving(ledger, outcome.head)['status'], B.RECORDED)
            with self.assertRaises(B.FeedbackRefused) as caught:
                B.verify_driving(ledger, outcome.head)
            self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, name))
            # A cache from an honest ledger of the same identity (the same positional commit key) never certifies it.
            honest_commit = self.first_ledger.chain()[1]
            self.assertEqual(honest_commit.key, outcome.head.key)
            with self.assertRaises(B.FeedbackRefused) as caught:
                B.verify_driving(ledger, outcome.head, cache={honest_commit.key: self.first_verified})
            self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'cache'))

    def test_the_committed_increments_and_split_names_are_replayed(self):
        """The dkappa half of the fixed point: increments halved under the honest record refuse 'advance'; a producer
        whose history names are salted (not the pure reference) refuses on reopen."""
        ledger = self.make('halved')
        honest = self.first.advance
        halved = M.MovingAdvance(honest.start_step, honest.end_step, births=honest.births,
                                 conduction=honest.conduction,
                                 increments=tuple((k, tuple(v/2 for v in values)) for k, values in honest.increments),
                                 driving=honest.declared_driving())
        outcome = K.Clock(ledger).advance(steps=1, transfers=(self.first.motion, halved),
                                          deadline=time.perf_counter()+600.)
        self.assertEqual(outcome.status, K.COMPLETED, outcome.reason)
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.verify_driving(ledger, outcome.head)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'advance'))
        ledger = self.make('salted')
        original = B.history_reference
        B.history_reference = lambda cohort, values, *, interval: original(cohort, values, interval=interval)+':salt'
        try:
            salted = B.step(ledger, self.inputs)
        finally:
            B.history_reference = original
        outcome = self.plain(ledger, salted)
        self.assertEqual(outcome.status, K.COMPLETED, outcome.reason)
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.verify_driving(ledger, outcome.head)
        # the renamed sub-cohorts change the endpoint state and the motion; the binding fields are compared in order
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'endpoint_state_id'))

    def test_a_dropped_inheritance_refuses_at_commit_and_on_reopen(self):
        ledger = self.make('dropped')
        B.commit(ledger, self.first, deadline=time.perf_counter()+600.)
        head = ledger.head()
        orphan = B.coupled_interval(ledger.sphere(head), ledger.moving(head), self.inputs,
                                    interval=B.next_interval(ledger))           # parent omitted by the caller
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.commit(ledger, orphan)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'parent'))
        self.assertEqual(ledger.head().key, head.key)
        outcome = self.plain(ledger, orphan)
        self.assertEqual(outcome.status, K.COMPLETED, outcome.reason)
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.verify_driving(ledger, outcome.head)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'parent_driving_sha256'))

    def test_a_malformed_record_refuses_by_name(self):
        honest = self.first.advance.declared_driving()
        bare = {k: honest[k] for k in ('schema', 'parent_state_id', 'endpoint_state_id', 'interval', 'motion_id')}
        ledger = self.make('malformed')
        outcome = self.plain(ledger, self.first, bare)                  # it carries the binding fields only
        self.assertEqual(outcome.status, K.COMPLETED, outcome.reason)
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.verify_driving(ledger, outcome.head)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.MISSING, 'driving'))
        unbound = self.make('unbound')
        root = unbound.head()
        outcome = self.plain(unbound, self.first, dict(schema=B.SCHEMA))  # I05 refuses it inside the commit
        self.assertNotEqual(outcome.status, K.COMPLETED)
        self.assertEqual(unbound.head().key, root.key)

    def test_the_commit_binds_the_interval_and_a_refused_interval_commits_nothing(self):
        ledger = self.make('interval')
        root = ledger.head()
        k0, k1, s0, s1 = B.next_interval(ledger)
        half = B.coupled_interval(ledger.sphere(root), ledger.moving(root), self.inputs,
                                  interval=(k0, k1, s0, s0+(s1-s0)/2))
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.commit(ledger, half)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'interval'))
        outcome = self.plain(ledger, half)                               # I05 binds the record inside the commit
        self.assertNotEqual(outcome.status, K.COMPLETED)
        self.assertEqual(ledger.head().key, root.key)
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.bind_commit_interval((0., 1., 0, 1), half.motion_port)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.STALE, 'interval'))
        capped = self.make('cap')
        path = self.folder/'cap'/'ledger.sqlite'
        before = (capped.head().key, len(capped.chain()), hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaises(B.FeedbackRefused) as caught:
            B.step(capped, self.inputs, outer_iterations=1)
        self.assertEqual(caught.exception.code, B.NONCONVERGED)
        self.assertEqual((capped.head().key, len(capped.chain()), hashlib.sha256(path.read_bytes()).hexdigest()),
                         before)

    def test_a_coupled_interval_with_gpe_replays(self):
        """Ruling P7 (notes): the coupled route with GPE binds its P1 columns in the endpoint balance, and replays."""
        ledger = self.make('gpe')
        inputs = Z.inputs(declaration=Z.side_declaration('right'),
                          forcing=Z.forcing(gamma=1., omitted=('slab_pull', 'mantle_traction')))
        coupled = B.step(ledger, inputs)
        self.assertIsNotNone(coupled.balance.record()['columns_id'])
        B.commit(ledger, coupled, deadline=time.perf_counter()+600.)
        self.assertEqual(B.verify_driving(ledger, ledger.head()).status, B.REPLAYED)

    def test_the_history_must_be_an_unbroken_coupled_chain(self):
        """In v1 a non-coupled interval after a coupled one, and any committed I03 topology event, refuse by name."""
        class Commit:
            def __init__(self, metadata):
                self._metadata = metadata

            def metadata(self):
                return self._metadata
        driving = dict(moving=dict(advance=dict(driving=dict(schema=B.SCHEMA))))
        plain = dict(sphere=dict(motion=dict()))
        event = dict(sphere=dict(motion=dict(events=[dict(kind='split')])))
        with self.assertRaises(B.FeedbackRefused) as caught:
            B._history(None, [Commit({}), Commit(driving), Commit(plain)], 2)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.UNSUPPORTED, 'chain'))
        with self.assertRaises(B.FeedbackRefused) as caught:
            B._history(None, [Commit({}), Commit(event), Commit(driving)], 2)
        self.assertEqual((caught.exception.code, caught.exception.detail), (B.UNSUPPORTED, 'events'))
        self.assertEqual(B._history(None, [Commit({}), Commit(plain), Commit(driving)], 2), 2)


if __name__ == '__main__':
    unittest.main()
