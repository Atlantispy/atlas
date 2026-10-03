"""Supplied-history controls: analytic curved trace, covariance, refinement and replay.

Three northern plates spread about a supplied RRR junction and consume into a fixed southern plate. The reference
plate is O. Junction rate (0.001,0.002,0.0015) rad/interval; plate rates add 0.04 rad equatorial spreading axes.
Values are retrospectively recorded in i03_controls_v4.json, not claimed as predeclared.
Representation budgets 1e-6 and 2.5e-7 rad, ceiling 256 per end; C1/C4/area/material gates are unchanged.
"""
import json
import math
from pathlib import Path
import tempfile
import time
import unittest
from dataclasses import replace
from unittest.mock import patch
import numpy as np
from threadpoolctl import threadpool_limits

import i02_workflow_fixtures as F2
import i03_fixtures as F
from atlas_tectonics import integration_sphere as S, integration_transfer as T
from atlas_tectonics import integration_clock as K, integration_ledger as L
from atlas_tectonics import integration_junction_paths as P
from atlas_tectonics.geometry import GeometryLimits
from atlas_tectonics.resources import WorkBudget, MemoryLimitError

CONTROL = json.loads((F.CASES/'i03_controls_v4.json').read_text(encoding='utf-8'))['controls']['junction_paths']


