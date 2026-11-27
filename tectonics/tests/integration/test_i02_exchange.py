"""Focused I02.3 checks: the real column's accepted state and finite exchanges committed together, exactly once.

A two-reservoir, two-component stock with signed enthalpy is attached to the declared layered column. Commits must
conserve every component and signed enthalpy against named exteriors, apply each transfer once, replay identically
without a second row, refuse changed replays and stale parents (two connections and two racing processes), and roll
back completely when a proposal, the store, the parent check or a cancellation fails. Nothing here restores from disk.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
import dataclasses
import hashlib
import json
import math
import os
import pickle
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np
from threadpoolctl import threadpool_limits

import atlas_tectonics
from atlas_tectonics.integration import ledger as L, state as I
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.codecs.storage import StoreError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tests.fixtures.i02_workflow_fixtures as F

EXTERIORS = (('inflow', 'source'), ('outflow', 'sink'))
FIX = {}


def setUpModule():
    with threadpool_limits(limits=1, user_api='blas'):
        FIX['prepared'] = F.preparation()


def transfer(label, donor, receiver, a, b, enthalpy, **changes):
    values = dict(label=label, producer='tests/integration/test_i02_exchange.py', donor=donor, receiver=receiver,
                  component_mass_kg={'A': a, 'B': b}, enthalpy_j=enthalpy, basis=F.BASIS, start_step=0, end_step=1)
    values.update(changes)
    return L.Transfer(**values)


def counts(store):
    stats = store.statistics()
    return stats['snapshots'], stats['unique_chunks']


class Limited(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api='blas')
        self.addCleanup(lease.restore_original_limits)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.path = self.folder/'ledger'/'ledger.sqlite'
        self.state = F.root(stocks=F.reservoirs(), basis=F.BASIS, prepared=FIX['prepared'])
        self.store = F.store(self.path)
        self.addCleanup(self.store.close)
        self.ledger, self.root = L.Ledger.create(self.store, self.state, exteriors=EXTERIORS)
        self.run = I.Continuation(self.state)

    def step(self, state, steps=1):
        outcome = self.run.advance(state, steps)
        self.assertEqual(outcome.accepted_steps, steps)
        return outcome.state

    def stocks(self, commit):
        inventory = self.ledger.exchange(commit).inventory
        return np.array(inventory.component_mass_kg), np.array(inventory.enthalpy_j)


class ExchangeTests(Limited):
    def test_two_reservoir_multicomponent_transfer_debits_and_credits_once(self):
        s1 = self.step(self.state)
        move = transfer('move-1', 'store-a', 'store-b', 1.5, .25, -1.25)
        c1 = self.ledger.commit(self.root, (s1,), (move,))
        mass, energy = self.stocks(c1)
        np.testing.assert_array_equal(mass, [[3.5, 1.75], [2.5, .75]])
        np.testing.assert_array_equal(energy, [-1.75, 2.75])            # signed: a negative quantity moved
        exchange = self.ledger.exchange(c1)
        closure = exchange.closure()
        self.assertEqual((closure['component_residual_kg'], closure['enthalpy_residual_j'], closure['identity_exact']),
                         ([0., 0.], 0., True))
        self.assertEqual((exchange.initial_kg, exchange.initial_j), ((6., 2.5), 1.))
        # Every participant describes the same accepted parent and interval.
        self.assertEqual(c1.interval, (self.root.time_s, s1.time_s, 0, 1))
        self.assertEqual((c1.state_id, c1.accepted_steps, c1.sequence), (s1.state_id, 1, 1))
        self.assertEqual(exchange.inventory.time_s, s1.time_s)
        self.assertEqual(self.ledger.exchange(self.root).inventory.time_s, self.state.time_s)
        # The transfer record binds ledger, parent, interval, producer, label, ends, quantities, basis and units.
        record = c1.metadata()['transfers'][0]
        body = {k: v for k, v in record.items() if k != 'transfer_id'}
        self.assertEqual(record['transfer_id'], hashlib.sha256(L._json(body)).hexdigest())
        self.assertEqual((record['parent_key'], record['interval']['end_step'], record['units']),
                         (self.root.key, 1, L.UNITS))
        self.assertEqual(c1.transfer_ids, (record['transfer_id'],))
        # The same transaction stored the column state and the stocks: the manifest names both.
        stored = self.store.get(c1.key)
        np.testing.assert_array_equal(stored['exchange.component_mass_kg'], mass)
        self.assertEqual(stored['column.theta_k'].tobytes(), s1.column.theta_k.tobytes())
        self.assertEqual(self.ledger.head().key, c1.key)
        # The envelope keeps its initial stocks as its declared initial payload, as it keeps theta0.
        self.assertIs(s1.reservoirs, self.state.reservoirs)

    def test_named_exteriors_close_every_component_and_signed_enthalpy(self):
        s1 = self.step(self.state)
        s2 = self.step(s1)
        inflow = transfer('in-1', 'inflow', 'store-b', 2., 0., -7.5)
        outflow = transfer('out-1', 'store-a', 'outflow', 1., 1., 2.)
        within = transfer('mix-1', 'store-b', 'store-a', .5, .25, 1e-3, start_step=1, end_step=2)
        c1 = self.ledger.commit(self.root, (s1,), (inflow, outflow))
        c2 = self.ledger.commit(c1, (s2,), (within,))
        exchange = self.ledger.exchange(c2)
        np.testing.assert_array_equal(exchange.supplied_kg, [[2., 0.], [-1., -1.]])
        np.testing.assert_array_equal(exchange.supplied_j, [-7.5, -2.])
        closure = exchange.closure()
        self.assertEqual(closure['component_residual_kg'], [0., 0.])
        self.assertLess(abs(closure['enthalpy_residual_j']), 1e-12)
        self.assertTrue(closure['identity_exact'])
        mass, energy = self.stocks(c2)
        np.testing.assert_array_equal(mass, [[4.5, 1.25], [2.5, .25]])
        self.assertEqual(float(energy.sum()), 1.-7.5-2.)
        self.assertEqual(exchange.exteriors, (('inflow', 'source'), ('outflow', 'sink')))

    def test_identical_replay_is_idempotent_and_changed_replay_refuses(self):
        s1 = self.step(self.state)
        move = transfer('move-1', 'store-a', 'store-b', 1., 0., 0.)
        c1 = self.ledger.commit(self.root, (s1,), (move,))
        before = counts(self.store)
        again = self.ledger.commit(self.root, (s1,), (transfer('move-1', 'store-a', 'store-b', 1., 0., 0.),))
        self.assertEqual((again.key, again.transfer_ids, again._metadata), (c1.key, c1.transfer_ids, c1._metadata))
        self.assertEqual(counts(self.store), before)                   # no second row: applied exactly once
        mass, _ = self.stocks(c1)
        np.testing.assert_array_equal(mass, [[4., 2.], [2., .5]])
        self.assertEqual(self.ledger.head().key, c1.key)

    def test_stale_parent_refuses_across_connections(self):
        other_store = F.store(self.path)
        self.addCleanup(other_store.close)
        other, other_root = L.Ledger.create(other_store, self.state, exteriors=EXTERIORS)
        self.assertEqual((other.ledger_id, other_root.key), (self.ledger.ledger_id, self.root.key))
        s1 = self.step(self.state)
        c1 = self.ledger.commit(self.root, (s1,), (transfer('ours', 'store-a', 'store-b', 1., 0., 0.),))
        self.assertEqual(other.head().key, c1.key)

    def test_racing_processes_publish_exactly_one_successor(self):
        script = r"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import tests.fixtures.i02_workflow_fixtures as F
from atlas_tectonics.integration import ledger as L, state as I
path, label, go = Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
state = F.root(stocks=F.reservoirs(), basis=F.BASIS)
store = F.store(path)
ledger, root = L.Ledger.create(store, state, exteriors=(('inflow', 'source'), ('outflow', 'sink')))
s1 = I.Continuation(state).advance(state, 1).state
move = L.Transfer(label=label, producer='racer', donor='store-a', receiver='store-b',
                  component_mass_kg={'A': 1., 'B': 0.}, enthalpy_j=0., basis=F.BASIS, start_step=0, end_step=1)
while not go.exists():
    time.sleep(0.005)
try:
    commit = ledger.commit(root, (s1,), (move,))
    print(json.dumps(dict(outcome='committed', key=commit.key)))
except L.LedgerConflict as exc:
    print(json.dumps(dict(outcome='conflict', reason=str(exc))))
store.close()
"""
        go = self.folder/'go'
        tectonics = Path(__file__).resolve().parents[2]
        native = Path(atlas_tectonics.__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(native), str(tectonics.parent/'shared/src'))))
        children = [subprocess.Popen([sys.executable, '-B', '-c', script, str(tectonics),
                                      str(self.path), label, str(go)], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, env=env) for label in ('racer-a', 'racer-b')]
        go.write_text('go')
        outcomes = []
        for child in children:
            out, err = child.communicate(timeout=120)
            self.assertEqual(child.returncode, 0, err)
            outcomes.append(json.loads(out.strip().splitlines()[-1]))
        self.assertEqual(sorted(o['outcome'] for o in outcomes), ['committed', 'conflict'])
        head = self.ledger.head()
        self.assertEqual(head.sequence, 1)
        self.assertEqual(head.key, next(o['key'] for o in outcomes if o['outcome'] == 'committed'))
        self.assertEqual(self.store.statistics()['snapshots'], 2)       # the root and one successor, never both


