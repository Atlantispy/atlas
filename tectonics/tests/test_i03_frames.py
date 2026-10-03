"""I03a-2 Part 1: vertices kept in plate reference frames, so a face that rides keeps its numbers. WORKING NON-CANON.

Every value comes from cases/i03_controls_v2.json (and, through it, cases/i03_controls_v1.json). The ride-then-remesh
path is the one Codex's review of I03a reproduced (finding P2): there a face's measured area drifted from its pieces
while it rode, and a later remesh of it, even a rename, was refused.
"""
import dataclasses
from fractions import Fraction
import json
import math
import unittest
from unittest import mock

import numpy as np

import i03_fixtures as F
from atlas_tectonics import integration_sphere as S, integration_state as I, integration_transfer as T
from atlas_tectonics.kinematics import _restore_rotation

CASE2 = json.loads((F.CASES/'i03_controls_v2.json').read_text(encoding='utf-8'))
RELATIVE = F.tolerance('relative')
MYR = F.MYR_S
EPS = float(np.finfo(float).eps)


def control(name):
    return CASE2['controls'][name]


def occupancy(state):
    """The largest relative difference between a face's measured area and the areas of its pieces."""
    network, material = state.network, state.material
    worst = 0.
    for index, area in enumerate(network.face_area_m2):
        held = math.fsum(material.stock[material.piece_face == index, 0])
        worst = max(worst, abs(held-area)/area)
    return worst


def merged(a, b, face_id):
    """One face of their plate whose ring is the union of two faces that share exactly one edge."""
    ra, rb = list(a.vertex_ids), list(b.vertex_ids)
    for i in range(len(ra)):
        u, v = ra[i], ra[(i+1) % len(ra)]
        if v in rb and rb[(rb.index(v)+1) % len(rb)] == u:
            break
    else:
        raise AssertionError('the faces share no edge')
    pa = [ra[(i+1+k) % len(ra)] for k in range(len(ra))]                    # from v round to u
    j = rb.index(u)
    pb = [rb[(j+k) % len(rb)] for k in range(len(rb))]                      # from u round to v
    return S.Face(face_id, a.plate_id, tuple(pa+pb[1:-1]))


def remeshed(state, faces, step):
    """One interval in which nothing moves and the sampling faces become ``faces``."""
    still = T.Motion(step, step+1, {plate: F.IDENTITY for plate in state.network.plate_ids}, mesh=T.Mesh(faces))
    return T.advance(state, still, end_time_s=(step+1)*MYR).state


class RideThenRemeshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rule = control('ride_then_remesh')
        cls.thin = rule['thin_face']
        state = F.crust(F.three_plates())
        state = T.advance(state, F.one_plate_motion(rule['advance_deg']), end_time_s=MYR).state
        cls.born = float(state.network.face_area_m2[state.network.face_ids.index(cls.thin)])
        turn = F.rotation(F.control('rigid_rotation')['rotation'])
        cls.worst = [occupancy(state)]
        for k in range(1, rule['rides']+1):
            motion = T.Motion(k, k+1, {plate: turn for plate in state.network.plate_ids})
            state = T.advance(state, motion, end_time_s=(k+1)*MYR).state
            cls.worst.append(occupancy(state))
        cls.ridden = state

    def test_every_face_keeps_its_pieces_after_every_ride(self):
        # The existing relative tolerance holds after every interval, for every face, the thin strip included.
        self.assertLessEqual(max(self.worst), RELATIVE, self.worst)
        network = self.ridden.network
        self.assertEqual(float(network.face_area_m2[network.face_ids.index(self.thin)]), self.born)

    def test_a_ridden_thin_strip_can_be_renamed_merged_and_split(self):
        state, step = self.ridden, self.ridden.step
        strip = state.network.face(self.thin)
        self.assertLess(self.born, 2e8)                                      # about 55 m by 3,200 km
        # 1. A rename: the same plate, rings and coordinates under another identity.
        renamed = tuple(S.Face('renamed-thin-face', f.plate_id, f.vertex_ids, f.holes, f.block_id)
                        if f.face_id == self.thin else f for f in state.network.faces)
        after = remeshed(state, renamed, step)
        self.assertTrue(after.material.closure()['identity_exact'])
        self.assertLessEqual(occupancy(after), RELATIVE)
        # 2. A merge with the cell of its plate that shares its long edge (the plate's copy of the old ridge).
        cells = [f for f in state.network.faces if f.plate_id == strip.plate_id and f.face_id != self.thin
                 and '|' not in f.face_id and len(set(f.vertex_ids) & set(strip.vertex_ids)) == 2]
        self.assertEqual(len(cells), 1, [f.face_id for f in cells])
        cell = cells[0]
        joined = merged(strip, cell, 'merged-strip-and-cell')
        faces = tuple(f for f in state.network.faces if f.face_id not in (self.thin, cell.face_id))+(joined,)
        merged_state = remeshed(state, faces, step)
        self.assertTrue(merged_state.material.closure()['identity_exact'])
        self.assertLessEqual(occupancy(merged_state), RELATIVE)
        self.assertEqual(merged_state.material.totals(), state.material.totals())
        # 3. From the merged state, a split back into the strip and the cell.
        apart = tuple(f for f in merged_state.network.faces if f.face_id != joined.face_id)+(strip, cell)
        split = remeshed(merged_state, apart, step+1)
        self.assertTrue(split.material.closure()['identity_exact'])
        self.assertLessEqual(occupancy(split), RELATIVE)
        index = split.network.face_ids.index(self.thin)
        self.assertEqual(float(split.network.face_area_m2[index]), self.born)


