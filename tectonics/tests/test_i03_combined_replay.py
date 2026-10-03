"""K1 regression: supplied paths survive remeshing, events and persisted continuation.

Uses the existing v4 junction_paths fixture; no new physical or numerical tolerance.
"""
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest

from threadpoolctl import threadpool_limits
import i02_workflow_fixtures as F2
import i03_fixtures as F
import test_i03_junction_paths as JP
from atlas_tectonics import integration_clock as K, integration_ledger as L
from atlas_tectonics import integration_transfer as T, integration_events as E, integration_sphere as S


def remeshed(state, end, *, rename=False, event=False):
    proposal = JP.motion()
    endpoint = T.advance(state, proposal, end_time_s=end).state.network
    faces = tuple(replace(face, face_id='renamed-'+face.face_id) if rename else face
                  for face in endpoint.faces)
    events = ()
    if event:
        # Split the stationary southern hemisphere along a complete existing meridian.
        east = tuple(face.face_id for face in faces if face.plate_id == 'O'
                     and F.sector_of(face.face_id) < 6)
        west = tuple(face.face_id for face in faces if face.plate_id == 'O' and face.face_id not in east)
        # Read the actual endpoint seam, including the corners retained on the carrier after sliding.
        def edges(names):
            return {(a, b) for face in faces if face.face_id in names
                    for a, b in zip(face.vertex_ids, face.vertex_ids[1:]+face.vertex_ids[:1])}
        west_edges = edges(west)
        shared = {a: b for a, b in edges(east) if (b, a) in west_edges}
        start, = set(shared)-set(shared.values())
        line = [start]
        while line[-1] in shared:
            line.append(shared[line[-1]])
        assert len(line) == len(shared)+1
        line = tuple(line)
        boundary = S.Boundary('south-split', S.TRANSFORM, 'O-east', 'O-west', line,
                              S.Origin(S.EVENT, 'split-o'))
        events = (E.Split('split-o', 'O', (('O-east', east), ('O-west', west)), boundary, end),)
    return replace(proposal, mesh=T.Mesh(faces), events=events)


class CombinedReplayTests(unittest.TestCase):
    def test_paths_with_identity_mesh_rename_and_events_restore(self):
        state = F.crust(JP.world())
        for rename, event in ((False, False), (True, False), (False, True)):
            with self.subTest(rename=rename, event=event):
                proposal = remeshed(state, F.MYR_S, rename=rename, event=event)
                step = T.advance(state, proposal, end_time_s=F.MYR_S)
                restored = T.restored(state, {'sphere': step.record(), 'transfers': []}, step.arrays())
                self.assertEqual(restored.state_id, step.state.state_id)
                self.assertEqual(step.motion.junction_paths, proposal.junction_paths)
                self.assertTrue(restored.material.closure()['identity_exact'])

    def test_paths_and_rename_reopen_verify_and_continue_actual_motion(self):
        with threadpool_limits(limits=1, user_api='blas'), tempfile.TemporaryDirectory() as folder:
            column = F2.root(F.control('clock_commit')['column_steps'])
            state = F.crust(JP.world(epoch=F2.EPOCH, time_s=F2.START))
            path = Path(folder)/'history.sqlite'
            deadline = lambda: time.perf_counter()+F.CASE['resources']['clock_deadline_s']
            store = F2.store(path)
            try:
                ledger, root = L.Ledger.create(store, column, sphere=state)
                clock = K.Clock(ledger)
                proposal = remeshed(state, clock.time_at(1), rename=True)
                first = clock.advance(steps=1, deadline=deadline(), transfers=(proposal,))
                self.assertEqual(first.status, K.COMPLETED, first.reason)
                saved = ledger.sphere(first.head)
                for schema in ('atlas.i03-sphere-step.v1', 'atlas.i03-sphere-step.v2'):
                    old = first.head.metadata()
                    old['sphere']['schema'] = schema
                    with self.assertRaisesRegex(L.LedgerError, 'unsupported spherical step schema.*'+schema):
                        ledger._checked(old, root)
                    with self.assertRaisesRegex(L.LedgerError, 'unsupported spherical step schema.*'+schema):
                        T.restored(state, old, {})
                follow = replace(JP.motion(), start_step=1, end_step=2)
                expected = T.advance(saved, follow, end_time_s=clock.time_at(2)).state.state_id
                ledger_id = ledger.ledger_id
            finally:
                store.close()
            store = F2.store(path)
            try:
                reopened = L.Ledger.open(store, ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
                self.assertEqual(reopened.verify_chain().key, first.head.key)
                self.assertEqual(reopened.sphere(first.head).state_id, saved.state_id)
                second = K.Clock(reopened).advance(steps=1, deadline=deadline(), transfers=(follow,))
                self.assertEqual(second.status, K.COMPLETED, second.reason)
                self.assertEqual(reopened.sphere(second.head).state_id, expected)
                self.assertEqual(reopened.verify_chain().key, second.head.key)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
