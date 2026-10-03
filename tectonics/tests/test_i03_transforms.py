"""I03a-2 Part 3: sliding transforms (approved 3 October 2026: D6 carrier_side, C6). WORKING NON-CANON.

Every value comes from cases/i03_controls_v2.json. A transform's trace is carried by the plate its record declares;
the far plate's cells beside it are sheared and remapped along it, and material never crosses it.
"""
import json
import math
import unittest

import numpy as np

import i03_fixtures as F
from atlas_tectonics import integration_sphere as S, integration_transfer as T
from atlas_tectonics.kinematics import Rotation

CASE2 = json.loads((F.CASES/'i03_controls_v2.json').read_text(encoding='utf-8'))
MYR = F.MYR_S
RELATIVE = F.tolerance('relative')


def control(name):
    return CASE2['controls'][name]


def twin_hemispheres(carrier_side='right', bend=False, lons=None, tilt=None):
    rule = control('sliding_transform')
    lons, lats = lons or rule['longitudes_deg'], rule['latitudes_deg']
    equator, count = lats.index(0), len(lons)
    vertices, rings = F.sector_mesh(lons, lats, tilt=tilt)
    if bend:                                  # one equator vertex moved north: the trace bends there
        vertices[F.vertex(3, equator)] = F.direction(lons[3], 2.)

    def owner(name):
        south = name.endswith('south') or ('-b' in name and int(name[-2:]) < equator)
        return 'south' if south else 'north'
    faces = tuple(S.Face(name, owner(name), ring) for name, ring in rings.items())
    # Going east along the equator the northern plate is on the left.
    equator_chain = tuple(F.vertex(i, equator) for i in range(count))
    boundaries = (S.Boundary('equator', S.TRANSFORM, 'north', 'south', equator_chain, F.origin(), closed=True,
                             carrier_side=carrier_side),)
    plates = tuple(S.Plate(name, F.IDENTITY) for name in ('north', 'south'))
    return S.build_network(sphere=F.sphere(), vertices=vertices, faces=faces, plates=plates, boundaries=boundaries,
                           epoch_id=F.EPOCH, time_s=F.START)


def slide(state, step, rotation):
    return T.advance(state, T.Motion(step, step+1, {'north': rotation, 'south': F.IDENTITY}),
                     end_time_s=(step+1)*MYR)


class ExactSlipTests(unittest.TestCase):
    def test_cells_slide_along_an_exactly_slip_parallel_transform(self):
        rule = control('sliding_transform')
        state = F.crust(twin_hemispheres())
        areas = {plate: state.network.plate_area_m2()[plate] for plate in ('north', 'south')}
        turn = F.spin(rule['slip_deg'])
        for k in range(rule['intervals']):
            step = slide(state, k, turn)
            after = step.state
            self.assertTrue(after.material.closure()['identity_exact'])
            self.assertEqual(after.material.supplied(), state.material.supplied())     # no party: nothing crosses
            for plate in ('north', 'south'):
                self.assertLessEqual(abs(after.network.plate_area_m2()[plate]-areas[plate]), RELATIVE*areas[plate])
            rows = step.map.rows
            self.assertTrue(rows)
            for donor, receiver, party, area in rows:
                self.assertGreaterEqual(donor, 0)
                self.assertGreaterEqual(receiver, 0)
                self.assertIsNone(party)
                donor, receiver = state.network.face_ids[donor], after.network.face_ids[receiver]
                self.assertEqual(state.network.face_plate(donor), 'north')
                self.assertEqual(after.network.face_plate(receiver), 'north')
                cell, into = F.sector_of(donor), F.sector_of(receiver)
                self.assertIn((into-cell) % len(rule['longitudes_deg']), (0, 1))     # itself or its eastern neighbour
            for index, face_id in enumerate(after.network.face_ids):
                if after.network.face_plate(face_id) == 'south' or face_id.endswith('north'):
                    old = state.network.face_ids.index(face_id)
                    self.assertEqual(after.network.face_area_m2[index], state.network.face_area_m2[old])
            state = after
        self.assertEqual(S.restore_sphere(state.descriptor(), state.arrays()).state_id, state.state_id)


class CumulativeTests(unittest.TestCase):
    # F3 (round 1): C6 is judged on the far plate's total motion relative to the carrier, not interval by interval.
    def history(self, state, rotation, steps):
        for k in range(steps):
            try:
                state = slide(state, k, rotation).state
            except T.TransferRefused as exc:
                return k+1, exc
        return None, None

    def test_sub_band_normal_motion_is_refused_once_it_adds_up_to_the_band(self):
        rule = control('sliding_transform_cumulative')
        eps = float(np.finfo(float).eps)
        turn = Rotation.from_axis_angle(tuple(rule['normal_axis']), rule['normal_turn_eps']*eps)
        refused, exc = self.history(F.crust(twin_hemispheres()), turn, rule['intervals'])
        self.assertEqual(refused, 2, exc)
        self.assertEqual(exc.code, T.TRANSFORM_NOT_SLIP_PARALLEL)

    def test_a_bent_trace_admits_no_slip_in_total(self):
        rule = control('sliding_transform_cumulative')
        turn = Rotation.from_axis_angle((0., 0., 1.), rule['bent_slip_band_fraction']*S.ATTACHMENT_BAND_RAD)
        refused, exc = self.history(F.crust(twin_hemispheres(bend=True)), turn, rule['intervals'])
        self.assertEqual(refused, 3, exc)
        self.assertEqual(exc.code, T.TRANSFORM_NOT_SLIP_PARALLEL)


