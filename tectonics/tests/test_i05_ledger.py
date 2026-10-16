"""The I02 attachment of an I05 moving state (ruling I05-1): committed with each step, restored by replay, continued.

The real layered I02 column is the ledger's root, the three-plate network stands beside it and the I05 moving state
beside that. Every commit carries the column steps, the network step and the moving step together or not at all; a
commit without a MovingAdvance commits nothing; a stored moving step restores by running its transaction again; and a
history saved after some intervals and continued by a fresh process reaches exactly the moving state of the
uninterrupted history. The moving control (i05_fixtures.ledger_plan) turns plate A between a ridge and a trench,
conducts heat under a declared lateral omission certified on the state's own cells (before and after the save),
splits a cohort and merges two faces.
SPDX-License-Identifier: AGPL-3.0-only
"""
import copy
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

import atlas_tectonics
from atlas_tectonics import integration_clock as K, integration_ledger as L, integration_material as M
from atlas_tectonics import integration_state as I

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import i02_workflow_fixtures as F2                          # noqa: E402
import i03_fixtures as F                                    # noqa: E402
import i05_fixtures as X                                    # noqa: E402

SRC = str(Path(atlas_tectonics.__file__).resolve().parents[1])
STEPS = 8
WHOLE, SAVED = 6, 3
FIX = {}


def setUpModule():
    with threadpool_limits(limits=1, user_api='blas'):
        FIX['prepared'] = F2.preparation()


def feed(k):
    """An ordinary I02 Transfer of interval k into store-b beside the moving control (authored test input)."""
    return L.Transfer(label='feed-%d' % k, producer='tests/test_i05_ledger.py', donor='inflow', receiver='store-b',
                      component_mass_kg={'A': .5, 'B': .25}, enthalpy_j=-.75, basis=F2.BASIS, start_step=k,
                      end_step=k+1)


def interval(ledger, k, stocked=False):
    """One clock request for interval k of the moving control, planned on the head's own network; with
    ``stocked``, an ordinary I02 Transfer is committed beside its Motion and MovingAdvance."""
    head = ledger.head()
    step_s = ledger.state(head).settings.step_s
    moves = tuple(X.ledger_plan(k, step_s, ledger.sphere(head), ledger.moving(head)))+((feed(k),) if stocked else ())
    return K.Clock(ledger).advance(steps=1, transfers=moves, deadline=time.perf_counter()+600.)


def summary(ledger):
    """What the continued and uninterrupted heads must share: the head record's digest (not the positional key), the
    column, network and moving identities and the exchange's identity."""
    head = ledger.head()
    exchange = ledger.exchange(head)
    return [str(head.accepted_steps), hashlib.sha256(head._metadata).hexdigest(), head.state_id,
            ledger.sphere(head).state_id, ledger.moving(head).moving_id,
            'none' if exchange is None else exchange.exchange_id, str(ledger.moving(head).closure()['identity_exact'])]


CONTINUE = r'''
import hashlib, sys, time
sys.path.insert(0, sys.argv[1])
import test_i05_ledger as T
import i02_workflow_fixtures as F2
from atlas_tectonics import integration_clock as K, integration_ledger as L
store = F2.store(sys.argv[2])
ledger = L.Ledger.open(store, sys.argv[3], source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
head = ledger.verify_chain()
restored = ledger.moving(head)
for k in range(head.accepted_steps, int(sys.argv[4])):
    outcome = T.interval(ledger, k, stocked=sys.argv[5] == 'stocked')
    assert outcome.status in (K.COMPLETED, K.HISTORY_COMPLETE), outcome.reason
print(' '.join(T.summary(ledger)+[restored.moving_id]))
store.close()
'''


class Limited(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api='blas')
        self.addCleanup(lease.restore_original_limits)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)

    def ledger(self, name='ledger', stocked=False):
        store = F2.store(self.folder/name/'ledger.sqlite')
        self.addCleanup(store.close)
        sphere, moving = X.ledger_world()
        if stocked:
            column = F2.root(STEPS, prepared=FIX['prepared'], stocks=F2.reservoirs(), basis=F2.BASIS)
            ledger, root = L.Ledger.create(store, column, exteriors=(('inflow', 'source'),), sphere=sphere,
                                           moving=moving)
        else:
            column = F2.root(STEPS, prepared=FIX['prepared'])
            ledger, root = L.Ledger.create(store, column, sphere=sphere, moving=moving)
        return store, ledger, root, moving

    def opened(self, store, ledger_id):
        return L.Ledger.open(store, ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)

    def replaced(self, store, key, metadata_edit=None, arrays_edit=None, name='ledger'):
        """The store with snapshot ``key`` rewritten through the edits (as test_i03_ledger rewrites a root): its row
        deleted and the edited metadata and arrays put again under the same key."""
        path = self.folder/name/'ledger.sqlite'
        metadata, arrays = copy.deepcopy(store.metadata(key)), dict(store.get(key))
        if metadata_edit is not None:
            metadata_edit(metadata)
        if arrays_edit is not None:
            arrays_edit(arrays)
        store.close()
        connection = sqlite3.connect(path)
        try:
            connection.execute('DELETE FROM snapshots WHERE id=?', (key,))
            connection.commit()
        finally:
            connection.close()
        store = F2.store(path)
        self.addCleanup(store.close)
        store.put(key, arrays, metadata)
        return store