class RollbackTests(Limited):
    def assert_untouched(self, before):
        self.assertEqual(counts(self.store), before)
        self.assertEqual(self.ledger.head().key, self.root.key)

    def test_failure_before_commit_publishes_nothing(self):
        s1 = self.step(self.state)
        before = counts(self.store)
        moves = (transfer('m1', 'store-a', 'store-b', 1., 1., -2.), transfer('m2', 'inflow', 'store-a', 3., 0., 1.))
        real = self.store.metadata

        def failing(key):
            if self.store._db.in_transaction:          # the ledger's in-transaction parent check
                raise RuntimeError('injected failure after every row was written, before COMMIT')
            return real(key)
        self.store.metadata = failing
        try:
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                self.ledger.commit(self.root, (s1,), moves)
        finally:
            del self.store.metadata
        self.assert_untouched(before)
        commit = self.ledger.commit(self.root, (s1,), moves)          # the same proposal then commits normally
        self.assertEqual(commit.sequence, 1)

    def test_failure_between_chunk_batches_rolls_back(self):
        store = F.store(self.folder/'small'/'ledger.sqlite', chunk_bytes=64, insert_batch_bytes=64)
        self.addCleanup(store.close)
        ledger, root = L.Ledger.create(store, self.state, exteriors=EXTERIORS)
        before = counts(store)
        real = store._db

        class Failing:
            calls = 0

            def __getattr__(self, name):
                return getattr(real, name)

            def executemany(self, *args):
                Failing.calls += 1
                if Failing.calls == 2:
                    raise sqlite3.OperationalError('injected failure between chunk batches')
                return real.executemany(*args)
        store._db = Failing()
        s1 = self.step(self.state)
        try:
            with self.assertRaises(StoreError):
                ledger.commit(root, (s1,), (transfer('m1', 'store-a', 'store-b', 1., 0., 0.),))
        finally:
            store._db = real
        self.assertEqual(Failing.calls, 2)
        self.assertEqual(counts(store), before)
        self.assertEqual(ledger.head().key, root.key)
        self.assertEqual(ledger.commit(root, (s1,), (transfer('m1', 'store-a', 'store-b', 1., 0., 0.),)).sequence, 1)

    def test_cancellation_and_refused_proposals_publish_nothing(self):
        s1 = self.step(self.state)
        before = counts(self.store)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(CancelledError):
            self.ledger.commit(self.root, (s1,), (transfer('m1', 'store-a', 'store-b', 1., 0., 0.),), cancel=cancel)
        self.assert_untouched(before)
        good = transfer('ok', 'store-a', 'store-b', 1., 0., 0.)
        refused = {
            'finite availability of a later component': (good, transfer('greedy', 'store-b', 'store-a', 0., .5000001, 0.)),
            'empty stock left holding enthalpy': (transfer('empty', 'store-b', 'store-a', 1., .5, 3.),),
            'column cohort is not an exchange support': (
                transfer('cohort', self.state.layer_cohorts[0], 'store-b', 1., 0., 0.),),
            'unknown receiver': (transfer('nowhere', 'store-a', 'store-z', 1., 0., 0.),),
            'untyped proposal': (dict(label='raw'),),
        }
        for name, proposal in refused.items():
            with self.subTest(name), self.assertRaises(TectonicsError):
                self.ledger.commit(self.root, (s1,), proposal)
            self.assert_untouched(before)
        mass, energy = self.stocks(self.root)
        np.testing.assert_array_equal(mass, [[5., 2.], [1., .5]])
        np.testing.assert_array_equal(energy, [-3., 4.])

    def test_proposals_are_owned_and_refuse_incompatible_units(self):
        masses = np.array([1., .5])
        move = L.Transfer(label='own', producer='p', donor='store-a', receiver='store-b',
                          component_mass_kg=(('B', masses[1]), ('A', masses[0])), enthalpy_j=np.float64(-1.),
                          basis=F.BASIS, start_step=0, end_step=1)
        masses[:] = 99.                                                # caller edits after submission
        self.assertEqual(move.component_mass_kg, (('A', 1.), ('B', .5)))
        self.assertEqual(dataclasses.replace(move, enthalpy_j=2.).enthalpy_j, 2.)
        with self.assertRaises(TypeError):
            L.Transfer(label='own', producer='p', donor='store-a', receiver='store-b',
                       component_mass_kg={'A': 1., 'B': 0.}, enthalpy_j=0., basis=F.BASIS)    # no declared interval
        s1 = self.step(self.state)
        commit = self.ledger.commit(self.root, (s1,), (move,))
        mass, _ = self.stocks(commit)
        np.testing.assert_array_equal(mass, [[4., 1.5], [2., 1.]])
        with self.assertRaises(ValueError):
            self.ledger.exchange(commit).inventory.component_mass_kg[0, 0] = 0.
        with self.assertRaises(ValueError):
            self.ledger.exchange(commit).supplied_kg[...] = 1.


