"""Focused I02.5 checks: save, reopen and continue the real column's accepted state, losslessly and atomically.

A reopened ledger must rebuild every commit's state and stocks from the store through the validating constructors and
the package restorer, reproducing each identity bit for bit, and refuse a changed source or runtime identity or an
edited record. A fresh process must continue the partly completed history to the uninterrupted result within the
retained parity without re-running its accepted prefix. A writer killed before, inside or after its commit must leave
the old complete head or the new complete head, never a mixture. Finite admission is issued for a restored commit only
through the engine's restoration; inspection reads metadata and single fields without running physics.
SPDX-License-Identifier: AGPL-3.0-only
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import numpy as np
from threadpoolctl import threadpool_limits

import atlas_tectonics
from atlas_tectonics import integration_clock as K, integration_evolution as E, integration_ledger as L
from atlas_tectonics import integration_state as I
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.storage import StoreError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent/'tools'))
import i02_workflow_fixtures as F
import check_i01_finite_admission as fa

FIX = {}
STEPS = 16
EXTERIORS = (('inflow', 'source'), ('outflow', 'sink'))
SRC = str(Path(atlas_tectonics.__file__).resolve().parents[1])
PARITY = F.POLICY['parity_relative']            # the retained warm/cold comparator allowance


def setUpModule():
    with threadpool_limits(limits=1, user_api='blas'):
        FIX['prepared'] = F.preparation()
        state = F.root(STEPS, prepared=FIX['prepared'], stocks=F.reservoirs(), basis=F.BASIS)
        FIX['root'], FIX['whole'] = state, I.Continuation(state).advance(state, STEPS).state


def near(value, reference, relative=PARITY):
    value, reference = np.asarray(value, dtype=float), np.asarray(reference, dtype=float)
    return float(np.abs(value-reference).max()) <= relative*max(float(np.abs(reference).max()), 1e-300)


def child(script, *args, timeout=240):
    env = dict(os.environ, PYTHONPATH=SRC)
    done = subprocess.run([sys.executable, '-B', '-c', script, str(HERE), *map(str, args)], capture_output=True,
                          text=True, env=env, timeout=timeout)
    return done


class Limited(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api='blas')
        self.addCleanup(lease.restore_original_limits)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.path = self.folder/'ledger'/'ledger.sqlite'

    def build(self, steps=6, **store):
        """The partly completed real history: clock commits at steps 2, 3 (with two transfers), 4 and 6."""
        s = F.store(self.path, **store)
        ledger, root = L.Ledger.create(s, FIX['root'], exteriors=EXTERIORS)
        moves = (L.Transfer(label='in', producer='test', donor='inflow', receiver='store-a',
                            component_mass_kg={'A': 1.25, 'B': .5}, enthalpy_j=-2.5, basis=F.BASIS, start_step=2,
                            end_step=3),
                 L.Transfer(label='mix', producer='test', donor='store-b', receiver='store-a',
                            component_mass_kg={'A': .5, 'B': 0.}, enthalpy_j=1.5, basis=F.BASIS, start_step=2,
                            end_step=3))
        outcome = K.Clock(ledger).advance(steps=steps, savepoint_steps=2, transfers=moves)
        self.assertEqual([c.accepted_steps for c in outcome.commits], [2, 3, 4, 6][:len(outcome.commits)])
        self.assertEqual(len(outcome.commits[1].transfer_ids), 2)
        return s, ledger

    def reopen(self, **changes):
        s = F.store(self.path)
        self.addCleanup(s.close)
        values = dict(source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)
        values.update(changes)
        return s, L.Ledger.open(s, FIX['ledger_id'], **values)


class RestoreTests(Limited):
    def test_reopened_commits_reproduce_every_identity_and_array(self):
        s, ledger = self.build()
        FIX['ledger_id'] = ledger.ledger_id
        chain, commit = [], ledger.root
        while True:
            chain.append((commit, ledger.state(commit), ledger.exchange(commit)))
            nxt = s.metadata(L.successor_key(ledger.ledger_id, commit.key))
            if nxt is None:
                break
            commit = ledger._checked(nxt, commit)
        s.close()
        again, reopened = self.reopen()
        head = reopened.head()
        self.assertEqual((head.key, head._metadata), (chain[-1][0].key, chain[-1][0]._metadata))
        walk = reopened.root
        for commit, state, exchange in chain:
            with self.subTest(sequence=commit.sequence):
                if commit.sequence:
                    walk = reopened._checked(again.metadata(L.successor_key(reopened.ledger_id, walk.key)), walk)
                self.assertEqual((walk.key, walk._metadata), (commit.key, commit._metadata))
                restored, stocks = reopened.state(walk), reopened.exchange(walk)
                self.assertIsNot(restored, state)
                self.assertEqual(restored.state_id, state.state_id)
                self.assertEqual(restored.identities(), state.identities())
                for name in ('theta_k', 'kappa', 'initial_theta_k', 'initial_kappa', 'yield_stage_counts'):
                    self.assertEqual(getattr(restored.column, name).tobytes(), getattr(state.column, name).tobytes())
                for (name, a), (_, b) in zip(restored.reference._arrays(), state.reference._arrays()):
                    self.assertEqual((name, a.tobytes()), (name, b.tobytes()))
                self.assertEqual(restored.column.accounts_j_m, state.column.accounts_j_m)
                self.assertEqual((stocks.exchange_id, stocks.inventory.inventory_id),
                                 (exchange.exchange_id, exchange.inventory.inventory_id))
        self.assertEqual(reopened.verify(head).key, head.key)
        # Unchanged reference, initial history and material payloads are stored once and shared by every commit.
        stats = again.statistics()
        self.assertEqual(stats['snapshots'], len(chain))
        names = set(again.get(head.key))
        self.assertEqual(names, {'column.theta_k', 'column.kappa', 'column.yield_stage_counts', *L.EXCHANGE_ARRAYS})

    def test_changed_identity_edited_records_and_foreign_ledgers_refuse(self):
        s, ledger = self.build()
        FIX['ledger_id'] = ledger.ledger_id
        head = ledger.head()
        s.close()
        for changes in (dict(source_id='0'*64), dict(runtime_id='1'*64)):
            with self.subTest(changes), self.assertRaisesRegex(L.LedgerError, 'not silently rebound'):
                self.reopen(**changes)
        store = F.store(self.path)
        self.addCleanup(store.close)
        with self.assertRaises(L.LedgerError):
            L.Ledger.open(store, '2'*64, source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)
        # Rewrite one committed account consistently with the store's own manifest checksum: the store accepts the
        # row, the restorer must not.
        raw = sqlite3.connect(self.path)
        body = json.loads(raw.execute('SELECT body FROM snapshots WHERE id=?', (head.key,)).fetchone()[0])
        accounts = body['metadata']['state']['column']['accounts_j_m']
        self.assertNotEqual(accounts['heat_j_m'], 0.)
        accounts['heat_j_m'] *= 1.5
        text = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        import hashlib
        raw.execute('UPDATE snapshots SET body=?, digest=? WHERE id=?', (text, hashlib.sha256(text).hexdigest(),
                                                                        head.key))
        raw.commit()
        raw.close()
        _, reopened = self.reopen()
        edited = reopened.head()
        with self.assertRaises(TectonicsError):
            reopened.state(edited)
        with self.assertRaises(TectonicsError):
            reopened.state(head)                           # the originally issued commit no longer matches its row

    def test_fresh_process_continues_to_the_uninterrupted_result(self):
        s, ledger = self.build(steps=6)
        FIX['ledger_id'] = ledger.ledger_id
        s.close()
        script = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from threadpoolctl import threadpool_limits
import i02_workflow_fixtures as F
from atlas_tectonics import integration_clock as K, integration_evolution as E, integration_ledger as L
calls, original = [], E.stage
def counted(*args, **kwargs):
    calls.append(args[3])
    return original(*args, **kwargs)
E.stage = counted
with threadpool_limits(limits=1, user_api='blas'):
    store = F.store(Path(sys.argv[2]))
    ledger = L.Ledger.open(store, sys.argv[3], source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)
    clock = K.Clock(ledger)
    start = clock.head.accepted_steps
    outcome = clock.advance(steps=%d-start, savepoint_steps=4)
    state = ledger.state(ledger.head())
print(json.dumps(dict(start=start, status=outcome.status, stages=len(calls), step=outcome.step,
                      theta=state.column.theta_k.tolist(), kappa=state.column.kappa.tolist(),
                      yields=state.column.yield_stage_counts.tolist(), accounts=state.column.accounts_j_m,
                      counters=state.column.counters, stretch=state.column.stretch,
                      displacement=state.column.displacement_m, clock=state.column.clock_s)))
store.close()
""" % STEPS
        done = child(script, self.path, ledger.ledger_id)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout.strip().splitlines()[-1])
        whole = FIX['whole'].column
        self.assertEqual((out['start'], out['status'], out['step']), (6, K.HISTORY_COMPLETE, STEPS))
        # One cold endpoint re-solve (operational, unbooked) plus two stages per remaining step: no prefix replay.
        self.assertEqual(out['stages'], 1+2*(STEPS-6))
        self.assertEqual(out['counters']['stages'], whole.counters['stages'])
        self.assertEqual(out['yields'], whole.yield_stage_counts.tolist())
        for name, reference in (('theta', whole.theta_k), ('kappa', whole.kappa)):
            self.assertTrue(near(out[name], reference), name)
        for name, reference in (('stretch', whole.stretch), ('displacement', whole.displacement_m),
                                ('clock', whole.clock_s)):
            self.assertLess(abs(out[name]-reference), PARITY*abs(reference), name)
        extensive = I.STAGE_ACCOUNTS+I.THERMAL_ACCOUNTS
        self.assertTrue(near([out['accounts'][n] for n in extensive], [whole.accounts_j_m[n] for n in extensive]))
        _, reopened = self.reopen()
        final = reopened.state(reopened.head())
        self.assertEqual(final.column.theta_k.tolist(), out['theta'])
        exchange = reopened.exchange(reopened.head())
        self.assertLess(max(map(abs, exchange.closure()['component_residual_kg'])), 1e-12)