class AttachmentTests(Limited):
    def test_root_carries_the_moving_state_and_a_ledger_without_it_is_unchanged(self):
        store, ledger, root, moving = self.ledger()
        self.assertIs(ledger.moving(root), moving)
        metadata = root.metadata()
        self.assertEqual(metadata['declaration']['moving'], dict(schema=M.SCHEMA, moving_id=moving.moving_id))
        self.assertEqual(store.get(root.key)['moving.heat_j'].tobytes(), moving.arrays()['moving.heat_j'].tobytes())
        plain_store = F2.store(self.folder/'plain'/'ledger.sqlite')
        self.addCleanup(plain_store.close)
        plain, plain_root = L.Ledger.create(plain_store, F2.root(STEPS, prepared=FIX['prepared']),
                                            sphere=X.ledger_world()[0])
        self.assertNotIn('moving', plain_root.metadata()['declaration'])
        self.assertIsNone(plain.moving(plain_root))
        state = plain.state(plain_root)                            # an advance offered with no moving state
        piece = I.Continuation(state).advance(state, 1).state
        motion, advance = X.ledger_plan(0, state.settings.step_s, plain.sphere(plain_root), moving)
        with self.assertRaisesRegex(L.ExchangeRefused, 'no I05 moving state'):
            plain.commit(plain_root, (piece,), (motion, advance))
        self.assertEqual(plain.head().key, plain_root.key)
        bare = F2.store(self.folder/'bare'/'ledger.sqlite')
        self.addCleanup(bare.close)
        with self.assertRaises(L.LedgerError):                     # a moving state needs its network
            L.Ledger.create(bare, F2.root(STEPS, prepared=FIX['prepared']), moving=moving)

    def test_each_commit_carries_its_moving_step_and_a_missing_advance_commits_nothing(self):
        store, ledger, root, moving = self.ledger()
        step_s = ledger.state(root).settings.step_s
        motion, _ = X.ledger_plan(0, step_s, ledger.sphere(root), moving)
        refused = K.Clock(ledger).advance(steps=1, transfers=(motion,), deadline=time.perf_counter()+600.)
        self.assertEqual((refused.status, refused.accepted_steps), (K.REFUSED_EXCHANGE, 0))
        self.assertEqual(ledger.head().key, root.key)
        done = interval(ledger, 0)
        self.assertEqual(done.status, K.COMPLETED, done.reason)
        head = done.head
        record = head.metadata()['moving']
        state = ledger.moving(head)
        self.assertEqual((record['parent_moving_id'], record['moving_id'], record['state_id']),
                         (moving.moving_id, state.moving_id, ledger.sphere(head).state_id))
        self.assertTrue(state.closure()['identity_exact'])
        self.assertIn(M.CONDUCTION_PARTY, state.supplied())                 # interval 0 conducts under omission
        self.assertNotEqual(state.descriptor()['lateral_omission_error_k'], M.UNKNOWN_BOUND)

    def test_identical_replay_is_a_no_op_and_a_changed_replay_is_a_stale_parent(self):
        store, ledger, root, moving = self.ledger()
        state = ledger.state(root)
        piece = I.Continuation(state).advance(state, 1).state
        motion, advance = X.ledger_plan(0, state.settings.step_s, ledger.sphere(root), moving)
        first = ledger.commit(root, (piece,), (motion, advance))
        again = ledger.commit(root, (piece,), (motion, advance))
        self.assertEqual(again.key, first.key)
        changed = M.MovingAdvance(0, 1, conduction=M.Conduction('solve', X.nodes(ledger.sphere(root).network)))
        with self.assertRaises(L.LedgerConflict):
            ledger.commit(root, (piece,), (motion, changed))

    def test_an_edited_moving_array_is_refused_on_replay(self):
        store, ledger, root, moving = self.ledger()
        head = interval(ledger, 0).head
        metadata, arrays = head.metadata(), dict(store.get(head.key))
        edited = dict(arrays)
        edited['moving.heat_j'] = arrays['moving.heat_j'].copy()
        edited['moving.heat_j'][0] *= 1+1e-9
        with self.assertRaises((L.LedgerError, M.TransportRefused)):
            M.restored(moving, metadata, edited, ledger.sphere(root))
        self.assertEqual(M.restored(moving, metadata, arrays, ledger.sphere(root)).moving_id,
                         ledger.moving(head).moving_id)