class ContractTests(Limited):
    def test_commits_accept_only_whole_steps_continuing_the_parent(self):
        s1 = self.step(self.state)
        s3 = self.step(s1, 2)
        other = F.root(stocks=F.reservoirs(), basis=F.BASIS, prepared=FIX['prepared'], scenario='another-scenario')
        foreign = I.Continuation(other).advance(other, 1).state
        refused = {
            'a gap': (s3,),
            'out of order': (s3, s1),
            'another history': (foreign,),
        }
        for name, path in refused.items():
            with self.subTest(name), self.assertRaises(TectonicsError):
                self.ledger.commit(self.root, path)
        commit = self.ledger.commit(self.root, (s1, s3))                # two pieces, three whole steps
        self.assertEqual((commit.interval[2:], commit.metadata()['path']),
                         ((0, 3), [[s1.state_id, 1], [s3.state_id, 3]]))
        with self.assertRaises(TectonicsError):
            self.ledger.commit(commit, (s3,))

    def test_only_a_declared_initial_state_roots_a_ledger(self):
        closed = F.root(prepared=FIX['prepared'])
        ledger, root = L.Ledger.create(self.store, closed)             # a closed strip: no exchange accounts
        self.assertIsNone(ledger.exchange(root))
        c1 = ledger.commit(root, (I.Continuation(closed).advance(closed, 1).state,))
        self.assertIsNone(ledger.exchange(c1))
        with self.assertRaisesRegex(L.LedgerError, 'transfers nothing'):
            ledger.commit(c1, (I.Continuation(closed).advance(ledger.state(c1), 1).state,),
                          (transfer('x', 'store-a', 'store-b', 1., 0., 0.),))
        with self.assertRaises(TypeError):
            L.Ledger()



