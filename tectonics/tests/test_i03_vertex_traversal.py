"""D1-b traversal of sampling vertices at ridge/transform and ridge/trench junctions.

WORKING NON-CANON. These controls extend the v2 prescribed histories with the
K2 review's sampling vertices; all physical motions and tolerances are retained.
SPDX-License-Identifier: AGPL-3.0-only
"""
import dataclasses
import json
import math
import unittest
from unittest.mock import patch

import numpy as np

import i03_fixtures as F
import test_i03_junctions as J
import test_i03_junction_paths as P
import test_i03_transient as D5
from atlas_tectonics import integration_sphere as S, integration_transfer as T
from atlas_tectonics.resources import MemoryLimitError, WorkBudget

CONTROLS = json.loads((F.CASES/'i03_controls_v4.json').read_text(encoding='utf-8'))['controls']
CONTROL = CONTROLS['vertex_traversal']


def subdivided(network, additions):
    """Insert named degree-two samples in both faces and the declared boundary."""
    vertices = dict(zip(network.vertex_ids, network.vertex_direction.copy()))
    edges = {}
    for boundary_id, index, values in additions:
        chain = network.boundary(boundary_id).vertex_ids
        a, b = chain[index:index+2]
        names = tuple(name for name, _ in values)
        edges[a, b] = names
        for name, longitude in values:
            vertices[name] = F.direction(longitude, 0.)

    def inserted(chain, closed):
        out = []
        for k, a in enumerate(chain):
            out.append(a)
            if k+1 == len(chain) and not closed:
                continue
            b = chain[(k+1) % len(chain)]
            out.extend(edges.get((a, b), edges.get((b, a), ())[::-1]))
        return tuple(out)

    faces = tuple(dataclasses.replace(face, vertex_ids=inserted(face.vertex_ids, True),
                                      holes=tuple(inserted(ring, True) for ring in face.holes))
                  for face in network.faces)
    boundaries = tuple(dataclasses.replace(boundary, vertex_ids=inserted(boundary.vertex_ids, boundary.closed))
                       for boundary in network.boundaries)
    return S.build_network(network.sphere, vertices, faces, network.plates, boundaries,
                           epoch_id=network.epoch_id, time_s=network.time_s)


def carried_world(longitudes):
    values = tuple(('mid%d' % k, longitude) for k, longitude in enumerate(longitudes))
    return subdivided(J.four_north(), (('eq-n2', 0, values),))


def trench_world(east, west):
    world = J.hemispheres()
    last = len(world.boundary('trench-s2').vertex_ids)-2
    return subdivided(world, (('trench-s1', 0, (('mid-e', east),)),
                              ('trench-s2', last, (('mid-w', west),))))


