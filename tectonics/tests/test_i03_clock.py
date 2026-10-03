"""Focused I03.2 checks through I02: the moving network committed by the accepted clock, saved and continued.

The real layered column is the ledger's root and a three-plate sector network stands beside it. Every commit must
carry the column steps, the network's step and its transfers together or not at all; a request without a motion, a
refused motion, a cancelled commit or an exhausted finite stock commits nothing of its interval; a stored step must
restore by applying its recorded rows to its parent again; an edited store is refused; and a history saved after some
steps and continued in a fresh process must reach exactly the network state of the uninterrupted history. The
controls' values are read from cases/i03_controls_v1.json (clock_commit, finite_stock, continuation).
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np
from threadpoolctl import threadpool_limits

import atlas_tectonics
from atlas_tectonics import integration_clock as K, integration_ledger as L, integration_sphere as S
from atlas_tectonics import integration_state as I, integration_transfer as T
from atlas_tectonics.storage import StoreError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import i02_workflow_fixtures as F2
import i03_fixtures as F

SRC = str(Path(atlas_tectonics.__file__).resolve().parents[1])
RELATIVE = F.tolerance('relative')
ANGULAR = F.tolerance('angular_absolute_rad')
COMMIT = F.control('clock_commit')
STOCK = F.control('finite_stock')
CONTINUATION = F.control('continuation')
RESOURCES = F.CASE['resources']
STEPS = COMMIT['column_steps']
DEGREES = COMMIT['rotation_deg_per_interval']
EXCHANGE = tuple(tuple(pair) for pair in STOCK['exchange_exteriors'])
LINK = dict(STOCK['stock_link'])
FIX = {}


def setUpModule():
    with threadpool_limits(limits=1, user_api='blas'):
        FIX['prepared'] = F2.preparation()


def child(script, *args):
    env = dict(os.environ, PYTHONPATH=SRC)
    return subprocess.run([sys.executable, '-B', '-c', script, str(HERE), *map(str, args)], capture_output=True,
                          text=True, env=env, timeout=RESOURCES['child_timeout_s'])


def advance(clock, **request):
    """One clock request under the case's cooperative deadline."""
    return clock.advance(deadline=time.perf_counter()+RESOURCES['clock_deadline_s'], **request)


def world(**changes):
    return F.three_plates(epoch=F2.EPOCH, time_s=F2.START, **changes)


def motion(step, degrees=DEGREES, end=None, **changes):
    """Plate A turns ``degrees`` per interval between fixed B and C: a ridge behind it and a trench ahead."""
    values = dict(step=step)
    if end is not None:
        values['end_step'] = end
    values.update(changes)
    return F.one_plate_motion(degrees, **values)


def stocked_sphere():
    """Pieces in the finite stocks' own components and basis, linked to them through the exchange."""
    pieces = STOCK['pieces']
    return F.state(world(), phases=tuple(pieces['phases']), basis=F2.BASIS, stock_link=LINK, exteriors=F.EXTERIORS,
                   mass_per_area_kg_m2=dict(pieces['mass_per_area_kg_m2']), thickness_m=dict(pieces['thickness_m']),
                   enthalpy_per_area_j_m2=pieces['enthalpy_per_area_j_m2'])


def stock_supply(side, **changes):
    supply = STOCK['supply']
    values = dict(source=supply['source'], stock=True, mass_per_area_kg_m2=dict(supply['mass_per_area_kg_m2']),
                  thickness_m=dict(supply['thickness_m']), enthalpy_per_area_j_m2=supply['enthalpy_per_area_j_m2'])
    values.update(changes)
    return F.supply('boundary-m02', side, **values)


class Limited(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api='blas')
        self.addCleanup(lease.restore_original_limits)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.path = self.folder/'ledger'/'ledger.sqlite'
        self.store = F2.store(self.path)
        self.addCleanup(self.store.close)

    def ledger(self, sphere=None, stocks=False, **kwargs):
        column = F2.root(STEPS, prepared=FIX['prepared'], **(dict(stocks=F2.reservoirs(), basis=F2.BASIS)
                                                             if stocks else {}))
        sphere = F.crust(world()) if sphere is None else sphere
        return L.Ledger.create(self.store, column, sphere=sphere, **kwargs)