class AccountingTests(Limited):
    """Regressions for the first candidate's review: exactness, resolution, range, tokens and authenticity."""

    def exact(self, commit):
        return self.ledger.exchange(commit).descriptor()['exact']

    def test_large_flows_cannot_absorb_small_stocks_or_exterior_amounts(self):
        s1 = self.step(self.state)
        s2 = self.step(s1)
        through = (transfer('big-in', 'inflow', 'store-a', 1e17, 0., 1e17),
                   transfer('big-out', 'store-a', 'outflow', 1e17, 0., 1e17))
        c1 = self.ledger.commit(self.root, (s1,), through)
        mass, energy = self.stocks(c1)
        np.testing.assert_array_equal(mass, [[5., 2.], [1., .5]])        # the 5 kg stock is not absorbed
        np.testing.assert_array_equal(energy, [-3., 4.])
        c2 = self.ledger.commit(c1, (s2,), (transfer('small-in', 'inflow', 'store-a', 5., 0., 0., start_step=1,
                                                     end_step=2),))
        mass, _ = self.stocks(c2)
        np.testing.assert_array_equal(mass[0], [10., 2.])
        closure = self.ledger.exchange(c2).closure()
        self.assertEqual((closure['component_residual_kg'], closure['enthalpy_residual_j'], closure['identity_exact']),
                         ([0., 0.], 0., True))
        exact = self.exact(c2)
        self.assertEqual(exact['supplied_kg'][0][0], '100000000000000005/1')     # the exterior keeps the 5 kg
        self.assertEqual(exact['supplied_kg'][1][0], '-100000000000000000/1')

    def test_changes_below_a_stock_resolution_refuse_and_rounding_is_an_exact_account(self):
        big = F.root(stocks=F.reservoirs(component_mass_kg=[[5., 2.], [1e20, .5]]), basis=F.BASIS,
                     prepared=FIX['prepared'])
        store = F.store(self.folder/'big'/'ledger.sqlite')
        self.addCleanup(store.close)
        ledger, root = L.Ledger.create(store, big, exteriors=EXTERIORS)
        s1 = I.Continuation(big).advance(big, 1).state
        batch = tuple(transfer('in-%d' % i, 'inflow', 'store-b', 5000., 0., 0.) for i in range(64))
        commit = ledger.commit(root, (s1,), batch)                          # 320 t as one exact change: booked
        exchange = ledger.exchange(commit)
        stored = float(exchange.inventory.component_mass_kg[1, 0])
        self.assertNotEqual(stored, 1e20)
        closure = exchange.closure()
        self.assertTrue(closure['identity_exact'])
        self.assertEqual(closure['component_residual_kg'][0], exchange.rounding_kg[0])
        self.assertLessEqual(abs(exchange.rounding_kg[0]), math.ulp(stored)/2)
        # Only a value a commit changes is rounded, so only it widens the allowance: moving B leaves A's alone.
        s2 = I.Continuation(big).advance(s1, 1).state
        b_only = transfer('b-only', 'inflow', 'store-b', 0., .25, 0., start_step=1, end_step=2)
        moved = ledger.exchange(ledger.commit(commit, (s2,), (b_only,)))
        self.assertEqual((moved.allowance_kg[0], moved.allowance_j), (exchange.allowance_kg[0], exchange.allowance_j))
        self.assertGreater(moved.allowance_kg[1], exchange.allowance_kg[1])
        self.assertTrue(moved.closure()['identity_exact'])

    def test_quantities_outside_the_finite_accounting_range_refuse(self):
        for change in (dict(component_mass_kg={'A': 4.5e307, 'B': 0.}), dict(enthalpy_j=4.5e307),
                       dict(enthalpy_j=-4.5e307, component_mass_kg={'A': 1., 'B': 0.})):
            with self.subTest(change), self.assertRaises(TectonicsError):
                transfer('huge', 'inflow', 'store-a', 1., 0., 1., **change)

    def test_proposals_are_validated_again_when_used(self):
        good = transfer('p-1', 'store-a', 'store-b', 1., 0., 0.)
        self.assertEqual(pickle.loads(pickle.dumps(good)), good)
        forged = pickle.loads(pickle.dumps(good))
        object.__setattr__(forged, 'component_mass_kg', (('A', -3.), ('B', .1)))
        s1 = self.step(self.state)
        with self.assertRaises(TectonicsError):
            self.ledger.commit(self.root, (s1,), (forged,))
        self.assertEqual(self.ledger.head().key, self.root.key)
        self.assertEqual(self.ledger.commit(self.root, (s1,), (pickle.loads(pickle.dumps(good)),)).sequence, 1)

    def test_malformed_successor_rows_refuse_as_ledger_errors(self):
        key = L.successor_key(self.ledger.ledger_id, self.root.key)
        self.store.put(key, {'x': np.zeros(1)}, dict(schema=L.SCHEMA, kind='successor', state='not-a-state'))
        with self.assertRaisesRegex(L.LedgerError, 'well-formed'):
            self.ledger.head()

    def test_a_transfer_commits_only_over_the_interval_it_declares(self):
        s1 = self.step(self.state)
        s2 = self.step(s1)
        whole = transfer('m', 'store-a', 'store-b', 1., 0., 0., start_step=0, end_step=2)
        commit = self.ledger.commit(self.root, (s1, s2), (whole,))              # the commit spanning (0, 2]
        record = commit.metadata()['transfers'][0]
        self.assertEqual((record['parent_key'], record['interval']['start_step'], record['interval']['end_step']),
                         (self.root.key, 0, 2))                                  # the parent is the commit at 0
        self.assertNotEqual(whole, dataclasses.replace(whole, start_step=1))     # the interval is proposal content

    def test_a_stored_transfer_that_no_longer_applies_is_not_a_refused_exchange(self):
        s1 = self.step(self.state)
        c1 = self.ledger.commit(self.root, (s1,), (transfer('m1', 'store-a', 'store-b', 1., 0., 0.),))
        other = F.store(self.path)
        self.addCleanup(other.close)
        reopened = L.Ledger.open(other, self.ledger.ledger_id, source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)

        def refusing(*args, **kwargs):
            raise L.ExchangeRefused('finite availability: the donor stock holds less than the transfer')
        with mock.patch.object(L, '_apply', refusing), self.assertRaises(L.LedgerError) as caught:
            reopened.exchange(c1)                                  # the replay of a stored record, not a proposal
        self.assertNotIsInstance(caught.exception, L.ExchangeRefused)
        self.assertIn('stored transfer record no longer applies', str(caught.exception))

        def invalid(*args, **kwargs):
            raise TectonicsError('transfer masses are nonnegative')
        with mock.patch.object(L, 'Transfer', invalid), self.assertRaises(L.LedgerError) as caught:
            reopened.exchange(c1)                                  # a stored record that is not a valid transfer
        self.assertIn('not a valid transfer', str(caught.exception))

    def test_heat_only_transfers_flow_from_donor_to_receiver(self):
        s1 = self.step(self.state)
        c1 = self.ledger.commit(self.root, (s1,), (transfer('heat-out', 'store-a', 'outflow', 0., 0., 1000.),))
        _, energy = self.stocks(c1)
        self.assertEqual(float(energy[0]), -1003.)
        self.assertEqual(float(self.ledger.exchange(c1).supplied_j[1]), -1000.)