class RidgeFrameTests(unittest.TestCase):
    def test_a_ridge_vertex_is_placed_once_from_its_declared_reference(self):
        rule = control('ridge_frame')
        state = F.crust(F.three_plates())
        ridge = state.network.boundary('boundary-m02')
        name = ridge.vertex_ids[len(ridge.vertex_ids)//2]
        index = state.network.vertex_ids.index(name)
        declared = np.array(state.network.arrays()['sphere.vertex_reference'][index])
        start = np.array(state.network.vertex_direction[index])
        for k in range(rule['intervals']):
            state = T.advance(state, F.one_plate_motion(rule['advance_deg'], k), end_time_s=(k+1)*MYR).state
            network = state.network
            index = network.vertex_ids.index(name)                     # copies born each interval shift the rows
            self.assertEqual(network.arrays()['sphere.vertex_reference'][index].tobytes(), declared.tobytes())
            self.assertEqual(network.vertex_home(name), ('ridge', ridge.boundary_id))
            frame = network.ridge_frames[ridge.boundary_id]
            self.assertEqual(network.vertex_direction[index].tobytes(), S._placed(frame, declared)[0].tobytes())
            expected = F.spin((k+1)*rule['advance_deg']/2).apply(start)
            self.assertLessEqual(float(F.angle(network.vertex_direction[index], expected)),
                                 F.tolerance('angular_absolute_rad'))


class RenamedCornersTests(unittest.TestCase):
    def test_a_strip_keeps_its_measured_area_while_its_corners_are_renamed(self):
        # Each interval the strips born before keep their ridge-side corners under new copy identities, so their
        # rings start at another vertex; the measured area must not depend on where a ring starts.
        rule = control('ridge_frame')
        state = F.crust(F.three_plates())
        born = {}
        for k in range(rule['intervals']):
            state = T.advance(state, F.one_plate_motion(rule['advance_deg'], k), end_time_s=(k+1)*MYR).state
            network = state.network
            for index, face_id in enumerate(network.face_ids):
                if face_id.startswith('boundary-m02|'):
                    area = network.face_area_m2[index].tobytes()
                    self.assertEqual(born.setdefault(face_id, area), area, face_id)
        starts = {face.face_id: face.vertex_ids[0] for face in state.network.faces if face.face_id in born}
        self.assertTrue(any('|C|' in start for start in starts.values()))   # the rings were restarted


class ContainmentTests(unittest.TestCase):
    def test_containment_is_decided_exactly(self):
        rule = control('containment')
        outer = np.array([F.direction(*corner) for corner in rule['outer_lon_lat_deg']])
        centre = T._cap([outer])[0]
        for name, case in rule['cases'].items():
            inner = outer if name == 'identical' else np.array([F.direction(*c) for c in case['lon_lat_deg']])
            with self.subTest(case=name):
                self.assertIs(T._within(inner, outer, centre), case['contained'])


class StoredFramesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.moved = T.advance(F.crust(F.three_plates()), F.one_plate_motion(control('ridge_frame')['advance_deg']),
                              end_time_s=MYR).state

    def test_a_forged_ridge_frame_is_refused(self):
        # The same rotation with the opposite quaternion sign places every vertex on the same bits; only the
        # record's ridge frames tell them apart.
        state = T.advance(F.crust(F.three_plates()), F.one_plate_motion(control('ridge_frame')['advance_deg']),
                          end_time_s=MYR).state
        layout = state.network._layout
        flipped = tuple((b, _negated(r)) for b, r in layout.ridges)
        object.__setattr__(state.network, '_layout', dataclasses.replace(layout, ridges=flipped))
        self.assertEqual(S._directions(state.network._layout).tobytes(), S._directions(layout).tobytes())
        with self.assertRaises(S.SphereError):
            S.verified(state)

    def test_a_layout_lacking_a_needed_copy_is_refused(self):
        network = self.moved.network
        layout = network._layout
        shorter = dataclasses.replace(layout, views=layout.views[1:])
        with self.assertRaises(S.SphereError) as caught:
            S._network(network.sphere, shorter, network.faces, network.plates, network.boundaries, network.epoch_id,
                       network.time_s, network.step, network.reference_time_s, network.lineage, None, None, None,
                       False)
        self.assertIn('copies', str(caught.exception))

    def test_a_vertex_kept_anywhere_but_its_carrier_is_refused(self):
        # A ridge vertex kept by plate C, with C's own copy as its reference and every other copy in place: no issuing
        # route makes this layout, and kept there it would be placed again every interval.
        network = self.moved.network
        layout = network._layout
        name = network.boundary('boundary-m02').vertex_ids[2]
        index = layout.names.index(name)
        views = dict(layout.views)
        home, reference = list(layout.home), np.array(layout.reference)
        home[index], reference[index] = 'C', views[(name, 'C')]
        moved = dict((key, value) for key, value in layout.views if key != (name, 'C'))
        for plate in ('A',):
            moved.setdefault((name, plate), views.get((name, plate), tuple(reference[index])))
        forged = dataclasses.replace(layout, home=tuple(home), reference=reference, views=tuple(sorted(moved.items())))
        with self.assertRaises(S.SphereError) as caught:
            S._network(network.sphere, forged, network.faces, network.plates, network.boundaries, network.epoch_id,
                       network.time_s, network.step, network.reference_time_s, network.lineage, None, None, None,
                       True)
        self.assertIn('kept by', str(caught.exception))

    def test_a_declared_state_needs_a_declared_layout(self):
        # A declaration has every frame at the sphere's axes and every copy equal to its vertex's own direction. A
        # network whose copy of one vertex is displaced, issued through the internal constructor, is not one.
        network = F.three_plates()
        layout = network._layout
        (name, plate), value = layout.views[0]
        # Displaced by 16 eps: inside C10's bound, so only the declaration check can refuse it.
        turned = S._placed(F.rotation(dict(axis=[1., 0., 0.], angle_rad=16*EPS)), np.array(value))[0]
        self.assertGreater(float(F.angle(turned, value)), 0.)
        views = ((layout.views[0][0], tuple(float(x) for x in turned)),)+layout.views[1:]
        forged = S._network(network.sphere, dataclasses.replace(layout, views=views), network.faces, network.plates,
                            network.boundaries, network.epoch_id, network.time_s, network.step,
                            network.reference_time_s, network.lineage, None, None, None, False)
        with self.assertRaises(S.SphereError) as caught:
            F.crust(forged)
        self.assertIn('declaration', str(caught.exception))
        self.assertTrue(F.crust(network).material.closure()['identity_exact'])

    def test_a_restored_computed_state_is_measured_against_its_pieces(self):
        rule = control('every_interval_occupancy')
        state = self.moved
        network, material = state.network, state.material
        stock = np.array(material.stock)
        before = Fraction(float(stock[0, 0]))
        stock[0, 0] *= 1+rule['mismatch_relative']
        initial = (material._initial[0]+Fraction(float(stock[0, 0]))-before,)+tuple(material._initial[1:])
        with mock.patch.object(S, '_occupancy', lambda *args, **kwargs: None):
            forged = S._material(network, material.phases, material.enthalpy_basis, material.cohorts,
                                 material.exteriors, None, material.piece_face, material.piece_cohort, stock, initial,
                                 material._supplied, material._rounding, material._allowance, None)
            computed = S._sphere(network, forged, state.parent_state_id, state.root_state_id, I.COMPUTED)
        with self.assertRaises(S.SphereError) as caught:
            S.restore_sphere(computed.descriptor(), computed.arrays())
        self.assertIn('do not occupy', str(caught.exception))
        self.assertEqual(S.restore_sphere(state.descriptor(), state.arrays()).state_id, state.state_id)


def _negated(rotation):
    """The same rotation stored with the opposite quaternion sign."""
    return _restore_rotation(tuple(-x for x in rotation.quaternion))


def displaced_copy(layout, plate, multiple):
    """``layout`` with ``plate``'s first copy set to its vertex's placement turned by ``multiple`` epsilon."""
    index = next(k for k, ((name, owner), _) in enumerate(layout.views) if owner == plate)
    (name, _), _ = layout.views[index]
    where = S._directions(layout)[layout.names.index(name)]
    axis = np.cross(where, (0., 0., 1.) if abs(where[2]) < .9 else (1., 0., 0.))
    turn = F.rotation(dict(axis=list(axis/np.linalg.norm(axis)), angle_rad=multiple*EPS))
    frame = dict(layout.frames)[plate]
    value = S._placed(frame.inverse(), S._placed(turn, where))[0]
    views = layout.views[:index]+(((name, plate), tuple(float(x) for x in value)),)+layout.views[index+1:]
    return dataclasses.replace(layout, views=views), name


class CopyPlacementTests(unittest.TestCase):
    # C10 form (a), approved 3 October 2026: a plate's copy of a vertex kept elsewhere lies within the band plus 4 eps
    # of the vertex's placement, on issue and on restore.
    def issue(self, network, layout):
        return S._network(network.sphere, layout, network.faces, network.plates, network.boundaries, network.epoch_id,
                          network.time_s, network.step, network.reference_time_s, network.lineage, None, None, None,
                          False)

    def test_a_copy_beyond_the_band_from_its_vertex_is_refused_on_issue_and_restore(self):
        rule = control('copy_placement')
        network = T.advance(F.crust(F.three_plates()), F.one_plate_motion(control('ridge_frame')['advance_deg']),
                            end_time_s=MYR).state.network
        plate = next(owner for (_, owner), _ in network._layout.views
                     if tuple(dict(network._layout.frames)[owner].quaternion) != (1., 0., 0., 0.))
        far, name = displaced_copy(network._layout, plate, rule['displaced_beyond_eps'])
        with self.assertRaises(S.SphereError) as caught:
            self.issue(network, far)
        self.assertIn(name, str(caught.exception))
        self.assertIn('C10', str(caught.exception))
        with mock.patch.object(S, '_copies_placed', lambda layout: None):
            forged = self.issue(network, far)
        with self.assertRaises(S.SphereError) as caught:
            S.restore_network(forged.descriptor(), forged.arrays())
        self.assertIn('C10', str(caught.exception))
        near, _ = displaced_copy(network._layout, plate, rule['displaced_within_eps'])
        accepted = self.issue(network, near)
        self.assertEqual(S.restore_network(accepted.descriptor(), accepted.arrays()).network_id, accepted.network_id)


class SubBandMotionTests(unittest.TestCase):
    def test_motion_inside_the_band_does_not_accumulate_between_copies(self):
        # Plate A turns by less than the attachment band per interval, with no supply and no sink: each interval alone
        # moves nothing. A plate's corner is its own copy, so once the motion since a corner was placed exceeds the
        # band the ridge opens or the trench consumes, and without a supply or a sink that interval is refused, never
        # accepted with the copies drifting apart.
        band = S.ATTACHMENT_BAND_RAD
        degrees = math.degrees(.3*band)
        state = F.crust(F.three_plates())
        refused = None
        for k in range(40):
            motion = T.Motion(k, k+1, {'A': F.spin(degrees), 'B': F.IDENTITY, 'C': F.IDENTITY})
            try:
                state = T.advance(state, motion, end_time_s=(k+1)*MYR).state
            except T.TransferRefused as exc:
                refused = (k+1, str(exc))
                break
            layout = state.network._layout
            homes = S._directions(layout)
            frames = dict(layout.frames)
            for (name, plate), value in layout.views:
                placed = S._placed(frames[plate], np.array(value))[0]
                drift = float(np.linalg.norm(placed-homes[layout.names.index(name)]))
                self.assertLessEqual(drift, band+4*EPS, (k, name))               # C10, on every accepted interval
        self.assertIsNotNone(refused)
        self.assertLessEqual(refused[0], 12)
        self.assertTrue('no supply' in refused[1] or 'no destination' in refused[1], refused)


class SubBandRidgeTests(unittest.TestCase):
    def test_a_ridge_moving_inside_the_band_opens_once_its_motion_exceeds_it(self):
        # The conservation verifier's case (probe 10, case 2): C's copies of the ridge vertices are re-placed, and the
        # opening on C's side booked, once the ridge has moved more than the band since C's corners were placed.
        rule = control('sub_band_ridge')
        band = S.ATTACHMENT_BAND_RAD
        state = F.crust(F.three_plates(kinds={2: dict(kind=S.RIDGE, accretion_fraction=rule['accretion_fraction'])}))
        opened = 0
        for k in range(rule['intervals']):
            # A supply is declared only for a side that opens: the left (C's) side is supplied when it is refused for
            # want of one, which happens once C's corners lie more than the band from the ridge.
            turn = math.degrees(rule['turn_rad'])
            try:
                state = T.advance(state, F.one_plate_motion(turn, k, supplies=(F.supply('boundary-m02', 'right'),)),
                                  end_time_s=(k+1)*MYR).state
            except T.TransferRefused as exc:
                self.assertIn('opens on its left side but no supply', str(exc))
                state = T.advance(state, F.one_plate_motion(turn, k, supplies=F.both_sides('boundary-m02')),
                                  end_time_s=(k+1)*MYR).state
                opened += 1
            layout = state.network._layout
            homes, frames = S._directions(layout), dict(layout.frames)
            for (name, plate), value in layout.views:
                placed = S._placed(frames[plate], np.array(value))[0]
                self.assertLessEqual(float(np.linalg.norm(placed-homes[layout.names.index(name)])), band+4*EPS,
                                     (k, name, plate))
        self.assertTrue(state.material.closure()['identity_exact'])
        self.assertGreater(opened, 0)
        self.assertGreater(state.material.supplied()['ridge|boundary-m02|left']['area_m2'], 0.)


class RestoreDiagnosisTests(unittest.TestCase):
    def test_restoration_keeps_the_cause_of_a_refusal(self):
        from atlas_tectonics.resources import MemoryLimitError, WorkBudget
        network = F.three_plates()
        with self.assertRaises(MemoryLimitError):
            S.restore_network(network.descriptor(), network.arrays(), budget=WorkBudget(1024))
        arrays = dict(network.arrays())
        arrays['sphere.vertex_ids'] = S._pack([name+'x' if name == 'N' else name for name in network.vertex_ids])
        with self.assertRaises(S.SphereError) as caught:
            S.restore_network(network.descriptor(), arrays)
        self.assertNotIn('incomplete', str(caught.exception))

    def test_verified_measures_every_face_against_its_pieces(self):
        rule = control('every_interval_occupancy')
        good = F.crust(F.three_plates())
        network, material = good.network, good.material
        stock = np.array(material.stock)
        stock[0, 0] *= 1+rule['mismatch_relative']
        exact = tuple(sum((Fraction(float(x)) for x in stock[:, column]), Fraction(0))
                      for column in range(stock.shape[1]))
        zero = (Fraction(0),)*stock.shape[1]
        forged = S._material(network, material.phases, material.enthalpy_basis, material.cohorts,
                             material.exteriors, None, material.piece_face, material.piece_cohort, stock, exact, (),
                             zero, zero, None, ())
        state = S._sphere(network, forged, None, None, I.DECLARED)
        with self.assertRaises(S.SphereError):
            S.verified(state)
        self.assertIs(S.verified(good), good)


class EveryIntervalOccupancyTests(unittest.TestCase):
    def test_every_face_is_measured_against_its_pieces_every_interval(self):
        # A face that only rides in the next interval, whose pieces miss its measured area by twice the existing
        # tolerance: the interval is refused, because every face is measured after every interval.
        rule = control('every_interval_occupancy')
        good = F.crust(F.three_plates())
        network, material = good.network, good.material
        stock = np.array(material.stock)
        stock[0, 0] *= 1+rule['mismatch_relative']
        exact = tuple(sum((Fraction(float(x)) for x in stock[:, column]), Fraction(0))
                      for column in range(stock.shape[1]))
        zero = (Fraction(0),)*stock.shape[1]
        forged = S._material(network, material.phases, material.enthalpy_basis, material.cohorts,
                             material.exteriors, None, material.piece_face, material.piece_cohort, stock, exact, (),
                             zero, zero, None, ())
        state = S._sphere(network, forged, None, None, I.DECLARED)
        still = T.Motion(0, 1, {plate: F.IDENTITY for plate in network.plate_ids})
        with self.assertRaises(T.TransferRefused) as caught:
            T.advance(state, still, end_time_s=MYR)
        self.assertIn('do not occupy', str(caught.exception))
        self.assertEqual(T.advance(good, still, end_time_s=MYR).state.material.stock.tobytes(),
                         material.stock.tobytes())


if __name__ == '__main__':
    unittest.main()