class DegreeTwoTraversalTests(unittest.TestCase):
    def history(self, world, rotations, supplies, sinks, *, tilt=None, frames=None):
        if tilt is not None:
            world = S.rotate_frame(world, tilt, 'degree-two-traversal-tilted')
        state = F.crust(world)
        carrier = 'S' if 'S' in world.plate_ids else 'O'
        samples = {name: world.vertex_direction[i].copy() for i, name in enumerate(world.vertex_ids)
                   if name.startswith('mid')}
        states = []
        for k in range(CONTROL['intervals']):
            stage = rotations(k)
            if tilt is not None:
                stage = {plate: tilt.inverse().then(value).then(tilt) for plate, value in stage.items()}
            if frames is not None:
                before = F.IDENTITY if k == 0 else frames[k-1].inverse()
                stage = {plate: before.then(value).then(frames[k]) for plate, value in stage.items()}
            step = T.advance(state, T.Motion(k, k+1, stage, supplies=supplies, sinks=sinks),
                             end_time_s=(k+1)*F.MYR_S)
            J.check_state(self, step.state)
            restored = T.restored(state, {'sphere': step.record(), 'transfers': []}, step.arrays())
            self.assertEqual(restored.state_id, step.state.state_id)
            for name, point in samples.items():
                samples[name] = stage[carrier].apply(point)
                if name in restored.network.vertex_ids:
                    actual = restored.network.vertex_direction[restored.network.vertex_ids.index(name)]
                    self.assertLessEqual(float(F.angle(actual, samples[name])), F.tolerance('angular_absolute_rad'))
            state = restored
            states.append(state)
        return states

    def test_carried_ridge_strict_pass_and_landing_then_moving_continuation(self):
        rule = J.control('carried_ridge')
        for longitudes in CONTROL['carried_ridge_midpoints_deg']:
            for label, tilt, frames in (('plain', None, None), ('tilted', F.TILT, None),
                                         ('D3', None, J.d3_frames(rule))):
                with self.subTest(longitudes=longitudes, frame=label):
                    states = self.history(carried_world(longitudes), J.carried(rule['omega_deg']),
                                          J.CARRIED_SUPPLIES, J.CARRIED_SINKS, tilt=tilt, frames=frames)
                    for interval, state in enumerate(states, 1):
                        network = state.network
                        for k, longitude in enumerate(longitudes):
                            name = 'mid%d' % k
                            landing = (longitude-rule['ridge_lon'])/rule['omega_deg']
                            if landing.is_integer() and landing <= interval:
                                self.assertNotIn(name, network.vertex_ids)
                            else:
                                behind = rule['ridge_lon']+interval*rule['omega_deg'] > longitude
                                self.assertIn(name, network.boundary('eq-n4' if behind else 'eq-n2').vertex_ids)

    def test_ridge_on_trench_strict_pass_and_landing_then_moving_continuation(self):
        rule = J.control('hemispheres_slide')
        for east, west in CONTROL['trench_midpoints_deg']:
            for label, tilt, frames in (('plain', None, None), ('tilted', F.TILT, None),
                                         ('D3', None, J.d3_frames(rule))):
                with self.subTest(east=east, frame=label):
                    states = self.history(trench_world(east, west), J.sliding(rule),
                                          J.HEMISPHERE_SUPPLIES, J.HEMISPHERE_SINKS, tilt=tilt, frames=frames)
                    last = states[-1].network
                    self.assertNotIn('mid-e', last.boundary('trench-s1').vertex_ids)
                    self.assertIn('mid-w', last.boundary('trench-s2').vertex_ids)
                    if east == rule['delta_deg']-rule['gamma_deg']:
                        self.assertNotIn('mid-e', last.vertex_ids)
                    else:
                        self.assertIn('mid-e', last.boundary('trench-s2').vertex_ids)