class CommitTests(Limited):
    def test_each_commit_carries_the_column_steps_and_the_network_step_together(self):
        ledger, root = self.ledger()
        clock = K.Clock(ledger)
        (a, b), (c, d) = COMMIT['commit_intervals']
        outcome = advance(clock, steps=COMMIT['first_request_steps'], transfers=(motion(a), motion(c, end=d)))
        self.assertEqual((outcome.status, outcome.accepted_steps), (K.COMPLETED, COMMIT['first_request_steps']))
        self.assertEqual([commit.interval[2:] for commit in outcome.commits], [(a, b), (c, d)])
        first, second = outcome.commits
        one, two = ledger.sphere(first), ledger.sphere(second)
        self.assertEqual((one.step, one.time_s, one.issued_by), (b, clock.time_at(b), I.COMPUTED))
        self.assertEqual((two.step, two.time_s), (d, clock.time_at(d)))
        self.assertEqual((one.parent_state_id, two.parent_state_id), (ledger.sphere(root).state_id, one.state_id))
        self.assertEqual(two.initial_state_id, ledger.sphere(root).state_id)
        # The network moved once per committed interval: one rotation, then one over two column steps.
        self.assertLessEqual(F.rotation_angle(two.network.plate('A').rotation, F.spin(2*DEGREES)), ANGULAR)
        metadata = second.metadata()
        self.assertEqual(metadata['sphere']['interval'], metadata['interval'])
        self.assertEqual((metadata['sphere']['state_id'], metadata['sphere']['parent_state_id']),
                         (two.state_id, one.state_id))
        # One snapshot holds the column's arrays, the network, its material and the overlap rows.
        stored = self.store.get(second.key)
        self.assertEqual(stored['sphere.piece_stock'].tobytes(), two.material.stock.tobytes())
        self.assertEqual(stored['sphere.vertex_reference'].tobytes(),
                         two.network.arrays()['sphere.vertex_reference'].tobytes())
        self.assertIn('column.theta_k', stored)
        self.assertEqual(len(stored['sphere.map_area_m2']), metadata['sphere']['map']['rows'])
        self.assertEqual(self.store.statistics()['snapshots'], 3)
        self.assertEqual(ledger.describe(second)['sphere']['state_id'], two.state_id)
        self.assertTrue(two.material.closure()['identity_exact'])
        self.assertEqual(ledger.state(second).column.accepted_steps, d)
        ledger.verify_chain()

    def test_a_request_without_a_motion_commits_nothing(self):
        ledger, root = self.ledger()
        clock = K.Clock(ledger)
        outcome = advance(clock, steps=2)
        self.assertEqual((outcome.status, outcome.accepted_steps, outcome.head.key),
                         (K.REFUSED_EXCHANGE, 0, root.key))
        self.assertIn('exactly one Motion', outcome.reason)
        partly = advance(clock, steps=2, transfers=(motion(0),))           # the second step has no motion
        self.assertEqual((partly.status, partly.accepted_steps, [c.accepted_steps for c in partly.commits]),
                         (K.REFUSED_EXCHANGE, 1, [1]))
        self.assertEqual(ledger.head().accepted_steps, 1)
        self.assertEqual(self.store.statistics()['snapshots'], 2)

    def test_a_refused_motion_leaves_the_head_at_the_interval_start(self):
        ledger, root = self.ledger()
        clock = K.Clock(ledger)
        backwards = motion(1, degrees=COMMIT['backward_deg'])
        outcome = advance(clock, steps=2, transfers=(motion(0), backwards))
        self.assertEqual((outcome.status, outcome.accepted_steps), (K.REFUSED_EXCHANGE, 1))
        self.assertIn('negative half-rate', outcome.reason)
        self.assertEqual(ledger.head().key, outcome.commits[0].key)
        again = advance(clock, steps=1, transfers=(motion(1),))            # the history continues from there
        self.assertEqual((again.status, ledger.sphere(again.head).step), (K.COMPLETED, 2))

    def test_a_motion_is_committed_only_over_its_own_interval_and_parent(self):
        ledger, root = self.ledger()
        run = I.Continuation(ledger.state(root))
        s1 = run.advance(ledger.state(root), 1).state
        s2 = run.advance(s1, 1).state
        with self.assertRaises(L.ExchangeRefused) as caught:
            ledger.commit(root, (s1, s2), (motion(0),))
        self.assertIn('cannot be committed over (0, 2]', str(caught.exception))
        with self.assertRaises(L.ExchangeRefused):
            ledger.commit(root, (s1,), (motion(0), motion(0, degrees=COMMIT['rival_deg'])))
        c1 = ledger.commit(root, (s1,), (motion(0),))
        again = ledger.commit(root, (s1,), (motion(0),))                    # an identical replay is idempotent
        self.assertEqual((again.key, self.store.statistics()['snapshots']), (c1.key, 2))
        with self.assertRaises(L.LedgerConflict):
            ledger.commit(root, (s1,), (motion(0, degrees=COMMIT['rival_deg']),))   # a changed replay: stale parent
        self.assertEqual(ledger.head().key, c1.key)

    def test_a_retry_that_meets_its_own_published_record_adopts_it(self):
        ledger, root = self.ledger()
        put, calls = self.store.put, []

        def faulty(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise StoreError('the retry fails at its write')
            result = put(*args, **kwargs)
            if len(calls) == 1:
                raise KeyboardInterrupt                  # published, then interrupted before the clock hears of it
            return result
        clock = K.Clock(ledger)
        with mock.patch.object(self.store, 'put', faulty), self.assertRaises(KeyboardInterrupt) as caught:
            advance(clock, steps=2, transfers=(motion(0), motion(1)))
        head = ledger.head()
        self.assertEqual((head.accepted_steps, ledger.sphere(head).step), (1, 1))     # the network step too
        self.assertIn('committed as %s' % head.key, '\n'.join(caught.exception.__notes__))
        after = advance(clock, steps=1, transfers=(motion(1),))                      # adopted, not overtaken
        self.assertEqual((after.status, after.accepted_steps, ledger.sphere(after.head).step), (K.COMPLETED, 1, 2))

    def test_a_rival_record_of_the_same_steps_with_another_motion_is_refused_not_adopted_as_ours(self):
        ledger, root = self.ledger()
        other = F2.store(self.path)                                # a second connection to the same file
        self.addCleanup(other.close)
        rival = L.Ledger.open(other, ledger.ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
        column = ledger.state(root)
        s1 = I.Continuation(column).advance(column, 1).state       # the same deterministic first column step
        put, done = self.store.put, []

        def racing(*args, **kwargs):
            if not done:
                done.append(1)
                rival.commit(rival.root, (s1,), (motion(0, degrees=COMMIT['rival_deg']),))
            return put(*args, **kwargs)
        with mock.patch.object(self.store, 'put', racing):
            outcome = advance(K.Clock(ledger), steps=1, transfers=(motion(0),))
        self.assertEqual(outcome.status, K.REFUSED_EXCHANGE)
        self.assertIn('other transfers', outcome.reason)
        self.assertEqual([c.key for c in outcome.commits], [ledger.head().key])      # the rival's record is the head
        self.assertLessEqual(F.rotation_angle(ledger.sphere(ledger.head()).network.plate('A').rotation,
                                              F.spin(COMMIT['rival_deg'])), ANGULAR)

    def test_a_mesh_change_is_committed_and_restored_with_its_rows(self):
        ledger, root = self.ledger()
        start = ledger.sphere(root)
        faces = {face.face_id: face for face in start.network.faces}
        for name in COMMIT['mesh_merge']:
            del faces[name]
        faces['s00-merged'] = S.Face('s00-merged', 'C', (F.vertex(0, 1), F.vertex(1, 1), F.vertex(1, 2),
                                                           F.vertex(1, 3), F.vertex(0, 3), F.vertex(0, 2)))
        still = T.Motion(0, 1, {plate: F.IDENTITY for plate in 'ABC'}, mesh=T.Mesh(tuple(faces.values())))
        outcome = advance(K.Clock(ledger), steps=2, transfers=(still, motion(1)))
        self.assertEqual(outcome.status, K.COMPLETED, outcome.reason)
        first, second = outcome.commits
        meshed = ledger.sphere(first)
        self.assertEqual(len(meshed.network.face_ids), len(start.network.face_ids)-1)
        stored = self.store.get(first.key)
        self.assertEqual(len(stored['sphere.remap_area_m2']), len(COMMIT['mesh_merge']))
        self.assertEqual(first.metadata()['sphere']['motion']['mesh_id'], still.mesh.mesh_id)
        final = ledger.sphere(second)
        self.store.close()
        store = F2.store(self.path)
        self.addCleanup(store.close)
        again = L.Ledger.open(store, ledger.ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
        chain = again.chain()
        self.assertEqual(again.verify_chain().key, second.key)
        self.assertEqual((again.sphere(chain[1]).state_id, again.sphere(chain[2]).state_id),
                         (meshed.state_id, final.state_id))
        self.assertEqual(again.sphere(chain[1]).material.face_cohorts('s00-merged'), ('inherited-C',))

    def test_a_cancelled_commit_stops_in_the_network_step_and_publishes_nothing(self):
        ledger, root = self.ledger()
        column = ledger.state(root)
        s1 = I.Continuation(column).advance(column, 1).state
        cancel = threading.Event()
        cancel.set()
        with mock.patch.object(self.store, 'put', wraps=self.store.put) as put, self.assertRaises(CancelledError):
            ledger.commit(root, (s1,), (motion(0),), cancel=cancel)
        put.assert_not_called()                      # stopped while moving the network: nothing was prepared
        self.assertEqual((ledger.head().key, self.store.statistics()['snapshots']), (root.key, 1))
        done = ledger.commit(root, (s1,), (motion(0),))                     # the parent is still usable
        self.assertEqual((ledger.sphere(done).step, ledger.head().key), (1, done.key))

    def test_a_clock_request_stops_at_its_cancellation_between_whole_intervals(self):
        ledger, root = self.ledger()
        polls = []

        def cancel():
            polls.append(1)
            return len(polls) > 1                    # after the first whole step
        outcome = advance(K.Clock(ledger), steps=2, transfers=(motion(0), motion(1)), cancel=cancel)
        self.assertEqual((outcome.status, outcome.accepted_steps), (K.CANCELLED, 1))
        self.assertEqual(ledger.sphere(ledger.head()).step, 1)               # the accepted interval is kept whole
        again = advance(K.Clock(ledger), steps=1, transfers=(motion(1),))
        self.assertEqual((again.status, ledger.sphere(again.head).step), (K.COMPLETED, 2))

    def test_a_slow_interval_does_not_strand_the_history(self):
        # The strips born in a slow interval are a few metres wide; the next interval must still be accepted.
        ledger, root = self.ledger()
        slow, usual = COMMIT['slow_then_normal_deg']
        outcome = advance(K.Clock(ledger), steps=3, transfers=(motion(0, degrees=slow), motion(1, degrees=usual),
                                                               motion(2, degrees=usual)))
        self.assertEqual((outcome.status, outcome.accepted_steps), (K.COMPLETED, 3), outcome.reason)
        final = ledger.sphere(outcome.head)
        self.assertTrue(final.material.closure()['identity_exact'])
        self.store.close()
        store = F2.store(self.path)
        self.addCleanup(store.close)
        again = L.Ledger.open(store, ledger.ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
        self.assertEqual(again.sphere(again.verify_chain()).state_id, final.state_id)

    def test_a_ledger_without_a_network_refuses_a_motion(self):
        ledger, root = L.Ledger.create(self.store, F2.root(STEPS, prepared=FIX['prepared']))
        outcome = advance(K.Clock(ledger), steps=1, transfers=(motion(0),))
        self.assertEqual((outcome.status, outcome.accepted_steps), (K.REFUSED_EXCHANGE, 0))
        self.assertEqual(advance(K.Clock(ledger), steps=1).status, K.COMPLETED)


class StockTests(Limited):
    def test_births_debit_a_finite_stock_once_and_returns_credit_one(self):
        source, target = STOCK['supply']['source'], STOCK['return_to']
        components = tuple(STOCK['pieces']['phases'])
        ledger, root = self.ledger(stocked_sphere(), stocks=True, exteriors=EXCHANGE)
        move = motion(0, supplies=(stock_supply('left'), stock_supply('right')),
                      sinks=(F.sink('boundary-m04', ((target, 1., True),)),))
        outcome = advance(K.Clock(ledger), steps=1, transfers=(move,))
        self.assertEqual(outcome.status, K.COMPLETED, outcome.reason)
        commit = outcome.head
        sphere, exchange = ledger.sphere(commit), ledger.exchange(commit)
        records = commit.metadata()['transfers']
        self.assertEqual([r['producer'] for r in records], [T.PRODUCER]*3)
        births = [r for r in records if r['donor'] == source]
        returns = [r for r in records if r['receiver'] == target]
        self.assertEqual((len(births), len(returns)), (2, 1))
        self.assertEqual({r['receiver'] for r in births}, {LINK['receives']})
        self.assertEqual(returns[0]['donor'], LINK['returns'])
        # The stocks changed by the recorded transfers, and the exchange accounts close exactly.
        before = ledger.exchange(root).inventory
        given = [math.fsum(r['component_mass_kg'][c] for r in births) for c in components]
        taken = [returns[0]['component_mass_kg'][c] for c in components]
        after = exchange.inventory
        np.testing.assert_allclose(after.component_mass_kg[0], before.component_mass_kg[0]-given, rtol=RELATIVE)
        np.testing.assert_allclose(after.component_mass_kg[1], before.component_mass_kg[1]+taken, rtol=RELATIVE)
        self.assertTrue(exchange.closure()['identity_exact'])
        self.assertTrue(sphere.material.closure()['identity_exact'])
        # One debit, one credit: what the exchange says the lithosphere received is what the pieces' account holds.
        supplied = sphere.material.supplied()
        names = [name for name, _ in exchange.exteriors]
        for k, component in enumerate(components):
            received = -exchange._supplied[0][names.index(LINK['receives'])][k]
            self.assertEqual(supplied['stock|'+source]['mass_kg:'+component], received)
            returned = exchange._supplied[0][names.index(LINK['returns'])][k]
            self.assertEqual(-supplied['stock|'+target]['mass_kg:'+component], returned)
        self.assertEqual(supplied['stock|'+source]['enthalpy_j'],
                         -exchange._supplied[1][names.index(LINK['receives'])])
        self.assertEqual(-supplied['stock|'+target]['enthalpy_j'],
                         exchange._supplied[1][names.index(LINK['returns'])])
        self.assertGreater(float(supplied['stock|'+source]['volume_m3:A']), 0)       # volume: the network's account
        self.assertEqual(sorted(commit.metadata()['sphere']['stock_transfers']), sorted(r['label'] for r in records))
        ledger.verify_chain()

    def test_an_exhausted_finite_source_refuses_the_whole_interval(self):
        ledger, root = self.ledger(stocked_sphere(), stocks=True, exteriors=EXCHANGE)
        greedy = motion(0, supplies=(stock_supply('left', mass_per_area_kg_m2=dict(
            STOCK['exhausting_mass_per_area_kg_m2'])), stock_supply('right')))
        outcome = advance(K.Clock(ledger), steps=1, transfers=(greedy,))
        self.assertEqual((outcome.status, outcome.accepted_steps, outcome.head.key),
                         (K.REFUSED_EXCHANGE, 0, root.key))
        self.assertIn('finite availability', outcome.reason)
        self.assertEqual(self.store.statistics()['snapshots'], 1)
        modest = motion(0, supplies=(stock_supply('left'), stock_supply('right')))
        self.assertEqual(advance(K.Clock(ledger), steps=1, transfers=(modest,)).status, K.COMPLETED)

    def test_restoration_refuses_a_foreign_transfer_through_the_linked_exteriors(self):
        # A commit written by a writer that skipped the check commit() makes: another producer moves stock into the
        # exterior that stands for the network. The pieces never received it, so the history must not restore.
        source = STOCK['supply']['source']
        ledger, root = self.ledger(stocked_sphere(), stocks=True, exteriors=EXCHANGE)
        column = ledger.state(root)
        s1 = I.Continuation(column).advance(column, 1).state
        move = motion(0, supplies=(stock_supply('left'), stock_supply('right')))
        leak = L.Transfer(label='leak', producer='tests', donor=source, receiver=LINK['receives'],
                          component_mass_kg={'A': 1., 'B': 0.}, enthalpy_j=0., basis=F2.BASIS, start_step=0,
                          end_step=1)
        with self.assertRaises(L.ExchangeRefused):
            ledger.commit(root, (s1,), (move, leak))

        def lax(ledger, parent, parent_meta, interval, transfers, budget=None, cancel=None):
            others = tuple(item for item in transfers if type(item) is not T.Motion)
            step = T.advance(ledger._restored_sphere(parent, parent_meta), move, end_time_s=interval[1])
            return others+step.stock_transfers, step
        with mock.patch.object(T, 'proposed', lax):
            ledger.commit(root, (s1,), (move, leak))
        self.store.close()
        store = F2.store(self.path)
        self.addCleanup(store.close)
        again = L.Ledger.open(store, ledger.ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
        with self.assertRaises(L.LedgerError):
            again.verify_chain()
        with self.assertRaises(L.LedgerError):
            again.sphere(again.chain()[-1])

    def test_only_the_network_step_uses_its_linked_exteriors(self):
        source, target = STOCK['supply']['source'], STOCK['return_to']
        ledger, root = self.ledger(stocked_sphere(), stocks=True, exteriors=EXCHANGE)
        leak = L.Transfer(label='leak', producer='tests', donor=source, receiver=LINK['receives'],
                          component_mass_kg={'A': 1., 'B': 0.}, enthalpy_j=0., basis=F2.BASIS, start_step=0,
                          end_step=1)
        move = motion(0, supplies=(stock_supply('left'), stock_supply('right')))
        outcome = advance(K.Clock(ledger), steps=1, transfers=(move, leak))
        self.assertEqual((outcome.status, outcome.accepted_steps), (K.REFUSED_EXCHANGE, 0))
        self.assertIn('linked exchange exteriors', outcome.reason)
        between = L.Transfer(label='between-stocks', producer='tests', donor=source, receiver=target,
                             component_mass_kg={'A': 1., 'B': 0.}, enthalpy_j=0., basis=F2.BASIS, start_step=0,
                             end_step=1)
        done = advance(K.Clock(ledger), steps=1, transfers=(move, between))  # unrelated exchanges still commit
        self.assertEqual(done.status, K.COMPLETED, done.reason)
        self.assertEqual(len(done.head.metadata()['transfers']), 3)


CONTINUE = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
import i02_workflow_fixtures as F2
import i03_fixtures as F
from atlas_tectonics import integration_clock as K, integration_ledger as L
store = F2.store(sys.argv[2])
ledger = L.Ledger.open(store, sys.argv[3], source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
head = ledger.verify_chain()
start, steps = head.accepted_steps, int(sys.argv[4])
restored = ledger.sphere(head)
degrees = F.control('clock_commit')['rotation_deg_per_interval']
moves = tuple(F.one_plate_motion(degrees, step=k) for k in range(start, start+steps))
outcome = K.Clock(ledger).advance(steps=steps, transfers=moves,
                                  deadline=time.perf_counter()+F.CASE['resources']['clock_deadline_s'])
state = ledger.sphere(outcome.head)
print(outcome.status, outcome.head.accepted_steps, restored.issued_by, state.state_id,
      state.material.closure()['identity_exact'], len(ledger.chain()))
store.close()
'''


class ContinuationTests(Limited):
    whole, saved, continued = (CONTINUATION[name] for name in ('uninterrupted_steps', 'saved_after_steps',
                                                              'continued_steps'))
    factors = CONTINUATION['edit_factors']

    def run_steps(self, ledger, first, count):
        moves = tuple(motion(k) for k in range(first, first+count))
        outcome = advance(K.Clock(ledger), steps=count, transfers=moves)
        self.assertIn(outcome.status, (K.COMPLETED, K.HISTORY_COMPLETE), outcome.reason)
        return outcome

    def test_save_reopen_and_continue_reaches_the_uninterrupted_network_state(self):
        self.assertEqual(self.saved+self.continued, self.whole)
        # The uninterrupted history, in its own store.
        whole_store = F2.store(self.folder/'whole'/'ledger.sqlite')
        self.addCleanup(whole_store.close)
        column = F2.root(STEPS, prepared=FIX['prepared'])
        whole, _ = L.Ledger.create(whole_store, column, sphere=F.crust(world()))
        final = whole.sphere(self.run_steps(whole, 0, self.whole).head)
        # The same history saved after three steps and continued by a fresh process.
        ledger, root = self.ledger()
        saved = self.run_steps(ledger, 0, self.saved).head
        middle = ledger.sphere(saved)
        self.store.close()
        done = child(CONTINUE, self.path, ledger.ledger_id, self.continued)
        self.assertEqual(done.returncode, 0, done.stderr)
        status, steps, issued, state_id, exact, commits = done.stdout.split()
        self.assertEqual((status, steps, issued, exact, commits),
                         (K.COMPLETED, str(self.whole), I.RESTORED, 'True', str(self.whole+1)))
        self.assertEqual(state_id, final.state_id)                           # exactly the uninterrupted state
        # Reopened here, every commit restores: geometry recomputed, rows applied again, identities reproduced.
        store = F2.store(self.path)
        self.addCleanup(store.close)
        again = L.Ledger.open(store, ledger.ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
        chain = again.chain()
        self.assertEqual(again.verify_chain().key, chain[-1].key)
        restored = again.sphere(chain[-1])
        self.assertEqual((restored.state_id, restored.issued_by), (final.state_id, I.RESTORED))
        self.assertEqual(restored.material.stock.tobytes(), final.material.stock.tobytes())
        self.assertEqual(restored.network.vertex_direction.tobytes(), final.network.vertex_direction.tobytes())
        self.assertEqual(again.sphere(chain[self.saved]).state_id, middle.state_id)
        self.assertEqual(restored.material.cohorts, final.material.cohorts)   # birth intervals survive the reopen
        self.assertEqual(restored.material.supplied(), final.material.supplied())
        self.assertEqual(again.state(chain[-1]).column.accepted_steps, self.whole)

    def stored(self, change, commit_index, transfers=None):
        """A reopened ledger whose stored commit ``commit_index`` had ``change(metadata, arrays)`` applied."""
        path = Path(tempfile.mkdtemp(dir=self.folder))/'ledger.sqlite'
        first = F2.store(path)
        ledger, root = L.Ledger.create(first, F2.root(STEPS, prepared=FIX['prepared']), sphere=F.crust(world()))
        if transfers is None:
            self.run_steps(ledger, 0, self.saved)
        else:
            outcome = advance(K.Clock(ledger), steps=len(transfers), transfers=transfers)
            self.assertEqual(outcome.status, K.COMPLETED, outcome.reason)
        chain = ledger.chain()
        target = chain[commit_index]
        snapshots = {c.key: (first.metadata(c.key), dict(first.get(c.key))) for c in chain}
        snapshots[target.key] = change(*snapshots[target.key])
        first.close()
        connection = sqlite3.connect(path)
        try:
            connection.execute('DELETE FROM snapshots')
            connection.commit()
        finally:
            connection.close()
        store = F2.store(path)
        self.addCleanup(store.close)
        for key, (metadata, arrays) in snapshots.items():
            store.put(key, arrays, metadata)
        again = L.Ledger.open(store, ledger.ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
        return again, target

    def test_an_unchanged_rewrite_still_restores(self):
        for index in (2, self.saved):
            again, target = self.stored(lambda metadata, arrays: (metadata, arrays), index)
            self.assertEqual(again.sphere(again.chain()[index]).step, index)
            again.verify_chain()

    def refused(self, change):
        # Inside the chain the next commit's parent digest also notices an edited record; at the head only the
        # network's own restoration can. Both must refuse.
        for index in (2, self.saved):
            with self.subTest(commit=index):
                try:
                    again, target = self.stored(change, index)
                    commit = again.chain()[index]
                except L.LedgerError:
                    continue                                                 # the chain itself no longer links
                with self.assertRaises(L.LedgerError):
                    again.sphere(commit)
                with self.assertRaises(L.LedgerError):
                    again.verify_chain()

    def test_an_edited_piece_account_is_refused(self):
        def change(metadata, arrays):
            stock = np.array(arrays['sphere.piece_stock'])
            stock[0, 1] *= self.factors['piece']
            return metadata, dict(arrays, **{'sphere.piece_stock': stock})
        self.refused(change)

    def test_an_edited_vertex_is_refused(self):
        def change(metadata, arrays):
            points = np.array(arrays['sphere.vertex_reference'])
            points[5] = F.direction(*self.factors['vertex_deg'])
            return metadata, dict(arrays, **{'sphere.vertex_reference': points})
        self.refused(change)

    def test_an_edited_overlap_row_is_refused(self):
        def change(metadata, arrays):
            area = np.array(arrays['sphere.map_area_m2'])
            area[-1] *= self.factors['row']
            return metadata, dict(arrays, **{'sphere.map_area_m2': area})
        self.refused(change)

    def test_an_edited_motion_record_is_refused(self):
        def change(metadata, arrays):
            metadata['sphere']['motion']['rotations'][0][1] = list(F.spin(self.factors['motion_deg']).quaternion)
            return metadata, arrays
        self.refused(change)

    def test_the_recorded_mesh_identity_is_bound_to_the_stored_mesh(self):
        # Another mesh identity written into the record, with the motion and map identities recomputed to match:
        # the stored endpoint is still the mesh that was applied, and it is not the one the record now names.
        start = F.crust(world())
        faces = {face.face_id: face for face in start.network.faces}
        for name in COMMIT['mesh_merge']:
            del faces[name]
        faces['s00-merged'] = S.Face('s00-merged', 'C', (F.vertex(0, 1), F.vertex(1, 1), F.vertex(1, 2),
                                                           F.vertex(1, 3), F.vertex(0, 3), F.vertex(0, 2)))
        still = T.Motion(0, 1, {plate: F.IDENTITY for plate in 'ABC'}, mesh=T.Mesh(tuple(faces.values())))
        canon = lambda value: json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'),
                                         allow_nan=False).encode()

        def change(metadata, arrays):
            record = metadata['sphere']
            record['motion']['mesh_id'] = 'ef'*32
            body = {key: value for key, value in record['motion'].items() if key != 'motion_id'}
            renamed = hashlib.sha256(canon(body)).hexdigest()
            record['motion']['motion_id'] = record['motion_id'] = renamed
            described = record['map']
            digest = hashlib.sha256(canon(dict(
                schema=T.MAP_SCHEMA, parent_geometry_id=described['parent_geometry_id'],
                moved_geometry_id=described['moved_geometry_id'],
                endpoint_geometry_id=described['endpoint_geometry_id'], motion_id=renamed,
                parties=described['parties'])))
            for name in sorted(n for n in arrays if n.startswith(('sphere.map_', 'sphere.remap_'))):
                array = np.asarray(arrays[name])
                digest.update(b'\0'+canon([name, array.dtype.str, list(array.shape)]))
                digest.update(array.tobytes())
            described['map_id'] = digest.hexdigest()
            return metadata, arrays

        unchanged, _ = self.stored(lambda metadata, arrays: (metadata, arrays), 1, (still,))
        self.assertEqual(unchanged.sphere(unchanged.verify_chain()).step, 1)
        again, _ = self.stored(change, 1, (still,))
        with self.assertRaises(L.LedgerError):
            again.sphere(again.chain()[1])
        with self.assertRaises(L.LedgerError):
            again.verify_chain()

    def test_a_step_record_moved_onto_another_parent_is_refused(self):
        def change(metadata, arrays):
            metadata['sphere']['parent_state_id'] = '0'*64
            return metadata, arrays
        self.refused(change)


if __name__ == '__main__':
    unittest.main()