class InterruptionTests(Limited):
    KILLER = r"""
import os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import i02_workflow_fixtures as F
from atlas_tectonics import integration_clock as K, integration_ledger as L
path, ledger_id, mode = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
store = F.store(path, sqlite_cache_bytes=1024)       # a tiny page cache: large changes spill before COMMIT
ledger = L.Ledger.open(store, ledger_id, source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)
clock = K.Clock(ledger)
if mode == 'inside':
    real = store.metadata
    def dying(key):
        if store._db.in_transaction:                   # every commit row written, journal live, COMMIT not reached
            # A further 4 MB in the same transaction overflows the page cache, so changed pages reach the database
            # file itself before the process dies; only the rollback journal can restore the old head.
            store._db.execute('INSERT INTO chunks VALUES(?,?,?,?,?)', ('f'*64, b'{}', 'raw', '0'*64, bytes(4 << 20)))
            print('spilled', path.stat().st_size, flush=True)
            os._exit(9)
        return real(key)
    store.metadata = dying
    clock.advance(steps=2)
elif mode == 'after':
    clock.advance(steps=2)
    os._exit(9)                                        # committed, then the process dies without closing
else:
    print('ready', flush=True)
    while True:
        clock.advance(steps=1)
        if clock.head.accepted_steps >= %d:
            clock = None
            break
"""

    def prepared(self):
        s, ledger = self.build(steps=6)
        FIX['ledger_id'] = ledger.ledger_id
        head = ledger.head()
        s.close()
        return head

    def check_complete(self, expected):
        store, reopened = self.reopen()
        head = reopened.head()
        self.assertIn(head.accepted_steps, expected)
        reopened.verify(head)
        commit = reopened.root
        while True:                                     # every commit on the chain restores completely
            reopened.state(commit)
            reopened.exchange(commit)
            nxt = store.metadata(L.successor_key(reopened.ledger_id, commit.key))
            if nxt is None:
                break
            commit = reopened._checked(nxt, commit)
        self.assertEqual(commit.key, head.key)
        self.assertEqual(store.statistics()['snapshots'], head.sequence+1)
        return head

    def test_killed_before_commit_leaves_the_old_head(self):
        before = self.prepared()
        size = self.path.stat().st_size
        done = child(self.KILLER % STEPS, self.path, FIX['ledger_id'], 'inside')
        self.assertEqual(done.returncode, 9, done.stderr)
        journal = Path(str(self.path)+'-journal')
        self.assertTrue(journal.exists())                         # a hot journal was left behind
        spilled = int(done.stdout.split()[-1])
        self.assertGreater(spilled, size+(4 << 20)//2)            # uncommitted pages had reached the database file
        head = self.check_complete({before.accepted_steps})
        self.assertEqual(head.key, before.key)
        self.assertFalse(journal.exists())                        # rolled back by the next connection
        self.assertEqual(self.path.stat().st_size, size)
        raw = sqlite3.connect(self.path)
        self.addCleanup(raw.close)
        self.assertIsNone(raw.execute('SELECT 1 FROM chunks WHERE id=?', ('f'*64,)).fetchone())
        self.assertEqual(raw.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_killed_after_commit_leaves_the_new_head(self):
        before = self.prepared()
        done = child(self.KILLER % STEPS, self.path, FIX['ledger_id'], 'after')
        self.assertEqual(done.returncode, 9, done.stderr)
        self.check_complete({before.accepted_steps+2})

    def test_killed_at_arbitrary_moments_exposes_old_or_new_complete_heads(self):
        before = self.prepared()
        env = dict(os.environ, PYTHONPATH=SRC)
        rng = random.Random(20260929)
        seen = set()
        for trial in range(4):
            process = subprocess.Popen([sys.executable, '-B', '-c', self.KILLER % STEPS, str(HERE), str(self.path),
                                        FIX['ledger_id'], 'loop'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, env=env)
            self.assertEqual(process.stdout.readline().strip(), 'ready')
            time.sleep(rng.uniform(0., .05))
            process.kill()
            process.communicate(timeout=60)
            head = self.check_complete(set(range(before.accepted_steps, STEPS+1)))
            self.assertGreaterEqual(head.accepted_steps, before.accepted_steps)
            seen.add(head.accepted_steps)
            before = head
        self.assertTrue(seen)


class AdmissionTests(Limited):
    def evolution(self, theta0=None):
        base, thermal, key, _ = FIX['prepared']
        kappa0 = np.asarray(F.WEAK['campaign']['initial_history_by_layer'], dtype=float)[base.layer]
        return fa.Evolution(base, thermal, F.LAW, F.DRIVE, key, kappa0, FIX['root'].settings.step_s,
                            dict(stretch=F.REP['stretch_window'], temperature_k=F.REP['temperature_window_k']),
                            F.REP['max_temperature_step_k'], (1., 1.), F.POLICY,
                            theta0=F.theta_signed(base) if theta0 is None else theta0)

    def test_every_package_module_restored_executes_is_bound_and_import_checked(self):
        s = F.store(self.path)
        self.addCleanup(s.close)
        ledger, _ = L.Ledger.create(s, FIX['root'], exteriors=EXTERIORS)
        K.Clock(ledger).advance(steps=2)
        other = F.store(self.path)
        self.addCleanup(other.close)
        evolution, package, executed = self.evolution(), Path(atlas_tectonics.__file__).resolve().parent, set()

        def hook(frame, event, arg):
            if event == 'call':
                path = Path(frame.f_code.co_filename).resolve()
                if path.parent == package:
                    executed.add('src/atlas_tectonics/'+path.name)
        sys.setprofile(hook)
        try:                             # restored() and the Ledger.open whose rebuilt root it relies on
            reopened = L.Ledger.open(other, ledger.ledger_id, source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)
            fa.restored(evolution, reopened, reopened.head())
        finally:
            sys.setprofile(None)
        self.assertIn('src/atlas_tectonics/integration_ledger.py', executed)
        self.assertLessEqual(executed, set(fa.RETAINED) | set(fa.RESTORATION))
        self.assertLessEqual(set(fa.RESTORATION), set(fa.IMPORTED))
        self.assertTrue(all(fa.evidence_match(fa.bindings())['imported'].values()))

    def test_restored_commits_are_admitted_only_through_the_engine(self):
        s = F.store(self.path)
        ledger, root = L.Ledger.create(s, FIX['root'], exteriors=EXTERIORS)
        K.Clock(ledger).advance(steps=4)
        FIX['ledger_id'] = ledger.ledger_id
        s.close()
        _, reopened = self.reopen()
        head = reopened.head()
        evolution = self.evolution()
        state = fa.restored(evolution, reopened, head)
        base, thermal, key, _ = FIX['prepared']
        _, direct = fa.evolved(evolution, 4)
        self.assertLess(abs(state.stretch-direct.stretch), PARITY*direct.stretch)
        self.assertEqual(state.elapsed_s, direct.elapsed_s)
        self.assertTrue(near(state.kappa, direct.kappa) and near(state.theta, direct.theta))
        spec = fa.load_case()[0]
        envelope = fa.prepare(base, thermal, F.LAW, F.DRIVE, key, state, window=fa.declared(spec),
                              horizon_s=spec['contract']['horizon_s'])
        result = fa.admit(envelope, base, thermal, F.LAW, F.DRIVE, state, duration_s=FIX['root'].settings.step_s,
                          relative_tolerance=spec['campaign']['relative_tolerances'][0],
                          displacement_limit_m=spec['campaign']['displacement_limit_m'])
        self.assertIn(result['status'], (fa.CERTIFIED, fa.NOT_CERTIFIED))
        self.assertEqual(result['window_start_s'], state.elapsed_s)
        # Nothing but an engine-restored commit of this evolution issues a state.
        other = F.root(STEPS, prepared=FIX['prepared'], scenario='another-scenario')
        s2 = F.store(self.folder/'other'/'ledger.sqlite')
        self.addCleanup(s2.close)
        foreign, _ = L.Ledger.create(s2, other)
        K.Clock(foreign).advance(steps=1)
        forged = L._issue(L.Commit, **{**{f: getattr(head, f) for f in ('ledger_id', 'parent_key', 'sequence',
                                                                         'state_id', 'time_s', 'elapsed_s',
                                                                         'accepted_steps', 'interval',
                                                                         'transfer_ids', '_metadata')},
                                       'key': '3'*64})
        refused = {
            'a common state': lambda: fa.restored(evolution, reopened, reopened.state(head)),
            'a fingerprint': lambda: fa.restored(evolution, reopened, head.state_id),
            'another ledger\'s commit': lambda: fa.restored(evolution, reopened, foreign.head()),
            'a forged commit': lambda: fa.restored(evolution, reopened, forged),
            'another evolution': lambda: fa.restored(self.evolution(theta0=np.zeros(base.size)), reopened, head),
            'a common state to prepare': lambda: fa.prepare(base, thermal, F.LAW, F.DRIVE, key, reopened.state(head),
                                                            window=fa.declared(spec),
                                                            horizon_s=spec['contract']['horizon_s']),
        }
        for name, fn in refused.items():
            with self.subTest(name), self.assertRaises(ValueError):
                fn()


class TrustBoundaryTests(Limited):
    """The store is trusted local state. A record appended through the public ArrayStore.put that is well-formed,
    well-linked, inside the admitted ranges and consistent with the retained step relations is restored, continued and
    admitted, whoever wrote it; restore() refuses records whose values contradict those relations."""
    evolution = AdmissionTests.evolution

    def genuine(self, steps=4):
        root = F.root(STEPS, prepared=FIX['prepared'])
        s = F.store(self.path)
        self.addCleanup(s.close)
        ledger, _ = L.Ledger.create(s, root)
        K.Clock(ledger).advance(steps=steps)
        return root, s, ledger

    @staticmethod
    def append(s, ledger, head, parent, state, arrays):
        key = L.successor_key(ledger.ledger_id, head.key)
        column = state.column
        s.put(key, arrays, dict(
            schema=L.SCHEMA, kind='successor', ledger_id=ledger.ledger_id, key=key, parent_key=head.key,
            parent_digest=hashlib.sha256(head._metadata).hexdigest(), sequence=head.sequence+1,
            interval=dict(start_s=head.time_s, end_s=state.time_s, start_step=head.accepted_steps,
                          end_step=column.accepted_steps),
            path=[[state.state_id, column.accepted_steps]], transfers=[],
            state=dict(state_id=state.state_id, parent_state_id=parent.state_id, time_s=state.time_s,
                       elapsed_s=column.elapsed_s, accepted_steps=column.accepted_steps, column=column.descriptor()),
            exchange=None))

    def test_a_consistent_record_appended_through_put_is_restored_continued_and_admitted(self):
        root, s, ledger = self.genuine()
        step8 = I.Continuation(root).advance(root, 8).state          # genuine physics of 8 steps ...
        head = ledger.head()
        parent = ledger.state(head)
        claimed = 5                                                  # ... recorded as 5 whole steps
        record = step8.column.descriptor()
        record.update(accepted_steps=claimed, elapsed_s=claimed*root.settings.step_s)
        record['counters']['stages'] = 1+2*claimed
        record['accounts_j_m']['radiogenic_j_m'] *= claimed/8         # the steady production of the claimed steps
        yields = np.minimum(step8.column.yield_stage_counts, 1+2*claimed)
        state = I.restore(ledger.state(ledger.root), parent_state_id=parent.state_id, column=record,
                          theta_k=step8.column.theta_k, kappa=step8.column.kappa, yield_stage_counts=yields)
        self.append(s, ledger, head, parent, state, {'column.theta_k': step8.column.theta_k,
                                                     'column.kappa': step8.column.kappa,
                                                     'column.yield_stage_counts': yields})
        other = F.store(self.path)
        self.addCleanup(other.close)
        reopened = L.Ledger.open(other, ledger.ledger_id, source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)
        # The current boundary, recorded: nothing here can tell this record from one the engine computed.
        self.assertEqual(reopened.verify_chain().accepted_steps, claimed)
        issued = fa.restored(self.evolution(), reopened, reopened.head())
        self.assertEqual((issued.stretch, issued.elapsed_s), (step8.column.stretch, claimed*root.settings.step_s))
        self.assertEqual(K.Clock(reopened).advance(steps=1).accepted_steps, 1)

    def test_a_genuine_zero_drive_history_restores_and_continues(self):
        # A zero drive books no motion evaluations: exact rest is a genuine history, not a contradiction.
        rest = F.root(STEPS, prepared=FIX['prepared'], drive=F.M.Drive(0., F.DRIVE.drag_pa_s, F.DRIVE.width_m))
        s = F.store(self.path)
        self.addCleanup(s.close)
        ledger, _ = L.Ledger.create(s, rest)
        K.Clock(ledger).advance(steps=4, savepoint_steps=2)
        other = F.store(self.path)
        self.addCleanup(other.close)
        reopened = L.Ledger.open(other, ledger.ledger_id, source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)
        head = reopened.verify_chain()
        state = reopened.state(head)
        self.assertEqual((state.column.accepted_steps, state.column.counters['evaluations']), (4, 0))
        self.assertEqual(K.Clock(reopened).advance(steps=1).accepted_steps, 1)

    def test_records_contradicting_the_retained_step_relations_are_refused(self):
        root, s, ledger = self.genuine()
        genuine = ledger.state(ledger.head())
        column, base = genuine.column, genuine.column.descriptor()
        start = ledger.state(ledger.root)
        edits = {
            'displacement is not the width': lambda r: r.update(displacement_m=0.),
            'quadrature exceeds': lambda r: r.update(log_strain_quadrature=-7.),
            'does not follow the declared drive': lambda r: r['accounts_j_m'].update(drive_work_j_m=-1e30),
            'account identities': lambda r: r['accounts_j_m'].update(heat_j_m=0.),
            'stage extrema': lambda r: r['extrema'].update(max_power_relative=-1.),
            'stage extrema ': lambda r: r['extrema'].update(min_dissipation_w_m=-1.),
            'follow the declared drive  ': lambda r: r.update(                   # larger than the drive itself
                column_force_start_n_m=2*root.settings.drive_parameters[0]),
            'does not follow the declared drive ': lambda r: r.update(
                velocity_start_m_s=-abs(r['velocity_start_m_s'])),
        }
        for message, edit in edits.items():
            with self.subTest(message.strip()):
                record = copy.deepcopy(base)
                edit(record)
                with self.assertRaisesRegex(TectonicsError, message.strip()):
                    I.restore(start, parent_state_id=genuine.parent_state_id, column=record, theta_k=column.theta_k,
                              kappa=column.kappa, yield_stage_counts=column.yield_stage_counts)
        # The reviewed forgery: a reachable stretch with no displacement, no booked energy and invented history.
        lo, hi, tlo, thi = root.settings.window
        record = copy.deepcopy(base)
        record.update(accepted_steps=8, elapsed_s=8*root.settings.step_s, clock_s=8*root.settings.step_s,
                      stretch=min(hi, 1.1), displacement_m=0., log_path=10.)
        record['counters'].update(stages=17, restress_mismatches=0)
        record['accounts_j_m'].update({name: 0. for name in record['accounts_j_m']})
        steady = np.asarray(genuine.reference.steady_temperature_k)
        with self.assertRaises(TectonicsError):
            I.restore(start, parent_state_id=genuine.state_id, column=record,
                      theta_k=np.clip(steady+37., tlo, thi)-steady, kappa=np.asarray(column.initial_kappa)+5.,
                      yield_stage_counts=np.zeros(len(steady), dtype=np.int64))


class RestoreRelationTests(Limited):
    """Correction round 3: restore() and Ledger.commit check only relations the engine enforces exactly, so a genuine
    history restores at every step whatever its schedule, and records the engine could not have written refuse."""

    def root(self, steps, duration, drive, fractions=(1., 1.)):
        def settings(st, du, dr=F.DRIVE, **representation):
            return I.ColumnSettings(representation=dict(F.REP, **representation),
                                    law=dict(start=F.LAW.start, end=F.LAW.end, cohesion_factor=F.LAW.cohesion_factor,
                                             friction_factor=F.LAW.friction_factor),
                                    drive=dict(force_n_m=dr.force_n_m, drag_pa_s=dr.drag_pa_s, width_m=dr.width_m),
                                    heat_fractions=fractions, policy=F.POLICY, schedule=dict(duration_s=du, steps=st))
        with mock.patch.object(F, 'settings', settings):
            return F.root(steps, duration=duration, prepared=FIX['prepared'], drive=drive)

    def test_genuine_short_step_ledgers_reopen_verify_describe_and_continue(self):
        rest = F.M.Drive(0., F.DRIVE.drag_pa_s, F.DRIVE.width_m)
        for index, (name, root, request) in enumerate((
                ('zero drive, 1e9 s over 16 steps', self.root(16, 1e9, rest), dict(steps=2)),
                ('heat fractions (0, 0), 3e11 s over 256 steps', self.root(256, 3e11, F.DRIVE, (0., 0.)),
                 dict(steps=8, savepoint_steps=4)))):
            with self.subTest(name):
                path = self.folder/str(index)/'ledger.sqlite'
                s = F.store(path)
                self.addCleanup(s.close)
                ledger, _ = L.Ledger.create(s, root)
                self.assertEqual(K.Clock(ledger).advance(**request).status, K.COMPLETED)
                other = F.store(path)                          # a new connection: every commit is restored again
                self.addCleanup(other.close)
                reopened = L.Ledger.open(other, ledger.ledger_id, source_id=F.SOURCE_ID, runtime_id=F.RUNTIME_ID)
                head = reopened.verify_chain()
                self.assertEqual(reopened.describe(head)['accepted_steps'], request['steps'])
                self.assertEqual(K.Clock(reopened).advance(steps=1).accepted_steps, 1)

    def test_genuine_histories_restore_at_every_step_whatever_the_schedule(self):
        rest = F.M.Drive(0., F.DRIVE.drag_pa_s, F.DRIVE.width_m)
        cases = [(duration, rest, (1., 1.)) for duration in (F.DURATION, 1e11, 1e9, 1e7, 1e5)]
        cases += [(duration, F.DRIVE, (1., 1.)) for duration in (F.DURATION, 1e11, 1e7, 1e5)]
        cases += [(1e9, F.SQUEEZE, (1., 1.)), (1e7, F.DRIVE, (0., 0.)), (F.DURATION, F.DRIVE, (.5, .25))]
        for duration, drive, fractions in cases:
            with self.subTest(duration=duration, force=drive.force_n_m, fractions=fractions):
                root = self.root(16, duration, drive, fractions)
                run, state = I.Continuation(root), root
                for k in range(16):
                    if k == 8:
                        run = I.Continuation(state)                # a new process: the head is re-solved cold
                    piece = run.advance(state, 1)
                    self.assertEqual(piece.accepted_steps, 1)
                    state = I.publishable(piece.state)
                    column = state.column
                    again = I.restore(root, parent_state_id=state.parent_state_id, column=column.descriptor(),
                                      theta_k=column.theta_k, kappa=column.kappa,
                                      yield_stage_counts=column.yield_stage_counts)
                    self.assertEqual(again.state_id, state.state_id)

    def test_records_the_engine_could_not_have_written_are_refused(self):
        root = F.root(STEPS, prepared=FIX['prepared'])
        genuine = I.Continuation(root).advance(root, 4).state
        column, base = genuine.column, genuine.column.descriptor()
        width = root.settings.drive_parameters[2]
        capacity = np.asarray(root.reference.capacity_j_m2_k)
        change = width*math.fsum(capacity*(np.asarray(column.theta_k)-np.asarray(column.initial_theta_k)))

        def at_rest(record, consistent_heat=False):                  # the round-1 load forgery, under the drive
            record.update(stretch=1., displacement_m=0.)
            record['accounts_j_m'] = {name: 0. for name in record['accounts_j_m']}
            if consistent_heat:
                record['accounts_j_m']['thermal_change_j_m'] = change

        def undissipated(record):                                     # drive work booked, nothing dissipated
            accounts = record['accounts_j_m']
            accounts.update(drag_work_j_m=0., creep_work_j_m=0., plastic_work_j_m=0., column_work_j_m=0., heat_j_m=0.,
                            stored_j_m=0.)

        def scaled(name, factor, offset=0.):
            return lambda record: record['accounts_j_m'].update({name: factor*record['accounts_j_m'][name]+offset})
        edits = {
            'at rest under the drive': (at_rest, 'follow the declared drive'),
            'at rest under the drive, thermal change consistent': (lambda r: at_rest(r, True),
                                                                  'follow the declared drive'),
            'drive work booked with nothing dissipated': (undissipated, 'account identities'),
            'drag work x1000': (scaled('drag_work_j_m', 1000.), 'account identities'),
            'column work 0 while creep and plastic work is booked': (scaled('column_work_j_m', 0.),
                                                                     'account identities'),
            'stored work x1e6': (scaled('stored_j_m', 1e6, 1e20), 'account identities'),
            'thermal change zeroed': (scaled('thermal_change_j_m', 0.), 'thermal change'),
            'radiogenic heat x1000': (scaled('radiogenic_j_m', 1000.), 'steady production'),
            'reference outflow zeroed': (scaled('reference_outflow_j_m', 0.), 'steady production'),
            'reference outflow x(1+1e-9)': (scaled('reference_outflow_j_m', 1+1e-9), 'steady production'),
            'reference surface loss x1000': (scaled('reference_surface_loss_j_m', 1000.), 'steady reference flow'),
            'reference basal gain negated': (scaled('reference_basal_gain_j_m', -1.), 'steady reference flow'),
            'force residual above the solver tolerance': (
                lambda r: r['extrema'].update(max_force_relative=1e-9), 'stage extrema'),
            'power residual above the engine bound': (
                lambda r: r['extrema'].update(max_power_relative=1e-6), 'stage extrema'),
            'drag work x1000 with its own power residual raised': (
                lambda r: (scaled('drag_work_j_m', 1000.)(r), r['extrema'].update(max_power_relative=1e3)),
                'account identities'),
        }
        for name, (edit, message) in edits.items():
            with self.subTest(name):
                record = copy.deepcopy(base)
                edit(record)
                with self.assertRaisesRegex(TectonicsError, message):
                    I.restore(root, parent_state_id=genuine.parent_state_id, column=record, theta_k=column.theta_k,
                              kappa=column.kappa, yield_stage_counts=column.yield_stage_counts)

    def test_reference_flows_are_the_runners_for_other_conductivities_and_insulated_boundaries(self):
        varied = [dict(p, conductivity_w_m_k=k) for p, k in zip(F.HEAT['thermal_layers'], (2.1, 2.9, 3.3, 4.0))]
        still = [dict(p, radiogenic_w_m3=0.) for p in varied]
        side = lambda k: dict(type='insulated') if k is None else dict(type='temperature', value_k=k)
        rest = F.M.Drive(0., F.DRIVE.drag_pa_s, F.DRIVE.width_m)
        for name, changes, insulated in (
                ('other conductivities', dict(thermal_layers=varied), ()),
                ('insulated top', dict(thermal_layers=still, boundaries=dict(top=side(None), bottom=side(1000.))),
                 ('departure_surface_loss_j_m',)),
                ('insulated base', dict(thermal_layers=still, boundaries=dict(top=side(1000.), bottom=side(None))),
                 ('departure_basal_gain_j_m',))):
            with self.subTest(name), mock.patch.dict(F.HEAT, changes):
                root = F.root(STEPS, prepared=F.preparation(), drive=rest)
                run = I.Continuation(root)
                self.assertEqual(I._reference_flows(root.reference), tuple(run._runner.reference_flows[:2]))
                state = I.publishable(run.advance(root, 2).state)          # a genuine history passes the check
                column = state.column
                for account in ('departure_surface_loss_j_m', 'departure_basal_gain_j_m'):
                    for change in (1., -1.):
                        record = column.descriptor()
                        record['accounts_j_m'][account] += change
                        restore = lambda: I.restore(root, parent_state_id=state.parent_state_id, column=record,
                                                    theta_k=column.theta_k, kappa=column.kappa,
                                                    yield_stage_counts=column.yield_stage_counts)
                        if account in insulated:                          # no departure heat crosses it
                            self.assertEqual(column.accounts_j_m[account], 0.)
                            with self.assertRaisesRegex(TectonicsError, 'insulated boundary'):
                                restore()
                        else:                                             # a fixed boundary: unrelated (trust boundary)
                            self.assertEqual(restore().column.accounts_j_m[account], record['accounts_j_m'][account])

    def test_a_ledger_never_publishes_a_state_that_breaks_the_restored_relations(self):
        root = F.root(STEPS, prepared=FIX['prepared'])
        s = F.store(self.path)
        self.addCleanup(s.close)
        ledger, _ = L.Ledger.create(s, root)
        piece = I.Continuation(root).advance(root, 1).state
        with mock.patch.object(I, '_consistent', side_effect=TectonicsError('a relation the engine enforces')), \
                self.assertRaisesRegex(L.LedgerError, 'not published'):
            ledger.commit(ledger.root, (piece,))
        self.assertEqual(ledger.head().accepted_steps, 0)
        self.assertEqual(ledger.commit(ledger.root, (piece,)).accepted_steps, 1)     # the genuine state publishes


class InspectionTests(Limited):
    def test_inspection_reads_only_the_root_and_the_commit_and_runs_no_physics(self):
        s, ledger = self.build()
        FIX['ledger_id'] = ledger.ledger_id
        head = ledger.head()
        expected = ledger.state(head)
        s.close()
        store, reopened = self.reopen()
        reads, real = [], type(store).get

        def counted(self_, key, **kwargs):
            reads.append(key)
            return real(self_, key, **kwargs)
        refuse = dict(side_effect=AssertionError('inspection ran physics'))
        with mock.patch.object(E, 'stage', **refuse), mock.patch.object(type(store), 'get', counted):
            head = reopened.head()
            summary = reopened.describe(head)
            temperature = reopened.field(head, 'temperature_k')
            depth = reopened.field(head, 'current_depth_m')
            stocks = reopened.field(head, 'exchange.component_mass_kg')
            with self.assertRaises(L.LedgerError):
                reopened.field(head, 'unknown_field')
        self.assertTrue(set(reads) <= {head.key, head.parent_key})       # the commit and its parent's stocks only
        self.assertEqual((summary['accepted_steps'], summary['remaining_steps'], summary['history']),
                         (6, STEPS-6, 'partial'))
        self.assertEqual((summary['time_s'], summary['state_id']), (expected.time_s, expected.state_id))
        self.assertEqual(summary['accounts_j_m'], expected.column.accounts_j_m)
        self.assertEqual(summary['identity']['source_id'], F.SOURCE_ID)
        self.assertTrue(summary['exchange']['closure']['identity_exact'])
        self.assertEqual(temperature['values'].tobytes(), expected.temperature_k.tobytes())
        self.assertEqual((temperature['units'], temperature['support'], temperature['time_s']),
                         ('K', 'material point', expected.time_s))
        self.assertEqual(depth['values'].tobytes(), expected.current_depth_m.tobytes())
        np.testing.assert_array_equal(stocks['values'], reopened.exchange(head).inventory.component_mass_kg)
        self.assertEqual((stocks['units'], stocks['support']), ('kg', 'W08 node x component'))
        self.assertEqual(reopened.describe(reopened.root)['history'], 'initial')
        # Returned values are copies: editing them changes nothing the ledger holds.
        summary['schedule']['steps'], summary['accounts_j_m']['heat_j_m'] = 0, -1.
        temperature['values'].setflags(write=False)
        again = reopened.describe(head)
        self.assertEqual((again['remaining_steps'], again['accounts_j_m']), (STEPS-6, expected.column.accounts_j_m))
        self.assertEqual(reopened.describe(reopened.root)['schedule']['steps'], STEPS)


class ProvenanceTests(Limited):
    def test_only_computed_states_can_be_committed(self):
        s, ledger = self.build(steps=3)
        FIX['ledger_id'] = ledger.ledger_id
        head = ledger.head()
        computed = ledger.state(head)
        s.close()
        _, reopened = self.reopen()
        restored = reopened.state(reopened.head())
        self.assertEqual((computed.issued_by, restored.issued_by), (I.COMPUTED, I.RESTORED))
        record = restored.column.descriptor()                # genuine values, so every restore relation holds
        fabricated = I.restore(reopened.state(reopened.root), parent_state_id=restored.state_id, column=record,
                               theta_k=restored.column.theta_k, kappa=restored.column.kappa,
                               yield_stage_counts=restored.column.yield_stage_counts)
        with self.assertRaisesRegex(L.LedgerError, 'computed'):
            reopened.commit(reopened.head(), (fabricated,))
        with self.assertRaisesRegex(L.LedgerError, 'computed'):
            reopened.commit(reopened.root, (reopened.state(reopened.root),))
        with self.assertRaises(TectonicsError):                        # beyond anything whole steps can reach
            I.restore(reopened.state(reopened.root), parent_state_id=restored.state_id,
                      column=dict(record, stretch=restored.column.stretch, displacement_m=-1e20),
                      theta_k=restored.column.theta_k, kappa=restored.column.kappa,
                      yield_stage_counts=restored.column.yield_stage_counts)

    def rewrite(self, key, edit):
        raw = sqlite3.connect(self.path)
        body = json.loads(raw.execute('SELECT body FROM snapshots WHERE id=?', (key,)).fetchone()[0])
        edit(body)
        text = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        import hashlib
        raw.execute('UPDATE snapshots SET body=?, digest=? WHERE id=?', (text, hashlib.sha256(text).hexdigest(), key))
        raw.commit()
        raw.close()

    def test_edited_root_middle_rows_and_swapped_chunks_refuse(self):
        s, ledger = self.build()
        FIX['ledger_id'] = ledger.ledger_id
        chain = list(ledger.chain())
        s.close()
        root, middle, head = chain[0], chain[2], chain[-1]
        for edit in (lambda b: b['metadata']['state']['record'].update(admission='CONFERRED_BY_EDIT'),
                     lambda b: b['metadata']['state'].update(accepted_steps=-1)):
            original = sqlite3.connect(self.path).execute('SELECT body, digest FROM snapshots WHERE id=?',
                                                          (root.key,)).fetchone()
            self.rewrite(root.key, edit)
            with self.assertRaises(L.LedgerError):
                self.reopen()
            raw = sqlite3.connect(self.path)
            raw.execute('UPDATE snapshots SET body=?, digest=? WHERE id=?', (*original, root.key))
            raw.commit()
            raw.close()
        self.rewrite(middle.key, lambda b: b['metadata']['state']['column']['accounts_j_m'].update(heat_j_m=1.))
        store, reopened = self.reopen()
        for call in (reopened.head, reopened.chain, reopened.verify_chain):
            with self.subTest(call=call.__name__), self.assertRaisesRegex(L.LedgerError, 'well-formed'):
                call()                                                # its child binds the original record
        # A handle on the rewritten record itself, as a lazily read chain once handed out, reads nothing either.
        edited = reopened._issued(store.metadata(middle.key))
        for name, call in (('verify', reopened.verify), ('state', reopened.state), ('exchange', reopened.exchange),
                           ('describe', reopened.describe), ('field', lambda c: reopened.field(c, 'theta_k'))):
            with self.subTest(read=name), self.assertRaises(L.LedgerError):
                call(edited)

    def test_a_rewrite_after_a_cached_read_is_still_refused(self):
        s, ledger = self.build()
        self.addCleanup(s.close)
        chain = ledger.chain()
        middle, head = chain[2], chain[-1]
        ledger.describe(head)
        reads, real = [], s.metadata

        def counted(key):
            reads.append(key)
            return real(key)
        with mock.patch.object(s, 'metadata', side_effect=counted):
            ledger.describe(chain[1])
        self.assertLessEqual(len(reads), 3)             # the checked chain is reused while nothing was written
        original = s._db.execute('SELECT body, digest FROM snapshots WHERE id=?', (middle.key,)).fetchone()
        for writer in ('another connection', 'this connection'):
            with self.subTest(writer=writer):
                body = json.loads(original[0])
                body['metadata']['state']['column']['accounts_j_m'].update(heat_j_m=1.)
                text = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
                import hashlib
                values = (text, hashlib.sha256(text).hexdigest(), middle.key)
                if writer == 'another connection':
                    raw = sqlite3.connect(self.path)
                    raw.execute('UPDATE snapshots SET body=?, digest=? WHERE id=?', values)
                    raw.commit()
                    raw.close()
                else:
                    s._db.execute('UPDATE snapshots SET body=?, digest=? WHERE id=?', values)
                for call in (lambda: ledger.describe(head), ledger.head, lambda: ledger.state(chain[1])):
                    with self.assertRaisesRegex(L.LedgerError, 'well-formed'):
                        call()
                s._db.execute('UPDATE snapshots SET body=?, digest=? WHERE id=?', (*original, middle.key))
                self.assertEqual(ledger.head().key, head.key)      # the restored record is accepted again

    def test_inspection_refuses_a_row_whose_arrays_were_swapped(self):
        s, ledger = self.build()
        FIX['ledger_id'] = ledger.ledger_id
        chain = list(ledger.chain())
        s.close()
        first, last = chain[1], chain[-1]
        raw = sqlite3.connect(self.path)
        theirs = json.loads(raw.execute('SELECT body FROM snapshots WHERE id=?', (last.key,)).fetchone()[0])
        raw.close()
        self.rewrite(first.key, lambda b: b['arrays'].update({'column.theta_k': theirs['arrays']['column.theta_k']}))
        _, reopened = self.reopen()
        commit = next(c for c in reopened.chain() if c.key == first.key)
        for call in (lambda: reopened.field(commit, 'theta_k'), lambda: reopened.describe(commit),
                     lambda: reopened.verify(commit)):
            with self.assertRaises(TectonicsError):
                call()

if __name__ == '__main__':
    unittest.main()
