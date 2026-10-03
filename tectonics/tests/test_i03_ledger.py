"""Focused I03.1 checks: the spherical network carried by the I02 accepted state, saved and reopened.

The real layered column of the I02 checks is the ledger's root; a declared sector network and its material are
attached beside it. The root commit must store both in one snapshot, bind the network into the ledger identity,
return it unchanged, restore it through the validating constructors in this process and in a fresh one, and refuse
an edited store, a state of another epoch or time, and a stock link the exchange does not declare. Motion and
transfers through the clock are in test_i03_clock.py. The control's values are read from
cases/i03_controls_v1.json (control ledger_attachment).
SPDX-License-Identifier: AGPL-3.0-only
"""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

import atlas_tectonics
from atlas_tectonics import integration_ledger as L, integration_sphere as S, integration_state as I

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import i02_workflow_fixtures as F2
import i03_fixtures as F

SRC = str(Path(atlas_tectonics.__file__).resolve().parents[1])
CONTROL = F.control('ledger_attachment')
EXTERIORS = tuple(tuple(pair) for pair in CONTROL['exchange_exteriors'])
LINK = dict(CONTROL['stock_link'])
LINKED = dict(phases=tuple(CONTROL['linked_material']['phases']), basis=F2.BASIS, stock_link=LINK,
              mass_per_area_kg_m2=dict(CONTROL['linked_material']['mass_per_area_kg_m2']),
              thickness_m=dict(CONTROL['linked_material']['thickness_m']))
FACES = F.CASE['meshes'][F.CASE['worlds'][CONTROL['world']]['mesh']]['faces']
FIX = {}


def setUpModule():
    with threadpool_limits(limits=1, user_api='blas'):
        FIX['prepared'] = F2.preparation()


def child(script, *args):
    env = dict(os.environ, PYTHONPATH=SRC)
    return subprocess.run([sys.executable, '-B', '-c', script, str(HERE), *map(str, args)], capture_output=True,
                          text=True, env=env, timeout=F.CASE['resources']['child_timeout_s'])


def network(**changes):
    values = dict(epoch=F2.EPOCH, time_s=F2.START)
    values.update(changes)
    return F.sector_world(**values)


class Limited(unittest.TestCase):
    def setUp(self):
        lease = threadpool_limits(limits=1, user_api='blas')
        self.addCleanup(lease.restore_original_limits)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.path = self.folder/'ledger'/'ledger.sqlite'
        self.column = F2.root(prepared=FIX['prepared'])
        self.store = F2.store(self.path)
        self.addCleanup(self.store.close)
        self.sphere = F.state(network())