class StoredRecordTests(Limited):
    """ledger-1, ledger-2 and ledger-8: an edited or foreign stored moving record or array is refused by name, through
    the store, open, verify_chain, chain and moving, never with a raw Python error."""

    def history(self, intervals=2):
        store, ledger, root, moving = self.ledger()
        for k in range(intervals):
            self.assertEqual(interval(ledger, k).status, K.COMPLETED)
        return store, ledger, root

    def assertRefusedFresh(self, store, ledger_id, call, pattern=None):
        with self.assertRaises(L.LedgerError) as caught:
            call(self.opened(store, ledger_id))
        if pattern:
            self.assertIn(pattern, str(caught.exception))

    def test_an_edited_head_record_or_array_is_refused_through_the_store(self):
        store, ledger, root = self.history()
        head = ledger.head()

        def summary(metadata):
            metadata['moving']['summary']['transport'] = 'edited'
        store = self.replaced(store, head.key, metadata_edit=summary)
        self.assertRefusedFresh(store, ledger.ledger_id, lambda again: again.verify_chain())
        self.assertRefusedFresh(store, ledger.ledger_id, lambda again: again.moving(again.head()))

    def test_an_edited_head_array_is_refused_through_the_store(self):
        store, ledger, root = self.history()
        head = ledger.head()

        def heat(arrays):
            arrays['moving.heat_j'] = arrays['moving.heat_j'].copy()
            arrays['moving.heat_j'][0] *= 1+1e-9
        store = self.replaced(store, head.key, arrays_edit=heat)
        self.assertRefusedFresh(store, ledger.ledger_id, lambda again: again.verify_chain())
        self.assertRefusedFresh(store, ledger.ledger_id, lambda again: again.moving(again.head()))

    def test_an_unknown_moving_step_schema_is_refused_by_name(self):
        store, ledger, root = self.history()

        def schema(metadata):
            metadata['moving']['schema'] = 'atlas.i05-moving-step.v2'
        store = self.replaced(store, ledger.head().key, metadata_edit=schema)
        self.assertRefusedFresh(store, ledger.ledger_id, lambda again: again.verify_chain(),
                                'unsupported moving step schema')

    def test_a_successor_without_its_moving_record_is_refused(self):
        store, ledger, root = self.history()

        def drop(metadata):
            del metadata['moving']
        store = self.replaced(store, ledger.head().key, metadata_edit=drop)
        self.assertRefusedFresh(store, ledger.ledger_id, lambda again: again.chain())

    def test_an_edited_or_extra_root_array_or_a_malformed_root_record_is_refused_on_open(self):
        for name, metadata_edit, arrays_edit in (
                ('trailing', None, lambda arrays: arrays.update({'moving.heat_j': np.append(arrays['moving.heat_j'],
                                                                                            1.)})),
                ('extra', None, lambda arrays: arrays.update({'moving.zzz': np.zeros(1)})),
                ('supplied', lambda metadata: metadata['moving']['accounts'].update(supplied=[]), None)):
            with self.subTest(name):
                store, ledger, root, _ = self.ledger(name)
                store = self.replaced(store, root.key, metadata_edit, arrays_edit, name=name)
                with self.assertRaises(L.LedgerError):
                    self.opened(store, ledger.ledger_id)

    def test_a_foreign_root_declaring_a_moving_state_without_its_network_is_refused(self):
        store, ledger, root, _ = self.ledger()
        metadata = copy.deepcopy(store.metadata(root.key))
        arrays = {k: v for k, v in store.get(root.key).items() if not k.startswith('sphere.')}
        del metadata['declaration']['sphere'], metadata['sphere']
        forged_id = hashlib.sha256(L._canonical(metadata['declaration'], 'ledger declaration')).hexdigest()
        metadata['ledger_id'], metadata['key'] = forged_id, L.root_key(forged_id)
        forged = F2.store(self.folder/'forged'/'ledger.sqlite')
        self.addCleanup(forged.close)
        forged.put(metadata['key'], arrays, metadata)
        with self.assertRaises(L.LedgerError) as caught:
            self.opened(forged, forged_id)
        self.assertIn('spherical network', str(caught.exception))


