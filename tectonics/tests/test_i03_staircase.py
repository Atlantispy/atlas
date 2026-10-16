"""Actual ridge-transform staircase material controls, retaining the existing I03 tolerances.

The fixture's one transform is an exact great circle; this does not admit off-equator small-circle transforms.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import replace
from fractions import Fraction
import math
from pathlib import Path
import sys
import tempfile
import time
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i03_fixtures as F
import i03_staircase_fixtures as Q
import i02_workflow_fixtures as F2
from atlas_tectonics import integration_clock as K
from atlas_tectonics import integration_ledger as L
from atlas_tectonics import integration_sphere as S
from atlas_tectonics import integration_transfer as T


class StaircaseMaterial(unittest.TestCase):
    def check_step(self, parent, step, degrees, fraction):
        network, material = step.state.network, step.state.material
        self.assertTrue(material.closure()['identity_exact'])
        self.assertLessEqual(abs(network.statistics['area_residual_sr']), F.tolerance('area_closure_absolute_sr'))
        for index, area in enumerate(network.face_area_m2):
            held = math.fsum(material.stock[material.piece_face == index, 0])
            self.assertLessEqual(abs(held-area), max(F.tolerance('relative')*area,
                                                      float(material.occupancy_allowance_m2[index])))
        expected = Q.expected_birth_area(degrees)
        births = step.summary()['births']
        self.assertAlmostEqual(sum(float(Fraction(row['area_m2'])) for row in births)/expected,
                               1., delta=F.tolerance('relative'))
        for row in births:
            share = fraction if row['side'] == 'left' else 1-fraction
            self.assertAlmostEqual(float(Fraction(row['area_m2']))/(expected*.5*share),
                                   1., delta=F.tolerance('relative'))
            self.assertNotIn('transient_consumption', row)
        self.assertFalse(step.map._motion.transient)
        self.assertFalse(any(Q.TRANSFORM in party for party in step.map._motion.parties))
        consumed = step.summary()['consumption_accuracy'][Q.TRENCH]['swept_area_m2']
        self.assertAlmostEqual(consumed/expected, 1., delta=F.tolerance('relative'))
        restored = T.restored(parent, {'sphere': step.record(), 'transfers': []}, step.arrays())
        self.assertEqual(restored.state_id, step.state.state_id)
        return restored

    def test_symmetric_spreading_survives_three_intervals_and_replay(self):
        state = Q.state()
        histories = {}
        for k in range(3):
            step = T.advance(state, Q.motion(.1, step=k), end_time_s=(k+1)*F.MYR_S)
            state = self.check_step(state, step, .1, .5)
            for cohort in state.material.cohorts:
                record = (cohort.formation_start_s, cohort.formation_end_s, cohort.history_id)
                if cohort.cohort_id in histories:
                    self.assertEqual(record, histories[cohort.cohort_id])
                histories[cohort.cohort_id] = record
        self.assertEqual(state.network.step, 3)

    def test_endpoint_accretion_fractions_keep_the_same_material_path(self):
        for fraction, side in ((0., 'right'), (1., 'left')):
            with self.subTest(fraction=fraction):
                state = Q.state(fraction=fraction)
                supplies = tuple(F.supply(ridge, side) for ridge in Q.RIDGES)
                for k in range(2):
                    step = T.advance(state, Q.motion(.1, step=k, supplies=supplies), end_time_s=(k+1)*F.MYR_S)
                    state = self.check_step(state, step, .1, fraction)

    def test_tilted_axes_preserve_two_intervals_and_birth_accounts(self):
        plain, tilted = Q.state(), Q.state(tilt=F.TILT)
        for k in range(2):
            a = T.advance(plain, Q.motion(.1, step=k), end_time_s=(k+1)*F.MYR_S)
            b = T.advance(tilted, Q.motion(.1, step=k, tilt=F.TILT), end_time_s=(k+1)*F.MYR_S)
            plain = self.check_step(plain, a, .1, .5)
            tilted = self.check_step(tilted, b, .1, .5)
            self.assertEqual(plain.network.vertex_ids, tilted.network.vertex_ids)
            angles = F.angle(F.TILT.apply(plain.network.vertex_direction), tilted.network.vertex_direction)
            self.assertLessEqual(float(np.max(angles)), F.tolerance('angular_absolute_rad'))
            for name, amount in plain.material.totals().items():
                self.assertLessEqual(abs(tilted.material.totals()[name]-amount),
                                     F.tolerance('relative')*max(abs(amount), 1.))

    def test_nonparallel_transform_still_refuses(self):
        state = Q.state()
        motion = Q.motion(.1, rotations={'A': F.IDENTITY,
                                        'B': F.Rotation.from_axis_angle((1., 0., 0.), math.radians(.1))})
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, motion, end_time_s=F.MYR_S)
        self.assertEqual(caught.exception.code, T.TRANSFORM_NOT_SLIP_PARALLEL)

    def test_a_moving_material_seam_cannot_pass_its_neighbour(self):
        state = T.advance(Q.state(), Q.motion(.1), end_time_s=F.MYR_S).state
        identity, stock = state.state_id, state.material.stock.copy()
        # The far-side seam advances past the retained carrier corner inside the transform; the two physical
        # ridge endpoints themselves remain distinct. This is a material-seam collision, not C5 end collapse.
        with self.assertRaisesRegex(T.TransferRefused, 'material seam.*collide with or pass'):
            T.advance(state, Q.motion(20., step=1), end_time_s=2*F.MYR_S)
        self.assertEqual(state.state_id, identity)
        np.testing.assert_array_equal(state.material.stock, stock)

    def test_an_explicit_carrier_split_uses_conservative_transform_remapping(self):
        state = T.advance(Q.state(), Q.motion(.1), end_time_s=F.MYR_S).state
        network = state.network
        trace = next(b for b in network.boundaries if b.boundary_id == Q.TRANSFORM)
        seam = next(name for name in trace.vertex_ids if name.endswith('|B|1'))
        face = next(f for f in network.faces if f.plate_id == 'A' and seam in f.vertex_ids)
        i = face.vertex_ids.index(seam)
        ring = face.vertex_ids[i:]+face.vertex_ids[:i]
        j = next(k for k in range(2, len(ring)-1)
                 if abs(network.vertex_direction[network.vertex_ids.index(ring[k]), 2]) > .1)
        first = replace(face, face_id=face.face_id+'-split0', vertex_ids=ring[:j+1])
        second = replace(face, face_id=face.face_id+'-split1', vertex_ids=(ring[0],)+ring[j:])
        faces = tuple(f for f in network.faces if f.face_id != face.face_id)+(first, second)
        still = T.Motion(1, 2, {'A': F.IDENTITY, 'B': F.IDENTITY}, mesh=T.Mesh(faces))
        remeshed = T.advance(state, still, end_time_s=2*F.MYR_S).state
        self.assertTrue(remeshed.material.closure()['identity_exact'])
        after = T.advance(remeshed, Q.motion(.01, step=2), end_time_s=3*F.MYR_S).state
        self.assertTrue(after.material.closure()['identity_exact'])
        cohort_id = 'ridge-north|right|0-1'

        def selected(sphere):
            m = sphere.material
            c = next(i for i, row in enumerate(m.cohorts) if row.cohort_id == cohort_id)
            return m.cohorts[c], {sphere.network.face_ids[int(face)]: stock
                                 for face, cohort, stock in zip(m.piece_face, m.piece_cohort, m.stock) if cohort == c}

        before_record, old = selected(remeshed)
        after_record, new = selected(after)
        self.assertEqual(before_record, after_record)   # formation interval and history do not reset
        for k in range(len(remeshed.material.columns)):
            a, b = math.fsum(row[k] for row in old.values()), math.fsum(row[k] for row in new.values())
            self.assertLessEqual(abs(a-b), F.tolerance('relative')*max(abs(a), 1.))
        gained, = set(new)-set(old)
        # The caller has made a shared sampling corner by splitting the carrier face. The ordinary transform
        # remap keeps that corner and transfers the advected cohort across it. Its crossing is independently the
        # spherical triangle between 0.1 and 0.11 degrees on the equator, closing at (0.11, 30): no clipping code.
        a, b, c = (np.asarray(F.direction(lon, lat)) for lon, lat in ((.1, 0.), (.11, 0.), (.11, 30.)))
        expected = 2*math.atan2(abs(float(a @ np.cross(b-a, c-a))), 1+float(a @ b+b @ c+c @ a))*F.RADIUS_M**2
        self.assertAlmostEqual(float(new[gained][0])/expected, 1., delta=F.tolerance('relative'))
        donor = old['ridge-north|right|1|0000']
        for k, value in enumerate(new[gained]):
            amount = expected*donor[k]/donor[0]
            self.assertLessEqual(abs(value-amount), F.tolerance('relative')*max(abs(amount), 1.))

    def test_saved_mesh_rename_reopens_and_continues_actual_staircase_motion(self):
        network = Q.network()
        rebound = S.build_network(sphere=network.sphere,
                                  vertices=dict(zip(network.vertex_ids, network.vertex_direction)),
                                  faces=network.faces, plates=network.plates, boundaries=network.boundaries,
                                  epoch_id=F2.EPOCH, time_s=F2.START)
        state = F.crust(rebound)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'history.sqlite'
            with F2.store(path) as store:
                ledger, _ = L.Ledger.create(store, F2.root(8), sphere=state)
                clock = K.Clock(ledger)
                proposal = Q.motion(.1)
                endpoint = T.advance(state, proposal, end_time_s=clock.time_at(1)).state.network
                renamed = tuple(replace(face, face_id='renamed-'+face.face_id) for face in endpoint.faces)
                proposal = replace(proposal, mesh=T.Mesh(renamed))
                first = clock.advance(steps=1, deadline=time.perf_counter()+60., transfers=(proposal,))
                self.assertEqual(first.status, K.COMPLETED, first.reason)
                saved = ledger.sphere(first.head)
                self.assertTrue(all(name.startswith('renamed-') for name in saved.network.face_ids))
                follow = Q.motion(.1, step=1)
                expected = T.advance(saved, follow, end_time_s=clock.time_at(2)).state.state_id
                ledger_id = ledger.ledger_id
            with F2.store(path) as store:
                reopened = L.Ledger.open(store, ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
                self.assertEqual(reopened.verify_chain().key, first.head.key)
                self.assertEqual(reopened.sphere(first.head).state_id, saved.state_id)
                self.assertEqual(first.head.metadata()['sphere']['motion']['mesh_id'], proposal.mesh.mesh_id)
                second = K.Clock(reopened).advance(steps=1, deadline=time.perf_counter()+60., transfers=(follow,))
                self.assertEqual(second.status, K.COMPLETED, second.reason)
                self.assertEqual(reopened.sphere(second.head).state_id, expected)
                self.assertEqual(reopened.verify_chain().key, second.head.key)


if __name__ == '__main__':
    unittest.main()