class AttachmentTests(Limited):
    def test_the_control_stands_at_the_column_s_own_epoch_and_start(self):
        self.assertEqual((CONTROL['epoch_id'], CONTROL['start_time_s']), (F2.EPOCH, F2.START))
        self.assertEqual((self.column.epoch_id, self.column.time_s), (self.sphere.network.epoch_id,
                                                                      self.sphere.network.time_s))

    def test_root_commit_carries_the_network_beside_the_column(self):
        ledger, root = L.Ledger.create(self.store, self.column, sphere=self.sphere)
        self.assertIs(ledger.sphere(root), self.sphere)
        metadata = root.metadata()
        self.assertEqual(metadata['declaration']['sphere'], dict(schema=S.SCHEMA, state_id=self.sphere.state_id))
        self.assertEqual(metadata['sphere']['state_id'], self.sphere.state_id)
        # One snapshot under the root key holds the column, the network geometry and its material accounts.
        stored = self.store.get(root.key)
        self.assertEqual(stored['sphere.vertex_reference'].tobytes(),
                         self.sphere.network.arrays()['sphere.vertex_reference'].tobytes())
        self.assertEqual(stored['sphere.piece_stock'].tobytes(), self.sphere.material.stock.tobytes())
        self.assertIn('column.theta_k', stored)
        self.assertEqual(self.store.statistics()['snapshots'], 1)
        described = ledger.describe(root)
        self.assertEqual(described['sphere'], dict(self.sphere.identities(), time_s=F2.START, step=0,
                                                   faces=FACES, pieces=FACES))
        ledger.verify(root)
        self.assertEqual(ledger.verify_chain().key, root.key)

    def test_the_network_is_bound_into_the_ledger_identity(self):
        with_sphere, _ = L.Ledger.create(self.store, self.column, sphere=self.sphere)
        other = F.state(network(latitudes_deg=F.moved_latitudes()))
        different, _ = L.Ledger.create(self.store, self.column, sphere=other)
        plain, root = L.Ledger.create(self.store, self.column)
        self.assertEqual(len({with_sphere.ledger_id, different.ledger_id, plain.ledger_id}), 3)
        self.assertIsNone(plain.sphere(root))
        self.assertNotIn('sphere', root.metadata())
        self.assertNotIn('sphere', root.metadata()['declaration'])
        self.assertNotIn('sphere', plain.describe(root))            # a history without one reports none
        again, same = L.Ledger.create(self.store, self.column, sphere=self.sphere)      # idempotent
        self.assertEqual((again.ledger_id, same.key), (with_sphere.ledger_id, with_sphere.root.key))

    def test_only_a_declared_state_of_the_same_epoch_and_start_can_be_attached(self):
        for wrong in (F.state(network(time_s=F2.START+1.)), F.state(network(epoch='another-epoch')),
                      F.state(network(step=1))):
            with self.assertRaises(L.LedgerError):
                L.Ledger.create(self.store, self.column, sphere=wrong)
        restored = S.restore_sphere(self.sphere.descriptor(), self.sphere.arrays())
        with self.assertRaises(L.LedgerError) as caught:
            L.Ledger.create(self.store, self.column, sphere=restored)
        self.assertIn('declared initial', str(caught.exception))
        with self.assertRaises(L.LedgerError):
            L.Ledger.create(self.store, self.column, sphere=self.sphere.network)
        self.assertEqual(self.store.statistics()['snapshots'], 0)

    def test_a_stock_link_must_name_declared_exchange_exteriors(self):
        linked = F.state(network(), **LINKED)
        with self.assertRaises(L.LedgerError) as caught:
            L.Ledger.create(self.store, self.column, sphere=linked)                # no finite stocks attached
        self.assertIn('finite stocks', str(caught.exception))
        stocked = F2.root(prepared=FIX['prepared'], stocks=F2.reservoirs(), basis=F2.BASIS)
        ledger, root = L.Ledger.create(self.store, stocked, exteriors=EXTERIORS, sphere=linked)
        self.assertEqual(ledger.sphere(root).material.stock_link, LINK)
        receives, returns = LINK['receives'], LINK['returns']
        for exteriors in (((receives, 'source'), (returns, 'source')), ((receives, 'sink'),),
                          ((receives, 'sink'), (returns, 'sink'))):
            with self.assertRaises(L.LedgerError):
                L.Ledger.create(self.store, stocked, exteriors=exteriors, sphere=linked)
        # The finite stocks and the pieces must describe the same components in the same enthalpy basis.
        for changes in (dict(phases=('A',), mass_per_area_kg_m2={'A': 1.}, thickness_m={'A': 3.}),
                        dict(basis='another-basis')):
            values = dict(LINKED)
            values.update(changes)
            with self.assertRaises(L.LedgerError):
                L.Ledger.create(self.store, stocked, exteriors=EXTERIORS, sphere=F.state(network(), **values))


REOPEN = r'''
import sys
sys.path.insert(0, sys.argv[1])
import i02_workflow_fixtures as F2
from atlas_tectonics import integration_ledger as L
store = F2.store(sys.argv[2])
ledger = L.Ledger.open(store, sys.argv[3], source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
state = ledger.sphere(ledger.root)
ledger.verify_chain()
closure = state.material.closure()
print(state.state_id, state.network.network_id, state.material.material_id, state.issued_by,
      state.network.lineage.retired_face_ids[0], closure['identity_exact'], len(state.network.junctions))
store.close()
'''