class TransientEndpointTests(unittest.TestCase):
    def test_a_degenerate_planar_overlay_uses_exact_spherical_operands_and_the_same_budget(self):
        network = F.three_plates()
        rings = T._Shapes(network).rings(0)
        expected = float(network.face_area_m2[0])/network.sphere.radius_m**2
        with patch.object(T.shapely, 'intersection', return_value=T.shapely.LineString()):
            actual = T._overlap_sr(rings, rings, network.sphere, budget=F.budget())
            self.assertLessEqual(abs(actual-expected), F.tolerance('relative')*expected)
            with self.assertRaises(MemoryLimitError):
                T._overlap_sr(rings, rings, network.sphere, budget=WorkBudget(1024))
            with patch.object(T, '_exact_overlap_sr', side_effect=T.TransferRefused('unresolved exact operands')):
                with self.assertRaisesRegex(T.TransferRefused, 'unresolved exact operands'):
                    T._overlap_sr(rings, rings, network.sphere, budget=F.budget())

    def test_zero_opening_side_consumes_without_a_transient_birth(self):
        rule = CONTROLS['transient']
        for fraction in rule['endpoint_fractions']:
            for tilt in (None, F.TILT):
                with self.subTest(fraction=fraction, tilted=tilt is not None):
                    world = D5.world()
                    boundaries = tuple(dataclasses.replace(b, accretion_fraction=fraction)
                                       if b.boundary_id == 'ridge' else b for b in world.boundaries)
                    world = S.build_network(world.sphere, dict(zip(world.vertex_ids, world.vertex_direction)),
                                            world.faces, world.plates, boundaries,
                                            epoch_id=world.epoch_id, time_s=world.time_s)
                    if tilt is not None:
                        world = S.rotate_frame(world, tilt, 'zero-opening-d5-tilted')
                    state = F.crust(world)
                    zero_side = 'left' if fraction == 0. else 'right'
                    for k in range(rule['endpoint_intervals']):
                        initial = D5.motion()
                        stage = dict(initial.rotations)
                        if tilt is not None:
                            stage = {p: tilt.inverse().then(r).then(tilt) for p, r in stage.items()}
                        supplies = tuple(s for s in initial.supplies
                                         if (s.boundary_id, s.side) != ('ridge', zero_side))
                        motion = dataclasses.replace(initial, start_step=k, end_step=k+1, rotations=stage,
                                                     supplies=supplies)
                        try:
                            step = T.advance(state, motion, end_time_s=(k+1)*F.MYR_S)
                        except T.TransferRefused as exc:
                            exc.add_note('Endpoint-fraction continuation interval %d' % (k+1))
                            raise
                        J.check_state(self, step.state)
                        births = step.record()['births']
                        self.assertFalse(any(b['boundary_id'] == 'ridge' and b['side'] == zero_side for b in births))
                        self.assertTrue(any(b['boundary_id'] == 'ridge' and b['side'] != zero_side for b in births))
                        state = T.restored(state, {'sphere': step.record(), 'transfers': []}, step.arrays())
                        self.assertEqual(state.state_id, step.state.state_id)

    def test_unconstructed_large_spread_names_the_d5_subdivision_limit(self):
        rule = CONTROLS['junction_paths']
        rate = np.asarray(rule['junction_rate_rad'])
        for spread in rule['unsupported_large_spread_rad']:
            with self.subTest(spread=spread):
                stage = {'O': F.IDENTITY}
                for k in range(3):
                    longitude = math.radians(60+120*k)
                    stage['P%d' % k] = P.P.exponential(rate+spread*np.array((-math.sin(longitude),
                                                                           math.cos(longitude), 0.)))
                motion = dataclasses.replace(P.motion(), rotations=stage)
                with self.assertRaisesRegex(T.TransferRefused, 'D5 overriding-side subdivision.*seam reorganisation'):
                    T.advance(F.crust(P.world()), motion, end_time_s=F.MYR_S)


class TransientTraversalTests(unittest.TestCase):
    """N1: D1-b at a D5 junction is refused by name; a pass outside the triangle stays admitted."""
    rule = CONTROLS['d5_traversal']

    def history(self, fraction, segment, longitude):
        base = D5.world()
        boundaries = tuple(dataclasses.replace(b, accretion_fraction=fraction) if b.boundary_id == 'ridge' else b
                           for b in base.boundaries)
        base = S.build_network(base.sphere, dict(zip(base.vertex_ids, base.vertex_direction)), base.faces,
                               base.plates, boundaries, epoch_id=base.epoch_id, time_s=base.time_s)
        world = subdivided(base, (('trench-s1', segment, (('mid', longitude),)),))
        initial = D5.motion()
        zero = {0.: 'left', 1.: 'right'}.get(float(fraction))
        supplies = tuple(s for s in initial.supplies if (s.boundary_id, s.side) != ('ridge', zero))
        return F.crust(world), dataclasses.replace(initial, supplies=supplies)

    def test_a_pass_at_a_d5_junction_is_refused_naming_the_unconstructed_case(self):
        for case in self.rule['named_refusals']:
            with self.subTest(**{k: case[k] for k in ('fraction', 'segment', 'longitude_deg')}):
                state, motion = self.history(case['fraction'], case['segment'], case['longitude_deg'])
                with self.assertRaises(T.TransferRefused) as caught:
                    T.advance(state, motion, end_time_s=F.MYR_S)
                self.assertIn(case['message'], str(caught.exception))
                self.assertNotIn('seam reorganisation', str(caught.exception))

    def test_a_pass_outside_the_triangle_on_the_zero_opening_side_stays_admitted(self):
        for case in self.rule['still_admitted']:
            with self.subTest(**case):
                state, motion = self.history(case['fraction'], case['segment'], case['longitude_deg'])
                step = T.advance(state, motion, end_time_s=F.MYR_S)
                J.check_state(self, step.state)
                self.assertNotIn('mid', step.state.network.boundary('trench-s1').vertex_ids)
                again = T.restored(state, {'sphere': step.record(), 'transfers': []}, step.arrays())
                self.assertEqual(again.state_id, step.state.state_id)


if __name__ == '__main__':
    unittest.main()