class PublicationTests(Limited):
    """Review round 5: nothing is read after a successor is published, and the checked chain a ledger reuses never
    hides a write made straight after one of its own commits."""

    def test_a_published_commit_returns_even_if_the_store_is_locked_straight_after(self):
        from unittest import mock
        import time
        real_put, blockers = self.store.put, []
        self.addCleanup(lambda: [blocker.close() for blocker in blockers])

        def put_then_locked(*args, **kwargs):
            result = real_put(*args, **kwargs)
            other = sqlite3.connect(self.path, timeout=0, isolation_level=None)
            other.execute('BEGIN EXCLUSIVE')           # another connection takes the file right after COMMIT
            blockers.append(other)
            return result
        s1 = self.step(self.state)
        started = time.perf_counter()
        with mock.patch.object(self.store, 'put', put_then_locked):
            commit = self.ledger.commit(self.root, (s1,))
        self.assertLess(time.perf_counter()-started, 3.)  # no read after publication could wait or fail
        blockers[0].execute('ROLLBACK')
        self.assertEqual(self.ledger.head().key, commit.key)

    def test_a_commit_by_another_ledger_object_straight_after_is_seen_by_the_next_read(self):
        from unittest import mock
        s1 = self.step(self.state)
        s2 = self.step(s1)
        other = L.Ledger.open(self.store, self.ledger.ledger_id, source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)
        self.ledger.head()                             # the checked chain is now reused while nothing is written
        real_put, done = self.store.put, []

        def put_then_other(*args, **kwargs):
            result = real_put(*args, **kwargs)
            if not done:
                done.append(1)
                other.commit(other.head(), (s2,))      # the same connection writes before the caller reads again
            return result
        with mock.patch.object(self.store, 'put', put_then_other):
            self.ledger.commit(self.root, (s1,))
        self.assertEqual((self.ledger.head().sequence, other.head().sequence), (2, 2))


if __name__ == '__main__':
    unittest.main()