class ReopenTests(Limited):
    def saved(self):
        lineage = S.Lineage(retired_face_ids=(CONTROL['retired_face'],))
        sphere = F.state(network(tilt=F.TILT, lineage=lineage), exteriors=(('slab', 'sink'),))
        ledger, root = L.Ledger.create(self.store, self.column, sphere=sphere)
        return ledger, root, sphere

    def test_reopened_ledger_restores_the_network_through_its_constructors(self):
        ledger, root, sphere = self.saved()
        self.store.close()
        store = F2.store(self.path)
        self.addCleanup(store.close)
        again = L.Ledger.open(store, ledger.ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
        state = again.sphere(again.root)
        self.assertIsNot(state, sphere)
        self.assertEqual((state.state_id, state.issued_by), (sphere.state_id, I.RESTORED))
        self.assertEqual(state.network.vertex_direction.tobytes(), sphere.network.vertex_direction.tobytes())
        self.assertEqual(state.material.stock.tobytes(), sphere.material.stock.tobytes())
        self.assertEqual(state.network.lineage, sphere.network.lineage)
        self.assertEqual(again.describe(again.root)['sphere']['state_id'], sphere.state_id)
        again.verify_chain()

    def test_fresh_process_reopens_the_network_with_its_lineage(self):
        ledger, root, sphere = self.saved()
        self.store.close()
        done = child(REOPEN, self.path, ledger.ledger_id)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.split(),
                         [sphere.state_id, sphere.network.network_id, sphere.material.material_id, I.RESTORED,
                          CONTROL['retired_face'], 'True', '2'])

    def rewritten(self, change):
        """A store whose root snapshot was replaced by ``change(metadata, arrays)``: (store, ledger identity)."""
        ledger, root, sphere = self.saved()
        metadata, arrays = self.store.metadata(root.key), dict(self.store.get(root.key))
        metadata, arrays = change(metadata, arrays)
        self.store.close()
        connection = sqlite3.connect(self.path)
        try:
            connection.execute('DELETE FROM snapshots')
            connection.commit()
        finally:
            connection.close()
        store = F2.store(self.path)
        self.addCleanup(store.close)
        store.put(root.key, arrays, metadata)
        return store, ledger.ledger_id

    def refused(self, change):
        store, ledger_id = self.rewritten(change)
        with self.assertRaises(L.LedgerError):
            L.Ledger.open(store, ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)

    def other(self):
        """Another, equally valid state: the same tilted world with one latitude moved."""
        return F.state(network(tilt=F.TILT, latitudes_deg=F.moved_latitudes()), exteriors=(('slab', 'sink'),))

    def test_an_unchanged_rewrite_reopens(self):
        store, ledger_id = self.rewritten(lambda metadata, arrays: (metadata, arrays))
        again = L.Ledger.open(store, ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
        self.assertEqual(again.sphere(again.root).issued_by, I.RESTORED)

    def test_an_edited_stored_network_is_refused_not_rebound(self):
        # Another, equally well-formed network written over the stored arrays no longer matches the recorded identity.
        other = self.other()
        self.refused(lambda metadata, arrays: (metadata, dict(arrays, **other.arrays())))

    def test_a_consistently_replaced_network_still_breaks_the_ledger_identity(self):
        # Record and arrays of another valid state together: the declaration bound the original state's identity.
        other = self.other()
        self.refused(lambda metadata, arrays: (dict(metadata, sphere=other.descriptor()),
                                               dict(arrays, **other.arrays())))

    def test_an_edited_material_account_is_refused(self):
        def change(metadata, arrays):
            stock = np.array(arrays['sphere.piece_stock'])
            stock[3, 1] *= 1.5
            return metadata, dict(arrays, **{'sphere.piece_stock': stock})
        self.refused(change)

    def test_root_arrays_of_another_type_or_not_its_own_are_refused(self):
        # Values that would cast to the issued ones are not the issued bytes; and a root holds no step's arrays.
        for name, convert in (('sphere.piece_face', lambda a: a.astype(np.int32)),
                              ('sphere.piece_face', lambda a: a.astype(np.float64)+0.4),
                              ('sphere.piece_cohort', lambda a: a.astype(np.float64)+0.9),
                              ('sphere.piece_stock', lambda a: a.astype(np.float32)),
                              ('sphere.map_area_m2', lambda a: np.zeros(2))):
            with self.subTest(array=name):
                def change(metadata, arrays, name=name, convert=convert):
                    return metadata, dict(arrays, **{name: convert(np.array(arrays.get(name, 0.)))})
                directory = tempfile.TemporaryDirectory()
                self.addCleanup(directory.cleanup)
                self.path = Path(directory.name)/'ledger'/'ledger.sqlite'
                self.store = F2.store(self.path)
                self.addCleanup(self.store.close)
                self.refused(change)

    def test_a_root_without_its_declared_network_is_refused(self):
        def change(metadata, arrays):
            metadata = {key: value for key, value in metadata.items() if key != 'sphere'}
            return metadata, {name: array for name, array in arrays.items() if not name.startswith('sphere.')}
        self.refused(change)


if __name__ == '__main__':
    unittest.main()
