"""I03.4 joint geometry commits: supplied topology events through the I02 clock and ledger. WORKING NON-CANON.

A split, a merge and a ridge jump (prescribed history) ride in the Motion of the interval they end and are committed
with its steps or not at all. Ownership changes by whole faces, so every ownership intersection is exact and no
material moves. Every value comes from the event_* controls of cases/i03_controls_v3.json.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction
import json
import math
import os
from unittest import mock
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import numpy as np
from threadpoolctl import threadpool_limits

import atlas_tectonics
from atlas_tectonics import integration_clock as K, integration_events as E, integration_ledger as L
from atlas_tectonics import integration_sphere as S, integration_state as I, integration_transfer as T

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import i02_workflow_fixtures as F2
import i03_fixtures as F

SRC = str(Path(atlas_tectonics.__file__).resolve().parents[1])
CASE3 = json.loads((F.CASES/'i03_controls_v3.json').read_text(encoding='utf-8'))
MYR = F.MYR_S
ANGULAR = F.tolerance('angular_absolute_rad')
RELATIVE = F.tolerance('relative')
AREA_CLOSURE_SR = F.tolerance('area_closure_absolute_sr')
RESOURCES = F.CASE['resources']
STEPS = F.control('clock_commit')['column_steps']
FIX = {}


def control(name):
    return CASE3['controls'][name]


def meridian(i):
    return ('S',)+tuple(F.vertex(i, j) for j in range(5))+('N',)


def faces_of(network, plate, keep=lambda name: True):
    return tuple(sorted(f.face_id for f in network.faces if f.plate_id == plate and keep(f.face_id)))


def still(network, step=0, events=(), end=None):
    """An interval in which no plate moves, ending with ``events``."""
    return T.Motion(step, step+1 if end is None else end, {p: F.IDENTITY for p in network.plate_ids}, events=events)


def meridian_split(network, event_id='split-a', names=('A1', 'A2'), boundary_id=None, plate='A', at=None,
                   time_s=MYR):
    """Plate ``plate`` divided along meridian ``at`` (the control's, 3, by default) at ``time_s``: the sector east of
    it to the east, every other face of the plate to the west."""
    rule = control('event_split_meridian')
    at = rule['boundary']['meridian'] if at is None else at
    prefix = 's%02d-' % at
    east = faces_of(network, plate, lambda name: name.startswith(prefix))
    west = faces_of(network, plate, lambda name: not name.startswith(prefix))
    boundary = S.Boundary(boundary_id or rule['boundary']['boundary_id'], S.RIDGE, names[0], names[1],
                          meridian(at), S.Origin(S.EVENT, event_id),
                          accretion_fraction=rule['boundary']['accretion_fraction'])
    return E.Split(event_id, plate, ((names[0], west), (names[1], east)), boundary, time_s)


def latitude_split(network, event_id='split-lat', plate='A', names=None, boundary_id=None, meridians=(2, 3, 4),
                   time_s=MYR):
    """Plate ``plate`` divided along the control's latitude, eastward through ``meridians``: north on the left."""
    rule = control('event_split_latitude')
    j = rule['boundary']['latitude_index']
    north = faces_of(network, plate, lambda name: name.split('-')[1] in ('b02', 'b03', 'north'))
    south = faces_of(network, plate, lambda name: name.split('-')[1] in ('b00', 'b01', 'south'))
    names = names or tuple(rule['parts'])
    boundary = S.Boundary(boundary_id or rule['boundary']['boundary_id'], S.TRANSFORM, names[0], names[1],
                          tuple(F.vertex(i, j) for i in meridians), S.Origin(S.EVENT, event_id))
    return E.Split(event_id, plate, ((names[0], north), (names[1], south)), boundary, time_s)


def ridge_jump(endpoint):
    """The control's jump at the end of the interval it closes, its parts read from that interval's endpoint."""
    rule = control('event_ridge_jump')
    split, merge = rule['split'], rule['merge']
    slice_, east = tuple(split['parts'])
    part = meridian_split(endpoint, split['event_id'], (slice_, east), split['boundary_id'], split['plate'],
                          time_s=endpoint.time_s)
    return E.RidgeJump('jump', part, E.Merge(merge['event_id'], tuple(merge['plates']), merge['new_plate'],
                                             endpoint.time_s))


def placed(network, name):
    """A face's outer ring on the sphere, every vertex: its plate-frame coordinates placed by its plate's frame."""
    k = network.face_ids.index(name)
    return S._placed(dict(network.frames)[network.faces[k].plate_id], network.face_coordinates(k)[0])


def close(test, value, expected, relative=RELATIVE):
    test.assertLessEqual(abs(value-expected), relative*abs(expected), (value, expected))


def pieces(state):
    """{(face ID, cohort): stock bytes}: what sits where, independent of the face order."""
    material, names = state.material, state.network.face_ids
    return {(names[int(material.piece_face[k])], material.cohorts[int(material.piece_cohort[k])].cohort_id):
            material.stock[k].tobytes() for k in range(len(material.piece_face))}


def areas(network):
    return {name: float(network.face_area_m2[k]) for k, name in enumerate(network.face_ids)}


def restored(parent, step):
    return T.restored(parent, {'sphere': step.record(), 'transfers': []}, step.arrays())


def refused(test, text, state, motion, end_time_s=MYR):
    with test.assertRaises(T.TransferRefused) as caught:
        T.advance(state, motion, end_time_s=end_time_s)
    test.assertIn(text, str(caught.exception))
    return caught.exception


class Unchanged:
    def assert_material_unmoved(self, before, after):
        self.assertEqual(pieces(after), pieces(before))
        for column in before.material.columns:
            self.assertEqual(after.material.exact_total(column), before.material.exact_total(column))
        self.assertEqual(after.material.supplied(), before.material.supplied())
        self.assertTrue(after.material.closure()['identity_exact'])
        self.assertEqual(areas(after.network), areas(before.network))


class SplitTests(Unchanged, unittest.TestCase):
    def test_a_meridian_split_divides_whole_faces_and_moves_no_material(self):
        state = F.crust(F.three_plates())
        split = meridian_split(state.network)
        step = T.advance(state, still(state.network, events=(split,)), end_time_s=MYR)
        after = step.state
        network = after.network
        self.assertEqual(network.plate_ids, ('A1', 'A2', 'B', 'C'))
        owners = {f.face_id: f.plate_id for f in network.faces}
        for name, faces in split.parts:
            self.assertTrue(all(owners[face] == name for face in faces))
        self.assert_material_unmoved(state, after)
        self.assertEqual(network.vertex_direction.tobytes(), state.network.vertex_direction.tobytes())
        self.assertEqual(network.lineage.events, ('split-a',))
        self.assertEqual(network.lineage.retired_plate_ids, ('A',))
        self.assertEqual({p.plate_id: p.parent_plate_ids for p in network.plates if p.plate_id in ('A1', 'A2')},
                         {'A1': ('A',), 'A2': ('A',)})
        sides = {b.boundary_id: (b.left_plate_id, b.right_plate_id) for b in network.boundaries}
        self.assertEqual(sides, {'boundary-m00': ('B', 'C'), 'boundary-m02': ('C', 'A1'),
                                 'boundary-m04': ('A2', 'B'), 'ridge-split': ('A1', 'A2')})
        self.assertEqual(step.record()['events'], [split.record()])
        self.assertEqual(restored(state, step).state_id, after.state_id)
        S.verified(after)

    def test_a_split_across_the_plate_cuts_the_records_it_meets(self):
        rule = control('event_split_latitude')
        state = F.crust(F.three_plates())
        split = latitude_split(state.network)
        step = T.advance(state, still(state.network, events=(split,)), end_time_s=MYR)
        network = step.state.network
        self.assertEqual(network.lineage.retired_boundary_ids, ('boundary-m02', 'boundary-m04'))
        north, south = tuple(rule['parts'])
        cut = {b.boundary_id: (b.left_plate_id, b.right_plate_id, b.vertex_ids) for b in network.boundaries}
        m2, m4 = meridian(2), meridian(4)
        self.assertEqual(cut['boundary-m02|split-lat|0'], ('C', south, m2[:4]))
        self.assertEqual(cut['boundary-m02|split-lat|1'], ('C', north, m2[3:]))
        self.assertEqual(cut['boundary-m04|split-lat|0'], (south, 'B', m4[:4]))
        self.assertEqual(cut['boundary-m04|split-lat|1'], (north, 'B', m4[3:]))
        junctions = {j.vertex_id for j in network.junctions}
        self.assertEqual(junctions, {'S', 'N', F.vertex(2, 2), F.vertex(4, 2)})
        self.assert_material_unmoved(state, step.state)
        self.assertEqual(restored(state, step).state_id, step.state.state_id)
        S.verified(step.state)


class MergeTests(Unchanged, unittest.TestCase):
    def test_a_merge_unites_whole_faces_and_retires_the_suture(self):
        rule = control('event_merge')
        state = F.crust(F.three_plates())
        merge = E.Merge('merge-ab', tuple(rule['plates']), rule['new_plate'], MYR)
        step = T.advance(state, still(state.network, events=(merge,)), end_time_s=MYR)
        network = step.state.network
        self.assertEqual(network.plate_ids, ('AB', 'C'))
        self.assertEqual(faces_of(network, 'AB'), tuple(sorted(faces_of(state.network, 'A')
                                                                 + faces_of(state.network, 'B'))))
        self.assertEqual(network.lineage.retired_boundary_ids, ('boundary-m04',))
        self.assertEqual(network.lineage.retired_plate_ids, ('A', 'B'))
        self.assertEqual(network.plate('AB').parent_plate_ids, ('A', 'B'))
        self.assert_material_unmoved(state, step.state)
        self.assertEqual(restored(state, step).state_id, step.state.state_id)

    def test_a_merge_after_motion_keeps_every_vertex_where_it_was(self):
        rule = control('event_merge_after_motion')
        state = F.crust(F.three_plates())
        moved = T.advance(state, F.one_plate_motion(rule['turn_deg']), end_time_s=MYR).state
        merge = E.Merge('merge-ab', tuple(rule['plates']), rule['new_plate'], 2*MYR)
        step = T.advance(moved, still(moved.network, 1, events=(merge,)), end_time_s=2*MYR)
        before, after = moved.network, step.state.network
        # The merged plate continues the larger plate (M1): A lost more at the trench than it gained at the ridge.
        area = before.plate_area_m2()
        self.assertLess(area['A'], area['B'])
        self.assertEqual(after.plate(rule['new_plate']).rotation.quaternion, before.plate('B').rotation.quaternion)
        self.assertEqual(after.vertex_ids, before.vertex_ids)
        gap = np.linalg.norm(after.vertex_direction-before.vertex_direction, axis=1)
        self.assertLessEqual(float(gap.max()), ANGULAR)
        self.assertEqual(pieces(step.state), pieces(moved))
        self.assertTrue(step.state.material.closure()['identity_exact'])
        self.assertEqual(restored(moved, step).state_id, step.state.state_id)


class MergeFrameTests(unittest.TestCase):
    def test_a_merge_carries_the_other_plate_into_the_continued_plates_frame(self):
        # Every plate turns 1 degree as one piece, then A alone 0.5 degrees: C's frame is a 1-degree turn and A's a
        # 1.5-degree one. Merging A into the larger C carries A's coordinates by the 0.5-degree difference.
        state = F.crust(F.three_plates())
        whole = T.advance(state, T.Motion(0, 1, {p: F.spin(1.) for p in 'ABC'}), end_time_s=MYR).state
        turned = T.advance(whole, F.one_plate_motion(.5, step=1), end_time_s=2*MYR).state
        before = turned.network
        area = before.plate_area_m2()
        self.assertGreater(area['C'], area['A'])
        step = T.advance(turned, still(before, 2, events=(E.Merge('merge-ac', ('A', 'C'), 'AC', 3*MYR),)),
                         end_time_s=3*MYR)
        after = step.state.network
        self.assertEqual(after.plate('AC').rotation.quaternion, before.plate('C').rotation.quaternion)
        self.assertEqual(dict(after.frames)['AC'].quaternion, dict(before.frames)['C'].quaternion)
        for name in faces_of(before, 'A'):
            self.assertLessEqual(float(np.abs(placed(after, name)-placed(before, name)).max()), ANGULAR, name)
        self.assertEqual(pieces(step.state), pieces(turned))
        self.assertEqual(restored(turned, step).state_id, step.state.state_id)


class RidgeJumpTests(unittest.TestCase):
    def test_a_ridge_jump_across_a_spreading_ridge_captures_the_slice(self):
        rule = control('event_ridge_jump')
        state = F.crust(F.three_plates())
        motion = F.one_plate_motion(rule['turn_deg'])
        endpoint = T.advance(state, motion, end_time_s=MYR).state.network
        jump = ridge_jump(endpoint)
        step = T.advance(state, F.one_plate_motion(rule['turn_deg'], events=(jump,)), end_time_s=MYR)
        network = step.state.network
        slice_, east = tuple(rule['split']['parts'])
        grown = rule['merge']['new_plate']
        # Capture (coordinator's condition): the slice moved with A up to the jump and its accounts transfer exactly.
        plain = T.advance(state, motion, end_time_s=MYR).state
        sliced = dict(jump.split.parts)[slice_]
        self.assertEqual({k: v for k, v in pieces(step.state).items() if k[0] in sliced},
                         {k: v for k, v in pieces(plain).items() if k[0] in sliced})
        for name in sliced:
            self.assertLessEqual(float(np.abs(placed(network, name)-placed(plain.network, name)).max()), ANGULAR)
        # The grown plate continues the plate across the old ridge: its frame and total rotation (M1), whatever the
        # slice is called.
        self.assertEqual(network.plate(grown).rotation.quaternion, state.network.plate('C').rotation.quaternion)
        self.assertEqual(network.plate_ids, tuple(sorted((east, 'B', grown))))
        self.assertIn('boundary-m02', network.lineage.retired_boundary_ids)
        self.assertEqual(set(network.lineage.retired_plate_ids), {'A', slice_, 'C'})
        self.assertEqual(network.lineage.events, ('jump', 'jump-split', 'jump-merge'))
        sides = {b.boundary_id: (b.kind, b.left_plate_id, b.right_plate_id) for b in network.boundaries}
        self.assertEqual(sides['ridge-new'], (S.RIDGE, grown, east))
        self.assertTrue(step.state.material.closure()['identity_exact'])
        self.assertEqual(restored(state, step).state_id, step.state.state_id)
        g = rule['grown_turn_deg']
        follow = T.Motion(1, 2, {east: F.spin(g+rule['follow_turn_deg']), 'B': F.spin(g), grown: F.spin(g)},
                          supplies=F.both_sides('ridge-new'), sinks=(F.sink('boundary-m04'),))
        later = T.advance(step.state, follow, end_time_s=2*MYR)
        # ... and with its new plate after: the grown plate turned g, A-east g + follow, so the slice must turn g.
        for name in sliced:
            moved = placed(later.state.network, name)
            self.assertLessEqual(float(np.abs(moved-F.spin(g).apply(placed(network, name))).max()), ANGULAR)
            self.assertGreater(float(np.abs(moved-F.spin(g+rule['follow_turn_deg']).apply(
                placed(network, name))).max()), 1e3*ANGULAR)
        born = [f for f in later.state.network.faces if f.face_id.startswith('ridge-new|')]
        self.assertEqual({f.plate_id for f in born}, {grown, east})
        self.assertTrue(later.state.material.closure()['identity_exact'])
        self.assertEqual(restored(step.state, later).state_id, later.state.state_id)


class FindingTests(unittest.TestCase):
    # The I03.4 verifier's findings (3 October 2026), each a test that failed before its fix.
    def merged_mesh(self, network):
        """Faces s02-b01 and s02-b02 of plate A merged into one face (a mesh change of that interval)."""
        faces = {f.face_id: f for f in network.faces}
        del faces['s02-b01'], faces['s02-b02']
        faces['s02-merged'] = S.Face('s02-merged', 'A', (F.vertex(2, 1), F.vertex(3, 1), F.vertex(3, 2), F.vertex(3, 3),
                                                       F.vertex(2, 3), F.vertex(2, 2)))
        return T.Mesh(tuple(faces.values()))

    def test_c1_a_mesh_change_and_events_in_one_interval_restore(self):
        state = F.crust(F.three_plates())
        mesh = self.merged_mesh(state.network)
        plates = {p: F.IDENTITY for p in state.network.plate_ids}
        endpoint = T.advance(state, T.Motion(0, 1, plates, mesh=mesh), end_time_s=MYR).state.network
        for events in ((meridian_split(endpoint),), (E.Merge('merge-ab', ('A', 'B'), 'AB', MYR),)):
            with self.subTest(events=[e.event_id for e in events]):
                step = T.advance(state, T.Motion(0, 1, plates, mesh=mesh, events=events), end_time_s=MYR)
                self.assertEqual(restored(state, step).state_id, step.state.state_id)

    def test_i1_a_new_record_is_accepted_whatever_its_name(self):
        state = F.crust(F.sector_world())                 # every meridian a ridge: records tie at the poles
        for name in ('z-ridge', 'a-ridge', 'boundary-l01'):
            with self.subTest(name=name):
                split = meridian_split(state.network, 'split-a', ('A1', 'A2'), name, 'A', at=1)
                step = T.advance(state, still(state.network, events=(split,)), end_time_s=MYR)
                self.assertEqual(restored(state, step).state_id, step.state.state_id)

    def test_i3_an_event_on_a_plate_another_event_creates_is_one_joint_proposal(self):
        state = F.crust(F.three_plates())
        split = meridian_split(state.network)
        for merge_id in ('a-merge', 'z-merge'):
            with self.subTest(merge_id=merge_id):
                merge = E.Merge(merge_id, ('A2', 'B'), 'A2B', MYR)
                refused(self, 'one joint proposal', state, still(state.network, events=(split, merge)))

    def test_m4_malformed_events_are_refused_not_raised(self):
        split = meridian_split(F.three_plates())
        (first, faces), (second, others) = split.parts
        for parts in (((first, (1, 2)), (second, others)), ((first, faces, 'extra'), (second, others)),
                      ((first, faces),)):
            with self.subTest(parts=str(parts)[:40]), self.assertRaises(E.EventRefused):
                E.Split('split-a', 'A', parts, split.boundary, MYR)
        bad = S.Boundary('ridge|split', S.RIDGE, first, second, split.boundary.vertex_ids, split.boundary.origin,
                         accretion_fraction=.5)
        with self.assertRaises(E.EventRefused):
            E.Split('split-a', 'A', split.parts, bad, MYR)



class MergeTieTests(unittest.TestCase):
    def merged(self, north):
        rule = control('merge_tie')
        lons, lats = F.mesh('sector6')
        vertices, rings = F.sector_mesh(lons, lats)
        owner = lambda name: north if name.split('-')[1] in ('b02', 'b03', 'north') else 'south'
        network = S.build_network(
            sphere=F.sphere(), vertices=vertices, faces=tuple(S.Face(n, owner(n), r) for n, r in rings.items()),
            plates=tuple(S.Plate(p, F.IDENTITY) for p in sorted((north, 'south'))),
            boundaries=(S.Boundary('equator', S.TRANSFORM, north, 'south', tuple(F.vertex(i, 2) for i in range(len(lons))),
                                   F.origin(), closed=True, carrier_side='right'),),
            epoch_id=F.EPOCH, time_s=F.START)
        state = F.crust(network, cohort_of=lambda face: 'inherited', exteriors=())
        moved = T.advance(state, T.Motion(0, 1, {north: F.spin(rule['turn_deg']), 'south': F.IDENTITY}),
                          end_time_s=F.START+MYR).state
        merged = T.advance(moved, T.Motion(1, 2, {north: F.IDENTITY, 'south': F.IDENTITY}, events=(
            E.Merge('m', (north, 'south'), 'NS', F.START+2*MYR),)), end_time_s=F.START+2*MYR).state
        return moved, merged

    def test_the_merged_plate_continues_the_larger_exact_account_whatever_the_names(self):
        for north in ('north', 'znorth'):
            with self.subTest(north=north):
                moved, merged = self.merged(north)
                measured = moved.network.plate_area_m2()
                self.assertEqual(measured[north], measured['south'])                # measured areas tie (p3)
                exact = E._exact_areas(moved.network, moved.material)
                self.assertGreater(exact[north], exact['south'])                    # the exact accounts do not
                self.assertEqual(merged.network.plate('NS').rotation.quaternion,
                                 moved.network.plate(north).rotation.quaternion)


class JumpContinuationTests(unittest.TestCase):
    def test_the_grown_plate_continues_the_plate_across_even_when_it_is_smaller(self):
        # C spans 0-60 degrees and A 60-240, so the jump's slice of A (60-180) is larger than C: the rule must still
        # continue C, the plate across the old ridge, not the larger plate.
        world = F.three_plates(plates=('C', 'A', 'A', 'A', 'B', 'B'),
                               kinds={1: dict(kind=S.RIDGE, accretion_fraction=.5)})
        state = F.crust(world)
        motion = F.one_plate_motion(.5, ridge='boundary-m01')
        endpoint = T.advance(state, motion, end_time_s=MYR).state.network
        jump = ridge_jump(endpoint)
        slice_ = dict(jump.split.parts)
        rule = control('event_ridge_jump')
        name, grown = tuple(rule['split']['parts'])[0], rule['merge']['new_plate']
        sliced = sum(float(endpoint.face_area_m2[endpoint.face_ids.index(face)]) for face in slice_[name])
        self.assertGreater(sliced, endpoint.plate_area_m2()['C'])
        step = T.advance(state, F.one_plate_motion(.5, ridge='boundary-m01', events=(jump,)), end_time_s=MYR)
        network = step.state.network
        self.assertEqual(network.plate(grown).rotation.quaternion, endpoint.plate('C').rotation.quaternion)
        self.assertEqual(dict(network.frames)[grown].quaternion, dict(endpoint.frames)['C'].quaternion)
        self.assertEqual(restored(state, step).state_id, step.state.state_id)


def remeasured(before, after):
    """[(face, |delta|, D7'' bound, allowance before, allowance after, measure before)] for every face whose measure an
    event changed: ``before`` is the same interval without the event, ``after`` with it (one face order)."""
    radius = before.network.sphere.radius_m
    out = []
    for k, name in enumerate(after.network.face_ids):
        mu, again = float(before.network.face_area_m2[k]), float(after.network.face_area_m2[k])
        if mu != again:
            bound = E._reexpression_bound(before.network.face_coordinates(k), after.network.face_coordinates(k), again,
                                          radius)
            out.append((name, abs(again-mu), bound, float(before.material.occupancy_allowance_m2[k]),
                        float(after.material.occupancy_allowance_m2[k]), mu))
    return out


def perimeter(rings):
    return math.fsum(float(T._angle(a, b)) for ring in rings for a, b in zip(ring, np.roll(ring, -1, axis=0)))


class ReexpressionTests(unittest.TestCase):
    # D7'' (approved 3 October 2026 with conditions): a face an event carries into another frame is measured again;
    # within C7(R) + C7(R') + 4 eps P (the C7 terms zero above the C7 range) its allowance takes the exact change.
    def check_allowances(self, rows):
        for name, delta, bound, before, after, mu in rows:
            self.assertIsNotNone(bound, name)
            self.assertLessEqual(delta, bound, name)
            self.assertEqual(after, max(S.RELATIVE_TOLERANCE*mu, before)+delta, name)

    def slow_jump(self):
        slow, usual = F.control('clock_commit')['slow_then_normal_deg']
        state = F.crust(F.three_plates())
        first = T.advance(state, F.one_plate_motion(slow), end_time_s=MYR).state
        plain = T.advance(first, F.one_plate_motion(usual, step=1), end_time_s=2*MYR).state
        return first, plain, F.one_plate_motion(usual, step=1, events=(ridge_jump(plain.network),))

    def test_the_jump_after_the_slow_control_is_accepted(self):
        first, plain, motion = self.slow_jump()
        step = T.advance(first, motion, end_time_s=2*MYR)
        rows = remeasured(plain, step.state)
        self.assertTrue(rows)
        self.check_allowances(rows)
        self.assertTrue(step.state.material.closure()['identity_exact'])
        self.assertEqual(restored(first, step).state_id, step.state.state_id)

    def test_a_change_just_beyond_the_bound_is_refused(self):
        first, plain, motion = self.slow_jump()
        rows = remeasured(plain, T.advance(first, motion, end_time_s=2*MYR).state)
        name, delta, _, _, _, _ = max(rows, key=lambda row: row[1])
        k = plain.network.face_ids.index(name)
        bound = E._reexpression_bound

        def forged(limit):
            def at(old, new, area, radius):
                if np.array_equal(old[0], plain.network.face_coordinates(k)[0]):
                    return limit
                return bound(old, new, area, radius)
            return at
        with mock.patch.object(E, '_reexpression_bound', forged(math.nextafter(delta, 0.))):
            refused(self, 'beyond its D7', first, motion, 2*MYR)
        with mock.patch.object(E, '_reexpression_bound', forged(delta)):
            T.advance(first, motion, end_time_s=2*MYR)

    def test_a_face_above_the_c7_range_is_held_to_four_eps_perimeter(self):
        rule = control('reexpression_above_range')
        state = F.crust(F.three_plates())
        first = T.advance(state, F.one_plate_motion(rule['slow_turn_deg']), end_time_s=MYR).state
        plain = T.advance(first, still(first.network, 1), end_time_s=2*MYR).state
        merged = T.advance(first, still(first.network, 1, events=(E.Merge('merge-ac', ('A', 'C'), 'AC', 2*MYR),)),
                           end_time_s=2*MYR).state
        rows = remeasured(plain, merged)
        self.check_allowances(rows)
        radius = state.network.sphere.radius_m
        held = []
        for name, delta, bound, _, _, mu in rows:
            k = plain.network.face_ids.index(name)
            p = perimeter(merged.network.face_coordinates(k))
            ratio = mu/radius**2/p
            if ratio > 2*T.THIN_FACE_RATIO:
                self.assertEqual(bound, 4*np.finfo(float).eps*p*radius**2, name)      # no C7 term above the range
                width_km = 2*ratio*radius/1e3
                if 3 <= width_km <= 11 and delta > 0:
                    held.append((name, width_km, delta, bound))
        self.assertTrue(held, 'no face 3-11 km wide above the C7 range was measured again')

    def test_allowances_grow_only_where_a_merge_measures_again(self):
        rule = control('reexpression_repeated')
        s0 = F.crust(F.three_plates())
        s1 = T.advance(s0, F.one_plate_motion(rule['slow_turn_deg']), end_time_s=MYR).state
        old_c, old_a = faces_of(s1.network, 'C'), faces_of(s1.network, 'A')
        p2 = T.advance(s1, still(s1.network, 1), end_time_s=2*MYR).state
        s2 = T.advance(s1, still(s1.network, 1, events=(E.Merge('merge-ac', ('A', 'C'), 'AC', 2*MYR),)),
                       end_time_s=2*MYR).state
        first = remeasured(p2, s2)
        self.check_allowances(first)
        back = S.Boundary('ridge-back', S.RIDGE, 'C2', 'A2', meridian(2), S.Origin(S.EVENT, 'split-ac'),
                          accretion_fraction=.5)
        s3 = T.advance(s2, still(s2.network, 2, events=(E.Split('split-ac', 'AC', (('C2', old_c), ('A2', old_a)), back,
                                                                 3*MYR),)), end_time_s=3*MYR).state
        self.assertEqual(s3.material.occupancy_allowance_m2.tobytes(), s2.material.occupancy_allowance_m2.tobytes())
        turn = T.Motion(3, 4, {'A2': F.spin(rule['turn_deg']), 'B': F.IDENTITY, 'C2': F.IDENTITY},
                        supplies=F.both_sides('ridge-back'), sinks=(F.sink('boundary-m04'),))
        step4 = T.advance(s3, turn, end_time_s=4*MYR)
        s4 = step4.state
        changed = {s3.network.face_ids[row[0]] for row in step4.map.rows if row[0] >= 0}   # cut, consumed or remapped
        p5 = T.advance(s4, still(s4.network, 4), end_time_s=5*MYR).state
        s5 = T.advance(s4, still(s4.network, 4, events=(E.Merge('merge-back', ('A2', 'C2'), 'AC2', 5*MYR),)),
                       end_time_s=5*MYR).state
        second = remeasured(p5, s5)
        self.check_allowances(second)
        twice = {name for name, *_ in first} & {name for name, *_ in second}
        rode = twice-changed
        self.assertTrue(rode, 'no face measured again by both merges rode between them')
        allowance = lambda state, name: float(state.material.occupancy_allowance_m2[state.network.face_ids.index(name)])
        for name, delta, _, before, after, mu in second:
            if name in rode:
                # It rode between the merges with its allowance (split, turn, still interval), and grew at the second
                # merge by that merge's change alone: after the first it already exceeds 1e-12 mu.
                self.assertEqual(before, allowance(s2, name), name)
                self.assertGreaterEqual(before, S.RELATIVE_TOLERANCE*mu, name)
                self.assertEqual(after, before+delta, name)
                self.assertEqual(allowance(s1, name), 0., name)
        self.assertTrue(s5.material.closure()['identity_exact'])


class SimultaneousTests(unittest.TestCase):
    def events(self, network):
        return meridian_split(network), E.Merge('merge-bc', ('B', 'C'), 'BC', MYR)

    def test_disjoint_events_give_one_state_in_any_order(self):
        state = F.crust(F.three_plates())
        split, merge = self.events(state.network)
        one = T.advance(state, still(state.network, events=(split, merge)), end_time_s=MYR).state
        two = T.advance(state, still(state.network, events=(merge, split)), end_time_s=MYR).state
        self.assertEqual(one.state_id, two.state_id)
        self.assertEqual(one.network.lineage.events, ('merge-bc', 'split-a'))
        stage = {p: F.IDENTITY for p in state.network.plate_ids}
        ids = state.network.lineage.events+('merge-bc', 'split-a')
        forward = E._in_order(state.network, state.material, (merge, split), stage, None, None, ids)
        backward = E._in_order(state.network, state.material, (split, merge), stage, None, None, ids)
        self.assertEqual((forward[0].network_id, forward[1].material_id),
                         (backward[0].network_id, backward[1].material_id))

    def test_two_splits_that_cut_one_record_are_refused_with_their_cause(self):
        # V1 (coordinator, round 1): the latitude splits of A and of C touch disjoint plates, but both cut the ridge
        # between them at the equator; the cut records would be named after whichever ran first.
        state = F.crust(F.three_plates())
        net = state.network
        a = latitude_split(net, 'split-a', 'A', ('An', 'As'), 'cut-a', (2, 3, 4))
        c = latitude_split(net, 'split-c', 'C', ('Cn', 'Cs'), 'cut-c', (0, 1, 2))
        self.assertFalse(a.footprint() & c.footprint())
        for event in (a, c):                                          # each alone is valid
            T.advance(state, still(net, events=(event,)), end_time_s=MYR)
        refused(self, "both cut record 'boundary-m02'", state, still(net, events=(a, c)))

    def test_the_two_order_check_refuses_order_dependent_events_the_early_checks_miss(self):
        # V1: the reverse-order check is a safety net. With the early cut check bypassed, the same pair (the
        # coordinator's counterexample to 'disjoint footprints commute') is still refused, by the two-order check.
        state = F.crust(F.three_plates())
        net = state.network
        a = latitude_split(net, 'split-a', 'A', ('An', 'As'), 'cut-a', (2, 3, 4))
        c = latitude_split(net, 'split-c', 'C', ('Cn', 'Cs'), 'cut-c', (0, 1, 2))
        with mock.patch.object(E, '_cuts', lambda network, event: set()):
            refused(self, 'different networks in the two orders', state, still(net, events=(a, c)))

    def test_events_that_share_a_plate_are_one_joint_proposal(self):
        state = F.crust(F.three_plates())
        merge = E.Merge('merge-ab', ('A', 'B'), 'AB', MYR)
        refused(self, 'one joint proposal', state, still(state.network, events=(meridian_split(state.network),
                                                                                 merge)))


class RefusalTests(unittest.TestCase):
    def setUp(self):
        self.state = F.crust(F.three_plates())
        self.network = self.state.network

    def test_a_plate_cannot_retire_on_its_own(self):
        refused(self, 'cannot retire on its own', self.state,
                still(self.network, events=(E.Retire('r', 'A', MYR),)))

    def test_an_event_takes_effect_only_at_the_end_of_its_interval(self):
        # Design-note condition 1 (coordinator, 3 October 2026): nothing is applied in the middle of an interval.
        for time_s in (MYR/2, 2*MYR):
            with self.subTest(time_s=time_s):
                refused(self, 'takes effect only at the end of the interval', self.state,
                        still(self.network, events=(E.Merge('merge-ab', ('A', 'B'), 'AB', time_s),)))
        with self.assertRaises(E.EventRefused):
            E.Merge('merge-ab', ('A', 'B'), 'AB', float('nan'))

    def test_a_split_whose_new_record_ends_inside_the_plate_is_refused(self):
        split = meridian_split(self.network)
        short = S.Boundary('ridge-split', S.RIDGE, 'A1', 'A2', meridian(3)[:4], S.Origin(S.EVENT, 'split-a'),
                           accretion_fraction=.5)
        event = E.Split('split-a', 'A', split.parts, short, MYR)
        refused(self, 'ends inside plate', self.state, still(self.network, events=(event,)))

    def test_plates_that_move_apart_cannot_merge(self):
        merge = E.Merge('merge-ab', ('A', 'B'), 'AB', MYR)
        refused(self, 'do not move together', self.state, F.one_plate_motion(.5, events=(merge,)))

    def test_new_identities_are_fresh(self):
        step = T.advance(self.state, still(self.network, events=(meridian_split(self.network),)), end_time_s=MYR)
        after = step.state.network
        for taken in ('A', 'B'):
            again = latitude_split(after, 'split-a1', 'A1', (taken, 'A9'), 'cut-a1', (2, 3), 2*MYR)
            refused(self, "plate identity %r is in use or retired" % taken, step.state,
                    still(after, 1, events=(again,)), 2*MYR)
        merged = T.advance(self.state, still(self.network, events=(E.Merge('m', ('A', 'B'), 'AB', MYR),)),
                           end_time_s=MYR).state
        reused = latitude_split(merged.network, 'split-ab', 'AB', ('AB1', 'AB2'), 'boundary-m04', (2, 3, 4, 5, 0),
                                2*MYR)
        refused(self, "boundary identity 'boundary-m04' is in use or retired", merged,
                still(merged.network, 1, events=(reused,)), 2*MYR)

    def test_a_ridge_jump_needs_a_ridge_to_retire(self):
        # The eastern slice of A borders B across the trench, not across a ridge.
        split = meridian_split(self.network, 'jump-split', ('A-west', 'A-east'), 'ridge-new')
        jump = E.RidgeJump('jump', split, E.Merge('jump-merge', ('A-east', 'B'), 'B-grown', MYR))
        refused(self, 'no ridge separates them', self.state, still(self.network, events=(jump,)))

    def test_plates_without_a_common_record_cannot_merge(self):
        step = T.advance(self.state, still(self.network, events=(meridian_split(self.network),)), end_time_s=MYR)
        merge = E.Merge('merge', ('A1', 'B'), 'A1B', 2*MYR)
        refused(self, 'share no boundary record', step.state, still(step.state.network, 1, events=(merge,)),
                2*MYR)

    def test_a_split_must_name_every_face_of_its_plate(self):
        split = meridian_split(self.network)
        (first, faces), second = split.parts
        event = E.Split('split-a', 'A', ((first, faces[1:]), second), split.boundary, MYR)
        refused(self, 'own exactly the faces', self.state, still(self.network, events=(event,)))

    def test_only_supplied_prescribed_history_is_admitted(self):
        with self.assertRaises(E.EventRefused) as caught:
            E.Merge('merge-ab', ('A', 'B'), 'AB', MYR, basis='generated_v1')
        self.assertIn('admitted law', str(caught.exception))
        with self.assertRaises(L.LedgerError):
            still(self.network, events=('a split',))


class RecordTests(unittest.TestCase):
    def test_a_motion_without_events_keeps_its_record_and_identity(self):
        # Ledgers written before I03.4 store motions and steps without events; they must restore as they were.
        state = F.crust(F.three_plates())
        motion = F.one_plate_motion(.5)
        self.assertNotIn('events', motion._declared())
        step = T.advance(state, motion, end_time_s=MYR)
        self.assertNotIn('events', step.record())
        self.assertNotIn('events', step.record()['motion'])
        self.assertEqual(T._motion(step.record()['motion']).motion_id, motion.motion_id)

    def test_an_event_record_round_trips(self):
        state = F.crust(F.three_plates())
        endpoint = T.advance(state, F.one_plate_motion(.5), end_time_s=MYR).state.network
        for event in (meridian_split(state.network), E.Merge('m', ('A', 'B'), 'AB', MYR), ridge_jump(endpoint),
                      E.Retire('r', 'A', MYR)):
            self.assertEqual(E.from_record(event.record()), event)
        changed = dict(E.Merge('m', ('A', 'B'), 'AB', MYR).record(), new_plate_id=7)
        with self.assertRaises(E.EventRefused):
            E.from_record(changed)


class CeilingTests(unittest.TestCase):
    def test_an_event_interval_counts_against_the_256_step_ceiling(self):
        self.assertEqual(I.MAX_STEPS, 256)
        state = F.crust(F.three_plates())
        step = T.advance(state, still(state.network, 0, (meridian_split(state.network),), I.MAX_STEPS),
                         end_time_s=MYR)
        self.assertEqual(step.state.network.step, I.MAX_STEPS)
        with self.assertRaises(L.LedgerError):
            still(step.state.network, I.MAX_STEPS, (E.Merge('m', ('A1', 'A2'), 'A3', 2*MYR),))


class ClosedSphereTests(unittest.TestCase):
    def test_source_and_sink_accounts_hold_through_a_ridge_jump(self):
        rule, jumped = control('event_closed_sphere'), control('event_ridge_jump')
        turn, count = rule['turn_deg'], rule['intervals']
        self.assertEqual(count*turn, rule['born_total_deg'])
        self.assertEqual(count*turn, rule['consumed_total_deg'])
        east, grown = tuple(jumped['split']['parts'])[1], jumped['merge']['new_plate']
        states = [F.crust(F.three_plates())]
        states.append(T.advance(states[0], F.one_plate_motion(turn), end_time_s=MYR).state)
        endpoint = T.advance(states[1], F.one_plate_motion(turn, step=1), end_time_s=2*MYR).state.network
        states.append(T.advance(states[1], F.one_plate_motion(turn, step=1, events=(ridge_jump(endpoint),)),
                                end_time_s=2*MYR).state)
        follow = T.Motion(2, 3, {east: F.spin(turn), 'B': F.IDENTITY, grown: F.IDENTITY},
                          supplies=F.both_sides('ridge-new'), sinks=(F.sink('boundary-m04'),))
        states.append(T.advance(states[2], follow, end_time_s=3*MYR).state)
        for state in states:
            self.assertLessEqual(abs(state.network.statistics['area_residual_sr']), AREA_CLOSURE_SR)
            self.assertLessEqual(abs(state.material.totals()['area_m2']-F.SPHERE_M2),
                                 AREA_CLOSURE_SR*F.RADIUS_M**2)
            self.assertTrue(state.material.closure()['identity_exact'])
        material = states[-1].material
        supplied = {name: {k: float(v) for k, v in values.items()} for name, values in material.supplied().items()}
        self.assertEqual(sorted(supplied), ['mantle-source', 'ridge|boundary-m02|left', 'ridge|boundary-m02|right',
                                            'ridge|ridge-new|left', 'ridge|ridge-new|right', 'slab',
                                            'trench|boundary-m04'])
        born, consumed = F.lune(rule['born_total_deg']), F.lune(rule['consumed_total_deg'])
        births = sum(supplied[name]['area_m2'] for name in supplied if name.startswith('ridge|'))
        close(self, births, born)
        close(self, supplied['mantle-source']['mass_kg:crust'], F.D3_MASS_PER_AREA*born)
        close(self, supplied['mantle-source']['volume_m3:crust'], F.D3_THICKNESS*born)
        close(self, supplied['mantle-source']['enthalpy_j'], F.D3_ENTHALPY_PER_AREA*born)
        close(self, -supplied['trench|boundary-m04']['area_m2'], consumed)
        close(self, -supplied['slab']['mass_kg:crust'], F.D3_MASS_PER_AREA*consumed)
        close(self, -supplied['slab']['enthalpy_j'], F.INHERITED_ENTHALPY_PER_AREA*consumed)
        # Exact identity, account by account, from the stored record: pieces = declared + supplied + rounding.
        declared, rounding, allowance = ([Fraction(text) for text in material.descriptor()['exact'][name]]
                                         for name in ('initial', 'rounding', 'allowance'))
        for index, column in enumerate(material.columns):
            given = sum((values[column] for values in material.supplied().values()), Fraction(0))
            self.assertEqual(material.exact_total(column), declared[index]+given+rounding[index])
            self.assertEqual(declared[index], states[0].material.exact_total(column))
            self.assertLessEqual(abs(rounding[index]), allowance[index])


# ----------------------------------------------------------------------------- through the I02 clock and ledger

def setUpModule():
    with threadpool_limits(limits=1, user_api='blas'):
        FIX['prepared'] = F2.preparation()


def advance(clock, **request):
    return clock.advance(deadline=time.perf_counter()+RESOURCES['clock_deadline_s'], **request)


def world():
    return F.three_plates(epoch=F2.EPOCH, time_s=F2.START)


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

    def ledger(self, store=None):
        column = F2.root(STEPS, prepared=FIX['prepared'])
        return L.Ledger.create(store or self.store, column, sphere=F.crust(world()))

    def reopened(self, ledger):
        self.store.close()
        store = F2.store(self.path)
        self.addCleanup(store.close)
        return L.Ledger.open(store, ledger.ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)


class RollbackTests(Limited):
    def test_a_joint_proposal_whose_component_fails_commits_nothing(self):
        ledger, root = self.ledger()
        parent = ledger.sphere(root)
        t1 = K.Clock(ledger).time_at(1)
        bad_jump = E.RidgeJump('jump', meridian_split(parent.network, 'jump-split', ('A-slice', 'A-east'),
                                                      'ridge-new', time_s=t1),
                               E.Merge('jump-merge', ('A-slice', 'B'), 'B-grown', t1))
        bad_pair = (meridian_split(parent.network, 'a-split', time_s=t1), E.Merge('b-merge', ('B', 'C'), 'A1', t1))
        for events in ((bad_jump,), bad_pair):
            with self.subTest(events=[e.event_id for e in events]):
                outcome = advance(K.Clock(ledger), steps=1, transfers=(still(parent.network, events=events),))
                self.assertEqual((outcome.status, outcome.accepted_steps, outcome.head.key),
                                 (K.REFUSED_EXCHANGE, 0, root.key))
                self.assertIn('topology event', outcome.reason)
                self.assertEqual(self.store.statistics()['snapshots'], 1)
        good = advance(K.Clock(ledger), steps=1, transfers=(still(parent.network, events=bad_pair[:1]),))
        self.assertEqual(good.status, K.COMPLETED, good.reason)
        self.assertEqual(ledger.sphere(good.head).network.plate_ids, ('A1', 'A2', 'B', 'C'))


class ReplayTests(Limited):
    def test_identical_replay_is_idempotent_and_a_changed_replay_refuses(self):
        ledger, root = self.ledger()
        parent = ledger.sphere(root)
        column = ledger.state(root)
        s1 = I.Continuation(column).advance(column, 1).state
        t1 = K.Clock(ledger).time_at(1)
        split = meridian_split(parent.network, time_s=t1)
        c1 = ledger.commit(root, (s1,), (still(parent.network, events=(split,)),))
        again = ledger.commit(root, (s1,), (still(parent.network, events=(split,)),))
        self.assertEqual((again.key, self.store.statistics()['snapshots']), (c1.key, 2))
        changed = meridian_split(parent.network, names=('A-west', 'A-east'), time_s=t1)
        with self.assertRaises(L.LedgerConflict):
            ledger.commit(root, (s1,), (still(parent.network, events=(changed,)),))
        self.assertEqual(ledger.head().key, c1.key)
        self.assertEqual(c1.metadata()['sphere']['events'], [split.record()])
        after = ledger.sphere(c1)
        with self.assertRaises(E.EventRefused) as caught:
            E.applied(after.network, after.material, (split,), {p: F.IDENTITY for p in after.network.plate_ids})
        self.assertIn('replay', str(caught.exception))


class MeshAndEventLedgerTests(Limited):
    def test_c1_a_mesh_change_with_a_split_reopens_and_continues(self):
        ledger, root = self.ledger()
        parent = ledger.sphere(root)
        clock = K.Clock(ledger)
        mesh = FindingTests.merged_mesh(None, parent.network)
        plates = {p: F.IDENTITY for p in parent.network.plate_ids}
        endpoint = T.advance(parent, T.Motion(0, 1, plates, mesh=mesh), end_time_s=clock.time_at(1)).state.network
        split = meridian_split(endpoint, time_s=clock.time_at(1))
        first = advance(clock, steps=1, transfers=(T.Motion(0, 1, plates, mesh=mesh, events=(split,)),))
        self.assertEqual(first.status, K.COMPLETED, first.reason)
        made = ledger.sphere(first.head)
        again = self.reopened(ledger)
        self.assertEqual(again.verify_chain().key, first.head.key)
        self.assertEqual(again.sphere(first.head).state_id, made.state_id)
        later = advance(K.Clock(again), steps=1, transfers=(still(made.network, 1),))
        self.assertEqual(later.status, K.COMPLETED, later.reason)


class CascadeTests(Limited):
    def test_a_later_event_is_evaluated_on_the_committed_state(self):
        ledger, root = self.ledger()
        parent = ledger.sphere(root)
        clock = K.Clock(ledger)
        merge = E.Merge('merge-ab', ('A', 'B'), 'AB', clock.time_at(1))
        split = meridian_split(parent.network, time_s=clock.time_at(2))
        # From the parent, the split is valid on its own.
        T.advance(parent, still(parent.network, events=(meridian_split(parent.network, time_s=clock.time_at(1)),)),
                  end_time_s=clock.time_at(1))
        merged = T.advance(parent, still(parent.network, events=(merge,)),
                           end_time_s=K.Clock(ledger).time_at(1)).state.network
        outcome = advance(K.Clock(ledger), steps=2, transfers=(still(parent.network, events=(merge,)),
                                                                 still(merged, 1, events=(split,))))
        self.assertEqual((outcome.status, outcome.accepted_steps), (K.REFUSED_EXCHANGE, 1))
        self.assertIn("plate 'A' is not a plate of this network", outcome.reason)
        self.assertEqual(ledger.sphere(ledger.head()).network.plate_ids, ('AB', 'C'))


STOCK = F.control('finite_stock')


class ScarceStockTests(Limited):
    def stocked(self):
        pieces = STOCK['pieces']
        sphere = F.state(world(), phases=tuple(pieces['phases']), basis=F2.BASIS, stock_link=dict(STOCK['stock_link']),
                         exteriors=F.EXTERIORS, mass_per_area_kg_m2=dict(pieces['mass_per_area_kg_m2']),
                         thickness_m=dict(pieces['thickness_m']),
                         enthalpy_per_area_j_m2=pieces['enthalpy_per_area_j_m2'])
        column = F2.root(STEPS, prepared=FIX['prepared'], stocks=F2.reservoirs(), basis=F2.BASIS)
        return L.Ledger.create(self.store, column, sphere=sphere,
                               exteriors=tuple(tuple(pair) for pair in STOCK['exchange_exteriors']))

    def supply(self, side, source=None, mass=None):
        supply = STOCK['supply']
        return F.supply('boundary-m02', side, source=source or supply['source'], stock=True,
                        mass_per_area_kg_m2=mass or dict(supply['mass_per_area_kg_m2']),
                        thickness_m=dict(supply['thickness_m']),
                        enthalpy_per_area_j_m2=supply['enthalpy_per_area_j_m2'])

    def test_a_joint_demand_beyond_a_finite_stock_refuses_the_interval_and_its_event(self):
        rule = control('event_scarce_stock')
        degrees = F.control('clock_commit')['rotation_deg_per_interval']
        ledger, root = self.stocked()
        parent = ledger.sphere(root)
        split = meridian_split(parent.network, 'split-b', ('B-west', 'B-east'), 'ridge-b', 'B', at=5,
                               time_s=K.Clock(ledger).time_at(1))
        source = STOCK['supply']['source']
        store = F2.reservoirs()
        available = float(store.component_mass_kg[list(store.node_ids).index(source)][0])
        # The declared supply's own debit of component A on one side, from a dry run of the same interval.
        dry = T.advance(parent, F.one_plate_motion(degrees, supplies=(self.supply('left'), self.supply('right'))),
                        end_time_s=K.Clock(ledger).time_at(1))
        one_side = dict([t for t in dry.stock_transfers if t.donor == source][0].component_mass_kg)['A']
        scale = rule['share_of_stock_per_side']*available/one_side
        mass = dict(STOCK['supply']['mass_per_area_kg_m2'])
        mass['A'] = mass['A']*scale
        greedy = F.one_plate_motion(degrees, supplies=(self.supply('left', mass=mass), self.supply('right', mass=mass)),
                                    events=(split,))
        outcome = advance(K.Clock(ledger), steps=1, transfers=(greedy,))
        self.assertEqual((outcome.status, outcome.accepted_steps, outcome.head.key), (K.REFUSED_EXCHANGE, 0, root.key))
        self.assertIn('finite availability', outcome.reason)
        self.assertEqual(self.store.statistics()['snapshots'], 1)
        shared = F.one_plate_motion(degrees, supplies=(self.supply('left', mass=mass),
                                                       self.supply('right', STOCK['return_to'])), events=(split,))
        done = advance(K.Clock(ledger), steps=1, transfers=(shared,))
        self.assertEqual(done.status, K.COMPLETED, done.reason)
        after = ledger.sphere(done.head)
        self.assertEqual(after.network.plate_ids, ('A', 'B-east', 'B-west', 'C'))
        debit = [r for r in done.head.metadata()['transfers'] if r['donor'] == source][0]
        close(self, debit['component_mass_kg']['A'], rule['share_of_stock_per_side']*available)


CONTINUE = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
import json
import i02_workflow_fixtures as F2
import i03_fixtures as F
from atlas_tectonics import integration_clock as K, integration_ledger as L, integration_transfer as T
store = F2.store(sys.argv[2])
ledger = L.Ledger.open(store, sys.argv[3], source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
head = ledger.verify_chain()
start, steps = head.accepted_steps, int(sys.argv[4])
restored = ledger.sphere(head)
rule = json.loads(sys.argv[5])
moves = tuple(T.Motion(k, k+1, {rule['east']: F.spin(rule['turn']), 'B': F.IDENTITY, rule['grown']: F.IDENTITY},
                       supplies=F.both_sides('ridge-new'), sinks=(F.sink('boundary-m04'),))
              for k in range(start, start+steps))
outcome = K.Clock(ledger).advance(steps=steps, transfers=moves,
                                  deadline=time.perf_counter()+F.CASE['resources']['clock_deadline_s'])
state = ledger.sphere(outcome.head)
print(outcome.status, outcome.head.accepted_steps, restored.issued_by, state.state_id,
      state.material.closure()['identity_exact'], len(ledger.chain()))
store.close()
'''


class ContinuationTests(Limited):
    def history(self, ledger, count):
        """The control's history through the clock: a motion, the jump, then the new ridge spreading."""
        rule = control('event_ridge_jump')
        turn = control('event_continuation')['turn_deg']
        clock = K.Clock(ledger)
        first = advance(clock, steps=1, transfers=(F.one_plate_motion(turn),))
        self.assertEqual(first.status, K.COMPLETED, first.reason)
        before = ledger.sphere(first.head)
        endpoint = T.advance(before, F.one_plate_motion(turn, step=1), end_time_s=clock.time_at(2)).state.network
        jump = ridge_jump(endpoint)
        second = advance(clock, steps=1, transfers=(F.one_plate_motion(turn, step=1, events=(jump,)),))
        self.assertEqual(second.status, K.COMPLETED, second.reason)
        self.assertEqual(second.head.metadata()['sphere']['events'], [jump.record()])
        east, grown = tuple(rule['split']['parts'])[1], rule['merge']['new_plate']
        moves = tuple(T.Motion(k, k+1, {east: F.spin(turn), 'B': F.IDENTITY, grown: F.IDENTITY},
                               supplies=F.both_sides('ridge-new'), sinks=(F.sink('boundary-m04'),))
                      for k in range(2, count))
        if moves:
            rest = advance(clock, steps=len(moves), transfers=moves)
            self.assertEqual(rest.status, K.COMPLETED, rest.reason)
        return ledger.head(), dict(east=east, grown=grown, turn=turn)

    def test_save_reopen_and_continue_through_a_ridge_jump(self):
        whole_store = F2.store(self.folder/'whole'/'ledger.sqlite')
        self.addCleanup(whole_store.close)
        whole, _ = self.ledger(whole_store)
        final = whole.sphere(self.history(whole, 4)[0])
        self.assertTrue(final.material.closure()['identity_exact'])
        ledger, root = self.ledger()
        saved, rule = self.history(ledger, 2)
        middle = ledger.sphere(saved)
        self.store.close()
        env = dict(os.environ, PYTHONPATH=SRC)
        done = subprocess.run([sys.executable, '-B', '-c', CONTINUE, str(HERE), str(self.path), ledger.ledger_id, '2',
                               json.dumps(rule)], capture_output=True, text=True, env=env,
                              timeout=RESOURCES['child_timeout_s'])
        self.assertEqual(done.returncode, 0, done.stderr)
        status, steps, issued, state_id, exact, commits = done.stdout.split()
        self.assertEqual((status, steps, issued, exact, commits), (K.COMPLETED, '4', I.RESTORED, 'True', '5'))
        self.assertEqual(state_id, final.state_id)
        store = F2.store(self.path)
        self.addCleanup(store.close)
        again = L.Ledger.open(store, ledger.ledger_id, source_id=F2.SOURCE_ID, runtime_id=F2.RUNTIME_ID)
        chain = again.chain()
        self.assertEqual(again.verify_chain().key, chain[-1].key)
        self.assertEqual(again.sphere(chain[2]).state_id, middle.state_id)
        self.assertEqual(again.sphere(chain[-1]).state_id, final.state_id)
        self.assertEqual(again.sphere(chain[2]).network.lineage.events, ('jump', 'jump-split', 'jump-merge'))


if __name__ == '__main__':
    unittest.main()