def world(tilt=None, *, epoch=F.EPOCH, time_s=F.START):
    vertices, rings = F.sector_mesh(tuple(CONTROL['longitudes_deg']), tuple(CONTROL['latitudes_deg']), tilt=tilt)
    def owner(name):
        south = name.endswith('south') or ('-b' in name and int(name[-2:]) < 2)
        return 'O' if south else 'P%d' % (F.sector_of(name)//4)
    faces = tuple(S.Face(name, owner(name), ring) for name, ring in rings.items())
    boundaries = []
    for k in range(3):
        i = 4*k
        boundaries.append(S.Boundary('ridge%d' % k, S.RIDGE, 'P%d' % ((k-1) % 3), 'P%d' % k,
                                     tuple(F.vertex(i, j) for j in range(2, 5))+('N',), F.origin(), accretion_fraction=.5))
        boundaries.append(S.Boundary('trench%d' % k, S.TRENCH, 'P%d' % k, 'O',
                                     tuple(F.vertex(j % 12, 2) for j in range(i, i+5)), F.origin(),
                                     subducting_side='left'))
    return S.build_network(sphere=F.sphere(), vertices=vertices, faces=faces,
                           plates=tuple(S.Plate(p, F.IDENTITY) for p in ('O', 'P0', 'P1', 'P2')),
                           boundaries=tuple(boundaries), epoch_id=epoch, time_s=time_s)


def motion(accuracy=CONTROL['accuracy_rad'], ceiling=CONTROL['max_segments'], tilt=None):
    rate = np.array(CONTROL['junction_rate_rad'])
    turn = (lambda r: r) if tilt is None else (lambda r: tilt.inverse().then(r).then(tilt))
    rotations = {'O': F.IDENTITY}
    for k in range(3):
        lon = math.radians(60+120*k)
        rotations['P%d' % k] = turn(P.exponential(rate+CONTROL['spread_rad']*np.array((-math.sin(lon), math.cos(lon), 0.))))
    # An initially tilted declaration has identity local plate frames, so its supplied local axes are tilted too.
    path = T.JunctionPath('junction:N', 'O', turn(P.exponential(rate)), accuracy, ceiling)
    return T.Motion(0, 1, rotations, supplies=tuple(s for k in range(3) for s in F.both_sides('ridge%d' % k)),
                    sinks=tuple(F.sink('trench%d' % k) for k in range(3)), junction_paths=(path,))


class SuppliedPathTests(unittest.TestCase):
    def test_curved_noncommuting_history_closes_and_restores(self):
        state = F.crust(world())
        step = T.advance(state, motion(), end_time_s=F.MYR_S)
        self.assertTrue(step.state.material.closure()['identity_exact'])
        self.assertGreater(len(step.state.network.vertex_ids), len(state.network.vertex_ids)+20)
        rebuilt = T._motion(step.motion.record())
        self.assertEqual(rebuilt.motion_id, step.motion.motion_id)
        restored = T.restored(state, {'sphere': step.record(), 'transfers': []}, step.arrays())
        self.assertEqual(restored.state_id, step.state.state_id)
        # The next actual interval starts against the retained analytic tangent, not the last sampled chord.
        follow = replace(motion(), start_step=1, end_step=2)
        continued = T.advance(restored, follow, end_time_s=2*F.MYR_S)
        self.assertTrue(continued.state.material.closure()['identity_exact'])
        self.assertGreater(len(continued.state.network.vertex_ids), len(restored.network.vertex_ids))
        rebuilt = T.restored(restored, {'sphere': continued.record(), 'transfers': []}, continued.arrays())
        self.assertEqual(rebuilt.state_id, continued.state.state_id)
        # The prior D5 seam stays with its carried interior material edge, not its old trench sampling point.
        name = 'm00-p02|P0|1'
        i = rebuilt.network.vertex_ids.index(name)
        j = rebuilt.network.vertex_ids.index('m00-p02')
        self.assertGreater(math.atan2(*rebuilt.network.vertex_direction[i, 1::-1]),
                           math.atan2(*rebuilt.network.vertex_direction[j, 1::-1]))

    def test_common_reference_and_declared_axes_are_covariant(self):
        state, proposal = F.crust(world()), motion()
        plain = T.advance(state, proposal, end_time_s=F.MYR_S)
        plain_next = T.advance(plain.state, replace(proposal, start_step=1, end_step=2), end_time_s=2*F.MYR_S)
        for initial_tilt in (False, True):
            parent = F.crust(world(F.TILT)) if initial_tilt else state
            moved = motion(tilt=F.TILT) if initial_tilt else replace(
                proposal, rotations=tuple((p, r.then(F.TILT)) for p, r in proposal.rotations))
            turned = T.advance(parent, moved, end_time_s=F.MYR_S)
            self.assertEqual(plain.state.network.vertex_ids, turned.state.network.vertex_ids)
            error = F.angle(F.TILT.apply(plain.state.network.vertex_direction), turned.state.network.vertex_direction)
            self.assertLessEqual(float(np.max(error)), S.ATTACHMENT_BAND_RAD)
            for key, value in plain.state.material.totals().items():
                self.assertLessEqual(abs(turned.state.material.totals()[key]-value), 1e-12*max(1., abs(value)))
            follow = replace(motion(tilt=F.TILT), start_step=1, end_step=2)
            if not initial_tilt:
                # A common first-interval turn moves O's stored reference frame as well. Stage rotations use
                # global axes, but the supplied path still uses the original, now rotated O-local axes.
                follow = replace(follow, junction_paths=proposal.junction_paths)
            turned_next = T.advance(turned.state, follow, end_time_s=2*F.MYR_S)
            self.assertEqual(plain_next.state.network.vertex_ids, turned_next.state.network.vertex_ids)
            error = F.angle(F.TILT.apply(plain_next.state.network.vertex_direction),
                            turned_next.state.network.vertex_direction)
            self.assertLessEqual(float(np.max(error)), S.ATTACHMENT_BAND_RAD)
            for key, value in plain_next.state.material.totals().items():
                self.assertLessEqual(abs(turned_next.state.material.totals()[key]-value), 1e-12*max(1., abs(value)))

    def test_same_continuous_rates_advance_in_one_or_two_intervals(self):
        state, proposal = F.crust(world()), motion()
        whole = T.advance(state, proposal, end_time_s=F.MYR_S)
        half = replace(proposal, rotations=tuple((p, P.exponential(.5*P.vector(r)))
                                                for p, r in proposal.rotations),
                       junction_paths=tuple(replace(path, relative_rotation=P.exponential(
                           .5*P.vector(path.relative_rotation))) for path in proposal.junction_paths))
        first = T.advance(state, half, end_time_s=F.MYR_S/2)
        second = T.advance(first.state, replace(half, start_step=1, end_step=2), end_time_s=F.MYR_S)
        # The original vertices are the physical junctions and retained carrier samples. New curve samples need
        # not have matching identities after subdivision. Their representation has its separate bound below.
        for name in state.network.vertex_ids:
            a = whole.state.network.vertex_direction[whole.state.network.vertex_ids.index(name)]
            b = second.state.network.vertex_direction[second.state.network.vertex_ids.index(name)]
            self.assertLessEqual(float(F.angle(a, b)), S.ATTACHMENT_BAND_RAD, name)
        self.assertTrue(first.state.material.closure()['identity_exact'])
        self.assertTrue(second.state.material.closure()['identity_exact'])
        rebuilt = T.restored(first.state, {'sphere': second.record(), 'transfers': []}, second.arrays())
        self.assertEqual(rebuilt.state_id, second.state.state_id)

    def test_saved_history_reopens_then_accepts_the_next_advancing_interval(self):
        with threadpool_limits(limits=1, user_api='blas'), tempfile.TemporaryDirectory() as folder:
            column = F2.root(F.control('clock_commit')['column_steps'])
            state = F.crust(world(epoch=F2.EPOCH, time_s=F2.START))
            store = F2.store(Path(folder)/'ledger.sqlite')
            deadline = lambda: time.perf_counter()+F.CASE['resources']['clock_deadline_s']
            try:
                ledger, root = L.Ledger.create(store, column, sphere=state)
                first = K.Clock(ledger).advance(steps=1, deadline=deadline(), transfers=(motion(),))
                self.assertEqual(first.status, K.COMPLETED, first.reason)
                saved = ledger.sphere(first.head)
                follow = replace(motion(), start_step=1, end_step=2)
                end_time_s = saved.network.time_s+(saved.network.time_s-state.network.time_s)
                expected = T.advance(saved, follow, end_time_s=end_time_s).state.state_id
                ledger_id = ledger.ledger_id
            finally:
                store.close()
            store = F2.store(Path(folder)/'ledger.sqlite')
            try:
                reopened = L.Ledger.open(store, ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
                self.assertEqual(reopened.verify_chain().key, first.head.key)
                self.assertEqual(reopened.sphere(first.head).state_id, saved.state_id)
                # Commit the actual advancing interval from the reopened head, not a preparation helper.
                second = K.Clock(reopened).advance(steps=1, deadline=deadline(), transfers=(follow,))
                self.assertEqual(second.status, K.COMPLETED, second.reason)
                self.assertEqual(reopened.sphere(second.head).state_id, expected)
                self.assertEqual(reopened.verify_chain().key, second.head.key)
            finally:
                store.close()

    def test_curve_refinement_meets_its_separate_representation_bound(self):
        j = np.array(CONTROL['junction_rate_rad'])
        c = j+np.array((0., -.02, 0.))
        origin = np.array((0., 0., 1.))
        previous = math.inf
        counts = []
        for accuracy in (CONTROL['accuracy_rad'], CONTROL['refined_accuracy_rad']):
            points = P.sample(c, j, origin, accuracy, 256, None)
            counts.append(len(points))
            worst = 0.
            for k, (a, b) in enumerate(zip(points, points[1:])):
                pole = np.cross(a, b)
                pole /= np.linalg.norm(pole)
                for part in (.25, .5, .75):
                    s = (k+part)/(len(points)-1)
                    exact = S._placed(P.exponential(-s*c), S._placed(P.exponential(s*j), origin)[0])[0]
                    worst = max(worst, abs(math.asin(float(pole @ exact))))
            self.assertGreater(worst, 0.)       # actually curved, not a renamed great-circle control
            self.assertLessEqual(worst, accuracy+S.ATTACHMENT_BAND_RAD)
            self.assertLess(worst, previous)
            previous = worst
            step = T.advance(F.crust(world()), motion(accuracy), end_time_s=F.MYR_S)
            self.assertTrue(step.state.material.closure()['identity_exact'])
        self.assertGreater(counts[1], counts[0])
        exact = P.sample(np.array((0., -.02, 0.)), np.zeros(3), origin, 1e-10, 1, None)
        self.assertEqual(len(exact), 2)

    def test_limits_refuse_before_issuing_and_release_workspace(self):
        state, proposal = F.crust(world()), motion()
        with self.assertRaisesRegex(T.TransferRefused, 'segment ceiling'):
            T.advance(state, motion(ceiling=1), end_time_s=F.MYR_S)
        with self.assertRaisesRegex(T.TransferRefused, 'vertex limit'):
            T.advance(state, proposal, end_time_s=F.MYR_S, limits=GeometryLimits(max_vertices=100))
        budget = WorkBudget(T._step_workspace(state.network, proposal)-1)
        with self.assertRaises(MemoryLimitError):
            T.advance(state, proposal, end_time_s=F.MYR_S, budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)
        # Charge remains live when the later material assembly runs, not merely while samples are constructed.
        roomy = WorkBudget(64 << 20)
        original = T._transferred
        def observed(*args, **kwargs):
            self.assertGreaterEqual(roomy.reserved_bytes, T._step_workspace(state.network, proposal))
            return original(*args, **kwargs)
        with patch.object(T, '_transferred', observed):
            step = T.advance(state, proposal, end_time_s=F.MYR_S, budget=roomy)
        self.assertEqual(roomy.reserved_bytes, 0)
        with self.assertRaises(MemoryLimitError):
            T.restored(state, {'sphere': step.record(), 'transfers': []}, step.arrays(), budget=budget)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_incompatible_or_unsupported_paths_do_not_fall_back(self):
        state, proposal = F.crust(world()), motion()
        wrong = replace(proposal.junction_paths[0], relative_rotation=F.IDENTITY)
        with self.assertRaisesRegex(T.TransferRefused, 'C1'):
            T.advance(state, replace(proposal, junction_paths=(wrong,)), end_time_s=F.MYR_S)
        mixed = replace(proposal.junction_paths[0], junction_id='junction:m00-p02')
        with self.assertRaisesRegex(T.TransferRefused, 'all-ridge'):
            T.advance(state, replace(proposal, junction_paths=(mixed,)), end_time_s=F.MYR_S)
        record = proposal.record()
        record['path_interpolation'] = 'unchecked-endpoints'
        with self.assertRaises(T.LedgerError):
            T._motion(record)


if __name__ == '__main__':
    unittest.main()
