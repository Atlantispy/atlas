"""I03 history split (I05-2 ruling): named endpoint pieces of one cohort become history-distinct sub-cohorts.

The split is carried in the interval's Motion and applied last, atomically with the step. Every exact account and
occupancy allowance is unchanged, a sub-cohort keeps its parent's material, origin and formation interval, the lineage
is stored in the step's arrays, and restoring the step applies the split again. The worlds are the I03 control worlds
(tests/i03_fixtures.py, cases/i03_controls_v1.json): plate A turns between a ridge behind and a trench ahead.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i03_fixtures as F                                    # noqa: E402

from atlas_tectonics import integration_splits as X         # noqa: E402
from atlas_tectonics import integration_sphere as S         # noqa: E402
from atlas_tectonics import integration_transfer as T       # noqa: E402

DEGREES = 2.
TILT = F.Rotation.from_axis_angle((1., 0., 0.), 0.7)


def endpoint_faces(step, cohort):
    return sorted(piece.face_id for piece in step.state.material.pieces() if piece.cohort_id == cohort)


def by_face(material):
    """(face, cohort) -> exact stock row: what the split may relabel but never change."""
    return {(piece.face_id, piece.cohort_id): tuple(Fraction(float(v)) for v in row)
            for piece, row in zip(material.pieces(), material.stock)}


def restored(parent, step):
    return T.restored(parent, {'sphere': step.record(), 'transfers': []}, step.arrays())


class SplitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network = F.three_plates()
        cls.state = F.crust(cls.network)
        cls.plain = T.advance(cls.state, F.one_plate_motion(DEGREES), end_time_s=cls.state.network.time_s+F.MYR_S)
        cls.faces = endpoint_faces(cls.plain, 'inherited-A')

    def split(self, groups=None, cohort='inherited-A'):
        if groups is None:
            third = len(self.faces)//3
            groups = (('history-a1', tuple(self.faces[:third])), ('history-a2', tuple(self.faces[third:2*third])))
        return X.HistorySplit(cohort, groups)

    def stepped(self, *splits, state=None, motion=None):
        state = self.state if state is None else state
        motion = F.one_plate_motion(DEGREES, history_splits=splits) if motion is None else motion
        return T.advance(state, motion, end_time_s=state.network.time_s+F.MYR_S)

    def test_relabels_named_pieces_and_keeps_every_account(self):
        step = self.stepped(self.split())
        plain, split = self.plain.state.material, step.state.material
        self.assertEqual(split.closure(), plain.closure())
        self.assertEqual([split.exact_total(name) for name in split.columns],
                         [plain.exact_total(name) for name in plain.columns])
        self.assertEqual(split.supplied(), plain.supplied())
        self.assertEqual(split.occupancy_allowance_m2.tobytes(), plain.occupancy_allowance_m2.tobytes())
        # The same stock rows on the same faces; only the named pieces change cohort.
        before, after = by_face(plain), by_face(split)
        groups = {face: X.sub_cohort_id('inherited-A', 1, history)
                  for history, faces in self.split().groups for face in faces}
        moved = {(face, groups.get(face, cohort) if cohort == 'inherited-A' else cohort): row
                 for (face, cohort), row in before.items()}
        self.assertEqual(moved, after)
        parent = plain.cohort('inherited-A')
        for history in ('history-a1', 'history-a2'):
            child = split.cohort(X.sub_cohort_id('inherited-A', 1, history))
            self.assertEqual((child.material_id, child.origin_id, child.formation_start_s, child.formation_end_s),
                             (parent.material_id, parent.origin_id, parent.formation_start_s, parent.formation_end_s))
            self.assertEqual(child.history_id, history)
            self.assertTrue(child.cohort_id.startswith(X.PREFIX) and len(child.cohort_id) == len(X.PREFIX)+32)
        # Unnamed pieces stay in the parent cohort; the lineage names (parent, child) in the successor's cohorts.
        self.assertEqual(len(endpoint_faces(step, 'inherited-A')), len(self.faces)-2*(len(self.faces)//3))
        arrays = step.arrays()
        names = [record.cohort_id for record in split.cohorts]
        lineage = sorted(zip(arrays['sphere.split_parent'].tolist(), arrays['sphere.split_child'].tolist()))
        self.assertEqual([(names[p], names[c]) for p, c in lineage],
                         sorted(('inherited-A', X.sub_cohort_id('inherited-A', 1, h))
                                for h in ('history-a1', 'history-a2')))
        self.assertNotIn('sphere.split_parent', self.plain.arrays())

    def test_restore_replays_the_split_and_refuses_edited_lineage(self):
        step = self.stepped(self.split())
        again = restored(self.state, step)
        self.assertEqual(again.state_id, step.state.state_id)
        verified, state = T._restored_step(self.state, {'sphere': step.record(), 'transfers': []}, step.arrays())
        self.assertEqual((verified.map.map_id, state.state_id), (step.map.map_id, step.state.state_id))
        self.assertEqual(self.stepped(self.split()).record(), step.record())          # replay is idempotent
        edited = dict(step.arrays())
        edited['sphere.split_child'] = edited['sphere.split_child'][::-1].copy()
        with self.assertRaises(T.LedgerError):
            T.restored(self.state, {'sphere': step.record(), 'transfers': []}, edited)
        edited = dict(step.arrays())
        parents = edited['sphere.split_parent'].copy()
        parents[0] = edited['sphere.split_child'][0]
        edited['sphere.split_parent'] = parents
        with self.assertRaises(T.LedgerError):
            T.restored(self.state, {'sphere': step.record(), 'transfers': []}, edited)
        dropped = {k: v for k, v in step.arrays().items() if not k.startswith('sphere.split_')}
        with self.assertRaises(T.LedgerError):
            T.restored(self.state, {'sphere': step.record(), 'transfers': []}, dropped)

    def test_split_then_transfer_keeps_sub_cohorts_and_exact_accounts(self):
        step = self.stepped(self.split())
        later = T.advance(step.state, F.one_plate_motion(DEGREES, step=1),
                          end_time_s=step.state.network.time_s+F.MYR_S)
        material = later.state.material
        self.assertTrue(material.closure()['identity_exact'])
        held = {piece.cohort_id for piece in material.pieces()}
        self.assertTrue({X.sub_cohort_id('inherited-A', 1, h) for h in ('history-a1', 'history-a2')} <= held)
        child = material.cohort(X.sub_cohort_id('inherited-A', 1, 'history-a1'))
        self.assertEqual((child.formation_start_s, child.formation_end_s),
                         (self.state.material.cohort('inherited-A').formation_start_s,
                          self.state.material.cohort('inherited-A').formation_end_s))
        self.assertEqual(restored(step.state, later).state_id, later.state.state_id)

    def test_refusals(self):
        faces = self.faces
        with self.assertRaises(T.TransferRefused):
            self.stepped(self.split(cohort='inherited-nowhere', groups=(('h', (faces[0],)),)))
        foreign = endpoint_faces(self.plain, 'inherited-C')[0]
        with self.assertRaises(T.TransferRefused):
            self.stepped(self.split(groups=(('h1', (faces[0],)), ('h2', (foreign,)))))
        with self.assertRaises(T.TransferRefused) as caught:                          # one group, every piece
            self.stepped(self.split(groups=(('h', tuple(faces)),)))
        self.assertIn('no-op', str(caught.exception))
        with self.assertRaises(T.TransferRefused) as caught:                          # groups empty the parent
            self.stepped(self.split(groups=(('h1', tuple(faces[:2])), ('h2', tuple(faces[2:])))))
        self.assertIn('parent', str(caught.exception))
        named = tuple(F.cohort(name, history='history-of-'+name) for name in ('inherited-A', 'inherited-B',
                                                                                   'inherited-C'))
        historied = F.crust(self.network, cohorts=named)
        with self.assertRaises(T.TransferRefused):                                    # the parent's own history
            self.stepped(self.split(groups=(('history-of-inherited-A', (faces[0],)),)), state=historied)
        self.assertEqual(self.stepped(self.split(), state=historied).state.material.cohort(
            X.sub_cohort_id('inherited-A', 1, 'history-a1')).history_id, 'history-a1')
        for groups in ((), (('h', ()),), (('h1', (faces[0],)), ('h2', (faces[0],))),
                       (('h', (faces[0],)), ('h', (faces[1],))), (('', (faces[0],)),), (('h', ('',)),)):
            with self.assertRaises(X.SplitRefused, msg=str(groups)):
                X.HistorySplit('inherited-A', groups)
        with self.assertRaises(T.LedgerError):                                        # one split per cohort
            F.one_plate_motion(DEGREES, history_splits=(self.split(), self.split(groups=(('h9', (faces[-1],)),))))
        with self.assertRaises(T.LedgerError):
            F.one_plate_motion(DEGREES, history_splits=('not a split',))

    def test_a_derived_identity_already_in_use_is_refused(self):
        taken = X.sub_cohort_id('inherited-A', 1, 'history-a1')
        state = F.crust(self.network, cohort_of=lambda face: taken if self.network.face_plate(face) == 'C'
                        else 'inherited-'+self.network.face_plate(face))
        with self.assertRaises(T.TransferRefused):
            self.stepped(self.split(groups=(('history-a1', (self.faces[0],)),)), state=state)

    def test_a_cohort_carried_by_a_regional_return_is_not_split(self):
        material = self.plain.state.material

        class Carried:                       # the only part of a regional return the check reads
            pieces = ((self.faces[0], (('inherited-A', (1.,)),)),)
        with self.assertRaises(X.SplitRefused):
            X.applied(self.plain.state.network, material, (self.split(),), 1, (Carried(),))
        result, _ = X.applied(self.plain.state.network, material, (self.split(),), 1, ())
        self.assertTrue(result.closure()['identity_exact'])

    def test_a_cohort_carried_by_a_real_regional_return_is_not_split(self):
        """splits-4: a real RegionalReturn through T.advance (test_i03_bridges' carried route). A split changes the
        interval's forcing identity, so the return is extracted against the split motion itself (splits-2)."""
        import test_i03_bridges as TB
        from atlas_tectonics import integration_bridges as B
        rule = TB.control('bridge_return_commit')
        state = F.crust(F.three_plates())
        end = state.network.time_s+F.MYR_S
        plain = T.advance(state, F.one_plate_motion(rule['turn_deg']), end_time_s=end)

        def returned(split):
            motion = F.one_plate_motion(rule['turn_deg'], history_splits=(split,))
            extract = B.extract(state, TB.footprint(rule), motion, F.MYR_S)
            carried = B.carried(extract, TB.unchanged(extract))
            return carried, F.one_plate_motion(rule['turn_deg'], history_splits=(split,), regional_returns=(carried,))
        carried, motion = returned(X.HistorySplit('inherited-A', (('history-a1',
                                                                   tuple(endpoint_faces(plain, 'inherited-A')[:1])),)))
        self.assertIn('inherited-A', {cohort for _, face in carried.pieces for cohort, _ in face})
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, motion, end_time_s=end)
        self.assertIn('regional return', str(caught.exception))
        carried, motion = returned(X.HistorySplit('inherited-B', (('history-b1',
                                                                   tuple(endpoint_faces(plain, 'inherited-B')[:1])),)))
        self.assertNotIn('inherited-B', {cohort for _, face in carried.pieces for cohort, _ in face})
        step = T.advance(state, motion, end_time_s=end)                     # a cohort the return does not carry
        self.assertEqual(restored(state, step).state_id, step.state.state_id)
        # N4: a return extracted for the split-free motion is stale for the split motion (history_splits stays in
        # the bridges' forcing identity), even though it carries no split cohort.
        free = B.extract(state, TB.footprint(rule), F.one_plate_motion(rule['turn_deg']), F.MYR_S)
        stale = B.carried(free, TB.unchanged(free))
        split = X.HistorySplit('inherited-B', (('history-b1', tuple(endpoint_faces(plain, 'inherited-B')[:1])),))
        with self.assertRaises(B.BridgeRefused) as caught:
            T.advance(state, F.one_plate_motion(rule['turn_deg'], history_splits=(split,), regional_returns=(stale,)),
                      end_time_s=end)
        self.assertEqual(caught.exception.code, B.STALE_GEOMETRY)

    def test_motion_identity_and_record(self):
        plain = F.one_plate_motion(DEGREES)
        self.assertNotIn('history_splits', plain.record())
        self.assertEqual(T._motion(plain.record()).motion_id, plain.motion_id)
        motion = F.one_plate_motion(DEGREES, history_splits=(self.split(),))
        self.assertNotEqual(motion.motion_id, plain.motion_id)
        self.assertEqual(T._motion(motion.record()).motion_id, motion.motion_id)
        record = motion.record()
        record['history_splits'][0]['groups'][0][0] = 'history-other'
        with self.assertRaises(T.LedgerError):
            T._motion(record)
        split = self.split()
        self.assertEqual(X.HistorySplit.from_record(split.record()), split)
        shuffled = X.HistorySplit('inherited-A', tuple(reversed([(h, tuple(reversed(f))) for h, f in split.groups])))
        self.assertEqual(shuffled, split)

    def test_pre_i05_identities_are_kept_bit_for_bit(self):
        """A motion without splits keeps the identities the code before I05 issued (the scratch baseline, 30a79e6 +
        I04a, run on 4 October 2026): the motion, its overlap map and the successor state, bit for bit."""
        baseline = dict(motion='e9008bd675000efed6160468da0c261c6585b0e700c3bde386b93c3b927b3712',
                        map='6400d2a45397223a235f09ae6d42408cf97a7a5fa11724df2b9e30b90a47b105',
                        state='403ef26f5c13b452d206edcc48cfd5411c626f805f1d5727fcac8979b9a13bdd',
                        still='d6853a888ff9ed2ed0d8d4e447a6f657b98fe5ed3338fdd63e8087f7f687c733',
                        later='cdb4b86c5811c5436f7072b743d924347e1d3d7cd8dc485d4e6c2fbd7a1ae7b4')
        self.assertEqual((self.plain.motion.motion_id, self.plain.map.map_id, self.plain.state.state_id),
                         (baseline['motion'], baseline['map'], baseline['state']))
        self.assertEqual(T.Motion(0, 1, {p: F.IDENTITY for p in 'ABC'}).motion_id, baseline['still'])
        self.assertEqual(F.one_plate_motion(.4, step=3).motion_id, baseline['later'])
        split = F.one_plate_motion(DEGREES, history_splits=(self.split(),))
        self.assertNotEqual(split.motion_id, baseline['motion'])

    def test_frame_independence(self):
        """The same split about a tilted axis gives the same pieces, cohorts and exact accounts to the I03 tolerance."""
        tilted = F.crust(F.three_plates(tilt=TILT))
        motion = F.one_plate_motion(DEGREES, tilt=TILT, history_splits=(self.split(),))
        turned = T.advance(tilted, motion, end_time_s=tilted.network.time_s+F.MYR_S)
        step = self.stepped(self.split())
        ours = sorted((p.face_id, p.cohort_id, p.area_m2) for p in step.state.material.pieces())
        theirs = sorted((p.face_id, p.cohort_id, p.area_m2) for p in turned.state.material.pieces())
        self.assertEqual([row[:2] for row in ours], [row[:2] for row in theirs])
        for (_, _, a), (_, _, b) in zip(ours, theirs):
            self.assertLessEqual(abs(a-b), F.tolerance('relative')*max(a, b))
        self.assertEqual({r.cohort_id: r.history_id for r in step.state.material.cohorts},
                         {r.cohort_id: r.history_id for r in turned.state.material.cohorts})


if __name__ == '__main__':
    unittest.main()