IMPORTS = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
import i02_workflow_fixtures as F2
from atlas_tectonics import integration_clock as K, integration_ledger as L
store = F2.store(sys.argv[2])
ledger, root = L.Ledger.create(store, F2.root(4, stocks=F2.reservoirs(), basis=F2.BASIS),
                               exteriors=(('inflow', 'source'),))
feed = L.Transfer(label='feed-0', producer='imports', donor='inflow', receiver='store-b',
                  component_mass_kg={'A': .5, 'B': .25}, enthalpy_j=-.75, basis=F2.BASIS, start_step=0, end_step=1)
outcome = K.Clock(ledger).advance(steps=1, transfers=(feed,), deadline=time.perf_counter()+600.)
print(outcome.status, sorted(name for name in sys.modules if name.startswith('atlas_tectonics.integration_')
                             and name.rsplit('.', 1)[1] in ('integration_material', 'integration_transfer',
                                                            'integration_sphere', 'integration_splits')))
store.close()
'''


class ContinuationTests(Limited):
    def continued(self, stocked):
        """(uninterrupted summary, continued summary, the middle moving identity, the reopened one)."""
        _, whole, _, _ = self.ledger('whole', stocked)
        for k in range(WHOLE):
            outcome = interval(whole, k, stocked)
            self.assertEqual(outcome.status, K.COMPLETED, (k, outcome.reason))
        final = whole.moving(whole.head())
        cohorts = {c.cohort_id for c in final.cohorts}
        self.assertTrue(any(c.startswith('split:') for c in cohorts))                 # the split was committed
        self.assertIn(('s00-merged', 'inherited-C'), final.pieces)                    # and the merge
        self.assertIn(M.CONDUCTION_PARTY, final.supplied())                           # and the heat conducted
        want = summary(whole)
        store, ledger, root, _ = self.ledger('saved', stocked)
        for k in range(SAVED):
            self.assertEqual(interval(ledger, k, stocked).status, K.COMPLETED)
        middle = ledger.moving(ledger.head())
        path = self.folder/'saved'/'ledger.sqlite'
        store.close()
        env = dict(os.environ, PYTHONPATH=SRC)
        done = subprocess.run([sys.executable, '-B', '-c', CONTINUE, str(HERE), str(path), ledger.ledger_id,
                               str(WHOLE), 'stocked' if stocked else 'plain'], capture_output=True, text=True,
                              env=env, timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr)
        got = done.stdout.split()
        store = F2.store(path)
        self.addCleanup(store.close)
        again = self.opened(store, ledger.ledger_id)
        head = again.verify_chain()
        self.assertEqual(again.moving(head).arrays()['moving.heat_j'].tobytes(),
                         final.arrays()['moving.heat_j'].tobytes())
        return want, got[:-1], middle.moving_id, got[-1]

    def test_save_reopen_and_continue_reaches_the_uninterrupted_moving_state(self):
        """ledger-5: parity compares the head record's digest, the column, network and moving identities and the
        exact closure; ledger keys are positional, so they are not evidence of parity."""
        want, got, middle, reopened = self.continued(False)
        self.assertEqual(got, want)
        self.assertEqual(got[0], str(WHOLE))
        self.assertEqual(got[-1], 'True')
        self.assertEqual(reopened, middle)

    def test_save_reopen_and_continue_with_i02_transfers_beside_the_moving_advance(self):
        """ledger-4: with finite stocks, an ordinary I02 Transfer is committed beside each Motion and MovingAdvance;
        the continued head equals the uninterrupted one, its exchange identity included."""
        want, got, middle, reopened = self.continued(True)
        self.assertEqual(got, want)
        self.assertNotEqual(got[5], 'none')
        self.assertEqual(reopened, middle)

    def test_a_ledger_without_a_moving_state_never_imports_i05(self):
        """ledger-6: a column-only commit with an ordinary I02 Transfer (so every shared-path check runs) imports no
        I03 or I05 module (a fresh process; sys.modules lookup)."""
        env = dict(os.environ, PYTHONPATH=SRC)
        done = subprocess.run([sys.executable, '-B', '-c', IMPORTS, str(HERE), str(self.folder/'plain.sqlite')],
                              capture_output=True, text=True, env=env, timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip().split(None, 1), [K.COMPLETED, '[]'])


if __name__ == '__main__':
    unittest.main()