class DegenerateOverlayTests(unittest.TestCase):
    def test_an_overlay_with_no_polygonal_part_recovers_the_exact_spherical_overlap(self):
        # v4 supersedes v2's refusal expectation, not its geometry or existing conservation criteria.
        rule = control('degenerate_overlay')
        state = F.crust(twin_hemispheres())
        step = slide(state, 0, F.spin(rule['slip_deg']))
        self.assertTrue(step.state.material.closure()['identity_exact'])
        self.assertEqual(step.state.material.supplied(), state.material.supplied())
        for plate, area in state.network.plate_area_m2().items():
            self.assertLessEqual(abs(step.state.network.plate_area_m2()[plate]-area), RELATIVE*area)
        for donor, receiver, party, area in step.map.rows:
            self.assertGreaterEqual(donor, 0)
            self.assertGreaterEqual(receiver, 0)
            self.assertIsNone(party)
            self.assertEqual(state.network.face_plate(state.network.face_ids[donor]),
                             step.state.network.face_plate(step.state.network.face_ids[receiver]))
        self.assertEqual(T.restored(state, {'sphere': step.record(), 'transfers': []}, step.arrays()).state_id,
                         step.state.state_id)


class ShortSegmentTests(unittest.TestCase):
    def test_an_exact_slip_along_short_segments_is_accepted_in_every_frame(self):
        # C6 tests a far image against the trace's own line, formed stably from well-separated vertices, not against
        # the circle of a short segment carried far beyond it (Part 3 verifier, 3 October 2026).
        rule = control('sliding_transform_short_segments')
        base = control('sliding_transform')['longitudes_deg']
        lons = sorted({*base, *(round(lon+rule['short_deg']*j, 6) for lon in base for j in (1, 2))})
        frame = control('junction_frames_and_composition')['frame_rotation']
        q = Rotation.from_axis_angle(tuple(frame['axis']), math.radians(frame['angle_deg']))
        turn, tilted = F.spin(rule['slip_deg']), F.spin(rule['slip_deg'], F.TILT)
        histories = {
            'plain': (twin_hemispheres(lons=lons), lambda k: {'north': turn, 'south': F.IDENTITY}),
            'tilted': (twin_hemispheres(lons=lons, tilt=F.TILT), lambda k: {'north': tilted, 'south': F.IDENTITY}),
            'D3': (twin_hemispheres(lons=lons), lambda k: {p: (F.IDENTITY if k == 0 else q.inverse()).then(r).then(q)
                                                           for p, r in (('north', turn), ('south', F.IDENTITY))}),
        }
        for label, (network, rotations) in histories.items():
            with self.subTest(frame=label):
                state = F.crust(network)
                for k in range(rule['intervals']):
                    state = T.advance(state, T.Motion(k, k+1, rotations(k)), end_time_s=(k+1)*MYR).state
                    self.assertTrue(state.material.closure()['identity_exact'])


class RefusalTests(unittest.TestCase):
    def test_a_slip_off_the_traces_pole_is_refused_with_the_port_code(self):
        rule = control('sliding_transform')
        state = F.crust(twin_hemispheres())
        axis = np.array([math.sin(rule['off_pole_rad']), 0., math.cos(rule['off_pole_rad'])])
        turn = Rotation.from_axis_angle(tuple(axis), math.radians(rule['slip_deg']))
        with self.assertRaises(T.TransferRefused) as caught:
            slide(state, 0, turn)
        self.assertEqual(caught.exception.code, T.TRANSFORM_NOT_SLIP_PARALLEL)

    def test_a_bent_transform_admits_no_slip(self):
        rule = control('sliding_transform')
        state = F.crust(twin_hemispheres(bend=True))
        with self.assertRaises(T.TransferRefused) as caught:
            slide(state, 0, F.spin(rule['slip_deg']))
        self.assertEqual(caught.exception.code, T.TRANSFORM_NOT_SLIP_PARALLEL)

    def test_a_transform_without_a_declared_carrier_slides_only_when_locked(self):
        state = F.crust(twin_hemispheres(carrier_side=None))
        with self.assertRaises(T.TransferRefused) as caught:
            slide(state, 0, F.spin(control('sliding_transform')['slip_deg']))
        self.assertIn('sliding along a transform is not supported', str(caught.exception))    # I03a's wording kept
        self.assertIn('carrier_side', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
